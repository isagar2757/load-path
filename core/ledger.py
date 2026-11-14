"""Append-only, hash-chained audit ledger per session. Rules: docs/formulas.md section 2.

The chain detects edits and gaps; it does not prevent them.
"""
import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

import db as dbmod
from contracts import GENESIS_HASH, AuditEvent

_RETRIES = 5


def _db(db):
    return db if db is not None else dbmod.get_db()


def _ms(ts: datetime) -> datetime:
    """UTC, truncated to milliseconds (what BSON stores). Naive values are taken as UTC."""
    ts = ts.replace(tzinfo=UTC) if ts.tzinfo is None else ts.astimezone(UTC)
    return ts.replace(microsecond=ts.microsecond // 1000 * 1000)


def _default(o: Any) -> str:
    if isinstance(o, datetime):
        return _ms(o).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if isinstance(o, ObjectId):
        return str(o)
    raise TypeError(f"not canonicalisable: {type(o).__name__}")


def canon(obj: Any) -> str:
    """JSON, sorted keys, no whitespace, dates ISO-8601 ms UTC, ObjectIds as hex."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=_default, ensure_ascii=False)


def event_hash(prev_hash: str, event: dict) -> str:
    body = {k: v for k, v in event.items() if k not in ("_id", "hash")}
    return hashlib.sha256((prev_hash + canon(body)).encode()).hexdigest()


def append(session_id: str, event: dict, db=None) -> dict:
    """Add `event` as the next `seq` of the session; returns the stored document.

    `seq` and `prev_hash` come from the session's last event; the unique `{session_id, seq}` index (created by
    setup_db.py) turns a concurrent append into a retry instead of a fork. `ts` is always stamped here.
    """
    d = _db(db)
    for _ in range(_RETRIES):
        last = d.audit_events.find_one({"session_id": session_id}, sort=[("seq", -1)],
                                       projection={"seq": 1, "hash": 1})
        seq, prev = (last["seq"] + 1, last["hash"]) if last else (1, GENESIS_HASH)
        doc = {**event, "session_id": session_id, "seq": seq, "prev_hash": prev,
               "ts": _ms(datetime.now(UTC)), "hash": ""}
        doc = AuditEvent.model_validate(doc).model_dump()
        doc["hash"] = event_hash(prev, doc)
        try:
            d.audit_events.insert_one(doc)
        except DuplicateKeyError:
            continue
        if ObjectId.is_valid(session_id):
            # Guarded on the previous head so a late writer cannot move the head backwards.
            d.sessions.update_one({"_id": ObjectId(session_id), "audit_head": prev},
                                  {"$set": {"audit_head": doc["hash"]}})
        return doc
    raise RuntimeError(f"ledger append contended {_RETRIES} times for session {session_id}")


def replay(session_id: str, db=None) -> list[dict]:
    """Events of the session in `seq` order."""
    return list(_db(db).audit_events.find({"session_id": session_id}, {"_id": 0}).sort("seq", 1))


def verify(session_id: str, db=None) -> tuple[bool, int | None]:
    """Recompute the chain. Returns `(True, None)` or `(False, n)`: the first position whose seq or hash is wrong.

    If a session document exists, its `audit_head` must equal the last hash; otherwise events were removed from
    the end and `n` is the first missing position.
    """
    d = _db(db)
    prev, n = GENESIS_HASH, 0
    for n, ev in enumerate(replay(session_id, db=d), start=1):
        if ev.get("seq") != n or ev.get("prev_hash") != prev or ev.get("hash") != event_hash(prev, ev):
            return False, n
        prev = ev["hash"]
    session = d.sessions.find_one({"_id": ObjectId(session_id)}, {"audit_head": 1}) \
        if ObjectId.is_valid(session_id) else None
    if session is not None and session.get("audit_head", GENESIS_HASH) != prev:
        return False, n + 1
    return True, None
