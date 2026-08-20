from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.learn.recognition.bbox_alignment import evaluate_bbox_alignment

INTERACTABLE_SUPPORT_KEYS = {"uia", "omniparser", "calibrated_targets", "execute_candidate_result"}


def build_pathgraph_readiness_diagnosis(
    *,
    status_report_path: str | Path,
    parser_batch_report_path: str | Path,
    manifest_path: str | Path,
    out_dir: str | Path,
    support_search_roots: list[str | Path] | None = None,
    json_stdout: bool = False,
) -> dict[str, Any]:
    status_report_path = Path(status_report_path)
    parser_batch_report_path = Path(parser_batch_report_path)
    manifest_path = Path(manifest_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    status_report = _read_json(status_report_path)
    parser_batch = _read_json(parser_batch_report_path)
    manifest = _read_json(manifest_path)
    support_index = _build_support_index(support_search_roots or [])

    readiness = status_report.get("pathgraph_connection_readiness")
    readiness = readiness if isinstance(readiness, dict) else {}
    case_results = _case_index(parser_batch.get("case_results"))
    manifest_cases = _case_index(manifest.get("cases"))
    ready_ids = [str(case_id) for case_id in readiness.get("ready_cases", []) if str(case_id).strip()]
    blocked_ids = [str(case_id) for case_id in readiness.get("blocked_cases", []) if str(case_id).strip()]

    ready_cases = [
        _diagnose_case(
            case_id=case_id,
            case_result=case_results.get(case_id, {}),
            manifest_case=manifest_cases.get(case_id, {}),
            blocked=False,
            support_index=support_index,
        )
        for case_id in ready_ids
    ]
    blocked_cases = [
        _diagnose_case(
            case_id=case_id,
            case_result=case_results.get(case_id, {}),
            manifest_case=manifest_cases.get(case_id, {}),
            blocked=True,
            support_index=support_index,
        )
        for case_id in blocked_ids
    ]
    report = {
        "contract_version": "learn_pathgraph_readiness_blocker_diagnosis_v1",
        "input_reports": {
            "status_report_path": str(status_report_path),
            "parser_batch_report_path": str(parser_batch_report_path),
            "manifest_path": str(manifest_path),
            "support_search_roots": [str(path) for path in support_search_roots or []],
        },
        "summary": {
            "readiness_status": str(readiness.get("status") or "not_covered"),
            "ready_case_count": len(ready_cases),
            "blocked_case_count": len(blocked_cases),
            "ready_for_pathgraph_candidate_review": bool(ready_cases) and not bool(blocked_cases),
        },
        "support_discovery": _support_discovery_summary(support_index),
        "support_repair_targets": _support_repair_targets(blocked_cases),
        "ready_cases": ready_cases,
        "blocked_cases": blocked_cases,
        "interpretation": (
            "diagnoses why parser actual-call cases can or cannot enter PathGraph candidate review; "
            "this is not Execute authorization, click success, or a 90% recognition claim"
        ),
        "safety": {
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "real_clicks_performed": 0,
            "final_submit_forbidden": True,
        },
    }
    report_path = out_dir / "learn_pathgraph_readiness_blocker_diagnosis_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report["report_path"] = str(report_path)
    if json_stdout:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def _diagnose_case(
    *,
    case_id: str,
    case_result: dict[str, Any],
    manifest_case: dict[str, Any],
    blocked: bool,
    support_index: dict[str, Any],
) -> dict[str, Any]:
    usefulness = case_result.get("parser_actual_call_usefulness")
    usefulness = usefulness if isinstance(usefulness, dict) else {}
    validity = case_result.get("supplemental_source_validity")
    validity = validity if isinstance(validity, dict) else {}
    supplemental_status = str(validity.get("status") or "not_reported")
    root_cause = _root_cause(usefulness=usefulness, supplemental_status=supplemental_status, blocked=blocked)
    screenshot_path = str(manifest_case.get("screenshot_path") or case_result.get("screenshot_path") or "")
    screenshot_sha256 = _case_screenshot_sha256(screenshot_path=screenshot_path, case_result=case_result)
    support_discovery = _support_discovery_for_screenshot(screenshot_path, support_index)
    bbox_alignment_audit = _bbox_alignment_audit(
        screenshot_sha256=screenshot_sha256,
        case_result=case_result,
        support_index=support_index,
    )
    root_cause = _refine_root_cause_with_bbox_alignment(root_cause, bbox_alignment_audit)
    result = {
        "case_id": case_id,
        "surface": str(manifest_case.get("surface") or case_result.get("surface") or ""),
        "goal": str(manifest_case.get("goal") or ""),
        "screenshot_path": screenshot_path,
        "screenshot_sha256": screenshot_sha256,
        "actual_parser_smoke_report_path": str(case_result.get("report_path") or ""),
        "supplemental_sources_path": str(case_result.get("supplemental_sources_path") or manifest_case.get("supplemental_sources_path") or ""),
        "supplemental_source_validity_status": supplemental_status,
        "same_screenshot_support_discovery": support_discovery,
        "bbox_alignment_audit": bbox_alignment_audit,
        "parser_inventory_generated": bool(usefulness.get("parser_inventory_generated")),
        "parser_useful_for_review": bool(usefulness.get("parser_useful_for_review")),
        "parser_useful_for_grounding": bool(usefulness.get("parser_useful_for_grounding")),
        "semantic_only_regions": _int(usefulness.get("semantic_only_regions")),
        "grounding_eligible_regions": _int(usefulness.get("grounding_eligible_regions")),
        "accepted_for_grounding": _int(usefulness.get("accepted_for_grounding")),
        "blocked_from_grounding_reason": str(usefulness.get("blocked_from_grounding_reason") or ""),
        "root_cause": root_cause,
    }
    if blocked:
        result.update(
            {
                "failure_category": "no_grounding_candidate",
                "block_reason": _block_reason(root_cause),
                "not_prompt_tuning_issue": root_cause != "parser_bbox_alignment_failed",
                "not_pathgraph_wiring_issue": True,
                "recommended_next_evidence": [
                    "capture_same_screenshot_uia",
                    "capture_same_screenshot_omniparser",
                    "add_same_screenshot_calibrated_target",
                    "record_no_dispatch_execute_candidate",
                ],
                "pathgraph_action": "do_not_wire_to_pathgraph_candidate",
                "proposed_fix": _proposed_fix(root_cause),
                "safety_impact": (
                    "keeping this case blocked preserves no-click/no-Execute safety because semantic-only regions cannot become actions"
                ),
            }
        )
    else:
        result.update(
            {
                "pathgraph_action": "candidate_review_allowed",
                "proposed_fix": "review generated candidate evidence before any promotion; keep Execute authorization disabled",
                "safety_impact": "candidate review remains display-only and does not authorize clicks",
            }
        )
    return result


def _support_repair_targets(blocked_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for case in blocked_cases:
        if not isinstance(case, dict):
            continue
        discovery = case.get("same_screenshot_support_discovery")
        discovery = discovery if isinstance(discovery, dict) else {}
        targets.append(
            {
                "case_id": str(case.get("case_id") or ""),
                "surface": str(case.get("surface") or ""),
                "goal": str(case.get("goal") or ""),
                "screenshot_path": str(case.get("screenshot_path") or ""),
                "screenshot_sha256": str(case.get("screenshot_sha256") or ""),
                "case_locked_by_sha256": bool(case.get("screenshot_sha256")),
                "current_status": str(case.get("block_reason") or "blocked"),
                "root_cause": str(case.get("root_cause") or ""),
                "same_screenshot_support_status": str(discovery.get("status") or "not_searched"),
                "interactable_support_count": _int(discovery.get("interactable_support_count")),
                "bbox_alignment_status": str((case.get("bbox_alignment_audit") or {}).get("status") or "not_evaluated"),
                "required_next_evidence": list(case.get("recommended_next_evidence") or []),
                "acceptance_criteria": {
                    "support_artifact_screenshot_sha256_must_match": True,
                    "near_miss_support_counts_as_interactable_support": False,
                    "bbox_alignment_required_before_grounding_eligible": True,
                    "semantic_or_ocr_leaked_to_grounding_must_remain": 0,
                    "pathgraph_promotion_allowed": False,
                    "pathgraph_candidate_created": False,
                    "execute_binding_enabled": False,
                    "artifact_is_authorization": False,
                },
                "next_checkpoint": "same_screenshot_support_repair_v1",
            }
        )
    return targets


def _bbox_alignment_audit(
    *,
    screenshot_sha256: str,
    case_result: dict[str, Any],
    support_index: dict[str, Any],
) -> dict[str, Any]:
    matches = (support_index.get("by_checksum") or {}).get(screenshot_sha256, []) if screenshot_sha256 else []
    support_items = [
        item
        for source in matches
        for item in source.get("support_items", [])
        if isinstance(item, dict) and item.get("support_type") in INTERACTABLE_SUPPORT_KEYS
    ]
    if not support_items:
        return {
            "contract_version": "learn_support_bbox_alignment_audit_v1",
            "status": "not_evaluated_no_same_screenshot_interactable_support",
            "attempted": 0,
            "passed": 0,
            "support_item_count": 0,
            "parser_candidate_count": 0,
            "best_matches": [],
            "interpretation": "bbox alignment is only evaluated after exact same-screenshot interactable support is present",
        }
    parser_output = _case_parser_output_payload(case_result)
    parser_items = _case_parser_inventory(case_result, parser_output=parser_output)
    parser_candidates = [
        item
        for item in parser_items
        if isinstance(item, dict) and isinstance(item.get("bbox"), dict)
    ]
    if not parser_candidates:
        return {
            "contract_version": "learn_support_bbox_alignment_audit_v1",
            "status": "not_evaluated_no_parser_inventory",
            "attempted": 0,
            "passed": 0,
            "support_item_count": len(support_items),
            "parser_candidate_count": 0,
            "best_matches": [],
            "interpretation": "support exists, but parser inventory was unavailable for bbox alignment replay",
        }
    coordinate_evidence = _coordinate_diagnosis_evidence(parser_output)
    best_matches = [
        _best_alignment_for_support(
            support_item,
            parser_candidates,
            coordinate_evidence=coordinate_evidence,
        )
        for support_item in support_items
    ]
    passed = sum(1 for item in best_matches if item.get("bbox_alignment", {}).get("passed") is True)
    status = "bbox_alignment_passed" if passed > 0 else "support_found_but_bbox_alignment_failed"
    coordinate_categories = _coordinate_failure_categories(best_matches)
    return {
        "contract_version": "learn_support_bbox_alignment_audit_v1",
        "status": status,
        "attempted": len(best_matches),
        "passed": passed,
        "support_item_count": len(support_items),
        "parser_candidate_count": len(parser_candidates),
        "best_matches": best_matches,
        "coordinate_failure_categories": coordinate_categories,
        "pathgraph_promotion_allowed": False,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
        "interpretation": (
            "same-screenshot support must also align with parser candidate bbox before it can upgrade a review-only "
            "semantic region toward grounding eligibility; this still does not authorize Execute or PathGraph promotion"
        ),
    }


def _best_alignment_for_support(
    support_item: dict[str, Any],
    parser_items: list[dict[str, Any]],
    *,
    coordinate_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    best: dict[str, Any] | None = None
    best_score = -1.0
    support_bbox = support_item.get("bbox") if isinstance(support_item.get("bbox"), dict) else {}
    for parser_item in parser_items:
        parser_bbox = parser_item.get("bbox") if isinstance(parser_item.get("bbox"), dict) else {}
        alignment = evaluate_bbox_alignment(parser_bbox, support_bbox)
        overlap_score = float(alignment.get("iou") or 0) + float(alignment.get("vision_coverage") or 0) + float(alignment.get("support_coverage") or 0)
        label_score = _label_similarity(str(support_item.get("label") or ""), str(parser_item.get("label") or ""))
        score = overlap_score * 100.0 + label_score
        if score > best_score:
            best_score = score
            best = {
                "support": {
                    "support_type": str(support_item.get("support_type") or ""),
                    "label": str(support_item.get("label") or ""),
                    "bbox": support_bbox,
                    "path": str(support_item.get("path") or ""),
                },
                "parser_candidate": {
                    "item_id": str(parser_item.get("item_id") or ""),
                    "label": str(parser_item.get("label") or ""),
                    "source_evidence": list(parser_item.get("source_evidence") or []),
                    "bbox": parser_bbox,
                    "review_only": bool(parser_item.get("review_only")),
                    "grounding_eligible": bool(parser_item.get("grounding_eligible")),
                },
                "bbox_alignment": alignment,
            }
            best["coordinate_diagnosis"] = _coordinate_diagnosis_for_match(
                support_item=support_item,
                parser_item=parser_item,
                coordinate_evidence=coordinate_evidence or {},
                remapped_alignment=alignment,
            )
    return best or {
        "support": {
            "support_type": str(support_item.get("support_type") or ""),
            "label": str(support_item.get("label") or ""),
            "bbox": support_bbox,
            "path": str(support_item.get("path") or ""),
        },
        "parser_candidate": {},
        "bbox_alignment": evaluate_bbox_alignment({}, support_bbox),
        "coordinate_diagnosis": {
            "status": "not_evaluated_no_parser_candidate",
            "failure_category": "parser_candidate_missing",
        },
    }


def _label_similarity(left: str, right: str) -> float:
    left_tokens = _label_tokens(left)
    right_tokens = _label_tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = left_tokens.intersection(right_tokens)
    union = left_tokens.union(right_tokens)
    return float(len(overlap)) / float(max(1, len(union)))


def _label_tokens(value: str) -> set[str]:
    normalized = "".join(char.lower() if char.isalnum() else " " for char in value)
    return {token for token in normalized.split() if token}


def _case_parser_inventory(case_result: dict[str, Any], *, parser_output: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    inline = case_result.get("screen_inventory")
    if isinstance(inline, list):
        return [item for item in inline if isinstance(item, dict)]
    payload = parser_output if isinstance(parser_output, dict) else _case_parser_output_payload(case_result)
    inventory = payload.get("screen_inventory") if isinstance(payload, dict) else None
    if isinstance(inventory, list):
        return [item for item in inventory if isinstance(item, dict)]
    return []


def _case_parser_output_payload(case_result: dict[str, Any]) -> dict[str, Any]:
    output_path = Path(str(case_result.get("actual_parser_output_path") or ""))
    if output_path.exists():
        return _read_json(output_path)
    return {}


def _coordinate_diagnosis_evidence(parser_output: dict[str, Any]) -> dict[str, Any]:
    vision = _vision_source(parser_output)
    raw_response = vision.get("raw_response") if isinstance(vision.get("raw_response"), dict) else {}
    attempts = raw_response.get("attempts") if isinstance(raw_response.get("attempts"), list) else []
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        model_io = attempt.get("model_io") if isinstance(attempt.get("model_io"), dict) else {}
        input_info = model_io.get("input") if isinstance(model_io.get("input"), dict) else {}
        output = model_io.get("output") if isinstance(model_io.get("output"), dict) else {}
        raw_text = str(output.get("raw_text") or model_io.get("raw_text") or "").strip()
        parsed_raw = _parse_raw_model_json(raw_text)
        raw_regions = parsed_raw.get("regions") if isinstance(parsed_raw.get("regions"), list) else []
        raw_by_id: dict[str, dict[str, Any]] = {}
        for region in raw_regions:
            if not isinstance(region, dict):
                continue
            item_id = str(region.get("region_id") or region.get("id") or "").strip()
            bbox = _bbox_from_region(region)
            if item_id and bbox:
                raw_by_id[item_id] = bbox
        if raw_by_id:
            return {
                "status": "available",
                "attempt_tag": str((model_io.get("attempt") or {}).get("tag") or attempt.get("tag") or ""),
                "original_image_size": _size_dict(input_info.get("original_image_size")),
                "inference_image_size": _size_dict(input_info.get("inference_image_size")),
                "raw_model_bbox_by_item_id": raw_by_id,
            }
    return {"status": "missing_model_io_raw_coordinates"}


def _vision_source(parser_output: dict[str, Any]) -> dict[str, Any]:
    observe_bundle = parser_output.get("observe_bundle") if isinstance(parser_output.get("observe_bundle"), dict) else {}
    sources = observe_bundle.get("sources") if isinstance(observe_bundle.get("sources"), dict) else {}
    vision = sources.get("vision") if isinstance(sources.get("vision"), dict) else {}
    return vision


def _parse_raw_model_json(raw_text: str) -> dict[str, Any]:
    if not raw_text:
        return {}
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _coordinate_diagnosis_for_match(
    *,
    support_item: dict[str, Any],
    parser_item: dict[str, Any],
    coordinate_evidence: dict[str, Any],
    remapped_alignment: dict[str, Any],
) -> dict[str, Any]:
    if coordinate_evidence.get("status") != "available":
        return {
            "status": "not_evaluated",
            "failure_category": "coordinate_evidence_missing",
            "reason": str(coordinate_evidence.get("status") or "missing_coordinate_evidence"),
        }
    item_id = str(parser_item.get("item_id") or "").strip()
    raw_bbox = (coordinate_evidence.get("raw_model_bbox_by_item_id") or {}).get(item_id)
    if not isinstance(raw_bbox, dict):
        return {
            "status": "not_evaluated",
            "failure_category": "raw_model_bbox_missing_for_candidate",
            "parser_item_id": item_id,
        }
    original_size = coordinate_evidence.get("original_image_size") if isinstance(coordinate_evidence.get("original_image_size"), dict) else {}
    inference_size = coordinate_evidence.get("inference_image_size") if isinstance(coordinate_evidence.get("inference_image_size"), dict) else {}
    projected_support_bbox = _project_bbox_between_sizes(
        support_item.get("bbox") if isinstance(support_item.get("bbox"), dict) else {},
        from_size=original_size,
        to_size=inference_size,
    )
    raw_alignment = evaluate_bbox_alignment(raw_bbox, projected_support_bbox)
    recovered_bbox = _recover_normalized_1000_bbox(raw_bbox, inference_size)
    recovered_alignment = evaluate_bbox_alignment(recovered_bbox, projected_support_bbox) if recovered_bbox else {}
    remapped_passed = bool(remapped_alignment.get("passed"))
    raw_passed = bool(raw_alignment.get("passed"))
    if remapped_passed:
        failure_category = "no_coordinate_failure"
        status = "passed"
    elif raw_passed:
        failure_category = "coordinate_remap_or_scale_restore_failure"
        status = "failed"
    elif recovered_alignment.get("passed") is True:
        failure_category = "implicit_normalized_1000_recovery_needed"
        status = "failed"
    else:
        failure_category = "raw_model_bbox_misaligned_before_remap"
        status = "failed"
    return {
        "status": status,
        "failure_category": failure_category,
        "parser_item_id": item_id,
        "attempt_tag": str(coordinate_evidence.get("attempt_tag") or ""),
        "original_image_size": original_size,
        "inference_image_size": inference_size,
        "raw_model_bbox_in_inference_space": raw_bbox,
        "support_bbox_in_original_space": support_item.get("bbox") if isinstance(support_item.get("bbox"), dict) else {},
        "support_bbox_projected_to_inference_space": projected_support_bbox,
        "raw_model_vs_projected_support_alignment": raw_alignment,
        "coordinate_recovery_candidate": {
            "method": "normalized_1000_to_inference_image",
            "recovered_bbox_in_inference_space": recovered_bbox,
            "recovered_vs_projected_support_alignment": recovered_alignment,
            "alignment_improved": bool(recovered_alignment.get("passed")) and not raw_passed,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        },
        "remapped_parser_vs_support_alignment": remapped_alignment,
        "interpretation": (
            "raw model bbox is compared against support bbox projected into inference-image coordinates; "
            "if normalized_1000 recovery would align, the blocker is coordinate-space recovery rather than prompt tuning"
        ),
    }


def _coordinate_failure_categories(best_matches: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in best_matches:
        diagnosis = item.get("coordinate_diagnosis") if isinstance(item.get("coordinate_diagnosis"), dict) else {}
        category = str(diagnosis.get("failure_category") or "not_evaluated")
        counts[category] = counts.get(category, 0) + 1
    return counts


def _project_bbox_between_sizes(bbox: dict[str, Any], *, from_size: dict[str, Any], to_size: dict[str, Any]) -> dict[str, int]:
    from_width = _int(from_size.get("width"))
    from_height = _int(from_size.get("height"))
    to_width = _int(to_size.get("width"))
    to_height = _int(to_size.get("height"))
    if from_width <= 0 or from_height <= 0 or to_width <= 0 or to_height <= 0:
        return {}
    scale_x = float(to_width) / float(from_width)
    scale_y = float(to_height) / float(from_height)
    return {
        "x": round(_int(bbox.get("x")) * scale_x),
        "y": round(_int(bbox.get("y")) * scale_y),
        "w": max(1, round(_int(bbox.get("w")) * scale_x)),
        "h": max(1, round(_int(bbox.get("h")) * scale_y)),
    }


def _recover_normalized_1000_bbox(bbox: dict[str, Any], inference_size: dict[str, Any]) -> dict[str, int]:
    width = _int(inference_size.get("width")) if isinstance(inference_size, dict) else 0
    height = _int(inference_size.get("height")) if isinstance(inference_size, dict) else 0
    if width <= 0 or height <= 0:
        return {}
    try:
        x = float(bbox.get("x"))
        y = float(bbox.get("y"))
        w = float(bbox.get("w"))
        h = float(bbox.get("h"))
    except (TypeError, ValueError):
        return {}
    if not all(0.0 <= value <= 1000.0 for value in (x, y, w, h)):
        return {}
    return {
        "x": max(0, min(width, round(x * float(width) / 1000.0))),
        "y": max(0, min(height, round(y * float(height) / 1000.0))),
        "w": max(1, min(width, round(w * float(width) / 1000.0))),
        "h": max(1, min(height, round(h * float(height) / 1000.0))),
    }


def _bbox_from_region(region: dict[str, Any]) -> dict[str, int]:
    bbox = region.get("bbox") if isinstance(region.get("bbox"), dict) else {}
    if bbox:
        return {
            "x": _int(bbox.get("x")),
            "y": _int(bbox.get("y")),
            "w": _int(bbox.get("w", bbox.get("width"))),
            "h": _int(bbox.get("h", bbox.get("height"))),
        }
    diagonal = region.get("diagonal") if isinstance(region.get("diagonal"), dict) else {}
    if diagonal:
        x1 = _int(diagonal.get("x1"))
        y1 = _int(diagonal.get("y1"))
        x2 = _int(diagonal.get("x2"))
        y2 = _int(diagonal.get("y2"))
        return {"x": min(x1, x2), "y": min(y1, y2), "w": abs(x2 - x1), "h": abs(y2 - y1)}
    return {}


def _size_dict(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {"width": _int(value.get("width")), "height": _int(value.get("height"))}


def _root_cause(*, usefulness: dict[str, Any], supplemental_status: str, blocked: bool) -> str:
    if not blocked:
        return "grounding_candidates_available_for_review"
    if not usefulness.get("parser_inventory_generated"):
        return "parser_inventory_missing"
    if supplemental_status == "stale_fixture":
        return "stale_supplemental_sources"
    if supplemental_status in {"not_provided", "not_reported", ""}:
        return "no_same_screenshot_interactable_support"
    if _int(usefulness.get("grounding_eligible_regions")) == 0:
        return "semantic_only_without_grounding_eligible_candidates"
    return "grounding_candidate_missing"


def _refine_root_cause_with_bbox_alignment(root_cause: str, bbox_alignment_audit: dict[str, Any]) -> str:
    status = str(bbox_alignment_audit.get("status") or "")
    if status == "support_found_but_bbox_alignment_failed":
        coordinate_categories = bbox_alignment_audit.get("coordinate_failure_categories")
        if isinstance(coordinate_categories, dict) and coordinate_categories.get("implicit_normalized_1000_recovery_needed"):
            return "coordinate_space_recovery_needed"
        return "parser_bbox_alignment_failed"
    return root_cause


def _block_reason(root_cause: str) -> str:
    if root_cause == "coordinate_space_recovery_needed":
        return "same_screenshot_support_found_but_coordinate_recovery_not_applied"
    if root_cause == "parser_bbox_alignment_failed":
        return "same_screenshot_support_found_but_parser_bbox_alignment_failed"
    return "semantic_only_without_same_screenshot_interactable_support"


def _case_screenshot_sha256(*, screenshot_path: str, case_result: dict[str, Any]) -> str:
    reported = str(case_result.get("screenshot_sha256") or "").strip().lower()
    if len(reported) == 64:
        return reported
    path = Path(screenshot_path)
    if path.exists():
        return _sha256_file(path)
    return ""


def _proposed_fix(root_cause: str) -> str:
    if root_cause == "stale_supplemental_sources":
        return "replace supplemental support with evidence whose screenshot_sha256 matches this case screenshot"
    if root_cause == "parser_inventory_missing":
        return "rerun actual parser and inspect model/protocol output before PathGraph wiring"
    if root_cause == "coordinate_space_recovery_needed":
        return "rerun Learn Recognition actual parser with opt-in implicit normalized_1000 coordinate recovery, then recheck same-screenshot support alignment before PathGraph wiring"
    if root_cause == "parser_bbox_alignment_failed":
        return "fix actual parser bbox/coordinate output or use an alternative ROI/parser locator before PathGraph wiring"
    return "attach same-screenshot OCR/UIA/OmniParser/calibrated-target support or improve parser bbox alignment before PathGraph wiring"


def _case_index(value: Any) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        case_id = str(item.get("case_id") or "").strip()
        if case_id:
            indexed[case_id] = item
    return indexed


def _build_support_index(roots: list[str | Path]) -> dict[str, Any]:
    normalized_roots = [Path(root) for root in roots if str(root).strip()]
    index: dict[str, Any] = {
        "searched": bool(normalized_roots),
        "searched_roots": [str(root) for root in normalized_roots],
        "search_complete": True,
        "json_files_scanned": 0,
        "support_candidate_file_count": 0,
        "by_checksum": {},
    }
    for root in normalized_roots:
        if not root.exists():
            continue
        for path in root.rglob("*.json"):
            index["json_files_scanned"] += 1
            payload = _read_json(path)
            if not payload:
                continue
            support_keys = _support_keys(payload)
            if INTERACTABLE_SUPPORT_KEYS.intersection(set(support_keys)):
                index["support_candidate_file_count"] += 1
            checksum = _payload_screenshot_checksum(payload)
            if not checksum:
                continue
            entry = {
                "path": str(path),
                "support_keys": support_keys,
                "support_items": _support_items(payload, path=path),
            }
            index["by_checksum"].setdefault(checksum, []).append(entry)
    return index


def _support_discovery_summary(support_index: dict[str, Any]) -> dict[str, Any]:
    by_checksum = support_index.get("by_checksum") if isinstance(support_index.get("by_checksum"), dict) else {}
    return {
        "searched_roots": support_index.get("searched_roots") or [],
        "searched_file_count": _int(support_index.get("json_files_scanned")),
        "json_files_scanned": _int(support_index.get("json_files_scanned")),
        "support_candidate_file_count": _int(support_index.get("support_candidate_file_count")),
        "indexed_checksum_count": len(by_checksum),
        "search_complete": bool(support_index.get("search_complete")),
        "same_screenshot_definition": "exact screenshot_sha256 match only; filename, URL, title, and timestamp are not accepted",
        "interactable_support_keys": sorted(INTERACTABLE_SUPPORT_KEYS),
        "interpretation": (
            "support discovery audits evidence availability only; support artifacts are not Execute authorization "
            "and do not prove model accuracy"
        ),
    }


def _support_discovery_for_screenshot(screenshot_path: str, support_index: dict[str, Any]) -> dict[str, Any]:
    if not support_index.get("searched"):
        return {
            "status": "not_searched",
            "searched_roots": [],
            "screenshot_sha256": "",
            "matching_source_count": 0,
            "interactable_support_count": 0,
            "interactable_support_paths": [],
        }
    screenshot = Path(screenshot_path)
    checksum = _sha256_file(screenshot) if screenshot.exists() else ""
    matches = (support_index.get("by_checksum") or {}).get(checksum, []) if checksum else []
    interactable = [
        item
        for item in matches
        if INTERACTABLE_SUPPORT_KEYS.intersection(set(item.get("support_keys") or []))
    ]
    if interactable:
        status = "matching_interactable_support_found"
    elif matches:
        status = "matching_json_without_interactable_support"
    else:
        status = "no_matching_support_json_found"
    return {
        "status": status,
        "searched_roots": support_index.get("searched_roots") or [],
        "search_complete": bool(support_index.get("search_complete")),
        "candidate_support_file_count": _int(support_index.get("support_candidate_file_count")),
        "screenshot_sha256": checksum,
        "matching_source_count": len(matches),
        "interactable_support_count": len(interactable),
        "matching_source_paths": [str(item.get("path") or "") for item in matches],
        "interactable_support_paths": [str(item.get("path") or "") for item in interactable],
        "near_miss_count": 0,
        "near_misses": [],
        "support_details": _support_details(interactable),
    }


def _support_details(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for item in items:
        keys = [key for key in item.get("support_keys") or [] if key in INTERACTABLE_SUPPORT_KEYS]
        for key in keys:
            details.append(
                {
                    "path": str(item.get("path") or ""),
                    "support_type": key,
                    "support_scope": _support_scope(key),
                    "artifact_is_authorization": False,
                    "same_screenshot_sha256": True,
                    "bbox_overlap": "not_evaluated_by_support_discovery",
                    "action_region_linkage": "not_evaluated_by_support_discovery",
                    "interactable_reason": _interactable_reason(key),
                }
            )
    return details


def _support_items(payload: dict[str, Any], *, path: Path) -> list[dict[str, Any]]:
    sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else None
    if sources is None and isinstance(payload.get("observe_bundle"), dict):
        observe_bundle = payload.get("observe_bundle") or {}
        sources = observe_bundle.get("sources") if isinstance(observe_bundle.get("sources"), dict) else None
    if not isinstance(sources, dict):
        return []
    image_size = _payload_image_size(payload)
    items: list[dict[str, Any]] = []
    items.extend(_uia_support_items(sources.get("uia"), path=path))
    items.extend(_calibrated_support_items(sources.get("calibrated_targets"), path=path))
    items.extend(_execute_candidate_support_items(sources.get("execute_candidate_result"), path=path))
    items.extend(_omniparser_support_items(sources.get("omniparser"), path=path, image_size=image_size))
    return items


def _uia_support_items(source: Any, *, path: Path) -> list[dict[str, Any]]:
    controls = source.get("controls") if isinstance(source, dict) else []
    return [
        {
            "support_type": "uia",
            "label": str(item.get("name") or item.get("label") or ""),
            "bbox": item.get("bbox"),
            "path": str(path),
        }
        for item in controls if isinstance(item, dict) and isinstance(item.get("bbox"), dict)
    ]


def _calibrated_support_items(source: Any, *, path: Path) -> list[dict[str, Any]]:
    targets = source.get("targets") if isinstance(source, dict) else []
    return [
        {
            "support_type": "calibrated_targets",
            "label": str(item.get("label") or ""),
            "bbox": item.get("bbox"),
            "path": str(path),
        }
        for item in targets if isinstance(item, dict) and isinstance(item.get("bbox"), dict)
    ]


def _execute_candidate_support_items(source: Any, *, path: Path) -> list[dict[str, Any]]:
    candidates = source.get("candidates") if isinstance(source, dict) else []
    return [
        {
            "support_type": "execute_candidate_result",
            "label": str(item.get("label") or item.get("text") or ""),
            "bbox": item.get("bbox"),
            "path": str(path),
        }
        for item in candidates if isinstance(item, dict) and isinstance(item.get("bbox"), dict)
    ]


def _omniparser_support_items(source: Any, *, path: Path, image_size: dict[str, int]) -> list[dict[str, Any]]:
    elements = source.get("parsed_content_list") if isinstance(source, dict) else []
    items: list[dict[str, Any]] = []
    for item in elements if isinstance(elements, list) else []:
        if not isinstance(item, dict):
            continue
        bbox = _normalize_omniparser_bbox(item.get("bbox"), image_size=image_size)
        if not bbox:
            continue
        items.append(
            {
                "support_type": "omniparser",
                "label": str(item.get("content") or item.get("text") or ""),
                "bbox": bbox,
                "path": str(path),
            }
        )
    return items


def _normalize_omniparser_bbox(value: Any, *, image_size: dict[str, int]) -> dict[str, float]:
    if isinstance(value, dict):
        if {"x", "y", "w", "h"}.issubset(set(value)):
            return {"x": float(value.get("x") or 0), "y": float(value.get("y") or 0), "w": float(value.get("w") or 0), "h": float(value.get("h") or 0)}
        if {"x1", "y1", "x2", "y2"}.issubset(set(value)):
            x1, y1, x2, y2 = (float(value.get(key) or 0) for key in ("x1", "y1", "x2", "y2"))
            return {"x": x1, "y": y1, "w": max(0.0, x2 - x1), "h": max(0.0, y2 - y1)}
    if isinstance(value, list) and len(value) == 4:
        coords = [float(part or 0) for part in value]
        if max(coords) <= 1.0 and image_size.get("width") and image_size.get("height"):
            coords = [coords[0] * image_size["width"], coords[1] * image_size["height"], coords[2] * image_size["width"], coords[3] * image_size["height"]]
        x1, y1, x2, y2 = coords
        return {"x": x1, "y": y1, "w": max(0.0, x2 - x1), "h": max(0.0, y2 - y1)}
    return {}


def _payload_image_size(payload: dict[str, Any]) -> dict[str, int]:
    candidates = [
        payload.get("image_size"),
        payload.get("screen_size"),
        (payload.get("observe_bundle") or {}).get("image_size") if isinstance(payload.get("observe_bundle"), dict) else None,
        (payload.get("observe_bundle") or {}).get("screen_size") if isinstance(payload.get("observe_bundle"), dict) else None,
    ]
    for candidate in candidates:
        if isinstance(candidate, dict):
            width = _int(candidate.get("width") or candidate.get("w"))
            height = _int(candidate.get("height") or candidate.get("h"))
            if width > 0 and height > 0:
                return {"width": width, "height": height}
    return {"width": 0, "height": 0}


def _support_scope(key: str) -> str:
    if key == "execute_candidate_result":
        return "no_dispatch_evidence_only"
    if key == "calibrated_targets":
        return "human_or_tool_calibrated_support_only"
    return "interactable_evidence_only"


def _interactable_reason(key: str) -> str:
    return {
        "uia": "uia_control_pattern_or_role",
        "omniparser": "omniparser_interactable_element",
        "calibrated_targets": "calibrated_actionable_target",
        "execute_candidate_result": "no_dispatch_execute_candidate",
    }.get(key, "interactable_support_key")


def _payload_screenshot_checksum(payload: dict[str, Any]) -> str:
    candidates = [
        payload.get("screenshot_sha256"),
        (payload.get("screenshot") or {}).get("sha256") if isinstance(payload.get("screenshot"), dict) else "",
        ((payload.get("observe_bundle") or {}).get("screenshot") or {}).get("sha256")
        if isinstance(payload.get("observe_bundle"), dict)
        and isinstance((payload.get("observe_bundle") or {}).get("screenshot"), dict)
        else "",
    ]
    for candidate in candidates:
        value = str(candidate or "").strip().lower()
        if len(value) == 64:
            return value
    return ""


def _support_keys(payload: dict[str, Any]) -> list[str]:
    sources = payload.get("sources") if isinstance(payload.get("sources"), dict) else None
    if sources is None and isinstance(payload.get("observe_bundle"), dict):
        observe_bundle = payload.get("observe_bundle") or {}
        sources = observe_bundle.get("sources") if isinstance(observe_bundle.get("sources"), dict) else None
    if not isinstance(sources, dict):
        return []
    return sorted(str(key) for key, value in sources.items() if isinstance(value, dict))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--status-report", required=True)
    parser.add_argument("--parser-batch-report", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--support-search-root", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    build_pathgraph_readiness_diagnosis(
        status_report_path=args.status_report,
        parser_batch_report_path=args.parser_batch_report,
        manifest_path=args.manifest,
        out_dir=args.out,
        support_search_roots=args.support_search_root,
        json_stdout=args.json,
    )


if __name__ == "__main__":
    main()
