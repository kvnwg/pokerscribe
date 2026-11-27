"""The local end-to-end run (python -m tools.cloud local-test): the real supervisor and the
fake trainer, a local folder for the bucket, SIGTERM to every process halfway through, then a
new machine with an empty disk that resumes from the bucket and finishes. See local_test.py
for everything it checks."""
from __future__ import annotations

import subprocess
import sys

from tools.cloud import fake_trainer, local_test, settings


def test_sigterm_halfway_then_resume_on_a_new_machine(tmp_path):
    out = local_test.run(str(tmp_path), iterations=400, say=lambda _line: None)
    assert 200 <= out["stopped_at"] < 400
    assert out["resumed_at"] == out["stopped_at"]
    assert out["digest"] == fake_trainer.expected_digest(400)
    assert len(out["kept"]) == 3 and out["sessions"] == 2 and out["state"] == "done"
    assert out["cost"]["sessions"] == 2 and out["cost"]["total_usd"] > 0


def test_local_test_command(tmp_path):
    p = subprocess.run([sys.executable, "-m", "tools.cloud", "local-test", "--keep",
                        str(tmp_path)], capture_output=True, text=True, timeout=180,
                       cwd=settings.REPO)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "the hash matches an uninterrupted run" in p.stdout
    assert (tmp_path / "bucket" / "runs" / "local-test" / "state.json").exists()
