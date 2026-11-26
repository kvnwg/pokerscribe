"""Render synthetic poker-table screenshots with known ground truth.

Used by the test-suite and to build the demo screenshots in app/assets/demo.
Card indices are drawn with fonts that are NOT used to build the recognizer's
generic templates, so tests measure generalisation rather than memorisation.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

RANK_TEXT = {"T": "10"}
SUIT_CHAR = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}

_FONT_DIRS = [
    "/usr/share/fonts",
    "/usr/share/texmf/fonts",
    "/System/Library/Fonts",
    "/System/Library/Fonts/Supplemental",
    "/Library/Fonts",
    os.path.expanduser("~/Library/Fonts"),
]
_font_index: Optional[Dict[str, str]] = None


def find_font(*names: str) -> Optional[str]:
    """Return the first font file whose basename matches one of `names`."""
    global _font_index
    if _font_index is None:
        _font_index = {}
        for root_dir in _FONT_DIRS:
            if not os.path.isdir(root_dir):
                continue
            for root, _dirs, files in os.walk(root_dir):
                for f in files:
                    if f.lower().endswith((".ttf", ".otf", ".ttc")):
                        _font_index.setdefault(f.lower(), os.path.join(root, f))
    for n in names:
        p = _font_index.get(n.lower())
        if p:
            return p
    return None


# Held-out fonts for card indices (not used by tools/build_templates.py).
HELD_OUT_RANK_FONTS = [
    ["texgyreadventor-bold.otf"],
    ["GilliusADF-Bold.otf"],
    ["Loma-Bold.otf"],
    ["lmsans10-bold.otf"],
    ["CrimsonText-Bold.ttf"],
    ["texgyreschola-bold.otf"],
    ["Arial Bold.ttf", "Arial Black.ttf"],  # macOS fallback
]
TEXT_FONTS = ["DejaVuSans.ttf", "LiberationSans-Regular.ttf", "Arial.ttf", "Helvetica.ttc"]
TEXT_BOLD_FONTS = ["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf", "Arial Bold.ttf", "Helvetica.ttc"]


def held_out_rank_fonts() -> List[str]:
    out = []
    for names in HELD_OUT_RANK_FONTS:
        p = find_font(*names)
        if p:
            out.append(p)
    return out


def _font(path: Optional[str], size: int) -> ImageFont.FreeTypeFont:
    if path:
        return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


@dataclass
class Theme:
    width: int = 1280
    height: int = 860
    background: Tuple[int, int, int] = (17, 19, 23)
    felt: Tuple[int, int, int] = (29, 112, 66)
    felt_edge: Tuple[int, int, int] = (20, 80, 47)
    rail: Tuple[int, int, int] = (58, 42, 30)
    card_w: int = 64
    card_h: int = 90
    rank_font: Optional[str] = None
    suit_font: Optional[str] = None  # None = draw suit shapes
    four_color: bool = False
    face: Tuple[int, int, int] = (250, 250, 248)
    back: Tuple[int, int, int] = (176, 32, 44)
    text_size: int = 18
    nameplate: Tuple[int, int, int] = (34, 37, 43)
    hero_overlap: float = 0.0  # 0 = side by side, 0.4 = 40% overlap
    scale: float = 1.0
    blur: float = 0.0
    jpeg_quality: Optional[int] = None
    noise: float = 0.0


@dataclass
class SynthPlayer:
    name: str
    stack: str
    bet: Optional[str] = None
    in_hand: bool = True
    action: Optional[str] = None


@dataclass
class SynthTable:
    players: List[SynthPlayer]  # 0 = hero at the bottom, then clockwise
    hero_cards: List[str]
    board: List[str]
    pot: Optional[str] = "Pot: 120"
    button: int = 0
    action_buttons: List[str] = field(default_factory=list)
    pre_actions: List[str] = field(default_factory=list)  # checkboxes shown when it is not hero's turn
    blinds_text: Optional[str] = None
    theme: Theme = field(default_factory=Theme)


def suit_color(suit: str, four_color: bool) -> Tuple[int, int, int]:
    if four_color:
        return {"s": (20, 20, 20), "h": (205, 28, 36), "d": (30, 90, 200), "c": (24, 140, 52)}[suit]
    return (205, 28, 36) if suit in "hd" else (20, 20, 20)


def draw_suit_shape(d: ImageDraw.ImageDraw, suit: str, cx: float, cy: float, size: float, fill) -> None:
    """Suit symbols drawn from circles and polygons (a different construction from the
    recognizer's templates, so tests do not compare a shape with itself)."""
    s = size / 2.0
    if suit == "d":
        d.polygon([(cx, cy - s), (cx + s * 0.72, cy), (cx, cy + s), (cx - s * 0.72, cy)], fill=fill)
    elif suit == "h":
        r = s * 0.52
        d.ellipse([cx - 2 * r + r * 0.15, cy - s * 0.75, cx + r * 0.15, cy - s * 0.75 + 2 * r], fill=fill)
        d.ellipse([cx - r * 0.15, cy - s * 0.75, cx + 2 * r - r * 0.15, cy - s * 0.75 + 2 * r], fill=fill)
        d.polygon([(cx - s * 0.93, cy - s * 0.18), (cx + s * 0.93, cy - s * 0.18), (cx, cy + s)], fill=fill)
    elif suit == "s":
        # upside-down heart body with a slim flared stem
        r = s * 0.44
        d.ellipse([cx - 2 * r + r * 0.12, cy - s * 0.12, cx + r * 0.12, cy - s * 0.12 + 2 * r], fill=fill)
        d.ellipse([cx - r * 0.12, cy - s * 0.12, cx + 2 * r - r * 0.12, cy - s * 0.12 + 2 * r], fill=fill)
        d.polygon([(cx - s * 0.84, cy + s * 0.22), (cx + s * 0.84, cy + s * 0.22), (cx, cy - s)], fill=fill)
        d.polygon([(cx - s * 0.07, cy + s * 0.3), (cx + s * 0.07, cy + s * 0.3),
                   (cx + s * 0.3, cy + s), (cx - s * 0.3, cy + s)], fill=fill)
    elif suit == "c":
        # three overlapping lobes and a slim flared stem
        r = s * 0.40
        d.ellipse([cx - r, cy - s, cx + r, cy - s + 2 * r], fill=fill)
        d.ellipse([cx - s * 0.9, cy - s * 0.32, cx - s * 0.9 + 2 * r, cy - s * 0.32 + 2 * r], fill=fill)
        d.ellipse([cx + s * 0.9 - 2 * r, cy - s * 0.32, cx + s * 0.9, cy - s * 0.32 + 2 * r], fill=fill)
        d.ellipse([cx - r * 0.6, cy - s * 0.45, cx + r * 0.6, cy + s * 0.1], fill=fill)
        d.polygon([(cx - s * 0.07, cy + s * 0.1), (cx + s * 0.07, cy + s * 0.1),
                   (cx + s * 0.3, cy + s), (cx - s * 0.3, cy + s)], fill=fill)


def draw_card(img: Image.Image, card: str, x: int, y: int, th: Theme) -> Tuple[int, int, int, int]:
    """Draw a face-up card with top-left corner at (x, y). Returns its box."""
    w, h = th.card_w, th.card_h
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x, y, x + w, y + h], radius=max(3, w // 10), fill=th.face, outline=(150, 150, 150), width=1)
    rank, suit = card[0], card[1]
    color = suit_color(suit, th.four_color)
    rank_txt = RANK_TEXT.get(rank, rank)
    rsize = int(h * 0.30)
    rfont = _font(th.rank_font, rsize)
    if rank_txt == "10":
        # real decks squeeze "10" into the same index width
        rfont = _font(th.rank_font, int(rsize * 0.85))
    d.text((x + w * 0.08, y + h * 0.05), rank_txt, font=rfont, fill=color, anchor="lt")
    bbox = d.textbbox((x + w * 0.08, y + h * 0.05), rank_txt, font=rfont, anchor="lt")
    ssize = h * 0.22
    scx = (bbox[0] + bbox[2]) / 2
    scy = bbox[3] + h * 0.04 + ssize / 2
    if th.suit_font:
        sfont = _font(th.suit_font, int(ssize * 1.25))
        d.text((scx, scy), SUIT_CHAR[suit], font=sfont, fill=color, anchor="mm")
    else:
        draw_suit_shape(d, suit, scx, scy, ssize, color)
    big = h * 0.42
    if th.suit_font:
        sfont = _font(th.suit_font, int(big * 1.25))
        d.text((x + w * 0.62, y + h * 0.66), SUIT_CHAR[suit], font=sfont, fill=color, anchor="mm")
    else:
        draw_suit_shape(d, suit, x + w * 0.62, y + h * 0.66, big, color)
    return x, y, w, h


def draw_card_back(img: Image.Image, x: int, y: int, w: int, h: int, th: Theme) -> None:
    tile = Image.new("RGB", (w, h), th.back)
    td = ImageDraw.Draw(tile)
    light = tuple(min(255, c + 30) for c in th.back)
    for k in range(-h, w, 6):
        td.line([(k, 0), (k + h, h)], fill=light, width=1)
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=max(2, w // 8), fill=255)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x - 2, y - 2, x + w + 1, y + h + 1], radius=max(2, w // 8), fill=(235, 235, 235))
    img.paste(tile, (x, y), mask)


def seat_points(n: int, th: Theme) -> List[Tuple[float, float]]:
    cx, cy = th.width / 2, th.height * 0.45
    rx, ry = th.width * 0.40, th.height * 0.355
    pts = []
    for i in range(n):
        a = math.radians(90 + i * 360.0 / n)
        pts.append((cx + rx * math.cos(a), cy + ry * math.sin(a)))
    return pts


def render_table(t: SynthTable) -> Tuple[np.ndarray, dict]:
    th = t.theme
    W, H = th.width, th.height
    img = Image.new("RGB", (W, H), th.background)
    d = ImageDraw.Draw(img)
    cx, cy = W / 2, H * 0.45
    d.ellipse([W * 0.08, H * 0.12, W * 0.92, H * 0.80], fill=th.rail)
    d.ellipse([W * 0.10, H * 0.145, W * 0.90, H * 0.775], fill=th.felt_edge)
    d.ellipse([W * 0.115, H * 0.165, W * 0.885, H * 0.755], fill=th.felt)

    font = _font(find_font(*TEXT_FONTS), th.text_size)
    bold = _font(find_font(*TEXT_BOLD_FONTS), th.text_size)
    truth: dict = {"seats": [], "hero_cards": list(t.hero_cards), "board": list(t.board), "card_boxes": {}}

    # board and pot
    n_board = len(t.board)
    gap = 8
    total_w = 5 * th.card_w + 4 * gap
    bx0 = int(cx - total_w / 2)
    by0 = int(cy - th.card_h / 2)
    for i, c in enumerate(t.board):
        truth["card_boxes"][f"board{i}"] = draw_card(img, c, bx0 + i * (th.card_w + gap), by0, th)
    if t.pot:
        d.text((cx, by0 - 26), t.pot, font=bold, fill=(240, 240, 240), anchor="mm")
    if t.blinds_text:
        d.text((24, 18), t.blinds_text, font=font, fill=(170, 175, 182), anchor="lt")

    pts = seat_points(len(t.players), th)
    plate_w, plate_h = int(th.text_size * 8.2), int(th.text_size * 2.9)
    for i, (p, (sx, sy)) in enumerate(zip(t.players, pts)):
        hero = i == 0
        # cards first so the nameplate overlaps them, like most clients
        if hero and t.hero_cards:
            step = int(th.card_w * (1 - th.hero_overlap)) + (6 if th.hero_overlap == 0 else 0)
            total = th.card_w + step * (len(t.hero_cards) - 1)
            hx = int(sx - total / 2)
            hy = int(sy - plate_h / 2 - th.card_h + 8)
            for k, c in enumerate(t.hero_cards):
                truth["card_boxes"][f"hero{k}"] = draw_card(img, c, hx + k * step, hy, th)
        elif p.in_hand and not hero:
            bw, bh = int(th.card_w * 0.55), int(th.card_h * 0.55)
            bx = int(sx - bw * 0.8)
            by = int(sy - plate_h / 2 - bh + 6)
            draw_card_back(img, bx, by, bw, bh, th)
            draw_card_back(img, bx + int(bw * 0.6), by - 2, bw, bh, th)
        x0, y0 = int(sx - plate_w / 2), int(sy - plate_h / 2)
        shade = th.nameplate if p.in_hand or hero else tuple(int(c * 0.7) for c in th.nameplate)
        d.rounded_rectangle([x0, y0, x0 + plate_w, y0 + plate_h], radius=8, fill=shade, outline=(70, 74, 82))
        name_col = (235, 235, 235) if p.in_hand or hero else (130, 130, 130)
        d.text((sx, y0 + plate_h * 0.30), p.name, font=font, fill=name_col, anchor="mm")
        d.text((sx, y0 + plate_h * 0.72), p.stack, font=bold, fill=(255, 214, 102), anchor="mm")
        if p.action:
            aw = int(th.text_size * 4.6)
            ah = int(th.text_size * 1.35)
            ax0, ay0 = int(sx - aw / 2), int(y0 - ah * 0.8)
            d.rounded_rectangle([ax0, ay0, ax0 + aw, ay0 + ah], radius=5, fill=(46, 120, 200))
            d.text((sx, ay0 + ah / 2), p.action, font=bold, fill=(255, 255, 255), anchor="mm")
        if p.bet:
            bx = sx + (cx - sx) * 0.42
            by = sy + (cy - sy) * 0.42
            r = th.text_size * 0.55
            d.ellipse([bx - 2 * r - 4, by - r, bx - 4, by + r], fill=(210, 60, 60), outline=(250, 250, 250))
            d.text((bx + 2, by), p.bet, font=bold, fill=(250, 250, 250), anchor="lm")
        if i == t.button:
            side = 1.0 if cx - sx >= -1 else -1.0
            dx = sx + side * plate_w * 0.64
            dy = sy + (plate_h * 0.25 if cy > sy else -plate_h * 0.25)
            r = th.text_size * 0.75
            d.ellipse([dx - r, dy - r, dx + r, dy + r], fill=(245, 245, 245), outline=(120, 120, 120), width=2)
            d.text((dx, dy), "D", font=bold, fill=(20, 20, 20), anchor="mm")
        truth["seats"].append({"name": p.name, "stack": p.stack, "bet": p.bet, "in_hand": p.in_hand,
                               "action": p.action, "point": (sx, sy)})

    # action buttons
    if t.action_buttons:
        bw, bh = int(th.text_size * 8.5), int(th.text_size * 2.6)
        x = W - 20 - len(t.action_buttons) * (bw + 10)
        y = H - bh - 22
        colors = [(150, 40, 40), (40, 110, 60), (40, 80, 150), (110, 70, 150)]
        for k, label in enumerate(t.action_buttons):
            bx = x + k * (bw + 10)
            d.rounded_rectangle([bx, y, bx + bw, y + bh], radius=8, fill=colors[k % len(colors)])
            d.text((bx + bw / 2, y + bh / 2), label, font=bold, fill=(255, 255, 255), anchor="mm")
    if t.pre_actions:
        x = 24
        y = H - 46
        for label in t.pre_actions:
            d.rectangle([x, y + 4, x + 16, y + 20], outline=(200, 200, 200), width=2)
            d.text((x + 24, y + 12), label, font=font, fill=(220, 220, 220), anchor="lm")
            x += int(th.text_size * (len(label) * 0.62 + 4))
    truth["button"] = t.button
    truth["action_buttons"] = list(t.action_buttons)

    out = img
    if th.blur > 0:
        out = out.filter(ImageFilter.GaussianBlur(th.blur))
    arr = cv2.cvtColor(np.array(out), cv2.COLOR_RGB2BGR)
    if th.noise > 0:
        rng = np.random.default_rng(7)
        arr = np.clip(arr.astype(np.float32) + rng.normal(0, th.noise, arr.shape), 0, 255).astype(np.uint8)
    if th.scale != 1.0:
        arr = cv2.resize(arr, None, fx=th.scale, fy=th.scale, interpolation=cv2.INTER_AREA)
        for k, (x, y, w, h) in list(truth["card_boxes"].items()):
            truth["card_boxes"][k] = tuple(int(round(v * th.scale)) for v in (x, y, w, h))
    if th.jpeg_quality:
        ok, enc = cv2.imencode(".jpg", arr, [cv2.IMWRITE_JPEG_QUALITY, th.jpeg_quality])
        arr = cv2.imdecode(enc, cv2.IMREAD_COLOR)
    return arr, truth


def demo_table(theme: Optional[Theme] = None) -> SynthTable:
    """A flop spot: hero on the button facing a bet, 6-max."""
    th = theme or Theme(rank_font=(held_out_rank_fonts() or [None])[0])
    players = [
        SynthPlayer("Hero", "800"),
        SynthPlayer("RiverRat", "1,140", in_hand=False),
        SynthPlayer("Maverick", "950", bet="60", action="Bet 60"),
        SynthPlayer("Lucky7", "2,210", in_hand=False),
        SynthPlayer("Nightowl", "640", in_hand=False),
        SynthPlayer("Grinder", "1,575", in_hand=False),
    ]
    return SynthTable(
        players=players,
        hero_cards=["As", "Kh"],
        board=["Ah", "8d", "5c"],
        pot="Pot: 120",
        button=0,
        action_buttons=["Fold", "Call 60", "Raise to 240"],
        blinds_text="Blinds 5/10",
        theme=th,
    )


def render_fanned(cards: List[str], angles: List[float], h: int = 110, font: Optional[str] = None,
                  felt=(20, 100, 40), overlap: float = 0.55) -> np.ndarray:
    """Hole cards fanned like many clients draw them: each card turned by its angle
    (degrees, counter-clockwise) and overlapping the previous one."""
    th = Theme(card_w=int(h * 0.71), card_h=h, rank_font=font)
    W, H = int(h * 3.2), int(h * 2.0)
    img = Image.new("RGBA", (W, H), tuple(felt) + (255,))
    for k, (card, ang) in enumerate(zip(cards, angles)):
        layer = Image.new("RGBA", (th.card_w + 4, th.card_h + 4), (0, 0, 0, 0))
        draw_card(layer, card, 1, 1, th)
        turned = layer.rotate(ang, resample=Image.BICUBIC, expand=True)
        x = int(W * 0.25 + k * th.card_w * overlap)
        y = int(H * 0.2 + (abs(ang) * 0.6 if k else 0))
        img.alpha_composite(turned, (x, y))
    return cv2.cvtColor(np.array(img.convert("RGB")), cv2.COLOR_RGB2BGR)
