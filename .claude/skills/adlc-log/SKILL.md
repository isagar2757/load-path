---
name: adlc-log
description: Use when starting, finishing, deciding, being blocked, handing off or testing work in this repo. Appends an event to the shared Mongo ADLC log (db adlc, collection log) so both teammates and their agents see current state.
---

# adlc-log

The session-start hook already printed the latest 10 events. Read them before choosing work.

Log with the script (never write secrets):
```
uv run scripts/adlc_log.py add --item <ID> --phase <Spec|Plan|Build|Verify|Ship> \
  --event <task_start|task_done|decision|blocker|handoff|test_run|commit|question> \
  --summary "<one line>" [--evidence "<command output excerpt>"] [--tool claude-code]
```
- Log `task_start` when you begin an item, `task_done` with evidence (test output) when its gate passes, `decision` for anything another person must know, `blocker` and `handoff` when work crosses the lane.
- Commits are logged automatically by the post-commit hook; do not log them by hand.
- Read more: `uv run scripts/adlc_log.py tail -n 30 [--item <ID>]`.
- If the script fails, say so and fix `MONGODB_URI`; do not skip silently. Convention: `docs/adlc/shared-log.md`.
