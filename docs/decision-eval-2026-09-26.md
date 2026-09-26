# Decision evaluation, 2026-09-26: Jev and Laya on 150 labelled decisions

Data, runner and scorer: `experiments/decision-eval-2026-09-26/` (`cases-*.jsonl`, `run.mjs`, `score.py`, `scores.json`).

## What was measured

150 cases, labelled from written rules before any model ran:

| Source | Cases | Labels come from |
| --- | --- | --- |
| Hydra Oracle | 40 | Droppy Code source (`HydraOracle*.swift`, `AppModel+Hydra*.swift`) |
| CONCLAVE | 30 | `jev-arbiter.js`, `panel-rules.js`, the deliberation protocol; 21 reuse CONCLAVE's own Jev questions |
| General | 80 | mix-mode `routing.json`, the orchestrator scope check, the calibrated packs; 16 everyday cases by common sense |

Each case went to Jev once (one request per case, all its questions batched; `purpose: decision-eval-2026-09-26`) and to the Laya v2 model once (called directly, so the service's pack-overlap routing guard did not hide its answers). 12 cases whose answer code can compute are scored separately.

## Results

| | Jev (jev-1.13.0) | Laya (typed-decisions v2) |
| --- | --- | --- |
| Accuracy, 138 cases / 173 questions | **86.1%** (95% CI 80.7–91.1) | 45.2% (38.1–52.5) |
| Errors | 0 | 7 (plan-class states over its 1,024-token budget) |
| Calibration error (ECE) | 0.031 | 0.062 |
| Mean selected p, right vs wrong | 0.878 vs 0.656 | 0.541 vs 0.477 |
| Latency p50 / p90 | 133 / 169 ms | 9 / 13 ms (warm, in process) |
| When they disagree (87 questions) | right 86% | right 9% |
| Code-computable cases | 75% | 42% |

Jev by source: CONCLAVE 88.9%, general 89.6%, Oracle 75.0%. By category: plan-class 7/7, pairing 7/7, claim verification 16/16, review triage 20/20, bookmark topic 6/6, everyday 94%, routing 82%, delegate-or-not 84%, Oracle refusal 5/10, head profile 4/6.

Laya holds only on bookmark topics (5/6). Everywhere else it is near chance, and its probability does not separate right from wrong answers, so no threshold makes it usable (at p ≥ 0.75 it covers 6% of answers at 82%).

### Jev gate (bootstrap, 1,000 resamples by case)

| Act when selected p ≥ | Accuracy 95% interval | Coverage |
| --- | --- | --- |
| 0.6 | 85.3–94.9% | 90% |
| 0.7 | 89.4–97.7% | 75% |
| **0.8** | **92.6–99.2%** | **67%** |
| 0.9 | 92.8–100% | 55% |

## Why Jev missed (24 of 173)

1. **The rule was not in the state (about 10).** Oracle round caps, the school-scope model list, profile fallback, session boundaries, and CONCLAVE's "security-sensitive requires a panel" live in code. Jev cannot apply a rule it is not shown. Every one of these is a deterministic check.
2. **Applying a long policy text (about 7).** With the whole routing table in the state, Jev chose Codex at p 0.92 when every bucket was exhausted and the policy says pause, and Claude at p 0.90 for tutoring, which the policy routes to Codex. Classification alone (plan-class) was 7/7.
3. **Genuinely close calls (the rest).** Mostly at p 0.5–0.65, which the 0.8 gate already filters.

## What to change

**Jev everywhere**
- Act on a Jev answer automatically only at selected p ≥ 0.8. Between 0.6 and 0.8, flag it or ask. Below 0.6, do not act on it.
- Ask Jev to classify; let code apply the policy. Routing = Jev picks the task class, code maps class to vendor through `routing.json` and applies capacity and pause rules.
- Never ask Jev a rule the state does not carry. Counts, allowlists, round caps, proof fields, tallies and capacity are code.
- Pack triage: `code-review-triage`'s `is_real` stays ungated (non-predictive on real findings, 2026-09-19). These synthetic cases were easy (20/20) and do not overturn that measurement; use `reachable` and `route`.

**Laya**
- Keep it to bookmark topics, as the owner override already says. Do not use it for decisions or delegation: 45% with no usable threshold.
- Its 1,024-token budget truncates CONCLAVE plan-class states; it cannot take those questions at all.

**CONCLAVE**
- Fixed: `jev-arbiter.js` read the convene prior under `conclaveConveneByClass2026-09-16`, but `routing.json` still names it `magiConveneByClass2026-09-16`, so every convene decision went to Jev with prior null. A regression test now reads the real file.
- Classification (7/7) and evidence checks (3/3, plus 16/16 general claim checks) are where Jev earns its place. Keep tallies, proof checks, tie-breaks and the fail-closed rule for destructive actions in `panel-rules.js`.
- Put `requiresPanel` and `minimumReviewVendors` from the dispatch matrix into the convene state, or decide that class in code: Jev said no panel for a security-sensitive task at p 0.62 because the state lacked the rule.

**Hydra Oracle**
- The Oracle already keeps its gates (school-scope models, round cap, profile fallback, session boundary, provider choice) in code. Keep it that way: Jev scored 50–67% on those questions only because they are rules, not judgments.
- Jev fits the semantic parts: whether a request is academic work, and which recipe or pairing fits a task (pairing 7/7).
- Do not let the local Laya worker make pair decisions except as a labelled degraded mode: Laya scored 42.5% on the Oracle cases.

## Limits

- Labels were written by agents from rules; the weakest are listed in the case files' `rule` fields. Everyday and some delegation labels are judgment.
- Clear cases dominate (120 of 138), so the ambiguous-case numbers (n=18) are wide.
- One run per case. The 2026-10-02 usage review measures real traffic.
