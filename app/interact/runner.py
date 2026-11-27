"""Carry out plans on a thread of their own, check every step, log it, and stop on demand."""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
import weakref
from concurrent.futures import Future
from concurrent.futures import TimeoutError as CallTimeout
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional, Tuple

from .backend import Backend, BackendError
from .intents import Click, Expect, Plan, PressKey, Step, Target, TypeText, describe

log = logging.getLogger(__name__)


@dataclass
class Settings:
    clicks: bool = True  # clicking switched on
    keys: bool = True  # typing and keys switched on
    dry_run: bool = False  # find and check every target, log what would be done, do nothing
    call_timeout: float = 2.0  # the longest one backend call may take (seconds)
    verify_timeout: float = 2.0  # the longest to wait for a step's expected state
    poll_interval: float = 0.01  # how often the expected state is looked at meanwhile
    retries: int = 0  # times a step is tried again when its expected state doesn't show
    stop_on_failure: bool = False  # a failed plan stops the runner (as stop() does)
    log_path: Optional[str] = None  # one JSON line per step and per plan


@dataclass
class StepResult:
    index: int
    action: str
    status: str  # "done", "dry-run", "failed", "stopped"
    reason: str = ""
    target: Optional[Target] = None
    point: Optional[Tuple[float, float]] = None
    attempts: int = 0
    seconds: float = 0.0


@dataclass
class Outcome:
    label: str
    status: str  # "done", "dry-run", "skipped" (switched off), "failed", "stopped"
    reason: str = ""
    steps: List[StepResult] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status in ("done", "dry-run")


class _Halted(Exception):
    pass


class Runner:
    """One plan at a time, in the order submitted, on the runner's own thread.

    submit() returns at once with a Future; run() waits for the outcome. stop() is the
    emergency stop: plans waiting are dropped, the plan under way ends before its next step
    (or as soon as it is waiting for a state), and new plans are refused until reset().
    A backend call that doesn't return in time stops the runner too, since it may still act.
    """

    _all: "weakref.WeakSet[Runner]" = weakref.WeakSet()

    def __init__(self, backend: Backend, settings: Optional[Settings] = None):
        self.backend = backend
        self.settings = settings or Settings()
        self._queue: "queue.Queue[Optional[Tuple[Plan, Future]]]" = queue.Queue()
        self._halt = threading.Event()
        self._halt_reason = ""
        self._lock = threading.Lock()
        self._closed = False
        self._log_lock = threading.Lock()
        self._log_file = open(self.settings.log_path, "a") if self.settings.log_path else None
        self._thread = threading.Thread(target=self._loop, name="interact-runner", daemon=True)
        self._thread.start()
        Runner._all.add(self)

    # ------------------------------------------------------------ the caller's side
    def submit(self, plan: Plan, on_done: Optional[Callable[[Outcome], None]] = None) -> "Future[Outcome]":
        fut: "Future[Outcome]" = Future()
        if on_done is not None:
            fut.add_done_callback(lambda f: on_done(f.result()))
        with self._lock:
            if self._closed:
                raise RuntimeError("the runner is closed")
            if self._halt.is_set():
                fut.set_running_or_notify_cancel()
                fut.set_result(self._finish(plan, "stopped", self._halt_reason, [], time.monotonic()))
                return fut
            self._queue.put((plan, fut))
        return fut

    def run(self, plan: Plan, timeout: Optional[float] = None) -> Outcome:
        if not self.backend.can_wait_here():
            raise RuntimeError(f"waiting here would block {self.backend.name}: use submit() with on_done")
        return self.submit(plan).result(timeout)

    def stop(self, reason: str = "emergency stop") -> None:
        self._halt_all(reason, warn=True)

    def _halt_all(self, reason: str, warn: bool) -> None:
        with self._lock:
            if not self._halt.is_set():
                self._halt_reason = reason
                self._halt.set()
                if warn:
                    log.warning("interaction stopped: %s", reason)
                self._write({"event": "stop", "reason": reason})
            dropped = []
            while True:
                try:
                    item = self._queue.get_nowait()
                except queue.Empty:
                    break
                if item is None:
                    self._queue.put(None)  # keep the close() sentinel
                    break
                dropped.append(item)
        for plan, fut in dropped:
            if fut.set_running_or_notify_cancel():
                fut.set_result(self._finish(plan, "stopped", self._halt_reason, [], time.monotonic()))

    @classmethod
    def stop_all(cls, reason: str = "emergency stop") -> None:
        for r in list(cls._all):
            r.stop(reason)

    def reset(self) -> None:
        """Take plans again after a stop."""
        with self._lock:
            self._halt.clear()
            self._halt_reason = ""
            self._write({"event": "reset"})

    @property
    def stopped(self) -> bool:
        return self._halt.is_set()

    @property
    def stop_reason(self) -> str:
        return self._halt_reason

    def close(self, timeout: float = 2.0) -> None:
        self._halt_all("closed", warn=False)
        with self._lock:
            self._closed = True
            self._queue.put(None)
        self._thread.join(timeout)
        with self._log_lock:
            if self._log_file is not None:
                self._log_file.close()
                self._log_file = None
        Runner._all.discard(self)

    # ------------------------------------------------------------ the runner's thread
    def _loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                return
            plan, fut = item
            if not fut.set_running_or_notify_cancel():
                continue
            try:
                out = self._execute(plan)
            except Exception as exc:  # a bug here must not kill the thread or leave the caller waiting
                log.exception("interaction runner error")
                out = self._finish(plan, "failed", f"runner error: {exc}", [], time.monotonic())
            fut.set_result(out)

    def _execute(self, plan: Plan) -> Outcome:
        s = self.settings
        t0 = time.monotonic()
        done: List[StepResult] = []
        if self._halt.is_set():
            return self._finish(plan, "stopped", self._halt_reason, done, t0)
        kinds = {type(st.intent) for st in plan.steps}
        if Click in kinds and not s.clicks:
            return self._finish(plan, "skipped", "clicking is switched off", done, t0)
        if kinds & {TypeText, PressKey}:
            if not s.keys:
                return self._finish(plan, "skipped", "typing and keys are switched off", done, t0)
            if not self.backend.keyboard:
                return self._finish(plan, "failed", f"{self.backend.name} takes no typing or keys", done, t0)
        try:
            if plan.require is not None:
                ok, why = self._holds(plan.require)
                if not ok:
                    return self._finish(plan, "failed", f"not in the expected state ({plan.require.description}){why}",
                                        done, t0)
            for i, step in enumerate(plan.steps):
                if self._halt.is_set():
                    raise _Halted()
                r = self._step(plan, i, step)
                done.append(r)
                if r.status == "failed":
                    return self._finish(plan, "failed", f"step {i + 1}, {r.action}: {r.reason}", done, t0)
        except _Halted:
            return self._finish(plan, "stopped", self._halt_reason, done, t0)
        return self._finish(plan, "dry-run" if s.dry_run else "done", "", done, t0)

    def _step(self, plan: Plan, i: int, step: Step) -> StepResult:
        s = self.settings
        intent = step.intent
        what = describe(intent)
        t0 = time.monotonic()
        attempts = 0
        while True:
            attempts += 1
            try:
                targets = self._call(self.backend.targets)
            except BackendError as exc:
                return self._step_result(plan, i, what, "failed", f"can't see the targets: {exc}", None, None,
                                         attempts, t0)
            target: Optional[Target] = None
            name = getattr(intent, "target", None)
            if name is not None:
                target = targets.get(name)
                problem = ""
                if target is None:
                    shown = ", ".join(sorted(targets)) or "nothing"
                    problem = f"{name} is not on screen (on screen: {shown})"
                elif not target.visible:
                    problem = f"{name} is hidden"
                elif not target.enabled:
                    problem = f"{name} is switched off"
                if problem:
                    return self._step_result(plan, i, what, "failed", problem, target, None, attempts, t0)
            point = target.center if isinstance(intent, Click) and target is not None else None
            if s.dry_run:
                return self._step_result(plan, i, what, "dry-run", "", target, point, attempts, t0)
            try:
                if isinstance(intent, Click):
                    self._call(lambda: self.backend.click(target, point), acts=True)
                elif isinstance(intent, TypeText):
                    self._call(lambda: self.backend.type_text(target, intent.text, intent.clear), acts=True)
                else:
                    self._call(lambda: self.backend.press_key(intent.key, target), acts=True)
            except BackendError as exc:
                return self._step_result(plan, i, what, "failed", str(exc) or type(exc).__name__, target, point,
                                         attempts, t0)
            if step.expect is None:
                return self._step_result(plan, i, what, "done", "", target, point, attempts, t0)
            ok, why = self._holds(step.expect, wait=s.verify_timeout)
            if ok:
                return self._step_result(plan, i, what, "done", "", target, point, attempts, t0)
            if attempts > s.retries:
                reason = f"expected {step.expect.description}, not seen within {s.verify_timeout:g} s{why}"
                return self._step_result(plan, i, what, "failed", reason, target, point, attempts, t0)

    def _holds(self, expect: Expect, wait: float = 0.0) -> Tuple[bool, str]:
        """Whether the state shows, looking again every poll_interval for up to `wait` seconds."""
        deadline = time.monotonic() + wait
        why = ""
        while True:
            try:
                snap = self._call(self.backend.snapshot)
                if expect.check(snap):
                    return True, ""
                why = ""
            except _Halted:
                raise
            except Exception as exc:  # a check that can't read the snapshot hasn't seen the state
                why = f" (the check failed: {exc})"
            if time.monotonic() >= deadline:
                return False, why
            if self._halt.wait(self.settings.poll_interval):
                raise _Halted()

    def _call(self, fn: Callable[[], Any], acts: bool = False) -> Any:
        fut = self.backend.invoke(fn)
        try:
            return fut.result(timeout=self.settings.call_timeout)
        except CallTimeout:
            fut.cancel()
            late = " and may still act" if acts else ""
            self.stop(f"{self.backend.name} did not answer within {self.settings.call_timeout:g} s{late}")
            raise _Halted()
        except BackendError:
            raise
        except Exception as exc:
            raise BackendError(f"{type(exc).__name__}: {exc}") from exc

    # ------------------------------------------------------------ results and the log
    def _step_result(self, plan, i, what, status, reason, target, point, attempts, t0) -> StepResult:
        r = StepResult(i, what, status, reason, target, point, attempts, time.monotonic() - t0)
        self._write({"event": "step", "plan": plan.label, "index": i, "action": what, "status": status,
                     "reason": reason, "target": target.name if target else None,
                     "box": list(target.box) if target else None, "point": list(point) if point else None,
                     "attempts": attempts, "ms": round(1000 * r.seconds, 2), "dry_run": self.settings.dry_run})
        if status == "failed":
            log.info("interaction step failed: %s: %s", what, reason)
        return r

    def _finish(self, plan: Plan, status: str, reason: str, steps: List[StepResult], t0: float) -> Outcome:
        out = Outcome(plan.label, status, reason, steps, time.monotonic() - t0)
        self._write({"event": "plan", "plan": plan.label, "status": status, "reason": reason, "steps": len(steps),
                     "ms": round(1000 * out.seconds, 2), "dry_run": self.settings.dry_run, "meta": plan.meta})
        if status == "failed" and self.settings.stop_on_failure:
            self.stop(f"a plan failed: {reason}")
        return out

    def _write(self, record: dict) -> None:
        with self._log_lock:
            if self._log_file is None:
                return
            record = {"time": round(time.time(), 4), "backend": self.backend.name, **record}
            self._log_file.write(json.dumps(record, default=str) + "\n")
            self._log_file.flush()
