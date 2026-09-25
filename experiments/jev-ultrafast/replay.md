# jev-ultrafast paired replay (experiment-only)

Replays `browser_trial.py` decision captures against the Jev client, batched vs
sequential, and optionally against the local Laya worker for compatibility. This
runner changes no production code and is not evidence for adoption by itself.

Upstream pin: `browser-use/jev-ultrafast@1231850a0bf1a0c0341fe408ef1668dbbfdfac46`
(`jev_ultrafast/model.py` is the operation/target contract this replays against).

## Input

`--input PATH` consumes JSONL captures, one record per line:

```
{id, task_id, state, questions, response, model, latency_ms}
```

`state` and `questions` are the upstream `choose()` request body pieces. The
runner selects the first 12 distinct `{state, questions}` hashes in capture
order (override with `--limit N`) and preserves the captured objects.

Upstream sends `instructions` as objects; our validator is string-only, so
object instructions are normalized to canonical JSON (sorted keys, no
whitespace) before any call. Original and normalized request hashes are both
recorded. This is not byte-identical upstream behavior and is never reported
as such.

## What it measures (provider `jev`, default)

Per selected state, 3 alternating paired repetitions:

- rep 1: batched `systemOne` call (all questions) → sequential calls (one per question)
- rep 2: sequential → batched
- rep 3: batched → sequential

Alternation keeps slow drift from favoring one arm. `decision-service` auto
routing is not used; `systemOne` is called directly so credential resolution,
redaction and the spend log apply. The experiment adapter disables SDK retries — a failed call
stays in its row and in every denominator. The production client is unchanged; `logged-client.mjs` applies a process-local SDK request override with `maxRetries: 0`.

Per call: model pin, request, usage, error, duration. Per pair: arm wall time,
paired latency delta (`sequential.wallMs - batch.wallMs`, positive = batch
faster), upstream-semantics analysis (`operation` choice, the single
`<operation>_target` head it selects, `validate_choice` validity) and
batched-vs-sequential agreement. Unused speculative heads are never graded as
required answers — upstream cannot act on them. Summary reports median delta,
min/max spread, call counts, and agreement rates.

## What it measures (provider `laya`)

`--provider laya` replays the identical normalized payloads once per selected
state through `createLayaClient` configured from trusted env only
(`LAYA_MODEL_DIR`, `LAYA_CHECKPOINT`, `LAYA_MODEL_REVISION`, `LAYA_PYTHON`,
optional `LAYA_TIMEOUT_MS`, `LAYA_MAX_QUEUE`). There is no Jev fallback in this
mode; absent config produces `not-run`. Recorded per state: schema
compatibility, per-head argmax alignment and upstream `validate_choice`
validity, truncation/option rejections (`input_truncated`), checkpoint
identity vs `status()`, first-call duration separately from warm latency. Max
context comes from the checkpoint config — the typed model is 1024 tokens, not
a universal 512-token limit; options are capped at 48 tokens. No
confidence-based promotion happens anywhere in this runner.

## Commands (for the lead)

```
# dry run: parse + planned-call report only; no inference, no provider imports
node experiments/jev-ultrafast/replay.mjs --input /path/to/captures.jsonl
node experiments/jev-ultrafast/replay.mjs --input /path/to/captures.jsonl --provider laya

# jev paired pass; exact call count is printed before any inference
node experiments/jev-ultrafast/replay.mjs --input /path/to/captures.jsonl --live > jev-replay.json

# bounded smoke
node experiments/jev-ultrafast/replay.mjs --input /path/to/captures.jsonl --limit 2 --live > smoke.json

# laya compatibility pass (env-configured; never falls back to Jev)
LAYA_MODEL_DIR=/path/to/checkpoint LAYA_CHECKPOINT=<id> LAYA_MODEL_REVISION=<rev> LAYA_PYTHON=/path/to/python \
  node experiments/jev-ultrafast/replay.mjs --input /path/to/captures.jsonl --provider laya --live > laya-replay.json

# regression tests (fake-only; no providers, no credentials)
node --test experiments/jev-ultrafast/replay.test.mjs
```

Jev calls spend: each state costs `3 × (1 + question_count)` requests; the
exact total is announced on stderr before the pass and charged through the
existing spend logger.

## What these results cannot establish

- **Adoption.** Speed alone is not a PASS. Adoption still needs the noise-floor
  and quality gates in `docs/laya-comparison-protocol.md`; this report is
  descriptive (median, spread, agreement), not a verdict.
- **Task correctness.** Agreement between arms is not correctness. Only
  `validate_choice` head validity is checked against upstream semantics;
  whether the chosen action was right in the browser is not judged.
- **Real-web reliability.** Captured states measure replay behavior. Synthetic
  fixtures and real-web captures must stay distinguished; neither licenses a
  claim about live pages.
- **Byte-identical upstream behavior.** Instructions normalization and
  sequential decomposition change the request. Sequential submission also
  changes conditioning — each head is answered alone rather than jointly; that
  difference is the comparison, not a defect to explain away.
- **Statistical power.** 12 states × 3 pairs is small; degenerate intervals
  and 100% agreement are not proof of generalization.
- **Latency generalization.** First-call (load) and warm laya timings are kept
  separate; hosted-API vs local-GPU latency describes deployment choice, not
  equal-hardware speed.

## Selected-target baseline

Use `--selected-only` for the practical two-stage baseline: request the operation,
then request only its chosen target head. DONE/BLOCKED/WAIT need no target call.
The printed plan is an upper bound because selected operations determine the
actual request count. This measures the saved round trip without charging the
sequential arm for unused speculative target questions. Both arms retain the
same normalized question definitions and state.

    node experiments/jev-ultrafast/replay.mjs --input CAPTURES --selected-only --live > selected-replay.json

Latency includes awaited inference. The timing regression test advances a fake
clock inside the asynchronous provider call so pre-await timing cannot pass.
