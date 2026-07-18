from __future__ import annotations

from typing import Any


def build_coarse_region_proposals(
    items: list[dict[str, Any]],
    image_size: dict[str, Any],
) -> dict[str, Any]:
    """从原子元素证据生成少量、匿名、原图坐标的粗区域候选。"""

    width = max(1, int(image_size.get("width") or 0))
    height = max(1, int(image_size.get("height") or 0))
    screen = {"x": 0, "y": 0, "w": width, "h": height}
    elements = _normalize_elements(items, screen)
    x_cuts = _axis_cuts(elements, screen, axis="x")
    y_cuts = _axis_cuts(elements, screen, axis="y")
    edge_bands = _edge_bands(elements, screen)

    major_boxes, major_source = _major_partition(screen, x_cuts, y_cuts, edge_bands)
    major_boxes = _merge_tiny_neighbors(major_boxes, screen)
    proposals = [
        _proposal(
            proposal_id=f"P{index}",
            box=box,
            level=1,
            sources=major_source,
            elements=elements,
            screen=screen,
            boundary_strength=_boundary_strength(box, x_cuts, y_cuts, screen),
        )
        for index, box in enumerate(major_boxes[:8], start=1)
    ]

    child_boxes = _child_proposals(major_boxes, elements, screen)
    for child_box, sources in child_boxes[: max(0, 10 - len(proposals))]:
        proposals.append(
            _proposal(
                proposal_id=f"P{len(proposals) + 1}",
                box=child_box,
                level=2,
                sources=sources,
                elements=elements,
                screen=screen,
                boundary_strength=_boundary_strength(child_box, x_cuts, y_cuts, screen),
            )
        )

    return {
        "contract_version": "coarse_region_proposal_v1",
        "coordinate_space": "original_image",
        "image_size": {"width": width, "height": height},
        "proposals": proposals,
        "diagnostics": {
            "element_count": len(elements),
            "proposal_count": len(proposals),
            "level1_count": sum(item["proposal_level"] == 1 for item in proposals),
            "level2_count": sum(item["proposal_level"] == 2 for item in proposals),
            "x_cut_count": len(x_cuts),
            "y_cut_count": len(y_cuts),
            "edge_bands": edge_bands,
            "major_partition_source": major_source,
        },
    }


def _normalize_elements(items: list[dict[str, Any]], screen: dict[str, int]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[int, int, int, int]] = set()
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        box = _bbox(item.get("bbox"))
        if box is None or not _inside(box, screen):
            continue
        key = (box["x"], box["y"], box["w"], box["h"])
        if key in seen:
            continue
        seen.add(key)
        item_id = str(item.get("item_id") or item.get("candidate_id") or f"E{index}")
        normalized.append(
            {
                "element_id": item_id,
                "bbox": box,
                "source_types": _source_types(item),
            }
        )
    return normalized


def _axis_cuts(
    elements: list[dict[str, Any]],
    screen: dict[str, int],
    *,
    axis: str,
) -> list[dict[str, Any]]:
    size_key = "w" if axis == "x" else "h"
    cross_key = "h" if axis == "x" else "w"
    total = screen[size_key]
    cross_total = screen[cross_key]
    start_key = axis
    eligible = []
    for element in elements:
        box = element["bbox"]
        if box[size_key] / total >= 0.7 or box["w"] * box["h"] / (screen["w"] * screen["h"]) >= 0.18:
            continue
        eligible.append(box)
    bin_count = min(512, max(128, total // 2))
    occupancy = []
    for index in range(bin_count):
        point = (index + 0.5) * total / bin_count
        cross_intervals = []
        for box in eligible:
            if box[start_key] <= point <= box[start_key] + box[size_key]:
                if axis == "x":
                    cross_intervals.append((box["y"], box["y"] + box["h"]))
                else:
                    cross_intervals.append((box["x"], box["x"] + box["w"]))
        occupancy.append(_interval_coverage(cross_intervals) / cross_total)

    low_segments: list[tuple[int, int]] = []
    segment_start: int | None = None
    for index, value in enumerate([*occupancy, 1.0]):
        if value <= 0.03 and segment_start is None:
            segment_start = index
        elif value > 0.03 and segment_start is not None:
            low_segments.append((segment_start, index))
            segment_start = None

    minimum_gap = max(4, int(total * 0.004))
    cuts: list[dict[str, Any]] = []
    for start_bin, end_bin in low_segments:
        gap_start = int(start_bin * total / bin_count)
        gap_end = int(end_bin * total / bin_count)
        if gap_end - gap_start < minimum_gap:
            continue
        if gap_start <= total * 0.01 or gap_end >= total * 0.99:
            continue
        point = (gap_start + gap_end) // 2
        before = [item["bbox"] for item in elements if item["bbox"][start_key] + item["bbox"][size_key] / 2 < point]
        after = [item["bbox"] for item in elements if item["bbox"][start_key] + item["bbox"][size_key] / 2 >= point]
        if not before or not after:
            continue
        before_span = _cross_span_ratio(before, axis=axis, cross_total=cross_total)
        after_span = _cross_span_ratio(after, axis=axis, cross_total=cross_total)
        support = min(before_span, after_span)
        side_ratio = min(point / total, (total - point) / total)
        remainder_supported = max(before_span, after_span) >= 0.3 and side_ratio >= 0.22
        if support < 0.16 and not remainder_supported:
            continue
        gap_ratio = (gap_end - gap_start) / total
        effective_support = support if support >= 0.16 else max(before_span, after_span) * 0.45
        cuts.append(
            {
                "axis": axis,
                "point": point,
                "gap_start": gap_start,
                "gap_end": gap_end,
                "gap_ratio": round(gap_ratio, 4),
                "support": round(support, 4),
                "remainder_supported": remainder_supported,
                "score": round(min(1.0, gap_ratio * 2.0 + effective_support), 4),
            }
        )
    for aligned in _aligned_boundary_cuts(elements, screen, axis=axis):
        existing = next((item for item in cuts if abs(item["point"] - aligned["point"]) <= total * 0.015), None)
        if existing is None:
            cuts.append(aligned)
        elif aligned["score"] > existing["score"]:
            existing.update(aligned)
    cuts.sort(key=lambda item: item["score"], reverse=True)
    selected: list[dict[str, Any]] = []
    for cut in cuts:
        if all(abs(cut["point"] - prior["point"]) >= total * 0.1 for prior in selected):
            selected.append(cut)
        if len(selected) == 3:
            break
    return sorted(selected, key=lambda item: item["point"])


def _aligned_boundary_cuts(
    elements: list[dict[str, Any]],
    screen: dict[str, int],
    *,
    axis: str,
) -> list[dict[str, Any]]:
    size_key = "w" if axis == "x" else "h"
    start_key = axis
    total = screen[size_key]
    cross_total = screen["h" if axis == "x" else "w"]
    tolerance = max(3, int(total * 0.004))
    starts: list[int] = []
    ends: list[int] = []
    for element in elements:
        box = element["bbox"]
        if box[size_key] / total >= 0.7:
            continue
        starts.append(box[start_key])
        ends.append(box[start_key] + box[size_key])
    positions = sorted(set(starts + ends))
    clusters: list[list[int]] = []
    for position in positions:
        if not clusters or position - clusters[-1][-1] > tolerance:
            clusters.append([position])
        else:
            clusters[-1].append(position)

    cuts: list[dict[str, Any]] = []
    for cluster in clusters:
        point = round(sum(cluster) / len(cluster))
        if point <= total * 0.01 or point >= total * 0.99:
            continue
        start_votes = sum(abs(value - point) <= tolerance for value in starts)
        end_votes = sum(abs(value - point) <= tolerance for value in ends)
        if start_votes < 2 or end_votes < 2:
            continue
        before = [item["bbox"] for item in elements if item["bbox"][start_key] + item["bbox"][size_key] / 2 < point]
        after = [item["bbox"] for item in elements if item["bbox"][start_key] + item["bbox"][size_key] / 2 >= point]
        if not before or not after:
            continue
        before_span = _cross_span_ratio(before, axis=axis, cross_total=cross_total)
        after_span = _cross_span_ratio(after, axis=axis, cross_total=cross_total)
        support = min(before_span, after_span)
        if support < 0.25:
            continue
        vote_strength = min(0.25, min(start_votes, end_votes) / 20)
        cuts.append(
            {
                "axis": axis,
                "point": point,
                "gap_start": point,
                "gap_end": point,
                "gap_ratio": 0.0,
                "support": round(support, 4),
                "remainder_supported": False,
                "aligned_edge_votes": {"starts": start_votes, "ends": end_votes},
                "score": round(min(1.0, support + vote_strength), 4),
            }
        )
    return cuts


def _edge_bands(elements: list[dict[str, Any]], screen: dict[str, int]) -> dict[str, int | None]:
    width = screen["w"]
    height = screen["h"]
    top_items = [item["bbox"] for item in elements if item["bbox"]["y"] < height * 0.14 and item["bbox"]["h"] < height * 0.2]
    bottom_items = [
        item["bbox"]
        for item in elements
        if item["bbox"]["y"] + item["bbox"]["h"] > height * 0.86 and item["bbox"]["h"] < height * 0.2
    ]
    top_end = None
    if top_items and _interval_coverage([(box["x"], box["x"] + box["w"]) for box in top_items]) / width >= 0.1:
        top_end = min(height - 1, max(box["y"] + box["h"] for box in top_items) + max(4, int(height * 0.012)))
    bottom_start = None
    if bottom_items and _interval_coverage([(box["x"], box["x"] + box["w"]) for box in bottom_items]) / width >= 0.1:
        bottom_start = max(1, min(box["y"] for box in bottom_items) - max(4, int(height * 0.012)))
    if top_end is not None and bottom_start is not None and bottom_start <= top_end + height * 0.15:
        bottom_start = None
    return {"top_end": top_end, "bottom_start": bottom_start}


def _major_partition(
    screen: dict[str, int],
    x_cuts: list[dict[str, Any]],
    y_cuts: list[dict[str, Any]],
    edge_bands: dict[str, int | None],
) -> tuple[list[dict[str, int]], list[str]]:
    x_score = sum(float(item["score"]) for item in x_cuts[:2])
    y_score = sum(float(item["score"]) for item in y_cuts[:2])
    supported_x_columns = (
        len(x_cuts) >= 2
        and any(float(item["support"]) >= 0.72 for item in x_cuts[:2])
        and all(float(item["support"]) >= 0.72 or bool(item.get("remainder_supported")) for item in x_cuts[:2])
    )
    edge_partition_available = edge_bands.get("top_end") is not None or edge_bands.get("bottom_start") is not None or bool(y_cuts)
    if x_cuts and (supported_x_columns or (not edge_partition_available and x_score >= y_score * 1.05)):
        return _cells_from_cuts(screen, "x", x_cuts[:2]), ["x_whitespace_partition", "element_cluster"]

    top_end = edge_bands.get("top_end")
    bottom_start = edge_bands.get("bottom_start")
    if top_end is not None or bottom_start is not None:
        boundaries = [0]
        if isinstance(top_end, int):
            boundaries.append(top_end)
        if isinstance(bottom_start, int):
            boundaries.append(bottom_start)
        boundaries.append(screen["h"])
        boxes = [
            {"x": 0, "y": start, "w": screen["w"], "h": end - start}
            for start, end in zip(sorted(set(boundaries)), sorted(set(boundaries))[1:])
            if end > start
        ]
        return boxes, ["y_whitespace_partition", "remainder_region"]

    if y_cuts:
        return _cells_from_cuts(screen, "y", y_cuts[:2]), ["y_whitespace_partition", "element_cluster"]
    if x_cuts:
        return _cells_from_cuts(screen, "x", x_cuts[:2]), ["x_whitespace_partition", "element_cluster"]

    midpoint = max(1, min(screen["h"] - 1, screen["h"] // 2))
    return (
        [
            {"x": 0, "y": 0, "w": screen["w"], "h": midpoint},
            {"x": 0, "y": midpoint, "w": screen["w"], "h": screen["h"] - midpoint},
        ],
        ["remainder_region"],
    )


def _cells_from_cuts(
    screen: dict[str, int],
    axis: str,
    cuts: list[dict[str, Any]],
) -> list[dict[str, int]]:
    total = screen["w"] if axis == "x" else screen["h"]
    boundaries = [0, *[int(item["point"]) for item in cuts], total]
    boxes = []
    for start, end in zip(boundaries, boundaries[1:]):
        if axis == "x":
            boxes.append({"x": start, "y": 0, "w": end - start, "h": screen["h"]})
        else:
            boxes.append({"x": 0, "y": start, "w": screen["w"], "h": end - start})
    return boxes


def _merge_tiny_neighbors(boxes: list[dict[str, int]], screen: dict[str, int]) -> list[dict[str, int]]:
    if len(boxes) <= 1:
        return boxes
    merged = [dict(box) for box in boxes]
    index = 0
    screen_area = screen["w"] * screen["h"]
    while index < len(merged):
        box = merged[index]
        if box["w"] * box["h"] / screen_area >= 0.045 or len(merged) <= 2:
            index += 1
            continue
        target_index = index - 1 if index > 0 else 1
        target = merged[target_index]
        union = _union([box, target])
        merged[target_index] = union
        merged.pop(index)
        if target_index < index:
            index = max(0, index - 1)
    return merged


def _child_proposals(
    parents: list[dict[str, int]],
    elements: list[dict[str, Any]],
    screen: dict[str, int],
) -> list[tuple[dict[str, int], list[str]]]:
    children: list[tuple[dict[str, int], list[str]]] = []
    for parent in parents:
        contained = [item for item in elements if _inside(item["bbox"], parent)]
        if not contained:
            continue
        for edge in ("top", "bottom"):
            candidates = []
            for item in contained:
                box = item["bbox"]
                if box["w"] / parent["w"] < 0.42:
                    continue
                if edge == "top" and box["y"] <= parent["y"] + parent["h"] * 0.22:
                    candidates.append(box)
                if edge == "bottom" and box["y"] + box["h"] >= parent["y"] + parent["h"] * 0.78:
                    candidates.append(box)
            if not candidates:
                continue
            envelope = _union(candidates)
            pad = max(2, int(min(screen["w"], screen["h"]) * 0.006))
            top = max(parent["y"], envelope["y"] - pad)
            bottom = min(parent["y"] + parent["h"], envelope["y"] + envelope["h"] + pad)
            child = {"x": parent["x"], "y": top, "w": parent["w"], "h": bottom - top}
            if child["h"] / parent["h"] < 0.45:
                children.append((child, ["element_cluster", "remainder_region"]))
    unique: list[tuple[dict[str, int], list[str]]] = []
    seen: set[tuple[int, int, int, int]] = set()
    for box, sources in children:
        key = (box["x"], box["y"], box["w"], box["h"])
        if key not in seen:
            seen.add(key)
            unique.append((box, sources))
    return unique


def _proposal(
    *,
    proposal_id: str,
    box: dict[str, int],
    level: int,
    sources: list[str],
    elements: list[dict[str, Any]],
    screen: dict[str, int],
    boundary_strength: float,
) -> dict[str, Any]:
    contained = [item for item in elements if _inside(item["bbox"], box)]
    occupied = sum(item["bbox"]["w"] * item["bbox"]["h"] for item in contained)
    area = max(1, box["w"] * box["h"])
    source_types = sorted({source for item in contained for source in item["source_types"]}) or ["geometry"]
    touches = []
    tolerance = max(2, int(min(screen["w"], screen["h"]) * 0.01))
    if box["x"] <= tolerance:
        touches.append("left")
    if box["y"] <= tolerance:
        touches.append("top")
    if screen["w"] - (box["x"] + box["w"]) <= tolerance:
        touches.append("right")
    if screen["h"] - (box["y"] + box["h"]) <= tolerance:
        touches.append("bottom")
    return {
        "proposal_id": proposal_id,
        "candidate_id": proposal_id,
        "bbox": box,
        "proposal_level": level,
        "generation_sources": sorted(set(sources)),
        "contained_element_ids": [item["element_id"] for item in contained],
        "touches_edges": touches,
        "area_ratio": round(area / (screen["w"] * screen["h"]), 4),
        "evidence": {
            "separator_strength": round(boundary_strength, 4),
            "whitespace_boundary_strength": round(boundary_strength, 4),
            "element_density": round(min(1.0, occupied / area), 4),
        },
        "coordinate_space": "original_image",
        "element_count": len(contained),
        "source_types": source_types,
    }


def _boundary_strength(
    box: dict[str, int],
    x_cuts: list[dict[str, Any]],
    y_cuts: list[dict[str, Any]],
    screen: dict[str, int],
) -> float:
    boundaries = [box["x"], box["x"] + box["w"], box["y"], box["y"] + box["h"]]
    scores = []
    for cut in x_cuts:
        if min(abs(boundaries[0] - cut["point"]), abs(boundaries[1] - cut["point"])) <= screen["w"] * 0.03:
            scores.append(float(cut["score"]))
    for cut in y_cuts:
        if min(abs(boundaries[2] - cut["point"]), abs(boundaries[3] - cut["point"])) <= screen["h"] * 0.03:
            scores.append(float(cut["score"]))
    return min(1.0, max(scores, default=0.5))


def _bbox(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        box = {key: int(value.get(key) or 0) for key in ("x", "y", "w", "h")}
    except (TypeError, ValueError):
        return None
    return box if box["w"] > 0 and box["h"] > 0 else None


def _inside(inner: dict[str, int], outer: dict[str, int]) -> bool:
    return (
        inner["x"] >= outer["x"]
        and inner["y"] >= outer["y"]
        and inner["x"] + inner["w"] <= outer["x"] + outer["w"]
        and inner["y"] + inner["h"] <= outer["y"] + outer["h"]
    )


def _source_types(item: dict[str, Any]) -> list[str]:
    sources = [str(value).strip() for value in item.get("sources", []) if str(value).strip()] if isinstance(item.get("sources"), list) else []
    source = str(item.get("source") or "").strip()
    if source:
        sources.append(source)
    return sorted(set(sources)) or ["unknown"]


def _merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def _interval_coverage(intervals: list[tuple[int, int]]) -> int:
    return sum(end - start for start, end in _merge_intervals(intervals))


def _cross_span_ratio(boxes: list[dict[str, int]], *, axis: str, cross_total: int) -> float:
    intervals = [(box["y"], box["y"] + box["h"]) for box in boxes] if axis == "x" else [(box["x"], box["x"] + box["w"]) for box in boxes]
    return min(1.0, _interval_coverage(intervals) / cross_total)


def _union(boxes: list[dict[str, int]]) -> dict[str, int]:
    left = min(box["x"] for box in boxes)
    top = min(box["y"] for box in boxes)
    right = max(box["x"] + box["w"] for box in boxes)
    bottom = max(box["y"] + box["h"] for box in boxes)
    return {"x": left, "y": top, "w": right - left, "h": bottom - top}
