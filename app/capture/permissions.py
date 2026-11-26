"""macOS Screen Recording permission checks (no-ops elsewhere).

Without the permission macOS still returns an image, but other apps' windows are
blank, so we check up front and explain how to grant it.
"""
from __future__ import annotations

import ctypes
import sys
from typing import Optional

_CG_PATH = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"

INSTRUCTIONS = (
    "macOS needs Screen Recording permission to see other apps.\n\n"
    "Open System Settings > Privacy & Security > Screen & System Audio Recording, "
    "turn on the app you launched PokerScribe from (Terminal, iTerm, or PokerScribe), "
    "then quit and reopen it."
)


def _core_graphics():
    return ctypes.cdll.LoadLibrary(_CG_PATH)


def has_screen_capture_access() -> Optional[bool]:
    """True/False on macOS 10.15+, None when unknown or not macOS."""
    if sys.platform != "darwin":
        return None
    try:
        fn = _core_graphics().CGPreflightScreenCaptureAccess
        fn.restype = ctypes.c_bool
        return bool(fn())
    except Exception:
        return None


def request_screen_capture_access() -> Optional[bool]:
    """Ask macOS to show its permission prompt (shown once per app)."""
    if sys.platform != "darwin":
        return None
    try:
        fn = _core_graphics().CGRequestScreenCaptureAccess
        fn.restype = ctypes.c_bool
        return bool(fn())
    except Exception:
        return None
