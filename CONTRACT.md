# Jev Client Contract

Shared specification for TypeSafe Jev clients in this environment: `~/src/jev-mcp/src/client.js` (official `@typesafe-ai/sdk`) and `~/src/conclave/tools/jev-client.js` (zero-dependency global `fetch`). Neither repository may import the other.

## MUST AGREE

Facts where a difference is a defect. Stated as testable assertions with current values:

1. **API Endpoint**: The endpoint resolves to `https://api.typesafe.ai/v1/systemone`.
2. **Default Model Alias**: The default model alias is `jev-latest`.
3. **Calibrated Model Pin**: The resolved model version that calibrated gates are pinned to is `jev-1.13.0`, which is what the API returns when asked for the alias.
4. **Credential Redaction**: Every error path passes its message through a redaction step that removes the API key and any `Bearer <token>` before the message can reach a log, a receipt, or a tool result.
5. **Question Validation**:
   - The three question types are `noul`, `choice`, and `score`.
   - `choice` criteria is a non-empty object mapping each option name to a description or null.
   - `score` criteria is an ordered array of at least two levels.
   - A question id may never be `__proto__`, `constructor`, or `prototype`.

## MAY DIFFER

Declared differences between clients, so checkers do not flag intended design decisions:

1. **Transport**:
   - `jev-mcp`: Official `@typesafe-ai/sdk` (`TypeSafeClient`).
   - `conclave`: Hand-rolled `fetch` client (`globalThis.fetch`).
   - *Why*: `conclave` ships as an npm package with zero runtime dependencies.
2. **Retry Status Codes**:
   - `jev-mcp`: SDK retries HTTP 408, 429, and all 5xx (500–599) server errors.
   - `conclave`: Retries only 429 and 529.
   - *Why*: Conclave implements minimal backoff specifically for rate limits and server overload without importing full SDK retry policies.
3. **Request Timeout**:
   - `jev-mcp`: Sets 30000 ms explicitly.
   - `conclave`: Sets none.
   - *Why*: SDK client configures an explicit timeout; Conclave relies on external caller/session deadlines.
4. **Key Resolution**:
   - `jev-mcp`: Reads `process.env.TYPESAFE_API_KEY` with fallback to reading `~/.config/typesafe/env.sh`.
   - `conclave`: Requires `process.env.TYPESAFE_API_KEY` directly, expecting the lead to source `~/.config/typesafe/env.sh` first.
   - *Why*: Conclave minimizes filesystem coupling and environment assumptions.
5. **Spend / Provenance Log**:
   - `jev-mcp`: Logs to `~/.claude/docs/telemetry/jev-spend.jsonl` tracking input/output tokens, request count, and answer summaries.
   - `conclave`: Logs to a caller-specified `provenancePath` (JSONL) with request/response SHA256 hashes and usage.
   - *Why*: Host environments require distinct telemetry structures and provenance trails.

## HOW THIS IS ENFORCED

Neither repository imports the other. Enforcement is three layers, and the third
exists because the first two cannot catch the interesting failure.

1. **`jev-mcp` checks itself** — `tools/jev_contract_check.py`, offline, wired
   advisorily into `hooks/pre-push`. Carries `--selftest`, which injects a deliberate
   mismatch and confirms the checker reports FAIL.
2. **`conclave` checks itself** — `tools/jev-contract.test.js`, self-contained, in its
   own suite. It drives `systemOne` with an injected `fetchImpl` that throws a fake key,
   so it proves redaction is APPLIED rather than merely defined.
3. **The two are compared against each other** — `check_peer_agreement` in
   `tools/jev_contract_check.py` reads `~/src/conclave/tools/jev-client.js` as TEXT and
   compares `ENDPOINT`, `DEFAULT_MODEL` and `PINNED_MODEL` to the values above. It never
   imports, so the dependency-free rule holds. If conclave is not on the machine the
   check reports SKIP, because absence is not disagreement.

Layer 3 is the point. Layers 1 and 2 each compare a repository to its OWN copy of these
values, so both can pass while disagreeing with each other: bump the pinned model here
and in the packs, and `conclave` keeps asserting the old version and stays green. Only a
check that reads both sides sees that. Verified 2026-09-19 by pointing the peer check at
a fixture pinned to `jev-1.14.0`; it reported
`PINNED_MODEL: peer='jev-1.14.0' contract='jev-1.13.0'`.

A declared difference moving within its scope is not a defect. An undeclared difference
is a defect. Moving a MUST AGREE value means editing this file and both sides in the
same pass — layer 3 is what makes forgetting the second one loud.
