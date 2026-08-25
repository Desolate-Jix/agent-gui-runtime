from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from app.learn.agent_evidence import (
    PersistedReviewRevision,
    build_workflow_agent_evidence,
)
from app.learn.application_identity import normalize_application_identity


INTERFACE_WORKFLOW_REVIEW_CONTRACT = "single_application_workflow_review_v1"
INTERFACE_NODE_HUMAN_REVIEW_CONFIRMATION_CONTRACT = (
    "interface_node_human_review_confirmation_v1"
)
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
    "clickpoint",
    "confirmed_point",
    "expected_point",
    "screen_point",
    "target_point",
}
_REVISION_METADATA_KEYS = {
    "agent_eligibility_reason",
    "agent_usable",
    "artifact_is_authorization",
    "current_revision_hash",
    "display_only",
    "editable_review_source_path",
    "execute_binding_enabled",
    "execution_verification_status",
    "human_review_confirmation",
    "review_bucket",
    "review_status",
    "reviewed_by_human",
    "reviewed_revision_hash",

    "source_paths",
    "source_screenshot_sha256",
    "review_revision_source_screenshot_path",
    "review_revision_numbered_overlay_path",
    "review_revision_fused_overlay_path",
    "review_revision_human_review_overlay_path",
}


def build_interface_node_review_revision(
    review: dict[str, Any],
    *,
    node_id: str,
) -> dict[str, Any]:
    """生成绑定人工审核事实的节点与出边内容快照。"""

    nodes = review.get("nodes") if isinstance(review, dict) else None
    edges = review.get("edges") if isinstance(review, dict) else None
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("workflow review nodes and edges must be arrays")
    normalized_node_id = str(node_id or "").strip()
    matches = [
        item
        for item in nodes
        if isinstance(item, dict)
        and str(item.get("node_id") or "").strip() == normalized_node_id
    ]
    if len(matches) != 1:
        raise ValueError(f"workflow review node must exist exactly once: {normalized_node_id}")

    node = _without_review_revision_metadata(matches[0])
    source_paths = matches[0].get("source_paths")
    if isinstance(source_paths, list):
        normalized_source_paths = [
            str(value or "").strip()
            for value in source_paths
            if str(value or "").strip()
            and "node-review-sources" not in str(value).replace("\\", "/")
        ]
        if normalized_source_paths:
            node["source_paths"] = normalized_source_paths
    raw_evidence = matches[0].get("evidence")
    if isinstance(raw_evidence, dict) and isinstance(node.get("evidence"), dict):
        for evidence_key in (
            "source_screenshot_path",
            "numbered_overlay_path",
            "fused_overlay_path",
            "human_review_overlay_path",
        ):
            current_path = str(raw_evidence.get(evidence_key) or "").strip()
            original_path = str(
                raw_evidence.get(f"review_revision_{evidence_key}") or ""
            ).strip()
            if (
                original_path
                and "node-evidence" in current_path.replace("\\", "/")
            ):
                node["evidence"][evidence_key] = original_path

    outgoing_edges = [
        _without_review_revision_metadata(item)
        for item in edges
        if isinstance(item, dict)
        and str(item.get("source_node_id") or "").strip() == normalized_node_id
    ]
    outgoing_edges.sort(key=lambda item: str(item.get("edge_id") or ""))
    return _without_runtime_click_coordinates(
        {
            "node": node,
            "outgoing_edges": outgoing_edges,
        }
    )


def _without_review_revision_metadata(value: Any) -> Any:
    """递归移除不属于界面语义修订的审核与投影元数据。"""

    if isinstance(value, list):
        return [_without_review_revision_metadata(item) for item in value]
    if not isinstance(value, dict):
        return deepcopy(value)
    return {
        str(key): _without_review_revision_metadata(item)
        for key, item in value.items()
        if str(key) not in _REVISION_METADATA_KEYS
    }


def _interface_node_review_revision_hash(revision: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            revision,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


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
        node_id = _preserved_node_id(review) or f"interface_{_stable_hash(signature)[:12]}"
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
            observed_node_ids.append(str(node["node_id"]))
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
            "agent_description": str(draft.get("agent_description") or "").strip(),
            "content_descriptors": _clean_list(draft.get("content_descriptors")),
            "page_details": _without_runtime_click_coordinates(
                draft.get("page_details") if isinstance(draft.get("page_details"), dict) else {}
            ),
            "ui_hierarchy": _without_runtime_click_coordinates(
                draft.get("ui_hierarchy") if isinstance(draft.get("ui_hierarchy"), dict) else {}
            ),
            "hierarchy_ownership_review": _hierarchy_ownership_review(draft),
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
            "reviewed_by_human": review.get("reviewed_by_human") is True,
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
    destination = destination_root / safe_workflow_id / "reviewed_workflow.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    # 先固化证据路径，再计算确认修订，确保服务器持久化后的规范修订一致。
    _materialize_durable_node_evidence(
        nodes,
        workflow_dir=destination.parent,
        project_root=root,
    )
    confirmed_node_revisions: dict[str, dict[str, Any]] = {}
    for node in nodes:
        status = str(node.get("review_status") or "needs_human_review").strip()
        node_id = str(node.get("node_id") or "").strip()
        confirmation = node.get("human_review_confirmation")
        current_revision = build_interface_node_review_revision(
            sanitized,
            node_id=node_id,
        )
        reviewed = (
            node.get("reviewed_by_human") is True
            and status.casefold() in _HUMAN_REVIEWED_INTERFACE_STATUSES
            and isinstance(confirmation, dict)
            and confirmation.get("contract_version")
            == INTERFACE_NODE_HUMAN_REVIEW_CONFIRMATION_CONTRACT
            and confirmation.get("revision") == current_revision
        )
        if reviewed:
            confirmed_node_revisions[node_id] = deepcopy(confirmation["revision"])
        node.pop("human_review_confirmation", None)
        node["reviewed_by_human"] = False
        node["reviewed_revision_hash"] = ""
        if not reviewed and status.casefold() in _HUMAN_REVIEWED_INTERFACE_STATUSES:
            node["review_status"] = "needs_human_review"
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

    application_identity = normalize_application_identity(
        workflow.get("application_identity")
        if isinstance(workflow.get("application_identity"), dict)
        else {}
    )
    workflow["application_identity"] = application_identity
    _materialize_editable_node_review_sources(
        nodes,
        workflow_id=workflow_id,
        workflow_dir=destination.parent,
        project_root=root,
    )
    for node in nodes:
        node_id = str(node.get("node_id") or "").strip()
        final_revision = build_interface_node_review_revision(
            sanitized,
            node_id=node_id,
        )
        revision_hash = _interface_node_review_revision_hash(final_revision)
        node["current_revision_hash"] = revision_hash
        if confirmed_node_revisions.get(node_id) == final_revision:
            node["review_status"] = "human_approved"
            node["reviewed_by_human"] = True
            node["reviewed_revision_hash"] = revision_hash
        elif str(node.get("review_status") or "").strip().casefold() in (
            _HUMAN_REVIEWED_INTERFACE_STATUSES
        ):
            node["review_status"] = "needs_human_review"
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
            reviewed_node_revision_hashes={
                str(node.get("node_id") or ""): str(
                    node.get("reviewed_revision_hash") or ""
                )
                for node in nodes
                if node.get("reviewed_by_human") is True
                and str(node.get("reviewed_revision_hash") or "").strip()
            },
            reviewed_node_evidence_sha256={
                str(node.get("node_id") or ""): _node_evidence_provenance(
                    node,
                    project_root=root,
                )
                for node in nodes
                if node.get("reviewed_by_human") is True
                and str(node.get("reviewed_revision_hash") or "").strip()
            },
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


def _materialize_durable_node_evidence(
    nodes: list[dict[str, Any]],
    *,
    workflow_dir: Path,
    project_root: Path,
) -> None:
    """把正式流程依赖的图片复制到流程目录，避免清理临时截图后证据失效。"""

    image_keys = (
        "source_screenshot_path",
        "numbered_overlay_path",
        "fused_overlay_path",
        "human_review_overlay_path",
    )
    evidence_root = workflow_dir / "node-evidence"
    for index, node in enumerate(nodes):
        evidence = node.get("evidence") if isinstance(node.get("evidence"), dict) else {}
        if not evidence:
            continue
        node_id = str(node.get("node_id") or f"interface_{index + 1}").strip()
        safe_node_id = "".join(
            character if character.isalnum() or character in "_.-" else "_"
            for character in node_id
        ).strip("._") or f"interface_{index + 1}"
        node_root = evidence_root / safe_node_id
        for key in image_keys:
            source_text = str(evidence.get(key) or "").strip()
            if not source_text:
                continue
            source = Path(source_text)
            source = source.resolve() if source.is_absolute() else (project_root / source).resolve()
            if not source.is_file():
                continue
            suffix = source.suffix.lower() or ".png"
            destination = node_root / f"{key}{suffix}"
            destination.parent.mkdir(parents=True, exist_ok=True)
            revision_key = f"review_revision_{key}"
            if not evidence.get(revision_key):
                evidence[revision_key] = source_text
            if source != destination.resolve():
                destination.write_bytes(source.read_bytes())
            evidence[key] = _project_path_reference(destination, project_root)
            if key == "source_screenshot_path":
                evidence["source_screenshot_sha256"] = hashlib.sha256(
                    destination.read_bytes()
                ).hexdigest()
        node["evidence"] = evidence


def _materialize_editable_node_review_sources(
    nodes: list[dict[str, Any]],
    *,
    workflow_id: str,
    workflow_dir: Path,
    project_root: Path,
) -> None:
    """为正式流程节点生成可由人工框编辑器加载的只读证据投影。"""

    source_dir = workflow_dir / "node-review-sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    for index, node in enumerate(nodes):
        node_id = str(node.get("node_id") or f"interface_{index + 1}").strip()
        safe_node_id = "".join(
            character if character.isalnum() or character in "_.-" else "_"
            for character in node_id
        ).strip("._") or f"interface_{index + 1}"
        source_path = source_dir / f"{safe_node_id}.json"
        source_ref = _project_path_reference(source_path, project_root)
        evidence = node.get("evidence") if isinstance(node.get("evidence"), dict) else {}
        page_details = deepcopy(node.get("page_details")) if isinstance(node.get("page_details"), dict) else {}
        screen = page_details.get("screen") if isinstance(page_details.get("screen"), dict) else {}
        screen.update(
            {
                "summary": str(node.get("display_name") or node_id),
                "source_image_path": _project_path_reference(
                    evidence.get("source_screenshot_path"),
                    project_root,
                ),
                "source_image_sha256": str(evidence.get("source_screenshot_sha256") or "").strip(),
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        )
        page_details["screen"] = screen
        payload = {
            "contract_version": "interface_workflow_node_review_source_v1",
            "workflow_id": workflow_id,
            "node_id": node_id,
            "draft": {
                "contract_version": "learning_template_draft_v1",
                "screen_summary": str(node.get("display_name") or node_id),
                "state_guess": str(node.get("surface_type") or "unknown_surface"),
                "state_signature": str(node.get("state_signature") or node_id),
                "states": deepcopy(node.get("states")) if isinstance(node.get("states"), list) else [],
                "regions": deepcopy(node.get("regions")) if isinstance(node.get("regions"), list) else [],
                "action_templates": _editable_action_templates(node),
                "blockers": deepcopy(node.get("blockers")) if isinstance(node.get("blockers"), list) else [],
                "verification_rules": (
                    deepcopy(node.get("verification_rules"))
                    if isinstance(node.get("verification_rules"), list)
                    else []
                ),
                "page_details": page_details,
                "learning_source": "reviewed_multi_interface_workflow",
                "safety": {
                    "artifact_is_authorization": False,
                    "execute_binding_enabled": False,
                    "final_submit_forbidden": True,
                },
            },
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
        source_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        node["editable_review_source_path"] = source_ref
        existing_paths = [
            str(value or "").strip()
            for value in (node.get("source_paths") if isinstance(node.get("source_paths"), list) else [])
            if str(value or "").strip() and str(value or "").strip() != source_ref
        ]
        has_authoritative_reviewed_source = any(
            _is_reviewed_candidate_source(value, project_root=project_root)
            for value in existing_paths
        )
        node["source_paths"] = (
            existing_paths
            if has_authoritative_reviewed_source
            else [source_ref, *existing_paths]
        )


def _is_reviewed_candidate_source(value: str, *, project_root: Path) -> bool:
    """仅把现存的 Task 8 reviewed candidate 识别为权威父来源。"""

    candidate = Path(value)
    resolved = (
        candidate.resolve()
        if candidate.is_absolute()
        else (project_root / candidate).resolve()
    )
    try:
        resolved.relative_to(project_root.resolve())
        payload = json.loads(resolved.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, dict)
        and payload.get("contract_version") == "reviewed_template_candidate_v1"
    )


def _editable_action_templates(node: dict[str, Any]) -> list[dict[str, Any]]:
    actions = node.get("action_candidates") if isinstance(node.get("action_candidates"), list) else []
    templates: list[dict[str, Any]] = []
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            continue
        action_id = str(
            action.get("action_template_id")
            or action.get("action_id")
            or f"action_{index + 1}"
        ).strip()
        templates.append(
            {
                **deepcopy(action),
                "action_template_id": action_id,
                "label": str(action.get("display_name") or action.get("label") or action_id),
                "semantic_action": str(
                    action.get("semantic_action")
                    or action.get("action_type")
                    or "read"
                ),
                "target_region_id": str(action.get("target_region_id") or "").strip(),
                "display_only": True,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        )
    return templates


def _project_path_reference(value: Any, project_root: Path) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    candidate = Path(text)
    resolved = candidate.resolve() if candidate.is_absolute() else (project_root / candidate).resolve()
    try:
        return resolved.relative_to(project_root).as_posix()
    except ValueError:
        return str(resolved)


def _index_workflow_review(
    *,
    registry_path: Path,
    identity: dict[str, Any],
    workflow: dict[str, Any],
    destination: Path,
    node_count: int,
    edge_count: int,
    reviewed_node_revision_hashes: dict[str, str],
    reviewed_node_evidence_sha256: dict[str, dict[str, str]],
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
        "reviewed_node_revision_hashes": deepcopy(reviewed_node_revision_hashes),
        "reviewed_node_evidence_sha256": deepcopy(reviewed_node_evidence_sha256),
        "source_asset_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
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


def _node_evidence_provenance(
    node: dict[str, Any],
    *,
    project_root: Path,
) -> dict[str, str]:
    evidence = node.get("evidence") if isinstance(node.get("evidence"), dict) else {}
    provenance: dict[str, str] = {}
    source_paths = node.get("source_paths")
    if isinstance(source_paths, list):
        normalized_source_paths = [
            str(value or "").strip()
            for value in source_paths
            if str(value or "").strip()
        ]
        provenance["source_paths_sha256"] = hashlib.sha256(
            json.dumps(
                normalized_source_paths,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    for key, value in sorted(evidence.items()):
        if not str(key).endswith("_path"):
            continue
        path_text = str(value or "").strip()
        if not path_text:
            continue
        candidate = Path(path_text)
        resolved = (
            candidate.resolve()
            if candidate.is_absolute()
            else (project_root / candidate).resolve()
        )
        if not resolved.is_file():
            provenance[str(key)] = f"missing:{resolved}"
            continue
        provenance[str(key)] = hashlib.sha256(resolved.read_bytes()).hexdigest()
    return provenance


def evaluate_interface_workflow_node_integrity(
    *,
    review: dict[str, Any],
    node: dict[str, Any],
    record: dict[str, Any],
    project_root: Path,
    source_asset_sha256: str,
) -> dict[str, Any]:
    """验证节点人工审核事实、流程资产与证据来源是否仍为同一修订。"""

    node_id = str(node.get("node_id") or "").strip()
    canonical_revision = build_interface_node_review_revision(
        review,
        node_id=node_id,
    )
    canonical_revision_hash = _interface_node_review_revision_hash(
        canonical_revision
    )
    persisted_revision_hashes = (
        record.get("reviewed_node_revision_hashes")
        if isinstance(record.get("reviewed_node_revision_hashes"), dict)
        else {}
    )
    persisted_evidence_provenance = (
        record.get("reviewed_node_evidence_sha256")
        if isinstance(record.get("reviewed_node_evidence_sha256"), dict)
        else {}
    )
    persisted_source_asset_sha256 = str(
        record.get("source_asset_sha256") or ""
    ).strip()
    expected_evidence_provenance = persisted_evidence_provenance.get(node_id)
    current_evidence_provenance = _node_evidence_provenance(
        node,
        project_root=project_root,
    )
    integrity_verified = bool(
        persisted_source_asset_sha256
        and persisted_source_asset_sha256 == source_asset_sha256
        and canonical_revision_hash
        == str(persisted_revision_hashes.get(node_id) or "").strip()
        and isinstance(expected_evidence_provenance, dict)
        and current_evidence_provenance == expected_evidence_provenance
    )
    eligibility = project_interface_review_eligibility(node)
    if eligibility["agent_usable"] and not integrity_verified:
        eligibility = project_interface_review_eligibility(
            node,
            projection_error="human_review_revision_mismatch",
        )
    return {
        "canonical_revision": canonical_revision,
        "canonical_revision_hash": canonical_revision_hash,
        "expected_evidence_provenance": deepcopy(expected_evidence_provenance),
        "integrity_verified": integrity_verified,
        "eligibility": eligibility,
    }


_HUMAN_REVIEWED_INTERFACE_STATUSES = {
    "approved_as_assisted_template",
    "agent_usable",
    "human_approved",
    "human_reviewed",
}


def project_interface_review_eligibility(
    node: dict[str, Any],
    *,
    projection_error: str = "",
) -> dict[str, Any]:
    """集中计算界面审核资格；未知或损坏状态一律关闭 Agent 使用。"""

    status = str(node.get("review_status") or "needs_human_review").strip().casefold()
    error = str(projection_error or "").strip()
    current_revision_hash = str(node.get("current_revision_hash") or "").strip()
    reviewed_revision_hash = str(node.get("reviewed_revision_hash") or "").strip()
    ownership_review = (
        node.get("hierarchy_ownership_review")
        if isinstance(node.get("hierarchy_ownership_review"), dict)
        else {}
    )
    if ownership_review:
        if ownership_review.get("contract_version") != (
            "hierarchy_ownership_review_revision_v1"
        ):
            return {
                "review_bucket": "unreviewed",
                "agent_usable": False,
                "agent_eligibility_reason": "hierarchy_ownership_review_invalid",
            }
        if str(
            ownership_review.get("integrity_revalidation_status") or ""
        ).strip().casefold() != "passed":
            return {
                "review_bucket": "unreviewed",
                "agent_usable": False,
                "agent_eligibility_reason": (
                    "hierarchy_integrity_revalidation_required"
                ),
            }
        if ownership_review.get("agent_usable") is not True:
            return {
                "review_bucket": "unreviewed",
                "agent_usable": False,
                "agent_eligibility_reason": "hierarchy_review_not_agent_usable",
            }
    revision_bound = bool(
        current_revision_hash
        and reviewed_revision_hash
        and current_revision_hash == reviewed_revision_hash
    )
    reviewed = (
        node.get("reviewed_by_human") is True
        and status in _HUMAN_REVIEWED_INTERFACE_STATUSES
        and revision_bound
        and not error
    )
    return {
        "review_bucket": "reviewed" if reviewed else "unreviewed",
        "agent_usable": reviewed,
        "agent_eligibility_reason": (
            "human_reviewed_current_revision"
            if reviewed
            else error
            or (
                "human_review_revision_missing"
                if node.get("reviewed_by_human") is True and not revision_bound
                else "human_review_required"
            )
        ),
    }


def _hierarchy_ownership_review(draft: dict[str, Any]) -> dict[str, Any]:
    page_details = (
        draft.get("page_details")
        if isinstance(draft.get("page_details"), dict)
        else {}
    )
    review = page_details.get("hierarchy_ownership_review")
    return (
        _without_runtime_click_coordinates(review)
        if isinstance(review, dict)
        else {}
    )


def build_blocked_interface_projection(
    node: dict[str, Any],
    *,
    workflow_id: str,
    reason: str,
) -> dict[str, Any]:
    """只暴露阻断元数据，禁止未审核控件、动作和历史几何进入 Agent 上下文。"""

    return {
        "workflow_id": str(workflow_id or ""),
        "interface_id": str(node.get("node_id") or node.get("interface_id") or ""),
        "display_name": str(
            node.get("display_name") or node.get("node_id") or "未审核界面"
        ),
        "availability": "blocked_unreviewed_interface",
        "agent_usable": False,
        "reason": str(reason or "human_review_required"),
    }


def _project_interface_review_groups(
    *,
    project_root: Path,
    record: dict[str, Any],
) -> tuple[dict[str, list[dict[str, Any]]], str]:
    """从持久化流程生成面板所需的审核分组，不暴露历史点击坐标。"""

    groups: dict[str, list[dict[str, Any]]] = {"reviewed": [], "unreviewed": []}
    raw_path = str(record.get("path") or "").strip()
    if not raw_path:
        return groups, "workflow_path_missing"
    candidate = Path(raw_path)
    resolved = candidate.resolve() if candidate.is_absolute() else (project_root / candidate).resolve()
    if project_root != resolved and project_root not in resolved.parents:
        return groups, "workflow_path_outside_project"
    if not resolved.is_file():
        return groups, "workflow_file_missing"
    try:
        payload_bytes = resolved.read_bytes()
        payload = json.loads(payload_bytes.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return groups, "workflow_file_invalid"
    if payload.get("contract_version") != INTERFACE_WORKFLOW_REVIEW_CONTRACT:
        return groups, "workflow_contract_invalid"
    source_asset_sha256 = hashlib.sha256(payload_bytes).hexdigest()

    for node in payload.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        status = str(node.get("review_status") or "needs_human_review").strip()
        integrity = evaluate_interface_workflow_node_integrity(
            review=payload,
            node=node,
            record=record,
            project_root=project_root,
            source_asset_sha256=source_asset_sha256,
        )
        eligibility = integrity["eligibility"]
        bucket = eligibility["review_bucket"]
        groups[bucket].append(
            {
                "node_id": str(node.get("node_id") or ""),
                "display_name": str(node.get("display_name") or node.get("node_id") or "界面"),
                "state_type": str(node.get("state_type") or "unknown"),
                "review_status": status,
                "reviewed_by_human": node.get("reviewed_by_human") is True,
                "agent_usable": eligibility["agent_usable"],
                "agent_eligibility_reason": eligibility[
                    "agent_eligibility_reason"
                ],
                "editable_review_source_path": str(
                    node.get("editable_review_source_path") or ""
                ),
                "source_paths": [
                    str(value)
                    for value in node.get("source_paths") or []
                    if str(value or "").strip()
                ],
            }
        )
    return groups, ""


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
    applications = registry.get("applications")
    workflows = registry.get("workflows")
    revision = registry.get("registry_revision")
    if (
        not isinstance(applications, dict)
        or not isinstance(workflows, dict)
        or type(revision) is not int
        or revision < 0
    ):
        raise ValueError("interface workflow library registry has an invalid shape")
    for record in workflows.values():
        if not isinstance(record, dict):
            continue
        review_groups, projection_error = _project_interface_review_groups(
            project_root=root,
            record=record,
        )
        record["review_groups"] = review_groups
        record["review_counts"] = {
            "reviewed": len(review_groups["reviewed"]),
            "unreviewed": len(review_groups["unreviewed"]),
        }
        if projection_error:
            record["review_projection_error"] = projection_error
    registry["artifact_is_authorization"] = False
    return registry


def load_interface_workflow_review_context(
    *,
    project_root: Path,
    application_identity_key: str,
    workflow_id: str,
) -> dict[str, Any]:
    """加载完整人工审核流程，保留未审核节点供面板继续修订。"""

    root = Path(project_root).resolve()
    identity_key = str(application_identity_key or "").strip()
    selected_workflow_id = str(workflow_id or "").strip()
    if not identity_key:
        raise ValueError("application identity key is required")
    if not selected_workflow_id:
        raise ValueError("workflow id is required")

    registry = load_interface_workflow_library_registry(project_root=root)
    application = registry.get("applications", {}).get(identity_key)
    if not isinstance(application, dict):
        raise ValueError(f"interface workflow application identity not found: {identity_key}")
    if selected_workflow_id not in set(application.get("workflow_ids") or []):
        raise ValueError("interface workflow does not belong to the selected application")
    record = registry.get("workflows", {}).get(selected_workflow_id)
    if not isinstance(record, dict):
        raise ValueError(f"interface workflow not found: {selected_workflow_id}")

    path = Path(str(record.get("path") or ""))
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    if root not in resolved.parents:
        raise ValueError("interface workflow path escapes project root")
    payload = json.loads(resolved.read_text(encoding="utf-8-sig"))
    if payload.get("contract_version") != INTERFACE_WORKFLOW_REVIEW_CONTRACT:
        raise ValueError("reviewed interface workflow has an invalid contract")
    review = _without_runtime_click_coordinates(payload)
    review["artifact_is_authorization"] = False
    review["execute_binding_enabled"] = False
    return review


def delete_learning_evidence(
    *,
    project_root: Path,
    source_path: str | Path,
) -> dict[str, Any]:
    """删除未被流程引用的单个学习证据文件。"""

    root = Path(project_root).resolve()
    candidate = Path(source_path)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    managed_roots = (
        root / "artifacts" / "learning-runs",
        root / "artifacts" / "learning-draft-review",
    )
    if not any(managed_root in resolved.parents for managed_root in managed_roots):
        raise ValueError("learning evidence path must stay inside managed learning evidence roots")
    if not resolved.is_file():
        raise ValueError(f"learning evidence file does not exist: {resolved}")

    references = _find_workflow_evidence_references(
        project_root=root,
        evidence_path=resolved,
    )
    if references:
        workflow_ids = ", ".join(sorted({item["workflow_id"] for item in references}))
        raise ValueError(
            "learning evidence is still referenced by workflows: " + workflow_ids
        )

    deleted_path = _project_path_reference(resolved, root)
    resolved.unlink()
    return {
        "contract_version": "learning_evidence_delete_v1",
        "deleted": True,
        "deleted_path": deleted_path,
        "workflow_references": [],
        "associated_files_preserved": True,
        "artifact_is_authorization": False,
    }


def delete_interface_workflow_review_candidate(
    *,
    project_root: Path,
    workflow_id: str,
) -> dict[str, Any]:
    """删除一个已保存流程，不级联删除共享的单界面证据。"""

    normalized_workflow_id = str(workflow_id or "").strip()
    if not normalized_workflow_id:
        raise ValueError("workflow_id is required")
    root = Path(project_root).resolve()
    workflow_root = (root / "artifacts" / "interface-workflow-reviews").resolve()
    registry_path = workflow_root / "registry.json"
    registry = _load_raw_interface_workflow_registry(registry_path)
    workflows = registry.get("workflows")
    if not isinstance(workflows, dict) or normalized_workflow_id not in workflows:
        raise ValueError(f"interface workflow does not exist: {normalized_workflow_id}")
    record = workflows[normalized_workflow_id]
    if not isinstance(record, dict):
        raise ValueError("interface workflow registry record must be an object")
    raw_path = str(record.get("path") or "").strip()
    if not raw_path:
        raise ValueError("interface workflow registry path is missing")
    candidate = Path(raw_path)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    if workflow_root not in resolved.parents or resolved.parent == workflow_root:
        raise ValueError("interface workflow path must stay inside its managed workflow directory")
    if resolved.name != "reviewed_workflow.json":
        raise ValueError("interface workflow registry path must target reviewed_workflow.json")
    safe_workflow_id = "".join(
        character if character.isalnum() or character in "_.-" else "_"
        for character in normalized_workflow_id
    ).strip("._")
    if not safe_workflow_id or resolved.parent.name != safe_workflow_id:
        raise ValueError("interface workflow registry path does not match workflow_id")

    next_registry = deepcopy(registry)
    next_registry["workflows"].pop(normalized_workflow_id, None)
    applications = next_registry.get("applications")
    if isinstance(applications, dict):
        empty_identity_keys: list[str] = []
        for identity_key, application in applications.items():
            if not isinstance(application, dict):
                continue
            workflow_ids = [
                str(value)
                for value in application.get("workflow_ids") or []
                if str(value) != normalized_workflow_id
            ]
            application["workflow_ids"] = workflow_ids
            if not workflow_ids:
                empty_identity_keys.append(str(identity_key))
        for identity_key in empty_identity_keys:
            applications.pop(identity_key, None)
    next_registry["registry_revision"] = int(registry.get("registry_revision") or 0) + 1
    next_registry["artifact_is_authorization"] = False
    _write_interface_workflow_registry(registry_path, next_registry)

    if resolved.parent.exists():
        shutil.rmtree(resolved.parent)
    return {
        "contract_version": "interface_workflow_delete_v1",
        "workflow_id": normalized_workflow_id,
        "deleted": True,
        "deleted_path": _project_path_reference(resolved.parent, root),
        "single_interface_evidence_deleted": False,
        "shared_evidence_preserved": True,
        "artifact_is_authorization": False,
    }


def _load_raw_interface_workflow_registry(registry_path: Path) -> dict[str, Any]:
    if not registry_path.is_file():
        raise ValueError("interface workflow library registry does not exist")
    registry = json.loads(registry_path.read_text(encoding="utf-8-sig"))
    if (
        not isinstance(registry, dict)
        or registry.get("contract_version") != "interface_workflow_library_registry_v1"
    ):
        raise ValueError("interface workflow library registry has an invalid contract")
    if not isinstance(registry.get("workflows"), dict):
        raise ValueError("interface workflow library registry workflows must be an object")
    return registry


def _write_interface_workflow_registry(
    registry_path: Path,
    registry: dict[str, Any],
) -> None:
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = registry_path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(registry_path)


def _find_workflow_evidence_references(
    *,
    project_root: Path,
    evidence_path: Path,
) -> list[dict[str, str]]:
    registry_path = (
        project_root / "artifacts" / "interface-workflow-reviews" / "registry.json"
    )
    if not registry_path.is_file():
        return []
    registry = _load_raw_interface_workflow_registry(registry_path)
    references: list[dict[str, str]] = []
    for workflow_id, record in registry.get("workflows", {}).items():
        if not isinstance(record, dict):
            continue
        raw_workflow_path = str(record.get("path") or "").strip()
        if not raw_workflow_path:
            continue
        workflow_path = Path(raw_workflow_path)
        workflow_path = (
            workflow_path.resolve()
            if workflow_path.is_absolute()
            else (project_root / workflow_path).resolve()
        )
        if not workflow_path.is_file():
            continue
        try:
            workflow = json.loads(workflow_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        for node in workflow.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            node_paths = [node.get("editable_review_source_path")]
            node_paths.extend(node.get("source_paths") or [])
            for raw_node_path in node_paths:
                node_path_text = str(raw_node_path or "").strip()
                if not node_path_text:
                    continue
                node_path = Path(node_path_text)
                node_path = (
                    node_path.resolve()
                    if node_path.is_absolute()
                    else (project_root / node_path).resolve()
                )
                if node_path == evidence_path:
                    references.append(
                        {
                            "workflow_id": str(workflow_id),
                            "node_id": str(node.get("node_id") or ""),
                        }
                    )
                    break
    return references


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
    agent_evidence_workflows: list[dict[str, Any]] = []
    blocked_interfaces: list[dict[str, Any]] = []
    agent_usable_interfaces: list[dict[str, Any]] = []
    for workflow_id in application.get("workflow_ids", []):
        record = registry.get("workflows", {}).get(workflow_id)
        if not isinstance(record, dict):
            continue
        path = Path(str(record.get("path") or ""))
        resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
        if root not in resolved.parents:
            raise ValueError("interface workflow path escapes project root")
        payload_bytes = resolved.read_bytes()
        payload = json.loads(payload_bytes.decode("utf-8-sig"))
        if payload.get("contract_version") != INTERFACE_WORKFLOW_REVIEW_CONTRACT:
            raise ValueError("reviewed interface workflow has an invalid contract")
        workflow = _without_runtime_click_coordinates(payload)
        nodes = [node for node in workflow.get("nodes") or [] if isinstance(node, dict)]
        source_asset_sha256 = hashlib.sha256(payload_bytes).hexdigest()
        trusted_revisions: dict[str, PersistedReviewRevision] = {}
        context_nodes: list[dict[str, Any]] = []
        persisted_revision_hashes = (
            record.get("reviewed_node_revision_hashes")
            if isinstance(record.get("reviewed_node_revision_hashes"), dict)
            else {}
        )
        persisted_evidence_provenance = (
            record.get("reviewed_node_evidence_sha256")
            if isinstance(record.get("reviewed_node_evidence_sha256"), dict)
            else {}
        )
        source_asset_verified = (
            str(record.get("source_asset_sha256") or "").strip()
            == source_asset_sha256
        )
        for node in nodes:
            node_id = str(node.get("node_id") or "").strip()
            integrity = evaluate_interface_workflow_node_integrity(
                review=workflow,
                node=node,
                record=record,
                project_root=root,
                source_asset_sha256=source_asset_sha256,
            )
            canonical_revision = integrity["canonical_revision"]
            canonical_revision_hash = integrity["canonical_revision_hash"]
            eligibility = integrity["eligibility"]
            if eligibility["agent_usable"] and integrity["integrity_verified"]:
                trusted_revisions[node_id] = PersistedReviewRevision(
                    revision=canonical_revision,
                    revision_hash=canonical_revision_hash,
                    source_asset_sha256=source_asset_sha256,
                )
            if eligibility["agent_usable"]:
                context_nodes.append(node)
                continue
            if (
                node.get("agent_evidence_status") == "reviewed_interface_memory"
                and source_asset_verified
                and node_id not in persisted_revision_hashes
                and node_id not in persisted_evidence_provenance
                and eligibility["agent_eligibility_reason"] == "human_review_required"
            ):
                context_nodes.append(node)
                continue
            blocked_interfaces.append(
                build_blocked_interface_projection(
                    node,
                    workflow_id=str(workflow_id),
                    reason=str(eligibility["agent_eligibility_reason"]),
                )
            )

        context_node_ids = {
            str(node.get("node_id") or "") for node in context_nodes
        }
        context_edges = [
            edge
            for edge in workflow.get("edges") or []
            if isinstance(edge, dict)
            and str(edge.get("source_node_id") or "") in context_node_ids
            and str(edge.get("target_node_id") or "") in context_node_ids
        ]
        filtered_workflow = deepcopy(workflow)
        filtered_workflow["nodes"] = context_nodes
        filtered_workflow["edges"] = context_edges
        workflow_meta = (
            filtered_workflow.get("workflow")
            if isinstance(filtered_workflow.get("workflow"), dict)
            else {}
        )
        workflow_meta["node_ids"] = [
            str(node.get("node_id") or "") for node in context_nodes
        ]
        workflow_meta["edge_ids"] = [
            str(edge.get("edge_id") or "") for edge in context_edges
        ]
        entry_node_id = str(workflow_meta.get("entry_node_id") or "")
        if entry_node_id not in context_node_ids:
            workflow_meta["entry_node_id"] = (
                str(context_nodes[0].get("node_id") or "") if context_nodes else ""
            )
        filtered_workflow["workflow"] = workflow_meta
        workflows.append(filtered_workflow)
        if not context_nodes:
            continue

        workflow_evidence = build_workflow_agent_evidence(
            filtered_workflow,
            persisted_review_revisions=trusted_revisions,
        )
        for interface_evidence in workflow_evidence.get("interfaces") or []:
            if not isinstance(interface_evidence, dict):
                continue
            interface_evidence["source_asset_sha256"] = source_asset_sha256
            if (interface_evidence.get("readiness") or {}).get("status") == "agent_usable":
                agent_usable_interfaces.append(
                    {
                        "workflow_id": str(workflow_id),
                        "interface_id": str(
                            (interface_evidence.get("interface") or {}).get(
                                "interface_id"
                            )
                            or ""
                        ),
                        "display_name": str(
                            (interface_evidence.get("interface") or {}).get(
                                "display_name"
                            )
                            or ""
                        ),
                        "agent_usable": True,
                    }
                )
        agent_evidence_workflows.append(workflow_evidence)

    projected_interface_count = sum(
        len(workflow.get("interfaces") or [])
        for workflow in agent_evidence_workflows
        if isinstance(workflow, dict)
    )
    agent_ready = bool(
        projected_interface_count
        and not blocked_interfaces
        and len(agent_usable_interfaces) == projected_interface_count
    )

    return {
        "contract_version": "interface_workflow_agent_context_v1",
        "application_identity_key": identity_key,
        "application_identity": deepcopy(application.get("application_identity") or {}),
        "workflow_count": len(workflows),
        "workflows": workflows,
        "agent_evidence_workflows": agent_evidence_workflows,
        "agent_ready": agent_ready,
        "blocked_interfaces": blocked_interfaces,
        "agent_usable_interfaces": agent_usable_interfaces,
        "execution_contract": {
            "historical_coordinates_forbidden": True,
            "current_capture_required": True,
            "fresh_grounding_required": True,
            "gate_required": True,
            "post_action_verification_required": True,
            "final_submit_forbidden": True,
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


def _preserved_node_id(review: dict[str, Any]) -> str:
    identity = (
        review.get("workflow_node_identity")
        if isinstance(review.get("workflow_node_identity"), dict)
        else {}
    )
    node_id = str(identity.get("node_id") or "").strip()
    if node_id.startswith("interface_") and all(
        character.isalnum() or character in "_.-" for character in node_id
    ):
        return node_id
    return ""


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
