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

## Runtime stack (`pyproject.toml`, locked in `uv.lock`)
Python 3.13.3. Versions and licences read from installed package metadata after `uv sync`, 2026-11-14 (Sagar). Arad's machine: UNVERIFIED (`uv sync && uv run pytest -q`).
| Package | Version | Licence | Purpose | Owner |
|---|---|---|---|---|
| pymongo | 4.20.0 | Apache-2.0 | Atlas driver | both |
| certifi | 2026.10.23 | MPL-2.0 | CA bundle passed as `tlsCAFile` | both |
| pydantic | 2.14.3 | MIT | Shapes in `contracts.py` | both |
| scipy | 1.18.1 | BSD-3-Clause (read from `LICENSE.txt`; bundled components list their own licences there) | `scipy.optimize.milp` (HiGHS) | Arad |
| scikit-learn | 1.9.1 | BSD-3-Clause | Random forest (Stage 5) | Arad |
| fastapi | 0.162.7 | MIT | Web server, SSE feed | Arad |
| uvicorn | 0.54.0 | BSD-3-Clause | ASGI server | Arad |
| pytest (dev) | 9.2.0 | MIT | Tests | both |

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
