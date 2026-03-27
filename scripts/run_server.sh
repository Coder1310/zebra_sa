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
HOST="${ZEBRA_HOST:-127.0.0.1}"
PORT="${ZEBRA_PORT:-8000}"

exec "$PYTHON_BIN" -m uvicorn server.main:app --host "$HOST" --port "$PORT" --reload