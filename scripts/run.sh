#!/usr/bin/env bash
# Start the platform. Extra arguments go to "gtp serve", e.g. --port 9000 --host 0.0.0.0
set -euo pipefail
cd "$(dirname "$0")/.."
[ -d .venv ] || { echo "Run ./scripts/setup.sh first." >&2; exit 1; }
exec .venv/bin/python -m gtp serve "$@"
