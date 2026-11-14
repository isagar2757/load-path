"""A6: treatment selection as a MILP (docs/formulas.md section 4). Pure: reads its arguments, writes nothing."""
import hashlib
import json

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from contracts import PlanLine, PlanResult

# assumption, README: treatment -> (rating gain in BCI points, cost per m2 of deck area). Not sourced figures.
TREATMENTS = {
    "minor_rehab": (10.0, 500.0),
    "major_rehab": (25.0, 2000.0),
    "replacement": (60.0, 6000.0),
}
RATING_MAX = 100.0  # top of the BCI scale; a treatment cannot gain more than the distance to it
OPTIMAL, INFEASIBLE = "optimal", "infeasible"
_MILP_INFEASIBLE = 2  # scipy.optimize.milp status code


def candidates(assets: list[dict], conditions: list[dict]) -> list[PlanLine]:
    """One candidate per (condition record, treatment): cost = rate x deck area, benefit = gain x deck area."""
    area = {a["_id"]: a["deck_area"] for a in assets}
    return [
        PlanLine(asset_id=c["asset_id"], treatment=name, cost=rate * area[c["asset_id"]],
                 benefit=min(gain, RATING_MAX - c["rating"]) * area[c["asset_id"]])
        for c in conditions for name, (gain, rate) in TREATMENTS.items()
    ]


def solve(candidates: list, envelope: float, fixed: list, excluded: list) -> PlanResult:
    """Maximise total benefit within `envelope`, at most one treatment per bridge.

    candidates: PlanLine or dicts of that shape, at least one, each (asset_id, treatment) once.
    fixed: (asset_id, treatment) pairs that must be chosen. excluded: asset ids that must not be.
    """
    lines = sorted((PlanLine.model_validate(c) for c in candidates), key=lambda l: (l.asset_id, l.treatment))
    fixed = sorted(tuple(f) for f in fixed)
    excluded = sorted(excluded)
    inputs_hash = hashlib.sha256(json.dumps(
        {"candidates": [l.model_dump() for l in lines], "envelope": envelope, "fixed": fixed, "excluded": excluded},
        sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()

    keys = [(l.asset_id, l.treatment) for l in lines]
    unknown = set(fixed) - set(keys)
    if unknown:
        raise ValueError(f"fixed lines are not candidates: {sorted(unknown)}")
    bridges = sorted({l.asset_id for l in lines})
    one_per_bridge = np.array([[float(l.asset_id == b) for l in lines] for b in bridges])
    res = milp(
        c=[-l.benefit for l in lines],
        integrality=np.ones(len(lines)),
        bounds=Bounds([float(k in fixed) for k in keys], [float(l.asset_id not in excluded) for l in lines]),
        constraints=[LinearConstraint(np.array([[l.cost for l in lines]]), ub=envelope),
                     LinearConstraint(one_per_bridge, ub=1.0)],
    )
    if res.status == _MILP_INFEASIBLE:
        return PlanResult(status=INFEASIBLE, objective=None, lines=[], inputs_hash=inputs_hash)
    if not res.success:
        raise RuntimeError(f"milp: {res.message}")
    chosen = [l for l, x in zip(lines, res.x) if x > 0.5]
    return PlanResult(status=OPTIMAL, objective=sum(l.benefit for l in chosen), lines=chosen, inputs_hash=inputs_hash)
