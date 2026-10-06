# Correction: owner overlay Q2 boundary restored to the original frozen protocol (2026-10-02, before any v3/v4 paid attempt)

- **What was wrong.** `v2lib/acceptance.py` had implemented unjustified abstention as strictly `< 0.20`, following an instruction the qualification manager has since withdrawn as boundary drift.
- **Correction.** The overlay now uses `<= 0.20`, matching:
  - the original preregistration (PREREG-V2 section 7, Q2 "<= 0.20");
  - the frozen scorer gate label "Q2 unjustified abstention <= 0.20".

  Exactly 0.20 passes; anything above 0.20 fails.
- **Unchanged:**
  - per-mode lower bound strictly > −0.05 for EVERY requested mode (a missing mode fails);
  - adjusted utility lower bound > 0 against BOTH the best comparator and the best constant;
  - all other original gates;
  - the 0.8 owner threshold.
- **Test.** `OwnerAcceptanceOverlay.test_unjustified_abstention_boundary_matches_original_q2`: 0.20 → QUALIFIED, 0.21 → NOT QUALIFIED. The boundary-case list now tests 0.2000001 → NOT QUALIFIED.
- **Freezes.** `FROZEN-v3.json` (`f0f68b4b…`) is kept unchanged as superseded before-calls evidence; it was never used for any attempt. The new proof is `zero-retry-proof-v4.json` and the new freeze is `FROZEN-v4.json`.
