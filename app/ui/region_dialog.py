"""Draw the table box on a fresh screenshot (simple view setup)."""
from __future__ import annotations

from typing import Callable, List, Optional

import numpy as np
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app.capture import ScreenInfo

from .images import bgr_to_qimage
from .region_selector import RegionSelector


class RegionDialog(QDialog):
    def __init__(self, image: np.ndarray, region: Optional[list], screens: List[ScreenInfo], current: int,
                 regrab: Optional[Callable[[ScreenInfo], Optional[np.ndarray]]] = None,
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Set the table box")
        self._regrab = regrab
        self.image = image
        self.screen: Optional[ScreenInfo] = screens[current] if screens and 0 <= current < len(screens) else None
        root = QVBoxLayout(self)
        tip = QLabel("<b>Drag a box around the poker table</b>: the felt, the cards, the players and the "
                     "Fold/Call/Raise buttons. Leave out everything else, including the PokerScribe window.")
        tip.setWordWrap(True)
        root.addWidget(tip)
        if len(screens) > 1:
            row = QHBoxLayout()
            row.addWidget(QLabel("Screen"))
            self.screen_combo = QComboBox()
            for s in screens:
                self.screen_combo.addItem(s.label, s)
            self.screen_combo.setCurrentIndex(max(0, current))
            self.screen_combo.currentIndexChanged.connect(self._screen_changed)
            row.addWidget(self.screen_combo)
            row.addStretch(1)
            root.addLayout(row)
        self.selector = RegionSelector()
        self.selector.set_image(bgr_to_qimage(image))
        if region:
            self.selector.set_region_fraction(region, emit=False)
        self.selector.regionChanged.connect(self._update_ok)
        root.addWidget(self.selector, 1)
        self.buttons = QDialogButtonBox()
        self.ok = self.buttons.addButton("Use this box", QDialogButtonBox.ButtonRole.AcceptRole)
        self.ok.setObjectName("primary")
        self.buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        root.addWidget(self.buttons)
        self._update_ok()
        if parent is not None and parent.screen() is not None:
            avail = parent.screen().availableGeometry()
            self.resize(int(avail.width() * 0.85), int(avail.height() * 0.85))

    def region_fraction(self) -> Optional[list]:
        return self.selector.region_fraction()

    def _update_ok(self, *_args) -> None:
        self.ok.setEnabled(self.selector.region() is not None)

    def _screen_changed(self, index: int) -> None:
        screen = self.screen_combo.itemData(index)
        if screen is None or self._regrab is None:
            return
        img = self._regrab(screen)
        if img is None:
            return
        self.screen, self.image = screen, img
        self.selector.set_image(bgr_to_qimage(img))
        self._update_ok()
