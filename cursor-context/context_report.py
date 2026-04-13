#!/usr/bin/env python3
"""Estimate Cursor-related static context and optional session transcript size.

Claude Code's /context shows a live per-category token breakdown inside the app.
Cursor Agent CLI does not expose that API; this script approximates the same
categories from disk (rules, CLAUDE.md chain, skills, MCP config shape) and
optionally sums JSONL agent transcripts under ~/.cursor/projects.

Token counts are rough (character length / 4), not API-identical counts.

Usage:
  python3 context_report.py              # compact + color (TTY)
  python3 context_report.py --details    # full file lists
  python3 context_report.py --tui        # scrollable view (plain text)
  python3 context_report.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, TextIO


def rough_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def read_text(path: Path, limit: int | None = None) -> str:
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if limit is not None and len(data) > limit:
        return data[:limit]
    return data


def git_root(start: Path) -> Path | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    p = out.stdout.strip()
    return Path(p) if p else None


def walk_parents(start: Path) -> list[Path]:
    cur = start.resolve()
    roots: list[Path] = []
    for _ in range(64):
        roots.append(cur)
        if cur.parent == cur:
            break
        cur = cur.parent
    return roots


def collect_claude_md_chain(cwd: Path) -> list[tuple[Path, int]]:
    found: list[tuple[Path, int]] = []
    for d in walk_parents(cwd):
        for name in ("CLAUDE.md", "AGENTS.md"):
            p = d / name
            if p.is_file():
                t = read_text(p)
                found.append((p, rough_tokens(t)))
    return found


def glob_files(root: Path, pattern: str) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(root.glob(pattern))


def sum_rules_under(rules_dir: Path) -> tuple[int, list[tuple[Path, int]]]:
    total = 0
    rows: list[tuple[Path, int]] = []
    for f in glob_files(rules_dir, "**/*"):
        if not f.is_file():
            continue
        if f.suffix.lower() not in {".md", ".mdc", ".txt"}:
            continue
        t = read_text(f)
        tok = rough_tokens(t)
        total += tok
        rows.append((f, tok))
    return total, rows


def project_rules_root(cwd: Path, gr: Path | None) -> Path:
    return (gr or cwd).resolve()


def _dedupe_skill_bases(bases: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for b in bases:
        if not b.is_dir():
            continue
        key = str(b.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(b)
    return out


def skills_rows(bases: list[Path]) -> tuple[int, list[tuple[Path, int]]]:
    rows_by_key: dict[str, tuple[Path, int]] = {}
    for base in _dedupe_skill_bases(bases):
        for f in base.glob("**/SKILL.md"):
            if not f.is_file():
                continue
            key = str(f.resolve())
            t = read_text(f)
            tok = rough_tokens(t)
            rows_by_key[key] = (f, tok)
    rows = list(rows_by_key.values())
    rows.sort(key=lambda x: (-x[1], str(x[0])))
    total = sum(t for _, t in rows)
    return total, rows


def mcp_summary(path: Path) -> tuple[int, list[tuple[str, int]], list[str]]:
    """Return (estimated_tooling_tokens, per_server_rows, notes).

    Does not print command strings or env values — only names and rough JSON size.
    """
    notes: list[str] = []
    if not path.is_file():
        return 0, [], [f"no file: {path}"]

    try:
        raw = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError) as e:
        return 0, [], [f"mcp.json unreadable: {e}"]

    servers = raw.get("mcpServers") or raw.get("servers") or {}
    if not isinstance(servers, dict):
        return 0, [], ["mcpServers not an object"]

    rows: list[tuple[str, int]] = []
    for name, cfg in servers.items():
        if not isinstance(cfg, dict):
            continue
        redacted = json.dumps(cfg, sort_keys=True)
        rows.append((str(name), rough_tokens(redacted)))
    rows.sort(key=lambda x: (-x[1], x[0]))
    total = sum(t for _, t in rows)
    return total, rows, notes


def parse_transcript(path: Path) -> tuple[int, dict[str, int], int]:
    """Return (total_tokens, by_role, line_count)."""
    by_role: dict[str, int] = {}
    total = 0
    lines = 0
    if not path.is_file():
        return 0, {}, 0
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            lines += 1
            try:
                obj: dict[str, Any] = json.loads(line)
            except json.JSONDecodeError:
                continue
            role = str(obj.get("role") or "unknown")
            chunk = json.dumps(obj, ensure_ascii=False)
            tok = rough_tokens(chunk)
            total += tok
            by_role[role] = by_role.get(role, 0) + tok
    return total, by_role, lines


def find_latest_transcript(projects_dir: Path) -> Path | None:
    best: Path | None = None
    best_mtime = -1.0
    if not projects_dir.is_dir():
        return None
    for jsonl in projects_dir.glob("**/agent-transcripts/*/*.jsonl"):
        if not jsonl.is_file():
            continue
        try:
            m = jsonl.stat().st_mtime
        except OSError:
            continue
        if m > best_mtime:
            best_mtime = m
            best = jsonl
    return best


def bar(pct: float, width: int = 24) -> str:
    pct = max(0.0, min(100.0, pct))
    filled = int(round((pct / 100.0) * width))
    return "[" + ("#" * filled).ljust(width) + "]"


ESC = "\033["


class Term:
    """ANSI styling (caller decides tty / NO_COLOR / --color via use_ansi)."""

    def __init__(self, use_ansi: bool, file: TextIO = sys.stdout) -> None:
        self.use_ansi = bool(use_ansi)
        self.file = file

    def _wrap(self, code: str, s: str) -> str:
        if not self.use_ansi:
            return s
        return f"{ESC}{code}m{s}{ESC}0m"

    def bold(self, s: str) -> str:
        return self._wrap("1", s)

    def dim(self, s: str) -> str:
        return self._wrap("2", s)

    def red(self, s: str) -> str:
        return self._wrap("31", s)

    def green(self, s: str) -> str:
        return self._wrap("32", s)

    def yellow(self, s: str) -> str:
        return self._wrap("33", s)

    def cyan(self, s: str) -> str:
        return self._wrap("36", s)

    def bar_paint(self, pct: float, width: int) -> str:
        raw = bar(pct, width)
        if not self.use_ansi:
            return raw
        if pct >= 20.0:
            return self.red(raw)
        if pct >= 8.0:
            return self.yellow(raw)
        return self.dim(self.green(raw))

    def pct_paint(self, pct: float, s: str) -> str:
        if not self.use_ansi:
            return s
        if pct >= 20.0:
            return self.red(s)
        if pct >= 8.0:
            return self.yellow(s)
        return s


def want_color(mode: str, stream: TextIO) -> bool:
    if mode == "never":
        return False
    if mode == "always":
        return True
    if os.environ.get("NO_COLOR", "").strip():
        return False
    return stream.isatty()


def bar_width(term_cols: int, reserved: int = 52) -> int:
    w = term_cols - reserved
    return max(8, min(32, w))


def format_compact_table(
    term: Term,
    categories: list[tuple[str, str, int, str]],
    win: int,
    cwd: Path,
    gr: Path | None,
    static_total: int,
    grand: int,
    transcript_path: Path | None,
    term_cols: int,
) -> None:
    """categories: (short_label, full_label, tok, note)"""
    bw = bar_width(term_cols)
    f = term.file
    print(term.bold("cursor-context"), term.dim(" (~tok ≈ chars÷4)"), file=f)
    print(term.dim(f"workspace {cwd}"), file=f)
    if gr:
        print(term.dim(f"git root  {gr}"), file=f)
    print(term.dim(f"window {win:,} tok (for %)"), file=f)
    print(file=f)

    hdr = f"{'Category':<22} {'~tok':>8} {'%':>7}  Bar"
    print(term.bold(hdr), file=f)
    print(term.dim("-" * min(term_cols - 2, 78)), file=f)

    for short, _full, tok, _note in categories:
        pct = 100.0 * tok / win
        b = term.bar_paint(pct, bw)
        pct_plain = f"{pct:5.1f}%"
        line = f"{short:<22} {tok:>8,} {pct_plain:>7}  {b}"
        print(line, file=f)

    print(file=f)
    print(
        term.bold(f"static ~{static_total:,}"),
        term.dim("|"),
        term.bold(f"total ~{grand:,}"),
        term.dim("(incl. transcript)" if transcript_path else ""),
        file=f,
    )
    print(
        term.dim("--details file paths · --tui scrollable report · --color always|never · NO_COLOR"),
        file=f,
    )


def print_details(
    term: Term,
    proj_rule_files: list[tuple[Path, int]],
    user_rule_files: list[tuple[Path, int]],
    chain: list[tuple[Path, int]],
    skill_rows: list[tuple[Path, int]],
    mcp_rows: list[tuple[str, int]],
    mcp_notes: list[str],
    transcript_path: Path | None,
    tr_lines: int,
    tr_by_role: dict[str, int],
    no_transcript_hint: bool,
) -> None:
    f = term.file
    print(file=f)
    print(term.bold("Project rules"), file=f)
    for p, tok in sorted(proj_rule_files, key=lambda x: (-x[1], str(x[0])))[:20]:
        print(f"  {term.cyan(f'{tok:6,}')}  {p}", file=f)
    if not proj_rule_files:
        print(term.dim("  (none)"), file=f)

    print(file=f)
    print(term.bold("User rules"), file=f)
    for p, tok in sorted(user_rule_files, key=lambda x: (-x[1], str(x[0]))):
        print(f"  {term.cyan(f'{tok:6,}')}  {p}", file=f)
    if not user_rule_files:
        print(term.dim("  (none)"), file=f)

    print(file=f)
    print(term.bold("CLAUDE.md / AGENTS.md"), file=f)
    for p, tok in chain:
        print(f"  {term.cyan(f'{tok:6,}')}  {p}", file=f)
    if not chain:
        print(term.dim("  (none)"), file=f)

    print(file=f)
    print(term.bold("Skills"), file=f)
    for p, tok in skill_rows[:20]:
        print(f"  {term.cyan(f'{tok:6,}')}  {p}", file=f)
    if not skill_rows:
        print(term.dim("  (none)"), file=f)

    print(file=f)
    print(term.bold("MCP"), file=f)
    if mcp_rows:
        for name, tok in mcp_rows:
            print(f"  {term.cyan(f'{tok:6,}')}  {name}", file=f)
    else:
        print(term.dim("  (none or unreadable)"), file=f)
    for n in mcp_notes:
        print(term.dim(f"  note: {n}"), file=f)

    print(file=f)
    print(term.bold("Transcript"), file=f)
    if transcript_path is not None:
        print(term.dim(f"  {transcript_path}"), file=f)
        print(f"  {term.cyan(str(tr_lines))} lines", file=f)
        for role, tok in sorted(tr_by_role.items(), key=lambda x: -x[1]):
            print(f"  {role}: ~{tok:,} tok", file=f)
    elif no_transcript_hint:
        print(term.dim("  (no JSONL under ~/.cursor/projects/)"), file=f)


def run_tui(lines: list[str]) -> int:
    try:
        import curses
    except ImportError:
        print("curses not available on this platform", file=sys.stderr)
        return 1

    def draw(stdscr: Any) -> None:
        stdscr.clear()
        h, w = stdscr.getmaxyx()
        offset = 0
        while True:
            stdscr.erase()
            title = "cursor-context — q quit · j/k or arrows scroll · g/G top/bottom"
            stdscr.addnstr(0, 0, title[: w - 1], w - 1, curses.A_BOLD)
            body_h = max(1, h - 2)
            for i in range(body_h):
                idx = offset + i
                if idx >= len(lines):
                    break
                row = lines[idx].replace("\t", "    ")
                if len(row) >= w:
                    row = row[: w - 1]
                try:
                    stdscr.addnstr(1 + i, 0, row, min(len(row), w - 1))
                except curses.error:
                    pass
            stdscr.addnstr(
                h - 1,
                0,
                f"lines {offset + 1}-{min(offset + body_h, len(lines))} / {len(lines)}"[: w - 1],
                w - 1,
                curses.A_DIM,
            )
            stdscr.refresh()
            ch = stdscr.getch()
            if ch in (ord("q"), ord("Q"), 27):
                break
            if ch in (curses.KEY_DOWN, ord("j")):
                offset = min(max(0, len(lines) - body_h), offset + 1)
            elif ch in (curses.KEY_UP, ord("k")):
                offset = max(0, offset - 1)
            elif ch in (curses.KEY_NPAGE,):
                offset = min(max(0, len(lines) - body_h), offset + body_h)
            elif ch in (curses.KEY_PPAGE,):
                offset = max(0, offset - body_h)
            elif ch in (ord("G"),):
                offset = max(0, len(lines) - body_h)
            elif ch in (ord("g"),):
                offset = 0

    curses.wrapper(draw)
    return 0


def build_plain_lines(
    categories_short: list[tuple[str, str, int, str]],
    win: int,
    cwd: Path,
    gr: Path | None,
    static_total: int,
    grand: int,
    transcript_path: Path | None,
    proj_rule_files: list[tuple[Path, int]],
    user_rule_files: list[tuple[Path, int]],
    chain: list[tuple[Path, int]],
    skill_rows: list[tuple[Path, int]],
    mcp_rows: list[tuple[str, int]],
    mcp_notes: list[str],
    tr_lines: int,
    tr_by_role: dict[str, int],
    no_transcript_hint: bool,
) -> list[str]:
    lines: list[str] = []
    lines.append("cursor-context (~tok ~ chars/4)")
    lines.append(f"workspace: {cwd}")
    if gr:
        lines.append(f"git root:  {gr}")
    lines.append(f"context window (for %): {win:,}")
    lines.append("")
    bw = 24
    lines.append(f"{'Category':<22} {'~tok':>8} {'%':>7}  Bar")
    lines.append("-" * 60)
    for short, _full, tok, note in categories_short:
        pct = 100.0 * tok / win
        lines.append(f"{short:<22} {tok:>8,} {pct:5.1f}%  {bar(pct, bw)}  ({note})")
    lines.append("")
    lines.append(f"static: ~{static_total:,} tok | total: ~{grand:,} tok")
    lines.append("")
    lines.append("=== Project rules ===")
    for p, tok in sorted(proj_rule_files, key=lambda x: (-x[1], str(x[0]))):
        lines.append(f"  {tok:6,}  {p}")
    if not proj_rule_files:
        lines.append("  (none)")
    lines.append("")
    lines.append("=== User rules ===")
    for p, tok in sorted(user_rule_files, key=lambda x: (-x[1], str(x[0]))):
        lines.append(f"  {tok:6,}  {p}")
    if not user_rule_files:
        lines.append("  (none)")
    lines.append("")
    lines.append("=== CLAUDE.md / AGENTS.md ===")
    for p, tok in chain:
        lines.append(f"  {tok:6,}  {p}")
    if not chain:
        lines.append("  (none)")
    lines.append("")
    lines.append("=== Skills ===")
    for p, tok in skill_rows:
        lines.append(f"  {tok:6,}  {p}")
    if not skill_rows:
        lines.append("  (none)")
    lines.append("")
    lines.append("=== MCP ===")
    if mcp_rows:
        for name, tok in mcp_rows:
            lines.append(f"  {tok:6,}  {name}")
    else:
        lines.append("  (none or unreadable)")
    for n in mcp_notes:
        lines.append(f"  note: {n}")
    lines.append("")
    lines.append("=== Transcript ===")
    if transcript_path is not None:
        lines.append(f"  path: {transcript_path}")
        lines.append(f"  lines: {tr_lines}")
        for role, tok in sorted(tr_by_role.items(), key=lambda x: -x[1]):
            lines.append(f"  {role}: ~{tok:,} tok")
    elif no_transcript_hint:
        lines.append("  (no JSONL found)")
    lines.append("")
    lines.append("Limitations: rough counts; skills may be partially injected.")
    return lines


def main() -> int:
    ap = argparse.ArgumentParser(description="Cursor context usage estimator (Claude /context-style).")
    ap.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Project directory (default: cwd).",
    )
    ap.add_argument(
        "--transcript",
        type=Path,
        default=None,
        help="Agent JSONL transcript. Default: newest under ~/.cursor/projects/**/agent-transcripts/.",
    )
    ap.add_argument(
        "--no-transcript",
        action="store_true",
        help="Skip transcript section.",
    )
    ap.add_argument(
        "--context-window",
        type=int,
        default=200_000,
        help="Assumed context window for %% bars (default 200000).",
    )
    ap.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    ap.add_argument(
        "-d",
        "--details",
        action="store_true",
        help="Print per-file lists after the summary (verbose).",
    )
    ap.add_argument(
        "--color",
        choices=("auto", "always", "never"),
        default="auto",
        help="ANSI colors: auto (TTY, respects NO_COLOR), always, or never.",
    )
    ap.add_argument(
        "--tui",
        action="store_true",
        help="Scrollable full report (curses). Implies plain text; use q to quit.",
    )
    args = ap.parse_args()

    home = Path.home()
    cwd = args.workspace.resolve()

    gr = git_root(cwd)
    user_rules_dir = (home / ".cursor" / "rules").resolve()
    user_rules_tok, user_rule_files = sum_rules_under(home / ".cursor" / "rules")

    proj_root = project_rules_root(cwd, gr)
    proj_rules_dir = (proj_root / ".cursor" / "rules").resolve()
    if proj_rules_dir == user_rules_dir:
        proj_rules_tok, proj_rule_files = 0, []
        proj_rules_note = "same directory as user rules; counted once under user"
    else:
        proj_rules_tok, proj_rule_files = sum_rules_under(proj_root / ".cursor" / "rules")
        proj_rules_note = "git root or workspace"

    chain = collect_claude_md_chain(cwd)
    chain_tok = sum(t for _, t in chain)

    skill_roots = [
        home / ".cursor" / "skills-cursor",
        cwd / ".cursor" / "skills",
    ]
    if gr:
        skill_roots.insert(1, gr / ".cursor" / "skills")
    skills_tok, skill_rows = skills_rows([p for p in skill_roots if p.exists()])

    mcp_paths = [cwd / ".cursor" / "mcp.json", home / ".cursor" / "mcp.json"]
    mcp_tok = 0
    mcp_by_name: dict[str, int] = {}
    mcp_notes: list[str] = []
    for mp in mcp_paths:
        if mp.is_file():
            _t, rows, notes = mcp_summary(mp)
            for name, tok in rows:
                prev = mcp_by_name.get(name)
                mcp_by_name[name] = max(prev or 0, tok)
            mcp_notes.extend(notes)
    mcp_rows = sorted(mcp_by_name.items(), key=lambda x: (-x[1], x[0]))
    mcp_tok = sum(mcp_by_name.values())

    hooks_path = home / ".cursor" / "hooks.json"
    hooks_tok = rough_tokens(read_text(hooks_path)) if hooks_path.is_file() else 0

    cli_cfg = home / ".cursor" / "cli-config.json"
    cli_tok = 0
    if cli_cfg.is_file():
        try:
            cfg = json.loads(cli_cfg.read_text(encoding="utf-8", errors="replace"))
            model = cfg.get("model") or cfg.get("selectedModel") or {}
            cli_blob = json.dumps(
                {
                    "modelId": model.get("modelId") or model.get("model_id"),
                    "displayName": model.get("displayName") or model.get("display_name"),
                    "approvalMode": cfg.get("approvalMode"),
                    "sandbox": cfg.get("sandbox"),
                },
                sort_keys=True,
            )
            cli_tok = rough_tokens(cli_blob)
        except (OSError, json.JSONDecodeError):
            cli_tok = rough_tokens(read_text(cli_cfg, limit=4000))

    transcript_path = None if args.no_transcript else args.transcript
    if transcript_path is None and not args.no_transcript:
        transcript_path = find_latest_transcript(home / ".cursor" / "projects")

    tr_total = 0
    tr_by_role: dict[str, int] = {}
    tr_lines = 0
    if transcript_path is not None:
        tr_total, tr_by_role, tr_lines = parse_transcript(transcript_path)

    static_total = (
        user_rules_tok
        + proj_rules_tok
        + chain_tok
        + skills_tok
        + mcp_tok
        + hooks_tok
        + cli_tok
    )
    grand = static_total + tr_total

    categories: list[tuple[str, int, str]] = [
        ("User rules (~/.cursor/rules)", user_rules_tok, "always-on user rules"),
        ("Project rules (.cursor/rules)", proj_rules_tok, proj_rules_note),
        ("CLAUDE.md / AGENTS.md chain", chain_tok, "walk from cwd upward"),
        ("Skills (SKILL.md on disk)", skills_tok, "full files; product may inject subset"),
        ("MCP config (mcp.json)", mcp_tok, "names + config JSON size; secrets not printed"),
        ("Hooks (hooks.json)", hooks_tok, "hook definitions only"),
        ("CLI profile slice (cli-config)", cli_tok, "model + approval + sandbox subset"),
    ]
    if transcript_path is not None:
        categories.append(
            (
                f"Transcript ({transcript_path.name})",
                tr_total,
                f"{tr_lines} JSONL lines; includes tools + text",
            )
        )

    if args.json:
        out = {
            "workspace": str(cwd),
            "git_root": str(gr) if gr else None,
            "assumed_context_window": args.context_window,
            "rough_token_total": grand,
            "categories": {name: tok for name, tok, _ in categories},
            "transcript_path": str(transcript_path) if transcript_path else None,
            "transcript_by_role": tr_by_role,
            "detail": {
                "user_rule_files": [str(p) for p, _ in user_rule_files],
                "project_rule_files": [str(p) for p, _ in proj_rule_files],
                "claude_chain": [str(p) for p, _ in chain],
                "skill_files": [str(p) for p, _ in skill_rows[:50]],
                "mcp_servers": [{"name": n, "rough_tokens": t} for n, t in mcp_rows],
            },
        }
        print(json.dumps(out, indent=2))
        return 0

    if args.tui and args.details:
        print("warning: --tui already includes full detail; ignoring redundant --details", file=sys.stderr)

    win = max(1, args.context_window)
    term_cols = max(60, shutil.get_terminal_size(fallback=(100, 24)).columns)

    tr_note = f"{tr_lines} JSONL lines" if transcript_path else ""
    categories_compact: list[tuple[str, str, int, str]] = [
        ("User rules", "User rules (~/.cursor/rules)", user_rules_tok, "always-on"),
        ("Project rules", "Project rules (.cursor/rules)", proj_rules_tok, proj_rules_note[:40]),
        ("CLAUDE/AGENTS", "CLAUDE.md / AGENTS.md chain", chain_tok, "parent dirs"),
        ("Skills (disk)", "Skills (SKILL.md on disk)", skills_tok, "not all injected"),
        ("MCP", "MCP config (mcp.json)", mcp_tok, "config size"),
        ("Hooks", "Hooks (hooks.json)", hooks_tok, "hooks.json"),
        ("CLI slice", "CLI profile slice (cli-config)", cli_tok, "model + policy"),
    ]
    if transcript_path is not None:
        categories_compact.append(
            ("Transcript", f"Transcript ({transcript_path.name})", tr_total, tr_note or "session JSONL"),
        )

    no_transcript_hint = not args.no_transcript and transcript_path is None

    if args.tui:
        lines = build_plain_lines(
            categories_compact,
            win,
            cwd,
            gr,
            static_total,
            grand,
            transcript_path,
            proj_rule_files,
            user_rule_files,
            chain,
            skill_rows,
            mcp_rows,
            mcp_notes,
            tr_lines,
            tr_by_role,
            no_transcript_hint,
        )
        return run_tui(lines)

    use_color = want_color(args.color, sys.stdout)
    term = Term(use_color, sys.stdout)
    format_compact_table(
        term,
        categories_compact,
        win,
        cwd,
        gr,
        static_total,
        grand,
        transcript_path,
        term_cols,
    )

    if args.details:
        print_details(
            term,
            proj_rule_files,
            user_rule_files,
            chain,
            skill_rows,
            mcp_rows,
            mcp_notes,
            transcript_path,
            tr_lines,
            tr_by_role,
            no_transcript_hint,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
