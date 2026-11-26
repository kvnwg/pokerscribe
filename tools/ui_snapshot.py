"""Developer helper: drive the main window headlessly and save a screenshot.

    QT_QPA_PLATFORM=offscreen python tools/ui_snapshot.py out.png [screenshot.png] [--tab N] [--simple]

With --simple the screenshot is read once in watch mode and the simple view is saved.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.config import Settings  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.theme import apply_theme  # noqa: E402
from app.ui.workers import wait_for_all  # noqa: E402


def pump(ms=300):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main():
    out = sys.argv[1]
    image = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else None
    tab = int(sys.argv[sys.argv.index("--tab") + 1]) if "--tab" in sys.argv else 0
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    settings = Settings()
    settings.simple_mode = "--simple" in sys.argv
    w = MainWindow(settings)
    if not settings.simple_mode:
        w.resize(1480, 920)
    w.show()
    if image and settings.simple_mode:
        w.open_image(image)
        iw, ih = w.region_selector.image_size()
        w.region_selector.set_region((0, 0, iw, ih))
        w.toggle_watch(True)
        for _ in range(80):
            pump(200)
            wait_for_all(100)
            if w.advice is not None:
                break
        w.toggle_watch(False)
        pump(300)
        w.grab().save(out)
        print("saved", out, "advice:", w.advice.headline if w.advice else None)
        return
    if image:
        w.open_image(image)
        iw, ih = w.region_selector.image_size()
        w.region_selector.set_region((int(iw * 0.02), int(ih * 0.01), int(iw * 0.96), int(ih * 0.98)))
        w.capture_region()
        for _ in range(60):
            pump(200)
            wait_for_all(100)
            if w._busy_count == 0:
                break
        pump(500)
    w.tabs.setCurrentIndex(tab)
    pump(300)
    w.grab().save(out)
    print("saved", out, "status:", w.status_label.text())


if __name__ == "__main__":
    main()
