# Correction: helper keep-current contract and replay identity (2026-10-02)

Root approved this as a bounded offline correction. It involved no paid calls and no held-out scoring. The original freezes, results and incident are unchanged:

| File | SHA-256 prefix |
|---|---|
| `FROZEN-v2.json` | `4a65597e` |
| `FROZEN-v2-preattempt.json` | `aacbd92b` |
| `INCIDENT-2026-10-02-HELPER-REBUILD.md` | `e143ef4a` |
| `runs/dev-score-owner-bands.json` | `24d0d976` |

The pre-correction code is archived read-only in `~/.local/scratch/routing-qual-v2/code-archive/FROZEN-v2/`. Each archived file matches its `FROZEN-v2.json` hash.

## Confirmed root cause (stored dev routes, case dv2-042)

| Run | Confidence vs 0.8 | Helper result |
|---|---|---|
| Jev repeat 0 | 0.79 | `outcome: keep-current`, `currentCandidateID` = the current pair (`…0006`, the gold-correct pair), with **no** `recommendation`, `resolvedConfiguration` or `binding`; reason `classification-abstained-or-low-confidence`. The current pair is absent from the helper's failing-eligibility list. |
| Jev repeat 1 | 0.82 | `outcome: recommendation`, recommending the same pair with a `recommendation` object |
| Laya, both repeats | 0.5907 | the same keep-current shape |

`score.selected()` read only `recommendation.id`, so a helper keep-current gave `selected = None`. That produced a false `C1-candidate` violation, scored at utility 0. This was a scorer defect, unrelated to the Oracle bracket-alias change. The matrix baseline and the anti and shuffled controls hit the same defect on dv2-042.

## Patch

- **`v2lib/score.py`:**
  - On a keep-current outcome, `selected()` uses `recommendation.id` if present, else `currentCandidateID`.
  - `check()` keeps every existing check: C1 existence, C10 equals the case's current, the frozen-guard S2 check on the candidate's own configuration, C2 readiness and effort in the facts, the C5 cap, and S3, S4 and S5.
  - It adds `C10-current-ineligible` when the helper's own eligibility map lists reasons against the retained pair.
- **`v2lib/run.py`:** replay compares the executable stub, `.debug.dylib` and `droppy_cli.py` hashes. Before, it compared only the stub, which is how the post-rebuild held-out replay slipped through.
- **`v2lib/helper.py`, `context.py`, `run_v2.py`:** an `app` / `--helper-app` option points the callable at an immutable snapshot bundle.
- **`v2lib/frozen.py`:** `snapshot_helper()` and `verify_helper_snapshot()` take a whole-bundle copy plus extra files, record a per-file SHA-256 manifest, make it read-only and never overwrite. They are prepared but **not run** on the current, changing build.

## Tests

`tests/test_v2.py`: 29 tests, all passing, 1 intentional skip. The shared ledger was untouched. New tests:

1. **Positive keep-current.** A real helper-produced keep-current result (a below-threshold answer replayed through `droppy route`) resolves to the eligible current pair, with no violations and utility = `keep_current_utility`.
2. **Negatives:**
   - a fabricated current pair is kept by the helper and flagged `C10-current-ineligible`, `S2` and `S3`;
   - an unknown id fails `C1`;
   - a non-current valid id fails `C10-not-current`;
   - an absent `currentCandidateID` fails `C1`.
3. **Replay identity:** replay refuses a run whose recorded `.debug.dylib` hash differs.
4. **Snapshot tool:** complete, read-only, refuses to overwrite, detects tampering.

## Corrected dev metrics

Stored outputs only, owner rule 0.8. New file: `runs/dev-score-owner-bands.r2.json`.

| Arm | Before | After |
|---|---|---|
| Jev | 0.816, 1 violation (false C1) | **0.824** [0.752, 0.889], **0 violations** |
| Laya | 0.412, 2 false C1 | 0.428, 0 violations |
| matrix comparator | 0.520 | 0.537 |
| anti / shuffled | — | real S4 and S5 catches remain |

Jev detail: invalid output 0.000; unjustified abstention 0.125; routed-label precision 0.888 (Wilson lower bound 0.805); repeat stability 0.967; twin stability 0.90. Against the best comparator (matrix): +0.287 [0.133, 0.447]. Against the best constant: +0.314 [0.157, 0.451].

Laya still fails Q2 and Q5: unjustified abstention 0.817, and 36 of 120 requests over its token limit.

These are **dev development results, not qualification**. The run remains NONQUALIFYING.

## Remaining prerequisites for manager acceptance (none done)

1. **Final source.** The Oracle lead supplies the final, accepted, narrowed-alias source as a versioned build, with commit and diff hash, separate from the shared build.
2. **Snapshot.** Run `snapshot_helper()` on that `.app` bundle plus `conclave-seat-catalog-v1.json`, `droppy_cli.py` / `CommandLineControl.json` (client manifest) and the integration `snapshot.py`. Then run `verify_helper_snapshot()` and record the manifest hash.
3. **Offline equivalence.** With `--helper-app <snapshot>`:
   - all 60 dev and 120 held-out prepared requests are byte-identical to the stored ones;
   - both corpora pass the corpus gates;
   - `tests/test_v2.py` passes.
4. **New proof.** Regenerate the zero-retry proof, since its test-file hash changed.
5. **New freeze.** Write a new freeze (new name, for example `FROZEN-v3.json`) pinning:
   - the helper snapshot manifest;
   - the patched code;
   - the frozen catalogs;
   - both corpora and the r2 held-out commitment;
   - the new proof;
   - the dev-chosen best constant.
6. **Root authorization** of a held-out-only admission: 360 attempts, US$1.00 (65,536 tokens × US$0.042/M per attempt, rounded up), zero retries. Then the ledger freeze row, the run, the close, and held-out scoring under the new freeze. The post-rebuild held-out replay file (`heldout-jev/routes-owner-bands.jsonl`) stays unused and unopened.
