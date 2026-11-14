"""A1: SSE audit feed and session stop. Plan Stage 1."""
import json
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from bson import ObjectId
from starlette.testclient import TestClient

import contracts
import db

needs_atlas = pytest.mark.skipif(not db.mongo_uri(required=False), reason="MONGODB_URI not set")


@pytest.fixture
def tdb():
    if not db.mongo_uri(required=False):
        pytest.skip("MONGODB_URI not set")
    d = db.get_db(f"{contracts.TEST_DB_NAME}_{uuid.uuid4().hex[:8]}")
    d.client.drop_database(d.name)
    for coll, keys, opts in contracts.INDEXES:
        d[coll].create_index(keys, **opts)
    yield d
    d.client.drop_database(d.name)


@pytest.fixture
def session_id(tdb):
    now = datetime.now(UTC)
    return str(tdb.sessions.insert_one(contracts.Session(
        principal_id="user:owner_a", task="demo", region="r1", budget_envelope=100.0,
        status="running", created_at=now, updated_at=now,
    ).model_dump()).inserted_id)


@needs_atlas
def test_stop_sets_abort_requested(tdb, session_id):
    from web.server import create_app

    client = TestClient(create_app(database=tdb))
    r = client.post(f"/sessions/{session_id}/stop", json={"aborted_by": "user:owner_a"})
    assert r.status_code == 200
    doc = tdb.sessions.find_one({"_id": ObjectId(session_id)})
    assert doc["status"] == "abort_requested"
    assert doc["aborted_by"] == "user:owner_a"


@needs_atlas
def test_events_streams_audit_insert(tdb, session_id):
    from web.server import create_app

    client = TestClient(create_app(database=tdb))
    received = []

    def read_stream():
        with client.stream("GET", f"/events?session_id={session_id}") as resp:
            assert resp.status_code == 200
            for line in resp.iter_lines():
                if line.startswith("data: "):
                    received.append(json.loads(line.removeprefix("data: ")))
                    break

    t = threading.Thread(target=read_stream, daemon=True)
    t.start()
    time.sleep(0.4)
    tdb.audit_events.insert_one({
        "session_id": session_id, "seq": 1, "ts": datetime.now(UTC),
        "type": "session_started", "principal_id": "user:owner_a",
        "actor_id": "user:owner_a", "tool": None, "args": None,
        "policy_id": None, "policy_version": None, "decision": None,
        "reason": None, "rationale": None, "before": None, "after": None,
        "depends_on": [], "prev_hash": contracts.GENESIS_HASH, "hash": "a" * 64,
    })
    t.join(timeout=5)
    assert received, "no SSE event within 5 s"
    assert received[0]["session_id"] == session_id
    assert received[0]["seq"] == 1
    assert received[0]["type"] == "session_started"


def test_index_is_control_surface():
    html = (Path(__file__).resolve().parents[2] / "web" / "index.html").read_text()
    assert "EventSource" in html
    assert "/events" in html
    assert "/sessions/" in html
    assert "stop" in html.lower()
