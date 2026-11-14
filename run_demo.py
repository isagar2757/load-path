"""Full demo beat: intake, plan, commitments, denials, a rejection that reverts only its dependants, stop.

    uv run uvicorn web.server:app --port 8000     # the page, in another terminal
    uv run python run_demo.py --reset             # interactive: Approve, Reject and Stop come from the page
    uv run python run_demo.py --reset --auto      # no page: the human actions go through the same server routes
    uv run python run_demo.py --reset --auto --llm

Amounts are assumptions and the two proposed condition ratings are MOCK input (README). The orchestrator relays
every agent step; every domain write goes through `guarded_call`. Exits 1 when a beat differs from the script.
"""
import argparse
import time
from datetime import UTC, datetime

from bson import ObjectId

import contracts as c
import db as dbmod
import setup_db
import systems
from core import agents, orchestrator
from core.agents import Step, intake, planner, programming, workorder

RUN_COLLECTIONS = ("sessions", "tasks", "audit_events", "saga_stack", "budget_ledger", "work_orders",
                   "inspection_requests", "plans")
OWNER, ENGINEER = "user:owner_a", "user:engineer_b"
ENVELOPE = 250_000_000.0  # assumption: large enough that the plan holds a line for each demo asset
OVER_LIMIT = setup_db.OWNER_SPEND + 50_000.0
OFF_PLAN = 12_345.0       # assumption: an amount no plan line has
SEED_KEY = r"^[^:]+:\d{4}$"  # condition ids the asset loader writes; anything else is from an earlier run
TIMEOUT = 60.0         # seconds for the watcher to finish a revert and re-plan
HUMAN_TIMEOUT = 1800.0  # seconds to wait for a click on the page


class Beat:
    """Prints one line per beat and records each one that differs from the script."""

    def __init__(self) -> None:
        self.n, self.bad = 0, []

    def show(self, actor: str, tool: str, allowed: bool, reason: str | None, expect: bool, note: str = "") -> None:
        self.n += 1
        line = f"{self.n:>2}. {actor:<18} {tool:<18} {'ALLOW' if allowed else 'DENY '} {note}"
        print(line + (f"  ({reason})" if reason else ""), flush=True)
        if allowed != expect:
            self.bad.append(f"beat {self.n} {tool}: expected {'ALLOW' if expect else 'DENY'}")

    def check(self, label: str, ok: bool) -> None:
        print(f"    {'ok  ' if ok else 'FAIL'} {label}", flush=True)
        if not ok:
            self.bad.append(label)


def reset(d) -> None:
    for name in RUN_COLLECTIONS:
        d[name].delete_many({})
    d.condition_records.delete_many({"_id": {"$not": {"$regex": SEED_KEY}}})
    setup_db.setup(d.name)


def wait_for(what: str, done, timeout: float = TIMEOUT) -> None:
    end = time.monotonic() + timeout
    while not done():
        if time.monotonic() > end:
            raise SystemExit(f"timed out waiting for {what}")
        time.sleep(0.2)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true")
    p.add_argument("--auto", "--auto-stop", action="store_true", help="human actions without the page")
    p.add_argument("--llm", action="store_true", help="agents pick from code-built options and write the rationale")
    p.add_argument("--wait", type=float, default=8.0, help="seconds to open the page before the run")
    p.add_argument("--step", type=float, default=1.5)
    a = p.parse_args()

    d = dbmod.get_db()
    if a.reset:
        reset(d)
    systems.register()
    if d.assets.count_documents({"region": setup_db.REGION}) < 3:
        raise SystemExit("need 3 assets in region r1: run `uv run python -m systems.assets` (A4)")

    now = datetime.now(UTC)
    sid = str(d.sessions.insert_one(c.Session(
        principal_id=OWNER, task="full demo beat", region=setup_db.REGION, budget_envelope=ENVELOPE,
        status="running", created_at=now, updated_at=now).model_dump()).inserted_id)
    oid = ObjectId(sid)
    print(f"session {sid}\nopen http://127.0.0.1:8000/?session_id={sid}&actor={OWNER}", flush=True)
    time.sleep(a.wait)

    beat = Beat()
    orch = orchestrator.Orchestrator(sid, db=d)
    orch.start()
    client = None
    if a.auto:
        from fastapi.testclient import TestClient
        from web.server import create_app
        client = TestClient(create_app(d))

    def stopped() -> bool:
        session = d.sessions.find_one({"_id": oid}, {"status": 1})
        return session is None or session["status"] not in (orchestrator.RUNNING, orchestrator.REVERTING)

    def finish(early: bool = False) -> None:
        """Wait for the watcher's rollback, check the end state and exit."""
        if early:
            print("    Stop pressed before the script finished: rolling back what was done", flush=True)
        orch.watcher.join()
        session = d.sessions.find_one({"_id": oid}, {"status": 1})
        if session is None:
            raise SystemExit("FAILED: the session was deleted (another run with --reset?)")
        left = d.budget_ledger.count_documents({"session_id": sid, "status": "committed"})
        beat.check(f"session status {session['status']}", session["status"] == orchestrator.ROLLED_BACK)
        beat.check(f"committed lines left: {left}", left == 0)
        if a.llm:
            u = agents.USAGE
            print(f"LLM calls: {u['calls']}, tokens: {u['tokens']}, fallbacks: {u['fallbacks']}", flush=True)
            for agent_id, n in u["by_agent"].items():
                print(f"    {agent_id}: calls {n['calls']}, tokens {n['tokens']}, fallbacks {n['fallbacks'] or 0}",
                      flush=True)
        if beat.bad:
            raise SystemExit("FAILED: " + "; ".join(beat.bad))
        print("demo ok" + (" (stopped early)" if early else ""), flush=True)
        raise SystemExit(0)

    def pick(agent, scope: list[str]) -> Step:
        """The agent's step for `scope`: the code-ranked best, or in LLM mode the model's pick among the options."""
        step, meta = agents.choose(agent, d, sid, scope, a.llm)
        if step is None:
            if stopped():
                finish(early=True)
            raise SystemExit(f"FAILED: {agent.AGENT_ID} has no option for {scope}")
        print(f"    {agent.AGENT_ID} offered {meta['offered']}, picked {meta['picked']}, by {meta['by']}"
              + (f" ({meta['model']})" if meta["model"] else ""), flush=True)
        return step

    def relay(script: list[Step], expect: list[bool]) -> list[c.ToolResult]:
        out = []
        for (step, r), want in zip(orch.run(script), expect):
            shown = {k: v for k, v in step.args.items() if k in ("asset_id", "amount", "rating")}
            beat.show(c.TOOLS[step.tool].actor, step.tool, r.allowed, r.reason, want, f"{shown} | {step.rationale}")
            out.append(r)
            time.sleep(a.step)
        if len(out) != len(expect):
            finish(early=True)
        return out

    def human(actor: str, action: str, condition_id: str, expect: bool, reason: str | None = None) -> None:
        """--auto: the same server route the page button calls. Interactive: wait for the page."""
        tool = f"{action}_condition"
        if client is None:
            print(f"    on the page, as {actor}: {action} {condition_id}", flush=True)
            if expect:
                wait_for(f"{action} or Stop from the page", lambda: stopped() or (d.condition_records.find_one(
                    {"_id": condition_id}) or {}).get("status") != "pending", HUMAN_TIMEOUT)
                if stopped():
                    finish(early=True)
                got = d.condition_records.find_one({"_id": condition_id})["status"]
                beat.show(actor, tool, got == f"{action[:-1] if action.endswith('e') else action}ed", None, True,
                          f"{condition_id} -> {got}")
            return
        body = {"actor_id": actor, "condition_id": condition_id, **({"reason": reason} if reason else {})}
        resp = client.post(f"/sessions/{sid}/conditions/{action}", json=body)
        beat.show(actor, tool, resp.status_code == 200, None if resp.status_code == 200 else resp.json()["detail"],
                  expect, condition_id + (f" | {reason}" if reason else ""))

    def active_plan() -> dict:
        return d.plans.find_one({"session_id": sid, "superseded": False}, sort=[("seq", -1)]) or {"lines": []}

    def status_of(coll: str, key: str) -> str:
        return d[coll].find_one({"_id": key})["status"]

    # 1. intake proposes a reading, the owner approves it, the planner solves.
    scope = [x["_id"] for x in d.assets.find({"region": setup_db.REGION}, {"_id": 1}, sort=[("_id", 1)], limit=3)]
    cond1 = relay([pick(intake, scope[:1])], [True])[0].result["produced"]
    human(OWNER, "approve", cond1, True)
    relay([pick(planner, scope)], [True])
    plan = active_plan()
    if len([l for l in plan["lines"] if l["asset_id"] in scope]) < 3:
        raise SystemExit(f"plan {plan.get('_id')} has no line for one of {scope}")
    print(f"    plan {plan['_id']}: {len(plan['lines'])} lines, total cost "
          f"{sum(l['cost'] for l in plan['lines']):,.2f} of envelope {ENVELOPE:,.2f}", flush=True)

    # 2. programming picks which plan line to commit first; work order follows; two commitments are denied.
    commit_a = pick(programming, scope)
    a_id = commit_a.args["asset_id"]
    b_id = next(x for x in scope[1:] if x != a_id)   # a bridge with no reading in this session yet
    budget_a = relay([commit_a], [True])[0].result["produced"]
    relay([pick(workorder, [a_id])], [True])
    relay([
        Step("commit_budget", {"asset_id": b_id, "amount": OFF_PLAN}, "off-plan attempt: amount is not a plan line"),
        Step("commit_budget", {"asset_id": b_id, "amount": OVER_LIMIT}, "over-limit attempt"),
    ], [False, False])

    # 3. a second reading arrives; agents act on it while it is pending; the engineer cannot decide it.
    done = [relay([pick(agent, [b_id])], [True])[0] for agent in (intake, programming, workorder)]
    cond2, budget_b, order_b = (r.result["produced"] for r in done)
    human(ENGINEER, "approve", cond2, False)

    # 4. the owner rejects it: only its dependants revert, an inspection is requested, the plan is re-solved.
    human(OWNER, "reject", cond2, True, "reading disputed, re-inspect")
    wait_for("revert and re-plan", lambda: stopped() or (
        d.plans.count_documents({"session_id": sid}) >= 2
        and d.sessions.find_one({"_id": oid})["status"] == orchestrator.RUNNING))
    if stopped():
        finish(early=True)
    replanned = active_plan()
    beat.check(f"reverted: budget for {b_id} released", status_of("budget_ledger", budget_b) == "released")
    beat.check(f"reverted: work order for {b_id} cancelled", status_of("work_orders", order_b) == "cancelled")
    beat.check(f"kept: budget for {a_id} still committed", status_of("budget_ledger", budget_a) == "committed")
    beat.check("inspection request opened", d.inspection_requests.count_documents({"condition_id": cond2}) == 1)
    beat.check(f"re-plan {replanned['_id']} excludes {b_id} and keeps {a_id}",
               replanned["_id"] != plan["_id"] and b_id not in {l["asset_id"] for l in replanned["lines"]}
               and a_id in {l["asset_id"] for l in replanned["lines"]})

    # 5. stop: everything left is rolled back.
    if client is None:
        print("    on the page, as the owner: Stop", flush=True)
    else:
        resp = client.post(f"/sessions/{sid}/stop", json={"aborted_by": OWNER})
        beat.show(OWNER, "stop", resp.status_code == 200, None, True)
    finish()


if __name__ == "__main__":
    main()
