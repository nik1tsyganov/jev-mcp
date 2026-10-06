# v2 batch — ready-to-run sequence (nothing below has been executed)

Preconditions already met:
- protocol r3 and code are frozen (`FROZEN-v2-protocol-r3.json`);
- the integrated callable is pinned;
- offline tests pass;
- the zero-retry proof exists (`~/.local/scratch/routing-qual-v2/zero-retry-proof.json`);
- the owner admission `f5538be0-2713-475b-b263-b084f99638f2` is recorded in the shared ledger.

**Blocking:** steps 1–3 need corpus authors and an adjudicator. Per the manager rule, they need a manager brief before any new agent session is created.

Throughout: `PY=~/.local/scratch/laya-evaluation/venv/bin/python`, working directory `experiments/routing-qual-v2`, `TYPESAFE_API_KEY` unset except for steps 7 and 10.

1. **Author dev-v2 (Author A).**
   - Write 60 cases to `cases/v2/dev.jsonl` and their gold to `cases/v2/dev-gold.jsonl`.
   - Use the native schema: `helper.savedPairs` as `HydraPair` records, bindings by `pairID`, and Conclave seats only from the frozen bundled seat catalog with `maxConcurrent` 3. `fixtures/make_synthetic.py` shows the shape.
   - Synthetic, non-private task text only.
   - Avoid M1 models (`claude-sonnet-5-5`, `gpt-5.6-sol`) and `ultra` efforts, except in exactly 6 planted fabricated members.
2. **Author held-out-v2 (Author B).**
   - Write 120 cases to `cases/v2/heldout.jsonl`.
   - Write the gold only to `~/.local/scratch/routing-qual-v2/sealed/heldout-gold.jsonl`, with 12 planted fabricated members.
   - Commit `cases/v2/heldout-gold.sha256` in two-line shasum form (`heldout.jsonl`, `heldout-gold.jsonl`).
3. **Adjudicate (third session).** Review a seeded 25% sample of each split (seed 20261002). Log changes before sealing.
4. **Corpus gates.** Both must print `"pass": true`. On failure, the author rewrites; the lead does not read held-out gold.

        $PY run_v2.py gate-check --cases cases/v2/dev.jsonl --gold cases/v2/dev-gold.jsonl --other ../routing-qual-2026-10-01/cases/dev.jsonl ../routing-qual-2026-10-01/cases/heldout.jsonl
        $PY run_v2.py gate-check --cases cases/v2/heldout.jsonl --gold ~/.local/scratch/routing-qual-v2/sealed/heldout-gold.jsonl --other cases/v2/dev.jsonl ../routing-qual-2026-10-01/cases/dev.jsonl ../routing-qual-2026-10-01/cases/heldout.jsonl

5. **Pre-attempt protocol freeze.** List every file in `FROZEN-v2-protocol-r3.json`, plus `cases/v2/*` and the zero-retry proof:

        $PY run_v2.py freeze --name FROZEN-v2-preattempt.json --commitment cases/v2/heldout-gold.sha256 <paths...>

6. **Ledger freeze row: once, by `laya-qualification`, after step 5.** `<P>` = `shasum -a 256 FROZEN-v2-preattempt.json`; `<Z>` = `shasum -a 256 ~/.local/scratch/routing-qual-v2/zero-retry-proof.json`.

        python3 ~/.local/scratch/jev-testing-campaign-2026-10/jev_campaign_ledger.py freeze --party laya-qualification \
          --admission f5538be0-2713-475b-b263-b084f99638f2 --json '{"model":"jev-1.13.0","retries":0,"arm":"base-480",
          "perAttemptTokenBound":65536,"maxAttempts":480,"usdPerInputToken":4.2e-08,"maxUSD":1.33,
          "protocolSHA256":"<P>","zeroRetryProof":{"sha256":"<Z>"}}'

7. **Jev dev batch: 120 attempts.** The admission gate is read in-process. The run stops at the first failure.

        $PY run_v2.py classify --cases cases/v2/dev.jsonl --backend jev --repeats 2 --out ~/.local/scratch/routing-qual-v2/runs/dev-jev \
          --paid --price ~/.local/scratch/routing-qual-20261001/runs/jev-price-1.13.0.json \
          --batch-dir ~/.local/scratch/routing-qual-v2/batch --max-attempts 480 --admission f5538be0-2713-475b-b263-b084f99638f2

8. **Dev offline arms.**
   - Run `laya` (local), `matrix`, `manual`, `keep-current` and each `constant:F:C` on dev, plus `oracle`, `anti` and `shuffled` with `--gold`.
   - Replay every run with `--rule owner-bands`.
   - Choose the analysis threshold with `run_v2.py tune` (analysis only) and the best constant on dev.
9. **Final freeze, before any held-out call.** Freeze everything from step 5, plus the dev analysis thresholds and the best-constant choice:

        $PY run_v2.py freeze --name FROZEN-v2.json --commitment cases/v2/heldout-gold.sha256 <paths...>

10. **Jev held-out batch: 360 attempts** (the remainder of 480).

        $PY run_v2.py classify --cases cases/v2/heldout.jsonl --backend jev --repeats 3 --freeze FROZEN-v2.json --out ~/.local/scratch/routing-qual-v2/runs/heldout-jev \
          --paid --price ~/.local/scratch/routing-qual-20261001/runs/jev-price-1.13.0.json \
          --batch-dir ~/.local/scratch/routing-qual-v2/batch --max-attempts 480 --admission f5538be0-2713-475b-b263-b084f99638f2

11. **Close the admission.**

        python3 .../jev_campaign_ledger.py close-admission --party laya-qualification --admission f5538be0-... --reason "batch complete"

    Run the held-out local and offline arms, replay with `--rule owner-bands`, then score with `--commitment` and `--freeze FROZEN-v2.json`. No second batch runs before the owner reconciles this one.
12. **Report.** Report per-backend and per-mode gate status. Only a section-7 pass may produce an export record, and the owner applies it, never this experiment.

**Cleanup.** The test-only defaults domain can be removed by the owner with `defaults delete iordv.droppycode.routing-qual-v2-tests`. The harness never deletes it.
