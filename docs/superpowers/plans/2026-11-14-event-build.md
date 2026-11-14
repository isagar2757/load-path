# Audited Capital-Program Agents — Event Build Plan

> **For agentic workers:** work one task at a time, in your owner's lane only. Steps use checkbox (`- [ ]`) syntax.
> This plan holds names, shapes and checks only. **No code is written before Sat 2026-11-14 10:45 AM EST.**

**Goal:** Several agents plan and commit a bridge repair program under a budget, with every action tied to a person, checked against policy in Atlas before it runs, recorded, and reversible.

**Architecture:** A deterministic policy gate, ledger, orchestrator and revert engine (Sagar) sit between LLM agents and three Atlas-backed systems plus a solver and a web page (Arad). The two lanes meet only through the shapes in `contracts.py` and the Atlas collections.

**Tech stack:** Python 3.13 via `uv` · `pymongo` + `certifi` · `scipy.optimize.milp` · `scikit-learn` · `fastapi` + `uvicorn` (server-sent events) · `pydantic` · `pytest` · one static HTML page.

**Spec:** [2026-11-13-audited-agent-design.md](../specs/2026-11-13-audited-agent-design.md)

**Formulas and rules:** [formulas.md](../../formulas.md) (policy checks, hash chain, revert set, MILP, forest, agent relay, data preparation)

## Global constraints
- Data layer: the hackathon Atlas Sandbox only (`Cluster0`). Database `capital`; tests use `capital_test` and drop it.
- Public repo `load-path`, MIT licence. Product code starts after 10:45; earlier commits are process tooling and docs only. Never commit a secret; `.env` is gitignored.
- Every `MongoClient` passes `tlsCAFile=certifi.where()`. Never disable TLS verification.
- Nothing from an employer, no vendor product names, no safety or engineering judgment.
- The page is a control surface (feed, approve/reject, stop). No chart-only views.
- Code does all arithmetic. The LLM picks from listed options and writes the rationale.
- Treatment costs are assumptions; the README says so.
- Every tool call, agent or human, goes through `guarded_call`. Nothing else writes to a domain collection after seeding.

## Review focus
1. **Atlas unreachable mid-run:** the gate denies; no tool runs. Test in Task S2.
2. **Stop arrives while a tool is executing:** the tool finishes, its event is written, then the run halts and rolls back. Test in Task S4.
3. **Rejecting a condition nothing depends on:** nothing is reverted; an inspection request is still opened. Test in Task S6.
4. **Undo runs twice:** every undo is idempotent. Test in Tasks A2 and A3.
5. **Budget envelope lowered below what is already committed:** the next commitment is denied; existing ones stay until a person acts. Test in Task S7.

## Ownership
| Path | Owner | Purpose |
|---|---|---|
| `contracts.py` | both, locked at 11:10 | Collection names, tool names, pydantic shapes below |
| `db.py` | both, written once | `get_db(name="capital")` |
| `AGENTS.md`, `README.md`, `pyproject.toml`, `.env.example`, `.gitignore`, `LICENSE` | both | README sections are owned by whoever built the feature |
| `core/gate.py` | Sagar | Tool registry, policy checks, `guarded_call` |
| `core/ledger.py` | Sagar | `append`, `verify`, `replay` |
| `core/revert.py` | Sagar | Saga entries, `rollback_session`, `revert_dependants` |
| `core/orchestrator.py` | Sagar | `tasks` state machine, session watcher |
| `core/agents.py` | Sagar | Agent loop, scripted mode, `llm()` |
| `tests/core/` | Sagar | |
| `setup_db.py` | Arad | Validators, indexes, seed |
| `systems/assets.py` | Arad | Data load, condition tools |
| `systems/budget.py` | Arad | Budget tools |
| `systems/workorders.py` | Arad | Work-order tools |
| `engine/plan.py` | Arad | MILP |
| `engine/forest.py` | Arad | Stage 5 |
| `web/server.py`, `web/index.html` | Arad | Feed and controls |
| `tests/systems/`, `tests/engine/` | Arad | |
| `run_demo.py` | Sagar writes, Arad reviews | Reset and scripted scenario |

**Conflict rules:** never edit a file you do not own; ask its owner. A change to `contracts.py` needs both to agree out loud, then one commit by whoever is free. Branches follow [AGENTS.md](../../../AGENTS.md) (`type/slug`, PR into protected `main`); merge at a stage gate, Sagar's PR first, then Arad rebases.

## Contracts (agree by 11:10, then locked)

**Tool function shape (Arad provides, Sagar calls):** `fn(db, args: dict) -> dict` · `snapshot(db, args) -> dict | None` · `undo(db, undo_args: dict) -> dict` (idempotent). Each returns the `_id` of what it wrote as `produced`.

**Core functions (Sagar provides, Arad calls):**
| Function | Returns |
|---|---|
| `register_tool(name, fn, snapshot, undo, undo_tool)` | — |
| `guarded_call(session_id, actor_id, tool, args, rationale, depends_on=[])` | `ToolResult{allowed, reason, result, seq}` |
| `ledger.verify(session_id)` | `(ok, first_bad_seq)` |
| `ledger.replay(session_id)` | ordered events |

**Solver (Arad provides, Planner calls):** `solve(candidates, envelope, caps) -> PlanResult{status, objective, lines, inputs_hash}`. Same inputs must give the same result.

**Tools:**
| Tool | Allowed actor | Undo | Stage |
|---|---|---|---|
| `propose_condition` | `agent:intake` | `withdraw_condition` | 3 |
| `approve_condition`, `reject_condition` | human with role `owner` for the asset's region | none | 3 |
| `propose_plan` | `agent:planner` | `supersede_plan` | 4 |
| `commit_budget` | `agent:programming` | `release_budget` | 2 |
| `create_work_order` | `agent:workorder` | `cancel_work_order` | 2 |
| `request_inspection` | `agent:orchestrator` | none | 3 |

**Policy checks (named in `policies.checks`, implemented in the gate):** `role` · `spend_limit` · `envelope` · `jurisdiction` · `has_commitment` · `in_approved_plan` (Stage 4).

**Collections** (control ones get `$jsonSchema`, `additionalProperties: false`):
| Collection | Fields |
|---|---|
| `principals` | `_id` (`user:<name>` or `agent:<role>`), `kind`, `roles[]`, `region`, `spend_limit`, `active` |
| `policies` | `tool`, `version`, `status` (`active`/`retired`), `roles[]`, `checks[{name, params}]`, `author`, `created_at` |
| `sessions` | `principal_id`, `task`, `region`, `budget_envelope`, `status`, `revert_for`, `aborted_by`, `audit_head`, `created_at`, `updated_at` |
| `tasks` | `session_id`, `type`, `agent_id`, `status` (`queued`/`claimed`/`done`/`failed`/`cancelled`), `input`, `output`, `created_at` |
| `audit_events` | `session_id`, `seq`, `ts`, `type`, `principal_id`, `actor_id`, `tool`, `args`, `policy_id`, `policy_version`, `decision`, `reason`, `rationale`, `before`, `after`, `depends_on[]`, `prev_hash`, `hash` |
| `saga_stack` | `session_id`, `seq`, `tool`, `undo_tool`, `undo_args`, `produced`, `depends_on[]`, `state` (`armed`/`done`/`compensated`/`comp_failed`) |
| `assets` | `_id`, `region`, plus fields chosen after the bridge file layout is read |
| `condition_records` | `asset_id`, ratings, `source`, `inspected_on`, `status` (`pending`/`approved`/`rejected`), `decided_by`, `reason` |
| `plans` | `session_id`, `inputs_hash`, `policy_versions`, `status`, `objective`, `lines[]` |
| `budget_ledger` | `session_id`, `asset_id`, `amount`, `status` (`committed`/`released`), `depends_on[]` |
| `work_orders` | `session_id`, `asset_id`, `budget_id`, `status` (`draft`/`released`/`cancelled`), `depends_on[]` |
| `inspection_requests` | `asset_id`, `reason`, `requested_by`, `status`, `created_at` |

**Session status:** `running` → `reverting` (set by the page with `revert_for`) → `running`; or `running` → `abort_requested` (set by the page) → `rolling_back` → `rolled_back`; or `completed` / `failed`. Only Sagar's orchestrator leaves `reverting` and `abort_requested`.

**Event types:** `session_started`, `decision`, `executed`, `failed`, `abort_observed`, `compensated`, `session_ended`.

**Indexes:** `audit_events` unique `{session_id, seq}` · `saga_stack` unique `{session_id, seq}` · `policies` unique `{tool, version}` and partial unique `{tool}` where `status: "active"` · `tasks` `{session_id, status}`.

**Hash:** SHA-256 of `prev_hash` + canonical JSON of the event without `hash`; `ts` truncated to milliseconds; first `prev_hash` is 64 zeros.

## Stage gate (run at every merge; do not start the next stage until it passes)
- [ ] `uv run pytest -q` passes on `main`.
- [ ] The stage's demo beat works twice in a row from `uv run python run_demo.py --reset`.
- [ ] `git grep -nE "mongodb(\+srv)?://[^<]" -- . ':!.env.example'` prints nothing.
- [ ] README "Built during the hackathon" lists the new feature; any new library and its licence is listed.
- [ ] Still inside the spec: no new feature that is not in a stage. New ideas go to README "Next".
- [ ] More than 20 minutes behind the stage's end time: apply the cut order in the spec, tell the other person.

## Stage 0 — Eligible (10:45–11:15, together)
- [ ] Re-read guide section 6 and Discord #questions for LLM access; note the provider.
- [x] Public repo `load-path` exists with protected `main`, `.gitignore`, `.env.example`, hooks and CI (ADLC-2).
- [ ] Sagar: MIT `LICENSE`; `.env.example` gains `LLM_API_KEY=<key>`; `pyproject.toml`. Arad's collaborator access confirmed.
- [ ] Together: `contracts.py` from the tables above; `db.py`; `AGENTS.md` holding the Global constraints, Ownership and Conflict rules sections of this plan.
- [ ] Arad: `setup_db.py` creates validators, indexes and seeds two humans (`user:owner_a` with a region and spend limit, `user:engineer_b` with a lower limit), the agent principals, and one active policy per Stage 2 tool.
- [ ] Check: `uv run python setup_db.py` twice without error; a `principals` insert missing `kind` fails with code 121; add venue IP to the Atlas access list.
- [ ] Commit, open PRs, run the stage gate.

## Stage 1 — Skeleton (11:15–12:00)
**S1 (Sagar) `core/ledger.py`, `core/gate.py`**
- [ ] Tests: `test_append_chains_hashes` (3 events, each `prev_hash` equals the prior `hash`) · `test_verify_flags_edit` (edit event 1, `verify` returns `(False, 1)`) · `test_deny_without_policy` (unknown tool: `allowed` false, target unchanged) · `test_decision_precedes_write` (decision `ts` ≤ the tool's write).
- [ ] Implement `append`, `verify`, `register_tool`, `guarded_call` with the `role` check only, against a stub tool writing to `scratch`.
- [ ] `uv run pytest tests/core -q` passes. Commit.

**A1 (Arad) `web/server.py`, `web/index.html`**
- [ ] `GET /events?session_id=` streams `audit_events` inserts from a change stream; the page lists them newest first. `POST /sessions/{id}/stop` sets `status: abort_requested`, `aborted_by`.
- [ ] Check: insert an event by hand in Compass; it appears on the page within 2 s. Commit.
- [ ] Merge both; stage gate. Beat: one allowed and one denied call appear on the page.

## Stage 2 — Base (12:00–13:15)
**S2 (Sagar)** remaining checks `spend_limit`, `envelope`, `jurisdiction`, `has_commitment`; fail closed.
- [ ] Tests: one deny per check with the target unchanged · `test_gate_denies_when_atlas_down` (client pointed at an unreachable host: `allowed` false).

**S3 (Sagar) `core/revert.py`:** saga entry `armed` before execute, `done` after; `rollback_session` compensates newest first and writes `compensated` events.
- [ ] Test: `test_rollback_restores_state` (two commits, one work order, rollback: all three collections equal their pre-run contents).

**S4 (Sagar) `core/orchestrator.py`, `core/agents.py`:** `tasks` claim loop; a thread watches the session; scripted mode drives Programming and Work Order agents from a fixed list.
- [ ] Tests: `test_stop_halts_and_rolls_back` (set `abort_requested` mid-run: status reaches `rolled_back`, measured under 2 s) · `test_stop_during_tool` (the running tool's `executed` event exists before `abort_observed`).

**A2 (Arad) `systems/budget.py`:** `commit_budget` / `release_budget`.
**A3 (Arad) `systems/workorders.py`:** `create_work_order` / `cancel_work_order`.
- [ ] Tests for each: write then undo restores the collection · undo twice equals undo once.

**A4 (Arad) `systems/assets.py`:** download one state's bridge file, read its layout, load one county into `assets` and approved `condition_records`. Record the chosen fields in `contracts.py` with Sagar.
- [ ] Check: the county's asset count in Atlas equals the row count filtered from the file.
- [ ] Merge; stage gate. Beat: agents commit, an over-limit commitment is denied, stop rolls back.

## Stage 3 — Approval (13:15–14:00)
**S5 (Sagar)** humans through the gate: `approve_condition`, `reject_condition` policies; rejection without `reason` refused by the validator.
**S6 (Sagar)** `revert_dependants(session_id, condition_id)`: on `status: reverting`, compensate every saga entry whose `depends_on` reaches that condition, newest first; call `request_inspection`; set `running`.
- [ ] Tests: `test_reject_reverts_only_dependants` (two assets committed, reject one condition: only that asset's budget and work order are reverted) · `test_reject_with_no_dependants` (nothing reverted, inspection request opened) · `test_agent_cannot_approve` (denied).

**A5 (Arad)** `propose_condition`, `approve_condition`, `reject_condition` tools; page shows pending conditions with approve and reject-with-reason; reject sets `status: reverting`, `revert_for`.
- [ ] Merge; stage gate. Beat: owner rejects, only dependants revert, an inspection request appears.
- [ ] **Record the fallback one-minute video now.**

## Stage 4 — MILP (14:00–14:45)
**A6 (Arad) `engine/plan.py`:** binary choice per candidate, maximise condition benefit, subject to the envelope and per-region caps.
- [ ] Tests: `test_solve_is_repeatable` (same inputs, same `lines` and `inputs_hash`) · `test_solve_respects_envelope` (sum of costs ≤ envelope) · a 3-item case with a known optimum.

**S7 (Sagar)** Planner agent calls `solve` via `propose_plan`; `in_approved_plan` check; after a revert, queue a re-plan task.
- [ ] Tests: `test_off_plan_commit_denied` · `test_envelope_lowered_denies_next` (existing commitments untouched).
- [ ] Merge; stage gate. Beat: the plan is solved from real data and re-solved after a rejection.

## Stage 5 — Stretch (14:45–15:30), in this order, each dropped if not passing by 15:30
- [ ] **A7 (Arad) `engine/forest.py`:** train on two consecutive years; report held-out accuracy and the "same as last year" baseline. Keep only if it beats the baseline; then `propose_condition` holds downstream tasks when the deviation is large.
- [ ] **S8 (Sagar)** policy replay: before a policy goes `active`, list past `decision` events that would flip.
- [ ] **S9 (Sagar)** Verifier agent: budget total equals the sum of committed lines; every work order has a commitment.

## Freeze and ship (15:30–16:45)
- [ ] 15:30 freeze. Only fixes for the demo script in the spec.
- [ ] Rehearse the 3-minute script three times from `--reset`. Arad drives the page, Sagar speaks.
- [ ] Sagar: README (problem, what was built today, assumptions, libraries and licences, how to run). Arad: one-minute video, uploaded and opened in a private window.
- [ ] 16:30 final stage gate on `main`; repo public; both names on the submission form; submit by 16:45.

## Plan self-review
- Spec coverage: AC1 S1 · AC2 S2 · AC3 S2 · AC4 S5 · AC5 S6 · AC6 S4 · AC7 S1 · AC8 A6 · AC9 Stage 0 and Freeze.
- Not covered by a test: page rendering (checked by hand at each gate) and LLM mode (scripted mode is the tested path).
