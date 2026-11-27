"""Drive the real main window: screenshot -> region -> recognition -> correction -> text -> AI."""
import time

import pytest
from PySide6.QtWidgets import QApplication

from app.ai.base import AIProvider
from app.ai.claude import ClaudeProvider
from app.config import Settings, app_data_dir
from app.state.text_format import parse_text
from app.tests.synthetic import demo_table, render_table
from app.tests.test_ai_providers import _Server
from app.vision.card_recognizer import CardRecognizer
from app.ui.main_window import MainWindow
from app.ui.settings_dialog import SettingsDialog
from app.ui.workers import wait_for_all
from app.vision.ocr import RapidOcrEngine


def wait_until(cond, timeout=60.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        QApplication.processEvents()
        if cond():
            return True
        wait_for_all(20)
    return False


@pytest.mark.skipif(not RapidOcrEngine.available(), reason="RapidOCR not installed")
def test_full_flow(qapp, tmp_home, monkeypatch):
    server = _Server()
    AIProvider._cache.clear()
    try:
        settings = Settings()
        settings.math_time_ms = 200
        settings.confirm_new_cards = False
        w = MainWindow(settings)
        w.show()
        img, _ = render_table(demo_table())
        w.load_image(img)
        h, wd = img.shape[:2]
        w.region_selector.set_region((10, 5, wd - 20, h - 10))
        w.capture_region()
        assert wait_until(lambda: w.result is not None)
        st = w.state
        assert [c.value for c in st.hero_cards] == ["As", "Kh"]
        assert w.capture_preview.has_image()
        assert parse_text(w.text_panel.text)["TO CALL"] == "60"
        assert not w.text_panel.problems

        # local maths arrives asynchronously
        assert wait_until(lambda: "LOCAL MATH" in w.text_panel.text)
        assert "Equity" in w.correction.math_summary.text()

        # correct a card: state, text and learned templates update
        w.correction.apply_card_choice("hero", 1, "Kd")
        assert w.state.hero_cards[1].value == "Kd" and w.state.hero_cards[1].source == "manual"
        assert parse_text(w.text_panel.text)["HERO CARDS"] == "Ace of Spades, King of Diamonds"
        assert any((app_data_dir() / "learned_templates" / "rank").glob("K_*.png"))

        # correct the pot by typing
        w.correction.pot_edit.setText("150")
        w.correction.pot_edit.editingFinished.emit()
        assert parse_text(w.text_panel.text)["POT"] == "150"
        assert w.state.pot.source == "manual"

        # mark an opponent's stack unknown: it shows up in UNKNOWN FIELDS
        maverick = next(p for p in w.state.opponents if p.in_hand.value)
        w.correction._set(maverick, "stack", None)
        assert "OPPONENT 1 STACK" in parse_text(w.text_panel.text)["UNKNOWN FIELDS"]

        # AI analysis through a local mock of the Messages API
        monkeypatch.setattr("app.ui.main_window.create_provider", lambda s: ClaudeProvider(
            "test-key", api_url=f"http://127.0.0.1:{server.port}/v1/messages"))
        w._update_provider()
        w._refresh_outputs()
        assert w.ai_panel.button.isEnabled()
        w.analyze()
        assert wait_until(lambda: "Missing information" in w.ai_panel.output.toPlainText())
        sent = server.requests[-1]["body"]["messages"][0]["content"]
        assert "King of Diamonds" in sent and "POT: 150" in sent and "Maverick" not in sent

        # settings dialog round trip
        dlg = SettingsDialog(w.settings, w)
        dlg.threshold.setValue(0.8)
        dlg.apply()
        assert w.settings.confidence_threshold == 0.8
        w.close()
    finally:
        server.close()


@pytest.mark.skipif(not RapidOcrEngine.available(), reason="RapidOCR not installed")
def test_simple_view_watch_mode(qapp, tmp_home):
    from PySide6.QtCore import Qt

    settings = Settings()
    settings.math_time_ms = 200
    settings.watch_interval_ms = 300
    settings.confirm_new_cards = False
    w = MainWindow(settings)
    w.show()
    assert w.pages.currentIndex() == 0 and not w.toolbar.isVisible()
    assert w.simple.headline.text() == "SET UP"
    # watching without a table box explains what to do first
    w.toggle_watch(True)
    assert not w._watch_timer.isActive() and "Set table box" in w.simple.warning.text()

    img, _ = render_table(demo_table())
    w.load_image(img)
    h, wd = img.shape[:2]
    w.region_selector.set_region((10, 5, wd - 20, h - 10))
    w.toggle_watch(True)
    assert w._watch_timer.isActive() and w.simple.watch_btn.isChecked()
    assert wait_until(lambda: w.advice is not None)
    assert w.advice.headline == "CALL 60" and w.simple.headline.text() == "CALL 60"
    assert "A♠" in w.simple.facts.text() and "To call" in w.simple.facts.text()
    assert "Watching" in w.simple.status.text()
    # the table did not change: no new recognition on the next ticks
    version = w._state_version
    deadline = time.time() + 1.2
    while time.time() < deadline:
        QApplication.processEvents()
        wait_for_all(50)
    assert w._state_version == version
    w.toggle_watch(False)
    assert not w._watch_timer.isActive() and not w.simple.watch_btn.isChecked()

    # details view and back
    w.show_details()
    assert w.pages.currentIndex() == 1 and w.toolbar.isVisible() and not w.settings.simple_mode
    assert w.capture_preview.has_image()
    w.show_simple()
    assert w.pages.currentIndex() == 0 and w.settings.simple_mode
    w.set_on_top(True)
    assert w.windowFlags() & Qt.WindowType.WindowStaysOnTopHint and w.settings.always_on_top
    w.close()


@pytest.mark.skipif(not RapidOcrEngine.available(), reason="RapidOCR not installed")
def test_exact_cards_checks_each_new_card_once(qapp, tmp_home, monkeypatch):
    # a deck the app doesn't know yet, read without the "very sure" shortcut (this
    # synthetic deck is so clean that the general reader would be sure of every card)
    monkeypatch.setattr("app.vision.card_recognizer.load_builtin_deck", lambda ts, kind: 0)
    monkeypatch.setattr(CardRecognizer, "SURE", 1.01)

    settings = Settings()
    settings.math_time_ms = 200
    assert settings.confirm_new_cards  # on by default
    w = MainWindow(settings)
    w.show()
    img, _ = render_table(demo_table())
    w.load_image(img)
    h, wd = img.shape[:2]
    w.region_selector.set_region((10, 5, wd - 20, h - 10))
    w.capture_region()
    # a deck it has never seen: every card is shown for one check, nothing is assumed
    assert wait_until(lambda: w.advice is not None)
    assert w.advice.headline == "CONFIRM YOUR CARDS" and w.simple.fix_box.isVisible()
    assert [g for _, _, g in w.simple._fix_items] == ["As", "Kh", "Ah", "8d", "5c"]
    w.simple.fix_yes.click()
    assert wait_until(lambda: w.advice.action == "call")
    assert w.state.hero_cards[1].value == "Kh" and not w.simple.fix_box.isVisible()

    # the same cards again: read exactly, no questions
    before = w.result
    w.capture_region()
    assert wait_until(lambda: w.result is not before and w.advice is not None and w.advice.action == "call")
    assert [c.value for c in w.state.hero_cards] == ["As", "Kh"]
    assert all(c.confidence == 1.0 and c.source == "auto" for c in w.state.hero_cards + w.state.board)
    assert not w.simple.fix_box.isVisible()

    # (keeping confirmed cards for the rest of a hand is tested in test_hand.py)
    w.close()


def test_watch_notices_one_changed_digit_and_ignores_still_frames():
    import cv2

    from app.ui.main_window import frame_changed

    img, _ = render_table(demo_table())

    def small(a):
        g = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY)
        return cv2.resize(g, (g.shape[1] // 4, g.shape[0] // 4), interpolation=cv2.INTER_AREA)

    same = img.copy()
    assert not frame_changed(small(img), small(same))
    # one stack label goes from $998 to $994: a few dozen pixels of a large table
    edited = img.copy()
    cv2.putText(edited, "4", (300, 300), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    assert frame_changed(small(img), small(edited))
    assert float(cv2.absdiff(small(img), small(edited)).mean()) < 0.6  # the old whole-table average missed it


@pytest.mark.skipif(not RapidOcrEngine.available(), reason="RapidOCR not installed")
def test_claude_reads_the_cards_the_app_is_unsure_of(qapp, tmp_home, monkeypatch):
    """With 'Let Claude read cards' on, unclear cards are filled in from Claude's answer
    instead of asking, and only crops of the cards are handed over."""
    from app.ai.vision import CardsRead

    monkeypatch.setattr("app.vision.card_recognizer.load_builtin_deck", lambda ts, kind: 0)
    monkeypatch.setattr(CardRecognizer, "SURE", 1.01)  # the app alone is unsure of every card

    class FakeReader:
        calls = []

        def read(self, hero_crop, board_crop):
            self.calls.append((None if hero_crop is None else hero_crop.shape,
                               None if board_crop is None else board_crop.shape))
            return CardsRead(["As", "Kh"], ["Ah", "8d", "5c"])

    reader = FakeReader()
    settings = Settings()
    settings.math_time_ms = 200
    settings.watch_interval_ms = 300
    w = MainWindow(settings)
    monkeypatch.setattr(w, "_card_reader", lambda: reader)
    w.show()
    img, _ = render_table(demo_table())
    w.load_image(img)
    h, wd = img.shape[:2]
    w.region_selector.set_region((10, 5, wd - 20, h - 10))
    w.toggle_watch(True)
    assert wait_until(lambda: w.advice is not None and w.advice.action != "unknown")
    assert [c.value for c in w.state.hero_cards] == ["As", "Kh"]
    assert [c.value for c in w.state.board] == ["Ah", "8d", "5c"]
    assert not w.simple.fix_box.isVisible() and w.advice.headline == "CALL 60"
    hero_shape, board_shape = reader.calls[0]
    assert hero_shape[0] < h / 3 and board_shape[0] < h / 3  # crops of the cards, not the table
    assert "Hand 1" in w.simple.status.text()
    w.toggle_watch(False)
    w.close()


def test_one_instruction_per_spot(qapp, tmp_home):
    """A re-read of the same spot keeps the move; a real change (a bet, a card) updates it."""
    from app.poker.advice import Advice
    from app.state.model import Field, GameState

    w = MainWindow(Settings())

    def st(pot=10.0, to_call=0.0, board=("2h", "6c", "Tc")):
        s = GameState(hero_cards=[Field.manual("Qd"), Field.manual("Th")], board=[Field.manual(c) for c in board])
        s.pot = Field.manual(pot) if pot is not None else Field()
        s.to_call = Field.manual(to_call) if to_call is not None else Field()
        s.hero_to_act = Field.manual(True)
        return s

    bet = Advice("bet", "BET 7", "strong")
    check = Advice("check", "CHECK", "medium")
    assert w._steady(bet, st()).headline == "BET 7"
    assert w._steady(check, st()).headline == "BET 7"  # same spot read again: no flip
    assert w._steady(check, st(to_call=None)).headline == "BET 7"  # the price just wasn't read this time
    assert w._steady(Advice("unknown", "CONFIRM THE BOARD", "?"), st()).headline == "BET 7"
    call = Advice("call", "CALL 4", "price")
    assert w._steady(call, st(pot=14.0, to_call=4.0)).headline == "CALL 4"  # someone bet: new move
    assert w._steady(check, st(pot=14.0, board=("2h", "6c", "Tc", "Js"))).headline == "CHECK"  # new card
    w.close()


def test_check_turning_into_call_is_a_new_spot(qapp, tmp_home):
    """Kevin on 247: "the guy just bet and it's telling me to check". You check, the bot bets at
    once (its turn never captured), and the next read can't work out the price (247 prints no
    bets). Only the buttons changed, Check to Call: that is a bet, never a value merely lost."""
    from app.poker.advice import Advice
    from app.state.model import Action, Field, GameState

    w = MainWindow(Settings())

    def st(buttons, to_call):
        s = GameState(hero_cards=[Field.manual("Qd"), Field.manual("Th")],
                      board=[Field.manual(c) for c in ("2h", "6c", "Tc")])
        s.pot = Field.manual(10.0)
        s.to_call = Field.manual(to_call) if to_call is not None else Field()
        s.hero_to_act = Field.manual(True)
        s.available_actions = Field.manual(buttons) if buttons is not None else Field()
        return s

    check = Advice("check", "CHECK", "medium")
    call = Advice("call", "CALL UP TO 12", "price unknown")
    assert w._steady(check, st([Action("check"), Action("bet")], 0.0)).headline == "CHECK"
    assert w._steady(check, st(None, None)).headline == "CHECK"  # buttons not read once: keep the move
    assert w._steady(call, st([Action("fold"), Action("call"), Action("raise")], None)).headline == "CALL UP TO 12"
    w.close()
