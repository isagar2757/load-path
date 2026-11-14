"""S7: Planner tool. Solves the session's plan (docs/formulas.md section 4) and records it as one upsert.

A plan's `_id` is the gate's idempotency key `<session_id>:<seq>`. The session's active plan is its
highest-`seq` plan not superseded; `supersede_plan` (the undo) marks a plan superseded.
"""
import scipy
from bson import ObjectId

import db as dbmod
from contracts import TOOLS, ConditionStatus, ToolResult
from core import gate
from engine import plan as engine

TOOL = "propose_plan"
APPROVED = ConditionStatus.__args__[1]
SOLVER = {"name": "scipy.optimize.milp", "version": scipy.__version__}


def _session_and_seq(key: str) -> tuple[str, int]:
    sid, seq = key.rsplit(":", 1)
    return sid, int(seq)


def propose_plan(db, args: dict) -> dict:
    key = args["idempotency_key"]
    sid, seq = _session_and_seq(key)
    session = db.sessions.find_one({"_id": ObjectId(sid)})
    assets = list(db.assets.find({"region": session["region"]}, {"deck_area": 1}))
    conditions = list(db.condition_records.find(
        {"asset_id": {"$in": [a["_id"] for a in assets]}, "status": APPROVED}, {"asset_id": 1, "rating": 1}))
    cands = engine.candidates(assets, conditions)
    committed = {(b["asset_id"], b["amount"])
                 for b in db.budget_ledger.find({"session_id": sid, "status": "committed"})}
    fixed = [(c.asset_id, c.treatment) for c in cands if (c.asset_id, c.cost) in committed]
    result = engine.solve(cands, session["budget_envelope"], fixed, [])
    versions = {p["tool"]: p["version"] for p in db.policies.find(
        {"tool": {"$in": [TOOL, "commit_budget"]}, "status": "active"}, {"tool": 1, "version": 1})}
    db.plans.update_one({"_id": key}, {"$setOnInsert": {
        "session_id": sid, "seq": seq, "superseded": False, **result.model_dump(),
        "policy_versions": versions, "solver": SOLVER,
    }}, upsert=True)
    return {"produced": key}


def snapshot(db, args: dict) -> dict | None:
    return db.plans.find_one({"_id": args["idempotency_key"]})


def supersede_plan(db, undo_args: dict) -> dict:
    r = db.plans.update_one({"_id": undo_args["idempotency_key"], "superseded": False},
                            {"$set": {"superseded": True}})
    return {"superseded": r.modified_count}


def replan(session_id: str, db=None) -> ToolResult:
    """Re-solve the session's plan through the gate, e.g. after a revert. S4's watcher calls this."""
    d = db if db is not None else dbmod.get_db()
    return gate.guarded_call(session_id, TOOLS[TOOL].actor, TOOL, {}, "re-plan from current approved conditions",
                             db=d)
