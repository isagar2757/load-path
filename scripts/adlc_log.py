#!/usr/bin/env -S uv run --quiet --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pymongo>=4.7", "certifi"]
# ///
"""Shared ADLC state: sandbox db `adlc`. `items` = status (only source), `log` = event feed.
Convention: docs/adlc/shared-log.md. `add` updates the item's status from the event; nothing to sync by hand.

  adlc_log.py board [--owner WHO] [--all]   # active, blocked, READY (todo with deps done); --all = every item
  adlc_log.py item ID [--owner O] [--title T] [--depends D ...] [--check C] [--status S] [--phase P] [--sha S]
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
OWNERS = PEOPLE + ["both"]
STATUSES = ["todo", "active", "blocked", "done", "dropped"]
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


_DB = None


def adlc_db():
    global _DB
    if _DB is None:
        import certifi
        from pymongo import MongoClient
        c = MongoClient(uri(), tlsCAFile=certifi.where(), serverSelectionTimeoutMS=8000)
        _DB = c[os.environ.get("ADLC_DB", "adlc")]
    return _DB


def coll():
    return adlc_db()["log"]


def items():
    return adlc_db()["items"]


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
    _id = coll().insert_one(doc).inserted_id
    apply_status(doc)
    return _id


def apply_status(e):
    """Event -> item status. The only automatic writer of `items`; commits never change status."""
    ev, upd = e.get("event"), {}
    if ev == "task_start":
        upd = {"status": "active", "blocked_on": None}
    elif ev == "blocker":
        upd = {"status": "blocked", "blocked_on": e.get("summary")}
    elif ev in ("task_done", "gate"):
        upd = {"status": "done", "blocked_on": None, "sha": e.get("sha") or e.get("evidence")}
    if e.get("phase") and ev != "commit":
        upd["phase"] = e["phase"]
    if not upd:
        return
    upd |= {"updated": e["ts"], "by": e["author"]}
    if items().update_one({"_id": e["item"]}, {"$set": upd}).matched_count == 0 and "status" in upd:
        print(f"adlc_log: no item {e['item']} in adlc.items; status not changed", file=sys.stderr)


def board(owner=None, show_all=False):
    rows = list(items().find({}).sort("order", 1))
    done = {r["_id"] for r in rows if r.get("status") in ("done", "dropped")}
    print(f"{'ID':6} {'OWNER':5} {'STATUS':8} {'PHASE':6} {'DEPS':12} TITLE / CHECK")
    for r in rows:
        if owner and r.get("owner") not in (owner, "both"):
            continue
        st = r.get("status", "todo")
        if st == "todo" and all(d in done for d in r.get("depends", [])):
            st = "READY"
        if not show_all and st not in ("active", "blocked", "READY"):
            continue
        extra = f" [{r['blocked_on']}]" if st == "blocked" and r.get("blocked_on") else ""
        extra += f" ({r['sha']})" if r.get("sha") and st == "done" else ""
        print(f"{r['_id']:6} {r.get('owner','?'):5} {st:8} {r.get('phase') or '-':6} "
              f"{','.join(r.get('depends', [])) or '-':12} {r.get('title','')}{extra}")
        if r.get("check") and st != "done":
            print(f"{'':42} check: {r['check']}")


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
    bd = s.add_parser("board")
    bd.add_argument("--owner", choices=OWNERS)
    bd.add_argument("--all", action="store_true")
    it = s.add_parser("item")
    it.add_argument("id")
    it.add_argument("--owner", choices=OWNERS)
    it.add_argument("--title")
    it.add_argument("--depends", nargs="*")
    it.add_argument("--check")
    it.add_argument("--status", choices=STATUSES)
    it.add_argument("--phase", choices=PHASES)
    it.add_argument("--sha")
    it.add_argument("--order", type=int)
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
    elif x.cmd == "board":
        board(x.owner, x.all)
    elif x.cmd == "item":
        f = {k: v for k, v in vars(x).items() if k not in ("cmd", "id") and v is not None}
        f |= {"updated": datetime.now(timezone.utc), "by": author()}
        u = {"$set": f}
        if "status" not in f:
            u["$setOnInsert"] = {"status": "todo"}
        r = items().update_one({"_id": x.id}, u, upsert=True)
        print("created" if r.upserted_id else "updated", x.id)
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
