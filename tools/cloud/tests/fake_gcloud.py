#!/usr/bin/env python3
"""A stand-in for the gcloud CLI's storage commands, for the tests: gs://<bucket>/<path> is
the file $FAKE_GCS_ROOT/<bucket>/<path>. It answers like gcloud does: the same output formats
for ``ls -l``, "-" for stdin and stdout, and the same "matched no objects" errors.

Implemented: storage cp SRC DST, storage cat URL..., storage ls [-l] URL, storage rm URL...
Every call is appended to $FAKE_GCS_ROOT/calls.log.
"""
import os
import shutil
import sys
import time

ROOT = os.environ.get("FAKE_GCS_ROOT")


def path_of(url):
    assert url.startswith("gs://"), url
    return os.path.join(ROOT, *url[len("gs://"):].split("/"))


def no_match(url):
    sys.stderr.write(f"ERROR: (gcloud.storage) One or more URLs matched no objects: {url}\n")
    return 1


def cp(src, dst):
    if dst.startswith("gs://"):
        target = path_of(dst)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        tmp = target + ".fake-upload"
        if src == "-":
            with open(tmp, "wb") as f:
                f.write(sys.stdin.buffer.read())
        else:
            if not os.path.isfile(src):
                sys.stderr.write(f"ERROR: (gcloud.storage.cp) not found: {src}\n")
                return 1
            shutil.copyfile(src, tmp)
        os.replace(tmp, target)
        return 0
    source = path_of(src)
    if not os.path.isfile(source):
        return no_match(src)
    if dst == "-":
        with open(source, "rb") as f:
            sys.stdout.buffer.write(f.read())
        return 0
    if os.path.isdir(dst):
        dst = os.path.join(dst, os.path.basename(source))
    shutil.copyfile(source, dst)
    return 0


def ls(urls, long):
    total = n = 0
    out = []
    for url in urls:
        p = path_of(url.rstrip("/"))
        if os.path.isfile(p) and not url.endswith("/"):
            entries = [(url, p)]
        elif os.path.isdir(p):
            base = url if url.endswith("/") else url + "/"
            entries = [(base + e + ("/" if os.path.isdir(os.path.join(p, e)) else ""),
                        os.path.join(p, e)) for e in sorted(os.listdir(p))
                       if not e.endswith(".fake-upload")]
        else:
            entries = []
        if not entries:
            return no_match(url)
        for u, fp in entries:
            if u.endswith("/"):
                out.append(f"{'':>32}{u}" if long else u)
            elif long:
                size = os.path.getsize(fp)
                stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(os.path.getmtime(fp)))
                out.append(f"{size:>12}  {stamp}  {u}")
                total += size
                n += 1
            else:
                out.append(u)
    if long:
        out.append(f"TOTAL: {n} objects, {total} bytes")
    print("\n".join(out))
    return 0


def main(argv):
    with open(os.path.join(ROOT, "calls.log"), "a") as f:
        f.write(" ".join(argv) + "\n")
    if not argv or argv[0] != "storage":
        sys.stderr.write(f"fake gcloud: not implemented: {' '.join(argv)}\n")
        return 2
    cmd, rest = argv[1], [a for a in argv[2:]]
    if cmd == "cp":
        args = [a for a in rest if a == "-" or not a.startswith("-")]
        return cp(args[0], args[1])
    if cmd == "cat":
        for url in rest:
            p = path_of(url)
            if not os.path.isfile(p):
                return no_match(url)
            with open(p, "rb") as f:
                sys.stdout.buffer.write(f.read())
        return 0
    if cmd == "ls":
        long = "-l" in rest
        return ls([a for a in rest if not a.startswith("-")], long)
    if cmd == "rm":
        for url in rest:
            p = path_of(url)
            if not os.path.isfile(p):
                return no_match(url)
            os.unlink(p)
        return 0
    sys.stderr.write(f"fake gcloud: not implemented: storage {cmd}\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
