"""The last reads of the table, kept in memory so a misread can be saved and replayed.

Each entry is the picture of the table box plus what was read from it and the instruction
given. Nothing is written or sent anywhere until you press "Save last reads"; then it goes
to a folder on your Mac, and sharing it is up to you."""
from __future__ import annotations

import dataclasses
import json
import os
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, Optional, Tuple

import cv2
import numpy as np

README = """These are the last reads PokerScribe made before you pressed "Save last reads".

001.png, 002.png, ...  the table box as PokerScribe saw it, oldest first
reads.jsonl            one line per picture: what was read (cards, stacks, bets, pot, whose
                       turn), what the hand tracker worked out, and the instruction shown

Nothing here was sent anywhere. To get a misread fixed, drag this folder into the chat.
"""


def _plain(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _plain(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(k): _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    return obj


class ReadLog:
    def __init__(self, keep: int = 30) -> None:
        self._items: Deque[Tuple[float, bytes, Dict[str, Any]]] = deque(maxlen=keep)
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)

    def add(self, image: np.ndarray, record: Dict[str, Any]) -> None:
        """Called from the watch thread after every read that was acted on."""
        ok, png = cv2.imencode(".png", image, [cv2.IMWRITE_PNG_COMPRESSION, 1])
        if not ok:
            return
        rec = _plain(record)
        with self._lock:
            self._items.append((time.time(), png.tobytes(), rec))

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def save(self, folder: str) -> int:
        """Write every kept read to `folder` (created if needed). Returns how many."""
        with self._lock:
            items = list(self._items)
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "reads.jsonl"), "w", encoding="utf-8") as fh:
            for i, (ts, png, rec) in enumerate(items, 1):
                name = f"{i:03d}.png"
                with open(os.path.join(folder, name), "wb") as img:
                    img.write(png)
                line = {"n": i, "time": datetime.fromtimestamp(ts).isoformat(timespec="milliseconds"),
                        "image": name}
                line.update(rec)
                fh.write(json.dumps(line, default=str) + "\n")
        with open(os.path.join(folder, "README.txt"), "w", encoding="utf-8") as fh:
            fh.write(README)
        return len(items)


def default_folder(now: Optional[datetime] = None) -> str:
    now = now or datetime.now()
    return os.path.join(os.path.expanduser("~"), "Documents", "PokerScribe reads",
                        now.strftime("%Y-%m-%d %H-%M-%S"))
