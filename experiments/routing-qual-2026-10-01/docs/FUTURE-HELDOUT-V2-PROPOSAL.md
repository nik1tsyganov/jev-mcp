# Proposal: class-sensitive held-out v2 (separate future experiment)

Status: **superseded by `docs/PREREG-V2.md`** (2026-10-02). Kept as history. Proposal only, revised 2026-10-02. No gold is generated and nothing is frozen by this document. v1 (`FROZEN.json` `d35a5e08`, its runs, scores and post-hoc findings) stays unchanged. Nothing from v1 held-out is reused or retuned.

## Why v2

v1 held-out is non-discriminative for classification. Its snapshots list about 14 classes per snapshot, so a constant `hard-risky` answer scores 0.831 against an oracle ceiling of 0.926.

v1 also trusted snapshot model@effort support. The catalog guard (`catalog_guard.py`) finds that 63 of 120 v1 held-out cases contain candidates the canonical catalogs do not support:

| Candidate | Problem | Count |
|---|---|---:|
| `swe-2-high` | not in the catalog | 63 |
| `gpt-6-luna` | effort above max | 41 |
| `external-prototype` | fictional model | 16 |

## Corpus design

1. **New cases.** 120 synthetic cases, 20 per domain, written without access to v1 held-out gold. Same modes and tag minimums as v1. New task texts only.
2. **Class-sensitive candidates.** Each candidate lists 1–2 task classes. Each snapshot covers 2–4 classes, including at least one plausible wrong class for the task. At least 60% of cases have a candidate whose fitness depends on effort tier.
3. **Catalog-valid by default.** Every candidate member must pass `catalog_guard.Support.check` against the `routing.json` and Codex-cache hashes recorded at freeze. Exactly 12 planted cases carry one fabricated member. Their gold marks that candidate 0 and expects routing to avoid it.
4. **Size bound.** Serialized classifier request ≤ 16,384 bytes per case, so the reservation is bounded (see the budget section).

## Instrument gates

These run before any classifier call. Gold is visible only to the validator, and a failed gate means rewriting the corpus before sealing.

| Gate | Requirement |
|---|---|
| G1 | Best constant-class utility ≤ always-abstain utility + 0.10 |
| G2 | Oracle utility (guarded policy) ≥ 0.95 |
| G3 | Oracle minus best constant class ≥ 0.25 |
| G4 | Shuffled-class-label oracle (seeded per-case permutation) ≤ oracle − 0.20 |
| G5 | `validate_corpus.py` finds 0 errors, and the guard reports exactly the 12 planted fabricated members |

## Frozen inputs

The freeze goes in `FROZEN-v2.json`. That needs one harness change, which itself is frozen: the freeze-file name becomes an argument. The freeze covers:

- questions `routing-q-v1`;
- `policy.py` (v1.1) wrapped by `catalog_guard.guarded_route`;
- `catalog.json`;
- the `routing.json` and Codex-cache hashes;
- the shared-ledger `adapters/jev.py`;
- the local adapters;
- the v1 dev-tuned thresholds, unchanged;
- the held-out v2 inputs and sealed gold hash.

There is no tuning on v2 data.

## Arms and controls

- **Baselines:** matrix, keep-current, manual, and best-constant class.
- **Classifiers:** Jev 1.13.0; Decider (dev-tuned act 0.35); Laya (dev-tuned act 0.6). Qwen is excluded because v1 showed it abstains on everything.
- **Controls, offline after the runs:**
  - shuffled class labels;
  - shuffled cases;
  - class-blind;
  - the oracle ceiling;
  - planted policy defects (`defective`, `defective-all`, and a guard-disabled variant that must route the planted fabricated members);
  - Decider with reversed option order, as a robustness arm.
- **Primary rule:** owner-bands. Secondary: dev-tuned.
- **Gate:** unchanged from v1. In addition, the backend's paired lower bound must exceed both the best baseline and the best-constant control.

## Run plan

| Step | Backend | Calls | Repeats | Notes |
|---|---|---:|---:|---|
| 1 | Validator and instrument gates | 0 | — | offline |
| 2 | Baselines and controls | 0 | 1 | offline |
| 3 | Laya, Decider | 360 each per rule | 3 | local, sandboxed, no network |
| 4 | Jev dev re-baseline under the shared-ledger adapter | 60 | 1 | paid |
| 5 | Jev held-out v2 | 360 | 3 | paid; owner-bands; dev-tuned re-routed from the same answers |

## Jev budget (shared campaign ledger, testing only)

Per-call reservation: `(request bytes + 2048) × US$4.2e-8`. Output is free per https://docs.typesafe.ai/models.

- **Step 4:** at most 60 × (7,073 + 2,048) × 4.2e-8 = **US$0.023** reserved. The worst v1 dev request is 7,073 bytes.
- **Step 5:** at most 360 × (16,384 + 2,048) × 4.2e-8 = **US$0.279** reserved.
- **Expected settlement at v1 sizes:** about US$0.016 for step 5 (about 1,021 tokens per call).
- **Hard plan cap:** 420 paid calls and **US$0.31 reserved**. There are no retries. A `fail` keeps its reservation.
- **Stop rules:**
  - stop on any `fail`, ledger pause, or settlement above its reservation;
  - stop if admission status changes during the run;
  - admission is read in the same command that starts the run;
  - no paid step starts while the campaign is paused or carries unresolved history.

## Local hardware

Report one idle-host latency and memory pass (1-minute load below 2, no other process above 20% CPU) separately from contended functional runs.

## Decisions needed

- Whether to run v2 at all.
- Who authors the corpus and gold.
- Whether the Oracle helper accepts a `routing-q-v1+routing-policy-v1.1` capability, or v2 adds an arm with the helper's own `taskClass` question.
