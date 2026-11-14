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


# A5: pending conditions, approve, reject-with-reason. Plan Stage 3.
CID = "b1:2026"


@pytest.fixture
def conditions_world(world):
    """`world` plus assets in two regions, one pending record each, and policies for the two human tools."""
    d, sid = world
    now = datetime.now(UTC)
    d.assets.insert_many([{"_id": "b1", "region": "r1"}, {"_id": "b9", "region": "r2"}])
    d.condition_records.insert_many([
        {"_id": CID, "asset_id": "b1", "rating": 62.0, "year": 2026, "status": "pending"},
        {"_id": "b1:2025", "asset_id": "b1", "rating": 70.0, "year": 2025, "status": "approved"},
        {"_id": "b9:2026", "asset_id": "b9", "rating": 40.0, "year": 2026, "status": "pending"},
    ])
    d.policies.insert_many([contracts.Policy(
        tool=tool, version=1, status="active", roles=["owner"],
        checks=[contracts.PolicyCheck(name="role")], author="user:owner_a", created_at=now,
    ).model_dump() for tool in ("approve_condition", "reject_condition")])
    from web.server import create_app
    return d, sid, TestClient(create_app(database=d))


def _condition(d, cid=CID):
    return d.condition_records.find_one({"_id": cid})["status"]


def _session(d, sid):
    return d.sessions.find_one({"_id": ObjectId(sid)})


def test_pending_conditions_for_session_region(conditions_world):
    d, sid, client = conditions_world
    r = client.get(f"/sessions/{sid}/conditions")
    assert r.status_code == 200
    assert r.json() == [{"_id": CID, "asset_id": "b1", "rating": 62.0, "year": 2026, "status": "pending"}]


def test_approve_goes_through_gate(conditions_world):
    d, sid, client = conditions_world
    r = client.post(f"/sessions/{sid}/conditions/approve", json={"actor_id": "user:owner_a", "condition_id": CID})
    assert r.status_code == 200
    assert _condition(d) == "approved"
    assert _session(d, sid)["status"] == "running"
    ev = d.audit_events.find_one({"session_id": sid, "type": "executed"})
    assert (ev["tool"], ev["actor_id"]) == ("approve_condition", "user:owner_a")


def test_reject_sets_reverting(conditions_world):
    d, sid, client = conditions_world
    r = client.post(f"/sessions/{sid}/conditions/reject",
                    json={"actor_id": "user:owner_a", "condition_id": CID, "reason": "rating disputed"})
    assert r.status_code == 200
    assert _condition(d) == "rejected"
    s = _session(d, sid)
    assert (s["status"], s["revert_for"]) == ("reverting", CID)
    ev = d.audit_events.find_one({"session_id": sid, "type": "decision"})
    assert ev["args"]["reason"] == "rating disputed"


@pytest.mark.parametrize("body", [{}, {"reason": ""}, {"reason": "  "}])
def test_reject_without_reason_refused(conditions_world, body):
    d, sid, client = conditions_world
    r = client.post(f"/sessions/{sid}/conditions/reject",
                    json={"actor_id": "user:owner_a", "condition_id": CID, **body})
    assert r.status_code == 422
    assert _condition(d) == "pending"
    assert _session(d, sid)["status"] == "running"
    assert d.audit_events.count_documents({}) == 0


def test_agent_reject_denied_and_session_keeps_running(conditions_world):
    d, sid, client = conditions_world
    r = client.post(f"/sessions/{sid}/conditions/reject",
                    json={"actor_id": "agent:intake", "condition_id": CID, "reason": "x"})
    assert r.status_code == 403
    assert _condition(d) == "pending"
    s = _session(d, sid)
    assert (s["status"], s["revert_for"]) == ("running", None)


def test_reject_already_decided_does_not_revert(conditions_world):
    d, sid, client = conditions_world
    r = client.post(f"/sessions/{sid}/conditions/reject",
                    json={"actor_id": "user:owner_a", "condition_id": "b1:2025", "reason": "late"})
    assert r.status_code == 409
    assert _condition(d, "b1:2025") == "approved"
    assert _session(d, sid)["status"] == "running"


def test_index_has_condition_controls():
    html = (Path(__file__).resolve().parents[2] / "web" / "index.html").read_text()
    assert "/conditions" in html
    assert 'decide("approve"' in html
    assert 'decide("reject"' in html


# A8: actor picker. The chosen actor is sent with every action; the gate decides, not the page.
def test_index_has_actor_picker():
    html = (Path(__file__).resolve().parents[2] / "web" / "index.html").read_text()
    assert 'id="actor"' in html
    assert 'value="user:owner_a"' in html
    assert 'value="user:engineer_b"' in html
    assert 'get("actor")' in html


@needs_atlas
def test_engineer_approve_denied_and_logged(conditions_world):
    d, sid, client = conditions_world
    d.principals.insert_one(contracts.Principal(
        id="user:engineer_b", kind="human", roles=["engineer"], region="r1",
        spend_limit=0, active=True).model_dump(by_alias=True))
    r = client.post(f"/sessions/{sid}/conditions/approve",
                    json={"actor_id": "user:engineer_b", "condition_id": CID})
    assert r.status_code == 403
    assert _condition(d) == "pending"
    ev = d.audit_events.find_one({"session_id": sid, "type": "decision"})
    assert (ev["decision"], ev["actor_id"], ev["tool"]) == ("deny", "user:engineer_b", "approve_condition")


@needs_atlas
@pytest.mark.parametrize("body", [{}, {"actor_id": ""}, {"actor_id": "user:ghost"}])
def test_missing_or_unknown_actor_never_approves(conditions_world, body):
    d, sid, client = conditions_world
    r = client.post(f"/sessions/{sid}/conditions/approve", json={"condition_id": CID, **body})
    assert r.status_code in (403, 422)
    assert _condition(d) == "pending"
