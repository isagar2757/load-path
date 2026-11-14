"""S7: Planner proposes a plan through the gate; commit_budget only for a line of the session's active plan."""
from datetime import UTC, datetime

import pytest
from bson import ObjectId

import contracts
import setup_db
import systems
from core import gate
from systems import plans

PLANNER = contracts.TOOLS["propose_plan"].actor
PROGRAMMING = contracts.TOOLS["commit_budget"].actor


@pytest.fixture(autouse=True)
def domain(world):
    tdb, sid = world
    systems.register()
    tdb.principals.insert_one(contracts.Principal(
        id=PLANNER, kind="agent", roles=["planner"], region="r1", spend_limit=0, active=True,
    ).model_dump(by_alias=True))
    tdb.policies.insert_many(setup_db._policies(datetime.now(UTC)))
    # deck 10 m2: b1 (BCI 50) major 20000 -> 250; b2 (BCI 80) minor 5000 -> 100. Optimum at 25000: both.
    tdb.assets.insert_many([{"_id": "b1", "region": "r1", "deck_area": 10.0},
                            {"_id": "b2", "region": "r1", "deck_area": 10.0}])
    tdb.condition_records.insert_many([{"_id": "c1", "asset_id": "b1", "rating": 50.0, "status": "approved"},
                                       {"_id": "c2", "asset_id": "b2", "rating": 80.0, "status": "approved"}])
    _envelope(tdb, sid, 25_000.0)


def _envelope(tdb, sid, value):
    tdb.sessions.update_one({"_id": ObjectId(sid)}, {"$set": {"budget_envelope": value}})


def _commit(tdb, sid, asset_id, amount):
    return gate.guarded_call(sid, PROGRAMMING, "commit_budget", {"asset_id": asset_id, "amount": amount}, "r", db=tdb)


def _lines(tdb, plan_id):
    return sorted((l["asset_id"], l["cost"]) for l in tdb.plans.find_one({"_id": plan_id})["lines"])


def test_off_plan_commit_denied(world):
    tdb, sid = world
    assert _commit(tdb, sid, "b1", 20_000.0).reason.startswith("in_approved_plan")  # no plan yet

    r = plans.replan(sid, db=tdb)
    assert r.allowed and r.result, r.reason
    assert _lines(tdb, r.result["produced"]) == [("b1", 20_000.0), ("b2", 5_000.0)]

    off = _commit(tdb, sid, "b2", 20_000.0)
    assert off.allowed is False and off.reason.startswith("in_approved_plan")
    assert _commit(tdb, sid, "b1", 20_000.0).allowed is True
    assert tdb.budget_ledger.count_documents({"session_id": sid}) == 1


def test_envelope_lowered_denies_next(world):
    tdb, sid = world
    assert plans.replan(sid, db=tdb).allowed
    first = _commit(tdb, sid, "b1", 20_000.0)
    assert first.allowed

    _envelope(tdb, sid, 22_000.0)
    r = plans.replan(sid, db=tdb)
    assert r.allowed and r.result, r.reason
    assert _lines(tdb, r.result["produced"]) == [("b1", 20_000.0)]  # the commitment stays fixed (F)

    assert _commit(tdb, sid, "b2", 5_000.0).allowed is False
    line = tdb.budget_ledger.find_one({"_id": first.result["produced"]})
    assert line["status"] == "committed" and line["amount"] == 20_000.0
