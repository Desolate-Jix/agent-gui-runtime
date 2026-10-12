"""把本帧模型几何转换为既有识别合同，不读取控件、不执行输入。"""
from __future__ import annotations

import math
from typing import Any

from app.operation.recognition.schemas import (
    CandidateRankResult, LocalGroundingResult, PreClickCandidateDecision, PreClickDecisionResult,
)
from app.vision.schemas import ImageSize


MIN_VISUAL_CONFIDENCE = 0.7
POINT_PROTOCOL_BASELINE = 0.72


def validate_direct_point_payload(parsed: dict[str, Any], *, image_size: ImageSize) -> float:
    """点协议不允许把越界坐标夹回图内，显式不确定性不能被坐标覆盖。"""
    if parsed.get("status", "found") not in {"found", "ready", "ok"}:
        raise ValueError("direct_visual_model_target_not_found")
    point = parsed.get("point")
    if not isinstance(point, dict):
        raise ValueError("direct_visual_model_point_missing")
    coordinates = [point.get("x"), point.get("y")]
    if any(type(value) not in {int, float} or not math.isfinite(value) for value in coordinates):
        raise ValueError("direct_visual_model_point_invalid")
    x, y = coordinates
    space = str(point.get("coordinate_space") or "normalized_0_1000").lower()
    if space in {"normalized_0_1000", "0_1000", "normalized"}:
        valid = 0 <= x <= 1000 and 0 <= y <= 1000
    elif space in {"pixel", "pixels", "screenshot", "capture_image_pixels"}:
        valid = 0 <= x < image_size.width and 0 <= y < image_size.height
    else:
        raise ValueError("direct_visual_model_coordinate_space_invalid")
    if not valid:
        raise ValueError("direct_visual_model_point_outside_image")
    confidence = parsed.get("confidence", POINT_PROTOCOL_BASELINE)
    if (type(confidence) not in {int, float} or not math.isfinite(confidence)
            or confidence < MIN_VISUAL_CONFIDENCE or confidence > 1):
        raise ValueError("direct_visual_model_confidence_too_low_or_invalid")
    return float(confidence)


def decide_direct_visual(*, candidates: CandidateRankResult, grounding: LocalGroundingResult,
                         image_size: ImageSize, screenshot_sha256: str) -> PreClickDecisionResult:
    """保留视觉来源；门禁核验几何与置信，不伪造 OCR 或控件旁证。"""
    locals_by_id = {item.candidate_id: item for item in grounding.results}
    decisions = []
    margin_ok = len(candidates.candidates) == 1 or (
        candidates.margin_to_second is not None and candidates.margin_to_second >= 0.06)
    for candidate in candidates.candidates:
        local = locals_by_id.get(candidate.candidate_id)
        proof = candidate.element.evidence.get("direct_visual") or {}
        point = local.refined_click_point if local is not None else None
        bbox = candidate.refined_bbox or candidate.element.bbox.to_dict()
        reasons = []
        if not candidate.eligible or not candidate.element.interaction_policy.allowed:
            reasons.append("interaction_policy_blocked")
        if candidate.score < 0.45:
            reasons.append("candidate_score_too_low")
        if not margin_ok:
            reasons.append("top_candidate_margin_too_small")
        if (local is None or local.status != "grounded" or local.confidence < MIN_VISUAL_CONFIDENCE
                or local.coordinate_source != "direct_visual_model"):
            reasons.append("direct_visual_grounding_unverified")
        if proof.get("screenshot_sha256") != screenshot_sha256:
            reasons.append("direct_visual_capture_mismatch")
        inside = (isinstance(point, dict) and all(type(point.get(k)) is int for k in ("x", "y"))
            and 0 <= point["x"] < image_size.width and 0 <= point["y"] < image_size.height
            and bbox["x"] <= point["x"] < bbox["x"] + bbox["w"]
            and bbox["y"] <= point["y"] < bbox["y"] + bbox["h"])
        if not inside:
            reasons.append("direct_visual_point_outside_capture_or_bbox")
        decisions.append(PreClickCandidateDecision(candidate_id=candidate.candidate_id,
            element_id=candidate.element_id, allowed=not reasons, score=candidate.score,
            click_point=point, reasons=reasons or ["direct_visual_model_geometry_verified"],
            resolved_click_point={"contract_version":"resolved_click_point_v1",
                "target_text":candidate.label,"target_role":candidate.role,"bbox":bbox,
                "bbox_source":candidate.bbox_refine_reason,"raw_model_point":point,
                "raw_grounding_point":point,"chosen_point":point,
                "chosen_point_source":"raw_grounding_point","inside_bbox":bool(inside),
                "raw_inside_bbox":bool(inside),"independent_target_bbox_verified":False,
                "geometry_check_scope":"model_target_bounds" if proof.get("model_bbox") else "search_region_only"}))
    selected = next((item for item in decisions if item.allowed), None)
    return PreClickDecisionResult(allowed=selected is not None,
        selected_candidate_id=selected.candidate_id if selected else None,
        selected_element_id=selected.element_id if selected else None,
        selected_click_point=selected.click_point if selected else None,
        reasons=["direct_visual_candidate_allowed"] if selected else ["no_candidate_passed_pre_click_checks"],
        candidate_decisions=decisions, summary={"execution_grounding":"direct_visual",
            "candidate_count":len(decisions),"top_margin_ok":margin_ok,
            "allowed_candidate_count":sum(item.allowed for item in decisions)})
