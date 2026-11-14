"""Intake agent: proposes a condition reading for a bridge. Scripted: the readings are MOCK input (README)."""
from contracts import AGENT_IDS, ConditionStatus
from core.agents import Step

AGENT_ID = AGENT_IDS[0]
MODEL = None   # never sent to a model: the rationale carries the MOCK label and must reach the ledger unchanged
SYSTEM = "Intake agent. Scripted: proposes the code-built MOCK reading; no model call."
GOAL = "Propose one condition reading for a bridge in scope that has none in this session."
TOOL = "propose_condition"
APPROVED = ConditionStatus.__args__[1]
MOCK_YEAR = 2026   # mock: the proposed readings are not in the source file
MOCK_DROP = 5.0    # mock: proposed rating = newest published rating minus this


def options(d, session_id: str, scope: list[str]) -> list[Step]:
    """One MOCK reading per bridge in scope with no reading proposed in this session, by asset id."""
    out = []
    for asset in sorted(scope):
        if d.condition_records.find_one({"asset_id": asset, "_id": {"$regex": f"^{session_id}:"}}, {"_id": 1}):
            continue
        newest = d.condition_records.find_one({"asset_id": asset, "status": APPROVED}, sort=[("year", -1)])
        if newest is None:
            continue
        rating = round(newest["rating"] - MOCK_DROP, 2)
        out.append(Step(TOOL, {"asset_id": asset, "rating": rating, "year": MOCK_YEAR},
                        f"MOCK reading for the demo: {rating} in {MOCK_YEAR} "
                        f"(published {newest['rating']} in {newest['year']})"))
    return out
