"""The simple screen: one big instruction, one line saying why, and the key numbers."""
from __future__ import annotations

import html
import time
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.poker.advice import Advice
from app.state.model import GameState
from app.state.text_format import card_symbol, fmt_amount

from . import theme

# tone -> (background, border, headline colour)
TONE_STYLE = {
    "stop": ("#3a1418", "#ef5350", "#ff8a80"),  # FOLD
    "go": ("#0f2e1f", "#2ec27e", "#6ef0b0"),  # CALL
    "strong": ("#33250b", "#f2b33d", "#ffd27a"),  # BET / RAISE / ALL IN
    "neutral": ("#112538", "#5aa9e6", "#a6d4ff"),  # CHECK
    "idle": ("#171b21", "#2a313b", "#8d97a5"),  # WAIT
    "warn": ("#2f2608", "#f2b33d", "#f2b33d"),  # can't read something
}
SUIT_HTML = {"s": "#e7e9ec", "c": "#e7e9ec", "h": "#ff6b6b", "d": "#ff6b6b"}


def cards_html(codes) -> str:
    out = []
    for c in codes:
        if c is None:
            out.append(f'<span style="color:{theme.UNKNOWN_GREY}">?</span>')
        else:
            out.append(f'<span style="color:{SUIT_HTML[c[1]]}">{html.escape(card_symbol(c))}</span>')
    return " ".join(out)


ORDINAL = ["first", "second", "third", "fourth", "fifth"]


class SimpleView(QWidget):
    setupRequested = Signal()
    watchToggled = Signal(bool)
    readNowRequested = Signal()
    detailsRequested = Signal()
    explainRequested = Signal()
    saveReadsRequested = Signal()
    onTopToggled = Signal(bool)
    cardsConfirmed = Signal(list)  # [("hero" | "board", index, card code), ...]
    cardPickRequested = Signal(str, int)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._last_update: Optional[float] = None
        self._watching = False
        self._hand = 0  # number of the hand being followed (it counts up when a new one starts)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)

        top = QHBoxLayout()
        self.setup_btn = QPushButton("1. Set table box")
        self.setup_btn.setToolTip("Grab the screen and draw a box around the poker table")
        self.setup_btn.clicked.connect(self.setupRequested)
        self.watch_btn = QPushButton("2. Start watching")
        self.watch_btn.setObjectName("primary")
        self.watch_btn.setCheckable(True)
        self.watch_btn.setToolTip("Look at the table a few times a second and update the instruction when it changes")
        self.watch_btn.toggled.connect(self._on_watch_clicked)
        self.read_btn = QPushButton("Read now")
        self.read_btn.setToolTip("Read the table right away (starts watching if it isn't)")
        self.read_btn.clicked.connect(self.readNowRequested)
        self.details_btn = QPushButton("Details")
        self.details_btn.setToolTip("Everything that was read, corrections, text for the AI")
        self.details_btn.clicked.connect(self.detailsRequested)
        top.addWidget(self.setup_btn)
        top.addWidget(self.watch_btn, 1)
        top.addWidget(self.read_btn)
        top.addWidget(self.details_btn)
        root.addLayout(top)

        self.status = QLabel()
        self.status.setObjectName("muted")
        root.addWidget(self.status)

        self.card = QFrame()
        self.card.setObjectName("adviceCard")
        self.card.setMinimumHeight(150)
        cl = QVBoxLayout(self.card)
        cl.setContentsMargins(14, 18, 14, 18)
        cl.setSpacing(6)
        self.headline = QLabel()
        self.headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.headline.setWordWrap(True)
        self.close_tag = QLabel("CLOSE CALL: EITHER CHOICE IS FINE")
        self.close_tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.close_tag.hide()
        cl.addStretch(1)
        cl.addWidget(self.headline)
        cl.addWidget(self.close_tag)
        cl.addStretch(1)
        root.addWidget(self.card)

        self.reason = QLabel()
        self.reason.setWordWrap(True)
        self.reason.setStyleSheet("font-size: 17px; line-height: 130%;")
        self.reason.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        root.addWidget(self.reason)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setObjectName("muted")
        self.detail.setStyleSheet("font-size: 14px;")
        root.addWidget(self.detail)

        # one-click check of cards that aren't confirmed yet
        self.fix_box = QFrame()
        self.fix_box.setObjectName("fixBox")
        self.fix_box.setStyleSheet(f"QFrame#fixBox {{ background: {theme.PANEL_2}; border: 1px solid {theme.WARN}; "
                                   "border-radius: 8px; }")
        fl = QVBoxLayout(self.fix_box)
        fl.setContentsMargins(12, 10, 12, 10)
        fl.setSpacing(8)
        self.fix_label = QLabel()
        self.fix_label.setTextFormat(Qt.TextFormat.RichText)
        self.fix_label.setWordWrap(True)
        self.fix_label.setStyleSheet("background: transparent; font-size: 16px;")
        fl.addWidget(self.fix_label)
        row = QWidget()
        row.setStyleSheet("background: transparent;")
        row.setMinimumHeight(50)
        self.fix_cards = QHBoxLayout(row)
        self.fix_cards.setContentsMargins(0, 0, 0, 0)
        self.fix_cards.setSpacing(6)
        fl.addWidget(row)
        fb = QHBoxLayout()
        self.fix_yes = QPushButton("Yes, all right")
        self.fix_yes.setObjectName("primary")
        self.fix_yes.clicked.connect(self._fix_yes)
        self.fix_pick = QPushButton("No, pick the card")
        self.fix_pick.clicked.connect(self._fix_pick_single)
        fb.addWidget(self.fix_yes)
        fb.addWidget(self.fix_pick)
        fb.addStretch(1)
        fl.addLayout(fb)
        self.fix_note = QLabel()
        self.fix_note.setObjectName("muted")
        self.fix_note.setWordWrap(True)
        self.fix_note.setStyleSheet("background: transparent; font-size: 12px;")
        fl.addWidget(self.fix_note)
        self.fix_box.hide()
        self._fix_items: list = []
        root.addWidget(self.fix_box)

        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet(f"background: #2f2608; color: {theme.WARN}; border: 1px solid #6b5212; "
                                   "border-radius: 6px; padding: 8px; font-size: 13px;")
        self.warning.hide()
        root.addWidget(self.warning)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet(f"color: {theme.BORDER};")
        root.addWidget(line)
        self.facts = QLabel()
        self.facts.setTextFormat(Qt.TextFormat.RichText)
        self.facts.setWordWrap(True)
        self.facts.setStyleSheet("font-size: 15px;")
        root.addWidget(self.facts)
        root.addStretch(1)

        bottom = QHBoxLayout()
        self.on_top = QCheckBox("Keep this window on top")
        self.on_top.setToolTip("Stay visible while you click in the poker window")
        self.on_top.toggled.connect(self.onTopToggled)
        self.explain_btn = QPushButton("Why? Ask Claude")
        self.explain_btn.setToolTip("Send the text description (never the image) to your AI provider")
        self.explain_btn.clicked.connect(self.explainRequested)
        self.explain_btn.hide()
        self.save_btn = QPushButton("Save last reads")
        self.save_btn.setToolTip("Something looks wrong? Saves the last reads (pictures of the table box and what "
                                 "was read) to a folder on your Mac, with a note on what went wrong. Sent to your private "
                                 "GitHub repository for Claude only if you set up Settings, Send reads.")
        self.save_btn.clicked.connect(self.saveReadsRequested)
        bottom.addWidget(self.on_top)
        bottom.addStretch(1)
        bottom.addWidget(self.save_btn)
        bottom.addWidget(self.explain_btn)
        root.addLayout(bottom)

        self._ticker = QTimer(self)
        self._ticker.setInterval(1000)
        self._ticker.timeout.connect(self._refresh_status)
        self._ticker.start()
        self.show_intro()
        self._refresh_status()

    # ------------------------------------------------------------ public
    def show_intro(self, has_box: bool = False) -> None:
        if has_box:
            self._paint("idle", "READY", "Press Start watching. Keep the poker table visible and this window off it.")
        else:
            self._paint("idle", "SET UP",
                        "Press 1. Set table box and draw a box around the poker table. Then press 2. Start watching.")
        self.detail.setText("")
        self.facts.setText("")

    def show_advice(self, advice: Advice, state: Optional[GameState] = None, invested: Optional[float] = None,
                    bets_note: str = "") -> None:
        self._paint(advice.tone, advice.headline, advice.reason, advice.close)
        self.detail.setText(advice.detail)
        self.detail.setVisible(bool(advice.detail))
        self.facts.setText(self._facts_html(advice, state, invested, bets_note))
        self._last_update = time.time()
        self._refresh_status()

    def show_fix(self, items: list) -> None:
        """Ask about cards that aren't confirmed yet: [(kind, index, best guess or None), ...]."""
        self._fix_items = list(items)
        while self.fix_cards.count():
            w = self.fix_cards.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        last_kind = None
        for kind, index, guess in items:
            if kind != last_kind and len({k for k, _, _ in items}) > 1:
                tag = QLabel("Yours" if kind == "hero" else "Board")
                tag.setObjectName("muted")
                tag.setStyleSheet("background: transparent; padding-right: 2px;")
                self.fix_cards.addWidget(tag)
                last_kind = kind
            b = QPushButton(card_symbol(guess) if guess else "?")
            b.setFixedSize(54, 44)
            color = theme.SUIT_COLORS[guess[1]] if guess else theme.UNKNOWN_GREY
            b.setStyleSheet(f"QPushButton {{ background: #fafaf7; color: {color}; font-size: 18px; font-weight: 800;"
                            f" border: 2px solid #c9c9c4; border-radius: 6px; padding: 0; }}"
                            f" QPushButton:hover {{ border-color: {theme.ACCENT}; }}")
            b.setToolTip("Click to change this card")
            b.clicked.connect(lambda _=False, k=kind, i=index: self.cardPickRequested.emit(k, i))
            self.fix_cards.addWidget(b)
        self.fix_cards.addStretch(1)
        missing = any(g is None for _, _, g in items)
        if len(items) == 1:
            kind, index, guess = items[0]
            which = (f"your {ORDINAL[index]} card" if kind == "hero"
                     else f"the {ORDINAL[min(index, 4)]} card in the middle")
            self.fix_label.setText(f"Is {which} {cards_html([guess])}?" if guess else f"Which is {which}?")
            self.fix_yes.setText(f"Yes, {card_symbol(guess)}" if guess else "Yes")
            self.fix_pick.setVisible(True)
            self.fix_pick.setText("No, pick the card" if guess else "Pick the card")
        else:
            self.fix_label.setText("Are these cards right?")
            self.fix_yes.setText("Yes, all right")
            self.fix_pick.setVisible(False)
        self.fix_yes.setVisible(not missing)
        self.fix_note.setText("Click a card to change it. Each card shape is checked with you once; after that "
                              "it's read exactly.")
        self.card.setMinimumHeight(96)  # make room for the question
        self.fix_box.show()

    def hide_fix(self) -> None:
        self.fix_box.hide()
        self.card.setMinimumHeight(150)
        self._fix_items = []

    def _fix_yes(self) -> None:
        items = [(k, i, g) for k, i, g in self._fix_items if g]
        if items and len(items) == len(self._fix_items):
            self.cardsConfirmed.emit(items)

    def _fix_pick_single(self) -> None:
        if self._fix_items:
            kind, index, _ = self._fix_items[0]
            self.cardPickRequested.emit(kind, index)


    def show_warning(self, text: str) -> None:
        self.warning.setText(text)
        self.warning.setVisible(bool(text))

    def set_watching(self, on: bool) -> None:
        self._watching = on
        self.watch_btn.blockSignals(True)
        self.watch_btn.setChecked(on)
        self.watch_btn.blockSignals(False)
        self.watch_btn.setText("Stop watching" if on else "2. Start watching")
        self._refresh_status()

    def set_on_top(self, on: bool) -> None:
        self.on_top.blockSignals(True)
        self.on_top.setChecked(on)
        self.on_top.blockSignals(False)

    def set_explain_available(self, on: bool) -> None:
        self.explain_btn.setVisible(on)

    def set_hand(self, number: int) -> None:
        """Show which hand is being followed, so you can see it knows it's the same hand."""
        self._hand = int(number)
        self._refresh_status()

    def checked(self) -> None:
        """The table was looked at and nothing changed."""
        self._last_update = time.time()
        self._refresh_status()

    # ----------------------------------------------------------- private
    def _on_watch_clicked(self, on: bool) -> None:
        self.watchToggled.emit(on)

    def _refresh_status(self) -> None:
        if self._watching:
            dot = f'<span style="color:{theme.ACCENT}">●</span>'
            if self._last_update is None:
                self.status.setText(f"{dot} Watching the table...")
            else:
                ago = max(0, int(time.time() - self._last_update))
                when = "just now" if ago < 2 else f"{ago} s ago"
                hand = f" Hand {self._hand}." if self._hand else ""
                self.status.setText(f"{dot} Watching.{hand} Last checked {when}.")
        else:
            self.status.setText(f'<span style="color:{theme.MUTED}">●</span> Not watching.')

    def _paint(self, tone: str, headline: str, reason: str, close: bool = False) -> None:
        bg, border, fg = TONE_STYLE.get(tone, TONE_STYLE["idle"])
        self.card.setStyleSheet(f"QFrame#adviceCard {{ background: {bg}; border: 2px solid {border}; "
                                "border-radius: 14px; }")
        size = 44 if len(headline) <= 12 else 34 if len(headline) <= 20 else 26
        self.headline.setStyleSheet(f"background: transparent; color: {fg}; font-size: {size}px; "
                                    "font-weight: 800; letter-spacing: 1px;")
        self.close_tag.setStyleSheet(f"background: transparent; color: {fg}; font-size: 12px; font-weight: 600;")
        self.close_tag.setVisible(close)
        self.headline.setText(headline)
        self.reason.setText(reason)

    @staticmethod
    def _facts_html(advice: Advice, state: Optional[GameState], invested: Optional[float],
                    bets_note: str = "") -> str:
        if state is None:
            return ""
        rows = []
        hero = [c.value if c.known else None for c in state.hero_cards]
        if any(hero):
            rows.append(("Your cards", cards_html(hero)))
        board = [c.value if c.known else None for c in state.board]
        rows.append(("Board", cards_html(board) if board else '<span style="color:#8d97a5">none yet</span>'))
        if state.pot.known:
            rows.append(("Pot", fmt_amount(state.pot.value)))
        bets = []
        for p in state.opponents:
            if p.bet.known and float(p.bet.value) > 0:
                who = p.name or (str(p.position.value) if p.position.known else f"Seat {p.seat}")
                bets.append(f"{html.escape(who)} {fmt_amount(p.bet.value)}")
        if bets:
            rows.append(("Bets this round", " · ".join(bets)))
        elif bets_note:
            rows.append(("Bets", f'<span style="color:#8d97a5">{html.escape(bets_note)}</span>'))
        if state.to_call.known and float(state.to_call.value) > 0:
            rows.append(("To call", fmt_amount(state.to_call.value)))
        if invested is not None:
            rows.append(("You've put in", fmt_amount(invested)))
        cells = "".join(f'<tr><td style="color:{theme.MUTED}; padding-right:14px">{k}</td><td>{v}</td></tr>'
                        for k, v in rows)
        return f"<table>{cells}</table>"
