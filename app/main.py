"""Entry point: python -m app.main [--image screenshot.png]"""
from __future__ import annotations

import argparse
import logging
import sys


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PokerScribe: local poker table recognition")
    parser.add_argument("--image", help="open this screenshot on start")
    parser.add_argument("--debug", action="store_true", help="verbose logging")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    from PySide6.QtWidgets import QApplication

    from app import APP_NAME
    from app.ui.main_window import MainWindow
    from app.ui.theme import apply_theme

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    apply_theme(app)
    window = MainWindow()
    window.show()
    if args.image:
        window.open_image(args.image)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
