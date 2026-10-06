# Routing qualification — final report (2026-10-02)

Endpoint: **honest negative qualification.** No backend is qualified for routing. Nothing is exported to the Oracle helper, saved pairs or Conclave. Nothing is promoted or activated.

Identifiers:

| Item | Value |
|---|---|
| Repo | `jev-mcp`, branch `main`, base `32f77df`; this directory is uncommitted |
| Run root | `~/.local/scratch/routing-qual-20261001/runs/` |

Fixed hashes (SHA-256 prefixes):

| File | Hash |
|---|---|
| `FROZEN.json` (v1) | `d35a5e08` |
| `catalog.json` | `544724b4` (source `routing.json` `e6dd2185`) |
| held-out `results.json` | `d70df23b` |
| sealed gold | `bbff0b94` |
| held-out inputs | `9ac28f66` |

## 1. Verdicts

| Backend | Status | Evidence |
|---|---|---|
| Jev 1.13.0 | **not-run on held-out** (by decision) | Dev only: utility 0.807 against best baseline 0.592; paired difference [+0.117, +0.309]; class acceptance 0.63; unjustified abstention 0.28, above the 0.20 gate. The held-out split cannot discriminate classifiers (section 3), so no Jev calls are spent on it. |
| Decider 2B v11 | **inconclusive** (dev-tuned, act 0.35); **unqualified** (owner-bands) | Held-out 0.680 against manual 0.716; difference −0.036 [−0.105, +0.039]. Option-order sensitive (section 5). |
| Laya (revision 28416e7) | **unqualified** | Twin stability 0.70 against the 0.80 gate. Owner-bands unjustified abstention 0.23. |
| Qwen3-Reranker-0.6B | **unqualified** | It abstains on almost every case; utility 0.480, equal to always-abstain. |

## 2. What was measured

- **Routing outcome quality.** This is utility and regret of the full pipeline (classifier, then deterministic policy) on synthetic snapshots, against gold eligible sets and defensible alternatives. Every number above is this.
- **Classifier quality.** This is measured only indirectly: task-class and effort acceptance on routed cases. Only the dev split is class-sensitive: there the best constant class scores 0.603 and the oracle 1.000. Dev class acceptance: Jev 0.63, Decider 0.33, Laya 0.22, Qwen 0.00, matrix 0.28. Dev is in-sample for thresholds and for policy v1.1, so these are development measurements, not qualification.
- **Not measured.**
  - Live dispatch outcomes.
  - Real tasks.
  - Calibration: confidence is uncalibrated, and Brier/ECE are descriptive only.
  - Idle-host performance: all timings are contended.
  - The Oracle helper's own `taskClass` question.

## 3. Instrument finding (post-hoc, preserved)

The held-out snapshots declare on average all 14 classes per snapshot (dev: 2), so the class filter rarely selects anything.

- A constant `hard-risky` answer scores 0.831 on held-out, above every backend and baseline. The gold-answer ceiling is 0.926.
- The held-out split therefore measures constraint handling and abstention, not classification.
- The held-out verdicts stand as frozen-protocol outcomes. They are weak evidence about classifier quality.
- Diagnostic: `runs/heldout-posthoc/class-sensitivity.txt`. The replacement experiment is preregistered in `docs/PREREG-V2.md` (revision 2; machine-readable `docs/prereg-v2.json`). It targets the Oracle helper's native question. Its offline harness is in `../routing-qual-v2/`, frozen as `FROZEN-v2-protocol.json` (`3e91d32a`). Corpora, gold and paid runs have not started.

## 4. Held-out table (frozen v1, sealed gold, all runs contended)

| Backend | Rule | Utility [95%] | Violations | Unjustified abstain | Repeat | Twin | Δ vs best baseline [95%] |
|---|---|---|---:|---:|---:|---:|---|
| manual | — | 0.716 [0.66, 0.77] | 0 | 0.00 | — | 1.00 | best baseline |
| matrix | — | 0.629 [0.57, 0.69] | 0 | 0.17 | — | 0.80 | −0.087 |
| keep-current | — | 0.530 [0.47, 0.59] | 0 | 0.43 | — | 1.00 | −0.186 |
| decider | dev-tuned | 0.680 [0.65, 0.71] | 0 | 0.11 | 1.00 | 0.90 | −0.036 [−0.105, +0.039] |
| decider | owner-bands | 0.522 [0.49, 0.55] | 0 | 0.49 | 1.00 | 0.90 | −0.194 [−0.268, −0.115] |
| laya | dev-tuned | 0.658 [0.63, 0.69] | 0 | 0.15 | 1.00 | 0.70 | −0.058 [−0.125, +0.010] |
| laya | owner-bands | 0.617 [0.59, 0.65] | 0 | 0.23 | 1.00 | 0.70 | −0.098 [−0.169, −0.019] |
| qwen_reranker | both | 0.480 [0.45, 0.51] | 0 | 0.56 | 1.00 | 1.00 | −0.236 [−0.306, −0.162] |

Full metrics with per-domain and per-effort breakdowns: `runs/heldout-score/results.json`, `RESULTS.md`.

Hardware: M5 Max with 64 GB, 1-minute load 3.2–10.6.

| Backend | Peak RSS | Time per 360 calls |
|---|---:|---:|
| Laya | 0.98 GB | 14 s |
| Qwen | 1.1–2.0 GB | 381–411 s |
| Decider | 4.2 GB | about 300 s |

## 5. Decider dev-jump checks (dev only)

Dev utility moved from 0.545 under owner-bands to 0.872 at act 0.35. Output: `runs/dev-diagnostics/`.

- **Leakage:** none. No class key or gold field appears in the state.
- **Parsing:** no failures and no default distributions.
- **Negative controls:** shuffled class labels 0.557, shuffled cases 0.510, class-blind 0.598, always-abstain 0.487.
- **Candidate filter:** no route used an unacceptable class. The class filter turned 3 confident wrong answers into abstentions.
- **Label order:** labels map by key, but reversing option order moves probabilities by up to 0.35 and changes the top label in 3 of 10 cases.
- **Verdict:** a real in-sample gain that did not carry over.

## 6. Model and effort eligibility contract (as implemented)

A route may only name what the caller's snapshot supplies. The benchmark never invents a model, effort, role or count.

- **Identity.** `lead` and `heads` are `{model, provider, effort, role[, profile]}` copied from one snapshot candidate. Providers: anthropic, openai, google, cognition; anything in `unsupported_providers` is ineligible (C3). Catalog models (`catalog.json`, from `routing.json`):

  | Model | Provider | Efforts |
  |---|---|---|
  | opus, fable | anthropic | low–max |
  | gpt-6-astra | openai | low–ultra |
  | gpt-6-sol, gpt-6.1-sol, gpt-6-luna | openai | **none recorded in `routing.json`** |
  | gemini-3.8-flash-{high,medium,low}, gemini-3.1-pro-{high,low} | google | fused into the slug |
  | swe-2-high | cognition | high (benchmark fixture only) |

- **Effort.** `routed_effort` is the smallest effort whose cumulative probability reaches the rule's quantile. The candidate chosen is the eligible one with the smallest lead effort at or above that. If none qualifies, the highest available effort is used and `effort-below-need` is reported.
- **Model@effort support (post-v1 guard, `catalog_guard.py`).** Frozen v1 trusts the snapshot's model–effort pairs, so a caller can fabricate support. The guard removes any candidate with an unsupported member before the v1 policy runs, re-checks the emitted route, and abstains when nothing remains. It records `catalog_guard` provenance: version, source hashes, and the removed candidates with reasons.

  A member is supported only if all of these hold:
  - the model is listed for its vendor in `routing.json` (`claudeModels`; `codexModels` plus `codexReviewModel`; `geminiModels`);
  - its provider matches;
  - its effort is supported, by vendor:

  | Vendor | Supported efforts |
  |---|---|
  | anthropic | `routing.json` `efforts.claude`, low–max |
  | openai | the Codex vendor cache's `supported_reasoning_levels`, intersected with `routing.json` `codexByModel` where that has an entry |
  | google | the slug suffix; an explicit effort must match it |

  Unknown means unsupported. Sources at check time:
  - `routing.json`: `e6dd2185`, updated 2026-09-30;
  - `~/.codex/models_cache.json`: `aebe103d`, fetched 2026-10-02T01:27Z.

  Resulting rows:
  - `gpt-6-astra`: low–ultra;
  - `gpt-6.1-sol`: low–ultra;
  - `gpt-6-sol`: low–ultra;
  - `gpt-6-luna`: low–max;
  - `codex-auto-review`: low–max;
  - `opus` and `fable`: low–max;
  - `swe-2-high` (cognition): unsupported, because it is not in the canonical catalog.
- **Ranking.** Candidates using the routed class's `routing.json` implement or fallback models rank first. Then: current candidate, fewer helpers, id.
- **Role and count.**
  - A saved pair or seat binding keeps its configured `helper_count`. Above `max_helpers` it is ineligible (C5).
  - An experimental composition sums its sides' counts, which must fit `max_helpers`, and needs `experimental_opt_in`.
  - Conclave security-sensitive or hard-risky classes need two checkers whose providers differ from each other and from the lead.
- **Other constraints.** C2 availability, C4 evidence age, C6 context window and C7 tools apply to every used candidate.
- **Provenance and uncertainty.** Every route carries backend, classifier model and revision, question-set, policy and catalog versions, rule and thresholds. It also carries class top-p, margin, security-p, ambiguous-p and `calibrated: false`. `dispatch_authorized` is always false.
- **Failure.** An adapter error becomes `backend-unavailable`, then keep-current or abstain. There is never another backend and never truncation.

## 7. Schema compatibility vs empirical qualification

- **Schema compatibility** (`docs/ADAPTER-CONTRACT.md`, `docs/ORACLE-HELPER-SCHEMA.md`). Route fields map onto `OracleRoutingResult`, and the outcome strings match. There are gaps:
  - only 6 of 14 class labels are shared with the Conclave matrix;
  - the helper has no effort, security or ambiguity fields;
  - the helper's backend enum is jev or laya only;
  - the helper requires capability `oracle-classification-policy-v1`, which names a different question.

  A mapped field is not evidence that the classifier is good.
- **Empirical qualification.** None exists. No backend passed the held-out gate, and the held-out instrument cannot discriminate classification. A future pass would also need the owner to accept a `routing-q-v1+routing-policy-v1.1` capability, or a rerun through the helper's own question, before any helper qualification row.

## 8. Harness and accounting checks

- **Benchmark tests:** 23 unit tests pass, and `validate_corpus.py` finds 0 errors on both splits.
- **Planted defect:** `defective-all` gives 15 violations, and utility falls from 1.000 to 0.668.
- **Malformed outputs:** all 7 malformed-output controls are rejected.
- **Network:** the sandbox blocks network access (EPERM), while the same connection works outside it. There were no held-out network attempts.
- **Shared-ledger adapter:** 5 offline tests, passing 3 runs in a row, against a fake server and a temporary ledger. A valid reply settles. HTTP 500, missing usage, wrong resolved model and a dropped connection each record a fail. Pause or unresolved history blocks the call before the network. A six-process race stays within the ceiling. A SIGKILL mid-call leaves an open reservation counted at its full `maxUSD`. Oracle's module tests also pass.
- **Repo regressions:** after the optional `spend_log` tag, 157/157 Node tests and 4/4 Python test scripts pass.
- **Unintended paid call (disclosed).** At 2026-10-02T01:22:26Z a probe meant to show refusal ran against the shared ledger, 15 s after an owner resume was appended. It made one paid dev call: 1,052 input tokens, US$0.0000442. It was correctly reserved (`3839ab90`), settled (`cb5f18c2`) and tagged in telemetry. Run directory: `runs/smoke/jev-unintended-paid-call-after-resume-2026-10-02T012226Z`. No other Jev calls ran in this pass.
- **Catalog guard tests (`tests/test_catalog_guard.py`, 6 tests).**
  - **Positive:** every dispatch-row and Conclave-seat model@effort is supported, except a frozen list of four catalog inconsistencies. Required rows pass, including Astra medium/high/xhigh and Sol 6.1 medium–ultra.
  - **Negative:** 13 fabricated or unsupported members are refused. Examples: Luna@ultra, Opus@ultra, a provider mismatch, a Gemini effort contradicting its slug, `swe-2-high`, an agy third-party slug, a missing effort, unknown models.
  - **Behaviour:** routing.json and the cache are intersected; with no cache, routing.json alone is used; a fabricated snapshot abstains where v1 routed it; a supported candidate routes as in v1.
  - **Mutation check:** disabling the effort or provider check fails 9 and 1 assertions respectively.
- **Catalog inconsistencies found (reported, not fixed; no Conclave or catalog edits).**
  - Conclave seat `gpt-5.6-sol@high` uses a model absent from `routing.json` `codexModels`.
  - Fallback rows use `sonnet@medium`, `haiku@medium` and `haiku@high`, which are aliases, not listed Claude models.
  - `routing.json` `codexByModel` has no effort rows for `gpt-6.1-sol`, `gpt-6-sol` or `gpt-6-luna` and still lists `gpt-5.6-*`.
- **Guard impact.**
  - Dev: 11 of 192 candidates removed; 0 of 60 routes change for matrix, manual, oracle, Jev, Decider and Laya.
  - v1 held-out (inputs only, not rescored): 63 of 120 cases lose candidates.
  - Output: `runs/catalog-guard/impact.txt`.
- **Total Jev calls from this project:** 243, all dev or smoke. Receipt for the earlier 242: `runs/FAILURE-RECEIPT-routing-qual.json`.

## 9. Post-freeze changes (disclosed)

- `score_heldout.py` fixes only the sealed-gold hash-line check; a tampered gold file is still refused. `score.py` stays frozen.
- `adapters/jev.py` now uses the shared campaign ledger. The v1 adapter is kept at `runs/frozen-v1-copies/jev.py`; its hash `ac7cb293` matches the freeze. `FROZEN.json` therefore no longer verifies, and the harness refuses held-out runs under v1. The local held-out scores still reproduce exactly.
- The interrupted Qwen run is kept as `runs/heldout/interrupted-qwen_reranker-owner-bands-0of360`.

## 10. Reproduce (offline, no paid calls)

Run from this directory with `PY=~/.local/scratch/laya-evaluation/venv/bin/python`:

    $PY -m unittest tests.test_routing_qual tests.test_jev_campaign_adapter
    $PY validate_corpus.py cases/dev.jsonl cases/dev-gold.jsonl
    $PY score.py score --runs <dev run dirs> --gold cases/dev-gold.jsonl --out <dir>
    $PY score_heldout.py score --runs <held-out run dirs except interrupted-*> \
        --gold ~/.local/scratch/routing-qual-20261001/sealed/heldout-gold.jsonl --out <dir>
    $PY diagnostics/decider_checks.py <runs>/dev-backends/decider <runs>/thresholds/decider.json <out.json>

Local backend reruns use `harness.py run --backend laya|qwen_reranker|decider --split dev`. Held-out reruns are refused under v1 by design.

## 11. Limitations

- No backend is qualified. The held-out split cannot discriminate classification, and v1 held-out scores do not reflect the catalog guard.
- Anthropic effort support comes from `routing.json` only; no vendor-native Claude catalog is read offline. The Codex cache is a live file that changes between runs, so guard results are tied to its recorded hash.
- The guard checks the model@effort list. It does not check account access, quota or provider readiness, which are caller readiness facts.
- Every local timing is contended. There is no idle-host measurement.
- Confidence is uncalibrated.
- Jev was evaluated on dev only, and dev results are in-sample for thresholds and policy v1.1.
- One unintended paid call is recorded and kept (section 8).
