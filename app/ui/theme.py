"""Dark theme: palette, stylesheet and confidence colours."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

BG = "#111418"
PANEL = "#171b21"
PANEL_2 = "#1e232b"
BORDER = "#2a313b"
TEXT = "#e7e9ec"
MUTED = "#8d97a5"
ACCENT = "#2ec27e"
ACCENT_DIM = "#1d7f53"
WARN = "#f2b33d"
BAD = "#ef5350"
INFO = "#5aa9e6"
UNKNOWN_GREY = "#6b7280"

SUIT_COLORS = {"s": "#111111", "c": "#111111", "h": "#d32f2f", "d": "#d32f2f"}


def confidence_color(confidence: float, known: bool, threshold: float) -> str:
    if not known:
        return UNKNOWN_GREY
    if confidence >= 0.995:
        return INFO  # manual / exact
    if confidence >= 0.9:
        return ACCENT
    if confidence >= threshold:
        return WARN
    return BAD


STYLESHEET = f"""
QWidget {{ background-color: {BG}; color: {TEXT}; font-size: 13px; }}
QMainWindow::separator {{ background: {BORDER}; width: 1px; height: 1px; }}
QToolBar {{ background: {PANEL}; border: none; border-bottom: 1px solid {BORDER}; spacing: 6px; padding: 6px; }}
QToolBar QLabel {{ background: transparent; color: {MUTED}; }}
QStatusBar {{ background: {PANEL}; border-top: 1px solid {BORDER}; color: {MUTED}; }}
QStatusBar QLabel {{ background: transparent; }}
QPushButton, QToolButton {{
    background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 6px;
    padding: 6px 12px; color: {TEXT};
}}
QPushButton:hover, QToolButton:hover {{ border-color: {ACCENT_DIM}; }}
QPushButton:pressed, QToolButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled, QToolButton:disabled {{ color: #5b6370; border-color: #222831; }}
QPushButton#primary {{ background: {ACCENT_DIM}; border-color: {ACCENT}; color: white; font-weight: 600; }}
QPushButton#primary:hover {{ background: {ACCENT}; }}
QPushButton#primary:disabled {{ background: #1b3a2c; color: #7f9b8c; border-color: #1f4733; }}
QPushButton#primary:checked {{ background: #5c1d22; border-color: {BAD}; color: white; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextBrowser, QTextEdit {{
    background: {PANEL}; border: 1px solid {BORDER}; border-radius: 5px; padding: 4px 6px;
    selection-background-color: {ACCENT_DIM};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
QComboBox QAbstractItemView {{ background: {PANEL_2}; border: 1px solid {BORDER}; selection-background-color: {ACCENT_DIM}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 6px; top: -1px; background: {PANEL}; }}
QTabBar::tab {{ background: {BG}; color: {MUTED}; padding: 7px 14px; border: 1px solid {BORDER};
    border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; margin-right: 2px; }}
QTabBar::tab:selected {{ background: {PANEL}; color: {TEXT}; border-color: {BORDER}; }}
QGroupBox {{ border: 1px solid {BORDER}; border-radius: 6px; margin-top: 14px; padding: 8px; background: {PANEL}; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {MUTED}; background: transparent; }}
QGroupBox QWidget {{ background: transparent; }}
QGroupBox QLineEdit, QGroupBox QComboBox, QGroupBox QSpinBox, QGroupBox QDoubleSpinBox, QGroupBox QPlainTextEdit
    {{ background: {BG}; }}
QTableWidget {{ background: {BG}; gridline-color: {BORDER}; border: 1px solid {BORDER}; border-radius: 5px; }}
QHeaderView::section {{ background: {PANEL_2}; color: {MUTED}; border: none; border-right: 1px solid {BORDER};
    padding: 4px 6px; }}
QTableWidget::item:selected {{ background: {ACCENT_DIM}; }}
QCheckBox {{ background: transparent; spacing: 6px; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border: 1px solid #4a5361; border-radius: 4px; background: {PANEL_2}; }}
QCheckBox::indicator:hover {{ border-color: {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QSplitter::handle {{ background: {BORDER}; }}
QScrollBar:vertical {{ background: {BG}; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; min-height: 24px; }}
QScrollBar:horizontal {{ background: {BG}; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 4px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QProgressBar {{ background: {PANEL_2}; border: 1px solid {BORDER}; border-radius: 4px; height: 8px; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QLabel#muted {{ color: {MUTED}; background: transparent; }}
QLabel#heading {{ color: {TEXT}; font-weight: 600; font-size: 14px; background: transparent; }}
QToolTip {{ background: {PANEL_2}; color: {TEXT}; border: 1px solid {BORDER}; }}
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(BG))
    pal.setColor(QPalette.ColorRole.WindowText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Base, QColor(PANEL))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor(PANEL_2))
    pal.setColor(QPalette.ColorRole.Text, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Button, QColor(PANEL_2))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(ACCENT_DIM))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("white"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor(PANEL_2))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor(TEXT))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor(MUTED))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)
