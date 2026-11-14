"""S4: task claim, scripted agents and the stop watcher (docs/formulas.md section 6)."""
import threading
import time
from datetime import UTC, datetime

import pytest
from bson import ObjectId

import contracts
import setup_db
import systems
from core import gate, ledger, orchestrator
from core.agents import Step
from systems import budget


@pytest.fixture
def stage2(world):
    """The real budget and work-order tools with their stage 2 policies and two assets in the session's region."""
    tdb, sid = world
    systems.register()
    now = datetime.now(UTC)
    tdb.principals.insert_one(contracts.Principal(id="agent:workorder", kind="agent", roles=["workorder"],
                                                  region="r1", spend_limit=0, active=True).model_dump(by_alias=True))
    for tool, role, checks in [("commit_budget", "programming", ["spend_limit", "envelope", "jurisdiction"]),
                               ("create_work_order", "workorder", ["has_commitment"])]:
        tdb.policies.insert_one(contracts.Policy(
            tool=tool, version=1, status="active", roles=[role],
            checks=[contracts.PolicyCheck(name=n) for n in ["role", *checks]],
            author="user:owner_a", created_at=now).model_dump())
    tdb.assets.insert_many([{"_id": "b1", "region": "r1"}, {"_id": "b2", "region": "r1"}])
    yield tdb, sid
    systems.register()


SCRIPT = [
    Step("commit_budget", {"asset_id": "b1", "amount": 30.0}, "commit b1"),
    Step("commit_budget", {"asset_id": "b2", "amount": 40.0}, "commit b2"),
    Step("create_work_order", {"asset_id": "b1"}, "work order b1", {"budget_id": 0}),
    Step("commit_budget", {"asset_id": "b2", "amount": 10.0}, "never runs"),
]


def _request_stop(tdb, sid):
    tdb.sessions.update_one({"_id": ObjectId(sid), "status": "running"},
                            {"$set": {"status": "abort_requested", "aborted_by": "user:owner_a"}})


def _status(tdb, sid):
    return tdb.sessions.find_one({"_id": ObjectId(sid)})["status"]


def test_claim_takes_a_queued_task_once(world):
    tdb, sid = world
    tdb.tasks.insert_one(contracts.Task(session_id=sid, type="commit_budget", agent_id="agent:programming",
                                        status="queued", created_at=datetime.now(UTC)).model_dump())
    assert orchestrator.claim(tdb, sid)["status"] == "claimed"
    assert orchestrator.claim(tdb, sid) is None


def test_script_hands_off_through_tasks(stage2):
    tdb, sid = stage2
    orch = orchestrator.Orchestrator(sid, db=tdb)
    orch.start()
    results = [r for _, r in orch.run(SCRIPT[:3])]
    assert [r.allowed for r in results] == [True, True, True], [r.reason for r in results]
    tasks = list(tdb.tasks.find({"session_id": sid}).sort("_id", 1))
    assert [(t["type"], t["agent_id"], t["status"]) for t in tasks] == [
        ("commit_budget", "agent:programming", "done"), ("commit_budget", "agent:programming", "done"),
        ("create_work_order", "agent:workorder", "done")]
    order = tdb.work_orders.find_one({"session_id": sid})
    assert order["budget_id"] == tasks[0]["output"]["produced"]
    assert ledger.replay(sid, db=tdb)[0]["type"] == "session_started"
    assert _status(tdb, sid) == "running"


def test_stop_halts_and_rolls_back(stage2):
    tdb, sid = stage2
    orch = orchestrator.Orchestrator(sid, db=tdb)
    orch.start()
    results, t0 = [], None
    for _, r in orch.run(SCRIPT):
        results.append(r)
        if len(results) == 3:
            _request_stop(tdb, sid)
            t0 = time.monotonic()
    while _status(tdb, sid) != "rolled_back" and time.monotonic() - t0 < 10:
        pass
    elapsed = time.monotonic() - t0
    orch.watcher.join(timeout=10)
    assert _status(tdb, sid) == "rolled_back"
    assert len(results) == 3 and all(r.allowed for r in results)
    assert tdb.budget_ledger.count_documents({"status": "committed"}) == 0
    assert tdb.work_orders.count_documents({"status": {"$ne": "cancelled"}}) == 0
    assert tdb.tasks.count_documents({"session_id": sid}) == 3
    types = [e["type"] for e in ledger.replay(sid, db=tdb)]
    assert types.count("compensated") == 3 and types[-1] == "session_ended"
    assert types.index("abort_observed") < types.index("compensated")
    assert ledger.verify(sid, db=tdb) == (True, None)
    assert elapsed < 5, f"stop to rolled_back took {elapsed:.2f} s"


def test_stop_during_tool(stage2):
    tdb, sid = stage2
    started = threading.Event()

    def slow_commit(db, args):
        started.set()
        time.sleep(0.6)
        return budget.commit_budget(db, args)

    gate.register_tool("commit_budget", slow_commit, budget.snapshot, budget.release_budget, "release_budget")
    orch = orchestrator.Orchestrator(sid, db=tdb)
    orch.start()
    stopper = threading.Thread(target=lambda: started.wait(10) and _request_stop(tdb, sid))
    stopper.start()
    results = [r for _, r in orch.run(SCRIPT[:2])]
    stopper.join()
    orch.watcher.join(timeout=10)
    assert _status(tdb, sid) == "rolled_back"
    assert len(results) == 1 and results[0].result is not None
    types = [e["type"] for e in ledger.replay(sid, db=tdb)]
    assert types.count("executed") == 1
    assert types.index("executed") < types.index("abort_observed")
    assert tdb.budget_ledger.count_documents({"status": "committed"}) == 0


def test_reject_reverts_dependants_then_replans(world):
    tdb, sid = world
    systems.register()
    tdb.principals.insert_many([
        contracts.Principal(id=aid, kind="agent", roles=[aid.split(":")[1]], region="r1", spend_limit=0,
                            active=True).model_dump(by_alias=True)
        for aid in ("agent:workorder", "agent:orchestrator", "agent:planner")])
    tdb.policies.insert_many(setup_db._policies(datetime.now(UTC)))
    tdb.policies.update_one({"tool": "commit_budget", "status": "active"},
                            {"$pull": {"checks": {"name": "in_approved_plan"}}})  # same test with or without it
    tdb.assets.insert_many([{"_id": "b1", "region": "r1", "deck_area": 10.0},
                            {"_id": "b2", "region": "r1", "deck_area": 10.0}])
    tdb.condition_records.insert_many([{"_id": "c1", "asset_id": "b1", "rating": 50.0, "status": "rejected"},
                                       {"_id": "c2", "asset_id": "b2", "rating": 80.0, "status": "approved"}])
    ids = {}
    for asset_id, cond in [("b1", "c1"), ("b2", "c2")]:
        b = gate.guarded_call(sid, "agent:programming", "commit_budget", {"asset_id": asset_id, "amount": 30.0},
                              "r", depends_on=[cond], db=tdb)
        assert b.allowed and b.result, b.reason
        ids[asset_id] = b.result["produced"]
    orch = orchestrator.Orchestrator(sid, db=tdb)
    orch.start()
    tdb.sessions.update_one({"_id": ObjectId(sid)}, {"$set": {"status": "reverting", "revert_for": "c1"}})
    t0 = time.monotonic()
    while not tdb.plans.find_one({"session_id": sid}) and time.monotonic() - t0 < 10:
        time.sleep(0.05)

    assert tdb.budget_ledger.find_one({"_id": ids["b1"]})["status"] == "released"
    assert tdb.budget_ledger.find_one({"_id": ids["b2"]})["status"] == "committed"
    [req] = tdb.inspection_requests.find()
    assert (req["condition_id"], req["asset_id"]) == ("c1", "b1")
    assert tdb.plans.count_documents({"session_id": sid, "superseded": False}) == 1
    assert _status(tdb, sid) == "running"

    _request_stop(tdb, sid)
    orch.watcher.join(timeout=10)
    assert _status(tdb, sid) == "rolled_back"
    assert tdb.budget_ledger.count_documents({"status": "committed"}) == 0
    assert ledger.verify(sid, db=tdb) == (True, None)
