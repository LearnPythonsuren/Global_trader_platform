#!/usr/bin/env bash
# One-time setup on Linux/macOS: virtualenv, dependencies, .env, tests.
# Usage: ./scripts/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "Python 3.10+ is required (set PYTHON=/path/to/python if it isn't python3)." >&2
  exit 1
fi
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || { echo "Python 3.10+ is required; found $("$PY" --version)." >&2; exit 1; }

if [ ! -d .venv ]; then
  echo "==> Creating virtual environment in .venv"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "==> Installing dependencies"
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -e ".[dev]"

if [ ! -f .env ]; then
  echo "==> Creating .env from .env.example (demo mode)"
  cp .env.example .env
fi

echo "==> Running tests"
python -m pytest -q

cat <<'MSG'

Setup complete.
  Start the app:   ./scripts/run.sh          (http://127.0.0.1:8000)
  Demo API keys:   demo-free-key, demo-pro-key, demo-algo-key
  Go live:         edit .env (GTP_MODE=live + your Global Datafeeds keys),
                   then run: .venv/bin/python -m gtp check
MSG
