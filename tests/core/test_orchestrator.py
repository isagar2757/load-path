"""S4/X2: task claim, the agent turn loop and the stop watcher (docs/formulas.md section 6)."""
import threading
import time
from datetime import UTC, datetime

import pytest
from bson import ObjectId

import contracts
import setup_db
import systems
from core import gate, ledger, orchestrator
from core.agents import Step, intake, planner, programming, workorder
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
    Step("commit_budget", {"asset_id": "b2", "amount": 40.0}, "never runs"),
]
LOOP = [planner, intake, programming, workorder]


def _request_stop(tdb, sid):
    tdb.sessions.update_one({"_id": ObjectId(sid), "status": "running"},
                            {"$set": {"status": "abort_requested", "aborted_by": "user:owner_a"}})


def _status(tdb, sid):
    return tdb.sessions.find_one({"_id": ObjectId(sid)})["status"]


@pytest.fixture
def program(world):
    """Every agent and demo policy, two bridges with an approved reading each, an envelope that fits both."""
    tdb, sid = world
    systems.register()
    tdb.principals.insert_many([
        contracts.Principal(id=aid, kind="agent", roles=[aid.split(":")[1]], region="r1", spend_limit=0,
                            active=True).model_dump(by_alias=True)
        for aid in ("agent:workorder", "agent:orchestrator", "agent:planner")])
    tdb.policies.insert_many(setup_db._policies(datetime.now(UTC)))
    tdb.sessions.update_one({"_id": ObjectId(sid)}, {"$set": {"budget_envelope": 1_000_000.0}})
    tdb.assets.insert_many([{"_id": "b1", "region": "r1", "deck_area": 10.0},
                            {"_id": "b2", "region": "r1", "deck_area": 20.0}])
    tdb.condition_records.insert_many([
        {"_id": "b1:2020", "asset_id": "b1", "rating": 70.0, "year": 2020, "status": "approved"},
        {"_id": "b2:2020", "asset_id": "b2", "rating": 60.0, "year": 2020, "status": "approved"}])
    return tdb, sid


def test_claim_takes_a_queued_task_once(world):
    tdb, sid = world
    tdb.tasks.insert_one(contracts.Task(session_id=sid, type="commit_budget", agent_id="agent:programming",
                                        status="queued", created_at=datetime.now(UTC)).model_dump())
    assert orchestrator.claim(tdb, sid)["status"] == "claimed"
    assert orchestrator.claim(tdb, sid) is None


def test_run_agents_yields_task_chain_and_stops(program):
    tdb, sid = program
    orch = orchestrator.Orchestrator(sid, db=tdb)
    orch.start()
    done = list(orch.run_agents(LOOP, ["b1", "b2"], use_llm=False, max_rounds=10))
    assert all(r.allowed and r.result for _, _, r in done), [r.reason for _, _, r in done]
    tasks = list(tdb.tasks.find({"session_id": sid}).sort("_id", 1))
    out = [t["output"]["produced"] for t in tasks]
    # round 1: plan both bridges, a reading for b1 arrives, commit the best line (b2), open its order;
    # round 2: a reading for b2, commit b1 (now resting on its pending reading), open its order; round 3: nothing.
    assert [(t["type"], t["agent_id"], t["status"], t["input"]["args"].get("asset_id"), t["input"]["depends_on"])
            for t in tasks] == [
        ("propose_plan", "agent:planner", "done", None, []),
        ("propose_condition", "agent:intake", "done", "b1", []),
        ("commit_budget", "agent:programming", "done", "b2", []),
        ("create_work_order", "agent:workorder", "done", "b2", [out[2]]),
        ("propose_condition", "agent:intake", "done", "b2", []),
        ("commit_budget", "agent:programming", "done", "b1", [out[1]]),
        ("create_work_order", "agent:workorder", "done", "b1", [out[5]])]
    assert [{k: t["input"][k] for k in ("offered", "picked", "by", "model")} for t in tasks[1:3]] == [
        {"offered": 2, "picked": 0, "by": "script", "model": None}] * 2
    assert [m for _, m, _ in done] == [{k: t["input"][k] for k in ("offered", "picked", "by", "model")} for t in tasks]
    assert ledger.replay(sid, db=tdb)[0]["type"] == "session_started"
    assert _status(tdb, sid) == "running"
    assert list(orch.run_agents(LOOP, ["b1", "b2"], use_llm=False, max_rounds=10)) == []


def test_run_agents_stops_at_max_rounds_and_at_a_deny(program):
    tdb, sid = program
    orch = orchestrator.Orchestrator(sid, db=tdb)
    orch.start()
    assert [s.tool for s, _, _ in orch.run_agents(LOOP, ["b1", "b2"], use_llm=False, max_rounds=1)] == [
        "propose_plan", "propose_condition", "commit_budget", "create_work_order"]
    tdb.policies.update_one({"tool": "commit_budget", "status": "active"}, {"$set": {"roles": ["nobody"]}})
    done = list(orch.run_agents(LOOP, ["b1", "b2"], use_llm=False, max_rounds=10))
    assert [(s.tool, r.allowed) for s, _, r in done] == [("propose_condition", True), ("commit_budget", False)]
    assert tdb.tasks.find_one({"session_id": sid}, sort=[("_id", -1)])["status"] == "failed"
    assert _status(tdb, sid) == "running"


def test_stop_mid_loop_rolls_back(program):
    tdb, sid = program
    orch = orchestrator.Orchestrator(sid, db=tdb)
    orch.start()
    results, t0 = [], None
    for _, _, r in orch.run_agents(LOOP, ["b1", "b2"], use_llm=False, max_rounds=10):
        results.append(r)
        if len(results) == 4:
            _request_stop(tdb, sid)
            t0 = time.monotonic()
    while _status(tdb, sid) != "rolled_back" and time.monotonic() - t0 < 10:
        pass
    elapsed = time.monotonic() - t0
    orch.watcher.join(timeout=10)
    assert _status(tdb, sid) == "rolled_back"
    assert len(results) == 4 and all(r.allowed for r in results)
    assert tdb.budget_ledger.count_documents({"status": "committed"}) == 0
    assert tdb.work_orders.count_documents({"status": {"$ne": "cancelled"}}) == 0
    assert tdb.plans.count_documents({"superseded": False}) == 0
    assert tdb.tasks.count_documents({"session_id": sid}) == 4
    types = [e["type"] for e in ledger.replay(sid, db=tdb)]
    assert types.count("compensated") == 4 and types[-1] == "session_ended"
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
    results = [orch.submit(step) for step in SCRIPT]
    stopper.join()
    orch.watcher.join(timeout=10)
    assert _status(tdb, sid) == "rolled_back"
    assert results[0].result is not None and results[1] is None
    types = [e["type"] for e in ledger.replay(sid, db=tdb)]
    assert types.count("executed") == 1
    assert types.index("executed") < types.index("abort_observed")
    assert tdb.budget_ledger.count_documents({"status": "committed"}) == 0


def _two_commitments(tdb, sid):
    """b1's commitment depends on rejected c1, b2's on approved c2. Returns {asset_id: budget_id}."""
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
    return ids


def test_reject_reverts_dependants_then_replans(world):
    tdb, sid = world
    ids = _two_commitments(tdb, sid)
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


def test_failed_undo_ends_session_failed(world):
    tdb, sid = world
    ids = _two_commitments(tdb, sid)
    reg = gate.REGISTRY["commit_budget"]

    def broken(db, undo_args):
        raise RuntimeError("undo broke")

    gate.register_tool("commit_budget", reg.fn, reg.snapshot, broken, reg.undo_tool)
    try:
        orch = orchestrator.Orchestrator(sid, db=tdb)
        orch.start()
        tdb.sessions.update_one({"_id": ObjectId(sid)}, {"$set": {"status": "reverting", "revert_for": "c1"}})
        orch.watcher.join(timeout=10)
    finally:
        systems.register()

    assert not orch.watcher.is_alive()
    assert _status(tdb, sid) == "failed"
    ended = [e for e in ledger.replay(sid, db=tdb) if e["type"] == "session_ended"]
    assert [e["after"]["failed"] for e in ended] == [[int(ids["b1"].rsplit(":", 1)[1])]]
    assert tdb.inspection_requests.count_documents({}) == 0
    assert tdb.plans.count_documents({}) == 0
    assert ledger.verify(sid, db=tdb) == (True, None)


def test_denied_replan_ends_session_failed(world):
    tdb, sid = world
    ids = _two_commitments(tdb, sid)
    tdb.policies.update_one({"tool": "propose_plan", "status": "active"}, {"$set": {"roles": ["nobody"]}})
    orch = orchestrator.Orchestrator(sid, db=tdb)
    orch.start()
    tdb.sessions.update_one({"_id": ObjectId(sid)}, {"$set": {"status": "reverting", "revert_for": "c1"}})
    orch.watcher.join(timeout=10)

    assert not orch.watcher.is_alive()
    assert _status(tdb, sid) == "failed"
    assert tdb.budget_ledger.find_one({"_id": ids["b1"]})["status"] == "released"
    assert tdb.plans.count_documents({}) == 0
    [ended] = [e for e in ledger.replay(sid, db=tdb) if e["type"] == "session_ended"]
    assert ended["after"]["status"] == "failed" and ended["after"]["reason"].startswith("re-plan: role")
    assert ledger.verify(sid, db=tdb) == (True, None)
