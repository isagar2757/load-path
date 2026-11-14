# Tracker

Single source of status. Phases: Spec → Plan → Build → Verify → Ship (`adlc` skill).
Status: `todo` · `active` · `blocked(<on what>)` · `done(<sha>)`.
IDs: `S*` Sagar (Claude Code) · `A*` Arad (Cursor) · `G*` stage gate (both) · `F*` freeze. Task IDs match the
[plan](docs/superpowers/plans/2026-11-14-event-build.md); tests and checks are defined there. Relay loop per item:
[shared-log.md](docs/adlc/shared-log.md#relay-one-task-start-to-merge). Branch `feat/<id>-<slug>`.

## Now
| ID | Owner | Item | Phase | Status | Depends on | Check (evidence for `task_done`) |
|---|---|---|---|---|---|---|
| S0 | Sagar | LICENSE, pyproject, `contracts.py`, `db.py`, lanes in AGENTS.md | Verify | active | — | PR #3: CI green; 12 passed. Merge |
| RELAY | Sagar | Relay loop: `--to`, `inbox`, `review`/`gate` events, item from branch, rules | Verify | active | S0 | `setup.sh` all ok; arad inbox shows a `--to arad` handoff |
| A0 | Arad | `setup_db.py`: validators, indexes (`contracts.INDEXES`), seed 2 humans, agents, one active policy per Stage 2 tool | Build | todo | S0 | runs twice without error; `principals` insert missing `kind` → code 121 |
| S1 | Sagar | `core/ledger.py` (`append`, `verify`), `core/gate.py` (`register_tool`, `guarded_call`, `role` check) | Verify | active | S0 | `uv run pytest tests/core -q`: chain, edit flagged, deny without policy, decision before write |
| A1 | Arad | `web/server.py` SSE `/events`, `POST /sessions/{id}/stop`; `web/index.html` feed | Build | todo | S0 | event inserted by hand appears on the page < 2 s |

## Ground truth
- 2026-11-14 — Shared log exists on the Atlas Sandbox: db `adlc`, collection `log`, indexes `item_ts`, `author_ts` (verified by insert and `find`).
- 2026-11-14 — `main` protected: PR required, checks `checks` and `tests` must pass, 0 approvals, no force push; secret scanning and push protection enabled (read back via API). CI negative case (a bad PR failing) not yet exercised: UNVERIFIED.
- 2026-11-14 — This repo is public. Keep personal notes, IPs and credentials out of it.

## Backlog (stage order; deadline = stage end, EST)
| ID | Owner | Item | Depends on | Check |
|---|---|---|---|---|
| G0 | both | Gate 0 · 11:15 | S0, A0 | pytest green on `main`; Arad `setup.sh` all ok; venue IP on access list; LLM provider noted or scripted-only |
| G1 | both | Gate 1 · 12:00 | S1, A1 | one allowed and one denied call on the page, twice from `--reset` |
| S2 | Sagar | Checks `spend_limit`, `envelope`, `jurisdiction`, `has_commitment`; fail closed | S1 | one deny per check, target unchanged; `test_gate_denies_when_atlas_down` |
| A2 | Arad | `systems/budget.py`: `commit_budget` / `release_budget` (atomic, idempotent) | A0 | write+undo restores; undo twice = once |
| A3 | Arad | `systems/workorders.py`: `create_work_order` / `cancel_work_order` | A0 | same as A2 |
| A4 | Arad | `systems/assets.py`: one county into `assets` + approved `condition_records`; fields agreed into `contracts.py` | A0 | Atlas count = filtered row count |
| S3 | Sagar | `core/revert.py`: saga `armed`→`done`, `rollback_session` newest first | S1, A2, A3 | `test_rollback_restores_state` |
| S4 | Sagar | `core/orchestrator.py`, `core/agents.py`: task claim loop, session watcher, scripted mode | S3 | `test_stop_halts_and_rolls_back` < 2 s; `test_stop_during_tool` |
| G2 | both | Gate 2 · 13:15 | S2–S4, A2–A4 | agents commit, over-limit denied, stop rolls back |
| S5 | Sagar | Human tools through the gate; rejection without `reason` refused | G2 | `test_agent_cannot_approve` |
| S6 | Sagar | `revert_dependants` + `request_inspection` | S5 | `test_reject_reverts_only_dependants`, `test_reject_with_no_dependants` |
| A5 | Arad | Condition tools; page pending list, approve, reject-with-reason → `reverting` | G2 | by hand on the page |
| G3 | both | Gate 3 · 14:00 + record fallback video | S5, S6, A5 | reject reverts only dependants; inspection request appears |
| A6 | Arad | `engine/plan.py` MILP | A4 | `test_solve_is_repeatable`, `test_solve_respects_envelope`, 3-item optimum |
| S7 | Sagar | Planner via `propose_plan`; `in_approved_plan`; re-plan after revert | A6, G3 | `test_off_plan_commit_denied`, `test_envelope_lowered_denies_next` |
| G4 | both | Gate 4 · 14:45 | A6, S7 | plan from real data, re-solved after a rejection |
| A7 | Arad | `engine/forest.py` (stretch) | G4 | beats "same as last year" on held-out, else dropped |
| S8 | Sagar | Policy replay (stretch) | G4 | lists flipped decisions |
| S9 | Sagar | Verifier agent (stretch) | G4 | budget total = committed lines; every WO has a commitment |
| G5 | both | Freeze · 15:30 | — | cut order applied; `main` green |
| F1 | Sagar | README: problem, built today, assumptions, libraries + licences, run steps | G5 | read by Arad |
| F2 | Arad | One-minute video, uploaded, opened in a private window | G5 | link opens |
| F3 | both | Rehearse ×3 from `--reset`; final gate 16:30; submit 16:45 | F1, F2 | submission confirmation |

## Open decisions
| ADR | Question | Status |
|---|---|---|

## Done
- ADLC-2 branch workflow, hooks, CI, protected main, shared log client (a57fe7e)
- ADLC-1 shared log, convention, Arad onboarding prompt (c1be56c)

## Log
- 2026-11-14 — S1: `core/ledger.py`, `core/gate.py`, `tests/core/` on `feat/s1-ledger-gate`. `uv run pytest -q`: 24 passed (Atlas); without `MONGODB_URI`: 11 passed, 13 skipped. `guarded_call` and ledger functions take an optional `db=` keyword (tests pass `capital_test`); default is `db.get_db()`. Checks other than `role` deny as `not implemented` until S2.
- 2026-11-14 — Tracker and shared ADLC docs added on `main` by agreement as a one-off; later work goes through branches.
- 2026-11-14 — ADLC-2: hooks (pre-commit, commit-msg, post-commit Mongo log, pre-push), `scripts/check.sh` shared with CI, `scripts/adlc_log.py`, `scripts/setup.sh`, Claude skill + SessionStart hook, Cursor rule, CI workflow, PR template. Local run: `setup.sh` all ok.
- 2026-11-14 — RELAY: relay loop added; `ADLC_AUTHOR` required (`sagar`/`arad`); stages broken into S*/A*/G*/F* rows.
- 2026-11-14 — S0: spec, plan, formulas imported from the local prep repo as a cleaned copy (employer note, machine paths, Discord notes, score estimate removed; branch rule follows AGENTS.md). Arad owns `setup_db.py`.
- 2026-11-14 — PR #1 squash-merged (a57fe7e), CI green on it. Arad's GitHub collaborator access: UNVERIFIED (username not given).
