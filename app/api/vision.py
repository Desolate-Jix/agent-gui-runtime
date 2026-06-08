from __future__ import annotations

import hashlib
import json
from pathlib import Path
from difflib import SequenceMatcher
from typing import Any

from fastapi import APIRouter
from PIL import Image

from app.core.ocr_service import ocr_service
from app.core.runtime_artifacts import RuntimeTimer, write_trace
from app.core.screenshot import screenshot_service
from app.models.request import (
    VisionAnalyzeRequestModel,
    VisionLocateTargetRequestModel,
    VisionObserveScreenRequestModel,
    VisionRecognitionPlanOverlayRequestModel,
    VisionRecognitionPlanRequestModel,
    VisionReviewOverlayRequestModel,
)
from app.models.response import APIResponse, ErrorModel, VisionResultData
from app.models.request import OCRRegionRequest
from app.page_structure import build_page_structure
from app.recognition import CandidateRankRequest, LocalGroundingRequest, decide_pre_click, rank_candidates, run_local_grounding
from app.recognition.plan_overlay import render_recognition_plan_overlay
from app.screen_reading import build_screen_reading
from app.screen_reading.uia_provider import uia_provider
from app.vision.artifacts import save_region_artifacts
from app.vision.anchor_grounding import apply_anchor_grounding_evaluation
from app.vision.factory import VisionProviderFactory
from app.vision.layer_trace import (
    failure_layer,
    make_layer,
    summarize_ocr,
    summarize_page_structure,
    summarize_vision,
    validate_input_layer,
    validate_ocr_layer,
    validate_page_structure_layer,
    validate_provider_layer,
    validate_vision_regions_layer,
)
from app.vision.normalizer import normalizer
from app.vision.ocr_anchors import (
    DEFAULT_PROMPT_ANCHOR_LIMIT,
    DEFAULT_PROMPT_FOCUS_NEIGHBOR_LIMIT,
    DEFAULT_PROMPT_TEXT_MATCH_THRESHOLD,
    build_ocr_anchor_payload,
)
from app.vision.ocr_region_refiner import parse_ocr_region_refine_options, refine_vision_regions_with_ocr
from app.vision.review_overlay import render_review_overlay
from app.vision.schemas import ImageSize, VisionAnalyzeRequest
from modules.ocr.contracts import OCRResult

router = APIRouter(prefix="/vision", tags=["vision"])


def _vision_execution_path(
    *,
    requested_mode: str | None,
    response_provider: str | None = None,
    raw_response: dict | None = None,
    page_structure_generated: bool = False,
    ocr_region_refine_used: bool = False,
) -> dict[str, object]:
    raw = raw_response or {}
    stub_mode = bool(raw.get("mode") == "stub")
    return {
        "vision_provider_requested": requested_mode,
        "vision_provider_used": response_provider,
        "vision_model_used": bool(response_provider) and not stub_mode,
        "page_structure_used": bool(page_structure_generated),
        "ocr_region_refine_used": bool(ocr_region_refine_used),
        "coordinate_source": "page_structure_v1.click_point" if page_structure_generated else "vision_regions_v1",
    }


def _maybe_refine_with_ocr(provider_response, *, request: VisionAnalyzeRequestModel, image_path: Path):
    options = parse_ocr_region_refine_options(request.metadata)
    if not options.enabled:
        return provider_response, None, options
    ocr_result = ocr_service.scan_image(str(image_path))
    refined = refine_vision_regions_with_ocr(provider_response, ocr_result, options=options)
    return refined, ocr_result, options


def _recognition_vision_request_with_ocr_anchors(
    request: VisionRecognitionPlanRequestModel,
    *,
    image_path: Path,
    image_size: ImageSize,
) -> tuple[VisionAnalyzeRequest, OCRResult | None, dict[str, object] | None, dict[str, object]]:
    metadata = dict(request.metadata or {})
    anchor_status: dict[str, object] = {
        "enabled": _ocr_anchors_enabled(metadata),
        "used": False,
        "fallback_used": False,
        "anchor_count": 0,
    }
    ocr_result: OCRResult | None = None
    anchor_payload: dict[str, object] | None = None

    if anchor_status["enabled"]:
        try:
            raw_options = metadata.get("ocr_anchors") if isinstance(metadata.get("ocr_anchors"), dict) else {}
            reused = metadata.get("reused_ocr_anchors") if isinstance(metadata.get("reused_ocr_anchors"), dict) else None
            raw_max_anchors = raw_options.get("max_anchors") if isinstance(raw_options, dict) else None
            if _reusable_ocr_anchor_payload(reused, image_path=image_path):
                anchor_payload = dict(reused or {})
                anchor_status["reused"] = True
                anchor_status["source_trace_path"] = metadata.get("reused_ocr_source_trace_path")
            else:
                ocr_result = ocr_service.scan_image(str(image_path))
                max_anchors = None if raw_max_anchors in (None, "all", "ALL", 0, "0") else int(raw_max_anchors)
                min_score = float(raw_options.get("min_score", 0.0)) if isinstance(raw_options, dict) else 0.0
                anchor_payload = build_ocr_anchor_payload(
                    ocr_result,
                    image_size=image_size,
                    goal=request.goal or request.task,
                    max_anchors=max_anchors,
                    min_score=min_score,
                )
            anchor_payload["prompt_max_anchors"] = (
                int(raw_options.get("prompt_max_anchors", DEFAULT_PROMPT_ANCHOR_LIMIT))
                if isinstance(raw_options, dict)
                else DEFAULT_PROMPT_ANCHOR_LIMIT
            )
            anchor_payload["prompt_text_match_threshold"] = (
                float(raw_options.get("prompt_text_match_threshold", DEFAULT_PROMPT_TEXT_MATCH_THRESHOLD))
                if isinstance(raw_options, dict)
                else DEFAULT_PROMPT_TEXT_MATCH_THRESHOLD
            )
            anchor_payload["prompt_focus_neighbor_limit"] = (
                int(raw_options.get("prompt_focus_neighbor_limit", DEFAULT_PROMPT_FOCUS_NEIGHBOR_LIMIT))
                if isinstance(raw_options, dict)
                else DEFAULT_PROMPT_FOCUS_NEIGHBOR_LIMIT
            )
            metadata["ocr_anchors"] = anchor_payload
            metadata.pop("reused_ocr_anchors", None)
            anchor_status.update(
                {
                    "used": bool(anchor_payload.get("anchor_count")),
                    "anchor_count": int(anchor_payload.get("anchor_count") or 0),
                    "source_engine": anchor_payload.get("source_engine"),
                }
            )
        except Exception as exc:
            anchor_status.update({"fallback_used": True, "error": str(exc)})
            metadata.pop("ocr_anchors", None)

    vision_request = VisionAnalyzeRequest(
        image_path=str(image_path),
        task=request.task,
        app_name=request.app_name,
        goal=request.goal,
        state_hint=request.state_hint,
        provider_mode=request.provider_mode,
        metadata=metadata,
    )
    return vision_request, ocr_result, anchor_payload, anchor_status


def _reusable_ocr_anchor_payload(payload: dict[str, Any] | None, *, image_path: Path) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("contract_version") != "ocr_anchors_v1":
        return False
    if not isinstance(payload.get("anchors"), list):
        return False
    source_image = str(payload.get("image_path") or "")
    if source_image:
        try:
            return Path(source_image).resolve() == image_path.resolve()
        except Exception:
            return source_image == str(image_path)
    return True


def _ocr_anchors_enabled(metadata: dict[str, object]) -> bool:
    raw = metadata.get("ocr_anchors", True)
    if raw is False:
        return False
    if isinstance(raw, dict):
        return bool(raw.get("enabled", True))
    return True


def _vision_request_without_ocr_anchors(request: VisionRecognitionPlanRequestModel, *, image_path: Path) -> VisionAnalyzeRequest:
    metadata = dict(request.metadata or {})
    metadata.pop("ocr_anchors", None)
    return VisionAnalyzeRequest(
        image_path=str(image_path),
        task=request.task,
        app_name=request.app_name,
        goal=request.goal,
        state_hint=request.state_hint,
        provider_mode=request.provider_mode,
        metadata=metadata,
    )


def _image_path_for_live_or_saved(
    *,
    capture_live: bool,
    image_path: str | None,
    purpose: str,
    app_name: str | None = None,
) -> tuple[str, dict | None]:
    if capture_live:
        capture = screenshot_service.capture_window(save_image=True, purpose=purpose, name_hint=app_name or purpose)
        return str(Path(str(capture["image_path"])).resolve()), capture
    if image_path:
        return image_path, None
    raise ValueError("Provide image_path or set capture_live=true")


def _load_observe_trace_reuse(trace_path_value: str | None, *, image_path: str, goal: str | None = None) -> dict[str, Any]:
    if not trace_path_value:
        return {}
    trace_path = Path(trace_path_value)
    if not trace_path.exists():
        return {
            "status": "unavailable",
            "reason": "observe_trace_not_found",
            "trace_path": str(trace_path),
        }
    try:
        trace = json.loads(trace_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {
            "status": "unavailable",
            "reason": f"observe_trace_read_failed: {exc}",
            "trace_path": str(trace_path),
        }
    result = trace.get("result") if isinstance(trace.get("result"), dict) else {}
    if not result:
        nested = trace.get("data") if isinstance(trace.get("data"), dict) else {}
        result = nested.get("result") if isinstance(nested.get("result"), dict) else {}
    parse_result = result.get("parse_result") if isinstance(result.get("parse_result"), dict) else {}
    ocr_anchors = parse_result.get("ocr_anchors") if isinstance(parse_result.get("ocr_anchors"), dict) else None
    if not ocr_anchors:
        ocr_anchors = _ocr_anchor_payload_from_observe_texts(result, image_path=image_path, goal=goal)
    if not ocr_anchors:
        return {
            "status": "unavailable",
            "reason": "observe_trace_has_no_ocr_texts",
            "trace_path": str(trace_path),
        }
    if not _reusable_ocr_anchor_payload(ocr_anchors, image_path=Path(image_path)):
        return {
            "status": "unavailable",
            "reason": "observe_trace_image_mismatch",
            "trace_path": str(trace_path),
            "trace_image_path": ocr_anchors.get("image_path"),
            "image_path": image_path,
        }
    screen_map = result.get("screen_map") if isinstance(result.get("screen_map"), dict) else {}
    return {
        "status": "ready",
        "trace_path": str(trace_path),
        "ocr_anchors": ocr_anchors,
        "screen_map": screen_map,
        "state_id": screen_map.get("state_id") if isinstance(screen_map, dict) else None,
        "candidate_count": len(screen_map.get("candidates") or []) if isinstance(screen_map, dict) else 0,
        "anchor_count": int(ocr_anchors.get("anchor_count") or 0),
        "anchor_source": ocr_anchors.get("source_engine"),
    }


def _ocr_anchor_payload_from_observe_texts(result: dict[str, Any], *, image_path: str, goal: str | None = None) -> dict[str, Any] | None:
    texts = _screen_map_texts(result)
    if not texts:
        return None
    image_size_payload = result.get("image_size") if isinstance(result.get("image_size"), dict) else {}
    width = int(_number(image_size_payload.get("width")) or _max_text_edge(result, axis="x") or 0)
    height = int(_number(image_size_payload.get("height")) or _max_text_edge(result, axis="y") or 0)
    anchors: list[dict[str, Any]] = []
    normalized_goal = _normalize_anchor_text(goal or "")
    for index, item in enumerate(texts, start=1):
        text = _first_compact_text(item.get("text"))
        bbox = _normalize_map_bbox(item.get("bbox"))
        if not text or not bbox:
            continue
        confidence = _bounded_float(item.get("confidence"))
        goal_similarity = _anchor_text_similarity(normalized_goal, _normalize_anchor_text(text)) if normalized_goal else 0.0
        anchors.append(
            {
                "anchor_id": f"observe_text_anchor_{index}",
                "text": text,
                "bbox": bbox,
                "center": _normalize_map_point(None, bbox),
                "confidence": confidence if confidence is not None else 1.0,
                "goal_similarity": round(goal_similarity, 4),
                "source_text_id": item.get("id"),
            }
        )
    if not anchors:
        return None
    anchors.sort(key=lambda item: (item["goal_similarity"], item["confidence"], len(item["text"])), reverse=True)
    return {
        "contract_version": "ocr_anchors_v1",
        "coordinate_space": "original_image",
        "image_path": image_path,
        "image_size": {"width": width, "height": height},
        "source_engine": "observe_trace_texts",
        "total_detected_count": len(anchors),
        "anchor_count": len(anchors),
        "anchors": anchors,
    }


def _normalize_anchor_text(value: str) -> str:
    return "".join(str(value or "").casefold().split())


def _anchor_text_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return min(len(a), len(b)) / max(len(a), len(b))
    return SequenceMatcher(None, a, b).ratio()


@router.post("/ocr_region", response_model=APIResponse)
def ocr_region(request: OCRRegionRequest) -> APIResponse:
    try:
        capture = screenshot_service.capture_window(roi=request.roi, save_image=True, purpose="ocr_region")
        result = ocr_service.scan_image(capture["image_path"])
        result.metadata.update(
            {
                "roi": capture.get("roi"),
                "roi_adjusted": capture.get("roi_adjusted"),
                "window_size": capture.get("window_size"),
                "capture_saved_for_ocr": True,
            }
        )
        result_payload = {
            "execution_path": {
                "vision_model_used": False,
                "page_structure_used": False,
                "coordinate_source": "ocr_bbox",
            },
            "ocr_result": result.to_dict(),
        }
        result_payload["trace_path"] = write_trace(
            category="vision",
            operation="ocr_region",
            payload={"success": True, "request": request.model_dump(), "result": result_payload},
            name_hint="ocr_region",
        )
        data = VisionResultData(result=result_payload)
        return APIResponse(success=True, message="OCR completed", data=data.model_dump(), error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="OCR failed",
            data=None,
            error=ErrorModel(code="ocr_failed", details=str(exc)),
        )


@router.post("/analyze", response_model=APIResponse)
def analyze_vision(request: VisionAnalyzeRequestModel) -> APIResponse:
    image_path = Path(request.image_path)
    if not image_path.exists():
        return APIResponse(
            success=False,
            message="Image path not found",
            data=None,
            error=ErrorModel(code="image_not_found", details=str(image_path)),
        )

    try:
        config = VisionProviderFactory.load_config()
        provider = VisionProviderFactory.create(mode=request.provider_mode, config=config)
        response = provider.analyze(
            VisionAnalyzeRequest(
                image_path=str(image_path),
                task=request.task,
                app_name=request.app_name,
                goal=request.goal,
                state_hint=request.state_hint,
                provider_mode=request.provider_mode,
                metadata=request.metadata,
            )
        )
        response, ocr_result, refine_options = _maybe_refine_with_ocr(response, request=request, image_path=image_path)
        normalized = normalizer.normalize(response.to_dict(), response.provider)
        if normalized.image_size is None:
            with Image.open(image_path) as image:
                normalized.image_size = ImageSize(width=image.width, height=image.height)
        normalized.artifacts = save_region_artifacts(image_path, normalized)
        result_payload = normalized.to_dict()
        result_payload["execution_path"] = _vision_execution_path(
            requested_mode=request.provider_mode or str((config.get("vision") or {}).get("mode") or "local"),
            response_provider=response.provider,
            raw_response=response.raw_response,
            page_structure_generated=False,
            ocr_region_refine_used=refine_options.enabled,
        )
        if ocr_result is not None:
            result_payload["ocr_result"] = ocr_result.to_dict()
        result_payload["trace_path"] = write_trace(
            category="vision",
            operation="vision_analyze",
            payload={"success": True, "request": request.model_dump(), "result": result_payload},
            name_hint=request.app_name or image_path.stem,
        )
        data = VisionResultData(result=result_payload)
        return APIResponse(success=True, message="Vision analysis completed", data=data.model_dump(), error=None)
    except Exception as exc:
        trace_path = write_trace(
            category="vision",
            operation="vision_analyze",
            payload={"success": False, "request": request.model_dump(), "error": str(exc)},
            name_hint=request.app_name or image_path.stem,
        )
        return APIResponse(
            success=False,
            message="Vision analysis failed",
            data={"trace_path": trace_path},
            error=ErrorModel(code="vision_analyze_failed", details=str(exc)),
        )


@router.post("/page_structure", response_model=APIResponse)
def page_structure(request: VisionAnalyzeRequestModel) -> APIResponse:
    image_path = Path(request.image_path)
    if not image_path.exists():
        return APIResponse(
            success=False,
            message="Image path not found",
            data=None,
            error=ErrorModel(code="image_not_found", details=str(image_path)),
        )

    try:
        config = VisionProviderFactory.load_config()
        provider = VisionProviderFactory.create(mode=request.provider_mode, config=config)
        response = provider.analyze(
            VisionAnalyzeRequest(
                image_path=str(image_path),
                task=request.task,
                app_name=request.app_name,
                goal=request.goal,
                state_hint=request.state_hint,
                provider_mode=request.provider_mode,
                metadata=request.metadata,
            )
        )
        response, ocr_result, refine_options = _maybe_refine_with_ocr(response, request=request, image_path=image_path)
        normalized = normalizer.normalize(response.to_dict(), response.provider)
        if normalized.image_size is None:
            with Image.open(image_path) as image:
                normalized.image_size = ImageSize(width=image.width, height=image.height)
        if ocr_result is None:
            ocr_result = ocr_service.scan_image(str(image_path))
        structure = build_page_structure(normalized, ocr_result)
        result_payload = structure.to_dict()
        result_payload["execution_path"] = _vision_execution_path(
            requested_mode=request.provider_mode or str((config.get("vision") or {}).get("mode") or "local"),
            response_provider=response.provider,
            raw_response=response.raw_response,
            page_structure_generated=True,
            ocr_region_refine_used=refine_options.enabled,
        )
        result_payload["trace_path"] = write_trace(
            category="vision",
            operation="page_structure",
            payload={"success": True, "request": request.model_dump(), "result": result_payload},
            name_hint=request.app_name or image_path.stem,
        )
        data = VisionResultData(result=result_payload)
        return APIResponse(success=True, message="Page structure completed", data=data.model_dump(), error=None)
    except Exception as exc:
        trace_path = write_trace(
            category="vision",
            operation="page_structure",
            payload={"success": False, "request": request.model_dump(), "error": str(exc)},
            name_hint=request.app_name or image_path.stem,
        )
        return APIResponse(
            success=False,
            message="Page structure failed",
            data={"trace_path": trace_path},
            error=ErrorModel(code="page_structure_failed", details=str(exc)),
        )


@router.post("/screen_reading", response_model=APIResponse)
def screen_reading(request: VisionAnalyzeRequestModel) -> APIResponse:
    image_path = Path(request.image_path)
    if not image_path.exists():
        return APIResponse(
            success=False,
            message="Image path not found",
            data=None,
            error=ErrorModel(code="image_not_found", details=str(image_path)),
        )

    try:
        config = VisionProviderFactory.load_config()
        provider = VisionProviderFactory.create(mode=request.provider_mode, config=config)
        response = provider.analyze(
            VisionAnalyzeRequest(
                image_path=str(image_path),
                task=request.task,
                app_name=request.app_name,
                goal=request.goal,
                state_hint=request.state_hint,
                provider_mode=request.provider_mode,
                metadata=request.metadata,
            )
        )
        response, ocr_result, refine_options = _maybe_refine_with_ocr(response, request=request, image_path=image_path)
        normalized = normalizer.normalize(response.to_dict(), response.provider)
        if normalized.image_size is None:
            with Image.open(image_path) as image:
                normalized.image_size = ImageSize(width=image.width, height=image.height)
        if ocr_result is None:
            ocr_result = ocr_service.scan_image(str(image_path))
        structure = build_page_structure(normalized, ocr_result)
        uia_snapshot = uia_provider.snapshot_bound_window()
        result_payload = build_screen_reading(
            image_path=str(image_path),
            vision=normalized,
            ocr=ocr_result,
            page_structure=structure,
            app_name=request.app_name,
            uia_snapshot=uia_snapshot,
        )
        result_payload["execution_path"] = {
            **_vision_execution_path(
                requested_mode=request.provider_mode or str((config.get("vision") or {}).get("mode") or "local"),
                response_provider=response.provider,
                raw_response=response.raw_response,
                page_structure_generated=True,
                ocr_region_refine_used=refine_options.enabled,
            ),
            "screen_reading_used": True,
            "ui_provider_slots_available": True,
            "uia_provider_connected": True,
            "uia_scan_status": uia_snapshot.get("status"),
        }
        result_payload["trace_path"] = write_trace(
            category="vision",
            operation="screen_reading",
            payload={"success": True, "request": request.model_dump(), "result": result_payload},
            name_hint=request.app_name or image_path.stem,
        )
        data = VisionResultData(result=result_payload)
        return APIResponse(success=True, message="Screen reading completed", data=data.model_dump(), error=None)
    except Exception as exc:
        trace_path = write_trace(
            category="vision",
            operation="screen_reading",
            payload={"success": False, "request": request.model_dump(), "error": str(exc)},
            name_hint=request.app_name or image_path.stem,
        )
        return APIResponse(
            success=False,
            message="Screen reading failed",
            data={"trace_path": trace_path},
            error=ErrorModel(code="screen_reading_failed", details=str(exc)),
        )


@router.post("/observe_screen", response_model=APIResponse)
def observe_screen(request: VisionObserveScreenRequestModel) -> APIResponse:
    """Capture or read a screen and return broad UI understanding for agent planning."""
    timer = RuntimeTimer()
    try:
        with timer.step("resolve_image_source", capture_live=request.capture_live):
            image_path, live_capture = _image_path_for_live_or_saved(
                capture_live=request.capture_live,
                image_path=request.image_path,
                purpose="observe_screen",
                app_name=request.app_name,
            )
        screen_request = VisionAnalyzeRequestModel(
            image_path=image_path,
            task=request.task,
            app_name=request.app_name,
            goal="understand the current interface, visible controls, and likely actions",
            state_hint=request.state_hint,
            provider_mode=request.provider_mode or "local_understanding",
            metadata={
                **dict(request.metadata or {}),
                "ocr_anchors": {"enabled": True, "max_anchors": "all", **dict((request.metadata or {}).get("ocr_anchors") or {})}
                if isinstance((request.metadata or {}).get("ocr_anchors"), dict)
                else (request.metadata or {}).get("ocr_anchors", {"enabled": True, "max_anchors": "all"}),
            },
        )
        with timer.step("screen_reading"):
            response = screen_reading(screen_request)
        if not response.success or not response.data:
            if isinstance(response.data, dict):
                response.data["timings"] = timer.to_dict()
            return response
        result = response.data["result"]
        result["contract_version"] = "screen_observation_v1"
        result["live_capture"] = live_capture
        result["suggested_state_hint"] = _suggested_state_hint_from_observation(result)
        result["screen_map"] = _build_screen_map_from_observation(result, request=request, image_path=image_path)
        result["agent_next_steps"] = [
            "Read screen_map.candidates to decide what the user likely wants; it is a semantic map, not executable coordinates.",
            "Use screen_map.state_id and suggested_state_hint as the default context for POST /vision/locate_target unless the user overrides it.",
            "When a concrete target is chosen, call POST /vision/locate_target with that candidate label/goal.",
            "Execute only through POST /action/execute_recognition_plan after pre_click_decision allows it.",
        ]
        result["timings"] = timer.to_dict()
        result["trace_path"] = write_trace(
            category="vision",
            operation="observe_screen",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint=request.app_name or Path(image_path).stem,
        )
        data = VisionResultData(result=result)
        return APIResponse(success=True, message="Screen observation completed", data=data.model_dump(), error=None)
    except Exception as exc:
        timings = timer.to_dict()
        trace_path = write_trace(
            category="vision",
            operation="observe_screen",
            payload={"success": False, "request": request.model_dump(), "error": str(exc), "timings": timings},
            name_hint=request.app_name or "observe_screen",
        )
        return APIResponse(
            success=False,
            message="Screen observation failed",
            data={"trace_path": trace_path, "timings": timings},
            error=ErrorModel(code="observe_screen_failed", details=str(exc)),
        )


def _suggested_state_hint_from_observation(result: dict[str, Any]) -> str:
    for value in (result.get("state_guess"), result.get("screen_summary")):
        hint = _compact_state_hint(value)
        if hint:
            return hint
    screen_reading = result.get("screen_reading") if isinstance(result.get("screen_reading"), dict) else {}
    for value in (screen_reading.get("state_guess"), screen_reading.get("screen_summary")):
        hint = _compact_state_hint(value)
        if hint:
            return hint
    return ""


def _compact_state_hint(value: Any) -> str:
    text = " ".join(str(value or "").strip().split())
    if not text or text.casefold() in {"unknown", "none", "null"}:
        return ""
    return text[:80]


def _build_screen_map_from_observation(result: dict[str, Any], *, request: VisionObserveScreenRequestModel, image_path: str) -> dict[str, Any]:
    screen_reading = result.get("screen_reading") if isinstance(result.get("screen_reading"), dict) else {}
    screen_summary = (
        result.get("screen_summary")
        or screen_reading.get("screen_summary")
        or result.get("message")
        or ""
    )
    state_hint = result.get("suggested_state_hint") or _suggested_state_hint_from_observation(result)
    sections = _screen_map_sections(result)
    candidates = _screen_map_candidates(result, sections=sections)
    app_name = request.app_name or result.get("app_name") or screen_reading.get("app_name") or ""
    signature = _screen_state_signature(
        app_name=app_name,
        state_hint=state_hint,
        screen_summary=screen_summary,
        image_path=image_path,
        candidates=candidates,
    )
    return {
        "contract_version": "screen_map_v1",
        "state_id": signature["state_id"],
        "app_name": app_name,
        "image_path": image_path,
        "state_hint": state_hint,
        "summary": {
            "screen_summary": screen_summary,
            "candidate_count": len(candidates),
            "safe_candidate_count": len([item for item in candidates if item.get("risk_class") == "safe_click_allowed"]),
            "blocked_candidate_count": len([item for item in candidates if item.get("risk_class") == "blocked"]),
            "section_count": len(sections),
        },
        "state_signature": signature,
        "sections": sections,
        "candidates": candidates,
        "agent_usage": {
            "observe_role": "Build the semantic page/action map.",
            "locate_role": "Locate one selected screen_map candidate precisely before any click.",
            "execute_role": "Verify the selected point and post-click transition through the gated action API.",
        },
    }


def _screen_map_sections(result: dict[str, Any]) -> list[dict[str, Any]]:
    image_size = result.get("image_size") if isinstance(result.get("image_size"), dict) else {}
    live_capture = result.get("live_capture") if isinstance(result.get("live_capture"), dict) else {}
    width = int(_number(image_size.get("width") or live_capture.get("image_width")) or 0)
    height = int(_number(image_size.get("height") or live_capture.get("image_height")) or 0)
    if width <= 0:
        width = _max_text_edge(result, axis="x") or 1000
    if height <= 0:
        height = _max_text_edge(result, axis="y") or 1000

    browser_chrome_bottom = min(height, max(80, round(height * 0.085)))
    page_header_bottom = min(height, max(browser_chrome_bottom + 70, round(height * 0.17)))
    promo_bottom = min(height, max(page_header_bottom + 90, round(height * 0.30)))
    main_bottom = min(height, max(promo_bottom + 260, round(height * 0.86)))

    sections = [
        _screen_map_section(
            "browser_chrome",
            "Browser chrome",
            "browser",
            "Browser tabs, address bar, and extension controls.",
            {"x": 0, "y": 0, "w": width, "h": browser_chrome_bottom},
            result,
        ),
        _screen_map_section(
            "page_header",
            "Top navigation",
            "navigation",
            "Website header, logo, language controls, and top navigation tabs.",
            {"x": 0, "y": browser_chrome_bottom, "w": width, "h": max(1, page_header_bottom - browser_chrome_bottom)},
            result,
        ),
        _screen_map_section(
            "promo_strip",
            "Promotion strip",
            "content",
            "Horizontal promotional or feature cards above the main tool area.",
            {"x": 0, "y": page_header_bottom, "w": width, "h": max(1, promo_bottom - page_header_bottom)},
            result,
        ),
        _screen_map_section(
            "main_content",
            "Main content",
            "content",
            "Primary page body with tool cards, panels, forms, and test areas.",
            {"x": 0, "y": promo_bottom, "w": width, "h": max(1, main_bottom - promo_bottom)},
            result,
        ),
    ]
    if main_bottom < height:
        sections.append(
            _screen_map_section(
                "lower_content",
                "Lower content",
                "content",
                "Content below the first viewport's main card area.",
                {"x": 0, "y": main_bottom, "w": width, "h": max(1, height - main_bottom)},
                result,
            )
        )
    floating = _floating_overlay_section(result, width=width, height=height)
    if floating:
        sections.append(floating)
    return sections


def _screen_map_section(section_id: str, label: str, role: str, description: str, bbox: dict[str, int], result: dict[str, Any]) -> dict[str, Any]:
    texts = _texts_in_bbox(_screen_map_texts(result), bbox)
    return {
        "contract_version": "screen_map_section_v1",
        "section_id": section_id,
        "label": label,
        "role": role,
        "description": description,
        "bbox": bbox,
        "text_count": len(texts),
        "text_sample": [_first_compact_text(item.get("text")) for item in texts[:10] if _first_compact_text(item.get("text"))],
    }


def _floating_overlay_section(result: dict[str, Any], *, width: int, height: int) -> dict[str, Any] | None:
    texts = _screen_map_texts(result)
    bottom_right = []
    for text in texts:
        bbox = _normalize_map_bbox(text.get("bbox"))
        if not bbox:
            continue
        cx = bbox["x"] + bbox["w"] / 2
        cy = bbox["y"] + bbox["h"] / 2
        if cx > width * 0.72 and cy > height * 0.65:
            label = str(text.get("text") or "")
            if label and any(token in label.casefold() for token in ["video", "help", "帮助", "房间", "密码", "join", "加入"]):
                bottom_right.append(text)
    if not bottom_right:
        return None
    bbox = _bbox_union([_normalize_map_bbox(item.get("bbox")) for item in bottom_right])
    if not bbox:
        return None
    padded = _pad_bbox(bbox, pad=28, max_width=width, max_height=height)
    return _screen_map_section(
        "floating_overlay",
        "Floating overlay",
        "overlay",
        "Floating widget or overlay above the page content.",
        padded,
        result,
    )


def _screen_map_text_candidates(result: dict[str, Any], *, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for index, text_item in enumerate(_screen_map_texts(result)):
        if not isinstance(text_item, dict):
            continue
        label = _normalize_ocr_candidate_label(_first_compact_text(text_item.get("text")))
        bbox = _normalize_map_bbox(text_item.get("bbox"))
        confidence = _bounded_float(text_item.get("confidence"))
        if not label or not bbox:
            continue
        section_id = _section_id_for_bbox(bbox, sections)
        role = _ocr_text_candidate_role(label, bbox, section_id=section_id)
        if not role:
            continue
        min_confidence = 0.5 if section_id == "page_header" else (0.6 if len(label) <= 4 else 0.72)
        if confidence is not None and confidence < min_confidence:
            continue
        candidates.append(
            {
                "id": f"ocr_{text_item.get('id') or index}",
                "text_id": text_item.get("id"),
                "label": label,
                "type": role,
                "bbox": bbox,
                "click_point": _normalize_map_point(None, bbox),
                "confidence": confidence,
                "interaction_policy": {
                    "allowed": True if role in {"text_action", "nav_text_action"} else None,
                    "reasons": ["ocr_text_candidate"],
                },
                "verification_hints": {"expected_changes": [_expected_effect_for_ocr_text(label, role)]},
                "evidence_level": "ocr_text_only",
                "screen_map_rule": "header_text_is_button" if section_id == "page_header" else "ocr_action_text",
            }
        )
    return candidates


def _screen_map_texts(result: dict[str, Any]) -> list[dict[str, Any]]:
    texts: list[dict[str, Any]] = []
    seen: set[str] = set()
    screen_reading = result.get("screen_reading") if isinstance(result.get("screen_reading"), dict) else {}
    for source in (result.get("texts"), screen_reading.get("texts")):
        for item in _as_list(source):
            if not isinstance(item, dict):
                continue
            key = str(item.get("id") or item.get("text") or "") + "|" + str(item.get("bbox") or "")
            if key in seen:
                continue
            seen.add(key)
            texts.append(item)
    return texts


def _normalize_ocr_candidate_label(label: str) -> str:
    return str(label or "").strip().strip("·•・-—→ ").strip()


def _ocr_text_candidate_role(label: str, bbox: dict[str, int], *, section_id: str | None = None) -> str | None:
    text = label.strip()
    lowered = text.casefold()
    if bbox["y"] < 90:
        return None
    if section_id == "page_header":
        if _screen_map_text_is_noise(text, allow_short=True):
            return None
        return "nav_text_action"
    if bbox["y"] < 180 and ("." in text or "mousetester" in lowered):
        return None
    if len(text) > 24:
        return None
    if any(mark in text for mark in ["、", "，", ","]) and not text.startswith(("点击", "立即")):
        return None
    if "峰值" in text or "成功次数" in text or "上次间隔" in text:
        return None
    action_terms = [
        "click",
        "start",
        "open",
        "apply",
        "test",
        "reset",
        "join",
        "点击",
        "开始",
        "测试",
        "重置",
        "左键",
        "中键",
        "右键",
        "前进",
        "后退",
        "加入",
    ]
    card_terms = [
        "dpi",
        "cps",
        "hz",
        "回报率",
        "双击",
        "按键",
        "滚轮",
        "平滑度",
        "灵敏度",
        "键盘",
        "白噪音",
    ]
    if any(term in lowered or term in text for term in action_terms):
        return "nav_text_action" if bbox["y"] < 180 else "text_action"
    if bbox["y"] >= 250 and any(term in lowered or term in text for term in card_terms):
        return "content_card"
    return None


def _screen_map_text_is_noise(text: str, *, allow_short: bool = False) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    lowered = value.casefold()
    if "://" in lowered or lowered.startswith("http"):
        return True
    if len(value) == 1 and not allow_short:
        return True
    if len(value) == 1 and allow_short and not value.isalnum():
        return True
    if all(not char.isalnum() for char in value):
        return True
    return False


def _screen_map_card_candidates(result: dict[str, Any], *, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    text_items = _screen_map_texts(result)
    section_by_id = {str(section.get("section_id")): section for section in sections if isinstance(section, dict)}
    for section_id in ("main_content", "promo_strip", "lower_content"):
        section = section_by_id.get(section_id)
        section_bbox = _normalize_map_bbox((section or {}).get("bbox"))
        if not section_bbox:
            continue
        section_texts = _texts_in_bbox(text_items, section_bbox)
        seed_boxes = [
            bbox
            for item in section_texts
            if (bbox := _normalize_map_bbox(item.get("bbox")))
            and _is_card_seed_label(_normalize_ocr_candidate_label(_first_compact_text(item.get("text"))), section_id=section_id)
        ]
        used_centers: list[dict[str, int]] = []
        for index, text_item in enumerate(section_texts):
            seed_bbox = _normalize_map_bbox(text_item.get("bbox"))
            label = _normalize_ocr_candidate_label(_first_compact_text(text_item.get("text")))
            if not seed_bbox or not _is_card_seed_label(label, section_id=section_id):
                continue
            seed_center = _normalize_map_point(None, seed_bbox)
            if seed_center and any(_point_inside_bbox(seed_center, used) for used in used_centers):
                continue
            card_bbox = _card_bbox_for_seed(section_texts, seed_bbox=seed_bbox, seed_boxes=seed_boxes, section_bbox=section_bbox)
            if not card_bbox:
                continue
            used_centers.append(card_bbox)
            card_texts = _texts_in_bbox(section_texts, card_bbox)
            candidates.append(
                {
                    "id": f"card_{section_id}_{index}",
                    "label": label,
                    "type": "content_card",
                    "bbox": card_bbox,
                    "click_point": _normalize_map_point(None, card_bbox),
                    "confidence": _bounded_float(text_item.get("confidence")) or 0.75,
                    "interaction_policy": {
                        "allowed": None,
                        "reasons": ["card_group_candidate", f"section:{section_id}"],
                    },
                    "verification_hints": {"expected_changes": [f"open or focus the {label} card"]},
                    "evidence_level": "ocr_grouped_card",
                    "text_id": text_item.get("id"),
                    "screen_map_rule": "card_texts_grouped_as_single_candidate",
                    "text_sample": [_first_compact_text(item.get("text")) for item in card_texts[:8] if _first_compact_text(item.get("text"))],
                    "text_count": len(card_texts),
                }
            )
    return candidates


def _is_card_seed_label(label: str, *, section_id: str) -> bool:
    text = str(label or "").strip()
    if _screen_map_text_is_noise(text):
        return False
    lowered = text.casefold()
    if any(text.startswith(prefix) for prefix in ("点击", "检测", "测试鼠标", "请输入", "输入")):
        return False
    if section_id == "promo_strip":
        return len(text) >= 3 and any(term in text or term in lowered for term in ["测试", "工具", "dpi", "cps", "延迟", "灵敏度", "白噪音", "键盘"])
    return any(
        term in text or term in lowered
        for term in [
            "测试",
            "按键",
            "滚轮",
            "回报率",
            "双击",
            "轮询率",
            "平滑度",
            "灵敏度",
            "dpi",
            "cps",
            "hz",
            "键盘",
            "白噪音",
            "建房",
            "加入",
        ]
    )


def _card_bbox_for_seed(
    texts: list[dict[str, Any]],
    *,
    seed_bbox: dict[str, int],
    seed_boxes: list[dict[str, int]],
    section_bbox: dict[str, int],
) -> dict[str, int] | None:
    seed_cx = seed_bbox["x"] + seed_bbox["w"] / 2
    half_width = min(260, max(150, int(section_bbox["w"] * 0.11)))
    x1 = max(section_bbox["x"], int(seed_cx - half_width))
    x2 = min(section_bbox["x"] + section_bbox["w"], int(seed_cx + half_width))
    x1, x2 = _card_column_bounds(seed_bbox=seed_bbox, seed_boxes=seed_boxes, fallback_x1=x1, fallback_x2=x2, section_bbox=section_bbox)
    y1 = max(section_bbox["y"], seed_bbox["y"] - 24)
    y2 = min(section_bbox["y"] + section_bbox["h"], seed_bbox["y"] + max(120, int(section_bbox["h"] * 0.34)))
    cluster: list[dict[str, int]] = [seed_bbox]
    for text_item in texts:
        bbox = _normalize_map_bbox(text_item.get("bbox"))
        if not bbox:
            continue
        cx = bbox["x"] + bbox["w"] / 2
        cy = bbox["y"] + bbox["h"] / 2
        if x1 <= cx <= x2 and y1 <= cy <= y2:
            cluster.append(bbox)
    bbox = _bbox_union(cluster)
    if not bbox:
        return None
    return _pad_bbox(bbox, pad=18, max_width=section_bbox["x"] + section_bbox["w"], max_height=section_bbox["y"] + section_bbox["h"])


def _card_column_bounds(
    *,
    seed_bbox: dict[str, int],
    seed_boxes: list[dict[str, int]],
    fallback_x1: int,
    fallback_x2: int,
    section_bbox: dict[str, int],
) -> tuple[int, int]:
    seed_cx = seed_bbox["x"] + seed_bbox["w"] / 2
    seed_cy = seed_bbox["y"] + seed_bbox["h"] / 2
    row_peers = [
        box
        for box in seed_boxes
        if abs((box["y"] + box["h"] / 2) - seed_cy) <= 80
    ]
    centers = sorted({round(box["x"] + box["w"] / 2) for box in row_peers})
    if len(centers) < 2:
        return fallback_x1, fallback_x2
    center = round(seed_cx)
    left_centers = [item for item in centers if item < center]
    right_centers = [item for item in centers if item > center]
    left_bound = section_bbox["x"]
    right_bound = section_bbox["x"] + section_bbox["w"]
    if left_centers:
        left_bound = max(left_bound, int(round((left_centers[-1] + center) / 2)))
    if right_centers:
        right_bound = min(right_bound, int(round((right_centers[0] + center) / 2)))
    return max(fallback_x1, left_bound), min(fallback_x2, right_bound)


def _point_inside_bbox(point: dict[str, int], bbox: dict[str, int]) -> bool:
    return bbox["x"] <= point["x"] <= bbox["x"] + bbox["w"] and bbox["y"] <= point["y"] <= bbox["y"] + bbox["h"]


def _expected_effect_for_ocr_text(label: str, role: str) -> str:
    if role == "content_card":
        return f"open or focus the {label} section"
    return f"activate {label}"


def _screen_map_candidates(result: dict[str, Any], *, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources: list[tuple[str, list[Any]]] = []
    screen_reading = result.get("screen_reading") if isinstance(result.get("screen_reading"), dict) else {}
    ui = screen_reading.get("ui") if isinstance(screen_reading.get("ui"), dict) else {}
    sources.append(("screen_reading.ui.elements", _as_list(ui.get("elements"))))
    sources.append(("screen_reading.ui.icon_candidates", _as_list(ui.get("icon_candidates"))))
    sources.append(("screen_reading.ui_elements", _as_list(screen_reading.get("ui_elements"))))
    sources.append(("top_level.ui.elements", _as_list(result.get("ui", {}).get("elements") if isinstance(result.get("ui"), dict) else None)))
    sources.append(("top_level.ui.icon_candidates", _as_list(result.get("ui", {}).get("icon_candidates") if isinstance(result.get("ui"), dict) else None)))
    sources.append(("top_level.ui_elements", _as_list(result.get("ui_elements"))))
    sources.append(("top_level.elements", _as_list(result.get("elements"))))
    sources.append(("top_level.controls", _as_list(result.get("controls"))))
    sources.append(("ocr_card_groups", _screen_map_card_candidates(result, sections=sections)))
    sources.append(("ocr_text_actions", _screen_map_text_candidates(result, sections=sections)))

    seen: set[str] = set()
    candidates: list[dict[str, Any]] = []
    for source_name, items in sources:
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            candidate = _screen_map_candidate(item, source=source_name, index=index, sections=sections)
            if candidate is None:
                continue
            dedupe_key = f"{candidate['label']}|{candidate.get('bbox')}"
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            candidates.append(candidate)
    return candidates[:80]


def _screen_map_candidate(item: dict[str, Any], *, source: str, index: int, sections: list[dict[str, Any]]) -> dict[str, Any] | None:
    label = _first_compact_text(
        item.get("label"),
        item.get("text"),
        item.get("name"),
        item.get("title"),
        item.get("description"),
        item.get("role_guess"),
        item.get("role"),
        item.get("type"),
    )
    label = _normalize_ocr_candidate_label(label)
    if not label:
        return None
    bbox = _normalize_map_bbox(item.get("bbox") or item.get("bounding_box") or item.get("bounds") or item.get("rect") or item.get("region"))
    click_point = _normalize_map_point(item.get("click_point") or item.get("clickPoint"), bbox)
    role = _first_compact_text(item.get("type"), item.get("role_guess"), item.get("role"), item.get("control_type")) or "control"
    policy = _interaction_policy_from_item(item)
    risk_class, risk_reasons = _risk_class_for_candidate(label=label, role=role, policy=policy)
    expected_effect = _expected_effect_from_item(item, role=role)
    candidate_id = str(item.get("id") or item.get("element_id") or item.get("candidate_id") or f"screen_map_{index}")
    return {
        "contract_version": "screen_map_candidate_v1",
        "candidate_id": candidate_id[:100],
        "label": label,
        "role": role,
        "goal_hint": _goal_hint_for_candidate(label=label, role=role),
        "expected_effect": expected_effect,
        "risk_class": risk_class,
        "risk_reasons": risk_reasons,
        "section_id": _section_id_for_bbox(bbox, sections),
        "bbox": bbox,
        "click_point": click_point,
        "confidence": _bounded_float(item.get("confidence")),
        "source": source,
        "source_id": item.get("id") or item.get("element_id") or item.get("candidate_id"),
        "screen_map_rule": item.get("screen_map_rule"),
        "evidence": {
            "interaction_policy": policy,
            "coordinate_confidence": item.get("coordinate_confidence"),
            "evidence_level": item.get("evidence_level"),
            "memory_key": item.get("memory_key"),
            "source_text_id": item.get("text_id"),
            "screen_map_rule": item.get("screen_map_rule"),
        },
    }


def _interaction_policy_from_item(item: dict[str, Any]) -> dict[str, Any]:
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    policy = evidence.get("interaction_policy") if isinstance(evidence.get("interaction_policy"), dict) else {}
    if not policy and isinstance(item.get("interaction_policy"), dict):
        policy = item["interaction_policy"]
    return dict(policy)


def _risk_class_for_candidate(*, label: str, role: str, policy: dict[str, Any]) -> tuple[str, list[str]]:
    reasons = [str(item) for item in _as_list(policy.get("reasons")) if str(item or "").strip()]
    risk_text = " ".join([label, role, " ".join(reasons), str(policy.get("zone_type") or "")]).casefold()
    dangerous_terms = [
        "delete",
        "remove",
        "payment",
        "pay",
        "purchase",
        "send",
        "submit",
        "authorize",
        "permission",
        "close window",
        "删除",
        "移除",
        "支付",
        "购买",
        "发送",
        "提交",
        "授权",
        "关闭窗口",
    ]
    if any(term in risk_text for term in dangerous_terms):
        return "requires_user_confirmation", sorted(set([*reasons, "potential_side_effect_action"]))
    if policy.get("allowed") is False:
        return "blocked", sorted(set(reasons or ["interaction_policy_blocked"]))
    if policy.get("allowed") is True:
        return "safe_click_allowed", sorted(set(reasons))
    if any(token in str(role).casefold() for token in ["input", "textbox", "search"]):
        return "safe_click_allowed", sorted(set(reasons))
    return "safe_dry_run_only", sorted(set(reasons or ["requires_precise_location_before_click"]))


def _expected_effect_from_item(item: dict[str, Any], *, role: str) -> str:
    verification = item.get("verification_hints") if isinstance(item.get("verification_hints"), dict) else {}
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    evidence_verification = evidence.get("verification_hints") if isinstance(evidence.get("verification_hints"), dict) else {}
    for value in (
        item.get("expected_effect"),
        item.get("possible_navigation"),
        item.get("possible_destinations"),
        item.get("action"),
        item.get("interaction_type"),
        verification.get("expected_changes"),
        evidence_verification.get("expected_changes"),
    ):
        text = _first_compact_text(value)
        if text:
            return text
    role_text = str(role or "").casefold()
    if any(token in role_text for token in ["input", "textbox", "search"]):
        return "focus or edit input"
    return "click may change the current interface"


def _goal_hint_for_candidate(*, label: str, role: str) -> str:
    role_text = str(role or "control").replace("_", " ")
    return f"{role_text}: {label}"[:120]


def _section_id_for_bbox(bbox: dict[str, int] | None, sections: list[dict[str, Any]]) -> str | None:
    if not bbox:
        return None
    cx = bbox["x"] + bbox["w"] / 2
    cy = bbox["y"] + bbox["h"] / 2
    best_section = None
    best_score = -1
    for section in sections:
        section_bbox = _normalize_map_bbox(section.get("bbox"))
        if not section_bbox:
            continue
        inside = (
            section_bbox["x"] <= cx <= section_bbox["x"] + section_bbox["w"]
            and section_bbox["y"] <= cy <= section_bbox["y"] + section_bbox["h"]
        )
        overlap = _bbox_overlap_area(bbox, section_bbox)
        score = overlap + (1_000_000 if inside else 0)
        if score > best_score:
            best_score = score
            best_section = section
    return str(best_section.get("section_id")) if best_section else None


def _max_text_edge(result: dict[str, Any], *, axis: str) -> int | None:
    edge = 0
    for text in _screen_map_texts(result):
        bbox = _normalize_map_bbox(text.get("bbox"))
        if not bbox:
            continue
        if axis == "x":
            edge = max(edge, bbox["x"] + bbox["w"])
        else:
            edge = max(edge, bbox["y"] + bbox["h"])
    return edge or None


def _texts_in_bbox(texts: list[dict[str, Any]], bbox: dict[str, int]) -> list[dict[str, Any]]:
    selected = []
    for text in texts:
        text_bbox = _normalize_map_bbox(text.get("bbox"))
        if not text_bbox:
            continue
        cx = text_bbox["x"] + text_bbox["w"] / 2
        cy = text_bbox["y"] + text_bbox["h"] / 2
        if bbox["x"] <= cx <= bbox["x"] + bbox["w"] and bbox["y"] <= cy <= bbox["y"] + bbox["h"]:
            selected.append(text)
    selected.sort(key=lambda item: ((_normalize_map_bbox(item.get("bbox")) or {}).get("y", 0), (_normalize_map_bbox(item.get("bbox")) or {}).get("x", 0)))
    return selected


def _bbox_union(boxes: list[dict[str, int] | None]) -> dict[str, int] | None:
    valid = [box for box in boxes if box]
    if not valid:
        return None
    x1 = min(box["x"] for box in valid)
    y1 = min(box["y"] for box in valid)
    x2 = max(box["x"] + box["w"] for box in valid)
    y2 = max(box["y"] + box["h"] for box in valid)
    return {"x": x1, "y": y1, "w": max(1, x2 - x1), "h": max(1, y2 - y1)}


def _pad_bbox(bbox: dict[str, int], *, pad: int, max_width: int, max_height: int) -> dict[str, int]:
    x = max(0, bbox["x"] - pad)
    y = max(0, bbox["y"] - pad)
    x2 = min(max_width, bbox["x"] + bbox["w"] + pad)
    y2 = min(max_height, bbox["y"] + bbox["h"] + pad)
    return {"x": x, "y": y, "w": max(1, x2 - x), "h": max(1, y2 - y)}


def _bbox_overlap_area(a: dict[str, int], b: dict[str, int]) -> int:
    x1 = max(a["x"], b["x"])
    y1 = max(a["y"], b["y"])
    x2 = min(a["x"] + a["w"], b["x"] + b["w"])
    y2 = min(a["y"] + a["h"], b["y"] + b["h"])
    return max(0, x2 - x1) * max(0, y2 - y1)


def _screen_state_signature(*, app_name: str, state_hint: str, screen_summary: str, image_path: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    labels = [str(item.get("label") or "")[:60] for item in candidates[:20]]
    source = "|".join([app_name or "", state_hint or "", screen_summary or "", image_path or "", *labels])
    digest = hashlib.sha256(source.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return {
        "state_id": f"state_{digest}",
        "app_name": app_name,
        "state_hint": state_hint,
        "screen_summary_hash": hashlib.sha256(str(screen_summary or "").encode("utf-8", errors="ignore")).hexdigest()[:16],
        "image_path": image_path,
        "candidate_label_sample": labels[:12],
        "candidate_count": len(candidates),
    }


def _normalize_map_bbox(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    x = _number(value.get("x", value.get("left", value.get("x1"))))
    y = _number(value.get("y", value.get("top", value.get("y1"))))
    right = _number(value.get("right", value.get("x2")))
    bottom = _number(value.get("bottom", value.get("y2")))
    width = _number(value.get("w", value.get("width")))
    height = _number(value.get("h", value.get("height")))
    if width is None and right is not None and x is not None:
        width = right - x
    if height is None and bottom is not None and y is not None:
        height = bottom - y
    if x is None or y is None or width is None or height is None or width <= 0 or height <= 0:
        return None
    return {"x": int(round(x)), "y": int(round(y)), "w": int(round(width)), "h": int(round(height))}


def _normalize_map_point(value: Any, bbox: dict[str, int] | None) -> dict[str, int] | None:
    if isinstance(value, dict):
        x = _number(value.get("x"))
        y = _number(value.get("y"))
        if x is not None and y is not None:
            return {"x": int(round(x)), "y": int(round(y))}
    if bbox:
        return {"x": int(round(bbox["x"] + bbox["w"] / 2)), "y": int(round(bbox["y"] + bbox["h"] / 2))}
    return None


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _bounded_float(value: Any) -> float | None:
    number = _number(value)
    if number is None:
        return None
    return round(max(0.0, min(1.0, number)), 4)


def _first_compact_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, list):
            text = "; ".join(str(item).strip() for item in value if str(item or "").strip())
        else:
            text = str(value or "").strip()
        text = " ".join(text.split())
        if text:
            return text[:160]
    return ""


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


@router.post("/locate_target", response_model=APIResponse)
def locate_target(request: VisionLocateTargetRequestModel) -> APIResponse:
    """Precisely locate a chosen target without clicking."""
    timer = RuntimeTimer()
    try:
        with timer.step("resolve_image_source", capture_live=request.capture_live):
            image_path, live_capture = _image_path_for_live_or_saved(
                capture_live=request.capture_live,
                image_path=request.image_path,
                purpose="locate_target",
                app_name=request.app_name,
            )
        with timer.step("load_observe_trace_reuse", has_observe_trace=bool(request.observe_trace_path)):
            observe_reuse = _load_observe_trace_reuse(request.observe_trace_path, image_path=image_path, goal=request.goal)
        metadata = dict(request.metadata or {})
        if observe_reuse.get("status") == "ready":
            metadata["reused_ocr_anchors"] = observe_reuse["ocr_anchors"]
            metadata["reused_ocr_source_trace_path"] = observe_reuse["trace_path"]
            metadata["screen_map_context"] = {
                "state_id": observe_reuse.get("state_id"),
                "candidate_count": observe_reuse.get("candidate_count"),
                "source_trace_path": observe_reuse.get("trace_path"),
            }
        plan_request = VisionRecognitionPlanRequestModel(
            image_path=image_path,
            task=request.task,
            app_name=request.app_name,
            goal=request.goal,
            state_hint=request.state_hint,
            provider_mode=request.provider_mode or "local_grounding",
            metadata={
                **metadata,
                "ocr_anchors": {"enabled": True, "max_anchors": "all", **dict(metadata.get("ocr_anchors") or {})}
                if isinstance(metadata.get("ocr_anchors"), dict)
                else metadata.get("ocr_anchors", {"enabled": True, "max_anchors": "all"}),
            },
            top_k=request.top_k,
        )
        with timer.step("recognition_plan"):
            response = recognition_plan(plan_request)
        if not response.success or not response.data:
            if isinstance(response.data, dict):
                response.data["timings"] = timer.to_dict()
            return response
        result = response.data["result"]
        recommended_target = _locatable_target_from_plan_result(result)
        recommended_element = recommended_target.get("element") if isinstance(recommended_target, dict) else {}
        recommended_element = recommended_element if isinstance(recommended_element, dict) else {}
        selected_click_point = ((result.get("pre_click_decision") or {}).get("selected_click_point"))
        located_bbox = _locatable_bbox(recommended_target)
        located_point = selected_click_point if isinstance(selected_click_point, dict) else _locatable_point(recommended_target, located_bbox)
        located_source = str(recommended_target.get("location_source") or "recommended_target.element.click_point")
        locate_result = {
            "contract_version": "target_location_v1",
            "goal": request.goal,
            "image_path": image_path,
            "live_capture": live_capture,
            "recognition_plan": result,
            "pre_click_decision": result.get("pre_click_decision"),
            "selected_click_point": selected_click_point,
            "recommended_target": recommended_target,
            "located_bbox": located_bbox,
            "located_point": located_point,
            "location_status": "pre_click_verified" if selected_click_point else ("requires_pre_click_confirmation" if located_point else "not_located"),
            "observe_trace_reuse": {
                key: value
                for key, value in observe_reuse.items()
                if key not in {"ocr_anchors", "screen_map"}
            },
            "execution_path": {
                **dict(result.get("execution_path") or {}),
                "action_executed": False,
                "coordinate_source": "pre_click_decision_v1.selected_click_point",
                "located_coordinate_source": located_source,
                "ocr_anchor_reused_from_observe": observe_reuse.get("status") == "ready",
                "ocr_anchor_reuse_source": observe_reuse.get("anchor_source"),
                "ocr_anchor_reuse_trace_path": observe_reuse.get("trace_path") if observe_reuse.get("status") == "ready" else None,
                "agent_must_call_for_click": "POST /action/execute_recognition_plan",
            },
        }
        locate_result["timings"] = timer.to_dict()
        locate_result["trace_path"] = write_trace(
            category="vision",
            operation="locate_target",
            payload={"success": True, "request": request.model_dump(), "result": locate_result},
            name_hint=request.app_name or Path(image_path).stem,
        )
        data = VisionResultData(result=locate_result)
        return APIResponse(success=True, message="Target located", data=data.model_dump(), error=None)
    except Exception as exc:
        timings = timer.to_dict()
        trace_path = write_trace(
            category="vision",
            operation="locate_target",
            payload={"success": False, "request": request.model_dump(), "error": str(exc), "timings": timings},
            name_hint=request.app_name or "locate_target",
        )
        return APIResponse(
            success=False,
            message="Target location failed",
            data={"trace_path": trace_path, "timings": timings},
            error=ErrorModel(code="locate_target_failed", details=str(exc)),
        )


def _locatable_target_from_plan_result(result: dict[str, Any]) -> dict[str, Any]:
    recommended = result.get("recommended_target") if isinstance(result.get("recommended_target"), dict) else {}
    if isinstance(recommended.get("element"), dict):
        recommended.setdefault("location_source", "recommended_target.element.click_point")
        return recommended

    candidate_result = result.get("candidate_result") if isinstance(result.get("candidate_result"), dict) else {}
    for source_key, source_name in (("candidates", "candidate_result.candidates[0]"), ("rejected", "candidate_result.rejected[0]")):
        candidates = candidate_result.get(source_key) if isinstance(candidate_result.get(source_key), list) else []
        for candidate in candidates:
            if not isinstance(candidate, dict) or not isinstance(candidate.get("element"), dict):
                continue
            candidate = dict(candidate)
            candidate["location_source"] = source_name
            return candidate
    return {}


def _locatable_bbox(target: dict[str, Any]) -> dict[str, Any] | None:
    refined = target.get("refined_bbox")
    if isinstance(refined, dict):
        return refined
    element = target.get("element") if isinstance(target.get("element"), dict) else {}
    bbox = element.get("bbox") if isinstance(element, dict) else None
    return bbox if isinstance(bbox, dict) else None


def _locatable_point(target: dict[str, Any], bbox: dict[str, Any] | None) -> dict[str, int] | None:
    element = target.get("element") if isinstance(target.get("element"), dict) else {}
    point = element.get("click_point") if isinstance(element, dict) else None
    if isinstance(point, dict):
        return {"x": int(point.get("x", 0)), "y": int(point.get("y", 0))}
    if not isinstance(bbox, dict):
        return None
    width = int(bbox.get("w", bbox.get("width", 0)) or 0)
    height = int(bbox.get("h", bbox.get("height", 0)) or 0)
    if width <= 0 or height <= 0:
        return None
    return {"x": int(bbox.get("x", 0)) + width // 2, "y": int(bbox.get("y", 0)) + height // 2}


@router.post("/recognition_plan", response_model=APIResponse)
def recognition_plan(request: VisionRecognitionPlanRequestModel) -> APIResponse:
    timer = RuntimeTimer()
    image_path = Path(request.image_path)
    if not image_path.exists():
        timings = timer.to_dict()
        return APIResponse(
            success=False,
            message="Image path not found",
            data={"timings": timings},
            error=ErrorModel(code="image_not_found", details=str(image_path)),
        )

    try:
        with timer.step("load_vision_provider"):
            config = VisionProviderFactory.load_config()
            provider = VisionProviderFactory.create(mode=request.provider_mode, config=config)
        with timer.step("read_image_size"):
            with Image.open(image_path) as image:
                input_image_size = ImageSize(width=image.width, height=image.height)
        with timer.step("prepare_ocr_anchors"):
            vision_request, ocr_result, ocr_anchor_payload, ocr_anchor_status = _recognition_vision_request_with_ocr_anchors(
                request,
                image_path=image_path,
                image_size=input_image_size,
            )
        try:
            with timer.step("vision_provider_analyze", provider_mode=request.provider_mode):
                response = provider.analyze(vision_request)
        except Exception as exc:
            if not ocr_anchor_status.get("used"):
                raise
            ocr_anchor_status.update({"used": False, "fallback_used": True, "provider_error": str(exc)})
            ocr_anchor_payload = None
            with timer.step("vision_provider_analyze_without_ocr_anchors", provider_mode=request.provider_mode):
                response = provider.analyze(_vision_request_without_ocr_anchors(request, image_path=image_path))
        with timer.step("ocr_region_refine"):
            response, refine_ocr_result, refine_options = _maybe_refine_with_ocr(response, request=request, image_path=image_path)
        if refine_ocr_result is not None:
            ocr_result = refine_ocr_result
        with timer.step("normalize_vision_regions", provider=response.provider):
            normalized = normalizer.normalize(response.to_dict(), response.provider)
        if normalized.image_size is None:
            normalized.image_size = input_image_size
        with timer.step("anchor_grounding_evaluation", anchor_count=ocr_anchor_status.get("anchor_count")):
            normalized = apply_anchor_grounding_evaluation(normalized, ocr_anchor_payload)
        if ocr_result is None:
            with timer.step("ocr_scan"):
                ocr_result = ocr_service.scan_image(str(image_path))
        with timer.step("build_page_structure"):
            structure = build_page_structure(normalized, ocr_result)
        with timer.step("uia_snapshot"):
            uia_snapshot = uia_provider.snapshot_bound_window()
        with timer.step("build_screen_reading"):
            screen_reading_payload = build_screen_reading(
                image_path=str(image_path),
                vision=normalized,
                ocr=ocr_result,
                page_structure=structure,
                app_name=request.app_name,
                uia_snapshot=uia_snapshot,
            )
        goal = request.goal or request.task
        with timer.step("rank_candidates", top_k=request.top_k):
            candidate_result = rank_candidates(
                CandidateRankRequest(
                    goal=goal,
                    page_structure=structure,
                    top_k=request.top_k,
                    state_hint=request.state_hint,
                    screen_reading=screen_reading_payload,
                )
            )
        with timer.step("run_local_grounding", candidate_count=len(candidate_result.candidates)):
            narrow_search_result = run_local_grounding(
                LocalGroundingRequest(
                    image_path=str(image_path),
                    goal=goal,
                    candidates=candidate_result.candidates,
                    ocr_scan=ocr_service.scan_image,
                    app_name=request.app_name,
                )
            )
        with timer.step("pre_click_decision"):
            pre_click_decision = decide_pre_click(
                goal=goal,
                candidates=candidate_result,
                grounding=narrow_search_result,
            )
        recommended = candidate_result.candidates[0].to_dict() if candidate_result.candidates else None
        result_payload = {
            "contract_version": "recognition_plan_v1",
            "image_path": str(image_path),
            "goal": goal,
            "top_k": request.top_k,
            "parse_result": {
                "vision_regions": normalized.to_dict(),
                "ocr_result": ocr_result.to_dict(),
                "ocr_anchors": ocr_anchor_payload,
                "page_structure": structure.to_dict(),
                "screen_reading": screen_reading_payload,
            },
            "candidate_result": candidate_result.to_dict(),
            "narrow_search_result": narrow_search_result.to_dict(),
            "pre_click_decision": pre_click_decision.to_dict(),
            "verification_plan": {
                "status": "planned_not_executed",
                "pre_click_checks": [
                    "top_1_margin_to_second",
                    "candidate_policy_allowed",
                    "candidate_not_ad_like",
                    "click_point_inside_candidate_bbox",
                ],
                "post_click_checks": [
                    "ocr_change",
                    "content_change",
                    "focus_or_state_change",
                ],
            },
            "recommended_target": recommended,
            "execution_path": {
                **_vision_execution_path(
                    requested_mode=request.provider_mode or str((config.get("vision") or {}).get("mode") or "local"),
                    response_provider=response.provider,
                    raw_response=response.raw_response,
                    page_structure_generated=True,
                    ocr_region_refine_used=refine_options.enabled,
                ),
                "candidate_rank_used": True,
                "ocr_anchor_grounding_used": bool(ocr_anchor_status.get("used")),
                "ocr_anchor_grounding_fallback_used": bool(ocr_anchor_status.get("fallback_used")),
                "ocr_anchor_count": int(ocr_anchor_status.get("anchor_count") or 0),
                "screen_reading_used": True,
                "screen_reading_rank_evidence_used": True,
                "uia_scan_status": uia_snapshot.get("status"),
                "narrow_search_used": True,
                "pre_click_decision_used": True,
                "action_executed": False,
            },
        }
        result_payload["timings"] = timer.to_dict()
        result_payload["trace_path"] = write_trace(
            category="vision",
            operation="recognition_plan",
            payload={"success": True, "request": request.model_dump(), "result": result_payload},
            name_hint=request.app_name or image_path.stem,
        )
        data = VisionResultData(result=result_payload)
        return APIResponse(success=True, message="Recognition plan completed", data=data.model_dump(), error=None)
    except Exception as exc:
        timings = timer.to_dict()
        trace_path = write_trace(
            category="vision",
            operation="recognition_plan",
            payload={"success": False, "request": request.model_dump(), "error": str(exc), "timings": timings},
            name_hint=request.app_name or image_path.stem,
        )
        return APIResponse(
            success=False,
            message="Recognition plan failed",
            data={"trace_path": trace_path, "timings": timings},
            error=ErrorModel(code="recognition_plan_failed", details=str(exc)),
        )


@router.post("/layer_trace", response_model=APIResponse)
def layer_trace(request: VisionAnalyzeRequestModel) -> APIResponse:
    image_path = Path(request.image_path)
    trace: dict[str, object] = {
        "contract_version": "vision_layer_trace_v1",
        "image_path": str(image_path),
        "final_ok": False,
        "layers": [],
    }
    layers: list[dict[str, object]] = trace["layers"]  # type: ignore[assignment]

    image_size: ImageSize | None = None
    input_result: dict[str, object] = {
        "image_path": str(image_path),
        "image_exists": image_path.exists(),
        "image_size": None,
    }
    if image_path.exists():
        with Image.open(image_path) as image:
            image_size = ImageSize(width=image.width, height=image.height)
            input_result["image_size"] = image_size.to_dict()
    layers.append(
        make_layer(
            "input_image",
            input_result,
            validate_input_layer(input_result),
            summary={"image_exists": input_result["image_exists"], "image_size": input_result["image_size"]},
        )
    )
    if not image_path.exists():
        trace["trace_path"] = write_trace(
            category="vision",
            operation="layer_trace",
            payload={"success": False, "request": request.model_dump(), "result": trace},
            name_hint=request.app_name or image_path.stem,
        )
        data = VisionResultData(result=trace)  # type: ignore[arg-type]
        return APIResponse(success=True, message="Layer trace completed with failures", data=data.model_dump(), error=None)

    try:
        config = VisionProviderFactory.load_config()
        provider = VisionProviderFactory.create(mode=request.provider_mode, config=config)
        provider_response = provider.analyze(
            VisionAnalyzeRequest(
                image_path=str(image_path),
                task=request.task,
                app_name=request.app_name,
                goal=request.goal,
                state_hint=request.state_hint,
                provider_mode=request.provider_mode,
                metadata=request.metadata,
            )
        )
        provider_result = provider_response.to_dict()
        layers.append(
            make_layer(
                "vision_provider_raw",
                provider_result,
                validate_provider_layer(provider_result),
                summary=summarize_vision(provider_result),
            )
        )
    except Exception as exc:
        layers.append(failure_layer("vision_provider_raw", exc))
        trace["trace_path"] = write_trace(
            category="vision",
            operation="layer_trace",
            payload={"success": False, "request": request.model_dump(), "result": trace},
            name_hint=request.app_name or image_path.stem,
        )
        data = VisionResultData(result=trace)  # type: ignore[arg-type]
        return APIResponse(success=True, message="Layer trace completed with failures", data=data.model_dump(), error=None)

    try:
        normalized = normalizer.normalize(provider_result, provider_response.provider)
        if normalized.image_size is None and image_size is not None:
            normalized.image_size = image_size
        vision_result = normalized.to_dict()
        layers.append(
            make_layer(
                "vision_regions_v1",
                vision_result,
                validate_vision_regions_layer(vision_result),
                summary=summarize_vision(vision_result),
            )
        )
    except Exception as exc:
        layers.append(failure_layer("vision_regions_v1", exc))
        trace["trace_path"] = write_trace(
            category="vision",
            operation="layer_trace",
            payload={"success": False, "request": request.model_dump(), "result": trace},
            name_hint=request.app_name or image_path.stem,
        )
        data = VisionResultData(result=trace)  # type: ignore[arg-type]
        return APIResponse(success=True, message="Layer trace completed with failures", data=data.model_dump(), error=None)

    try:
        ocr_result = ocr_service.scan_image(str(image_path))
        ocr_payload = ocr_result.to_dict()
        layers.append(
            make_layer(
                "ocr_result",
                ocr_payload,
                validate_ocr_layer(ocr_payload),
                summary=summarize_ocr(ocr_payload),
            )
        )
    except Exception as exc:
        layers.append(failure_layer("ocr_result", exc))
        trace["trace_path"] = write_trace(
            category="vision",
            operation="layer_trace",
            payload={"success": False, "request": request.model_dump(), "result": trace},
            name_hint=request.app_name or image_path.stem,
        )
        data = VisionResultData(result=trace)  # type: ignore[arg-type]
        return APIResponse(success=True, message="Layer trace completed with failures", data=data.model_dump(), error=None)

    refine_options = parse_ocr_region_refine_options(request.metadata)
    vision_for_structure = normalized
    if refine_options.enabled:
        try:
            refined = refine_vision_regions_with_ocr(normalized, ocr_result, options=refine_options)
            refined_payload = refined.to_dict()
            layers.append(
                make_layer(
                    "vision_regions_refined_v1",
                    refined_payload,
                    validate_vision_regions_layer(refined_payload),
                    summary=summarize_vision(refined_payload),
                )
            )
            vision_for_structure = refined
        except Exception as exc:
            layers.append(failure_layer("vision_regions_refined_v1", exc))
            trace["trace_path"] = write_trace(
                category="vision",
                operation="layer_trace",
                payload={"success": False, "request": request.model_dump(), "result": trace},
                name_hint=request.app_name or image_path.stem,
            )
            data = VisionResultData(result=trace)  # type: ignore[arg-type]
            return APIResponse(success=True, message="Layer trace completed with failures", data=data.model_dump(), error=None)

    try:
        structure = build_page_structure(vision_for_structure, ocr_result)
        structure_payload = structure.to_dict()
        layers.append(
            make_layer(
                "page_structure_v1",
                structure_payload,
                validate_page_structure_layer(structure_payload),
                summary=summarize_page_structure(structure_payload),
            )
        )
    except Exception as exc:
        layers.append(failure_layer("page_structure_v1", exc))
        trace["trace_path"] = write_trace(
            category="vision",
            operation="layer_trace",
            payload={"success": False, "request": request.model_dump(), "result": trace},
            name_hint=request.app_name or image_path.stem,
        )
        data = VisionResultData(result=trace)  # type: ignore[arg-type]
        return APIResponse(success=True, message="Layer trace completed with failures", data=data.model_dump(), error=None)

    trace["final_ok"] = all(bool(layer.get("ok")) for layer in layers)
    trace["execution_path"] = _vision_execution_path(
        requested_mode=request.provider_mode or str((config.get("vision") or {}).get("mode") or "local"),
        response_provider=provider_response.provider,
        raw_response=provider_response.raw_response,
        page_structure_generated=True,
        ocr_region_refine_used=refine_options.enabled,
    )
    trace["trace_path"] = write_trace(
        category="vision",
        operation="layer_trace",
        payload={"success": bool(trace["final_ok"]), "request": request.model_dump(), "result": trace},
        name_hint=request.app_name or image_path.stem,
    )
    data = VisionResultData(result=trace)  # type: ignore[arg-type]
    return APIResponse(success=True, message="Layer trace completed", data=data.model_dump(), error=None)


@router.post("/render_review_overlay", response_model=APIResponse)
def render_review_overlay_route(request: VisionReviewOverlayRequestModel) -> APIResponse:
    trace_path = Path(request.trace_path)
    if not trace_path.exists():
        return APIResponse(
            success=False,
            message="Trace path not found",
            data=None,
            error=ErrorModel(code="trace_not_found", details=str(trace_path)),
        )

    try:
        overlay = render_review_overlay(
            trace_path=trace_path,
            region_layer=request.region_layer,
            include_regions=request.include_regions,
            include_ocr=request.include_ocr,
            label_regions=request.label_regions,
            label_ocr=request.label_ocr,
        )
        overlay["trace_path"] = write_trace(
            category="vision",
            operation="render_review_overlay",
            payload={"success": True, "request": request.model_dump(), "result": overlay},
            name_hint=trace_path.stem,
        )
        data = VisionResultData(result=overlay)
        return APIResponse(success=True, message="Review overlay rendered", data=data.model_dump(), error=None)
    except Exception as exc:
        trace_out = write_trace(
            category="vision",
            operation="render_review_overlay",
            payload={"success": False, "request": request.model_dump(), "error": str(exc)},
            name_hint=trace_path.stem,
        )
        return APIResponse(
            success=False,
            message="Review overlay failed",
            data={"trace_path": trace_out},
            error=ErrorModel(code="render_review_overlay_failed", details=str(exc)),
        )


@router.post("/render_recognition_plan_overlay", response_model=APIResponse)
def render_recognition_plan_overlay_route(request: VisionRecognitionPlanOverlayRequestModel) -> APIResponse:
    trace_path = Path(request.trace_path)
    if not trace_path.exists():
        return APIResponse(
            success=False,
            message="Trace path not found",
            data=None,
            error=ErrorModel(code="trace_not_found", details=str(trace_path)),
        )

    try:
        overlay = render_recognition_plan_overlay(
            trace_path=trace_path,
            include_rejected=request.include_rejected,
            include_points=request.include_points,
            label_candidates=request.label_candidates,
            label_reasons=request.label_reasons,
        )
        overlay["trace_path"] = write_trace(
            category="vision",
            operation="render_recognition_plan_overlay",
            payload={"success": True, "request": request.model_dump(), "result": overlay},
            name_hint=trace_path.stem,
        )
        data = VisionResultData(result=overlay)
        return APIResponse(success=True, message="Recognition plan overlay rendered", data=data.model_dump(), error=None)
    except Exception as exc:
        trace_out = write_trace(
            category="vision",
            operation="render_recognition_plan_overlay",
            payload={"success": False, "request": request.model_dump(), "error": str(exc)},
            name_hint=trace_path.stem,
        )
        return APIResponse(
            success=False,
            message="Recognition plan overlay failed",
            data={"trace_path": trace_out},
            error=ErrorModel(code="render_recognition_plan_overlay_failed", details=str(exc)),
        )
