from __future__ import annotations

from copy import deepcopy
from typing import Any


def resolve_inventory_layout(items: list[dict[str, Any]]) -> dict[str, Any]:
    """清理学习模式候选框，保留可复盘诊断。"""

    valid_items = [deepcopy(item) for item in items if isinstance(item, dict)]
    overlap_pairs = _count_overlap_pairs(valid_items)
    kept: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    duplicates_merged = 0

    for item in _sort_for_resolution(valid_items):
        duplicate_resolution = _find_duplicate_resolution(kept, item)
        duplicate_index = duplicate_resolution["index"]
        if duplicate_index is not None:
            existing = kept[duplicate_index]
            if duplicate_resolution["prefer_incoming"]:
                kept[duplicate_index] = _merge_duplicate(item, existing)
                suppressed_item = existing
            else:
                kept[duplicate_index] = _merge_duplicate(existing, item)
                suppressed_item = item
            suppressed.append(_suppressed_entry(suppressed_item, duplicate_resolution["reason"], kept[duplicate_index]))
            duplicates_merged += 1
            continue
        container_reason = _semantic_container_suppression_reason(item, kept)
        if container_reason:
            suppressed.append(_suppressed_entry(item, container_reason, None))
            continue
        kept.append(_annotate_kept(item))

    cleaned_items = sorted(kept, key=lambda item: int(item.get("_original_order", 0)))
    for index, item in enumerate(cleaned_items):
        item.pop("_original_order", None)
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        item["metadata"] = metadata
        metadata.setdefault("layout_cleanup", {})["resolved_index"] = index + 1

    for entry in suppressed:
        if isinstance(entry.get("item"), dict):
            entry["item"].pop("_original_order", None)

    suppression_reason_counts = _count_suppression_reasons(suppressed)
    return {
        "contract_version": "learn_layout_cleanup_report_v1",
        "input_count": len(valid_items),
        "output_count": len(cleaned_items),
        "suppressed_count": len(suppressed),
        "suppression_reason_counts": suppression_reason_counts,
        "overlap_pair_count": overlap_pairs,
        "duplicates_merged": duplicates_merged,
        "suppressed_items": suppressed,
        "cleaned_items": cleaned_items,
        "metrics": {
            "layout_cleanup_applied": {
                "passed": 1,
                "attempted": 1,
                "rate": 1.0,
                "interpretation": "候选框清理已运行；这不是识别准确率或点击成功率",
            },
            "overlap_reduction": {
                "before": overlap_pairs,
                "after": _count_overlap_pairs(cleaned_items),
            },
            "cross_evidence_support_duplicate_merge": {
                "passed": int(suppression_reason_counts.get("cross_evidence_support_duplicate", 0)),
                "attempted": int(suppression_reason_counts.get("cross_evidence_support_duplicate", 0)),
                "rate": (
                    "not_covered"
                    if int(suppression_reason_counts.get("cross_evidence_support_duplicate", 0)) == 0
                    else 1.0
                ),
                "interpretation": "显式 cross-evidence support 去重数量；不是模型准确率或点击成功率",
            },
        },
        "interpretation": (
            "layout cleanup resolves duplicate and container-heavy parser candidates before classification; "
            "raw parser evidence remains available for audit"
        ),
    }


def _sort_for_resolution(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        item["_original_order"] = index
        ordered.append(item)
    return sorted(
        ordered,
        key=lambda item: (
            -_evidence_score(item),
            _bbox_area(item.get("bbox")),
            int(item.get("_original_order", 0)),
        ),
    )


def _annotate_kept(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    item["metadata"] = metadata
    metadata.setdefault("layout_cleanup", {})["status"] = "kept"
    return item


def _find_duplicate_resolution(kept: list[dict[str, Any]], item: dict[str, Any]) -> dict[str, Any]:
    for index, existing in enumerate(kept):
        if _cross_evidence_support_duplicate(existing, item):
            return {"index": index, "reason": "cross_evidence_support_duplicate", "prefer_incoming": False}
        if _cross_evidence_support_duplicate(item, existing):
            return {"index": index, "reason": "cross_evidence_support_duplicate", "prefer_incoming": True}
        if _same_target(existing, item):
            return {"index": index, "reason": "duplicate_or_same_target", "prefer_incoming": False}
    return {"index": None, "reason": "", "prefer_incoming": False}


def _same_target(left: dict[str, Any], right: dict[str, Any]) -> bool:
    if _label_key(left) != _label_key(right):
        return False
    if _role_key(left) != _role_key(right):
        return False
    return _iou(left.get("bbox"), right.get("bbox")) >= 0.78 or _mutual_containment(left.get("bbox"), right.get("bbox")) >= 0.9


def _merge_duplicate(primary: dict[str, Any], duplicate: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(primary)
    merged["source_evidence"] = sorted(
        {
            str(value)
            for value in [
                *(primary.get("source_evidence") if isinstance(primary.get("source_evidence"), list) else []),
                *(duplicate.get("source_evidence") if isinstance(duplicate.get("source_evidence"), list) else []),
            ]
            if str(value or "").strip()
        }
    )
    primary_interactable = primary.get("interactable_evidence") if isinstance(primary.get("interactable_evidence"), dict) else {}
    duplicate_interactable = duplicate.get("interactable_evidence") if isinstance(duplicate.get("interactable_evidence"), dict) else {}
    merged["interactable_evidence"] = {
        key: bool(primary_interactable.get(key)) or bool(duplicate_interactable.get(key))
        for key in sorted({*primary_interactable.keys(), *duplicate_interactable.keys()})
    }
    metadata = merged.get("metadata") if isinstance(merged.get("metadata"), dict) else {}
    metadata.setdefault("layout_cleanup", {})["status"] = "merged_duplicate"
    metadata["layout_cleanup"]["merged_item_ids"] = sorted(
        {
            str(primary.get("item_id") or ""),
            str(duplicate.get("item_id") or ""),
            *[
                str(value)
                for value in metadata.get("layout_cleanup", {}).get("merged_item_ids", [])
                if str(value or "").strip()
            ],
        }
        - {""}
    )
    support_snapshot = _merged_support_snapshot(primary, duplicate)
    if support_snapshot:
        metadata["layout_cleanup"]["merged_support"] = support_snapshot
    merged["metadata"] = metadata
    return merged


def _cross_evidence_support_duplicate(primary: dict[str, Any], support: dict[str, Any]) -> bool:
    support_item_id = _cross_evidence_support_item_id(primary)
    if not support_item_id or str(support.get("item_id") or "") != support_item_id:
        return False
    if "calibrated_target" not in _sources(support):
        return False
    return _bbox_overlap_compatible(primary.get("bbox"), support.get("bbox"))


def _cross_evidence_support_item_id(item: dict[str, Any]) -> str:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    cross_evidence = metadata.get("cross_evidence") if isinstance(metadata.get("cross_evidence"), dict) else {}
    return str(cross_evidence.get("support_item_id") or "").strip()


def _sources(item: dict[str, Any]) -> set[str]:
    return {
        str(value).casefold()
        for value in item.get("source_evidence", [])
        if str(value or "").strip()
    } if isinstance(item.get("source_evidence"), list) else set()


def _bbox_overlap_compatible(left: Any, right: Any) -> bool:
    return _iou(left, right) >= 0.2 or _mutual_containment(left, right) >= 0.5


def _merged_support_snapshot(primary: dict[str, Any], duplicate: dict[str, Any]) -> dict[str, Any]:
    support = duplicate if _cross_evidence_support_duplicate(primary, duplicate) else primary if _cross_evidence_support_duplicate(duplicate, primary) else {}
    if not support:
        return {}
    metadata = support.get("metadata") if isinstance(support.get("metadata"), dict) else {}
    snapshot: dict[str, Any] = {
        "item_id": str(support.get("item_id") or ""),
        "source_evidence": sorted(_sources(support)),
    }
    if isinstance(metadata.get("click_point"), dict):
        snapshot["click_point"] = deepcopy(metadata["click_point"])
    if isinstance(metadata.get("coordinate_validation"), dict):
        snapshot["coordinate_validation"] = deepcopy(metadata["coordinate_validation"])
    if str(metadata.get("coordinate_source") or "").strip():
        snapshot["coordinate_source"] = str(metadata.get("coordinate_source"))
    return snapshot


def _semantic_container_suppression_reason(item: dict[str, Any], kept: list[dict[str, Any]]) -> str:
    item_type = str(item.get("item_type") or "").casefold()
    evidence_level = str(item.get("evidence_level") or "").casefold()
    role = str(item.get("role") or "").casefold()
    if item_type not in {"layout", "readable"}:
        return ""
    if evidence_level not in {"semantic_region_only", "ocr_text_only"}:
        return ""
    if role in {"button", "link", "input", "edit", "textbox", "text field"}:
        return ""
    item_area = _bbox_area(item.get("bbox"))
    if item_area <= 0:
        return ""
    contained = [
        existing
        for existing in kept
        if _contains(item.get("bbox"), existing.get("bbox")) >= 0.85
        and _bbox_area(existing.get("bbox")) > 0
        and item_area >= _bbox_area(existing.get("bbox")) * 3
    ]
    if len(contained) >= 1:
        return "semantic_container_overlaps_interactable_children"
    return ""


def _suppressed_entry(item: dict[str, Any], reason: str, kept_item: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "item_id": str(item.get("item_id") or ""),
        "label": str(item.get("label") or item.get("text") or ""),
        "reason": reason,
        "kept_item_id": str((kept_item or {}).get("item_id") or ""),
        "item": deepcopy(item),
    }


def _count_suppression_reasons(suppressed: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in suppressed:
        reason = str(entry.get("reason") or "unknown").strip() or "unknown"
        counts[reason] = int(counts.get(reason, 0)) + 1
    return dict(sorted(counts.items()))


def _count_overlap_pairs(items: list[dict[str, Any]]) -> int:
    count = 0
    for left_index, left in enumerate(items):
        for right in items[left_index + 1 :]:
            if _iou(left.get("bbox"), right.get("bbox")) >= 0.2 or _mutual_containment(left.get("bbox"), right.get("bbox")) >= 0.8:
                count += 1
    return count


def _evidence_score(item: dict[str, Any]) -> int:
    sources = {
        str(value).casefold()
        for value in item.get("source_evidence", [])
        if str(value or "").strip()
    } if isinstance(item.get("source_evidence"), list) else set()
    score = 0
    if "calibrated_target" in sources:
        score += 50
    if "execute_candidate_result" in sources:
        score += 45
    if "uia" in sources:
        score += 35
    if "omniparser" in sources:
        score += 25
    if "vision" in sources:
        score += 15
    if "ocr" in sources:
        score += 5
    if str(item.get("item_type") or "").casefold() in {"actionable", "form_field"}:
        score += 20
    interactable = item.get("interactable_evidence") if isinstance(item.get("interactable_evidence"), dict) else {}
    if any(bool(value) for value in interactable.values()):
        score += 15
    return score


def _label_key(item: dict[str, Any]) -> str:
    return " ".join(str(item.get("label") or item.get("text") or "").casefold().split())


def _role_key(item: dict[str, Any]) -> str:
    role = str(item.get("role") or "").casefold()
    if role in {"edit", "textbox", "text field", "input"}:
        return "input"
    if role in {"button", "icon_button", "nav text action"}:
        return "button"
    return role


def _bbox_area(value: Any) -> float:
    bbox = value if isinstance(value, dict) else {}
    return max(0.0, _float(bbox.get("w"))) * max(0.0, _float(bbox.get("h")))


def _iou(left: Any, right: Any) -> float:
    intersection = _intersection_area(left, right)
    if intersection <= 0:
        return 0.0
    union = _bbox_area(left) + _bbox_area(right) - intersection
    return 0.0 if union <= 0 else intersection / union


def _mutual_containment(left: Any, right: Any) -> float:
    intersection = _intersection_area(left, right)
    smaller = min(_bbox_area(left), _bbox_area(right))
    return 0.0 if smaller <= 0 else intersection / smaller


def _contains(outer: Any, inner: Any) -> float:
    intersection = _intersection_area(outer, inner)
    inner_area = _bbox_area(inner)
    return 0.0 if inner_area <= 0 else intersection / inner_area


def _intersection_area(left: Any, right: Any) -> float:
    lb = left if isinstance(left, dict) else {}
    rb = right if isinstance(right, dict) else {}
    lx1 = _float(lb.get("x"))
    ly1 = _float(lb.get("y"))
    lx2 = lx1 + max(0.0, _float(lb.get("w")))
    ly2 = ly1 + max(0.0, _float(lb.get("h")))
    rx1 = _float(rb.get("x"))
    ry1 = _float(rb.get("y"))
    rx2 = rx1 + max(0.0, _float(rb.get("w")))
    ry2 = ry1 + max(0.0, _float(rb.get("h")))
    width = max(0.0, min(lx2, rx2) - max(lx1, rx1))
    height = max(0.0, min(ly2, ry2) - max(ly1, ry1))
    return width * height


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
