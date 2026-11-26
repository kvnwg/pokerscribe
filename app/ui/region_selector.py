"""Shows a captured screen and lets the user draw, move and resize a capture region."""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import theme

Rect = Tuple[int, int, int, int]

_CURSORS = {
    "tl": Qt.CursorShape.SizeFDiagCursor,
    "br": Qt.CursorShape.SizeFDiagCursor,
    "tr": Qt.CursorShape.SizeBDiagCursor,
    "bl": Qt.CursorShape.SizeBDiagCursor,
    "l": Qt.CursorShape.SizeHorCursor,
    "r": Qt.CursorShape.SizeHorCursor,
    "t": Qt.CursorShape.SizeVerCursor,
    "b": Qt.CursorShape.SizeVerCursor,
    "move": Qt.CursorShape.SizeAllCursor,
}


def fit_transform(img_w: int, img_h: int, area: QRectF) -> Tuple[float, float, float]:
    """Scale and offsets that fit an image inside `area` keeping its aspect ratio."""
    if img_w <= 0 or img_h <= 0 or area.width() <= 0 or area.height() <= 0:
        return 1.0, area.x(), area.y()
    scale = min(area.width() / img_w, area.height() / img_h)
    ox = area.x() + (area.width() - img_w * scale) / 2.0
    oy = area.y() + (area.height() - img_h * scale) / 2.0
    return scale, ox, oy


class RegionSelector(QWidget):
    """Drag on empty space to draw a region; drag inside to move it; drag the
    handles to resize. Arrow keys nudge (Shift = 10 px, Alt = resize)."""

    regionChanged = Signal(object)  # (x, y, w, h) in image pixels, or None

    HANDLE = 9.0
    MIN_SIZE = 12.0
    MARGIN = 8.0

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(320, 220)
        self._image: Optional[QImage] = None
        self._rect: Optional[QRectF] = None  # image coordinates
        self._mode: Optional[str] = None
        self._press: Optional[QPointF] = None
        self._rect_at_press: Optional[QRectF] = None
        self.placeholder = "Capture a screen or open a screenshot, then drag a box around the poker table."

    # ------------------------------------------------------------------ API
    def set_image(self, image: Optional[QImage]) -> None:
        self._image = image
        if image is not None and self._rect is not None:
            self._rect = self._clamped(self._rect)
        self.update()

    def has_image(self) -> bool:
        return self._image is not None

    def image_size(self) -> Tuple[int, int]:
        if self._image is None:
            return 0, 0
        return self._image.width(), self._image.height()

    def region(self) -> Optional[Rect]:
        if self._rect is None or self._image is None:
            return None
        r = self._rect
        return int(round(r.x())), int(round(r.y())), int(round(r.width())), int(round(r.height()))

    def set_region(self, rect: Optional[Rect], emit: bool = True) -> None:
        if rect is None or self._image is None:
            self._rect = None
        else:
            x, y, w, h = rect
            self._rect = self._clamped(QRectF(x, y, w, h))
        self.update()
        if emit:
            self.regionChanged.emit(self.region())

    def region_fraction(self) -> Optional[list]:
        r, (w, h) = self.region(), self.image_size()
        if r is None or not w or not h:
            return None
        return [r[0] / w, r[1] / h, r[2] / w, r[3] / h]

    def set_region_fraction(self, frac: Optional[list], emit: bool = True) -> None:
        w, h = self.image_size()
        if frac is None or not w or not h:
            self.set_region(None, emit)
            return
        fx, fy, fw, fh = frac
        self.set_region((fx * w, fy * h, fw * w, fh * h), emit)

    # ------------------------------------------------------------- geometry
    def _transform(self) -> Tuple[float, float, float]:
        w, h = self.image_size()
        area = QRectF(self.rect()).adjusted(self.MARGIN, self.MARGIN, -self.MARGIN, -self.MARGIN)
        return fit_transform(w, h, area)

    def _to_view(self, p: QPointF) -> QPointF:
        s, ox, oy = self._transform()
        return QPointF(p.x() * s + ox, p.y() * s + oy)

    def _to_image(self, p: QPointF) -> QPointF:
        s, ox, oy = self._transform()
        return QPointF((p.x() - ox) / s, (p.y() - oy) / s)

    def _view_rect(self) -> Optional[QRectF]:
        if self._rect is None:
            return None
        tl = self._to_view(self._rect.topLeft())
        br = self._to_view(self._rect.bottomRight())
        return QRectF(tl, br)

    def _image_view_rect(self) -> QRectF:
        w, h = self.image_size()
        return QRectF(self._to_view(QPointF(0, 0)), self._to_view(QPointF(w, h)))

    def _handles(self) -> Dict[str, QRectF]:
        vr = self._view_rect()
        if vr is None:
            return {}
        cx, cy = vr.center().x(), vr.center().y()
        pts = {
            "tl": (vr.left(), vr.top()),
            "t": (cx, vr.top()),
            "tr": (vr.right(), vr.top()),
            "r": (vr.right(), cy),
            "br": (vr.right(), vr.bottom()),
            "b": (cx, vr.bottom()),
            "bl": (vr.left(), vr.bottom()),
            "l": (vr.left(), cy),
        }
        hs = self.HANDLE
        return {k: QRectF(x - hs / 2, y - hs / 2, hs, hs) for k, (x, y) in pts.items()}

    def _hit(self, pos: QPointF) -> Optional[str]:
        for key, hr in self._handles().items():
            if hr.adjusted(-4, -4, 4, 4).contains(pos):
                return key
        vr = self._view_rect()
        if vr is not None and vr.contains(pos):
            return "move"
        return None

    def _clamp_point(self, p: QPointF) -> QPointF:
        w, h = self.image_size()
        return QPointF(min(max(p.x(), 0.0), float(w)), min(max(p.y(), 0.0), float(h)))

    def _clamped(self, r: QRectF) -> QRectF:
        w, h = self.image_size()
        r = r.normalized()
        left = min(max(r.left(), 0.0), float(w))
        top = min(max(r.top(), 0.0), float(h))
        right = min(max(r.right(), 0.0), float(w))
        bottom = min(max(r.bottom(), 0.0), float(h))
        return QRectF(QPointF(left, top), QPointF(right, bottom))

    # --------------------------------------------------------------- events
    def mousePressEvent(self, event) -> None:
        if self._image is None or event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        hit = self._hit(pos)
        self._press = self._clamp_point(self._to_image(pos))
        self._rect_at_press = QRectF(self._rect) if self._rect is not None else None
        if hit is None:
            self._mode = "new"
            self._rect = QRectF(self._press, self._press)
        else:
            self._mode = hit
        self.update()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        if self._mode is None:
            hit = self._hit(pos) if self._image is not None else None
            self.setCursor(QCursor(_CURSORS.get(hit, Qt.CursorShape.CrossCursor)))
            return
        cur = self._clamp_point(self._to_image(pos))
        if self._mode == "new":
            self._rect = QRectF(self._press, cur).normalized()
        elif self._mode == "move" and self._rect_at_press is not None:
            self._rect = self._moved(self._rect_at_press, cur.x() - self._press.x(), cur.y() - self._press.y())
        elif self._rect_at_press is not None:
            r = QRectF(self._rect_at_press)
            if "l" in self._mode:
                r.setLeft(cur.x())
            if "r" in self._mode:
                r.setRight(cur.x())
            if "t" in self._mode:
                r.setTop(cur.y())
            if "b" in self._mode:
                r.setBottom(cur.y())
            self._rect = self._clamped(r)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._mode is None:
            return
        if self._rect is not None and (self._rect.width() < self.MIN_SIZE or self._rect.height() < self.MIN_SIZE):
            self._rect = self._rect_at_press  # a click, not a drag: keep the old region
        self._mode = None
        self.update()
        self.regionChanged.emit(self.region())

    def keyPressEvent(self, event) -> None:
        if self._rect is None:
            return super().keyPressEvent(event)
        key = event.key()
        if key in (Qt.Key.Key_Escape, Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.set_region(None)
            return
        step = 10.0 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1.0
        dx = {Qt.Key.Key_Left: -step, Qt.Key.Key_Right: step}.get(key, 0.0)
        dy = {Qt.Key.Key_Up: -step, Qt.Key.Key_Down: step}.get(key, 0.0)
        if not dx and not dy:
            return super().keyPressEvent(event)
        if event.modifiers() & Qt.KeyboardModifier.AltModifier:
            r = QRectF(self._rect)
            r.setWidth(max(self.MIN_SIZE, r.width() + dx))
            r.setHeight(max(self.MIN_SIZE, r.height() + dy))
            self._rect = self._clamped(r)
        else:
            self._rect = self._moved(self._rect, dx, dy)
        self.update()
        self.regionChanged.emit(self.region())

    def _moved(self, r: QRectF, dx: float, dy: float) -> QRectF:
        w, h = self.image_size()
        moved = r.translated(dx, dy)
        if moved.left() < 0:
            moved.moveLeft(0)
        if moved.top() < 0:
            moved.moveTop(0)
        if moved.right() > w:
            moved.moveRight(w)
        if moved.bottom() > h:
            moved.moveBottom(h)
        return moved

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.update()

    # ---------------------------------------------------------------- paint
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(theme.BG))
        if self._image is None:
            p.setPen(QColor(theme.MUTED))
            p.drawText(self.rect().adjusted(20, 20, -20, -20), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.placeholder)
            p.end()
            return
        img_rect = self._image_view_rect()
        p.drawImage(img_rect, self._image)
        vr = self._view_rect()
        if vr is not None and vr.width() > 0 and vr.height() > 0:
            shade = QColor(0, 0, 0, 150)
            p.fillRect(QRectF(img_rect.left(), img_rect.top(), img_rect.width(), vr.top() - img_rect.top()), shade)
            p.fillRect(QRectF(img_rect.left(), vr.bottom(), img_rect.width(), img_rect.bottom() - vr.bottom()), shade)
            p.fillRect(QRectF(img_rect.left(), vr.top(), vr.left() - img_rect.left(), vr.height()), shade)
            p.fillRect(QRectF(vr.right(), vr.top(), img_rect.right() - vr.right(), vr.height()), shade)
            p.setPen(QPen(QColor(theme.ACCENT), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(vr)
            p.setPen(QPen(QColor(theme.BG), 1))
            p.setBrush(QColor(theme.ACCENT))
            for hr in self._handles().values():
                p.drawRect(hr)
            region = self.region()
            if region:
                label = f"{region[2]} x {region[3]} px"
                font = QFont(self.font())
                font.setPointSizeF(max(9.0, font.pointSizeF() - 1))
                p.setFont(font)
                tw = p.fontMetrics().horizontalAdvance(label) + 12
                th = p.fontMetrics().height() + 4
                ly = vr.top() - th - 4 if vr.top() - th - 4 > img_rect.top() else vr.top() + 4
                box = QRectF(vr.left(), ly, tw, th)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(0, 0, 0, 190))
                p.drawRoundedRect(box, 4, 4)
                p.setPen(QColor(theme.TEXT))
                p.drawText(box, Qt.AlignmentFlag.AlignCenter, label)
        p.end()
