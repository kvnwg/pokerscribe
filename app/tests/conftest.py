import os
import sys
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("POKERSCRIBE_HOME", tempfile.mkdtemp(prefix="pokerscribe-test-"))
# Never let tests pick up a real key from the developer's environment.
for _var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
    os.environ.pop(_var, None)

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication

    from app.ui.theme import apply_theme

    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    yield app


@pytest.fixture()
def tmp_home(tmp_path, monkeypatch):
    monkeypatch.setenv("POKERSCRIBE_HOME", str(tmp_path))
    return tmp_path
