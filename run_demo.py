"""Stage 2 demo beat: agents commit, an over-limit commitment is denied, stop rolls back.

    uv run python run_demo.py --reset            # then open the printed URL and press Stop
    uv run python run_demo.py --reset --auto-stop

Amounts are assumptions (README). Every domain write goes through `guarded_call`.
"""
import argparse
import time
from datetime import UTC, datetime

from bson import ObjectId

import contracts as c
import db as dbmod
import setup_db
import systems
from core import gate, revert

RUN_COLLECTIONS = ("sessions", "tasks", "audit_events", "saga_stack", "budget_ledger", "work_orders",
                   "inspection_requests")
OWNER = "user:owner_a"
ENVELOPE = 120_000.0
COMMITS = (40_000.0, 35_000.0)
OVER_LIMIT = setup_db.OWNER_SPEND + 50_000.0


def reset(d) -> None:
    for name in RUN_COLLECTIONS:
        d[name].delete_many({})
    setup_db.setup(d.name)


def _set_status(d, sid: str, status: str) -> None:
    d.sessions.update_one({"_id": ObjectId(sid)}, {"$set": {"status": status, "updated_at": datetime.now(UTC)}})


def _show(r: c.ToolResult, label: str) -> None:
    print(f"  {label}: {'ALLOW' if r.allowed else 'DENY'}" + ("" if r.allowed else f"  ({r.reason})"))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true")
    p.add_argument("--auto-stop", action="store_true", help="request stop without the page")
    p.add_argument("--wait", type=float, default=8.0, help="seconds to open the page before the run")
    p.add_argument("--step", type=float, default=1.5)
    a = p.parse_args()

    d = dbmod.get_db()
    if a.reset:
        reset(d)
    systems.register()
    assets = [x["_id"] for x in d.assets.find({"region": setup_db.REGION}, {"_id": 1}).sort("_id", 1).limit(2)]
    if len(assets) < 2:
        raise SystemExit("need 2 assets in region r1: run `uv run python -m systems.assets` (A4)")

    now = datetime.now(UTC)
    sid = str(d.sessions.insert_one(c.Session(
        principal_id=OWNER, task="stage 2 demo", region=setup_db.REGION, budget_envelope=ENVELOPE,
        status="running", created_at=now, updated_at=now).model_dump()).inserted_id)
    print(f"session {sid}\nopen http://127.0.0.1:8000/?session_id={sid}")
    time.sleep(a.wait)

    commits = []
    for asset, amount in zip(assets, COMMITS):
        r = gate.guarded_call(sid, "agent:programming", "commit_budget", {"asset_id": asset, "amount": amount},
                              f"commit {amount:.0f} for {asset}", db=d)
        _show(r, f"commit_budget {asset} {amount:.0f}")
        commits.append(r)
        time.sleep(a.step)
    if commits[0].allowed:
        r = gate.guarded_call(sid, "agent:workorder", "create_work_order",
                              {"asset_id": assets[0], "budget_id": commits[0].result["produced"]},
                              f"work order for {assets[0]}", db=d)
        _show(r, f"create_work_order {assets[0]}")
        time.sleep(a.step)
    r = gate.guarded_call(sid, "agent:programming", "commit_budget", {"asset_id": assets[1], "amount": OVER_LIMIT},
                          "over-limit attempt", db=d)
    _show(r, f"commit_budget {assets[1]} {OVER_LIMIT:.0f}")

    if a.auto_stop:
        _set_status(d, sid, "abort_requested")
    print("waiting for Stop ...")
    while d.sessions.find_one({"_id": ObjectId(sid)}, {"status": 1})["status"] != "abort_requested":
        time.sleep(0.5)
    _set_status(d, sid, "rolling_back")
    out = revert.rollback_session(sid, db=d)
    _set_status(d, sid, "rolled_back" if not out["failed"] else "failed")
    print(f"rollback: {out}")
    print(f"committed lines left: {d.budget_ledger.count_documents({'session_id': sid, 'status': 'committed'})}")


if __name__ == "__main__":
    main()
