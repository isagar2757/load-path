---
name: adlc-log
description: Use when starting, finishing, deciding, being blocked, handing off, reviewing or testing work in this repo. Appends an event to the shared Mongo ADLC log (db adlc, collection log) and runs the relay loop with Arad's Cursor agent.
---

# adlc-log

The session-start hook printed your inbox (events addressed to sagar) and the latest 10 events. Act on the inbox first.
Follow the relay loop in `docs/adlc/shared-log.md` (pick → start → red → green → ship → review → fix → merge → gate).

```
uv run scripts/adlc_log.py add --item <ID> --phase <Spec|Plan|Build|Verify|Ship> \
  --event <task_start|task_done|decision|blocker|handoff|test_run|question|review|gate> \
  --summary "<one line>" [--to arad] [--evidence "<command output line>"]
uv run scripts/adlc_log.py inbox            # addressed to me
uv run scripts/adlc_log.py tail -n 30 [--item <ID>]
```
- `test_run` after red and after green, with the pytest summary line as evidence.
- PR ready: `handoff --to arad --summary "review PR #<n>"`. Reviewing Arad's PR: `review --to arad` with `pass` or `fail: <reason>`.
- Commits log themselves (item from the branch `feat/<id>-<slug>`); do not log them by hand.
- Never write secrets. If the script fails, say so and fix `.env` (`MONGODB_URI`, `ADLC_AUTHOR`); do not skip silently.
