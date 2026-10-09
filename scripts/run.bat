@echo off
REM Start the platform. Extra arguments go to "gtp serve", e.g. --port 9000
cd /d "%~dp0\.."
if not exist .venv\Scripts\python.exe (
  echo Run scripts\setup.bat first.
  exit /b 1
)
.venv\Scripts\python -m gtp serve %*
