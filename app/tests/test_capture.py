import json
import os
import shutil
import subprocess
import sys

import numpy as np
import pytest

from app.capture import CaptureError, ImageSource, Region, ScreenInfo, ScreenSource
from app.capture.sources import clamp_rect, load_image_file
from app.config import Settings

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_clamp_rect():
    assert clamp_rect((10, 10, 50, 40), 100, 100) == (10, 10, 50, 40)
    assert clamp_rect((-10, -5, 50, 40), 100, 100) == (0, 0, 40, 35)
    assert clamp_rect((90, 90, 50, 50), 100, 100) == (90, 90, 10, 10)
    assert clamp_rect((200, 200, 5, 5), 100, 100) is None


def test_image_source_crops_exact_pixels():
    img = np.zeros((100, 200, 3), np.uint8)
    img[20:30, 40:60] = (0, 0, 255)
    src = ImageSource(img)
    assert src.size == (200, 100)
    crop = src.region_image((40, 20, 20, 10))
    assert crop.shape == (10, 20, 3)
    assert (crop == (0, 0, 255)).all()
    with pytest.raises(CaptureError):
        src.region_image((500, 500, 10, 10))


class _FakeGrabber:
    """Pretends to be a Retina display: images come back at 2x the point size."""

    def __init__(self):
        self.calls = []

    def grab_screen(self, screen):
        return np.zeros((screen.height * 2, screen.width * 2, 3), np.uint8)

    def grab(self, region):
        self.calls.append(region)
        return np.zeros((region.height * 2, region.width * 2, 3), np.uint8)


def test_screen_source_maps_pixels_to_screen_points():
    screen = ScreenInfo(index=2, left=1440, top=0, width=1512, height=982)
    grabber = _FakeGrabber()
    src = ScreenSource(screen, grabber)
    full = src.full_image()
    assert full.shape[:2] == (1964, 3024)
    region = src.to_screen_region((200, 100, 800, 600))  # in 2x pixels
    assert region == Region(left=1440 + 100, top=50, width=400, height=300)
    img = src.region_image((200, 100, 800, 600))
    assert img.shape[:2] == (600, 800)
    assert grabber.calls[-1] == region


def test_settings_round_trip(tmp_home):
    s = Settings()
    s.region = [0.1, 0.2, 0.5, 0.6]
    s.confidence_threshold = 0.8
    s.ai_provider = "claude"
    s.save()
    loaded = Settings.load()
    assert loaded.region == [0.1, 0.2, 0.5, 0.6]
    assert loaded.confidence_threshold == 0.8
    assert loaded.ai_provider == "claude"
    raw = json.loads(Settings.default_path().read_text())
    assert not any("key" in k.lower() for k in raw), "API keys must never be stored in settings"


def test_settings_reject_bad_values(tmp_home):
    Settings.default_path().write_text(json.dumps({"region": [5, 5, -1, 2], "confidence_threshold": "high",
                                                   "max_tokens": 10**9, "unknown": 1}))
    s = Settings.load()
    assert s.region is None
    assert s.confidence_threshold == Settings().confidence_threshold
    assert s.max_tokens == 4000
    Settings.default_path().write_text("{not json")
    assert Settings.load() == Settings()


def test_load_image_file(tmp_path):
    import cv2

    img = np.full((30, 40, 3), (10, 200, 30), np.uint8)
    path = tmp_path / "shot é.png"  # non-ASCII path
    cv2.imencode(".png", img)[1].tofile(str(path))
    loaded = load_image_file(path)
    assert loaded.shape == (30, 40, 3)
    assert tuple(loaded[0, 0]) == (10, 200, 30)
    with pytest.raises(CaptureError):
        load_image_file(tmp_path / "missing.png")


@pytest.mark.skipif(not shutil.which("xvfb-run") or sys.platform == "darwin", reason="needs Xvfb")
def test_real_screen_capture_on_virtual_display():
    """Shows a coloured window on a virtual X display and grabs it with mss."""
    env = dict(os.environ)
    env.pop("QT_QPA_PLATFORM", None)
    env["PYTHONPATH"] = ROOT
    proc = subprocess.run(
        ["xvfb-run", "-a", "-s", "-screen 0 1280x800x24", sys.executable, "-m", "app.tests.xvfb_capture_probe"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    assert result["screens"] >= 1
    assert result["shape"] == [200, 300, 3]
    b, g, r = result["center_bgr"]
    assert r > 200 and g < 60 and b > 200, result  # magenta window
    assert result["blue_square_found"]


@pytest.mark.skipif(not shutil.which("xvfb-run") or sys.platform == "darwin", reason="needs Xvfb")
def test_main_window_live_capture_on_virtual_display():
    """End to end through the UI: Capture screen, then Capture region, in worker threads."""
    env = dict(os.environ)
    env.pop("QT_QPA_PLATFORM", None)
    env["PYTHONPATH"] = ROOT
    proc = subprocess.run(
        ["xvfb-run", "-a", "-s", "-screen 0 1280x800x24", sys.executable, "-m", "app.tests.xvfb_ui_probe"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, proc.stderr[-2000:]
    result = json.loads(proc.stdout.strip().splitlines()[-1])
    assert result["screens"] >= 1 and result["enabled"]
    assert result["screen_image"] == [1280, 800]
    assert result["region_shape"][:2] == [200, 300]
