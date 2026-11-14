"""X2: each agent builds its options from the database; index 0 is the code's best. Pure reads."""
import contracts
from core.agents import intake, planner, programming, workorder


def _line(asset_id, cost, benefit, treatment="minor_rehab"):
    return {"asset_id": asset_id, "treatment": treatment, "cost": cost, "benefit": benefit}


def _plan(tdb, sid, seq, lines):
    tdb.plans.insert_one({"_id": f"{sid}:{seq}", "session_id": sid, "seq": seq, "superseded": False, "lines": lines})


def _commit(tdb, sid, seq, asset_id, amount=5000.0):
    tdb.budget_ledger.insert_one({"_id": f"{sid}:{seq}", "session_id": sid, "asset_id": asset_id, "amount": amount,
                                  "status": "committed"})


def test_agent_ids_come_from_the_contract():
    ids = [m.AGENT_ID for m in (intake, planner, programming, workorder)]
    assert ids == list(contracts.AGENT_IDS[:4])
    assert [contracts.TOOLS[t].actor for t in
            ("propose_condition", "propose_plan", "commit_budget", "create_work_order")] == ids


def test_intake_offers_a_mock_reading_per_bridge_without_one(world):
    tdb, sid = world
    tdb.condition_records.insert_many([
        {"_id": "b1:2018", "asset_id": "b1", "rating": 90.0, "year": 2018, "status": "approved"},
        {"_id": "b1:2020", "asset_id": "b1", "rating": 70.0, "year": 2020, "status": "approved"},
        {"_id": "b2:2020", "asset_id": "b2", "rating": 60.5, "year": 2020, "status": "approved"}])
    got = intake.options(tdb, sid, ["b2", "b1"])
    assert [(s.tool, s.args) for s in got] == [
        ("propose_condition", {"asset_id": "b1", "rating": 65.0, "year": intake.MOCK_YEAR}),
        ("propose_condition", {"asset_id": "b2", "rating": 55.5, "year": intake.MOCK_YEAR})]
    assert all(s.rationale.startswith("MOCK") for s in got) and "70.0 in 2020" in got[0].rationale
    tdb.condition_records.insert_one({"_id": f"{sid}:3", "asset_id": "b1", "rating": 65.0, "year": 2026,
                                      "status": "rejected"})
    assert [s.args["asset_id"] for s in intake.options(tdb, sid, ["b2", "b1"])] == ["b2"]
    assert intake.options(tdb, sid, []) == []


def test_planner_proposes_only_when_an_approval_is_newer_than_the_plan(world):
    tdb, sid = world
    [first] = planner.options(tdb, sid, [])
    assert (first.tool, first.args) == ("propose_plan", {}) and "no active plan" in first.rationale
    _plan(tdb, sid, 5, [])
    assert planner.options(tdb, sid, []) == []
    tdb.audit_events.insert_many([
        {"session_id": sid, "seq": 3, "type": "executed", "tool": "approve_condition"},
        {"session_id": sid, "seq": 7, "type": "decision", "tool": "approve_condition"}])
    assert planner.options(tdb, sid, []) == []
    tdb.audit_events.insert_one({"session_id": sid, "seq": 8, "type": "executed", "tool": "approve_condition"})
    [again] = planner.options(tdb, sid, [])
    assert "seq 8" in again.rationale and "seq 5" in again.rationale


def test_programming_ranks_uncommitted_plan_lines_in_scope(world):
    tdb, sid = world
    assert programming.options(tdb, sid, ["b1"]) == []
    _plan(tdb, sid, 5, [_line("b1", 5000.0, 100.0), _line("b2", 10000.0, 200.0), _line("b3", 500.0, 10.0),
                        _line("b4", 60000.0, 600.0, "replacement"), _line("zz", 1.0, 1.0)])
    got = programming.options(tdb, sid, ["b1", "b2", "b3", "b4"])
    assert [(s.tool, s.args) for s in got] == [
        ("commit_budget", {"asset_id": "b2", "amount": 10000.0}),   # 0.02 per dollar, benefit 200
        ("commit_budget", {"asset_id": "b1", "amount": 5000.0}),    # 0.02 per dollar, benefit 100
        ("commit_budget", {"asset_id": "b3", "amount": 500.0}),     # 0.02 per dollar, benefit 10
        ("commit_budget", {"asset_id": "b4", "amount": 60000.0})]   # 0.01 per dollar
    assert "0.020000" in got[0].rationale and "200.00" in got[0].rationale and "10,000.00" in got[0].rationale
    assert all(s.depends_on == () for s in got)

    _commit(tdb, sid, 6, "b2", 10000.0)
    tdb.condition_records.insert_one({"_id": f"{sid}:9", "asset_id": "b1", "rating": 65.0, "year": 2026,
                                      "status": "pending"})
    got = programming.options(tdb, sid, ["b1", "b2"])
    assert [s.args["asset_id"] for s in got] == ["b1"]
    assert got[0].depends_on == (f"{sid}:9",) and f"{sid}:9" in got[0].rationale


def test_workorder_offers_committed_lines_without_an_order(world):
    tdb, sid = world
    assert workorder.options(tdb, sid, ["b1", "b2"]) == []
    _commit(tdb, sid, 10, "b2", 7000.0)
    _commit(tdb, sid, 4, "b1")
    _commit(tdb, sid, 12, "zz")
    tdb.budget_ledger.insert_one({"_id": f"{sid}:2", "session_id": sid, "asset_id": "b1", "amount": 1.0,
                                  "status": "released"})
    got = workorder.options(tdb, sid, ["b1", "b2"])
    assert [(s.tool, s.args, s.depends_on) for s in got] == [
        ("create_work_order", {"asset_id": "b1", "budget_id": f"{sid}:4"}, (f"{sid}:4",)),
        ("create_work_order", {"asset_id": "b2", "budget_id": f"{sid}:10"}, (f"{sid}:10",))]
    assert "7,000.00" in got[1].rationale
    tdb.work_orders.insert_one({"_id": f"{sid}:5", "session_id": sid, "asset_id": "b1", "budget_id": f"{sid}:4",
                                "status": "draft"})
    assert [s.args["asset_id"] for s in workorder.options(tdb, sid, ["b1", "b2"])] == ["b2"]
    tdb.work_orders.update_one({"_id": f"{sid}:5"}, {"$set": {"status": "cancelled"}})
    assert [s.args["asset_id"] for s in workorder.options(tdb, sid, ["b1", "b2"])] == ["b1", "b2"]
