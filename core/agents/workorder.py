"""Work-order agent: opens the work order for a committed budget line that has none."""
from contracts import AGENT_IDS, BudgetStatus, WorkOrderStatus
from core.agents import Step

AGENT_ID = AGENT_IDS[3]
MODEL = "gemini-3.5-flash-lite"
SYSTEM = (
    "You are the work-order agent of a bridge capital program. Your single decision: which committed budget "
    "line gets its work order opened next. Criterion: the oldest commitment without a work order. You do not "
    "commit budget or change amounts; a policy gate decides whether the order is allowed. Choose only from the "
    "numbered options. Name the bridge by its id. Never state amounts or numbers not shown in the options. "
    'Reply only with JSON {"choice": <option number>, "rationale": "<one or two sentences>"}.'
)
GOAL = "Open the work order for the oldest committed budget line that has none."
TOOL = "create_work_order"
COMMITTED = BudgetStatus.__args__[0]
CANCELLED = WorkOrderStatus.__args__[2]


def options(d, session_id: str, scope: list[str]) -> list[Step]:
    """Committed lines of the session for bridges in scope with no live work order, oldest commitment first."""
    ordered = {w["budget_id"] for w in d.work_orders.find(
        {"session_id": session_id, "status": {"$ne": CANCELLED}}, {"budget_id": 1})}
    lines = [b for b in d.budget_ledger.find({"session_id": session_id, "status": COMMITTED,
                                              "asset_id": {"$in": list(scope)}}) if b["_id"] not in ordered]
    return [Step(TOOL, {"asset_id": b["asset_id"], "budget_id": b["_id"]},
                 f"work order for {b['asset_id']}: committed line {b['_id']}, amount {b['amount']:,.2f}, "
                 "has no work order", (b["_id"],))
            for b in sorted(lines, key=lambda b: int(b["_id"].rsplit(":", 1)[1]))]
