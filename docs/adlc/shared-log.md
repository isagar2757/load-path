# Shared ADLC log

Working log for the two of us and our agents. Process tooling: not part of the solution and not shown in the demo.
`TRACKER.md` stays the status file; this is the event feed.

- Location: hackathon Atlas Sandbox, database `adlc`, collection `log`. Connection string only in `.env` (gitignored).
- Indexes: `{item, ts}`, `{author, ts}`. No schema validator; follow the table.
- Write: MongoDB MCP `insert-many` on `adlc.log`. Read: `find`, sort `ts` descending.
- One document per event. Never store secrets or connection strings.

| Field | Value |
|---|---|
| `ts` | Date (UTC) |
| `author` | `sagar` or `arad` |
| `actor` | `human` or the agent name |
| `tool` | `claude-code` or `cursor` |
| `item` | tracker or plan task ID |
| `phase` | `Spec` `Plan` `Build` `Verify` `Ship` |
| `event` | `task_start` `task_done` `decision` `blocker` `handoff` `test_run` `commit` `question` |
| `summary` | one line |
| `evidence`, `commit_sha`, `files[]`, `refs[]` | optional |
