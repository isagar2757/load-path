<img src="docs/assets/logo.svg" alt="load-path mark" width="96">

# Load Path

> In a bridge, the load path is the route a load takes down to the ground. In ours, it is the route every agent action takes through the gate, the ledger and, if rejected, the revert.

Built for the MongoDB Agents in Context Toronto Hackathon, 2026-11-14.

## Problem

A public agency chooses which bridges to treat with a budget that never covers all of them, and the budget and the condition data change during the year. A council or auditor then asks why one bridge was chosen over another, who authorised the spend, and what was undone when a fact turned out to be wrong. That answer is usually rebuilt by hand from several systems. Load Path routes every tool call, from an agent or a person, through one policy gate, records it in a hash-chained ledger, and can reverse the work that depended on a rejected fact.

## What was built today

- **Policy gate** (`core/gate.py`): `guarded_call` checks the session state, loads the actor and the active policy for the tool, evaluates the policy checks (`role`, `spend_limit`, `envelope`, `jurisdiction`, `has_commitment`, `in_approved_plan`, `has_reason`), writes a decision event, takes a snapshot, runs the tool and writes an executed event. A missing policy or any error is a deny.
- **Ledger** (`core/ledger.py`): per-session events with a SHA-256 hash chain; `verify` returns the first sequence number where the chain breaks. The chain detects edits and gaps; it does not prevent them.
- **Revert** (`core/revert.py`): a saga stack of compensating actions. `rollback_session` undoes every live entry; `revert_dependants` undoes only the entries that depend on a rejected condition, newest first. Undo functions are idempotent.
- **Domain systems** (`systems/`): simulated budget ledger, work orders, inspection requests and condition records. Tools: `commit_budget`, `create_work_order`, `request_inspection`, `propose_condition`, `approve_condition`, `reject_condition`. They are registered with the gate and write only through `guarded_call`.
- **Data seed** (`setup_db.py`, `systems/assets.py`): validators, indexes, principals and policies for database `capital`; assets and approved condition records for 198 Highway 401 bridges (culverts excluded) inside an approximate Toronto bounding box, from the Ontario bridge conditions file.
- **Treatment selection** (`engine/plan.py`): a mixed-integer program (`scipy.optimize.milp`) that maximises total benefit within a budget envelope, at most one treatment per bridge, with optional fixed lines and excluded bridges. Each result carries an `inputs_hash`. The formulation is in [docs/formulas.md](docs/formulas.md).
- **Control surface** (`web/server.py`, `web/index.html`): a FastAPI app with a Stop button, a list of pending condition records with approve and reject buttons, and a live event feed (server-sent events from a MongoDB change stream on `audit_events`). Every button calls an endpoint that calls `guarded_call` or sets the session status. The page also shows the session's active plan with its total against the envelope, commitments, work orders and inspection requests, read from `GET /sessions/{id}/state`. The feed replays the session's earlier events when it connects.
  With `present=1` in the URL (for recording), live events are shown one at a time, each held `hold` seconds (default 5), with the changed panel outlined and a two-line caption; Space pauses.
- **Demo script** (`run_demo.py`): one session, 13 beats. Intake proposes a mock condition reading and the owner approves it; the planner solves the plan; programming commits a plan line and the work-order agent opens the order; an off-plan and an over-limit commitment are denied; a second mock reading arrives and agents act on it while it is pending; the engineer's approval is denied; the owner rejects the reading, so only its commitment and work order revert, an inspection request opens and the plan is re-solved without that bridge; Stop rolls back the rest. The script exits 1 when any beat differs.
- **Orchestrator and stop watcher** (`core/orchestrator.py`): `Orchestrator.run` relays a script one step at a time. Each step is queued as a `tasks` document, claimed atomically and acted on through the gate. A step whose handoff source produced nothing is not queued; an allowed step with no result ends the session as `failed`. On `reverting` the watcher thread reverts the rejected condition's dependants and calls `plans.replan`. On `abort_requested` it waits for the tool call in flight, writes `abort_observed`, rolls the session back and ends it as `rolled_back` (or `failed`, if a compensation failed).
- **Planner** (`systems/plans.py`, `engine/plan.py`): the `propose_plan` tool (actor `agent:planner`, undo `supersede_plan`) solves the session's plan over the region's bridges whose newest condition record is approved (a pending or rejected reading keeps a bridge out), with committed budget lines fixed, and stores it under `<session_id>:<seq>`. The `in_approved_plan` check (`core/gate.py`) allows a commitment only when the session's highest-`seq` non-superseded plan has a line with the same asset and cost. The seeded `commit_budget` policy lists this check.
- **Actor picker** (`web/index.html`): a select with `user:owner_a` and `user:engineer_b`, preset from the `actor` query parameter. Approve and reject send the choice as `actor_id` and Stop sends it as `aborted_by`. The server checks the id format and passes `actor_id` to `guarded_call`, so the gate decides what the actor may do. An empty or unknown actor never approves.

- **LLM mode** (`core/agents.py`): `choose()` gives an agent a goal and a list of options built in code. The model `gemini-3.5-flash-lite` (Gemini API `generateContent`, JSON output) returns an option number and a rationale. The tool and args always come from the code-built option. A missing key, a failed call or an invalid reply returns `options[default]`. `run_demo.py --llm` uses it for the planner, the first commitment (a choice among three plan lines) and the work order; without the flag the scripted steps run, and that is the tested path.

Design: [spec](docs/superpowers/specs/2026-11-13-audited-agent-design.md).

## Run steps

Requires `uv` and a MongoDB Atlas sandbox cluster.

```bash
./scripts/setup.sh                      # git hooks; creates .env from the template, then reports what is missing
```

Edit `.env`: set `MONGODB_URI` (the repo never holds a real connection string) and `ADLC_AUTHOR` (`sagar` or `arad`, used by the team's shared log). Re-run `./scripts/setup.sh` until it prints `ready`.

```bash
uv sync
uv run python setup_db.py               # validators, indexes, principals, policies in database `capital`
uv run python -m systems.assets         # seed assets and condition records (needs the data file below)
uv run uvicorn web.server:app --port 8000
uv run python run_demo.py --reset       # in another terminal; prints the page URL; Approve, Reject and Stop come from the page
uv run python run_demo.py --reset --auto         # no page: human actions go through the same server routes
uv run python run_demo.py --reset --auto --llm   # agents pick from code-built options (needs LLM_API_KEY in .env)
uv run pytest -q
```

- `systems.assets` reads `bridge_condition_open_data_2020_en.csv` from `~/hackathon-data/ontario-bridge-conditions/`, or from the path in `ONTARIO_BRIDGES_PATH`. Download the file from the source under Data and attribution.
- `run_demo.py` flags: `--reset` clears the run collections and re-runs `setup_db`; `--auto` performs the approve, reject and stop actions without the page; `--llm` turns on LLM mode; `--wait SECONDS` (default 8) is the pause to open the page; `--step SECONDS` (default 1.5) is the pause between steps. It needs at least three assets in region `r1`. `--reset` deletes every session in the database it runs on: set `CAPITAL_DB=capital_<name>` in `.env` to use your own database, then run `setup_db.py` and `systems.assets` for it. Stop at any point ends the run with a rollback.
- Tests that need Atlas skip when `MONGODB_URI` is unset. Each test uses its own `capital_test_<suffix>` database and drops it.

## Demo

3-minute live demo. Arad drives the page, Sagar speaks. Values come from a real run: `main` c56d97b, `run_demo.py --reset --auto --wait 0 --step 0` on database `capital_sagar`, which ended `demo ok`. Live, run `--reset` without `--auto` and click through; `--auto` is the fallback. Cut the 0:00 beat first if time runs short.

| Time | On screen (seq from the run) | Line |
|---|---|---|
| 0:00 | `adlc_log.py tail -n 12`; a non-conventional commit rejected by the hook | "We built this the way our agents run: every step logged, every commit checked before it lands." |
| 0:15 | 198 Highway 401 bridges, envelope 250,000,000. 1: Intake proposes a MOCK reading for 22X-0161/B1 (72.7, published 77.7 in 2020). 2: `user:owner_a` approves | "Agencies can't fund every bridge. Every action, agent or person, goes through one gate in Atlas before it runs." |
| 0:40 | 3: Planner solves: 190 lines, 249,979,760 of 250,000,000. 4: commit 1,618,200 for B1. 5: work order for B1 | "Code does the arithmetic. Each agent does one job, and each step names a person and a policy version." |
| 1:05 | 6: off-plan commit of 12,345: DENY `in_approved_plan`. 7: commit of 100,050,000: DENY `spend_limit` (limit 100,000,000) | "Off plan or over the limit, it never runs, and the denial is recorded." |
| 1:25 | 8–10: second MOCK reading for B2, commit 1,844,400, work order. 11: `user:engineer_b` approves: DENY `role` | "Only the owner can approve a reading." |
| 1:45 | 12: owner rejects B2 ("reading disputed, re-inspect"). B2 budget released, B2 work order cancelled, B1 kept, inspection opened, re-plan excludes B2 | "One wrong fact, and only what depended on it is undone." |
| 2:20 | 13: Stop. Status `rolled_back`, 0 committed lines | "Stop it, and everything it did is undone." |
| 2:35 | Terminal: edit the seq 8 amount in Atlas, then `ledger.verify(sid)` returns `(False, 8)` | "The record shows exactly where it was altered." |

## Assumptions

Treatment gains and costs are assumptions, not sourced figures (`TREATMENTS` in `engine/plan.py`). Cost = rate × deck area. Benefit = rating gain × deck area, with the gain capped at 100 − current BCI; no traffic weight.

| Treatment | Rating gain (BCI points) | Cost per m² of deck |
|---|---|---|
| `minor_rehab` | 10 | 500 |
| `major_rehab` | 25 | 2000 |
| `replacement` | 60 | 6000 |

- The demo amounts in `run_demo.py` (envelope 250,000,000; the off-plan and over-limit amounts), the seeded spend limits and the region `r1` in `setup_db.py` are assumptions.
- The tool takes published condition ratings as given. It makes no safety or engineering judgment and is not engineering or cost data.
- The solver picks treatments by arithmetic in code. The conditions file's per-year ratings are not loaded.
- The people (`user:owner_a`, `user:engineer_b`) and the five agent identities in `contracts.py` are fictional.
- Policies, spend limits and the budget envelope are demo rules, not a real authority matrix.
- The two condition ratings `run_demo.py` proposes are mock input (newest published rating minus 5, dated 2026) and are labelled MOCK in the feed.
- Plan output is illustrative. It is not an engineering, safety or funding recommendation.

## Data and attribution

Bridge conditions: Ontario Ministry of Transportation, [Bridge conditions](https://data.ontario.ca/dataset/bridge-conditions), file `bridge_condition_open_data_2020_en.csv`, 2021-06-09. Licence: [Open Government Licence - Ontario](https://www.ontario.ca/page/open-government-licence-ontario), version 1.0.

Contains information licensed under the Open Government Licence - Ontario.

Not affiliated with or endorsed by the Government of Ontario. Data is provided as is.

The data file is not stored in this repository. The seed keeps rows for highway `401` inside an approximate Toronto bounding box, so it can include structures just over the city line. The set is Highway 401 bridges in the Toronto area. The area label (stored as county `TORONTO`) and the bounding box are ours; the source file's COUNTY values for these rows are YORK, PEEL, ONTARIO or blank.

Condition ratings are from 2019 and 2020 inspections (source file dated 2021-06-09). They are not current. `deck_area` is derived (deck length × total width), not a source column.

## Libraries and licences

Versions are read from the installed packages (`uv sync`, 2026-11-14); see [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md). The project is MIT licensed ([LICENSE](LICENSE)).

| Name | Version | Purpose | Licence |
|---|---|---|---|
| pymongo | 4.20.0 | Atlas driver | Apache-2.0 |
| certifi | 2026.10.23 | CA bundle for TLS | MPL-2.0 |
| pydantic | 2.14.3 | Shapes in `contracts.py` | MIT |
| scipy | 1.18.1 | `scipy.optimize.milp` | BSD-3-Clause |
| numpy | 2.5.4 | Arrays for the MILP (installed with scipy) | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| scikit-learn | 1.9.1 | Declared in `pyproject.toml`; no code imports it on this branch | BSD-3-Clause |
| fastapi | 0.162.7 | Web server | MIT |
| uvicorn | 0.54.0 | ASGI server | BSD-3-Clause |
| pytest (dev) | 9.2.0 | Tests | MIT |
| httpx (dev) | 0.28.1 | Test client for the web tests | BSD-3-Clause |
