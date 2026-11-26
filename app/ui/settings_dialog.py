"""API settings and recognition options. API keys go to the system keychain, never to disk."""
from __future__ import annotations

import shutil
import sys
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.ai.claude import CLAUDE_MODELS
from app.ai.registry import PROVIDERS
from app.config import Settings, app_data_dir
from app.config import secrets
from app.vision.ocr import ENGINES

from . import theme
from .widgets import labeled_row


class _KeyRow(QWidget):
    def __init__(self, provider: str, parent=None):
        super().__init__(parent)
        self.provider = provider
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setPlaceholderText("Paste a new key to store it")
        save = QPushButton("Save key")
        save.clicked.connect(self._save)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove)
        lay.addWidget(labeled_row(self.edit, save, remove))
        self.status = QLabel()
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self.refresh()

    def refresh(self) -> None:
        key, where = secrets.get_api_key(self.provider)
        if key:
            self.status.setText(f"A key is set ({where}), ending in ...{key[-4:]}.")
        else:
            env = secrets.ENV_VARS.get(self.provider, "")
            self.status.setText(f"No key stored. Save one here (system keychain) or set {env} in the environment.")

    def _save(self) -> None:
        key = self.edit.text().strip()
        if not key:
            return
        try:
            secrets.set_api_key(self.provider, key)
        except Exception as exc:
            QMessageBox.warning(self, "Could not store the key",
                                f"The system keychain is not available ({exc}). "
                                f"Set the {secrets.ENV_VARS.get(self.provider)} environment variable instead.")
            return
        self.edit.clear()
        self.refresh()

    def _remove(self) -> None:
        secrets.delete_api_key(self.provider)
        self.refresh()


class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Settings")
        self.resize(620, 560)
        lay = QVBoxLayout(self)
        tabs = QTabWidget()
        lay.addWidget(tabs)

        # AI ----------------------------------------------------------------
        ai = QWidget()
        al = QVBoxLayout(ai)
        form = QFormLayout()
        self.provider = QComboBox()
        for key, label in PROVIDERS.items():
            self.provider.addItem(label, key)
        self.provider.setCurrentIndex(max(0, self.provider.findData(settings.ai_provider)))
        form.addRow("AI provider", self.provider)
        self.max_tokens = QSpinBox()
        self.max_tokens.setRange(100, 4000)
        self.max_tokens.setSingleStep(100)
        self.max_tokens.setValue(settings.max_tokens)
        form.addRow("Max answer length (tokens)", self.max_tokens)
        al.addLayout(form)
        claude = QGroupBox("Claude")
        cf = QFormLayout(claude)
        self.claude_model = QComboBox()
        self.claude_model.setEditable(True)
        self.claude_model.addItems(CLAUDE_MODELS)
        self.claude_model.setCurrentText(settings.claude_model)
        cf.addRow("Model", self.claude_model)
        cf.addRow("API key", _KeyRow("claude"))
        tip = QLabel("Haiku is the cheapest and is enough for these short analyses. "
                     "Each analysis sends about 600 tokens of text.")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        cf.addRow(tip)
        al.addWidget(claude)
        oa = QGroupBox("OpenAI-compatible (OpenAI, OpenRouter, or a local Ollama / LM Studio server)")
        of = QFormLayout(oa)
        self.oa_url = QLineEdit(settings.openai_base_url)
        of.addRow("API address", self.oa_url)
        self.oa_model = QLineEdit(settings.openai_model)
        self.oa_model.setPlaceholderText("e.g. llama3.1 for a local Ollama server")
        of.addRow("Model", self.oa_model)
        of.addRow("API key", _KeyRow("openai_compat"))
        local = QLabel("A local server (http://localhost:11434/v1 for Ollama) needs no key, costs nothing, "
                       "and keeps even the text on this computer.")
        local.setObjectName("muted")
        local.setWordWrap(True)
        of.addRow(local)
        al.addWidget(oa)
        al.addStretch(1)
        tabs.addTab(ai, "AI provider")

        # Recognition --------------------------------------------------------
        rec = QWidget()
        rf = QFormLayout(rec)
        self.ocr = QComboBox()
        self.ocr.addItem("Automatic (best installed)", "auto")
        for name, cls in ENGINES.items():
            suffix = "" if cls.available() else "  (not installed)"
            self.ocr.addItem(cls.label + suffix, name)
        self.ocr.addItem("None (cards only)", "none")
        self.ocr.setCurrentIndex(max(0, self.ocr.findData(settings.ocr_engine)))
        rf.addRow("Text reader (OCR)", self.ocr)
        note = QLabel("All OCR engines run on this computer. RapidOCR ships with the app and is the tested "
                      "default; Apple Vision is built into macOS and faster, worth trying; Tesseract needs "
                      "'brew install tesseract' and is the least accurate.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        rf.addRow(note)
        self.threshold = QDoubleSpinBox()
        self.threshold.setRange(0.5, 0.95)
        self.threshold.setSingleStep(0.05)
        self.threshold.setDecimals(2)
        self.threshold.setValue(settings.confidence_threshold)
        rf.addRow("Confidence needed (else UNKNOWN)", self.threshold)
        self.learn = QCheckBox("Learn my deck from the cards I correct")
        self.learn.setChecked(settings.learn_from_corrections)
        rf.addRow(self.learn)
        self.exact = QCheckBox("Exact cards: check each new card shape with me once, then read it exactly")
        self.exact.setChecked(settings.confirm_new_cards)
        rf.addRow(self.exact)
        self.claude_cards = QCheckBox("Let Claude read cards it isn't sure of, instead of asking me")
        self.claude_cards.setChecked(settings.claude_reads_cards)
        self.claude_cards.setToolTip("Sends Claude a small cropped picture of just those cards (nothing else from the "
                                     "screen). Needs a Claude API key (AI tab). A card read the same way by the app "
                                     "and Claude is learned, so it's read exactly next time.")
        rf.addRow(self.claude_cards)
        note = QLabel("This is the only picture the app ever sends: a crop of the unclear cards only.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        rf.addRow(note)
        forget = QPushButton("Forget learned cards")
        forget.clicked.connect(self._forget)
        rf.addRow(forget)
        tabs.addTab(rec, "Recognition")

        # Capture and maths ----------------------------------------------
        cap = QWidget()
        kf = QFormLayout(cap)
        self.hide_window = QCheckBox("Hide this window while capturing (single-screen setups)")
        self.hide_window.setChecked(settings.hide_window_on_capture)
        kf.addRow(self.hide_window)
        self.full_res = QCheckBox("Capture at full Retina resolution (sharper text and cards)")
        self.full_res.setChecked(settings.full_resolution)
        self.full_res.setEnabled(sys.platform == "darwin")
        kf.addRow(self.full_res)
        self.math_ms = QSpinBox()
        self.math_ms.setRange(100, 5000)
        self.math_ms.setSingleStep(100)
        self.math_ms.setValue(settings.math_time_ms)
        kf.addRow("Equity calculation time (ms)", self.math_ms)
        tabs.addTab(cap, "Capture and math")

        # Send reads -------------------------------------------------------
        snd = QWidget()
        sl = QVBoxLayout(snd)
        how = QLabel(
            "Save last reads can also send the folder to a private GitHub repository, so Claude can "
            "fetch it without you dragging it into the chat. Set up once:<br>"
            "1. On github.com make a new <b>private</b> repository, e.g. <i>pokerscribe-reads</i>.<br>"
            "2. Make a fine-grained token (GitHub, Settings, Developer settings, Personal access tokens, "
            "Fine-grained tokens): only that repository, permission <b>Contents: Read and write</b>.<br>"
            "3. Write the repository as owner/name below and paste the token. Press Test.<br>"
            "The pictures show other players' names: a public repository is refused.")
        how.setWordWrap(True)
        how.setTextFormat(Qt.TextFormat.RichText)
        sl.addWidget(how)
        sf = QFormLayout()
        self.reads_repo = QLineEdit(settings.reads_repo)
        self.reads_repo.setPlaceholderText("you/pokerscribe-reads")
        sf.addRow("Repository", self.reads_repo)
        self.reads_token = _KeyRow("github_reads")
        sf.addRow("Token", self.reads_token)
        test = QPushButton("Test")
        test.clicked.connect(self._test_send)
        self.send_status = QLabel()
        self.send_status.setObjectName("muted")
        self.send_status.setWordWrap(True)
        sf.addRow(labeled_row(test), self.send_status)
        sl.addLayout(sf)
        sl.addStretch(1)
        tabs.addTab(snd, "Send reads")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    forgot = False

    def _forget(self) -> None:
        folder = app_data_dir() / "learned_templates"
        shutil.rmtree(folder, ignore_errors=True)
        self.forgot = True
        QMessageBox.information(self, "Learned cards", "Learned card templates were removed.")

    def _test_send(self) -> None:
        from app.capture.send import SendError, check_repo, github_http

        token, _ = secrets.get_api_key("github_reads")
        if not token:
            self.send_status.setText("Paste the token and press Save key first.")
            return
        repo = self.reads_repo.text().strip()
        try:
            branch = check_repo(repo, github_http(token, timeout=15))
        except SendError as exc:
            self.send_status.setText(str(exc))
            return
        self.send_status.setText(f"Ready: {repo} is private and the token can write to it (branch {branch}).")

    def apply(self) -> None:
        s = self.settings
        s.reads_repo = self.reads_repo.text().strip()
        s.ai_provider = self.provider.currentData()
        s.max_tokens = self.max_tokens.value()
        s.claude_model = self.claude_model.currentText().strip() or "claude-haiku-5-5"
        s.openai_base_url = self.oa_url.text().strip() or "https://api.openai.com/v1"
        s.openai_model = self.oa_model.text().strip()
        s.ocr_engine = self.ocr.currentData()
        s.confidence_threshold = round(self.threshold.value(), 2)
        s.learn_from_corrections = self.learn.isChecked()
        s.confirm_new_cards = self.exact.isChecked()
        s.claude_reads_cards = self.claude_cards.isChecked()
        s.hide_window_on_capture = self.hide_window.isChecked()
        s.full_resolution = self.full_res.isChecked()
        s.math_time_ms = self.math_ms.value()
