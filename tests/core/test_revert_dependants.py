"""S6: dependency-scoped revert (docs/formulas.md section 3) with the real budget, work-order and inspection tools."""
from datetime import UTC, datetime

import pytest
from bson import ObjectId

import contracts
import setup_db
import systems
from core import gate, ledger, revert


@pytest.fixture(autouse=True)
def domain(world):
    tdb, _ = world
    systems.register()
    now = datetime.now(UTC)
    tdb.principals.insert_many([
        contracts.Principal(id=aid, kind="agent", roles=[aid.split(":")[1]], region="r1", spend_limit=0,
                            active=True).model_dump(by_alias=True)
        for aid in ("agent:workorder", "agent:orchestrator")])
    tdb.policies.insert_many(setup_db._policies(now))
    tdb.assets.insert_many([{"_id": "b1", "region": "r1"}, {"_id": "b2", "region": "r1"}])
    tdb.condition_records.insert_many([{"_id": "c1", "asset_id": "b1", "status": "pending"},
                                       {"_id": "c2", "asset_id": "b2", "status": "pending"}])


def _commit_and_order(tdb, sid, asset_id, condition_id):
    b = gate.guarded_call(sid, "agent:programming", "commit_budget", {"asset_id": asset_id, "amount": 30.0},
                          "r", depends_on=[condition_id], db=tdb)
    bid = b.result["produced"]
    w = gate.guarded_call(sid, "agent:workorder", "create_work_order", {"asset_id": asset_id, "budget_id": bid},
                          "r", depends_on=[bid], db=tdb)
    assert b.allowed and w.allowed and w.result, (b.reason, w.reason)
    return bid, w.result["produced"]


def _reverting(tdb, sid, condition_id):
    tdb.sessions.update_one({"_id": ObjectId(sid)}, {"$set": {"status": "reverting", "revert_for": condition_id}})


def _session(tdb, sid):
    return tdb.sessions.find_one({"_id": ObjectId(sid)})


def _seq(key):
    return int(key.rsplit(":", 1)[1])


def test_reject_reverts_only_dependants(world):
    tdb, sid = world
    b1, w1 = _commit_and_order(tdb, sid, "b1", "c1")
    b2, w2 = _commit_and_order(tdb, sid, "b2", "c2")
    _reverting(tdb, sid, "c1")

    out = revert.revert_dependants(sid, "c1", db=tdb)

    assert out["compensated"] == [_seq(w1), _seq(b1)] and out["failed"] == []
    assert tdb.budget_ledger.find_one({"_id": b1})["status"] == "released"
    assert tdb.work_orders.find_one({"_id": w1})["status"] == "cancelled"
    assert tdb.budget_ledger.find_one({"_id": b2})["status"] == "committed"
    assert tdb.work_orders.find_one({"_id": w2})["status"] == "draft"
    assert {s["seq"]: s["state"] for s in tdb.saga_stack.find({"session_id": sid})} == {
        _seq(b1): "compensated", _seq(w1): "compensated", _seq(b2): "done", _seq(w2): "done"}
    [req] = tdb.inspection_requests.find()
    assert (req["condition_id"], req["asset_id"]) == ("c1", "b1")
    assert out["inspection"].allowed is True
    assert _session(tdb, sid)["status"] == "running"
    assert ledger.verify(sid, db=tdb) == (True, None)


def test_reject_with_no_dependants(world):
    tdb, sid = world
    b2, w2 = _commit_and_order(tdb, sid, "b2", "c2")
    _reverting(tdb, sid, "c1")

    out = revert.revert_dependants(sid, "c1", db=tdb)

    assert out["compensated"] == [] and out["failed"] == []
    assert tdb.budget_ledger.find_one({"_id": b2})["status"] == "committed"
    assert tdb.work_orders.find_one({"_id": w2})["status"] == "draft"
    assert not [e for e in ledger.replay(sid, db=tdb) if e["type"] == "compensated"]
    [req] = tdb.inspection_requests.find()
    assert (req["condition_id"], req["asset_id"]) == ("c1", "b1")
    assert _session(tdb, sid)["status"] == "running"


def test_revert_requires_reverting_status(world):
    tdb, sid = world
    b1, _ = _commit_and_order(tdb, sid, "b1", "c1")
    with pytest.raises(RuntimeError, match="reverting"):
        revert.revert_dependants(sid, "c1", db=tdb)
    assert tdb.budget_ledger.find_one({"_id": b1})["status"] == "committed"
    assert tdb.inspection_requests.count_documents({}) == 0


def test_unknown_condition_raises_before_compensating(world):
    tdb, sid = world
    b1, _ = _commit_and_order(tdb, sid, "b1", "c1")
    tdb.condition_records.delete_one({"_id": "c1"})
    _reverting(tdb, sid, "c1")
    with pytest.raises(LookupError, match="c1"):
        revert.revert_dependants(sid, "c1", db=tdb)
    assert tdb.budget_ledger.find_one({"_id": b1})["status"] == "committed"
    assert _session(tdb, sid)["status"] == "reverting"


def test_failed_undo_keeps_session_reverting(world):
    tdb, sid = world
    b1, w1 = _commit_and_order(tdb, sid, "b1", "c1")
    _reverting(tdb, sid, "c1")
    reg = gate.REGISTRY["commit_budget"]

    def broken(db, undo_args):
        raise RuntimeError("undo broke")

    gate.register_tool("commit_budget", reg.fn, reg.snapshot, broken, reg.undo_tool)
    out = revert.revert_dependants(sid, "c1", db=tdb)

    assert out["failed"] == [_seq(b1)] and out["inspection"] is None
    assert tdb.work_orders.find_one({"_id": w1})["status"] == "cancelled"
    assert tdb.inspection_requests.count_documents({}) == 0
    assert _session(tdb, sid)["status"] == "reverting"
