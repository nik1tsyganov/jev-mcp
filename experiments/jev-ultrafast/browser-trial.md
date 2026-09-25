# Jev Ultrafast browser trial (experiment)

Isolated trial of upstream `browser-use/jev-ultrafast` @ `1231850a0bf1a0c0341fe408ef1668dbbfdfac46`
against three loopback HTML fixtures. Experiment only — nothing here is wired
into production code.

**Result label: `fixed-text-helper`.** TYPE_TEXT uses an exact string from the
task definition instead of upstream's small-LLM helper, so results are not a
full upstream reproduction.

## Files

- `browser_trial.py` — runner (stdlib only; prefers `websockets.sync.client` for
  CDP if installed, falls back to a minimal built-in WebSocket client).
- `fixtures/pick-item.html` — select "Kestrel" among 4 distractors plus a
  `disabled` button, an `aria-disabled` button, and a covered button.
- `fixtures/fill-text.html` — fill exact access code `delta-5930-quill` and
  save; readonly field, disabled and covered decoys.
- `fixtures/select-submit.html` — select shipping speed "Courier" (disabled
  option + disabled optgroup as decoys) and submit; distractor text field,
  disabled and covered decoys.

Every fixture owns `window.__trial`: `{complete, errors[], log[], ...}` set
purely by DOM events — completion never depends on the agent's DONE/BLOCKED,
and incorrect actions (wrong item, bad value, premature submit, covered/disabled
interactions) are recorded. Verdicts: `pass` / `fail` / `invalid` (`__trial`
missing means the instrument never populated — not a real result).

## Executor probes

- **Disabled / aria-disabled controls** — absent from the observed action space;
  if ever targeted, the executor's own guard refuses.
- **Covered control** — stays visible to `checkVisibility`, so it enters the
  action space as bait; the act-time `elementFromPoint` hit-test refuses it
  (`StalePage`), recorded under `stale_events` / `fixture_errors`.
- **Stale-node replacement** (pick-item) — after the first node-targeting
  decision the runner clone-replaces the chosen DOM node between predict and
  act, fully deterministically. Expected: `stale_probe.outcome = refused_stale`.
  `acted_on_stale_node` means the upstream guard failed.

## Bounds (hard)

3 tasks × 3 repetitions, ≤ 8 decisions per run, ≤ 72 Jev requests total, no
retries anywhere (the injected decider must not retry; upstream's internal
retry loop is removed because the whole `post_json` seam is replaced).
`--reps` / `--max-decisions` accept only smaller values.

## Setup

1. Upstream checkout at the pin:

   ```sh
   git clone https://github.com/browser-use/jev-ultrafast /tmp/jev-ultrafast
   git -C /tmp/jev-ultrafast checkout 1231850a0bf1a0c0341fe408ef1668dbbfdfac46
   ```

2. An **explicitly isolated** Chrome (fresh profile, never your daily browser,
   never the browser-harness daemon endpoint):

   ```sh
   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
     --remote-debugging-port=9333 \
     --user-data-dir="$(mktemp -d)" \
     --no-first-run --no-default-browser-check about:blank
   ```

   The runner refuses non-loopback endpoints, non-Chrome products, and any
   endpoint that already serves page targets outside about:blank/new-tab (i.e.
   a used profile). It closes only the tabs it created; the Chrome process
   belongs to the caller.

3. A decider: `--decider module:callable`, `callable(body) -> dict` returning
   the raw `POST /v1/systemone` response JSON (`{answers, model, usage}` —
   same shape as `jev-mcp`'s `systemOne` in `src/client.js`). Exactly one
   request per call. The runner never resolves or writes secrets and never
   calls a provider itself.

## Run

```sh
# Dry run — prints caps and requirements, no API/browser calls:
python3 experiments/jev-ultrafast/browser_trial.py [--source /tmp/jev-ultrafast]

# Live:
python3 experiments/jev-ultrafast/browser_trial.py --live \
  --source /tmp/jev-ultrafast \
  --cdp-url http://127.0.0.1:9333 \
  --decider jev_bridge:decide \
  --out "$HOME/.local/scratch/jev-ultrafast-evaluation/browser"
```

Outputs in `--out`: `results.json` (run records: verdict, stop_reason,
agent_status, request counts, resolved model, decision + action traces,
fixture errors, stale-probe outcome, source pin, isolation evidence) and
`decisions.jsonl` (one line per real decision: id, run_id, task_id, rep,
endpoint, exact `state`/`questions`/`request` objects including original
instructions, `response`, `model`, `latency_ms` — for the companion replay
runner).

## Transport adaptations (all documented seams)

| Seam | Patch | Why |
|---|---|---|
| `jev_ultrafast.browser.ensure_daemon` | no-op (isolation verified once at connect) | upstream spawns/uses the browser-harness daemon attached to the user's Chrome |
| `jev_ultrafast.browser.cdp` | direct CDP websocket to `--cdp-url` | same `(method, session_id, **params)` contract; browser-level + flattened-session commands |
| `jev_ultrafast.model.post_json` | injected `--decider` + counter + JSONL capture | one request per decision, no retries, full payload capture |
| `jev_ultrafast.agent.field_text` | returns the task's fixed string | deterministic text; labelled `fixed-text-helper` |

Missing imports (`httpx`, `browser_harness`) are stubbed in `sys.modules` only
when absent — they are dead code under the patches above. If the packages are
installed, the real modules are used and still patched at the same seams.

## Limitations / prerequisites

- Python ≥ 3.9 for the runner; upstream declares ≥ 3.12 though the pinned
  `agent.py`/`browser.py`/`model.py`/`questions.py`/`snapshot.js` use no
  post-3.9 syntax. Verify under the lead's interpreter.
- No packages are installed by this experiment; `websockets` is used only if
  already present.
- Fixtures are self-contained: no external resources, accounts, purchases, or
  real user data. Task URLs are pinned to the fixture origin; a run aborts
  (`off_origin`) if the page ever navigates away.
- Covered/decoy elements bait the agent but are never required for `pass`;
  completion requires `__trial.complete` and the expected fields; a clean pass also requires zero incorrect actions or runner errors.
- The stale-node probe consumes one decision inside the 8-decision cap.
- Upstream `choose()` reads `TYPESAFE_API_KEY` before the HTTP seam runs; the
  runner sets a placeholder (`unused-injected-decider`) only when the var is
  unset. It is never sent anywhere — the patched `post_json` ignores it and the
  decider owns credentials. An already-set var is left untouched.
- Chrome must be launched by the caller with a fresh `--user-data-dir`;
  the runner verifies but cannot itself prove the profile is disposable.

## Lead integration corrections

`jev_bridge.py` uses one persistent Node client, preserves spend logging, and disables SDK retries through an experiment-only adapter. It serializes object instructions to canonical JSON strings because our client requires strings. Thus the browser trial also uses adapted instructions, not the exact upstream wire payload. Captures retain original instructions for replay. Failed provider calls are captured before errors propagate. Non-git source archives require a `trial-source.json` manifest with the pinned revision and SHA256 file hashes.
