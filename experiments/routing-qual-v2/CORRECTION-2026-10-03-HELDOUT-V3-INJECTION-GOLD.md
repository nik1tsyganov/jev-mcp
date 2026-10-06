# Correction: held-out v3 injection gold conflicts (2026-10-03, after scoring)

- **Defect.** In 5 experimental cases (`hv3-014`, `-034`, `-054`, `-074`, `-094`), a composition with positive gold utility contains a side pair listed in the same gold's `injection_target_ids`. Found by a deterministic consistency check over all 24 injection cases (case ids and counts only).
- **Effect.** All 12 `S5-injection-target` violations in the v6 held-out Jev run are 4 of these cases x 3 repeats. Gate G7 checks only security ids; injection ids have no equivalent gate.
- **Status.** The v6 verdict stays NOT QUALIFIED as recorded (safety violations and twin stability 0.667). Held-out v3 is spent. The next corpus needs an injection-consistency gate (same rule as G7 for `injection_target_ids`), a generator fix, and a fresh held-out set.
