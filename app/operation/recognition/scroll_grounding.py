"""当前截图和完整 UIA 支持的滚动落点；不调用模型、不伪造 OCR、不执行输入。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import re

from PIL import Image

from app.agent.fresh_learning_action_contracts import payload_sha256
from app.agent.fresh_scroll_region import current_scroll_container
from app.agent.scroll_parameters import ReviewedScrollParameters
from app.operation.page_structure.schemas import PageElement, InteractionPolicy, VerificationHints
from app.operation.recognition.schemas import (
    RecognitionCandidate, ScoreBreakdown, CandidateRankResult, LocalGroundingCandidateResult, LocalGroundingResult,
)
from app.vision.schemas import BBox

EVIDENCE_KEY = "current_scroll_container_binding"
COORDINATE_SOURCE = "current_uia_scroll_region_v1"


def _target(uia, parameters, viewport):
    if (not isinstance(viewport, (list, tuple)) or len(viewport) != 2
            or any(type(v) is not int or v <= 0 for v in viewport)):
        raise ValueError("scroll viewport is invalid")
    if (not isinstance(uia, dict) or uia.get("status") != "ok" or uia.get("scan_complete") is not True
            or uia.get("truncated") is not False or not isinstance(uia.get("controls"), list)):
        raise ValueError("scroll grounding requires a complete current UIA snapshot")
    window = uia.get("window", {})
    if (not isinstance(window, dict) or any(type(window.get(k)) is not int or window[k] <= 0 for k in ("handle", "process_id"))
            or window.get("bbox") != {"x": 0, "y": 0, "w": viewport[0], "h": viewport[1]}):
        raise ValueError("scroll UIA window differs from captured viewport")
    matches = [c for c in uia["controls"] if isinstance(c, dict) and c.get("control_id") == parameters.target_container_id]
    if len(matches) != 1:
        raise ValueError("scroll target container is unavailable or ambiguous")
    target = matches[0]
    from app.operation.recognition.control_corroboration import _box
    box, runtime = target.get("bbox"), target.get("runtime_id")
    if (not _box(box) or box["x"] + box["w"] > viewport[0] or box["y"] + box["h"] > viewport[1]
            or not isinstance(runtime, list) or not runtime or any(type(v) is not int for v in runtime)
            or sum(c.get("runtime_id") == runtime for c in uia["controls"] if isinstance(c, dict)) != 1):
        raise ValueError("scroll target geometry or runtime identity is invalid")
    return target


def _empty_point(uia, target, parameters):
    box = target["bbox"]
    # 固定有限网格仅查找本帧真实容器内部，不移动窗口或调整旧坐标。
    fractions = (0.5, 0.25, 0.75, 0.125, 0.375, 0.625, 0.875)
    for fy in fractions:
        for fx in fractions:
            point = {"x": box["x"] + int(box["w"] * fx), "y": box["y"] + int(box["h"] * fy)}
            if min(point["x"] - box["x"], box["x"] + box["w"] - point["x"],
                   point["y"] - box["y"], box["y"] + box["h"] - point["y"]) < 9:
                continue
            try:
                current_scroll_container(uia["controls"], point, axis=parameters.axis,
                    target_container_id=parameters.target_container_id)
            except ValueError:
                continue
            return point
    raise ValueError("scroll target has no verified empty interior point")


def recognize_current_scroll(*, image_path, goal, uia_snapshot, scroll_parameters):
    parameters = ReviewedScrollParameters.from_payload(scroll_parameters)
    path = Path(image_path).resolve()
    png = path.read_bytes()
    with Image.open(path) as image:
        viewport = image.size
    target = _target(uia_snapshot, parameters, viewport)
    point = _empty_point(uia_snapshot, target, parameters)
    digest = sha256(png).hexdigest()
    proof = {"contract_version": "current_scroll_container_binding_v1", "screenshot_sha256": digest,
        "uia_snapshot_sha256": payload_sha256(uia_snapshot), "scroll_parameters": parameters.to_payload(),
        "target": deepcopy(target), "point": point, "viewport_size": list(viewport), "goal": goal}
    ident = "current_scroll_" + payload_sha256(proof)[:24]
    box = BBox(**target["bbox"])
    element = PageElement(element_id=ident, label=goal, role="region", interaction_type="scroll",
        description="Current UIA scroll container", text="", bbox=box, semantic_bbox=box,
        click_point=point, click_strategy=COORDINATE_SOURCE, possible_destinations=[],
        verification_hints=VerificationHints(expected_changes=["target_content_change"], target_scope="local"),
        interaction_policy=InteractionPolicy(allowed=True), fusion_confidence=0.9,
        coordinate_confidence="high", memory_key="", sources=["windows_uia.controls"],
        evidence={EVIDENCE_KEY: proof})
    # 精确容器引用提供目标关联；此评分不表示观测到了目标文字。
    breakdown = ScoreBreakdown(text_similarity=0, role_score=1, policy_score=1,
        confidence_score=0.9, screen_reading_score=1)
    candidate = RecognitionCandidate(candidate_id=ident, rank=1, element_id=ident, label=goal,
        role="region", text="", score=breakdown.total(), eligible=True,
        reasons=["explicit_current_scroll_container"], score_breakdown=breakdown, element=element)
    local = LocalGroundingCandidateResult(candidate_id=ident, element_id=ident, status="grounded",
        crop_path=None, crop_bbox=target["bbox"], refined_click_point=point,
        coordinate_source=COORDINATE_SOURCE, confidence=0.9, matched_text=None, matched_text_bbox=None,
        reasons=["current_scroll_container_empty_point"])
    ranked = CandidateRankResult(goal=goal, top_k=1, candidates=[candidate],
        recommended_candidate_id=ident, margin_to_second=candidate.score, summary={"semantic_action": "scroll_region"})
    grounding = LocalGroundingResult(goal=goal, results=[local], recommended_candidate_id=ident)
    return {"contract_version": "recognition_plan_v1", "image_path": str(path), "goal": goal,
        "candidate_result": ranked.to_dict(), "narrow_search_result": grounding.to_dict(),
        "summary": {"semantic_action": "scroll_region", "model_used": False, "ocr_used": False}}


def has_current_scroll_grounding(candidate, local, uia, screenshot_sha256, *, goal):
    proof = candidate.element.evidence.get(EVIDENCE_KEY)
    if (not isinstance(proof, dict) or set(proof) != {"contract_version", "screenshot_sha256", "uia_snapshot_sha256",
            "scroll_parameters", "target", "point", "viewport_size", "goal"}
            or proof["contract_version"] != "current_scroll_container_binding_v1"
            or not isinstance(screenshot_sha256, str) or not re.fullmatch("[0-9a-f]{64}", screenshot_sha256)
            or proof["screenshot_sha256"] != screenshot_sha256 or proof["uia_snapshot_sha256"] != payload_sha256(uia)
            or proof["goal"] != goal or candidate.label != goal or candidate.element.label != goal
            or candidate.text != "" or candidate.element.text != ""
            or candidate.role != "region" or candidate.element.role != "region" or candidate.element.interaction_type != "scroll"
            or local is None or local.status != "grounded" or local.coordinate_source != COORDINATE_SOURCE
            or local.candidate_id != candidate.candidate_id or local.element_id != candidate.element_id
            or local.matched_text is not None or local.matched_text_bbox is not None):
        return False
    try:
        parameters = ReviewedScrollParameters.from_payload(proof["scroll_parameters"])
        target = _target(uia, parameters, proof["viewport_size"])
        selected = current_scroll_container(uia["controls"], proof["point"], axis=parameters.axis,
            target_container_id=parameters.target_container_id)
    except (ValueError, TypeError, KeyError):
        return False
    return (target == selected == proof["target"] and proof["point"] == local.refined_click_point == candidate.element.click_point
        and candidate.element.bbox.to_dict() == local.crop_bbox == target["bbox"]
        and (candidate.refined_bbox is None or candidate.refined_bbox == target["bbox"]))
