# Shared ADLC state

Working log for the two of us and our agents. Process tooling: not part of the solution and not shown in the demo.
Two collections in db `adlc`: `items` = status (the only status source), `log` = event feed.
`add` writes the event and moves the item's status; `board` shows it. `TRACKER.md` keeps only ground truth and decisions.

## Status (`adlc.items`)
| Event | Item becomes |
|---|---|
| `task_start` | `active` |
| `blocker` | `blocked` (summary kept as `blocked_on`) |
| `task_done`, `gate` | `done` (`--sha` or evidence kept) |
| any event with `--phase` | phase updated |
| `commit` and others | no change |

Read: `adlc_log.py board [--owner sagar|arad] [--all]` (default: active, blocked, READY = todo with every dependency done; `--all`: every item).
Add or edit an item (new task, changed check, dropped stretch): `adlc_log.py item <ID> --owner ... --title ... --depends ... --check ... [--status dropped]`, then log a `decision --to <other>`.

## Events (`adlc.log`)

- Location: hackathon Atlas Sandbox, database `adlc`, collection `log`. Connection string only in `.env` (gitignored).
- Indexes: `{item, ts}`, `{author, ts}`. No schema validator; follow the table.
- Write: `uv run scripts/adlc_log.py add ...`. Read: `uv run scripts/adlc_log.py tail`. Commits are logged by `.githooks/post-commit`; failures land in `.git/adlc-log.err`.
- Claude Code prints the latest 10 events at session start (`.claude/settings.json`). Skill: `adlc-log`. Cursor rule: `.cursor/rules/adlc.mdc`.
- One document per event. Never store secrets or connection strings.

| Field | Value |
|---|---|
| `ts` | Date (UTC) |
| `author` | `sagar` or `arad` |
| `actor` | `human` or the agent name |
| `tool` | `claude-code`, `cursor`, `git` (post-commit hook) or `human` |
| `item` | tracker or plan task ID |
| `phase` | `Spec` `Plan` `Build` `Verify` `Ship` |
| `event` | `task_start` `task_done` `decision` `blocker` `handoff` `test_run` `commit` `question` `review` `gate` |
| `to` | `sagar` or `arad`: the person who must act (handoff, question, review, blocker) |
| `summary` | one line |
| `evidence`, `commit_sha`, `files[]`, `refs[]` | optional |

`author` comes from `ADLC_AUTHOR` in `.env` (`sagar` or `arad`; `add` refuses anything else). Commits take
`item` from the branch: `feat/a0-setup-db` → `A0`.

## Relay: one task, start to merge
Sagar works in Claude Code, Arad in Cursor. Both agents follow the same loop. Item IDs are the tracker's.

| Step | Who | Command / action | Done when |
|---|---|---|---|
| 1 Pick | agent | `adlc_log.py inbox`, then `board --owner <me>`; take a READY item; `tail --item <ID>`; read its plan task | inbox empty or answered |
| 2 Start | agent | branch `feat/<id>-<slug>`; `add --item <ID> --event task_start --phase Build` | event logged |
| 3 Red | agent | write the plan task's tests; run them; `--event test_run --evidence "<n> failed"` | tests fail for the right reason |
| 4 Green | agent | implement in own lane only; `--event test_run --evidence "<n> passed"` | `uv run pytest -q` green |
| 5 Ship | agent | commit (hooks log it), push, PR; `--event handoff --to <other> --summary "review PR #<n>"` | PR open, CI green |
| 6 Review | other agent | read the diff against the plan task, `contracts.py` and the AGENTS.md design bar; `--event review --to <author> --summary "pass"` or `"fail: <rule #> <file:line> <fix>"` | pass logged |
| 7 Fix | agent | on `fail`, back to step 4 on the same branch; max 2 rounds, then `--event blocker --to <other>` | pass logged |
| 8 Merge | human | merge the PR; agent logs `--event task_done --sha <merge sha>` (sets the item done) | on `main` |
| 9 Gate | both | at a stage gate run the plan's checklist; `--event gate --item G<n> --evidence "<pytest line>; beat ok x2"` | gate logged |

Rules:
- Need something from the other lane: `--event question --to <other>`; never edit their file.
- `contracts.py` change: `question` → both agree → `decision` event → one commit.
- Blocked over 10 minutes: `--event blocker --to <other>`, then take the next unblocked item in your lane.
- Evidence is a command and its output line, never "works".
