from __future__ import annotations

import time
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from loguru import logger
from PIL import Image

from app.core.runtime_artifacts import VERIFICATION_DIR, build_verification_image_path
from app.core.screenshot import screenshot_service
from app.core.window_manager import window_manager
from app.api.models.request import ROIModel
from app.agent.native_identity import WindowsNativeIdentityReader, validate_native_identity_fact
from app.gate.scroll_evidence import SCROLL_CAPTURE_CONTRACT

CAPTURE_CLOCK_ID = uuid4().hex


def _label_observation_frame(capture, frame_id):
    """每张诊断帧独立标识；缺失原件时不能伪造摘要。"""
    frame = dict(capture or {})
    frame.update(frame_id=frame_id, observation_stage="immediate", render_completion_verified=False)
    path = frame.get("image_path")
    try:
        digest = sha256(Path(path).read_bytes()).hexdigest() if path else None
    except OSError:
        digest = None
    frame.update(sha256=digest, image_hash_status="recorded" if digest else "unavailable")
    return frame

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

    def __init__(self, *, native_identity_reader: Any | None = None) -> None:
        self._verification_dir = VERIFICATION_DIR
        self._native_identity_reader = native_identity_reader

    def capture_pre_action_state(self, roi: Optional[ROIModel] = None, *, action_name: Optional[str] = None, capture_scope_evidence: bool = False) -> dict[str, Any]:
        """Capture minimal state before an action executes."""
        if capture_scope_evidence:
            return self._capture_scope_state(roi=roi, action_name=action_name, purpose="pre_action")
        bound = window_manager.get_bound_window()
        capture = screenshot_service.capture_window(roi=roi, save_image=True, purpose="pre_action", name_hint=action_name)
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

    def _capture_scope_state(self, *, roi: Optional[ROIModel], action_name: Optional[str], purpose: str) -> dict[str, Any]:
        state: dict[str, Any] = {
            "contract_version": SCROLL_CAPTURE_CONTRACT, "captured": False,
            "capture_status": "unavailable", "capture_id": uuid4().hex,
            "capture_clock_id": CAPTURE_CLOCK_ID, "capture_started_ns": time.perf_counter_ns(),
        }

        def unavailable(reason: str, **details: Any) -> dict[str, Any]:
            state.update(captured_at_ns=time.perf_counter_ns(), reason=reason, **details)
            return state

        def geometry(bound: Any) -> dict[str, int] | None:
            rect = getattr(bound, "rect", None)
            if rect is None:
                return None
            return {"x": rect.left, "y": rect.top, "width": rect.right - rect.left, "height": rect.bottom - rect.top}

        if roi is not None:
            return unavailable("full_window_capture_required")
        try:
            bound = window_manager.get_bound_window()
            handle = getattr(bound, "handle", None)
            rect = geometry(bound)
            reader = self._native_identity_reader or WindowsNativeIdentityReader(window_manager=window_manager)
            identity = validate_native_identity_fact(reader.read_identity(handle), target_window_handle=handle) if type(handle) is int else None
            if identity is None:
                return unavailable("capture_identity_unavailable")
            state.update(window_handle=handle, window_title=bound.title, is_active=bound.is_active,
                         window_rect=rect, native_identity=identity)
            capture = screenshot_service.capture_window(
                roi=roi, save_image=True, purpose=purpose, name_hint=action_name, focus_window=False,
            )
            state.update(captured=True, roi=capture.get("roi"), image_path=capture.get("image_path"),
                         viewport_size=capture.get("window_size"))
            after_identity = validate_native_identity_fact(reader.read_identity(handle), target_window_handle=handle)
            after_bound = window_manager.get_bound_window()
            if identity != after_identity or getattr(after_bound, "handle", None) != handle:
                return unavailable("capture_identity_changed")
            if rect is None or geometry(after_bound) != rect:
                return unavailable("capture_geometry_changed")
            if capture.get("window_size") != {key: rect[key] for key in ("width", "height")}:
                return unavailable("capture_viewport_mismatch")
            raw = Path(capture["image_path"]).read_bytes()
            with Image.open(BytesIO(raw)) as image:
                if image.format != "PNG" or image.size != (rect["width"], rect["height"]):
                    return unavailable("capture_image_geometry_invalid")
                image.load()
            state["image_sha256"] = sha256(raw).hexdigest()
        except Exception as error:
            # 捕获边界错误必须显式返回不可用，不能伪造截图或范围成功。
            return unavailable("capture_failed", error_type=type(error).__name__)
        state.update(capture_status="observed", captured_at_ns=time.perf_counter_ns())
        return state

    def verify_action(
        self,
        action_name: str,
        *,
        roi: Optional[ROIModel] = None,
        before_state: Optional[dict[str, Any]] = None,
        click_result: Optional[dict[str, Any]] = None,
        wait_ms: int = 250,
        capture_scope_evidence: bool = False,
        judged_by_agent: bool = False,
    ) -> dict[str, Any]:
        """Verify an action using before/after screenshots plus focus/cursor checks."""
        logger.info("Verifying action: {}", action_name)
        time.sleep(max(0, wait_ms) / 1000.0)

        after_capture = self._capture_scope_state(roi=roi, action_name=action_name, purpose="post_action") if capture_scope_evidence else screenshot_service.capture_window(
            roi=roi, save_image=True, purpose="post_action", name_hint=action_name,
        )
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
        # Agent 判定模式只返回观察事实，连原始日志也不把启发式信号记成成功。
        verified = None if capture_scope_evidence or judged_by_agent else bool(diff_changed) or bool(cursor_moved and foreground_consistent)

        result = {
            "verified": verified,
            "action_name": action_name,
            "before": before_state,
            "after": after_capture if capture_scope_evidence else {
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
        if judged_by_agent:
            result.update(verification_status="awaiting_agent_review", judged_by="agent",
                          automatic_retry_allowed=False)
            result["before"] = _label_observation_frame(result["before"], "before_immediate")
            result["after"] = _label_observation_frame(result["after"], "after_immediate")
            result["diff"] = {**result["diff"], "frame_pair": "immediate",
                "evidence_role": "diagnostic_not_agent_review",
                "source_frames": {key: {field: result[key].get(field)
                    for field in ("frame_id", "image_path", "sha256")}
                    for key in ("before", "after")}}
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
        diff_path = build_verification_image_path(action_name=action_name, suffix="diff")
        diff_path.parent.mkdir(parents=True, exist_ok=True)
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
