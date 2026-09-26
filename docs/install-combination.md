# The install combination

`npx skills add typesafe-ai/skills --skill typesafe-ai` installs the upstream design
skill. That teaches an agent what Jev is; it does not give the agent a way to call it.
`scripts/install-typesafe-jev.sh` wraps that command into a setup that works: the skill,
the credential, the `jev` and `laya` MCP servers, the `jev-audit` skill in both stores, and a live
call that proves the whole path answers.

## What it does

1. Checks Node >= 20 and npm.
2. Runs `npx skills add typesafe-ai/skills --skill typesafe-ai`, skipped when the skill
   is already installed.
3. Checks `~/.config/typesafe/env.sh` exists, is mode 600, and yields
   `TYPESAFE_API_KEY` when sourced. If it is missing the script prints the key-creation
   instructions and exits — it never asks you to type a secret into it.
4. Runs `npm install` in `~/src/jev-mcp`, skipped when `node_modules` exists.
5. Registers the `jev` MCP server (`node src/server.js`) and the `laya` MCP server
   (`node src/laya-server.js`) with all four hosts. Claude and Codex go through their
   CLIs (`claude mcp remove` then `claude mcp add-json -s user`; `codex mcp remove` then
   `codex mcp add`), and a host whose CLI is not on PATH is skipped with a message.
   Antigravity (`~/.gemini/config/mcp_config.json`) and Cursor (`~/.cursor/mcp.json`) get
   an atomic JSON edit that keeps other servers and any extra keys on the two entries.
   `jev` gets no env; the server reads `~/.config/typesafe/env.sh` itself, so the key
   never appears on argv or in a config file. `laya` gets only the six `LAYA_*` settings:
   shell env first, then the first saved value in Claude, Cursor, Antigravity, then the
   default profile.
6. Copies `skills/jev-audit` into `~/.claude/skills` and mirrors it byte-for-byte into
   `~/.codex/skills`. An existing copy that differs stops the script unless `--force`.
7. Posts one tiny `noul` question and asserts HTTP 200, printing the status and the
   answer only.

## Run it

    # see every action, change nothing
    ~/src/jev-mcp/scripts/install-typesafe-jev.sh --dry-run

    # do it, with the confirmation prompt
    ~/src/jev-mcp/scripts/install-typesafe-jev.sh

    # unattended
    ~/src/jev-mcp/scripts/install-typesafe-jev.sh --yes

    # take it back out, leaving the credential and the upstream skill alone
    ~/src/jev-mcp/scripts/install-typesafe-jev.sh --uninstall

## Verify by hand

- The upstream skill is present: `ls ~/.claude/skills/typesafe-ai` or the plugin path.
- `claude mcp list`, `codex mcp get jev`, `codex mcp get laya` and `agy mcp list` each
  show both `jev` and `laya`.
- `cursor-agent mcp list` shows `jev: ready` and `laya: ready`.
  `cursor-agent mcp list-tools jev` lists the six `jev` tools (`jev_ask`, `jev_noul`,
  `jev_choice`, `jev_score`, `jev_models`, `decision_browser_action`), and
  `cursor-agent mcp list-tools laya` lists the three `laya_*` tools (`laya_ask`,
  `laya_bookmark_topic`, `laya_status`).
- The smoke test printed `HTTP 200` and a `noul` near 1.
- `ls ~/.claude/skills/jev-audit ~/.codex/skills/jev-audit` both resolve.
- A fresh agent session lists the six `jev` tools and the three `laya_*` tools.

## Troubleshooting

| Symptom | Means | Do |
| --- | --- | --- |
| HTTP 401 | the key is invalid or revoked | create a new key and rewrite the credential file; do not retry |
| HTTP 422 | a malformed request; the body names the field | fix the question shape — `choice` needs an object criteria, `score` an ordered array of two or more |
| HTTP 429 | rate limited | wait and re-run; the server and SDKs already back off |
| HTTP 529 | the service is overloaded | wait and re-run |
| a vendor's list has no `jev` or no `laya` | registration was skipped or that config file was not written | re-run step 5; it registers both servers with all four hosts (check that host's CLI is on PATH) |
| a vendor has `jev` but no key | that CLI launched the server without `TYPESAFE_API_KEY` | nothing to do: the server falls back to reading `~/.config/typesafe/env.sh` itself |
| the agent sees no `jev_*` or `laya_*` tools | the session started before registration | restart the agent session |

## A note on the standing rule

This Mac's rule is to not install third-party skill packs. This install is an explicit
owner exception, taken on 2026-09-19, covering the `typesafe-ai/skills` pack only. The
`jev-audit` skill is locally authored and not third-party.
