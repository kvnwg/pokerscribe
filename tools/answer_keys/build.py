"""Turn the hand-written spots (spot_defs.py) into data/answer_keys/spots/*.json."""
from __future__ import annotations

import json
import os
from typing import Dict, List, Mapping

from .spots import (FORMAT, SPOTS_DIR, VERSION, SpotError, capped_sizes, class_weights, expand_range_text,
                    integer_amounts, validate_spot)

KEY_ORDER = ("format", "version", "id", "street", "title", "tags", "board", "pot", "stacks", "spr",
             "max_raises", "sizes", "river_sizes", "range_text", "ranges", "expected")


def build_spot(defn: Mapping) -> Dict:
    d = dict(defn)
    d["format"], d["version"] = FORMAT, VERSION
    d["stacks"] = [round(float(s), 2) for s in d["stacks"]]
    d["stacks"] = [int(s) if s == int(s) else s for s in d["stacks"]]
    d["spr"] = round(min(d["stacks"]) / d["pot"], 2)
    d["ranges"] = {p: expand_range_text(d["range_text"][p], d["board"]) for p in ("oop", "ip")}
    if not d.get("expected"):
        d.pop("expected", None)
    out = {k: d[k] for k in KEY_ORDER if k in d}
    extra = set(d) - set(out)
    if extra:
        raise SpotError(f"{d['id']}: unknown fields {sorted(extra)}")
    validate_spot(out)
    for p in ("oop", "ip"):
        class_weights(out["ranges"][p], out["board"])  # TexasSolver can take it exactly
    problems = capped_sizes(out) + integer_amounts(out)
    if problems:
        raise SpotError(f"{out['id']}: " + "; ".join(problems[:5]))
    return out


def write_spots(defs: List[Mapping], spots_dir: str = SPOTS_DIR) -> List[str]:
    os.makedirs(spots_dir, exist_ok=True)
    ids = [d["id"] for d in defs]
    if len(set(ids)) != len(ids):
        raise SpotError("Two spots share an id.")
    paths = []
    for defn in defs:
        spot = build_spot(defn)
        path = os.path.join(spots_dir, spot["id"] + ".json")
        with open(path, "w") as f:
            f.write(dumps_spot(spot))
        paths.append(path)
    return paths


def dumps_spot(spot: Mapping) -> str:
    """Readable JSON: one line per field, ranges one combo per line would be too long,
    so each range is a single line."""
    lines = ["{"]
    items = list(spot.items())
    for i, (k, v) in enumerate(items):
        comma = "," if i < len(items) - 1 else ""
        if k in ("ranges", "range_text", "sizes", "river_sizes"):
            inner = ",\n".join(f"    {json.dumps(p)}: {json.dumps(v[p])}" for p in v)
            lines.append(f"  {json.dumps(k)}: {{\n{inner}\n  }}{comma}")
        elif k == "expected":
            inner = ",\n".join("    " + json.dumps(c) for c in v)
            lines.append(f"  {json.dumps(k)}: [\n{inner}\n  ]{comma}")
        else:
            lines.append(f"  {json.dumps(k)}: {json.dumps(v)}{comma}")
    lines.append("}")
    return "\n".join(lines) + "\n"
