#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

PYTHON_BIN="${XIAOYI_PYTHON:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  if [[ ! -x .venv/bin/python ]]; then
    python3 -m venv .venv
  fi
  PYTHON_BIN=".venv/bin/python"
fi

if ! "$PYTHON_BIN" -c 'import fastapi, pydantic, uvicorn' >/dev/null 2>&1; then
  "$PYTHON_BIN" -m pip install -r requirements.lock
fi

if [[ ! -f data/public/uci_appliances_energy.csv ]]; then
  "$PYTHON_BIN" scripts/fetch_public_rl_dataset.py
fi

"$PYTHON_BIN" scripts/build_index.py
exec "$PYTHON_BIN" -m uvicorn app.main:app \
  --host "${XIAOYI_HOST:-127.0.0.1}" \
  --port "${XIAOYI_PORT:-8010}"
