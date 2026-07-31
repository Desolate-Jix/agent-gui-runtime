from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

from app.learn.agent_evidence import build_workflow_agent_evidence
from app.learn.application_identity import normalize_application_identity


INTERFACE_WORKFLOW_REVIEW_CONTRACT = "single_application_workflow_review_v1"
ALLOWED_REVIEW_ACTION_TYPES = {
    "back",
    "close_modal",
    "continue_next_step",
    "fill_field",
    "open_apply_flow",
    "open_detail",
    "open_modal",
    "read",
    "scroll",
    "select_option",
    "unknown_action",
    "wait",
}
FORBIDDEN_REVIEW_ACTION_TYPES = {
    "confirm",
    "delete",
    "final_submit",
    "payment",
    "send",
    "submit",
}
_RUNTIME_POINT_KEYS = {
    "actual_point",
    "click_point",
    "expected_point",
    "screen_point",
    "target_point",
}


def build_interface_workflow_review(
    *,
    goal: str,
    application_identity: dict[str, Any],
    draft_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    """把已有学习草稿投影为只读的单软件界面流程审核图。"""

    normalized_goal = str(goal or "").strip()
    normalized_application = normalize_application_identity(
        _without_runtime_click_coordinates(
            application_identity if isinstance(application_identity, dict) else {}
        )
    )
    sources = draft_sources if isinstance(draft_sources, list) else []
    nodes_by_signature: OrderedDict[str, dict[str, Any]] = OrderedDict()
    observed_node_ids: list[str] = []
    invalid_sources: list[dict[str, Any]] = []

    for source_index, review in enumerate(sources):
        if not isinstance(review, dict):
            invalid_sources.append(
                {
                    "source_index": source_index,
                    "failure_category": "invalid_review_source",
                    "reason": "review source must be an object",
                }
            )
            continue
        draft = review.get("draft")
        if not isinstance(draft, dict):
            invalid_sources.append(
                {
                    "source_index": source_index,
                    "source_path": _source_path(review),
                    "failure_category": "learning_draft_missing",
                    "reason": "review source does not contain a draft object",
                }
            )
            continue

        signature = _state_signature(review, draft, source_index)
        node_id = f"interface_{_stable_hash(signature)[:12]}"
        source_path = _source_path(review)
        if signature in nodes_by_signature:
            node = nodes_by_signature[signature]
            node["observation_count"] += 1
            if source_path and source_path not in node["source_paths"]:
                node["source_paths"].append(source_path)
            if node["evidence_status"] != "ready":
                replacement = _node_evidence(review, draft)
                if replacement["evidence_status"] == "ready":
                    node["evidence"] = replacement["evidence"]
                    node["evidence_status"] = "ready"
            observed_node_ids.append(node_id)
            continue

        evidence_result = _node_evidence(review, draft)
        node = {
            "node_id": node_id,
            "display_name": _display_name(draft, source_index),
            "surface_type": str(
                draft.get("surface_type")
                or draft.get("state_guess")
                or "unknown_surface"
            ).strip(),
            "state_signature": signature,
            "source_paths": [source_path] if source_path else [],
            "observation_count": 1,
            "evidence": evidence_result["evidence"],
            "evidence_status": evidence_result["evidence_status"],
            "page_details": _without_runtime_click_coordinates(
                draft.get("page_details") if isinstance(draft.get("page_details"), dict) else {}
            ),
            "ui_hierarchy": _without_runtime_click_coordinates(
                draft.get("ui_hierarchy") if isinstance(draft.get("ui_hierarchy"), dict) else {}
            ),
            "states": _clean_list(draft.get("states")),
            "regions": _clean_list(draft.get("regions")),
            "controls": _clean_list(
                draft.get("controls")
                or draft.get("components")
                or draft.get("screen_inventory")
            ),
            "action_candidates": _clean_list(draft.get("action_templates")),
            "blockers": _clean_list(draft.get("blockers")),
            "verification_rules": _clean_list(draft.get("verification_rules")),
            "review_status": str(
                review.get("review_status") or "needs_human_review"
            ).strip(),
            "execution_verification_status": "not_verified",
            "manual_revision": {},
            "display_only": True,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
        nodes_by_signature[signature] = node
        observed_node_ids.append(node_id)

    path_node_ids = _deduplicated_path(observed_node_ids)
    edges = [
        _transition_edge(path_node_ids[index], path_node_ids[index + 1], index)
        for index in range(len(path_node_ids) - 1)
    ]
    nodes = list(nodes_by_signature.values())
    workflow_id = f"workflow_{_stable_hash({'goal': normalized_goal, 'application': normalized_application, 'nodes': path_node_ids})[:12]}"
    return {
        "contract_version": INTERFACE_WORKFLOW_REVIEW_CONTRACT,
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "workflow": {
            "workflow_id": workflow_id,
            "goal": normalized_goal,
            "application_identity": normalized_application,
            "entry_node_id": path_node_ids[0] if path_node_ids else "",
            "node_ids": [node["node_id"] for node in nodes],
            "edge_ids": [edge["edge_id"] for edge in edges],
            "review_status": "needs_human_review" if nodes else "not_covered",
            "published_memory_version": None,
        },
        "nodes": nodes,
        "edges": edges,
        "invalid_sources": invalid_sources,
        "safety": {
            "review_draft_only": True,
            "runtime_requires_fresh_capture": True,
            "runtime_requires_fresh_grounding": True,
            "runtime_requires_gate": True,
            "final_submit_forbidden": True,
            "send_delete_confirm_payment_forbidden": True,
        },
    }


def save_interface_workflow_review_candidate(
    review: dict[str, Any],
    *,
    project_root: Path,
    out_dir: str | Path | None = None,
) -> dict[str, Any]:
    """保存人工审核后的流程草稿，但不授予发布或执行权限。"""

    if not isinstance(review, dict):
        raise ValueError("workflow review must be an object")
    if review.get("contract_version") != INTERFACE_WORKFLOW_REVIEW_CONTRACT:
        raise ValueError(
            f"workflow review contract must be {INTERFACE_WORKFLOW_REVIEW_CONTRACT}"
        )

    sanitized = _without_runtime_click_coordinates(review)
    sanitized["display_only"] = True
    sanitized["artifact_is_authorization"] = False
    sanitized["execute_binding_enabled"] = False

    workflow = sanitized.get("workflow")
    if not isinstance(workflow, dict):
        raise ValueError("workflow review must contain a workflow object")
    workflow_id = str(workflow.get("workflow_id") or "").strip()
    if not workflow_id:
        raise ValueError("workflow review must contain workflow.workflow_id")
    workflow["published_memory_version"] = None
    workflow["review_status"] = str(
        workflow.get("review_status") or "needs_human_review"
    ).strip()

    nodes = sanitized.get("nodes")
    edges = sanitized.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("workflow review nodes and edges must be arrays")
    for item in [*nodes, *edges]:
        if not isinstance(item, dict):
            raise ValueError("workflow review nodes and edges must contain objects")
        item["display_only"] = True
        item["artifact_is_authorization"] = False
        item["execute_binding_enabled"] = False
    _validate_workflow_structure(workflow=workflow, nodes=nodes, edges=edges)

    safety = sanitized.get("safety")
    if not isinstance(safety, dict):
        safety = {}
        sanitized["safety"] = safety
    safety.update(
        {
            "review_draft_only": True,
            "runtime_requires_fresh_capture": True,
            "runtime_requires_fresh_grounding": True,
            "runtime_requires_gate": True,
            "final_submit_forbidden": True,
            "send_delete_confirm_payment_forbidden": True,
        }
    )

    root = Path(project_root).resolve()
    destination_root = (
        _resolve_review_output_dir(root, out_dir)
        if out_dir is not None
        else root / "artifacts" / "interface-workflow-reviews"
    )
    safe_workflow_id = "".join(
        character if character.isalnum() or character in "_.-" else "_"
        for character in workflow_id
    ).strip("._")
    if not safe_workflow_id:
        raise ValueError("workflow.workflow_id does not contain a safe file name")
    application_identity = normalize_application_identity(
        workflow.get("application_identity")
        if isinstance(workflow.get("application_identity"), dict)
        else {}
    )
    workflow["application_identity"] = application_identity
    destination = destination_root / safe_workflow_id / "reviewed_workflow.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(sanitized, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    identity_key = application_identity.get("identity_key")
    library_index_status = "identity_unresolved"
    if identity_key:
        _index_workflow_review(
            registry_path=destination_root / "registry.json",
            identity=application_identity,
            workflow=workflow,
            destination=destination,
            node_count=len(nodes),
            edge_count=len(edges),
        )
        library_index_status = "indexed"
    return {
        "path": str(destination.resolve()),
        "workflow_id": workflow_id,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "review_status": workflow["review_status"],
        "published": False,
        "application_identity_key": identity_key,
        "identity_status": application_identity["identity_status"],
        "library_index_status": library_index_status,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _index_workflow_review(
    *,
    registry_path: Path,
    identity: dict[str, Any],
    workflow: dict[str, Any],
    destination: Path,
    node_count: int,
    edge_count: int,
) -> None:
    registry = {
        "contract_version": "interface_workflow_library_registry_v1",
        "registry_revision": 0,
        "applications": {},
        "workflows": {},
        "artifact_is_authorization": False,
    }
    if registry_path.exists():
        loaded = json.loads(registry_path.read_text(encoding="utf-8-sig"))
        if not isinstance(loaded, dict):
            raise ValueError("interface workflow library registry must be an object")
        registry.update(loaded)

    identity_key = str(identity["identity_key"])
    workflow_id = str(workflow["workflow_id"])
    applications = registry.setdefault("applications", {})
    workflows = registry.setdefault("workflows", {})
    application = applications.setdefault(
        identity_key,
        {
            "application_identity": deepcopy(identity),
            "workflow_ids": [],
            "artifact_is_authorization": False,
        },
    )
    workflow_ids = application.setdefault("workflow_ids", [])
    if workflow_id not in workflow_ids:
        workflow_ids.append(workflow_id)
    workflows[workflow_id] = {
        "path": str(destination.resolve()),
        "application_identity_key": identity_key,
        "goal": str(workflow.get("goal") or ""),
        "node_count": node_count,
        "edge_count": edge_count,
        "review_status": str(workflow.get("review_status") or "needs_human_review"),
        "published": False,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    registry["registry_revision"] = int(registry.get("registry_revision") or 0) + 1
    registry["artifact_is_authorization"] = False
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = registry_path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(registry_path)


def load_interface_workflow_library_registry(
    *,
    project_root: Path,
) -> dict[str, Any]:
    """加载按软件或网站归档的审核流程索引。"""

    root = Path(project_root).resolve()
    registry_path = root / "artifacts" / "interface-workflow-reviews" / "registry.json"
    if not registry_path.exists():
        return {
            "contract_version": "interface_workflow_library_registry_v1",
            "registry_revision": 0,
            "applications": {},
            "workflows": {},
            "artifact_is_authorization": False,
        }
    registry = json.loads(registry_path.read_text(encoding="utf-8-sig"))
    if (
        not isinstance(registry, dict)
        or registry.get("contract_version") != "interface_workflow_library_registry_v1"
    ):
        raise ValueError("interface workflow library registry has an invalid contract")
    registry["artifact_is_authorization"] = False
    return registry


def load_interface_workflow_agent_context(
    *,
    project_root: Path,
    application_identity_key: str,
) -> dict[str, Any]:
    """向 Agent 提供人工审核流程；运行时仍必须重新定位并经过 Gate。"""

    root = Path(project_root).resolve()
    identity_key = str(application_identity_key or "").strip()
    if not identity_key:
        raise ValueError("application identity key is required")
    registry = load_interface_workflow_library_registry(project_root=root)
    application = registry.get("applications", {}).get(identity_key)
    if not isinstance(application, dict):
        raise ValueError(f"interface workflow application identity not found: {identity_key}")

    workflows: list[dict[str, Any]] = []
    for workflow_id in application.get("workflow_ids", []):
        record = registry.get("workflows", {}).get(workflow_id)
        if not isinstance(record, dict):
            continue
        path = Path(str(record.get("path") or ""))
        resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
        if root not in resolved.parents:
            raise ValueError("interface workflow path escapes project root")
        payload = json.loads(resolved.read_text(encoding="utf-8-sig"))
        if payload.get("contract_version") != INTERFACE_WORKFLOW_REVIEW_CONTRACT:
            raise ValueError("reviewed interface workflow has an invalid contract")
        workflows.append(_without_runtime_click_coordinates(payload))

    return {
        "contract_version": "interface_workflow_agent_context_v1",
        "application_identity_key": identity_key,
        "application_identity": deepcopy(application.get("application_identity") or {}),
        "workflow_count": len(workflows),
        "workflows": workflows,
        "agent_evidence_workflows": [
            build_workflow_agent_evidence(workflow)
            for workflow in workflows
        ],
        "execution_contract": {
            "historical_coordinates_forbidden": True,
            "current_capture_required": True,
            "fresh_grounding_required": True,
            "gate_required": True,
            "post_action_verification_required": True,
        },
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _validate_workflow_structure(
    *,
    workflow: dict[str, Any],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> None:
    node_ids = [str(node.get("node_id") or "").strip() for node in nodes]
    if any(not node_id for node_id in node_ids):
        raise ValueError("workflow review nodes must contain node_id")
    if len(node_ids) != len(set(node_ids)):
        raise ValueError("workflow review contains duplicate node_id")
    known_node_ids = set(node_ids)

    declared_node_ids = workflow.get("node_ids")
    if not isinstance(declared_node_ids, list):
        raise ValueError("workflow.node_ids must be an array")
    normalized_declared_node_ids = [
        str(node_id or "").strip() for node_id in declared_node_ids
    ]
    if normalized_declared_node_ids != node_ids:
        raise ValueError("workflow.node_ids must match nodes in display order")

    entry_node_id = str(workflow.get("entry_node_id") or "").strip()
    if node_ids and entry_node_id not in known_node_ids:
        raise ValueError("workflow.entry_node_id must reference a workflow node")
    if not node_ids and entry_node_id:
        raise ValueError("workflow.entry_node_id must be empty when nodes are empty")

    edge_ids = [str(edge.get("edge_id") or "").strip() for edge in edges]
    if any(not edge_id for edge_id in edge_ids):
        raise ValueError("workflow review edges must contain edge_id")
    if len(edge_ids) != len(set(edge_ids)):
        raise ValueError("workflow review contains duplicate edge_id")
    declared_edge_ids = workflow.get("edge_ids")
    if not isinstance(declared_edge_ids, list):
        raise ValueError("workflow.edge_ids must be an array")
    normalized_declared_edge_ids = [
        str(edge_id or "").strip() for edge_id in declared_edge_ids
    ]
    if normalized_declared_edge_ids != edge_ids:
        raise ValueError("workflow.edge_ids must match edges in display order")

    for edge in edges:
        source_node_id = str(edge.get("source_node_id") or "").strip()
        target_node_id = str(edge.get("target_node_id") or "").strip()
        if source_node_id not in known_node_ids:
            raise ValueError(
                f"workflow edge references unknown source node: {source_node_id}"
            )
        if target_node_id not in known_node_ids:
            raise ValueError(
                f"workflow edge references unknown target node: {target_node_id}"
            )
        _validate_review_operation(edge)


def _validate_review_operation(edge: dict[str, Any]) -> None:
    action_type = str(edge.get("action_type") or "unknown_action").strip().lower()
    if action_type in FORBIDDEN_REVIEW_ACTION_TYPES:
        raise ValueError(f"forbidden review action type: {action_type}")
    if action_type not in ALLOWED_REVIEW_ACTION_TYPES:
        raise ValueError(f"unsupported review action type: {action_type}")

    risk_level = str(edge.get("risk_level") or "low").strip().lower()
    if risk_level not in {"low", "medium", "high"}:
        raise ValueError("workflow edge risk_level must be low, medium, or high")

    edge["action_type"] = action_type
    edge["operation_id"] = str(
        edge.get("operation_id") or edge.get("edge_id") or ""
    ).strip()
    edge["target_control_id"] = str(edge.get("target_control_id") or "").strip()
    edge["target_region_id"] = str(edge.get("target_region_id") or "").strip()
    edge["risk_level"] = risk_level
    edge["requires_user_confirmation"] = bool(
        edge.get("requires_user_confirmation") or risk_level == "high"
    )
    for field_name in (
        "preconditions",
        "success_conditions",
        "failure_conditions",
    ):
        values = edge.get(field_name)
        if not isinstance(values, list):
            raise ValueError(f"workflow edge {field_name} must be an array")
        edge[field_name] = [
            str(value).strip()
            for value in values
            if str(value).strip()
        ]


def _resolve_review_output_dir(project_root: Path, out_dir: str | Path) -> Path:
    candidate = Path(out_dir)
    resolved = (
        candidate.resolve()
        if candidate.is_absolute()
        else (project_root / candidate).resolve()
    )
    try:
        resolved.relative_to(project_root)
    except ValueError as exc:
        raise ValueError("workflow review output directory must stay inside project root") from exc
    return resolved


def _node_evidence(review: dict[str, Any], draft: dict[str, Any]) -> dict[str, Any]:
    page_details = draft.get("page_details") if isinstance(draft.get("page_details"), dict) else {}
    screen = page_details.get("screen") if isinstance(page_details.get("screen"), dict) else {}
    preview = (
        review.get("screen_understanding_preview")
        if isinstance(review.get("screen_understanding_preview"), dict)
        else {}
    )
    fusion = (
        page_details.get("precise_understanding_fusion_status")
        if isinstance(page_details.get("precise_understanding_fusion_status"), dict)
        else {}
    )
    source_screenshot_path = _first_text(
        draft.get("source_image_path"),
        draft.get("screenshot_path"),
        screen.get("image_path"),
        page_details.get("screenshot_path"),
        preview.get("source_image_path"),
        preview.get("screenshot_path"),
    )
    numbered_overlay_path = _first_text(
        draft.get("numbered_map_path"),
        page_details.get("full_screen_understanding_overlay_path"),
        screen.get("full_screen_understanding_overlay_path"),
        preview.get("numbered_map_path"),
        preview.get("overlay_path"),
    )
    fused_overlay_path = _first_text(
        page_details.get("human_review_overlay_path"),
        page_details.get("compiled_overlay_path"),
        screen.get("compiled_overlay_path"),
        fusion.get("compiled_overlay_path"),
        numbered_overlay_path,
    )
    if not source_screenshot_path:
        evidence_status = "screenshot_missing"
    elif not numbered_overlay_path and not fused_overlay_path:
        evidence_status = "overlay_missing"
    else:
        evidence_status = "ready"
    return {
        "evidence_status": evidence_status,
        "evidence": {
            "source_screenshot_path": source_screenshot_path,
            "numbered_overlay_path": numbered_overlay_path,
            "fused_overlay_path": fused_overlay_path,
            "human_review_overlay_path": _first_text(
                page_details.get("human_review_overlay_path"),
                screen.get("human_review_overlay_path"),
            ),
            "source_path": _source_path(review),
            "source_sha256": str(
                (review.get("source") or {}).get("sha256")
                if isinstance(review.get("source"), dict)
                else ""
            ).strip(),
        },
    }


def _transition_edge(source_node_id: str, target_node_id: str, index: int) -> dict[str, Any]:
    edge_id = f"edge_{_stable_hash([source_node_id, target_node_id, index])[:12]}"
    return {
        "edge_id": edge_id,
        "operation_id": edge_id,
        "source_node_id": source_node_id,
        "target_node_id": target_node_id,
        "display_name": "Observed transition",
        "action_type": "unknown_action",
        "target_region_id": "",
        "target_control_id": "",
        "risk_level": "low",
        "requires_user_confirmation": False,
        "preconditions": [],
        "success_conditions": [],
        "failure_conditions": [],
        "gate_policy": "fresh_grounding_and_gate_required",
        "verification_evidence": {},
        "review_status": "needs_human_review",
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _state_signature(
    review: dict[str, Any],
    draft: dict[str, Any],
    source_index: int,
) -> str:
    page_details = draft.get("page_details") if isinstance(draft.get("page_details"), dict) else {}
    explicit = _first_text(
        draft.get("state_signature"),
        page_details.get("state_signature"),
        review.get("state_signature"),
    )
    if explicit:
        return explicit
    source = review.get("source") if isinstance(review.get("source"), dict) else {}
    return _first_text(
        source.get("sha256"),
        source.get("source_path"),
        f"source-{source_index}",
    )


def _display_name(draft: dict[str, Any], source_index: int) -> str:
    page_details = draft.get("page_details") if isinstance(draft.get("page_details"), dict) else {}
    screen = page_details.get("screen") if isinstance(page_details.get("screen"), dict) else {}
    return _first_text(
        draft.get("screen_summary"),
        screen.get("summary"),
        draft.get("state_guess"),
        f"Interface {source_index + 1}",
    )


def _source_path(review: dict[str, Any]) -> str:
    source = review.get("source") if isinstance(review.get("source"), dict) else {}
    return _first_text(
        source.get("source_path"),
        source.get("original_draft_path"),
        source.get("source_trial_path"),
    )


def _clean_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        _without_runtime_click_coordinates(item)
        for item in value
        if isinstance(item, dict)
    ]


def _without_runtime_click_coordinates(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _without_runtime_click_coordinates(item)
            for key, item in value.items()
            if str(key) not in _RUNTIME_POINT_KEYS
        }
    if isinstance(value, list):
        return [_without_runtime_click_coordinates(item) for item in value]
    return deepcopy(value)


def _deduplicated_path(node_ids: list[str]) -> list[str]:
    result: list[str] = []
    for node_id in node_ids:
        if result and result[-1] == node_id:
            continue
        result.append(node_id)
    return result


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
