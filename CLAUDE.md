# Holden — Global context (canonical)

Edit this file under `~/ai-context/`. Claude Code loads it via `~/.claude/CLAUDE.md` import; Cursor loads it via `~/.cursor/rules/holden.mdc`.

## Role

Senior SRE in cybersecurity domain, own production SaaS. AI engineering. Build internal AI tooling. 

## Stack

TypeScript, Python, Bash, AWS.

## Git rules

- Never commit directly to `main` or `master`; use a feature branch.
- Workflow: branch → pull request → review → merge.
- Conventional Commits: `<type>(<scope>): <imperative summary>` with subject ≤50 characters.
- Confirm before: `git push`, any force operation, branch deletion.

## Hard rules

- Confirm before: file deletion, auth or credential changes, any production-impacting action.
- Do not bypass hooks with `--no-verify` unless the user explicitly requests it.
- Never expose secrets, tokens, or personally identifiable information in output.
