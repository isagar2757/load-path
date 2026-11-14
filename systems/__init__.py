"""Domain tools. `register()` puts them in the gate registry; undo names come from contracts.TOOLS."""
from contracts import TOOLS
from core import gate
from systems import budget, conditions, inspections, workorders

_TOOLS = {
    "commit_budget": (budget.commit_budget, budget.snapshot, budget.release_budget),
    "create_work_order": (workorders.create_work_order, workorders.snapshot, workorders.cancel_work_order),
    "propose_condition": (conditions.propose_condition, conditions.snapshot, conditions.withdraw_condition),
    "approve_condition": (conditions.approve_condition, conditions.decision_snapshot, None),
    "reject_condition": (conditions.reject_condition, conditions.decision_snapshot, None),
    "request_inspection": (inspections.request_inspection, inspections.snapshot, None),
}


def register() -> None:
    for name, (fn, snap, undo) in _TOOLS.items():
        gate.register_tool(name, fn, snap, undo, TOOLS[name].undo_tool)
