from __future__ import annotations

import copy
from typing import Any

from app.vision.region_standard import clamp_bbox, diagonal_from_bbox
from app.vision.schemas import BBox, VisionAnalyzeResponse, VisionRegion


def apply_anchor_grounding_evaluation(response: VisionAnalyzeResponse, ocr_anchor_payload: dict[str, Any] | None) -> VisionAnalyzeResponse:
    anchor_map = _anchor_map(ocr_anchor_payload)
    if not anchor_map:
        return response

    for region in response.regions:
        evaluation = evaluate_region_grounding(region, anchor_map, image_size=(response.image_size.to_dict() if response.image_size else None))
        if evaluation["referenced_anchor_ids"] or evaluation["violations"]:
            constraints = copy.deepcopy(region.grounding_constraints)
            constraints["grounding_evaluation"] = evaluation
            region.grounding_constraints = constraints
    return response


def evaluate_region_grounding(
    region: VisionRegion,
    anchor_map: dict[str, BBox],
    *,
    image_size: dict[str, int] | None = None,
) -> dict[str, Any]:
    policy = _text_inclusion_policy(region)
    referenced_ids = _referenced_anchor_ids(region)
    referenced_anchors = [(anchor_id, anchor_map[anchor_id]) for anchor_id in referenced_ids if anchor_id in anchor_map]
    included: list[str] = []
    excluded: list[str] = []
    violations: list[dict[str, Any]] = []

    for anchor_id, anchor_bbox in referenced_anchors:
        if _contains(region.bbox, anchor_bbox):
            included.append(anchor_id)
        else:
            excluded.append(anchor_id)

        if policy == "exclude_text" and _intersects(region.bbox, anchor_bbox):
            violations.append(
                {
                    "type": "text_anchor_included_but_policy_excludes_text",
                    "anchor_id": anchor_id,
                    "anchor_bbox": anchor_bbox.to_dict(),
                }
            )
        if policy == "include_referenced_text" and not _contains(region.bbox, anchor_bbox):
            violations.append(
                {
                    "type": "referenced_text_anchor_missing_from_bbox",
                    "anchor_id": anchor_id,
                    "anchor_bbox": anchor_bbox.to_dict(),
                }
            )

    anchor_frame = _union_bbox([bbox for _, bbox in referenced_anchors])
    corrected_bbox = None
    if policy == "include_referenced_text" and referenced_anchors and excluded:
        corrected = _union_bbox([region.bbox] + [bbox for _, bbox in referenced_anchors])
        if corrected is not None and image_size:
            corrected = clamp_bbox(corrected, width=int(image_size.get("width") or 0), height=int(image_size.get("height") or 0))
        corrected_bbox = corrected.to_dict() if corrected is not None else None

    return {
        "contract_version": "anchor_grounding_evaluation_v1",
        "text_inclusion_policy": policy,
        "referenced_anchor_ids": referenced_ids,
        "known_referenced_anchor_ids": [anchor_id for anchor_id, _ in referenced_anchors],
        "included_anchor_ids": included,
        "excluded_anchor_ids": excluded,
        "anchor_frame_bbox": anchor_frame.to_dict() if anchor_frame is not None else None,
        "anchor_corrected_bbox": corrected_bbox,
        "violations": violations,
        "ok": not violations,
    }


def _anchor_map(payload: dict[str, Any] | None) -> dict[str, BBox]:
    if not isinstance(payload, dict):
        return {}
    result: dict[str, BBox] = {}
    for anchor in payload.get("anchors") or []:
        if not isinstance(anchor, dict) or not isinstance(anchor.get("bbox"), dict):
            continue
        anchor_id = str(anchor.get("anchor_id") or anchor.get("id") or "").strip()
        bbox = anchor["bbox"]
        if not anchor_id:
            continue
        try:
            result[anchor_id] = BBox(
                x=int(bbox.get("x") or 0),
                y=int(bbox.get("y") or 0),
                w=int(bbox.get("w") or bbox.get("width") or 0),
                h=int(bbox.get("h") or bbox.get("height") or 0),
            )
        except Exception:
            continue
    return result


def _text_inclusion_policy(region: VisionRegion) -> str:
    raw = str((region.grounding_constraints or {}).get("text_inclusion_policy") or "").strip().lower()
    normalized = raw.replace("-", "_").replace(" ", "_")
    if normalized in {"exclude_text", "visual_only", "not_include_text", "no_text"}:
        return "exclude_text"
    if normalized in {"include_referenced_text", "include_text", "contains_text", "text_inside"}:
        return "include_referenced_text"
    relations = {str(item.get("relation") or "").strip().lower() for item in region.anchor_relations if isinstance(item, dict)}
    if relations & {"inside", "contains", "boundary_text", "text_inside"}:
        return "include_referenced_text"
    if region.role == "icon" and not region.ocr_text and not region.text_lines:
        return "exclude_text"
    return "unspecified"


def _referenced_anchor_ids(region: VisionRegion) -> list[str]:
    ids: list[str] = []
    for relation in region.anchor_relations:
        if isinstance(relation, dict):
            _append_id(ids, relation.get("anchor_id"))
            _append_id(ids, relation.get("id"))
    _collect_anchor_ids(region.grounding_constraints, ids)
    seen: set[str] = set()
    unique: list[str] = []
    for anchor_id in ids:
        if anchor_id not in seen:
            unique.append(anchor_id)
            seen.add(anchor_id)
    return unique


def _collect_anchor_ids(value: Any, ids: list[str]) -> None:
    if isinstance(value, dict):
        _append_id(ids, value.get("anchor_id"))
        for item in value.get("anchor_ids") or []:
            _append_id(ids, item)
        for item in value.values():
            _collect_anchor_ids(item, ids)
    elif isinstance(value, list):
        for item in value:
            _collect_anchor_ids(item, ids)


def _append_id(ids: list[str], value: Any) -> None:
    text = str(value or "").strip()
    if text:
        ids.append(text)


def _contains(outer: BBox, inner: BBox) -> bool:
    outer_d = diagonal_from_bbox(outer)
    inner_d = diagonal_from_bbox(inner)
    return inner_d.x1 >= outer_d.x1 and inner_d.y1 >= outer_d.y1 and inner_d.x2 <= outer_d.x2 and inner_d.y2 <= outer_d.y2


def _intersects(left: BBox, right: BBox) -> bool:
    left_d = diagonal_from_bbox(left)
    right_d = diagonal_from_bbox(right)
    return left_d.x1 < right_d.x2 and left_d.x2 > right_d.x1 and left_d.y1 < right_d.y2 and left_d.y2 > right_d.y1


def _union_bbox(items: list[BBox]) -> BBox | None:
    if not items:
        return None
    diagonals = [diagonal_from_bbox(item) for item in items]
    x1 = min(item.x1 for item in diagonals)
    y1 = min(item.y1 for item in diagonals)
    x2 = max(item.x2 for item in diagonals)
    y2 = max(item.y2 for item in diagonals)
    return BBox(x=x1, y=y1, w=max(1, x2 - x1), h=max(1, y2 - y1))
