#!/usr/bin/env bash
#
# Install (or remove) the advisory merge-risk pre-push hook in a repository.
#
set -euo pipefail

SRC="$HOME/src/jev-mcp/hooks/pre-push"
FORCE=0
REMOVE=0
REPOS=()

for a in "$@"; do
  case "$a" in
    --force)  FORCE=1 ;;
    --remove) REMOVE=1 ;;
    -h|--help) echo "usage: install_hook.sh [--force] [--remove] <repo> [repo...]"; exit 0 ;;
    *) REPOS+=("$a") ;;
  esac
done
[ "${#REPOS[@]}" -gt 0 ] || { echo "usage: install_hook.sh [--force] [--remove] <repo> [repo...]" >&2; exit 64; }
[ -x "$SRC" ] || { echo "missing hook source at $SRC" >&2; exit 1; }

for repo in "${REPOS[@]}"; do
  # A linked worktree shares its hooks with the main repository: say so, because
  # installing from a worktree changes the parent repo's behaviour too.
  common="$(git -C "$repo" rev-parse --git-common-dir 2>/dev/null)" || { echo "not a git repo: $repo" >&2; exit 1; }
  case "$common" in /*) ;; *) common="$(cd "$repo" && cd "$common" && pwd)" ;; esac
  dest="$common/hooks/pre-push"
  # A leak-guard wrapper at pre-push runs pre-push.local first: install there and keep the wrapper.
  if [ -e "$dest" ] && grep -q "leak-guard" "$dest" 2>/dev/null; then
    dest="$common/hooks/pre-push.local"
  fi
  mkdir -p "$(dirname "$dest")"

  if [ "$REMOVE" = 1 ]; then
    if [ -e "$dest" ] && grep -q "merge_risk.py" "$dest" 2>/dev/null; then
      rm "$dest"; echo "removed $dest"
    else
      echo "nothing of ours at $dest"
    fi
    continue
  fi

  if [ -e "$dest" ] && ! grep -q "merge_risk.py" "$dest" 2>/dev/null && [ "$FORCE" = 0 ]; then
    echo "refusing to overwrite an existing hook at $dest (use --force)" >&2
    exit 1
  fi
  cp "$SRC" "$dest"
  chmod +x "$dest"
  echo "installed $dest"
  gitdir="$(cd "$repo" && cd "$(git rev-parse --git-dir)" && pwd)"
  [ "$gitdir" != "$common" ] && \
    echo "  note: $repo is a linked worktree; this hook now applies to every worktree of that repository"
done
