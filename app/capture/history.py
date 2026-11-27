"""The last reads of the table, kept in memory so a misread can be saved and replayed.

Each entry is the picture of the table box plus what was read from it and the instruction
given. Nothing is written or sent anywhere until you press "Save last reads"; then it goes
to a folder on your Mac, and to your private GitHub repository only if you set that up
(Settings, Send reads; see send.py)."""
from __future__ import annotations

import dataclasses
import json
import os
import threading
import time
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional, Tuple

import cv2
import numpy as np

README = """These are the last reads PokerScribe made before you pressed "Save last reads".

001.png, 002.png, ...  the table box as PokerScribe saw it, oldest first
reads.jsonl            one line per picture: what was read (cards, stacks, bets, pot, whose
                       turn), what the hand tracker worked out, and the instruction shown
note.txt               what you said went wrong, if you wrote anything
about.json             the PokerScribe version that made these reads

Sent to GitHub only if you set up Settings, Send reads. Otherwise drag this folder into the
chat with Claude to get the misread fixed.
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

    def snapshot(self) -> List[Tuple[float, bytes, Dict[str, Any]]]:
        """The reads kept right now. Taken when the button is pressed: watching goes on while
        you type a note, and the reads that went wrong must not scroll out meanwhile."""
        with self._lock:
            return list(self._items)

    def save(self, folder: str, items: Optional[List[Tuple[float, bytes, Dict[str, Any]]]] = None,
             note: str = "", about: Optional[Dict[str, Any]] = None) -> int:
        """Write the kept reads (or `items`, from snapshot()) to `folder` (created if needed).
        Returns how many."""
        if items is None:
            items = self.snapshot()
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
        if note.strip():
            with open(os.path.join(folder, "note.txt"), "w", encoding="utf-8") as fh:
                fh.write(note.strip() + "\n")
        with open(os.path.join(folder, "about.json"), "w", encoding="utf-8") as fh:
            json.dump(about if about is not None else app_about(), fh, indent=2)
        return len(items)


def app_about() -> Dict[str, Any]:
    """The app version and, when run from a git checkout, the commit: replaying needs to know
    which reader made the reads."""
    from app import __version__

    about: Dict[str, Any] = {"version": __version__, "saved": datetime.now().isoformat(timespec="seconds")}
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    commit = _git_head(root)
    if commit:
        about["commit"] = commit
    build = os.path.join(root, "BUILD.txt")  # written into the zip builds
    if os.path.exists(build):
        with open(build, encoding="utf-8") as fh:
            about["build"] = fh.read().strip()
    return about


def _git_head(root: str) -> Optional[str]:
    """The checked-out commit, read from .git directly (running git on a Mac without the
    developer tools pops up an install prompt)."""
    git = os.path.join(root, ".git")
    try:
        with open(os.path.join(git, "HEAD"), encoding="utf-8") as fh:
            head = fh.read().strip()
        if not head.startswith("ref: "):
            return head or None
        ref = head[5:]
        path = os.path.join(git, *ref.split("/"))
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                return fh.read().strip() or None
        with open(os.path.join(git, "packed-refs"), encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) == 2 and parts[1] == ref:
                    return parts[0]
    except OSError:
        pass
    return None


def default_folder(now: Optional[datetime] = None) -> str:
    now = now or datetime.now()
    return os.path.join(os.path.expanduser("~"), "Documents", "PokerScribe reads",
                        now.strftime("%Y-%m-%d %H-%M-%S"))
