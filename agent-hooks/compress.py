#!/usr/bin/env python3
"""
Shared PreToolUse hook: rewrites verbose shell commands to shorter output.
Used by Claude Code (Bash) and Cursor (Shell). Invoke with --format claude|cursor.

Targets: git, npm, pip, aws, pytest, tsc, docker, ls — TS/Python/Bash/AWS stack.
"""
from __future__ import annotations

import argparse
import json
import re
import sys


def rewrite(cmd: str) -> str | None:
    """Return rewritten command, or None if no rewrite needed."""

    skip_signals = ["--oneline", "--short", "| head", "| tail", "| jq", "| grep", "2>/dev/null"]
    if any(s in cmd for s in skip_signals):
        return None

    if re.match(r"^git log\b", cmd):
        return re.sub(r"^git log", "git log --oneline --graph --decorate -30", cmd, count=1)

    if re.match(r"^git diff\b", cmd) and "--stat" not in cmd and "--name-only" not in cmd:
        return f"({cmd}) | head -150"

    if re.match(r"^git status\b", cmd):
        return re.sub(r"^git status", "git status --short --branch", cmd, count=1)

    if re.match(r"^git blame\b", cmd):
        return f"({cmd}) | head -60"

    if re.match(r"^npm (install|ci|i)\b", cmd):
        return f"({cmd}) 2>&1 | grep -E '(added|removed|changed|audited|found|error|warn|ERR!)' | tail -15"

    if re.match(r"^npx\b", cmd):
        return f"({cmd}) 2>&1 | tail -30"

    if re.match(r"^pip(3?) install\b", cmd):
        return f"({cmd}) 2>&1 | grep -E '(Successfully|already satisfied|Requirement|error|ERROR|WARNING)'"

    if re.match(r"^pip(3?) (freeze|list)\b", cmd):
        return f"({cmd}) | head -40"

    if re.match(r"^aws\b", cmd):
        return f"({cmd}) | head -80"

    if re.match(r"^(pytest|python -m pytest)\b", cmd) and "-v" not in cmd:
        return f"({cmd}) 2>&1 | tail -40"

    if re.match(r"^(npx )?tsc\b", cmd) and "--watch" not in cmd:
        return f"({cmd}) 2>&1 | grep -E '(error TS|warning TS|Found [0-9])' | head -50 || true"

    if re.match(r"^docker build\b", cmd):
        return f"({cmd}) 2>&1 | grep -E '(Step|Successfully|error|Error)' | tail -20"

    if re.match(r"^docker logs\b", cmd) and "--tail" not in cmd:
        return re.sub(r"^docker logs", "docker logs --tail 50", cmd, count=1)

    if re.match(r"^ls\b", cmd) and re.search(r"-[a-zA-Z]*[la]", cmd):
        return f"({cmd}) | head -60"

    return None


def rewrite_compound(cmd: str) -> str | None:
    """Apply rewrite() to the full command or to one segment of && / ; chains.

    Agents almost always run repo-relative commands as ``cd /path && git log``;
    the inner ``git log`` must be rewritten even though the line does not start
    with ``git``.
    """

    direct = rewrite(cmd)
    if direct is not None:
        return direct

    if "&&" in cmd:
        parts = re.split(r"\s*&&\s*", cmd)
        if len(parts) >= 2:
            parts = [p.strip() for p in parts]
            for i in range(len(parts) - 1, -1, -1):
                r_seg = rewrite(parts[i])
                if r_seg is not None:
                    parts[i] = r_seg
                    return " && ".join(parts)

    if ";" in cmd and "&&" not in cmd:
        parts = re.split(r"\s*;\s*", cmd)
        if len(parts) >= 2:
            parts = [p.strip() for p in parts]
            for i in range(len(parts) - 1, -1, -1):
                r_seg = rewrite(parts[i])
                if r_seg is not None:
                    parts[i] = r_seg
                    return "; ".join(parts)

    return None


def _get_shell_tool_context(data: dict, fmt: str) -> tuple[str, dict] | None:
    """Return (command, merged_tool_input) or None if hook should not rewrite.

    Merge `input` and `tool_input`/`toolInput` so we preserve every field when
    emitting updated input. Claude Code replaces the full tool input object
    (does not deep-merge), so omitting fields breaks Bash and other tools.
    """
    ti = data.get("tool_input") or data.get("toolInput") or {}
    inp = data.get("input") or {}
    tool = data.get("tool_name") or data.get("toolName")
    base = {**inp, **ti}
    cmd = (base.get("command") or "").strip()
    if not cmd:
        return None

    if fmt == "claude":
        if tool != "Bash":
            return None
        return (cmd, base)

    # Cursor: hooks.json matcher already limits to Shell; accept Shell or unknown tool shape
    if tool in (None, "Shell", "shell") or (isinstance(tool, str) and tool.endswith("Shell")):
        return (cmd, base)
    return None


def emit_claude(new_cmd: str, base: dict) -> None:
    merged = dict(base)
    merged["command"] = new_cmd
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "updatedInput": merged,
                }
            }
        )
    )


def emit_cursor(new_cmd: str, base: dict) -> None:
    merged = dict(base)
    merged["command"] = new_cmd
    print(
        json.dumps(
            {
                "permission": "allow",
                "updated_input": merged,
            }
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Compress verbose agent shell commands.")
    parser.add_argument(
        "--format",
        choices=("claude", "cursor"),
        required=True,
        help="Hook output shape for Claude Code vs Cursor.",
    )
    args = parser.parse_args()

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    ctx = _get_shell_tool_context(data, args.format)
    if not ctx:
        sys.exit(0)

    cmd, base = ctx

    new_cmd = rewrite_compound(cmd)
    if new_cmd is None:
        sys.exit(0)

    if args.format == "claude":
        emit_claude(new_cmd, base)
    else:
        emit_cursor(new_cmd, base)
    sys.exit(0)


if __name__ == "__main__":
    main()
