"""Planner agent: asks for the session's plan to be solved when an approval has made the active plan stale."""
from contracts import AGENT_IDS
from core.agents import Step

AGENT_ID = AGENT_IDS[1]
MODEL = "gemini-3.5-flash-lite"
SYSTEM = (
    "You are the planner agent of a bridge capital program. Your single decision: whether to ask for the "
    "treatment plan to be solved now. Criterion: the plan is solved when there is no active plan or an owner "
    "approval is newer than it. You do not solve the plan, pick treatments or compute amounts; code does. "
    "Choose only from the numbered options. Never state amounts or numbers not shown in the options. "
    'Reply only with JSON {"choice": <option number>, "rationale": "<one or two sentences>"}.'
)
GOAL = "Solve the treatment plan from the approved condition records when the active plan is stale."
TOOL = "propose_plan"
APPROVE = "approve_condition"


def options(d, session_id: str, scope: list[str]) -> list[Step]:
    """`propose_plan` when the session has no active plan or an executed approval has a higher seq than it."""
    plan = d.plans.find_one({"session_id": session_id, "superseded": False}, {"seq": 1}, sort=[("seq", -1)])
    if plan is None:
        return [Step(TOOL, {}, "no active plan for the session: solve one from the approved condition records")]
    approval = d.audit_events.find_one({"session_id": session_id, "type": "executed", "tool": APPROVE},
                                       {"seq": 1}, sort=[("seq", -1)])
    if approval is None or approval["seq"] < plan["seq"]:
        return []
    return [Step(TOOL, {}, f"approval at seq {approval['seq']} is newer than the active plan at seq {plan['seq']}: "
                           "re-solve from the approved condition records")]
