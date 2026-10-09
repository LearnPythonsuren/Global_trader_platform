@echo off
REM One-time setup on Windows: virtualenv, dependencies, .env, tests.
REM Usage: scripts\setup.bat
setlocal
cd /d "%~dp0\.."

where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" || (
  echo Python 3.10+ is required. Install it from https://www.python.org/downloads/
  exit /b 1
)

if not exist .venv (
  echo ==^> Creating virtual environment in .venv
  %PY% -m venv .venv || exit /b 1
)

echo ==^> Installing dependencies
.venv\Scripts\python -m pip install --quiet --upgrade pip || exit /b 1
.venv\Scripts\python -m pip install --quiet -e ".[dev]" || exit /b 1

if not exist .env (
  echo ==^> Creating .env from .env.example ^(demo mode^)
  copy .env.example .env >nul
)

echo ==^> Running tests
.venv\Scripts\python -m pytest -q || exit /b 1

echo.
echo Setup complete.
echo   Start the app:   scripts\run.bat          (http://127.0.0.1:8000)
echo   Demo API keys:   demo-free-key, demo-pro-key, demo-algo-key
echo   Go live:         edit .env (GTP_MODE=live + your Global Datafeeds keys),
echo                    then run: .venv\Scripts\python -m gtp check
