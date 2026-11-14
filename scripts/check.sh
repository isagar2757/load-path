#!/usr/bin/env bash
# Shared checks for the local pre-commit hook and CI.
#   scripts/check.sh staged            check the index
#   scripts/check.sh range <a>...<b>   check a commit range (CI)
set -u
mode=${1:-staged}; range=${2:-}
if [[ "$mode" == "staged" ]]; then
  diffcmd=(git diff --cached); ref=":"
else
  diffcmd=(git diff "$range"); ref="HEAD:"
fi
fail=0
err() { echo "check: $*" >&2; fail=1; }

files=$("${diffcmd[@]}" --name-only --diff-filter=ACM)
[[ -z "$files" ]] && exit 0

# 1. Secrets in added lines.
added=$("${diffcmd[@]}" -U0 --diff-filter=ACM -- . ':(exclude).env.example' ':(exclude)scripts/check.sh' | grep -E '^\+[^+]' || true)
patterns='mongodb(\+srv)?://[^:/[:space:]<]+:[^@<[:space:]$]+@|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}|-----BEGIN [A-Z ]*PRIVATE KEY-----|(password|passwd|secret|api[_-]?key|token)[[:space:]]*[:=][[:space:]]*["'"'"']?[A-Za-z0-9/+_.-]{12,}'
hits=$(echo "$added" | grep -i -E "$patterns" || true)
if [[ -n "$hits" ]]; then err "possible secret in added lines:"; echo "$hits" | cut -c1-100 >&2; fi
if echo "$files" | grep -E '(^|/)\.env($|\.)' | grep -v -E '\.env\.example$' | grep -q .; then
  err ".env file in change. Only .env.example may be committed."
fi

# 2. Docs sync: dependency/plugin/MCP/skill change must touch docs/DEPENDENCIES.md.
manifests='^(pyproject\.toml|uv\.lock|requirements[^/]*\.txt|package\.json|package-lock\.json|pnpm-lock\.yaml|\.mcp\.json|\.cursor/mcp\.json|\.cursor/rules/.*|\.claude/settings(\.local)?\.json|\.claude/plugins/.*|\.claude/skills/.*|\.github/workflows/.*)$'
if echo "$files" | grep -E -q "$manifests" && ! echo "$files" | grep -q '^docs/DEPENDENCIES\.md$'; then
  err "dependency/plugin/MCP/skill/workflow file changed but docs/DEPENDENCIES.md did not. Record name, version, purpose, owner."
fi

# 3. Filler phrases in markdown (prompts excluded).
fluff='\b(delve|seamless(ly)?|robust (solution|framework)|cutting-edge|game-changer|state-of-the-art|in today.s (fast-paced )?world|it.s important to note|leverag(e|ing)|comprehensive (guide|solution)|unlock the (power|potential))\b'
for f in $(echo "$files" | grep -E '\.md$' | grep -v -E '^docs/adlc/prompts/'); do
  m=$(git show "${ref}${f}" 2>/dev/null | grep -n -i -E "$fluff" | head -3 || true)
  if [[ -n "$m" ]]; then err "filler phrase in $f:"; echo "$m" >&2; fi
done
exit $fail
