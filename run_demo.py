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
from core.agents import Step

RUN_COLLECTIONS = ("sessions", "tasks", "audit_events", "saga_stack", "budget_ledger", "work_orders",
                   "inspection_requests", "plans")
OWNER, ENGINEER = "user:owner_a", "user:engineer_b"
ENVELOPE = 250_000_000.0  # assumption: large enough that the plan holds a line for each demo asset
OVER_LIMIT = setup_db.OWNER_SPEND + 50_000.0
OFF_PLAN = 12_345.0       # assumption: an amount no plan line has
MOCK_YEAR = 2026          # mock: the proposed readings are not in the source file
MOCK_DROP = 5.0           # mock: proposed rating = newest published rating minus this
SEED_KEY = r"^[^:]+:\d{4}$"  # condition ids the asset loader writes; anything else is from an earlier run
TIMEOUT = 60.0


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


def wait_for(what: str, done) -> None:
    end = time.monotonic() + TIMEOUT
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

    def pick(tool: str, goal: str, options: list[Step]) -> Step:
        return agents.choose(c.TOOLS[tool].actor, goal, options) if a.llm else options[0]

    def relay(script: list[Step], expect: list[bool]) -> list[c.ToolResult]:
        out = []
        for (step, r), want in zip(orch.run(script), expect):
            shown = {k: v for k, v in step.args.items() if k in ("asset_id", "amount", "rating")}
            beat.show(c.TOOLS[step.tool].actor, step.tool, r.allowed, r.reason, want, f"{shown} | {step.rationale}")
            out.append(r)
            time.sleep(a.step)
        if len(out) != len(expect):
            raise SystemExit(f"relay stopped after {len(out)} of {len(expect)} steps: session is not running "
                             "(another run with --reset deletes it)")
        return out

    def mock_condition(asset: str) -> Step:
        newest = d.condition_records.find_one({"asset_id": asset, "status": "approved"}, sort=[("year", -1)])
        rating = round(newest["rating"] - MOCK_DROP, 2)
        return Step("propose_condition", {"asset_id": asset, "rating": rating, "year": MOCK_YEAR},
                    f"MOCK reading for the demo: {rating} in {MOCK_YEAR} (published {newest['rating']} in {newest['year']})")

    def human(actor: str, action: str, condition_id: str, expect: bool, reason: str | None = None) -> None:
        """--auto: the same server route the page button calls. Interactive: wait for the page."""
        tool = f"{action}_condition"
        if client is None:
            print(f"    on the page, as {actor}: {action} {condition_id}", flush=True)
            if expect:
                wait_for(f"{action} from the page",
                         lambda: d.condition_records.find_one({"_id": condition_id})["status"] != "pending")
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
    first = d.assets.find_one({"region": setup_db.REGION}, sort=[("_id", 1)])["_id"]
    cond1 = relay([mock_condition(first)], [True])[0].result["produced"]
    human(OWNER, "approve", cond1, True)
    relay([pick("propose_plan", "Solve the treatment plan for the session from the approved condition records.",
                [Step("propose_plan", {}, "plan from approved conditions")])], [True])
    plan = active_plan()
    lines = sorted(plan["lines"], key=lambda l: (-l["benefit"] / l["cost"], l["asset_id"]))[:3]
    if len(lines) < 3:
        raise SystemExit(f"plan has {len(plan['lines'])} lines, need 3")
    print(f"    plan {plan['_id']}: {len(plan['lines'])} lines, total cost "
          f"{sum(l['cost'] for l in plan['lines']):,.2f} of envelope {ENVELOPE:,.2f}", flush=True)

    # 2. programming picks which plan line to commit first; work order follows; two commitments are denied.
    options = [Step("commit_budget", {"asset_id": l["asset_id"], "amount": l["cost"]},
                    f"plan line {l['treatment']}: cost {l['cost']:,.2f}, benefit {l['benefit']:,.2f}, "
                    f"benefit per dollar {l['benefit'] / l['cost']:.6f}") for l in lines]
    commit_a = pick("commit_budget", "Commit first the plan line with the highest benefit per dollar.", options)
    a_id = commit_a.args["asset_id"]
    commit_b = next(o for o in options if o.args["asset_id"] != a_id)
    b_id = commit_b.args["asset_id"]
    order_a = pick("create_work_order", f"Open the work order for the bridge whose budget was just committed ({a_id}).",
                   [Step("create_work_order", {"asset_id": a_id}, f"work order for {a_id}", {"budget_id": 0})])
    done = relay([
        commit_a, order_a,
        Step("commit_budget", {"asset_id": b_id, "amount": OFF_PLAN}, "off-plan attempt: amount is not a plan line"),
        Step("commit_budget", {"asset_id": b_id, "amount": OVER_LIMIT}, "over-limit attempt"),
    ], [True, True, False, False])
    budget_a = done[0].result["produced"]

    # 3. a second reading arrives; agents act on it while it is pending; the engineer cannot decide it.
    done = relay([
        mock_condition(b_id),
        commit_b._replace(handoff={"condition_id": 0}),
        Step("create_work_order", {"asset_id": b_id}, f"work order for {b_id}", {"budget_id": 1}),
    ], [True, True, True])
    cond2, budget_b, order_b = (r.result["produced"] for r in done)
    human(ENGINEER, "approve", cond2, False)

    # 4. the owner rejects it: only its dependants revert, an inspection is requested, the plan is re-solved.
    human(OWNER, "reject", cond2, True, "reading disputed, re-inspect")
    wait_for("revert and re-plan", lambda: d.plans.count_documents({"session_id": sid}) >= 2
             and d.sessions.find_one({"_id": oid})["status"] == orchestrator.RUNNING)
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
    orch.watcher.join()
    status = d.sessions.find_one({"_id": oid}, {"status": 1})["status"]
    left = d.budget_ledger.count_documents({"session_id": sid, "status": "committed"})
    beat.check(f"session status {status}", status == orchestrator.ROLLED_BACK)
    beat.check(f"committed lines left: {left}", left == 0)
    if a.llm:
        print(f"LLM calls: {agents.USAGE['calls']}, tokens: {agents.USAGE['tokens']}", flush=True)
    if beat.bad:
        raise SystemExit("FAILED: " + "; ".join(beat.bad))
    print("demo ok", flush=True)


if __name__ == "__main__":
    main()
