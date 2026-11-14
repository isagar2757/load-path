"""Programming agent: picks which line of the active plan to commit budget to next."""
from contracts import AGENT_IDS, BudgetStatus, ConditionStatus
from core.agents import Step

AGENT_ID = AGENT_IDS[2]
MODEL = "gemini-3.5-flash-lite"
SYSTEM = (
    "You are the programming agent of a bridge capital program. Your single decision: which one line of the "
    "approved plan gets its budget committed next. Criterion: the highest benefit per dollar; when that ties, "
    "the larger benefit. You do not change amounts, add lines or approve anything; a policy gate decides whether "
    "the commitment is allowed. Choose only from the numbered options. Name the bridge by its id. Never state "
    'amounts or numbers not shown in the options. Reply only with JSON {"choice": <option number>, "rationale": "<one or two sentences>"}.'
)
GOAL = "Commit one plan line: the highest benefit per dollar; when that ties, the larger benefit."
TOOL = "commit_budget"
COMMITTED = BudgetStatus.__args__[0]
PENDING = ConditionStatus.__args__[0]


def options(d, session_id: str, scope: list[str]) -> list[Step]:
    """Active-plan lines for bridges in scope with no committed line, ranked by benefit per dollar, then benefit.

    A line whose bridge has a pending reading depends on it, so rejecting the reading reverts the commitment.
    """
    plan = d.plans.find_one({"session_id": session_id, "superseded": False}, {"lines": 1}, sort=[("seq", -1)])
    if plan is None:
        return []
    committed = {b["asset_id"] for b in d.budget_ledger.find({"session_id": session_id, "status": COMMITTED},
                                                             {"asset_id": 1})}
    lines = [l for l in plan["lines"] if l["asset_id"] in scope and l["asset_id"] not in committed]
    out = []
    for l in sorted(lines, key=lambda l: (-round(l["benefit"] / l["cost"], 6), -l["benefit"], l["asset_id"])):
        pending = d.condition_records.find_one({"asset_id": l["asset_id"], "status": PENDING}, {"_id": 1})
        out.append(Step(
            TOOL, {"asset_id": l["asset_id"], "amount": l["cost"]},
            f"plan line {l['treatment']} for {l['asset_id']}: cost {l['cost']:,.2f}, benefit {l['benefit']:,.2f}, "
            f"benefit per dollar {l['benefit'] / l['cost']:.6f}"
            + (f"; depends on pending condition {pending['_id']}" if pending else ""),
            (pending["_id"],) if pending else ()))
    return out
