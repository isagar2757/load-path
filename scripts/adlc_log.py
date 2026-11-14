#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pymongo>=4.7", "certifi"]
# ///
"""Shared ADLC log: sandbox db `adlc`, collection `log`. Convention: docs/adlc/shared-log.md.

  adlc_log.py add --item ID --event EVENT --summary TEXT [--to WHO] [--phase P] [--evidence T] [--sha S] [--files F ...]
  adlc_log.py tail [-n N] [--item ID]
  adlc_log.py inbox [-n N]     # events addressed to me (--to), newest first
  adlc_log.py item-of BRANCH   # tracker ID from a branch name, e.g. feat/a0-setup-db -> A0
  adlc_log.py check            # connectivity + write permission
  adlc_log.py commit-hook      # called by .githooks/post-commit
Connection string: MONGODB_URI from the environment or ./.env. Author: ADLC_AUTHOR or git user.name.
"""
import argparse, os, re, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

PHASES = ["Spec", "Plan", "Build", "Verify", "Ship"]
EVENTS = ["task_start", "task_done", "decision", "blocker", "handoff", "test_run", "commit", "question",
          "review", "gate"]
TOOLS = ["claude-code", "cursor", "git", "human"]
PEOPLE = ["sagar", "arad"]
ROOT = Path(__file__).resolve().parent.parent
ITEM_RE = re.compile(r"^[a-z]+/([a-z]+[0-9]+[a-z]?)(?:-|$)")


def item_of(branch):
    """feat/a0-setup-db -> A0; anything else -> the branch name."""
    m = ITEM_RE.match(branch)
    return m.group(1).upper() if m else branch


def git(*a):
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def env_value(key):
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip().strip("\"'") or None
    return None


def uri():
    v = os.environ.get("MONGODB_URI") or env_value("MONGODB_URI")
    if not v:
        sys.exit("adlc_log: MONGODB_URI not set (env or .env)")
    return v


def coll():
    import certifi
    from pymongo import MongoClient
    c = MongoClient(uri(), tlsCAFile=certifi.where(), serverSelectionTimeoutMS=8000)
    return c["adlc"]["log"]


def author(strict=True):
    """ADLC_AUTHOR from env or .env; must be in PEOPLE. Falls back to git user.name only for commits."""
    v = os.environ.get("ADLC_AUTHOR") or env_value("ADLC_AUTHOR")
    if v and v.lower() in PEOPLE:
        return v.lower()
    if strict:
        sys.exit(f"adlc_log: set ADLC_AUTHOR to one of {PEOPLE} in .env")
    return (git("config", "user.name") or "unknown").lower()


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
    a.add_argument("--to", choices=PEOPLE)
    t = s.add_parser("tail")
    t.add_argument("-n", type=int, default=10)
    t.add_argument("--item")
    b = s.add_parser("inbox")
    b.add_argument("-n", type=int, default=10)
    i = s.add_parser("item-of")
    i.add_argument("branch")
    s.add_parser("check")
    h = s.add_parser("commit-hook")
    h.add_argument("--sha")
    h.add_argument("--branch")
    x = p.parse_args()

    if x.cmd == "add":
        d = vars(x).copy(); d.pop("cmd")
        print("logged", add(d))
    elif x.cmd in ("tail", "inbox"):
        if x.cmd == "inbox":
            q, title = {"to": author()}, f"# inbox for {author()} (latest first)"
        else:
            q, title = ({"item": x.item} if x.item else {}), "# adlc.log (latest first)"
        print(title)
        for r in coll().find(q).sort("ts", -1).limit(x.n):
            to = f"->{r['to']} " if r.get("to") else ""
            print(f"{r['ts']:%m-%d %H:%M} {r.get('author','?'):6} {r.get('item','?'):10} "
                  f"{r.get('event','?'):10} {to}{r.get('summary','')[:110]}")
    elif x.cmd == "item-of":
        print(item_of(x.branch))
    elif x.cmd == "check":
        c = coll(); c.database.client.admin.command("ping")
        i = add({"item": "ADLC-CHECK", "event": "test_run", "tool": "human", "actor": "human",
                 "summary": "setup check", "phase": "Build"})
        c.delete_one({"_id": i})
        print("atlas ok; adlc.log writable")
    elif x.cmd == "commit-hook":
        sha = x.sha or git("rev-parse", "HEAD")
        msg = git("log", "-1", "--format=%s", sha)
        files = git("show", "--name-only", "--format=", sha).splitlines()
        item = item_of(x.branch or git("rev-parse", "--abbrev-ref", "HEAD"))
        add({"item": item, "event": "commit", "tool": "git", "actor": "human", "phase": None,
             "author": author(strict=False),
             "summary": msg, "commit_sha": sha[:7], "files": files[:50]})


if __name__ == "__main__":
    main()
