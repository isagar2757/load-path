"""Saga stack and compensation. Rules: docs/formulas.md section 3.

`guarded_call` arms an entry before a tool runs and marks it `done` after. Compensation calls the registered
`undo` directly (not through the gate: the session is no longer `running` while it rolls back) and records a
`compensated` event per entry, or a `failed` event and `comp_failed` state when an undo raises.
Session status changes belong to the orchestrator (S4), except `reverting` → `running` after `revert_dependants`.
"""
from datetime import UTC, datetime

from bson import ObjectId

import db as dbmod
from contracts import TOOLS, SagaEntry
from core import gate

ACTOR = "core:revert"
INSPECT = "request_inspection"


def arm(d, session_id: str, seq: int, tool: str, undo_tool: str, key: str, depends_on: list[str]) -> None:
    d.saga_stack.insert_one(SagaEntry(
        session_id=session_id, seq=seq, tool=tool, undo_tool=undo_tool,
        undo_args={"idempotency_key": key, "produced": None}, depends_on=depends_on, state="armed",
    ).model_dump())


def mark_done(d, session_id: str, seq: int, produced) -> None:
    """Best effort: if this update fails the entry stays armed, which is still compensable."""
    produced = None if produced is None else str(produced)
    try:
        d.saga_stack.update_one({"session_id": session_id, "seq": seq, "state": "armed"},
                                {"$set": {"state": "done", "produced": produced, "undo_args.produced": produced}})
    except Exception:
        pass


def compensate(d, session_id: str, entries: list[dict]) -> dict:
    """Undo `entries` newest first. Returns the saga seqs compensated and failed."""
    session = d.sessions.find_one({"_id": ObjectId(session_id)}) if ObjectId.is_valid(session_id) else None
    principal = (session or {}).get("principal_id", "unknown")
    out: dict[str, list[int]] = {"compensated": [], "failed": []}
    for e in sorted(entries, key=lambda s: s["seq"], reverse=True):
        base = {"principal_id": principal, "actor_id": ACTOR, "tool": e["undo_tool"], "args": e["undo_args"],
                "depends_on": e.get("depends_on", [])}
        reg = gate.REGISTRY.get(e["tool"])
        try:
            if reg is None:
                raise LookupError(f"{e['tool']} is not registered")
            result = reg.undo(d, e["undo_args"])
        except Exception as ex:
            d.saga_stack.update_one({"session_id": session_id, "seq": e["seq"]}, {"$set": {"state": "comp_failed"}})
            gate._record_after(d, session_id, {**base, "type": "failed",
                                               "reason": f"undo seq {e['seq']}: {gate._err(ex)}"})
            out["failed"].append(e["seq"])
            continue
        d.saga_stack.update_one({"session_id": session_id, "seq": e["seq"]}, {"$set": {"state": "compensated"}})
        gate._record_after(d, session_id, {**base, "type": "compensated",
                                           "after": {"saga_seq": e["seq"], "result": result}})
        out["compensated"].append(e["seq"])
    return out


def _live(d, session_id: str) -> list[dict]:
    return list(d.saga_stack.find({"session_id": session_id, "state": {"$in": ["armed", "done"]}}))


def rollback_session(session_id: str, db=None) -> dict:
    """Compensate every `armed` or `done` entry of the session, newest first. Safe to repeat."""
    d = db if db is not None else dbmod.get_db()
    return compensate(d, session_id, _live(d, session_id))


def dependants(entries: list[dict], condition_id: str) -> list[dict]:
    """D(c): entries whose `depends_on` reaches `condition_id` directly or through another entry's `produced`."""
    reached, hit = {condition_id}, {}
    while new := [e for e in entries if e["seq"] not in hit and reached & set(e.get("depends_on", []))]:
        for e in new:
            hit[e["seq"]] = e
            if e.get("produced"):
                reached.add(e["produced"])
    return list(hit.values())


def revert_dependants(session_id: str, condition_id: str, db=None) -> dict:
    """Compensate D(condition) newest first, resume the session, then open an inspection request.

    Raises unless the session is `reverting`. A failed undo opens no request and leaves the status `reverting`;
    the orchestrator then ends the session `failed`.
    """
    d = db if db is not None else dbmod.get_db()
    oid = ObjectId(session_id) if ObjectId.is_valid(session_id) else None
    session = d.sessions.find_one({"_id": oid}) if oid else None
    if session is None or session["status"] != "reverting":
        raise RuntimeError(f"revert_dependants: session {session_id} is not reverting")
    condition = d.condition_records.find_one({"_id": condition_id}, {"asset_id": 1})
    if condition is None:
        raise LookupError(f"revert_dependants: condition {condition_id} not found")
    out = compensate(d, session_id, dependants(_live(d, session_id), condition_id))
    if out["failed"]:
        return {**out, "inspection": None}
    # Conditional: a stop requested meanwhile is kept, and the gate then denies the request below.
    d.sessions.update_one({"_id": oid, "status": "reverting"},
                          {"$set": {"status": "running", "updated_at": datetime.now(UTC)}})
    inspection = gate.guarded_call(
        session_id, TOOLS[INSPECT].actor, INSPECT, {"condition_id": condition_id, "asset_id": condition["asset_id"]},
        f"condition {condition_id} rejected; {len(out['compensated'])} dependants reverted", db=d)
    return {**out, "inspection": inspection}
