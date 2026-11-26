"""Application settings stored as JSON in the per-user data folder.

API keys are never stored here. They live in the macOS Keychain (see secrets.py)
or in environment variables.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Optional

from app import APP_NAME


def app_data_dir() -> Path:
    """Per-user folder for settings and learned card templates."""
    override = os.environ.get("POKERSCRIBE_HOME")
    if override:
        path = Path(override)
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    elif sys.platform.startswith("win"):
        path = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME
    else:
        path = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Settings:
    # AI provider ("none" means: build the text, never call an API)
    ai_provider: str = "none"  # none | claude | openai_compat
    claude_model: str = "claude-haiku-5-5"
    claude_reads_cards: bool = False  # send a cropped picture of unclear cards (only those) to Claude
    openai_model: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    max_tokens: int = 700

    # Recognition
    ocr_engine: str = "auto"  # auto | apple_vision | rapidocr | tesseract | none
    confidence_threshold: float = 0.70
    learn_from_corrections: bool = True
    # Exact cards: each new card shape is checked with the user once, then read exactly.
    confirm_new_cards: bool = True

    # Capture
    screen_index: int = 1
    region: Optional[list] = None  # [x, y, w, h] as fractions of the captured screen
    hide_window_on_capture: bool = False
    full_resolution: bool = True

    # Simple view and watch mode
    simple_mode: bool = True
    always_on_top: bool = False
    watch_interval_ms: int = 400  # how often the table is looked at; it's read once it holds still

    # Local math
    math_time_ms: int = 600
    opponent_range: str = "medium"
    custom_range: str = ""
    pot_includes_bets: bool = False

    @staticmethod
    def default_path() -> Path:
        return app_data_dir() / "settings.json"

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Settings":
        path = Path(path) if path else cls.default_path()
        settings = cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return settings
        if not isinstance(raw, dict):
            return settings
        for f in fields(cls):
            if f.name not in raw:
                continue
            value = raw[f.name]
            default = getattr(settings, f.name)
            if _compatible(value, default):
                setattr(settings, f.name, value)
        settings.confidence_threshold = min(0.99, max(0.3, float(settings.confidence_threshold)))
        settings.max_tokens = int(min(4000, max(100, settings.max_tokens)))
        settings.math_time_ms = int(min(5000, max(100, settings.math_time_ms)))
        if settings.watch_interval_ms in (900, 500):
            settings.watch_interval_ms = 400  # an old default: it now reads only still frames, so look more often
        settings.watch_interval_ms = int(min(5000, max(300, settings.watch_interval_ms)))
        if settings.region is not None and not _valid_region(settings.region):
            settings.region = None
        return settings

    def save(self, path: Optional[Path] = None) -> None:
        path = Path(path) if path else self.default_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
        tmp.replace(path)


def _compatible(value: Any, default: Any) -> bool:
    if default is None:
        return value is None or isinstance(value, list)
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, (int, float)) and not isinstance(default, bool):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, type(default))


def _valid_region(region: Any) -> bool:
    if not isinstance(region, list) or len(region) != 4:
        return False
    try:
        x, y, w, h = (float(v) for v in region)
    except (TypeError, ValueError):
        return False
    return 0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1
