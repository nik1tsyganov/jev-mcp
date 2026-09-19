# A pass end to end

The example is a skill-store audit: roughly 60 skill files, each holding references
that rot — paths that moved, URLs that died, model names that were retired, version
claims that stopped being true. Reading all of them by hand is a day. Judging them one
reference at a time is 200-odd requests and about twenty minutes.

## 1. One item

One reference inside one skill file. Not one skill — a skill with eleven references is
eleven items, because each one is kept, updated or deleted on its own.

## 2. The state

    {
      "skill_file": "~/.claude/skills/gemini-bridge/SKILL.md",
      "reference_text": "Binary ~/.local/bin/agy, `agy --version` = 1.2.4 (checked 2026-09-16).",   // an example of a STALE line; the installed binary was 1.2.7
      "reference_kind": "version",
      "target_exists": true,
      "target_excerpt": "1.2.7",
      "written_on": "2026-09-16"
    }

`target_excerpt` is the whole point. A regex that only asks "does this path exist"
produces confident wrong answers; opening the target and pasting what it says produces
a judgment worth having.

## 3. The questions

From `packs/skill-store-stale-ref.json`, all four in one request:

- `is_stale` — `noul`, with `criteria` `{"true": "the claim no longer matches reality",
  "false": "the claim still matches, or the evidence does not show otherwise"}`.
- `load_bearing` — `noul`, no criteria. Would an agent act differently if it were wrong?
- `risk_if_wrong` — `score`, `criteria` `["nothing, it is decoration", "wasted effort",
  "a wrong answer to the user", "a destructive or irreversible action"]`.
- `route` — `choice`, `criteria` an object: `keep`, `verify_live`, `update`, `delete`,
  each with a description.

Remember the shapes: `choice` criteria is an object, `score` criteria is an ordered
array of at least two labels, `noul` criteria is optional and may only carry `true` and
`false`. A `noul` answer has no confidence field; the probability is the answer.

## 4. Thresholds and actions

| Answer | Gate | Above | Below |
| --- | --- | --- | --- |
| `is_stale` | 0.6 | queue the reference | leave it |
| `load_bearing` | 0.5 | fix before the next dispatch | fix at leisure |
| `risk_if_wrong` | 2.0 | fix in this pass | batch into the next one |
| `route` | top option under 0.5, or under 0.1 clear of the second | send to a human | apply the route |

That last row matters more than the others. A route with a 0.45 top option is a tie
dressed as a decision.

## 5. Report

    64 skill files, 207 references, 207 requests, 148k input tokens, 24k output.
    41 references scored stale above 0.6. 12 of those are load-bearing.
    Routes: keep 151, update 33, verify_live 15, delete 8.
    23 routes fell under the tie rule and went to a human.
    Threshold source: 25 hand-labelled references, disagreement rate 8 percent.

Numbers, thresholds, disagreement rate, usage. Not "the store looks healthy".

## Batching

**Do batch** every question about one item into one request. Six questions cost roughly
one request; six requests cost six.

**Do not batch** unrelated items into one state. Ten findings in one state produces
answers about the pile, not about any finding, and you lose the per-item number that
made the pass useful. The exception is a genuine comparison — a candidate lesson beside
the closest existing one — where both texts belong to the same judgment.

**Do not re-ask.** Asking the same question twice and taking the better answer is
sampling your own bias, and it doubles the bill.

## Reading a score between levels

A `score` is probability-weighted, so 1.58 on a four-level scale means the mass sits
across levels 1 and 2. That is information: the item is genuinely between "a pointer
worth opening" and "a summary you could act on". Round it only at the threshold, never
in the report.

`confidence` is about the spread of the distribution, not about whether the model is
right. Low confidence plus a clear top option is still a usable route; high confidence
on a badly written question is worthless.

## Troubleshooting

| Status | Means | Do |
| --- | --- | --- |
| 401 | the key is invalid or revoked | stop and tell the owner; do not retry, do not go looking for another key |
| 422 | a malformed request; the body names the field | fix the shape and re-send once. Never retry a 422 unchanged — it will fail identically |
| 429 | rate limited | back off and retry; the SDKs and the MCP server already do |
| 529 | the service is overloaded | back off and retry; if it persists, stop the pass and report how far it got |

Two rules that are not status codes. Never retry a classifier hoping for a different
answer: an unstable answer is a question problem, so rewrite the question. And when a
pass dies halfway, report the items it covered and the items it did not, rather than
presenting a partial pass as a complete one.
