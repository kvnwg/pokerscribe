"""Main window.

Simple view (default): one big instruction that updates while it watches the table.
Details view: capture controls on the left, extracted information on the right."""
from __future__ import annotations

import logging
import sys
import time
from typing import List, Optional

import cv2
import numpy as np
from PySide6.QtCore import QRect, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from app import APP_NAME
from app.capture.history import ReadLog, default_folder
from app.capture.send import send_folder
from app.ai.base import AIError
from app.ai.registry import create_provider
from app.capture import CaptureError, ImageSource, ScreenGrabber, ScreenSource, list_screens, load_image_file
from app.capture import permissions
from app.config import Settings, app_data_dir
from app.poker.advice import Advice, advise
from app.poker.calculator import compute
from app.poker.ranges import make_range
from app.recognition.recognizer import RecognitionResult, TableRecognizer
from app.ai.vision import ClaudeCardReader, crop_cards
from app.config.secrets import get_api_key
from app.poker.profiles import Profiles
from app.recognition.hand import HandMemory
from app.recognition.tracker import HandTracker, TrackInfo
from app.state.model import Field, GameState
from app.state.positions import POSITION_LABELS
from app.state.text_format import card_symbol, fmt_pct, parse_text, render_text
from app.vision.card_recognizer import CardRecognizer
from app.vision.ocr import FallbackOcr

from . import theme
from .ai_panel import AIPanel
from .capture_preview import CapturePreview, Overlay
from .card_picker import CardPicker
from .correction_panel import CorrectionPanel
from .images import bgr_to_qimage
from .region_dialog import RegionDialog
from .region_selector import RegionSelector
from .settings_dialog import SettingsDialog
from .simple_view import SimpleView
from .text_panel import TextPanel
from .workers import run_task, wait_for_all

log = logging.getLogger(__name__)


def blank_out(img: np.ndarray, box: tuple) -> np.ndarray:
    """Paint over part of a capture (fractions left, top, right, bottom) with the
    capture's typical colour, so nothing there is read."""
    h, w = img.shape[:2]
    x0, y0 = max(0, int(box[0] * w)), max(0, int(box[1] * h))
    x1, y1 = min(w, int(np.ceil(box[2] * w))), min(h, int(np.ceil(box[3] * h)))
    if x1 <= x0 or y1 <= y0:
        return img
    out = img.copy()
    small = img[::8, ::8].reshape(-1, img.shape[2])
    out[y0:y1, x0:x1] = np.median(small, axis=0).astype(img.dtype)
    return out


def frame_changed(a: np.ndarray, b: np.ndarray, block: int = 6, level: float = 8.0) -> bool:
    """True when any small patch of the table changed, such as one digit of a stack.
    (An average over the whole table misses that: "$998" becoming "$994" is a tiny
    fraction of the pixels.) a and b are the table at a quarter of its size, in grey."""
    if a.shape != b.shape:
        return True
    d = cv2.absdiff(a, b).astype(np.float32)
    h, w = d.shape
    hb, wb = h // block, w // block
    if hb == 0 or wb == 0:
        return float(d.mean()) > 2.0
    patches = d[: hb * block, : wb * block].reshape(hb, block, wb, block).mean(axis=(1, 3))
    return float(patches.max()) > level


class MainWindow(QMainWindow):
    def __init__(self, settings: Optional[Settings] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.settings = settings or Settings.load()
        self.source = None  # ScreenSource | ImageSource
        self.last_capture: Optional[np.ndarray] = None
        self.result: Optional[RecognitionResult] = None
        self.state = GameState()
        self._recognizer: Optional[TableRecognizer] = None
        self._generation = 0
        self._state_version = 0
        self._busy_count = 0
        self._permission_checked = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(800)
        self._save_timer.timeout.connect(self._save_settings)
        self._math_timer = QTimer(self)
        self._math_timer.setSingleShot(True)
        self._math_timer.setInterval(350)
        self._math_timer.timeout.connect(self._run_math)
        # watch mode
        self.tracker = HandTracker()
        self._watch_timer = QTimer(self)
        self._watch_timer.timeout.connect(self._watch_tick)
        self._watch_inflight = False
        self._watch_small: Optional[np.ndarray] = None  # the table as the last read saw it
        self._watch_prev: Optional[np.ndarray] = None  # the table one tick ago
        self._watch_waits = 0
        self._bets_note = ""
        self._invested: Optional[float] = None
        self.advice: Optional[Advice] = None
        self.hand = HandMemory()  # what is known about the hand being played, from one check to the next
        self._held_advice: Optional[Advice] = None  # the instruction shown for the current spot
        self._held_key: Optional[tuple] = None
        self.read_log = ReadLog(keep=30)  # the last reads, for "Save last reads"
        self.profiles = Profiles()  # how each opponent plays, learned while watching (screen and advice only)
        self._reader: Optional[ClaudeCardReader] = None
        self._reader_key: Optional[str] = None
        self._claude_asks = 0  # pictures sent to Claude this hand
        self._watch_gen = 0  # bumped when the user confirms cards: reads started before that are stale

        self.setWindowTitle(APP_NAME)
        self.resize(1500, 940)
        self._build_toolbar()
        self._build_central()
        self._build_status()
        self.refresh_screens()
        self._update_provider()
        self._refresh_outputs()
        self.simple.set_on_top(self.settings.always_on_top)
        if self.settings.always_on_top:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.simple.show_intro(has_box=bool(self.settings.region))
        if self.settings.simple_mode:
            self.show_simple()
        else:
            self.show_details(resize=False)
        self.set_status("Ready." if self.settings.region else
                        "Ready. Press 1. Set table box to draw a box around the poker table.")

    # ------------------------------------------------------------------ UI
    def _build_toolbar(self) -> None:
        tb = QToolBar("Capture")
        tb.setMovable(False)
        self.addToolBar(tb)
        simple_btn = QPushButton("Simple view")
        simple_btn.setToolTip("Back to the one-instruction screen")
        simple_btn.clicked.connect(lambda: self.show_simple())
        tb.addWidget(simple_btn)
        tb.addSeparator()
        tb.addWidget(QLabel(" Screen "))
        self.screen_combo = QComboBox()
        self.screen_combo.setMinimumWidth(190)
        self.screen_combo.setToolTip("Display to capture")
        tb.addWidget(self.screen_combo)
        self.capture_screen_btn = QPushButton("Capture screen")
        self.capture_screen_btn.setToolTip("Grab the whole display so you can select the table region")
        self.capture_screen_btn.clicked.connect(self.capture_screen)
        tb.addWidget(self.capture_screen_btn)
        self.open_image_btn = QPushButton("Open screenshot...")
        self.open_image_btn.setToolTip("Use a saved screenshot or a frame from a recording instead of the live screen")
        self.open_image_btn.clicked.connect(lambda: self.open_image())
        tb.addWidget(self.open_image_btn)
        tb.addSeparator()
        self.capture_region_btn = QPushButton("Capture region")
        self.capture_region_btn.setObjectName("primary")
        self.capture_region_btn.setToolTip("Grab the selected region and recognize it (Ctrl/Cmd+R)")
        self.capture_region_btn.clicked.connect(self.capture_region)
        tb.addWidget(self.capture_region_btn)
        act = QAction("Capture region", self)
        act.setShortcut(QKeySequence("Ctrl+R"))
        act.triggered.connect(self.capture_region)
        self.addAction(act)
        self.overlay_check = QCheckBox("Show detections")
        self.overlay_check.setChecked(True)
        self.overlay_check.toggled.connect(lambda on: self.capture_preview.set_show_overlays(on))
        tb.addWidget(self.overlay_check)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        tb.addWidget(spacer)
        settings_btn = QPushButton("Settings")
        settings_btn.clicked.connect(self.open_settings)
        tb.addWidget(settings_btn)
        self.toolbar = tb

    def _build_central(self) -> None:
        self.region_selector = RegionSelector()
        self.region_selector.regionChanged.connect(self._on_region_changed)
        self.capture_preview = CapturePreview()
        screen_box = QGroupBox("Screen and region")
        sl = QVBoxLayout(screen_box)
        sl.setContentsMargins(6, 10, 6, 6)
        sl.addWidget(self.region_selector, 1)
        hint = QLabel("Drag to draw the region. Drag inside to move it, drag the handles to resize. "
                      "Arrow keys nudge it (Shift = 10 px, Alt = resize).")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        sl.addWidget(hint)
        preview_box = QGroupBox("Capture preview")
        pl = QVBoxLayout(preview_box)
        pl.setContentsMargins(6, 10, 6, 6)
        pl.addWidget(self.capture_preview, 1)
        left = QSplitter(Qt.Orientation.Vertical)
        left.addWidget(screen_box)
        left.addWidget(preview_box)
        left.setStretchFactor(0, 3)
        left.setStretchFactor(1, 2)

        self.correction = CorrectionPanel(self.settings.confidence_threshold)
        self.correction.set_range(self.settings.opponent_range, self.settings.custom_range)
        self.correction.stateEdited.connect(self._on_state_edited)
        self.correction.cardCorrected.connect(self._on_card_corrected)
        self.correction.rangeChanged.connect(self._on_range_changed)
        self.text_panel = TextPanel()
        self.ai_panel = AIPanel()
        self.ai_panel.analyzeRequested.connect(self.analyze)
        self.tabs = QTabWidget()
        self.tabs.setMinimumWidth(540)
        self.tabs.addTab(self.correction, "Extracted info")
        self.tabs.addTab(self.text_panel, "Text output")
        self.tabs.addTab(self.ai_panel, "AI analysis")

        main = QSplitter(Qt.Orientation.Horizontal)
        main.addWidget(left)
        main.addWidget(self.tabs)
        main.setStretchFactor(0, 5)
        main.setStretchFactor(1, 4)
        main.setSizes([820, 660])
        self.details_page = main

        self.simple = SimpleView()
        self.simple.setupRequested.connect(self.setup_table_box)
        self.simple.watchToggled.connect(self.toggle_watch)
        self.simple.readNowRequested.connect(self.read_now)
        self.simple.detailsRequested.connect(lambda: self.show_details())
        self.simple.explainRequested.connect(self.explain_from_simple)
        self.simple.saveReadsRequested.connect(self.save_reads)
        self.simple.onTopToggled.connect(self.set_on_top)
        self.simple.cardsConfirmed.connect(self.confirm_cards)
        self.simple.cardPickRequested.connect(self.pick_card)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.simple)
        self.pages.addWidget(main)
        self.setCentralWidget(self.pages)

    def _build_status(self) -> None:
        sb = self.statusBar()
        self.status_label = QLabel()
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setMaximumWidth(120)
        self.busy_bar.setMaximumHeight(10)
        self.busy_bar.hide()
        self.engine_label = QLabel()
        self.engine_label.setObjectName("muted")
        sb.addWidget(self.status_label, 1)
        sb.addPermanentWidget(self.engine_label)
        sb.addPermanentWidget(self.busy_bar)

    # -------------------------------------------------------------- status
    def set_status(self, message: str, level: str = "info") -> None:
        color = {"info": theme.MUTED, "ok": theme.ACCENT, "warn": theme.WARN, "error": theme.BAD}.get(level, theme.MUTED)
        self.status_label.setStyleSheet(f"color: {color};")
        self.status_label.setText(message)

    def _busy(self, message: str) -> None:
        self._busy_count += 1
        self.busy_bar.show()
        self.set_status(message)

    def _idle(self) -> None:
        self._busy_count = max(0, self._busy_count - 1)
        if self._busy_count == 0:
            self.busy_bar.hide()

    # ------------------------------------------------------------- screens
    def refresh_screens(self) -> None:
        self.screen_combo.clear()
        screens = list_screens()
        for s in screens:
            self.screen_combo.addItem(s.label, s)
        if not screens:
            self.screen_combo.addItem("No screen available")
            self.screen_combo.setEnabled(False)
            self.capture_screen_btn.setEnabled(False)
            return
        self.screen_combo.setEnabled(True)
        self.capture_screen_btn.setEnabled(True)
        self.screen_combo.setCurrentIndex(max(0, min(len(screens) - 1, self.settings.screen_index - 1)))

    def _check_permission(self) -> bool:
        if self._permission_checked or sys.platform != "darwin":
            return True
        self._permission_checked = True
        if permissions.has_screen_capture_access() is False:
            permissions.request_screen_capture_access()
            QMessageBox.information(self, "Screen Recording permission", permissions.INSTRUCTIONS)
            return False
        return True

    # ------------------------------------------------------------- capture
    def capture_screen(self) -> None:
        screen = self.screen_combo.currentData()
        if screen is None:
            self.set_status("No screen to capture.", "warn")
            return
        if not self._check_permission():
            return
        self.settings.screen_index = screen.index
        source = ScreenSource(screen, ScreenGrabber(full_resolution=self.settings.full_resolution))
        hide = self.settings.hide_window_on_capture
        if hide:
            self.hide()
            QApplication.processEvents()

        def done(img):
            if hide:
                self.show()
            self._idle()
            self.source = source
            self.region_selector.set_image(bgr_to_qimage(img))
            if self.settings.region:
                self.region_selector.set_region_fraction(self.settings.region, emit=False)
            h, w = img.shape[:2]
            self.set_status(f"Captured {screen.label} at {w} x {h} px. Select or adjust the table region.", "ok")

        def failed(msg):
            if hide:
                self.show()
            self._idle()
            self.set_status(msg, "error")

        def start():
            self._busy("Capturing screen...")
            run_task(source.full_image, on_done=done, on_error=failed)

        QTimer.singleShot(250, start) if hide else start()

    def open_image(self, path: Optional[str] = None) -> None:
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Open screenshot", "",
                                                  "Images (*.png *.jpg *.jpeg *.bmp *.webp *.tif *.tiff)")
        if not path:
            return
        try:
            img = load_image_file(path)
        except CaptureError as exc:
            self.set_status(str(exc), "error")
            return
        self.load_image(img, description="screenshot")

    def load_image(self, img: np.ndarray, description: str = "screenshot") -> None:
        self.source = ImageSource(img, description)
        self.region_selector.set_image(bgr_to_qimage(img))
        h, w = img.shape[:2]
        if self.settings.region:
            self.region_selector.set_region_fraction(self.settings.region, emit=False)
        self.set_status(f"Loaded a {w} x {h} px {description}. Select the table region, then Capture region.", "ok")

    def capture_region(self) -> None:
        if self.source is None:
            self.set_status("Capture a screen or open a screenshot first.", "warn")
            return
        rect = self.region_selector.region()
        if rect is None:
            w, h = self.region_selector.image_size()
            if not w:
                self.set_status("Select a region first.", "warn")
                return
            rect = (0, 0, w, h)
        if isinstance(self.source, ScreenSource) and not self._check_permission():
            return
        self._generation += 1
        gen = self._generation
        source = self.source
        hide = self.settings.hide_window_on_capture and isinstance(source, ScreenSource)
        if hide:
            self.hide()
            QApplication.processEvents()

        def work():
            t0 = time.perf_counter()
            img = source.region_image(rect)
            return self.process_capture(img, t0)

        def done(result):
            if hide:
                self.show()
            self._idle()
            if gen == self._generation:  # ignore results superseded by a newer capture
                self.on_processed(result)

        def failed(msg):
            if hide:
                self.show()
            self._idle()
            self.set_status(msg, "error")

        def start():
            self._busy("Capturing and recognizing...")
            run_task(work, on_done=done, on_error=failed)

        QTimer.singleShot(250, start) if hide else start()

    # ------------------------------------------------------- simple view
    COMPACT_SIZE = (480, 640)
    SETTLE_TICKS = 1  # wait at most this many ticks for moving cards or chips to stop

    def _set_page(self, index: int) -> None:
        # a hidden page must not force its minimum size on the window
        for i in range(self.pages.count()):
            policy = QSizePolicy.Policy.Preferred if i == index else QSizePolicy.Policy.Ignored
            self.pages.widget(i).setSizePolicy(policy, policy)
        self.pages.setCurrentIndex(index)
        self.pages.adjustSize()

    def show_simple(self, resize: bool = True) -> None:
        self._set_page(0)
        self.toolbar.hide()
        if self.settings.simple_mode is not True:
            self.settings.simple_mode = True
            self._save_timer.start()
        if resize:
            self.resize(*self.COMPACT_SIZE)

    def show_details(self, resize: bool = True) -> None:
        self._set_page(1)
        self.toolbar.show()
        if self.settings.simple_mode is not False:
            self.settings.simple_mode = False
            self._save_timer.start()
        if self.result is not None and self.last_capture is not None:
            self.capture_preview.set_image(bgr_to_qimage(self.last_capture), self._overlays(self.result))
            self.correction.set_state(self.state)
            self._refresh_outputs()
        if resize:
            w, h = 1500, 940
            scr = self.screen()
            if scr is not None:
                avail = scr.availableGeometry()
                w, h = min(w, avail.width() - 40), min(h, avail.height() - 40)
            self.resize(w, h)

    def _show_advice(self, adv: Advice) -> None:
        self.advice = adv
        self.simple.show_advice(adv, self.state, self._invested, self._bets_note)
        items = self._unclear_cards() if adv.action == "unknown" else []
        if items:
            self.simple.show_fix(items)
        else:
            self.simple.hide_fix()

    def _unclear_cards(self) -> List[tuple]:
        """Cards not confirmed or not read for sure: [(kind, index, best guess), ...]."""
        out = []
        hero_in = self.state.hero is not None and any(c.known or c.guess for c in self.state.hero_cards)
        if hero_in:
            out += [("hero", i, c.guess if isinstance(c.guess, str) else None)
                    for i, c in enumerate(self.state.hero_cards) if not c.known]
        out += [("board", i, c.guess if isinstance(c.guess, str) else None)
                for i, c in enumerate(self.state.board) if not c.known]
        return out


    def confirm_cards(self, items: list) -> None:
        """The user confirmed or picked cards: use them now, remember them for the rest of
        this hand, and learn the deck's shapes so they are read exactly next time."""
        self.correction.set_state(self.state)
        for kind, index, code in items:
            used = [c.value for c in self.state.hero_cards + self.state.board if c.known]
            if code in used:
                continue  # the same card can't be on the table twice
            self.correction.apply_card_choice(kind, index, code)  # learns it, then updates the instruction
            self.hand.confirm(kind, index, code)  # and it stays known for the rest of this hand
        self._watch_gen += 1  # a read already under way still has the old answer: drop it
        self._watch_small = None  # read the table again, now knowing this deck better
        self.simple.hide_fix()

    def confirm_card(self, kind: str, index: int, code: str) -> None:
        self.confirm_cards([(kind, index, code)])

    def pick_card(self, kind: str, index: int) -> None:
        fields = self.state.hero_cards if kind == "hero" else self.state.board
        current = fields[index] if index < len(fields) else Field()
        used = [c.value for c in self.state.hero_cards + self.state.board if c.known]
        guess = current.guess if isinstance(current.guess, str) else None
        dlg = CardPicker(self, "Which card is it?", None, guess, used)
        if dlg.exec() and dlg.choice and dlg.choice not in (CardPicker.UNKNOWN, CardPicker.REMOVE):
            self.confirm_card(kind, index, dlg.choice)


    def set_on_top(self, on: bool) -> None:
        self.settings.always_on_top = bool(on)
        self._save_timer.start()
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, bool(on))
        self.show()  # changing window flags hides the window

    def explain_from_simple(self) -> None:
        self.show_details()
        self.tabs.setCurrentWidget(self.ai_panel)
        self.analyze()

    def setup_table_box(self) -> None:
        """Grab the screen (with this window hidden) and let the user draw the table box."""
        if not self._check_permission():
            return
        screens = list_screens()
        if not screens:
            self.simple.show_warning("No screen available to capture.")
            return
        current = next((i for i, s in enumerate(screens) if s.index == self.settings.screen_index), 0)
        if self._watch_timer.isActive():
            self.toggle_watch(False)
        source = ScreenSource(screens[current], ScreenGrabber(full_resolution=self.settings.full_resolution))
        self.hide()
        QApplication.processEvents()

        def done(img):
            self.show()
            self._idle()
            self._open_region_dialog(screens, current, source, img)

        def failed(msg):
            self.show()
            self._idle()
            self.simple.show_warning(msg)

        def start():
            self._busy("Grabbing the screen...")
            run_task(source.full_image, on_done=done, on_error=failed)

        QTimer.singleShot(300, start)

    def _open_region_dialog(self, screens, current: int, source: ScreenSource, img: np.ndarray) -> None:
        sources = {screens[current].index: source}

        def regrab(screen):
            src = ScreenSource(screen, ScreenGrabber(full_resolution=self.settings.full_resolution))
            try:
                image = src.full_image()
            except CaptureError as exc:
                self.set_status(str(exc), "error")
                return None
            sources[screen.index] = src
            return image

        dlg = RegionDialog(img, self.settings.region, screens, current, regrab, self)
        if not dlg.exec():
            return
        screen = dlg.screen or screens[current]
        self.source = sources.get(screen.index, source)
        self.settings.screen_index = screen.index
        i = self.screen_combo.findText(screen.label)
        if i >= 0:
            self.screen_combo.setCurrentIndex(i)
        self.region_selector.set_image(bgr_to_qimage(dlg.image))
        self.region_selector.set_region_fraction(dlg.region_fraction())
        self._save_settings()
        self.simple.show_warning("")
        self.simple.show_intro(has_box=True)
        self.toggle_watch(True)

    # -------------------------------------------------------------- watch
    def toggle_watch(self, on: bool) -> None:
        if on:
            if not self._ensure_watch_source():
                self.simple.set_watching(False)
                return
            self.tracker.reset()
            self.hand.reset()
            self._held_advice, self._held_key = None, None
            self.profiles.reset()
            self.simple.set_hand(0)
            self._watch_small = None
            self._watch_prev = None
            self._watch_waits = 0
            self.simple.show_warning("")
            self._watch_timer.start(max(300, int(self.settings.watch_interval_ms)))
            self.simple.set_watching(True)
            self.set_status("Watching the table.", "ok")
            self._watch_tick()
        else:
            self._watch_timer.stop()
            self.simple.set_watching(False)
            self.set_status("Stopped watching.")

    def read_now(self) -> None:
        """Read the table right away, even if nothing seems to have changed."""
        if not self._watch_timer.isActive():
            self.toggle_watch(True)  # starting to watch reads at once
            return
        self._watch_small = None  # read even if the table looks the same
        self._watch_prev = None  # and don't wait for it to hold still
        self._watch_waits = self.SETTLE_TICKS
        self._watch_tick()

    def _ensure_watch_source(self) -> bool:
        if self.source is not None and self.region_selector.region() is not None:
            return True
        if not self.settings.region:
            self.simple.show_warning("First press 1. Set table box and draw a box around the poker table.")
            return False
        if not self._check_permission():
            return False
        screens = list_screens()
        if not screens:
            self.simple.show_warning("No screen available to watch.")
            return False
        screen = next((s for s in screens if s.index == self.settings.screen_index), screens[0])
        source = ScreenSource(screen, ScreenGrabber(full_resolution=self.settings.full_resolution))
        try:
            img = source.full_image()  # also measures the screen's pixel scale
        except CaptureError as exc:
            self.simple.show_warning(str(exc))
            return False
        self.source = source
        self.region_selector.set_image(bgr_to_qimage(img))
        self.region_selector.set_region_fraction(self.settings.region, emit=False)
        return self.region_selector.region() is not None

    def _watch_tick(self) -> None:
        if self._watch_inflight:
            return
        rect = self.region_selector.region()
        source = self.source
        if source is None or rect is None:
            self.toggle_watch(False)
            return
        try:
            spec = make_range(self.correction.range_key(), self.correction.custom_range.text())
        except ValueError:
            spec = make_range("medium")
        budget = min(250, self.settings.math_time_ms)  # answer fast: you may be on a clock
        gen = self._watch_gen
        own = self._own_window_in_box(rect)
        reader = self._card_reader()
        self._watch_inflight = True

        def work():
            t0 = time.perf_counter()
            img = source.region_image(rect)
            if own is not None:
                img = blank_out(img, own)  # never read our own window (its card pictures, say)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            small = cv2.resize(gray, (max(1, gray.shape[1] // 4), max(1, gray.shape[0] // 4)),
                               interpolation=cv2.INTER_AREA)
            before, self._watch_prev = self._watch_prev, small
            last = self._watch_small  # what the last read saw
            if last is not None and not frame_changed(last, small):
                return None  # nothing changed on the table, not even one number
            if before is not None and frame_changed(before, small) and self._watch_waits < self.SETTLE_TICKS:
                self._watch_waits += 1
                return None  # cards or chips still moving: read once the table is still
            self._watch_waits = 0
            self._watch_small = small
            result = self.recognizer().recognize(img)
            info = self.tracker.update(result.state)
            # same hand as the last check? Keep what it knew; a new hand starts afresh
            if self.hand.update(result.state, [r.box for r in result.board_readings], info.new_hand,
                                result.layout.hand_id):
                self._claude_asks = 0
            claude_note = self._ask_claude(reader, img, result) if reader is not None else ""
            # opponents' styles from the hands seen so far (never part of the text for an AI)
            self.profiles.update(result.state, info, self.hand.number)
            self.profiles.annotate(result.state)
            computed = compute(result.state, spec, budget)
            result.state.computed = computed
            adv = advise(result.state, computed, numbers_checked=info.valid)
            seconds = time.perf_counter() - t0
            self.read_log.add(img, {"state": result.state.to_json(), "track": info, "advice": adv.to_dict(),
                                    "hand_number": self.hand.number, "seconds": round(seconds, 3),
                                    "warnings": list(result.warnings)})
            return {"image": img, "result": result, "advice": adv, "track": info, "claude": claude_note,
                    "seconds": seconds}

        def done(payload):
            self._watch_inflight = False
            if not self._watch_timer.isActive():
                return  # stopped meanwhile
            if gen != self._watch_gen:
                self._watch_small = None  # started before the user confirmed cards: read again
                return
            if payload is None:
                self.simple.checked()
                return
            self._on_watch_result(payload)

        def failed(msg):
            self._watch_inflight = False
            self.simple.show_warning(f"Couldn't read the screen: {msg}")

        run_task(work, on_done=done, on_error=failed)

    def save_reads(self) -> None:
        """Write the last reads to a folder on this Mac, with a note on what went wrong, and send
        it to the private GitHub repository from Settings, Send reads, if one is set up."""
        items = self.read_log.snapshot()  # now: watching goes on while the note is typed
        if not items:
            self.simple.show_warning("Nothing to save yet: start watching first, then press Save last reads "
                                     "right after something goes wrong.")
            return
        note, ok = QInputDialog.getText(
            self, "Save last reads",
            "What went wrong? (optional, e.g. \"said I was re-raised, he only posted the big blind\")")
        if not ok:
            return
        folder = default_folder()
        try:
            n = self.read_log.save(folder, items=items, note=note)
        except OSError as exc:
            self.simple.show_warning(f"Couldn't save the reads: {exc}")
            return
        repo = (self.settings.reads_repo or "").strip()
        token, _ = get_api_key("github_reads")
        if not (repo and token):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
            self.simple.show_warning(f"Saved the last {n} reads to Documents/PokerScribe reads. Drag that folder "
                                     "into the chat with Claude, or set up Settings, Send reads to have them sent.")
            return
        self.simple.show_warning(f"Saved the last {n} reads. Sending them to {repo}...")

        def sent(url):
            self.simple.show_warning(f"Sent the last {n} reads to {repo}. Tell Claude \"check my saved reads\".")

        def failed(msg):
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
            self.simple.show_warning(f"Saved the last {n} reads on this Mac (Documents/PokerScribe reads), but "
                                     f"sending failed: {msg}")

        run_task(send_folder, folder, repo, token, on_done=sent, on_error=failed)

    def _on_watch_result(self, payload: dict) -> None:
        res: RecognitionResult = payload["result"]
        info: TrackInfo = payload["track"]
        self.last_capture = payload["image"]
        self.result = res
        self.state = res.state
        self._state_version += 1
        self._invested = info.hero_invested if info.valid else None
        self._bets_note = "" if info.valid or self.state.to_call.known else \
            "known from the start of the next hand (it works them out from the stacks)"
        self._show_advice(self._steady(payload["advice"], self.state))
        self._bets_note = ""
        self.simple.set_hand(self.hand.number)
        self.simple.show_warning(self._watch_warning() or payload.get("claude", ""))
        self.engine_label.setText(f"OCR: {res.ocr_engine}")
        self.set_status(f"Read the table in {payload['seconds']:.2f} s.", "ok")
        if self.pages.currentIndex() == 1:
            self.capture_preview.set_image(bgr_to_qimage(payload["image"]), self._overlays(res))
            self.correction.set_state(self.state)
            self.correction.set_math_summary(f"Instruction: {payload['advice'].headline}. "
                                             + self._math_summary(self.state.computed))
            self._refresh_outputs()

    def _spot_key(self, st: GameState) -> tuple:
        """What the decision depends on: the hand, the cards, the pot, the price and whose turn."""
        cards = lambda fs: tuple(f.value if f.known else None for f in fs)  # noqa: E731
        acts = st.available_actions.value if st.available_actions.known else None
        return (self.hand.number, tuple(sorted(c for c in cards(st.hero_cards) if c)), cards(st.board),
                round(float(st.pot.value), 1) if st.pot.known else None,
                round(float(st.to_call.value), 1) if st.to_call.known else None,
                st.hero_to_act.value if st.hero_to_act.known else None,
                # the buttons: Check turning into Call means someone bet, whatever else was read
                tuple(sorted({a.kind for a in acts})) if acts else None)

    def _steady(self, adv: Advice, st: GameState) -> Advice:
        """Keep one instruction for one spot. Another read of the same table must not change
        your move; it changes when something real does (a card, a bet, the pot, your turn).
        A read that only saw less (a value it couldn't read this time) keeps the last move."""
        key = self._spot_key(st)
        held, held_key = self._held_advice, self._held_key
        if held is not None and held_key is not None and adv.action != "unknown":
            if key == held_key:
                return held
            same_hand_board = key[:3] == held_key[:3] and key[5] == held_key[5]
            lost_only = (same_hand_board and all(key[i] in (None, held_key[i]) for i in (3, 4, 6))
                         and key != held_key)
            if lost_only:
                return held
        if held is not None and held_key is not None and adv.action == "unknown" and key[0] == held_key[0] \
                and held.action != "unknown" and key[2] == held_key[2]:
            return held  # cards it knew a moment ago just read badly once: keep the move
        self._held_advice, self._held_key = adv, key
        return adv

    def _watch_warning(self) -> str:
        if self._covers_table():
            return "PokerScribe is covering part of the table box. Move this window to the side of the table."
        return ""

    CLAUDE_ASKS_PER_HAND = 4

    def _card_reader(self) -> Optional[ClaudeCardReader]:
        """Claude as a second pair of eyes for unclear cards, when that's turned on."""
        if not self.settings.claude_reads_cards:
            return None
        key, _ = get_api_key("claude")
        if not key:
            return None
        if self._reader is None or self._reader_key != key:
            self._reader, self._reader_key = ClaudeCardReader(key), key
        return self._reader

    def _ask_claude(self, reader: ClaudeCardReader, img: np.ndarray, result: RecognitionResult) -> str:
        """Runs in the watch worker. Sends crops of just the unclear cards to Claude and
        fills in what it reads. A card the app read the same way is learned, so it's read
        exactly next time without asking anyone. Returns a note for the screen, if any."""
        st = result.state
        hero_open = [i for i, f in enumerate(st.hero_cards) if not f.known and f.guess]
        board_open = [i for i, f in enumerate(st.board) if not f.known]
        if not hero_open and not board_open or self._claude_asks >= self.CLAUDE_ASKS_PER_HAND:
            return ""
        hero_boxes = [r.box for r in result.hero_readings if r is not None] if hero_open else []
        board_boxes = [r.box for r in result.board_readings] if board_open else []
        hero_crop = crop_cards(img, hero_boxes) if hero_boxes else None
        board_crop = crop_cards(img, board_boxes) if board_boxes else None
        if hero_crop is None and board_crop is None:
            return ""
        self._claude_asks += 1
        try:
            got = reader.read(hero_crop, board_crop)
        except AIError as exc:
            return f"Claude couldn't read the cards: {exc}"
        cards = self.recognizer().cards
        taken = {f.value for f in st.hero_cards + st.board if f.known}

        def fill(kind: str, index: int, code: str, reading) -> None:
            fields = st.hero_cards if kind == "hero" else st.board
            local = fields[index].guess
            fields[index] = Field(code, 0.99, "auto")
            taken.add(code)
            self.hand.confirm(kind, index, code, Field(code, 0.99, "auto"))
            if reading is not None and reading.glyphs is not None and local == code:
                cards.learn(reading.glyphs, code)  # the app and Claude agree: learn this shape

        if hero_crop is not None:
            known = {f.value for f in st.hero_cards if f.known}
            seen = [c for c in got.hero if c]
            if len(got.hero) == 2 and known <= set(seen):
                spare = [c for c in seen if c not in known and c not in taken]
                for i in hero_open:
                    match = st.hero_cards[i].guess if st.hero_cards[i].guess in spare else (spare[0] if spare else None)
                    if match is None:
                        break
                    spare.remove(match)
                    reading = result.hero_readings[i] if i < len(result.hero_readings) else None
                    fill("hero", i, match, reading)
        if board_crop is not None and len(got.board) == len(result.board_readings) == len(st.board):
            for i in board_open:
                code = got.board[i]
                if code and code not in taken:
                    fill("board", i, code, result.board_readings[i])
        return ""

    def _own_window_in_box(self, rect) -> Optional[tuple]:
        """The part of the table box this window covers, as fractions of the box
        (left, top, right, bottom), or None."""
        if not isinstance(self.source, ScreenSource) or not self.isVisible() or rect is None:
            return None
        try:
            r = self.source.to_screen_region(rect)
        except CaptureError:
            return None
        g = self.frameGeometry()
        x0, y0 = max(r.left, g.left()), max(r.top, g.top())
        x1, y1 = min(r.left + r.width, g.left() + g.width()), min(r.top + r.height, g.top() + g.height())
        if x1 <= x0 or y1 <= y0:
            return None
        return ((x0 - r.left) / r.width, (y0 - r.top) / r.height, (x1 - r.left) / r.width, (y1 - r.top) / r.height)

    def _covers_table(self) -> bool:
        if not isinstance(self.source, ScreenSource) or not self.isVisible():
            return False
        rect = self.region_selector.region()
        if rect is None:
            return False
        try:
            r = self.source.to_screen_region(rect)
        except CaptureError:
            return False
        return QRect(r.left, r.top, r.width, r.height).intersects(self.frameGeometry())

    # ---------------------------------------------------------- recognition
    def recognizer(self) -> TableRecognizer:
        if self._recognizer is None:
            cards = CardRecognizer(app_data_dir() / "learned_templates", self.settings.confidence_threshold,
                                   require_learned=self.settings.confirm_new_cards)
            ocr = FallbackOcr(self.settings.ocr_engine) if self.settings.ocr_engine != "none" else None
            self._recognizer = TableRecognizer(cards, ocr, self.settings.confidence_threshold,
                                               self.settings.pot_includes_bets)
        return self._recognizer

    def process_capture(self, img: np.ndarray, t0: float) -> dict:
        """Runs in a worker thread: everything here is local."""
        result = self.recognizer().recognize(img)
        return {"image": img, "result": result, "seconds": time.perf_counter() - t0}

    def on_processed(self, payload: dict) -> None:
        img = payload["image"]
        self._invested = None
        self.last_capture = img
        self.result = payload["result"]
        self.state = self.result.state
        self._state_version += 1
        self.capture_preview.set_image(bgr_to_qimage(img), self._overlays(self.result))
        self.correction.set_state(self.state)
        self._refresh_outputs()
        self._math_timer.start(10)
        unknown = parse_text(self.text_panel.text).get("UNKNOWN FIELDS", "None")
        n_unknown = 0 if unknown == "None" else len(str(unknown).split(","))
        engine = self.result.ocr_engine
        self.engine_label.setText(f"OCR: {engine}")
        msg = f"Recognized in {payload['seconds']:.2f} s. {n_unknown} field(s) UNKNOWN: review the Extracted info tab."
        if self.result.warnings:
            msg += " Note: " + self.result.warnings[0]
        self.set_status(msg, "warn" if n_unknown or self.result.warnings else "ok")
        self.tabs.setCurrentWidget(self.correction)

    def _overlays(self, res: RecognitionResult) -> List[Overlay]:
        T = self.settings.confidence_threshold
        out = []
        for r in res.readings:
            color = theme.ACCENT if r.confidence >= T else theme.WARN
            out.append(Overlay(r.box, color, f"{int(r.confidence * 100)}%"))
        lay = res.layout
        if lay.pot_box is not None:
            b = lay.pot_box
            out.append(Overlay((b.x, b.y, b.w, b.h), theme.INFO, "pot"))
        by_anchor = {p.anchor: p for p in res.state.players if p.anchor}
        for s in lay.seats:
            p = by_anchor.get(s.center)
            tag = (p.position.value if p and p.position.known else "seat") + ("*" if s.is_hero else "")
            out.append(Overlay(s.box, "#9b8cff", tag))
            if s.bet_box is not None:
                b = s.bet_box
                out.append(Overlay((b.x, b.y, b.w, b.h), theme.WARN, ""))
        if lay.button_box is not None:
            out.append(Overlay(lay.button_box, "#ffffff", ""))
        for b in lay.action_boxes:
            out.append(Overlay((b.x, b.y, b.w, b.h), "#f472b6", ""))
        return out

    # ------------------------------------------------------ state changes
    def _on_state_edited(self) -> None:
        self._state_version += 1
        self.state.computed = {}
        self._refresh_outputs()
        self._math_timer.start()

    def _on_range_changed(self) -> None:
        self.settings.opponent_range = self.correction.range_key()
        self.settings.custom_range = self.correction.custom_range.text().strip()
        self._save_timer.start()
        self._on_state_edited()

    def _on_card_corrected(self, kind: str, index: int, code: str) -> None:
        if not self.settings.learn_from_corrections or self.result is None:
            return
        readings = self.result.hero_readings if kind == "hero" else self.result.board_readings
        if index < len(readings) and readings[index] is not None:
            if self.recognizer().cards.learn(readings[index].glyphs, code):
                self.set_status(f"Learned this deck's {card_symbol(code)} from your correction.", "ok")

    def _refresh_outputs(self) -> None:
        self.text_panel.set_state(self.state)
        has_cards = any(c.known for c in self.state.hero_cards)
        provider_ok = self.ai_panel.provider_label.property("ok")
        self.ai_panel.button.setEnabled(bool(provider_ok) and has_cards and not self.text_panel.problems)

    def _run_math(self) -> None:
        version = self._state_version
        snapshot = GameState.from_json(self.state.to_json())
        try:
            spec = make_range(self.correction.range_key(), self.correction.custom_range.text())
        except ValueError as exc:
            self.correction.set_math_summary(f"Range not understood: {exc}", "error")
            return
        budget = self.settings.math_time_ms

        def work():
            computed = compute(snapshot, spec, budget)
            snapshot.computed = computed
            return computed, advise(snapshot, computed)

        def done(out):
            computed, adv = out
            if version != self._state_version:
                return  # the user edited something meanwhile; a newer run is queued
            self.state.computed = computed
            self._refresh_outputs()
            self.correction.set_math_summary(f"Instruction: {adv.headline}. " + self._math_summary(computed))
            self._show_advice(adv)

        def failed(msg):
            self.correction.set_math_summary(f"Local math failed: {msg}", "error")

        self.correction.set_math_summary("Calculating...")
        run_task(work, on_done=done, on_error=failed)

    @staticmethod
    def _math_summary(c: dict) -> str:
        if not c:
            return "Needs both hero cards (and every board card) to be known."
        parts = [c.get("hand", "")]
        eqs = c.get("equity", [])
        if eqs:
            parts.append("Equity " + ", ".join(f"{fmt_pct(e['equity'])} vs {e['label']}" for e in eqs))
        if c.get("pot_odds"):
            parts.append(f"pot odds need {fmt_pct(c['pot_odds']['required_equity'])}")
        v = c.get("verdict")
        if v:
            if v["action"] == "close":
                parts.append("call or fold: too close to call")
            else:
                parts.append(f"call or fold: {v['action']}" + (" (exact)" if v["exact"] else " (pot odds only)"))
        return ". ".join(p for p in parts if p) + "."

    # ------------------------------------------------------------------ AI
    def _update_provider(self) -> None:
        try:
            provider = create_provider(self.settings)
        except AIError as exc:
            self.ai_panel.set_provider(None, str(exc))
            self.ai_panel.provider_label.setProperty("ok", False)
            self.simple.set_explain_available(False)
            return
        self.ai_panel.set_provider(provider.description if provider else None)
        self.ai_panel.provider_label.setProperty("ok", provider is not None)
        self.simple.set_explain_available(provider is not None)

    def analyze(self) -> None:
        if self.text_panel.problems:
            self.ai_panel.show_error("Not sent: " + "; ".join(self.text_panel.problems[:3]))
            return
        try:
            provider = create_provider(self.settings)
        except AIError as exc:
            self.ai_panel.show_error(str(exc))
            return
        if provider is None:
            self.ai_panel.show_error("No AI provider selected. Choose one in Settings.")
            return
        text = self.text_panel.text
        self.ai_panel.set_busy(True)
        self._busy(f"Sending the text description to {provider.name}...")

        def done(result):
            self._idle()
            self.ai_panel.set_busy(False)
            self.ai_panel.show_result(result)
            self.set_status("AI analysis received." + (" (from cache, no charge)" if result.cached else ""), "ok")

        def failed(msg):
            self._idle()
            self.ai_panel.set_busy(False)
            self.ai_panel.show_error(msg)
            self.set_status(msg, "error")

        self.tabs.setCurrentWidget(self.ai_panel)
        run_task(provider.analyze, text, on_done=done, on_error=failed)

    # ------------------------------------------------------------ settings
    def open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        accepted = dlg.exec()
        if dlg.forgot:
            self._recognizer = None  # drop the forgotten card shapes from memory too
        if not accepted:
            self._update_provider()  # keys may have been saved or removed
            return
        before = (self.settings.ocr_engine, self.settings.confidence_threshold, self.settings.confirm_new_cards)
        dlg.apply()
        self._save_settings()
        if (self.settings.ocr_engine, self.settings.confidence_threshold, self.settings.confirm_new_cards) != before:
            self._recognizer = None
            self.correction.threshold = self.settings.confidence_threshold
        self._update_provider()
        self._refresh_outputs()
        self.set_status("Settings saved.", "ok")

    def _on_region_changed(self, rect) -> None:
        self.settings.region = self.region_selector.region_fraction()
        self._save_timer.start()

    def _save_settings(self) -> None:
        try:
            self.settings.save()
        except OSError as exc:
            log.warning("Could not save settings: %s", exc)

    def closeEvent(self, event) -> None:
        self._watch_timer.stop()
        self._save_settings()
        wait_for_all(5000)
        super().closeEvent(event)


__all__ = ["MainWindow", "POSITION_LABELS"]
