# ai-context

Versioned AI context artifacts for Claude Code and Cursor — rules, skills, hooks, and eval harness.

## Table of Contents

- [Overview](#overview)
- [Repository Structure](#repository-structure)
- [Artifact Types](#artifact-types)
- [Development Workflow](#development-workflow)
- [Testing with skill-creator](#testing-with-skill-creator)
- [Benchmarking](#benchmarking)
- [Deployment Runbook](#deployment-runbook)
- [Validation Gate](#validation-gate)
- [Cursor Context Reporter](#cursor-context-reporter)
- [Adding a New Artifact](#adding-a-new-artifact)

---

## Overview

Three categories of artifact live here:

| Category | Files | Loaded by |
|---|---|---|
| **Rules** | `CLAUDE.md`, `caveman.md` | `~/.claude/CLAUDE.md` via `@import` |
| **Skills** | `skills/*.md` | `~/.claude/skills/` via symlinks |
| **Hooks** | `agent-hooks/compress.py` | `~/.claude/settings.json` PreToolUse entry |
| **Tooling** | `cursor-context/context_report.py` | Run manually — not injected into context |

All changes follow: **feature branch → eval → benchmark → PR → merge → deploy**.

---

## Repository Structure

```
ai-context/
├── CLAUDE.md                        # Global role, stack, git, hard rules
├── caveman.md                       # Output contract (terse response levels)
├── skills/                          # Skill markdown files (slash commands)
│   └── .gitkeep
├── agent-hooks/
│   ├── compress.py                  # PreToolUse hook: rewrites noisy commands
│   └── README.md                    # Hook-specific docs and manual tests
├── evals/                           # Eval cases and rubrics per artifact
│   ├── skills/
│   │   ├── commit/
│   │   │   ├── cases.json           # Input prompts + expected behavior
│   │   │   └── rubric.md            # Grading dimensions and pass threshold
│   │   └── review-pr/
│   │       ├── cases.json
│   │       └── rubric.md
│   ├── rules/
│   │   ├── caveman/
│   │   │   ├── cases.json
│   │   │   └── rubric.md
│   │   └── global/
│   │       ├── cases.json
│   │       └── rubric.md
│   └── hooks/
│       └── compress/
│           └── cases.json
├── benchmarks/
│   ├── raw/                         # Gitignored raw run outputs
│   └── summaries/                   # Committed benchmark result summaries
├── cursor-context/
│   └── context_report.py            # Cursor context estimator (mirror of /context)
├── scripts/
│   ├── deploy.sh                    # Symlinks skills, validates settings.json
│   └── validate.sh                  # Pre-push gate: lint + smoke tests
└── .gitignore
```

---

## Artifact Types

### Rules (`CLAUDE.md`, `caveman.md`)

Prose instructions injected as system context on every session start. Claude Code loads them via `~/.claude/CLAUDE.md`:

```
@/home/holdennguyen/ai-context/CLAUDE.md
```

`caveman.md` is loaded via the same import chain. Changes are live on next session start — no deploy step needed.

**Rule authoring guidelines:**
- One concern per section, keep sections ≤20 lines
- Use imperative language ("Never commit to main", not "You should not commit to main")
- Hard rules go under `## Hard rules`; soft preferences go under the relevant section
- Test impact with the caveman eval cases before merging

### Skills (`skills/*.md`)

Markdown files that define slash commands (`/commit`, `/review-pr`, etc.). Each file contains:

```markdown
---
name: commit
description: Create a conventional commit for staged changes
---

[Skill prompt content here]
```

Skills are symlinked into `~/.claude/skills/` by `deploy.sh`.

### Hooks (`agent-hooks/compress.py`)

Python 3.10+ script invoked by Claude Code and Cursor before each shell tool call. Rewrites noisy commands (`git log`, `npm install`, etc.) to limit output. See `agent-hooks/README.md` for full docs.

---

## Development Workflow

### 1. Create a feature branch

```bash
cd ~/ai-context
git checkout main && git pull
git checkout -b feat/<scope>/<short-description>
# Examples:
#   feat/rules/tighten-caveman-ultra
#   feat/skills/add-review-pr
#   fix/hooks/compound-command-rewrite
```

### 2. Edit the artifact

- **Rules**: edit `CLAUDE.md` or `caveman.md` directly
- **Skills**: create or edit `skills/<name>.md`
- **Hooks**: edit `agent-hooks/compress.py`

### 3. Run local validation

```bash
./scripts/validate.sh
```

Fix any failures before proceeding.

### 4. Eval with skill-creator

See [Testing with skill-creator](#testing-with-skill-creator).

### 5. Open a PR

```bash
git add -p                          # stage intentionally
git commit -m "feat(rules): ..."    # conventional commit
git push origin HEAD
# Open PR; paste eval scores into PR description
```

### 6. Merge and deploy

After review, merge to `main`, then run:

```bash
git checkout main && git pull
./scripts/deploy.sh
```

---

## Testing with skill-creator

[skill-creator](https://claude.com/plugins/skill-creator) is an Anthropic-verified Claude.ai plugin with four modes:

| Mode | When to use |
|---|---|
| **Create** | Drafting a new skill from scratch |
| **Eval** | Testing a skill or rule change against eval cases |
| **Improve** | Getting targeted suggestions from failed eval cases |
| **Benchmark** | A/B comparing two versions across N runs |

### Eval workflow (step by step)

1. Open [claude.com](https://claude.com) with skill-creator installed.
2. Run: `/skill-creator eval`
3. When prompted, paste the artifact content (skill markdown or rule text).
4. When prompted for test cases, paste the contents of the relevant `evals/*/cases.json`.
5. When prompted for rubric, paste the relevant `evals/*/rubric.md`.
6. skill-creator's **Executor** runs each case; **Grader** scores against the rubric.
7. Record scores — pass threshold is defined in each rubric (typically 8/10).

**Eval case format** (`evals/<type>/<name>/cases.json`):

```json
[
  {
    "id": "unique-case-id",
    "prompt": "The user prompt to test",
    "expect": {
      "format_prefix": "feat(",         // string that must appear
      "max_subject_len": 50,            // numeric constraint
      "no_trailing_summary": true,      // boolean behavior check
      "note": "optional human note"
    }
  }
]
```

### Improve workflow

After an eval run with failures:

1. Run: `/skill-creator improve`
2. Paste: failing cases + current artifact content + grader feedback.
3. The **Analyzer** agent suggests targeted edits.
4. Apply suggestions to the artifact file on your feature branch.
5. Re-run eval until pass threshold is met.

---

## Benchmarking

Use benchmarking when comparing two versions of an artifact (e.g., `caveman.md` v1 vs v2, or two skill prompt strategies).

### Setup

Place the candidate alongside the current version:

```
skills/commit.md          # current (on main)
skills/commit.v2.md       # candidate (on feature branch)
```

### Running a benchmark

1. Run: `/skill-creator benchmark`
2. Paste both versions when prompted (Comparator runs blind A/B).
3. Specify N runs (recommend 10 for skills, 5 for rules).
4. The **Analyzer** returns variance analysis and a winner recommendation.

### Recording results

Save a summary in `benchmarks/summaries/`:

```
benchmarks/summaries/commit-skill-2026-04-13.md
```

Format:

```markdown
# Benchmark: commit skill v1 vs v2 — 2026-04-13

## Winner: v2

| Dimension | v1 avg | v2 avg | delta |
|---|---|---|---|
| Format compliance | 1.6/2 | 1.9/2 | +0.3 |
| Subject length | 2.0/2 | 2.0/2 | 0 |
| No trailing summary | 1.2/2 | 1.8/2 | +0.6 |

## Decision: promote v2 to commit.md
```

Commit the summary; raw run JSON goes in `benchmarks/raw/` (gitignored).

---

## Deployment Runbook

### Prerequisites

- Python 3.10+
- Claude Code installed, `~/.claude/` exists
- `~/.claude/CLAUDE.md` contains `@/home/<user>/ai-context/CLAUDE.md`

### First-time setup

```bash
# 1. Clone repo
git clone https://github.com/holdennguyen/ai-context.git ~/ai-context
cd ~/ai-context

# 2. Verify ~/.claude/CLAUDE.md imports this repo
grep "ai-context/CLAUDE.md" ~/.claude/CLAUDE.md

# 3. Wire the hook (if not already)
# Add to ~/.claude/settings.json under hooks.PreToolUse:
#   {
#     "matcher": "Bash",
#     "hooks": [{
#       "type": "command",
#       "command": "python3 ~/ai-context/agent-hooks/compress.py --format claude",
#       "timeout": 5
#     }]
#   }

# 4. Deploy skills
./scripts/deploy.sh

# 5. Validate
./scripts/validate.sh
```

### Routine deploy (after merging a PR)

```bash
git checkout main && git pull
./scripts/deploy.sh
# Restart Claude Code
```

### Dry-run (preview what deploy would do)

```bash
./scripts/deploy.sh --dry-run
```

### Rollback

```bash
git log --oneline -10              # find last good commit
git checkout -b rollback/<sha>     # branch from it
./scripts/deploy.sh                # redeploy old version
# Open PR to merge rollback to main
```

### Verifying hook is active

Ask Claude Code (or Cursor): "Run `git log` in this repo (no extra flags)."

| Signal | Hook active | Hook inactive |
|---|---|---|
| Line count | ~30 one-line commits | Thousands of lines |
| Commit shape | `* abc1234 (HEAD) subject` | Full multi-line blocks |

---

## Validation Gate

`scripts/validate.sh` runs the following checks:

1. **Hook syntax** — `python3 -m py_compile agent-hooks/compress.py`
2. **Hook smoke tests** — 3 piped payloads covering: rewrite, compound command, no-rewrite
3. **settings.json** — `python3 -m json.tool`
4. **Eval case JSON** — validates all `evals/**/cases.json`

Wire as a git pre-push hook:

```bash
ln -sf "$(pwd)/scripts/validate.sh" .git/hooks/pre-push
chmod +x .git/hooks/pre-push
```

Exit code 1 on any failure — blocks the push.

---

## Cursor Context Reporter

`cursor-context/context_report.py` — Cursor's equivalent of Claude Code's `/context` command. Estimates static context token usage from disk, broken down by category. Useful for monitoring context budget before/after rule or skill changes.

### What it measures

| Category | Source |
|---|---|
| User rules | `~/.cursor/rules/**/*.md` |
| Project rules | `<git-root>/.cursor/rules/**/*.md` |
| CLAUDE.md / AGENTS.md chain | Walked upward from cwd |
| Skills | `~/.cursor/skills-cursor/**/SKILL.md` |
| MCP config | `~/.cursor/mcp.json`, `.cursor/mcp.json` |
| Hooks | `~/.cursor/hooks.json` |
| CLI profile | `~/.cursor/cli-config.json` (model + approval subset) |
| Transcript (optional) | Latest JSONL under `~/.cursor/projects/` |

Token counts are rough approximations (`chars ÷ 4`), not API-identical.

### Requirements

- Python 3.10+ (stdlib only, no third-party deps)

### Usage

```bash
# Compact summary (default) — run from any project directory
python3 ~/ai-context/cursor-context/context_report.py

# With a specific workspace
python3 ~/ai-context/cursor-context/context_report.py --workspace /path/to/project

# Full file-level breakdown
python3 ~/ai-context/cursor-context/context_report.py --details

# Scrollable TUI (curses) — q to quit, j/k to scroll, g/G for top/bottom
python3 ~/ai-context/cursor-context/context_report.py --tui

# JSON output (for scripting / CI)
python3 ~/ai-context/cursor-context/context_report.py --json

# Skip transcript (faster if ~/.cursor/projects/ is large)
python3 ~/ai-context/cursor-context/context_report.py --no-transcript

# Custom context window for % bars (default 200000)
python3 ~/ai-context/cursor-context/context_report.py --context-window 128000
```

### Output (compact mode)

```
cursor-context (~tok ≈ chars÷4)
workspace /home/user/myproject
window 200,000 tok (for %)

Category               ~tok      %  Bar
------------------------------------------------------------------------
User rules               842    0.4% [                        ]
Project rules            210    0.1% [                        ]
CLAUDE/AGENTS            253    0.1% [                        ]
Skills (disk)              0    0.0% [                        ]
MCP                      120    0.1% [                        ]
Hooks                     65    0.0% [                        ]
CLI slice                 28    0.0% [                        ]

static ~1,518 | total ~1,518
```

Bar colors (TTY): green < 8%, yellow 8–20%, red ≥ 20%.

### Workflow integration

Use before and after rule/skill changes to verify context budget impact:

```bash
# Baseline before your change
python3 ~/ai-context/cursor-context/context_report.py --json > benchmarks/raw/context-before.json

# After editing rules/skills
python3 ~/ai-context/cursor-context/context_report.py --json > benchmarks/raw/context-after.json

# Diff
diff <(python3 -m json.tool benchmarks/raw/context-before.json) \
     <(python3 -m json.tool benchmarks/raw/context-after.json)
```

---

## Adding a New Artifact

### New skill

```bash
git checkout -b feat/skills/my-skill

# Create skill file
cat > skills/my-skill.md << 'EOF'
---
name: my-skill
description: One-line description of what this skill does
---

[Skill prompt here]
EOF

# Create eval cases
mkdir -p evals/skills/my-skill
# Write evals/skills/my-skill/cases.json and rubric.md

# Eval and improve with skill-creator (see Testing section)
# Then:
git add skills/my-skill.md evals/skills/my-skill/
git commit -m "feat(skills): add my-skill"
git push origin HEAD
# Open PR, attach eval scores
```

### New rule section

```bash
git checkout -b feat/rules/my-rule
# Edit CLAUDE.md or caveman.md
# Add eval cases to evals/rules/global/cases.json
# Run skill-creator eval against caveman.md evals
./scripts/validate.sh
git commit -m "feat(rules): add my-rule guidance"
```

### New hook rewrite

```bash
git checkout -b feat/hooks/my-rewrite
# Edit agent-hooks/compress.py
# Add case to evals/hooks/compress/cases.json
./scripts/validate.sh            # must include new case in smoke test
git commit -m "feat(hooks): rewrite my-command output"
```
