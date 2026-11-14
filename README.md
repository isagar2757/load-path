# Load Path

> In a bridge, the load path is the route a load takes down to the ground. In ours, it is the route every agent action takes through the gate, the ledger and, if rejected, the revert.

Built for the MongoDB Agents in Context Toronto Hackathon, 2026-11-14.

## Problem

A public agency chooses which bridges to treat with a budget that never covers all of them, and the budget and the condition data change during the year. A council or auditor then asks why one bridge was chosen over another, who authorised the spend, and what was undone when a fact turned out to be wrong. That answer is usually rebuilt by hand from several systems. Load Path routes every tool call, from an agent or a person, through one policy gate, records it in a hash-chained ledger, and can reverse the work that depended on a rejected fact.

## What was built today

- **Policy gate** (`core/gate.py`): `guarded_call` checks the session state, loads the actor and the active policy for the tool, evaluates the policy checks (`role`, `spend_limit`, `envelope`, `jurisdiction`, `has_commitment`, `has_reason`), writes a decision event, takes a snapshot, runs the tool and writes an executed event. A missing policy or any error is a deny. The `in_approved_plan` check name is defined in `contracts.py`; `core/gate.py` has no evaluator for it.
- **Ledger** (`core/ledger.py`): per-session events with a SHA-256 hash chain; `verify` returns the first sequence number where the chain breaks. The chain detects edits and gaps; it does not prevent them.
- **Revert** (`core/revert.py`): a saga stack of compensating actions. `rollback_session` undoes every live entry; `revert_dependants` undoes only the entries that depend on a rejected condition, newest first. Undo functions are idempotent.
- **Domain systems** (`systems/`): simulated budget ledger, work orders, inspection requests and condition records. Tools: `commit_budget`, `create_work_order`, `request_inspection`, `propose_condition`, `approve_condition`, `reject_condition`. They are registered with the gate and write only through `guarded_call`.
- **Data seed** (`setup_db.py`, `systems/assets.py`): validators, indexes, principals and policies for database `capital`; assets and approved condition records for 206 Highway 401 structures inside an approximate Toronto bounding box, from the Ontario bridge conditions file.
- **Treatment selection** (`engine/plan.py`): a mixed-integer program (`scipy.optimize.milp`) that maximises total benefit within a budget envelope, at most one treatment per bridge, with optional fixed lines and excluded bridges. Each result carries an `inputs_hash`. The formulation is in [docs/formulas.md](docs/formulas.md).
- **Control surface** (`web/server.py`, `web/index.html`): a FastAPI app with a Stop button, a list of pending condition records with approve and reject buttons, and a live event feed (server-sent events from a MongoDB change stream on `audit_events`). Every button calls an endpoint that calls `guarded_call` or sets the session status.
- **Demo script** (`run_demo.py`): creates a session, commits budget for two bridges, creates a work order, attempts a commitment above the owner's spend limit (denied), waits for Stop, then rolls the session back.

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
uv run python run_demo.py --reset       # in another terminal; prints the page URL, then press Stop
uv run pytest -q
```

- `systems.assets` reads `bridge_condition_open_data_2020_en.csv` from `~/hackathon-data/ontario-bridge-conditions/`, or from the path in `ONTARIO_BRIDGES_PATH`. Download the file from the source under Data and attribution.
- `run_demo.py` flags: `--reset` clears the run collections and re-runs `setup_db`; `--auto-stop` requests the stop without the page; `--wait SECONDS` (default 8) is the pause to open the page; `--step SECONDS` (default 1.5) is the pause between steps. It needs at least two assets in region `r1`.
- Tests that need Atlas skip when `MONGODB_URI` is unset. Each test uses its own `capital_test_<suffix>` database and drops it.

## Assumptions

Treatment gains and costs are assumptions, not sourced figures (`TREATMENTS` in `engine/plan.py`). Cost = rate × deck area. Benefit = rating gain × deck area, with the gain capped at 100 − current BCI; no traffic weight.

| Treatment | Rating gain (BCI points) | Cost per m² of deck |
|---|---|---|
| `minor_rehab` | 10 | 500 |
| `major_rehab` | 25 | 2000 |
| `replacement` | 60 | 6000 |

- The demo amounts in `run_demo.py` (envelope 120,000; commitments 40,000 and 35,000), the seeded spend limits and the region `r1` in `setup_db.py` are assumptions.
- The tool takes published condition ratings as given. It makes no safety or engineering judgment and is not engineering or cost data.
- The solver picks treatments by arithmetic in code. The conditions file's per-year ratings are not loaded.

## Data and attribution

Bridge conditions: Ontario Ministry of Transportation, [Bridge conditions](https://data.ontario.ca/dataset/bridge-conditions), file `bridge_condition_open_data_2020_en.csv`, 2021-06-09. Licence: Open Government Licence - Ontario.

Contains information licensed under the Open Government Licence - Ontario.

The data file is not stored in this repository. The seed keeps rows for highway `401` inside an approximate Toronto bounding box, so it can include structures just over the city line.

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
