from __future__ import annotations

from pathlib import Path
import sys

from fastapi.staticfiles import StaticFiles
from loguru import logger

from app.api.application import create_runtime_app
from app.api.panel import PANEL_DIR, router as panel_router


class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response


def _print_log_message(message: str) -> None:
    encoding = sys.stdout.encoding or "utf-8"
    sys.stdout.write(message.encode(encoding, errors="replace").decode(encoding, errors="replace"))
    sys.stdout.flush()


LOG_DIR = Path("logs")
LOG_DIR.mkdir(parents=True, exist_ok=True)

logger.remove()
logger.add(lambda message: _print_log_message(str(message)), level="INFO")
logger.add(LOG_DIR / "app.log", level="INFO", rotation="10 MB", retention=5)

app = create_runtime_app()
app.include_router(panel_router)
app.mount("/panel/assets", NoCacheStaticFiles(directory=PANEL_DIR), name="panel-assets")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
