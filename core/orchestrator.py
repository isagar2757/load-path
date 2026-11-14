"""Task relay and stop watcher. Relay: docs/formulas.md section 6; session statuses: plan, section Contracts.

One worker queues a script step as a `tasks` document, claims it and lets the step's agent act through the gate.
A watcher thread polls the session; on `abort_requested` it waits for the tool call in flight, then rolls back.
On `reverting` it reverts the rejected condition's dependants and re-plans, then keeps watching; a failed undo
ends the session `failed` (a person decides).
"""
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime

from bson import ObjectId
from pymongo import ReturnDocument

import contracts
import db as dbmod
from core import agents, ledger, revert
from systems import plans

RUNNING, REVERTING, ABORT_REQUESTED, ROLLING_BACK, ROLLED_BACK, _, FAILED = contracts.SESSION_STATUS
QUEUED, CLAIMED, DONE, TASK_FAILED, _ = contracts.TaskStatus.__args__
SESSION_STARTED, _, _, _, ABORT_OBSERVED, _, SESSION_ENDED = contracts.EVENT_TYPES
*_, ACTOR = contracts.AGENT_IDS  # agent:orchestrator


def claim(d, session_id: str) -> dict | None:
    """Take the oldest queued task of the session in one atomic update, so two workers cannot take it."""
    return d.tasks.find_one_and_update({"session_id": session_id, "status": QUEUED}, {"$set": {"status": CLAIMED}},
                                       sort=[("_id", 1)], return_document=ReturnDocument.AFTER)


class Orchestrator:
    def __init__(self, session_id: str, db=None, poll: float = 0.1):
        self.d = db if db is not None else dbmod.get_db()
        self.sid, self.poll = session_id, poll
        self._oid = ObjectId(session_id)
        self._principal = self.d.sessions.find_one({"_id": self._oid})["principal_id"]
        self._lock = threading.Lock()  # held around a tool call and around the rollback
        self.watcher = threading.Thread(target=self._watch, daemon=True)

    def start(self) -> None:
        self._event(SESSION_STARTED)
        self.watcher.start()

    def _event(self, type_: str, **fields) -> None:
        ledger.append(self.sid, {"type": type_, "principal_id": self._principal, "actor_id": ACTOR, **fields},
                      db=self.d)

    def _status(self) -> str | None:
        """None when the session document is gone: the watcher and the relay both stop."""
        session = self.d.sessions.find_one({"_id": self._oid}, {"status": 1})
        return session and session["status"]

    def _move(self, old: str, new: str) -> dict | None:
        return self.d.sessions.find_one_and_update(
            {"_id": self._oid, "status": old}, {"$set": {"status": new, "updated_at": datetime.now(UTC)}})

    def _end(self, old: str, new: str, detail: dict) -> None:
        if self._move(old, new) is not None:
            self._event(SESSION_ENDED, after={"status": new, **detail})

    def _watch(self) -> None:
        while (status := self._status()) in (RUNNING, REVERTING):
            if status == REVERTING:
                with self._lock:
                    session = self.d.sessions.find_one({"_id": self._oid})
                    out = revert.revert_dependants(self.sid, session["revert_for"], db=self.d)
                    if out["failed"]:  # an undo failed: stop here, a person decides
                        self._end(REVERTING, FAILED, {"compensated": out["compensated"], "failed": out["failed"]})
                        return
                    plans.replan(self.sid, db=self.d)
                continue
            time.sleep(self.poll)
        if status != ABORT_REQUESTED:
            return
        with self._lock:  # a tool call in flight finishes and records `executed` first
            session = self._move(ABORT_REQUESTED, ROLLING_BACK)
            if session is None:
                return
            self._event(ABORT_OBSERVED, reason=f"stop requested by {session.get('aborted_by')}")
            out = revert.rollback_session(self.sid, db=self.d)
            self._end(ROLLING_BACK, FAILED if out["failed"] else ROLLED_BACK, out)

    def run(self, script: list[agents.Step]) -> Iterator[tuple[agents.Step, contracts.ToolResult]]:
        """Relay the script one task at a time, yielding each step with its gate result.

        A step whose handoff source produced nothing is not queued. The relay ends when the session is no
        longer `running`, and fails the session when a tool errors after an allow (no automatic retry of a write).
        """
        outputs: list[dict | None] = []
        for step in script:
            handed = {arg: (outputs[i] or {}).get("produced") for arg, i in step.handoff.items()}
            if None in handed.values():
                outputs.append(None)
                continue
            with self._lock:
                if self._status() != RUNNING:
                    return
                self.d.tasks.insert_one(contracts.Task(
                    session_id=self.sid, type=step.tool, agent_id=contracts.TOOLS[step.tool].actor, status=QUEUED,
                    input={"args": {**step.args, **handed}, "rationale": step.rationale,
                           "depends_on": list(handed.values())},
                    created_at=datetime.now(UTC)).model_dump())
                task = claim(self.d, self.sid)
                r = agents.act(self.d, task)
                self.d.tasks.update_one({"_id": task["_id"]}, {"$set": {
                    "status": TASK_FAILED if r.result is None else DONE, "output": r.result}})
                if r.allowed and r.result is None:
                    self._end(RUNNING, FAILED, {"reason": r.reason})
            outputs.append(r.result)
            yield step, r
