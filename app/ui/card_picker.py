"""Dialog to set a card: pick one of 52, mark it UNKNOWN, or remove it from the board."""
from __future__ import annotations

from typing import Iterable, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from app.state.text_format import card_name, card_symbol

from . import theme

RANKS = "AKQJT98765432"
SUITS = "shdc"


class CardPicker(QDialog):
    UNKNOWN = "UNKNOWN"
    REMOVE = "REMOVE"

    def __init__(self, parent=None, title: str = "Choose card", current: Optional[str] = None,
                 guess: Optional[str] = None, used: Iterable[str] = (), allow_remove: bool = False):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.choice: Optional[str] = None
        used = set(used)
        lay = QVBoxLayout(self)
        info = QLabel("Pick the card shown on the table. Cards already used elsewhere are disabled.")
        info.setObjectName("muted")
        lay.addWidget(info)
        grid = QGridLayout()
        grid.setSpacing(4)
        for row, s in enumerate(SUITS):
            for col, r in enumerate(RANKS):
                code = r + s
                b = QPushButton(card_symbol(code))
                b.setFixedSize(46, 40)
                b.setToolTip(card_name(code))
                color = theme.SUIT_COLORS[s]
                border = theme.ACCENT if code == current else ("#c9c9c4" if code != guess else theme.WARN)
                b.setStyleSheet(f"QPushButton {{ background: #fafaf7; color: {color}; font-size: 15px; font-weight: 700;"
                                f" border: 2px solid {border}; border-radius: 5px; padding: 0; }}"
                                f" QPushButton:hover {{ border-color: {theme.ACCENT}; }}"
                                f" QPushButton:disabled {{ background: #3a3f47; color: #6b7280; }}")
                b.setEnabled(code not in used or code == current)
                b.clicked.connect(lambda _=False, c=code: self._pick(c))
                grid.addWidget(b, row, col)
        lay.addLayout(grid)
        row = QHBoxLayout()
        if guess and guess not in used:
            acc = QPushButton(f"Accept guess {card_symbol(guess)}")
            acc.setObjectName("primary")
            acc.clicked.connect(lambda: self._pick(guess))
            row.addWidget(acc)
        unk = QPushButton("Mark UNKNOWN")
        unk.clicked.connect(lambda: self._pick(self.UNKNOWN))
        row.addWidget(unk)
        if allow_remove:
            rem = QPushButton("Remove from board")
            rem.clicked.connect(lambda: self._pick(self.REMOVE))
            row.addWidget(rem)
        row.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        lay.addLayout(row)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)

    def _pick(self, code: str) -> None:
        self.choice = code
        self.accept()
