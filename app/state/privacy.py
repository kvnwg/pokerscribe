"""Last line of defence before anything leaves the machine.

The outgoing text must have exactly the structure render_text() produces and use
only its vocabulary. Anything else (a player name, a site name read from the felt,
a URL, a file path, an e-mail address) makes the check fail and nothing is sent.
"""
from __future__ import annotations

import re
from typing import List

from .positions import POSITION_LABELS
from .text_format import MATH_HEADER, RANK_NAMES, RANK_PLURALS, STREET_NAMES, SUIT_NAMES

MAX_CHARS = 6000

TOP_KEYS = {
    "GAME", "HERO CARDS", "HERO POSITION", "STREET", "BOARD", "POT", "POT INCLUDES CURRENT BETS", "BLINDS",
    "HERO STACK", "HERO BET", "ACTIVE PLAYERS", "FOLDED OPPONENTS", "HERO TO ACT", "AVAILABLE ACTIONS",
    "ACTION FACING HERO", "TO CALL", "UNKNOWN FIELDS",
}
OPPONENT_SUBKEYS = {"Position", "Stack", "Bet", "Last action", "Status"}

_PHRASES = [
    "Texas Hold'em", "UNKNOWN", "None preflop", "Yes No", "In hand All-in", "not hero's turn Not hero's turn",
    "Fold Check Call Bet Raise to All-in fold check call bet raise all-in or",
    "HERO CARD STATUS LAST ACTION BOARD CARD OPPONENT POSITION STACK BET",
    "Hero hand Draws Pot odds call to win needs equity Equity vs random hands opponent opponents",
    "EV of calling ignoring future betting Chance to improve next card outs by the river Stack to pot ratio",
    "Any two cards Loose Medium Tight Very tight range top custom Custom",
    "High card Pair of Two pair and Three of a Kind Straight Flush Full House Four Royal high full over",
    "flush draw open-ended straight gutshot backdoor",
    "Pocket suited offsuit of starting hands",
    "Call or fold is the higher-EV choice against exact calling ends the betting",
    "too close to call the difference within estimate's error by pot odds only future not modelled",
    MATH_HEADER,
] + list(TOP_KEYS) + list(OPPONENT_SUBKEYS)
VOCAB = set()
for _p in _PHRASES + list(RANK_NAMES.values()) + list(RANK_PLURALS.values()) + list(SUIT_NAMES.values()) \
        + list(STREET_NAMES.values()) + list(POSITION_LABELS.values()):
    VOCAB.update(w.lower() for w in re.findall(r"[A-Za-z][A-Za-z'+-]*", _p))

_WORD = re.compile(r"[A-Za-z][A-Za-z'+-]*")
_TOP = re.compile(r"^([A-Z][A-Z ]*[A-Z]): (.+)$")
_HEADER = re.compile(r"^(OPPONENT \d{1,2}|" + re.escape(MATH_HEADER) + r"):$")
_SUB = re.compile(r"^  ([A-Z][A-Za-z ,()+/0-9%-]*?): (.+)$")
_SUSPICIOUS = re.compile(
    r"(https?:|www\.|\.[a-z]{2,6}\b(?<!\.\d)|@|\\|/(users|home|var|tmp|applications|library)\b|[a-z]:\\|\.exe\b|\.app\b)",
    re.I,
)
_ALLOWED_CHARS = re.compile(r"^[A-Za-z0-9 ,.:;'()+/%\-]*$")


class PrivacyError(ValueError):
    pass


def check_outgoing_text(text: str) -> List[str]:
    """Return a list of problems; an empty list means the text is safe to send."""
    problems: List[str] = []
    if not text or not text.strip():
        return ["The text is empty."]
    if len(text) > MAX_CHARS:
        problems.append("The text is unexpectedly long.")
    in_block = False
    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        if not _ALLOWED_CHARS.match(line):
            problems.append(f"Line {n} contains unexpected characters.")
            continue
        if _SUSPICIOUS.search(line.replace("+/- ", "")):
            problems.append(f"Line {n} looks like it contains an address, path or file name.")
        if _HEADER.match(line):
            in_block = True
        elif line.startswith("  "):
            m = _SUB.match(line)
            if not in_block or not m:
                problems.append(f"Line {n} is not in the expected format.")
        else:
            in_block = False
            m = _TOP.match(line)
            if not m or m.group(1) not in TOP_KEYS:
                problems.append(f"Line {n} is not in the expected format.")
        for word in _WORD.findall(line):
            if word.lower() not in VOCAB:
                problems.append(f"Line {n} contains a word that is not part of the game description: {word!r}")
    return problems


def assert_safe(text: str) -> None:
    problems = check_outgoing_text(text)
    if problems:
        raise PrivacyError("Blocked before sending: " + "; ".join(problems[:3]))
