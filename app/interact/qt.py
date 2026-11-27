"""Our own Qt windows as a backend: targets are the named widgets of one window.

Clicks and keys go through QtTest, which hands the events to the widget itself: the
computer's pointer doesn't move and no other program sees them. Every call runs on the GUI
thread (the runner waits for it there), so the window stays responsive while a plan runs, and
a plan must not be waited for on the GUI thread itself: submit() it with on_done.
"""
from __future__ import annotations

from concurrent.futures import Future
from typing import Any, Callable, Dict, Optional, Tuple

from PySide6.QtCore import QObject, QPoint, Qt, QThread, Signal, Slot
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QApplication, QComboBox, QLineEdit, QSpinBox, QWidget

from .backend import Backend, BackendError
from .intents import Target

KEYS = {
    "enter": Qt.Key_Return, "return": Qt.Key_Return, "escape": Qt.Key_Escape, "esc": Qt.Key_Escape,
    "tab": Qt.Key_Tab, "space": Qt.Key_Space, "backspace": Qt.Key_Backspace, "delete": Qt.Key_Delete,
    "up": Qt.Key_Up, "down": Qt.Key_Down, "left": Qt.Key_Left, "right": Qt.Key_Right,
    "home": Qt.Key_Home, "end": Qt.Key_End, "pageup": Qt.Key_PageUp, "pagedown": Qt.Key_PageDown,
    **{f"f{n}": getattr(Qt, f"Key_F{n}") for n in range(1, 13)},
}
WIDGETS = (QAbstractButton, QLineEdit, QComboBox, QSpinBox)  # what counts as a target


def key_code(key: str) -> Qt.Key:
    k = KEYS.get(key.lower())
    if k is not None:
        return k
    if len(key) == 1:
        return Qt.Key(ord(key.upper()))
    raise BackendError(f"unknown key {key!r}")


class _GuiCaller(QObject):
    """Runs functions on the thread this object lives in (the GUI thread)."""
    call = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.call.connect(self._run, Qt.QueuedConnection)

    @Slot(object)
    def _run(self, job: Tuple["Future[Any]", Callable[[], Any]]) -> None:
        fut, fn = job
        if not fut.set_running_or_notify_cancel():
            return  # timed out and cancelled before it started: don't act late
        try:
            fut.set_result(fn())
        except BaseException as exc:
            fut.set_exception(exc)


class QtBackend(Backend):
    """The widgets of `root` that have an object name (setObjectName) and can be acted on."""

    name = "qt"
    keyboard = True

    def __init__(self, root: QWidget):
        super().__init__()
        app = QApplication.instance()
        if app is None:
            raise RuntimeError("QtBackend needs a QApplication")
        self.root = root
        self._caller = _GuiCaller()
        self._caller.moveToThread(app.thread())

    def _gui_thread(self) -> bool:
        return QThread.currentThread() is QApplication.instance().thread()

    def invoke(self, fn: Callable[[], Any]) -> "Future[Any]":
        if self._gui_thread():
            fut: "Future[Any]" = Future()
            fut.set_running_or_notify_cancel()
            try:
                fut.set_result(fn())
            except BaseException as exc:
                fut.set_exception(exc)
            return fut
        fut = Future()
        self._caller.call.emit((fut, fn))
        return fut

    def can_wait_here(self) -> bool:
        return not self._gui_thread()

    def _widget(self, name: str) -> QWidget:
        w = self.root if self.root.objectName() == name else self.root.findChild(QWidget, name)
        if w is None:
            raise BackendError(f"no widget named {name}")
        return w

    def targets(self) -> Dict[str, Target]:
        out: Dict[str, Target] = {}
        for w in self.root.findChildren(QWidget):
            name = w.objectName()
            if not name or name in out or not isinstance(w, WIDGETS) or name.startswith("qt_"):
                continue
            top_left = w.mapTo(self.root, QPoint(0, 0))
            label = w.text() if isinstance(w, (QAbstractButton, QLineEdit)) else \
                w.currentText() if isinstance(w, QComboBox) else str(w.value()) if isinstance(w, QSpinBox) else ""
            out[name] = Target(name, (top_left.x(), top_left.y(), w.width(), w.height()), label,
                               enabled=w.isEnabled(), visible=w.isVisible())
        return out

    def click(self, target: Target, point: Tuple[float, float]) -> None:
        w = self._widget(target.name)
        if not (w.isVisible() and w.isEnabled()):
            raise BackendError(f"{target.name} can't be clicked now")
        local = w.mapFrom(self.root, QPoint(int(round(point[0])), int(round(point[1]))))
        if not w.rect().contains(local):
            raise BackendError(f"the point {point} is outside {target.name}")
        QTest.mouseClick(w, Qt.LeftButton, Qt.NoModifier, local)

    def type_text(self, target: Target, text: str, clear: bool) -> None:
        w = self._widget(target.name)
        if not (w.isVisible() and w.isEnabled()):
            raise BackendError(f"{target.name} can't take typing now")
        w.setFocus(Qt.OtherFocusReason)
        if clear:
            if isinstance(w, QLineEdit):
                w.selectAll()
            elif isinstance(w, QSpinBox):
                w.lineEdit().selectAll()
            QTest.keyClick(w, Qt.Key_Backspace)
        QTest.keyClicks(w, text)

    def press_key(self, key: str, target: Optional[Target]) -> None:
        code = key_code(key)
        w = self._widget(target.name) if target is not None else (QApplication.focusWidget() or self.root)
        QTest.keyClick(w, code)

    def snapshot(self) -> Dict[str, Target]:
        """The targets again: their text, and whether they are shown and enabled."""
        return self.targets()

