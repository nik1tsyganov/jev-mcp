# jev-mcp

This repository provides two MCP stdio servers. `jev` exposes TypeSafe Jev System One. `laya` runs Laya-MLX locally and offline. TypeSafe publishes no official MCP server as of 2026-09-25, so this repository remains the Jev MCP server.

Jev takes a *state* and a map of *questions*. It returns typed judgments: probabilities, labelled choices, or scores. Batch questions about the same state in one request.

## Tools

| Server | Tool | Use |
| --- | --- | --- |
| `jev` | `jev_ask` | Ask one or more typed questions through TypeSafe Jev. |
| `jev` | `jev_noul` | Ask one yes/no question. |
| `jev` | `jev_choice` | Choose among named options. |
| `jev` | `jev_score` | Score on an ordered scale. |
| `jev` | `jev_models` | List available Jev models without a judgment request. |
| `jev` | `decision_browser_action` | Get advisory browser action advice from Jev; the caller executes and verifies the action. |
| `laya` | `laya_ask` | Ask local questions with `state`, `questions`, and optional `profile`. |
| `laya` | `laya_bookmark_topic` | Tag a bookmark from `state` and optional `profile`; omitted profile uses v2. |
| `laya` | `laya_status` | Read local runtime and profile status. |

`decision_browser_action` remains Jev-only. It neither launches a browser nor executes an action. See [browser action decisions](docs/browser-decisions.md).

## Provider choice

The caller chooses `jev` or `laya` for each request. The servers never call each other. There is no automatic routing, fallback, or shadow run. A Laya result below its profile threshold returns `accepted: false` and `reason: "below_threshold"`. The caller can then choose to ask Jev in a separate request.

Both registered bookmark profiles are enabled by explicit owner override after qualification **FAILED**. The override does not change their failed evidence or thresholds:

- `technical-bookmark-topic-v1`: threshold `0.5`; select it explicitly.
- `technical-bookmark-topic-v2`: threshold `0.4`; default for `laya_bookmark_topic`.

The frozen 400-case synthetic v2 confirmation measured Jev at 94.5%, Laya at 74.75%, and the former combination at 92.0%. Accepted local answers scored 88.53% against a 95% target. These are historical measurements, not a current quality claim. See the [confirmation record](docs/technical-bookmark-topic-v2-confirmation.md).

| Old tool | New call |
| --- | --- |
| `decision_ask` | `jev.jev_ask` or `laya.laya_ask`; the caller selects the provider. |
| `decision_bookmark_topic` | `laya.laya_bookmark_topic`. |
| `decision_status` | `laya.laya_status`. |
| `decision_browser_action` | Unchanged on `jev`. |

For bookmark tagging, call `laya_bookmark_topic` with `{ "state": { "title": "…", "description": "…" } }`. The tool supplies the frozen question. To select v1, add `"profile": "technical-bookmark-topic-v1"`.

## Environment and telemetry

Jev needs a TypeSafe key. It reads `TYPESAFE_API_KEY` from its environment or the single export line in `~/.config/typesafe/env.sh`. The key is never printed by the server. Laya uses `LAYA_PYTHON`, `LAYA_MODEL_DIR`, `LAYA_CHECKPOINT`, `LAYA_MODEL_REVISION`, `LAYA_TIMEOUT_MS`, and `LAYA_MAX_QUEUE`. Its worker uses cached model files and stays offline. The trusted profile registry also holds pinned worker settings and evidence.

Jev spend goes to `~/.claude/docs/telemetry/jev-spend.jsonl` (`TYPESAFE_SPEND_LOG` overrides the path). Laya decisions go to `~/.claude/docs/telemetry/laya-decisions.jsonl` (`LAYA_DECISION_LOG` overrides the path). A Laya request does not create Jev spend.

## Install and register

Node >= 20 is required. Run `npm install` once; there is no build step. `scripts/install-typesafe-jev.sh` registers both servers for Claude, Codex, Cursor, and Antigravity. It removes old combined routing environment keys from `jev` on repeat runs. Jev starts from `src/server.js`; Laya starts from `src/laya-server.js`.

For a portable Droppy Code runtime, run `python3 scripts/install-decision-runtime.py --download-laya`. It packages both servers. Use `node launch.mjs jev` or `node launch.mjs laya` in that runtime; omitting the argument selects Jev. A Laya launch requires the installed `runtime.json` Laya settings. A fresh install has an empty profile registry and does not inherit this machine's owner overrides. The earlier combined managed-entry design is retained as a [historical record](docs/droppy-local-fallback.md).

`MAX_QUESTIONS_PER_CALL` (32) and `MAX_STATE_CHARS` (200000) bound Jev calls. The shared question validator checks choice options, ordered score levels, and noul shape before inference.
