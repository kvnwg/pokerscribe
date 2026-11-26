"""Helper for test_capture: run under xvfb-run. Clicks Capture screen and Capture region in
the real main window and prints what was captured as JSON."""
import json
import os
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "xcb"
os.environ.setdefault("POKERSCRIBE_HOME", tempfile.mkdtemp())

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.config import Settings  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.workers import wait_for_all  # noqa: E402


def pump(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main():
    app = QApplication(sys.argv)
    w = MainWindow(Settings())
    w.setGeometry(0, 0, 1200, 760)
    w.show()
    pump(800)
    out = {"screens": w.screen_combo.count(), "enabled": w.capture_screen_btn.isEnabled()}
    w.capture_screen()
    for _ in range(50):
        pump(100)
        if w.region_selector.has_image() and w._busy_count == 0:
            break
    out["screen_image"] = list(w.region_selector.image_size())
    w.region_selector.set_region((10, 10, 300, 200))
    w.capture_region()
    for _ in range(50):
        pump(100)
        wait_for_all(50)
        if w.last_capture is not None and w._busy_count == 0:
            break
    out["region_shape"] = list(w.last_capture.shape) if w.last_capture is not None else None
    out["status"] = w.status_label.text()
    print(json.dumps(out))
    w.close()


if __name__ == "__main__":
    main()
