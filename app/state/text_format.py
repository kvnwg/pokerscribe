"""GameState -> the clean, machine-readable text that is the ONLY thing sent to an AI.

Only enumerated values (card names, positions, actions, statuses) and numbers are
written. Nothing read by OCR as free text (player names, table titles, site logos)
can appear, because no field of that kind is ever rendered.

Format: one "KEY: value" per line; opponent and maths blocks have a header line
ending in ":" followed by indented "Key: value" lines. Missing values are UNKNOWN.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from .model import Action, Field, GameState, Player
from .positions import label as position_label

UNKNOWN = "UNKNOWN"
RANK_NAMES = {"A": "Ace", "K": "King", "Q": "Queen", "J": "Jack", "T": "10", "9": "9", "8": "8", "7": "7",
              "6": "6", "5": "5", "4": "4", "3": "3", "2": "2"}
RANK_PLURALS = {"A": "Aces", "K": "Kings", "Q": "Queens", "J": "Jacks", "T": "Tens", "9": "Nines", "8": "Eights",
                "7": "Sevens", "6": "Sixes", "5": "Fives", "4": "Fours", "3": "Threes", "2": "Twos"}
SUIT_NAMES = {"s": "Spades", "h": "Hearts", "d": "Diamonds", "c": "Clubs"}
STREET_NAMES = {"preflop": "Preflop", "flop": "Flop", "turn": "Turn", "river": "River"}
MATH_HEADER = "LOCAL MATH (estimates from a local calculator, not solver output)"


def fmt_amount(value: float) -> str:
    """120 -> '120', 12.5 -> '12.5', 0.25 -> '0.25', 1250 -> '1250'."""
    v = float(value)
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.2f}".rstrip("0").rstrip(".")


def fmt_pct(p: float, digits: int = 1) -> str:
    return f"{100.0 * p:.{digits}f}%"


def card_name(code: str) -> str:
    return f"{RANK_NAMES[code[0]]} of {SUIT_NAMES[code[1]]}"


def card_symbol(code: str) -> str:
    return ("10" if code[0] == "T" else code[0]) + {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}[code[1]]


def describe_actions(actions: List[Action]) -> str:
    return ", ".join(a.describe() for a in actions)


def facing_summary(actions: List[Action]) -> str:
    """[Fold, Call 60, Raise to 240] -> 'Call 60, raise, or fold' (as in the spec example)."""
    kinds = {a.kind: a for a in actions}
    parts = []
    if "check" in kinds:
        parts.append("check")
    if "call" in kinds:
        amt = kinds["call"].amount
        parts.append(f"call {fmt_amount(amt)}" if amt is not None else "call")
    for k in ("bet", "raise"):
        if k in kinds:
            parts.append(k)
    if "all-in" in kinds and not ({"bet", "raise"} & set(kinds)):
        amt = kinds["all-in"].amount
        parts.append(f"all-in {fmt_amount(amt)}" if amt is not None else "all-in")
    if "fold" in kinds:
        parts.append("fold")
    if not parts:
        return UNKNOWN
    text = parts[0] if len(parts) == 1 else (" or ".join(parts) if len(parts) == 2 else ", ".join(parts[:-1]) + ", or " + parts[-1])
    return text[0].upper() + text[1:]


class _Collector:
    def __init__(self):
        self.unknown: List[str] = []

    def value(self, f: Field, name: str, fmt=lambda v: str(v)) -> str:
        if f.known:
            return fmt(f.value)
        self.unknown.append(name)
        return UNKNOWN


def render_text(state: GameState) -> str:
    c = _Collector()
    lines: List[str] = ["GAME: Texas Hold'em"]

    cards = []
    for i, f in enumerate(state.hero_cards[:2]):
        cards.append(c.value(f, f"HERO CARD {i + 1}", card_name))
    lines.append("HERO CARDS: " + (", ".join(cards) if cards else UNKNOWN))
    hero = state.hero or Player(seat=0, is_hero=True)
    lines.append("HERO POSITION: " + c.value(hero.position, "HERO POSITION", position_label))
    lines.append("STREET: " + c.value(state.street, "STREET", lambda s: STREET_NAMES[s]))
    if state.street.known and state.street.value == "preflop" and not state.board:
        lines.append("BOARD: None (preflop)")
    elif not state.board:
        c.unknown.append("BOARD")
        lines.append("BOARD: " + UNKNOWN)
    else:
        lines.append("BOARD: " + ", ".join(c.value(f, f"BOARD CARD {i + 1}", card_name) for i, f in enumerate(state.board)))
    lines.append("POT: " + c.value(state.pot, "POT", fmt_amount))
    lines.append("POT INCLUDES CURRENT BETS: " + ("Yes" if state.pot_includes_bets else "No"))
    lines.append("BLINDS: " + c.value(state.blinds, "BLINDS", lambda b: f"{fmt_amount(b[0])}/{fmt_amount(b[1])}"))
    lines.append("HERO STACK: " + c.value(hero.stack, "HERO STACK", fmt_amount))
    lines.append("HERO BET: " + c.value(hero.bet, "HERO BET", fmt_amount))
    lines.append("ACTIVE PLAYERS: " + c.value(state.active_players(), "ACTIVE PLAYERS", str))

    folded = []
    n = 0
    for p in state.opponents:
        if p.in_hand.known and p.in_hand.value is False:
            folded.append(p)
            continue
        n += 1
        tag = f"OPPONENT {n}"
        lines.append(f"{tag}:")
        lines.append("  Position: " + c.value(p.position, f"{tag} POSITION", position_label))
        lines.append("  Stack: " + c.value(p.stack, f"{tag} STACK", fmt_amount))
        lines.append("  Bet: " + c.value(p.bet, f"{tag} BET", fmt_amount))
        lines.append("  Last action: " + c.value(p.last_action, f"{tag} LAST ACTION", lambda a: a.describe()))
        if p.in_hand.known:
            status = "All-in" if p.stack.known and float(p.stack.value) == 0 else "In hand"
        else:
            status = UNKNOWN
            c.unknown.append(f"{tag} STATUS")
        lines.append("  Status: " + status)
    if folded:
        pos = [position_label(p.position.value) for p in folded if p.position.known]
        extra = f" ({', '.join(pos)})" if pos and len(pos) == len(folded) else ""
        lines.append(f"FOLDED OPPONENTS: {len(folded)}{extra}")
    else:
        lines.append("FOLDED OPPONENTS: 0")

    lines.append("HERO TO ACT: " + c.value(state.hero_to_act, "HERO TO ACT", lambda v: "Yes" if v else "No"))
    if state.hero_to_act.known and state.hero_to_act.value is False:
        lines.append("AVAILABLE ACTIONS: None (not hero's turn)")
        lines.append("ACTION FACING HERO: Not hero's turn")
    else:
        lines.append("AVAILABLE ACTIONS: " + c.value(state.available_actions, "AVAILABLE ACTIONS",
                                                     lambda v: describe_actions(v) if v else UNKNOWN))
        if state.available_actions.known and state.available_actions.value:
            lines.append("ACTION FACING HERO: " + facing_summary(state.available_actions.value))
        elif state.to_call.known:
            tc = float(state.to_call.value)
            lines.append("ACTION FACING HERO: " + (f"Call {fmt_amount(tc)}, raise, or fold" if tc > 0 else "Check or bet"))
        else:
            c.unknown.append("ACTION FACING HERO")
            lines.append("ACTION FACING HERO: " + UNKNOWN)
    lines.append("TO CALL: " + c.value(state.to_call, "TO CALL", fmt_amount))

    math_lines = render_math(state.computed)
    if math_lines:
        lines.append(MATH_HEADER + ":")
        lines.extend("  " + m for m in math_lines)
    lines.append("UNKNOWN FIELDS: " + (", ".join(c.unknown) if c.unknown else "None"))
    return "\n".join(lines)


def render_math(computed: Dict) -> List[str]:
    if not computed:
        return []
    out = []
    if computed.get("hand"):
        out.append(f"Hero hand: {computed['hand']}")
    if computed.get("draws"):
        out.append("Draws: " + ", ".join(computed["draws"]))
    po = computed.get("pot_odds")
    if po:
        out.append(f"Pot odds: call {fmt_amount(po['to_call'])} to win {fmt_amount(po['pot'])}, "
                   f"needs {fmt_pct(po['required_equity'])} equity")
    for eq in computed.get("equity", []):
        opp = eq["opponents"]
        out.append(f"Equity vs {eq['label']} ({opp} opponent{'s' if opp != 1 else ''}): "
                   f"{fmt_pct(eq['equity'])} (+/- {fmt_pct(eq['stderr'])})")
    verdict = computed.get("verdict")
    if computed.get("ev_call") is not None:
        ev = computed["ev_call"]
        tail = "" if verdict and verdict.get("exact") else ", ignoring future betting"
        out.append(f"EV of calling{tail}: {'+' if ev >= 0 else '-'}{fmt_amount(round(abs(ev), 1))}")
    if verdict:
        action = verdict["action"]
        if action == "close":
            out.append("Call or fold: too close to call, the difference is within the estimate's error")
        elif verdict.get("exact"):
            out.append(f"Call or fold: {action} is the higher-EV choice against {verdict['range']} "
                       "(exact, calling ends the betting)")
        else:
            out.append(f"Call or fold: {action} by pot odds only (future betting not modelled)")
    imp = computed.get("improve")
    if imp:
        parts = []
        if imp.get("next_card") is not None:
            parts.append(f"next card {fmt_pct(imp['next_card'])} ({imp['outs']} outs)")
        if imp.get("by_river") is not None:
            parts.append(f"by the river {fmt_pct(imp['by_river'])}")
        if parts:
            out.append("Chance to improve: " + ", ".join(parts))
    if computed.get("spr") is not None:
        out.append(f"Stack to pot ratio: {computed['spr']:.1f}")
    return out


# ------------------------------------------------------------------ parse
_LINE = re.compile(r"^([A-Z][A-Z0-9 '()+/,.-]*?):\s?(.*)$")
_SUB = re.compile(r"^  ([A-Za-z][^:]*?):\s?(.*)$")


def parse_text(text: str) -> Dict[str, object]:
    """Inverse of render_text, for tools and tests: {'POT': '120', 'OPPONENT 1': {...}, ...}."""
    out: Dict[str, object] = {}
    block: Optional[Dict[str, str]] = None
    for raw in text.splitlines():
        if not raw.strip():
            continue
        if raw.startswith("  "):
            m = _SUB.match(raw)
            if not m or block is None:
                raise ValueError(f"Malformed line: {raw!r}")
            block[m.group(1)] = m.group(2)
            continue
        m = _LINE.match(raw)
        if not m:
            raise ValueError(f"Malformed line: {raw!r}")
        key, value = m.group(1), m.group(2)
        if value == "":
            block = {}
            out[key] = block
        else:
            out[key] = value
            block = None
    return out
