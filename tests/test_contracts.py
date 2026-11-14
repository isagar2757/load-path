import pytest
from pydantic import ValidationError

import contracts as c


def test_collection_names():
    assert c.CONTROL_COLLECTIONS == (
        "principals", "policies", "sessions", "tasks", "audit_events", "saga_stack",
    )
    assert c.DOMAIN_COLLECTIONS == (
        "assets", "condition_records", "plans", "program_lines",
        "budget_ledger", "work_orders", "inspection_requests",
    )


def test_tool_table_matches_plan():
    assert c.TOOLS["commit_budget"].actor == "agent:programming"
    assert c.TOOLS["commit_budget"].undo_tool == "release_budget"
    assert c.TOOLS["approve_condition"].undo_tool is None
    assert c.TOOLS["request_inspection"].actor == "agent:orchestrator"
    assert {n for n, t in c.TOOLS.items() if t.stage == 2} == {"commit_budget", "create_work_order"}


def test_principal_requires_kind():
    with pytest.raises(ValidationError):
        c.Principal(id="user:owner_a", roles=["owner"], region="r1", spend_limit=100, active=True)


def test_principal_id_prefix_enforced():
    with pytest.raises(ValidationError):
        c.Principal(id="owner_a", kind="human", roles=[], region="r1", spend_limit=0, active=True)


def test_extra_fields_rejected_on_control_shapes():
    with pytest.raises(ValidationError):
        c.Principal(id="agent:intake", kind="agent", roles=[], region="r1",
                    spend_limit=0, active=True, colour="red")


def test_genesis_hash_is_64_zeros():
    assert c.GENESIS_HASH == "0" * 64


def test_tool_result_shape():
    r = c.ToolResult(allowed=False, reason="role", result=None, seq=3)
    assert r.model_dump() == {"allowed": False, "reason": "role", "result": None, "seq": 3}


def test_session_status_values():
    assert set(c.SESSION_STATUS) == {
        "running", "reverting", "abort_requested", "rolling_back",
        "rolled_back", "completed", "failed",
    }


def test_policy_check_names():
    assert set(c.CHECK_NAMES) == {
        "role", "spend_limit", "envelope", "jurisdiction", "has_commitment", "in_approved_plan", "has_reason",
    }
    with pytest.raises(ValidationError):
        c.PolicyCheck(name="vibes", params={})
