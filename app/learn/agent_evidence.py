from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from app.learn.interface_assets import _merge_by_identifier, _project_human_described_regions


AGENT_EVIDENCE_CONTRACT = "agent_evidence_context_v1"
AGENT_EVIDENCE_MIGRATION_REPORT_CONTRACT = "agent_evidence_migration_report_v1"
_SUPPORTED_AGENT_ACTION_TYPES = {
    "back",
    "click",
    "close_modal",
    "continue_next_step",
    "fill_field",
    "input",
    "open_apply_flow",
    "open_detail",
    "open_filter",
    "open_link",
    "open_modal",
    "open_search",
    "read",
    "read_only",
    "scroll",
    "select",
    "select_option",
    "submit_search",
    "toggle_setting",
    "type_text",
    "wait",
}
_FORBIDDEN_ACTION_TYPES = {
    "confirm",
    "delete",
    "final_apply",
    "final_submit",
    "payment",
    "send",
    "submit",
}
_GEOMETRY_KEYS = {
    "actual_point",
    "bbox",
    "bounding_box",
    "click_point",
    "clickpoint",
    "coordinates",
    "expected_bbox",
    "expected_point",
    "point",
    "source_bbox",
    "viewport_size",
}


@dataclass(frozen=True)
class PersistedReviewRevision:
    """服务端持久化流程为单个节点提供的可信审核修订上下文。"""

    revision: dict[str, Any]
    revision_hash: str
    source_asset_sha256: str


def _trusted_review_revision_hash(
    persisted: PersistedReviewRevision | None,
) -> str:
    if not isinstance(persisted, PersistedReviewRevision):
        return ""
    claimed_hash = str(persisted.revision_hash or "").strip().lower()
    source_asset_sha256 = str(persisted.source_asset_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", claimed_hash) or not re.fullmatch(
        r"[0-9a-f]{64}", source_asset_sha256
    ):
        return ""
    canonical_payload = json.dumps(
        persisted.revision,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    canonical_hash = hashlib.sha256(canonical_payload.encode("utf-8")).hexdigest()
    return canonical_hash if canonical_hash == claimed_hash else ""


def build_agent_evidence_context(
    asset: dict[str, Any],
    *,
    outgoing_transitions: list[dict[str, Any]] | None = None,
    live_observation: dict[str, Any] | None = None,
    persisted_review_revision: PersistedReviewRevision | None = None,
) -> dict[str, Any]:
    """把学习资产编译为 Agent 可理解、但不授权执行的语义证据。"""

    if not isinstance(asset, dict) or asset.get("contract_version") != "single_interface_asset_v1":
        raise ValueError("agent evidence requires a single_interface_asset_v1 asset")

    normalized = _without_geometry(asset)
    interface_id = str(normalized.get("interface_id") or "").strip()
    if not interface_id:
        raise ValueError("agent evidence requires interface_id")

    review = normalized.get("review") if isinstance(normalized.get("review"), dict) else {}
    manual_revision = (
        review.get("manual_revision")
        if isinstance(review.get("manual_revision"), dict)
        else {}
    )
    responsibility = str(
        manual_revision.get("semantic_description")
        or manual_revision.get("agent_description")
        or normalized.get("agent_description")
        or ""
    ).strip()

    fixed_anchors = _semantic_content(normalized.get("fixed_anchors"), live_values={})
    live_values, observation_meta = _live_values(
        live_observation,
        interface_id=interface_id,
    )
    dynamic_content = _semantic_content(
        normalized.get("dynamic_slots"),
        live_values=live_values,
        observation_meta=observation_meta,
    )
    deferred_reads = [
        item
        for item in dynamic_content
        if item.get("read_policy") == "on_demand"
        or item.get("observation_status") == "requires_observation"
    ]

    controls = _semantic_controls(normalized.get("controls"))
    control_ids = {
        str(item.get("control_id") or "")
        for item in controls
        if str(item.get("control_id") or "")
    }
    available_actions, forbidden_actions, actions_needing_review = _semantic_actions(
        normalized.get("action_candidates"),
        outgoing_transitions=outgoing_transitions or [],
        control_ids=control_ids,
        interface_id=interface_id,
    )
    (
        controls,
        available_actions,
        control_actions_needing_review,
    ) = _link_actionable_control_semantics(controls, available_actions)
    actions_needing_review.extend(control_actions_needing_review)

    referenced_ids = {
        str(item.get("source_id") or "")
        for item in [*fixed_anchors, *dynamic_content]
        if str(item.get("source_id") or "")
    }
    legacy_candidates, legacy_summary = _legacy_candidates(
        normalized.get("regions"),
        referenced_ids=referenced_ids,
    )

    missing_fields: list[str] = []
    if not responsibility:
        missing_fields.append("interface_responsibility")
    if not fixed_anchors:
        missing_fields.append("identity_anchor")
    if not fixed_anchors and not dynamic_content:
        missing_fields.append("semantic_content")
    terminal_safe_stop = _has_reviewed_terminal_safe_stop(
        blockers=normalized.get("blockers"),
        verification_rules=normalized.get("verification_rules"),
    )
    if not available_actions and not deferred_reads and not terminal_safe_stop:
        missing_fields.append("action_semantics")
    if actions_needing_review:
        missing_fields.append("action_linkage")
    if control_actions_needing_review:
        missing_fields.append("control_semantics")
    reviewed_revision_hash = str(review.get("reviewed_revision_hash") or "").strip()
    current_revision_hash = str(review.get("current_revision_hash") or "").strip()
    if (
        str(review.get("status") or "") != "human_approved"
        or review.get("reviewed_by_human") is not True
    ):
        missing_fields.append("human_approval")
    trusted_revision_hash = _trusted_review_revision_hash(persisted_review_revision)
    if not (
        trusted_revision_hash
        and reviewed_revision_hash == trusted_revision_hash
        and current_revision_hash == trusted_revision_hash
    ):
        missing_fields.append("human_review_revision")

    readiness_status = "agent_usable" if not missing_fields else "needs_human_review"
    evidence = normalized.get("evidence") if isinstance(normalized.get("evidence"), dict) else {}
    evidence_refs = {
        key: value
        for key, value in evidence.items()
        if key.endswith("_path") and isinstance(value, str) and value.strip()
    }

    return {
        "contract_version": AGENT_EVIDENCE_CONTRACT,
        "interface": {
            "interface_id": interface_id,
            "application_identity_key": str(
                normalized.get("application_identity_key") or ""
            ),
            "display_name": str(normalized.get("display_name") or interface_id),
            "surface_type": str(normalized.get("surface_type") or "unknown_surface"),
            "state_signature": str(normalized.get("state_signature") or interface_id),
            "responsibility": responsibility,
            "review_status": str(review.get("status") or "needs_human_review"),
        },
        "identity_anchors": fixed_anchors,
        "dynamic_content": dynamic_content,
        "deferred_reads": deferred_reads,
        "semantic_controls": controls,
        "available_actions": available_actions,
        "actions_needing_review": actions_needing_review,
        "forbidden_actions": forbidden_actions,
        "states": _dict_list(normalized.get("states")),
        "verification_rules": _dict_list(normalized.get("verification_rules")),
        "blockers": _dict_list(normalized.get("blockers")),
        "legacy_recognition_candidates": legacy_candidates,
        "legacy_candidate_summary": legacy_summary,
        "evidence_refs": evidence_refs,
        "readiness": {
            "status": readiness_status,
            "lifecycle_stage": readiness_status,
            "missing_fields": missing_fields,
            "legacy_inferred": bool(legacy_candidates),
            "counts": {
                "identity_anchors": len(fixed_anchors),
                "dynamic_content": len(dynamic_content),
                "semantic_controls": len(controls),
                "available_actions": len(available_actions),
                "forbidden_actions": len(forbidden_actions),
                "legacy_recognition_candidates": legacy_summary["total"],
            },
        },
        "live_observation": observation_meta,
        "execution_contract": {
            "observe_before_decision": True,
            "current_capture_required": True,
            "current_target_resolution_required": True,
            "historical_coordinates_forbidden": True,
            "gate_required": True,
            "operation_required": True,
            "trace_required": True,
            "post_action_verification_required": True,
            "final_submit_forbidden": True,
        },
        "projection_contract": {
            "projection_is_read_only": True,
            "authoritative_source": "server_persisted_canonical_workflow_revision",
            "reverse_write_forbidden": True,
            "evidence_reference_expansion_for_agent_forbidden": True,
        },
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _has_reviewed_terminal_safe_stop(
    *,
    blockers: Any,
    verification_rules: Any,
) -> bool:
    """仅把同时具备阻断证据和停止验证规则的终态视为完整语义。"""

    has_blocker = any(
        item.get("safe_stop_required") is True
        for item in _dict_list(blockers)
    )
    has_stop_rule = any(
        str(item.get("expected_decision") or "").strip().casefold() == "safe_stop"
        for item in _dict_list(verification_rules)
    )
    return has_blocker and has_stop_rule


def build_workflow_agent_evidence(
    review: dict[str, Any],
    *,
    persisted_review_revisions: Mapping[str, PersistedReviewRevision] | None = None,
) -> dict[str, Any]:
    """把审核流程节点编译为通用 Agent 证据图。"""

    if (
        not isinstance(review, dict)
        or review.get("contract_version") != "single_application_workflow_review_v1"
    ):
        raise ValueError("workflow agent evidence requires a reviewed workflow")
    workflow = review.get("workflow") if isinstance(review.get("workflow"), dict) else {}
    application_identity = (
        workflow.get("application_identity")
        if isinstance(workflow.get("application_identity"), dict)
        else {}
    )
    identity_key = str(
        application_identity.get("identity_key")
        or workflow.get("application_identity_key")
        or ""
    ).strip()

    edges = _dict_list(review.get("edges"))
    interfaces: list[dict[str, Any]] = []
    for node in _dict_list(review.get("nodes")):
        interface_id = str(node.get("node_id") or node.get("interface_id") or "").strip()
        if not interface_id:
            continue
        regions = _dict_list(node.get("regions"))
        projected = _project_human_described_regions(regions)
        for action in projected["action_candidates"]:
            action["review_status"] = "human_approved"
        controls = _merge_by_identifier(
            _dict_list(node.get("controls")), projected["controls"],
            keys=("control_id", "element_id", "region_id"),
        )
        action_candidates = _merge_by_identifier(
            _dict_list(node.get("action_candidates") or node.get("action_templates")),
            projected["action_candidates"],
            keys=("action_template_id", "action_id"),
        )
        verification_rules = _merge_by_identifier(
            _dict_list(node.get("verification_rules")), projected["verification_rules"],
            keys=("rule_id",),
        )
        pseudo_asset = {
            "contract_version": "single_interface_asset_v1",
            "interface_id": interface_id,
            "application_identity_key": identity_key,
            "application_identity": deepcopy(application_identity),
            "display_name": str(node.get("display_name") or interface_id),
            "surface_type": str(node.get("surface_type") or "unknown_surface"),
            "state_signature": str(node.get("state_signature") or interface_id),
            "agent_description": str(node.get("agent_description") or "").strip(),
            "evidence": _without_geometry(node.get("evidence") or {}),
            "fixed_anchors": _descriptor_bucket(
                node.get("content_descriptors"),
                fixed=True,
            ),
            "dynamic_slots": _descriptor_bucket(
                node.get("content_descriptors"),
                fixed=False,
            ),
            "states": _dict_list(node.get("states")),
            "regions": regions,
            "controls": controls,
            "action_candidates": action_candidates,
            "verification_rules": verification_rules,
            "blockers": _dict_list(node.get("blockers")),
            "review": {
                "status": str(node.get("review_status") or "needs_human_review"),
                "reviewed_by_human": node.get("reviewed_by_human") is True,
                "reviewed_revision_hash": str(
                    node.get("reviewed_revision_hash") or ""
                ).strip(),
                "current_revision_hash": str(
                    node.get("current_revision_hash") or ""
                ).strip(),
                "manual_revision": _without_geometry(node.get("manual_revision") or {}),
            },
        }
        outgoing = [
            _workflow_edge_as_transition(
                edge,
                action_candidates=action_candidates,
            )
            for edge in edges
            if str(edge.get("source_node_id") or "") == interface_id
        ]
        interfaces.append(
            build_agent_evidence_context(
                pseudo_asset,
                outgoing_transitions=outgoing,
                persisted_review_revision=(persisted_review_revisions or {}).get(
                    interface_id
                ),
            )
        )

    return {
        "contract_version": "workflow_agent_evidence_v1",
        "workflow_id": str(workflow.get("workflow_id") or ""),
        "goal": str(workflow.get("goal") or ""),
        "entry_interface_id": str(
            workflow.get("entry_node_id")
            or workflow.get("entry_interface_id")
            or ""
        ),
        "interfaces": interfaces,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def load_application_agent_evidence_context(
    application_identity_key: str,
    *,
    project_root: str | Path,
    interface_id: str | None = None,
) -> dict[str, Any]:
    """加载一个软件的 Agent 语义证据，界面图仍不提供执行授权。"""

    from app.learn.application_interface_graph import load_application_interface_graph
    from app.learn.interface_assets import load_application_interface_library

    identity_key = str(application_identity_key or "").strip()
    if not identity_key:
        raise ValueError("application identity key is required")
    library = load_application_interface_library(
        identity_key,
        project_root=project_root,
    )
    graph = load_application_interface_graph(
        identity_key,
        project_root=project_root,
    )
    requested_interface_id = str(interface_id or "").strip()
    assets = [
        item
        for item in library.get("interfaces", [])
        if isinstance(item, dict)
        and (
            not requested_interface_id
            or str(item.get("interface_id") or "") == requested_interface_id
        )
    ]
    if requested_interface_id and not assets:
        raise ValueError(
            f"application interface not found: {requested_interface_id}"
        )

    transitions = _dict_list(graph.get("transitions"))
    contexts = [
        build_agent_evidence_context(
            asset,
            outgoing_transitions=[
                transition
                for transition in transitions
                if str(transition.get("source_interface_id") or "")
                == str(asset.get("interface_id") or "")
            ],
        )
        for asset in assets
    ]
    return {
        "contract_version": "application_agent_evidence_context_v1",
        "application_identity_key": identity_key,
        "application_identity": deepcopy(library.get("application_identity") or {}),
        "entry_interface_id": str(graph.get("entry_interface_id") or ""),
        "interface_count": len(contexts),
        "interfaces": contexts,
        "readiness_summary": {
            "agent_usable": sum(
                item["readiness"]["status"] == "agent_usable"
                for item in contexts
            ),
            "needs_human_review": sum(
                item["readiness"]["status"] != "agent_usable"
                for item in contexts
            ),
        },
        "execution_contract": {
            "observe_before_decision": True,
            "current_capture_required": True,
            "current_target_resolution_required": True,
            "gate_required": True,
            "operation_required": True,
            "trace_required": True,
            "post_action_verification_required": True,
            "final_submit_forbidden": True,
        },
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def migrate_agent_evidence_assets(
    *,
    project_root: str | Path,
    application_identity_key: str | None = None,
    persisted_review_revisions: Mapping[str, PersistedReviewRevision] | None = None,
) -> dict[str, Any]:
    """为旧界面资产生成旁路 Agent 证据，不修改原始 interface.json。"""

    root = Path(project_root).resolve()
    asset_root = root / "artifacts" / "interface-assets"
    pattern = (
        f"{_safe_path_segment(application_identity_key)}/interfaces/*/interface.json"
        if application_identity_key
        else "*/interfaces/*/interface.json"
    )
    records: list[dict[str, Any]] = []
    usable_count = 0
    needs_review_count = 0

    for asset_path in sorted(asset_root.glob(pattern)):
        original_bytes = asset_path.read_bytes()
        try:
            payload = json.loads(original_bytes.decode("utf-8-sig"))
            identity_key = str(payload.get("application_identity_key") or "")
            transitions = _load_transitions_for_interface(
                asset_root=asset_root,
                application_identity_key=identity_key,
                interface_id=str(payload.get("interface_id") or ""),
            )
            context = build_agent_evidence_context(
                payload,
                outgoing_transitions=transitions,
                persisted_review_revision=(persisted_review_revisions or {}).get(
                    str(payload.get("interface_id") or "").strip()
                ),
            )
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            records.append(
                {
                    "asset_path": asset_path.relative_to(root).as_posix(),
                    "status": "invalid",
                    "error": str(exc),
                }
            )
            continue

        output_path = asset_path.with_name("agent_evidence.json")
        output_bytes = _json_bytes(context)
        _atomic_write(output_path, output_bytes)
        status = context["readiness"]["status"]
        if status == "agent_usable":
            usable_count += 1
        else:
            needs_review_count += 1
        records.append(
            {
                "interface_id": context["interface"]["interface_id"],
                "application_identity_key": identity_key,
                "asset_path": asset_path.relative_to(root).as_posix(),
                "agent_evidence_path": output_path.relative_to(root).as_posix(),
                "agent_evidence_sha256": hashlib.sha256(output_bytes).hexdigest(),
                "status": status,
                "missing_fields": context["readiness"]["missing_fields"],
                "legacy_candidate_count": context["legacy_candidate_summary"]["total"],
                "source_asset_unchanged": asset_path.read_bytes() == original_bytes,
            }
        )

    return {
        "contract_version": AGENT_EVIDENCE_MIGRATION_REPORT_CONTRACT,
        "asset_count": len(records),
        "agent_usable_count": usable_count,
        "needs_human_review_count": needs_review_count,
        "invalid_count": sum(item.get("status") == "invalid" for item in records),
        "records": records,
        "artifact_is_authorization": False,
    }


def _semantic_content(
    value: Any,
    *,
    live_values: dict[str, Any],
    observation_meta: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in _dict_list(value):
        content_id = str(raw.get("content_id") or "").strip()
        if not content_id:
            continue
        item = {
            "content_id": content_id,
            "label": str(raw.get("label") or content_id),
            "source_kind": str(raw.get("source_kind") or "unknown"),
            "source_id": str(raw.get("source_id") or ""),
            "content_behavior": str(raw.get("content_behavior") or ""),
            "agent_usage": str(raw.get("agent_usage") or ""),
            "read_policy": str(raw.get("read_policy") or ""),
            "agent_description": str(raw.get("agent_description") or ""),
        }
        read_strategy = str(raw.get("read_strategy") or "").strip()
        if not read_strategy:
            read_strategy = (
                "infinite_collection"
                if item["content_behavior"] == "dynamic_collection"
                else "finite_detail"
            )
            item["read_strategy_source"] = "inferred_from_content_behavior"
        else:
            item["read_strategy_source"] = "reviewed_asset"
        item["read_strategy"] = read_strategy
        item["completion_policy"] = str(
            raw.get("completion_policy")
            or (
                "budget_or_no_new_content"
                if read_strategy == "infinite_collection"
                else "reached_bottom_required"
            )
        )
        for field_name in ("max_scrolls", "max_items", "wheel_clicks"):
            try:
                limit = int(raw.get(field_name))
            except (TypeError, ValueError):
                continue
            if limit > 0:
                item[field_name] = limit
        for field_name in ("scroll_scope", "target_pane"):
            field_value = str(raw.get(field_name) or "").strip()
            if field_value:
                item[field_name] = field_value
        bottom_markers = [
            str(marker).strip()
            for marker in raw.get("bottom_markers") or []
            if str(marker).strip()
        ]
        if bottom_markers:
            item["bottom_markers"] = bottom_markers
        if item["content_behavior"] in {
            "dynamic_collection",
            "dynamic_value",
            "ephemeral",
            "sensitive_dynamic",
            "user_input",
        }:
            if content_id not in live_values:
                item["observation_status"] = "requires_observation"
            elif item["content_behavior"] == "sensitive_dynamic":
                serialized = _canonical_value(live_values[content_id])
                item["observation_status"] = "current_redacted"
                item["value_length"] = len(serialized)
                item["value_sha256"] = hashlib.sha256(
                    serialized.encode("utf-8")
                ).hexdigest()
            else:
                item["observation_status"] = "current"
                item["value"] = deepcopy(live_values[content_id])
            if observation_meta and observation_meta.get("status") == "current":
                item["capture_id"] = observation_meta["capture_id"]
                item["observed_at"] = observation_meta["observed_at"]
        result.append(item)
    return result


def _semantic_controls(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for raw in _dict_list(value):
        control_id = str(
            raw.get("control_id") or raw.get("element_id") or raw.get("region_id") or ""
        ).strip()
        if not control_id:
            continue
        control = {
            "control_id": control_id,
            "semantic_name": str(
                raw.get("semantic_name")
                or raw.get("label")
                or raw.get("name")
                or ""
            ).strip(),
            "purpose": str(
                raw.get("purpose")
                or raw.get("agent_description")
                or ""
            ).strip(),
            "role": str(raw.get("role") or raw.get("control_type") or "unknown"),
            "allowed_actions": [],
            "verification_rule": {
                "rule_ids": [],
                "success_conditions": [],
            },
            "risk_class": str(
                raw.get("risk_class") or raw.get("risk_level") or "unknown"
            ).strip()
            or "unknown",
            "review_status": str(raw.get("review_status") or "needs_human_review"),
            "requires_fresh_grounding": True,
        }
        visible_text_anchors = list(
            dict.fromkeys(
                str(anchor).strip()
                for anchor in raw.get("visible_text_anchors") or []
                if str(anchor).strip()
            )
        )
        if visible_text_anchors:
            control["visible_text_anchors"] = visible_text_anchors
        result.append(control)
    return result


def _link_actionable_control_semantics(
    controls: list[dict[str, Any]],
    actions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """把动作投影到语义控件；语义不完整的控件不得进入 Agent 可用动作。"""

    controls_by_id = {
        str(control.get("control_id") or ""): control
        for control in controls
        if str(control.get("control_id") or "")
    }
    available: list[dict[str, Any]] = []
    needs_review: list[dict[str, Any]] = []

    for action in actions:
        source_control_id = str(action.get("source_control_id") or "")
        control = controls_by_id.get(source_control_id)
        missing: list[str] = []
        if not control or not str(control.get("semantic_name") or "").strip():
            missing.append("source_control_semantic_name")
        if not control or not str(control.get("purpose") or "").strip():
            missing.append("source_control_purpose")
        if missing:
            item = deepcopy(action)
            item["missing_fields"] = missing
            needs_review.append(item)
            continue

        action_type = _normalize_action_type(str(action.get("action_type") or ""))
        allowed_actions = control["allowed_actions"]
        if action_type and action_type not in allowed_actions:
            allowed_actions.append(action_type)

        verification = control["verification_rule"]
        for rule_id in action.get("verification_rule_ids") or []:
            normalized_rule_id = str(rule_id).strip()
            if normalized_rule_id and normalized_rule_id not in verification["rule_ids"]:
                verification["rule_ids"].append(normalized_rule_id)
        for condition in action.get("success_conditions") or []:
            normalized_condition = str(condition).strip()
            if (
                normalized_condition
                and normalized_condition not in verification["success_conditions"]
            ):
                verification["success_conditions"].append(normalized_condition)

        risk_level = str(action.get("risk_level") or "unknown").strip()
        if risk_level and risk_level != "unknown":
            control["risk_class"] = risk_level
        elif control.get("risk_class") == "unknown":
            control["risk_class"] = _default_action_risk(action_type)
        available.append(action)

    return controls, available, needs_review


def _default_action_risk(action_type: str) -> str:
    if action_type in {
        "back",
        "close_modal",
        "open_detail",
        "open_filter",
        "open_link",
        "open_modal",
        "open_search",
        "read",
        "read_only",
        "scroll",
        "wait",
    }:
        return "low"
    return "unknown"


def _semantic_actions(
    value: Any,
    *,
    outgoing_transitions: list[dict[str, Any]],
    control_ids: set[str],
    interface_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    available: list[dict[str, Any]] = []
    forbidden: list[dict[str, Any]] = []
    needs_review: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    raw_actions = [
        *_dict_list(outgoing_transitions),
        *_dict_list(value),
    ]
    for raw in raw_actions:
        action_type = str(
            raw.get("action_type")
            or raw.get("semantic_action")
            or raw.get("operation")
            or ""
        ).strip()
        source_control_id = str(
            raw.get("source_control_id")
            or raw.get("target_control_id")
            or raw.get("target_region_id")
            or ""
        ).strip()
        target_interface_id = str(
            raw.get("target_interface_id") or raw.get("target_node_id") or ""
        ).strip()
        description = str(
            raw.get("agent_description")
            or raw.get("description")
            or raw.get("display_name")
            or ""
        ).strip()
        item = {
            "action_id": str(
                raw.get("transition_id")
                or raw.get("action_template_id")
                or raw.get("action_id")
                or action_type
            ),
            "action_type": action_type,
            "display_name": str(raw.get("display_name") or action_type),
            "agent_description": description,
            "source_interface_id": str(
                raw.get("source_interface_id") or interface_id
            ),
            "source_control_id": source_control_id,
            "target_interface_id": target_interface_id,
            "risk_level": str(raw.get("risk_level") or "unknown"),
            "review_status": str(raw.get("review_status") or "needs_human_review"),
            "success_conditions": list(raw.get("success_conditions") or []),
            "verification_rule_ids": list(raw.get("verification_rule_ids") or []),
            "operation_goal": str(
                raw.get("operation_goal")
                or raw.get("agent_description")
                or raw.get("display_name")
                or action_type
            ),
            "requires_completed_read": str(
                raw.get("requires_completed_read") or ""
            ).strip()
            or None,
            "requires_fresh_grounding": True,
            "gate_required": True,
            "automatic_execution_allowed": False,
        }
        key = (action_type, source_control_id, target_interface_id)
        if key in seen:
            continue
        seen.add(key)
        if _is_forbidden_action(action_type):
            item["blocked_reason"] = "unsafe_or_final_action"
            forbidden.append(item)
            continue
        missing: list[str] = []
        if not action_type:
            missing.append("action_type")
        elif _normalize_action_type(action_type) not in _SUPPORTED_AGENT_ACTION_TYPES:
            missing.append("supported_action_type")
        if not source_control_id:
            missing.append("source_control_id")
        elif source_control_id not in control_ids:
            missing.append("known_source_control")
        if not description:
            missing.append("agent_description")
        if item["review_status"] != "human_approved":
            missing.append("human_approval")
        if missing:
            item["missing_fields"] = missing
            needs_review.append(item)
            continue
        available.append(item)
    return available, forbidden, needs_review


def _legacy_candidates(
    value: Any,
    *,
    referenced_ids: set[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for raw in _dict_list(value):
        region_id = str(raw.get("region_id") or raw.get("node_id") or "").strip()
        if not region_id or region_id in referenced_ids:
            continue
        candidates.append(
            {
                "evidence_id": region_id,
                "label": str(raw.get("label") or raw.get("name") or region_id),
                "hierarchy_level": str(
                    raw.get("hierarchy_level") or raw.get("level") or "unknown"
                ),
                "role": str(raw.get("role") or raw.get("component_type") or "unknown"),
                "parent_evidence_id": str(
                    raw.get("parent_region_id") or raw.get("parent_id") or ""
                ),
                "review_status": str(raw.get("review_status") or "review_only"),
                "semantic_status": "requires_human_semantics",
                "actionable": False,
            }
        )
    total = len(candidates)
    included = candidates[:50]
    return included, {
        "total": total,
        "included": len(included),
        "truncated": total > len(included),
        "interpretation": "legacy recognition evidence only; not an action source",
    }


def _live_values(
    value: dict[str, Any] | None,
    *,
    interface_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if value is None:
        return {}, {
            "status": "not_provided",
            "capture_id": None,
            "observed_at": None,
        }
    if not isinstance(value, dict) or value.get("contract_version") != "live_interface_observation_v1":
        raise ValueError("live interface observation has an unsupported contract")
    if str(value.get("interface_id") or "") != interface_id:
        raise ValueError("live interface observation interface identity mismatch")
    capture_id = str(value.get("capture_id") or "").strip()
    observed_at = str(value.get("observed_at") or "").strip()
    values = value.get("values_by_content_id")
    if not capture_id or not observed_at or not isinstance(values, dict):
        raise ValueError("live interface observation is incomplete")
    return deepcopy(values), {
        "status": "current",
        "capture_id": capture_id,
        "observed_at": observed_at,
    }


def _descriptor_bucket(value: Any, *, fixed: bool) -> list[dict[str, Any]]:
    fixed_behaviors = {"fixed_label", "fixed_structure"}
    return [
        item
        for item in _dict_list(value)
        if (str(item.get("content_behavior") or "") in fixed_behaviors) is fixed
    ]


def _workflow_edge_as_transition(
    edge: dict[str, Any],
    *,
    action_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    source_control_id = str(
        edge.get("source_control_id")
        or edge.get("target_control_id")
        or edge.get("control_id")
        or ""
    )
    action_type = str(edge.get("action_type") or "")
    target_interface_id = str(edge.get("target_node_id") or "")
    matched_candidate = next(
        (
            candidate
            for candidate in action_candidates or []
            if str(
                candidate.get("semantic_action")
                or candidate.get("action_type")
                or candidate.get("operation")
                or ""
            )
            == action_type
            and str(
                candidate.get("target_control_id")
                or candidate.get("source_control_id")
                or candidate.get("target_region_id")
                or ""
            )
            == source_control_id
            and str(candidate.get("target_interface_id") or target_interface_id)
            == target_interface_id
        ),
        {},
    )
    return {
        "transition_id": str(edge.get("edge_id") or edge.get("transition_id") or ""),
        "source_interface_id": str(edge.get("source_node_id") or ""),
        "target_interface_id": target_interface_id,
        "source_control_id": source_control_id,
        "action_type": action_type,
        "display_name": str(edge.get("display_name") or ""),
        "agent_description": str(edge.get("agent_description") or ""),
        "risk_level": str(edge.get("risk_level") or "unknown"),
        "review_status": str(edge.get("review_status") or "needs_human_review"),
        "success_conditions": list(edge.get("success_conditions") or []),
        "operation_goal": str(matched_candidate.get("operation_goal") or ""),
        "requires_completed_read": str(
            matched_candidate.get("requires_completed_read") or ""
        ),
    }


def _load_transitions_for_interface(
    *,
    asset_root: Path,
    application_identity_key: str,
    interface_id: str,
) -> list[dict[str, Any]]:
    if not application_identity_key or not interface_id:
        return []
    graph_path = asset_root / _safe_path_segment(application_identity_key) / "graph.json"
    if not graph_path.is_file():
        return []
    graph = json.loads(graph_path.read_text(encoding="utf-8-sig"))
    if graph.get("contract_version") != "application_interface_graph_v1":
        raise ValueError("application interface graph has an unsupported contract")
    return [
        item
        for item in _dict_list(graph.get("transitions"))
        if str(item.get("source_interface_id") or "") == interface_id
    ]


def _is_forbidden_action(action_type: str) -> bool:
    normalized = _normalize_action_type(action_type)
    return normalized in _FORBIDDEN_ACTION_TYPES or any(
        token in normalized
        for token in (
            "complete_application",
            "confirm_purchase",
            "final_apply",
            "final_submit",
            "payment",
            "place_order",
            "purchase",
            "send_application",
            "send_message",
            "submit_application",
        )
    )


def _normalize_action_type(action_type: str) -> str:
    return action_type.strip().casefold().replace("-", "_").replace(" ", "_")


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        _without_geometry(item)
        for item in value
        if isinstance(item, dict)
    ]


def _without_geometry(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _without_geometry(item)
            for key, item in value.items()
            if str(key).replace("-", "_").casefold() not in _GEOMETRY_KEYS
        }
    if isinstance(value, list):
        return [_without_geometry(item) for item in value]
    return deepcopy(value)


def _canonical_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _safe_path_segment(value: str | None) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "")).strip("._-")
    if not cleaned:
        raise ValueError("application identity key is not a safe path segment")
    return cleaned[:120]


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            default=str,
        )
        + "\n"
    ).encode("utf-8")


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)
