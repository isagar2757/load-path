from datetime import UTC, datetime, timedelta

from bson import ObjectId

from contracts import GENESIS_HASH
from core import ledger


def _event(i):
    return {"type": "decision", "principal_id": "user:owner_a", "actor_id": "agent:programming",
            "tool": "write_scratch", "args": {"n": i}, "decision": "allow"}


def test_append_chains_hashes(tdb):
    evs = [ledger.append("s1", _event(i), db=tdb) for i in range(3)]
    assert [e["seq"] for e in evs] == [1, 2, 3]
    assert evs[0]["prev_hash"] == GENESIS_HASH
    stored = list(tdb.audit_events.find({"session_id": "s1"}).sort("seq", 1))
    for prev, cur in zip(stored, stored[1:]):
        assert cur["prev_hash"] == prev["hash"]
    assert ledger.verify("s1", db=tdb) == (True, None)


def test_verify_flags_edit(tdb):
    for i in range(3):
        ledger.append("s1", _event(i), db=tdb)
    tdb.audit_events.update_one({"session_id": "s1", "seq": 1}, {"$set": {"args": {"n": 99}}})
    assert ledger.verify("s1", db=tdb) == (False, 1)


def test_verify_flags_gap(tdb):
    for i in range(3):
        ledger.append("s1", _event(i), db=tdb)
    tdb.audit_events.delete_one({"session_id": "s1", "seq": 2})
    assert ledger.verify("s1", db=tdb) == (False, 2)


def test_replay_returns_events_in_seq_order(tdb):
    for i in range(3):
        ledger.append("s1", _event(i), db=tdb)
    assert [e["args"]["n"] for e in ledger.replay("s1", db=tdb)] == [0, 1, 2]


def test_append_stamps_ts_itself(tdb):
    old = datetime.now(UTC) - timedelta(hours=1)
    ev = ledger.append("s1", {**_event(0), "ts": old}, db=tdb)
    assert ev["ts"] > old + timedelta(minutes=59)


def test_verify_flags_truncated_tail(world):
    tdb, sid = world
    for i in range(3):
        ledger.append(sid, _event(i), db=tdb)
    assert tdb.sessions.find_one({"_id": ObjectId(sid)})["audit_head"] == ledger.replay(sid, db=tdb)[-1]["hash"]
    tdb.audit_events.delete_one({"session_id": sid, "seq": 3})
    assert ledger.verify(sid, db=tdb) == (False, 3)
