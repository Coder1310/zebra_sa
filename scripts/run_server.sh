#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ -d "venv" ]; then
  source venv/bin/activate
fi

python -m uvicorn server.main:app --host 127.0.0.1 --port 8000 --reload