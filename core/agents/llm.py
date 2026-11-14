"""One JSON-mode Gemini completion behind a timeout and per-run call and token caps. Stdlib HTTP only."""
import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path

import certifi

URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
TLS = ssl.create_default_context(cafile=certifi.where())   # same CA bundle as the Mongo client
TIMEOUT = 10.0               # seconds per call
MAX_OUTPUT_TOKENS = 300
MAX_CALLS_PER_RUN = 30       # per process; the demo makes 5
MAX_TOKENS_PER_RUN = 30_000
# Live calls and total tokens since import; `choose` counts fallbacks and fills by_agent:
# {agent_id: {"calls", "tokens", "fallbacks": {cause: n}}}. The demo prints it.
USAGE = {"calls": 0, "tokens": 0, "fallbacks": 0, "by_agent": {}}
last_cause: str | None = None   # why the last `complete` returned None


def api_key() -> str | None:
    """LLM_API_KEY from the environment, else from ./.env."""
    v = os.environ.get("LLM_API_KEY")
    if not v and ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith("LLM_API_KEY="):
                v = line.split("=", 1)[1].strip().strip("\"'")
    return v or None


def _miss(cause: str) -> None:
    global last_cause
    last_cause = cause


def complete(model: str, system: str, prompt: str) -> str | None:
    """The reply text, or None (cause in `last_cause`): no key, over a cap, failed or timed-out call, empty reply."""
    _miss(None)
    key = api_key()
    if not key:
        return _miss("no_key")
    if USAGE["calls"] >= MAX_CALLS_PER_RUN or USAGE["tokens"] >= MAX_TOKENS_PER_RUN:
        return _miss("cap")
    body = {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": MAX_OUTPUT_TOKENS, "responseMimeType": "application/json"}}
    req = urllib.request.Request(URL.format(model=model), data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=TLS) as resp:
            out = json.load(resp)
    except TimeoutError:
        return _miss("timeout")
    except (urllib.error.URLError, json.JSONDecodeError):
        return _miss("http")
    USAGE["calls"] += 1
    USAGE["tokens"] += out.get("usageMetadata", {}).get("totalTokenCount", 0)
    try:
        return out["candidates"][0]["content"]["parts"][0]["text"] or _miss("empty")
    except (KeyError, IndexError, TypeError):
        return _miss("empty")
