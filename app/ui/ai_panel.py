"""Send the structured text to the configured AI provider and show the answer."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from app.ai.base import AIResult

from . import theme
from .widgets import labeled_row


class AIPanel(QWidget):
    analyzeRequested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self.provider_label = QLabel()
        self.provider_label.setWordWrap(True)
        lay.addWidget(self.provider_label)
        self.button = QPushButton("Analyze with AI")
        self.button.setObjectName("primary")
        self.button.clicked.connect(self.analyzeRequested.emit)
        self.usage = QLabel()
        self.usage.setObjectName("muted")
        lay.addWidget(labeled_row(self.button, self.usage, "stretch"))
        self.output = QTextBrowser()
        self.output.setOpenExternalLinks(False)
        self.output.setPlaceholderText("The analysis appears here. Only the text in the Text output tab is sent, "
                                       "and only when you press the button.")
        lay.addWidget(self.output, 1)
        note = QLabel("AI analysis is reasoning, not a game-theory solver, and can be wrong. "
                      "The call-or-fold line in the local math is exact only where it says so.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        lay.addWidget(note)

    def set_provider(self, description: Optional[str], error: Optional[str] = None) -> None:
        if error:
            self.provider_label.setStyleSheet(f"color: {theme.WARN};")
            self.provider_label.setText(error)
            self.button.setEnabled(False)
        elif description:
            self.provider_label.setStyleSheet(f"color: {theme.MUTED};")
            self.provider_label.setText(f"Provider: {description}")
            self.button.setEnabled(True)
        else:
            self.provider_label.setStyleSheet(f"color: {theme.MUTED};")
            self.provider_label.setText("No AI provider selected: the app builds the text and sends nothing. "
                                        "Choose a provider in Settings to enable analysis.")
            self.button.setEnabled(False)

    def set_busy(self, busy: bool) -> None:
        self.button.setEnabled(not busy)
        self.button.setText("Analyzing..." if busy else "Analyze with AI")

    def show_result(self, result: AIResult) -> None:
        self.output.setMarkdown(result.text)
        parts = []
        if result.input_tokens is not None:
            parts.append(f"{result.input_tokens} tokens in, {result.output_tokens} out")
        if result.cached:
            parts.append("from cache, no charge")
        parts.append(result.model)
        self.usage.setText(" | ".join(parts))

    def show_error(self, message: str) -> None:
        self.output.setPlainText(message)
        self.usage.setText("")
