#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [ -f ".env" ]; then
  set -a
  source .env
  set +a
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
HOST="${ZEBRA_HOST:-127.0.0.1}"
PORT="${ZEBRA_PORT:-8000}"
API_URL="http://$HOST:$PORT"

if [ -z "${BOT_TOKEN:-}" ]; then
  echo "BOT_TOKEN is not set"
  exit 1
fi

export ZEBRA_API="${ZEBRA_API:-$API_URL}"

cleanup() {
  jobs -p | xargs -r kill
}
trap cleanup EXIT

"$PYTHON_BIN" -m uvicorn server.main:app --host "$HOST" --port "$PORT" --reload &
sleep 2
exec "$PYTHON_BIN" -m zebra_bot.main