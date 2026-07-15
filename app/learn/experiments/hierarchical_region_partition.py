from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image


SCHEMA_VERSION = "hierarchical_region_partition_mvp_v1"
ALLOWED_ROLES = {"navigation", "list", "content", "toolbar", "composer", "status", "media", "unknown"}


def _bbox(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        parsed = {key: int(value.get(key) or 0) for key in ("x", "y", "w", "h")}
    except (TypeError, ValueError):
        return None
    return parsed if parsed["w"] > 0 and parsed["h"] > 0 else None


def _inside(inner: dict[str, int], outer: dict[str, int]) -> bool:
    return (
        inner["x"] >= outer["x"]
        and inner["y"] >= outer["y"]
        and inner["x"] + inner["w"] <= outer["x"] + outer["w"]
        and inner["y"] + inner["h"] <= outer["y"] + outer["h"]
    )


def _union(boxes: list[dict[str, int]]) -> dict[str, int] | None:
    if not boxes:
        return None
    left = min(item["x"] for item in boxes)
    top = min(item["y"] for item in boxes)
    right = max(item["x"] + item["w"] for item in boxes)
    bottom = max(item["y"] + item["h"] for item in boxes)
    return {"x": left, "y": top, "w": right - left, "h": bottom - top}


def _iou(left: dict[str, int], right: dict[str, int]) -> float:
    x1 = max(left["x"], right["x"])
    y1 = max(left["y"], right["y"])
    x2 = min(left["x"] + left["w"], right["x"] + right["w"])
    y2 = min(left["y"] + left["h"], right["y"] + right["h"])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    union = left["w"] * left["h"] + right["w"] * right["h"] - intersection
    return intersection / union if union else 0.0


def _source_types(item: dict[str, Any]) -> list[str]:
    values = [str(value).strip() for value in item.get("sources", []) if str(value).strip()] if isinstance(item.get("sources"), list) else []
    source = str(item.get("source") or "").strip()
    if source:
        values.append(source)
    return sorted(set(values)) or ["unknown"]


def build_anonymous_candidates(items: list[dict[str, Any]], image_size: dict[str, Any]) -> list[dict[str, Any]]:
    width = max(1, int(image_size.get("width") or 0))
    height = max(1, int(image_size.get("height") or 0))
    candidates_by_bbox: dict[tuple[int, int, int, int], dict[str, Any]] = {}
    for item in items:
        box = _bbox(item.get("bbox"))
        if box is None or not _inside(box, {"x": 0, "y": 0, "w": width, "h": height}):
            continue
        bbox_key = (box["x"], box["y"], box["w"], box["h"])
        existing = candidates_by_bbox.get(bbox_key)
        if existing is not None:
            existing["element_count"] += 1
            existing["source_types"] = sorted(set(existing["source_types"] + _source_types(item)))
            continue
        touches = []
        tolerance = max(2, int(min(width, height) * 0.01))
        if box["x"] <= tolerance:
            touches.append("left")
        if box["y"] <= tolerance:
            touches.append("top")
        if width - (box["x"] + box["w"]) <= tolerance:
            touches.append("right")
        if height - (box["y"] + box["h"]) <= tolerance:
            touches.append("bottom")
        candidates_by_bbox[bbox_key] = {
            "source_item_id": str(item.get("item_id") or item.get("candidate_id") or ""),
            "bbox": box,
            "coordinate_space": "original_image",
            "touches_edges": touches,
            "width_ratio": round(box["w"] / width, 4),
            "height_ratio": round(box["h"] / height, 4),
            "element_count": 1,
            "source_types": _source_types(item),
        }
    selected = _limit_candidates(list(candidates_by_bbox.values()), width=width, height=height, limit=96)
    for index, candidate in enumerate(selected, start=1):
        candidate["candidate_id"] = f"C{index}"
    return selected


def _limit_candidates(candidates: list[dict[str, Any]], *, width: int, height: int, limit: int) -> list[dict[str, Any]]:
    if len(candidates) <= limit:
        return candidates
    buckets: dict[tuple[int, int], dict[str, Any]] = {}
    for candidate in candidates:
        box = candidate["bbox"]
        center_x = box["x"] + box["w"] / 2
        center_y = box["y"] + box["h"] / 2
        bucket = (min(7, int(center_x / width * 8)), min(5, int(center_y / height * 6)))
        current = buckets.get(bucket)
        if current is None or _candidate_priority(candidate) > _candidate_priority(current):
            buckets[bucket] = candidate
    selected_ids = {id(item) for item in buckets.values()}
    selected = [item for item in candidates if id(item) in selected_ids]
    remaining = [item for item in candidates if id(item) not in selected_ids]
    remaining.sort(key=_candidate_priority, reverse=True)
    selected.extend(remaining[: max(0, limit - len(selected))])
    selected.sort(key=lambda item: (item["bbox"]["y"], item["bbox"]["x"], -item["bbox"]["w"] * item["bbox"]["h"]))
    return selected[:limit]


def _candidate_priority(candidate: dict[str, Any]) -> tuple[int, int, int]:
    box = candidate["bbox"]
    return (
        box["w"] * box["h"],
        len(candidate.get("touches_edges") or []),
        len(candidate.get("source_types") or []),
    )


def _disconnected(boxes: list[dict[str, int]], union_box: dict[str, int] | None) -> bool:
    if len(boxes) < 2 or union_box is None:
        return False
    occupied = sum(item["w"] * item["h"] for item in boxes)
    union_area = union_box["w"] * union_box["h"]
    if union_area <= 0 or occupied / union_area >= 0.35:
        return False
    for index, left in enumerate(boxes):
        for right in boxes[index + 1 :]:
            x_gap = max(0, max(left["x"], right["x"]) - min(left["x"] + left["w"], right["x"] + right["w"]))
            y_gap = max(0, max(left["y"], right["y"]) - min(left["y"] + left["h"], right["y"] + right["h"]))
            if x_gap <= max(16, int(union_box["w"] * 0.08)) and y_gap <= max(16, int(union_box["h"] * 0.08)):
                return False
    return True


def compile_hierarchical_regions(
    model_payload: dict[str, Any],
    candidates: list[dict[str, Any]],
    image_size: dict[str, Any],
) -> dict[str, Any]:
    width = max(1, int(image_size.get("width") or 0))
    height = max(1, int(image_size.get("height") or 0))
    screen = {"x": 0, "y": 0, "w": width, "h": height}
    candidate_map = {str(item.get("candidate_id")): item for item in candidates if str(item.get("candidate_id") or "")}
    failures: list[dict[str, Any]] = []
    raw_regions = model_payload.get("regions") if isinstance(model_payload.get("regions"), list) else []
    if model_payload.get("schema_version") != SCHEMA_VERSION or not isinstance(model_payload.get("candidate_gaps", []), list):
        failures.append({"reason": "invalid_schema", "detail": "schema_version or candidate_gaps is invalid"})

    compiled_regions: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in raw_regions:
        if not isinstance(raw, dict):
            failures.append({"reason": "invalid_schema", "detail": "region must be an object"})
            continue
        region_id = str(raw.get("region_id") or "").strip()
        if not region_id or region_id in seen_ids:
            failures.append({"reason": "duplicate_or_missing_region_id", "region_id": region_id})
            continue
        seen_ids.add(region_id)
        source_ids = [str(value) for value in raw.get("source_candidate_ids", [])] if isinstance(raw.get("source_candidate_ids"), list) else []
        missing = [value for value in source_ids if value not in candidate_map]
        if missing:
            failures.append({"reason": "invalid_candidate_reference", "region_id": region_id, "candidate_ids": missing})
        boxes = [_bbox(candidate_map[value].get("bbox")) for value in source_ids if value in candidate_map]
        valid_boxes = [item for item in boxes if item is not None]
        union_box = _union(valid_boxes)
        if union_box is None:
            failures.append({"reason": "region_bbox_unavailable", "region_id": region_id})
        elif not _inside(union_box, screen):
            failures.append({"reason": "bbox_out_of_bounds", "region_id": region_id, "bbox": union_box})
        if _disconnected(valid_boxes, union_box):
            failures.append({"reason": "disconnected_candidate_union", "region_id": region_id})
        role = str(raw.get("optional_role") or "unknown")
        compiled_regions.append(
            {
                "region_id": region_id,
                "level": int(raw.get("level") or 0),
                "parent_id": str(raw.get("parent_id") or ""),
                "source_candidate_ids": source_ids,
                "content_summary": str(raw.get("content_summary") or ""),
                "optional_role": role if role in ALLOWED_ROLES else "unknown",
                "confidence": max(0.0, min(1.0, float(raw.get("confidence") or 0.0))),
                "children": [str(value) for value in raw.get("children", [])] if isinstance(raw.get("children"), list) else [],
                "bbox": union_box,
            }
        )

    regions_by_id = {item["region_id"]: item for item in compiled_regions}
    roots = [item for item in compiled_regions if item["parent_id"] == "root"]
    if not roots:
        failures.append({"reason": "no_valid_root_region"})
    for region in compiled_regions:
        if region["level"] not in {1, 2}:
            failures.append({"reason": "maximum_depth_exceeded", "region_id": region["region_id"]})
        parent_id = region["parent_id"]
        if parent_id != "root" and parent_id not in regions_by_id:
            failures.append({"reason": "invalid_parent_reference", "region_id": region["region_id"], "parent_id": parent_id})
        if parent_id in regions_by_id:
            parent = regions_by_id[parent_id]
            if parent.get("bbox") and region.get("bbox") and not _inside(region["bbox"], parent["bbox"]):
                failures.append({"reason": "child_outside_parent", "region_id": region["region_id"], "parent_id": parent_id})

    for region in compiled_regions:
        visited = {region["region_id"]}
        parent_id = region["parent_id"]
        while parent_id in regions_by_id:
            if parent_id in visited:
                failures.append({"reason": "parent_child_cycle", "region_id": region["region_id"]})
                break
            visited.add(parent_id)
            parent_id = regions_by_id[parent_id]["parent_id"]

    severe_overlap_count = 0
    for index, left in enumerate(compiled_regions):
        if left.get("bbox") is None:
            continue
        for right in compiled_regions[index + 1 :]:
            if right.get("bbox") is None or left["parent_id"] != right["parent_id"]:
                continue
            overlap = _iou(left["bbox"], right["bbox"])
            if overlap >= 0.4:
                severe_overlap_count += 1
                failures.append({"reason": "severe_sibling_overlap", "region_ids": [left["region_id"], right["region_id"]], "iou": round(overlap, 4)})

    assigned = {value for item in compiled_regions for value in item["source_candidate_ids"] if value in candidate_map}
    root_area = sum(item["bbox"]["w"] * item["bbox"]["h"] for item in roots if item.get("bbox"))
    coverage = min(1.0, root_area / (width * height))
    if roots and coverage < 0.2:
        failures.append({"reason": "insufficient_major_region_coverage", "coverage": round(coverage, 4)})
    unassigned_ratio = (len(candidate_map) - len(assigned)) / len(candidate_map) if candidate_map else 0.0
    if candidate_map and unassigned_ratio > 0.6:
        failures.append({"reason": "excessive_unassigned_candidates", "ratio": round(unassigned_ratio, 4)})

    return {
        "schema_version": SCHEMA_VERSION,
        "page_type": str(model_payload.get("page_type") or ""),
        "image_size": {"width": width, "height": height},
        "candidates": candidates,
        "regions": compiled_regions,
        "regions_by_id": regions_by_id,
        "unassigned_candidate_ids": sorted(set(candidate_map) - assigned),
        "candidate_gaps": model_payload.get("candidate_gaps", []) if isinstance(model_payload.get("candidate_gaps"), list) else [],
        "validator": {
            "valid": not failures,
            "failures": failures,
            "root_region_count": len(roots),
            "child_region_count": len(compiled_regions) - len(roots),
            "major_content_coverage": round(coverage, 4),
            "severe_overlap_count": severe_overlap_count,
            "unassigned_candidate_ratio": round(unassigned_ratio, 4),
            "candidate_gap_count": len(model_payload.get("candidate_gaps", [])) if isinstance(model_payload.get("candidate_gaps"), list) else 0,
            "disconnected_union_count": sum(item["reason"] == "disconnected_candidate_union" for item in failures),
        },
    }


@dataclass
class RegionFrame:
    image_path: Path
    compiled: dict[str, Any]

    def get_region(self, region_id: str) -> dict[str, Any]:
        region = self.compiled.get("regions_by_id", {}).get(region_id)
        if not isinstance(region, dict):
            raise KeyError(f"unknown region_id: {region_id}")
        return region

    def get_region_children(self, region_id: str) -> list[dict[str, Any]]:
        return [item for item in self.compiled.get("regions", []) if item.get("parent_id") == region_id]

    def crop_region(self, region_id: str, out_dir: Path) -> Path:
        region = self.get_region(region_id)
        box = _bbox(region.get("bbox"))
        if box is None:
            raise ValueError(f"region has no valid bbox: {region_id}")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{region_id}.png"
        with Image.open(self.image_path) as image:
            image.crop((box["x"], box["y"], box["x"] + box["w"], box["y"] + box["h"])).save(out_path)
        return out_path
