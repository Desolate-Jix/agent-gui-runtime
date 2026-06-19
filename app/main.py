from __future__ import annotations

from pathlib import Path
import sys

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.api.action import router as action_router
from app.api.apps import router as apps_router
from app.api.execute import router as execute_router
from app.api.panel import PANEL_DIR, router as panel_router
from app.api.runtime import router as runtime_router
from app.api.session import router as session_router
from app.api.state import router as state_router
from app.api.vision import router as vision_router
from app.models.response import APIResponse, HealthData

LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

logger.remove()
logger.add(lambda message: _print_log_message(str(message)), level="INFO")
logger.add(LOG_DIR / "app.log", level="INFO", rotation="10 MB", retention=5)

app = FastAPI(title="agent-gui-runtime", version="0.1.0")
app.include_router(apps_router)
app.include_router(runtime_router)
app.include_router(session_router)
app.include_router(state_router)
app.include_router(action_router)
app.include_router(execute_router)
app.include_router(vision_router)
app.include_router(panel_router)
app.mount("/panel/assets", StaticFiles(directory=PANEL_DIR), name="panel-assets")


def _print_log_message(message: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    sys.stdout.write(message.encode(encoding, errors="replace").decode(encoding, errors="replace"))
    sys.stdout.flush()


@app.get("/health", response_model=APIResponse)
def health() -> APIResponse:
    """Service health endpoint."""
    data = HealthData()
    return APIResponse(success=True, message="Service is healthy", data=data.model_dump(), error=None)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
