from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from app.learn.draft_review import load_learning_draft_review, save_reviewed_template_candidate
from app.learn.model_artifact_loader import _build_interface_map, _build_runtime_path_graph

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def build_pathgraph_candidate_from_review(
    source_path: str | Path,
    review_patch: dict[str, Any] | None,
    *,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    save_result = save_reviewed_template_candidate(source_path, review_patch, project_root=root)
    reviewed_path = _resolve_under_root(save_result["reviewed_template_candidate_path"], root)
    source_bytes = reviewed_path.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    reviewed = json.loads(source_bytes.decode("utf-8-sig"))
    if not isinstance(reviewed, dict) or reviewed.get("contract_version") != "reviewed_template_candidate_v1":
        raise ValueError("reviewed template candidate is invalid")

    draft = _nested_draft_from_reviewed(reviewed.get("draft") if isinstance(reviewed.get("draft"), dict) else {})
    source_ref = {
        "trial_path": _relative_path(reviewed_path, root),
        "reviewed_candidate_path": _relative_path(reviewed_path, root),
        "source_trial_path": reviewed.get("audit", {}).get("source_trial_path") if isinstance(reviewed.get("audit"), dict) else None,
        "sha256": source_hash,
        "attempt_index": None,
        "readonly": True,
        "posthoc_optimization_allowed": False,
        "candidate_mode": True,
    }
    trial = {
        "contract_version": "reviewed_template_candidate_v1",
        "app_name": _app_name_from_reviewed(reviewed, draft),
    }
    graph = _build_runtime_path_graph(trial, draft, source_ref)
    interface_map = _build_interface_map(trial, draft, source_ref, graph)
    _mark_candidate_graph(graph)
    _mark_candidate_interface_map(interface_map)
    validation_report = _validate_candidate(reviewed=reviewed, graph=graph, interface_map=interface_map)
    manual_bbox_edit_summary = validation_report.get("manual_bbox_edit_summary", _manual_bbox_edit_summary_from_reviewed(reviewed))
    source_freshness_summary = validation_report.get("source_freshness_summary", _source_freshness_summary_from_reviewed(reviewed))
    precise_understanding_summary = validation_report.get(
        "precise_understanding_summary",
        _precise_understanding_summary_from_reviewed(reviewed),
    )
    precise_understanding_readiness_summary = validation_report.get(
        "precise_understanding_readiness_summary",
        _precise_understanding_readiness_summary_from_reviewed(reviewed),
    )
    evidence_integrity = validation_report.get(
        "evidence_integrity",
        _evidence_integrity_from_reviewed(reviewed),
    )
    model_start_runbook = validation_report.get(
        "model_start_runbook",
        _model_start_runbook_from_reviewed(reviewed),
    )
    pending_detail_observe_requests = validation_report.get(
        "pending_detail_observe_requests",
        _pending_detail_observe_requests(graph),
    )
    correction_memory = (
        save_result.get("correction_memory") if isinstance(save_result.get("correction_memory"), dict) else None
    )

    out_dir = reviewed_path.parent / "pathgraph_candidate"
    out_dir.mkdir(parents=True, exist_ok=True)
    graph_path = out_dir / "runtime_path_graph_candidate.json"
    interface_path = out_dir / "interface_map_candidate.json"
    validation_path = out_dir / "promotion_validation_report.json"
    wrapper_path = out_dir / "pathgraph_candidate.json"

    graph_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    interface_path.write_text(json.dumps(interface_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    validation_report["paths"] = {
        "runtime_path_graph_candidate_path": _relative_path(graph_path, root),
        "interface_map_candidate_path": _relative_path(interface_path, root),
    }
    validation_path.write_text(json.dumps(validation_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    wrapper = {
        "contract_version": "pathgraph_candidate_v1",
        "artifact_type": "pathgraph_candidate",
        "candidate_status": validation_report["validation_status"],
        "source_after_promotion": reviewed.get("source_after_review") or "mixed",
        "counts_as_pure_model_generated": False,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
        "real_action_requires_gate": True,
        "reviewed_template_candidate_path": _relative_path(reviewed_path, root),
        "runtime_path_graph_candidate_path": _relative_path(graph_path, root),
        "interface_map_candidate_path": _relative_path(interface_path, root),
        "validation_report_path": _relative_path(validation_path, root),
        "validation_status": validation_report["validation_status"],
        "validation_summary": validation_report["summary"],
        "manual_bbox_edit_summary": manual_bbox_edit_summary,
        "source_freshness_summary": source_freshness_summary,
        "precise_understanding_summary": precise_understanding_summary,
        "precise_understanding_readiness_summary": precise_understanding_readiness_summary,
        "evidence_integrity": evidence_integrity,
        "model_start_runbook": model_start_runbook,
        "pending_detail_observe_requests": pending_detail_observe_requests,
        "created_at": datetime.now().isoformat(),
    }
    if correction_memory:
        wrapper["correction_memory"] = dict(correction_memory)
    wrapper_path.write_text(json.dumps(wrapper, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {
        "contract_version": "pathgraph_candidate_build_v1",
        "pathgraph_candidate_path": _relative_path(wrapper_path, root),
        "reviewed_template_candidate_path": _relative_path(reviewed_path, root),
        "runtime_path_graph_candidate_path": _relative_path(graph_path, root),
        "interface_map_candidate_path": _relative_path(interface_path, root),
        "validation_report_path": _relative_path(validation_path, root),
        "validation_status": validation_report["validation_status"],
        "artifact_type": "pathgraph_candidate",
        "counts_as_pure_model_generated": False,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
        "real_action_requires_gate": True,
        "summary": validation_report["summary"],
        "manual_bbox_edit_summary": manual_bbox_edit_summary,
        "source_freshness_summary": source_freshness_summary,
        "precise_understanding_summary": precise_understanding_summary,
        "precise_understanding_readiness_summary": precise_understanding_readiness_summary,
        "evidence_integrity": evidence_integrity,
        "model_start_runbook": model_start_runbook,
        "pending_detail_observe_requests": pending_detail_observe_requests,
        "human_review_patch_path": save_result.get("human_review_patch_path") or "",
        "human_review_patch_revision": save_result.get("human_review_patch_revision"),
        "reviewed_overlay_path": save_result.get("reviewed_overlay_path") or "",
        "changes_summary": save_result.get("changes_summary") or [],
    }
    if correction_memory:
        result["correction_memory"] = dict(correction_memory)
    return result


def build_model_generated_pathgraph_preview(
    source_path: str | Path,
    *,
    out_dir: str | Path,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """从 raw model artifact 生成只读路径图预览，不经过人工 reviewed candidate。"""
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    source_file = _resolve_under_root(source_path, root)
    out = Path(out_dir).expanduser()
    if not out.is_absolute():
        out = root / out
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)

    source_bytes = source_file.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    source_payload = json.loads(source_bytes.decode("utf-8-sig"))
    if not isinstance(source_payload, dict):
        raise ValueError("model-generated pathgraph preview source must be a JSON object")
    review = load_learning_draft_review(_relative_path(source_file, root), project_root=root)
    flat_draft = _model_generated_flat_draft(
        review.get("draft") if isinstance(review.get("draft"), dict) else {},
        source_payload,
    )
    draft = _nested_draft_from_reviewed(flat_draft)
    source_ref = {
        "trial_path": _relative_path(source_file, root),
        "source_trial_path": _relative_path(source_file, root),
        "sha256": source_hash,
        "attempt_index": None,
        "readonly": True,
        "posthoc_optimization_allowed": False,
        "candidate_mode": True,
        "source_type": source_payload.get("source_type"),
        "actual_model_call_in_this_run": source_payload.get("actual_model_call_in_this_run") is True,
        "counts_as_pure_model_generated": source_payload.get("actual_model_call_in_this_run") is True,
    }
    trial = {
        "contract_version": "model_generated_learning_draft_preview_v1",
        "app_name": _slug(str(source_payload.get("app_name") or draft.get("state_guess") or "model_generated_app"), fallback="model_generated_app"),
    }
    graph = _build_runtime_path_graph(trial, draft, source_ref)
    interface_map = _build_interface_map(trial, draft, source_ref, graph)
    _mark_candidate_graph(graph)
    _mark_candidate_interface_map(interface_map)
    graph["model_generated_preview"] = True
    graph["counts_as_pure_model_generated"] = source_payload.get("actual_model_call_in_this_run") is True
    interface_map["model_generated_preview"] = True
    interface_map["counts_as_pure_model_generated"] = source_payload.get("actual_model_call_in_this_run") is True

    preview_dir = out / "model_generated_pathgraph_preview"
    preview_dir.mkdir(parents=True, exist_ok=True)
    graph_path = preview_dir / "runtime_path_graph_model_preview.json"
    interface_path = preview_dir / "interface_map_model_preview.json"
    report_path = preview_dir / "model_generated_pathgraph_preview.json"
    graph_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    interface_path.write_text(json.dumps(interface_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    actual_model = source_payload.get("actual_model_call_in_this_run") is True
    regions = _list_of_dicts(interface_map.get("regions"))
    actions = _list_of_dicts(graph.get("action_templates"))
    transitions = _list_of_dicts(graph.get("transitions"))
    page_detail_preview = _model_generated_page_detail_preview(regions=regions, actions=actions)
    preview_status = "model_generated_preview_ready"
    blockers: list[str] = []
    if not actual_model:
        blockers.append("source_not_actual_model_call")
    if not regions:
        blockers.append("missing_regions")
    if not actions:
        blockers.append("missing_action_templates")
    if blockers:
        preview_status = "blocked_for_model_generated_demo"
    report = {
        "contract_version": "model_generated_pathgraph_preview_v1",
        "preview_status": preview_status,
        "source_path": _relative_path(source_file, root),
        "source_type": source_payload.get("source_type"),
        "actual_model_call_in_this_run": actual_model,
        "counts_as_pure_model_generated": actual_model,
        "reviewed_by_human": False,
        "source_after_review": "model_generated",
        "runtime_path_graph_model_preview_path": _relative_path(graph_path, root),
        "interface_map_model_preview_path": _relative_path(interface_path, root),
        "summary": {
            "state_count": len(_list_of_dicts(graph.get("states"))),
            "region_count": len(regions),
            "action_template_count": len(actions),
            "transition_count": len(transitions),
            "page_detail_section_count": _int_value(_dict(page_detail_preview.get("summary")).get("section_count")),
            "page_detail_possible_operation_count": _int_value(
                _dict(page_detail_preview.get("summary")).get("possible_operation_count")
            ),
            "blocker_count": len(blockers),
        },
        "page_detail_preview": page_detail_preview,
        "blockers": blockers,
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
        "interpretation": (
            "Model-generated PathGraph preview built directly from a raw learning artifact. "
            "It bypasses reviewed_template_candidate for demo provenance only and remains display-only; "
            "it does not authorize Execute or Runtime PathGraph promotion."
        ),
    }
    report["report_path"] = str(report_path.resolve())
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def attach_detail_observe_result_to_candidate(
    candidate_path: str | Path,
    *,
    request_id: str,
    detail_source_path: str | Path,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    wrapper_path = _resolve_under_root(candidate_path, root)
    wrapper = json.loads(wrapper_path.read_text(encoding="utf-8-sig"))
    if not isinstance(wrapper, dict) or wrapper.get("contract_version") != "pathgraph_candidate_v1":
        raise ValueError("candidate_path must point to pathgraph_candidate_v1")

    graph_path = _resolve_under_root(wrapper.get("runtime_path_graph_candidate_path"), root)
    interface_path = _resolve_under_root(wrapper.get("interface_map_candidate_path"), root)
    validation_path = _resolve_under_root(wrapper.get("validation_report_path"), root)
    graph = json.loads(graph_path.read_text(encoding="utf-8-sig"))
    interface_map = json.loads(interface_path.read_text(encoding="utf-8-sig"))
    validation_report = json.loads(validation_path.read_text(encoding="utf-8-sig"))

    requests = _list_of_dicts(wrapper.get("pending_detail_observe_requests"))
    request = next((item for item in requests if item.get("request_id") == request_id), None)
    if request is None:
        raise ValueError(f"pending detail observe request not found: {request_id}")
    detail_review = load_learning_draft_review(detail_source_path, project_root=root)
    detail_draft = detail_review.get("draft") if isinstance(detail_review.get("draft"), dict) else {}

    target_state_id = str(request.get("target_state_id") or "model_detail_view")
    attachment_id = f"detail_surface:{request_id}"
    namespaced_regions = _namespaced_detail_regions(detail_draft, target_state_id, attachment_id)
    namespaced_actions = _namespaced_detail_actions(detail_draft, target_state_id, attachment_id)
    _attach_regions_to_interface_map(interface_map, namespaced_regions)
    _attach_actions_to_graph(graph, namespaced_actions)
    _attach_regions_to_state(graph, target_state_id, [item["region_id"] for item in namespaced_regions])

    attachment = {
        "contract_version": "detail_surface_attachment_v1",
        "attachment_id": attachment_id,
        "request_id": request_id,
        "source_action_template_id": request.get("source_action_template_id"),
        "from_state_id": request.get("from_state_id"),
        "target_state_id": target_state_id,
        "detail_source_path": detail_review.get("source", {}).get("source_path"),
        "region_count": len(namespaced_regions),
        "action_template_count": len(namespaced_actions),
        "no_dispatch": True,
        "requires_user_review": True,
        "candidate_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
    }
    attachments = _list_of_dicts(wrapper.get("detail_surface_attachments"))
    attachments = [item for item in attachments if item.get("request_id") != request_id]
    attachments.append(attachment)

    for item in requests:
        if item.get("request_id") == request_id:
            item["status"] = "attached"
            item["attached_detail_surface_attachment_id"] = attachment_id
            item["no_dispatch"] = True
            item["execute_binding_enabled"] = False

    precise_summary = _precise_understanding_summary_from_graph(graph, interface_map, attachments)
    wrapper["pending_detail_observe_requests"] = requests
    wrapper["detail_surface_attachments"] = attachments
    wrapper["precise_understanding_summary"] = precise_summary
    validation_report["pending_detail_observe_requests"] = requests
    validation_report["detail_surface_attachments"] = attachments
    validation_report["precise_understanding_summary"] = precise_summary
    validation_report.setdefault("summary", {})["pending_detail_observe_request_count"] = len(requests)
    validation_report["summary"]["detail_surface_attachment_count"] = len(attachments)
    validation_report["summary"]["precise_understanding_summary"] = precise_summary

    graph_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    interface_path.write_text(json.dumps(interface_map, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    validation_path.write_text(json.dumps(validation_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    wrapper_path.write_text(json.dumps(wrapper, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "contract_version": "detail_observe_attachment_result_v1",
        "pathgraph_candidate_path": _relative_path(wrapper_path, root),
        "runtime_path_graph_candidate_path": _relative_path(graph_path, root),
        "interface_map_candidate_path": _relative_path(interface_path, root),
        "validation_report_path": _relative_path(validation_path, root),
        "pending_detail_observe_requests": requests,
        "detail_surface_attachments": attachments,
        "precise_understanding_summary": precise_summary,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
    }


def _nested_draft_from_reviewed(draft: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": draft.get("contract_version") or "learning_template_draft_v1",
        "screen_summary": draft.get("screen_summary") or "",
        "state_guess": draft.get("state_guess") or "",
        "workflow_draft": {
            "states": _list_of_dicts(draft.get("states")),
            "action_templates": _list_of_dicts(draft.get("action_templates")),
            "verification_rules": _list_of_dicts(draft.get("verification_rules")),
            "transitions": _list_of_dicts(draft.get("transitions")),
        },
        "interface_draft": {
            "regions": _list_of_dicts(draft.get("regions")),
            "visual_assets": _list_of_dicts(draft.get("visual_assets")),
            "dynamic_areas": _list_of_dicts(draft.get("dynamic_areas")),
            "danger_zones": _list_of_dicts(draft.get("danger_zones")),
        },
        "page_details": draft.get("page_details") if isinstance(draft.get("page_details"), dict) else {},
        "blockers": _list_of_dicts(draft.get("blockers")),
        "safety": draft.get("safety") if isinstance(draft.get("safety"), dict) else {},
    }


def _model_generated_flat_draft(draft: dict[str, Any], source_payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(draft)
    if not _list_of_dicts(result.get("states")):
        result["states"] = [
            {
                "state_id": str(result.get("state_guess") or source_payload.get("state_guess") or "model_observed_state"),
                "label": str(result.get("state_guess") or source_payload.get("state_guess") or "Model observed state"),
                "page_type": str(result.get("state_guess") or source_payload.get("state_guess") or "learned_page"),
            }
        ]
    if not _list_of_dicts(result.get("regions")):
        inventory = _list_of_dicts(source_payload.get("screen_inventory"))
        result["regions"] = [_region_from_model_inventory(item, index) for index, item in enumerate(inventory)]
    if not _list_of_dicts(result.get("action_templates")):
        result["action_templates"] = [
            action
            for action in (
                _action_from_model_region(region, index)
                for index, region in enumerate(_list_of_dicts(result.get("regions")))
            )
            if action
        ]
    if not _list_of_dicts(result.get("blockers")):
        result["blockers"] = [
            {
                "blocker_id": "model_generated_preview_requires_review",
                "label": "Model-generated preview requires review before any runtime use",
                "severity": "blocking",
            }
        ]
    if not _list_of_dicts(result.get("verification_rules")):
        result["verification_rules"] = [
            {
                "rule_id": "verify_current_screen_before_action",
                "description": "Re-observe and gate the current screen before using any preview action",
            }
        ]
    return result


def _region_from_model_inventory(item: dict[str, Any], index: int) -> dict[str, Any]:
    region_id = str(item.get("item_id") or item.get("region_id") or f"model_region_{index + 1}").strip()
    role = str(item.get("role") or item.get("region_type") or "region").strip()
    return {
        "region_id": region_id or f"model_region_{index + 1}",
        "label": item.get("label") or region_id or f"Model region {index + 1}",
        "role": role,
        "region_type": role or "model_observed_region",
        "bbox": _normalized_bbox(item.get("bbox") if isinstance(item.get("bbox"), dict) else item.get("rough_bbox_hint")),
        "source_type": item.get("source_type") or "model_screen_inventory",
        "source_item_id": item.get("item_id"),
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _action_from_model_region(region: dict[str, Any], index: int) -> dict[str, Any] | None:
    label = str(region.get("label") or region.get("region_id") or "").strip()
    role = str(region.get("role") or region.get("region_type") or "").casefold()
    text = f"{label} {role}".casefold()
    if any(term in text for term in ("submit", "send", "complete", "confirm", "payment")):
        return None
    if "input" in role or "textbox" in role or "search" in text or "location" in text:
        action_type = "input"
        semantic_action = "fill_field"
    elif "card" in role or "job" in text or "listing" in text:
        action_type = "click"
        semantic_action = "open_detail"
    elif "button" in role or "filter" in text or "menu" in text:
        action_type = "click"
        semantic_action = "open_control"
    else:
        return None
    return {
        "action_template_id": f"model_action_{index + 1}_{semantic_action}",
        "label": label or f"Model action {index + 1}",
        "action_type": action_type,
        "semantic_action": semantic_action,
        "target_entity": region.get("region_id"),
        "requires_gate": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _normalized_bbox(value: Any) -> dict[str, Any]:
    bbox = value if isinstance(value, dict) else {}
    x = bbox.get("x", 0)
    y = bbox.get("y", 0)
    width = bbox.get("width", bbox.get("w", 0))
    height = bbox.get("height", bbox.get("h", 0))
    return {"x": x, "y": y, "w": width, "h": height, "width": width, "height": height}


def _model_generated_page_detail_preview(*, regions: list[dict[str, Any]], actions: list[dict[str, Any]]) -> dict[str, Any]:
    action_by_region = {
        str(action.get("target_entity") or ""): action
        for action in actions
        if str(action.get("target_entity") or "")
    }
    layout_regions = []
    for index, region in enumerate(regions):
        bbox = _normalized_bbox(region.get("bbox"))
        action = action_by_region.get(str(region.get("region_id") or ""))
        operation = _model_preview_possible_operation(region, action)
        layout_regions.append(
            {
                "region_no": index + 1,
                "region_id": region.get("region_id") or f"model_region_{index + 1}",
                "label": region.get("label") or region.get("region_id") or f"Model region {index + 1}",
                "role": region.get("role") or region.get("region_type") or "region",
                "bbox": bbox,
                "layout_zone": _model_preview_layout_zone(region, bbox),
                "visual_order_key": [int(bbox.get("y") or 0), int(bbox.get("x") or 0)],
                "description": " · ".join(
                    [
                        str(region.get("label") or region.get("region_id") or "Model region"),
                        f"role={region.get('role') or region.get('region_type') or 'region'}",
                        f"operation={operation.get('kind')}",
                    ]
                ),
                "possible_operation": operation,
                "display_only": True,
                "execute_binding_enabled": False,
                "artifact_is_authorization": False,
            }
        )
    bounds = _model_preview_layout_bounds(layout_regions)
    sections = _model_preview_layout_sections(layout_regions)
    return {
        "contract_version": "model_generated_page_detail_preview_v1",
        "layout_mode": "model_screen_inventory_spatial_bbox_order",
        "summary": {
            "region_count": len(layout_regions),
            "section_count": len(sections),
            "possible_operation_count": sum(1 for item in layout_regions if isinstance(item.get("possible_operation"), dict)),
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
        "layout": {
            "bounds": bounds,
            "sections": sections,
            "regions": layout_regions,
        },
        "safety": {
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "runtime_pathgraph_promotion": False,
        },
    }


def _model_preview_possible_operation(region: dict[str, Any], action: dict[str, Any] | None) -> dict[str, Any]:
    if action:
        semantic = str(action.get("semantic_action") or action.get("action_type") or "inspect").strip()
        label = str(action.get("label") or semantic or "Inspect region").strip()
        return {
            "kind": semantic or "inspect",
            "label": label,
            "readiness": "model_preview_requires_gate_review",
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        }
    role = str(region.get("role") or region.get("region_type") or "").casefold()
    label = str(region.get("label") or "").casefold()
    if "input" in role or "search" in label or "location" in label:
        kind = "fill_field"
        text = "Type or edit text"
    elif "card" in role or "job" in label or "listing" in label:
        kind = "open_detail"
        text = "Open detail"
    else:
        kind = "read_only"
        text = "Read or inspect region"
    return {
        "kind": kind,
        "label": text,
        "readiness": "model_preview_requires_gate_review",
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _model_preview_layout_zone(region: dict[str, Any], bbox: dict[str, Any]) -> str:
    label = str(region.get("label") or "").casefold()
    role = str(region.get("role") or region.get("region_type") or "").casefold()
    x = int(bbox.get("x") or 0)
    y = int(bbox.get("y") or 0)
    if y < 320 and ("search" in label or "location" in label or "filter" in label or "input" in role):
        return "top_search_and_filters"
    if "detail" in label or x >= 1120:
        return "right_detail_panel"
    if "job listing" in label or "listing" in label or "count" in label or "save search" in label:
        return "left_results_list"
    if y < 320:
        return "top_search_and_filters"
    return "middle_controls"


def _model_preview_layout_bounds(regions: list[dict[str, Any]]) -> dict[str, int]:
    boxes = [_dict(item.get("bbox")) for item in regions]
    if not boxes:
        return {"x": 0, "y": 0, "w": 1, "h": 1}
    min_x = min(int(box.get("x") or 0) for box in boxes)
    min_y = min(int(box.get("y") or 0) for box in boxes)
    max_x = max(int(box.get("x") or 0) + int(box.get("w") or box.get("width") or 1) for box in boxes)
    max_y = max(int(box.get("y") or 0) + int(box.get("h") or box.get("height") or 1) for box in boxes)
    return {"x": min_x, "y": min_y, "w": max(1, max_x - min_x), "h": max(1, max_y - min_y)}


def _model_preview_layout_sections(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_zone: dict[str, list[dict[str, Any]]] = {}
    for item in sorted(regions, key=lambda value: value.get("visual_order_key") or [0, 0]):
        by_zone.setdefault(str(item.get("layout_zone") or "other"), []).append(item)
    sections = []
    for zone in ["top_search_and_filters", "left_results_list", "right_detail_panel", "middle_controls", "other"]:
        items = by_zone.get(zone) or []
        if not items:
            continue
        sections.append(
            {
                "section_id": zone,
                "label": zone.replace("_", " ").title(),
                "region_numbers": [item.get("region_no") for item in items],
                "possible_operations": sorted(
                    {str(_dict(item.get("possible_operation")).get("kind") or "read_only") for item in items}
                ),
                "regions": items,
            }
        )
    return sections


def _mark_candidate_graph(graph: dict[str, Any]) -> None:
    graph["candidate_mode"] = True
    graph["candidate_contract_version"] = "runtime_path_graph_candidate_v1"
    graph["artifact_is_authorization"] = False
    graph["execute_binding_enabled"] = False
    graph["final_submit_forbidden"] = True
    graph["real_action_requires_gate"] = True
    graph.setdefault("safety", {})
    graph["safety"].update({
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
        "real_action_requires_gate": True,
        "candidate_only": True,
    })
    graph.setdefault("loader", {})
    graph["loader"]["candidate_mode"] = True


def _mark_candidate_interface_map(interface_map: dict[str, Any]) -> None:
    interface_map["candidate_mode"] = True
    interface_map["candidate_contract_version"] = "interface_map_candidate_v1"
    interface_map["artifact_is_authorization"] = False
    interface_map["execute_binding_enabled"] = False
    interface_map.setdefault("editor_policy", {})
    interface_map["editor_policy"].update({
        "candidate_only": True,
        "execute_binding_enabled": False,
    })


def _validate_candidate(*, reviewed: dict[str, Any], graph: dict[str, Any], interface_map: dict[str, Any]) -> dict[str, Any]:
    regions = [item for item in interface_map.get("regions") or [] if isinstance(item, dict)]
    actions = [item for item in graph.get("action_templates") or [] if isinstance(item, dict)]
    states = [item for item in graph.get("states") or [] if isinstance(item, dict)]
    draft = reviewed.get("draft") if isinstance(reviewed.get("draft"), dict) else {}
    blockers = _list_of_dicts(draft.get("blockers"))
    verification_rules = _list_of_dicts(draft.get("verification_rules"))
    region_ids = {str(item.get("region_id") or "") for item in regions}
    unsafe_actions = [_action_id(item) for item in actions if _is_unsafe_final_action(item)]
    unlinked_actions = [
        _action_id(item)
        for item in actions
        if str(item.get("target_entity") or "") and str(item.get("target_entity") or "") not in region_ids
    ]
    manual_bbox_edit_summary = _manual_bbox_edit_summary_from_reviewed(reviewed)
    source_freshness_summary = _source_freshness_summary_from_reviewed(reviewed)
    precise_understanding_summary = _precise_understanding_summary_from_reviewed(reviewed)
    precise_understanding_readiness_summary = _precise_understanding_readiness_summary_from_reviewed(reviewed)
    evidence_integrity = _evidence_integrity_from_reviewed(reviewed)
    model_start_runbook = _model_start_runbook_from_reviewed(reviewed)
    missing_declared_evidence = evidence_integrity.get("status") == "missing_declared_evidence"
    pending_calibration = _precise_understanding_has_pending_calibration(precise_understanding_readiness_summary)
    pending_detail_observe_requests = _pending_detail_observe_requests(graph)
    checks = [
        _check("states_present", bool(states), {"count": len(states)}),
        _check("regions_present", bool(regions), {"count": len(regions)}),
        _check("action_templates_present", bool(actions), {"count": len(actions)}),
        _check("action_region_linkage", not unlinked_actions, {"unlinked_actions": unlinked_actions}),
        _check("blockers_present", bool(blockers), {"count": len(blockers)}),
        _check("verification_rules_present", bool(verification_rules), {"count": len(verification_rules)}),
        _check("unsafe_final_actions_absent", not unsafe_actions, {"unsafe_actions": unsafe_actions}),
        _check("artifact_is_authorization_false", reviewed.get("artifact_is_authorization") is False and graph.get("artifact_is_authorization") is False),
        _check("execute_binding_disabled", reviewed.get("execute_binding_enabled") is False and graph.get("execute_binding_enabled") is False),
        _check("final_submit_forbidden", reviewed.get("final_submit_forbidden") is True and graph.get("final_submit_forbidden") is True),
        _check("source_not_pure_model_generated", reviewed.get("counts_as_pure_model_generated") is False),
        _check(
            "precise_understanding_ready_for_pathgraph_candidate",
            not pending_calibration,
            {
                "precise_understanding_readiness_summary": precise_understanding_readiness_summary,
                "model_start_runbook": model_start_runbook,
            },
        ),
        _check(
            "precise_understanding_evidence_integrity_complete",
            not missing_declared_evidence,
            {"evidence_integrity": evidence_integrity},
        ),
        _check("no_dispatch_dry_run_preview_only", True, {"operation_dispatch": "not_executed"}),
    ]
    failed = [item for item in checks if item["passed"] is False]
    if unsafe_actions:
        status = "blocked_unsafe_action"
    elif unlinked_actions:
        status = "missing_action_region_linkage"
    elif missing_declared_evidence:
        status = "blocked_missing_evidence"
    elif pending_calibration:
        status = "blocked_pending_calibration"
    elif failed:
        missing = {item["check_id"] for item in failed}
        if "blockers_present" in missing:
            status = "missing_blockers"
        elif "verification_rules_present" in missing:
            status = "missing_verification_rules"
        else:
            status = "needs_human_review"
    else:
        status = "passed_candidate"
    return {
        "contract_version": "pathgraph_candidate_validation_report_v1",
        "validation_status": status,
        "checks": checks,
        "summary": {
            "state_count": len(states),
            "region_count": len(regions),
            "action_template_count": len(actions),
            "blocker_count": len(blockers),
            "verification_rule_count": len(verification_rules),
            "failed_check_count": len(failed),
            "operation_dispatch": "not_executed",
            "candidate_only": True,
            "manual_bbox_edit_summary": manual_bbox_edit_summary,
            "source_freshness_summary": source_freshness_summary,
            "precise_understanding_summary": precise_understanding_summary,
            "precise_understanding_readiness_summary": precise_understanding_readiness_summary,
            "evidence_integrity": evidence_integrity,
            "model_start_runbook": model_start_runbook,
            "pending_detail_observe_request_count": len(pending_detail_observe_requests),
        },
        "manual_bbox_edit_summary": manual_bbox_edit_summary,
        "source_freshness_summary": source_freshness_summary,
        "precise_understanding_summary": precise_understanding_summary,
        "precise_understanding_readiness_summary": precise_understanding_readiness_summary,
        "evidence_integrity": evidence_integrity,
        "model_start_runbook": model_start_runbook,
        "pending_detail_observe_requests": pending_detail_observe_requests,
        "safety": {
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "final_submit_forbidden": True,
            "real_action_requires_gate": True,
        },
    }


def _pending_detail_observe_requests(graph: dict[str, Any]) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for index, transition in enumerate(_list_of_dicts(graph.get("transitions"))):
        if str(transition.get("transition_type") or "") != "open_detail":
            continue
        if transition.get("requires_post_action_observe") is False:
            continue
        action_id = str(transition.get("action_template_id") or f"action_{index + 1}")
        requests.append({
            "contract_version": "pending_detail_observe_request_v1",
            "request_id": f"detail_observe:{action_id}",
            "source_action_template_id": action_id,
            "from_state_id": str(transition.get("from_state_id") or ""),
            "target_state_id": str(transition.get("to_state_id") or ""),
            "transition_id": str(transition.get("transition_id") or ""),
            "transition_type": "open_detail",
            "target_surface": str(transition.get("target_surface") or "detail_pane_or_detail_page"),
            "observe_goal": "re-observe detail surface after reviewed open_detail candidate",
            "requires_user_review": True,
            "requires_post_action_observe": True,
            "no_dispatch": True,
            "candidate_only": True,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "final_submit_forbidden": True,
        })
    return requests


def _namespaced_detail_regions(draft: dict[str, Any], target_state_id: str, attachment_id: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for index, region in enumerate(_list_of_dicts(draft.get("regions"))):
        source_region_id = str(region.get("region_id") or f"detail_region_{index + 1}")
        namespaced_id = f"{target_state_id}::{source_region_id}"
        result.append({
            **region,
            "region_id": namespaced_id,
            "source_region_id": source_region_id,
            "state_id": target_state_id,
            "detail_surface_attachment_id": attachment_id,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        })
    return result


def _namespaced_detail_actions(draft: dict[str, Any], target_state_id: str, attachment_id: str) -> list[dict[str, Any]]:
    region_ids = {
        str(region.get("region_id") or "")
        for region in _list_of_dicts(draft.get("regions"))
        if str(region.get("region_id") or "")
    }
    result: list[dict[str, Any]] = []
    for index, action in enumerate(_list_of_dicts(draft.get("action_templates"))):
        source_action_id = str(action.get("action_template_id") or action.get("action_id") or f"detail_action_{index + 1}")
        target_entity = str(action.get("target_entity") or action.get("target_region_id") or "")
        namespaced_target = f"{target_state_id}::{target_entity}" if target_entity in region_ids else target_entity
        result.append({
            **action,
            "action_template_id": f"{target_state_id}::{source_action_id}",
            "source_action_template_id": source_action_id,
            "target_entity": namespaced_target,
            "target_region_id": namespaced_target,
            "state_id": target_state_id,
            "detail_surface_attachment_id": attachment_id,
            "requires_gate": action.get("requires_gate", True),
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        })
    return result


def _attach_regions_to_interface_map(interface_map: dict[str, Any], regions: list[dict[str, Any]]) -> None:
    existing = _list_of_dicts(interface_map.get("regions"))
    replacing_ids = {item["region_id"] for item in regions}
    interface_map["regions"] = [item for item in existing if item.get("region_id") not in replacing_ids] + regions
    interface_map.setdefault("summary", {})["region_count"] = len(interface_map["regions"])


def _attach_actions_to_graph(graph: dict[str, Any], actions: list[dict[str, Any]]) -> None:
    existing = _list_of_dicts(graph.get("action_templates"))
    replacing_ids = {item["action_template_id"] for item in actions}
    graph["action_templates"] = [item for item in existing if item.get("action_template_id") not in replacing_ids] + actions
    graph.setdefault("summary", {})["action_template_count"] = len(graph["action_templates"])


def _attach_regions_to_state(graph: dict[str, Any], target_state_id: str, region_ids: list[str]) -> None:
    for state in _list_of_dicts(graph.get("states")):
        if state.get("state_id") != target_state_id:
            continue
        refs = [str(item) for item in state.get("region_refs") or [] if str(item)]
        for region_id in region_ids:
            if region_id not in refs:
                refs.append(region_id)
        state["region_refs"] = refs
        state["detail_surface_attached"] = True
        state["execute_binding_enabled"] = False
        state["artifact_is_authorization"] = False
        return


def _precise_understanding_summary_from_graph(
    graph: dict[str, Any],
    interface_map: dict[str, Any],
    attachments: list[dict[str, Any]],
) -> dict[str, Any]:
    regions = _list_of_dicts(interface_map.get("regions"))
    actions = _list_of_dicts(graph.get("action_templates"))
    open_detail_hints = [
        item
        for item in actions
        if isinstance(item.get("transition_hint"), dict)
        and item["transition_hint"].get("contract_version") == "learn_open_detail_transition_hint_v1"
    ]
    semantic_actions = sorted({
        str(item.get("semantic_action") or item.get("action_kind") or "").strip()
        for item in actions
        if str(item.get("semantic_action") or item.get("action_kind") or "").strip()
    })
    return {
        "contract_version": "precise_understanding_summary_v1",
        "state_count": len(_list_of_dicts(graph.get("states"))),
        "region_count": len(regions),
        "bbox_region_count": len([item for item in regions if isinstance(item.get("bbox"), dict) and item.get("bbox")]),
        "action_template_count": len(actions),
        "action_click_point_count": len([item for item in actions if isinstance(item.get("click_point"), dict) and item.get("click_point")]),
        "open_detail_transition_hint_count": len(open_detail_hints),
        "detail_surface_attachment_count": len(attachments),
        "semantic_actions": semantic_actions,
        "candidate_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
        "interpretation": "review-only precise understanding summary; not Execute authorization",
    }


def _manual_bbox_edit_summary_from_reviewed(reviewed: dict[str, Any]) -> dict[str, Any]:
    audit = reviewed.get("audit") if isinstance(reviewed.get("audit"), dict) else {}
    summary = audit.get("manual_bbox_edit_summary") if isinstance(audit.get("manual_bbox_edit_summary"), dict) else {}
    if summary:
        return summary
    return {
        "contract_version": "manual_bbox_edit_summary_v1",
        "edited_region_count": 0,
        "edited_action_count": 0,
        "edited_total": 0,
        "point_inside_bbox_passed": 0,
        "point_inside_bbox_failed": 0,
        "invalid_geometry_count": 0,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _source_freshness_summary_from_reviewed(reviewed: dict[str, Any]) -> dict[str, Any]:
    audit = reviewed.get("audit") if isinstance(reviewed.get("audit"), dict) else {}
    summary = audit.get("source_freshness_summary") if isinstance(audit.get("source_freshness_summary"), dict) else {}
    if summary:
        return summary
    return {
        "contract_version": "source_freshness_summary_v1",
        "source_image_status": "unknown",
        "checksum_status": "unknown",
        "freshness_status": "warning",
        "warning_count": 1,
        "warnings": ["source_freshness_summary_missing"],
        "edited_geometry_requires_review": False,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _precise_understanding_summary_from_reviewed(reviewed: dict[str, Any]) -> dict[str, Any]:
    audit = reviewed.get("audit") if isinstance(reviewed.get("audit"), dict) else {}
    summary = audit.get("precise_understanding_summary") if isinstance(audit.get("precise_understanding_summary"), dict) else {}
    if summary:
        return summary
    draft = reviewed.get("draft") if isinstance(reviewed.get("draft"), dict) else {}
    regions = _list_of_dicts(draft.get("regions"))
    actions = _list_of_dicts(draft.get("action_templates"))
    open_detail_hints = [
        item
        for item in actions
        if isinstance(item.get("transition_hint"), dict)
        and item["transition_hint"].get("contract_version") == "learn_open_detail_transition_hint_v1"
    ]
    return {
        "contract_version": "precise_understanding_summary_v1",
        "state_count": len(_list_of_dicts(draft.get("states"))),
        "region_count": len(regions),
        "bbox_region_count": len([item for item in regions if isinstance(item.get("bbox"), dict) and item.get("bbox")]),
        "action_template_count": len(actions),
        "action_click_point_count": len([item for item in actions if isinstance(item.get("click_point"), dict) and item.get("click_point")]),
        "open_detail_transition_hint_count": len(open_detail_hints),
        "blocker_count": len(_list_of_dicts(draft.get("blockers"))),
        "verification_rule_count": len(_list_of_dicts(draft.get("verification_rules"))),
        "candidate_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
        "interpretation": "review-only precise understanding summary; not Execute authorization",
    }


def _precise_understanding_readiness_summary_from_reviewed(reviewed: dict[str, Any]) -> dict[str, Any]:
    audit = reviewed.get("audit") if isinstance(reviewed.get("audit"), dict) else {}
    summary = audit.get("precise_understanding_readiness_summary")
    if isinstance(summary, dict) and summary:
        return summary
    return {
        "contract_version": "precise_understanding_readiness_summary_v1",
        "readiness_status": "not_available",
        "pending_calibration_ready_count": 0,
        "pending_calibration_review_count": 0,
        "ready_for_runtime_pathgraph_promotion": False,
        "display_only": True,
        "not_accuracy": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _evidence_integrity_from_reviewed(reviewed: dict[str, Any]) -> dict[str, Any]:
    audit = reviewed.get("audit") if isinstance(reviewed.get("audit"), dict) else {}
    integrity = audit.get("evidence_integrity")
    if isinstance(integrity, dict) and integrity:
        return integrity
    return {
        "contract_version": "learn_precise_understanding_evidence_integrity_v1",
        "status": "not_available",
        "required_for_pathgraph_review": True,
        "missing_declared_evidence": [],
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _model_start_runbook_from_reviewed(reviewed: dict[str, Any]) -> dict[str, Any]:
    audit = reviewed.get("audit") if isinstance(reviewed.get("audit"), dict) else {}
    audit_runbook = audit.get("model_start_runbook")
    if isinstance(audit_runbook, dict) and audit_runbook:
        return _model_start_runbook_summary(audit_runbook)
    draft = reviewed.get("draft") if isinstance(reviewed.get("draft"), dict) else {}
    page_details = draft.get("page_details") if isinstance(draft.get("page_details"), dict) else {}
    pipeline_audit = page_details.get("pipeline_audit") if isinstance(page_details.get("pipeline_audit"), dict) else {}
    fusion_status = (
        pipeline_audit.get("precise_understanding_fusion_status")
        if isinstance(pipeline_audit.get("precise_understanding_fusion_status"), dict)
        else {}
    )
    runbook = fusion_status.get("model_start_runbook")
    if isinstance(runbook, dict) and runbook:
        return _model_start_runbook_summary(runbook)
    return {
        "contract_version": "learning_draft_model_start_runbook_v1",
        "runbook_status": "not_available",
        "approval_required": False,
        "may_start_model_after_user_approval": False,
        "may_run_calibration_batch_now": False,
        "next_manual_action": "repair_or_attach_model_start_runbook_before_calibration",
        "ready_region_numbers": [],
        "review_blocked_region_numbers": [],
        "guards": {},
        "safety": {
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "model_started": False,
            "live_clicks": 0,
            "live_fills": 0,
            "live_submits": 0,
        },
        "blockers": ["model_start_runbook_missing"],
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _model_start_runbook_summary(runbook: dict[str, Any]) -> dict[str, Any]:
    guards = runbook.get("guards") if isinstance(runbook.get("guards"), dict) else {}
    safety = runbook.get("safety") if isinstance(runbook.get("safety"), dict) else {}
    return {
        "contract_version": str(runbook.get("contract_version") or "learning_draft_model_start_runbook_v1"),
        "runbook_status": str(runbook.get("runbook_status") or ""),
        "approval_required": runbook.get("approval_required") is True,
        "may_start_model_after_user_approval": runbook.get("may_start_model_after_user_approval") is True,
        "may_run_calibration_batch_now": runbook.get("may_run_calibration_batch_now") is True,
        "next_manual_action": str(runbook.get("next_manual_action") or ""),
        "ready_region_numbers": _list_of_ints(runbook.get("ready_region_numbers")),
        "review_blocked_region_numbers": _list_of_ints(runbook.get("review_blocked_region_numbers")),
        "guards": {
            "post_batch_refresh_has_batch_plan": guards.get("post_batch_refresh_has_batch_plan") is True,
            "prebatch_refresh_blocks_before_future_rerun": guards.get("prebatch_refresh_blocks_before_future_rerun") is True,
            "acceptance_required_before_refresh": guards.get("acceptance_required_before_refresh") is True,
            "accepted_for_post_batch_refresh": guards.get("accepted_for_post_batch_refresh") is True,
        },
        "safety": {
            "display_only": True,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "model_started": safety.get("model_started") is True,
            "live_clicks": _int_value(safety.get("live_clicks")),
            "live_fills": _int_value(safety.get("live_fills")),
            "live_submits": _int_value(safety.get("live_submits")),
        },
        "blockers": _list_of_strings(runbook.get("blockers")),
        "display_only": True,
        "execute_binding_enabled": False,
        "artifact_is_authorization": False,
    }


def _precise_understanding_has_pending_calibration(summary: dict[str, Any]) -> bool:
    status = str(summary.get("readiness_status") or "")
    if status == "needs_pending_calibration":
        return True
    return int(summary.get("pending_calibration_ready_count") or 0) > 0


def _check(check_id: str, passed: bool, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "passed": bool(passed),
        "severity": "hard_error",
        "details": details or {},
    }


def _list_of_ints(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item or "").strip()]


def _int_value(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _is_unsafe_final_action(action: dict[str, Any]) -> bool:
    text = " ".join(str(action.get(key) or "") for key in ("action_template_id", "label", "semantic_action", "action_type", "low_level_action_type")).casefold()
    unsafe_terms = ("submit", "send", "complete", "confirm", "payment", "final apply", "review and submit")
    return any(term in text for term in unsafe_terms)


def _action_id(action: dict[str, Any]) -> str:
    return str(action.get("action_template_id") or action.get("action_id") or action.get("label") or "unknown_action")


def _app_name_from_reviewed(reviewed: dict[str, Any], draft: dict[str, Any]) -> str:
    source = reviewed.get("source") if isinstance(reviewed.get("source"), dict) else {}
    for value in (reviewed.get("app_name"), draft.get("app_name"), source.get("app_name"), source.get("source_trial_path")):
        if value:
            return _slug(str(value), fallback="reviewed_learning_app")
    return "reviewed_learning_app"


def _resolve_under_root(path_value: str | Path, root: Path) -> Path:
    path = Path(path_value).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    allowed_roots = [(root / "artifacts").resolve(), (root / "logs").resolve()]
    if not any(path == allowed or allowed in path.parents for allowed in allowed_roots):
        raise ValueError("pathgraph candidate source must be under artifacts or logs")
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(str(path))
    return path


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _slug(value: str, *, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._-").lower()
    return cleaned[:80] or fallback


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
