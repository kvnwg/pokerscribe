"""Image -> GameState. Combines card recognition, OCR and layout analysis.

Every value gets a confidence. Values below the threshold become UNKNOWN (their
best guess is kept for the correction screen only).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from app.state.model import Field, GameState, Player
from app.state.positions import assign_positions
from app.vision.card_recognizer import CardReading, CardRecognizer
from app.vision.ocr import OcrEngine, TextBox

from .layout import LayoutResult, analyse


@dataclass
class RecognitionResult:
    state: GameState
    hero_readings: List[Optional[CardReading]]  # aligned with state.hero_cards
    board_readings: List[CardReading]  # aligned with state.board
    readings: List[CardReading]
    text_boxes: List[TextBox]
    layout: LayoutResult
    timings: Dict[str, float] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    ocr_engine: str = "none"


class TableRecognizer:
    def __init__(self, cards: CardRecognizer, ocr: Optional[OcrEngine], threshold: float = 0.70,
                 pot_includes_bets: bool = False):
        self.cards = cards
        self.ocr = ocr
        self.threshold = threshold
        self.pot_includes_bets = pot_includes_bets

    def recognize(self, image: np.ndarray) -> RecognitionResult:
        timings: Dict[str, float] = {}
        warnings: List[str] = []
        t = time.perf_counter()
        readings = self.cards.read(image)
        timings["cards"] = time.perf_counter() - t

        t = time.perf_counter()
        boxes: List[TextBox] = []
        if self.ocr is not None:
            try:
                boxes = self.ocr.read(image)
                boxes += self._big_amounts(image, boxes)
                boxes += self._big_light_text(image, boxes)
                boxes += self._short_amounts(image, boxes)
                boxes = self._verify_amounts(image, boxes)
            except Exception as exc:
                warnings.append(f"OCR failed: {exc}")
        else:
            warnings.append("No OCR engine available: amounts, seats and actions are UNKNOWN.")
        timings["ocr"] = time.perf_counter() - t
        failures = getattr(self.ocr, "failures", None)
        if failures:
            warnings.extend(f"OCR engine skipped ({f})" for f in failures)

        # a "card" whose corner index sits inside text with a currency sign is the pot or
        # a stack drawn in big white letters, not a card
        money = [b for b in boxes if any(sym in b.text for sym in "$€£")]
        readings = [r for r in readings if not (r.glyphs is not None and r.glyphs.rank is not None and any(
            m.x <= r.glyphs.rank.box[0] + r.glyphs.rank.box[2] / 2 <= m.x + m.w
            and m.y <= r.glyphs.rank.box[1] + r.glyphs.rank.box[3] / 2 <= m.y + m.h for m in money))]

        t = time.perf_counter()
        layout = analyse(image, readings, boxes)
        state = self._build_state(layout, has_ocr=self.ocr is not None and bool(boxes))
        timings["layout"] = time.perf_counter() - t
        warnings.extend(layout.warnings)

        hero_readings: List[Optional[CardReading]] = list(layout.hero_cards) + [None] * (2 - len(layout.hero_cards))
        warnings.extend(self._resolve_duplicates(state, hero_readings, layout.board))
        return RecognitionResult(
            state=state,
            hero_readings=hero_readings[:2],
            board_readings=list(layout.board),
            readings=readings,
            text_boxes=boxes,
            layout=layout,
            timings=timings,
            warnings=warnings,
            ocr_engine=getattr(self.ocr, "label", "none") if self.ocr else "none",
        )

    # ------------------------------------------------------------------
    def _card_field(self, r: Optional[CardReading]) -> Field:
        if r is None:
            return Field()
        return Field.auto(r.guess, r.confidence, self.threshold)

    def _build_state(self, lay: LayoutResult, has_ocr: bool) -> GameState:
        T = self.threshold
        st = GameState()
        st.hero_cards = [self._card_field(r) for r in lay.hero_cards[:2]]
        while len(st.hero_cards) < 2:
            st.hero_cards.append(Field())
        st.board = [self._card_field(r) for r in lay.board[:5]]
        street = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}.get(len(st.board))
        if street == "preflop":
            st.street = Field.auto(street, 0.92 if lay.hero_cards else 0.6, T)
        elif street:
            st.street = Field.auto(street, 0.96, T)
        else:
            st.street = Field(None, 0.3, "auto")  # 1-2 board cards: probably mid-animation

        if lay.pot is not None:
            st.pot = Field.auto(lay.pot.value, lay.pot_conf, T)
        st.pot_includes_bets = bool(lay.pot_is_total) or self.pot_includes_bets
        if lay.blinds:
            st.blinds = Field.auto(tuple(lay.blinds), lay.blinds_conf, T)

        positions: Dict[int, str] = {}
        if lay.button_seat is not None and len(lay.seats) >= 2:
            positions = assign_positions(list(range(len(lay.seats))), lay.button_seat)
        pos_conf = lay.button_conf * 0.95

        # If this client shows bet amounts (some seat has one), a seat without one has bet
        # nothing. If no amounts are visible at all (chips drawn without numbers), we can't tell.
        bets_visible = any(s.bet is not None or (s.action is not None and s.action.amount is not None)
                           for s in lay.seats)
        no_bet_conf = 0.75 if bets_visible else 0.6
        players: List[Player] = []
        for i, s in enumerate(lay.seats):
            p = Player(seat=i, is_hero=s.is_hero, name=s.name, anchor=s.center)
            if s.stack is not None:
                p.stack = Field.auto(s.stack.value, s.stack_conf, T)
            tagged = (s.action.amount if s.action is not None and s.action.amount is not None
                      and s.action.kind in ("bet", "call", "raise", "all-in") else None)
            if s.bet is not None:
                value, conf = s.bet.value, s.bet_conf
                if tagged is not None and abs(tagged - value) < 1e-6:
                    conf = min(0.97, max(conf, s.action_conf * 0.9) + 0.1)  # chips and tag agree
                elif tagged is not None and s.action_conf * 0.9 > conf:
                    value, conf = tagged, s.action_conf * 0.9
                p.bet = Field.auto(value, conf, T)
            elif tagged is not None:
                p.bet = Field.auto(tagged, s.action_conf * 0.9, T)
            elif has_ocr:
                p.bet = Field.auto(0.0, no_bet_conf, T)  # nothing in front of this seat
            if s.action is not None:
                p.last_action = Field.auto(s.action, s.action_conf, T)
            if s.is_hero:
                if lay.hero_cards:
                    p.in_hand = Field.auto(True, 0.95, T)
            elif s.action is not None and s.action.kind == "fold":
                p.in_hand = Field.auto(False, max(0.75, s.action_conf), T)
            elif s.has_cards is not None:
                p.in_hand = Field.auto(s.has_cards, s.cards_conf, T)
            elif s.action is not None or (s.bet is not None and s.bet.value > 0):
                p.in_hand = Field.auto(True, 0.75, T)
            if i in positions:
                p.position = Field.auto(positions[i], pos_conf, T)
            players.append(p)
        if not any(p.is_hero for p in players):
            hero = Player(seat=-1, is_hero=True)
            if lay.hero_cards:
                hero.in_hand = Field.auto(True, 0.95, T)
            players.insert(0, hero)
        st.players = players

        hero_acting = lay.acting_seat is not None and lay.seats[lay.acting_seat].is_hero
        if lay.hero_to_act is True:
            conf = lay.hero_to_act_conf
            if hero_acting:  # the buttons and the timer on your seat agree
                conf = max(conf, min(0.95, 0.5 * (conf + lay.acting_conf) + 0.1))
            st.hero_to_act = Field.auto(True, conf, T)
            st.available_actions = Field.auto(list(lay.actions), max(lay.actions_conf, conf if hero_acting else 0.0), T)
        elif lay.hero_to_act is False:
            st.hero_to_act = Field.auto(False, lay.hero_to_act_conf, T)
            st.available_actions = Field.auto([], lay.hero_to_act_conf, T)
        elif lay.acting_seat is not None and not lay.seats[lay.acting_seat].is_hero:
            # the timer bar or glow is on another seat and no buttons are showing
            st.hero_to_act = Field.auto(False, lay.acting_conf, T)
            st.available_actions = Field.auto([], lay.acting_conf, T)

        st.to_call = self._to_call(st, lay)
        return st

    def _verify_amounts(self, image: np.ndarray, boxes: List[TextBox]) -> List[TextBox]:
        """Read every amount a second time from just that spot. A number is only trusted
        when two reads agree; if the first two differ, a zoomed-in read decides, and with
        no majority the number is left UNKNOWN.

        One more check: when nearly every amount on the table starts with "$", an amount
        without it that starts with a 5 or an S is probably "$998" read as "5998"."""
        import re

        import cv2

        from .amounts import parse_amount

        H, W = image.shape[:2]
        amounts = [b for b in boxes if parse_amount(b.text) is not None]
        with_symbol = [b for b in amounts if re.match(r"^\s*[$€£]", b.text)]
        uses_symbol = len(amounts) >= 3 and len(with_symbol) >= 0.6 * len(amounts)
        out: List[TextBox] = []
        for b in boxes:
            first = parse_amount(b.text)
            if first is None:
                out.append(b)
                continue
            digits = re.sub(r"[^0-9A-Za-z]", "", b.text)
            suspicious = uses_symbol and not re.match(r"^\s*[$€£]", b.text) and re.match(r"^[5S8s]\d{2,}", digits)
            reads = [] if suspicious else [(first.value, b.text, b.confidence)]
            tries = [("line", 0.25), ("line", 0.6), ("zoom", 0.4)]
            decided = None
            for how, pad in tries:
                px, py = max(3, int(pad * b.h)), max(2, int(0.5 * pad * b.h))
                crop = image[max(0, b.y - py): min(H, b.y + b.h + py), max(0, b.x - px): min(W, b.x + b.w + px)]
                if crop.size == 0:
                    continue
                if how == "line":
                    line = self.ocr.read_line(crop)
                else:
                    big = cv2.resize(crop, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
                    found = sorted(self.ocr.read(big), key=lambda t: t.x)
                    line = ("".join(t.text for t in found), min(t.confidence for t in found)) if found else None
                if not line or (uses_symbol and not re.match(r"^\s*[$€£]", line[0])):
                    continue  # this read lost the "$": don't count it
                amount = parse_amount(line[0])
                if amount is not None:
                    reads.append((amount.value, line[0], line[1]))
                values = [r[0] for r in reads]
                agreed = [v for v in values if values.count(v) >= 2]
                if agreed:
                    same = [r for r in reads if r[0] == agreed[0]]
                    text = b.text if b.text in [r[1] for r in same] else max(same, key=lambda r: r[2])[1]
                    decided = TextBox(text, max(r[2] for r in same), b.x, b.y, b.w, b.h)
                    break
            out.append(decided or TextBox(b.text, min(b.confidence, 0.2), b.x, b.y, b.w, b.h))
        return out

    def _big_light_text(self, image: np.ndarray, boxes: List[TextBox]) -> List[TextBox]:
        """Big white numbers in the middle of the felt (a pot like "$3") that the text
        finder missed: found as light strokes, then read directly."""
        import cv2

        from .amounts import parse_amount

        H, W = image.shape[:2]
        if not boxes:
            return []
        median_h = float(np.median([b.h for b in boxes]))
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        light = ((hsv[..., 2] >= 200) & (hsv[..., 1] <= 60)).astype(np.uint8)
        n, _, stats, _ = cv2.connectedComponentsWithStats(light, connectivity=8)
        comps = []
        for i in range(1, n):
            x, y, w, h, area = (int(v) for v in stats[i])
            if not (1.6 * median_h <= h <= 6 * median_h and w <= 2.5 * h):
                continue
            if area > 0.6 * w * h:
                continue  # solid shapes (cards, buttons) are not letters
            if not (0.12 * W <= x + w / 2 <= 0.88 * W and 0.03 * H <= y + h / 2 <= 0.78 * H):
                continue
            comps.append([x, y, w, h])
        comps.sort()
        lines: List[List[int]] = []
        for c in comps:
            for ln in lines:
                lx, ly, lw, lh = ln
                overlap = min(ly + lh, c[1] + c[3]) - max(ly, c[1])
                if overlap > 0.6 * min(lh, c[3]) and 0 <= c[0] - (lx + lw) < 0.8 * lh:
                    nx, ny = min(lx, c[0]), min(ly, c[1])
                    ln[:] = [nx, ny, max(lx + lw, c[0] + c[2]) - nx, max(ly + lh, c[1] + c[3]) - ny]
                    break
            else:
                lines.append(list(c))
        out: List[TextBox] = []
        for x, y, w, h in lines:
            if any(x < b.x + b.w and b.x < x + w and y < b.y + b.h and b.y < y + h for b in boxes + out):
                continue  # already read
            px, py = int(0.3 * h), int(0.15 * h)
            crop = image[max(0, y - py): min(H, y + h + py), max(0, x - px): min(W, x + w + px)]
            line = self.ocr.read_line(crop) if crop.size else None
            if line and line[1] >= 0.5 and parse_amount(line[0]) is not None and any(ch.isdigit() for ch in line[0]):
                out.append(TextBox(line[0], line[1], x, y, w, h))
        return out

    def _short_amounts(self, image: np.ndarray, boxes: List[TextBox]) -> List[TextBox]:
        """Short amounts on the felt that the text finder skipped ("$2", a lone "6" by a bet's
        chip): light text of the usual height that no box covers, read directly. A bet that
        isn't found counts as no bet at all, so a missed "6" would turn a raise into nothing."""
        import unicodedata

        import cv2

        from .amounts import parse_amount

        H, W = image.shape[:2]
        if not boxes:
            return []
        median_h = float(np.median([b.h for b in boxes]))
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        light = ((hsv[..., 2] >= 190) & (hsv[..., 1] <= 70)).astype(np.uint8)
        n, _, stats, _ = cv2.connectedComponentsWithStats(light, connectivity=8)
        comps = []
        for i in range(1, n):
            x, y, w, h, area = (int(v) for v in stats[i])
            if not (0.45 * median_h <= h <= 1.3 * median_h and w <= 1.5 * h):
                continue
            if 0.8 <= w / h <= 1.25 and (area < 0.35 * w * h or area > 0.5 * w * h and h >= median_h):
                continue  # round: a chip's outline, or the dealer button
            if area > 0.75 * w * h:
                continue  # solid: a card or a button
            if not (0.1 * W <= x + w / 2 <= 0.9 * W and 0.1 * H <= y + h / 2 <= 0.88 * H):
                continue
            comps.append([x, y, w, h])
        comps.sort()
        lines: List[List[int]] = []
        for c in comps:
            for ln in lines:
                lx, ly, lw, lh = ln
                overlap = min(ly + lh, c[1] + c[3]) - max(ly, c[1])
                if overlap > 0.5 * min(lh, c[3]) and 0 <= c[0] - (lx + lw) < 0.6 * max(lh, c[3]):
                    nx, ny = min(lx, c[0]), min(ly, c[1])
                    ln[:] = [nx, ny, max(lx + lw, c[0] + c[2]) - nx, max(ly + lh, c[1] + c[3]) - ny]
                    break
            else:
                lines.append(list(c))
        out: List[TextBox] = []
        for x, y, w, h in lines:
            if w > 6 * h or any(x < b.x + b.w and b.x < x + w and y < b.y + b.h and b.y < y + h for b in boxes):
                continue
            px, py = int(0.6 * h), int(0.35 * h)
            crop = image[max(0, y - py): min(H, y + h + py), max(0, x - px): min(W, x + w + px)]
            line = self.ocr.read_line(crop) if crop.size else None
            if not line:
                continue
            text = unicodedata.normalize("NFKC", line[0]).strip()
            amount = parse_amount(text)
            if amount is not None and amount.value > 0 and any(ch.isdigit() for ch in text):
                out.append(TextBox(text, line[1], x, y, w, h))
        return out

    def _big_amounts(self, image: np.ndarray, boxes: List[TextBox]) -> List[TextBox]:
        """Large amounts in the middle of the table (a pot drawn as "$3" in big letters)
        can be missed at full resolution; a half-size pass over the centre finds them."""
        import cv2

        from .amounts import parse_amount

        H, W = image.shape[:2]
        x0, x1, y0, y1 = int(0.15 * W), int(0.85 * W), int(0.05 * H), int(0.75 * H)
        if x1 - x0 < 40 or y1 - y0 < 40:
            return []
        small = cv2.resize(image[y0:y1, x0:x1], None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        median_h = float(np.median([b.h for b in boxes])) if boxes else 14.0
        out: List[TextBox] = []
        for b in self.ocr.read(small):
            bx, by, bw, bh = x0 + 2 * b.x, y0 + 2 * b.y, 2 * b.w, 2 * b.h
            if bh < 1.5 * median_h or parse_amount(b.text) is None:
                continue  # small text is read better at full size
            if any(bx < o.x + o.w and o.x < bx + bw and by < o.y + o.h and o.y < by + bh for o in boxes):
                continue  # already read
            out.append(TextBox(b.text, b.confidence, bx, by, bw, bh))
        return out

    def _to_call(self, st: GameState, lay: LayoutResult) -> Field:
        T = self.threshold
        if lay.actions:
            kinds = {a.kind: a for a in lay.actions}
            if "check" in kinds:
                return Field.auto(0.0, lay.actions_conf, T)
            if "call" in kinds and kinds["call"].amount is not None:
                return Field.auto(kinds["call"].amount, lay.actions_conf, T)
            if "all-in" in kinds and kinds["all-in"].amount is not None and "call" not in kinds:
                return Field.auto(kinds["all-in"].amount, lay.actions_conf * 0.85, T)
        hero = st.hero
        opp_bets = [p.bet for p in st.opponents]
        if hero is None or not opp_bets or not hero.bet.known or any(not b.known for b in opp_bets):
            return Field()
        conf = min([hero.bet.confidence] + [b.confidence for b in opp_bets]) * 0.95
        value = max(0.0, max(float(b.value) for b in opp_bets) - float(hero.bet.value))
        if hero.stack.known:
            value = min(value, float(hero.stack.value))
        return Field.auto(value, conf, T)

    @staticmethod
    def _resolve_duplicates(st: GameState, hero_readings, board_readings) -> List[str]:
        """The same card cannot appear twice: keep the more confident read, drop the other."""
        warnings = []
        fields = list(zip(st.hero_cards, hero_readings)) + list(zip(st.board, board_readings))
        seen: Dict[str, Field] = {}
        for f, _ in fields:
            if not f.known:
                continue
            other = seen.get(f.value)
            if other is None:
                seen[f.value] = f
                continue
            loser = f if f.confidence <= other.confidence else other
            if loser is other:
                seen[f.value] = f
            loser.guess, loser.value = loser.value, None
            loser.confidence = round(loser.confidence * 0.5, 3)
            warnings.append(f"Card {loser.guess} was read twice; the less certain read is now UNKNOWN.")
        return warnings
