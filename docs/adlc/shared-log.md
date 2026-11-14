# Shared ADLC log

Working log for the two of us and our agents. Process tooling: not part of the solution and not shown in the demo.
`TRACKER.md` stays the status file; this is the event feed.

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
| `event` | `task_start` `task_done` `decision` `blocker` `handoff` `test_run` `commit` `question` |
| `summary` | one line |
| `evidence`, `commit_sha`, `files[]`, `refs[]` | optional |
