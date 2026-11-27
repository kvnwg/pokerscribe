"""Save last reads, sent to a private GitHub repository for Claude (Kevin, 26 Nov: "when i click
save last reads ... it can auto come to u and u can analyze it"). A fake GitHub stands in for
the real one: nothing goes over the network."""
import base64
import json

import numpy as np
import pytest

from app.capture.history import ReadLog
from app.capture.send import SendError, check_repo, send_folder


class FakeGitHub:
    def __init__(self, private=True, empty=False, races=0, status=None):
        self.private, self.empty, self.races = private, empty, races
        self.status = status  # force this answer to the first call
        self.calls = []
        self.blobs = {}
        self.head = None if empty else "c0"
        self.commits = {"c0": {"tree": {"sha": "t0"}, "parents": []}}
        self.trees = {}

    def __call__(self, method, path, body):
        self.calls.append((method, path))
        if self.status is not None:
            return self.status, {"message": "nope"}
        if method == "GET" and path == "/repos/me/reads":
            return 200, {"private": self.private, "default_branch": "main", "permissions": {"push": True}}
        if path == "/repos/me/reads/git/ref/heads/main":
            if self.head is None:
                return 409, {"message": "Git Repository is empty."}
            return 200, {"object": {"sha": self.head}}
        if method == "PUT" and path == "/repos/me/reads/contents/README.md":
            self.head = "c0"
            return 201, {}
        if method == "POST" and path.endswith("/git/blobs"):
            if self.head is None:
                return 409, {"message": "Git Repository is empty."}
            sha = f"b{len(self.blobs)}"
            self.blobs[sha] = base64.b64decode(body["content"])
            return 201, {"sha": sha}
        if method == "GET" and "/git/commits/" in path:
            return 200, self.commits[path.rsplit("/", 1)[1]]
        if method == "POST" and path.endswith("/git/trees"):
            sha = f"t{len(self.trees) + 1}"
            self.trees[sha] = body
            return 201, {"sha": sha}
        if method == "POST" and path.endswith("/git/commits"):
            sha = f"c{len(self.commits)}"
            self.commits[sha] = {"tree": {"sha": body["tree"]}, "parents": body["parents"]}
            return 201, {"sha": sha}
        if method == "PATCH" and path == "/repos/me/reads/git/refs/heads/main":
            if self.races:
                self.races -= 1
                self.commits["other"] = {"tree": {"sha": "t0"}, "parents": [self.head]}
                self.head = "other"  # someone else moved the branch first
                return 422, {"message": "Update is not a fast forward"}
            assert self.commits[body["sha"]]["parents"] == [self.head]
            self.head = body["sha"]
            return 200, {}
        raise AssertionError(f"unexpected {method} {path}")


def saved(tmp_path, note="said re-raise, he only posted the big blind"):
    log = ReadLog(keep=5)
    for i in range(3):
        log.add(np.full((20, 30, 3), i * 50, dtype=np.uint8), {"state": {"pot": i}})
    folder = tmp_path / "2026-11-26 23-20-01"
    log.save(str(folder), note=note, about={"version": "test"})
    return folder


def test_the_saved_folder_goes_up_as_one_commit(tmp_path):
    gh = FakeGitHub()
    url = send_folder(str(saved(tmp_path)), "me/reads", http=gh)
    assert url == "https://github.com/me/reads/tree/main/reads/2026-11-26_23-20-01"
    tree = gh.trees[gh.commits[gh.head]["tree"]["sha"]]
    assert tree["base_tree"] == "t0"  # added to what is there, nothing removed
    paths = sorted(e["path"] for e in tree["tree"])
    assert paths == [f"reads/2026-11-26_23-20-01/{f}" for f in
                     ["001.png", "002.png", "003.png", "README.txt", "about.json", "note.txt", "reads.jsonl"]]
    by_path = {e["path"]: gh.blobs[e["sha"]] for e in tree["tree"]}
    assert by_path["reads/2026-11-26_23-20-01/note.txt"].decode().strip() == \
        "said re-raise, he only posted the big blind"
    lines = by_path["reads/2026-11-26_23-20-01/reads.jsonl"].decode().splitlines()
    assert [json.loads(x)["state"]["pot"] for x in lines] == [0, 1, 2]


def test_a_public_repository_is_refused(tmp_path):
    """The pictures show other players' names: never to a public repository."""
    gh = FakeGitHub(private=False)
    with pytest.raises(SendError, match="public"):
        send_folder(str(saved(tmp_path)), "me/reads", http=gh)
    assert not any(path.endswith("/git/blobs") for _, path in gh.calls)


def test_an_empty_new_repository_gets_its_first_commit(tmp_path):
    gh = FakeGitHub(empty=True)
    send_folder(str(saved(tmp_path)), "me/reads", http=gh)
    assert ("PUT", "/repos/me/reads/contents/README.md") in gh.calls
    assert gh.commits[gh.head]["parents"] == ["c0"]


def test_the_branch_moving_meanwhile_is_built_on(tmp_path):
    gh = FakeGitHub(races=1)
    send_folder(str(saved(tmp_path)), "me/reads", http=gh)
    assert gh.commits[gh.head]["parents"] == ["other"]


def test_plain_reasons_when_it_cannot_send(tmp_path):
    with pytest.raises(SendError, match="token"):
        check_repo("me/reads", FakeGitHub(status=401))
    with pytest.raises(SendError, match="Can't see"):
        check_repo("me/reads", FakeGitHub(status=404))
    with pytest.raises(SendError, match="owner/name"):
        check_repo("https://github.com/me/reads", FakeGitHub())


def test_the_reads_are_the_ones_from_when_the_button_was_pressed(tmp_path):
    """Watching goes on while the note is typed: the reads that went wrong must not scroll out."""
    log = ReadLog(keep=2)
    for i in range(2):
        log.add(np.zeros((10, 10, 3), dtype=np.uint8), {"state": {"pot": i}})
    items = log.snapshot()
    for i in range(2, 4):
        log.add(np.zeros((10, 10, 3), dtype=np.uint8), {"state": {"pot": i}})
    log.save(str(tmp_path / "r"), items=items, about={})
    lines = (tmp_path / "r" / "reads.jsonl").read_text().splitlines()
    assert [json.loads(x)["state"]["pot"] for x in lines] == [0, 1]
    assert not (tmp_path / "r" / "note.txt").exists()  # no note written: no file


def test_the_button_saves_with_the_note_and_sends(qapp, tmp_home, monkeypatch):
    """The whole press: the note asked for, the folder saved, sent in the background, and a
    plain answer shown."""
    from PySide6.QtWidgets import QInputDialog

    import app.ui.main_window as mw
    from app.config import Settings
    from app.ui.workers import wait_for_all

    sent = []
    monkeypatch.setenv("POKERSCRIBE_GITHUB_TOKEN", "test-token")
    monkeypatch.setattr(mw, "default_folder", lambda: str(tmp_home / "reads" / "2026-11-26 23-20-01"))
    monkeypatch.setattr(mw, "send_folder", lambda folder, repo, token: sent.append((folder, repo, token)) or "url")
    monkeypatch.setattr(mw.QDesktopServices, "openUrl", lambda url: True)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("he only posted the big blind", True))
    settings = Settings()
    settings.reads_repo = "me/reads"
    w = mw.MainWindow(settings)
    w.read_log.add(np.zeros((10, 10, 3), dtype=np.uint8), {"state": {"pot": 1}})
    w.save_reads()
    for _ in range(100):
        wait_for_all(50)
        qapp.processEvents()
        if "Sent" in w.simple.warning.text():
            break
    assert sent == [(str(tmp_home / "reads" / "2026-11-26 23-20-01"), "me/reads", "test-token")]
    assert (tmp_home / "reads" / "2026-11-26 23-20-01" / "note.txt").read_text().strip() == \
        "he only posted the big blind"
    assert "check my saved reads" in w.simple.warning.text()

    # Cancel on the note: nothing saved
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("", False))
    monkeypatch.setattr(mw, "default_folder", lambda: str(tmp_home / "reads" / "cancelled"))
    w.save_reads()
    assert not (tmp_home / "reads" / "cancelled").exists()
    w.close()
