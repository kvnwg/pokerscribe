"""Helper for test_capture: run under xvfb-run. Shows a known pattern, grabs it, prints JSON."""
import json
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "xcb"

from PySide6.QtCore import QTimer, Qt  # noqa: E402
from PySide6.QtGui import QColor, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from app.capture import Region, ScreenGrabber, list_screens  # noqa: E402


class Pattern(QWidget):
    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(255, 0, 255))
        p.fillRect(20, 20, 40, 40, QColor(0, 0, 255))
        p.end()


def main():
    app = QApplication(sys.argv)
    w = Pattern()
    w.setWindowFlags(Qt.WindowType.FramelessWindowHint)
    w.setGeometry(100, 80, 300, 200)
    w.show()
    out = {}

    def grab():
        screens = list_screens()
        img = ScreenGrabber().grab(Region(100, 80, 300, 200))
        out["screens"] = len(screens)
        out["shape"] = list(img.shape)
        out["center_bgr"] = [int(v) for v in img[100, 150]]
        sq = img[25:55, 25:55]
        out["blue_square_found"] = bool((sq[:, :, 0] > 200).mean() > 0.9 and (sq[:, :, 2] < 60).mean() > 0.9)
        print(json.dumps(out))
        app.quit()

    QTimer.singleShot(1200, grab)
    app.exec()


if __name__ == "__main__":
    main()
