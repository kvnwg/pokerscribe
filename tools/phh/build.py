"""Build decision-point datasets from the PHH dataset.

    python -m tools.phh.build --root /path/to/phh-dataset --out /path/to/output \
        [--handhq-share 0.01] [--workers 2]

Writes Parquet files (one row per decision) and stats.json. The Pluribus hands go to their
own folder and are never mixed into the other splits. HandHQ (21.6 million hands) is
sampled by default; --handhq-share 1 processes all of it (about a day of CPU)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import shutil
import time
import warnings
from collections import Counter, defaultdict
from multiprocessing import Pool
from typing import Any, Dict, List, Tuple

import pyarrow as pa
import pyarrow.parquet as pq

from .reader import iter_file, iter_paths
from .replay import hand_decisions, leak_check
from .sources import id_key, source_of

SCHEMA = pa.schema([
    ("hand_uid", pa.string()), ("source", pa.string()), ("venue", pa.string()), ("stakes", pa.string()),
    ("session", pa.string()), ("split", pa.string()), ("file", pa.string()), ("hand_index", pa.int32()),
    ("n_players", pa.int8()), ("n_active", pa.int8()), ("street", pa.string()), ("position", pa.string()),
    ("seat", pa.int8()), ("actor_id", pa.string()), ("actor_is_pluribus", pa.bool_()),
    ("opponents", pa.list_(pa.string())), ("hole_cards", pa.string()), ("board", pa.string()),
    ("bb", pa.float64()), ("pot_bb", pa.float64()), ("to_call_bb", pa.float64()), ("stack_bb", pa.float64()),
    ("bet_bb", pa.float64()), ("eff_stack_bb", pa.float64()), ("history", pa.list_(pa.string())),
    ("can_fold", pa.bool_()), ("can_check", pa.bool_()), ("can_call", pa.bool_()), ("can_raise", pa.bool_()),
    ("min_raise_to_bb", pa.float64()), ("max_raise_to_bb", pa.float64()),
    ("action", pa.string()), ("amount_to_bb", pa.float64()), ("amount_added_bb", pa.float64()),
    ("size_of_pot", pa.float64()), ("all_in", pa.bool_()), ("label_source", pa.string()),
])


def select_files(root: str, handhq_share: float, seed: int = 7) -> List[str]:
    """Every Pluribus, WSOP and historical file; a share of the HandHQ files, spread evenly
    over every site and stake so each one is represented."""
    by_folder: Dict[str, List[str]] = defaultdict(list)
    chosen: List[str] = []
    for path in iter_paths(os.path.join(root, "data")):
        rel = os.path.relpath(path, root)
        if source_of(rel) == "handhq":
            by_folder[rel.split(os.sep)[2]].append(path)
        else:
            chosen.append(path)
    rng = random.Random(seed)
    for folder, files in sorted(by_folder.items()):
        files.sort()
        if handhq_share >= 1:
            chosen.extend(files)
            continue
        k = max(2, round(handhq_share * len(files)))
        chosen.extend(sorted(rng.sample(files, min(k, len(files)))))
    return chosen


def _process(args: Tuple[str, str, str, int]) -> Dict[str, Any]:
    path, root, shard_dir, leak_every = args
    warnings.filterwarnings("ignore")
    stats: Counter = Counter()
    errors: Dict[str, List[str]] = defaultdict(list)
    keys: List[Tuple[str, Any, int, str]] = []
    rows: List[Dict[str, Any]] = []
    for n, raw in enumerate(iter_file(path, root)):
        src = source_of(raw.path)
        stats[f"{src}|hands_read"] += 1
        if raw.data is None:
            reason = (raw.error or "unknown").split(":")[0]
            stats[f"{src}|unparseable|{reason}"] += 1
            if len(errors[reason]) < 5:
                errors[reason].append(f"{raw.path}#{raw.index}: {raw.error}")
            continue
        stats[f"{src}|variant|{raw.data.get('variant')}"] += 1
        recs, info = hand_decisions(raw)
        stats[f"{src}|status|{info['status']}"] += 1
        if info["status"] not in ("ok", "not_nlhe"):
            reason = info["status"]
            if len(errors[reason]) < 8:
                errors[reason].append(f"{raw.path}#{raw.index}: {info.get('error')}")
            continue
        if info["status"] != "ok":
            continue
        stats[f"{src}|players|{info['n_players']}"] += 1
        keys.append((info["hand_uid"], id_key(src, raw.data), info.get("known_hole_cards", 0), src))
        if leak_every and n % leak_every == 0 and recs:
            checked, bad = leak_check(raw, recs)
            stats[f"{src}|leak_checked"] += checked
            stats[f"{src}|leak_mismatch"] += bad
        for r in recs:
            stats[f"{src}|decisions|{r['street']}|{r['action']}"] += 1
            stats[f"{src}|cards_known|{r['hole_cards'] is not None}"] += 1
            if r["action"] == "fold" and r["can_check"]:
                stats[f"{src}|free_fold"] += 1
        rows.extend(recs)
    shard = None
    if rows:
        shard = os.path.join(shard_dir, hashlib.sha1(path.encode()).hexdigest()[:16] + ".parquet")
        pq.write_table(pa.Table.from_pylist(rows, schema=SCHEMA), shard, compression="zstd")
    return {"path": path, "stats": stats, "errors": dict(errors), "keys": keys, "shard": shard}


def build(root: str, out: str, handhq_share: float, workers: int, leak_every: int) -> Dict[str, Any]:
    t0 = time.time()
    shard_dir = os.path.join(out, "_shards")
    os.makedirs(shard_dir, exist_ok=True)
    files = select_files(root, handhq_share)
    stats: Counter = Counter()
    errors: Dict[str, List[str]] = defaultdict(list)
    seen: Dict[str, str] = {}  # hand_uid -> first shard
    by_id: Dict[Any, Tuple[int, str]] = {}  # site hand number -> (known cards, hand_uid kept)
    drop: set = set()
    shards: List[str] = []
    jobs = [(p, root, shard_dir, leak_every) for p in files]
    with Pool(workers) as pool:
        for i, res in enumerate(pool.imap_unordered(_process, jobs, chunksize=1)):
            stats.update(res["stats"])
            for k, v in res["errors"].items():
                errors[k].extend(v[: max(0, 8 - len(errors[k]))])
            if res["shard"]:
                shards.append(res["shard"])
            for uid, ikey, known, src in res["keys"]:
                if uid in seen:
                    stats[f"{src}|duplicate|same_content"] += 1
                    drop.add(("dup", uid))  # marker: the later copies of this content are dropped below
                    continue
                seen[uid] = res["shard"]
                if ikey is not None:
                    if ikey in by_id:
                        stats[f"{src}|duplicate|same_hand_number"] += 1
                        kept_known, kept_uid = by_id[ikey]
                        if known > kept_known:
                            drop.add(kept_uid)
                            by_id[ikey] = (known, uid)
                        else:
                            drop.add(uid)
                    else:
                        by_id[ikey] = (known, uid)
            if (i + 1) % 50 == 0:
                print(f"  {i + 1}/{len(files)} files, {time.time() - t0:.0f}s", flush=True)
    stats_out = _consolidate(out, shards, {u for u in drop if isinstance(u, str)}, stats)
    shutil.rmtree(shard_dir, ignore_errors=True)  # per-file pieces, merged above
    summary = {
        "root": root, "handhq_share": handhq_share, "files_processed": len(files),
        "seconds": round(time.time() - t0, 1), "stats": dict(sorted(stats.items())),
        "errors": dict(errors), "outputs": stats_out,
    }
    with open(os.path.join(out, "stats.json"), "w") as fh:
        json.dump(summary, fh, indent=1, default=str)
    return summary


def _consolidate(out: str, shards: List[str], drop: set, stats: Counter) -> Dict[str, int]:
    """One file per source and split, without dropped duplicates. Exact duplicate copies are
    removed by keeping the first row group of each hand_uid."""
    writers: Dict[str, pq.ParquetWriter] = {}
    counts: Counter = Counter()
    kept_uids: set = set()
    for shard in sorted(shards):
        table = pq.read_table(shard)
        rows = table.to_pylist()
        keep = []
        uids_here = set()
        for r in rows:
            uid = r["hand_uid"]
            if uid in drop or (uid in kept_uids and uid not in uids_here):
                continue
            uids_here.add(uid)
            keep.append(r)
        kept_uids |= uids_here
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for r in keep:
            src = r["source"]
            name = ("pluribus/decisions" if src == "pluribus" else
                    f"handhq/{r['split']}" if src == "handhq" else f"evaluation/{src}")
            groups[name].append(r)
        for name, rs in groups.items():
            path = os.path.join(out, name + ".parquet")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if name not in writers:
                writers[name] = pq.ParquetWriter(path, SCHEMA, compression="zstd")
            writers[name].write_table(pa.Table.from_pylist(rs, schema=SCHEMA))
            counts[name] += len(rs)
    for w in writers.values():
        w.close()
    stats["hands_kept"] = len(kept_uids)
    return dict(counts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True, help="folder of the phh-dataset checkout (holds data/)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--handhq-share", type=float, default=0.01)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2)))
    ap.add_argument("--leak-every", type=int, default=25, help="leak-check every n-th hand of each file (0 = off)")
    a = ap.parse_args()
    s = build(a.root, a.out, a.handhq_share, a.workers, a.leak_every)
    print(json.dumps(s["outputs"], indent=1), f"{s['seconds']}s")


if __name__ == "__main__":
    main()
