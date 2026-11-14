"""Control-surface HTTP API: SSE audit feed and session stop. Plan A1."""
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bson import ObjectId
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

import db as dbmod

WEB_DIR = Path(__file__).resolve().parent


class StopBody(BaseModel):
    aborted_by: str = Field(pattern=r"^(user|agent):[a-z0-9_]+$")


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

    def d():
        return database if database is not None else dbmod.get_db()

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
            with database.audit_events.watch(pipeline, full_document="updateLookup") as stream:
                for change in stream:
                    doc = change.get("fullDocument") or {}
                    payload = _jsonable(doc)
                    yield f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


app = create_app()
