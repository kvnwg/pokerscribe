"""Generic table-layout analysis from card detections and OCR text boxes.

Nothing here assumes a particular site. It relies on conventions shared by
almost every poker client:
  * the board is a row of 3-5 face-up cards near the middle of the table,
    and the hero's two cards are the face-up pair nearest the bottom;
  * each seat shows a short label (name or last action) with a stack amount
    right below it;
  * bets sit between a seat and the table centre; the pot is labelled "Pot";
  * the dealer button is a small round disc, usually marked "D";
  * the hero's action buttons (Fold / Check / Call / Bet / Raise) form a row at
    the bottom, while pre-action checkboxes ("Check/Fold", "Call any") mean it is
    not the hero's turn.
Anything that cannot be matched confidently is left out (and becomes UNKNOWN).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

from app.state.model import Action
from app.vision.card_recognizer import CardReading
from app.vision.ocr import TextBox

from .amounts import CURRENCY, Amount, first_amount, has_blinds_label, parse_amount, parse_blinds

# OCR often drops spaces: "Call60", "Raiseto$46"
ACTION_RE = re.compile(r"^\s*(fold|folds|check|checks|call|calls|bet|bets|raise\s*to|raises|raise|all[\s-]?in|allin)(?![a-z])", re.I)
PRE_ACTION_RE = re.compile(r"(check\s*/\s*fold|call\s*any|fold\s*to\s*any|check\s*/\s*call|fold\s*/\s*check|auto[\s-]?(check|fold|call))", re.I)
POT_RE = re.compile(r"\b(total\s*)?pot\b", re.I)  # "Total pot", and "Totalpot" when OCR drops the space
STATUS_RE = re.compile(r"(sitting\s*out|sit\s*out|empty\s*seat|open\s*seat|seat\s*open|disconnected|reserved|join)", re.I)
# "# 357,618,379", "Hand #123456789", "Hand ID: 12345678": a new number means a new hand
HAND_ID_RE = re.compile(r"(?:\bhand\b[^#\d]{0,6})?#\s*(\d[\d,.\s]{4,}\d)|\bhand\s*(?:id|no\.?|number)?\s*:?\s*(\d{6,})", re.I)
# your hand's strength written by your seat ("High Card", "Two Pair"): never a name
HAND_RANK_RE = re.compile(
    r"(?i)^\s*(high\s*card|one\s*pair|two\s*pairs?|three\s*of\s*a\s*kind|four\s*of\s*a\s*kind|full\s*house"
    r"|straight\s*flush|royal\s*flush|pair\s*of\b|(pair|trips|straight|flush|quads)\s*$)")
SIZING_RE = re.compile(r"^\s*(min|max|pot|\d/\d\s*pot|\d+(\.\d+)?\s*x|\d+\s*%)\s*$", re.I)


@dataclass
class Seat:
    label: TextBox  # name or action label shown on the nameplate
    stack_box: Optional[TextBox]
    stack: Optional[Amount]
    stack_conf: float
    status: Optional[str] = None  # "all-in", "sitting out"
    bet: Optional[Amount] = None
    bet_conf: float = 0.0
    bet_box: Optional[TextBox] = None
    action: Optional[Action] = None
    action_conf: float = 0.0
    has_cards: Optional[bool] = None
    cards_conf: float = 0.0
    is_hero: bool = False
    angle: float = 0.0
    name: str = ""

    @property
    def box(self) -> Tuple[int, int, int, int]:
        boxes = [b for b in (self.label, self.stack_box) if b is not None]
        x0 = min(b.x for b in boxes)
        y0 = min(b.y for b in boxes)
        x1 = max(b.right for b in boxes)
        y1 = max(b.bottom for b in boxes)
        return x0, y0, x1 - x0, y1 - y0

    @property
    def center(self) -> Tuple[float, float]:
        x, y, w, h = self.box
        return x + w / 2.0, y + h / 2.0


@dataclass
class LayoutResult:
    hero_cards: List[CardReading] = field(default_factory=list)
    board: List[CardReading] = field(default_factory=list)
    other_cards: List[CardReading] = field(default_factory=list)
    pot: Optional[Amount] = None
    pot_conf: float = 0.0
    pot_box: Optional[TextBox] = None
    pot_is_total: bool = False
    blinds: Optional[Tuple[float, float]] = None
    blinds_conf: float = 0.0
    seats: List[Seat] = field(default_factory=list)  # hero first, then clockwise
    button_seat: Optional[int] = None  # index into seats
    button_conf: float = 0.0
    button_box: Optional[Tuple[int, int, int, int]] = None
    hero_to_act: Optional[bool] = None
    hero_to_act_conf: float = 0.0
    actions: List[Action] = field(default_factory=list)
    actions_conf: float = 0.0
    action_boxes: List[TextBox] = field(default_factory=list)
    center: Tuple[float, float] = (0.0, 0.0)
    hand_id: Optional[str] = None  # the hand number shown by the client, digits only
    acting_seat: Optional[int] = None  # index into seats: timer bar or glow ring on it
    acting_conf: float = 0.0
    pictures: List[Tuple[float, float, float]] = field(default_factory=list)  # round player pictures (x, y, r)
    warnings: List[str] = field(default_factory=list)


# ----------------------------------------------------------------- cards
HERO_SPREAD = 0.25  # your cards lie within this share of the width from the middle


def split_cards(readings: List[CardReading], width: int, height: int) -> Tuple[List[CardReading], List[CardReading], List[CardReading]]:
    """Return (hero cards, board, other face-up cards)."""
    if not readings:
        return [], [], []
    med_h = float(np.median([r.box[3] for r in readings]))
    rows: List[List[CardReading]] = []
    for r in sorted(readings, key=lambda r: r.center[1]):
        for row in rows:
            ref = row[0]
            if abs(r.center[1] - ref.center[1]) < 0.35 * med_h and 0.7 < r.box[3] / max(1, ref.box[3]) < 1.4:
                row.append(r)
                break
        else:
            rows.append([r])
    for row in rows:
        row.sort(key=lambda r: r.box[0])

    def spread_ok(row):
        if len(row) < 2:
            return True
        gaps = [b.box[0] - (a.box[0] + a.box[2]) for a, b in zip(row, row[1:])]
        return max(gaps) < 1.6 * med_h

    def runs(row):
        """The row cut where a wide gap opens or the card size changes. At showdown a player
        beside the middle shows their cards on the board's line, smaller and apart from it:
        seven cards in a row were no board at all, and the board cards were then taken for that
        player's (a folded player at the top was read as still in)."""
        out = [[row[0]]]
        for a, b in zip(row, row[1:]):
            gap = b.box[0] - (a.box[0] + a.box[2])
            if gap < 1.6 * med_h and 0.85 <= b.box[3] / max(1, a.box[3]) <= 1.18:
                out[-1].append(b)
            else:
                out.append([b])
        return out

    board: List[CardReading] = []
    # board cards are all the same size: pieces of a card cut by something drawn over it
    # (43, 15 and 71 pixels wide) are not a board
    candidates = [run for row in rows for run in runs(row) if 3 <= len(run) <= 5 and spread_ok(run)
                  and max(r.box[2] for r in run) <= 1.35 * min(r.box[2] for r in run)
                  and 0.18 * height <= np.mean([r.center[1] for r in run]) <= 0.75 * height]
    if candidates:
        board = min(candidates, key=lambda row: abs(np.mean([r.center[1] for r in row]) - 0.45 * height))
    rest = [r for r in readings if r not in board]

    hero: List[CardReading] = []
    if rest:
        bottom = sorted(rest, key=lambda r: -r.center[1])
        anchor = min(bottom[:4], key=lambda r: abs(r.center[0] - width / 2) + 0.5 * (height - r.center[1]))
        # Clients turn the table so your seat is at the bottom middle. Face-up cards at
        # another seat are an opponent's, shown at showdown (after you folded, say).
        middle = abs(anchor.center[0] - width / 2) <= HERO_SPREAD * width
        if middle and anchor.center[1] > (np.mean([r.center[1] for r in board]) if board else 0.45 * height):
            hero = [anchor]
            partners = [r for r in rest if r is not anchor
                        and abs(r.center[1] - anchor.center[1]) < 0.5 * med_h
                        and abs(r.center[0] - anchor.center[0]) < 1.6 * med_h]
            if partners:
                hero.append(min(partners, key=lambda r: abs(r.center[0] - anchor.center[0])))
            hero.sort(key=lambda r: r.box[0])
    others = [r for r in readings if r not in board and r not in hero]
    return hero, board, others


# ------------------------------------------------------------------ main
def analyse(image: np.ndarray, readings: List[CardReading], boxes: List[TextBox]) -> LayoutResult:
    H, W = image.shape[:2]
    res = LayoutResult()
    res.hero_cards, res.board, res.other_cards = split_cards(readings, W, H)
    card_rects = [r.box for r in readings]

    def inside_card(b: TextBox) -> bool:
        return any(x - 2 <= b.cx <= x + w + 2 and y - 2 <= b.cy <= y + h + 2 for x, y, w, h in card_rects)

    boxes = [b for b in boxes if b.text.strip() and not inside_card(b)]
    if res.board:
        res.center = _board_middle(res.board)
    else:
        res.center = (W / 2.0, H * 0.45)
    med_text_h = float(np.median([b.h for b in boxes])) if boxes else 14.0
    used: set = set()

    res.pictures = _find_pictures(image, med_text_h)
    discs, badges = [], []
    for c in _button_discs(image, card_rects, med_text_h):
        (badges if _picture_disc(c, res.pictures) else discs).append(c)
    boxes = [_without_button(b, discs) for b in boxes]
    _find_hand_id(res, boxes, used)
    for b in boxes:
        # A level, a countdown or "Seat" drawn on a player's picture, or in a badge on its
        # rim, is never a name, a stack or a bet.
        if _on_picture(b, res.pictures, med_text_h) or any(
                x - 0.3 * b.h <= b.cx <= x + w + 0.3 * b.h and y - 0.3 * b.h <= b.cy <= y + h + 0.3 * b.h
                for _, (x, y, w, h) in badges):
            used.add(id(b))
    _find_action_buttons(res, boxes, used, W, H, med_text_h)
    _find_pot(res, boxes, used, W, H)
    _find_blinds(res, boxes, used)
    _find_seats(res, boxes, used, med_text_h)
    _your_seat_without_name(res, boxes, used)
    _assign_hero_and_order(res, W, H)
    _assign_bets(res, boxes, used, W, H, image)
    _find_button(res, image, boxes, card_rects, med_text_h)
    _find_card_backs(res, image, boxes)
    _find_acting(res, image, boxes, med_text_h)
    return res


def _picture_disc(c, pictures) -> bool:
    """A bright disc centred inside a player's round picture or on its rim: the picture's own
    white rim, or a badge (a level) drawn over the rim. The dealer button sits beside the
    picture, its centre further out."""
    x, y, w, h = c[1]
    return any(math.hypot(x + w / 2 - px, y + h / 2 - py) < pr + 0.25 * w for px, py, pr in pictures)


def _without_button(b: TextBox, discs) -> TextBox:
    """The dealer button touching an amount is read with it ("$ 200D", then "$ 2000"): drop
    the character the button's disc covers."""
    t = b.text.strip()
    if len(t) < 2 or not re.search(r"\d", t):
        return b
    for _, (x, y, w, h) in discs:
        dcx, dcy = x + w / 2.0, y + h / 2.0
        if abs(dcy - b.cy) >= 0.6 * b.h:
            continue
        at_end = b.right - 1.3 * b.h <= dcx <= b.right + 0.3 * b.h
        at_start = b.x - 0.3 * b.h <= dcx <= b.x + 1.3 * b.h
        if at_end and at_start:  # a short box ("D19"): the end the disc is nearer
            at_end = b.right - dcx < dcx - b.x
        if at_end:
            return TextBox(t[:-1].rstrip(), b.confidence, b.x, b.y, max(1, b.w - w), b.h)
        if at_start:
            return TextBox(t[1:].lstrip(), b.confidence, b.x + w, b.y, max(1, b.w - w), b.h)
    return b


def _find_hand_id(res: LayoutResult, boxes, used) -> None:
    """The hand number ("# 357,618,379"): never an amount, and it changes with every hand."""
    for b in boxes:
        m = HAND_ID_RE.search(b.text)
        if m:
            used.add(id(b))
            digits = re.sub(r"\D", "", m.group(1) or m.group(2))
            if len(digits) >= 6:
                res.hand_id = digits
            return


def _find_action_buttons(res: LayoutResult, boxes, used, W, H, text_h) -> None:
    pre = [b for b in boxes if PRE_ACTION_RE.search(b.text)]
    for b in pre:
        used.add(id(b))
    low = [b for b in boxes if id(b) not in used and b.cy > 0.62 * H and ACTION_RE.match(b.text)]
    row: List[TextBox] = []
    for b in low:
        mates = sorted((o for o in low if abs(o.cy - b.cy) < 0.8 * max(b.h, o.h)), key=lambda o: o.x)
        # Buttons sit side by side. Action tags on two seat plates can share a line too
        # ("Call" at the lower left, "Fold" at the lower right), but far apart: split there.
        group: List[TextBox] = [mates[0]]
        for a, o in zip(mates, mates[1:]):
            # buttons across the bottom edge of a phone can be far apart
            reach = 0.5 * W if min(a.cy, o.cy) > 0.88 * H else 2.5 * max(a.w, o.w, 4 * text_h)
            if o.x - a.right > reach:
                if b in group:
                    break
                group = [o]
            else:
                group.append(o)
        if b in group and len(group) > len(row):
            row = group
    # Some clients stack the buttons one above the other at the right edge.
    for b in low:
        col = sorted((o for o in low if abs(o.cx - b.cx) < 0.5 * max(b.w, o.w, 2 * text_h)), key=lambda o: o.y)
        group = [col[0]]
        for a, o in zip(col, col[1:]):
            if o.y - a.bottom > 3.0 * max(text_h, a.h, o.h):
                if b in group:
                    break
                group = [o]
            else:
                group.append(o)
        if b in group and len(group) >= 2 and len(group) > len(row):
            row = group
    if len(row) < 2:
        # a single button counts only in the corner where clients put them: a lone action
        # word elsewhere is a seat's last-action tag. Not while pre-action boxes show (it
        # isn't your turn then), and not a word under a name ("All in" is a seat's status).
        corner = [b for b in low if b.cx > 0.55 * W and b.cy > 0.8 * H
                  and not _under_name_or_picture(b, boxes, res.pictures, text_h)]
        row = corner[:1] if len(corner) == 1 and not pre else []
    if row:
        actions = []
        for b in sorted(row, key=lambda b: b.x):
            a = Action.parse(b.text)
            if a is not None:
                actions.append(a)
                used.add(id(b))
        if actions and any(a.kind == "call" for a in actions) and not any(a.kind == "fold" for a in actions):
            actions.insert(0, Action("fold"))  # whenever a call is possible, so is folding
        if actions:
            res.actions = actions
            res.action_boxes = sorted(row, key=lambda b: b.x)
            res.actions_conf = round(min(0.97, 0.75 + 0.1 * len(actions)) * min(1.0, min(b.confidence for b in row) + 0.15), 3)
            res.hero_to_act = True
            res.hero_to_act_conf = res.actions_conf
            # bet-size boxes and sizing buttons next to the action buttons are not table amounts
            y0 = min(b.y for b in row) - 3.5 * text_h
            x0 = min(b.x for b in row) - 4 * text_h
            for b in boxes:
                if b.cy >= y0 and b.cx >= x0 and (parse_amount(b.text) or SIZING_RE.match(b.text)):
                    if parse_amount(b.text) and _under_name_or_picture(b, boxes, res.pictures, text_h):
                        continue  # your own stack (phones put the buttons right under it)
                    used.add(id(b))
    elif pre:
        res.hero_to_act = False
        res.hero_to_act_conf = 0.85
    for b in boxes:
        if SIZING_RE.match(b.text) and b.cy > 0.7 * H:
            used.add(id(b))


def _under_name_or_picture(b: TextBox, boxes, pictures, text_h: float) -> bool:
    """Right under a name or a round picture: a seat's stack."""
    for o in boxes:
        if o is b or parse_amount(o.text) or not re.search(r"[A-Za-z]", o.text):
            continue
        if ACTION_RE.match(o.text) or SIZING_RE.match(o.text) or PRE_ACTION_RE.search(o.text):
            continue
        if 0 <= b.y - o.bottom <= 1.2 * max(b.h, o.h) and abs(o.cx - b.cx) < 0.6 * max(o.w, b.w):
            return True
    return any(abs(b.cx - x) < r and -0.3 * text_h <= b.y - (y + r) <= 1.6 * text_h for x, y, r in pictures)


def _find_pot(res: LayoutResult, boxes, used, W, H) -> None:
    candidates = []
    for b in boxes:
        if id(b) in used or not POT_RE.search(b.text) or not (0.1 * H <= b.cy <= 0.8 * H):
            continue
        m = POT_RE.search(b.text)
        amount = first_amount(b.text[m.end():])
        partner = None
        if amount is None:
            # "Pot:" and the number read as separate boxes on the same line
            right = [o for o in boxes if id(o) not in used and o is not b and abs(o.cy - b.cy) < 0.6 * b.h
                     and 0 <= o.x - b.right < 2.5 * b.h and parse_amount(o.text)]
            if right:
                partner = min(right, key=lambda o: o.x)
                amount = parse_amount(partner.text)
            else:
                # "Pot Amt." with the amount on the line under it
                under = [o for o in boxes if id(o) not in used and o is not b and 0 <= o.y - b.bottom < 1.5 * b.h
                         and abs(o.cx - b.cx) < 0.6 * max(b.w, o.w) and parse_amount(o.text)]
                if under:
                    partner = min(under, key=lambda o: o.y)
                    amount = parse_amount(partner.text)
        if amount is None:
            continue
        dist = math.hypot(b.cx - res.center[0], b.cy - res.center[1])
        candidates.append((bool(m.group(1)), dist, b, partner, amount))
    if not candidates:
        _find_unlabelled_pot(res, boxes, used, W, H)
        return
    plain = [c for c in candidates if not c[0]]
    is_total, _, b, partner, amount = min(plain or candidates, key=lambda c: c[1])
    used.add(id(b))
    if partner is not None:
        used.add(id(partner))
    res.pot, res.pot_box, res.pot_is_total = amount, b, is_total
    conf = min(b.confidence, partner.confidence if partner else 1.0)
    res.pot_conf = round(min(0.98, 0.25 + 0.75 * conf) * amount.confidence_factor, 3)


def _find_unlabelled_pot(res: LayoutResult, boxes, used, W, H) -> None:
    """Some clients show the pot as a bare amount in the middle of the felt ("$5")."""
    heights = sorted(b.h for b in boxes) or [14]
    median_h = heights[len(heights) // 2]
    cx, cy = res.center
    best = None
    for b in boxes:
        if id(b) in used:
            continue
        amount = parse_amount(b.text)
        if amount is None or b.h < 1.3 * median_h or b.confidence < 0.4:
            continue
        if abs(b.cx - cx) > 0.22 * W or abs(b.cy - cy) > 0.3 * H:
            continue
        if _under_name_or_picture(b, boxes, res.pictures, median_h):
            # a seat's stack on the edge of the felt (the top seat of eight, before the flop
            # with no pot shown): taken for the pot, that seat was lost
            continue
        d = math.hypot(b.cx - cx, b.cy - cy)
        if best is None or d < best[0]:
            best = (d, b, amount)
    if best is None:
        return
    _, b, amount = best
    used.add(id(b))
    res.pot, res.pot_box = amount, b
    # a big lone amount in the middle of the felt is almost always the pot
    res.pot_conf = round(min(0.9, 0.5 + 0.45 * b.confidence) * amount.confidence_factor, 3)
    res.warnings.append("Pot read from an unlabelled amount in the middle of the table.")


def _find_blinds(res: LayoutResult, boxes, used) -> None:
    for b in boxes:
        if id(b) in used:
            continue
        if not has_blinds_label(b.text):
            continue  # "11/26" or "3/5" on its own is a date or a count: the blinds come from the chips then
        blinds = parse_blinds(b.text)
        if blinds:
            used.add(id(b))
            res.blinds = blinds
            res.blinds_conf = round(0.92 * min(1.0, b.confidence + 0.15), 3)
            return


def _find_seats(res: LayoutResult, boxes, used, text_h) -> None:
    amounts = [(b, parse_amount(b.text)) for b in boxes if id(b) not in used]
    amounts = [(b, a) for b, a in amounts if a is not None]
    all_in = [b for b in boxes if id(b) not in used and re.fullmatch(r"(?i)\s*all[\s-]?in\s*", b.text)]
    labels = [b for b in boxes if id(b) not in used and parse_amount(b.text) is None and b not in all_in
              and re.search(r"[A-Za-z0-9]", b.text)]
    pairs = []
    # "All in" can also stand where the name was (clients that show the last action there)
    for lab in labels + all_in:
        for amt_box, amt in amounts + [(b, None) for b in all_in]:
            if amt_box is lab:
                continue
            for below in (True, False):
                gap = amt_box.y - lab.bottom if below else lab.y - amt_box.bottom
                lh = max(lab.h, amt_box.h)
                if -0.4 * lh <= gap <= 1.2 * lh and abs(amt_box.cx - lab.cx) < 0.6 * max(lab.w, amt_box.w, 2 * lh):
                    score = gap / lh + abs(amt_box.cx - lab.cx) / max(lab.w, 1) + (0 if below else 0.5)
                    if any(lab is a for a in all_in):
                        score += 1.0 + (0 if below else 2.0)  # a name above "All in" comes first
                    pairs.append((score, lab, amt_box, amt))
    # A name above a round picture with the stack under it (phone tables): the picture sits
    # between them, further apart than a name and its stack usually are.
    for x, y, r in res.pictures:
        def near(b, x=x, r=r):
            return abs(b.cx - x) < max(r, 0.6 * b.w)
        above = [lab for lab in labels if near(lab) and -0.3 * text_h <= (y - r) - lab.bottom <= 1.6 * text_h]
        under = [(b, a) for b, a in amounts + [(b, None) for b in all_in]
                 if near(b) and -0.3 * text_h <= b.y - (y + r) <= 1.6 * text_h]
        if not above or not under:
            continue
        lab = min(above, key=lambda o: (y - r) - o.bottom)
        amt_box, amt = min(under, key=lambda o: o[0].y)
        if any(o is not lab and near(o) and o.y >= y + r - 0.3 * text_h and o.bottom <= amt_box.y + 2 for o in labels):
            continue  # the name is under the picture: the usual name-over-stack pairing does it
        pairs.append((-1.0, lab, amt_box, amt))
    pairs.sort(key=lambda p: p[0])
    taken: set = set()
    for _, lab, amt_box, amt in pairs:
        if id(lab) in taken or id(amt_box) in taken:
            continue
        if STATUS_RE.search(lab.text):
            continue
        taken.update({id(lab), id(amt_box)})
        action = Action.parse(lab.text) if ACTION_RE.match(lab.text) else None
        seat = Seat(
            label=lab,
            stack_box=amt_box,
            stack=amt if amt is not None else Amount(0.0, "chips", "All-in"),
            stack_conf=round(min(0.97, 0.2 + 0.8 * amt_box.confidence) * (amt.confidence_factor if amt else 1.0), 3),
            status="all-in" if amt is None else None,
            action=action,
            action_conf=round(min(0.95, 0.3 + 0.7 * lab.confidence), 3) if action else 0.0,
            name="" if action else lab.text,
        )
        res.seats.append(seat)
    # A name with a number under it that couldn't be read ("$25¡") is still a seat: leaving
    # it out would shift every position after it. Its stack is UNKNOWN.
    for lab in labels:
        if id(lab) in taken or STATUS_RE.search(lab.text) or ACTION_RE.match(lab.text) or len(lab.text.strip()) < 2:
            continue
        under = [b for b in boxes if id(b) not in used and id(b) not in taken and b is not lab
                 and re.search(r"\d", b.text) and _number_like(b.text) and 0 <= b.y - lab.bottom <= 1.2 * max(lab.h, b.h)
                 and abs(b.cx - lab.cx) < 0.6 * max(lab.w, b.w)]
        if not under:
            continue
        b = min(under, key=lambda o: o.y - lab.bottom)
        taken.update({id(lab), id(b)})
        res.seats.append(Seat(label=lab, stack_box=b, stack=None, stack_conf=0.0, name=lab.text))
    for s in res.seats:
        if HAND_RANK_RE.match(s.label.text):
            # the hand's strength sits where a name would (beside your picture): the name is
            # the text nearest it, under or over the picture
            names = [lab for lab in labels if id(lab) not in taken and not HAND_RANK_RE.match(lab.text)
                     and not STATUS_RE.search(lab.text) and not ACTION_RE.match(lab.text)
                     and math.hypot(lab.cx - s.label.cx, lab.cy - s.label.cy) < 5 * text_h]
            if names:
                name = min(names, key=lambda o: math.hypot(o.cx - s.label.cx, o.cy - s.label.cy))
                s.name = name.text
                taken.add(id(name))
                used.add(id(name))
            else:
                s.name = ""
        used.add(id(s.label))
        used.add(id(s.stack_box))
    # action badges near a nameplate ("Bet 60" above the name)
    for b in boxes:
        if id(b) in used or not ACTION_RE.match(b.text):
            continue
        best, best_d = None, None
        for s in res.seats:
            sx, sy, sw, sh = s.box
            if sx - 0.4 * sw <= b.cx <= sx + 1.4 * sw and sy - 2.8 * text_h <= b.cy <= sy + sh + 1.5 * text_h:
                d = math.hypot(b.cx - s.center[0], b.cy - s.center[1])
                if best is None or d < best_d:
                    best, best_d = s, d
        if best is not None and best.action is None:
            best.action = Action.parse(b.text)
            best.action_conf = round(min(0.95, 0.3 + 0.7 * b.confidence), 3)
            used.add(id(b))


def _your_seat_without_name(res: LayoutResult, boxes, used) -> None:
    """Your name can be missed (drawn across the edge of the table, say), and then your seat is
    lost and the seat beside you taken for yours. With your cards showing and no seat under
    them, a stack just under your cards that nothing claimed is your seat."""
    if not res.hero_cards:
        return
    hx = float(np.mean([r.center[0] for r in res.hero_cards]))
    bottom = max(r.box[1] + r.box[3] for r in res.hero_cards)
    card_w = float(np.mean([r.box[2] for r in res.hero_cards]))
    card_h = float(np.mean([r.box[3] for r in res.hero_cards]))
    if any(abs(s.center[0] - hx) < 1.5 * card_w and -card_h <= s.center[1] - bottom <= 2 * card_h for s in res.seats):
        return
    under = [b for b in boxes if id(b) not in used and parse_amount(b.text) is not None
             and bottom - 0.3 * card_h <= b.y <= bottom + 1.6 * card_h and abs(b.cx - hx) < 1.2 * card_w]
    if not under:
        return
    b = min(under, key=lambda o: o.y)
    amt = parse_amount(b.text)
    label = TextBox("", 0.0, b.x, int(b.y - 1.1 * b.h), b.w, b.h)  # where the name was
    res.seats.append(Seat(label=label, stack_box=b, stack=amt,
                          stack_conf=round(min(0.97, 0.2 + 0.8 * b.confidence) * amt.confidence_factor, 3)))
    used.add(id(b))
    res.warnings.append("Your name was not read: your seat is the stack under your cards.")


def _number_like(text: str) -> bool:
    """A misread amount ("$25¡", "1,2O0"), not a percentage, a count or a ratio ("+100%",
    "300512 / 512000")."""
    t = text.strip()
    if not t or re.search(r"[%+/:]", t) or not re.search(r"\d", t):
        return False
    return sum(ch.isalpha() for ch in t) <= 0.5 * len(t)


def _assign_hero_and_order(res: LayoutResult, W, H) -> None:
    if not res.seats:
        return
    cx, cy = res.center
    for s in res.seats:
        x, y = s.center
        s.angle = math.degrees(math.atan2(y - cy, x - cx)) % 360.0
    hero = None
    if res.hero_cards:
        hx = float(np.mean([r.center[0] for r in res.hero_cards]))
        hy = float(np.mean([r.box[1] + r.box[3] for r in res.hero_cards]))
        card_h = float(np.mean([r.box[3] for r in res.hero_cards]))
        near = [s for s in res.seats if math.hypot(s.center[0] - hx, s.center[1] - hy) < 3.0 * card_h]
        if near:
            hero = min(near, key=lambda s: math.hypot(s.center[0] - hx, s.center[1] - hy))
    bottom = [s for s in res.seats if 0.3 * W <= s.center[0] <= 0.7 * W]
    # clients put your seat at the bottom middle: the seat nearest that spot (another seat
    # can sit lower, off to one side)
    mid = min(bottom, key=lambda s: abs(s.center[0] - W / 2) + 0.5 * (H - s.center[1])) if bottom else None
    if (hero is not None and mid is not None and mid is not hero and mid.center[1] > 0.5 * H
            and abs(mid.center[0] - W / 2) + 0.1 * W < abs(hero.center[0] - W / 2)):
        # the face-up cards lie beside a seat off to the side, with a seat in the bottom
        # middle: an opponent's cards shown at showdown (after you folded), not yours
        res.other_cards = res.other_cards + res.hero_cards
        res.hero_cards = []
        hero = None
    if hero is None and mid is not None:
        hero = mid
        res.warnings.append("Hero seat guessed from layout (no hero cards near a nameplate).")
    if hero is None:
        res.warnings.append("Could not tell which seat is the hero.")
        res.seats.sort(key=lambda s: s.angle)
        return
    hero.is_hero = True
    ref = hero.angle
    res.seats.sort(key=lambda s: (s.angle - ref) % 360.0)


def _assign_bets(res: LayoutResult, boxes, used, W, H, image: Optional[np.ndarray] = None) -> None:
    if not res.seats:
        return
    cx, cy = res.center
    diag = math.hypot(W, H)
    candidates = []
    for b in boxes:
        if id(b) in used:
            continue
        amt = parse_amount(b.text)
        if amt is None:
            continue
        if res.pot_box is not None and _next_to(b, res.pot_box):
            continue  # the pot's own number, read apart from its label
        if _beside_seat_text(b, res.seats) and not _chip_before(image, b, boxes):
            continue  # a level or rank on the nameplate, next to the name or the stack
        best, best_d = None, None
        for s in res.seats:
            sx, sy = s.center
            vx, vy = cx - sx, cy - sy
            L2 = vx * vx + vy * vy
            if L2 <= 1:
                continue
            t = ((b.cx - sx) * vx + (b.cy - sy) * vy) / L2
            if not 0.05 <= t <= BET_REACH:
                continue
            px, py = sx + t * vx, sy + t * vy
            d = math.hypot(b.cx - px, b.cy - py)
            if d < 0.12 * diag and (best is None or d < best_d):
                best, best_d = s, d
        if best is not None:
            candidates.append((best_d, best, b, amt))
    candidates.sort(key=lambda c: c[0])
    for d, seat, b, amt in candidates:
        if seat.bet is not None:
            continue
        seat.bet, seat.bet_box = amt, b
        seat.bet_conf = round(min(0.95, 0.2 + 0.8 * b.confidence) * amt.confidence_factor * (1.0 if d < 0.06 * diag else 0.85), 3)
        used.add(id(b))


def _beside_seat_text(b: TextBox, seats: List[Seat]) -> bool:
    """On the same line as a seat's name or stack and next to it: part of the nameplate
    (a player level, a rank), never a bet. Bets lie apart, toward the middle. An amount with a
    currency sign is no level: on a crowded table (eight on a phone) a bet can sit beside the
    next seat's name, and dropping it lost the blinds."""
    if re.search(f"[{CURRENCY}]", b.text):
        return False
    for s in seats:
        for t in (s.label, s.stack_box):
            if t is None or t is b:
                continue
            h = max(b.h, t.h)
            if abs(b.cy - t.cy) < 0.6 * h and max(b.x - t.right, t.x - b.right) < 3.0 * h:
                return True
    return False


def _chip_before(image: Optional[np.ndarray], b: TextBox, boxes) -> bool:
    """A chip picture just before the number, about as big as the text: the number is a bet.
    On a crowded table a bet can lie beside the next seat's name or stack, where a level would
    be; the chip tells them apart (a level has none). The currency sign doesn't always: in some
    fonts the OCR loses the "$" next to the chip ("200")."""
    if image is None:
        return False
    H, W = image.shape[:2]
    h = b.h
    x0, x1 = int(max(0, b.x - 2.0 * h)), int(min(W, b.x + 0.2 * h))
    y0, y1 = int(max(0, b.cy - 1.0 * h)), int(min(H, b.cy + 1.0 * h))
    roi = image[y0:y1, x0:x1].astype(np.int16)
    if roi.shape[0] < 4 or roi.shape[1] < 4:
        return False
    bg = np.median(roi.reshape(-1, 3), axis=0)
    diff = (np.abs(roi - bg).sum(axis=-1) > 60).astype(np.uint8)
    for t in boxes:  # other text (a name, a stack) is no chip
        if t is not b:
            diff[max(0, t.y - y0): max(0, t.bottom - y0), max(0, t.x - x0): max(0, t.right - x0)] = 0
    n, _, stats, _ = cv2.connectedComponentsWithStats(diff, connectivity=8)
    for i in range(1, n):
        cx, cy, cw, ch, area = (int(v) for v in stats[i])
        if not (0.5 * h <= cw <= 1.6 * h and 0.5 * h <= ch <= 1.6 * h and 0.6 <= cw / ch <= 1.6):
            continue
        if area < 0.5 * cw * ch:
            continue  # a ring or a letter's stroke, not a solid chip
        if x0 + cx + cw > b.x + 0.3 * h or b.x - (x0 + cx + cw) > 0.9 * h:
            continue  # not just before the number
        if abs((y0 + cy + ch / 2) - b.cy) > 0.5 * h:
            continue
        return True
    return False


# A bet lies between its seat and the middle, at most this share of the way. Further in, by the
# board, is the collected pot (chips from earlier rounds): never a seat's bet.
BET_REACH = 0.65


def _next_to(b: TextBox, label: TextBox) -> bool:
    """On the same line as the label and touching it (a bet elsewhere on that line is a bet)."""
    if abs(b.cy - label.cy) >= 0.8 * max(b.h, label.h):
        return False
    gap = max(b.x - label.right, label.x - b.right)
    return gap < 1.5 * max(b.h, label.h)


def _find_button(res: LayoutResult, image: np.ndarray, boxes, card_rects, text_h) -> None:
    if not res.seats:
        return
    candidates: List[Tuple[float, Tuple[int, int, int, int]]] = []
    for b in boxes:
        if b.text.strip() in ("D", "DEALER", "Dealer", "BTN") and b.w < 4 * b.h:
            pad = int(0.3 * b.h)
            candidates.append((0.9, (b.x - pad, b.y - pad, b.w + 2 * pad, b.h + 2 * pad)))
    # the white rim of a player's round picture is a bright disc too, and so is a level
    # badge on the rim: not the button
    candidates.extend(c for c in _button_discs(image, card_rects, text_h) if not _picture_disc(c, res.pictures))
    if not candidates:
        return
    score, rect = max(candidates, key=lambda c: c[0])
    bx, by = rect[0] + rect[2] / 2.0, rect[1] + rect[3] / 2.0
    dists = sorted((math.hypot(s.center[0] - bx, s.center[1] - by), i) for i, s in enumerate(res.seats))
    d0, idx = dists[0]
    ratio = d0 / dists[1][0] if len(dists) > 1 and dists[1][0] > 0 else 0.0
    sw = res.seats[idx].box[2]
    if d0 > 2.5 * max(sw, 4 * text_h):
        return
    res.button_seat = idx
    res.button_box = rect
    res.button_conf = round(score * (0.97 if ratio < 0.55 else 0.85 if ratio < 0.75 else 0.6), 3)


def _button_discs(image: np.ndarray, card_rects, text_h) -> List[Tuple[float, Tuple[int, int, int, int]]]:
    """Small bright round discs with a dark mark inside: dealer-button candidates."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    bright = ((hsv[..., 2] >= 185)).astype(np.uint8) * 255
    contours, _ = cv2.findContours(bright, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    lo, hi = max(8.0, 0.8 * text_h), max(20.0, 3.2 * text_h)
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if not (lo <= w <= hi and lo <= h <= hi and 0.75 <= w / float(h) <= 1.33):
            continue
        if any(cx - 2 <= x + w / 2 <= cx + cw + 2 and cy - 2 <= y + h / 2 <= cy + ch + 2 for cx, cy, cw, ch in card_rects):
            continue
        area = cv2.contourArea(c)
        perim = cv2.arcLength(c, True)
        if perim <= 0:
            continue
        hull_area = cv2.contourArea(cv2.convexHull(c))
        circularity = 4 * math.pi * hull_area / (cv2.arcLength(cv2.convexHull(c), True) ** 2 + 1e-6)
        if circularity < 0.8:
            continue
        inner = hsv[y + h // 5: y + h - h // 5, x + w // 5: x + w - w // 5, 2]
        dark = float((inner < 120).mean()) if inner.size else 0.0
        if not 0.06 <= dark <= 0.6:
            continue
        out.append((round(0.55 + 0.35 * min(1.0, (circularity - 0.8) / 0.15), 3), (x, y, w, h)))
    return out


FELT_SHARE = 0.12  # a coloured felt covers at least this share of the table picture


def _felt_hue(hsv: np.ndarray) -> Optional[float]:
    """The felt's hue, or None for a grey or black felt. On a grey felt the few coloured
    things (card backs, your plate, chips) must not be taken for the felt."""
    sat = (hsv[..., 1] > 60) & (hsv[..., 2] > 40)
    if sat.sum() < 100:
        return None
    hist = np.bincount(hsv[..., 0][sat].ravel(), minlength=180)
    smooth = np.convolve(np.r_[hist[-5:], hist, hist[:5]], np.ones(5), "same")[5:-5]
    peak = int(np.argmax(smooth))
    hue = hsv[..., 0].astype(np.int16)
    near = sat & (np.minimum(np.abs(hue - peak), 180 - np.abs(hue - peak)) <= 10)
    if near.mean() < FELT_SHARE:
        return None
    return float(peak)


def _find_card_backs(res: LayoutResult, image: np.ndarray, boxes: List[TextBox]) -> None:
    """Opponents with face-down cards in front of them are still in the hand."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    felt = _felt_hue(hsv)
    H, W = image.shape[:2]
    hue = hsv[..., 0].astype(np.int16)
    colourful = (hsv[..., 1] > 70) & (hsv[..., 2] > 50)
    if felt is not None:  # (on a grey felt anything coloured stands out)
        # Leave out the felt itself: the big areas of its colour. Card backs of a similar
        # colour are separate small patches (a white border, or off the felt), so they stay.
        diff = np.minimum(np.abs(hue - felt), 180 - np.abs(hue - felt))
        near = (colourful & (diff <= 18)).astype(np.uint8)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(near, connectivity=8)
        big = [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= 0.01 * H * W]
        if big:
            colourful &= ~np.isin(labels, big)
    text_h = float(np.median([b.h for b in boxes])) if boxes else 12.0
    # Split by hue so card backs are not merged with an action badge or chips of
    # another colour that overlap them.
    masks = []
    for centre in range(0, 180, 15):
        d = np.minimum(np.abs(hue - centre), 180 - np.abs(hue - centre))
        m = colourful & (d <= 10)
        if not m.any():
            continue
        # the table's rim and other long shapes: a name or stack written across them
        # would cut them into card-sized pieces
        n, labels, stats, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
        long_parts = [i for i in range(1, n) if max(stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]) > 12 * text_h]
        if long_parts:
            m &= ~np.isin(labels, long_parts)
        for b in boxes:  # text badges ("Bet 60") often overlap the cards; ignore their area
            m[max(0, b.y - 3): b.bottom + 3, max(0, b.x - 3): b.right + 3] = False
        if m.any():
            masks.append(cv2.morphologyEx(m.astype(np.uint8) * 255, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)))
    found_any = False
    for s in res.seats:
        if s.is_hero:
            continue
        x, y, w, h = s.box
        nh = max(h, 10)
        rx0, rx1 = int(max(0, x - 0.6 * w)), int(min(W, x + 1.6 * w))
        ry0, ry1 = int(max(0, y - 3.2 * nh)), int(min(H, y + 1.2 * nh))
        pic = _seat_picture(res, s, text_h) if res.pictures else None
        if pic is not None:
            # the backs lie beside the picture, on either side. On a crowded table (eight
            # players) they reach past the name's width, and cut off they were no card
            px, py, pr = pic
            rx0, rx1 = min(rx0, int(max(0, px - 3.2 * pr))), max(rx1, int(min(W, px + 3.2 * pr)))
            ry0, ry1 = min(ry0, int(max(0, py - 1.6 * pr))), max(ry1, int(min(H, py + 1.6 * pr)))
        contours = []
        for m in masks:
            roi = m[ry0:ry1, rx0:rx1]
            if roi.size and roi.any():
                contours.extend(cv2.findContours(roi, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0])
        best = 0.0
        for c in contours:
            cx, cy, cw, ch = cv2.boundingRect(c)
            if ch < 0.3 * nh or ch > 4 * nh or cw < 0.4 * ch:
                continue
            aspect = cw / float(ch)
            if not 0.45 <= aspect <= 2.6:  # nameplates often cover the lower half
                continue
            fill = cv2.contourArea(cv2.convexHull(c)) / float(cw * ch)
            if fill < 0.75:
                continue
            # card backs are rectangles (turned a little, perhaps): hair or shoulders in a
            # player's picture are not
            rw, rh = cv2.minAreaRect(c)[1]
            if cv2.contourArea(c) < 0.8 * rw * rh:
                continue
            ax0, ay0 = rx0 + cx, ry0 + cy
            if any(math.hypot(ax0 + cw / 2 - px, ay0 + ch / 2 - py) < pr for px, py, pr in res.pictures):
                continue  # part of a player's picture
            if any(ax0 - 2 <= b.x and b.right <= ax0 + cw + 2 and ay0 - 2 <= b.y and b.bottom <= ay0 + ch + 2
                   for b in boxes):
                continue  # a coloured badge with a number in it (a level), not cards
            if any(t is not None and abs(ay0 + ch / 2 - t.cy) <= 0.5 * t.h and ch <= 1.3 * t.h
                   for t in (s.label, s.stack_box)):
                continue  # as tall as the text, on the name's or the stack's line: a badge
            # chips are round; card backs are rectangles
            circ = 4 * math.pi * cv2.contourArea(c) / (cv2.arcLength(c, True) ** 2 + 1e-6)
            if circ > 0.84 and 0.8 < aspect < 1.25:
                continue
            best = max(best, 0.8)
        if best:
            s.has_cards, s.cards_conf = True, best
            found_any = True
    # at showdown the players still in turn their cards face up. A player's two cards go to one
    # seat together: one by one, the card further out can be nearer the next seat's name
    for hand in _hands_shown(res.other_cards):
        rx = sum(r.center[0] for r in hand) / len(hand)
        ry = sum(r.center[1] for r in hand) / len(hand)
        ch = max(r.box[3] for r in hand)
        near = [s for s in res.seats if not s.is_hero and math.hypot(s.center[0] - rx, s.center[1] - ry) < 3 * ch]
        if near:
            s = min(near, key=lambda s: math.hypot(s.center[0] - rx, s.center[1] - ry))
            s.has_cards, s.cards_conf = True, 0.85
            found_any = True
    if not found_any:
        found_any = _plain_backs(res, image, boxes)
    if found_any:
        # this client shows card backs, so a seat without them has folded
        for s in res.seats:
            if not s.is_hero and s.has_cards is None:
                s.has_cards, s.cards_conf = False, 0.75


def _board_middle(board: List[CardReading]) -> Tuple[float, float]:
    """The middle of the table: the middle of the board's five places. The flop and the turn fill
    the places from the left, so the cards dealt so far sit left of the middle; taken for it, a
    bet on a crowded table (eight players) went to the seat beside its own."""
    cards = sorted(board, key=lambda r: r.center[0])
    xs = [r.center[0] for r in cards]
    cy = float(np.mean([r.center[1] for r in cards]))
    if 3 <= len(cards) < 5:
        step = float(np.median(np.diff(xs)))
        w = float(np.median([r.box[2] for r in cards]))
        if 0.9 * w <= step <= 2.0 * w:  # side by side in their places
            return xs[0] + 2 * step, cy
    return float(np.mean(xs)), cy


def _hands_shown(cards: List[CardReading]) -> List[List[CardReading]]:
    """Face-up cards in twos: cards of one size on one line, touching or nearly, belong to one
    player."""
    hands: List[List[CardReading]] = []
    for r in sorted(cards, key=lambda r: r.box[0]):
        x, y, w, h = r.box
        for hand in hands:
            lx, ly, lw, lh = hand[0].box
            if (len(hand) == 1 and abs((y + h / 2) - (ly + lh / 2)) < 0.3 * h and 0.8 <= h / lh <= 1.25
                    and x - (lx + lw) < 0.35 * w):
                hand.append(r)
                break
        else:
            hands.append([r])
    return hands


def _plain_backs(res: LayoutResult, image: np.ndarray, boxes: List[TextBox]) -> bool:
    """Card backs without colour (dark grey, white) beside round player pictures: a solid
    patch, card-sized for the picture, that differs from what surrounds the seat. Used only
    when no coloured backs were found anywhere on the table."""
    if not res.pictures or not boxes:
        return False
    H, W = image.shape[:2]
    text_h = float(np.median([b.h for b in boxes]))
    img = image.astype(np.int16)
    cards = [r.box for r in res.hero_cards + res.board]
    found_any = False
    for s in res.seats:
        if s.is_hero or s.has_cards is not None:
            continue
        pic = _seat_picture(res, s, text_h)
        if pic is None:
            continue
        px, py, pr = pic
        x0, x1 = int(max(0, px - 3.2 * pr)), int(min(W, px + 3.2 * pr))
        y0, y1 = int(max(0, py - 1.6 * pr)), int(min(H, py + 1.6 * pr))
        roi = img[y0:y1, x0:x1]
        if roi.shape[0] < 8 or roi.shape[1] < 8:
            continue
        border = np.concatenate([roi[0], roi[-1], roi[:, 0], roi[:, -1]])
        diff = np.abs(roi - np.median(border, axis=0)).sum(axis=-1) > 45
        yy, xx = np.mgrid[y0:y1, x0:x1]
        for x, y, r in res.pictures:  # the pictures themselves, and their rims
            diff &= np.hypot(xx - x, yy - y) > r + 3
        for bx, by, bw, bh in [(b.x, b.y, b.w, b.h) for b in boxes] + cards:
            diff[max(0, by - y0 - 3): max(0, by + bh - y0 + 3), max(0, bx - x0 - 3): max(0, bx + bw - x0 + 3)] = False
        k = max(3, int(0.2 * pr)) | 1  # open: drops thin things (a timer ring) touching the backs
        diff = cv2.morphologyEx(diff.astype(np.uint8), cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
        n, labels, stats, _ = cv2.connectedComponentsWithStats(diff, connectivity=8)
        rh, rw = diff.shape
        for i in range(1, n):
            cx, cy, cw, ch, area = (int(v) for v in stats[i])
            if cx == 0 or cy == 0 or cx + cw >= rw or cy + ch >= rh:
                continue  # runs out of the area: the felt, its rim
            if not (0.5 * pr <= ch <= 1.8 * pr and 0.35 * pr <= cw <= 2.6 * pr and 0.45 <= cw / ch <= 2.6):
                continue
            if area < 0.75 * cw * ch:
                continue  # card backs are solid
            c = cv2.findContours((labels[cy:cy + ch, cx:cx + cw] == i).astype(np.uint8), cv2.RETR_EXTERNAL,
                                 cv2.CHAIN_APPROX_SIMPLE)[0][0]
            circ = 4 * math.pi * cv2.contourArea(c) / (cv2.arcLength(c, True) ** 2 + 1e-6)
            if 0.8 < cw / ch < 1.25 and (circ > 0.84 or area < 0.85 * cw * ch):
                continue  # round (a disc fills 0.79 of its box): the dealer button or chips
            s.has_cards, s.cards_conf = True, 0.75
            found_any = True
            break
        if s.has_cards is None and _outlined_back(res, image, boxes, cards, pic, text_h):
            s.has_cards, s.cards_conf = True, 0.75
            found_any = True
    return found_any


def _outlined_back(res: LayoutResult, image: np.ndarray, boxes: List[TextBox], cards, pic, text_h: float) -> bool:
    """A card-shaped outline beside the picture: the edge of a card back that lies where the
    felt changes colour, so it doesn't stand out from one surrounding colour."""
    H, W = image.shape[:2]
    px, py, pr = pic
    x0, x1 = int(max(0, px - 3.2 * pr)), int(min(W, px + 3.2 * pr))
    y0, y1 = int(max(0, py - 1.6 * pr)), int(min(H, py + 1.6 * pr))
    edges = cv2.Canny(cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY), 25, 70)
    for c in cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[0]:
        bx, by, bw, bh = cv2.boundingRect(c)
        if not (1.15 * text_h <= bh <= 5 * text_h and (0.5 <= bw / bh <= 0.9 or 1.2 <= bw / bh <= 1.9)):
            continue  # one card, or two side by side
        if cv2.contourArea(c) < 0.6 * bw * bh:
            continue
        if len(cv2.approxPolyDP(c, 0.04 * cv2.arcLength(c, True), True)) != 4:
            continue
        gx, gy = x0 + bx, y0 + by
        if any(math.hypot(gx + bw / 2 - x, gy + bh / 2 - y) < r + 0.3 * text_h for x, y, r in res.pictures):
            continue
        rects = [(t.x, t.y, t.w, t.h) for t in boxes] + list(cards)
        if any(rx < gx + bw and gx < rx + rw and ry < gy + bh and gy < ry + rh for rx, ry, rw, rh in rects):
            continue
        return True
    return _white_edged_back(res, image, boxes, cards, pic)


def _white_edged_back(res: LayoutResult, image: np.ndarray, boxes: List[TextBox], cards, pic) -> bool:
    """A dark card inside a thin white edge, beside the picture: the inside of the edge is a
    card-shaped hole in the white. 8-player phone table: the backs lay across the table's
    black rim, so they neither stood out from one colour nor had an outline of their own."""
    H, W = image.shape[:2]
    px, py, pr = pic
    x0, x1 = int(max(0, px - 3.2 * pr)), int(min(W, px + 3.2 * pr))
    y0, y1 = int(max(0, py - 1.6 * pr)), int(min(H, py + 1.6 * pr))
    white = (cv2.cvtColor(image[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY) >= 200).astype(np.uint8)
    contours, hierarchy = cv2.findContours(white, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hierarchy is None:
        return False
    rects = [(t.x, t.y, t.w, t.h) for t in boxes] + list(cards)
    for c, (_, _, _, parent) in zip(contours, hierarchy[0]):
        if parent < 0:
            continue  # an outer edge; the holes inside the white have a parent
        bx, by, bw, bh = cv2.boundingRect(c)
        if not (0.5 * pr <= bh <= 1.8 * pr and 0.45 <= bw / bh <= 0.95):
            continue  # one card standing up (the hole in a letter or in the button is far smaller)
        if cv2.contourArea(c) < 0.75 * bw * bh:
            continue
        gx, gy = x0 + bx, y0 + by
        if any(math.hypot(gx + bw / 2 - x, gy + bh / 2 - y) < r + 0.2 * pr for x, y, r in res.pictures):
            continue  # a picture inside its white rim
        if any(rx < gx + bw and gx < rx + rw and ry < gy + bh and gy < ry + rh for rx, ry, rw, rh in rects):
            continue
        return True
    return False


# ------------------------------------------------------------- player pictures
PICTURE_SUPPORT = 0.9  # share of a circle's outline that must be an edge in the picture
_ANGLES = np.linspace(0.0, 2.0 * np.pi, 72, endpoint=False)


def _circle_support(edges: np.ndarray, x: float, y: float, r: float) -> float:
    """The share of the circle's outline lying on an edge (within 2 pixels)."""
    H, W = edges.shape
    hit = np.zeros(len(_ANGLES), bool)
    cos, sin = np.cos(_ANGLES), np.sin(_ANGLES)
    for dr in (-2, -1, 0, 1, 2):
        px = np.round(x + (r + dr) * cos).astype(int)
        py = np.round(y + (r + dr) * sin).astype(int)
        ok = (px >= 0) & (px < W) & (py >= 0) & (py < H)
        hit[ok] |= edges[py[ok], px[ok]] > 0
    return float(hit.mean())


def _on_picture(b: TextBox, pictures, text_h: float) -> bool:
    """The text's middle, or at least half of it, lies on a round picture (a level badge on
    its edge counts; a name just above or below it does not)."""
    for x, y, r in pictures:
        reach = r + 0.25 * text_h
        if math.hypot(b.cx - x, b.cy - y) < r:
            return True  # its middle is on the picture
        if math.hypot(b.cx - x, b.cy - y) > reach + 0.5 * math.hypot(b.w, b.h):
            continue
        xs = b.x + (np.arange(5) + 0.5) / 5.0 * b.w
        ys = b.y + (np.arange(5) + 0.5) / 5.0 * b.h
        inside = np.hypot(xs[None, :] - x, ys[:, None] - y) <= reach
        if inside.mean() >= 0.5:
            return True
    return False


def _find_pictures(image: np.ndarray, text_h: float) -> List[Tuple[float, float, float]]:
    """Round player pictures (avatars), as (x, y, radius): circles a few text heights across
    whose whole outline is an edge. Folded players' greyed pictures count too. The round
    ends of buttons and the corners of plates are only partly circles, so they don't."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.medianBlur(gray, 3)
    lo, hi = int(max(8, 1.1 * text_h)), int(max(16, 4.5 * text_h))
    candidates = []
    found = cv2.HoughCircles(blurred, cv2.HOUGH_GRADIENT, dp=1, minDist=2 * lo, param1=100, param2=24,
                             minRadius=lo, maxRadius=hi)
    if found is not None:
        candidates.extend(found[0][:40])
    # The classic finder can settle on a wrong, larger circle round a dim (folded) picture, too
    # far off for the small adjustment below to fix; the newer one is steadier there. Both
    # only propose: the outline check below decides.
    found = cv2.HoughCircles(blurred, cv2.HOUGH_GRADIENT_ALT, dp=1.5, minDist=lo, param1=100, param2=0.6,
                             minRadius=lo, maxRadius=hi)
    if found is not None:
        candidates.extend(found[0][:40])
    if not candidates:
        return []
    edges = cv2.Canny(gray, 25, 70)
    out: List[Tuple[float, float, float, float]] = []
    for x, y, r in candidates:
        best = (_circle_support(edges, x, y, r), float(x), float(y), float(r))
        for step in (2.0, 1.0):  # Hough's circle is a pixel or two off: settle it on the outline
            s0, x0, y0, r0 = best
            for dx in (-step, 0.0, step):
                for dy in (-step, 0.0, step):
                    for dr in (-step, 0.0, step):
                        s = _circle_support(edges, x0 + dx, y0 + dy, r0 + dr)
                        if s > best[0]:
                            best = (s, x0 + dx, y0 + dy, r0 + dr)
        if best[0] >= PICTURE_SUPPORT:
            out.append(best)
    keep: List[Tuple[float, float, float]] = []
    for s, x, y, r in sorted(out, reverse=True):
        if all(math.hypot(x - kx, y - ky) > 0.8 * max(r, kr) for kx, ky, kr in keep):
            keep.append((x, y, r))
    return keep


# ------------------------------------------------------------- whose turn
def _plate(image: np.ndarray, box: Tuple[int, int, int, int], text_h: float) -> Tuple[int, int, int, int]:
    """The nameplate around a seat's name and stack: from the text outwards until the
    plate's colour ends. Without a plate (text straight on the felt) it is the text."""
    H, W = image.shape[:2]
    x, y, w, h = box
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return x, y, w, h
    fill = np.median(image[y0:y1, x0:x1].reshape(-1, 3), axis=0).astype(np.int16)

    def same(px) -> float:
        return float((np.abs(px.astype(np.int16) - fill).sum(axis=-1) < 45).mean())

    reach = int(max(2 * text_h, 1.5 * w))
    left = x0
    while left > max(0, x0 - reach) and same(image[y0:y1, left - 1]) > 0.6:
        left -= 1
    right = x1
    while right < min(W, x1 + reach) and same(image[y0:y1, right]) > 0.6:
        right += 1
    bottom = y1
    while bottom < min(H, y1 + int(2 * text_h)) and same(image[bottom, left:right]) > 0.6:
        bottom += 1
    top = y0
    while top > max(0, y0 - int(2 * text_h)) and same(image[top - 1, left:right]) > 0.6:
        top -= 1
    return left, top, right - left, bottom - top


def _seat_picture(res: LayoutResult, seat: Seat, text_h: float) -> Optional[Tuple[float, float, float]]:
    """The round picture by a seat's name and stack (above, between or beside them)."""
    x, y, w, h = seat.box
    best, best_d = None, None
    for px, py, pr in res.pictures:
        dx = max(x - px, 0.0, px - (x + w))
        dy = max(y - py, 0.0, py - (y + h))
        d = math.hypot(dx, dy)
        if d <= pr + 1.5 * text_h and (best is None or d < best_d):
            best, best_d = (px, py, pr), d
    return best


def _thin_parts(vivid: np.ndarray) -> np.ndarray:
    """The coloured lines and curves of a mask, without its solid shapes (card backs, chips,
    badges fill most of their box; a ring around a picture fills little of its box)."""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(vivid.astype(np.uint8), connectivity=8)
    solid = [i for i in range(1, n)
             if stats[i, cv2.CC_STAT_AREA] > 0.45 * stats[i, cv2.CC_STAT_WIDTH] * stats[i, cv2.CC_STAT_HEIGHT]]
    return vivid & ~np.isin(labels, solid) if solid else vivid


def _ring_cover(vivid: np.ndarray, pic: Tuple[float, float, float], text_h: float,
                full: Optional[np.ndarray] = None) -> float:
    """The share of the way round a picture that a thin coloured ring covers. Card backs or
    chips beside the picture are not thin: they still show further out (in `full`, the mask
    before its solid shapes were taken out; striped backs leave thin stripes behind)."""
    H, W = vivid.shape
    x, y, r = pic
    cos, sin = np.cos(_ANGLES), np.sin(_ANGLES)

    def hits(mask, radii):
        out = np.zeros(len(_ANGLES), bool)
        for dr in radii:
            px = np.round(x + (r + dr) * cos).astype(int)
            py = np.round(y + (r + dr) * sin).astype(int)
            ok = (px >= 0) & (px < W) & (py >= 0) & (py < H)
            out[ok] |= mask[py[ok], px[ok]]
        return out

    near = hits(vivid, np.arange(1.0, max(2.0, 0.6 * text_h), 1.0))
    far = hits(vivid if full is None else full, np.linspace(1.0, 1.6, 4) * text_h)
    return float((near & ~far).mean())


def _find_acting(res: LayoutResult, image: np.ndarray, boxes: List[TextBox], text_h: float) -> None:
    """The seat whose turn it is: a coloured timer bar under its plate, or a glow ring
    around it. Only a seat that clearly stands out from every other counts: at most one
    seat is ever highlighted."""
    if len(res.seats) < 2:
        return
    H, W = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    # bright, strongly coloured pixels: timer bars and glow rings, never felt, plates or text
    vivid = (hsv[..., 1] > 100) & (hsv[..., 2] > 150)
    felt = _felt_hue(hsv)
    if felt is not None:
        hue = hsv[..., 0].astype(np.int16)
        on_felt = np.minimum(np.abs(hue - felt), 180 - np.abs(hue - felt)) <= 10
        felt_v = float(np.median(hsv[..., 2][on_felt & (hsv[..., 1] > 60)])) if on_felt.any() else 0.0
        vivid &= ~(on_felt & (np.abs(hsv[..., 2].astype(np.int16) - felt_v) < 40))
    for b in boxes:  # coloured text (stacks drawn in yellow, say) is not a highlight
        vivid[max(0, b.y - 2): b.bottom + 2, max(0, b.x - 2): b.right + 2] = False
    # rings round pictures are measured on the whole pictures: one cut out would leave a thin
    # sliver of its edge behind, like a ring
    thin = _thin_parts(vivid) if res.pictures else None
    for x, y, r in res.pictures:  # a player's picture is no highlight, whatever its colours
        x0, y0 = max(0, int(x - r - 1)), max(0, int(y - r - 1))
        yy, xx = np.mgrid[y0:min(H, int(y + r + 2)), x0:min(W, int(x + r + 2))]
        vivid[yy, xx] &= np.hypot(xx - x, yy - y) > r + 0.5
    around = vivid.copy()  # for the glow and bar beside plates
    for r in res.hero_cards + res.board + res.other_cards:  # red suits on a card
        x, y, w, h = r.box
        around[max(0, y): y + h, max(0, x): x + w] = False
    n, labels, stats, _ = cv2.connectedComponentsWithStats(around.astype(np.uint8), connectivity=8)
    span = np.maximum(stats[:, cv2.CC_STAT_WIDTH], stats[:, cv2.CC_STAT_HEIGHT])
    solid = stats[:, cv2.CC_STAT_AREA] > 0.45 * stats[:, cv2.CC_STAT_WIDTH] * stats[:, cv2.CC_STAT_HEIGHT]
    long_parts = [i for i in range(1, n) if span[i] > 12 * text_h]  # the table's rim
    blobs = [i for i in range(1, n) if solid[i] and span[i] <= 2 * text_h]  # a coin, a chip, a badge
    if long_parts:
        around &= ~np.isin(labels, long_parts)
    glow = around & ~np.isin(labels, blobs) if blobs else around
    pad = max(3, int(round(0.3 * text_h)))
    below = int(round(1.4 * text_h))
    scores = []
    for s in res.seats:
        px, py, pw, ph = _plate(image, s.box, text_h)
        x0, y0, x1, y1 = px, py, px + pw, py + ph
        # a glow ring: both sides of the plate light up
        lft = glow[y0:y1, max(0, x0 - pad): x0]
        rgt = glow[y0:y1, x1: min(W, x1 + pad)]
        ring = min(float(lft.mean()) if lft.size else 0.0, float(rgt.mean()) if rgt.size else 0.0)
        # a timer bar: a thin coloured line under the plate (its length is the time left)
        strip = around[y1: min(H, y1 + below), x0:x1]
        bar = 0.0
        if strip.size:
            rows = strip.sum(axis=1)
            lit = rows >= max(3, 0.04 * pw)
            if lit.any() and lit.sum() <= 0.8 * text_h:
                bar = float(rows.max()) / max(1, pw)
        scores.append(max(min(1.0, 2.0 * ring), min(1.0, 4.0 * bar)))
    # round pictures: a thin coloured ring around the acting player's picture (its length is
    # the time left)
    if res.pictures:
        for k, s in enumerate(res.seats):
            pic = _seat_picture(res, s, text_h)
            if pic is not None:
                # with little time left the ring is a short arc, partly under the name
                scores[k] = max(scores[k], min(1.0, 4.0 * _ring_cover(thin, pic, text_h, vivid)))
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    best, second = scores[order[0]], scores[order[1]]
    if best >= 0.25 and second <= 0.35 * best:
        res.acting_seat = order[0]
        res.acting_conf = round(min(0.92, 0.6 + 0.35 * best) * (1.0 - second / max(best, 1e-6) * 0.5), 3)
    elif best >= 0.25:
        res.warnings.append("More than one seat looks highlighted: whose turn it is was not read.")
