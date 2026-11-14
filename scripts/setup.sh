#!/usr/bin/env bash
# One-command local setup. Safe to re-run.
set -u
cd "$(git rev-parse --show-toplevel)"
ok() { echo "ok    $*"; }; bad() { echo "FAIL  $*"; rc=1; }; rc=0

command -v uv >/dev/null && ok "uv $(uv --version | cut -d' ' -f2)" || bad "uv missing: https://docs.astral.sh/uv/getting-started/installation/"
git config core.hooksPath .githooks && chmod +x .githooks/* scripts/*.sh scripts/adlc_log.py && ok "git hooks active"
if [[ ! -e .env ]]; then cp .env.example .env; bad ".env created from template: paste MONGODB_URI from Sagar, then re-run"; fi
if grep -q '^MONGODB_URI=mongodb.*<' .env 2>/dev/null || ! grep -q '^MONGODB_URI=.\+' .env 2>/dev/null; then
  bad "MONGODB_URI not set in .env"
else
  uv run --quiet scripts/adlc_log.py check 2>&1 | tail -1 | grep -q "atlas ok" && ok "atlas ok; adlc.log writable" \
    || bad "atlas check failed (IP on access list? string correct?): uv run scripts/adlc_log.py check"
fi
[[ $rc -eq 0 ]] && echo "ready: log with 'uv run scripts/adlc_log.py add ...', see AGENTS.md" || echo "not ready: fix FAIL lines"
exit $rc
