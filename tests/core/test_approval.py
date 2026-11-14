"""S5: humans through the gate. `approve_condition` / `reject_condition` policies from setup_db (formulas section 1).

Stub tools stand in for A5: they set the condition's status in one update keyed by `condition_id`.
"""
from datetime import UTC, datetime

import pytest

import contracts
import setup_db
from core import gate, ledger

PENDING, APPROVED, REJECTED = contracts.ConditionStatus.__args__


def _set_status(status):
    def fn(db, args):
        db.condition_records.update_one({"_id": args["condition_id"]}, {"$set": {"status": status}})
        return {"produced": args["idempotency_key"]}
    return fn


def _none(db, args):
    return None


@pytest.fixture(autouse=True)
def approval(world):
    tdb, _ = world
    now = datetime.now(UTC)
    tdb.policies.insert_many([p for p in setup_db._policies(now)
                              if p["tool"] in ("approve_condition", "reject_condition")])
    tdb.assets.insert_many([{"_id": "b1", "region": "r1"}, {"_id": "b2", "region": "r2"}])
    tdb.condition_records.insert_many([{"_id": "c1", "asset_id": "b1", "status": PENDING},
                                       {"_id": "c2", "asset_id": "b2", "status": PENDING}])
    gate.register_tool("approve_condition", _set_status(APPROVED), _none, _none, None)
    gate.register_tool("reject_condition", _set_status(REJECTED), _none, _none, None)
    yield
    gate.REGISTRY.pop("approve_condition", None)
    gate.REGISTRY.pop("reject_condition", None)


def _call(tdb, sid, tool, args, actor="user:owner_a"):
    return gate.guarded_call(sid, actor, tool, args, "inspection report read", db=tdb)


def _status(tdb, cid):
    return tdb.condition_records.find_one({"_id": cid})["status"]


def test_agent_cannot_approve(world):
    tdb, sid = world
    r = _call(tdb, sid, "approve_condition", {"condition_id": "c1", "asset_id": "b1"}, actor="agent:intake")
    assert r.allowed is False and r.reason.startswith("role")
    assert [(e["type"], e["decision"], e["actor_id"]) for e in ledger.replay(sid, db=tdb)] == \
        [("decision", "deny", "agent:intake")]
    assert _status(tdb, "c1") == PENDING


def test_owner_approves_in_region(world):
    tdb, sid = world
    r = _call(tdb, sid, "approve_condition", {"condition_id": "c1", "asset_id": "b1"})
    assert r.allowed is True and r.reason is None
    assert _status(tdb, "c1") == APPROVED


def test_owner_cannot_approve_out_of_region(world):
    tdb, sid = world
    r = _call(tdb, sid, "approve_condition", {"condition_id": "c2", "asset_id": "b2"})
    assert r.allowed is False and r.reason.startswith("jurisdiction")
    assert _status(tdb, "c2") == PENDING


@pytest.mark.parametrize("reason", [None, "", "   ", 7, ["why"]])
def test_reject_without_reason_denied(world, reason):
    tdb, sid = world
    args = {"condition_id": "c1", "asset_id": "b1"} | ({} if reason is None else {"reason": reason})
    r = _call(tdb, sid, "reject_condition", args)
    assert r.allowed is False and r.reason.startswith("has_reason")
    assert _status(tdb, "c1") == PENDING


def test_reject_with_reason_allowed(world):
    tdb, sid = world
    r = _call(tdb, sid, "reject_condition", {"condition_id": "c1", "asset_id": "b1", "reason": "deck spalling"})
    assert r.allowed is True and r.reason is None
    assert _status(tdb, "c1") == REJECTED
