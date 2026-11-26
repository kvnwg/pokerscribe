"""Capture sources: a live screen, or a screenshot image loaded from disk.

The region selector works in the pixel coordinates of `full_image()`. Each source
converts that rectangle into whatever it needs to produce fresh pixels.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from .grabber import CaptureError, Region, ScreenGrabber
from .screens import ScreenInfo

Rect = Tuple[int, int, int, int]  # x, y, w, h in full-image pixels


def clamp_rect(rect: Rect, width: int, height: int) -> Optional[Rect]:
    x, y, w, h = (int(round(v)) for v in rect)
    x0 = max(0, min(x, width))
    y0 = max(0, min(y, height))
    x1 = max(0, min(x + w, width))
    y1 = max(0, min(y + h, height))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return None
    return x0, y0, x1 - x0, y1 - y0


class CaptureSource:
    """Base class. `full_image` must be called before `region_image`."""

    description = "source"

    def full_image(self) -> np.ndarray:
        raise NotImplementedError

    def region_image(self, rect: Rect) -> np.ndarray:
        raise NotImplementedError

    @property
    def size(self) -> Tuple[int, int]:
        raise NotImplementedError


class ScreenSource(CaptureSource):
    def __init__(self, screen: ScreenInfo, grabber: Optional[ScreenGrabber] = None):
        self.screen = screen
        self.grabber = grabber or ScreenGrabber()
        self._scale_x = 1.0
        self._scale_y = 1.0
        self._size = (screen.width, screen.height)
        self.description = screen.label

    def full_image(self) -> np.ndarray:
        img = self.grabber.grab_screen(self.screen)
        h, w = img.shape[:2]
        self._scale_x = w / float(self.screen.width)
        self._scale_y = h / float(self.screen.height)
        self._size = (w, h)
        return img

    @property
    def size(self) -> Tuple[int, int]:
        return self._size

    def to_screen_region(self, rect: Rect) -> Region:
        clamped = clamp_rect(rect, *self._size)
        if clamped is None:
            raise CaptureError("The selected region is too small.")
        x, y, w, h = clamped
        return Region(
            left=self.screen.left + int(round(x / self._scale_x)),
            top=self.screen.top + int(round(y / self._scale_y)),
            width=max(1, int(round(w / self._scale_x))),
            height=max(1, int(round(h / self._scale_y))),
        )

    def region_image(self, rect: Rect) -> np.ndarray:
        return self.grabber.grab(self.to_screen_region(rect))


class ImageSource(CaptureSource):
    """A screenshot or a frame from a recording, loaded from disk or memory."""

    def __init__(self, image: np.ndarray, description: str = "image"):
        if image is None or image.ndim != 3:
            raise CaptureError("Not a colour image.")
        self._image = np.ascontiguousarray(image[:, :, :3])
        self.description = description

    def full_image(self) -> np.ndarray:
        return self._image

    @property
    def size(self) -> Tuple[int, int]:
        h, w = self._image.shape[:2]
        return w, h

    def region_image(self, rect: Rect) -> np.ndarray:
        clamped = clamp_rect(rect, *self.size)
        if clamped is None:
            raise CaptureError("The selected region is too small.")
        x, y, w, h = clamped
        return np.ascontiguousarray(self._image[y : y + h, x : x + w])


def load_image_file(path: str | Path) -> np.ndarray:
    """Load PNG/JPEG/etc. as BGR uint8. Handles non-ASCII paths."""
    import cv2

    try:
        data = np.fromfile(str(path), dtype=np.uint8)
    except OSError as exc:
        raise CaptureError(f"Could not open {Path(path).name}: {exc.strerror or exc}") from exc
    img = cv2.imdecode(data, cv2.IMREAD_COLOR) if data.size else None
    if img is None:
        raise CaptureError(f"Could not read image: {Path(path).name}")
    return img
