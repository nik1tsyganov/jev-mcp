# Correction: helper bundle repinned to the locally signed rebuild (2026-10-03, before any v5 paid attempt)

- **What was wrong.** `FROZEN-v4.json` pins `oracle-bundles/debug-6d3c381729357abe`. That bundle was built with `CODE_SIGNING_ALLOWED=NO`: it has no resource seal, and `codesign -v --strict` fails. It could not be installed.
- **Correction.** The owner chose a rebuild of the same accepted source (base `329ecdea6b1f…`, diff `ee656e3eaf6e…`) with Xcode's local ad-hoc signing. The new immutable package is `oracle-bundles/debug-signed-d557cead9f917186`. Its strict deep signature check passes.
- **Equivalence on this bundle, offline.** All 60 dev and 120 held-out prepared requests are byte-identical to the stored ones. Both corpora pass every gate (held-out oracle 0.967, best constant 0.444). `tests/test_v2.py` passes: 33 run, 1 planned skip.
- **Unchanged.** Code, corpora, gold commitment, protocol, thresholds, dev best constant and the owner overlay.
- **Freezes.** `FROZEN-v4.json` is kept unchanged as superseded before-calls evidence; it was never used for any attempt. The new proof is `zero-retry-proof-v5.json` and the new freeze is `FROZEN-v5.json`.
