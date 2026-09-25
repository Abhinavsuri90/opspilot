#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
python -m uvicorn app.main:app --app-dir apps/api --host 127.0.0.1 --port 8765 &
api_pid=$!
trap 'kill "$api_pid" 2>/dev/null || true' EXIT

attempt=0
while [ "$attempt" -lt 20 ]; do
  if python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/readyz', timeout=1)" >/dev/null 2>&1; then
    break
  fi
  attempt=$((attempt + 1))
  sleep 1
done

python scripts/smoke_test.py http://127.0.0.1:8765
