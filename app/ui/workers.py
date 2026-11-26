"""Run slow work (capture, recognition, maths, AI calls) off the UI thread."""
from __future__ import annotations

import logging
import traceback
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

log = logging.getLogger(__name__)
_live: set = set()  # keeps task objects alive until their signals are delivered


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class Task(QRunnable):
    def __init__(self, fn: Callable, *args: Any, **kwargs: Any):
        super().__init__()
        self.fn, self.args, self.kwargs = fn, args, kwargs
        self.signals = _Signals()
        self.setAutoDelete(False)

    def run(self) -> None:  # executed in a worker thread
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as exc:
            log.debug("Task failed:\n%s", traceback.format_exc())
            message = str(exc) or type(exc).__name__
            self.signals.failed.emit(message)
        else:
            self.signals.done.emit(result)


def run_task(
    fn: Callable,
    *args: Any,
    on_done: Optional[Callable[[Any], None]] = None,
    on_error: Optional[Callable[[str], None]] = None,
    **kwargs: Any,
) -> Task:
    task = Task(fn, *args, **kwargs)
    _live.add(task)

    def _finish(_=None):
        _live.discard(task)

    if on_done:
        task.signals.done.connect(on_done)
    if on_error:
        task.signals.failed.connect(on_error)
    task.signals.done.connect(_finish)
    task.signals.failed.connect(_finish)
    QThreadPool.globalInstance().start(task)
    return task


def wait_for_all(timeout_ms: int = 30000) -> bool:
    """Used by tests and on shutdown."""
    return QThreadPool.globalInstance().waitForDone(timeout_ms)
