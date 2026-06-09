#!/usr/bin/env bash
# PostToolUse formatter: runs on Edit/Write of .py / .ts / .tsx files.
# Input: JSON on stdin with tool_input.file_path.

set -euo pipefail

FILE=$(cat - | jq -r '.tool_input.file_path // empty')

if [[ -z "$FILE" ]]; then
  exit 0
fi

REPO_ROOT="$(git -C "$(dirname "$FILE")" rev-parse --show-toplevel 2>/dev/null || true)"

case "$FILE" in
  *.py)
    if [[ -n "$REPO_ROOT" && -d "$REPO_ROOT/backend" ]]; then
      cd "$REPO_ROOT/backend"
      uv run ruff format "$FILE" 2>/dev/null || true
      uv run ruff check --fix --unsafe-fixes "$FILE" 2>/dev/null || true
    fi
    ;;
  *.ts|*.tsx)
    if [[ -n "$REPO_ROOT" && -d "$REPO_ROOT/frontend/node_modules/.bin" ]]; then
      "$REPO_ROOT/frontend/node_modules/.bin/prettier" --write "$FILE" 2>/dev/null || true
    fi
    ;;
esac
