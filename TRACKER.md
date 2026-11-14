# Tracker

Status lives in Mongo, not here: sandbox db `adlc`, collection `items` (one doc per item). Events in `adlc.log`
update it; nobody edits status by hand. Convention: [shared-log.md](docs/adlc/shared-log.md).

```
uv run scripts/adlc_log.py board                # active, blocked, READY (todo, deps done)
uv run scripts/adlc_log.py board --owner arad   # one lane (+ both)
uv run scripts/adlc_log.py board --all          # every item, incl. waiting and done
```
Phases: Spec → Plan → Build → Verify → Ship. IDs: `S*` Sagar · `A*` Arad · `G*` gate (both) · `F*` freeze.
Task IDs, tests and checks: [plan](docs/superpowers/plans/2026-11-14-event-build.md). Branch `feat/<id>-<slug>`.

This file keeps only what does not change per task: ground truth and decisions.

## Ground truth
- 2026-11-14 — Shared log exists on the Atlas Sandbox: db `adlc`, collection `log`, indexes `item_ts`, `author_ts` (verified by insert and `find`).
- 2026-11-14 — `main` protected: PR required, checks `checks` and `tests` must pass, 0 approvals, no force push; secret scanning and push protection enabled (read back via API). CI negative case (a bad PR failing) not yet exercised: UNVERIFIED.
- 2026-11-14 — Status moved to `adlc.items` (seeded from this file's tables; S0, RELAY, S1 done; A0 active/Verify from Arad's log events).
- 2026-11-14 — Data: `capital.assets` = 206 Highway 401 structures inside a Toronto lat/long box from Ontario bridge conditions 2020 (OGL-Ontario); BCI 0–100. Gardiner is city-owned, not in the file.
- 2026-11-14 — Speed mode until the demo (decision on A4): one machine, CI workflows disabled, `push --no-verify`, admin merge; full suite and cleanup after features land.
- 2026-11-14 — Stage 2 beat (`run_demo.py --reset --auto-stop`) green twice on main e6d363b: 3 allow, over-limit deny, rollback 3, 0 committed left. Page run by hand: UNVERIFIED.
- 2026-11-14 — This repo is public. Keep personal notes, IPs and credentials out of it.

## Open decisions
| ADR | Question | Status |
|---|---|---|

## History (before status moved to Mongo)
- 2026-11-14 — S1 merged (PR #6, CI green, review waived by Sagar for the hackathon).
- 2026-11-14 — S1: `core/ledger.py`, `core/gate.py`, `tests/core/` on `feat/s1-ledger-gate`. `uv run pytest -q`: 24 passed (Atlas); without `MONGODB_URI`: 11 passed, 13 skipped. `guarded_call` and ledger functions take an optional `db=` keyword (tests pass `capital_test`); default is `db.get_db()`. Checks other than `role` deny as `not implemented` until S2.
- 2026-11-14 — S1 `/code-review` (medium): fixed post-execution ledger failure escaping `guarded_call`, `policy.roles` always enforced (beyond formulas §1: role binds even if not listed in `checks`), guarded `audit_head` update, `verify` flags tail truncation via `audit_head`, ledger stamps `ts` itself, driver error text kept out of `reason`. Deferred: unserialisable args deny without a ledger record; deny events written for unknown or ended sessions; `append` relies on the unique index from `setup_db.py` (A0). `uv run pytest -q`: 28 passed.
- 2026-11-14 — Tracker and shared ADLC docs added on `main` by agreement as a one-off; later work goes through branches.
- 2026-11-14 — ADLC-2: hooks (pre-commit, commit-msg, post-commit Mongo log, pre-push), `scripts/check.sh` shared with CI, `scripts/adlc_log.py`, `scripts/setup.sh`, Claude skill + SessionStart hook, Cursor rule, CI workflow, PR template. Local run: `setup.sh` all ok.
- 2026-11-14 — RELAY: relay loop added; `ADLC_AUTHOR` required (`sagar`/`arad`); stages broken into S*/A*/G*/F* rows.
- 2026-11-14 — S0: spec, plan, formulas imported from the local prep repo as a cleaned copy (employer note, machine paths, Discord notes, score estimate removed; branch rule follows AGENTS.md). Arad owns `setup_db.py`.
- 2026-11-14 — PR #1 squash-merged (a57fe7e), CI green on it. Arad's GitHub collaborator access: UNVERIFIED (username not given).
