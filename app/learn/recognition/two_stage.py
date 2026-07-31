from __future__ import annotations

import re
import unicodedata
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.core.ocr_service import ocr_service
from app.core.runtime_artifacts import ARTIFACTS_DIR
from app.learn.recognition.root_partition import (
    adapt_root_partition_to_stage1_contract,
    build_deterministic_root_partition,
    detect_horizontal_separator_cuts,
    detect_vertical_separator_cuts,
)
from app.learn.hierarchy_draft import build_hierarchy_learning_draft
from app.learn.recognition.interface_classification import classify_interface_surface
from app.learn.recognition.layout_regularization import (
    apply_card_layout_review_enhancement,
)
from app.learn.recognition.peer_card_inventory import build_agent_peer_card_inventory
from app.learn.recognition.surface_adapters import (
    build_surface_adapter_stage2_policy,
    build_surface_adapter_application,
    select_learning_surface_adapter,
    surface_adapter_excludes_inventory_item,
)
from app.learn.recognition.ownership import resolve_group_ownership
from app.learn.recognition.review_finalization import stage2_graph_revision
from app.learn.recognition.stage1_audit import audit_stage1_region_selection
from app.learn.ui_hierarchy import build_ui_hierarchy_graph


STAGE1_REGION_LOCALIZATION_PROMPT = """\
You are doing learning-mode screen structure localization.

Goal:
- Identify the visible top-level page structure regions only.
- Then localize the full visible boundary of each region in full screenshot pixel coordinates.

Rules:
- Do not number inner buttons, cards, text lines, icons, or fields in this stage.
- A region bbox must cover one whole visual area such as left rail, header, main content, list pane, detail pane, modal, or bottom bar.
- A region bbox must not cross into a neighboring structure region unless the visual evidence shows real containment.
- Use OCR text, card/text containment, separators, gutters, scrollbars, and alignment as calibration evidence.
- If the coarse bbox is offset, replace it completely instead of preserving the old coordinates.
- Return full screenshot coordinates only, never crop-local coordinates.

Output JSON:
{
  "regions": [
    {
      "region_id": "...",
      "label": "...",
      "role": "left_nav|header|main_content|list_pane|detail_pane|modal|bottom_bar|other",
      "rough_bbox": {"x": 0, "y": 0, "w": 0, "h": 0},
      "precise_bbox": {"x": 0, "y": 0, "w": 0, "h": 0},
      "evidence": ["visible boundary / OCR / separator evidence"],
      "excluded_neighbors": ["neighboring areas deliberately excluded"],
      "confidence": 0.0
    }
  ]
}
"""


def _build_stage1_structure(
    *,
    items_by_id: dict[str, dict[str, Any]],
    screen_size: dict[str, int],
    source_image_path: str,
    class_rule_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    width = _int(screen_size.get("width"))
    height = _int(screen_size.get("height"))
    if width <= 0 or height <= 0:
        raise ValueError("deterministic Stage1 requires a valid screen size")
    partition = build_deterministic_root_partition(
        list(items_by_id.values()),
        {"width": width, "height": height},
        image_path=source_image_path,
        class_rule_profile=class_rule_profile,
    )
    return adapt_root_partition_to_stage1_contract(partition)


def _normalize_stage1_structure_override(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Stage1 structure override must be a JSON object")
    regions = value.get("structure_regions")
    if not isinstance(regions, list) or not regions:
        raise ValueError("Stage1 structure override requires non-empty structure_regions")
    if value.get("execute_binding_enabled") is not False or value.get("artifact_is_authorization") is not False:
        raise ValueError("Stage1 structure override must remain read-only")
    for region in regions:
        if not isinstance(region, dict) or not isinstance(region.get("bbox"), dict):
            raise ValueError("Stage1 structure override region requires bbox")
        if region.get("execute_binding_enabled") is not False or region.get("artifact_is_authorization") is not False:
            raise ValueError("Stage1 structure override regions must remain read-only")
    return deepcopy(value)


def _localize_authoritative_root_partition(stage1: dict[str, Any]) -> dict[str, Any]:
    """把已验证的根分区原样传给下游，不再进行旧栏规则校准。"""

    localized_regions: list[dict[str, Any]] = []
    source = str(stage1.get("source") or stage1.get("partition_contract") or "explicit_structure_override")
    for region in stage1.get("structure_regions") or []:
        if not isinstance(region, dict):
            continue
        bbox = _bbox(region.get("bbox"))
        if bbox is None:
            continue
        localized_regions.append(
            {
                **deepcopy(region),
                "contract_version": "learn_stage1_authoritative_root_region_v1",
                "rough_bbox": deepcopy(bbox),
                "precise_bbox": deepcopy(bbox),
                "bbox": deepcopy(bbox),
                "stage": "stage1_authoritative_root_partition",
                "source": source,
                "bbox_policy": "authoritative_deterministic_root_partition",
                "coordinate_validation": {
                    "contract_version": "learn_stage1_region_coordinate_validation_v1",
                    "status": "authoritative_partition_geometry",
                    "evidence": "validated deterministic root partition in original-image coordinates",
                    "model_grounding_attempted": False,
                    "semantic_model": "not_run",
                    "coordinate_model": "not_run",
                    "calibration_strategy": "identity_from_validated_root_partition",
                    "can_be_replaced_by_model": False,
                    "display_only": True,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    return {
        "contract_version": "learn_stage1_authoritative_root_localization_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "localized_region_count": len(localized_regions),
        "regions": localized_regions,
        "geometry_authoritative": True,
        "legacy_bar_postprocessing_applied": False,
        "actual_model_calls": 0,
        "source": source,
    }


def build_two_stage_screen_understanding(
    *,
    bundle: dict[str, Any],
    screen_inventory: list[dict[str, Any]],
    layout_graph: dict[str, Any],
    require_stage1_gate: bool = False,
    stage2_region_strategy: str = "partitioned",
    enable_ocr_content_recovery: bool = False,
    stage1_structure_override: dict[str, Any] | None = None,
    active_surface_rules: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """生成学习模式的两阶段只读理解结果。"""

    items_by_id = _items_by_id(screen_inventory, layout_graph)
    screen_size = _screen_size_from_bundle(bundle)
    source_image_path = _source_image_path(bundle)
    interface_classification = classify_interface_surface(bundle, screen_inventory=screen_inventory)
    surface_adapter_decision = select_learning_surface_adapter(
        bundle=bundle,
        screen_inventory=screen_inventory,
        active_surface_rules=active_surface_rules or [],
    )
    class_rule_profile = deepcopy(interface_classification.get("class_rule_profile") or {})
    surface_adapter_stage2_policy = build_surface_adapter_stage2_policy(
        decision=surface_adapter_decision,
        legacy_class_rule_profile=class_rule_profile,
    )
    supplemental_text_items = _bundle_screen_text_items(bundle)
    recovered_ocr_items, content_recovery = _recover_undercovered_content_with_ocr(
        enabled=enable_ocr_content_recovery,
        image_path=source_image_path,
        items_by_id=items_by_id,
        screen_size=screen_size,
    )
    recovered_stage1_item_ids: list[str] = []
    for item in recovered_ocr_items:
        item_id = str(item.get("item_id") or "").strip()
        if not item_id or item_id in items_by_id:
            continue
        items_by_id[item_id] = deepcopy(item)
        recovered_stage1_item_ids.append(item_id)
    content_recovery["stage1_candidate_count_added"] = len(recovered_stage1_item_ids)
    content_recovery["stage1_candidate_integration"] = (
        "included_before_root_partition" if recovered_stage1_item_ids else "not_added"
    )
    supplemental_text_items.extend(recovered_ocr_items)
    normalized_stage1_override = _normalize_stage1_structure_override(stage1_structure_override)
    stage1 = normalized_stage1_override or _build_stage1_structure(
        items_by_id=items_by_id,
        screen_size=screen_size,
        source_image_path=source_image_path,
        class_rule_profile=class_rule_profile,
    )
    stage1_localization = _localize_authoritative_root_partition(stage1)
    surface_adapter_application = build_surface_adapter_application(
        decision=surface_adapter_decision,
        localized_regions=stage1_localization["regions"],
        items_by_id=items_by_id,
    )
    stage1_overlay_path = _render_stage1_region_localization_overlay(
        image_path=source_image_path,
        localized_regions=stage1_localization["regions"],
    )
    stage1_localization["overlay_path"] = stage1_overlay_path
    stage1_gate = _stage1_gate_report(
        localized_regions=stage1_localization["regions"],
        screen_size=screen_size,
        required=require_stage1_gate,
    )
    region_selection_audit = stage1_gate.get("audit") if isinstance(stage1_gate.get("audit"), dict) else {}
    granularity_review = _stage1_granularity_review(
        localized_regions=stage1_localization["regions"],
        items_by_id=items_by_id,
        screen_size=screen_size,
        region_selection_audit=region_selection_audit,
        class_rule_profile=class_rule_profile,
    )
    stage1_5_partition = _stage1_5_partition(
        localized_regions=stage1_localization["regions"],
        items_by_id=items_by_id,
        screen_size=screen_size,
        region_selection_audit=region_selection_audit,
        granularity_review=granularity_review,
        source_image_path=source_image_path,
        class_rule_profile=class_rule_profile,
    )
    normalized_stage2_strategy = _normalize_stage2_region_strategy(stage2_region_strategy)
    if normalized_stage2_strategy == "global_no_partition":
        stage2_input_regions = _stage2_global_no_partition_input_regions(
            items_by_id=items_by_id,
            screen_size=screen_size,
        )
    else:
        stage2_input_regions = _stage2_input_regions(
            localized_regions=stage1_localization["regions"],
            stage1_5_partition=stage1_5_partition,
            items_by_id=items_by_id,
        )
    if require_stage1_gate and not stage1_gate["allow_stage2_numbering"]:
        stage2 = _stage2_skipped_by_stage1_gate(stage1_gate)
    else:
        stage2 = _stage2_numbering(
            stage2_input_regions,
            items_by_id=items_by_id,
            supplemental_text_items=supplemental_text_items,
            image_path=source_image_path,
            class_rule_profile=class_rule_profile,
            surface_adapter_decision=surface_adapter_decision,
            surface_adapter_stage2_policy=surface_adapter_stage2_policy,
        )
    layout_review_enhancement = apply_card_layout_review_enhancement(
        image_path=source_image_path,
        numbered_regions=stage2["regions"],
        stage2_policy=surface_adapter_stage2_policy,
    )
    stage2["regions"] = layout_review_enhancement["regions"]
    stage2["layout_review_enhancement"] = {
        key: deepcopy(value)
        for key, value in layout_review_enhancement.items()
        if key != "regions"
    }
    stage2["agent_peer_card_inventory"] = build_agent_peer_card_inventory(
        numbered_regions=stage2["regions"],
        stage2_policy=surface_adapter_stage2_policy,
    )
    calibration_partition = summarize_stage2_calibration_partition(stage2)
    stage2["calibration_candidate_count"] = calibration_partition["calibration_candidate_count"]
    stage2["calibration_child_evidence_count"] = calibration_partition["calibration_child_evidence_count"]
    stage2["calibration_partition_summary"] = calibration_partition
    fusion = _fusion_boxes(stage1_localization["regions"], stage2["regions"])
    downstream_numbered_regions, downstream_group_normalization = _active_numbered_regions_after_sibling_review(
        stage2["regions"]
    )
    fusion["downstream_group_normalization"] = downstream_group_normalization
    fusion["stage1_structure_overlay_path"] = stage1_overlay_path
    if stage2.get("skipped"):
        _mark_fusion_not_promotable_when_stage2_skipped(fusion, stage2)
    overlay_path = _render_two_stage_overlay(
        image_path=source_image_path,
        structure_regions=stage1_localization["regions"],
        numbered_regions=downstream_numbered_regions,
    )
    if overlay_path:
        fusion["compiled_overlay_path"] = overlay_path
        fusion["full_screen_understanding_overlay_path"] = overlay_path
    context_overlay = _render_message_context_review_overlay(
        image_path=source_image_path,
        numbered_regions=downstream_numbered_regions,
        fused_review_boxes=fusion["fused_review_boxes"],
    )
    if context_overlay.get("overlay_path"):
        fusion["message_context_overlay"] = context_overlay
        fusion["message_context_overlay_path"] = context_overlay.get("overlay_path", "")
        fusion["message_context_zoom_path"] = context_overlay.get("zoom_path", "")
    ui_hierarchy = build_ui_hierarchy_graph(
        structure_regions=stage1_localization["regions"],
        numbered_regions=downstream_numbered_regions,
        screen_size=screen_size,
    )
    learning_draft = build_hierarchy_learning_draft(
        ui_hierarchy=ui_hierarchy,
        source_image_path=source_image_path,
        compiled_overlay_path=str(fusion.get("compiled_overlay_path") or ""),
    )
    pipeline_contract = _two_pass_pipeline_contract()
    return {
        "contract_version": "learn_two_stage_screen_understanding_v1",
        "source_image_path": source_image_path,
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "pipeline_contract": pipeline_contract,
        "interface_classification": interface_classification,
        "surface_adapter_decision": surface_adapter_decision,
        "surface_adapter_application": surface_adapter_application,
        "surface_adapter_stage2_policy": surface_adapter_stage2_policy,
        "class_rule_profile": class_rule_profile,
        "flow_compliance": _two_pass_flow_compliance(stage1_localization, stage2),
        "content_recovery": content_recovery,
        "stage1_gate": stage1_gate,
        "stage1_granularity_review": granularity_review,
        "stage1_5_partition": stage1_5_partition,
        "stage2_input_policy": {
            "contract_version": "learn_stage2_input_policy_v1",
            "display_only": True,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "stage2_region_strategy": normalized_stage2_strategy,
            "stage1_5_subregions_replace_parent_for_numbering": bool(
                (stage1_5_partition.get("stage2_selection") or {}).get("eligible_count")
            ),
            "stage1_5_eligible_subregion_count": _int(
                (stage1_5_partition.get("stage2_selection") or {}).get("eligible_count")
            ),
            "stage1_5_rejected_subregion_count": _int(
                (stage1_5_partition.get("stage2_selection") or {}).get("rejected_count")
            ),
            "stage1_regions_unchanged": True,
            "input_region_count": len(stage2_input_regions),
        },
        "stage2_numbering_skipped": bool(stage2.get("skipped")),
        "execution_evidence": {
            "contract_version": "learn_recognition_execution_evidence_v1",
            "stage1_engine": str(stage1.get("partition_contract") or stage1.get("source") or "explicit_structure_override"),
            "stage2_engine": "deterministic_partition_content_recognition_v1",
            "actual_model_calls": 0,
            "stage1_model_calls": 0,
            "stage2_model_calls": 0,
            "model_assisted": False,
            "stage1_geometry_authoritative": True,
            "legacy_bar_postprocessing_applied": False,
            "interpretation": (
                "Execution evidence for this run; no model call or legacy bar-localization postprocessor was used."
            ),
        },
        "stage1_structure": stage1,
        "stage1_source": str(stage1.get("source") or stage1.get("partition_contract") or "explicit_structure_override"),
        "stage1_region_localization": stage1_localization,
        "source_graph_revision": stage2_graph_revision(stage2),
        "stage2_numbering": stage2,
        "fusion": fusion,
        "ui_hierarchy": ui_hierarchy,
        "learning_draft": learning_draft,
        "page_details": deepcopy(learning_draft.get("page_details") or {}),
        "interpretation": (
            "Two-stage learning output is display/review only; it is not a Runtime PathGraph, "
            "not click authorization, and not a recognition accuracy metric."
        ),
    }


def _mark_fusion_not_promotable_when_stage2_skipped(fusion: dict[str, Any], stage2: dict[str, Any]) -> None:
    summary = fusion.get("region_content_boundary_summary")
    if not isinstance(summary, dict):
        return
    blockers = summary.get("promotion_blockers") if isinstance(summary.get("promotion_blockers"), list) else []
    if "stage2_numbering_skipped" not in blockers:
        blockers.append("stage2_numbering_skipped")
    summary["boundary_contract_status"] = "not_evaluated_stage2_skipped"
    summary["pathgraph_promotion_allowed"] = False
    summary["promotion_blockers"] = blockers
    summary["stage2_skip_reason"] = str(stage2.get("skip_reason") or "stage2_skipped")
    summary["interpretation"] = (
        "Stage2 child boundary checks were not evaluated because Stage1 gate blocked numbering; "
        "this cannot be promoted or treated as a child-boundary pass."
    )


def _stage1_gate_report(
    *,
    localized_regions: list[dict[str, Any]],
    screen_size: dict[str, int],
    required: bool,
) -> dict[str, Any]:
    audit = audit_stage1_region_selection(
        localized_regions=localized_regions,
        screen_size=screen_size,
    )
    allow_stage2 = bool(audit.get("passed"))
    return {
        "contract_version": "learn_stage1_before_stage2_gate_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "required": bool(required),
        "allow_stage2_numbering": allow_stage2,
        "status": "passed" if allow_stage2 else "blocked_before_stage2_numbering",
        "failure_categories": deepcopy(audit.get("failure_categories") if isinstance(audit.get("failure_categories"), list) else []),
        "audit": audit,
        "policy": (
            "New interface tests must stop after bind/screenshot/stage1 localization until whole-region "
            "selection is reviewed as precise and structurally correct. Stage2 item numbering is not allowed "
            "when this gate fails."
        ),
        "not_accuracy": True,
    }


def _stage2_skipped_by_stage1_gate(stage1_gate: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": "learn_stage2_region_numbering_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "skipped": True,
        "skip_reason": "stage1_region_gate_failed",
        "stage1_gate_status": deepcopy(stage1_gate),
        "region_count": 0,
        "numbered_item_count": 0,
        "regions": [],
        "model_prompt_intent": "Stage2 item numbering is blocked until Stage1 region localization is reviewed and accepted.",
    }


def _append_supplemental_text_items_for_region(
    region_items: list[dict[str, Any]],
    supplemental_text_items: list[dict[str, Any]],
    *,
    region_bbox: dict[str, int],
) -> list[dict[str, Any]]:
    if not region_bbox or not supplemental_text_items:
        return region_items
    result = list(region_items)
    existing_bboxes = [_bbox(item.get("bbox")) for item in result if isinstance(item, dict)]
    existing_labels = {str(item.get("label") or item.get("text") or "").strip().casefold() for item in result}
    for item in supplemental_text_items:
        if not isinstance(item, dict):
            continue
        bbox = _bbox(item.get("bbox"))
        label = str(item.get("label") or item.get("text") or "").strip()
        if not bbox or not label:
            continue
        if _bbox_containment_ratio(bbox, region_bbox) < 0.98:
            continue
        label_key = label.casefold()
        duplicate = False
        for existing_bbox in existing_bboxes:
            if not existing_bbox:
                continue
            if _bbox_overlap_ratio(bbox, existing_bbox) >= 0.65 or _bbox_overlap_ratio(existing_bbox, bbox) >= 0.65:
                duplicate = label_key in existing_labels or abs(bbox["y"] - existing_bbox["y"]) <= 8
                if duplicate:
                    break
        if duplicate:
            continue
        result.append(deepcopy(item))
        existing_bboxes.append(bbox)
        existing_labels.add(label_key)
    return result


def _two_pass_pipeline_contract() -> dict[str, Any]:
    return {
        "contract_version": "learn_mode_deterministic_hierarchy_pipeline_contract_v1",
        "source_doc": "docs/DETERMINISTIC_HIERARCHICAL_REGION_PARTITION.md",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "steps": [
            "bind_and_capture",
            "collect_parser_ocr_uia_evidence",
            "coarse_region_proposal",
            "deterministic_root_partition",
            "root_partition_validation",
            "authoritative_root_geometry_passthrough",
            "per_partition_content_recognition",
            "conditional_ocr_main_content_recovery",
            "nested_content_grouping",
            "evidence_fusion",
            "learning_draft_review_only",
            "pathgraph_preview_review_only",
            "human_review_edit",
        ],
        "region_bbox_policy": "validated_root_partition_geometry_is_authoritative_and_covers_the_screen",
        "parent_child_boundary_policy": (
            "stage2_children_must_name_parent_region_and_final_fusion_overlay_must_clip_child_bbox_to_parent"
        ),
        "partition_numbering_policy": "recognize_content_inside_each_authoritative_root_partition",
        "center_policy": "nested_content_groups_may_be_built_inside_root_partitions",
        "single_screenshot_patch_policy": "forbidden_as_primary_strategy",
        "actual_model_calls": 0,
        "legacy_bar_postprocessing_applied": False,
    }


def _recover_undercovered_content_with_ocr(
    *,
    enabled: bool,
    image_path: str,
    items_by_id: dict[str, dict[str, Any]],
    screen_size: dict[str, int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    width = _int(screen_size.get("width"))
    height = _int(screen_size.get("height"))
    existing_bottom = max(
        (
            bbox["y"] + bbox["h"]
            for item in items_by_id.values()
            for bbox in [_bbox(item.get("bbox"))]
            if bbox
        ),
        default=0,
    )
    existing_coverage = round(existing_bottom / max(1, height), 4) if height > 0 else 0.0
    base_report = {
        "contract_version": "learn_conditional_ocr_content_recovery_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "trigger_threshold": 0.55,
        "existing_content_vertical_coverage": existing_coverage,
        "ocr_match_count": 0,
        "added_item_count": 0,
    }
    if not enabled:
        return [], {**base_report, "status": "disabled"}
    if existing_coverage >= 0.55:
        return [], {**base_report, "status": "not_needed_existing_coverage_sufficient"}
    source = Path(image_path) if image_path else None
    if source is None or not source.is_file() or width <= 0 or height <= 0:
        return [], {**base_report, "status": "unavailable", "reason": "source_image_or_size_missing"}
    try:
        ocr_result = ocr_service.scan_image(str(source))
    except Exception as exc:
        return [], {
            **base_report,
            "status": "failed",
            "reason": f"ocr_scan_failed:{type(exc).__name__}:{exc}",
        }
    recovered: list[dict[str, Any]] = []
    for index, match in enumerate(ocr_result.matches, start=1):
        score = float(match.score)
        bbox = {
            "x": max(0, int(match.bbox.x)),
            "y": max(0, int(match.bbox.y)),
            "w": max(1, int(match.bbox.width)),
            "h": max(1, int(match.bbox.height)),
        }
        if score < 0.55 or bbox["x"] >= width or bbox["y"] >= height:
            continue
        bbox["w"] = min(bbox["w"], width - bbox["x"])
        bbox["h"] = min(bbox["h"], height - bbox["y"])
        recovered.append(
            {
                "item_id": f"ocr_content_recovery_{index}",
                "label": str(match.text).strip(),
                "role": "text",
                "item_type": "readable",
                "bbox": bbox,
                "source": "conditional_ocr_content_recovery",
                "source_evidence": ["ocr"],
                "review_only": True,
                "grounding_eligible": False,
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
                "metadata": {"confidence": score, "ocr_engine": ocr_result.metadata.get("engine")},
            }
        )
    recovered_bottom = max((item["bbox"]["y"] + item["bbox"]["h"] for item in recovered), default=existing_bottom)
    return recovered, {
        **base_report,
        "status": "applied" if recovered else "no_new_content",
        "ocr_engine": ocr_result.metadata.get("engine"),
        "ocr_match_count": len(ocr_result.matches),
        "added_item_count": len(recovered),
        "recovered_content_vertical_coverage": round(recovered_bottom / max(1, height), 4),
    }


def _two_pass_flow_compliance(stage1_localization: dict[str, Any], stage2: dict[str, Any]) -> dict[str, Any]:
    regions = stage2.get("regions") if isinstance(stage2.get("regions"), list) else []
    direct_regions = [
        region
        for region in regions
        if isinstance(region, dict)
        and (region.get("region_processing_contract") or {}).get("mode") == "direct_numbering_within_precise_region"
    ]
    center_regions = [
        region
        for region in regions
        if isinstance(region, dict)
        and (region.get("region_processing_contract") or {}).get("mode") == "subdivide_then_number"
    ]
    center_with_subdivision = [
        region for region in center_regions if (region.get("main_content_subdivision") or {}).get("subdivision_required") is True
    ]
    return {
        "contract_version": "learn_two_pass_flow_compliance_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "stage1_region_split_present": bool((stage1_localization.get("regions") or [])),
        "whole_region_localization_present": bool((stage1_localization.get("regions") or [])),
        "direct_partition_region_count": len(direct_regions),
        "center_region_count": len(center_regions),
        "center_subdivision_region_count": len(center_with_subdivision),
        "single_screenshot_patch_strategy_used": False,
        "status": "deterministic_hierarchy_executed",
        "actual_model_calls": 0,
        "legacy_bar_postprocessing_applied": False,
        "not_accuracy": True,
    }


def build_stage1_region_localization_report(
    *,
    bundle: dict[str, Any],
    screen_inventory: list[dict[str, Any]],
    layout_graph: dict[str, Any],
    stage1_structure_override: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """只运行学习模式第一阶段：整栏定位和校准诊断。"""

    items_by_id = _items_by_id(screen_inventory, layout_graph)
    screen_size = _screen_size_from_bundle(bundle)
    interface_classification = classify_interface_surface(bundle, screen_inventory=screen_inventory)
    class_rule_profile = deepcopy(interface_classification.get("class_rule_profile") or {})
    normalized_stage1_override = _normalize_stage1_structure_override(stage1_structure_override)
    stage1 = normalized_stage1_override or _build_stage1_structure(
        items_by_id=items_by_id,
        screen_size=screen_size,
        source_image_path=_source_image_path(bundle),
        class_rule_profile=class_rule_profile,
    )
    stage1_localization = _stage1_region_localization(
        stage1["structure_regions"],
        items_by_id=items_by_id,
        screen_size=screen_size,
    )
    calibration = _stage1_calibration_diagnostics(stage1_localization["regions"])
    overlay_path = _render_stage1_region_localization_overlay(
        image_path=_source_image_path(bundle),
        localized_regions=stage1_localization["regions"],
    )
    region_selection_audit = audit_stage1_region_selection(
        localized_regions=stage1_localization["regions"],
        screen_size=_screen_size_from_bundle(bundle),
        overlay_path=overlay_path,
    )
    granularity_review = _stage1_granularity_review(
        localized_regions=stage1_localization["regions"],
        items_by_id=items_by_id,
        screen_size=screen_size,
        region_selection_audit=region_selection_audit,
        class_rule_profile=class_rule_profile,
    )
    stage1_5_partition = _stage1_5_partition(
        localized_regions=stage1_localization["regions"],
        items_by_id=items_by_id,
        screen_size=screen_size,
        region_selection_audit=region_selection_audit,
        granularity_review=granularity_review,
        source_image_path=_source_image_path(bundle),
        class_rule_profile=class_rule_profile,
    )
    stage1_5_overlay_path = _render_stage1_5_partition_overlay(
        image_path=_source_image_path(bundle),
        localized_regions=stage1_localization["regions"],
        subregions=stage1_5_partition["subregions"],
    )
    return {
        "contract_version": "learn_stage1_region_localization_report_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "scope": "stage1_region_localization_only",
        "stage2_numbering_skipped": True,
        "pathgraph_generation_skipped": True,
        "model_call_plan": {
            "contract_version": "learn_stage1_region_localization_model_call_plan_v1",
            "recommended_model_calls": 1,
            "semantic_model": "qwen3_vl_8b_q4_k_m",
            "coordinate_model": "vista_4b_transformers",
            "prompt": STAGE1_REGION_LOCALIZATION_PROMPT,
            "input_contract": {
                "screenshot": "full_window_screenshot",
                "ocr": "text anchors for boundary calibration",
                "coarse_regions": "initial hints only; model may replace them completely",
            },
            "output_contract": "top_level_structure_regions_with_precise_full_screenshot_bbox",
            "interpretation": "This is a prompt/model calibration report, not a learning draft and not click authorization.",
        },
        "stage1_structure": stage1,
        "stage1_source": str(stage1.get("source") or stage1.get("partition_contract") or ""),
        "stage1_region_localization": stage1_localization,
        "calibration_diagnostics": calibration,
        "region_selection_audit": region_selection_audit,
        "stage1_granularity_review": granularity_review,
        "stage1_5_partition": stage1_5_partition,
        "stage1_5_overlay_path": stage1_5_overlay_path,
        "overlay_path": overlay_path,
        "display_readiness": {
            "stage1_overlay_available": bool(overlay_path),
            "stage1_5_overlay_available": bool(stage1_5_overlay_path),
            "shows_only_structure_regions": True,
            "requires_click_to_show_boxes": False,
        },
        "interpretation": (
            "Stage1-only report isolates column/region localization offset. "
            "It deliberately skips item numbering, fusion, Runtime PathGraph, and execution."
        ),
    }


def fusion_status_from_two_stage(two_stage: dict[str, Any]) -> dict[str, Any]:
    fusion = two_stage.get("fusion") if isinstance(two_stage.get("fusion"), dict) else {}
    stage1 = two_stage.get("stage1_structure") if isinstance(two_stage.get("stage1_structure"), dict) else {}
    stage1_localization = (
        two_stage.get("stage1_region_localization")
        if isinstance(two_stage.get("stage1_region_localization"), dict)
        else {}
    )
    stage2 = two_stage.get("stage2_numbering") if isinstance(two_stage.get("stage2_numbering"), dict) else {}
    return {
        "contract_version": "learn_precise_understanding_fusion_status_report_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "not_accuracy": True,
        "full_screen_understanding_overlay_path": str(fusion.get("full_screen_understanding_overlay_path") or ""),
        "compiled_overlay_path": str(fusion.get("compiled_overlay_path") or ""),
        "summary": {
            "structure_region_count": _int(stage1.get("region_count")),
            "stage1_localized_region_count": _int(stage1_localization.get("localized_region_count")),
            "numbered_item_count": _int(stage2.get("numbered_item_count")),
            "fused_review_box_count": _int(fusion.get("fused_review_box_count")),
            "stage1_engine": str((two_stage.get("execution_evidence") or {}).get("stage1_engine") or "unknown"),
            "stage2_engine": str((two_stage.get("execution_evidence") or {}).get("stage2_engine") or "unknown"),
            "actual_model_calls": _int((two_stage.get("execution_evidence") or {}).get("actual_model_calls")),
        },
        "display_readiness": {
            "screenshot_updates_automatically": bool(fusion.get("compiled_overlay_path")),
            "review_only_boxes_visible": True,
            "requires_click_to_show_boxes": False,
        },
        "interpretation": "Fused two-stage screenshot overlay for review only; not Execute binding.",
    }


def model_grounding_evidence_status_from_two_stage(two_stage: dict[str, Any]) -> dict[str, Any]:
    stage1_localization = (
        two_stage.get("stage1_region_localization")
        if isinstance(two_stage.get("stage1_region_localization"), dict)
        else {}
    )
    regions = stage1_localization.get("regions") if isinstance(stage1_localization.get("regions"), list) else []
    grounded_region_ids: list[str] = []
    ungrounded_region_ids: list[str] = []
    model_names: set[str] = set()
    for region in regions:
        if not isinstance(region, dict):
            continue
        validation = region.get("coordinate_validation") if isinstance(region.get("coordinate_validation"), dict) else {}
        region_id = str(region.get("region_id") or region.get("label") or "").strip()
        if validation.get("model_grounding_attempted") is True:
            grounded_region_ids.append(region_id)
            for key in ("semantic_model", "coordinate_model"):
                model_name = str(validation.get(key) or "").strip()
                if model_name and model_name != "not_run":
                    model_names.add(model_name)
        else:
            ungrounded_region_ids.append(region_id)
    model_call_plan = two_stage.get("model_call_plan") if isinstance(two_stage.get("model_call_plan"), dict) else {}
    recommendation_only = bool(model_call_plan) and not grounded_region_ids
    stage2 = two_stage.get("stage2_numbering") if isinstance(two_stage.get("stage2_numbering"), dict) else {}
    if not grounded_region_ids:
        status = "not_valid_for_model_grounding_evidence"
        reason = "no_model_grounding_attempts_recorded"
    elif len(grounded_region_ids) < len(regions):
        status = "partial_model_grounding_evidence"
        reason = "some_structure_regions_have_no_model_grounding_evidence"
    else:
        status = "valid_for_model_grounding_evidence"
        reason = "all_structure_regions_record_model_grounding_attempts"
    return {
        "contract_version": "learn_model_grounding_evidence_status_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "not_accuracy": True,
        "status": status,
        "reason": reason,
        "model_grounding_attempted_count": len(grounded_region_ids),
        "stage1_region_count": len(regions),
        "stage2_numbered_item_count": _int(stage2.get("numbered_item_count")),
        "model_grounded_region_ids": grounded_region_ids,
        "regions_without_model_grounding": ungrounded_region_ids,
        "model_names_with_recorded_grounding": sorted(model_names),
        "model_call_plan_is_recommendation_only": recommendation_only,
        "interpretation": (
            "This field only says whether the overlay can be used as model-grounding evidence. "
            "Recommendation-only model names, heuristic calibration, or parser cleanup do not prove model accuracy."
        ),
    }


def _items_by_id(screen_inventory: list[dict[str, Any]], layout_graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(screen_inventory if isinstance(screen_inventory, list) else []):
        if not isinstance(item, dict):
            continue
        item_id = _item_id(item, index)
        result[item_id] = deepcopy(item)
    nodes = layout_graph.get("nodes") if isinstance(layout_graph.get("nodes"), dict) else {}
    for node_id, node in nodes.items():
        if not isinstance(node, dict):
            continue
        normalized_id = str(node.get("item_id") or node_id or "").strip()
        if normalized_id and normalized_id not in result:
            result[normalized_id] = deepcopy(node)
    return result


def _bundle_screen_text_items(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    texts: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int, int, int]] = set()
    candidates: list[Any] = []
    for container in (
        bundle.get("screen_reading") if isinstance(bundle.get("screen_reading"), dict) else {},
        bundle.get("result", {}).get("screen_reading") if isinstance(bundle.get("result"), dict) and isinstance(bundle.get("result", {}).get("screen_reading"), dict) else {},
    ):
        if isinstance(container, dict) and isinstance(container.get("texts"), list):
            candidates.extend(container["texts"])
    if isinstance(bundle.get("texts"), list):
        candidates.extend(bundle["texts"])
    for index, item in enumerate(candidates, start=1):
        if not isinstance(item, dict):
            continue
        label = str(item.get("text") or item.get("label") or "").strip()
        bbox = _bbox(item.get("bbox"))
        if not label or not bbox:
            continue
        key = (label, bbox["x"], bbox["y"], bbox["w"], bbox["h"])
        if key in seen:
            continue
        seen.add(key)
        texts.append(
            {
                "item_id": f"ocr_bundle_text_{len(texts) + 1}",
                "label": label,
                "role": "text",
                "item_type": "readable",
                "bbox": bbox,
                "source": str(item.get("source") or "screen_reading_text"),
                "review_only": True,
                "grounding_eligible": False,
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    return texts


def _split_conversation_bottom_panel(
    corrected_zone_items: dict[str, list[str]],
    *,
    items_by_id: dict[str, dict[str, Any]],
    screen_size: dict[str, int],
    class_rule_profile: dict[str, Any] | None,
) -> dict[str, Any] | None:
    profile = class_rule_profile if isinstance(class_rule_profile, dict) else {}
    if profile.get("primary_content_strategy") != "conversation_rows":
        return None
    width = _int(screen_size.get("width"))
    height = _int(screen_size.get("height"))
    if width <= 0 or height <= 0:
        return None
    start_y = int(height * 0.84)
    candidates_by_zone: dict[str, list[str]] = {}
    candidate_boxes: list[dict[str, int]] = []
    for zone_id, item_ids in corrected_zone_items.items():
        if _is_top_zone(zone_id) or zone_id in {"browser_chrome", "bottom_bar", "conversation_bottom_panel"}:
            continue
        for item_id in item_ids:
            item = items_by_id.get(item_id)
            bbox = _bbox(item.get("bbox")) if isinstance(item, dict) else None
            if not bbox or bbox["y"] < start_y or bbox["y"] >= height:
                continue
            candidates_by_zone.setdefault(zone_id, []).append(item_id)
            candidate_boxes.append(bbox)
    candidate_ids = [item_id for item_ids in candidates_by_zone.values() for item_id in item_ids]
    if len(candidate_ids) < 3 or len(candidates_by_zone) < 2:
        return None
    if not _has_explicit_conversation_bottom_panel_boundary(
        candidate_ids,
        items_by_id=items_by_id,
        screen_width=width,
    ):
        return None
    for zone_id, selected_ids in candidates_by_zone.items():
        selected = set(selected_ids)
        corrected_zone_items[zone_id] = [item_id for item_id in corrected_zone_items[zone_id] if item_id not in selected]
    corrected_zone_items["conversation_bottom_panel"] = candidate_ids
    source_bbox = _bbox_union(candidate_boxes) or {}
    return {
        "contract_version": "learn_stage1_zone_correction_v1",
        "correction": "cross_zone_conversation_bottom_panel_reunited",
        "source_zones": list(candidates_by_zone),
        "target_zone": "conversation_bottom_panel",
        "item_ids": candidate_ids,
        "source_bbox": deepcopy(source_bbox),
        "reason": "conversation evidence in the same bottom band was split across structure zones",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _has_explicit_conversation_bottom_panel_boundary(
    candidate_ids: list[str],
    *,
    items_by_id: dict[str, dict[str, Any]],
    screen_width: int,
) -> bool:
    """只有存在明确分段证据时，才把底部内容提升为独立会话面板。"""

    group_section_tokens = (
        "group chat",
        "group chats",
        "group conversation",
        "group conversations",
        "群组聊天",
        "群組聊天",
        "群聊",
    )
    for item_id in candidate_ids:
        item = items_by_id.get(item_id)
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        structural_value = " ".join(
            [
                str(item.get("item_id") or ""),
                str(item.get("role") or ""),
                str(item.get("item_type") or ""),
                str(metadata.get("surface_zone") or ""),
                str(metadata.get("layout_zone") or ""),
            ]
        ).casefold()
        if "bottom_bar" in structural_value or "conversation_bottom_panel" in structural_value:
            return True
        label_value = " ".join(
            [
                str(item.get("label") or ""),
                str(item.get("description") or ""),
                str(item.get("ocr_text") or ""),
            ]
        ).casefold()
        if any(token in label_value for token in group_section_tokens):
            return True
        if "separator" in structural_value:
            bbox = _bbox(item.get("bbox"))
            if bbox and bbox["w"] >= max(1, int(screen_width * 0.45)):
                return True
    return False




def _is_top_zone(zone_id: str) -> bool:
    lowered = str(zone_id or "").casefold()
    return lowered in {"page_header", "top_bar", "browser_chrome", "header"} or any(
        token in lowered for token in ("header", "top_bar", "browser_chrome")
    )




def _looks_like_browser_chrome_evidence(item: dict[str, Any]) -> bool:
    text = " ".join(
        str(item.get(key) or "")
        for key in ("label", "text", "description", "role", "item_type")
    ).casefold()
    return any(
        token in text
        for token in (
            "http://",
            "https://",
            "www.",
            ".com",
            ".org",
            "address",
            "browser",
            "tab",
            "new tab",
            "reload",
            "调试此浏览器",
            "自动测试软件控制",
            "debugging this browser",
            "controlled by automated test software",
        )
    )


def _is_browser_chrome_top_item(item: dict[str, Any], *, chrome_bottom: int, screen_width: int = 0) -> bool:
    bbox = _bbox(item.get("bbox"))
    if not bbox:
        return False
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    if _is_large_top_surface_container(item, bbox=bbox, chrome_bottom=chrome_bottom, screen_width=screen_width):
        return False
    if _looks_like_browser_chrome_evidence(item):
        return True
    if bbox["y"] > chrome_bottom:
        return False
    if any(token in role for token in ("icon", "button", "control")):
        return True
    label = str(item.get("label") or item.get("text") or "").strip()
    if label in {"←", "→", "↻", "⌂", "★", "☆", "+", "×", "x"}:
        return True
    return bool(screen_width and bbox["x"] >= int(screen_width * 0.85) and len(label) <= 12)


def _is_large_top_surface_container(
    item: dict[str, Any],
    *,
    bbox: dict[str, int],
    chrome_bottom: int,
    screen_width: int = 0,
) -> bool:
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    if not any(token in role for token in ("window", "pane", "document", "group")):
        return False
    if screen_width > 0 and bbox["w"] < int(screen_width * 0.45):
        return False
    return bbox["h"] > max(72, chrome_bottom * 2)








def _split_narrow_left_rail_from_visual_separator(
    corrected_zone_items: dict[str, list[str]],
    *,
    items_by_id: dict[str, dict[str, Any]],
    screen_size: dict[str, int],
    source_image_path: str,
) -> None:
    width = _int(screen_size.get("width"))
    height = _int(screen_size.get("height"))
    if (
        width <= 0
        or height <= 0
        or not source_image_path
        or any(zone_id in corrected_zone_items for zone_id in ("left_nav", "left_sidebar"))
    ):
        return
    divider_x = _persistent_left_vertical_divider(
        source_image_path=source_image_path,
        width=width,
        height=height,
    )
    if divider_x <= 0:
        return
    source_zone = next(
        (zone_id for zone_id in ("primary_area", "main_content") if corrected_zone_items.get(zone_id)),
        "",
    )
    if not source_zone:
        return
    source_ids = corrected_zone_items[source_zone]
    candidate_ids: list[str] = []
    for item_id in source_ids:
        item = items_by_id.get(item_id)
        bbox = _bbox(item.get("bbox")) if isinstance(item, dict) else None
        if not isinstance(item, dict) or not bbox or _is_section_hint(item):
            continue
        center_x = bbox["x"] + bbox["w"] / 2
        if center_x >= divider_x or bbox["w"] > divider_x:
            continue
        candidate_ids.append(item_id)
    if len(candidate_ids) < 3:
        return
    for item_id in candidate_ids:
        item = items_by_id[item_id]
        metadata = deepcopy(item.get("metadata")) if isinstance(item.get("metadata"), dict) else {}
        metadata.update(
            {
                "surface_zone": "left_nav",
                "visual_left_rail_boundary_x": divider_x,
                "visual_left_rail_evidence": "persistent_vertical_separator_with_aligned_left_items",
            }
        )
        item["metadata"] = metadata
    candidate_set = set(candidate_ids)
    corrected_zone_items[source_zone] = [item_id for item_id in source_ids if item_id not in candidate_set]
    corrected_zone_items["left_nav"] = [item_id for item_id in source_ids if item_id in candidate_set]


def _persistent_left_vertical_divider(*, source_image_path: str, width: int, height: int) -> int:
    path = Path(source_image_path)
    if not path.is_file():
        return 0
    try:
        with Image.open(path) as image:
            gray = image.convert("L")
            if gray.size != (width, height):
                gray = gray.resize((width, height))
            pixels = gray.load()
            y_start = max(1, int(height * 0.08))
            y_values = range(y_start, height, 2)
            scores: list[tuple[float, float, int]] = []
            for x in range(max(2, int(width * 0.03)), min(width - 1, int(width * 0.18))):
                differences = [abs(int(pixels[x, y]) - int(pixels[x - 1, y])) for y in y_values]
                if not differences:
                    continue
                mean_difference = sum(differences) / len(differences)
                persistent_ratio = sum(1 for value in differences if value > 12) / len(differences)
                scores.append((mean_difference, persistent_ratio, x))
    except (OSError, ValueError):
        return 0
    if not scores:
        return 0
    mean_difference, persistent_ratio, divider_x = max(scores, key=lambda value: (value[0], value[1], -value[2]))
    return divider_x if mean_difference >= 35.0 and persistent_ratio >= 0.30 else 0












def _is_card_like_region_item(item: dict[str, Any]) -> bool:
    value = " ".join(str(item.get(key) or "").casefold() for key in ("role", "item_type", "layout", "label"))
    return any(token in value for token in ("card", "media", "album", "grid", "recommendation"))


def _horizontal_overlap_ratio(left: dict[str, int], right: dict[str, int]) -> float:
    x1 = max(left["x"], right["x"])
    x2 = min(left["x"] + left["w"], right["x"] + right["w"])
    overlap = max(0, x2 - x1)
    return overlap / max(1, min(left["w"], right["w"]))


def _vertical_overlap_ratio(top: dict[str, int], bottom: dict[str, int]) -> float:
    y1 = max(top["y"], bottom["y"])
    y2 = min(top["y"] + top["h"], bottom["y"] + bottom["h"])
    overlap = max(0, y2 - y1)
    return overlap / max(1, min(top["h"], bottom["h"]))


def _stage1_region_localization(
    structure_regions: list[dict[str, Any]],
    *,
    items_by_id: dict[str, dict[str, Any]] | None = None,
    screen_size: dict[str, int] | None = None,
    boundary_evidence_items: list[dict[str, Any]] | None = None,
    app_name: str = "",
) -> dict[str, Any]:
    localized_regions: list[dict[str, Any]] = []
    all_items = items_by_id if isinstance(items_by_id, dict) else {}
    screen = screen_size if isinstance(screen_size, dict) else {}
    for region in structure_regions:
        rough_bbox = _bbox(region.get("bbox"))
        calibration = _calibrated_stage1_bbox(region, items_by_id=all_items, screen_size=screen)
        precise_bbox = calibration.get("bbox") if isinstance(calibration.get("bbox"), dict) else deepcopy(rough_bbox or {})
        region_id = str(region.get("region_id") or "")
        label = str(region.get("label") or region_id)
        coordinate_validation = {
            "contract_version": "learn_stage1_region_coordinate_validation_v1",
            "status": str(calibration.get("status") or ("validated_from_stage1_geometry" if rough_bbox else "missing_region_bbox")),
            "evidence": str(calibration.get("evidence") or "bbox union after structure-zone correction"),
            "model_grounding_attempted": False,
            "semantic_model": "not_run",
            "coordinate_model": "not_run",
            "calibration_strategy": str(calibration.get("strategy") or "geometry_copy"),
            "can_be_replaced_by_model": True,
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
        for extra_key in ("right_edge_preservation", "unsupported_tail_trimmed"):
            extra_value = calibration.get(extra_key)
            if isinstance(extra_value, dict):
                coordinate_validation[extra_key] = deepcopy(extra_value)
            elif isinstance(extra_value, int) and extra_value > 0:
                coordinate_validation[extra_key] = extra_value
        localized_regions.append(
            {
                **deepcopy(region),
                "contract_version": "learn_stage1_localized_structure_region_v1",
                "rough_bbox": deepcopy(rough_bbox or {}),
                "precise_bbox": precise_bbox,
                "bbox": precise_bbox,
                "stage": "stage1_whole_region_localization",
                "source": "stage1_structure_region_geometry",
                "bbox_policy": "whole_structure_region_precise_bbox_hint_can_be_replaced_by_model",
                "locator_task": {
                    "contract_version": "learn_stage1_region_locator_task_v1",
                    "target_scope": "whole_structure_region",
                    "target_region_id": region_id,
                    "target_label": label,
                    "target_description": f"Locate the full visible boundary of the {label} area.",
                    "expected_output": "tight bbox for the whole region in full screenshot coordinates",
                    "must_include": "all visible children belonging to this structure region",
                    "must_exclude": "neighboring structure regions and unrelated browser chrome",
                    "display_only": True,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "coordinate_validation": coordinate_validation,
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    localized_regions, surface_conflict_resolution = _resolve_stage1_surface_conflicts(
        localized_regions,
        items_by_id=all_items,
        app_name=app_name,
    )
    localized_regions, structure_recovery = _recover_stage1_left_sidebar_from_list_container(
        localized_regions,
        items_by_id=all_items,
        screen_size=screen,
    )
    _align_vertical_sibling_lanes_to_main_rough_bounds(localized_regions)
    _record_horizontal_bar_content_lane(localized_regions, screen_size=screen)
    _clamp_topbar_against_main_regions(localized_regions)
    _clamp_topbar_against_adjacent_sidebar_start(localized_regions)
    _clamp_browser_chrome_against_page_topbar(localized_regions)
    _partition_nested_page_topbar_below_browser_chrome(localized_regions)
    _partition_sidebars_against_horizontal_bars(localized_regions)
    _expand_main_regions_to_available_lane(localized_regions, screen_size=screen)
    _clamp_main_regions_against_sidebars(localized_regions)
    _extend_browser_page_header_to_primary_boundary(localized_regions, items_by_id=all_items, screen_size=screen)
    _ensure_browser_right_edge_review_region(
        localized_regions,
        items_by_id=all_items,
        screen_size=screen,
        app_name=app_name,
    )
    localized_regions, merged_same_family = _merge_overlapping_same_family_structure_regions(localized_regions)
    localized_regions, suppressed_duplicates = _suppress_contained_duplicate_structure_regions(localized_regions)
    localized_regions = _recover_shallow_fullscreen_main_partition(
        localized_regions,
        screen_size=screen,
        boundary_evidence_items=boundary_evidence_items,
    )
    return {
        "contract_version": "learn_stage1_region_localization_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "localized_region_count": len(localized_regions),
        "merged_same_family_region_count": len(merged_same_family),
        "merged_same_family_regions": merged_same_family,
        "suppressed_duplicate_region_count": len(suppressed_duplicates),
        "suppressed_duplicate_regions": suppressed_duplicates,
        "surface_conflict_resolution": surface_conflict_resolution,
        "structure_recovery": structure_recovery,
        "regions": localized_regions,
        "model_prompt": STAGE1_REGION_LOCALIZATION_PROMPT,
        "model_prompt_intent": (
            "For each coarse structure region, precisely localize the full visible region boundary before per-region numbering."
        ),
    }


def _resolve_stage1_surface_conflicts(
    localized_regions: list[dict[str, Any]],
    *,
    items_by_id: dict[str, dict[str, Any]],
    app_name: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    browser_surface = _is_browser_app_name(app_name)
    kept: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    main_boxes = [
        box
        for candidate in localized_regions
        for box in [_bbox(candidate.get("bbox") or candidate.get("precise_bbox"))]
        if box and _stage1_region_family(candidate) == "main_content"
    ]
    for region in localized_regions:
        region_id = str(region.get("region_id") or "")
        region_items = [
            items_by_id[item_id]
            for item_id in region.get("item_ids", [])
            if item_id in items_by_id and isinstance(items_by_id[item_id], dict)
        ]
        if (
            _stage1_region_family(region) == "left_bar"
            and region_items
            and not _items_have_sidebar_structure_evidence(region_items)
            and not _region_covers_left_edge_main_lane(region, main_boxes=main_boxes)
        ):
            suppressed.append(
                {
                    "contract_version": "learn_stage1_surface_conflict_resolution_v1",
                    "region_id": region_id,
                    "reason": "text_only_column_without_sidebar_structure_evidence",
                    "app_name": app_name,
                    "bbox": deepcopy(_bbox(region.get("bbox") or region.get("precise_bbox")) or {}),
                    "display_only": True,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                }
            )
            continue
        if "browser_chrome" not in region_id.casefold():
            kept.append(region)
            continue
        hard_evidence = _items_have_browser_chrome_hard_evidence(region_items)
        if browser_surface or hard_evidence:
            kept.append(region)
            continue
        if not str(app_name or "").strip():
            review_region = deepcopy(region)
            review_region["surface_classification"] = {
                "status": "unknown_app_review_required",
                "reason": "app_name_missing_browser_chrome_not_suppressed",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
            kept.append(review_region)
            continue
        suppressed.append(
            {
                "contract_version": "learn_stage1_surface_conflict_resolution_v1",
                "region_id": region_id,
                "reason": "native_surface_without_browser_chrome_hard_evidence",
                "app_name": app_name,
                "browser_surface": False,
                "hard_evidence": False,
                "bbox": deepcopy(_bbox(region.get("bbox") or region.get("precise_bbox")) or {}),
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    return kept, {
        "contract_version": "learn_stage1_surface_conflict_resolution_v1",
        "app_name": app_name,
        "browser_surface": browser_surface,
        "suppressed_region_count": len(suppressed),
        "suppressed_regions": suppressed,
        "policy": (
            "Browser chrome on a known native surface requires address/URL hard evidence; "
            "when app identity is unavailable the explicit region is retained for review; "
            "a text-only column requires structural sidebar evidence before becoming a top-level sidebar."
        ),
    }


def _is_browser_app_name(app_name: str) -> bool:
    value = str(app_name or "").casefold()
    known_browser_tokens = ("msedge", "chrome", "chromium", "firefox", "brave", "opera", "vivaldi", "safari")
    if any(token in value for token in known_browser_tokens):
        return True
    normalized = " ".join(value.replace("_", " ").replace("-", " ").split())
    if "file browser" in normalized or "file explorer" in normalized:
        return False
    words = set(normalized.split())
    return "browser" in words and (
        words == {"browser"} or bool(words.intersection({"web", "window", "surface", "host"}))
    )


def _items_have_browser_chrome_hard_evidence(items: list[dict[str, Any]]) -> bool:
    for item in items:
        value = " ".join(
            str(item.get(key) or "").casefold()
            for key in ("item_id", "role", "item_type", "label", "text")
        )
        if any(token in value for token in ("address_bar", "omnibox", "http://", "https://", "www.")):
            return True
    return False


def _items_have_sidebar_structure_evidence(items: list[dict[str, Any]]) -> bool:
    for item in items:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        metadata_zone = str(metadata.get("surface_zone") or metadata.get("zone") or "").casefold()
        zone_evidence = str(metadata.get("zone_evidence") or "").casefold()
        if metadata_zone in {"left_nav", "left_sidebar", "right_nav", "right_sidebar"} and zone_evidence != "geometry_hint_only":
            return True
        value = " ".join(
            str(item.get(key) or "").casefold()
            for key in ("role", "item_type", "source")
        )
        if any(
            token in value
            for token in (
                "nav",
                "sidebar",
                "rail",
                "list",
                "tree",
                "menu",
                "tab",
                "button",
                "control",
                "link",
                "conversation",
            )
        ):
            return True
    return False


def _region_covers_left_edge_main_lane(
    region: dict[str, Any],
    *,
    main_boxes: list[dict[str, int]],
) -> bool:
    bbox = _bbox(region.get("bbox") or region.get("precise_bbox"))
    if not bbox or not main_boxes:
        return False
    main = max(main_boxes, key=lambda box: box["w"] * box["h"])
    x_tolerance = max(24, int(main["w"] * 0.03))
    y_tolerance = max(24, int(main["h"] * 0.05))
    return (
        bbox["x"] <= main["x"] + x_tolerance
        and bbox["y"] <= main["y"] + y_tolerance
        and bbox["y"] + bbox["h"] >= main["y"] + main["h"] - y_tolerance
    )


def _recover_stage1_left_sidebar_from_list_container(
    localized_regions: list[dict[str, Any]],
    *,
    items_by_id: dict[str, dict[str, Any]],
    screen_size: dict[str, int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if any(_stage1_region_family(region) == "left_bar" for region in localized_regions):
        return localized_regions, _stage1_structure_recovery_report([])
    width = _int(screen_size.get("width"))
    height = _int(screen_size.get("height"))
    main_candidates = [
        region
        for region in localized_regions
        if _stage1_region_family(region) == "main_content" and _bbox(region.get("bbox") or region.get("precise_bbox"))
    ]
    if width <= 0 or height <= 0 or not main_candidates:
        return localized_regions, _stage1_structure_recovery_report([])
    main_region = max(
        main_candidates,
        key=lambda region: (_bbox(region.get("bbox") or region.get("precise_bbox")) or {"w": 0, "h": 0})["w"],
    )
    main_bbox = _bbox(main_region.get("bbox") or main_region.get("precise_bbox"))
    if not main_bbox or main_bbox["x"] > max(20, int(width * 0.03)) or main_bbox["w"] < int(width * 0.7):
        return localized_regions, _stage1_structure_recovery_report([])
    item_ids = main_region.get("item_ids") if isinstance(main_region.get("item_ids"), list) else []
    list_candidates: list[tuple[dict[str, Any], dict[str, int]]] = []
    for item_id in item_ids:
        item = items_by_id.get(str(item_id))
        bbox = _bbox(item.get("bbox")) if isinstance(item, dict) else None
        role = str(item.get("role") or "").casefold() if isinstance(item, dict) else ""
        if not bbox or role != "list":
            continue
        if bbox["x"] > main_bbox["x"] + max(24, int(width * 0.03)):
            continue
        if bbox["w"] < int(width * 0.08) or bbox["w"] > int(width * 0.45):
            continue
        if bbox["h"] < int(height * 0.25):
            continue
        child_count = sum(
            1
            for child_id in item_ids
            for child in [items_by_id.get(str(child_id))]
            for child_bbox in [_bbox(child.get("bbox")) if isinstance(child, dict) else None]
            if child_bbox
            and str(child.get("role") or "").casefold() in {"listitem", "menu item", "menu_item"}
            and _bbox_containment_ratio(child_bbox, bbox) >= 0.8
        )
        if child_count >= 3:
            list_candidates.append((item, bbox))
    if not list_candidates:
        return localized_regions, _stage1_structure_recovery_report([])
    list_item, list_bbox = max(list_candidates, key=lambda entry: entry[1]["w"] * entry[1]["h"])
    sidebar_right = list_bbox["x"] + list_bbox["w"]
    if sidebar_right <= main_bbox["x"] + 80 or sidebar_right >= main_bbox["x"] + int(main_bbox["w"] * 0.48):
        return localized_regions, _stage1_structure_recovery_report([])
    sidebar_bbox = {
        "x": main_bbox["x"],
        "y": main_bbox["y"],
        "w": sidebar_right - main_bbox["x"],
        "h": main_bbox["h"],
    }
    owned_item_ids: list[str] = []
    for item_id in item_ids:
        item = items_by_id.get(str(item_id))
        item_bbox = _bbox(item.get("bbox")) if isinstance(item, dict) else None
        if not item_bbox:
            continue
        center_x = item_bbox["x"] + item_bbox["w"] / 2
        if center_x <= sidebar_right and _bbox_containment_ratio(item_bbox, sidebar_bbox) >= 0.75:
            owned_item_ids.append(str(item_id))
    main_item_ids = [str(item_id) for item_id in item_ids if str(item_id) not in set(owned_item_ids)]
    resolved: list[dict[str, Any]] = []
    for region in localized_regions:
        if region is not main_region:
            resolved.append(region)
            continue
        updated_main = deepcopy(region)
        updated_main_bbox = {
            "x": sidebar_right,
            "y": main_bbox["y"],
            "w": main_bbox["x"] + main_bbox["w"] - sidebar_right,
            "h": main_bbox["h"],
        }
        updated_main["bbox"] = deepcopy(updated_main_bbox)
        updated_main["precise_bbox"] = deepcopy(updated_main_bbox)
        updated_main["item_ids"] = main_item_ids
        updated_main["item_count"] = len(main_item_ids)
        updated_main["ownership_resolution"] = "left_list_container_items_reassigned_to_recovered_sidebar"
        resolved.append(updated_main)
    recovered_region = {
        "contract_version": "learn_stage1_localized_structure_region_v1",
        "region_id": "structure_region_recovered_left_sidebar",
        "zone_id": "left_sidebar",
        "label": "Left navigation/list sidebar",
        "role": "left_sidebar",
        "bbox": deepcopy(sidebar_bbox),
        "precise_bbox": deepcopy(sidebar_bbox),
        "rough_bbox": deepcopy(list_bbox),
        "item_ids": owned_item_ids,
        "item_count": len(owned_item_ids),
        "stage": "stage1_whole_region_localization",
        "source": "vertical_list_container_ownership_recovery",
        "bbox_policy": "whole_structure_region_recovered_from_owned_vertical_list_container",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    resolved.append(recovered_region)
    event = {
        "contract_version": "learn_stage1_structure_recovery_v1",
        "region_id": recovered_region["region_id"],
        "source_item_id": str(list_item.get("item_id") or ""),
        "reason": "owned_vertical_list_container_with_repeated_list_items",
        "bbox": deepcopy(sidebar_bbox),
        "owned_item_count": len(owned_item_ids),
    }
    resolved.sort(key=lambda item: (_bbox_top(item), _bbox_left(item), str(item.get("region_id") or "")))
    return resolved, _stage1_structure_recovery_report([event])


def _stage1_structure_recovery_report(events: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "contract_version": "learn_stage1_structure_recovery_v1",
        "recovered_region_count": len(events),
        "recovered_regions": events,
        "policy": "Recover a missing sidebar only from a bounded vertical list container with repeated owned list items.",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _align_vertical_sibling_lanes_to_main_rough_bounds(localized_regions: list[dict[str, Any]]) -> None:
    main_region = next(
        (region for region in localized_regions if _stage1_region_family(region) == "main_content"),
        None,
    )
    side_regions = [
        region
        for region in localized_regions
        if _stage1_region_family(region) in {"left_bar", "right_bar"}
    ]
    side_families = {_stage1_region_family(region) for region in side_regions}
    main_rough = _bbox(main_region.get("rough_bbox")) if isinstance(main_region, dict) else None
    if not main_region or not main_rough or side_families != {"left_bar", "right_bar"}:
        return
    shared_y = main_rough["y"]
    shared_h = main_rough["h"]
    source_region_id = str(main_region.get("region_id") or "")
    left_regions = [region for region in side_regions if _stage1_region_family(region) == "left_bar"]
    right_regions = [region for region in side_regions if _stage1_region_family(region) == "right_bar"]
    all_boxes = [
        bbox
        for region in localized_regions
        for bbox in [_bbox(region.get("rough_bbox")) or _bbox(region.get("bbox") or region.get("precise_bbox"))]
        if bbox
    ]
    screen_left = min((bbox["x"] for bbox in all_boxes), default=0)
    screen_right = max((bbox["x"] + bbox["w"] for bbox in all_boxes), default=main_rough["x"] + main_rough["w"])
    left_right = max(
        (
            bbox["x"] + bbox["w"]
            for region in left_regions
            for bbox in [_bbox(region.get("bbox") or region.get("precise_bbox"))]
            if bbox
        ),
        default=main_rough["x"],
    )
    right_left = min(
        (
            bbox["x"]
            for region in right_regions
            for bbox in [_bbox(region.get("bbox") or region.get("precise_bbox"))]
            if bbox
        ),
        default=main_rough["x"] + main_rough["w"],
    )
    for region in [main_region, *side_regions]:
        bbox = _bbox(region.get("bbox") or region.get("precise_bbox"))
        if not bbox:
            continue
        aligned = {**bbox, "y": shared_y, "h": shared_h}
        family = _stage1_region_family(region)
        if family == "left_bar":
            aligned.update({"x": screen_left, "w": max(1, left_right - screen_left)})
        elif family == "right_bar":
            aligned.update({"x": right_left, "w": max(1, screen_right - right_left)})
        elif family == "main_content":
            aligned.update({"x": left_right, "w": max(1, right_left - left_right)})
        region["bbox"] = deepcopy(aligned)
        region["precise_bbox"] = deepcopy(aligned)
        validation = region.get("coordinate_validation") if isinstance(region.get("coordinate_validation"), dict) else {}
        validation = deepcopy(validation)
        validation["shared_vertical_lane"] = {
            "contract_version": "learn_stage1_shared_vertical_lane_v1",
            "source_region_id": source_region_id,
            "previous_bbox": deepcopy(bbox),
            "aligned_bbox": deepcopy(aligned),
            "reason": "parallel_lanes_inherit_main_rough_vertical_bounds_including_empty_area",
            "policy": "parallel_structure_lanes_share_top_and_bottom_boundaries",
        }
        region["coordinate_validation"] = validation


def _recover_shallow_fullscreen_main_partition(
    localized_regions: list[dict[str, Any]],
    *,
    screen_size: dict[str, int],
    boundary_evidence_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    if len(localized_regions) != 1:
        return localized_regions
    width = _int(screen_size.get("width"))
    height = _int(screen_size.get("height"))
    region = localized_regions[0]
    bbox = _bbox(region.get("bbox"))
    rough_bbox = _bbox(region.get("rough_bbox"))
    if (
        width <= 0
        or height <= 0
        or _stage1_region_family(region) != "main_content"
        or not bbox
        or not rough_bbox
        or bbox["x"] > max(12, int(width * 0.02))
        or bbox["y"] > max(12, int(height * 0.02))
        or bbox["x"] + bbox["w"] < width - max(12, int(width * 0.02))
        or bbox["y"] + bbox["h"] < height - max(12, int(height * 0.02))
        or rough_bbox["h"] >= int(height * 0.35)
        or rough_bbox["y"] + rough_bbox["h"] > int(height * 0.35)
    ):
        return localized_regions
    rough_split_y = min(height - 1, max(1, rough_bbox["y"] + rough_bbox["h"]))
    boundary_recovery = _reliable_horizontal_control_row_boundary(
        boundary_evidence_items or [],
        width=width,
        height=height,
        rough_split_y=rough_split_y,
    )
    split_y = int(boundary_recovery.get("split_y") or rough_split_y)
    validation = deepcopy(region.get("coordinate_validation")) if isinstance(region.get("coordinate_validation"), dict) else {}
    if boundary_recovery.get("source") == "repeated_horizontal_control_row":
        validation.update(
            {
                "status": "heuristic_recovered_from_repeated_horizontal_control_row",
                "evidence": "OCR-aligned repeated horizontal controls define the header/main boundary",
                "calibration_strategy": "shallow_fullscreen_repeated_horizontal_control_row_boundary",
            }
        )
    header = deepcopy(region)
    header.update(
        {
            "region_no": 1,
            "region_id": "structure_region_page_header",
            "zone_id": "page_header",
            "label": "Top/header area",
            "bbox": {"x": 0, "y": 0, "w": width, "h": split_y},
            "precise_bbox": {"x": 0, "y": 0, "w": width, "h": split_y},
            "recovered_from_shallow_fullscreen_main": True,
            "coordinate_validation": deepcopy(validation),
            "boundary_recovery": deepcopy(boundary_recovery),
        }
    )
    header["locator_task"] = {
        **deepcopy(header.get("locator_task") or {}),
        "target_region_id": "structure_region_page_header",
        "target_label": "Top/header area",
        "target_description": "Locate the full visible boundary of the Top/header area.",
    }
    main = deepcopy(region)
    main.update(
        {
            "region_no": 2,
            "region_id": "structure_region_main_content",
            "zone_id": "main_content",
            "label": "Main content",
            "item_ids": [],
            "item_count": 0,
            "rough_bbox": {},
            "bbox": {"x": 0, "y": split_y, "w": width, "h": height - split_y},
            "precise_bbox": {"x": 0, "y": split_y, "w": width, "h": height - split_y},
            "recovered_from_shallow_fullscreen_main": True,
            "coordinate_validation": deepcopy(validation),
            "boundary_recovery": deepcopy(boundary_recovery),
        }
    )
    main["locator_task"] = {
        **deepcopy(main.get("locator_task") or {}),
        "target_region_id": "structure_region_main_content",
        "target_label": "Main content",
        "target_description": "Locate the full visible boundary of the Main content area.",
    }
    return [header, main]


def _reliable_horizontal_control_row_boundary(
    items: list[dict[str, Any]],
    *,
    width: int,
    height: int,
    rough_split_y: int,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for item in items:
        bbox = _bbox(item.get("bbox"))
        source = str(item.get("source") or "").casefold()
        source_evidence = {str(value).casefold() for value in item.get("source_evidence", [])}
        label = str(item.get("label") or item.get("text") or "").strip()
        if (
            not bbox
            or ("ocr" not in source and "ocr" not in source_evidence)
            or not label
            or len(label) > 40
            or bbox["h"] > max(48, int(height * 0.05))
            or bbox["y"] + bbox["h"] >= rough_split_y
        ):
            continue
        candidates.append(item)

    rows: list[list[dict[str, Any]]] = []
    for item in sorted(candidates, key=lambda entry: (_bbox_top(entry), _bbox_left(entry))):
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            continue
        center_y = bbox["y"] + bbox["h"] / 2
        row = next(
            (
                existing
                for existing in rows
                if abs(
                    ((_bbox(existing[0].get("bbox")) or {})["y"] + (_bbox(existing[0].get("bbox")) or {})["h"] / 2)
                    - center_y
                )
                <= 14
            ),
            None,
        )
        if row is None:
            rows.append([item])
        else:
            row.append(item)

    reliable_rows: list[tuple[int, list[dict[str, Any]], dict[str, int]]] = []
    for row in rows:
        boxes = [_bbox(item.get("bbox")) for item in row]
        boxes = [bbox for bbox in boxes if bbox]
        union = _bbox_union(boxes)
        if len(boxes) < 3 or not union or union["w"] < max(300, int(width * 0.20)):
            continue
        split_y = min(height - 1, max(1, max(box["y"] + box["h"] for box in boxes) + 10))
        reliable_rows.append((split_y, row, union))
    if not reliable_rows:
        return {
            "source": "rough_region_bottom",
            "split_y": rough_split_y,
            "reason": "no_reliable_repeated_horizontal_control_row",
        }
    split_y, row, union = max(reliable_rows, key=lambda value: value[0])
    return {
        "source": "repeated_horizontal_control_row",
        "split_y": split_y,
        "rough_split_y": rough_split_y,
        "row_bbox": union,
        "row_item_ids": [str(item.get("item_id") or "") for item in row],
        "reason": "last_reliable_ocr_aligned_control_row_before_shallow_rough_boundary",
    }


def _record_horizontal_bar_content_lane(
    localized_regions: list[dict[str, Any]],
    *,
    screen_size: dict[str, Any],
) -> None:
    width = _int(screen_size.get("width"))
    if width <= 0:
        return
    left_boxes = [
        _bbox(region.get("bbox") or region.get("precise_bbox"))
        for region in localized_regions
        if _stage1_region_family(region) == "left_bar"
    ]
    right_boxes = [
        _bbox(region.get("bbox") or region.get("precise_bbox"))
        for region in localized_regions
        if _stage1_region_family(region) == "right_bar"
    ]
    left_boxes = [box for box in left_boxes if box]
    right_boxes = [box for box in right_boxes if box]
    left_boundary = max((box["x"] + box["w"] for box in left_boxes), default=0)
    right_boundary = min((box["x"] for box in right_boxes), default=width)
    if right_boundary <= left_boundary:
        return
    for region in localized_regions:
        family = _stage1_region_family(region)
        if family not in {"top_bar", "bottom_bar"}:
            continue
        region_id = str(region.get("region_id") or "").casefold()
        if "browser_chrome" in region_id:
            continue
        bbox = _bbox(region.get("bbox") or region.get("precise_bbox"))
        if not bbox:
            continue
        validation = region.get("coordinate_validation") if isinstance(region.get("coordinate_validation"), dict) else {}
        validation = deepcopy(validation)
        validation["sibling_lane"] = {
            "contract_version": "learn_stage1_sibling_region_partition_v1",
            "reason": "horizontal_bar_full_bbox_preserved_non_sidebar_lane_recorded",
            "left_boundary": left_boundary,
            "right_boundary": right_boundary,
            "lane_bbox": {**bbox, "x": left_boundary, "w": max(1, right_boundary - left_boundary)},
            "previous_bbox": deepcopy(bbox),
            "preserved_bbox": deepcopy(bbox),
            "policy": "structure_regions_may_touch_but_must_not_overlap_unless_parent_child",
        }
        region["coordinate_validation"] = validation


def _partition_sidebars_against_horizontal_bars(localized_regions: list[dict[str, Any]]) -> None:
    top_boxes = [
        _bbox(region.get("bbox") or region.get("precise_bbox"))
        for region in localized_regions
        if _stage1_region_family(region) == "top_bar"
    ]
    bottom_boxes = [
        _bbox(region.get("bbox") or region.get("precise_bbox"))
        for region in localized_regions
        if _stage1_region_family(region) == "bottom_bar"
    ]
    top_boxes = [box for box in top_boxes if box]
    bottom_boxes = [box for box in bottom_boxes if box]
    top_boundary = max((box["y"] + box["h"] for box in top_boxes), default=None)
    bottom_boundary = min((box["y"] for box in bottom_boxes), default=None)
    if top_boundary is None and bottom_boundary is None:
        return
    for region in localized_regions:
        if _stage1_region_family(region) not in {"left_bar", "right_bar"}:
            continue
        bbox = _bbox(region.get("bbox") or region.get("precise_bbox"))
        if not bbox:
            continue
        y1 = bbox["y"]
        y2 = bbox["y"] + bbox["h"]
        if top_boundary is not None and y1 < top_boundary < y2:
            y1 = top_boundary
        if bottom_boundary is not None and y1 < bottom_boundary < y2:
            y2 = bottom_boundary
        partitioned = {**bbox, "y": y1, "h": max(1, y2 - y1)}
        if partitioned == bbox:
            continue
        region["bbox"] = deepcopy(partitioned)
        region["precise_bbox"] = deepcopy(partitioned)
        validation = region.get("coordinate_validation") if isinstance(region.get("coordinate_validation"), dict) else {}
        validation = deepcopy(validation)
        validation["sibling_partition"] = {
            "contract_version": "learn_stage1_sibling_region_partition_v1",
            "reason": "sidebar_must_use_non_horizontal_bar_lane",
            "top_boundary": top_boundary,
            "bottom_boundary": bottom_boundary,
            "previous_bbox": deepcopy(bbox),
            "partitioned_bbox": deepcopy(partitioned),
            "policy": "structure_regions_may_touch_but_must_not_overlap_unless_parent_child",
        }
        region["coordinate_validation"] = validation


def _clamp_topbar_against_adjacent_sidebar_start(localized_regions: list[dict[str, Any]]) -> None:
    sidebar_starts = [
        rough["y"]
        for region in localized_regions
        if _stage1_region_family(region) in {"left_bar", "right_bar"}
        if (rough := _bbox(region.get("rough_bbox"))) is not None
        and rough["y"] > 0
    ]
    if not sidebar_starts:
        return
    for region in localized_regions:
        if _stage1_region_family(region) != "top_bar":
            continue
        bbox = _bbox(region.get("bbox") or region.get("precise_bbox"))
        rough = _bbox(region.get("rough_bbox"))
        if not bbox or not rough:
            continue
        rough_bottom = rough["y"] + rough["h"]
        tolerance = max(1, int(round(rough["h"] * 0.25)))
        adjacent_starts = [
            start
            for start in sidebar_starts
            if start > bbox["y"] and abs(start - rough_bottom) <= tolerance
        ]
        if not adjacent_starts:
            continue
        boundary = min(adjacent_starts)
        if bbox["y"] + bbox["h"] <= boundary:
            continue
        clamped = {**bbox, "h": max(1, boundary - bbox["y"])}
        region["bbox"] = deepcopy(clamped)
        region["precise_bbox"] = deepcopy(clamped)
        validation = region.get("coordinate_validation") if isinstance(region.get("coordinate_validation"), dict) else {}
        validation = deepcopy(validation)
        validation["adjacent_sidebar_clamp"] = {
            "contract_version": "learn_stage1_adjacent_sidebar_boundary_v1",
            "reason": "adjacent_sidebar_rough_start_prevents_expanded_topbar_from_absorbing_sidebar_items",
            "sidebar_top_boundary": boundary,
            "topbar_rough_bottom": rough_bottom,
            "previous_bbox": deepcopy(bbox),
            "clamped_bbox": deepcopy(clamped),
            "policy": "adjacent_structure_regions_may_touch_but_must_not_overlap",
        }
        region["coordinate_validation"] = validation


def _expand_main_regions_to_available_lane(
    localized_regions: list[dict[str, Any]],
    *,
    screen_size: dict[str, Any],
) -> None:
    width = _int(screen_size.get("width"))
    height = _int(screen_size.get("height"))
    if width <= 0 or height <= 0:
        return
    left_boundary = max(
        (
            box["x"] + box["w"]
            for region in localized_regions
            if _stage1_region_family(region) == "left_bar"
            for box in [_bbox(region.get("bbox") or region.get("precise_bbox"))]
            if box
        ),
        default=0,
    )
    right_boundary = min(
        (
            box["x"]
            for region in localized_regions
            if _stage1_region_family(region) == "right_bar"
            for box in [_bbox(region.get("bbox") or region.get("precise_bbox"))]
            if box
        ),
        default=width,
    )
    top_boundary = max(
        (
            box["y"] + box["h"]
            for region in localized_regions
            if _stage1_region_family(region) == "top_bar"
            for box in [_bbox(region.get("bbox") or region.get("precise_bbox"))]
            if box
        ),
        default=0,
    )
    bottom_boundary = min(
        (
            box["y"]
            for region in localized_regions
            if _stage1_region_family(region) == "bottom_bar"
            for box in [_bbox(region.get("bbox") or region.get("precise_bbox"))]
            if box
        ),
        default=height,
    )
    if right_boundary <= left_boundary or bottom_boundary <= top_boundary:
        return
    available = {
        "x": left_boundary,
        "y": top_boundary,
        "w": max(1, right_boundary - left_boundary),
        "h": max(1, bottom_boundary - top_boundary),
    }
    for region in localized_regions:
        if _stage1_region_family(region) != "main_content":
            continue
        bbox = _bbox(region.get("bbox") or region.get("precise_bbox"))
        if not bbox or bbox == available:
            continue
        region["bbox"] = deepcopy(available)
        region["precise_bbox"] = deepcopy(available)
        validation = region.get("coordinate_validation") if isinstance(region.get("coordinate_validation"), dict) else {}
        validation = deepcopy(validation)
        validation["available_lane_expansion"] = {
            "contract_version": "learn_stage1_main_content_available_lane_expansion_v1",
            "reason": "main_content_must_cover_remaining_structure_lane_including_empty_area",
            "previous_bbox": deepcopy(bbox),
            "expanded_bbox": deepcopy(available),
            "policy": "stage1_structure_regions_tile_the_visible_window_before_stage2_numbering",
        }
        preservation = validation.get("right_edge_preservation")
        if isinstance(preservation, dict):
            preservation = deepcopy(preservation)
            preserved_right = _int(preservation.get("preserved_right"))
            final_right = available["x"] + available["w"]
            if preserved_right > 0 and final_right < preserved_right:
                preservation["status"] = "main_content_right_edge_preserved_then_clamped_to_sibling_region"
                preservation["final_right"] = final_right
                preservation["clamp_reason"] = "main_content_must_not_overlap_sibling_structure_region"
                validation["right_edge_preservation"] = preservation
        region["coordinate_validation"] = validation


def _extend_browser_page_header_to_primary_boundary(
    localized_regions: list[dict[str, Any]],
    *,
    items_by_id: dict[str, dict[str, Any]],
    screen_size: dict[str, Any],
) -> None:
    height = _int(screen_size.get("height"))
    if height <= 0 or not _items_have_browser_chrome_evidence(items_by_id.values()):
        return
    main_boxes = [
        _bbox(region.get("bbox") or region.get("precise_bbox"))
        for region in localized_regions
        if _stage1_region_family(region) == "main_content"
    ]
    main_boxes = [box for box in main_boxes if box]
    if not main_boxes:
        return
    main_top = min(box["y"] for box in main_boxes)
    if main_top <= 0 or main_top > int(height * 0.40):
        return
    for region in localized_regions:
        if _stage1_region_family(region) != "top_bar":
            continue
        region_id = str(region.get("region_id") or "").casefold()
        if "browser_chrome" in region_id:
            continue
        bbox = _bbox(region.get("bbox") or region.get("precise_bbox"))
        if not bbox:
            continue
        bottom = bbox["y"] + bbox["h"]
        if bottom >= main_top:
            continue
        extended = {**bbox, "h": max(1, main_top - bbox["y"])}
        region["bbox"] = deepcopy(extended)
        region["precise_bbox"] = deepcopy(extended)
        validation = region.get("coordinate_validation") if isinstance(region.get("coordinate_validation"), dict) else {}
        validation = deepcopy(validation)
        validation["browser_page_header_extension"] = {
            "contract_version": "learn_stage1_browser_page_header_extension_v1",
            "reason": "webpage_header_controls_must_not_seed_primary_content_top",
            "main_content_top_boundary": main_top,
            "previous_bbox": deepcopy(bbox),
            "extended_bbox": deepcopy(extended),
            "policy": "browser_surface_header_may_extend_to_primary_boundary_after_header_controls_are_excluded",
        }
        region["coordinate_validation"] = validation


def _ensure_browser_right_edge_review_region(
    localized_regions: list[dict[str, Any]],
    *,
    items_by_id: dict[str, dict[str, Any]],
    screen_size: dict[str, Any],
    app_name: str,
) -> None:
    width = _int(screen_size.get("width"))
    height = _int(screen_size.get("height"))
    if width <= 0 or height <= 0 or not _items_have_browser_chrome_evidence(items_by_id.values()):
        return
    has_retained_browser_region = any(
        "browser_chrome" in str(region.get("region_id") or "").casefold()
        for region in localized_regions
    )
    if not _is_browser_app_name(app_name) and not has_retained_browser_region:
        return
    families = {_stage1_region_family(region) for region in localized_regions}
    if "right_bar" in families or any(str(region.get("zone_id") or "") == "floating_controls" for region in localized_regions):
        return
    chrome_bottom = max(
        (
            box["y"] + box["h"]
            for box in (
                _bbox(region.get("bbox") or region.get("precise_bbox"))
                for region in localized_regions
                if "browser_chrome" in str(region.get("region_id") or "").casefold()
            )
            if box
        ),
        default=_top_bar_height(height),
    )
    strip_width = max(48, min(96, int(width * 0.035)))
    bbox = {
        "x": max(0, width - strip_width),
        "y": min(height - 1, max(0, chrome_bottom)),
        "w": strip_width,
        "h": max(1, height - min(height - 1, max(0, chrome_bottom))),
    }
    region_no = len(localized_regions) + 1
    localized_regions.append(
        {
            "contract_version": "learn_stage1_localized_structure_region_v1",
            "region_no": region_no,
            "region_id": "structure_region_floating_controls",
            "label": "Floating controls / scroll review area",
            "zone_id": "floating_controls",
            "bbox": deepcopy(bbox),
            "rough_bbox": deepcopy(bbox),
            "precise_bbox": deepcopy(bbox),
            "item_ids": [],
            "item_count": 0,
            "stage": "stage1_whole_region_localization",
            "source": "browser_surface_right_edge_review_policy",
            "bbox_policy": "synthetic_browser_right_edge_overlay_review_region",
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "locator_task": {
                "contract_version": "learn_stage1_region_locator_task_v1",
                "target_scope": "whole_structure_region",
                "target_region_id": "structure_region_floating_controls",
                "target_label": "Floating controls / scroll review area",
                "target_description": "Review the browser page right edge for floating controls, scrollbars, or overlay affordances.",
                "expected_output": "right-edge review strip in full screenshot coordinates",
                "must_include": "visible right-edge floating controls and scroll affordances when present",
                "must_exclude": "central page content and browser chrome",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            "coordinate_validation": {
                "contract_version": "learn_stage1_region_coordinate_validation_v1",
                "status": "synthetic_browser_right_edge_review_strip",
                "evidence": "browser chrome exists and no explicit right sidebar/floating-control region was detected",
                "model_grounding_attempted": False,
                "semantic_model": "not_run",
                "coordinate_model": "not_run",
                "calibration_strategy": "browser_right_edge_review_strip",
                "can_be_replaced_by_model": True,
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
        }
    )


def _clamp_topbar_against_main_regions(localized_regions: list[dict[str, Any]]) -> None:
    main_regions = [
        region
        for region in localized_regions
        if _stage1_region_family(region) == "main_content"
        and _bbox(region.get("bbox") or region.get("precise_bbox"))
    ]
    if not main_regions:
        return
    for region in localized_regions:
        if _stage1_region_family(region) != "top_bar":
            continue
        bbox = _bbox(region.get("bbox") or region.get("precise_bbox"))
        if not bbox:
            continue
        overlapping_main_regions = [
            main_region
            for main_region in main_regions
            for box in [_bbox(main_region.get("bbox") or main_region.get("precise_bbox"))]
            if box
            and box["y"] > bbox["y"]
            and _horizontal_overlap_ratio(bbox, box) >= 0.20
            and bbox["y"] + bbox["h"] > box["y"]
        ]
        if not overlapping_main_regions:
            continue
        rough = _bbox(region.get("rough_bbox"))
        top_bottom = bbox["y"] + bbox["h"]
        rough_bottom = rough["y"] + rough["h"] if rough else 0
        anchored_inner_header = bool(
            rough
            and rough["y"] > bbox["y"] + 4
            and top_bottom >= rough_bottom
            and top_bottom <= rough_bottom + max(12, rough["h"])
        )
        if anchored_inner_header:
            moved_main_regions: list[dict[str, Any]] = []
            for main_region in overlapping_main_regions:
                main_bbox = _bbox(main_region.get("bbox") or main_region.get("precise_bbox"))
                if not main_bbox:
                    continue
                main_bottom = main_bbox["y"] + main_bbox["h"]
                if main_bottom <= top_bottom:
                    continue
                adjusted = {**main_bbox, "y": top_bottom, "h": max(1, main_bottom - top_bottom)}
                main_region["bbox"] = deepcopy(adjusted)
                main_region["precise_bbox"] = deepcopy(adjusted)
                main_validation = (
                    main_region.get("coordinate_validation")
                    if isinstance(main_region.get("coordinate_validation"), dict)
                    else {}
                )
                main_validation = deepcopy(main_validation)
                main_validation["sibling_partition"] = {
                    "contract_version": "learn_stage1_sibling_region_partition_v1",
                    "reason": "main_content_must_follow_anchored_header_content",
                    "header_bottom_boundary": top_bottom,
                    "previous_bbox": deepcopy(main_bbox),
                    "adjusted_bbox": deepcopy(adjusted),
                    "policy": "adjacent_structure_regions_may_touch_but_must_not_overlap",
                }
                main_region["coordinate_validation"] = main_validation
                moved_main_regions.append(
                    {
                        "region_id": main_region.get("region_id"),
                        "previous_bbox": deepcopy(main_bbox),
                        "adjusted_bbox": deepcopy(adjusted),
                    }
                )
            if moved_main_regions:
                validation = region.get("coordinate_validation") if isinstance(region.get("coordinate_validation"), dict) else {}
                validation = deepcopy(validation)
                validation["sibling_partition"] = {
                    "contract_version": "learn_stage1_sibling_region_partition_v1",
                    "reason": "anchored_header_content_must_precede_main_content",
                    "header_bottom_boundary": top_bottom,
                    "rough_header_bbox": deepcopy(rough),
                    "adjusted_main_regions": moved_main_regions,
                    "policy": "adjacent_structure_regions_may_touch_but_must_not_overlap",
                }
                region["coordinate_validation"] = validation
                continue
        shallow_overlap = all(
            (
                top_bottom
                - (_bbox(main_region.get("bbox") or main_region.get("precise_bbox")) or {"y": top_bottom})["y"]
            )
            / max(1, bbox["h"])
            <= 0.25
            for main_region in overlapping_main_regions
        )
        if shallow_overlap:
            adjusted_main_regions: list[dict[str, Any]] = []
            for main_region in overlapping_main_regions:
                main_bbox = _bbox(main_region.get("bbox") or main_region.get("precise_bbox"))
                if not main_bbox:
                    continue
                main_bottom = main_bbox["y"] + main_bbox["h"]
                if main_bottom <= top_bottom:
                    continue
                adjusted = {**main_bbox, "y": top_bottom, "h": max(1, main_bottom - top_bottom)}
                main_region["bbox"] = deepcopy(adjusted)
                main_region["precise_bbox"] = deepcopy(adjusted)
                main_validation = (
                    main_region.get("coordinate_validation")
                    if isinstance(main_region.get("coordinate_validation"), dict)
                    else {}
                )
                main_validation = deepcopy(main_validation)
                main_validation["sibling_partition"] = {
                    "contract_version": "learn_stage1_sibling_region_partition_v1",
                    "reason": "main_content_must_follow_shallow_overlapping_horizontal_bar",
                    "header_bottom_boundary": top_bottom,
                    "previous_bbox": deepcopy(main_bbox),
                    "adjusted_bbox": deepcopy(adjusted),
                    "policy": "shallow_structure_overlap_preserves_complete_horizontal_bar",
                }
                main_region["coordinate_validation"] = main_validation
                adjusted_main_regions.append(
                    {
                        "region_id": main_region.get("region_id"),
                        "previous_bbox": deepcopy(main_bbox),
                        "adjusted_bbox": deepcopy(adjusted),
                    }
                )
            if adjusted_main_regions:
                validation = region.get("coordinate_validation") if isinstance(region.get("coordinate_validation"), dict) else {}
                validation = deepcopy(validation)
                validation["sibling_partition"] = {
                    "contract_version": "learn_stage1_sibling_region_partition_v1",
                    "reason": "complete_horizontal_bar_wins_shallow_main_overlap",
                    "header_bottom_boundary": top_bottom,
                    "adjusted_main_regions": adjusted_main_regions,
                    "policy": "shallow_structure_overlap_preserves_complete_horizontal_bar",
                }
                region["coordinate_validation"] = validation
                continue
        overlapping_main_tops = [
            box["y"]
            for main_region in overlapping_main_regions
            for box in [_bbox(main_region.get("bbox") or main_region.get("precise_bbox"))]
            if box
        ]
        boundary = min(overlapping_main_tops)
        clamped = {**bbox, "h": max(1, boundary - bbox["y"])}
        if clamped == bbox:
            continue
        region["bbox"] = deepcopy(clamped)
        region["precise_bbox"] = deepcopy(clamped)
        validation = region.get("coordinate_validation") if isinstance(region.get("coordinate_validation"), dict) else {}
        validation = deepcopy(validation)
        validation["sibling_clamp"] = {
            "contract_version": "learn_stage1_sibling_region_clamp_v1",
            "reason": "top_bar_must_not_overlap_main_content",
            "main_content_top_boundary": boundary,
            "previous_bbox": deepcopy(bbox),
            "clamped_bbox": deepcopy(clamped),
            "policy": "adjacent_structure_regions_may_touch_but_must_not_overlap",
        }
        region["coordinate_validation"] = validation


def _clamp_browser_chrome_against_page_topbar(localized_regions: list[dict[str, Any]]) -> None:
    top_boundaries = [
        box["y"]
        for region in localized_regions
        for box in [_bbox(region.get("bbox") or region.get("precise_bbox"))]
        if box
        and _stage1_region_family(region) == "top_bar"
        and "browser_chrome" not in str(region.get("region_id") or "").casefold()
        and box["y"] > 0
    ]
    if not top_boundaries:
        return
    boundary = min(top_boundaries)
    for region in localized_regions:
        if "browser_chrome" not in str(region.get("region_id") or "").casefold():
            continue
        bbox = _bbox(region.get("bbox") or region.get("precise_bbox"))
        if not bbox or bbox["y"] >= boundary or bbox["y"] + bbox["h"] <= boundary:
            continue
        clamped = {**bbox, "h": max(1, boundary - bbox["y"])}
        region["bbox"] = deepcopy(clamped)
        region["precise_bbox"] = deepcopy(clamped)
        validation = region.get("coordinate_validation") if isinstance(region.get("coordinate_validation"), dict) else {}
        validation = deepcopy(validation)
        validation["browser_chrome_page_header_clamp"] = {
            "contract_version": "learn_stage1_sibling_region_clamp_v1",
            "reason": "browser_chrome_must_not_overlap_page_top_header",
            "page_topbar_boundary": boundary,
            "previous_bbox": deepcopy(bbox),
            "clamped_bbox": deepcopy(clamped),
            "policy": "adjacent_structure_regions_may_touch_but_must_not_overlap",
        }
        region["coordinate_validation"] = validation


def _partition_nested_page_topbar_below_browser_chrome(localized_regions: list[dict[str, Any]]) -> None:
    browser_regions = [
        region
        for region in localized_regions
        if "browser_chrome" in str(region.get("region_id") or "").casefold()
    ]
    page_topbars = [
        region
        for region in localized_regions
        if _stage1_region_family(region) == "top_bar"
        and "browser_chrome" not in str(region.get("region_id") or "").casefold()
    ]
    for browser_region in browser_regions:
        browser_bbox = _bbox(browser_region.get("bbox") or browser_region.get("precise_bbox"))
        if not browser_bbox:
            continue
        browser_bottom = browser_bbox["y"] + browser_bbox["h"]
        for page_topbar in page_topbars:
            topbar_bbox = _bbox(page_topbar.get("bbox") or page_topbar.get("precise_bbox"))
            if not topbar_bbox:
                continue
            topbar_bottom = topbar_bbox["y"] + topbar_bbox["h"]
            horizontal_overlap = max(
                0,
                min(browser_bbox["x"] + browser_bbox["w"], topbar_bbox["x"] + topbar_bbox["w"])
                - max(browser_bbox["x"], topbar_bbox["x"]),
            )
            overlap_ratio = horizontal_overlap / max(1, min(browser_bbox["w"], topbar_bbox["w"]))
            same_top_origin = abs(topbar_bbox["y"] - browser_bbox["y"]) <= max(8, int(browser_bbox["h"] * 0.2))
            has_distinct_page_lane = topbar_bottom - browser_bottom >= 24
            if overlap_ratio < 0.8 or not same_top_origin or not has_distinct_page_lane:
                continue
            partitioned = {
                **topbar_bbox,
                "y": browser_bottom,
                "h": topbar_bottom - browser_bottom,
            }
            page_topbar["bbox"] = deepcopy(partitioned)
            page_topbar["precise_bbox"] = deepcopy(partitioned)
            validation = (
                page_topbar.get("coordinate_validation")
                if isinstance(page_topbar.get("coordinate_validation"), dict)
                else {}
            )
            validation = deepcopy(validation)
            validation["browser_chrome_page_header_partition"] = {
                "contract_version": "learn_stage1_sibling_region_partition_v1",
                "reason": "page_topbar_contained_browser_chrome_from_same_top_origin",
                "browser_chrome_bottom_boundary": browser_bottom,
                "previous_bbox": deepcopy(topbar_bbox),
                "partitioned_bbox": deepcopy(partitioned),
                "policy": "adjacent_top_structure_regions_may_touch_but_must_not_overlap",
            }
            page_topbar["coordinate_validation"] = validation


def _clamp_main_regions_against_sidebars(localized_regions: list[dict[str, Any]]) -> None:
    right_sidebar_boxes = [
        _bbox(region.get("bbox") or region.get("precise_bbox"))
        for region in localized_regions
        if _stage1_region_family(region) == "right_bar"
    ]
    right_sidebar_boxes = [box for box in right_sidebar_boxes if box]
    if not right_sidebar_boxes:
        return
    right_boundary = min(box["x"] for box in right_sidebar_boxes)
    for region in localized_regions:
        if _stage1_region_family(region) != "main_content":
            continue
        bbox = _bbox(region.get("bbox") or region.get("precise_bbox"))
        if not bbox or bbox["x"] >= right_boundary:
            continue
        current_right = bbox["x"] + bbox["w"]
        if current_right <= right_boundary:
            continue
        clamped = {**bbox, "w": max(1, right_boundary - bbox["x"])}
        region["bbox"] = deepcopy(clamped)
        region["precise_bbox"] = deepcopy(clamped)
        validation = region.get("coordinate_validation") if isinstance(region.get("coordinate_validation"), dict) else {}
        validation = deepcopy(validation)
        validation["sibling_clamp"] = {
            "contract_version": "learn_stage1_sibling_region_clamp_v1",
            "reason": "main_content_must_not_overlap_right_sidebar",
            "right_boundary": right_boundary,
            "previous_bbox": deepcopy(bbox),
            "clamped_bbox": deepcopy(clamped),
        }
        preservation = validation.get("right_edge_preservation")
        if isinstance(preservation, dict):
            preservation = deepcopy(preservation)
            preservation["status"] = "main_content_right_edge_preserved_then_clamped_to_sibling_region"
            preservation["final_right"] = clamped["x"] + clamped["w"]
            preservation["clamp_reason"] = "main_content_must_not_overlap_right_sidebar"
            validation["right_edge_preservation"] = preservation
        region["coordinate_validation"] = validation


def _merge_overlapping_same_family_structure_regions(
    localized_regions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    merged_by_index: dict[int, dict[str, Any]] = {}
    consumed: set[int] = set()
    events: list[dict[str, Any]] = []
    for index, region in enumerate(localized_regions):
        if index in consumed:
            continue
        family = _stage1_region_family(region)
        bbox = _bbox(region.get("bbox") or region.get("precise_bbox"))
        if not family or family == "modal_or_popup" or not bbox:
            merged_by_index[index] = deepcopy(region)
            continue
        duplicate_indexes = [index]
        for other_index in range(index + 1, len(localized_regions)):
            if other_index in consumed:
                continue
            other = localized_regions[other_index]
            if _stage1_region_family(other) != family:
                continue
            other_bbox = _bbox(other.get("bbox") or other.get("precise_bbox"))
            if not other_bbox:
                continue
            if _same_family_structure_region_duplicate(region, other, bbox, other_bbox):
                duplicate_indexes.append(other_index)
        if len(duplicate_indexes) == 1:
            merged_by_index[index] = deepcopy(region)
            continue
        duplicate_regions = [localized_regions[item_index] for item_index in duplicate_indexes]
        merged = deepcopy(duplicate_regions[0])
        merged_bbox = _bbox_union([
            duplicate_region.get("bbox") or duplicate_region.get("precise_bbox")
            for duplicate_region in duplicate_regions
        ]) or bbox
        item_ids: list[str] = []
        for duplicate_region in duplicate_regions:
            for item_id in duplicate_region.get("item_ids", []):
                item_id_text = str(item_id or "").strip()
                if item_id_text and item_id_text not in item_ids:
                    item_ids.append(item_id_text)
        merged["bbox"] = deepcopy(merged_bbox)
        merged["precise_bbox"] = deepcopy(merged_bbox)
        merged["item_ids"] = item_ids
        merged["item_count"] = len(item_ids)
        merged["merged_region_ids"] = [
            str(duplicate_region.get("region_id") or "") for duplicate_region in duplicate_regions
        ]
        merged["merged_zone_ids"] = [
            str(duplicate_region.get("zone_id") or "") for duplicate_region in duplicate_regions
        ]
        merged["merge_policy"] = "same_family_high_overlap_before_stage1_gate"
        merged["source"] = f"{merged.get('source') or 'stage1_structure_region_geometry'}+same_family_dedupe"
        for consumed_index in duplicate_indexes[1:]:
            consumed.add(consumed_index)
        merged_by_index[index] = merged
        events.append(
            {
                "contract_version": "learn_stage1_merged_same_family_region_v1",
                "family": family,
                "kept_region_id": str(merged.get("region_id") or ""),
                "merged_region_ids": deepcopy(merged["merged_region_ids"]),
                "merged_zone_ids": deepcopy(merged["merged_zone_ids"]),
                "bbox": deepcopy(merged_bbox),
                "reason": "same_family_structure_regions_had_near_identical_geometry",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    result = [region for index, region in merged_by_index.items() if index not in consumed]
    result.sort(key=lambda item: (_bbox_top(item), _bbox_left(item), str(item.get("region_id") or "")))
    for index, region in enumerate(result, start=1):
        region["region_no"] = index
    return result, events


def _same_family_structure_region_duplicate(
    first_region: dict[str, Any],
    second_region: dict[str, Any],
    first: dict[str, int],
    second: dict[str, int],
) -> bool:
    first_in_second = _bbox_containment_ratio(first, second)
    second_in_first = _bbox_containment_ratio(second, first)
    first_region_id = str(first_region.get("region_id") or "").casefold()
    second_region_id = str(second_region.get("region_id") or "").casefold()
    if (
        _stage1_region_family(first_region) == "top_bar"
        and _stage1_region_family(second_region) == "top_bar"
        and "browser_chrome" not in first_region_id
        and "browser_chrome" not in second_region_id
    ):
        horizontal_overlap = max(
            0,
            min(first["x"] + first["w"], second["x"] + second["w"]) - max(first["x"], second["x"]),
        )
        horizontal_overlap_ratio = horizontal_overlap / max(1, min(first["w"], second["w"]))
        if horizontal_overlap_ratio >= 0.98 and max(first_in_second, second_in_first) >= 0.98:
            return True
        first_rough = _bbox(first_region.get("rough_bbox"))
        second_rough = _bbox(second_region.get("rough_bbox"))
        if first_rough and second_rough and horizontal_overlap_ratio >= 0.98:
            rough_first_in_second = _bbox_containment_ratio(first_rough, second_rough)
            rough_second_in_first = _bbox_containment_ratio(second_rough, first_rough)
            vertical_gap = max(
                first["y"],
                second["y"],
            ) - min(
                first["y"] + first["h"],
                second["y"] + second["h"],
            )
            if max(rough_first_in_second, rough_second_in_first) >= 0.98 and vertical_gap <= 2:
                return True
    first_area = max(1, first["w"] * first["h"])
    second_area = max(1, second["w"] * second["h"])
    area_ratio = min(first_area, second_area) / max(first_area, second_area)
    if not (
        (first_in_second >= 0.98 and second_in_first >= 0.98)
        or (first_in_second >= 0.90 and second_in_first >= 0.90 and area_ratio >= 0.75)
    ):
        return False
    first_rough = _bbox(first_region.get("rough_bbox"))
    second_rough = _bbox(second_region.get("rough_bbox"))
    if first_rough and second_rough:
        rough_first_in_second = _bbox_containment_ratio(first_rough, second_rough)
        rough_second_in_first = _bbox_containment_ratio(second_rough, first_rough)
        first_rough_area = max(1, first_rough["w"] * first_rough["h"])
        second_rough_area = max(1, second_rough["w"] * second_rough["h"])
        rough_area_ratio = min(first_rough_area, second_rough_area) / max(first_rough_area, second_rough_area)
        if rough_first_in_second >= 0.90 and rough_second_in_first >= 0.90 and rough_area_ratio >= 0.75:
            return True
    first_item_count = len(first_region.get("item_ids") if isinstance(first_region.get("item_ids"), list) else [])
    second_item_count = len(second_region.get("item_ids") if isinstance(second_region.get("item_ids"), list) else [])
    return min(first_item_count, second_item_count) >= 2


def _suppress_contained_duplicate_structure_regions(
    localized_regions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept_indexes: set[int] = set(range(len(localized_regions)))
    suppressed: list[dict[str, Any]] = []
    for inner_index, inner_region in enumerate(localized_regions):
        inner_bbox = _bbox(inner_region.get("bbox") or inner_region.get("precise_bbox"))
        if not inner_bbox:
            continue
        inner_family = _stage1_region_family(inner_region)
        if inner_family in {"", "modal_or_popup"}:
            continue
        inner_area = inner_bbox["w"] * inner_bbox["h"]
        for outer_index, outer_region in enumerate(localized_regions):
            if inner_index == outer_index or inner_index not in kept_indexes:
                continue
            if _stage1_region_family(outer_region) != inner_family:
                continue
            outer_bbox = _bbox(outer_region.get("bbox") or outer_region.get("precise_bbox"))
            if not outer_bbox:
                continue
            outer_area = outer_bbox["w"] * outer_bbox["h"]
            if outer_area <= inner_area:
                precise_overlap = max(
                    _bbox_containment_ratio(inner_bbox, outer_bbox),
                    _bbox_containment_ratio(outer_bbox, inner_bbox),
                )
                if precise_overlap < 0.05:
                    continue
                rough_duplicate = _same_family_rough_contained_duplicate(inner_region, outer_region)
                if not rough_duplicate:
                    continue
                containment = rough_duplicate["containment_ratio"]
                area_ratio = rough_duplicate["area_ratio"]
                kept_indexes.discard(inner_index)
                suppressed.append(
                    {
                        "contract_version": "learn_stage1_suppressed_duplicate_region_v1",
                        "region_id": str(inner_region.get("region_id") or ""),
                        "label": str(inner_region.get("label") or ""),
                        "family": inner_family,
                        "bbox": deepcopy(inner_bbox),
                        "rough_bbox": deepcopy(rough_duplicate["inner_rough_bbox"]),
                        "contained_by_region_id": str(outer_region.get("region_id") or ""),
                        "contained_by_bbox": deepcopy(outer_bbox),
                        "contained_by_rough_bbox": deepcopy(rough_duplicate["outer_rough_bbox"]),
                        "containment_ratio": round(containment, 4),
                        "area_ratio": round(area_ratio, 4),
                        "reason": "same_family_rough_region_contained_by_larger_structure_region",
                        "display_only": True,
                        "execute_binding_enabled": False,
                        "artifact_is_authorization": False,
                    }
                )
                break
            containment = _bbox_containment_ratio(inner_bbox, outer_bbox)
            area_ratio = inner_area / max(1, outer_area)
            if containment >= 0.9 and area_ratio <= 0.25:
                kept_indexes.discard(inner_index)
                suppressed.append(
                    {
                        "contract_version": "learn_stage1_suppressed_duplicate_region_v1",
                        "region_id": str(inner_region.get("region_id") or ""),
                        "label": str(inner_region.get("label") or ""),
                        "family": inner_family,
                        "bbox": deepcopy(inner_bbox),
                        "contained_by_region_id": str(outer_region.get("region_id") or ""),
                        "contained_by_bbox": deepcopy(outer_bbox),
                        "containment_ratio": round(containment, 4),
                        "area_ratio": round(area_ratio, 4),
                        "reason": "same_family_region_contained_by_larger_structure_region",
                        "display_only": True,
                        "execute_binding_enabled": False,
                        "artifact_is_authorization": False,
                    }
                )
                break
    result = [deepcopy(region) for index, region in enumerate(localized_regions) if index in kept_indexes]
    result.sort(key=lambda item: (_bbox_top(item), _bbox_left(item), str(item.get("region_id") or "")))
    for index, region in enumerate(result, start=1):
        region["region_no"] = index
    return result, suppressed


def _same_family_rough_contained_duplicate(
    inner_region: dict[str, Any],
    outer_region: dict[str, Any],
) -> dict[str, Any] | None:
    inner_rough = _bbox(inner_region.get("rough_bbox"))
    outer_rough = _bbox(outer_region.get("rough_bbox"))
    if not inner_rough or not outer_rough:
        return None
    inner_area = max(1, inner_rough["w"] * inner_rough["h"])
    outer_area = max(1, outer_rough["w"] * outer_rough["h"])
    if outer_area <= inner_area:
        return None
    containment = _bbox_containment_ratio(inner_rough, outer_rough)
    area_ratio = inner_area / max(1, outer_area)
    if containment < 0.9 or area_ratio > 0.25:
        return None
    return {
        "inner_rough_bbox": inner_rough,
        "outer_rough_bbox": outer_rough,
        "containment_ratio": containment,
        "area_ratio": area_ratio,
    }


def _stage1_region_family(region: dict[str, Any]) -> str:
    value = " ".join(
        str(region.get(key) or "").casefold()
        for key in ("zone_id", "region_id", "label", "role")
    )
    if any(token in value for token in ("modal", "popup", "dialog", "floating")):
        return "modal_or_popup"
    if any(token in value for token in ("left_nav", "left_sidebar", "left navigation", "left sidebar")):
        return "left_bar"
    if any(token in value for token in ("right_nav", "right_sidebar", "right navigation", "right sidebar")):
        return "right_bar"
    if any(token in value for token in ("top_bar", "page_header", "browser_chrome", "header", "top/header")):
        return "top_bar"
    if any(token in value for token in ("bottom_bar", "footer", "bottom")):
        return "bottom_bar"
    if any(token in value for token in ("main_content", "primary_area", "primary", "content", "center")):
        return "main_content"
    return ""


def _bbox_containment_ratio(inner: dict[str, int], outer: dict[str, int]) -> float:
    x1 = max(inner["x"], outer["x"])
    y1 = max(inner["y"], outer["y"])
    x2 = min(inner["x"] + inner["w"], outer["x"] + outer["w"])
    y2 = min(inner["y"] + inner["h"], outer["y"] + outer["h"])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    inner_area = max(1, inner["w"] * inner["h"])
    return intersection / inner_area


def _calibrated_stage1_bbox(
    region: dict[str, Any],
    *,
    items_by_id: dict[str, dict[str, Any]],
    screen_size: dict[str, int],
) -> dict[str, Any]:
    rough = _bbox(region.get("bbox"))
    if not rough:
        return {"bbox": {}, "status": "missing_region_bbox", "strategy": "missing_bbox", "evidence": "no rough bbox"}
    width = _int(screen_size.get("width"))
    height = _int(screen_size.get("height"))
    region_items = _region_items(region, items_by_id)
    zone_id = str(region.get("zone_id") or "").casefold()
    region_id = str(region.get("region_id") or "").casefold()

    if "left_nav" in zone_id or "left_nav" in region_id:
        icon_boxes = [_bbox(item.get("bbox")) for item in region_items if _is_left_nav_item(item)]
        icon_boxes = [box for box in icon_boxes if box]
        if icon_boxes:
            right = max(box["x"] + box["w"] for box in icon_boxes)
            visual_boundaries = [
                _int((item.get("metadata") or {}).get("visual_left_rail_boundary_x"))
                for item in region_items
                if isinstance(item.get("metadata"), dict)
            ]
            rough_right = rough["x"] + rough["w"]
            rough_covers_full_lane = (
                rough["x"] <= max(24, int((width or rough_right) * 0.03))
                and rough["h"] >= max(120, int((height or rough["h"]) * 0.5))
                and rough["w"] <= max(240, int((width or rough_right) * 0.45))
            )
            boundary_candidates = [right + 18, *visual_boundaries]
            if rough_covers_full_lane:
                boundary_candidates.append(rough_right)
            else:
                boundary_candidates.append(int((width or right) * 0.08))
            visual_rail_width = max(boundary_candidates)
            calibrated = {
                "x": 0,
                "y": 0,
                "w": min(width or visual_rail_width, visual_rail_width),
                "h": height or rough["h"],
            }
            return {
                "bbox": calibrated,
                "status": "heuristic_calibrated_from_left_nav_icons",
                "strategy": "left_nav_icon_column_full_height",
                "evidence": "left rail icons define the rail width; full screenshot height retained",
            }

    if "right_sidebar" in zone_id or "right_sidebar" in region_id:
        item_boxes = [_bbox(item.get("bbox")) for item in region_items if not _is_section_hint(item)]
        item_boxes = [box for box in item_boxes if box]
        union = _bbox_union(item_boxes)
        if union:
            top = _top_bar_height(height)
            right = max(union["x"] + union["w"], width)
            x = max(0, union["x"])
            return {
                "bbox": {"x": x, "y": top, "w": max(1, right - x), "h": max(1, (height or union["y"] + union["h"]) - top)},
                "status": "heuristic_calibrated_right_sidebar_strip",
                "strategy": "right_sidebar_vertical_info_panel_full_height",
                "evidence": "right-edge candidates form a narrow vertical information panel; full visible height retained",
            }

    if zone_id == "browser_chrome" or "browser_chrome" in region_id:
        chrome_bottom = max(58, min(92, int(height * 0.06) if height else 72))
        item_boxes = [
            _bbox(item.get("bbox"))
            for item in region_items
            if _is_browser_chrome_top_item(item, chrome_bottom=chrome_bottom, screen_width=width)
        ]
        item_boxes = [box for box in item_boxes if box]
        union = _bbox_union(item_boxes)
        bottom = union["y"] + union["h"] + 6 if union else rough["y"] + rough["h"]
        chrome_h = max(56, bottom)
        return {
            "bbox": {"x": 0, "y": 0, "w": width or rough["w"], "h": max(1, min(height or chrome_h, chrome_h))},
            "status": "heuristic_calibrated_browser_chrome_review_region",
            "strategy": "browser_chrome_kept_separate_from_page_header",
            "evidence": "browser/address/tab evidence is separated from webpage header before page structure learning",
        }

    if zone_id in {"top_bar", "page_header"} or "header" in region_id:
        top_h = rough["y"] + rough["h"]
        item_boxes = [_bbox(item.get("bbox")) for item in region_items if not _is_section_hint(item)]
        item_boxes = [box for box in item_boxes if box]
        y = 0
        strategy = "top_bar_height_clamped_before_content_title"
        evidence = "top/header region is clamped so content title and cards are excluded"
        unsupported_tail_trimmed = 0
        browser_surface = _items_have_browser_chrome_evidence(items_by_id.values())
        if item_boxes:
            min_item_y = min(box["y"] for box in item_boxes)
            max_item_bottom = max(box["y"] + box["h"] for box in item_boxes)
            if browser_surface and min_item_y > max(56, int((height or 0) * 0.045)):
                y = max(0, min_item_y - 8)
                top_h = max(1, max_item_bottom + 8 - y)
                strategy = "browser_page_header_contains_assigned_children"
                evidence = "page header starts below browser chrome and contains every assigned child"
            else:
                trailing_padding = 8
                if rough["y"] > 0 and min_item_y > 56:
                    trailing_padding = max(8, min(48, max(box["h"] for box in item_boxes)))
                evidence_boundary = max(56, max_item_bottom + trailing_padding)
                unsupported_tail = max(0, top_h - evidence_boundary)
                tail_tolerance = max(32, max(box["h"] for box in item_boxes) * 2)
                if rough["y"] == 0 and unsupported_tail > tail_tolerance:
                    top_h = evidence_boundary
                    unsupported_tail_trimmed = unsupported_tail
                    strategy = "top_bar_sparse_tail_trimmed_to_assigned_children"
                    evidence = "coarse top/header tail had no assigned child evidence and was returned to main content"
                else:
                    top_h = max(top_h, evidence_boundary)
                    strategy = "top_bar_contains_assigned_children"
                    evidence = "top/header boundary contains every assigned child before sibling partitioning"
        result = {
            "bbox": {"x": 0, "y": y, "w": width or rough["w"], "h": top_h},
            "status": "heuristic_calibrated_top_bar",
            "strategy": strategy,
            "evidence": evidence,
        }
        if unsupported_tail_trimmed:
            result["unsupported_tail_trimmed"] = unsupported_tail_trimmed
        return result

    if zone_id in {"primary_area", "main_content", "lower_content"} or "main" in region_id or "primary" in region_id:
        browser_surface = _items_have_browser_chrome_evidence(items_by_id.values())
        explicit_top_candidates = [
            item
            for item in items_by_id.values()
            if _is_explicit_top_candidate(item)
        ]
        excluded_top_duplicate_ids = {
            str(item.get("item_id") or "")
            for item in region_items
            if _duplicates_explicit_top_candidate(item, explicit_top_candidates)
        }
        content_boxes = [
            _bbox(item.get("bbox"))
            for item in region_items
            if not _is_section_hint(item) and not _is_left_nav_item(item)
            and str(item.get("item_id") or "") not in excluded_top_duplicate_ids
            and not _is_floating_overlay_item(item, screen_width=width)
            and not (
                browser_surface
                and _looks_like_webpage_header_control(
                    item,
                    bbox=_bbox(item.get("bbox")) or {},
                    height=height,
                )
            )
        ]
        content_boxes = [box for box in content_boxes if box]
        if content_boxes:
            union = _bbox_union(content_boxes)
            if union:
                pad = 8
                left_nav_width = _left_nav_width(
                    items_by_id.values(),
                    width=width,
                    min_y=_top_bar_height(height),
                )
                x1 = max(left_nav_width, union["x"] - pad)
                y1 = max(_top_bar_height(height), union["y"] - pad)
                x2 = min(width or union["x"] + union["w"], union["x"] + union["w"] + pad)
                y2 = min(height or union["y"] + union["h"], union["y"] + union["h"] + pad)
                strategy = "content_union_excluding_section_hints_and_left_nav"
                evidence = "section bbox treated as hint; OCR/card/candidate content recalculates visible content area"
                right_edge_preservation: dict[str, Any] | None = None
                if (
                    left_nav_width == 0
                    and width > 0
                    and union["w"] < int(width * 0.82)
                    and (
                        _has_full_width_page_header_evidence(items_by_id.values(), width=width, height=height)
                        or _looks_like_centered_page_content_column(union, width=width)
                    )
                ):
                    x1 = 0
                    x2 = width
                    strategy = "main_content_full_width_when_no_sidebars"
                    evidence = (
                        "no left-sidebar evidence exists, so centered content columns calibrate the main visual "
                        "region height but not the full horizontal page area"
                    )
                else:
                    rough_right = rough["x"] + rough["w"]
                    target_right = min(width or rough_right, rough_right)
                    has_card_grid_evidence = any(_is_card_like_region_item(item) for item in region_items)
                    right_gap = target_right - x2
                    if (
                        left_nav_width > 0
                        and width > 0
                        and has_card_grid_evidence
                        and rough["x"] <= x1
                        and right_gap > max(12, int(width * 0.01))
                    ):
                        previous_right = x2
                        x2 = target_right
                        strategy = f"{strategy}_with_visual_region_right_edge"
                        evidence = (
                            f"{evidence}; media/card/grid evidence preserves the stage-1 visual shell right edge"
                        )
                        right_edge_preservation = {
                            "status": "main_content_right_edge_preserved_from_visual_region_hint",
                            "source": "stage1_rough_region_with_media_card_grid_evidence",
                            "previous_right": previous_right,
                            "preserved_right": x2,
                            "rough_right": rough_right,
                            "reason": (
                                "content union can end at inner text/card evidence while a media/grid shell continues "
                                "to the visible right edge"
                            ),
                        }
                result = {
                    "bbox": {"x": x1, "y": y1, "w": max(1, x2 - x1), "h": max(1, y2 - y1)},
                    "status": "heuristic_calibrated_from_region_content",
                    "strategy": strategy,
                    "evidence": evidence,
                }
                if right_edge_preservation:
                    result["right_edge_preservation"] = right_edge_preservation
                if excluded_top_duplicate_ids:
                    result["top_duplicate_exclusion"] = {
                        "contract_version": "learn_stage1_top_duplicate_exclusion_v1",
                        "excluded_item_count": len(excluded_top_duplicate_ids),
                        "excluded_item_ids": sorted(excluded_top_duplicate_ids),
                        "reason": "main_boundary_must_ignore_readable_duplicate_of_explicit_top_candidate",
                        "display_only": True,
                        "execute_binding_enabled": False,
                        "artifact_is_authorization": False,
                    }
                return result
        if zone_id == "lower_content":
            return {
                "bbox": deepcopy(rough),
                "status": "heuristic_calibrated_lower_content_section_boundary",
                "strategy": "lower_content_section_boundary_kept_for_review",
                "evidence": "lower visible content section has no stronger child candidates, so section boundary is retained for review",
            }

    return {
        "bbox": deepcopy(rough),
        "status": "geometry_only_needs_model_calibration",
        "strategy": "rough_geometry_copy",
        "evidence": "no stronger calibration evidence found",
    }


def _is_explicit_top_candidate(item: dict[str, Any]) -> bool:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return (
        str(metadata.get("source") or "").casefold() == "screen_map.candidates"
        and str(metadata.get("surface_zone") or "").casefold() in {"top_bar", "page_header", "header"}
    )


def _duplicates_explicit_top_candidate(
    item: dict[str, Any],
    explicit_top_candidates: list[dict[str, Any]],
) -> bool:
    if _is_explicit_top_candidate(item):
        return False
    bbox = _bbox(item.get("bbox"))
    label = " ".join(str(item.get("label") or item.get("text") or "").casefold().split())
    if not bbox or not label:
        return False
    center_y = bbox["y"] + bbox["h"] / 2
    row_peers = [
        (candidate, candidate_bbox)
        for candidate in explicit_top_candidates
        for candidate_bbox in [_bbox(candidate.get("bbox"))]
        if candidate_bbox
        and abs((candidate_bbox["y"] + candidate_bbox["h"] / 2) - center_y) <= max(24, bbox["h"] * 1.5)
    ]
    if len(row_peers) < 3:
        return False
    peer_centers_x = [peer["x"] + peer["w"] / 2 for _candidate, peer in row_peers]
    if max(peer_centers_x) - min(peer_centers_x) < max(180, bbox["w"] * 1.2):
        return False
    for candidate, candidate_bbox in row_peers:
        candidate_label = " ".join(
            str(candidate.get("label") or candidate.get("text") or "").casefold().split()
        )
        if candidate_label == label and _iou(bbox, candidate_bbox) >= 0.75:
            return True
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    return role in {"text", "readable", "label"}


def _has_full_width_page_header_evidence(items: Any, *, width: int, height: int) -> bool:
    if width <= 0:
        return False
    top_limit = max(80, int((height or 0) * 0.16))
    for item in items:
        if not isinstance(item, dict):
            continue
        bbox = _bbox(item.get("bbox"))
        if not bbox or bbox["y"] > top_limit:
            continue
        role = str(item.get("role") or item.get("item_type") or "").casefold()
        label = str(item.get("label") or "").casefold()
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        zone = str(metadata.get("surface_zone") or "").casefold()
        is_header_like = (
            "header" in label
            or "top" in label
            or "browser" in label
            or "header" in role
            or "layout" in role
            or zone in {"top_bar", "page_header", "browser_chrome"}
        )
        if is_header_like and bbox["x"] <= max(8, int(width * 0.02)) and bbox["w"] >= int(width * 0.72):
            return True
    return False


def _items_have_browser_chrome_evidence(items: Any) -> bool:
    for item in items:
        if not isinstance(item, dict):
            continue
        value = " ".join(
            str(item.get(key) or "").casefold()
            for key in ("item_id", "role", "item_type", "label")
        )
        if any(token in value for token in ("browser_chrome", "address_bar", "http://", "https://", "www.")):
            return True
    return False


def _looks_like_webpage_header_control(item: dict[str, Any], *, bbox: dict[str, int], height: int) -> bool:
    if not bbox or height <= 0:
        return False
    top_limit = max(180, int(height * 0.22), _top_bar_height(height) * 2)
    if bbox["y"] > top_limit:
        return False
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    label = str(item.get("label") or item.get("text") or "").strip()
    if not label and not role:
        return False
    role_is_header_control = any(
        token in role
        for token in (
            "nav",
            "menu",
            "search",
            "button",
            "input",
            "action",
            "toolbar",
            "tab",
            "brand",
            "logo",
        )
    )
    if role_is_header_control:
        return True
    if len(label) > 40 or bbox["h"] > 72:
        return False
    compact_top_text = bbox["w"] <= 180 and bbox["h"] <= 48
    return compact_top_text and bbox["y"] <= max(260, _top_bar_height(height) * 2)


def _looks_like_centered_page_content_column(union: dict[str, int], *, width: int) -> bool:
    if width <= 0:
        return False
    left_gap = union["x"]
    right_gap = width - (union["x"] + union["w"])
    min_gap = max(80, int(width * 0.16))
    return left_gap >= min_gap and right_gap >= min_gap


def _is_floating_overlay_item(item: dict[str, Any], *, screen_width: int = 0) -> bool:
    bbox = _bbox(item.get("bbox"))
    value = " ".join(
        str(item.get(key) or "").casefold()
        for key in ("item_id", "role", "item_type", "label")
    )
    if any(token in value for token in ("floating", "overlay", "translate", "popup")):
        return True
    if bbox and screen_width > 0:
        right_edge = bbox["x"] + bbox["w"]
        if right_edge >= int(screen_width * 0.94) and bbox["w"] <= max(96, int(screen_width * 0.12)):
            return True
    return False


def _region_items(region: dict[str, Any], items_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item_id in region.get("item_ids") if isinstance(region.get("item_ids"), list) else []:
        item = items_by_id.get(str(item_id))
        if isinstance(item, dict):
            result.append(item)
    return result


def _is_section_hint(item: dict[str, Any]) -> bool:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return str(metadata.get("source") or "").casefold() == "screen_map.sections"


def _is_left_nav_item(item: dict[str, Any]) -> bool:
    bbox = _bbox(item.get("bbox"))
    if not bbox:
        return False
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    if bbox["x"] <= 110 and bbox["w"] <= 120 and role in {
        "nav_rail_icon_review_only",
        "nav_item",
        "listitem",
        "menuitem",
        "icon_button",
        "icon",
        "button",
    }:
        return True
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return str(metadata.get("surface_zone") or "").casefold() == "left_nav"


def _left_nav_width(items: Any, *, width: int, min_y: int = 0) -> int:
    icon_boxes = [
        _bbox(item.get("bbox"))
        for item in items
        if isinstance(item, dict)
        and _is_left_nav_item(item)
        and (_bbox(item.get("bbox")) or {}).get("y", 0) + (_bbox(item.get("bbox")) or {}).get("h", 0) >= min_y
    ]
    icon_boxes = [box for box in icon_boxes if box]
    if not icon_boxes:
        return 0
    right = max(box["x"] + box["w"] for box in icon_boxes) + 18
    visual_rail_width = max(right, int((width or right) * 0.08))
    return min(width or visual_rail_width, visual_rail_width)


def _top_bar_height(height: int) -> int:
    if height <= 0:
        return 0
    return max(56, int(height * 0.09))


def _stage1_calibration_diagnostics(localized_regions: list[dict[str, Any]]) -> dict[str, Any]:
    diagnostics: list[dict[str, Any]] = []
    model_grounded = 0
    geometry_only = 0
    for region in localized_regions:
        rough = _bbox(region.get("rough_bbox"))
        precise = _bbox(region.get("precise_bbox"))
        validation = region.get("coordinate_validation") if isinstance(region.get("coordinate_validation"), dict) else {}
        if validation.get("model_grounding_attempted"):
            model_grounded += 1
        elif str(validation.get("status") or "").startswith("heuristic_calibrated"):
            pass
        else:
            geometry_only += 1
        dx = (precise["x"] - rough["x"]) if rough and precise else 0
        dy = (precise["y"] - rough["y"]) if rough and precise else 0
        diagnostics.append(
            {
                "region_id": str(region.get("region_id") or ""),
                "label": str(region.get("label") or ""),
                "rough_bbox": deepcopy(rough or {}),
                "precise_bbox": deepcopy(precise or {}),
                "delta": {"dx": dx, "dy": dy},
                "status": str(validation.get("status") or "unknown"),
                "risk": (
                    "model_grounded"
                    if validation.get("model_grounding_attempted")
                    else (
                        "heuristic_calibrated_needs_visual_review"
                        if str(validation.get("status") or "").startswith("heuristic_calibrated")
                        else "needs_model_calibration"
                    )
                ),
                "review_hint": (
                    "当前坐标仍来自结构几何并可能偏移；下一步应由整屏模型和 VISTA/4B 对整栏边界重新定位。"
                    if not validation.get("model_grounding_attempted")
                    else "模型已参与整栏定位，仍需人工看 overlay 复核。"
                ),
            }
        )
    return {
        "contract_version": "learn_stage1_region_calibration_diagnostics_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "region_count": len(localized_regions),
        "model_grounded_region_count": model_grounded,
        "geometry_only_region_count": geometry_only,
        "needs_prompt_or_model_calibration": geometry_only > 0,
        "diagnostics": diagnostics,
        "interpretation": (
            "geometry_only means the current box is only a starting hint. "
            "It must not be treated as precise model-localized evidence."
        ),
    }


def _stage1_granularity_review(
    *,
    localized_regions: list[dict[str, Any]],
    items_by_id: dict[str, dict[str, Any]],
    screen_size: dict[str, int],
    region_selection_audit: dict[str, Any],
    class_rule_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    width = _int(screen_size.get("width"))
    issues: list[dict[str, Any]] = []
    families = {_stage1_region_family(region) for region in localized_regions}
    has_browser = _items_have_browser_chrome_evidence(items_by_id.values())
    primary_regions = [
        region
        for region in localized_regions
        if _stage1_region_family(region) == "main_content"
    ]
    for region in primary_regions:
        bbox = _bbox(region.get("bbox") or region.get("precise_bbox"))
        if not bbox:
            continue
        region_id = str(region.get("region_id") or "")
        if has_browser and width > 0 and bbox["w"] >= int(width * 0.88):
            if any(str(item.get("zone_id") or "") == "floating_controls" for item in localized_regions) or _has_centered_content_column_evidence(region, items_by_id=items_by_id, screen_width=width):
                issues.append(
                    {
                        "issue": "browser_primary_scope_ambiguous_full_page_vs_content_column",
                        "region_id": region_id,
                        "review_question": "primary_area currently means full visible page body; if the product needs a centered content column, split that in Stage1.5 rather than shrinking Stage1.",
                        "recommended_next_step": "stage1_5_subpane_or_content_column_partition",
                    }
                )
        pane_evidence = _primary_subpane_evidence(region, items_by_id=items_by_id)
        if not pane_evidence and bool((class_rule_profile or {}).get("allow_chat_semantics")):
            pane_evidence = ["validated_conversation_profile"]
        if pane_evidence:
            issues.append(
                {
                    "issue": "primary_contains_multiple_work_panes",
                    "region_id": region_id,
                    "evidence": pane_evidence,
                    "review_question": "coarse Stage1 primary is geometrically valid, but list/thread/composer-style panes should be split before detailed numbering.",
                    "recommended_next_step": "stage1_5_subpane_partition",
                }
            )
    status = "stage1_geometry_ready"
    if issues:
        status = "stage1_geometry_passed_needs_granularity_review"
    if not region_selection_audit.get("passed"):
        status = "stage1_geometry_failed"
    return {
        "contract_version": "learn_stage1_granularity_review_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "not_accuracy": True,
        "status": status,
        "region_selection_audit_passed": bool(region_selection_audit.get("passed")),
        "issue_count": len(issues),
        "issues": issues,
        "stage1_definition": "top_level_structure_regions_only",
        "stage1_5_definition": "subpane/content-column partition before per-item numbering when primary is semantically composite",
        "recommended_next_step": "stage1_5_subpane_partition" if issues else "stage2_numbering",
        "interpretation": (
            "A passed region-selection audit only means the large boxes are geometrically legal. "
            "Granularity issues explain reviewer conditional-pass cases and must not be reported as full recognition reliability."
        ),
    }


def _has_centered_content_column_evidence(
    region: dict[str, Any],
    *,
    items_by_id: dict[str, dict[str, Any]],
    screen_width: int,
) -> bool:
    if screen_width <= 0:
        return False
    item_ids = region.get("item_ids") if isinstance(region.get("item_ids"), list) else []
    for item_id in item_ids:
        item = items_by_id.get(str(item_id))
        if not isinstance(item, dict):
            continue
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            continue
        if bbox["x"] > int(screen_width * 0.12) and bbox["x"] + bbox["w"] < int(screen_width * 0.88):
            if bbox["w"] <= int(screen_width * 0.78):
                return True
    return False


def _primary_subpane_evidence(
    region: dict[str, Any],
    *,
    items_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    item_ids = region.get("item_ids") if isinstance(region.get("item_ids"), list) else []
    item_texts: list[str] = []
    structural_texts: list[str] = []
    structural_roles = {
        "card",
        "container",
        "content_area",
        "detail_pane",
        "input_area",
        "layout",
        "list_pane",
        "message_card",
        "section",
    }
    for item_id in item_ids:
        item = items_by_id.get(str(item_id), {})
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        role = str(item.get("role") or "").casefold()
        item_type = str(item.get("item_type") or "").casefold()
        semantic_text = " ".join(
            [
                role,
                item_type,
                str(metadata.get("semantic_role") or ""),
                str(metadata.get("surface_zone") or ""),
            ]
        ).casefold()
        item_texts.append(semantic_text)
        if role in structural_roles or item_type in structural_roles:
            structural_texts.append(
                " ".join(
                    [
                        semantic_text,
                        str(item.get("item_id") or item.get("candidate_id") or ""),
                        str(item.get("label") or ""),
                    ]
                ).casefold()
            )
    evidence: list[str] = []
    if any(
        any(token in item_text for token in ("main_chat", "chat_area", "chat area", "chat surface", "conversation workspace"))
        for item_text in structural_texts
    ):
        evidence.append("chat_surface_signal")
    if any(
        any(token in item_text for token in ("conversation", "chat list", "session list", "会话", "联系人"))
        for item_text in item_texts
    ):
        evidence.append("conversation_or_list_pane_signal")
    if any(
        any(token in item_text for token in ("message", "chat thread", "bubble", "消息", "聊天"))
        for item_text in item_texts
    ):
        evidence.append("message_thread_signal")
    if any(
        any(token in item_text for token in ("composer", "input area", "send button", "输入框", "发送"))
        for item_text in item_texts
    ):
        evidence.append("bottom_composer_signal")
    return evidence


def _stage1_5_partition(
    *,
    localized_regions: list[dict[str, Any]],
    items_by_id: dict[str, dict[str, Any]],
    screen_size: dict[str, int],
    region_selection_audit: dict[str, Any],
    granularity_review: dict[str, Any],
    source_image_path: str,
    class_rule_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not region_selection_audit.get("passed"):
        status = "not_evaluated_stage1_geometry_failed"
        subregions: list[dict[str, Any]] = []
    elif not granularity_review.get("issues"):
        status = "not_needed_stage1_geometry_ready"
        subregions = []
    else:
        subregions = []
        issues = granularity_review.get("issues") if isinstance(granularity_review.get("issues"), list) else []
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            region_id = str(issue.get("region_id") or "")
            region = _find_localized_region(localized_regions, region_id)
            if not region:
                continue
            issue_name = str(issue.get("issue") or "")
            if issue_name == "browser_primary_scope_ambiguous_full_page_vs_content_column":
                subregions.extend(
                    _stage1_5_content_column_subregions(region=region, items_by_id=items_by_id, screen_size=screen_size)
                )
            elif issue_name == "primary_contains_multiple_work_panes":
                chat_evidence = _primary_subpane_evidence(region, items_by_id=items_by_id)
                chat_profile_enabled = bool((class_rule_profile or {}).get("allow_chat_semantics"))
                if chat_profile_enabled or "chat_surface_signal" in chat_evidence or len(chat_evidence) >= 2:
                    subregions.extend(
                        _stage1_5_chat_subregions(
                            region=region,
                            items_by_id=items_by_id,
                            source_image_path=source_image_path,
                            screen_size=screen_size,
                        )
                    )
                else:
                    subregions.extend(
                        _stage1_5_work_pane_subregions(
                            region=region,
                            items_by_id=items_by_id,
                            source_image_path=source_image_path,
                            screen_size=screen_size,
                        )
                    )
        status = "stage1_5_suggested" if subregions else "stage1_5_review_needed_no_subregion_candidate"
    subregions, stage2_selection = _stage1_5_stage2_selection_report(
        subregions=subregions,
        localized_regions=localized_regions,
    )
    return {
        "contract_version": "learn_stage1_5_partition_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "pathgraph_generation_skipped": True,
        "stage1_regions_unchanged": True,
        "source": "stage1_granularity_review",
        "status": status,
        "subregion_count": len(subregions),
        "stage2_selection": stage2_selection,
        "subregions": subregions,
        "interpretation": (
            "Stage1.5 is a read-only partition suggestion for page details and later numbering. "
            "It must not shrink Stage1 regions and must not authorize clicking."
        ),
    }


def _stage1_5_stage2_selection_report(
    *,
    subregions: list[dict[str, Any]],
    localized_regions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    region_by_id = {str(region.get("region_id") or ""): region for region in localized_regions if isinstance(region, dict)}
    child_item_ids_by_parent: dict[str, set[str]] = {}
    for subregion in subregions:
        if not isinstance(subregion, dict):
            continue
        parent_region_id = str(subregion.get("parent_region_id") or "")
        child_item_ids_by_parent.setdefault(parent_region_id, set()).update(
            str(item_id) for item_id in (subregion.get("item_ids") or []) if str(item_id)
        )
    parent_evidence_coverage: dict[str, dict[str, Any]] = {}
    for parent_region_id, parent_region in region_by_id.items():
        parent_item_ids = {
            str(item_id) for item_id in (parent_region.get("item_ids") or []) if str(item_id)
        }
        child_item_ids = child_item_ids_by_parent.get(parent_region_id, set())
        if not parent_item_ids:
            continue
        covered_count = len(parent_item_ids.intersection(child_item_ids))
        coverage = covered_count / len(parent_item_ids)
        parent_evidence_coverage[parent_region_id] = {
            "parent_item_count": len(parent_item_ids),
            "covered_item_count": covered_count,
            "coverage": round(float(coverage), 4),
            "minimum_required": 0.5,
            "sufficient_for_replacement": coverage >= 0.5,
        }
    annotated: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for subregion in subregions:
        item = deepcopy(subregion)
        parent_region_id = str(item.get("parent_region_id") or "")
        parent_region = region_by_id.get(parent_region_id)
        parent_family = _stage1_region_family(parent_region) if isinstance(parent_region, dict) else ""
        bbox = _bbox(item.get("bbox"))
        parent_bbox = _bbox(parent_region.get("bbox") or parent_region.get("precise_bbox")) if isinstance(parent_region, dict) else None
        containment = _bbox_containment_ratio(bbox, parent_bbox) if bbox and parent_bbox else 0.0
        reason = ""
        eligible = True
        if parent_family != "main_content":
            eligible = False
            reason = "stage1_5_only_main_content_may_replace_stage2_input"
        elif containment < 0.9:
            eligible = False
            reason = "stage1_5_subregion_not_contained_in_parent_region"
        elif (
            parent_region_id in parent_evidence_coverage
            and not parent_evidence_coverage[parent_region_id]["sufficient_for_replacement"]
        ):
            eligible = False
            reason = "stage1_5_partition_drops_parent_evidence"
        if eligible:
            reason = "stage1_5_main_content_partition_selected"
            accepted.append(
                {
                    "subregion_id": str(item.get("subregion_id") or ""),
                    "parent_region_id": parent_region_id,
                    "role": str(item.get("role") or ""),
                    "containment": round(float(containment), 4),
                }
            )
        else:
            rejected.append(
                {
                    "subregion_id": str(item.get("subregion_id") or ""),
                    "parent_region_id": parent_region_id,
                    "parent_family": parent_family,
                    "role": str(item.get("role") or ""),
                    "containment": round(float(containment), 4),
                    "reason": reason,
                }
            )
        item["stage2_numbering_eligible"] = bool(eligible)
        item["stage2_numbering_selection_reason"] = reason
        item["stage2_parent_family"] = parent_family
        item["stage2_parent_containment"] = round(float(containment), 4)
        item["stage2_parent_evidence_coverage"] = deepcopy(parent_evidence_coverage.get(parent_region_id) or {})
        annotated.append(item)
    return annotated, {
        "contract_version": "learn_stage1_5_stage2_selection_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "policy": "stage1_5_partitions_are_candidates; only stable main-content subregions may replace Stage2 input regions",
        "eligible_count": len(accepted),
        "rejected_count": len(rejected),
        "parent_evidence_coverage": parent_evidence_coverage,
        "accepted": accepted,
        "rejected": rejected,
    }


def _stage2_input_regions(
    *,
    localized_regions: list[dict[str, Any]],
    stage1_5_partition: dict[str, Any],
    items_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    subregions = stage1_5_partition.get("subregions") if isinstance(stage1_5_partition.get("subregions"), list) else []
    by_parent: dict[str, list[dict[str, Any]]] = {}
    for subregion in subregions:
        if not isinstance(subregion, dict):
            continue
        if subregion.get("stage2_numbering_eligible") is False:
            continue
        parent_region_id = str(subregion.get("parent_region_id") or "")
        if not parent_region_id:
            continue
        by_parent.setdefault(parent_region_id, []).append(subregion)
    if not by_parent:
        return [deepcopy(region) for region in localized_regions]

    result: list[dict[str, Any]] = []
    for region in localized_regions:
        region_id = str(region.get("region_id") or "")
        replacements = by_parent.get(region_id) or []
        if not replacements:
            result.append(deepcopy(region))
            continue
        parent_no = _int(region.get("region_no"))
        for index, subregion in enumerate(replacements, start=1):
            bbox = _bbox(subregion.get("bbox")) or {}
            seed_item_ids = [str(item_id) for item_id in subregion.get("item_ids", []) if str(item_id or "").strip()]
            parent_item_ids = [str(item_id) for item_id in region.get("item_ids", []) if str(item_id or "").strip()]
            numbering_item_ids: list[str] = []
            for item_id in [*seed_item_ids, *parent_item_ids]:
                if item_id in numbering_item_ids:
                    continue
                item = items_by_id.get(item_id)
                item_bbox = _bbox(item.get("bbox")) if isinstance(item, dict) else None
                if bbox and item_bbox and _bbox_substantially_inside_parent(bbox, item_bbox):
                    numbering_item_ids.append(item_id)
            synthetic = {
                **deepcopy(region),
                "contract_version": "learn_stage1_5_numbering_region_v1",
                "region_no": parent_no * 10 + index if parent_no else len(result) + 1,
                "region_id": str(subregion.get("subregion_id") or f"{region_id}__stage1_5__{index}"),
                "label": str(subregion.get("label") or subregion.get("role") or "Stage1.5 subregion"),
                "role": str(subregion.get("role") or "stage1_5_subregion"),
                "zone_id": f"{str(region.get('zone_id') or region_id)}__stage1_5",
                "bbox": deepcopy(bbox),
                "precise_bbox": deepcopy(bbox),
                "rough_bbox": deepcopy(bbox),
                "item_ids": numbering_item_ids,
                "stage": "stage1_5_subregion_for_stage2_numbering",
                "source": "stage1_5_partition",
                "bbox_policy": "stage1_5_subregion_replaces_broad_parent_for_stage2_numbering",
                "parent_region_id": region_id,
                "parent_region_bbox": deepcopy(_bbox(region.get("bbox") or region.get("precise_bbox")) or {}),
                "input_stage1_region": deepcopy(region),
                "input_stage1_5_subregion": deepcopy(subregion),
                "coordinate_validation": {
                    "contract_version": "learn_stage1_5_subregion_coordinate_validation_v1",
                    "status": "stage1_5_partition_selected_for_stage2_numbering",
                    "evidence": "parent region had a granularity issue; child subregion is used for numbering while Stage1 region remains unchanged",
                    "model_grounding_attempted": False,
                    "semantic_model": "not_run",
                    "coordinate_model": "not_run",
                    "calibration_strategy": "stage1_5_subregion_from_granularity_review",
                    "display_only": True,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
            result.append(synthetic)
    return result


def _normalize_stage2_region_strategy(value: str) -> str:
    text = str(value or "").strip().casefold()
    return "global_no_partition" if text in {"global_no_partition", "no_partition", "full_screen"} else "partitioned"


def _stage2_global_no_partition_input_regions(
    *,
    items_by_id: dict[str, dict[str, Any]],
    screen_size: dict[str, int],
) -> list[dict[str, Any]]:
    width = _int(screen_size.get("width"))
    height = _int(screen_size.get("height"))
    item_ids: list[str] = []
    for item_id, item in items_by_id.items():
        if not isinstance(item, dict) or _is_section_hint(item):
            continue
        if not _bbox(item.get("bbox")):
            continue
        item_ids.append(str(item_id))
    full_bbox = {"x": 0, "y": 0, "w": max(1, width), "h": max(1, height)}
    return [
        {
            "contract_version": "learn_stage2_global_no_partition_region_v1",
            "region_no": 1,
            "region_id": "global_no_partition",
            "label": "Full screen numbering canvas",
            "role": "global_no_partition_canvas",
            "zone_id": "full_screen",
            "bbox": deepcopy(full_bbox),
            "precise_bbox": deepcopy(full_bbox),
            "rough_bbox": deepcopy(full_bbox),
            "item_ids": item_ids,
            "stage": "stage2_global_no_partition_for_numbering",
            "source": "stage2_region_strategy",
            "bbox_policy": "full_screen_canvas_no_stage1_partition_clipping",
            "coordinate_validation": {
                "contract_version": "learn_stage2_global_no_partition_coordinate_validation_v1",
                "status": "full_screen_canvas_selected_for_stage2_numbering",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
    ]


def _find_localized_region(localized_regions: list[dict[str, Any]], region_id: str) -> dict[str, Any] | None:
    for region in localized_regions:
        if str(region.get("region_id") or "") == region_id:
            return region
    return None


def _stage1_5_content_column_subregions(
    *,
    region: dict[str, Any],
    items_by_id: dict[str, dict[str, Any]],
    screen_size: dict[str, int],
) -> list[dict[str, Any]]:
    parent_bbox = _bbox(region.get("bbox") or region.get("precise_bbox"))
    if not parent_bbox:
        return []
    width = _int(screen_size.get("width"))
    height = _int(screen_size.get("height"))
    browser_surface = _items_have_browser_chrome_evidence(items_by_id.values())
    item_ids = region.get("item_ids") if isinstance(region.get("item_ids"), list) else []
    candidates: list[dict[str, Any]] = []
    for item_id in item_ids:
        item = items_by_id.get(str(item_id))
        if not isinstance(item, dict) or _is_section_hint(item) or _is_floating_overlay_item(item, screen_width=width):
            continue
        bbox = _bbox(item.get("bbox"))
        if not bbox or not _bbox_substantially_inside_parent(parent_bbox, bbox):
            continue
        if browser_surface and _looks_like_webpage_header_control(item, bbox=bbox, height=height):
            continue
        if _looks_like_stage1_5_content_column_item(item, bbox=bbox, parent_bbox=parent_bbox, screen_width=width):
            candidates.append(item)
    if not candidates:
        for item_id in item_ids:
            item = items_by_id.get(str(item_id))
            if not isinstance(item, dict) or _is_section_hint(item) or _is_floating_overlay_item(item, screen_width=width):
                continue
            bbox = _bbox(item.get("bbox"))
            if not bbox or not _bbox_substantially_inside_parent(parent_bbox, bbox):
                continue
            if browser_surface and _looks_like_webpage_header_control(item, bbox=bbox, height=height):
                continue
            candidates.append(item)
    boxes = [_bbox(item.get("bbox")) for item in candidates]
    boxes = [box for box in boxes if box]
    union = _clip_bbox_to_parent(_bbox_union(boxes), parent_bbox)
    if not union or (width > 0 and not _looks_like_centered_page_content_column(union, width=width)):
        return []
    covered_item_ids = [
        str(item_id)
        for item_id in item_ids
        if (item := items_by_id.get(str(item_id))) is not None
        and (item_bbox := _bbox(item.get("bbox"))) is not None
        and _bbox_containment_ratio(item_bbox, union) >= 0.85
    ]
    return [
        _stage1_5_subregion(
            region=region,
            role="content_column",
            label="Stage1.5 content column",
            bbox=union,
            item_ids=covered_item_ids,
            source_issue="browser_primary_scope_ambiguous_full_page_vs_content_column",
            reason="centered_content_column_inside_full_width_primary",
        )
    ]


def _looks_like_stage1_5_content_column_item(
    item: dict[str, Any],
    *,
    bbox: dict[str, int],
    parent_bbox: dict[str, int],
    screen_width: int,
) -> bool:
    value = " ".join(
        str(item.get(key) or "").casefold()
        for key in ("item_id", "role", "item_type", "label")
    )
    semantic = any(token in value for token in ("content", "section", "hero", "main", "card", "grid", "list", "article"))
    if not semantic:
        return False
    min_area = max(1, int(parent_bbox["w"] * parent_bbox["h"] * 0.1))
    area = bbox["w"] * bbox["h"]
    if area < min_area:
        return False
    if screen_width > 0 and _looks_like_centered_page_content_column(bbox, width=screen_width):
        return True
    return bbox["w"] <= int(parent_bbox["w"] * 0.82)


def _stage1_5_work_pane_subregions(
    *,
    region: dict[str, Any],
    items_by_id: dict[str, dict[str, Any]],
    source_image_path: str,
    screen_size: dict[str, int],
) -> list[dict[str, Any]]:
    parent_bbox = _bbox(region.get("bbox") or region.get("precise_bbox"))
    if not parent_bbox:
        return []
    items: list[dict[str, Any]] = []
    for item_id in region.get("item_ids") or []:
        item = items_by_id.get(str(item_id))
        item_bbox = _bbox(item.get("bbox")) if isinstance(item, dict) else None
        if not item_bbox or not _bbox_substantially_inside_parent(parent_bbox, item_bbox):
            continue
        items.append(item)
    if len(items) < 2:
        return []

    ordered = sorted(items, key=lambda item: (_bbox(item.get("bbox"))["x"], _bbox(item.get("bbox"))["y"]))
    separator_x = _stage1_5_inner_vertical_separator(
        source_image_path=source_image_path,
        screen_size=screen_size,
        parent_bbox=parent_bbox,
    )
    if separator_x is not None:
        left_items = [
            item
            for item in ordered
            if _bbox(item.get("bbox"))["x"] + _bbox(item.get("bbox"))["w"] / 2 < separator_x
        ]
        right_items = [item for item in ordered if item not in left_items]
        minimum_x = parent_bbox["x"] + int(parent_bbox["w"] * 0.1)
        maximum_x = parent_bbox["x"] + int(parent_bbox["w"] * 0.9)
        if not left_items or not right_items or not minimum_x <= separator_x <= maximum_x:
            separator_x = None

    split_candidates: list[tuple[int, int, list[dict[str, Any]], list[dict[str, Any]]]] = []
    if separator_x is None:
        for index in range(1, len(ordered)):
            left = ordered[:index]
            right = ordered[index:]
            left_right = max(_bbox(item.get("bbox"))["x"] + _bbox(item.get("bbox"))["w"] for item in left)
            right_left = min(_bbox(item.get("bbox"))["x"] for item in right)
            gap = right_left - left_right
            split_x = left_right + max(0, gap // 2)
            minimum_x = parent_bbox["x"] + int(parent_bbox["w"] * 0.1)
            maximum_x = parent_bbox["x"] + int(parent_bbox["w"] * 0.9)
            if gap < max(24, int(parent_bbox["w"] * 0.03)):
                continue
            if not minimum_x <= split_x <= maximum_x:
                continue
            split_candidates.append((gap, split_x, left, right))
        if not split_candidates:
            return []
        _, separator_x, left_items, right_items = max(
            split_candidates,
            key=lambda candidate: (candidate[0], min(len(candidate[2]), len(candidate[3]))),
        )

    split_x = separator_x
    parent_right = parent_bbox["x"] + parent_bbox["w"]
    pane_specs = [
        (
            "list_pane",
            "Stage1.5 list/work pane",
            {**parent_bbox, "w": split_x - parent_bbox["x"]},
            left_items,
        ),
        (
            "detail_pane",
            "Stage1.5 detail/work pane",
            {
                "x": split_x,
                "y": parent_bbox["y"],
                "w": parent_right - split_x,
                "h": parent_bbox["h"],
            },
            right_items,
        ),
    ]
    return [
        _stage1_5_subregion(
            region=region,
            role=role,
            label=label,
            bbox=bbox,
            item_ids=[str(item.get("item_id") or item.get("candidate_id") or "") for item in pane_items],
            source_issue="primary_contains_multiple_work_panes",
            reason="geometry_split_without_chat_semantic_evidence",
        )
        for role, label, bbox, pane_items in pane_specs
    ]


def _stage1_5_chat_subregions(
    *,
    region: dict[str, Any],
    items_by_id: dict[str, dict[str, Any]],
    source_image_path: str,
    screen_size: dict[str, int],
) -> list[dict[str, Any]]:
    parent_bbox = _bbox(region.get("bbox") or region.get("precise_bbox"))
    if not parent_bbox:
        return []
    inner_separator_x = _stage1_5_inner_vertical_separator(
        source_image_path=source_image_path,
        screen_size=screen_size,
        parent_bbox=parent_bbox,
    )
    right_separator_x = _stage1_5_right_vertical_separator(
        source_image_path=source_image_path,
        screen_size=screen_size,
        parent_bbox=parent_bbox,
        left_separator_x=inner_separator_x,
    )
    groups: dict[str, list[dict[str, Any]]] = {
        "conversation_list": [],
        "message_thread": [],
        "bottom_composer": [],
        "auxiliary_pane": [],
    }
    item_ids = region.get("item_ids") if isinstance(region.get("item_ids"), list) else []
    for item_id in item_ids:
        item = items_by_id.get(str(item_id))
        if not isinstance(item, dict):
            continue
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            continue
        if _is_bottom_bar_section_item(item):
            if _clip_bbox_to_parent(bbox, parent_bbox):
                groups["bottom_composer"].append(item)
            continue
        if not _bbox_substantially_inside_parent(parent_bbox, bbox):
            continue
        center_x = bbox["x"] + bbox["w"] / 2
        if right_separator_x is not None and center_x >= right_separator_x:
            groups["auxiliary_pane"].append(item)
            continue
        role = _stage1_5_chat_item_role(item)
        if role:
            groups[role].append(item)
    auxiliary_bbox = _bbox_union([_bbox(item.get("bbox")) for item in groups["auxiliary_pane"]])
    auxiliary_span_is_stable = bool(
        auxiliary_bbox
        and len(groups["auxiliary_pane"]) >= 2
        and auxiliary_bbox["h"] >= max(48, int(parent_bbox["h"] * 0.08))
    )
    if not auxiliary_span_is_stable:
        groups["message_thread"].extend(groups["auxiliary_pane"])
        groups["auxiliary_pane"] = []
        right_separator_x = None
    if not groups["conversation_list"]:
        groups["conversation_list"].extend(
            _infer_stage1_5_left_list_pane_items(region=region, items_by_id=items_by_id, parent_bbox=parent_bbox)
        )
    _promote_stage1_5_message_context_items(
        groups=groups,
        region=region,
        items_by_id=items_by_id,
        parent_bbox=parent_bbox,
    )
    _promote_stage1_5_composer_adjacent_items(
        groups=groups,
        region=region,
        items_by_id=items_by_id,
        parent_bbox=parent_bbox,
    )
    horizontal_composer_separator_y = _stage1_5_chat_composer_separator(
        source_image_path=source_image_path,
        screen_size=screen_size,
        parent_bbox=parent_bbox,
        composer_items=groups["bottom_composer"],
    )
    raw_composer_bbox = _clip_bbox_to_parent(
        _bbox_union([_bbox(item.get("bbox")) for item in groups["bottom_composer"]]),
        parent_bbox,
    )
    composer_evidence_bbox = _clip_bbox_to_parent(
        _bbox_union(
            [
                _bbox(item.get("bbox"))
                for item in groups["bottom_composer"]
                if not _is_bottom_bar_section_item(item)
            ]
        ),
        parent_bbox,
    )
    minimum_composer_y = parent_bbox["y"] + int(parent_bbox["h"] * 0.68)
    composer_validation_bbox = composer_evidence_bbox or raw_composer_bbox
    if composer_validation_bbox and composer_validation_bbox["y"] < minimum_composer_y:
        groups["bottom_composer"] = []
    labels = {
        "conversation_list": "Stage1.5 conversation/list pane",
        "message_thread": "Stage1.5 message/detail pane",
        "bottom_composer": "Stage1.5 bottom composer",
        "auxiliary_pane": "Stage1.5 auxiliary pane",
    }
    subregions: list[dict[str, Any]] = []
    bottom_composer_bbox = _clip_bbox_to_parent(
        _bbox_union([_bbox(item.get("bbox")) for item in groups["bottom_composer"]]),
        parent_bbox,
    )
    bottom_composer_cut_top = (
        horizontal_composer_separator_y
        if horizontal_composer_separator_y is not None
        else (bottom_composer_bbox["y"] if bottom_composer_bbox else None)
    )
    if bottom_composer_bbox:
        composer_evidence_boxes = [
            _bbox(item.get("bbox"))
            for item in groups["bottom_composer"]
            if not _is_bottom_bar_section_item(item)
        ]
        composer_evidence_boxes = [box for box in composer_evidence_boxes if box]
        composer_evidence_bbox = _clip_bbox_to_parent(_bbox_union(composer_evidence_boxes), parent_bbox)
        if composer_evidence_bbox:
            raw_bottom = bottom_composer_bbox["y"] + bottom_composer_bbox["h"]
            evidence_bottom = composer_evidence_bbox["y"] + composer_evidence_bbox["h"]
            top_overreach = max(0, composer_evidence_bbox["y"] - bottom_composer_bbox["y"])
            bottom_overreach = max(0, raw_bottom - evidence_bottom)
            vertical_threshold = max(8, int(parent_bbox["h"] * 0.008))
            minimum_evidence_height = max(48, int(parent_bbox["h"] * 0.05))
            if (
                top_overreach + bottom_overreach > vertical_threshold
                and composer_evidence_bbox["h"] >= minimum_evidence_height
                and horizontal_composer_separator_y is None
            ):
                bottom_composer_cut_top = composer_evidence_bbox["y"]
    message_thread_anchor_bbox = _clip_bbox_to_parent(
        _bbox_union([_bbox(item.get("bbox")) for item in groups["message_thread"]]),
        parent_bbox,
    )
    has_list_and_thread = bool(groups["conversation_list"] and groups["message_thread"])
    semantic_separator_x = message_thread_anchor_bbox["x"] if message_thread_anchor_bbox and has_list_and_thread else None
    pane_separator_x = (inner_separator_x or semantic_separator_x) if has_list_and_thread else None
    if pane_separator_x is not None:
        minimum_pane_x = parent_bbox["x"] + max(48, int(parent_bbox["w"] * 0.08))
        maximum_pane_x = parent_bbox["x"] + int(parent_bbox["w"] * 0.72)
        if not minimum_pane_x <= pane_separator_x <= maximum_pane_x:
            pane_separator_x = None
    boundary_reviews: dict[str, dict[str, Any]] = {}
    vertical_reviews: dict[str, dict[str, Any]] = {}
    for role, items in groups.items():
        boxes = [_bbox(item.get("bbox")) for item in items]
        boxes = [box for box in boxes if box]
        bbox = _clip_bbox_to_parent(_bbox_union(boxes), parent_bbox)
        if not bbox:
            continue
        if role == "conversation_list" and message_thread_anchor_bbox:
            list_left = parent_bbox["x"]
            list_right = message_thread_anchor_bbox["x"]
            list_width = list_right - list_left
            max_list_width = max(220, int(parent_bbox["w"] * 0.48))
            if 80 <= list_width <= max_list_width and list_right > bbox["x"]:
                bbox = {**bbox, "x": list_left, "w": list_width}
        if role == "bottom_composer" and message_thread_anchor_bbox:
            message_left = message_thread_anchor_bbox["x"]
            message_right = message_thread_anchor_bbox["x"] + message_thread_anchor_bbox["w"]
            raw_right = bbox["x"] + bbox["w"]
            horizontal_margin = max(16, int(parent_bbox["w"] * 0.03))
            overreaches_message_channel = (
                bbox["x"] < message_left - horizontal_margin
                or raw_right > message_right + horizontal_margin
            )
            constrained_width = message_right - message_left
            if overreaches_message_channel and constrained_width >= 80:
                previous_bbox = deepcopy(bbox)
                bbox = {**bbox, "x": message_left, "w": constrained_width}
                boundary_reviews[role] = {
                    "contract_version": "learn_stage1_5_boundary_review_v1",
                    "status": "composer_bbox_constrained_to_message_channel",
                    "reason": "bottom_composer_shell_overreached_sibling_conversation_or_right_channel",
                    "previous_bbox": previous_bbox,
                    "constrained_bbox": deepcopy(bbox),
                    "message_channel_bbox": deepcopy(message_thread_anchor_bbox),
                    "policy": "chat_bottom_composer_main_bbox_should_follow_active_message_thread_channel_when_sibling_panes_exist",
                    "review_required": True,
                }
            evidence_boxes = [
                _bbox(item.get("bbox"))
                for item in items
                if not _is_bottom_bar_section_item(item)
            ]
            evidence_boxes = [box for box in evidence_boxes if box]
            evidence_bbox = _clip_bbox_to_parent(_bbox_union(evidence_boxes), parent_bbox)
            if evidence_bbox:
                raw_bottom = bbox["y"] + bbox["h"]
                evidence_bottom = evidence_bbox["y"] + evidence_bbox["h"]
                top_overreach = max(0, evidence_bbox["y"] - bbox["y"])
                bottom_overreach = max(0, raw_bottom - evidence_bottom)
                vertical_threshold = max(8, int(parent_bbox["h"] * 0.008))
                minimum_evidence_height = max(48, int(parent_bbox["h"] * 0.05))
                if (
                    top_overreach + bottom_overreach > vertical_threshold
                    and evidence_bbox["h"] >= minimum_evidence_height
                ):
                    previous_bbox = deepcopy(bbox)
                    bbox = {**bbox, "y": evidence_bbox["y"], "h": evidence_bbox["h"]}
                    vertical_reviews[role] = {
                        "contract_version": "learn_stage1_5_vertical_review_v1",
                        "status": "composer_bbox_constrained_to_evidence_vertical_span",
                        "reason": "coarse_bottom_composer_shell_exceeded_non_shell_composer_evidence",
                        "previous_bbox": previous_bbox,
                        "constrained_bbox": deepcopy(bbox),
                        "evidence_bbox": deepcopy(evidence_bbox),
                        "excluded_shell_item_ids": [
                            str(item.get("item_id") or item.get("candidate_id") or "")
                            for item in items
                            if _is_bottom_bar_section_item(item)
                        ],
                        "policy": "chat_bottom_composer_vertical_bbox_should_follow_non_shell_tool_input_send_evidence_when_available",
                        "review_required": True,
                    }
                elif top_overreach or bottom_overreach:
                    vertical_reviews[role] = {
                        "contract_version": "learn_stage1_5_vertical_review_v1",
                        "status": "composer_vertical_evidence_aligned_or_below_constraint_threshold",
                        "reason": "coarse_bottom_composer_shell_only_slightly_exceeds_non_shell_composer_evidence",
                        "shell_bbox": deepcopy(bbox),
                        "evidence_bbox": deepcopy(evidence_bbox),
                        "top_overreach": top_overreach,
                        "bottom_overreach": bottom_overreach,
                        "vertical_threshold": vertical_threshold,
                        "review_required": True,
                    }
            if horizontal_composer_separator_y is not None:
                previous_bbox = deepcopy(bbox)
                parent_bottom = parent_bbox["y"] + parent_bbox["h"]
                bbox = {
                    **bbox,
                    "y": horizontal_composer_separator_y,
                    "h": parent_bottom - horizontal_composer_separator_y,
                }
                vertical_reviews[role] = {
                    "contract_version": "learn_stage1_5_vertical_review_v1",
                    "status": "composer_boundary_anchored_to_current_pixel_separator",
                    "reason": "horizontal_separator_with_factual_composer_evidence_below_boundary",
                    "previous_bbox": previous_bbox,
                    "constrained_bbox": deepcopy(bbox),
                    "separator_y": horizontal_composer_separator_y,
                    "policy": "semantic_only_input_candidates_must_not_override_current_pixel_separator_evidence",
                    "review_required": True,
                }
        if role == "message_thread":
            bbox = _stage1_5_message_thread_review_bbox(
                bbox=bbox,
                parent_bbox=parent_bbox,
                context_already_included=any(_looks_like_stage1_5_message_context_item(item) for item in items),
                allow_horizontal_expansion=not bool(groups.get("conversation_list")),
            )
        if pane_separator_x is not None and role == "conversation_list":
            bbox = {
                "x": parent_bbox["x"],
                "y": parent_bbox["y"],
                "w": pane_separator_x - parent_bbox["x"],
                "h": parent_bbox["h"],
            }
        elif pane_separator_x is not None and role == "message_thread":
            parent_right = right_separator_x or (parent_bbox["x"] + parent_bbox["w"])
            target_bottom = bottom_composer_cut_top or (parent_bbox["y"] + parent_bbox["h"])
            bbox = {
                "x": pane_separator_x,
                "y": parent_bbox["y"],
                "w": parent_right - pane_separator_x,
                "h": target_bottom - parent_bbox["y"],
            }
        elif pane_separator_x is not None and role == "bottom_composer":
            parent_right = right_separator_x or (parent_bbox["x"] + parent_bbox["w"])
            bbox = {
                **bbox,
                "x": pane_separator_x,
                "w": parent_right - pane_separator_x,
            }
        elif right_separator_x is not None and role == "auxiliary_pane":
            parent_right = parent_bbox["x"] + parent_bbox["w"]
            bbox = {
                "x": right_separator_x,
                "y": parent_bbox["y"],
                "w": parent_right - right_separator_x,
                "h": parent_bbox["h"],
            }
        if role == "message_thread" and bottom_composer_cut_top is not None:
            target_bottom = bottom_composer_cut_top
            if target_bottom > bbox["y"]:
                bbox = {**bbox, "h": target_bottom - bbox["y"]}
        subregion = _stage1_5_subregion(
            region=region,
            role=role,
            label=labels[role],
            bbox=bbox,
            item_ids=[str(item.get("item_id") or item.get("candidate_id") or "") for item in items],
            source_issue="primary_contains_multiple_work_panes",
            reason=f"{role}_semantic_evidence_inside_primary",
        )
        if role in boundary_reviews:
            subregion["stage1_5_boundary_review"] = boundary_reviews[role]
            subregion["review_required"] = True
        if role in vertical_reviews:
            subregion["stage1_5_vertical_review"] = vertical_reviews[role]
            subregion["review_required"] = True
        subregions.append(subregion)
    if pane_separator_x is not None:
        _assign_stage1_5_items_by_geometry(
            subregions=subregions,
            region=region,
            items_by_id=items_by_id,
        )
    return subregions


def _stage1_5_chat_composer_separator(
    *,
    source_image_path: str,
    screen_size: dict[str, int],
    parent_bbox: dict[str, int],
    composer_items: list[dict[str, Any]],
) -> int | None:
    factual_boxes = [
        bbox
        for item in composer_items
        if not _stage1_5_model_only_item(item) and not _is_bottom_bar_section_item(item)
        for bbox in [_bbox(item.get("bbox"))]
        if bbox
    ]
    if not factual_boxes:
        return None
    width = _int(screen_size.get("width"))
    height = _int(screen_size.get("height"))
    cuts = detect_horizontal_separator_cuts(
        source_image_path,
        width=width,
        height=height,
    )
    minimum_y = parent_bbox["y"] + int(parent_bbox["h"] * 0.65)
    maximum_y = parent_bbox["y"] + int(parent_bbox["h"] * 0.95)
    first_factual_y = min(box["y"] for box in factual_boxes)
    candidates = [
        cut
        for cut in cuts
        if minimum_y <= _int(cut.get("point")) <= maximum_y
        and _int(cut.get("point")) <= first_factual_y + max(4, int(parent_bbox["h"] * 0.006))
        and any(box["y"] + box["h"] / 2 >= _int(cut.get("point")) for box in factual_boxes)
    ]
    if not candidates:
        return None
    selected = max(
        candidates,
        key=lambda cut: (
            float(cut.get("support") or 0.0),
            _int(cut.get("point")),
        ),
    )
    return _int(selected.get("point")) or None


def _stage1_5_model_only_item(item: dict[str, Any]) -> bool:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    evidence_level = str(item.get("evidence_level") or metadata.get("evidence_level") or "").casefold()
    source = str(item.get("source") or "").casefold()
    item_id = str(item.get("item_id") or item.get("candidate_id") or "").casefold()
    return evidence_level in {"semantic_region_only", "visual_region_only"} or item_id.startswith(
        ("action_screen_", "visual_", "element_")
    ) or source in {
        "screen_reading.ui_elements",
        "top_level.ui.elements",
        "vision_regions_v1",
    }


def _assign_stage1_5_items_by_geometry(
    *,
    subregions: list[dict[str, Any]],
    region: dict[str, Any],
    items_by_id: dict[str, dict[str, Any]],
) -> None:
    for subregion in subregions:
        subregion["item_ids"] = []
    for item_id in region.get("item_ids") or []:
        item_key = str(item_id)
        item = items_by_id.get(item_key)
        item_bbox = _bbox(item.get("bbox")) if isinstance(item, dict) else None
        if not item_bbox:
            continue
        center_x = item_bbox["x"] + item_bbox["w"] / 2
        center_y = item_bbox["y"] + item_bbox["h"] / 2
        candidates = []
        for subregion in subregions:
            subregion_bbox = _bbox(subregion.get("bbox"))
            if not subregion_bbox:
                continue
            contains_center = (
                subregion_bbox["x"] <= center_x <= subregion_bbox["x"] + subregion_bbox["w"]
                and subregion_bbox["y"] <= center_y <= subregion_bbox["y"] + subregion_bbox["h"]
            )
            if contains_center:
                candidates.append(subregion)
        if not candidates:
            continue
        owner = min(
            candidates,
            key=lambda candidate: (
                _bbox(candidate.get("bbox"))["w"] * _bbox(candidate.get("bbox"))["h"],
                str(candidate.get("subregion_id") or ""),
            ),
        )
        owner["item_ids"].append(item_key)


def _stage1_5_inner_vertical_separator(
    *,
    source_image_path: str,
    screen_size: dict[str, int],
    parent_bbox: dict[str, int],
) -> int | None:
    width = _int(screen_size.get("width"))
    height = _int(screen_size.get("height"))
    if width <= 0 or height <= 0:
        return None
    parent_left = parent_bbox["x"]
    parent_right = parent_left + parent_bbox["w"]
    minimum_x = parent_left + max(48, int(parent_bbox["w"] * 0.08))
    maximum_x = min(parent_right - 48, parent_left + int(parent_bbox["w"] * 0.55))
    eligible = [
        cut
        for cut in detect_vertical_separator_cuts(
            source_image_path,
            width=width,
            height=height,
            maximum_x_ratio=0.65,
        )
        if minimum_x <= _int(cut.get("point")) <= maximum_x
    ]
    if not eligible:
        return None
    selected = max(
        eligible,
        key=lambda cut: (
            float(cut.get("support") or 0.0),
            float(cut.get("score") or 0.0),
            -abs(_int(cut.get("point")) - int(parent_left + parent_bbox["w"] * 0.3)),
        ),
    )
    return _int(selected.get("point")) or None


def _stage1_5_right_vertical_separator(
    *,
    source_image_path: str,
    screen_size: dict[str, int],
    parent_bbox: dict[str, int],
    left_separator_x: int | None,
) -> int | None:
    width = _int(screen_size.get("width"))
    height = _int(screen_size.get("height"))
    if width <= 0 or height <= 0 or left_separator_x is None:
        return None
    parent_left = parent_bbox["x"]
    parent_right = parent_left + parent_bbox["w"]
    minimum_x = max(
        left_separator_x + max(96, int(parent_bbox["w"] * 0.18)),
        parent_left + int(parent_bbox["w"] * 0.55),
    )
    maximum_x = parent_right - max(48, int(parent_bbox["w"] * 0.08))
    eligible = [
        cut
        for cut in detect_vertical_separator_cuts(
            source_image_path,
            width=width,
            height=height,
            maximum_x_ratio=1.0,
        )
        if minimum_x <= _int(cut.get("point")) <= maximum_x
    ]
    if not eligible:
        return None
    selected = max(
        eligible,
        key=lambda cut: (
            float(cut.get("support") or 0.0),
            float(cut.get("score") or 0.0),
            _int(cut.get("point")),
        ),
    )
    return _int(selected.get("point")) or None


def _stage1_5_chat_item_role(item: dict[str, Any]) -> str:
    value = " ".join(
        str(item.get(key) or "").casefold()
        for key in ("item_id", "role", "item_type", "label")
    )
    if any(token in value for token in ("conversation", "chat list", "session list", "会话", "联系人", "list_pane")):
        return "conversation_list"
    if any(
        token in value
        for token in (
            "message_thread",
            "chat thread",
            "message_card",
            "message_text",
            "image_message",
            "forwarded",
            "sticker",
            "bubble",
            "消息",
            "聊天",
            "detail_pane",
        )
    ):
        return "message_thread"
    if any(token in value for token in ("composer", "input area", "send button", "输入框", "发送", "input_area")):
        return "bottom_composer"
    return ""


def _is_bottom_bar_section_item(item: dict[str, Any]) -> bool:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    value = " ".join(
        [
            str(item.get("item_id") or ""),
            str(item.get("role") or ""),
            str(item.get("item_type") or ""),
            str(metadata.get("surface_zone") or ""),
        ]
    ).casefold()
    return "bottom_bar" in value


def _promote_stage1_5_message_context_items(
    *,
    groups: dict[str, list[dict[str, Any]]],
    region: dict[str, Any],
    items_by_id: dict[str, dict[str, Any]],
    parent_bbox: dict[str, int],
) -> None:
    message_bbox = _clip_bbox_to_parent(
        _bbox_union([_bbox(item.get("bbox")) for item in groups.get("message_thread", [])]),
        parent_bbox,
    )
    if not message_bbox:
        return
    item_ids = region.get("item_ids") if isinstance(region.get("item_ids"), list) else []
    existing_ids = {
        str(item.get("item_id") or item.get("candidate_id") or "")
        for role in ("message_thread", "bottom_composer")
        for item in groups.get(role, [])
    }
    promoted_ids: set[str] = set()
    for item_id in item_ids:
        item_key = str(item_id)
        if item_key in existing_ids:
            continue
        item = items_by_id.get(item_key)
        if not isinstance(item, dict):
            continue
        bbox = _bbox(item.get("bbox"))
        if not bbox or not _bbox_substantially_inside_parent(parent_bbox, bbox):
            continue
        if not _looks_like_stage1_5_message_context_item(item):
            continue
        if not _bbox_near_stage1_5_message_thread_context(
            bbox=bbox,
            message_bbox=message_bbox,
            parent_bbox=parent_bbox,
        ):
            continue
        groups.setdefault("message_thread", []).append(item)
        promoted_ids.add(item_key)
    if not promoted_ids:
        return
    for role in ("conversation_list", "bottom_composer"):
        groups[role] = [
            item
            for item in groups.get(role, [])
            if str(item.get("item_id") or item.get("candidate_id") or "") not in promoted_ids
        ]


def _looks_like_stage1_5_message_context_item(item: dict[str, Any]) -> bool:
    label = str(item.get("label") or "").strip()
    if _looks_like_timestamp_label(label):
        return True
    return _looks_like_sender_or_level_context(item)


def _bbox_near_stage1_5_message_thread_context(
    *,
    bbox: dict[str, int],
    message_bbox: dict[str, int],
    parent_bbox: dict[str, int],
) -> bool:
    vertical_margin = max(56, int(parent_bbox["h"] * 0.08))
    message_top = message_bbox["y"]
    message_bottom = message_bbox["y"] + message_bbox["h"]
    candidate_bottom = bbox["y"] + bbox["h"]
    near_vertical_band = candidate_bottom >= message_top - vertical_margin and bbox["y"] <= message_bottom + vertical_margin
    if not near_vertical_band:
        return False
    center_x = bbox["x"] + bbox["w"] / 2
    message_left = message_bbox["x"] - max(24, int(message_bbox["w"] * 0.08))
    message_right = message_bbox["x"] + message_bbox["w"] + max(24, int(message_bbox["w"] * 0.08))
    horizontal_gap = max(0, max(bbox["x"], message_bbox["x"]) - min(bbox["x"] + bbox["w"], message_bbox["x"] + message_bbox["w"]))
    if horizontal_gap <= max(56, int(parent_bbox["w"] * 0.08)):
        return True
    return _horizontal_overlap_ratio(bbox, message_bbox) >= 0.18 or message_left <= center_x <= message_right


def _stage1_5_message_thread_review_bbox(
    *,
    bbox: dict[str, int],
    parent_bbox: dict[str, int],
    context_already_included: bool = False,
    allow_horizontal_expansion: bool = True,
) -> dict[str, int]:
    horizontal_padding = max(72, int(parent_bbox["w"] * 0.08)) if allow_horizontal_expansion else 0
    vertical_padding = max(48, int(parent_bbox["h"] * 0.06))
    parent_right = parent_bbox["x"] + parent_bbox["w"]
    parent_bottom = parent_bbox["y"] + parent_bbox["h"]
    left = max(parent_bbox["x"], bbox["x"] - horizontal_padding)
    top_padding = 0 if context_already_included else vertical_padding
    top = max(parent_bbox["y"], bbox["y"] - top_padding)
    right = min(parent_right, bbox["x"] + bbox["w"] + horizontal_padding)
    bottom = min(parent_bottom, bbox["y"] + bbox["h"] + vertical_padding)
    if right <= left or bottom <= top:
        return bbox
    return {"x": left, "y": top, "w": right - left, "h": bottom - top}


def _promote_stage1_5_composer_adjacent_items(
    *,
    groups: dict[str, list[dict[str, Any]]],
    region: dict[str, Any],
    items_by_id: dict[str, dict[str, Any]],
    parent_bbox: dict[str, int],
) -> None:
    composer_bbox = _clip_bbox_to_parent(
        _bbox_union([_bbox(item.get("bbox")) for item in groups.get("bottom_composer", [])]),
        parent_bbox,
    )
    if not composer_bbox:
        return
    item_ids = region.get("item_ids") if isinstance(region.get("item_ids"), list) else []
    promoted_ids: set[str] = set()
    existing_composer_ids = {
        str(item.get("item_id") or item.get("candidate_id") or "")
        for item in groups.get("bottom_composer", [])
    }
    for item_id in item_ids:
        item_key = str(item_id)
        if item_key in existing_composer_ids:
            continue
        item = items_by_id.get(item_key)
        if not isinstance(item, dict):
            continue
        bbox = _bbox(item.get("bbox"))
        if not bbox or not _bbox_substantially_inside_parent(parent_bbox, bbox):
            continue
        if not _looks_like_stage1_5_composer_tool_item(item):
            continue
        if not _bbox_near_stage1_5_bottom_composer(bbox=bbox, composer_bbox=composer_bbox, parent_bbox=parent_bbox):
            continue
        groups.setdefault("bottom_composer", []).append(item)
        promoted_ids.add(item_key)
    if not promoted_ids:
        return
    for role in ("conversation_list", "message_thread"):
        groups[role] = [
            item
            for item in groups.get(role, [])
            if str(item.get("item_id") or item.get("candidate_id") or "") not in promoted_ids
        ]


def _looks_like_stage1_5_composer_tool_item(item: dict[str, Any]) -> bool:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    value = " ".join(
        [
            str(item.get("item_id") or ""),
            str(item.get("role") or ""),
            str(item.get("item_type") or ""),
            str(item.get("label") or ""),
            str(metadata.get("description") or ""),
            str(metadata.get("surface_zone") or ""),
        ]
    ).casefold()
    if any(
        token in value
        for token in (
            "composer",
            "input area",
            "send",
            "toolbar",
            "tool",
            "attach",
            "attachment",
            "emoji",
            "voice",
            "microphone",
            "file",
            "image",
            "photo",
            "sticker",
            "reaction",
            "输入",
            "发送",
            "工具",
            "附件",
            "表情",
            "语音",
            "麦克风",
            "文件",
            "图片",
            "剪刀",
        )
    ):
        return True
    return _looks_like_stage1_5_short_icon_glyph(item)


def _looks_like_stage1_5_short_icon_glyph(item: dict[str, Any]) -> bool:
    label = str(item.get("label") or "").strip()
    if not label or len(label) > 6:
        return False
    role_value = " ".join(str(item.get(key) or "").casefold() for key in ("role", "item_type"))
    if not any(token in role_value for token in ("text", "readable", "ocr", "icon", "button")):
        return False
    letters_or_digits = sum(1 for char in label if char.isalnum())
    symbol_or_mark = sum(
        1
        for char in label
        if unicodedata.category(char).startswith(("P", "S", "M"))
    )
    if symbol_or_mark == 0:
        return False
    return letters_or_digits <= max(1, len(label) // 2)


def _bbox_near_stage1_5_bottom_composer(
    *,
    bbox: dict[str, int],
    composer_bbox: dict[str, int],
    parent_bbox: dict[str, int],
) -> bool:
    composer_top = composer_bbox["y"]
    composer_bottom = composer_bbox["y"] + composer_bbox["h"]
    vertical_margin = max(36, int(composer_bbox["h"] * 0.65), int(parent_bbox["h"] * 0.04))
    candidate_bottom = bbox["y"] + bbox["h"]
    within_vertical_band = candidate_bottom >= composer_top - vertical_margin and bbox["y"] <= composer_bottom
    if not within_vertical_band:
        return False
    horizontal_overlap = _horizontal_overlap_ratio(bbox, composer_bbox)
    center_x = bbox["x"] + bbox["w"] / 2
    composer_left = composer_bbox["x"] - 32
    composer_right = composer_bbox["x"] + composer_bbox["w"] + 32
    horizontally_aligned = horizontal_overlap >= 0.35 or composer_left <= center_x <= composer_right
    if not horizontally_aligned:
        return False
    return bbox["h"] <= max(80, int(composer_bbox["h"] * 1.1))


def _infer_stage1_5_left_list_pane_items(
    *,
    region: dict[str, Any],
    items_by_id: dict[str, dict[str, Any]],
    parent_bbox: dict[str, int],
) -> list[dict[str, Any]]:
    item_ids = region.get("item_ids") if isinstance(region.get("item_ids"), list) else []
    left_limit = parent_bbox["x"] + min(max(180, int(parent_bbox["w"] * 0.38)), 320)
    top_skip = parent_bbox["y"] + 36
    bottom_skip = parent_bbox["y"] + parent_bbox["h"] - 90
    candidates: list[dict[str, Any]] = []
    for item_id in item_ids:
        item = items_by_id.get(str(item_id))
        if not isinstance(item, dict) or _is_section_hint(item):
            continue
        bbox = _bbox(item.get("bbox"))
        if not bbox or not _bbox_substantially_inside_parent(parent_bbox, bbox):
            continue
        if bbox["y"] < top_skip or bbox["y"] > bottom_skip:
            continue
        center_x = bbox["x"] + bbox["w"] / 2
        if center_x > left_limit:
            continue
        value = " ".join(str(item.get(key) or "").casefold() for key in ("item_id", "role", "item_type", "label"))
        if any(
            token in value
            for token in (
                "message_thread",
                "message_text",
                "image_message",
                "message_card",
                "sticker",
                "bubble",
                "composer",
                "send button",
                "发送",
                "群公告",
            )
        ):
            continue
        candidates.append(item)
    if len(candidates) < 3:
        return []
    return candidates


def _stage1_5_subregion(
    *,
    region: dict[str, Any],
    role: str,
    label: str,
    bbox: dict[str, int],
    item_ids: list[str],
    source_issue: str,
    reason: str,
) -> dict[str, Any]:
    region_id = str(region.get("region_id") or "")
    return {
        "contract_version": "learn_stage1_5_subregion_v1",
        "subregion_id": f"{region_id}__stage1_5__{role}",
        "parent_region_id": region_id,
        "parent_region_bbox": deepcopy(_bbox(region.get("bbox") or region.get("precise_bbox")) or {}),
        "role": role,
        "label": label,
        "bbox": deepcopy(bbox),
        "item_ids": [item_id for item_id in item_ids if item_id],
        "source_issue": source_issue,
        "reason": reason,
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "pathgraph_candidate": False,
    }


def _bbox_inside(parent: dict[str, int], child: dict[str, int]) -> bool:
    return (
        child["x"] >= parent["x"]
        and child["y"] >= parent["y"]
        and child["x"] + child["w"] <= parent["x"] + parent["w"]
        and child["y"] + child["h"] <= parent["y"] + parent["h"]
    )


def _bbox_substantially_inside_parent(parent: dict[str, int], child: dict[str, int]) -> bool:
    if _bbox_inside(parent, child):
        return True
    x1 = max(parent["x"], child["x"])
    y1 = max(parent["y"], child["y"])
    x2 = min(parent["x"] + parent["w"], child["x"] + child["w"])
    y2 = min(parent["y"] + parent["h"], child["y"] + child["h"])
    if x2 <= x1 or y2 <= y1:
        return False
    child_area = max(1, child["w"] * child["h"])
    overlap_area = (x2 - x1) * (y2 - y1)
    return overlap_area / child_area >= 0.82


def _clip_bbox_to_parent(bbox: dict[str, int] | None, parent: dict[str, int]) -> dict[str, int] | None:
    if not bbox:
        return None
    x1 = max(parent["x"], bbox["x"])
    y1 = max(parent["y"], bbox["y"])
    x2 = min(parent["x"] + parent["w"], bbox["x"] + bbox["w"])
    y2 = min(parent["y"] + parent["h"], bbox["y"] + bbox["h"])
    if x2 <= x1 or y2 <= y1:
        return None
    return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}


def _normalized_stage2_item_role(
    role: str,
    *,
    region: dict[str, Any],
    class_rule_profile: dict[str, Any],
) -> str:
    normalized = str(role or "review_only")
    if not class_rule_profile.get("allow_chat_semantics"):
        return normalized
    if class_rule_profile.get("primary_content_strategy") != "conversation_rows":
        return normalized
    region_value = " ".join(
        str(region.get(key) or "").casefold()
        for key in ("region_id", "zone_id", "label")
    )
    if "conversation_bottom_panel" not in region_value:
        return normalized
    if normalized.casefold() in {"news_card", "recommendation_item", "card"}:
        return "group_chat_row"
    return normalized


def _normalized_structural_evidence_role(item: dict[str, Any], role: str) -> str:
    structure_text = " ".join(
        str(item.get(key) or "").casefold().replace("-", "_")
        for key in ("item_id", "candidate_id", "element_id", "layout", "section_id", "source")
    )
    if "bottom_bar" in structure_text or "status_bar" in structure_text:
        return "status_bar_evidence"
    return str(role or "review_only")


def _suppress_unsupported_semantic_action_hypotheses(
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    actionable_roles = {
        "button",
        "checkbox",
        "combobox",
        "input",
        "link",
        "menu item",
        "menu_item",
        "radio",
        "select",
        "switch",
        "tab",
    }
    for item in items:
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        role = str(item.get("role") or item.get("item_type") or "").strip().casefold()
        source = str(item.get("source") or "").strip().casefold()
        evidence_level = str(metadata.get("evidence_level") or "").strip().casefold()
        uia_match = metadata.get("uia_match")
        unsupported = (
            source == "screen_reading.ui_elements"
            and role in actionable_roles
            and evidence_level == "semantic_region_only"
            and not uia_match
        )
        if not unsupported:
            kept.append(item)
            continue
        suppressed.append(
            {
                "item_id": str(item.get("item_id") or item.get("candidate_id") or ""),
                "source_item_ids": list(
                    dict.fromkeys(
                        source_id
                        for source_id in (
                            str(item.get("item_id") or item.get("candidate_id") or "").strip(),
                            str(metadata.get("source_id") or "").strip(),
                        )
                        if source_id
                    )
                ),
                "label": str(item.get("label") or item.get("text") or ""),
                "role": role,
                "bbox": deepcopy(item.get("bbox") if isinstance(item.get("bbox"), dict) else {}),
                "source": source,
                "evidence_level": evidence_level,
            }
        )
    return kept, {
        "contract_version": "learn_stage2_unsupported_semantic_action_suppression_v1",
        "suppressed_count": len(suppressed),
        "suppressed_item_ids": [item["item_id"] for item in suppressed],
        "suppressed_items": suppressed,
        "reason": "semantic_action_without_ocr_uia_or_visual_grounding_evidence",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _stage2_numbering(
    localized_regions: list[dict[str, Any]],
    *,
    items_by_id: dict[str, dict[str, Any]],
    supplemental_text_items: list[dict[str, Any]] | None = None,
    image_path: str = "",
    class_rule_profile: dict[str, Any] | None = None,
    surface_adapter_decision: dict[str, Any] | None = None,
    surface_adapter_stage2_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    class_rule_profile = deepcopy(class_rule_profile) if isinstance(class_rule_profile, dict) else {}
    effective_rule_profile = (
        deepcopy(surface_adapter_stage2_policy)
        if isinstance(surface_adapter_stage2_policy, dict)
        else deepcopy(class_rule_profile)
    )
    surface_adapter_decision = (
        deepcopy(surface_adapter_decision)
        if isinstance(surface_adapter_decision, dict)
        else {}
    )
    grayscale_image = _load_stage2_grayscale_image(image_path)
    regions: list[dict[str, Any]] = []
    total = 0
    adapter_excluded_item_ids: set[str] = set()
    for region in localized_regions:
        region_no = _int(region.get("region_no"))
        numbered_items: list[dict[str, Any]] = []
        region_item_ids = region.get("item_ids") if isinstance(region.get("item_ids"), list) else []
        region_items = [items_by_id[str(item_id)] for item_id in region_item_ids if str(item_id) in items_by_id]
        region_items = [item for item in region_items if not _is_section_hint(item)]
        adapter_excluded_item_ids.update(
            str(item.get("item_id") or item.get("candidate_id") or "")
            for item in region_items
            if surface_adapter_excludes_inventory_item(surface_adapter_decision, item)
        )
        region_items = [
            item
            for item in region_items
            if not surface_adapter_excludes_inventory_item(surface_adapter_decision, item)
        ]
        region_items, unsupported_semantic_action_suppression = _suppress_unsupported_semantic_action_hypotheses(
            region_items
        )
        region_bbox = _bbox(region.get("bbox")) or _bbox(region.get("precise_bbox")) or {}
        region_items = [item for item in region_items if _item_belongs_to_region_bbox(item, region_bbox)]
        region_items, structural_container_suppression = (
            _suppress_oversized_stage2_structural_containers(
                region_items,
                region_bbox=region_bbox,
            )
        )
        region_items = _append_supplemental_text_items_for_region(
            region_items,
            supplemental_text_items or [],
            region_bbox=region_bbox,
        )
        adapter_excluded_item_ids.update(
            str(item.get("item_id") or item.get("candidate_id") or "")
            for item in region_items
            if surface_adapter_excludes_inventory_item(surface_adapter_decision, item)
        )
        region_items = [
            item
            for item in region_items
            if not surface_adapter_excludes_inventory_item(surface_adapter_decision, item)
        ]
        region_items, candidate_deduplication = _dedupe_region_items_by_semantic_overlap(region_items)
        region_items, unsupported_semantic_action_suppression = _attach_suppressed_source_lineage(
            region_items,
            unsupported_semantic_action_suppression,
        )
        region_items.sort(key=lambda item: (_bbox_top(item), _bbox_left(item), str(item.get("label") or "")))
        demoted_uia_text_item_ids: list[str] = []
        checked_uia_text_item_ids: list[str] = []
        for item_index, item in enumerate(region_items, start=1):
            bbox = _bbox(item.get("bbox"))
            if not bbox:
                continue
            original_role = str(item.get("role") or item.get("item_type") or "review_only")
            normalized_role = _normalized_stage2_item_role(
                original_role,
                region=region,
                class_rule_profile=effective_rule_profile,
            )
            normalized_role = _normalized_structural_evidence_role(item, normalized_role)
            numbered_item = {
                    "contract_version": "learn_stage2_numbered_item_v1",
                    "number": f"{region_no}.{item_index}",
                    "item_id": str(item.get("item_id") or item.get("candidate_id") or f"item_{region_no}_{item_index}"),
                    "label": str(item.get("label") or item.get("text") or ""),
                    "role": normalized_role,
                    "item_type": str(item.get("item_type") or ""),
                    "bbox": bbox,
                    "merged_source_item_ids": list(
                        dict.fromkeys(
                            str(item_id)
                            for item_id in item.get("merged_source_item_ids", [])
                            if str(item_id).strip()
                        )
                    ),
                    "click_point": deepcopy(item.get("click_point") if isinstance(item.get("click_point"), dict) else {}),
                    "children": _item_children(item),
                    "review_only": bool(item.get("review_only")) or not bool(item.get("grounding_eligible")),
                    "stage": "stage2_region_numbering",
                    "source": "structure_region_item",
                    "bbox_policy": "numbered_region_candidate_hint_only",
                    "display_only": True,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                }
            pixel_corroboration = _uia_text_pixel_corroboration(item, grayscale_image)
            if pixel_corroboration is not None:
                checked_uia_text_item_ids.append(numbered_item["item_id"])
                numbered_item["visual_evidence_status"] = pixel_corroboration
                if pixel_corroboration == "blank_at_capture":
                    numbered_item["render_in_main_overlay"] = False
                    numbered_item["review_only"] = True
                    numbered_item["demotion_reason"] = "uia_text_without_current_pixel_evidence"
                    demoted_uia_text_item_ids.append(numbered_item["item_id"])
            if normalized_role != original_role:
                numbered_item["original_role"] = original_role
                numbered_item["role_normalization_reason"] = (
                    "structural_status_bar_evidence"
                    if normalized_role == "status_bar_evidence"
                    else "conversation_bottom_panel_semantics"
                )
            numbered_items.append(numbered_item)
        stage1_5_subregion = (
            region.get("input_stage1_5_subregion") if isinstance(region.get("input_stage1_5_subregion"), dict) else {}
        )
        stage1_5_role = str(stage1_5_subregion.get("role") or "").casefold()
        numbered_items, stage1_5_semantic_drift = _demote_model_only_composer_cluster(
            numbered_items,
            stage1_5_role=stage1_5_role,
        )
        grouping_strategy = (
            "direct_region_numbering_without_subgrouping"
            if stage1_5_role in {"conversation_list", "bottom_composer"}
            else (
                "primary_region_homogeneous_grouping_with_visual_card_segmenter"
                if _is_primary_region_id(str(region.get("region_id") or ""))
                else "direct_region_numbering_without_subgrouping"
            )
        )
        region_processing_contract = _region_processing_contract(region, grouping_strategy=grouping_strategy)
        subregion_groups = (
            _primary_content_subregion_groups(
                region=region,
                numbered_items=numbered_items,
                class_rule_profile=effective_rule_profile,
                image_path=image_path,
            )
            if grouping_strategy == "primary_region_homogeneous_grouping_with_visual_card_segmenter"
            else []
        )
        main_content_subdivision = _main_content_subdivision_report(region, subregion_groups)
        bar_numbering_report = _bar_numbering_report(region, numbered_items, grouping_strategy=grouping_strategy)
        visual_refinement = {
            "applied": False,
            "reason": "not_applicable_to_primary_region",
            "candidate_count": 0,
        }
        if grouping_strategy == "direct_region_numbering_without_subgrouping":
            numbered_items, visual_refinement = _refine_direct_region_small_controls(
                numbered_items,
                image_path=image_path,
                region_bbox=_direct_region_control_search_bbox(region),
                region_family=_stage1_region_family(region),
            )
            subregion_groups = _semantic_parent_groups(
                region=region,
                numbered_items=numbered_items,
                class_rule_profile=effective_rule_profile,
                image_path=image_path,
            )
            main_content_subdivision = _main_content_subdivision_report(region, subregion_groups)
        elif grouping_strategy == "primary_region_homogeneous_grouping_with_visual_card_segmenter":
            numbered_items, embedded_top_controls = _refine_primary_embedded_top_controls(
                numbered_items,
                image_path=image_path,
                region_bbox=region_bbox,
            )
            configured_chat_semantics = effective_rule_profile.get("allow_chat_semantics")
            local_chat_surface_evidence = _stage2_region_has_chat_surface_evidence(
                region,
                numbered_items,
            )
            if configured_chat_semantics is False:
                chat_semantics_allowed = False
                chat_semantics_reason = "disabled_by_interface_class_rule"
            elif configured_chat_semantics is True:
                chat_semantics_allowed = True
                chat_semantics_reason = "enabled_by_interface_class_rule"
            else:
                chat_semantics_allowed = local_chat_surface_evidence
                chat_semantics_reason = (
                    "enabled_by_local_chat_surface_evidence"
                    if local_chat_surface_evidence
                    else "chat_surface_evidence_missing"
                )
            if effective_rule_profile.get("allow_media_card_synthesis") is False:
                media_card_synthesis = {
                    "applied": False,
                    "reason": "disabled_by_interface_class_rule",
                    "candidate_count": 0,
                }
            else:
                numbered_items, media_card_synthesis = _synthesize_primary_media_cards(
                    numbered_items,
                    image_path=image_path,
                    region_bbox=region_bbox,
                )
            numbered_items, partial_card_synthesis = _synthesize_partial_visible_cards(
                numbered_items,
                image_path=image_path,
                region_bbox=region_bbox,
            )
            if chat_semantics_allowed:
                numbered_items, chat_image_synthesis = _synthesize_chat_image_messages(
                    numbered_items,
                    image_path=image_path,
                    region_bbox=region_bbox,
                    chat_surface_confirmed=stage1_5_role == "message_thread",
                )
            else:
                chat_image_synthesis = {"applied": False, "reason": chat_semantics_reason, "candidate_count": 0}
            numbered_items, text_button_hit_area = _normalize_text_only_button_hit_areas(
                numbered_items,
                region_bbox=region_bbox,
            )
            if chat_semantics_allowed:
                numbered_items, message_bubble_hit_area = _normalize_text_only_message_bubble_backgrounds(
                    numbered_items,
                    region_bbox=region_bbox,
                )
                numbered_items, message_card_boundary_clip = _clip_message_cards_at_following_start_anchors(numbered_items)
            else:
                message_bubble_hit_area = {"applied": False, "reason": chat_semantics_reason, "candidate_count": 0}
                message_card_boundary_clip = {"applied": False, "reason": chat_semantics_reason, "candidate_count": 0}
            numbered_items, dense_document_role_normalization = _normalize_dense_document_semantic_card_roles(
                numbered_items
            )
            subregion_groups = _primary_content_subregion_groups(
                region=region,
                numbered_items=numbered_items,
                class_rule_profile=effective_rule_profile,
                image_path=image_path,
            )
            main_content_subdivision = _main_content_subdivision_report(region, subregion_groups)
            visual_refinement["media_card_synthesis"] = media_card_synthesis
            visual_refinement["embedded_top_control_strip"] = embedded_top_controls
            visual_refinement["partial_visible_card_synthesis"] = partial_card_synthesis
            visual_refinement["chat_image_message_synthesis"] = chat_image_synthesis
            visual_refinement["text_button_hit_area"] = text_button_hit_area
            visual_refinement["message_bubble_hit_area"] = message_bubble_hit_area
            visual_refinement["message_card_boundary_clip"] = message_card_boundary_clip
            visual_refinement["dense_document_semantic_card_normalization"] = dense_document_role_normalization
        ownership_resolution = resolve_group_ownership(subregion_groups)
        ownership_resolution["audit"] = _expand_ownership_source_aliases(
            numbered_items,
            ownership_resolution["audit"],
        )
        subregion_groups = ownership_resolution["accepted_groups"]
        numbered_items = _normalize_tile_group_member_roles(numbered_items, subregion_groups)
        numbered_items, subregion_groups = _apply_semantic_group_child_roles(numbered_items, subregion_groups)
        subregion_groups, group_evidence_reconciliation = _reconcile_subregion_group_display_evidence(
            numbered_items,
            subregion_groups,
        )
        numbered_items, subregion_groups, region_content_boundary = _enforce_region_content_boundary(
            numbered_items,
            subregion_groups,
            region_bbox=region_bbox,
            region_id=str(region.get("region_id") or ""),
            region_label=str(region.get("label") or ""),
        )
        main_content_subdivision = _main_content_subdivision_report(region, subregion_groups)
        evidence_only_visual_candidates = (
            visual_refinement.get("evidence_only_visual_candidates")
            if isinstance(visual_refinement.get("evidence_only_visual_candidates"), list)
            else []
        )
        control_parents = _atomic_control_parent_objects(
            numbered_items=numbered_items,
            visual_candidates=evidence_only_visual_candidates,
            region_bbox=region_bbox,
            region_family=_stage1_region_family(region),
        )
        for control_parent in control_parents:
            control_parent["parent_region_id"] = str(region.get("region_id") or "")
            control_parent["parent_region_label"] = str(region.get("label") or "")
            control_parent["parent_region_bbox"] = deepcopy(region_bbox)
        stage2_streams = _build_stage2_dual_streams(
            numbered_items=numbered_items,
            semantic_groups=subregion_groups,
            ownership_audit=ownership_resolution["audit"],
            visual_candidates=evidence_only_visual_candidates,
            control_parents=control_parents,
        )
        if grouping_strategy == "direct_region_numbering_without_subgrouping":
            bar_numbering_report = _bar_numbering_report(region, numbered_items, grouping_strategy=grouping_strategy)
        total += len(numbered_items)
        regions.append(
            {
                "contract_version": "learn_stage2_numbered_region_v1",
                "region_no": region_no,
                "region_id": str(region.get("region_id") or ""),
                "label": str(region.get("label") or ""),
                "bbox": deepcopy(region.get("bbox") if isinstance(region.get("bbox"), dict) else {}),
                "input_region_bbox": deepcopy(
                    region.get("precise_bbox")
                    if isinstance(region.get("precise_bbox"), dict)
                    else (region.get("bbox") if isinstance(region.get("bbox"), dict) else {})
                ),
                "input_region_localization": deepcopy(
                    region.get("coordinate_validation") if isinstance(region.get("coordinate_validation"), dict) else {}
                ),
                "input_stage1_5_subregion": deepcopy(stage1_5_subregion),
                "grouping_strategy": grouping_strategy,
                "class_rule_profile": deepcopy(class_rule_profile),
                "surface_adapter_processing_policy": deepcopy(effective_rule_profile),
                "region_processing_contract": region_processing_contract,
                "bar_numbering": bar_numbering_report,
                "main_content_subdivision": main_content_subdivision,
                "subregion_groups": subregion_groups,
                "control_parents": control_parents,
                "stage2_streams": stage2_streams,
                "ownership_resolution": ownership_resolution["audit"],
                "region_content_boundary": region_content_boundary,
                "visual_small_control_refinement": visual_refinement,
                "unsupported_semantic_action_suppression": unsupported_semantic_action_suppression,
                "structural_container_suppression": structural_container_suppression,
                "candidate_deduplication": candidate_deduplication,
                "uia_text_pixel_corroboration": {
                    "contract_version": "learn_uia_text_pixel_corroboration_v1",
                    "checked_count": len(checked_uia_text_item_ids),
                    "checked_item_ids": checked_uia_text_item_ids,
                    "demoted_count": len(demoted_uia_text_item_ids),
                    "demoted_item_ids": demoted_uia_text_item_ids,
                    "policy": "uia_only_text_requires_non_uniform_current_capture_pixels_for_main_overlay",
                    "audit_only": True,
                },
                "stage1_5_semantic_drift": stage1_5_semantic_drift,
                "group_evidence_reconciliation": group_evidence_reconciliation,
                "numbered_item_count": len(numbered_items),
                "numbered_items": numbered_items,
                "model_prompt_intent": (
                    "Primary/main content may be split into same-kind card/content rows before numbering; "
                    "header/sidebar regions use direct numbering with gated visual small-control refinement."
                ),
            }
        )
    return {
        "contract_version": "learn_stage2_region_numbering_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "region_count": len(regions),
        "numbered_item_count": total,
        "surface_adapter_filter": {
            "contract_version": "learning_surface_adapter_stage2_filter_v1",
            "adapter_id": str(surface_adapter_decision.get("adapter_id") or "generic"),
            "excluded_item_count": len({value for value in adapter_excluded_item_ids if value}),
            "excluded_item_ids": sorted(value for value in adapter_excluded_item_ids if value),
            "fixed_height_boundary_used": False,
            "app_name_boundary_used": False,
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
        "regions": regions,
    }


def _load_stage2_grayscale_image(image_path: str) -> Image.Image | None:
    path = str(image_path or "").strip()
    if not path:
        return None
    try:
        with Image.open(path) as image:
            return image.convert("L")
    except (FileNotFoundError, OSError, ValueError):
        return None


def _uia_text_pixel_corroboration(item: dict[str, Any], grayscale_image: Image.Image | None) -> str | None:
    if grayscale_image is None or not _is_uia_only_text_item(item):
        return None
    bbox = _bbox(item.get("bbox"))
    if not bbox:
        return None
    left = max(0, bbox["x"])
    top = max(0, bbox["y"])
    right = min(grayscale_image.width, bbox["x"] + bbox["w"])
    bottom = min(grayscale_image.height, bbox["y"] + bbox["h"])
    if right <= left or bottom <= top:
        return "blank_at_capture"
    extrema = grayscale_image.crop((left, top, right, bottom)).getextrema()
    if not isinstance(extrema, tuple) or len(extrema) != 2:
        return None
    return "blank_at_capture" if int(extrema[1]) - int(extrema[0]) <= 4 else "pixel_corroborated"


def _is_uia_only_text_item(item: dict[str, Any]) -> bool:
    role = str(item.get("role") or item.get("item_type") or "").casefold().replace(" ", "_")
    if role not in {"text", "static_text", "label"}:
        return False
    source = str(item.get("source") or "").casefold()
    lineage = [value.casefold() for value in _stage2_source_lineage_ids(item)]
    has_uia = "uia" in source or any(value.startswith(("uia_", "action_uia_")) for value in lineage)
    has_pixel_source = "ocr" in source or "visual" in source or any(
        value.startswith(("page_text_", "ocr_", "visual_", "action_visual_")) for value in lineage
    )
    return has_uia and not has_pixel_source


def _demote_model_only_composer_cluster(
    numbered_items: list[dict[str, Any]],
    *,
    stage1_5_role: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if str(stage1_5_role or "").casefold() != "message_thread":
        return numbered_items, {
            "contract_version": "learn_stage1_5_semantic_drift_v1",
            "applied": False,
            "reason": "not_message_thread",
            "demoted_count": 0,
            "demoted_item_ids": [],
        }

    composer_tokens = (
        "message_input",
        "message input",
        "input_area",
        "input area",
        "bottom_composer",
        "bottom composer",
        "attachment_icon",
        "attachment icon",
        "voice_input",
        "voice input",
        "emoji_icon",
        "emoji icon",
        "camera_icon",
        "camera icon",
    )
    candidates: list[dict[str, Any]] = []
    for item in numbered_items:
        if not isinstance(item, dict) or not _stage1_5_model_only_item(item):
            continue
        semantic_text = " ".join(
            str(item.get(key) or "").casefold()
            for key in ("item_id", "label", "role", "item_type")
        )
        normalized = semantic_text.replace("-", "_")
        if any(token in semantic_text or token in normalized for token in composer_tokens):
            candidates.append(item)

    has_input_area = any(
        any(token in str(item.get("item_id") or "").casefold().replace("-", "_") for token in ("message_input", "input_area"))
        for item in candidates
    )
    if len(candidates) < 3 or not has_input_area:
        return numbered_items, {
            "contract_version": "learn_stage1_5_semantic_drift_v1",
            "applied": False,
            "reason": "no_model_only_composer_cluster",
            "candidate_count": len(candidates),
            "demoted_count": 0,
            "demoted_item_ids": [],
        }

    candidate_ids = {str(item.get("item_id") or "") for item in candidates}
    updated_items: list[dict[str, Any]] = []
    for item in numbered_items:
        updated = dict(item)
        if str(updated.get("item_id") or "") in candidate_ids:
            updated["render_in_main_overlay"] = False
            updated["review_only"] = True
            updated["demotion_reason"] = "model_only_composer_cluster_outside_composer_region"
            updated["semantic_drift"] = "composer_candidate_assigned_to_message_thread"
        updated_items.append(updated)
    return updated_items, {
        "contract_version": "learn_stage1_5_semantic_drift_v1",
        "applied": True,
        "reason": "model_only_composer_cluster_cannot_override_stage1_5_message_thread_boundary",
        "candidate_count": len(candidates),
        "demoted_count": len(candidate_ids),
        "demoted_item_ids": sorted(candidate_ids),
    }


def _reconcile_subregion_group_display_evidence(
    numbered_items: list[dict[str, Any]],
    subregion_groups: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    item_by_alias: dict[str, dict[str, Any]] = {}
    for item in numbered_items:
        if not isinstance(item, dict):
            continue
        aliases = [item.get("item_id"), *(item.get("merged_source_item_ids") or [])]
        for alias in aliases:
            key = str(alias or "").strip()
            if key:
                item_by_alias[key] = item

    reconciled: list[dict[str, Any]] = []
    suppressed_group_ids: list[str] = []
    resized_group_ids: list[str] = []
    unresolved_member_count = 0
    for group in subregion_groups:
        if not isinstance(group, dict):
            continue
        updated = dict(group)
        member_ids = [
            str(item_id or "").strip()
            for item_id in group.get("member_item_ids", [])
            if str(item_id or "").strip()
        ]
        if not member_ids:
            reconciled.append(updated)
            continue
        linked_items: list[dict[str, Any]] = []
        seen: set[str] = set()
        unresolved = 0
        for member_id in member_ids:
            linked = item_by_alias.get(member_id)
            if linked is None:
                unresolved += 1
                continue
            linked_id = str(linked.get("item_id") or member_id)
            if linked_id in seen:
                continue
            seen.add(linked_id)
            linked_items.append(linked)
        unresolved_member_count += unresolved
        renderable = [item for item in linked_items if item.get("render_in_main_overlay") is not False]
        updated["current_evidence_member_count"] = len(renderable)
        updated["unresolved_member_count"] = unresolved
        if not renderable:
            updated["render_in_main_overlay"] = False
            updated["review_only"] = True
            updated["demotion_reason"] = "group_without_renderable_current_evidence"
            suppressed_group_ids.append(str(updated.get("group_id") or ""))
        elif len(renderable) != len(linked_items) or unresolved:
            live_bbox = _bbox_union([item.get("bbox") for item in renderable])
            if live_bbox and live_bbox != _bbox(updated.get("bbox")):
                updated["raw_bbox_before_evidence_reconciliation"] = deepcopy(updated.get("bbox"))
                updated["bbox"] = live_bbox
                updated["bbox_policy"] = "union_of_renderable_current_evidence_members"
                resized_group_ids.append(str(updated.get("group_id") or ""))
        reconciled.append(updated)
    return reconciled, {
        "contract_version": "learn_subregion_group_evidence_reconciliation_v1",
        "suppressed_group_count": len(suppressed_group_ids),
        "suppressed_group_ids": suppressed_group_ids,
        "resized_group_count": len(resized_group_ids),
        "resized_group_ids": resized_group_ids,
        "unresolved_member_count": unresolved_member_count,
        "policy": "semantic_groups_may_render_only_from_current_renderable_member_evidence",
    }


def _dedupe_region_items_by_semantic_overlap(
    items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    suppressed: list[dict[str, Any]] = []
    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue
        item = deepcopy(raw_item)
        label = _normalized_stage2_item_label(item)
        bbox = _bbox(item.get("bbox"))
        duplicate_index = None
        for index, existing in enumerate(deduped):
            if not label or label != _normalized_stage2_item_label(existing):
                continue
            existing_bbox = _bbox(existing.get("bbox"))
            if not bbox or not existing_bbox:
                continue
            if min(_bbox_overlap_ratio(bbox, existing_bbox), _bbox_overlap_ratio(existing_bbox, bbox)) < 0.72:
                continue
            duplicate_index = index
            break
        if duplicate_index is None:
            item["merged_source_item_ids"] = _stage2_source_lineage_ids(item)
            deduped.append(item)
            continue
        existing = deduped[duplicate_index]
        existing_score = _stage2_item_source_quality(existing)
        item_score = _stage2_item_source_quality(item)
        winner, loser = (item, existing) if item_score > existing_score else (existing, item)
        merged_ids = [*_stage2_source_lineage_ids(winner), *_stage2_source_lineage_ids(loser)]
        winner = deepcopy(winner)
        winner["merged_source_item_ids"] = list(dict.fromkeys(item_id for item_id in merged_ids if item_id))
        deduped[duplicate_index] = winner
        suppressed.append(
            {
                "winner_item_id": str(winner.get("item_id") or winner.get("candidate_id") or ""),
                "suppressed_item_id": str(loser.get("item_id") or loser.get("candidate_id") or ""),
                "label": str(winner.get("label") or winner.get("text") or ""),
                "reason": "same_semantic_label_and_overlapping_bbox",
            }
        )
    return deduped, {
        "contract_version": "learn_stage2_candidate_deduplication_v1",
        "input_count": len([item for item in items if isinstance(item, dict)]),
        "output_count": len(deduped),
        "suppressed_duplicate_count": len(suppressed),
        "suppressed_duplicates": suppressed,
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _stage2_source_lineage_ids(item: dict[str, Any]) -> list[str]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return list(
        dict.fromkeys(
            source_id
            for source_id in [
                str(item.get("item_id") or item.get("candidate_id") or "").strip(),
                str(item.get("source_id") or metadata.get("source_id") or "").strip(),
                *[
                    str(source_id).strip()
                    for source_id in item.get("merged_source_item_ids", [])
                    if str(source_id).strip()
                ],
            ]
            if source_id
        )
    )


def _attach_suppressed_source_lineage(
    items: list[dict[str, Any]],
    suppression: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    resolved_items = [deepcopy(item) for item in items if isinstance(item, dict)]
    audit = deepcopy(suppression) if isinstance(suppression, dict) else {}
    resolved: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    suppressed_items = audit.get("suppressed_items") if isinstance(audit.get("suppressed_items"), list) else []
    for suppressed in suppressed_items:
        if not isinstance(suppressed, dict):
            continue
        label = _normalized_stage2_item_label(suppressed)
        bbox = _bbox(suppressed.get("bbox"))
        matches: list[int] = []
        for index, item in enumerate(resolved_items):
            item_bbox = _bbox(item.get("bbox"))
            if not label or label != _normalized_stage2_item_label(item) or not bbox or not item_bbox:
                continue
            if min(_bbox_overlap_ratio(bbox, item_bbox), _bbox_overlap_ratio(item_bbox, bbox)) >= 0.72:
                matches.append(index)
        source_ids = [
            str(source_id).strip()
            for source_id in suppressed.get("source_item_ids", [])
            if str(source_id).strip()
        ] if isinstance(suppressed.get("source_item_ids"), list) else []
        if len(matches) != 1:
            unresolved.append(
                {
                    "suppressed_item_id": str(suppressed.get("item_id") or ""),
                    "source_item_ids": source_ids,
                    "matching_factual_item_count": len(matches),
                    "reason": "source_lineage_requires_unique_same_label_overlapping_factual_item",
                }
            )
            continue
        winner = resolved_items[matches[0]]
        winner_id = str(winner.get("item_id") or winner.get("candidate_id") or "").strip()
        winner["merged_source_item_ids"] = list(
            dict.fromkeys(
                [
                    winner_id,
                    *[
                        str(source_id).strip()
                        for source_id in winner.get("merged_source_item_ids", [])
                        if str(source_id).strip()
                    ],
                    *source_ids,
                ]
            )
        )
        resolved.append(
            {
                "suppressed_item_id": str(suppressed.get("item_id") or ""),
                "source_item_ids": source_ids,
                "winner_item_id": winner_id,
                "reason": "unique_same_label_overlapping_factual_item_preserves_source_lineage",
            }
        )
    audit["source_lineage_resolution_count"] = len(resolved)
    audit["source_lineage_resolutions"] = resolved
    audit["source_lineage_unresolved_count"] = len(unresolved)
    audit["source_lineage_unresolved"] = unresolved
    return resolved_items, audit


def _normalized_stage2_item_label(item: dict[str, Any]) -> str:
    value = str(item.get("label") or item.get("text") or "").casefold()
    return " ".join(value.split()).strip(" .,:;!?-_/\\|()[]{}")


def _stage2_item_source_quality(item: dict[str, Any]) -> tuple[int, int, int]:
    item_id = str(item.get("item_id") or item.get("candidate_id") or "").casefold()
    role = str(item.get("role") or "").casefold()
    item_type = str(item.get("item_type") or "").casefold()
    source_score = 0
    for prefix, score in (
        ("action_uia", 6),
        ("action_screen", 5),
        ("element_", 4),
        ("card_", 3),
        ("page_text", 2),
        ("ocr_text", 1),
        ("text_", 1),
    ):
        if item_id.startswith(prefix):
            source_score = score
            break
    semantic_score = int(item_type == "actionable") * 3 + int(
        role in {"button", "input", "combobox", "listitem", "menu item", "menu_item", "link"}
    ) * 2
    bbox = _bbox(item.get("bbox")) or {"w": 0, "h": 0}
    return source_score, semantic_score, bbox["w"] * bbox["h"]


def _item_belongs_to_region_bbox(item: dict[str, Any], region_bbox: dict[str, int]) -> bool:
    item_bbox = _bbox(item.get("bbox"))
    if not item_bbox or not region_bbox:
        return False
    cx = item_bbox["x"] + item_bbox["w"] / 2
    cy = item_bbox["y"] + item_bbox["h"] / 2
    if (
        region_bbox["x"] <= cx <= region_bbox["x"] + region_bbox["w"]
        and region_bbox["y"] <= cy <= region_bbox["y"] + region_bbox["h"]
    ):
        return True
    return _bbox_containment_ratio(item_bbox, region_bbox) >= 0.55


def _enforce_region_content_boundary(
    numbered_items: list[dict[str, Any]],
    subregion_groups: list[dict[str, Any]],
    *,
    region_bbox: dict[str, int],
    region_id: str = "",
    region_label: str = "",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    if not region_bbox:
        return numbered_items, subregion_groups, {
            "contract_version": "learn_stage2_region_content_boundary_v1",
            "applied": False,
            "reason": "missing_parent_region_bbox",
            "policy": "numbered_items_and_subregion_groups_must_not_extend_outside_parent_region",
            "parent_child_relation_policy": "every_stage2_child_must_name_its_parent_region_before_promotion",
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }

    clipped_items: list[dict[str, Any]] = []
    clipped_item_records: list[dict[str, Any]] = []
    rejected_item_records: list[dict[str, Any]] = []
    for item in numbered_items:
        updated = dict(item)
        updated["parent_region_id"] = region_id
        updated["parent_region_label"] = region_label
        updated["parent_region_bbox"] = deepcopy(region_bbox)
        updated["parent_boundary_relation"] = {
            "contract_version": "learn_stage2_parent_boundary_relation_v1",
            "relation": "child_of_structure_region",
            "parent_region_id": region_id,
            "parent_region_bbox": deepcopy(region_bbox),
            "child_bbox_policy": "must_be_inside_parent_region_after_boundary_enforcement",
            "sibling_overlap_policy": "non_parent_overlap_requires_boundary_review",
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
        bbox = _bbox(updated.get("bbox"))
        if bbox:
            intersection = _intersect_bbox(region_bbox, bbox)
            if not intersection:
                updated["raw_bbox_before_boundary"] = bbox
                updated["bbox"] = {}
                updated["review_required"] = True
                updated["candidate_only"] = True
                updated["parent_boundary_relation"]["child_scope"] = "outside_parent_rejected"
                updated["parent_boundary_relation"]["inside_parent_after_enforcement"] = False
                updated["bbox_boundary_reject"] = {
                    "contract_version": "learn_stage2_region_content_boundary_reject_v1",
                    "source": "region_content_boundary_contract",
                    "reason": "numbered_item_outside_parent_region",
                    "parent_region_bbox": deepcopy(region_bbox),
                    "previous_bbox": bbox,
                    "display_only": True,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                }
                rejected_item_records.append(
                    {
                        "number": updated.get("number"),
                        "item_id": updated.get("item_id"),
                        "label": updated.get("label"),
                        "previous_bbox": bbox,
                    }
                )
                clipped_items.append(updated)
                continue
            clipped = intersection
            updated["parent_boundary_relation"]["child_scope"] = (
                "inside_parent" if clipped == bbox else "clipped_to_parent"
            )
            updated["parent_boundary_relation"]["inside_parent_after_enforcement"] = True
            if clipped != bbox:
                updated["raw_bbox_before_boundary"] = bbox
                updated["bbox"] = clipped
                updated["review_required"] = True
                updated["candidate_only"] = True
                updated["bbox_boundary_clip"] = {
                    "contract_version": "learn_stage2_region_content_boundary_clip_v1",
                    "source": "region_content_boundary_contract",
                    "reason": "numbered_item_must_not_extend_outside_parent_region",
                    "parent_region_bbox": deepcopy(region_bbox),
                    "previous_bbox": bbox,
                    "clipped_bbox": clipped,
                    "display_only": True,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                }
                clipped_item_records.append(
                    {
                        "number": updated.get("number"),
                        "item_id": updated.get("item_id"),
                        "label": updated.get("label"),
                        "previous_bbox": bbox,
                        "clipped_bbox": clipped,
                    }
                )
        clipped_items.append(updated)

    clipped_groups: list[dict[str, Any]] = []
    clipped_group_records: list[dict[str, Any]] = []
    rejected_group_records: list[dict[str, Any]] = []
    for group in subregion_groups:
        updated = dict(group)
        updated["parent_region_id"] = region_id
        updated["parent_region_label"] = region_label
        updated["parent_region_bbox"] = deepcopy(region_bbox)
        updated["parent_boundary_relation"] = {
            "contract_version": "learn_stage2_parent_boundary_relation_v1",
            "relation": "child_group_of_structure_region",
            "parent_region_id": region_id,
            "parent_region_bbox": deepcopy(region_bbox),
            "child_bbox_policy": "must_be_inside_parent_region_after_boundary_enforcement",
            "sibling_overlap_policy": "non_parent_overlap_requires_boundary_review",
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
        bbox = _bbox(updated.get("bbox"))
        if bbox:
            intersection = _intersect_bbox(region_bbox, bbox)
            if not intersection:
                updated["raw_bbox_before_boundary"] = bbox
                updated["bbox"] = {}
                updated["review_required"] = True
                updated["candidate_only"] = True
                updated["parent_boundary_relation"]["child_scope"] = "outside_parent_rejected"
                updated["parent_boundary_relation"]["inside_parent_after_enforcement"] = False
                updated["bbox_boundary_reject"] = {
                    "contract_version": "learn_stage2_region_content_boundary_reject_v1",
                    "source": "region_content_boundary_contract",
                    "reason": "subregion_group_outside_parent_region",
                    "parent_region_bbox": deepcopy(region_bbox),
                    "previous_bbox": bbox,
                    "display_only": True,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                }
                rejected_group_records.append(
                    {
                        "group_id": updated.get("group_id"),
                        "label": updated.get("label"),
                        "previous_bbox": bbox,
                    }
                )
                clipped_groups.append(updated)
                continue
            clipped = intersection
            updated["parent_boundary_relation"]["child_scope"] = (
                "inside_parent" if clipped == bbox else "clipped_to_parent"
            )
            updated["parent_boundary_relation"]["inside_parent_after_enforcement"] = True
            if clipped != bbox:
                updated["raw_bbox_before_boundary"] = bbox
                updated["bbox"] = clipped
                updated["review_required"] = True
                updated["candidate_only"] = True
                updated["bbox_boundary_clip"] = {
                    "contract_version": "learn_stage2_region_content_boundary_clip_v1",
                    "source": "region_content_boundary_contract",
                    "reason": "subregion_group_must_not_extend_outside_parent_region",
                    "parent_region_bbox": deepcopy(region_bbox),
                    "previous_bbox": bbox,
                    "clipped_bbox": clipped,
                    "display_only": True,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                }
                clipped_group_records.append(
                    {
                        "group_id": updated.get("group_id"),
                        "label": updated.get("label"),
                        "previous_bbox": bbox,
                        "clipped_bbox": clipped,
                    }
                )
        clipped_groups.append(updated)

    return clipped_items, clipped_groups, {
        "contract_version": "learn_stage2_region_content_boundary_v1",
        "applied": True,
        "policy": "numbered_items_and_subregion_groups_must_not_extend_outside_parent_region",
        "parent_child_relation_policy": "every_stage2_child_must_name_its_parent_region_before_promotion",
        "parent_region_id": region_id,
        "parent_region_label": region_label,
        "parent_region_bbox": deepcopy(region_bbox),
        "clipped_numbered_item_count": len(clipped_item_records),
        "clipped_subregion_group_count": len(clipped_group_records),
        "rejected_numbered_item_count": len(rejected_item_records),
        "rejected_subregion_group_count": len(rejected_group_records),
        "annotated_numbered_item_count": len(clipped_items),
        "annotated_subregion_group_count": len(clipped_groups),
        "clipped_numbered_items": clipped_item_records,
        "clipped_subregion_groups": clipped_group_records,
        "rejected_numbered_items": rejected_item_records,
        "rejected_subregion_groups": rejected_group_records,
        "child_scope_policy": "children_may_only_overlap_when_the_parent_region_contains_them_after_enforcement",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "interpretation": (
            "Stage2 child boxes remain display-only review evidence and are clipped to the parent structure "
            "region when a model/OCR hint extends across a sibling region boundary."
        ),
    }


def _direct_region_control_search_bbox(region: dict[str, Any]) -> dict[str, int]:
    bbox = _bbox(region.get("bbox")) or _bbox(region.get("precise_bbox")) or {}
    if not bbox:
        return {}
    return bbox


def _region_processing_contract(region: dict[str, Any], *, grouping_strategy: str) -> dict[str, Any]:
    region_id = str(region.get("region_id") or "")
    if grouping_strategy == "primary_region_homogeneous_grouping_with_visual_card_segmenter":
        return {
            "contract_version": "learn_stage2_region_processing_contract_v1",
            "mode": "subdivide_then_number",
            "applies_to": "center_or_main_content",
            "required_sequence": [
                "use_precise_whole_region_bbox",
                "subdivide_main_content",
                "number_items_inside_subregions",
                "preserve_parent_child_relationships",
            ],
            "region_bbox_policy": "do_not_shrink_main_region_to_cards",
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
    return {
        "contract_version": "learn_stage2_region_processing_contract_v1",
        "mode": "direct_numbering_within_precise_region",
        "applies_to": _bar_region_kind(region_id),
        "required_sequence": [
            "use_precise_whole_region_bbox",
            "number_items_inside_bar_region",
            "group_controls_without_changing_region_bbox",
        ],
        "region_bbox_policy": "complete_bar_bbox_spacing_may_group_controls_only",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _bar_numbering_report(
    region: dict[str, Any],
    numbered_items: list[dict[str, Any]],
    *,
    grouping_strategy: str,
) -> dict[str, Any]:
    if grouping_strategy != "direct_region_numbering_without_subgrouping":
        return {
            "contract_version": "learn_stage2_bar_numbering_report_v1",
            "applied": False,
            "reason": "not_a_bar_region",
        }
    bbox = _bbox(region.get("bbox")) or {}
    return {
        "contract_version": "learn_stage2_bar_numbering_report_v1",
        "applied": True,
        "mode": "direct_numbering_within_precise_region",
        "region_bbox": deepcopy(bbox),
        "numbered_item_count": len(numbered_items),
        "spacing_policy": "spacing_may_split_control_groups_but_must_not_shrink_region_bbox",
        "keeps_sparse_icons": True,
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _main_content_subdivision_report(region: dict[str, Any], subregion_groups: list[dict[str, Any]]) -> dict[str, Any]:
    required = _is_primary_region_id(str(region.get("region_id") or ""))
    return {
        "contract_version": "learn_stage2_main_content_subdivision_report_v1",
        "subdivision_required": required,
        "applied": bool(subregion_groups) if required else False,
        "subregion_count": len(subregion_groups),
        "subregion_group_ids": [str(group.get("group_id") or "") for group in subregion_groups if isinstance(group, dict)],
        "policy": "center_main_content_must_subdivide_before_numbering" if required else "not_center_main_content",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _bar_region_kind(region_id: str) -> str:
    lowered = str(region_id or "").casefold()
    if "left" in lowered:
        return "left_sidebar"
    if "right" in lowered:
        return "right_sidebar"
    if "bottom" in lowered:
        return "bottom_bar"
    if "top" in lowered or "header" in lowered or "browser_chrome" in lowered:
        return "top_bar"
    return "non_main_structure_region"


def _apply_fused_child_parent_boundary(entry: dict[str, Any], source: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
    result = deepcopy(entry)
    parent_bbox = _bbox(source.get("parent_region_bbox"))
    if source.get("parent_region_id") is not None:
        result["parent_region_id"] = str(source.get("parent_region_id") or "")
    if source.get("parent_region_label") is not None:
        result["parent_region_label"] = str(source.get("parent_region_label") or "")
    if parent_bbox:
        result["parent_region_bbox"] = deepcopy(parent_bbox)
    if isinstance(source.get("parent_boundary_relation"), dict):
        result["parent_boundary_relation"] = deepcopy(source.get("parent_boundary_relation"))

    event = {
        "missing_parent": 0,
        "clipped": 0,
        "outside_after_clip": 0,
    }
    bbox = _bbox(result.get("bbox"))
    if not bbox:
        return result, event
    if not parent_bbox:
        event["missing_parent"] = 1
        result["review_required"] = True
        result["candidate_only"] = True
        result["fusion_boundary_review"] = {
            "contract_version": "learn_fused_review_parent_boundary_review_v1",
            "reason": "fused_child_box_missing_parent_region",
            "policy": "fused_child_boxes_must_name_parent_region_before_display_or_promotion",
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
        return result, event

    clipped = _intersect_bbox(parent_bbox, bbox)
    if not clipped:
        event["outside_after_clip"] = 1
        result["review_required"] = True
        result["candidate_only"] = True
        result["raw_bbox_before_boundary"] = bbox
        result["bbox"] = {}
        result["fusion_boundary_review"] = {
            "contract_version": "learn_fused_review_parent_boundary_review_v1",
            "reason": "fused_child_box_outside_parent_region",
            "policy": "fused_child_boxes_must_not_be_displayed_outside_parent_region",
            "parent_region_bbox": deepcopy(parent_bbox),
            "previous_bbox": bbox,
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
        return result, event
    if clipped != bbox:
        result["bbox"] = clipped
        result["review_required"] = True
        result["candidate_only"] = True
        result["fusion_boundary_clip"] = {
            "contract_version": "learn_fused_review_parent_boundary_clip_v1",
            "source": "fused_review_display_boundary_contract",
            "reason": "fused_child_box_must_not_extend_outside_parent_region",
            "parent_region_bbox": deepcopy(parent_bbox),
            "previous_bbox": bbox,
            "clipped_bbox": clipped,
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
        event["clipped"] = 1
    if _bbox_containment_ratio(_bbox(result.get("bbox")) or clipped, parent_bbox) < 0.999:
        event["outside_after_clip"] = 1
    return result, event


def _parent_bounded_display_bbox(entry: dict[str, Any]) -> dict[str, int] | None:
    if entry.get("render_in_main_overlay") is False:
        return None
    bbox = _bbox(entry.get("bbox"))
    if not bbox:
        return None
    parent_bbox = _bbox(entry.get("parent_region_bbox"))
    if not parent_bbox:
        return bbox
    return _intersect_bbox(parent_bbox, bbox)


def _mark_non_parent_sibling_group_overlaps(groups: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    updated = [dict(group) for group in groups]
    records: list[dict[str, Any]] = []
    for left_index in range(len(updated)):
        left = updated[left_index]
        if left.get("render_in_main_overlay") is False:
            continue
        left_bbox = _bbox(left.get("bbox"))
        if not left_bbox:
            continue
        for right_index in range(left_index + 1, len(updated)):
            if left.get("render_in_main_overlay") is False:
                break
            right = updated[right_index]
            if right.get("render_in_main_overlay") is False:
                continue
            right_bbox = _bbox(right.get("bbox"))
            if not right_bbox:
                continue
            overlap = min(_bbox_overlap_ratio(left_bbox, right_bbox), _bbox_overlap_ratio(right_bbox, left_bbox))
            if overlap < 0.18:
                continue
            if _distinct_repeated_row_siblings(left, right, left_bbox=left_bbox, right_bbox=right_bbox):
                review = {
                    "contract_version": "learn_repeated_row_overlap_review_v1",
                    "status": "preserved_distinct_rows",
                    "reason": "same_column_row_centers_are_distinct_despite_bbox_height_overlap",
                    "overlap_ratio": round(float(overlap), 4),
                    "display_only": True,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                }
                left.setdefault("repeated_row_overlap_reviews", []).append(
                    {**review, "sibling_group_id": _group_display_id(right)}
                )
                right.setdefault("repeated_row_overlap_reviews", []).append(
                    {**review, "sibling_group_id": _group_display_id(left)}
                )
                continue
            if _sibling_group_has_containment_relation(left_bbox, right_bbox):
                continue
            loser_index = _sibling_group_overlap_loser_index(left, right, left_index, right_index)
            winner = right if loser_index == left_index else left
            loser = updated[loser_index]
            if loser.get("render_in_main_overlay") is False:
                continue
            loser["render_in_main_overlay"] = False
            loser["candidate_only"] = True
            loser["review_required"] = True
            loser["sibling_overlap_review"] = {
                "contract_version": "learn_non_parent_sibling_group_overlap_review_v1",
                "reason": "non_parent_sibling_group_overlap",
                "overlap_ratio": round(float(overlap), 4),
                "blocked_by_group_id": _group_display_id(winner),
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
            records.append(
                {
                    "group_id": _group_display_id(loser),
                    "blocked_by_group_id": _group_display_id(winner),
                    "overlap_ratio": round(float(overlap), 4),
                    "reason": "non_parent_sibling_group_overlap",
                }
            )
    return updated, records


def _distinct_repeated_row_siblings(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    left_bbox: dict[str, int],
    right_bbox: dict[str, int],
) -> bool:
    repeated_row_roles = {"conversation_row", "file_row", "list_row", "settings_row", "table_row"}
    left_role = str(left.get("role") or "").casefold()
    right_role = str(right.get("role") or "").casefold()
    if left_role != right_role or left_role not in repeated_row_roles:
        return False
    horizontal_overlap = max(
        0,
        min(left_bbox["x"] + left_bbox["w"], right_bbox["x"] + right_bbox["w"])
        - max(left_bbox["x"], right_bbox["x"]),
    )
    horizontal_alignment = horizontal_overlap / max(1, min(left_bbox["w"], right_bbox["w"]))
    if horizontal_alignment < 0.85:
        return False
    left_center_y = left_bbox["y"] + left_bbox["h"] / 2
    right_center_y = right_bbox["y"] + right_bbox["h"] / 2
    center_separation = abs(left_center_y - right_center_y)
    minimum_separation = max(8.0, min(left_bbox["h"], right_bbox["h"]) * 0.45)
    return center_separation >= minimum_separation


def _active_numbered_regions_after_sibling_review(
    numbered_regions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    active_regions = deepcopy(numbered_regions)
    suppressed_groups: list[dict[str, Any]] = []
    for region in active_regions:
        groups = region.get("subregion_groups") if isinstance(region.get("subregion_groups"), list) else []
        reviewed_groups, records = _mark_non_parent_sibling_group_overlaps(groups)
        record_by_group_id = {str(record.get("group_id") or ""): record for record in records}
        for group in reviewed_groups:
            if group.get("render_in_main_overlay") is not False:
                continue
            group_id = _group_display_id(group)
            suppressed_groups.append(
                {
                    "region_id": str(region.get("region_id") or ""),
                    "group_id": group_id,
                    "role": str(group.get("role") or ""),
                    "bbox": deepcopy(group.get("bbox") if isinstance(group.get("bbox"), dict) else {}),
                    "review": deepcopy(group.get("sibling_overlap_review") or record_by_group_id.get(group_id) or {}),
                }
            )
        region["subregion_groups"] = [
            group for group in reviewed_groups if group.get("render_in_main_overlay") is not False
        ]
    return active_regions, {
        "contract_version": "learn_downstream_active_group_normalization_v1",
        "policy": "suppressed_sibling_groups_cannot_reenter_overlay_ui_hierarchy_or_page_details",
        "suppressed_group_count": len(suppressed_groups),
        "suppressed_groups": suppressed_groups,
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _sibling_group_has_containment_relation(left_bbox: dict[str, int], right_bbox: dict[str, int]) -> bool:
    return _bbox_overlap_ratio(left_bbox, right_bbox) >= 0.9 or _bbox_overlap_ratio(right_bbox, left_bbox) >= 0.9


def _sibling_group_overlap_loser_index(left: dict[str, Any], right: dict[str, Any], left_index: int, right_index: int) -> int:
    left_priority = _sibling_group_render_priority(left)
    right_priority = _sibling_group_render_priority(right)
    if left_priority != right_priority:
        return left_index if left_priority < right_priority else right_index
    left_bbox = _bbox(left.get("bbox")) or {}
    right_bbox = _bbox(right.get("bbox")) or {}
    left_area = left_bbox.get("w", 0) * left_bbox.get("h", 0)
    right_area = right_bbox.get("w", 0) * right_bbox.get("h", 0)
    if left_area != right_area:
        return left_index if left_area > right_area else right_index
    return right_index


def _sibling_group_render_priority(group: dict[str, Any]) -> int:
    role = str(group.get("role") or "").casefold()
    if role in {"section_parent", "hero_panel", "member_list_region", "conversation_row", "input_toolbar_region"}:
        return 80
    if role in {"hero_text_panel", "hero_code_panel", "list_group", "list_row"}:
        return 70
    if role in {"media_card_group", "tile_card_group", "message_item"}:
        return 50
    if role in {"ungrouped_review_region"}:
        return 20
    return 40


def _group_display_id(group: dict[str, Any]) -> str:
    return str(group.get("group_id") or group.get("number") or group.get("label") or "")


def _group_membership_for_region(region: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    membership: dict[str, list[dict[str, str]]] = {}
    groups = region.get("subregion_groups") if isinstance(region.get("subregion_groups"), list) else []
    numbered_items = region.get("numbered_items") if isinstance(region.get("numbered_items"), list) else []

    def add_membership(item_id: str, group_id: str, group_role: str, group_label: str) -> None:
        if not item_id or not group_id:
            return
        existing = membership.setdefault(item_id, [])
        if any(item.get("group_id") == group_id for item in existing):
            return
        existing.append(
            {
                "group_id": group_id,
                "role": group_role,
                "label": group_label,
            }
        )

    for group in groups:
        if not isinstance(group, dict):
            continue
        group_id = str(group.get("group_id") or "").strip()
        if not group_id:
            continue
        group_role = str(group.get("role") or "").strip()
        group_label = str(group.get("label") or "").strip()
        member_ids = group.get("member_item_ids") if isinstance(group.get("member_item_ids"), list) else []
        child_ids = group.get("child_item_ids") if isinstance(group.get("child_item_ids"), list) else []
        for raw_item_id in [*member_ids, *child_ids]:
            item_id = str(raw_item_id or "").strip()
            add_membership(item_id, group_id, group_role, group_label)
        if group_role not in _DETAIL_PARENT_GROUP_ROLES:
            continue
        group_bbox = _bbox(group.get("bbox"))
        if not group_bbox:
            continue
        for item in numbered_items:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("item_id") or "").strip()
            item_role = str(item.get("role") or "").strip()
            item_bbox = _bbox(item.get("bbox"))
            eligible_child_role = item_role in _DETAIL_CHILD_EVIDENCE_ROLES or (
                group_role in _HERO_PARENT_GROUP_ROLES and item_role in _HERO_CHILD_EVIDENCE_EXTRA_ROLES
            )
            if not item_id or not eligible_child_role or not item_bbox:
                continue
            if _bbox_containment_ratio(item_bbox, group_bbox) >= 0.9:
                add_membership(item_id, group_id, group_role, group_label)
    return membership


_DETAIL_PARENT_GROUP_ROLES = {
    "hero_panel",
    "hero_text_panel",
    "hero_code_panel",
    "section_parent",
    "media_card_group",
    "tile_card_group",
    "tile_card_parent",
    "list_group",
    "list_row",
    "member_list_region",
    "conversation_row",
    "message_item",
    "input_toolbar_region",
    "settings_status_tile",
    "table_row",
}


_DETAIL_CHILD_EVIDENCE_ROLES = {
    "text",
    "text_action",
    "button",
    "menu_item",
    "nav_text_action",
}


_HERO_PARENT_GROUP_ROLES = {
    "hero_panel",
    "hero_text_panel",
    "hero_code_panel",
}


_HERO_CHILD_EVIDENCE_EXTRA_ROLES = {
    "news_card",
    "recommendation_item",
    "partial_visible_card",
}


_MODEL_CARD_LIKE_TEXT_EVIDENCE_ROLES = {
    "news_card",
    "recommendation_item",
    "content_card",
}


_PRIMARY_VISUAL_CARD_SOURCES = {
    "visual_card_segmenter",
    "bottom_edge_partial_card_reconciliation",
}


_STRUCTURAL_CONTAINER_GROUP_ROLES = {
    "hero_panel",
    "section_parent",
    "list_group",
    "tile_card_group",
    "table_group",
}


def _is_model_card_like_text_evidence(item: dict[str, Any]) -> bool:
    role = str(item.get("role") or "").casefold()
    source = str(item.get("source") or "").casefold()
    if role not in _MODEL_CARD_LIKE_TEXT_EVIDENCE_ROLES:
        return False
    return source not in _PRIMARY_VISUAL_CARD_SOURCES


def _trusted_visual_card_member_count(group: dict[str, Any], item_by_id: dict[str, dict[str, Any]] | None = None) -> int:
    if str(group.get("role") or "") != "media_card_group" or not item_by_id:
        return 0
    count = 0
    member_ids = group.get("member_item_ids") if isinstance(group.get("member_item_ids"), list) else []
    for member_id in member_ids:
        item = item_by_id.get(str(member_id or ""))
        if not item:
            continue
        role = str(item.get("role") or "").casefold()
        source = str(item.get("source") or "").casefold()
        if role == "media_card" and source == "visual_card_segmenter":
            count += 1
    return count


def _model_card_like_text_member_count(group: dict[str, Any], item_by_id: dict[str, dict[str, Any]] | None = None) -> int:
    if str(group.get("role") or "") != "media_card_group" or not item_by_id:
        return 0
    count = 0
    member_ids = group.get("member_item_ids") if isinstance(group.get("member_item_ids"), list) else []
    for member_id in member_ids:
        item = item_by_id.get(str(member_id or ""))
        if item and _is_model_card_like_text_evidence(item):
            count += 1
    return count


def _group_display_hierarchy(
    group: dict[str, Any],
    item_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    role = str(group.get("role") or "")
    child_group_ids = [
        str(item or "").strip()
        for item in group.get("child_group_ids", [])
        if str(item or "").strip()
    ] if isinstance(group.get("child_group_ids"), list) else []
    detail_only_review_region = role == "ungrouped_review_region"
    model_card_like_text_members = _model_card_like_text_member_count(group, item_by_id)
    trusted_visual_card_members = _trusted_visual_card_member_count(group, item_by_id)
    detail_only_text_card_group = (
        role == "media_card_group"
        and model_card_like_text_members > 0
        and trusted_visual_card_members < 2
    )
    structural_container = bool(child_group_ids) and role in _STRUCTURAL_CONTAINER_GROUP_ROLES
    render_in_main_overlay = not structural_container and not detail_only_review_region and not detail_only_text_card_group
    return {
        "contract_version": "learn_group_display_hierarchy_v1",
        "display_layer": (
            "detail_only_review_region"
            if detail_only_review_region
            else (
                "detail_only_text_card_group"
                if detail_only_text_card_group
                else ("structural_container" if structural_container else "review_region")
            )
        ),
        "render_in_main_overlay": render_in_main_overlay,
        "child_group_ids": child_group_ids,
        "trusted_visual_card_member_count": trusted_visual_card_members,
        "model_card_like_text_member_count": model_card_like_text_members,
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        **(
            {
                "demotion_reason": "container_group_has_child_groups_render_children_in_main_overlay",
            }
            if structural_container
            else {}
        ),
    }


def _item_display_hierarchy(item: dict[str, Any], memberships: list[dict[str, str]]) -> dict[str, Any]:
    roles = {str(group.get("role") or "") for group in memberships}
    item_role = str(item.get("role") or "")
    normalized_item_role = item_role.casefold().replace(" ", "_")
    item_type = str(item.get("item_type") or "").casefold()
    parent_ids = [str(group.get("group_id") or "") for group in memberships if group.get("group_id")]
    is_structural_container = normalized_item_role in {
        "window",
        "pane",
        "document",
        "group",
        "container",
        "section",
        "region",
        "content_area",
        "main_content",
    }
    is_locatable_control = bool(
        item_type in {"actionable", "visual_control", "control", "button"}
        or normalized_item_role in {
            "button",
            "control",
            "icon_button",
            "menu_item",
            "nav_item",
            "text_input",
            "input",
        }
    ) and normalized_item_role not in {"text", "icon", "image"} and not is_structural_container
    inside_ungrouped_review_region = "ungrouped_review_region" in roles and not is_locatable_control
    inside_table_group = "table_group" in roles
    is_model_card_text_evidence = bool(roles & _DETAIL_PARENT_GROUP_ROLES) and _is_model_card_like_text_evidence(item)
    item_source = str(item.get("source") or "").casefold()
    is_tile_parent_fragment = (
        bool(roles & {"tile_card_parent", "tile_card_group", "media_card_group"})
        and item_role in {
            "card",
            "tile_card",
            "content_card",
            "news_card",
            "recommendation_item",
        }
        and item_source not in _PRIMARY_VISUAL_CARD_SOURCES
        and not (item_role == "tile_card" and bool(item.get("children")))
    )
    explicit_overlay_suppression = item.get("render_in_main_overlay") is False
    is_child_evidence = explicit_overlay_suppression or inside_ungrouped_review_region or inside_table_group or (
        bool(roles & _DETAIL_PARENT_GROUP_ROLES)
        and (
            item_role in _DETAIL_CHILD_EVIDENCE_ROLES
            or (bool(roles & _HERO_PARENT_GROUP_ROLES) and item_role in _HERO_CHILD_EVIDENCE_EXTRA_ROLES)
            or is_model_card_text_evidence
            or is_tile_parent_fragment
        )
    )
    demotion_reason = (
        str(item.get("demotion_reason") or "explicit_overlay_suppression")
        if explicit_overlay_suppression
        else (
        "ungrouped_review_region_detail_only"
        if inside_ungrouped_review_region
        else (
            "table_member_inside_row_hierarchy"
            if inside_table_group
            else (
                "model_card_like_text_evidence_inside_parent_group"
                if is_model_card_text_evidence
                else ("tile_card_fragment_inside_semantic_parent" if is_tile_parent_fragment else "")
            )
        ))
    )
    return {
        "contract_version": "learn_display_hierarchy_v1",
        "parent_group_ids": parent_ids,
        "parent_group_roles": sorted(role for role in roles if role),
        "display_layer": "child_evidence" if is_child_evidence else "primary_region",
        "render_in_main_overlay": not is_child_evidence,
        "page_detail_role": "child_evidence" if is_child_evidence else "region",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        **(
            {
                "demotion_reason": demotion_reason,
            }
            if demotion_reason
            else {}
        ),
    }


def partition_stage2_calibration_items(
    region: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """按渲染层级拆分可校准主项和仅作说明的子证据。"""
    numbered_items = region.get("numbered_items") if isinstance(region.get("numbered_items"), list) else []
    groups = region.get("subregion_groups") if isinstance(region.get("subregion_groups"), list) else []
    control_parents = region.get("control_parents") if isinstance(region.get("control_parents"), list) else []
    item_by_id = {
        str(item.get("item_id") or ""): item
        for item in numbered_items
        if isinstance(item, dict) and str(item.get("item_id") or "").strip()
    }
    control_parent_member_ids = {
        str(member_id or "").strip()
        for parent in control_parents
        if isinstance(parent, dict)
        for member_id in parent.get("member_object_ids", [])
        if str(member_id or "").strip() in item_by_id
    }
    consolidated_parent_member_ids = {
        str(item_id or "").strip()
        for group in groups
        if isinstance(group, dict)
        and str(group.get("role") or "") in _DETAIL_PARENT_GROUP_ROLES
        and group.get("adjacent_fragment_merged") is True
        for item_id in group.get("member_item_ids", [])
        if str(item_id or "").strip()
    }
    memberships = _group_membership_for_region(region)
    calibratable: list[dict[str, Any]] = []
    child_evidence: list[dict[str, Any]] = []
    for item in numbered_items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("item_id") or "").strip()
        hierarchy = _item_display_hierarchy(item, memberships.get(item_id, []))
        explicit_hierarchy = item.get("display_hierarchy") if isinstance(item.get("display_hierarchy"), dict) else {}
        if _is_stage2_semantic_container_item(item):
            child_evidence.append(
                {
                    **item,
                    "display_hierarchy": {
                        **hierarchy,
                        "display_layer": "semantic_group_evidence",
                        "render_in_main_overlay": False,
                        "page_detail_role": "semantic_group_evidence",
                        "demotion_reason": "semantic_container_is_not_an_atomic_calibration_target",
                    },
                }
            )
            continue
        if item_id in control_parent_member_ids:
            child_evidence.append(
                {
                    **item,
                    "display_hierarchy": {
                        **hierarchy,
                        "display_layer": "control_parent_child_evidence",
                        "render_in_main_overlay": False,
                        "page_detail_role": "control_parent_child_evidence",
                        "demotion_reason": "atomic_control_parent_replaces_member_fragment_calibration",
                    },
                }
            )
            continue
        if item_id in consolidated_parent_member_ids:
            child_evidence.append(
                {
                    **item,
                    "display_hierarchy": {
                        **hierarchy,
                        "display_layer": "child_evidence",
                        "render_in_main_overlay": False,
                        "page_detail_role": "child_evidence",
                        "demotion_reason": "consolidated_parent_replaces_fragment_calibration",
                    },
                }
            )
            continue
        explicitly_hidden = item.get("render_in_main_overlay") is False or explicit_hierarchy.get("render_in_main_overlay") is False
        if explicitly_hidden or hierarchy.get("render_in_main_overlay") is False:
            child_evidence.append({**item, "display_hierarchy": hierarchy})
            continue
        calibratable.append({**item, "display_hierarchy": hierarchy})

    calibratable_ids = {str(item.get("item_id") or "") for item in calibratable}
    for parent in control_parents:
        if not isinstance(parent, dict):
            continue
        parent_id = str(parent.get("object_id") or "").strip()
        parent_bbox = _bbox(parent.get("bbox"))
        if not parent_id or not parent_bbox:
            continue
        member_ids = [
            str(member_id or "").strip()
            for member_id in parent.get("member_object_ids", [])
            if str(member_id or "").strip()
        ]
        child_items = [item_by_id[member_id] for member_id in member_ids if member_id in item_by_id]
        calibratable.append(
            {
                "item_id": parent_id,
                "source_item_id": parent_id,
                "final_item_id": str(parent.get("final_control_parent_id") or "").strip() or parent_id,
                "number": parent.get("number"),
                "label": str(parent.get("label") or parent_id),
                "role": str(parent.get("role") or "atomic_control_parent"),
                "bbox": parent_bbox,
                "children": [
                    {
                        "child_id": item.get("item_id"),
                        "label": item.get("label") or item.get("text"),
                        "role": item.get("role"),
                        "bbox": item.get("bbox"),
                    }
                    for item in child_items
                ],
                "source": str(parent.get("source") or "atomic_control_parent_synthesis"),
                "calibration_target_kind": "atomic_control_parent",
                "display_hierarchy": {
                    "contract_version": "learn_display_hierarchy_v1",
                    "display_layer": "primary_control_parent",
                    "render_in_main_overlay": True,
                    "page_detail_role": "control_parent",
                    "display_only": True,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
        calibratable_ids.add(parent_id)
    for group in groups:
        if not isinstance(group, dict) or str(group.get("role") or "") not in _DETAIL_PARENT_GROUP_ROLES:
            continue
        group_id = str(group.get("group_id") or "").strip()
        group_bbox = _bbox(group.get("bbox"))
        if not group_id or not group_bbox:
            continue
        hierarchy = _group_display_hierarchy(group, item_by_id)
        if group.get("render_in_main_overlay") is False or hierarchy.get("render_in_main_overlay") is False:
            continue
        member_ids = [
            str(item_id or "").strip()
            for item_id in group.get("member_item_ids", [])
            if str(item_id or "").strip()
        ] if isinstance(group.get("member_item_ids"), list) else []
        if any(item_id in control_parent_member_ids for item_id in member_ids):
            continue
        if any(item_id in calibratable_ids for item_id in member_ids):
            continue
        child_items = [item_by_id[item_id] for item_id in member_ids if item_id in item_by_id]
        child_labels = [
            str(item.get("label") or item.get("text") or "").strip()
            for item in child_items
            if str(item.get("label") or item.get("text") or "").strip()
        ]
        calibratable.append(
            {
                "item_id": group_id,
                "source_item_id": group_id,
                "final_item_id": str(group.get("final_group_id") or "").strip() or group_id,
                "number": group.get("number"),
                "label": str(group.get("label") or (child_labels[0] if child_labels else group.get("role") or group_id)),
                "role": group.get("role"),
                "bbox": group_bbox,
                "children": [
                    {
                        "child_id": item.get("item_id"),
                        "label": item.get("label") or item.get("text"),
                        "role": item.get("role"),
                        "bbox": item.get("bbox"),
                    }
                    for item in child_items
                ],
                "source": "two_stage_parent_group",
                "display_hierarchy": hierarchy,
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    return calibratable, child_evidence


def summarize_stage2_calibration_partition(stage2: dict[str, Any]) -> dict[str, Any]:
    """汇总真正进入精准校准的父项，避免把说明性子证据当作模型任务。"""

    regions = stage2.get("regions") if isinstance(stage2.get("regions"), list) else []
    calibration_candidate_count = 0
    calibration_child_evidence_count = 0
    calibration_region_count = 0
    for region in regions:
        if not isinstance(region, dict):
            continue
        calibratable, child_evidence = partition_stage2_calibration_items(region)
        if calibratable or child_evidence:
            calibration_region_count += 1
        calibration_candidate_count += len(calibratable)
        calibration_child_evidence_count += len(child_evidence)
    return {
        "contract_version": "learn_stage2_calibration_partition_summary_v1",
        "numbered_item_count": _int(stage2.get("numbered_item_count")),
        "calibration_candidate_count": calibration_candidate_count,
        "calibration_child_evidence_count": calibration_child_evidence_count,
        "calibration_region_count": calibration_region_count,
        "count_basis": "parent_or_standalone_items_after_display_hierarchy_partition",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _fusion_boxes(structure_regions: list[dict[str, Any]], numbered_regions: list[dict[str, Any]]) -> dict[str, Any]:
    boxes: list[dict[str, Any]] = []
    boundary_summary = {
        "contract_version": "learn_fused_review_region_content_boundary_summary_v1",
        "policy": "fused_child_boxes_must_name_parent_region_and_stay_inside_parent_region",
        "child_scope_policy": "internal_content_can_only_belong_to_one_parent_region_and_must_not_render_outside_that_region",
        "missing_parent_child_count": 0,
        "clipped_fused_child_count": 0,
        "outside_parent_after_clip_count": 0,
        "sibling_non_parent_overlap_count": 0,
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "interpretation": "Final review boxes repeat the parent-region boundary check so stale or unbounded child boxes cannot be displayed as-is.",
    }
    for region in structure_regions:
        boxes.append(
            {
                "box_type": "structure_region",
                "number": str(region.get("region_no") or ""),
                "label": str(region.get("label") or ""),
                "bbox": deepcopy(region.get("bbox") if isinstance(region.get("bbox"), dict) else {}),
                "display_only": True,
            }
        )
    for region in numbered_regions:
        if _is_browser_chrome_region(region) and _numbered_region_has_explicit_browser_chrome_evidence(region):
            continue
        membership_by_item_id = _group_membership_for_region(region)
        for parent in region.get("control_parents", []) if isinstance(region.get("control_parents"), list) else []:
            if not isinstance(parent, dict):
                continue
            entry, boundary_event = _apply_fused_child_parent_boundary(
                {
                    "box_type": "control_parent",
                    "object_id": str(parent.get("object_id") or ""),
                    "label": str(parent.get("label") or ""),
                    "role": str(parent.get("role") or "atomic_control_parent"),
                    "bbox": deepcopy(parent.get("bbox") if isinstance(parent.get("bbox"), dict) else {}),
                    "member_object_ids": deepcopy(
                        parent.get("member_object_ids") if isinstance(parent.get("member_object_ids"), list) else []
                    ),
                    "source": str(parent.get("source") or ""),
                    "render_in_main_overlay": parent.get("render_in_main_overlay") is not False,
                    "review_only": True,
                    "display_only": True,
                },
                parent,
            )
            boundary_summary["missing_parent_child_count"] += boundary_event["missing_parent"]
            boundary_summary["clipped_fused_child_count"] += boundary_event["clipped"]
            boundary_summary["outside_parent_after_clip_count"] += boundary_event["outside_after_clip"]
            boxes.append(entry)
        raw_groups = region.get("subregion_groups", []) if isinstance(region.get("subregion_groups"), list) else []
        item_by_id = {
            str(item.get("item_id") or ""): item
            for item in region.get("numbered_items", [])
            if isinstance(item, dict) and str(item.get("item_id") or "").strip()
        } if isinstance(region.get("numbered_items"), list) else {}
        reviewed_groups, sibling_overlap_records = _mark_non_parent_sibling_group_overlaps(raw_groups)
        boundary_summary["sibling_non_parent_overlap_count"] += len(sibling_overlap_records)
        for group in reviewed_groups:
            if not isinstance(group, dict):
                continue
            group_display_hierarchy = _group_display_hierarchy(group, item_by_id)
            render_in_main_overlay = group.get("render_in_main_overlay")
            if render_in_main_overlay is not False:
                render_in_main_overlay = group_display_hierarchy["render_in_main_overlay"]
            entry, boundary_event = _apply_fused_child_parent_boundary(
                {
                    "box_type": "subregion_group",
                    "number": str(group.get("group_id") or ""),
                    "label": str(group.get("label") or ""),
                    "role": str(group.get("role") or ""),
                    "bbox": deepcopy(group.get("bbox") if isinstance(group.get("bbox"), dict) else {}),
                    "group_display_hierarchy": group_display_hierarchy,
                    "render_in_main_overlay": render_in_main_overlay,
                    "candidate_only": bool(group.get("candidate_only")),
                    "review_required": bool(group.get("review_required")),
                    "sibling_overlap_review": deepcopy(
                        group.get("sibling_overlap_review") if isinstance(group.get("sibling_overlap_review"), dict) else {}
                    ),
                    "display_only": True,
                },
                group,
            )
            boundary_summary["missing_parent_child_count"] += boundary_event["missing_parent"]
            boundary_summary["clipped_fused_child_count"] += boundary_event["clipped"]
            boundary_summary["outside_parent_after_clip_count"] += boundary_event["outside_after_clip"]
            boxes.append(entry)
        for item in region.get("numbered_items", []) if isinstance(region.get("numbered_items"), list) else []:
            if not isinstance(item, dict):
                continue
            item_memberships = membership_by_item_id.get(str(item.get("item_id") or ""), [])
            display_hierarchy = _item_display_hierarchy(item, item_memberships)
            entry, boundary_event = _apply_fused_child_parent_boundary(
                {
                    "box_type": "numbered_item",
                    "number": str(item.get("number") or ""),
                    "label": str(item.get("label") or ""),
                    "role": str(item.get("role") or ""),
                    "bbox": deepcopy(item.get("bbox") if isinstance(item.get("bbox"), dict) else {}),
                    "children": deepcopy(item.get("children") if isinstance(item.get("children"), list) else []),
                    "overlay_style": deepcopy(item.get("overlay_style") if isinstance(item.get("overlay_style"), dict) else {}),
                    "parent_group_ids": display_hierarchy["parent_group_ids"],
                    "parent_group_roles": display_hierarchy["parent_group_roles"],
                    "display_hierarchy": display_hierarchy,
                    "render_in_main_overlay": display_hierarchy["render_in_main_overlay"],
                    "display_only": True,
                },
                item,
            )
            boundary_summary["missing_parent_child_count"] += boundary_event["missing_parent"]
            boundary_summary["clipped_fused_child_count"] += boundary_event["clipped"]
            boundary_summary["outside_parent_after_clip_count"] += boundary_event["outside_after_clip"]
            boxes.append(entry)
    boundary_has_blocker = any(
        boundary_summary[key] > 0
        for key in (
            "missing_parent_child_count",
            "clipped_fused_child_count",
            "outside_parent_after_clip_count",
            "sibling_non_parent_overlap_count",
        )
    )
    boundary_summary["boundary_contract_status"] = "needs_human_review" if boundary_has_blocker else "passed"
    boundary_summary["pathgraph_promotion_allowed"] = not boundary_has_blocker
    boundary_summary["visual_overlay_status"] = "not_reviewed_by_metric"
    boundary_summary["learning_artifact_status"] = "review_only_not_runtime_pathgraph"
    boundary_summary["promotion_blockers"] = [
        key
        for key in ("missing_parent_child_count", "clipped_fused_child_count", "outside_parent_after_clip_count")
        if boundary_summary[key] > 0
    ] + [
        key
        for key in ("sibling_non_parent_overlap_count",)
        if boundary_summary[key] > 0
    ]
    return {
        "contract_version": "learn_two_stage_fused_review_boxes_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "fused_review_box_count": len(boxes),
        "fused_review_boxes": boxes,
        "region_content_boundary_summary": boundary_summary,
        "compiled_overlay_path": "",
        "full_screen_understanding_overlay_path": "",
        "message_context_overlay_path": "",
        "message_context_zoom_path": "",
    }


def _render_two_stage_overlay(
    *,
    image_path: str,
    structure_regions: list[dict[str, Any]],
    numbered_regions: list[dict[str, Any]],
) -> str:
    if not image_path:
        return ""
    source = Path(image_path)
    if not source.exists():
        return ""
    try:
        with Image.open(source) as image:
            canvas = image.convert("RGB")
    except Exception:
        return ""
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    message_parent_bboxes = _message_parent_bbox_map(numbered_regions)
    message_context_items: list[tuple[dict[str, Any], dict[str, int]]] = []
    for region in structure_regions:
        bbox = _bbox(region.get("bbox"))
        if not bbox:
            continue
        _draw_box(draw, bbox, f"S{region.get('region_no')}: {region.get('label')}", color=(24, 114, 204), font=font, width=3)
    for region in numbered_regions:
        if _is_browser_chrome_region(region) and _numbered_region_has_explicit_browser_chrome_evidence(region):
            continue
        for parent in region.get("control_parents", []) if isinstance(region.get("control_parents"), list) else []:
            if not isinstance(parent, dict) or parent.get("render_in_main_overlay") is False:
                continue
            bbox = _parent_bounded_display_bbox(parent)
            if not bbox:
                continue
            label = str(parent.get("label") or parent.get("object_id") or "control")
            _draw_box(draw, bbox, f"CP {label}", color=(0, 158, 115), font=font, width=3)
        raw_groups = region.get("subregion_groups", []) if isinstance(region.get("subregion_groups"), list) else []
        item_by_id = {
            str(item.get("item_id") or ""): item
            for item in region.get("numbered_items", [])
            if isinstance(item, dict) and str(item.get("item_id") or "").strip()
        } if isinstance(region.get("numbered_items"), list) else {}
        reviewed_groups, _sibling_overlap_records = _mark_non_parent_sibling_group_overlaps(raw_groups)
        for group in reviewed_groups:
            if not isinstance(group, dict):
                continue
            group_display_hierarchy = _group_display_hierarchy(group, item_by_id)
            if group.get("render_in_main_overlay") is not False and group_display_hierarchy["render_in_main_overlay"] is False:
                group = {**group, "render_in_main_overlay": False}
            bbox = _parent_bounded_display_bbox(group)
            if not bbox:
                continue
            _draw_box(draw, bbox, f"{group.get('group_id')} {group.get('role')}", color=(40, 145, 235), font=font, width=2)
        for item in region.get("numbered_items", []) if isinstance(region.get("numbered_items"), list) else []:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("item_id") or "")
            display_hierarchy = _item_display_hierarchy(item, _group_membership_for_region(region).get(item_id, []))
            if display_hierarchy["render_in_main_overlay"] is False:
                continue
            bbox = _parent_bounded_display_bbox(item)
            if not bbox:
                continue
            if _is_message_context_overlay_item(item):
                message_context_items.append((item, bbox))
                continue
            overlay_style = item.get("overlay_style") if isinstance(item.get("overlay_style"), dict) else {}
            if overlay_style.get("tone") == "background_review_region":
                _draw_review_background_box(
                    draw,
                    bbox,
                    "" if overlay_style.get("label_policy") == "hidden" else "review-only",
                    font=font,
                )
            elif overlay_style.get("tone") == "needs_review_incomplete_card":
                _draw_incomplete_card_box(
                    draw,
                    bbox,
                    f"{item.get('number')} {item.get('role')} needs review",
                    font=font,
                )
            else:
                _draw_box(draw, bbox, f"{item.get('number')} {item.get('role')}", color=(236, 126, 0), font=font, width=2)
    for item, bbox in message_context_items:
        parent_bbox = message_parent_bboxes.get(str(item.get("semantic_parent_group_id") or ""))
        _draw_message_context_box(
            draw,
            bbox,
            _message_context_overlay_label(item),
            font=font,
            parent_bbox=parent_bbox,
        )
    out_dir = ARTIFACTS_DIR / "review-overlays"
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    out_path = out_dir / f"{source.stem}__two-stage-understanding__{timestamp}.png"
    canvas.save(out_path)
    return str(out_path)


def _is_browser_chrome_region(region: dict[str, Any]) -> bool:
    return str(region.get("region_id") or region.get("zone_id") or "").casefold().endswith("browser_chrome")


def _numbered_region_has_explicit_browser_chrome_evidence(region: dict[str, Any]) -> bool:
    items = region.get("numbered_items") if isinstance(region.get("numbered_items"), list) else []
    return any(isinstance(item, dict) and _looks_like_browser_chrome_evidence(item) for item in items)


def _render_message_context_review_overlay(
    *,
    image_path: str,
    numbered_regions: list[dict[str, Any]],
    fused_review_boxes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not image_path:
        return {}
    source = Path(image_path)
    if not source.exists():
        return {}
    try:
        with Image.open(source) as image:
            original = image.convert("RGB")
    except Exception:
        return {}
    canvas = Image.blend(original, Image.new("RGB", original.size, (255, 255, 255)), 0.35)
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    parent_bboxes = _message_parent_bbox_map(numbered_regions)
    message_items: list[tuple[dict[str, Any], dict[str, int]]] = []
    context_items: list[tuple[dict[str, Any], dict[str, int]]] = []
    core_items: list[tuple[dict[str, Any], dict[str, int]]] = []
    for box in fused_review_boxes or []:
        if not isinstance(box, dict):
            continue
        role = str(box.get("role") or box.get("box_type") or "").casefold()
        bbox = _bbox(box.get("bbox"))
        if role != "message_item" or not bbox:
            continue
        message_items.append((box, bbox))
        key = str(box.get("number") or box.get("group_id") or box.get("label") or "").strip()
        if key:
            parent_bboxes[key] = bbox
    for region in numbered_regions:
        for group in region.get("subregion_groups", []) if isinstance(region.get("subregion_groups"), list) else []:
            if not isinstance(group, dict):
                continue
            if str(group.get("role") or "").casefold() != "message_item":
                continue
            bbox = _parent_bounded_display_bbox(group)
            if bbox:
                message_items.append((group, bbox))
        for item in region.get("numbered_items", []) if isinstance(region.get("numbered_items"), list) else []:
            if not isinstance(item, dict):
                continue
            bbox = _bbox(item.get("bbox"))
            if not bbox:
                continue
            role = str(item.get("role") or item.get("item_type") or "").casefold()
            if role == "message_item":
                message_items.append((item, bbox))
                for parent_key in _message_parent_overlay_keys(item):
                    parent_bboxes[parent_key] = bbox
            elif _is_message_context_overlay_item(item):
                context_items.append((item, bbox))
            elif role in {"message_bubble", "message_card", "message_card_content", "image_message", "text_button"}:
                core_items.append((item, bbox))
    if not context_items and not message_items:
        return {}
    for item, bbox in message_items:
        _draw_context_parent_box(draw, bbox, f"{item.get('group_id') or item.get('number') or 'message_item'}", font=font)
    for item, bbox in core_items:
        _draw_context_core_box(draw, bbox, f"{item.get('number')} {item.get('role')}", font=font)
    for item, bbox in context_items:
        parent_bbox = parent_bboxes.get(str(item.get("semantic_parent_group_id") or ""))
        _draw_message_context_box(
            draw,
            bbox,
            _message_context_overlay_label(item),
            font=font,
            parent_bbox=parent_bbox,
        )
    out_dir = ARTIFACTS_DIR / "review-overlays"
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    overlay_path = out_dir / f"{source.stem}__message-context-review__{timestamp}.png"
    canvas.save(overlay_path)
    zoom_path = _write_message_context_zoom(
        canvas=canvas,
        source_stem=source.stem,
        context_items=context_items,
        parent_bboxes=parent_bboxes,
        timestamp=timestamp,
    )
    return {
        "contract_version": "learn_message_context_review_overlay_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "overlay_path": str(overlay_path),
        "zoom_path": str(zoom_path) if zoom_path else "",
        "message_parent_count": len(message_items),
        "message_context_count": len(context_items),
        "message_core_count": len(core_items),
        "interpretation": "Dedicated review image for message parent/context visibility only; not Execute binding.",
    }


def _render_stage1_region_localization_overlay(
    *,
    image_path: str,
    localized_regions: list[dict[str, Any]],
) -> str:
    if not image_path:
        return ""
    source = Path(image_path)
    if not source.exists():
        return ""
    try:
        with Image.open(source) as image:
            canvas = image.convert("RGB")
    except Exception:
        return ""
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for region in localized_regions:
        rough = _bbox(region.get("rough_bbox"))
        precise = _bbox(region.get("precise_bbox"))
        label = f"S{region.get('region_no')}: {region.get('label')}"
        if rough:
            _draw_box(draw, rough, f"rough {label}", color=(160, 160, 160), font=font, width=2)
        if precise:
            _draw_box(draw, precise, f"precise {label}", color=(24, 114, 204), font=font, width=4)
    out_dir = ARTIFACTS_DIR / "review-overlays"
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    out_path = out_dir / f"{source.stem}__stage1-region-localization__{timestamp}.png"
    canvas.save(out_path)
    return str(out_path)


def _render_stage1_5_partition_overlay(
    *,
    image_path: str,
    localized_regions: list[dict[str, Any]],
    subregions: list[dict[str, Any]],
) -> str:
    if not image_path or not subregions:
        return ""
    source = Path(image_path)
    if not source.exists():
        return ""
    try:
        with Image.open(source) as image:
            canvas = image.convert("RGB")
    except Exception:
        return ""
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default()
    for region in localized_regions:
        precise = _bbox(region.get("precise_bbox") or region.get("bbox"))
        if not precise:
            continue
        label = f"S{region.get('region_no')}: {region.get('label')}"
        _draw_box(draw, precise, f"Stage1 {label}", color=(24, 114, 204), font=font, width=3)
    for index, subregion in enumerate(subregions, start=1):
        bbox = _bbox(subregion.get("bbox"))
        if not bbox:
            continue
        role = str(subregion.get("role") or "subregion")
        style = _stage1_5_overlay_style(role, index=index)
        _draw_box(
            draw,
            bbox,
            f"1.5-{index} {role}",
            color=style["color"],
            label_fill=style["label_fill"],
            font=font,
            width=style["width"],
        )
    out_dir = ARTIFACTS_DIR / "review-overlays"
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    out_path = out_dir / f"{source.stem}__stage1-5-partition__{timestamp}.png"
    canvas.save(out_path)
    return str(out_path)


def _stage1_5_overlay_style(role: str, *, index: int) -> dict[str, Any]:
    normalized = str(role or "").casefold()
    role_styles: dict[str, tuple[tuple[int, int, int], tuple[int, int, int], int]] = {
        "conversation_list": ((136, 78, 191), (136, 78, 191), 4),
        "message_thread": ((0, 128, 96), (0, 128, 96), 4),
        "bottom_composer": ((208, 76, 32), (208, 76, 32), 4),
        "content_column": ((230, 126, 34), (230, 126, 34), 4),
    }
    if normalized in role_styles:
        color, label_fill, width = role_styles[normalized]
        return {"color": color, "label_fill": label_fill, "width": width}
    palette = [
        (230, 126, 34),
        (32, 120, 180),
        (120, 120, 40),
        (170, 80, 120),
    ]
    color = palette[max(0, index - 1) % len(palette)]
    return {"color": color, "label_fill": color, "width": 4}


def _overlay_label_layout(
    draw: ImageDraw.ImageDraw,
    bbox: dict[str, int],
    label: str,
    *,
    font: Any,
    max_width: int,
) -> dict[str, Any] | None:
    text = _fit_overlay_label_text(draw, _compact_overlay_label(str(label or "")), font=font, max_width=max_width - 6)
    if not text:
        return None
    canvas_w, canvas_h = getattr(getattr(draw, "im", None), "size", (bbox["x"] + bbox["w"], bbox["y"] + bbox["h"]))
    text_bbox = draw.textbbox((bbox["x"], bbox["y"]), text, font=font)
    text_w = text_bbox[2] - text_bbox[0]
    text_h = text_bbox[3] - text_bbox[1]
    label_w = min(max_width, text_w + 6)
    label_h = text_h + 4
    label_x = min(max(0, bbox["x"]), max(0, canvas_w - label_w))
    label_y = bbox["y"] + 2
    if label_y + label_h > bbox["y"] + bbox["h"]:
        label_y = max(bbox["y"], bbox["y"] + bbox["h"] - label_h)
    label_y = min(max(0, label_y), max(0, canvas_h - label_h))
    rect = (label_x, label_y, label_x + label_w, label_y + label_h)
    return {
        "text": text,
        "rect": rect,
        "text_xy": (label_x + 3, label_y + 2),
    }


def _compact_overlay_label(label: str) -> str:
    text = " ".join(str(label or "").split())
    replacements = {
        "timestamp -> msg_": "time>m",
        "sender_or_level -> msg_": "sender>m",
        "semantic_parent_group": "parent",
        "topbar_control_cluster": "topctl",
        "topbar_semantic_group": "topgrp",
        "message_card_content": "card_text",
        "partial_visible_card": "partial",
        "media_card_group": "cardgrp",
        "section_parent": "section",
        "message_bubble": "bubble",
        "message_card": "msgcard",
        "message_item": "msg",
        "media_card": "card",
        "text_action": "txtact",
        "text_button": "btn",
        "icon_button": "icon",
        "nav_item": "nav",
        "control": "ctl",
        "review_only": "review",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text[:64]


def _fit_overlay_label_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    font: Any,
    max_width: int,
) -> str:
    text = str(text or "").strip()
    if not text or max_width <= 0:
        return ""
    if _text_width(draw, text, font=font) <= max_width:
        return text
    first_token = text.split(" ", 1)[0]
    if first_token and _text_width(draw, first_token, font=font) <= max_width:
        return first_token
    if max_width <= _text_width(draw, "...", font=font):
        return ""
    suffix = "..."
    for length in range(len(text), 0, -1):
        candidate = text[:length].rstrip() + suffix
        if _text_width(draw, candidate, font=font) <= max_width:
            return candidate
    return ""


def _text_width(draw: ImageDraw.ImageDraw, text: str, *, font: Any) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def _draw_box(
    draw: ImageDraw.ImageDraw,
    bbox: dict[str, int],
    label: str,
    *,
    color: tuple[int, int, int],
    font: Any,
    width: int,
    label_fill: tuple[int, int, int] | None = None,
    label_text_fill: tuple[int, int, int] = (255, 255, 255),
) -> None:
    x1 = bbox["x"]
    y1 = bbox["y"]
    x2 = bbox["x"] + bbox["w"]
    y2 = bbox["y"] + bbox["h"]
    draw.rectangle((x1, y1, x2, y2), outline=color, width=width)
    layout = _overlay_label_layout(draw, bbox, label, font=font, max_width=min(180, max(1, bbox["w"])))
    if not layout:
        return
    draw.rectangle(layout["rect"], fill=label_fill or color)
    draw.text(layout["text_xy"], layout["text"], fill=label_text_fill, font=font)


def _draw_review_background_box(
    draw: ImageDraw.ImageDraw,
    bbox: dict[str, int],
    label: str,
    *,
    font: Any,
) -> None:
    x1 = bbox["x"]
    y1 = bbox["y"]
    x2 = bbox["x"] + bbox["w"]
    y2 = bbox["y"] + bbox["h"]
    color = (126, 146, 166)
    dash = 8
    gap = 6
    for x in range(x1, x2, dash + gap):
        draw.line((x, y1, min(x + dash, x2), y1), fill=color, width=1)
        draw.line((x, y2, min(x + dash, x2), y2), fill=color, width=1)
    for y in range(y1, y2, dash + gap):
        draw.line((x1, y, x1, min(y + dash, y2)), fill=color, width=1)
        draw.line((x2, y, x2, min(y + dash, y2)), fill=color, width=1)
    layout = _overlay_label_layout(draw, bbox, label, font=font, max_width=min(140, max(1, bbox["w"])))
    if not layout:
        return
    draw.rectangle(layout["rect"], fill=(238, 243, 247))
    draw.text(layout["text_xy"], layout["text"], fill=(64, 82, 100), font=font)


def _draw_incomplete_card_box(
    draw: ImageDraw.ImageDraw,
    bbox: dict[str, int],
    label: str,
    *,
    font: Any,
) -> None:
    x1 = bbox["x"]
    y1 = bbox["y"]
    x2 = bbox["x"] + bbox["w"]
    y2 = bbox["y"] + bbox["h"]
    color = (180, 90, 0)
    dash = 7
    gap = 5
    for x in range(x1, x2, dash + gap):
        draw.line((x, y1, min(x + dash, x2), y1), fill=color, width=2)
        draw.line((x, y2, min(x + dash, x2), y2), fill=color, width=2)
    for y in range(y1, y2, dash + gap):
        draw.line((x1, y, x1, min(y + dash, y2)), fill=color, width=2)
        draw.line((x2, y, x2, min(y + dash, y2)), fill=color, width=2)
    layout = _overlay_label_layout(draw, bbox, label, font=font, max_width=min(180, max(1, bbox["w"])))
    if not layout:
        return
    draw.rectangle(layout["rect"], fill=(255, 240, 210))
    draw.text(layout["text_xy"], layout["text"], fill=(120, 62, 0), font=font)


def _draw_message_context_box(
    draw: ImageDraw.ImageDraw,
    bbox: dict[str, int],
    label: str,
    *,
    font: Any,
    parent_bbox: dict[str, int] | None = None,
) -> None:
    context_font = _message_context_overlay_font(font)
    x1 = bbox["x"]
    y1 = bbox["y"]
    x2 = bbox["x"] + bbox["w"]
    y2 = bbox["y"] + bbox["h"]
    color = (0, 150, 170)
    if parent_bbox:
        _draw_message_context_link(draw, bbox, parent_bbox, color=color)
    dash = 8
    gap = 3
    for x in range(x1, x2, dash + gap):
        draw.line((x, y1, min(x + dash, x2), y1), fill=color, width=3)
        draw.line((x, y2, min(x + dash, x2), y2), fill=color, width=3)
    for y in range(y1, y2, dash + gap):
        draw.line((x1, y, x1, min(y + dash, y2)), fill=color, width=3)
        draw.line((x2, y, x2, min(y + dash, y2)), fill=color, width=3)
    cx = x1 + max(1, bbox["w"] // 2)
    cy = y1 + max(1, bbox["h"] // 2)
    draw.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), fill=color, outline=(255, 255, 255), width=1)
    layout = _overlay_label_layout(draw, bbox, label, font=context_font, max_width=min(120, max(1, bbox["w"])))
    if not layout:
        return
    draw.rectangle(layout["rect"], fill=(0, 130, 150))
    draw.text(layout["text_xy"], layout["text"], fill=(255, 255, 255), font=context_font)


def _draw_context_parent_box(
    draw: ImageDraw.ImageDraw,
    bbox: dict[str, int],
    label: str,
    *,
    font: Any,
) -> None:
    _draw_box(
        draw,
        bbox,
        f"parent {label}",
        color=(24, 114, 204),
        font=font,
        width=4,
        label_fill=(24, 114, 204),
    )


def _draw_context_core_box(
    draw: ImageDraw.ImageDraw,
    bbox: dict[str, int],
    label: str,
    *,
    font: Any,
) -> None:
    _draw_box(
        draw,
        bbox,
        str(label or ""),
        color=(236, 126, 0),
        font=font,
        width=2,
        label_fill=(255, 236, 210),
        label_text_fill=(120, 62, 0),
    )


def _write_message_context_zoom(
    *,
    canvas: Image.Image,
    source_stem: str,
    context_items: list[tuple[dict[str, Any], dict[str, int]]],
    parent_bboxes: dict[str, dict[str, int]],
    timestamp: str,
) -> Path | None:
    boxes: list[dict[str, int]] = []
    for item, bbox in context_items:
        boxes.append(bbox)
        parent = parent_bboxes.get(str(item.get("semantic_parent_group_id") or ""))
        if parent:
            boxes.append(parent)
    crop_bbox = _padded_union_bbox(boxes, canvas_size=canvas.size, padding=60)
    if not crop_bbox:
        return None
    crop = canvas.crop(
        (
            crop_bbox["x"],
            crop_bbox["y"],
            crop_bbox["x"] + crop_bbox["w"],
            crop_bbox["y"] + crop_bbox["h"],
        )
    )
    zoom = crop.resize((crop.width * 2, crop.height * 2))
    out_dir = ARTIFACTS_DIR / "review-overlays"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{source_stem}__message-context-review-zoom__{timestamp}.png"
    zoom.save(out_path)
    return out_path


def _padded_union_bbox(
    boxes: list[dict[str, int]],
    *,
    canvas_size: tuple[int, int],
    padding: int,
) -> dict[str, int] | None:
    valid = [_bbox(box) for box in boxes]
    valid = [box for box in valid if box]
    if not valid:
        return None
    left = max(0, min(box["x"] for box in valid) - padding)
    top = max(0, min(box["y"] for box in valid) - padding)
    right = min(canvas_size[0], max(box["x"] + box["w"] for box in valid) + padding)
    bottom = min(canvas_size[1], max(box["y"] + box["h"] for box in valid) + padding)
    if right <= left or bottom <= top:
        return None
    return {"x": left, "y": top, "w": right - left, "h": bottom - top}


def _message_context_overlay_font(fallback: Any) -> Any:
    for font_name in ("arial.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(font_name, 16)
        except Exception:
            continue
    return fallback


def _draw_message_context_link(
    draw: ImageDraw.ImageDraw,
    child_bbox: dict[str, int],
    parent_bbox: dict[str, int],
    *,
    color: tuple[int, int, int],
) -> None:
    child_x = child_bbox["x"] + max(1, child_bbox["w"] // 2)
    child_y = child_bbox["y"] + max(1, child_bbox["h"] // 2)
    parent_x = parent_bbox["x"] + max(1, parent_bbox["w"] // 2)
    parent_y = parent_bbox["y"] + max(1, min(parent_bbox["h"] // 3, parent_bbox["h"] - 1))
    draw.line((child_x, child_y, parent_x, parent_y), fill=color, width=2)
    draw.ellipse((parent_x - 3, parent_y - 3, parent_x + 3, parent_y + 3), fill=color)


def _is_message_context_overlay_item(item: dict[str, Any]) -> bool:
    return bool(str(item.get("message_context_role") or "").strip() and str(item.get("semantic_parent_group_id") or "").strip())


def _message_context_overlay_label(item: dict[str, Any]) -> str:
    number = str(item.get("number") or "").strip()
    role = str(item.get("message_context_role") or item.get("role") or "context").strip()
    parent = str(item.get("semantic_parent_group_id") or "").strip()
    parent_short = parent.replace("message_item_", "msg_")
    prefix = f"{number} " if number else ""
    return f"{prefix}{role} -> {parent_short}"


def _message_parent_overlay_keys(item: dict[str, Any]) -> list[str]:
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    if role != "message_item":
        return []
    keys: list[str] = []
    for key in ("group_id", "item_id", "region_id", "id"):
        value = str(item.get(key) or "").strip()
        if value:
            keys.append(value)
    return list(dict.fromkeys(keys))


def _message_parent_bbox_map(numbered_regions: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    parent_bboxes: dict[str, dict[str, int]] = {}
    for region in numbered_regions:
        if _is_browser_chrome_region(region):
            continue
        for group in region.get("subregion_groups", []) if isinstance(region.get("subregion_groups"), list) else []:
            if not isinstance(group, dict):
                continue
            bbox = _parent_bounded_display_bbox(group)
            if not bbox:
                continue
            for parent_key in _message_parent_overlay_keys(group):
                parent_bboxes[parent_key] = bbox
        for item in region.get("numbered_items", []) if isinstance(region.get("numbered_items"), list) else []:
            if not isinstance(item, dict):
                continue
            bbox = _parent_bounded_display_bbox(item)
            if not bbox:
                continue
            for parent_key in _message_parent_overlay_keys(item):
                parent_bboxes[parent_key] = bbox
    return parent_bboxes


def _item_children(item: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    raw_children = item.get("children") if isinstance(item.get("children"), list) else []
    text_lines = metadata.get("text_lines") if isinstance(metadata.get("text_lines"), list) else []
    candidates = [*raw_children, *text_lines]
    result: list[dict[str, Any]] = []
    for index, child in enumerate(candidates):
        if not isinstance(child, dict):
            continue
        bbox = _bbox(child.get("bbox"))
        label = str(child.get("label") or child.get("text") or "").strip()
        if not label and not bbox:
            continue
        child_id = str(child.get("child_id") or child.get("item_id") or child.get("id") or f"text_line_{index + 1}")
        result.append(
            {
                "child_id": child_id,
                "item_id": child_id,
                "label": label,
                "role": str(child.get("role") or "text"),
                "bbox": bbox or {},
            }
        )
    return result


def _source_image_path(bundle: dict[str, Any]) -> str:
    for key in ("image_path", "source_image_path", "screenshot_path"):
        value = str(bundle.get(key) or "").strip()
        if value:
            return value
    return ""


def _is_primary_region_id(region_id: str) -> bool:
    lowered = str(region_id or "").casefold()
    return any(token in lowered for token in ("primary", "main", "content"))


def _primary_content_subregion_groups(
    *,
    region: dict[str, Any],
    numbered_items: list[dict[str, Any]],
    class_rule_profile: dict[str, Any] | None = None,
    image_path: str = "",
) -> list[dict[str, Any]]:
    strategy = str((class_rule_profile or {}).get("primary_content_strategy") or "evidence_balanced")
    dense_document_surface = _has_dense_code_or_document_surface(numbered_items)
    card_items = [
        item
        for item in numbered_items
        if _looks_like_card_item(item)
        and (
            not dense_document_surface
            or _has_explicit_visual_card_role(item)
        )
    ]
    rows = _group_card_items_by_row(card_items)
    groups: list[dict[str, Any]] = []
    for index, row in enumerate(rows if strategy != "text_structure_first" else [], start=1):
        if len(row) < 2:
            continue
        bbox = _bbox_union([item.get("bbox") for item in row])
        if not bbox:
            continue
        group_kind = _card_row_semantic_kind(row)
        partial_row = group_kind == "partial_visible_card"
        media_row = group_kind == "media_card"
        groups.append(
            {
                "contract_version": "learn_stage2_subregion_group_v1",
                "group_id": f"{'partial_visible_card_row' if partial_row else ('visual_card_row' if media_row else 'tile_card_row')}_{index}",
                "label": f"{'partial visible card row' if partial_row else ('visual media card row' if media_row else 'tile card row')} {index}",
                "role": "partial_visible_card_group" if partial_row else ("media_card_group" if media_row else "tile_card_group"),
                "bbox": bbox,
                "expected_item_role": group_kind,
                "homogeneity_rule": "same row and similar card/review item role from current screen inventory",
                "member_numbers": [str(item.get("number") or "") for item in row],
                "member_item_ids": [str(item.get("item_id") or "") for item in row],
                "source": "stage2_primary_content_card_row_grouping",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    groups.extend(
        _semantic_parent_groups(
            region=region,
            numbered_items=numbered_items,
            class_rule_profile=class_rule_profile,
            image_path=image_path,
        )
    )
    groups = _attach_card_row_child_groups(groups)
    groups.extend(_section_parent_groups(numbered_items=numbered_items, content_groups=groups))
    groups = _ensure_primary_items_have_subregion_parent(
        region=region,
        numbered_items=numbered_items,
        groups=groups,
        class_rule_profile=class_rule_profile,
    )
    groups.sort(key=lambda group: (_bbox_top(group), _bbox_left(group), str(group.get("group_id") or "")))
    return groups


def _attach_card_row_child_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    card_parents = [group for group in groups if str(group.get("role") or "") == "tile_card_parent"]
    if not card_parents:
        return groups
    result: list[dict[str, Any]] = []
    for group in groups:
        if str(group.get("role") or "") != "tile_card_group":
            result.append(group)
            continue
        row_members = {
            str(item_id or "").strip()
            for item_id in group.get("member_item_ids", [])
            if str(item_id or "").strip()
        }
        child_group_ids = [
            str(parent.get("group_id") or "").strip()
            for parent in card_parents
            if str(parent.get("group_id") or "").strip()
            and row_members.intersection(
                {
                    str(item_id or "").strip()
                    for item_id in parent.get("member_item_ids", [])
                    if str(item_id or "").strip()
                }
            )
        ]
        copied = deepcopy(group)
        if child_group_ids:
            copied["child_group_ids"] = child_group_ids
            copied["parent_child_policy"] = "card_row_is_structural_when_individual_card_parents_exist"
        result.append(copied)
    return result


def _card_row_semantic_kind(row: list[dict[str, Any]]) -> str:
    roles = {str(item.get("role") or "").casefold() for item in row}
    if roles == {"partial_visible_card"}:
        return "partial_visible_card"
    trusted_media_count = sum(
        1
        for item in row
        if str(item.get("role") or "").casefold() == "media_card"
        and str(item.get("source") or "").casefold() == "visual_card_segmenter"
    )
    return "media_card" if trusted_media_count >= 2 else "tile_card"


def _normalize_tile_group_member_roles(
    numbered_items: list[dict[str, Any]],
    subregion_groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    tile_member_ids = {
        str(item_id)
        for group in subregion_groups
        if str(group.get("role") or "") in {"tile_card_group", "tile_card_parent"}
        for item_id in group.get("member_item_ids", [])
        if str(item_id or "").strip()
    }
    generic_card_roles = {"news_card", "recommendation_item", "content_card"}
    normalized: list[dict[str, Any]] = []
    for item in numbered_items:
        item_id = str(item.get("item_id") or "")
        role = str(item.get("role") or "").casefold()
        if item_id not in tile_member_ids or role not in generic_card_roles:
            normalized.append(item)
            continue
        copied = deepcopy(item)
        copied["original_role"] = str(copied.get("role") or "")
        copied["role"] = "tile_card"
        copied["role_policy"] = "generic_card_role_normalized_from_tile_group_ownership"
        copied["review_only"] = True
        copied["display_only"] = True
        copied["execute_binding_enabled"] = False
        copied["artifact_is_authorization"] = False
        normalized.append(copied)
    return normalized


def _normalize_parallel_list_group_widths(
    groups: list[dict[str, Any]],
    *,
    region_bbox: dict[str, int] | None,
) -> list[dict[str, Any]]:
    if not region_bbox:
        return groups
    list_groups = [group for group in groups if str(group.get("role") or "") == "list_group" and _bbox(group.get("bbox"))]
    if len(list_groups) < 2:
        return groups
    bands: list[list[dict[str, Any]]] = []
    for group in sorted(list_groups, key=lambda item: (_bbox_top(item), _bbox_left(item))):
        bbox = _bbox(group.get("bbox"))
        if not bbox:
            continue
        band = next(
            (
                candidate
                for candidate in bands
                if abs((_bbox(candidate[0].get("bbox")) or {})["y"] - bbox["y"]) <= 40
            ),
            None,
        )
        if band is None:
            bands.append([group])
        else:
            band.append(group)
    for band in bands:
        if len(band) < 2:
            continue
        band.sort(key=_bbox_left)
        boxes = [_bbox(group.get("bbox")) for group in band]
        boxes = [bbox for bbox in boxes if bbox]
        target_width = max((bbox["w"] for bbox in boxes), default=0)
        if target_width <= 0:
            continue
        for index, group in enumerate(band):
            bbox = _bbox(group.get("bbox"))
            if not bbox or bbox["w"] >= target_width:
                continue
            next_x = (
                (_bbox(band[index + 1].get("bbox")) or {}).get("x", region_bbox["x"] + region_bbox["w"])
                if index + 1 < len(band)
                else region_bbox["x"] + region_bbox["w"]
            )
            width = min(target_width, next_x - bbox["x"], region_bbox["x"] + region_bbox["w"] - bbox["x"])
            if width <= bbox["w"]:
                continue
            group["bbox"] = {**bbox, "w": width}
            group["bbox_normalization"] = {
                "reason": "parallel_repeated_list_columns_share_complete_parent_width",
                "previous_bbox": bbox,
                "reference_width": target_width,
                "display_only": True,
            }
    return groups


def _ensure_primary_items_have_subregion_parent(
    *,
    region: dict[str, Any],
    numbered_items: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    class_rule_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not _is_primary_region_id(str(region.get("region_id") or "")) or not groups:
        return groups
    region_bbox = _bbox(region.get("bbox")) or _bbox(region.get("precise_bbox")) or {}
    if not region_bbox:
        return groups

    updated_groups = [deepcopy(group) for group in groups]
    item_by_id = {str(item.get("item_id") or ""): item for item in numbered_items if str(item.get("item_id") or "").strip()}
    assigned: set[str] = set()
    for group in updated_groups:
        for item_id in group.get("member_item_ids", []) if isinstance(group.get("member_item_ids"), list) else []:
            if str(item_id or "").strip():
                assigned.add(str(item_id))

    orphan_items: list[dict[str, Any]] = []
    for item in numbered_items:
        item_id = str(item.get("item_id") or "").strip()
        bbox = _bbox(item.get("bbox"))
        if not item_id or not bbox or item_id in assigned:
            continue
        containing_groups: list[tuple[int, dict[str, Any]]] = []
        for group in updated_groups:
            group_bbox = _bbox(group.get("bbox"))
            if not group_bbox:
                continue
            if _bbox_containment_ratio(bbox, group_bbox) >= 0.985:
                containing_groups.append((max(1, group_bbox["w"] * group_bbox["h"]), group))
        if containing_groups:
            containing_groups.sort(key=lambda pair: pair[0])
            _append_group_member(containing_groups[0][1], item, region_bbox=region_bbox)
            assigned.add(item_id)
        else:
            orphan_items.append(item)

    if len(orphan_items) < 4:
        return updated_groups

    strategy = str((class_rule_profile or {}).get("primary_content_strategy") or "evidence_balanced")
    spatial_columns = strategy == "independent_content_modules"
    for index, cluster in enumerate(
        _cluster_orphan_items_by_vertical_band(orphan_items, spatial_columns=spatial_columns),
        start=1,
    ):
        cluster_bbox = _bbox_union([item.get("bbox") for item in cluster])
        if not cluster_bbox:
            continue
        bounded = _intersect_bbox(region_bbox, _expand_bbox(cluster_bbox, pad_x=8, pad_y=8))
        if not bounded:
            continue
        updated_groups.append(
            {
                "contract_version": "learn_stage2_subregion_group_v1",
                "group_id": f"{_slug(str(region.get('region_id') or 'region'))}__ungrouped_review_region_{index}",
                "label": f"ungrouped review region {index}",
                "role": "ungrouped_review_region",
                "bbox": bounded,
                "member_numbers": [str(item.get("number") or "") for item in cluster],
                "member_item_ids": [str(item.get("item_id") or "") for item in cluster],
                "parent_child_policy": "main_content_visible_items_must_have_internal_review_region",
                "source": "stage2_primary_orphan_item_review_grouping",
                "review_only": True,
                "candidate_only": True,
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    return updated_groups


def _append_group_member(
    group: dict[str, Any],
    item: dict[str, Any],
    *,
    region_bbox: dict[str, int] | None = None,
) -> None:
    number = str(item.get("number") or "").strip()
    item_id = str(item.get("item_id") or "").strip()
    member_numbers = group.setdefault("member_numbers", [])
    if isinstance(member_numbers, list) and number and number not in member_numbers:
        member_numbers.append(number)
    member_item_ids = group.setdefault("member_item_ids", [])
    if isinstance(member_item_ids, list) and item_id and item_id not in member_item_ids:
        member_item_ids.append(item_id)
    previous_group_bbox = _bbox(group.get("bbox"))
    item_bbox = _bbox(item.get("bbox"))
    expanded_group_bbox = previous_group_bbox
    if previous_group_bbox and item_bbox:
        expanded_group_bbox = _bbox_union([previous_group_bbox, item_bbox])
        if expanded_group_bbox and region_bbox:
            expanded_group_bbox = _intersect_bbox(region_bbox, expanded_group_bbox)
        if expanded_group_bbox:
            group["bbox"] = expanded_group_bbox
    bbox_expanded = bool(previous_group_bbox and expanded_group_bbox and expanded_group_bbox != previous_group_bbox)
    repairs = group.setdefault("membership_repairs", [])
    if isinstance(repairs, list):
        repairs.append(
            {
                "contract_version": "learn_stage2_group_membership_repair_v1",
                "item_id": item_id,
                "number": number,
                "reason": "item_bbox_inside_group_bbox_but_missing_member_link",
                "bbox_expanded": bbox_expanded,
                "previous_group_bbox": deepcopy(previous_group_bbox) if previous_group_bbox else {},
                "repaired_group_bbox": deepcopy(expanded_group_bbox) if expanded_group_bbox else {},
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )


def _cluster_orphan_items_by_vertical_band(
    items: list[dict[str, Any]],
    *,
    spatial_columns: bool = False,
) -> list[list[dict[str, Any]]]:
    ordered = [item for item in items if _bbox(item.get("bbox"))]
    ordered.sort(key=lambda item: (_bbox_top(item), _bbox_left(item), str(item.get("item_id") or "")))
    if spatial_columns:
        clusters: list[list[dict[str, Any]]] = []
        cluster_boxes: list[dict[str, int]] = []
        for item in ordered:
            bbox = _bbox(item.get("bbox"))
            if not bbox:
                continue
            matching: list[tuple[float, int]] = []
            for index, cluster_bbox in enumerate(cluster_boxes):
                vertical_gap = max(
                    0,
                    bbox["y"] - (cluster_bbox["y"] + cluster_bbox["h"]),
                    cluster_bbox["y"] - (bbox["y"] + bbox["h"]),
                )
                if vertical_gap > 44:
                    continue
                overlap = max(
                    0,
                    min(bbox["x"] + bbox["w"], cluster_bbox["x"] + cluster_bbox["w"])
                    - max(bbox["x"], cluster_bbox["x"]),
                )
                overlap_ratio = overlap / max(1, min(bbox["w"], cluster_bbox["w"]))
                if overlap_ratio < 0.2:
                    continue
                matching.append((overlap_ratio, index))
            if not matching:
                clusters.append([item])
                cluster_boxes.append(dict(bbox))
                continue
            _, best_index = max(matching)
            clusters[best_index].append(item)
            cluster_boxes[best_index] = _bbox_union([cluster_boxes[best_index], bbox]) or cluster_boxes[best_index]
        return clusters

    clusters: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_bbox: dict[str, int] | None = None
    max_gap = 44
    for item in ordered:
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            continue
        if not current or not current_bbox:
            current = [item]
            current_bbox = bbox
            continue
        vertical_gap = bbox["y"] - (current_bbox["y"] + current_bbox["h"])
        if vertical_gap <= max_gap:
            current.append(item)
            current_bbox = _bbox_union([current_bbox, bbox])
        else:
            clusters.append(current)
            current = [item]
            current_bbox = bbox
    if current:
        clusters.append(current)
    return clusters


def _expand_settings_tile_visual_gutters(
    *,
    region: dict[str, Any],
    numbered_items: list[dict[str, Any]],
    groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    region_bbox = _bbox(region.get("precise_bbox")) or _bbox(region.get("bbox"))
    tile_groups = [group for group in groups if str(group.get("role") or "") == "tile_card_parent"]
    if not region_bbox or len(tile_groups) < 2:
        return groups
    heights = sorted(
        bbox["h"]
        for group in tile_groups
        if (bbox := _bbox(group.get("bbox"))) is not None
    )
    if not heights:
        return groups
    typical_height = heights[len(heights) // 2]
    inferred_width = max(36, min(72, int(round(typical_height * 0.75))))
    updated = [deepcopy(group) for group in groups]
    item_by_id = {
        str(item.get("item_id") or ""): item
        for item in numbered_items
        if str(item.get("item_id") or "").strip()
    }
    used_visual_ids: set[str] = set()
    for group in updated:
        if str(group.get("role") or "") != "tile_card_parent":
            continue
        group_bbox = _bbox(group.get("bbox"))
        if not group_bbox:
            continue
        anchor_x = _group_text_anchor_x(group, item_by_id=item_by_id)
        if anchor_x is None:
            continue
        inferred_x = max(region_bbox["x"], anchor_x - inferred_width)
        explicit_visuals = _leading_visual_items_for_group(
            group_bbox=group_bbox,
            text_anchor_x=anchor_x,
            inferred_left=inferred_x,
            numbered_items=numbered_items,
            used_item_ids=used_visual_ids,
        )
        explicit_ids = [str(item.get("item_id") or "") for item in explicit_visuals]
        used_visual_ids.update(explicit_ids)
        target_x = min([group_bbox["x"], inferred_x, *[_bbox_left(item) for item in explicit_visuals]])
        expanded_bbox = _bbox_union([group_bbox, *[item.get("bbox") for item in explicit_visuals]]) or group_bbox
        right = expanded_bbox["x"] + expanded_bbox["w"]
        expanded_bbox = {**expanded_bbox, "x": target_x, "w": max(1, right - target_x)}
        bounded_bbox = _intersect_bbox(region_bbox, expanded_bbox) or group_bbox
        group["bbox"] = bounded_bbox
        _prepend_group_members(group, explicit_visuals)
        group["leading_visual_gutter"] = {
            "source": "class_repeated_layout_inference",
            "class_strategy": "independent_control_cards",
            "inferred_width": inferred_width,
            "text_anchor_x": anchor_x,
            "explicit_visual_member_ids": explicit_ids,
            "previous_bbox": group_bbox,
            "display_only": True,
            "execute_binding_enabled": False,
        }
    return updated


def _expand_conversation_row_visual_gutters(
    *,
    region: dict[str, Any],
    numbered_items: list[dict[str, Any]],
    groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    region_bbox = _bbox(region.get("precise_bbox")) or _bbox(region.get("bbox"))
    if not region_bbox or len(groups) < 2:
        return groups
    item_by_id = {
        str(item.get("item_id") or ""): item
        for item in numbered_items
        if str(item.get("item_id") or "").strip()
    }
    anchors = [
        anchor
        for group in groups
        if (anchor := _group_text_anchor_x(group, item_by_id=item_by_id)) is not None
    ]
    top_values = sorted(
        bbox["y"]
        for group in groups
        if (bbox := _bbox(group.get("bbox"))) is not None
    )
    steps = sorted(second - first for first, second in zip(top_values, top_values[1:]) if 0 < second - first <= 96)
    if not anchors:
        return groups
    typical_step = steps[len(steps) // 2] if steps else 44
    inferred_width = max(28, min(64, int(round(typical_step * 0.9))))
    shared_left = max(region_bbox["x"], min(anchors) - inferred_width)
    updated = [deepcopy(group) for group in groups]
    used_visual_ids: set[str] = set()
    for group in updated:
        group_bbox = _bbox(group.get("bbox"))
        anchor_x = _group_text_anchor_x(group, item_by_id=item_by_id)
        if not group_bbox or anchor_x is None:
            continue
        explicit_visuals = _leading_visual_items_for_group(
            group_bbox=group_bbox,
            text_anchor_x=anchor_x,
            inferred_left=shared_left,
            numbered_items=numbered_items,
            used_item_ids=used_visual_ids,
        )
        explicit_ids = [str(item.get("item_id") or "") for item in explicit_visuals]
        used_visual_ids.update(explicit_ids)
        target_x = min([group_bbox["x"], shared_left, *[_bbox_left(item) for item in explicit_visuals]])
        expanded_bbox = _bbox_union([group_bbox, *[item.get("bbox") for item in explicit_visuals]]) or group_bbox
        right = expanded_bbox["x"] + expanded_bbox["w"]
        expanded_bbox = {**expanded_bbox, "x": target_x, "w": max(1, right - target_x)}
        bounded_bbox = _intersect_bbox(region_bbox, expanded_bbox) or group_bbox
        group["bbox"] = bounded_bbox
        _prepend_group_members(group, explicit_visuals)
        group["leading_visual_gutter"] = {
            "source": "class_repeated_layout_inference",
            "class_strategy": "conversation_rows",
            "inferred_width": inferred_width,
            "shared_track_x": shared_left,
            "text_anchor_x": anchor_x,
            "explicit_visual_member_ids": explicit_ids,
            "previous_bbox": group_bbox,
            "display_only": True,
            "execute_binding_enabled": False,
        }
    return updated


def _group_text_anchor_x(
    group: dict[str, Any],
    *,
    item_by_id: dict[str, dict[str, Any]],
) -> int | None:
    anchors: list[int] = []
    for item_id in group.get("member_item_ids", []) if isinstance(group.get("member_item_ids"), list) else []:
        item = item_by_id.get(str(item_id or ""))
        bbox = _bbox(item.get("bbox")) if isinstance(item, dict) else None
        role = str((item or {}).get("role") or (item or {}).get("item_type") or "").casefold()
        if bbox and any(token in role for token in ("text", "readable", "button", "tab", "label")):
            anchors.append(bbox["x"])
    return min(anchors) if anchors else None


def _leading_visual_items_for_group(
    *,
    group_bbox: dict[str, int],
    text_anchor_x: int,
    inferred_left: int,
    numbered_items: list[dict[str, Any]],
    used_item_ids: set[str],
) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for item in numbered_items:
        item_id = str(item.get("item_id") or "").strip()
        bbox = _bbox(item.get("bbox"))
        if not item_id or item_id in used_item_ids or not bbox or not _looks_like_leading_visual_item(item):
            continue
        if _vertical_overlap_ratio(group_bbox, bbox) < 0.45:
            continue
        if bbox["x"] < inferred_left - 8 or bbox["x"] >= text_anchor_x:
            continue
        if bbox["x"] + bbox["w"] > text_anchor_x + 8:
            continue
        matches.append(item)
    matches.sort(
        key=lambda item: (
            abs(_bbox_center_y_value(_bbox(item.get("bbox")) or {}) - _bbox_center_y_value(group_bbox)),
            -(_bbox(item.get("bbox")) or {}).get("x", 0),
        )
    )
    return matches[:1]


def _looks_like_leading_visual_item(item: dict[str, Any]) -> bool:
    text = " ".join(
        str(item.get(key) or "").casefold()
        for key in ("role", "item_type", "label")
    )
    return any(token in text for token in ("icon", "avatar", "glyph", "thumbnail", "头像", "图标"))


def _prepend_group_members(group: dict[str, Any], items: list[dict[str, Any]]) -> None:
    if not items:
        return
    item_ids = [str(item.get("item_id") or "") for item in items if str(item.get("item_id") or "").strip()]
    numbers = [str(item.get("number") or "") for item in items if str(item.get("number") or "").strip()]
    existing_ids = group.get("member_item_ids") if isinstance(group.get("member_item_ids"), list) else []
    existing_numbers = group.get("member_numbers") if isinstance(group.get("member_numbers"), list) else []
    group["member_item_ids"] = item_ids + [value for value in existing_ids if value not in item_ids]
    group["member_numbers"] = numbers + [value for value in existing_numbers if value not in numbers]


def _semantic_parent_groups(
    *,
    region: dict[str, Any],
    numbered_items: list[dict[str, Any]],
    class_rule_profile: dict[str, Any] | None = None,
    image_path: str = "",
) -> list[dict[str, Any]]:
    strategy = str((class_rule_profile or {}).get("primary_content_strategy") or "evidence_balanced")
    groups: list[dict[str, Any]] = []
    topbar_groups = _topbar_control_parent_groups(region=region, numbered_items=numbered_items)
    if strategy == "independent_control_cards":
        settings_status_groups = _settings_topbar_status_tile_parent_groups(
            region=region,
            numbered_items=numbered_items,
        )
        status_member_ids = {
            str(item_id)
            for group in settings_status_groups
            for item_id in group.get("member_item_ids", [])
        }
        topbar_groups = [
            group
            for group in topbar_groups
            if str(group.get("role") or "") != "topbar_control_cluster"
            or not status_member_ids.intersection(str(item_id) for item_id in group.get("member_item_ids", []))
        ]
        topbar_groups.extend(settings_status_groups)
    groups.extend(topbar_groups)
    groups.extend(
        _tile_card_parent_groups(
            region=region,
            numbered_items=numbered_items,
            include_inferred_text=strategy
            not in {"text_structure_first", "independent_content_modules"},
        )
    )
    if strategy == "independent_control_cards":
        groups = _expand_settings_tile_visual_gutters(
            region=region,
            numbered_items=numbered_items,
            groups=groups,
        )
    table_groups = _dense_aligned_table_parent_groups(
        region=region,
        numbered_items=numbered_items,
        minimum_row_count=4 if strategy == "row_table_first" else 8,
        image_path=image_path,
        require_explicit_container=strategy == "independent_content_modules",
    )
    groups.extend(table_groups)
    groups.extend(_notice_parent_groups(region=region, numbered_items=numbered_items))
    groups.extend(_list_row_parent_groups(region=region, numbered_items=numbered_items))
    groups.extend(_hero_panel_parent_groups(region=region, numbered_items=numbered_items))
    groups.extend(_member_list_parent_groups(region=region, numbered_items=numbered_items))
    stage1_5_source = region.get("input_stage1_5_subregion") if isinstance(region.get("input_stage1_5_subregion"), dict) else {}
    stage1_5_role = str(stage1_5_source.get("role") or region.get("role") or "").casefold()
    region_identity = " ".join(
        str(region.get(key) or "").casefold()
        for key in ("region_id", "zone_id", "label")
    )
    if not stage1_5_role and "conversation_list" in region_identity:
        stage1_5_role = "conversation_list"
    elif not stage1_5_role and "message_thread" in region_identity:
        stage1_5_role = "message_thread"
    elif not stage1_5_role and "bottom_composer" in region_identity:
        stage1_5_role = "bottom_composer"
    explicit_chat_subregion = stage1_5_role in {"conversation_list", "message_thread", "bottom_composer"}
    class_allows_chat_semantics = (
        bool((class_rule_profile or {}).get("allow_chat_semantics"))
        and _is_primary_region_id(str(region.get("region_id") or ""))
        and not explicit_chat_subregion
    )
    chat_surface_evidence = _stage2_region_has_chat_surface_evidence(region, numbered_items)
    conversation_list_evidence = _stage2_region_has_conversation_list_evidence(region, numbered_items)
    conversation_semantics_allowed = stage1_5_role == "conversation_list" or (
        not explicit_chat_subregion
        and (class_allows_chat_semantics or chat_surface_evidence or conversation_list_evidence)
    )
    message_semantics_allowed = stage1_5_role == "message_thread" or (
        not explicit_chat_subregion and (class_allows_chat_semantics or chat_surface_evidence)
    )
    conversation_groups: list[dict[str, Any]] = []
    if conversation_semantics_allowed:
        conversation_groups = _conversation_row_parent_groups(
            region=region,
            numbered_items=numbered_items,
            treat_primary_as_conversation_list=(
                stage1_5_role == "conversation_list"
                or class_allows_chat_semantics
                or conversation_list_evidence
            ),
        )
        if strategy == "conversation_rows":
            conversation_groups = _expand_conversation_row_visual_gutters(
                region=region,
                numbered_items=numbered_items,
                groups=conversation_groups,
            )
        groups.extend(conversation_groups)
    if message_semantics_allowed:
        groups.extend(_message_parent_groups(region=region, numbered_items=numbered_items))
    if conversation_groups:
        conversation_bboxes = [
            bbox
            for group in conversation_groups
            if (bbox := _bbox(group.get("bbox"))) is not None
        ]
        if conversation_bboxes:
            if strategy == "conversation_rows":
                groups = [
                    group
                    for group in groups
                    if str(group.get("role") or "") != "tile_card_parent"
                    or not any(
                        _bbox_containment_ratio(tile_bbox, row_bbox) >= 0.75
                        or _bbox_overlap_ratio(row_bbox, tile_bbox) >= 0.45
                        or _bbox_overlap_ratio(tile_bbox, row_bbox) >= 0.45
                        for row_bbox in conversation_bboxes
                        if (tile_bbox := _bbox(group.get("bbox"))) is not None
                    )
                ]
            else:
                groups = [
                    group
                    for group in groups
                    if str(group.get("role") or "") != "tile_card_parent"
                    or sum(
                        1
                        for row_bbox in conversation_bboxes
                        if (tile_bbox := _bbox(group.get("bbox"))) is not None
                        and _bbox_overlap_ratio(row_bbox, tile_bbox) >= 0.8
                    )
                    < 2
                ]
    groups.extend(_input_toolbar_parent_groups(region=region, numbered_items=numbered_items))
    table_member_ids = {
        str(item_id)
        for group in table_groups
        if str(group.get("role") or "") == "table_group"
        for item_id in group.get("member_item_ids", [])
        if str(item_id or "").strip()
    }
    if table_member_ids:
        groups = [
            group
            for group in groups
            if str(group.get("role") or "") != "tile_card_parent"
            or not table_member_ids.intersection(str(item_id) for item_id in group.get("member_item_ids", []))
        ]
    if strategy == "text_structure_first":
        list_bboxes = [
            bbox
            for group in groups
            if str(group.get("role") or "") == "list_group"
            if (bbox := _bbox(group.get("bbox"))) is not None
        ]
        groups = [
            group
            for group in groups
            if str(group.get("role") or "") != "tile_card_parent"
            or not any(
                _bbox_overlap_ratio(tile_bbox, list_bbox) >= 0.25
                for list_bbox in list_bboxes
                if (tile_bbox := _bbox(group.get("bbox"))) is not None
            )
        ]
    return groups


def _settings_topbar_status_tile_parent_groups(
    *,
    region: dict[str, Any],
    numbered_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if _bar_region_kind(str(region.get("region_id") or "")) != "top_bar":
        return []
    region_bbox = _bbox(region.get("bbox")) or _bbox(region.get("precise_bbox"))
    if not region_bbox:
        return []

    items = [item for item in numbered_items if _bbox(item.get("bbox")) and str(item.get("item_id") or "")]
    title_items = [
        item
        for item in items
        if str(item.get("role") or "").casefold() in {"text", "text_action", "nav_text_action"}
        and str(item.get("label") or "").strip()
    ]
    used_item_ids: set[str] = set()
    groups: list[dict[str, Any]] = []
    for title in title_items:
        title_id = str(title.get("item_id") or "")
        if title_id in used_item_ids:
            continue
        title_bbox = _bbox(title.get("bbox"))
        if not title_bbox:
            continue
        support_candidates: list[tuple[float, dict[str, Any]]] = []
        for item in items:
            item_id = str(item.get("item_id") or "")
            bbox = _bbox(item.get("bbox"))
            if not bbox or item_id == title_id or item_id in used_item_ids:
                continue
            if not str(item.get("label") or "").strip() or _horizontal_overlap_ratio(title_bbox, bbox) < 0.65:
                continue
            vertical_distance = abs((bbox["y"] + bbox["h"] / 2) - (title_bbox["y"] + title_bbox["h"] / 2))
            if vertical_distance > max(44, region_bbox["h"] * 0.32):
                continue
            if not item.get("children") and str(item.get("role") or "").casefold() not in {"text", "text_action"}:
                continue
            support_candidates.append((vertical_distance, item))
        if not support_candidates:
            continue
        support = min(support_candidates, key=lambda pair: pair[0])[1]
        support_bbox = _bbox(support.get("bbox"))
        if not support_bbox:
            continue

        content_union = _bbox_union([title_bbox, support_bbox])
        if not content_union:
            continue
        icon_candidates: list[tuple[float, dict[str, Any]]] = []
        for item in items:
            item_id = str(item.get("item_id") or "")
            bbox = _bbox(item.get("bbox"))
            if not bbox or item_id in {title_id, str(support.get("item_id") or "")} or item_id in used_item_ids:
                continue
            if str(item.get("role") or "").casefold() not in {"control", "icon", "icon_button"}:
                continue
            if bbox["w"] > region_bbox["w"] * 0.16 or bbox["h"] > region_bbox["h"] * 0.55:
                continue
            x_overlap = _horizontal_overlap_ratio(content_union, bbox)
            center_delta = abs(
                (bbox["x"] + bbox["w"] / 2) - (content_union["x"] + content_union["w"] / 2)
            )
            if x_overlap < 0.45 and center_delta > max(content_union["w"], bbox["w"]) * 0.35:
                continue
            if bbox["y"] > title_bbox["y"] or bbox["y"] + bbox["h"] < title_bbox["y"] - region_bbox["h"] * 0.28:
                continue
            icon_candidates.append((center_delta + abs(title_bbox["y"] - (bbox["y"] + bbox["h"])), item))
        if not icon_candidates:
            continue
        icon = min(icon_candidates, key=lambda pair: pair[0])[1]
        icon_bbox = _bbox(icon.get("bbox"))
        if not icon_bbox:
            continue

        parent_union = _bbox_union([title_bbox, support_bbox, icon_bbox])
        if not parent_union:
            continue
        horizontal_padding = max(12, round(icon_bbox["w"] * 0.25))
        parent_bbox = _clip_bbox(
            region_bbox,
            {
                "x": parent_union["x"] - horizontal_padding,
                "y": parent_union["y"],
                "w": parent_union["w"] + horizontal_padding * 2,
                "h": parent_union["h"],
            },
        )
        member_items = [icon, title, support]
        member_ids = [str(item.get("item_id") or "") for item in member_items]
        used_item_ids.update(member_ids)
        groups.append(
            {
                "contract_version": "learn_stage2_subregion_group_v1",
                "group_id": f"settings_status_tile_{len(groups) + 1}",
                "label": str(title.get("label") or "settings status tile"),
                "role": "settings_status_tile",
                "bbox": parent_bbox,
                "child_group_roles": _unique_roles(member_items),
                "member_numbers": [str(item.get("number") or "") for item in member_items],
                "member_item_ids": member_ids,
                "adjacent_fragment_merged": True,
                "parent_child_policy": "settings_status_icon_title_and_value_share_one_review_parent",
                "bbox_policy": "settings_status_tile_union_with_visual_icon_gutter",
                "source": "class_repeated_settings_status_tile",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    return groups


def _dense_aligned_table_parent_groups(
    *,
    region: dict[str, Any],
    numbered_items: list[dict[str, Any]],
    minimum_row_count: int,
    image_path: str = "",
    require_explicit_container: bool = False,
) -> list[dict[str, Any]]:
    if not _is_primary_region_id(str(region.get("region_id") or "")):
        return []
    region_bbox = _bbox(region.get("precise_bbox")) or _bbox(region.get("bbox"))
    if not region_bbox:
        return []
    table_container = _dominant_table_container(numbered_items, region_bbox=region_bbox)
    table_container_bbox = _bbox(table_container.get("bbox")) if table_container else None
    if require_explicit_container and not table_container_bbox:
        return []
    text_items = [
        item
        for item in numbered_items
        if str(item.get("role") or "").casefold() in {"text", "label", "cell", "partial_visible_card"}
        and _bbox(item.get("bbox"))
        and (not table_container_bbox or _bbox_center_inside(_bbox(item.get("bbox")), table_container_bbox))
    ]
    rows: list[dict[str, Any]] = []
    for item in sorted(text_items, key=lambda entry: (_bbox_top(entry), _bbox_left(entry))):
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            continue
        center_y = _bbox_center_y_value(bbox)
        row = min(rows, key=lambda candidate: abs(candidate["center_y"] - center_y), default=None)
        tolerance = max(8, min(16, int(bbox["h"] * 0.7)))
        if row is None or abs(row["center_y"] - center_y) > tolerance:
            rows.append(
                {
                    "center_y": center_y,
                    "items": [item],
                    "partial_visible": str(item.get("role") or "").casefold() == "partial_visible_card",
                }
            )
            continue
        row["items"].append(item)
        row["partial_visible"] = bool(row.get("partial_visible")) or (
            str(item.get("role") or "").casefold() == "partial_visible_card"
        )
        centers = [_bbox_center_y_value(_bbox(entry.get("bbox")) or bbox) for entry in row["items"]]
        row["center_y"] = sum(centers) / len(centers)

    row_entries: list[tuple[dict[str, Any], list[dict[str, Any]], int]] = []
    for row in rows:
        members = sorted(row["items"], key=_bbox_left)
        boxes = [_bbox(item.get("bbox")) for item in members]
        boxes = [box for box in boxes if box]
        if len(boxes) < 3:
            continue
        span = max(box["x"] + box["w"] for box in boxes) - min(box["x"] for box in boxes)
        row_entries.append((row, members, span))
    if len(row_entries) < max(4, minimum_row_count):
        return []
    ordered_spans = sorted(span for _row, _members, span in row_entries)
    typical_span = ordered_spans[len(ordered_spans) // 2]
    minimum_span = max(
        220,
        min(int(region_bbox["w"] * 0.18), int(round(typical_span * 0.9))),
    )
    candidates = []
    for row, members, span in row_entries:
        if span < minimum_span:
            continue
        candidates.append(
            {
                "center_y": row["center_y"],
                "items": members,
                "partial_visible": bool(row.get("partial_visible")),
            }
        )
    if len(candidates) < max(4, minimum_row_count):
        return []

    alignment_tolerance = max(12, int(region_bbox["w"] * 0.012))
    column_clusters: list[dict[str, Any]] = []
    for row_index, row in enumerate(candidates):
        for item in row["items"]:
            x = _bbox_left(item)
            target = min(
                column_clusters,
                key=lambda cluster: abs(int(cluster["x"]) - x),
                default=None,
            )
            if target is None or abs(int(target["x"]) - x) > alignment_tolerance:
                column_clusters.append({"x": x, "values": [x], "row_indexes": {row_index}})
                continue
            target["values"].append(x)
            target["row_indexes"].add(row_index)
            values = sorted(int(value) for value in target["values"])
            target["x"] = values[len(values) // 2]
    required_column_support = max(minimum_row_count, int(len(candidates) * 0.55))
    column_lefts = sorted(
        int(cluster["x"])
        for cluster in column_clusters
        if len(cluster["row_indexes"]) >= required_column_support
    )
    if len(column_lefts) < 3:
        return []
    text_heights = sorted(
        bbox["h"]
        for item in text_items
        if (bbox := _bbox(item.get("bbox"))) is not None
    )
    median_text_height = text_heights[len(text_heights) // 2] if text_heights else alignment_tolerance
    row_column_match_tolerance = max(
        alignment_tolerance,
        min(28, int(round(median_text_height * 0.9))),
    )
    def matched_column_count(row: dict[str, Any]) -> int:
        return sum(
            1
            for column_x in column_lefts
            if any(abs(_bbox_left(item) - column_x) <= row_column_match_tolerance for item in row["items"])
        )

    strict_candidates = [
        row
        for row in candidates
        if matched_column_count(row) >= 3
    ]
    if len(strict_candidates) < max(4, minimum_row_count):
        return []
    strict_centers = sorted(float(row["center_y"]) for row in strict_candidates)
    center_steps = [
        second - first
        for first, second in zip(strict_centers, strict_centers[1:])
        if 12 <= second - first <= 64
    ]
    row_step = 0.0
    if len(center_steps) >= 3:
        ordered_steps = sorted(center_steps)
        row_step = float(ordered_steps[len(ordered_steps) // 2])
    recovered_candidates: list[dict[str, Any]] = []
    if row_step > 0:
        rhythm_tolerance = max(3.0, row_step * 0.2)
        strict_ids = {id(row) for row in strict_candidates}
        for row in candidates:
            if id(row) in strict_ids or matched_column_count(row) < 2:
                continue
            nearest_delta = min(abs(float(row["center_y"]) - center) for center in strict_centers)
            step_count = max(1, round(nearest_delta / row_step))
            if abs(nearest_delta - step_count * row_step) <= rhythm_tolerance:
                recovered_candidates.append(row)
    candidates = [*strict_candidates, *recovered_candidates]

    shared_left = min(_bbox_left(item) for row in candidates for item in row["items"])
    shared_right = max(
        bbox["x"] + bbox["w"]
        for row in candidates
        for item in row["items"]
        if (bbox := _bbox(item.get("bbox"))) is not None
    )
    right_limit = (
        table_container_bbox["x"] + table_container_bbox["w"]
        if table_container_bbox
        else min(region_bbox["x"] + region_bbox["w"], shared_right + 8)
    )
    left_limit = table_container_bbox["x"] if table_container_bbox else max(region_bbox["x"], shared_left - 8)
    row_groups: list[dict[str, Any]] = []
    all_member_numbers: list[str] = []
    all_member_ids: list[str] = []
    for row_index, row in enumerate(sorted(candidates, key=lambda entry: entry["center_y"]), start=1):
        members = [item for item in row["items"] if _bbox_left(item) < right_limit]
        if len(members) < 3:
            continue
        bbox = _bbox_union([item.get("bbox") for item in members])
        if not bbox:
            continue
        bbox = _clip_bbox(region_bbox, _expand_bbox(bbox, pad_x=8, pad_y=2))
        if table_container_bbox:
            bbox = _clip_bbox(
                table_container_bbox,
                {
                    "x": table_container_bbox["x"],
                    "y": bbox["y"],
                    "w": table_container_bbox["w"],
                    "h": bbox["h"],
                },
            )
        else:
            bbox = _clip_bbox(
                region_bbox,
                {
                    "x": left_limit,
                    "y": bbox["y"],
                    "w": max(1, right_limit - left_limit),
                    "h": bbox["h"],
                },
            )
        member_numbers = [str(item.get("number") or "") for item in members]
        member_ids = [str(item.get("item_id") or "") for item in members]
        group_id = f"table_row_{row_index}"
        partial_visible = bool(row.get("partial_visible"))
        row_group = {
                "contract_version": "learn_stage2_subregion_group_v1",
                "group_id": group_id,
                "label": str(members[0].get("label") or f"table row {row_index}"),
                "role": "table_row",
                "bbox": bbox,
                "member_numbers": member_numbers,
                "member_item_ids": member_ids,
                "source": (
                    "stage2_dense_aligned_table_partial_row_synthesis"
                    if partial_visible
                    else "stage2_dense_aligned_table_row_synthesis"
                ),
                "parent_child_policy": "aligned_multi_column_cells_bind_to_same_row_parent",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        if partial_visible:
            row_group["partial_visible"] = True
            row_group["review_only"] = True
        row_groups.append(row_group)
        all_member_numbers.extend(member_numbers)
        all_member_ids.extend(member_ids)
    if len(row_groups) < max(4, minimum_row_count):
        return []
    if table_container_bbox and image_path:
        row_groups.extend(
            _complete_datagrid_rows_from_visual_evidence(
                image_path=image_path,
                table_bbox=table_container_bbox,
                row_groups=row_groups,
            )
        )
    table_bbox = table_container_bbox or _bbox_union([group.get("bbox") for group in row_groups])
    if not table_bbox:
        return []
    table_group_id = "table_group_1"
    for group in row_groups:
        group["parent_group_id"] = table_group_id
    container_owned_items = (
        [
            item
            for item in numbered_items
            if _bbox_center_inside(_bbox(item.get("bbox")), table_container_bbox)
        ]
        if table_container_bbox
        else []
    )
    container_member_numbers = [str(item.get("number") or "") for item in container_owned_items]
    container_member_ids = [str(item.get("item_id") or "") for item in container_owned_items]
    table_group = {
        "contract_version": "learn_stage2_subregion_group_v1",
        "group_id": table_group_id,
        "label": "aligned multi-column table",
        "role": "table_group",
        "bbox": table_bbox,
        "child_group_ids": [str(group["group_id"]) for group in row_groups],
        "child_group_roles": ["table_row" for _ in row_groups],
        "member_numbers": list(
            dict.fromkeys(number for number in [*container_member_numbers, *all_member_numbers] if number)
        ),
        "member_item_ids": list(
            dict.fromkeys(item_id for item_id in [*container_member_ids, *all_member_ids] if item_id)
        ),
        "source": (
            "stage2_explicit_datagrid_parent_synthesis"
            if table_container_bbox
            else "stage2_dense_aligned_table_parent_synthesis"
        ),
        "parent_child_policy": "repeated_aligned_rows_form_table_group",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    return [*row_groups, table_group]


def _complete_datagrid_rows_from_visual_evidence(
    *,
    image_path: str,
    table_bbox: dict[str, int],
    row_groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(row_groups) < 4 or not image_path or not Path(image_path).is_file():
        return []
    centers = sorted(
        _bbox_center_y_value(bbox)
        for group in row_groups
        if (bbox := _bbox(group.get("bbox")))
    )
    if len(centers) < 4:
        return []
    steps = [second - first for first, second in zip(centers, centers[1:]) if 16 <= second - first <= 56]
    if len(steps) < 3:
        return []
    ordered_steps = sorted(steps)
    row_step = int(round(ordered_steps[len(ordered_steps) // 2]))
    step_tolerance = max(3, int(round(row_step * 0.18)))
    regular_steps = [step for step in steps if abs(step - row_step) <= step_tolerance]
    if len(regular_steps) < max(3, int(len(steps) * 0.6)):
        return []
    heights = sorted(
        bbox["h"]
        for group in row_groups
        if (bbox := _bbox(group.get("bbox")))
    )
    row_height = max(10, min(row_step, heights[len(heights) // 2]))
    try:
        import numpy as np  # type: ignore

        gray = np.asarray(Image.open(image_path).convert("L"), dtype=np.float32)
    except (ImportError, OSError, ValueError):
        return []
    image_height, image_width = gray.shape[:2]
    table_left = max(0, table_bbox["x"] + max(4, int(table_bbox["w"] * 0.01)))
    table_right = min(
        image_width,
        table_bbox["x"] + table_bbox["w"] - max(4, int(table_bbox["w"] * 0.01)),
    )
    table_top = max(0, table_bbox["y"])
    table_bottom = min(image_height, table_bbox["y"] + table_bbox["h"])
    if table_right - table_left < 120 or table_bottom - table_top < row_step * 4:
        return []
    vertical_diff = np.abs(np.diff(gray[:, table_left:table_right], axis=0))

    def visual_score(center_y: int) -> tuple[float, float, int]:
        half_band = max(5, row_height // 2)
        start = max(table_top, center_y - half_band)
        stop = min(table_bottom - 1, center_y + half_band)
        best_score = 0.0
        best_active_ratio = 0.0
        best_y = start
        for y in range(start, stop):
            line = vertical_diff[y]
            active_ratio = float(np.mean(line > 20.0))
            if active_ratio >= 0.85:
                continue
            score = float(np.mean(line))
            if score > best_score:
                best_score = score
                best_active_ratio = active_ratio
                best_y = y
        return best_score, best_active_ratio, best_y

    confirmed_scores = [visual_score(int(round(center)))[0] for center in centers]
    positive_scores = sorted(score for score in confirmed_scores if score > 0.0)
    if len(positive_scores) < 3:
        return []
    baseline_score = positive_scores[len(positive_scores) // 2]
    score_threshold = max(4.0, baseline_score * 0.45)
    completed: list[dict[str, Any]] = []
    candidate_center = int(round(centers[-1])) + row_step
    consecutive_empty = 0
    while candidate_center - row_height // 2 < table_bottom and consecutive_empty < 2:
        score, active_ratio, evidence_y = visual_score(candidate_center)
        passed = score >= score_threshold and active_ratio >= 0.01
        if not passed:
            consecutive_empty += 1
            candidate_center += row_step
            continue
        consecutive_empty = 0
        row_index = len(row_groups) + len(completed) + 1
        row_y = max(table_top, candidate_center - row_height // 2)
        row_bottom = min(table_bottom, row_y + row_height)
        completed.append(
            {
                "contract_version": "learn_stage2_subregion_group_v1",
                "group_id": f"table_row_{row_index}",
                "label": f"visual table row {row_index}",
                "role": "table_row",
                "bbox": {
                    "x": table_bbox["x"],
                    "y": row_y,
                    "w": table_bbox["w"],
                    "h": max(1, row_bottom - row_y),
                },
                "member_numbers": [],
                "member_item_ids": [],
                "source": "stage2_datagrid_visual_row_completion",
                "parent_child_policy": "visual_row_evidence_extends_explicit_datagrid_without_semantic_fabrication",
                "visual_evidence": {
                    "passed": True,
                    "score": round(score, 4),
                    "threshold": round(score_threshold, 4),
                    "active_ratio": round(active_ratio, 4),
                    "evidence_y": evidence_y,
                    "row_step": row_step,
                },
                "review_only": True,
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
        candidate_center += row_step
    return completed


def _dominant_table_container(
    numbered_items: list[dict[str, Any]],
    *,
    region_bbox: dict[str, int],
) -> dict[str, Any] | None:
    region_area = max(1, region_bbox["w"] * region_bbox["h"])
    candidates: list[dict[str, Any]] = []
    for item in numbered_items:
        role = str(item.get("role") or item.get("item_type") or "").casefold().replace("_", "")
        if role not in {"datagrid", "table"}:
            continue
        bbox = _bbox(item.get("bbox"))
        if not bbox or _bbox_containment_ratio(bbox, region_bbox) < 0.8:
            continue
        if bbox["w"] < region_bbox["w"] * 0.5 or bbox["h"] < region_bbox["h"] * 0.3:
            continue
        if bbox["w"] * bbox["h"] < region_area * 0.2:
            continue
        candidates.append(item)
    return max(candidates, key=lambda item: (_bbox(item.get("bbox")) or {"w": 0, "h": 0})["w"] * (_bbox(item.get("bbox")) or {"w": 0, "h": 0})["h"], default=None)


def _stage2_region_has_chat_surface_evidence(
    region: dict[str, Any],
    numbered_items: list[dict[str, Any]],
) -> bool:
    stage1_5 = region.get("input_stage1_5_subregion") if isinstance(region.get("input_stage1_5_subregion"), dict) else {}
    region_text = " ".join(
        str(value or "").casefold()
        for value in (
            region.get("region_id"),
            region.get("role"),
            region.get("label"),
            stage1_5.get("role"),
            stage1_5.get("label"),
        )
    )
    if any(token in region_text for token in ("conversation_list", "message_thread", "bottom_composer", "chat_surface")):
        return True
    evidence_categories: set[str] = set()
    strong_chat_semantics = False
    timestamp_count = 0
    sender_context_count = 0
    long_message_like_text_count = 0
    for item in numbered_items:
        item_text = " ".join(
            str(item.get(key) or "").casefold()
            for key in ("item_id", "role", "item_type")
        )
        label_text = str(item.get("label") or "").casefold()
        bbox = _bbox(item.get("bbox"))
        if _looks_like_timestamp_label(str(item.get("label") or "")):
            timestamp_count += 1
        if _looks_like_sender_or_level_context(item):
            sender_context_count += 1
        if (
            bbox
            and bbox["w"] >= 120
            and str(item.get("role") or item.get("item_type") or "").casefold() in {"text", "readable", "message_text"}
            and not _looks_like_timestamp_label(str(item.get("label") or ""))
        ):
            long_message_like_text_count += 1
        if any(token in item_text for token in ("conversation_list", "conversation_row", "session_list")):
            evidence_categories.add("conversation")
        if any(token in item_text for token in ("message_thread", "message_bubble", "image_message", "chat_thread")):
            evidence_categories.add("message")
            strong_chat_semantics = True
        if any(token in item_text for token in ("message_text", "sender_label", "message_time")):
            evidence_categories.add("message")
            strong_chat_semantics = True
        if any(token in item_text for token in ("composer", "message_input", "send_button", "input_toolbar")):
            evidence_categories.add("composer")
        if any(
            phrase in label_text
            for phrase in ("chat history", "conversation history", "message history", "聊天记录", "会话列表")
        ):
            strong_chat_semantics = True
    repeated_message_context = timestamp_count >= 2 and sender_context_count >= 1 and long_message_like_text_count >= 1
    return strong_chat_semantics or len(evidence_categories) >= 2 or repeated_message_context


def _stage2_region_has_conversation_list_evidence(
    region: dict[str, Any],
    numbered_items: list[dict[str, Any]],
) -> bool:
    tokens = (
        "conversation_list",
        "session_list",
        "friends_list",
        "friend_list",
        "contact_list",
        "conversation list",
        "friends list",
        "friend list",
        "contact list",
        "会话列表",
        "好友列表",
        "联系人列表",
    )
    region_text = " ".join(
        str(region.get(key) or "").casefold()
        for key in ("region_id", "role", "label")
    )
    if any(token in region_text for token in tokens):
        return True
    for item in numbered_items:
        role = str(item.get("role") or item.get("item_type") or "").casefold()
        if not any(token in role for token in ("window", "container", "list", "region")):
            continue
        item_text = " ".join(
            str(item.get(key) or "").casefold()
            for key in ("item_id", "role", "item_type", "label")
        )
        if any(token in item_text for token in tokens):
            return True
    return False


def _tile_card_parent_groups(
    *,
    region: dict[str, Any],
    numbered_items: list[dict[str, Any]],
    include_inferred_text: bool = True,
) -> list[dict[str, Any]]:
    family = _stage1_region_family(region)
    region_text = " ".join(
        str(region.get(key) or "").casefold()
        for key in ("region_id", "zone_id", "label", "role")
    )
    if family != "main_content" and not any(token in region_text for token in ("primary", "main_content", "content")):
        return []
    dense_document_surface = _has_dense_code_or_document_surface(numbered_items)
    card_items = [
        item
        for item in numbered_items
        if _looks_like_tile_card_parent_candidate(item)
        and (
            not dense_document_surface
            or _has_explicit_visual_card_role(item)
        )
    ]
    groups: list[dict[str, Any]] = []
    text_items = [item for item in numbered_items if _looks_like_tile_text_child(item)]
    for index, card in enumerate(sorted(card_items, key=lambda item: (_bbox_top(item), _bbox_left(item))), start=1):
        card_bbox = _bbox(card.get("bbox"))
        card_id = str(card.get("item_id") or "").strip()
        if not card_bbox or not card_id:
            continue
        children = [
            item
            for item in text_items
            if str(item.get("item_id") or "").strip() != card_id
            and (
                (
                    _bbox_center_inside(_bbox(item.get("bbox")), card_bbox)
                    and _bbox_containment_ratio(_bbox(item.get("bbox")) or {}, card_bbox) >= 0.55
                )
                or _is_attached_tile_parent_text_child(item, card_bbox)
            )
        ]
        if not children:
            continue
        members = [card, *sorted(children, key=lambda item: (_bbox_top(item), _bbox_left(item)))]
        parent_bbox = _bbox_union([member.get("bbox") for member in members]) or card_bbox
        groups.append(
            {
                "contract_version": "learn_stage2_subregion_group_v1",
                "group_id": f"tile_card_parent_{index}_{_slug(card_id)}",
                "label": str(card.get("label") or f"tile card {index}"),
                "role": "tile_card_parent",
                "bbox": parent_bbox,
                "member_numbers": [str(item.get("number") or "") for item in members],
                "member_item_ids": [str(item.get("item_id") or "") for item in members],
                "parent_child_policy": "single_tile_card_bbox_contains_internal_text_children",
                "bbox_policy": "use_card_bbox_plus_directly_attached_internal_title_without_sibling_or_section",
                "source": "stage2_primary_tile_card_parent_grouping",
                "review_only": True,
                "candidate_only": True,
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    if include_inferred_text and not dense_document_surface:
        groups.extend(
            _repeated_text_column_parent_groups(
                region=region,
                numbered_items=numbered_items,
                existing_groups=groups,
                start_index=len(groups) + 1,
            )
        )
        groups.extend(
            _text_only_tile_card_parent_groups(
                region=region,
                numbered_items=numbered_items,
                existing_groups=groups,
                start_index=len(groups) + 1,
            )
        )
    deduplicated = _merge_duplicate_tile_card_parent_groups(groups)
    return _merge_adjacent_tile_card_parent_fragments(deduplicated)


def _has_dense_code_or_document_surface(numbered_items: list[dict[str, Any]]) -> bool:
    text_items = [
        item
        for item in numbered_items
        if str(item.get("role") or "").casefold() == "text"
        or str(item.get("item_type") or "").casefold() in {"text", "readable"}
    ]
    if len(text_items) < 12:
        return False

    code_signal_count = 0
    for item in text_items:
        label = str(item.get("label") or item.get("text") or "").strip().casefold()
        if not label:
            continue
        if (
            "@@" in label
            or ".get(" in label
            or label.startswith(("def ", "class ", "return ", "import ", "from "))
            or (label.startswith(("if ", "for ", "while ", "with ")) and label.endswith(":"))
            or any(token in label for token in (".py", ".ts", ".tsx", ".js", ".rs", ".java"))
        ):
            code_signal_count += 1

    structured_workspace_evidence = any(
        str(item.get("role") or "").casefold() in {"list", "tree", "table", "document", "code", "diff"}
        for item in numbered_items
    )
    return code_signal_count >= 3 and structured_workspace_evidence


def _normalize_dense_document_semantic_card_roles(
    numbered_items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not _has_dense_code_or_document_surface(numbered_items):
        return list(numbered_items), {
            "applied": False,
            "reason": "dense_document_evidence_missing",
            "normalized_count": 0,
        }

    weak_semantic_card_roles = {"news_card", "recommendation_item", "tile_card"}
    normalized_items: list[dict[str, Any]] = []
    normalized_item_ids: list[str] = []
    for item in numbered_items:
        roles = {
            str(item.get("role") or "").casefold(),
            str(item.get("original_role") or "").casefold(),
        }
        if not roles.intersection(weak_semantic_card_roles) or _has_explicit_visual_card_role(item):
            normalized_items.append(item)
            continue
        copied = deepcopy(item)
        copied.setdefault("original_role", str(copied.get("role") or ""))
        copied["role"] = "document_section"
        copied["role_policy"] = "dense_document_semantic_card_downgraded_to_read_only_section"
        copied["review_only"] = True
        copied["display_only"] = True
        copied["execute_binding_enabled"] = False
        copied["artifact_is_authorization"] = False
        normalized_items.append(copied)
        normalized_item_ids.append(str(copied.get("item_id") or ""))
    return normalized_items, {
        "applied": bool(normalized_item_ids),
        "reason": "dense_document_weak_card_semantics_downgraded",
        "normalized_count": len(normalized_item_ids),
        "normalized_item_ids": normalized_item_ids,
    }


def _has_explicit_visual_card_role(item: dict[str, Any]) -> bool:
    roles = {
        str(item.get("role") or "").casefold(),
        str(item.get("original_role") or "").casefold(),
    }
    return bool(roles.intersection({"content_card", "media_card"}))


def _is_attached_tile_parent_text_child(item: dict[str, Any], card_bbox: dict[str, int]) -> bool:
    item_bbox = _bbox(item.get("bbox"))
    if not item_bbox or item_bbox["y"] >= card_bbox["y"]:
        return False
    item_bottom = item_bbox["y"] + item_bbox["h"]
    if item_bottom < card_bbox["y"] - 12:
        return False
    center_x = item_bbox["x"] + item_bbox["w"] / 2
    if not card_bbox["x"] <= center_x <= card_bbox["x"] + card_bbox["w"]:
        return False
    if abs(item_bbox["x"] - card_bbox["x"]) > max(24, int(card_bbox["w"] * 0.16)):
        return False
    if _horizontal_overlap_ratio(item_bbox, card_bbox) < 0.45:
        return False
    return item_bbox["h"] <= max(48, int(card_bbox["h"] * 0.35))


def _merge_duplicate_tile_card_parent_groups(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for group in groups:
        if str(group.get("role") or "") != "tile_card_parent":
            merged.append(group)
            continue
        bbox = _bbox(group.get("bbox"))
        duplicate = next(
            (
                existing
                for existing in merged
                if str(existing.get("role") or "") == "tile_card_parent"
                and bbox
                and (existing_bbox := _bbox(existing.get("bbox")))
                and min(
                    _bbox_containment_ratio(bbox, existing_bbox),
                    _bbox_containment_ratio(existing_bbox, bbox),
                )
                >= 0.82
            ),
            None,
        )
        if duplicate is None:
            merged.append(deepcopy(group))
            continue
        duplicate["bbox"] = _bbox_union([duplicate.get("bbox"), group.get("bbox")]) or duplicate.get("bbox")
        for key in ("member_numbers", "member_item_ids"):
            existing_values = duplicate.setdefault(key, [])
            if not isinstance(existing_values, list):
                existing_values = []
                duplicate[key] = existing_values
            for value in group.get(key, []) if isinstance(group.get(key), list) else []:
                if value not in existing_values:
                    existing_values.append(value)
        merged_ids = duplicate.setdefault("merged_duplicate_group_ids", [])
        if isinstance(merged_ids, list):
            group_id = str(group.get("group_id") or "").strip()
            if group_id and group_id not in merged_ids:
                merged_ids.append(group_id)
        duplicate["duplicate_evidence_merged"] = True
        duplicate["duplicate_merge_policy"] = "same_layer_tile_parent_with_mutual_geometric_containment"
    return merged


def _merge_adjacent_tile_card_parent_fragments(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = [deepcopy(group) for group in groups]
    changed = True
    while changed:
        changed = False
        for first_index, first in enumerate(merged):
            if str(first.get("role") or "") != "tile_card_parent":
                continue
            first_bbox = _bbox(first.get("bbox"))
            if not first_bbox:
                continue
            for second_index in range(first_index + 1, len(merged)):
                second = merged[second_index]
                if str(second.get("role") or "") != "tile_card_parent":
                    continue
                second_bbox = _bbox(second.get("bbox"))
                if (
                    not second_bbox
                    or not _tile_parent_fragment_merge_source(first)
                    or not _tile_parent_fragment_merge_source(second)
                    or not _touching_fragments_share_content_column(first_bbox, second_bbox)
                ):
                    continue
                first["bbox"] = _bbox_union([first_bbox, second_bbox]) or first_bbox
                for key in ("member_numbers", "member_item_ids"):
                    values = first.setdefault(key, [])
                    if not isinstance(values, list):
                        values = []
                        first[key] = values
                    for value in second.get(key, []) if isinstance(second.get(key), list) else []:
                        if value not in values:
                            values.append(value)
                merged_ids = first.setdefault("merged_adjacent_fragment_group_ids", [])
                if isinstance(merged_ids, list):
                    for group_id in [second.get("group_id"), *second.get("merged_adjacent_fragment_group_ids", [])]:
                        value = str(group_id or "").strip()
                        if value and value not in merged_ids:
                            merged_ids.append(value)
                first["adjacent_fragment_merged"] = True
                first["adjacent_fragment_merge_policy"] = (
                    "same_column_strong_overlap_with_touching_vertical_spans"
                )
                merged.pop(second_index)
                changed = True
                break
            if changed:
                break
    return merged


def _tile_parent_fragment_merge_source(group: dict[str, Any]) -> bool:
    return str(group.get("source") or "") in {
        "stage2_primary_tile_card_parent_grouping",
        "stage2_primary_text_tile_card_parent_grouping",
    }


def _touching_fragments_share_content_column(first: dict[str, int], second: dict[str, int]) -> bool:
    if _horizontal_overlap_ratio(first, second) < 0.72:
        return False
    left_alignment_tolerance = max(12, int(min(first["w"], second["w"]) * 0.08))
    if abs(first["x"] - second["x"]) > left_alignment_tolerance:
        return False
    upper, lower = sorted((first, second), key=lambda bbox: (bbox["y"], bbox["x"]))
    vertical_gap = lower["y"] - (upper["y"] + upper["h"])
    scale = min(upper["h"], lower["h"])
    largest_touching_gap = max(8, int(scale * 0.15))
    largest_fragment_overlap = max(24, int(scale * 0.70))
    return -largest_fragment_overlap <= vertical_gap <= largest_touching_gap


def _repeated_text_column_parent_groups(
    *,
    region: dict[str, Any],
    numbered_items: list[dict[str, Any]],
    existing_groups: list[dict[str, Any]],
    start_index: int,
) -> list[dict[str, Any]]:
    region_bbox = _bbox(region.get("precise_bbox")) or _bbox(region.get("bbox"))
    if not region_bbox:
        return []
    existing_member_ids = {
        str(item_id)
        for group in existing_groups
        for item_id in group.get("member_item_ids", [])
        if str(item_id or "").strip()
    }
    text_items = [
        item
        for item in numbered_items
        if _looks_like_tile_text_child(item)
        and str(item.get("item_id") or "") not in existing_member_ids
        and _bbox(item.get("bbox"))
    ]
    rows: list[list[dict[str, Any]]] = []
    for item in sorted(text_items, key=lambda entry: (_bbox_top(entry), _bbox_left(entry))):
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            continue
        row = next(
            (
                candidate
                for candidate in rows
                if abs((_bbox(candidate[0].get("bbox")) or {})["y"] - bbox["y"]) <= 12
            ),
            None,
        )
        if row is None:
            rows.append([item])
        else:
            row.append(item)

    max_span = max(140, min(260, int(region_bbox["h"] * 0.28)))
    for anchors in rows:
        anchors = sorted(anchors, key=_bbox_left)
        if len(anchors) < 3:
            continue
        anchor_boxes = [_bbox(item.get("bbox")) for item in anchors]
        if any(not box for box in anchor_boxes):
            continue
        anchor_boxes = [box for box in anchor_boxes if box]
        centers = [box["x"] + box["w"] / 2 for box in anchor_boxes]
        if any(second - first < 100 for first, second in zip(centers, centers[1:])):
            continue
        top = min(box["y"] for box in anchor_boxes)
        bottom = top + max_span
        column_members: list[list[dict[str, Any]]] = []
        for index, anchor in enumerate(anchors):
            left = region_bbox["x"] if index == 0 else int((centers[index - 1] + centers[index]) / 2)
            right = (
                region_bbox["x"] + region_bbox["w"]
                if index == len(anchors) - 1
                else int((centers[index] + centers[index + 1]) / 2)
            )
            members = []
            for item in text_items:
                bbox = _bbox(item.get("bbox"))
                if not bbox or bbox["y"] < top - 3 or bbox["y"] + bbox["h"] > bottom:
                    continue
                center_x = bbox["x"] + bbox["w"] / 2
                if left <= center_x < right:
                    members.append(item)
            members.sort(key=lambda item: (_bbox_top(item), _bbox_left(item)))
            if anchor not in members:
                members.insert(0, anchor)
            column_members.append(members)
        if any(len(members) < 3 for members in column_members):
            continue
        if any(_has_repeated_text_column_section_break(members) for members in column_members):
            continue

        result: list[dict[str, Any]] = []
        for offset, members in enumerate(column_members):
            union = _bbox_union([item.get("bbox") for item in members])
            if not union:
                continue
            bbox = _clip_bbox(region_bbox, _expand_bbox(union, pad_x=20, pad_y=18))
            anchor = anchors[offset]
            result.append(
                {
                    "contract_version": "learn_stage2_subregion_group_v1",
                    "group_id": f"repeated_text_column_{start_index + offset}_{_slug(str(anchor.get('item_id') or ''))}",
                    "label": str(anchor.get("label") or f"text column {offset + 1}"),
                    "role": "tile_card_parent",
                    "bbox": bbox,
                    "member_numbers": [str(item.get("number") or "") for item in members],
                    "member_item_ids": [str(item.get("item_id") or "") for item in members],
                    "parent_child_policy": "repeated_aligned_heading_and_body_lines_form_one_text_column",
                    "bbox_policy": "union_column_text_children_with_review_padding",
                    "source": "stage2_repeated_text_column_parent_grouping",
                    "review_only": True,
                    "candidate_only": True,
                    "display_only": True,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                }
            )
        if len(result) >= 3:
            return result
    return []


def _has_repeated_text_column_section_break(members: list[dict[str, Any]]) -> bool:
    centers = sorted(
        _bbox_center_y_value(bbox)
        for item in members
        if (bbox := _bbox(item.get("bbox")))
    )
    gaps = [second - first for first, second in zip(centers, centers[1:]) if second > first]
    if len(gaps) < 2:
        return False
    baseline_gap = min(gaps)
    return max(gaps) >= max(60, baseline_gap * 2.2)


def _text_only_tile_card_parent_groups(
    *,
    region: dict[str, Any],
    numbered_items: list[dict[str, Any]],
    existing_groups: list[dict[str, Any]],
    start_index: int,
) -> list[dict[str, Any]]:
    region_bbox = _bbox(region.get("precise_bbox")) or _bbox(region.get("bbox"))
    if not region_bbox:
        return []
    existing_member_ids = {
        str(item_id)
        for group in existing_groups
        for item_id in group.get("member_item_ids", [])
        if str(item_id or "").strip()
    }
    existing_card_bboxes = [_bbox(group.get("bbox")) for group in existing_groups if group.get("role") == "tile_card_parent"]
    existing_card_bboxes = [bbox for bbox in existing_card_bboxes if bbox]
    text_items = [
        item
        for item in numbered_items
        if _looks_like_tile_text_child(item)
        and str(item.get("item_id") or "") not in existing_member_ids
        and not any(_bbox_center_inside(_bbox(item.get("bbox")), bbox) for bbox in existing_card_bboxes)
    ]
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    used_ids: set[str] = set()
    for title in sorted(text_items, key=lambda item: (_bbox_top(item), _bbox_left(item))):
        title_id = str(title.get("item_id") or "")
        if title_id in used_ids or not _looks_like_short_tile_title(title):
            continue
        title_bbox = _bbox(title.get("bbox"))
        if not title_bbox:
            continue
        best: tuple[float, dict[str, Any]] | None = None
        for subtitle in text_items:
            subtitle_id = str(subtitle.get("item_id") or "")
            if subtitle_id == title_id or subtitle_id in used_ids or not _looks_like_tile_subtitle(subtitle):
                continue
            subtitle_bbox = _bbox(subtitle.get("bbox"))
            if not subtitle_bbox:
                continue
            center_delta_y = _bbox_center_y_value(subtitle_bbox) - _bbox_center_y_value(title_bbox)
            if center_delta_y < 10 or center_delta_y > 42:
                continue
            left_delta = abs(subtitle_bbox["x"] - title_bbox["x"])
            if left_delta > max(14, int(max(title_bbox["w"], subtitle_bbox["w"]) * 0.18)):
                continue
            if subtitle_bbox["w"] < max(24, int(title_bbox["w"] * 0.65)):
                continue
            score = center_delta_y + left_delta * 0.5
            if best is None or score < best[0]:
                best = (score, subtitle)
        if best is None:
            continue
        subtitle = best[1]
        used_ids.add(title_id)
        used_ids.add(str(subtitle.get("item_id") or ""))
        pairs.append((title, subtitle))

    if len(pairs) < 2 and not _has_repeated_text_tile_column_or_row(pairs):
        return []

    groups: list[dict[str, Any]] = []
    for index, (title, subtitle) in enumerate(pairs, start=start_index):
        title_id = str(title.get("item_id") or "").strip()
        subtitle_id = str(subtitle.get("item_id") or "").strip()
        if not title_id or not subtitle_id:
            continue
        bbox = _text_tile_bbox(title, subtitle, region_bbox=region_bbox, existing_card_bboxes=existing_card_bboxes)
        if not bbox:
            continue
        groups.append(
            {
                "contract_version": "learn_stage2_subregion_group_v1",
                "group_id": f"text_tile_card_parent_{index}_{_slug(title_id)}",
                "label": str(title.get("label") or title.get("text") or f"text tile {index}"),
                "role": "tile_card_parent",
                "bbox": bbox,
                "member_numbers": [str(title.get("number") or ""), str(subtitle.get("number") or "")],
                "member_item_ids": [title_id, subtitle_id],
                "parent_child_policy": "paired_title_subtitle_text_tile_without_visible_card_bbox",
                "bbox_policy": "infer_tile_hit_area_from_aligned_title_subtitle_text_and_existing_tile_sizes",
                "source": "stage2_primary_text_tile_card_parent_grouping",
                "review_only": True,
                "candidate_only": True,
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    return groups


def _looks_like_short_tile_title(item: dict[str, Any]) -> bool:
    text = str(item.get("label") or item.get("text") or "").strip()
    if not text:
        return False
    if len(text) > 28:
        return False
    return not any(token in text.casefold() for token in ("http", "www.", "@"))


def _looks_like_tile_subtitle(item: dict[str, Any]) -> bool:
    text = str(item.get("label") or item.get("text") or "").strip()
    if not text:
        return False
    if len(text) > 64:
        return False
    return not any(token in text.casefold() for token in ("http", "www."))


def _has_repeated_text_tile_column_or_row(pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> bool:
    if len(pairs) < 2:
        return False
    title_bboxes = [_bbox(title.get("bbox")) for title, _subtitle in pairs]
    title_bboxes = [bbox for bbox in title_bboxes if bbox]
    for index, first in enumerate(title_bboxes):
        for second in title_bboxes[index + 1 :]:
            if abs(first["x"] - second["x"]) <= 28 or abs(first["y"] - second["y"]) <= 36:
                return True
    return False


def _text_tile_bbox(
    title: dict[str, Any],
    subtitle: dict[str, Any],
    *,
    region_bbox: dict[str, int],
    existing_card_bboxes: list[dict[str, int]],
) -> dict[str, int] | None:
    title_bbox = _bbox(title.get("bbox"))
    subtitle_bbox = _bbox(subtitle.get("bbox"))
    if not title_bbox or not subtitle_bbox:
        return None
    union = _bbox_union([title_bbox, subtitle_bbox])
    if not union:
        return None
    tile_widths = sorted(bbox["w"] for bbox in existing_card_bboxes if bbox.get("w"))
    inferred_width = tile_widths[len(tile_widths) // 2] if tile_widths else 176
    width = max(inferred_width, union["w"] + 42, 150)
    width = min(width, max(150, region_bbox["w"]))
    height = max(64, union["h"] + 34)
    height = min(height, max(64, region_bbox["h"]))
    x = union["x"] - 20
    y = union["y"] - 18
    x = max(region_bbox["x"], min(x, region_bbox["x"] + region_bbox["w"] - width))
    y = max(region_bbox["y"], min(y, region_bbox["y"] + region_bbox["h"] - height))
    return {"x": int(x), "y": int(y), "w": int(width), "h": int(height)}


def _looks_like_tile_card_parent_candidate(item: dict[str, Any]) -> bool:
    if not _looks_like_card_item(item):
        return False
    bbox = _bbox(item.get("bbox"))
    if not bbox:
        return False
    role = str(item.get("role") or "").casefold()
    item_type = str(item.get("item_type") or "").casefold()
    structure_text = " ".join(
        str(item.get(key) or "").casefold().replace("-", "_")
        for key in ("item_id", "element_id", "layout", "section_id", "source")
    )
    if "bottom_bar" in structure_text or "status_bar" in structure_text:
        return False
    if role in {"message_card", "message_card_content", "message_bubble", "image_message"}:
        return False
    if item_type == "section":
        return False
    if bbox["w"] < 72 or bbox["h"] < 42:
        return False
    if bbox["h"] > 160:
        return False
    return role in {"news_card", "recommendation_item", "content_card", "media_card"} or item_type == "card"


def _looks_like_tile_text_child(item: dict[str, Any]) -> bool:
    bbox = _bbox(item.get("bbox"))
    if not bbox:
        return False
    role = str(item.get("role") or "").casefold()
    item_type = str(item.get("item_type") or "").casefold()
    if _looks_like_card_item(item):
        return False
    if role in {"message_bubble", "message_card", "message_card_content", "image_message"}:
        return False
    action_text_evidence = (
        role in {"button", "control", "action"}
        or item_type in {"action", "action_uia", "button", "control"}
    ) and bbox["h"] <= 64
    return role in {"text", "label", "heading", "nav_text_action", "readable"} or item_type in {
        "text",
        "readable",
        "heading",
    } or action_text_evidence


def _bbox_center_inside(inner: dict[str, int] | None, outer: dict[str, int]) -> bool:
    if not inner:
        return False
    center_x = inner["x"] + inner["w"] / 2
    center_y = inner["y"] + inner["h"] / 2
    return (
        outer["x"] <= center_x <= outer["x"] + outer["w"]
        and outer["y"] <= center_y <= outer["y"] + outer["h"]
    )


def _input_toolbar_parent_groups(*, region: dict[str, Any], numbered_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    region_id = str(region.get("region_id") or "").casefold()
    if "top" in region_id or "header" in region_id or "sidebar" in region_id:
        return []
    region_bbox = _bbox(region.get("precise_bbox")) or _bbox(region.get("bbox"))
    if not region_bbox:
        return []
    send_items = [
        item
        for item in numbered_items
        if _bbox(item.get("bbox"))
        and _looks_like_send_button_item(item)
        and _is_near_region_bottom(_bbox(item.get("bbox")) or {}, region_bbox=region_bbox)
    ]
    if not send_items:
        return []
    groups: list[dict[str, Any]] = []
    assigned: set[str] = set()
    for index, send_item in enumerate(sorted(send_items, key=lambda item: (_bbox_top(item), _bbox_left(item))), start=1):
        send_bbox = _bbox(send_item.get("bbox"))
        if not send_bbox:
            continue
        send_center_y = send_bbox["y"] + send_bbox["h"] / 2
        toolbar_items: list[dict[str, Any]] = []
        for item in numbered_items:
            item_id = str(item.get("item_id") or "")
            if item_id in assigned:
                continue
            bbox = _bbox(item.get("bbox"))
            if not bbox:
                continue
            center_y = bbox["y"] + bbox["h"] / 2
            same_bottom_band = abs(center_y - send_center_y) <= max(42, send_bbox["h"] * 1.25)
            stacked_composer_band = (
                center_y <= send_center_y
                and send_center_y - center_y <= max(140, int(region_bbox["h"] * 0.24))
            )
            close_to_bottom = _is_near_region_bottom(bbox, region_bbox=region_bbox)
            if not (same_bottom_band or stacked_composer_band) or not close_to_bottom:
                continue
            if not (_looks_like_input_toolbar_child(item) or item is send_item):
                continue
            toolbar_items.append(item)
        if len(toolbar_items) < 2:
            continue
        bbox = _bbox_union([item.get("bbox") for item in toolbar_items])
        if not bbox:
            continue
        expanded = _clip_bbox(region_bbox, _expand_bbox(bbox, pad_x=8, pad_y=8))
        member_numbers = [str(item.get("number") or "") for item in toolbar_items]
        member_item_ids = [str(item.get("item_id") or "") for item in toolbar_items]
        assigned.update(member_item_ids)
        groups.append(
            {
                "contract_version": "learn_stage2_subregion_group_v1",
                "group_id": f"input_toolbar_region_{index}",
                "label": "bottom input toolbar",
                "role": "input_toolbar_region",
                "bbox": expanded,
                "member_numbers": member_numbers,
                "member_item_ids": member_item_ids,
                "source": "stage2_bottom_input_toolbar_synthesis",
                "parent_child_policy": "bottom_toolbar_controls_and_send_button_form_display_only_input_area",
                "bbox_policy": "bottom_input_toolbar_union_from_same_baseline_controls",
                "review_required": True,
                "action_candidate": False,
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    return groups


def _looks_like_send_button_item(item: dict[str, Any]) -> bool:
    label = str(item.get("label") or "").strip().casefold()
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    if not any(token in label for token in ("send", "发送")):
        return False
    return any(token in role for token in ("button", "text", "readable", "label"))


def _looks_like_input_toolbar_child(item: dict[str, Any]) -> bool:
    if _looks_like_send_button_item(item):
        return True
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    label = str(item.get("label") or "").strip()
    if any(token in role for token in ("input", "field", "edit", "toolbar", "icon", "button", "control", "text_button")):
        return True
    if len(label) <= 3 and label not in {"", "…"}:
        return True
    if any(token in label.casefold() for token in ("emoji", "image", "file", "mic", "voice", "表情", "图片", "文件", "语音")):
        return True
    return False


def _is_near_region_bottom(bbox: dict[str, int], *, region_bbox: dict[str, int]) -> bool:
    if not bbox or not region_bbox:
        return False
    region_bottom = region_bbox["y"] + region_bbox["h"]
    return bbox["y"] >= region_bbox["y"] + int(region_bbox["h"] * 0.68) or bbox["y"] + bbox["h"] >= region_bottom - 72


def _hero_panel_parent_groups(*, region: dict[str, Any], numbered_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not _is_primary_region_id(str(region.get("region_id") or "")):
        return []
    items = [item for item in numbered_items if _bbox(item.get("bbox"))]
    code_items = _hero_code_items(items)
    if len(code_items) < 3:
        return []
    code_bbox = _bbox_union([item.get("bbox") for item in code_items])
    if not code_bbox:
        return []
    text_items = _hero_text_items(items, code_bbox=code_bbox, excluded={id(item) for item in code_items})
    if len(text_items) < 2:
        return []
    text_bbox = _bbox_union([item.get("bbox") for item in text_items])
    hero_bbox = _bbox_union([code_bbox, text_bbox])
    if not text_bbox or not hero_bbox:
        return []
    code_group_id = "hero_code_panel_1"
    text_group_id = "hero_text_panel_1"
    return [
        {
            "contract_version": "learn_stage2_subregion_group_v1",
            "group_id": code_group_id,
            "label": "hero code panel",
            "role": "hero_code_panel",
            "bbox": code_bbox,
            "member_numbers": [str(item.get("number") or "") for item in code_items],
            "member_item_ids": [str(item.get("item_id") or "") for item in code_items],
            "source": "stage2_hero_code_text_panel_synthesis",
            "parent_child_policy": "code_like_text_lines_form_display_only_hero_code_panel",
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
        {
            "contract_version": "learn_stage2_subregion_group_v1",
            "group_id": text_group_id,
            "label": "hero text panel",
            "role": "hero_text_panel",
            "bbox": text_bbox,
            "member_numbers": [str(item.get("number") or "") for item in text_items],
            "member_item_ids": [str(item.get("item_id") or "") for item in text_items],
            "source": "stage2_hero_code_text_panel_synthesis",
            "parent_child_policy": "same_hero_band_heading_paragraph_cta_form_text_panel",
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
        {
            "contract_version": "learn_stage2_subregion_group_v1",
            "group_id": "hero_panel_1",
            "label": "hero panel",
            "role": "hero_panel",
            "bbox": hero_bbox,
            "child_group_ids": [code_group_id, text_group_id],
            "child_group_roles": ["hero_code_panel", "hero_text_panel"],
            "member_numbers": [
                *[str(item.get("number") or "") for item in code_items],
                *[str(item.get("number") or "") for item in text_items],
            ],
            "member_item_ids": [
                *[str(item.get("item_id") or "") for item in code_items],
                *[str(item.get("item_id") or "") for item in text_items],
            ],
            "source": "stage2_hero_code_text_panel_synthesis",
            "parent_child_policy": "code_panel_and_text_panel_form_display_only_hero_parent",
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
    ]


def _hero_code_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = [item for item in items if _looks_like_code_line(item)]
    if len(candidates) < 2:
        return []
    candidates.sort(key=lambda item: (_bbox_top(item), _bbox_left(item)))
    clusters: list[list[dict[str, Any]]] = []
    for item in candidates:
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            continue
        target: list[dict[str, Any]] | None = None
        for cluster in clusters:
            cluster_boxes = [_bbox(existing.get("bbox")) for existing in cluster]
            cluster_boxes = [box for box in cluster_boxes if box]
            if not cluster_boxes:
                continue
            avg_x = sum(box["x"] for box in cluster_boxes) / len(cluster_boxes)
            if abs(bbox["x"] - avg_x) <= 120:
                target = cluster
                break
        if target is None:
            clusters.append([item])
        else:
            target.append(item)
    clusters.sort(key=lambda cluster: (-len(cluster), _bbox_top(cluster[0]), _bbox_left(cluster[0])))
    if not clusters:
        return []
    cluster = _extend_code_cluster_with_output_lines(clusters[0], items)
    return cluster if len(cluster) >= 3 else []


def _extend_code_cluster_with_output_lines(
    code_cluster: list[dict[str, Any]],
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    code_boxes = [_bbox(item.get("bbox")) for item in code_cluster]
    code_boxes = [box for box in code_boxes if box]
    cluster_bbox = _bbox_union(code_boxes)
    if not cluster_bbox:
        return code_cluster
    output_candidates: list[dict[str, Any]] = []
    cluster_bottom = cluster_bbox["y"] + cluster_bbox["h"]
    for item in items:
        if item in code_cluster or _looks_like_code_line(item):
            continue
        role = str(item.get("role") or item.get("item_type") or "").casefold()
        if "text" not in role and role not in {"readable", "label"}:
            continue
        label = str(item.get("label") or "").strip()
        if not label or len(label) > 80:
            continue
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            continue
        y_gap = bbox["y"] - cluster_bottom
        same_left_column = abs(bbox["x"] - cluster_bbox["x"]) <= max(48, int(cluster_bbox["w"] * 0.18))
        horizontally_inside = bbox["x"] >= cluster_bbox["x"] - 12 and bbox["x"] <= cluster_bbox["x"] + cluster_bbox["w"] + 12
        if 0 <= y_gap <= 64 and (same_left_column or horizontally_inside):
            output_candidates.append(item)
    output_candidates.sort(key=lambda item: (_bbox_top(item), _bbox_left(item)))
    return [*code_cluster, *output_candidates[:2]]


def _looks_like_code_line(item: dict[str, Any]) -> bool:
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    if "text" not in role and role not in {"readable", "label"}:
        return False
    label = str(item.get("label") or "").strip()
    if not label:
        return False
    code_tokens = (">>>", "print(", "input(", "def ", "return ", " = ", "==", "{", "}", "console.", "</")
    return any(token in label for token in code_tokens)


def _hero_text_items(items: list[dict[str, Any]], *, code_bbox: dict[str, int], excluded: set[int]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    vertical_top = code_bbox["y"] - 60
    vertical_bottom = code_bbox["y"] + code_bbox["h"] + 110
    min_x = code_bbox["x"] + max(120, int(code_bbox["w"] * 0.55))
    for item in items:
        if id(item) in excluded or _looks_like_code_line(item) or _looks_like_card_item(item):
            continue
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            continue
        if bbox["x"] < min_x or bbox["y"] < vertical_top or bbox["y"] > vertical_bottom:
            continue
        label = str(item.get("label") or "").strip()
        if len(label) < 6:
            continue
        role = str(item.get("role") or item.get("item_type") or "").casefold()
        if not ("text" in role or "link" in role or "button" in role or "action" in role or role in {"label", "heading"}):
            continue
        candidates.append(item)
    candidates.sort(key=lambda item: (_bbox_top(item), _bbox_left(item)))
    return candidates


def _list_row_parent_groups(*, region: dict[str, Any], numbered_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not _is_primary_region_id(str(region.get("region_id") or "")):
        return []
    rows: list[dict[str, Any]] = []
    items = [item for item in numbered_items if _bbox(item.get("bbox"))]
    metadata_items = [item for item in items if _looks_like_list_metadata_item(item)]
    for metadata_item in sorted(metadata_items, key=lambda item: (_bbox_top(item), _bbox_left(item))):
        metadata_bbox = _bbox(metadata_item.get("bbox"))
        if not metadata_bbox:
            continue
        title = _nearest_list_row_title(metadata_item, items)
        if not title:
            continue
        title_bbox = _bbox(title.get("bbox"))
        row_bbox = _bbox_union([metadata_bbox, title_bbox])
        if not row_bbox or row_bbox["w"] < 120:
            continue
        rows.append({"metadata": metadata_item, "title": title, "bbox": row_bbox})
    clusters = _cluster_list_rows_by_metadata_column(rows)
    groups: list[dict[str, Any]] = []
    for cluster in clusters:
        if len(cluster) < 2:
            continue
        row_group_ids: list[str] = []
        row_member_numbers: list[str] = []
        row_member_item_ids: list[str] = []
        for row in cluster:
            group_id = f"list_row_{len([group for group in groups if group.get('role') == 'list_row']) + 1}"
            metadata_item = row["metadata"]
            title_item = row["title"]
            row_group_ids.append(group_id)
            row_member_numbers.extend(
                [str(metadata_item.get("number") or ""), str(title_item.get("number") or "")]
            )
            row_member_item_ids.extend(
                [str(metadata_item.get("item_id") or ""), str(title_item.get("item_id") or "")]
            )
            groups.append(
                {
                    "contract_version": "learn_stage2_subregion_group_v1",
                    "group_id": group_id,
                    "label": _list_row_label(metadata_item, title_item),
                    "role": "list_row",
                    "bbox": deepcopy(row["bbox"]),
                    "member_numbers": [
                        str(metadata_item.get("number") or ""),
                        str(title_item.get("number") or ""),
                    ],
                    "member_item_ids": [
                        str(metadata_item.get("item_id") or ""),
                        str(title_item.get("item_id") or ""),
                    ],
                    "source": "stage2_date_title_row_parent_synthesis",
                    "parent_child_policy": "short_metadata_column_binds_to_same_row_title",
                    "display_only": True,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                }
            )
        list_bbox = _bbox_union([row["bbox"] for row in cluster])
        if not list_bbox:
            continue
        groups.append(
            {
                "contract_version": "learn_stage2_subregion_group_v1",
                "group_id": f"list_group_{len([group for group in groups if group.get('role') == 'list_group']) + 1}",
                "label": "date/title list",
                "role": "list_group",
                "bbox": list_bbox,
                "child_group_ids": row_group_ids,
                "child_group_roles": ["list_row" for _ in row_group_ids],
                "member_numbers": [number for number in row_member_numbers if number],
                "member_item_ids": [item_id for item_id in row_member_item_ids if item_id],
                "source": "stage2_date_title_list_parent_synthesis",
                "parent_child_policy": "repeated_date_title_rows_form_list_group",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    region_bbox = _bbox(region.get("precise_bbox")) or _bbox(region.get("bbox"))
    return _normalize_parallel_list_group_widths(groups, region_bbox=region_bbox)


def _looks_like_list_metadata_item(item: dict[str, Any]) -> bool:
    bbox = _bbox(item.get("bbox"))
    if not bbox:
        return False
    label = str(item.get("label") or "").strip()
    if not label or len(label) > 24:
        return False
    return bool(re.fullmatch(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", label))


def _nearest_list_row_title(metadata_item: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any] | None:
    metadata_bbox = _bbox(metadata_item.get("bbox"))
    if not metadata_bbox:
        return None
    candidates: list[tuple[int, dict[str, Any]]] = []
    for item in items:
        if item is metadata_item or _looks_like_list_metadata_item(item):
            continue
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            continue
        label = str(item.get("label") or "").strip()
        if len(label) < 8 or _looks_like_card_item(item) or not _looks_like_list_title_item(item):
            continue
        gap = bbox["x"] - (metadata_bbox["x"] + metadata_bbox["w"])
        if gap < 6 or gap > 96:
            continue
        center_delta = abs(_bbox_center_y(item) - _bbox_center_y(metadata_item))
        if center_delta > max(16, (bbox["h"] + metadata_bbox["h"]) * 0.55):
            continue
        candidates.append((gap, item))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: (pair[0], _bbox_left(pair[1])))
    return candidates[0][1]


def _looks_like_list_title_item(item: dict[str, Any]) -> bool:
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    if any(token in role for token in ("button", "menu", "control", "input", "field")):
        return False
    return "text" in role or "link" in role or role in {"readable", "label", "heading"}


def _cluster_list_rows_by_metadata_column(rows: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    clusters: list[list[dict[str, Any]]] = []
    for row in sorted(rows, key=lambda item: (_bbox_left(item["metadata"]), _bbox_top(item["metadata"]))):
        metadata_bbox = _bbox(row["metadata"].get("bbox"))
        if not metadata_bbox:
            continue
        target: list[dict[str, Any]] | None = None
        for cluster in clusters:
            cluster_boxes = [_bbox(item["metadata"].get("bbox")) for item in cluster]
            cluster_boxes = [box for box in cluster_boxes if box]
            if not cluster_boxes:
                continue
            avg_x = sum(box["x"] for box in cluster_boxes) / len(cluster_boxes)
            if abs(metadata_bbox["x"] - avg_x) <= 48:
                target = cluster
                break
        if target is None:
            clusters.append([row])
        else:
            target.append(row)
    return clusters


def _list_row_label(metadata_item: dict[str, Any], title_item: dict[str, Any]) -> str:
    metadata = str(metadata_item.get("label") or "").strip()
    title = str(title_item.get("label") or "").strip()
    return f"{metadata} {title}".strip() or "list row"


def _topbar_control_parent_groups(*, region: dict[str, Any], numbered_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    region_id = str(region.get("region_id") or "")
    if _bar_region_kind(region_id) != "top_bar":
        return []
    region_bbox = _bbox(region.get("bbox")) or _bbox(region.get("precise_bbox"))
    if not region_bbox:
        return []
    controls = [
        item
        for item in numbered_items
        if _topbar_control_child_role(item)
        and (bbox := _bbox(item.get("bbox")))
        and _bbox_containment_ratio(bbox, region_bbox) >= 0.45
    ]
    if len(controls) < 3:
        return []
    rows = _cluster_topbar_controls_by_horizontal_band(controls, region_bbox=region_bbox)
    groups: list[dict[str, Any]] = []
    for row_index, row_controls in enumerate(rows, start=1):
        control_union = _bbox_union([item.get("bbox") for item in row_controls])
        if not control_union:
            continue
        strip_top = max(region_bbox["y"], control_union["y"] - 8)
        strip_bottom = min(region_bbox["y"] + region_bbox["h"], control_union["y"] + control_union["h"] + 8)
        strip_bbox = _clip_bbox(
            region_bbox,
            {
                "x": control_union["x"],
                "y": strip_top,
                "w": control_union["w"],
                "h": max(1, strip_bottom - strip_top),
            },
        )
        strip_group_id = f"topbar_control_strip_{row_index}"
        groups.append(
            {
                "contract_version": "learn_stage2_subregion_group_v1",
                "group_id": strip_group_id,
                "label": f"top/header control strip {row_index}",
                "role": "topbar_control_strip",
                "bbox": strip_bbox,
                "child_group_roles": _unique_roles(row_controls),
                "member_numbers": [str(item.get("number") or "") for item in row_controls],
                "member_item_ids": [str(item.get("item_id") or "") for item in row_controls],
                "parent_child_policy": "topbar_controls_share_display_only_strip_parent",
                "source": "stage2_direct_bar_parent_reconstruction",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
        groups.extend(
            _topbar_control_cluster_groups(
                controls=row_controls,
                region_bbox=region_bbox,
                strip_bbox=strip_bbox,
                parent_group_id=strip_group_id,
                group_id_prefix=f"topbar_control_cluster_{row_index}_",
            )
        )
        groups.extend(
            _topbar_sparse_center_semantic_groups(
                controls=row_controls,
                region_bbox=region_bbox,
                strip_bbox=strip_bbox,
                parent_group_id=strip_group_id,
                group_id_prefix=f"topbar_semantic_group_{row_index}_",
            )
        )
    return groups


def _topbar_control_cluster_groups(
    *,
    controls: list[dict[str, Any]],
    region_bbox: dict[str, int],
    strip_bbox: dict[str, int],
    parent_group_id: str = "topbar_control_strip_1",
    group_id_prefix: str = "topbar_control_cluster_",
) -> list[dict[str, Any]]:
    if len(controls) < 3:
        return []
    centers: list[float] = []
    for item in controls:
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            return []
        centers.append(bbox["x"] + bbox["w"] / 2)
    gaps = [centers[index + 1] - centers[index] for index in range(len(centers) - 1)]
    if not gaps:
        return []
    local_gaps = sorted(gap for gap in gaps if gap > 0)
    typical_gap_index = min(len(local_gaps) - 1, max(0, len(local_gaps) // 3)) if local_gaps else 0
    typical_gap = local_gaps[typical_gap_index] if local_gaps else 44
    split_gap = max(82, typical_gap * 1.85)
    clusters: list[list[dict[str, Any]]] = [[controls[0]]]
    for index, gap in enumerate(gaps, start=1):
        if gap > split_gap:
            clusters.append([])
        clusters[-1].append(controls[index])
    if len(clusters) <= 1:
        return []

    groups: list[dict[str, Any]] = []
    for index, cluster in enumerate(clusters, start=1):
        cluster_union = _bbox_union([item.get("bbox") for item in cluster])
        if not cluster_union:
            continue
        cluster_y = max(region_bbox["y"], min(cluster_union["y"] - 8, strip_bbox["y"]))
        cluster_bottom = min(
            region_bbox["y"] + region_bbox["h"],
            max(cluster_union["y"] + cluster_union["h"] + 8, strip_bbox["y"] + strip_bbox["h"]),
        )
        cluster_bbox = _clip_bbox(
            region_bbox,
            {
                "x": cluster_union["x"],
                "y": cluster_y,
                "w": cluster_union["w"],
                "h": max(1, cluster_bottom - cluster_y),
            },
        )
        groups.append(
            {
                "contract_version": "learn_stage2_subregion_group_v1",
                "group_id": f"{group_id_prefix}{index}",
                "label": f"top/header control cluster {index}",
                "role": "topbar_control_cluster",
                "bbox": cluster_bbox,
                "child_group_roles": _unique_roles(cluster),
                "member_numbers": [str(item.get("number") or "") for item in cluster],
                "member_item_ids": [str(item.get("item_id") or "") for item in cluster],
                "parent_group_id": parent_group_id,
                "parent_child_policy": "topbar_controls_split_by_horizontal_gap",
                "source": "stage2_direct_bar_parent_reconstruction",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    return groups


def _topbar_sparse_center_semantic_groups(
    *,
    controls: list[dict[str, Any]],
    region_bbox: dict[str, int],
    strip_bbox: dict[str, int],
    parent_group_id: str = "topbar_control_strip_1",
    group_id_prefix: str = "topbar_semantic_group_",
) -> list[dict[str, Any]]:
    if len(controls) < 5:
        return []
    ordered = [item for item in controls if _bbox(item.get("bbox"))]
    ordered.sort(key=lambda item: (_bbox_left(item), _bbox_top(item)))
    if len(ordered) < 5:
        return []

    region_left = region_bbox["x"]
    region_right = region_bbox["x"] + region_bbox["w"]
    center_band_left = region_left + region_bbox["w"] * 0.25
    center_band_right = region_left + region_bbox["w"] * 0.68
    centers = [(_bbox(item.get("bbox"))["x"] + _bbox(item.get("bbox"))["w"] / 2) for item in ordered]
    y_centers = [(_bbox(item.get("bbox"))["y"] + _bbox(item.get("bbox"))["h"] / 2) for item in ordered]

    groups: list[list[int]] = []
    current: list[int] = []
    for index, center_x in enumerate(centers):
        if not (center_band_left <= center_x <= center_band_right):
            if len(current) >= 2:
                groups.append(current)
            current = []
            continue
        if not current:
            previous_gap = center_x - centers[index - 1] if index > 0 else None
            if previous_gap is not None and previous_gap < 72:
                continue
            current = [index]
            continue
        gap = center_x - centers[current[-1]]
        y_delta = abs(y_centers[index] - y_centers[current[-1]])
        if 72 <= gap <= min(280, region_bbox["w"] * 0.28) and y_delta <= 18:
            current.append(index)
        else:
            if len(current) >= 2:
                groups.append(current)
            current = [index]
    if len(current) >= 2:
        groups.append(current)

    semantic_groups: list[dict[str, Any]] = []
    used_item_ids: set[str] = set()
    for group_indexes in groups:
        members = [ordered[index] for index in group_indexes]
        if not any(_topbar_semantic_status_member(item) for item in members):
            continue
        member_ids = {str(item.get("item_id") or "") for item in members}
        if used_item_ids & member_ids:
            continue
        raw_union = _bbox_union([item.get("bbox") for item in members])
        if not raw_union:
            continue
        first_index = group_indexes[0]
        last_index = group_indexes[-1]
        left_boundary = (
            (centers[first_index - 1] + centers[first_index]) / 2
            if first_index > 0
            else raw_union["x"] - max(48, raw_union["w"] * 0.25)
        )
        right_boundary = (
            (centers[last_index] + centers[last_index + 1]) / 2
            if last_index < len(centers) - 1
            else raw_union["x"] + raw_union["w"] + max(48, raw_union["w"] * 0.25)
        )
        min_width = max(raw_union["w"] + 96, int(region_bbox["w"] * 0.18))
        proposed_left = min(left_boundary, raw_union["x"] - 24)
        proposed_right = max(right_boundary, raw_union["x"] + raw_union["w"] + 24)
        if proposed_right - proposed_left < min_width:
            center = raw_union["x"] + raw_union["w"] / 2
            proposed_left = center - min_width / 2
            proposed_right = center + min_width / 2
        group_bbox = _clip_bbox(
            region_bbox,
            {
                "x": int(round(max(region_left, proposed_left))),
                "y": strip_bbox["y"],
                "w": int(round(min(region_right, proposed_right) - max(region_left, proposed_left))),
                "h": strip_bbox["h"],
            },
        )
        if group_bbox["w"] <= raw_union["w"]:
            continue
        used_item_ids.update(member_ids)
        semantic_groups.append(
            {
                "contract_version": "learn_stage2_subregion_group_v1",
                "group_id": f"{group_id_prefix}{len(semantic_groups) + 1}",
                "label": f"top/header semantic status group {len(semantic_groups) + 1}",
                "role": "topbar_semantic_group",
                "bbox": group_bbox,
                "child_group_roles": _unique_roles(members),
                "member_numbers": [str(item.get("number") or "") for item in members],
                "member_item_ids": [str(item.get("item_id") or "") for item in members],
                "parent_group_id": parent_group_id,
                "parent_child_policy": "sparse_center_topbar_controls_share_display_only_semantic_parent",
                "bbox_policy": "topbar_sparse_aligned_controls_expand_to_status_parent",
                "source": "stage2_direct_bar_parent_reconstruction",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    return semantic_groups


def _topbar_semantic_status_member(item: dict[str, Any]) -> bool:
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    item_type = str(item.get("item_type") or "").casefold()
    combined = f"{role} {item_type}"
    if any(token in combined for token in ("nav_text_action", "text_action", "text_link")):
        return False
    if role in {"text", "label"} or item_type in {"text", "label"}:
        return False
    return any(token in combined for token in ("icon", "button", "control"))


def _topbar_control_child_role(item: dict[str, Any]) -> str:
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    if any(token in role for token in ("control", "button", "icon", "nav_text_action", "text_action")):
        return role
    label = str(item.get("label") or "").strip()
    return "text" if label and len(label) <= 40 else ""


def _notice_parent_groups(*, region: dict[str, Any], numbered_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    used_numbers: set[str] = set()
    region_family = _stage1_region_family(region)
    for anchor in sorted(numbered_items, key=lambda item: (_bbox_top(item), _bbox_left(item))):
        if not _looks_like_notice_anchor(anchor):
            continue
        anchor_role = str(anchor.get("role") or anchor.get("item_type") or "").casefold()
        if region_family == "main_content" and anchor_role not in {
            "alert",
            "announcement",
            "banner",
            "notice",
            "notice_item",
            "pinned_notice",
        }:
            continue
        anchor_number = str(anchor.get("number") or "")
        if anchor_number in used_numbers:
            continue
        anchor_bbox = _bbox(anchor.get("bbox"))
        if not anchor_bbox:
            continue
        members = [anchor]
        for candidate in sorted(numbered_items, key=lambda item: (_bbox_top(item), _bbox_left(item))):
            candidate_number = str(candidate.get("number") or "")
            if candidate_number == anchor_number or candidate_number in used_numbers:
                continue
            candidate_bbox = _bbox(candidate.get("bbox"))
            if not candidate_bbox:
                continue
            if not _near_notice_anchor(candidate_bbox, anchor_bbox):
                continue
            if _looks_like_message_fragment(candidate):
                continue
            if _looks_like_member_list_row(candidate):
                continue
            if _looks_like_cross_notice_member_nav_item(candidate):
                continue
            members.append(candidate)
        if len(members) < 2:
            continue
        bbox = _bbox_union([item.get("bbox") for item in members])
        if not bbox:
            continue
        used_numbers.update(str(item.get("number") or "") for item in members)
        groups.append(
            {
                "contract_version": "learn_stage2_subregion_group_v1",
                "group_id": f"notice_region_{len(groups) + 1}",
                "label": str(anchor.get("label") or "notice"),
                "role": "notice_region",
                "bbox": bbox,
                "anchor_number": anchor_number,
                "anchor_item_id": str(anchor.get("item_id") or ""),
                "child_group_roles": _unique_roles(members),
                "member_numbers": [str(item.get("number") or "") for item in members],
                "member_item_ids": [str(item.get("item_id") or "") for item in members],
                "parent_child_policy": "notice_heading_binds_to_nearby_body_lines",
                "source": "stage2_semantic_parent_reconstruction",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    if not groups:
        fallback = _sidebar_top_text_block_notice_group(region=region, numbered_items=numbered_items)
        if fallback:
            groups.append(fallback)
    return groups


def _sidebar_top_text_block_notice_group(
    *,
    region: dict[str, Any],
    numbered_items: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if _bar_region_kind(str(region.get("region_id") or "")) != "right_sidebar":
        return None
    ordered = [
        item
        for item in sorted(numbered_items, key=lambda entry: (_bbox_top(entry), _bbox_left(entry)))
        if _looks_like_sidebar_text_block_item(item)
    ]
    if len(ordered) < 3:
        return None
    members: list[dict[str, Any]] = []
    previous_bbox: dict[str, int] | None = None
    first_top: int | None = None
    for item in ordered:
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            continue
        if first_top is None:
            first_top = bbox["y"]
        if previous_bbox is not None:
            vertical_gap = bbox["y"] - (previous_bbox["y"] + previous_bbox["h"])
            if vertical_gap > 72:
                break
        if members and _looks_like_member_list_row(item) and first_top is not None and bbox["y"] > first_top + 120:
            break
        members.append(item)
        previous_bbox = bbox
    if len(members) < 3:
        return None
    bbox = _bbox_union([item.get("bbox") for item in members])
    if not bbox or bbox["h"] < 72:
        return None
    return {
        "contract_version": "learn_stage2_subregion_group_v1",
        "group_id": "notice_region_1",
        "label": str(members[0].get("label") or "sidebar text block"),
        "role": "notice_region",
        "bbox": bbox,
        "anchor_number": str(members[0].get("number") or ""),
        "anchor_item_id": str(members[0].get("item_id") or ""),
        "child_group_roles": _unique_roles(members),
        "member_numbers": [str(item.get("number") or "") for item in members],
        "member_item_ids": [str(item.get("item_id") or "") for item in members],
        "parent_child_policy": "sidebar_top_text_block_before_list_binds_to_notice_region",
        "source": "stage2_semantic_parent_reconstruction",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _message_parent_groups(*, region: dict[str, Any], numbered_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    region_id = str(region.get("region_id") or "")
    if "sidebar" in region_id.casefold() or "top" in region_id.casefold() or "header" in region_id.casefold():
        return []
    explicit_candidates = [item for item in numbered_items if _looks_like_message_fragment(item)]
    if not explicit_candidates:
        return []
    anchor_candidates = [item for item in explicit_candidates if _looks_like_chat_surface_anchor(item)]
    column_seed = anchor_candidates or explicit_candidates
    message_column_min = min((_bbox_left(item) for item in column_seed if _bbox(item.get("bbox"))), default=0) - 48
    candidates = [
        item
        for item in numbered_items
        if _bbox_left(item) >= message_column_min and _message_child_role(item, chat_context=True)
    ]
    if not candidates:
        return []
    clusters: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_bbox: dict[str, int] | None = None
    for item in sorted(candidates, key=lambda entry: (_bbox_top(entry), _bbox_left(entry))):
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            continue
        if not current or current_bbox is None:
            current = [item]
            current_bbox = bbox
            continue
        gap = bbox["y"] - (current_bbox["y"] + current_bbox["h"])
        role = _message_child_role(item, chat_context=True)
        current_roles = {_message_child_role(member, chat_context=True) for member in current}
        same_message_column = _horizontal_overlap_ratio(bbox, current_bbox) >= 0.08 or abs(bbox["x"] - current_bbox["x"]) <= 96
        has_new_start_anchor = _has_new_message_start_anchor_before_item(
            item=item,
            item_bbox=bbox,
            current=current,
            numbered_items=numbered_items,
        )
        should_split_standalone_message = (
            gap > 36
            and role in {"image_message", "message_bubble", "message_card"}
            and bool(current_roles & {"image_message", "message_bubble", "message_card"})
        )
        if gap <= 72 and same_message_column and not should_split_standalone_message and not has_new_start_anchor:
            current.append(item)
            current_bbox = _bbox_union([current_bbox, bbox])
        else:
            if _message_cluster_is_parent(current):
                clusters.append(current)
            current = [item]
            current_bbox = bbox
    if _message_cluster_is_parent(current):
        clusters.append(current)
    clusters = _absorb_message_context_fragments(clusters, numbered_items)
    clusters.extend(
        _context_only_short_message_clusters(
            numbered_items,
            assigned_numbers={str(item.get("number") or "") for cluster in clusters for item in cluster},
            message_column_min=message_column_min,
        )
    )

    groups: list[dict[str, Any]] = []
    for cluster in clusters:
        raw_bbox = _bbox_union([item.get("bbox") for item in cluster])
        bbox, bbox_policy = _message_parent_display_bbox(cluster, region_bbox=(_bbox(region.get("bbox")) or _bbox(region.get("precise_bbox"))))
        if not bbox:
            continue
        label = _message_parent_label(cluster)
        context_only_short_message = _is_context_only_short_message_cluster(cluster)
        context_item_ids = [
            str(item.get("item_id") or "")
            for item in cluster
            if str(item.get("item_id") or "") and _message_context_role(item)
        ]
        core_item_ids = [
            str(item.get("item_id") or "")
            for item in cluster
            if str(item.get("item_id") or "")
            and _message_child_role(item, chat_context=True) in {"image_message", "message_bubble", "message_card"}
        ]
        child_item_ids = [
            str(item.get("item_id") or "")
            for item in cluster
            if str(item.get("item_id") or "") and str(item.get("item_id") or "") not in context_item_ids
        ]
        group = {
            "contract_version": "learn_stage2_subregion_group_v1",
            "group_id": f"message_item_{len(groups) + 1}",
            "label": label,
            "role": "message_item",
            "bbox": bbox,
            "child_group_roles": _unique_roles(cluster),
            "member_numbers": [str(item.get("number") or "") for item in cluster],
            "member_item_ids": [str(item.get("item_id") or "") for item in cluster],
            "child_item_ids": child_item_ids,
            "context_item_ids": context_item_ids,
            "core_item_ids": core_item_ids,
            "message_child_breakdown": {
                "contract_version": "learn_message_child_breakdown_v1",
                "core_item_count": len(core_item_ids),
                "context_item_count": len(context_item_ids),
                "display_child_count": len(child_item_ids),
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            },
            "parent_child_policy": (
                "message_context_only_short_message_parent"
                if context_only_short_message
                else "message_core_absorbs_nearby_context_fragments"
            ),
            "source": "stage2_semantic_parent_reconstruction",
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
        if context_only_short_message:
            group["bbox_policy"] = "message_context_only_short_message_needs_review"
            group["review_required"] = True
            group["action_candidate"] = False
        if raw_bbox and bbox_policy:
            group["bbox_policy"] = bbox_policy
            group["raw_bbox_before_policy"] = raw_bbox
            if bbox_policy == "message_item_image_background_expanded_needs_review":
                group["review_required"] = True
                group["action_candidate"] = False
        groups.append(group)
    return groups


def _message_parent_display_bbox(
    cluster: list[dict[str, Any]],
    *,
    region_bbox: dict[str, int] | None,
) -> tuple[dict[str, int] | None, str | None]:
    raw_bbox = _bbox_union([item.get("bbox") for item in cluster])
    if not raw_bbox:
        return None, None
    core_items = [
        item
        for item in cluster
        if _message_child_role(item, chat_context=True) in {"image_message", "message_bubble", "message_card"}
    ]
    core_roles = {_message_child_role(item, chat_context=True) for item in core_items}
    if core_roles == {"image_message"}:
        core_bbox = _bbox_union([item.get("bbox") for item in core_items])
        if not core_bbox:
            return raw_bbox, None
        expanded_left = max(0, min(raw_bbox["x"], core_bbox["x"] - 56))
        expanded_top = max(0, min(raw_bbox["y"], core_bbox["y"] - 16))
        expanded_right = max(raw_bbox["x"] + raw_bbox["w"], core_bbox["x"] + core_bbox["w"] + 28)
        expanded_bottom = max(raw_bbox["y"] + raw_bbox["h"], core_bbox["y"] + core_bbox["h"] + 20)
        expanded = {
            "x": expanded_left,
            "y": expanded_top,
            "w": max(1, expanded_right - expanded_left),
            "h": max(1, expanded_bottom - expanded_top),
        }
        if region_bbox:
            expanded = _clip_bbox(region_bbox, expanded)
        if expanded != raw_bbox:
            return expanded, "message_item_image_background_expanded_needs_review"
        return raw_bbox, None
    if core_roles != {"message_bubble"}:
        return raw_bbox, None
    core_bbox = _bbox_union([item.get("bbox") for item in core_items])
    if not core_bbox:
        return raw_bbox, None
    has_expanded_bubble_child = any(
        str(item.get("bbox_policy") or "") == "message_bubble_background_expanded_needs_review"
        for item in core_items
    )
    if has_expanded_bubble_child and _message_context_top_gap(raw_bbox, core_bbox) >= 18:
        display_bbox = _message_core_display_bbox(core_bbox, region_bbox=region_bbox)
        return display_bbox, "message_item_core_display_bbox_context_externalized"
    if core_bbox["h"] > 36 and raw_bbox["h"] >= 96 and not has_expanded_bubble_child:
        return raw_bbox, None
    expanded_right = max(raw_bbox["x"] + raw_bbox["w"], core_bbox["x"] + core_bbox["w"] + 40)
    bubble_bottom_padding = 24 if has_expanded_bubble_child else 54
    expanded_bottom = max(raw_bbox["y"] + raw_bbox["h"], core_bbox["y"] + max(72, core_bbox["h"] + bubble_bottom_padding))
    expanded = {
        "x": max(0, min(raw_bbox["x"], core_bbox["x"] - 12)),
        "y": raw_bbox["y"],
        "w": max(1, expanded_right - max(0, min(raw_bbox["x"], core_bbox["x"] - 12))),
        "h": max(1, expanded_bottom - raw_bbox["y"]),
    }
    if region_bbox:
        expanded = _clip_bbox(region_bbox, expanded)
    if expanded == raw_bbox:
        return raw_bbox, None
    return expanded, "message_item_text_bubble_background_expanded"


def _message_context_top_gap(raw_bbox: dict[str, int], core_bbox: dict[str, int]) -> int:
    return max(0, core_bbox["y"] - raw_bbox["y"])


def _message_core_display_bbox(
    core_bbox: dict[str, int],
    *,
    region_bbox: dict[str, int] | None,
) -> dict[str, int]:
    display_bbox = {
        "x": max(0, core_bbox["x"] - 10),
        "y": max(0, core_bbox["y"] - 6),
        "w": core_bbox["w"] + 20,
        "h": core_bbox["h"] + 12,
    }
    if region_bbox:
        display_bbox = _clip_bbox(region_bbox, display_bbox)
    return display_bbox


def _clip_message_cards_at_following_start_anchors(
    numbered_items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    clipped_items: list[dict[str, Any]] = []
    clipped_count = 0
    for item in numbered_items:
        bbox = _bbox(item.get("bbox"))
        if not bbox or _message_child_role(item, chat_context=True) != "message_card":
            clipped_items.append(item)
            continue
        clip_y: int | None = None
        for anchor in numbered_items:
            if anchor is item or not _looks_like_message_start_anchor(anchor):
                continue
            anchor_bbox = _bbox(anchor.get("bbox"))
            if not anchor_bbox:
                continue
            if anchor_bbox["y"] <= bbox["y"] + 32:
                continue
            if anchor_bbox["y"] >= bbox["y"] + bbox["h"]:
                continue
            if not _message_context_belongs_to_core(anchor_bbox, bbox):
                continue
            if not _has_following_message_core_for_anchor(anchor_bbox, item, numbered_items):
                continue
            candidate_clip_y = max(bbox["y"] + 24, anchor_bbox["y"] - 8)
            clip_y = candidate_clip_y if clip_y is None else min(clip_y, candidate_clip_y)
        if clip_y is None or clip_y >= bbox["y"] + bbox["h"]:
            clipped_items.append(item)
            continue
        updated = deepcopy(item)
        updated["bbox"] = {**bbox, "h": max(1, clip_y - bbox["y"])}
        updated["original_bbox_before_message_card_clip"] = bbox
        updated["bbox_policy"] = "message_card_clipped_before_following_start_anchor"
        updated["review_required"] = True
        updated["action_candidate"] = False
        updated["execute_binding_enabled"] = False
        updated["artifact_is_authorization"] = False
        clipped_items.append(updated)
        clipped_count += 1
    return clipped_items, {
        "contract_version": "learn_stage2_message_card_boundary_clip_v1",
        "applied": clipped_count > 0,
        "clipped_count": clipped_count,
        "policy": "oversized_message_card_stops_before_following_message_start_anchor",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _has_following_message_core_for_anchor(
    anchor_bbox: dict[str, int],
    owner_item: dict[str, Any],
    numbered_items: list[dict[str, Any]],
) -> bool:
    anchor_bottom = anchor_bbox["y"] + anchor_bbox["h"]
    for candidate in numbered_items:
        if candidate is owner_item:
            continue
        candidate_bbox = _bbox(candidate.get("bbox"))
        if not candidate_bbox:
            continue
        if candidate_bbox["y"] < anchor_bottom - 12:
            continue
        if candidate_bbox["y"] > anchor_bottom + 128:
            continue
        if _message_child_role(candidate, chat_context=True) not in {"image_message", "message_bubble", "message_card"}:
            continue
        if _message_context_belongs_to_core(anchor_bbox, candidate_bbox):
            return True
    return False


def _has_new_message_start_anchor_before_item(
    *,
    item: dict[str, Any],
    item_bbox: dict[str, int],
    current: list[dict[str, Any]],
    numbered_items: list[dict[str, Any]],
) -> bool:
    role = _message_child_role(item, chat_context=True)
    if role not in {"image_message", "message_bubble", "message_card"}:
        return False
    current_core_boxes = [
        bbox
        for member in current
        if _message_child_role(member, chat_context=True) in {"image_message", "message_bubble", "message_card"}
        for bbox in [_bbox(member.get("bbox"))]
        if bbox
    ]
    current_core_bbox = _bbox_union(current_core_boxes)
    if not current_core_bbox:
        return False
    item_top = int(item_bbox.get("y", 0))
    for context in numbered_items:
        if not _looks_like_message_start_anchor(context):
            continue
        context_bbox = _bbox(context.get("bbox"))
        if not context_bbox:
            continue
        context_bottom = context_bbox["y"] + context_bbox["h"]
        if context_bbox["y"] <= current_core_bbox["y"] + 32:
            continue
        if context_bottom > item_top + 18:
            continue
        if not _message_context_belongs_to_core(context_bbox, item_bbox):
            continue
        return True
    return False


def _absorb_message_context_fragments(
    clusters: list[list[dict[str, Any]]],
    numbered_items: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    assigned_numbers = {str(item.get("number") or "") for cluster in clusters for item in cluster}
    expanded_clusters: list[list[dict[str, Any]]] = [list(cluster) for cluster in clusters]
    cluster_core_bboxes = [_message_cluster_core_bbox(cluster) for cluster in clusters]
    for item in numbered_items:
        number = str(item.get("number") or "")
        if not number or number in assigned_numbers:
            continue
        if not _looks_like_message_context_fragment(item):
            continue
        item_bbox = _bbox(item.get("bbox"))
        if not item_bbox:
            continue
        best_index: int | None = None
        best_score: tuple[float, float, float] | None = None
        for index, core_bbox in enumerate(cluster_core_bboxes):
            if not core_bbox:
                continue
            score = _message_context_match_score(item_bbox, core_bbox)
            if score is None:
                continue
            if best_score is None or score < best_score:
                best_score = score
                best_index = index
        if best_index is None:
            continue
        expanded_clusters[best_index].append(item)
        assigned_numbers.add(number)
    normalized_clusters: list[list[dict[str, Any]]] = []
    for members in expanded_clusters:
        members.sort(key=lambda entry: (_bbox_top(entry), _bbox_left(entry)))
        normalized = _trim_message_cluster_to_last_start_anchor(members)
        if _message_cluster_is_parent(normalized):
            normalized_clusters.append(normalized)
    return normalized_clusters


def _context_only_short_message_clusters(
    numbered_items: list[dict[str, Any]],
    *,
    assigned_numbers: set[str],
    message_column_min: float,
) -> list[list[dict[str, Any]]]:
    contexts = [
        item
        for item in numbered_items
        if str(item.get("number") or "") not in assigned_numbers
        and _bbox_left(item) >= message_column_min
        and _looks_like_message_context_fragment(item)
    ]
    timestamps = [item for item in contexts if _looks_like_timestamp_label(str(item.get("label") or "").strip())]
    result: list[list[dict[str, Any]]] = []
    used_numbers: set[str] = set()
    for timestamp in sorted(timestamps, key=lambda entry: (_bbox_top(entry), _bbox_left(entry))):
        timestamp_number = str(timestamp.get("number") or "")
        if timestamp_number in used_numbers:
            continue
        timestamp_bbox = _bbox(timestamp.get("bbox"))
        if not timestamp_bbox:
            continue
        timestamp_bottom = timestamp_bbox["y"] + timestamp_bbox["h"]
        best_context: dict[str, Any] | None = None
        best_score: tuple[int, float] | None = None
        for context in contexts:
            context_number = str(context.get("number") or "")
            if context is timestamp or context_number in used_numbers:
                continue
            if not _looks_like_sender_or_level_context(context):
                continue
            context_bbox = _bbox(context.get("bbox"))
            if not context_bbox:
                continue
            vertical_gap = context_bbox["y"] - timestamp_bottom
            if vertical_gap < -8 or vertical_gap > 84:
                continue
            if not _message_context_pair_is_near(timestamp_bbox, context_bbox):
                continue
            score = (max(0, vertical_gap), abs((context_bbox["x"] + context_bbox["w"] / 2) - (timestamp_bbox["x"] + timestamp_bbox["w"] / 2)))
            if best_score is None or score < best_score:
                best_score = score
                best_context = context
        if best_context is None:
            continue
        result.append(sorted([timestamp, best_context], key=lambda entry: (_bbox_top(entry), _bbox_left(entry))))
        used_numbers.add(timestamp_number)
        used_numbers.add(str(best_context.get("number") or ""))
    return result


def _message_context_pair_is_near(first_bbox: dict[str, int], second_bbox: dict[str, int]) -> bool:
    if _horizontal_overlap_ratio(first_bbox, second_bbox) >= 0.04:
        return True
    first_center = first_bbox["x"] + first_bbox["w"] / 2
    second_center = second_bbox["x"] + second_bbox["w"] / 2
    return abs(first_center - second_center) <= 180


def _looks_like_sender_or_level_context(item: dict[str, Any]) -> bool:
    text = _semantic_item_text(item)
    if any(token in text for token in ("sender", "avatar", "from_user", "用户头像", "发送者", "头像")):
        return True
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    if not any(token in role for token in ("text", "readable", "label")):
        return False
    return any(token in text for token in ("lv", "level", "钻石", "王者", "黄金", "白银"))


def _is_context_only_short_message_cluster(cluster: list[dict[str, Any]]) -> bool:
    if len(cluster) < 2:
        return False
    if any(_message_child_role(item, chat_context=True) in {"image_message", "message_bubble", "message_card"} for item in cluster):
        return False
    has_timestamp = any(_looks_like_timestamp_label(str(item.get("label") or "").strip()) for item in cluster)
    has_sender_or_level = any(_looks_like_sender_or_level_context(item) for item in cluster)
    return has_timestamp and has_sender_or_level


def _trim_message_cluster_to_last_start_anchor(members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    start_anchors = [
        item
        for item in members
        if _looks_like_timestamp_label(str(item.get("label") or "").strip())
    ]
    if len(start_anchors) <= 1:
        return members
    start_anchors.sort(key=lambda entry: (_bbox_top(entry), _bbox_left(entry)))
    last_anchor = start_anchors[-1]
    last_bbox = _bbox(last_anchor.get("bbox"))
    if not last_bbox:
        return members
    trimmed = [
        item
        for item in members
        if (bbox := _bbox(item.get("bbox"))) and bbox["y"] >= last_bbox["y"] - 4
    ]
    if not any(_message_child_role(item, chat_context=True) in {"image_message", "message_bubble", "message_card"} for item in trimmed):
        return members
    return trimmed


def _message_cluster_core_bbox(cluster: list[dict[str, Any]]) -> dict[str, int] | None:
    core_bboxes = [
        bbox
        for item in cluster
        if _message_child_role(item, chat_context=True) in {"image_message", "message_bubble", "message_card"}
        for bbox in [_bbox(item.get("bbox"))]
        if bbox
    ]
    return _bbox_union(core_bboxes)


def _message_context_match_score(context_bbox: dict[str, int], core_bbox: dict[str, int]) -> tuple[float, float, float] | None:
    if not _message_context_belongs_to_core(context_bbox, core_bbox):
        return None
    context_bottom = context_bbox["y"] + context_bbox["h"]
    core_top = core_bbox["y"]
    following_gap = core_top - context_bottom
    context_center_x = context_bbox["x"] + context_bbox["w"] / 2
    core_center_x = core_bbox["x"] + core_bbox["w"] / 2
    horizontal_distance = abs(context_center_x - core_center_x)
    if -12 <= following_gap <= 96:
        return (0.0, abs(float(following_gap)), float(horizontal_distance))
    context_center_y = context_bbox["y"] + context_bbox["h"] / 2
    core_center_y = core_bbox["y"] + core_bbox["h"] / 2
    return (1.0, abs(float(context_center_y - core_center_y)), float(horizontal_distance))


def _looks_like_message_context_fragment(item: dict[str, Any]) -> bool:
    if _looks_like_chat_surface_anchor(item):
        return False
    if _message_child_role(item, chat_context=True):
        return False
    bbox = _bbox(item.get("bbox"))
    if not bbox:
        return False
    text = _semantic_item_text(item)
    label = str(item.get("label") or "").strip()
    if _looks_like_timestamp_label(label):
        return True
    if any(token in text for token in ("sender", "avatar", "from_user", "用户头像", "发送者", "头像")):
        return True
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    if any(token in role for token in ("text", "readable", "label")):
        if any(token in text for token in ("lv", "level", "钻石", "王者", "黄金", "白银")):
            return True
        return bbox["w"] <= 140 and bbox["h"] <= 28 and len(label) <= 18
    return False


def _message_context_belongs_to_core(context_bbox: dict[str, int], core_bbox: dict[str, int]) -> bool:
    if context_bbox["x"] < core_bbox["x"] - 72:
        return False
    horizontal_near = _horizontal_overlap_ratio(context_bbox, core_bbox) >= 0.08 or abs(context_bbox["x"] - core_bbox["x"]) <= 140
    if not horizontal_near:
        return False
    context_bottom = context_bbox["y"] + context_bbox["h"]
    core_top = core_bbox["y"]
    core_bottom = core_bbox["y"] + core_bbox["h"]
    above_gap = core_top - context_bottom
    if -12 <= above_gap <= 128:
        return True
    center_y = context_bbox["y"] + context_bbox["h"] / 2
    if core_top - 24 <= center_y <= core_bottom + 24:
        return True
    return False


def _looks_like_message_start_anchor(item: dict[str, Any]) -> bool:
    if _looks_like_chat_surface_anchor(item):
        return False
    bbox = _bbox(item.get("bbox"))
    if not bbox:
        return False
    label = str(item.get("label") or "").strip()
    if _looks_like_timestamp_label(label):
        return True
    text = _semantic_item_text(item)
    if any(token in text for token in ("sender", "avatar", "from_user", "用户头像", "发送者", "头像")):
        return True
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    if any(token in role for token in ("text", "readable", "label")):
        return any(token in text for token in ("lv", "level", "钻石", "王者", "黄金", "白银"))
    return False


def _member_list_parent_groups(*, region: dict[str, Any], numbered_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if _bar_region_kind(str(region.get("region_id") or "")) != "right_sidebar":
        return []
    candidates: list[dict[str, Any]] = []
    for item in sorted(numbered_items, key=lambda entry: (_bbox_top(entry), _bbox_left(entry))):
        child_proxies = _member_list_child_proxies(item)
        if child_proxies:
            candidates.extend(child_proxies)
            item_id = str(item.get("item_id") or "")
            role = str(item.get("role") or "")
            if item_id.startswith("merged_") or "review_region" in role:
                continue
            if not (_looks_like_member_list_row(item) or _looks_like_member_list_header(item)):
                continue
        header_proxy = _member_list_header_child_proxy(item)
        if header_proxy:
            candidates.append(header_proxy)
            continue
        if _looks_like_member_list_row(item) or _looks_like_member_list_header(item):
            candidates.append(item)
            continue
        if _looks_like_member_list_continuation_row(item):
            candidates.append(item)
    ordered = sorted(candidates, key=lambda entry: (_bbox_top(entry), _bbox_left(entry), str(entry.get("item_id") or "")))
    if sum(_member_evidence_count(item) for item in ordered) < 3:
        return []
    groups: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_bbox: dict[str, int] | None = None
    for item in ordered:
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            continue
        item_evidence = _member_evidence_count(item)
        current_evidence = sum(_member_evidence_count(entry) for entry in current)
        if not current and item_evidence <= 0:
            continue
        if not current or current_bbox is None:
            current = [item]
            current_bbox = bbox
            continue
        gap = bbox["y"] - (current_bbox["y"] + current_bbox["h"])
        same_list_column = _horizontal_overlap_ratio(bbox, current_bbox) >= 0.12 or abs(bbox["x"] - current_bbox["x"]) <= 96
        can_continue_member_list = item_evidence > 0 or current_evidence >= 2
        if -8 <= gap <= 76 and same_list_column and can_continue_member_list:
            current.append(item)
            current_bbox = _bbox_union([current_bbox, bbox])
        else:
            if _member_cluster_is_parent(current):
                group = _member_list_group(current, len(groups) + 1)
                if group:
                    groups.append(group)
            if item_evidence > 0:
                current = [item]
                current_bbox = bbox
            else:
                current = []
                current_bbox = None
    if _member_cluster_is_parent(current):
        group = _member_list_group(current, len(groups) + 1)
        if group:
            groups.append(group)
    return groups


def _conversation_row_container_groups(
    *,
    region: dict[str, Any],
    numbered_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """优先使用重复的完整列表行容器，避免把标题和预览文字拆成窄行。"""
    region_bbox = _bbox(region.get("precise_bbox")) or _bbox(region.get("bbox"))
    if not region_bbox:
        return []
    container_roles = {"dataitem", "listitem", "list_item", "conversation_row", "chat_row", "message_bubble"}
    seed_roles = {"dataitem", "listitem", "list_item", "conversation_row", "chat_row"}

    def role_of(item: dict[str, Any]) -> str:
        return str(item.get("role") or item.get("item_type") or "").strip().casefold().replace(" ", "_")

    def usable_container(item: dict[str, Any]) -> bool:
        bbox = _bbox(item.get("bbox"))
        role = role_of(item)
        if not bbox or role not in container_roles:
            return False
        if bbox["h"] < 36 or bbox["h"] > 128 or bbox["w"] < 120:
            return False
        semantic_text = _semantic_item_text(item)
        return not any(token in semantic_text for token in ("filter", "search", "筛选", "搜索"))

    seeds = [item for item in numbered_items if usable_container(item) and role_of(item) in seed_roles]
    if len(seeds) < 2:
        return []

    def similar_geometry(left: dict[str, Any], right: dict[str, Any]) -> bool:
        left_bbox = _bbox(left.get("bbox"))
        right_bbox = _bbox(right.get("bbox"))
        if not left_bbox or not right_bbox:
            return False
        return (
            abs(left_bbox["x"] - right_bbox["x"]) <= 14
            and min(left_bbox["w"], right_bbox["w"]) / max(left_bbox["w"], right_bbox["w"]) >= 0.82
            and min(left_bbox["h"], right_bbox["h"]) / max(left_bbox["h"], right_bbox["h"]) >= 0.62
        )

    clusters = [[candidate for candidate in seeds if similar_geometry(seed, candidate)] for seed in seeds]
    cluster = max(
        clusters,
        key=lambda values: (
            len(values),
            sum((_bbox(item.get("bbox")) or {"w": 0})["w"] for item in values),
        ),
    )
    if len(cluster) < 2:
        return []
    reference = max(cluster, key=lambda item: (_bbox(item.get("bbox")) or {"w": 0})["w"])
    containers = [item for item in numbered_items if usable_container(item) and similar_geometry(reference, item)]
    containers.sort(key=lambda item: (_bbox_top(item), _bbox_left(item)))

    deduped: list[dict[str, Any]] = []
    role_priority = {"dataitem": 4, "listitem": 4, "list_item": 4, "conversation_row": 4, "chat_row": 4, "message_bubble": 2}
    for item in containers:
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            continue
        duplicate_index = next(
            (
                index
                for index, existing in enumerate(deduped)
                if abs(_bbox_top(existing) - bbox["y"]) <= max(8, int(bbox["h"] * 0.3))
            ),
            None,
        )
        if duplicate_index is None:
            deduped.append(item)
            continue
        existing = deduped[duplicate_index]
        existing_bbox = _bbox(existing.get("bbox")) or {"w": 0}
        item_rank = (role_priority.get(role_of(item), 0), bbox["w"])
        existing_rank = (role_priority.get(role_of(existing), 0), existing_bbox["w"])
        if item_rank > existing_rank:
            deduped[duplicate_index] = item

    if len(deduped) < 2:
        return []
    container_ids = {str(item.get("item_id") or "") for item in containers}
    groups: list[dict[str, Any]] = []
    for container in deduped:
        bbox = _bbox(container.get("bbox"))
        if not bbox:
            continue
        children = [
            item
            for item in numbered_items
            if str(item.get("item_id") or "") not in container_ids
            and (child_bbox := _bbox(item.get("bbox"))) is not None
            and (
                _bbox_containment_ratio(child_bbox, bbox) >= 0.78
                or (
                    bbox["x"] <= child_bbox["x"] + child_bbox["w"] / 2 <= bbox["x"] + bbox["w"]
                    and bbox["y"] <= child_bbox["y"] + child_bbox["h"] / 2 <= bbox["y"] + bbox["h"]
                )
            )
        ]
        members = [container, *sorted(children, key=lambda item: (_bbox_top(item), _bbox_left(item)))]
        groups.append(
            {
                "contract_version": "learn_stage2_subregion_group_v1",
                "group_id": f"conversation_row_{len(groups) + 1}",
                "label": _conversation_row_label(members),
                "role": "conversation_row",
                "bbox": bbox,
                "child_group_roles": _unique_roles(members),
                "member_numbers": [str(item.get("number") or "") for item in members],
                "member_item_ids": [str(item.get("item_id") or "") for item in members],
                "parent_child_policy": "repeated_full_row_container_owns_internal_evidence",
                "adjacent_fragment_merged": True,
                "source": "stage2_semantic_row_container_reconstruction",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    return groups


def _conversation_row_parent_groups(
    *,
    region: dict[str, Any],
    numbered_items: list[dict[str, Any]],
    treat_primary_as_conversation_list: bool = False,
) -> list[dict[str, Any]]:
    if not _is_primary_region_id(str(region.get("region_id") or "")):
        return []
    is_conversation_list = treat_primary_as_conversation_list or _is_conversation_list_stage2_region(region)
    if is_conversation_list:
        container_groups = _conversation_row_container_groups(region=region, numbered_items=numbered_items)
        if container_groups:
            return container_groups
        candidates = [
            item
            for item in sorted(numbered_items, key=lambda entry: (_bbox_top(entry), _bbox_left(entry)))
            if _bbox(item.get("bbox"))
            and _looks_like_conversation_row_fragment(item)
            and (
                "text" in str(item.get("role") or "").casefold()
                or str(item.get("item_type") or "").casefold() in {"text", "readable"}
            )
        ]
    else:
        explicit_candidates = [item for item in numbered_items if _looks_like_message_fragment(item)]
        anchor_candidates = [item for item in explicit_candidates if _looks_like_chat_surface_anchor(item)]
        if not anchor_candidates:
            return []
        message_column_min = min((_bbox_left(item) for item in anchor_candidates if _bbox(item.get("bbox"))), default=0) - 48
        candidates = [
            item
            for item in sorted(numbered_items, key=lambda entry: (_bbox_top(entry), _bbox_left(entry)))
            if _bbox(item.get("bbox"))
            and _bbox_left(item) < message_column_min
            and _looks_like_conversation_row_fragment(item)
            and (
                "text" in str(item.get("role") or "").casefold()
                or str(item.get("item_type") or "").casefold() in {"text", "readable"}
            )
        ]
    if len(candidates) < 3:
        return []
    rows: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_top: int | None = None
    top_values = sorted((_bbox(item.get("bbox")) or {"y": 0})["y"] for item in candidates)
    positive_steps = sorted(
        second - first
        for first, second in zip(top_values, top_values[1:])
        if second - first > 0
    )
    lower_steps = positive_steps[: max(1, (len(positive_steps) + 1) // 2)]
    typical_inner_step = lower_steps[len(lower_steps) // 2] if lower_steps else 18
    same_row_line_step = max(20, min(30, int(round(typical_inner_step * 1.2))))
    for item in candidates:
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            continue
        if not current or current_top is None:
            current = [item]
            current_top = bbox["y"]
            continue
        same_row = bbox["y"] - current_top <= same_row_line_step
        if same_row:
            current.append(item)
            current_top = bbox["y"]
        else:
            if len(current) >= 2:
                rows.append(current)
            current = [item]
            current_top = bbox["y"]
    if len(current) >= 2:
        rows.append(current)
    if rows and is_conversation_list:
        used_item_ids = {
            str(item.get("item_id") or "")
            for row in rows
            for item in row
        }
        anchor_lefts = sorted(_bbox_left(row[0]) for row in rows if row)
        anchor_left = anchor_lefts[len(anchor_lefts) // 2]
        region_bbox = _bbox(region.get("precise_bbox")) or _bbox(region.get("bbox")) or {"w": 400}
        singleton_tolerance = max(24, min(36, int(region_bbox["w"] * 0.08)))
        rows.extend(
            [item]
            for item in candidates
            if str(item.get("item_id") or "") not in used_item_ids
            and abs(_bbox_left(item) - anchor_left) <= singleton_tolerance
        )
        rows.sort(key=lambda row: (_bbox_top(row[0]), _bbox_left(row[0])))
    groups: list[dict[str, Any]] = []
    for row in rows:
        if _conversation_row_is_section_heading(row):
            continue
        bbox = _bbox_union([item.get("bbox") for item in row])
        if not bbox:
            continue
        groups.append(
            {
                "contract_version": "learn_stage2_subregion_group_v1",
                "group_id": f"conversation_row_{len(groups) + 1}",
                "label": _conversation_row_label(row),
                "role": "conversation_row",
                "bbox": bbox,
                "child_group_roles": _unique_roles(row),
                "member_numbers": [str(item.get("number") or "") for item in row],
                "member_item_ids": [str(item.get("item_id") or "") for item in row],
                "parent_child_policy": "conversation_list_fragments_bind_to_row_parent",
                "source": "stage2_semantic_parent_reconstruction",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    return groups


def _is_conversation_list_stage2_region(region: dict[str, Any]) -> bool:
    value = " ".join(
        str(region.get(key) or "").casefold()
        for key in ("region_id", "role", "label")
    )
    return "conversation_list" in value or "conversation/list" in value


def _near_notice_anchor(candidate_bbox: dict[str, int], anchor_bbox: dict[str, int]) -> bool:
    vertical_gap = candidate_bbox["y"] - (anchor_bbox["y"] + anchor_bbox["h"])
    if vertical_gap < -12 or vertical_gap > 180:
        return False
    if _horizontal_overlap_ratio(candidate_bbox, anchor_bbox) >= 0.08:
        return True
    return abs(candidate_bbox["x"] - anchor_bbox["x"]) <= 96


def _looks_like_notice_anchor(item: dict[str, Any]) -> bool:
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    if role in {
        "card",
        "tile_card",
        "media_card",
        "message_card",
        "recommendation_item",
        "news_card",
    }:
        return False
    text = _semantic_item_text(item)
    return any(token in text for token in ("notice", "announcement", "pinned", "公告", "通知", "群公告"))


def _looks_like_sidebar_text_block_item(item: dict[str, Any]) -> bool:
    bbox = _bbox(item.get("bbox"))
    if not bbox:
        return False
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    if not any(token in role for token in ("text", "readable", "label", "nav_item", "notice", "card")):
        return False
    label = str(item.get("label") or "").strip()
    if not label:
        return False
    return bbox["h"] <= 96


def _looks_like_member_list_row(item: dict[str, Any]) -> bool:
    text = _semantic_item_text(item)
    return any(token in text for token in ("member", "admin", "owner", "成员", "管理员", "群主"))


def _looks_like_member_list_header(item: dict[str, Any]) -> bool:
    text = _semantic_item_text(item)
    return any(token in text for token in ("members", "member list", "群聊成员", "成员列表"))


def _looks_like_member_list_continuation_row(item: dict[str, Any]) -> bool:
    bbox = _bbox(item.get("bbox"))
    if not bbox or bbox["h"] > 64:
        return False
    label = str(item.get("label") or item.get("text") or "").strip()
    if not label:
        return False
    role = " ".join(str(item.get(key) or "") for key in ("role", "item_type")).casefold()
    if not any(token in role for token in ("nav_item", "readable", "text", "label", "member")):
        return False
    if _looks_like_notice_anchor(item) or _looks_like_message_fragment(item):
        return False
    return True


def _member_list_header_child_proxy(item: dict[str, Any]) -> dict[str, Any] | None:
    bbox = _bbox(item.get("bbox"))
    if not bbox or bbox["h"] <= 96:
        return None
    children = item.get("children") if isinstance(item.get("children"), list) else []
    for child in children:
        if not isinstance(child, dict):
            continue
        child_bbox = _bbox(child.get("bbox"))
        if not child_bbox or not _looks_like_member_list_header(child):
            continue
        child_label = str(child.get("label") or child.get("text") or item.get("label") or "member list").strip()
        child_id = str(child.get("child_id") or child.get("item_id") or "")
        parent_item_id = str(item.get("item_id") or "")
        proxy_id = child_id or f"{parent_item_id}::member_list_header"
        return _member_list_proxy_from_child(item, child, role="member_list_header", index=1) or {
            "contract_version": "learn_stage2_numbered_item_v1",
            "number": f"{str(item.get('number') or '')}.h1",
            "item_id": proxy_id,
            "label": child_label,
            "role": "member_list_header",
            "bbox": child_bbox,
            "click_point": {},
            "children": [],
            "review_only": True,
            "stage": "stage2_region_numbering",
            "source": "stage2_member_list_header_child_extraction",
            "bbox_policy": "member_list_header_child_bbox_from_oversized_boundary_container",
            "derived_from_item_id": parent_item_id,
            "derived_from_item_number": str(item.get("number") or ""),
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
    return None


def _member_list_child_proxies(item: dict[str, Any]) -> list[dict[str, Any]]:
    item_id = str(item.get("item_id") or "")
    role = str(item.get("role") or "")
    children = item.get("children") if isinstance(item.get("children"), list) else []
    if not children:
        return []
    is_merged_or_review_container = item_id.startswith("merged_") or "review_region" in role
    if not is_merged_or_review_container:
        return []
    proxies: list[dict[str, Any]] = []
    for index, child in enumerate(children, start=1):
        if not isinstance(child, dict):
            continue
        candidate_children = [child]
        child_bbox = _bbox(child.get("bbox"))
        if child_bbox and child_bbox["h"] > 96 and isinstance(child.get("children"), list):
            candidate_children = [entry for entry in child.get("children", []) if isinstance(entry, dict)]
        for candidate_index, candidate_child in enumerate(candidate_children, start=index):
            candidate_bbox = _bbox(candidate_child.get("bbox"))
            if not candidate_bbox or candidate_bbox["h"] > 96:
                continue
            child_role = (
                "member_list_header" if _looks_like_member_list_header(candidate_child) else "member_list_row"
            )
            if child_role == "member_list_row" and not _looks_like_member_list_row(candidate_child):
                continue
            proxy = _member_list_proxy_from_child(item, candidate_child, role=child_role, index=candidate_index)
            if proxy:
                proxies.append(proxy)
    return sorted(proxies, key=lambda entry: (_bbox_top(entry), _bbox_left(entry)))


def _member_list_proxy_from_child(
    item: dict[str, Any],
    child: dict[str, Any],
    *,
    role: str,
    index: int,
) -> dict[str, Any] | None:
    child_bbox = _bbox(child.get("bbox"))
    if not child_bbox:
        return None
    child_label = str(child.get("label") or child.get("text") or item.get("label") or "member list").strip()
    child_id = str(child.get("child_id") or child.get("item_id") or "")
    parent_item_id = str(item.get("item_id") or "")
    suffix = "h" if role == "member_list_header" else "r"
    proxy_id = child_id or f"{parent_item_id}::member_list_{suffix}{index}"
    return {
        "contract_version": "learn_stage2_numbered_item_v1",
        "number": f"{str(item.get('number') or '')}.{suffix}{index}",
        "item_id": proxy_id,
        "label": child_label,
        "role": role,
        "bbox": child_bbox,
        "click_point": {},
        "children": [],
        "review_only": True,
        "stage": "stage2_region_numbering",
        "source": "stage2_member_list_child_extraction",
        "bbox_policy": "member_list_child_bbox_from_oversized_sidebar_container",
        "derived_from_item_id": parent_item_id,
        "derived_from_item_number": str(item.get("number") or ""),
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _looks_like_message_fragment(item: dict[str, Any]) -> bool:
    text = _semantic_item_text(item)
    if _looks_like_system_message_notice(item):
        return False
    return any(
        token in text
        for token in (
            "message",
            "chat",
            "bubble",
            "avatar",
            "sender",
            "conversation",
            "image_message",
            "消息",
            "聊天",
            "气泡",
            "头像",
            "图片消息",
        )
    )


def _looks_like_chat_surface_anchor(item: dict[str, Any]) -> bool:
    text = _semantic_item_text(item)
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    if any(token in role for token in ("content_area", "main_content", "section", "region", "container")) and any(
        token in text for token in ("chat", "message", "conversation", "聊天", "消息", "会话")
    ):
        return True
    return any(
        token in text
        for token in (
            "chat area",
            "chat history",
            "conversation history",
            "conversation area",
            "chat record",
            "message area",
            "message thread",
            "sender",
            "avatar",
            "聊天区",
            "群聊的聊天记录",
            "聊天记录",
            "消息记录",
            "头像",
        )
    )


def _looks_like_image_message_fragment(item: dict[str, Any], *, chat_context: bool) -> bool:
    text = _semantic_item_text(item)
    bbox = _bbox(item.get("bbox"))
    if not bbox:
        return False
    if any(token in text for token in ("avatar", "sender_avatar", "用户头像", "发送者头像", "头像")):
        return False
    explicit = any(token in text for token in ("image_message", "sticker", "emoji", "图片消息", "表情消息"))
    if explicit:
        return True
    if not chat_context:
        return False
    if not any(token in text for token in ("image", "photo", "screenshot", "sticker", "emoji", "图片", "照片", "截图", "表情")):
        return False
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    if any(token in role for token in ("media_card", "news_card", "card")):
        return False
    return bbox["w"] >= 40 and bbox["h"] >= 40


def _looks_like_text_bubble_fragment(item: dict[str, Any], *, chat_context: bool) -> bool:
    if not chat_context:
        return False
    text = _semantic_item_text(item)
    bbox = _bbox(item.get("bbox"))
    if not bbox:
        return False
    if _looks_like_system_message_notice(item):
        return False
    if any(token in text for token in ("notice", "announcement", "member", "owner", "admin", "公告", "成员", "群主", "管理员")):
        return False
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    if not any(token in role for token in ("text", "readable", "label", "message", "bubble")):
        return False
    label = str(item.get("label") or "").strip()
    if bbox["h"] <= 28 and any(token in text for token in ("lv", "level", "钻石", "王者", "黄金", "白银")):
        return False
    return len(label) >= 12 or (bbox["w"] >= 140 and bbox["h"] >= 36)


def _looks_like_message_card_fragment(item: dict[str, Any], *, chat_context: bool) -> bool:
    if not chat_context:
        return False
    text = _semantic_item_text(item)
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    return any(token in role for token in ("news_card", "card")) and any(
        token in text for token in ("chat", "message", "聊天", "消息", "图片")
    )


def _message_child_role(item: dict[str, Any], *, chat_context: bool) -> str:
    original_role = str(item.get("role") or item.get("item_type") or "").strip()
    role_lower = original_role.casefold()
    if _looks_like_layout_adjustment_control(item):
        return original_role or "control"
    if "message_card_content" in role_lower:
        return ""
    if any(token in role_lower for token in ("content_area", "main_content", "section", "region", "container")):
        return ""
    if _looks_like_system_message_notice(item):
        return ""
    if _looks_like_image_message_fragment(item, chat_context=chat_context):
        return "image_message"
    if _looks_like_message_card_fragment(item, chat_context=chat_context):
        return "message_card"
    if _looks_like_text_bubble_fragment(item, chat_context=chat_context):
        return "message_bubble"
    if _looks_like_message_fragment(item):
        if "avatar" in _semantic_item_text(item):
            return original_role or "message_fragment"
        if any(token in _semantic_item_text(item) for token in ("message", "chat", "bubble", "消息", "聊天", "气泡")):
            return "message_bubble"
        return original_role or "message_fragment"
    return ""


def _looks_like_layout_adjustment_control(item: dict[str, Any]) -> bool:
    role = str(item.get("role") or item.get("item_type") or "").casefold().replace(" ", "_")
    if role not in {"button", "control", "separator", "splitter", "thumb", "scrollbar"}:
        return False
    text = _semantic_item_text(item)
    bbox = _bbox(item.get("bbox"))
    explicit_resize = any(token in text for token in ("resize", "splitter", "panel_size", "adjust_size")) or (
        "\u8c03\u6574" in text and "\u5927\u5c0f" in text
    )
    extreme_aspect_ratio = bool(
        bbox
        and (
            bbox["h"] >= max(120, bbox["w"] * 6)
            or bbox["w"] >= max(120, bbox["h"] * 6)
        )
    )
    return explicit_resize or extreme_aspect_ratio


def _looks_like_system_message_notice(item: dict[str, Any]) -> bool:
    label = str(item.get("label") or item.get("text") or "").strip().casefold()
    if not label:
        return False
    return any(
        token in label
        for token in (
            "new message",
            "new messages",
            "unread message",
            "unread messages",
            "条新消息",
            "新消息",
            "未读消息",
        )
    )


def _message_cluster_is_parent(items: list[dict[str, Any]]) -> bool:
    if len(items) >= 2:
        return True
    if not items:
        return False
    if _looks_like_chat_surface_anchor(items[0]):
        return False
    return _message_child_role(items[0], chat_context=True) in {"image_message", "message_bubble", "message_card"}


def _member_cluster_is_parent(items: list[dict[str, Any]]) -> bool:
    member_evidence_count = sum(_member_evidence_count(item) for item in items)
    if len(items) < 2 and member_evidence_count < 3:
        return False
    return member_evidence_count >= 2


def _member_evidence_count(item: dict[str, Any]) -> int:
    count = 2 if _looks_like_member_list_header(item) else (1 if _looks_like_member_list_row(item) else 0)
    children = item.get("children") if isinstance(item.get("children"), list) else []
    for child in children:
        if isinstance(child, dict) and _looks_like_member_list_row(child):
            count += 1
    return count


def _member_list_group(items: list[dict[str, Any]], index: int) -> dict[str, Any] | None:
    bbox = _bbox_union([item.get("bbox") for item in items])
    if not bbox:
        return None
    return {
        "contract_version": "learn_stage2_subregion_group_v1",
        "group_id": f"member_list_region_{index}",
        "label": str(items[0].get("label") or "member list"),
        "role": "member_list_region",
        "bbox": bbox,
        "child_group_roles": _unique_roles(items),
        "member_numbers": [str(item.get("number") or "") for item in items],
        "member_item_ids": _expanded_member_item_ids(items),
        "parent_child_policy": "adjacent_member_rows_bind_to_member_list_region",
        "source": "stage2_semantic_parent_reconstruction",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _expanded_member_item_ids(items: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for item in items:
        item_id = str(item.get("item_id") or "")
        children = item.get("children") if isinstance(item.get("children"), list) else []
        is_merged_review_container = bool(children) and (
            item_id.startswith("merged_") or "review_region" in str(item.get("role") or "")
        )
        if item_id and item_id not in ids and not is_merged_review_container:
            ids.append(item_id)
        for child in children:
            if not isinstance(child, dict):
                continue
            child_id = str(child.get("child_id") or child.get("item_id") or "")
            if child_id and child_id not in ids:
                ids.append(child_id)
    return ids


def _looks_like_conversation_row_fragment(item: dict[str, Any]) -> bool:
    bbox = _bbox(item.get("bbox"))
    if not bbox:
        return False
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    label = str(item.get("label") or "").strip()
    if not label:
        return False
    if any(token in role for token in ("text", "readable", "label", "news_card", "card")):
        return bbox["h"] <= 96
    return False


def _conversation_row_label(items: list[dict[str, Any]]) -> str:
    for item in items:
        label = str(item.get("label") or "").strip()
        if label and not _looks_like_timestamp_label(label):
            return label
    return str(items[0].get("label") or "conversation row") if items else "conversation row"


def _conversation_row_is_section_heading(items: list[dict[str, Any]]) -> bool:
    labels = [str(item.get("label") or "").strip() for item in items]
    labels = [label for label in labels if label]
    if not labels:
        return False
    section_pattern = re.compile(
        r"^(?:在线好友|离线好友|在线|离线|好友|游戏中|recent|online friends?|offline friends?|friends?)"
        r"(?:\s*[\(\[（]\s*\d+\s*[\)\]）])?$",
        re.IGNORECASE,
    )
    disclosure_labels = {"↓", "↑", "▼", "▲", "⌄", "⌃", ">", "<", "›", "‹", "v", "^"}
    has_section_label = any(section_pattern.fullmatch(label) for label in labels)
    return has_section_label and all(
        section_pattern.fullmatch(label) or label.casefold() in disclosure_labels
        for label in labels
    )


def _looks_like_timestamp_label(label: str) -> bool:
    stripped = label.strip()
    return bool(re.fullmatch(r"\d{1,2}:\d{2}", stripped) or re.fullmatch(r"\d{4}/\d{1,2}/\d{1,2}", stripped))


def _message_context_role(item: dict[str, Any]) -> str:
    label = str(item.get("label") or "").strip()
    if _looks_like_timestamp_label(label):
        return "timestamp"
    text = _semantic_item_text(item)
    if any(token in text for token in ("sender", "from_user", "发送者")):
        return "sender"
    if "avatar" in text or "头像" in text:
        return "avatar"
    if _looks_like_sender_or_level_context(item):
        return "sender_or_level"
    return ""


def _bbox_center_y_value(bbox: dict[str, int]) -> float:
    return float(bbox.get("y", 0)) + float(bbox.get("h", 0)) / 2


def _semantic_item_text(item: dict[str, Any]) -> str:
    values = [
        item.get("role"),
        item.get("item_type"),
        item.get("label"),
        item.get("source"),
    ]
    children = item.get("children") if isinstance(item.get("children"), list) else []
    for child in children:
        if isinstance(child, dict):
            values.extend([child.get("role"), child.get("item_type"), child.get("label"), child.get("source")])
    return " ".join(str(value or "") for value in values).casefold()


def _unique_roles(items: list[dict[str, Any]]) -> list[str]:
    roles: list[str] = []
    for item in items:
        role = str(item.get("role") or item.get("item_type") or "").strip()
        if role and role not in roles:
            roles.append(role)
    return roles


def _message_parent_label(items: list[dict[str, Any]]) -> str:
    for item in items:
        role = str(item.get("role") or "").casefold()
        label = str(item.get("label") or "").strip()
        if label and ("message" in role or "chat" in role):
            return label
    for item in items:
        label = str(item.get("label") or "").strip()
        if label:
            return label
    return "message item"


def _apply_semantic_group_child_roles(
    numbered_items: list[dict[str, Any]],
    subregion_groups: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    notice_numbers: set[str] = set()
    group_by_notice_number: dict[str, str] = {}
    notice_group_bboxes: list[dict[str, Any]] = []
    message_numbers: set[str] = set()
    group_by_message_number: dict[str, str] = {}
    for group in subregion_groups:
        group_id = str(group.get("group_id") or "")
        role = str(group.get("role") or "")
        if role == "notice_region":
            group_bbox = _bbox(group.get("bbox"))
            if group_bbox:
                notice_group_bboxes.append({"group_id": group_id, "bbox": group_bbox})
            for number in group.get("member_numbers", []) if isinstance(group.get("member_numbers"), list) else []:
                number_text = str(number or "")
                if not number_text:
                    continue
                notice_numbers.add(number_text)
                group_by_notice_number[number_text] = group_id
        if role == "message_item":
            for number in group.get("member_numbers", []) if isinstance(group.get("member_numbers"), list) else []:
                number_text = str(number or "")
                if not number_text:
                    continue
                message_numbers.add(number_text)
                group_by_message_number[number_text] = group_id

    if not notice_numbers and not message_numbers:
        return numbered_items, subregion_groups

    rewritten_items: list[dict[str, Any]] = []
    role_by_number: dict[str, str] = {}
    for item in numbered_items:
        number = str(item.get("number") or "")
        if number in notice_numbers:
            copied = deepcopy(item)
            original_role = str(copied.get("role") or "")
            if original_role == "nav_item":
                copied["role"] = "notice_item"
                copied["original_role"] = original_role
                copied["semantic_parent_group_id"] = group_by_notice_number.get(number, "")
                copied["action_candidate"] = False
                copied["review_only"] = True
                copied["display_only"] = True
                copied["execute_binding_enabled"] = False
                copied["artifact_is_authorization"] = False
                copied["bbox_policy"] = "notice_region_child_not_navigation_action"
            rewritten_items.append(copied)
            role_by_number[number] = str(copied.get("role") or "")
        elif number in message_numbers:
            copied = deepcopy(item)
            original_role = str(copied.get("role") or "")
            message_role = _message_child_role(copied, chat_context=True)
            copied["semantic_parent_group_id"] = group_by_message_number.get(number, "")
            context_role = _message_context_role(copied)
            if context_role:
                copied["message_context_role"] = context_role
                copied["action_candidate"] = False
                copied["review_only"] = True
                copied["display_only"] = True
                copied["execute_binding_enabled"] = False
                copied["artifact_is_authorization"] = False
                copied.setdefault("role_policy", "message_context_child_from_parent_group")
            if message_role and message_role != original_role:
                copied["role"] = message_role
                copied["original_role"] = original_role
                copied["action_candidate"] = False
                copied["review_only"] = True
                copied["display_only"] = True
                copied["execute_binding_enabled"] = False
                copied["artifact_is_authorization"] = False
                copied.setdefault("role_policy", "message_parent_child_role_from_chat_context")
                if not str(copied.get("bbox_policy") or "").strip():
                    copied["bbox_policy"] = "message_parent_child_role_from_chat_context"
            rewritten_items.append(copied)
            role_by_number[number] = str(copied.get("role") or "")
        else:
            boundary_violation = _cross_parent_boundary_violation(item, notice_group_bboxes)
            if boundary_violation:
                copied = deepcopy(item)
                original_role = str(copied.get("role") or "")
                copied["role"] = "boundary_review_region"
                copied["original_role"] = original_role
                copied["boundary_violation"] = boundary_violation
                copied["action_candidate"] = False
                copied["review_only"] = True
                copied["display_only"] = True
                copied["execute_binding_enabled"] = False
                copied["artifact_is_authorization"] = False
                copied["bbox_policy"] = "cross_parent_boundary_nav_item_needs_review"
                rewritten_items.append(copied)
                role_by_number[number] = str(copied.get("role") or "")
            else:
                rewritten_items.append(item)
                role_by_number[number] = str(item.get("role") or "")

    rewritten_groups: list[dict[str, Any]] = []
    for group in subregion_groups:
        group_role = str(group.get("role") or "")
        if group_role not in {"notice_region", "message_item"}:
            rewritten_groups.append(group)
            continue
        copied_group = deepcopy(group)
        roles: list[str] = []
        for number in copied_group.get("member_numbers", []) if isinstance(copied_group.get("member_numbers"), list) else []:
            role = role_by_number.get(str(number or ""), "")
            if role and role not in roles:
                roles.append(role)
        copied_group["child_group_roles"] = roles
        copied_group["child_role_policy"] = (
            "notice_children_are_not_navigation_actions_without_click_evidence"
            if group_role == "notice_region"
            else "message_children_are_display_only_without_click_evidence"
        )
        rewritten_groups.append(copied_group)
    return rewritten_items, rewritten_groups


def _looks_like_cross_notice_member_nav_item(item: dict[str, Any]) -> bool:
    bbox = _bbox(item.get("bbox"))
    if not bbox:
        return False
    if not _looks_like_member_list_row(item):
        return False
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    if "nav_item" not in role and "readable" not in role and "text" not in role:
        return False
    return bbox["h"] > 72


def _cross_parent_boundary_violation(
    item: dict[str, Any],
    notice_group_bboxes: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if str(item.get("role") or "") != "nav_item":
        return None
    bbox = _bbox(item.get("bbox"))
    if not bbox:
        return None
    for group in notice_group_bboxes:
        group_bbox = _bbox(group.get("bbox"))
        if not group_bbox:
            continue
        overlap = _bbox_overlap_ratio(bbox, group_bbox)
        if overlap <= 0:
            continue
        item_bottom = bbox["y"] + bbox["h"]
        group_bottom = group_bbox["y"] + group_bbox["h"]
        extends_below_notice = item_bottom > group_bottom + 12
        member_like = _looks_like_member_list_row(item)
        too_tall_for_notice_child = bbox["h"] > max(72, int(group_bbox["h"] * 0.65))
        if extends_below_notice or (member_like and too_tall_for_notice_child):
            return {
                "contract_version": "learn_stage2_boundary_violation_v1",
                "category": "notice_member_boundary_leak",
                "overlapped_parent_group_id": str(group.get("group_id") or ""),
                "overlap_ratio": round(float(overlap), 4),
                "extends_below_parent": bool(extends_below_notice),
                "member_like": bool(member_like),
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
    return None


def _section_parent_groups(
    *,
    numbered_items: list[dict[str, Any]],
    content_groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    eligible_group_roles = {
        "media_card_group",
        "tile_card_group",
        "partial_visible_card_group",
        "list_group",
        "form_group",
        "table_group",
    }
    component_member_ids = {
        str(item_id)
        for group in content_groups
        if str(group.get("role") or "") not in eligible_group_roles
        for item_id in (
            group.get("member_item_ids", [])
            if isinstance(group.get("member_item_ids"), list)
            else []
        )
        if str(item_id or "").strip()
    }
    section_titles = [
        item
        for item in numbered_items
        if _looks_like_section_title(item)
        and str(item.get("item_id") or item.get("number") or "") not in component_member_ids
    ]
    if not section_titles or not content_groups:
        return []
    used_title_ids: set[str] = set()
    parents: list[dict[str, Any]] = []
    eligible_groups = [
        group
        for group in content_groups
        if str(group.get("role") or "") in eligible_group_roles
    ]
    for group in sorted(eligible_groups, key=lambda item: (_bbox_top(item), _bbox_left(item))):
        group_bbox = _bbox(group.get("bbox"))
        if not group_bbox:
            continue
        title = _nearest_section_title_above(group_bbox, section_titles, used_title_ids=used_title_ids)
        if not title:
            continue
        title_bbox = _bbox(title.get("bbox"))
        if not title_bbox:
            continue
        title_id = str(title.get("item_id") or title.get("number") or "")
        used_title_ids.add(title_id)
        parent_bbox = _bbox_union([title_bbox, group_bbox])
        if not parent_bbox:
            continue
        group_id = str(group.get("group_id") or "")
        parents.append(
            {
                "contract_version": "learn_stage2_subregion_group_v1",
                "group_id": f"section_parent_{len(parents) + 1}",
                "label": str(title.get("label") or "section"),
                "role": "section_parent",
                "bbox": parent_bbox,
                "title_number": str(title.get("number") or ""),
                "title_item_id": title_id,
                "title_bbox": title_bbox,
                "child_group_ids": [group_id] if group_id else [],
                "child_group_roles": [str(group.get("role") or "")],
                "member_numbers": [
                    str(title.get("number") or ""),
                    *[str(number) for number in group.get("member_numbers", []) if str(number or "").strip()],
                ],
                "member_item_ids": [
                    title_id,
                    *[str(item_id) for item_id in group.get("member_item_ids", []) if str(item_id or "").strip()],
                ],
                "parent_child_policy": "section_title_binds_to_following_card_or_list_group",
                "source": "stage2_section_parent_reconciliation",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    return parents


def _looks_like_section_title(item: dict[str, Any]) -> bool:
    bbox = _bbox(item.get("bbox"))
    if not bbox:
        return False
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    if _looks_like_card_item(item):
        return False
    if role not in {"text", "readable", "label", "heading", "section_title"} and "text" not in role and "heading" not in role:
        return False
    label = str(item.get("label") or "").strip()
    if not label:
        return False
    if bbox["h"] > 72:
        return False
    return True


def _nearest_section_title_above(
    group_bbox: dict[str, int],
    section_titles: list[dict[str, Any]],
    *,
    used_title_ids: set[str],
) -> dict[str, Any] | None:
    candidates: list[tuple[float, dict[str, Any]]] = []
    for title in section_titles:
        title_id = str(title.get("item_id") or title.get("number") or "")
        if title_id in used_title_ids:
            continue
        title_bbox = _bbox(title.get("bbox"))
        if not title_bbox:
            continue
        vertical_gap = group_bbox["y"] - (title_bbox["y"] + title_bbox["h"])
        if vertical_gap < -8 or vertical_gap > max(96, int(group_bbox["h"] * 0.45)):
            continue
        horizontal_overlap = _horizontal_overlap_ratio(title_bbox, group_bbox)
        title_left_near_group = abs(title_bbox["x"] - group_bbox["x"]) <= max(120, int(group_bbox["w"] * 0.35))
        if horizontal_overlap < 0.05 and not title_left_near_group:
            continue
        score = vertical_gap + (0 if title_left_near_group else 40) - horizontal_overlap * 20
        candidates.append((score, title))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    return candidates[0][1]


def _synthesize_primary_media_cards(
    numbered_items: list[dict[str, Any]],
    *,
    image_path: str,
    region_bbox: dict[str, int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    card_boxes = _visual_media_card_boxes(image_path=image_path, parent_bbox=region_bbox)
    if len(card_boxes) < 2:
        return numbered_items, {
            "applied": False,
            "reason": "insufficient_visual_media_card_candidates",
            "candidate_count": len(card_boxes),
            "suppressed_child_item_count": 0,
        }
    card_rows = _media_card_rows(card_boxes)
    row_by_card_index: dict[int, list[dict[str, int]]] = {}
    for row in card_rows:
        for row_card in row:
            for card_index, card_bbox in enumerate(card_boxes):
                if row_card is card_bbox:
                    row_by_card_index[card_index] = row
                    break
    region_no = str(numbered_items[0].get("number") or "1").split(".", 1)[0] if numbered_items else "1"
    used_numbers: set[str] = set()
    child_groups: dict[int, list[dict[str, Any]]] = {index: [] for index in range(len(card_boxes))}
    for item in numbered_items:
        if _is_inter_row_section_heading(item, card_boxes):
            continue
        best_index = _best_media_card_child_index(item, card_boxes)
        if best_index is not None:
            child_groups[best_index].append(item)
    synthesized: list[dict[str, Any]] = []
    structured_parent_reconciliation_count = 0
    for zero_based_index, card_bbox in enumerate(card_boxes):
        index = zero_based_index + 1
        child_items = child_groups.get(zero_based_index, [])
        for child in child_items:
            used_numbers.add(str(child.get("number") or ""))
        slot_card_bbox, slot_inference = _infer_dense_row_placeholder_card_slot(
            card_bbox,
            row_cards=row_by_card_index.get(zero_based_index, []),
            child_items=child_items,
            parent_bbox=region_bbox,
        )
        label = _media_card_label(child_items, fallback=f"media card {index}")
        visual_boundary_before_reconciliation = _bbox(slot_card_bbox)
        structured_parent = _matching_structured_media_card_parent(
            visual_boundary_before_reconciliation or card_bbox,
            numbered_items,
            label=label,
        )
        structured_parent_bbox = _bbox(structured_parent.get("bbox")) if structured_parent else None
        if structured_parent_bbox:
            slot_card_bbox = structured_parent_bbox
            used_numbers.add(str(structured_parent.get("number") or ""))
            structured_parent_reconciliation_count += 1
        expanded_bbox = _media_card_bbox_with_children(slot_card_bbox, child_items, parent_bbox=region_bbox)
        completion = _media_card_completion_status(
            card_bbox=slot_card_bbox,
            expanded_bbox=expanded_bbox,
            row_cards=row_by_card_index.get(zero_based_index, []),
            parent_bbox=region_bbox,
            slot_inference=slot_inference,
        )
        role = "card_parent_incomplete" if not completion["complete"] else "media_card"
        incomplete_card = role == "card_parent_incomplete"
        synthesized.append(
            {
                "contract_version": "learn_stage2_numbered_item_v1",
                "number": f"{region_no}.0",
                "item_id": f"visual_media_card_{region_no}_{index}",
                "label": label,
                "role": role,
                "bbox": expanded_bbox,
                "click_point": {},
                "children": [_child_from_numbered_item(item) for item in child_items if _child_from_numbered_item(item)],
                "needs_review": not completion["complete"],
                "card_parent_validation": completion,
                "review_only": True,
                "stage": "stage2_region_numbering",
                "source": "visual_card_segmenter",
                "bbox_policy": (
                    "visual_media_card_parent_with_inferred_dense_row_slot"
                    if completion["complete"] and slot_inference.get("applied")
                    else (
                        "visual_media_card_parent_with_text_children"
                        if completion["complete"]
                        else "incomplete_visual_card_parent_needs_review"
                    )
                ),
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
                **(
                    {
                        "bbox_reconciliation": {
                            "contract_version": "learn_visual_structured_card_boundary_reconciliation_v1",
                            "source_item_id": str(structured_parent.get("item_id") or ""),
                            "source": str(structured_parent.get("source") or ""),
                            "previous_visual_bbox": visual_boundary_before_reconciliation or {},
                            "reconciled_bbox": deepcopy(expanded_bbox),
                            "reason": "same_label_high_overlap_structured_parent_boundary",
                        }
                    }
                    if structured_parent
                    else {}
                ),
                **(
                    {
                        "review_required": True,
                        "action_candidate": False,
                        "incomplete_reason": "missing_card_slot_or_click_area",
                        "overlay_style": _incomplete_card_overlay_style(),
                    }
                    if incomplete_card
                    else {}
                ),
            }
        )
    kept = [
        item
        for item in numbered_items
        if str(item.get("number") or "") not in used_numbers
        and not _item_overlaps_any_media_card(item, card_boxes)
    ]
    merged = kept + synthesized
    merged.sort(key=lambda item: (_bbox_top(item), _bbox_left(item), str(item.get("label") or "")))
    renumbered = []
    for index, item in enumerate(merged, start=1):
        copied = deepcopy(item)
        copied["number"] = f"{region_no}.{index}"
        renumbered.append(copied)
    return renumbered, {
        "applied": True,
        "reason": "visual_media_card_parent_synthesis",
        "candidate_count": len(card_boxes),
        "synthesized_count": len(synthesized),
        "suppressed_child_item_count": len(used_numbers),
        "structured_parent_reconciliation_count": structured_parent_reconciliation_count,
        "source": "visual_card_segmenter",
    }


def _matching_structured_media_card_parent(
    visual_bbox: dict[str, int],
    numbered_items: list[dict[str, Any]],
    *,
    label: str,
) -> dict[str, Any] | None:
    normalized_label = " ".join(str(label or "").casefold().split())
    if len(normalized_label) < 2 or normalized_label.startswith("media card "):
        return None
    visual_area = max(1, visual_bbox["w"] * visual_bbox["h"])
    matches: list[tuple[bool, float, int, dict[str, Any]]] = []
    for item in numbered_items:
        role = str(item.get("role") or "").casefold()
        item_type = str(item.get("item_type") or "").casefold()
        source = str(item.get("source") or "").casefold()
        item_bbox = _bbox(item.get("bbox"))
        item_label = " ".join(str(item.get("label") or "").casefold().split())
        if not item_bbox or source in _PRIMARY_VISUAL_CARD_SOURCES:
            continue
        if item_type != "actionable" or role in {"text", "icon", "image"}:
            continue
        if len(item_label) < 2 or not (
            item_label == normalized_label
            or item_label in normalized_label
            or normalized_label in item_label
        ):
            continue
        item_area = item_bbox["w"] * item_bbox["h"]
        area_ratio = item_area / visual_area
        if not 0.55 <= area_ratio <= 1.15:
            continue
        if _bbox_overlap_ratio(visual_bbox, item_bbox) < 0.75:
            continue
        if _bbox_overlap_ratio(item_bbox, visual_bbox) < 0.75:
            continue
        matches.append((item_label == normalized_label, abs(1.0 - area_ratio), item_area, item))
    if not matches:
        return None
    matches.sort(key=lambda entry: (not entry[0], entry[1], entry[2], str(entry[3].get("item_id") or "")))
    return matches[0][3]


def _incomplete_card_overlay_style() -> dict[str, Any]:
    return {
        "contract_version": "learn_overlay_style_v1",
        "tone": "needs_review_incomplete_card",
        "stroke": "warning_dashed",
        "display_layer": "review_candidate",
        "label_suffix": "needs review",
        "action_candidate_visual_weight": "low",
    }


def _infer_dense_row_placeholder_card_slot(
    card_bbox: dict[str, Any],
    *,
    row_cards: list[dict[str, int]],
    child_items: list[dict[str, Any]],
    parent_bbox: dict[str, int],
) -> tuple[dict[str, Any], dict[str, Any]]:
    audit: dict[str, Any] = {
        "contract_version": "learn_dense_row_placeholder_slot_inference_v1",
        "applied": False,
        "reason": "not_applicable",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    if len(row_cards) < 4:
        audit["reason"] = "row_not_dense_enough"
        return deepcopy(card_bbox), audit
    visual_bbox = _media_card_visual_bbox(card_bbox)
    row_expanded = [{key: _int(card.get(key)) for key in ("x", "y", "w", "h")} for card in row_cards]
    row_expanded = [box for box in row_expanded if box.get("w", 0) > 0 and box.get("h", 0) > 0]
    row_visuals = [_media_card_visual_bbox(card) for card in row_cards if _media_card_visual_bbox(card)]
    if len(row_expanded) < 4:
        audit["reason"] = "insufficient_row_geometry"
        return deepcopy(card_bbox), audit
    median_width = _median_positive([box["w"] for box in row_expanded])
    median_height = _median_positive([box["h"] for box in row_expanded])
    median_top = _median_positive([box["y"] for box in row_expanded])
    median_visual_width = _median_positive([box["w"] for box in row_visuals])
    median_visual_height = _median_positive([box["h"] for box in row_visuals])
    if median_width <= 0 or median_height <= 0 or median_top <= 0:
        audit["reason"] = "missing_row_medians"
        return deepcopy(card_bbox), audit
    if (
        median_visual_width > 0
        and median_visual_height > 0
        and visual_bbox["w"] >= median_visual_width * 0.70
        and visual_bbox["h"] >= median_visual_height * 0.70
    ):
        audit["reason"] = "visual_bbox_already_slot_sized"
        return deepcopy(card_bbox), audit

    child_boxes = [_bbox(item.get("bbox")) for item in child_items]
    child_boxes = [box for box in child_boxes if box]
    if not child_boxes:
        audit["reason"] = "missing_text_or_child_anchor"
        return deepcopy(card_bbox), audit
    child_union = _bbox_union(child_boxes)
    if not child_union:
        audit["reason"] = "missing_child_union"
        return deepcopy(card_bbox), audit

    sorted_row = sorted(row_expanded, key=lambda box: box["x"] + box["w"] / 2)
    visual_center_x = visual_bbox["x"] + visual_bbox["w"] / 2
    target_index = min(
        range(len(sorted_row)),
        key=lambda index: abs((sorted_row[index]["x"] + sorted_row[index]["w"] / 2) - visual_center_x),
    )
    prev_box = sorted_row[target_index - 1] if target_index > 0 else None
    next_box = sorted_row[target_index + 1] if target_index + 1 < len(sorted_row) else None
    target_width = int(round(median_width))
    child_bottom = child_union["y"] + child_union["h"]
    evidence_height = max(1, child_bottom - int(round(median_top)))
    target_height = int(round(max(median_visual_height, evidence_height)))
    inferred_x = int(round(min(child_union["x"], visual_center_x - target_width / 2)))
    if prev_box:
        inferred_x = max(inferred_x, prev_box["x"] + prev_box["w"] + 8)
    if next_box:
        inferred_x = min(inferred_x, next_box["x"] - target_width - 8)
    inferred_y = int(round(median_top))
    inferred = _clip_bbox(
        parent_bbox,
        {
            "x": inferred_x,
            "y": inferred_y,
            "w": target_width,
            "h": target_height,
        },
    )
    if inferred["w"] < median_width * 0.75 or inferred["h"] < target_height * 0.75:
        audit["reason"] = "inferred_slot_clipped_too_small"
        audit["candidate_slot_bbox"] = inferred
        return deepcopy(card_bbox), audit

    copied = deepcopy(card_bbox)
    copied.update(inferred)
    copied["visual_bbox"] = deepcopy(visual_bbox)
    copied["inferred_slot_bbox"] = deepcopy(inferred)
    audit.update(
        {
            "applied": True,
            "reason": "dense_row_placeholder_visual_slot_inferred",
            "original_visual_bbox": deepcopy(visual_bbox),
            "inferred_slot_bbox": deepcopy(inferred),
            "child_anchor_bbox": deepcopy(child_union),
            "row_peer_count": len(row_expanded),
            "row_medians": {
                "expanded_width": median_width,
                "expanded_height": median_height,
                "expanded_top": median_top,
                "visual_width": median_visual_width,
                "visual_height": median_visual_height,
                "evidence_height": evidence_height,
            },
        }
    )
    return copied, audit


def _media_card_completion_status(
    *,
    card_bbox: dict[str, Any],
    expanded_bbox: dict[str, int],
    row_cards: list[dict[str, int]],
    parent_bbox: dict[str, int],
    slot_inference: dict[str, Any] | None = None,
) -> dict[str, Any]:
    visual_bbox = _media_card_visual_bbox(card_bbox)
    original_visual_bbox = (
        _bbox(card_bbox.get("visual_bbox")) if isinstance(card_bbox.get("visual_bbox"), dict) else visual_bbox
    )
    visual_activity_ratio = float(card_bbox.get("visual_activity_ratio") or 0.0)
    reasons: list[str] = []
    row_visuals = [_media_card_visual_bbox(card) for card in row_cards if _media_card_visual_bbox(card)]
    row_expanded = [{key: _int(card.get(key)) for key in ("x", "y", "w", "h")} for card in row_cards]
    row_expanded = [card for card in row_expanded if card.get("w", 0) > 0 and card.get("h", 0) > 0]
    median_visual_width = _median_positive([card["w"] for card in row_visuals])
    median_visual_height = _median_positive([card["h"] for card in row_visuals])
    median_expanded_width = _median_positive([card["w"] for card in row_expanded])
    median_expanded_height = _median_positive([card["h"] for card in row_expanded])
    visual_too_small_for_dense_row = (
        len(row_visuals) >= 4
        and median_visual_width > 0
        and median_visual_height > 0
        and median_expanded_width > 0
        and median_expanded_height > 0
        and (
            visual_bbox["w"] < median_visual_width * 0.65
            or visual_bbox["h"] < median_visual_height * 0.65
        )
        and (
            expanded_bbox["w"] < median_expanded_width * 0.85
            or expanded_bbox["h"] < median_expanded_height * 0.80
        )
    )
    clipped_and_smaller_than_row = (
        _bbox_touches_parent_clip_edge(expanded_bbox, parent_bbox)
        and median_visual_width > 0
        and median_visual_height > 0
        and (
            visual_bbox["w"] < median_visual_width * 0.95
            or visual_bbox["h"] < median_visual_height * 0.95
        )
    )
    if visual_too_small_for_dense_row:
        reasons.append("visual_card_slot_smaller_than_dense_row_peers")
    if clipped_and_smaller_than_row:
        reasons.append("card_bbox_clipped_by_parent_region")
    slot_inference = slot_inference if isinstance(slot_inference, dict) else {"applied": False}
    if (
        not slot_inference.get("applied")
        and visual_activity_ratio > 0
        and visual_activity_ratio < 0.38
        and median_visual_width > 0
        and median_visual_height > 0
        and visual_bbox["w"] >= median_visual_width * 0.95
        and visual_bbox["h"] >= median_visual_height * 0.95
        and len(row_visuals) < 4
    ):
        reasons.append("low_visual_activity_placeholder_card")
    if slot_inference.get("applied") and reasons == ["visual_card_slot_smaller_than_dense_row_peers"]:
        reasons = []
    return {
        "contract_version": "learn_media_card_parent_validation_v1",
        "complete": not reasons,
        "reasons": reasons,
        "visual_bbox": visual_bbox,
        "original_visual_bbox": original_visual_bbox,
        "visual_activity_ratio": round(visual_activity_ratio, 4),
        "slot_inference": deepcopy(slot_inference),
        "expanded_bbox": expanded_bbox,
        "row_peer_count": len(row_visuals),
        "row_medians": {
            "visual_width": median_visual_width,
            "visual_height": median_visual_height,
            "expanded_width": median_expanded_width,
            "expanded_height": median_expanded_height,
        },
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _median_positive(values: list[int]) -> float:
    positives = sorted(value for value in values if value > 0)
    if not positives:
        return 0.0
    middle = len(positives) // 2
    if len(positives) % 2:
        return float(positives[middle])
    return (positives[middle - 1] + positives[middle]) / 2


def _bbox_touches_parent_clip_edge(bbox: dict[str, int], parent_bbox: dict[str, int]) -> bool:
    if not bbox or not parent_bbox:
        return False
    right_gap = parent_bbox["x"] + parent_bbox["w"] - (bbox["x"] + bbox["w"])
    bottom_gap = parent_bbox["y"] + parent_bbox["h"] - (bbox["y"] + bbox["h"])
    return 0 <= right_gap <= 2 or 0 <= bottom_gap <= 2


def _synthesize_partial_visible_cards(
    numbered_items: list[dict[str, Any]],
    *,
    image_path: str,
    region_bbox: dict[str, int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    section_title = _bottom_partial_card_section_title(numbered_items, region_bbox=region_bbox)
    if not section_title:
        return numbered_items, {
            "applied": False,
            "reason": "no_bottom_section_title_for_partial_cards",
            "candidate_count": 0,
            "synthesized_count": 0,
            "suppressed_child_item_count": 0,
        }
    title_bbox = _bbox(section_title.get("bbox"))
    candidates = [
        item
        for item in numbered_items
        if _is_bottom_edge_partial_card_fragment(item, region_bbox=region_bbox)
        and (not title_bbox or (_bbox(item.get("bbox")) or {"y": 0})["y"] > title_bbox["y"] + title_bbox["h"] + 6)
    ]
    visual_search_bbox = _partial_visible_card_visual_search_bbox(
        image_path=image_path,
        region_bbox=region_bbox,
        title_bbox=title_bbox or {},
    )
    visual_boxes = _visual_bottom_partial_card_boxes(
        image_path=image_path,
        region_bbox=visual_search_bbox,
        title_bbox=title_bbox or {},
    )
    if len(candidates) < 2 and len(visual_boxes) < 2:
        return numbered_items, {
            "applied": False,
            "reason": "insufficient_bottom_edge_card_evidence",
            "candidate_count": len(candidates),
            "synthesized_count": 0,
            "suppressed_child_item_count": 0,
            "visual_candidate_count": len(visual_boxes),
        }
    clusters = _cluster_partial_card_fragments(candidates)
    if not clusters and not visual_boxes:
        return numbered_items, {
            "applied": False,
            "reason": "no_partial_fragment_clusters",
            "candidate_count": len(candidates),
            "synthesized_count": 0,
            "suppressed_child_item_count": 0,
        }
    used_numbers = {str(item.get("number") or "") for cluster in clusters for item in cluster}
    kept = [item for item in numbered_items if str(item.get("number") or "") not in used_numbers]
    partial_cards: list[dict[str, Any]] = []
    cluster_entries = _merge_partial_text_clusters_with_visual_boxes(clusters, visual_boxes)
    suppressed_duplicate_partial_card_count = 0
    for index, entry in enumerate(cluster_entries, start=1):
        cluster = entry.get("items", []) if isinstance(entry.get("items"), list) else []
        visual_bbox = _bbox(entry.get("visual_bbox"))
        bbox = _bbox_union([*[item.get("bbox") for item in cluster], *([visual_bbox] if visual_bbox else [])])
        if not bbox:
            continue
        label = " ".join(str(item.get("label") or "").strip() for item in cluster if str(item.get("label") or "").strip())
        partial_card = {
            "contract_version": "learn_stage2_numbered_item_v1",
            "number": "0.0",
            "item_id": f"partial_visible_card_{index}",
            "label": label or f"partial visible card {index}",
            "role": "partial_visible_card",
            "bbox": _clip_bbox(visual_search_bbox, bbox),
            "click_point": {},
            "children": [_child_from_numbered_item(item) for item in cluster if _child_from_numbered_item(item)],
            "partial_visible": True,
            "review_only": True,
            "stage": "stage2_region_numbering",
            "source": "bottom_edge_partial_card_reconciliation",
            "bbox_policy": "bottom_edge_visible_partial_card_from_text_fragments",
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
        if _partial_card_duplicates_existing_structured_card(partial_card, kept):
            suppressed_duplicate_partial_card_count += 1
            continue
        partial_cards.append(partial_card)
    merged = kept + partial_cards
    renumbered = _renumber_stage2_items(merged, horizontal=False)
    return renumbered, {
        "applied": bool(partial_cards),
        "reason": "bottom_edge_text_fragments_grouped_as_partial_visible_cards" if partial_cards else "no_partial_cards_synthesized",
        "candidate_count": len(candidates),
        "synthesized_count": len(partial_cards),
        "suppressed_child_item_count": len(used_numbers),
        "suppressed_duplicate_partial_card_count": suppressed_duplicate_partial_card_count,
        "visual_candidate_count": len(visual_boxes),
        "visual_search_bbox": visual_search_bbox,
        "section_title_item_id": str(section_title.get("item_id") or section_title.get("number") or ""),
        "source": "bottom_edge_partial_card_reconciliation",
    }


def _partial_card_duplicates_existing_structured_card(
    partial_card: dict[str, Any],
    existing_items: list[dict[str, Any]],
) -> bool:
    partial_bbox = _bbox(partial_card.get("bbox"))
    if not partial_bbox:
        return False
    for item in existing_items:
        if str(item.get("role") or "") == "partial_visible_card":
            continue
        if not _looks_like_card_item(item):
            continue
        existing_bbox = _bbox(item.get("bbox"))
        if not existing_bbox:
            continue
        partial_in_existing = _bbox_overlap_ratio(partial_bbox, existing_bbox)
        existing_in_partial = _bbox_overlap_ratio(existing_bbox, partial_bbox)
        if max(partial_in_existing, existing_in_partial) >= 0.55:
            return True
    return False


def _synthesize_chat_image_messages(
    numbered_items: list[dict[str, Any]],
    *,
    image_path: str,
    region_bbox: dict[str, int],
    chat_surface_confirmed: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    anchors = [item for item in numbered_items if _looks_like_chat_surface_anchor(item)]
    if not anchors and not chat_surface_confirmed:
        return numbered_items, {
            "applied": False,
            "reason": "no_chat_surface_anchor",
            "candidate_count": 0,
            "synthesized_count": 0,
        }
    message_column_min = min(
        (_bbox_left(item) for item in anchors if _bbox(item.get("bbox"))),
        default=region_bbox.get("x", 0) + 48,
    ) - 48
    visual_boxes = _visual_chat_image_message_boxes(
        image_path=image_path,
        region_bbox=region_bbox,
        min_x=max(region_bbox.get("x", 0), message_column_min),
    )
    if not visual_boxes:
        return numbered_items, {
            "applied": False,
            "reason": "no_visual_chat_image_candidates",
            "candidate_count": 0,
            "synthesized_count": 0,
        }
    existing_bboxes = [
        _bbox(item.get("bbox"))
        for item in numbered_items
        if not _is_layout_background_review_item(item)
    ]
    synthesized_boxes: list[dict[str, int]] = []
    for box in visual_boxes:
        if any(existing and _bbox_overlap_ratio(box, existing) >= 0.55 for existing in existing_bboxes):
            continue
        synthesized_boxes.append(box)
    if not synthesized_boxes:
        return numbered_items, {
            "applied": False,
            "reason": "visual_chat_image_candidates_overlap_existing_items",
            "candidate_count": len(visual_boxes),
            "synthesized_count": 0,
        }
    region_no = str(numbered_items[0].get("number") or "1").split(".", 1)[0] if numbered_items else "1"
    synthesized: list[dict[str, Any]] = []
    for index, bbox in enumerate(synthesized_boxes, start=1):
        synthesized.append(
            {
                "contract_version": "learn_stage2_numbered_item_v1",
                "number": f"{region_no}.0",
                "item_id": f"visual_image_message_{region_no}_{index}",
                "label": f"image message {index}",
                "role": "image_message",
                "bbox": _clip_bbox(region_bbox, bbox),
                "click_point": {},
                "children": [],
                "review_only": True,
                "stage": "stage2_region_numbering",
                "source": "chat_visual_image_message_synthesis",
                "bbox_policy": "chat_context_visual_image_message_candidate",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
                "action_candidate": False,
            }
        )
    merged = numbered_items + synthesized
    merged.sort(key=lambda item: (_bbox_top(item), _bbox_left(item), str(item.get("label") or "")))
    return _renumber_stage2_items(merged, horizontal=False), {
        "applied": True,
        "reason": "chat_context_visual_image_message_synthesized",
        "chat_surface_evidence": "atomic_chat_anchor" if anchors else "stage1_5_message_thread",
        "candidate_count": len(visual_boxes),
        "synthesized_count": len(synthesized),
        "source": "chat_visual_image_message_synthesis",
    }


def _visual_chat_image_message_boxes(
    *,
    image_path: str,
    region_bbox: dict[str, int],
    min_x: int,
) -> list[dict[str, int]]:
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return []
    source = Path(image_path)
    if not source.exists() or not region_bbox:
        return []
    try:
        with Image.open(source) as image:
            crop = image.crop(
                (
                    region_bbox["x"],
                    region_bbox["y"],
                    region_bbox["x"] + region_bbox["w"],
                    region_bbox["y"] + region_bbox["h"],
                )
            ).convert("RGB")
    except Exception:
        return []
    arr = np.array(crop)
    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    mask = ((saturation > 45) & (value > 55)).astype("uint8") * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (11, 11))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes: list[dict[str, int]] = []
    small_candidates: list[dict[str, int]] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        box = {"x": region_bbox["x"] + x, "y": region_bbox["y"] + y, "w": w, "h": h}
        if box["x"] < min_x:
            continue
        area = w * h
        if w > region_bbox["w"] * 0.55 or h > region_bbox["h"] * 0.45:
            continue
        clipped = _clip_bbox(region_bbox, box)
        if w >= 56 and h >= 56 and area >= 3600:
            boxes.append(clipped)
        elif 32 <= w <= 96 and 28 <= h <= 96 and area >= 900:
            small_candidates.append(clipped)
    repeated_small_ids: set[int] = set()
    for index, seed in enumerate(small_candidates):
        seed_right = seed["x"] + seed["w"]
        cluster = []
        for candidate_index, candidate in enumerate(small_candidates):
            candidate_right = candidate["x"] + candidate["w"]
            width_ratio = min(seed["w"], candidate["w"]) / max(seed["w"], candidate["w"])
            height_ratio = min(seed["h"], candidate["h"]) / max(seed["h"], candidate["h"])
            if (
                abs(candidate_right - seed_right) <= max(10, int(seed["w"] * 0.25))
                and width_ratio >= 0.7
                and height_ratio >= 0.65
            ):
                cluster.append(candidate_index)
        if len(cluster) >= 2:
            repeated_small_ids.update(cluster)
    boxes.extend(small_candidates[index] for index in sorted(repeated_small_ids))
    return _dedupe_bboxes(boxes, iou_threshold=0.72)


def _is_layout_background_review_item(item: dict[str, Any]) -> bool:
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    source = str(item.get("source") or "").casefold()
    return any(token in role for token in ("content_area", "section", "layout", "review_region")) or "screen_map.sections" in source


def _normalize_text_only_button_hit_areas(
    numbered_items: list[dict[str, Any]],
    *,
    region_bbox: dict[str, int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    for item in numbered_items:
        bbox = _bbox(item.get("bbox"))
        if not bbox or not _looks_like_text_only_button(item):
            normalized.append(item)
            continue
        expanded = _text_button_hit_area_bbox(bbox, parent_bbox=region_bbox)
        copied = deepcopy(item)
        copied["role"] = "text_button"
        copied["original_role"] = str(item.get("role") or "")
        copied["bbox"] = expanded
        copied["bbox_policy"] = "text_only_button_hit_area_normalized"
        copied["bbox_refinement"] = {
            "source": "text_only_button_hit_area_normalizer",
            "previous_bbox": bbox,
            "reason": "button_label_text_box_must_cover_hit_area",
        }
        copied["review_only"] = True
        copied["display_only"] = True
        copied["execute_binding_enabled"] = False
        copied["artifact_is_authorization"] = False
        copied["action_candidate"] = False
        normalized.append(copied)
        changed.append({"item_id": copied.get("item_id"), "label": copied.get("label"), "from": bbox, "to": expanded})
    return normalized, {
        "applied": bool(changed),
        "reason": "text_only_button_hit_area_normalized" if changed else "no_text_only_button_candidates",
        "candidate_count": len(changed),
        "normalized_count": len(changed),
        "pairs": changed,
    }


def _normalize_text_only_message_bubble_backgrounds(
    numbered_items: list[dict[str, Any]],
    *,
    region_bbox: dict[str, int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    message_column_min = _message_column_min_for_bubble_normalization(numbered_items)
    message_card_content_item_ids = _message_card_content_item_ids(numbered_items)
    if message_column_min is None:
        return list(numbered_items), {
            "applied": False,
            "reason": "no_chat_surface_evidence",
            "candidate_count": 0,
            "normalized_count": 0,
            "pairs": [],
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
    normalized: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    for item in numbered_items:
        bbox = _bbox(item.get("bbox"))
        child_role = _message_child_role(item, chat_context=True)
        label = str(item.get("label") or "").strip()
        if str(item.get("item_id") or "") in message_card_content_item_ids:
            copied = deepcopy(item)
            copied["role"] = "message_card_content"
            copied["original_role"] = str(item.get("role") or "")
            copied["bbox_policy"] = "message_card_child_content_not_message_bubble"
            copied["review_required"] = True
            copied["review_only"] = True
            copied["display_only"] = True
            copied["execute_binding_enabled"] = False
            copied["artifact_is_authorization"] = False
            copied["action_candidate"] = False
            normalized.append(copied)
            continue
        if (
            not bbox
            or bbox["x"] < message_column_min
            or _looks_like_chat_surface_anchor(item)
            or child_role != "message_bubble"
        ):
            normalized.append(item)
            continue
        if bbox["w"] >= 250 and bbox["h"] >= 72:
            copied = deepcopy(item)
            copied["role"] = "message_bubble"
            normalized.append(copied)
            continue
        expanded = _message_bubble_review_background_bbox(bbox, parent_bbox=region_bbox)
        if expanded == bbox:
            copied = deepcopy(item)
            copied["role"] = "message_bubble"
            normalized.append(copied)
            continue
        copied = deepcopy(item)
        copied["role"] = "message_bubble"
        copied["original_role"] = str(item.get("role") or "")
        copied["bbox"] = expanded
        copied["bbox_policy"] = "message_bubble_background_expanded_needs_review"
        copied["raw_bbox_before_policy"] = bbox
        copied["bbox_refinement"] = {
            "source": "text_only_message_bubble_background_normalizer",
            "previous_bbox": bbox,
            "reason": "ocr_text_box_is_not_full_message_bubble_background",
        }
        copied["review_required"] = True
        copied["review_only"] = True
        copied["display_only"] = True
        copied["execute_binding_enabled"] = False
        copied["artifact_is_authorization"] = False
        copied["action_candidate"] = False
        normalized.append(copied)
        changed.append({"item_id": copied.get("item_id"), "label": copied.get("label"), "from": bbox, "to": expanded})
    return normalized, {
        "applied": bool(changed),
        "reason": "message_bubble_background_expanded" if changed else "no_text_only_message_bubble_candidates",
        "candidate_count": len(changed),
        "normalized_count": len(changed),
        "pairs": changed,
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _message_card_content_item_ids(numbered_items: list[dict[str, Any]]) -> set[str]:
    card_boxes = [
        _bbox(item.get("bbox"))
        for item in numbered_items
        if _message_child_role(item, chat_context=True) == "message_card"
    ]
    card_boxes = [box for box in card_boxes if box]
    protected: set[str] = set()
    for card_bbox in card_boxes:
        candidates: list[tuple[dict[str, int], dict[str, Any]]] = []
        for item in numbered_items:
            item_id = str(item.get("item_id") or "")
            bbox = _bbox(item.get("bbox"))
            label = str(item.get("label") or "").strip()
            if (
                not item_id
                or not bbox
                or _message_child_role(item, chat_context=True) == "message_card"
                or _looks_like_timestamp_label(label)
                or _looks_like_sender_or_level_context(item)
                or _bbox_containment_ratio(bbox, card_bbox) < 0.9
            ):
                continue
            candidates.append((bbox, item))
        candidates.sort(key=lambda pair: (pair[0]["y"], pair[0]["x"]))
        previous_bottom: int | None = None
        for bbox, item in candidates:
            if previous_bottom is not None and bbox["y"] - previous_bottom > 42:
                break
            protected.add(str(item.get("item_id") or ""))
            previous_bottom = max(previous_bottom or 0, bbox["y"] + bbox["h"])
    return protected


def _bbox_containment_ratio(inner: dict[str, int], outer: dict[str, int]) -> float:
    x1 = max(inner["x"], outer["x"])
    y1 = max(inner["y"], outer["y"])
    x2 = min(inner["x"] + inner["w"], outer["x"] + outer["w"])
    y2 = min(inner["y"] + inner["h"], outer["y"] + outer["h"])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    return intersection / max(1, inner["w"] * inner["h"])


def _message_column_min_for_bubble_normalization(numbered_items: list[dict[str, Any]]) -> int | None:
    explicit_candidates = [item for item in numbered_items if _looks_like_message_fragment(item)]
    if not explicit_candidates:
        return None
    anchor_candidates = [item for item in explicit_candidates if _looks_like_chat_surface_anchor(item)]
    column_seed = anchor_candidates or explicit_candidates
    left_values = [_bbox_left(item) for item in column_seed if _bbox(item.get("bbox"))]
    if not left_values:
        return None
    return min(left_values) - 48


def _message_bubble_review_background_bbox(bbox: dict[str, int], *, parent_bbox: dict[str, int]) -> dict[str, int]:
    target_w = max(250, min(340, bbox["w"] + 40))
    target_h = max(56, min(120, bbox["h"] + 40))
    x = int(round(bbox["x"] - 10))
    y = int(round(bbox["y"] - 8))
    parent_right = parent_bbox["x"] + parent_bbox["w"]
    parent_bottom = parent_bbox["y"] + parent_bbox["h"]
    if x + target_w > parent_right:
        x = parent_right - target_w
    if y + target_h > parent_bottom:
        y = parent_bottom - target_h
    x = max(parent_bbox["x"], x)
    y = max(parent_bbox["y"], y)
    return _clip_bbox(parent_bbox, {"x": int(x), "y": int(y), "w": int(target_w), "h": int(target_h)})


def _looks_like_text_only_button(item: dict[str, Any]) -> bool:
    bbox = _bbox(item.get("bbox"))
    if not bbox:
        return False
    label = str(item.get("label") or "").strip().casefold()
    if not label:
        return False
    keywords = (
        "send",
        "发送",
        "submit",
        "提交",
        "complete",
        "完成",
        "confirm",
        "确认",
        "apply now",
        "立即申请",
    )
    if not any(keyword in label for keyword in keywords):
        return False
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    if not any(token in role for token in ("text", "readable", "label", "button")):
        return False
    return bbox["w"] < 88 or bbox["h"] < 32


def _text_button_hit_area_bbox(bbox: dict[str, int], *, parent_bbox: dict[str, int]) -> dict[str, int]:
    target_w = max(72, min(120, bbox["w"] + 36))
    target_h = max(34, min(48, bbox["h"] + 18))
    cx = bbox["x"] + bbox["w"] / 2
    cy = bbox["y"] + bbox["h"] / 2
    x = int(round(cx - target_w / 2))
    y = int(round(cy - target_h / 2))
    parent_right = parent_bbox["x"] + parent_bbox["w"]
    parent_bottom = parent_bbox["y"] + parent_bbox["h"]
    if x + target_w > parent_right:
        x = parent_right - target_w
    if y + target_h > parent_bottom:
        y = parent_bottom - target_h
    x = max(parent_bbox["x"], x)
    y = max(parent_bbox["y"], y)
    expanded = {"x": int(x), "y": int(y), "w": int(target_w), "h": int(target_h)}
    return _clip_bbox(parent_bbox, expanded)


def _partial_visible_card_visual_search_bbox(
    *,
    image_path: str,
    region_bbox: dict[str, int],
    title_bbox: dict[str, int],
) -> dict[str, int]:
    if not region_bbox:
        return {}
    try:
        with Image.open(Path(image_path)) as image:
            image_width, image_height = image.size
    except Exception:
        image_width = region_bbox["x"] + region_bbox["w"]
        image_height = region_bbox["y"] + region_bbox["h"]
    left = min(region_bbox["x"], title_bbox.get("x", region_bbox["x"]))
    right = max(region_bbox["x"] + region_bbox["w"], image_width)
    bottom = min(max(region_bbox["y"] + region_bbox["h"], title_bbox.get("y", region_bbox["y"]) + 1), image_height)
    return {
        "x": max(0, left),
        "y": max(0, region_bbox["y"]),
        "w": max(1, right - max(0, left)),
        "h": max(1, bottom - max(0, region_bbox["y"])),
    }


def _merge_partial_text_clusters_with_visual_boxes(
    clusters: list[list[dict[str, Any]]],
    visual_boxes: list[dict[str, int]],
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    matched_visual_indexes: set[int] = set()
    visual_entries: dict[int, dict[str, Any]] = {}
    unmatched_clusters: list[list[dict[str, Any]]] = []
    for cluster in clusters:
        cluster_bbox = _bbox_union([item.get("bbox") for item in cluster])
        best_index: int | None = None
        best_score = 0.0
        if cluster_bbox:
            for index, visual in enumerate(visual_boxes):
                overlap = _horizontal_overlap_ratio(cluster_bbox, visual)
                center_x = cluster_bbox["x"] + cluster_bbox["w"] / 2
                center_inside = visual["x"] <= center_x <= visual["x"] + visual["w"]
                score = overlap + (0.5 if center_inside else 0.0)
                if score > best_score and score >= 0.35:
                    best_score = score
                    best_index = index
        visual_bbox = visual_boxes[best_index] if best_index is not None else None
        if best_index is not None:
            matched_visual_indexes.add(best_index)
            entry = visual_entries.setdefault(best_index, {"items": [], "visual_bbox": visual_bbox})
            entry["items"].extend(cluster)
        else:
            unmatched_clusters.append(cluster)
    entries.extend(visual_entries[index] for index in sorted(visual_entries))
    entries.extend(_merge_unmatched_partial_clusters_from_peer_width(unmatched_clusters, visual_boxes))
    for index, visual in enumerate(visual_boxes):
        if index in matched_visual_indexes:
            continue
        entries.append({"items": [], "visual_bbox": visual})
    entries.sort(key=lambda entry: (_bbox_left({"bbox": entry.get("visual_bbox") or _bbox_union([item.get("bbox") for item in entry.get("items", [])]) or {}}), _bbox_top({"bbox": entry.get("visual_bbox") or {}})))
    return entries


def _merge_unmatched_partial_clusters_from_peer_width(
    clusters: list[list[dict[str, Any]]],
    visual_boxes: list[dict[str, int]],
) -> list[dict[str, Any]]:
    if not clusters:
        return []
    ordered = sorted(clusters, key=lambda cluster: _bbox_left({"bbox": _bbox_union([item.get("bbox") for item in cluster]) or {}}))
    widths = sorted(box["w"] for box in visual_boxes if _bbox(box))
    if not widths:
        return [{"items": cluster, "visual_bbox": {}} for cluster in ordered]
    peer_width = widths[len(widths) // 2]
    peer_box = min(visual_boxes, key=lambda box: box["x"])
    merged_clusters: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for cluster in ordered:
        proposed = [*current, *cluster]
        proposed_bbox = _bbox_union([item.get("bbox") for item in proposed])
        if current and proposed_bbox and proposed_bbox["w"] > int(round(peer_width * 1.18)):
            merged_clusters.append(current)
            current = list(cluster)
        else:
            current = proposed
    if current:
        merged_clusters.append(current)

    entries: list[dict[str, Any]] = []
    for cluster in merged_clusters:
        cluster_bbox = _bbox_union([item.get("bbox") for item in cluster])
        if not cluster_bbox:
            entries.append({"items": cluster, "visual_bbox": {}})
            continue
        inferred_bbox = {
            "x": cluster_bbox["x"],
            "y": peer_box["y"],
            "w": max(peer_width, cluster_bbox["w"]),
            "h": peer_box["h"],
        }
        entries.append({"items": cluster, "visual_bbox": inferred_bbox})
    return entries


def _visual_bottom_partial_card_boxes(
    *,
    image_path: str,
    region_bbox: dict[str, int],
    title_bbox: dict[str, int],
) -> list[dict[str, int]]:
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return []
    source = Path(image_path)
    if not source.exists() or not region_bbox or not title_bbox:
        return []
    title_bottom = title_bbox["y"] + title_bbox["h"]
    y1 = max(title_bottom + 8, region_bbox["y"] + int(region_bbox["h"] * 0.72))
    y2 = region_bbox["y"] + region_bbox["h"]
    if y2 - y1 < 24:
        return []
    try:
        with Image.open(source) as image:
            crop = image.crop((region_bbox["x"], y1, region_bbox["x"] + region_bbox["w"], y2)).convert("RGB")
    except Exception:
        return []
    arr = np.array(crop)
    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    active = ((saturation > 35) | (value < 210)).astype("uint8")
    column_activity = active.mean(axis=0)
    segments: list[tuple[int, int]] = []
    start: int | None = None
    for index, value_ in enumerate(column_activity):
        if value_ > 0.08:
            if start is None:
                start = index
        elif start is not None:
            if index - start >= 40:
                segments.append((start, index))
            start = None
    if start is not None and len(column_activity) - start >= 40:
        segments.append((start, len(column_activity)))
    boxes: list[dict[str, int]] = []
    max_single_card_width = max(160, int(round(region_bbox["w"] * 0.55)))
    for start_x, end_x in segments:
        if end_x - start_x > max_single_card_width:
            continue
        segment_activity = active[:, start_x:end_x]
        rows = np.where(segment_activity.mean(axis=1) > 0.04)[0]
        if rows.size == 0:
            continue
        local_y1 = int(rows.min())
        local_y2 = int(rows.max()) + 1
        box = {
            "x": region_bbox["x"] + int(start_x),
            "y": y1 + local_y1,
            "w": int(end_x - start_x),
            "h": max(1, local_y2 - local_y1),
        }
        if box["h"] >= 12:
            boxes.append(_clip_bbox(region_bbox, box))
    return _dedupe_bboxes(boxes, iou_threshold=0.6)


def _bottom_partial_card_section_title(
    numbered_items: list[dict[str, Any]],
    *,
    region_bbox: dict[str, int],
) -> dict[str, Any] | None:
    candidates: list[tuple[int, dict[str, Any]]] = []
    for item in numbered_items:
        bbox = _bbox(item.get("bbox"))
        if not bbox or not _looks_like_section_title(item):
            continue
        if not _has_meaningful_section_title_text(item):
            continue
        below = [
            other
            for other in numbered_items
            if other is not item and _is_candidate_below_bottom_section_title(other, title_bbox=bbox, region_bbox=region_bbox)
        ]
        if not below:
            continue
        candidates.append((bbox["y"], item))
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return candidates[0][1]


def _is_candidate_below_bottom_section_title(
    item: dict[str, Any],
    *,
    title_bbox: dict[str, int],
    region_bbox: dict[str, int],
) -> bool:
    bbox = _bbox(item.get("bbox"))
    if not bbox:
        return False
    if bbox["y"] <= title_bbox["y"] + title_bbox["h"] + 6:
        return False
    if bbox["y"] - (title_bbox["y"] + title_bbox["h"]) > 120:
        return False
    return _is_bottom_edge_partial_card_fragment(item, region_bbox=region_bbox)


def _has_meaningful_section_title_text(item: dict[str, Any]) -> bool:
    label = str(item.get("label") or "").strip()
    if len(label) < 2:
        return False
    semantic_text_count = sum(1 for char in label if char.isalpha() or "\u4e00" <= char <= "\u9fff")
    return semantic_text_count >= 2


def _is_bottom_edge_partial_card_fragment(item: dict[str, Any], *, region_bbox: dict[str, int]) -> bool:
    bbox = _bbox(item.get("bbox"))
    if not bbox or not region_bbox:
        return False
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    if role not in {"text", "readable", "label"} and "text" not in role:
        return False
    if _looks_like_card_item(item) or "heading" in role or "section_title" in role:
        return False
    label = str(item.get("label") or "").strip()
    if not label:
        return False
    bottom_edge = region_bbox["y"] + region_bbox["h"]
    near_bottom = bbox["y"] >= region_bbox["y"] + int(region_bbox["h"] * 0.78) or bbox["y"] + bbox["h"] >= bottom_edge - 72
    if not near_bottom:
        return False
    if bbox["h"] > 48:
        return False
    return True


def _cluster_partial_card_fragments(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    rows: list[list[dict[str, Any]]] = []
    for item in sorted(items, key=lambda entry: (_bbox_top(entry), _bbox_left(entry))):
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            continue
        center_y = bbox["y"] + bbox["h"] / 2
        target_row: list[dict[str, Any]] | None = None
        for row in rows:
            row_boxes = [_bbox(existing.get("bbox")) for existing in row]
            row_boxes = [box for box in row_boxes if box]
            if not row_boxes:
                continue
            row_center = sum(box["y"] + box["h"] / 2 for box in row_boxes) / len(row_boxes)
            if abs(center_y - row_center) <= 16:
                target_row = row
                break
        if target_row is None:
            rows.append([item])
        else:
            target_row.append(item)
    clusters: list[list[dict[str, Any]]] = []
    for row in rows:
        current: list[dict[str, Any]] = []
        previous_bbox: dict[str, int] | None = None
        for item in sorted(row, key=_bbox_left):
            bbox = _bbox(item.get("bbox"))
            if not bbox:
                continue
            if previous_bbox is None:
                current = [item]
                previous_bbox = bbox
                continue
            gap = bbox["x"] - (previous_bbox["x"] + previous_bbox["w"])
            if gap <= max(22, int(previous_bbox["w"] * 0.35)):
                current.append(item)
            else:
                if current:
                    clusters.append(current)
                current = [item]
            previous_bbox = bbox
        if current:
            clusters.append(current)
    return [cluster for cluster in clusters if cluster]


def _visual_media_card_boxes(*, image_path: str, parent_bbox: dict[str, int]) -> list[dict[str, int]]:
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return []
    source = Path(image_path)
    if not source.exists() or not parent_bbox:
        return []
    try:
        with Image.open(source) as image:
            crop = image.crop(
                (
                    parent_bbox["x"],
                    parent_bbox["y"],
                    parent_bbox["x"] + parent_bbox["w"],
                    parent_bbox["y"] + parent_bbox["h"],
                )
            ).convert("RGB")
    except Exception:
        return []
    arr = np.array(crop)
    hsv = cv2.cvtColor(arr, cv2.COLOR_RGB2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    mask = ((saturation > 35) | (value < 215)).astype("uint8") * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (9, 9))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    raw_cards: list[dict[str, int]] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if w < 90 or h < 80 or area < 9000:
            continue
        if w > parent_bbox["w"] * 0.85 or h > parent_bbox["h"] * 0.65:
            continue
        raw_cards.append({"x": parent_bbox["x"] + x, "y": parent_bbox["y"] + y, "w": w, "h": h})
    cards = _dedupe_bboxes(raw_cards, iou_threshold=0.72)
    if not cards:
        return []
    visual_cards = [_clip_media_card_at_internal_gap(arr, card, parent_bbox=parent_bbox) for card in cards]
    visual_cards = _merge_fragmented_visual_media_card_boxes(visual_cards)
    output: list[dict[str, Any]] = []
    for card in visual_cards:
        expanded = _extend_media_card_bbox(card, parent_bbox=parent_bbox, all_cards=visual_cards)
        enriched = _with_visual_media_card_bbox(expanded, visual_bbox=card)
        enriched["visual_activity_ratio"] = _visual_media_card_activity_ratio(arr, card, parent_bbox=parent_bbox)
        output.append(enriched)
    return output


def _visual_media_card_activity_ratio(arr: Any, card: dict[str, int], *, parent_bbox: dict[str, int]) -> float:
    try:
        import cv2  # type: ignore
    except Exception:
        return 0.0
    x1 = max(0, _int(card.get("x")) - _int(parent_bbox.get("x")))
    y1 = max(0, _int(card.get("y")) - _int(parent_bbox.get("y")))
    x2 = max(x1 + 1, min(arr.shape[1], x1 + _int(card.get("w"))))
    y2 = max(y1 + 1, min(arr.shape[0], y1 + _int(card.get("h"))))
    crop = arr[y1:y2, x1:x2]
    if crop.size == 0:
        return 0.0
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    active = ((saturation > 45) | (value < 210)).sum()
    return float(active) / max(1, int(crop.shape[0]) * int(crop.shape[1]))


def _extend_media_card_bbox(
    card: dict[str, int],
    *,
    parent_bbox: dict[str, int],
    all_cards: list[dict[str, int]],
) -> dict[str, int]:
    next_row_top = min(
        (other["y"] for other in all_cards if other["y"] > card["y"] + 60),
        default=parent_bbox["y"] + parent_bbox["h"],
    )
    y2 = card["y"] + card["h"]
    if y2 + 24 < next_row_top:
        y2 += 78
    y2 = min(parent_bbox["y"] + parent_bbox["h"], next_row_top - 16, y2)
    return _clip_bbox(parent_bbox, {"x": card["x"], "y": card["y"], "w": card["w"], "h": max(1, y2 - card["y"])})


def _clip_media_card_at_internal_gap(
    crop_arr: Any,
    card: dict[str, int],
    *,
    parent_bbox: dict[str, int],
) -> dict[str, int]:
    if card["h"] < 260 or card["h"] < card["w"] * 1.35:
        return card
    local_x1 = max(0, card["x"] - parent_bbox["x"])
    local_y1 = max(0, card["y"] - parent_bbox["y"])
    local_x2 = min(crop_arr.shape[1], local_x1 + card["w"])
    local_y2 = min(crop_arr.shape[0], local_y1 + card["h"])
    if local_x2 <= local_x1 or local_y2 <= local_y1:
        return card
    card_arr = crop_arr[local_y1:local_y2, local_x1:local_x2]
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return card
    hsv = cv2.cvtColor(card_arr, cv2.COLOR_RGB2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    active = ((saturation > 35) | (value < 220)).astype("uint8")
    row_activity = active.mean(axis=1)
    quiet = row_activity < 0.035
    start_search = max(80, int(card["h"] * 0.45))
    best_start = -1
    best_len = 0
    current_start = -1
    current_len = 0
    for row_index in range(start_search, len(quiet)):
        if quiet[row_index]:
            if current_start < 0:
                current_start = row_index
                current_len = 0
            current_len += 1
        else:
            if current_len > best_len:
                best_start = current_start
                best_len = current_len
            current_start = -1
            current_len = 0
    if current_len > best_len:
        best_start = current_start
        best_len = current_len
    if best_start < 0 or best_len < 28:
        return card
    clipped_h = max(1, best_start)
    if clipped_h < 120:
        return card
    return _clip_bbox(parent_bbox, {"x": card["x"], "y": card["y"], "w": card["w"], "h": clipped_h})


def _with_visual_media_card_bbox(card: dict[str, int], *, visual_bbox: dict[str, int]) -> dict[str, Any]:
    result: dict[str, Any] = dict(card)
    result["visual_bbox"] = dict(visual_bbox)
    return result


def _merge_fragmented_visual_media_card_boxes(
    card_boxes: list[dict[str, int]],
) -> list[dict[str, int]]:
    merged = [
        {key: _int(card.get(key)) for key in ("x", "y", "w", "h")}
        for card in card_boxes
        if _int(card.get("w")) > 0 and _int(card.get("h")) > 0
    ]
    median_height = _median_positive([card["h"] for card in merged])
    fragment_height_limit = median_height * 0.55 if median_height > 0 else 0
    changed = True
    while changed:
        changed = False
        output: list[dict[str, int]] = []
        consumed: set[int] = set()
        for index, card in enumerate(merged):
            if index in consumed:
                continue
            current = dict(card)
            for other_index in range(index + 1, len(merged)):
                if other_index in consumed:
                    continue
                other = merged[other_index]
                overlap_width = max(
                    0,
                    min(current["x"] + current["w"], other["x"] + other["w"])
                    - max(current["x"], other["x"]),
                )
                horizontal_overlap = overlap_width / max(1, min(current["w"], other["w"]))
                current_bottom = current["y"] + current["h"]
                other_bottom = other["y"] + other["h"]
                vertical_gap = max(current["y"] - other_bottom, other["y"] - current_bottom, 0)
                if fragment_height_limit <= 0:
                    continue
                if current["h"] > fragment_height_limit or other["h"] > fragment_height_limit:
                    continue
                if horizontal_overlap < 0.70:
                    continue
                if vertical_gap > max(24, int(max(current["h"], other["h"]) * 0.12)):
                    continue
                union = _bbox_union([current, other])
                if not union or union["w"] > max(current["w"], other["w"]) * 1.20:
                    continue
                current = union
                consumed.add(other_index)
                changed = True
            output.append(current)
        merged = output
    return sorted(merged, key=lambda box: (box["y"], box["x"]))


def _item_should_be_card_child(item: dict[str, Any], card_bbox: dict[str, int]) -> bool:
    return _media_card_child_match_score(item, card_bbox) is not None


def _best_media_card_child_index(item: dict[str, Any], card_boxes: list[dict[str, int]]) -> int | None:
    scored: list[tuple[float, int]] = []
    contained_scored: list[tuple[float, int]] = []
    item_bbox = _bbox(item.get("bbox"))
    center_x = item_bbox["x"] + item_bbox["w"] / 2 if item_bbox else None
    center_y = item_bbox["y"] + item_bbox["h"] / 2 if item_bbox else None
    for index, card_bbox in enumerate(card_boxes):
        score = _media_card_child_match_score(item, card_bbox)
        if score is not None:
            scored.append((score, index))
            visual_bbox = _media_card_visual_bbox(card_bbox)
            if (
                center_x is not None
                and center_y is not None
                and visual_bbox["x"] <= center_x <= visual_bbox["x"] + visual_bbox["w"]
                and visual_bbox["y"] <= center_y <= visual_bbox["y"] + visual_bbox["h"]
            ):
                contained_scored.append((score, index))
    if contained_scored:
        contained_scored.sort(key=lambda pair: pair[0])
        return contained_scored[0][1]
    if not scored:
        return None
    scored.sort(key=lambda pair: pair[0])
    return scored[0][1]


def _media_card_child_match_score(item: dict[str, Any], card_bbox: dict[str, int]) -> float | None:
    bbox = _bbox(item.get("bbox"))
    if not bbox:
        return None
    role = str(item.get("role") or "").casefold()
    item_type = str(item.get("item_type") or "").casefold()
    visual_bbox = _media_card_visual_bbox(card_bbox)
    if "section_title" in role:
        return None
    if _is_media_card_structural_container(role=role, item_type=item_type):
        return None
    if (
        (bbox["w"] > visual_bbox["w"] * 1.6 or bbox["h"] > visual_bbox["h"] * 1.6)
        and _bbox_overlap_ratio(visual_bbox, bbox) >= 0.8
    ):
        return None
    if role == "text" and item_type == "text" and bbox["y"] > visual_bbox["y"] + visual_bbox["h"] + 18:
        return None
    if "text" in role and bbox["h"] > max(96, int(visual_bbox["h"] * 0.45)):
        return None
    center_x = bbox["x"] + bbox["w"] / 2
    center_y = bbox["y"] + bbox["h"] / 2
    if (
        visual_bbox["x"] <= center_x <= visual_bbox["x"] + visual_bbox["w"]
        and visual_bbox["y"] <= center_y <= visual_bbox["y"] + visual_bbox["h"]
    ):
        visual_center_x = visual_bbox["x"] + visual_bbox["w"] / 2
        visual_center_y = visual_bbox["y"] + visual_bbox["h"] / 2
        return abs(center_x - visual_center_x) / max(1, visual_bbox["w"]) + abs(
            center_y - visual_center_y
        ) / max(1, visual_bbox["h"])
    if visual_bbox["w"] >= visual_bbox["h"] * 1.60 and ("text" in role or item_type in {"text", "readable"}):
        visual_right = visual_bbox["x"] + visual_bbox["w"]
        horizontal_gap = bbox["x"] - visual_right
        candidate_right = bbox["x"] + bbox["w"]
        vertical_overlap = max(
            0,
            min(visual_bbox["y"] + visual_bbox["h"], bbox["y"] + bbox["h"])
            - max(visual_bbox["y"], bbox["y"]),
        )
        if (
            -16 <= horizontal_gap <= max(72, int(visual_bbox["w"] * 0.20))
            and candidate_right <= visual_right + int(visual_bbox["w"] * 1.55)
            and vertical_overlap / max(1, bbox["h"]) >= 0.60
        ):
            return (
                0.35
                + max(0, horizontal_gap) / max(1, visual_bbox["w"])
                + abs((bbox["y"] + bbox["h"] / 2) - (visual_bbox["y"] + visual_bbox["h"] / 2))
                / max(1, visual_bbox["h"])
            )
    max_caption_gap = max(64, int(visual_bbox["h"] * 0.16))
    if bbox["y"] > visual_bbox["y"] + visual_bbox["h"] + max_caption_gap:
        return None
    if card_bbox["x"] <= center_x <= card_bbox["x"] + card_bbox["w"] and card_bbox["y"] <= center_y <= card_bbox["y"] + card_bbox["h"]:
        card_center_x = card_bbox["x"] + card_bbox["w"] / 2
        card_center_y = card_bbox["y"] + card_bbox["h"] / 2
        return abs(center_x - card_center_x) / max(1, card_bbox["w"]) + abs(center_y - card_center_y) / max(1, card_bbox["h"])
    margin_x = max(60, int(card_bbox["w"] * 0.45))
    margin_y = max(36, int(card_bbox["h"] * 0.25))
    if (
        card_bbox["x"] - margin_x <= center_x <= card_bbox["x"] + card_bbox["w"] + margin_x
        and card_bbox["y"] <= center_y <= card_bbox["y"] + card_bbox["h"] + margin_y
    ):
        dx = max(card_bbox["x"] - center_x, center_x - (card_bbox["x"] + card_bbox["w"]), 0)
        dy = max(card_bbox["y"] - center_y, center_y - (card_bbox["y"] + card_bbox["h"]), 0)
        score = 1.0 + dx / max(1, card_bbox["w"]) + dy / max(1, card_bbox["h"])
        if _horizontal_overlap_ratio(bbox, visual_bbox) >= 0.1:
            score -= 1.0
        return score
    if _bbox_overlap_ratio(bbox, card_bbox) >= 0.5:
        return 2.0
    return None


def _is_media_card_structural_container(*, role: str, item_type: str) -> bool:
    if role == "media_card":
        return False
    structural_role_tokens = (
        "content_area",
        "content_card",
        "main_content",
        "container",
        "news_card",
        "section",
        "structure_region",
    )
    if any(token in role for token in structural_role_tokens):
        return True
    if role.endswith("_card") or role == "card":
        return True
    return item_type in {"card", "container", "section", "region"}


def _item_overlaps_any_media_card(item: dict[str, Any], card_boxes: list[dict[str, int]]) -> bool:
    bbox = _bbox(item.get("bbox"))
    if not bbox:
        return False
    if _is_inter_row_section_heading(item, card_boxes):
        return False
    role = str(item.get("role") or "").casefold()
    item_type = str(item.get("item_type") or "").casefold()
    if _is_media_card_structural_container(role=role, item_type=item_type):
        return any(_bbox_overlap_ratio(bbox, _media_card_visual_bbox(card_bbox)) >= 0.2 for card_bbox in card_boxes)
    return any(_item_should_be_card_child(item, card_bbox) or _bbox_overlap_ratio(bbox, card_bbox) >= 0.5 for card_bbox in card_boxes)


def _is_inter_row_section_heading(item: dict[str, Any], card_boxes: list[dict[str, int]]) -> bool:
    bbox = _bbox(item.get("bbox"))
    if not bbox or len(card_boxes) < 2:
        return False
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    if role not in {"text", "readable", "label", "heading"} and "text" not in role:
        return False
    rows = _media_card_rows(card_boxes)
    if len(rows) < 2:
        return False
    for previous_row, next_row in zip(rows, rows[1:]):
        previous_bottom = max(_media_card_visual_bbox(card)["y"] + _media_card_visual_bbox(card)["h"] for card in previous_row)
        next_top = min(_media_card_visual_bbox(card)["y"] for card in next_row)
        if next_top - previous_bottom < 48:
            continue
        if bbox["y"] >= previous_bottom + 18 and bbox["y"] + bbox["h"] <= next_top - 4:
            return True
    return False


def _media_card_rows(card_boxes: list[dict[str, int]]) -> list[list[dict[str, int]]]:
    rows: list[list[dict[str, int]]] = []
    for card in sorted(card_boxes, key=lambda box: (_media_card_visual_bbox(box)["y"], _media_card_visual_bbox(box)["x"])):
        visual = _media_card_visual_bbox(card)
        matched = False
        for row in rows:
            row_visuals = [_media_card_visual_bbox(item) for item in row]
            row_y = min(item["y"] for item in row_visuals)
            row_bottom = max(item["y"] + item["h"] for item in row_visuals)
            overlap_height = max(
                0,
                min(visual["y"] + visual["h"], row_bottom) - max(visual["y"], row_y),
            )
            row_height = max(1, row_bottom - row_y)
            vertical_overlap = overlap_height / max(1, min(visual["h"], row_height))
            if abs(visual["y"] - row_y) <= 72 or vertical_overlap >= 0.65:
                row.append(card)
                matched = True
                break
        if not matched:
            rows.append([card])
    return rows


def _media_card_visual_bbox(card_bbox: dict[str, Any]) -> dict[str, int]:
    visual = _bbox(card_bbox.get("visual_bbox")) if isinstance(card_bbox.get("visual_bbox"), dict) else None
    if visual:
        return visual
    return {key: _int(card_bbox.get(key)) for key in ("x", "y", "w", "h")}


def _media_card_bbox_with_children(
    card_bbox: dict[str, int],
    child_items: list[dict[str, Any]],
    *,
    parent_bbox: dict[str, int],
) -> dict[str, int]:
    inferred_slot_bbox = (
        _bbox(card_bbox.get("inferred_slot_bbox")) if isinstance(card_bbox.get("inferred_slot_bbox"), dict) else None
    )
    visual_bbox = _bbox(card_bbox.get("visual_bbox")) if isinstance(card_bbox.get("visual_bbox"), dict) else None
    base_bbox = inferred_slot_bbox or visual_bbox or {key: _int(card_bbox.get(key)) for key in ("x", "y", "w", "h")}
    if inferred_slot_bbox is None:
        base_bbox = _authoritative_media_card_parent_bbox(base_bbox, child_items) or base_bbox
    child_boxes = [_bbox(item.get("bbox")) for item in child_items]
    child_boxes = [box for box in child_boxes if box]
    if not child_boxes:
        return _clip_bbox(parent_bbox, base_bbox)
    union = _bbox_union([base_bbox, *child_boxes])
    return _clip_bbox(parent_bbox, union or base_bbox)


def _authoritative_media_card_parent_bbox(
    visual_bbox: dict[str, int],
    child_items: list[dict[str, Any]],
) -> dict[str, int] | None:
    visual_area = max(1, visual_bbox["w"] * visual_bbox["h"])
    candidates: list[dict[str, int]] = []
    for item in child_items:
        role = str(item.get("role") or "").casefold()
        item_type = str(item.get("item_type") or "").casefold()
        candidate_bbox = _bbox(item.get("bbox"))
        if not candidate_bbox or item_type != "actionable" or role in {"text", "icon", "image"}:
            continue
        candidate_area = candidate_bbox["w"] * candidate_bbox["h"]
        area_ratio = candidate_area / visual_area
        if not 0.55 <= area_ratio <= 1.15:
            continue
        if _bbox_overlap_ratio(visual_bbox, candidate_bbox) < 0.75:
            continue
        if _bbox_overlap_ratio(candidate_bbox, visual_bbox) < 0.75:
            continue
        content_boxes = [
            box
            for child in child_items
            if child is not item
            if (box := _bbox(child.get("bbox"))) is not None
        ]
        if content_boxes and any(_bbox_overlap_ratio(box, candidate_bbox) < 0.9 for box in content_boxes):
            continue
        candidates.append(candidate_bbox)
    if not candidates:
        return None
    return min(candidates, key=lambda bbox: (bbox["w"] * bbox["h"], bbox["y"], bbox["x"]))


def _bbox_overlap_ratio(bbox: dict[str, int], parent_bbox: dict[str, int]) -> float:
    x1 = max(bbox["x"], parent_bbox["x"])
    y1 = max(bbox["y"], parent_bbox["y"])
    x2 = min(bbox["x"] + bbox["w"], parent_bbox["x"] + parent_bbox["w"])
    y2 = min(bbox["y"] + bbox["h"], parent_bbox["y"] + parent_bbox["h"])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    return intersection / max(1, bbox["w"] * bbox["h"])


def _media_card_label(child_items: list[dict[str, Any]], *, fallback: str) -> str:
    candidates = [
        str(item.get("label") or "").strip()
        for item in sorted(child_items, key=lambda item: (_bbox_top(item), -(_bbox(item.get("bbox")) or {}).get("h", 0)))
        if str(item.get("label") or "").strip()
    ]
    for label in candidates:
        if len(label) >= 2 and not label.isdigit():
            return label
    return candidates[0] if candidates else fallback


def _child_from_numbered_item(item: dict[str, Any]) -> dict[str, Any]:
    bbox = _bbox(item.get("bbox"))
    label = str(item.get("label") or "").strip()
    if not bbox and not label:
        return {}
    child_id = str(item.get("item_id") or item.get("number") or "")
    child = {
        "child_id": child_id,
        "item_id": child_id,
        "label": label,
        "role": str(item.get("role") or "text"),
        "bbox": bbox or {},
    }
    nested_children = item.get("children") if isinstance(item.get("children"), list) else []
    if nested_children:
        child["children"] = deepcopy(nested_children)
    return child


def _looks_like_card_item(item: dict[str, Any]) -> bool:
    role = str(item.get("role") or "").casefold()
    if role in {"message_card", "message_card_content", "message_bubble", "image_message"}:
        return False
    if _message_child_role(item, chat_context=True) in {"message_card", "message_bubble", "image_message"}:
        return False
    item_id = str(item.get("item_id") or "").casefold()
    label = str(item.get("label") or "").casefold()
    return "card" in role or "card" in item_id or "card" in label or role in {"news_card", "recommendation_item", "content_card"}


def _group_card_items_by_row(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    rows: list[list[dict[str, Any]]] = []
    for item in sorted(items, key=lambda entry: (_bbox_center_y(entry), _bbox_left(entry))):
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            continue
        center_y = bbox["y"] + bbox["h"] / 2
        target_row: list[dict[str, Any]] | None = None
        for row in rows:
            row_boxes = [_bbox(existing.get("bbox")) for existing in row]
            row_boxes = [box for box in row_boxes if box]
            if not row_boxes:
                continue
            row_center = sum(box["y"] + box["h"] / 2 for box in row_boxes) / len(row_boxes)
            row_height = sum(box["h"] for box in row_boxes) / len(row_boxes)
            if abs(center_y - row_center) <= max(45, row_height * 0.35):
                target_row = row
                break
        if target_row is None:
            rows.append([item])
        else:
            target_row.append(item)
    return rows


def _bbox_center_y(item: dict[str, Any]) -> float:
    bbox = _bbox(item.get("bbox"))
    if not bbox:
        return 0.0
    return bbox["y"] + bbox["h"] / 2


def _refine_direct_region_small_controls(
    numbered_items: list[dict[str, Any]],
    *,
    image_path: str,
    region_bbox: dict[str, int],
    region_family: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    initial_model_item_count = len(numbered_items)
    classic_menu_report = {
        "applied": False,
        "reason": "not_topbar_direct_region",
        "menu_item_count": 0,
    }
    if region_family == "top_bar" and region_bbox:
        numbered_items, classic_menu_report = _normalize_classic_menu_bar_items(
            numbered_items,
            region_bbox=region_bbox,
        )
    if not image_path or not region_bbox:
        items, direct_bar_report = _normalize_direct_bar_items(
            numbered_items,
            region_bbox=region_bbox,
            region_family=region_family,
            image_path=image_path,
            reason="missing_image_or_region_bbox",
        )
        return items, {
            "applied": _direct_refinement_applied(False, direct_bar_report),
            "reason": _direct_refinement_reason("missing_image_or_region_bbox", direct_bar_report),
            "candidate_count": 0,
            "model_item_count": len(numbered_items),
            "classic_menu_ocr_anchor": classic_menu_report,
            **direct_bar_report,
        }
    detection_bbox = _direct_region_control_detection_bbox(region_bbox)
    candidates = _visual_small_control_boxes(image_path=image_path, parent_bbox=detection_bbox)
    leading_edge_candidates: list[dict[str, int]] = []
    if detection_bbox["x"] > region_bbox["x"]:
        leading_edge_width = min(
            region_bbox["w"],
            max(detection_bbox["x"] - region_bbox["x"], 96),
        )
        leading_edge_bbox = {
            "x": region_bbox["x"],
            "y": region_bbox["y"],
            "w": leading_edge_width,
            "h": region_bbox["h"],
        }
        leading_edge_candidates = _visual_small_control_boxes(
            image_path=image_path,
            parent_bbox=leading_edge_bbox,
        )
        candidates = _dedupe_bboxes([*candidates, *leading_edge_candidates], iou_threshold=0.72)
    compile_visual_candidates = region_family in {"", "left_bar", "right_bar", "top_bar", "bottom_bar"}
    if not compile_visual_candidates:
        items, direct_bar_report = _normalize_direct_bar_items(
            numbered_items,
            region_bbox=region_bbox,
            region_family=region_family,
            image_path=image_path,
            reason="non_bar_visual_candidates_preserved_as_evidence",
        )
        return items, {
            "applied": _direct_refinement_applied(False, direct_bar_report),
            "reason": _direct_refinement_reason(
                "non_bar_visual_candidates_preserved_as_evidence",
                direct_bar_report,
            ),
            "candidate_count": len(candidates),
            "model_item_count": initial_model_item_count,
            "leading_edge_candidate_count": len(leading_edge_candidates),
            "unmatched_visual_candidate_count": len(candidates),
            "uncompiled_visual_candidate_count": len(candidates),
            "candidate_compilation_status": "evidence_only",
            "evidence_only_visual_candidates": [dict(candidate) for candidate in candidates],
            "classic_menu_ocr_anchor": classic_menu_report,
            **direct_bar_report,
        }
    numbered_items, unmatched_visual_candidate_count = _append_unmatched_direct_visual_controls(
        numbered_items,
        candidates,
        region_family=region_family,
    )
    candidate_coverage_report = {
        "leading_edge_candidate_count": len(leading_edge_candidates),
        "unmatched_visual_candidate_count": unmatched_visual_candidate_count,
        "uncompiled_visual_candidate_count": 0,
        "candidate_compilation_status": "compiled_atomic_controls",
        "evidence_only_visual_candidates": [],
        "classic_menu_ocr_anchor": classic_menu_report,
    }
    if len(candidates) >= max(6, initial_model_item_count * 2):
        synthesized = _synthesize_direct_visual_controls(numbered_items, candidates, fallback_region_bbox=region_bbox)
        synthesized, direct_bar_report = _normalize_direct_bar_items(
            synthesized,
            region_bbox=region_bbox,
            region_family=region_family,
            image_path=image_path,
            reason="visual_candidates_replace_sparse_text_inventory",
        )
        return synthesized, {
            "applied": True,
            "reason": "visual_candidates_replace_sparse_text_inventory",
            "candidate_count": len(candidates),
            "model_item_count": initial_model_item_count,
            "refined_count": len(synthesized),
            "avg_model_visual_iou": 0.0,
            "low_overlap_count": len(synthesized),
            "orientation": "horizontal" if _is_horizontal_region(region_bbox) else "vertical",
            **direct_bar_report,
            **candidate_coverage_report,
            "pairs": [
                {
                    "number": item.get("number"),
                    "label": item.get("label"),
                    "to": item.get("bbox"),
                }
                for item in synthesized
            ],
        }
    if len(candidates) < max(3, int(len(numbered_items) * 0.55)):
        items, direct_bar_report = _normalize_direct_bar_items(
            numbered_items,
            region_bbox=region_bbox,
            region_family=region_family,
            image_path=image_path,
            reason="insufficient_visual_candidates",
        )
        return items, {
            "applied": _direct_refinement_applied(False, direct_bar_report),
            "reason": _direct_refinement_reason("insufficient_visual_candidates", direct_bar_report),
            "candidate_count": len(candidates),
            "model_item_count": initial_model_item_count,
            **direct_bar_report,
            **candidate_coverage_report,
        }
    if len(numbered_items) < 3:
        items, direct_bar_report = _normalize_direct_bar_items(
            numbered_items,
            region_bbox=region_bbox,
            region_family=region_family,
            image_path=image_path,
            reason="too_few_model_items",
        )
        return items, {
            "applied": _direct_refinement_applied(False, direct_bar_report),
            "reason": _direct_refinement_reason("too_few_model_items", direct_bar_report),
            "candidate_count": len(candidates),
            "model_item_count": initial_model_item_count,
            **direct_bar_report,
            **candidate_coverage_report,
        }
    overlaps = [
        max((_iou(_bbox(item.get("bbox")) or {"x": 0, "y": 0, "w": 1, "h": 1}, candidate) for candidate in candidates), default=0.0)
        for item in numbered_items
    ]
    avg_overlap = sum(overlaps) / max(1, len(overlaps))
    low_overlap_count = sum(1 for value in overlaps if value < 0.08)
    if avg_overlap >= 0.16 and low_overlap_count < len(numbered_items) * 0.45:
        items, direct_bar_report = _normalize_direct_bar_items(
            numbered_items,
            region_bbox=region_bbox,
            region_family=region_family,
            image_path=image_path,
            reason="model_boxes_already_overlap_visual_candidates",
        )
        return items, {
            "applied": _direct_refinement_applied(False, direct_bar_report),
            "reason": _direct_refinement_reason("model_boxes_already_overlap_visual_candidates", direct_bar_report),
            "candidate_count": len(candidates),
            "model_item_count": initial_model_item_count,
            "avg_model_visual_iou": avg_overlap,
            "low_overlap_count": low_overlap_count,
            **direct_bar_report,
            **candidate_coverage_report,
        }
    horizontal = region_bbox["w"] >= region_bbox["h"] * 2.5
    sorted_items = sorted(
        [deepcopy(item) for item in numbered_items],
        key=lambda item: ((_bbox_left(item), _bbox_top(item)) if horizontal else (_bbox_top(item), _bbox_left(item))),
    )
    refined_by_number: dict[str, dict[str, Any]] = {}
    pairs: list[dict[str, Any]] = []
    available_candidates = [dict(candidate) for candidate in candidates]
    for item in sorted_items:
        old_bbox = _bbox(item.get("bbox"))
        if not old_bbox or not _direct_item_accepts_visual_hit_area_refinement(item):
            continue
        candidate = _nearest_compatible_direct_visual_candidate(
            old_bbox,
            available_candidates,
            horizontal=horizontal,
        )
        if candidate is None:
            continue
        available_candidates.remove(candidate)
        item["bbox"] = candidate
        item["bbox_refinement"] = {
            "source": "visual_small_control_segmenter",
            "previous_bbox": old_bbox,
            "reason": "model_bbox_low_overlap_with_visual_control_candidate",
        }
        refined_by_number[str(item.get("number") or "")] = item
        pairs.append({"number": item.get("number"), "label": item.get("label"), "from": old_bbox, "to": candidate})
    refined = [refined_by_number.get(str(item.get("number") or ""), item) for item in numbered_items]
    refined = _renumber_stage2_items(refined, horizontal=horizontal)
    refined, direct_bar_report = _normalize_direct_bar_items(
        refined,
        region_bbox=region_bbox,
        region_family=region_family,
        image_path=image_path,
        reason="model_boxes_low_overlap_with_visual_candidates",
    )
    return refined, {
        "applied": _direct_refinement_applied(bool(pairs), direct_bar_report),
        "reason": _direct_refinement_reason(
            "model_boxes_low_overlap_with_visual_candidates" if pairs else "no_pairs_applied",
            direct_bar_report,
        ),
        "candidate_count": len(candidates),
        "model_item_count": initial_model_item_count,
        "refined_count": len(pairs),
        "avg_model_visual_iou": avg_overlap,
        "low_overlap_count": low_overlap_count,
        "orientation": "horizontal" if horizontal else "vertical",
        **direct_bar_report,
        **candidate_coverage_report,
        "pairs": pairs,
    }


def _refine_primary_embedded_top_controls(
    numbered_items: list[dict[str, Any]],
    *,
    image_path: str,
    region_bbox: dict[str, int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """从顶端起始的主区中恢复视觉顶控件带，不把普通内容行误当顶栏。"""

    base_report = {
        "contract_version": "learn_embedded_top_control_strip_v1",
        "applied": False,
        "candidate_count": 0,
        "recovered_control_count": 0,
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    if not image_path or not region_bbox:
        return numbered_items, {**base_report, "reason": "missing_image_or_region_bbox"}
    top_origin_tolerance = max(8, min(24, int(round(region_bbox["h"] * 0.015))))
    if region_bbox["y"] > top_origin_tolerance:
        return numbered_items, {**base_report, "reason": "primary_region_does_not_start_at_window_top"}

    search_height = min(region_bbox["h"], max(80, min(180, int(round(region_bbox["h"] * 0.18)))))
    search_bbox = {**region_bbox, "h": search_height}
    candidates = _visual_small_control_boxes(image_path=image_path, parent_bbox=search_bbox)
    if len(candidates) < 4:
        return numbered_items, {
            **base_report,
            "reason": "insufficient_top_visual_controls",
            "candidate_count": len(candidates),
        }

    candidate_items = [
        {"item_id": f"embedded_top_candidate_{index}", "role": "control", "bbox": bbox}
        for index, bbox in enumerate(candidates, start=1)
    ]
    rows = _cluster_topbar_controls_by_horizontal_band(candidate_items, region_bbox=search_bbox)
    eligible_rows: list[tuple[int, dict[str, int], list[dict[str, Any]]]] = []
    for row in rows:
        row_bbox = _bbox_union([item.get("bbox") for item in row])
        if not row_bbox or len(row) < 4:
            continue
        horizontal_span_ratio = row_bbox["w"] / max(1, region_bbox["w"])
        row_bottom = row_bbox["y"] + row_bbox["h"]
        maximum_row_bottom = region_bbox["y"] + max(72, int(round(region_bbox["h"] * 0.12)))
        if horizontal_span_ratio < 0.35 or row_bottom > maximum_row_bottom:
            continue
        eligible_rows.append((row_bbox["y"], row_bbox, row))
    if not eligible_rows:
        return numbered_items, {
            **base_report,
            "reason": "no_dense_wide_top_control_row",
            "candidate_count": len(candidates),
            "row_count": len(rows),
        }

    _, row_bbox, row = min(eligible_rows, key=lambda entry: (entry[0], -len(entry[2])))
    strip_bottom = min(
        region_bbox["y"] + region_bbox["h"],
        row_bbox["y"] + row_bbox["h"] + max(8, int(round(row_bbox["h"] * 0.25))),
    )
    strip_bbox = {
        "x": region_bbox["x"],
        "y": region_bbox["y"],
        "w": region_bbox["w"],
        "h": max(1, strip_bottom - region_bbox["y"]),
    }
    top_items: list[dict[str, Any]] = []
    remaining_items: list[dict[str, Any]] = []
    for item in numbered_items:
        bbox = _bbox(item.get("bbox"))
        center_y = bbox["y"] + bbox["h"] / 2 if bbox else float("inf")
        if bbox and center_y <= strip_bbox["y"] + strip_bbox["h"]:
            top_items.append(item)
        else:
            remaining_items.append(item)
    refined_top, direct_report = _refine_direct_region_small_controls(
        top_items,
        image_path=image_path,
        region_bbox=strip_bbox,
        region_family="top_bar",
    )
    normalized_top: list[dict[str, Any]] = []
    for item in refined_top:
        normalized_top.append(
            {
                **item,
                "source": "embedded_top_control_visual_segmenter",
                "embedded_top_control_strip": True,
            }
        )
    combined = _renumber_stage2_items([*normalized_top, *remaining_items], horizontal=False)
    return combined, {
        **base_report,
        "applied": bool(normalized_top),
        "reason": "dense_wide_top_control_row_recovered" if normalized_top else "top_control_refinement_empty",
        "candidate_count": len(candidates),
        "eligible_row_control_count": len(row),
        "recovered_control_count": len(normalized_top),
        "strip_bbox": strip_bbox,
        "row_bbox": row_bbox,
        "direct_refinement": direct_report,
    }


def _direct_item_accepts_visual_hit_area_refinement(item: dict[str, Any]) -> bool:
    role = str(item.get("role") or "").strip().casefold().replace(" ", "_")
    item_type = str(item.get("item_type") or "").strip().casefold().replace(" ", "_")
    if role in {
        "text",
        "readable",
        "label",
        "menu_bar_evidence",
        "status_bar_evidence",
        "bottom_bar_evidence",
        "title_bar",
    }:
        return False
    return bool(
        item_type in {"actionable", "button", "visual_control", "control"}
        or any(token in role for token in ("button", "control", "menu_item", "nav_item", "tab"))
    )


def _nearest_compatible_direct_visual_candidate(
    item_bbox: dict[str, int],
    candidates: list[dict[str, int]],
    *,
    horizontal: bool,
) -> dict[str, int] | None:
    item_cx = item_bbox["x"] + item_bbox["w"] / 2
    item_cy = item_bbox["y"] + item_bbox["h"] / 2
    scored: list[tuple[float, dict[str, int]]] = []
    for candidate in candidates:
        candidate_cx = candidate["x"] + candidate["w"] / 2
        candidate_cy = candidate["y"] + candidate["h"] / 2
        x_gap = max(
            0,
            max(item_bbox["x"], candidate["x"])
            - min(item_bbox["x"] + item_bbox["w"], candidate["x"] + candidate["w"]),
        )
        y_gap = max(
            0,
            max(item_bbox["y"], candidate["y"])
            - min(item_bbox["y"] + item_bbox["h"], candidate["y"] + candidate["h"]),
        )
        if horizontal:
            cross_overlap = max(
                0,
                min(item_bbox["y"] + item_bbox["h"], candidate["y"] + candidate["h"])
                - max(item_bbox["y"], candidate["y"]),
            )
            cross_overlap_ratio = cross_overlap / max(1, min(item_bbox["h"], candidate["h"]))
            cross_axis_limit = max(2, int(round(min(item_bbox["h"], candidate["h"]) * 0.08)))
            primary_axis_limit = max(360, int(round(max(item_bbox["w"], candidate["w"]) * 3.0)))
            if cross_overlap_ratio < 0.3 or y_gap > cross_axis_limit or x_gap > primary_axis_limit:
                continue
        else:
            cross_overlap = max(
                0,
                min(item_bbox["x"] + item_bbox["w"], candidate["x"] + candidate["w"])
                - max(item_bbox["x"], candidate["x"]),
            )
            cross_overlap_ratio = cross_overlap / max(1, min(item_bbox["w"], candidate["w"]))
            cross_axis_limit = max(2, int(round(min(item_bbox["w"], candidate["w"]) * 0.08)))
            primary_axis_limit = max(360, int(round(max(item_bbox["h"], candidate["h"]) * 3.0)))
            if cross_overlap_ratio < 0.3 or x_gap > cross_axis_limit or y_gap > primary_axis_limit:
                continue
        center_distance = ((item_cx - candidate_cx) ** 2 + (item_cy - candidate_cy) ** 2) ** 0.5
        overlap = _iou(item_bbox, candidate)
        containment = max(_bbox_overlap_ratio(item_bbox, candidate), _bbox_overlap_ratio(candidate, item_bbox))
        score = overlap * 3.0 + containment * 1.5 - center_distance / max(1.0, max(item_bbox["w"], item_bbox["h"]))
        scored.append((score, candidate))
    if not scored:
        return None
    return max(scored, key=lambda entry: entry[0])[1]


def _append_unmatched_direct_visual_controls(
    numbered_items: list[dict[str, Any]],
    candidates: list[dict[str, int]],
    *,
    region_family: str,
) -> tuple[list[dict[str, Any]], int]:
    existing = [deepcopy(item) for item in numbered_items]
    role = "nav_item" if region_family in {"left_bar", "right_bar"} else "control"
    consumed_candidate_indexes: set[int] = set()
    for candidate_index, candidate in enumerate(candidates):
        if candidate["w"] > 128 or candidate["h"] > 96:
            continue
        covered_by_control = False
        for item in existing:
            item_bbox = _bbox(item.get("bbox"))
            if not item_bbox or not _direct_item_can_claim_visual_candidate(item, candidate):
                continue
            if (
                _bbox_overlap_ratio(candidate, item_bbox) >= 0.45
                or _bbox_overlap_ratio(item_bbox, candidate) >= 0.45
            ):
                covered_by_control = True
                break
        if covered_by_control:
            continue

        scored_labels: list[tuple[float, int, dict[str, int]]] = []
        for item_index, item in enumerate(existing):
            item_bbox = _bbox(item.get("bbox"))
            if not item_bbox:
                continue
            item_role = str(item.get("role") or "").strip().lower()
            item_type = str(item.get("item_type") or "").strip().lower()
            item_source = str(item.get("source") or "").strip().lower()
            item_id = str(item.get("item_id") or "").strip().lower()
            if item_role not in {"text", "label"} and item_type != "readable":
                continue
            if "ocr" not in item_source and not item_id.startswith("ocr_"):
                continue
            overlap_x = max(
                0,
                min(candidate["x"] + candidate["w"], item_bbox["x"] + item_bbox["w"])
                - max(candidate["x"], item_bbox["x"]),
            )
            overlap_y = max(
                0,
                min(candidate["y"] + candidate["h"], item_bbox["y"] + item_bbox["h"])
                - max(candidate["y"], item_bbox["y"]),
            )
            x_overlap_ratio = overlap_x / max(1, min(candidate["w"], item_bbox["w"]))
            y_overlap_ratio = overlap_y / max(1, min(candidate["h"], item_bbox["h"]))
            x_gap = max(
                0,
                max(candidate["x"], item_bbox["x"])
                - min(candidate["x"] + candidate["w"], item_bbox["x"] + item_bbox["w"]),
            )
            if y_overlap_ratio < 0.45 or (x_overlap_ratio < 0.35 and x_gap > 6):
                continue
            union = _bbox_union([candidate, item_bbox])
            if not union:
                continue
            if union["w"] > max(candidate["w"] + 48, int(round(candidate["w"] * 1.6))):
                continue
            if union["h"] > max(candidate["h"] + 24, int(round(candidate["h"] * 1.35))):
                continue
            center_distance = abs(
                (candidate["x"] + candidate["w"] / 2) - (item_bbox["x"] + item_bbox["w"] / 2)
            )
            score = y_overlap_ratio * 2.0 + x_overlap_ratio - center_distance / max(1, candidate["w"])
            scored_labels.append((score, item_index, union))
        if not scored_labels:
            continue

        _, item_index, union = max(scored_labels, key=lambda entry: entry[0])
        label_item = deepcopy(existing[item_index])
        label_item_id = str(label_item.get("item_id") or f"ocr_label_{candidate_index + 1}")
        existing[item_index] = {
            **existing[item_index],
            "item_id": f"visual_control_with_ocr_label_{label_item_id}",
            "role": role,
            "item_type": "visual_control",
            "bbox": union,
            "click_point": {},
            "children": [label_item],
            "review_only": True,
            "stage": "stage2_region_numbering",
            "source": "visual_control_with_ocr_label",
            "source_label_item_id": label_item_id,
            "bbox_policy": "visual_control_parent_with_ocr_label",
            "calibration_target_kind": "atomic_control_parent",
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
        consumed_candidate_indexes.add(candidate_index)

    unmatched: list[dict[str, int]] = []
    for candidate_index, candidate in enumerate(candidates):
        if candidate_index in consumed_candidate_indexes:
            continue
        center_x = candidate["x"] + candidate["w"] / 2
        center_y = candidate["y"] + candidate["h"] / 2
        matched = any(
            (
                item_bbox["x"] <= center_x <= item_bbox["x"] + item_bbox["w"]
                and item_bbox["y"] <= center_y <= item_bbox["y"] + item_bbox["h"]
            )
            or _bbox_overlap_ratio(candidate, item_bbox) >= 0.45
            or _bbox_overlap_ratio(item_bbox, candidate) >= 0.45
            for item in existing
            if (item_bbox := _bbox(item.get("bbox"))) is not None
            and _direct_item_can_claim_visual_candidate(item, candidate)
        )
        if not matched:
            unmatched.append(candidate)
    if not unmatched:
        return existing, 0
    region_no = str(existing[0].get("number") or "1").split(".", 1)[0] if existing else "1"
    for index, candidate in enumerate(unmatched, start=1):
        existing.append(
            {
                "contract_version": "learn_stage2_numbered_item_v1",
                "number": f"{region_no}.{len(existing) + 1}",
                "item_id": f"unmatched_visual_control_{region_no}_{index}",
                "label": f"visual control {index}",
                "role": role,
                "item_type": "visual_control",
                "bbox": dict(candidate),
                "click_point": {},
                "children": [],
                "review_only": True,
                "stage": "stage2_region_numbering",
                "source": "visual_small_control_unmatched_candidate",
                "calibration_target_kind": "atomic_control_parent",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    return existing, len(unmatched)


def _direct_item_can_claim_visual_candidate(
    item: dict[str, Any],
    candidate: dict[str, int],
) -> bool:
    """只允许原子控件证据认领视觉候选，语义容器不得提前建立归属。"""
    item_bbox = _bbox(item.get("bbox"))
    if not item_bbox:
        return False
    role = str(item.get("role") or "").strip().casefold()
    item_type = str(item.get("item_type") or "").strip().casefold()
    source = str(item.get("source") or "").strip().casefold()
    evidence_level = str(item.get("evidence_level") or "").strip().casefold()
    if role in {"text", "label"} or item_type == "readable":
        return False
    if evidence_level == "semantic_region_only" or item_type in {"container", "group", "region"}:
        return False
    if "semantic_proposal" in source or "semantic_region" in source:
        return False

    candidate_area = max(1, candidate["w"] * candidate["h"])
    item_area = max(1, item_bbox["w"] * item_bbox["h"])
    scale_mismatch = (
        item_area > candidate_area * 8
        and (
            item_bbox["w"] > candidate["w"] * 3
            or item_bbox["h"] > candidate["h"] * 3
        )
    )
    return not scale_mismatch


def _expand_ownership_source_aliases(
    numbered_items: list[dict[str, Any]],
    ownership_audit: dict[str, Any],
) -> dict[str, Any]:
    """把去重前的来源 ID 绑定到同一个唯一 owner，不恢复重复显示框。"""

    audit = deepcopy(ownership_audit) if isinstance(ownership_audit, dict) else {}
    owner_map = dict(audit.get("source_item_owner_map") or {})
    alias_map: dict[str, str] = {}
    alias_owner_count = 0
    for item in numbered_items:
        if not isinstance(item, dict):
            continue
        winner_id = str(item.get("item_id") or "").strip()
        owner_id = str(owner_map.get(winner_id) or "").strip()
        if not winner_id:
            continue
        for source_id in item.get("merged_source_item_ids", []) if isinstance(item.get("merged_source_item_ids"), list) else []:
            source_id = str(source_id or "").strip()
            if not source_id or source_id == winner_id:
                continue
            alias_map[source_id] = winner_id
            if owner_id and source_id not in owner_map:
                owner_map[source_id] = owner_id
                alias_owner_count += 1
    audit["source_item_owner_map"] = owner_map
    audit["source_item_alias_map"] = alias_map
    audit["source_alias_owner_count"] = alias_owner_count
    return audit


def _build_stage2_dual_streams(
    *,
    numbered_items: list[dict[str, Any]],
    semantic_groups: list[dict[str, Any]],
    ownership_audit: dict[str, Any] | None = None,
    visual_candidates: list[dict[str, int]] | None = None,
    control_parents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """把事实对象、语义解释和归属关系分开保存，防止容器删除带走原子证据。"""
    owner_map = (
        ownership_audit.get("source_item_owner_map")
        if isinstance(ownership_audit, dict) and isinstance(ownership_audit.get("source_item_owner_map"), dict)
        else {}
    )
    groups = [deepcopy(group) for group in semantic_groups if isinstance(group, dict)]
    atomic_parents = [
        deepcopy(parent)
        for parent in control_parents or []
        if isinstance(parent, dict)
        and str(parent.get("object_id") or "").strip()
        and _bbox(parent.get("bbox"))
    ]
    group_ids = {
        str(group.get("group_id") or "").strip()
        for group in groups
        if str(group.get("group_id") or "").strip()
    }
    visual_objects: list[dict[str, Any]] = []
    associations: list[dict[str, Any]] = []
    for item in numbered_items:
        if not isinstance(item, dict):
            continue
        object_id = str(item.get("item_id") or "").strip()
        bbox = _bbox(item.get("bbox"))
        if not object_id or not bbox:
            continue
        if _is_stage2_semantic_container_item(item):
            if object_id not in group_ids:
                groups.append(
                    {
                        "group_id": object_id,
                        "label": str(item.get("label") or object_id),
                        "role": str(item.get("role") or "semantic_group"),
                        "bbox": bbox,
                        "member_item_ids": [],
                        "source": str(item.get("source") or "semantic_numbered_item"),
                        "display_only": True,
                        "execute_binding_enabled": False,
                    }
                )
                group_ids.add(object_id)
            continue

        owner_id = str(owner_map.get(object_id) or "").strip()
        rejected = bool(item.get("explicitly_rejected")) or str(item.get("candidate_disposition") or "") == (
            "explicitly_rejected"
        )
        disposition = "associated" if owner_id in group_ids else ("explicitly_rejected" if rejected else "review_only")
        visual_objects.append(
            {
                "object_id": object_id,
                "label": str(item.get("label") or ""),
                "role": str(item.get("role") or "review_only"),
                "item_type": str(item.get("item_type") or ""),
                "bbox": bbox,
                "source": str(item.get("source") or ""),
                "disposition": disposition,
                "display_only": True,
                "execute_binding_enabled": False,
            }
        )
        if disposition == "associated":
            associations.append(
                {
                    "object_id": object_id,
                    "semantic_group_id": owner_id,
                    "relationship": "member_of",
                    "source": "resolved_group_ownership",
                }
            )

    existing_object_ids = {str(item.get("object_id") or "") for item in visual_objects}
    for index, candidate in enumerate(visual_candidates or [], start=1):
        bbox = _bbox(candidate)
        object_id = f"raw_visual_candidate_{index}"
        if not bbox or object_id in existing_object_ids:
            continue
        visual_objects.append(
            {
                "object_id": object_id,
                "label": f"visual candidate {index}",
                "role": "visual_candidate",
                "item_type": "visual_candidate",
                "bbox": bbox,
                "source": "visual_small_control_candidate_stream",
                "disposition": "review_only",
                "display_only": True,
                "execute_binding_enabled": False,
            }
        )
        existing_object_ids.add(object_id)

    associated_count = sum(item["disposition"] == "associated" for item in visual_objects)
    review_only_count = sum(item["disposition"] == "review_only" for item in visual_objects)
    rejected_count = sum(item["disposition"] == "explicitly_rejected" for item in visual_objects)
    control_associations = [
        {
            "object_id": str(member_id),
            "control_parent_id": str(parent.get("object_id") or ""),
            "relationship": "evidence_for_control_parent",
            "source": "atomic_control_parent_synthesis",
        }
        for parent in atomic_parents
        for member_id in parent.get("member_object_ids", [])
        if str(member_id or "").strip()
    ]
    return {
        "contract_version": "learn_stage2_dual_streams_v1",
        "visual_objects": visual_objects,
        "control_parents": atomic_parents,
        "semantic_groups": groups,
        "associations": associations,
        "control_associations": control_associations,
        "integrity": {
            "visual_object_count": len(visual_objects),
            "semantic_group_count": len(groups),
            "control_parent_count": len(atomic_parents),
            "associated_count": associated_count,
            "review_only_count": review_only_count,
            "explicitly_rejected_count": rejected_count,
            "silent_loss_count": max(
                0,
                len(visual_objects) - associated_count - review_only_count - rejected_count,
            ),
        },
        "interpretation": (
            "visual objects are factual evidence; semantic groups are interpretation; "
            "associations are established only after both streams exist"
        ),
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _atomic_control_parent_objects(
    *,
    numbered_items: list[dict[str, Any]],
    visual_candidates: list[dict[str, int]] | None,
    region_bbox: dict[str, int],
    region_family: str = "",
) -> list[dict[str, Any]]:
    """从事实点击区或有内部证据的视觉边界合成完整控件父框。"""
    if region_family in {"left_bar", "right_bar", "top_bar", "bottom_bar"}:
        return []
    parent_bbox = _bbox(region_bbox)
    if not parent_bbox:
        return []

    candidates = [item for item in numbered_items if _is_atomic_control_hit_area(item, parent_bbox)]
    candidates.sort(key=lambda item: (_bbox_top(item), _bbox_left(item), str(item.get("item_id") or "")))
    accepted_hit_areas: list[dict[str, int]] = []
    parents: list[dict[str, Any]] = []
    claimed_evidence_ids: set[str] = set()
    for item in candidates:
        bbox = _bbox(item.get("bbox"))
        item_id = str(item.get("item_id") or "").strip()
        if not bbox or not item_id:
            continue
        if any(_iou(bbox, existing) >= 0.9 for existing in accepted_hit_areas):
            continue
        child_items = _atomic_control_child_evidence(numbered_items, bbox, exclude_item_id=item_id)
        member_ids = [item_id, *(str(child.get("item_id") or "") for child in child_items)]
        member_ids = list(dict.fromkeys(member_id for member_id in member_ids if member_id))
        claimed_evidence_ids.update(member_ids)
        parents.append(
            {
                "object_id": f"control_parent_{_slug(item_id)}",
                "label": str(item.get("label") or item_id),
                "role": "atomic_control_parent",
                "bbox": bbox,
                "member_object_ids": member_ids,
                "source": "factual_control_hit_area",
                "bbox_policy": "factual_control_hit_area",
                "review_only": True,
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
        accepted_hit_areas.append(bbox)

    repeated_row_parents, repeated_row_evidence_ids, repeated_row_visual_ids = (
        _repeated_visual_anchor_control_parents(
            numbered_items=numbered_items,
            visual_candidates=visual_candidates or [],
            region_bbox=parent_bbox,
            excluded_evidence_ids=claimed_evidence_ids,
        )
    )
    parents.extend(repeated_row_parents)
    claimed_evidence_ids.update(repeated_row_evidence_ids)
    accepted_hit_areas.extend(
        bbox
        for parent in repeated_row_parents
        if (bbox := _bbox(parent.get("bbox"))) is not None
    )

    region_area = max(1, parent_bbox["w"] * parent_bbox["h"])
    raw_candidates = sorted(
        (
            (index, bbox)
            for index, value in enumerate(visual_candidates or [], start=1)
            if (bbox := _bbox(value)) is not None
        ),
        key=lambda entry: (entry[1]["w"] * entry[1]["h"], entry[1]["y"], entry[1]["x"]),
    )
    for index, bbox in raw_candidates:
        if f"raw_visual_candidate_{index}" in repeated_row_visual_ids:
            continue
        area = bbox["w"] * bbox["h"]
        if bbox["w"] < 16 or bbox["h"] < 16 or area > region_area * 0.18:
            continue
        if _bbox_containment_ratio(bbox, parent_bbox) < 0.98:
            continue
        if any(
            _bbox_containment_ratio(bbox, existing) >= 0.8
            or _bbox_containment_ratio(existing, bbox) >= 0.8
            for existing in accepted_hit_areas
        ):
            continue
        child_items = [
            item
            for item in _atomic_control_child_evidence(numbered_items, bbox)
            if str(item.get("item_id") or "") not in claimed_evidence_ids
        ]
        if not child_items or not _visual_candidate_expands_child_evidence(bbox, child_items):
            continue
        member_ids = list(
            dict.fromkeys(
                str(child.get("item_id") or "")
                for child in child_items
                if str(child.get("item_id") or "").strip()
            )
        )
        if not member_ids:
            continue
        claimed_evidence_ids.update(member_ids)
        label = next((str(child.get("label") or "").strip() for child in child_items if str(child.get("label") or "").strip()), "")
        parents.append(
            {
                "object_id": f"control_parent_visual_{index}",
                "label": label or f"control {index}",
                "role": "atomic_control_parent",
                "bbox": bbox,
                "member_object_ids": member_ids,
                "source": "visual_candidate_with_internal_evidence",
                "bbox_policy": "visual_background_with_internal_evidence",
                "review_only": True,
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
        accepted_hit_areas.append(bbox)

    parents.sort(key=lambda parent: (_bbox_top(parent), _bbox_left(parent), str(parent.get("object_id") or "")))
    return parents


def _repeated_visual_anchor_control_parents(
    *,
    numbered_items: list[dict[str, Any]],
    visual_candidates: list[dict[str, int]],
    region_bbox: dict[str, int],
    excluded_evidence_ids: set[str],
) -> tuple[list[dict[str, Any]], set[str], set[str]]:
    entries = [
        {"index": index, "bbox": bbox}
        for index, value in enumerate(visual_candidates, start=1)
        if (bbox := _bbox(value)) is not None
        and 28 <= bbox["w"] <= 96
        and 28 <= bbox["h"] <= 96
        and 0.75 <= bbox["w"] / max(1, bbox["h"]) <= 1.35
    ]
    clusters: list[list[dict[str, Any]]] = []
    for entry in sorted(entries, key=lambda value: (value["bbox"]["x"], value["bbox"]["w"], value["bbox"]["y"])):
        bbox = entry["bbox"]
        cluster = next(
            (
                existing
                for existing in clusters
                if abs(bbox["x"] - int(round(sum(item["bbox"]["x"] for item in existing) / len(existing)))) <= 6
                and abs(bbox["w"] - int(round(sum(item["bbox"]["w"] for item in existing) / len(existing)))) <= 8
                and abs(bbox["h"] - int(round(sum(item["bbox"]["h"] for item in existing) / len(existing)))) <= 8
            ),
            None,
        )
        if cluster is None:
            clusters.append([entry])
        else:
            cluster.append(entry)

    text_items = [
        item
        for item in numbered_items
        if str(item.get("item_id") or "").strip()
        and str(item.get("item_id") or "") not in excluded_evidence_ids
        and (
            str(item.get("role") or "").casefold() in {"text", "status_text"}
            or str(item.get("item_type") or "").casefold() in {"readable", "text", "ocr_text"}
        )
        and _bbox(item.get("bbox")) is not None
    ]
    parents: list[dict[str, Any]] = []
    claimed_evidence_ids: set[str] = set()
    claimed_visual_ids: set[str] = set()
    for cluster in clusters:
        ordered = sorted(cluster, key=lambda value: value["bbox"]["y"] + value["bbox"]["h"] / 2)
        if len(ordered) < 3:
            continue
        centers = [entry["bbox"]["y"] + entry["bbox"]["h"] / 2 for entry in ordered]
        steps = sorted(second - first for first, second in zip(centers, centers[1:]) if second > first)
        if not steps:
            continue
        typical_step = steps[len(steps) // 2]
        if typical_step < 32 or typical_step > 160:
            continue
        sequences: list[list[dict[str, Any]]] = []
        current = [ordered[0]]
        for previous, entry in zip(ordered, ordered[1:]):
            previous_center = previous["bbox"]["y"] + previous["bbox"]["h"] / 2
            current_center = entry["bbox"]["y"] + entry["bbox"]["h"] / 2
            step = current_center - previous_center
            if typical_step * 0.65 <= step <= typical_step * 1.45:
                current.append(entry)
            else:
                if len(current) >= 3:
                    sequences.append(current)
                current = [entry]
        if len(current) >= 3:
            sequences.append(current)

        for sequence in sequences:
            sequence_centers = [entry["bbox"]["y"] + entry["bbox"]["h"] / 2 for entry in sequence]
            for position, entry in enumerate(sequence):
                anchor_bbox = entry["bbox"]
                center_y = sequence_centers[position]
                top_boundary = (
                    (sequence_centers[position - 1] + center_y) / 2
                    if position > 0
                    else center_y - typical_step / 2
                )
                bottom_boundary = (
                    (center_y + sequence_centers[position + 1]) / 2
                    if position + 1 < len(sequence)
                    else center_y + typical_step / 2
                )
                row_text = []
                for item in text_items:
                    item_id = str(item.get("item_id") or "")
                    if item_id in claimed_evidence_ids:
                        continue
                    item_bbox = _bbox(item.get("bbox"))
                    if not item_bbox:
                        continue
                    item_center_y = item_bbox["y"] + item_bbox["h"] / 2
                    if not top_boundary <= item_center_y < bottom_boundary:
                        continue
                    if item_bbox["x"] < anchor_bbox["x"] + anchor_bbox["w"] - 8:
                        continue
                    if item_bbox["x"] >= region_bbox["x"] + region_bbox["w"]:
                        continue
                    row_text.append(item)
                if not row_text:
                    continue
                row_text.sort(key=lambda item: (_bbox_top(item), _bbox_left(item), str(item.get("item_id") or "")))
                row_bbox = _bbox_union([anchor_bbox, *[item.get("bbox") for item in row_text]])
                if not row_bbox or row_bbox["w"] < anchor_bbox["w"] * 2:
                    continue
                visual_id = f"raw_visual_candidate_{entry['index']}"
                member_ids = [visual_id, *(str(item.get("item_id") or "") for item in row_text)]
                parents.append(
                    {
                        "object_id": f"control_parent_repeated_row_{entry['index']}",
                        "label": next(
                            (str(item.get("label") or "").strip() for item in row_text if str(item.get("label") or "").strip()),
                            f"row {entry['index']}",
                        ),
                        "role": "atomic_control_parent",
                        "bbox": row_bbox,
                        "member_object_ids": member_ids,
                        "source": "repeated_visual_anchor_with_row_evidence",
                        "bbox_policy": "visual_anchor_plus_aligned_text_evidence",
                        "review_only": True,
                        "display_only": True,
                        "execute_binding_enabled": False,
                        "artifact_is_authorization": False,
                    }
                )
                claimed_visual_ids.add(visual_id)
                claimed_evidence_ids.update(member_ids[1:])
    return parents, claimed_evidence_ids, claimed_visual_ids


def _is_atomic_control_hit_area(item: dict[str, Any], region_bbox: dict[str, int]) -> bool:
    bbox = _bbox(item.get("bbox"))
    if not bbox or _bbox_containment_ratio(bbox, region_bbox) < 0.98:
        return False
    role = str(item.get("role") or "").casefold()
    item_type = str(item.get("item_type") or "").casefold()
    if role not in {"button", "control", "input", "checkbox", "radio", "toggle", "tab", "menu_item", "nav_item"}:
        return False
    if item_type in {"container", "window", "pane", "group", "section"}:
        return False
    area = bbox["w"] * bbox["h"]
    region_area = max(1, region_bbox["w"] * region_bbox["h"])
    return bbox["w"] >= 24 and bbox["h"] >= 24 and area <= region_area * 0.3


def _atomic_control_child_evidence(
    numbered_items: list[dict[str, Any]],
    parent_bbox: dict[str, int],
    *,
    exclude_item_id: str = "",
) -> list[dict[str, Any]]:
    parent_area = max(1, parent_bbox["w"] * parent_bbox["h"])
    children: list[dict[str, Any]] = []
    for item in numbered_items:
        item_id = str(item.get("item_id") or "").strip()
        bbox = _bbox(item.get("bbox"))
        role = str(item.get("role") or "").casefold()
        item_type = str(item.get("item_type") or "").casefold()
        if not item_id or item_id == exclude_item_id or not bbox:
            continue
        if role not in {"text", "icon", "image", "status_text"} and item_type not in {"readable", "icon", "ocr_text"}:
            continue
        if bbox["w"] * bbox["h"] >= parent_area * 0.8:
            continue
        if not _bbox_center_inside(bbox, parent_bbox):
            continue
        if _bbox_containment_ratio(bbox, parent_bbox) < 0.75:
            continue
        children.append(item)
    children.sort(key=lambda item: (_bbox_top(item), _bbox_left(item), str(item.get("item_id") or "")))
    return children


def _visual_candidate_expands_child_evidence(
    candidate_bbox: dict[str, int],
    child_items: list[dict[str, Any]],
) -> bool:
    child_union = _bbox_union([item.get("bbox") for item in child_items])
    if not child_union:
        return False
    child_area = max(1, child_union["w"] * child_union["h"])
    candidate_area = candidate_bbox["w"] * candidate_bbox["h"]
    width_margin = candidate_bbox["w"] - child_union["w"]
    height_margin = candidate_bbox["h"] - child_union["h"]
    roles = {str(item.get("role") or "").casefold() for item in child_items}
    has_icon_and_text = bool(roles & {"icon", "image"}) and "text" in roles
    if has_icon_and_text:
        return (
            candidate_bbox["w"] >= 28
            and candidate_bbox["h"] >= 24
            and candidate_area >= child_area * 1.2
            and width_margin >= 4
            and height_margin >= 4
        )
    return (
        candidate_bbox["w"] >= 64
        and candidate_bbox["h"] >= 32
        and candidate_area >= child_area * 1.8
        and width_margin >= 10
        and height_margin >= 8
    )


def _is_stage2_semantic_container_item(item: dict[str, Any]) -> bool:
    item_type = str(item.get("item_type") or "").strip().casefold()
    evidence_level = str(item.get("evidence_level") or "").strip().casefold()
    source = str(item.get("source") or "").strip().casefold()
    return (
        evidence_level == "semantic_region_only"
        or item_type in {"container", "group", "region"}
        or "semantic_proposal" in source
        or "semantic_region" in source
    )


def _suppress_oversized_stage2_structural_containers(
    items: list[dict[str, Any]],
    *,
    region_bbox: dict[str, int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    suppressed_item_ids: list[str] = []
    region_area = max(1, _int(region_bbox.get("w")) * _int(region_bbox.get("h")))
    structural_roles = {"window", "pane", "document", "root", "container"}
    for item in items:
        bbox = _bbox(item.get("bbox"))
        role = str(item.get("role") or item.get("item_type") or "").strip().casefold()
        source = str(item.get("source") or "").strip().casefold()
        item_id = str(item.get("item_id") or item.get("candidate_id") or "").strip()
        uia_evidence = (
            "uia" in source
            or item_id.casefold().startswith(("action_uia_", "page_uia_"))
        )
        item_area = _int((bbox or {}).get("w")) * _int((bbox or {}).get("h"))
        covers_active_region = bool(bbox) and (item_area / region_area) >= 0.90
        if role in structural_roles and uia_evidence and covers_active_region:
            if item_id:
                suppressed_item_ids.append(item_id)
            continue
        kept.append(item)
    suppressed_item_ids = sorted(set(suppressed_item_ids))
    return kept, {
        "contract_version": "learn_stage2_structural_container_suppression_v1",
        "suppressed_count": len(suppressed_item_ids),
        "suppressed_item_ids": suppressed_item_ids,
        "reason_counts": (
            {"oversized_uia_structural_container": len(suppressed_item_ids)}
            if suppressed_item_ids
            else {}
        ),
        "policy": (
            "structural UIA containers covering nearly the active region remain context evidence "
            "and are not numbered as atomic targets"
        ),
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _synthesize_direct_visual_controls(
    numbered_items: list[dict[str, Any]],
    candidates: list[dict[str, int]],
    *,
    fallback_region_bbox: dict[str, int],
) -> list[dict[str, Any]]:
    if not candidates:
        return numbered_items
    region_no = str(numbered_items[0].get("number") or "1").split(".", 1)[0] if numbered_items else "1"
    horizontal = _is_horizontal_region(_bbox_union(candidates) or fallback_region_bbox)
    ordered = sorted(candidates, key=lambda item: (item["x"], item["y"]) if horizontal else (item["y"], item["x"]))
    result: list[dict[str, Any]] = []
    for index, bbox in enumerate(ordered, start=1):
        result.append(
            {
                "contract_version": "learn_stage2_numbered_item_v1",
                "number": f"{region_no}.{index}",
                "item_id": f"visual_control_{region_no}_{index}",
                "label": f"control {index}",
                "role": "control" if horizontal else "nav_icon",
                "bbox": bbox,
                "click_point": {},
                "children": [],
                "review_only": True,
                "stage": "stage2_region_numbering",
                "source": "visual_small_control_segmenter",
                "bbox_policy": "visual_control_candidate_display_only",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    return result


def _direct_refinement_applied(base_applied: bool, direct_bar_report: dict[str, Any]) -> bool:
    sidebar_report = direct_bar_report.get("sidebar_item_grouping")
    topbar_report = direct_bar_report.get("topbar_item_grouping")
    return bool(
        base_applied
        or direct_bar_report.get("applied")
        or (isinstance(sidebar_report, dict) and sidebar_report.get("applied"))
        or (isinstance(topbar_report, dict) and topbar_report.get("applied"))
    )


def _direct_refinement_reason(base_reason: str, direct_bar_report: dict[str, Any]) -> str:
    sidebar_report = direct_bar_report.get("sidebar_item_grouping")
    topbar_report = direct_bar_report.get("topbar_item_grouping")
    if isinstance(sidebar_report, dict) and sidebar_report.get("applied"):
        return f"sidebar_item_hit_area_normalized_after_{base_reason}"
    if isinstance(topbar_report, dict) and topbar_report.get("applied"):
        return f"topbar_control_hit_area_normalized_after_{base_reason}"
    if direct_bar_report.get("applied"):
        return str(direct_bar_report.get("reason") or base_reason)
    return base_reason


def _normalize_direct_bar_items(
    numbered_items: list[dict[str, Any]],
    *,
    region_bbox: dict[str, int],
    region_family: str,
    image_path: str,
    reason: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    items, sidebar_report = _normalize_sidebar_direct_items(
        numbered_items,
        region_bbox=region_bbox,
        region_family=region_family,
        image_path=image_path,
        reason=reason,
    )
    items, topbar_report = _normalize_topbar_direct_items(
        items,
        region_bbox=region_bbox,
        region_family=region_family,
        reason=reason,
    )
    return items, {
        "sidebar_item_grouping": sidebar_report,
        "topbar_item_grouping": topbar_report,
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


_CLASSIC_MENU_ACCELERATOR_RE = re.compile(r"\(\s*([A-Za-z])\s*\)?")


def _classic_menu_segments(label: str) -> list[dict[str, Any]]:
    normalized = unicodedata.normalize("NFKC", str(label or "")).strip()
    matches = list(_CLASSIC_MENU_ACCELERATOR_RE.finditer(normalized))
    if len(matches) < 3:
        return []
    segments: list[dict[str, Any]] = []
    cursor = 0
    for match in matches:
        raw_label = normalized[cursor : match.start()].strip(" \t\r\n()（）,，;；|/")
        if not raw_label or len(raw_label) > 24:
            return []
        accelerator = match.group(1).upper()
        segments.append(
            {
                "label": f"{raw_label}({accelerator})",
                "semantic_key": _classic_menu_semantic_key(raw_label),
                "span_start": cursor,
                "span_end": match.end(),
            }
        )
        cursor = match.end()
    if len({segment["semantic_key"] for segment in segments}) != len(segments):
        return []
    return segments


def _classic_menu_semantic_key(label: str) -> str:
    normalized = unicodedata.normalize("NFKC", str(label or "")).casefold()
    normalized = _CLASSIC_MENU_ACCELERATOR_RE.sub("", normalized)
    return "".join(character for character in normalized if character.isalnum())


def _normalize_classic_menu_bar_items(
    numbered_items: list[dict[str, Any]],
    *,
    region_bbox: dict[str, int],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    anchor_candidates: list[tuple[int, dict[str, Any], dict[str, int], list[dict[str, Any]]]] = []
    for index, item in enumerate(numbered_items):
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            continue
        segments = _classic_menu_segments(str(item.get("label") or ""))
        if not segments:
            continue
        role = str(item.get("role") or "").casefold().replace(" ", "_")
        if role not in {"menu_item", "text", "readable", "label"}:
            continue
        if bbox["w"] < max(72, bbox["h"] * 3) or bbox["h"] > max(40, int(region_bbox["h"] * 0.7)):
            continue
        anchor_candidates.append((index, item, bbox, segments))
    if not anchor_candidates:
        return [deepcopy(item) for item in numbered_items], {
            "applied": False,
            "reason": "classic_menu_ocr_line_missing",
            "menu_item_count": 0,
        }

    anchor_index, anchor_item, anchor_bbox, segments = max(
        anchor_candidates,
        key=lambda entry: (len(entry[3]), entry[2]["w"]),
    )
    segment_keys = {str(segment["semantic_key"]) for segment in segments}
    existing_by_key: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(numbered_items):
        if index == anchor_index:
            continue
        key = _classic_menu_semantic_key(str(item.get("label") or ""))
        if key in segment_keys and key not in existing_by_key:
            existing_by_key[key] = item

    normalized_label = unicodedata.normalize("NFKC", str(anchor_item.get("label") or ""))
    label_length = max(1, len(normalized_label))
    corrected_items: list[dict[str, Any]] = []
    corrected_count = 0
    for segment_index, segment in enumerate(segments, start=1):
        key = str(segment["semantic_key"])
        template = deepcopy(existing_by_key.get(key) or {})
        estimated_x = anchor_bbox["x"] + int(round(anchor_bbox["w"] * int(segment["span_start"]) / label_length))
        estimated_right = anchor_bbox["x"] + int(round(anchor_bbox["w"] * int(segment["span_end"]) / label_length))
        estimated_bbox = {
            "x": estimated_x,
            "y": anchor_bbox["y"],
            "w": max(24, estimated_right - estimated_x),
            "h": anchor_bbox["h"],
        }
        existing_bbox = _bbox(template.get("bbox"))
        target_bbox = _clip_bbox(region_bbox, estimated_bbox)
        if existing_bbox != target_bbox:
            corrected_count += 1
        template.update(
            {
                "contract_version": "learn_stage2_numbered_item_v1",
                "number": str(template.get("number") or f"1.{segment_index}"),
                "item_id": str(template.get("item_id") or f"classic_menu_item_{segment_index}_{key}"),
                "label": str(segment["label"]),
                "role": "menu_item",
                "item_type": "actionable",
                "bbox": target_bbox,
                "click_point": {},
                "review_only": True,
                "source": "classic_menu_ocr_anchor",
                "bbox_policy": "classic_menu_item_anchored_inside_ocr_menu_line",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
        if existing_bbox and existing_bbox != target_bbox:
            template["bbox_refinement"] = {
                "source": "classic_menu_ocr_anchor",
                "previous_bbox": existing_bbox,
                "reason": "menu_item_bbox_must_remain_inside_ocr_menu_line",
            }
        corrected_items.append(template)

    evidence_item = deepcopy(anchor_item)
    evidence_item.update(
        {
            "role": "menu_bar_evidence",
            "item_type": "readable",
            "review_only": True,
            "grounding_eligible": False,
            "source": "classic_menu_ocr_anchor",
            "bbox_policy": "combined_ocr_menu_line_is_evidence_not_click_target",
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
    )
    result: list[dict[str, Any]] = []
    inserted = False
    for index, item in enumerate(numbered_items):
        key = _classic_menu_semantic_key(str(item.get("label") or ""))
        if index == anchor_index:
            result.append(evidence_item)
            result.extend(corrected_items)
            inserted = True
            continue
        if key in segment_keys:
            continue
        result.append(deepcopy(item))
    if not inserted:
        result.extend([evidence_item, *corrected_items])
    result = _renumber_stage2_items(result, horizontal=True)
    return result, {
        "applied": True,
        "reason": "classic_menu_items_split_and_anchored_to_ocr_line",
        "anchor_item_id": str(anchor_item.get("item_id") or ""),
        "anchor_bbox": anchor_bbox,
        "menu_item_count": len(corrected_items),
        "corrected_bbox_count": corrected_count,
        "menu_labels": [item["label"] for item in corrected_items],
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _normalize_topbar_direct_items(
    numbered_items: list[dict[str, Any]],
    *,
    region_bbox: dict[str, int],
    region_family: str,
    reason: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if region_family != "top_bar" or not region_bbox or not numbered_items:
        return numbered_items, {
            "applied": False,
            "reason": "not_topbar_direct_region",
            "input_count": len(numbered_items),
            "output_count": len(numbered_items),
        }
    rows = _cluster_topbar_controls_by_horizontal_band(numbered_items, region_bbox=region_bbox)
    if not rows:
        return numbered_items, {
            "applied": False,
            "reason": "no_topbar_item_bbox",
            "input_count": len(numbered_items),
            "output_count": len(numbered_items),
        }
    expanded_count = 0
    normalized: list[dict[str, Any]] = []
    for row in rows:
        ordered = sorted([deepcopy(item) for item in row], key=lambda item: (_bbox_left(item), _bbox_top(item)))
        boxes = [_bbox(item.get("bbox")) for item in ordered]
        centers = [box["x"] + box["w"] / 2 for box in boxes if box]
        for index, item in enumerate(ordered):
            bbox = _bbox(item.get("bbox"))
            if not bbox:
                normalized.append(item)
                continue
            if not _direct_item_accepts_visual_hit_area_refinement(item):
                normalized.append(item)
                continue
            neighbor_gaps: list[float] = []
            if index > 0:
                neighbor_gaps.append(centers[index] - centers[index - 1])
            if index < len(centers) - 1:
                neighbor_gaps.append(centers[index + 1] - centers[index])
            local_gaps = [gap for gap in neighbor_gaps if 24 <= gap <= 120]
            inferred_slot_width = int(round(min(local_gaps) * 0.96)) if local_gaps else bbox["w"] + 28
            target_width = min(max(48, inferred_slot_width, bbox["w"]), 72)
            target_height = min(region_bbox["h"], max(36, min(52, bbox["h"] + 20)))
            center_x = bbox["x"] + bbox["w"] / 2
            center_y = bbox["y"] + bbox["h"] / 2
            target = _clip_bbox(
                region_bbox,
                {
                    "x": int(round(center_x - target_width / 2)),
                    "y": int(round(center_y - target_height / 2)),
                    "w": target_width,
                    "h": target_height,
                },
            )
            previous_bbox = _bbox(item.get("bbox")) or bbox
            if previous_bbox["w"] >= 36 and target["x"] < previous_bbox["x"] - 1:
                shifted_x = previous_bbox["x"] - 1
                target = _clip_bbox(
                    region_bbox,
                    {**target, "x": shifted_x, "w": min(target["w"], region_bbox["x"] + region_bbox["w"] - shifted_x)},
                )
            if target != previous_bbox:
                expanded_count += 1
                refinement = {
                    "source": "topbar_control_hit_area_normalizer",
                    "previous_bbox": previous_bbox,
                    "reason": "topbar_direct_item_must_cover_hit_area_not_fragment",
                    "trigger": reason,
                }
                if isinstance(item.get("bbox_refinement"), dict):
                    item["hit_area_refinement"] = refinement
                else:
                    item["bbox_refinement"] = refinement
            item["bbox"] = target
            item["role"] = str(item.get("role") or "control")
            item["bbox_policy"] = "topbar_control_hit_area_from_visual_or_text_fragments"
            item["review_only"] = True
            item["source"] = "topbar_control_hit_area_normalizer"
            item["display_only"] = True
            item["execute_binding_enabled"] = False
            item["artifact_is_authorization"] = False
            normalized.append(item)
    normalized = _renumber_stage2_items(normalized, horizontal=len(rows) == 1)
    return normalized, {
        "applied": expanded_count > 0,
        "reason": "topbar_control_hit_area_normalized" if expanded_count > 0 else "topbar_controls_already_hit_area_sized",
        "input_count": len(numbered_items),
        "output_count": len(normalized),
        "expanded_item_count": expanded_count,
        "horizontal_row_count": len(rows),
        "minimum_width_px": 48,
        "minimum_height_px": 36,
        "bbox_policy": "topbar_controls_must_not_remain_icon_or_ocr_fragments",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _cluster_topbar_controls_by_horizontal_band(
    controls: list[dict[str, Any]],
    *,
    region_bbox: dict[str, int],
) -> list[list[dict[str, Any]]]:
    candidates = [item for item in controls if _bbox(item.get("bbox"))]
    if not candidates:
        return []
    center_tolerance = max(18, min(36, int(round(region_bbox["h"] * 0.16))))
    rows: list[list[dict[str, Any]]] = []
    for item in sorted(candidates, key=lambda entry: (_bbox_top(entry), _bbox_left(entry))):
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            continue
        center_y = bbox["y"] + bbox["h"] / 2
        best_row: list[dict[str, Any]] | None = None
        best_delta = float("inf")
        for row in rows:
            row_boxes = [_bbox(existing.get("bbox")) for existing in row]
            row_boxes = [box for box in row_boxes if box]
            row_center = sum(box["y"] + box["h"] / 2 for box in row_boxes) / len(row_boxes)
            delta = abs(center_y - row_center)
            if delta <= center_tolerance and delta < best_delta:
                best_row = row
                best_delta = delta
        if best_row is None:
            rows.append([item])
        else:
            best_row.append(item)
    return [sorted(row, key=lambda entry: (_bbox_left(entry), _bbox_top(entry))) for row in rows]


def _normalize_sidebar_direct_items(
    numbered_items: list[dict[str, Any]],
    *,
    region_bbox: dict[str, int],
    region_family: str,
    image_path: str,
    reason: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if region_family not in {"left_bar", "right_bar"} or not region_bbox or not numbered_items:
        return numbered_items, {
            "applied": False,
            "reason": "not_sidebar_direct_region",
            "input_count": len(numbered_items),
            "output_count": len(numbered_items),
        }
    grouped = _group_sidebar_direct_item_rows(numbered_items)
    normalized: list[dict[str, Any]] = []
    merged_count = 0
    expanded_count = 0
    rejected_without_evidence_count = 0
    for index, group in enumerate(grouped, start=1):
        group_boxes = [_bbox(item.get("bbox")) for item in group]
        group_boxes = [box for box in group_boxes if box]
        if not group_boxes:
            continue
        row_bbox = _bbox_union(group_boxes)
        if not row_bbox:
            continue
        has_visual_evidence = _sidebar_group_has_semantic_evidence(group) or _sidebar_row_has_visual_evidence(
            image_path=image_path,
            row_bbox=row_bbox,
            region_bbox=region_bbox,
        )
        force_boundary_review_container = len(group) == 1 and _member_list_header_child_proxy(group[0]) and row_bbox["h"] > 96
        if force_boundary_review_container:
            has_visual_evidence = False
        full_row_bbox, expanded = _sidebar_hit_area_bbox(row_bbox, region_bbox=region_bbox, force_full_row=len(group) > 1)
        base = deepcopy(group[0])
        previous_bbox = _bbox(base.get("bbox")) or row_bbox
        if len(group) > 1:
            merged_count += len(group) - 1
            base["item_id"] = f"sidebar_item_{str(base.get('number') or index).replace('.', '_')}"
            base["label"] = _merged_sidebar_label(group)
            base["children"] = [_child_from_numbered_item(item) for item in group if _child_from_numbered_item(item)]
        elif force_boundary_review_container:
            base["item_id"] = f"merged_{str(base.get('item_id') or base.get('number') or index).replace('.', '_')}"
            base["children"] = [
                child
                for child in (_child_from_numbered_item(group[0]), *list(group[0].get("children") or []))
                if child
            ]
        base["role"] = "nav_item" if has_visual_evidence else "sidebar_review_region"
        base["bbox"] = full_row_bbox if has_visual_evidence else row_bbox
        base["review_only"] = True
        base["source"] = "sidebar_item_hit_area_normalizer" if has_visual_evidence else "sidebar_item_evidence_filter"
        base["bbox_policy"] = (
            "sidebar_item_hit_area_from_visual_or_text_fragments"
            if has_visual_evidence
            else "sidebar_fragment_kept_review_only_not_promoted_to_nav_item"
        )
        if not has_visual_evidence:
            base["overlay_style"] = _background_review_overlay_style()
        base["display_only"] = True
        base["execute_binding_enabled"] = False
        base["artifact_is_authorization"] = False
        if not has_visual_evidence:
            rejected_without_evidence_count += 1
            base["bbox_refinement"] = {
                "source": "sidebar_item_evidence_filter",
                "previous_bbox": previous_bbox,
                "reason": "sidebar_nav_item_rejected_no_visual_evidence",
                "trigger": reason,
            }
        elif expanded or len(group) > 1:
            expanded_count += 1
            base["bbox_refinement"] = {
                "source": "sidebar_item_hit_area_normalizer",
                "previous_bbox": previous_bbox,
                "reason": "sidebar_direct_item_must_cover_hit_area_not_fragment",
                "trigger": reason,
            }
        normalized.append(base)
    normalized, merged_review_region_count = _merge_sidebar_review_regions(normalized)
    normalized = _renumber_stage2_items(normalized, horizontal=False)
    return normalized, {
        "applied": bool(normalized) and (expanded_count > 0 or merged_count > 0),
        "reason": "sidebar_item_hit_area_normalized" if (expanded_count > 0 or merged_count > 0) else "sidebar_items_already_hit_area_sized",
        "input_count": len(numbered_items),
        "output_count": len(normalized),
        "merged_fragment_count": merged_count,
        "merged_review_region_count": merged_review_region_count,
        "expanded_item_count": expanded_count,
        "rejected_without_evidence_count": rejected_without_evidence_count,
        "minimum_width_ratio": 0.55,
        "visual_evidence_required_for_nav_item": True,
        "bbox_policy": "sidebar_items_must_not_remain_icon_or_ocr_fragments",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _group_sidebar_direct_item_rows(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    rows: list[list[dict[str, Any]]] = []
    for item in sorted(items, key=lambda entry: (_bbox_center_y(entry), _bbox_left(entry))):
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            continue
        center_y = bbox["y"] + bbox["h"] / 2
        target_row: list[dict[str, Any]] | None = None
        for row in rows:
            row_boxes = [_bbox(existing.get("bbox")) for existing in row]
            row_boxes = [box for box in row_boxes if box]
            if not row_boxes:
                continue
            row_union = _bbox_union(row_boxes)
            if not row_union:
                continue
            row_center = row_union["y"] + row_union["h"] / 2
            row_height = max(box["h"] for box in row_boxes)
            comparable_height = min(row_height, bbox["h"])
            if abs(center_y - row_center) <= max(12, comparable_height * 0.75):
                target_row = row
                break
        if target_row is None:
            rows.append([item])
        else:
            target_row.append(item)
    return rows


def _sidebar_hit_area_bbox(
    row_bbox: dict[str, int],
    *,
    region_bbox: dict[str, int],
    force_full_row: bool,
) -> tuple[dict[str, int], bool]:
    min_width = min(region_bbox["w"], max(40, int(round(region_bbox["w"] * 0.55))))
    target_width = region_bbox["w"] if force_full_row or row_bbox["w"] < min_width else row_bbox["w"]
    target_x = region_bbox["x"] if target_width == region_bbox["w"] else row_bbox["x"]
    target_height = max(row_bbox["h"], min(36, max(28, row_bbox["h"] + 12)))
    center_y = row_bbox["y"] + row_bbox["h"] / 2
    target = {
        "x": target_x,
        "y": int(round(center_y - target_height / 2)),
        "w": target_width,
        "h": target_height,
    }
    expanded = target != row_bbox
    return target, expanded


def _merged_sidebar_label(items: list[dict[str, Any]]) -> str:
    labels: list[str] = []
    for item in items:
        label = str(item.get("label") or "").strip()
        if label and label not in labels:
            labels.append(label)
    return " / ".join(labels) if labels else "sidebar item"


def _sidebar_group_has_semantic_evidence(items: list[dict[str, Any]]) -> bool:
    for item in items:
        value = " ".join(
            str(item.get(key) or "").casefold()
            for key in ("role", "item_type", "source")
        )
        actionable_tokens = (
            "button",
            "icon_button",
            "control",
            "menu",
            "tab",
            "link",
            "checkbox",
            "radio",
            "switch",
        )
        if any(token in value for token in actionable_tokens):
            return True
    return False


def _merge_sidebar_review_regions(items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    result: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []

    def flush_pending() -> None:
        if not pending:
            return
        if len(pending) == 1:
            result.append(pending[0])
            pending.clear()
            return
        boxes = [_bbox(item.get("bbox")) for item in pending]
        boxes = [box for box in boxes if box]
        union = _bbox_union(boxes)
        merged = deepcopy(pending[0])
        if union:
            merged["bbox"] = union
        merged["label"] = "sidebar background / empty review region"
        merged["item_id"] = f"merged_{str(merged.get('item_id') or merged.get('number') or 'sidebar_review')}"
        merged["children"] = [_child_from_numbered_item(item) for item in pending if _child_from_numbered_item(item)]
        merged["bbox_policy"] = "merged_sidebar_review_region_without_nav_evidence"
        merged["overlay_style"] = _background_review_overlay_style()
        merged["bbox_refinement"] = {
            "source": "sidebar_review_region_merger",
            "previous_bbox": boxes[0] if boxes else {},
            "merged_count": len(pending),
            "reason": "merge_consecutive_sidebar_review_regions_without_visual_evidence",
        }
        result.append(merged)
        pending.clear()

    for item in items:
        if str(item.get("role") or "") == "sidebar_review_region" and _sidebar_review_item_should_merge(item):
            pending.append(item)
            continue
        flush_pending()
        result.append(item)
    flush_pending()
    return result, max(0, len(items) - len(result))


def _sidebar_review_item_should_merge(item: dict[str, Any]) -> bool:
    item_id = str(item.get("item_id") or "")
    if item_id.startswith("merged_"):
        return False
    if (
        str(item.get("role") or "") == "sidebar_review_region"
        and str(item.get("item_type") or "") == "actionable"
    ):
        return True
    value = " ".join(
        str(item.get(key) or "").casefold()
        for key in ("role", "item_type", "source")
    )
    if "review_only" in value or "nav_rail_icon_review_only" in value:
        return True
    label = str(item.get("label") or "").strip().casefold()
    if not label:
        return True
    generic_tokens = ("maybe button", "blank", "empty", "background", "fragment")
    return any(token in label for token in generic_tokens)


def _background_review_overlay_style() -> dict[str, str]:
    return {
        "tone": "background_review_region",
        "label_policy": "review_only_badge",
        "stroke": "muted_dashed",
        "display_layer": "review_background",
        "number_policy": "hide_stage_number",
        "action_candidate_visual_weight": "low",
    }


def _sidebar_row_has_visual_evidence(
    *,
    image_path: str,
    row_bbox: dict[str, int],
    region_bbox: dict[str, int],
) -> bool:
    if not image_path:
        return True
    source = Path(image_path)
    if not source.exists():
        return True
    try:
        with Image.open(source) as image:
            probe = _clip_bbox(region_bbox, _expand_bbox(row_bbox, pad_x=2, pad_y=2))
            crop = image.crop((probe["x"], probe["y"], probe["x"] + probe["w"], probe["y"] + probe["h"])).convert("RGB")
    except Exception:
        return True
    pixel_source = getattr(crop, "get_flattened_data", None)
    pixels = list(pixel_source() if pixel_source else crop.getdata())
    if not pixels:
        return False
    evidence_pixels = 0
    for red, green, blue in pixels:
        avg = (red + green + blue) / 3
        chroma = max(red, green, blue) - min(red, green, blue)
        if avg < 210 or (chroma > 35 and avg < 245):
            evidence_pixels += 1
    return (evidence_pixels / len(pixels)) >= 0.025


def _expand_bbox(bbox: dict[str, int], *, pad_x: int, pad_y: int) -> dict[str, int]:
    return {
        "x": bbox["x"] - pad_x,
        "y": bbox["y"] - pad_y,
        "w": bbox["w"] + pad_x * 2,
        "h": bbox["h"] + pad_y * 2,
    }


def _direct_region_control_detection_bbox(region_bbox: dict[str, int]) -> dict[str, int]:
    if not _is_horizontal_region(region_bbox):
        return region_bbox
    if region_bbox.get("x") != 0:
        return region_bbox
    if _int(region_bbox.get("h")) > 140:
        return region_bbox
    offset = min(max(56, int(_int(region_bbox.get("w")) * 0.055)), 80)
    if offset >= _int(region_bbox.get("w")) - 1:
        return region_bbox
    return {
        "x": offset,
        "y": _int(region_bbox.get("y")),
        "w": max(1, _int(region_bbox.get("w")) - offset),
        "h": _int(region_bbox.get("h")),
    }


def _is_horizontal_region(bbox: dict[str, int]) -> bool:
    return _int(bbox.get("w")) >= _int(bbox.get("h")) * 2


def _renumber_stage2_items(items: list[dict[str, Any]], *, horizontal: bool) -> list[dict[str, Any]]:
    if not items:
        return []
    region_no = str(items[0].get("number") or "0").split(".", 1)[0]
    ordered = sorted(items, key=lambda item: ((_bbox_left(item), _bbox_top(item)) if horizontal else (_bbox_top(item), _bbox_left(item))))
    result: list[dict[str, Any]] = []
    for index, item in enumerate(ordered, start=1):
        copied = deepcopy(item)
        copied["number"] = f"{region_no}.{index}"
        result.append(copied)
    return result


def _visual_small_control_boxes(*, image_path: str, parent_bbox: dict[str, int]) -> list[dict[str, int]]:
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return []
    source = Path(image_path)
    if not source.exists():
        return []
    try:
        with Image.open(source) as image:
            crop = image.crop(
                (
                    parent_bbox["x"],
                    parent_bbox["y"],
                    parent_bbox["x"] + parent_bbox["w"],
                    parent_bbox["y"] + parent_bbox["h"],
                )
            ).convert("RGB")
    except Exception:
        return []
    arr = np.array(crop)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    dark = (gray < 190).astype("uint8") * 255
    edges = cv2.Canny(gray, 40, 120)
    mask = cv2.bitwise_or(dark, edges)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    raw_boxes: list[dict[str, int]] = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        if area < 18 or w < 3 or h < 2:
            continue
        if w > parent_bbox["w"] * 0.38 or h > parent_bbox["h"] * 0.82:
            continue
        if w > 90 or h > 70:
            continue
        raw_boxes.append({"x": parent_bbox["x"] + x, "y": parent_bbox["y"] + y, "w": w, "h": h})
    boxes = _dedupe_bboxes(raw_boxes, iou_threshold=0.55)
    padded = [_pad_small_control_bbox(box, parent_bbox=parent_bbox) for box in boxes]
    if _is_horizontal_region(parent_bbox):
        padded = _normalize_horizontal_control_hit_areas(padded, parent_bbox=parent_bbox)
    return _dedupe_bboxes(padded, iou_threshold=0.72)


def _pad_small_control_bbox(box: dict[str, int], *, parent_bbox: dict[str, int]) -> dict[str, int]:
    target_w = min(max(32, box["w"] + 14), 46)
    target_h = min(max(28, box["h"] + 12), 42)
    cx = box["x"] + box["w"] / 2
    cy = box["y"] + box["h"] / 2
    padded = {
        "x": int(round(cx - target_w / 2)),
        "y": int(round(cy - target_h / 2)),
        "w": int(target_w),
        "h": int(target_h),
    }
    return _clip_bbox(parent_bbox, padded)


def _normalize_horizontal_control_hit_areas(
    boxes: list[dict[str, int]],
    *,
    parent_bbox: dict[str, int],
) -> list[dict[str, int]]:
    if not boxes:
        return boxes
    ordered = sorted(boxes, key=lambda box: (box["x"] + box["w"] / 2, box["y"]))
    centers = [box["x"] + box["w"] / 2 for box in ordered]
    normalized: list[dict[str, int]] = []
    for index, box in enumerate(ordered):
        neighbor_gaps: list[float] = []
        if index > 0:
            neighbor_gaps.append(centers[index] - centers[index - 1])
        if index < len(ordered) - 1:
            neighbor_gaps.append(centers[index + 1] - centers[index])
        local_gaps = [gap for gap in neighbor_gaps if 18 <= gap <= 96]
        inferred_slot_width = int(round(min(local_gaps) * 0.72)) if local_gaps else box["w"] + 18
        target_w = min(max(36, inferred_slot_width, box["w"]), 52)
        target_h = min(max(30, box["h"] + 4), 44)
        cx = box["x"] + box["w"] / 2
        cy = box["y"] + box["h"] / 2
        normalized.append(
            _clip_bbox(
                parent_bbox,
                {
                    "x": int(round(cx - target_w / 2)),
                    "y": int(round(cy - target_h / 2)),
                    "w": target_w,
                    "h": target_h,
                },
            )
        )
    return normalized


def _dedupe_bboxes(boxes: list[dict[str, int]], *, iou_threshold: float) -> list[dict[str, int]]:
    result: list[dict[str, int]] = []
    for box in sorted(boxes, key=lambda item: item["w"] * item["h"], reverse=True):
        if any(_iou(box, existing) >= iou_threshold for existing in result):
            continue
        result.append(box)
    return sorted(result, key=lambda item: (item["y"], item["x"]))


def _clip_bbox(outer: dict[str, int], inner: dict[str, int]) -> dict[str, int]:
    x1 = max(outer["x"], inner["x"])
    y1 = max(outer["y"], inner["y"])
    x2 = min(outer["x"] + outer["w"], inner["x"] + inner["w"])
    y2 = min(outer["y"] + outer["h"], inner["y"] + inner["h"])
    return {"x": x1, "y": y1, "w": max(1, x2 - x1), "h": max(1, y2 - y1)}


def _intersect_bbox(outer: dict[str, int], inner: dict[str, int]) -> dict[str, int] | None:
    x1 = max(outer["x"], inner["x"])
    y1 = max(outer["y"], inner["y"])
    x2 = min(outer["x"] + outer["w"], inner["x"] + inner["w"])
    y2 = min(outer["y"] + outer["h"], inner["y"] + inner["h"])
    if x2 <= x1 or y2 <= y1:
        return None
    return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}


def _iou(left: dict[str, int], right: dict[str, int]) -> float:
    x1 = max(left["x"], right["x"])
    y1 = max(left["y"], right["y"])
    x2 = min(left["x"] + left["w"], right["x"] + right["w"])
    y2 = min(left["y"] + left["h"], right["y"] + right["h"])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    union = max(1, left["w"] * left["h"] + right["w"] * right["h"] - intersection)
    return intersection / union


def _bundle_app_name(bundle: dict[str, Any]) -> str:
    screen_reading = bundle.get("screen_reading") if isinstance(bundle.get("screen_reading"), dict) else {}
    request = bundle.get("request") if isinstance(bundle.get("request"), dict) else {}
    result = bundle.get("result") if isinstance(bundle.get("result"), dict) else {}
    result_screen_reading = result.get("screen_reading") if isinstance(result.get("screen_reading"), dict) else {}
    return str(
        bundle.get("app_name")
        or request.get("app_name")
        or result.get("app_name")
        or screen_reading.get("app_name")
        or result_screen_reading.get("app_name")
        or ""
    ).strip()


def _screen_size_from_bundle(bundle: dict[str, Any]) -> dict[str, int]:
    for key in ("screen_size", "viewport_size", "image_size", "source_image_size"):
        value = bundle.get(key)
        if isinstance(value, dict):
            return {"width": _int(value.get("width")), "height": _int(value.get("height"))}
    return {"width": 0, "height": 0}


def _bbox(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    x = _int(value.get("x"))
    y = _int(value.get("y"))
    w = _int(value.get("w", value.get("width")))
    h = _int(value.get("h", value.get("height")))
    if w <= 0 or h <= 0:
        return None
    return {"x": max(0, x), "y": max(0, y), "w": w, "h": h}


def _bbox_union(values: list[Any]) -> dict[str, int] | None:
    boxes = [_bbox(value) for value in values]
    boxes = [box for box in boxes if box]
    if not boxes:
        return None
    x1 = min(box["x"] for box in boxes)
    y1 = min(box["y"] for box in boxes)
    x2 = max(box["x"] + box["w"] for box in boxes)
    y2 = max(box["y"] + box["h"] for box in boxes)
    return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}


def _bbox_top(item: dict[str, Any]) -> int:
    bbox = _bbox(item.get("bbox"))
    return bbox["y"] if bbox else 10**9


def _bbox_left(item: dict[str, Any]) -> int:
    bbox = _bbox(item.get("bbox"))
    return bbox["x"] if bbox else 10**9


def _item_id(item: dict[str, Any], index: int) -> str:
    return str(item.get("item_id") or item.get("candidate_id") or item.get("id") or f"item_{index + 1}")


def _slug(value: str) -> str:
    text = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(value or "")).strip("_")
    return text or "region"


def _int(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0
