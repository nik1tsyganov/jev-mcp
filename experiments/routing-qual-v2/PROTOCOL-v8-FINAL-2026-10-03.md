# Protocol v8, final (2026-10-03, before any v8 paid attempt)

Finalizes the routing lead's draft `PROTOCOL-v8-2026-10-03.md` after the handoff (`~/.local/scratch/routing-continuation-2026-10-03/HANDOFF-MANIFEST.md`, SHA-256 `e5e5e0ba…`). Where they differ, this file governs.

- **Helper.** Unchanged immutable v7 package `oracle-bundles/debug-signed-c2168378d3512c03`.
- **Held-out.** `cases/v5/heldout.jsonl` (`c0cc0cf0…`, rephrased hv5) with sealed gold `heldout-gold.v5.jsonl` (`064056b0…`), committed in `cases/v5/heldout-gold.sha256`. Pre-seal independent review: `sealed/adjudication-v5/ADJUDICATION-LOG-heldout-v5.json` (native Claude Opus session, seed 20261002, 30/120 sampled, 0 changed, no backend outputs). Gates G1–G8 and leakage L1–L4 pass. Superseded staging is listed in `cases/SUPERSEDED-2026-10-03.md`.
- **Development.** No paid dev arm. Reused, pinned: v7 dev runs, dev score and best constant `constant:study:long-context-analysis` from `runs-v7/`, and `dev-adjudication/ADJUDICATION-LOG-dev.json` (15/60, 0 changed), all with unchanged dev case and gold hashes.
- **Batch.** One held-out-only Jev arm: 120 cases x 3, at most 360 attempts, US$1.00, zero retries; free arms matrix, manual, keep-current, constant and Laya on the same inputs; owner bands 0.8; historical gates and owner overlay.
- **Authority.** Owner approval carried in the handoff: one fresh held-out-only 360-attempt, US$1 run, zero retries; plus the owner's 2026-10-03 Oracle-chat statement that testing spend may exceed US$50 if needed.
- **Qualification boundary.** Passing requires the scorer gates, the owner overlay and this protocol's corpus, provenance and review conditions. It does not activate routing.
