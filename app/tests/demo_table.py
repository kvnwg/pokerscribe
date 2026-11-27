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
# Eight seats, hero at the bottom, then clockwise
EIGHT_MAX = [(0.50, 0.85), (0.20, 0.79), (0.08, 0.50), (0.20, 0.21), (0.50, 0.15), (0.80, 0.21),
             (0.92, 0.50), (0.80, 0.79)]


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
    # Clients drawn with round player pictures (added 26 Nov from Kevin's screenshots), and
    # numbers on screen that are neither stacks nor bets.
    seat_style: str = "plate"  # "plate", or "avatar": a round picture with the name and stack by it
    name_above: bool = False  # avatar: the name above the picture and the stack under it
    avatar_r: float = 1.7  # avatar radius, in text sizes
    amount_fmt: str = "prefix"  # "prefix" $1,234 | "suffix" 1,234$ | "spaced" $ 1,234 | "nocomma" $ 1234
    stack_box: str = "none"  # avatar: "pill" (dark), "outline" (outlined box) or "coin" (pill with a coin)
    bet_fmt: str = "chip"  # "chip": a chip and the amount | "bare": a chip stack and the number, no currency
    level: str = "none"  # player level: "badge" (disc on the picture), "corner" (box on the plate), "text"
    # (a bare number in gold right beside the name, outside the plate, toward the middle)
    countdown: bool = False  # seconds left, in big digits on the acting player's picture
    acting_ring: bool = False  # avatar: a coloured ring around the acting player's picture
    pot_style: str = "label"  # "label" ("Pot: $X"), "tight" ("Pot:X"), "stacked" ("Pot Amt." over the amount)
    question_slots: bool = False  # undealt board cards drawn as grey cards with "?"
    hand_strength: bool = False  # "High Card", "One Pair" beside your cards, your stack beside your picture
    top_bar: bool = False  # your level star and experience counter ("300512 / 512000")
    extras: bool = False  # "Bonus +100%" and a notification count
    buttons_style: str = "row"  # "row", "column" (stacked at the right edge), "bar" (full width at the bottom)
    upper_buttons: bool = False  # "FOLD", "CALL 20$"
    names: Optional[Dict[str, str]] = None  # names drawn in place of the self-test's (digits, cut short)
    hand_id_fmt: str = "# {n:,} · log"
    rim: int = 6  # width of the felt's edge
    hero_overlap: float = 0.0  # avatar: share of your cards' height drawn over your picture
    unit: float = 1.0  # every amount drawn times this (blinds 5/10 when 5)


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


def _num(v: float, commas: bool = True) -> str:
    v = round(v, 2)
    if abs(v - round(v)) < 1e-9:
        return f"{int(round(v)):,}" if commas else str(int(round(v)))
    return f"{v:,.2f}" if commas else f"{v:.2f}"


def amount_text(x: float, lay: "Layout", bare: bool = False) -> str:
    """An amount (in the self-test's chips) as this layout draws it."""
    v = x * lay.unit
    cur = "" if bare else lay.currency
    if lay.amount_fmt == "suffix":
        return f"{_num(v)}{cur}"
    if lay.amount_fmt == "spaced":
        return f"{cur} {_num(v)}".strip()
    if lay.amount_fmt == "nocomma":
        return f"{cur} {_num(v, False)}".strip()
    return f"{cur}{_num(v)}"


def level_of(name: str, lay: "Layout") -> int:
    """A player's level: fixed for a name on a layout, 1 to 40 (often the size of a bet)."""
    return sum(ord(c) * (k + 3) for k, c in enumerate(name + lay.name)) % 40 + 1


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
    return {lay.name: lay for lay in out + avatar_layouts()}


def avatar_layouts() -> List[Layout]:
    """Layouts with round player pictures and numbers that are neither stacks nor bets:
    levels on the pictures, a countdown, an experience counter, a bonus, notifications.
    Modelled on three screenshots Kevin sent (26 Nov): a free-play app, a stock table
    design and a phone table. Drawn from scratch, no logos or artwork of theirs."""
    inter = find_font("Inter-SemiBold.otf", "Inter-Medium.otf")
    free = find_font("FreeSansBold.ttf")
    return [
        # green app: pictures with a level disc, name and "12,400$" in a pill under them, red
        # backs, "?" for cards still to come, "High Card" by your cards, a level star and
        # experience counter at the top, blinds 5/10 and no stakes shown
        Layout("avatars", width=1280, height=960, background=(26, 70, 38), felt=(44, 124, 62),
               felt_edge=(118, 70, 34), rim=18, felt_box=(0.17, 0.19, 0.83, 0.70),
               slots=[(0.50, 0.80), (0.24, 0.76), (0.09, 0.45), (0.24, 0.13), (0.50, 0.10), (0.76, 0.13),
                      (0.91, 0.45), (0.76, 0.76)],
               used_slots=[0, 1, 2, 3, 4, 6], empty_seat_text="", seat_style="avatar", stack_box="pill",
               amount_fmt="suffix", level="badge", acting_ring=True, timer_bar=False, glow=False,
               timer_color=(120, 236, 120), pot_mode="pot", question_slots=True, empty_board_slots=False,
               hand_strength=True, top_bar=True, upper_buttons=True, pre_actions=True, header="", hand_id=False,
               unit=5, text_font=inter, text_size=20, back=(186, 38, 50),
               deck=Theme(card_w=64, card_h=90, rank_font=_rank_font(5))),
        # stock design: blue room, wooden rim, nine places with "Seat" on the free ones, stacks
        # "$ 2,000" in outlined boxes, bets as a chip stack and a bare number, "Pot:677",
        # buttons stacked at the right edge, "Bonus +100%" and a notification count
        Layout("stock", width=1440, height=860, background=(26, 38, 104), felt=(62, 150, 52),
               felt_edge=(128, 70, 30), rim=22, felt_box=(0.22, 0.20, 0.78, 0.76),
               slots=[(0.50, 0.73), (0.32, 0.76), (0.17, 0.62), (0.17, 0.28), (0.32, 0.12), (0.50, 0.12),
                      (0.68, 0.12), (0.83, 0.28), (0.83, 0.62), (0.68, 0.76)],
               used_slots=[0, 2, 3, 5, 7, 9], empty_seat_text="Seat", seat_style="avatar", stack_box="outline",
               amount_fmt="spaced", bet_fmt="bare", acting_ring=True, timer_bar=False, glow=False,
               timer_color=(250, 160, 40), pot_mode="pot", pot_style="tight", empty_board_slots=False,
               buttons_style="column", upper_buttons=True, extras=True, header="", hand_id=False, unit=10,
               hero_overlap=0.5,
               text_font=free, text_size=20, back=(40, 70, 190),
               deck=Theme(card_w=62, card_h=88, rank_font=_rank_font(6))),
        # phone, upright: ten places in two columns, names above the picture (some with digits,
        # some cut short), "$ 25658" with a coin under it, the seconds left in big digits on the
        # acting player's picture, "Pot Amt." over the pot, "Hand #...", buttons across the bottom
        Layout("portrait", width=720, height=1280, background=(66, 22, 20), felt=(38, 118, 50),
               felt_edge=(22, 22, 22), rim=14, felt_box=(0.16, 0.14, 0.84, 0.80),
               slots=[(0.44, 0.87), (0.11, 0.72), (0.11, 0.58), (0.11, 0.44), (0.11, 0.30), (0.50, 0.12),
                      (0.89, 0.30), (0.89, 0.44), (0.89, 0.58), (0.89, 0.72)],
               used_slots=[0, 1, 3, 5, 7, 9], empty_seat_text="", seat_style="avatar", name_above=True,
               stack_box="coin", amount_fmt="nocomma", countdown=True, acting_ring=True, timer_bar=False,
               glow=False, timer_color=(250, 150, 30), pot_mode="pot", pot_style="stacked",
               empty_board_slots=False, buttons_style="bar", upper_buttons=True, header="",
               hand_id_fmt="Hand #{n}", unit=100, text_font=inter, text_size=19, back=(34, 34, 40),
               names={"You": "YOU", "Marlow": "Panther2234", "Quinn": "Anthonystar..", "Jasper": "PeterPower",
                      "Rhea": "Anonymous23", "Toby": "Williamsonpo.."},
               deck=Theme(card_w=46, card_h=66, rank_font=_rank_font(7))),
        # plates like the wireframe, with each player's level in a small box on the plate's
        # corner, on the name's line
        Layout("levels", felt=(52, 78, 96), felt_edge=(30, 46, 60), background=(20, 24, 30), level="corner",
               pot_mode="pot", header="Blinds {sb}/{bb} · NL Hold'em", text_font=find_font("Carlito-Regular.ttf"),
               deck=Theme(card_w=58, card_h=82, rank_font=_rank_font(8)), back=(150, 90, 30)),
        # eight players round the table (Kevin, 26 Nov: "it also needs to be trained on an 8 people
        # table"): plates like the wireframe, Pot from earlier rounds, no stakes shown
        Layout("eight", width=1360, height=940, slots=list(EIGHT_MAX), felt=(34, 90, 70), felt_edge=(20, 56, 44),
               felt_box=(0.17, 0.25, 0.83, 0.72), pot_mode="pot", header="", text_size=20,
               deck=Theme(card_w=56, card_h=78, rank_font=_rank_font(10)), back=(160, 40, 40)),
        # held out (added after the fixes above, never tuned on): each player's level as a bare
        # gold number right beside the name, outside the plate toward the middle, where a bet
        # could be; no stakes shown
        Layout("lvtext", felt=(84, 44, 92), felt_edge=(50, 24, 56), background=(16, 14, 22), level="text",
               pot_mode="pot", header="", text_font=find_font("DejaVuSans.ttf"),
               deck=Theme(card_w=60, card_h=84, rank_font=_rank_font(9)), back=(30, 120, 160)),
    ]


# --------------------------------------------------------------------------- drawing
def for_players(lay: Layout, n: int) -> Optional[Layout]:
    """The layout with `n` players seated, spread over its seat spots (you at the bottom), or
    None when it has fewer spots than that."""
    used = lay.used_slots if lay.used_slots is not None else list(range(len(lay.slots)))
    if len(used) == n:
        return lay
    k = len(lay.slots)
    if k < n:
        return None
    spread = sorted({int(j * k / n + 0.5) % k for j in range(n)})
    return replace(lay, used_slots=spread) if len(spread) == n else None


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


def _shown_name(name: str, lay: Layout) -> str:
    return (lay.names or {}).get(name, name)


def _bet(d: ImageDraw.ImageDraw, lay: Layout, bx: float, by: float, bet: float, font) -> None:
    r = lay.text_size * 0.5
    if lay.bet_fmt == "bare":  # a little stack of chips and the number alone
        for k in range(3):
            yy = by + r * 0.5 - k * r * 0.45
            d.ellipse([bx - 2 * r - 8, yy - r * 0.55, bx - 8, yy + r * 0.55], fill=(30, 30, 30) if k % 2 else (235, 235, 235),
                      outline=(90, 90, 90))
        d.text((bx, by), amount_text(bet, lay, bare=True), font=font, fill=(245, 245, 240), anchor="lm")
        return
    d.ellipse([bx - 2 * r - 6, by - r, bx - 6, by + r], fill=(200, 60, 60), outline=(240, 240, 240))
    d.text((bx, by), amount_text(bet, lay), font=font, fill=(240, 240, 235), anchor="lm")


def _dealer(d: ImageDraw.ImageDraw, dx: float, dy: float, lay: Layout, bold) -> None:
    r = lay.text_size * 0.72
    d.ellipse([dx - r, dy - r, dx + r, dy + r], fill=(242, 242, 238), outline=(120, 120, 115), width=2)
    d.text((dx, dy), "D", font=bold, fill=(30, 30, 30), anchor="mm")


def _amount_pill(d: ImageDraw.ImageDraw, x: float, y: float, text: str, font, ts: int, style: str,
                 fill: Tuple[int, int, int], color=(240, 240, 235), anchor: str = "m") -> Tuple[float, float]:
    """An amount in a box: "pill" (rounded), "outline" (outlined box) or "coin" (with a coin).
    anchor "m" centres it on x, "l" starts it at x. Returns its width and height."""
    tw = font.getlength(text)
    coin = style == "coin"
    pad = ts * 0.5
    w = tw + 2 * pad + (ts * 1.1 if coin else 0)
    h = ts * 1.3
    x0 = x - w / 2 if anchor == "m" else x
    if style == "outline":
        d.rectangle([x0, y - h / 2, x0 + w, y + h / 2], fill=fill, outline=(235, 235, 235), width=2)
    else:
        d.rounded_rectangle([x0, y - h / 2, x0 + w, y + h / 2], radius=int(h / 2), fill=fill)
    tx = x0 + pad
    if coin:
        r = ts * 0.42
        d.ellipse([tx, y - r, tx + 2 * r, y + r], fill=(240, 190, 40), outline=(170, 120, 20), width=2)
        tx += ts * 1.1
    d.text((tx, y), text, font=font, fill=color, anchor="lm")
    return w, h


def _draw_avatar(img: Image.Image, ax: float, ay: float, r: float, key: str, dim: bool) -> None:
    """A round player picture: a coloured background, a head and shoulders."""
    size = max(8, int(2 * r))
    pal = [(70, 110, 200), (190, 90, 60), (120, 70, 170), (60, 150, 160), (210, 160, 60), (90, 160, 90),
           (200, 80, 140)]
    k = sum(ord(c) * (j + 1) for j, c in enumerate(key))
    bg, shirt = pal[k % len(pal)], pal[(k // 7 + 3) % len(pal)]
    skin = [(240, 200, 170), (200, 150, 110), (150, 100, 70)][k % 3]
    hair = [(40, 30, 20), (120, 70, 30), (220, 200, 120), (30, 30, 30)][(k // 3) % 4]
    layer = Image.new("RGB", (size, size), bg)
    ld = ImageDraw.Draw(layer)
    ld.ellipse([0.10 * size, 0.64 * size, 0.90 * size, 1.30 * size], fill=shirt)
    ld.ellipse([0.30 * size, 0.18 * size, 0.70 * size, 0.64 * size], fill=skin)
    ld.chord([0.28 * size, 0.12 * size, 0.72 * size, 0.50 * size], 180, 360, fill=hair)
    if dim:
        layer = layer.point(lambda v: int(v * 0.45))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, size - 1, size - 1], fill=255)
    img.paste(layer, (int(ax - r), int(ay - r)), mask)


def _hand_strength(cards: List[str], board: List[str]) -> str:
    allc = list(cards) + list(board)
    counts = sorted((sum(1 for c in allc if c[0] == r) for r in {c[0] for c in allc}), reverse=True)
    suits = max(sum(1 for c in allc if c[1] == s) for s in "cdhs")
    if counts and counts[0] == 4:
        return "Four of a Kind"
    if len(counts) > 1 and counts[0] == 3 and counts[1] >= 2:
        return "Full House"
    if suits >= 5:
        return "Flush"
    if counts and counts[0] == 3:
        return "Three of a Kind"
    if len(counts) > 1 and counts[0] == 2 and counts[1] == 2:
        return "Two Pair"
    if counts and counts[0] == 2:
        return "One Pair"
    return "High Card"


def _avatar_seat(img, d, view: TableView, lay: Layout, i: int, s: SeatView, ax: float, ay: float, cx: float,
                 cy: float, font, bold, small, meta: dict) -> None:
    """One player drawn as a round picture with the name and stack by it."""
    ts = lay.text_size
    r = lay.avatar_r * ts
    th = lay.deck
    hero = i == 0
    dim = not s.has_cards and not hero
    acting = view.acting == i
    toward = 1.0 if ax <= cx + 1 else -1.0  # the side facing the middle
    # cards: yours above the picture (or beside it), backs or shown cards beside it
    if hero and view.hero_cards:
        hw, hh = int(th.card_w * lay.hero_card_scale), int(th.card_h * lay.hero_card_scale)
        hth = replace(th, card_w=hw, card_h=hh)
        step = hw + 6
        if lay.name_above:
            hx, hy = int(ax + r + 8), int(ay - hh / 2 - 0.1 * hh)
        else:
            hx, hy = int(ax - (hw + step) / 2), int(ay - r - hh - 4 + lay.hero_overlap * hh)
        if not lay.hero_overlap:
            for k, c in enumerate(view.hero_cards):
                meta["hero_boxes"].append(draw_card(img, c, hx + k * step, hy, hth))
    elif s.shown and not hero:
        sw, sh = int(th.card_w * 0.8), int(th.card_h * 0.8)
        sth = replace(th, card_w=sw, card_h=sh)
        hx = int(ax + r + 4) if toward > 0 else int(ax - r - 4 - 2 * sw - 6)
        for k, c in enumerate(s.shown):
            draw_card(img, c, hx + k * (sw + 6), int(ay - sh / 2), sth)
    elif s.has_cards and not hero:
        bw, bh = int(0.62 * r), int(0.88 * r)
        bx = int(ax + 0.85 * r) if toward > 0 else int(ax - 0.85 * r - 2 * bw - 3)
        by = int(ay - 0.95 * r)
        for k in range(2):
            draw_card_back(img, bx + k * (bw + 3), by, bw, bh, replace(th, back=lay.back))
    _draw_avatar(img, ax, ay, r, s.name, dim)
    d.ellipse([ax - r - 2, ay - r - 2, ax + r + 2, ay + r + 2], outline=(70, 70, 70) if dim else (225, 225, 215), width=3)
    if acting and lay.acting_ring:  # time left, as a coloured ring
        g = max(4, ts // 4)
        d.arc([ax - r - g - 3, ay - r - g - 3, ax + r + g + 3, ay + r + g + 3], start=-90,
              end=-90 + 360 * max(0.08, view.timer_left), fill=lay.timer_color, width=g)
    if acting and lay.countdown:  # the seconds left in big digits on the picture
        big = _font(find_font(*TEXT_BOLD_FONTS), int(ts * 1.35))
        d.text((ax - 0.2 * r, ay + 0.25 * r), f"{max(1, int(round(view.timer_left * 15))):02d}", font=big,
               fill=(250, 210, 60), anchor="mm", stroke_width=2, stroke_fill=(40, 20, 0))
    if lay.level == "badge":
        lr = ts * 0.62
        lx, ly = ax - 0.78 * r, ay + 0.70 * r
        d.ellipse([lx - lr, ly - lr, lx + lr, ly + lr], fill=(40, 90, 50) if dim else (40, 150, 70),
                  outline=(235, 235, 235), width=2)
        lvf = _font(find_font(*TEXT_BOLD_FONTS), int(ts * 0.62))
        d.text((lx, ly), str(level_of(s.name, lay)), font=lvf, fill=(255, 255, 255), anchor="mm")
    if hero and view.hero_cards and lay.hero_overlap:  # your cards lie over your picture
        for k, c in enumerate(view.hero_cards):
            meta["hero_boxes"].append(draw_card(img, c, hx + k * step, hy, hth))
    # name and stack
    name = _shown_name(s.name, lay)
    stack = "All in" if s.all_in and s.stack <= 0 else amount_text(s.stack, lay)
    name_col = (130, 130, 125) if dim else lay.name_color
    stack_col = (140, 140, 135) if dim else (245, 245, 240)
    box_fill = (40, 160, 70) if (hero and lay.stack_box == "outline") else (16, 30, 20) if lay.stack_box == "pill" \
        else (22, 28, 70) if lay.stack_box == "outline" else (18, 18, 18)
    if dim:
        box_fill = tuple(int(c * 0.7) for c in box_fill)
    style = lay.stack_box if lay.stack_box != "none" else "pill"
    items_x = [ax - r, ax + r]
    if lay.name_above:
        ny, sy = ay - r - 0.8 * ts, ay + r + 0.95 * ts
    else:
        ny, sy = ay + r + 0.8 * ts, ay + r + 2.15 * ts
    d.text((ax, ny), name, font=bold, fill=name_col, anchor="mm")
    nw = bold.getlength(name)
    items_x += [ax - nw / 2, ax + nw / 2]
    if hero and lay.hand_strength and view.hero_cards:
        # "High Card" over your stack, beside the picture (your name stays under it)
        lx = ax + r + 0.7 * ts
        d.text((lx, ay - 0.45 * ts), _hand_strength(view.hero_cards, view.board), font=small, fill=(250, 250, 245),
               anchor="lm")
        w, _ = _amount_pill(d, lx, ay + 0.85 * ts, stack, font, ts, style, box_fill, stack_col, anchor="l")
        items_x += [lx + w, lx + small.getlength("Three of a Kind")]
    else:
        w, _ = _amount_pill(d, ax, sy, stack, font, ts, style, box_fill, stack_col)
        items_x += [ax - w / 2, ax + w / 2]
    top = ny - 0.6 * ts if lay.name_above else ay - r
    bottom = sy + 0.7 * ts
    x0, x1 = min(items_x), max(items_x)
    meta["plates"].append(((x0 + x1) / 2, (top + bottom) / 2, x1 - x0, bottom - top))
    # bet toward the middle
    if s.bet > 0 and lay.show_bets:
        if hero and not lay.name_above:  # above your cards
            hw, hh = th.card_w * lay.hero_card_scale, th.card_h * lay.hero_card_scale
            _bet(d, lay, ax + 0.3 * hw, ay - r - hh - 4 + lay.hero_overlap * hh - 0.9 * ts, s.bet, font)
        else:
            _bet(d, lay, ax + (cx - ax) * 0.42, ay + (cy - ay) * 0.42, s.bet, font)
    if view.button == i:
        if hero:
            dx, dy = ax - r - 0.9 * ts, ay + 0.5 * r
        else:
            dx, dy = ax + toward * (r + 0.95 * ts), ay + 0.55 * r
        _dealer(d, dx, dy, lay, bold)


def _top_bar(d: ImageDraw.ImageDraw, lay: Layout, small, bold) -> None:
    """Your level star and experience counter (top right), menu and settings (top left)."""
    W = lay.width
    for k in range(2):
        x = 24 + k * 58
        d.rounded_rectangle([x, 16, x + 46, 62], radius=10, fill=(60, 130, 70), outline=(160, 210, 160), width=2)
        for j in range(3):
            d.line([(x + 12, 28 + j * 10), (x + 34, 28 + j * 10)], fill=(240, 250, 240), width=3)
    sx, sy, rr = W - 330, 30, 11
    star = [(sx + rr * math.cos(math.radians(-90 + 36 * k)) * (1 if k % 2 == 0 else 0.45),
             sy + rr * math.sin(math.radians(-90 + 36 * k)) * (1 if k % 2 == 0 else 0.45)) for k in range(10)]
    d.polygon(star, fill=(250, 200, 40))
    d.text((sx + 18, sy), "1", font=bold, fill=(245, 245, 235), anchor="lm")
    d.rounded_rectangle([W - 290, 24, W - 40, 36], radius=6, fill=(30, 60, 36))
    d.rounded_rectangle([W - 290, 24, W - 290 + int(250 * 0.59), 36], radius=6, fill=(150, 220, 140))
    d.text((W - 40, 52), "300512 / 512000", font=small, fill=(200, 230, 200), anchor="rm")


def _extras(d: ImageDraw.ImageDraw, lay: Layout, bold, small) -> None:
    """"Bonus +100%" (top left), menu and settings (top right), a notification count (bottom left)."""
    W, H = lay.width, lay.height
    r = 34
    d.ellipse([24, 18, 24 + 2 * r, 18 + 2 * r], fill=(220, 40, 60), outline=(250, 250, 250), width=4)
    d.ellipse([24 + 14, 18 + 14, 24 + 2 * r - 14, 18 + 2 * r - 14], outline=(250, 250, 250), width=3)
    d.text((24 + 2 * r + 12, 36), "Bonus", font=bold, fill=(245, 245, 245), anchor="lm")
    d.text((24 + 2 * r + 12, 66), "+100%", font=bold, fill=(140, 230, 90), anchor="lm")
    for k in range(2):
        x = W - 24 - 64 - k * 76
        d.ellipse([x, 16, x + 64, 80], fill=(60, 70, 120), outline=(110, 120, 170), width=2)
        for j in range(3):
            d.line([(x + 18, 36 + j * 11), (x + 46, 36 + j * 11)], fill=(235, 235, 245), width=4)
    bx, by = 30, H - 110
    d.rounded_rectangle([bx, by, bx + 140, by + 80], radius=12, fill=(80, 70, 140))
    for k in range(3):
        hx = bx + 40 + k * 30
        d.ellipse([hx - 11, by + 18, hx + 11, by + 40], fill=(190, 150, 240))
        d.chord([hx - 18, by + 42, hx + 18, by + 78], 180, 360, fill=(190, 150, 240))
    d.ellipse([bx - 14, by - 14, bx + 16, by + 16], fill=(220, 40, 40), outline=(250, 250, 250), width=2)
    d.text((bx + 1, by + 1), "3", font=bold, fill=(255, 255, 255), anchor="mm")


def _button_fill(label: str) -> Tuple[int, int, int]:
    low = label.lower()
    if low.startswith("fold"):
        return (176, 38, 44)
    if low.startswith(("raise", "bet", "all")):
        return (64, 162, 64)
    return (58, 76, 168)


def _button_column(d: ImageDraw.ImageDraw, lay: Layout, labels: List[str], bold) -> None:
    """Buttons stacked at the right edge, raise on top and fold at the bottom."""
    W, H, ts = lay.width, lay.height, lay.text_size
    bw = int(max(ts * 6.5, max(bold.getlength(b) for b in labels) + 1.4 * ts))
    bh = int(ts * 2.6)
    x = W - 20 - bw
    for k, label in enumerate(reversed(labels)):
        y = H - 20 - (len(labels) - k) * (bh + 12)
        d.rounded_rectangle([x, y, x + bw, y + bh], radius=8, fill=_button_fill(label), outline=(20, 20, 30), width=2)
        d.text((x + bw / 2, y + bh / 2), label, font=bold, fill=(250, 250, 250), anchor="mm")


def _button_bar(d: ImageDraw.ImageDraw, lay: Layout, labels: List[str], bold) -> None:
    """Buttons side by side across the whole bottom edge (phones)."""
    W, H, ts = lay.width, lay.height, lay.text_size
    n = len(labels)
    gap = 12
    bw = (W - 32 - (n - 1) * gap) / n
    bh = int(ts * 2.3)
    y = H - bh - 18
    for k, label in enumerate(labels):
        x = 16 + k * (bw + gap)
        d.rounded_rectangle([x, y, x + bw, y + bh], radius=bh // 2, fill=_button_fill(label), outline=(240, 200, 80),
                            width=2)
        d.text((x + bw / 2, y + bh / 2), label, font=bold, fill=(250, 250, 250), anchor="mm")


def render(view: TableView, lay: Layout) -> Tuple[np.ndarray, dict]:
    """The picture and where things were drawn (in the picture's own pixels)."""
    W, H = lay.width, lay.height
    img = Image.new("RGB", (W, H), lay.background)
    d = ImageDraw.Draw(img)
    font = _font(lay.text_font or find_font(*TEXT_FONTS), lay.text_size)
    bold = _font(find_font(*TEXT_BOLD_FONTS), lay.text_size)
    small = _font(lay.text_font or find_font(*TEXT_FONTS), int(lay.text_size * 0.85))
    cur = lay.currency
    ts = lay.text_size
    fx0, fy0, fx1, fy1 = lay.felt_box
    rim = lay.rim
    d.ellipse([fx0 * W - rim, fy0 * H - rim, fx1 * W + rim, fy1 * H + rim], fill=lay.felt_edge)
    d.ellipse([fx0 * W, fy0 * H, fx1 * W, fy1 * H], fill=lay.felt)
    cx, cy = (fx0 + fx1) / 2 * W, (fy0 + fy1) / 2 * H
    meta: dict = {"plates": [], "board_boxes": [], "hero_boxes": []}

    # header
    if lay.header:
        d.rounded_rectangle([24, 14, W - 24, 14 + int(lay.text_size * 2.1)], radius=6, fill=(52, 52, 50),
                            outline=(90, 90, 88))
        header = lay.header.format(cur=cur, sb=amount_text(1, lay), bb=amount_text(2, lay))
        d.text((44, 14 + lay.text_size * 1.05), header, font=font, fill=(210, 210, 205), anchor="lm")
    if lay.top_bar:
        _top_bar(d, lay, small, bold)
    if lay.extras:
        _extras(d, lay, bold, small)

    # board: five slots, dealt cards face up
    th = lay.deck
    gap = int(th.card_w * 0.15)
    bx0 = int(cx - (5 * th.card_w + 4 * gap) / 2)
    by0 = int(cy - th.card_h / 2 - th.card_h * 0.05)
    for i in range(5):
        x = bx0 + i * (th.card_w + gap)
        if i < len(view.board):
            meta["board_boxes"].append(draw_card(img, view.board[i], x, by0, th))
        elif lay.question_slots:
            shade = tuple(min(255, c + 30) for c in lay.felt)
            d.rounded_rectangle([x, by0, x + th.card_w, by0 + th.card_h], radius=max(3, th.card_w // 10), fill=shade)
            d.text((x + th.card_w / 2, by0 + th.card_h / 2), "?", font=bold, fill=tuple(min(255, c + 70) for c in lay.felt),
                   anchor="mm")
        elif lay.empty_board_slots:
            _dashed_rect(d, (x, by0, x + th.card_w, by0 + th.card_h), tuple(min(255, c + 45) for c in lay.felt))

    # pot labels
    bets = sum(s.bet for s in view.seats)
    pot_y = by0 - lay.text_size * 1.6
    if lay.pot_mode == "total":
        if view.collected + bets > 0:
            d.text((cx + lay.text_size * 2, pot_y), f"Total pot: {amount_text(view.collected + bets, lay)}", font=font,
                   fill=(225, 225, 220), anchor="lm")
        if view.collected > 0:
            px, py = cx - lay.text_size * 2.5, by0 + th.card_h + lay.text_size * 1.6
            r = lay.text_size * 0.55
            d.ellipse([px - 2 * r - 6, py - r, px - 6, py + r], outline=(220, 220, 215), width=2)
            d.text((px, py), amount_text(view.collected, lay), font=font, fill=(225, 225, 220), anchor="lm")
    elif lay.pot_mode in ("pot", "all"):
        shown = view.collected + (bets if lay.pot_mode == "all" else 0.0)
        if shown > 0:
            if lay.pot_style == "tight":
                d.text((bx0, by0 + th.card_h + ts * 1.5), f"Pot:{amount_text(shown, lay)}", font=bold,
                       fill=(245, 245, 240), anchor="lm")
            elif lay.pot_style == "stacked":
                ly = by0 + th.card_h + ts * 1.1
                d.text((cx, ly), "Pot Amt.", font=small, fill=(230, 230, 225), anchor="mm")
                _amount_pill(d, cx, ly + ts * 1.45, amount_text(shown, lay), font, ts, "coin", (20, 20, 20))
            else:
                d.text((cx, pot_y), f"Pot: {amount_text(shown, lay)}", font=bold, fill=(240, 240, 235), anchor="mm")

    pw, ph = int(lay.text_size * 7.6), int(lay.text_size * 2.9)
    avatar = lay.seat_style == "avatar"
    ar = lay.avatar_r * ts
    # empty seats
    for sx, sy in _empty_points(lay):
        if avatar:
            d.ellipse([sx - ar, sy - ar, sx + ar, sy + ar], fill=tuple(int(c * 0.8) for c in lay.background),
                      outline=tuple(min(255, c + 60) for c in lay.background), width=3)
            if lay.empty_seat_text:
                d.text((sx, sy), lay.empty_seat_text, font=small, fill=(220, 220, 225), anchor="mm")
            else:  # a "sit here" sign
                k = ar * 0.35
                d.line([(sx - k, sy), (sx + k, sy)], fill=(200, 210, 200), width=4)
                d.line([(sx, sy - k), (sx, sy + k)], fill=(200, 210, 200), width=4)
        else:
            _dashed_rect(d, (sx - pw / 2, sy - ph / 2, sx + pw / 2, sy + ph / 2), (110, 110, 105))
            d.text((sx, sy), lay.empty_seat_text, font=small, fill=(150, 150, 145), anchor="mm")

    pts = _seat_points(lay)
    for i, (s, (sx, sy)) in enumerate(zip(view.seats, pts)):
        if avatar:
            _avatar_seat(img, d, view, lay, i, s, sx, sy, cx, cy, font, bold, small, meta)
            continue
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
        name = s.tag if (lay.action_tags and s.tag) else _shown_name(s.name, lay)
        d.text((sx, y0 + ph * 0.30), name, font=bold, fill=(130, 130, 125) if dim else lay.name_color, anchor="mm")
        stack = "All in" if s.all_in and s.stack <= 0 else amount_text(s.stack, lay)
        d.text((sx, y0 + ph * 0.72), stack, font=font, fill=(120, 120, 115) if dim else lay.stack_color,
               anchor="mm")
        if lay.level == "text":  # a bare number beside the name, on the side toward the middle
            lv = str(level_of(s.name, lay))
            right = sx <= cx
            d.text((x0 + pw + 6 if right else x0 - 6, y0 + ph * 0.30), lv, font=bold,
                   fill=(150, 125, 50) if dim else (236, 196, 70), anchor="lm" if right else "rm")
        if lay.level == "corner":  # the player's level in a small box on the name's line
            lv = str(level_of(s.name, lay))
            lw = max(ts * 1.3, small.getlength(lv) + ts * 0.5)
            lx1, ly = x0 + pw - 5, y0 + ph * 0.30
            d.rounded_rectangle([lx1 - lw, ly - ts * 0.55, lx1, ly + ts * 0.55], radius=4,
                                fill=(120, 100, 40) if dim else (214, 172, 52))
            d.text((lx1 - lw / 2, ly), lv, font=small, fill=(30, 26, 10), anchor="mm")
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
            _bet(d, lay, bx, by, s.bet, font)
        # dealer button beside the plate, on the side toward the middle
        if view.button == i:
            side = 1.0 if sx <= cx else -1.0
            dx = sx + side * (pw / 2 + lay.text_size * 1.1)
            dy = sy + (-ph * 0.4 if sy > cy else ph * 0.4)
            if i == 0:
                dx, dy = sx + pw / 2 + lay.text_size * 1.4, y0 - lay.text_size * 0.5
            _dealer(d, dx, dy, lay, bold)
        meta["plates"].append((sx, sy, pw, ph))

    # hand number, action buttons or pre-action boxes
    if lay.hand_id and view.hand_no:
        text = lay.hand_id_fmt.format(n=357_618_000 + view.hand_no)
        if avatar:
            d.text((20, 0.085 * H), text, font=small, fill=(170, 150, 140), anchor="lm")
        else:
            d.rounded_rectangle([24, H - 58, 24 + lay.text_size * 13, H - 18], radius=6, fill=(52, 52, 50),
                                outline=(90, 90, 88))
            d.text((40, H - 38), text, font=font, fill=(200, 200, 195), anchor="lm")
    if view.buttons:
        labels = [b.upper() for b in view.buttons] if lay.upper_buttons else list(view.buttons)
        if lay.buttons_style == "column":
            _button_column(d, lay, labels, bold)
        elif lay.buttons_style == "bar":
            _button_bar(d, lay, labels, bold)
        else:
            bw = int(max(lay.text_size * 6.2, max(font.getlength(b) for b in labels) + lay.text_size))
            bh = int(lay.text_size * 2.1)
            x = W - 24 - len(labels) * (bw + 10)
            y = H - bh - 18
            for k, label in enumerate(labels):
                bx = x + k * (bw + 10)
                if lay.upper_buttons:
                    d.rounded_rectangle([bx, y, bx + bw, y + bh], radius=bh // 2, fill=_button_fill(label),
                                        outline=(230, 240, 230), width=2)
                else:
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
        if lay.upper_buttons:  # dim pills in the buttons' place
            bh = int(ts * 2.1)
            x, y = W - 24, H - bh - 18
            for label in ("CALL ANY", "CHECK / FOLD"):
                bw = int(font.getlength(label) + 2 * ts)
                x -= bw + 10
                d.rounded_rectangle([x, y, x + bw, y + bh], radius=bh // 2, fill=tuple(int(c * 0.8) for c in lay.background),
                                    outline=(120, 150, 120), width=2)
                d.text((x + bw / 2, y + bh / 2), label, font=small, fill=(150, 170, 150), anchor="mm")
        else:
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
