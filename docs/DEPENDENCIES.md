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
| mongodb (via plugin above) | `adlc.log` / `adlc.items` writes and reads, ad-hoc queries on the sandbox | Sagar | 2026-11-14 insert and `find` on `adlc.log` |
| Arad's MongoDB MCP in Cursor | same | Arad | UNVERIFIED: Arad confirms connection |

## Runtime stack (`pyproject.toml`, locked in `uv.lock`)
Python 3.13.3. Versions and licences read from installed package metadata after `uv sync`, 2026-11-14 (Sagar). Arad's machine: UNVERIFIED (`uv sync && uv run pytest -q`).
| Package | Version | Licence | Purpose | Owner |
|---|---|---|---|---|
| pymongo | 4.20.0 | Apache-2.0 | Atlas driver | both |
| certifi | 2026.10.23 | MPL-2.0 | CA bundle passed as `tlsCAFile` | both |
| pydantic | 2.14.3 | MIT | Shapes in `contracts.py` | both |
| scipy | 1.18.1 | BSD-3-Clause (read from `LICENSE.txt`; bundled components list their own licences there) | `scipy.optimize.milp` (HiGHS) | Arad |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | Arrays for the MILP in `engine/plan.py` (installed with scipy) | Arad |
| scikit-learn | 1.9.1 | BSD-3-Clause | Random forest (Stage 5) | Arad |
| fastapi | 0.162.7 | MIT | Web server, SSE feed | Arad |
| uvicorn | 0.54.0 | BSD-3-Clause | ASGI server | Arad |
| pytest (dev) | 9.2.0 | MIT | Tests | both |
| httpx (dev) | 0.28.1 | BSD-3-Clause | Starlette/FastAPI TestClient for web tests | Arad |

## Models and APIs
| Name | Version / model id | Purpose | Owner | Verified |
|---|---|---|---|---|
| Gemini API `generateContent` (HTTPS via stdlib `urllib.request`, key `LLM_API_KEY` in `.env`) | `gemini-3.5-flash-lite`, v1beta | LLM mode in `core/agents.py`: picks one code-built option, writes the rationale; JSON output mode | sagar | 2026-11-14: HTTP 200 with `responseMimeType: application/json`; `test_choose_live_picks_listed_option` passed |

## Tooling
| Tool | Version | Purpose |
|---|---|---|
| uv | 0.13.8 | Python and env management |
| git hooks (`.githooks/`, `scripts/check.sh`) | n/a | pre-commit, commit-msg, post-commit (Mongo log), pre-push; no external dependency |
| `scripts/adlc_log.py` | n/a | Shared ADLC client: status in `adlc.items` (`board`, `item`), events in `adlc.log`; uv inline deps: pymongo>=4.7, certifi |
| Skill `adlc-log` (`.claude/skills/`), SessionStart hook (`.claude/settings.json`), Cursor rule `adlc.mdc` | n/a | Agents read inbox + board at start, log events that move status; verified 2026-11-14 by running the hook command |
| GitHub Actions `ci.yml` | actions/checkout@v4, astral-sh/setup-uv@v5 | Same checks as the hooks on every PR; pytest when `tests/` exists |
| Branch protection on `main` | n/a | PR required, `checks` and `tests` must pass |

## Project skills and rules
| Name | Where | Purpose |
|---|---|---|
| adlc-log | `.claude/skills/adlc-log/` | Teaches Claude Code the log and the relay loop |
| adlc rule | `.cursor/rules/adlc.mdc` | Same for Cursor (always applied); points to the AGENTS.md design bar and review loop |
| SessionStart hook | `.claude/settings.json` | Prints the inbox (events `--to` me) and latest 10 log events at session start |
