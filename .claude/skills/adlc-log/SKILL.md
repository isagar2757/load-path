---
name: adlc-log
description: Use when starting, finishing, deciding, being blocked, handing off, reviewing or testing work in this repo, or when asked for status, the board or the next item. Reads status from Mongo adlc.items, appends events to adlc.log (which move status), and runs the relay loop with Arad's Cursor agent.
---

# adlc-log

The session-start hook printed your inbox, the board (status from `adlc.items`) and the latest events. Act on the inbox first, then take a READY item.
Status lives only in `adlc.items`; events move it. Do not edit status in TRACKER.md.
Follow the relay loop in `docs/adlc/shared-log.md` (pick → start → red → green → ship → review → fix → merge → gate).

```
uv run scripts/adlc_log.py add --item <ID> --phase <Spec|Plan|Build|Verify|Ship> \
  --event <task_start|task_done|decision|blocker|handoff|test_run|question|review|gate> \
  --summary "<one line>" [--to arad] [--evidence "<command output line>"]
uv run scripts/adlc_log.py board [--owner sagar] [--all]   # status; READY = deps done
uv run scripts/adlc_log.py inbox            # addressed to me
uv run scripts/adlc_log.py tail -n 30 [--item <ID>]
```
- `test_run` after red and after green, with the pytest summary line as evidence.
- PR ready: `handoff --to arad --summary "review PR #<n>"`. Reviewing Arad's PR: `review --to arad` with `pass` or `fail: <reason>`.
- After merge: `task_done --sha <merge sha>` sets the item done.
- Commits log themselves (item from the branch `feat/<id>-<slug>`); do not log them by hand.
- Never write secrets. If the script fails, say so and fix `.env` (`MONGODB_URI`, `ADLC_AUTHOR`); do not skip silently.
