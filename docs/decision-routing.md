# Local profile policy

Historical integration results below describe the pre-split combined router (before 2026-09-25).

`src/provider-policy.js` now belongs to the local `laya` server. It checks trusted profile registry data, pinned runtime identity, question shape, calibrated-pack overlap, and evidence. It does not select Jev. The two MCP servers never call each other.

## Provider choice

Call `laya_ask` for local offline inference, with `state`, `questions`, and optional `profile`. Call `laya_bookmark_topic` for the frozen bookmark question; its omitted profile defaults to v2. Call `jev_ask` separately when Jev is wanted. There is no automatic routing, fallback, or shadow request. A Laya answer below its profile threshold returns `accepted: false` and `reason: "below_threshold"`; the caller decides whether to ask Jev.

## Profile adoption

`config/decision-profiles.json` is trusted local configuration. A caller cannot pass an inline approval, evidence file, or runtime pin. A profile must be enabled, match its question fingerprint and runtime identity, satisfy its input limits, avoid calibrated-pack overlap, and have valid pinned evidence.

Both registered bookmark profiles are enabled by explicit owner override after qualification **FAILED**. Their diagnostics remain FAILED, and the override does not claim a passing evaluation. `technical-bookmark-topic-v1` uses threshold `0.5` and requires an explicit profile id. `technical-bookmark-topic-v2` uses threshold `0.4` and is the bookmark default. A fresh portable runtime starts with an empty registry, so it does not inherit this machine's overrides.

Each profile stores its own worker settings under `runtime`. The worker loads cached model files lazily and stays offline. The `laya` server also reads `LAYA_PYTHON`, `LAYA_MODEL_DIR`, `LAYA_CHECKPOINT`, `LAYA_MODEL_REVISION`, `LAYA_TIMEOUT_MS`, and `LAYA_MAX_QUEUE`. The worker and registry must agree on pinned identities.

## Evidence limits

The failed qualification is an accuracy warning. The owner accepted that tradeoff for these two bookmark tasks only. A probability threshold controls acceptance of an answer; it does not prove general accuracy. The historical confirmation and integration records below are measurements of the former combined router, not evidence of the split servers.

## Integration validation (2026-09-21)

The lead ran 88 Node tests and 35 Python tests in the checkout. All passed after
correcting worker startup syntax, fallback state, environment names, registry
trust, result validation, process lifecycle, and shadow disagreement metrics.

One live MCP request used a public synthetic damaged-package example with three
questions. Jev 1.13.0 returned the authoritative answer; the pinned English MLX
worker completed the background comparison. The same MCP session refused an
offline-only request without calling Jev. Local checks also refused an oversized
state and a non-Latin state. The server exposed all five legacy tools and both
new tools. No profile was approved by these smoke checks.

The local worker was configured explicitly for these checks. Existing MCP host
environments were not changed. Set `LAYA_*` in the server environment and restart
the host connection to enable local comparisons. At that time production quality
remained unproven for every Laya profile and the shipped registry was still empty.


## Host activation and first profile (2026-09-21)

The existing four host registrations now carry `LAYA_*` settings and a 10% shadow
sample rate. New MCP connections passed; existing host sessions were not terminated.
The existing Claude registration is project-scoped.

`technical-bookmark-topic-v1` was calibrated on 80 development cases at probability
0.50, then evaluated once on 240 independent, author-labeled synthetic cases. It accepted
131 cases, with 127 correct; its cascade accuracy was 96.25%, versus Jev's 96.67%.
The overall confidence interval and several per-group gates failed. The registry entry
was therefore left disabled. See [the diagnostic](evidence/technical-bookmark-topic-v1.json).

A typed-decisions alternative, `technical-bookmark-topic-v2`, passed development
calibration at 0.40 (62/63 accepted cases correct). Its definition and calibration are
frozen for a new, independently authored confirmation corpus. It was not enabled at that
point, and the first holdout will not be reused to approve it.

## Owner-override adoption (2026-09-21)

After reviewing the failed qualification, the user chose the combination and directed
that both registered profiles be configured. Both are therefore enabled by trusted owner
override, not by passing evaluation:

- `technical-bookmark-topic-v1` — English `aac6fef/laya-mlx` at its existing pin,
  threshold `0.5`, selectable only when named explicitly.
- `technical-bookmark-topic-v2` — `aac6fef/laya-typed-decisions-mlx` at its existing
  pin, threshold `0.4`, named by `defaultProfile` so it answers an omitted `profile` id
  on an exact question-hash match only.

This is adoption, not a new result. The measured 400-case v2 confirmation stands
unchanged: Jev 94.5%, Laya 74.75%, combination 92.0%, accepted-local 88.53% against a
95% target; `qualificationStatus` stays `FAILED` and the evidence is unmodified. The user
accepted that accuracy tradeoff. Ordinary unmatched questions still use Jev.

Each profile carries its own `runtime` settings and its worker loads lazily from the
pinned cached model. The four existing MCP registrations still point at this server;
application sessions need an MCP reconnect to load the new code. The Claude registration
remains project-scoped. Lead validation is recorded below.


## Combination integration validation (2026-09-21)

All 131 Node tests passed after lead integration. Fresh MCP connections using the
saved Cursor, Codex, Antigravity and project-scoped Claude registrations returned
local answers from both pinned profiles. The Cursor connection also exercised
omitted-profile V2 selection, low-probability refusal with remote access disabled,
and exactly one Jev fallback for each profile (two Jev requests total). Changed
questions and unknown profiles refused offline. These are runtime checks, not new
quality measurements; both qualification results remain FAILED.

The lead corrected registry refresh order, closed obsolete cached workers, prevented
environment-worker substitution after a profile runtime failure, and corrected MCP
tool descriptions and documentation. The raw host report is
`~/.local/scratch/laya-activation/combination-integration.json`.
Existing application sessions were not restarted; reconnect MCP to load this code.
