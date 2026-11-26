"""Replay a folder saved with "Save last reads": read every picture again with the current
code and print what was read then and what is read now, side by side.

    python tools/replay_reads.py "~/Documents/PokerScribe reads/2026-11-26 01-58-03"
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import cv2  # noqa: E402

from app.poker.advice import advise  # noqa: E402
from app.poker.calculator import compute  # noqa: E402
from app.poker.ranges import make_range  # noqa: E402
from app.recognition.hand import HandMemory  # noqa: E402
from app.recognition.recognizer import TableRecognizer  # noqa: E402
from app.recognition.tracker import HandTracker  # noqa: E402
from app.vision.card_recognizer import CardRecognizer  # noqa: E402
from app.vision.ocr import create_engine  # noqa: E402


def summary(state: dict) -> str:
    def v(f):
        return None if not f or f.get("value") is None else f["value"]
    players = []
    for p in state.get("players", []):
        tag = "*" if p.get("is_hero") else ""
        players.append(f"{tag}{v(p.get('position')) or '?'}:{v(p.get('stack'))}/{v(p.get('bet'))}")
    return (f"turn={v(state.get('hero_to_act'))} pot={v(state.get('pot'))} call={v(state.get('to_call'))} "
            f"blinds={v(state.get('blinds'))} board={[v(c) for c in state.get('board', [])]} "
            f"hero={[v(c) for c in state.get('hero_cards', [])]} | " + " ".join(players))


def main(folder: str) -> None:
    folder = os.path.expanduser(folder)
    rec = TableRecognizer(CardRecognizer(), create_engine("auto"))
    tracker, hand = HandTracker(), HandMemory()
    spec = make_range("medium")
    with open(os.path.join(folder, "reads.jsonl")) as fh:
        lines = [json.loads(x) for x in fh if x.strip()]
    for line in lines:
        img = cv2.imread(os.path.join(folder, line["image"]))
        res = rec.recognize(img)
        info = tracker.update(res.state)
        hand.update(res.state, [r.box for r in res.board_readings], info.new_hand)
        computed = compute(res.state, spec, 250)
        res.state.computed = computed
        adv = advise(res.state, computed, numbers_checked=info.valid)
        then = line.get("advice", {}).get("headline")
        print(f"#{line['n']:03d} {line['time'][11:23]}  then: {then!s:<22} now: {adv.headline:<22} "
              f"tracker={'ok' if info.valid else 'no'} to_call={info.to_call}")
        print(f"      then {summary(line.get('state', {}))}")
        print(f"      now  {summary(res.state.to_json())}")


if __name__ == "__main__":
    main(sys.argv[1])
