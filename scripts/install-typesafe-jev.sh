#!/usr/bin/env bash
#
# Install and wire TypeSafe Jev on this Mac, in one idempotent pass.
#
# Extends `npx skills add typesafe-ai/skills --skill typesafe-ai` — which installs the
# upstream design skill and nothing else — into a working setup: the credential is
# checked, the `jev` and `laya` MCP servers are registered, the jev-audit skill lands in both skill
# stores, and a live call proves the whole thing answers.
#
# Safe to re-run: every step detects its own result and skips.
#
set -euo pipefail

REPO="~/src/jev-mcp"
SERVER="$REPO/src/server.js"
LAYA_SERVER="$REPO/src/laya-server.js"
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
  command -v claude >/dev/null 2>&1 && claude mcp list 2>/dev/null | grep -q "^$1\\b\\|[[:space:]]$1[[:space:]]\\|^$1:"
}

codex_registered() {
  command -v codex >/dev/null 2>&1 && codex mcp get "$1" >/dev/null 2>&1
}

agy_registered() {
  command -v agy >/dev/null 2>&1 && agy mcp list 2>/dev/null | grep -q "^$1[[:space:]]"
}

cursor_registered() {
  [ -f "$CURSOR_MCP" ] && grep -q "\"$1\"" "$CURSOR_MCP"
}

if [ "$UNINSTALL" = 1 ]; then
  step 1 "Remove the jev and laya MCP registrations"
  for server_name in jev laya; do
    if mcp_registered "$server_name"; then run claude mcp remove "$server_name" || true; else skip "claude: $server_name not registered"; fi
    if codex_registered "$server_name"; then run codex mcp remove "$server_name" || true; else skip "codex: $server_name not registered"; fi
    if agy_registered "$server_name"; then run agy mcp remove "$server_name" || true; else skip "antigravity: $server_name not registered"; fi
  done
  if cursor_registered jev || cursor_registered laya; then
    run python3 -c 'import json,sys; p=sys.argv[1]; c=json.load(open(p)); [c.get("mcpServers",{}).pop(n,None) for n in ("jev","laya")]; json.dump(c,open(p,"w"),indent=2)' "$CURSOR_MCP"
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
say "  5. register the jev and laya MCP servers with Claude (user scope), Codex, Antigravity and Cursor"
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

step 5 "MCP registration for both providers"
if [ "$DRY_RUN" = 1 ]; then
  say "      would write jev -> node $SERVER (no env)"
  say "      would write laya -> node $LAYA_SERVER (LAYA_* env only)"
else
  python3 - "$REPO" "$HOME" <<'PYEOF' || fail 5 "could not update MCP registrations"
import json
import os
from pathlib import Path
import re
import sys
try:
    import tomllib
except ImportError:  # macOS system python3 is 3.9; saved Codex env is then read from the other clients
    tomllib = None

repo, home = map(Path, sys.argv[1:])
names = ("LAYA_PYTHON", "LAYA_MODEL_DIR", "LAYA_CHECKPOINT",
         "LAYA_MODEL_REVISION", "LAYA_TIMEOUT_MS", "LAYA_MAX_QUEUE")
paths = {
    "claude": home / ".claude.json",
    "codex": home / ".codex/config.toml",
    "cursor": home / ".cursor/mcp.json",
    "antigravity": home / ".gemini/config/mcp_config.json",
}
saved = {}
configs = {}
for client in ("claude", "cursor", "antigravity"):
    path = paths[client]
    configs[client] = json.loads(path.read_text()) if path.exists() else {}
    for server in ("laya", "jev"):
        saved.update({k: str(v) for k, v in
            configs[client].get("mcpServers", {}).get(server, {}).get("env", {}).items()
            if k in names and v is not None})
codex_text = paths["codex"].read_text() if paths["codex"].exists() else ""
if codex_text and tomllib:
    codex_data = tomllib.loads(codex_text)
    for server in ("laya", "jev"):
        saved.update({k: str(v) for k, v in
            codex_data.get("mcp_servers", {}).get(server, {}).get("env", {}).items()
            if k in names and v is not None})
try:
    registry = json.loads((repo / "config/decision-profiles.json").read_text())
    profile = registry["profiles"][registry["defaultProfile"]]
    runtime = profile["runtime"]
    defaults = {
        "LAYA_PYTHON": runtime["python"],
        "LAYA_MODEL_DIR": runtime["modelPath"],
        "LAYA_CHECKPOINT": profile["checkpoint"],
        "LAYA_MODEL_REVISION": profile["revision"],
        "LAYA_TIMEOUT_MS": runtime["timeoutMs"],
        "LAYA_MAX_QUEUE": runtime["maxQueue"],
    }
except (OSError, KeyError, TypeError, ValueError):
    defaults = {}
laya_env = {k: str(os.environ.get(k) or saved.get(k) or defaults.get(k) or "")
            for k in names}
missing = [k for k, v in laya_env.items() if not v]
if missing:
    raise SystemExit("missing Laya settings: " + ", ".join(missing))

for client in ("claude", "cursor", "antigravity"):
    path = paths[client]
    cfg = configs[client]
    servers = cfg.setdefault("mcpServers", {})
    command = servers.get("jev", {}).get("command") or servers.get("laya", {}).get("command") or "node"
    servers["jev"] = {"command": command, "args": [str(repo / "src/server.js")]}
    servers["laya"] = {"command": command, "args": [str(repo / "src/laya-server.js")], "env": laya_env}
    output = json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"
    if not path.exists() or path.read_text() != output:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output)
    print(f"      {client}: jev and laya registered")

heading = re.compile(r"(?m)^\[mcp_servers\.(?:jev|laya)(?:\.env)?\]\s*\n")
positions = list(re.finditer(r"(?m)^\[[^\n]+\]\s*\n", codex_text))
remove = []
for index, match in enumerate(positions):
    if heading.fullmatch(match.group()):
        stop = positions[index + 1].start() if index + 1 < len(positions) else len(codex_text)
        remove.append((match.start(), stop))
for start, stop in reversed(remove):
    codex_text = codex_text[:start] + codex_text[stop:]
codex_text = codex_text.rstrip() + "\n\n"
codex_text += "[mcp_servers.jev]\ncommand = \"node\"\nargs = [" + json.dumps(str(repo / "src/server.js")) + "]\n\n"
codex_text += "[mcp_servers.laya]\ncommand = \"node\"\nargs = [" + json.dumps(str(repo / "src/laya-server.js")) + "]\n\n"
codex_text += "[mcp_servers.laya.env]\n"
for key in names:
    codex_text += key + " = " + json.dumps(laya_env[key]) + "\n"
path = paths["codex"]
if not path.exists() or path.read_text() != codex_text:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(codex_text)
print("      codex: jev and laya registered")
PYEOF
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
