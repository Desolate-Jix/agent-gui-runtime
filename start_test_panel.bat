@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Project Python environment is missing. Python 3.11 is required.
  echo Explicit setup: uv sync --locked --group dev
  exit /b 1
)

".venv\Scripts\python.exe" scripts\start_test_panel.py %*
if errorlevel 1 (
  echo Failed to start or check the test panel. 1>&2
  exit /b 1
)
