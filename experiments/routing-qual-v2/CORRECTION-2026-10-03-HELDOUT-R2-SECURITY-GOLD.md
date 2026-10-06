# Correction: held-out r2 security gold conflicts (2026-10-03, after scoring)

- **Defect.** In four experimental cases (`hv2-011` to `hv2-014`), the gold's utility-1.0 composition contains a candidate that the same gold lists in `security_unsafe_ids`. Both offered compositions in each case contain that candidate. No S4-safe route exists, so a perfect gold-label classifier is still scored `S4-security-unsafe`. All 12 S4 violations in the v5 held-out run (`runs/heldout-v5-score-owner-bands.json`) are these 4 cases x 3 repeats.
- **Evidence.** `~/.local/scratch/routing-qual-v2/analysis-v5/VIOLATIONS.md` and `violations.json` (deterministic joins, no model calls).
- **Second gap, product side.** The helper has no security eligibility rule in Hydra and experimental modes, so it offered the unsafe side pair without a reason. The Oracle lead is adding one.
- **Status.** `heldout.r2` is spent: its failures were analysed after scoring, so it cannot qualify any later build. It is kept unchanged as history. The v5 verdict stays NOT QUALIFIED as recorded. The next qualification needs a new held-out corpus, a corpus gate that rejects this conflict, and a new freeze.
