#!/usr/bin/env bash
#
# Install and wire TypeSafe Jev on this Mac, in one idempotent pass.
#
# Extends `npx skills add typesafe-ai/skills --skill typesafe-ai` — which installs the
# upstream design skill and nothing else — into a working setup: the credential is
# checked, the `jev` MCP server is registered, the jev-audit skill lands in both skill
# stores, and a live call proves the whole thing answers.
#
# Safe to re-run: every step detects its own result and skips.
#
set -euo pipefail

REPO="~/src/jev-mcp"
SERVER="$REPO/src/server.js"
SKILL_SRC="$REPO/skills/jev-audit"
CLAUDE_SKILLS="$HOME/.claude/skills"
CODEX_SKILLS="$HOME/.codex/skills"
KEY_FILE="$HOME/.config/typesafe/env.sh"
CURSOR_MCP="$HOME/.cursor/mcp.json"

DRY_RUN=0
ASSUME_YES=0
FORCE=0
UNINSTALL=0

for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    --force) FORCE=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help)
      echo "usage: $(basename "$0") [--dry-run] [--yes] [--force] [--uninstall]"
      exit 0
      ;;
    *)
      echo "unknown option: $arg" >&2
      exit 64
      ;;
  esac
done

say() { printf '%s\n' "$*"; }
step() { printf '\n[%s] %s\n' "$1" "$2"; }
skip() { printf '      already done: %s\n' "$1"; }
fail() { printf 'step %s failed: %s\n' "$1" "$2" >&2; exit 1; }
run() {
  if [ "$DRY_RUN" = 1 ]; then
    printf '      would run: %s\n' "$*"
    return 0
  fi
  "$@"
}

have_skill() {
  [ -d "$CLAUDE_SKILLS/typesafe-ai" ] \
    || [ -d "$HOME/.claude/plugins/typesafe/skills/typesafe-ai" ] \
    || ls -d "$HOME"/.claude/plugins/*/skills/typesafe-ai >/dev/null 2>&1
}

mcp_registered() {
  command -v claude >/dev/null 2>&1 && claude mcp list 2>/dev/null | grep -q '^jev\b\|[[:space:]]jev[[:space:]]\|^jev:'
}

codex_registered() {
  command -v codex >/dev/null 2>&1 && codex mcp get jev >/dev/null 2>&1
}

agy_registered() {
  command -v agy >/dev/null 2>&1 && agy mcp list 2>/dev/null | grep -q '^jev[[:space:]]'
}

cursor_registered() {
  [ -f "$CURSOR_MCP" ] && grep -q '"jev"' "$CURSOR_MCP"
}

# Adds jev to ~/.cursor/mcp.json without disturbing the servers already there.
cursor_add() {
  python3 - "$CURSOR_MCP" "$SERVER" <<'PYEOF'
import json, os, shutil, sys
path, server = sys.argv[1], sys.argv[2]
os.makedirs(os.path.dirname(path), exist_ok=True)
cfg = json.load(open(path)) if os.path.exists(path) else {}
if os.path.exists(path):
    shutil.copy(path, path + ".before-jev")
cfg.setdefault("mcpServers", {})["jev"] = {"command": "node", "args": [server]}
json.dump(cfg, open(path, "w"), indent=2)
print("      wrote", path)
PYEOF
}

if [ "$UNINSTALL" = 1 ]; then
  step 1 "Remove the jev MCP registrations"
  if mcp_registered; then run claude mcp remove jev || true; else skip "claude: not registered"; fi
  if codex_registered; then run codex mcp remove jev || true; else skip "codex: not registered"; fi
  if agy_registered; then run agy mcp remove jev || true; else skip "antigravity: not registered"; fi
  if cursor_registered; then
    run python3 -c 'import json,sys; p=sys.argv[1]; c=json.load(open(p)); c.get("mcpServers",{}).pop("jev",None); json.dump(c,open(p,"w"),indent=2)' "$CURSOR_MCP"
  else
    skip "cursor: not registered"
  fi
  step 2 "Remove the copied jev-audit skill"
  for dest in "$CLAUDE_SKILLS/jev-audit" "$CODEX_SKILLS/jev-audit"; do
    if [ -d "$dest" ]; then run rm -rf "$dest"; else skip "$dest absent"; fi
  done
  say ""
  say "Left alone on purpose: the credential at $KEY_FILE and the upstream typesafe-ai skill."
  exit 0
fi

say "Plan:"
say "  1. check Node >= 20 and npm"
say "  2. npx skills add typesafe-ai/skills --skill typesafe-ai"
say "  3. check the TypeSafe credential at $KEY_FILE"
say "  4. npm install in $REPO"
say "  5. register the jev MCP server with Claude, Codex, Antigravity and Cursor"
say "  6. copy skills/jev-audit into $CLAUDE_SKILLS and mirror to $CODEX_SKILLS"
say "  7. one live call to prove it answers"
[ "$DRY_RUN" = 1 ] && say "" && say "(dry run: nothing will change)"

if [ "$DRY_RUN" = 0 ] && [ "$ASSUME_YES" = 0 ]; then
  printf '\nProceed? [y/N] '
  read -r reply
  case "$reply" in
    y|Y) ;;
    *) say "stopped."; exit 0 ;;
  esac
fi

step 1 "Node and npm"
command -v node >/dev/null 2>&1 || fail 1 "node is not on PATH"
command -v npm  >/dev/null 2>&1 || fail 1 "npm is not on PATH"
node_major="$(node -p 'process.versions.node.split(".")[0]')"
[ "$node_major" -ge 20 ] || fail 1 "node $node_major is too old; the MCP SDK needs Node 20 or newer"
say "      node $(node -v), npm $(npm -v)"

step 2 "Upstream typesafe-ai skill"
if have_skill; then
  skip "typesafe-ai is present"
else
  run npx skills add typesafe-ai/skills --skill typesafe-ai || fail 2 "npx skills add failed"
fi

step 3 "Credential"
if [ ! -f "$KEY_FILE" ]; then
  say "      $KEY_FILE is missing."
  say "      Create a key at https://console.typesafe.ai/settings/keys, then write the file"
  say "      yourself — this script never asks for or stores a secret:"
  say ""
  say "        umask 077 && mkdir -p ~/.config/typesafe && \\"
  say "          printf 'export TYPESAFE_API_KEY=%s\\n' \"\$KEY\" > ~/.config/typesafe/env.sh"
  say ""
  fail 3 "no credential file"
fi
perms="$(stat -f '%OLp' "$KEY_FILE")"
[ "$perms" = "600" ] || say "      warning: $KEY_FILE is mode $perms; 600 is expected"
# shellcheck disable=SC1090
. "$KEY_FILE"
[ -n "${TYPESAFE_API_KEY:-}" ] || fail 3 "TYPESAFE_API_KEY is still unset after sourcing $KEY_FILE"
say "      key resolved (value never printed)"

step 4 "Dependencies"
if [ -d "$REPO/node_modules/@modelcontextprotocol" ]; then
  skip "node_modules present"
else
  run npm --prefix "$REPO" install || fail 4 "npm install failed"
fi

step 5 "MCP registration, one vendor at a time"
# The key never travels on argv: each server inherits it from the environment, and
# falls back to reading the credential file itself.
if ! command -v claude >/dev/null 2>&1; then
  say "      claude: CLI not found, skipping"
elif mcp_registered; then
  skip "claude: jev is registered"
else
  run claude mcp add-json jev "{\"command\":\"node\",\"args\":[\"$SERVER\"]}" || fail 5 "claude mcp add-json failed"
  say "      claude: registered"
fi

if ! command -v codex >/dev/null 2>&1; then
  say "      codex: CLI not found, skipping"
elif codex_registered; then
  skip "codex: jev is registered"
else
  run codex mcp add jev -- node "$SERVER" || fail 5 "codex mcp add failed"
  say "      codex: registered"
fi

if ! command -v agy >/dev/null 2>&1; then
  say "      antigravity: agy not found, skipping"
elif agy_registered; then
  skip "antigravity: jev is registered"
else
  run agy mcp add jev node "$SERVER" || fail 5 "agy mcp add failed"
  say "      antigravity: registered"
fi

if cursor_registered; then
  skip "cursor: jev is in $CURSOR_MCP"
elif [ "$DRY_RUN" = 1 ]; then
  say "      would add jev to $CURSOR_MCP"
else
  cursor_add || fail 5 "could not write $CURSOR_MCP"
  say "      cursor: registered"
fi

step 6 "jev-audit skill into both stores"
[ -d "$SKILL_SRC" ] || fail 6 "$SKILL_SRC is missing"
for dest_root in "$CLAUDE_SKILLS" "$CODEX_SKILLS"; do
  dest="$dest_root/jev-audit"
  if [ -d "$dest" ]; then
    if diff -r -q "$SKILL_SRC" "$dest" >/dev/null 2>&1; then
      skip "$dest is identical"
      continue
    fi
    if [ "$FORCE" = 0 ]; then
      fail 6 "$dest exists and differs; re-run with --force to overwrite it"
    fi
  fi
  run mkdir -p "$dest_root"
  run rm -rf "$dest"
  run cp -R "$SKILL_SRC" "$dest"
  say "      installed $dest"
done

step 7 "Live smoke test"
if [ "$DRY_RUN" = 1 ]; then
  say "      would POST one noul question to https://api.typesafe.ai/v1/systemone"
else
  body='{"state":"My payouts have been failing for 3 days. Please help ASAP.","model":"jev-latest","questions":{"is_urgent":{"type":"noul","instructions":"Does this message express urgency?"}}}'
  out="$(curl -s -m 30 -X POST https://api.typesafe.ai/v1/systemone \
    -H "Authorization: Bearer $TYPESAFE_API_KEY" \
    -H "Content-Type: application/json" \
    -w '\n%{http_code}' -d "$body")" || fail 7 "curl failed"
  code="${out##*$'\n'}"
  payload="${out%$'\n'*}"
  [ "$code" = "200" ] || fail 7 "HTTP $code from the API: ${payload:0:300}"
  say "      HTTP 200"
  say "      $payload"
fi

say ""
say "Done. Restart the agent session so it picks up the new MCP server and skill."
