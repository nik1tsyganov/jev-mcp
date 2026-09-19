# Question packs

A pack is one JSON file describing how to judge one kind of item: what a single item
is, what goes into the `state`, the questions to ask about it, and the threshold that
turns each answer into an action. Packs are data, not code — read one, fill in the
state per item, post it, then act on the numbers in code.

| Pack | One item is | Questions |
| --- | --- | --- |
| `code-review-triage.json` | a review finding plus the code it points at | 5 |
| `head-brief-quality.json` | a brief written for one delegated agent | 6 |
| `skill-store-stale-ref.json` | one reference inside a skill file | 4 |
| `research-claim-verification.json` | a claim plus the source excerpt cited for it | 4 |
| `lesson-dedupe.json` | a candidate lesson plus the closest existing one | 4 |
| `merge-risk.json` | one changed file with its diff summary | 4 |
| `docs-staleness.json` | a doc section plus the code it describes | 4 |
| `bookmark-triage.json` | one saved social post | 5 |

## Worked example

`bookmark-triage.json` against one real saved post. The whole pack goes in one request:

    {
      "model": "jev-latest",
      "state": {
        "author": "Movez @0xMovez",
        "text": "20 TIPS FOR USING JEV FROM 0 TO PRO. ... 3. batch your questions: one request can answer many questions about the same state.",
        "links": ["https://docs.typesafe.ai"],
        "posted_at": "2026-09-18T19:13:50Z",
        "engagement": "1.2K likes, 180 reposts"
      },
      "questions": { ...the `questions` object from the pack, unchanged... }
    }

The answer, live on 2026-09-19 against `jev-1.13.0`:

    durable_technique  noul  0.85
    expires            noul  0.41
    depth              score 1.58   (between "a pointer worth opening" and "a summary you could act on", confidence 0.57)
    verifiable         noul  0.85
    route              choice skill_intake, probabilities 0.45 / 0.37 / 0.17 / 0.01, confidence 0.26

    usage: 749 input tokens, 120 output tokens

Read that honestly: the post clears the `durable_technique` gate of 0.6 and the `depth`
gate of 1.5, so it is worth opening. But `route` picked `skill_intake` with a
confidence of 0.26 and only 0.08 between the top two options, which is a tie, not a
decision. Route ties belong to a human, and a pack that hides them is worse than no
pack.

## Thresholds are starting points

Every `gate` in these files is a guess until it is measured. Before trusting one:

1. Hand-label at least 20 items of that corpus yourself.
2. Run the pack over the same 20.
3. Set the gate where it reproduces your labels, and record the disagreement rate.
4. Report that rate with any result the pack produces. An uncalibrated gate gets
   labelled as a guess in the report, every time.

## Cost

One request per item, whatever the number of questions in the pack — that is why each
pack stops at six.

Cost is not the constraint (owner, 2026-09-19): Jev is cheap and no budget limits it.
State the request count anyway, before running a corpus. Two hundred bookmarks is two
hundred requests, and nobody should discover that afterwards. Every judgment is logged
to `~/.claude/docs/telemetry/jev-spend.jsonl`; `tools/spend.py` reports it per day.

## What a pack must never do

A pack ranks, routes and flags. It does not approve anything destructive or
irreversible. A deterministic check gates that action; the judgment only decides what a
human looks at first.
