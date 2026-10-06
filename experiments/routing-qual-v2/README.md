# Routing qualification v2 — native Oracle helper harness

Offline infrastructure for the preregistered v2 experiment (`../routing-qual-2026-10-01/docs/PREREG-V2.md`, revision 3). The shipping target is the Oracle helper's own classifier request, through the product callable `droppy route` of the integrated Oracle CLI (merge 329ecdea, Debug, test-only authority hooks), under capability `oracle-classification-policy-v1` at the owner threshold 0.8. The batch sequence is in `READY-TO-RUN.md`.

v1 (`../routing-qual-2026-10-01`) is preserved. v2 imports two of its modules unchanged: `catalog_guard.py` and `adapters/local_sandbox.py`.

## State

- Code and protocol are frozen in `FROZEN-v2-protocol-r3.json`. `FROZEN-v2-protocol.json` (r2) is kept as history and no longer verifies.
- Copies of the canonical catalogs and product authority inputs are kept outside the repo in `~/.local/scratch/routing-qual-v2/frozen-inputs-r3/` (manifest `CATALOGS.json`), because they carry an account-derived identifier and host routing notes. The freeze pins them by hash.
- Fixtures under `fixtures/synthetic/` are **synthetic**. They exist only for harness tests and are not dev-v2 or held-out-v2 evidence.
- dev-v2 and held-out-v2 corpora have not been authored.
- No paid call has been made by v2.

## Run (Python 3.12: `PY=~/.local/scratch/laya-evaluation/venv/bin/python`)

    $PY -m unittest tests.test_v2                      # offline; fake server and temporary ledger only
    $PY run_v2.py verify --name FROZEN-v2-protocol.json
    $PY run_v2.py drift                                # frozen-vs-live catalog differences
    $PY run_v2.py unsupported-rows                     # canonical rows the frozen catalogs do not support
    $PY run_v2.py gate-check --cases C --gold G --other ../routing-qual-2026-10-01/cases/dev.jsonl
    $PY run_v2.py classify --cases C --backend matrix --repeats 2 --out DIR
    $PY run_v2.py classify --cases C --backend laya --repeats 2 --out DIR          # local, sandboxed
    $PY run_v2.py replay --run DIR --rule owner-bands
    $PY run_v2.py replay --run DIR --rule dev-tuned --threshold T                  # analysis only
    $PY run_v2.py score --runs DIR... --comparators matrix=D keep-current=D manual=D --constant D \
        --cases C --gold G --rule owner-bands --out FILE

Paid Jev runs need `--paid --price FILE --batch-dir D --max-attempts 480 --admission ID`. Every attempt reserves the documented 64k-token ceiling under the owner's single-batch admission, with zero retries. Both the ledger and a local counter refuse a reused key and any attempt past the cap. Held-out runs need `--freeze FROZEN-v2.json` and never accept gold. Held-out scoring needs `--commitment` and `--freeze`.

Backends: `jev`, `laya`, the controls `oracle`/`anti`/`shuffled`/`random`/`constant:F:C`/`malformed:V`, and the baselines `matrix`/`manual`/`keep-current`. Decider has no helper identity and is not available here.
