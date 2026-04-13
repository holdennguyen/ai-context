#!/usr/bin/env bash
# validate.sh — pre-push gate: lint hooks, settings, eval case schemas
# Usage: ./scripts/validate.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PASS=0
FAIL=0

ok()   { echo "  [OK] $*";   ((PASS++)); }
fail() { echo "  [FAIL] $*"; ((FAIL++)); }

echo "=== Hook syntax ==="
if python3 -m py_compile "${REPO_DIR}/agent-hooks/compress.py"; then
  ok "compress.py compiles"
else
  fail "compress.py syntax error"
fi

echo "=== Hook smoke tests ==="
COMPRESS="${REPO_DIR}/agent-hooks/compress.py"

# Claude format — git log rewrite
OUT=$(printf '%s' '{"tool_name":"Bash","tool_input":{"command":"git log","working_directory":"/tmp"}}' \
  | python3 "${COMPRESS}" --format claude 2>/dev/null || true)
if echo "${OUT}" | python3 -m json.tool > /dev/null 2>&1 && echo "${OUT}" | grep -q "oneline"; then
  ok "claude git log → rewritten"
else
  fail "claude git log rewrite failed (got: ${OUT})"
fi

# Cursor format — compound command
OUT=$(printf '%s' '{"tool_name":"Shell","tool_input":{"command":"cd /tmp && git log"}}' \
  | python3 "${COMPRESS}" --format cursor 2>/dev/null || true)
if echo "${OUT}" | python3 -m json.tool > /dev/null 2>&1 && echo "${OUT}" | grep -q "oneline"; then
  ok "cursor cd && git log → rewritten"
else
  fail "cursor compound rewrite failed (got: ${OUT})"
fi

# No-rewrite case — already limited
OUT=$(printf '%s' '{"tool_name":"Bash","tool_input":{"command":"git log --oneline -5"}}' \
  | python3 "${COMPRESS}" --format claude 2>/dev/null || true)
if [[ -z "${OUT}" ]]; then
  ok "already-limited command → no rewrite (empty stdout)"
else
  fail "already-limited command should produce no output (got: ${OUT})"
fi

echo "=== settings.json ==="
SETTINGS="${HOME}/.claude/settings.json"
if [[ -f "${SETTINGS}" ]]; then
  if python3 -m json.tool "${SETTINGS}" > /dev/null 2>&1; then
    ok "settings.json valid JSON"
  else
    fail "settings.json invalid JSON"
  fi
else
  echo "  [SKIP] ~/.claude/settings.json not found"
fi

echo "=== Eval case JSON ==="
find "${REPO_DIR}/evals" -name "cases.json" | while read -r f; do
  if python3 -m json.tool "${f}" > /dev/null 2>&1; then
    ok "${f#"${REPO_DIR}/"}"
  else
    fail "${f#"${REPO_DIR}/"} invalid JSON"
  fi
done

echo ""
echo "=== Result: ${PASS} passed, ${FAIL} failed ==="
[[ "${FAIL}" -eq 0 ]] || exit 1
