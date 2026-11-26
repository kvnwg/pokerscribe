"""Preview of the exact text that would be sent, its privacy check, and the internal JSON."""
from __future__ import annotations

import json
from typing import Optional

from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtWidgets import QFileDialog, QLabel, QPlainTextEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget

from app.state.model import GameState
from app.state.privacy import check_outgoing_text
from app.state.text_format import render_text

from . import theme
from .widgets import labeled_row


class TextPanel(QWidget):
    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.text = ""
        self.json_data: dict = {}
        self.problems: list = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        self.status = QLabel()
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        tabs = QTabWidget()
        mono = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self.text_view = QPlainTextEdit()
        self.text_view.setReadOnly(True)
        self.text_view.setFont(mono)
        self.json_view = QPlainTextEdit()
        self.json_view.setReadOnly(True)
        self.json_view.setFont(mono)
        tabs.addTab(self.text_view, "Text sent to the AI")
        tabs.addTab(self.json_view, "Internal JSON (stays on this computer)")
        lay.addWidget(tabs, 1)
        copy_text = QPushButton("Copy text")
        copy_text.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.text))
        copy_json = QPushButton("Copy JSON")
        copy_json.clicked.connect(lambda: QGuiApplication.clipboard().setText(json.dumps(self.json_data, indent=2)))
        save_json = QPushButton("Save JSON...")
        save_json.clicked.connect(self._save_json)
        lay.addWidget(labeled_row(copy_text, copy_json, save_json, "stretch"))

    def set_state(self, state: GameState) -> None:
        self.text = render_text(state)
        self.json_data = state.to_json()
        self.problems = check_outgoing_text(self.text)
        self.text_view.setPlainText(self.text)
        self.json_view.setPlainText(json.dumps(self.json_data, indent=2))
        if self.problems:
            self.status.setStyleSheet(f"color: {theme.BAD};")
            self.status.setText("Blocked by the privacy check, nothing will be sent: " + "; ".join(self.problems[:3]))
        else:
            self.status.setStyleSheet(f"color: {theme.ACCENT};")
            self.status.setText("Passes the privacy check. Only this text is sent to the AI: no screenshots, "
                                "player names, site or app names, or details about this computer.")

    def _save_json(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Save game state", "hand.json", "JSON (*.json)")
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self.json_data, fh, indent=2)
