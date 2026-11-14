"""Saga stack and compensation. Rules: docs/formulas.md section 3.

`guarded_call` arms an entry before a tool runs and marks it `done` after. Compensation calls the registered
`undo` directly (not through the gate: the session is no longer `running` while it rolls back) and records a
`compensated` event per entry, or a `failed` event and `comp_failed` state when an undo raises.
Session status changes belong to the orchestrator (S4); this module only undoes.
"""
from bson import ObjectId

import db as dbmod
from contracts import SagaEntry
from core import gate

ACTOR = "core:revert"


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


def rollback_session(session_id: str, db=None) -> dict:
    """Compensate every `armed` or `done` entry of the session, newest first. Safe to repeat."""
    d = db if db is not None else dbmod.get_db()
    entries = list(d.saga_stack.find({"session_id": session_id, "state": {"$in": ["armed", "done"]}}))
    return compensate(d, session_id, entries)
