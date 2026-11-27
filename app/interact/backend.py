"""The interface every backend implements, and the default way its calls are made."""
from __future__ import annotations

import abc
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, Dict, Optional, Tuple

from .intents import Target


class BackendError(RuntimeError):
    """The backend couldn't do what it was asked (the click missed, the widget went away)."""


class Backend(abc.ABC):
    """One program we drive. Coordinates are the backend's own (a picture's pixels, a window's
    widget coordinates). Methods are called through invoke(), never at the same time."""

    name = "backend"
    keyboard = False  # takes TypeText and PressKey

    def __init__(self) -> None:
        self._pool: Optional[ThreadPoolExecutor] = None
        self._pool_lock = threading.Lock()

    @abc.abstractmethod
    def targets(self) -> Dict[str, Target]:
        """What can be acted on now, by name."""

    @abc.abstractmethod
    def click(self, target: Target, point: Tuple[float, float]) -> None:
        """Click `point` (inside target.box). Raise BackendError when it can't."""

    def type_text(self, target: Target, text: str, clear: bool) -> None:
        raise BackendError(f"{self.name} takes no typing")

    def press_key(self, key: str, target: Optional[Target]) -> None:
        raise BackendError(f"{self.name} takes no keys")

    def snapshot(self) -> Any:
        """What Expect checks are given: whatever the backend can report about its state."""
        return None

    def invoke(self, fn: Callable[[], Any]) -> "Future[Any]":
        """Run `fn` where this backend's calls must run. By default on one thread of its own, so a
        call that hangs can be timed out by the runner; a Qt backend runs them on the GUI thread."""
        with self._pool_lock:
            if self._pool is None:
                self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"interact-{self.name}")
        return self._pool.submit(fn)

    def can_wait_here(self) -> bool:
        """False where waiting for a plan would block the very thread the backend needs."""
        return True

    def close(self) -> None:
        with self._pool_lock:
            if self._pool is not None:
                self._pool.shutdown(wait=False)
                self._pool = None
