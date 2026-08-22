"""将已持久化的人审 v1 流程严格编译为可验证的 v2 语义资产。"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset
from app.learn.application_identity import normalize_application_identity
from app.learn.interface_workflow_review import (
    INTERFACE_WORKFLOW_REVIEW_CONTRACT,
    evaluate_interface_workflow_node_integrity,
)

_COMPILE_CONTRACT = "reviewed_workflow_compile_result_v2"
_REGISTRY_CONTRACT = "interface_workflow_library_registry_v1"
_ALLOWED_ACTIONS = {"open_detail", "open_apply_flow", "back", "close_modal"}
_STOP_BOUNDARY_STATUS = "needs_learning"
_SAFE_ID_PART = re.compile(r"[^A-Za-z0-9_.:-]+")
_GRANULAR_CONFIRMATION_CONTRACTS = {
    "action_candidate": "interface_action_candidate_human_review_confirmation_v1",
    "edge": "interface_workflow_edge_human_review_confirmation_v1",
    "target_control": "interface_target_control_human_review_confirmation_v1",
}
_REVIEW_REVISION_METADATA_FIELDS = {
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
_RUNTIME_POINT_FIELDS = {
    "actual_point",
    "click_point",
    "clickpoint",
    "confirmed_point",
    "screen_point",
    "target_point",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_sha256(value: Any) -> str:
    return _sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def _granular_review_revision(value: Any) -> Any:
    if isinstance(value, list):
        return [_granular_review_revision(item) for item in value]
    if not isinstance(value, dict):
        return deepcopy(value)
    return {
        key: _granular_review_revision(item)
        for key, item in value.items()
        if key not in _REVIEW_REVISION_METADATA_FIELDS and key not in _RUNTIME_POINT_FIELDS
    }


def _type_exact_equal(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _type_exact_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _type_exact_equal(left_item, right_item)
            for left_item, right_item in zip(left, right)
        )
    return left == right


def _granular_human_review_is_current(subject: Any, subject_kind: str) -> bool:
    if not isinstance(subject, dict):
        return False
    confirmation = subject.get("human_review_confirmation")
    return (
        subject.get("review_status") == "human_approved"
        and subject.get("reviewed_by_human") is True
        and isinstance(confirmation, dict)
        and confirmation.get("contract_version")
        == _GRANULAR_CONFIRMATION_CONTRACTS[subject_kind]
        and subject.get("display_only") is True
        and subject.get("artifact_is_authorization") is False
        and subject.get("execute_binding_enabled") is False
        and _type_exact_equal(
            confirmation.get("revision"), _granular_review_revision(subject)
        )
    )


def _exact_transition_subjects(
    *, node: dict[str, Any], edge: dict[str, Any]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str]:
    target_control_id = _text(edge.get("target_control_id"))
    target_region_id = _text(edge.get("target_region_id"))
    if bool(target_control_id) == bool(target_region_id):
        return None, None, "edge must reference exactly one target control or target region"
    collection_name = "controls" if target_control_id else "regions"
    id_key = "control_id" if target_control_id else "region_id"
    target_id = target_control_id or target_region_id
    collection = node.get(collection_name)
    target_matches = [
        item
        for item in collection if isinstance(item, dict) and _text(item.get(id_key)) == target_id
    ] if isinstance(collection, list) else []
    if len(target_matches) != 1:
        return None, None, "edge target must match exactly one source-node item of the declared type"

    action_template_id = _text(edge.get("action_template_id"))
    candidates = node.get("action_candidates")
    action_matches = [
        item
        for item in candidates
        if isinstance(item, dict)
        and _text(item.get("action_template_id")) == action_template_id
    ] if isinstance(candidates, list) else []
    if not action_template_id or len(action_matches) != 1:
        return target_matches[0], None, "edge action_template_id must match exactly one action candidate"
    action_candidate = action_matches[0]
    edge_action = _text(edge.get("action_type")).casefold()
    edge_semantic_action = _text(edge.get("semantic_action")).casefold()
    candidate_semantic_action = _text(action_candidate.get("semantic_action")).casefold()
    candidate_action_type = _text(action_candidate.get("action_type")).casefold()
    candidate_action = candidate_semantic_action or candidate_action_type
    candidate_target_node_ids = [
        _text(action_candidate.get(key))
        for key in ("target_interface_id", "target_node_id")
        if _text(action_candidate.get(key))
    ]
    if (
        (edge_semantic_action and edge_semantic_action != edge_action)
        or (
            candidate_semantic_action
            and candidate_action_type
            and candidate_semantic_action != candidate_action_type
        )
        or candidate_action != edge_action
        or _text(action_candidate.get("target_control_id")) != target_control_id
        or _text(action_candidate.get("target_region_id")) != target_region_id
        or (
            _text(action_candidate.get("source_control_id"))
            and _text(action_candidate.get("source_control_id")) != target_id
        )
        or not candidate_target_node_ids
        or any(value != _text(edge.get("target_node_id")) for value in candidate_target_node_ids)
    ):
        return target_matches[0], None, "matched action candidate type, control, or target is inconsistent with edge"
    return target_matches[0], action_candidate, ""


def _reason(code: str, detail: str, **context: str) -> dict[str, Any]:
    result: dict[str, Any] = {"code": code, "detail": detail}
    if context:
        result["context"] = context
    return result


def _blocked(reasons: list[dict[str, Any]], *, lineage: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "contract_version": _COMPILE_CONTRACT,
        "status": "blocked",
        "asset": None,
        "source_review_lineage": deepcopy(lineage) if lineage else {},
        "blocked_reasons": reasons,
    }


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _resolve_source(project_root: Path, source_workflow_path: str | Path) -> tuple[Path, str] | None:
    raw = Path(source_workflow_path)
    if raw.is_absolute() or PureWindowsPath(str(source_workflow_path)).is_absolute():
        return None
    if any(part in {"", ".", ".."} for part in raw.parts):
        return None
    root = project_root.resolve()
    source = (root / raw).resolve()
    if not _inside(root, source) or not source.is_file():
        return None
    try:
        relative = source.relative_to(root).as_posix()
    except ValueError:
        return None
    path = PurePosixPath(relative)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    return source, relative


def _safe_id(prefix: str, value: Any) -> str:
    raw = _text(value)
    normalized = _SAFE_ID_PART.sub("_", raw).strip("_.:-") or "unnamed"
    suffix = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    available = 127 - len(prefix) - len(suffix)
    return f"{prefix}{normalized[:max(1, available)]}_{suffix}"


def _anchor_label(item: dict[str, Any], fallback: str) -> str:
    for key in ("label", "semantic_name", "display_name", "name", "purpose", "text", "value"):
        value = _text(item.get(key))
        if value:
            return value
    return fallback


def _stable_node_anchors(node: dict[str, Any], state_id: str) -> tuple[list[dict[str, str]], dict[str, str]]:
    anchors: list[dict[str, str]] = []
    target_refs: dict[str, str] = {}
    display = _text(node.get("display_name") or node.get("state_signature") or node.get("node_id"))
    anchors.append(
        {
            "anchor_id": _safe_id("anchor_", f"{state_id}:identity"),
            "label": display,
            "kind": "text",
        }
    )
    for collection, id_keys, kind in (
        (node.get("controls"), ("control_id", "id"), "control"),
        (node.get("regions"), ("region_id", "id"), "region"),
    ):
        if not isinstance(collection, list):
            continue
        for index, item in enumerate(collection):
            if not isinstance(item, dict):
                continue
            original_id = next((_text(item.get(key)) for key in id_keys if _text(item.get(key))), "")
            if not original_id or original_id in target_refs:
                continue
            anchor_id = _safe_id("anchor_", f"{state_id}:{kind}:{original_id}")
            anchors.append(
                {"anchor_id": anchor_id, "label": _anchor_label(item, original_id), "kind": kind}
            )
            target_refs[original_id] = anchor_id
    return anchors, target_refs


def _application_asset(identity: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "identity_status": "resolved",
        "kind": identity["kind"],
        "allow_external_sites": False,
    }
    if identity["kind"] == "web":
        result["canonical_origin"] = identity.get("canonical_origin")
        result["canonical_domain"] = identity.get("canonical_domain")
    else:
        result["executable"] = identity.get("executable_identity")
        result["product_identity"] = identity.get("product_identity")
    return result


def _preconditions() -> dict[str, Any]:
    return {
        "current_observation": {"required": True},
        "capture": {
            "capture_id": {"required": True},
            "screenshot_sha256": {"required": True},
            "viewport_size": {"required": True},
        },
        "grounding": {
            "required": True,
            "current_target_bbox": {"required": True},
            "click_point": {"required": True},
            "confidence": {"required": True},
            "score_margin": {"required": True},
        },
        "source_state_unique": {"required": True},
        "gate": {"required": True, "endpoint": "POST /action/execute_recognition_plan"},
        "approved_plan_capture_lineage": {"required": True},
    }


def _recovery_policy() -> dict[str, Any]:
    return {
        "max_attempts": 1,
        "stale_capture": "recapture_and_reground",
        "target_not_found": "one_fresh_grounding",
        "post_action_failure": "observe_without_repeat",
        "destination_mismatch": "safe_stop_human_review",
        "foreground_change": "safe_stop_human_review",
        "unexpected_origin": "safe_stop_human_review",
    }


def _identity_comparison_fields(identity: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "identity_status": identity.get("identity_status"),
        "kind": identity.get("kind"),
        "identity_key": identity.get("identity_key"),
    }
    if identity.get("kind") == "web":
        fields.update(
            {
                "canonical_origin": identity.get("canonical_origin"),
                "canonical_domain": identity.get("canonical_domain"),
            }
        )
    else:
        fields.update(
            {
                "executable_identity": identity.get("executable_identity"),
                "product_identity": identity.get("product_identity"),
            }
        )
    return fields


def _reviewed_condition_rules(
    *, edge_id: str, field_name: str, value: Any, required: bool
) -> tuple[list[dict[str, str]], dict[str, Any] | None]:
    if not isinstance(value, list):
        return [], _reason(
            "semantic_condition_malformed",
            f"edge {field_name} must be an array of nonempty strings",
            edge_id=edge_id,
            field=field_name,
        )
    if any(not isinstance(item, str) or not item.strip() for item in value):
        return [], _reason(
            "semantic_condition_malformed",
            f"edge {field_name} must contain only nonempty strings",
            edge_id=edge_id,
            field=field_name,
        )
    if required and not value:
        return [], _reason(
            "success_conditions_missing",
            "edge requires nonempty semantic success conditions",
            edge_id=edge_id,
        )
    rule_type = {
        "preconditions": "source_semantic_precondition",
        "success_conditions": "source_semantic_success_condition",
        "failure_conditions": "source_semantic_failure_condition",
    }[field_name]
    return [
        {
            "rule_id": _safe_id("rule_", f"{edge_id}:{field_name}:{index}"),
            "type": rule_type,
            "condition": item.strip(),
        }
        for index, item in enumerate(value, start=1)
    ], None


def _load_registry(root: Path) -> dict[str, Any] | None:
    path = root / "artifacts" / "interface-workflow-reviews" / "registry.json"
    if not path.is_file():
        return None
    try:
        registry = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(registry, dict) or registry.get("contract_version") != _REGISTRY_CONTRACT:
        return None
    return registry


def _registry_record(
    *, root: Path, registry: dict[str, Any], workflow_id: str, identity: dict[str, Any], source: Path, source_sha: str
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    workflows = registry.get("workflows")
    applications = registry.get("applications")
    if not isinstance(workflows, dict) or not isinstance(applications, dict):
        return None, [_reason("registry_invalid", "v1 registry must contain workflows and applications objects")]
    record = workflows.get(workflow_id)
    identity_key = _text(identity.get("identity_key"))
    application = applications.get(identity_key)
    if not isinstance(record, dict) or not isinstance(application, dict):
        return None, [_reason("registry_workflow_or_application_missing", "workflow and normalized application must be indexed", workflow_id=workflow_id, identity_key=identity_key)]
    if workflow_id not in {str(value) for value in application.get("workflow_ids") or []}:
        return None, [_reason("registry_application_workflow_mismatch", "workflow is not registered for normalized application identity", workflow_id=workflow_id, identity_key=identity_key)]
    if _text(record.get("application_identity_key")) != identity_key:
        return None, [_reason("registry_application_identity_mismatch", "registry record identity does not match source workflow", workflow_id=workflow_id)]
    embedded_identity = application.get("application_identity")
    if not isinstance(embedded_identity, dict):
        return None, [_reason("registry_embedded_application_identity_missing", "registry application record must contain application_identity", identity_key=identity_key)]
    try:
        normalized_embedded_identity = normalize_application_identity(embedded_identity)
    except Exception:
        return None, [
            _reason(
                "registry_embedded_application_identity_invalid",
                "registry embedded application identity could not be normalized",
                identity_key=identity_key,
            )
        ]
    if _identity_comparison_fields(normalized_embedded_identity) != _identity_comparison_fields(identity):
        return None, [_reason("registry_embedded_application_identity_mismatch", "registry embedded application identity does not match source workflow", identity_key=identity_key)]
    raw_record_path = _text(record.get("path"))
    if not raw_record_path:
        return None, [_reason("registry_path_missing", "registry record does not contain a workflow path", workflow_id=workflow_id)]
    record_path = Path(raw_record_path)
    resolved_record_path = record_path.resolve() if record_path.is_absolute() else (root / record_path).resolve()
    if not _inside(root, resolved_record_path) or resolved_record_path != source:
        return None, [_reason("registry_path_mismatch", "registry path does not resolve to requested source workflow", workflow_id=workflow_id)]
    if _text(record.get("source_asset_sha256")).lower() != source_sha:
        return None, [_reason("registry_source_asset_sha256_mismatch", "registry source asset hash does not match source bytes", workflow_id=workflow_id)]
    return record, []


def compile_reviewed_workflow_asset_v2(
    *, project_root: Path, source_workflow_path: str | Path, expected_source_workflow_sha256: str
) -> dict[str, Any]:
    """编译 v1 人审流程；所有不可信或过期输入均显式返回 blocked。"""

    root = Path(project_root).resolve()
    resolved = _resolve_source(root, source_workflow_path)
    if resolved is None:
        return _blocked([_reason("source_workflow_path_invalid", "source workflow path must be an existing project-relative non-symlink-escape file")])
    source, source_path = resolved
    try:
        source_bytes = source.read_bytes()
    except OSError as exc:
        return _blocked([_reason("source_workflow_read_failed", str(exc))])
    source_sha = _sha256(source_bytes)
    if _text(expected_source_workflow_sha256).lower() != source_sha:
        return _blocked([_reason("source_workflow_sha256_mismatch", "expected source workflow SHA-256 does not match current bytes")])
    try:
        review = json.loads(source_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _blocked([_reason("source_workflow_invalid_json", str(exc))])
    if not isinstance(review, dict) or review.get("contract_version") != INTERFACE_WORKFLOW_REVIEW_CONTRACT:
        return _blocked([_reason("source_workflow_contract_invalid", f"source contract must be {INTERFACE_WORKFLOW_REVIEW_CONTRACT}")])
    workflow = review.get("workflow")
    nodes = review.get("nodes")
    edges = review.get("edges")
    if not isinstance(workflow, dict) or not isinstance(nodes, list) or not isinstance(edges, list):
        return _blocked([_reason("source_workflow_structure_invalid", "v1 workflow, nodes and edges are required")])
    workflow_id = _text(workflow.get("workflow_id"))
    try:
        identity = normalize_application_identity(
            workflow.get("application_identity")
            if isinstance(workflow.get("application_identity"), dict)
            else {}
        )
    except Exception:
        return _blocked(
            [
                _reason(
                    "application_identity_invalid",
                    "source application identity could not be normalized",
                )
            ]
        )
    if not workflow_id or identity.get("identity_status") != "resolved" or not _text(identity.get("identity_key")):
        return _blocked([_reason("application_identity_unresolved", "workflow id and resolved application identity are required")])
    registry = _load_registry(root)
    if registry is None:
        return _blocked([_reason("registry_missing_or_invalid", "v1 workflow registry is missing or invalid")])
    record, registry_errors = _registry_record(root=root, registry=registry, workflow_id=workflow_id, identity=identity, source=source, source_sha=source_sha)
    if registry_errors:
        return _blocked(registry_errors)
    assert record is not None

    node_by_id: dict[str, dict[str, Any]] = {}
    reasons: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict) or not _text(node.get("node_id")):
            reasons.append(_reason("source_node_invalid", "each source node requires a node_id"))
            continue
        node_id = _text(node["node_id"])
        if node_id in node_by_id:
            reasons.append(_reason("duplicate_source_node_id", "source node ids must be unique", node_id=node_id))
        node_by_id[node_id] = node
    declared_node_ids = [_text(value) for value in workflow.get("node_ids") or []]
    if declared_node_ids != list(node_by_id):
        reasons.append(_reason("source_node_revision_invalid", "workflow node ids must match source node order"))
    entry_node_id = _text(workflow.get("entry_node_id"))
    if entry_node_id not in node_by_id:
        reasons.append(_reason("entry_node_invalid", "entry node must resolve to a source node", node_id=entry_node_id))

    reviewed_integrity: dict[str, dict[str, Any]] = {}
    availability: dict[str, str] = {}
    for node_id, node in node_by_id.items():
        status = _text(node.get("review_status")).casefold()
        if status == _STOP_BOUNDARY_STATUS:
            availability[node_id] = "stop_boundary"
            continue
        integrity = evaluate_interface_workflow_node_integrity(review=review, node=node, record=record, project_root=root, source_asset_sha256=source_sha)
        reviewed_integrity[node_id] = integrity
        if integrity["integrity_verified"] and integrity["eligibility"].get("agent_usable") is True:
            availability[node_id] = "reviewed"
        else:
            availability[node_id] = "blocked"
            reasons.append(_reason("source_node_not_human_reviewed", "source node is not a current integrity-verified human review", node_id=node_id, reason=_text(integrity["eligibility"].get("agent_eligibility_reason"))))

    edge_by_id: dict[str, dict[str, Any]] = {}
    for edge in edges:
        if not isinstance(edge, dict) or not _text(edge.get("edge_id")):
            reasons.append(_reason("source_edge_invalid", "each source edge requires an edge_id"))
            continue
        edge_id = _text(edge["edge_id"])
        if edge_id in edge_by_id:
            reasons.append(_reason("duplicate_source_edge_id", "source edge ids must be unique", edge_id=edge_id))
        edge_by_id[edge_id] = edge
    declared_edge_ids = [_text(value) for value in workflow.get("edge_ids") or []]
    if declared_edge_ids != list(edge_by_id):
        reasons.append(_reason("source_edge_revision_invalid", "workflow edge ids must match source edge order"))

    state_ids = {node_id: _safe_id("state_", node_id) for node_id in node_by_id}
    anchors_by_node: dict[str, dict[str, str]] = {}
    states: list[dict[str, Any]] = []
    for node_id, node in node_by_id.items():
        state_id = state_ids[node_id]
        anchors, target_refs = _stable_node_anchors(node, state_id)
        anchors_by_node[node_id] = target_refs
        state: dict[str, Any] = {
            "state_id": state_id,
            "source_node_id": node_id,
            "state_type": _text(node.get("surface_type") or "application_surface"),
            "display_name": _text(node.get("display_name") or node_id),
            "identity_anchors": anchors,
            "allowed_transition_ids": [],
            "availability": availability.get(node_id, "blocked"),
        }
        if state["availability"] == "reviewed":
            state["grounding_profile"] = {"provider": "current_observation_grounding_v1"}
        states.append(state)

    transitions: list[dict[str, Any]] = []
    for edge_id, edge in edge_by_id.items():
        source_id = _text(edge.get("source_node_id"))
        target_id = _text(edge.get("target_node_id"))
        action = _text(edge.get("action_type")).casefold()
        if source_id not in node_by_id or target_id not in node_by_id:
            reasons.append(_reason("edge_node_reference_invalid", "edge source and target must exist", edge_id=edge_id))
            continue
        if action not in _ALLOWED_ACTIONS:
            reasons.append(_reason("semantic_action_not_mvp_executable", "action is not executable in the v2 MVP", edge_id=edge_id, action=action or "missing"))
            continue
        reviewed_preconditions, precondition_error = _reviewed_condition_rules(
            edge_id=edge_id,
            field_name="preconditions",
            value=edge.get("preconditions"),
            required=False,
        )
        success_rules, success_error = _reviewed_condition_rules(
            edge_id=edge_id,
            field_name="success_conditions",
            value=edge.get("success_conditions"),
            required=True,
        )
        failure_rules, failure_error = _reviewed_condition_rules(
            edge_id=edge_id,
            field_name="failure_conditions",
            value=edge.get("failure_conditions"),
            required=False,
        )
        condition_errors = [
            item
            for item in (precondition_error, success_error, failure_error)
            if item is not None
        ]
        if condition_errors:
            reasons.extend(condition_errors)
            continue
        if availability.get(source_id) == "stop_boundary":
            reasons.append(
                _reason(
                    "stop_boundary_has_outgoing_transition",
                    "needs_learning stop boundary cannot declare outgoing transitions",
                    edge_id=edge_id,
                    source_node_id=source_id,
                )
            )
            continue
        availability_invalid = False
        if availability.get(source_id) != "reviewed":
            reasons.append(_reason("edge_source_not_reviewed", "outgoing edge authority requires reviewed source node", edge_id=edge_id, source_node_id=source_id))
            availability_invalid = True
        if availability.get(target_id) not in {"reviewed", "stop_boundary"}:
            reasons.append(_reason("edge_target_not_reviewed", "edge target must be reviewed or needs_learning stop boundary", edge_id=edge_id, target_node_id=target_id))
            availability_invalid = True
        target_reference = _text(edge.get("target_control_id") or edge.get("target_region_id"))
        element_ref = anchors_by_node[source_id].get(target_reference)
        element_invalid = not target_reference or not element_ref
        if element_invalid:
            reasons.append(_reason("edge_target_element_invalid", "edge target control or region must exist in reviewed source node", edge_id=edge_id, source_node_id=source_id))
        target_subject, action_subject, subject_error = _exact_transition_subjects(
            node=node_by_id[source_id], edge=edge
        )
        granular_errors: list[dict[str, Any]] = []
        if not _granular_human_review_is_current(target_subject, "target_control"):
            granular_errors.append(
                _reason(
                    "edge_target_control_approval_invalid",
                    subject_error or "edge target control or region lacks a current human approval",
                    edge_id=edge_id,
                    source_node_id=source_id,
                )
            )
        if not _granular_human_review_is_current(action_subject, "action_candidate"):
            granular_errors.append(
                _reason(
                    "edge_action_candidate_approval_invalid",
                    subject_error or "edge action candidate lacks a current human approval",
                    edge_id=edge_id,
                    source_node_id=source_id,
                )
            )
        if not _granular_human_review_is_current(edge, "edge"):
            granular_errors.append(
                _reason(
                    "edge_approval_invalid",
                    "edge lacks a current human approval for its exact semantic revision",
                    edge_id=edge_id,
                    source_node_id=source_id,
                )
            )
        if granular_errors:
            reasons.extend(granular_errors)
        if granular_errors or availability_invalid:
            continue
        if element_invalid:
            continue
        transition_id = _safe_id("transition_", edge_id)
        target_state_id = state_ids[target_id]
        target_identity_rule = {
            "rule_id": _safe_id(
                "rule_",
                f"{edge_id}:target_state_identity:{target_state_id}",
            ),
            "type": "target_state_identity",
        }
        requires_user_confirmation = edge.get("requires_user_confirmation")
        if not isinstance(requires_user_confirmation, bool):
            reasons.append(
                _reason(
                    "risk_policy_malformed",
                    "requires_user_confirmation must be boolean",
                    edge_id=edge_id,
                )
            )
            continue
        risk_policy: dict[str, Any] = {
            "risk_level": _text(edge.get("risk_level") or "low").casefold(),
            "requires_gate": True,
            "final_submit_forbidden": True,
            "requires_user_confirmation": requires_user_confirmation,
        }
        if requires_user_confirmation:
            risk_policy["automatic_execution_allowed"] = False
        transitions.append(
            {
                "transition_id": transition_id,
                "source_state_id": state_ids[source_id],
                "target_state_id": target_state_id,
                "semantic_action": action,
                "display_name": _text(edge.get("operation_id") or edge_id),
                "element_ref": element_ref,
                "preconditions": _preconditions(),
                "reviewed_semantic_constraints": {
                    "preconditions": reviewed_preconditions,
                    "failure_conditions": failure_rules,
                },
                "expected_effect": {"semantic_success": {"target_state_id": target_state_id}, "semantic_success_rules": deepcopy(success_rules)},
                "post_action_verification": {"requires_new_capture": True, "semantic_success_rules": [target_identity_rule]},
                "recovery_policy": _recovery_policy(),
                "risk_policy": risk_policy,
            }
        )
        next(state for state in states if state["source_node_id"] == source_id)["allowed_transition_ids"].append(transition_id)

    if reasons:
        return _blocked(reasons)
    approved_ids = sorted(reviewed_integrity)
    current_revision_hash = _canonical_sha256({node_id: reviewed_integrity[node_id]["canonical_revision_hash"] for node_id in approved_ids})
    evidence_sha256 = _canonical_sha256({node_id: reviewed_integrity[node_id]["expected_evidence_provenance"] for node_id in approved_ids})
    lineage = {
        "source_workflow_id": workflow_id,
        "source_workflow_path": source_path,
        "source_workflow_sha256": source_sha,
        "current_revision_hash": current_revision_hash,
        "reviewed_revision_hash": current_revision_hash,
        "human_approved_node_ids": approved_ids,
        "reviewed_by_human": True,
        "evidence_sha256": evidence_sha256,
    }
    asset = {
        "contract_version": "reviewed_workflow_asset_v2",
        "asset_id": _safe_id("workflow_", workflow_id),
        "application": _application_asset(identity),
        "source_review_lineage": lineage,
        "entry_state_id": state_ids[entry_node_id],
        "states": states,
        "transitions": transitions,
        "safety": {
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "final_submit_forbidden": True,
            "real_action_requires_gate": True,
            "fresh_grounding_required": True,
            "post_action_verification_required": True,
            "historical_coordinates_used": False,
        },
        "lifecycle": {"status": "compiled", "version": 2},
    }
    try:
        validated = validate_reviewed_workflow_asset(asset)
    except ValueError as exc:
        return _blocked([_reason("compiled_asset_invalid", str(exc))], lineage=lineage)
    try:
        if source.read_bytes() != source_bytes:
            return _blocked([_reason("source_workflow_changed_during_compile", "source bytes changed while compilation was in progress")], lineage=lineage)
    except OSError as exc:
        return _blocked([_reason("source_workflow_read_failed", str(exc))], lineage=lineage)
    return {
        "contract_version": _COMPILE_CONTRACT,
        "status": "compiled",
        "asset": validated,
        "source_review_lineage": deepcopy(lineage),
        "blocked_reasons": [],
    }
