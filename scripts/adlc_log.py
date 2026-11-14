#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pymongo>=4.7", "certifi"]
# ///
"""Shared ADLC log: sandbox db `adlc`, collection `log`. Convention: docs/adlc/shared-log.md.

  adlc_log.py add --item ID --event EVENT --summary TEXT [--phase P] [--evidence T] [--sha S] [--files F ...]
  adlc_log.py tail [-n N] [--item ID]
  adlc_log.py check            # connectivity + write permission
  adlc_log.py commit-hook      # called by .githooks/post-commit
Connection string: MONGODB_URI from the environment or ./.env. Author: ADLC_AUTHOR or git user.name.
"""
import argparse, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

PHASES = ["Spec", "Plan", "Build", "Verify", "Ship"]
EVENTS = ["task_start", "task_done", "decision", "blocker", "handoff", "test_run", "commit", "question"]
TOOLS = ["claude-code", "cursor", "git", "human"]
ROOT = Path(__file__).resolve().parent.parent


def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def uri():
    v = os.environ.get("MONGODB_URI")
    env = ROOT / ".env"
    if not v and env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("MONGODB_URI="):
                v = line.split("=", 1)[1].strip().strip("\"'")
    if not v:
        sys.exit("adlc_log: MONGODB_URI not set (env or .env)")
    return v


def coll():
    import certifi
    from pymongo import MongoClient
    c = MongoClient(uri(), tlsCAFile=certifi.where(), serverSelectionTimeoutMS=8000)
    return c["adlc"]["log"]


def author():
    return (os.environ.get("ADLC_AUTHOR") or git("config", "user.name") or "unknown").lower()


def add(doc):
    doc = {k: v for k, v in doc.items() if v not in (None, [], "")}
    doc["ts"] = datetime.now(timezone.utc)
    doc.setdefault("author", author())
    return coll().insert_one(doc).inserted_id


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    s = p.add_subparsers(dest="cmd", required=True)
    a = s.add_parser("add")
    a.add_argument("--item", required=True)
    a.add_argument("--event", required=True, choices=EVENTS)
    a.add_argument("--summary", required=True)
    a.add_argument("--phase", choices=PHASES)
    a.add_argument("--tool", choices=TOOLS, default=os.environ.get("ADLC_TOOL", "claude-code"))
    a.add_argument("--actor", default="human")
    a.add_argument("--evidence")
    a.add_argument("--sha")
    a.add_argument("--files", nargs="*")
    t = s.add_parser("tail")
    t.add_argument("-n", type=int, default=10)
    t.add_argument("--item")
    s.add_parser("check")
    s.add_parser("commit-hook")
    x = p.parse_args()

    if x.cmd == "add":
        d = vars(x).copy(); d.pop("cmd")
        print("logged", add(d))
    elif x.cmd == "tail":
        q = {"item": x.item} if x.item else {}
        print("# adlc.log (latest first)")
        for r in coll().find(q).sort("ts", -1).limit(x.n):
            print(f"{r['ts']:%m-%d %H:%M} {r.get('author','?'):6} {r.get('item','?'):10} "
                  f"{r.get('event','?'):10} {r.get('summary','')[:110]}")
    elif x.cmd == "check":
        c = coll(); c.database.client.admin.command("ping")
        i = add({"item": "ADLC-CHECK", "event": "test_run", "tool": "human", "actor": "human",
                 "summary": "setup check", "phase": "Build"})
        c.delete_one({"_id": i})
        print("atlas ok; adlc.log writable")
    elif x.cmd == "commit-hook":
        sha = git("rev-parse", "HEAD")
        msg = git("log", "-1", "--format=%s")
        files = git("show", "--name-only", "--format=", "HEAD").splitlines()
        item = git("rev-parse", "--abbrev-ref", "HEAD")
        add({"item": item, "event": "commit", "tool": "git", "actor": "human", "phase": None,
             "summary": msg, "commit_sha": sha[:7], "files": files[:50]})


if __name__ == "__main__":
    main()
