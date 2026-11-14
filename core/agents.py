"""Agents: scripted mode replays a fixed `Step`; LLM mode picks one code-built `Step` and writes the rationale.
The gate decides either way. Relay: docs/formulas.md section 6."""
import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import NamedTuple

import certifi

from contracts import ToolResult
from core import gate

LLM_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent"
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
TLS = ssl.create_default_context(cafile=certifi.where())   # same CA bundle as the Mongo client
USAGE = {"calls": 0, "tokens": 0}   # live calls and total tokens since import; the demo prints it


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


def api_key() -> str | None:
    """LLM_API_KEY from the environment, else from ./.env."""
    v = os.environ.get("LLM_API_KEY")
    if not v and ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("LLM_API_KEY="):
                v = line.split("=", 1)[1].strip().strip("\"'")
    return v or None


def llm(prompt: str) -> str | None:
    """One JSON-mode completion; None when the key is missing, the call fails or the reply is empty."""
    key = api_key()
    if not key:
        return None
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": 300, "responseMimeType": "application/json"}}
    req = urllib.request.Request(LLM_URL, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=15, context=TLS) as resp:
            out = json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None
    USAGE["calls"] += 1
    USAGE["tokens"] += out.get("usageMetadata", {}).get("totalTokenCount", 0)
    try:
        return out["candidates"][0]["content"]["parts"][0]["text"] or None
    except (KeyError, IndexError, TypeError):
        return None


def choose(agent_id: str, goal: str, options: list[Step], default: int = 0) -> Step:
    """The LLM picks one listed option and writes its rationale; any invalid reply returns options[default]."""
    role = agent_id.split(":", 1)[-1]
    listed = "\n".join(f"{i}. tool={o.tool} args={json.dumps(o.args)} : {o.rationale}" for i, o in enumerate(options))
    prompt = (f"You are the {role} agent. Goal: {goal}\nAllowed options:\n{listed}\n"
              'Pick exactly one option by its number. Reply only with JSON '
              '{"choice": <number>, "rationale": "<one or two sentences>"}.')
    try:
        reply = json.loads(llm(prompt) or "")
    except json.JSONDecodeError:
        return options[default]
    if not isinstance(reply, dict):
        return options[default]
    i, why = reply.get("choice"), reply.get("rationale")
    if type(i) is not int or not 0 <= i < len(options) or not isinstance(why, str) or not why.strip():
        return options[default]
    return options[i]._replace(rationale=why.strip())
