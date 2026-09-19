# jev-mcp

An MCP stdio server that exposes [TypeSafe](https://docs.typesafe.ai)'s System One
decision model (Jev) as tools. Jev does not write text: it takes a *state* and a map
of *questions* and returns typed judgments — a probability, a labelled choice with
per-option probabilities, or a score on an ordered scale. Code can threshold those
numbers, which a prose answer never allows.

## Tools

| Tool | Returns | Use it for |
| --- | --- | --- |
| `jev_ask` | every answer, plus `usage` | the batched primitive: many questions about one state in one request |
| `jev_noul` | a probability 0..1 | one yes/no judgment a threshold will act on |
| `jev_choice` | chosen option, per-option probabilities, confidence | routing, classification, triage |
| `jev_score` | probability-weighted score, legend, per-level probabilities, confidence | quality, severity, risk grading |
| `jev_models` | the account's model list | checking what is available; costs no judgment tokens |

Prefer `jev_ask`. One request answering six questions costs roughly one request; six
single-question calls cost six.

Every successful result carries the resolved `model`, the `answers` and the `usage`
token counts, so a caller can report spend instead of guessing it.

## Register it

`scripts/install-typesafe-jev.sh` does all four vendors at once. By hand:

    claude mcp add-json jev '{"command":"node","args":["~/src/jev-mcp/src/server.js"],"env":{"TYPESAFE_API_KEY":"'"$TYPESAFE_API_KEY"'"}}'

Codex: `codex mcp add jev -- node ~/src/jev-mcp/src/server.js`

Antigravity: `agy mcp add jev node ~/src/jev-mcp/src/server.js`

Cursor: add a `jev` entry under `mcpServers` in `~/.cursor/mcp.json`, then
`cursor-agent mcp list-tools jev` to confirm.

Or in an `.mcp.json`:

    {
      "mcpServers": {
        "jev": {
          "command": "node",
          "args": ["~/src/jev-mcp/src/server.js"]
        }
      }
    }

With no `env` block the server reads `TYPESAFE_API_KEY` from the environment it
inherits, and falls back to parsing the single export line in
`~/.config/typesafe/env.sh`. The key value is never printed, logged, or included in an
error message.

## Guards

`MAX_QUESTIONS_PER_CALL` (32) and `MAX_STATE_CHARS` (200000) in `src/server.js` reject
oversized calls locally, before the request is made. Question shapes are checked
locally too (`src/questions.js`): a `choice` needs an object of options, a `score` needs
at least two ordered levels, and a `noul` answer has no confidence field. A wrong shape
is a 422 from the API, so catching it here costs nothing.

## Requirements

Node >= 20, a TypeSafe API key. `npm install` once; there is no build step.
