from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from PIL import Image

from app.core.ocr_service import ocr_service
from app.core.runtime_artifacts import write_trace
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
from app.vision.ocr_anchors import build_ocr_anchor_payload
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
            ocr_result = ocr_service.scan_image(str(image_path))
            raw_options = metadata.get("ocr_anchors") if isinstance(metadata.get("ocr_anchors"), dict) else {}
            raw_max_anchors = raw_options.get("max_anchors") if isinstance(raw_options, dict) else None
            max_anchors = None if raw_max_anchors in (None, "all", "ALL", 0, "0") else int(raw_max_anchors)
            min_score = float(raw_options.get("min_score", 0.0)) if isinstance(raw_options, dict) else 0.0
            anchor_payload = build_ocr_anchor_payload(
                ocr_result,
                image_size=image_size,
                goal=request.goal or request.task,
                max_anchors=max_anchors,
                min_score=min_score,
            )
            metadata["ocr_anchors"] = anchor_payload
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
            "icon_library_provider_connected": True,
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
    try:
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
        response = screen_reading(screen_request)
        if not response.success or not response.data:
            return response
        result = response.data["result"]
        result["contract_version"] = "screen_observation_v1"
        result["live_capture"] = live_capture
        result["agent_next_steps"] = [
            "Read screen_reading.ui.elements and ui.icon_candidates to decide what the user likely wants.",
            "When a concrete target is chosen, call POST /vision/locate_target with that goal.",
            "Execute only through POST /action/execute_recognition_plan after pre_click_decision allows it.",
        ]
        result["trace_path"] = write_trace(
            category="vision",
            operation="observe_screen",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint=request.app_name or Path(image_path).stem,
        )
        data = VisionResultData(result=result)
        return APIResponse(success=True, message="Screen observation completed", data=data.model_dump(), error=None)
    except Exception as exc:
        trace_path = write_trace(
            category="vision",
            operation="observe_screen",
            payload={"success": False, "request": request.model_dump(), "error": str(exc)},
            name_hint=request.app_name or "observe_screen",
        )
        return APIResponse(
            success=False,
            message="Screen observation failed",
            data={"trace_path": trace_path},
            error=ErrorModel(code="observe_screen_failed", details=str(exc)),
        )


@router.post("/locate_target", response_model=APIResponse)
def locate_target(request: VisionLocateTargetRequestModel) -> APIResponse:
    """Precisely locate a chosen target without clicking."""
    try:
        image_path, live_capture = _image_path_for_live_or_saved(
            capture_live=request.capture_live,
            image_path=request.image_path,
            purpose="locate_target",
            app_name=request.app_name,
        )
        plan_request = VisionRecognitionPlanRequestModel(
            image_path=image_path,
            task=request.task,
            app_name=request.app_name,
            goal=request.goal,
            state_hint=request.state_hint,
            provider_mode=request.provider_mode or "local_grounding",
            metadata={
                **dict(request.metadata or {}),
                "ocr_anchors": {"enabled": True, "max_anchors": "all", **dict((request.metadata or {}).get("ocr_anchors") or {})}
                if isinstance((request.metadata or {}).get("ocr_anchors"), dict)
                else (request.metadata or {}).get("ocr_anchors", {"enabled": True, "max_anchors": "all"}),
            },
            top_k=request.top_k,
        )
        response = recognition_plan(plan_request)
        if not response.success or not response.data:
            return response
        result = response.data["result"]
        locate_result = {
            "contract_version": "target_location_v1",
            "goal": request.goal,
            "image_path": image_path,
            "live_capture": live_capture,
            "recognition_plan": result,
            "pre_click_decision": result.get("pre_click_decision"),
            "selected_click_point": ((result.get("pre_click_decision") or {}).get("selected_click_point")),
            "recommended_target": result.get("recommended_target"),
            "execution_path": {
                **dict(result.get("execution_path") or {}),
                "action_executed": False,
                "coordinate_source": "pre_click_decision_v1.selected_click_point",
                "agent_must_call_for_click": "POST /action/execute_recognition_plan",
            },
        }
        locate_result["trace_path"] = write_trace(
            category="vision",
            operation="locate_target",
            payload={"success": True, "request": request.model_dump(), "result": locate_result},
            name_hint=request.app_name or Path(image_path).stem,
        )
        data = VisionResultData(result=locate_result)
        return APIResponse(success=True, message="Target located", data=data.model_dump(), error=None)
    except Exception as exc:
        trace_path = write_trace(
            category="vision",
            operation="locate_target",
            payload={"success": False, "request": request.model_dump(), "error": str(exc)},
            name_hint=request.app_name or "locate_target",
        )
        return APIResponse(
            success=False,
            message="Target location failed",
            data={"trace_path": trace_path},
            error=ErrorModel(code="locate_target_failed", details=str(exc)),
        )


@router.post("/recognition_plan", response_model=APIResponse)
def recognition_plan(request: VisionRecognitionPlanRequestModel) -> APIResponse:
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
        with Image.open(image_path) as image:
            input_image_size = ImageSize(width=image.width, height=image.height)
        vision_request, ocr_result, ocr_anchor_payload, ocr_anchor_status = _recognition_vision_request_with_ocr_anchors(
            request,
            image_path=image_path,
            image_size=input_image_size,
        )
        try:
            response = provider.analyze(vision_request)
        except Exception as exc:
            if not ocr_anchor_status.get("used"):
                raise
            ocr_anchor_status.update({"used": False, "fallback_used": True, "provider_error": str(exc)})
            ocr_anchor_payload = None
            response = provider.analyze(_vision_request_without_ocr_anchors(request, image_path=image_path))
        response, refine_ocr_result, refine_options = _maybe_refine_with_ocr(response, request=request, image_path=image_path)
        if refine_ocr_result is not None:
            ocr_result = refine_ocr_result
        normalized = normalizer.normalize(response.to_dict(), response.provider)
        if normalized.image_size is None:
            normalized.image_size = input_image_size
        normalized = apply_anchor_grounding_evaluation(normalized, ocr_anchor_payload)
        if ocr_result is None:
            ocr_result = ocr_service.scan_image(str(image_path))
        structure = build_page_structure(normalized, ocr_result)
        uia_snapshot = uia_provider.snapshot_bound_window()
        screen_reading_payload = build_screen_reading(
            image_path=str(image_path),
            vision=normalized,
            ocr=ocr_result,
            page_structure=structure,
            app_name=request.app_name,
            uia_snapshot=uia_snapshot,
        )
        goal = request.goal or request.task
        candidate_result = rank_candidates(
            CandidateRankRequest(
                goal=goal,
                page_structure=structure,
                top_k=request.top_k,
                state_hint=request.state_hint,
                screen_reading=screen_reading_payload,
            )
        )
        narrow_search_result = run_local_grounding(
            LocalGroundingRequest(
                image_path=str(image_path),
                goal=goal,
                candidates=candidate_result.candidates,
                ocr_scan=ocr_service.scan_image,
                app_name=request.app_name,
            )
        )
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
        result_payload["trace_path"] = write_trace(
            category="vision",
            operation="recognition_plan",
            payload={"success": True, "request": request.model_dump(), "result": result_payload},
            name_hint=request.app_name or image_path.stem,
        )
        data = VisionResultData(result=result_payload)
        return APIResponse(success=True, message="Recognition plan completed", data=data.model_dump(), error=None)
    except Exception as exc:
        trace_path = write_trace(
            category="vision",
            operation="recognition_plan",
            payload={"success": False, "request": request.model_dump(), "error": str(exc)},
            name_hint=request.app_name or image_path.stem,
        )
        return APIResponse(
            success=False,
            message="Recognition plan failed",
            data={"trace_path": trace_path},
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
