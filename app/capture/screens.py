"""Enumerate the displays that can be captured."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class ScreenInfo:
    index: int  # mss monitor index (1 = first physical display)
    left: int
    top: int
    width: int
    height: int

    @property
    def label(self) -> str:
        return f"Screen {self.index}  ({self.width} x {self.height})"


def new_mss():
    """Create an mss instance, compatible with mss 9.x and 10.x."""
    import mss

    factory = getattr(mss, "MSS", None) or mss.mss
    return factory()


def list_screens() -> List[ScreenInfo]:
    """Return the physical displays. Returns an empty list if no display is reachable."""
    try:
        with new_mss() as sct:
            monitors = list(sct.monitors)
    except Exception:
        return []
    screens = []
    # monitors[0] is the union of all displays; the rest are individual displays.
    for i, mon in enumerate(monitors[1:], start=1):
        screens.append(
            ScreenInfo(
                index=i,
                left=int(mon["left"]),
                top=int(mon["top"]),
                width=int(mon["width"]),
                height=int(mon["height"]),
            )
        )
    return screens
