"""L1: an LLM picks one code-built option and writes the rationale; tool and args never come from model text."""
import json

import pytest

from core import agents
from core.agents import Step

OPTIONS = [
    Step("commit_budget", {"asset_id": "b1", "amount": 30.0}, "commit 30 to asset b1"),
    Step("commit_budget", {"asset_id": "b2", "amount": 40.0}, "commit 40 to asset b2"),
    Step("create_work_order", {"asset_id": "b1"}, "work order for b1", {"budget_id": 0}),
]


@pytest.mark.parametrize("reply", [
    None,
    "not json",
    json.dumps({"choice": 7, "rationale": "x"}),
    json.dumps({"choice": -1, "rationale": "x"}),
    json.dumps({"choice": "1", "rationale": "x"}),
    json.dumps({"choice": 1.0, "rationale": "x"}),
    json.dumps({"choice": True, "rationale": "x"}),
    json.dumps({"choice": 0, "rationale": ""}),
    json.dumps({"choice": 0, "rationale": 5}),
    json.dumps([0, "x"]),
])
def test_choose_falls_back_to_default_on_invalid_reply(monkeypatch, reply):
    monkeypatch.setattr(agents, "llm", lambda prompt: reply)
    assert agents.choose("agent:programming", "fund the riskiest asset", OPTIONS, default=1) == OPTIONS[1]


def test_choose_never_takes_tool_or_args_from_model(monkeypatch):
    reply = json.dumps({"choice": 2, "rationale": "b1 is funded; open its work order.",
                        "tool": "delete_everything", "args": {"asset_id": "zz"}, "amount": 1e9})
    monkeypatch.setattr(agents, "llm", lambda prompt: reply)
    got = agents.choose("agent:workorder", "start work", OPTIONS)
    assert (got.tool, got.args, got.handoff) == (OPTIONS[2].tool, OPTIONS[2].args, OPTIONS[2].handoff)
    assert got.rationale == "b1 is funded; open its work order."


def test_llm_returns_none_without_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setattr(agents, "ENV_FILE", agents.ENV_FILE.with_name("no-such.env"))
    assert agents.llm("hello") is None


@pytest.mark.skipif(not agents.api_key(), reason="LLM_API_KEY not set")
def test_choose_live_picks_listed_option():
    before = agents.USAGE["calls"]
    got = agents.choose("agent:programming", "Commit budget to the asset with the higher risk score (b2).",
                        OPTIONS[:2])
    assert (got.tool, got.args) in [(o.tool, o.args) for o in OPTIONS[:2]]
    assert isinstance(got.rationale, str) and got.rationale.strip()
    assert agents.USAGE["calls"] == before + 1
