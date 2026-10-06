# Incident: pinned helper rebuilt during the held-out batch (2026-10-02)

## Facts

- **Final freeze.** `FROZEN-v2.json` (SHA-256 `4a65597e…`) was written at 02:47:13Z. It pins the integrated Oracle CLI Debug build at merge `329ecdea6b1f…`:

  | File | Pinned SHA-256 prefix |
  |---|---|
  | `Droppy Code Dev.debug.dylib` | `34e587d8297349c4` |
  | `Droppy Code Dev` | `f439c8f492a35677` |
  | `droppy_cli.py` | `f92d09b1008ff5e8` |

- **Paid held-out batch.** It ran 02:47:22Z–02:48:25Z under admission `f5538be0`: 360 of 360 attempts settled, all returning `jev-1.13.0`. The paid dev batch (02:43:38Z–02:44:00Z, 120 attempts) ran entirely on the pinned build.
- **The rebuild.** At 02:47:29Z the Debug executable and `.debug.dylib` were rebuilt in `~/.local/scratch/droppy-oracle-cli-integration`. The new dylib is `fc8d0e9c2852db42`; the executable stub is unchanged at `f439c8f4…`. That checkout has one uncommitted change, to `DroppyCode/Core/Models/OracleRoutingAuthority.swift`: the authority now resolves a bracketed model id such as `opus[1m]` to its base catalog row. It was not reported to this project before the batch.
- **Effect on this project.** `run_v2.py verify --name FROZEN-v2.json` now fails. Held-out replays and local held-out arms refuse to run, as designed.

## Evidence of equivalence (offline; no gold read, no classifier call)

- **Classifier requests are byte-identical.** All 60 dev and all 120 held-out requests prepared with the current build match the SHA-256 recorded during the paid runs. The 480 paid answers are answers to exactly the frozen requests.
- **The authority change cannot fire on these corpora.** It differs only when a model id contains `[`. There are 0 bracketed ids among 930 model slots (dev 326, held-out 604).

## Status

- Held-out scoring has **not** been run; no held-out result has been seen.
- No retries were made and no extra calls. Batch ledger: 480 reserves and 480 settles, US$0.016459884, admission closed at the cap.
- The Oracle integration was not edited.

## Decision needed (before any held-out score)

Preregistration section 9 says any change after `FROZEN-v2.json` invalidates held-out-v2 for qualification. The options:

- **A.** Approve a pre-scoring amendment `FROZEN-v2-r4.json` that pins the current build `fc8d0e9c`, citing the evidence above. Held-out results would then be scored and labelled "amended freeze, rebuild shown equivalent for these corpora".
- **B.** The Oracle lead restores a build whose `.debug.dylib` hashes to `34e587d8297349c4`. Debug builds may not be byte-reproducible.
- **C.** Treat held-out-v2 as non-qualifying evidence and report scored results without a qualification status.

## Root decision (2026-10-02)

The base-480 run is **NONQUALIFYING** because of the freeze breach. The freeze is not amended. Held-out stays unscored. All 480 settled records, requests and replies are preserved.

## Evidence packet (read-only checks)

### Helper hashes

| File | Pinned (FROZEN-v2.json) | Current |
|---|---|---|
| `Droppy Code Dev.debug.dylib` | `34e587d8297349c445cd42f5a8fc65f6698a787b3a971ae74c837caa5a40fce3` | `fc8d0e9c2852db42f5657bb65a33b2711e0b39ef4b25989b83bcca72ff2b6e73` (65,799,352 bytes, modified 2026-10-02T02:47:29Z) |
| `Droppy Code Dev` (stub) | `f439c8f492a35677ee4a9a02ec08371f5bac5dccb7e278d654f9f7c2887b9173` | unchanged |
| `droppy_cli.py` | `f92d09b1008ff5e8d2f00d4e3c33beb59e7dd0f25026b58c8fd8c77d6e104bab` | unchanged |

### Source and build change

- The integration checkout is still at HEAD `329ecdea6b1fd17e4cd1ce391c0967a425cb45a4`. One file is modified and uncommitted: `DroppyCode/Core/Models/OracleRoutingAuthority.swift`.
  - At HEAD it hashes `0c0ff2650155c582…`; in the working tree, `8988130f8f874cef…`.
- The change adds `bracketBase(_:)`, so `slotReasons` falls back to the catalog row of the id before a `[` suffix (`opus[1m]` → `opus`).
- A rebuild at 02:47:29Z rewrote the `.debug.dylib` and `DroppyCode.swiftmodule`.

### Which stage used which build

| Stage | Time (UTC) | Build |
|---|---|---|
| Dev and held-out gate checks, dev free arms and replays, dev scoring, dev paid batch (02:43:38–02:44:00Z), both freezes (02:43:17Z and 02:47:13Z) | before 02:47:29Z | pinned `34e587d8` |
| Held-out paid batch | 02:47:22–02:48:25Z | Requests were prepared case by case, so early cases used `34e587d8` and later cases used `fc8d0e9c`. The per-case boundary is not logged. All 120 prepared requests are byte-identical to those the current build produces, and Jev answered exactly those bytes. |
| Held-out replay of the stored Jev answers (`heldout-jev/routes-owner-bands.jsonl`, created 02:49:18Z, 360 rows, SHA-256 `148a12fa…`) | 02:49:18Z | **new build `fc8d0e9c`** |
| Held-out free arms (matrix, manual, keep-current, constant, Laya) | after 02:47:29Z | Refused by the freeze verification. Nothing was produced. |

The held-out replay was not blocked because `run.replay` compares only the executable stub's hash, and the stub didn't change. That is a harness gap: the replay check does not cover the `.debug.dylib`.

### Immutable original

**No copy matching `34e587d8…` exists.** I searched read-only across `~/.local/scratch`, Xcode DerivedData, `~/Applications` and `/Applications`. It found 11 `Droppy Code Dev.debug.dylib` files with other hashes; the only integration-build copy is `fc8d0e9c`. The pinned original was overwritten in place.

### Held-out scoring status (complete account)

- No backend's held-out routes were scored against gold.
- No held-out backend metrics were computed or viewed.
- The `heldout-jev` routes file exists but was never opened or scored.
- Before the paid batch, held-out gold entered only aggregate corpus-instrument checks:
  - gate checks of r1 and r2 (oracle, shuffled and constant controls through the helper);
  - aggregate diagnostics: counts by mode, outcome shape and helper reason code, plus a condition count;
  - adjudication-log header counts.

  These are corpus checks, not backend scoring.

### Denied dev safety-violation inspection (not retried)

The command attempted, verbatim:

    python3 - <<'EOF'
    import json
    r=json.load(open('~/.local/scratch/routing-qual-v2/runs/dev-score-owner-bands.json'))
    for k in ('jev','laya','anti','shuffled'):
        for v in r['backends'][k]['violations']:
            print(k, v['case_id'], v['repeat'], v['outcome'], v['selected'], v['label'], v['violations'])
    EOF
    python3 - <<'EOF'
    import json
    g={json.loads(l)['id']:json.loads(l) for l in open('~/src/jev-mcp/experiments/routing-qual-v2/cases/v2/dev-gold.jsonl')}
    for cid in ('dv2-003','dv2-001','dv2-045','dv2-008'):
        x=g.get(cid); print(cid, x['preferred_label'], 'unsafe', x['security_unsafe_ids'], 'inject', x['injection_target_ids'])
    EOF

The stated denial is from the Claude Code auto-mode classifier: "Permission for this action was denied by the Claude Code auto mode classifier. Reason: [Real-World Transactions]." It was not retried, and no alternate route was used.

### Future held-out-only admission (calculated, not opened)

- 120 cases × 3 repeats = **360 attempts**.
- At 65,536 tokens × US$0.042/M per attempt: 360 × 0.002752512 = US$0.99090432, which is **US$1.00 rounded up**.
- Zero retries.

Prerequisites (root has not authorized this campaign):
- an immutable versioned copy of the final stable helper;
- a new freeze that pins it;
- a replay check extended to the `.debug.dylib`.
