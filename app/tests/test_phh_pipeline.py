"""The hand history pipeline (tools/phh): parsing, decision points, leak checks, splits."""
import warnings

import pytest

pytest.importorskip("pokerkit")
warnings.filterwarnings("ignore", message="There is no reason for this player to fold")

from tools.phh.reader import RawHand, iter_file, parse_block  # noqa: E402
from tools.phh.replay import FEATURES, hand_decisions, leak_check, position_names  # noqa: E402
from tools.phh.sources import content_key, session_of, split_of  # noqa: E402

HAND = """variant = 'NT'
ante_trimming_status = true
antes = [0, 0, 0]
blinds_or_straddles = [1, 2, 0]
min_bet = 2
starting_stacks = [200, 200, 200]
actions = ['d dh p1 AsKs', 'd dh p2 7c2d', 'd dh p3 QhQd', 'p3 cbr 6', 'p1 cc', 'p2 f', 'd db 9h8h2c', 'p1 cc', 'p3 cbr 8', 'p1 f']
players = ['Alice', 'Bob', 'Carol']
hand = 7
"""


def raw(text=HAND, path="data/pluribus/100b/7.phh"):
    return parse_block(path, 1, text)


def test_parses_one_hand_and_reports_broken_ones():
    assert raw().data["variant"] == "NT"
    assert raw("variant = 'NT'\nactions = [").error.startswith("toml")
    assert "missing fields" in raw("variant = 'NT'\nactions = []\n").error
    stud = raw("variant = 'F7S'\nactions = []\n")
    assert stud.error is None and stud.data["variant"] == "F7S"
    assert hand_decisions(stud)[1]["status"] == "not_nlhe"


def test_reads_every_hand_of_a_phhs_file(tmp_path):
    f = tmp_path / "data" / "handhq" / "x.phhs"
    f.parent.mkdir(parents=True)
    f.write_text("[1]\n" + HAND + "\n[2]\nvariant = 'NT'\nactions = [\n\n[3]\n" + HAND)
    hands = list(iter_file(str(f), str(tmp_path)))
    assert [h.index for h in hands] == [1, 2, 3]
    assert hands[0].data and hands[1].data is None and hands[2].data


def test_decision_points_hold_only_what_the_player_saw():
    recs, info = hand_decisions(raw())
    assert info["status"] == "ok" and len(recs) == 6
    first = recs[0]
    assert (first["position"], first["hole_cards"], first["board"]) == ("BTN", "QhQd", "")
    assert (first["pot_bb"], first["to_call_bb"], first["min_raise_to_bb"]) == (1.5, 1.0, 2.0)
    assert (first["action"], first["amount_to_bb"]) == ("raise", 3.0)
    sb_flop = recs[3]
    assert (sb_flop["street"], sb_flop["position"], sb_flop["hole_cards"]) == ("flop", "SB", "AsKs")
    assert sb_flop["board"] == "9h8h2c" and sb_flop["can_check"] and sb_flop["pot_bb"] == 7.0
    assert sb_flop["history"] == ["p:BTN:r3", "p:SB:c", "p:BB:f"]
    assert (recs[4]["position"], recs[4]["action"], recs[4]["amount_to_bb"]) == ("BTN", "bet", 4.0)
    assert recs[5]["action"] == "fold" and recs[5]["to_call_bb"] == 4.0
    for r in recs:  # nobody else's cards, no outcome
        assert set(r) >= set(FEATURES) and "winnings" not in r and "finishing_stacks" not in r
        assert r["label_source"] == "observed"
    assert leak_check(raw(), recs) == (6, 0)


def test_a_missing_action_drops_the_whole_hand():
    broken = HAND.replace("'p2 f', ", "")
    recs, info = hand_decisions(raw(broken))
    assert recs == [] and info["status"] == "out_of_turn"


def test_a_card_dealt_twice_is_corrupt():
    recs, info = hand_decisions(raw(HAND.replace("QhQd", "AsQd")))
    assert recs == [] and info["status"] == "corrupt"


def test_seat_names():
    assert position_names(6, [1, 2, 0, 0, 0, 0]) == ["SB", "BB", "UTG", "HJ", "CO", "BTN"]
    assert position_names(2, [2, 1]) == ["BB", "BTN/SB"]
    assert position_names(9, [1, 2] + [0] * 7)[2:8] == ["UTG", "UTG+1", "UTG+2", "LJ", "HJ", "CO"]


def test_sessions_and_splits_keep_sittings_together():
    data = raw().data
    assert session_of("pluribus", "data/pluribus/100b/7.phh", data) == session_of("pluribus", "data/pluribus/100/3.phh", data)
    hq = dict(data, venue="PokerStars", year=2009, month=7, day=5)
    s = session_of("handhq", "data/handhq/PS-2009-07-01_2009-07-23_200NLH_OBFU/1/a.phhs", hq)
    assert s == "handhq/PokerStars/200NL/2009-07-05"
    assert split_of(s, "handhq") == split_of(s, "handhq") in ("train", "validation", "test")
    assert split_of("wsop/2023/43/5", "wsop") == "evaluation"


def test_identical_play_is_not_a_duplicate_when_the_hand_number_differs():
    a = raw().data
    b = dict(a, hand=8)
    assert content_key(a, "s") != content_key(b, "s") and content_key(a, "s") == content_key(dict(a), "s")
