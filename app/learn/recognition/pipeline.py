from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

from app.learn.recognition.classifier import classify_inventory_items
from app.learn.recognition.contracts import build_learning_template_draft_from_validated_items
from app.learn.recognition.eligibility import summarize_grounding_eligibility
from app.learn.recognition.grounding import build_grounding_request, normalize_grounding_result_to_screen
from app.learn.recognition.layout_cleanup import resolve_inventory_layout
from app.learn.recognition.layout_graph import build_inventory_layout_graph
from app.learn.recognition.locator_tasks import build_locator_task_cards
from app.learn.recognition.parsers import parse_existing_evidence_to_inventory
from app.learn.recognition.roi import bounded_roi_crop_size_for_bbox, build_roi_crop_metadata
from app.learn.recognition.two_stage import build_two_stage_screen_understanding, fusion_status_from_two_stage
from app.learn.recognition.validator import validate_grounding_candidate


GroundingAdapter = Callable[..., dict[str, Any]]


def build_learning_recognition_trial(
    *,
    observe_bundle: dict[str, Any],
    state_guess: str,
    summary: str,
    grounding_adapter: GroundingAdapter | None = None,
    crop_size: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把学习模式前半段的识别结果串成只读学习草稿。"""

    bundle = observe_bundle if isinstance(observe_bundle, dict) else {}
    raw_screen_inventory = parse_existing_evidence_to_inventory(bundle)
    layout_cleanup = resolve_inventory_layout(raw_screen_inventory)
    screen_inventory = layout_cleanup["cleaned_items"]
    classification = classify_inventory_items(screen_inventory)
    grounding_eligibility_gate = summarize_grounding_eligibility(_classified_items(classification))
    layout_graph = build_inventory_layout_graph(screen_inventory, screen_size=_source_image_size(bundle))
    locator_task_cards = build_locator_task_cards(screen_inventory)
    two_stage_understanding = build_two_stage_screen_understanding(
        bundle=bundle,
        screen_inventory=screen_inventory,
        layout_graph=layout_graph,
    )
    accepted_items = classification.get("accepted_for_grounding")
    accepted_items = accepted_items if isinstance(accepted_items, list) else []

    roi_crops: list[dict[str, Any]] = []
    grounding_validations: list[dict[str, Any]] = []
    valid_items: list[dict[str, Any]] = []
    status = "needs_grounding_adapter" if accepted_items and grounding_adapter is None else "needs_human_review"

    if grounding_adapter is not None:
        source_image_size = _source_image_size(bundle)
        for item in accepted_items:
            roi_crop = build_roi_crop_metadata(
                source_image_size=source_image_size,
                candidate_bbox=item.get("bbox") if isinstance(item, dict) else {},
                crop_size=_crop_size_for_item(item, crop_size),
            )
            roi_crop["grounding_request"] = build_grounding_request(item=item, roi_crop=roi_crop)
            roi_crops.append(roi_crop)
            grounding = _call_grounding_adapter(grounding_adapter, item=item, roi_crop=roi_crop)
            grounding = normalize_grounding_result_to_screen(grounding, roi_crop=roi_crop)
            evidence = _validation_evidence(item=item, grounding=grounding)
            validation = validate_grounding_candidate(item=item, grounding=grounding, evidence=evidence)
            validation["roi_crop"] = deepcopy(roi_crop)
            validation["grounding_debug"] = deepcopy(grounding.get("debug")) if isinstance(grounding, dict) else {}
            grounding_validations.append(validation)
            if validation["status"] == "valid_candidate":
                valid_item = deepcopy(item)
                valid_item["bbox"] = deepcopy(validation["screen_bbox"])
                valid_item["click_point"] = deepcopy(validation["screen_point"])
                valid_item["screen_point"] = deepcopy(validation["screen_point"])
                valid_items.append(valid_item)
        status = "draft_ready" if valid_items else "needs_human_review"

    page_details = _page_details(
        bundle=bundle,
        summary=summary,
        screen_inventory=screen_inventory,
        classification=classification,
        layout_cleanup=layout_cleanup,
        layout_graph=layout_graph,
        locator_task_cards=locator_task_cards,
        two_stage_understanding=two_stage_understanding,
        grounding_eligibility_gate=grounding_eligibility_gate,
        grounding_validations=grounding_validations,
    )
    learning_draft = build_learning_template_draft_from_validated_items(
        state_guess=state_guess,
        summary=summary,
        valid_items=valid_items,
        evidence_refs={
            "screen_inventory_count": len(screen_inventory),
            "raw_screen_inventory_count": len(raw_screen_inventory),
            "accepted_for_grounding_count": len(accepted_items),
            "grounding_validation_count": len(grounding_validations),
            "layout_cleanup_suppressed_count": layout_cleanup["suppressed_count"],
            "layout_cleanup_suppression_reason_counts": deepcopy(layout_cleanup.get("suppression_reason_counts", {})),
            "source_contract": str(bundle.get("contract_version") or ""),
        },
        page_details=page_details,
    )
    learning_draft["regions"] = _regions_with_review_only_display_items(learning_draft.get("regions"), page_details)
    safety = _display_only_safety()
    learning_draft.update(safety)
    return {
        "contract_version": "learn_recognition_pipeline_result_v1",
        "status": status,
        "raw_screen_inventory": raw_screen_inventory,
        "layout_cleanup": layout_cleanup,
        "layout_graph": layout_graph,
        "locator_task_cards": locator_task_cards,
        "two_stage_understanding": two_stage_understanding,
        "grounding_eligibility_gate": grounding_eligibility_gate,
        "screen_inventory": screen_inventory,
        "classification": classification,
        "roi_crops": roi_crops,
        "grounding_validations": grounding_validations,
        "learning_draft": learning_draft,
        "safety": safety,
    }


def _call_grounding_adapter(grounding_adapter: GroundingAdapter, *, item: dict[str, Any], roi_crop: dict[str, Any]) -> dict[str, Any]:
    result = grounding_adapter(item=item, roi_crop=roi_crop)
    return result if isinstance(result, dict) else {}


def _validation_evidence(*, item: dict[str, Any], grounding: dict[str, Any]) -> dict[str, Any]:
    evidence = grounding.get("evidence") if isinstance(grounding.get("evidence"), dict) else {}
    return {
        "coordinate_transform_replay": bool(evidence.get("coordinate_transform_replay")),
        "screenshot_freshness": bool(evidence.get("screenshot_freshness")),
        "ocr_anchor_overlap": evidence.get("ocr_anchor_overlap", True),
        "uia_or_dom_or_parser_overlap": evidence.get(
            "uia_or_dom_or_parser_overlap",
            _has_non_ocr_source(item),
        ),
    }


def _source_image_size(bundle: dict[str, Any]) -> dict[str, int]:
    for key in ("screen_size", "viewport_size", "image_size", "source_image_size"):
        value = bundle.get(key)
        if isinstance(value, dict):
            return {"width": _int_or_zero(value.get("width")), "height": _int_or_zero(value.get("height"))}
    return {"width": 0, "height": 0}


def _crop_size_for_item(item: dict[str, Any], requested: dict[str, Any] | None) -> dict[str, int]:
    if isinstance(requested, dict):
        return {"width": max(1, _int_or_zero(requested.get("width"))), "height": max(1, _int_or_zero(requested.get("height")))}
    bbox = item.get("bbox") if isinstance(item, dict) else {}
    bbox = bbox if isinstance(bbox, dict) else {}
    return bounded_roi_crop_size_for_bbox(bbox)


def _has_non_ocr_source(item: dict[str, Any]) -> bool:
    sources = item.get("source_evidence") if isinstance(item, dict) else []
    if not isinstance(sources, list):
        return False
    return any(str(source).casefold() in {"uia", "dom", "omniparser"} for source in sources)


def _display_only_safety() -> dict[str, Any]:
    return {
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "real_action_requires_gate": True,
        "final_submit_forbidden": True,
    }


def _classified_items(classification: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key in ("accepted_for_grounding", "rejected_non_actionable", "needs_human_review", "danger_zones"):
        bucket = classification.get(key) if isinstance(classification, dict) else []
        items.extend(deepcopy(item) for item in bucket if isinstance(item, dict))
    return items


def _regions_with_review_only_display_items(regions: Any, page_details: dict[str, Any]) -> list[dict[str, Any]]:
    draft_regions = [deepcopy(item) for item in regions if isinstance(item, dict)] if isinstance(regions, list) else []
    existing_ids = {str(item.get("region_id") or "").strip() for item in draft_regions if str(item.get("region_id") or "").strip()}
    review_items = page_details.get("review_only_regions") if isinstance(page_details, dict) else []
    for index, item in enumerate(review_items if isinstance(review_items, list) else []):
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("item_id") or "").strip()
        region_id = _review_only_region_id(item_id, index)
        if region_id in existing_ids:
            continue
        draft_regions.append(
            {
                "region_id": region_id,
                "label": str(item.get("label") or item_id or region_id),
                "role": str(item.get("role") or item.get("item_type") or "review_only"),
                "bbox": deepcopy(item.get("bbox") if isinstance(item.get("bbox"), dict) else {}),
                "source_item_id": item_id or None,
                "source_evidence": deepcopy(item.get("source_evidence") if isinstance(item.get("source_evidence"), list) else []),
                "grounding_status": "review_only",
                "candidate_only": True,
                "requires_human_review": True,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
                "real_action_requires_gate": True,
                "final_submit_forbidden": True,
            }
        )
        existing_ids.add(region_id)
    return draft_regions


def _review_only_region_id(item_id: str, index: int) -> str:
    base = "".join(ch if ch.isalnum() else "_" for ch in str(item_id or "").strip().lower()).strip("_")
    return f"review_region_{base or index + 1}"


def _page_details(
    *,
    bundle: dict[str, Any],
    summary: str,
    screen_inventory: list[dict[str, Any]],
    classification: dict[str, Any],
    layout_cleanup: dict[str, Any],
    layout_graph: dict[str, Any],
    locator_task_cards: dict[str, Any],
    two_stage_understanding: dict[str, Any],
    grounding_eligibility_gate: dict[str, Any],
    grounding_validations: list[dict[str, Any]],
) -> dict[str, Any]:
    panel_evidence = bundle.get("panel_observation_evidence") if isinstance(bundle.get("panel_observation_evidence"), dict) else {}
    model_roles = panel_evidence.get("model_roles") if isinstance(panel_evidence.get("model_roles"), dict) else {}
    return {
        "contract_version": "learning_draft_page_details_v1",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "screen": {
            "app_name": str(bundle.get("app_name") or ""),
            "state_hint": str(bundle.get("state_hint") or ""),
            "image_path": str(bundle.get("image_path") or bundle.get("source_image_path") or ""),
            "screen_size": _source_image_size(bundle),
            "summary": str(summary or ""),
        },
        "model_roles": deepcopy(model_roles),
        "layout_graph": deepcopy(layout_graph),
        "locator_task_cards": deepcopy(locator_task_cards),
        "two_stage_understanding": deepcopy(two_stage_understanding),
        "pipeline_audit": {
            "contract_version": "learning_draft_pipeline_audit_v1",
            "display_only": True,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "precise_understanding_fusion_status": fusion_status_from_two_stage(two_stage_understanding),
            "layout_cleanup": _layout_cleanup_page_summary(layout_cleanup),
            "grounding_eligibility_gate": _grounding_gate_page_summary(grounding_eligibility_gate),
            "roi_grounding": {
                "validation_count": len(grounding_validations),
                "valid_candidate_count": len(
                    [
                        item
                        for item in grounding_validations
                        if isinstance(item, dict) and item.get("status") == "valid_candidate"
                    ]
                ),
                "interpretation": "ROI grounding evidence is display/review only until a later Gate authorizes real action.",
            },
            "interpretation": (
                "Pipeline audit explains parser cleanup, eligibility gating, and ROI validation for human review; "
                "it is not click authorization or a recognition accuracy metric."
            ),
        },
        "inventory_summary": {
            **(deepcopy(classification.get("summary")) if isinstance(classification.get("summary"), dict) else {}),
            "screen_inventory_count": len(screen_inventory),
            "grounding_validation_count": len(grounding_validations),
        },
        "review_only_regions": _display_items(
            list(classification.get("rejected_non_actionable") or []) + list(classification.get("needs_human_review") or []),
            limit=32,
        ),
        "grounding_candidates": _display_items(classification.get("accepted_for_grounding") or [], limit=32),
        "danger_zones": _display_items(classification.get("danger_zones") or [], limit=16),
        "interpretation": "Read-only page understanding details; not a PathGraph, not click authorization, and not Execute binding.",
    }


def _layout_cleanup_page_summary(layout_cleanup: dict[str, Any]) -> dict[str, Any]:
    cleanup = layout_cleanup if isinstance(layout_cleanup, dict) else {}
    reason_counts = cleanup.get("suppression_reason_counts") if isinstance(cleanup.get("suppression_reason_counts"), dict) else {}
    return {
        "contract_version": str(cleanup.get("contract_version") or "learn_layout_cleanup_report_v1"),
        "input_count": _int_or_zero(cleanup.get("input_count")),
        "output_count": _int_or_zero(cleanup.get("output_count")),
        "suppressed_count": _int_or_zero(cleanup.get("suppressed_count")),
        "duplicates_merged": _int_or_zero(cleanup.get("duplicates_merged")),
        "suppression_reason_counts": {str(key): _int_or_zero(value) for key, value in reason_counts.items()},
        "interpretation": "BBox Cleanup summary for display/review; candidate suppression is not model accuracy.",
    }


def _grounding_gate_page_summary(grounding_eligibility_gate: dict[str, Any]) -> dict[str, Any]:
    gate = grounding_eligibility_gate if isinstance(grounding_eligibility_gate, dict) else {}
    counts = gate.get("grounding_eligibility") if isinstance(gate.get("grounding_eligibility"), dict) else {}
    leakage = (
        gate.get("non_actionable_leaked_to_grounding")
        if isinstance(gate.get("non_actionable_leaked_to_grounding"), dict)
        else {}
    )
    return {
        "contract_version": str(gate.get("contract_version") or "learn_grounding_eligibility_gate_report_v1"),
        "attempted": _int_or_zero(counts.get("attempted")),
        "eligible": _int_or_zero(counts.get("eligible")),
        "blocked": _int_or_zero(counts.get("blocked")),
        "non_actionable_leaked_to_grounding": _int_or_zero(leakage.get("leaked_count")),
        "not_accuracy": bool(gate.get("not_accuracy", True)),
        "interpretation": (
            "Grounding Eligibility Gate decides which candidates may enter ROI grounding for learning evidence; "
            "it does not authorize clicks."
        ),
    }


def _display_items(items: Any, *, limit: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        decision = item.get("classification_decision") if isinstance(item.get("classification_decision"), dict) else {}
        result.append(
            {
                "item_id": str(item.get("item_id") or ""),
                "label": str(item.get("label") or item.get("text") or ""),
                "item_type": str(item.get("item_type") or ""),
                "role": str(item.get("role") or ""),
                "bbox": deepcopy(item.get("bbox") if isinstance(item.get("bbox"), dict) else {}),
                "source_evidence": deepcopy(item.get("source_evidence") if isinstance(item.get("source_evidence"), list) else []),
                "evidence_level": str(item.get("evidence_level") or ""),
                "decision": {
                    "outcome": str(decision.get("outcome") or ""),
                    "reason": str(decision.get("reason") or item.get("grounding_block_reason") or ""),
                    "grounding_eligible": bool(item.get("grounding_eligible")),
                    "review_only": bool(item.get("review_only")),
                },
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        )
        if len(result) >= limit:
            break
    return result


def _int_or_zero(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0
