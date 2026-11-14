from datetime import UTC, datetime

import pytest

from core import gate, ledger


def _write_scratch(db, args):
    _id = db.scratch.insert_one({"n": args["n"], "written_at": datetime.now(UTC)}).inserted_id
    return {"produced": str(_id)}


def _snapshot(db, args):
    return None


def _undo(db, undo_args):
    return {}


@pytest.fixture(autouse=True)
def stub_tool():
    gate.register_tool("write_scratch", _write_scratch, _snapshot, _undo, None)
    yield
    gate.REGISTRY.pop("write_scratch", None)


def _events(tdb, sid):
    return ledger.replay(sid, db=tdb)


def test_deny_without_policy(world):
    tdb, sid = world
    gate.register_tool("no_policy_tool", _write_scratch, _snapshot, _undo, None)
    try:
        r = gate.guarded_call(sid, "agent:programming", "no_policy_tool", {"n": 1}, "why", db=tdb)
    finally:
        gate.REGISTRY.pop("no_policy_tool", None)
    assert r.allowed is False and r.reason
    assert tdb.scratch.count_documents({}) == 0
    evs = _events(tdb, sid)
    assert [(e["type"], e["decision"]) for e in evs] == [("decision", "deny")]


def test_deny_unregistered_tool(world):
    tdb, sid = world
    r = gate.guarded_call(sid, "agent:programming", "nope", {"n": 1}, "why", db=tdb)
    assert r.allowed is False
    assert tdb.scratch.count_documents({}) == 0


def test_role_check_denies_wrong_actor(world):
    tdb, sid = world
    r = gate.guarded_call(sid, "agent:intake", "write_scratch", {"n": 1}, "why", db=tdb)
    assert r.allowed is False and r.reason.startswith("role")
    assert tdb.scratch.count_documents({}) == 0


def test_deny_inactive_actor(world):
    tdb, sid = world
    tdb.principals.update_one({"_id": "agent:programming"}, {"$set": {"active": False}})
    r = gate.guarded_call(sid, "agent:programming", "write_scratch", {"n": 1}, "why", db=tdb)
    assert r.allowed is False
    assert tdb.scratch.count_documents({}) == 0


def test_deny_when_session_not_running(world):
    tdb, sid = world
    from bson import ObjectId
    tdb.sessions.update_one({"_id": ObjectId(sid)}, {"$set": {"status": "abort_requested"}})
    r = gate.guarded_call(sid, "agent:programming", "write_scratch", {"n": 1}, "why", db=tdb)
    assert r.allowed is False
    assert tdb.scratch.count_documents({}) == 0


def test_allowed_call_executes_and_logs(world):
    tdb, sid = world
    r = gate.guarded_call(sid, "agent:programming", "write_scratch", {"n": 7}, "because", db=tdb)
    assert r.allowed is True and r.reason is None
    assert tdb.scratch.count_documents({"n": 7}) == 1
    evs = _events(tdb, sid)
    assert [e["type"] for e in evs] == ["decision", "executed"]
    d = evs[0]
    assert (d["principal_id"], d["actor_id"], d["policy_version"], d["rationale"]) == \
        ("user:owner_a", "agent:programming", 1, "because")
    assert evs[1]["after"] == r.result and r.seq == evs[1]["seq"]
    assert ledger.verify(sid, db=tdb) == (True, None)


def test_decision_precedes_write(world):
    tdb, sid = world
    gate.guarded_call(sid, "agent:programming", "write_scratch", {"n": 1}, "why", db=tdb)
    decision = _events(tdb, sid)[0]
    written = tdb.scratch.find_one({"n": 1})
    assert decision["type"] == "decision"
    assert decision["ts"] <= written["written_at"]


def test_tool_error_logs_failed(world):
    tdb, sid = world

    def boom(db, args):
        raise RuntimeError("tool broke")

    gate.register_tool("write_scratch", boom, _snapshot, _undo, None)
    r = gate.guarded_call(sid, "agent:programming", "write_scratch", {"n": 1}, "why", db=tdb)
    assert r.allowed is True and r.result is None and "tool broke" in r.reason
    assert [e["type"] for e in _events(tdb, sid)] == ["decision", "failed"]


def test_role_enforced_when_policy_lists_no_checks(world):
    tdb, sid = world
    tdb.policies.update_one({"tool": "write_scratch"}, {"$set": {"checks": []}})
    r = gate.guarded_call(sid, "agent:intake", "write_scratch", {"n": 1}, "why", db=tdb)
    assert r.allowed is False and r.reason.startswith("role")
    assert tdb.scratch.count_documents({}) == 0


def test_unrecordable_result_still_logged_as_failed(world):
    tdb, sid = world

    def odd(db, args):
        db.scratch.insert_one({"n": args["n"]})
        return {"produced": {1, 2}}  # a set: cannot be canonicalised

    gate.register_tool("write_scratch", odd, _snapshot, _undo, None)
    r = gate.guarded_call(sid, "agent:programming", "write_scratch", {"n": 1}, "why", db=tdb)
    assert r.allowed is True and r.reason.startswith("ledger")
    evs = _events(tdb, sid)
    assert [e["type"] for e in evs] == ["decision", "failed"]
    assert evs[1]["reason"].startswith("ledger")
