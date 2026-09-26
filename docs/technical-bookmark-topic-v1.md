# Technical bookmark topic profile v1 (candidate)

This records the pre-split combined router (before 2026-09-25). Status: qualification FAILED on 2026-09-21; the profile is enabled on this machine by owner override on the `laya` server and is selected with `profile: technical-bookmark-topic-v1`. There are no background comparisons. See [qualification results](evidence/technical-bookmark-topic-v1.json).

## Intended scope

`technical-bookmark-topic-v1` is a narrow, low-risk classification profile that groups a
bookmark into one of four subject labels. It exists to test whether a small local model
can place a short bookmark title and description into a topic bucket, so a downstream
feature can group saved links by subject.

It is topic grouping only. It is never keep/drop, safety, merge approval, plan
classification, or execution routing. Those decisions stay on Jev and are out of scope
for this profile.

Labels, in the frozen option order:

1. `software_development` — programming, databases, software testing, deployment and
   software security.
2. `machine_learning` — model training, inference and ML research.
3. `computer_hardware` — physical components, processors, memory, electronics and
   peripherals.
4. `other` — content outside those subjects.

The question asks the model to judge the main subject of the bookmark, not incidental
mentions. A hardware review that happens to mention a driver is `computer_hardware`; a
database post that mentions a laptop is `software_development`; an index-fund post that
uses a spreadsheet formula is `other`.

## Profile definition

`config/technical-bookmark-topic-v1.json` is the candidate definition. It declares:

- `profileId`: `technical-bookmark-topic-v1`
- `purpose`: `low_risk_classification` (the only purpose the local fast path allows)
- `checkpoint`: `aac6fef/laya-mlx`
- `revision`: `047678560251f28113ee8f5df4be82102c7bf336`
- `maxQuestions`: `1`
- `maxOptions`: `4`
- `maxStateChars`: `2000`
- `thresholdCandidates`: `[0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95]`
- `questions`: exactly one question, id `topic`
- `enabled`: `false`

`enabled` is `false` on purpose: this is a candidate, not an enabled profile. The registry entry in `config/decision-profiles.json` is enabled by owner override; this candidate definition file stays `enabled: false`. The live registry schema additionally needs a `questionsHash`, a
`minSelectedProbability` and a pinned `evidence` file; those are not in this candidate
because no evaluation has produced them. The lead froze input hashes before evaluation and recorded the failed diagnostic afterward.

## Frozen question

The question object is frozen: its instructions and its option order must not change
between development and holdout, because option order affects inference and the harness
hashes the validated questions. Every row in both corpora embeds this exact object:

```json
{
  "topic": {
    "type": "choice",
    "instructions": "Choose the main subject of this bookmark. Judge the primary subject of the title and description, not incidental words that appear in them.",
    "criteria": {
      "software_development": "programming, databases, software testing, deployment or software security",
      "machine_learning": "model training, inference or machine-learning research",
      "computer_hardware": "physical components, processors, memory, electronics or peripherals",
      "other": "content outside those subjects"
    }
  }
}
```

The harness computes `questionsFingerprint(questions)` as the SHA256 of
`JSON.stringify(validateQuestions(questions))`, preserving option order. Changing any
word of the instructions or reordering the criteria changes the hash and invalidates the
frozen corpus.

## Corpora

Two separate files, disjoint by construction:

| File | Split | Cases | Per label |
| --- | --- | --- | --- |
| `data/technical-bookmark-topic-dev.jsonl` | `dev` | 80 | 20 |
| `data/technical-bookmark-topic-holdout.jsonl` | `holdout` | 240 | 60 |

Each label (`software_development`, `machine_learning`, `computer_hardware`, `other`) has
20 development cases and 60 held-out cases. Topics are distinct within and across splits;
no case is a numbered paraphrase of another. Both corpora contain incidental cross-topic
words and clear primary-topic contrasts, so a label cannot be recovered from a single
keyword.

### Row schema

Each JSONL row follows the existing harness contract used by `tools/laya_compare.py`
(`load_cases`, `validate_cases`, `extract`) and the synthetic cases in
`data/laya-comparison-cases.jsonl`:

- `id` — unique across both files (prefix `tbt-dev-` / `tbt-holdout-`).
- `group` — equals the expected label, so the harness groups accuracy by label.
- `split` — `dev` or `holdout`.
- `origin` — `synthetic`.
- `state` — `{ "title": ..., "description": ... }`, a short realistic bookmark title
  plus a description. Serialized state stays well under `maxStateChars` (2000).
- `questions` — the exact frozen question object above (one `choice` question, id `topic`).
- `expected` — `{ "topic": "<label>" }`.
- `label_source` — identifies agent authorship.
- `label_reason` — a concise reason for the label.

`validate_cases` requires exactly one scored question per case and an expected answer for
it; these rows satisfy that. The `extract` function reads the single primitive and
validates the returned choice and probabilities, so a `choice` question with four
options is directly runnable by the existing harness.

## Development and holdout protocol

The development split selects a single probability threshold from `thresholdCandidates`
(`0.4`, `0.5`, `0.6`, `0.7`, `0.8`, `0.9`, `0.95`) before the holdout split is opened for evaluation. The
holdout file must stay closed during development: it is not read, scored, or used to pick
the threshold. Once a threshold is chosen and recorded, the holdout split is opened and
scored at that threshold as a single confirmatory pass.

## Authored-label limitations

- The labels are authored by an agent (the Juno head) from a rubric, not by a human
  annotator, and the cases are synthetic. They are not real user bookmarks and not
  representative browsing traffic.
- Each label reflects one authoring pass over a short title and description. Ambiguous
  edge cases (a robotics post, a hardware post about firmware, a statistics post) were
  resolved by the stated definitions; a different annotator could disagree on some rows.
- No private browsing history, repository diffs, or external data were used. The corpus
  is self-contained.
- `sampleCount` in any future evidence file is a count of cases, not a claim of
  statistical power. The operational margins in `docs/decision-routing.md` are thresholds,
  not proof of generalization.

## Provenance and prior research

Created 2026-09-21 by the Juno head (agent-authored, synthetic) for `jev-mcp`. The runtime
identity pinned here (`aac6fef/laya-mlx` at revision
`047678560251f28113ee8f5df4be82102c7bf336`) matches the `laya-mlx` provider and the
`--revision` value in `docs/laya-comparison-protocol.md`.

Existing research found no qualified general Laya profile: on the 36 synthetic cases and
the 40 local change-review cases, no Laya production profile passed, and the registry (`config/decision-profiles.json`) has no enabled profile. This corpus does not establish
general superiority of Laya over Jev, and it does not change the default of Jev. It only
provides a candidate profile definition and the two corpora a future, properly frozen
evaluation would need.

No performance evidence is recorded here because none was produced: no model was run, no
API call was made, and no test, build, or lint was executed while authoring these files.
Any accuracy, latency, or threshold claim must come from a separate frozen evaluation.

Development-only adjustment: the initial 0.7–0.95 candidate grid accepted at most 8 of 80 development examples. Before holdout inference, the grid was expanded to include 0.4, 0.5 and 0.6. The minimum accuracy, sample-count, coverage and comparison gates were not relaxed.
