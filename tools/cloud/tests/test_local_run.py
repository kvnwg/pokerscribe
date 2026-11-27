"""The local end-to-end run (python -m tools.cloud local-test): the real supervisor and the
fake trainer, a local folder for the bucket, SIGTERM to every process halfway through, then a
new machine with an empty disk that resumes from the bucket and finishes. See local_test.py
for everything it checks."""
from __future__ import annotations

import json
import os
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


def test_rehearsal_mode_with_stages_and_a_stop(tmp_path):
    """The real-trainer mode, run here with the fake trainer writing a stage every 100
    iterations: SIGTERM after 2 stages, a new machine gets the checkpoint and the stage files
    back, then the stop marker after 4."""
    tables = tmp_path / "tables"
    tables.mkdir()
    cfg = tmp_path / "fake.json"
    cfg.write_text(json.dumps({"iterations": 100000, "iteration_seconds": 0.03,
                               "checkpoint_seconds": 0.3, "checkpoint_bytes": 4096,
                               "stage_every": 100, "progress_every": 10,
                               "tables": "/opt/pscloud/bundle/files/tables"}))
    out = local_test.run_trainer(str(tmp_path / "run"), [sys.executable, local_test.FAKE],
                                 str(cfg), files=[str(tables)], sigterm_after=2, stop_after=4,
                                 timeout_minutes=3, say=lambda _line: None)
    assert out["rewritten"] == [f"/opt/pscloud/bundle/files/tables -> {tables}"]
    assert out["resumed_at"] == out["stopped_at"] >= 200
    assert out["state"] == "stopped" and out["stopped_again_at"] >= 400
    its = [s["iterations"] for s in out["stages"]]
    assert its[:4] == [100, 200, 300, 400] and its == sorted(set(its))
    assert out["artifacts"]["restored"] >= 2
    names = sorted(os.listdir(tmp_path / "run" / "bucket" / "runs" / "local-test" / "artifacts"))
    assert {"stage-100.bps", "stage-200.bps", "stage-400.bps", "stages.jsonl"} <= set(names)
    if sys.platform.startswith("linux"):         # the trainer's memory comes from /proc
        assert out["trainer_peak_bytes"] > 0
