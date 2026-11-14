"""A6: solve() per docs/formulas.md section 4. Pure: no database."""
import pytest

from contracts import PlanLine
from engine import plan


def _c(asset_id, treatment, cost, benefit):
    return {"asset_id": asset_id, "treatment": treatment, "cost": cost, "benefit": benefit}


# Greedy by benefit or by benefit/cost takes b1 alone (100); the optimum is b2 + b3 (120).
THREE = [_c("b1", "t", 60.0, 100.0), _c("b2", "t", 50.0, 60.0), _c("b3", "t", 50.0, 60.0)]
TWO_TREATMENTS = [_c("b1", "small", 10.0, 10.0), _c("b1", "large", 20.0, 25.0), _c("b2", "small", 10.0, 8.0)]


def _picked(result):
    return [(line.asset_id, line.treatment) for line in result.lines]


def test_solve_three_items_known_optimum():
    r = plan.solve(THREE, 100.0, [], [])
    assert r.status == plan.OPTIMAL
    assert _picked(r) == [("b2", "t"), ("b3", "t")]
    assert r.objective == 120.0


def test_solve_respects_envelope():
    for envelope in (0.0, 49.0, 50.0, 100.0, 110.0, 160.0):
        r = plan.solve(THREE, envelope, [], [])
        assert r.status == plan.OPTIMAL
        assert sum(line.cost for line in r.lines) <= envelope


def test_solve_is_repeatable():
    a = plan.solve(THREE, 100.0, [], ["b1"])
    b = plan.solve(list(reversed(THREE)), 100.0, [], ["b1"])
    assert a.lines == b.lines
    assert a.inputs_hash == b.inputs_hash
    assert len(a.inputs_hash) == 64


def test_inputs_hash_changes_with_each_input():
    base = plan.solve(TWO_TREATMENTS, 100.0, [], []).inputs_hash
    assert plan.solve(TWO_TREATMENTS[:2], 100.0, [], []).inputs_hash != base
    assert plan.solve(TWO_TREATMENTS, 99.0, [], []).inputs_hash != base
    assert plan.solve(TWO_TREATMENTS, 100.0, [("b1", "small")], []).inputs_hash != base
    assert plan.solve(TWO_TREATMENTS, 100.0, [], ["b2"]).inputs_hash != base


def test_solve_picks_at_most_one_treatment_per_bridge():
    r = plan.solve(TWO_TREATMENTS, 100.0, [], [])
    assert _picked(r) == [("b1", "large"), ("b2", "small")]


def test_solve_keeps_fixed_lines():
    r = plan.solve(TWO_TREATMENTS, 100.0, [("b1", "small")], [])
    assert _picked(r) == [("b1", "small"), ("b2", "small")]
    assert r.objective == 18.0


def test_solve_never_chooses_excluded_bridge():
    r = plan.solve(TWO_TREATMENTS, 100.0, [], ["b1"])
    assert _picked(r) == [("b2", "small")]


def test_solve_reports_infeasible_when_fixed_exceeds_envelope():
    r = plan.solve(TWO_TREATMENTS, 5.0, [("b1", "small")], [])
    assert (r.status, r.objective, r.lines) == (plan.INFEASIBLE, None, [])


def test_solve_reports_infeasible_when_fixed_bridge_is_excluded():
    assert plan.solve(TWO_TREATMENTS, 100.0, [("b1", "small")], ["b1"]).status == plan.INFEASIBLE


def test_solve_refuses_fixed_line_that_is_not_a_candidate():
    with pytest.raises(ValueError):
        plan.solve(TWO_TREATMENTS, 100.0, [("b9", "small")], [])


def test_candidates_cost_and_benefit_from_treatments():
    assets = [{"_id": "b1", "deck_area": 200.0}, {"_id": "b2", "deck_area": 50.0}]
    conditions = [{"asset_id": "b1", "rating": 70.0}, {"asset_id": "b2", "rating": 95.0}]
    got = plan.candidates(assets, conditions)
    assert len(got) == 2 * len(plan.TREATMENTS)
    for line in got:
        delta, cost_per_m2 = plan.TREATMENTS[line.treatment]
        area, rating = {"b1": (200.0, 70.0), "b2": (50.0, 95.0)}[line.asset_id]
        assert line == PlanLine(asset_id=line.asset_id, treatment=line.treatment,
                                cost=cost_per_m2 * area, benefit=min(delta, 100.0 - rating) * area)


def test_candidates_refuses_condition_without_asset():
    with pytest.raises(KeyError):
        plan.candidates([], [{"asset_id": "b1", "rating": 70.0}])
