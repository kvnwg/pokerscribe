"""Optional: let Claude read the cards the local reader isn't sure of.

This is the one part of the app that sends a picture, so it is off until you turn on
"Let Claude read cards it isn't sure of" in Settings. Even then it never sends the
table: only tight crops around the unclear cards themselves (your two cards, or the
cards in the middle), so no names, amounts, buttons, logos or anything else on the
screen leave the computer. The text analysis keeps its own rule of text only.
"""
from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

from .base import AIError
from .claude import API_URL, API_VERSION
from .http import post_json

READER_MODEL = "claude-haiku-5-5"  # the fastest: a few clean card pictures are an easy read
CARD = re.compile(r"^(10|[2-9TJQKA])([shdc])$", re.I)
MAX_SIDE = 900  # px: cards stay sharp, pictures stay small

SYSTEM = ("You read playing cards from pictures of an online card game. Answer with JSON only. "
          "Never guess: use null for any card you can't read with certainty.")


@dataclass
class CardsRead:
    hero: List[Optional[str]] = field(default_factory=list)  # left to right
    board: List[Optional[str]] = field(default_factory=list)  # left to right
    model: str = ""


def crop_cards(img: np.ndarray, boxes: Sequence[Tuple[int, int, int, int]], margin: float = 0.06) -> Optional[np.ndarray]:
    """The smallest picture holding these cards (and only a sliver around them)."""
    if not boxes:
        return None
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    pad = int(margin * max(b[3] for b in boxes))
    h, w = img.shape[:2]
    x0, y0, x1, y1 = max(0, x0 - pad), max(0, y0 - pad), min(w, x1 + pad), min(h, y1 + pad)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    crop = img[y0:y1, x0:x1]
    scale = MAX_SIDE / float(max(crop.shape[:2]))
    if scale < 1.0:
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return crop


def _png_b64(img: np.ndarray) -> str:
    ok, enc = cv2.imencode(".png", img)
    if not ok:
        raise AIError("Couldn't prepare the card picture.")
    return base64.b64encode(enc.tobytes()).decode("ascii")


def normalize(code) -> Optional[str]:
    if not isinstance(code, str):
        return None
    m = CARD.match(code.strip().replace(" ", ""))
    if not m:
        return None
    rank = "T" if m.group(1) == "10" else m.group(1).upper()
    return rank + m.group(2).lower()


def parse(text: str) -> Tuple[List[Optional[str]], List[Optional[str]]]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise AIError("Claude's card reading wasn't in the expected form.")
    try:
        data = json.loads(m.group(0))
    except ValueError:
        raise AIError("Claude's card reading wasn't in the expected form.") from None
    hero = [normalize(c) for c in (data.get("hero") or [])][:2]
    board = [normalize(c) for c in (data.get("board") or [])][:5]
    return hero, board


class ClaudeCardReader:
    def __init__(self, api_key: str, model: str = READER_MODEL, api_url: str = API_URL, timeout: float = 25.0):
        if not api_key:
            raise AIError("Letting Claude read cards needs a Claude API key. Add one in Settings.")
        self._key = api_key
        self.model = model
        self.api_url = api_url
        self.timeout = timeout

    def read(self, hero_crop: Optional[np.ndarray], board_crop: Optional[np.ndarray]) -> CardsRead:
        """Send the crops that are given (one or both) and get the cards back."""
        content = []
        asks = []
        if hero_crop is not None:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                        "data": _png_b64(hero_crop)}})
            asks.append(f"Picture {len(asks) + 1} shows the player's own two cards, fanned and overlapping. "
                        'Put them in "hero", left card first.')
        if board_crop is not None:
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                        "data": _png_b64(board_crop)}})
            asks.append(f"Picture {len(asks) + 1} shows the face-up cards in the middle of the table. "
                        'Put them in "board", left to right.')
        if not content:
            return CardsRead(model=self.model)
        content.append({"type": "text", "text": " ".join(asks) + (
            " Write each card as rank then suit: rank 2-9, T (ten), J, Q, K or A; suit s (spades), h (hearts), "
            "d (diamonds) or c (clubs). Example: {\"hero\": [\"Qd\", \"Th\"], \"board\": [\"2h\", \"6c\", \"Tc\"]}. "
            "Leave out a list whose picture wasn't sent. Use null for a card you can't read for sure, and leave "
            "out face-down cards.")})
        payload = {"model": self.model, "max_tokens": 120, "system": SYSTEM,
                   "messages": [{"role": "user", "content": content}]}
        data = post_json(self.api_url, payload, {"x-api-key": self._key, "anthropic-version": API_VERSION},
                         self.timeout)
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        hero, board = parse(text)
        return CardsRead(hero, board, data.get("model", self.model))
