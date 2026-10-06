# dev-v2 correction receipt (lead-authored split; before any classifier result)

Thresholds and protocol are unchanged. Only corpus construction was corrected.

## Lineage

| Version | `dev.jsonl` | `dev-gold.jsonl` | Gate result |
|---|---|---|---|
| Pre-fix (first gate run) | `bc76521949cb07190d49288e648e397f9f41c97cf8e56ba285f4aebf032c2265` | `072fac2d48188e7ed8efa73722b4444e85700e6b9835fffad01062c1bf525397` | L3 fail (1 label); oracle 0.953 |
| Current | `0cc11d95dc7aebc28da8e61a62b1a2ba125783a4f361753ac891dd134da7eb04` | `beba25e916f4a81f67090fbd16c873c3355b5c2ebfb3e1b29b0848657596c721` | pass |

The pre-fix hashes were not recorded when the file was first written. They come from a deterministic regeneration of the generator with exactly the two edits below reversed. The generator is `make_dev.py` (current SHA-256 `c4d9ba48…`).

## L3 scope skew

The rule fails when a preferred label with n ≥ 5 has `|share(scope == "school") − overall share| > 0.20`.

| | Overall school share | `study` label (n = 5) | Skew |
|---|---:|---:|---:|
| Pre-fix | 4/60 = 0.0667 | 2 school (dv2-033, dv2-034) | **+0.3333 (fail)** |
| Current | 3/60 = 0.05 | 1 school (dv2-033) | +0.15 (pass) |

Every other label with n ≥ 5 had skew −0.0667 before the fix and −0.05 after.

**Offending feature:** `helper.scope` on preferred label `study`.

**Smallest correction:** dv2-034 ("Quiz me on Bayes' rule.") changed from `scope: "school"` to `scope: "personal"`. That task is personal practice, not coursework, under CORPUS-SPEC section 1. Nothing else changed for L3.

## Oracle consistency (G2), fixed in the same edit

The product school policy makes Claude and Luna slots ineligible for school scope, and forbids an Anthropic vendor in school-related Conclave contracts. Before the fix, dv2-033, dv2-034, dv2-038 and dv2-039 routed to such slots, so the oracle reached 0.953.

- **dv2-033:** now uses two school-safe Codex/Gemini pairs.
- **dv2-034:** now personal scope.
- **dv2-038 and dv2-039:** now use a two-role Codex + Gemini seat.

Oracle is now 1.000.

## Current aggregate gate packet

From the gate run that produced the current hashes:

| Item | Value |
|---|---|
| Structure errors | 0 |
| L1–L4 | all 0 |
| Oracle | 1.000 |
| Shuffled-label oracle | 0.440 |
| Always-abstain | 0.417 |
| Best constant | 0.493 |
| All-families oracle | 0.405 (class-filtered 1.000) |

| Gate | Requirement | Result |
|---|---|---|
| G1 | best constant ≤ abstain + 0.10 | 0.493 ≤ 0.517, pass |
| G2 | oracle ≥ 0.95 | pass |
| G3 | oracle − best constant ≥ 0.25 | 0.507, pass |
| G4 | shuffled ≤ oracle − 0.20 | 0.440 ≤ 0.80, pass |
| G5 | structure and guard | pass |
| G6 | all-families drop ≥ 0.15 | 0.595, pass |

**Overall: pass.**
