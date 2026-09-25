# Laya comparison protocol

This protocol compares Jev, upstream Laya, and Laya-MLX on identical inputs.
The runner is `tools/laya_compare.py`. The initial corpus is `data/laya-comparison-cases.jsonl`.
No production default changes unless the measured replacement meets the adoption rule.

## Corpus and labels

The 36 synthetic cases contain 12 choice, 12 noul, and 12 score questions.
Each case contains one scored question. Multiple questions are rejected, never silently ignored.
The six groups cover negation, absent evidence, multilingual input, late evidence, similar labels, and large option sets.
The lead reviewed labels before inference. Rubrics define synthetic expected answers; these are not independently human-labeled traffic.
Six late-evidence cases include about 2,500 filler words before relevant evidence to exercise truncation.

Required JSONL fields: `id`, `group`, `split`, `state`, `questions`, `expected`.
Also include `origin` and `label_source`. The shipped split is `smoke`.
Calibration cases and final evaluation cases must be disjoint.

The existing `data/merge-risk.jsonl` labels describe functional behavior change.
Only `--adapter-question behaviour_change` with `packs/merge-risk.json` is supported.
Mapping these labels to `irreversible_path` would be incorrect.
The adapter preserves source labels and marks cases `split=adapter`; they cannot authorize adoption.
The retired stale-reference dataset is excluded.

## Measurements

Each provider loads once. Downloads, model loading, first calls, and warm samples are distinct costs.
Every accelerator timing waits for completed work. Synchronization failures invalidate the call.
Warmups apply per case. Each repeated answer and distribution is retained.
The first answer measures accuracy; repeats measure stability and timing, not additional independent observations.
Errors stay in accuracy denominators. Brier and MAE use valid responses, with valid and attempted counts exposed.
Any provider error or invalid response blocks adoption.

Choice ECE uses the selected label's probability, not the API's entropy-based confidence.
Noul ECE compares P(true) with the binary label. Score ECE compares the modal level's probability with its correctness.
Score MAE compares the expected level with the labeled level.
ECE uses ten equal-width bins by default and reports each bin's count.
Never combine the three primitives into one accuracy statistic.

Paired bootstrap intervals resample independent case IDs, with a fixed seed and 2,000 samples.
Pairing requires identical case IDs, input hashes, primitives, and expected labels.
The bootstrap is descriptive on small datasets; degenerate intervals are not proof of generalization.

## Adoption rule declared before inference

- Choice and noul accuracy: at most two percentage points worse overall.
- Critical-group accuracy: at most five percentage points worse.
- Noul Brier regression: at most 0.02. Score MAE regression: at most 0.10 levels.
- No request errors or schema incompatibilities.
- A measured latency benefit; a local runtime alone does not prove absence of data egress.

Apply paired 95% intervals and at least 30 pairs per assessed metric and group.
An interval entirely beyond the regression margin fails. An interval crossing it is inconclusive.
A small, synthetic, or previously calibrated corpus cannot authorize a global switch, even with perfect observed scores.
These numerical margins are operational thresholds, not claims that 30 observations provide adequate statistical power.
Final adoption also requires representative held-out tasks, recalibrated gates, and integration checks.

## Execution

Dependencies live in `~/.local/scratch/laya-evaluation/venv`.
Model caches and raw results live under the same scratch directory.
The runtime source pins used for this evaluation are:

- Laya: `42626c348753fbb17572a813127df2278a1ec527`.
- Laya-MLX: `fc1df62828a3fedf4d8229fdac1cbd85f1cdf337`.
- MLX 0.32.2 and Transformers 4.57.6, with the complete environment recorded separately.

Run from the jev-mcp checkout. Set `HF_HOME` to the scratch cache and `USE_TF=0`.
Use the isolated environment's Python executable in place of `python` below.

    python tools/laya_compare.py --provider jev --warmup 0 --repetitions 1
    python tools/laya_compare.py --provider jev --warmup 0 --repetitions 1 --live --out /path/to/fresh/jev-results
    python tools/laya_compare.py --provider laya-mlx --checkpoint aac6fef/laya-mlx --revision 047678560251f28113ee8f5df4be82102c7bf336 --reference-run /path/to/jev-results/run.json --live --out /path/to/fresh/mlx-results
    python tools/laya_compare.py --provider upstream-laya --checkpoint convaiinnovations/laya --revision c5d78730f3493e4fe16d61507ef4b78eef7318cf --device mps --live --out /path/to/fresh/upstream-results

`--live` enables execution. Otherwise the runner only prints a plan.
Selecting a local provider never silently adds Jev requests.
`--reference-run` reuses a prior Jev run after exact input/label matching; it makes no additional Jev calls.
A missing runtime produces NOT RUN. No provider substitutes for another.
The upstream Router is a separate configuration. Its ordinary CLI mode is unpinned and must not be used as pinned evidence.
Use explicit local paths and preloaded models in a separate recorded experiment to evaluate a pinned router.

Before each live Jev pass, announce the planned request count.
The smoke reference uses 36 requests, without warmups or repeats. Calls are not retried.
The planned count is an upper bound when an error stops repeated calls or authentication stops the pass.
Jev requests use the existing credential resolver and spend logger. No credentials enter artifacts.

## Artifacts and limitations

`run.json` contains parameters, package versions, requested model/revision, resolved identity, cases, metrics, and comparisons.
`predictions.jsonl` contains provider-tagged case records and all sampled answers.
A nonempty output directory is rejected when it already contains a run. Use a new directory for each experiment.
Only a successful response establishes the live Jev model identity.
Hosted API latency and local GPU latency describe deployment choices, not equal-hardware model speed.
