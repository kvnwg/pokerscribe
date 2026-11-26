"""Send a "Save last reads" folder to a private GitHub repository, where Claude can fetch it.

Only once you have set it up (Settings, Send reads: a repository and a token) and only the
folder you just saved. The repository must be private: the pictures show other players' names.
Each folder becomes one commit, under reads/<date and time>/ on the repository's main branch.

Claude's side: tools/fetch_reads.py lists the folders sent and replays one."""
from __future__ import annotations

import base64
import json
import os
import re
import urllib.error
import urllib.request
from typing import Callable, Dict, List, Optional, Tuple

API = "https://api.github.com"
REPO_RE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")

# (method, path, JSON body or None) -> (HTTP status, JSON answer)
Http = Callable[[str, str, Optional[dict]], Tuple[int, dict]]

FIRST_README = """# PokerScribe saved reads

Folders sent by PokerScribe's "Save last reads", one per press, under reads/. Each holds the
pictures of the table box (001.png, ...), reads.jsonl (what was read and the instruction shown),
note.txt (what you said went wrong) and about.json (the app version).

Keep this repository private: the pictures show other players' names.
"""


class SendError(Exception):
    """Sending failed; the message says why in plain words."""


def github_http(token: str, timeout: float = 60) -> Http:
    def call(method: str, path: str, body: Optional[dict] = None) -> Tuple[int, dict]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(API + path, data=data, method=method, headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "PokerScribe",
        })
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                answer = json.loads(raw) if raw else {}
            except ValueError:
                answer = {"message": raw[:200].decode("utf-8", "replace")}
            return exc.code, answer if isinstance(answer, dict) else {}
        except (urllib.error.URLError, OSError) as exc:
            raise SendError(f"No connection to GitHub ({getattr(exc, 'reason', exc)}).") from exc
    return call


def _fail(status: int, answer: dict, what: str) -> SendError:
    msg = answer.get("message", "") if isinstance(answer, dict) else ""
    if status == 401:
        return SendError("GitHub didn't accept the token (wrong or expired). Make a new one: Settings, Send reads.")
    if status == 403:
        return SendError("The token may not write to that repository. Give it Contents: Read and write.")
    return SendError(f"GitHub answered {status} while {what}{': ' + msg if msg else ''}.")


def check_repo(repo: str, http: Http) -> str:
    """The repository's main branch, after checking it can be used. Raises SendError."""
    repo = repo.strip()
    if not REPO_RE.fullmatch(repo):
        raise SendError(f'"{repo}" is not a repository name. Write it as owner/name, e.g. you/pokerscribe-reads.')
    status, info = http("GET", f"/repos/{repo}", None)
    if status == 404:
        raise SendError(f"Can't see {repo}. Check the name, and that the token is for that repository.")
    if status != 200:
        raise _fail(status, info, "looking at the repository")
    if not info.get("private", False):
        raise SendError(f"{repo} is public. The pictures show other players' names, so reads only go to a "
                        "private repository.")
    perms = info.get("permissions")
    if isinstance(perms, dict) and not perms.get("push", True):
        raise SendError("The token may read but not write that repository. Give it Contents: Read and write.")
    return info.get("default_branch") or "main"


def _head(http: Http, repo: str, branch: str) -> Optional[str]:
    status, ref = http("GET", f"/repos/{repo}/git/ref/heads/{branch}", None)
    if status in (404, 409):  # no commits yet
        return None
    if status != 200:
        raise _fail(status, ref, "finding the branch")
    return ref["object"]["sha"]


def send_folder(folder: str, repo: str, token: str = "", http: Optional[Http] = None) -> str:
    """Upload every file in `folder` as one commit under reads/<folder name>/. Returns the
    folder's address on GitHub."""
    http = http or github_http(token)
    repo = repo.strip()
    branch = check_repo(repo, http)
    name = os.path.basename(os.path.normpath(folder)).replace(" ", "_")
    files = sorted(f for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f)))
    if not files:
        raise SendError("The folder is empty.")

    if _head(http, repo, branch) is None:
        # an empty repository: the git data calls refuse it, the contents call makes the first commit
        status, answer = http("PUT", f"/repos/{repo}/contents/README.md", {
            "message": "Start the saved reads",
            "content": base64.b64encode(FIRST_README.encode("utf-8")).decode("ascii"),
        })
        if status not in (200, 201):
            raise _fail(status, answer, "starting the empty repository")

    entries: List[Dict[str, str]] = []
    for f in files:
        with open(os.path.join(folder, f), "rb") as fh:
            content = base64.b64encode(fh.read()).decode("ascii")
        status, blob = http("POST", f"/repos/{repo}/git/blobs", {"content": content, "encoding": "base64"})
        if status != 201:
            raise _fail(status, blob, f"sending {f}")
        entries.append({"path": f"reads/{name}/{f}", "mode": "100644", "type": "blob", "sha": blob["sha"]})

    for _ in range(3):  # the branch moved meanwhile (another send): build on the new head
        parent = _head(http, repo, branch)
        if parent is None:
            raise SendError("The repository's branch disappeared while sending.")
        status, commit = http("GET", f"/repos/{repo}/git/commits/{parent}", None)
        if status != 200:
            raise _fail(status, commit, "reading the last commit")
        status, tree = http("POST", f"/repos/{repo}/git/trees",
                            {"base_tree": commit["tree"]["sha"], "tree": entries})
        if status != 201:
            raise _fail(status, tree, "building the folder")
        status, new = http("POST", f"/repos/{repo}/git/commits",
                           {"message": f"Saved reads {name}", "tree": tree["sha"], "parents": [parent]})
        if status != 201:
            raise _fail(status, new, "making the commit")
        status, answer = http("PATCH", f"/repos/{repo}/git/refs/heads/{branch}", {"sha": new["sha"]})
        if status == 200:
            return f"https://github.com/{repo}/tree/{branch}/reads/{name}"
        if status != 422:
            raise _fail(status, answer, "moving the branch")
    raise SendError("The repository kept changing while sending. Press Save last reads again.")
