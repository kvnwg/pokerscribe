"""Shows the latest region capture, optionally with what the recognizer found."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import theme
from .region_selector import fit_transform


@dataclass
class Overlay:
    rect: Tuple[float, float, float, float]  # x, y, w, h in image pixels
    color: str
    label: str = ""


class CapturePreview(QWidget):
    MARGIN = 6.0

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumSize(320, 180)
        self._image: Optional[QImage] = None
        self._overlays: List[Overlay] = []
        self.show_overlays = True
        self.placeholder = "Captured region appears here."

    def set_image(self, image: Optional[QImage], overlays: Optional[List[Overlay]] = None) -> None:
        self._image = image
        self._overlays = list(overlays or [])
        self.update()

    def set_overlays(self, overlays: List[Overlay]) -> None:
        self._overlays = list(overlays)
        self.update()

    def set_show_overlays(self, show: bool) -> None:
        self.show_overlays = show
        self.update()

    def has_image(self) -> bool:
        return self._image is not None

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.fillRect(self.rect(), QColor(theme.BG))
        if self._image is None:
            p.setPen(QColor(theme.MUTED))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.placeholder)
            p.end()
            return
        area = QRectF(self.rect()).adjusted(self.MARGIN, self.MARGIN, -self.MARGIN, -self.MARGIN)
        s, ox, oy = fit_transform(self._image.width(), self._image.height(), area)
        target = QRectF(ox, oy, self._image.width() * s, self._image.height() * s)
        p.drawImage(target, self._image)
        if self.show_overlays and self._overlays:
            font = QFont(self.font())
            font.setPointSizeF(max(8.0, font.pointSizeF() - 2))
            font.setBold(True)
            p.setFont(font)
            fm = p.fontMetrics()
            for ov in self._overlays:
                x, y, w, h = ov.rect
                r = QRectF(ox + x * s, oy + y * s, w * s, h * s)
                p.setPen(QPen(QColor(ov.color), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(r)
                tw = fm.horizontalAdvance(ov.label) + 6 if ov.label else 0
                if ov.label and r.width() >= tw - 2:  # skip labels that would cover their neighbours
                    th = fm.height() + 1
                    box = QRectF(r.left(), min(target.bottom() - th, r.bottom() + 1), tw, th)
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(QColor(ov.color))
                    p.drawRect(box)
                    p.setPen(QColor("#0b0d10"))
                    p.drawText(box, Qt.AlignmentFlag.AlignCenter, ov.label)
        p.end()
