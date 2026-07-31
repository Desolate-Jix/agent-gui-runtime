@echo off
setlocal
cd /d "%~dp0"

where uv >nul 2>nul
if errorlevel 1 (
  echo uv is not available on PATH.
  echo Install uv or open this project from an environment where uv works.
  pause
  exit /b 1
)

uv run python scripts\start_test_panel.py %*
if errorlevel 1 (
  echo.
  echo Failed to start the test panel.
  pause
  exit /b 1
)
