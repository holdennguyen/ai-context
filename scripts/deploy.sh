#!/usr/bin/env bash
# deploy.sh — sync ai-context artifacts into ~/.claude/
# Usage: ./scripts/deploy.sh [--dry-run]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_DIR="${HOME}/.claude"
SKILLS_DEST="${CLAUDE_DIR}/skills"
DRY_RUN=false

[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=true

log() { echo "[deploy] $*"; }
run() { $DRY_RUN && log "DRY: $*" || "$@"; }

# 1. Skills — symlink each .md into ~/.claude/skills/
if [[ -d "${REPO_DIR}/skills" ]]; then
  run mkdir -p "${SKILLS_DEST}"
  for f in "${REPO_DIR}"/skills/*.md; do
    [[ -e "$f" ]] || continue
    name="$(basename "$f")"
    log "skill: ${name} → ${SKILLS_DEST}/${name}"
    run ln -sf "$f" "${SKILLS_DEST}/${name}"
  done
else
  log "skills/ dir not found — skipping"
fi

# 2. CLAUDE.md — loaded via ~/.claude/CLAUDE.md @import already; no copy needed
log "CLAUDE.md: loaded via @import in ~/.claude/CLAUDE.md — no action"

# 3. Validate settings.json if present
if [[ -f "${CLAUDE_DIR}/settings.json" ]]; then
  python3 -m json.tool "${CLAUDE_DIR}/settings.json" > /dev/null \
    && log "settings.json: valid JSON" \
    || { echo "[deploy] ERROR: settings.json invalid JSON"; exit 1; }
fi

log "Done. Restart Claude Code to pick up skill changes."
