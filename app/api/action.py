from __future__ import annotations

import difflib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import APIRouter
from loguru import logger

from app.core.input_controller import input_controller
from app.core.ocr_engine import ocr_engine
from app.core.template_matcher import template_matcher
from app.core.verifier import verifier
from app.core.window_manager import window_manager
from app.models.request import ClickTemplateRequest, ClickTextRequest, ROIModel
from app.models.response import APIResponse, ActionResultData, ErrorModel

router = APIRouter(prefix="/action", tags=["action"])

OCR_NOISE_CHARS_PATTERN = re.compile(r"[\|`'\"‘’“”.,:_~\-]+")
WHITESPACE_PATTERN = re.compile(r"\s+")
CACHE_DIR = Path("logs/region-click-cache")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CASES_DIR = Path("logs/region-click-cases")
CASES_DIR.mkdir(parents=True, exist_ok=True)


RegionClickPanelLocator = Callable[[Any], dict[str, Any]]
RegionClickZoneResolver = Callable[[dict[str, Any]], dict[str, Any]]
RegionClickPointStrategy = Callable[[dict[str, Any], Optional[dict[str, float]]], list[dict[str, Any]]]
RegionClickValidator = Callable[[list[str], list[str]], dict[str, Any]]


def _normalize_text(value: str) -> str:
    text = (value or "").upper().strip()
    text = OCR_NOISE_CHARS_PATTERN.sub(" ", text)
    text = WHITESPACE_PATTERN.sub(" ", text).strip()
    text = text.replace(" ", "")
    return text


def _candidate_geometry(points: list[dict[str, Any]], roi_offset_x: int, roi_offset_y: int) -> Optional[dict[str, Any]]:
    if not points:
        return None
    xs = [int(point["x"]) for point in points if "x" in point]
    ys = [int(point["y"]) for point in points if "y" in point]
    if not xs or not ys:
        return None
    min_x = min(xs)
    max_x = max(xs)
    min_y = min(ys)
    max_y = max(ys)
    width = max_x - min_x
    height = max_y - min_y
    center_x = int(round((min_x + max_x) / 2))
    center_y = int(round((min_y + max_y) / 2))
    baseline_y = int(round(min_y + max(1, height) * 0.65))
    safe_padding_x = max(2, min(10, width // 6 if width > 0 else 2))
    safe_padding_y = max(2, min(8, height // 6 if height > 0 else 2))
    return {
        "box": {"min_x": min_x, "min_y": min_y, "max_x": max_x, "max_y": max_y, "width": width, "height": height, "center_x": center_x, "center_y": center_y, "baseline_y": baseline_y, "safe_padding_x": safe_padding_x, "safe_padding_y": safe_padding_y},
        "roi_point": {"x": center_x, "y": center_y},
        "window_point": {"x": center_x + roi_offset_x, "y": center_y + roi_offset_y},
        "baseline_window_point": {"x": center_x + roi_offset_x, "y": baseline_y + roi_offset_y},
        "points": points,
    }


def _evaluate_strategy(raw_text: str, target_text: str, normalized_text: str, normalized_target_text: str, partial_match: bool) -> tuple[Optional[str], float]:
    stripped_raw = (raw_text or "").strip()
    stripped_target = (target_text or "").strip()
    fuzzy_score = difflib.SequenceMatcher(None, normalized_text, normalized_target_text).ratio() if normalized_text and normalized_target_text else 0.0
    if stripped_raw == stripped_target:
        return "exact", fuzzy_score
    if normalized_text and normalized_target_text and normalized_text == normalized_target_text:
        return "normalized_exact", fuzzy_score
    if normalized_text and normalized_target_text and normalized_target_text in normalized_text:
        return "partial", fuzzy_score
    if partial_match and fuzzy_score >= 0.72:
        return "fuzzy", fuzzy_score
    return None, fuzzy_score


def _build_text_candidate(*, index: int, raw_text: str, points: list[dict[str, Any]], confidence: Optional[float], target_text: str, normalized_target_text: str, allow_partial_fallback: bool, roi_offset_x: int, roi_offset_y: int, source: str = "ocr_line", window_height: Optional[int] = None) -> Optional[dict[str, Any]]:
    normalized = raw_text.strip()
    if not normalized or not points:
        return None
    normalized_text = _normalize_text(normalized)
    strategy, fuzzy_score = _evaluate_strategy(raw_text=normalized, target_text=target_text, normalized_text=normalized_text, normalized_target_text=normalized_target_text, partial_match=allow_partial_fallback)
    if strategy is None:
        return None
    geometry = _candidate_geometry(points, roi_offset_x=roi_offset_x, roi_offset_y=roi_offset_y)
    if geometry is None:
        return None
    box = geometry["box"]
    confidence_value = float(confidence) if confidence is not None else 0.0
    area = max(1, box["width"] * box["height"])
    area_score = min(area / 2500.0, 3.0)
    nav_band_score = 0.0
    if window_height:
        nav_band_score = max(0.0, 1.0 - (box["center_y"] / max(1, window_height * 0.25)))
    strategy_bonus = {"exact": 3000.0, "normalized_exact": 2200.0, "partial": 1400.0, "fuzzy": 900.0}[strategy]
    score = strategy_bonus + confidence_value * 100.0 + fuzzy_score * 100.0 + area_score * 10.0 + nav_band_score * 20.0
    return {"index": index, "text": normalized, "normalized_text": normalized_text, "confidence": confidence, "match_strategy": strategy, "fuzzy_score": fuzzy_score, "area": area, "nav_band_score": nav_band_score, "exact_match": strategy == "exact", "normalized_exact_match": strategy == "normalized_exact", "partial_match": strategy == "partial", "fuzzy_match": strategy == "fuzzy", "score": score, "source": source, **geometry}


def _merge_adjacent_lines(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        text = str(line.get("text", "")).strip()
        points = line.get("points") or []
        if not text or not points:
            continue
        xs = [int(point["x"]) for point in points if "x" in point]
        ys = [int(point["y"]) for point in points if "y" in point]
        if not xs or not ys:
            continue
        prepared.append({"index": index, "text": text, "confidence": line.get("confidence"), "points": points, "min_x": min(xs), "max_x": max(xs), "min_y": min(ys), "max_y": max(ys), "center_y": (min(ys) + max(ys)) / 2.0, "height": max(1, max(ys) - min(ys))})
    prepared.sort(key=lambda item: (item["min_y"], item["min_x"]))
    merged: list[dict[str, Any]] = []
    for item in prepared:
        if not merged:
            merged.append(item)
            continue
        previous = merged[-1]
        vertical_gap = item["min_y"] - previous["max_y"]
        same_band = abs(item["center_y"] - previous["center_y"]) <= max(previous["height"], item["height"], 24)
        close_vertical = vertical_gap <= max(previous["height"], item["height"], 24)
        if same_band or close_vertical:
            previous["text"] = f"{previous['text']} {item['text']}".strip()
            previous["points"] = previous["points"] + item["points"]
            previous["min_x"] = min(previous["min_x"], item["min_x"])
            previous["max_x"] = max(previous["max_x"], item["max_x"])
            previous["min_y"] = min(previous["min_y"], item["min_y"])
            previous["max_y"] = max(previous["max_y"], item["max_y"])
            previous["center_y"] = (previous["min_y"] + previous["max_y"]) / 2.0
            previous["height"] = max(1, previous["max_y"] - previous["min_y"])
            confidences = [value for value in [previous.get("confidence"), item.get("confidence")] if value is not None]
            previous["confidence"] = sum(confidences) / len(confidences) if confidences else None
        else:
            merged.append(item)
    return merged


def _to_roi_model(value: Optional[dict[str, Any] | ROIModel]) -> Optional[ROIModel]:
    if value is None:
        return None
    if isinstance(value, ROIModel):
        return value
    return ROIModel(**value)


def _extract_numeric_texts(texts: list[str]) -> list[str]:
    return sorted([text for text in texts if text.strip().isdigit()])


def _window_rect(bound: Any) -> dict[str, int]:
    left = int(bound.rect.left)
    top = int(bound.rect.top)
    right = int(bound.rect.right)
    bottom = int(bound.rect.bottom)
    return {"left": left, "top": top, "width": right - left, "height": bottom - top}


def _window_size_bucket(rect: dict[str, int]) -> str:
    return f"{rect['width']}x{rect['height']}"


def _locate_mouse_tester_panel(bound: Any) -> dict[str, Any]:
    rect = _window_rect(bound)
    return {"x": int(rect["width"] * 0.16), "y": int(rect["height"] * 0.48), "width": int(rect["width"] * 0.48), "height": int(rect["height"] * 0.40), "source": "window_relative_fixed_roi"}


def _derive_left_button_zone(panel: dict[str, Any]) -> dict[str, Any]:
    return {"x": int(panel["x"] + panel["width"] * 0.10), "y": int(panel["y"] + panel["height"] * 0.15), "width": int(panel["width"] * 0.35), "height": int(panel["height"] * 0.40), "source": "panel_relative_left_button_zone"}


def _generate_zone_points(zone: dict[str, Any], preferred_norm_point: Optional[dict[str, float]] = None) -> list[dict[str, Any]]:
    inset_x = max(8, int(zone["width"] * 0.18))
    inset_y = max(8, int(zone["height"] * 0.18))
    left = zone["x"] + inset_x
    right = zone["x"] + zone["width"] - inset_x
    top = zone["y"] + inset_y
    bottom = zone["y"] + zone["height"] - inset_y
    mid_x = int(round((left + right) / 2))
    mid_y = int(round((top + bottom) / 2))
    points = [
        {"x": left, "y": top, "label": "top_left"},
        {"x": mid_x, "y": top, "label": "top_center"},
        {"x": right, "y": top, "label": "top_right"},
        {"x": left, "y": mid_y, "label": "center_left"},
        {"x": mid_x, "y": mid_y, "label": "center"},
        {"x": right, "y": mid_y, "label": "center_right"},
        {"x": left, "y": bottom, "label": "bottom_left"},
        {"x": mid_x, "y": bottom, "label": "bottom_center"},
        {"x": right, "y": bottom, "label": "bottom_right"},
    ]
    if preferred_norm_point is not None:
        px = int(zone["x"] + zone["width"] * preferred_norm_point["nx"])
        py = int(zone["y"] + zone["height"] * preferred_norm_point["ny"])
        preferred = {"x": px, "y": py, "label": "preferred_cached_point"}
        points = [preferred] + [point for point in points if point["x"] != preferred["x"] or point["y"] != preferred["y"]]
    return points


def _counter_value(texts: list[str]) -> Optional[int]:
    values = []
    for text in texts:
        text = text.strip()
        if text.isdigit():
            try:
                values.append(int(text))
            except ValueError:
                pass
    if not values:
        return None
    return min(values)


def _evaluate_counter_result(before_numeric_texts: list[str], after_numeric_texts: list[str]) -> dict[str, Any]:
    before_val = _counter_value(before_numeric_texts)
    after_val = _counter_value(after_numeric_texts)
    strict_success = before_val is not None and after_val is not None and after_val > before_val
    weak_success = before_numeric_texts != after_numeric_texts
    return {"target_counter_before": before_val, "target_counter_after": after_val, "strict_success": strict_success, "weak_success": weak_success, "counter_changed": weak_success}


def _normalized_point(zone: dict[str, Any], point: dict[str, Any]) -> dict[str, float]:
    return {"nx": round((point["x"] - zone["x"]) / max(1, zone["width"]), 4), "ny": round((point["y"] - zone["y"]) / max(1, zone["height"]), 4)}


def _load_region_click_memory(case_name: str, bucket: str) -> Optional[dict[str, Any]]:
    path = CACHE_DIR / f"{case_name}-{bucket}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _save_region_click_memory(case_name: str, bucket: str, payload: dict[str, Any]) -> str:
    path = CACHE_DIR / f"{case_name}-{bucket}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return str(path.resolve())


def _save_region_click_case(case_name: str, payload: dict[str, Any]) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = CASES_DIR / f"{case_name}-{timestamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return str(path.resolve())


def _run_region_click(
    *,
    case_name: str,
    bound: Any,
    panel_locator: RegionClickPanelLocator,
    zone_resolver: RegionClickZoneResolver,
    point_strategy: RegionClickPointStrategy,
    validator: RegionClickValidator,
    settle_ms: int = 120,
    hold_ms: int = 70,
) -> dict[str, Any]:
    window_rect = _window_rect(bound)
    bucket = _window_size_bucket(window_rect)
    memory = _load_region_click_memory(case_name, bucket)
    panel = panel_locator(bound)
    zone = zone_resolver(panel)
    points = point_strategy(zone, memory.get("successful_point_norm") if memory else None)
    counter_roi = ROIModel(x=zone["x"], y=zone["y"], width=max(zone["width"], 220), height=max(zone["height"], 170))

    before_ocr = ocr_engine.ocr_region(counter_roi, save_image=True, debug=False)
    before_texts = [str(line.get("text", "")).strip() for line in (before_ocr.get("lines", []) or []) if str(line.get("text", "")).strip()]
    before_numeric_texts = _extract_numeric_texts(before_texts)

    logger.info("region_click case={} panel rect: {}", case_name, panel)
    logger.info("region_click case={} zone rect: {}", case_name, zone)
    logger.info("region_click case={} points: {}", case_name, points)
    logger.info("region_click case={} before counter texts: {}", case_name, before_numeric_texts)

    retries: list[dict[str, Any]] = []
    for idx, point in enumerate(points):
        before_state = verifier.capture_pre_action_state(roi=counter_roi)
        click_result = input_controller.click_point(point["x"], point["y"], move_before_click=True, settle_ms=settle_ms, hold_ms=hold_ms)
        verification = verifier.verify_action(case_name, roi=counter_roi, before_state=before_state, click_result=click_result)
        after_ocr = ocr_engine.ocr_region(counter_roi, save_image=True, debug=False)
        after_texts = [str(line.get("text", "")).strip() for line in (after_ocr.get("lines", []) or []) if str(line.get("text", "")).strip()]
        after_numeric_texts = _extract_numeric_texts(after_texts)
        counter_eval = validator(before_numeric_texts, after_numeric_texts)
        retry = {
            "attempt_index": idx,
            "point": point,
            "point_norm": _normalized_point(zone, point),
            "click": click_result,
            "verification": verification,
            "before_numeric_texts": before_numeric_texts,
            "after_numeric_texts": after_numeric_texts,
            **counter_eval,
        }
        retries.append(retry)
        logger.info("region_click case={} attempt: {}", case_name, retry)

        if counter_eval["weak_success"]:
            memory_payload = {
                "case": case_name,
                "window_size_bucket": bucket,
                "panel_rect": panel,
                "zone_rect": zone,
                "successful_point_norm": retry["point_norm"],
                "successful_attempt_index": idx,
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
            memory_path = _save_region_click_memory(case_name, bucket, memory_payload)
            case_payload = {
                "case": case_name,
                "window_rect": window_rect,
                "panel_rect": panel,
                "zone_rect": zone,
                "successful_point": point,
                "successful_point_norm": retry["point_norm"],
                "before_numeric_texts": before_numeric_texts,
                "after_numeric_texts": after_numeric_texts,
                **counter_eval,
                "retries": [{k: v for k, v in r.items() if k not in {"click", "verification"}} for r in retries],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            case_path = _save_region_click_case(case_name, case_payload)
            return {
                "success": True,
                "panel": panel,
                "zone": zone,
                "successful_point": point,
                "click": click_result,
                "verification": verification,
                "before_numeric_texts": before_numeric_texts,
                "after_numeric_texts": after_numeric_texts,
                **counter_eval,
                "retries": retries,
                "memory_path": memory_path,
                "case_path": case_path,
            }

    return {
        "success": False,
        "panel": panel,
        "zone": zone,
        "points": points,
        "before_numeric_texts": before_numeric_texts,
        "retries": retries,
    }


@router.post("/click_template", response_model=APIResponse)
def click_template(request: ClickTemplateRequest) -> APIResponse:
    template_result = template_matcher.find_template(request.name, request.roi)
    click_result = input_controller.click_point(0, 0)
    verification = verifier.verify_action("click_template") if request.enable_validation else {"verified": None}
    data = ActionResultData(action="click_template", result={"template": template_result, "click": click_result, "verification": verification})
    return APIResponse(success=True, message="Template click attempted", data=data.model_dump(), error=None)


@router.post("/click_mouse_tester_left_region", response_model=APIResponse)
def click_mouse_tester_left_region() -> APIResponse:
    bound = window_manager.get_bound_window()
    if bound is None:
        return APIResponse(success=False, message="No bound window is currently available", data=None, error=ErrorModel(code="no_bound_window", details="Bind a MouseTester window before calling /action/click_mouse_tester_left_region"))

    try:
        result = _run_region_click(
            case_name="click_mouse_tester_left_region",
            bound=bound,
            panel_locator=_locate_mouse_tester_panel,
            zone_resolver=_derive_left_button_zone,
            point_strategy=_generate_zone_points,
            validator=_evaluate_counter_result,
        )
    except Exception as exc:
        return APIResponse(success=False, message="Region click execution failed", data=None, error=ErrorModel(code="region_click_failed", details=str(exc)))

    if not result["success"]:
        return APIResponse(success=False, message="MouseTester left region click did not change the counter", data=result, error=ErrorModel(code="counter_not_changed", details="No region sample point changed the target counter"))

    data = ActionResultData(action="click_mouse_tester_left_region", result=result)
    return APIResponse(success=True, message="MouseTester left region clicked successfully", data=data.model_dump(), error=None)


@router.post("/click_text", response_model=APIResponse)
def click_text(request: ClickTextRequest) -> APIResponse:
    bound = window_manager.get_bound_window()
    if bound is None:
        return APIResponse(success=False, message="No bound window is currently available", data=None, error=ErrorModel(code="no_bound_window", details="Bind a window before calling /action/click_text"))

    roi_model = _to_roi_model(request.roi)
    try:
        ocr_result = ocr_engine.ocr_region(request.roi, save_image=True, debug=True)
    except ValueError as exc:
        return APIResponse(success=False, message="OCR failed for click_text", data=None, error=ErrorModel(code="ocr_failed", details=str(exc)))
    except RuntimeError as exc:
        return APIResponse(success=False, message="OCR backend unavailable", data=None, error=ErrorModel(code="ocr_backend_unavailable", details=str(exc)))

    lines = ocr_result.get("lines", []) or []
    raw_ocr_texts = [str(line.get("text", "")).strip() for line in lines if str(line.get("text", "")).strip()]
    normalized_ocr_texts = [_normalize_text(text) for text in raw_ocr_texts]
    target_text = request.text.strip()
    normalized_target_text = _normalize_text(target_text)
    logger.info("click_text target text: {!r}", request.text)
    logger.info("click_text raw OCR texts: {}", raw_ocr_texts)
    logger.info("click_text normalized OCR texts: {}", normalized_ocr_texts)
    logger.info("click_text normalized target text: {}", normalized_target_text)

    if not raw_ocr_texts:
        return APIResponse(success=False, message="OCR returned no visible text", data={"matched_text": None, "clicked_point": None, "roi": ocr_result.get("roi"), "image_path": ocr_result.get("image_path"), "confidence": ocr_result.get("confidence"), "candidates": [], "raw_ocr_texts": [], "normalized_ocr_texts": [], "normalized_target_text": normalized_target_text}, error=ErrorModel(code="ocr_no_text", details="OCR completed but returned no recognized text"))

    roi_info = ocr_result.get("roi") or None
    roi_offset_x = int(roi_info.get("x", 0)) if isinstance(roi_info, dict) else 0
    roi_offset_y = int(roi_info.get("y", 0)) if isinstance(roi_info, dict) else 0
    window_size = ocr_result.get("debug", {}).get("window_size") or {}
    bound_height = int(window_size.get("height", max(1, bound.rect.bottom - bound.rect.top)))
    allow_partial_fallback = True

    candidates: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        candidate = _build_text_candidate(index=index, raw_text=str(line.get("text", "")).strip(), points=line.get("points") or [], confidence=line.get("confidence"), target_text=target_text, normalized_target_text=normalized_target_text, allow_partial_fallback=allow_partial_fallback, roi_offset_x=roi_offset_x, roi_offset_y=roi_offset_y, source="ocr_line", window_height=bound_height)
        if candidate is not None:
            candidates.append(candidate)
    merged_lines = _merge_adjacent_lines(lines)
    merged_texts = [item["text"] for item in merged_lines]
    normalized_merged_texts = [_normalize_text(text) for text in merged_texts]
    logger.info("click_text merged OCR texts: {}", merged_texts)
    logger.info("click_text normalized merged OCR texts: {}", normalized_merged_texts)
    for merged_index, merged in enumerate(merged_lines):
        candidate = _build_text_candidate(index=10000 + merged_index, raw_text=merged["text"], points=merged["points"], confidence=merged.get("confidence"), target_text=target_text, normalized_target_text=normalized_target_text, allow_partial_fallback=allow_partial_fallback, roi_offset_x=roi_offset_x, roi_offset_y=roi_offset_y, source="merged_lines", window_height=bound_height)
        if candidate is not None:
            candidates.append(candidate)
    logger.info("click_text candidate count: {}", len(candidates))
    logger.info("click_text candidates (scored): {}", candidates)
    if not candidates:
        return APIResponse(success=False, message="Target text not found in OCR results", data={"matched_text": None, "clicked_point": None, "roi": ocr_result.get("roi"), "image_path": ocr_result.get("image_path"), "confidence": ocr_result.get("confidence"), "candidates": [], "raw_ocr_texts": raw_ocr_texts, "normalized_ocr_texts": normalized_ocr_texts, "merged_ocr_texts": merged_texts, "normalized_merged_ocr_texts": normalized_merged_texts, "normalized_target_text": normalized_target_text}, error=ErrorModel(code="target_text_not_found", details={"target": request.text, "partial_match": request.partial_match}))
    strategy_rank = {"exact": 0, "normalized_exact": 1, "partial": 2, "fuzzy": 3}
    candidates.sort(key=lambda item: (strategy_rank.get(item["match_strategy"], 99), -item["score"], item["index"]))
    selected = candidates[0]
    click_result = input_controller.click_point(selected["window_point"]["x"], selected["window_point"]["y"], move_before_click=True, settle_ms=100, hold_ms=70)
    verification = verifier.verify_action("click_text", roi=roi_model, before_state=verifier.capture_pre_action_state(roi=roi_model) if request.enable_validation else None, click_result=click_result) if request.enable_validation else {"verified": None}
    data = ActionResultData(action="click_text", result={"matched_text": selected.get("text"), "normalized_matched_text": selected.get("normalized_text"), "match_strategy": selected.get("match_strategy"), "clicked_point": click_result.get("window_point"), "roi": ocr_result.get("roi"), "image_path": ocr_result.get("image_path"), "confidence": selected.get("confidence"), "candidates": candidates, "raw_ocr_texts": raw_ocr_texts, "normalized_ocr_texts": normalized_ocr_texts, "merged_ocr_texts": merged_texts, "normalized_merged_ocr_texts": normalized_merged_texts, "normalized_target_text": normalized_target_text, "ocr": ocr_result, "click": click_result, "verification": verification})
    return APIResponse(success=True, message="Text matched and clicked", data=data.model_dump(), error=None)
