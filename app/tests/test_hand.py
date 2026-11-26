"""Watch mode: knowing it's still the same hand from one check to the next."""
from typing import Optional, Sequence

from app.recognition.hand import HandMemory
from app.state.model import Field, GameState

W = 70  # board card width in px; cards sit 80 px apart
SLOTS = [300 + 80 * i for i in range(5)]


def read(hero: Sequence[Optional[str]] = ("Qd", "Th"), board: Sequence[Optional[str]] = (),
         pot: Optional[float] = 10.0, guesses=None, slots=None):
    """One read of the table. None = a card that's there but unsure (with a guess)."""
    def card(code, guess=None):
        return Field(code, 1.0, "auto") if code else Field(None, 0.5, "auto", guess=guess or "2c")

    st = GameState(hero_cards=[card(c) for c in hero] if hero else [Field(), Field()],
                   board=[card(c) for c in board])
    if pot is not None:
        st.pot = Field.manual(float(pot))
    xs = slots if slots is not None else SLOTS[: len(board)]
    boxes = [(x, 200, W, 100) for x in xs]
    return st, boxes


def test_cards_known_a_moment_ago_stay_known():
    m = HandMemory()
    st, boxes = read(board=("2h", "6c", "Tc"))
    assert m.update(st, boxes) and m.number == 1
    # chips fly over the cards: this read is unsure of one hole card and one board card
    st, boxes = read(hero=("Qd", None), board=("2h", None, "Tc"))
    assert not m.update(st, boxes)
    assert [c.value for c in st.hero_cards] == ["Qd", "Th"]
    assert [c.value for c in st.board] == ["2h", "6c", "Tc"]
    assert m.number == 1


def test_new_board_cards_are_added_and_a_missed_one_keeps_its_place():
    m = HandMemory()
    st, boxes = read(board=("2h", "6c", "Tc"))
    m.update(st, boxes)
    # the turn comes, and the first flop card isn't seen in this read at all
    st, boxes = read(board=("6c", "Tc", "Js"), slots=SLOTS[1:4])
    assert not m.update(st, boxes)
    assert [c.value for c in st.board] == ["2h", "6c", "Tc", "Js"]
    st, boxes = read(board=("2h", "6c", "Tc", "Js", "Kh"), pot=26)
    assert not m.update(st, boxes)
    assert m.board_cards == ["2h", "6c", "Tc", "Js", "Kh"]


def test_different_hole_cards_start_a_new_hand():
    m = HandMemory()
    m.update(*read(board=("2h", "6c", "Tc")))
    st, boxes = read(hero=("7s", "4s"), board=(), pot=3)
    assert m.update(st, boxes) and m.number == 2
    assert m.board_cards == [] and m.hero_cards == ["7s", "4s"]


def test_pot_starting_over_or_stacks_say_new_hand():
    m = HandMemory()
    m.update(*read(hero=(None, None), board=(), pot=40))
    assert m.update(*read(hero=(None, None), board=(), pot=3))  # the pot fell back to the blinds
    m2 = HandMemory()
    m2.update(*read(pot=3))
    assert m2.update(*read(hero=(None, None), pot=3), stacks_new_hand=True)


def test_a_different_card_in_a_board_spot_is_a_new_hand():
    m = HandMemory()
    m.update(*read(board=("2h", "6c", "Tc")))
    assert m.update(*read(hero=("Qd", "Th"), board=("Ah", "6c", "Tc")))


def test_one_empty_read_is_not_a_new_hand():
    m = HandMemory()
    m.update(*read(board=("2h", "6c", "Tc")))
    st, boxes = read(hero=(), board=(), pot=None)  # a frame where nothing could be seen
    assert not m.update(st, boxes)
    st, boxes = read(hero=(None, None), board=("2h", "6c", "Tc"))
    assert not m.update(st, boxes)
    assert [c.value for c in st.hero_cards] == ["Qd", "Th"] and m.number == 1


def test_confirmed_cards_last_for_the_hand_only():
    m = HandMemory()
    st, boxes = read(hero=(None, "Th"), board=("2h", None, "Tc"))
    m.update(st, boxes)
    m.confirm("hero", 0, "Qd")
    m.confirm("board", 1, "6c")
    st, boxes = read(hero=(None, None), board=(None, None, "Tc"))
    m.update(st, boxes)
    assert {c.value for c in st.hero_cards} == {"Qd", "Th"}
    assert [c.value for c in st.board] == ["2h", "6c", "Tc"]
    assert st.hero_cards[0].source == "manual" or st.hero_cards[1].source == "manual"
    # next hand: nothing carried over
    st, boxes = read(hero=(None, None), board=(), pot=3)
    assert m.update(st, boxes, stacks_new_hand=True)
    assert not any(c.known for c in st.hero_cards)


def test_folded_hand_is_not_filled_back_in():
    m = HandMemory()
    m.update(*read(board=("2h", "6c", "Tc")))
    st, boxes = read(hero=(), board=("2h", "6c", "Tc"))  # you folded: your cards are gone
    assert not m.update(st, boxes)
    assert not any(c.known for c in st.hero_cards)


def test_hand_count_ignores_the_gap_between_hands():
    m = HandMemory()
    m.update(*read(hero=(), board=(), pot=None))  # watching starts between hands
    assert m.number == 1
    m.update(*read(pot=3), stacks_new_hand=True)  # the first hand
    assert m.number == 1
    m.update(*read(hero=("7s", "4s"), pot=3), stacks_new_hand=True)
    assert m.number == 2
