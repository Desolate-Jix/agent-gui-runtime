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

if not exist logs mkdir logs

curl -fsS "http://127.0.0.1:8000/health" >nul 2>nul
if errorlevel 1 (
  echo FastAPI runtime is not ready. Starting it in a minimized window...
  start "agent-gui-runtime-api" /min cmd /c "cd /d ""%~dp0"" && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 >> logs\test-panel-runtime.log 2>&1"
)

set READY=0
for /l %%i in (1,1,20) do (
  curl -fsS "http://127.0.0.1:8000/health" >nul 2>nul
  if not errorlevel 1 (
    set READY=1
    goto runtime_ready
  )
  timeout /t 1 /nobreak >nul
)

:runtime_ready
if not "%READY%"=="1" (
  echo FastAPI runtime did not become ready at http://127.0.0.1:8000/health.
  echo Check logs\test-panel-runtime.log for details.
  pause
  exit /b 1
)

echo Opening browser test panel...
start "" "http://127.0.0.1:8000/panel"
