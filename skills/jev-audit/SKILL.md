---
name: "jev-audit"
description: "Use when auditing, triaging, ranking, classifying or verifying more than a handful of items of any kind — skill files, review findings, lessons, saved posts, dependencies, doc sections, memory entries, agent briefs. Covers turning a corpus into a state-plus-questions pass over TypeSafe Jev, batching questions into one request per item, thresholds, calibration against hand labels, and reporting the numbers rather than the verdicts."
metadata: {"canonical-home": "~/.claude/skills/jev-audit", "packs": "~/src/jev-mcp/packs", "verified-live": "2026-09-19"}
---

# Jev audit

Jev returns typed judgments, not prose: a probability (`noul`), a labelled option with
per-option probabilities (`choice`), or a probability-weighted number on an ordered
scale (`score`). That is what makes an audit over many items cheap — code applies the
threshold, and the model never gets to decide what happens next.

Design guidance lives in `typesafe:typesafe-ai`; the credential and the verified API
contract live in `typesafe-setup`. This skill is only the audit procedure.

## When this applies

More than a handful of items, one repeated decision: keep or drop, rank, triage,
classify, route, extract a field, verify a claim against evidence.

## When it does not

- The output has to be prose, a plan, or code. Jev writes nothing.
- The decision needs tool use, a lookup, or several reasoning steps.
- There is one item. One request for one decision is fine, but call it a decision, not
  an audit, and do not build a pack for it.

## The pass

1. **Define one item.** A finding, a file, a claim, a post. If you cannot say what one
   item is in a sentence, the corpus is not ready.
2. **Define the state.** The fields needed to judge one item, and nothing else. Paste
   the evidence in: a truncated preview produces a judgment about the preview.
3. **Pick a type per decision.** Yes/no a threshold acts on → `noul`. One of several
   named destinations → `choice`. Graded quality, severity, risk → `score`.
4. **Write at most six questions.** They all share one request, so the sixth is nearly
   free and the seventh means the item is really two items.
5. **State the request count before running.** One request per item. Two hundred items
   is two hundred requests against the owner's balance.
6. **Apply thresholds in code.** Never ask the model what to do with its own number.

## Calibration

A threshold nobody measured is a guess. Hand-label at least 20 items, run the pack over
the same 20, put the gate where it reproduces your labels, and record the disagreement
rate. Report an uncalibrated gate as a guess, in those words.

Read a `score` as the number it is. A 1.58 on a four-level scale sits between levels 1
and 2; rounding it to 2 throws away the thing that made it worth measuring. Read a
`choice` with its probabilities: a top option at 0.45 against a second at 0.37 is a
tie, and a tie goes to a human.

## Reporting

Report the numbers, the thresholds, the disagreement rate and the total `usage`. Not
"most look fine". Simple words, active voice, one instruction per sentence, 20 words or
fewer. Say what the numbers changed.

## The gate rule

A judgment ranks, routes and flags. It never approves a destructive or irreversible
action on its own. A deterministic check gates the action; the judgment decides what a
human reads first.

When a judgment is missing — no key, a failed call — fall back to the behaviour you had
before it existed. The exception: where the judgment gates something destructive,
absence must refuse loudly rather than silently allow.

## Packs

Ready-made question sets, one JSON file each, at `~/src/jev-mcp/packs`:

| Pack | One item |
| --- | --- |
| `code-review-triage` | a review finding plus the code it points at |
| `head-brief-quality` | a brief written for one delegated agent |
| `skill-store-stale-ref` | one reference inside a skill file |
| `research-claim-verification` | a claim plus the source excerpt cited for it |
| `lesson-dedupe` | a candidate lesson plus the closest existing one |
| `merge-risk` | one changed file with its diff summary |
| `docs-staleness` | a doc section plus the code it describes |
| `bookmark-triage` | one saved social post |

Each file carries its state schema, its questions, its thresholds and its pitfalls.
Thresholds ship uncalibrated on purpose.

## Running a pass

Either the `jev` MCP server at `~/src/jev-mcp` (tool `jev_ask` takes a
state and a questions map in one call), or a direct `POST https://api.typesafe.ai/v1/systemone`.

## Credential

`TYPESAFE_API_KEY`, stored on this Mac at `~/.config/typesafe/env.sh`. Check presence
with `[ -n "${TYPESAFE_API_KEY:-}" ]`. Never print it, never write it into a repository,
never paste it into a report.

## Worked example and troubleshooting

`references/workflow.md`: a full skill-store audit end to end, batching rules, and the
401 / 422 / 429 / 529 table.
