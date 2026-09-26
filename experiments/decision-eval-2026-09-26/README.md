# Decision eval 2026-09-26

Runs the labelled cases in `cases-*.jsonl` against Jev and Laya, then scores both.

## Run

All commands run from this folder. `--cases` globs resolve relative to this folder.

```sh
cd ~/src/jev-mcp/experiments/decision-eval-2026-09-26

# 1. Count only: prints the provider and the number of requests, sends nothing.
node run.mjs --provider jev
node run.mjs --provider laya

# 2. Send. One request per case, all of that case's questions in it.
node run.mjs --provider jev --yes            # concurrency 4 (--concurrency N to change)
node run.mjs --provider laya --yes           # always concurrency 1

# 3. Score.
python3 score.py results-jev.jsonl results-laya.jsonl --cases 'cases-*.jsonl' --json scores.json
```

Options: `--cases GLOB` (default `cases-*.jsonl`), `--out FILE` (default `results-<provider>.jsonl`),
`--limit N` (first N cases not yet in the output file).

- **Resume.** A re-run skips every id already in the output file, including failed ones. To retry
  failures, delete their lines first.
- **Invalid cases.** Cases whose questions fail `validateQuestions` are written as `ok:false`,
  `error:"invalid-case"`, and are not sent.
- **Jev** calls `systemOne` with caller `{tool:"eval-runner", client:"decision-eval",
  purpose:"decision-eval-2026-09-26"}`. Every call is also logged to the normal Jev spend log.
- **Laya** uses the default profile's pinned runtime from `config/decision-profiles.json`. Its
  decision log goes to `laya-decisions.eval.jsonl` here, not the real log. Cases take the generic
  path, except `bookmark-topic` cases whose questions are exactly the frozen v2 questions (by
  fingerprint): they ask with profile `technical-bookmark-topic-v2`. The generic path refuses
  questions that overlap a calibrated pack (`pack-overlap`); those show up as errors.

Dry test of the scorer (fake results, no model calls):

```sh
python3 score.py fixtures/results-jev.jsonl fixtures/results-laya.jsonl --cases 'fixtures/cases-fixture.jsonl'
```

## Metrics

Cases with `code_computable: true` are left out of every metric below and reported on their own.
A question is **answered** when the case succeeded and the answer has a usable value.

- **accuracy**: correct / answered. choice: chosen label equals expected. noul: `noul >= 0.5`
  equals expected. score: `round(score)` equals the expected level index.
- **ci95**: 2.5th and 97.5th percentiles of accuracy over 1,000 bootstrap resamples of cases
  (fixed seed).
- **coverage**: answered / all questions. **err**: cases with `ok:false`. **missing**: cases
  with no result line.
- **selected p**: probability of the selected answer. choice: `probabilities[choice]`. noul:
  `max(p, 1-p)`. score: highest level probability.
- **calibration / ECE**: 10 equal bins of selected p, with count, mean p and accuracy per bin.
  ECE is the count-weighted mean of |accuracy - mean p|. Lower is better.
- **mean selected p**: on correct vs wrong answers, and on clear vs ambiguous cases. A useful
  gate needs a clear gap in both pairs.
- **threshold sweep**: for t = 0.30 to 0.95 (step 0.05), the share of all questions answered
  with selected p >= t (coverage) and their accuracy. The report gives the lowest t with
  accuracy >= 0.90 and coverage >= 0.30. **stable** means that t still meets both targets in
  all 5 random half-samples of the cases.
- **latency**: p50, p90 and max over successful requests (nearest rank). **tokens**: Jev input
  and output token totals.
- **agreement**: on questions both providers answered, the share with the same prediction, and
  each provider's accuracy on the questions where they disagree.
