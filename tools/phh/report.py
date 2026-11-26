"""Write the dataset quality report (markdown) from a build's stats.json.

    python -m tools.phh.report --stats /path/to/output/stats.json --out docs/research/DATASET.md
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from typing import Any, Dict

SOURCES = ("pluribus", "handhq", "wsop", "historical")


def _by_source(stats: Dict[str, int]) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = defaultdict(dict)
    for k, v in stats.items():
        if "|" in k:
            src, rest = k.split("|", 1)
            out[src][rest] = v
    return out


def render(summary: Dict[str, Any]) -> str:
    st = _by_source(summary["stats"])
    lines = ["# PHH dataset: quality, coverage and limits", "",
             f"Built from `{summary['root']}` with HandHQ share {summary['handhq_share']} "
             f"({summary['files_processed']} files, {summary['seconds']} s).", "",
             "| Source | Hands read | Hold'em replayed | Other variants | Unreadable | Missing actions | Corrupt "
             "| Duplicates | Decisions | Own cards known | Leak checks (mismatches) |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for src in SOURCES:
        s = st.get(src, {})
        if not s:
            continue
        dec = sum(v for k, v in s.items() if k.startswith("decisions|"))
        known = s.get("cards_known|True", 0)
        unread = sum(v for k, v in s.items() if k.startswith("unparseable|"))
        dups = sum(v for k, v in s.items() if k.startswith("duplicate|"))
        lines.append(
            f"| {src} | {s.get('hands_read', 0):,} | {s.get('status|ok', 0):,} | {s.get('status|not_nlhe', 0):,} "
            f"| {unread:,} | {s.get('status|out_of_turn', 0):,} | {s.get('status|corrupt', 0):,} | {dups:,} "
            f"| {dec:,} | {(known / dec if dec else 0):.1%} | {s.get('leak_checked', 0):,} ({s.get('leak_mismatch', 0)}) |")
    lines += ["", "## Output files (decision rows)", ""]
    lines += [f"- `{name}.parquet`: {n:,}" for name, n in sorted(summary["outputs"].items())]
    lines += ["", "## Variants seen", ""]
    variants: Dict[str, int] = defaultdict(int)
    for src, s in st.items():
        for k, v in s.items():
            if k.startswith("variant|"):
                variants[k.split("|", 1)[1]] += v
    lines += [f"- {k}: {v:,}" for k, v in sorted(variants.items(), key=lambda kv: -kv[1])]
    lines += ["", "## Table sizes (Hold'em hands)", ""]
    for src in SOURCES:
        sizes = {int(k.split("|")[1]): v for k, v in st.get(src, {}).items() if k.startswith("players|")}
        if sizes:
            lines.append(f"- {src}: " + ", ".join(f"{n} players {v:,}" for n, v in sorted(sizes.items())))
    lines += ["", "## Actions by street", ""]
    for src in SOURCES:
        acts = {k.split("|", 1)[1]: v for k, v in st.get(src, {}).items() if k.startswith("decisions|")}
        if acts:
            lines.append(f"- {src}: " + ", ".join(f"{k.replace('|', ' ')} {v:,}" for k, v in sorted(acts.items())))
    if summary.get("errors"):
        lines += ["", "## Examples of dropped hands", ""]
        for reason, examples in summary["errors"].items():
            for e in examples[:3]:
                lines.append(f"- {reason}: `{e}`")
    lines += ["", "## Known limits", "",
              "- HandHQ logs stacks as infinite: stack, effective stack and stack-to-pot ratio are missing there.",
              "- HandHQ shows the acting player's cards mostly in hands that reached showdown (selection bias).",
              "- Labels are the observed actions (`label_source = observed`), never the best actions.",
              "- Splits keep whole session groups together (Pluribus: day folder; HandHQ: site, stake, day).",
              "- The ACPC logs are only on Zenodo and are not part of this build.", ""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stats", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    with open(a.stats) as fh:
        summary = json.load(fh)
    with open(a.out, "w") as fh:
        fh.write(render(summary))


if __name__ == "__main__":
    main()
