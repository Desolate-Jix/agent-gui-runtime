from __future__ import annotations

import re
import unicodedata
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from app.core.runtime_artifacts import ARTIFACTS_DIR
from app.learn.recognition.stage1_audit import audit_stage1_region_selection


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


def build_two_stage_screen_understanding(
    *,
    bundle: dict[str, Any],
    screen_inventory: list[dict[str, Any]],
    layout_graph: dict[str, Any],
    require_stage1_gate: bool = False,
    stage2_region_strategy: str = "partitioned",
) -> dict[str, Any]:
    """生成学习模式的两阶段只读理解结果。"""

    items_by_id = _items_by_id(screen_inventory, layout_graph)
    supplemental_text_items = _bundle_screen_text_items(bundle)
    screen_size = _screen_size_from_bundle(bundle)
    stage1 = _stage1_structure_regions(items_by_id=items_by_id, layout_graph=layout_graph, screen_size=screen_size)
    stage1_localization = _stage1_region_localization(
        stage1["structure_regions"],
        items_by_id=items_by_id,
        screen_size=screen_size,
    )
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
    )
    stage1_5_partition = _stage1_5_partition(
        localized_regions=stage1_localization["regions"],
        items_by_id=items_by_id,
        screen_size=screen_size,
        region_selection_audit=region_selection_audit,
        granularity_review=granularity_review,
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
            image_path=_source_image_path(bundle),
        )
    fusion = _fusion_boxes(stage1_localization["regions"], stage2["regions"])
    if stage2.get("skipped"):
        _mark_fusion_not_promotable_when_stage2_skipped(fusion, stage2)
    overlay_path = _render_two_stage_overlay(
        image_path=_source_image_path(bundle),
        structure_regions=stage1_localization["regions"],
        numbered_regions=stage2["regions"],
    )
    if overlay_path:
        fusion["compiled_overlay_path"] = overlay_path
        fusion["full_screen_understanding_overlay_path"] = overlay_path
    context_overlay = _render_message_context_review_overlay(
        image_path=_source_image_path(bundle),
        numbered_regions=stage2["regions"],
        fused_review_boxes=fusion["fused_review_boxes"],
    )
    if context_overlay.get("overlay_path"):
        fusion["message_context_overlay"] = context_overlay
        fusion["message_context_overlay_path"] = context_overlay.get("overlay_path", "")
        fusion["message_context_zoom_path"] = context_overlay.get("zoom_path", "")
    pipeline_contract = _two_pass_pipeline_contract()
    return {
        "contract_version": "learn_two_stage_screen_understanding_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "pipeline_contract": pipeline_contract,
        "flow_compliance": _two_pass_flow_compliance(stage1_localization, stage2),
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
        "model_call_plan": {
            "contract_version": "learn_two_stage_model_call_plan_v1",
            "recommended_model_calls": 2,
            "stage1": {
                "call_index": 1,
                "purpose": "full_screen_structure_region_split",
                "output": (
                    "top/left/right/bottom/center/modal structure regions only; "
                    "no inner button, card, or action numbering"
                ),
            },
            "region_localization": {
                "purpose": "precise_whole_region_localization",
                "output": "complete visual bbox for every structure region; regions may touch and should not shrink to buttons",
            },
            "stage2": {
                "call_index": 2,
                "purpose": "per_region_content_recognition",
                "output": (
                    "top/left/right/bottom regions use direct item numbering; "
                    "center/main content must subdivide first, then number items inside subregions"
                ),
            },
            "interpretation": (
                "This result is the deployable two-pass learning-mode contract. "
                "Current internals may still be deterministic/parser-backed, but downstream checks must validate this flow."
            ),
        },
        "stage1_structure": stage1,
        "stage1_region_localization": stage1_localization,
        "stage2_numbering": stage2,
        "fusion": fusion,
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
        "contract_version": "learn_mode_two_pass_pipeline_contract_v1",
        "source_doc": "docs/LEARN_MODE_TWO_PASS_PIPELINE_CONTRACT.zh-CN.md",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "steps": [
            "bind_and_capture",
            "model_call_1_full_screen_region_split",
            "precise_whole_region_localization",
            "model_call_2_per_region_content_recognition",
            "sidebar_top_bottom_direct_numbering",
            "center_subdivide_then_number",
            "ocr_vision_grounding_gate_fusion",
            "learning_draft_review_only",
            "pathgraph_preview_review_only",
            "human_review_edit",
        ],
        "region_bbox_policy": "complete_visual_region_bbox_regions_may_touch_do_not_shrink_to_buttons",
        "parent_child_boundary_policy": (
            "stage2_children_must_name_parent_region_and_final_fusion_overlay_must_clip_child_bbox_to_parent"
        ),
        "bar_numbering_policy": "button_spacing_groups_controls_only_never_shrinks_region_bbox",
        "center_policy": "subdivide_main_content_before_item_numbering",
        "single_screenshot_patch_policy": "forbidden_as_primary_strategy",
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
        "direct_bar_region_count": len(direct_regions),
        "center_region_count": len(center_regions),
        "center_subdivision_region_count": len(center_with_subdivision),
        "single_screenshot_patch_strategy_used": False,
        "status": "contract_scaffold_ready_for_model_backing",
        "not_accuracy": True,
    }


def build_stage1_region_localization_report(
    *,
    bundle: dict[str, Any],
    screen_inventory: list[dict[str, Any]],
    layout_graph: dict[str, Any],
) -> dict[str, Any]:
    """只运行学习模式第一阶段：整栏定位和校准诊断。"""

    items_by_id = _items_by_id(screen_inventory, layout_graph)
    screen_size = _screen_size_from_bundle(bundle)
    stage1 = _stage1_structure_regions(items_by_id=items_by_id, layout_graph=layout_graph, screen_size=screen_size)
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
    )
    stage1_5_partition = _stage1_5_partition(
        localized_regions=stage1_localization["regions"],
        items_by_id=items_by_id,
        screen_size=screen_size,
        region_selection_audit=region_selection_audit,
        granularity_review=granularity_review,
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
            "stage1_model_call": "page_structure_and_whole_region_localization",
            "stage2_model_call": "per_region_numbering",
        },
        "display_readiness": {
            "screenshot_updates_automatically": bool(fusion.get("compiled_overlay_path")),
            "review_only_boxes_visible": True,
            "requires_click_to_show_boxes": False,
        },
        "interpretation": "Fused two-stage screenshot overlay for review only; not Execute binding.",
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


def _stage1_structure_regions(
    *,
    items_by_id: dict[str, dict[str, Any]],
    layout_graph: dict[str, Any],
    screen_size: dict[str, int] | None = None,
) -> dict[str, Any]:
    zones = layout_graph.get("zones") if isinstance(layout_graph.get("zones"), dict) else {}
    corrected_zone_items: dict[str, list[str]] = {}
    regions: list[dict[str, Any]] = []
    screen = screen_size if isinstance(screen_size, dict) else {}
    for zone_id, zone in zones.items():
        if not isinstance(zone, dict):
            continue
        item_ids = [str(item_id) for item_id in zone.get("item_ids", []) if str(item_id or "").strip()]
        for item_id in item_ids:
            item = items_by_id.get(item_id)
            if not isinstance(item, dict):
                continue
            corrected_zone = _preferred_stage1_zone(item, fallback_zone=str(zone_id), screen_size=screen)
            corrected_zone_items.setdefault(corrected_zone, []).append(item_id)
    for item_id, item in items_by_id.items():
        if any(item_id in ids for ids in corrected_zone_items.values()):
            continue
        corrected_zone_items.setdefault(
            _preferred_stage1_zone(item, fallback_zone="main_content", screen_size=screen),
            [],
        ).append(item_id)

    _split_browser_chrome_from_top_regions(corrected_zone_items, items_by_id=items_by_id, screen_size=screen)
    _merge_content_continuation_regions(corrected_zone_items, items_by_id=items_by_id)
    zone_corrections: list[dict[str, Any]] = []
    zone_corrections.extend(_merge_false_bottom_bar_content_regions(
        corrected_zone_items,
        items_by_id=items_by_id,
        screen_size=screen,
    ))
    _split_right_edge_floating_controls_region(
        corrected_zone_items,
        items_by_id=items_by_id,
        screen_size=screen,
    )
    _split_right_sidebar_region(
        corrected_zone_items,
        items_by_id=items_by_id,
        screen_size=screen,
    )

    for zone_id, item_ids in corrected_zone_items.items():
        zone_items = [items_by_id[item_id] for item_id in item_ids if item_id in items_by_id]
        bbox = _bbox_union([item.get("bbox") for item in zone_items if isinstance(item, dict)])
        if not bbox:
            continue
        region_index = len(regions) + 1
        regions.append(
            {
                "contract_version": "learn_stage1_structure_region_v1",
                "region_no": region_index,
                "region_id": f"structure_region_{_slug(zone_id)}",
                "label": _zone_label(str(zone_id)),
                "zone_id": str(zone_id),
                "bbox": bbox,
                "item_ids": item_ids,
                "item_count": len(zone_items),
                "stage": "stage1_page_structure",
                "source": "layout_graph_zones",
                "bbox_policy": "coarse_structure_region_hint_only",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    regions.sort(key=lambda item: (_bbox_top(item), _bbox_left(item), str(item.get("region_id") or "")))
    for index, region in enumerate(regions, start=1):
        region["region_no"] = index
    return {
        "contract_version": "learn_stage1_structure_regions_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "region_count": len(regions),
        "structure_regions": regions,
        "zone_corrections": zone_corrections,
        "zone_correction_status": "passed_with_correction" if zone_corrections else "clean",
        "model_prompt_intent": "Identify only the page structure and coarse areas; do not enumerate every element yet.",
    }


def _preferred_stage1_zone(
    item: dict[str, Any],
    *,
    fallback_zone: str,
    screen_size: dict[str, int] | None = None,
) -> str:
    bbox = _bbox(item.get("bbox"))
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    if bbox and bbox["x"] <= 110 and bbox["w"] <= 120 and role in {"nav_rail_icon_review_only", "icon_button", "icon", "button"}:
        return "left_nav"
    fallback = str(fallback_zone or "main_content")
    if bbox and _is_top_zone(fallback):
        screen = screen_size if isinstance(screen_size, dict) else {}
        top_limit = _top_bar_height(_int(screen.get("height")))
        if top_limit and bbox["y"] >= top_limit:
            if _looks_like_page_top_navigation_item(item, bbox=bbox, top_limit=top_limit):
                return fallback
            return "main_content"
        if not top_limit and bbox["y"] >= 96:
            return "main_content"
    return fallback


def _is_top_zone(zone_id: str) -> bool:
    lowered = str(zone_id or "").casefold()
    return lowered in {"page_header", "top_bar", "browser_chrome", "header"} or any(
        token in lowered for token in ("header", "top_bar", "browser_chrome")
    )


def _looks_like_page_top_navigation_item(item: dict[str, Any], *, bbox: dict[str, int], top_limit: int) -> bool:
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    if not any(token in role for token in ("nav_text_action", "text_action", "nav_item")):
        return False
    label = str(item.get("label") or item.get("text") or "").strip()
    if not label or len(label) > 40:
        return False
    return bbox["y"] <= max(top_limit * 2, 128)


def _split_browser_chrome_from_top_regions(
    corrected_zone_items: dict[str, list[str]],
    *,
    items_by_id: dict[str, dict[str, Any]],
    screen_size: dict[str, int] | None = None,
) -> None:
    screen = screen_size if isinstance(screen_size, dict) else {}
    height = _int(screen.get("height"))
    chrome_bottom = max(58, min(92, int(height * 0.06) if height else 72))
    top_zone_ids = [zone_id for zone_id in list(corrected_zone_items) if _is_top_zone(zone_id)]
    browser_surface_detected = any(
        _looks_like_browser_chrome_evidence(items_by_id.get(item_id, {}))
        for zone_id in top_zone_ids
        for item_id in corrected_zone_items.get(zone_id, [])
    )
    if not browser_surface_detected:
        return

    moved: list[str] = []
    candidate_zone_ids = [*top_zone_ids]
    if "left_nav" in corrected_zone_items:
        candidate_zone_ids.append("left_nav")
    for zone_id in candidate_zone_ids:
        if zone_id == "browser_chrome":
            continue
        kept: list[str] = []
        for item_id in corrected_zone_items.get(zone_id, []):
            item = items_by_id.get(item_id, {})
            if _is_browser_chrome_top_item(
                item,
                chrome_bottom=chrome_bottom,
                screen_width=_int(screen.get("width")),
            ) or (
                zone_id == "left_nav"
                and _is_top_left_browser_chrome_fragment(item, chrome_bottom=chrome_bottom)
            ):
                moved.append(item_id)
            else:
                kept.append(item_id)
        corrected_zone_items[zone_id] = kept
    if moved:
        existing = corrected_zone_items.get("browser_chrome", [])
        corrected_zone_items["browser_chrome"] = [*existing, *moved]
    for zone_id in list(corrected_zone_items):
        if not corrected_zone_items.get(zone_id):
            corrected_zone_items.pop(zone_id, None)


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
        )
    )


def _is_browser_chrome_top_item(item: dict[str, Any], *, chrome_bottom: int, screen_width: int = 0) -> bool:
    bbox = _bbox(item.get("bbox"))
    if not bbox:
        return False
    if _looks_like_browser_chrome_evidence(item):
        return True
    role = str(item.get("role") or item.get("item_type") or "").casefold()
    if bbox["y"] > chrome_bottom:
        return False
    if any(token in role for token in ("icon", "button", "control")):
        return True
    label = str(item.get("label") or item.get("text") or "").strip()
    if label in {"←", "→", "↻", "⌂", "★", "☆", "+", "×", "x"}:
        return True
    return bool(screen_width and bbox["x"] >= int(screen_width * 0.85) and len(label) <= 12)


def _is_top_left_browser_chrome_fragment(item: dict[str, Any], *, chrome_bottom: int) -> bool:
    bbox = _bbox(item.get("bbox"))
    if not bbox:
        return False
    label = str(item.get("label") or item.get("text") or "").strip()
    return (
        bbox["x"] <= 110
        and bbox["y"] <= chrome_bottom
        and bbox["w"] <= 80
        and bbox["h"] <= 40
        and len(label) <= 3
    )


def _merge_content_continuation_regions(
    corrected_zone_items: dict[str, list[str]],
    *,
    items_by_id: dict[str, dict[str, Any]],
) -> None:
    main_ids = corrected_zone_items.get("main_content")
    lower_ids = corrected_zone_items.get("lower_content")
    if not main_ids or not lower_ids:
        return
    main_bbox = _bbox_union([items_by_id[item_id].get("bbox") for item_id in main_ids if item_id in items_by_id])
    lower_bbox = _bbox_union([items_by_id[item_id].get("bbox") for item_id in lower_ids if item_id in items_by_id])
    if not main_bbox or not lower_bbox:
        return
    horizontal_overlap = _horizontal_overlap_ratio(main_bbox, lower_bbox)
    vertical_gap = lower_bbox["y"] - (main_bbox["y"] + main_bbox["h"])
    if horizontal_overlap >= 0.35 and vertical_gap <= 96:
        main_ids.extend(item_id for item_id in lower_ids if item_id not in main_ids)
        corrected_zone_items.pop("lower_content", None)


def _merge_false_bottom_bar_content_regions(
    corrected_zone_items: dict[str, list[str]],
    *,
    items_by_id: dict[str, dict[str, Any]],
    screen_size: dict[str, int],
) -> list[dict[str, Any]]:
    bottom_ids = corrected_zone_items.get("bottom_bar")
    if not bottom_ids:
        return []
    target_zone = "primary_area" if corrected_zone_items.get("primary_area") else "main_content"
    target_ids = corrected_zone_items.get(target_zone)
    if not target_ids:
        return []
    width = _int(screen_size.get("width"))
    height = _int(screen_size.get("height"))
    bottom_bbox = _bbox_union([items_by_id[item_id].get("bbox") for item_id in bottom_ids if item_id in items_by_id])
    target_bbox = _bbox_union([items_by_id[item_id].get("bbox") for item_id in target_ids if item_id in items_by_id])
    if not bottom_bbox or not target_bbox or width <= 0 or height <= 0:
        return []
    full_width_bar = bottom_bbox["x"] <= max(12, int(width * 0.02)) and bottom_bbox["w"] >= int(width * 0.85)
    anchored_to_screen_bottom = bottom_bbox["y"] + bottom_bbox["h"] >= height - max(24, int(height * 0.035))
    if full_width_bar and anchored_to_screen_bottom:
        return []
    vertical_overlap = _vertical_overlap_ratio(bottom_bbox, target_bbox)
    vertical_gap = bottom_bbox["y"] - (target_bbox["y"] + target_bbox["h"])
    horizontal_overlap = _horizontal_overlap_ratio(bottom_bbox, target_bbox)
    looks_like_primary_continuation = (
        horizontal_overlap >= 0.35
        and (
            vertical_overlap >= 0.08
            or abs(vertical_gap) <= max(96, int(height * 0.12))
            or bottom_bbox["y"] < target_bbox["y"] + target_bbox["h"]
        )
    )
    narrow_or_not_aligned = bottom_bbox["x"] > max(12, int(width * 0.02)) or bottom_bbox["w"] < int(width * 0.85)
    if not (looks_like_primary_continuation and narrow_or_not_aligned):
        return []
    target_ids.extend(item_id for item_id in bottom_ids if item_id not in target_ids)
    corrected_zone_items.pop("bottom_bar", None)
    return [
        {
            "contract_version": "learn_stage1_zone_correction_v1",
            "correction": "bottom_bar_content_merged_into_primary_region",
            "source_zone": "bottom_bar",
            "target_zone": target_zone,
            "item_ids": list(bottom_ids),
            "source_bbox": deepcopy(bottom_bbox),
            "target_bbox_before_merge": deepcopy(target_bbox),
            "reason": "narrow_or_not_left_aligned_bottom_like_region_is_primary_content_continuation",
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
    ]


def _split_right_sidebar_region(
    corrected_zone_items: dict[str, list[str]],
    *,
    items_by_id: dict[str, dict[str, Any]],
    screen_size: dict[str, int],
) -> None:
    width = _int(screen_size.get("width"))
    height = _int(screen_size.get("height"))
    if width <= 0 or height <= 0 or "right_sidebar" in corrected_zone_items:
        return
    source_zone = ""
    source_ids: list[str] = []
    for zone_id in ("primary_area", "main_content"):
        ids = corrected_zone_items.get(zone_id)
        if ids:
            source_zone = zone_id
            source_ids = ids
            break
    if not source_ids:
        return
    items = [(item_id, items_by_id.get(item_id)) for item_id in source_ids]
    boxes = [(item_id, item, _bbox(item.get("bbox")) if isinstance(item, dict) else None) for item_id, item in items]
    boxes = [(item_id, item, bbox) for item_id, item, bbox in boxes if isinstance(item, dict) and bbox]
    if len(boxes) < 3:
        return
    right_candidates = [
        (item_id, item, bbox)
        for item_id, item, bbox in boxes
        if bbox["x"] >= int(width * 0.62)
        and bbox["x"] + bbox["w"] >= int(width * 0.9)
        and bbox["w"] <= int(width * 0.36)
        and bbox["h"] >= 32
        and bbox["y"] >= max(48, int(height * 0.08))
    ]
    if len(right_candidates) < 2:
        return
    candidate_union = _bbox_union([bbox for _, _, bbox in right_candidates])
    if not candidate_union:
        return
    if candidate_union["w"] > int(width * 0.36):
        return
    if candidate_union["h"] < int(height * 0.35):
        return
    if _right_strip_looks_like_card_grid(right_candidates, boxes):
        return
    left_context = [
        bbox
        for item_id, item, bbox in boxes
        if item_id not in {candidate_id for candidate_id, _, _ in right_candidates}
        and bbox["x"] < candidate_union["x"] - max(24, int(width * 0.03))
        and _vertical_overlap_ratio(bbox, candidate_union) >= 0.25
    ]
    if not left_context:
        return
    right_ids = _right_sidebar_item_ids_from_strip(
        right_candidates=right_candidates,
        all_boxes=boxes,
        strip_bbox=candidate_union,
    )
    corrected_zone_items[source_zone] = [item_id for item_id in source_ids if item_id not in set(right_ids)]
    corrected_zone_items["right_sidebar"] = right_ids


def _split_right_edge_floating_controls_region(
    corrected_zone_items: dict[str, list[str]],
    *,
    items_by_id: dict[str, dict[str, Any]],
    screen_size: dict[str, int],
) -> None:
    width = _int(screen_size.get("width"))
    height = _int(screen_size.get("height"))
    if width <= 0 or height <= 0 or "floating_controls" in corrected_zone_items:
        return
    source_zone = ""
    source_ids: list[str] = []
    for zone_id in ("primary_area", "main_content"):
        ids = corrected_zone_items.get(zone_id)
        if ids:
            source_zone = zone_id
            source_ids = ids
            break
    if not source_ids:
        return
    candidates: list[str] = []
    for item_id in source_ids:
        item = items_by_id.get(item_id)
        if not isinstance(item, dict):
            continue
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            continue
        if _looks_like_right_edge_floating_control(item, bbox=bbox, width=width, height=height):
            candidates.append(item_id)
    if not candidates:
        return
    has_scrollbar = any(_looks_like_scrollbar_or_edge_strip(items_by_id[item_id], bbox=_bbox(items_by_id[item_id].get("bbox")) or {}, width=width, height=height) for item_id in candidates)
    if len(candidates) < 2 and not has_scrollbar:
        return
    corrected_zone_items[source_zone] = [item_id for item_id in source_ids if item_id not in set(candidates)]
    corrected_zone_items["floating_controls"] = candidates


def _looks_like_right_edge_floating_control(
    item: dict[str, Any],
    *,
    bbox: dict[str, int],
    width: int,
    height: int,
) -> bool:
    if width <= 0 or height <= 0:
        return False
    if _looks_like_scrollbar_or_edge_strip(item, bbox=bbox, width=width, height=height):
        return True
    role = " ".join(
        str(item.get(key) or "").casefold()
        for key in ("role", "item_type", "label", "item_id")
    )
    right_edge = bbox["x"] + bbox["w"]
    near_right_edge = right_edge >= int(width * 0.965) or bbox["x"] >= int(width * 0.94)
    compact_control = bbox["w"] <= max(48, int(width * 0.055)) and bbox["h"] <= max(56, int(height * 0.08))
    below_chrome = bbox["y"] >= max(48, int(height * 0.06))
    control_role = any(token in role for token in ("floating", "translate", "tool", "button", "icon", "control"))
    return near_right_edge and compact_control and below_chrome and control_role


def _looks_like_scrollbar_or_edge_strip(
    item: dict[str, Any],
    *,
    bbox: dict[str, int],
    width: int,
    height: int,
) -> bool:
    if width <= 0 or height <= 0 or not bbox:
        return False
    role = " ".join(
        str(item.get(key) or "").casefold()
        for key in ("role", "item_type", "label", "item_id")
    )
    right_edge = bbox["x"] + bbox["w"]
    return (
        ("scroll" in role or "scrollbar" in role)
        and right_edge >= width - max(10, int(width * 0.01))
        and bbox["w"] <= max(16, int(width * 0.025))
        and bbox["h"] >= int(height * 0.30)
    )


def _right_sidebar_item_ids_from_strip(
    *,
    right_candidates: list[tuple[str, dict[str, Any], dict[str, int]]],
    all_boxes: list[tuple[str, dict[str, Any], dict[str, int]]],
    strip_bbox: dict[str, int],
) -> list[str]:
    right_ids = {item_id for item_id, _, _ in right_candidates}
    for item_id, _, bbox in all_boxes:
        if item_id in right_ids:
            continue
        cx = bbox["x"] + bbox["w"] / 2
        cy = bbox["y"] + bbox["h"] / 2
        if (
            strip_bbox["x"] <= cx <= strip_bbox["x"] + strip_bbox["w"]
            and strip_bbox["y"] <= cy <= strip_bbox["y"] + strip_bbox["h"]
        ):
            right_ids.add(item_id)
    return [item_id for item_id, _, _ in all_boxes if item_id in right_ids]


def _right_strip_looks_like_card_grid(
    right_candidates: list[tuple[str, dict[str, Any], dict[str, int]]],
    all_boxes: list[tuple[str, dict[str, Any], dict[str, int]]],
) -> bool:
    right_ids = {item_id for item_id, _, _ in right_candidates}
    for _, right_item, right_bbox in right_candidates:
        if not _is_card_like_region_item(right_item):
            continue
        same_row_card_count = 0
        for item_id, item, bbox in all_boxes:
            if item_id in right_ids or not _is_card_like_region_item(item):
                continue
            if _vertical_overlap_ratio(right_bbox, bbox) < 0.55:
                continue
            height_ratio = min(right_bbox["h"], bbox["h"]) / max(1, max(right_bbox["h"], bbox["h"]))
            if height_ratio >= 0.55 and bbox["x"] < right_bbox["x"]:
                same_row_card_count += 1
        if same_row_card_count >= 2:
            return True
    return False


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
        for extra_key in ("right_edge_preservation",):
            extra_value = calibration.get(extra_key)
            if isinstance(extra_value, dict):
                coordinate_validation[extra_key] = deepcopy(extra_value)
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
    _record_horizontal_bar_content_lane(localized_regions, screen_size=screen)
    _clamp_topbar_against_main_regions(localized_regions)
    _partition_sidebars_against_horizontal_bars(localized_regions)
    _expand_main_regions_to_available_lane(localized_regions, screen_size=screen)
    _clamp_main_regions_against_sidebars(localized_regions)
    _extend_browser_page_header_to_primary_boundary(localized_regions, items_by_id=all_items, screen_size=screen)
    _ensure_browser_right_edge_review_region(localized_regions, items_by_id=all_items, screen_size=screen)
    localized_regions, suppressed_duplicates = _suppress_contained_duplicate_structure_regions(localized_regions)
    return {
        "contract_version": "learn_stage1_region_localization_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "localized_region_count": len(localized_regions),
        "suppressed_duplicate_region_count": len(suppressed_duplicates),
        "suppressed_duplicate_regions": suppressed_duplicates,
        "regions": localized_regions,
        "model_prompt": STAGE1_REGION_LOCALIZATION_PROMPT,
        "model_prompt_intent": (
            "For each coarse structure region, precisely localize the full visible region boundary before per-region numbering."
        ),
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
) -> None:
    width = _int(screen_size.get("width"))
    height = _int(screen_size.get("height"))
    if width <= 0 or height <= 0 or not _items_have_browser_chrome_evidence(items_by_id.values()):
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
    main_boxes = [
        _bbox(region.get("bbox") or region.get("precise_bbox"))
        for region in localized_regions
        if _stage1_region_family(region) == "main_content"
    ]
    main_boxes = [box for box in main_boxes if box]
    if not main_boxes:
        return
    for region in localized_regions:
        if _stage1_region_family(region) != "top_bar":
            continue
        bbox = _bbox(region.get("bbox") or region.get("precise_bbox"))
        if not bbox:
            continue
        overlapping_main_tops = [
            box["y"]
            for box in main_boxes
            if box["y"] > bbox["y"]
            and _horizontal_overlap_ratio(bbox, box) >= 0.20
            and bbox["y"] + bbox["h"] > box["y"]
        ]
        if not overlapping_main_tops:
            continue
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
                continue
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
            visual_rail_width = max(right + 18, int((width or right) * 0.08))
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
        item_boxes = [_bbox(item.get("bbox")) for item in region_items]
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
        top_h = rough["h"]
        item_boxes = [_bbox(item.get("bbox")) for item in region_items if not _is_section_hint(item)]
        item_boxes = [box for box in item_boxes if box]
        if height > 0:
            top_h = max(top_h, max(56, int(height * 0.09)))
        y = 0
        if item_boxes:
            min_item_y = min(box["y"] for box in item_boxes)
            max_item_bottom = max(box["y"] + box["h"] for box in item_boxes)
            if min_item_y > max(56, int((height or 0) * 0.045)):
                y = max(0, min_item_y - 8)
                top_h = max(1, max_item_bottom + 8 - y)
        return {
            "bbox": {"x": 0, "y": y, "w": width or rough["w"], "h": top_h},
            "status": "heuristic_calibrated_top_bar",
            "strategy": "top_bar_height_clamped_before_content_title",
            "evidence": "top/header region is clamped so content title and cards are excluded",
        }

    if zone_id in {"primary_area", "main_content", "lower_content"} or "main" in region_id or "primary" in region_id:
        browser_surface = _items_have_browser_chrome_evidence(items_by_id.values())
        content_boxes = [
            _bbox(item.get("bbox"))
            for item in region_items
            if not _is_section_hint(item) and not _is_left_nav_item(item)
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
    if bbox["x"] <= 110 and bbox["w"] <= 120 and role in {"nav_rail_icon_review_only", "icon_button", "icon", "button"}:
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
    text = " ".join(
        " ".join(
            [
                str(items_by_id.get(str(item_id), {}).get("role") or ""),
                str(items_by_id.get(str(item_id), {}).get("item_type") or ""),
                str(items_by_id.get(str(item_id), {}).get("label") or ""),
            ]
        ).casefold()
        for item_id in item_ids
    )
    evidence: list[str] = []
    if any(token in text for token in ("conversation", "chat list", "session list", "会话", "联系人")):
        evidence.append("conversation_or_list_pane_signal")
    if any(token in text for token in ("message", "chat thread", "bubble", "消息", "聊天")):
        evidence.append("message_thread_signal")
    if any(token in text for token in ("composer", "input area", "send button", "输入框", "发送")):
        evidence.append("bottom_composer_signal")
    return evidence


def _stage1_5_partition(
    *,
    localized_regions: list[dict[str, Any]],
    items_by_id: dict[str, dict[str, Any]],
    screen_size: dict[str, int],
    region_selection_audit: dict[str, Any],
    granularity_review: dict[str, Any],
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
                subregions.extend(_stage1_5_chat_subregions(region=region, items_by_id=items_by_id))
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
        annotated.append(item)
    return annotated, {
        "contract_version": "learn_stage1_5_stage2_selection_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "policy": "stage1_5_partitions_are_candidates; only stable main-content subregions may replace Stage2 input regions",
        "eligible_count": len(accepted),
        "rejected_count": len(rejected),
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
                if item_id in seed_item_ids or (bbox and item_bbox and _bbox_substantially_inside_parent(bbox, item_bbox)):
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
    return [
        _stage1_5_subregion(
            region=region,
            role="content_column",
            label="Stage1.5 content column",
            bbox=union,
            item_ids=[str(item.get("item_id") or item.get("candidate_id") or "") for item in candidates],
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


def _stage1_5_chat_subregions(
    *,
    region: dict[str, Any],
    items_by_id: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    parent_bbox = _bbox(region.get("bbox") or region.get("precise_bbox"))
    if not parent_bbox:
        return []
    groups: dict[str, list[dict[str, Any]]] = {
        "conversation_list": [],
        "message_thread": [],
        "bottom_composer": [],
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
        role = _stage1_5_chat_item_role(item)
        if role:
            groups[role].append(item)
    if not groups["conversation_list"]:
        groups["conversation_list"].extend(
            _infer_stage1_5_left_list_pane_items(region=region, items_by_id=items_by_id, parent_bbox=parent_bbox)
        )
    _promote_stage1_5_composer_adjacent_items(
        groups=groups,
        region=region,
        items_by_id=items_by_id,
        parent_bbox=parent_bbox,
    )
    labels = {
        "conversation_list": "Stage1.5 conversation/list pane",
        "message_thread": "Stage1.5 message/detail pane",
        "bottom_composer": "Stage1.5 bottom composer",
    }
    subregions: list[dict[str, Any]] = []
    bottom_composer_bbox = _clip_bbox_to_parent(
        _bbox_union([_bbox(item.get("bbox")) for item in groups["bottom_composer"]]),
        parent_bbox,
    )
    bottom_composer_cut_top = bottom_composer_bbox["y"] if bottom_composer_bbox else None
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
            ):
                bottom_composer_cut_top = composer_evidence_bbox["y"]
    message_thread_anchor_bbox = _clip_bbox_to_parent(
        _bbox_union([_bbox(item.get("bbox")) for item in groups["message_thread"]]),
        parent_bbox,
    )
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
        if role in {"conversation_list", "message_thread"} and bottom_composer_cut_top is not None:
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
    return subregions


def _stage1_5_chat_item_role(item: dict[str, Any]) -> str:
    value = " ".join(
        str(item.get(key) or "").casefold()
        for key in ("item_id", "role", "item_type", "label")
    )
    if any(token in value for token in ("conversation", "chat list", "session list", "会话", "联系人", "list_pane")):
        return "conversation_list"
    if any(token in value for token in ("message_thread", "chat thread", "bubble", "消息", "聊天", "detail_pane")):
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
        value = " ".join(str(item.get(key) or "").casefold() for key in ("role", "item_type", "label"))
        if any(token in value for token in ("message_thread", "composer", "send button", "发送", "群公告")):
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


def _stage2_numbering(
    localized_regions: list[dict[str, Any]],
    *,
    items_by_id: dict[str, dict[str, Any]],
    supplemental_text_items: list[dict[str, Any]] | None = None,
    image_path: str = "",
) -> dict[str, Any]:
    regions: list[dict[str, Any]] = []
    total = 0
    for region in localized_regions:
        region_no = _int(region.get("region_no"))
        numbered_items: list[dict[str, Any]] = []
        region_item_ids = region.get("item_ids") if isinstance(region.get("item_ids"), list) else []
        region_items = [items_by_id[str(item_id)] for item_id in region_item_ids if str(item_id) in items_by_id]
        region_items = [item for item in region_items if not _is_section_hint(item)]
        region_bbox = _bbox(region.get("bbox")) or _bbox(region.get("precise_bbox")) or {}
        region_items = [item for item in region_items if _item_belongs_to_region_bbox(item, region_bbox)]
        region_items = _append_supplemental_text_items_for_region(
            region_items,
            supplemental_text_items or [],
            region_bbox=region_bbox,
        )
        region_items.sort(key=lambda item: (_bbox_top(item), _bbox_left(item), str(item.get("label") or "")))
        for item_index, item in enumerate(region_items, start=1):
            bbox = _bbox(item.get("bbox"))
            if not bbox:
                continue
            numbered_items.append(
                {
                    "contract_version": "learn_stage2_numbered_item_v1",
                    "number": f"{region_no}.{item_index}",
                    "item_id": str(item.get("item_id") or item.get("candidate_id") or f"item_{region_no}_{item_index}"),
                    "label": str(item.get("label") or item.get("text") or ""),
                    "role": str(item.get("role") or item.get("item_type") or "review_only"),
                    "bbox": bbox,
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
            )
        stage1_5_subregion = (
            region.get("input_stage1_5_subregion") if isinstance(region.get("input_stage1_5_subregion"), dict) else {}
        )
        stage1_5_role = str(stage1_5_subregion.get("role") or "").casefold()
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
            _primary_content_subregion_groups(region=region, numbered_items=numbered_items)
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
            subregion_groups = _semantic_parent_groups(region=region, numbered_items=numbered_items)
            main_content_subdivision = _main_content_subdivision_report(region, subregion_groups)
        elif grouping_strategy == "primary_region_homogeneous_grouping_with_visual_card_segmenter":
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
            numbered_items, chat_image_synthesis = _synthesize_chat_image_messages(
                numbered_items,
                image_path=image_path,
                region_bbox=region_bbox,
            )
            numbered_items, text_button_hit_area = _normalize_text_only_button_hit_areas(
                numbered_items,
                region_bbox=region_bbox,
            )
            numbered_items, message_bubble_hit_area = _normalize_text_only_message_bubble_backgrounds(
                numbered_items,
                region_bbox=region_bbox,
            )
            numbered_items, message_card_boundary_clip = _clip_message_cards_at_following_start_anchors(numbered_items)
            subregion_groups = _primary_content_subregion_groups(region=region, numbered_items=numbered_items)
            main_content_subdivision = _main_content_subdivision_report(region, subregion_groups)
            visual_refinement["media_card_synthesis"] = media_card_synthesis
            visual_refinement["partial_visible_card_synthesis"] = partial_card_synthesis
            visual_refinement["chat_image_message_synthesis"] = chat_image_synthesis
            visual_refinement["text_button_hit_area"] = text_button_hit_area
            visual_refinement["message_bubble_hit_area"] = message_bubble_hit_area
            visual_refinement["message_card_boundary_clip"] = message_card_boundary_clip
        numbered_items, subregion_groups = _apply_semantic_group_child_roles(numbered_items, subregion_groups)
        numbered_items, subregion_groups, region_content_boundary = _enforce_region_content_boundary(
            numbered_items,
            subregion_groups,
            region_bbox=region_bbox,
            region_id=str(region.get("region_id") or ""),
            region_label=str(region.get("label") or ""),
        )
        main_content_subdivision = _main_content_subdivision_report(region, subregion_groups)
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
                "region_processing_contract": region_processing_contract,
                "bar_numbering": bar_numbering_report,
                "main_content_subdivision": main_content_subdivision,
                "subregion_groups": subregion_groups,
                "region_content_boundary": region_content_boundary,
                "visual_small_control_refinement": visual_refinement,
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
        "regions": regions,
    }


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
    family = _stage1_region_family(region)
    if family == "top_bar":
        control_band_h = min(bbox["h"], max(56, min(96, int(round(bbox["h"] * 0.65)))))
        return {**bbox, "h": max(1, control_band_h)}
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
        left_bbox = _bbox(left.get("bbox"))
        if not left_bbox:
            continue
        for right_index in range(left_index + 1, len(updated)):
            right = updated[right_index]
            right_bbox = _bbox(right.get("bbox"))
            if not right_bbox:
                continue
            overlap = min(_bbox_overlap_ratio(left_bbox, right_bbox), _bbox_overlap_ratio(right_bbox, left_bbox))
            if overlap < 0.18:
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
    if role in {"media_card_group", "message_item"}:
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
    "list_group",
    "list_row",
    "member_list_region",
    "conversation_row",
    "message_item",
    "input_toolbar_region",
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
    parent_ids = [str(group.get("group_id") or "") for group in memberships if group.get("group_id")]
    inside_ungrouped_review_region = "ungrouped_review_region" in roles
    is_model_card_text_evidence = bool(roles & _DETAIL_PARENT_GROUP_ROLES) and _is_model_card_like_text_evidence(item)
    is_child_evidence = inside_ungrouped_review_region or (
        bool(roles & _DETAIL_PARENT_GROUP_ROLES)
        and (
            item_role in _DETAIL_CHILD_EVIDENCE_ROLES
            or (bool(roles & _HERO_PARENT_GROUP_ROLES) and item_role in _HERO_CHILD_EVIDENCE_EXTRA_ROLES)
            or is_model_card_text_evidence
        )
    )
    demotion_reason = (
        "ungrouped_review_region_detail_only"
        if inside_ungrouped_review_region
        else ("model_card_like_text_evidence_inside_parent_group" if is_model_card_text_evidence else "")
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
        if _is_browser_chrome_region(region):
            continue
        membership_by_item_id = _group_membership_for_region(region)
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
        if _is_browser_chrome_region(region):
            continue
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
    candidates = metadata.get("text_lines") if isinstance(metadata.get("text_lines"), list) else []
    result: list[dict[str, Any]] = []
    for index, child in enumerate(candidates):
        if not isinstance(child, dict):
            continue
        bbox = _bbox(child.get("bbox"))
        label = str(child.get("label") or child.get("text") or "").strip()
        if not label and not bbox:
            continue
        result.append(
            {
                "child_id": str(child.get("child_id") or child.get("id") or f"text_line_{index + 1}"),
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


def _primary_content_subregion_groups(*, region: dict[str, Any], numbered_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    card_items = [item for item in numbered_items if _looks_like_card_item(item)]
    rows = _group_card_items_by_row(card_items)
    groups: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        if len(row) < 2:
            continue
        bbox = _bbox_union([item.get("bbox") for item in row])
        if not bbox:
            continue
        partial_row = all(str(item.get("role") or "") == "partial_visible_card" for item in row)
        groups.append(
            {
                "contract_version": "learn_stage2_subregion_group_v1",
                "group_id": f"{'partial_visible_card_row' if partial_row else 'visual_card_row'}_{index}",
                "label": f"{'partial visible card row' if partial_row else 'visual media card row'} {index}",
                "role": "partial_visible_card_group" if partial_row else "media_card_group",
                "bbox": bbox,
                "expected_item_role": "partial_visible_card" if partial_row else "media_card",
                "homogeneity_rule": "same row and similar card/review item role from current screen inventory",
                "member_numbers": [str(item.get("number") or "") for item in row],
                "member_item_ids": [str(item.get("item_id") or "") for item in row],
                "source": "stage2_primary_content_card_row_grouping",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    groups.extend(_semantic_parent_groups(region=region, numbered_items=numbered_items))
    groups.extend(_section_parent_groups(numbered_items=numbered_items, content_groups=groups))
    groups = _ensure_primary_items_have_subregion_parent(region=region, numbered_items=numbered_items, groups=groups)
    groups.sort(key=lambda group: (_bbox_top(group), _bbox_left(group), str(group.get("group_id") or "")))
    return groups


def _ensure_primary_items_have_subregion_parent(
    *,
    region: dict[str, Any],
    numbered_items: list[dict[str, Any]],
    groups: list[dict[str, Any]],
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
            _append_group_member(containing_groups[0][1], item)
            assigned.add(item_id)
        else:
            orphan_items.append(item)

    if len(orphan_items) < 4:
        return updated_groups

    for index, cluster in enumerate(_cluster_orphan_items_by_vertical_band(orphan_items), start=1):
        cluster_bbox = _bbox_union([item.get("bbox") for item in cluster])
        if not cluster_bbox:
            continue
        bounded = _intersect_bbox(region_bbox, _expand_bbox(cluster_bbox, pad_x=8, pad_y=8))
        if not bounded:
            continue
        updated_groups.append(
            {
                "contract_version": "learn_stage2_subregion_group_v1",
                "group_id": f"ungrouped_review_region_{index}",
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


def _append_group_member(group: dict[str, Any], item: dict[str, Any]) -> None:
    number = str(item.get("number") or "").strip()
    item_id = str(item.get("item_id") or "").strip()
    member_numbers = group.setdefault("member_numbers", [])
    if isinstance(member_numbers, list) and number and number not in member_numbers:
        member_numbers.append(number)
    member_item_ids = group.setdefault("member_item_ids", [])
    if isinstance(member_item_ids, list) and item_id and item_id not in member_item_ids:
        member_item_ids.append(item_id)
    repairs = group.setdefault("membership_repairs", [])
    if isinstance(repairs, list):
        repairs.append(
            {
                "contract_version": "learn_stage2_group_membership_repair_v1",
                "item_id": item_id,
                "number": number,
                "reason": "item_bbox_inside_group_bbox_but_missing_member_link",
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )


def _cluster_orphan_items_by_vertical_band(items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    ordered = [item for item in items if _bbox(item.get("bbox"))]
    ordered.sort(key=lambda item: (_bbox_top(item), _bbox_left(item), str(item.get("item_id") or "")))
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


def _semantic_parent_groups(*, region: dict[str, Any], numbered_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    groups.extend(_topbar_control_parent_groups(region=region, numbered_items=numbered_items))
    groups.extend(_notice_parent_groups(region=region, numbered_items=numbered_items))
    groups.extend(_list_row_parent_groups(region=region, numbered_items=numbered_items))
    groups.extend(_hero_panel_parent_groups(region=region, numbered_items=numbered_items))
    groups.extend(_member_list_parent_groups(region=region, numbered_items=numbered_items))
    groups.extend(_conversation_row_parent_groups(region=region, numbered_items=numbered_items))
    groups.extend(_message_parent_groups(region=region, numbered_items=numbered_items))
    groups.extend(_input_toolbar_parent_groups(region=region, numbered_items=numbered_items))
    return groups


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
    return groups


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
    controls.sort(key=lambda item: (_bbox_left(item), _bbox_top(item)))
    control_union = _bbox_union([item.get("bbox") for item in controls])
    if not control_union:
        return []
    strip_top = max(region_bbox["y"], min(control_union["y"] - 8, region_bbox["y"] + max(0, int(region_bbox["h"] * 0.12))))
    strip_bottom = min(
        region_bbox["y"] + region_bbox["h"],
        max(control_union["y"] + control_union["h"] + 8, region_bbox["y"] + min(region_bbox["h"], 56)),
    )
    strip_bbox = _clip_bbox(
        region_bbox,
        {
            "x": control_union["x"],
            "y": strip_top,
            "w": control_union["w"],
            "h": max(1, strip_bottom - strip_top),
        },
    )
    strip_group = {
        "contract_version": "learn_stage2_subregion_group_v1",
        "group_id": "topbar_control_strip_1",
        "label": "top/header control strip",
        "role": "topbar_control_strip",
        "bbox": strip_bbox,
        "child_group_roles": _unique_roles(controls),
        "member_numbers": [str(item.get("number") or "") for item in controls],
        "member_item_ids": [str(item.get("item_id") or "") for item in controls],
        "parent_child_policy": "topbar_controls_share_display_only_strip_parent",
        "source": "stage2_direct_bar_parent_reconstruction",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }
    return [
        strip_group,
        *_topbar_control_cluster_groups(controls=controls, region_bbox=region_bbox, strip_bbox=strip_bbox),
        *_topbar_sparse_center_semantic_groups(controls=controls, region_bbox=region_bbox, strip_bbox=strip_bbox),
    ]


def _topbar_control_cluster_groups(
    *,
    controls: list[dict[str, Any]],
    region_bbox: dict[str, int],
    strip_bbox: dict[str, int],
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
                "group_id": f"topbar_control_cluster_{index}",
                "label": f"top/header control cluster {index}",
                "role": "topbar_control_cluster",
                "bbox": cluster_bbox,
                "child_group_roles": _unique_roles(cluster),
                "member_numbers": [str(item.get("number") or "") for item in cluster],
                "member_item_ids": [str(item.get("item_id") or "") for item in cluster],
                "parent_group_id": "topbar_control_strip_1",
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
                "group_id": f"topbar_semantic_group_{len(semantic_groups) + 1}",
                "label": f"top/header semantic status group {len(semantic_groups) + 1}",
                "role": "topbar_semantic_group",
                "bbox": group_bbox,
                "child_group_roles": _unique_roles(members),
                "member_numbers": [str(item.get("number") or "") for item in members],
                "member_item_ids": [str(item.get("item_id") or "") for item in members],
                "parent_group_id": "topbar_control_strip_1",
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
    for anchor in sorted(numbered_items, key=lambda item: (_bbox_top(item), _bbox_left(item))):
        if not _looks_like_notice_anchor(anchor):
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


def _conversation_row_parent_groups(*, region: dict[str, Any], numbered_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not _is_primary_region_id(str(region.get("region_id") or "")):
        return []
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
    ]
    if len(candidates) < 3:
        return []
    rows: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_bbox: dict[str, int] | None = None
    for item in candidates:
        bbox = _bbox(item.get("bbox"))
        if not bbox:
            continue
        if not current or current_bbox is None:
            current = [item]
            current_bbox = bbox
            continue
        row_gap = bbox["y"] - (current_bbox["y"] + current_bbox["h"])
        same_row = abs((_bbox_center_y_value(bbox)) - (_bbox_center_y_value(current_bbox))) <= 24 or row_gap <= 12
        if same_row:
            current.append(item)
            current_bbox = _bbox_union([current_bbox, bbox])
        else:
            if len(current) >= 2:
                rows.append(current)
            current = [item]
            current_bbox = bbox
    if len(current) >= 2:
        rows.append(current)
    groups: list[dict[str, Any]] = []
    for row in rows:
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


def _near_notice_anchor(candidate_bbox: dict[str, int], anchor_bbox: dict[str, int]) -> bool:
    vertical_gap = candidate_bbox["y"] - (anchor_bbox["y"] + anchor_bbox["h"])
    if vertical_gap < -12 or vertical_gap > 180:
        return False
    if _horizontal_overlap_ratio(candidate_bbox, anchor_bbox) >= 0.08:
        return True
    return abs(candidate_bbox["x"] - anchor_bbox["x"]) <= 96


def _looks_like_notice_anchor(item: dict[str, Any]) -> bool:
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
    role = str(item.get("role") or item.get("item_type") or "").casefold()
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
    section_titles = [item for item in numbered_items if _looks_like_section_title(item)]
    if not section_titles or not content_groups:
        return []
    used_title_ids: set[str] = set()
    parents: list[dict[str, Any]] = []
    eligible_groups = [
        group
        for group in content_groups
        if str(group.get("role") or "") in {
            "media_card_group",
            "partial_visible_card_group",
            "list_group",
            "form_group",
            "table_group",
        }
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
        expanded_bbox = _media_card_bbox_with_children(slot_card_bbox, child_items, parent_bbox=region_bbox)
        label = _media_card_label(child_items, fallback=f"media card {index}")
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
        "source": "visual_card_segmenter",
    }


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
    target_height = int(round(median_height))
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
    if inferred["w"] < median_width * 0.75 or inferred["h"] < median_height * 0.75:
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
    if slot_inference.get("applied") and reasons == ["visual_card_slot_smaller_than_dense_row_peers"]:
        reasons = []
    return {
        "contract_version": "learn_media_card_parent_validation_v1",
        "complete": not reasons,
        "reasons": reasons,
        "visual_bbox": visual_bbox,
        "original_visual_bbox": original_visual_bbox,
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
    if len(candidates) < 2:
        return numbered_items, {
            "applied": False,
            "reason": "insufficient_bottom_edge_text_fragments",
            "candidate_count": len(candidates),
            "synthesized_count": 0,
            "suppressed_child_item_count": 0,
        }
    clusters = _cluster_partial_card_fragments(candidates)
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
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    anchors = [item for item in numbered_items if _looks_like_chat_surface_anchor(item)]
    if not anchors:
        return numbered_items, {
            "applied": False,
            "reason": "no_chat_surface_anchor",
            "candidate_count": 0,
            "synthesized_count": 0,
        }
    message_column_min = min((_bbox_left(item) for item in anchors if _bbox(item.get("bbox"))), default=region_bbox.get("x", 0)) - 48
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
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        box = {"x": region_bbox["x"] + x, "y": region_bbox["y"] + y, "w": w, "h": h}
        if box["x"] < min_x:
            continue
        area = w * h
        if w < 56 or h < 56 or area < 3600:
            continue
        if w > region_bbox["w"] * 0.55 or h > region_bbox["h"] * 0.45:
            continue
        boxes.append(_clip_bbox(region_bbox, box))
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
        entries.append({"items": cluster, "visual_bbox": visual_bbox or {}})
    for index, visual in enumerate(visual_boxes):
        if index in matched_visual_indexes:
            continue
        entries.append({"items": [], "visual_bbox": visual})
    entries.sort(key=lambda entry: (_bbox_left({"bbox": entry.get("visual_bbox") or _bbox_union([item.get("bbox") for item in entry.get("items", [])]) or {}}), _bbox_top({"bbox": entry.get("visual_bbox") or {}})))
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
    for start_x, end_x in segments:
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
        if len(below) < 2:
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
    if any(char.isdigit() for char in label):
        return False
    alnum_or_cjk = sum(1 for char in label if char.isalnum() or "\u4e00" <= char <= "\u9fff")
    return alnum_or_cjk >= 2


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
    return [
        _with_visual_media_card_bbox(
            _extend_media_card_bbox(card, parent_bbox=parent_bbox, all_cards=visual_cards),
            visual_bbox=card,
        )
        for card in visual_cards
    ]


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


def _item_should_be_card_child(item: dict[str, Any], card_bbox: dict[str, int]) -> bool:
    return _media_card_child_match_score(item, card_bbox) is not None


def _best_media_card_child_index(item: dict[str, Any], card_boxes: list[dict[str, int]]) -> int | None:
    scored: list[tuple[float, int]] = []
    for index, card_bbox in enumerate(card_boxes):
        score = _media_card_child_match_score(item, card_bbox)
        if score is not None:
            scored.append((score, index))
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
    if "section_title" in role:
        return None
    if _is_media_card_structural_container(role=role, item_type=item_type):
        return None
    visual_bbox = _media_card_visual_bbox(card_bbox)
    if "text" in role and bbox["h"] > max(96, int(visual_bbox["h"] * 0.45)):
        return None
    max_caption_gap = max(64, int(visual_bbox["h"] * 0.16))
    if bbox["y"] > visual_bbox["y"] + visual_bbox["h"] + max_caption_gap:
        return None
    center_x = bbox["x"] + bbox["w"] / 2
    center_y = bbox["y"] + bbox["h"] / 2
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
            row_y = min(_media_card_visual_bbox(item)["y"] for item in row)
            if abs(visual["y"] - row_y) <= 72:
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
    child_boxes = [_bbox(item.get("bbox")) for item in child_items]
    child_boxes = [box for box in child_boxes if box]
    if not child_boxes:
        return _clip_bbox(parent_bbox, base_bbox)
    union = _bbox_union([base_bbox, *child_boxes])
    return _clip_bbox(parent_bbox, union or base_bbox)


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
    child = {
        "child_id": str(item.get("item_id") or item.get("number") or ""),
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
            **direct_bar_report,
        }
    detection_bbox = _direct_region_control_detection_bbox(region_bbox)
    candidates = _visual_small_control_boxes(image_path=image_path, parent_bbox=detection_bbox)
    if len(candidates) >= max(6, len(numbered_items) * 2):
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
            "model_item_count": len(numbered_items),
            "refined_count": len(synthesized),
            "avg_model_visual_iou": 0.0,
            "low_overlap_count": len(synthesized),
            "orientation": "horizontal" if _is_horizontal_region(region_bbox) else "vertical",
            **direct_bar_report,
            "pairs": [
                {
                    "number": item.get("number"),
                    "label": item.get("label"),
                    "to": item.get("bbox"),
                }
                for item in synthesized
            ],
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
            "model_item_count": len(numbered_items),
            **direct_bar_report,
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
            "model_item_count": len(numbered_items),
            **direct_bar_report,
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
            "model_item_count": len(numbered_items),
            "avg_model_visual_iou": avg_overlap,
            "low_overlap_count": low_overlap_count,
            **direct_bar_report,
        }
    horizontal = region_bbox["w"] >= region_bbox["h"] * 2.5
    sorted_candidates = sorted(candidates, key=lambda box: (box["x"], box["y"]) if horizontal else (box["y"], box["x"]))
    sorted_items = sorted(
        [deepcopy(item) for item in numbered_items],
        key=lambda item: ((_bbox_left(item), _bbox_top(item)) if horizontal else (_bbox_top(item), _bbox_left(item))),
    )
    refined_by_number: dict[str, dict[str, Any]] = {}
    pairs: list[dict[str, Any]] = []
    for item, candidate in zip(sorted_items, sorted_candidates):
        old_bbox = _bbox(item.get("bbox"))
        if not old_bbox:
            continue
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
        "model_item_count": len(numbered_items),
        "refined_count": len(pairs),
        "avg_model_visual_iou": avg_overlap,
        "low_overlap_count": low_overlap_count,
        "orientation": "horizontal" if horizontal else "vertical",
        **direct_bar_report,
        "pairs": pairs,
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
    ordered = sorted([deepcopy(item) for item in numbered_items], key=lambda item: (_bbox_left(item), _bbox_top(item)))
    boxes = [_bbox(item.get("bbox")) for item in ordered]
    boxes = [box for box in boxes if box]
    if not boxes:
        return numbered_items, {
            "applied": False,
            "reason": "no_topbar_item_bbox",
            "input_count": len(numbered_items),
            "output_count": len(numbered_items),
        }
    centers = [box["x"] + box["w"] / 2 for box in boxes]
    expanded_count = 0
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(ordered):
        bbox = _bbox(item.get("bbox"))
        if not bbox:
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
    normalized = _renumber_stage2_items(normalized, horizontal=True)
    return normalized, {
        "applied": expanded_count > 0,
        "reason": "topbar_control_hit_area_normalized" if expanded_count > 0 else "topbar_controls_already_hit_area_sized",
        "input_count": len(numbered_items),
        "output_count": len(normalized),
        "expanded_item_count": expanded_count,
        "minimum_width_px": 48,
        "minimum_height_px": 36,
        "bbox_policy": "topbar_controls_must_not_remain_icon_or_ocr_fragments",
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


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
        full_row_bbox, expanded = _sidebar_hit_area_bbox(row_bbox, region_bbox=region_bbox, force_full_row=len(group) > 1)
        base = deepcopy(group[0])
        previous_bbox = _bbox(base.get("bbox")) or row_bbox
        if len(group) > 1:
            merged_count += len(group) - 1
            base["item_id"] = f"sidebar_item_{str(base.get('number') or index).replace('.', '_')}"
            base["label"] = _merged_sidebar_label(group)
            base["children"] = [_child_from_numbered_item(item) for item in group if _child_from_numbered_item(item)]
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
    clipped = _clip_bbox(region_bbox, target)
    expanded = clipped != row_bbox
    return clipped, expanded


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
        if any(token in value for token in ("text", "readable", "card", "member", "notice", "recommendation")):
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
        if str(item.get("role") or "") == "sidebar_review_region":
            pending.append(item)
            continue
        flush_pending()
        result.append(item)
    flush_pending()
    return result, max(0, len(items) - len(result))


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


def _zone_label(zone_id: str) -> str:
    labels = {
        "left_nav": "Left navigation",
        "left_sidebar": "Left sidebar",
        "browser_chrome": "Browser chrome",
        "page_header": "Top/header area",
        "top_bar": "Top/header area",
        "main_content": "Main content",
        "right_sidebar": "Right sidebar/detail area",
        "bottom_bar": "Bottom bar",
    }
    return labels.get(str(zone_id), str(zone_id).replace("_", " ").title())


def _int(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0
