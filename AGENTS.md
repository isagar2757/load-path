# Rules for agents and humans

Applies to Claude Code, Cursor and any other agent. `CLAUDE.md` imports this file.

## Workflow (ADLC)
- Status lives only in `TRACKER.md`. Phases: Spec → Plan → Build → Verify → Ship. One chat per tracker item.
- Event feed: `adlc.log` on the sandbox ([convention](docs/adlc/shared-log.md)). Read it at session start; log task start/done, decisions, blockers, handoffs with `uv run scripts/adlc_log.py add ...`. Commits log themselves.
- New clone: `./scripts/setup.sh` (hooks, `.env`, Atlas check). It prints what is missing.
- No guessing. Verify by reading or running; otherwise write `UNVERIFIED` plus the command that would verify it.

## Git
- Never commit or push to `main`. Branch `type/slug`, open a PR, the other person or a review pass approves.
- Conventional Commits, one logical change per commit, tracker update in the same commit as the work.
- Hooks (installed by `./scripts/setup.sh`): branch guard, secret scan, docs sync, filler check, commit-msg, post-commit log, pre-push tests. CI repeats the checks on every PR; `main` is protected. `--no-verify` only with the other person's agreement.
- Before a PR: `/code-review`; add `/security-review` when secrets, auth, PII or external input are touched.

## Secrets
- Connection strings and keys only in `.env` (gitignored). `.env.example` holds placeholders. The repo is public.
- Python MongoDB clients use `tlsCAFile=certifi.where()`.

## Docs
- Concise, factual, present tense. No marketing words, no summaries of what the reader just read.
- Every plugin, MCP server, library, CLI or model added or removed updates [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md) in the same commit: name, version, purpose, owner, how it was verified. The docs-sync hook enforces this for manifest files; for global installs (plugins, CLIs) it is on you.
- Decisions go in `docs/adr/NNNN-slug.md` (Status, Context, Decision, Consequences). The tracker links to them.
- Only use code, data and assets we have rights to. Record the licence of anything copied in.

## Hackathon guards
- Project data layer is the sandbox cluster only. No personal Atlas, no local MongoDB.
- Demo and video show only what was built during the event.
- Check ideas against the anti-project list: no basic RAG, no Streamlit, no dashboard as the main feature.
