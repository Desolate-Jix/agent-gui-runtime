from __future__ import annotations

from typing import Any


def validate_grounding_candidate(
    *,
    item: dict[str, Any],
    grounding: dict[str, Any],
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    evidence = evidence if isinstance(evidence, dict) else {}
    item_bbox = _normalize_bbox(item.get("bbox") if isinstance(item, dict) else {})
    screen_bbox = _normalize_bbox(grounding.get("screen_bbox") if isinstance(grounding, dict) else {})
    candidate_bbox = screen_bbox if screen_bbox["w"] and screen_bbox["h"] else item_bbox
    raw_screen_point = grounding.get("screen_point") if isinstance(grounding, dict) else None
    point_present = _point_mapping_present(raw_screen_point)
    screen_point = _normalize_point(raw_screen_point)
    checks = {
        "point_present": point_present,
        "point_inside_bbox": point_present and _point_inside_bbox(screen_point, candidate_bbox),
        "bbox_inside_image": bool(candidate_bbox["w"] and candidate_bbox["h"]),
        "ocr_anchor_overlap": _optional_bool(evidence.get("ocr_anchor_overlap"), default=True),
        "uia_or_dom_or_parser_overlap": _optional_bool(evidence.get("uia_or_dom_or_parser_overlap"), default=True),
        "coordinate_transform_replay": bool(evidence.get("coordinate_transform_replay")),
        "screenshot_freshness": bool(evidence.get("screenshot_freshness")),
        "not_non_actionable_content": not _is_non_actionable_item(item),
        "not_danger_zone": not _is_danger_item(item),
    }
    failure_category = _failure_category(checks)
    status = "valid_candidate" if failure_category is None else "rejected"
    return {
        "contract_version": "learning_grounding_validation_v1",
        "status": status,
        "failure_category": failure_category,
        "item_id": item.get("item_id") if isinstance(item, dict) else None,
        "checks": checks,
        "screen_point": screen_point,
        "screen_bbox": candidate_bbox,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "real_action_requires_gate": True,
    }


def _failure_category(checks: dict[str, bool]) -> str | None:
    if not checks["not_danger_zone"]:
        return "danger_zone"
    if not checks["not_non_actionable_content"]:
        return "non_actionable_content"
    if not checks["screenshot_freshness"] or not checks["coordinate_transform_replay"]:
        return "stale_or_unreplayable_evidence"
    if not checks["bbox_inside_image"]:
        return "invalid_bbox"
    if not checks["point_present"]:
        return "missing_grounding_point"
    if not checks["point_inside_bbox"]:
        return "point_outside_bbox"
    if not checks["ocr_anchor_overlap"] or not checks["uia_or_dom_or_parser_overlap"]:
        return "insufficient_evidence_overlap"
    return None


def _is_non_actionable_item(item: dict[str, Any]) -> bool:
    item_type = str(item.get("item_type") or "").casefold() if isinstance(item, dict) else ""
    role = str(item.get("role") or "").casefold() if isinstance(item, dict) else ""
    evidence_level = str(item.get("evidence_level") or "").casefold() if isinstance(item, dict) else ""
    if _looks_like_open_detail_card(item):
        return False
    if item_type in {"readable", "layout"}:
        return True
    if role in {"text", "card", "section", "group", "news_card", "recommendation_item"}:
        return True
    return evidence_level in {"ocr_text_only", "semantic_region_only"} and item_type not in {"actionable", "form_field"}


def _looks_like_open_detail_card(item: dict[str, Any]) -> bool:
    role = str(item.get("role") or "").casefold() if isinstance(item, dict) else ""
    if role != "card":
        return False
    interactable = item.get("interactable_evidence") if isinstance(item.get("interactable_evidence"), dict) else {}
    if not (bool(interactable.get("calibrated_target_validated")) or bool(interactable.get("cross_evidence_overlap"))):
        return False
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    text_parts = [
        str(item.get("label") or ""),
        str(item.get("text") or ""),
        str(metadata.get("description") or ""),
    ]
    if isinstance(metadata.get("text_lines"), list):
        text_parts.extend(str(value) for value in metadata.get("text_lines", []))
    text = " ".join(text_parts).casefold()
    return any(term in text for term in ("job", "listing", "result", "company"))


def _is_danger_item(item: dict[str, Any]) -> bool:
    item_type = str(item.get("item_type") or "").casefold() if isinstance(item, dict) else ""
    label = str(item.get("label") or "").casefold() if isinstance(item, dict) else ""
    if item_type == "danger_zone":
        return True
    return any(
        token in label
        for token in (
            "submit application",
            "send application",
            "complete application",
            "review and submit",
            "confirm",
            "payment",
            "delete",
        )
    )


def _point_inside_bbox(point: dict[str, int], bbox: dict[str, int]) -> bool:
    return bbox["x"] <= point["x"] <= bbox["x"] + bbox["w"] and bbox["y"] <= point["y"] <= bbox["y"] + bbox["h"]


def _normalize_bbox(value: dict[str, Any] | None) -> dict[str, int]:
    value = value if isinstance(value, dict) else {}
    return {
        "x": _int_or_zero(value.get("x")),
        "y": _int_or_zero(value.get("y")),
        "w": max(0, _int_or_zero(value.get("w"))),
        "h": max(0, _int_or_zero(value.get("h"))),
    }


def _normalize_point(value: dict[str, Any] | None) -> dict[str, int]:
    value = value if isinstance(value, dict) else {}
    return {"x": _int_or_zero(value.get("x")), "y": _int_or_zero(value.get("y"))}


def _point_mapping_present(value: Any) -> bool:
    return isinstance(value, dict) and "x" in value and "y" in value


def _int_or_zero(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def _optional_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    return bool(value)
