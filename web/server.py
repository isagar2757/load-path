"""Control-surface HTTP API: SSE audit feed, session stop (A1), condition approve/reject (A5), demo pause cue."""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bson import ObjectId
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

import contracts
import db as dbmod
import systems
from core import gate

WEB_DIR = Path(__file__).resolve().parent


PRINCIPAL_ID = r"^(user|agent):[a-z0-9_]+$"
STATUS_PENDING = contracts.ConditionStatus.__args__[0]


class StopBody(BaseModel):
    aborted_by: str = Field(pattern=PRINCIPAL_ID)


class ApproveBody(BaseModel):
    actor_id: str = Field(pattern=PRINCIPAL_ID)
    condition_id: str = Field(min_length=1)


class RejectBody(ApproveBody):
    reason: str = Field(pattern=r"\S")


class PauseBody(BaseModel):
    cue: str = Field(pattern=r"\S", max_length=200)


def _jsonable(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def create_app(database=None) -> FastAPI:
    app = FastAPI()
    systems.register()

    def d():
        return database if database is not None else dbmod.get_db()

    # Demo pacing only: session id -> the cue `run_demo.py --pause page` waits on. In memory, no domain write,
    # so it does not go through the gate and is not in the ledger.
    waiting: dict[str, str] = {}

    @app.put("/sessions/{session_id}/pause")
    def set_pause(session_id: str, body: PauseBody):
        waiting[session_id] = body.cue
        return {"cue": body.cue}

    @app.get("/sessions/{session_id}/pause")
    def get_pause(session_id: str):
        return {"cue": waiting.get(session_id)}

    @app.delete("/sessions/{session_id}/pause")
    def clear_pause(session_id: str):
        waiting.pop(session_id, None)
        return {"cue": None}

    @app.get("/")
    def index():
        return FileResponse(WEB_DIR / "index.html")

    @app.post("/sessions/{session_id}/stop")
    def stop_session(session_id: str, body: StopBody):
        if not ObjectId.is_valid(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        now = datetime.now(UTC)
        result = d().sessions.update_one(
            {"_id": ObjectId(session_id), "status": "running"},
            {"$set": {
                "status": "abort_requested",
                "aborted_by": body.aborted_by,
                "updated_at": now,
            }},
        )
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="session not found or not running")
        return {"status": "abort_requested", "aborted_by": body.aborted_by}

    def session(session_id: str) -> dict:
        doc = d().sessions.find_one({"_id": ObjectId(session_id)}) if ObjectId.is_valid(session_id) else None
        if doc is None:
            raise HTTPException(status_code=404, detail="session not found")
        return doc

    def decide(session_id: str, tool: str, body: ApproveBody) -> contracts.ToolResult:
        session(session_id)
        rec = d().condition_records.find_one({"_id": body.condition_id}, {"asset_id": 1})
        if rec is None:
            raise HTTPException(status_code=404, detail="condition not found")
        # asset_id comes from the record, so the jurisdiction check reads the condition's real asset.
        args = {**body.model_dump(exclude={"actor_id"}), "asset_id": rec["asset_id"]}
        res = gate.guarded_call(session_id, body.actor_id, tool, args, None, db=d())
        if not res.allowed:
            raise HTTPException(status_code=403, detail=res.reason)
        if res.result is None:
            raise HTTPException(status_code=409, detail=res.reason)
        return res

    @app.get("/sessions/{session_id}/conditions")
    def pending_conditions(session_id: str):
        region = session(session_id)["region"]
        asset_ids = d().assets.distinct("_id", {"region": region})
        return list(d().condition_records.find({"status": STATUS_PENDING, "asset_id": {"$in": asset_ids}})
                    .sort("_id", 1))

    @app.get("/sessions/{session_id}/state")
    def session_state(session_id: str):
        doc = session(session_id)
        by_session = {"session_id": session_id}
        plan = d().plans.find_one({**by_session, "superseded": False}, sort=[("seq", -1)])
        if plan is not None:
            plan["total_cost"] = sum(line["cost"] for line in plan["lines"])
        return {
            "session": {"status": doc["status"], "budget_envelope": doc["budget_envelope"]},
            "plan": plan,
            "budget": list(d().budget_ledger.find(by_session).sort("_id", 1)),
            "work_orders": list(d().work_orders.find(by_session).sort("_id", 1)),
            # Inspection requests carry no session_id; their _id is the gate key "<session_id>:<seq>".
            "inspections": list(d().inspection_requests.find({"_id": {"$regex": f"^{re.escape(session_id)}:"}})
                                .sort("_id", 1)),
        }

    @app.post("/sessions/{session_id}/conditions/approve")
    def approve_condition(session_id: str, body: ApproveBody):
        return decide(session_id, "approve_condition", body)

    @app.post("/sessions/{session_id}/conditions/reject")
    def reject_condition(session_id: str, body: RejectBody):
        res = decide(session_id, "reject_condition", body)
        d().sessions.update_one(
            {"_id": ObjectId(session_id), "status": "running"},
            {"$set": {"status": "reverting", "revert_for": body.condition_id, "updated_at": datetime.now(UTC)}},
        )
        return res

    @app.get("/events")
    def events(session_id: str):
        database = d()

        def gen():
            pipeline = [{
                "$match": {
                    "operationType": "insert",
                    "fullDocument.session_id": session_id,
                },
            }]
            def frame(doc: dict) -> str:
                return f"data: {json.dumps(_jsonable(doc), separators=(',', ':'))}\n\n"

            # The stream opens before the replay, so no event falls between them; `sent` drops the overlap.
            with database.audit_events.watch(pipeline, full_document="updateLookup") as stream:
                sent = 0
                for doc in database.audit_events.find({"session_id": session_id}).sort("seq", 1):
                    sent = doc["seq"]
                    yield frame(doc)
                for change in stream:
                    doc = change.get("fullDocument") or {}
                    if doc.get("seq", sent + 1) > sent:
                        yield frame(doc)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


app = create_app()
