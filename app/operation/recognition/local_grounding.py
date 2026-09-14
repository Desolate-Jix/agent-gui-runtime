from __future__ import annotations

import re
import math
from app.operation.recognition.text_match import text_similarity as _text_similarity, normalize_text as _normalize_text
from pathlib import Path

from PIL import Image

from app.core.runtime_artifacts import build_recognition_crop_path
from app.operation.recognition.schemas import LocalGroundingCandidateResult, LocalGroundingRequest, LocalGroundingResult, RecognitionCandidate
from app.vision.schemas import BBox
from modules.ocr.contracts import OCRTextMatch


def run_local_grounding(request: LocalGroundingRequest) -> LocalGroundingResult:
    image_path = Path(request.image_path)
    results: list[LocalGroundingCandidateResult] = []
    if not image_path.exists():
        return LocalGroundingResult(
            goal=request.goal,
            results=[],
            recommended_candidate_id=None,
            summary={"status": "image_not_found", "candidate_count": len(request.candidates)},
        )

    with Image.open(image_path) as image:
        width, height = image.size
        for candidate in request.candidates:
            results.append(_ground_candidate(image, image_path=image_path, image_size=(width, height), request=request, candidate=candidate))

    successful = [item for item in results if item.status == "grounded"]
    recommended = successful[0].candidate_id if successful else (results[0].candidate_id if results else None)
    return LocalGroundingResult(
        goal=request.goal,
        results=results,
        recommended_candidate_id=recommended,
        summary={
            "status": "completed",
            "candidate_count": len(request.candidates),
            "grounded_count": len(successful),
            "fallback_count": len([item for item in results if item.status == "fallback"]),
        },
    )


def _ground_candidate(
    image: Image.Image,
    *,
    image_path: Path,
    image_size: tuple[int, int],
    request: LocalGroundingRequest,
    candidate: RecognitionCandidate,
) -> LocalGroundingCandidateResult:
    crop_bbox = _crop_bbox(_candidate_crop_bbox(candidate), image_size=image_size, padding=request.crop_padding)
    crop_path = build_recognition_crop_path(name_hint=request.app_name or image_path.stem, candidate_id=candidate.candidate_id)
    crop = image.crop((crop_bbox["x"], crop_bbox["y"], crop_bbox["x"] + crop_bbox["width"], crop_bbox["y"] + crop_bbox["height"]))
    crop.save(crop_path)

    ocr_result = request.ocr_scan(str(crop_path))
    match = _best_match(
        ocr_result.matches,
        goal=request.goal,
        candidate_texts=[candidate.label, candidate.text, candidate.element.description],
    )
    if match is None:
        from app.operation.recognition.native_control_ocr_observation import KEY, record_native_ocr
        observed = record_native_ocr(image_path=image_path, image_size=image_size,
            crop=crop_bbox, candidate=candidate, ocr_result=ocr_result)
        if observed is not None:
            candidate.element.evidence[KEY] = observed
        reasons = ['no_matching_local_ocr_text']
        if not ocr_result.matches:
            reasons.append('local_ocr_returned_no_text')
        elif _ocr_outside_target(ocr_result.matches, crop_bbox, candidate.element.bbox):
            reasons.append('local_ocr_no_text_in_target')
        return LocalGroundingCandidateResult(
            candidate_id=candidate.candidate_id,
            element_id=candidate.element_id,
            status="fallback",
            crop_path=str(crop_path.resolve()),
            crop_bbox=crop_bbox,
            refined_click_point=dict(candidate.element.click_point),
            coordinate_source="candidate_element_click_point",
            confidence=round(candidate.score * 0.6, 4),
            matched_text=None,
            matched_text_bbox=None,
            reasons=reasons,
        )

    local_bbox = {
        "x": int(match.bbox.x),
        "y": int(match.bbox.y),
        "width": int(match.bbox.width),
        "height": int(match.bbox.height),
    }
    global_point = {
        "x": int(round(crop_bbox["x"] + match.bbox.x + (match.bbox.width / 2.0))),
        "y": int(round(crop_bbox["y"] + match.bbox.y + (match.bbox.height / 2.0))),
    }
    confidence = min(1.0, max(float(match.score), candidate.score))
    return LocalGroundingCandidateResult(
        candidate_id=candidate.candidate_id,
        element_id=candidate.element_id,
        status="grounded",
        crop_path=str(crop_path.resolve()),
        crop_bbox=crop_bbox,
        refined_click_point=global_point,
        coordinate_source="local_ocr_text_center",
        confidence=round(confidence, 4),
        matched_text=match.text,
        matched_text_bbox=local_bbox,
        reasons=["matched_local_ocr_text", "mapped_crop_text_center_to_full_image"],
    )


def _ocr_outside_target(matches, crop, target) -> bool:
    """只排除目标框外的上下文文字；无效框或任何重叠都不能声明目标无字。"""
    if not matches:
        return False
    for match in matches:
        box = getattr(match, 'bbox', None)
        values = [getattr(box, key, None) for key in ('x', 'y', 'width', 'height')]
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in values):
            return False
        x, y, width, height = values
        if (x < 0 or y < 0 or width <= 0 or height <= 0
                or x + width > crop['width'] or y + height > crop['height']):
            return False
        x, y = x + crop['x'], y + crop['y']
        if (x < target.x + target.w and x + width > target.x
                and y < target.y + target.h and y + height > target.y):
            return False
    return True


def _crop_bbox(bbox: BBox, *, image_size: tuple[int, int], padding: int) -> dict[str, int]:
    image_width, image_height = image_size
    x1 = max(0, int(bbox.x) - int(padding))
    y1 = max(0, int(bbox.y) - int(padding))
    x2 = min(image_width, int(bbox.x + bbox.w) + int(padding))
    y2 = min(image_height, int(bbox.y + bbox.h) + int(padding))
    return {
        "x": x1,
        "y": y1,
        "width": max(1, x2 - x1),
        "height": max(1, y2 - y1),
    }


def _candidate_crop_bbox(candidate: RecognitionCandidate) -> BBox:
    bbox = candidate.refined_bbox
    if not bbox:
        return candidate.element.bbox
    return BBox(
        x=int(bbox.get("x", 0)),
        y=int(bbox.get("y", 0)),
        w=int(bbox.get("w", bbox.get("width", 0))),
        h=int(bbox.get("h", bbox.get("height", 0))),
    )


def _best_match(matches: list[OCRTextMatch], *, goal: str, candidate_texts: list[str]) -> OCRTextMatch | None:
    if not matches:
        return None
    target_values = [_normalize_text(goal), *[_normalize_text(value) for value in candidate_texts]]
    scored: list[tuple[float, OCRTextMatch]] = []
    for match in matches:
        text = _normalize_text(match.text)
        if not text:
            continue
        similarity = max((_text_similarity(text, target) for target in target_values if target), default=0.0)
        score = (similarity * 0.75) + (max(0.0, min(float(match.score), 1.0)) * 0.25)
        scored.append((round(score, 4), match))
    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1].score), reverse=True)
    best_score, best_match = scored[0]
    # 同名文字分布在不同位置时不能凭列表顺序选出坐标。
    if any(_normalize_text(other.text) == _normalize_text(best_match.text)
           and other.bbox != best_match.bbox for _, other in scored[1:]):
        return None
    return best_match if best_score >= 0.45 else None


