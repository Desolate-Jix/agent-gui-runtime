from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from difflib import SequenceMatcher
from typing import Any

from fastapi import APIRouter
from PIL import Image, ImageDraw, ImageFont, ImageStat

from app.core.ocr_service import ocr_service
from app.core.model_server import load_model_profiles
from app.core.runtime_artifacts import ARTIFACTS_DIR, RuntimeTimer, build_review_overlay_path, write_trace
from app.core.screenshot import screenshot_service
from app.gate.candidates import validate_action_candidate_freshness
from app.operation.path_graph import build_available_actions
from app.operation.runtime_context import build_operation_runtime_context, operation_trace_link
from app.operation.visual_asset_matching import match_visual_asset
from app.learn.interface_map import build_learned_interface_map
from app.learn.path_graph_resolver import resolve_runtime_path_graph
from app.learn.recognition.two_stage import partition_stage2_calibration_items
from app.learn.visual_asset_crops import build_visual_assets_from_screen_map
from app.api.models.request import (
    VisionAnalyzeRequestModel,
    VisionLocateTargetRequestModel,
    VisionObserveScreenRequestModel,
    VisionRecognitionPlanOverlayRequestModel,
    VisionRecognitionPlanRequestModel,
    VisionReviewOverlayRequestModel,
)
from app.api.models.response import APIResponse, ErrorModel, VisionResultData
from app.api.models.request import OCRRegionRequest
from app.operation.page_structure import build_page_structure
from app.operation.page_structure.schemas import InteractionPolicy, PageElement, PageStructure, VerificationHints
from app.operation.recognition import CandidateRankRequest, LocalGroundingRequest, decide_pre_click, rank_candidates, run_local_grounding
from app.operation.recognition.precise_locator import build_precise_locator_evidence
from app.operation.recognition.schemas import CandidateRankResult, LocalGroundingCandidateResult, LocalGroundingResult, RecognitionCandidate, ScoreBreakdown
from app.operation.recognition.plan_overlay import render_recognition_plan_overlay
from app.operation.screen_inventory import build_screen_inventory
from app.operation.screen_reading import build_screen_reading
from app.operation.screen_reading.uia_provider import uia_provider
from app.vision.artifacts import save_region_artifacts
from app.vision.anchor_grounding import apply_anchor_grounding_evaluation
from app.vision.factory import VisionProviderFactory
from app.vision.local_provider import LocalVisionProvider
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
from app.vision.schemas import BBox, ImageSize, VisionAnalyzeRequest
from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch

router = APIRouter(prefix="/vision", tags=["vision"])

VISTA_DIRECT_IMAGES_DIR = ARTIFACTS_DIR / "vista-direct"
VISUAL_ASSET_RECALL_CONTRACT = "visual_asset_recall_v1"
DEFAULT_LEARNED_RUNTIME_PATH_GRAPHS = {
    "seek": ARTIFACTS_DIR / "seek" / "runtime_path_graph_seek_mvp_20260617.json",
}


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


def _model_io_trace(provider_response: Any | None = None, *, error: Exception | None = None) -> dict[str, Any] | None:
    if provider_response is not None:
        raw_response = getattr(provider_response, "raw_response", None)
        raw = raw_response if isinstance(raw_response, dict) else {}
        attempts = raw.get("attempts") if isinstance(raw.get("attempts"), list) else []
        model_json = raw.get("model_json") if isinstance(raw.get("model_json"), dict) else {}
        model_name = raw.get("model_name") or model_json.get("model_name") or model_json.get("provider")
        return {
            "contract_version": "model_io_trace_v1",
            "status": "success",
            "provider": getattr(provider_response, "provider", None),
            "model_name": model_name,
            "raw_text": getattr(provider_response, "raw_text", None) or raw.get("raw_text"),
            "raw_response": raw,
            "attempt_count": len(attempts),
            "attempts": attempts,
        }
    if error is not None:
        diagnostics = getattr(error, "diagnostics", None)
        if isinstance(diagnostics, dict):
            return {
                "contract_version": "model_io_trace_v1",
                "status": "failed",
                **diagnostics,
            }
    return None


def _attach_model_io(result_payload: dict[str, Any], provider_response: Any | None) -> None:
    model_io = _model_io_trace(provider_response)
    if model_io is not None:
        result_payload["model_io"] = model_io


def _model_io_failure_payload(exc: Exception) -> dict[str, Any] | None:
    return _model_io_trace(error=exc)


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
                ocr_result = _ocr_result_from_anchor_payload(anchor_payload, image_path=str(image_path))
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


def _ocr_result_from_anchor_payload(payload: dict[str, Any], *, image_path: str) -> OCRResult:
    matches: list[OCRTextMatch] = []
    for anchor in _as_list(payload.get("anchors")):
        if not isinstance(anchor, dict):
            continue
        text = str(anchor.get("text") or "").strip()
        bbox = _normalize_map_bbox(anchor.get("bbox"))
        if not text or not bbox:
            continue
        matches.append(
            OCRTextMatch(
                text=text,
                score=float(anchor.get("confidence") or anchor.get("score") or 1.0),
                bbox=OCRBoundingBox(x=bbox["x"], y=bbox["y"], width=bbox["w"], height=bbox["h"]),
            )
        )
    return OCRResult(
        image_path=image_path,
        metadata={
            "engine": "observe_trace_reuse",
            "source_trace_path": payload.get("source_trace_path"),
            "source_anchor_count": len(matches),
        },
        matches=matches,
    )


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


def _learning_capture_visual_readiness(image_path: str | Path) -> dict[str, Any]:
    """识别低信息启动页，避免把尚未绘制完成的窗口送入整屏理解。"""

    path = Path(image_path)
    with Image.open(path) as image:
        sample = image.convert("RGB")
        sample.thumbnail((160, 120))
        quantized = sample.quantize(colors=32)
        colors = quantized.getcolors(maxcolors=32) or []
        total_pixels = max(1, sample.width * sample.height)
        dominant_pixels = max((count for count, _color in colors), default=total_pixels)
        dominant_color_ratio = dominant_pixels / total_pixels
        color_bucket_count = len(colors)

        grayscale = sample.convert("L")
        margin_x = max(2, grayscale.width // 32)
        margin_y = max(2, grayscale.height // 32)
        core = grayscale.crop((margin_x, margin_y, grayscale.width - margin_x, grayscale.height - margin_y))
        grid_size = 5
        informative_tile_count = 0
        for row in range(grid_size):
            for column in range(grid_size):
                tile = core.crop(
                    (
                        column * core.width // grid_size,
                        row * core.height // grid_size,
                        (column + 1) * core.width // grid_size,
                        (row + 1) * core.height // grid_size,
                    )
                )
                if ImageStat.Stat(tile).stddev[0] >= 8.0:
                    informative_tile_count += 1

    informative_tile_ratio = informative_tile_count / (grid_size * grid_size)
    ready = dominant_color_ratio < 0.985 and informative_tile_count >= 3
    return {
        "contract_version": "learning_capture_visual_readiness_v2",
        "ready": ready,
        "dominant_color_ratio": round(dominant_color_ratio, 6),
        "color_bucket_count": color_bucket_count,
        "informative_tile_count": informative_tile_count,
        "informative_tile_ratio": round(informative_tile_ratio, 6),
        "reason": "visual_information_present" if ready else "low_information_startup_surface",
    }


def _learning_observe_image_source(
    request: VisionObserveScreenRequestModel,
    *,
    max_attempts: int = 4,
    retry_delay_seconds: float = 0.75,
) -> tuple[str, dict | None]:
    image_path, live_capture = _image_path_for_live_or_saved(
        capture_live=request.capture_live,
        image_path=request.image_path,
        purpose="observe_screen",
        app_name=request.app_name,
    )
    readiness_requested = bool(
        isinstance(request.metadata, dict)
        and (
            request.metadata.get("learning_studio_draft_capture") is True
            or request.metadata.get("require_capture_readiness") is True
        )
    )
    if (
        request.agent_mode != "learn"
        or not request.capture_live
        or not readiness_requested
        or not Path(image_path).exists()
    ):
        return image_path, live_capture

    attempts: list[dict[str, Any]] = []
    capture_payload = dict(live_capture or {})
    for attempt_index in range(max_attempts):
        readiness = _learning_capture_visual_readiness(image_path)
        attempts.append({"attempt": attempt_index + 1, "image_path": image_path, **readiness})
        if readiness["ready"] is True:
            capture_payload["image_path"] = image_path
            capture_payload["capture_readiness"] = {
                **readiness,
                "attempt_count": attempt_index + 1,
                "attempts": attempts,
            }
            return image_path, capture_payload
        if attempt_index + 1 < max_attempts:
            time.sleep(retry_delay_seconds)
            capture_payload = screenshot_service.capture_window(
                save_image=True,
                purpose="observe_screen_ready_retry",
                name_hint=request.app_name or "learning_observe",
            )
            image_path = str(capture_payload.get("image_path") or "")
            if not image_path or not Path(image_path).exists():
                raise RuntimeError("Learning capture readiness retry did not create an image")

    raise RuntimeError(
        "Learning capture stayed on a low-information startup surface after "
        f"{max_attempts} attempts"
    )


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
    screen_inventory = result.get("screen_inventory") if isinstance(result.get("screen_inventory"), dict) else None
    if screen_inventory is None:
        screen_reading = parse_result.get("screen_reading") if isinstance(parse_result.get("screen_reading"), dict) else {}
        if isinstance(screen_reading.get("screen_inventory"), dict):
            screen_inventory = screen_reading["screen_inventory"]
        elif screen_reading.get("contract_version") == "screen_reading_v1":
            from app.operation.screen_inventory import build_screen_inventory

            screen_inventory = build_screen_inventory(screen_reading, goal=goal)
    return {
        "status": "ready",
        "trace_path": str(trace_path),
        "ocr_anchors": ocr_anchors,
        "observe_result": result,
        "screen_map": screen_map,
        "screen_inventory": screen_inventory,
        "state_id": screen_map.get("state_id") if isinstance(screen_map, dict) else None,
        "candidate_count": len(screen_map.get("candidates") or []) if isinstance(screen_map, dict) else 0,
        "anchor_count": int(ocr_anchors.get("anchor_count") or 0),
        "anchor_source": ocr_anchors.get("source_engine"),
    }


def _build_path_graph_recall(
    *,
    observe_reuse: dict[str, Any],
    goal: str,
    top_k: int,
    image_size: ImageSize,
) -> dict[str, Any]:
    if observe_reuse.get("status") != "ready":
        return {
            "contract_version": "path_graph_recall_v1",
            "status": "unavailable",
            "reason": observe_reuse.get("reason") or "observe_trace_reuse_not_ready",
            "state_match": {"status": "unavailable"},
            "candidates": [],
            "summary": {"candidate_count": 0, "recalled_count": 0},
        }
    screen_map = observe_reuse.get("screen_map") if isinstance(observe_reuse.get("screen_map"), dict) else {}
    if screen_map.get("contract_version") != "screen_map_v1":
        return {
            "contract_version": "path_graph_recall_v1",
            "status": "unavailable",
            "reason": "screen_map_unavailable",
            "state_match": {"status": "unavailable", "source_trace_path": observe_reuse.get("trace_path")},
            "candidates": [],
            "summary": {"candidate_count": 0, "recalled_count": 0},
        }
    raw_candidates = [item for item in _as_list(screen_map.get("candidates")) if isinstance(item, dict)]
    recallable_candidates = [item for item in raw_candidates if not _path_graph_candidate_is_browser_chrome(item)]
    filtered_browser_chrome_count = len(raw_candidates) - len(recallable_candidates)
    recalled = [
        recall
        for recall in (
            _path_graph_recall_candidate(candidate, goal=goal, rank=index + 1, image_size=image_size)
            for index, candidate in enumerate(recallable_candidates)
        )
        if recall is not None
    ]
    recalled.sort(key=lambda item: (-float(item.get("score") or 0.0), int(item.get("source_rank") or 9999)))
    selected = recalled[: max(1, int(top_k))]
    return {
        "contract_version": "path_graph_recall_v1",
        "status": "ready" if selected else "empty",
        "goal": goal,
        "state_match": {
            "status": "matched",
            "state_id": screen_map.get("state_id"),
            "source_trace_path": observe_reuse.get("trace_path"),
            "candidate_count": len(raw_candidates),
            "recallable_candidate_count": len(recallable_candidates),
            "filtered_browser_chrome_count": filtered_browser_chrome_count,
            "anchor_count": observe_reuse.get("anchor_count"),
        },
        "candidates": selected,
        "summary": {
            "candidate_count": len(raw_candidates),
            "recallable_candidate_count": len(recallable_candidates),
            "filtered_browser_chrome_count": filtered_browser_chrome_count,
            "recalled_count": len(selected),
            "top_score": selected[0].get("score") if selected else 0.0,
        },
    }


def _path_graph_candidate_is_browser_chrome(candidate: dict[str, Any]) -> bool:
    for key in ("section_id", "section", "source", "parent_region_id", "zone_id", "surface_zone"):
        value = str(candidate.get(key) or "").strip().casefold().replace("-", "_").replace(" ", "_")
        if value == "browser_chrome" or "browser_chrome" in value:
            return True
    text = " ".join(
        str(candidate.get(key) or "")
        for key in ("label", "text", "description")
    ).casefold()
    if any(
        token in text
        for token in (
            "调试此浏览器",
            "自动测试软件控制",
            "debugging this browser",
            "controlled by automated test software",
        )
    ):
        return True
    return False


def _path_graph_recall_candidate(
    candidate: dict[str, Any],
    *,
    goal: str,
    rank: int,
    image_size: ImageSize,
) -> dict[str, Any] | None:
    label = _first_compact_text(candidate.get("label"), candidate.get("text"), candidate.get("goal_hint"))
    role = _first_compact_text(candidate.get("role"), candidate.get("type"))
    expected_effect = _first_compact_text(candidate.get("expected_effect"))
    section_id = _first_compact_text(candidate.get("section_id"))
    search_text = " ".join(part for part in [label, role, expected_effect, section_id] if part)
    if not search_text:
        return None
    goal_key = _path_label_key(goal)
    label_key = _path_label_key(label)
    search_key = _path_label_key(search_text)
    label_score = _path_label_similarity(goal_key, label_key)
    search_score = _path_label_similarity(goal_key, search_key)
    substring_score = 0.0
    if goal_key and label_key and (goal_key in label_key or label_key in goal_key):
        substring_score = 0.92
    if goal_key and search_key and (goal_key in search_key or search_key in goal_key):
        substring_score = max(substring_score, 0.78)
    role_bonus = 0.04 if any(token in str(role).casefold() for token in ["button", "link", "input", "tab", "menu"]) else 0.0
    score = min(1.0, max(label_score, search_score * 0.9, substring_score) + role_bonus)
    if score < 0.2:
        return None
    reasons = []
    if label_score >= 0.55 or substring_score >= 0.9:
        reasons.append("label_matches_goal")
    if search_score >= 0.5 or substring_score >= 0.78:
        reasons.append("semantic_context_matches_goal")
    if role_bonus:
        reasons.append("interactive_role_bonus")
    bbox = _normalize_map_bbox(candidate.get("bbox"))
    click_point = _normalize_map_point(candidate.get("click_point") or candidate.get("clickPoint"), bbox)
    local_ocr_roi = _pad_bbox(bbox, pad=24, max_width=image_size.width, max_height=image_size.height) if bbox else None
    return {
        "contract_version": "path_graph_recall_candidate_v1",
        "candidate_id": candidate.get("candidate_id") or candidate.get("id"),
        "source_rank": rank,
        "label": label,
        "role": role,
        "section_id": section_id,
        "bbox": bbox,
        "click_point": click_point,
        "local_ocr_roi": local_ocr_roi,
        "risk_class": candidate.get("risk_class"),
        "expected_effect": expected_effect,
        "source": candidate.get("source"),
        "score": round(score, 4),
        "score_reasons": reasons or ["weak_text_similarity"],
    }


def _merge_path_graph_recall_candidates(
    candidate_result: CandidateRankResult,
    *,
    path_graph_recall: dict[str, Any],
    goal: str,
    top_k: int,
) -> CandidateRankResult:
    recall_candidates = [
        _recognition_candidate_from_path_recall(item, rank=index + 1)
        for index, item in enumerate(_as_list(path_graph_recall.get("candidates")))
        if isinstance(item, dict)
    ]
    recall_candidates = [item for item in recall_candidates if item is not None]
    if not recall_candidates:
        return candidate_result

    merged: list[RecognitionCandidate] = []
    rejected = list(candidate_result.rejected)
    for candidate in [*candidate_result.candidates, *recall_candidates]:
        if _candidate_duplicate(candidate, merged):
            rejected.append(candidate)
            continue
        merged.append(candidate)

    merged.sort(
        key=lambda item: (
            float(item.score),
            float(item.score_breakdown.text_similarity),
            1.0 if "path_graph_recall" in item.reasons else 0.0,
            float(item.element.fusion_confidence),
        ),
        reverse=True,
    )
    selected = merged[: max(1, int(top_k))]
    selected_ids = {item.candidate_id for item in selected}
    rejected.extend(item for item in merged[max(1, int(top_k)) :] if item.candidate_id not in selected_ids)

    for index, candidate in enumerate(selected, start=1):
        candidate.rank = index
    for index, candidate in enumerate(rejected, start=1):
        candidate.rank = index

    margin = None
    if len(selected) >= 2:
        margin = round(float(selected[0].score) - float(selected[1].score), 4)
    elif selected:
        margin = round(float(selected[0].score), 4)

    summary = dict(candidate_result.summary)
    summary.update(
        {
            "returned_count": len(selected),
            "has_recommendation": bool(selected),
            "path_graph_recall_used": True,
            "path_graph_recall_candidate_count": len(recall_candidates),
            "path_graph_recall_selected_count": len([item for item in selected if "path_graph_recall" in item.reasons]),
        }
    )
    return CandidateRankResult(
        goal=goal,
        top_k=top_k,
        candidates=selected,
        rejected=rejected,
        recommended_candidate_id=selected[0].candidate_id if selected else None,
        margin_to_second=margin,
        summary=summary,
    )


def _seeded_candidate_payload(metadata: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(metadata, dict):
        return None
    seeded = metadata.get("seeded_candidate") or metadata.get("seeded_candidate_v1")
    if not isinstance(seeded, dict):
        return None
    if str(seeded.get("contract_version") or "seeded_candidate_v1") != "seeded_candidate_v1":
        return None
    return dict(seeded)


def _candidate_freshness_decision_for_trace(
    seeded: dict[str, Any] | None,
    *,
    image_path: Path,
    image_size: ImageSize,
    grounding: LocalGroundingResult | None = None,
) -> dict[str, Any] | None:
    if not isinstance(seeded, dict):
        return None
    current_viewport = image_size.to_dict()
    decision = validate_action_candidate_freshness(
        seeded,
        current_capture_id=str(image_path),
        current_viewport_size=current_viewport,
    )
    if decision.get("allowed") is True:
        return decision
    if _seeded_candidate_grounded_in_current_capture(seeded, grounding):
        return {
            **decision,
            "allowed": True,
            "reasons": [*decision.get("reasons", []), "candidate_refreshed_by_current_grounding"],
            "freshness": "reviewed_current_capture",
            "current_capture_id": str(image_path),
            "current_viewport_size": current_viewport,
        }
    return {
        **decision,
        "current_capture_id": str(image_path),
        "current_viewport_size": current_viewport,
    }


def _seeded_candidate_grounded_in_current_capture(
    seeded: dict[str, Any],
    grounding: LocalGroundingResult | None,
) -> bool:
    if grounding is None:
        return False
    seed_id = str(seeded.get("candidate_id") or "")
    expected_ids = {seed_id, f"seeded_{seed_id}"}
    for item in grounding.results:
        if item.status != "grounded":
            continue
        if item.candidate_id in expected_ids or item.element_id in expected_ids:
            return True
        if "seeded_candidate" in str(item.coordinate_source or ""):
            return True
    return False


def _recognition_candidate_from_seeded_candidate(item: dict[str, Any], *, rank: int) -> RecognitionCandidate | None:
    bbox = _normalize_map_bbox(item.get("bbox") or item.get("card_bbox"))
    if not bbox:
        return None
    click_point = _normalize_map_point(item.get("click_point") or item.get("point"), bbox)
    if not click_point:
        return None
    if not _point_inside_map_bbox(click_point, bbox, padding=0):
        return None
    label = _first_compact_text(item.get("label"), item.get("title"), item.get("candidate_id"))
    if not label:
        return None
    role = _first_compact_text(item.get("role"), "button")
    risk_class = str(item.get("risk_class") or "safe_click_allowed")
    allowed, policy_reason = _execution_allowed_for_risk_class(label=label, role=role, risk_class=risk_class)
    score = max(0.0, min(1.0, float(item.get("score") or 0.99)))
    seed_id = _first_compact_text(item.get("candidate_id"), hashlib.sha256(label.encode("utf-8")).hexdigest()[:12])
    candidate_id = f"seeded_{seed_id}"[:120]
    element_id = f"seeded_{seed_id}"[:120]
    expected_effect = _first_compact_text(item.get("expected_effect"), "open selected target")
    policy = InteractionPolicy(
        allowed=allowed,
        zone_type="general_action" if allowed else "seeded_candidate_requires_confirmation",
        priority="seeded_candidate",
        ad_risk=0.0,
        reasons=["seeded_candidate_policy", f"risk_class:{risk_class or 'unknown'}", policy_reason],
    )
    element = PageElement(
        element_id=element_id,
        label=label,
        role=role,
        interaction_type="focus" if any(token in role.casefold() for token in ["input", "textbox", "search"]) else "click",
        description=expected_effect or label,
        text=label,
        bbox=BBox(x=bbox["x"], y=bbox["y"], w=bbox["w"], h=bbox["h"]),
        semantic_bbox=None,
        click_point=click_point,
        click_strategy="seeded_candidate_v1_then_local_grounding",
        possible_destinations=[expected_effect] if expected_effect else [],
        verification_hints=VerificationHints(expected_changes=[expected_effect] if expected_effect else []),
        interaction_policy=policy,
        fusion_confidence=max(0.75, score),
        coordinate_confidence="seeded_candidate_observation_hint",
        memory_key=f"seeded_candidate:{seed_id}",
        sources=["seeded_candidate_v1"],
        evidence={"seeded_candidate": dict(item)},
    )
    breakdown = ScoreBreakdown(
        text_similarity=max(0.82, score),
        role_score=0.9 if element.interaction_type in {"click", "focus"} else 0.4,
        policy_score=0.78 if allowed else 0.0,
        confidence_score=max(0.85, score),
        state_score=0.5,
        screen_reading_score=0.2,
        ad_penalty=0.0,
        blocked_penalty=0.0 if allowed else 1.0,
    )
    return RecognitionCandidate(
        candidate_id=candidate_id,
        rank=rank,
        element_id=element_id,
        label=label,
        role=role,
        text=label,
        score=round(max(score, breakdown.total()), 4),
        eligible=allowed,
        reasons=["seeded_candidate", "seeded_candidate_point_inside_bbox"],
        score_breakdown=breakdown,
        element=element,
        refined_bbox=bbox,
        bbox_refine_reason="seeded_candidate_bbox",
    )


def _merge_seeded_candidate(
    candidate_result: CandidateRankResult,
    *,
    seeded_candidate: dict[str, Any] | None,
    goal: str,
    top_k: int,
) -> CandidateRankResult:
    seed = _recognition_candidate_from_seeded_candidate(seeded_candidate or {}, rank=1) if seeded_candidate else None
    if seed is None:
        return candidate_result
    merged: list[RecognitionCandidate] = [seed]
    rejected = list(candidate_result.rejected)
    for candidate in candidate_result.candidates:
        if _candidate_duplicate(candidate, merged):
            rejected.append(candidate)
            continue
        merged.append(candidate)
    merged.sort(
        key=lambda item: (
            1.0 if "seeded_candidate" in item.reasons else 0.0,
            float(item.score),
            float(item.score_breakdown.text_similarity),
            float(item.element.fusion_confidence),
        ),
        reverse=True,
    )
    selected = merged[: max(1, int(top_k))]
    selected_ids = {item.candidate_id for item in selected}
    rejected.extend(item for item in merged[max(1, int(top_k)) :] if item.candidate_id not in selected_ids)
    for index, candidate in enumerate(selected, start=1):
        candidate.rank = index
    for index, candidate in enumerate(rejected, start=1):
        candidate.rank = index
    if len(selected) >= 2:
        margin = round(float(selected[0].score) - float(selected[1].score), 4)
    elif selected:
        margin = round(float(selected[0].score), 4)
    else:
        margin = None
    summary = dict(candidate_result.summary)
    summary.update(
        {
            "returned_count": len(selected),
            "has_recommendation": bool(selected),
            "seeded_candidate_used": True,
            "seeded_candidate_selected": bool(selected and "seeded_candidate" in selected[0].reasons),
            "seeded_candidate_candidate_count": 1,
        }
    )
    return CandidateRankResult(
        goal=goal,
        top_k=top_k,
        candidates=selected,
        rejected=rejected,
        recommended_candidate_id=selected[0].candidate_id if selected else None,
        margin_to_second=margin,
        summary=summary,
    )


def _recognition_candidate_from_path_recall(item: dict[str, Any], *, rank: int) -> RecognitionCandidate | None:
    bbox = _normalize_map_bbox(item.get("bbox"))
    if not bbox:
        return None
    label = _first_compact_text(item.get("label"), item.get("candidate_id"))
    if not label:
        return None
    role = _first_compact_text(item.get("role")) or "button"
    score = max(0.0, min(1.0, float(item.get("score") or 0.0)))
    risk_class = str(item.get("risk_class") or "")
    allowed, policy_reason = _execution_allowed_for_risk_class(label=label, role=role, risk_class=risk_class)
    policy = InteractionPolicy(
        allowed=allowed,
        zone_type="general_action" if allowed else "path_graph_requires_confirmation",
        priority="path_graph_recall",
        ad_risk=0.0,
        reasons=["path_graph_recall_policy", f"risk_class:{risk_class or 'unknown'}", policy_reason],
    )
    click_point = _normalize_map_point(item.get("click_point"), bbox) or {"x": bbox["x"] + bbox["w"] // 2, "y": bbox["y"] + bbox["h"] // 2}
    candidate_id = str(item.get("candidate_id") or f"path_recall_{rank}")[:100]
    element_id = f"path_graph_{candidate_id}"[:120]
    element = PageElement(
        element_id=element_id,
        label=label,
        role=role,
        interaction_type="focus" if any(token in role.casefold() for token in ["input", "textbox", "search"]) else "click",
        description=_first_compact_text(item.get("expected_effect"), item.get("section_id"), label),
        text=label,
        bbox=BBox(x=bbox["x"], y=bbox["y"], w=bbox["w"], h=bbox["h"]),
        semantic_bbox=None,
        click_point=click_point,
        click_strategy="path_graph_recall_then_local_ocr",
        possible_destinations=[_first_compact_text(item.get("expected_effect"))] if item.get("expected_effect") else [],
        verification_hints=VerificationHints(expected_changes=[_first_compact_text(item.get("expected_effect"))] if item.get("expected_effect") else []),
        interaction_policy=policy,
        fusion_confidence=max(0.45, score),
        coordinate_confidence="path_graph_observation_hint",
        memory_key=f"path_graph:{candidate_id}",
        sources=["path_graph_recall_v1"],
        evidence={"path_graph_recall": dict(item)},
    )
    breakdown = ScoreBreakdown(
        text_similarity=max(0.45, score),
        role_score=0.85 if element.interaction_type in {"click", "focus"} else 0.4,
        policy_score=0.7 if allowed else 0.0,
        confidence_score=max(0.45, score),
        state_score=0.4,
        screen_reading_score=0.25,
        ad_penalty=0.0,
        blocked_penalty=0.0 if allowed else 1.0,
    )
    candidate_score = max(score, breakdown.total())
    return RecognitionCandidate(
        candidate_id=f"path_graph_{candidate_id}"[:120],
        rank=rank,
        element_id=element_id,
        label=label,
        role=role,
        text=label,
        score=round(candidate_score, 4),
        eligible=allowed,
        reasons=["path_graph_recall", *[str(reason) for reason in _as_list(item.get("score_reasons"))]],
        score_breakdown=breakdown,
        element=element,
        refined_bbox=bbox,
        bbox_refine_reason="path_graph_recall_bbox",
    )


def _selected_local_vision_config(config: dict[str, Any], provider_mode: str | None) -> dict[str, Any]:
    vision = config.get("vision") if isinstance(config.get("vision"), dict) else {}
    selected_mode = str(provider_mode or vision.get("mode") or "local").strip().lower()
    if selected_mode == "local_understanding":
        return vision.get("local_understanding") or vision.get("local_small") or vision.get("local") or {}
    if selected_mode == "local_grounding":
        return vision.get("local_grounding") or vision.get("local_large") or vision.get("local") or {}
    return vision.get("local") or {}


def _selected_learning_grounding_config(
    config: dict[str, Any],
    request: VisionLocateTargetRequestModel,
) -> dict[str, Any]:
    selected = dict(_selected_local_vision_config(config, request.provider_mode or "local_grounding"))
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    profile_id = str(metadata.get("learn_grounding_profile_id") or "").strip()
    if request.agent_mode != "learn" or not profile_id:
        return selected
    profile = next(
        (item for item in load_model_profiles() if str(item.get("profile_id") or "").strip() == profile_id),
        None,
    )
    if profile is None:
        raise ValueError(f"unknown learning grounding profile: {profile_id}")
    if str(profile.get("provider_mode") or "").strip() != "local_grounding":
        raise ValueError(f"learning grounding profile is not local_grounding: {profile_id}")
    default_profile_id = str(selected.get("profile_id") or "").strip()
    if str(profile.get("mode_scope") or "").strip() != "learn_only" and profile_id != default_profile_id:
        raise ValueError(f"learning grounding override must be learn_only: {profile_id}")
    if not str(profile.get("endpoint") or "").strip():
        raise ValueError(f"learning grounding profile has no endpoint: {profile_id}")
    return {**selected, **profile}


def _uses_vista_point_grounding(local_config: dict[str, Any]) -> bool:
    contract = str(local_config.get("output_contract") or "").strip().lower()
    model_name = str(local_config.get("model_name") or local_config.get("model_path") or "").casefold()
    runtime = str(local_config.get("runtime") or "").strip().lower()
    return contract == "vista_point_v1" or ("vista" in model_name and runtime == "transformers")


def _uses_learning_point_grounding(local_config: dict[str, Any]) -> bool:
    if _uses_vista_point_grounding(local_config):
        return True
    model_family = str(local_config.get("model_family") or "").strip().casefold()
    model_name = str(local_config.get("model_name") or local_config.get("model_path") or "").casefold()
    grounding_role = str(local_config.get("grounding_role") or "").strip().casefold()
    return (
        model_family == "uground"
        or "uground" in model_name
        or grounding_role in {"roi_point_grounding", "roi_point_grounding_baseline"}
    )


def _candidate_bbox_for_prompt(candidate: RecognitionCandidate, coordinate_transform: dict[str, Any] | None = None) -> dict[str, int]:
    bbox = candidate.refined_bbox or candidate.element.bbox.to_dict()
    transform = coordinate_transform if isinstance(coordinate_transform, dict) else {}
    origin = transform.get("origin_original") if isinstance(transform.get("origin_original"), dict) else {}
    scale = transform.get("scale_original_to_processed") if isinstance(transform.get("scale_original_to_processed"), dict) else {}
    if not transform:
        return bbox
    sx = float(scale.get("x") or 1.0)
    sy = float(scale.get("y") or 1.0)
    ox = float(origin.get("x") or 0)
    oy = float(origin.get("y") or 0)
    return {
        "x": max(0, int(round((float(bbox["x"]) - ox) * sx))),
        "y": max(0, int(round((float(bbox["y"]) - oy) * sy))),
        "w": max(1, int(round(float(bbox["w"]) * sx))),
        "h": max(1, int(round(float(bbox["h"]) * sy))),
    }


def _vista_point_prompt(
    goal: str,
    candidates: list[RecognitionCandidate],
    *,
    coordinate_transform: dict[str, Any] | None = None,
    coordinate_space: str = "screenshot",
) -> str:
    candidate_lines = []
    for candidate in candidates[:8]:
        bbox = _candidate_bbox_for_prompt(candidate, coordinate_transform=coordinate_transform)
        candidate_lines.append(
            f"- {candidate.candidate_id}: label={candidate.label!r}, role={candidate.role!r}, "
            f"bbox=[{bbox['x']},{bbox['y']},{bbox['w']},{bbox['h']}]"
        )
    candidate_block = "\n".join(candidate_lines) if candidate_lines else "- none"
    return (
        "Locate the requested GUI target in the screenshot.\n"
        f"Goal: {goal}\n"
        f"Candidate bboxes are in {coordinate_space} pixel coordinates. Use the candidate list only as context. Return the center point of the actual target.\n"
        "Return normalized 0-1000 coordinates only, preferably as [x, y].\n"
        "Candidates:\n"
        f"{candidate_block}"
    )


def _call_vista_point_grounding(
    *,
    local_config: dict[str, Any],
    image_path: Path,
    goal: str,
    candidates: list[RecognitionCandidate],
    image_size: ImageSize,
    original_image_size: ImageSize | None = None,
    coordinate_transform: dict[str, Any] | None = None,
    image_preprocess: dict[str, Any] | None = None,
    vista_stage: str | None = None,
    coordinate_space: str = "screenshot",
    timeout_seconds: float,
) -> dict[str, Any]:
    endpoint = str(local_config.get("endpoint") or "").strip()
    if not endpoint:
        raise ValueError("VISTA point grounding requires local_config.endpoint")
    model_name = str(local_config.get("model_name") or "inclusionAI/VISTA-4B")
    prompt = _vista_point_prompt(
        goal,
        candidates,
        coordinate_transform=coordinate_transform,
        coordinate_space=coordinate_space,
    )
    return _call_vista_point_prompt(
        local_config=local_config,
        image_path=image_path,
        goal=goal,
        prompt=prompt,
        image_size=image_size,
        original_image_size=original_image_size,
        coordinate_transform=coordinate_transform,
        image_preprocess=image_preprocess,
        vista_stage=vista_stage,
        timeout_seconds=timeout_seconds,
        max_tokens=int(local_config.get("max_new_tokens") or 32),
        provider_name="vista_point_grounding",
    )


def _vista_client_timeout_seconds(server_timeout_seconds: float) -> float:
    server_timeout = max(1.0, float(server_timeout_seconds))
    client_grace = max(30.0, min(60.0, server_timeout * 2.0))
    return server_timeout + client_grace


def _call_vista_point_prompt(
    *,
    local_config: dict[str, Any],
    image_path: Path,
    goal: str,
    prompt: str,
    image_size: ImageSize,
    original_image_size: ImageSize | None = None,
    coordinate_transform: dict[str, Any] | None = None,
    image_preprocess: dict[str, Any] | None = None,
    vista_stage: str | None = None,
    timeout_seconds: float,
    max_tokens: int,
    provider_name: str,
) -> dict[str, Any]:
    endpoint = str(local_config.get("endpoint") or "").strip()
    if not endpoint:
        raise ValueError("VISTA point grounding requires local_config.endpoint")
    model_name = str(local_config.get("model_name") or "inclusionAI/VISTA-4B")
    server_timeout_seconds = max(1.0, float(timeout_seconds))
    provider = LocalVisionProvider(
        endpoint=endpoint,
        model_name=model_name,
        timeout_seconds=_vista_client_timeout_seconds(server_timeout_seconds),
    )
    raw_response = provider._call_openai_compatible_endpoint(
        image_path,
        prompt,
        max_tokens=max_tokens,
        request_timeout_seconds=server_timeout_seconds,
    )
    raw_text = provider._extract_message_text(raw_response).strip()
    parsed = _parse_vista_point_text(raw_text)
    processed_point = _vista_point_to_original_pixel(parsed, image_size=image_size)
    output_image_size = original_image_size or image_size
    point = (
        _map_vista_processed_point_to_original(
            processed_point,
            original_image_size=output_image_size,
            coordinate_transform=coordinate_transform,
        )
        if coordinate_transform
        else processed_point
    )
    return {
        "contract_version": "vista_point_grounding_v1",
        "status": "ready",
        "provider": provider_name,
        "vista_stage": vista_stage,
        "model_name": model_name,
        "output_contract": local_config.get("output_contract") or "vista_point_v1",
        "image_path": str(image_path),
        "goal": goal,
        "prompt": prompt,
        "raw_text": raw_text,
        "raw_response": raw_response,
        "parsed": parsed,
        "processed_point": processed_point,
        "point": point,
        "image_size": output_image_size.to_dict(),
        "inference_image_size": image_size.to_dict(),
        "coordinate_transform": coordinate_transform,
        "image_preprocess": image_preprocess,
        "model_io_attempt": {
            "contract_version": "model_io_attempt_v1",
            "status": "success",
            "provider": provider_name,
            "vista_stage": vista_stage,
            "model_name": model_name,
            "image_path": str(image_path),
            "prompt": prompt,
            "raw_text": raw_text,
            "raw_response": raw_response,
            "parsed_model_json": parsed,
            "processed_point": processed_point,
            "point": point,
            "image_preprocess": image_preprocess,
            "coordinate_transform": coordinate_transform,
        },
    }


def _parse_vista_point_text(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    parsed: Any
    try:
        parsed = json.loads(text)
    except Exception:
        start = text.find("[")
        end = text.find("]", start + 1)
        if start < 0 or end < 0:
            raise ValueError(f"VISTA point output is not JSON or [x, y]: {raw_text[:200]}")
        parsed = json.loads(text[start : end + 1])
    if isinstance(parsed, dict):
        if parsed.get("point") is None and isinstance(parsed.get("raw_text"), str) and parsed.get("raw_text"):
            nested = _parse_vista_point_text(str(parsed["raw_text"]))
            nested["wrapped_unparsed_payload"] = parsed
            return nested
        point = parsed.get("point") if isinstance(parsed.get("point"), dict) else parsed
        bbox = point.get("bbox") if isinstance(point.get("bbox"), dict) else parsed.get("bbox") if isinstance(parsed.get("bbox"), dict) else None
        if bbox is not None:
            normalized_bbox = _normalize_map_bbox(bbox)
            if normalized_bbox is None:
                raise ValueError(f"VISTA bbox payload is invalid: {raw_text[:200]}")
            x = normalized_bbox["x"] + normalized_bbox["w"] / 2
            y = normalized_bbox["y"] + normalized_bbox["h"] / 2
            space = str(point.get("coordinate_space") or parsed.get("coordinate_space") or "pixel")
        else:
            x = point.get("x")
            y = point.get("y")
            space = str(point.get("coordinate_space") or parsed.get("coordinate_space") or "normalized_0_1000")
    elif isinstance(parsed, list) and len(parsed) >= 4:
        x = float(parsed[0]) + float(parsed[2]) / 2
        y = float(parsed[1]) + float(parsed[3]) / 2
        space = "pixel"
    elif isinstance(parsed, list) and len(parsed) >= 2:
        x, y = parsed[0], parsed[1]
        space = "normalized_0_1000"
    else:
        raise ValueError(f"Unsupported VISTA point payload: {raw_text[:200]}")
    if x is None or y is None:
        raise ValueError(f"VISTA point payload missing x/y: {raw_text[:200]}")
    return {
        "contract_version": "vista_point_v1",
        "point": {"x": float(x), "y": float(y), "coordinate_space": space},
    }


def _vista_point_to_original_pixel(parsed: dict[str, Any], *, image_size: ImageSize) -> dict[str, int]:
    point = parsed.get("point") if isinstance(parsed.get("point"), dict) else {}
    x = float(point.get("x"))
    y = float(point.get("y"))
    space = str(point.get("coordinate_space") or "normalized_0_1000").lower()
    if space in {"normalized_0_1000", "0_1000", "normalized"}:
        px = round(x * max(1, image_size.width) / 1000.0)
        py = round(y * max(1, image_size.height) / 1000.0)
    else:
        if x < 0 or y < 0 or x >= image_size.width or y >= image_size.height:
            raise ValueError(
                "VISTA pixel point outside inference image bounds: "
                f"point=({x:.3f}, {y:.3f}), image_size={image_size.width}x{image_size.height}, "
                f"coordinate_space={space}"
            )
        px = round(x)
        py = round(y)
    return {
        "x": max(0, min(int(image_size.width) - 1, int(px))),
        "y": max(0, min(int(image_size.height) - 1, int(py))),
    }


def _identity_vista_image_preprocess(image_path: Path, image_size: ImageSize, *, max_edge: int) -> dict[str, Any]:
    return {
        "contract_version": "vista_direct_image_preprocess_v1",
        "status": "identity",
        "strategy": "none",
        "max_edge": int(max_edge),
        "original_image_path": str(image_path),
        "processed_image_path": str(image_path),
        "original_size": image_size.to_dict(),
        "processed_size": image_size.to_dict(),
        "transform": {
            "contract_version": "vista_coordinate_transform_v1",
            "type": "identity",
            "origin_original": {"x": 0, "y": 0},
            "scale_original_to_processed": {"x": 1.0, "y": 1.0},
            "scale_processed_to_original": {"x": 1.0, "y": 1.0},
        },
    }


def _prepare_vista_direct_image(image_path: Path, image_size: ImageSize, *, max_edge: int) -> dict[str, Any]:
    max_edge = int(max_edge or 0)
    if max_edge <= 0:
        return _identity_vista_image_preprocess(image_path, image_size, max_edge=max_edge)
    longest = max(int(image_size.width), int(image_size.height))
    if longest <= max_edge:
        return _identity_vista_image_preprocess(image_path, image_size, max_edge=max_edge)

    scale = float(max_edge) / float(longest)
    processed_width = max(1, int(round(float(image_size.width) * scale)))
    processed_height = max(1, int(round(float(image_size.height) * scale)))
    digest_source = f"{image_path.resolve()}:{image_path.stat().st_mtime_ns}:{max_edge}:{processed_width}x{processed_height}"
    digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:10]
    VISTA_DIRECT_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    processed_path = VISTA_DIRECT_IMAGES_DIR / f"{image_path.stem}__vista-direct-max{max_edge}__{digest}.png"
    with Image.open(image_path) as image:
        resized = image.convert("RGB").resize((processed_width, processed_height), Image.Resampling.LANCZOS)
        resized.save(processed_path)

    scale_x = processed_width / max(1, int(image_size.width))
    scale_y = processed_height / max(1, int(image_size.height))
    return {
        "contract_version": "vista_direct_image_preprocess_v1",
        "status": "processed",
        "strategy": "resize_max_edge",
        "max_edge": max_edge,
        "original_image_path": str(image_path),
        "processed_image_path": str(processed_path),
        "original_size": image_size.to_dict(),
        "processed_size": {"width": processed_width, "height": processed_height},
        "transform": {
            "contract_version": "vista_coordinate_transform_v1",
            "type": "resize",
            "origin_original": {"x": 0, "y": 0},
            "scale_original_to_processed": {"x": scale_x, "y": scale_y},
            "scale_processed_to_original": {
                "x": 1.0 / scale_x if scale_x else 1.0,
                "y": 1.0 / scale_y if scale_y else 1.0,
            },
        },
    }


def _roi_bounds_around_point(point: dict[str, int], *, image_size: ImageSize, roi_size: int) -> dict[str, int]:
    size = max(64, int(roi_size or 512))
    width = int(image_size.width)
    height = int(image_size.height)
    crop_w = min(size, max(1, width))
    crop_h = min(size, max(1, height))
    x = int(point.get("x") or 0) - crop_w // 2
    y = int(point.get("y") or 0) - crop_h // 2
    x = max(0, min(max(0, width - crop_w), x))
    y = max(0, min(max(0, height - crop_h), y))
    return {"x": x, "y": y, "w": crop_w, "h": crop_h}


def _select_pathgraph_roi_candidates(candidates: list[RecognitionCandidate], *, top_k: int = 3, score_gap: float = 0.15) -> tuple[list[RecognitionCandidate], str]:
    if not candidates:
        return [], "none"
    if len(candidates) == 1:
        return [candidates[0]], "top1_only"
    first = float(candidates[0].score)
    second = float(candidates[1].score)
    if first - second >= score_gap:
        return [candidates[0]], "top1_score_gap"
    return candidates[: max(1, int(top_k or 3))], "union_top_candidates"


def _vista_candidate_roi_policy(roi_source: str) -> dict[str, Any]:
    """Return ROI sizing policy for VISTA point grounding.

    Seeded candidates are already localized by the caller/PathGraph, so the
    primary path should be a compact single-candidate crop. Wider multi-candidate
    crops remain an explicit fallback for ambiguous PathGraph recall.
    """
    if roi_source == "seeded_candidate_v1":
        return {
            "policy": "compact_seed_candidate_roi_primary",
            "padding": 16,
            "min_size": 192,
            "max_edge": 448,
            "fallback_tier": "primary",
        }
    if roi_source in {"top1_only", "top1_score_gap"}:
        return {
            "policy": "compact_pathgraph_top1_roi_primary",
            "padding": 32,
            "min_size": 224,
            "max_edge": 512,
            "fallback_tier": "primary",
        }
    return {
        "policy": "pathgraph_union_roi_fallback",
        "padding": 48,
        "min_size": 256,
        "max_edge": 640,
        "fallback_tier": "fallback",
    }


def _candidate_bbox(candidate: RecognitionCandidate) -> dict[str, int]:
    return candidate.refined_bbox or candidate.element.bbox.to_dict()


def _vista_union_roi_requires_full_resolution(
    roi: dict[str, int],
    *,
    image_size: ImageSize,
    roi_source: str,
) -> bool:
    if roi_source != "union_top_candidates":
        return False
    image_width = max(1, int(image_size.width))
    image_height = max(1, int(image_size.height))
    width_ratio = int(roi.get("w") or 0) / image_width
    height_ratio = int(roi.get("h") or 0) / image_height
    area_ratio = width_ratio * height_ratio
    return area_ratio >= 0.45 or (width_ratio >= 0.75 and height_ratio >= 0.45)


def _expand_bbox_roi(
    bbox: dict[str, int],
    *,
    image_size: ImageSize,
    padding: int,
    min_size: int,
) -> dict[str, int]:
    width = int(image_size.width)
    height = int(image_size.height)
    x1 = int(bbox["x"]) - int(padding)
    y1 = int(bbox["y"]) - int(padding)
    x2 = int(bbox["x"]) + int(bbox["w"]) + int(padding)
    y2 = int(bbox["y"]) + int(bbox["h"]) + int(padding)
    if x2 - x1 < min_size:
        extra = min_size - (x2 - x1)
        x1 -= extra // 2
        x2 += extra - extra // 2
    if y2 - y1 < min_size:
        extra = min_size - (y2 - y1)
        y1 -= extra // 2
        y2 += extra - extra // 2
    x1 = max(0, min(width - 1, x1))
    y1 = max(0, min(height - 1, y1))
    x2 = max(x1 + 1, min(width, x2))
    y2 = max(y1 + 1, min(height, y2))
    if x2 - x1 < min_size and width >= min_size:
        shift = min(min_size - (x2 - x1), x1)
        x1 -= shift
        x2 = min(width, x1 + min_size)
    if y2 - y1 < min_size and height >= min_size:
        shift = min(min_size - (y2 - y1), y1)
        y1 -= shift
        y2 = min(height, y1 + min_size)
    return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}


def _prepare_vista_candidate_roi_image(
    image_path: Path,
    image_size: ImageSize,
    *,
    candidates: list[RecognitionCandidate],
    max_edge: int,
    padding: int,
    min_size: int,
    roi_source: str,
) -> dict[str, Any]:
    if not candidates:
        raise ValueError("PathGraph candidate ROI refine requires at least one candidate")
    bboxes = [_candidate_bbox(candidate) for candidate in candidates]
    x1 = min(int(item["x"]) for item in bboxes)
    y1 = min(int(item["y"]) for item in bboxes)
    x2 = max(int(item["x"]) + int(item["w"]) for item in bboxes)
    y2 = max(int(item["y"]) + int(item["h"]) for item in bboxes)
    roi = _expand_bbox_roi(
        {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1},
        image_size=image_size,
        padding=padding,
        min_size=min_size,
    )
    preserve_full_resolution = _vista_union_roi_requires_full_resolution(
        roi,
        image_size=image_size,
        roi_source=roi_source,
    )
    if preserve_full_resolution:
        roi = {"x": 0, "y": 0, "w": int(image_size.width), "h": int(image_size.height)}
    max_edge = int(max_edge or 0)
    crop_width = int(roi["w"])
    crop_height = int(roi["h"])
    longest = max(crop_width, crop_height)
    if preserve_full_resolution:
        scale = 1.0
        processed_width = crop_width
        processed_height = crop_height
        strategy = "pathgraph_union_full_screen_preserve_resolution"
    elif max_edge > 0 and longest > max_edge:
        scale = float(max_edge) / float(longest)
        processed_width = max(1, int(round(crop_width * scale)))
        processed_height = max(1, int(round(crop_height * scale)))
        strategy = "pathgraph_candidate_roi_resize_max_edge"
    else:
        scale = 1.0
        processed_width = crop_width
        processed_height = crop_height
        strategy = "pathgraph_candidate_roi"

    candidate_ids = [candidate.candidate_id for candidate in candidates]
    digest_source = (
        f"{image_path.resolve()}:{image_path.stat().st_mtime_ns}:"
        f"pathgraph-roi-{roi['x']}-{roi['y']}-{roi['w']}-{roi['h']}:"
        f"{','.join(candidate_ids)}:max{max_edge}:{processed_width}x{processed_height}"
    )
    digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:10]
    VISTA_DIRECT_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    processed_path = VISTA_DIRECT_IMAGES_DIR / f"{image_path.stem}__vista-pathgraph-roi-{roi['x']}-{roi['y']}-{roi['w']}x{roi['h']}-max{max_edge}__{digest}.png"
    with Image.open(image_path) as image:
        crop = image.convert("RGB").crop((roi["x"], roi["y"], roi["x"] + roi["w"], roi["y"] + roi["h"]))
        if scale != 1.0:
            crop = crop.resize((processed_width, processed_height), Image.Resampling.LANCZOS)
        crop.save(processed_path)

    scale_x = processed_width / max(1, crop_width)
    scale_y = processed_height / max(1, crop_height)
    candidate_summaries = []
    for candidate in candidates:
        bbox = _candidate_bbox(candidate)
        candidate_summaries.append(
            {
                "candidate_id": candidate.candidate_id,
                "label": candidate.label,
                "score": float(candidate.score),
                "bbox_original": bbox,
            }
        )
    return {
        "contract_version": "vista_direct_image_preprocess_v1",
        "status": "processed",
        "strategy": strategy,
        "locate_strategy": "pathgraph_candidate_roi_refine",
        "roi_source": roi_source,
        "roi_padding_px": int(padding),
        "max_edge": max_edge,
        "full_resolution_preserved": preserve_full_resolution,
        "full_resolution_reason": "ambiguous_union_roi_covers_large_screen_fraction" if preserve_full_resolution else None,
        "original_image_path": str(image_path),
        "processed_image_path": str(processed_path),
        "original_size": image_size.to_dict(),
        "crop_bounds_original": roi,
        "processed_size": {"width": processed_width, "height": processed_height},
        "pathgraph_candidates": candidate_summaries,
        "transform": {
            "contract_version": "vista_coordinate_transform_v1",
            "type": "pathgraph_candidate_crop_resize" if scale != 1.0 else "pathgraph_candidate_crop",
            "origin_original": {"x": int(roi["x"]), "y": int(roi["y"])},
            "scale_original_to_processed": {"x": scale_x, "y": scale_y},
            "scale_processed_to_original": {
                "x": 1.0 / scale_x if scale_x else 1.0,
                "y": 1.0 / scale_y if scale_y else 1.0,
            },
        },
    }


def _prepare_vista_region_roi_image(
    image_path: Path,
    image_size: ImageSize,
    *,
    region_bbox: dict[str, int],
    padding: int,
    max_edge: int,
) -> dict[str, Any]:
    roi = _expand_bbox_roi(
        region_bbox,
        image_size=image_size,
        padding=max(0, int(padding)),
        min_size=1,
    )
    crop_width = int(roi["w"])
    crop_height = int(roi["h"])
    max_edge = max(0, int(max_edge or 0))
    longest = max(crop_width, crop_height)
    if max_edge > 0 and longest > max_edge:
        scale = float(max_edge) / float(longest)
        processed_width = max(1, int(round(crop_width * scale)))
        processed_height = max(1, int(round(crop_height * scale)))
        strategy = "learn_parent_region_roi_resize_max_edge"
    else:
        scale = 1.0
        processed_width = crop_width
        processed_height = crop_height
        strategy = "learn_parent_region_roi"

    digest_source = (
        f"{image_path.resolve()}:{image_path.stat().st_mtime_ns}:"
        f"learn-region-{roi['x']}-{roi['y']}-{roi['w']}x{roi['h']}:"
        f"max{max_edge}:{processed_width}x{processed_height}"
    )
    digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:10]
    VISTA_DIRECT_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    processed_path = VISTA_DIRECT_IMAGES_DIR / (
        f"{image_path.stem}__vista-learn-region-roi-"
        f"{roi['x']}-{roi['y']}-{roi['w']}x{roi['h']}-max{max_edge}__{digest}.png"
    )
    with Image.open(image_path) as image:
        crop = image.convert("RGB").crop((roi["x"], roi["y"], roi["x"] + roi["w"], roi["y"] + roi["h"]))
        if scale != 1.0:
            crop = crop.resize((processed_width, processed_height), Image.Resampling.LANCZOS)
        crop.save(processed_path)

    scale_x = processed_width / max(1, crop_width)
    scale_y = processed_height / max(1, crop_height)
    return {
        "contract_version": "vista_direct_image_preprocess_v1",
        "status": "processed",
        "strategy": strategy,
        "original_image_path": str(image_path),
        "processed_image_path": str(processed_path),
        "original_size": image_size.to_dict(),
        "crop_bounds_original": roi,
        "processed_size": {"width": processed_width, "height": processed_height},
        "transform": {
            "contract_version": "vista_coordinate_transform_v1",
            "type": "learn_parent_region_crop_resize" if scale != 1.0 else "learn_parent_region_crop",
            "origin_original": {"x": int(roi["x"]), "y": int(roi["y"])},
            "scale_original_to_processed": {"x": scale_x, "y": scale_y},
            "scale_processed_to_original": {
                "x": 1.0 / scale_x if scale_x else 1.0,
                "y": 1.0 / scale_y if scale_y else 1.0,
            },
        },
    }


def _prepare_vista_roi_image(
    image_path: Path,
    image_size: ImageSize,
    *,
    center_point: dict[str, int],
    roi_size: int,
    max_edge: int,
) -> dict[str, Any]:
    roi = _roi_bounds_around_point(center_point, image_size=image_size, roi_size=roi_size)
    max_edge = int(max_edge or 0)
    crop_width = int(roi["w"])
    crop_height = int(roi["h"])
    longest = max(crop_width, crop_height)
    if max_edge > 0 and longest > max_edge:
        scale = float(max_edge) / float(longest)
        processed_width = max(1, int(round(crop_width * scale)))
        processed_height = max(1, int(round(crop_height * scale)))
        strategy = "crop_roi_resize_max_edge"
    else:
        scale = 1.0
        processed_width = crop_width
        processed_height = crop_height
        strategy = "crop_roi"

    digest_source = (
        f"{image_path.resolve()}:{image_path.stat().st_mtime_ns}:"
        f"roi-{roi['x']}-{roi['y']}-{roi['w']}-{roi['h']}:max{max_edge}:{processed_width}x{processed_height}"
    )
    digest = hashlib.sha1(digest_source.encode("utf-8")).hexdigest()[:10]
    VISTA_DIRECT_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    processed_path = VISTA_DIRECT_IMAGES_DIR / f"{image_path.stem}__vista-direct-roi-{roi['x']}-{roi['y']}-{roi['w']}x{roi['h']}-max{max_edge}__{digest}.png"
    with Image.open(image_path) as image:
        crop = image.convert("RGB").crop((roi["x"], roi["y"], roi["x"] + roi["w"], roi["y"] + roi["h"]))
        if scale != 1.0:
            crop = crop.resize((processed_width, processed_height), Image.Resampling.LANCZOS)
        crop.save(processed_path)

    scale_x = processed_width / max(1, crop_width)
    scale_y = processed_height / max(1, crop_height)
    return {
        "contract_version": "vista_direct_image_preprocess_v1",
        "status": "processed",
        "strategy": strategy,
        "max_edge": max_edge,
        "original_image_path": str(image_path),
        "processed_image_path": str(processed_path),
        "original_size": image_size.to_dict(),
        "crop_bounds_original": roi,
        "processed_size": {"width": processed_width, "height": processed_height},
        "transform": {
            "contract_version": "vista_coordinate_transform_v1",
            "type": "crop_resize" if scale != 1.0 else "crop",
            "origin_original": {"x": int(roi["x"]), "y": int(roi["y"])},
            "scale_original_to_processed": {"x": scale_x, "y": scale_y},
            "scale_processed_to_original": {
                "x": 1.0 / scale_x if scale_x else 1.0,
                "y": 1.0 / scale_y if scale_y else 1.0,
            },
        },
    }


def _map_vista_processed_point_to_original(
    point: dict[str, int],
    *,
    original_image_size: ImageSize,
    coordinate_transform: dict[str, Any] | None,
) -> dict[str, int]:
    transform = coordinate_transform if isinstance(coordinate_transform, dict) else {}
    origin = transform.get("origin_original") if isinstance(transform.get("origin_original"), dict) else {}
    scale = transform.get("scale_processed_to_original") if isinstance(transform.get("scale_processed_to_original"), dict) else {}
    x = round(float(origin.get("x") or 0) + float(point.get("x") or 0) * float(scale.get("x") or 1.0))
    y = round(float(origin.get("y") or 0) + float(point.get("y") or 0) * float(scale.get("y") or 1.0))
    return {
        "x": max(0, min(int(original_image_size.width) - 1, int(x))),
        "y": max(0, min(int(original_image_size.height) - 1, int(y))),
    }


def _point_inside_map_bbox(point: dict[str, int], bbox: dict[str, int], *, padding: int = 8) -> bool:
    x = int(point.get("x", -1))
    y = int(point.get("y", -1))
    return bbox["x"] - padding <= x <= bbox["x"] + bbox["w"] + padding and bbox["y"] - padding <= y <= bbox["y"] + bbox["h"] + padding


def _vista_direct_grounding_options(request: VisionRecognitionPlanRequestModel) -> dict[str, Any]:
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    raw = metadata.get("vista_direct_grounding", True)
    if raw is False:
        return {"enabled": False, "reason": "disabled_by_metadata"}
    if isinstance(raw, dict):
        return {
            "enabled": raw.get("enabled", True) is not False,
            "timeout_seconds": float(raw.get("timeout_seconds") or 15),
            "bbox_size": int(raw.get("bbox_size") or 48),
            "max_edge": int(raw.get("max_edge") or 640),
            "refine": raw.get("refine", True) is not False,
            "refine_roi_size": int(raw.get("refine_roi_size") or 512),
            "refine_max_edge": int(raw.get("refine_max_edge") or raw.get("max_edge") or 640),
        }
    return {
        "enabled": str(request.agent_mode or "execute").casefold() == "execute",
        "timeout_seconds": 15.0,
        "bbox_size": 48,
        "max_edge": 640,
        "refine": True,
        "refine_roi_size": 512,
        "refine_max_edge": 640,
    }


def _vista_direct_prompt(goal: str) -> str:
    text = str(goal or "").strip()
    if not text:
        return "Locate the requested UI target"
    lowered = text.casefold()
    if lowered.startswith(("click ", "locate ", "press ", "tap ")) or text.startswith(("点击", "定位", "选择", "打开")):
        return text
    return f"Click {text}"


def _bbox_around_point(point: dict[str, int], *, image_size: ImageSize, size: int) -> dict[str, int]:
    width = max(8, int(size or 48))
    half = width // 2
    x = max(0, min(int(image_size.width) - 1, int(point["x"]) - half))
    y = max(0, min(int(image_size.height) - 1, int(point["y"]) - half))
    w = min(width, max(1, int(image_size.width) - x))
    h = min(width, max(1, int(image_size.height) - y))
    return {"x": x, "y": y, "w": w, "h": h}


def _is_browser_app_name(app_name: str | None) -> bool:
    normalized = str(app_name or "").strip().lower()
    if normalized in {"edge", "chrome", "browser", "msedge", "msedge.exe", "chrome.exe", "firefox", "brave"}:
        return True
    return any(token in normalized for token in ("edge", "chrome", "firefox", "brave", "browser", "msedge"))


def _point_in_browser_chrome(point: dict[str, int], *, image_size: ImageSize, app_name: str | None) -> bool:
    if not _is_browser_app_name(app_name):
        return False
    y = int(point.get("y", -1))
    if y < 0:
        return False
    browser_chrome_bottom = min(int(image_size.height), max(72, round(int(image_size.height) * 0.065)))
    return y <= browser_chrome_bottom


def _recognition_candidate_from_vista_direct(
    *,
    goal: str,
    point: dict[str, int],
    image_size: ImageSize,
    bbox_size: int,
) -> RecognitionCandidate:
    bbox = _bbox_around_point(point, image_size=image_size, size=bbox_size)
    label = _first_compact_text(goal) or "VISTA direct target"
    candidate_hash = hashlib.sha1(f"{label}|{point.get('x')}|{point.get('y')}".encode("utf-8")).hexdigest()[:10]
    candidate_id = f"vista_direct_{candidate_hash}"
    policy = InteractionPolicy(
        allowed=True,
        zone_type="general_action",
        priority="vista_direct_grounding",
        ad_risk=0.0,
        reasons=["vista_direct_point_grounding_policy", "requires_post_click_verification"],
    )
    element = PageElement(
        element_id=f"element_{candidate_id}",
        label=label,
        role="button",
        interaction_type="click",
        description="Direct VISTA point-grounded target without PathGraph recall.",
        text=label,
        bbox=BBox(x=bbox["x"], y=bbox["y"], w=bbox["w"], h=bbox["h"]),
        semantic_bbox=None,
        click_point=point,
        click_strategy="vista_direct_point_grounding",
        possible_destinations=[],
        verification_hints=VerificationHints(expected_changes=["target action should change focus, state, or visible content"]),
        interaction_policy=policy,
        fusion_confidence=0.72,
        coordinate_confidence="vista_direct_point",
        memory_key=f"vista_direct:{candidate_hash}",
        sources=["vista_point_v1_direct"],
        evidence={"vista_direct_point": {"point": point, "bbox": bbox}},
    )
    breakdown = ScoreBreakdown(
        text_similarity=0.78,
        role_score=0.75,
        policy_score=0.72,
        confidence_score=0.72,
        state_score=0.35,
        screen_reading_score=0.0,
        ad_penalty=0.0,
        blocked_penalty=0.0,
    )
    return RecognitionCandidate(
        candidate_id=candidate_id,
        rank=1,
        element_id=element.element_id,
        label=label,
        role="button",
        text=label,
        score=0.78,
        eligible=True,
        reasons=["vista_direct_point_grounding", "no_path_graph_recall_candidate"],
        score_breakdown=breakdown,
        element=element,
        refined_bbox=bbox,
        bbox_refine_reason="synthetic_bbox_around_vista_direct_point",
    )


def _execute_fast_inventory_from_uia(
    *,
    image_path: Path,
    image_size: ImageSize,
    app_name: str | None,
    goal: str,
    metadata: dict[str, Any] | None,
) -> dict[str, Any]:
    options = metadata.get("execute_fast_inventory") if isinstance(metadata, dict) else None
    if isinstance(options, dict) and options.get("enabled") is False:
        return {
            "contract_version": "execute_fast_inventory_v1",
            "status": "skipped",
            "reason": "disabled_by_request_metadata",
            "provider": "windows_uia",
        }
    max_controls = 250
    if isinstance(options, dict) and options.get("max_controls") is not None:
        try:
            max_controls = max(1, int(options.get("max_controls")))
        except (TypeError, ValueError):
            max_controls = 250
    try:
        uia_snapshot = uia_provider.snapshot_bound_window(max_controls=max_controls)
    except Exception as exc:
        return {
            "contract_version": "execute_fast_inventory_v1",
            "status": "failed",
            "reason": "uia_snapshot_failed",
            "provider": "windows_uia",
            "error": str(exc),
        }
    raw_controls = [item for item in (uia_snapshot.get("controls") or []) if isinstance(item, dict)]
    controls = _filter_execute_fast_inventory_controls(raw_controls, image_size=image_size, app_name=app_name)
    status = str(uia_snapshot.get("status") or "unknown")
    screen_reading = {
        "contract_version": "screen_reading_v1",
        "image_path": str(image_path),
        "image_size": image_size.to_dict(),
        "app_name": app_name,
        "texts": [],
        "ui_elements": [],
        "source_layers": {
            "windows_uia": {
                "provider": uia_snapshot.get("provider") or "windows_uia",
                "provider_version": uia_snapshot.get("provider_version"),
                "status": status,
                "control_count": len(controls),
                "reason": uia_snapshot.get("reason"),
                "controls": controls,
            }
        },
    }
    inventory = build_screen_inventory(screen_reading, goal=goal)
    screen_reading["screen_inventory"] = inventory
    action_count = int(((inventory.get("summary") or {}).get("available_action_count")) or 0)
    page_count = int(((inventory.get("summary") or {}).get("page_element_count")) or 0)
    result_status = "ready" if status == "ok" and (action_count or page_count) else "empty" if status == "ok" else "unavailable"
    return {
        "contract_version": "execute_fast_inventory_v1",
        "status": result_status,
        "provider": "windows_uia",
        "uia_scan_status": status,
        "uia_reason": uia_snapshot.get("reason"),
        "raw_control_count": len(raw_controls),
        "filtered_control_count": len(raw_controls) - len(controls),
        "control_count": len(controls),
        "screen_reading": screen_reading,
        "screen_inventory": inventory if result_status in {"ready", "empty"} else None,
    }


def _filter_execute_fast_inventory_controls(
    controls: list[dict[str, Any]],
    *,
    image_size: ImageSize,
    app_name: str | None,
) -> list[dict[str, Any]]:
    return [
        control
        for control in controls
        if _execute_fast_inventory_control_allowed(control, image_size=image_size, app_name=app_name)
    ]


def _execute_fast_inventory_control_allowed(
    control: dict[str, Any],
    *,
    image_size: ImageSize,
    app_name: str | None,
) -> bool:
    if control.get("enabled") is False or control.get("visible") is False:
        return False
    bbox = control.get("bbox") if isinstance(control.get("bbox"), dict) else {}
    width = int(bbox.get("w") or 0)
    height = int(bbox.get("h") or 0)
    if width <= 0 or height <= 0:
        return False
    y = int(bbox.get("y") or 0)
    if _is_browser_app_name(app_name):
        chrome_bottom = min(int(image_size.height), max(80, round(int(image_size.height) * 0.085)))
        if y < chrome_bottom:
            return False
    control_type = str(control.get("control_type") or "").strip().casefold()
    if control_type in {"window", "pane", "group", "toolbar", "titlebar", "title bar"}:
        return False
    label = str(control.get("name") or control.get("automation_id") or "").strip()
    if not label and control_type not in {"edit", "combo box", "combobox", "check box", "checkbox", "radio button", "radiobutton"}:
        return False
    area = width * height
    screen_area = max(1, int(image_size.width) * int(image_size.height))
    if area / screen_area > 0.5 and control_type not in {"document", "edit"}:
        return False
    return True


def _recognition_plan_from_vista_point(
    *,
    request: VisionRecognitionPlanRequestModel,
    timer: RuntimeTimer,
    config: dict[str, Any],
    local_config: dict[str, Any],
    image_path: Path,
    input_image_size: ImageSize,
    goal: str,
    observe_reuse: dict[str, Any],
    path_graph_recall: dict[str, Any],
) -> APIResponse:
    seeded_candidate = _seeded_candidate_payload(request.metadata)
    visual_asset_recall = request.metadata.get("visual_asset_recall") if isinstance(request.metadata, dict) else None
    if not isinstance(visual_asset_recall, dict):
        visual_asset_recall = {
            "contract_version": VISUAL_ASSET_RECALL_CONTRACT,
            "status": "not_requested",
            "matches": [],
            "selected_candidate": None,
            "fast_lane_allowed": False,
        }
    seed_candidate = _recognition_candidate_from_seeded_candidate(seeded_candidate or {}, rank=1) if seeded_candidate else None
    reviewed_execution = request.metadata.get("reviewed_test_execution") if isinstance(request.metadata, dict) else None
    allow_reviewed_seed_without_model = bool(
        seed_candidate is not None
        and isinstance(reviewed_execution, dict)
        and reviewed_execution.get("allow_seeded_candidate_without_model") is True
    )
    recall_candidates = [
        _recognition_candidate_from_path_recall(item, rank=index + 1)
        for index, item in enumerate(_as_list(path_graph_recall.get("candidates")))
        if isinstance(item, dict)
    ]
    candidates = [item for item in [seed_candidate, *recall_candidates] if item is not None]
    vista_payload: dict[str, Any] | None = None
    vista_error: str | None = None
    selected_candidate: RecognitionCandidate | None = None
    vista_direct_used = False
    vista_direct_attempted = False
    vista_direct_failure_model_io: dict[str, Any] | None = None
    seeded_primary_point_used = False
    vista_point_inside_selected_bbox = False
    if candidates:
        if allow_reviewed_seed_without_model and seed_candidate is not None:
            selected_candidate = seed_candidate
            seeded_primary_point_used = True
            selected_candidate.score = max(float(selected_candidate.score), 0.92)
            selected_candidate.score_breakdown.text_similarity = max(selected_candidate.score_breakdown.text_similarity, 0.82)
            selected_candidate.score_breakdown.confidence_score = max(selected_candidate.score_breakdown.confidence_score, 0.9)
            selected_candidate.reasons = _unique_list(
                [
                    *selected_candidate.reasons,
                    "reviewed_seeded_candidate_primary_point_used_without_model",
                ]
            )
            candidates = [selected_candidate, *[item for item in candidates if item.candidate_id != selected_candidate.candidate_id]]
        elif seed_candidate is not None:
            roi_candidates, roi_source = [seed_candidate], "seeded_candidate_v1"
        else:
            roi_candidates, roi_source = _select_pathgraph_roi_candidates(candidates)
        if selected_candidate is None:
            roi_policy = _vista_candidate_roi_policy(roi_source)
            roi_padding = int(roi_policy["padding"])
            roi_min_size = int(roi_policy["min_size"])
            roi_max_edge = int(roi_policy["max_edge"])
            pathgraph_roi_preprocess = _prepare_vista_candidate_roi_image(
                image_path,
                input_image_size,
                candidates=roi_candidates,
                max_edge=roi_max_edge,
                padding=roi_padding,
                min_size=roi_min_size,
                roi_source=roi_source,
            )
            pathgraph_roi_preprocess["roi_policy"] = roi_policy["policy"]
            pathgraph_roi_preprocess["fallback_tier"] = roi_policy["fallback_tier"]
            pathgraph_roi_preprocess["full_screen_fallback_available"] = True
            pathgraph_roi_image_path = Path(str(pathgraph_roi_preprocess.get("processed_image_path") or image_path))
            roi_size_raw = pathgraph_roi_preprocess.get("processed_size") if isinstance(pathgraph_roi_preprocess.get("processed_size"), dict) else input_image_size.to_dict()
            pathgraph_roi_image_size = ImageSize(
                width=int(roi_size_raw.get("width") or input_image_size.width),
                height=int(roi_size_raw.get("height") or input_image_size.height),
            )
            with timer.step(
                "vista_point_grounding_pathgraph_roi",
                candidate_count=len(candidates),
                roi_candidate_count=len(roi_candidates),
                roi_source=roi_source,
                roi_policy=roi_policy["policy"],
                fallback_tier=roi_policy["fallback_tier"],
                crop_bounds_original=pathgraph_roi_preprocess.get("crop_bounds_original"),
                max_edge=roi_max_edge,
            ):
                vista_payload = _call_vista_point_grounding(
                    local_config=local_config,
                    image_path=pathgraph_roi_image_path,
                    goal=goal,
                    candidates=roi_candidates,
                    image_size=pathgraph_roi_image_size,
                    original_image_size=input_image_size,
                    coordinate_transform=pathgraph_roi_preprocess.get("transform") if isinstance(pathgraph_roi_preprocess.get("transform"), dict) else None,
                    image_preprocess=pathgraph_roi_preprocess,
                    vista_stage="pathgraph_candidate_roi_refine",
                    coordinate_space="processed ROI image",
                    timeout_seconds=float((config.get("vision") or {}).get("timeout_seconds") or 600),
                )
            point = vista_payload["point"]
            for candidate in candidates:
                bbox = candidate.refined_bbox or candidate.element.bbox.to_dict()
                if _point_inside_map_bbox(point, bbox):
                    selected_candidate = candidate
                    vista_point_inside_selected_bbox = True
                    break
            if selected_candidate is None and seed_candidate is not None and seed_candidate.element.click_point is not None:
                selected_candidate = seed_candidate
                seeded_primary_point_used = True
            if selected_candidate is not None:
                selected_candidate.score = max(float(selected_candidate.score), 0.92)
                selected_candidate.score_breakdown.text_similarity = max(selected_candidate.score_breakdown.text_similarity, 0.72)
                selected_candidate.score_breakdown.confidence_score = max(selected_candidate.score_breakdown.confidence_score, 0.9)
                selected_candidate.reasons = _unique_list(
                    [
                        *selected_candidate.reasons,
                        "vista_point_inside_candidate_bbox"
                        if vista_point_inside_selected_bbox
                        else "seeded_candidate_primary_point_used_after_vista_disagreement",
                    ]
                )
                candidates = [selected_candidate, *[item for item in candidates if item.candidate_id != selected_candidate.candidate_id]]
    else:
        vista_error = "path_graph_recall_has_no_candidates"
        direct_options = _vista_direct_grounding_options(request)
        if direct_options.get("enabled"):
            vista_direct_attempted = True
            image_preprocess = _prepare_vista_direct_image(
                image_path,
                input_image_size,
                max_edge=int(direct_options.get("max_edge") or 640),
            )
            image_preprocess["roi_policy"] = "vista_direct_full_screen_fallback"
            image_preprocess["fallback_tier"] = "fallback"
            image_preprocess["fallback_reason"] = vista_error
            inference_image_path = Path(str(image_preprocess.get("processed_image_path") or image_path))
            inference_size_raw = image_preprocess.get("processed_size") if isinstance(image_preprocess.get("processed_size"), dict) else input_image_size.to_dict()
            inference_image_size = ImageSize(
                width=int(inference_size_raw.get("width") or input_image_size.width),
                height=int(inference_size_raw.get("height") or input_image_size.height),
            )
            coarse_payload: dict[str, Any] | None = None
            refine_payload: dict[str, Any] | None = None
            refine_preprocess: dict[str, Any] | None = None
            try:
                with timer.step(
                    "vista_direct_point_grounding_coarse",
                    timeout_seconds=direct_options.get("timeout_seconds"),
                    max_edge=direct_options.get("max_edge"),
                    preprocess_status=image_preprocess.get("status"),
                ):
                    coarse_payload = _call_vista_point_prompt(
                        local_config=local_config,
                        image_path=inference_image_path,
                        goal=goal,
                        prompt=_vista_direct_prompt(goal),
                        image_size=inference_image_size,
                        original_image_size=input_image_size,
                        coordinate_transform=image_preprocess.get("transform") if isinstance(image_preprocess.get("transform"), dict) else None,
                        image_preprocess=image_preprocess,
                        vista_stage="coarse_full",
                        timeout_seconds=float(direct_options.get("timeout_seconds") or 15),
                        max_tokens=int(local_config.get("max_new_tokens") or 32),
                        provider_name="vista_direct_point_grounding",
                    )
                vista_payload = coarse_payload
                if direct_options.get("refine") is not False:
                    refine_preprocess = _prepare_vista_roi_image(
                        image_path,
                        input_image_size,
                        center_point=coarse_payload["point"],
                        roi_size=int(direct_options.get("refine_roi_size") or 512),
                        max_edge=int(direct_options.get("refine_max_edge") or direct_options.get("max_edge") or 640),
                    )
                    refine_image_path = Path(str(refine_preprocess.get("processed_image_path") or image_path))
                    refine_size_raw = refine_preprocess.get("processed_size") if isinstance(refine_preprocess.get("processed_size"), dict) else input_image_size.to_dict()
                    refine_image_size = ImageSize(
                        width=int(refine_size_raw.get("width") or input_image_size.width),
                        height=int(refine_size_raw.get("height") or input_image_size.height),
                    )
                    with timer.step(
                        "vista_direct_point_grounding_refine",
                        timeout_seconds=direct_options.get("timeout_seconds"),
                        roi_size=direct_options.get("refine_roi_size"),
                        max_edge=direct_options.get("refine_max_edge"),
                        crop_bounds_original=refine_preprocess.get("crop_bounds_original"),
                    ):
                        refine_payload = _call_vista_point_prompt(
                            local_config=local_config,
                            image_path=refine_image_path,
                            goal=goal,
                            prompt=_vista_direct_prompt(goal),
                            image_size=refine_image_size,
                            original_image_size=input_image_size,
                            coordinate_transform=refine_preprocess.get("transform") if isinstance(refine_preprocess.get("transform"), dict) else None,
                            image_preprocess=refine_preprocess,
                            vista_stage="refine_roi",
                            timeout_seconds=float(direct_options.get("timeout_seconds") or 15),
                            max_tokens=int(local_config.get("max_new_tokens") or 32),
                            provider_name="vista_direct_point_grounding",
                        )
                    vista_payload = {
                        **refine_payload,
                        "vista_stage": "final_refine_roi",
                        "coarse_vista_point_grounding": coarse_payload,
                        "refine_vista_point_grounding": refine_payload,
                        "model_io_attempts": [
                            coarse_payload.get("model_io_attempt"),
                            refine_payload.get("model_io_attempt"),
                        ],
                    }
                elif coarse_payload is not None:
                    vista_payload = {
                        **coarse_payload,
                        "vista_stage": "final_coarse_full",
                        "coarse_vista_point_grounding": coarse_payload,
                        "model_io_attempts": [coarse_payload.get("model_io_attempt")],
                    }
                if _point_in_browser_chrome(vista_payload["point"], image_size=input_image_size, app_name=request.app_name):
                    selected_candidate = None
                    candidates = []
                    vista_error = "vista_direct_point_in_browser_chrome"
                    vista_direct_used = False
                    vista_payload = {
                        **vista_payload,
                        "status": "blocked",
                        "blocked_reason": "vista_direct_point_in_browser_chrome",
                    }
                else:
                    selected_candidate = _recognition_candidate_from_vista_direct(
                        goal=goal,
                        point=vista_payload["point"],
                        image_size=input_image_size,
                        bbox_size=int(direct_options.get("bbox_size") or 48),
                    )
                    candidates = [selected_candidate]
                    vista_error = None
                    vista_direct_used = True
            except Exception as exc:
                vista_error = f"vista_direct_point_grounding_failed: {exc}"
                vista_direct_failure_model_io = {
                    "contract_version": "model_io_trace_v1",
                    "status": "failed",
                    "provider": "vista_direct_point_grounding",
                    "model_name": local_config.get("model_name"),
                    "error": str(exc),
                    "attempt_count": 1,
                    "attempts": [
                        {
                            "contract_version": "model_io_attempt_v1",
                            "status": "failed",
                            "provider": "vista_direct_point_grounding",
                            "model_name": local_config.get("model_name"),
                            "image_path": str(inference_image_path),
                            "original_image_path": str(image_path),
                            "image_preprocess": image_preprocess,
                            "coarse_vista_point_grounding": coarse_payload,
                            "refine_image_preprocess": refine_preprocess,
                            "refine_vista_point_grounding": refine_payload,
                            "prompt": _vista_direct_prompt(goal),
                            "error": str(exc),
                        }
                    ],
                }

    fast_inventory: dict[str, Any] = {
        "contract_version": "execute_fast_inventory_v1",
        "status": "skipped",
        "reason": "observe_trace_reuse_has_screen_inventory" if isinstance(observe_reuse.get("screen_inventory"), dict) else "not_started",
        "provider": "windows_uia",
    }
    screen_inventory = observe_reuse.get("screen_inventory") if isinstance(observe_reuse.get("screen_inventory"), dict) else None
    screen_reading_from_fast_inventory = None
    if screen_inventory is None:
        with timer.step("uia_inventory_scan"):
            fast_inventory = _execute_fast_inventory_from_uia(
                image_path=image_path,
                image_size=input_image_size,
                app_name=request.app_name,
                goal=goal,
                metadata=request.metadata,
            )
        screen_inventory = fast_inventory.get("screen_inventory") if isinstance(fast_inventory.get("screen_inventory"), dict) else None
        screen_reading_from_fast_inventory = fast_inventory.get("screen_reading") if isinstance(fast_inventory.get("screen_reading"), dict) else None
    elif screen_inventory is not None:
        screen_reading_from_fast_inventory = {
            "contract_version": "screen_reading_v1",
            "image_path": str(image_path),
            "image_size": input_image_size.to_dict(),
            "app_name": request.app_name,
            "texts": [],
            "ui_elements": [],
            "screen_inventory": screen_inventory,
        }
    screen_inventory_rank_result: CandidateRankResult | None = None
    if isinstance(screen_reading_from_fast_inventory, dict) and screen_inventory is not None:
        with timer.step("rank_screen_inventory_candidates", top_k=request.top_k):
            screen_inventory_rank_result = rank_candidates(
                CandidateRankRequest(
                    goal=goal,
                    page_structure=PageStructure(
                        image_size=input_image_size,
                        screen_summary="execute fast inventory",
                        state_guess=request.state_hint,
                        elements=[],
                        texts=[],
                    ),
                    top_k=request.top_k,
                    state_hint=request.state_hint,
                    screen_reading=screen_reading_from_fast_inventory,
                )
            )
        existing_candidate_ids = {item.candidate_id for item in candidates}
        for candidate in screen_inventory_rank_result.candidates:
            if candidate.candidate_id not in existing_candidate_ids:
                candidates.append(candidate)
                existing_candidate_ids.add(candidate.candidate_id)
        candidates.sort(
            key=lambda item: (
                float(item.score),
                float(item.score_breakdown.text_similarity),
                float(item.score_breakdown.screen_reading_score),
            ),
            reverse=True,
        )
        candidates = candidates[: max(1, int(request.top_k or 5))]

    for index, candidate in enumerate(candidates, start=1):
        candidate.rank = index
    margin = round(float(candidates[0].score) - float(candidates[1].score), 4) if len(candidates) > 1 else round(float(candidates[0].score), 4) if candidates else None
    if selected_candidate is not None:
        margin = max(float(margin or 0.0), 0.2)
    vista_image_preprocess = vista_payload.get("image_preprocess") if isinstance(vista_payload, dict) and isinstance(vista_payload.get("image_preprocess"), dict) else {}
    candidate_result = CandidateRankResult(
        goal=goal,
        top_k=request.top_k,
        candidates=candidates,
        rejected=[],
        recommended_candidate_id=candidates[0].candidate_id if candidates else None,
        margin_to_second=margin,
        summary={
            "returned_count": len(candidates),
            "has_recommendation": bool(candidates),
            "path_graph_recall_used": True,
            "path_graph_recall_candidate_count": len([item for item in candidates if "path_graph_recall" in item.reasons]),
            "path_graph_recall_selected_count": len([item for item in candidates if "path_graph_recall" in item.reasons]),
            "seeded_candidate_used": seed_candidate is not None,
            "seeded_candidate_selected": bool(candidates and "seeded_candidate" in candidates[0].reasons),
            "vista_point_grounding_used": vista_payload is not None,
            "vista_point_inside_candidate_bbox": vista_point_inside_selected_bbox,
            "seeded_candidate_primary_point_used": seeded_primary_point_used,
            "vista_direct_point_grounding_used": vista_direct_used,
            "vista_direct_point_grounding_attempted": vista_direct_attempted,
            "screen_inventory_candidate_rank_used": screen_inventory_rank_result is not None,
            "screen_inventory_candidate_count": len(screen_inventory_rank_result.candidates) if screen_inventory_rank_result else 0,
            "vista_roi_policy": vista_image_preprocess.get("roi_policy"),
            "vista_roi_source": vista_image_preprocess.get("roi_source"),
            "vista_roi_fallback_tier": vista_image_preprocess.get("fallback_tier"),
            "vista_processed_size": vista_image_preprocess.get("processed_size"),
            "vista_crop_bounds_original": vista_image_preprocess.get("crop_bounds_original"),
        },
    )
    grounding_results: list[LocalGroundingCandidateResult] = []
    if vista_payload is not None:
        point = vista_payload["point"]
        for candidate in candidates:
            inside = selected_candidate is not None and candidate.candidate_id == selected_candidate.candidate_id
            bbox = candidate.refined_bbox or candidate.element.bbox.to_dict()
            model_point_inside_bbox = _point_inside_map_bbox(point, bbox)
            uses_seeded_point = inside and "seeded_candidate" in candidate.reasons and candidate.element.click_point is not None
            refined_click_point = dict(candidate.element.click_point) if uses_seeded_point else point
            if vista_direct_used and inside:
                reasons = ["vista_direct_point_grounding"]
                coordinate_source = "vista_point_v1"
            elif uses_seeded_point and model_point_inside_bbox:
                reasons = ["seeded_candidate_point_validated_by_vista_point"]
                coordinate_source = "seeded_candidate_v1_validated_by_vista_point_v1"
            elif uses_seeded_point:
                reasons = ["seeded_candidate_primary_point_used", "vista_point_disagrees_with_seed_bbox"]
                coordinate_source = "seeded_candidate_v1_model_disagreed"
            elif inside:
                reasons = ["vista_point_inside_candidate_bbox"]
                coordinate_source = "vista_point_v1"
            else:
                reasons = ["vista_point_not_inside_candidate_bbox"]
                coordinate_source = "vista_point_v1"
            grounding_results.append(
                LocalGroundingCandidateResult(
                    candidate_id=candidate.candidate_id,
                    element_id=candidate.element_id,
                    status="grounded" if inside else "point_outside_candidate",
                    crop_path=None,
                    crop_bbox=bbox,
                    refined_click_point=refined_click_point,
                    coordinate_source=coordinate_source,
                    confidence=0.82 if vista_direct_used and inside else 0.9 if inside else 0.35,
                    matched_text=candidate.label if inside else None,
                    matched_text_bbox=bbox if inside else None,
                    reasons=reasons,
                )
            )
    if allow_reviewed_seed_without_model and selected_candidate is not None and "seeded_candidate" in selected_candidate.reasons:
        bbox = selected_candidate.refined_bbox or selected_candidate.element.bbox.to_dict()
        grounding_results.append(
            LocalGroundingCandidateResult(
                candidate_id=selected_candidate.candidate_id,
                element_id=selected_candidate.element_id,
                status="grounded",
                crop_path=None,
                crop_bbox=bbox,
                refined_click_point=dict(selected_candidate.element.click_point),
                coordinate_source="seeded_candidate_v1_reviewed_local",
                confidence=0.9,
                matched_text=selected_candidate.label,
                matched_text_bbox=bbox,
                reasons=["reviewed_seeded_candidate_without_model", "seeded_candidate_point_inside_bbox"],
            )
        )
    grounded_candidate_ids = {item.candidate_id for item in grounding_results}
    for candidate in candidates:
        if candidate.candidate_id in grounded_candidate_ids:
            continue
        if not isinstance(candidate.element.evidence.get("screen_inventory_action"), dict):
            continue
        bbox = candidate.refined_bbox or candidate.element.bbox.to_dict()
        grounding_results.append(
            LocalGroundingCandidateResult(
                candidate_id=candidate.candidate_id,
                element_id=candidate.element_id,
                status="grounded",
                crop_path=None,
                crop_bbox=bbox,
                refined_click_point=dict(candidate.element.click_point),
                coordinate_source="screen_inventory_available_action",
                confidence=0.86 if candidate.element.coordinate_confidence == "high" else 0.72,
                matched_text=candidate.label,
                matched_text_bbox=bbox,
                reasons=["screen_inventory_available_action", "uia_coordinate_grounding"],
            )
        )
    narrow_search_result = LocalGroundingResult(
        goal=goal,
        results=grounding_results,
        recommended_candidate_id=selected_candidate.candidate_id if selected_candidate else None,
        summary={
            "provider": "vista_point_grounding",
            "output_contract": "vista_point_v1",
            "candidate_count": len(candidates),
            "grounded_count": 1 if selected_candidate else 0,
            "error": vista_error,
            "vista_point_inside_candidate_bbox": vista_point_inside_selected_bbox,
            "seeded_candidate_primary_point_used": seeded_primary_point_used,
            "vista_direct_point_grounding_used": vista_direct_used,
            "vista_roi_policy": vista_image_preprocess.get("roi_policy"),
            "vista_roi_source": vista_image_preprocess.get("roi_source"),
            "vista_roi_fallback_tier": vista_image_preprocess.get("fallback_tier"),
        },
    )
    allow_low_margin_when_grounded = bool(
        isinstance(reviewed_execution, dict)
        and reviewed_execution.get("allow_low_margin_when_grounded") is True
    )
    with timer.step("pre_click_decision"):
        pre_click_decision = decide_pre_click(
            goal=goal,
            candidates=candidate_result,
            grounding=narrow_search_result,
            allow_low_margin_when_grounded=allow_low_margin_when_grounded,
        )
    recommended = candidate_result.candidates[0].to_dict() if candidate_result.candidates else None
    model_io = vista_direct_failure_model_io or _vista_model_io_trace(vista_payload, error=vista_error)
    result_payload = {
        "contract_version": "recognition_plan_v1",
        **_mode_payload(request, fallback_contract="recognition_plan_v1"),
        "image_path": str(image_path),
        "goal": goal,
        "top_k": request.top_k,
        "observe_trace_reuse": {key: value for key, value in observe_reuse.items() if key not in {"ocr_anchors", "screen_map"}},
        "path_graph_recall": path_graph_recall,
        "visual_asset_recall": visual_asset_recall,
        "seeded_candidate": seeded_candidate,
        "candidate_freshness_decision": _candidate_freshness_decision_for_trace(
            seeded_candidate,
            image_path=image_path,
            image_size=input_image_size,
            grounding=narrow_search_result,
        ),
        "parse_result": {
            "vision_regions": {
                "contract_version": "vision_regions_v1",
                "provider": "vista_point_grounding",
                "image_size": input_image_size.to_dict(),
                "screen_summary": "VISTA point grounding uses PathGraph recall instead of full-screen region parsing.",
                "regions": [],
                "targets": [],
                "observers": [],
                "notes": ["vista_point_grounding_only"],
            },
            "ocr_result": None,
            "ocr_anchors": observe_reuse.get("ocr_anchors"),
            "page_structure": None,
            "screen_reading": screen_reading_from_fast_inventory,
            "screen_inventory": screen_inventory,
            "execute_fast_inventory": {key: value for key, value in fast_inventory.items() if key not in {"screen_reading", "screen_inventory"}},
            "vista_point_grounding": vista_payload,
        },
        "screen_inventory": screen_inventory,
        "candidate_result": candidate_result.to_dict(),
        "narrow_search_result": narrow_search_result.to_dict(),
        "pre_click_decision": pre_click_decision.to_dict(),
        "verification_plan": {
            "status": "planned_not_executed",
            "pre_click_checks": [
                "path_graph_state_match",
                "vista_point_inside_candidate_bbox",
                "vista_direct_point_grounding",
                "candidate_policy_allowed",
                "click_point_inside_candidate_bbox",
            ],
            "post_click_checks": ["ocr_change", "content_change", "focus_or_state_change"],
        },
        "recommended_target": recommended,
        "model_io": model_io,
        "execution_path": {
            **_vision_execution_path(
                requested_mode=request.provider_mode or str((config.get("vision") or {}).get("mode") or "local"),
                response_provider="vista_point_grounding",
                raw_response={"mode": "vista_point_grounding", "model_name": local_config.get("model_name")},
                page_structure_generated=False,
                ocr_region_refine_used=False,
            ),
            "vision_provider_used": "seeded_candidate_fast_lane"
            if allow_reviewed_seed_without_model and vista_payload is None
            else "vista_point_grounding",
            "vision_model_used": bool(vista_payload),
            "coordinate_source": (
                "seeded_candidate_v1.selected_click_point"
                if allow_reviewed_seed_without_model and seeded_primary_point_used
                else
                narrow_search_result.results[0].coordinate_source
                if narrow_search_result.results
                else "unavailable"
            ),
            "candidate_rank_used": True,
            "ocr_anchor_grounding_used": False,
            "ocr_anchor_grounding_fallback_used": False,
            "ocr_anchor_count": int(observe_reuse.get("anchor_count") or 0),
            "ocr_anchor_reused_from_observe": observe_reuse.get("status") == "ready",
            "path_graph_recall_used": path_graph_recall.get("status") == "ready",
            "path_graph_recall_count": len(path_graph_recall.get("candidates") or []),
            "path_graph_recall_candidates_ranked": bool(candidates),
            "path_graph_recall_selected_count": len([item for item in candidates if "path_graph_recall" in item.reasons]),
            "seeded_candidate_used": seed_candidate is not None,
            "seeded_candidate_selected": bool((candidate_result.summary or {}).get("seeded_candidate_selected")),
            "visual_asset_recall_used": visual_asset_recall.get("status") in {"matched", "no_match"},
            "visual_asset_recall_status": visual_asset_recall.get("status"),
            "visual_asset_fast_lane_used": bool(
                visual_asset_recall.get("fast_lane_allowed")
                and (candidate_result.summary or {}).get("seeded_candidate_selected")
                and seeded_primary_point_used
            ),
            "path_graph_candidate_roi_refine_used": bool(vista_payload and isinstance(vista_payload.get("image_preprocess"), dict) and vista_payload["image_preprocess"].get("locate_strategy") == "pathgraph_candidate_roi_refine"),
            "state_match_status": (path_graph_recall.get("state_match") or {}).get("status"),
            "screen_reading_used": False,
            "screen_reading_rank_evidence_used": False,
            "screen_inventory_used": screen_inventory is not None,
            "screen_inventory_source": "observe_trace_reuse" if isinstance(observe_reuse.get("screen_inventory"), dict) else ("execute_fast_inventory_uia" if screen_inventory is not None else "unavailable"),
            "screen_inventory_available_action_count": int(((screen_inventory or {}).get("summary") or {}).get("available_action_count") or 0),
            "screen_inventory_page_element_count": int(((screen_inventory or {}).get("summary") or {}).get("page_element_count") or 0),
            "screen_inventory_card_count": int(((screen_inventory or {}).get("summary") or {}).get("card_count") or 0),
            "execute_fast_inventory_status": fast_inventory.get("status"),
            "uia_scan_status": fast_inventory.get("uia_scan_status") or "skipped_observe_trace_reuse",
            "narrow_search_used": True,
            "vista_point_grounding_used": vista_payload is not None,
            "vista_point_inside_candidate_bbox": vista_point_inside_selected_bbox,
            "seeded_candidate_primary_point_used": seeded_primary_point_used,
            "vista_direct_point_grounding_used": vista_direct_used,
            "vista_direct_point_grounding_attempted": vista_direct_attempted,
            "vista_roi_policy": vista_image_preprocess.get("roi_policy"),
            "vista_roi_source": vista_image_preprocess.get("roi_source"),
            "vista_roi_fallback_tier": vista_image_preprocess.get("fallback_tier"),
            "vista_processed_size": vista_image_preprocess.get("processed_size"),
            "vista_crop_bounds_original": vista_image_preprocess.get("crop_bounds_original"),
            "pre_click_decision_used": True,
            "reviewed_test_execution_used": allow_reviewed_seed_without_model or allow_low_margin_when_grounded,
            "action_executed": False,
        },
    }
    result_payload["timings"] = timer.to_dict()
    result_payload["trace_path"] = _write_trace_if_enabled(
        request,
        category="vision",
        operation="recognition_plan",
        payload={"success": True, "request": request.model_dump(), "result": result_payload},
        name_hint=request.app_name or image_path.stem,
    )
    data = VisionResultData(result=result_payload)
    return APIResponse(success=True, message="Recognition plan completed", data=data.model_dump(), error=None)


def _vista_model_io_trace(payload: dict[str, Any] | None, *, error: str | None = None) -> dict[str, Any]:
    if payload is None:
        return {
            "contract_version": "model_io_trace_v1",
            "status": "skipped",
            "provider": "vista_point_grounding",
            "error": error or "vista_point_grounding_not_invoked",
            "attempt_count": 0,
            "attempts": [],
        }
    attempts = [item for item in _as_list(payload.get("model_io_attempts")) if isinstance(item, dict)]
    if not attempts:
        attempts = [
            {
                "contract_version": "model_io_attempt_v1",
                "status": "success",
                "provider": payload.get("provider"),
                "vista_stage": payload.get("vista_stage"),
                "model_name": payload.get("model_name"),
                "image_path": payload.get("image_path"),
                "prompt": payload.get("prompt"),
                "raw_text": payload.get("raw_text"),
                "raw_response": payload.get("raw_response"),
                "parsed_model_json": payload.get("parsed"),
                "processed_point": payload.get("processed_point"),
                "point": payload.get("point"),
                "image_preprocess": payload.get("image_preprocess"),
                "coordinate_transform": payload.get("coordinate_transform"),
            }
        ]
    return {
        "contract_version": "model_io_trace_v1",
        "status": "success",
        "provider": payload.get("provider"),
        "model_name": payload.get("model_name"),
        "raw_text": payload.get("raw_text"),
        "raw_response": payload.get("raw_response"),
        "parsed_json": payload.get("parsed"),
        "attempt_count": len(attempts),
        "attempts": attempts,
    }


def _unique_list(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _candidate_duplicate(candidate: RecognitionCandidate, existing: list[RecognitionCandidate]) -> bool:
    candidate_bbox = candidate.refined_bbox or candidate.element.bbox.to_dict()
    candidate_label = _path_label_key(candidate.label)
    for other in existing:
        other_bbox = other.refined_bbox or other.element.bbox.to_dict()
        same_label = candidate_label and _path_label_similarity(candidate_label, _path_label_key(other.label)) >= 0.9
        high_overlap = _path_bbox_similarity(candidate_bbox, other_bbox) >= 0.82
        if same_label and high_overlap:
            return True
    return False


def _mode_contract_version(agent_mode: str | None, learn_depth: str | None, *, fallback: str) -> str:
    if agent_mode == "learn":
        return "learn_screen_deep_v1" if learn_depth == "deep" else "learn_screen_fast_v1"
    if agent_mode == "execute":
        return "execute_plan_v1"
    return fallback


def _mode_payload(request: Any, *, fallback_contract: str) -> dict[str, Any]:
    write_policy = getattr(request, "write_policy", None)
    return {
        "agent_mode": getattr(request, "agent_mode", None) or "execute",
        "learn_depth": getattr(request, "learn_depth", None),
        "mode_contract_version": _mode_contract_version(
            getattr(request, "agent_mode", None),
            getattr(request, "learn_depth", None),
            fallback=fallback_contract,
        ),
        "write_policy": write_policy.model_dump() if hasattr(write_policy, "model_dump") else dict(write_policy or {}),
    }


def _should_learn_visual_assets(request: Any) -> bool:
    if getattr(request, "agent_mode", None) != "learn":
        return False
    metadata = getattr(request, "metadata", None)
    if isinstance(metadata, dict):
        visual_assets = metadata.get("visual_assets")
        if isinstance(visual_assets, dict) and visual_assets.get("enabled") is False:
            return False
    return True


def _safe_visual_asset_run_name(value: Any) -> str:
    text = str(value or "screen").strip()
    safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in text)
    return safe.strip("_")[:80] or "screen"


def _skipped_visual_asset_learning(
    *,
    image_path: str,
    reason: str,
    app_id: Any,
    page_type: Any,
    learn_depth: Any,
    error_detail: str | None = None,
) -> dict[str, Any]:
    payload = {
        "contract_version": "visual_asset_learning_v1",
        "status": "skipped",
        "reason": reason,
        "source_image_path": str(image_path),
        "app_id": app_id,
        "page_type": page_type,
        "learn_depth": learn_depth,
        "visual_assets": {
            "contract_version": "visual_asset_store_v1",
            "asset_status_default": "skipped",
            "asset_match_is_evidence_only": True,
            "asset_can_authorize_click": False,
            "assets": [],
        },
        "summary": {
            "candidate_count": 0,
            "asset_count": 0,
            "skipped_count": 0,
            "artifact_is_authorization": False,
        },
    }
    if error_detail:
        payload["error_detail"] = error_detail
    return payload


def _build_visual_asset_recall(
    *,
    metadata: dict[str, Any] | None,
    observe_reuse: dict[str, Any],
    image_path: Path,
    image_size: ImageSize,
    goal: str | None,
) -> dict[str, Any]:
    stores = _visual_asset_stores_from_sources(metadata=metadata, observe_reuse=observe_reuse)
    assets = _visual_asset_items_from_stores(stores)
    if not assets:
        return {
            "contract_version": VISUAL_ASSET_RECALL_CONTRACT,
            "status": "no_assets",
            "asset_count": 0,
            "matches": [],
            "selected_candidate": None,
            "fast_lane_allowed": False,
        }

    matches: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        asset_id = str(asset.get("asset_id") or asset.get("id") or asset.get("candidate_id") or "")
        label = _first_compact_text(asset.get("label"), asset_id)
        semantic_action = _first_compact_text(asset.get("semantic_action"), asset.get("action"), "click")
        template_path = _visual_asset_template_path(asset)
        if not asset_id or not label or not template_path:
            skipped.append({"asset_id": asset_id, "reason": "missing_asset_id_label_or_template"})
            continue
        if not _visual_asset_relevant_to_goal(asset, goal):
            skipped.append({"asset_id": asset_id, "label": label, "reason": "not_goal_relevant"})
            continue
        min_score = _visual_asset_min_score(asset)
        allowed_region = _visual_asset_allowed_region(asset, image_size=image_size)
        match = match_visual_asset(
            asset_id=asset_id,
            template_path=template_path,
            target_image_path=image_path,
            label=label,
            semantic_action=semantic_action,
            allowed_region=allowed_region,
            scales=tuple(_visual_asset_scales(asset)),
            min_score=min_score,
            min_score_gap=_visual_asset_min_score_gap(asset),
            artifact_dir=ARTIFACTS_DIR / "visual-matches" / _safe_visual_asset_run_name(Path(image_path).stem),
            capture_id=str(image_path),
            viewport_size=image_size.to_dict(),
        )
        match["asset_summary"] = {
            "asset_id": asset_id,
            "label": label,
            "semantic_action": semantic_action,
            "danger_level": asset.get("danger_level"),
            "requires_gate": asset.get("requires_gate"),
            "review_policy": asset.get("review_policy") if isinstance(asset.get("review_policy"), dict) else None,
            "source_capture_id": ((asset.get("source") or {}).get("capture_id") if isinstance(asset.get("source"), dict) else None),
        }
        matches.append(match)

    matched = [item for item in matches if item.get("matched") is True]
    matched.sort(key=lambda item: float(item.get("match_score") or 0.0), reverse=True)
    selected_match = next((item for item in matched if _visual_asset_fast_lane_allowed(item)), None)
    selected_candidate = selected_match.get("candidate") if isinstance(selected_match, dict) else None
    status = "matched" if matched else "no_match"
    return {
        "contract_version": VISUAL_ASSET_RECALL_CONTRACT,
        "status": status,
        "asset_count": len(assets),
        "matched_count": len(matched),
        "skipped": skipped[:20],
        "matches": matches[:20],
        "selected_asset_id": selected_match.get("asset_id") if isinstance(selected_match, dict) else None,
        "selected_candidate": selected_candidate,
        "fast_lane_allowed": bool(selected_candidate and selected_match and _visual_asset_fast_lane_allowed(selected_match)),
        "fast_lane_reason": "low_risk_visual_asset_current_capture_match"
        if selected_candidate
        else "no_low_risk_matched_asset",
    }


def _visual_asset_stores_from_sources(
    *, metadata: dict[str, Any] | None, observe_reuse: dict[str, Any]
) -> list[dict[str, Any]]:
    stores: list[dict[str, Any]] = []
    if isinstance(metadata, dict):
        for key in ("visual_assets", "visual_asset_store"):
            value = metadata.get(key)
            if isinstance(value, dict):
                stores.append(value)
        learning = metadata.get("visual_asset_learning")
        if isinstance(learning, dict) and isinstance(learning.get("visual_assets"), dict):
            stores.append(learning["visual_assets"])
        interface_map = metadata.get("learned_interface_map")
        interface_store = _visual_asset_store_from_interface_map(interface_map)
        if interface_store is not None:
            stores.append(interface_store)
    observe_result = observe_reuse.get("observe_result") if isinstance(observe_reuse, dict) else None
    if isinstance(observe_result, dict):
        learning = observe_result.get("visual_asset_learning")
        if isinstance(learning, dict) and isinstance(learning.get("visual_assets"), dict):
            stores.append(learning["visual_assets"])
        interface_store = _visual_asset_store_from_interface_map(observe_result.get("learned_interface_map"))
        if interface_store is not None:
            stores.append(interface_store)
        screen_map = observe_result.get("screen_map")
        if isinstance(screen_map, dict) and isinstance(screen_map.get("visual_assets"), dict):
            stores.append(screen_map["visual_assets"])
    screen_map = observe_reuse.get("screen_map") if isinstance(observe_reuse, dict) else None
    if isinstance(screen_map, dict) and isinstance(screen_map.get("visual_assets"), dict):
        stores.append(screen_map["visual_assets"])
    return stores


def _visual_asset_store_from_interface_map(interface_map: Any) -> dict[str, Any] | None:
    if not isinstance(interface_map, dict):
        return None
    fixed_assets = interface_map.get("fixed_visual_assets")
    if not isinstance(fixed_assets, list):
        return None
    assets = [item for item in fixed_assets if isinstance(item, dict)]
    if not assets:
        return None
    return {
        "contract_version": "visual_asset_store_v1",
        "source_contract_version": interface_map.get("contract_version"),
        "asset_status_default": "from_learned_interface_map",
        "asset_match_is_evidence_only": True,
        "asset_can_authorize_click": False,
        "assets": assets,
    }


def _visual_asset_items_from_stores(stores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for store in stores:
        assets = store.get("assets")
        if not isinstance(assets, list):
            continue
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            key = str(asset.get("asset_id") or asset.get("id") or asset.get("candidate_id") or id(asset))
            if key in seen:
                continue
            seen.add(key)
            items.append(asset)
    return items


def _visual_asset_template_path(asset: dict[str, Any]) -> str | None:
    crop = asset.get("crop") if isinstance(asset.get("crop"), dict) else {}
    source = asset.get("source") if isinstance(asset.get("source"), dict) else {}
    template_refs = asset.get("template_refs") if isinstance(asset.get("template_refs"), dict) else {}
    for value in (
        template_refs.get("tight_crop_ref"),
        template_refs.get("crop_ref"),
        template_refs.get("template_path"),
        crop.get("tight_crop_ref"),
        crop.get("crop_ref"),
        crop.get("template_path"),
        source.get("crop_path"),
    ):
        if value and Path(str(value)).exists():
            return str(value)
    return None


def _visual_asset_relevant_to_goal(asset: dict[str, Any], goal: str | None) -> bool:
    goal_text = str(goal or "").casefold()
    if not goal_text:
        return True
    label = str(asset.get("label") or "").casefold()
    semantic_action = str(asset.get("semantic_action") or "").casefold()
    action_terms = {
        "open_apply_flow": ("apply", "quick apply", "申请", "快速申请"),
        "continue_next_step": ("continue", "next", "下一步", "继续"),
        "final_submit": ("submit", "send", "confirm", "提交", "发送", "确认"),
        "save": ("save", "saved", "保存", "收藏"),
        "search": ("search", "find", "搜索", "查找"),
        "filter": ("filter", "refine", "pay", "date listed", "classification", "筛选"),
    }
    label_terms = _visual_asset_goal_label_terms(label)
    goal_action_terms = _visual_asset_goal_action_terms(goal_text, action_terms)
    if goal_action_terms:
        semantic_terms = set(action_terms.get(semantic_action, (semantic_action,)))
        if semantic_terms & goal_action_terms:
            return True
        return bool(label_terms & goal_action_terms)
    if any(token in goal_text for token in label_terms):
        return True
    if semantic_action and semantic_action not in {"click", "press"}:
        return semantic_action in goal_text
    return False


def _visual_asset_goal_label_terms(label: str) -> set[str]:
    stop_terms = {
        "seek",
        "jobs",
        "job",
        "page",
        "detail",
        "details",
        "area",
        "top",
        "selected",
        "results",
        "result",
    }
    return {
        token
        for token in re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", label.casefold()).split()
        if len(token) >= 3 and token not in stop_terms
    }


def _visual_asset_goal_action_terms(goal_text: str, action_terms: dict[str, tuple[str, ...]]) -> set[str]:
    terms: set[str] = set()
    for semantic_action, values in action_terms.items():
        if semantic_action == "final_submit" and not _looks_like_final_submit_action_text(goal_text):
            continue
        for term in values:
            if term and term in goal_text:
                terms.add(term)
    return terms


def _visual_asset_min_score(asset: dict[str, Any]) -> float:
    policy = asset.get("match_policy") if isinstance(asset.get("match_policy"), dict) else {}
    try:
        return max(0.5, min(0.99, float(policy.get("min_score", 0.9))))
    except (TypeError, ValueError):
        return 0.9


def _visual_asset_min_score_gap(asset: dict[str, Any]) -> float:
    policy = asset.get("match_policy") if isinstance(asset.get("match_policy"), dict) else {}
    try:
        return max(0.0, min(0.5, float(policy.get("min_score_gap", 0.0))))
    except (TypeError, ValueError):
        return 0.0


def _visual_asset_scales(asset: dict[str, Any]) -> list[float]:
    policy = asset.get("match_policy") if isinstance(asset.get("match_policy"), dict) else {}
    raw_scales = policy.get("scales") or policy.get("scale_variants")
    if isinstance(raw_scales, list):
        result: list[float] = []
        for value in raw_scales:
            try:
                result.append(float(value))
            except (TypeError, ValueError):
                continue
        if result:
            return result
    return [0.92, 1.0, 1.08]


def _visual_asset_allowed_region(asset: dict[str, Any], *, image_size: ImageSize) -> dict[str, Any] | None:
    source_geometry = asset.get("source_geometry") if isinstance(asset.get("source_geometry"), dict) else {}
    bbox = _normalize_map_bbox(source_geometry.get("bbox") or asset.get("bbox"))
    if not bbox:
        return None
    source = asset.get("source") if isinstance(asset.get("source"), dict) else {}
    source_size = source.get("screenshot_size") if isinstance(source.get("screenshot_size"), dict) else {}
    same_viewport = (
        int(source_size.get("width") or image_size.width) == int(image_size.width)
        and int(source_size.get("height") or image_size.height) == int(image_size.height)
    )
    if not same_viewport:
        return None
    pad_x = max(80, int(bbox["w"] * 3))
    pad_y = max(60, int(bbox["h"] * 3))
    x = max(0, int(bbox["x"]) - pad_x)
    y = max(0, int(bbox["y"]) - pad_y)
    right = min(int(image_size.width), int(bbox["x"] + bbox["w"]) + pad_x)
    bottom = min(int(image_size.height), int(bbox["y"] + bbox["h"]) + pad_y)
    region = {"x": x, "y": y, "w": max(1, right - x), "h": max(1, bottom - y)}
    scope = asset.get("scope") if isinstance(asset.get("scope"), dict) else {}
    container_ids = scope.get("allowed_container_ids") if isinstance(scope.get("allowed_container_ids"), list) else []
    if not container_ids and isinstance(asset.get("allowed_region_ids"), list):
        container_ids = asset["allowed_region_ids"]
    if not container_ids and asset.get("region_id"):
        container_ids = [asset.get("region_id")]
    if container_ids:
        region["container_id"] = str(container_ids[0])
    return region


def _visual_asset_fast_lane_allowed(match: dict[str, Any]) -> bool:
    if not match.get("matched"):
        return False
    summary = match.get("asset_summary") if isinstance(match.get("asset_summary"), dict) else {}
    semantic_action = str(match.get("semantic_action") or summary.get("semantic_action") or "").casefold()
    danger_level = str(summary.get("danger_level") or "").casefold()
    label = str(match.get("label") or "").casefold()
    review_policy = summary.get("review_policy") if isinstance(summary.get("review_policy"), dict) else {}
    if review_policy and not review_policy.get("fast_lane_eligible"):
        return False
    if semantic_action == "final_submit" or danger_level == "final_submit":
        return False
    if _looks_like_final_submit_action_text(" ".join([label, semantic_action, danger_level])):
        return False
    return bool(match.get("candidate"))


def _trace_enabled(request: Any) -> bool:
    write_policy = getattr(request, "write_policy", None)
    payload = write_policy.model_dump() if hasattr(write_policy, "model_dump") else dict(write_policy or {})
    return payload.get("trace", True) is not False


def _write_trace_if_enabled(request: Any, **kwargs: Any) -> str | None:
    operation = kwargs.get("operation")
    agent_mode = getattr(request, "agent_mode", None)
    learn_depth = getattr(request, "learn_depth", None)
    if operation == "recognition_plan" and agent_mode == "execute":
        kwargs["operation"] = "execute_mode_recognition_plan"
    elif operation == "locate_target" and agent_mode == "learn" and learn_depth == "deep":
        kwargs["operation"] = "learn_mode_deep_locate"
    elif operation == "observe_screen" and agent_mode == "learn":
        kwargs["operation"] = "learn_mode_fast_observe"
    return write_trace(**kwargs) if _trace_enabled(request) else None


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
        operation_context = build_operation_runtime_context(
            request=request,
            skill_id="read_region",
            semantic_action="read_region",
            side_effect_class="read_only",
            requires_gate=False,
            capture_id=capture.get("image_path"),
            viewport_size=capture.get("window_size") if isinstance(capture.get("window_size"), dict) else None,
            evidence_refs=[str(capture.get("image_path"))] if capture.get("image_path") else [],
        )
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
            "operation_context": operation_context,
            "operation_trace_link": operation_trace_link(operation_context, result_status="success"),
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
        _attach_model_io(result_payload, response)
        result_payload["execution_path"] = _vision_execution_path(
            requested_mode=request.provider_mode or str((config.get("vision") or {}).get("mode") or "local"),
            response_provider=response.provider,
            raw_response=response.raw_response,
            page_structure_generated=False,
            ocr_region_refine_used=refine_options.enabled,
        )
        if ocr_result is not None:
            result_payload["ocr_result"] = ocr_result.to_dict()
        result_payload["trace_path"] = _write_trace_if_enabled(
            request,
            category="vision",
            operation="vision_analyze",
            payload={"success": True, "request": request.model_dump(), "result": result_payload},
            name_hint=request.app_name or image_path.stem,
        )
        data = VisionResultData(result=result_payload)
        return APIResponse(success=True, message="Vision analysis completed", data=data.model_dump(), error=None)
    except Exception as exc:
        model_io = _model_io_failure_payload(exc)
        failure_payload = {"success": False, "request": request.model_dump(), "error": str(exc)}
        if model_io is not None:
            failure_payload["model_io"] = model_io
        trace_path = _write_trace_if_enabled(
            request,
            category="vision",
            operation="vision_analyze",
            payload=failure_payload,
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
        _attach_model_io(result_payload, response)
        result_payload["execution_path"] = _vision_execution_path(
            requested_mode=request.provider_mode or str((config.get("vision") or {}).get("mode") or "local"),
            response_provider=response.provider,
            raw_response=response.raw_response,
            page_structure_generated=True,
            ocr_region_refine_used=refine_options.enabled,
        )
        result_payload["trace_path"] = _write_trace_if_enabled(
            request,
            category="vision",
            operation="page_structure",
            payload={"success": True, "request": request.model_dump(), "result": result_payload},
            name_hint=request.app_name or image_path.stem,
        )
        data = VisionResultData(result=result_payload)
        return APIResponse(success=True, message="Page structure completed", data=data.model_dump(), error=None)
    except Exception as exc:
        model_io = _model_io_failure_payload(exc)
        failure_payload = {"success": False, "request": request.model_dump(), "error": str(exc)}
        if model_io is not None:
            failure_payload["model_io"] = model_io
        trace_path = _write_trace_if_enabled(
            request,
            category="vision",
            operation="page_structure",
            payload=failure_payload,
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
        _attach_model_io(result_payload, response)
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
        result_payload["trace_path"] = _write_trace_if_enabled(
            request,
            category="vision",
            operation="screen_reading",
            payload={"success": True, "request": request.model_dump(), "result": result_payload},
            name_hint=request.app_name or image_path.stem,
        )
        data = VisionResultData(result=result_payload)
        return APIResponse(success=True, message="Screen reading completed", data=data.model_dump(), error=None)
    except Exception as exc:
        model_io = _model_io_failure_payload(exc)
        failure_payload = {"success": False, "request": request.model_dump(), "error": str(exc)}
        if model_io is not None:
            failure_payload["model_io"] = model_io
        trace_path = _write_trace_if_enabled(
            request,
            category="vision",
            operation="screen_reading",
            payload=failure_payload,
            name_hint=request.app_name or image_path.stem,
        )
        return APIResponse(
            success=False,
            message="Screen reading failed",
            data={"trace_path": trace_path, "model_io": model_io} if model_io is not None else {"trace_path": trace_path},
            error=ErrorModel(code="screen_reading_failed", details=str(exc)),
        )


def _observe_screen_provider_mode(provider_mode: str | None) -> str:
    """整屏观察必须使用理解模型，不能继承最近一次定位模型切换。"""

    requested = str(provider_mode or "").strip().casefold()
    if requested in {"", "local", "local_grounding"}:
        return "local_understanding"
    return str(provider_mode).strip()


@router.post("/observe_screen", response_model=APIResponse)
def observe_screen(request: VisionObserveScreenRequestModel) -> APIResponse:
    """Capture or read a screen and return broad UI understanding for agent planning."""
    timer = RuntimeTimer()
    try:
        with timer.step("resolve_image_source", capture_live=request.capture_live):
            image_path, live_capture = _learning_observe_image_source(request)
        operation_context = build_operation_runtime_context(
            request=request,
            skill_id="observe_screen",
            semantic_action="observe_screen",
            side_effect_class="read_only",
            requires_gate=False,
            capture_id=image_path,
            viewport_size=_image_size_payload(image_path=image_path, live_capture=live_capture),
            evidence_refs=[image_path],
        )
        screen_request = VisionAnalyzeRequestModel(
            image_path=image_path,
            task=request.task,
            app_name=request.app_name,
            goal="understand the current interface, visible controls, and likely actions",
            state_hint=request.state_hint,
            provider_mode=_observe_screen_provider_mode(request.provider_mode),
            agent_mode=request.agent_mode,
            learn_depth=request.learn_depth,
            write_policy=request.write_policy,
            metadata={
                **dict(request.metadata or {}),
                "ocr_anchors": {"enabled": True, "max_anchors": "all", **dict((request.metadata or {}).get("ocr_anchors") or {})}
                if isinstance((request.metadata or {}).get("ocr_anchors"), dict)
                else (request.metadata or {}).get("ocr_anchors", {"enabled": True, "max_anchors": "all"}),
            },
            operation_context=operation_context,
        )
        with timer.step("screen_reading"):
            response = screen_reading(screen_request)
        if not response.success or not response.data:
            with timer.step("observe_degraded_fallback"):
                result = _build_degraded_observation_result(
                    request=request,
                    image_path=image_path,
                    live_capture=live_capture,
                    screen_response=response,
                )
        else:
            result = response.data["result"]
        result["contract_version"] = "screen_observation_v1"
        result.update(_mode_payload(request, fallback_contract="screen_observation_v1"))
        result["live_capture"] = live_capture
        result["operation_context"] = operation_context
        result["operation_trace_link"] = operation_trace_link(operation_context, result_status="success", evidence_refs=[image_path])
        result["suggested_state_hint"] = _suggested_state_hint_from_observation(result)
        result["screen_map"] = _build_screen_map_from_observation(result, request=request, image_path=image_path)
        result["screen_map"] = _apply_learned_path_graph_to_screen_map(
            result["screen_map"],
            result=result,
            request=request,
            image_path=image_path,
        )
        if request.learn_depth == "deep":
            with timer.step("learn_deep_review"):
                deep_result = _build_learn_deep_review(
                    result=result,
                    screen_map=result["screen_map"],
                    request=request,
                )
            result["screen_map"] = deep_result["screen_map"]
            result["path_graph_deep_review"] = deep_result["path_graph_deep_review"]
            result["path_graph_delta"] = deep_result["path_graph_delta"]
            result["element_memory_init_plan"] = deep_result["element_memory_init_plan"]
        if _should_learn_visual_assets(request):
            page_type = result["screen_map"].get("page_type") or result.get("state_guess") or request.state_hint
            if not Path(image_path).exists():
                visual_asset_learning = _skipped_visual_asset_learning(
                    image_path=image_path,
                    reason="missing_source_image",
                    app_id=request.app_name or result.get("app_name"),
                    page_type=page_type,
                    learn_depth=request.learn_depth,
                )
            else:
                try:
                    with timer.step("learn_visual_assets"):
                        visual_asset_learning = build_visual_assets_from_screen_map(
                            result["screen_map"],
                            source_image_path=image_path,
                            output_dir=ARTIFACTS_DIR
                            / "visual-assets"
                            / _safe_visual_asset_run_name(request.app_name or result.get("app_name") or Path(image_path).stem),
                            app_id=request.app_name or result.get("app_name"),
                            page_type=page_type,
                            capture_id=str(image_path),
                            learn_depth=request.learn_depth,
                        )
                except Exception as exc:
                    visual_asset_learning = _skipped_visual_asset_learning(
                        image_path=image_path,
                        reason="visual_asset_learning_failed",
                        app_id=request.app_name or result.get("app_name"),
                        page_type=page_type,
                        learn_depth=request.learn_depth,
                        error_detail=str(exc),
                    )
            result["visual_asset_learning"] = visual_asset_learning
            result["screen_map"]["visual_assets"] = visual_asset_learning.get("visual_assets")
            with timer.step("build_learned_interface_map"):
                learned_interface_map = build_learned_interface_map(
                    _runtime_graph_from_screen_map_for_interface_map(result["screen_map"], result=result),
                    visual_asset_learning.get("visual_assets"),
                )
            result["learned_interface_map"] = learned_interface_map
            result["screen_map"]["learned_interface_map_summary"] = learned_interface_map.get("summary")
        result["agent_next_steps"] = [
            "Read screen_map.candidates to decide what the user likely wants; it is a semantic map, not executable coordinates.",
            "Use screen_map.state_id and suggested_state_hint as the default context for POST /vision/locate_target unless the user overrides it.",
            "When a concrete target is chosen, call POST /vision/locate_target with that candidate label/goal.",
            "Execute only through POST /action/execute_recognition_plan after pre_click_decision allows it.",
        ]
        result["timings"] = timer.to_dict()
        result["trace_path"] = _write_trace_if_enabled(
            request,
            category="vision",
            operation="observe_screen",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint=request.app_name or Path(image_path).stem,
        )
        data = VisionResultData(result=result)
        return APIResponse(success=True, message="Screen observation completed", data=data.model_dump(), error=None)
    except Exception as exc:
        timings = timer.to_dict()
        model_io = _model_io_failure_payload(exc)
        failure_payload = {"success": False, "request": request.model_dump(), "error": str(exc), "timings": timings}
        if model_io is not None:
            failure_payload["model_io"] = model_io
        trace_path = _write_trace_if_enabled(
            request,
            category="vision",
            operation="observe_screen",
            payload=failure_payload,
            name_hint=request.app_name or "observe_screen",
        )
        return APIResponse(
            success=False,
            message="Screen observation failed",
            data={"trace_path": trace_path, "timings": timings, "model_io": model_io} if model_io is not None else {"trace_path": trace_path, "timings": timings},
            error=ErrorModel(code="observe_screen_failed", details=str(exc)),
        )


def _build_degraded_observation_result(
    *,
    request: VisionObserveScreenRequestModel,
    image_path: str,
    live_capture: dict[str, Any] | None,
    screen_response: APIResponse,
) -> dict[str, Any]:
    image_size = _image_size_payload(image_path=image_path, live_capture=live_capture)
    ocr_payload: dict[str, Any] = {"image_path": image_path, "matches": [], "metadata": {"status": "unavailable"}}
    ocr_error = None
    try:
        ocr_payload = ocr_service.scan_image(str(image_path)).to_dict()
    except Exception as exc:
        ocr_error = str(exc)
        ocr_payload["metadata"] = {"status": "failed", "error": ocr_error}

    try:
        uia_snapshot = uia_provider.snapshot_bound_window()
    except Exception as exc:
        uia_snapshot = {"provider": "windows_uia", "status": "failed", "reason": str(exc), "control_count": 0, "controls": []}

    texts = _texts_from_ocr_payload(ocr_payload)
    error_details = screen_response.error.model_dump() if hasattr(screen_response.error, "model_dump") else screen_response.error
    screen_response_data = screen_response.data if isinstance(screen_response.data, dict) else {}
    model_io = screen_response_data.get("model_io") if isinstance(screen_response_data.get("model_io"), dict) else None
    screen_summary = "Degraded screen observation from OCR/UIA because model screen reading failed."
    state_guess = request.state_hint or _first_compact_text(*(item.get("text") for item in texts[:5])) or "ocr fallback observation"
    screen_reading_payload = {
        "contract_version": "screen_reading_v1",
        "status": "degraded",
        "image_path": image_path,
        "app_name": request.app_name,
        "image_size": image_size,
        "screen_summary": screen_summary,
        "state_guess": state_guess,
        "texts": texts,
        "ui": {
            "summary": {
                "element_count": 0,
                "module_count": 0,
                "icon_candidate_count": 0,
                "text_backed_element_count": 0,
                "visual_only_element_count": 0,
            },
            "elements": [],
            "modules": [],
            "icon_candidates": [],
            "provider_slots": {
                "uia": {
                    "status": "connected",
                    "last_scan_status": uia_snapshot.get("status"),
                    "control_count": uia_snapshot.get("control_count"),
                }
            },
            "learning_hooks": [],
        },
        "ui_elements": [],
        "modules": [],
        "relationships": [],
        "execution_relevance": {"safe_action_candidates": [], "risky_candidates": [], "unknown_candidates": []},
        "uncertainties": {
            "status": "degraded_model_failure",
            "reason": "screen_reading_failed",
            "needed_evidence": ["model_json_repair_or_retry", "locate_target_before_click"],
        },
        "source_layers": {
            "vision_regions_v1": {"provider": request.provider_mode or "local_understanding", "status": "failed", "error": error_details},
            "ocr_result": {"engine": str((ocr_payload.get("metadata") or {}).get("engine") or "ocr"), "match_count": len(texts), "error": ocr_error},
            "windows_uia": {
                "status": uia_snapshot.get("status"),
                "control_count": uia_snapshot.get("control_count"),
                "available": uia_snapshot.get("status") == "ok",
            },
        },
        "raw_refs": {
            "ocr_image_path": ocr_payload.get("image_path"),
            "degraded_from_error": error_details,
            "model_io": model_io,
        },
    }
    return {
        "contract_version": "screen_observation_v1",
        "status": "degraded",
        "image_path": image_path,
        "image_size": image_size,
        "app_name": request.app_name,
        "screen_summary": screen_summary,
        "state_guess": state_guess,
        "texts": texts,
        "ocr_result": ocr_payload,
        "screen_reading": screen_reading_payload,
        "degraded_reason": {
            "code": "screen_reading_failed",
            "message": screen_response.message,
            "error": error_details,
            "model_io": model_io,
        },
        "execution_path": {
            "vision_provider_requested": request.provider_mode or "local_understanding",
            "vision_provider_used": None,
            "vision_model_used": False,
            "page_structure_used": False,
            "screen_reading_used": False,
            "degraded_observe_fallback_used": True,
            "coordinate_source": "ocr_result_v1",
        },
    }


def _image_size_payload(*, image_path: str, live_capture: dict[str, Any] | None) -> dict[str, int]:
    if isinstance(live_capture, dict):
        width = _number(live_capture.get("image_width") or live_capture.get("width"))
        height = _number(live_capture.get("image_height") or live_capture.get("height"))
        if width and height:
            return {"width": int(width), "height": int(height)}
    try:
        with Image.open(image_path) as image:
            return {"width": int(image.width), "height": int(image.height)}
    except Exception:
        return {"width": 0, "height": 0}


def _texts_from_ocr_payload(ocr_payload: dict[str, Any]) -> list[dict[str, Any]]:
    texts: list[dict[str, Any]] = []
    for index, match in enumerate(_as_list(ocr_payload.get("matches"))):
        if not isinstance(match, dict):
            continue
        text = _first_compact_text(match.get("text"))
        bbox = _normalize_map_bbox(match.get("bbox"))
        if not text or not bbox:
            continue
        texts.append(
            {
                "id": f"ocr_fallback_text_{index}",
                "text": text,
                "bbox": bbox,
                "confidence": _bounded_float(match.get("score")) or 0.0,
                "source": "ocr_fallback",
                "source_index": index,
            }
        )
    return texts


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


def _runtime_graph_from_screen_map_for_interface_map(screen_map: dict[str, Any], *, result: dict[str, Any]) -> dict[str, Any]:
    """把 observe 的 screen_map 转成 Interface Map 所需的最小路径图。"""

    graph = screen_map if isinstance(screen_map, dict) else {}
    state_id = str(graph.get("state_id") or "observed_state")
    page_type = str(graph.get("page_type") or graph.get("state_hint") or result.get("state_guess") or "observed_page")
    regions: list[dict[str, Any]] = []
    for section in graph.get("sections") or []:
        if not isinstance(section, dict):
            continue
        section_id = str(section.get("section_id") or section.get("region_id") or "").strip()
        if not section_id:
            continue
        regions.append(
            {
                "region_id": section_id,
                "label": section.get("label") or section_id,
                "role": section.get("role") or section.get("section_type") or "content",
                "bbox": section.get("bbox") if isinstance(section.get("bbox"), dict) else None,
                "container_id": section.get("container_id") or section_id,
                "repeatable": bool(section.get("repeatable")),
            }
        )
    return {
        "contract_version": "runtime_path_graph_v1",
        "graph_id": f"{graph.get('app_name') or result.get('app_name') or 'app'}:{page_type}:observe_interface_seed",
        "app_id": graph.get("app_name") or result.get("app_name"),
        "page_type": page_type,
        "states": [
            {
                "state_id": state_id,
                "label": graph.get("state_hint") or result.get("state_guess") or state_id,
                "state_fingerprint": graph.get("state_signature") if isinstance(graph.get("state_signature"), dict) else {},
            }
        ],
        "regions": regions,
        "source": {
            "contract_version": graph.get("contract_version"),
            "artifact_is_authorization": False,
            "source": "screen_map_v1",
        },
    }


def _apply_learned_path_graph_to_screen_map(
    screen_map: dict[str, Any],
    *,
    result: dict[str, Any],
    request: VisionObserveScreenRequestModel,
    image_path: str,
) -> dict[str, Any]:
    graph_info = _default_learned_runtime_path_graph(result, request=request)
    graph = graph_info.get("graph") if isinstance(graph_info, dict) else None
    if not isinstance(graph, dict):
        return screen_map
    screen_inventory = _observation_screen_inventory(result)
    if _observation_looks_like_seek_application_form(result, screen_inventory=screen_inventory):
        assisted = dict(screen_map)
        assisted["learned_path_graph_resolution"] = {
            "contract_version": "learned_path_graph_observe_resolution_v1",
            "matched": False,
            "reason": "seek_application_form_not_search_results",
            "graph_path": graph_info.get("path"),
        }
        return assisted
    resolution = resolve_runtime_path_graph(
        graph,
        screen_inventory=screen_inventory,
        requested_state_id=None,
        safety={
            "forbid_final_submit": False,
            "allow_apply_entry": False,
            "allow_safe_fill": False,
        },
    )
    if not resolution.get("matched"):
        assisted = dict(screen_map)
        assisted["learned_path_graph_resolution"] = {
            **resolution,
            "contract_version": "learned_path_graph_observe_resolution_v1",
            "graph_path": graph_info.get("path"),
        }
        return assisted
    sections = _screen_map_sections_from_runtime_path_graph(
        graph,
        result=result,
        image_path=image_path,
        fallback_sections=screen_map.get("sections") if isinstance(screen_map.get("sections"), list) else [],
    )
    actions = build_available_actions(
        graph,
        current_state_id=resolution.get("state_id"),
        include_guarded_apply=False,
        path_graph_resolution=resolution,
    )
    path_candidates = _screen_map_candidates_from_path_graph_actions(actions, sections=sections)
    observed_candidates = _resection_observed_candidates_for_path_graph(
        screen_map.get("candidates") if isinstance(screen_map.get("candidates"), list) else [],
        sections=sections,
        graph_app_id=str(graph.get("app_id") or ""),
    )
    candidates = _dedupe_screen_map_candidates([*path_candidates, *observed_candidates])
    assisted = {
        **screen_map,
        "state_id": resolution.get("state_id") or screen_map.get("state_id"),
        "state_hint": graph.get("page_type") or screen_map.get("state_hint"),
        "sections": sections,
        "candidates": candidates[:80],
        "learned_path_graph_resolution": {
            **resolution,
            "contract_version": "learned_path_graph_observe_resolution_v1",
            "graph_path": graph_info.get("path"),
            "source": "runtime_path_graph_v1",
            "screen_map_policy": "learned_path_graph_primary_model_supplemental",
        },
        "learned_path_graph_available_actions": actions,
    }
    summary = dict(assisted.get("summary") if isinstance(assisted.get("summary"), dict) else {})
    summary.update(
        {
            "candidate_count": len(assisted["candidates"]),
            "safe_candidate_count": len([item for item in assisted["candidates"] if item.get("risk_class") == "safe_click_allowed"]),
            "blocked_candidate_count": len([item for item in assisted["candidates"] if item.get("risk_class") == "blocked"]),
            "section_count": len(sections),
            "learned_path_graph_used": True,
            "learned_path_graph_id": graph.get("graph_id"),
        }
    )
    assisted["summary"] = summary
    agent_usage = dict(assisted.get("agent_usage") if isinstance(assisted.get("agent_usage"), dict) else {})
    agent_usage["observe_role"] = "Use the learned runtime PathGraph as the primary page structure; use model output only as current text/evidence."
    agent_usage["execute_role"] = "Choose from learned_path_graph_available_actions, then validate coordinates through the gated action API."
    assisted["agent_usage"] = agent_usage
    return assisted


def _default_learned_runtime_path_graph(result: dict[str, Any], *, request: VisionObserveScreenRequestModel) -> dict[str, Any]:
    key = _learned_path_graph_key(result, request=request)
    path = DEFAULT_LEARNED_RUNTIME_PATH_GRAPHS.get(key)
    if not path or not path.exists():
        return {}
    try:
        graph = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    if not isinstance(graph, dict) or graph.get("contract_version") != "runtime_path_graph_v1":
        return {}
    return {"key": key, "path": str(path), "graph": graph}


def _learned_path_graph_key(result: dict[str, Any], *, request: VisionObserveScreenRequestModel) -> str | None:
    haystack = " ".join(
        str(item or "")
        for item in [
            request.app_name,
            request.state_hint,
            result.get("app_name"),
            result.get("state_guess"),
            result.get("screen_summary"),
            (result.get("screen_reading") or {}).get("screen_summary") if isinstance(result.get("screen_reading"), dict) else "",
            (result.get("screen_reading") or {}).get("state_guess") if isinstance(result.get("screen_reading"), dict) else "",
        ]
    ).casefold()
    if "seek" in haystack or "nz.seek" in haystack or "job search" in haystack:
        return "seek"
    return None


def _observation_screen_inventory(result: dict[str, Any]) -> dict[str, Any] | None:
    if isinstance(result.get("screen_inventory"), dict):
        return result["screen_inventory"]
    screen_reading = result.get("screen_reading") if isinstance(result.get("screen_reading"), dict) else {}
    if isinstance(screen_reading.get("screen_inventory"), dict):
        return screen_reading["screen_inventory"]
    parse_result = result.get("parse_result") if isinstance(result.get("parse_result"), dict) else {}
    nested = parse_result.get("screen_reading") if isinstance(parse_result.get("screen_reading"), dict) else {}
    if isinstance(nested.get("screen_inventory"), dict):
        return nested["screen_inventory"]
    return None


def _observation_looks_like_seek_application_form(result: dict[str, Any], *, screen_inventory: dict[str, Any] | None) -> bool:
    labels = " ".join(_inventory_texts(screen_inventory)).casefold()
    fields = [
        result.get("screen_summary"),
        result.get("state_guess"),
        (result.get("screen_reading") or {}).get("screen_summary") if isinstance(result.get("screen_reading"), dict) else "",
        (result.get("screen_reading") or {}).get("state_guess") if isinstance(result.get("screen_reading"), dict) else "",
        labels,
    ]
    text = " ".join(str(item or "") for item in fields).casefold()
    form_terms = [
        "choose documents",
        "answer employer questions",
        "update seek profile",
        "review and submit",
        "application form",
        "cover letter",
    ]
    return any(term in text for term in form_terms)


def _screen_map_sections_from_runtime_path_graph(
    graph: dict[str, Any],
    *,
    result: dict[str, Any],
    image_path: str,
    fallback_sections: list[Any],
) -> list[dict[str, Any]]:
    width, height = _screen_map_image_size(result, image_path=image_path)
    learned_bboxes = _learned_graph_region_bboxes(graph, width=width, height=height)
    sections: list[dict[str, Any]] = []
    fallback_by_id = {str(item.get("section_id") or ""): item for item in fallback_sections if isinstance(item, dict)}
    for region in graph.get("regions") or []:
        if not isinstance(region, dict):
            continue
        region_id = str(region.get("region_id") or "").strip()
        if not region_id:
            continue
        bbox = learned_bboxes.get(region_id) or _normalize_map_bbox(region.get("bbox")) or _normalize_map_bbox(fallback_by_id.get(region_id, {}).get("bbox"))
        section = {
            "contract_version": "screen_map_section_v1",
            "section_id": region_id,
            "label": region.get("label") or region_id.replace("_", " ").title(),
            "role": region.get("role") or "content",
            "description": "Learned from runtime_path_graph_v1.",
            "bbox": bbox,
            "container_id": region.get("container_id"),
            "parent_section_id": region.get("parent_region_id"),
            "repeatable": bool(region.get("repeatable")),
            "contains": region.get("contains") or [],
            "source": "runtime_path_graph_v1",
            "text_count": 0,
            "text_sample": [],
        }
        texts = _texts_in_bbox(_screen_map_texts(result), bbox) if bbox else []
        section["text_count"] = len(texts)
        section["text_sample"] = [_first_compact_text(item.get("text")) for item in texts[:10] if _first_compact_text(item.get("text"))]
        sections.append(section)
    return sections or [item for item in fallback_sections if isinstance(item, dict)]


def _screen_map_candidates_from_path_graph_actions(actions: dict[str, Any], *, sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    payload = actions.get("actions") if isinstance(actions, dict) else []
    candidates: list[dict[str, Any]] = []
    for index, action in enumerate(payload if isinstance(payload, list) else []):
        if not isinstance(action, dict):
            continue
        action_id = str(action.get("action_template_id") or action.get("action_id") or f"path_action_{index}")
        section_id = _section_for_path_graph_action(action_id, action)
        bbox = _section_bbox(sections, section_id)
        candidates.append(
            {
                "contract_version": "screen_map_candidate_v1",
                "candidate_id": f"path_graph_action_{action_id}",
                "label": action.get("label") or action.get("goal_template") or action_id.replace("_", " "),
                "role": action.get("action_kind") or action.get("low_level_action_type") or "action",
                "goal_hint": action.get("goal_template") or action_id,
                "expected_effect": action.get("to_state_id") or action.get("transition_id") or "",
                "risk_class": "safe_click_allowed" if action.get("low_level_action_type") in {"click", "scroll", "input"} else "safe_review_only",
                "section_id": section_id,
                "bbox": bbox,
                "click_point": _bbox_center(bbox),
                "confidence": 0.92,
                "source": "runtime_path_graph_v1",
                "action_template_id": action_id,
                "low_level_action_type": action.get("low_level_action_type"),
                "artifact_is_authorization": False,
            }
        )
    return candidates


def _resection_observed_candidates_for_path_graph(
    candidates: list[Any],
    *,
    sections: list[dict[str, Any]],
    graph_app_id: str,
) -> list[dict[str, Any]]:
    learned_sections = [item for item in sections if isinstance(item, dict) and item.get("bbox")]
    results: list[dict[str, Any]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        candidate = dict(item)
        bbox = _normalize_map_bbox(candidate.get("bbox"))
        section_id = _best_section_id_for_bbox(bbox, learned_sections) if bbox else candidate.get("section_id")
        if section_id:
            candidate["section_id"] = section_id
        if graph_app_id == "seek":
            _apply_seek_path_graph_candidate_policy(candidate)
        candidate["source_before_path_graph"] = candidate.get("source")
        candidate["source"] = "model_observation_resectioned_by_runtime_path_graph"
        results.append(candidate)
    return results


def _apply_seek_path_graph_candidate_policy(candidate: dict[str, Any]) -> None:
    section_id = str(candidate.get("section_id") or "")
    role = str(candidate.get("role") or "").casefold()
    label = str(candidate.get("label") or "")
    if section_id == "results_list" and role in {"news_card", "card", "menu_item", "menu item", ""}:
        candidate["role"] = "job_card"
        candidate["risk_class"] = "safe_click_allowed"
        candidate["expected_effect"] = "open selected SEEK job in job_detail"
    elif section_id in {"job_detail", "detail_header", "detail_body"}:
        if any(term in label.casefold() for term in ("apply", "quick apply")):
            candidate["role"] = "button"
            candidate["risk_class"] = "safe_click_allowed"
            candidate["expected_effect"] = "enter guarded apply flow; final submit remains forbidden"
        else:
            candidate["risk_class"] = candidate.get("risk_class") or "safe_review_only"


def _screen_map_image_size(result: dict[str, Any], *, image_path: str) -> tuple[int, int]:
    image_size = result.get("image_size") if isinstance(result.get("image_size"), dict) else {}
    live_capture = result.get("live_capture") if isinstance(result.get("live_capture"), dict) else {}
    width = int(_number(image_size.get("width") or live_capture.get("image_width")) or 0)
    height = int(_number(image_size.get("height") or live_capture.get("image_height")) or 0)
    if width > 0 and height > 0:
        return width, height
    try:
        with Image.open(image_path) as image:
            return int(image.width), int(image.height)
    except Exception:
        return 1000, 1000


def _learned_graph_region_bboxes(graph: dict[str, Any], *, width: int, height: int) -> dict[str, dict[str, int]]:
    if graph.get("app_id") != "seek":
        return {}
    chrome_h = min(height, max(72, round(height * 0.06)))
    top_h = min(height - chrome_h, max(120, round(height * 0.12)))
    content_y = chrome_h + top_h
    content_h = max(1, height - content_y)
    results_x = round(width * 0.235)
    results_w = round(width * 0.20)
    detail_x = round(width * 0.45)
    detail_w = max(1, width - detail_x - round(width * 0.04))
    return {
        "top_search_area": {"x": 0, "y": chrome_h, "w": width, "h": top_h},
        "results_list": {"x": results_x, "y": content_y, "w": results_w, "h": content_h},
        "job_detail": {"x": detail_x, "y": content_y, "w": detail_w, "h": content_h},
        "job_card": {"x": results_x, "y": content_y, "w": results_w, "h": content_h},
        "detail_header": {"x": detail_x, "y": content_y, "w": detail_w, "h": max(1, round(content_h * 0.30))},
        "detail_body": {"x": detail_x, "y": content_y + round(content_h * 0.30), "w": detail_w, "h": max(1, round(content_h * 0.70))},
    }


def _section_for_path_graph_action(action_id: str, action: dict[str, Any]) -> str:
    if action.get("scroll_container_id") == "seek:job_detail" or action_id in {"read_detail", "apply_entry"}:
        return "job_detail"
    if action.get("scroll_container_id") == "seek:results_list" or action_id in {"open_job_card", "load_more_results"}:
        return "results_list"
    return str(action.get("source_section_id") or action.get("target_section_id") or "main_content")


def _section_bbox(sections: list[dict[str, Any]], section_id: str) -> dict[str, int] | None:
    for section in sections:
        if section.get("section_id") == section_id and isinstance(section.get("bbox"), dict):
            return _normalize_map_bbox(section["bbox"])
    return None


def _bbox_center(bbox: dict[str, Any] | None) -> dict[str, int] | None:
    normalized = _normalize_map_bbox(bbox)
    if not normalized:
        return None
    return {
        "x": int(round(normalized["x"] + normalized["w"] / 2)),
        "y": int(round(normalized["y"] + normalized["h"] / 2)),
    }


def _best_section_id_for_bbox(bbox: dict[str, Any] | None, sections: list[dict[str, Any]]) -> str | None:
    normalized = _normalize_map_bbox(bbox)
    if not normalized:
        return None
    best: tuple[float, str] | None = None
    for section in sections:
        section_bbox = _normalize_map_bbox(section.get("bbox"))
        if not section_bbox:
            continue
        overlap = _bbox_intersection_area(normalized, section_bbox)
        if overlap <= 0:
            continue
        score = overlap / max(1.0, float(normalized["w"] * normalized["h"]))
        section_id = str(section.get("section_id") or "")
        if best is None or score > best[0]:
            best = (score, section_id)
    return best[1] if best and best[0] >= 0.2 else None


def _bbox_intersection_area(a: dict[str, Any], b: dict[str, Any]) -> float:
    ax1, ay1 = float(a["x"]), float(a["y"])
    ax2, ay2 = ax1 + float(a["w"]), ay1 + float(a["h"])
    bx1, by1 = float(b["x"]), float(b["y"])
    bx2, by2 = bx1 + float(b["w"]), by1 + float(b["h"])
    return max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))


def _dedupe_screen_map_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for candidate in candidates:
        label = str(candidate.get("label") or "")
        section_id = str(candidate.get("section_id") or "")
        action_id = str(candidate.get("action_template_id") or "")
        bbox = _normalize_map_bbox(candidate.get("bbox"))
        bbox_key = ""
        if bbox:
            bbox_key = f"{bbox['x']}:{bbox['y']}:{bbox['w']}:{bbox['h']}"
        key = f"{action_id}|{label.casefold()}|{section_id}|{bbox_key}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _inventory_texts(screen_inventory: dict[str, Any] | None) -> list[str]:
    inventory = screen_inventory if isinstance(screen_inventory, dict) else {}
    labels: list[str] = []
    for key in ("available_actions", "page_elements", "cards"):
        for item in inventory.get(key) or []:
            if not isinstance(item, dict):
                continue
            for field in ("label", "text", "title", "name"):
                value = item.get(field)
                if value:
                    labels.append(str(value))
    return labels


def _build_learn_deep_review(
    *,
    result: dict[str, Any],
    screen_map: dict[str, Any],
    request: VisionObserveScreenRequestModel,
) -> dict[str, Any]:
    candidates = [dict(item) for item in _as_list(screen_map.get("candidates")) if isinstance(item, dict)]
    sections = [item for item in _as_list(screen_map.get("sections")) if isinstance(item, dict)]
    kept: list[dict[str, Any]] = []
    removals: list[dict[str, Any]] = []
    candidate_decisions: list[dict[str, Any]] = []

    for candidate in candidates:
        duplicate_of = _deep_duplicate_candidate(candidate, kept)
        if duplicate_of is not None:
            removals.append(
                {
                    "candidate_id": candidate.get("candidate_id"),
                    "label": candidate.get("label"),
                    "reason": "duplicate_candidate_same_label_and_bbox",
                    "duplicate_of": duplicate_of.get("candidate_id"),
                }
            )
            candidate_decisions.append(
                {
                    "candidate_id": candidate.get("candidate_id"),
                    "label": candidate.get("label"),
                    "action": "remove",
                    "reasons": ["duplicate_candidate_same_label_and_bbox"],
                }
            )
            continue
        kept.append(candidate)
        candidate_decisions.append(
            {
                "candidate_id": candidate.get("candidate_id"),
                "label": candidate.get("label"),
                "action": "keep",
                "risk_class": candidate.get("risk_class"),
                "section_id": candidate.get("section_id"),
                "reasons": _deep_candidate_reasons(candidate),
            }
        )

    additions = _deep_missing_text_additions(result=result, candidates=kept, sections=sections)
    for addition in additions:
        candidate_decisions.append(
            {
                "candidate_id": addition.get("candidate_id"),
                "label": addition.get("label"),
                "action": "add",
                "reasons": ["important_ocr_text_missing_from_path_graph"],
            }
        )

    refined_candidates = [*kept, *additions]
    refined_map = dict(screen_map)
    refined_map["candidates"] = refined_candidates
    refined_map["learn_depth"] = "deep"
    refined_map["summary"] = {
        **dict(screen_map.get("summary") if isinstance(screen_map.get("summary"), dict) else {}),
        "candidate_count": len(refined_candidates),
        "safe_candidate_count": len([item for item in refined_candidates if item.get("risk_class") == "safe_click_allowed"]),
        "blocked_candidate_count": len([item for item in refined_candidates if item.get("risk_class") == "blocked"]),
        "deep_addition_count": len(additions),
        "deep_removal_count": len(removals),
    }

    delta = {
        "contract_version": "path_graph_delta_v1",
        "source": "learn_deep_review",
        "state_id": screen_map.get("state_id"),
        "status": "ready",
        "additions": additions,
        "removals": removals,
        "updates": [
            {
                "field": "screen_map.summary",
                "reason": "learn_deep_summary_recomputed",
                "candidate_count": len(refined_candidates),
            }
        ],
        "summary": {
            "addition_count": len(additions),
            "removal_count": len(removals),
            "update_count": 1,
        },
    }
    review = {
        "contract_version": "path_graph_deep_review_v1",
        "status": "ready",
        "state_id": screen_map.get("state_id"),
        "learn_depth": "deep",
        "candidate_decisions": candidate_decisions,
        "summary": {
            "input_candidate_count": len(candidates),
            "output_candidate_count": len(refined_candidates),
            "duplicate_count": len(removals),
            "missing_text_addition_count": len(additions),
            "section_count": len(sections),
        },
    }
    write_policy = request.write_policy.model_dump() if hasattr(request.write_policy, "model_dump") else {}
    deep_result = {
        "screen_map": refined_map,
        "path_graph_deep_review": review,
        "path_graph_delta": delta,
        "element_memory_init_plan": _build_element_memory_init_plan(
            screen_map=refined_map,
            enabled=bool(write_policy.get("element_memory", False)),
        ),
    }
    model_review = _run_learn_deep_model_review(
        result=result,
        screen_map=refined_map,
        deterministic_review=review,
        deterministic_delta=delta,
        request=request,
    )
    deep_result = _apply_learn_deep_model_review(
        deep_result=deep_result,
        model_review=model_review,
        element_memory_enabled=bool(write_policy.get("element_memory", False)),
    )
    return deep_result


def _run_learn_deep_model_review(
    *,
    result: dict[str, Any],
    screen_map: dict[str, Any],
    deterministic_review: dict[str, Any],
    deterministic_delta: dict[str, Any],
    request: VisionObserveScreenRequestModel,
) -> dict[str, Any]:
    options = _learn_deep_model_options(request)
    if options.get("enabled") is False:
        return {
            "contract_version": "learn_deep_model_review_v1",
            "status": "disabled",
            "reason": "disabled_by_metadata",
        }
    image_path = str(screen_map.get("image_path") or result.get("image_path") or "").strip()
    if not image_path:
        return {
            "contract_version": "learn_deep_model_review_v1",
            "status": "skipped",
            "reason": "missing_image_path",
        }
    try:
        config = VisionProviderFactory.load_config()
        provider_mode = str(options.get("provider_mode") or request.provider_mode or "local_grounding")
        provider = VisionProviderFactory.create(mode=provider_mode, config=config)
        provider_response = provider.analyze(
            VisionAnalyzeRequest(
                image_path=image_path,
                task="learn_deep_review",
                app_name=request.app_name,
                goal="Review and refine the whole-screen PathGraph draft without executing actions.",
                state_hint=screen_map.get("state_hint") or result.get("suggested_state_hint") or request.state_hint,
                provider_mode=provider_mode,
                metadata={
                    "max_output_tokens": int(options.get("max_output_tokens") or 2048),
                    "learn_deep_review_context": _learn_deep_model_context(
                        result=result,
                        screen_map=screen_map,
                        deterministic_review=deterministic_review,
                        deterministic_delta=deterministic_delta,
                        max_candidates=int(options.get("max_candidates") or 80),
                        max_texts=int(options.get("max_texts") or 120),
                    ),
                },
            )
        )
        model_json = _extract_provider_model_json(provider_response.raw_response)
        model_json = model_json if isinstance(model_json, dict) else {}
        return {
            "contract_version": "learn_deep_model_review_v1",
            "status": str(model_json.get("status") or "ready"),
            "provider": provider_response.provider,
            "provider_mode": provider_mode,
            "model_name": model_json.get("model_name") or model_json.get("provider") or provider_response.provider,
            "model_io": _model_io_trace(provider_response),
            "screen_summary": model_json.get("screen_summary") or provider_response.screen_summary,
            "state_guess": model_json.get("state_guess") or provider_response.state_guess,
            "candidate_decisions": _as_list(model_json.get("candidate_decisions")),
            "additions": _as_list(model_json.get("additions")),
            "removals": _as_list(model_json.get("removals")),
            "updates": _as_list(model_json.get("updates")),
            "notes": _as_list(model_json.get("notes")) or list(provider_response.notes),
        }
    except Exception as exc:
        model_io = _model_io_failure_payload(exc)
        return {
            "contract_version": "learn_deep_model_review_v1",
            "status": "failed",
            "error": str(exc),
            "provider_mode": str(options.get("provider_mode") or request.provider_mode or "local_grounding"),
            "model_io": model_io,
            "fallback": "deterministic_learn_deep_review",
        }


def _learn_deep_model_options(request: VisionObserveScreenRequestModel) -> dict[str, Any]:
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    raw = metadata.get("learn_deep_model_review")
    if raw is False:
        return {"enabled": False}
    if isinstance(raw, dict):
        return {**raw, "enabled": raw.get("enabled", True) is not False}
    return {"enabled": True}


def _learn_deep_model_context(
    *,
    result: dict[str, Any],
    screen_map: dict[str, Any],
    deterministic_review: dict[str, Any],
    deterministic_delta: dict[str, Any],
    max_candidates: int,
    max_texts: int,
) -> dict[str, Any]:
    return {
        "contract_version": "learn_deep_review_context_v1",
        "state_id": screen_map.get("state_id"),
        "app_name": screen_map.get("app_name"),
        "state_hint": screen_map.get("state_hint"),
        "summary": screen_map.get("summary"),
        "sections": _compact_map_items(screen_map.get("sections"), limit=40),
        "candidates": _compact_map_items(screen_map.get("candidates"), limit=max_candidates),
        "ocr_texts": _compact_map_items(_screen_map_texts(result), limit=max_texts),
        "uia": _compact_uia_for_learn_deep(result),
        "deterministic_review_summary": deterministic_review.get("summary"),
        "deterministic_delta_summary": deterministic_delta.get("summary"),
        "safety": {
            "path_graph_coordinates_are_observation_only": True,
            "execution_requires_pre_click_decision_v1": True,
        },
    }


def _compact_map_items(value: Any, *, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in _as_list(value)[: max(0, int(limit))]:
        if isinstance(item, dict):
            items.append(
                {
                    key: item.get(key)
                    for key in (
                        "id",
                        "candidate_id",
                        "section_id",
                        "label",
                        "text",
                        "role",
                        "type",
                        "risk_class",
                        "expected_effect",
                        "bbox",
                        "click_point",
                        "confidence",
                        "source",
                    )
                    if key in item
                }
            )
    return items


def _compact_uia_for_learn_deep(result: dict[str, Any]) -> dict[str, Any]:
    screen_reading = result.get("screen_reading") if isinstance(result.get("screen_reading"), dict) else {}
    source_layers = screen_reading.get("source_layers") if isinstance(screen_reading.get("source_layers"), dict) else {}
    uia = source_layers.get("windows_uia") if isinstance(source_layers.get("windows_uia"), dict) else {}
    return {
        "status": uia.get("status"),
        "control_count": uia.get("control_count"),
        "available": uia.get("available"),
    }


def _extract_provider_model_json(raw_response: Any) -> dict[str, Any]:
    if not isinstance(raw_response, dict):
        return {}
    model_json = raw_response.get("model_json")
    if isinstance(model_json, dict):
        return model_json
    if raw_response.get("contract_version") == "learn_deep_model_review_v1":
        return raw_response
    nested = raw_response.get("raw_response")
    if isinstance(nested, dict):
        return _extract_provider_model_json(nested)
    return {}


def _apply_learn_deep_model_review(
    *,
    deep_result: dict[str, Any],
    model_review: dict[str, Any],
    element_memory_enabled: bool,
) -> dict[str, Any]:
    review = dict(deep_result.get("path_graph_deep_review") or {})
    delta = dict(deep_result.get("path_graph_delta") or {})
    screen_map = dict(deep_result.get("screen_map") or {})
    candidates = [dict(item) for item in _as_list(screen_map.get("candidates")) if isinstance(item, dict)]
    model_status = str(model_review.get("status") or "")
    review["model_review"] = model_review
    if model_status != "ready":
        deep_result["path_graph_deep_review"] = review
        return deep_result

    existing_by_id = {str(item.get("candidate_id")): item for item in candidates if item.get("candidate_id")}
    remove_ids: set[str] = set()
    model_decisions: list[dict[str, Any]] = []
    additions: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []

    review_items = [item for item in _as_list(model_review.get("candidate_decisions")) if isinstance(item, dict)]
    review_items.extend({"action": "remove", **item} for item in _as_list(model_review.get("removals")) if isinstance(item, dict))
    review_items.extend({"action": "add", "candidate": item} for item in _as_list(model_review.get("additions")) if isinstance(item, dict))
    review_items.extend({"action": "update", **item} for item in _as_list(model_review.get("updates")) if isinstance(item, dict))

    for index, item in enumerate(review_items):
        action = str(item.get("action") or "").strip().lower()
        candidate_id = str(item.get("candidate_id") or "").strip()
        reasons = [str(reason) for reason in _as_list(item.get("reasons")) if str(reason).strip()]
        if action == "remove" and candidate_id in existing_by_id and reasons:
            remove_ids.add(candidate_id)
            model_decisions.append(
                {
                    "candidate_id": candidate_id,
                    "label": item.get("label") or existing_by_id[candidate_id].get("label"),
                    "action": "remove",
                    "source": "learn_deep_model_review",
                    "reasons": reasons,
                }
            )
        elif action == "add":
            candidate = _normalize_learn_deep_model_candidate(
                item.get("candidate") if isinstance(item.get("candidate"), dict) else item,
                index=index,
                screen_map=screen_map,
            )
            if candidate and not _deep_duplicate_candidate(candidate, candidates + additions):
                additions.append(candidate)
                model_decisions.append(
                    {
                        "candidate_id": candidate.get("candidate_id"),
                        "label": candidate.get("label"),
                        "action": "add",
                        "source": "learn_deep_model_review",
                        "reasons": reasons or ["model_identified_missing_candidate"],
                    }
                )
        elif action == "update" and candidate_id in existing_by_id:
            update = _normalize_learn_deep_model_update(item, existing_by_id[candidate_id])
            if update:
                updates.append(update)
                existing_by_id[candidate_id].update(update["fields"])
                model_decisions.append(
                    {
                        "candidate_id": candidate_id,
                        "label": existing_by_id[candidate_id].get("label"),
                        "action": "update",
                        "source": "learn_deep_model_review",
                        "reasons": reasons or ["model_refined_candidate_semantics"],
                        "fields": sorted(update["fields"].keys()),
                    }
                )
        elif action == "keep" and candidate_id in existing_by_id:
            model_decisions.append(
                {
                    "candidate_id": candidate_id,
                    "label": item.get("label") or existing_by_id[candidate_id].get("label"),
                    "action": "keep",
                    "source": "learn_deep_model_review",
                    "reasons": reasons or ["model_kept_candidate"],
                }
            )

    refined_candidates = [item for item in candidates if str(item.get("candidate_id") or "") not in remove_ids]
    refined_candidates.extend(additions)
    screen_map["candidates"] = refined_candidates
    screen_map["summary"] = {
        **dict(screen_map.get("summary") if isinstance(screen_map.get("summary"), dict) else {}),
        "candidate_count": len(refined_candidates),
        "safe_candidate_count": len([item for item in refined_candidates if item.get("risk_class") == "safe_click_allowed"]),
        "blocked_candidate_count": len([item for item in refined_candidates if item.get("risk_class") == "blocked"]),
        "model_addition_count": len(additions),
        "model_removal_count": len(remove_ids),
        "model_update_count": len(updates),
    }

    delta_removals = [item for item in _as_list(delta.get("removals")) if isinstance(item, dict)]
    for candidate_id in sorted(remove_ids):
        delta_removals.append(
            {
                "candidate_id": candidate_id,
                "label": existing_by_id.get(candidate_id, {}).get("label"),
                "reason": "model_review_remove",
                "source": "learn_deep_model_review",
            }
        )
    delta["additions"] = [*([item for item in _as_list(delta.get("additions")) if isinstance(item, dict)]), *additions]
    delta["removals"] = delta_removals
    delta["updates"] = [*([item for item in _as_list(delta.get("updates")) if isinstance(item, dict)]), *updates]
    delta["summary"] = {
        "addition_count": len(delta["additions"]),
        "removal_count": len(delta["removals"]),
        "update_count": len(delta["updates"]),
    }

    review["candidate_decisions"] = [*([item for item in _as_list(review.get("candidate_decisions")) if isinstance(item, dict)]), *model_decisions]
    review["summary"] = {
        **dict(review.get("summary") if isinstance(review.get("summary"), dict) else {}),
        "output_candidate_count": len(refined_candidates),
        "model_decision_count": len(model_decisions),
        "model_addition_count": len(additions),
        "model_removal_count": len(remove_ids),
        "model_update_count": len(updates),
    }

    deep_result["screen_map"] = screen_map
    deep_result["path_graph_deep_review"] = review
    deep_result["path_graph_delta"] = delta
    deep_result["element_memory_init_plan"] = _build_element_memory_init_plan(
        screen_map=screen_map,
        enabled=element_memory_enabled,
    )
    return deep_result


def _normalize_learn_deep_model_candidate(raw: Any, *, index: int, screen_map: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    label = _first_compact_text(raw.get("label"), raw.get("text"), raw.get("name"))
    bbox = _normalize_map_bbox(raw.get("bbox") or raw.get("diagonal"))
    if not label or not bbox:
        return None
    candidate_id = str(raw.get("candidate_id") or raw.get("id") or f"learn_deep_model_{index}").strip()
    role = _first_compact_text(raw.get("role"), raw.get("type")) or "model_candidate"
    risk_class = str(raw.get("risk_class") or "safe_dry_run_only").strip()
    if risk_class not in {"safe_click_allowed", "safe_dry_run_only", "requires_user_confirmation", "blocked"}:
        risk_class = "safe_dry_run_only"
    return {
        "contract_version": "screen_map_candidate_v1",
        "candidate_id": candidate_id,
        "label": label,
        "role": role,
        "goal_hint": _first_compact_text(raw.get("goal_hint")) or _goal_hint_for_candidate(label=label, role=role),
        "expected_effect": _first_compact_text(raw.get("expected_effect"), raw.get("description")) or "click may change the current interface",
        "risk_class": risk_class,
        "risk_reasons": [str(item) for item in _as_list(raw.get("risk_reasons") or raw.get("reasons")) if str(item).strip()],
        "section_id": raw.get("section_id") or _section_id_for_bbox(bbox, _as_list(screen_map.get("sections"))),
        "bbox": bbox,
        "click_point": _normalize_map_point(raw.get("click_point"), bbox),
        "confidence": _bounded_float(raw.get("confidence")) or 0.55,
        "source": "learn_deep_model_review",
        "screen_map_rule": "learn_deep_model_added",
        "evidence": {
            "model_review": {
                "reason": _first_compact_text(raw.get("reason"), raw.get("description")),
                "coordinates_are_observation_only": True,
            }
        },
    }


def _normalize_learn_deep_model_update(raw: dict[str, Any], existing: dict[str, Any]) -> dict[str, Any] | None:
    fields: dict[str, Any] = {}
    for key in ("label", "role", "section_id", "expected_effect", "risk_class", "description"):
        value = raw.get(key)
        if value is not None and str(value).strip() and value != existing.get(key):
            fields[key] = str(value).strip()
    bbox = _normalize_map_bbox(raw.get("bbox") or raw.get("bounding_box") or raw.get("bounds"))
    if bbox and bbox != _normalize_map_bbox(existing.get("bbox")):
        fields["bbox"] = bbox
    point = _normalize_map_point(raw.get("click_point") or raw.get("clickPoint"), bbox or _normalize_map_bbox(existing.get("bbox")))
    if point and point != _normalize_map_point(existing.get("click_point") or existing.get("clickPoint"), _normalize_map_bbox(existing.get("bbox"))):
        fields["click_point"] = point
    confidence = _bounded_float(raw.get("confidence"))
    if confidence is not None and confidence != existing.get("confidence"):
        fields["confidence"] = confidence
    if not fields:
        return None
    return {
        "candidate_id": existing.get("candidate_id"),
        "source": "learn_deep_model_review",
        "fields": fields,
    }


def _deep_duplicate_candidate(candidate: dict[str, Any], kept: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidate_label = _path_label_key(candidate.get("label"))
    candidate_bbox = _normalize_map_bbox(candidate.get("bbox"))
    if not candidate_label or not candidate_bbox:
        return None
    for existing in kept:
        existing_label = _path_label_key(existing.get("label"))
        existing_bbox = _normalize_map_bbox(existing.get("bbox"))
        if not existing_label or not existing_bbox:
            continue
        if _path_label_similarity(candidate_label, existing_label) >= 0.92 and _path_bbox_similarity(candidate_bbox, existing_bbox) >= 0.82:
            return existing
    return None


def _path_candidate_contains(parent: dict[str, Any], child: dict[str, Any], *, tolerance: int = 3) -> bool:
    parent_bbox = _normalize_map_bbox(parent.get("bbox"))
    child_bbox = _normalize_map_bbox(child.get("bbox"))
    if not parent_bbox or not child_bbox:
        return False
    return (
        parent_bbox["x"] - tolerance <= child_bbox["x"]
        and parent_bbox["y"] - tolerance <= child_bbox["y"]
        and parent_bbox["x"] + parent_bbox["w"] + tolerance >= child_bbox["x"] + child_bbox["w"]
        and parent_bbox["y"] + parent_bbox["h"] + tolerance >= child_bbox["y"] + child_bbox["h"]
    )


def _path_candidate_overlap_conflict(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_bbox = _normalize_map_bbox(left.get("bbox"))
    right_bbox = _normalize_map_bbox(right.get("bbox"))
    if not left_bbox or not right_bbox:
        return False
    if _path_candidate_contains(left, right) or _path_candidate_contains(right, left):
        return False
    left_section = str(left.get("section_id") or "").strip()
    right_section = str(right.get("section_id") or "").strip()
    if left_section and right_section and left_section != right_section:
        return False
    overlap = _bbox_overlap_area(left_bbox, right_bbox)
    if overlap <= 16:
        return False
    smaller = min(left_bbox["w"] * left_bbox["h"], right_bbox["w"] * right_bbox["h"])
    return smaller > 0 and overlap / smaller >= 0.15


def _path_candidate_overlap_priority(candidate: dict[str, Any]) -> tuple[float, float, float]:
    role = str(candidate.get("role") or "").casefold()
    role_priority = {
        "text_input": 90.0,
        "input": 90.0,
        "button": 82.0,
        "icon_button": 80.0,
        "text_action": 78.0,
        "nav_text_action": 75.0,
        "menu_item": 72.0,
        "recommendation_item": 64.0,
        "news_card": 62.0,
    }.get(role, 55.0)
    confidence = float(_bounded_float(candidate.get("confidence")) or 0.0)
    bbox = _normalize_map_bbox(candidate.get("bbox"))
    area = float(bbox["w"] * bbox["h"]) if bbox else 0.0
    return (role_priority, confidence, -area)


def _path_overlap_decision(
    *,
    removed: dict[str, Any],
    kept_candidate: dict[str, Any],
    reason: str,
    source: str,
) -> dict[str, Any]:
    return {
        "candidate_id": removed.get("candidate_id") or removed.get("id"),
        "label": removed.get("label"),
        "bbox": removed.get("bbox"),
        "section_id": removed.get("section_id"),
        "reason": reason,
        "source": source,
        "kept_candidate_id": kept_candidate.get("candidate_id") or kept_candidate.get("id"),
        "kept_label": kept_candidate.get("label"),
    }


def _prune_non_containment_overlaps(candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    removals: list[dict[str, Any]] = []
    for candidate in candidates:
        conflict_index = next(
            (index for index, existing in enumerate(kept) if _path_candidate_overlap_conflict(candidate, existing)),
            None,
        )
        if conflict_index is None:
            kept.append(candidate)
            continue
        existing = kept[conflict_index]
        if _path_candidate_overlap_priority(candidate) > _path_candidate_overlap_priority(existing):
            kept[conflict_index] = candidate
            removed = existing
            kept_candidate = candidate
        else:
            removed = candidate
            kept_candidate = existing
        removals.append(
            _path_overlap_decision(
                removed=removed,
                kept_candidate=kept_candidate,
                reason="non_containment_overlap_removed",
                source="path_graph_overlap_rule",
            )
        )
    return kept, removals


def _learn_target_visual_priority(target: dict[str, Any]) -> tuple[float, float, float]:
    role = str(target.get("role") or "").casefold()
    role_priority = {
        "text_input": 94.0,
        "input": 94.0,
        "button": 90.0,
        "icon_button": 88.0,
        "text_action": 86.0,
        "nav_text_action": 84.0,
        "menu_item": 82.0,
        "recommendation_item": 66.0,
        "news_card": 62.0,
        "card": 60.0,
        "group": 48.0,
        "section": 42.0,
    }.get(role, 55.0)
    confidence = float(_bounded_float(target.get("confidence")) or 0.0)
    bbox = _normalize_map_bbox(target.get("bbox"))
    area = float(bbox["w"] * bbox["h"]) if bbox else 0.0
    return (role_priority, confidence, -area)


def _learn_target_visual_conflict(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_bbox = _normalize_map_bbox(left.get("bbox"))
    right_bbox = _normalize_map_bbox(right.get("bbox"))
    if not left_bbox or not right_bbox:
        return False
    left_section = str(left.get("section_id") or "").strip()
    right_section = str(right.get("section_id") or "").strip()
    if left_section and right_section and left_section != right_section:
        return False
    if _path_candidate_contains(left, right) or _path_candidate_contains(right, left):
        return True
    overlap = _bbox_overlap_area(left_bbox, right_bbox)
    if overlap <= 16:
        return False
    smaller = min(left_bbox["w"] * left_bbox["h"], right_bbox["w"] * right_bbox["h"])
    return smaller > 0 and overlap / smaller >= 0.15


def _learn_target_visual_removal_reason(removed: dict[str, Any], kept_candidate: dict[str, Any]) -> str:
    if _path_candidate_contains(removed, kept_candidate):
        return "contained_visual_parent_removed"
    if _path_candidate_contains(kept_candidate, removed):
        return "contained_visual_child_removed"
    return "visual_overlap_removed"


def _prune_learn_target_visual_overlaps(targets: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    removals: list[dict[str, Any]] = []
    for target in targets:
        conflict_index = next(
            (index for index, existing in enumerate(kept) if _learn_target_visual_conflict(target, existing)),
            None,
        )
        if conflict_index is None:
            kept.append(target)
            continue
        existing = kept[conflict_index]
        if _learn_target_visual_priority(target) > _learn_target_visual_priority(existing):
            kept[conflict_index] = target
            removed = existing
            kept_candidate = target
        else:
            removed = target
            kept_candidate = existing
        removals.append(
            _path_overlap_decision(
                removed=removed,
                kept_candidate=kept_candidate,
                reason=_learn_target_visual_removal_reason(removed, kept_candidate),
                source="learn_target_visual_overlap_rule",
            )
        )
    return kept, removals


def _deep_candidate_reasons(candidate: dict[str, Any]) -> list[str]:
    reasons = ["candidate_retained"]
    if candidate.get("source") in {"ocr_card_groups", "ocr_text_actions", "nav_text_action"}:
        reasons.append("ocr_backed_candidate")
    if candidate.get("section_id"):
        reasons.append("section_assigned")
    if candidate.get("risk_class") == "safe_click_allowed":
        reasons.append("safe_click_candidate")
    return reasons


def _deep_missing_text_additions(
    *,
    result: dict[str, Any],
    candidates: list[dict[str, Any]],
    sections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    additions: list[dict[str, Any]] = []
    existing_labels = {_path_label_key(item.get("label")) for item in candidates}
    existing_boxes = [_normalize_map_bbox(item.get("bbox")) for item in candidates]
    for index, text_item in enumerate(_screen_map_texts(result)):
        text = _normalize_ocr_candidate_label(_first_compact_text(text_item.get("text")))
        if not text or _screen_map_text_is_noise(text, allow_short=False):
            continue
        text_key = _path_label_key(text)
        bbox = _normalize_map_bbox(text_item.get("bbox"))
        if not text_key or not bbox:
            continue
        if any(_path_label_similarity(text_key, existing) >= 0.92 for existing in existing_labels if existing):
            continue
        if any(box and _bbox_contains_center(box, bbox) for box in existing_boxes):
            continue
        section_id = _section_id_for_bbox(bbox, sections)
        addition = {
            "contract_version": "screen_map_candidate_v1",
            "candidate_id": f"learn_deep_text_{index}",
            "label": text,
            "role": "ocr_text_action",
            "goal_hint": _goal_hint_for_candidate(label=text, role="ocr_text_action"),
            "expected_effect": "click may change the current interface",
            "risk_class": "safe_dry_run_only",
            "risk_reasons": ["learn_deep_missing_text_requires_locate"],
            "section_id": section_id,
            "bbox": bbox,
            "click_point": _normalize_map_point(None, bbox),
            "confidence": _bounded_float(text_item.get("confidence") or text_item.get("score")) or 0.5,
            "source": "learn_deep_missing_ocr_text",
            "source_id": text_item.get("id") or text_item.get("text_id"),
            "screen_map_rule": "learn_deep_missing_text_added",
            "evidence": {
                "source_text": text_item,
                "screen_map_rule": "learn_deep_missing_text_added",
            },
        }
        additions.append(addition)
        existing_labels.add(text_key)
        existing_boxes.append(bbox)
    return additions[:20]


def _bbox_contains_center(container: dict[str, int], inner: dict[str, int]) -> bool:
    cx = inner["x"] + inner["w"] / 2
    cy = inner["y"] + inner["h"] / 2
    return container["x"] <= cx <= container["x"] + container["w"] and container["y"] <= cy <= container["y"] + container["h"]


def _build_element_memory_init_plan(*, screen_map: dict[str, Any], enabled: bool) -> dict[str, Any]:
    candidates = [item for item in _as_list(screen_map.get("candidates")) if isinstance(item, dict)]
    entries = [
        {
            "candidate_id": item.get("candidate_id"),
            "memory_key": f"{screen_map.get('state_id')}::{item.get('candidate_id')}",
            "label": item.get("label"),
            "role": item.get("role"),
            "section_id": item.get("section_id"),
            "risk_class": item.get("risk_class"),
            "write_status": "planned_not_written",
        }
        for item in candidates
        if item.get("candidate_id") and item.get("label")
    ]
    return {
        "contract_version": "element_memory_init_plan_v1",
        "status": "planned" if enabled else "disabled_by_write_policy",
        "write_policy_element_memory": bool(enabled),
        "state_id": screen_map.get("state_id"),
        "entry_count": len(entries) if enabled else 0,
        "entries": entries if enabled else [],
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

    if not _screen_map_looks_like_browser_page(result):
        return _application_screen_map_sections(result, width=width, height=height)

    browser_chrome_bottom = min(height, max(80, round(height * 0.085)))
    page_header_bottom = min(height, max(browser_chrome_bottom + 70, round(height * 0.17)))
    promo_bottom = min(height, max(page_header_bottom + 90, round(height * 0.30)))
    main_bottom = min(height, max(promo_bottom + 260, round(height * 0.86)))

    has_right_sidebar = _screen_map_has_right_sidebar_evidence(result, width=width, height=height, top_y=promo_bottom, bottom_y=main_bottom)
    right_sidebar_x = round(width * 0.58) if has_right_sidebar else width

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
            {"x": 0, "y": promo_bottom, "w": right_sidebar_x, "h": max(1, main_bottom - promo_bottom)},
            result,
        ),
    ]
    if has_right_sidebar:
        sections.append(
            _screen_map_section(
                "right_sidebar",
                "Right sidebar",
                "content",
                "Secondary column with recommendations, related items, widgets, or quick actions.",
                {"x": right_sidebar_x, "y": promo_bottom, "w": max(1, width - right_sidebar_x), "h": max(1, main_bottom - promo_bottom)},
                result,
            )
        )
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


def _screen_map_looks_like_browser_page(result: dict[str, Any]) -> bool:
    screen_reading = result.get("screen_reading") if isinstance(result.get("screen_reading"), dict) else {}
    live_capture = result.get("live_capture") if isinstance(result.get("live_capture"), dict) else {}
    haystack = " ".join(
        str(item or "")
        for item in (
            result.get("app_name"),
            screen_reading.get("app_name"),
            result.get("suggested_state_hint"),
            result.get("state_guess"),
            result.get("screen_summary"),
            live_capture.get("process_name"),
            live_capture.get("window_title"),
            live_capture.get("title"),
        )
    ).casefold()
    browser_tokens = (
        "browser",
        "chrome",
        "edge",
        "msedge",
        "firefox",
        "brave",
        "google news",
        "news homepage",
        "web page",
        "website",
        "http://",
        "https://",
        "www.",
    )
    if any(token in haystack for token in browser_tokens):
        return True
    text_blob = " ".join(str(item.get("text") or "") for item in _screen_map_texts(result) if isinstance(item, dict)).casefold()
    web_text_hits = sum(1 for token in ("home", "for you", "following", "search", "sign in", "settings") if token in text_blob)
    return web_text_hits >= 4


def _screen_map_has_right_sidebar_evidence(result: dict[str, Any], *, width: int, height: int, top_y: int, bottom_y: int) -> bool:
    if width < 900:
        return False
    right_x = round(width * 0.58)
    right_texts: list[str] = []
    left_texts = 0
    for item in _screen_map_texts(result):
        if not isinstance(item, dict):
            continue
        bbox = _normalize_map_bbox(item.get("bbox"))
        if not bbox:
            continue
        center_x = bbox["x"] + bbox["w"] / 2
        center_y = bbox["y"] + bbox["h"] / 2
        if center_y < top_y or center_y > bottom_y:
            continue
        text = str(item.get("text") or "").strip()
        if center_x >= right_x:
            if text:
                right_texts.append(text)
        else:
            left_texts += 1
    if len(right_texts) < 3 or left_texts < 2:
        return False
    right_blob = " ".join(right_texts).casefold()
    sidebar_tokens = (
        "recommended",
        "recommendation",
        "related",
        "for you",
        "headlines",
        "perspectives",
        "weather",
        "business",
        "technology",
        "entertainment",
        "sports",
        "world",
        "local",
    )
    if any(token in right_blob for token in sidebar_tokens):
        return True
    return len(right_texts) >= 5


def _application_screen_map_sections(result: dict[str, Any], *, width: int, height: int) -> list[dict[str, Any]]:
    top_bar_bottom = _application_top_bar_bottom(result, width=width, height=height)
    bottom_bar_top = _application_bottom_bar_top(result, height=height)
    content_bottom = bottom_bar_top if bottom_bar_top is not None else height
    sections = [
        _screen_map_section(
            "top_bar",
            "Top bar",
            "navigation",
            "Application top bar with primary tabs, search, account, and window-level actions.",
            {"x": 0, "y": 0, "w": width, "h": top_bar_bottom},
            result,
        ),
        _screen_map_section(
            "primary_area",
            "Primary area",
            "content",
            "Primary application workspace with panels, controls, cards, and action areas.",
            {"x": 0, "y": top_bar_bottom, "w": width, "h": max(1, content_bottom - top_bar_bottom)},
            result,
        ),
    ]
    if bottom_bar_top is not None:
        sections.append(
            _screen_map_section(
                "bottom_bar",
                "Bottom bar",
                "status",
                "Lower application area with secondary actions, status, or footer controls.",
                {"x": 0, "y": content_bottom, "w": width, "h": max(1, height - content_bottom)},
                result,
            )
        )
    floating = _floating_overlay_section(result, width=width, height=height)
    if floating:
        sections.append(floating)
    return sections


def _application_top_bar_bottom(result: dict[str, Any], *, width: int, height: int) -> int:
    top_limit = max(80, round(height * 0.24))
    evidence_boxes: list[dict[str, int]] = []
    element_sources = [_as_list(result.get("ui_elements"))]
    screen_reading = result.get("screen_reading") if isinstance(result.get("screen_reading"), dict) else {}
    element_sources.append(_as_list(screen_reading.get("ui_elements")))
    screen_reading_ui = screen_reading.get("ui") if isinstance(screen_reading.get("ui"), dict) else {}
    element_sources.append(_as_list(screen_reading_ui.get("elements")))
    for source in element_sources:
        for item in source:
            if not isinstance(item, dict):
                continue
            bbox = _normalize_map_bbox(item.get("bbox"))
            if not bbox or bbox["y"] >= top_limit:
                continue
            role = " ".join(str(item.get(key) or "") for key in ("type", "role", "role_guess")).casefold()
            if not any(token in role for token in ("menu", "tab", "nav", "button", "input", "search", "control")):
                continue
            # 左侧窄轨道上的纵向图标属于侧栏，不能把上栏向下拉长。
            narrow_left_icon = (
                "menu" not in role
                and bbox["x"] + bbox["w"] <= max(72, round(width * 0.12))
                and bbox["y"] >= max(56, round(height * 0.06))
            )
            if not narrow_left_icon:
                evidence_boxes.append(bbox)
    text_limit = min(top_limit, max(128, round(height * 0.12)))
    for item in _screen_map_texts(result):
        if not isinstance(item, dict):
            continue
        bbox = _normalize_map_bbox(item.get("bbox"))
        if bbox and bbox["y"] < text_limit:
            evidence_boxes.append(bbox)
    if evidence_boxes:
        evidence_bottom = max(box["y"] + box["h"] for box in evidence_boxes)
        return min(height, max(56, evidence_bottom + 8))
    return min(height, max(72, round(height * 0.10)))


def _application_bottom_bar_top(result: dict[str, Any], *, height: int) -> int | None:
    model_io = result.get("model_io") if isinstance(result.get("model_io"), dict) else {}
    raw_response = model_io.get("raw_response") if isinstance(model_io.get("raw_response"), dict) else {}
    model_json = raw_response.get("model_json") if isinstance(raw_response.get("model_json"), dict) else {}
    candidates: list[int] = []
    for item in _as_list(model_json.get("regions")):
        if not isinstance(item, dict):
            continue
        role = " ".join(str(item.get(key) or "") for key in ("role", "label", "region_id")).casefold()
        if not any(token in role for token in ("status_bar", "status bar", "bottom_bar", "bottom bar", "footer")):
            continue
        diagonal = item.get("diagonal") if isinstance(item.get("diagonal"), dict) else {}
        top = int(_number(diagonal.get("y1")) or 0)
        if top >= round(height * 0.70):
            candidates.append(top)
    return min(candidates) if candidates else None


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
        min_confidence = 0.5 if section_id in {"page_header", "top_bar"} else (0.6 if len(label) <= 4 else 0.72)
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
                    "allowed": True if role in {"button", "text_action", "nav_text_action"} else None,
                    "reasons": ["ocr_text_candidate"],
                },
                "verification_hints": {"expected_changes": [_expected_effect_for_ocr_text(label, role)]},
                "evidence_level": "ocr_text_only",
                "screen_map_rule": (
                    "more_text_is_button"
                    if _looks_like_more_button_text(label)
                    else ("header_text_is_button" if section_id in {"page_header", "top_bar"} else "ocr_action_text")
                ),
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
    if section_id == "top_bar":
        if _screen_map_text_is_noise(text, allow_short=True):
            return None
        if len(text) <= 1:
            return None
        if sum(1 for char in text if char.isalnum()) <= 1 and len(text) <= 3:
            return None
        digit_count = sum(1 for char in text if char.isdigit())
        alpha_count = sum(1 for char in text if char.isalpha())
        if digit_count and digit_count >= max(1, alpha_count):
            return None
        return "nav_text_action"
    if bbox["y"] < 90:
        return None
    if section_id == "page_header":
        if _screen_map_text_is_noise(text, allow_short=True):
            return None
        if _header_ocr_text_is_noise(text, bbox):
            return None
        return "nav_text_action"
    if bbox["y"] < 180 and ("." in text or "mousetester" in lowered):
        return None
    if _looks_like_more_button_text(text):
        return "button"
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
        "启动",
        "停止",
        "测试",
        "重置",
        "左键",
        "中键",
        "右键",
        "前进",
        "后退",
        "加入",
        "参与",
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


def _header_ocr_text_is_noise(text: str, bbox: dict[str, int]) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    lowered = value.casefold()
    known_short_nav = {"home", "world", "local", "sports", "health", "science", "for you", "中国", "全球"}
    if lowered in known_short_nav or value in known_short_nav:
        return False
    alnum_count = sum(1 for char in value if char.isalnum())
    alpha_count = sum(1 for char in value if char.isalpha())
    digit_count = sum(1 for char in value if char.isdigit())
    # Top toolbar OCR often turns icons, avatars, extension badges, and the search icon into tiny text.
    if bbox.get("y", 0) < 130:
        if len(value) <= 3:
            return True
        if digit_count and digit_count >= alpha_count:
            return True
    if len(value) <= 2 and value not in known_short_nav:
        return True
    if alnum_count <= 1 and len(value) <= 3:
        return True
    if digit_count and digit_count >= max(1, alpha_count):
        return True
    return False


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
    for section_id in ("main_content", "right_sidebar", "promo_strip", "lower_content", "primary_area", "bottom_bar"):
        section = section_by_id.get(section_id)
        section_bbox = _normalize_map_bbox((section or {}).get("bbox"))
        if not section_bbox:
            continue
        section_texts = _texts_in_bbox(text_items, section_bbox)
        seed_boxes = [
            bbox
            for item in section_texts
            if (bbox := _normalize_map_bbox(item.get("bbox")))
            and _is_card_seed_label(
                _normalize_ocr_candidate_label(_first_compact_text(item.get("text"))),
                section_id=section_id,
                bbox=bbox,
            )
        ]
        used_centers: list[dict[str, int]] = []
        for index, text_item in enumerate(section_texts):
            seed_bbox = _normalize_map_bbox(text_item.get("bbox"))
            label = _normalize_ocr_candidate_label(_first_compact_text(text_item.get("text")))
            if not seed_bbox or not _is_card_seed_label(label, section_id=section_id, bbox=seed_bbox):
                continue
            seed_center = _normalize_map_point(None, seed_bbox)
            if seed_center and any(_point_inside_bbox(seed_center, used) for used in used_centers):
                continue
            card_bbox = _card_bbox_for_seed(section_texts, seed_bbox=seed_bbox, seed_boxes=seed_boxes, section_bbox=section_bbox)
            if not card_bbox:
                continue
            used_centers.append(card_bbox)
            card_texts = _texts_in_bbox(section_texts, card_bbox)
            card_role = (
                "recommendation_item"
                if section_id == "right_sidebar"
                else ("news_card" if section_id == "main_content" else _card_role_for_bbox(card_bbox, section_bbox=section_bbox))
            )
            candidates.append(
                {
                    "id": f"card_{section_id}_{index}",
                    "label": label,
                    "type": card_role,
                    "section_id": section_id,
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
                    "children": _card_children_from_texts(card_texts, seed_text_id=text_item.get("id")),
                }
            )
    return candidates


def _is_card_seed_label(label: str, *, section_id: str, bbox: dict[str, int] | None = None) -> bool:
    text = str(label or "").strip()
    if _screen_map_text_is_noise(text):
        return False
    if _looks_like_more_button_text(text):
        return False
    lowered = text.casefold()
    if _is_generic_article_seed_label(text, bbox=bbox, section_id=section_id):
        return True
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


def _is_generic_article_seed_label(label: str, *, bbox: dict[str, int] | None, section_id: str) -> bool:
    text = str(label or "").strip()
    if section_id in {"page_header", "top_bar"} or _screen_map_text_is_noise(text):
        return False
    if _looks_like_more_button_text(text):
        return False
    lowered = text.casefold()
    if any(token in lowered for token in ["http", "google", "search", "setting", "privacy", "cookie"]):
        return False
    if _looks_like_metadata_text(text):
        return False
    alpha_count = sum(1 for char in text if char.isalpha())
    digit_count = sum(1 for char in text if char.isdigit())
    non_ascii_count = sum(1 for char in text if ord(char) > 127)
    word_count = len([part for part in text.replace("-", " ").split() if part.strip()])
    width = int((bbox or {}).get("w") or 0)
    if digit_count and digit_count >= max(2, alpha_count):
        return False
    if len(text) >= 10 and (non_ascii_count >= 4 or word_count >= 4):
        return True
    if width >= 140 and len(text) >= 8 and (non_ascii_count >= 3 or word_count >= 3):
        return True
    return False


def _looks_like_more_button_text(label: str) -> bool:
    text = str(label or "").strip()
    if not text:
        return False
    lowered = text.casefold()
    compact = "".join(char for char in lowered if char.isalnum() or ord(char) > 127)
    if any(token in text for token in ["查看更多", "更多", "显示更多", "加载更多"]):
        return True
    more_phrases = [
        "more",
        "see more",
        "view more",
        "read more",
        "show more",
        "load more",
        "more stories",
        "more news",
        "more headlines",
    ]
    if any(phrase in lowered for phrase in more_phrases):
        return True
    return compact in {"more", "seemore", "viewmore", "readmore", "showmore", "loadmore"}


def _looks_like_metadata_text(label: str) -> bool:
    text = str(label or "").strip()
    lowered = text.casefold()
    if not text:
        return True
    if any(char.isdigit() for char in text):
        time_markers = [
            "ago",
            "hour",
            "hours",
            "minute",
            "minutes",
            "day",
            "days",
            "\u5c0f\u65f6",
            "\u5c0f\u6642",
            "\u5206\u949f",
            "\u5206\u9418",
            "\u524d",
            "\u00b7",
            "\u00c2\u00b7",
            "\u00e5\u00b0\u008f\u00e6\u0097\u00b6",
        ]
        if any(token in lowered for token in time_markers):
            return True
    metadata_tokens = [
        "ago",
        "hour",
        "hours",
        "minute",
        "minutes",
        "today",
        "yesterday",
        "source",
        "author",
        "å°æ¶",
        "åé",
        "å¤©å",
        "ä½è€",
    ]
    if any(token in lowered for token in metadata_tokens):
        return True
    if len(text) <= 14 and any(char.isdigit() for char in text) and not any(char in text for char in "!?？！“”\""):
        return True
    if len(text) <= 12 and sum(1 for char in text if char.isalpha()) <= 2 and any(ord(char) > 127 for char in text):
        return True
    return False


def _card_role_for_bbox(card_bbox: dict[str, int], *, section_bbox: dict[str, int]) -> str:
    center_x = card_bbox["x"] + card_bbox["w"] / 2
    right_threshold = section_bbox["x"] + section_bbox["w"] * 0.58
    if center_x >= right_threshold and card_bbox["w"] <= max(360, section_bbox["w"] * 0.34):
        return "recommendation_item"
    return "news_card"


def _card_children_from_texts(texts: list[dict[str, Any]], *, seed_text_id: Any) -> list[dict[str, Any]]:
    children: list[dict[str, Any]] = []
    for index, text_item in enumerate(texts[:12]):
        label = _normalize_ocr_candidate_label(_first_compact_text(text_item.get("text")))
        bbox = _normalize_map_bbox(text_item.get("bbox"))
        if not label or not bbox or _screen_map_text_is_noise(label, allow_short=False):
            continue
        role = "title" if text_item.get("id") == seed_text_id else ("metadata" if _looks_like_metadata_text(label) else "text")
        children.append(
            {
                "contract_version": "screen_map_child_v1",
                "child_id": str(text_item.get("id") or f"text_{index}")[:100],
                "role": role,
                "label": label,
                "bbox": bbox,
                "click_point": _normalize_map_point(None, bbox),
                "confidence": _bounded_float(text_item.get("confidence")),
                "source": "ocr_text",
            }
        )
    return children


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
    candidate_rows: list[dict[str, Any]] = []
    for text_item in texts:
        bbox = _normalize_map_bbox(text_item.get("bbox"))
        if not bbox:
            continue
        cx = bbox["x"] + bbox["w"] / 2
        cy = bbox["y"] + bbox["h"] / 2
        if x1 <= cx <= x2 and y1 <= cy <= y2:
            candidate_rows.append({"bbox": bbox, "cy": cy})
    candidate_rows.sort(key=lambda item: (item["cy"], item["bbox"]["x"]))
    seed_cy = seed_bbox["y"] + seed_bbox["h"] / 2
    seed_index = next(
        (
            index
            for index, item in enumerate(candidate_rows)
            if _bbox_overlap_area(item["bbox"], seed_bbox) > 0
        ),
        None,
    )
    if seed_index is None:
        candidate_rows.append({"bbox": seed_bbox, "cy": seed_cy})
        candidate_rows.sort(key=lambda item: (item["cy"], item["bbox"]["x"]))
        seed_index = next(index for index, item in enumerate(candidate_rows) if item["bbox"] == seed_bbox)
    cluster = [candidate_rows[seed_index]["bbox"]]
    max_gap = 46
    previous_cy = candidate_rows[seed_index]["cy"]
    for item in reversed(candidate_rows[:seed_index]):
        if previous_cy - item["cy"] > max_gap:
            break
        cluster.append(item["bbox"])
        previous_cy = item["cy"]
    previous_cy = candidate_rows[seed_index]["cy"]
    for item in candidate_rows[seed_index + 1 :]:
        if item["cy"] - previous_cy > max_gap:
            break
        cluster.append(item["bbox"])
        previous_cy = item["cy"]
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
        "section_id": _first_compact_text(item.get("section_id")) or _section_id_for_bbox(bbox, sections),
        "bbox": bbox,
        "click_point": click_point,
        "confidence": _bounded_float(item.get("confidence")),
        "source": source,
        "source_id": item.get("id") or item.get("element_id") or item.get("candidate_id"),
        "screen_map_rule": item.get("screen_map_rule"),
        "children": _as_list(item.get("children")),
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
    if _looks_like_high_risk_action_text(risk_text):
        return "requires_user_confirmation", sorted(set([*reasons, "potential_side_effect_action"]))
    if policy.get("allowed") is False:
        if _looks_like_low_risk_navigation_candidate(label=label, role=role, extra_text=risk_text):
            return "safe_click_allowed", sorted(set([*reasons, "low_risk_navigation_policy_relaxed"]))
        return "blocked", sorted(set(reasons or ["interaction_policy_blocked"]))
    if policy.get("allowed") is True:
        return "safe_click_allowed", sorted(set(reasons))
    if any(token in str(role).casefold() for token in ["input", "textbox", "search"]):
        return "safe_click_allowed", sorted(set(reasons))
    return "safe_dry_run_only", sorted(set(reasons or ["requires_precise_location_before_click"]))


def _execution_allowed_for_risk_class(*, label: str, role: str, risk_class: str) -> tuple[bool, str]:
    normalized_risk = str(risk_class or "").strip()
    risk_text = " ".join([label, role, normalized_risk]).casefold()
    if normalized_risk == "safe_open_apply_flow" and not _looks_like_final_submit_action_text(risk_text):
        return True, "risk_class_safe_open_apply_flow"
    if (
        normalized_risk == "safe_click_allowed"
        and _looks_like_apply_entry_action_text(risk_text)
        and not _looks_like_final_submit_action_text(risk_text)
    ):
        return True, "risk_class_safe_apply_entry"
    if _looks_like_high_risk_action_text(risk_text):
        return False, "potential_side_effect_action"
    if normalized_risk == "safe_click_allowed":
        return True, "risk_class_safe_click_allowed"
    if normalized_risk == "safe_dry_run_only" and _looks_like_low_risk_navigation_candidate(
        label=label,
        role=role,
        extra_text=risk_text,
    ):
        return True, "low_risk_navigation_policy_relaxed"
    return False, "requires_confirmation_or_high_risk_policy"


def _looks_like_final_submit_action_text(text: str) -> bool:
    normalized = str(text or "").casefold()
    final_terms = [
        "submit application",
        "send application",
        "complete application",
        "confirm application",
        "final_submit",
        "payment",
        "pay now",
        "提交申请",
        "发送申请",
        "确认提交",
        "付款",
    ]
    return any(term in normalized for term in final_terms)


def _looks_like_high_risk_action_text(text: str) -> bool:
    normalized = str(text or "").casefold()
    tokens = set(re.findall(r"[a-z0-9]+", normalized))
    if "pay" in tokens and "filter" in tokens and not any(
        phrase in normalized
        for phrase in [
            "pay now",
            "pay invoice",
            "make payment",
            "payment",
            "checkout",
            "purchase",
        ]
    ):
        return False
    dangerous_phrases = [
        "quick apply",
        "submit application",
        "send application",
        "complete application",
        "confirm application",
        "make payment",
        "pay now",
        "pay invoice",
        "save changes",
        "close window",
        "删除",
        "移除",
        "支付",
        "购买",
        "发送",
        "提交",
        "申请",
        "授权",
        "关闭窗口",
    ]
    if any(term in normalized for term in dangerous_phrases):
        return True
    dangerous_tokens = {"delete", "remove", "purchase", "send", "submit", "apply", "authorize", "permission", "upload", "pay", "payment"}
    return bool(tokens & dangerous_tokens)


def _looks_like_apply_entry_action_text(text: str) -> bool:
    normalized = str(text or "").casefold()
    if _looks_like_final_submit_action_text(normalized):
        return False
    tokens = set(re.findall(r"[a-z0-9]+", normalized))
    if "apply" in tokens:
        return True
    return "quick apply" in normalized or "申请" in normalized


def _looks_like_low_risk_navigation_candidate(*, label: str, role: str, extra_text: str = "") -> bool:
    text = " ".join([label, role, extra_text]).casefold()
    role_tokens = [
        "card",
        "news_card",
        "job_card",
        "result",
        "search_result",
        "link",
        "title",
        "row",
        "list_item",
        "article",
        "detail",
    ]
    effect_tokens = [
        "open",
        "view",
        "read",
        "detail",
        "article",
        "job",
        "card",
        "result",
        "recommended",
        "recommendation",
        "listing",
    ]
    return any(token in text for token in role_tokens) or any(token in text for token in effect_tokens)


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


def _learn_all_targets_requested(request: VisionLocateTargetRequestModel, metadata: dict[str, Any]) -> bool:
    if request.agent_mode != "learn":
        return False
    return bool(metadata.get("learn_all_targets") or metadata.get("learn_all_subpath_targets"))


def _stage2_calibration_locator_context(
    item: dict[str, Any],
    *,
    region_label: str,
    region_bbox: dict[str, int] | None,
    item_index: int,
    item_count: int,
) -> tuple[str, dict[str, Any]]:
    label = _first_compact_text(item.get("label"), item.get("text"), item.get("number"), item.get("item_id"))
    role = _first_compact_text(item.get("role"), "review_only")
    number = _first_compact_text(item.get("number"), str(item_index))
    child_labels: list[str] = []
    seen: set[str] = set()
    for child in _as_list(item.get("children")):
        if not isinstance(child, dict):
            continue
        child_label = _first_compact_text(child.get("label"), child.get("text"))
        key = child_label.casefold()
        if not child_label or key == label.casefold() or key in seen:
            continue
        seen.add(key)
        child_labels.append(child_label)
        if len(child_labels) >= 5:
            break
    prompt_parts = [
        f"Locate the exact {role} numbered {number} in {region_label or 'the current region'}.",
        f"It is item {item_index} of {item_count} in that region.",
    ]
    if child_labels:
        prompt_parts.append(f"It contains visible text: {' | '.join(child_labels)}.")
    elif label:
        prompt_parts.append(f"Its visible label is {label}.")
    prompt_parts.append("Return one point inside this exact item, not a nearby sibling.")
    context = {
        "contract_version": "stage2_calibration_locator_context_v1",
        "region_label": region_label,
        "region_bbox": region_bbox,
        "item_number": number,
        "item_index": item_index,
        "item_count": item_count,
        "child_labels": child_labels,
    }
    return " ".join(prompt_parts), context


def _attach_two_stage_calibration_candidates(
    observe_reuse: dict[str, Any],
    *,
    report_path_value: Any,
    image_path: str,
) -> dict[str, Any]:
    report_path_text = str(report_path_value or "").strip()
    if not report_path_text:
        return observe_reuse
    report_path = Path(report_path_text)
    if not report_path.is_absolute():
        report_path = Path.cwd() / report_path
    try:
        report = json.loads(report_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        return {
            **observe_reuse,
            "two_stage_calibration_source": {
                "status": "invalid",
                "reason": f"two_stage_report_unreadable: {exc}",
                "report_path": str(report_path),
            },
        }
    if not isinstance(report, dict):
        return observe_reuse
    source_image_text = str(report.get("source_image_path") or "").strip()
    if source_image_text:
        source_image = Path(source_image_text)
        if not source_image.is_absolute():
            source_image = Path.cwd() / source_image
        if source_image.resolve() != Path(image_path).resolve():
            return {
                **observe_reuse,
                "two_stage_calibration_source": {
                    "status": "stale_fixture",
                    "reason": "two_stage_source_image_mismatch",
                    "report_path": str(report_path),
                    "expected_image_path": str(Path(image_path).resolve()),
                    "actual_image_path": str(source_image.resolve()),
                },
            }
    stage2 = report.get("stage2_numbering") if isinstance(report.get("stage2_numbering"), dict) else {}
    stage1_localization = report.get("stage1_region_localization") if isinstance(report.get("stage1_region_localization"), dict) else {}
    stage1_structure = report.get("stage1_structure") if isinstance(report.get("stage1_structure"), dict) else {}
    structure_regions = [
        item
        for item in _as_list(stage1_localization.get("regions") or stage1_structure.get("structure_regions"))
        if isinstance(item, dict)
    ]
    fusion = report.get("fusion") if isinstance(report.get("fusion"), dict) else {}
    numbered_overlay_value = str(
        fusion.get("compiled_overlay_path")
        or fusion.get("full_screen_understanding_overlay_path")
        or ""
    ).strip()
    numbered_overlay_path = ""
    if numbered_overlay_value:
        numbered_overlay = Path(numbered_overlay_value)
        if not numbered_overlay.is_absolute():
            numbered_overlay = Path.cwd() / numbered_overlay
        numbered_overlay_path = str(numbered_overlay.resolve())
    calibration_candidates: list[dict[str, Any]] = []
    suppressed_child_evidence: list[dict[str, Any]] = []
    for region in _as_list(stage2.get("regions")):
        if not isinstance(region, dict):
            continue
        region_id = _first_compact_text(region.get("region_id"), f"region_{len(calibration_candidates) + 1}")
        region_label = _first_compact_text(region.get("label"), region_id)
        region_bbox = _normalize_map_bbox(region.get("bbox"))
        calibratable_items, child_evidence_items = partition_stage2_calibration_items(region)
        suppressed_child_evidence.extend(
            {
                "region_id": region_id,
                "item_id": _first_compact_text(item.get("item_id"), item.get("number")),
                "label": _first_compact_text(item.get("label"), item.get("text")),
                "reason": "child_evidence_is_calibrated_through_parent_region",
            }
            for item in child_evidence_items
        )
        for item_index, item in enumerate(calibratable_items, start=1):
            if not isinstance(item, dict):
                continue
            bbox = _normalize_map_bbox(item.get("bbox"))
            if not bbox:
                continue
            item_id = _first_compact_text(item.get("item_id"), item.get("number"), f"item_{len(calibration_candidates) + 1}")
            locator_prompt, locator_context = _stage2_calibration_locator_context(
                item,
                region_label=region_label,
                region_bbox=region_bbox,
                item_index=item_index,
                item_count=len(calibratable_items),
            )
            calibration_candidates.append(
                {
                    "contract_version": "screen_map_calibration_candidate_v1",
                    "candidate_id": f"stage2:{region_id}:{item_id}",
                    "label": _first_compact_text(item.get("label"), item.get("text"), item.get("number"), item_id),
                    "role": _first_compact_text(item.get("role"), "review_only"),
                    "bbox": bbox,
                    "click_point": _normalize_map_point(item.get("click_point"), bbox),
                    "section_id": region_id,
                    "source": "two_stage_stage2_numbering",
                    "confidence": item.get("confidence"),
                    "locator_prompt": locator_prompt,
                    "locator_context": locator_context,
                    "numbered_overlay_path": numbered_overlay_path,
                    "calibration_only": True,
                    "review_only": True,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                }
            )
    calibration_candidates.sort(key=_stage2_calibration_candidate_priority, reverse=True)
    screen_map = observe_reuse.get("screen_map") if isinstance(observe_reuse.get("screen_map"), dict) else {}
    return {
        **observe_reuse,
        "screen_map": {
            **screen_map,
            "calibration_candidates": calibration_candidates,
            "two_stage_calibration_authoritative": bool(calibration_candidates),
            "two_stage_structure_regions": structure_regions,
        },
        "two_stage_calibration_source": {
            "status": "ready" if calibration_candidates else "empty",
            "report_path": str(report_path.resolve()),
            "candidate_count": len(calibration_candidates),
            "suppressed_child_evidence_count": len(suppressed_child_evidence),
            "suppressed_child_evidence": suppressed_child_evidence,
            "source_image_path": str(Path(image_path).resolve()),
            "numbered_overlay_path": numbered_overlay_path,
            "numbered_overlay_available": bool(numbered_overlay_path and Path(numbered_overlay_path).exists()),
        },
    }


def _stage2_calibration_candidate_priority(candidate: dict[str, Any]) -> tuple[int, int, int]:
    label = _first_compact_text(candidate.get("label")).casefold()
    role = _first_compact_text(candidate.get("role")).casefold()
    generic_label = bool(re.fullmatch(r"(?:control|item|button|card)\s*\d+", label))
    weak_label = label in {"", "music", "mus", "unknown"}
    partial = "partial" in role or "partial" in label
    semantic_role = role in {
        "button",
        "icon_button",
        "nav_item",
        "menu_item",
        "media_card",
        "card",
        "tile",
        "input",
        "text_input",
    }
    score = 100
    if generic_label:
        score -= 80
    if weak_label:
        score -= 40
    if partial:
        score -= 30
    if semantic_role:
        score += 20
    return score, min(len(label), 80), -int((_normalize_map_bbox(candidate.get("bbox")) or {}).get("y") or 0)


def _screen_map_candidate_to_learn_target(candidate: dict[str, Any], index: int) -> dict[str, Any] | None:
    bbox = _normalize_map_bbox(candidate.get("bbox") or candidate.get("bounding_box") or candidate.get("bounds"))
    point = _normalize_map_point(candidate.get("click_point") or candidate.get("clickPoint"), bbox)
    label = _first_compact_text(candidate.get("label"), candidate.get("text"), candidate.get("name"), candidate.get("description"))
    if not label and not bbox:
        return None
    role = _first_compact_text(candidate.get("role"), candidate.get("type"), candidate.get("kind"), "control")
    return {
        "contract_version": "learn_target_location_v1",
        "candidate_id": _first_compact_text(candidate.get("candidate_id"), candidate.get("id"), f"learn_target_{index}"),
        "label": label or f"control {index + 1}",
        "role": role,
        "bbox": bbox,
        "click_point": point,
        "section_id": _first_compact_text(candidate.get("section_id"), candidate.get("section")),
        "source": _first_compact_text(candidate.get("source"), "screen_map"),
        "confidence": _bounded_float(candidate.get("confidence")),
        "description": _first_compact_text(candidate.get("description"), candidate.get("meaning"), candidate.get("purpose")),
        "coordinate_source": "screen_map_v1.candidates",
        "location_status": "coordinate_ready" if point else "bbox_missing_click_point",
    }


def _screen_map_calibration_candidate_to_target(candidate: dict[str, Any], index: int) -> dict[str, Any] | None:
    target = _screen_map_candidate_to_learn_target(candidate, index)
    if target is None:
        return None
    return {
        **target,
        "locator_prompt": " ".join(str(candidate.get("locator_prompt") or "").split())[:600],
        "locator_context": candidate.get("locator_context") if isinstance(candidate.get("locator_context"), dict) else {},
        "numbered_overlay_path": str(candidate.get("numbered_overlay_path") or ""),
        "calibration_only": True,
        "review_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "coordinate_source": "two_stage_stage2_numbering",
    }


def _screen_map_candidate_to_learn_review_box(candidate: dict[str, Any], index: int, *, review_status: str) -> dict[str, Any] | None:
    bbox = _normalize_map_bbox(candidate.get("bbox") or candidate.get("bounding_box") or candidate.get("bounds"))
    point = _normalize_map_point(candidate.get("click_point") or candidate.get("clickPoint"), bbox)
    label = _first_compact_text(candidate.get("label"), candidate.get("text"), candidate.get("name"), candidate.get("description"))
    if not label and not bbox:
        return None
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
    policy = evidence.get("interaction_policy") if isinstance(evidence.get("interaction_policy"), dict) else {}
    reasons = policy.get("reasons") if isinstance(policy.get("reasons"), list) else []
    children = _normalize_learn_review_children(candidate.get("children"))
    return {
        "contract_version": "learn_review_box_v1",
        "candidate_id": _first_compact_text(candidate.get("candidate_id"), candidate.get("id"), f"learn_review_box_{index}"),
        "label": label or f"review box {index + 1}",
        "role": _first_compact_text(candidate.get("role"), candidate.get("type"), candidate.get("kind"), "review_only"),
        "bbox": bbox,
        "click_point": point,
        "section_id": _first_compact_text(candidate.get("section_id"), candidate.get("section")),
        "source": _first_compact_text(candidate.get("source"), "screen_map"),
        "confidence": _bounded_float(candidate.get("confidence")),
        "review_status": review_status,
        "review_reason": "; ".join(str(item) for item in reasons if str(item or "").strip())[:240],
        "coordinate_source": "screen_map_v1.candidates",
        "children": children,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _normalize_learn_review_children(value: Any) -> list[dict[str, Any]]:
    children: list[dict[str, Any]] = []
    for index, item in enumerate(_as_list(value)):
        if not isinstance(item, dict):
            continue
        label = _normalize_ocr_candidate_label(_first_compact_text(item.get("label"), item.get("text"), item.get("name")))
        bbox = _normalize_map_bbox(item.get("bbox") or item.get("bounding_box") or item.get("bounds"))
        if not label and not bbox:
            continue
        children.append(
            {
                "child_id": _first_compact_text(item.get("child_id"), item.get("id"), item.get("text_id"), f"child_{index + 1}"),
                "label": label or f"child {index + 1}",
                "role": _first_compact_text(item.get("role"), item.get("type"), "text"),
                "bbox": bbox,
                "source": _first_compact_text(item.get("source"), "screen_map_child"),
            }
        )
    return children


def _ocr_text_to_learn_review_box(text_item: dict[str, Any], index: int) -> dict[str, Any] | None:
    label = _normalize_ocr_candidate_label(_first_compact_text(text_item.get("text"), text_item.get("label")))
    bbox = _normalize_map_bbox(text_item.get("bbox") or text_item.get("bounding_box") or text_item.get("bounds"))
    if not label or not bbox:
        return None
    if _learn_review_ocr_text_is_noise(label, bbox=bbox, confidence=_bounded_float(text_item.get("confidence"))):
        return None
    text_id = _first_compact_text(text_item.get("id"), f"ocr_text_{index}")
    return {
        "contract_version": "learn_review_box_v1",
        "candidate_id": f"learn_ocr_text_{text_id}",
        "label": label,
        "role": "ocr_text_review_only",
        "bbox": bbox,
        "click_point": _normalize_map_point(None, bbox),
        "section_id": _first_compact_text(text_item.get("section_id"), text_item.get("section")),
        "source": _first_compact_text(text_item.get("source"), "observe_result.texts"),
        "confidence": _bounded_float(text_item.get("confidence")),
        "review_status": "ocr_text_review_only",
        "review_reason": "ocr_text_detail_for_learning_interface",
        "coordinate_source": "observe_result.texts",
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _learn_review_ocr_text_is_noise(label: str, *, bbox: dict[str, int], confidence: float | None) -> bool:
    text = str(label or "").strip()
    if _screen_map_text_is_noise(text, allow_short=True):
        return True
    if confidence is not None and confidence < 0.45:
        return True
    if bbox["y"] < 64:
        return True
    alnum_count = sum(1 for char in text if char.isalnum())
    digit_count = sum(1 for char in text if char.isdigit())
    alpha_count = sum(1 for char in text if char.isalpha())
    if len(text) <= 1:
        return True
    if digit_count and digit_count >= max(1, alpha_count) and len(text) <= 6:
        return True
    return alnum_count <= 1 and len(text) <= 3


def _learn_review_child_identity(review_boxes: list[dict[str, Any]]) -> tuple[set[str], set[str]]:
    child_ids: set[str] = set()
    child_box_keys: set[str] = set()
    for review_box in review_boxes:
        for child in _as_list(review_box.get("children")):
            if not isinstance(child, dict):
                continue
            child_id = _first_compact_text(child.get("child_id"), child.get("id"), child.get("text_id"))
            if child_id:
                child_ids.add(child_id)
            label = _normalize_ocr_candidate_label(_first_compact_text(child.get("label"), child.get("text"), child.get("name")))
            bbox = _normalize_map_bbox(child.get("bbox"))
            if label and bbox:
                child_box_keys.add(f"{label}|{bbox}")
    return child_ids, child_box_keys


def _screen_map_has_side_navigation_region(screen_map: dict[str, Any]) -> bool:
    regions = _as_list(screen_map.get("two_stage_structure_regions"))
    side_navigation_tokens = {
        "left_navigation",
        "right_navigation",
        "side_navigation",
        "navigation_rail",
        "left_sidebar",
        "right_sidebar",
        "sidebar",
        "side_bar",
    }
    for region in regions:
        if not isinstance(region, dict):
            continue
        fields = {
            str(region.get("region_id") or "").casefold().replace(" ", "_"),
            str(region.get("role") or "").casefold().replace(" ", "_"),
            str(region.get("region_type") or "").casefold().replace(" ", "_"),
            str(region.get("label") or "").casefold().replace(" ", "_"),
        }
        if any(token in field for field in fields for token in side_navigation_tokens):
            return True
    return False


def _learn_nav_rail_review_boxes_from_image(image_path: str, *, existing_count: int = 0) -> list[dict[str, Any]]:
    source_image = Path(image_path)
    if not source_image.exists():
        return []
    try:
        with Image.open(source_image) as image:
            rgb = image.convert("RGB")
            width, height = rgb.size
            if width <= 0 or height <= 0:
                return []
            strip_w = min(96, max(44, round(width * 0.075)))
            y_min = max(48, round(height * 0.05))
            y_max = max(y_min, height - max(16, round(height * 0.02)))
            pixels = rgb.load()
            active_rows: list[tuple[int, int, int]] = []
            for y in range(y_min, y_max):
                xs: list[int] = []
                for x in range(0, strip_w):
                    r, g, b = pixels[x, y]
                    lum = (int(r) + int(g) + int(b)) / 3
                    saturation = max(r, g, b) - min(r, g, b)
                    if lum < 120 or (saturation >= 70 and lum < 235):
                        xs.append(x)
                if len(xs) >= 3:
                    active_rows.append((y, min(xs), max(xs)))
    except Exception:
        return []

    runs: list[dict[str, int]] = []
    current: dict[str, int] | None = None
    for y, min_x, max_x in active_rows:
        if current is None or y > current["bottom"] + 5:
            if current is not None:
                runs.append(current)
            current = {"top": y, "bottom": y, "min_x": min_x, "max_x": max_x}
            continue
        current["bottom"] = y
        current["min_x"] = min(current["min_x"], min_x)
        current["max_x"] = max(current["max_x"], max_x)
    if current is not None:
        runs.append(current)

    boxes: list[dict[str, Any]] = []
    for run in runs:
        x = max(0, run["min_x"] - 4)
        y = max(0, run["top"] - 4)
        w = min(strip_w - x, run["max_x"] - run["min_x"] + 9)
        h = run["bottom"] - run["top"] + 9
        if w < 6 or h < 6 or h > 56 or w > 56:
            continue
        boxes.append(
            {
                "contract_version": "learn_review_box_v1",
                "candidate_id": f"learn_nav_rail_icon_{existing_count + len(boxes) + 1}",
                "label": f"Left nav icon {len(boxes) + 1}",
                "role": "nav_rail_icon_review_only",
                "bbox": {"x": int(x), "y": int(y), "w": int(w), "h": int(h)},
                "click_point": {"x": int(x + w / 2), "y": int(y + h / 2)},
                "section_id": "left_nav_rail",
                "source": "image_left_nav_rail_scan",
                "confidence": None,
                "review_status": "nav_rail_review_only",
                "review_reason": "left_nav_rail_visual_icon_without_ocr_or_uia",
                "coordinate_source": "screenshot_left_nav_rail_scan",
                "children": [],
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
        if len(boxes) >= 16:
            break
    return boxes


def _learn_target_candidate_is_tiny_noise(candidate: dict[str, Any]) -> bool:
    bbox = _normalize_map_bbox(candidate.get("bbox") or candidate.get("bounding_box") or candidate.get("bounds"))
    if not bbox:
        return True
    return bbox["w"] < 4 or bbox["h"] < 4 or bbox["w"] * bbox["h"] < 64


def _learn_target_candidate_is_browser_chrome(candidate: dict[str, Any], *, image_size: dict[str, int], screen_map: dict[str, Any]) -> bool:
    if _path_graph_candidate_is_browser_chrome(candidate):
        return True
    app_name = _first_compact_text(screen_map.get("app_name"), screen_map.get("state_hint"), screen_map.get("state_id"))
    browser_surface = _is_browser_app_name(app_name) or _looks_like_web_app_name(app_name) or _screen_map_looks_like_browser_surface(screen_map)
    bbox = _normalize_map_bbox(candidate.get("bbox") or candidate.get("bounding_box") or candidate.get("bounds"))
    if not bbox:
        return False
    if not browser_surface:
        return False
    if _learn_target_candidate_is_os_taskbar(candidate, bbox=bbox, image_size=image_size):
        return True
    chrome_bottom = min(int(image_size.get("height") or 0), max(72, round(int(image_size.get("height") or 0) * 0.065)))
    if bbox["y"] > chrome_bottom:
        return False
    text = " ".join(
        part
        for part in [
            _first_compact_text(candidate.get("label"), candidate.get("text"), candidate.get("description")),
            _first_compact_text(candidate.get("role"), candidate.get("type")),
        ]
        if part
    ).casefold()
    chrome_tokens = ("http://", "https://", "www.", ".com", ".org", "address", "tab", "new tab", "back", "reload")
    return bbox["y"] <= 56 or any(token in text for token in chrome_tokens)


def _learn_target_candidate_is_non_actionable_content(candidate: dict[str, Any]) -> bool:
    source = str(candidate.get("source") or "").casefold()
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
    policy = evidence.get("interaction_policy") if isinstance(evidence.get("interaction_policy"), dict) else {}
    if policy.get("allowed") is True:
        if source != "ocr_text_actions":
            return False
    if source == "ocr_text_actions":
        evidence_level = str(evidence.get("evidence_level") or "").casefold()
        if evidence_level != "ocr_text_only":
            return False
        role = str(candidate.get("role") or "").casefold()
        bbox = _normalize_map_bbox(candidate.get("bbox") or candidate.get("bounding_box") or candidate.get("bounds")) or {}
        label = _first_compact_text(candidate.get("label"), candidate.get("text"), candidate.get("description")).casefold()
        screen_map_rule = str(candidate.get("screen_map_rule") or evidence.get("screen_map_rule") or "").casefold()
        clear_button_rule = screen_map_rule in {"more_text_is_button", "explicit_button_text", "submit_text_is_button"}
        clear_button_text = bool(re.search(r"(^|\\b)(more|learn more|download|apply|next|continue|go|search)(\\b|$)", label))
        if role == "button" and (clear_button_rule or clear_button_text) and int(bbox.get("w") or 0) <= 180 and int(bbox.get("h") or 0) <= 72:
            return False
        return True
    if source != "ocr_card_groups":
        return False
    role = str(candidate.get("role") or "").casefold()
    risk_class = str(candidate.get("risk_class") or "").casefold()
    screen_map_rule = str(candidate.get("screen_map_rule") or "").casefold()
    content_roles = {"card", "news_card", "recommendation_item", "section", "group"}
    if risk_class in {"safe_dry_run_only", "safe_review_only"} and role in content_roles:
        return True
    return screen_map_rule == "card_texts_grouped_as_single_candidate" and role in content_roles


def _learn_target_candidate_is_blocked_review_only(candidate: dict[str, Any]) -> bool:
    risk_class = str(candidate.get("risk_class") or "").casefold()
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
    policy = evidence.get("interaction_policy") if isinstance(evidence.get("interaction_policy"), dict) else {}
    return risk_class == "blocked" or policy.get("allowed") is False


def _learn_blocked_candidate_should_be_suppressed_from_review(candidate: dict[str, Any]) -> bool:
    source = str(candidate.get("source") or "").casefold()
    role = str(candidate.get("role") or candidate.get("type") or "").casefold()
    section_id = str(candidate.get("section_id") or candidate.get("section") or "").casefold()
    bbox = _normalize_map_bbox(candidate.get("bbox") or candidate.get("bounding_box") or candidate.get("bounds"))
    if not bbox:
        return False
    if section_id in {"left_nav_rail", "left_nav", "left_sidebar"} and role in {"icon_button", "button", "icon"}:
        return True
    return source == "top_level.ui.elements" and role in {"icon_button", "icon"} and bbox["x"] <= 96


def _learn_target_candidate_is_ungrounded_semantic_region(candidate: dict[str, Any]) -> bool:
    evidence = candidate.get("evidence") if isinstance(candidate.get("evidence"), dict) else {}
    evidence_level = str(candidate.get("evidence_level") or evidence.get("evidence_level") or "").casefold()
    if evidence_level != "semantic_region_only":
        return False
    coordinate_confidence = str(candidate.get("coordinate_confidence") or evidence.get("coordinate_confidence") or "").casefold()
    if coordinate_confidence == "high":
        return False
    if _first_compact_text(candidate.get("source_text_id"), evidence.get("source_text_id")):
        return False
    return True


def _looks_like_web_app_name(value: str | None) -> bool:
    text = str(value or "").strip().casefold()
    return bool(re.search(r"\b[a-z0-9-]+\.(com|org|net|io|co|nz|dev|app)\b", text))


def _screen_map_looks_like_browser_surface(screen_map: dict[str, Any]) -> bool:
    haystack = " ".join(
        _first_compact_text(item.get("label"), item.get("text"), item.get("name"), item.get("description"))
        for item in screen_map.get("candidates") or []
        if isinstance(item, dict)
    ).casefold()
    if any(token in haystack for token in ("http://", "https://", "www.", ".com", ".org", "address bar", "new tab", "reload")):
        return True
    for item in screen_map.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        bbox = _normalize_map_bbox(item.get("bbox") or item.get("bounding_box") or item.get("bounds"))
        if not bbox or bbox["y"] > 86:
            continue
        text = _first_compact_text(item.get("label"), item.get("text"), item.get("name"), item.get("description")).casefold()
        if any(token in text for token in ("tab", "http", "www.", ".org", ".com", "back", "reload")):
            return True
    return False


def _learn_target_candidate_is_os_taskbar(candidate: dict[str, Any], *, bbox: dict[str, int], image_size: dict[str, int]) -> bool:
    height = int(image_size.get("height") or 0)
    if height <= 0 or bbox["y"] < max(0, height - 96):
        return False
    text = " ".join(
        part
        for part in [
            _first_compact_text(candidate.get("label"), candidate.get("text"), candidate.get("name"), candidate.get("description")),
            _first_compact_text(candidate.get("role"), candidate.get("type"), candidate.get("source")),
        ]
        if part
    ).casefold()
    taskbar_tokens = (
        "taskbar",
        "start",
        "steam",
        "codex",
        "edge",
        "microsoft edge",
        "explorer",
        "system tray",
        "search",
        "好友列表",
        "搜索",
    )
    return any(token in text for token in taskbar_tokens) or bbox["h"] <= 36


def _learn_target_image_size(image_path: str) -> dict[str, int]:
    try:
        with Image.open(image_path) as image:
            return {"width": int(image.width), "height": int(image.height)}
    except Exception:
        return {"width": 0, "height": 0}


def _point_inside_bbox(point: dict[str, int] | None, bbox: dict[str, int] | None) -> bool:
    if not point or not bbox:
        return False
    x = int(point.get("x", 0))
    y = int(point.get("y", 0))
    return bbox["x"] <= x <= bbox["x"] + bbox["w"] and bbox["y"] <= y <= bbox["y"] + bbox["h"]


def _bbox_inside_image(bbox: dict[str, int] | None, image_size: dict[str, int]) -> bool | None:
    if not bbox:
        return False
    width = int(image_size.get("width") or 0)
    height = int(image_size.get("height") or 0)
    if width <= 0 or height <= 0:
        return None
    return bbox["x"] >= 0 and bbox["y"] >= 0 and bbox["x"] + bbox["w"] <= width and bbox["y"] + bbox["h"] <= height


def _point_inside_image(point: dict[str, int] | None, image_size: dict[str, int]) -> bool | None:
    if not point:
        return False
    width = int(image_size.get("width") or 0)
    height = int(image_size.get("height") or 0)
    if width <= 0 or height <= 0:
        return None
    return 0 <= int(point.get("x", -1)) < width and 0 <= int(point.get("y", -1)) < height


def _validate_learn_target_coordinates(target: dict[str, Any], *, image_size: dict[str, int]) -> dict[str, Any]:
    bbox = _normalize_map_bbox(target.get("bbox"))
    point = _normalize_map_point(target.get("click_point"), bbox)
    bbox_inside = _bbox_inside_image(bbox, image_size)
    point_inside_bbox = _point_inside_bbox(point, bbox)
    point_inside = _point_inside_image(point, image_size)
    reasons: list[str] = []
    if not bbox:
        reasons.append("bbox_missing_or_invalid")
    if not point:
        reasons.append("click_point_missing")
    if bbox_inside is False:
        reasons.append("bbox_outside_image")
    if bbox_inside is None or point_inside is None:
        reasons.append("image_size_unavailable")
    if point_inside is False:
        reasons.append("click_point_outside_image")
    if point and bbox and not point_inside_bbox:
        reasons.append("click_point_outside_bbox")

    valid = bool(bbox and point and point_inside_bbox and bbox_inside is True and point_inside is True)
    target["bbox"] = bbox
    target["click_point"] = point
    target["location_status"] = "coordinate_verified" if valid else "coordinate_invalid"
    target["coordinate_validation"] = {
        "contract_version": "learn_target_coordinate_validation_v1",
        "status": "valid" if valid else "invalid",
        "bbox_present": bool(bbox),
        "click_point_present": bool(point),
        "bbox_inside_image": bbox_inside,
        "click_point_inside_image": point_inside,
        "click_point_inside_bbox": point_inside_bbox,
        "image_size": image_size,
        "reasons": reasons,
    }
    return target


def _learn_vista_coordinate_validation_options(request: VisionLocateTargetRequestModel, local_config: dict[str, Any]) -> dict[str, Any]:
    if request.learn_depth != "deep":
        return {"enabled": False, "reason": "not_learn_deep"}
    if not _uses_learning_point_grounding(local_config):
        return {"enabled": False, "reason": "local_grounding_is_not_supported_point_model"}
    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    raw = metadata.get("learn_vista_coordinate_validation", True)
    if raw is False:
        return {"enabled": False, "reason": "disabled_by_metadata"}
    if isinstance(raw, dict):
        raw_max_targets = raw.get("max_targets") or raw.get("max_candidates") or 5
        validate_all_targets = str(raw_max_targets).casefold() == "all"
        max_targets = 9999 if validate_all_targets else int(raw_max_targets)
        return {
            "enabled": raw.get("enabled", True) is not False,
            "max_targets": max_targets,
            "validate_all_targets": validate_all_targets,
            "update_click_point": raw.get("update_click_point", True) is not False,
            "padding": int(raw.get("padding") or 10),
            "per_target_timeout_seconds": float(raw.get("per_target_timeout_seconds") or 12),
            "stop_on_failure": raw.get("stop_on_failure", True) is not False,
            "use_numbered_overlay": raw.get("use_numbered_overlay") is True,
        }
    return {
        "enabled": True,
        "max_targets": 5,
        "update_click_point": True,
        "padding": 10,
        "per_target_timeout_seconds": 12.0,
        "stop_on_failure": True,
        "use_numbered_overlay": False,
    }


def _learn_precise_locator_text_similarity(left: str, right: str) -> float:
    left_text = "".join(character for character in str(left or "").casefold() if character.isalnum())
    right_text = "".join(character for character in str(right or "").casefold() if character.isalnum())
    if not left_text or not right_text:
        return 0.0
    if left_text in right_text or right_text in left_text:
        return min(len(left_text), len(right_text)) / max(len(left_text), len(right_text))
    return SequenceMatcher(None, left_text, right_text).ratio()


def _learn_precise_locator_bbox_inside_parent(bbox: dict[str, int], parent_bbox: dict[str, int]) -> bool:
    return (
        parent_bbox["x"] <= bbox["x"]
        and parent_bbox["y"] <= bbox["y"]
        and bbox["x"] + bbox["w"] <= parent_bbox["x"] + parent_bbox["w"]
        and bbox["y"] + bbox["h"] <= parent_bbox["y"] + parent_bbox["h"]
    )


def _learn_vista_target_context_bbox(
    target_bbox: dict[str, int],
    *,
    parent_bbox: dict[str, int],
    target_role: str | None = None,
) -> dict[str, int]:
    target_center_x = target_bbox["x"] + target_bbox["w"] / 2
    target_center_y = target_bbox["y"] + target_bbox["h"] / 2
    normalized_role = str(target_role or "").strip().casefold().replace("-", "_").replace(" ", "_")
    compact_direct_control = _learn_vista_is_compact_direct_control(target_bbox, target_role=target_role)
    dense_column_row = normalized_role in {"list_row", "table_row", "file_row"}
    if normalized_role == "menu_item":
        context_width = min(parent_bbox["w"], max(72, int(round(target_bbox["w"] * 1.6))))
        context_height = min(parent_bbox["h"], max(48, int(round(target_bbox["h"] * 1.36))))
    elif compact_direct_control:
        context_width = min(parent_bbox["w"], max(72, int(round(target_bbox["w"] * 1.5))))
        context_height = min(parent_bbox["h"], max(56, int(round(target_bbox["h"] * 1.25))))
    elif dense_column_row:
        horizontal_padding = min(48, max(16, int(round(target_bbox["w"] * 0.1))))
        context_width = min(parent_bbox["w"], max(96, target_bbox["w"] + horizontal_padding * 2))
    else:
        context_width = min(parent_bbox["w"], max(160, int(round(target_bbox["w"] * 2.0))))
    if normalized_role in {"conversation_row", "list_row", "table_row", "file_row", "message_item"}:
        context_height = min(parent_bbox["h"], max(1, int(target_bbox["h"])))
    elif normalized_role != "menu_item" and not compact_direct_control:
        context_height = min(parent_bbox["h"], max(100, int(round(target_bbox["h"] * 1.8))))
    max_x = parent_bbox["x"] + parent_bbox["w"] - context_width
    max_y = parent_bbox["y"] + parent_bbox["h"] - context_height
    context_x = max(parent_bbox["x"], min(int(round(target_center_x - context_width / 2)), max_x))
    context_y = max(parent_bbox["y"], min(int(round(target_center_y - context_height / 2)), max_y))
    return {
        "x": context_x,
        "y": context_y,
        "w": context_width,
        "h": context_height,
    }


def _learn_vista_is_compact_direct_control(
    target_bbox: dict[str, int],
    *,
    target_role: str | None,
) -> bool:
    normalized_role = str(target_role or "").strip().casefold().replace("-", "_").replace(" ", "_")
    return (
        normalized_role in {"button", "control", "icon_button", "tab"}
        and int(target_bbox.get("w") or 0) <= 72
        and int(target_bbox.get("h") or 0) <= 72
    )


def _learn_vista_compact_control_prompt(label: str, role: str) -> str:
    normalized_label = " ".join(str(label or "").split())
    generic_label = re.fullmatch(r"(?:visual\s+)?control(?:\s+\d+)?", normalized_label, flags=re.IGNORECASE)
    target_text = "the visible control" if generic_label else f'the visible {role} "{normalized_label}"'
    return (
        f"Locate {target_text} closest to the center of this crop. "
        "The crop is centered on the current candidate; return one point inside that candidate, not an adjacent control."
    )


def _learn_precise_locator_expand_ocr_bbox(
    bbox: dict[str, int],
    *,
    parent_bbox: dict[str, int],
    padding: int = 8,
) -> dict[str, int] | None:
    x1 = max(parent_bbox["x"], bbox["x"] - padding)
    y1 = max(parent_bbox["y"], bbox["y"] - padding)
    x2 = min(parent_bbox["x"] + parent_bbox["w"], bbox["x"] + bbox["w"] + padding)
    y2 = min(parent_bbox["y"] + parent_bbox["h"], bbox["y"] + bbox["h"] + padding)
    if x2 <= x1 or y2 <= y1:
        return None
    return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}


def _learn_precise_locator_evidence_candidates(
    target: dict[str, Any],
    *,
    all_targets: list[dict[str, Any]],
    evidence_context: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    locator_context = target.get("locator_context") if isinstance(target.get("locator_context"), dict) else {}
    parent_bbox = _normalize_map_bbox(locator_context.get("region_bbox"))
    if parent_bbox is None:
        return [], {
            "ocr": "not_available_parent_region_missing",
            "uia": "not_available_missing_binding_evidence",
            "visual": "not_available_parent_region_missing",
        }
    target_id = str(target.get("candidate_id") or "")
    target_label = _first_compact_text(target.get("label"), target_id)
    target_role = _first_compact_text(target.get("role"), "unknown")
    child_labels = [
        _first_compact_text(item)
        for item in _as_list(locator_context.get("child_labels"))
        if _first_compact_text(item)
    ]
    query_labels = [target_label, *child_labels]
    for part in re.split(r"[/|]", target_label):
        compact = _first_compact_text(part)
        if compact:
            query_labels.append(compact)

    candidates: list[dict[str, Any]] = []
    for sibling in all_targets:
        if str(sibling.get("candidate_id") or "") == target_id:
            continue
        sibling_context = sibling.get("locator_context") if isinstance(sibling.get("locator_context"), dict) else {}
        sibling_parent_bbox = _normalize_map_bbox(sibling_context.get("region_bbox"))
        sibling_bbox = _normalize_map_bbox(sibling.get("bbox"))
        if sibling_parent_bbox != parent_bbox or sibling_bbox is None:
            continue
        candidates.append(
            {
                "candidate_id": sibling.get("candidate_id"),
                "label": sibling.get("label"),
                "role": sibling.get("role"),
                "bbox": sibling_bbox,
                "click_point": sibling.get("click_point"),
                "confidence": sibling.get("confidence") or 0.5,
                "source": "same_region_visual_candidate",
                "freshness": "current_capture",
            }
        )

    context = evidence_context if isinstance(evidence_context, dict) else {}
    observe_result = context.get("observe_result") if isinstance(context.get("observe_result"), dict) else {}
    ocr_count = 0
    for index, text_item in enumerate(_as_list(observe_result.get("texts"))):
        if not isinstance(text_item, dict):
            continue
        text = _first_compact_text(text_item.get("text"))
        text_bbox = _normalize_map_bbox(text_item.get("bbox"))
        if not text or text_bbox is None or not _learn_precise_locator_bbox_inside_parent(text_bbox, parent_bbox):
            continue
        similarity = max((_learn_precise_locator_text_similarity(text, query) for query in query_labels), default=0.0)
        if similarity < 0.58:
            continue
        expanded_bbox = _learn_precise_locator_expand_ocr_bbox(text_bbox, parent_bbox=parent_bbox)
        if expanded_bbox is None:
            continue
        candidates.append(
            {
                "candidate_id": _first_compact_text(text_item.get("id"), f"ocr-{index}"),
                "label": text,
                "role": target_role,
                "bbox": expanded_bbox,
                "click_point": {
                    "x": expanded_bbox["x"] + expanded_bbox["w"] // 2,
                    "y": expanded_bbox["y"] + expanded_bbox["h"] // 2,
                },
                "confidence": float(text_item.get("confidence") or 0.0),
                "source": "ocr_anchor",
                "freshness": "current_capture",
                "evidence": {"text_similarity": round(similarity, 4), "raw_text_bbox": text_bbox},
            }
        )
        ocr_count += 1

    screen_map = context.get("screen_map") if isinstance(context.get("screen_map"), dict) else {}
    visual_count = 0
    for index, item in enumerate(_as_list(screen_map.get("candidates"))):
        if not isinstance(item, dict) or str(item.get("candidate_id") or "") == target_id:
            continue
        item_bbox = _normalize_map_bbox(item.get("bbox"))
        item_label = _first_compact_text(item.get("label"))
        if item_bbox is None or not _learn_precise_locator_bbox_inside_parent(item_bbox, parent_bbox):
            continue
        similarity = _learn_precise_locator_text_similarity(item_label, target_label)
        if similarity < 0.35:
            continue
        candidates.append(
            {
                "candidate_id": _first_compact_text(item.get("candidate_id"), f"visual-{index}"),
                "label": item_label,
                "role": _first_compact_text(item.get("role"), target_role),
                "bbox": item_bbox,
                "click_point": item.get("click_point"),
                "confidence": float(item.get("confidence") or 0.0),
                "source": _first_compact_text(item.get("source"), "observe_visual_candidate"),
                "freshness": "current_capture",
            }
        )
        visual_count += 1

    return candidates, {
        "ocr": "available" if ocr_count else "no_semantic_match",
        "uia": "not_available_missing_binding_evidence",
        "visual": "available" if (visual_count or candidates) else "no_semantic_match",
        "ocr_candidate_count": ocr_count,
        "visual_candidate_count": visual_count,
    }


def _apply_vista_coordinate_validation_to_learn_targets(
    targets: list[dict[str, Any]],
    *,
    image_path: str,
    image_size: dict[str, int],
    local_config: dict[str, Any],
    options: dict[str, Any],
    timeout_seconds: float,
    evidence_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not options.get("enabled"):
        return {
            "contract_version": "learn_vista_coordinate_validation_v1",
            "status": "disabled",
            "reason": options.get("reason") or "disabled",
            "validated_count": 0,
            "inside_count": 0,
            "outside_count": 0,
            "needs_review_count": 0,
            "skipped_count": len(targets),
            "results": [],
        }
    image_size_model = ImageSize(width=int(image_size.get("width") or 0), height=int(image_size.get("height") or 0))
    if image_size_model.width <= 0 or image_size_model.height <= 0:
        return {
            "contract_version": "learn_vista_coordinate_validation_v1",
            "status": "skipped",
            "reason": "image_size_unavailable",
            "validated_count": 0,
            "inside_count": 0,
            "outside_count": 0,
            "needs_review_count": 0,
            "skipped_count": len(targets),
            "results": [],
        }
    validate_all_targets = options.get("validate_all_targets") is True
    max_targets = len(targets) if validate_all_targets else max(0, int(options.get("max_targets") or 40))
    padding = max(0, int(options.get("padding") or 10))
    update_click_point = options.get("update_click_point", True) is not False
    per_target_timeout = max(1.0, float(options.get("per_target_timeout_seconds") or timeout_seconds))
    region_roi_padding = max(0, int(options.get("region_roi_padding") or 10))
    region_roi_max_edge = max(0, int(options.get("region_roi_max_edge") or 0))
    stop_on_failure = options.get("stop_on_failure", True) is not False
    use_numbered_overlay = options.get("use_numbered_overlay") is True
    results: list[dict[str, Any]] = []
    abort_reason: str | None = None
    validated_targets = targets[:max_targets]
    for index, target in enumerate(validated_targets, start=1):
        bbox = _normalize_map_bbox(target.get("bbox"))
        label = _first_compact_text(target.get("label"), target.get("candidate_id"))
        if not bbox or not label:
            result = {
                "contract_version": "learn_vista_target_coordinate_validation_v1",
                "status": "skipped",
                "reason": "missing_label_or_bbox",
                "candidate_id": target.get("candidate_id"),
                "label": label,
            }
            target["vista_coordinate_validation"] = result
            results.append(result)
            continue
        role = _first_compact_text(target.get("role"), "control")
        normalized_target_role = role.strip().casefold().replace("-", "_").replace(" ", "_")
        compact_direct_control = _learn_vista_is_compact_direct_control(bbox, target_role=role)
        target_uses_numbered_overlay = (
            use_numbered_overlay
            and normalized_target_role != "menu_item"
            and not compact_direct_control
        )
        goal = f"Click {label}"
        locator_prompt = " ".join(str(target.get("locator_prompt") or "").split())[:600]
        if compact_direct_control and use_numbered_overlay:
            prompt = _learn_vista_compact_control_prompt(label, role)
        else:
            prompt = locator_prompt or (
                f"Click {label}" if role in {"button", "link", "tab", "menu_item", "nav text action"} else f"Locate {label}"
            )
        try:
            locator_context = target.get("locator_context") if isinstance(target.get("locator_context"), dict) else {}
            region_bbox = _normalize_map_bbox(locator_context.get("region_bbox"))
            inference_path = Path(image_path)
            inference_size = image_size_model
            coordinate_transform = None
            image_preprocess = None
            inference_scope = "full_screen"
            inference_visual_source = "source_screenshot"
            numbered_overlay_text = str(target.get("numbered_overlay_path") or "").strip()
            visual_source_path = Path(image_path)
            if target_uses_numbered_overlay and numbered_overlay_text:
                numbered_overlay_path = Path(numbered_overlay_text)
                if not numbered_overlay_path.exists():
                    raise ValueError("numbered_overlay_path_missing")
                with Image.open(numbered_overlay_path) as numbered_image:
                    if numbered_image.size != (image_size_model.width, image_size_model.height):
                        raise ValueError("numbered_overlay_size_mismatch")
                visual_source_path = numbered_overlay_path
                inference_visual_source = "numbered_overlay"
            inference_bbox = region_bbox
            if use_numbered_overlay:
                inference_bbox = _learn_vista_target_context_bbox(
                    bbox,
                    parent_bbox=region_bbox
                    or {
                        "x": 0,
                        "y": 0,
                        "w": image_size_model.width,
                        "h": image_size_model.height,
                    },
                    target_role=role,
                )
            if inference_bbox is not None:
                if not _bbox_inside_image(inference_bbox, image_size):
                    raise ValueError("parent_region_bbox_outside_image")
                region_preprocess = _prepare_vista_region_roi_image(
                    visual_source_path,
                    image_size_model,
                    region_bbox=inference_bbox,
                    padding=region_roi_padding,
                    max_edge=region_roi_max_edge,
                )
                inference_path = Path(region_preprocess["processed_image_path"])
                processed_size = region_preprocess["processed_size"]
                inference_size = ImageSize(width=int(processed_size["width"]), height=int(processed_size["height"]))
                coordinate_transform = region_preprocess["transform"]
                image_preprocess = region_preprocess
                image_preprocess["numbered_overlay_source_path"] = (
                    str(visual_source_path) if inference_visual_source == "numbered_overlay" else ""
                )
                image_preprocess["coordinate_reference_image_path"] = str(Path(image_path))
                inference_scope = "target_context_roi" if use_numbered_overlay else "parent_region_roi"
            elif inference_visual_source == "numbered_overlay":
                inference_path = visual_source_path
            vista_payload = _call_vista_point_prompt(
                local_config=local_config,
                image_path=inference_path,
                goal=goal,
                prompt=prompt,
                image_size=inference_size,
                original_image_size=image_size_model,
                coordinate_transform=coordinate_transform,
                image_preprocess=image_preprocess,
                timeout_seconds=per_target_timeout,
                max_tokens=int(local_config.get("max_new_tokens") or 32),
                provider_name=f"{str(local_config.get('profile_id') or 'vista').strip()}_learn_coordinate_validation",
            )
            point = vista_payload["point"]
            inside = _point_inside_map_bbox(point, bbox, padding=padding)
            previous_point = _normalize_map_point(target.get("click_point"), bbox)
            precise_candidates, evidence_availability = _learn_precise_locator_evidence_candidates(
                target,
                all_targets=targets,
                evidence_context=evidence_context,
            )
            precise_evidence = build_precise_locator_evidence(
                capture_id=str(Path(image_path)),
                image_size=image_size,
                goal=goal,
                target={
                    "target_id": target.get("candidate_id"),
                    "label": label,
                    "role": role,
                    "parent_region_id": locator_context.get("region_label"),
                    "parent_region_bbox": region_bbox
                    or {
                        "x": 0,
                        "y": 0,
                        "w": int(image_size.get("width") or 0),
                        "h": int(image_size.get("height") or 0),
                    },
                },
                source_candidate={
                    "candidate_id": target.get("candidate_id"),
                    "label": label,
                    "role": role,
                    "bbox": bbox,
                    "click_point": previous_point,
                    "confidence": float(target.get("confidence") or 0.5),
                    "source": _first_compact_text(target.get("source"), "stage2_visual"),
                    "freshness": "current_capture",
                },
                evidence_candidates=precise_candidates,
                vista_point=point,
                mode="learn",
                numbered_overlay_used=inference_visual_source == "numbered_overlay",
            )
            precise_evidence["evidence_availability"] = evidence_availability
            selected_candidate = (
                precise_evidence.get("selected_candidate")
                if isinstance(precise_evidence.get("selected_candidate"), dict)
                else None
            )
            precise_gate = precise_evidence.get("dry_run_gate") if isinstance(precise_evidence.get("dry_run_gate"), dict) else {}
            precise_pass = precise_gate.get("status") == "locate_review_pass"
            if precise_pass and selected_candidate is not None and update_click_point:
                target["bbox"] = dict(selected_candidate["bbox"])
                target["click_point"] = point
                target["coordinate_source"] = "precise_locator_v1"
                target = _validate_learn_target_coordinates(target, image_size=image_size)
            result = {
                "contract_version": "learn_vista_target_coordinate_validation_v1",
                "status": "valid" if precise_pass else "needs_review",
                "candidate_id": target.get("candidate_id"),
                "label": label,
                "role": target.get("role"),
                "bbox": bbox,
                "previous_click_point": previous_point,
                "vista_point": point,
                "vista_point_inside_bbox": inside,
                "vista_point_inside_selected_bbox": bool(
                    selected_candidate and _point_inside_map_bbox(point, selected_candidate["bbox"], padding=0)
                ),
                "vista_instruction": prompt,
                "inference_scope": inference_scope,
                "inference_visual_source": inference_visual_source,
                "coordinate_transform": vista_payload.get("coordinate_transform"),
                "image_preprocess": vista_payload.get("image_preprocess"),
                "padding": padding,
                "updated_click_point": bool(precise_pass and selected_candidate is not None and update_click_point),
                "precise_locator_evidence": precise_evidence,
                "model_io": _vista_model_io_trace(vista_payload),
            }
        except Exception as exc:
            failure_category = _vista_validation_failure_category(exc)
            result = {
                "contract_version": "learn_vista_target_coordinate_validation_v1",
                "status": "failed",
                "candidate_id": target.get("candidate_id"),
                "label": label,
                "bbox": bbox,
                "error": str(exc),
                "model_io": _model_io_failure_payload(exc),
            }
            if failure_category:
                result["failure_category"] = failure_category
        target["vista_coordinate_validation"] = result
        results.append(result)
        if result.get("failure_category"):
            abort_reason = str(result["failure_category"])
            break
        if result.get("status") == "failed" and stop_on_failure:
            break
    skipped_count = max(0, len(targets) - len(results))
    inside_count = sum(1 for item in results if item.get("vista_point_inside_bbox") is True)
    outside_count = sum(1 for item in results if item.get("vista_point_inside_bbox") is False)
    needs_review_count = sum(1 for item in results if item.get("status") == "needs_review")
    failed_count = sum(1 for item in results if item.get("status") == "failed")
    precise_review_pass_count = sum(
        1
        for item in results
        if ((item.get("precise_locator_evidence") or {}).get("dry_run_gate") or {}).get("status") == "locate_review_pass"
    )
    return {
        "contract_version": "learn_vista_coordinate_validation_v1",
        "status": "blocked" if abort_reason else ("ready" if results and failed_count == 0 else ("partial" if results else "empty")),
        "grounding_profile_id": local_config.get("profile_id"),
        "grounding_model_family": local_config.get("model_family") or "VISTA",
        "model_name": local_config.get("model_name"),
        "output_contract": local_config.get("output_contract") or "vista_point_v1",
        "validated_count": len(results),
        "attempted_count": len(results),
        "inside_count": inside_count,
        "outside_count": outside_count,
        "needs_review_count": needs_review_count,
        "precise_review_pass_count": precise_review_pass_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "validation_scope": "all_targets" if validate_all_targets else "capped",
        "update_click_point": update_click_point,
        "padding": padding,
        "per_target_timeout_seconds": per_target_timeout,
        "stop_on_failure": stop_on_failure,
        "batch_aborted": abort_reason is not None,
        "abort_reason": abort_reason,
        "use_numbered_overlay": use_numbered_overlay,
        "interpretation": "dry-run locator evidence only; no click authorization and no action executed",
        "results": results,
    }


def _vista_validation_failure_category(exc: Exception) -> str | None:
    text = str(exc or "").casefold()
    if "model_busy" in text or "already processing another request" in text:
        return "model_busy"
    if "timed out" in text or "timeout" in text:
        return "request_timeout"
    if "failed to reach local vision endpoint" in text or "connection refused" in text:
        return "model_unreachable"
    if "http 502" in text or "http 503" in text or "http 504" in text:
        return "model_unavailable"
    return None


def _draw_learn_target_overlay_label(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    *,
    font: ImageFont.ImageFont,
    color: tuple[int, int, int],
) -> None:
    try:
        left, top, right, bottom = draw.textbbox((x, y), label, font=font)
        text_w = right - left
        text_h = bottom - top
    except Exception:
        text_w = max(8, len(label) * 7)
        text_h = 12
    y0 = max(0, y - text_h - 6)
    draw.rectangle((x, y0, x + text_w + 8, y0 + text_h + 5), fill=color)
    draw.text((x + 4, y0 + 2), label, fill=(255, 255, 255), font=font)


def _render_learn_all_targets_overlay(
    *,
    image_path: str,
    targets: list[dict[str, Any]],
    name_hint: str | None,
    review_boxes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    review_boxes = review_boxes or []
    source_image = Path(image_path)
    if not source_image.exists():
        return {
            "contract_version": "learn_target_coordinate_overlay_v1",
            "status": "skipped",
            "reason": "source_image_not_found",
            "target_count": len(targets),
            "review_box_count": len(review_boxes),
            "total_box_count": len(targets) + len(review_boxes),
        }

    base_image = source_image
    base_visual_source = "source_screenshot"
    base_overlay_path = ""
    numbered_overlay_paths = {
        str(Path(path_value).expanduser().resolve())
        for target in targets
        if (path_value := str(target.get("numbered_overlay_path") or "").strip())
        and Path(path_value).expanduser().exists()
    }
    if len(numbered_overlay_paths) == 1:
        candidate_base = Path(next(iter(numbered_overlay_paths)))
        try:
            with Image.open(source_image) as source_probe, Image.open(candidate_base) as overlay_probe:
                if source_probe.size == overlay_probe.size:
                    base_image = candidate_base
                    base_visual_source = "two_stage_numbered_overlay"
                    base_overlay_path = str(candidate_base.resolve())
        except Exception:
            base_image = source_image
    calibration_label_mode = (
        "failed_status_badges_only"
        if base_visual_source == "two_stage_numbered_overlay"
        else "full_status_labels"
    )

    output_path = build_review_overlay_path(name_hint=name_hint or source_image.stem, suffix="learn-target-coordinates")
    try:
        with Image.open(base_image) as image:
            annotated = image.convert("RGB")
            draw = ImageDraw.Draw(annotated)
            font = ImageFont.load_default()
            for index, target in enumerate(targets, start=1):
                validation = target.get("coordinate_validation") if isinstance(target.get("coordinate_validation"), dict) else {}
                calibration_only = target.get("calibration_only") is True
                vista_validation = target.get("vista_coordinate_validation") if isinstance(target.get("vista_coordinate_validation"), dict) else {}
                vista_status = str(vista_validation.get("status") or "not_attempted")
                if calibration_only:
                    color = (
                        (0, 170, 110)
                        if vista_status == "valid"
                        else ((215, 40, 40) if vista_status in {"failed", "needs_review"} else (24, 114, 204))
                    )
                else:
                    color = (0, 170, 110) if validation.get("status") == "valid" else (215, 40, 40)
                bbox = _normalize_map_bbox(target.get("bbox"))
                if not bbox:
                    continue
                rect = (bbox["x"], bbox["y"], bbox["x"] + bbox["w"], bbox["y"] + bbox["h"])
                draw.rectangle(rect, outline=color, width=4)
                point = (
                    _normalize_map_point(target.get("click_point"), bbox)
                    if not calibration_only or vista_status in {"valid", "needs_review"}
                    else None
                )
                if point:
                    px = int(point["x"])
                    py = int(point["y"])
                    draw.ellipse((px - 5, py - 5, px + 5, py + 5), fill=(0, 100, 255), outline=(255, 255, 255), width=2)
                if calibration_only:
                    status_label = {
                        "valid": "OK",
                        "needs_review": "R",
                        "failed": "F",
                    }.get(vista_status, "P")
                    if calibration_label_mode == "failed_status_badges_only":
                        label = status_label if vista_status == "failed" else ""
                    else:
                        label = f"C:{status_label}"
                else:
                    label = f"{index} {target.get('role') or 'control'} ({bbox['x']},{bbox['y']},{bbox['w']},{bbox['h']})"
                if label:
                    _draw_learn_target_overlay_label(draw, bbox["x"], bbox["y"], label, font=font, color=color)
            review_color = (217, 119, 6)
            for index, review_box in enumerate(review_boxes, start=1):
                bbox = _normalize_map_bbox(review_box.get("bbox"))
                if not bbox:
                    continue
                rect = (bbox["x"], bbox["y"], bbox["x"] + bbox["w"], bbox["y"] + bbox["h"])
                draw.rectangle(rect, outline=review_color, width=3)
                role = str(review_box.get("role") or "review")
                label = f"R{index}" if role in {"ocr_text_review_only", "nav_rail_icon_review_only"} else f"R{index} {role}"
                _draw_learn_target_overlay_label(draw, bbox["x"], bbox["y"], label, font=font, color=review_color)
            annotated.save(output_path)
    except Exception as exc:
        return {
            "contract_version": "learn_target_coordinate_overlay_v1",
            "status": "failed",
            "reason": f"overlay_render_failed: {exc}",
            "image_path": str(source_image),
            "target_count": len(targets),
            "review_box_count": len(review_boxes),
            "total_box_count": len(targets) + len(review_boxes),
        }

    return {
        "contract_version": "learn_target_coordinate_overlay_v1",
        "status": "ready",
        "image_path": str(source_image.resolve()),
        "output_path": str(output_path.resolve()),
        "base_visual_source": base_visual_source,
        "base_overlay_path": base_overlay_path,
        "final_fusion_overlay": base_visual_source == "two_stage_numbered_overlay",
        "calibration_label_mode": calibration_label_mode,
        "target_count": len(targets),
        "review_box_count": len(review_boxes),
        "total_box_count": len(targets) + len(review_boxes),
        "valid_count": sum(1 for item in targets if (item.get("coordinate_validation") or {}).get("status") == "valid"),
        "invalid_count": sum(1 for item in targets if (item.get("coordinate_validation") or {}).get("status") != "valid"),
        "model_validated_calibration_count": sum(
            1
            for item in targets
            if item.get("calibration_only") is True
            and (item.get("vista_coordinate_validation") or {}).get("status") == "valid"
        ),
        "model_review_calibration_count": sum(
            1
            for item in targets
            if item.get("calibration_only") is True
            and (item.get("vista_coordinate_validation") or {}).get("status") in {"needs_review", "failed"}
        ),
        "pending_calibration_count": sum(
            1
            for item in targets
            if item.get("calibration_only") is True
            and not isinstance(item.get("vista_coordinate_validation"), dict)
        ),
    }


def _learn_locate_model_review_enabled(request: VisionLocateTargetRequestModel, metadata: dict[str, Any]) -> bool:
    if request.learn_depth != "deep":
        return False
    return metadata.get("learn_locate_model_review", True) is not False and metadata.get("learn_deep_model_review", True) is not False


def _learn_locate_model_context(
    *,
    observe_reuse: dict[str, Any],
    screen_map: dict[str, Any],
    image_path: str,
    max_candidates: int,
    max_texts: int,
) -> dict[str, Any]:
    observe_result = observe_reuse.get("observe_result") if isinstance(observe_reuse.get("observe_result"), dict) else {}
    ocr_anchors = observe_reuse.get("ocr_anchors") if isinstance(observe_reuse.get("ocr_anchors"), dict) else {}
    return {
        "contract_version": "learn_locate_path_calibration_context_v1",
        "state_id": screen_map.get("state_id"),
        "app_name": screen_map.get("app_name"),
        "state_hint": screen_map.get("state_hint"),
        "image_path": image_path,
        "summary": screen_map.get("summary"),
        "sections": _compact_map_items(screen_map.get("sections"), limit=40),
        "candidates": _compact_map_items(screen_map.get("candidates"), limit=max_candidates),
        "ocr_texts": _compact_map_items(_screen_map_texts(observe_result), limit=max_texts),
        "ocr_anchor_count": ocr_anchors.get("anchor_count"),
        "uia": _compact_uia_for_learn_deep(observe_result),
        "required_review_actions": {
            "add_missing_nodes": True,
            "update_wrong_coordinates": True,
            "rename_mislabeled_nodes": True,
            "remove_duplicates_or_noise": True,
            "resolve_non_containment_overlaps": True,
            "overlap_rule": "Sibling path nodes must not overlap. Overlap is allowed only when one bbox contains the other as a parent-child relationship.",
        },
        "safety": {
            "coordinates_are_observation_only": True,
            "execution_requires_pre_click_decision_v1": True,
        },
    }


def _run_learn_locate_model_review(
    *,
    request: VisionLocateTargetRequestModel,
    observe_reuse: dict[str, Any],
    screen_map: dict[str, Any],
    image_path: str,
) -> dict[str, Any]:
    metadata = dict(request.metadata or {})
    if not _learn_locate_model_review_enabled(request, metadata):
        return {
            "contract_version": "learn_locate_model_review_v1",
            "status": "disabled",
            "reason": "disabled_by_depth_or_metadata",
        }
    if not image_path:
        return {
            "contract_version": "learn_locate_model_review_v1",
            "status": "skipped",
            "reason": "missing_image_path",
        }
    try:
        options = _learn_deep_model_options(request)
        config = VisionProviderFactory.load_config()
        provider_mode = str(options.get("provider_mode") or request.provider_mode or "local_grounding")
        local_config = _selected_local_vision_config(config, provider_mode)
        if _uses_vista_point_grounding(local_config):
            return {
                "contract_version": "learn_locate_model_review_v1",
                "status": "skipped",
                "reason": "vista_point_grounding_not_suitable_for_full_map_review",
                "provider_mode": provider_mode,
                "model_name": local_config.get("model_name"),
                "output_contract": local_config.get("output_contract") or "vista_point_v1",
                "fallback": "screen_map_candidate_coordinate_validation",
                "notes": [
                    "VISTA-4B is a single-point grounding model. Learn Deep full-map review uses deterministic screen_map coordinate validation unless a non-point review model is configured."
                ],
            }
        provider = VisionProviderFactory.create(mode=provider_mode, config=config)
        provider_response = provider.analyze(
            VisionAnalyzeRequest(
                image_path=image_path,
                task="learn_deep_review",
                app_name=request.app_name,
                goal="Calibrate the current PathGraph draft: add missing child nodes, fix wrong coordinates, rename mislabeled nodes, and remove duplicates. Do not execute actions.",
                state_hint=screen_map.get("state_hint") or request.state_hint,
                provider_mode=provider_mode,
                metadata={
                    "max_output_tokens": int(options.get("max_output_tokens") or 2048),
                    "learn_deep_review_context": _learn_locate_model_context(
                        observe_reuse=observe_reuse,
                        screen_map=screen_map,
                        image_path=image_path,
                        max_candidates=int(options.get("max_candidates") or 15),
                        max_texts=int(options.get("max_texts") or 20),
                    ),
                },
            )
        )
        model_json = _extract_provider_model_json(provider_response.raw_response)
        model_json = model_json if isinstance(model_json, dict) else {}
        return {
            "contract_version": "learn_locate_model_review_v1",
            "status": str(model_json.get("status") or "ready"),
            "provider": provider_response.provider,
            "provider_mode": provider_mode,
            "model_name": model_json.get("model_name") or model_json.get("provider") or provider_response.provider,
            "model_io": _model_io_trace(provider_response),
            "screen_summary": model_json.get("screen_summary") or provider_response.screen_summary,
            "state_guess": model_json.get("state_guess") or provider_response.state_guess,
            "candidate_decisions": _as_list(model_json.get("candidate_decisions")),
            "additions": _as_list(model_json.get("additions")),
            "removals": _as_list(model_json.get("removals")),
            "updates": _as_list(model_json.get("updates")),
            "notes": _as_list(model_json.get("notes")) or list(provider_response.notes),
        }
    except Exception as exc:
        return {
            "contract_version": "learn_locate_model_review_v1",
            "status": "failed",
            "error": str(exc),
            "provider_mode": str((request.provider_mode or "local_grounding")),
            "model_io": _model_io_failure_payload(exc),
            "fallback": "screen_map_candidate_coordinate_validation",
        }


def _apply_learn_locate_model_review_to_screen_map(
    *,
    screen_map: dict[str, Any],
    model_review: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    refined = dict(screen_map)
    candidates = [dict(item) for item in _as_list(refined.get("candidates")) if isinstance(item, dict)]
    if model_review.get("status") != "ready":
        refined_candidates, overlap_removals = _prune_non_containment_overlaps(candidates)
        refined["candidates"] = refined_candidates
        refined["summary"] = {
            **dict(refined.get("summary") if isinstance(refined.get("summary"), dict) else {}),
            "candidate_count": len(refined_candidates),
            "non_containment_overlap_removal_count": len(overlap_removals),
        }
        decisions = [
            {
                "candidate_id": removal.get("candidate_id"),
                "label": removal.get("label"),
                "action": "remove",
                "source": "path_graph_overlap_rule",
                "reasons": [removal.get("reason")],
                "kept_candidate_id": removal.get("kept_candidate_id"),
                "kept_label": removal.get("kept_label"),
            }
            for removal in overlap_removals
        ]
        return refined, {
            "contract_version": "learn_locate_path_calibration_delta_v1",
            "status": "ready" if overlap_removals else (model_review.get("status") or "skipped"),
            "summary": {
                "addition_count": 0,
                "removal_count": len(overlap_removals),
                "update_count": 0,
                "non_containment_overlap_removal_count": len(overlap_removals),
                "output_candidate_count": len(refined_candidates),
            },
            "additions": [],
            "removals": overlap_removals,
            "updates": [],
            "candidate_decisions": decisions,
        }

    existing_by_id = {str(item.get("candidate_id")): item for item in candidates if item.get("candidate_id")}
    remove_ids: set[str] = set()
    additions: list[dict[str, Any]] = []
    updates: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    review_items = [item for item in _as_list(model_review.get("candidate_decisions")) if isinstance(item, dict)]
    review_items.extend({"action": "remove", **item} for item in _as_list(model_review.get("removals")) if isinstance(item, dict))
    review_items.extend({"action": "add", "candidate": item} for item in _as_list(model_review.get("additions")) if isinstance(item, dict))
    review_items.extend({"action": "update", **item} for item in _as_list(model_review.get("updates")) if isinstance(item, dict))

    for index, item in enumerate(review_items):
        action = str(item.get("action") or "").strip().lower()
        candidate_id = str(item.get("candidate_id") or "").strip()
        reasons = [str(reason) for reason in _as_list(item.get("reasons") or item.get("reason")) if str(reason).strip()]
        if action == "remove" and candidate_id in existing_by_id and reasons:
            remove_ids.add(candidate_id)
            decisions.append({"candidate_id": candidate_id, "action": "remove", "source": "learn_locate_model_review", "reasons": reasons})
            continue
        if action == "add":
            candidate = _normalize_learn_deep_model_candidate(
                item.get("candidate") if isinstance(item.get("candidate"), dict) else item,
                index=index,
                screen_map=refined,
            )
            if candidate and not _deep_duplicate_candidate(candidate, candidates + additions):
                additions.append(candidate)
                decisions.append(
                    {
                        "candidate_id": candidate.get("candidate_id"),
                        "label": candidate.get("label"),
                        "action": "add",
                        "source": "learn_locate_model_review",
                        "reasons": reasons or ["model_identified_missing_child_node"],
                    }
                )
            continue
        if action == "update" and candidate_id in existing_by_id:
            update = _normalize_learn_deep_model_update(item, existing_by_id[candidate_id])
            if update:
                updates.append(update)
                existing_by_id[candidate_id].update(update["fields"])
                decisions.append(
                    {
                        "candidate_id": candidate_id,
                        "label": existing_by_id[candidate_id].get("label"),
                        "action": "update",
                        "source": "learn_locate_model_review",
                        "reasons": reasons or ["model_refined_child_node"],
                        "fields": sorted(update["fields"].keys()),
                    }
                )
            continue
        if action == "keep" and candidate_id in existing_by_id:
            decisions.append(
                {
                    "candidate_id": candidate_id,
                    "label": item.get("label") or existing_by_id[candidate_id].get("label"),
                    "action": "keep",
                    "source": "learn_locate_model_review",
                    "reasons": reasons or ["model_kept_child_node"],
                }
            )

    refined_candidates = [item for item in candidates if str(item.get("candidate_id") or "") not in remove_ids]
    refined_candidates.extend(additions)
    refined_candidates, overlap_removals = _prune_non_containment_overlaps(refined_candidates)
    refined["candidates"] = refined_candidates
    refined["summary"] = {
        **dict(refined.get("summary") if isinstance(refined.get("summary"), dict) else {}),
        "candidate_count": len(refined_candidates),
        "learn_locate_model_addition_count": len(additions),
        "learn_locate_model_removal_count": len(remove_ids),
        "learn_locate_model_update_count": len(updates),
        "non_containment_overlap_removal_count": len(overlap_removals),
    }
    for removal in overlap_removals:
        decisions.append(
            {
                "candidate_id": removal.get("candidate_id"),
                "label": removal.get("label"),
                "action": "remove",
                "source": "path_graph_overlap_rule",
                "reasons": [removal.get("reason")],
                "kept_candidate_id": removal.get("kept_candidate_id"),
                "kept_label": removal.get("kept_label"),
            }
        )
    return refined, {
        "contract_version": "learn_locate_path_calibration_delta_v1",
        "status": "ready",
        "summary": {
            "addition_count": len(additions),
            "removal_count": len(remove_ids) + len(overlap_removals),
            "update_count": len(updates),
            "non_containment_overlap_removal_count": len(overlap_removals),
            "output_candidate_count": len(refined_candidates),
        },
        "additions": additions,
        "removals": [
            {
                "candidate_id": candidate_id,
                "label": existing_by_id.get(candidate_id, {}).get("label"),
                "reason": "model_review_remove",
                "source": "learn_locate_model_review",
            }
            for candidate_id in sorted(remove_ids)
        ]
        + overlap_removals,
        "updates": updates,
        "candidate_decisions": decisions,
    }


def _learn_vista_target_ineligibility_reason(
    target: dict[str, Any],
    *,
    image_size: dict[str, int],
) -> str:
    """区分需要显示的审阅证据和适合点定位的目标。"""
    candidate_id = str(target.get("candidate_id") or "").strip().casefold()
    source = str(target.get("source") or "").strip().casefold()
    role = str(target.get("role") or "").strip().casefold().replace(" ", "_")
    bbox = _normalize_map_bbox(target.get("bbox"))
    if "partial_visible" in candidate_id or "partial_card" in source or "bottom_edge_partial" in source:
        return "partial_visible_review_only"
    if role in {"separator", "sidebar_review_region"}:
        return "structural_separator_review_only"
    if role in {"status_bar", "status_bar_evidence", "bottom_bar", "bottom_bar_evidence"}:
        return "structural_status_bar_review_only"
    if role in {"menu_bar", "menu_bar_evidence"}:
        return "structural_menu_bar_review_only"
    if bbox and (bbox["h"] <= 3 or bbox["w"] <= 3):
        return "structural_separator_review_only"
    if role in {
        "text",
        "readable",
        "label",
        "pane",
        "group",
        "message_card_content",
        "window_shell",
        "title_bar",
    }:
        return "non_actionable_semantic_evidence"
    label_text = str(target.get("label") or "").strip().casefold()
    if role in {"message_bubble", "group"} and any(token in label_text for token in ("list-filter", "list_filter", "filters", "筛选组")):
        return "semantic_container_review_only"
    image_height = int(image_size.get("height") or 0)
    if bbox and image_height > 0 and role in {"message_bubble", "list", "list_container"} and bbox["h"] >= int(image_height * 0.45):
        return "broad_container_review_only"
    if bbox and image_height > 0 and bbox["y"] + bbox["h"] >= image_height and bbox["h"] < max(24, int(image_height * 0.04)):
        return "partial_visible_review_only"
    return ""


def _build_learn_all_targets_from_screen_map(
    observe_reuse: dict[str, Any],
    *,
    image_path: str,
    vista_validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    screen_map = observe_reuse.get("screen_map") if isinstance(observe_reuse.get("screen_map"), dict) else {}
    image_size = _learn_target_image_size(image_path)
    raw_observe_candidates = [item for item in _as_list(screen_map.get("candidates")) if isinstance(item, dict)]
    raw_calibration_candidates = [
        item for item in _as_list(screen_map.get("calibration_candidates")) if isinstance(item, dict)
    ]
    authoritative_two_stage = bool(
        screen_map.get("two_stage_calibration_authoritative") and raw_calibration_candidates
    )
    raw_candidates = [] if authoritative_two_stage else raw_observe_candidates
    filtered_browser_chrome: list[dict[str, Any]] = []
    filtered_noise: list[dict[str, Any]] = []
    filtered_non_actionable: list[dict[str, Any]] = []
    filtered_blocked_review_only: list[dict[str, Any]] = []
    filtered_ungrounded: list[dict[str, Any]] = []
    filtered_calibration_browser_chrome: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for candidate in raw_candidates:
        if _learn_target_candidate_is_tiny_noise(candidate):
            filtered_noise.append(candidate)
            continue
        if _learn_target_candidate_is_browser_chrome(candidate, image_size=image_size, screen_map=screen_map):
            filtered_browser_chrome.append(candidate)
            continue
        if _learn_target_candidate_is_non_actionable_content(candidate):
            filtered_non_actionable.append(candidate)
            continue
        if _learn_target_candidate_is_blocked_review_only(candidate):
            filtered_blocked_review_only.append(candidate)
            continue
        if _learn_target_candidate_is_ungrounded_semantic_region(candidate):
            filtered_ungrounded.append(candidate)
            continue
        candidates.append(candidate)
    calibration_candidates: list[dict[str, Any]] = []
    for candidate in raw_calibration_candidates:
        if _learn_target_candidate_is_browser_chrome(candidate, image_size=image_size, screen_map=screen_map):
            filtered_calibration_browser_chrome.append(candidate)
            continue
        calibration_candidates.append(candidate)
    targets = [
        _validate_learn_target_coordinates(target, image_size=image_size)
        for index, candidate in enumerate(candidates)
        if (target := _screen_map_candidate_to_learn_target(candidate, index)) is not None
    ]
    calibration_targets = [
        _validate_learn_target_coordinates(target, image_size=image_size)
        for index, candidate in enumerate(calibration_candidates)
        if (target := _screen_map_calibration_candidate_to_target(candidate, index)) is not None
    ]
    review_boxes = [
        review_box
        for index, candidate in enumerate(filtered_non_actionable)
        if (review_box := _screen_map_candidate_to_learn_review_box(candidate, index, review_status="non_actionable_review_only")) is not None
    ]
    for index, candidate in enumerate(filtered_blocked_review_only):
        if _learn_blocked_candidate_should_be_suppressed_from_review(candidate):
            continue
        review_box = _screen_map_candidate_to_learn_review_box(candidate, index, review_status="blocked_review_only")
        if review_box is not None:
            review_boxes.append(review_box)
    review_box_keys = {
        f"{item.get('label')}|{item.get('bbox')}"
        for item in review_boxes
    }
    child_ids, child_box_keys = _learn_review_child_identity(review_boxes)
    observe_result = observe_reuse.get("observe_result") if isinstance(observe_reuse.get("observe_result"), dict) else {}
    if not authoritative_two_stage:
        for index, text_item in enumerate(_screen_map_texts(observe_result)):
            if not isinstance(text_item, dict):
                continue
            text_id = _first_compact_text(text_item.get("id"), text_item.get("text_id"))
            if text_id and text_id in child_ids:
                continue
            review_box = _ocr_text_to_learn_review_box(text_item, index)
            if review_box is None:
                continue
            key = f"{review_box.get('label')}|{review_box.get('bbox')}"
            if key in child_box_keys:
                continue
            if key in review_box_keys:
                continue
            review_box_keys.add(key)
            review_boxes.append(review_box)
            if len(review_boxes) >= 80:
                break
    if not authoritative_two_stage and _screen_map_has_side_navigation_region(screen_map):
        for review_box in _learn_nav_rail_review_boxes_from_image(image_path, existing_count=len(review_boxes)):
            key = f"{review_box.get('label')}|{review_box.get('bbox')}"
            if key in review_box_keys:
                continue
            review_box_keys.add(key)
            review_boxes.append(review_box)
            if len(review_boxes) >= 96:
                break
    targets, visual_overlap_removals = _prune_learn_target_visual_overlaps(targets)
    vista_summary = None
    if isinstance(vista_validation, dict):
        vista_options = vista_validation.get("options") if isinstance(vista_validation.get("options"), dict) else {"enabled": False}
        all_vista_targets = [*calibration_targets, *targets]
        vista_targets = all_vista_targets
        review_only_not_sent_to_vista: list[dict[str, Any]] = []
        if vista_options.get("enabled"):
            vista_targets = []
            for target in all_vista_targets:
                reason = _learn_vista_target_ineligibility_reason(target, image_size=image_size)
                if reason:
                    skipped = {
                        "contract_version": "learn_vista_target_coordinate_validation_v1",
                        "status": "skipped",
                        "reason": reason,
                        "candidate_id": target.get("candidate_id"),
                        "label": target.get("label"),
                        "role": target.get("role"),
                        "bbox": target.get("bbox"),
                    }
                    target["vista_coordinate_validation"] = skipped
                    review_only_not_sent_to_vista.append(skipped)
                    continue
                vista_targets.append(target)
        vista_summary = _apply_vista_coordinate_validation_to_learn_targets(
            vista_targets,
            image_path=image_path,
            image_size=image_size,
            local_config=vista_validation.get("local_config") if isinstance(vista_validation.get("local_config"), dict) else {},
            options=vista_options,
            timeout_seconds=float(vista_validation.get("timeout_seconds") or 600),
            evidence_context={
                "screen_map": screen_map,
                "observe_result": observe_result,
                "source_trace_path": observe_reuse.get("trace_path"),
            },
        )
        vista_summary = {
            **vista_summary,
            "display_target_count": len(all_vista_targets),
            "eligible_target_count": len(vista_targets),
            "review_only_not_sent_to_vista_count": len(review_only_not_sent_to_vista),
            "review_only_not_sent_to_vista": review_only_not_sent_to_vista,
            "interpretation": "VISTA validates locatable targets only; skipped review evidence remains visible in the fused overlay.",
        }
    overlay = _render_learn_all_targets_overlay(
        image_path=image_path,
        targets=[*targets, *calibration_targets],
        name_hint=f"{screen_map.get('state_id') or Path(image_path).stem}-learn-targets",
        review_boxes=review_boxes,
    )
    valid_count = sum(1 for item in targets if (item.get("coordinate_validation") or {}).get("status") == "valid")
    invalid_count = len(targets) - valid_count
    calibration_valid_count = sum(
        1 for item in calibration_targets if (item.get("coordinate_validation") or {}).get("status") == "valid"
    )
    vista_blocked = bool(isinstance(vista_summary, dict) and vista_summary.get("status") == "blocked")
    return {
        "contract_version": "learn_all_target_locations_v1",
        "status": "blocked" if vista_blocked else (
            "ready" if (targets or calibration_targets) and invalid_count == 0 else ("needs_review" if targets else "empty")
        ),
        "state_id": screen_map.get("state_id"),
        "source_trace_path": observe_reuse.get("trace_path"),
        "image_size": image_size,
        "raw_candidate_count": len(raw_observe_candidates),
        "raw_candidates_suppressed_by_authoritative_two_stage_count": (
            len(raw_observe_candidates) if authoritative_two_stage else 0
        ),
        "raw_calibration_candidate_count": len(raw_calibration_candidates),
        "filtered_browser_chrome_count": len(filtered_browser_chrome) + len(filtered_calibration_browser_chrome),
        "filtered_calibration_browser_chrome_count": len(filtered_calibration_browser_chrome),
        "filtered_noise_count": len(filtered_noise),
        "filtered_non_actionable_count": len(filtered_non_actionable),
        "filtered_blocked_review_only_count": len(filtered_blocked_review_only),
        "filtered_ungrounded_count": len(filtered_ungrounded),
        "target_count": len(targets),
        "calibration_target_count": len(calibration_targets),
        "calibration_valid_count": calibration_valid_count,
        "review_box_count": len(review_boxes),
        "validated_count": valid_count,
        "invalid_count": invalid_count,
        "visual_overlap_removal_count": len(visual_overlap_removals),
        "visual_overlap_removals": visual_overlap_removals,
        "overlay": overlay,
        "overlay_path": overlay.get("output_path") if overlay.get("status") == "ready" else None,
        "targets": targets,
        "calibration_targets": calibration_targets,
        "review_boxes": review_boxes,
        "vista_coordinate_validation": vista_summary,
    }


def _learn_all_targets_location_status(learn_all_targets: dict[str, Any]) -> str:
    """区分可执行定位目标和学习模式只读识别框。"""

    vista_validation = (
        learn_all_targets.get("vista_coordinate_validation")
        if isinstance(learn_all_targets.get("vista_coordinate_validation"), dict)
        else {}
    )
    if vista_validation.get("status") == "blocked" or vista_validation.get("batch_aborted") is True:
        return "learn_calibration_blocked"
    target_count = int(learn_all_targets.get("target_count") or 0)
    invalid_count = int(learn_all_targets.get("invalid_count") or 0)
    review_box_count = int(learn_all_targets.get("review_box_count") or 0)
    calibration_target_count = int(learn_all_targets.get("calibration_target_count") or 0)
    if target_count:
        return "learn_all_targets_ready" if invalid_count == 0 else "learn_all_targets_needs_review"
    if calibration_target_count:
        return "learn_calibration_targets_ready"
    if review_box_count > 0:
        return "learn_review_boxes_ready"
    return "not_located"


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
        operation_context = build_operation_runtime_context(
            request=request,
            skill_id="locate_element",
            semantic_action="locate_element",
            side_effect_class="read_only",
            requires_gate=False,
            capture_id=image_path,
            viewport_size=_image_size_payload(image_path=image_path, live_capture=live_capture),
            evidence_refs=[ref for ref in [image_path, request.observe_trace_path] if ref],
        )
        with timer.step("load_observe_trace_reuse", has_observe_trace=bool(request.observe_trace_path)):
            observe_reuse = _load_observe_trace_reuse(request.observe_trace_path, image_path=image_path, goal=request.goal)
        metadata = dict(request.metadata or {})
        observe_reuse = _attach_two_stage_calibration_candidates(
            observe_reuse,
            report_path_value=metadata.get("two_stage_report_path"),
            image_path=image_path,
        )
        if observe_reuse.get("status") == "ready":
            metadata["reused_ocr_anchors"] = observe_reuse["ocr_anchors"]
            metadata["reused_ocr_source_trace_path"] = observe_reuse["trace_path"]
            metadata["screen_map_context"] = {
                "state_id": observe_reuse.get("state_id"),
                "candidate_count": observe_reuse.get("candidate_count"),
                "source_trace_path": observe_reuse.get("trace_path"),
            }
        if _learn_all_targets_requested(request, metadata):
            vision_config = VisionProviderFactory.load_config()
            learn_grounding_mode = str(request.provider_mode or "local_grounding")
            learn_grounding_config = _selected_learning_grounding_config(vision_config, request)
            vista_validation_options = _learn_vista_coordinate_validation_options(request, learn_grounding_config)
            learn_locate_model_review: dict[str, Any] = {
                "contract_version": "learn_locate_model_review_v1",
                "status": "skipped",
                "reason": "not_requested",
            }
            learn_locate_delta: dict[str, Any] = {
                "contract_version": "learn_locate_path_calibration_delta_v1",
                "status": "skipped",
                "summary": {"addition_count": 0, "removal_count": 0, "update_count": 0},
                "additions": [],
                "removals": [],
                "updates": [],
                "candidate_decisions": [],
            }
            if isinstance(observe_reuse.get("screen_map"), dict):
                with timer.step("learn_locate_model_review", enabled=_learn_locate_model_review_enabled(request, metadata)):
                    learn_locate_model_review = _run_learn_locate_model_review(
                        request=request,
                        observe_reuse=observe_reuse,
                        screen_map=observe_reuse["screen_map"],
                        image_path=image_path,
                    )
                with timer.step("learn_locate_apply_model_review", status=learn_locate_model_review.get("status")):
                    refined_screen_map, learn_locate_delta = _apply_learn_locate_model_review_to_screen_map(
                        screen_map=observe_reuse["screen_map"],
                        model_review=learn_locate_model_review,
                    )
                    observe_reuse = {**observe_reuse, "screen_map": refined_screen_map, "candidate_count": len(refined_screen_map.get("candidates") or [])}
            with timer.step(
                "learn_all_targets_from_screen_map",
                candidate_count=observe_reuse.get("candidate_count"),
                vista_validation_enabled=bool(vista_validation_options.get("enabled")),
                vista_validation_max_targets=vista_validation_options.get("max_targets"),
            ):
                learn_all_targets = _build_learn_all_targets_from_screen_map(
                    observe_reuse,
                    image_path=image_path,
                    vista_validation={
                        "local_config": learn_grounding_config,
                        "options": vista_validation_options,
                        "timeout_seconds": float((vision_config.get("vision") or {}).get("timeout_seconds") or 600),
                    },
                )
            delta_summary = learn_locate_delta.get("summary") if isinstance(learn_locate_delta.get("summary"), dict) else {}
            locate_result = {
                "contract_version": "target_location_v1",
                **_mode_payload(request, fallback_contract="locate_target_v1"),
                "goal": request.goal,
                "image_path": image_path,
                "live_capture": live_capture,
                "recognition_plan": None,
                "pre_click_decision": None,
                "selected_click_point": None,
                "recommended_target": None,
                "located_bbox": None,
                "located_point": None,
                "location_status": _learn_all_targets_location_status(learn_all_targets),
                "learn_all_targets": learn_all_targets,
                "operation_context": operation_context,
                "operation_trace_link": operation_trace_link(operation_context, result_status="success", evidence_refs=[image_path]),
                "coordinate_overlay_path": learn_all_targets.get("overlay_path"),
                "coordinate_overlay": learn_all_targets.get("overlay"),
                "learn_locate_model_review": learn_locate_model_review,
                "learn_locate_path_delta": learn_locate_delta,
                "path_map_review": {
                    "contract_version": "path_map_review_v1",
                    "status": "ready",
                    "source": "learn_locate_model_review" if learn_locate_model_review.get("status") == "ready" else "screen_map_v1",
                    "review_source": "learn_locate_deep_calibration",
                    "summary": {
                        "addition_count": learn_all_targets["target_count"],
                        "calibration_target_count": learn_all_targets.get("calibration_target_count", 0),
                        "review_box_count": learn_all_targets.get("review_box_count", 0),
                        "review_only_overlay_ready": bool(learn_all_targets.get("review_box_count") and learn_all_targets.get("overlay_path")),
                        "validated_count": learn_all_targets.get("validated_count", 0),
                        "invalid_count": learn_all_targets.get("invalid_count", 0),
                        "coordinate_overlay_path": learn_all_targets.get("overlay_path"),
                        "model_addition_count": int(delta_summary.get("addition_count") or 0),
                        "model_removal_count": int(delta_summary.get("removal_count") or 0),
                        "model_update_count": int(delta_summary.get("update_count") or 0),
                        "removal_count": len(learn_locate_delta.get("removals") or []),
                        "update_count": len(learn_locate_delta.get("updates") or []),
                        "kept_count": 0,
                        "vista_validated_count": int((learn_all_targets.get("vista_coordinate_validation") or {}).get("validated_count") or 0),
                        "vista_inside_count": int((learn_all_targets.get("vista_coordinate_validation") or {}).get("inside_count") or 0),
                        "vista_outside_count": int((learn_all_targets.get("vista_coordinate_validation") or {}).get("outside_count") or 0),
                        "vista_needs_review_count": int((learn_all_targets.get("vista_coordinate_validation") or {}).get("needs_review_count") or 0),
                    },
                    "additions": learn_all_targets["targets"],
                    "calibration_targets": learn_all_targets.get("calibration_targets", []),
                    "removals": learn_locate_delta.get("removals") or [],
                    "updates": learn_locate_delta.get("updates") or [],
                    "kept": [],
                    "candidate_decisions": learn_locate_delta.get("candidate_decisions") or [],
                    "model_review": learn_locate_model_review,
                    "vista_coordinate_validation": learn_all_targets.get("vista_coordinate_validation"),
                },
                "observe_trace_reuse": {
                    key: value
                    for key, value in observe_reuse.items()
                    if key not in {"ocr_anchors", "screen_map", "observe_result"}
                },
                "execution_path": {
                    "action_executed": False,
                    "learn_all_targets_used": True,
                    "target_count": learn_all_targets["target_count"],
                    "calibration_target_count": learn_all_targets.get("calibration_target_count", 0),
                    "review_box_count": learn_all_targets.get("review_box_count", 0),
                    "review_only_overlay_ready": bool(learn_all_targets.get("review_box_count") and learn_all_targets.get("overlay_path")),
                    "coordinate_source": "screen_map_v1.candidates",
                    "ocr_anchor_reused_from_observe": observe_reuse.get("status") == "ready",
                    "ocr_anchor_reuse_source": observe_reuse.get("anchor_source"),
                    "ocr_anchor_reuse_trace_path": observe_reuse.get("trace_path") if observe_reuse.get("status") == "ready" else None,
                    "agent_must_call_for_click": "POST /action/execute_recognition_plan",
                },
            }
            locate_result["timings"] = timer.to_dict()
            locate_result["trace_path"] = _write_trace_if_enabled(
                request,
                category="vision",
                operation="locate_target",
                payload={"success": True, "request": request.model_dump(), "result": locate_result},
                name_hint=request.app_name or Path(image_path).stem,
            )
            data = VisionResultData(result=locate_result)
            return APIResponse(success=True, message="Learn targets located", data=data.model_dump(), error=None)
        plan_request = VisionRecognitionPlanRequestModel(
            image_path=image_path,
            task=request.task,
            app_name=request.app_name,
            goal=request.goal,
            state_hint=request.state_hint,
            provider_mode=request.provider_mode or "local_grounding",
            agent_mode=request.agent_mode,
            learn_depth=request.learn_depth,
            write_policy=request.write_policy,
            metadata={
                **metadata,
                "ocr_anchors": {"enabled": True, "max_anchors": "all", **dict(metadata.get("ocr_anchors") or {})}
                if isinstance(metadata.get("ocr_anchors"), dict)
                else metadata.get("ocr_anchors", {"enabled": True, "max_anchors": "all"}),
            },
            top_k=request.top_k,
            observe_trace_path=request.observe_trace_path,
            operation_context=operation_context,
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
        path_map_review = _build_path_map_review_from_locate(
            observe_reuse=observe_reuse,
            recognition_result=result,
            goal=request.goal,
            located_bbox=located_bbox,
            located_point=located_point,
        )
        locate_result = {
            "contract_version": "target_location_v1",
            **_mode_payload(request, fallback_contract="locate_target_v1"),
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
            "path_map_review": path_map_review,
            "operation_context": operation_context,
            "operation_trace_link": operation_trace_link(operation_context, result_status="success", evidence_refs=[image_path]),
            "observe_trace_reuse": {
                key: value
                for key, value in observe_reuse.items()
                if key not in {"ocr_anchors", "screen_map", "observe_result"}
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
        locate_result["trace_path"] = _write_trace_if_enabled(
            request,
            category="vision",
            operation="locate_target",
            payload={"success": True, "request": request.model_dump(), "result": locate_result},
            name_hint=request.app_name or Path(image_path).stem,
        )
        data = VisionResultData(result=locate_result)
        return APIResponse(success=True, message="Target located", data=data.model_dump(), error=None)
    except Exception as exc:
        timings = timer.to_dict()
        trace_path = _write_trace_if_enabled(
            request,
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


def _build_path_map_review_from_locate(
    *,
    observe_reuse: dict[str, Any],
    recognition_result: dict[str, Any],
    goal: str,
    located_bbox: dict[str, Any] | None,
    located_point: dict[str, Any] | None,
) -> dict[str, Any]:
    screen_map = observe_reuse.get("screen_map") if isinstance(observe_reuse.get("screen_map"), dict) else {}
    if observe_reuse.get("status") != "ready" or screen_map.get("contract_version") != "screen_map_v1":
        return {
            "contract_version": "path_map_review_v1",
            "status": "skipped",
            "reason": "observe_screen_map_unavailable",
            "additions": [],
            "removals": [],
            "kept": [],
        }

    sections = _as_list(screen_map.get("sections"))
    observed = [item for item in _as_list(screen_map.get("candidates")) if isinstance(item, dict)]
    ai_candidates = _locate_review_candidates(
        recognition_result,
        goal=goal,
        located_bbox=located_bbox,
        located_point=located_point,
    )
    additions: list[dict[str, Any]] = []
    removals: list[dict[str, Any]] = []
    kept: list[dict[str, Any]] = []

    matched_observed_ids: set[str] = set()
    for candidate in ai_candidates:
        match = _best_path_map_match(candidate, observed)
        if match:
            matched_observed_ids.add(str(match.get("candidate_id") or match.get("id") or ""))
            kept.append(
                {
                    "candidate_id": match.get("candidate_id") or match.get("id"),
                    "label": match.get("label"),
                    "reason": "matched_locate_ai_candidate",
                    "matched_label": candidate.get("label"),
                }
            )
            continue
        additions.append(_path_map_addition_from_locate_candidate(candidate, sections=sections, goal=goal))

    ai_label_keys = {_path_label_key(item.get("label")) for item in ai_candidates if _path_label_key(item.get("label"))}
    goal_key = _path_label_key(goal)
    for candidate in observed:
        candidate_id = str(candidate.get("candidate_id") or candidate.get("id") or "")
        if candidate_id and candidate_id in matched_observed_ids:
            continue
        label_key = _path_label_key(candidate.get("label"))
        same_target_label = bool(label_key and (label_key == goal_key or label_key in ai_label_keys))
        overlaps_ai_target = any(_path_bbox_conflicts(candidate, ai_candidate) for ai_candidate in ai_candidates)
        if not same_target_label and not overlaps_ai_target:
            continue
        removals.append(
            {
                "candidate_id": candidate.get("candidate_id") or candidate.get("id"),
                "label": candidate.get("label"),
                "bbox": candidate.get("bbox"),
                "source": candidate.get("source"),
                "reason": "same_label_or_overlap_replaced_by_locate_ai",
                "matched_goal": goal,
            }
        )

    return {
        "contract_version": "path_map_review_v1",
        "status": "ready",
        "review_source": "locate_target.recognition_plan",
        "source_trace_path": observe_reuse.get("trace_path"),
        "state_id": screen_map.get("state_id"),
        "goal": goal,
        "scope": "same_label_or_high_overlap_only",
        "summary": {
            "observed_candidate_count": len(observed),
            "ai_candidate_count": len(ai_candidates),
            "addition_count": len(additions),
            "removal_count": len(removals),
            "kept_count": len(kept),
        },
        "additions": additions,
        "removals": removals,
        "kept": kept,
    }


def _locate_review_candidates(
    recognition_result: dict[str, Any],
    *,
    goal: str,
    located_bbox: dict[str, Any] | None,
    located_point: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    recommended = recognition_result.get("recommended_target") if isinstance(recognition_result.get("recommended_target"), dict) else {}
    if recommended:
        candidates.append(_locate_review_candidate(recommended, source="recommended_target", fallback_label=goal, fallback_bbox=located_bbox, fallback_point=located_point))

    candidate_result = recognition_result.get("candidate_result") if isinstance(recognition_result.get("candidate_result"), dict) else {}
    for key in ("candidates", "rejected"):
        for item in _as_list(candidate_result.get(key)):
            if isinstance(item, dict):
                candidates.append(_locate_review_candidate(item, source=f"candidate_result.{key}", fallback_label=goal))

    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        label = _first_compact_text(candidate.get("label"))
        bbox = _normalize_map_bbox(candidate.get("bbox"))
        if not label or not bbox:
            continue
        key = f"{_path_label_key(label)}|{bbox['x']},{bbox['y']},{bbox['w']},{bbox['h']}"
        if key in seen:
            continue
        seen.add(key)
        candidate["bbox"] = bbox
        candidate["click_point"] = _normalize_map_point(candidate.get("click_point"), bbox)
        unique.append(candidate)
    return unique


def _locate_review_candidate(
    item: dict[str, Any],
    *,
    source: str,
    fallback_label: str,
    fallback_bbox: dict[str, Any] | None = None,
    fallback_point: dict[str, Any] | None = None,
) -> dict[str, Any]:
    element = item.get("element") if isinstance(item.get("element"), dict) else {}
    bbox = item.get("refined_bbox") or element.get("bbox") or item.get("bbox") or fallback_bbox
    point = element.get("click_point") or item.get("click_point") or fallback_point
    label = _first_compact_text(item.get("label"), element.get("label"), item.get("text"), item.get("name"), fallback_label)
    role = _first_compact_text(item.get("type"), item.get("role"), element.get("role"), "button")
    return {
        "candidate_id": item.get("candidate_id") or item.get("id"),
        "label": label,
        "role": role,
        "bbox": bbox,
        "click_point": point,
        "confidence": _bounded_float(item.get("confidence") or item.get("score")),
        "reason": _first_compact_text(item.get("reason"), item.get("purpose"), item.get("description")),
        "source": source,
    }


def _best_path_map_match(candidate: dict[str, Any], observed: list[dict[str, Any]]) -> dict[str, Any] | None:
    label_key = _path_label_key(candidate.get("label"))
    bbox = _normalize_map_bbox(candidate.get("bbox"))
    best: tuple[float, dict[str, Any]] | None = None
    for item in observed:
        item_bbox = _normalize_map_bbox(item.get("bbox"))
        label_score = _path_label_similarity(label_key, _path_label_key(item.get("label")))
        bbox_score = _path_bbox_similarity(bbox, item_bbox)
        label_and_position_match = label_score >= 0.85 and (bbox_score >= 0.35 or not bbox or not item_bbox)
        strong_spatial_match = bbox_score >= 0.65
        if not label_and_position_match and not strong_spatial_match:
            continue
        score = max(label_score, bbox_score) + min(label_score, bbox_score) * 0.25
        if best is None or score > best[0]:
            best = (score, item)
    return best[1] if best else None


def _path_map_addition_from_locate_candidate(candidate: dict[str, Any], *, sections: list[Any], goal: str) -> dict[str, Any]:
    bbox = _normalize_map_bbox(candidate.get("bbox"))
    point = _normalize_map_point(candidate.get("click_point"), bbox)
    label = _first_compact_text(candidate.get("label"), goal)
    role = _first_compact_text(candidate.get("role"), "button")
    source_id = candidate.get("candidate_id") or f"{label}|{bbox}"
    digest = hashlib.sha256(str(source_id).encode("utf-8", errors="ignore")).hexdigest()[:12]
    return {
        "contract_version": "screen_map_candidate_v1",
        "candidate_id": f"locate_review_{digest}",
        "label": label,
        "role": role,
        "bbox": bbox,
        "click_point": point,
        "confidence": candidate.get("confidence"),
        "section_id": _section_id_for_bbox(bbox, [section for section in sections if isinstance(section, dict)]),
        "source": "locate_path_review",
        "source_id": candidate.get("candidate_id"),
        "risk_class": "requires_user_confirmation",
        "expected_effect": f"precisely located during Locate for goal: {goal}"[:160],
        "evidence": {
            "path_map_review": True,
            "review_action": "add",
            "review_source": candidate.get("source"),
            "reason": candidate.get("reason"),
        },
    }


def _path_bbox_conflicts(observed: dict[str, Any], ai_candidate: dict[str, Any]) -> bool:
    observed_bbox = _normalize_map_bbox(observed.get("bbox"))
    ai_bbox = _normalize_map_bbox(ai_candidate.get("bbox"))
    if not observed_bbox or not ai_bbox:
        return False
    label_score = _path_label_similarity(_path_label_key(observed.get("label")), _path_label_key(ai_candidate.get("label")))
    overlap = _bbox_overlap_area(observed_bbox, ai_bbox)
    smaller = min(observed_bbox["w"] * observed_bbox["h"], ai_bbox["w"] * ai_bbox["h"])
    overlap_ratio = overlap / smaller if smaller > 0 else 0.0
    return overlap_ratio >= 0.72 and label_score < 0.45


def _path_bbox_similarity(a: dict[str, int] | None, b: dict[str, int] | None) -> float:
    if not a or not b:
        return 0.0
    overlap = _bbox_overlap_area(a, b)
    union = a["w"] * a["h"] + b["w"] * b["h"] - overlap
    iou = overlap / union if union > 0 else 0.0
    acx = a["x"] + a["w"] / 2
    acy = a["y"] + a["h"] / 2
    bcx = b["x"] + b["w"] / 2
    bcy = b["y"] + b["h"] / 2
    distance = ((acx - bcx) ** 2 + (acy - bcy) ** 2) ** 0.5
    max_size = max(a["w"], a["h"], b["w"], b["h"], 1)
    center_score = max(0.0, 1.0 - distance / max_size)
    return max(iou, center_score * 0.8)


def _path_label_key(value: Any) -> str:
    return "".join(char for char in str(value or "").casefold() if char.isalnum())


def _path_label_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if a in b or b in a:
        return min(len(a), len(b)) / max(len(a), len(b))
    return SequenceMatcher(None, a, b).ratio()


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
        goal = request.goal or request.task
        operation_context = build_operation_runtime_context(
            request=request,
            skill_id="locate_element",
            semantic_action="rank_candidates",
            side_effect_class="read_only",
            requires_gate=False,
            capture_id=str(image_path),
            viewport_size={"width": int(input_image_size.width), "height": int(input_image_size.height)},
            evidence_refs=[str(image_path), *([request.observe_trace_path] if request.observe_trace_path else [])],
        )
        with timer.step("load_observe_trace_reuse", has_observe_trace=bool(request.observe_trace_path)):
            observe_reuse = _load_observe_trace_reuse(request.observe_trace_path, image_path=str(image_path), goal=goal)
        with timer.step("path_graph_recall", observe_reuse_status=observe_reuse.get("status")):
            path_graph_recall = _build_path_graph_recall(
                observe_reuse=observe_reuse,
                goal=goal,
                top_k=request.top_k,
                image_size=input_image_size,
            )
        with timer.step("visual_asset_recall", observe_reuse_status=observe_reuse.get("status")):
            visual_asset_recall = _build_visual_asset_recall(
                metadata=request.metadata,
                observe_reuse=observe_reuse,
                image_path=image_path,
                image_size=input_image_size,
                goal=goal,
            )
        original_seeded_candidate = _seeded_candidate_payload(request.metadata)
        visual_asset_seeded_candidate = (
            visual_asset_recall.get("selected_candidate") if isinstance(visual_asset_recall, dict) else None
        )
        effective_seeded_candidate = original_seeded_candidate or (
            visual_asset_seeded_candidate if isinstance(visual_asset_seeded_candidate, dict) else None
        )
        recognition_metadata = dict(request.metadata or {})
        recognition_metadata["visual_asset_recall"] = visual_asset_recall
        if effective_seeded_candidate is not None and original_seeded_candidate is None:
            recognition_metadata["seeded_candidate_v1"] = effective_seeded_candidate
        if (
            original_seeded_candidate is None
            and isinstance(visual_asset_seeded_candidate, dict)
            and visual_asset_recall.get("fast_lane_allowed") is True
        ):
            reviewed_execution = dict(recognition_metadata.get("reviewed_test_execution") or {})
            reviewed_execution.update(
                {
                    "allow_seeded_candidate_without_model": True,
                    "allow_low_margin_when_grounded": True,
                    "source": "visual_asset_recall_v1",
                    "reason": "low_risk_visual_asset_current_capture_match",
                }
            )
            recognition_metadata["reviewed_test_execution"] = reviewed_execution
        effective_request_for_recognition = request.model_copy(update={"metadata": recognition_metadata})
        seeded_candidate = _seeded_candidate_payload(effective_request_for_recognition.metadata)
        local_config = _selected_local_vision_config(config, request.provider_mode)
        if _uses_vista_point_grounding(local_config):
            return _recognition_plan_from_vista_point(
                request=effective_request_for_recognition,
                timer=timer,
                config=config,
                local_config=local_config,
                image_path=image_path,
                input_image_size=input_image_size,
                goal=goal,
                observe_reuse=observe_reuse,
                path_graph_recall=path_graph_recall,
            )
        effective_metadata = dict(effective_request_for_recognition.metadata or {})
        if observe_reuse.get("status") == "ready":
            effective_metadata["reused_ocr_anchors"] = observe_reuse["ocr_anchors"]
            effective_metadata["reused_ocr_source_trace_path"] = observe_reuse["trace_path"]
            effective_metadata["screen_map_context"] = {
                "state_id": observe_reuse.get("state_id"),
                "candidate_count": observe_reuse.get("candidate_count"),
                "source_trace_path": observe_reuse.get("trace_path"),
            }
        if path_graph_recall.get("status") in {"ready", "empty"}:
            effective_metadata["path_graph_recall"] = path_graph_recall
        effective_request = effective_request_for_recognition.model_copy(update={"metadata": effective_metadata})
        with timer.step("prepare_ocr_anchors"):
            vision_request, ocr_result, ocr_anchor_payload, ocr_anchor_status = _recognition_vision_request_with_ocr_anchors(
                effective_request,
                image_path=image_path,
                image_size=input_image_size,
            )
        provider_failover_model_io: dict[str, Any] | None = None
        try:
            with timer.step("vision_provider_analyze", provider_mode=request.provider_mode):
                response = provider.analyze(vision_request)
        except Exception as exc:
            if not ocr_anchor_status.get("used"):
                raise
            provider_failover_model_io = _model_io_failure_payload(exc)
            ocr_anchor_status.update({"used": False, "fallback_used": True, "provider_error": str(exc)})
            ocr_anchor_payload = None
            with timer.step("vision_provider_analyze_without_ocr_anchors", provider_mode=request.provider_mode):
                response = provider.analyze(_vision_request_without_ocr_anchors(effective_request, image_path=image_path))
        with timer.step("ocr_region_refine"):
            response, refine_ocr_result, refine_options = _maybe_refine_with_ocr(response, request=effective_request, image_path=image_path)
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
        with timer.step("merge_path_graph_recall_candidates", recall_status=path_graph_recall.get("status")):
            if path_graph_recall.get("status") == "ready":
                candidate_result = _merge_path_graph_recall_candidates(
                    candidate_result,
                    path_graph_recall=path_graph_recall,
                    goal=goal,
                    top_k=request.top_k,
                )
        with timer.step("merge_seeded_candidate", seeded_candidate=seeded_candidate is not None):
            candidate_result = _merge_seeded_candidate(
                candidate_result,
                seeded_candidate=seeded_candidate,
                goal=goal,
                top_k=request.top_k,
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
            reviewed_execution = request.metadata.get("reviewed_test_execution") if isinstance(request.metadata, dict) else None
            allow_low_margin_when_grounded = bool(
                isinstance(reviewed_execution, dict)
                and reviewed_execution.get("allow_low_margin_when_grounded") is True
            )
            pre_click_decision = decide_pre_click(
                goal=goal,
                candidates=candidate_result,
                grounding=narrow_search_result,
                allow_low_margin_when_grounded=allow_low_margin_when_grounded,
            )
        recommended = candidate_result.candidates[0].to_dict() if candidate_result.candidates else None
        screen_inventory = screen_reading_payload.get("screen_inventory") if isinstance(screen_reading_payload.get("screen_inventory"), dict) else None
        result_payload = {
            "contract_version": "recognition_plan_v1",
            **_mode_payload(request, fallback_contract="recognition_plan_v1"),
            "image_path": str(image_path),
            "goal": goal,
            "top_k": request.top_k,
            "observe_trace_reuse": {
                key: value
                for key, value in observe_reuse.items()
                if key not in {"ocr_anchors", "screen_map"}
            },
            "path_graph_recall": path_graph_recall,
            "visual_asset_recall": visual_asset_recall,
            "seeded_candidate": seeded_candidate,
            "operation_context": operation_context,
            "operation_trace_link": operation_trace_link(operation_context, result_status="success", evidence_refs=[str(image_path)]),
            "candidate_freshness_decision": _candidate_freshness_decision_for_trace(
                seeded_candidate,
                image_path=image_path,
                image_size=input_image_size,
                grounding=narrow_search_result,
            ),
            "parse_result": {
                "vision_regions": normalized.to_dict(),
                "ocr_result": ocr_result.to_dict(),
                "ocr_anchors": ocr_anchor_payload,
                "page_structure": structure.to_dict(),
                "screen_reading": screen_reading_payload,
            },
            "screen_inventory": screen_inventory,
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
            "model_io": _model_io_trace(response),
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
                "ocr_anchor_reused_from_observe": observe_reuse.get("status") == "ready" and bool(ocr_anchor_status.get("reused")),
                "path_graph_recall_used": path_graph_recall.get("status") == "ready",
                "path_graph_recall_count": len(path_graph_recall.get("candidates") or []),
                "path_graph_recall_candidates_ranked": bool((candidate_result.summary or {}).get("path_graph_recall_used")),
                "path_graph_recall_selected_count": int((candidate_result.summary or {}).get("path_graph_recall_selected_count") or 0),
                "seeded_candidate_used": bool((candidate_result.summary or {}).get("seeded_candidate_used")),
                "seeded_candidate_selected": bool((candidate_result.summary or {}).get("seeded_candidate_selected")),
                "visual_asset_recall_used": visual_asset_recall.get("status") in {"matched", "no_match"},
                "visual_asset_recall_status": visual_asset_recall.get("status"),
                "visual_asset_fast_lane_used": bool(
                    visual_asset_recall.get("fast_lane_allowed")
                    and (candidate_result.summary or {}).get("seeded_candidate_selected")
                ),
                "state_match_status": (path_graph_recall.get("state_match") or {}).get("status"),
                "screen_reading_used": True,
                "screen_reading_rank_evidence_used": True,
                "screen_inventory_used": screen_inventory is not None,
                "screen_inventory_available_action_count": int(((screen_inventory or {}).get("summary") or {}).get("available_action_count") or 0),
                "screen_inventory_page_element_count": int(((screen_inventory or {}).get("summary") or {}).get("page_element_count") or 0),
                "screen_inventory_card_count": int(((screen_inventory or {}).get("summary") or {}).get("card_count") or 0),
                "uia_scan_status": uia_snapshot.get("status"),
                "narrow_search_used": True,
                "pre_click_decision_used": True,
                "reviewed_test_execution_used": allow_low_margin_when_grounded,
                "action_executed": False,
            },
        }
        if provider_failover_model_io is not None:
            result_payload["model_io_failovers"] = [provider_failover_model_io]
        result_payload["timings"] = timer.to_dict()
        result_payload["trace_path"] = _write_trace_if_enabled(
            request,
            category="vision",
            operation="recognition_plan",
            payload={"success": True, "request": request.model_dump(), "result": result_payload},
            name_hint=request.app_name or image_path.stem,
        )
        data = VisionResultData(result=result_payload)
        return APIResponse(success=True, message="Recognition plan completed", data=data.model_dump(), error=None)
    except Exception as exc:
        timings = timer.to_dict()
        model_io = _model_io_failure_payload(exc)
        failure_payload = {"success": False, "request": request.model_dump(), "error": str(exc), "timings": timings}
        if model_io is not None:
            failure_payload["model_io"] = model_io
        trace_path = _write_trace_if_enabled(
            request,
            category="vision",
            operation="recognition_plan",
            payload=failure_payload,
            name_hint=request.app_name or image_path.stem,
        )
        return APIResponse(
            success=False,
            message="Recognition plan failed",
            data={"trace_path": trace_path, "timings": timings, "model_io": model_io} if model_io is not None else {"trace_path": trace_path, "timings": timings},
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
