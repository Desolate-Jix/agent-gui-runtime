from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.learn.recognition.layout_graph import build_inventory_layout_graph
from app.learn.recognition.two_stage import build_two_stage_screen_understanding
from app.learn.recognition.trace_input import (
    observe_bundle_from_trace_result as _observe_bundle_from_trace_result,
    stage1_inventory_from_trace_result as _stage1_inventory_from_trace_result,
)


def _evaluate_ownership_golden(
    report: dict[str, Any],
    annotations: list[dict[str, Any]],
) -> dict[str, Any]:
    stage2 = report.get("stage2_numbering") if isinstance(report.get("stage2_numbering"), dict) else {}
    regions = {
        str(region.get("region_id") or ""): region
        for region in stage2.get("regions", [])
        if isinstance(region, dict)
    }
    checks: list[dict[str, Any]] = []
    for annotation in annotations:
        annotation_id = str(annotation.get("annotation_id") or "")
        region_id = str(annotation.get("region_id") or "")
        item_id = str(annotation.get("item_id") or "")
        expected_role = str(annotation.get("expected_owner_role") or "")
        region = regions.get(region_id)
        owner_group_id = ""
        actual_role = ""
        failure_category = ""
        if region is None:
            failure_category = "ownership_region_missing"
        else:
            audit = region.get("ownership_resolution") if isinstance(region.get("ownership_resolution"), dict) else {}
            owner_map = audit.get("source_item_owner_map") if isinstance(audit.get("source_item_owner_map"), dict) else {}
            owner_group_id = str(owner_map.get(item_id) or "")
            if not owner_group_id:
                failure_category = "ownership_item_missing"
            else:
                groups = {
                    str(group.get("group_id") or ""): group
                    for group in region.get("subregion_groups", [])
                    if isinstance(group, dict)
                }
                actual_role = str((groups.get(owner_group_id) or {}).get("role") or "")
                if actual_role != expected_role:
                    failure_category = "ownership_role_mismatch"
        passed = not failure_category
        checks.append(
            {
                "annotation_id": annotation_id,
                "region_id": region_id,
                "item_id": item_id,
                "expected_owner_role": expected_role,
                "actual_owner_role": actual_role or None,
                "actual_owner_group_id": owner_group_id or None,
                "passed": passed,
                "failure_category": failure_category or None,
            }
        )
    attempted = len(checks)
    passed = sum(1 for check in checks if check["passed"])
    return {
        "source": "human_curated",
        "scope": "fixed_ownership_holdout",
        "used_for_rule_tuning": False,
        "passed": passed,
        "attempted": attempted,
        "rate": round(passed / attempted, 4) if attempted else "not_covered",
        "checks": checks,
        "mismatches": [check for check in checks if not check["passed"]],
        "interpretation": "human-curated owner-role checks; not model accuracy or general UI reliability",
    }


def _load_ownership_golden_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    path_value = str(manifest.get("ownership_golden_manifest_path") or "").strip()
    expected_checksum = str(manifest.get("ownership_golden_manifest_sha256") or "").strip().casefold()
    if not path_value:
        return {
            "status": "not_configured",
            "annotation_count": 0,
            "annotations_by_case": {},
            "path": None,
        }
    path = _resolve(path_value)
    base = {
        "path": _relative(path),
        "expected_checksum": expected_checksum,
        "annotation_count": 0,
        "annotations_by_case": {},
    }
    if not path.exists():
        return {**base, "status": "invalid", "failure_category": "missing_ownership_golden_fixture"}
    actual_checksum = _sha256(path)
    if not expected_checksum or actual_checksum != expected_checksum:
        return {
            **base,
            "status": "invalid",
            "failure_category": "stale_ownership_golden_fixture",
            "actual_checksum": actual_checksum,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            **base,
            "status": "invalid",
            "failure_category": "invalid_ownership_golden_json",
            "error": str(exc),
            "actual_checksum": actual_checksum,
        }
    if payload.get("contract_version") != "general_ui_ownership_golden_holdout_v1":
        return {
            **base,
            "status": "invalid",
            "failure_category": "invalid_ownership_golden_contract",
            "actual_checksum": actual_checksum,
        }
    annotations = payload.get("annotations") if isinstance(payload.get("annotations"), list) else []
    required = {"annotation_id", "case_id", "region_id", "item_id", "expected_owner_role"}
    annotations_by_case: dict[str, list[dict[str, Any]]] = {}
    seen_ids: set[str] = set()
    for annotation in annotations:
        if not isinstance(annotation, dict) or not required.issubset(annotation):
            return {
                **base,
                "status": "invalid",
                "failure_category": "invalid_ownership_golden_annotation",
                "actual_checksum": actual_checksum,
            }
        annotation_id = str(annotation.get("annotation_id") or "")
        if not annotation_id or annotation_id in seen_ids or str(annotation.get("source") or "human_curated") != "human_curated":
            return {
                **base,
                "status": "invalid",
                "failure_category": "invalid_ownership_golden_annotation",
                "actual_checksum": actual_checksum,
            }
        seen_ids.add(annotation_id)
        case_id = str(annotation.get("case_id") or "")
        annotations_by_case.setdefault(case_id, []).append(dict(annotation))
    return {
        **base,
        "status": "valid",
        "actual_checksum": actual_checksum,
        "annotation_count": len(annotations),
        "annotations_by_case": annotations_by_case,
        "source": "human_curated",
        "used_for_rule_tuning": False,
    }


def _summarize_ownership_golden(
    case_results: list[dict[str, Any]],
    fixture: dict[str, Any],
) -> dict[str, Any]:
    annotated_cases = [
        result
        for result in case_results
        if isinstance(result.get("ownership_golden"), dict)
        and str(result["ownership_golden"].get("source") or "human_curated") == "human_curated"
        and int(result["ownership_golden"].get("attempted") or 0) > 0
    ]
    valid_results = [result["ownership_golden"] for result in annotated_cases]
    attempted = sum(int(result.get("attempted") or 0) for result in valid_results)
    passed = sum(int(result.get("passed") or 0) for result in valid_results)
    annotated_families = sorted({str(result.get("app_family") or "unknown") for result in annotated_cases})
    annotation_threshold = 30
    family_threshold = 8
    sample_insufficient = attempted < annotation_threshold
    family_insufficient = len(annotated_families) < family_threshold
    if not attempted:
        reliability_status = "not_covered"
    elif sample_insufficient and family_insufficient:
        reliability_status = "insufficient_sample_size_and_application_diversity"
    elif sample_insufficient:
        reliability_status = "insufficient_sample_size"
    elif family_insufficient:
        reliability_status = "insufficient_application_diversity"
    else:
        reliability_status = "minimum_thresholds_met"
    mismatches = [
        mismatch
        for result in valid_results
        for mismatch in result.get("mismatches", [])
        if isinstance(mismatch, dict)
    ]
    return {
        "fixture_status": str(fixture.get("status") or "not_configured"),
        "fixture_path": fixture.get("path"),
        "source": "human_curated",
        "used_for_rule_tuning": False,
        "passed": passed,
        "attempted": attempted,
        "rate": round(passed / attempted, 4) if attempted else "not_covered",
        "denominator": "human-curated owner-role annotations on fixed recorded surfaces",
        "annotated_case_count": len(annotated_cases),
        "annotated_application_family_count": len(annotated_families),
        "annotated_application_families": annotated_families,
        "coverage_status": "fixed_human_owner_role_holdout" if attempted else "not_covered",
        "reliability_status": reliability_status,
        "annotation_reliability_threshold": annotation_threshold,
        "application_family_reliability_threshold": family_threshold,
        "mismatches": mismatches,
        "interpretation": "human-curated owner-role holdout; not model accuracy or general UI reliability",
    }


def _write_case_review_sheet(
    *,
    case_id: str,
    report: dict[str, Any],
    source_image_path: Path,
    case_dir: Path,
) -> dict[str, Any]:
    stage1 = report.get("stage1_region_localization") if isinstance(report.get("stage1_region_localization"), dict) else {}
    fusion = report.get("fusion") if isinstance(report.get("fusion"), dict) else {}
    stage1_path = _resolve(str(stage1.get("overlay_path") or ""))
    final_path = _resolve(str(fusion.get("compiled_overlay_path") or ""))
    evidence_paths = {
        "original": source_image_path.resolve(),
        "stage1": stage1_path,
        "final": final_path,
    }
    missing = [name for name, path in evidence_paths.items() if not path.exists()]
    if missing:
        return {
            "status": "invalid",
            "failure_category": "review_evidence_missing",
            "missing_evidence": missing,
            "evidence_paths": {name: _relative(path) for name, path in evidence_paths.items()},
        }
    images: dict[str, Image.Image] = {}
    try:
        for name, path in evidence_paths.items():
            with Image.open(path) as image:
                images[name] = image.convert("RGB")
    except OSError as exc:
        return {
            "status": "invalid",
            "failure_category": "review_evidence_unreadable",
            "error": str(exc),
            "evidence_paths": {name: _relative(path) for name, path in evidence_paths.items()},
        }
    dimensions = {name: image.size for name, image in images.items()}
    if len(set(dimensions.values())) != 1:
        return {
            "status": "invalid",
            "failure_category": "review_evidence_dimension_mismatch",
            "same_source_dimensions": False,
            "dimensions": {name: {"width": size[0], "height": size[1]} for name, size in dimensions.items()},
            "evidence_paths": {name: _relative(path) for name, path in evidence_paths.items()},
        }

    panel_width = 360
    panel_height = 260
    label_height = 28
    gap = 12
    sheet = Image.new("RGB", (panel_width * 4 + gap * 5, panel_height + label_height + gap * 2), "white")
    draw = ImageDraw.Draw(sheet)
    for index, name in enumerate(("original", "stage1", "final")):
        x = gap + index * (panel_width + gap)
        draw.text((x, gap), name.upper(), fill="black")
        fitted = _fit_review_panel(images[name], width=panel_width, height=panel_height)
        sheet.paste(fitted, (x, gap + label_height))

    hierarchy = report.get("ui_hierarchy") if isinstance(report.get("ui_hierarchy"), dict) else {}
    summary = hierarchy.get("summary") if isinstance(hierarchy.get("summary"), dict) else {}
    level_counts = summary.get("level_counts") if isinstance(summary.get("level_counts"), dict) else {}
    validation = hierarchy.get("validation") if isinstance(hierarchy.get("validation"), dict) else {}
    hierarchy_counts = {
        "nodes": int(summary.get("node_count") or len(hierarchy.get("nodes") or [])),
        "structure_regions": int(summary.get("structure_region_count") or level_counts.get("structure_region") or 0),
        "sections": int(summary.get("section_count") or level_counts.get("section") or 0),
        "component_groups": int(summary.get("component_group_count") or level_counts.get("component_group") or 0),
        "components": int(summary.get("component_count") or level_counts.get("component") or 0),
        "content_nodes": int(summary.get("content_node_count") or summary.get("content_count") or level_counts.get("content") or 0),
    }
    hierarchy_x = gap + 3 * (panel_width + gap)
    draw.text((hierarchy_x, gap), "UI HIERARCHY", fill="black")
    hierarchy_lines = [
        f"case: {case_id}",
        f"contract: {hierarchy.get('contract_version') or 'missing'}",
        f"nodes: {hierarchy_counts['nodes']}",
        f"structure regions: {hierarchy_counts['structure_regions']}",
        f"sections: {hierarchy_counts['sections']}",
        f"component groups: {hierarchy_counts['component_groups']}",
        f"components: {hierarchy_counts['components']}",
        f"content nodes: {hierarchy_counts['content_nodes']}",
        f"validation: {validation.get('status', 'not_available')}",
        f"orphans: {validation.get('orphan_node_count', 0)}",
        f"duplicate owners: {validation.get('duplicate_primary_owner_count', 0)}",
        f"outside parent: {validation.get('child_outside_parent_count', 0)}",
        "display only / no Execute",
    ]
    for row, line in enumerate(hierarchy_lines):
        draw.text((hierarchy_x, gap + label_height + row * 18), line, fill="black")

    case_dir.mkdir(parents=True, exist_ok=True)
    review_sheet_path = case_dir / "review_sheet.png"
    sheet.save(review_sheet_path)
    return {
        "status": "available",
        "same_source_dimensions": True,
        "panel_count": 4,
        "review_sheet_path": _relative(review_sheet_path),
        "hierarchy_counts": hierarchy_counts,
        "evidence_paths": {name: _relative(path) for name, path in evidence_paths.items()},
        "source_dimensions": {"width": dimensions["original"][0], "height": dimensions["original"][1]},
        "interpretation": "original / Stage1 / final / hierarchy review sheet; display-only evidence",
    }


def _fit_review_panel(image: Image.Image, *, width: int, height: int) -> Image.Image:
    fitted = image.copy()
    fitted.thumbnail((width, height), Image.Resampling.LANCZOS)
    panel = Image.new("RGB", (width, height), "#f3f4f6")
    panel.paste(fitted, ((width - fitted.width) // 2, (height - fitted.height) // 2))
    return panel


def evaluate_case_report(
    case: dict[str, Any],
    report: dict[str, Any],
    *,
    check_artifact_files: bool = False,
    ownership_annotations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    expectations = case.get("expectations") if isinstance(case.get("expectations"), dict) else {}
    expected_outcome = str(case.get("expected_outcome") or "supported")
    gate = report.get("stage1_gate") if isinstance(report.get("stage1_gate"), dict) else {}
    stage1 = report.get("stage1_region_localization") if isinstance(report.get("stage1_region_localization"), dict) else {}
    stage2 = report.get("stage2_numbering") if isinstance(report.get("stage2_numbering"), dict) else {}
    hierarchy = report.get("ui_hierarchy") if isinstance(report.get("ui_hierarchy"), dict) else {}
    validation = hierarchy.get("validation") if isinstance(hierarchy.get("validation"), dict) else {}
    draft = report.get("learning_draft") if isinstance(report.get("learning_draft"), dict) else {}
    draft_safety = draft.get("safety") if isinstance(draft.get("safety"), dict) else {}
    fusion = report.get("fusion") if isinstance(report.get("fusion"), dict) else {}
    interface_classification = (
        report.get("interface_classification")
        if isinstance(report.get("interface_classification"), dict)
        else {}
    )
    class_rule_profile = (
        report.get("class_rule_profile") if isinstance(report.get("class_rule_profile"), dict) else {}
    )
    regions = [region for region in stage2.get("regions", []) if isinstance(region, dict)]
    structure_type_counts: dict[str, int] = {}
    structure_regions_by_type: dict[str, list[dict[str, Any]]] = {}
    for region in stage1.get("regions", []) if isinstance(stage1.get("regions"), list) else []:
        if not isinstance(region, dict):
            continue
        region_type = _structure_type(region)
        structure_type_counts[region_type] = structure_type_counts.get(region_type, 0) + 1
        structure_regions_by_type.setdefault(region_type, []).append(region)
    groups = [
        group
        for region in regions
        for group in region.get("subregion_groups", [])
        if isinstance(group, dict)
    ]
    group_role_counts: dict[str, int] = {}
    for group in groups:
        role = str(group.get("role") or "")
        group_role_counts[role] = group_role_counts.get(role, 0) + 1
    item_role_counts: dict[str, int] = {}
    for region in regions:
        for item in region.get("numbered_items", []) if isinstance(region.get("numbered_items"), list) else []:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "")
            item_role_counts[role] = item_role_counts.get(role, 0) + 1
    labels = "\n".join(
        str(node.get("label") or "").casefold()
        for node in hierarchy.get("nodes", [])
        if isinstance(node, dict)
    )
    assertions: list[dict[str, Any]] = []

    def add(assertion_id: str, passed: bool, expected: Any, actual: Any, category: str) -> None:
        assertions.append(
            {
                "assertion_id": assertion_id,
                "passed": bool(passed),
                "expected": expected,
                "actual": actual,
                "category": category,
            }
        )

    expected_gate = str(
        expectations.get("expected_stage1_gate_status")
        or ("passed" if expected_outcome == "supported" else "blocked_before_stage2_numbering")
    )
    add("stage1_gate_status", str(gate.get("status") or "") == expected_gate, expected_gate, gate.get("status"), "stage1")
    expected_hierarchy_status = str(expectations.get("expected_hierarchy_status") or "").strip()
    if expected_hierarchy_status:
        actual_hierarchy_status = str(validation.get("status") or "").strip()
        add(
            "hierarchy_expected_status",
            actual_hierarchy_status == expected_hierarchy_status,
            expected_hierarchy_status,
            actual_hierarchy_status or "missing",
            "hierarchy",
        )
    expected_interface_category = str(expectations.get("expected_interface_category") or "").strip()
    if expected_interface_category:
        actual_interface_category = str(interface_classification.get("category") or "").strip()
        add(
            "expected_interface_category",
            actual_interface_category == expected_interface_category,
            expected_interface_category,
            actual_interface_category or "missing",
            "class_profile",
        )
    expected_class_strategy = str(expectations.get("expected_class_strategy") or "").strip()
    if expected_class_strategy:
        actual_class_strategy = str(class_rule_profile.get("primary_content_strategy") or "").strip()
        add(
            "expected_class_strategy",
            actual_class_strategy == expected_class_strategy,
            expected_class_strategy,
            actual_class_strategy or "missing",
            "class_profile",
        )
    add(
        "class_profile_cannot_override_safety",
        interface_classification.get("safety_policy_override_allowed") is False,
        False,
        interface_classification.get("safety_policy_override_allowed", "missing"),
        "safety",
    )
    if "expected_min_clipped_nodes" in expectations:
        minimum_clipped = int(expectations.get("expected_min_clipped_nodes") or 0)
        actual_clipped = int(validation.get("clipped_node_count") or 0)
        add(
            "hierarchy_expected_min_clipped_nodes",
            actual_clipped >= minimum_clipped,
            {"min": minimum_clipped},
            actual_clipped,
            "hierarchy",
        )
    if expected_outcome == "supported":
        add("stage2_executed", stage2.get("skipped") is not True, False, bool(stage2.get("skipped")), "stage2")
        min_regions = int(expectations.get("min_structure_regions") or 1)
        actual_regions = int(stage1.get("localized_region_count") or len(stage1.get("regions") or []))
        add("structure_region_count", actual_regions >= min_regions, {"min": min_regions}, actual_regions, "stage1")
        for required_type in expectations.get("required_structure_types") or []:
            region_type = str(required_type)
            actual = int(structure_type_counts.get(region_type, 0))
            add(f"required_structure_type:{region_type}", actual > 0, {"min": 1}, actual, "stage1")
        shared_lane_types = [str(value) for value in expectations.get("shared_vertical_lane_types") or []]
        if shared_lane_types:
            tolerance = int(expectations.get("shared_vertical_lane_tolerance_px") or 2)
            actual_bounds: dict[str, dict[str, int] | str] = {}
            for region_type in shared_lane_types:
                candidates = structure_regions_by_type.get(region_type, [])
                bbox = _bbox(candidates[0].get("bbox")) if candidates else None
                actual_bounds[region_type] = (
                    {"top": bbox["y"], "bottom": bbox["y"] + bbox["h"]} if bbox else "missing"
                )
            numeric_bounds = [value for value in actual_bounds.values() if isinstance(value, dict)]
            lane_passed = (
                len(numeric_bounds) == len(shared_lane_types)
                and max(value["top"] for value in numeric_bounds) - min(value["top"] for value in numeric_bounds)
                <= tolerance
                and max(value["bottom"] for value in numeric_bounds) - min(value["bottom"] for value in numeric_bounds)
                <= tolerance
            )
            add(
                "shared_vertical_lane_boundaries",
                lane_passed,
                {"types": shared_lane_types, "max_boundary_delta_px": tolerance},
                actual_bounds,
                "stage1",
            )
        horizontal_lane_types = [str(value) for value in expectations.get("horizontal_lane_tiling_types") or []]
        if horizontal_lane_types:
            tolerance = int(expectations.get("horizontal_lane_tolerance_px") or 2)
            expected_width = int(expectations.get("expected_screen_width") or 0)
            lane_boxes: list[tuple[str, dict[str, int]]] = []
            missing_types: list[str] = []
            for region_type in horizontal_lane_types:
                candidates = structure_regions_by_type.get(region_type, [])
                bbox = _bbox(candidates[0].get("bbox")) if candidates else None
                if bbox:
                    lane_boxes.append((region_type, bbox))
                else:
                    missing_types.append(region_type)
            gaps = [
                right[1]["x"] - (left[1]["x"] + left[1]["w"])
                for left, right in zip(lane_boxes, lane_boxes[1:])
            ]
            left_edge = lane_boxes[0][1]["x"] if lane_boxes else None
            right_edge = lane_boxes[-1][1]["x"] + lane_boxes[-1][1]["w"] if lane_boxes else None
            tiling_passed = (
                not missing_types
                and len(lane_boxes) == len(horizontal_lane_types)
                and left_edge is not None
                and abs(left_edge) <= tolerance
                and (expected_width <= 0 or (right_edge is not None and abs(right_edge - expected_width) <= tolerance))
                and all(abs(gap) <= tolerance for gap in gaps)
            )
            add(
                "horizontal_lane_tiling",
                tiling_passed,
                {
                    "types": horizontal_lane_types,
                    "left_edge": 0,
                    "right_edge": expected_width or "screen_right",
                    "max_gap_or_overlap_px": tolerance,
                },
                {
                    "left_edge": left_edge,
                    "right_edge": right_edge,
                    "adjacent_deltas": gaps,
                    "missing_types": missing_types,
                },
                "stage1",
            )
        add(
            "hierarchy_contract",
            hierarchy.get("contract_version") == "ui_hierarchy_graph_v1",
            "ui_hierarchy_graph_v1",
            hierarchy.get("contract_version"),
            "hierarchy",
        )
        min_nodes = int(expectations.get("min_hierarchy_nodes") or 2)
        node_count = len([node for node in hierarchy.get("nodes", []) if isinstance(node, dict)])
        add("hierarchy_node_count", node_count >= min_nodes, {"min": min_nodes}, node_count, "hierarchy")
        for field in (
            "orphan_node_count",
            "duplicate_primary_owner_count",
            "child_outside_parent_count",
            "clipped_node_count",
            "cycle_node_count",
            "unreachable_from_root_count",
        ):
            actual = int(validation.get(field) or 0)
            add(field, actual == 0, 0, actual, "hierarchy")
        add(
            "learning_draft_contract",
            draft.get("contract_version") == "learning_template_draft_v1" and bool(draft.get("regions")),
            "learning_template_draft_v1 with regions",
            {"contract_version": draft.get("contract_version"), "region_count": len(draft.get("regions") or [])},
            "draft",
        )
        for role, minimum in (expectations.get("required_group_roles") or {}).items():
            actual = int(group_role_counts.get(str(role), 0))
            add(f"required_group_role:{role}", actual >= int(minimum), {"min": int(minimum)}, actual, "semantics")
        for role in expectations.get("forbidden_group_roles") or []:
            actual = int(group_role_counts.get(str(role), 0))
            add(f"forbidden_group_role:{role}", actual == 0, 0, actual, "anti_pollution")
        for role in expectations.get("forbidden_item_roles") or []:
            actual = int(item_role_counts.get(str(role), 0))
            add(f"forbidden_item_role:{role}", actual == 0, 0, actual, "anti_pollution")
        for token in expectations.get("forbidden_label_tokens") or []:
            token_text = str(token).casefold()
            add(
                f"forbidden_label_token:{token_text}",
                token_text not in labels,
                "absent",
                "present" if token_text in labels else "absent",
                "anti_pollution",
            )

    overlay_path = str(fusion.get("compiled_overlay_path") or "")
    overlay_available = bool(overlay_path) and (not check_artifact_files or _resolve(overlay_path).exists())
    add("compiled_overlay_available", overlay_available, True, overlay_path or "missing", "artifact")
    safety_pass = (
        draft_safety.get("execute_binding_enabled") is False
        and draft_safety.get("artifact_is_authorization") is False
        and draft_safety.get("runtime_pathgraph_promotion") is False
    )
    add(
        "draft_safety",
        safety_pass,
        {"execute_binding_enabled": False, "artifact_is_authorization": False, "runtime_pathgraph_promotion": False},
        draft_safety,
        "safety",
    )
    ownership_golden = _evaluate_ownership_golden(report, list(ownership_annotations or []))
    if ownership_golden["attempted"]:
        add(
            "ownership_golden_holdout",
            ownership_golden["passed"] == ownership_golden["attempted"],
            {"passed": ownership_golden["attempted"], "attempted": ownership_golden["attempted"]},
            {"passed": ownership_golden["passed"], "attempted": ownership_golden["attempted"]},
            "ownership_holdout",
        )
    all_passed = all(assertion["passed"] for assertion in assertions)
    known_limitation_reproduced = expected_outcome != "supported" and all_passed
    case_outcome = (
        "supported_pass"
        if expected_outcome == "supported" and all_passed
        else (
            "supported_fail"
            if expected_outcome == "supported"
            else ("known_limitation_reproduced" if known_limitation_reproduced else "known_limitation_drifted")
        )
    )
    return {
        "case_id": str(case.get("case_id") or ""),
        "app_family": str(case.get("app_family") or "unknown"),
        "surface_type": str(case.get("surface_type") or "unknown"),
        "expected_outcome": expected_outcome,
        "case_outcome": case_outcome,
        "capability_pass": expected_outcome == "supported" and all_passed,
        "safety_pass": safety_pass,
        "known_limitation_reproduced": known_limitation_reproduced,
        "group_role_counts": group_role_counts,
        "item_role_counts": item_role_counts,
        "structure_type_counts": structure_type_counts,
        "hierarchy_summary": hierarchy.get("summary") if isinstance(hierarchy.get("summary"), dict) else {},
        "hierarchy_validation": validation,
        "interface_classification": interface_classification,
        "class_rule_profile": class_rule_profile,
        "ownership_golden": ownership_golden,
        "assertions": assertions,
        "failed_assertions": [item for item in assertions if not item["passed"]],
        "overlay_path": overlay_path,
    }


def summarize_metrics(cases: list[dict[str, Any]], invalid_cases: list[dict[str, Any]]) -> dict[str, Any]:
    supported = [
        case
        for case in cases
        if case.get("expected_outcome") == "supported" or str(case.get("case_outcome") or "").startswith("supported_")
    ]
    supported_passed = sum(1 for case in supported if case.get("capability_pass") is True)
    families = sorted({str(case.get("app_family") or "unknown") for case in cases})
    supported_families = sorted({str(case.get("app_family") or "unknown") for case in supported})
    attempted = len(supported)
    categories: dict[str, dict[str, Any]] = {}
    for case in cases:
        classification = (
            case.get("interface_classification")
            if isinstance(case.get("interface_classification"), dict)
            else {}
        )
        if classification.get("source") != "model_output" or classification.get("status") != "accepted":
            continue
        category = str(classification.get("category") or "generic")
        entry = categories.setdefault(
            category,
            {
                "case_ids": [],
                "application_families": set(),
                "recursive_state_case_count": 0,
            },
        )
        entry["case_ids"].append(str(case.get("case_id") or ""))
        entry["application_families"].add(str(case.get("app_family") or "unknown"))
        entry["recursive_state_case_count"] += int(case.get("repeated_application_state") is True)
    category_summaries: dict[str, dict[str, Any]] = {}
    for category, entry in sorted(categories.items()):
        case_count = len(entry["case_ids"])
        application_families_for_category = sorted(entry["application_families"])
        family_count = len(application_families_for_category)
        sample_insufficient = case_count < 5
        family_insufficient = family_count < 2
        if sample_insufficient and family_insufficient:
            reliability_status = "insufficient_sample_size_and_application_diversity"
        elif sample_insufficient:
            reliability_status = "insufficient_sample_size"
        elif family_insufficient:
            reliability_status = "insufficient_application_diversity"
        else:
            reliability_status = "minimum_recursive_thresholds_met"
        category_summaries[category] = {
            "case_count": case_count,
            "case_ids": entry["case_ids"],
            "application_family_count": family_count,
            "application_families": application_families_for_category,
            "recursive_state_case_count": entry["recursive_state_case_count"],
            "reliability_status": reliability_status,
            "minimum_case_threshold": 5,
            "minimum_application_family_threshold": 2,
            "interpretation": "model-selected class profile coverage on fixed recorded surfaces; not class reliability",
        }
    return {
        "case_count": len(cases) + len(invalid_cases),
        "valid_case_count": len(cases),
        "application_family_count": len(families),
        "application_families": families,
        "supported_application_family_count": len(supported_families),
        "supported_application_families": supported_families,
        "coverage_status": "fixed_recorded_surface_coverage",
        "reliability_status": (
            "minimum_diversity_reached" if len(supported_families) >= 8 else "insufficient_application_diversity"
        ),
        "reliability_family_threshold": 8,
        "supported_capability": {
            "passed": supported_passed,
            "attempted": attempted,
            "rate": round(supported_passed / attempted, 4) if attempted else "not_covered",
            "interpretation": "fixed recorded-surface hierarchy benchmark only; not model accuracy or general UI reliability",
        },
        "known_limitation_count": sum(1 for case in cases if case.get("case_outcome") == "known_limitation_reproduced"),
        "invalid_fixture_count": len(invalid_cases),
        "repeated_state_case_count": sum(1 for case in cases if case.get("repeated_application_state") is True),
        "class_profile_coverage": {
            "model_selected_case_count": sum(item["case_count"] for item in category_summaries.values()),
            "category_count": len(category_summaries),
            "categories": category_summaries,
            "interpretation": (
                "Model-selected class profiles are counted separately by case and application family; repeated states "
                "do not establish cross-application class reliability."
            ),
        },
        "interpretation": (
            "Case count and application-family count are separate. Repeated states test regression stability and do not "
            "increase application-family coverage. No aggregate system success rate is reported."
        ),
    }


def run_benchmark(*, manifest_path: str | Path, out_dir: str | Path) -> dict[str, Any]:
    manifest_file = _resolve(manifest_path)
    out = _resolve(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8-sig"))
    ownership_golden_fixture = _load_ownership_golden_manifest(manifest)
    ownership_annotations_by_case = (
        ownership_golden_fixture.get("annotations_by_case")
        if ownership_golden_fixture.get("status") == "valid"
        and isinstance(ownership_golden_fixture.get("annotations_by_case"), dict)
        else {}
    )
    cases = [case for case in manifest.get("cases", []) if isinstance(case, dict)]
    results: list[dict[str, Any]] = []
    invalid_cases: list[dict[str, Any]] = []
    review_evidence_failures: list[dict[str, Any]] = []
    for case in cases:
        case_id = str(case.get("case_id") or "unknown_case")
        trace_path = _resolve(str(case.get("trace_path") or ""))
        image_path = _resolve(str(case.get("screenshot_path") or ""))
        fixture_error = _fixture_error(case, trace_path=trace_path, image_path=image_path)
        if fixture_error:
            invalid_cases.append(fixture_error)
            continue
        case_dir = out / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        report = _build_case_report(trace_path=trace_path, image_path=image_path)
        report_path = case_dir / "two_stage_report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        result = evaluate_case_report(
            case,
            report,
            check_artifact_files=True,
            ownership_annotations=list(ownership_annotations_by_case.get(case_id) or []),
        )
        result["trace_path"] = _relative(trace_path)
        result["screenshot_path"] = _relative(image_path)
        result["screenshot_sha256"] = _sha256(image_path)
        result["two_stage_report_path"] = _relative(report_path)
        result["repeated_application_state"] = bool(case.get("repeated_application_state"))
        review_evidence = _write_case_review_sheet(
            case_id=case_id,
            report=report,
            source_image_path=image_path,
            case_dir=case_dir,
        )
        result["review_evidence"] = review_evidence
        if review_evidence.get("status") != "available":
            review_evidence_failures.append(
                {
                    "case_id": case_id,
                    **review_evidence,
                }
            )
        results.append(result)
    summary = summarize_metrics(results, invalid_cases)
    ownership_golden_summary = _summarize_ownership_golden(results, ownership_golden_fixture)
    review_evidence_summary = {
        "available": sum(1 for result in results if (result.get("review_evidence") or {}).get("status") == "available"),
        "invalid": len(review_evidence_failures),
        "required_panels": ["original", "stage1", "final", "ui_hierarchy"],
        "interpretation": "same-size review evidence generated from each fixed source; not recognition reliability",
    }
    payload = {
        "contract_version": "general_ui_recognition_benchmark_report_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_path": _relative(manifest_file),
        "summary": summary,
        "ownership_golden_holdout": ownership_golden_summary,
        "review_evidence_summary": review_evidence_summary,
        "ownership_golden_fixture": {
            key: value
            for key, value in ownership_golden_fixture.items()
            if key != "annotations_by_case"
        },
        "cases": results,
        "invalid_cases": invalid_cases,
        "failure_cases": [case for case in results if case.get("case_outcome") == "supported_fail"],
        "known_limitations": [case for case in results if case.get("case_outcome") != "supported_pass" and case.get("expected_outcome") != "supported"],
        "fixture_validity_failures": review_evidence_failures + (
            []
            if ownership_golden_fixture.get("status") in {"valid", "not_configured"}
            else [
                {
                    key: value
                    for key, value in ownership_golden_fixture.items()
                    if key != "annotations_by_case"
                }
            ]
        ),
        "safety": _runner_safety_audit(),
        "interpretation": (
            "Offline fixed-trace and fixed-screenshot parser/OCR/heuristic benchmark. It does not measure model accuracy, "
            "live GUI execution, point grounding, or general UI reliability."
        ),
    }
    report_path = out / "general_ui_recognition_benchmark_report.json"
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    payload["report_path"] = _relative(report_path)
    return payload


def _build_case_report(*, trace_path: Path, image_path: Path) -> dict[str, Any]:
    trace = json.loads(trace_path.read_text(encoding="utf-8-sig"))
    result = trace.get("result") if isinstance(trace.get("result"), dict) else trace
    bundle = _observe_bundle_from_trace_result(result, trace_path=trace_path)
    bundle["image_path"] = str(image_path)
    bundle["source_image_path"] = str(image_path)
    with Image.open(image_path) as image:
        bundle["screen_size"] = {"width": int(image.width), "height": int(image.height)}
        bundle["image_size"] = {"width": int(image.width), "height": int(image.height)}
    inventory = _stage1_inventory_from_trace_result(result)
    layout_graph = build_inventory_layout_graph(inventory, screen_size=bundle.get("screen_size"))
    report = build_two_stage_screen_understanding(
        bundle=bundle,
        screen_inventory=inventory,
        layout_graph=layout_graph,
        require_stage1_gate=True,
        enable_ocr_content_recovery=True,
    )
    report["source_trace_path"] = _relative(trace_path)
    report["source_image_path"] = _relative(image_path)
    report["screen_inventory_count"] = len(inventory)
    return report


def _fixture_error(case: dict[str, Any], *, trace_path: Path, image_path: Path) -> dict[str, Any] | None:
    case_id = str(case.get("case_id") or "unknown_case")
    if not trace_path.exists() or not image_path.exists():
        return {
            "case_id": case_id,
            "failure_category": "missing_fixture",
            "trace_path": _relative(trace_path),
            "screenshot_path": _relative(image_path),
        }
    expected = str(case.get("screenshot_sha256") or "").casefold()
    expected_trace = str(case.get("trace_sha256") or "").casefold()
    actual_trace = _sha256(trace_path)
    if not expected_trace or expected_trace != actual_trace:
        return {
            "case_id": case_id,
            "failure_category": "stale_trace_fixture",
            "expected_trace_checksum": expected_trace,
            "actual_trace_checksum": actual_trace,
            "trace_path": _relative(trace_path),
        }
    actual = _sha256(image_path)
    if not expected or expected != actual:
        return {
            "case_id": case_id,
            "failure_category": "stale_fixture",
            "expected_checksum": expected,
            "actual_checksum": actual,
            "screenshot_path": _relative(image_path),
        }
    return None


def _runner_safety_audit() -> dict[str, Any]:
    source_path = Path(__file__).resolve()
    tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
    forbidden_prefixes = (
        "app.api.action",
        "app.operation",
        "app.vision_protocol.executor_adapter",
        "pyautogui",
        "pynput",
    )
    direct_forbidden_imports = sorted(
        module
        for module in imported_modules
        if any(module == prefix or module.startswith(f"{prefix}.") for prefix in forbidden_prefixes)
    )
    return {
        "runner_mode": "offline_fixed_artifact_replay",
        "runtime_action_trace_covered": False,
        "runtime_measured_side_effect_counts": "not_covered",
        "counter_evidence_status": "declared_by_offline_runner_design_not_runtime_measured",
        "declared_side_effect_counts": {
            "model_calls": 0,
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
        },
        "execute_binding_enabled": False,
        "runtime_pathgraph_promotion": False,
        "static_source_audit": {
            "passed": not direct_forbidden_imports,
            "audited_script": _relative(source_path),
            "direct_forbidden_imports": direct_forbidden_imports,
            "interpretation": (
                "Direct-import audit of the offline benchmark runner only; this is not runtime action-trace evidence."
            ),
        },
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _structure_type(region: dict[str, Any]) -> str:
    value = " ".join(
        str(region.get(key) or "") for key in ("region_id", "zone_id", "label", "region_type")
    ).casefold()
    if any(token in value for token in ("left_sidebar", "left sidebar", "left_nav", "left navigation")):
        return "left_sidebar"
    if any(token in value for token in ("right_sidebar", "right sidebar", "right_nav", "right navigation")):
        return "right_sidebar"
    if any(
        token in value
        for token in ("top_bar", "top/header", "page_header", "header area", "browser_chrome", "browser chrome")
    ):
        return "top_bar"
    if any(token in value for token in ("bottom_bar", "bottom bar", "footer")):
        return "bottom_bar"
    if any(token in value for token in ("main_content", "main content", "primary_area", "primary area")):
        return "main_content"
    if "overlay" in value or "modal" in value:
        return "overlay"
    return "other"


def _bbox(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    try:
        bbox = {key: int(value.get(key)) for key in ("x", "y", "w", "h")}
    except (TypeError, ValueError):
        return None
    return bbox if bbox["w"] > 0 and bbox["h"] > 0 else None


def _resolve(path: str | Path) -> Path:
    value = Path(path)
    return value.resolve() if value.is_absolute() else (ROOT / value).resolve()


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the fixed general UI recognition hierarchy benchmark.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_benchmark(manifest_path=args.manifest, out_dir=args.out)
    output = {
        "report_path": report["report_path"],
        "summary": report["summary"],
        "failure_case_ids": [case["case_id"] for case in report["failure_cases"]],
        "known_limitation_case_ids": [case["case_id"] for case in report["known_limitations"]],
        "invalid_case_ids": [case["case_id"] for case in report["invalid_cases"]],
    }
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        for key, value in output.items():
            print(f"{key}={value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
