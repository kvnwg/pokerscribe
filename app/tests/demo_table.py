"""A bare-bones poker table of our own, drawn from a known game state.

Used by tools/selftest.py (PokerScribe plays hands on it and its reads are checked
against the truth) and by regression tests. Nothing here talks to a real poker site.

Each Layout changes how the table looks, within what real clients do: where the seats
sit, colours, fonts, the deck, whether bets are printed, what the pot label means
(Total pot with the bets in it, or Pot from earlier rounds only), timer bars, glow
rings, the dealer button, empty seats, a hand number, and the action buttons.

The elements follow the usual client layout (see docs/research/SCREEN_READING.md):

  header (table, game, stakes) . seat plate (name, stack) . card backs . dimmed plate
  when folded . glow ring and timer bar on the seat acting . status plate (All in) .
  dealer button . bet in front (this round) . total pot and collected pot . board with
  empty slots . hero cards face up at the bottom . action buttons only on your turn .
  hand number.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .synthetic import (TEXT_BOLD_FONTS, TEXT_FONTS, Theme, _font, draw_card, draw_card_back, find_font,
                        held_out_rank_fonts)

# Six seats, hero at the bottom, then clockwise on screen (lower left, upper left, top,
# upper right, lower right), as fractions of the table picture.
SIX_MAX = [(0.50, 0.84), (0.13, 0.64), (0.13, 0.30), (0.50, 0.17), (0.87, 0.30), (0.87, 0.64)]
# Nine slots, hero at the bottom; six players sit in some of them.
NINE_MAX = [(0.50, 0.85), (0.22, 0.80), (0.09, 0.56), (0.15, 0.30), (0.36, 0.17), (0.64, 0.17),
            (0.85, 0.30), (0.91, 0.56), (0.78, 0.80)]


@dataclass
class Layout:
    name: str
    width: int = 1280
    height: int = 900
    background: Tuple[int, int, int] = (26, 26, 26)
    felt: Tuple[int, int, int] = (72, 72, 66)
    felt_edge: Tuple[int, int, int] = (110, 110, 100)
    felt_box: Tuple[float, float, float, float] = (0.17, 0.20, 0.83, 0.74)
    slots: List[Tuple[float, float]] = field(default_factory=lambda: list(SIX_MAX))
    used_slots: Optional[List[int]] = None  # slots the six players sit in (others: empty seats)
    empty_seat_text: str = "Empty seat"
    text_font: Optional[str] = None
    text_size: int = 22
    plate: Tuple[int, int, int] = (72, 72, 70)
    plate_edge: Tuple[int, int, int] = (125, 125, 120)
    name_color: Tuple[int, int, int] = (235, 235, 230)
    stack_color: Tuple[int, int, int] = (205, 205, 200)
    hero_plate: Tuple[int, int, int] = (14, 84, 66)
    currency: str = "$"
    # what the middle shows: "total" = "Total pot: X" (middle + bets) and the collected
    # pile by itself; "pot" = "Pot: X" (earlier rounds only); "all" = "Pot: X" with the
    # bets already in it (bets go straight to the pot: none printed in front)
    pot_mode: str = "total"
    show_bets: bool = True
    header: str = "Aurora · NL Hold'em · {cur}1/{cur}2"
    timer_bar: bool = True
    timer_color: Tuple[int, int, int] = (60, 200, 150)
    outline_bars: bool = False  # an empty outline bar under every other seat
    glow: bool = True
    hand_id: bool = True
    empty_board_slots: bool = True
    deck: Theme = field(default_factory=lambda: Theme(card_w=58, card_h=80))
    hero_card_scale: float = 1.0
    back: Tuple[int, int, int] = (16, 92, 76)
    button_labels: str = "short"  # "short": Fold / Call $92 / Raise ; "long": Fold / Call 92 / Raise to 240
    sizing_buttons: bool = False  # Min, 1/2 Pot, Pot, Max and an amount box above the buttons
    pre_actions: bool = False  # Check/Fold and Call any boxes while it isn't your turn
    action_tags: bool = False  # the last action replaces the name on the plate ("Call", "Raise")
    jpeg_quality: Optional[int] = None
    scale: float = 1.0  # the window drawn smaller or bigger than the client's own size


@dataclass
class SeatView:
    name: str
    stack: float
    bet: float = 0.0
    has_cards: bool = True  # card backs (or face-up cards for the hero)
    all_in: bool = False
    shown: Optional[Tuple[str, str]] = None  # cards turned face up at showdown
    tag: Optional[str] = None  # last action tag, when the layout shows them


@dataclass
class TableView:
    """What is on screen at one moment. Seats in screen order: hero first, then clockwise."""
    seats: List[SeatView]
    hero_cards: List[str]
    board: List[str]
    collected: float  # chips in the middle from earlier rounds
    button: int  # screen index of the dealer button
    acting: Optional[int]  # screen index of the seat whose turn it is
    buttons: List[str] = field(default_factory=list)  # action buttons (hero's turn only)
    hand_no: int = 0
    timer_left: float = 0.7


def money(x: float, cur: str) -> str:
    if abs(x - round(x)) < 1e-9:
        return f"{cur}{int(round(x)):,}"
    return f"{cur}{x:,.2f}"


def _rank_font(i: int) -> Optional[str]:
    fonts = held_out_rank_fonts()
    return fonts[i % len(fonts)] if fonts else None


def layouts() -> Dict[str, Layout]:
    """The layouts the self-test cycles through."""
    dejavu = find_font("DejaVuSans.ttf")
    liberation = find_font("LiberationSans-Regular.ttf")
    out = [
        # like the annotated wireframe: grey felt, Total pot with the bets, timer bars
        Layout("wireframe", deck=Theme(card_w=58, card_h=80, rank_font=_rank_font(0))),
        # green felt, Pot means earlier rounds only, bets printed, no timer (glow only)
        Layout("green", background=(18, 22, 30), felt=(30, 110, 64), felt_edge=(64, 44, 30), pot_mode="pot",
               timer_bar=False, plate=(36, 40, 46), plate_edge=(80, 84, 92), stack_color=(255, 214, 102),
               currency="", header="Table 12 - Blinds 1/2 - No Limit", back=(170, 32, 44),
               deck=Theme(card_w=62, card_h=86, rank_font=_rank_font(1), four_color=True),
               button_labels="long", text_font=liberation, hand_id=False, empty_board_slots=False),
        # bets go straight into the pot (no amounts in front), smaller window, blue felt
        Layout("compact", width=1024, height=720, felt=(24, 62, 120), felt_edge=(14, 36, 70),
               background=(12, 14, 20), pot_mode="all", show_bets=False, text_size=18,
               header="NLHE {cur}1/{cur}2", deck=Theme(card_w=46, card_h=64, rank_font=_rank_font(2)),
               back=(140, 30, 120), outline_bars=True, text_font=dejavu),
        # nine-seat table with three empty seats, sizing buttons, pre-action boxes
        Layout("ninemax", width=1360, height=920, slots=list(NINE_MAX), used_slots=[0, 1, 3, 4, 6, 7],
               felt=(40, 96, 60), felt_box=(0.14, 0.20, 0.86, 0.72), pot_mode="pot", sizing_buttons=True,
               pre_actions=True, deck=Theme(card_w=56, card_h=78, rank_font=_rank_font(3)),
               header="Blinds {cur}1/{cur}2 · Hold'em"),
        # last action shown on the plate, window scaled down and saved as JPEG
        Layout("tags", felt=(60, 40, 40), felt_edge=(90, 60, 40), action_tags=True, scale=0.8, jpeg_quality=85,
               deck=Theme(card_w=60, card_h=84, rank_font=_rank_font(4)), button_labels="long"),
        # held out: added after the fixes, to check they generalise. Big window, other seat
        # spots, an orange timer bar and no glow, bigger text, another card font
        Layout("wide", width=1600, height=1000, felt=(20, 96, 104), felt_edge=(12, 60, 66), background=(24, 22, 30),
               slots=[(0.50, 0.86), (0.16, 0.70), (0.10, 0.36), (0.42, 0.15), (0.84, 0.24), (0.90, 0.62)],
               felt_box=(0.15, 0.21, 0.85, 0.75), text_size=26, timer_color=(236, 142, 40), glow=False,
               deck=Theme(card_w=70, card_h=98, rank_font=find_font("DejaVuSans-Bold.ttf")),
               back=(40, 60, 170), button_labels="long", header="Holdout table · Blinds {cur}1/{cur}2"),
    ]
    return {lay.name: lay for lay in out}


# --------------------------------------------------------------------------- drawing
def _seat_points(lay: Layout) -> List[Tuple[float, float]]:
    slots = lay.slots if lay.used_slots is None else [lay.slots[i] for i in lay.used_slots]
    return [(fx * lay.width, fy * lay.height) for fx, fy in slots]


def _empty_points(lay: Layout) -> List[Tuple[float, float]]:
    if lay.used_slots is None:
        return []
    return [(fx * lay.width, fy * lay.height) for i, (fx, fy) in enumerate(lay.slots) if i not in lay.used_slots]


def _dashed_rect(d: ImageDraw.ImageDraw, box, color, dash: int = 7) -> None:
    x0, y0, x1, y1 = box
    for x in range(int(x0), int(x1), 2 * dash):
        d.line([(x, y0), (min(x + dash, x1), y0)], fill=color, width=2)
        d.line([(x, y1), (min(x + dash, x1), y1)], fill=color, width=2)
    for y in range(int(y0), int(y1), 2 * dash):
        d.line([(x0, y), (x0, min(y + dash, y1))], fill=color, width=2)
        d.line([(x1, y), (x1, min(y + dash, y1))], fill=color, width=2)


def render(view: TableView, lay: Layout) -> Tuple[np.ndarray, dict]:
    """The picture and where things were drawn (in the picture's own pixels)."""
    W, H = lay.width, lay.height
    img = Image.new("RGB", (W, H), lay.background)
    d = ImageDraw.Draw(img)
    font = _font(lay.text_font or find_font(*TEXT_FONTS), lay.text_size)
    bold = _font(find_font(*TEXT_BOLD_FONTS), lay.text_size)
    small = _font(lay.text_font or find_font(*TEXT_FONTS), int(lay.text_size * 0.85))
    cur = lay.currency
    fx0, fy0, fx1, fy1 = lay.felt_box
    d.ellipse([fx0 * W - 6, fy0 * H - 6, fx1 * W + 6, fy1 * H + 6], fill=lay.felt_edge)
    d.ellipse([fx0 * W, fy0 * H, fx1 * W, fy1 * H], fill=lay.felt)
    cx, cy = (fx0 + fx1) / 2 * W, (fy0 + fy1) / 2 * H
    meta: dict = {"plates": [], "board_boxes": [], "hero_boxes": []}

    # header
    if lay.header:
        d.rounded_rectangle([24, 14, W - 24, 14 + int(lay.text_size * 2.1)], radius=6, fill=(52, 52, 50),
                            outline=(90, 90, 88))
        d.text((44, 14 + lay.text_size * 1.05), lay.header.format(cur=cur), font=font, fill=(210, 210, 205),
               anchor="lm")

    # board: five slots, dealt cards face up
    th = lay.deck
    gap = int(th.card_w * 0.15)
    bx0 = int(cx - (5 * th.card_w + 4 * gap) / 2)
    by0 = int(cy - th.card_h / 2 - th.card_h * 0.05)
    for i in range(5):
        x = bx0 + i * (th.card_w + gap)
        if i < len(view.board):
            meta["board_boxes"].append(draw_card(img, view.board[i], x, by0, th))
        elif lay.empty_board_slots:
            _dashed_rect(d, (x, by0, x + th.card_w, by0 + th.card_h), tuple(min(255, c + 45) for c in lay.felt))

    # pot labels
    bets = sum(s.bet for s in view.seats)
    pot_y = by0 - lay.text_size * 1.6
    if lay.pot_mode == "total":
        if view.collected + bets > 0:
            d.text((cx + lay.text_size * 2, pot_y), f"Total pot: {money(view.collected + bets, cur)}", font=font,
                   fill=(225, 225, 220), anchor="lm")
        if view.collected > 0:
            px, py = cx - lay.text_size * 2.5, by0 + th.card_h + lay.text_size * 1.6
            r = lay.text_size * 0.55
            d.ellipse([px - 2 * r - 6, py - r, px - 6, py + r], outline=(220, 220, 215), width=2)
            d.text((px, py), money(view.collected, cur), font=font, fill=(225, 225, 220), anchor="lm")
    elif lay.pot_mode in ("pot", "all"):
        shown = view.collected + (bets if lay.pot_mode == "all" else 0.0)
        if shown > 0:
            d.text((cx, pot_y), f"Pot: {money(shown, cur)}", font=bold, fill=(240, 240, 235), anchor="mm")

    # empty seats
    pw, ph = int(lay.text_size * 7.6), int(lay.text_size * 2.9)
    for sx, sy in _empty_points(lay):
        _dashed_rect(d, (sx - pw / 2, sy - ph / 2, sx + pw / 2, sy + ph / 2), (110, 110, 105))
        d.text((sx, sy), lay.empty_seat_text, font=small, fill=(150, 150, 145), anchor="mm")

    pts = _seat_points(lay)
    for i, (s, (sx, sy)) in enumerate(zip(view.seats, pts)):
        hero = i == 0
        x0, y0 = int(sx - pw / 2), int(sy - ph / 2)
        # cards first so the plate overlaps them a little
        if hero and view.hero_cards:
            hw, hh = int(th.card_w * lay.hero_card_scale), int(th.card_h * lay.hero_card_scale)
            hth = replace(th, card_w=hw, card_h=hh)
            step = hw + 6
            hx = int(sx - (hw + step) / 2)
            hy = int(y0 - hh + 4)
            for k, c in enumerate(view.hero_cards):
                meta["hero_boxes"].append(draw_card(img, c, hx + k * step, hy, hth))
        elif s.shown and not hero:
            sw, sh = int(th.card_w * 0.8), int(th.card_h * 0.8)
            sth = replace(th, card_w=sw, card_h=sh)
            hx = int(sx - sw - 3)
            for k, c in enumerate(s.shown):
                draw_card(img, c, hx + k * (sw + 6), int(y0 - sh + 4), sth)
        elif s.has_cards and not hero:
            bw, bh = int(th.card_w * 0.42), int(th.card_h * 0.42)
            bx = int(sx + pw * 0.5 - 2 * bw - 4) if sy > cy else int(sx - bw - 2)
            by = int(y0 - bh - 6)
            for k in range(2):
                draw_card_back(img, bx + k * (bw + 4), by, bw, bh, replace(th, back=lay.back))
        acting = view.acting == i
        fill = lay.hero_plate if hero else lay.plate
        if not s.has_cards and not hero:
            fill = tuple(int(c * 0.55) for c in lay.plate)  # dimmed: folded
        if acting and lay.glow:
            d.rounded_rectangle([x0 - 4, y0 - 4, x0 + pw + 4, y0 + ph + 4], radius=10, fill=(90, 220, 170))
        d.rounded_rectangle([x0, y0, x0 + pw, y0 + ph], radius=7, fill=fill, outline=lay.plate_edge, width=2)
        dim = not s.has_cards and not hero
        name = s.tag if (lay.action_tags and s.tag) else s.name
        d.text((sx, y0 + ph * 0.30), name, font=bold, fill=(130, 130, 125) if dim else lay.name_color, anchor="mm")
        stack = "All in" if s.all_in and s.stack <= 0 else money(s.stack, cur)
        d.text((sx, y0 + ph * 0.72), stack, font=font, fill=(120, 120, 115) if dim else lay.stack_color,
               anchor="mm")
        # timer bar under the plate of the seat acting
        ty = y0 + ph + 7
        if acting and lay.timer_bar:
            d.rounded_rectangle([x0, ty, x0 + pw, ty + 7], radius=3, fill=(40, 40, 40), outline=(90, 90, 90))
            d.rounded_rectangle([x0, ty, x0 + int(pw * view.timer_left), ty + 7], radius=3, fill=lay.timer_color)
        elif lay.outline_bars:
            d.rounded_rectangle([x0, ty, x0 + pw, ty + 7], radius=3, outline=(90, 90, 90))
        # bet in front, a third of the way to the middle
        if s.bet > 0 and lay.show_bets:
            bx, by = sx + (cx - sx) * 0.42, sy + (cy - sy) * 0.42
            if i == 0:
                bx, by = sx + pw * 0.05, y0 - th.card_h * lay.hero_card_scale - lay.text_size * 1.2
            r = lay.text_size * 0.5
            d.ellipse([bx - 2 * r - 6, by - r, bx - 6, by + r], fill=(200, 60, 60), outline=(240, 240, 240))
            d.text((bx, by), money(s.bet, cur), font=font, fill=(240, 240, 235), anchor="lm")
        # dealer button beside the plate, on the side toward the middle
        if view.button == i:
            side = 1.0 if sx <= cx else -1.0
            dx = sx + side * (pw / 2 + lay.text_size * 1.1)
            dy = sy + (-ph * 0.4 if sy > cy else ph * 0.4)
            if i == 0:
                dx, dy = sx + pw / 2 + lay.text_size * 1.4, y0 - lay.text_size * 0.5
            r = lay.text_size * 0.72
            d.ellipse([dx - r, dy - r, dx + r, dy + r], fill=(242, 242, 238), outline=(120, 120, 115), width=2)
            d.text((dx, dy), "D", font=bold, fill=(30, 30, 30), anchor="mm")
        meta["plates"].append((sx, sy, pw, ph))

    # bottom: hand number, action buttons or pre-action boxes
    if lay.hand_id and view.hand_no:
        d.rounded_rectangle([24, H - 58, 24 + lay.text_size * 13, H - 18], radius=6, fill=(52, 52, 50),
                            outline=(90, 90, 88))
        d.text((40, H - 38), f"# {357_618_000 + view.hand_no:,} · log", font=font, fill=(200, 200, 195),
               anchor="lm")
    if view.buttons:
        bw = int(max(lay.text_size * 6.2, max(font.getlength(b) for b in view.buttons) + lay.text_size))
        bh = int(lay.text_size * 2.1)
        x = W - 24 - len(view.buttons) * (bw + 10)
        y = H - bh - 18
        for k, label in enumerate(view.buttons):
            bx = x + k * (bw + 10)
            d.rounded_rectangle([bx, y, bx + bw, y + bh], radius=6, fill=(60, 60, 58), outline=(140, 140, 135),
                                width=2)
            d.text((bx + bw / 2, y + bh / 2), label, font=font, fill=(235, 235, 230), anchor="mm")
        if lay.sizing_buttons:
            sw = int(lay.text_size * 3.6)
            sx0 = W - 24 - 4 * (sw + 8)
            for k, label in enumerate(["Min", "1/2 Pot", "Pot", "Max"]):
                bx = sx0 + k * (sw + 8)
                d.rounded_rectangle([bx, y - bh - 14, bx + sw, y - 14], radius=5, fill=(48, 48, 46))
                d.text((bx + sw / 2, y - bh / 2 - 14), label, font=small, fill=(220, 220, 215), anchor="mm")
            ax = sx0 - int(lay.text_size * 5.5)
            d.rounded_rectangle([ax, y - bh - 14, ax + int(lay.text_size * 4.8), y - 14], radius=5,
                                fill=(235, 235, 230))
            d.text((ax + 10, y - bh / 2 - 14), "6", font=font, fill=(20, 20, 20), anchor="lm")
    elif lay.pre_actions and view.hero_cards and view.acting not in (None, 0):
        x, y = W - 24 - int(lay.text_size * 16), H - 44
        for label in ("Check/Fold", "Call any"):
            d.rectangle([x, y, x + 16, y + 16], outline=(200, 200, 200), width=2)
            d.text((x + 24, y + 8), label, font=small, fill=(220, 220, 215), anchor="lm")
            x += int(lay.text_size * 7.5)

    arr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    if lay.scale != 1.0:
        arr = cv2.resize(arr, None, fx=lay.scale, fy=lay.scale, interpolation=cv2.INTER_AREA)
        k = lay.scale
        meta["plates"] = [(x * k, y * k, w * k, h * k) for x, y, w, h in meta["plates"]]
    if lay.jpeg_quality:
        ok, enc = cv2.imencode(".jpg", arr, [cv2.IMWRITE_JPEG_QUALITY, lay.jpeg_quality])
        arr = cv2.imdecode(enc, cv2.IMREAD_COLOR)
    return arr, meta


def plate_distance(anchor: Tuple[float, float], plate: Tuple[float, float, float, float]) -> float:
    return math.hypot(anchor[0] - plate[0], anchor[1] - plate[1])
