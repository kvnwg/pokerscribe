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

from .amounts import Amount, first_amount, has_blinds_label, parse_amount, parse_blinds

# OCR often drops the space in "Call 60", so a digit may follow the word directly
ACTION_RE = re.compile(r"^\s*(fold|folds|check|checks|call|calls|bet|bets|raise|raises|all[\s-]?in|allin)(?![a-z])", re.I)
PRE_ACTION_RE = re.compile(r"(check\s*/\s*fold|call\s*any|fold\s*to\s*any|check\s*/\s*call|fold\s*/\s*check|auto[\s-]?(check|fold|call))", re.I)
POT_RE = re.compile(r"\b(total\s+)?pot\b", re.I)
STATUS_RE = re.compile(r"(sitting\s*out|sit\s*out|empty\s*seat|open\s*seat|seat\s*open|disconnected|reserved|join)", re.I)
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
    warnings: List[str] = field(default_factory=list)


# ----------------------------------------------------------------- cards
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

    board: List[CardReading] = []
    candidates = [row for row in rows if 3 <= len(row) <= 5 and spread_ok(row)
                  and 0.18 * height <= np.mean([r.center[1] for r in row]) <= 0.75 * height]
    if candidates:
        board = min(candidates, key=lambda row: abs(np.mean([r.center[1] for r in row]) - 0.45 * height))
    rest = [r for r in readings if r not in board]

    hero: List[CardReading] = []
    if rest:
        bottom = sorted(rest, key=lambda r: -r.center[1])
        anchor = min(bottom[:4], key=lambda r: abs(r.center[0] - width / 2) + 0.5 * (height - r.center[1]))
        if anchor.center[1] > (np.mean([r.center[1] for r in board]) if board else 0.45 * height):
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
        res.center = (float(np.mean([r.center[0] for r in res.board])), float(np.mean([r.center[1] for r in res.board])))
    else:
        res.center = (W / 2.0, H * 0.45)
    med_text_h = float(np.median([b.h for b in boxes])) if boxes else 14.0
    used: set = set()

    _find_action_buttons(res, boxes, used, W, H, med_text_h)
    _find_pot(res, boxes, used, W, H)
    _find_blinds(res, boxes, used)
    _find_seats(res, boxes, used, med_text_h)
    _assign_hero_and_order(res, W, H)
    _assign_bets(res, boxes, used, W, H)
    _find_button(res, image, boxes, card_rects, med_text_h)
    _find_card_backs(res, image, boxes)
    return res


def _find_action_buttons(res: LayoutResult, boxes, used, W, H, text_h) -> None:
    pre = [b for b in boxes if PRE_ACTION_RE.search(b.text)]
    for b in pre:
        used.add(id(b))
    low = [b for b in boxes if id(b) not in used and b.cy > 0.62 * H and ACTION_RE.match(b.text)]
    row: List[TextBox] = []
    for b in low:
        mates = [o for o in low if abs(o.cy - b.cy) < 0.8 * max(b.h, o.h)]
        if len(mates) > len(row):
            row = mates
    if len(row) < 2:
        corner = [b for b in low if b.cx > 0.55 * W and b.cy > 0.8 * H]
        row = corner[:1] if len(corner) == 1 else row
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
                    used.add(id(b))
    elif pre:
        res.hero_to_act = False
        res.hero_to_act_conf = 0.85
    for b in boxes:
        if SIZING_RE.match(b.text) and b.cy > 0.7 * H:
            used.add(id(b))


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
    for lab in labels:
        for amt_box, amt in amounts + [(b, None) for b in all_in]:
            if amt_box is lab:
                continue
            for below in (True, False):
                gap = amt_box.y - lab.bottom if below else lab.y - amt_box.bottom
                lh = max(lab.h, amt_box.h)
                if -0.4 * lh <= gap <= 1.2 * lh and abs(amt_box.cx - lab.cx) < 0.6 * max(lab.w, amt_box.w, 2 * lh):
                    score = gap / lh + abs(amt_box.cx - lab.cx) / max(lab.w, 1) + (0 if below else 0.5)
                    pairs.append((score, lab, amt_box, amt))
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
    for s in res.seats:
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
    if hero is None:
        bottom = [s for s in res.seats if 0.3 * W <= s.center[0] <= 0.7 * W]
        if bottom:
            hero = max(bottom, key=lambda s: s.center[1])
            res.warnings.append("Hero seat guessed from layout (no hero cards near a nameplate).")
    if hero is None:
        res.warnings.append("Could not tell which seat is the hero.")
        res.seats.sort(key=lambda s: s.angle)
        return
    hero.is_hero = True
    ref = hero.angle
    res.seats.sort(key=lambda s: (s.angle - ref) % 360.0)


def _assign_bets(res: LayoutResult, boxes, used, W, H) -> None:
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
        if res.pot_box is not None and abs(b.cy - res.pot_box.cy) < 1.5 * b.h and abs(b.cx - res.pot_box.cx) < 3 * res.pot_box.w:
            continue
        best, best_d = None, None
        for s in res.seats:
            sx, sy = s.center
            vx, vy = cx - sx, cy - sy
            L2 = vx * vx + vy * vy
            if L2 <= 1:
                continue
            t = ((b.cx - sx) * vx + (b.cy - sy) * vy) / L2
            if not 0.05 <= t <= 0.9:
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


def _find_button(res: LayoutResult, image: np.ndarray, boxes, card_rects, text_h) -> None:
    if not res.seats:
        return
    candidates: List[Tuple[float, Tuple[int, int, int, int]]] = []
    for b in boxes:
        if b.text.strip() in ("D", "DEALER", "Dealer", "BTN") and b.w < 4 * b.h:
            pad = int(0.3 * b.h)
            candidates.append((0.9, (b.x - pad, b.y - pad, b.w + 2 * pad, b.h + 2 * pad)))
    candidates.extend(_button_discs(image, card_rects, text_h))
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


def _felt_hue(hsv: np.ndarray) -> Optional[float]:
    sat = (hsv[..., 1] > 60) & (hsv[..., 2] > 40)
    if sat.sum() < 100:
        return None
    hist = np.bincount(hsv[..., 0][sat].ravel(), minlength=180)
    return float(np.argmax(np.convolve(np.r_[hist[-5:], hist, hist[:5]], np.ones(5), "same")[5:-5]))


def _find_card_backs(res: LayoutResult, image: np.ndarray, boxes: List[TextBox]) -> None:
    """Opponents with face-down cards in front of them are still in the hand."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    felt = _felt_hue(hsv)
    H, W = image.shape[:2]
    if felt is None:
        return
    hue = hsv[..., 0].astype(np.int16)
    diff = np.minimum(np.abs(hue - felt), 180 - np.abs(hue - felt))
    colourful = (hsv[..., 1] > 70) & (hsv[..., 2] > 50) & (diff > 18)
    for b in boxes:  # text badges ("Bet 60") often overlap the cards; ignore their area
        colourful[max(0, b.y - 3): b.bottom + 3, max(0, b.x - 3): b.right + 3] = False
    # Split by hue so card backs are not merged with an action badge or chips of
    # another colour that overlap them.
    masks = []
    for centre in range(0, 180, 15):
        d = np.minimum(np.abs(hue - centre), 180 - np.abs(hue - centre))
        m = (colourful & (d <= 10)).astype(np.uint8) * 255
        if m.any():
            masks.append(cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)))
    found_any = False
    for s in res.seats:
        if s.is_hero:
            continue
        x, y, w, h = s.box
        nh = max(h, 10)
        rx0, rx1 = int(max(0, x - 0.6 * w)), int(min(W, x + 1.6 * w))
        ry0, ry1 = int(max(0, y - 3.2 * nh)), int(min(H, y + 1.2 * nh))
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
            # chips are round; card backs are rectangles
            circ = 4 * math.pi * cv2.contourArea(c) / (cv2.arcLength(c, True) ** 2 + 1e-6)
            if circ > 0.84 and 0.8 < aspect < 1.25:
                continue
            best = max(best, 0.8)
        if best:
            s.has_cards, s.cards_conf = True, best
            found_any = True
    if found_any:
        # this client shows card backs, so a seat without them has folded
        for s in res.seats:
            if not s.is_hero and s.has_cards is None:
                s.has_cards, s.cards_conf = False, 0.75
