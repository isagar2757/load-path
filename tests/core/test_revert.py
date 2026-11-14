"""S3: saga entries around execution and newest-first rollback (docs/formulas.md section 3).

Stub tools follow the A2/A3 shape: the gate adds `idempotency_key`; undo finds the write by that key.
`test_rollback_restores_state` with the real budget and work-order tools is added when A2/A3 land.
"""
import pytest

from core import gate, ledger, revert


def _put(db, args):
    key = args["idempotency_key"]
    db.stub.update_one({"_id": key}, {"$setOnInsert": {"n": args["n"]}}, upsert=True)
    return {"produced": key}


def _del(db, undo_args):
    db.stub.delete_one({"_id": undo_args["idempotency_key"]})
    return {"deleted": undo_args["idempotency_key"]}


def _none(db, args):
    return None


@pytest.fixture(autouse=True)
def tools(world):
    tdb, _ = world
    gate.register_tool("write_scratch", _put, _none, _del, "delete_scratch")
    yield
    gate.REGISTRY.pop("write_scratch", None)


def _call(tdb, sid, n, depends_on=None):
    return gate.guarded_call(sid, "agent:programming", "write_scratch", {"n": n}, "why",
                             depends_on=depends_on, db=tdb)


def _saga(tdb, sid):
    return list(tdb.saga_stack.find({"session_id": sid}, {"_id": 0}).sort("seq", 1))


def test_allowed_call_leaves_done_entry(world):
    tdb, sid = world
    r = _call(tdb, sid, 1, depends_on=["c1"])
    [s] = _saga(tdb, sid)
    decision = ledger.replay(sid, db=tdb)[0]
    key = f"{sid}:{decision['seq']}"
    assert (s["seq"], s["state"], s["tool"], s["undo_tool"]) == (decision["seq"], "done", "write_scratch",
                                                                 "delete_scratch")
    assert s["produced"] == key == r.result["produced"]
    assert s["undo_args"] == {"idempotency_key": key, "produced": key}
    assert s["depends_on"] == ["c1"]


def test_entry_is_armed_while_tool_runs(world):
    tdb, sid = world
    seen = []

    def spy(db, args):
        seen.append(db.saga_stack.find_one({"session_id": sid})["state"])
        return _put(db, args)

    gate.register_tool("write_scratch", spy, _none, _del, "delete_scratch")
    _call(tdb, sid, 1)
    assert seen == ["armed"]


def test_tool_error_leaves_entry_armed(world):
    tdb, sid = world

    def half(db, args):
        _put(db, args)
        raise RuntimeError("after write")

    gate.register_tool("write_scratch", half, _none, _del, "delete_scratch")
    r = _call(tdb, sid, 1)
    assert r.result is None and "after write" in r.reason
    [s] = _saga(tdb, sid)
    assert s["state"] == "armed" and s["undo_args"]["produced"] is None


def test_denied_call_has_no_entry(world):
    tdb, sid = world
    gate.guarded_call(sid, "agent:intake", "write_scratch", {"n": 1}, "why", db=tdb)
    assert _saga(tdb, sid) == []


def test_tool_without_undo_has_no_entry(world):
    tdb, sid = world
    gate.register_tool("write_scratch", _put, _none, _del, None)
    assert _call(tdb, sid, 1).allowed is True
    assert _saga(tdb, sid) == []


def test_rollback_newest_first_restores_and_logs(world):
    tdb, sid = world
    for n in (1, 2, 3):
        _call(tdb, sid, n)
    order = []
    gate.register_tool("write_scratch", _put, _none,
                       lambda db, u: order.append(u["idempotency_key"]) or _del(db, u), "delete_scratch")
    out = revert.rollback_session(sid, db=tdb)
    seqs = [s["seq"] for s in _saga(tdb, sid)]
    assert order == [f"{sid}:{q}" for q in reversed(seqs)]
    assert tdb.stub.count_documents({}) == 0
    assert {s["state"] for s in _saga(tdb, sid)} == {"compensated"}
    comp = [e for e in ledger.replay(sid, db=tdb) if e["type"] == "compensated"]
    assert [e["after"]["saga_seq"] for e in comp] == list(reversed(seqs))
    assert out == {"compensated": list(reversed(seqs)), "failed": []}
    assert ledger.verify(sid, db=tdb) == (True, None)


def test_rollback_compensates_armed_entry(world):
    tdb, sid = world

    def half(db, args):
        _put(db, args)
        raise RuntimeError("after write")

    gate.register_tool("write_scratch", half, _none, _del, "delete_scratch")
    _call(tdb, sid, 1)
    assert tdb.stub.count_documents({}) == 1
    revert.rollback_session(sid, db=tdb)
    assert tdb.stub.count_documents({}) == 0
    assert _saga(tdb, sid)[0]["state"] == "compensated"


def test_rollback_twice_is_once(world):
    tdb, sid = world
    _call(tdb, sid, 1)
    revert.rollback_session(sid, db=tdb)
    n_events = len(ledger.replay(sid, db=tdb))
    assert revert.rollback_session(sid, db=tdb) == {"compensated": [], "failed": []}
    assert len(ledger.replay(sid, db=tdb)) == n_events


def test_failed_undo_marks_comp_failed_and_continues(world):
    tdb, sid = world
    _call(tdb, sid, 1)
    _call(tdb, sid, 2)
    first, second = [s["seq"] for s in _saga(tdb, sid)]

    def flaky(db, u):
        if u["idempotency_key"].endswith(f":{second}"):
            raise RuntimeError("undo broke")
        return _del(db, u)

    gate.register_tool("write_scratch", _put, _none, flaky, "delete_scratch")
    out = revert.rollback_session(sid, db=tdb)
    assert out == {"compensated": [first], "failed": [second]}
    states = {s["seq"]: s["state"] for s in _saga(tdb, sid)}
    assert states == {first: "compensated", second: "comp_failed"}
    failed = [e for e in ledger.replay(sid, db=tdb) if e["type"] == "failed"]
    assert failed and "undo broke" in failed[-1]["reason"]
