#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ -f ".env" ]; then
  set -a
  source .env
  set +a
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
export ZEBRA_API="${ZEBRA_API:-http://127.0.0.1:8000}"

if [ -z "${BOT_TOKEN:-}" ]; then
  echo "BOT_TOKEN is not set"
  exit 1
fi

exec "$PYTHON_BIN" -m zebra_bot.main