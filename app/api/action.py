from __future__ import annotations

import json
import re
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter

from app.actions.known_action_runner import run_known_action
from app.core.action_registry import action_registry
from app.core.input_controller import input_controller
from app.core.ocr_service import ocr_service
from app.core.runtime_artifacts import RuntimeTimer, new_learned_instruction_id, write_trace
from app.core.screenshot import screenshot_service
from app.core.verifier import verifier
from app.core.window_manager import window_manager
from app.models.request import (
    ClickTextRequest,
    ExecuteConfirmedPointRequest,
    ExecuteRecognitionPlanRequest,
    TypeTextRequest,
    VisionRecognitionPlanOverlayRequestModel,
    VisionRecognitionPlanRequestModel,
)
from app.models.response import APIResponse, ActionResultData, ErrorModel
from app.schemas.action_target import ActionTarget
from app.schemas.state import AppState
from app.schemas.validator_profile import ValidatorProfile
from modules.ocr.matching import bbox_center, find_text_matches
from modules.region.geometry import (
    generate_zone_points as generate_zone_points_module,
    locate_mouse_tester_panel as locate_mouse_tester_panel_module,
    normalized_point as normalized_point_module,
    window_rect as window_rect_module,
    window_size_bucket as window_size_bucket_module,
)
from modules.validation.counter import evaluate_counter_result as evaluate_counter_result_module

try:
    from PIL import Image
except Exception:  # pragma: no cover - depends on optional runtime imaging support
    Image = None  # type: ignore[assignment]

router = APIRouter(prefix="/action", tags=["action"])

CACHE_DIR = Path("logs/region-click-cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CASES_DIR = Path("logs/region-click-cases")
CASES_DIR.mkdir(parents=True, exist_ok=True)
APPROVED_PLANS_DIR = Path("logs/approved-plans")
APPROVED_PLANS_DIR.mkdir(parents=True, exist_ok=True)
APPROVED_PLAN_TTL_SECONDS = 300
LEARNED_INSTRUCTIONS_DIR = Path("artifacts/local-learning/instructions")
LEARNED_INSTRUCTIONS_DIR.mkdir(parents=True, exist_ok=True)
LEGACY_LEARNED_INSTRUCTIONS_DIR = Path("logs/learned-instructions")

RegionClickPanelLocator = Callable[[Any], dict[str, Any]]
RegionClickZoneResolver = Callable[[dict[str, Any]], dict[str, Any]]
RegionClickPointStrategy = Callable[[dict[str, Any], Optional[dict[str, float]]], list[dict[str, Any]]]
RegionClickValidator = Callable[[list[str], list[str]], dict[str, Any]]


def _run_recognition_plan_for_execution(request: VisionRecognitionPlanRequestModel) -> APIResponse:
    from app.api.vision import recognition_plan

    return recognition_plan(request)


def _render_recognition_plan_overlay_for_execution(trace_path: str) -> Optional[dict[str, Any]]:
    from app.api.vision import render_recognition_plan_overlay_route

    response = render_recognition_plan_overlay_route(
        VisionRecognitionPlanOverlayRequestModel(
            trace_path=trace_path,
            include_rejected=True,
            include_points=True,
            label_candidates=True,
            label_reasons=True,
        )
    )
    if not response.success or not response.data:
        return None
    return response.data.get("result")


def _extract_action_point(plan: dict[str, Any]) -> Optional[dict[str, int]]:
    point = (plan.get("pre_click_decision") or {}).get("selected_click_point")
    if not point:
        return None
    return {"x": int(point["x"]), "y": int(point["y"])}


def _should_verify_mouse_tester_semantics(request: ExecuteRecognitionPlanRequest, plan: dict[str, Any]) -> bool:
    values = [
        request.app_name or "",
        request.state_hint or "",
        plan.get("goal") or "",
        (plan.get("parse_result") or {}).get("vision_regions", {}).get("screen_summary") or "",
    ]
    normalized = " ".join(str(value).casefold() for value in values)
    return "mousetester" in normalized or "mouse tester" in normalized or "鼠标" in normalized


def _verify_mouse_tester_post_click_semantics(
    *,
    request: ExecuteRecognitionPlanRequest,
    plan: dict[str, Any],
    generic_verification: dict[str, Any],
) -> dict[str, Any]:
    before_path = ((generic_verification.get("before") or {}).get("image_path"))
    after_path = ((generic_verification.get("after") or {}).get("image_path"))
    recommended = plan.get("recommended_target") or {}
    target_bbox = _target_bbox_from_recommended(recommended)
    if not before_path or not after_path or target_bbox is None:
        return {
            "applicable": True,
            "verified": False,
            "reason": "missing_before_after_or_target_bbox",
            "before_path": before_path,
            "after_path": after_path,
            "target_bbox": target_bbox,
        }

    image_size = _image_size_from_plan(plan)
    verification_bbox = _expand_bbox(target_bbox, pad_x=90, pad_y=55, image_size=image_size)
    before_texts = _ocr_texts_in_bbox(before_path, verification_bbox)
    after_texts = _ocr_texts_in_bbox(after_path, verification_bbox)
    expected_values = [
        request.goal,
        str(recommended.get("label") or ""),
        str(recommended.get("text") or ""),
    ]
    before_target_present = _texts_contain_expected(before_texts, expected_values)
    after_target_present = _texts_contain_expected(after_texts, expected_values)
    localized_text_changed = _text_signature(before_texts) != _text_signature(after_texts)
    diff_overlaps_target = _diff_overlaps_bbox(generic_verification.get("diff") or {}, verification_bbox)
    target_text_replaced = bool(before_target_present and not after_target_present)
    verified = bool(diff_overlaps_target and localized_text_changed and (target_text_replaced or before_target_present))

    return {
        "applicable": True,
        "verified": verified,
        "profile": "mousetester_target_text_change_v1",
        "target_bbox": target_bbox,
        "verification_bbox": verification_bbox,
        "before_path": before_path,
        "after_path": after_path,
        "before_texts": before_texts,
        "after_texts": after_texts,
        "before_target_present": before_target_present,
        "after_target_present": after_target_present,
        "target_text_replaced": target_text_replaced,
        "localized_text_changed": localized_text_changed,
        "diff_overlaps_target": diff_overlaps_target,
        "reasons": _semantic_verification_reasons(
            before_target_present=before_target_present,
            after_target_present=after_target_present,
            target_text_replaced=target_text_replaced,
            localized_text_changed=localized_text_changed,
            diff_overlaps_target=diff_overlaps_target,
        ),
    }


def _target_bbox_from_recommended(recommended: dict[str, Any]) -> Optional[dict[str, int]]:
    source = recommended.get("refined_bbox") or (recommended.get("element") or {}).get("bbox")
    if not source:
        return None
    return {
        "x": int(source.get("x", 0)),
        "y": int(source.get("y", 0)),
        "width": int(source.get("width", source.get("w", 0))),
        "height": int(source.get("height", source.get("h", 0))),
    }


def _image_size_from_plan(plan: dict[str, Any]) -> Optional[dict[str, int]]:
    image_size = (((plan.get("parse_result") or {}).get("vision_regions") or {}).get("image_size") or {})
    width = image_size.get("width")
    height = image_size.get("height")
    if width and height:
        return {"width": int(width), "height": int(height)}
    return None


def _expand_bbox(
    bbox: dict[str, int],
    *,
    pad_x: int,
    pad_y: int,
    image_size: Optional[dict[str, int]] = None,
) -> dict[str, int]:
    x1 = int(bbox["x"]) - int(pad_x)
    y1 = int(bbox["y"]) - int(pad_y)
    x2 = int(bbox["x"]) + int(bbox["width"]) + int(pad_x)
    y2 = int(bbox["y"]) + int(bbox["height"]) + int(pad_y)
    x1 = max(0, x1)
    y1 = max(0, y1)
    if image_size:
        x2 = min(int(image_size["width"]), x2)
        y2 = min(int(image_size["height"]), y2)
    return {"x": x1, "y": y1, "width": max(1, x2 - x1), "height": max(1, y2 - y1)}


def _ocr_texts_in_bbox(image_path: str, bbox: dict[str, int]) -> list[dict[str, Any]]:
    result = ocr_service.scan_image(image_path)
    texts: list[dict[str, Any]] = []
    for match in result.matches:
        match_bbox = match.bbox.to_dict()
        center = {
            "x": int(match_bbox["x"] + match_bbox["width"] / 2),
            "y": int(match_bbox["y"] + match_bbox["height"] / 2),
        }
        if _point_in_rect(center, bbox):
            texts.append({"text": match.text, "score": float(match.score), "bbox": match_bbox})
    texts.sort(key=lambda item: (item["bbox"]["y"], item["bbox"]["x"]))
    return texts


def _texts_contain_expected(texts: list[dict[str, Any]], expected_values: list[str]) -> bool:
    expected = [_normalize_semantic_text(value) for value in expected_values if _normalize_semantic_text(value)]
    for item in texts:
        normalized_text = _normalize_semantic_text(str(item.get("text") or ""))
        if any(_semantic_text_similarity(normalized_text, value) >= 0.75 for value in expected):
            return True
    return False


def _text_signature(texts: list[dict[str, Any]]) -> list[str]:
    return [_normalize_semantic_text(str(item.get("text") or "")) for item in texts]


def _diff_overlaps_bbox(diff: dict[str, Any], bbox: dict[str, int]) -> bool:
    for region in diff.get("regions") or []:
        region_bbox = {
            "x": int(region.get("x", 0)),
            "y": int(region.get("y", 0)),
            "width": int(region.get("width", region.get("w", 0))),
            "height": int(region.get("height", region.get("h", 0))),
        }
        if _rects_intersect(region_bbox, bbox):
            return True
    return False


def _semantic_verification_reasons(
    *,
    before_target_present: bool,
    after_target_present: bool,
    target_text_replaced: bool,
    localized_text_changed: bool,
    diff_overlaps_target: bool,
) -> list[str]:
    reasons: list[str] = []
    reasons.append("before_target_present" if before_target_present else "before_target_missing")
    reasons.append("after_target_still_present" if after_target_present else "after_target_absent")
    if target_text_replaced:
        reasons.append("target_text_replaced")
    if localized_text_changed:
        reasons.append("localized_text_changed")
    if diff_overlaps_target:
        reasons.append("diff_overlaps_target")
    else:
        reasons.append("diff_did_not_overlap_target")
    return reasons


def _point_in_rect(point: dict[str, int], rect: dict[str, int]) -> bool:
    return (
        int(rect["x"]) <= int(point["x"]) <= int(rect["x"]) + int(rect["width"])
        and int(rect["y"]) <= int(point["y"]) <= int(rect["y"]) + int(rect["height"])
    )


def _rects_intersect(left: dict[str, int], right: dict[str, int]) -> bool:
    left_x2 = int(left["x"]) + int(left["width"])
    left_y2 = int(left["y"]) + int(left["height"])
    right_x2 = int(right["x"]) + int(right["width"])
    right_y2 = int(right["y"]) + int(right["height"])
    return not (
        left_x2 < int(right["x"])
        or right_x2 < int(left["x"])
        or left_y2 < int(right["y"])
        or right_y2 < int(left["y"])
    )


def _semantic_text_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if min(len(left), len(right)) >= 3 and (left in right or right in left):
        return 0.9
    return SequenceMatcher(None, left, right).ratio()


def _normalize_semantic_text(value: str) -> str:
    normalized = str(value or "").casefold()
    normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", normalized)
    return " ".join(normalized.split())


def _execution_attempt_verified(
    *,
    request: ExecuteRecognitionPlanRequest,
    post_click_verification: dict[str, Any],
    semantic_post_click_verification: dict[str, Any],
) -> bool:
    if not request.enable_post_click_verification:
        return True
    if semantic_post_click_verification.get("applicable"):
        return bool(post_click_verification.get("verified")) and bool(semantic_post_click_verification.get("verified"))
    return bool(post_click_verification.get("verified"))


def _retry_allowed_after_attempt(
    *,
    request: ExecuteRecognitionPlanRequest,
    pre_click: dict[str, Any],
    attempt_index: int,
    attempt_verified: bool,
) -> tuple[bool, str]:
    if attempt_verified:
        return False, "attempt_verified"
    if not request.enable_post_click_verification:
        return False, "post_click_verification_disabled"
    if attempt_index >= int(request.max_execution_attempts):
        return False, "max_execution_attempts_reached"
    if not pre_click.get("allowed"):
        return False, "pre_click_not_allowed"

    selected_candidate_id = pre_click.get("selected_candidate_id")
    selected_decision = None
    for item in pre_click.get("candidate_decisions") or []:
        if item.get("candidate_id") == selected_candidate_id:
            selected_decision = item
            break
    selected_reasons = set((selected_decision or {}).get("reasons") or [])
    blocked_reasons = {
        "candidate_goal_text_mismatch",
        "local_ocr_text_mismatch",
        "candidate_not_eligible",
        "interaction_policy_blocked",
        "ad_like_candidate",
        "refined_point_outside_candidate_bbox",
    }
    if selected_reasons & blocked_reasons:
        return False, "selected_candidate_not_retry_safe"
    return True, "verification_failed_retry_safe"


def _window_rect(bound: Any) -> dict[str, int]:
    return window_rect_module(bound)


def _window_size_bucket(rect: dict[str, int]) -> str:
    return window_size_bucket_module(rect)


def _locate_mouse_tester_panel(bound: Any) -> dict[str, Any]:
    return locate_mouse_tester_panel_module(bound)


def _generate_zone_points(zone: dict[str, Any], preferred_norm_point: Optional[dict[str, float]] = None) -> list[dict[str, Any]]:
    return generate_zone_points_module(zone, preferred_norm_point)


def _counter_value(texts: list[str]) -> Optional[int]:
    from modules.validation.counter import counter_value

    return counter_value(texts)


def _evaluate_counter_result(before_numeric_texts: list[str], after_numeric_texts: list[str]) -> dict[str, Any]:
    return evaluate_counter_result_module(before_numeric_texts, after_numeric_texts)


def _normalized_point(zone: dict[str, Any], point: dict[str, Any]) -> dict[str, float]:
    return normalized_point_module(zone, point)


def _load_region_click_memory(case_name: str, bucket: str) -> Optional[dict[str, Any]]:
    path = CACHE_DIR / f"{case_name}-{bucket}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_region_click_memory(case_name: str, bucket: str, payload: dict[str, Any]) -> str:
    path = CACHE_DIR / f"{case_name}-{bucket}.json"
    payload = {**payload, "updated_at": datetime.now(timezone.utc).isoformat()}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path.resolve())


def _capture_bound_window_image(bound: Any, name_prefix: str) -> Optional[str]:
    capture = screenshot_service.capture_window(save_image=True, purpose="state_snapshot", name_hint=name_prefix)
    image_path = capture.get("image_path")
    if not image_path:
        return None
    return str(Path(image_path).resolve())


def _bound_window_snapshot(bound: Any) -> dict[str, Any]:
    rect = _window_rect(bound)
    return {
        "handle": int(bound.handle),
        "title": bound.title,
        "process_id": getattr(bound, "process_id", None),
        "process_name": getattr(bound, "process_name", None),
        "rect": rect,
    }


def _approved_plan_path(approved_plan_id: str) -> Path:
    safe_id = re.sub(r"[^a-zA-Z0-9_.-]+", "", approved_plan_id)
    if not safe_id:
        raise ValueError("approved_plan_id is empty or invalid")
    return APPROVED_PLANS_DIR / f"{safe_id}.json"


def _learned_instruction_path(learned_instruction_id: str) -> Path:
    safe_id = re.sub(r"[^a-zA-Z0-9_.-]+", "", learned_instruction_id)
    if not safe_id:
        raise ValueError("learned_instruction_id is empty or invalid")
    return LEARNED_INSTRUCTIONS_DIR / safe_id / "learned_instruction.json"


def _legacy_learned_instruction_path(learned_instruction_id: str) -> Path:
    safe_id = re.sub(r"[^a-zA-Z0-9_.-]+", "", learned_instruction_id)
    if not safe_id:
        raise ValueError("learned_instruction_id is empty or invalid")
    return LEGACY_LEARNED_INSTRUCTIONS_DIR / f"{safe_id}.json"


def _instruction_learning_enabled(request: ExecuteRecognitionPlanRequest) -> bool:
    write_policy = request.write_policy.model_dump() if hasattr(request.write_policy, "model_dump") else {}
    return bool(write_policy.get("element_memory", True)) and str(request.learning_mode or "").strip().casefold() in {"instruction", "instruction_learning"}


def _execute_trace_enabled(request: ExecuteRecognitionPlanRequest) -> bool:
    write_policy = request.write_policy.model_dump() if hasattr(request.write_policy, "model_dump") else {}
    return write_policy.get("trace", True) is not False


def _write_execute_trace_if_enabled(request: ExecuteRecognitionPlanRequest, **kwargs: Any) -> str | None:
    if not _execute_trace_enabled(request):
        return None
    return write_trace(**kwargs)


def _save_approved_plan(
    *,
    request: ExecuteRecognitionPlanRequest,
    bound: Any,
    image_path: str,
    live_capture: Optional[dict[str, Any]],
    plan: dict[str, Any],
    pre_click: dict[str, Any],
    selected_point: dict[str, Any],
    plan_trace_path: Optional[str],
    overlay: Optional[dict[str, Any]],
) -> dict[str, Any]:
    approved_plan_id = uuid.uuid4().hex
    created_at = datetime.now(timezone.utc)
    expires_at = created_at + timedelta(seconds=APPROVED_PLAN_TTL_SECONDS)
    record = {
        "contract_version": "approved_recognition_plan_v1",
        "approved_plan_id": approved_plan_id,
        "created_at": created_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "ttl_seconds": APPROVED_PLAN_TTL_SECONDS,
        "goal": request.goal,
        "task": request.task,
        "app_name": request.app_name,
        "state_hint": request.state_hint,
        "provider_mode": request.provider_mode,
        "top_k": request.top_k,
        "request_metadata": request.metadata,
        "bound_window": _bound_window_snapshot(bound),
        "image_path": image_path,
        "live_capture": live_capture,
        "recognition_plan": plan,
        "recognition_plan_trace_path": plan_trace_path,
        "recognition_plan_overlay": overlay,
        "pre_click_decision": pre_click,
        "selected_click_point": selected_point,
    }
    path = _approved_plan_path(approved_plan_id)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "approved_plan_id": approved_plan_id,
        "approved_plan_path": str(path.resolve()),
        "expires_at": expires_at.isoformat(),
        "ttl_seconds": APPROVED_PLAN_TTL_SECONDS,
    }


def _load_approved_plan(approved_plan_id: str) -> dict[str, Any]:
    path = _approved_plan_path(approved_plan_id)
    if not path.exists():
        raise ValueError(f"approved_plan_id not found: {approved_plan_id}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("contract_version") != "approved_recognition_plan_v1":
        raise ValueError("approved plan has an invalid contract")
    return payload


def _validate_approved_plan_reuse(
    *,
    request: ExecuteRecognitionPlanRequest,
    bound: Any,
    record: dict[str, Any],
    selected_point: dict[str, Any],
) -> dict[str, Any]:
    expires_at = datetime.fromisoformat(str(record.get("expires_at")))
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if now > expires_at:
        raise ValueError("approved_plan_expired")
    if request.goal != record.get("goal"):
        raise ValueError("approved_plan_goal_mismatch")

    current_window = _bound_window_snapshot(bound)
    approved_window = record.get("bound_window") if isinstance(record.get("bound_window"), dict) else {}
    if int(current_window.get("handle") or 0) != int(approved_window.get("handle") or 0):
        raise ValueError("approved_plan_window_handle_mismatch")

    current_rect = current_window.get("rect") or {}
    approved_rect = approved_window.get("rect") or {}
    current_size = {"width": int(current_rect.get("width") or 0), "height": int(current_rect.get("height") or 0)}
    approved_size = {"width": int(approved_rect.get("width") or 0), "height": int(approved_rect.get("height") or 0)}
    if current_size != approved_size:
        raise ValueError("approved_plan_window_size_mismatch")

    if not _point_in_rect(selected_point, {"x": 0, "y": 0, "width": current_size["width"] - 1, "height": current_size["height"] - 1}):
        raise ValueError("approved_plan_point_outside_window")

    return {
        "contract_version": "approved_plan_reuse_validation_v1",
        "approved_plan_id": record.get("approved_plan_id"),
        "valid": True,
        "checked_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "current_window": current_window,
        "approved_window": approved_window,
        "selected_click_point": selected_point,
    }


def _copy_learning_file(source: Any, destination: Path, *, missing_sources: list[str]) -> Optional[str]:
    if not source:
        return None
    source_path = Path(str(source))
    if not source_path.exists() or not source_path.is_file():
        missing_sources.append(str(source_path))
        return None
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination)
    return str(destination.resolve())


def _learning_target_bbox(plan: dict[str, Any], selected_point: dict[str, Any]) -> dict[str, int]:
    target_bbox = _target_bbox_from_recommended(plan.get("recommended_target") or {})
    if target_bbox is not None:
        return target_bbox
    x = int(selected_point.get("x", 0))
    y = int(selected_point.get("y", 0))
    return {"x": max(0, x - 48), "y": max(0, y - 48), "width": 96, "height": 96}


def _crop_learning_target(
    *,
    source_image_path: Any,
    destination: Path,
    target_bbox: dict[str, int],
    missing_sources: list[str],
) -> Optional[str]:
    if Image is None:
        return None
    if not source_image_path:
        return None
    source_path = Path(str(source_image_path))
    if not source_path.exists() or not source_path.is_file():
        missing_sources.append(str(source_path))
        return None
    try:
        with Image.open(source_path) as image:
            width, height = image.size
            x1 = max(0, int(target_bbox["x"]))
            y1 = max(0, int(target_bbox["y"]))
            x2 = min(width, x1 + max(1, int(target_bbox["width"])))
            y2 = min(height, y1 + max(1, int(target_bbox["height"])))
            if x2 <= x1 or y2 <= y1:
                return None
            destination.parent.mkdir(parents=True, exist_ok=True)
            image.crop((x1, y1, x2, y2)).save(destination)
            return str(destination.resolve())
    except Exception:
        return None


def _persist_learned_instruction_assets(
    *,
    learned_instruction_id: str,
    bundle_dir: Path,
    image_path: str,
    plan: dict[str, Any],
    selected_point: dict[str, Any],
    post_click_verification: dict[str, Any],
) -> dict[str, Any]:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    missing_sources: list[str] = []
    before_path = ((post_click_verification.get("before") or {}).get("image_path"))
    after_path = ((post_click_verification.get("after") or {}).get("image_path"))
    diff_path = ((post_click_verification.get("diff") or {}).get("diff_image_path"))
    target_bbox = _learning_target_bbox(plan, selected_point)
    source_for_crop = before_path or image_path

    assets = {
        "contract_version": "learned_instruction_artifacts_v1",
        "learned_instruction_id": learned_instruction_id,
        "bundle_dir": str(bundle_dir.resolve()),
        "source_image_path": _copy_learning_file(image_path, bundle_dir / "source_window.png", missing_sources=missing_sources),
        "pre_action_image_path": _copy_learning_file(before_path, bundle_dir / "pre_action.png", missing_sources=missing_sources),
        "post_action_image_path": _copy_learning_file(after_path, bundle_dir / "post_action.png", missing_sources=missing_sources),
        "diff_image_path": _copy_learning_file(diff_path, bundle_dir / "post_action_diff.png", missing_sources=missing_sources),
        "target_crop_path": _crop_learning_target(
            source_image_path=source_for_crop,
            destination=bundle_dir / "target_crop.png",
            target_bbox=target_bbox,
            missing_sources=missing_sources,
        ),
        "target_bbox": target_bbox,
        "selected_click_point": selected_point,
        "missing_sources": sorted(set(missing_sources)),
    }
    return assets


def _save_learned_instruction(
    *,
    request: ExecuteRecognitionPlanRequest,
    bound: Any,
    image_path: str,
    live_capture: Optional[dict[str, Any]],
    plan: dict[str, Any],
    pre_click: dict[str, Any],
    selected_point: dict[str, Any],
    click_result: dict[str, Any],
    post_click_verification: dict[str, Any],
    semantic_post_click_verification: dict[str, Any],
    plan_trace_path: Optional[str],
    action_trace_path: Optional[str],
) -> dict[str, Any]:
    learned_instruction_id = new_learned_instruction_id()
    created_at = datetime.now(timezone.utc)
    path = _learned_instruction_path(learned_instruction_id)
    bundle_dir = path.parent
    learning_artifacts = _persist_learned_instruction_assets(
        learned_instruction_id=learned_instruction_id,
        bundle_dir=bundle_dir,
        image_path=image_path,
        plan=plan,
        selected_point=selected_point,
        post_click_verification=post_click_verification,
    )
    record = {
        "contract_version": "learned_instruction_v1",
        "learned_instruction_id": learned_instruction_id,
        "created_at": created_at.isoformat(),
        "instruction": {
            "original": request.goal,
            "normalized": request.goal,
        },
        "task": request.task,
        "app_name": request.app_name,
        "state_hint": request.state_hint,
        "provider_mode": request.provider_mode,
        "top_k": request.top_k,
        "request_metadata": request.metadata,
        "bound_window": _bound_window_snapshot(bound),
        "image_path": image_path,
        "live_capture": live_capture,
        "learning_artifacts": learning_artifacts,
        "recognition_plan": plan,
        "recognition_plan_trace_path": plan_trace_path,
        "action_trace_path": action_trace_path,
        "pre_click_decision": pre_click,
        "selected_click_point": selected_point,
        "click_result": click_result,
        "post_click_verification": post_click_verification,
        "semantic_post_click_verification": semantic_post_click_verification,
        "reuse_policy": {
            "mode": "same_window_exact",
            "match_goal": True,
            "match_app_name": True,
            "match_window_handle": True,
            "match_window_size": True,
            "fallback_to_model": True,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "learned_instruction_id": learned_instruction_id,
        "learned_instruction_path": str(path.resolve()),
        "learned_instruction_bundle_dir": str(path.parent.resolve()),
        "learned_instruction_artifacts": learning_artifacts,
        "learning_mode": "instruction",
    }


def _load_learned_instruction(learned_instruction_id: str) -> dict[str, Any]:
    path = _learned_instruction_path(learned_instruction_id)
    if not path.exists():
        path = _legacy_learned_instruction_path(learned_instruction_id)
    if not path.exists():
        raise ValueError(f"learned_instruction_id not found: {learned_instruction_id}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("contract_version") != "learned_instruction_v1":
        raise ValueError("learned instruction has an invalid contract")
    return payload


def _validate_learned_instruction_reuse(
    *,
    request: ExecuteRecognitionPlanRequest,
    bound: Any,
    record: dict[str, Any],
    selected_point: dict[str, Any],
) -> dict[str, Any]:
    instruction = record.get("instruction") if isinstance(record.get("instruction"), dict) else {}
    if request.goal != instruction.get("original"):
        raise ValueError("learned_instruction_goal_mismatch")
    if request.app_name and record.get("app_name") and request.app_name != record.get("app_name"):
        raise ValueError("learned_instruction_app_mismatch")

    current_window = _bound_window_snapshot(bound)
    learned_window = record.get("bound_window") if isinstance(record.get("bound_window"), dict) else {}
    if int(current_window.get("handle") or 0) != int(learned_window.get("handle") or 0):
        raise ValueError("learned_instruction_window_handle_mismatch")

    current_rect = current_window.get("rect") or {}
    learned_rect = learned_window.get("rect") or {}
    current_size = {"width": int(current_rect.get("width") or 0), "height": int(current_rect.get("height") or 0)}
    learned_size = {"width": int(learned_rect.get("width") or 0), "height": int(learned_rect.get("height") or 0)}
    if current_size != learned_size:
        raise ValueError("learned_instruction_window_size_mismatch")

    if not _point_in_rect(selected_point, {"x": 0, "y": 0, "width": current_size["width"] - 1, "height": current_size["height"] - 1}):
        raise ValueError("learned_instruction_point_outside_window")

    return {
        "contract_version": "learned_instruction_reuse_validation_v1",
        "learned_instruction_id": record.get("learned_instruction_id"),
        "valid": True,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "reuse_policy": record.get("reuse_policy"),
        "current_window": current_window,
        "learned_window": learned_window,
        "selected_click_point": selected_point,
    }


@router.post("/execute_recognition_plan", response_model=APIResponse)
def execute_recognition_plan(request: ExecuteRecognitionPlanRequest) -> APIResponse:
    timer = RuntimeTimer()
    bound = window_manager.get_bound_window()
    live_capture: Optional[dict[str, Any]] = None

    def attach_timings(result: dict[str, Any]) -> dict[str, Any]:
        result["timings"] = timer.to_dict()
        return result

    if request.approved_plan_id and request.dry_run:
        timings = timer.to_dict()
        return APIResponse(
            success=False,
            message="approved_plan_id can only be used for real execution",
            data={"approved_plan_id": request.approved_plan_id, "timings": timings},
            error=ErrorModel(code="approved_plan_dry_run_not_allowed", details="First create the approved plan with dry_run=true, then reuse it with dry_run=false"),
        )

    if request.approved_plan_id and request.learned_instruction_id:
        timings = timer.to_dict()
        return APIResponse(
            success=False,
            message="Only one reuse source can be selected",
            data={"approved_plan_id": request.approved_plan_id, "learned_instruction_id": request.learned_instruction_id, "timings": timings},
            error=ErrorModel(code="reuse_source_conflict", details="Use either approved_plan_id or learned_instruction_id, not both"),
        )

    learned_instruction_reuse_validation: dict[str, Any] | None = None
    learned_record: dict[str, Any] | None = None
    if request.learned_instruction_id:
        if bound is None:
            timings = timer.to_dict()
            return APIResponse(
                success=False,
                message="No bound window is currently available",
                data={"timings": timings},
                error=ErrorModel(
                    code="no_bound_window",
                    details="Bind the target window before reusing a learned instruction",
                ),
            )
        try:
            with timer.step("load_learned_instruction"):
                learned_record = _load_learned_instruction(request.learned_instruction_id)
            plan = learned_record["recognition_plan"]
            pre_click = learned_record.get("pre_click_decision") or {}
            selected_point = learned_record.get("selected_click_point")
            if not isinstance(selected_point, dict):
                raise ValueError("learned_instruction_missing_selected_click_point")
            with timer.step("validate_learned_instruction_reuse"):
                learned_instruction_reuse_validation = _validate_learned_instruction_reuse(
                    request=request,
                    bound=bound,
                    record=learned_record,
                    selected_point=selected_point,
                )
            image_path = str(learned_record.get("image_path") or "")
            live_capture = learned_record.get("live_capture") if isinstance(learned_record.get("live_capture"), dict) else None
            plan_trace_path = learned_record.get("recognition_plan_trace_path") or plan.get("trace_path")
            overlay = None
        except Exception as exc:
            timings = timer.to_dict()
            trace_path = _write_execute_trace_if_enabled(
                request,
                category="actions",
                operation="execute_recognition_plan",
                payload={
                    "success": False,
                    "request": request.model_dump(),
                    "learned_instruction_id": request.learned_instruction_id,
                    "failure_reason": "learned_instruction_reuse_failed",
                    "error": str(exc),
                    "timings": timings,
                },
                name_hint=request.app_name or "recognition_plan",
            )
            return APIResponse(
                success=False,
                message="Learned instruction could not be reused",
                data={"trace_path": trace_path, "learned_instruction_id": request.learned_instruction_id, "timings": timings},
                error=ErrorModel(code="learned_instruction_reuse_failed", details=str(exc)),
            )
        execution_path = {
            "vision_model_used": False,
            "page_structure_used": False,
            "candidate_rank_used": False,
            "narrow_search_used": False,
            "pre_click_decision_used": True,
            "post_click_verification_used": bool(request.enable_post_click_verification and not request.dry_run),
            "coordinate_source": "learned_instruction_v1.selected_click_point",
            "selection_source": "learned_instruction_v1",
            "approved_plan_reused": False,
            "recognition_plan_reused": True,
            "instruction_learning_reused": True,
            "action_executed": False,
            "dry_run": bool(request.dry_run),
            "retry_policy_used": True,
            "max_execution_attempts": int(request.max_execution_attempts),
        }
    approval_reuse_validation: dict[str, Any] | None = None
    if request.approved_plan_id:
        if bound is None:
            timings = timer.to_dict()
            return APIResponse(
                success=False,
                message="No bound window is currently available",
                data={"timings": timings},
                error=ErrorModel(
                    code="no_bound_window",
                    details="Bind the target window before reusing an approved recognition plan",
                ),
            )
        try:
            with timer.step("load_approved_plan"):
                approved_record = _load_approved_plan(request.approved_plan_id)
            plan = approved_record["recognition_plan"]
            pre_click = approved_record.get("pre_click_decision") or {}
            selected_point = approved_record.get("selected_click_point")
            if not isinstance(selected_point, dict):
                raise ValueError("approved_plan_missing_selected_click_point")
            with timer.step("validate_approved_plan_reuse"):
                approval_reuse_validation = _validate_approved_plan_reuse(
                    request=request,
                    bound=bound,
                    record=approved_record,
                    selected_point=selected_point,
                )
            image_path = str(approved_record.get("image_path") or "")
            live_capture = approved_record.get("live_capture") if isinstance(approved_record.get("live_capture"), dict) else None
            plan_trace_path = approved_record.get("recognition_plan_trace_path") or plan.get("trace_path")
            overlay = approved_record.get("recognition_plan_overlay") if isinstance(approved_record.get("recognition_plan_overlay"), dict) else None
        except Exception as exc:
            timings = timer.to_dict()
            trace_path = _write_execute_trace_if_enabled(
                request,
                category="actions",
                operation="execute_recognition_plan",
                payload={
                    "success": False,
                    "request": request.model_dump(),
                    "approved_plan_id": request.approved_plan_id,
                    "failure_reason": "approved_plan_reuse_failed",
                    "error": str(exc),
                    "timings": timings,
                },
                name_hint=request.app_name or "recognition_plan",
            )
            return APIResponse(
                success=False,
                message="Approved recognition plan could not be reused",
                data={"trace_path": trace_path, "approved_plan_id": request.approved_plan_id, "timings": timings},
                error=ErrorModel(code="approved_plan_reuse_failed", details=str(exc)),
            )
        execution_path = {
            "vision_model_used": False,
            "page_structure_used": False,
            "candidate_rank_used": False,
            "narrow_search_used": False,
            "pre_click_decision_used": True,
            "post_click_verification_used": bool(request.enable_post_click_verification),
            "coordinate_source": "approved_plan_v1.selected_click_point",
            "selection_source": "approved_recognition_plan_v1",
            "approved_plan_reused": True,
            "recognition_plan_reused": True,
            "action_executed": False,
            "dry_run": False,
            "retry_policy_used": True,
            "max_execution_attempts": int(request.max_execution_attempts),
        }
    elif not request.learned_instruction_id:
        if request.capture_live:
            if bound is None:
                timings = timer.to_dict()
                return APIResponse(
                    success=False,
                    message="No bound window is currently available",
                    data={"timings": timings},
                    error=ErrorModel(
                        code="no_bound_window",
                        details="Bind the MouseTester window before calling /action/execute_recognition_plan with live capture",
                    ),
                )
            try:
                with timer.step("capture_live_window"):
                    live_capture = screenshot_service.capture_window(
                        save_image=True,
                        purpose="recognition_plan_execution",
                        name_hint=request.app_name or "recognition_plan",
                    )
            except Exception as exc:
                timings = timer.to_dict()
                trace_path = _write_execute_trace_if_enabled(
                    request,
                    category="actions",
                    operation="execute_recognition_plan",
                    payload={"success": False, "request": request.model_dump(), "error": str(exc), "timings": timings},
                    name_hint=request.app_name or "recognition_plan",
                )
                return APIResponse(
                    success=False,
                    message="Live capture failed",
                    data={"trace_path": trace_path, "timings": timings},
                    error=ErrorModel(code="live_capture_failed", details=str(exc)),
                )
            image_path = str(Path(str(live_capture["image_path"])).resolve())
        elif request.image_path:
            with timer.step("use_saved_image_source"):
                image_path = request.image_path
            if not request.allow_saved_image_execution and not request.dry_run:
                timings = timer.to_dict()
                trace_path = _write_execute_trace_if_enabled(
                    request,
                    category="actions",
                    operation="execute_recognition_plan",
                    payload={
                        "success": False,
                        "request": request.model_dump(),
                        "failure_reason": "saved_image_execution_not_allowed",
                        "timings": timings,
                    },
                    name_hint=request.app_name or "recognition_plan",
                )
                return APIResponse(
                    success=False,
                    message="Saved-image execution requires explicit override",
                    data={"trace_path": trace_path, "timings": timings},
                    error=ErrorModel(
                        code="saved_image_execution_not_allowed",
                        details="Use capture_live=true, dry_run=true, or allow_saved_image_execution=true",
                    ),
                )
        else:
            timings = timer.to_dict()
            return APIResponse(
                success=False,
                message="No screenshot source provided",
                data={"timings": timings},
                error=ErrorModel(code="missing_image_source", details="Provide image_path or set capture_live=true"),
            )

        plan_request = VisionRecognitionPlanRequestModel(
            image_path=image_path,
            task=request.task,
            app_name=request.app_name,
            goal=request.goal,
            state_hint=request.state_hint,
            provider_mode=request.provider_mode,
            agent_mode=request.agent_mode,
            learn_depth=request.learn_depth,
            write_policy=request.write_policy,
            metadata=request.metadata,
            top_k=request.top_k,
            observe_trace_path=request.observe_trace_path,
        )
        with timer.step("recognition_plan"):
            plan_response = _run_recognition_plan_for_execution(plan_request)
        if not plan_response.success or not plan_response.data:
            timings = timer.to_dict()
            trace_path = _write_execute_trace_if_enabled(
                request,
                category="actions",
                operation="execute_recognition_plan",
                payload={
                    "success": False,
                    "request": request.model_dump(),
                    "live_capture": live_capture,
                    "recognition_plan_response": plan_response.model_dump(),
                    "failure_reason": "recognition_plan_failed",
                    "timings": timings,
                },
                name_hint=request.app_name or "recognition_plan",
            )
            return APIResponse(
                success=False,
                message="Recognition plan failed",
                data={"trace_path": trace_path, "recognition_plan_response": plan_response.model_dump(), "timings": timings},
                error=ErrorModel(code="recognition_plan_failed", details=plan_response.error.model_dump() if plan_response.error else None),
            )

        plan = plan_response.data["result"]
        pre_click = plan.get("pre_click_decision") or {}
        selected_point = _extract_action_point(plan)
        plan_trace_path = plan.get("trace_path")
        with timer.step("render_recognition_plan_overlay", has_plan_trace=bool(plan_trace_path)):
            overlay = _render_recognition_plan_overlay_for_execution(plan_trace_path) if plan_trace_path else None
        execution_path = {
            "vision_model_used": bool((plan.get("execution_path") or {}).get("vision_model_used")),
            "page_structure_used": True,
            "candidate_rank_used": True,
            "narrow_search_used": True,
            "pre_click_decision_used": True,
            "post_click_verification_used": bool(request.enable_post_click_verification and not request.dry_run),
            "coordinate_source": "pre_click_decision_v1.selected_click_point",
            "selection_source": "recognition_plan_v1",
            "approved_plan_reused": False,
            "recognition_plan_reused": False,
            "action_executed": False,
            "dry_run": bool(request.dry_run),
            "retry_policy_used": True,
            "max_execution_attempts": int(request.max_execution_attempts),
        }

    base_result: dict[str, Any] = {
        "contract_version": "execute_recognition_plan_v1",
        "agent_mode": request.agent_mode,
        "learn_depth": request.learn_depth,
        "mode_contract_version": "execute_plan_v1" if request.agent_mode == "execute" else ("learn_screen_deep_v1" if request.learn_depth == "deep" else "learn_screen_fast_v1"),
        "write_policy": request.write_policy.model_dump(),
        "goal": request.goal,
        "image_path": image_path,
        "live_capture": live_capture,
        "recognition_plan": plan,
        "recognition_plan_trace_path": plan_trace_path,
        "recognition_plan_overlay": overlay,
        "pre_click_decision": pre_click,
        "selected_click_point": selected_point,
        "approved_plan_id": request.approved_plan_id,
        "approved_plan_reuse_validation": approval_reuse_validation,
        "learned_instruction_id": request.learned_instruction_id,
        "learning_mode": request.learning_mode,
        "learned_instruction_reuse_validation": learned_instruction_reuse_validation,
        "learned_instruction_artifacts": (learned_record.get("learning_artifacts") if isinstance(learned_record, dict) else None),
        "execution_path": execution_path,
    }

    if not pre_click.get("allowed") or selected_point is None:
        attach_timings(base_result)
        base_result["trace_path"] = _write_execute_trace_if_enabled(
            request,
            category="actions",
            operation="execute_recognition_plan",
            payload={
                "success": False,
                "request": request.model_dump(),
                "result": base_result,
                "failure_reason": "pre_click_rejected",
            },
            name_hint=request.app_name or "recognition_plan",
        )
        return APIResponse(
            success=False,
            message="Recognition plan was rejected before click",
            data=base_result,
            error=ErrorModel(code="pre_click_rejected", details=pre_click.get("reasons")),
        )

    if request.dry_run:
        if bound is not None and selected_point is not None:
            with timer.step("save_approved_plan"):
                approval = _save_approved_plan(
                    request=request,
                    bound=bound,
                    image_path=image_path,
                    live_capture=live_capture,
                    plan=plan,
                    pre_click=pre_click,
                    selected_point=selected_point,
                    plan_trace_path=plan_trace_path,
                    overlay=overlay,
                )
            base_result.update(approval)
            base_result["approved_plan_id"] = approval["approved_plan_id"]
        attach_timings(base_result)
        base_result["trace_path"] = _write_execute_trace_if_enabled(
            request,
            category="actions",
            operation="execute_recognition_plan",
            payload={"success": True, "request": request.model_dump(), "result": base_result},
            name_hint=request.app_name or "recognition_plan",
        )
        data = ActionResultData(action="execute_recognition_plan", result=base_result)
        return APIResponse(success=True, message="Recognition plan accepted; dry run did not click", data=data.model_dump(), error=None)

    attempts: list[dict[str, Any]] = []
    final_attempt: dict[str, Any] | None = None
    try:
        for attempt_index in range(1, int(request.max_execution_attempts) + 1):
            with timer.step("execution_attempt", attempt=attempt_index):
                with timer.step("capture_pre_action_state", attempt=attempt_index, enabled=request.enable_post_click_verification):
                    before_state = (
                        verifier.capture_pre_action_state(action_name="execute_recognition_plan")
                        if request.enable_post_click_verification
                        else None
                    )
                with timer.step("click_point", attempt=attempt_index):
                    click_result = input_controller.click_point(
                        selected_point["x"],
                        selected_point["y"],
                        move_before_click=True,
                        settle_ms=100,
                        hold_ms=70,
                    )
                with timer.step("post_click_verification", attempt=attempt_index, enabled=request.enable_post_click_verification):
                    post_click_verification = (
                        verifier.verify_action(
                            "execute_recognition_plan",
                            before_state=before_state,
                            click_result=click_result,
                        )
                        if request.enable_post_click_verification
                        else {"verified": None, "verification_skipped": True}
                    )
                with timer.step(
                    "semantic_post_click_verification",
                    attempt=attempt_index,
                    enabled=request.enable_post_click_verification and _should_verify_mouse_tester_semantics(request, plan),
                ):
                    semantic_post_click_verification = (
                        _verify_mouse_tester_post_click_semantics(
                            request=request,
                            plan=plan,
                            generic_verification=post_click_verification,
                        )
                        if request.enable_post_click_verification and _should_verify_mouse_tester_semantics(request, plan)
                        else {"applicable": False, "verified": None, "verification_skipped": True}
                    )
                attempt_verified = _execution_attempt_verified(
                    request=request,
                    post_click_verification=post_click_verification,
                    semantic_post_click_verification=semantic_post_click_verification,
                )
                retry_allowed, retry_reason = _retry_allowed_after_attempt(
                    request=request,
                    pre_click=pre_click,
                    attempt_index=attempt_index,
                    attempt_verified=attempt_verified,
                )
            attempt = {
                "attempt": attempt_index,
                "click_point": selected_point,
                "click_result": click_result,
                "post_click_verification": post_click_verification,
                "semantic_post_click_verification": semantic_post_click_verification,
                "verified": attempt_verified,
                "retry_allowed": retry_allowed,
                "retry_reason": retry_reason,
            }
            attempts.append(attempt)
            final_attempt = attempt
            if attempt_verified or not retry_allowed:
                break
    except Exception as exc:
        base_result["execution_path"]["action_executed"] = bool(attempts)
        base_result["attempts"] = attempts
        attach_timings(base_result)
        base_result["trace_path"] = _write_execute_trace_if_enabled(
            request,
            category="actions",
            operation="execute_recognition_plan",
            payload={
                "success": False,
                "request": request.model_dump(),
                "result": base_result,
                "error": str(exc),
            },
            name_hint=request.app_name or "recognition_plan",
        )
        return APIResponse(
            success=False,
            message="Recognition-plan click failed",
            data=base_result,
            error=ErrorModel(code="recognition_plan_click_failed", details=str(exc)),
        )

    final_attempt = final_attempt or {}
    verified = bool(final_attempt.get("verified"))
    post_click_verification = final_attempt.get("post_click_verification") or {}
    semantic_post_click_verification = final_attempt.get("semantic_post_click_verification") or {}
    click_result = final_attempt.get("click_result") or {}
    base_result.update(
        {
            "click_result": click_result,
            "post_click_verification": post_click_verification,
            "semantic_post_click_verification": semantic_post_click_verification,
            "attempts": attempts,
        }
    )
    base_result["execution_path"]["action_executed"] = bool(attempts)
    base_result["execution_path"]["execution_attempt_count"] = len(attempts)
    base_result["execution_path"]["retry_count"] = max(0, len(attempts) - 1)
    base_result["execution_path"]["semantic_post_click_verification_used"] = bool(semantic_post_click_verification.get("applicable"))
    attach_timings(base_result)
    base_result["trace_path"] = _write_execute_trace_if_enabled(
        request,
        category="actions",
        operation="execute_recognition_plan",
        payload={"success": verified, "request": request.model_dump(), "result": base_result},
        name_hint=request.app_name or "recognition_plan",
    )

    if not verified:
        error_code = "semantic_post_click_verification_failed" if semantic_post_click_verification.get("applicable") else "post_click_verification_failed"
        return APIResponse(
            success=False,
            message="Recognition-plan click executed but post-click verification failed",
            data=base_result,
            error=ErrorModel(
                code=error_code,
                details={
                    "post_click_verification": post_click_verification,
                    "semantic_post_click_verification": semantic_post_click_verification,
                },
            ),
        )

    if _instruction_learning_enabled(request) and bound is not None and not request.learned_instruction_id:
        with timer.step("save_learned_instruction"):
            learning_record = _save_learned_instruction(
                request=request,
                bound=bound,
                image_path=image_path,
                live_capture=live_capture,
                plan=plan,
                pre_click=pre_click,
                selected_point=selected_point,
                click_result=click_result,
                post_click_verification=post_click_verification,
                semantic_post_click_verification=semantic_post_click_verification,
                plan_trace_path=plan_trace_path,
                action_trace_path=base_result.get("trace_path"),
            )
        base_result.update(learning_record)
        attach_timings(base_result)

    data = ActionResultData(action="execute_recognition_plan", result=base_result)
    return APIResponse(success=True, message="Recognition-plan click executed and verified", data=data.model_dump(), error=None)


@router.post("/execute_confirmed_point", response_model=APIResponse)
def execute_confirmed_point(request: ExecuteConfirmedPointRequest) -> APIResponse:
    """Dispatch a point explicitly confirmed in the review UI."""
    timer = RuntimeTimer()
    with timer.step("get_bound_window"):
        bound = window_manager.get_bound_window()
    if bound is None:
        timings = timer.to_dict()
        return APIResponse(
            success=False,
            message="No bound window is currently available",
            data={"timings": timings},
            error=ErrorModel(code="no_bound_window", details="Bind a target window before executing a confirmed point"),
        )

    with timer.step("validate_confirmed_point"):
        point = {"x": int(request.x), "y": int(request.y)}
        bbox = request.bbox.model_dump() if request.bbox is not None else None
    if bbox is not None and not _point_in_rect(point, bbox):
        timings = timer.to_dict()
        return APIResponse(
            success=False,
            message="Confirmed point is outside its reviewed candidate box",
            data={"point": point, "bbox": bbox, "timings": timings},
            error=ErrorModel(code="confirmed_point_outside_bbox", details={"point": point, "bbox": bbox}),
        )

    with timer.step("validate_bound_window_rect"):
        rect = _window_rect(bound)
    if not _point_in_rect(point, {"x": 0, "y": 0, "width": rect["width"] - 1, "height": rect["height"] - 1}):
        timings = timer.to_dict()
        return APIResponse(
            success=False,
            message="Confirmed point is outside the currently bound window",
            data={"point": point, "window_size": {"width": rect["width"], "height": rect["height"]}, "timings": timings},
            error=ErrorModel(code="confirmed_point_outside_window", details=point),
        )

    result: dict[str, Any] = {
        "contract_version": "execute_confirmed_point_v1",
        "label": request.label,
        "confirmed_point": point,
        "candidate_bbox": bbox,
        "source_trace_path": request.source_trace_path,
        "bound_window": {"handle": int(bound.handle), "title": bound.title, "width": rect["width"], "height": rect["height"]},
        "execution_path": {
            "coordinate_source": "human_confirmed_candidate_center",
            "selection_source": "settings_panel_candidate_review",
            "action_executed": False,
            "dry_run": bool(request.dry_run),
        },
    }
    if request.dry_run:
        result["timings"] = timer.to_dict()
        result["trace_path"] = write_trace(
            category="actions",
            operation="execute_confirmed_point",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint=request.label or "confirmed_point",
        )
        data = ActionResultData(action="execute_confirmed_point", result=result)
        return APIResponse(success=True, message="Confirmed point accepted; dry run did not click", data=data.model_dump(), error=None)

    try:
        with timer.step("click_point"):
            result["click_result"] = input_controller.click_point(
                point["x"],
                point["y"],
                move_before_click=True,
                settle_ms=100,
                hold_ms=70,
            )
        result["execution_path"]["action_executed"] = True
        result["timings"] = timer.to_dict()
        result["trace_path"] = write_trace(
            category="actions",
            operation="execute_confirmed_point",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint=request.label or "confirmed_point",
        )
        data = ActionResultData(action="execute_confirmed_point", result=result)
        return APIResponse(success=True, message="Confirmed coordinate click dispatched", data=data.model_dump(), error=None)
    except Exception as exc:
        result["timings"] = timer.to_dict()
        result["trace_path"] = write_trace(
            category="actions",
            operation="execute_confirmed_point",
            payload={"success": False, "request": request.model_dump(), "result": result, "error": str(exc)},
            name_hint=request.label or "confirmed_point",
        )
        return APIResponse(
            success=False,
            message="Confirmed coordinate click failed",
            data=result,
            error=ErrorModel(code="confirmed_point_click_failed", details=str(exc)),
        )


def _ensure_mouse_tester_state_assets(bound: Any) -> tuple[Optional[AppState], list[ActionTarget], dict[str, ValidatorProfile]]:
    state_id = f"mousetester_main_{_window_size_bucket(_window_rect(bound))}"
    state = action_registry.load_state_hint(state_id)
    if state is None:
        state = AppState(
            state_id=state_id,
            app_name="MouseTesterWeb",
            state_name="main_page",
            window_size_bucket=_window_size_bucket(_window_rect(bound)),
            fingerprint=None,
            panel_profiles=[],
            known_action_ids=["click_mouse_tester_left_region", "click_mouse_tester_left_region_alt"],
            tags=["legacy-reduced", "manual-zone"],
            version=1,
        )
        action_registry.save_state_hint(state)

    action_specs = [
        {
            "action_id": "click_mouse_tester_left_region",
            "action_name": "Click MouseTester Left Region",
            "zone": {"nx": 0.10, "ny": 0.15, "nw": 0.35, "nh": 0.40},
            "validator_id": "validator_mouse_tester_left_counter",
        },
        {
            "action_id": "click_mouse_tester_left_region_alt",
            "action_name": "Click MouseTester Left Region Alt",
            "zone": {"nx": 0.14, "ny": 0.18, "nw": 0.28, "nh": 0.32},
            "validator_id": "validator_mouse_tester_left_counter",
        },
    ]

    actions: list[ActionTarget] = []
    for spec in action_specs:
        action = action_registry.load_action(spec["action_id"])
        if action is None:
            action = ActionTarget(
                action_id=spec["action_id"],
                state_id=state.state_id,
                action_name=spec["action_name"],
                target_kind="region",
                panel_locator_profile={
                    "mode": "window_relative_rect",
                    "coord_space": "window",
                    "nx": 0.16,
                    "ny": 0.48,
                    "nw": 0.48,
                    "nh": 0.40,
                },
                zone_resolver_profile={"mode": "panel_relative_rect", "coord_space": "panel", **spec["zone"]},
                point_strategy_profile={"mode": "grid", "rows": 3, "cols": 3, "inset": 0.18, "prefer_memory": True},
                validator_profile_id=spec["validator_id"],
                successful_points=[],
                forbidden_points=[],
                local_patch_template_path=None,
                notes="Reduced legacy region action kept as reusable click fallback.",
                version=1,
            )
            action_registry.save_action(action)
        actions.append(action)

    validator = action_registry.load_validator("validator_mouse_tester_left_counter")
    if validator is None:
        validator = ValidatorProfile(
            validator_profile_id="validator_mouse_tester_left_counter",
            name="MouseTester Left Counter Validator",
            ocr_roi=None,
            roi_diff_threshold=0.01,
            strict_rule={"type": "counter_change_or_visual_diff"},
            weak_rule={"type": "visual_diff"},
            version=1,
        )
        action_registry.save_validator(validator)

    validators = {action.action_id: validator for action in actions}
    return state, actions, validators


@router.post("/click_text", response_model=APIResponse)
def click_text(request: ClickTextRequest) -> APIResponse:
    bound = window_manager.get_bound_window()
    if bound is None:
        return APIResponse(
            success=False,
            message="No bound window is currently available",
            data=None,
            error=ErrorModel(code="no_bound_window", details="Bind a target window before calling /action/click_text"),
        )

    try:
        action_name = f"click_text:{request.text}"
        execution_path = {
            "vision_model_used": False,
            "page_structure_used": False,
            "coordinate_source": "ocr_bbox_center",
            "selection_source": "ocr_text_match",
        }
        capture = screenshot_service.capture_window(
            roi=request.roi,
            save_image=True,
            purpose="click_text_scan",
            name_hint=request.text,
        )
        ocr_result = ocr_service.scan_image(capture["image_path"])
        matches = find_text_matches(ocr_result, request.text, partial_match=request.partial_match)
        if not matches:
            trace_path = write_trace(
                category="actions",
                operation="click_text",
                payload={
                    "success": False,
                    "request": request.model_dump(),
                    "execution_path": execution_path,
                    "capture": capture,
                    "ocr_result": ocr_result.to_dict(),
                    "failure_reason": "text_not_found",
                },
                name_hint=request.text,
            )
            return APIResponse(
                success=False,
                message="Requested text was not found in OCR result",
                data={
                    "query": request.text,
                    "partial_match": request.partial_match,
                    "execution_path": execution_path,
                    "trace_path": trace_path,
                    "matches": [match.to_dict() for match in find_text_matches(ocr_result, request.text, partial_match=True)],
                    "ocr_result": ocr_result.to_dict(),
                },
                error=ErrorModel(code="text_not_found", details=request.text),
            )

        roi_payload = capture.get("roi") or {}
        attempts: list[dict[str, Any]] = []
        selected_result: Optional[dict[str, Any]] = None
        candidate_matches = matches[: request.max_retries]

        for index, candidate in enumerate(candidate_matches, start=1):
            center = bbox_center(candidate.bbox)
            window_x = int(center["x"] + int(roi_payload.get("x", 0)))
            window_y = int(center["y"] + int(roi_payload.get("y", 0)))

            before_state = verifier.capture_pre_action_state(roi=request.roi, action_name=action_name) if request.enable_validation else None
            click_result = input_controller.click_point(window_x, window_y, move_before_click=True, settle_ms=100, hold_ms=70)
            verification = (
                verifier.verify_action(
                    action_name,
                    roi=request.roi,
                    before_state=before_state,
                    click_result=click_result,
                )
                if request.enable_validation
                else {"verified": None, "verification_skipped": True}
            )
            success = True if not request.enable_validation else bool(verification.get("verified"))
            attempt = {
                "attempt": index,
                "match": candidate.to_dict(),
                "window_point": {"x": window_x, "y": window_y},
                "click_result": click_result,
                "verification": verification,
                "success": success,
            }
            attempts.append(attempt)
            if success:
                selected_result = attempt
                break

        if selected_result is None:
            trace_path = write_trace(
                category="actions",
                operation="click_text",
                payload={
                    "success": False,
                    "request": request.model_dump(),
                    "execution_path": execution_path,
                    "capture": capture,
                    "ocr_result": ocr_result.to_dict(),
                    "attempts": attempts,
                    "failure_reason": "verification_failed",
                },
                name_hint=request.text,
            )
            return APIResponse(
                success=False,
                message="Text candidates were clicked but verification did not succeed",
                data={
                    "query": request.text,
                    "partial_match": request.partial_match,
                    "execution_path": execution_path,
                    "trace_path": trace_path,
                    "capture": {
                        "image_path": capture.get("image_path"),
                        "roi": capture.get("roi"),
                        "roi_adjusted": capture.get("roi_adjusted"),
                        "window_size": capture.get("window_size"),
                    },
                    "ocr_match_count": len(ocr_result.matches),
                    "attempts": attempts,
                },
                error=ErrorModel(code="click_text_not_verified", details=request.text),
            )

        result = {
            "query": request.text,
            "partial_match": request.partial_match,
            "selected_match": selected_result["match"],
            "window_point": selected_result["window_point"],
            "capture": {
                "image_path": capture.get("image_path"),
                "roi": capture.get("roi"),
                "roi_adjusted": capture.get("roi_adjusted"),
                "window_size": capture.get("window_size"),
            },
            "execution_path": execution_path,
            "ocr_match_count": len(ocr_result.matches),
            "attempts": attempts,
            "click_result": selected_result["click_result"],
            "verification": selected_result["verification"],
        }
        result["trace_path"] = write_trace(
            category="actions",
            operation="click_text",
            payload={
                "success": True,
                "request": request.model_dump(),
                "execution_path": execution_path,
                "result": result,
                "ocr_result": ocr_result.to_dict(),
            },
            name_hint=request.text,
        )
        data = ActionResultData(action="click_text", result=result)
        return APIResponse(success=True, message="Text clicked successfully", data=data.model_dump(), error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Text click failed",
            data=None,
            error=ErrorModel(code="click_text_failed", details=str(exc)),
        )


@router.post("/type_text", response_model=APIResponse)
def type_text(request: TypeTextRequest) -> APIResponse:
    bound = window_manager.get_bound_window()
    if bound is None:
        return APIResponse(
            success=False,
            message="No bound window is currently available",
            data=None,
            error=ErrorModel(code="no_bound_window", details="Bind a target window before calling /action/type_text"),
        )
    if request.click_before_typing and (request.x is None or request.y is None):
        return APIResponse(
            success=False,
            message="Text input point is incomplete",
            data=None,
            error=ErrorModel(code="missing_input_point", details="Provide x and y when click_before_typing=true"),
        )

    result: dict[str, Any] = {
        "contract_version": "type_text_result_v1",
        "dry_run": request.dry_run,
        "text_length": len(request.text),
        "click_before_typing": request.click_before_typing,
        "point": {"x": request.x, "y": request.y} if request.x is not None and request.y is not None else None,
        "clear_existing": request.clear_existing,
        "submit": request.submit,
        "execution_path": {
            "vision_model_used": False,
            "page_structure_used": False,
            "input_backend": "SendInput+clipboard",
            "action_executed": False,
        },
    }
    if request.dry_run:
        result["trace_path"] = write_trace(
            category="actions",
            operation="type_text",
            payload={"success": True, "request": request.model_dump(exclude={"text"}), "result": result},
            name_hint="type_text_dry_run",
        )
        data = ActionResultData(action="type_text", result=result)
        return APIResponse(success=True, message="Text input dry-run validated", data=data.model_dump(), error=None)

    try:
        result["type_result"] = input_controller.type_text(
            request.text,
            x=request.x,
            y=request.y,
            click_before_typing=request.click_before_typing,
            clear_existing=request.clear_existing,
            submit=request.submit,
            restore_clipboard=request.restore_clipboard,
        )
        result["execution_path"]["action_executed"] = True
        result["trace_path"] = write_trace(
            category="actions",
            operation="type_text",
            payload={"success": True, "request": request.model_dump(exclude={"text"}), "result": result},
            name_hint="type_text",
        )
        data = ActionResultData(action="type_text", result=result)
        return APIResponse(success=True, message="Text input dispatched", data=data.model_dump(), error=None)
    except Exception as exc:
        result["trace_path"] = write_trace(
            category="actions",
            operation="type_text",
            payload={"success": False, "request": request.model_dump(exclude={"text"}), "result": result, "error": str(exc)},
            name_hint="type_text",
        )
        return APIResponse(
            success=False,
            message="Text input failed",
            data=result,
            error=ErrorModel(code="type_text_failed", details=str(exc)),
        )


def _run_region_click(
    *,
    case_name: str,
    bound: Any,
    panel_locator: RegionClickPanelLocator,
    zone_resolver: RegionClickZoneResolver,
    point_strategy: RegionClickPointStrategy,
    validator: RegionClickValidator,
    validator_profile: Optional[ValidatorProfile] = None,
    max_retries: int = 1,
) -> dict[str, Any]:
    panel = panel_locator(bound)
    zone = zone_resolver(panel)
    bucket = _window_size_bucket(_window_rect(bound))
    memory = _load_region_click_memory(case_name, bucket) or {}
    preferred_norm_point = memory.get("preferred_norm_point")
    points = point_strategy(zone, preferred_norm_point)

    before_state = verifier.capture_pre_action_state(action_name=case_name)
    retries: list[dict[str, Any]] = []

    for attempt_index, point in enumerate(points[: max(1, len(points))]):
        click_result = input_controller.click_point(point["x"], point["y"], move_before_click=True, settle_ms=100, hold_ms=70)
        verification = verifier.verify_action(case_name, before_state=before_state, click_result=click_result)
        diff_changed = verification.get("diff", {}).get("changed")
        counter_eval = validator([], [])
        if diff_changed and not counter_eval.get("weak_success"):
            counter_eval["weak_success"] = True
        if diff_changed and not counter_eval.get("strict_success"):
            counter_eval["strict_success"] = True
        success = bool(counter_eval.get("strict_success") or counter_eval.get("weak_success"))

        retry_entry = {
            "attempt": attempt_index + 1,
            "point": point,
            "click": click_result,
            "verification": verification,
            "counter_eval": counter_eval,
            "success": success,
        }
        retries.append(retry_entry)

        if success:
            memory_path = _save_region_click_memory(
                case_name,
                bucket,
                {
                    "preferred_norm_point": _normalized_point(zone, point),
                    "last_success_point": point,
                    "validator_profile_id": validator_profile.validator_profile_id if validator_profile else None,
                },
            )
            case_path = str((CASES_DIR / f"{case_name}-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.json").resolve())
            Path(case_path).write_text(json.dumps(retry_entry, ensure_ascii=False, indent=2), encoding="utf-8")
            return {
                "success": True,
                "panel": panel,
                "zone": zone,
                "points": points,
                "selected_point": point,
                "strict_success": bool(counter_eval.get("strict_success")),
                "weak_success": bool(counter_eval.get("weak_success")),
                "verification": verification,
                "roi_diff_score": verification.get("diff", {}).get("count"),
                "retries": retries,
                "memory_path": memory_path,
                "case_path": case_path,
            }

        if attempt_index + 1 >= max_retries and max_retries > 0:
            break

    return {
        "success": False,
        "panel": panel,
        "zone": zone,
        "points": points,
        "retries": retries,
    }


@router.post("/click_mouse_tester_left_region", response_model=APIResponse)
def click_mouse_tester_left_region() -> APIResponse:
    bound = window_manager.get_bound_window()
    if bound is None:
        return APIResponse(success=False, message="No bound window is currently available", data=None, error=ErrorModel(code="no_bound_window", details="Bind a MouseTester window before calling /action/click_mouse_tester_left_region"))

    state_before, actions, validators = _ensure_mouse_tester_state_assets(bound)

    primary_action = next((a for a in actions if a.action_id == "click_mouse_tester_left_region"), None)
    alt_action = next((a for a in actions if a.action_id == "click_mouse_tester_left_region_alt"), None)

    def execute_with_action(action_target: ActionTarget) -> dict[str, Any]:
        zone_profile = action_target.zone_resolver_profile

        def dynamic_zone(panel: dict[str, Any]) -> dict[str, Any]:
            return {
                "x": int(panel["x"] + panel["width"] * float(zone_profile.get("nx", 0.0))),
                "y": int(panel["y"] + panel["height"] * float(zone_profile.get("ny", 0.0))),
                "width": max(1, int(panel["width"] * float(zone_profile.get("nw", 1.0)))),
                "height": max(1, int(panel["height"] * float(zone_profile.get("nh", 1.0)))),
                "source": action_target.action_id,
            }

        return run_known_action(
            app_name="MouseTesterWeb",
            state_before=state_before,
            action_target=action_target,
            validator_profile=validators.get(action_target.action_id),
            capture_state_image=lambda prefix: _capture_bound_window_image(bound, prefix),
            get_window_bucket=lambda: _window_size_bucket(_window_rect(bound)),
            execute_action=lambda: _run_region_click(
                case_name=action_target.action_id,
                bound=bound,
                panel_locator=_locate_mouse_tester_panel,
                zone_resolver=dynamic_zone,
                point_strategy=_generate_zone_points,
                validator=_evaluate_counter_result,
                validator_profile=validators.get(action_target.action_id),
            ),
        )

    try:
        result = execute_with_action(primary_action) if primary_action else {"success": False}
        if not result.get("success") and alt_action is not None:
            result["fallback_attempted_action_id"] = alt_action.action_id
            fallback_result = execute_with_action(alt_action)
            result["fallback_result"] = {
                "success": fallback_result.get("success"),
                "action_target_id": fallback_result.get("action_target_id"),
                "strict_success": fallback_result.get("strict_success"),
                "weak_success": fallback_result.get("weak_success"),
            }
            if fallback_result.get("success"):
                result = fallback_result
                result["used_fallback_action"] = True
    except Exception as exc:
        return APIResponse(success=False, message="Region click execution failed", data=None, error=ErrorModel(code="region_click_failed", details=str(exc)))

    if not result["success"]:
        result["execution_path"] = {
            "vision_model_used": False,
            "page_structure_used": False,
            "coordinate_source": "region_grid_or_memory_point",
            "selection_source": "known_action_target",
        }
        result["trace_path"] = write_trace(
            category="actions",
            operation="click_mouse_tester_left_region",
            payload={"success": False, "result": result},
            name_hint="mouse_tester_left_region",
        )
        return APIResponse(success=False, message="MouseTester left region click did not change the counter", data=result, error=ErrorModel(code="counter_not_changed", details="No known action target changed the target counter; generic region_click path remains available as fallback"))

    result["execution_path"] = {
        "vision_model_used": False,
        "page_structure_used": False,
        "coordinate_source": "region_grid_or_memory_point",
        "selection_source": "known_action_target",
    }
    result["trace_path"] = write_trace(
        category="actions",
        operation="click_mouse_tester_left_region",
        payload={"success": True, "result": result},
        name_hint="mouse_tester_left_region",
    )
    data = ActionResultData(action="click_mouse_tester_left_region", result=result)
    return APIResponse(success=True, message="MouseTester left region clicked successfully", data=data.model_dump(), error=None)
