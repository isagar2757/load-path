"""Agents in scripted mode: the proposal is a fixed `Step`; the gate decides. Relay: docs/formulas.md section 6."""
from typing import NamedTuple

from contracts import ToolResult
from core import gate


class Step(NamedTuple):
    tool: str                      # the acting agent is contracts.TOOLS[tool].actor
    args: dict
    rationale: str
    handoff: dict[str, int] = {}   # arg name -> index of the earlier step whose `produced` id fills it


def act(d, task: dict) -> ToolResult:
    """The agent named on a claimed task submits the task's proposal through the gate."""
    proposal = task["input"]
    return gate.guarded_call(task["session_id"], task["agent_id"], task["type"], proposal["args"],
                             proposal["rationale"], depends_on=proposal["depends_on"], db=d)
