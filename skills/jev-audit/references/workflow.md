# Per-item request and failure contract

Use `jev_ask` with one item's evidence in `state`, a `questions` map, and a short local `purpose` tag.
For a stale reference, the state needs the skill location, cited text, target evidence, and observation date.
Compute existence and exact version comparisons in code; ask Jev only for semantic judgments.
Keep a genuine comparison pair together, but do not combine unrelated references or findings.

## Question shapes

- `noul`: `type`, `instructions`, optional `criteria` with `true` and `false`.
- `choice`: `type`, `instructions`, required `criteria` object mapping options to descriptions or null.
- `score`: `type`, `instructions`, required ordered `criteria` array with at least two levels.

Every question about the item shares the request. A question cannot consume another question's answer.
Preserve `model`, verbatim `answers`, and `usage`.
Apply the host 0.8/0.6 selected-probability gate from `SKILL.md`; do not substitute a confidence field.
Keep fractional scores and their distributions visible; a weighted mean is not an action probability.

## Failures

| Status | Action |
| --- | --- |
| 401 | Stop and report invalid credentials; do not search for another key. |
| 422 | Correct the named request field; do not retry unchanged. |
| 429 | Use bounded backoff, accounting for SDK/server retries. |
| 529 | Use bounded backoff; report partial coverage if overload persists. |

Do not re-ask a successful judgment to obtain a more convenient result.
Report processed items, remaining items, request count, thresholds, model, and actual token usage.
A failed or partial corpus pass is not a completed audit.
