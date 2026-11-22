#!/usr/bin/env bash
# Start the demo with one command (macOS/Linux). Builds whatever is missing, then serves everything on :8000.
# Usage: ./run.sh            (./run.sh --rebuild to rebuild the frontend)
set -euo pipefail
root="$(cd "$(dirname "$0")" && pwd)"

cd "$root/backend"
if [ ! -x .venv/bin/python ]; then
  echo "Creating Python environment..."
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
fi
if [ "${1:-}" = "--rebuild" ] || [ ! -f "$root/frontend/dist/index.html" ]; then
  echo "Building frontend..."
  (cd "$root/frontend" && npm install && npm run build)
fi
echo
echo "Demo running at http://localhost:8000   (Ctrl+C to stop)"
exec .venv/bin/python -m uvicorn app.main:app --port 8000
