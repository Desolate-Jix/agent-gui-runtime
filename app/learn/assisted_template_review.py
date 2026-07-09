from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from app.learn.draft_review import load_learning_draft_review

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_VERSION = "assisted_template_review_package_v1"


def create_assisted_template_review_package(
    candidate_path: str | Path,
    *,
    review_decision: str = "prepare_for_review",
    reviewer_note: str = "",
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """把通过 promotion-review gate 的候选整理成审查包；仍不授权执行。"""
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    wrapper_path = _resolve_under_root(candidate_path, root)
    wrapper = _read_json(wrapper_path)
    if wrapper.get("contract_version") != "pathgraph_candidate_v1":
        raise ValueError("candidate_path must point to pathgraph_candidate_v1")

    review = load_learning_draft_review(wrapper_path, project_root=root)
    candidate_review = review.get("pathgraph_candidate_review") if isinstance(review.get("pathgraph_candidate_review"), dict) else {}
    readiness = (
        candidate_review.get("pathgraph_readiness_summary")
        if isinstance(candidate_review.get("pathgraph_readiness_summary"), dict)
        else {}
    )
    gate = readiness.get("promotion_review_gate") if isinstance(readiness.get("promotion_review_gate"), dict) else {}
    failed_checks = gate.get("failed_check_ids") if isinstance(gate.get("failed_check_ids"), list) else []
    if gate.get("gate_status") != "passed_for_human_promotion_review":
        raise ValueError(f"pathgraph candidate is not ready for human promotion review: {failed_checks}")

    graph_path = _resolve_under_root(wrapper.get("runtime_path_graph_candidate_path"), root)
    interface_path = _resolve_under_root(wrapper.get("interface_map_candidate_path"), root)
    validation_path = _resolve_under_root(wrapper.get("validation_report_path"), root)
    reviewed_path = _resolve_under_root(wrapper.get("reviewed_template_candidate_path"), root)
    graph = _read_json(graph_path)
    interface_map = _read_json(interface_path)
    validation_report = _read_json(validation_path)
    reviewed = _read_json(reviewed_path)

    decision = _review_decision(review_decision)
    out_dir = wrapper_path.parent / "assisted_template_review"
    out_dir.mkdir(parents=True, exist_ok=True)
    package_path = out_dir / "assisted_template_review_package.json"
    package = {
        "contract_version": CONTRACT_VERSION,
        "package_status": "ready_for_human_assisted_template_review",
        "review_decision": decision,
        "reviewer_note": str(reviewer_note or ""),
        "created_at": datetime.now().isoformat(),
        "source_tracking": "assisted_generation",
        "counts_as_pure_model_generated": False,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
        "real_action_requires_gate": True,
        "authorization_scope": "display_and_review_only",
        "ready_for_runtime_pathgraph_promotion": False,
        "candidate_path": _relative_path(wrapper_path, root),
        "reviewed_template_candidate_path": _relative_path(reviewed_path, root),
        "runtime_path_graph_candidate_path": _relative_path(graph_path, root),
        "interface_map_candidate_path": _relative_path(interface_path, root),
        "validation_report_path": _relative_path(validation_path, root),
        "candidate_sha256": hashlib.sha256(wrapper_path.read_bytes()).hexdigest(),
        "reviewed_template_candidate_sha256": hashlib.sha256(reviewed_path.read_bytes()).hexdigest(),
        "readiness_summary": readiness,
        "promotion_review_gate": gate,
        "source_freshness_summary": wrapper.get("source_freshness_summary")
        if isinstance(wrapper.get("source_freshness_summary"), dict)
        else {},
        "precise_understanding_summary": wrapper.get("precise_understanding_summary")
        if isinstance(wrapper.get("precise_understanding_summary"), dict)
        else {},
        "detail_surface_attachments": _list_of_dicts(wrapper.get("detail_surface_attachments")),
        "pending_detail_observe_requests": _list_of_dicts(wrapper.get("pending_detail_observe_requests")),
        "checklist_items": _checklist_items(graph=graph, interface_map=interface_map),
        "summary": {
            "state_count": len(_list_of_dicts(graph.get("states"))),
            "region_count": len(_list_of_dicts(interface_map.get("regions"))),
            "action_template_count": len(_list_of_dicts(graph.get("action_templates"))),
            "transition_count": len(_list_of_dicts(graph.get("transitions"))),
            "detail_surface_attachment_count": len(_list_of_dicts(wrapper.get("detail_surface_attachments"))),
            "validation_status": validation_report.get("validation_status") or wrapper.get("validation_status") or "",
            "promotion_gate_status": gate.get("gate_status") or "",
            "remaining_failed_checks": failed_checks,
            "ready_for_runtime_pathgraph_promotion": False,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
        },
        "review_payload_refs": {
            "draft_contract_version": reviewed.get("contract_version") or "",
            "graph_contract_version": graph.get("contract_version") or "",
            "interface_map_contract_version": interface_map.get("contract_version") or "",
        },
        "interpretation": (
            "human-review package for an assisted template candidate; passing the promotion-review gate does not "
            "authorize Execute, clicks, form filling, submit, or Runtime PathGraph promotion"
        ),
    }
    package_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "contract_version": "assisted_template_review_package_create_v1",
        "package_path": _relative_path(package_path, root),
        "package_status": package["package_status"],
        "review_decision": decision,
        "candidate_path": package["candidate_path"],
        "promotion_gate_status": gate.get("gate_status") or "",
        "remaining_failed_checks": failed_checks,
        "ready_for_runtime_pathgraph_promotion": False,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "final_submit_forbidden": True,
        "summary": package["summary"],
    }


def load_assisted_template_review_package(
    package_path: str | Path,
    *,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """加载审查包并确认它仍是非执行资产。"""
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    resolved = _resolve_under_root(package_path, root)
    package = _read_json(resolved)
    if package.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("package_path must point to assisted_template_review_package_v1")
    if package.get("execute_binding_enabled") is not False or package.get("artifact_is_authorization") is not False:
        raise ValueError("assisted template review package must remain non-authorizing")
    package = dict(package)
    package["package_path"] = _relative_path(resolved, root)
    package["package_sha256"] = hashlib.sha256(resolved.read_bytes()).hexdigest()
    package["review_record"] = _optional_non_authorizing_artifact(
        resolved.parent / "assisted_template_review_record.json",
        root=root,
        contract_version="assisted_template_review_record_v1",
        missing_status="missing_review_record",
    )
    package["asset_candidate"] = _optional_non_authorizing_artifact(
        resolved.parent / "assisted_template_asset_candidate.json",
        root=root,
        contract_version="assisted_template_asset_candidate_v1",
        missing_status="missing_asset_candidate",
    )
    package["graph_draft"] = _optional_non_authorizing_artifact(
        resolved.parent / "assisted_template_graph_draft.json",
        root=root,
        contract_version="assisted_template_graph_draft_v1",
        missing_status="missing_graph_draft",
    )
    package["acceptance_suggestions"] = _optional_non_authorizing_artifact(
        resolved.parent / "assisted_template_acceptance_suggestions.json",
        root=root,
        contract_version="assisted_template_acceptance_suggestions_v1",
        missing_status="missing_acceptance_suggestions",
    )
    package["acceptance_simulation"] = _optional_non_authorizing_artifact(
        resolved.parent / "assisted_template_acceptance_simulation.json",
        root=root,
        contract_version="assisted_template_acceptance_simulation_v1",
        missing_status="missing_acceptance_simulation",
    )
    package["promotion_preflight"] = _optional_non_authorizing_artifact(
        resolved.parent / "assisted_template_promotion_preflight.json",
        root=root,
        contract_version="assisted_template_promotion_preflight_v1",
        missing_status="missing_promotion_preflight",
    )
    package["audited_promotion_request"] = _optional_non_authorizing_artifact(
        resolved.parent / "assisted_template_audited_promotion_request.json",
        root=root,
        contract_version="assisted_template_audited_promotion_request_v1",
        missing_status="missing_audited_promotion_request",
    )
    return package


def save_assisted_template_review_decisions(
    package_path: str | Path,
    decisions: list[dict[str, Any]],
    *,
    overall_decision: str = "needs_changes",
    reviewer_note: str = "",
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """保存人工 checklist 决策；只写 review record，不改候选路径图。"""
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    package = load_assisted_template_review_package(package_path, project_root=root)
    package_resolved = _resolve_under_root(package_path, root)
    valid_items = {
        (str(item.get("item_type") or ""), str(item.get("item_id") or ""))
        for item in _list_of_dicts(package.get("checklist_items"))
    }
    normalized: list[dict[str, Any]] = []
    for item in _list_of_dicts(decisions):
        item_type = str(item.get("item_type") or "").strip()
        item_id = str(item.get("item_id") or "").strip()
        if (item_type, item_id) not in valid_items:
            continue
        normalized.append(
            {
                "item_type": item_type,
                "item_id": item_id,
                "decision": _item_decision(str(item.get("decision") or "")),
                "note": str(item.get("note") or ""),
                "overrides": _safe_item_overrides(item.get("overrides")),
            }
        )
    out_path = package_resolved.parent / "assisted_template_review_record.json"
    record = {
        "contract_version": "assisted_template_review_record_v1",
        "package_path": _relative_path(package_resolved, root),
        "package_sha256": package.get("package_sha256") or hashlib.sha256(package_resolved.read_bytes()).hexdigest(),
        "overall_decision": _review_record_decision(overall_decision),
        "reviewer_note": str(reviewer_note or ""),
        "item_decisions": normalized,
        "decision_summary": _decision_summary(normalized),
        "created_at": datetime.now().isoformat(),
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "ready_for_runtime_pathgraph_promotion": False,
        "final_submit_forbidden": True,
        "interpretation": "human checklist decisions only; not Runtime PathGraph promotion or Execute authorization",
    }
    out_path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "contract_version": "assisted_template_review_record_save_v1",
        "review_record_path": _relative_path(out_path, root),
        "package_path": record["package_path"],
        "overall_decision": record["overall_decision"],
        "decision_summary": record["decision_summary"],
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "ready_for_runtime_pathgraph_promotion": False,
        "final_submit_forbidden": True,
    }


def create_assisted_template_asset_candidate(
    package_path: str | Path,
    *,
    review_record_path: str | Path | None = None,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """把已接受的人工清单项导出成候选资产；仍不授权 Runtime/Execute。"""
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    package = load_assisted_template_review_package(package_path, project_root=root)
    package_resolved = _resolve_under_root(package_path, root)
    record_resolved = (
        _resolve_under_root(review_record_path, root)
        if review_record_path
        else package_resolved.parent / "assisted_template_review_record.json"
    )
    if not record_resolved.exists() or not record_resolved.is_file():
        raise FileNotFoundError(str(record_resolved))
    record = _read_json(record_resolved)
    if record.get("contract_version") != "assisted_template_review_record_v1":
        raise ValueError("review_record_path must point to assisted_template_review_record_v1")
    if record.get("execute_binding_enabled") is not False or record.get("artifact_is_authorization") is not False:
        raise ValueError("assisted template review record must remain non-authorizing")

    graph_path = _resolve_under_root(package.get("runtime_path_graph_candidate_path"), root)
    interface_path = _resolve_under_root(package.get("interface_map_candidate_path"), root)
    validation_path = _resolve_under_root(package.get("validation_report_path"), root)
    graph = _read_json(graph_path)
    interface_map = _read_json(interface_path)
    validation = _read_json(validation_path)

    accepted_keys = {
        (str(item.get("item_type") or ""), str(item.get("item_id") or ""))
        for item in _list_of_dicts(record.get("item_decisions"))
        if _item_decision(str(item.get("decision") or "")) == "accepted"
    }
    accepted_notes = {
        (str(item.get("item_type") or ""), str(item.get("item_id") or "")): str(item.get("note") or "")
        for item in _list_of_dicts(record.get("item_decisions"))
        if _item_decision(str(item.get("decision") or "")) == "accepted"
    }
    accepted_overrides = {
        (str(item.get("item_type") or ""), str(item.get("item_id") or "")): _safe_item_overrides(item.get("overrides"))
        for item in _list_of_dicts(record.get("item_decisions"))
        if _item_decision(str(item.get("decision") or "")) == "accepted"
    }
    accepted = _accepted_payload(
        accepted_keys=accepted_keys,
        accepted_notes=accepted_notes,
        accepted_overrides=accepted_overrides,
        graph=graph,
        interface_map=interface_map,
    )
    accepted_count = sum(len(items) for items in accepted.values())
    asset_validation_summary = _asset_validation_summary(accepted)
    status = "ready_for_manual_template_asset_review" if accepted_count else "no_accepted_items"
    out_path = package_resolved.parent / "assisted_template_asset_candidate.json"
    asset = {
        "contract_version": "assisted_template_asset_candidate_v1",
        "asset_candidate_status": status,
        "source_tracking": "assisted_generation",
        "counts_as_pure_model_generated": False,
        "created_at": datetime.now().isoformat(),
        "package_path": _relative_path(package_resolved, root),
        "review_record_path": _relative_path(record_resolved, root),
        "package_sha256": hashlib.sha256(package_resolved.read_bytes()).hexdigest(),
        "review_record_sha256": hashlib.sha256(record_resolved.read_bytes()).hexdigest(),
        "runtime_path_graph_candidate_path": _relative_path(graph_path, root),
        "runtime_path_graph_candidate_sha256": hashlib.sha256(graph_path.read_bytes()).hexdigest(),
        "interface_map_candidate_path": _relative_path(interface_path, root),
        "interface_map_candidate_sha256": hashlib.sha256(interface_path.read_bytes()).hexdigest(),
        "validation_report_path": _relative_path(validation_path, root),
        "validation_report_sha256": hashlib.sha256(validation_path.read_bytes()).hexdigest(),
        "accepted_items": accepted,
        "accepted_item_keys": [
            {
                "item_type": item_type,
                "item_id": item_id,
                "note": accepted_notes.get((item_type, item_id), ""),
                "overrides": accepted_overrides.get((item_type, item_id), {}),
            }
            for item_type, item_id in sorted(accepted_keys)
        ],
        "summary": {
            "accepted_state_count": len(accepted["states"]),
            "accepted_region_count": len(accepted["regions"]),
            "accepted_action_template_count": len(accepted["action_templates"]),
            "accepted_transition_count": len(accepted["transitions"]),
            "accepted_total_count": accepted_count,
            "asset_validation_status": asset_validation_summary["validation_status"],
            "asset_validation_error_count": asset_validation_summary["error_count"],
            "asset_validation_warning_count": asset_validation_summary["warning_count"],
            "review_decision": record.get("overall_decision") or "needs_changes",
            "validation_status": validation.get("validation_status") or "",
        },
        "asset_validation_summary": asset_validation_summary,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "ready_for_runtime_pathgraph_promotion": False,
        "final_submit_forbidden": True,
        "real_action_requires_gate": True,
        "authorization_scope": "display_and_review_only",
        "interpretation": (
            "accepted checklist items exported as a reviewable assisted-template asset candidate; "
            "this does not authorize Execute, clicks, form filling, submit, or Runtime PathGraph promotion"
        ),
    }
    out_path.write_text(json.dumps(asset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "contract_version": "assisted_template_asset_candidate_create_v1",
        "asset_candidate_path": _relative_path(out_path, root),
        "asset_candidate_status": status,
        "summary": asset["summary"],
        "asset_validation_summary": asset_validation_summary,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "ready_for_runtime_pathgraph_promotion": False,
        "final_submit_forbidden": True,
    }


def create_assisted_template_graph_draft(
    asset_candidate_path: str | Path,
    *,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """把资产候选整理成只读 PathGraph 形状草稿；仍不做 Runtime promotion。"""
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    asset_path = _resolve_under_root(asset_candidate_path, root)
    asset = _read_json(asset_path)
    if asset.get("contract_version") != "assisted_template_asset_candidate_v1":
        raise ValueError("asset_candidate_path must point to assisted_template_asset_candidate_v1")
    if asset.get("execute_binding_enabled") is not False or asset.get("artifact_is_authorization") is not False:
        raise ValueError("assisted template asset candidate must remain non-authorizing")
    accepted = asset.get("accepted_items") if isinstance(asset.get("accepted_items"), dict) else {}
    validation = (
        asset.get("asset_validation_summary")
        if isinstance(asset.get("asset_validation_summary"), dict)
        else _asset_validation_summary(
            {
                "states": _list_of_dicts(accepted.get("states")),
                "regions": _list_of_dicts(accepted.get("regions")),
                "action_templates": _list_of_dicts(accepted.get("action_templates")),
                "transitions": _list_of_dicts(accepted.get("transitions")),
            }
        )
    )
    validation_status = str(validation.get("validation_status") or "not_evaluated")
    if validation_status == "passed_manual_asset_checks":
        draft_status = "ready_for_manual_pathgraph_review"
    elif validation_status == "no_accepted_items":
        draft_status = "no_accepted_items"
    else:
        draft_status = "blocked_by_asset_validation"
    graph = {
        "contract_version": "assisted_template_graph_draft_v1",
        "graph_draft_status": draft_status,
        "source_tracking": "assisted_generation",
        "counts_as_pure_model_generated": False,
        "created_at": datetime.now().isoformat(),
        "asset_candidate_path": _relative_path(asset_path, root),
        "asset_candidate_sha256": hashlib.sha256(asset_path.read_bytes()).hexdigest(),
        "asset_validation_summary": validation,
        "states": [_non_authorizing_copy(item) for item in _list_of_dicts(accepted.get("states"))],
        "regions": [_non_authorizing_copy(item) for item in _list_of_dicts(accepted.get("regions"))],
        "action_templates": [_non_authorizing_copy(item) for item in _list_of_dicts(accepted.get("action_templates"))],
        "transitions": [_non_authorizing_copy(item) for item in _list_of_dicts(accepted.get("transitions"))],
        "summary": {
            "state_count": len(_list_of_dicts(accepted.get("states"))),
            "region_count": len(_list_of_dicts(accepted.get("regions"))),
            "action_template_count": len(_list_of_dicts(accepted.get("action_templates"))),
            "transition_count": len(_list_of_dicts(accepted.get("transitions"))),
            "asset_validation_status": validation_status,
            "asset_validation_error_count": validation.get("error_count", 0),
            "asset_validation_warning_count": validation.get("warning_count", 0),
        },
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "ready_for_runtime_pathgraph_promotion": False,
        "final_submit_forbidden": True,
        "authorization_scope": "display_and_review_only",
        "interpretation": (
            "read-only graph-shaped assisted-template draft for manual PathGraph review; "
            "this does not promote Runtime PathGraph or authorize Execute"
        ),
    }
    out_path = asset_path.parent / "assisted_template_graph_draft.json"
    out_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "contract_version": "assisted_template_graph_draft_create_v1",
        "graph_draft_path": _relative_path(out_path, root),
        "graph_draft_status": draft_status,
        "summary": graph["summary"],
        "asset_validation_summary": validation,
        "states": graph["states"],
        "regions": graph["regions"],
        "action_templates": graph["action_templates"],
        "transitions": graph["transitions"],
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "ready_for_runtime_pathgraph_promotion": False,
        "final_submit_forbidden": True,
    }


def create_assisted_template_acceptance_suggestions(
    package_path: str | Path,
    *,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """生成成组 accepted 建议；只辅助人工选择，不写 review record。"""
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    package = load_assisted_template_review_package(package_path, project_root=root)
    package_resolved = _resolve_under_root(package_path, root)
    graph_path = _resolve_under_root(package.get("runtime_path_graph_candidate_path"), root)
    interface_path = _resolve_under_root(package.get("interface_map_candidate_path"), root)
    graph = _read_json(graph_path)
    interface_map = _read_json(interface_path)
    region_ids = {str(item.get("region_id") or "") for item in _list_of_dicts(interface_map.get("regions"))}
    state_ids = {str(item.get("state_id") or "") for item in _list_of_dicts(graph.get("states"))}
    transitions = _list_of_dicts(graph.get("transitions"))
    suggestions: list[dict[str, Any]] = []
    for action in _list_of_dicts(graph.get("action_templates")):
        action_id = str(action.get("action_template_id") or action.get("action_id") or "").strip()
        if not action_id:
            continue
        target = str(action.get("target_entity") or action.get("target_region_id") or "").strip()
        linked_transitions = [
            item for item in transitions if str(item.get("action_template_id") or "").strip() == action_id
        ]
        items: list[dict[str, str]] = []
        if target and target in region_ids:
            items.append({"item_type": "region", "item_id": target})
        items.append({"item_type": "action", "item_id": action_id})
        for transition in linked_transitions:
            from_state = str(transition.get("from_state_id") or "").strip()
            to_state = str(transition.get("to_state_id") or "").strip()
            for state_id in (from_state, to_state):
                if state_id and state_id in state_ids:
                    items.append({"item_type": "state", "item_id": state_id})
            transition_id = str(transition.get("transition_id") or "").strip()
            if transition_id:
                items.append({"item_type": "transition", "item_id": transition_id})
        suggestions.append(
            {
                "suggestion_id": f"linked_acceptance:{action_id}",
                "label": str(action.get("label") or action_id),
                "semantic_action": str(action.get("semantic_action") or action.get("action_kind") or ""),
                "target_entity": target,
                "recommended_decision": "accepted",
                "item_count": len(_dedupe_items(items)),
                "items": _dedupe_items(items),
                "recommended_note": "linked suggestion generated from action target and transition references",
                "overrides": _safe_item_overrides(
                    {
                        "label": action.get("label"),
                        "semantic_action": action.get("semantic_action") or action.get("action_kind"),
                        "target_entity": target,
                    }
                ),
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        )
    out_path = package_resolved.parent / "assisted_template_acceptance_suggestions.json"
    payload = {
        "contract_version": "assisted_template_acceptance_suggestions_v1",
        "suggestion_status": "ready_for_human_review" if suggestions else "no_suggestions",
        "created_at": datetime.now().isoformat(),
        "package_path": _relative_path(package_resolved, root),
        "package_sha256": hashlib.sha256(package_resolved.read_bytes()).hexdigest(),
        "suggestions": suggestions,
        "summary": {
            "suggestion_count": len(suggestions),
            "action_suggestion_count": len(suggestions),
        },
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "ready_for_runtime_pathgraph_promotion": False,
        "final_submit_forbidden": True,
        "interpretation": "human acceptance suggestions only; not review decisions and not Runtime PathGraph promotion",
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "contract_version": "assisted_template_acceptance_suggestions_create_v1",
        "suggestions_path": _relative_path(out_path, root),
        "suggestion_status": payload["suggestion_status"],
        "suggestions": suggestions,
        "summary": payload["summary"],
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "ready_for_runtime_pathgraph_promotion": False,
        "final_submit_forbidden": True,
    }


def create_assisted_template_acceptance_simulation(
    package_path: str | Path,
    *,
    suggestion_ids: list[str] | None = None,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """按 acceptance suggestions 预演人工接受后的图准备状态；不写真实 review record。"""
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    package = load_assisted_template_review_package(package_path, project_root=root)
    package_resolved = _resolve_under_root(package_path, root)
    suggestions_path = package_resolved.parent / "assisted_template_acceptance_suggestions.json"
    if not suggestions_path.exists() or not suggestions_path.is_file():
        raise FileNotFoundError(str(suggestions_path))
    suggestions_payload = _read_json(suggestions_path)
    if suggestions_payload.get("contract_version") != "assisted_template_acceptance_suggestions_v1":
        raise ValueError("acceptance suggestions must point to assisted_template_acceptance_suggestions_v1")
    if (
        suggestions_payload.get("execute_binding_enabled") is not False
        or suggestions_payload.get("artifact_is_authorization") is not False
    ):
        raise ValueError("acceptance suggestions must remain non-authorizing")

    selected_ids = {str(item).strip() for item in suggestion_ids or [] if str(item).strip()}
    suggestions = [
        item
        for item in _list_of_dicts(suggestions_payload.get("suggestions"))
        if not selected_ids or str(item.get("suggestion_id") or "") in selected_ids
    ]
    accepted_keys: set[tuple[str, str]] = set()
    accepted_notes: dict[tuple[str, str], str] = {}
    accepted_overrides: dict[tuple[str, str], dict[str, str]] = {}
    suggestion_results: list[dict[str, Any]] = []
    for suggestion in suggestions:
        note = str(suggestion.get("recommended_note") or "")
        overrides = _safe_item_overrides(suggestion.get("overrides"))
        item_keys: list[tuple[str, str]] = []
        for item in _list_of_dicts(suggestion.get("items")):
            item_type = str(item.get("item_type") or "").strip()
            item_id = str(item.get("item_id") or "").strip()
            if not item_type or not item_id:
                continue
            key = (item_type, item_id)
            accepted_keys.add(key)
            accepted_notes.setdefault(key, note)
            if item_type == "action" and overrides:
                accepted_overrides[key] = overrides
            item_keys.append(key)
        suggestion_results.append(
            {
                "suggestion_id": str(suggestion.get("suggestion_id") or ""),
                "label": str(suggestion.get("label") or ""),
                "selected": True,
                "item_count": len(set(item_keys)),
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        )

    graph_path = _resolve_under_root(package.get("runtime_path_graph_candidate_path"), root)
    interface_path = _resolve_under_root(package.get("interface_map_candidate_path"), root)
    graph = _read_json(graph_path)
    interface_map = _read_json(interface_path)
    accepted = _accepted_payload(
        accepted_keys=accepted_keys,
        accepted_notes=accepted_notes,
        accepted_overrides=accepted_overrides,
        graph=graph,
        interface_map=interface_map,
    )
    validation = _asset_validation_summary(accepted)
    accepted_count = sum(len(items) for items in accepted.values())
    validation_passed = validation.get("validation_status") == "passed_manual_asset_checks"
    checks = {
        "review_record_would_be_saved": bool(accepted_count),
        "accepted_items_present": bool(accepted_count),
        "asset_validation_would_pass": validation_passed,
        "graph_draft_would_be_ready": bool(accepted_count and validation_passed),
        "accepted_items_would_export_to_graph": bool(accepted_count and validation_passed),
        "no_execute_binding": True,
        "no_authorization_artifact": True,
    }
    blockers = [key for key, passed in checks.items() if not passed]
    simulated_preflight_status = (
        "ready_for_audited_runtime_promotion_review" if not blockers else "blocked_before_runtime_promotion_review"
    )
    simulation_status = (
        "would_make_preflight_ready_for_audit_request_preview"
        if simulated_preflight_status == "ready_for_audited_runtime_promotion_review"
        else "would_remain_blocked_before_audit_request_preview"
    )
    out_path = package_resolved.parent / "assisted_template_acceptance_simulation.json"
    payload = {
        "contract_version": "assisted_template_acceptance_simulation_v1",
        "simulation_status": simulation_status,
        "created_at": datetime.now().isoformat(),
        "package_path": _relative_path(package_resolved, root),
        "package_sha256": hashlib.sha256(package_resolved.read_bytes()).hexdigest(),
        "acceptance_suggestions_path": _relative_path(suggestions_path, root),
        "acceptance_suggestions_sha256": hashlib.sha256(suggestions_path.read_bytes()).hexdigest(),
        "selected_suggestion_ids": [item["suggestion_id"] for item in suggestion_results],
        "suggestion_results": suggestion_results,
        "simulated_review_record": {
            "decision_summary": {
                "accepted": accepted_count,
                "needs_changes": 0,
                "rejected": 0,
                "pending_review": 0,
                "total": accepted_count,
            },
            "would_write_review_record": bool(accepted_count),
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        },
        "simulated_asset_validation_summary": validation,
        "simulated_counts": {
            "selected_suggestion_count": len(suggestion_results),
            "accepted_review_items": accepted_count,
            "exported_asset_items": accepted_count if validation_passed else 0,
            "graph_draft_items": accepted_count if validation_passed else 0,
        },
        "simulated_preflight": {
            "preflight_status": simulated_preflight_status,
            "checks": checks,
            "blockers": blockers,
            "blocker_details": [_promotion_preflight_blocker_detail(item) for item in blockers],
            "ready_for_runtime_pathgraph_promotion": False,
            "execute_binding_enabled": False,
            "artifact_is_authorization": False,
            "final_submit_forbidden": True,
        },
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "ready_for_runtime_pathgraph_promotion": False,
        "final_submit_forbidden": True,
        "interpretation": (
            "acceptance simulation only; it previews whether suggested human decisions could unblock audit-request "
            "preflight, but it does not save review decisions, create Runtime PathGraph promotion, or authorize Execute"
        ),
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "contract_version": "assisted_template_acceptance_simulation_create_v1",
        "simulation_path": _relative_path(out_path, root),
        "simulation_status": simulation_status,
        "selected_suggestion_ids": payload["selected_suggestion_ids"],
        "summary": payload["simulated_counts"],
        "simulated_preflight": payload["simulated_preflight"],
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "ready_for_runtime_pathgraph_promotion": False,
        "final_submit_forbidden": True,
    }


def create_assisted_template_promotion_preflight(
    package_path: str | Path,
    *,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """生成 Runtime promotion 前的人工审计预检；不授权 promotion。"""
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    package = load_assisted_template_review_package(package_path, project_root=root)
    package_resolved = _resolve_under_root(package_path, root)
    record = package.get("review_record") if isinstance(package.get("review_record"), dict) else {}
    asset = package.get("asset_candidate") if isinstance(package.get("asset_candidate"), dict) else {}
    graph = package.get("graph_draft") if isinstance(package.get("graph_draft"), dict) else {}
    record_loaded = record.get("load_status") == "loaded"
    asset_loaded = asset.get("load_status") == "loaded"
    graph_loaded = graph.get("load_status") == "loaded"
    decision_summary = record.get("decision_summary") if isinstance(record.get("decision_summary"), dict) else {}
    asset_summary = asset.get("summary") if isinstance(asset.get("summary"), dict) else {}
    graph_summary = graph.get("summary") if isinstance(graph.get("summary"), dict) else {}
    validation = asset.get("asset_validation_summary") if isinstance(asset.get("asset_validation_summary"), dict) else {}
    accepted_total = int(decision_summary.get("accepted") or 0)
    exported_total = int(asset_summary.get("accepted_total_count") or 0)
    graph_total = sum(
        int(graph_summary.get(key) or 0)
        for key in ("state_count", "region_count", "action_template_count", "transition_count")
    )
    accepted_items_exported_to_graph = accepted_total > 0 and accepted_total == exported_total == graph_total
    checks = {
        "review_record_saved": record_loaded,
        "accepted_items_present": accepted_total > 0,
        "asset_candidate_created": asset_loaded,
        "asset_validation_passed": validation.get("validation_status") == "passed_manual_asset_checks",
        "graph_draft_created": graph_loaded,
        "graph_draft_ready": graph.get("graph_draft_status") == "ready_for_manual_pathgraph_review",
        "accepted_items_exported_to_graph": accepted_items_exported_to_graph,
        "no_execute_binding": all(
            item.get("execute_binding_enabled") is False
            for item in (package, record, asset, graph)
            if isinstance(item, dict) and item.get("load_status") != "missing_graph_draft"
        ),
        "no_authorization_artifact": all(
            item.get("artifact_is_authorization") is False
            for item in (package, record, asset, graph)
            if isinstance(item, dict) and item.get("load_status") != "missing_graph_draft"
        ),
    }
    blockers = [key for key, passed in checks.items() if not passed]
    blocker_details = [_promotion_preflight_blocker_detail(key) for key in blockers]
    status = "ready_for_audited_runtime_promotion_review" if not blockers else "blocked_before_runtime_promotion_review"
    out_path = package_resolved.parent / "assisted_template_promotion_preflight.json"
    payload = {
        "contract_version": "assisted_template_promotion_preflight_v1",
        "preflight_status": status,
        "created_at": datetime.now().isoformat(),
        "package_path": _relative_path(package_resolved, root),
        "package_sha256": hashlib.sha256(package_resolved.read_bytes()).hexdigest(),
        "review_record_path": record.get("path") or "",
        "asset_candidate_path": asset.get("path") or "",
        "graph_draft_path": graph.get("path") or "",
        "counts": {
            "accepted_review_items": accepted_total,
            "exported_asset_items": exported_total,
            "graph_draft_items": graph_total,
        },
        "checks": checks,
        "blockers": blockers,
        "blocker_details": blocker_details,
        "audit_required_before_runtime_promotion": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "ready_for_runtime_pathgraph_promotion": False,
        "final_submit_forbidden": True,
        "authorization_scope": "manual_preflight_only",
        "interpretation": (
            "manual promotion preflight only; this does not promote Runtime PathGraph, "
            "enable Execute, dispatch clicks, fill forms, or submit"
        ),
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "contract_version": "assisted_template_promotion_preflight_create_v1",
        "preflight_path": _relative_path(out_path, root),
        "preflight_status": status,
        "counts": payload["counts"],
        "checks": checks,
        "blockers": blockers,
        "blocker_details": blocker_details,
        "audit_required_before_runtime_promotion": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "ready_for_runtime_pathgraph_promotion": False,
        "final_submit_forbidden": True,
    }


def _promotion_preflight_blocker_detail(check_id: str) -> dict[str, Any]:
    catalog = {
        "review_record_saved": (
            "Review decisions have not been saved.",
            "Save checklist decisions before creating promotion preflight.",
        ),
        "accepted_items_present": (
            "No checklist items are accepted yet.",
            "Accept at least one coherent state/region/action/transition set, then rebuild the asset candidate.",
        ),
        "asset_candidate_created": (
            "No assisted-template asset candidate exists.",
            "Create the asset candidate from saved accepted checklist items.",
        ),
        "asset_validation_passed": (
            "The asset candidate failed manual asset validation.",
            "Fix accepted item linkage, final-submit safety, action semantics, and target regions, then rebuild.",
        ),
        "graph_draft_created": (
            "No read-only graph draft exists.",
            "Create a graph draft preview from the asset candidate.",
        ),
        "graph_draft_ready": (
            "The graph draft is not ready for manual PathGraph review.",
            "Resolve asset validation blockers, then rebuild the graph draft preview.",
        ),
        "accepted_items_exported_to_graph": (
            "Accepted review items were not fully reflected in the asset candidate and graph draft.",
            "Regenerate the asset candidate and graph draft after saving review decisions.",
        ),
        "no_execute_binding": (
            "One review artifact unexpectedly enables Execute binding.",
            "Inspect the artifact and remove it from the promotion path before continuing.",
        ),
        "no_authorization_artifact": (
            "One review artifact is incorrectly marked as authorization.",
            "Inspect the artifact and keep it review-only before continuing.",
        ),
    }
    reason, recommended_action = catalog.get(
        check_id,
        ("Unknown preflight check failed.", "Inspect the preflight artifact and repair the failed check."),
    )
    return {
        "check_id": check_id,
        "severity": "blocking",
        "reason": reason,
        "recommended_action": recommended_action,
        "runtime_promotion_allowed": False,
    }


def create_assisted_template_audited_promotion_request(
    package_path: str | Path,
    *,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """把 ready preflight 打包成外部审计请求预览；仍不执行 promotion。"""
    root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
    package = load_assisted_template_review_package(package_path, project_root=root)
    package_resolved = _resolve_under_root(package_path, root)
    preflight = package.get("promotion_preflight") if isinstance(package.get("promotion_preflight"), dict) else {}
    if preflight.get("load_status") != "loaded":
        raise FileNotFoundError(str(package_resolved.parent / "assisted_template_promotion_preflight.json"))
    if preflight.get("preflight_status") != "ready_for_audited_runtime_promotion_review":
        raise ValueError(f"preflight is not ready: {preflight.get('preflight_status')}")
    asset = package.get("asset_candidate") if isinstance(package.get("asset_candidate"), dict) else {}
    graph = package.get("graph_draft") if isinstance(package.get("graph_draft"), dict) else {}
    out_path = package_resolved.parent / "assisted_template_audited_promotion_request.json"
    payload = {
        "contract_version": "assisted_template_audited_promotion_request_v1",
        "request_status": "ready_for_external_audited_promotion_design",
        "created_at": datetime.now().isoformat(),
        "package_path": _relative_path(package_resolved, root),
        "package_sha256": hashlib.sha256(package_resolved.read_bytes()).hexdigest(),
        "preflight_path": preflight.get("path") or "",
        "preflight_sha256": preflight.get("sha256") or "",
        "asset_candidate_path": asset.get("path") or "",
        "asset_candidate_sha256": asset.get("sha256") or "",
        "graph_draft_path": graph.get("path") or "",
        "graph_draft_sha256": graph.get("sha256") or "",
        "required_external_audit_items": [
            "operator_confirms_review_record",
            "operator_confirms_asset_validation",
            "operator_confirms_graph_draft_shape",
            "operator_confirms_gate_contracts",
            "operator_confirms_no_final_submit_actions",
            "operator_confirms_runtime_promotion_scope",
        ],
        "requires_separate_audited_promotion_path": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "ready_for_runtime_pathgraph_promotion": False,
        "final_submit_forbidden": True,
        "authorization_scope": "audit_request_preview_only",
        "interpretation": (
            "audited promotion request preview only; a separate Runtime promotion implementation "
            "and explicit user approval are still required"
        ),
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "contract_version": "assisted_template_audited_promotion_request_create_v1",
        "request_path": _relative_path(out_path, root),
        "request_status": payload["request_status"],
        "required_external_audit_items": payload["required_external_audit_items"],
        "requires_separate_audited_promotion_path": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "ready_for_runtime_pathgraph_promotion": False,
        "final_submit_forbidden": True,
    }


def _review_decision(value: str) -> str:
    decision = str(value or "prepare_for_review").strip()
    allowed = {"prepare_for_review", "needs_changes", "approved_for_assisted_template_asset"}
    return decision if decision in allowed else "prepare_for_review"


def _review_record_decision(value: str) -> str:
    decision = str(value or "needs_changes").strip()
    allowed = {"needs_changes", "accepted_for_assisted_template_review", "rejected"}
    return decision if decision in allowed else "needs_changes"


def _item_decision(value: str) -> str:
    decision = str(value or "pending_review").strip()
    allowed = {"pending_review", "accepted", "needs_changes", "rejected"}
    return decision if decision in allowed else "pending_review"


def _decision_summary(decisions: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"accepted": 0, "needs_changes": 0, "rejected": 0, "pending_review": 0}
    for item in decisions:
        decision = _item_decision(str(item.get("decision") or ""))
        summary[decision] = summary.get(decision, 0) + 1
    summary["total"] = len(decisions)
    return summary


def _safe_item_overrides(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    allowed = {"label", "semantic_action", "target_entity"}
    overrides: dict[str, str] = {}
    for key in sorted(allowed):
        text = str(value.get(key) or "").strip()
        if text:
            overrides[key] = text
    return overrides


def _dedupe_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    deduped: list[dict[str, str]] = []
    for item in items:
        item_type = str(item.get("item_type") or "").strip()
        item_id = str(item.get("item_id") or "").strip()
        if not item_type or not item_id:
            continue
        key = (item_type, item_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append({"item_type": item_type, "item_id": item_id})
    return deduped


def _checklist_items(*, graph: dict[str, Any], interface_map: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in _list_of_dicts(graph.get("states")):
        item_id = str(item.get("state_id") or "")
        if item_id:
            items.append(_checklist_item("state", item_id, item.get("label") or item_id, item))
    for item in _list_of_dicts(interface_map.get("regions")):
        item_id = str(item.get("region_id") or "")
        if item_id:
            items.append(_checklist_item("region", item_id, item.get("label") or item_id, item))
    for item in _list_of_dicts(graph.get("action_templates")):
        item_id = str(item.get("action_template_id") or item.get("action_id") or "")
        if item_id:
            items.append(_checklist_item("action", item_id, item.get("label") or item_id, item))
    for item in _list_of_dicts(graph.get("transitions")):
        item_id = str(item.get("transition_id") or "")
        if item_id:
            label = item.get("label") or item.get("transition_type") or item_id
            items.append(_checklist_item("transition", item_id, label, item))
    return items


def _checklist_item(item_type: str, item_id: str, label: Any, source: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_type": item_type,
        "item_id": item_id,
        "label": str(label or item_id),
        "state_id": source.get("state_id") or source.get("from_state_id") or "",
        "target_entity": source.get("target_entity") or source.get("target_region_id") or "",
        "semantic_action": source.get("semantic_action") or source.get("action_kind") or source.get("transition_type") or "",
        "bbox": source.get("bbox") if isinstance(source.get("bbox"), dict) else {},
        "requires_human_review": source.get("requires_human_review") is not False,
        "default_decision": "pending_review",
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _accepted_payload(
    *,
    accepted_keys: set[tuple[str, str]],
    accepted_notes: dict[tuple[str, str], str],
    accepted_overrides: dict[tuple[str, str], dict[str, str]],
    graph: dict[str, Any],
    interface_map: dict[str, Any],
) -> dict[str, list[dict[str, Any]]]:
    return {
        "states": [
            _non_authorizing_copy(
                item,
                review_note=accepted_notes.get(("state", str(item.get("state_id") or "")), ""),
                overrides=accepted_overrides.get(("state", str(item.get("state_id") or "")), {}),
            )
            for item in _list_of_dicts(graph.get("states"))
            if ("state", str(item.get("state_id") or "")) in accepted_keys
        ],
        "regions": [
            _non_authorizing_copy(
                item,
                review_note=accepted_notes.get(("region", str(item.get("region_id") or "")), ""),
                overrides=accepted_overrides.get(("region", str(item.get("region_id") or "")), {}),
            )
            for item in _list_of_dicts(interface_map.get("regions"))
            if ("region", str(item.get("region_id") or "")) in accepted_keys
        ],
        "action_templates": [
            _non_authorizing_copy(
                item,
                review_note=accepted_notes.get(
                    ("action", str(item.get("action_template_id") or item.get("action_id") or "")),
                    "",
                ),
                overrides=accepted_overrides.get(
                    ("action", str(item.get("action_template_id") or item.get("action_id") or "")),
                    {},
                ),
            )
            for item in _list_of_dicts(graph.get("action_templates"))
            if ("action", str(item.get("action_template_id") or item.get("action_id") or "")) in accepted_keys
        ],
        "transitions": [
            _non_authorizing_copy(
                item,
                review_note=accepted_notes.get(("transition", str(item.get("transition_id") or "")), ""),
                overrides=accepted_overrides.get(("transition", str(item.get("transition_id") or "")), {}),
            )
            for item in _list_of_dicts(graph.get("transitions"))
            if ("transition", str(item.get("transition_id") or "")) in accepted_keys
        ],
    }


def _asset_validation_summary(accepted: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    states = _list_of_dicts(accepted.get("states"))
    regions = _list_of_dicts(accepted.get("regions"))
    actions = _list_of_dicts(accepted.get("action_templates"))
    transitions = _list_of_dicts(accepted.get("transitions"))
    state_ids = {str(item.get("state_id") or "") for item in states if item.get("state_id")}
    region_ids = {str(item.get("region_id") or "") for item in regions if item.get("region_id")}
    action_ids = {
        str(item.get("action_template_id") or item.get("action_id") or "")
        for item in actions
        if item.get("action_template_id") or item.get("action_id")
    }
    issues: list[dict[str, Any]] = []

    for item in actions:
        action_id = str(item.get("action_template_id") or item.get("action_id") or "")
        semantic_action = str(item.get("semantic_action") or item.get("action_kind") or "").strip()
        label = str(item.get("label") or "")
        target = str(item.get("target_entity") or item.get("target_region_id") or "").strip()
        if not semantic_action:
            issues.append(_asset_issue("error", "action_missing_semantic_action", "action", action_id))
        if _looks_like_final_submit(semantic_action, label):
            issues.append(_asset_issue("error", "final_submit_action_forbidden", "action", action_id))
        if not target:
            issues.append(_asset_issue("error", "action_missing_target_entity", "action", action_id))
        elif target not in region_ids:
            issues.append(
                _asset_issue(
                    "error",
                    "action_target_region_not_accepted",
                    "action",
                    action_id,
                    details={"target_entity": target},
                )
            )

    for item in transitions:
        transition_id = str(item.get("transition_id") or "")
        action_id = str(item.get("action_template_id") or "").strip()
        from_state = str(item.get("from_state_id") or "").strip()
        to_state = str(item.get("to_state_id") or "").strip()
        if not action_id:
            issues.append(_asset_issue("error", "transition_missing_action_template_id", "transition", transition_id))
        elif action_id not in action_ids:
            issues.append(
                _asset_issue(
                    "error",
                    "transition_action_not_accepted",
                    "transition",
                    transition_id,
                    details={"action_template_id": action_id},
                )
            )
        for state_role, state_id in (("from_state_id", from_state), ("to_state_id", to_state)):
            if state_id and state_id not in state_ids:
                issues.append(
                    _asset_issue(
                        "error",
                        "transition_state_not_accepted",
                        "transition",
                        transition_id,
                        details={state_role: state_id},
                    )
                )

    accepted_total = len(states) + len(regions) + len(actions) + len(transitions)
    error_count = sum(1 for issue in issues if issue.get("severity") == "error")
    warning_count = sum(1 for issue in issues if issue.get("severity") == "warning")
    if accepted_total == 0:
        status = "no_accepted_items"
    elif error_count:
        status = "needs_manual_fix"
    else:
        status = "passed_manual_asset_checks"
    return {
        "contract_version": "assisted_template_asset_validation_summary_v1",
        "validation_status": status,
        "error_count": error_count,
        "warning_count": warning_count,
        "issues": issues,
        "checks": {
            "accepted_state_count": len(states),
            "accepted_region_count": len(regions),
            "accepted_action_template_count": len(actions),
            "accepted_transition_count": len(transitions),
        },
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "ready_for_runtime_pathgraph_promotion": False,
    }


def _asset_issue(
    severity: str,
    check_id: str,
    item_type: str,
    item_id: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "check_id": check_id,
        "item_type": item_type,
        "item_id": item_id,
        "details": details or {},
    }


def _looks_like_final_submit(semantic_action: str, label: str) -> bool:
    text = f"{semantic_action} {label}".lower()
    forbidden = ("final_submit", "submit_application", "send_application", "complete_application", "payment")
    return any(token in text for token in forbidden)


def _non_authorizing_copy(
    item: dict[str, Any],
    *,
    review_note: str = "",
    overrides: dict[str, str] | None = None,
) -> dict[str, Any]:
    copied = dict(item)
    copied["human_review_note"] = str(review_note or "")
    safe_overrides = _safe_item_overrides(overrides)
    for key, value in safe_overrides.items():
        copied[key] = value
    copied["human_review_overrides"] = safe_overrides
    copied["artifact_is_authorization"] = False
    copied["execute_binding_enabled"] = False
    copied["ready_for_runtime_pathgraph_promotion"] = False
    copied["final_submit_forbidden"] = True
    return copied


def _optional_non_authorizing_artifact(
    path: Path,
    *,
    root: Path,
    contract_version: str,
    missing_status: str,
) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {"load_status": missing_status, "path": _relative_path(path, root)}
    payload = _read_json(path)
    if payload.get("contract_version") != contract_version:
        raise ValueError(f"{path.name} must point to {contract_version}")
    if payload.get("execute_binding_enabled") is not False or payload.get("artifact_is_authorization") is not False:
        raise ValueError(f"{path.name} must remain non-authorizing")
    payload = dict(payload)
    payload["load_status"] = "loaded"
    payload["path"] = _relative_path(path, root)
    payload["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    return payload


def _resolve_under_root(path_value: Any, root: Path) -> Path:
    path_text = str(path_value or "").strip()
    if not path_text:
        raise ValueError("path is required")
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    allowed_roots = [(root / "artifacts").resolve(), (root / "logs").resolve()]
    if not any(path == allowed or allowed in path.parents for allowed in allowed_roots):
        raise ValueError("assisted template review source must be under artifacts or logs")
    if not path.exists() or not path.is_file():
        raise FileNotFoundError(str(path))
    return path


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []
