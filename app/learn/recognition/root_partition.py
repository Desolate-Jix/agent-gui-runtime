from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image

from app.learn.recognition.coarse_region_proposal import (
    _axis_cuts,
    _cells_from_cuts,
    _edge_bands,
    _normalize_elements,
    build_coarse_region_proposals,
)


_TOP_BAND_TOKENS = (
    "toolbar",
    "title_bar",
    "browser_chrome",
    "header",
    "menu",
    "navigation",
    "nav_",
    "window_control",
)
_BOTTOM_BAND_TOKENS = (
    "status_bar",
    "bottom_bar",
    "footer",
    "composer",
    "conversation_bottom_panel",
    "group_chat",
    "群组聊天",
)
_SIDE_NAVIGATION_TOKENS = (
    "navigation",
    "nav_",
    "sidebar",
    "side_bar",
    "nav_rail",
)


def build_deterministic_root_partition(
    items: list[dict[str, Any]],
    image_size: dict[str, Any],
    *,
    image_path: str = "",
    class_rule_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把现有原子证据编译为覆盖完整、同层不重叠的根级区域。"""

    width = max(1, int(image_size.get("width") or 0))
    height = max(1, int(image_size.get("height") or 0))
    normalized_size = {"width": width, "height": height}
    proposal_report = build_coarse_region_proposals(items, normalized_size)
    diagnostics = dict(proposal_report.get("diagnostics") or {})
    level1, selection = _select_root_proposals(
        items,
        width=width,
        height=height,
        image_path=image_path,
        class_rule_profile=class_rule_profile,
    )
    diagnostics["root_selection"] = selection
    diagnostics["fallback"] = selection.get("fallback")

    root_regions = []
    for index, proposal in enumerate(level1, start=1):
        bbox = _bbox(proposal.get("bbox"))
        if bbox is None:
            continue
        root_regions.append(
            {
                "contract_version": "deterministic_root_region_v1",
                "region_no": index,
                "region_id": f"deterministic_root_{index}",
                "label": f"Root region {index}",
                "bbox": bbox,
                "item_ids": list(proposal.get("contained_element_ids") or _contained_item_ids(items, bbox)),
                "generation_sources": list(proposal.get("generation_sources") or []),
                "stage": "stage1_page_structure",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )

    validator = validate_root_partition(root_regions, normalized_size)
    return {
        "contract_version": "deterministic_root_partition_v1",
        "coordinate_space": "original_image",
        "image_size": normalized_size,
        "root_regions": root_regions,
        "validator": validator,
        "diagnostics": diagnostics,
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _select_root_proposals(
    items: list[dict[str, Any]],
    *,
    width: int,
    height: int,
    image_path: str = "",
    class_rule_profile: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    screen = {"x": 0, "y": 0, "w": width, "h": height}
    elements = _normalize_elements(items, screen)
    x_cuts = _axis_cuts(elements, screen, axis="x")
    y_cuts = _axis_cuts(elements, screen, axis="y")
    color_vertical_cuts = _color_block_boundary_cuts(
        image_path,
        width=width,
        height=height,
        axis="x",
    )
    color_horizontal_cuts = _color_block_boundary_cuts(
        image_path,
        width=width,
        height=height,
        axis="y",
    )
    image_separator_cuts = [
        *color_vertical_cuts,
        *_vertical_separator_cuts(image_path, width=width, height=height),
    ]
    image_horizontal_cuts = [
        *color_horizontal_cuts,
        *_horizontal_separator_cuts(image_path, width=width, height=height),
    ]
    raw_edge_bands = _edge_bands(elements, screen)
    edge_bands = _calibrate_edge_bands(
        raw_edge_bands,
        image_horizontal_cuts=image_horizontal_cuts,
        height=height,
        require_bottom_image_evidence=bool(str(image_path or "").strip()),
    )
    document_content_start = _full_width_document_content_start(
        items,
        width=width,
        height=height,
    )
    if document_content_start is not None and isinstance(edge_bands.get("top_end"), int):
        edge_bands["top_end"] = min(int(edge_bands["top_end"]), document_content_start)
    aligned_bottom_status_start = _aligned_bottom_status_start(
        items,
        width=width,
        height=height,
    )
    if edge_bands.get("bottom_start") is None and aligned_bottom_status_start is not None:
        edge_bands["bottom_start"] = aligned_bottom_status_start
    boxes: list[dict[str, int]] = []
    source = ""

    dominant_tabular_bbox = _dominant_tabular_container(
        items,
        width=width,
        height=height,
    )
    rejected_tabular_internal_cut = _has_only_tabular_internal_edge_cuts(
        x_cuts,
        image_separator_cuts=image_separator_cuts,
        tabular_bbox=dominant_tabular_bbox,
        width=width,
    )
    rejected_grid_internal_cut = (
        not image_separator_cuts
        and _looks_like_repeated_grid_column_cuts(x_cuts, width=width)
    )
    first_two_x = x_cuts[:2]
    supported_columns = (
        not rejected_tabular_internal_cut
        and not rejected_grid_internal_cut
        and len(first_two_x) == 2
        and any(float(cut.get("support") or 0.0) >= 0.72 for cut in first_two_x)
        and all(
            float(cut.get("support") or 0.0) >= 0.72
            or (
                bool(cut.get("remainder_supported"))
                and float(cut.get("gap_ratio") or 0.0) <= 0.35
            )
            for cut in first_two_x
        )
    )
    edge_cut = _select_supported_edge_cut(
        x_cuts,
        width=width,
        image_separator_cuts=image_separator_cuts,
    )
    if rejected_grid_internal_cut or rejected_tabular_internal_cut:
        edge_cut = None
    trusted_top_band_end = _trusted_top_band_end(
        items,
        image_horizontal_cuts=image_horizontal_cuts,
        width=width,
        height=height,
    )
    stacked_top_end = _stacked_top_control_end(
        items,
        image_horizontal_cuts=image_horizontal_cuts,
        width=width,
        height=height,
    )
    if document_content_start is not None:
        if trusted_top_band_end is not None:
            trusted_top_band_end = min(trusted_top_band_end, document_content_start)
        if stacked_top_end is not None:
            stacked_top_end = min(stacked_top_end, document_content_start)
    edge_rail_top_end = _strong_top_boundary_for_edge_rail(
        edge_bands=edge_bands,
        image_horizontal_cuts=image_horizontal_cuts,
        height=height,
    )
    centered_content_margin_pair = _centered_content_margin_pair(
        items,
        color_vertical_cuts=color_vertical_cuts,
        width=width,
        height=height,
        content_start=(
            edge_rail_top_end
            or trusted_top_band_end
            or stacked_top_end
            or edge_bands.get("top_end")
        ),
    )
    if centered_content_margin_pair is not None:
        edge_cut = None
        supported_columns = False
    primary_content_strategy = str(
        (class_rule_profile or {}).get("primary_content_strategy") or ""
    ).strip()
    class_rule_vertical_partition_suppressed = False
    class_rule_edge_partition_suppressed_without_navigation_evidence = False
    candidate_split_x = None
    if edge_cut is not None:
        candidate_split_x = int(edge_cut.get("point") or 0)
    elif supported_columns and first_two_x:
        candidate_split_x = int(first_two_x[0].get("point") or 0)
    if primary_content_strategy and candidate_split_x is not None and candidate_split_x > 0:
        content_start = int(
            edge_rail_top_end
            or trusted_top_band_end
            or stacked_top_end
            or edge_bands.get("top_end")
            or 0
        )
        has_explicit_side_navigation = _has_vertical_band_semantics(
            items,
            start=0,
            end=candidate_split_x,
            content_start=content_start,
            tokens=_SIDE_NAVIGATION_TOKENS,
        )
        if not has_explicit_side_navigation:
            edge_cut = None
            supported_columns = False
            class_rule_edge_partition_suppressed_without_navigation_evidence = True
            if primary_content_strategy == "independent_content_modules":
                class_rule_vertical_partition_suppressed = True
    bottom_start = edge_bands.get("bottom_start")
    bottom_supported = isinstance(bottom_start, int) and (
        (height - bottom_start) / height <= 0.08
        or _has_band_semantics(
            items,
            start=bottom_start,
            end=height,
            tokens=_BOTTOM_BAND_TOKENS,
        )
    )
    if rejected_tabular_internal_cut and trusted_top_band_end is not None:
        boxes = [
            {"x": 0, "y": 0, "w": width, "h": trusted_top_band_end},
            {
                "x": 0,
                "y": trusted_top_band_end,
                "w": width,
                "h": height - trusted_top_band_end,
            },
        ]
        source = "supported_top_band_above_tabular_content"
    elif edge_cut is not None and stacked_top_end is not None:
        split_x = int(edge_cut.get("point") or 0)
        content_bottom = int(bottom_start) if bottom_supported and int(bottom_start) > stacked_top_end else height
        boxes = [
            {"x": 0, "y": 0, "w": width, "h": stacked_top_end},
            {"x": 0, "y": stacked_top_end, "w": split_x, "h": content_bottom - stacked_top_end},
            {
                "x": split_x,
                "y": stacked_top_end,
                "w": width - split_x,
                "h": content_bottom - stacked_top_end,
            },
        ]
        if content_bottom < height:
            boxes.append({"x": 0, "y": content_bottom, "w": width, "h": height - content_bottom})
        source = (
            "stacked_top_controls_with_edge_rail_and_bottom"
            if content_bottom < height
            else "stacked_top_controls_with_edge_rail"
        )
    elif edge_cut is not None and trusted_top_band_end is not None:
        split_x = int(edge_cut.get("point") or 0)
        content_bottom = (
            int(bottom_start)
            if bottom_supported and int(bottom_start) > trusted_top_band_end
            else height
        )
        boxes = [
            {"x": 0, "y": 0, "w": width, "h": trusted_top_band_end},
            {
                "x": 0,
                "y": trusted_top_band_end,
                "w": split_x,
                "h": content_bottom - trusted_top_band_end,
            },
            {
                "x": split_x,
                "y": trusted_top_band_end,
                "w": width - split_x,
                "h": content_bottom - trusted_top_band_end,
            },
        ]
        if content_bottom < height:
            boxes.append({"x": 0, "y": content_bottom, "w": width, "h": height - content_bottom})
        source = (
            "supported_top_band_with_edge_rail_and_bottom"
            if content_bottom < height
            else "supported_top_band_with_edge_rail"
        )
    elif edge_cut is not None and edge_rail_top_end is not None:
        split_x = int(edge_cut.get("point") or 0)
        boxes = [
            {"x": 0, "y": 0, "w": split_x, "h": height},
            {"x": split_x, "y": 0, "w": width - split_x, "h": edge_rail_top_end},
            {
                "x": split_x,
                "y": edge_rail_top_end,
                "w": width - split_x,
                "h": height - edge_rail_top_end,
            },
        ]
        source = "full_height_edge_rail_with_right_top"
    elif edge_cut is not None and edge_cut.get("source") in {
        "image_long_vertical_separator",
        "image_color_block_boundary",
    }:
        boxes = _cells_from_cuts(screen, "x", [edge_cut])
        source = (
            "strong_color_block_vertical_partition"
            if edge_cut.get("source") == "image_color_block_boundary"
            else "supported_image_edge_rail"
        )
    elif supported_columns:
        if int(first_two_x[0].get("point") or 0) <= width * 0.22:
            boxes = _cells_from_cuts(screen, "x", [first_two_x[0]])
            source = "supported_edge_rail_with_child_columns"
        else:
            boxes = _cells_from_cuts(screen, "x", first_two_x)
            source = "supported_vertical_columns"
    else:
        if edge_cut is not None:
            boxes = _cells_from_cuts(screen, "x", [edge_cut])
            source = "supported_edge_rail"

    if not boxes:
        top_end = edge_bands.get("top_end")
        top_supported = isinstance(top_end, int) and (
            top_end / height <= 0.16
            or _is_visually_supported_top_band(
                top_end,
                image_horizontal_cuts=image_horizontal_cuts,
                height=height,
            )
            or _has_band_semantics(items, start=0, end=top_end, tokens=_TOP_BAND_TOKENS)
        )
        boundaries = [0]
        if top_supported:
            boundaries.append(int(top_end))
        if bottom_supported:
            boundaries.append(int(bottom_start))
        boundaries.append(height)
        boundaries = sorted(set(boundaries))
        if len(boundaries) > 2:
            boxes = [
                {"x": 0, "y": start, "w": width, "h": end - start}
                for start, end in zip(boundaries, boundaries[1:])
                if end > start
            ]
            source = "supported_horizontal_edge_bands"

    if not boxes:
        strong_color_horizontal = [
            cut
            for cut in color_horizontal_cuts
            if (
                height * 0.03 <= int(cut.get("point") or 0) <= height * 0.20
                or height * 0.80 <= int(cut.get("point") or 0) <= height * 0.97
            )
            and float(cut.get("support") or 0.0) >= 0.72
            and float(cut.get("color_distance") or 0.0) >= 40.0
        ]
        if strong_color_horizontal:
            color_cut = max(
                strong_color_horizontal,
                key=lambda cut: (
                    float(cut.get("support") or 0.0),
                    float(cut.get("color_distance") or 0.0),
                ),
            )
            boxes = _cells_from_cuts(screen, "y", [color_cut])
            source = "strong_color_block_horizontal_partition"

    fallback = None
    if not boxes:
        boxes = [screen]
        source = "single_root_no_supported_cut"
        fallback = source
    proposals = [
        {
            "proposal_id": f"P{index}",
            "bbox": box,
            "generation_sources": [source],
            "contained_element_ids": _contained_item_ids(items, box),
        }
        for index, box in enumerate(boxes, start=1)
    ]
    return proposals, {
        "strategy": source,
        "fallback": fallback,
        "x_cuts": x_cuts,
        "image_separator_cuts": image_separator_cuts,
        "image_horizontal_cuts": image_horizontal_cuts,
        "color_vertical_cuts": color_vertical_cuts,
        "color_horizontal_cuts": color_horizontal_cuts,
        "raw_edge_bands": raw_edge_bands,
        "y_cuts": y_cuts,
        "edge_bands": edge_bands,
        "rejected_grid_internal_cut": rejected_grid_internal_cut,
        "rejected_tabular_internal_cut": rejected_tabular_internal_cut,
        "dominant_tabular_bbox": dominant_tabular_bbox,
        "trusted_top_band_end": trusted_top_band_end,
        "document_content_start": document_content_start,
        "edge_rail_top_end": edge_rail_top_end,
        "aligned_bottom_status_start": aligned_bottom_status_start,
        "centered_content_margin_pair_rejected": centered_content_margin_pair is not None,
        "centered_content_margin_pair": centered_content_margin_pair,
        "primary_content_strategy": primary_content_strategy,
        "class_rule_vertical_partition_suppressed": class_rule_vertical_partition_suppressed,
        "class_rule_edge_partition_suppressed_without_navigation_evidence": (
            class_rule_edge_partition_suppressed_without_navigation_evidence
        ),
    }


def _full_width_document_content_start(
    items: list[dict[str, Any]],
    *,
    width: int,
    height: int,
) -> int | None:
    """用全宽文档节点收紧被网页横幅放大的顶栏。"""

    starts: list[int] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        bbox = _bbox(item.get("bbox"))
        if (
            bbox is None
            or bbox["y"] < height * 0.03
            or bbox["y"] > height * 0.30
            or bbox["x"] > width * 0.03
            or bbox["w"] < width * 0.80
            or bbox["h"] < height * 0.50
        ):
            continue
        semantic_text = " ".join(
            str(item.get(key) or "").casefold()
            for key in ("item_id", "candidate_id", "role", "item_type", "label", "layout")
        )
        if not any(token in semantic_text for token in ("document", "web_area", "web area")):
            continue
        starts.append(bbox["y"])
    if not starts:
        return None

    candidate = min(starts)
    top_control_evidence = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        bbox = _bbox(item.get("bbox"))
        if bbox is None or bbox["y"] + bbox["h"] > candidate + height * 0.02:
            continue
        semantic_text = " ".join(
            str(item.get(key) or "").casefold()
            for key in ("item_id", "candidate_id", "role", "item_type", "label", "layout")
        )
        if any(token in semantic_text for token in ("toolbar", "address", "input", "window control")):
            top_control_evidence += 1
    return candidate if top_control_evidence > 0 else None


def _is_visually_supported_top_band(
    top_end: int,
    *,
    image_horizontal_cuts: list[dict[str, Any]],
    height: int,
) -> bool:
    if top_end <= 0 or top_end / max(1, height) > 0.2:
        return False
    return any(
        abs(int(cut.get("point") or 0) - top_end) <= max(2, int(height * 0.005))
        and float(cut.get("support") or 0.0) >= 0.45
        for cut in image_horizontal_cuts
    )


def _aligned_bottom_status_start(
    items: list[dict[str, Any]],
    *,
    width: int,
    height: int,
) -> int | None:
    candidates: list[dict[str, int]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        bbox = _bbox(item.get("bbox"))
        if bbox is None:
            continue
        center_y = bbox["y"] + bbox["h"] / 2
        if (
            center_y < height * 0.94
            or bbox["h"] > height * 0.06
            or bbox["w"] > width * 0.35
        ):
            continue
        candidates.append(bbox)
    if len(candidates) < 2:
        return None

    maximum_center_delta = max(6, int(height * 0.012))
    minimum_center_span = width * 0.65
    pairs: list[tuple[dict[str, int], dict[str, int]]] = []
    for index, left in enumerate(candidates):
        left_center_x = left["x"] + left["w"] / 2
        left_center_y = left["y"] + left["h"] / 2
        for right in candidates[index + 1 :]:
            right_center_x = right["x"] + right["w"] / 2
            right_center_y = right["y"] + right["h"] / 2
            if (
                abs(right_center_x - left_center_x) >= minimum_center_span
                and abs(right_center_y - left_center_y) <= maximum_center_delta
            ):
                pairs.append((left, right))
    if not pairs:
        return None
    pair = max(
        pairs,
        key=lambda values: min(
            values[0]["y"] + values[0]["h"] / 2,
            values[1]["y"] + values[1]["h"] / 2,
        ),
    )
    padding = max(3, int(height * 0.006))
    return max(int(height * 0.9), min(pair[0]["y"], pair[1]["y"]) - padding)


def _strong_top_boundary_for_edge_rail(
    *,
    edge_bands: dict[str, Any],
    image_horizontal_cuts: list[dict[str, Any]],
    height: int,
) -> int | None:
    top_end = edge_bands.get("top_end")
    if not isinstance(top_end, int) or top_end <= 0 or top_end > height * 0.35:
        return None
    limit = min(int(height * 0.2), top_end + max(2, int(height * 0.02)))
    candidates = [
        int(cut.get("point") or 0)
        for cut in image_horizontal_cuts
        if float(cut.get("support") or 0.0) >= 0.94
        and height * 0.03 <= int(cut.get("point") or 0) <= limit
    ]
    return max(candidates) if candidates else None


def _looks_like_repeated_grid_column_cuts(
    cuts: list[dict[str, Any]],
    *,
    width: int,
) -> bool:
    ordered = sorted(
        (cut for cut in cuts if int(cut.get("point") or 0) > 0),
        key=lambda cut: int(cut.get("point") or 0),
    )[:3]
    if len(ordered) < 3:
        return False
    points = [int(cut.get("point") or 0) for cut in ordered]
    spans = [points[0], points[1] - points[0], points[2] - points[1]]
    if points[0] > width * 0.22 or min(spans) <= 0:
        return False
    if not all(float(cut.get("support") or 0.0) >= 0.55 for cut in ordered):
        return False
    if not all(float(cut.get("gap_ratio") or 0.0) <= 0.01 for cut in ordered):
        return False
    return max(spans) / min(spans) <= 1.2


def _dominant_tabular_container(
    items: list[dict[str, Any]],
    *,
    width: int,
    height: int,
) -> dict[str, int] | None:
    candidates: list[dict[str, int]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        bbox = _bbox(item.get("bbox"))
        if bbox is None:
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        semantic_text = " ".join(
            str(value or "")
            for value in (
                item.get("role"),
                item.get("item_type"),
                item.get("layout"),
                metadata.get("control_type"),
                metadata.get("semantic_type"),
            )
        ).casefold()
        if not any(token in semantic_text for token in ("datagrid", "data_grid", "table", "gridview")):
            continue
        if (
            bbox["w"] < width * 0.75
            or bbox["h"] < height * 0.45
            or bbox["x"] > width * 0.25
        ):
            continue
        candidates.append(bbox)
    if not candidates:
        return None
    return max(candidates, key=lambda bbox: bbox["w"] * bbox["h"])


def _has_only_tabular_internal_edge_cuts(
    cuts: list[dict[str, Any]],
    *,
    image_separator_cuts: list[dict[str, Any]],
    tabular_bbox: dict[str, int] | None,
    width: int,
) -> bool:
    if tabular_bbox is None:
        return False
    tolerance = max(4, int(width * 0.015))
    left = tabular_bbox["x"]
    right = left + tabular_bbox["w"]
    candidate_points = [
        int(cut.get("point") or 0)
        for cut in [*cuts, *image_separator_cuts]
        if 0 < int(cut.get("point") or 0) <= width * 0.35
    ]
    if not candidate_points:
        return False
    if any(abs(point - left) <= tolerance for point in candidate_points):
        return False
    return all(left + tolerance < point < right - tolerance for point in candidate_points)


def _trusted_top_band_end(
    items: list[dict[str, Any]],
    *,
    image_horizontal_cuts: list[dict[str, Any]],
    width: int,
    height: int,
) -> int | None:
    candidate_ends: list[int] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        bbox = _bbox(item.get("bbox"))
        if (
            bbox is None
            or bbox["y"] > height * 0.03
            or bbox["x"] > width * 0.03
            or bbox["w"] < width * 0.8
            or bbox["h"] > height * 0.22
        ):
            continue
        semantic_text = " ".join(
            str(item.get(key) or "").casefold()
            for key in ("item_id", "candidate_id", "role", "item_type", "label", "layout", "section_id")
        )
        if not any(token in semantic_text for token in _TOP_BAND_TOKENS):
            continue
        candidate_ends.append(bbox["y"] + bbox["h"])
    if not candidate_ends:
        return None
    eligible_cuts = [
        int(cut.get("point") or 0)
        for cut in image_horizontal_cuts
        if float(cut.get("support") or 0.0) >= 0.75
    ]
    matches = [
        (abs(point - end), point)
        for end in candidate_ends
        for point in eligible_cuts
        if abs(point - end) <= height * 0.04
    ]
    if not matches:
        return None
    return min(matches)[1]


def _select_supported_edge_cut(
    cuts: list[dict[str, Any]],
    *,
    width: int,
    image_separator_cuts: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    color_eligible = [
        cut
        for cut in image_separator_cuts or []
        if cut.get("source") == "image_color_block_boundary"
        and width * 0.045 <= int(cut.get("point") or 0) <= width * 0.35
        and float(cut.get("support") or 0.0) >= 0.72
        and float(cut.get("color_distance") or 0.0) >= 40.0
    ]
    if color_eligible:
        return min(color_eligible, key=lambda cut: int(cut.get("point") or 0))
    image_eligible = [
        cut
        for cut in image_separator_cuts or []
        if width * 0.045 <= int(cut.get("point") or 0) <= width * 0.18
        and float(cut.get("score") or 0.0) >= 0.7
        and float(cut.get("support") or 0.0) >= 0.6
    ]
    if image_eligible:
        return min(image_eligible, key=lambda cut: int(cut.get("point") or 0))
    eligible = [
        cut
        for cut in cuts
        if int(cut.get("point") or 0) <= width * 0.18
        and float(cut.get("score") or 0.0) >= 0.45
        and float(cut.get("support") or 0.0) >= 0.3
    ]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda cut: (
            float(cut.get("support") or 0.0),
            float(cut.get("score") or 0.0),
            int(cut.get("point") or 0),
        ),
    )


def _centered_content_margin_pair(
    items: list[dict[str, Any]],
    *,
    color_vertical_cuts: list[dict[str, Any]],
    width: int,
    height: int,
    content_start: Any,
) -> dict[str, Any] | None:
    """识别居中内容面板两侧的空白外边距，避免把外边距误当侧栏。"""

    left_cuts = [
        cut
        for cut in color_vertical_cuts
        if width * 0.045 <= int(cut.get("point") or 0) <= width * 0.35
        and float(cut.get("support") or 0.0) >= 0.72
        and float(cut.get("color_distance") or 0.0) >= 40.0
    ]
    right_cuts = [
        cut
        for cut in color_vertical_cuts
        if width * 0.65 <= int(cut.get("point") or 0) <= width * 0.955
        and float(cut.get("support") or 0.0) >= 0.72
        and float(cut.get("color_distance") or 0.0) >= 40.0
    ]
    candidates: list[tuple[int, dict[str, Any], dict[str, Any], str]] = []
    for left in left_cuts:
        left_margin = int(left.get("point") or 0)
        for right in right_cuts:
            right_point = int(right.get("point") or 0)
            right_margin = width - right_point
            difference = abs(left_margin - right_margin)
            tolerance = max(int(width * 0.04), int(min(left_margin, right_margin) * 0.20))
            if right_point - left_margin < width * 0.40 or difference > tolerance:
                continue
            candidates.append((difference, left, right, "paired_visible_boundaries"))
    if not candidates:
        for left in left_cuts:
            left_boundary = int(left.get("point") or 0)
            mirrored_right = width - left_boundary
            if mirrored_right - left_boundary < width * 0.40:
                continue
            candidates.append(
                (
                    0,
                    left,
                    {
                        "point": mirrored_right,
                        "support": left.get("support"),
                        "color_distance": left.get("color_distance"),
                        "source": "mirrored_centered_margin_boundary",
                    },
                    "single_visible_boundary_with_mirrored_empty_margin",
                )
            )
        for right in right_cuts:
            right_boundary = int(right.get("point") or 0)
            mirrored_left = width - right_boundary
            if right_boundary - mirrored_left < width * 0.40:
                continue
            candidates.append(
                (
                    0,
                    {
                        "point": mirrored_left,
                        "support": right.get("support"),
                        "color_distance": right.get("color_distance"),
                        "source": "mirrored_centered_margin_boundary",
                    },
                    right,
                    "single_visible_boundary_with_mirrored_empty_margin",
                )
            )
    if not candidates:
        return None

    _, left_cut, right_cut, boundary_evidence = min(candidates, key=lambda value: value[0])
    left_boundary = int(left_cut.get("point") or 0)
    right_boundary = int(right_cut.get("point") or 0)
    start_y = max(0, min(height - 1, int(content_start or height * 0.08)))
    counts = {"left": 0, "center": 0, "right": 0}
    for item in items:
        bbox = _bbox(item.get("bbox")) if isinstance(item, dict) else None
        if bbox is None or bbox["w"] >= width * 0.60:
            continue
        center_x = bbox["x"] + bbox["w"] / 2
        center_y = bbox["y"] + bbox["h"] / 2
        if center_y < start_y:
            continue
        if center_x < left_boundary:
            counts["left"] += 1
        elif center_x >= right_boundary:
            counts["right"] += 1
        else:
            counts["center"] += 1

    outer_count = counts["left"] + counts["right"]
    if counts["center"] < 2 or outer_count > max(1, int(counts["center"] * 0.08)):
        return None
    return {
        "left_boundary": left_boundary,
        "right_boundary": right_boundary,
        "left_margin": left_boundary,
        "right_margin": width - right_boundary,
        "content_start": start_y,
        "evidence_counts": counts,
        "boundary_evidence": boundary_evidence,
        "reason": "symmetric_color_boundaries_with_empty_outer_margins",
    }


def _stacked_top_control_end(
    items: list[dict[str, Any]],
    *,
    image_horizontal_cuts: list[dict[str, Any]],
    width: int,
    height: int,
) -> int | None:
    candidates: list[dict[str, int]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        bbox = _bbox(item.get("bbox"))
        if not bbox or bbox["y"] > height * 0.18 or bbox["w"] < width * 0.8 or bbox["h"] > height * 0.22:
            continue
        value = " ".join(
            str(item.get(key) or "").casefold()
            for key in ("item_id", "candidate_id", "role", "item_type", "label", "layout", "section_id")
        )
        if not any(token in value for token in _TOP_BAND_TOKENS):
            continue
        if bbox not in candidates:
            candidates.append(bbox)
    candidates.sort(key=lambda bbox: (bbox["y"], bbox["y"] + bbox["h"]))
    if len(candidates) < 2:
        return None
    covered_end = 0
    stacked_count = 0
    maximum_gap = max(4, int(height * 0.025))
    for bbox in candidates:
        if bbox["y"] > covered_end + maximum_gap:
            continue
        if bbox["y"] + bbox["h"] > covered_end:
            covered_end = bbox["y"] + bbox["h"]
            stacked_count += 1
    if stacked_count < 2 or covered_end > height * 0.35:
        return None
    cuts = [
        int(cut.get("point") or 0)
        for cut in image_horizontal_cuts
        if float(cut.get("support") or 0.0) >= 0.9
        and abs(int(cut.get("point") or 0) - covered_end) <= height * 0.1
    ]
    if not cuts:
        return None
    return min(cuts, key=lambda point: abs(point - covered_end))


def _color_block_boundary_cuts(
    image_path: str,
    *,
    width: int,
    height: int,
    axis: str,
) -> list[dict[str, Any]]:
    """检测跨越大部分界面的明显 RGB 色块边界。"""

    path = str(image_path or "").strip()
    if not path or width <= 0 or height <= 0 or axis not in {"x", "y"}:
        return []
    try:
        with Image.open(path) as image:
            rgb = np.asarray(image.convert("RGB"), dtype=np.int16)
    except (FileNotFoundError, OSError, ValueError):
        return []
    if rgb.shape[:2] != (height, width):
        return []

    # 只采样中心主体，避免窗口边框和角落装饰制造伪分区。
    if axis == "x":
        orthogonal_start = min(height - 1, max(0, int(height * 0.04)))
        orthogonal_end = min(height, max(orthogonal_start + 1, int(height * 0.96)))
        adjacent_delta = np.max(
            np.abs(
                rgb[orthogonal_start:orthogonal_end, 1:, :]
                - rgb[orthogonal_start:orthogonal_end, :-1, :]
            ),
            axis=2,
        )
        axis_length = width
    else:
        orthogonal_start = min(width - 1, max(0, int(width * 0.04)))
        orthogonal_end = min(width, max(orthogonal_start + 1, int(width * 0.96)))
        adjacent_delta = np.max(
            np.abs(
                rgb[1:, orthogonal_start:orthogonal_end, :]
                - rgb[:-1, orthogonal_start:orthogonal_end, :]
            ),
            axis=2,
        ).T
        axis_length = height

    support = (adjacent_delta >= 36).mean(axis=0)
    color_distance = adjacent_delta.mean(axis=0)
    candidate_points = np.flatnonzero((support >= 0.72) & (color_distance >= 40.0))
    minimum_point = max(1, int(axis_length * 0.03))
    maximum_point = min(axis_length - 2, int(axis_length * 0.97))
    candidates = [
        int(value)
        for value in candidate_points
        if minimum_point <= int(value) <= maximum_point
    ]
    if not candidates:
        return []

    maximum_gap = max(2, int(axis_length * 0.004))
    clusters: list[list[int]] = []
    for value in candidates:
        if not clusters or value - clusters[-1][-1] > maximum_gap:
            clusters.append([value])
        else:
            clusters[-1].append(value)

    cuts = []
    for cluster in clusters:
        strongest = max(
            cluster,
            key=lambda value: (float(support[value]), float(color_distance[value])),
        )
        point = strongest + 1
        cuts.append(
            {
                "axis": axis,
                "point": point,
                "gap_start": min(cluster) + 1,
                "gap_end": max(cluster) + 1,
                "gap_ratio": round((max(cluster) - min(cluster) + 1) / axis_length, 4),
                "support": round(float(support[strongest]), 4),
                "color_distance": round(float(color_distance[strongest]), 4),
                "remainder_supported": True,
                "score": round(min(1.0, float(support[strongest]) + 0.15), 4),
                "source": "image_color_block_boundary",
            }
        )
    return cuts


def _vertical_separator_cuts(
    image_path: str,
    *,
    width: int,
    height: int,
    maximum_x_ratio: float = 0.35,
) -> list[dict[str, Any]]:
    path = str(image_path or "").strip()
    if not path or width <= 0 or height <= 0:
        return []
    try:
        with Image.open(path) as image:
            grayscale = np.asarray(image.convert("L"), dtype=np.int16)
    except (FileNotFoundError, OSError, ValueError):
        return []
    if grayscale.shape != (height, width):
        return []

    start_y = min(height - 1, max(0, int(height * 0.14)))
    end_y = min(height, max(start_y + 1, int(height * 0.96)))
    gradient = np.abs(grayscale[start_y:end_y, 1:] - grayscale[start_y:end_y, :-1])
    strong_support = (gradient >= 24).mean(axis=0)
    low_contrast_support = (gradient >= 6).mean(axis=0)
    minimum_x = max(1, int(width * 0.03))
    maximum_x = min(width - 2, int(width * max(0.35, min(0.95, maximum_x_ratio))))
    candidate_x = np.flatnonzero((strong_support >= 0.6) | (low_contrast_support >= 0.9))
    candidate_x = [int(value) for value in candidate_x if minimum_x <= value <= maximum_x]
    if not candidate_x:
        return []

    maximum_gap = max(3, int(width * 0.008))
    clusters: list[list[int]] = []
    for value in candidate_x:
        if not clusters or value - clusters[-1][-1] > maximum_gap:
            clusters.append([value])
        else:
            clusters[-1].append(value)

    cuts = []
    for cluster in clusters:
        point = max(cluster) + 1
        strong_cluster_support = max(float(strong_support[value]) for value in cluster)
        low_cluster_support = max(float(low_contrast_support[value]) for value in cluster)
        cluster_support = max(strong_cluster_support, low_cluster_support)
        cuts.append(
            {
                "axis": "x",
                "point": point,
                "gap_start": min(cluster) + 1,
                "gap_end": point,
                "gap_ratio": round((point - min(cluster)) / width, 4),
                "support": round(cluster_support, 4),
                "strong_contrast_support": round(strong_cluster_support, 4),
                "low_contrast_full_height_support": round(low_cluster_support, 4),
                "remainder_supported": False,
                "score": round(min(1.0, cluster_support + 0.1), 4),
                "source": "image_long_vertical_separator",
            }
        )
    return cuts


def detect_vertical_separator_cuts(
    image_path: str,
    *,
    width: int,
    height: int,
    maximum_x_ratio: float = 0.35,
) -> list[dict[str, Any]]:
    return _vertical_separator_cuts(
        image_path,
        width=width,
        height=height,
        maximum_x_ratio=maximum_x_ratio,
    )


def _horizontal_separator_cuts(
    image_path: str,
    *,
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    path = str(image_path or "").strip()
    if not path or width <= 0 or height <= 0:
        return []
    try:
        with Image.open(path) as image:
            grayscale = np.asarray(image.convert("L"), dtype=np.int16)
    except (FileNotFoundError, OSError, ValueError):
        return []
    if grayscale.shape != (height, width):
        return []

    start_x = min(width - 1, max(0, int(width * 0.03)))
    end_x = min(width, max(start_x + 1, int(width * 0.97)))
    gradient = np.abs(grayscale[1:, start_x:end_x] - grayscale[:-1, start_x:end_x])
    support = (gradient >= 10).mean(axis=1)
    minimum_y = max(1, int(height * 0.02))
    maximum_y = min(height - 2, int(height * 0.98))
    candidate_y = np.flatnonzero(support >= 0.45)
    candidate_y = [int(value) for value in candidate_y if minimum_y <= value <= maximum_y]
    if not candidate_y:
        return []

    maximum_gap = max(3, int(height * 0.008))
    clusters: list[list[int]] = []
    for value in candidate_y:
        if not clusters or value - clusters[-1][-1] > maximum_gap:
            clusters.append([value])
        else:
            clusters[-1].append(value)

    cuts = []
    for cluster in clusters:
        point = max(cluster) + 1
        cluster_support = max(float(support[value]) for value in cluster)
        cuts.append(
            {
                "axis": "y",
                "point": point,
                "gap_start": min(cluster) + 1,
                "gap_end": point,
                "gap_ratio": round((point - min(cluster)) / height, 4),
                "support": round(cluster_support, 4),
                "remainder_supported": False,
                "score": round(min(1.0, cluster_support + 0.1), 4),
                "source": "image_long_horizontal_separator",
            }
        )
    return cuts


def detect_horizontal_separator_cuts(
    image_path: str,
    *,
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    return _horizontal_separator_cuts(
        image_path,
        width=width,
        height=height,
    )


def _calibrate_edge_bands(
    edge_bands: dict[str, int | None],
    *,
    image_horizontal_cuts: list[dict[str, Any]],
    height: int,
    require_bottom_image_evidence: bool,
) -> dict[str, int | None]:
    top_end = edge_bands.get("top_end")
    bottom_start = edge_bands.get("bottom_start")
    points = [int(cut.get("point") or 0) for cut in image_horizontal_cuts]
    repeated_grid_points = _repeated_separator_sequence_points(image_horizontal_cuts)

    if isinstance(top_end, int):
        top_candidates = [
            point
            for point in points
            if height * 0.02 <= point <= height * 0.35
            and abs(point - top_end) <= height * 0.15
        ]
        if top_candidates:
            top_end = min(top_candidates, key=lambda point: abs(point - top_end))

    if isinstance(bottom_start, int):
        bottom_candidates = [
            point
            for point in points
            if height * 0.65 <= point <= height * 0.985
            and height * 0.015 <= height - point <= height * 0.25
            and abs(point - bottom_start) <= height * 0.2
            and point not in repeated_grid_points
        ]
        if bottom_candidates:
            bottom_start = min(bottom_candidates, key=lambda point: abs(point - bottom_start))
        elif require_bottom_image_evidence:
            bottom_start = None

    return {"top_end": top_end, "bottom_start": bottom_start}


def _repeated_separator_sequence_points(cuts: list[dict[str, Any]]) -> set[int]:
    ordered = sorted(
        (
            cut
            for cut in cuts
            if int(cut.get("point") or 0) > 0
            and float(cut.get("support") or 0.0) >= 0.55
            and float(cut.get("gap_ratio") or 0.0) <= 0.01
        ),
        key=lambda cut: int(cut.get("point") or 0),
    )
    repeated: set[int] = set()
    for index in range(max(0, len(ordered) - 3)):
        points = [int(cut.get("point") or 0) for cut in ordered[index : index + 4]]
        intervals = [right - left for left, right in zip(points, points[1:])]
        if min(intervals) > 0 and max(intervals) / min(intervals) <= 1.15:
            repeated.update(points)
    return repeated


def validate_root_partition(
    root_regions: list[dict[str, Any]],
    image_size: dict[str, Any],
) -> dict[str, Any]:
    width = max(1, int(image_size.get("width") or 0))
    height = max(1, int(image_size.get("height") or 0))
    screen_area = width * height
    boxes = [_bbox(region.get("bbox")) for region in root_regions]
    boxes = [box for box in boxes if box is not None]
    out_of_bounds = [
        box
        for box in boxes
        if box["x"] < 0
        or box["y"] < 0
        or box["x"] + box["w"] > width
        or box["y"] + box["h"] > height
    ]
    sum_area = sum(box["w"] * box["h"] for box in boxes)
    covered_area = _union_area(boxes)
    overlap_area = max(0, sum_area - covered_area)
    coverage_ratio = round(min(1.0, covered_area / screen_area), 4)
    failures: list[dict[str, Any]] = []
    if not boxes:
        failures.append({"reason": "no_root_regions"})
    if out_of_bounds:
        failures.append({"reason": "root_region_out_of_bounds", "count": len(out_of_bounds)})
    if overlap_area:
        failures.append({"reason": "sibling_overlap", "area": overlap_area})
    if coverage_ratio < 0.9999:
        failures.append({"reason": "incomplete_root_coverage", "coverage_ratio": coverage_ratio})
    return {
        "contract_version": "deterministic_root_partition_validator_v1",
        "valid": not failures,
        "root_count": len(boxes),
        "coverage_ratio": coverage_ratio,
        "sibling_overlap_area": overlap_area,
        "out_of_bounds_count": len(out_of_bounds),
        "failures": failures,
    }


def adapt_root_partition_to_stage1_contract(
    partition: dict[str, Any],
    *,
    source: str = "deterministic_root_partition_v1",
) -> dict[str, Any]:
    validator = partition.get("validator") if isinstance(partition.get("validator"), dict) else {}
    if not validator.get("valid"):
        raise ValueError(f"invalid deterministic root partition: {validator.get('failures') or []}")
    image_size = partition.get("image_size") if isinstance(partition.get("image_size"), dict) else {}
    semantic_regions = _assign_stage1_semantics(
        partition.get("root_regions") or [],
        width=int(image_size.get("width") or 0),
        height=int(image_size.get("height") or 0),
    )
    structure_regions = []
    for index, region in enumerate(semantic_regions, start=1):
        bbox = _bbox(region.get("bbox"))
        if bbox is None:
            continue
        item_ids = [str(item_id) for item_id in region.get("item_ids") or []]
        structure_regions.append(
            {
                "contract_version": "learn_stage1_structure_region_v1",
                "region_no": index,
                "region_id": str(region.get("stage1_region_id") or f"structure_region_main_content_{index}"),
                "label": str(region.get("stage1_label") or "Main content"),
                "zone_id": str(region.get("stage1_zone_id") or "main_content"),
                "role": str(region.get("stage1_zone_id") or "main_content"),
                "bbox": bbox,
                "item_ids": item_ids,
                "item_count": len(item_ids),
                "stage": "stage1_page_structure",
                "source": source,
                "bbox_policy": "deterministic_root_partition_original_image",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    result = {
        "contract_version": "learn_stage1_structure_regions_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "region_count": len(structure_regions),
        "structure_regions": structure_regions,
        "source": source,
        "partition_contract": partition.get("contract_version"),
        "root_validator": validator,
        "diagnostics": dict(partition.get("diagnostics") or {}),
    }
    return result


def _assign_stage1_semantics(
    regions: list[dict[str, Any]],
    *,
    width: int,
    height: int,
) -> list[dict[str, Any]]:
    resolved = [dict(region) for region in regions if isinstance(region, dict) and _bbox(region.get("bbox"))]
    if not resolved:
        return []
    boxes = [_bbox(region.get("bbox")) for region in resolved]
    vertical_partition = width > 0 and all(box and box["h"] >= height * 0.95 for box in boxes)
    horizontal_partition = height > 0 and all(box and box["w"] >= width * 0.95 for box in boxes)
    assignments: list[str] = []
    if len(resolved) == 1:
        assignments = ["main_content"]
    elif _is_top_with_lower_edge_rail_and_bottom(boxes, width=width, height=height):
        assignments = ["top_bar", "left_nav", "main_content", "bottom_bar"]
    elif _is_top_with_lower_edge_rail(boxes, width=width, height=height):
        assignments = ["top_bar", "left_nav", "main_content"]
    elif _is_left_with_right_top(boxes, width=width, height=height):
        assignments = ["left_nav", "top_bar", "main_content"]
    elif vertical_partition:
        for index, box in enumerate(boxes):
            if index == 0 and box and box["x"] <= width * 0.02 and box["w"] <= width * 0.35:
                assignments.append("left_nav")
            elif index == len(boxes) - 1:
                assignments.append("main_content")
            else:
                assignments.append("primary_area")
    elif horizontal_partition:
        for index, box in enumerate(boxes):
            if index == 0 and box and box["y"] <= height * 0.02 and box["h"] <= height * 0.35:
                assignments.append("top_bar")
            elif index == len(boxes) - 1 and len(boxes) >= 3 and box and box["h"] <= height * 0.25:
                assignments.append("bottom_bar")
            else:
                assignments.append("main_content")
    else:
        assignments = ["main_content" for _ in resolved]

    labels = {
        "top_bar": "Top bar",
        "bottom_bar": "Bottom bar",
        "left_nav": "Left navigation",
        "primary_area": "Primary area",
        "main_content": "Main content",
    }
    counts: dict[str, int] = {}
    for region, zone_id in zip(resolved, assignments):
        counts[zone_id] = counts.get(zone_id, 0) + 1
        suffix = f"_{counts[zone_id]}" if counts[zone_id] > 1 else ""
        region["stage1_zone_id"] = zone_id
        region["stage1_region_id"] = f"structure_region_{zone_id}{suffix}"
        region["stage1_label"] = labels[zone_id]
    return resolved


def _is_left_with_right_top(
    boxes: list[dict[str, int] | None],
    *,
    width: int,
    height: int,
) -> bool:
    if len(boxes) != 3 or any(box is None for box in boxes):
        return False
    left, top, main = boxes
    if left is None or top is None or main is None:
        return False
    split_x = left["x"] + left["w"]
    top_end = top["y"] + top["h"]
    return (
        left["x"] == 0
        and left["y"] == 0
        and left["h"] == height
        and left["w"] <= width * 0.35
        and top["x"] == split_x
        and top["y"] == 0
        and top["w"] == width - split_x
        and top["h"] <= height * 0.35
        and main["x"] == split_x
        and main["y"] == top_end
        and main["w"] == width - split_x
        and main["y"] + main["h"] == height
    )


def _is_top_with_lower_edge_rail(
    boxes: list[dict[str, int] | None],
    *,
    width: int,
    height: int,
) -> bool:
    if len(boxes) != 3 or any(box is None for box in boxes):
        return False
    top, left, main = boxes
    assert top is not None and left is not None and main is not None
    top_bottom = top["y"] + top["h"]
    return (
        top["x"] == 0
        and top["y"] == 0
        and top["w"] == width
        and top["h"] <= height * 0.35
        and left["x"] == 0
        and left["y"] == top_bottom
        and main["y"] == top_bottom
        and left["h"] == main["h"] == height - top_bottom
        and left["x"] + left["w"] == main["x"]
        and main["x"] + main["w"] == width
        and left["w"] <= width * 0.35
    )


def _is_top_with_lower_edge_rail_and_bottom(
    boxes: list[dict[str, int] | None],
    *,
    width: int,
    height: int,
) -> bool:
    if len(boxes) != 4 or any(box is None for box in boxes):
        return False
    top, left, main, bottom = boxes
    assert top is not None and left is not None and main is not None and bottom is not None
    top_bottom = top["y"] + top["h"]
    content_bottom = bottom["y"]
    return (
        top["x"] == 0
        and top["y"] == 0
        and top["w"] == width
        and top["h"] <= height * 0.35
        and left["x"] == 0
        and left["y"] == top_bottom
        and main["y"] == top_bottom
        and left["h"] == main["h"] == content_bottom - top_bottom
        and left["x"] + left["w"] == main["x"]
        and main["x"] + main["w"] == width
        and left["w"] <= width * 0.35
        and bottom["x"] == 0
        and bottom["w"] == width
        and bottom["y"] + bottom["h"] == height
        and bottom["h"] <= height * 0.25
    )


def _contained_item_ids(items: list[dict[str, Any]], container: dict[str, int]) -> list[str]:
    result: list[str] = []
    for index, item in enumerate(items, start=1):
        bbox = _bbox(item.get("bbox")) if isinstance(item, dict) else None
        if bbox is None:
            continue
        center_x = bbox["x"] + bbox["w"] / 2
        center_y = bbox["y"] + bbox["h"] / 2
        if (
            container["x"] <= center_x < container["x"] + container["w"]
            and container["y"] <= center_y < container["y"] + container["h"]
        ):
            result.append(str(item.get("item_id") or item.get("candidate_id") or f"E{index}"))
    return result


def _has_band_semantics(
    items: list[dict[str, Any]],
    *,
    start: int,
    end: int,
    tokens: tuple[str, ...],
) -> bool:
    for item in items:
        if not isinstance(item, dict):
            continue
        bbox = _bbox(item.get("bbox"))
        if bbox is None:
            continue
        center_y = bbox["y"] + bbox["h"] / 2
        if not start <= center_y <= end:
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        source_evidence = {
            str(value or "").strip().casefold()
            for value in item.get("source_evidence") or []
            if str(value or "").strip()
        }
        metadata_source = str(metadata.get("source") or "").strip().casefold()
        # 模型生成的 section 只是结构解释，不能单独证明真实栏存在。
        if source_evidence and source_evidence <= {"screen_map_section"}:
            continue
        if not source_evidence and metadata_source == "screen_map.sections":
            continue
        semantic_text = " ".join(
            str(value or "")
            for value in (
                item.get("item_id"),
                item.get("label"),
                item.get("text"),
                item.get("name"),
                item.get("role"),
                item.get("item_type"),
                metadata.get("surface_zone"),
                metadata.get("layout_zone"),
            )
        ).casefold()
        normalized_semantic_text = semantic_text.replace("-", "_").replace(" ", "_")
        if any(token in semantic_text or token in normalized_semantic_text for token in tokens):
            return True
    return False


def _has_vertical_band_semantics(
    items: list[dict[str, Any]],
    *,
    start: int,
    end: int,
    content_start: int,
    tokens: tuple[str, ...],
) -> bool:
    for item in items:
        if not isinstance(item, dict):
            continue
        bbox = _bbox(item.get("bbox"))
        if bbox is None:
            continue
        center_x = bbox["x"] + bbox["w"] / 2
        center_y = bbox["y"] + bbox["h"] / 2
        if not start <= center_x <= end or center_y < content_start:
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        semantic_text = " ".join(
            str(value or "")
            for value in (
                item.get("item_id"),
                item.get("label"),
                item.get("text"),
                item.get("name"),
                item.get("role"),
                item.get("item_type"),
                metadata.get("surface_zone"),
                metadata.get("layout_zone"),
            )
        ).casefold()
        normalized_semantic_text = semantic_text.replace("-", "_").replace(" ", "_")
        if any(token in semantic_text or token in normalized_semantic_text for token in tokens):
            return True
    return False


def _bbox(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        x = int(round(float(value.get("x") or 0)))
        y = int(round(float(value.get("y") or 0)))
        w = int(round(float(value.get("w") or value.get("width") or 0)))
        h = int(round(float(value.get("h") or value.get("height") or 0)))
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return {"x": x, "y": y, "w": w, "h": h}


def _intersection_area(left: dict[str, int], right: dict[str, int]) -> int:
    x1 = max(left["x"], right["x"])
    y1 = max(left["y"], right["y"])
    x2 = min(left["x"] + left["w"], right["x"] + right["w"])
    y2 = min(left["y"] + left["h"], right["y"] + right["h"])
    return max(0, x2 - x1) * max(0, y2 - y1)


def _union_area(boxes: list[dict[str, int]]) -> int:
    x_points = sorted({point for box in boxes for point in (box["x"], box["x"] + box["w"])})
    area = 0
    for left, right in zip(x_points, x_points[1:]):
        if right <= left:
            continue
        intervals = [
            (box["y"], box["y"] + box["h"])
            for box in boxes
            if box["x"] < right and box["x"] + box["w"] > left
        ]
        if not intervals:
            continue
        intervals.sort()
        covered_y = 0
        start, end = intervals[0]
        for next_start, next_end in intervals[1:]:
            if next_start > end:
                covered_y += end - start
                start, end = next_start, next_end
            else:
                end = max(end, next_end)
        covered_y += end - start
        area += (right - left) * covered_y
    return area
