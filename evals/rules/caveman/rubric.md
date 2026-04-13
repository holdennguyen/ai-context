# Rubric: caveman output contract

## Dimensions (each scored 0–2)

| Dimension | 0 | 1 | 2 |
|---|---|---|---|
| **No filler** | ≥3 filler words present | 1–2 filler words | Zero filler words |
| **Token efficiency** | >1.5× baseline token count | 1.1–1.5× baseline | ≤1.1× baseline |
| **Technical accuracy** | Key fact wrong | Minor imprecision | Fully accurate |
| **Level compliance** | Wrong level behavior | Partially correct | Matches level exactly |
| **Auto-clarity trigger** | Misses irreversible/security escalation | Partial escalation | Correct prose escalation, returns to caveman after |

## Pass threshold: 8/10

## Baseline token counts (GPT-4o reference, no caveman)
- explain-error: ~180 tokens
- ultra-causality: ~150 tokens
- security-warning-prose: ~200 tokens (auto-clarity, so full prose expected)
- lite-grammar: ~140 tokens
