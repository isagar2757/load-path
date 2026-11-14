"""S2: policy checks beyond `role` (docs/formulas.md section 1). Each deny leaves the target unchanged."""
import pytest
from bson import ObjectId
from pymongo import MongoClient

from core import gate


def _write_scratch(db, args):
    return {"produced": str(db.scratch.insert_one({"args": args}).inserted_id)}


def _none(db, args):
    return None


@pytest.fixture(autouse=True)
def stub_tool():
    gate.register_tool("write_scratch", _write_scratch, _none, lambda db, a: {}, None)
    yield
    gate.REGISTRY.pop("write_scratch", None)


def _checks(tdb, *names):
    tdb.policies.update_one({"tool": "write_scratch"},
                            {"$set": {"checks": [{"name": n, "params": {}} for n in ("role", *names)]}})


def _call(tdb, sid, args, actor="agent:programming"):
    return gate.guarded_call(sid, actor, "write_scratch", args, "why", db=tdb)


def _line(tdb, sid, asset_id, amount, status="committed"):
    tdb.budget_ledger.insert_one({"session_id": sid, "asset_id": asset_id, "amount": amount,
                                  "status": status, "depends_on": []})


# spend_limit: args.amount <= spend_limit of the human the session acts for
def test_spend_limit_denies_over_human_limit(world):
    tdb, sid = world
    _checks(tdb, "spend_limit")
    tdb.principals.update_one({"_id": "user:owner_a"}, {"$set": {"spend_limit": 50}})
    r = _call(tdb, sid, {"amount": 60})
    assert r.allowed is False and r.reason.startswith("spend_limit")
    assert tdb.scratch.count_documents({}) == 0
    assert _call(tdb, sid, {"amount": 50}).allowed is True


@pytest.mark.parametrize("amount", [None, "10", -5, 0, True, float("nan")])
def test_spend_limit_denies_bad_amount(world, amount):
    tdb, sid = world
    _checks(tdb, "spend_limit")
    args = {} if amount is None else {"amount": amount}
    r = _call(tdb, sid, args)
    assert r.allowed is False and r.reason.startswith("spend_limit")
    assert tdb.scratch.count_documents({}) == 0


# envelope: committed lines in the session + args.amount <= session.budget_envelope (100 in `world`)
def test_envelope_denies_over_session_envelope(world):
    tdb, sid = world
    _checks(tdb, "envelope")
    _line(tdb, sid, "a1", 70)
    _line(tdb, sid, "a2", 500, status="released")    # released lines do not count
    _line(tdb, str(ObjectId()), "a3", 500)            # other sessions do not count
    r = _call(tdb, sid, {"amount": 40})
    assert r.allowed is False and r.reason.startswith("envelope")
    assert tdb.scratch.count_documents({}) == 0
    assert _call(tdb, sid, {"amount": 30}).allowed is True


# jurisdiction: asset.region = session.region; a human actor's region must match too
def test_jurisdiction_denies_asset_in_other_region(world):
    tdb, sid = world
    _checks(tdb, "jurisdiction")
    tdb.assets.insert_many([{"_id": "a1", "region": "r1"}, {"_id": "a2", "region": "r2"}])
    r = _call(tdb, sid, {"asset_id": "a2"})
    assert r.allowed is False and r.reason.startswith("jurisdiction")
    assert tdb.scratch.count_documents({}) == 0
    assert _call(tdb, sid, {"asset_id": "a1"}).allowed is True


def test_jurisdiction_denies_unknown_asset(world):
    tdb, sid = world
    _checks(tdb, "jurisdiction")
    r = _call(tdb, sid, {"asset_id": "ghost"})
    assert r.allowed is False and r.reason.startswith("jurisdiction")
    assert tdb.scratch.count_documents({}) == 0


def test_jurisdiction_denies_human_from_other_region(world):
    tdb, sid = world
    _checks(tdb, "jurisdiction")
    tdb.policies.update_one({"tool": "write_scratch"}, {"$set": {"roles": ["owner"]}})
    tdb.assets.insert_one({"_id": "a1", "region": "r1"})
    tdb.principals.insert_one({"_id": "user:owner_b", "kind": "human", "roles": ["owner"], "region": "r2",
                               "spend_limit": 10, "active": True})
    r = _call(tdb, sid, {"asset_id": "a1"}, actor="user:owner_b")
    assert r.allowed is False and r.reason.startswith("jurisdiction")
    assert tdb.scratch.count_documents({}) == 0
    assert _call(tdb, sid, {"asset_id": "a1"}, actor="user:owner_a").allowed is True


# has_commitment: a committed budget line exists for (session, asset)
def test_has_commitment_denies_without_committed_line(world):
    tdb, sid = world
    _checks(tdb, "has_commitment")
    _line(tdb, sid, "a1", 10, status="released")
    _line(tdb, str(ObjectId()), "a1", 10)
    r = _call(tdb, sid, {"asset_id": "a1"})
    assert r.allowed is False and r.reason.startswith("has_commitment")
    assert tdb.scratch.count_documents({}) == 0
    _line(tdb, sid, "a1", 10)
    assert _call(tdb, sid, {"asset_id": "a1"}).allowed is True


def test_first_failing_check_is_the_reason(world):
    tdb, sid = world
    _checks(tdb, "spend_limit", "envelope")
    tdb.principals.update_one({"_id": "user:owner_a"}, {"$set": {"spend_limit": 50}})
    r = _call(tdb, sid, {"amount": 500})   # fails both; spend_limit is listed first
    assert r.reason.startswith("spend_limit")


def test_unknown_check_denies(world):
    tdb, sid = world
    _checks(tdb, "in_approved_plan")       # Stage 4; not implemented yet
    r = _call(tdb, sid, {"amount": 1})
    assert r.allowed is False and r.reason.startswith("in_approved_plan")
    assert tdb.scratch.count_documents({}) == 0


# Fail closed: no database, no decision, no execution. Runs without MONGODB_URI.
def test_gate_denies_when_atlas_down():
    ran = []
    gate.register_tool("write_scratch", lambda db, a: ran.append(a) or {}, _none, lambda db, a: {}, None)
    dead = MongoClient("mongodb://127.0.0.1:1/", serverSelectionTimeoutMS=300, connectTimeoutMS=300)["capital_test"]
    try:
        r = gate.guarded_call(str(ObjectId()), "agent:programming", "write_scratch", {"amount": 1}, "why", db=dead)
    finally:
        dead.client.close()
    assert r.allowed is False and r.reason
    assert ran == []
