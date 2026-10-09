#!/bin/bash
# Installs Python dependencies so tests (pytest) and the linter (ruff) work
# in Claude Code cloud sessions. Runs synchronously; safe to run repeatedly.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "${CLAUDE_PROJECT_DIR:-$(dirname "$0")/../..}"

# Editable install pulls runtime deps from pyproject.toml plus pytest and ruff.
python3 -m pip install --quiet --disable-pip-version-check -e ".[dev]"

# Demo mode needs no secrets; create .env from the example if it is missing.
[ -f .env ] || cp .env.example .env

# pip may place console scripts (ruff, gtp) here.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$CLAUDE_ENV_FILE"
fi
