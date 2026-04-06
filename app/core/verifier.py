from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from app.core.screenshot import screenshot_service
from app.core.window_manager import window_manager
from app.models.request import ROIModel

CV2_AVAILABLE = False
CV2_IMPORT_ERROR: Optional[str] = None

try:
    import cv2
    import numpy as np

    CV2_AVAILABLE = True
except Exception as exc:  # pragma: no cover
    cv2 = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    CV2_IMPORT_ERROR = str(exc)


class Verifier:
    """Validate post-action outcomes for stable automation steps."""

    def __init__(self) -> None:
        self._log_dir = Path("logs")
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def capture_pre_action_state(self, roi: Optional[ROIModel] = None) -> dict[str, Any]:
        """Capture minimal state before an action executes."""
        bound = window_manager.get_bound_window()
        capture = screenshot_service.capture_window(roi=roi, save_image=True)
        pre_state = {
            "captured": True,
            "roi": capture.get("roi"),
            "image_path": capture.get("image_path"),
            "window_handle": bound.handle if bound is not None else None,
            "window_title": bound.title if bound is not None else None,
            "is_active": bound.is_active if bound is not None else False,
        }
        logger.info("Captured pre-action state: {}", pre_state)
        return pre_state

    def verify_action(
        self,
        action_name: str,
        *,
        roi: Optional[ROIModel] = None,
        before_state: Optional[dict[str, Any]] = None,
        click_result: Optional[dict[str, Any]] = None,
        wait_ms: int = 250,
    ) -> dict[str, Any]:
        """Verify an action using before/after screenshots plus focus/cursor checks."""
        logger.info("Verifying action: {}", action_name)
        time.sleep(max(0, wait_ms) / 1000.0)

        after_capture = screenshot_service.capture_window(roi=roi, save_image=True)
        bound = window_manager.get_bound_window()

        diff_result = self._compare_images(
            before_path=(before_state or {}).get("image_path"),
            after_path=after_capture.get("image_path"),
            action_name=action_name,
        )

        cursor_moved = None
        foreground_consistent = None
        expected_handle = (before_state or {}).get("window_handle")
        if click_result:
            before_cursor = click_result.get("cursor_before") or {}
            after_cursor = click_result.get("cursor_after") or {}
            if before_cursor and after_cursor:
                cursor_moved = (
                    before_cursor.get("x") != after_cursor.get("x") or
                    before_cursor.get("y") != after_cursor.get("y")
                )

            foreground_before = click_result.get("foreground_before")
            foreground_after = click_result.get("foreground_after")
            if foreground_before is not None and foreground_after is not None:
                foreground_consistent = foreground_before == foreground_after
                if expected_handle is not None:
                    foreground_consistent = foreground_consistent and int(foreground_after) == int(expected_handle)

        diff_changed = diff_result.get("changed")
        verified = bool(diff_changed) or bool(cursor_moved and foreground_consistent)

        result = {
            "verified": verified,
            "action_name": action_name,
            "before": before_state,
            "after": {
                "image_path": after_capture.get("image_path"),
                "roi": after_capture.get("roi"),
                "window_handle": bound.handle if bound is not None else None,
                "window_title": bound.title if bound is not None else None,
                "is_active": bound.is_active if bound is not None else False,
            },
            "diff": diff_result,
            "cursor_moved": cursor_moved,
            "foreground_consistent": foreground_consistent,
            "verification_basis": {
                "diff_changed": diff_changed,
                "cursor_and_focus": bool(cursor_moved and foreground_consistent),
            },
        }
        logger.info("Verification result: {}", result)
        return result

    def _compare_images(self, before_path: Optional[str], after_path: Optional[str], action_name: str) -> dict[str, Any]:
        if not before_path or not after_path:
            return {
                "available": False,
                "changed": None,
                "reason": "missing_before_or_after_image",
            }

        if not CV2_AVAILABLE:
            return {
                "available": False,
                "changed": None,
                "reason": f"opencv_unavailable: {CV2_IMPORT_ERROR}",
                "before_path": before_path,
                "after_path": after_path,
            }

        before = cv2.imread(before_path)
        after = cv2.imread(after_path)
        if before is None or after is None:
            return {
                "available": False,
                "changed": None,
                "reason": "failed_to_read_images",
                "before_path": before_path,
                "after_path": after_path,
            }

        if before.shape != after.shape:
            return {
                "available": False,
                "changed": None,
                "reason": f"image_size_mismatch: {before.shape} vs {after.shape}",
                "before_path": before_path,
                "after_path": after_path,
            }

        gray1 = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
        gray2 = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(gray1, gray2)
        _, thresholded = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        thresholded = cv2.morphologyEx(thresholded, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(thresholded, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        regions: list[dict[str, int]] = []
        visual = after.copy()
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            area = int(w * h)
            if area < 80:
                continue
            regions.append({"x": int(x), "y": int(y), "w": int(w), "h": int(h), "area": area})
            cv2.rectangle(visual, (x, y), (x + w, y + h), (0, 0, 255), 2)

        regions.sort(key=lambda item: item["area"], reverse=True)
        timestamp = int(time.time() * 1000)
        diff_path = self._log_dir / f"verify-{action_name}-{timestamp}-diff.png"
        cv2.imwrite(str(diff_path), visual)

        return {
            "available": True,
            "changed": len(regions) > 0,
            "count": len(regions),
            "regions": regions,
            "before_path": before_path,
            "after_path": after_path,
            "diff_image_path": str(diff_path.resolve()),
        }


verifier = Verifier()
