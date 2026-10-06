# Superseded held-out staging (2026-10-03)

- `v5-superseded-d3cc88fd/`: schema-corrected hv5 before rephrasing (`d3cc88fd…`). It fails leakage gate L2 (49 internal near-duplicate pairs). Its Oracle-side review (Milo, `sealed/ADJUDICATION-LOG-heldout-v5.json`, `heldout-gold.v5.adjudicated.jsonl`) binds this older input and is not used.
- `v5r-superseded-kai/` (if present): a duplicate rephrasing started before the routing handoff arrived. Not reviewed and not used.
- Accepted for v8: `v5/heldout.jsonl` = routing-lead rephrased corpus `c0cc0cf0…`, gold `sealed/heldout-gold.v5.jsonl` (`064056b0…`), independent review `sealed/adjudication-v5/ADJUDICATION-LOG-heldout-v5.json` (30/30 accepted). See `~/.local/scratch/routing-continuation-2026-10-03/HANDOFF-MANIFEST.md`.
