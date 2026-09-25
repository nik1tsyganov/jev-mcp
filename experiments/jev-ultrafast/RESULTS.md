# Jev Ultrafast trial — 2026-09-21

Decision: the batched operation-and-target design merits a small, optional Jev
browser feature. Do not import this repository as a production dependency or
replace the current browser tools. Laya cannot serve these payloads unchanged.

The existing `decision_ask` already supports multiple questions. An integration
would mainly connect that capability to observed browser actions and existing
execution controls; it does not require a new decision model.

## Measured results

| Check | Result |
|---|---|
| Three local tasks, three repetitions each | 9/9 clean completions; 27 Jev requests |
| Independent completion evidence | Fixture DOM event state; zero incorrect actions |
| Stale-node replacement | 3/3 refused before action |
| Covered control and newly disabled control | Both refused; positive control clicked successfully |
| Selected-target replay | 8 distinct states, 24 paired comparisons, 63 requests, zero request failures |
| Median decision latency | Batched 146.4 ms; operation-then-selected-target 278.9 ms |
| Median paired saving | 121.5 ms; range −74.1 to 235.7 ms |
| Operation agreement | 24/24 pairs |
| Selected-target agreement | 15/15 applicable pairs |
| Local typed Laya replay | 0/8 accepted; all rejected before inference because input would truncate |
| Local runtime positive control | Passed a short independent classification |
| Experiment regression checks | 13 Node tests and 2 Python tests passed |

On the 15 pairs requiring a target, the median saving was 155.4 ms. On the nine
terminal decisions without targets, batching was 14.6 ms slower at the median.
Batching saves a round trip when a target is needed; it is not a universal speedup.
The median within-state median absolute deviation of batch timings was 7.65 ms,
based on only three repetitions per state. This is a descriptive variability
check, not a confidence bound or a production adoption gate.

A preliminary comparison requested every target head sequentially. It used 99
requests and showed a 373 ms median paired saving. That is an inefficient
baseline, so the recommendation uses the selected-target comparison above.
Total paid judgment requests: 189, all through the existing spend logger with
SDK retries disabled in the experiment process. The text helper made no paid calls.

## Why Laya refused

The pinned typed checkpoint has a 1,024-token sequence limit and a 256-token
question-head budget. The operation questions needed prefixes of 310–345 tokens,
including special tokens. The configured builder shortened them to 259 tokens.
Complete operation sequences were only 553–697 tokens: the first obstruction
was the question-head budget, not the overall sequence limit.

The worker's error names the overall model budget even when head truncation is
the cause. Tokenizer measurements isolate this distinction. No quality or
latency claim about Laya inference follows from these rejections. Supporting
these requests needs a separately evaluated representation or configuration;
silent truncation is not a valid substitute.

## Scope and adaptations

- Upstream revision: `1231850a0bf1a0c0341fe408ef1668dbbfdfac46`.
- Resolved decision model: `jev-1.13.0` throughout both replay comparisons.
- Browser: Chrome 153.0.8010.50, headless, with a fresh owned profile and direct
  loopback CDP. No authenticated user profile or browser-harness daemon was used.
- Tasks: choose an item, fill and save an exact string, select and submit a value.
- The real upstream agent and executor ran with transport and model-call seams
  replaced. The upstream files remained unchanged and hash-recorded.
- Object instructions became deterministic JSON strings for our validator.
  Captures retain the originals. This is not an exact upstream wire reproduction.
- TYPE_TEXT received a fixed task string. Text generation was not evaluated.
- Browser timing uses upstream's first-predict-to-DONE boundary. It excludes
  initial setup/navigation and the final independent verifier.
- Replay timings include awaited API calls through our client. Agreement is
  measured separately from the end-to-end fixture completion checks.

These small fixtures do not establish live-site reliability, prompt-injection
resistance, permission enforcement, or superiority over our existing browser
tools. No comparison with an external browser agent was run. The earlier source
review's authorization gaps remain; the fixture refusals measure stale and
unavailable controls, not whether an action is authorized.

## Corrections made before trusting measurements

The lead repaired a timer that stopped before awaiting inference, retained failed
provider calls in captures, and prevented incorrect actions or runtime errors from
counting as clean passes. A persistent logged bridge now disables SDK retries.
The lead added the selected-target baseline and deterministic executor probes.
Regression tests exercise awaited timing, failure retention and single-attempt
transport behavior. Production routing and application defaults were unchanged.

## Reproduction and evidence

Use [browser-trial.md](browser-trial.md) for browser setup and capture, and
[replay.md](replay.md) for both replay modes. The practical baseline uses
`--selected-only`. Run local checks with:

    node --test experiments/jev-ultrafast/*.test.mjs
    python3 experiments/jev-ultrafast/browser_trial_test.py

[results-summary.json](results-summary.json) records metrics, source hashes, and
SHA256 hashes for the complete local evidence. Raw traces remain under
`~/.local/scratch/jev-ultrafast-evaluation/`; they contain only these synthetic fixtures.
