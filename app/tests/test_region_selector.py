"""Region selection: draw, move, resize, keyboard nudge, and coordinate mapping."""
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QImage, QKeyEvent, QMouseEvent

from app.ui.region_selector import RegionSelector


def _mouse(widget, kind, x, y, buttons=Qt.MouseButton.LeftButton):
    button = Qt.MouseButton.LeftButton if kind != QEvent.Type.MouseMove else Qt.MouseButton.NoButton
    ev = QMouseEvent(kind, QPointF(x, y), QPointF(x, y), button, buttons, Qt.KeyboardModifier.NoModifier)
    {QEvent.Type.MouseButtonPress: widget.mousePressEvent,
     QEvent.Type.MouseMove: widget.mouseMoveEvent,
     QEvent.Type.MouseButtonRelease: widget.mouseReleaseEvent}[kind](ev)


def _drag(widget, x0, y0, x1, y1):
    _mouse(widget, QEvent.Type.MouseButtonPress, x0, y0)
    _mouse(widget, QEvent.Type.MouseMove, (x0 + x1) / 2, (y0 + y1) / 2)
    _mouse(widget, QEvent.Type.MouseMove, x1, y1)
    _mouse(widget, QEvent.Type.MouseButtonRelease, x1, y1)


def _selector(qapp):
    w = RegionSelector()
    w.resize(1016, 816)  # 8 px margins -> exactly 1000 x 800 drawing area
    img = QImage(2000, 1600, QImage.Format.Format_RGB888)  # displayed at scale 0.5
    img.fill(0)
    w.set_image(img)
    return w


def test_draw_region_maps_to_image_pixels(qapp):
    w = _selector(qapp)
    seen = []
    w.regionChanged.connect(seen.append)
    _drag(w, 108, 58, 508, 358)  # view coords -> image ((x-8)*2, (y-8)*2)
    assert w.region() == (200, 100, 800, 600)
    assert seen[-1] == (200, 100, 800, 600)
    assert w.region_fraction() == [0.1, 0.0625, 0.4, 0.375]


def test_move_and_resize(qapp):
    w = _selector(qapp)
    w.set_region((200, 100, 800, 600))
    # drag from inside the box: move by (+50, +25) view px = (+100, +50) image px
    _drag(w, 300, 200, 350, 225)
    assert w.region() == (300, 150, 800, 600)
    # bottom-right handle is at view ((300+800)/2+8, (150+600)/2+8) = (558, 383)
    _drag(w, 558, 383, 608, 433)
    assert w.region() == (300, 150, 900, 700)
    # left edge handle: rect is x 300..1200, y 150..850 -> view (158, 258)
    _drag(w, 158, 258, 133, 258)
    assert w.region() == (250, 150, 950, 700)


def test_click_without_drag_keeps_region(qapp):
    w = _selector(qapp)
    w.set_region((200, 100, 800, 600))
    _drag(w, 900, 700, 901, 701)  # tiny drag outside the box
    assert w.region() == (200, 100, 800, 600)


def test_region_is_clamped_to_image(qapp):
    w = _selector(qapp)
    w.set_region((1900, 1500, 500, 500))
    assert w.region() == (1900, 1500, 100, 100)
    w.set_region((200, 100, 400, 300))
    _drag(w, 200, 150, 1015, 815)  # move far beyond the bottom-right corner
    x, y, rw, rh = w.region()
    assert (rw, rh) == (400, 300) and x + rw == 2000 and y + rh == 1600


def test_keyboard_nudge_and_clear(qapp):
    w = _selector(qapp)
    w.set_region((200, 100, 400, 300))
    w.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier))
    w.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.ShiftModifier))
    assert w.region() == (201, 110, 400, 300)
    w.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.AltModifier))
    assert w.region() == (201, 110, 401, 300)
    w.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert w.region() is None
