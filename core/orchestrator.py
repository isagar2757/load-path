"""Task relay and stop watcher. Relay: docs/formulas.md section 6; session statuses: plan, section Contracts.

A turn loop asks each agent for its next step, queues it as a `tasks` document, claims it and lets the agent act
through the gate.
A watcher thread polls the session; on `abort_requested` it waits for the tool call in flight, then rolls back.
On `reverting` it reverts the rejected condition's dependants and re-plans, then keeps watching; a failed undo or
a denied or failed re-plan ends the session `failed` (a person decides).
"""
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime

from bson import ObjectId
from pymongo import ReturnDocument

import contracts
import db as dbmod
from core import agents, gate, ledger, revert
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

    def _end(self, old: str, new: str, detail: dict) -> bool:
        """Move the session from `old` to `new` and record it; False when it was no longer `old`."""
        if self._move(old, new) is None:
            return False
        self._event(SESSION_ENDED, after={"status": new, **detail})
        return True

    def _watch(self) -> None:
        while (status := self._status()) in (RUNNING, REVERTING):
            if status == REVERTING:
                with self._lock:
                    session = self.d.sessions.find_one({"_id": self._oid})
                    out = revert.revert_dependants(self.sid, session["revert_for"], db=self.d)
                    if out["failed"]:  # an undo failed: stop here, a person decides
                        self._end(REVERTING, FAILED, {"compensated": out["compensated"], "failed": out["failed"]})
                        return
                    r = plans.replan(self.sid, db=self.d)
                    # No new plan: do not run on the old one. A stop requested meanwhile is left to the rollback.
                    if r.result is None and self._end(RUNNING, FAILED, {"reason": f"re-plan: {r.reason}"}):
                        return
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

    def _act(self, step: agents.Step, meta: dict | None) -> contracts.ToolResult:
        """Caller holds the lock. Queue the step as a task, claim it, act through the gate, record the result."""
        self.d.tasks.insert_one(contracts.Task(
            session_id=self.sid, type=step.tool, agent_id=contracts.TOOLS[step.tool].actor, status=QUEUED,
            input={"args": step.args, "rationale": step.rationale, "depends_on": list(step.depends_on),
                   **(meta or {})},
            created_at=datetime.now(UTC)).model_dump())
        task = claim(self.d, self.sid)
        r = agents.act(self.d, task)
        self.d.tasks.update_one({"_id": task["_id"]}, {"$set": {
            "status": TASK_FAILED if r.result is None else DONE, "output": r.result}})
        if r.allowed and r.result is None:   # tool error after an allow: no automatic retry of a write
            self._end(RUNNING, FAILED, {"reason": r.reason})
        return r

    def submit(self, step: agents.Step) -> contracts.ToolResult | None:
        """Send one step through the gate as a task. None when the session is not `running`."""
        with self._lock:
            return self._act(step, None) if self._status() == RUNNING else None

    def run_agents(self, agent_modules: list, scope: list[str], use_llm: bool,
                   max_rounds: int) -> Iterator[tuple[agents.Step, dict, contracts.ToolResult]]:
        """Turn loop: each round asks each agent in order for one step and submits it, yielding (step, meta, result).

        How the step was chosen (`meta`) is stored in the task input. A turn waits while a rejection is being
        reverted. A person may act while an agent chooses, so the step is submitted only if the agent still
        offers it once the lock is held; otherwise it is dropped and the loop goes on.
        Ends when a round passes with no agent offering a step, the session is not `running`, a step is denied
        by policy or fails (a person decides), or `max_rounds` is reached.
        """
        for _ in range(max_rounds):
            idle = True
            for agent in agent_modules:
                while (status := self._status()) == REVERTING:
                    time.sleep(self.poll)
                if status != RUNNING:
                    return
                step, meta = agents.choose(agent, self.d, self.sid, scope, use_llm)
                if step is None:
                    continue
                idle = False
                with self._lock:
                    if self._status() != RUNNING or not any(
                            (o.tool, o.args, o.depends_on) == (step.tool, step.args, step.depends_on)
                            for o in agent.options(self.d, self.sid, scope)):
                        continue
                    r = self._act(step, meta)
                yield step, meta, r
                # A deny because the session left `running` under the step is not the agent's to answer for:
                # the next turn waits for the revert or ends the loop. Any other deny or failure ends the pass.
                if r.result is None and not (r.reason or "").startswith(gate.SESSION_DENY):
                    return
            if idle:
                return
