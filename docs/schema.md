# Schema

Database `capital` (or `CAPITAL_DB`, see `db.py:35`) holds the control and domain collections. Database `adlc` holds the shared work log. Names come from `contracts.py`; validators and seeds from `setup_db.py`. Field lists were checked against a live run in `capital_rec` and against `adlc` on 2026-11-14.

Writers: **tool** = a domain tool in `systems/` run by `guarded_call`; **gate** = `core/gate.py`; **ledger** = `core/ledger.py`; **revert** = `core/revert.py`; **orch** = `core/orchestrator.py`; **web** = `web/server.py`; **seed** = `setup_db.py` / `systems/assets.py`.

## Control collections

All six carry a `$jsonSchema` validator with `additionalProperties: false`, `validationLevel: strict`, `validationAction: error` (`setup_db.py:31-171`).

### principals

| field | type | req | meaning | writer |
|---|---|---|---|---|
| `_id` | string `^(user\|agent):[a-z0-9_]+$` | yes | principal id, e.g. `user:owner_a`, `agent:planner` | seed |
| `kind` | `human` \| `agent` | yes | | seed |
| `roles` | string[] | yes | matched against `policies.roles` | seed |
| `region` | string | yes | jurisdiction of a human | seed |
| `spend_limit` | number | yes | per-commit limit of the session's human (owner 100,000,000; engineer 10,000; agents 0) | seed |
| `active` | bool | yes | inactive actors are denied | seed |

### policies

| field | type | req | meaning | writer |
|---|---|---|---|---|
| `_id` | ObjectId | | | seed |
| `tool` | string | yes | tool name from `contracts.TOOLS` | seed |
| `version` | int | yes | | seed |
| `status` | `active` \| `retired` | yes | one active per tool | seed |
| `roles` | string[] | yes | actor must hold one | seed |
| `checks` | `{name, params}`[] | yes | `name` in `CHECK_NAMES` | seed |
| `author` | string | yes | `user:owner_a` | seed |
| `created_at` | date | yes | | seed |

### sessions

| field | type | req | meaning | writer |
|---|---|---|---|---|
| `_id` | ObjectId | | session id; string form is `session_id` elsewhere | `run_demo.py` |
| `principal_id` | string | yes | human the agents act for | `run_demo.py` |
| `task` | string | yes | | `run_demo.py` |
| `region` | string | yes | jurisdiction scope | `run_demo.py` |
| `budget_envelope` | number | yes | `E` in formulas §4 | `run_demo.py` |
| `status` | `SESSION_STATUS` | yes | `running`, `reverting`, `abort_requested`, `rolling_back`, `rolled_back`, `completed`, `failed` | web (stop, reject), orch, revert (`reverting`→`running`) |
| `revert_for` | string \| null | | condition id being reverted | web (reject) |
| `aborted_by` | string \| null | | who pressed Stop | web (stop) |
| `audit_head` | string | yes | hash of the last audit event | ledger |
| `created_at`, `updated_at` | date | yes | | `run_demo.py`, web, orch, revert |

### tasks

| field | type | req | meaning | writer |
|---|---|---|---|---|
| `session_id` | string | yes | | orch |
| `type` | string | yes | tool name | orch |
| `agent_id` | string | yes | `TOOLS[tool].actor` | orch |
| `status` | `queued` \| `claimed` \| `done` \| `failed` \| `cancelled` | yes | | orch |
| `input` | object | | `args`, `rationale`, `depends_on`, plus choice meta (`offered`, `picked`, `by`, `model`) | orch |
| `output` | object \| null | | tool result | orch |
| `created_at` | date | yes | | orch |

### audit_events

Append-only, hash-chained per session.

| field | type | req | meaning | writer |
|---|---|---|---|---|
| `session_id` | string | yes | | ledger |
| `seq` | int | yes | 1, 2, ... per session | ledger |
| `ts` | date | yes | stamped by the ledger, ms UTC | ledger |
| `type` | `EVENT_TYPES` | yes | `session_started`, `decision`, `executed`, `failed`, `abort_observed`, `compensated`, `session_ended` | gate, revert, orch |
| `principal_id` | string | yes | session's human | gate, revert, orch |
| `actor_id` | string | yes | agent, human, or `core:revert` | gate, revert, orch |
| `tool` | string \| null | | tool, or undo tool on `compensated` | gate, revert |
| `args` | object \| null | | tool args, or `undo_args` | gate, revert |
| `policy_id`, `policy_version` | string, int \| null | | policy evaluated | gate |
| `decision` | `allow` \| `deny` \| null | | on `decision` events | gate |
| `reason` | string \| null | | deny or failure reason | gate, revert, orch |
| `rationale` | string \| null | | agent's (or model's) text | gate |
| `before` | object \| null | | snapshot before the write | gate |
| `after` | object \| null | | tool result, or `{saga_seq, result}`, or end status | gate, revert, orch |
| `depends_on` | string[] | | ids the call relies on | gate, revert |
| `prev_hash` | string | yes | previous event's `hash`, `"0"*64` for seq 1 | ledger |
| `hash` | string | yes | `SHA-256(prev_hash + canon(event without _id, hash))` | ledger |

### saga_stack

| field | type | req | meaning | writer |
|---|---|---|---|---|
| `session_id` | string | yes | | revert (`arm`) |
| `seq` | int | yes | seq of the `decision` event | revert |
| `tool` | string | yes | | revert |
| `undo_tool` | string \| null | | from `contracts.TOOLS` | revert |
| `undo_args` | object | yes | `{idempotency_key, produced}` | revert |
| `produced` | string \| null | | `_id` the tool wrote | revert (`mark_done`) |
| `depends_on` | string[] | | used by `revert_dependants` | revert |
| `state` | `armed` \| `done` \| `compensated` \| `comp_failed` | yes | | revert |

## Domain collections

No validators; shapes come from the tool code. Every tool write uses the gate's idempotency key `<session_id>:<decision seq>` as `_id`.

### assets (seed, 198 Highway 401 bridges in Toronto)

| field | type | req | meaning | writer |
|---|---|---|---|---|
| `_id` | string | yes | Ontario `ID (SITE N°)` | seed |
| `region` | string | yes | `r1` | seed |
| `county` | string | yes | `TORONTO` | seed |
| `year_built` | int | yes | | seed |
| `deck_area` | number | yes | length × total width, m² | seed |

### condition_records

| field | type | req | meaning | writer |
|---|---|---|---|---|
| `_id` | string | yes | seed: `<asset_id>:<year>`; proposal: idempotency key | seed, tool |
| `asset_id` | string | yes | | seed, `propose_condition` |
| `rating` | number | yes | BCI 0-100 | seed, `propose_condition` |
| `year` | int | yes | | seed, `propose_condition` |
| `status` | `pending` \| `approved` \| `rejected` | yes | | `propose_condition`, `approve_condition`, `reject_condition`; `withdraw_condition` deletes a pending one |

### plans

| field | type | meaning | writer |
|---|---|---|---|
| `_id` | string | idempotency key | `propose_plan` |
| `session_id`, `seq` | string, int | active plan = highest `seq` not superseded | `propose_plan` |
| `superseded` | bool | | `propose_plan`, `supersede_plan` (undo) |
| `status` | `optimal` \| `infeasible` | | `propose_plan` |
| `objective` | number \| null | total benefit | `propose_plan` |
| `lines` | `{asset_id, treatment, cost, benefit}`[] | | `propose_plan` |
| `inputs_hash` | string | SHA-256 of candidates, envelope, fixed, excluded | `propose_plan` |
| `policy_versions` | object | `{propose_plan, commit_budget}` versions | `propose_plan` |
| `solver` | object | `{name: scipy.optimize.milp, version}` | `propose_plan` |

### budget_ledger

| field | type | meaning | writer |
|---|---|---|---|
| `_id` | string | idempotency key | `commit_budget` |
| `session_id`, `asset_id` | string | | `commit_budget` |
| `amount` | number | equals a plan line `cost` | `commit_budget` |
| `status` | `committed` \| `released` | | `commit_budget`, `release_budget` (undo) |
| `depends_on` | string[] | | `commit_budget` |

### work_orders

| field | type | meaning | writer |
|---|---|---|---|
| `_id` | string | idempotency key | `create_work_order` |
| `session_id`, `asset_id` | string | | `create_work_order` |
| `budget_id` | string | `budget_ledger._id` | `create_work_order` |
| `status` | `draft` \| `released` \| `cancelled` | | `create_work_order`, `cancel_work_order` (undo) |
| `depends_on` | string[] | `[budget_id]` | `create_work_order` |

### inspection_requests

| field | type | meaning | writer |
|---|---|---|---|
| `_id` | string | idempotency key (no `session_id` field; the page matches the key prefix) | `request_inspection` |
| `condition_id`, `asset_id` | string | rejected condition and its bridge | `request_inspection` |

`program_lines` is listed in `contracts.DOMAIN_COLLECTIONS` but no code reads or writes it.

## ADLC collections (database `adlc`, `scripts/adlc_log.py`)

### adlc.items (status, the only source)

| field | type | meaning | writer |
|---|---|---|---|
| `_id` | string | item id, e.g. `S3` | `item` |
| `owner` | `sagar` \| `arad` \| `both` | | `item` |
| `title`, `check` | string | | `item` |
| `depends` | string[] | | `item` |
| `order` | int | board order | `item` |
| `status` | `todo` \| `active` \| `blocked` \| `done` \| `dropped` | | `item`, `add` (event-driven) |
| `phase` | `Spec` … `Ship` | | `item`, `add` |
| `blocked_on`, `sha` | string \| null | | `add` |
| `updated`, `by` | date, string | | `item`, `add` |

### adlc.log (event feed)

| field | type | meaning |
|---|---|---|
| `item` | string | item id (from branch for commits) |
| `event` | `task_start` `task_done` `decision` `blocker` `handoff` `test_run` `commit` `question` `review` `gate` | |
| `summary` | string | |
| `ts`, `author` | date, string | |
| `tool`, `actor` | string | `claude-code`, `cursor`, `git`, `human` |
| `phase`, `to`, `evidence`, `sha`, `files`, `commit_sha` | optional | |

`add` writes the event, then `apply_status` moves the item: `task_start`→active, `blocker`→blocked, `task_done`/`gate`→done (`scripts/adlc_log.py:91-115`). The post-commit hook logs `commit` events.

## Indexes (`contracts.py:189-196`, created by `setup_db.py:174-176`)

| collection | keys | options | purpose |
|---|---|---|---|
| audit_events | `session_id, seq` | unique | a concurrent append retries instead of forking the chain |
| saga_stack | `session_id, seq` | unique | one saga entry per decision |
| policies | `tool, version` | unique | |
| policies | `tool` | unique, partial `{status: "active"}`, name `one_active_per_tool` | at most one active policy per tool |
| tasks | `session_id, status` | | claim query |

Domain idempotency relies on the `_id` index: the key is the `_id`.

## MongoDB features used

| feature | where |
|---|---|
| `$jsonSchema` validators, strict / error | `setup_db.py:150-171` |
| unique compound indexes, partial unique index | `contracts.py:189-196`, `setup_db.py:176` |
| `DuplicateKeyError` retry on append | `core/ledger.py:62-65` |
| guarded update of `audit_head` (`{_id, audit_head: prev}`) | `core/ledger.py:68` |
| `find_one_and_update` task claim | `core/orchestrator.py:30` |
| `find_one_and_update` session status moves | `core/orchestrator.py:57` |
| `$setOnInsert` idempotent upserts | `systems/budget.py:13`, `systems/workorders.py:9`, `systems/conditions.py:9`, `systems/inspections.py:6`, `systems/plans.py:43` |
| conditional single updates (undo, decide, stop) | `systems/budget.py:25`, `systems/conditions.py:25`, `systems/workorders.py:21`, `systems/plans.py:55`, `web/server.py:68` |
| `$group` aggregation for the envelope check | `core/gate.py:81` |
| change stream on `audit_events` inserts (SSE feed) | `web/server.py:152` |

## Life of a tool call (`guarded_call`, `core/gate.py:166`)

Allow path, for a tool with an undo (e.g. `commit_budget`):

1. `_evaluate` reads `sessions`, `principals`, active `policies`, and whatever the checks need (`budget_ledger`, `assets`, `plans`). Nothing is written.
2. `audit_events` ← `decision` event, `decision: allow`, seq *n*; `sessions.audit_head` moves.
3. `saga_stack` ← entry `{seq: n, state: armed, undo_args.idempotency_key: "<sid>:<n>"}`. Insert fails → `failed` event, no execution.
4. Tool `snapshot` reads the target document (`before`).
5. Tool writes the domain document, `_id = "<sid>:<n>"`, via `$setOnInsert` upsert. Raises → `failed` event; the entry stays `armed`.
6. `saga_stack` entry → `state: done`, `produced` set.
7. `audit_events` ← `executed` event with `before` and `after`, seq *n+1*.

Deny path: steps 1-2 only, with `decision: deny` and `reason`. No saga entry, no domain write.

Revert after a rejected condition: `web` sets the session `reverting` and `revert_for`; the orchestrator calls `revert_dependants`, which finds `armed`/`done` entries whose `depends_on` reaches the condition (directly or through `produced`), runs each undo newest first, sets the entry `compensated` and appends a `compensated` event per entry, returns the session to `running`, then opens an inspection request through `guarded_call`. Stop: `abort_requested` → `rolling_back`, `abort_observed` event, every live entry compensated newest first, `session_ended` with `rolled_back` (or `failed` if an undo raised).
