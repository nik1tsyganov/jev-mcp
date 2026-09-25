# Local profile qualification

`tools/qualify-laya-profile.js` turns saved `tools/laya_compare.py` results into a
frozen calibration and, only when every gate passes, the evidence file
`src/provider-policy.js` pins. It is offline: it loads no model, makes no network
call, and never writes `config/decision-profiles.json`.

Two commands, strictly separated:

- `calibrate` reads the profile definition, the development corpus, and the saved
  local development predictions. It never opens the holdout corpus.
- `evaluate` reads the frozen calibration artifact, the definition, the holdout
  corpus, and the saved local and Jev holdout predictions. It uses only the frozen
  threshold and never re-derives one.

The qualification is narrow and synthetic. The corpora are generated,
author-labeled rows, not production traffic. A pass qualifies one local choice
profile for the declared purpose; it is not a general model ranking.

## Inputs

### Definition — `config/technical-bookmark-topic-v1.json`

`profileId`, `purpose`, `questions` (one `choice` question), `checkpoint`,
`revision`, `maxQuestions`/`maxOptions`/`maxStateChars`, and
`thresholdCandidates: [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95]`. `questionsHash` is computed with
`questionsFingerprint` from `src/provider-policy.js`, so it is the same hash the
registry profile must carry.

### Corpora — `data/technical-bookmark-topic-{dev,holdout}.jsonl`

Development is 80 rows, 20 per label; holdout is 240 rows, 60 per label. Labels
and critical groups are `software_development`, `machine_learning`,
`computer_hardware`, `other`. Each row carries `id`, `group`, `split`, `state`,
`questions`, `expected`, plus `origin`/`label_source`. Required relationships:

- `expected.topic` is one of the four labels and one of the question's `criteria` keys.
- `group` equals `expected.topic` (label and group are the same four names).
- Development and holdout case ids and content (state + questions) are disjoint.
  The calibration artifact records the development ids and input hashes, and
  `evaluate` refuses any holdout case that overlaps them.

### Predictions — a `laya_compare.py` result

A prediction source is one of:

- a `run.json` written by `tools/laya_compare.py`,
- the `--out` directory containing it,
- a `predictions.jsonl` from that directory (the sibling `run.json` supplies the
  pins when present).

From `run.json` the tool reads `run.parameters.revision`, the provider's
`requested_checkpoint`, `resolved_model`, and `cases`. Each case record is the
harness shape: `case_id`, `group`, `split`, `primitive`, `question_id`,
`input_hash`, `ok`, `error`, `schema_ok`, `prediction`, `expected`, `warm_p50`,
`latency_samples`, `raw_answer`, `provider`, `checkpoint`.

The accepted probability is always the probability of the chosen label,
`raw_answer.answers[qid].probabilities[prediction]`. The entropy `confidence`
field is never read.

## Calibration

For each candidate threshold in ascending order, the accepted set is every
development case whose chosen-label probability is at least the threshold. A
threshold is selected when its accepted set has at least 20 examples and its
observed accepted accuracy is at least 0.95. The lowest such threshold wins;
otherwise the run is `INCONCLUSIVE`. A development run with any error or schema
error is also `INCONCLUSIVE`, never partially trusted.

The frozen artifact records `schemaVersion`, `kind`, `profileId`, the exact
`questionsHash`, `checkpoint`, `revision`, `definitionSha256`,
`thresholdCandidates`, `selectedThreshold`/`minSelectedProbability`, the
development corpus and prediction file hashes, the accepted count/accuracy, every
development case id and input hash, all candidate attempts, and `generatedAt`.

## Evaluation

Validation, all fail-closed:

- the artifact matches the definition's questions hash, checkpoint and revision,
  and its frozen threshold is one of the frozen candidates;
- the holdout corpus, local records and Jev records have matching case ids, and
  the local and Jev sets match each other exactly;
- each record's `input_hash` equals the corpus recomputation (byte-equivalent
  state/questions), its label equals the corpus label, its question id matches,
  and its primitive is `choice`;
- the local run's checkpoint and revision equal the definition's pins, and the
  Jev run records a resolved model;
- every distribution is finite, labelled like the question's criteria, and sums
  to 1;
- no record is missing, duplicated, or extra. Missing or errored records are
  reported, never dropped.

Metrics, over the accepted-local subset derived from the frozen threshold only:

- absolute local accuracy and coverage;
- paired local-minus-Jev accuracy bootstrap CIs (2,000 deterministic seeded
  resamples, percentile interval) overall and per label group;
- `latencyRatio` = median local `warm_p50` / median Jev `warm_p50` over accepted
  paired cases. This is the harness's recorded measured boundary: warmup and cold
  load are excluded, so it is a per-request warm ratio, not a cold-start claim.
- full-corpus `localFullAccuracy`, `jevFullAccuracy`, and `cascadeAccuracy`,
  where the cascade uses local when the chosen-label probability clears the
  frozen threshold and Jev otherwise. Cascade accuracy is reported separately so
  the effect of selection stays visible.

Gates, all required for a pass:

| Gate | Requirement |
| --- | --- |
| errors | `errorCount == 0` |
| schema errors | `schemaErrorCount == 0` |
| coverage | accepted / total `>= 0.25` |
| accepted accuracy | observed accepted accuracy `>= 0.95` |
| overall CI | lower bound `>= -0.02` |
| group counts | `>= 30` accepted in each of the four groups |
| group CIs | lower bound `>= -0.05` in each group |
| latency | `latencyRatio` strictly between 0 and 1 |

Insufficient counts or coverage yield `INCONCLUSIVE`; a violated accuracy, CI or
latency gate yields `FAILED`. Both write a diagnostic report and no evidence.

## Evidence and proposal

Only a `PASS` emits the evidence `src/provider-policy.js` validates:
`schemaVersion: 1`, `profileId`, `questionsHash`, `checkpoint`, `revision`,
`heldOut: true`, `sampleCount` (accepted cases), `confidenceLevel: 0.95`,
`accuracyDeltaCI`, `groupAccuracyDeltaCI`, `groupSampleCounts`, `errorCount: 0`,
`schemaErrorCount: 0`, `latencyRatio`, `minSelectedProbability`, `evaluatedAt`,
and `expiresAt` seven days later. Extra fields carry provenance (definition,
calibration, corpus and prediction SHA256s, resolved local and Jev models,
bootstrap seed/reps), `totalHoldoutCount`, `coverage`, the full-corpus accuracies,
`resolvedJevModel`, and `qualificationScope`, which marks the data as generated
author-labeled and synthetic.

With `--out`, the evidence is written there and a proposed registry profile is
written to `<out>.proposed-profile.json` with the evidence path and SHA256. The
tool never mutates `config/decision-profiles.json`; the lead adds the profile by
hand. Without `--out`, the evidence, its SHA256, and the proposal are printed as
one JSON object.

Exit codes: `0` calibrated or passed, `1` inconclusive or failed (diagnostic
written), `2` invalid input (fail-closed validation error).

## Commands

Generate the saved predictions with the existing harness (one provider per run,
as in `docs/laya-comparison-protocol.md`). Pin the local runtime exactly as the
definition declares:

    python tools/laya_compare.py --provider laya-mlx \
      --checkpoint <definition.checkpoint> --revision <definition.revision> \
      --cases data/technical-bookmark-topic-dev.jsonl \
      --warmup 0 --repetitions 1 --live --out ~/.local/scratch/tbt-dev-local

    python tools/laya_compare.py --provider jev \
      --cases data/technical-bookmark-topic-holdout.jsonl \
      --warmup 0 --repetitions 1 --live --out ~/.local/scratch/tbt-holdout-jev

    python tools/laya_compare.py --provider laya-mlx \
      --checkpoint <definition.checkpoint> --revision <definition.revision> \
      --cases data/technical-bookmark-topic-holdout.jsonl \
      --warmup 0 --repetitions 1 --live --out ~/.local/scratch/tbt-holdout-local

Calibrate from the development local run only:

    node tools/qualify-laya-profile.js calibrate \
      --definition config/technical-bookmark-topic-v1.json \
      --corpus data/technical-bookmark-topic-dev.jsonl \
      --predictions ~/.local/scratch/tbt-dev-local/run.json \
      --out ~/.local/scratch/tbt-calibration.json

Evaluate the frozen calibration against the held-out runs:

    node tools/qualify-laya-profile.js evaluate \
      --calibration ~/.local/scratch/tbt-calibration.json \
      --definition config/technical-bookmark-topic-v1.json \
      --corpus data/technical-bookmark-topic-holdout.jsonl \
      --local ~/.local/scratch/tbt-holdout-local/run.json \
      --jev ~/.local/scratch/tbt-holdout-jev/run.json \
      --out ~/.local/scratch/tbt-evidence.json

Both commands default `--definition`, `--corpus` (dev for `calibrate`, holdout
for `evaluate`) to the paths above, so only `--predictions`/`--local`/`--jev` and
`--out` are usually required. Add `--provider <name>` when a `run.json` holds more
than one completed provider.

## Raw-format assumptions

These are the places the tool depends on the harness's exact shapes. If a
produced artifact disagrees, the tool fails closed rather than guessing.

- `input_hash` is recomputed as SHA256 of the same canonical JSON
  (`sort_keys`, `(",", ":")`, literal non-ASCII) that `tools/laya_compare.py`
  uses. Number formatting (`1.0` vs `1`) or exotic escapes could differ between
  Python and JavaScript; a mismatch is reported, never ignored.
- `group` must equal `expected.topic`; the four labels are also the critical groups.
- `run.json` records the local revision only when `--revision` was passed, and
  `run.parameters.checkpoint` is null unless `--checkpoint` was passed, so the
  loader reads the provider's `requested_checkpoint`. A `predictions.jsonl` with
  no sibling `run.json` has no revision pin and fails pin validation.
- Latency uses `warm_p50` (falling back to the median of `latency_samples`);
  cold-load time is not part of `latencyRatio`.
- The Jev run must record `resolved_model`; the harness only fills it after a
  successful response.

Development-only adjustment: the initial 0.7–0.95 candidate grid accepted at most 8 of 80 development examples. Before holdout inference, the grid was expanded to include 0.4, 0.5 and 0.6. The minimum accuracy, sample-count, coverage and comparison gates were not relaxed.
