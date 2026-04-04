from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from loguru import logger

MSS_BACKEND_AVAILABLE = False
MSS_BACKEND_IMPORT_ERROR: Optional[str] = None

try:
    from mss import mss
    from PIL import Image

    MSS_BACKEND_AVAILABLE = True
except Exception as exc:  # pragma: no cover - depends on runtime platform/environment
    mss = None  # type: ignore[assignment]
    Image = None  # type: ignore[assignment]
    MSS_BACKEND_IMPORT_ERROR = str(exc)

from app.core.window_manager import window_manager
from app.models.request import ROIModel


class ScreenshotService:
    """Capture screenshots for the currently bound window using MSS."""

    def __init__(self) -> None:
        self._log_dir = Path("logs")
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._capture_keep_limit = 40

    def capture_window(self, roi: Optional[ROIModel] = None, save_image: bool = True) -> dict[str, Any]:
        """Capture a screenshot for the bound window or a sub-region."""
        self._ensure_capture_backend()

        bound = window_manager.get_bound_window()
        if bound is None:
            raise ValueError("No bound window available for capture")

        capture_rect = self._resolve_capture_rect(
            left=bound.rect.left,
            top=bound.rect.top,
            right=bound.rect.right,
            bottom=bound.rect.bottom,
            roi=roi,
        )

        monitor = {
            "left": capture_rect["left"],
            "top": capture_rect["top"],
            "width": capture_rect["width"],
            "height": capture_rect["height"],
        }

        logger.info("Capturing bound window: handle={}, monitor={}", bound.handle, monitor)

        with mss() as sct:  # type: ignore[operator]
            raw = sct.grab(monitor)
            image = Image.frombytes("RGB", raw.size, raw.rgb)  # type: ignore[union-attr]

        image_path: Optional[str] = None
        if save_image:
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            image_path = str((self._log_dir / f"capture-{timestamp}.png").resolve())
            image.save(image_path)
            logger.info("Saved screenshot to {}", image_path)
            self._cleanup_old_captures()

        return {
            "image_path": image_path,
            "image_width": image.width,
            "image_height": image.height,
            "roi": capture_rect["roi"],
            "roi_adjusted": capture_rect["roi_adjusted"],
            "window_size": {
                "width": capture_rect["window_width"],
                "height": capture_rect["window_height"],
            },
        }

    def _resolve_capture_rect(
        self,
        left: int,
        top: int,
        right: int,
        bottom: int,
        roi: Optional[ROIModel],
    ) -> dict[str, Any]:
        """Resolve full-window or ROI-relative capture coordinates."""
        window_width = max(1, right - left)
        window_height = max(1, bottom - top)

        if roi is None:
            return {
                "left": left,
                "top": top,
                "width": window_width,
                "height": window_height,
                "roi": None,
                "roi_adjusted": False,
                "window_width": window_width,
                "window_height": window_height,
            }

        requested = roi.model_dump()
        roi_x = min(max(0, roi.x), window_width - 1)
        roi_y = min(max(0, roi.y), window_height - 1)
        max_width = max(1, window_width - roi_x)
        max_height = max(1, window_height - roi_y)
        roi_width = min(roi.width, max_width)
        roi_height = min(roi.height, max_height)
        adjusted = (
            roi_x != roi.x or
            roi_y != roi.y or
            roi_width != roi.width or
            roi_height != roi.height
        )

        if roi_width < 1 or roi_height < 1:
            raise ValueError("ROI is outside the bound window")

        return {
            "left": left + roi_x,
            "top": top + roi_y,
            "width": roi_width,
            "height": roi_height,
            "roi": {
                "x": roi_x,
                "y": roi_y,
                "width": roi_width,
                "height": roi_height,
                "requested": requested,
            },
            "roi_adjusted": adjusted,
            "window_width": window_width,
            "window_height": window_height,
        }

    def _cleanup_old_captures(self) -> None:
        captures = sorted(
            self._log_dir.glob("capture-*.png"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for stale in captures[self._capture_keep_limit:]:
            try:
                stale.unlink()
                logger.info("Removed old capture {}", stale)
            except Exception as exc:  # pragma: no cover - cleanup should be best effort
                logger.warning("Failed to remove old capture {}: {}", stale, exc)

    def _ensure_capture_backend(self) -> None:
        """Ensure screenshot capture dependencies are available."""
        if not MSS_BACKEND_AVAILABLE:
            raise RuntimeError(
                "Screenshot backend is unavailable. "
                f"Import error: {MSS_BACKEND_IMPORT_ERROR}"
            )


screenshot_service = ScreenshotService()
