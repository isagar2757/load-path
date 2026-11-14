# Public and demo readiness plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Steps use `- [ ]`.

**Goal:** the public repo holds only accurate docs, no dead code, no secrets or PII, and a demo that runs clean from `--reset`.
**Base:** `origin/main` bb8cef3. **Rules:** [AGENTS.md](../../../AGENTS.md) (branches, lanes, design bar, guards). One PR per task, `/code-review` before each; `/security-review` on T1 and T2.
**Out of scope until the last task:** removing `docs/superpowers/plans/`, `TRACKER.md`, ADLC prompts and tooling.

## Global constraints
- Never commit to `main`. Branch `type/slug` per task.
- `uv run pytest -q` green before every PR; CI green before merge.
- A finding without a command that proves it is written `UNVERIFIED: <command>`, not fixed.
- No new tool or library unless it gets a `docs/DEPENDENCIES.md` row in the same commit.
- Lanes: `systems/`, `engine/`, `web/`, `setup_db.py` were Arad's. The 17:14 `decision` moves remaining lanes to Sagar. Confirm with Arad before T4/T5 touch them.

## Review focus
1. Git history, not just the tree: a secret removed from a file is still public in an old commit.
2. Personal data in committed files: emails, home paths, account names (`.claude/settings.json`, `docs/adlc/prompts/`, `adlc.log` exports).
3. README claims that no longer match the code (one found: "run_demo.py has no LLM flag", but `--llm` exists).
4. Demo flake: `core/orchestrator.py:38` got no session right after insert (1 of 4 runs, D4 dry run).
5. Data rights: the Ontario bridge conditions file needs a recorded licence.

---

### T1: Secrets and PII audit (read-only, findings first)
**Files:** report only, in the PR description; fixes go in T2.
- [ ] Tree and history scan for connection strings and keys: `git log -p --all | grep -nE 'mongodb(\+srv)?://[^<]|AIza|sk-[A-Za-z0-9]{20}|_KEY=[^<$]'`. Expected: no match outside placeholders.
- [ ] Find PII: `git grep -nIE '@[a-z0-9-]+\.(com|ca)|/Users/|<employer>' $(git rev-parse HEAD)`. List every hit with file:line.
- [ ] Check `.env.example` has placeholders only; check `.gitignore` covers `.env`, `.venv`, `.local/`, `__pycache__`.
- [ ] Any secret in history → stop, rotate the credential first, and agree with Arad on a history rewrite. Do not force-push alone.

### T2: Guards and rights
**Files:** `README.md`, `docs/DEPENDENCIES.md`, `LICENSE`, any hit from T1.
- [ ] Vendor and employer names: `git grep -nIi -E '<vendor list agreed with Arad>'`. The list is not fixed yet; agree it before running.
- [ ] Wording that gives safety or engineering judgment: `git grep -nIiE 'safe|unsafe|structural(ly)? sound|recommend(s|ed)? repair'`, then review each hit.
- [ ] Record the bridge data source, its URL and its licence in README and `docs/DEPENDENCIES.md`. Opening the source page is the evidence.
- [ ] Every `pyproject.toml` dependency has a DEPENDENCIES row with version = `uv.lock`, and every row is still used.
- [ ] Fix the T1 PII hits.

### T3: Dead code
**Files:** `core/`, `systems/`, `engine/`, `web/`, `run_demo.py`, `setup_db.py`, `contracts.py`, `db.py`, `scripts/`.
- [ ] Unused imports and variables: `uvx ruff check --select F401,F811,F841 .`. ruff is a new tool: add the DEPENDENCIES row, or skip it and use the grep below.
- [ ] Unused definitions: for each `def`/`class` at top level, `git grep -nw <name>` gives 1 hit → candidate. Delete only after the full test suite passes without it.
- [ ] Names in `contracts.py` that nothing imports: the same grep. Changing contracts needs both people to agree (AGENTS.md).
- [ ] Remove commented-out code and `print` debug lines.
- [ ] `uv run pytest -q` green, then `run_demo.py --reset --auto` twice clean.

### T4: Demo defects (TDD, `fix/` branches)
- [ ] `core/orchestrator.py:38` session None: reproduce first (superpowers:systematic-debugging). Suspect a concurrent `--reset`, but the cause is UNVERIFIED. Write a failing test for the confirmed cause.
- [ ] Amounts print as `1618199.9999999998`: round at the source the formulas define (`docs/formulas.md`). Test `test_commit_amount_is_rounded`.
- [ ] Script beats missing from `--auto` (D4 dry run): Planner out-of-role deny, reject → revert, `verify` on an edited entry. Each one gets added to the run or cut from the script. Sagar and Arad decide which.

### T5: Docs accuracy
**Files:** `README.md`, `docs/formulas.md`, `docs/superpowers/specs/…design.md`, `docs/adlc/shared-log.md`, `.github/pull_request_template.md`.
- [ ] Each README claim gets a file:line or a command. Fix stale lines; the `--llm` line is stale now.
- [ ] Run every README command in a fresh clone (`git clone` to scratch, `./scripts/setup.sh`, `uv sync`, run steps). Expected: all succeed.
- [ ] `docs/formulas.md` matches `engine/plan.py` and `core/gate.py` term by term.
- [ ] Spec: set Status, mark built and not-built items, and remove open questions that are now answered.
- [ ] Docs bar: present tense, no marketing words or recaps (`scripts/check.sh` filler check passes).

### T6: Whole-repo review
- [ ] `/code-review high` on the full tree, plus `/security-review`.
- [ ] Fix or log each finding (`review --to <author>`). Done when there are no open `fail` findings.

### T7: Last (only after the user says go)
- [ ] Remove `docs/superpowers/plans/`, `docs/adlc/prompts/`, and clean `TRACKER.md`. Decide whether `.cursor/`, `.claude/`, ADLC scripts and hooks stay public.
- [ ] Update README links that pointed at removed files: `git grep -n 'superpowers/plans\|TRACKER'`.

## Order
T1 → T2 (secrets first; a history leak changes everything) → T3 ‖ T4 → T5 → T6 → T7.
