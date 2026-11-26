"""Parse chip and money amounts as they appear on poker tables.

Handles "1,250", "1 250", "$12.50", "12,50" (decimal comma), "1.5K", "2M",
"45.5 BB", and the common OCR slips O->0, l/I->1 inside numbers.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Tuple

CURRENCY = "$€£¥₹"


@dataclass(frozen=True)
class Amount:
    value: float
    unit: str  # "chips" (chips or money) or "bb"
    raw: str
    corrected: bool = False  # OCR characters were repaired

    @property
    def confidence_factor(self) -> float:
        return 0.85 if self.corrected else 1.0


_NUM = r"\d{1,3}(?:[,\u00a0\u202f]\d{3})+(?:\.\d+)?|\d{1,3}(?:\.\d{3})+,\d+|\d+(?:[.,]\d+)?"
AMOUNT_RE = re.compile(
    rf"(?P<cur>[{CURRENCY}])?\s*(?P<num>{_NUM})(?P<suf>[kKmM](?![a-zA-Z]))?\s*(?P<bb>[bB][bB](?![a-zA-Z]))?(?![\d/:])"
)


def _repair(token: str) -> Tuple[str, bool]:
    """Fix letters that OCR often confuses with digits, only inside number-like tokens
    (what follows a currency sign: "pot:$1o" is $10)."""
    head, cur, tail = "", "", token
    m = re.search(rf"[{CURRENCY}]", token)
    if m:
        head, cur, tail = token[: m.start()], m.group(), token[m.end():]
    digits = sum(ch.isdigit() for ch in tail)
    if digits == 0 or digits < len(tail) * 0.5:
        return token, False
    fixed = head + cur + tail.translate(str.maketrans({"O": "0", "o": "0", "D": "0", "l": "1", "I": "1", "i": "1", "|": "1"}))
    return fixed, fixed != token


def _to_number(num: str) -> Optional[float]:
    num = num.replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    if "," in num and "." in num:
        if num.rfind(",") > num.rfind("."):  # 1.234,56
            num = num.replace(".", "").replace(",", ".")
        else:  # 1,234.56
            num = num.replace(",", "")
    elif "," in num:
        head, _, tail = num.rpartition(",")
        if len(tail) == 3 and re.fullmatch(r"\d{1,3}(,\d{3})*", num):
            num = num.replace(",", "")  # thousands
        else:
            num = head.replace(",", "") + "." + tail  # decimal comma
    try:
        return float(num)
    except ValueError:
        return None


def find_amounts(text: str) -> List[Tuple[Amount, int, int]]:
    """All amounts in `text` with their (start, end) positions."""
    text = unicodedata.normalize("NFKC", text)  # full-width digits ("６") from some OCR reads
    repaired_parts = []
    corrected = False
    for tok in re.split(r"(\s+)", text):
        fixed, changed = _repair(tok)
        corrected |= changed
        repaired_parts.append(fixed)
    t = "".join(repaired_parts)
    out = []
    for m in AMOUNT_RE.finditer(t):
        # skip fractions such as blinds "5/10" or "1/2 pot", and clock times "12:30"
        i = m.start("num")
        if i >= 2 and t[i - 1] in "/:" and t[i - 2].isdigit():
            continue
        value = _to_number(m.group("num"))
        if value is None:
            continue
        suf = (m.group("suf") or "").lower()
        if suf == "k":
            value *= 1_000
        elif suf == "m":
            value *= 1_000_000
        unit = "bb" if m.group("bb") else "chips"
        out.append((Amount(round(value, 4), unit, m.group(0).strip(), corrected), m.start(), m.end()))
    return out


def parse_amount(text: str) -> Optional[Amount]:
    """The amount when `text` is essentially just an amount (e.g. a stack label)."""
    stripped = text.strip()
    found = find_amounts(stripped)
    if len(found) != 1:
        return None
    amount, start, end = found[0]
    rest = (stripped[:start] + stripped[end:]).strip(" :.,-")
    if rest and not re.fullmatch(r"(?i)(bb|chips?)", rest):
        return None
    return amount


def first_amount(text: str) -> Optional[Amount]:
    found = find_amounts(text)
    return found[0][0] if found else None


BLINDS_RE = re.compile(
    rf"(?P<sb>[{CURRENCY}]?\d[\d.,]*\s*[kK]?)\s*/\s*(?P<bb>[{CURRENCY}]?\d[\d.,]*\s*[kK]?)(?:\s*/\s*[{CURRENCY}]?\d[\d.,]*)?"
)


BLINDS_LABEL_RE = re.compile(rf"(?i)(blind|stake|\bnl\b|\bpl\b|nlh|plo|hold.?em|limit|ante|[{CURRENCY}])")
# words that make "3/5" a count rather than the blinds: "Seat 3/5", "Hand #25/50", "Level 2/10"
_NOT_BLINDS_BEFORE = re.compile(r"(?i)(seat|seats|player|players|table|hand|level|lvl|game|round|page|#)\s*[:#.]?\s*$")


def has_blinds_label(text: str) -> bool:
    """The text says what the numbers are ("Blinds", "NL Hold'em", "$", ...). A bare "11/26"
    is a date, a bare "3/5" a seat count: neither is taken as the blinds."""
    return BLINDS_LABEL_RE.search(text) is not None


def parse_blinds(text: str) -> Optional[Tuple[float, float]]:
    """'Blinds 5/10', 'NLH $0.05/$0.10', '25/50 ante 5' -> (sb, bb)."""
    if "pot" in text.lower():
        return None  # bet-sizing buttons such as "1/2 Pot"
    text = re.sub(r"(?<=/)\s*[sS](?=\d)", "$", text)  # "$1/s2": OCR read the second "$" as an s
    for m in BLINDS_RE.finditer(text):
        if _NOT_BLINDS_BEFORE.search(text[:m.start()]):
            continue
        sb, bb = first_amount(m.group("sb")), first_amount(m.group("bb"))
        if sb is None or bb is None or sb.value <= 0 or bb.value < sb.value or bb.value > 20 * sb.value:
            continue
        return sb.value, bb.value
    return None
