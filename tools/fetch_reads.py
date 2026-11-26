"""Fetch the folders that "Save last reads" sent to the private reads repository (Settings,
Send reads in the app) and replay one through the current reader.

    python tools/fetch_reads.py                       # the folders sent, newest first, with the notes
    python tools/fetch_reads.py --replay              # replay the newest
    python tools/fetch_reads.py --replay 2026-11-26_23-20-01

The repository: --repo, else POKERSCRIBE_READS_REPO, else kvnwg/pokerscribe-reads. In a Claude
Code cloud session, attach it first (add_repo) so git can read it. The copy is kept in
--dir (default ~/.cache/pokerscribe-reads) and only pulled on later runs.
"""
import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_REPO = "kvnwg/pokerscribe-reads"


def sync(repo: str, folder: str) -> None:
    if os.path.isdir(os.path.join(folder, ".git")):
        subprocess.run(["git", "-C", folder, "pull", "--ff-only", "--quiet"], check=True)
    else:
        os.makedirs(os.path.dirname(folder) or ".", exist_ok=True)
        subprocess.run(["git", "clone", "--quiet", f"https://github.com/{repo}.git", folder], check=True)


def sent_folders(folder: str):
    root = os.path.join(folder, "reads")
    if not os.path.isdir(root):
        return []
    return sorted((d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))), reverse=True)


def describe(path: str) -> str:
    pictures = sum(1 for f in os.listdir(path) if f.endswith(".png"))
    note = ""
    if os.path.exists(os.path.join(path, "note.txt")):
        with open(os.path.join(path, "note.txt"), encoding="utf-8") as fh:
            note = fh.read().strip()
    about = {}
    if os.path.exists(os.path.join(path, "about.json")):
        with open(os.path.join(path, "about.json"), encoding="utf-8") as fh:
            about = json.load(fh)
    made_by = about.get("commit", "")[:7] or about.get("build", "") or about.get("version", "?")
    return f"{pictures} pictures, made by {made_by}" + (f'\n      note: "{note}"' if note else "")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=os.environ.get("POKERSCRIBE_READS_REPO", DEFAULT_REPO))
    ap.add_argument("--dir", default=os.path.expanduser("~/.cache/pokerscribe-reads"))
    ap.add_argument("--replay", nargs="?", const="newest", help="replay this folder (default: the newest)")
    ap.add_argument("--no-pull", action="store_true", help="use the copy already fetched")
    args = ap.parse_args()

    if not args.no_pull:
        try:
            sync(args.repo, args.dir)
        except subprocess.CalledProcessError:
            sys.exit(f"Couldn't fetch {args.repo}. In a cloud session, attach it first (add_repo).")
    names = sent_folders(args.dir)
    if not names:
        sys.exit(f"Nothing sent to {args.repo} yet.")
    if args.replay is None:
        for name in names:
            print(f"  {name}: {describe(os.path.join(args.dir, 'reads', name))}")
        return
    name = names[0] if args.replay == "newest" else args.replay
    path = os.path.join(args.dir, "reads", name)
    if not os.path.isdir(path):
        sys.exit(f"No folder {name}. Sent: {', '.join(names[:10])}")
    print(f"{name}: {describe(path)}\n")
    subprocess.run([sys.executable, os.path.join(HERE, "replay_reads.py"), path], check=False)


if __name__ == "__main__":
    main()
