# Rubric: /commit skill

## Dimensions (each scored 0–2)

| Dimension | 0 | 1 | 2 |
|---|---|---|---|
| **Format** | Wrong prefix or missing scope | Correct type, wrong scope | Correct `type(scope): summary` |
| **Subject length** | >60 chars | 51–60 chars | ≤50 chars |
| **Imperative mood** | Past tense ("added", "fixed") | Mixed | Imperative ("add", "fix") |
| **No trailing summary** | Has "Here's what I did" block | Has minor fluff | Clean, no recap |
| **Co-authored-by** | Missing | Present but wrong format | `Co-Authored-By: Claude ... <noreply@anthropic.com>` |

## Pass threshold: 8/10

## Notes
- Conventional Commits spec: https://www.conventionalcommits.org
- Breaking changes must appear in footer as `BREAKING CHANGE:` or `!` after type
