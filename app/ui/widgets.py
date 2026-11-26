"""Small reusable widgets: confidence badges, amount fields and card buttons."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from app.recognition.amounts import parse_amount
from app.state.model import Field
from app.state.text_format import card_symbol, fmt_amount

from . import theme


def badge_text(field: Field) -> str:
    if field.source == "manual":
        return "manual" if field.known else "UNKNOWN"
    if not field.known:
        return "UNKNOWN"
    if field.source == "derived":
        return f"calc {int(round(field.confidence * 100))}%"
    return f"{int(round(field.confidence * 100))}%"


def badge_tooltip(field: Field) -> str:
    if field.source == "manual":
        return "Set by you"
    if not field.known and field.guess is not None:
        g = field.guess
        shown = card_symbol(g) if isinstance(g, str) and len(g) == 2 else (fmt_amount(g) if isinstance(g, (int, float)) else str(g))
        return f"Not confident enough ({int(field.confidence * 100)}%). Best guess: {shown}. It is sent as UNKNOWN until you confirm it."
    if not field.known:
        return "Not detected. It is sent as UNKNOWN."
    return f"Detected automatically with {int(field.confidence * 100)}% confidence"


class ConfidenceBadge(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumWidth(64)
        self.set_field(Field(), 0.7)

    def set_field(self, field: Field, threshold: float) -> None:
        color = theme.confidence_color(field.confidence, field.known, threshold)
        if field.source == "manual" and field.known:
            color = theme.INFO
        self.setText(badge_text(field))
        self.setToolTip(badge_tooltip(field))
        self.setStyleSheet(f"QLabel {{ background: {color}; color: #0b0d10; border-radius: 8px; padding: 1px 8px;"
                           f" font-size: 11px; font-weight: 600; }}")


class AmountEdit(QLineEdit):
    """Empty means UNKNOWN. Accepts 1,250 / 12.5 / 1.5K / $2.50."""

    valueEdited = Signal()

    def __init__(self, parent=None, placeholder: str = "UNKNOWN"):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.setMaximumWidth(130)
        self.editingFinished.connect(self._finish)
        self._last = self.text()

    def value(self) -> Optional[float]:
        t = self.text().strip()
        if not t:
            return None
        a = parse_amount(t)
        return a.value if a else None

    def is_valid(self) -> bool:
        return not self.text().strip() or self.value() is not None

    def set_value(self, v: Optional[float]) -> None:
        self.blockSignals(True)
        self.setText("" if v is None else fmt_amount(v))
        self.blockSignals(False)
        self._last = self.text()
        self._style()

    def _style(self):
        self.setStyleSheet("" if self.is_valid() else f"QLineEdit {{ border: 1px solid {theme.BAD}; }}")

    def _finish(self):
        self._style()
        if self.text() != self._last and self.is_valid():
            self._last = self.text()
            self.valueEdited.emit()


class CardButton(QWidget):
    """A card face (or a grey '?' when UNKNOWN) with its confidence underneath."""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        self.button = QPushButton()
        self.button.setFixedSize(52, 70)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(self.clicked.emit)
        self.badge = ConfidenceBadge()
        self.badge.setMinimumWidth(52)
        lay.addWidget(self.button, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignHCenter)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_field(self, field: Field, threshold: float) -> None:
        if field.known:
            code = field.value
            color = theme.SUIT_COLORS[code[1]]
            sym = card_symbol(code)
            self.button.setText(sym[:-1] + "\n" + sym[-1])
            self.button.setStyleSheet(
                f"QPushButton {{ background: #fafaf7; color: {color}; border: 2px solid #c9c9c4; border-radius: 7px;"
                f" font-size: 20px; font-weight: 700; padding: 0; }} QPushButton:hover {{ border-color: {theme.ACCENT}; }}")
            self.button.setToolTip("Click to change this card")
        else:
            guess = f"\n{card_symbol(field.guess)}?" if isinstance(field.guess, str) and len(field.guess) == 2 else ""
            self.button.setText("?" + guess)
            self.button.setStyleSheet(
                f"QPushButton {{ background: {theme.PANEL_2}; color: {theme.WARN}; border: 2px dashed {theme.BORDER};"
                f" border-radius: 7px; font-size: 18px; font-weight: 700; padding: 0; }}"
                f" QPushButton:hover {{ border-color: {theme.ACCENT}; }}")
            self.button.setToolTip("UNKNOWN: click to set this card")
        self.badge.set_field(field, threshold)


def labeled_row(*widgets) -> QWidget:
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(6)
    for x in widgets:
        if x == "stretch":
            lay.addStretch(1)
        else:
            lay.addWidget(x)
    return w
