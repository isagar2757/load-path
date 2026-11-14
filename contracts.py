"""Shared names and shapes between lanes. Locked at 11:10; change only when both agree.

Source: docs/superpowers/plans/2026-11-14-event-build.md, section Contracts.
Formulas: docs/formulas.md. Asset fields are added after the bridge file layout is read (task A4).
"""
from datetime import datetime
from typing import Any, Literal, NamedTuple

from pydantic import BaseModel, ConfigDict, Field

# Collections
CONTROL_COLLECTIONS = ("principals", "policies", "sessions", "tasks", "audit_events", "saga_stack")
DOMAIN_COLLECTIONS = (
    "assets", "condition_records", "plans", "program_lines",
    "budget_ledger", "work_orders", "inspection_requests",
)
DB_NAME = "capital"
TEST_DB_NAME = "capital_test"

# Tools
class Tool(NamedTuple):
    actor: str               # principal id, or "human:owner" for a human with role owner in the asset's region
    undo_tool: str | None
    stage: int


TOOLS: dict[str, Tool] = {
    "propose_condition": Tool("agent:intake", "withdraw_condition", 3),
    "approve_condition": Tool("human:owner", None, 3),
    "reject_condition": Tool("human:owner", None, 3),
    "propose_plan": Tool("agent:planner", "supersede_plan", 4),
    "commit_budget": Tool("agent:programming", "release_budget", 2),
    "create_work_order": Tool("agent:workorder", "cancel_work_order", 2),
    "request_inspection": Tool("agent:orchestrator", None, 3),
}
AGENT_IDS = ("agent:intake", "agent:planner", "agent:programming", "agent:workorder", "agent:orchestrator")

# Tool function shape (lane B provides, lane A calls):
#   fn(db, args: dict) -> dict            result includes "produced": the _id it wrote
#   snapshot(db, args) -> dict | None
#   undo(db, undo_args: dict) -> dict     idempotent

# Enumerations
CheckName = Literal["role", "spend_limit", "envelope", "jurisdiction", "has_commitment", "in_approved_plan"]
CHECK_NAMES: tuple[str, ...] = CheckName.__args__
SessionStatus = Literal[
    "running", "reverting", "abort_requested", "rolling_back", "rolled_back", "completed", "failed",
]
SESSION_STATUS: tuple[str, ...] = SessionStatus.__args__
TaskStatus = Literal["queued", "claimed", "done", "failed", "cancelled"]
EventType = Literal[
    "session_started", "decision", "executed", "failed", "abort_observed", "compensated", "session_ended",
]
EVENT_TYPES: tuple[str, ...] = EventType.__args__
SagaState = Literal["armed", "done", "compensated", "comp_failed"]
ConditionStatus = Literal["pending", "approved", "rejected"]
BudgetStatus = Literal["committed", "released"]
WorkOrderStatus = Literal["draft", "released", "cancelled"]
PolicyStatus = Literal["active", "retired"]

GENESIS_HASH = "0" * 64  # prev_hash of the first event; see docs/formulas.md section 2


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# Control collections ($jsonSchema with additionalProperties: false)
class Principal(_Strict):
    id: str = Field(alias="_id", pattern=r"^(user|agent):[a-z0-9_]+$")
    kind: Literal["human", "agent"]
    roles: list[str]
    region: str
    spend_limit: float
    active: bool


class PolicyCheck(_Strict):
    name: CheckName
    params: dict[str, Any] = {}


class Policy(_Strict):
    tool: str
    version: int
    status: PolicyStatus
    roles: list[str]
    checks: list[PolicyCheck]
    author: str
    created_at: datetime


class Session(_Strict):
    principal_id: str
    task: str
    region: str
    budget_envelope: float
    status: SessionStatus
    revert_for: str | None = None
    aborted_by: str | None = None
    audit_head: str = GENESIS_HASH
    created_at: datetime
    updated_at: datetime


class Task(_Strict):
    session_id: str
    type: str
    agent_id: str
    status: TaskStatus
    input: dict[str, Any] = {}
    output: dict[str, Any] | None = None
    created_at: datetime


class AuditEvent(_Strict):
    session_id: str
    seq: int
    ts: datetime
    type: EventType
    principal_id: str
    actor_id: str
    tool: str | None = None
    args: dict[str, Any] | None = None
    policy_id: str | None = None
    policy_version: int | None = None
    decision: Literal["allow", "deny"] | None = None
    reason: str | None = None
    rationale: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    depends_on: list[str] = []
    prev_hash: str
    hash: str


class SagaEntry(_Strict):
    session_id: str
    seq: int
    tool: str
    undo_tool: str | None
    undo_args: dict[str, Any]
    produced: str | None = None
    depends_on: list[str] = []
    state: SagaState


# Domain: assets (task A4). One Ontario bridge; `_id` is "ID (SITE N°)".
class Asset(_Strict):
    id: str = Field(alias="_id")
    region: str
    county: str                  # COUNTY
    year_built: int              # YEAR BUILT
    deck_area: float             # DECK / CULVERTS LENGTH (m) x WIDTH TOTAL (m), m2


class ConditionRecord(_Strict):
    asset_id: str
    rating: float                # CURRENT BCI, 0-100
    year: int                    # year of LAST INSPECTION DATE
    status: ConditionStatus


# Return shapes
class ToolResult(_Strict):
    allowed: bool
    reason: str | None
    result: dict[str, Any] | None
    seq: int | None


class PlanLine(_Strict):
    asset_id: str
    treatment: str
    cost: float
    benefit: float


class PlanResult(_Strict):
    status: str
    objective: float | None
    lines: list[PlanLine]
    inputs_hash: str


# Indexes (setup_db.py creates them): (collection, keys, options)
INDEXES = [
    ("audit_events", [("session_id", 1), ("seq", 1)], {"unique": True}),
    ("saga_stack", [("session_id", 1), ("seq", 1)], {"unique": True}),
    ("policies", [("tool", 1), ("version", 1)], {"unique": True}),
    ("policies", [("tool", 1)], {"unique": True, "partialFilterExpression": {"status": "active"},
                                 "name": "one_active_per_tool"}),
    ("tasks", [("session_id", 1), ("status", 1)], {}),
]
