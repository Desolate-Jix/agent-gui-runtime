from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.learn.draft_review import load_learning_draft_review
from scripts.build_learn_precise_understanding_candidate import build_learn_precise_understanding_candidate


REPORT_NAME = "learn_page_detail_candidate.json"


def build_learn_page_detail_candidate(
    *,
    source_path: str | Path,
    out_dir: str | Path,
    project_root: str | Path | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    source_file = _resolve_path(source_path, root)
    out = _resolve_path(out_dir, root)
    out.mkdir(parents=True, exist_ok=True)
    source_payload = _read_json(source_file)
    page_details = _learning_draft_page_details(source_payload)
    two_stage_source = _two_stage_source(source_payload)
    precise: dict[str, Any] = {}
    if two_stage_source:
        regions = _regions_from_fused_review_boxes(two_stage_source)
        if not regions:
            regions = _regions_from_two_stage(two_stage_source)
        regions = _overlay_precise_locator_regions(regions, source_payload)
        regions = _resolve_page_detail_sibling_panel_overlaps(regions)
        regions = _resolve_page_detail_overlapping_row_shells(regions)
        sections = _layout_sections_from_two_stage(two_stage_source, regions)
        source_detail_shape = str(two_stage_source.get("contract_version") or "learn_two_stage_screen_understanding_v1")
    else:
        regions = _regions_from_learning_draft(source_payload)
        sections = []
        if regions:
            source_detail_shape = str(_dict(source_payload.get("learning_draft")).get("contract_version") or "learning_template_draft_v1")
        else:
            precise = _load_or_build_precise_candidate(source_file=source_file, out_dir=out, root=root)
            items = _list_of_dicts(precise.get("items"))
            regions = [_region_from_precise_item(item) for item in items]
            regions = [item for item in regions if item]
            source_detail_shape = "learn_precise_understanding_candidate_v1"
    if not regions and page_details:
        regions = _regions_from_page_details(page_details)
        sections = []
        source_detail_shape = str(page_details.get("contract_version") or "learning_draft_page_details_v1")
    bounds = _layout_bounds(regions)
    if not sections:
        sections = _layout_sections(regions, bounds=bounds)
    display_groups = _page_detail_display_groups(regions)
    inventory_summary = _dict(page_details.get("inventory_summary")) if source_detail_shape != "learn_precise_understanding_candidate_v1" else {}
    screen = _dict(page_details.get("screen")) if source_detail_shape != "learn_precise_understanding_candidate_v1" else {}
    readiness_status = (
        precise.get("readiness_status")
        if source_detail_shape == "learn_precise_understanding_candidate_v1"
        else "needs_page_detail_review"
    ) or ("needs_page_detail_review" if regions else "unknown")
    output_path = out / REPORT_NAME
    source_visuals = _source_visual_paths(source_payload, root)
    calibration_overlay_path = _source_calibration_overlay_path(source_payload)
    if two_stage_source and not _source_has_precise_locator_targets(source_payload):
        calibration_overlay_path = ""
    two_stage_fusion = _dict(two_stage_source.get("fusion"))
    verified_final_fusion = _verified_final_fusion_status(source_payload)
    if verified_final_fusion:
        calibration_overlay_path = str(
            verified_final_fusion.get("calibration_overlay_path")
            or verified_final_fusion.get("compiled_overlay_path")
            or calibration_overlay_path
            or ""
        ).strip()
    fused_compiled_overlay_path = str(
        verified_final_fusion.get("compiled_overlay_path")
        or two_stage_fusion.get("compiled_overlay_path")
        or two_stage_fusion.get("full_screen_understanding_overlay_path")
        or page_details.get("compiled_overlay_path")
        or page_details.get("full_screen_understanding_overlay_path")
        or ""
    ).strip()
    fused_full_overlay_path = str(
        verified_final_fusion.get("full_screen_understanding_overlay_path")
        or verified_final_fusion.get("compiled_overlay_path")
        or two_stage_fusion.get("full_screen_understanding_overlay_path")
        or two_stage_fusion.get("compiled_overlay_path")
        or page_details.get("full_screen_understanding_overlay_path")
        or page_details.get("compiled_overlay_path")
        or ""
    ).strip()
    screenshot_path = (
        precise.get("screenshot_path")
        or screen.get("image_path")
        or source_payload.get("screenshot_path")
        or source_visuals.get("screenshot_path")
    )
    compiled_overlay_path = (
        fused_compiled_overlay_path
        or calibration_overlay_path
        or precise.get("compiled_overlay_path")
        or source_visuals.get("compiled_overlay_path")
    )
    source_identity = _learning_repaired_source_identity(
        source=two_stage_source or source_payload,
        source_file=source_file,
        root=root,
        screenshot_path=screenshot_path,
        compiled_overlay_path=compiled_overlay_path,
    )
    payload = {
        "contract_version": "learn_page_detail_candidate_v1",
        "source_path": _relative_path(source_file, root),
        "source_identity": source_identity,
        "source_detail_shape": source_detail_shape,
        "precise_understanding_candidate_path": _display_path(precise.get("report_path"), root=root),
        "screen_summary": "Auto-generated page detail candidate from Learn Mode full-screen understanding and calibration evidence.",
        "layout_mode": "stage_parent_sections_spatial_bbox_order"
        if source_detail_shape == "learn_two_stage_screen_understanding_v1"
        else "spatial_bbox_order",
        "readiness_status": readiness_status,
        "screenshot_path": screenshot_path,
        "full_screen_understanding_overlay_path": fused_full_overlay_path
        or calibration_overlay_path
        or precise.get("full_screen_understanding_overlay_path")
        or source_visuals.get("full_screen_understanding_overlay_path"),
        "compiled_overlay_path": compiled_overlay_path,
        "calibration_overlay_path": calibration_overlay_path,
        "final_fusion_overlay": bool(verified_final_fusion),
        "display_overlay_source": str(verified_final_fusion.get("display_overlay_source") or ""),
        "stage2_compiled_overlay_path": str(
            verified_final_fusion.get("stage2_compiled_overlay_path")
            or two_stage_fusion.get("compiled_overlay_path")
            or ""
        ),
        "ui_hierarchy": _source_ui_hierarchy(two_stage_source or source_payload),
        "summary": {
            "region_count": len(regions),
            "section_count": len(sections),
            "display_group_count": len(display_groups),
            "list_group_count": sum(1 for item in display_groups if item.get("role") == "list_group"),
            "container_group_count": sum(
                1 for item in display_groups if item.get("role") in _PAGE_DETAIL_CONTAINER_DISPLAY_GROUP_ROLES
            ),
            "spatial_preview_suppressed_region_count": sum(
                1 for item in regions if item.get("render_in_spatial_preview") is False
            ),
            "possible_operation_count": sum(1 for item in regions if isinstance(item.get("possible_operation"), dict)),
            "pending_calibration_count": _dict(precise.get("summary")).get("pending_calibration_count")
            if source_detail_shape == "learn_precise_understanding_candidate_v1"
            else inventory_summary.get("pending_calibration_count"),
            "review_blocked_count": _dict(precise.get("summary")).get("review_blocked_count")
            if source_detail_shape == "learn_precise_understanding_candidate_v1"
            else inventory_summary.get("review_blocked_count"),
            "pathgraph_candidate_review_ready_count": _dict(precise.get("summary")).get(
                "pathgraph_candidate_review_ready_count"
            ),
            "runtime_pathgraph_promotion": False,
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
        "layout": {
            "bounds": bounds,
            "sections": sections,
            "display_groups": display_groups,
            "regions": regions,
        },
        "safety": {
            "display_only": True,
            "model_started": False,
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "runtime_pathgraph_promotion": False,
        },
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "not_accuracy": True,
        "not_e2e_success": True,
        "interpretation": (
            "Template-like page detail candidate generated from model-produced learning artifacts and existing "
            "calibration evidence. It is arranged by source bbox layout for demo/review only; it does not start models, "
            "click, fill, submit, authorize Execute, or promote Runtime PathGraph."
        ),
    }
    payload["report_path"] = str(output_path.resolve())
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if json_stdout:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return payload


def _learning_repaired_source_identity(
    *,
    source: dict[str, Any],
    source_file: Path,
    root: Path,
    screenshot_path: Any,
    compiled_overlay_path: Any,
) -> dict[str, Any]:
    review_repair = _dict(source.get("model_review_repair"))
    stage2 = _dict(source.get("stage2_numbering"))
    final_numbering = _dict(stage2.get("final_numbering"))
    integrity = _dict(review_repair.get("integrity_gate"))
    final_revision = str(
        review_repair.get("final_numbering_revision")
        or final_numbering.get("revision")
        or stage2.get("graph_revision")
        or ""
    ).strip()
    if not final_revision:
        return {}

    dual_stream_regions = []
    visual_object_count = 0
    semantic_group_count = 0
    association_count = 0
    for region in _list_of_dicts(stage2.get("regions")):
        streams = _dict(region.get("stage2_streams"))
        if streams.get("contract_version") != "learn_stage2_dual_streams_v1":
            continue
        dual_stream_regions.append(region)
        visual_object_count += len(_list_of_dicts(streams.get("visual_objects")))
        semantic_group_count += len(_list_of_dicts(streams.get("semantic_groups")))
        association_count += len(_list_of_dicts(streams.get("associations")))

    return {
        "contract_version": "learning_repaired_source_identity_v1",
        "source_path": _relative_path(source_file, root),
        "source_contract_version": str(source.get("contract_version") or ""),
        "source_artifact_type": str(source.get("artifact_type") or ""),
        "source_graph_revision": str(review_repair.get("source_graph_revision") or ""),
        "reviewed_graph_revision": str(review_repair.get("reviewed_graph_revision") or ""),
        "final_numbering_revision": final_revision,
        "capture_sha256": str(
            integrity.get("actual_capture_sha256")
            or integrity.get("expected_capture_sha256")
            or final_numbering.get("capture_sha256")
            or ""
        ),
        "screenshot_path": str(screenshot_path or source.get("source_image_path") or ""),
        "compiled_overlay_path": str(compiled_overlay_path or ""),
        "dual_stream_contract": "learn_stage2_dual_streams_v1" if dual_stream_regions else "",
        "dual_stream_region_count": len(dual_stream_regions),
        "visual_object_count": visual_object_count,
        "semantic_group_count": semantic_group_count,
        "association_count": association_count,
    }


def _learning_draft_page_details(source: dict[str, Any]) -> dict[str, Any]:
    draft = _dict(source.get("learning_draft"))
    page_details = _dict(draft.get("page_details"))
    if page_details.get("contract_version") == "learning_draft_page_details_v1":
        return page_details
    direct = _dict(source.get("page_details"))
    if direct.get("contract_version") == "learning_draft_page_details_v1":
        return direct
    return {}


def _verified_final_fusion_status(source: dict[str, Any]) -> dict[str, Any]:
    draft = _dict(source.get("learning_draft"))
    page_details = _dict(draft.get("page_details"))
    pipeline_audit = _dict(page_details.get("pipeline_audit"))
    candidates = [
        _dict(page_details.get("precise_understanding_fusion_status")),
        _dict(pipeline_audit.get("precise_understanding_fusion_status")),
    ]
    for status in candidates:
        if (
            status.get("final_fusion_overlay") is True
            and status.get("display_overlay_source") == "two_stage_plus_precise_calibration"
            and str(status.get("compiled_overlay_path") or "").strip()
        ):
            return status
    return {}


def _source_visual_paths(source: dict[str, Any], root: Path) -> dict[str, str]:
    visuals: dict[str, str] = {}
    fusion = _dict(source.get("fusion"))
    fusion_status = _dict(source.get("fusion_status"))
    for key in ("full_screen_understanding_overlay_path", "compiled_overlay_path"):
        value = fusion.get(key) or fusion_status.get(key)
        if value:
            visuals[key] = str(value)
    observe_bundle = _dict(source.get("observe_bundle"))
    observation_evidence = _dict(observe_bundle.get("panel_observation_evidence"))
    calibrated_source = _dict(_dict(observe_bundle.get("sources")).get("calibrated_targets"))
    overlay_value = (
        observation_evidence.get("coordinate_overlay_path")
        or calibrated_source.get("source_overlay_path")
        or source.get("coordinate_overlay_path")
    )
    if overlay_value:
        visuals.setdefault("compiled_overlay_path", str(overlay_value))
        visuals.setdefault("full_screen_understanding_overlay_path", str(overlay_value))
    for key in ("screenshot_path", "image_path", "source_image_path"):
        value = source.get(key)
        if value:
            visuals["screenshot_path"] = str(value)
            break
    if not visuals.get("screenshot_path"):
        for key in ("source_image_path", "image_path"):
            value = observe_bundle.get(key)
            if value:
                visuals["screenshot_path"] = str(value)
                break
    if not visuals.get("screenshot_path"):
        trace_path = str(source.get("source_trace_path") or "").strip()
        if trace_path:
            trace_payload = _load_json_if_exists(trace_path, root)
            trace_screenshot = _trace_screenshot_path(trace_payload)
            if trace_screenshot:
                visuals["screenshot_path"] = trace_screenshot
    return visuals


def _source_calibration_overlay_path(source: dict[str, Any]) -> str:
    observe_bundle = _dict(source.get("observe_bundle"))
    observation_evidence = _dict(observe_bundle.get("panel_observation_evidence"))
    calibrated_source = _dict(_dict(observe_bundle.get("sources")).get("calibrated_targets"))
    return str(
        observation_evidence.get("coordinate_overlay_path")
        or calibrated_source.get("source_overlay_path")
        or source.get("coordinate_overlay_path")
        or ""
    ).strip()


def _source_has_precise_locator_targets(source: dict[str, Any]) -> bool:
    calibrated_source = _dict(_dict(_dict(source.get("observe_bundle")).get("sources")).get("calibrated_targets"))
    return any(
        str(item.get("coordinate_source") or "") == "precise_locator_v1" and bool(_dict(item.get("bbox")))
        for item in _list_of_dicts(calibrated_source.get("targets"))
    )


def _load_json_if_exists(path: str, root: Path) -> dict[str, Any]:
    try:
        resolved = _resolve_path(path, root)
        if not resolved.exists():
            return {}
        return _read_json(resolved)
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _trace_screenshot_path(trace: dict[str, Any]) -> str:
    for key in ("screenshot_path", "image_path", "source_image_path"):
        value = trace.get(key)
        if value:
            return str(value)
    for container_key in ("input", "request", "capture", "screenshot", "metadata"):
        container = _dict(trace.get(container_key))
        for key in ("screenshot_path", "image_path", "source_image_path"):
            value = container.get(key)
            if value:
                return str(value)
    return ""


def _two_stage_source(source: dict[str, Any]) -> dict[str, Any]:
    if source.get("contract_version") == "learn_two_stage_screen_understanding_v1":
        return source
    if isinstance(source.get("stage2_numbering"), dict) and isinstance(source.get("fusion"), dict):
        return source
    nested = _dict(source.get("two_stage_understanding"))
    if nested.get("contract_version") == "learn_two_stage_screen_understanding_v1":
        return nested
    if isinstance(nested.get("stage2_numbering"), dict) and isinstance(nested.get("fusion"), dict):
        return nested
    return {}


def _is_two_stage_source(source: dict[str, Any]) -> bool:
    return bool(_two_stage_source(source))


def _load_or_build_precise_candidate(*, source_file: Path, out_dir: Path, root: Path) -> dict[str, Any]:
    source = _read_json(source_file)
    if source.get("contract_version") == "learn_precise_understanding_candidate_v1":
        return source
    review = load_learning_draft_review(_relative_path(source_file, root), project_root=root)
    candidate = _dict(_dict(review.get("pathgraph_candidate_review")).get("precise_understanding_candidate"))
    if candidate:
        return candidate
    return build_learn_precise_understanding_candidate(source_path=_relative_path(source_file, root), out_dir=out_dir, project_root=root)


_PAGE_DETAIL_PARENT_GROUP_ROLES = {
    "hero_panel",
    "hero_text_panel",
    "hero_code_panel",
    "section_parent",
    "media_card_group",
    "tile_card_group",
    "list_group",
    "list_row",
    "member_list_region",
    "conversation_row",
    "message_item",
    "input_toolbar_region",
    "topbar_control_strip",
    "topbar_control_cluster",
}


_PAGE_DETAIL_CHILD_EVIDENCE_ROLES = {
    "text",
    "text_action",
    "button",
    "menu_item",
    "nav_text_action",
}


_PAGE_DETAIL_HERO_PARENT_ROLES = {
    "hero_panel",
    "hero_text_panel",
    "hero_code_panel",
}


_PAGE_DETAIL_HERO_CHILD_EXTRA_ROLES = {
    "news_card",
    "recommendation_item",
    "partial_visible_card",
}


_PAGE_DETAIL_EXCLUSIVE_SIBLING_PANEL_ROLES = {
    "hero_text_panel",
    "hero_code_panel",
}

_PAGE_DETAIL_ROW_SHELL_ROLES = {
    "nav_item",
    "notice_item",
}

_PAGE_DETAIL_CONTAINER_DISPLAY_GROUP_ROLES = {
    "member_list_region",
    "notice_region",
    "message_item",
}

_PAGE_DETAIL_CONTAINER_CHILD_ROLES = {
    "member_list_region": {"nav_item", "member_item"},
    "notice_region": {"notice_item", "text", "text_action"},
    "message_item": {"message_bubble", "message_card", "message_card_content", "image_message", "text"},
}


def _regions_from_two_stage(source: dict[str, Any]) -> list[dict[str, Any]]:
    stage2 = _dict(source.get("stage2_numbering"))
    regions: list[dict[str, Any]] = []
    next_region_no = 1
    for parent in _list_of_dicts(stage2.get("regions")):
        numbered_items = _list_of_dicts(parent.get("numbered_items"))
        items_by_id = {str(item.get("item_id") or ""): item for item in numbered_items}
        child_ids_by_group = _two_stage_child_ids_by_group(parent)
        child_ids: set[str] = set()
        for group in _list_of_dicts(parent.get("subregion_groups")):
            group_id = str(group.get("group_id") or "")
            region = _region_from_two_stage_group(
                group,
                parent=parent,
                items_by_id=items_by_id,
                child_ids=child_ids_by_group.get(group_id, []),
                index=next_region_no,
            )
            if region:
                regions.append(region)
                next_region_no += 1
                child_ids.update(str(item.get("source_item_id") or "") for item in region.get("child_evidence", []) if item)
        for item in numbered_items:
            item_id = str(item.get("item_id") or "")
            if item_id in child_ids and str(item.get("role") or "") in _PAGE_DETAIL_CHILD_EVIDENCE_ROLES:
                continue
            region = _region_from_two_stage_item(item, parent=parent, index=next_region_no)
            if region:
                regions.append(region)
                next_region_no += 1
    return regions


def _resolve_page_detail_sibling_panel_overlaps(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    resolved = [dict(region) for region in regions]
    by_section: dict[str, list[int]] = {}
    for index, region in enumerate(resolved):
        role = str(region.get("role") or "")
        if role not in _PAGE_DETAIL_EXCLUSIVE_SIBLING_PANEL_ROLES:
            continue
        section_id = str(region.get("source_section_id") or region.get("source_parent_region_id") or "")
        if not section_id:
            continue
        by_section.setdefault(section_id, []).append(index)

    for indices in by_section.values():
        ordered = sorted(indices, key=lambda idx: _bbox_sort_key(_dict(resolved[idx].get("bbox"))))
        for left_idx, right_idx in zip(ordered, ordered[1:]):
            left = resolved[left_idx]
            right = resolved[right_idx]
            left_bbox = _normalized_int_bbox(_dict(left.get("bbox")))
            right_bbox = _normalized_int_bbox(_dict(right.get("bbox")))
            if not left_bbox or not right_bbox:
                continue
            if not _should_clip_sibling_panel_overlap(left_bbox, right_bbox):
                continue
            clipped = _clip_right_sibling_after_left(left_bbox, right_bbox)
            if not clipped:
                continue
            patched = dict(right)
            patched["bbox"] = clipped
            patched["visual_order_key"] = [clipped["y"], clipped["x"]]
            evidence = dict(_dict(patched.get("evidence")))
            evidence["page_detail_collision_resolution"] = {
                "status": "clipped_sibling_overlap",
                "reason": "same_section_sibling_panels_without_containment_must_not_overlap",
                "left_region_id": left.get("region_id"),
                "left_role": left.get("role"),
                "right_region_id": right.get("region_id"),
                "right_role": right.get("role"),
                "original_bbox": right_bbox,
                "resolved_bbox": clipped,
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
            patched["evidence"] = evidence
            resolved[right_idx] = patched
    return resolved


def _bbox_sort_key(bbox: dict[str, Any]) -> list[int]:
    normalized = _normalized_int_bbox(bbox)
    return [normalized.get("x", 0), normalized.get("y", 0)]


def _normalized_int_bbox(bbox: dict[str, Any]) -> dict[str, int]:
    normalized = _normalize_bbox(bbox)
    if not normalized:
        return {}
    try:
        x = int(normalized.get("x") or 0)
        y = int(normalized.get("y") or 0)
        w = int(normalized.get("w") or 0)
        h = int(normalized.get("h") or 0)
    except (TypeError, ValueError):
        return {}
    if w <= 0 or h <= 0:
        return {}
    return {"x": x, "y": y, "w": w, "h": h}


def _should_clip_sibling_panel_overlap(left: dict[str, int], right: dict[str, int]) -> bool:
    if _bbox_containment_ratio(left, right) >= 0.9 or _bbox_containment_ratio(right, left) >= 0.9:
        return False
    overlap_area = _bbox_intersection_area(left, right)
    if overlap_area <= 0:
        return False
    vertical_overlap = _bbox_axis_overlap(
        int(left["y"]),
        int(left["y"]) + int(left["h"]),
        int(right["y"]),
        int(right["y"]) + int(right["h"]),
    )
    if vertical_overlap / max(1, min(int(left["h"]), int(right["h"]))) < 0.35:
        return False
    return overlap_area / max(1, min(_bbox_area(left), _bbox_area(right))) >= 0.08


def _clip_right_sibling_after_left(left: dict[str, int], right: dict[str, int]) -> dict[str, int]:
    gap = 8
    new_x = int(left["x"]) + int(left["w"]) + gap
    original_right = int(right["x"]) + int(right["w"])
    if new_x <= int(right["x"]):
        return {}
    new_w = original_right - new_x
    if new_w < 120:
        return {}
    return {"x": new_x, "y": int(right["y"]), "w": new_w, "h": int(right["h"])}


def _resolve_page_detail_overlapping_row_shells(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    resolved = [dict(region) for region in regions]
    by_section: dict[str, list[int]] = {}
    for index, region in enumerate(resolved):
        role = str(region.get("role") or "").casefold()
        if role not in _PAGE_DETAIL_ROW_SHELL_ROLES:
            continue
        section_id = str(region.get("source_section_id") or region.get("source_parent_region_id") or "")
        if not section_id:
            continue
        by_section.setdefault(section_id, []).append(index)

    for indices in by_section.values():
        row_boxes = []
        for index in indices:
            bbox = _normalized_int_bbox(_dict(resolved[index].get("bbox")))
            if bbox:
                row_boxes.append(bbox)
        if len(row_boxes) < 3:
            continue
        heights = sorted(item["h"] for item in row_boxes)
        median_height = heights[len(heights) // 2]
        for index in indices:
            region = resolved[index]
            bbox = _normalized_int_bbox(_dict(region.get("bbox")))
            if not bbox:
                continue
            if bbox["h"] < max(96, int(median_height * 2.75)):
                continue
            overlapped = []
            for other_index in indices:
                if other_index == index:
                    continue
                other = resolved[other_index]
                other_box = _normalized_int_bbox(_dict(other.get("bbox")))
                if other_box and _row_shell_overlaps_more_specific_row(bbox, other_box):
                    overlapped.append(other)
            if len(overlapped) < 2:
                continue
            patched = dict(region)
            patched["visual_emphasis"] = "low_review"
            patched["page_detail_review_category"] = "overlapping_row_shell_review"
            patched["render_in_spatial_preview"] = False
            evidence = dict(_dict(patched.get("evidence")))
            evidence["page_detail_overlap_resolution"] = {
                "status": "suppressed_overlapping_row_shell",
                "reason": "oversized_row_shell_overlaps_more_specific_same_section_rows",
                "overlapped_sibling_count": len(overlapped),
                "overlapped_region_ids": [item.get("region_id") for item in overlapped],
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
            patched["evidence"] = evidence
            resolved[index] = patched
    return resolved


def _row_shell_overlaps_more_specific_row(shell: dict[str, int], row: dict[str, int]) -> bool:
    if _bbox_area(row) >= _bbox_area(shell):
        return False
    horizontal_overlap = _bbox_axis_overlap(shell["x"], shell["x"] + shell["w"], row["x"], row["x"] + row["w"])
    if horizontal_overlap / max(1, min(shell["w"], row["w"])) < 0.75:
        return False
    vertical_overlap = _bbox_axis_overlap(shell["y"], shell["y"] + shell["h"], row["y"], row["y"] + row["h"])
    return vertical_overlap / max(1, row["h"]) >= 0.65


def _bbox_intersection_area(a: dict[str, int], b: dict[str, int]) -> int:
    x1 = max(int(a["x"]), int(b["x"]))
    y1 = max(int(a["y"]), int(b["y"]))
    x2 = min(int(a["x"]) + int(a["w"]), int(b["x"]) + int(b["w"]))
    y2 = min(int(a["y"]) + int(a["h"]), int(b["y"]) + int(b["h"]))
    return max(0, x2 - x1) * max(0, y2 - y1)


def _bbox_axis_overlap(a1: int, a2: int, b1: int, b2: int) -> int:
    return max(0, min(a2, b2) - max(a1, b1))


def _bbox_area(bbox: dict[str, int]) -> int:
    return max(1, int(bbox["w"]) * int(bbox["h"]))


def _page_detail_display_groups(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = _container_display_groups(regions)
    rows_by_parent: dict[str, list[dict[str, Any]]] = {}
    for region in regions:
        if str(region.get("role") or "").casefold() != "list_row":
            continue
        bbox = _normalized_int_bbox(_dict(region.get("bbox")))
        if not bbox:
            continue
        parent_id = str(region.get("source_section_id") or region.get("source_parent_region_id") or "root")
        rows_by_parent.setdefault(parent_id, []).append(region)

    for parent_id, rows in sorted(rows_by_parent.items()):
        for column_index, column_rows in enumerate(_cluster_display_list_rows(rows), start=1):
            if len(column_rows) < 2:
                continue
            group_id = _display_group_id(parent_id, "list_group", column_index)
            for item in column_rows:
                item["parent_display_group_id"] = group_id
                item["parent_display_group_role"] = "list_group"
            groups.append(
                {
                    "group_id": group_id,
                    "label": _display_list_group_label(column_rows, column_index=column_index),
                    "role": "list_group",
                    "bbox": _padded_bbox_union([_dict(item.get("bbox")) for item in column_rows], padding=10),
                    "source_section_id": parent_id,
                    "source_section_label": column_rows[0].get("source_section_label"),
                    "member_region_numbers": [item.get("region_no") for item in column_rows],
                    "member_region_ids": [item.get("region_id") for item in column_rows],
                    "member_count": len(column_rows),
                    "group_source": "page_detail_list_row_cluster",
                    "visual_emphasis": "review_group",
                    "display_only": True,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                }
            )
    _attach_list_group_footers(regions=regions, groups=groups)
    return sorted(groups, key=lambda item: _bbox_sort_key(_dict(item.get("bbox"))))


def _container_display_groups(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    containers = [
        region
        for region in regions
        if str(region.get("role") or "").casefold() in _PAGE_DETAIL_CONTAINER_DISPLAY_GROUP_ROLES
        and _normalized_int_bbox(_dict(region.get("bbox")))
    ]
    for container in containers:
        role = str(container.get("role") or "").casefold()
        container_box = _normalized_int_bbox(_dict(container.get("bbox")))
        section_id = str(container.get("source_section_id") or container.get("source_parent_region_id") or "root")
        child_roles = _PAGE_DETAIL_CONTAINER_CHILD_ROLES.get(role, set())
        children: list[dict[str, Any]] = []
        for region in regions:
            if region is container:
                continue
            if region.get("parent_display_group_id"):
                continue
            if str(region.get("source_section_id") or region.get("source_parent_region_id") or "root") != section_id:
                continue
            if str(region.get("role") or "").casefold() not in child_roles:
                continue
            bbox = _normalized_int_bbox(_dict(region.get("bbox")))
            if not bbox or _bbox_containment_ratio(bbox, container_box) < 0.82:
                continue
            children.append(region)
        children = sorted(children, key=lambda item: _bbox_sort_key(_dict(item.get("bbox"))))
        if len(children) < 2:
            continue
        group_id = f"{container.get('region_id') or role}__contained_children"
        for child in children:
            child["parent_display_group_id"] = group_id
            child["parent_display_group_role"] = role
        groups.append(
            {
                "group_id": group_id,
                "label": container.get("label") or role.replace("_", " "),
                "role": role,
                "bbox": container_box,
                "source_section_id": section_id,
                "source_section_label": container.get("source_section_label"),
                "container_region_no": container.get("region_no"),
                "container_region_id": container.get("region_id"),
                "member_region_numbers": [item.get("region_no") for item in children],
                "member_region_ids": [item.get("region_id") for item in children],
                "member_count": len(children),
                "group_source": "page_detail_container_with_contained_children",
                "visual_emphasis": "review_group",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    return groups


def _attach_list_group_footers(*, regions: list[dict[str, Any]], groups: list[dict[str, Any]]) -> None:
    list_groups = [group for group in groups if group.get("role") == "list_group" and _normalized_int_bbox(_dict(group.get("bbox")))]
    if not list_groups:
        return
    for region in regions:
        if region.get("parent_display_group_id"):
            continue
        if not _is_list_footer_candidate(region):
            continue
        region_box = _normalized_int_bbox(_dict(region.get("bbox")))
        if not region_box:
            continue
        region_parent = str(region.get("source_section_id") or region.get("source_parent_region_id") or "root")
        candidates = [
            group
            for group in list_groups
            if str(group.get("source_section_id") or "") == region_parent
            and _list_footer_fits_group(region_box, _normalized_int_bbox(_dict(group.get("bbox"))))
        ]
        if not candidates:
            continue
        group = min(candidates, key=lambda item: _list_footer_group_distance(region_box, _normalized_int_bbox(_dict(item.get("bbox")))))
        footer_numbers = group.setdefault("footer_region_numbers", [])
        footer_ids = group.setdefault("footer_region_ids", [])
        footer_numbers.append(region.get("region_no"))
        footer_ids.append(region.get("region_id"))
        group["footer_count"] = len(footer_numbers)
        expand_bbox = _list_footer_should_expand_group_bbox(region_box, _normalized_int_bbox(_dict(group.get("bbox"))))
        if expand_bbox:
            group["bbox"] = _padded_bbox_union([_dict(group.get("bbox")), _dict(region.get("bbox"))], padding=0)
        group["footer_bbox_policy"] = (
            "included_in_group_bbox" if expand_bbox else "semantic_attachment_no_bbox_expand"
        )
        connector = None if expand_bbox else _list_footer_connector(group=_dict(group.get("bbox")), footer=region_box)
        if connector:
            connectors = group.setdefault("footer_connectors", [])
            connector.update(
                {
                    "footer_region_no": region.get("region_no"),
                    "footer_region_id": region.get("region_id"),
                }
            )
            connectors.append(connector)
        group["group_source"] = "page_detail_list_row_cluster_with_footer"
        region["parent_display_group_id"] = group.get("group_id")
        region["parent_display_group_role"] = "list_group_footer"
        region["page_detail_review_category"] = "list_group_footer"
        region["visual_emphasis"] = "review_group_child"
        region.setdefault("evidence", {})
        if isinstance(region["evidence"], dict):
            region["evidence"]["list_group_footer_attachment"] = {
                "contract_version": "learn_page_detail_list_group_footer_attachment_v1",
                "parent_display_group_id": group.get("group_id"),
                "attachment_reason": "short_link_below_same_section_list_group",
                "bbox_expanded": expand_bbox,
                "footer_bbox_policy": group["footer_bbox_policy"],
                "connector_available": connector is not None,
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }


def _is_list_footer_candidate(region: dict[str, Any]) -> bool:
    bbox = _normalized_int_bbox(_dict(region.get("bbox")))
    if not bbox:
        return False
    label = str(region.get("label") or region.get("region_id") or "").casefold()
    role = str(region.get("role") or "").casefold()
    if bbox["h"] > 64 or bbox["w"] > 180:
        return False
    if role in {"list_row", "media_card", "message_item", "member_item"}:
        return False
    footer_terms = ("more", "see all", "view all", "show all", "更多", "查看更多", "全部")
    if any(term in label for term in footer_terms):
        return True
    return role in {"link", "footer_link", "text_link", "pagination", "partial_visible_card"} and bbox["w"] <= 120


def _list_footer_fits_group(footer: dict[str, int], group: dict[str, int]) -> bool:
    if not group:
        return False
    footer_center_x = footer["x"] + footer["w"] / 2
    group_left = group["x"]
    group_right = group["x"] + group["w"]
    group_bottom = group["y"] + group["h"]
    vertical_gap = footer["y"] - group_bottom
    if vertical_gap < -12 or vertical_gap > 180:
        return False
    return group_left - 80 <= footer_center_x <= group_right + max(260, int(group["w"] * 0.9))


def _list_footer_should_expand_group_bbox(footer: dict[str, int], group: dict[str, int]) -> bool:
    if not group:
        return False
    footer_left = footer["x"]
    footer_right = footer["x"] + footer["w"]
    group_left = group["x"]
    group_right = group["x"] + group["w"]
    horizontal_overlap = min(footer_right, group_right) - max(footer_left, group_left)
    if horizontal_overlap > 0:
        return True
    nearest_gap = min(abs(footer_left - group_right), abs(group_left - footer_right))
    return nearest_gap <= min(80, max(32, int(group["w"] * 0.25)))


def _list_footer_connector(*, group: dict[str, int], footer: dict[str, int]) -> dict[str, Any] | None:
    group_box = _normalized_int_bbox(group)
    footer_box = _normalized_int_bbox(footer)
    if not group_box or not footer_box:
        return None
    group_center_y = group_box["y"] + group_box["h"] // 2
    footer_center_y = footer_box["y"] + footer_box["h"] // 2
    if footer_box["x"] >= group_box["x"] + group_box["w"]:
        from_x = group_box["x"] + group_box["w"]
        to_x = footer_box["x"]
    elif footer_box["x"] + footer_box["w"] <= group_box["x"]:
        from_x = group_box["x"]
        to_x = footer_box["x"] + footer_box["w"]
    else:
        from_x = group_box["x"] + group_box["w"] // 2
        to_x = footer_box["x"] + footer_box["w"] // 2
    return {
        "contract_version": "learn_page_detail_footer_connector_v1",
        "connector_role": "review_only_semantic_attachment",
        "from_point": {"x": from_x, "y": group_center_y},
        "to_point": {"x": to_x, "y": footer_center_y},
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _list_footer_group_distance(footer: dict[str, int], group: dict[str, int]) -> float:
    footer_center_x = footer["x"] + footer["w"] / 2
    group_center_x = group["x"] + group["w"] / 2
    group_bottom = group["y"] + group["h"]
    vertical_gap = max(0, footer["y"] - group_bottom)
    horizontal_gap = abs(footer_center_x - group_center_x)
    return vertical_gap * 3 + horizontal_gap


def _cluster_display_list_rows(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    clusters: list[list[dict[str, Any]]] = []
    for row in sorted(rows, key=lambda item: _bbox_sort_key(_dict(item.get("bbox")))):
        bbox = _normalized_int_bbox(_dict(row.get("bbox")))
        if not bbox:
            continue
        for cluster in clusters:
            if _list_row_fits_display_column(cluster, bbox):
                cluster.append(row)
                break
        else:
            clusters.append([row])
    return [sorted(cluster, key=lambda item: _bbox_sort_key(_dict(item.get("bbox")))) for cluster in clusters]


def _list_row_fits_display_column(cluster: list[dict[str, Any]], bbox: dict[str, int]) -> bool:
    anchors = [_normalized_int_bbox(_dict(item.get("bbox"))) for item in cluster]
    anchors = [item for item in anchors if item]
    if not anchors:
        return False
    lefts = sorted(item["x"] for item in anchors)
    widths = sorted(item["w"] for item in anchors)
    median_left = lefts[len(lefts) // 2]
    median_width = widths[len(widths) // 2]
    tolerance = max(90, int(max(1, min(median_width, bbox["w"])) * 0.35))
    return abs(int(bbox["x"]) - int(median_left)) <= tolerance


def _display_group_id(parent_id: str, role: str, index: int) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in parent_id.casefold()).strip("_")
    return f"{slug or 'root'}__{role}_{index}"


def _display_list_group_label(rows: list[dict[str, Any]], *, column_index: int) -> str:
    parent_label = str(rows[0].get("source_section_label") or "section")
    return f"List group {column_index}: {parent_label}"


def _padded_bbox_union(boxes: list[dict[str, Any]], *, padding: int) -> dict[str, int]:
    normalized = [_normalized_int_bbox(_dict(item)) for item in boxes]
    normalized = [item for item in normalized if item]
    if not normalized:
        return {}
    min_x = min(item["x"] for item in normalized)
    min_y = min(item["y"] for item in normalized)
    max_x = max(item["x"] + item["w"] for item in normalized)
    max_y = max(item["y"] + item["h"] for item in normalized)
    return {
        "x": max(0, min_x - padding),
        "y": max(0, min_y - padding),
        "w": max(1, max_x - min_x + padding * 2),
        "h": max(1, max_y - min_y + padding * 2),
    }


def _regions_from_fused_review_boxes(source: dict[str, Any]) -> list[dict[str, Any]]:
    fusion = _dict(source.get("fusion"))
    boxes = _list_of_dicts(fusion.get("fused_review_boxes"))
    regions: list[dict[str, Any]] = []
    next_region_no = 1
    for box in boxes:
        if str(box.get("box_type") or "") == "structure_region":
            continue
        if box.get("render_in_main_overlay") is False:
            continue
        region = _region_from_fused_review_box(box, index=next_region_no)
        if region:
            regions.append(region)
            next_region_no += 1
    return regions


def _overlay_precise_locator_regions(
    regions: list[dict[str, Any]],
    source: dict[str, Any],
) -> list[dict[str, Any]]:
    calibrated_source = _dict(_dict(_dict(source.get("observe_bundle")).get("sources")).get("calibrated_targets"))
    precise_targets = [
        item
        for item in _list_of_dicts(calibrated_source.get("targets"))
        if str(item.get("coordinate_source") or "") == "precise_locator_v1" and _dict(item.get("bbox"))
    ]
    if not precise_targets:
        return regions
    target_by_key: dict[str, dict[str, Any]] = {}
    for target in precise_targets:
        for key in _calibrated_target_match_keys(target):
            target_by_key.setdefault(key, target)
    output: list[dict[str, Any]] = []
    used_target_ids: set[str] = set()
    for region in regions:
        target = next(
            (
                target_by_key[key]
                for key in _page_detail_region_match_keys(region)
                if key in target_by_key and _precise_target_identity(target_by_key[key]) not in used_target_ids
            ),
            None,
        )
        if not target:
            target = _geometric_precise_target_for_region(
                region,
                precise_targets,
                used_target_ids=used_target_ids,
            )
        if not target:
            output.append(region)
            continue
        used_target_ids.add(_precise_target_identity(target))
        updated = dict(region)
        bbox = _dict(target.get("bbox"))
        updated["bbox"] = bbox
        updated["candidate_point"] = _dict(target.get("click_point"))
        updated["visual_order_key"] = [int(bbox.get("y") or 0), int(bbox.get("x") or 0)]
        updated["page_detail_source"] = "precise_locator_calibrated_target"
        evidence = dict(_dict(updated.get("evidence")))
        evidence.update(
            {
                "calibrated_candidate_id": target.get("candidate_id") or target.get("id"),
                "coordinate_source": "precise_locator_v1",
                "coordinate_validation": _dict(target.get("coordinate_validation")),
                "precise_locator_evidence": _dict(target.get("precise_locator_evidence")),
            }
        )
        updated["evidence"] = evidence
        parent_bbox = _dict(target.get("parent_bbox")) or _dict(
            next(
                (
                    item.get("bbox")
                    for item in _list_of_dicts(updated.get("child_evidence"))
                    if item.get("source_item_id") == updated.get("source_parent_region_id")
                ),
                {},
            )
        )
        if not parent_bbox:
            parent_bbox = _dict(updated.get("source_parent_bbox"))
        if parent_bbox:
            ratio = _bbox_containment_ratio(bbox, parent_bbox)
            updated["source_section_containment_ratio"] = round(ratio, 4)
            updated["inside_source_section"] = ratio >= 0.85
        output.append(updated)
    return output


def _geometric_precise_target_for_region(
    region: dict[str, Any],
    targets: list[dict[str, Any]],
    *,
    used_target_ids: set[str],
) -> dict[str, Any] | None:
    region_bbox = _dict(region.get("bbox"))
    if not region_bbox:
        return None
    matches: list[tuple[float, dict[str, Any]]] = []
    for target in targets:
        if _precise_target_identity(target) in used_target_ids:
            continue
        if not _page_detail_roles_compatible(str(region.get("role") or ""), str(target.get("role") or "")):
            continue
        overlap = _page_detail_bbox_iou(region_bbox, _dict(target.get("bbox")))
        if overlap >= 0.72:
            matches.append((overlap, target))
    if not matches:
        return None
    matches.sort(key=lambda item: item[0], reverse=True)
    if len(matches) > 1 and matches[0][0] - matches[1][0] < 0.08:
        return None
    return matches[0][1]


def _precise_target_identity(target: dict[str, Any]) -> str:
    return str(target.get("candidate_id") or target.get("id") or id(target))


def _page_detail_roles_compatible(region_role: str, target_role: str) -> bool:
    return _page_detail_role_family(region_role) == _page_detail_role_family(target_role)


def _page_detail_role_family(role: str) -> str:
    value = str(role or "").casefold()
    if "partial" in value and "card" in value:
        return "partial_card"
    if "card" in value or "recommendation" in value or "tile" in value:
        return "card"
    if "nav" in value or "sidebar" in value or "menu" in value:
        return "navigation"
    if "text" in value or value in {"label", "heading"}:
        return "text"
    if "input" in value or "field" in value or "search_box" in value:
        return "input"
    if "control" in value or "button" in value or "icon" in value:
        return "control"
    return value


def _page_detail_bbox_iou(left: dict[str, Any], right: dict[str, Any]) -> float:
    if not left or not right:
        return 0.0
    left_x1 = float(left.get("x") or 0)
    left_y1 = float(left.get("y") or 0)
    left_x2 = left_x1 + max(0.0, float(left.get("w") or 0))
    left_y2 = left_y1 + max(0.0, float(left.get("h") or 0))
    right_x1 = float(right.get("x") or 0)
    right_y1 = float(right.get("y") or 0)
    right_x2 = right_x1 + max(0.0, float(right.get("w") or 0))
    right_y2 = right_y1 + max(0.0, float(right.get("h") or 0))
    intersection = max(0.0, min(left_x2, right_x2) - max(left_x1, right_x1)) * max(
        0.0,
        min(left_y2, right_y2) - max(left_y1, right_y1),
    )
    union = max(0.0, (left_x2 - left_x1) * (left_y2 - left_y1)) + max(
        0.0,
        (right_x2 - right_x1) * (right_y2 - right_y1),
    ) - intersection
    return intersection / union if union > 0 else 0.0


def _calibrated_target_match_keys(target: dict[str, Any]) -> set[str]:
    candidate_id = str(target.get("candidate_id") or target.get("id") or "").strip()
    if not candidate_id:
        return set()
    keys = {_normalized_match_key(candidate_id)}
    parts = [part for part in candidate_id.replace("/", ":").split(":") if part]
    if len(parts) >= 2:
        keys.add(_normalized_match_key("_".join(parts[-2:])))
    return {key for key in keys if key}


def _page_detail_region_match_keys(region: dict[str, Any]) -> set[str]:
    values = [region.get("region_id"), region.get("source_item_id")]
    values.extend(item.get("source_item_id") for item in _list_of_dicts(region.get("child_evidence")))
    keys: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        keys.add(_normalized_match_key(text))
        prefix = "two_stage_review_"
        if text.casefold().startswith(prefix):
            keys.add(_normalized_match_key(text[len(prefix) :]))
    return {key for key in keys if key}


def _normalized_match_key(value: Any) -> str:
    return "".join(char for char in str(value or "").casefold() if char.isalnum())


def _region_from_fused_review_box(box: dict[str, Any], *, index: int) -> dict[str, Any]:
    bbox = _dict(box.get("bbox"))
    if not bbox:
        return {}
    role = str(box.get("role") or "region")
    parent = {
        "region_id": box.get("parent_region_id"),
        "label": box.get("parent_region_label"),
        "bbox": box.get("parent_region_bbox"),
    }
    parent_bbox = _dict(parent.get("bbox"))
    section_ratio = _bbox_containment_ratio(bbox, parent_bbox) if parent_bbox else 0.0
    hierarchy = _dict(box.get("display_hierarchy")) or _dict(box.get("group_display_hierarchy"))
    region_id = _fused_region_id(box, index)
    operation = _possible_operation({"label": box.get("label"), "role": role})
    review_category = _page_detail_review_category_for_fused_box(box, role=role, hierarchy=hierarchy)
    visual_emphasis = _page_detail_visual_emphasis(review_category)
    return {
        "region_no": index,
        "region_id": region_id,
        "source_item_id": region_id,
        "label": box.get("label") or region_id,
        "role": role,
        "bbox": bbox,
        "candidate_point": _dict(box.get("candidate_point") or box.get("click_point")),
        "layout_zone": _layout_zone_for_two_stage(parent, box, bbox) if parent.get("region_id") else _layout_zone(box, bbox),
        "visual_order_key": [int(bbox.get("y") or 0), int(bbox.get("x") or 0)],
        "description": _description({"label": box.get("label"), "role": role}, operation),
        "possible_operation": operation,
        "child_evidence": [_child_evidence_from_fused_child(item) for item in _list_of_dicts(box.get("children"))],
        "child_evidence_count": len(_list_of_dicts(box.get("children"))),
        "source_parent_region_id": parent.get("region_id"),
        "source_parent_region_label": parent.get("label"),
        "source_section_id": parent.get("region_id"),
        "source_section_label": parent.get("label"),
        "source_section_containment_ratio": round(section_ratio, 4),
        "inside_source_section": section_ratio >= 0.85 if parent_bbox else None,
        "page_detail_source": "two_stage_fused_review_box",
        "display_layer": hierarchy.get("display_layer") or "review_region",
        "page_detail_review_category": review_category,
        "visual_emphasis": visual_emphasis,
        "calibration_state": "page_detail_review_only",
        "pathgraph_candidate_review_state": "blocked_page_detail_review_only",
        "required_next_step": "review_before_pathgraph_promotion",
        "evidence": {
            "box_type": box.get("box_type"),
            "number": box.get("number"),
            "parent_region_id": parent.get("region_id"),
            "render_in_main_overlay": box.get("render_in_main_overlay") is not False,
            "display_hierarchy": hierarchy,
        },
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "render_in_spatial_preview": True,
    }


def _page_detail_review_category_for_fused_box(
    box: dict[str, Any],
    *,
    role: str,
    hierarchy: dict[str, Any],
) -> str:
    label = str(box.get("label") or "").casefold()
    role_text = str(role or "").casefold()
    reason = str(hierarchy.get("reason") or hierarchy.get("suppression_reason") or "").casefold()
    box_type = str(box.get("box_type") or "").casefold()
    if role_text in {"topbar_control_strip", "topbar_control_cluster"}:
        return "container_shell_review"
    if role_text in _PAGE_DETAIL_HERO_PARENT_ROLES and box_type == "subregion_group":
        return "semantic_panel_review"
    if "background" in label or "empty review" in label or "background" in role_text:
        return "background_or_empty_review"
    if "boundary_review" in role_text or "boundary review" in label:
        return "boundary_review_region"
    if "partial_visible" in role_text or "partial visible" in label:
        return "partial_visible_review"
    if "semantic_region_only_without_grounding_evidence" in reason:
        return "semantic_only_without_grounding_evidence"
    if box_type in {"subregion_group", "numbered_item"}:
        return "visible_review_region"
    return "review_region"


def _page_detail_visual_emphasis(review_category: str) -> str:
    if review_category in {
        "background_or_empty_review",
        "boundary_review_region",
        "partial_visible_review",
        "container_shell_review",
        "overlapping_row_shell_review",
    }:
        return "low_review"
    if review_category in {"semantic_only_without_grounding_evidence", "semantic_panel_review"}:
        return "review_candidate"
    return "primary_content"


def _fused_region_id(box: dict[str, Any], index: int) -> str:
    number = str(box.get("number") or "").strip()
    if number and not any(char.isspace() for char in number):
        return number.replace(".", "_").replace(":", "_")
    label = str(box.get("label") or "").strip()
    if label:
        safe = "".join(char if char.isalnum() else "_" for char in label.casefold()).strip("_")
        if safe:
            return f"fused_{index}_{safe[:40]}"
    return f"fused_review_box_{index}"


def _child_evidence_from_fused_child(item: dict[str, Any]) -> dict[str, Any]:
    bbox = _dict(item.get("bbox"))
    return {
        "source_item_id": item.get("item_id") or item.get("source_item_id") or item.get("number"),
        "number": item.get("number"),
        "label": item.get("label") or item.get("text") or item.get("item_id"),
        "role": item.get("role"),
        "bbox": bbox,
        "display_layer": "child_evidence",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _layout_sections_from_two_stage(source: dict[str, Any], regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stage2 = _dict(source.get("stage2_numbering"))
    regions_by_parent: dict[str, list[dict[str, Any]]] = {}
    for region in sorted(regions, key=lambda value: value.get("visual_order_key") or [0, 0]):
        parent_id = str(region.get("source_section_id") or region.get("source_parent_region_id") or "")
        if not parent_id:
            continue
        regions_by_parent.setdefault(parent_id, []).append(region)

    sections: list[dict[str, Any]] = []
    for parent in sorted(
        _list_of_dicts(stage2.get("regions")),
        key=lambda value: [
            int(_dict(value.get("bbox")).get("y") or 0),
            int(_dict(value.get("bbox")).get("x") or 0),
        ],
    ):
        parent_id = str(parent.get("region_id") or "")
        parent_bbox = _dict(parent.get("bbox"))
        if not parent_id or not parent_bbox:
            continue
        items = regions_by_parent.get(parent_id) or []
        sections.append(
            {
                "section_id": parent_id,
                "label": parent.get("label") or parent_id,
                "bbox": parent_bbox,
                "layout_zone": _layout_zone_for_stage_parent(parent),
                "section_source": "stage2_parent_region",
                "source_stage_region_id": parent_id,
                "region_count": len(items),
                "region_numbers": [item.get("region_no") for item in items],
                "possible_operations": sorted(
                    {str(_dict(item.get("possible_operation")).get("kind") or "read_only") for item in items}
                ),
                "operation_summary": _operation_summary(items),
                "operation_links": [_operation_link(item) for item in items],
                "regions": items,
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    return sections


def _two_stage_child_ids_by_group(parent: dict[str, Any]) -> dict[str, list[str]]:
    groups = _list_of_dicts(parent.get("subregion_groups"))
    numbered_items = _list_of_dicts(parent.get("numbered_items"))
    by_group: dict[str, list[str]] = {}

    def add(group_id: str, item_id: str) -> None:
        if not group_id or not item_id:
            return
        values = by_group.setdefault(group_id, [])
        if item_id not in values:
            values.append(item_id)

    for group in groups:
        group_id = str(group.get("group_id") or "")
        group_role = str(group.get("role") or "")
        explicit_ids = [*_list(group.get("member_item_ids")), *_list(group.get("child_item_ids"))]
        for raw_item_id in explicit_ids:
            add(group_id, str(raw_item_id or ""))
        if group_role not in _PAGE_DETAIL_PARENT_GROUP_ROLES:
            continue
        group_bbox = _dict(group.get("bbox"))
        if not group_bbox:
            continue
        for item in numbered_items:
            item_id = str(item.get("item_id") or "")
            role = str(item.get("role") or "")
            bbox = _dict(item.get("bbox"))
            eligible_child_role = role in _PAGE_DETAIL_CHILD_EVIDENCE_ROLES or (
                group_role in _PAGE_DETAIL_HERO_PARENT_ROLES and role in _PAGE_DETAIL_HERO_CHILD_EXTRA_ROLES
            )
            if not item_id or not eligible_child_role or not bbox:
                continue
            if _bbox_containment_ratio(bbox, group_bbox) >= 0.9:
                add(group_id, item_id)
    return by_group


def _region_from_two_stage_group(
    group: dict[str, Any],
    *,
    parent: dict[str, Any],
    items_by_id: dict[str, dict[str, Any]],
    child_ids: list[str],
    index: int,
) -> dict[str, Any]:
    bbox = _dict(group.get("bbox"))
    if not bbox:
        return {}
    group_id = str(group.get("group_id") or f"two_stage_group_{index}")
    child_evidence = [_child_evidence_from_two_stage_item(items_by_id[item_id]) for item_id in child_ids if item_id in items_by_id]
    role = str(group.get("role") or "region")
    operation = _possible_operation({"label": group.get("label"), "role": role})
    parent_bbox = _dict(parent.get("bbox"))
    section_ratio = _bbox_containment_ratio(bbox, parent_bbox) if parent_bbox else 0.0
    return {
        "region_no": index,
        "region_id": group_id,
        "source_item_id": group_id,
        "label": group.get("label") or group_id,
        "role": role,
        "bbox": bbox,
        "candidate_point": {},
        "layout_zone": _layout_zone_for_two_stage(parent, group, bbox),
        "visual_order_key": [int(bbox.get("y") or 0), int(bbox.get("x") or 0)],
        "description": _description({"label": group.get("label"), "role": role}, operation),
        "possible_operation": operation,
        "child_evidence": child_evidence,
        "child_evidence_count": len(child_evidence),
        "source_parent_region_id": parent.get("region_id"),
        "source_parent_region_label": parent.get("label"),
        "source_section_id": parent.get("region_id"),
        "source_section_label": parent.get("label"),
        "source_section_containment_ratio": round(section_ratio, 4),
        "inside_source_section": section_ratio >= 0.85,
        "page_detail_source": "two_stage_subregion_group",
        "display_layer": "parent_region",
        "calibration_state": "page_detail_review_only",
        "pathgraph_candidate_review_state": "blocked_page_detail_review_only",
        "required_next_step": "review_before_pathgraph_promotion",
        "evidence": {
            "member_item_ids": child_ids,
            "source": group.get("source"),
            "bbox_policy": group.get("bbox_policy"),
            "parent_region_id": parent.get("region_id"),
        },
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "render_in_spatial_preview": True,
    }


def _region_from_two_stage_item(item: dict[str, Any], *, parent: dict[str, Any], index: int) -> dict[str, Any]:
    bbox = _dict(item.get("bbox"))
    if not bbox:
        return {}
    operation = _possible_operation(item)
    item_id = str(item.get("item_id") or f"two_stage_item_{index}")
    parent_bbox = _dict(parent.get("bbox"))
    section_ratio = _bbox_containment_ratio(bbox, parent_bbox) if parent_bbox else 0.0
    return {
        "region_no": index,
        "region_id": item_id,
        "source_item_id": item_id,
        "label": item.get("label") or item_id,
        "role": item.get("role") or "region",
        "bbox": bbox,
        "candidate_point": _dict(item.get("candidate_point") or item.get("click_point")),
        "layout_zone": _layout_zone_for_two_stage(parent, item, bbox),
        "visual_order_key": [int(bbox.get("y") or 0), int(bbox.get("x") or 0)],
        "description": _description(item, operation),
        "possible_operation": operation,
        "child_evidence": [],
        "child_evidence_count": 0,
        "source_parent_region_id": parent.get("region_id"),
        "source_parent_region_label": parent.get("label"),
        "source_section_id": parent.get("region_id"),
        "source_section_label": parent.get("label"),
        "source_section_containment_ratio": round(section_ratio, 4),
        "inside_source_section": section_ratio >= 0.85,
        "page_detail_source": "two_stage_numbered_item",
        "display_layer": "standalone_region",
        "calibration_state": "page_detail_review_only",
        "pathgraph_candidate_review_state": "blocked_page_detail_review_only",
        "required_next_step": "review_before_pathgraph_promotion",
        "evidence": {
            "number": item.get("number"),
            "parent_region_id": parent.get("region_id"),
        },
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "render_in_spatial_preview": True,
    }


def _child_evidence_from_two_stage_item(item: dict[str, Any]) -> dict[str, Any]:
    bbox = _dict(item.get("bbox"))
    return {
        "source_item_id": item.get("item_id"),
        "number": item.get("number"),
        "label": item.get("label") or item.get("text") or item.get("item_id"),
        "role": item.get("role"),
        "bbox": bbox,
        "display_layer": "child_evidence",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _layout_zone_for_two_stage(parent: dict[str, Any], item: dict[str, Any], bbox: dict[str, Any]) -> str:
    parent_id = str(parent.get("region_id") or "").casefold()
    parent_label = str(parent.get("label") or "").casefold()
    role = str(item.get("role") or "").casefold()
    if "browser_chrome" in parent_id:
        return "browser_chrome"
    if "top" in parent_id or "header" in parent_id or role.startswith("topbar"):
        return "top_search_and_filters"
    if "content_column" in parent_id or "primary" in parent_id or "main" in parent_id:
        return "middle_controls"
    if "left" in parent_id or "sidebar" in parent_id and "right" not in parent_id:
        return "left_results_list"
    if "right" in parent_id:
        return "right_detail_panel"
    if "floating" in parent_id or "scroll" in parent_label:
        return "right_detail_panel"
    return _layout_zone(item, bbox)


def _layout_zone_for_stage_parent(parent: dict[str, Any]) -> str:
    parent_id = str(parent.get("region_id") or "").casefold()
    parent_label = str(parent.get("label") or "").casefold()
    if "browser_chrome" in parent_id:
        return "browser_chrome"
    if "top" in parent_id or "header" in parent_id or "toolbar" in parent_id:
        return "top_search_and_filters"
    if "content_column" in parent_id or "primary" in parent_id or "main" in parent_id:
        return "middle_controls"
    if ("left" in parent_id or "sidebar" in parent_id) and "right" not in parent_id:
        return "left_results_list"
    if "right" in parent_id:
        return "right_detail_panel"
    if "floating" in parent_id or "scroll" in parent_label:
        return "right_detail_panel"
    return _layout_zone(parent, _dict(parent.get("bbox")))


def _regions_from_page_details(page_details: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    rows.extend(_list_of_dicts(page_details.get("grounding_candidates")))
    rows.extend(_list_of_dicts(page_details.get("review_only_regions")))
    rows.extend(_list_of_dicts(page_details.get("danger_zones")))
    regions = []
    for index, item in enumerate(rows, start=1):
        region = _region_from_page_detail_item(item, index)
        if region:
            regions.append(region)
    return regions


def _region_from_page_detail_item(item: dict[str, Any], index: int) -> dict[str, Any]:
    bbox = _dict(item.get("bbox") or item.get("rough_bbox_hint"))
    if not bbox:
        return {}
    operation = _possible_operation(item)
    return {
        "region_no": item.get("region_no") or index,
        "region_id": str(item.get("region_id") or f"learn_region_{index}"),
        "source_item_id": item.get("source_item_id") or item.get("item_id") or item.get("id"),
        "label": item.get("label") or item.get("source_item_id") or item.get("item_id") or "Region",
        "role": item.get("role") or "region",
        "bbox": bbox,
        "candidate_point": _dict(item.get("candidate_point") or item.get("click_point")),
        "layout_zone": _layout_zone(item, bbox),
        "visual_order_key": [int(bbox.get("y") or 0), int(bbox.get("x") or 0)],
        "description": _description(item, operation),
        "possible_operation": operation,
        "calibration_state": item.get("calibration_state") or "page_detail_review_only",
        "pathgraph_candidate_review_state": item.get("pathgraph_candidate_review_state") or "blocked_page_detail_review_only",
        "required_next_step": item.get("required_next_step") or "review_before_pathgraph_promotion",
        "evidence": {
            "decision": _dict(item.get("decision")),
            "source_evidence": item.get("source_evidence") if isinstance(item.get("source_evidence"), list) else [],
            "trace_path": item.get("trace_path"),
            "overlay_path": item.get("overlay_path"),
        },
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _regions_from_learning_draft(source: dict[str, Any]) -> list[dict[str, Any]]:
    draft = _dict(source.get("learning_draft"))
    regions = _list_of_dicts(draft.get("regions"))
    if not regions:
        interface = _dict(draft.get("interface_draft"))
        regions = _list_of_dicts(interface.get("regions"))
    if not regions:
        return []
    actions = _list_of_dicts(draft.get("action_templates"))
    if not actions:
        workflow = _dict(draft.get("workflow_draft"))
        actions = _list_of_dicts(workflow.get("action_templates"))
    action_by_region = {
        str(action.get("target_entity") or action.get("region_id") or ""): action
        for action in actions
        if str(action.get("target_entity") or action.get("region_id") or "")
    }
    output = []
    for index, item in enumerate(regions, start=1):
        region_id = str(item.get("region_id") or item.get("id") or f"learn_region_{index}")
        region = _region_from_learning_draft_item(item, index=index, action=action_by_region.get(region_id))
        if region:
            output.append(region)
    return output


def _region_from_learning_draft_item(item: dict[str, Any], *, index: int, action: dict[str, Any] | None) -> dict[str, Any]:
    bbox = _normalize_bbox(_dict(item.get("bbox") or item.get("rough_bbox_hint")))
    if not bbox:
        return {}
    merged = dict(item)
    if action:
        merged["semantic_action"] = action.get("semantic_action") or action.get("action_type")
        merged["action_label"] = action.get("label")
    operation = _possible_operation(merged)
    return {
        "region_no": item.get("region_no") or index,
        "region_id": str(item.get("region_id") or item.get("id") or f"learn_region_{index}"),
        "source_item_id": item.get("source_item_id") or item.get("item_id") or item.get("id"),
        "label": item.get("label") or item.get("region_id") or f"Region {index}",
        "role": item.get("role") or item.get("region_type") or "region",
        "bbox": bbox,
        "candidate_point": _dict(item.get("candidate_point") or item.get("click_point")),
        "layout_zone": _layout_zone(item, bbox),
        "visual_order_key": [int(bbox.get("y") or 0), int(bbox.get("x") or 0)],
        "description": _description(item, operation),
        "possible_operation": operation,
        "calibration_state": item.get("calibration_state") or "learning_draft_review_only",
        "pathgraph_candidate_review_state": item.get("pathgraph_candidate_review_state")
        or "blocked_learning_draft_review_only",
        "required_next_step": item.get("required_next_step") or "review_before_pathgraph_promotion",
        "evidence": {
            "source": "learning_draft.regions",
            "action_template_id": action.get("action_template_id") if action else None,
        },
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _region_from_precise_item(item: dict[str, Any]) -> dict[str, Any]:
    bbox = _dict(item.get("rough_bbox_hint"))
    if not bbox:
        return {}
    operation = _possible_operation(item)
    return {
        "region_no": item.get("region_no"),
        "region_id": f"learn_region_{item.get('region_no')}",
        "source_item_id": item.get("source_item_id"),
        "label": item.get("label") or item.get("source_item_id") or "Region",
        "role": item.get("role") or "region",
        "bbox": bbox,
        "candidate_point": _dict(item.get("candidate_point")),
        "layout_zone": _layout_zone(item, bbox),
        "visual_order_key": [int(bbox.get("y") or 0), int(bbox.get("x") or 0)],
        "description": _description(item, operation),
        "possible_operation": operation,
        "calibration_state": item.get("calibration_state"),
        "pathgraph_candidate_review_state": item.get("pathgraph_candidate_review_state"),
        "required_next_step": item.get("required_next_step"),
        "evidence": {
            "point_quality": item.get("point_quality"),
            "gate_safety": item.get("gate_safety"),
            "trace_path": item.get("trace_path"),
            "recognition_plan_trace_path": item.get("recognition_plan_trace_path"),
            "overlay_path": item.get("overlay_path"),
        },
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _possible_operation(item: dict[str, Any]) -> dict[str, Any]:
    semantic = str(item.get("semantic_action") or item.get("action_type") or "").strip().casefold()
    label = str(item.get("label") or "").casefold()
    role = str(item.get("role") or "").casefold()
    state = str(item.get("calibration_state") or "")
    pathgraph_state = str(item.get("pathgraph_candidate_review_state") or "")
    if semantic in {"fill_field", "input", "type_text"}:
        kind = "fill_field"
        label_text = str(item.get("action_label") or "Type or edit search/filter text")
    elif semantic in {"open_detail", "open_card", "click_card"}:
        kind = "open_detail"
        label_text = str(item.get("action_label") or "Open detail")
    elif semantic in {"submit_search", "search"}:
        kind = "submit_search"
        label_text = str(item.get("action_label") or "Run search")
    elif semantic in {"open_filter", "toggle_filter"}:
        kind = "open_filter"
        label_text = str(item.get("action_label") or "Open or change filter")
    elif "search bar" in label or "location" in label or role == "input":
        kind = "fill_field"
        label_text = "Type or edit search/filter text"
    elif "search button" in label:
        kind = "submit_search"
        label_text = "Run search"
    elif "job listing" in label or role == "card":
        kind = "open_detail"
        label_text = "Open job detail"
    elif "filter" in label or role in {"toggle", "menu_item"}:
        kind = "open_filter"
        label_text = "Open or change filter"
    elif "save search" in label:
        kind = "save_search"
        label_text = "Save current search"
    else:
        kind = "read_only"
        label_text = "Read or inspect region"
    if "pending_execute_dry_run_calibration" in state:
        readiness = "blocked_pending_calibration"
    elif "review_before_calibration" in state:
        readiness = "blocked_manual_review"
    elif pathgraph_state == "candidate_for_human_pathgraph_review":
        readiness = "ready_for_human_pathgraph_review"
    else:
        readiness = "review_required"
    return {
        "kind": kind,
        "label": label_text,
        "readiness": readiness,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _normalize_bbox(bbox: dict[str, Any]) -> dict[str, Any]:
    if not bbox:
        return {}
    width = bbox.get("w", bbox.get("width"))
    height = bbox.get("h", bbox.get("height"))
    return {
        "x": bbox.get("x", 0),
        "y": bbox.get("y", 0),
        "w": width if width is not None else 1,
        "h": height if height is not None else 1,
    }


def _layout_zone(item: dict[str, Any], bbox: dict[str, Any]) -> str:
    label = str(item.get("label") or "").casefold()
    x = int(bbox.get("x") or 0)
    y = int(bbox.get("y") or 0)
    if "detail" in label or (x >= 1120) or ("placeholder" in label and x >= 480):
        return "right_detail_panel"
    if "job listing" in label or "job count" in label or "save search" in label:
        return "left_results_list"
    if y < 320:
        return "top_search_and_filters"
    return "middle_controls"


def _description(item: dict[str, Any], operation: dict[str, Any]) -> str:
    parts = [
        str(item.get("label") or "Region"),
        f"role={item.get('role') or 'region'}",
        f"operation={operation.get('kind')}",
        f"readiness={operation.get('readiness')}",
    ]
    return " · ".join(parts)


def _layout_bounds(regions: list[dict[str, Any]]) -> dict[str, int]:
    boxes = [_dict(item.get("bbox")) for item in regions]
    if not boxes:
        return {"x": 0, "y": 0, "w": 1, "h": 1}
    min_x = min(int(box.get("x") or 0) for box in boxes)
    min_y = min(int(box.get("y") or 0) for box in boxes)
    max_x = max(int(box.get("x") or 0) + int(box.get("w") or 1) for box in boxes)
    max_y = max(int(box.get("y") or 0) + int(box.get("h") or 1) for box in boxes)
    return {"x": min_x, "y": min_y, "w": max(1, max_x - min_x), "h": max(1, max_y - min_y)}


def _bbox_containment_ratio(inner: dict[str, Any], outer: dict[str, Any]) -> float:
    try:
        inner_x = int(inner.get("x") or 0)
        inner_y = int(inner.get("y") or 0)
        inner_w = int(inner.get("w") or 0)
        inner_h = int(inner.get("h") or 0)
        outer_x = int(outer.get("x") or 0)
        outer_y = int(outer.get("y") or 0)
        outer_w = int(outer.get("w") or 0)
        outer_h = int(outer.get("h") or 0)
    except (TypeError, ValueError):
        return 0.0
    if inner_w <= 0 or inner_h <= 0 or outer_w <= 0 or outer_h <= 0:
        return 0.0
    x1 = max(inner_x, outer_x)
    y1 = max(inner_y, outer_y)
    x2 = min(inner_x + inner_w, outer_x + outer_w)
    y2 = min(inner_y + inner_h, outer_y + outer_h)
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    return intersection / max(1, inner_w * inner_h)


def _layout_sections(regions: list[dict[str, Any]], *, bounds: dict[str, int]) -> list[dict[str, Any]]:
    del bounds
    by_zone: dict[str, list[dict[str, Any]]] = {}
    for item in sorted(regions, key=lambda value: value.get("visual_order_key") or [0, 0]):
        by_zone.setdefault(str(item.get("layout_zone") or "other"), []).append(item)
    order = ["top_search_and_filters", "left_results_list", "right_detail_panel", "middle_controls", "other"]
    sections = []
    for zone in order:
        items = by_zone.get(zone) or []
        if not items:
            continue
        sections.append(
            {
                "section_id": zone,
                "label": zone.replace("_", " ").title(),
                "bbox": _layout_bounds(items),
                "region_count": len(items),
                "region_numbers": [item.get("region_no") for item in items],
                "possible_operations": sorted(
                    {str(_dict(item.get("possible_operation")).get("kind") or "read_only") for item in items}
                ),
                "operation_summary": _operation_summary(items),
                "operation_links": [_operation_link(item) for item in items],
                "regions": items,
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    return sections


def _operation_summary(items: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    kind_counts: dict[str, int] = {}
    readiness_counts: dict[str, int] = {}
    for item in items:
        operation = _dict(item.get("possible_operation"))
        kind = str(operation.get("kind") or "read_only")
        readiness = str(operation.get("readiness") or "review_required")
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        readiness_counts[readiness] = readiness_counts.get(readiness, 0) + 1
    return {
        "kind_counts": dict(sorted(kind_counts.items())),
        "readiness_counts": dict(sorted(readiness_counts.items())),
    }


def _operation_link(item: dict[str, Any]) -> dict[str, Any]:
    operation = _dict(item.get("possible_operation"))
    return {
        "region_no": item.get("region_no"),
        "region_id": item.get("region_id"),
        "label": item.get("label") or item.get("region_id") or "Region",
        "operation_kind": operation.get("kind") or "read_only",
        "operation_label": operation.get("label") or "Read or inspect region",
        "readiness": operation.get("readiness") or "review_required",
        "candidate_point": _dict(item.get("candidate_point")),
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _resolve_path(path: str | Path, root: Path) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = root / resolved
    return resolved.resolve()


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return str(path.resolve())


def _display_path(value: Any, *, root: Path) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return _relative_path(_resolve_path(text, root), root)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _source_ui_hierarchy(payload: dict[str, Any]) -> dict[str, Any]:
    for candidate in (
        payload.get("ui_hierarchy"),
        _dict(payload.get("learning_draft")).get("ui_hierarchy"),
        _dict(payload.get("fusion")).get("ui_hierarchy"),
    ):
        if isinstance(candidate, dict) and candidate.get("contract_version") == "ui_hierarchy_graph_v1":
            return candidate
    return {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a template-like page-detail candidate for Learning Mode demo.")
    parser.add_argument("--source", required=True, help="Learning draft source, pathgraph_candidate.json, or precise candidate JSON.")
    parser.add_argument("--out", required=True, help="Output directory.")
    parser.add_argument("--json", action="store_true", help="Print JSON.")
    args = parser.parse_args()
    build_learn_page_detail_candidate(source_path=args.source, out_dir=args.out, json_stdout=args.json)


if __name__ == "__main__":
    main()
