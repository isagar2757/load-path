---
name: run-demo
description: Use when asked to run, start, demo, test or record the load-path app, its page or the demo script, or when a demo run crashes with a missing session. Gives the exact commands, the click sequence and the one rule that prevents two people from wiping each other's run.
---

# Run the demo

## Once per machine
```
./scripts/setup.sh                      # hooks, .env, Atlas check
uv sync
```
`.env` needs `MONGODB_URI` and `ADLC_AUTHOR`. `LLM_API_KEY` only for `--llm`.

## Your own database (do this before testing in parallel)
`run_demo.py --reset` deletes every session in the database it runs on. Two runs on one database crash each
other (`'NoneType' object is not subscriptable`, or "the session was deleted"). Give yourself a database:
```
echo 'CAPITAL_DB=capital_<yourname>' >> .env
uv run python setup_db.py               # prints: setup_db ok (capital_<yourname>)
uv run python -m systems.assets         # prints 198; needs the data file, see README "Run steps"
```
Leave `CAPITAL_DB` unset only for the shared rehearsal on `capital`, one run at a time.

## Run
```
uv run uvicorn web.server:app --port 8000        # terminal 1: the page
uv run python run_demo.py --reset                # terminal 2: interactive; prints the page URL
uv run python run_demo.py --reset --auto         # no page; human actions go through the same server routes
uv run python run_demo.py --reset --auto --llm   # agents pick from code-built options and write the rationale
```
Add `--wait 0 --step 0` to skip the pauses. The script prints one line per beat and ends with `demo ok`; it
exits 1 and names the beat when an allow, deny or end state differs.

## Interactive click sequence (page opened from the printed URL)
1. A MOCK condition appears under Pending: as `user:owner_a`, Approve. The plan, one commitment, one work order
   and two DENY rows follow.
2. A second pending condition appears with its own commitment and work order: switch the actor to
   `user:engineer_b` and Approve. Expect a DENY (role).
3. Switch back to `user:owner_a`, type a reason, Reject. Only that bridge's commitment and work order revert,
   an inspection request opens, the plan is re-solved without that bridge.
4. Stop. Status `rolled_back`, no committed lines left. Stop at any earlier point also ends cleanly.

## Tests
```
uv run pytest -q tests/<path>/<file>.py   # one file at a time against Atlas; each test uses capital_test_<suffix>
```

## When it fails
- Session or condition missing mid-run: someone else ran `--reset` on the same database. Set `CAPITAL_DB`.
- `need 3 assets in region r1`: run `uv run python -m systems.assets` for your database.
- `--llm` rationales look scripted: the model reply was invalid or the key is missing; the scripted step ran.
