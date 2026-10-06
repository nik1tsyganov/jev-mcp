# Routing qualification protocol (preregistered 2026-10-01)

## Question

Can a classifier backend improve task routing (model, provider, effort, role and helper count for Hydra saved pairs, experimental compositions and Conclave seat bindings) over deterministic and do-nothing baselines without breaking any constraint?

Jev is the owner's backend. Laya is an optional free local backend for people without Jev. It is not an automatic fallback for Jev. Qwen3-Reranker-0.6B and Decider Mapika 2B v11 are local alternatives under the same inputs and decision rules. Earlier context-deletion results do not transfer to this task (see `docs/EVIDENCE-INVENTORY.md`).

## Design

- The backend only classifies. It answers five frozen questions (`questions.py`, version `routing-q-v1`): task class (14 `routing.json` classes plus `unclear`), effort, security-sensitive, injection, ambiguous. Its state is `task_text`, `mode` and `metadata` only. It never sees the snapshot, gold, domain or tags.
- Deterministic code (`policy.py`) applies constraints C1-C10 and the routing matrix (`catalog.json`, extracted from the Agent-Vault `routing.json`). The route object carries model, provider, effort, role, helper count, provenance and uncertainty. `dispatch_authorized` is always false.
- `score.py` re-checks every route with an independent constraint checker. It does not import `policy.py`.
- Gold encodes acceptable classes and efforts, utilities for each candidate (1.0 preferred, 0.7 defensible, 0.3 weak, 0 wrong or ineligible), and utilities for abstaining and for keeping the current candidate. Rubric: `cases/GOLD-RUBRIC.md`.

## Corpus

| Split | Cases | Author | Gold location |
|---|---:|---|---|
| dev | 60 | Walter | `cases/dev-gold.jsonl` |
| held-out | 120 | Ada (independent of dev) | sealed outside the repo; SHA-256 committed in `cases/heldout-gold.sha256` |

Both splits cover backend, frontend, research, document/PDF, mechanical and ambiguous domains. They vary context size, tool needs, availability, evidence age, saved pairs, helper caps and unsupported providers. They include malicious task text, missing metadata, ties, no-eligible abstentions and paraphrase twins. `validate_corpus.py` checks structure and gold eligibility against the constraints.

## Decision rules

- `owner-bands` (primary): act at p >= 0.8 and flag at 0.6-0.8, which is the owner's Jev rule. A flag counts as abstain with a suggestion.
- `dev-tuned` (secondary): `act` and `effort_q` per backend from the grid {0.35, 0.4, 0.5, 0.6, 0.7, 0.8}, chosen on dev by mean utility with zero violations. Ties go to the higher threshold.
- Security is forced at p(yes) >= 0.5. Injection is informational only. The policy never reads task text.
- Errors such as `input_over_limit`, `timeout` or `malformed` become `backend-unavailable`. It is scored with the abstain utility. That is the conservative fallback: no route, never another backend. Inputs are never truncated.

## Baselines and controls

- Baselines: `matrix` (keyword lookup over `routing.json` titles), `keep-current`, and `manual` (always standard-feature/medium). Always abstaining equals the malformed-control utility.
- Positive controls: `control_oracle` (gold answers; dev only), `control_anti`, `control_constant`, `control_random`, and seven malformed-output variants.
- Planted defects: `--policy defective` (ignores unsupported providers) and `--policy defective-all` (drops C2-C7). The checker must report violations.
- Network control: `control_network` must be blocked by the `sandbox-exec` deny-network profile used for every local backend.

## Metrics

Invalid-output, invalid-route and constraint-violation rates; justified and unjustified abstention; utility and regret; class and effort acceptance; repeat and twin stability; degenerate-output flag; latency p50/p95; peak RSS; input tokens and USD.

- Proportions use Wilson 95% intervals.
- Means use a 2,000-resample percentile bootstrap (seed 20261001).
- Comparisons against the best baseline use a paired bootstrap over case-mean utility.
- Results are broken down per domain and per preferred effort.
- Brier and 10-bin ECE are descriptive only. Confidence is treated as uncalibrated.

## Qualification gate (held-out)

A backend is **qualified** only if all of these hold:

- zero constraint violations;
- invalid-output Wilson upper bound <= 0.05;
- unjustified abstention <= 0.20;
- repeat stability >= 0.95 and twin stability >= 0.80;
- local backends make no network attempts, and over-limit input becomes `backend-unavailable`;
- complete runs;
- paired-bootstrap lower bound of (backend minus best baseline) utility > 0.

If every other check passes but the interval spans 0, the status is **inconclusive**. Otherwise it is **unqualified**. A successful run or a model-card score is not qualification.

## Execution order

1. Offline controls on dev.
2. Backend dev runs, 2 repeats.
3. `harness.py tune` per backend.
4. `harness.py freeze`. This hashes the policy, questions, catalog, adapters, harness, scorer, thresholds and held-out inputs, and records the held-out gold commitment.
5. Held-out runs, 3 repeats, owner-bands and dev-tuned.
6. Score with the sealed gold. The scorer refuses gold whose hash does not match, or a run that started before the freeze.

Host load is recorded per run. Every timing is labelled `idle` or `contended`, and contended timings are not performance claims.

## Budget

Jev costs US$0.042 per million input tokens and output is free (https://docs.typesafe.ai/models, checked 2026-10-01). This phase has a US$1.00 hard cap, enforced by a locked ledger in the runs directory. That cap sits inside the owner's US$30 total across projects. There are no retries and no automatic purchases.

## Dev-phase changes (before freeze)

- `policy.py` v1 to v1.1: a saved-pair or seat-binding `helper_count` is a fixed configuration and is never clamped. A candidate above `max_helpers` fails C5. An experimental composition sums its sides' counts. Both corpus authors and the Oracle helper contract ("return it unchanged") use this reading.
- `policy.py` v1.1: candidates using the routed class's `routing.json` models rank before the helper-count tie-break. With v1, oracle answers reached utility 0.918 on dev; with v1.1 they reach 1.000. The v1 runs are kept in `runs/dev-offline-policy-v1`.
- `score.py`: null `preferred_effort` is bucketed as `none`. The over-limit error name is aligned to `input_over_limit`. Baseline comparison uses owner-bands baseline runs for both rules.
- `questions.py` and `policy.py`: probability sums are accepted within max(1e-3, 0.005 x label count), the rounding bound of Jev's two-decimal wire values. The first Jev dev run rejected 2 of 120 records only for sums of 0.99. It is kept in `runs/dev-backends/jev-validator-1e-3`. Distributions are never renormalized.

## Post-freeze adapter change (2026-10-02)

- `adapters/jev.py` now accounts every call in the shared Jev testing-campaign ledger (campaign CONTRACT.md v1). It reserves before the network call, then settles on a reply with measured input usage for the requested model, or fails otherwise, keeping maxUSD. Admission is refused while the campaign is paused or has unresolved history. A verified price file is required. Spend-log rows carry `campaignReserveId`.
- The frozen v1 adapter (SHA-256 `ac7cb293…`) is kept outside the repo in `runs/frozen-v1-copies/`. `FROZEN.json` therefore no longer verifies, and the harness refuses held-out runs under v1. That is deliberate. Any later Jev held-out run needs a new freeze, which the replacement held-out split needs anyway. The local held-out results scored under v1 still reproduce exactly.
