# Tracker

Single source of status. Phases: Spec → Plan → Build → Verify → Ship (`adlc` skill).
Status: `todo` · `active` · `blocked(<on what>)` · `done(<sha>)`.

## Now
| ID | Item | Phase | Status | Next action | Links |
|---|---|---|---|---|---|
| S0 | Stage 0: contracts, db.py, AGENTS lanes, setup_db.py | Verify | active | Sagar's part on `docs/s0-import-spec` (12 tests pass). Push + PR; Arad: `setup_db.py` against `contracts.py`, then code-121 check and venue IP on access list | [spec](docs/superpowers/specs/2026-11-13-audited-agent-design.md) · [plan](docs/superpowers/plans/2026-11-14-event-build.md) · [formulas](docs/formulas.md) |

## Ground truth
- 2026-11-14 — Shared log exists on the Atlas Sandbox: db `adlc`, collection `log`, indexes `item_ts`, `author_ts` (verified by insert and `find`).
- 2026-11-14 — `main` protected: PR required, checks `checks` and `tests` must pass, 0 approvals, no force push; secret scanning and push protection enabled (read back via API). CI negative case (a bad PR failing) not yet exercised: UNVERIFIED.
- 2026-11-14 — This repo is public. Keep personal notes, IPs and credentials out of it.

## Backlog
| ID | Item | Phase | Status | Depends on | Links |
|---|---|---|---|---|---|

## Open decisions
| ADR | Question | Status |
|---|---|---|

## Done
- ADLC-2 branch workflow, hooks, CI, protected main, shared log client (a57fe7e)
- ADLC-1 shared log, convention, Arad onboarding prompt (c1be56c)

## Log
- 2026-11-14 — Tracker and shared ADLC docs added on `main` by agreement as a one-off; later work goes through branches.
- 2026-11-14 — ADLC-2: hooks (pre-commit, commit-msg, post-commit Mongo log, pre-push), `scripts/check.sh` shared with CI, `scripts/adlc_log.py`, `scripts/setup.sh`, Claude skill + SessionStart hook, Cursor rule, CI workflow, PR template. Local run: `setup.sh` all ok.
- 2026-11-14 — S0: spec, plan, formulas imported from the local prep repo as a cleaned copy (employer note, machine paths, Discord notes, score estimate removed; branch rule follows AGENTS.md). Arad owns `setup_db.py`.
- 2026-11-14 — PR #1 squash-merged (a57fe7e), CI green on it. Arad's GitHub collaborator access: UNVERIFIED (username not given).
