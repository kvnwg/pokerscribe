"""Grab pixels from the screen with mss. Images stay in memory and are never uploaded."""
from __future__ import annotations

import sys
from dataclasses import dataclass

import numpy as np

from .screens import ScreenInfo, new_mss


class CaptureError(RuntimeError):
    pass


@dataclass(frozen=True)
class Region:
    """A rectangle in screen coordinates (points on macOS)."""

    left: int
    top: int
    width: int
    height: int

    def as_mss(self) -> dict:
        return {"left": int(self.left), "top": int(self.top), "width": int(self.width), "height": int(self.height)}


_NOMINAL_FLAG = 1 << 4  # kCGWindowImageNominalResolution


def _set_macos_full_resolution(enabled: bool) -> None:
    """On Retina displays mss captures at 1x by default. Asking CoreGraphics for the
    best resolution gives OCR and card recognition twice the pixels to work with."""
    if sys.platform != "darwin":
        return
    try:
        import mss.darwin as darwin
    except Exception:
        return
    if not hasattr(darwin, "IMAGE_OPTIONS"):
        return
    if enabled:
        darwin.IMAGE_OPTIONS = darwin.IMAGE_OPTIONS & ~_NOMINAL_FLAG
    else:
        darwin.IMAGE_OPTIONS = darwin.IMAGE_OPTIONS | _NOMINAL_FLAG


class ScreenGrabber:
    def __init__(self, full_resolution: bool = True):
        self.full_resolution = full_resolution

    def grab(self, region: Region) -> np.ndarray:
        """Return the region as a BGR uint8 array."""
        if region.width <= 0 or region.height <= 0:
            raise CaptureError("The capture region is empty.")
        _set_macos_full_resolution(self.full_resolution)
        try:
            with new_mss() as sct:
                shot = sct.grab(region.as_mss())
                arr = np.asarray(shot)
        except Exception as exc:  # mss raises platform specific errors
            raise CaptureError(f"Screen capture failed: {exc}") from exc
        if arr.ndim != 3 or arr.shape[2] < 3:
            raise CaptureError("Screen capture returned an unexpected image format.")
        return np.ascontiguousarray(arr[:, :, :3])

    def grab_screen(self, screen: ScreenInfo) -> np.ndarray:
        return self.grab(Region(screen.left, screen.top, screen.width, screen.height))
