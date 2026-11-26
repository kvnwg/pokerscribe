"""numpy <-> Qt image helpers."""
from __future__ import annotations

import numpy as np
from PySide6.QtGui import QImage


def bgr_to_qimage(img: np.ndarray) -> QImage:
    if img.ndim == 2:
        img = np.repeat(img[:, :, None], 3, axis=2)
    rgb = np.ascontiguousarray(img[:, :, 2::-1])
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def qimage_to_bgr(qimg: QImage) -> np.ndarray:
    qimg = qimg.convertToFormat(QImage.Format.Format_RGB888)
    w, h = qimg.width(), qimg.height()
    ptr = qimg.constBits()
    arr = np.frombuffer(ptr, dtype=np.uint8, count=qimg.bytesPerLine() * h).reshape(h, qimg.bytesPerLine())
    arr = arr[:, : w * 3].reshape(h, w, 3)
    return np.ascontiguousarray(arr[:, :, ::-1])
