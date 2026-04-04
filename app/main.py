from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from loguru import logger

from app.api.action import router as action_router
from app.api.session import router as session_router
from app.api.state import router as state_router
from app.api.vision import router as vision_router
from app.api.wait import router as wait_router
from app.models.response import APIResponse, HealthData

LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

logger.remove()
logger.add(lambda message: print(message, end=""), level="INFO")
logger.add(LOG_DIR / "app.log", level="INFO", rotation="10 MB", retention=5)

app = FastAPI(title="agent-gui-runtime", version="0.1.0")
app.include_router(session_router)
app.include_router(state_router)
app.include_router(vision_router)
app.include_router(action_router)
app.include_router(wait_router)


@app.get("/health", response_model=APIResponse)
def health() -> APIResponse:
    """Service health endpoint."""
    data = HealthData()
    return APIResponse(success=True, message="Service is healthy", data=data.model_dump(), error=None)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
