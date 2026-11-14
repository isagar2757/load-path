# Rules for agents and humans

Applies to Claude Code, Cursor and any other agent. `CLAUDE.md` imports this file.

## Workflow (ADLC)
- Status lives only in Mongo `adlc.items`; see it with `uv run scripts/adlc_log.py board`. Phases: Spec → Plan → Build → Verify → Ship. One chat per item.
- Events go to `adlc.log` with `uv run scripts/adlc_log.py add ...` and move the item's status (`task_start` → active, `blocker` → blocked, `task_done`/`gate` → done). Commits log themselves. [Convention](docs/adlc/shared-log.md).
- `TRACKER.md` holds only ground truth and decisions. Never edit status by hand in two places.
- Either person (or agent) may update ADLC files (`TRACKER.md`, `docs/adlc/`, `scripts/`, `.githooks/`, agent rules) for both, via PR, with a `decision --to <other>` event.
- New clone: `./scripts/setup.sh` (hooks, `.env`, Atlas check). It prints what is missing.
- No guessing. Verify by reading or running; otherwise write `UNVERIFIED` plus the command that would verify it.

## Git
- Never commit or push to `main`. Branch `type/slug`, open a PR, the other person or a review pass approves.
- Conventional Commits, one logical change per commit, status changes come from logged events, not commits.
- Hooks (installed by `./scripts/setup.sh`): branch guard, secret scan, docs sync, filler check, commit-msg, post-commit log, pre-push tests. CI repeats the checks on every PR; `main` is protected. `--no-verify` only with the other person's agreement.
- Before a PR: `/code-review`; add `/security-review` when secrets, auth, PII or external input are touched.

## Secrets
- Connection strings and keys only in `.env` (gitignored). `.env.example` holds placeholders. The repo is public.
- Python MongoDB clients use `tlsCAFile=certifi.where()`.

## Docs
- Concise, factual, present tense. No marketing words, no summaries of what the reader just read.
- Every plugin, MCP server, library, CLI or model added or removed updates [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md) in the same commit: name, version, purpose, owner, how it was verified. The docs-sync hook enforces this for manifest files; for global installs (plugins, CLIs) it is on you.
- Decisions go in `docs/adr/NNNN-slug.md` (Status, Context, Decision, Consequences). The tracker links to them.
- Only use code, data and assets we have rights to. Record the licence of anything copied in.

## Hackathon guards
- Project data layer is the sandbox cluster only. No personal Atlas, no local MongoDB.
- Demo and video show only what was built during the event.
- Check ideas against the anti-project list: no basic RAG, no Streamlit, no dashboard as the main feature.

## Event build: constraints
Spec, plan and formulas: [spec](docs/superpowers/specs/2026-11-13-audited-agent-design.md) · [plan](docs/superpowers/plans/2026-11-14-event-build.md) · [formulas](docs/formulas.md).
- Database `capital`; each test uses its own `capital_test_<suffix>` and drops it (a shared name races between our runs). Get a handle only through `db.get_db()`.
- Nothing from an employer, no vendor product names, no safety or engineering judgment.
- The page is a control surface (feed, approve/reject, stop). No chart-only views.
- Code does all arithmetic. The LLM picks from listed options and writes the rationale.
- Treatment costs are assumptions; the README says so.
- Every tool call, agent or human, goes through `guarded_call`. Nothing else writes to a domain collection after seeding.
- Tests that need Atlas skip when `MONGODB_URI` is unset (CI has none).

## Design bar (both agents; reviews enforce it)
A PR that breaks a rule below fails review. The reviewer cites the rule number.
1. Build what the plan task and `contracts.py` say. No extra collections, fields, endpoints, flags, layers or abstractions. A gap is a `question --to <other>`, not an invention.
2. Names, fields, statuses and tool names come from `contracts.py`; import them, never retype the strings.
3. Tools match the `contracts.py` shape: `fn(db, args)` returns `produced`; `snapshot`; `undo` idempotent. Domain writes are single atomic updates (no read-then-write; formulas §4) and run only via `guarded_call`.
4. Fail closed: no bare `except` that hides an error; no default that turns a missing value into an allow.
5. Each test the plan names exists under that name; a red `test_run` event precedes the green one. No test that only asserts a mock was called.
6. Smallest code that passes: no dead code, commented-out code, unused parameters, or TODO without a tracker item. A new library needs a `docs/DEPENDENCIES.md` row.
7. Page: the control surface in the constraints above; every button calls the server, the server calls `guarded_call`.

## Review loop
- Reviewer: read the diff against the plan task, `contracts.py`, `docs/formulas.md` and the design bar; run `uv run pytest -q`. Log `review --to <author>` with `pass` or `fail: <rule #> <file:line> <fix>`, one line per finding.
- Author: fix every finding on the same branch, or reply `question --to <reviewer>` with evidence. No silent skips, no merging over a `fail`.
- After two `fail` rounds on the same item: `blocker --to <other>`; the two people decide.

## Event build: lanes and ownership
| Path | Owner |
|---|---|
| `contracts.py`, `db.py`, `pyproject.toml`, `.env.example`, `LICENSE`, `README.md`, `AGENTS.md` | both (README sections: whoever built the feature) |
| `core/` (gate, ledger, revert, orchestrator, agents), `tests/core/`, `run_demo.py` | Sagar |
| `setup_db.py`, `systems/`, `engine/`, `web/`, `tests/systems/`, `tests/engine/` | Sagar (pair on one machine from 17:14 until the demo; decision on A2) |

- Never edit a file you do not own; ask its owner.
- `contracts.py` is locked after Stage 0. A change needs both to agree out loud, then one commit by whoever is free.
- Merge only at a stage gate (plan, section Stage gate): Sagar's PR first, then Arad rebases.
