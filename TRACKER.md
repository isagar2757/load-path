# Tracker

Single source of status. Phases: Spec → Plan → Build → Verify → Ship (`adlc` skill).
Status: `todo` · `active` · `blocked(<on what>)` · `done(<sha>)`.

## Now
| ID | Item | Phase | Status | Next action | Links |
|---|---|---|---|---|---|
| ADLC-1 | Shared ADLC setup for Sagar and Arad | Build | active | Arad runs the onboarding prompt; then move to branches with pre-commit hooks (review, secret scan) | [log](docs/adlc/shared-log.md) [prompt](docs/adlc/prompts/00-arad-understand.md) |

## Ground truth
- 2026-11-14 — Shared log exists on the Atlas Sandbox: db `adlc`, collection `log`, indexes `item_ts`, `author_ts` (verified by insert and `find`).
- 2026-11-14 — This repo is public. Keep personal notes, IPs and credentials out of it.

## Backlog
| ID | Item | Phase | Status | Depends on | Links |
|---|---|---|---|---|---|
| ADLC-2 | Branch workflow, Conventional Commits, git hooks, agent rules, dependency doc | Verify | active | ADLC-1 | [AGENTS.md](AGENTS.md) [deps](docs/DEPENDENCIES.md) |

## Open decisions
| ADR | Question | Status |
|---|---|---|

## Done
- ADLC-1 shared log, convention, Arad onboarding prompt (c1be56c)

## Log
- 2026-11-14 — Tracker and shared ADLC docs added on `main` by agreement as a one-off; later work goes through branches.
- 2026-11-14 — ADLC-2: hooks (pre-commit, commit-msg, post-commit Mongo log, pre-push), `scripts/check.sh` shared with CI, `scripts/adlc_log.py`, `scripts/setup.sh`, Claude skill + SessionStart hook, Cursor rule, CI workflow, PR template. Local run: `setup.sh` all ok.
