"""Save last reads: the pictures and what was read, written only when asked."""
import json

import numpy as np

from app.capture.history import ReadLog
from app.poker.advice import Advice
from app.recognition.tracker import TrackInfo


def test_keeps_only_the_last_reads_and_saves_them(tmp_path):
    log = ReadLog(keep=3)
    for i in range(5):
        img = np.full((40, 60, 3), i * 40, dtype=np.uint8)
        log.add(img, {"state": {"pot": i}, "track": TrackInfo(valid=True, to_call=float(i), street_bets={0: 2.0}),
                      "advice": Advice("check", "CHECK", "free").to_dict()})
    assert len(log) == 3
    n = log.save(str(tmp_path / "reads"))
    assert n == 3
    lines = [json.loads(x) for x in (tmp_path / "reads" / "reads.jsonl").read_text().splitlines()]
    assert [x["state"]["pot"] for x in lines] == [2, 3, 4]
    assert lines[0]["track"]["street_bets"] == {"0": 2.0} and lines[0]["advice"]["headline"] == "CHECK"
    assert (tmp_path / "reads" / "001.png").exists() and (tmp_path / "reads" / "README.txt").exists()
