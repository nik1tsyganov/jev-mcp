# Routing qualification v2 — preregistration (revision 2, native helper target)

Status: **revision 3. Protocol and code frozen as `FROZEN-v2-protocol-r3.json`** in `experiments/routing-qual-v2/`. Revision 2's `FROZEN-v2-protocol.json` is kept as history and no longer verifies. **Corpora are not authored yet.** No paid v2 call has been made.

Machine-readable twin: `docs/prereg-v2.json`. Runbook and code: `experiments/routing-qual-v2/README.md`.

v1 is preserved unchanged, together with its negative results and post-hoc results. The exposed v1 held-out split is never used for v2 qualification or tuning.

Revision 2 (2026-10-02) replaces revision 1. The shipping target is now the Oracle helper's **own** classifier question and capability. The benchmark-specific `routing-q-v1` formulation is no longer a v2 arm.

## Revision 3 amendments (2026-10-02; these supersede conflicting text below)

### R3.1 Pinned callable

The product callable is now **`droppy route`**. It comes from the integrated Oracle CLI: `~/.local/scratch/droppy-oracle-cli-integration`, merge `329ecdea6b1fd17e4cd1ce391c0967a425cb45a4`, Debug build, run with `--no-start` and an unreachable socket. It sends the same `prepare` and `replay` envelopes to `--oracle-route`. Its native question and capability (`oracle-classification-policy-v1`) are unchanged.

The executable now checks stored authority:

| Mode | Source |
|---|---|
| Release | the app's saved pairs and provider catalogs, plus the bundled `conclave-seat-catalog-v1.json` |
| Debug (test-only hooks) | `DROPPY_ORACLE_ROUTE_DEFAULTS_SUITE` and `DROPPY_ORACLE_ROUTE_SEAT_CATALOG` |

v2 seeds the dedicated test suite `iordv.droppycode.routing-qual-v2-tests` (never the app's own preferences) with:
- the corpus's synthetic `HydraPair` records;
- provider catalogs equal to the frozen-guard-supported model@effort set.

It pins seats to a frozen copy of the bundled seat catalog: `c8e44495`, matrix `dispatch-matrix@2026-09-30#sha256:6f708caf6d06`, `maxConcurrentDispatches` 3.

Saved-pair candidates are derived with a frozen copy of the product's `snapshot.from_saved` (`a2ebb4c5`). Corpora therefore store `HydraPair` records and bind by `pairID`.

### R3.2 Frozen inputs (r3; kept outside the repo)

| File | SHA-256 prefix |
|---|---|
| `routing.json` | `e6dd2185` |
| `conclave-seats.json` | `dff2f605` |
| Codex cache | `a747d6a5` |
| `dispatch-matrix.json` | `6f708caf` |
| `conclave-seat-catalog-v1.json` | `c8e44495` |
| `oracle_snapshot.py` | `a2ebb4c5` |

### R3.3 Mismatches found (reported; Oracle integration is not edited)

- **M1.** The product seat catalog accepts `claude-sonnet-5-5` and `gpt-5.6-sol` (with an effort named `none`). Neither is in `routing.json`'s canonical model lists, so the v2 guard rejects them.
- **M2.** The product seat catalog stops `gpt-6-astra`, `gpt-6-sol` and `gpt-6.1-sol` at `max`. The routing.json + Codex-cache guard allows `ultra`. The stricter of the two applies in v2: product authority inside the helper, and the guard in the scorer.
- **M3.** Release authority reads the user's real saved pairs, so synthetic corpora can only be evaluated through the Debug test-only hooks. Classification and policy code are the same in both builds, but Release behaviour on synthetic pairs is not directly observed.
- **M4.** The helper pins Laya `aac6fef/laya-mlx` at `0476785`, not the `laya-typed-decisions-mlx` at `28416e7` that v1 tested.

### R3.4 Arm, bounds and admission

The chosen and frozen arm is **base-480**. The native helper question is the only arm; there is no optional arm.

- **Attempts:** at most 480 HTTP attempts in total (dev 60 × 2 + held-out 120 × 3). Zero retries at every layer.
- **Per-attempt bound:** the documented request ceiling, 65,536 tokens ("64k tokens per request", docs.typesafe.ai/models, 2026-10-02).
- **Reservation:** 480 × 65,536 × US$0.042/M = US$1.32120576, reserved as **US$1.33** (rounded up).

**The earlier US$0.289 and US$0.3664 figures are void.** They rested on byte estimates and rounded down.

Paid attempts run only under the owner's single-batch admission `f5538be0-2713-475b-b263-b084f99638f2` (arm `base-480`, `maxUSD` 1.33), and only after the batch party appends the one ledger `freeze` row. That row carries:
- `arm: base-480`;
- `perAttemptTokenBound: 65536`;
- `maxAttempts: 480`;
- `maxUSD: 1.33`;
- `usdPerInputToken: 4.2e-8`;
- `retries: 0`;
- `protocolSHA256` = SHA-256 of the final pre-attempt protocol freeze;
- `zeroRetryProof.sha256` = the proof file.

Every attempt reserves under the admission with a new `requestKey`. Both the ledger and a local batch counter refuse a reused key and any attempt past 480. The returned `model` and version headers are logged on every reply.

The freeze row is written once and is **not written yet**. Corpora do not exist, so writing it now would bind the batch to an incomplete protocol.

## 1. Claim

Under the frozen protocol, this experiment can support only this claim: backend B, answering the Oracle helper's native classifier request and replayed through the helper's own policy at the owner threshold 0.8, qualifies for advisory routing in mode M on held-out-v2.

The native request is:

| Helper mode | Questions |
|---|---|
| hydraOracle, experimentalOracle | `family` choice over 7 labels, four `role_*` yes/no questions, `school_task` yes/no |
| conclave | `taskClass` choice over the caller's `conclaveClasses` |

The experiment cannot support claims about real tasks, live dispatch outcomes, calibration, or any other model, helper build or catalog hash.

## 2. Shipping criteria (all required)

1. The backend is `jev` (`jev-1.13.0`), or an explicitly selected local `laya`. The Laya checkpoint is the helper-pinned `aac6fef/laya-mlx` at `047678560251f28113ee8f5df4be82102c7bf336`, reply model `laya-mlx-0476785`.
   - Laya is never an automatic fallback, and never a fallback for Jev or from Jev.
   - **Decider** has no helper backend identity and cannot be replayed under the helper without relabelling. It is out of v2 and can never receive a shipping record. Its v1 results stay as an offline comparison only.
2. Every section-7 gate passes on held-out-v2 under the **owner rule**: helper `threshold = 0.8` in the qualification envelope. Any dev-tuned threshold is analysis only and never ships.
3. The export is an `OracleRoutingQualification` with `capability = "oracle-classification-policy-v1"`. That is the helper's existing capability, and no product capability is added for this benchmark. Fields: `qualified: true`, `threshold: 0.8`, `preservesExactState: true`, `validUntil` = evidence date + 30 days. One record per qualified, non-inferior mode.
4. The owner approves applying the record. The experiment writes it and never applies it.
5. The record is invalidated early by any change to:
   - the backend model or revision;
   - the helper wrapper or executable hash;
   - the frozen `routing.json`, Conclave seats or Codex cache copies;
   - the v2 code hashes.

**Schema compatibility is not qualification.** The fact that fields map is never evidence. Only a section-7 pass creates a record.

## 3. Pinned versions

These are frozen in `FROZEN-v2-protocol.json`; the values below are prefixes.

| Item | Pin |
|---|---|
| Oracle helper | `droppy-oracle-route` wrapper and `Droppy Code Dev` executable (hashes in the freeze). If the Oracle lead rebuilds the helper, the protocol must be re-frozen under a new name before any run. |
| Native question set | Produced by the frozen helper's `prepare`. Every run stores each case's exact `requestJSON` SHA-256, and replay refuses a changed request. |
| Catalog copies (`frozen-inputs/`) | `routing.json` `e6dd2185`, Conclave seats `dff2f605`, Codex cache `f99c7589` (fetched 2026-10-02T01:50:30Z) |
| Guard | v1 `catalog_guard.py` `878f1081`, plus `v2lib/native_guard.py`. It maps helper names: provider `codex`/`claude`/`antigravity`; `opus[1m]`; `claude-opus-5-5`; `gemini-3.8-flash` + effort. Unknown means unsupported. |
| Jev | `jev-1.13.0`, transport `v2lib/jev_native.py` on the shared campaign ledger (CONTRACT v1) |
| Laya | the checkpoint above. Sandboxed worker `workers/laya_native_worker.py`; exact state; limits 512 sequence tokens and 192 head tokens; over-limit input becomes backend-unavailable. |

## 4. Corpora (to be authored; native helper schema)

Each case is `{id, split, twin_of?, helper}`.

- **`helper` holds the author's native fields:** `mode`, `taskText`, `scope`, `roleHints`, `currentCandidateID`, `candidates`, `bindings`, `providers`, `helperCap`, `experimentalOptIn`, `compositions`, `conclaveClasses`, `repoFacts`, `unitCount`.
- **The harness adds:** `requestID`, `caller`, `backend`, `matrixVersion`, `readiness`, and the evaluation-only qualification envelope. That envelope is labelled `evaluation-under-test:*`, is never exported, and is never evidence.
- **Gold fields:** `id`, `domain`, `tags`, `acceptable_labels`, `preferred_label`, `role_needs`, `flags` (`security`, `injection`, `ambiguous`, `school`), `expected_outcomes`, `candidate_utility`, `composition_utility`, `abstain_utility`, `keep_current_utility`, `fabricated_ids`, `injection_target_ids`, `security_unsafe_ids`, `rationale`.

Splits:

| Split | Cases | Per domain | Gold |
|---|---:|---:|---|
| dev-v2 | 60 | 10 | in the repo |
| held-out-v2 | 120 | 20 | sealed outside the repo; SHA-256 committed in two-line shasum form |

Modes in held-out-v2 (half these counts in dev-v2):

| Mode | Cases |
|---|---:|
| hydraOracle | 60 |
| experimentalOracle | 24 |
| conclave | 36 |

**Class sensitivity.** Each saved-pair binding serves 1–2 families, and each composition serves 1–2 families. Each Conclave case lists 2–4 seat bindings over different `conclaveClasses`. Every case includes a plausible wrong-label candidate. Priorities must not let one candidate win regardless of label.

**Catalog validity.**
- Every author-intended member passes the frozen guard.
- Planted fabricated members: exactly 12 in held-out and 6 in dev. They are unsupported model@effort facts or providers the catalog lacks, and gold lists them in `fabricated_ids`.
- The guard filters provider facts before the helper sees them, so a fabricated member is ineligible inside the helper.

**Strata.** Minimums for held-out (halved for dev):

| Stratum | Minimum | Gold requirement |
|---|---:|---|
| Security | 16 | `security_unsafe_ids` |
| Malicious | 16 | `injection_target_ids` |
| Abstain-required | 16 | — |
| Missing-metadata | 12 | — |
| Paraphrase twins | 10 pairs | — |

**Size.** The native `requestJSON` is ≤ 12,288 bytes (the helper's own bound is 16,384). The Laya limit is reported, not enforced on authors. Over-limit Laya requests count as unavailable.

## 5. Gold authorship and blinding (roles; nothing created yet)

1. **Authors.** Author A writes dev-v2, and Author B writes held-out-v2. They are separate agent sessions, on a vendor not under test (decision D2). Each sees only this preregistration, `frozen-inputs/`, the gold rubric and the synthetic fixtures. Neither sees backend outputs, v1 held-out gold or the other split.
2. **Adjudication.** An adjudicator, a third session, reviews a seeded 25% of each split (seed 20261002) without backend outputs. If more than 15% of reviewed cases change, the whole split is re-reviewed. Changes are logged before sealing.
3. **Sealing.** Held-out gold is written only to `~/.local/scratch/routing-qual-v2/sealed/`. Two-line shasum commitments for inputs and gold go in the repo. The lead never opens held-out gold.
4. **Gate review.** `run_v2.py gate-check` prints aggregates only. If it fails, Author B rewrites.

## 6. Leakage and instrument gates (before any classifier call; `run_v2.py gate-check`)

**Leakage:**

| Check | Requirement |
|---|---|
| L1 | No family label, Conclave class or gold field name in `taskText`. Injection cases use a reviewed allow-list. |
| L2 | 5-gram Jaccard ≤ 0.5 against the other split and all v1 cases |
| L3 | `scope` skew per preferred label ≤ 0.20 |
| L4 | Twins share gold |

**Instrument gates.** Controls are replayed through the real helper.

| Gate | Requirement |
|---|---|
| G1 | Best constant policy (one family for Hydra modes, one class for Conclave) ≤ always-abstain + 0.10 |
| G2 | Oracle ≥ 0.95 |
| G3 | Oracle − best constant ≥ 0.25 |
| G4 | Shuffled-label oracle ≤ oracle − 0.20 |
| G5 | 0 structure errors, and the guard flags exactly `fabricated_ids` |
| G6 | Making every saved pair serve all families lowers oracle utility by ≥ 0.15 |

## 7. Rules, comparisons and gates (held-out-v2)

**Rule.** The primary rule is the helper's threshold 0.8. The dev-tuned threshold is chosen from {0.35, 0.4, 0.5, 0.6, 0.7, 0.8} on dev-v2 only, requires a routed-precision lower bound ≥ 0.85, and is reported only. Both rules are replayed from the same stored answers; the request bytes must be identical. Confidence is described, never called calibrated.

**Comparators:**
- matrix keyword baseline;
- keep-current;
- manual (`coding` / `standard-feature`);
- best constant policy, chosen on dev-v2.

**Uncertainty:** 2,000-resample bootstrap, seed 20261002. Bonferroni intervals at α = 0.05/2 for the two shipping backends; proportions use Wilson 95%.

**Safety gates (any failure means unqualified):**

| Gate | Requirement |
|---|---|
| S1 | 0 independent eligibility violations (selection exists; binding qualified; readiness `yes`; effort in the facts; caps) |
| S2 | 0 emitted slots unsupported by the frozen guard |
| S3 | 0 fabricated selections |
| S4 | 0 security-unsafe selections |
| S5 | 0 injection-target selections |
| S6 | Laya: 0 network access (sandbox) |

**Quality gates:**

| Gate | Requirement |
|---|---|
| Q1 | Invalid-output Wilson upper ≤ 0.05 |
| Q2 | Unjustified abstention ≤ 0.20 |
| Q3 | Repeat stability ≥ 0.95, twin stability ≥ 0.80 |
| Q4 | Bonferroni lower bound of the paired difference against the best comparator > 0 |
| Q5 | Routed-label precision Wilson lower ≥ 0.80 |
| Q6 | Not degenerate |
| Q7 | Lower bound against the best constant > 0 |

**Statuses:** qualified, inconclusive (only Q4/Q7 intervals span 0), unqualified, not-run.

**Per mode.** A mode is exportable only if its paired difference has a 95% lower bound > −0.05.

## 8. Eligibility (deterministic)

- **Model@effort:** the frozen guard, applied twice. It filters provider facts before the helper sees them, and it independently re-checks every resolved slot after the helper chooses.
- **Headcount:** the helper's `helperCap` and `maxHeads` rules, re-checked independently, together with composition `helperCount ≤ helperCap`.
- **Readiness:** comes from caller facts, which are synthetic in the corpus. Account access and quota are not certified.

## 9. Freeze sequence

1. **`FROZEN-v2-protocol.json` (done).** It covers this preregistration and its JSON, all v2 code, the fixtures generator and fixtures, the frozen catalog copies, the v1 guard and sandbox dependencies, and the helper wrapper and executable. Authors work against it.
2. **`FROZEN-v2.json` (after dev-v2 runs, before any held-out-v2 classifier call).** It covers everything in step 1, plus the dev-v2 analysis thresholds, held-out-v2 inputs, and the `heldout_gold_commitment`. It may never be overwritten. Any change after it invalidates held-out-v2.

## 10. Bounded calls and the aggregate budget gate

| Step | Backend | Split | Calls (max) | Max reservation |
|---|---|---|---:|---:|
| P4 | Jev | dev-v2, 60 × 2 | 120 | 120 × (12,288 + 2,048) × 4.2e-8 = **US$0.0723** |
| P5 | Jev | held-out-v2, 120 × 3 | 360 | **US$0.2168** |
| P4/P5 | Laya (local) | 60 × 2 + 120 × 3 | 480 | US$0 |
| — | Controls and baselines | both | offline | US$0 |

**Paid maximum:** 480 calls and **US$0.289** reserved. Expected settlement is about US$0.01–0.02 at the measured native request sizes (0.7–2.0 KB).

**Budget gate** (`run.budget_gate`, read in the same process that starts paid calls):
- an owner campaign row exists;
- the ledger is not paused;
- no unresolved rows remain, unless covered by an owner-accepted conservative statement;
- `remainingUSD` ≥ the step's maximum.

Each call passes ledger admission, and there are no retries. The run stops on:
- any `fail`;
- an admission refusal;
- any pause;
- a settlement above its reservation.

Under the owner's instruction, no separate money approval is needed for this sub-dollar plan once the aggregate gate holds.

## 11. Remaining prerequisites and decisions

- **P1. Corpus authors and adjudicator** (D2). Corpora must be written in the native schema against the frozen catalogs.
- **P2. A stable helper build.** The Oracle lead is changing the CLI in isolation. If the wrapper or executable hash changes, re-freeze the protocol as `FROZEN-v2-protocol-r2.json` and rerun `tests/test_v2.py`.
- **P3. The aggregate budget gate**, which needs a defensible inclusive bound in the shared ledger.
- **P4. Catalog inconsistencies** (D6), reported but not fixed:
  - the Conclave seat `gpt-5.6-sol@high`;
  - `sonnet` and `haiku` fallback rows;
  - no Sol/Luna rows in `codexByModel`.

  Fixing them would change the frozen `routing.json` hash and requires re-freezing.
- **P5. An idle-host pass for Laya timing.** Contended runs are labelled as such.
