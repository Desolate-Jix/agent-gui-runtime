from __future__ import annotations

from copy import deepcopy
from typing import Any


def audit_stage1_region_selection(
    *,
    localized_regions: list[dict[str, Any]],
    screen_size: dict[str, int],
    overlay_path: str = "",
) -> dict[str, Any]:
    width = _int(screen_size.get("width"))
    height = _int(screen_size.get("height"))
    case_results = []
    for region in localized_regions:
        if not isinstance(region, dict):
            continue
        case_results.append(_audit_region(region, width=width, height=height))
    structure_family_coverage = _structure_family_coverage(case_results)
    if case_results and structure_family_coverage["recognized_region_count"] == 0:
        for item in case_results:
            _mark_failed(item, "unknown_only_structure")
    _audit_single_region_structure(case_results, width=width, height=height)
    _audit_region_overlap(case_results)
    _audit_horizontal_bar_lane(case_results, width=width)
    _audit_stage1_partition_adjacency(case_results, width=width, height=height)
    failed = [item for item in case_results if item["status"] != "passed"]
    return {
        "contract_version": "learn_stage1_region_selection_audit_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "scope": "stage1_region_selection_only",
        "screen_size": {"width": width, "height": height},
        "overlay_path": overlay_path,
        "passed": len(failed) == 0,
        "status": "passed" if not failed else "needs_region_strategy_review",
        "region_count": len(case_results),
        "failed_region_count": len(failed),
        "failure_categories": sorted({failure for item in failed for failure in item["failure_categories"]}),
        "structure_family_coverage": structure_family_coverage,
        "regions": case_results,
        "interpretation": (
            "This audit checks generic structure-region completeness. It is not a model accuracy score, "
            "not item recognition, and not Execute authorization."
        ),
    }


def _structure_family_coverage(case_results: list[dict[str, Any]]) -> dict[str, Any]:
    recognized = [
        item
        for item in case_results
        if item.get("region_type") in {"top_bar", "bottom_bar", "left_sidebar", "right_sidebar", "main_content"}
    ]
    families = sorted({str(item.get("region_type") or "") for item in recognized})
    return {
        "contract_version": "learn_stage1_structure_family_coverage_v1",
        "status": "covered" if recognized else "not_covered",
        "recognized_region_count": len(recognized),
        "recognized_families": families,
        "unknown_region_count": sum(1 for item in case_results if item.get("region_type") == "other"),
    }


def _audit_region(region: dict[str, Any], *, width: int, height: int) -> dict[str, Any]:
    bbox = _bbox(region.get("bbox"))
    region_id = str(region.get("region_id") or "")
    region_type = _region_type(region)
    failures: list[str] = []
    notes: list[str] = []
    if not bbox:
        failures.append("region_bbox_missing")
    elif width > 0 and height > 0:
        if region_type == "top_bar":
            _audit_horizontal_bar(bbox, width=width, height=height, failures=failures, prefix="topbar")
        elif region_type == "bottom_bar":
            _audit_horizontal_bar(bbox, width=width, height=height, failures=failures, prefix="bottombar")
        elif region_type == "left_sidebar":
            _audit_vertical_bar(bbox, width=width, height=height, failures=failures, prefix="sidebar")
            if bbox["x"] > max(12, int(width * 0.02)):
                failures.append("sidebar_not_left_aligned")
        elif region_type == "right_sidebar":
            _audit_vertical_bar(bbox, width=width, height=height, failures=failures, prefix="right_sidebar")
            if bbox["x"] + bbox["w"] < width - max(12, int(width * 0.02)):
                failures.append("right_sidebar_not_right_aligned")
        elif region_type == "main_content":
            main_bbox_too_small = bbox["w"] < int(width * 0.35) or bbox["h"] < int(height * 0.35)
            if main_bbox_too_small:
                failures.append("main_region_too_small")
            rough_bbox = _bbox(region.get("rough_bbox"))
            if rough_bbox and (
                rough_bbox["w"] < int(width * 0.35)
                or rough_bbox["h"] < int(height * 0.35)
            ):
                if _main_bbox_covers_stage_lane(bbox, width=width, height=height) or bool(
                    region.get("recovered_from_unknown_only")
                ):
                    notes.append("main_content_has_centered_rough_content_column")
                elif not main_bbox_too_small:
                    failures.append("main_region_too_small")
        if bbox["x"] < 0 or bbox["y"] < 0 or bbox["x"] + bbox["w"] > width or bbox["y"] + bbox["h"] > height:
            failures.append("region_bbox_outside_screen")
    if region_type in {"top_bar", "left_sidebar", "right_sidebar", "bottom_bar"}:
        notes.append("bar_spacing_must_not_shrink_region_bbox")
        notes.append("region_may_touch_neighboring_regions")
    return {
        "region_id": region_id,
        "label": str(region.get("label") or ""),
        "region_type": region_type,
        "bbox": deepcopy(bbox or {}),
        "rough_bbox": deepcopy(_bbox(region.get("rough_bbox")) or {}),
        "status": "passed" if not failures else "failed",
        "failure_categories": failures,
        "notes": notes,
    }


def _audit_single_region_structure(case_results: list[dict[str, Any]], *, width: int, height: int) -> None:
    if len(case_results) != 1 or width <= 0 or height <= 0:
        return
    item = case_results[0]
    if item.get("region_type") != "main_content":
        return
    bbox = _bbox(item.get("bbox"))
    rough_bbox = _bbox(item.get("rough_bbox"))
    if not bbox or not rough_bbox or not _main_bbox_covers_stage_lane(bbox, width=width, height=height):
        return
    if rough_bbox["h"] < int(height * 0.35):
        _mark_failed(item, "single_region_undersegmented")
        item["notes"].append("full_screen_main_was_backfilled_from_shallow_observed_content")


def _main_bbox_covers_stage_lane(bbox: dict[str, int], *, width: int, height: int) -> bool:
    tolerance_x = max(12, int(width * 0.02))
    tolerance_y = max(12, int(height * 0.02))
    return (
        bbox["x"] <= tolerance_x
        and bbox["y"] <= tolerance_y
        and bbox["x"] + bbox["w"] >= width - tolerance_x
        and bbox["y"] + bbox["h"] >= height - tolerance_y
    )


def _audit_region_overlap(case_results: list[dict[str, Any]]) -> None:
    for index, first in enumerate(case_results):
        first_bbox = _bbox(first.get("bbox"))
        if not first_bbox:
            continue
        for second in case_results[index + 1 :]:
            second_bbox = _bbox(second.get("bbox"))
            if not second_bbox:
                continue
            if _regions_may_overlap(first["region_type"], second["region_type"]):
                continue
            overlap_ratio = max(_bbox_overlap_ratio(first_bbox, second_bbox), _bbox_overlap_ratio(second_bbox, first_bbox))
            if overlap_ratio < 0.03:
                continue
            for item, other in ((first, second), (second, first)):
                item["status"] = "failed"
                item["failure_categories"].append("structure_region_overlap")
                item["notes"].append(f"overlaps_neighbor:{other['region_id']}")


def _regions_may_overlap(first_type: str, second_type: str) -> bool:
    pair = {first_type, second_type}
    if "other" in pair:
        return True
    return False


def _audit_horizontal_bar_lane(case_results: list[dict[str, Any]], *, width: int) -> None:
    if width <= 0:
        return
    tolerance = max(12, int(width * 0.02))
    for item in case_results:
        if item.get("region_type") not in {"top_bar", "bottom_bar"}:
            continue
        region_id = str(item.get("region_id") or "").casefold()
        if "browser_chrome" in region_id:
            continue
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            continue
        left_boundary = max(
            (
                side_bbox["x"] + side_bbox["w"]
                for side in case_results
                if side.get("region_type") == "left_sidebar"
                for side_bbox in [_bbox(side.get("bbox"))]
                if side_bbox and _vertical_overlap_px(bbox, side_bbox) > tolerance
            ),
            default=0,
        )
        right_boundary = min(
            (
                side_bbox["x"]
                for side in case_results
                if side.get("region_type") == "right_sidebar"
                for side_bbox in [_bbox(side.get("bbox"))]
                if side_bbox and _vertical_overlap_px(bbox, side_bbox) > tolerance
            ),
            default=width,
        )
        if right_boundary <= left_boundary:
            continue
        expected_width = max(1, right_boundary - left_boundary)
        if bbox["x"] < left_boundary - tolerance:
            _mark_failed(item, "horizontal_bar_overlaps_left_sidebar")
        if bbox["x"] + bbox["w"] > right_boundary + tolerance:
            _mark_failed(item, "horizontal_bar_overlaps_right_sidebar")
        if bbox["w"] < int(expected_width * 0.65):
            _mark_failed(item, "horizontal_bar_lane_too_narrow")


def _audit_stage1_partition_adjacency(case_results: list[dict[str, Any]], *, width: int, height: int) -> None:
    if width <= 0 or height <= 0:
        return
    tolerance_x = max(12, int(width * 0.025))
    tolerance_y = max(12, int(height * 0.025))
    lower_edge_tolerance_y = max(tolerance_y, 32, int(height * 0.035))
    left_boundary = max(
        (
            bbox["x"] + bbox["w"]
            for item in case_results
            if item.get("region_type") == "left_sidebar"
            for bbox in [_bbox(item.get("bbox"))]
            if bbox
        ),
        default=0,
    )
    right_boundary = min(
        (
            bbox["x"]
            for item in case_results
            if item.get("region_type") == "right_sidebar"
            for bbox in [_bbox(item.get("bbox"))]
            if bbox
        ),
        default=width,
    )
    top_boundary = max(
        (
            bbox["y"] + bbox["h"]
            for item in case_results
            if item.get("region_type") == "top_bar"
            for bbox in [_bbox(item.get("bbox"))]
            if bbox
        ),
        default=0,
    )
    bottom_boundary = min(
        (
            bbox["y"]
            for item in case_results
            if item.get("region_type") == "bottom_bar"
            for bbox in [_bbox(item.get("bbox"))]
            if bbox
        ),
        default=height,
    )
    if right_boundary <= left_boundary or bottom_boundary <= top_boundary:
        return
    for item in case_results:
        if item.get("region_type") != "main_content":
            continue
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            continue
        if bbox["x"] > left_boundary + tolerance_x:
            _mark_failed(item, "main_content_not_adjacent_to_left_boundary")
            item["notes"].append("main_content_must_include_empty_gap_after_left_bar")
        if bbox["x"] + bbox["w"] < right_boundary - tolerance_x:
            _mark_failed(item, "main_content_does_not_cover_right_empty_area")
            item["notes"].append("main_content_must_cover_empty_space_until_right_boundary")
        if bbox["y"] > top_boundary + tolerance_y:
            _mark_failed(item, "main_content_not_adjacent_to_top_boundary")
            item["notes"].append("main_content_must_start_at_topbar_bottom_even_when_empty")
        if bbox["y"] + bbox["h"] < bottom_boundary - lower_edge_tolerance_y:
            _mark_failed(item, "main_content_does_not_cover_lower_empty_area")
            item["notes"].append("main_content_must_cover_empty_visible_lower_area")
        elif bbox["y"] + bbox["h"] < bottom_boundary:
            item["notes"].append("main_content_lower_edge_within_system_border_tolerance")


def _mark_failed(item: dict[str, Any], category: str) -> None:
    item["status"] = "failed"
    failures = item.get("failure_categories")
    if not isinstance(failures, list):
        failures = []
        item["failure_categories"] = failures
    if category not in failures:
        failures.append(category)


def _bbox_overlap_ratio(bbox: dict[str, int], other: dict[str, int]) -> float:
    x1 = max(bbox["x"], other["x"])
    y1 = max(bbox["y"], other["y"])
    x2 = min(bbox["x"] + bbox["w"], other["x"] + other["w"])
    y2 = min(bbox["y"] + bbox["h"], other["y"] + other["h"])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    return intersection / max(1, bbox["w"] * bbox["h"])


def _vertical_overlap_px(bbox: dict[str, int], other: dict[str, int]) -> int:
    return max(0, min(bbox["y"] + bbox["h"], other["y"] + other["h"]) - max(bbox["y"], other["y"]))


def _audit_horizontal_bar(
    bbox: dict[str, int],
    *,
    width: int,
    height: int,
    failures: list[str],
    prefix: str,
) -> None:
    if bbox["h"] < 24:
        failures.append(f"{prefix}_bbox_too_short")
    if bbox["h"] > int(height * 0.35):
        failures.append(f"{prefix}_bbox_too_tall")


def _audit_vertical_bar(
    bbox: dict[str, int],
    *,
    width: int,
    height: int,
    failures: list[str],
    prefix: str,
) -> None:
    if bbox["h"] < int(height * 0.75):
        failures.append(f"{prefix}_bbox_too_short")
    if bbox["w"] < max(48, int(width * 0.045)):
        failures.append(f"{prefix}_bbox_too_narrow")
    if bbox["w"] > int(width * 0.35):
        failures.append(f"{prefix}_bbox_too_wide")


def _region_type(region: dict[str, Any]) -> str:
    value = " ".join(
        [
            str(region.get("region_id") or ""),
            str(region.get("zone_id") or ""),
            str(region.get("label") or ""),
        ]
    ).casefold()
    if "left" in value:
        return "left_sidebar"
    if "right" in value:
        return "right_sidebar"
    if "bottom" in value:
        return "bottom_bar"
    if "top" in value or "header" in value or "browser_chrome" in value:
        return "top_bar"
    if "main" in value or "primary" in value or "content" in value:
        return "main_content"
    return "other"


def _bbox(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    bbox = {
        "x": _int(value.get("x")),
        "y": _int(value.get("y")),
        "w": _int(value.get("w", value.get("width"))),
        "h": _int(value.get("h", value.get("height"))),
    }
    if bbox["w"] <= 0 or bbox["h"] <= 0:
        return {}
    return bbox


def _int(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0
