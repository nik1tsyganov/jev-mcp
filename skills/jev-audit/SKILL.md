---
name: "jev-audit"
description: "Runs per-item Jev judgments for corpus audits, triage, ranking, classification, and claim checks. Use for more than a handful of semantic decisions; batches each item\u2019s questions, applies measured probability bands in code, and reports model, answers, and usage."
metadata: {"canonical-home": "{agents.skills_canonical}/jev-audit", "packs": "{project.jev-mcp.packs}", "verified-live": "2026-09-19"}
---

# Jev audit

Use Jev for bounded semantic judgments over more than a handful of items.
Use code for counts, membership, caps, allowlists, and exact comparisons.
Use a generative model for prose or code; a judgment does not authorize an irreversible action.
Design guidance belongs to `typesafe:typesafe-ai` or `typesafe-ai`; machine access belongs to `typesafe-setup`.

## One item, one request

1. Define one item and the evidence needed to judge it.
2. Put that item's facts into a state object. Include the rule being judged; Jev cannot apply an absent rule.
3. Batch all questions about that item in one `jev_ask`. Do not put unrelated items in one state.
4. State the request count before the corpus pass. Cost is not the constraint; visibility is.
5. Pass a short `purpose` on every `jev_*` call. It is logged locally, not sent to Jev.
6. Preserve `model`, verbatim `answers`, and `usage`; let code apply the outcome policy.

Choose `noul` for yes/no, `choice` for named options, and `score` for ordered levels.
A question does not see another question's answer; include its needed premises.
A comparison pair can be one item when the decision is specifically about that pair.

## Measured host gate

| Selected probability | Policy |
| --- | --- |
| p >= 0.8 | May act automatically within authorized scope |
| 0.6 <= p < 0.8 | Flag for more evidence or an owner decision |
| p < 0.6 | Ignore the judgment; do not act on it |

Use the selected option's probability, not a generic confidence field, for this gate.
For `noul`, the yes probability is `noul`; the no probability is `1 - noul`.
A weighted `score` is not a probability; preserve its distribution and apply an explicit policy.
Do not round a score and treat the result as a high-confidence choice.

Measured on 150 labelled decisions, 2026-09-26: Jev was 86% correct overall;
selected p >= 0.8 yielded 92.6–99.2% accuracy across reported subsets, covering about two thirds of answers.
Source: `{project.jev-mcp.root}/docs/decision-eval-2026-09-26.md`.
These measurements are not a guarantee for a new pack. Calibrate new question sets on held-out labels.
Record `calibrated_on_model`; remeasure when changing the pinned model or questions.

## Packs and Hydra reports

Load the matching pack from `{project.jev-mcp.packs}`:
`code-review-triage`, `head-brief-quality`, `skill-store-stale-ref`,
`research-claim-verification`, `lesson-dedupe`, `merge-risk`, `docs-staleness`, or `bookmark-triage`.
Example pack thresholds do not override the host gate.

When heads return five or more findings, use one `jev_ask` per finding with the matching pack's questions
and `purpose: hydra-report-triage`. For review triage, use `reachable` and `route`; `is_real` was non-predictive.
A head brief for several judgments names `jev_ask`, per-item batching, and verbatim answers with model and usage.
Jev classifies; code applies routing policy and capacity. This is not a required second reviewer round.

## Failure and reporting

Use the `jev` server for general decisions. Laya stays bookmark-only; provider fallback is caller-controlled.
If Jev fails, report incomplete coverage. A missing judgment does not silently approve a gated action.
Do not repeat the same question to obtain a preferred answer.
Report request/item counts, probabilities, thresholds, calibration limits, model, and usage.
Spend: `{agents.claude_telemetry}/jev-spend.jsonl`; reader: `{project.jev-mcp.root}/tools/spend.py`.
[Request shape and failures](references/workflow.md) gives the concrete contract.
