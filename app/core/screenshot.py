from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional, Protocol

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
from app.core.runtime_artifacts import SCREENSHOTS_DIR, build_screenshot_path


class ROIValue(Protocol):
    x: int
    y: int
    width: int
    height: int

    def model_dump(self) -> dict[str, Any]: ...


class CaptureVisibilityError(ValueError):
    """仅保留固定可见性原因，不把窗口信息放入跨边界错误。"""

    def __init__(self, reason: str) -> None:
        allowed = {"capture_window_minimized", "capture_window_occluded",
                   "capture_visibility_unavailable", "capture_window_unavailable",
                   "capture_binding_changed", "capture_rectangle_invalid", "capture_visibility_changed"}
        self.reason = reason if isinstance(reason, str) and reason in allowed else "capture_visibility_unavailable"
        super().__init__(self.reason + ": restore and uncover the target window before capture")


class ScreenshotService:
    """Capture screenshots for the currently bound window using MSS."""

    def __init__(
        self,
        *,
        window_manager: Any | None = None,
        capture_dir: Path | None = None,
    ) -> None:
        self._window_manager = (
            globals()["window_manager"] if window_manager is None else window_manager
        )
        self._capture_dir = SCREENSHOTS_DIR if capture_dir is None else Path(capture_dir)
        self._capture_keep_limit = 40
        self._focus_settle_seconds = 0.5

    def capture_window(
        self,
        roi: Optional[ROIValue] = None,
        save_image: bool = True,
        *,
        purpose: str = "capture",
        name_hint: Optional[str] = None,
        focus_window: bool = True,
    ) -> dict[str, Any]:
        """Capture a screenshot for the bound window or a sub-region."""
        started = last_mark = time.perf_counter()
        capture_stages = []

        def mark(name):
            nonlocal last_mark
            now = time.perf_counter()
            capture_stages.append({"name": name, "elapsed_ms": round((now - last_mark) * 1000, 3)})
            last_mark = now

        self._ensure_capture_backend()

        bound = self._window_manager.get_bound_window()
        mark("backend_and_binding")
        # 只用刚刷新过的前台事实省去重复激活，不缓存截图或省略前后来源校验。
        if focus_window and (bound is None or getattr(bound, "is_active", None) is not True):
            bound = self._window_manager.focus_bound_window()
            self._wait_after_focus()
        if bound is None:
            raise ValueError("No bound window available to capture")
        mark("foreground_preparation")

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

        binding = self._capture_binding(bound)
        visibility = self._require_capture_visibility(bound, monitor)
        mark("geometry_and_pre_visibility")

        logger.info("Capturing bound window: handle={}, monitor={}", bound.handle, monitor)

        with mss() as sct:  # type: ignore[operator]
            raw = sct.grab(monitor)
            mark("backend_open_and_grab")
            current = self._window_manager.get_bound_window()
            if current is None or self._capture_binding(current) != binding:
                raise ValueError("capture_binding_changed: discard the captured screen pixels")
            after_visibility = self._require_capture_visibility(current, monitor)
            if visibility.get("occluded_regions", []) != after_visibility.get("occluded_regions", []):
                logger.warning("Capture visibility changed: before={} after={}", visibility.get("occluded_regions"), after_visibility.get("occluded_regions"))
                raise CaptureVisibilityError("capture_visibility_changed")
            mark("post_binding_and_visibility")
            image = Image.frombytes("RGB", raw.size, raw.rgb)  # type: ignore[union-attr]
            mark("pixel_conversion")

        # 不把其他窗口的像素当成目标内容；窗口坐标只在遮罩时换算一次。
        for region in visibility.get("occluded_regions", []):
            x = bound.rect.left + region["x"] - monitor["left"]
            y = bound.rect.top + region["y"] - monitor["top"]
            image.paste((32, 32, 32), (x, y, x + region["width"], y + region["height"]))
        mark("backend_close_and_mask")

        image_path: Optional[str] = None
        if save_image:
            generated_path = build_screenshot_path(
                title=bound.title,
                process_name=bound.process_name,
                handle=bound.handle,
                purpose=purpose,
                roi=capture_rect["roi"],
                name_hint=name_hint,
            )
            output_path = (
                generated_path
                if self._capture_dir == SCREENSHOTS_DIR
                else self._capture_dir / generated_path.name
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            image_path = str(output_path.resolve())
            mark("output_path")
            image.save(image_path, compress_level=3)
            # PIL 直接写文件以免增加一次整图缓冲复制，此段明确包含编码和写盘。
            mark("png_encode_and_write")
            logger.info("Saved screenshot to {}", image_path)
            self._cleanup_old_captures(output_path.parent)
            mark("retention_cleanup")

        result = {
            "image_path": image_path,
            "image_width": image.width,
            "image_height": image.height,
            "roi": capture_rect["roi"],
            "roi_adjusted": capture_rect["roi_adjusted"],
            "capture_purpose": purpose,
            "window_size": {
                "width": capture_rect["window_width"],
                "height": capture_rect["window_height"],
            },
            "capture_timings": {"contract_version": "window_capture_timing_v1",
                "total_ms": round((time.perf_counter() - started) * 1000, 3),
                "steps": capture_stages, "nested_timings_additive": False},
        }
        if visibility.get("occluded_regions"):
            result["capture_visibility"] = {**visibility, "masked": True,
                                             "coordinate_space": "window"}
        return result

    @staticmethod
    def _capture_binding(bound):
        return (bound.handle, bound.process_id, bound.rect.left, bound.rect.top,
                bound.rect.right, bound.rect.bottom)

    def _require_capture_visibility(self, bound, monitor):
        check = getattr(self._window_manager, "validate_bound_capture_visibility", None)
        result = check(bound=bound, rect=monitor, allow_partial=True) if callable(check) else None
        if not isinstance(result, dict) or result.get("allowed") is not True:
            reason = result.get("reason", "capture_visibility_unavailable") if isinstance(result, dict) else "capture_visibility_unavailable"
            raise CaptureVisibilityError(reason)
        return result

    def _resolve_capture_rect(
        self,
        left: int,
        top: int,
        right: int,
        bottom: int,
        roi: Optional[ROIValue],
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

    def _cleanup_old_captures(self, capture_dir: Path | None = None) -> None:
        resolved_capture_dir = capture_dir or self._capture_dir
        protected = _benchmark_protected_screenshot_paths(resolved_capture_dir)
        captures = sorted(
            (path for path in resolved_capture_dir.glob("*.png") if path.resolve() not in protected),
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

    def _wait_after_focus(self) -> None:
        if self._focus_settle_seconds > 0:
            time.sleep(self._focus_settle_seconds)


screenshot_service = ScreenshotService()


def _benchmark_protected_screenshot_paths(capture_dir: Path) -> set[Path]:
    artifact_dir = capture_dir.parent
    project_root = artifact_dir.parent
    benchmark_dir = artifact_dir / "benchmarks"
    protected: set[Path] = set()
    if not benchmark_dir.exists():
        return protected

    def collect(value: Any, key: str = "") -> None:
        if isinstance(value, dict):
            for child_key, child_value in value.items():
                collect(child_value, str(child_key))
            return
        if isinstance(value, list):
            for child in value:
                collect(child, key)
            return
        if key not in {"screenshot_path", "source_image_path"} or not isinstance(value, str) or not value.strip():
            return
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        protected.add(candidate.resolve())

    for manifest_path in benchmark_dir.glob("*.json"):
        try:
            collect(json.loads(manifest_path.read_text(encoding="utf-8-sig")))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to read benchmark screenshot references from {}: {}", manifest_path, exc)
    return protected
