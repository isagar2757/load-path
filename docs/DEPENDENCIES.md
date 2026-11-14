# Dependencies, plugins, MCP servers

One row per item. Update in the same commit that adds, changes or removes it. Verified = command run in this repo's session or on that person's machine.

## Claude Code plugins (user scope, Sagar)
| Name | Version | Purpose | Verified |
|---|---|---|---|
| superpowers@anthropic-plugin-directory | 7.0.2 | Phase skills: brainstorming, plans, TDD, review, debugging | 2026-11-14 `claude plugin list` |
| mongodb-self-managed-mcp@anthropic-plugin-directory | 1.2.1 | MongoDB MCP server and skills; reads `MDB_MCP_CONNECTION_STRING` | 2026-11-14 `claude plugin list` |

## MCP servers
| Server | Used for | Owner | Verified |
|---|---|---|---|
| mongodb (via plugin above) | `adlc.log` writes and reads, ad-hoc queries on the sandbox | Sagar | 2026-11-14 insert and `find` on `adlc.log` |
| Arad's MongoDB MCP in Cursor | same | Arad | UNVERIFIED: Arad confirms connection |

## Runtime stack (planned, not yet in a manifest)
Verified once on Sagar's Mac, 2026-11-13, in a throwaway uv env: Python 3.13.3, pymongo 4.20.0, certifi 2026.10.23, scipy 1.18.1, scikit-learn 1.9.1, fastapi 0.162.7, uvicorn 0.54.0, pydantic 2.14.3. Pin in `pyproject.toml` at Stage 0 and replace this paragraph with a table. Arad's machine: UNVERIFIED.

## Tooling
| Tool | Version | Purpose |
|---|---|---|
| uv | 0.13.8 | Python and env management |
| git hooks (`.githooks/`, `scripts/check.sh`) | n/a | pre-commit, commit-msg, post-commit (Mongo log), pre-push; no external dependency |
| `scripts/adlc_log.py` | n/a | Shared log client; uv inline deps: pymongo>=4.7, certifi |
| GitHub Actions `ci.yml` | actions/checkout@v4, astral-sh/setup-uv@v5 | Same checks as the hooks on every PR; pytest when `tests/` exists |
| Branch protection on `main` | n/a | PR required, `checks` and `tests` must pass |

## Project skills and rules
| Name | Where | Purpose |
|---|---|---|
| adlc-log | `.claude/skills/adlc-log/` | Teaches Claude Code when and how to log |
| adlc rule | `.cursor/rules/adlc.mdc` | Same for Cursor (always applied) |
| SessionStart hook | `.claude/settings.json` | Prints latest 10 log events at session start |
