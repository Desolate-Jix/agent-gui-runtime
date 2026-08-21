"""Web reference adapter from server-trusted reviewed evidence to AgentObservationV1."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from app.agent.reviewed_workflow_asset import content_sha256, validate_reviewed_workflow_asset
from app.agent.reviewed_workflow_replay import resolve_current_state
from app.agent.runtime_contracts import AgentObservationV1, validate_agent_observation_v1
from app.learn.interface_workflow_review import load_interface_workflow_agent_context


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _as_list(value: object) -> list[Mapping[str, Any]]:
    return [item for item in value or [] if isinstance(item, Mapping)]


def _expected_application_key(application: Mapping[str, Any]) -> str:
    if application.get("kind") == "web":
        domain = str(application.get("canonical_domain") or "").strip()
        if domain:
            return f"web:{domain}"
    raise ValueError("reviewed asset application identity is unsupported")


def _safe_stop_action() -> dict[str, object]:
    return {
        "action_id": "runtime.safe_stop",
        "semantic_action": "safe_stop",
        "description": "Stop without dispatching another action.",
        "target_state_id": None,
        "expected_effect": "Stop without dispatching another action.",
        "verification_rule_refs": [],
        "risk_level": "low",
        "requires_user_confirmation": False,
    }


def _safe_blocker(reason: str, evidence_refs: list[str]) -> dict[str, object]:
    return {
        "blocker_id": f"blocker.{reason}",
        "blocker_type": "state",
        "description": f"Runtime requires safe stop: {reason}.",
        "safe_stop_required": True,
        "evidence_refs": evidence_refs,
    }


def _content_ref(source_sha: str, *identity: str) -> str:
    digest = hashlib.sha256(
        ":".join(identity).encode("utf-8")
    ).hexdigest()
    return f"content-sha256:{source_sha}:{digest}"


def _stable_suffix(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._:-]+", "-", value).strip(".-:")
    return normalized[:96] or fallback


def _capture_bound_refs(
    asset_sha: str,
    current_observation: Mapping[str, Any],
    resolution: Mapping[str, Any],
) -> tuple[str, str, list[str]]:
    capture_id = str(current_observation.get("capture_id") or "")
    screenshot_sha = str(current_observation.get("screenshot_sha256") or "")
    viewport = current_observation.get("viewport_size")
    capture_ref = _content_ref(
        asset_sha,
        "capture",
        capture_id,
        screenshot_sha,
        json.dumps(viewport, sort_keys=True, separators=(",", ":")),
    )
    anchor_bindings = sorted(
        (
            str(item.get("anchor_id") or ""),
            str(item.get("matched")),
            str(item.get("confidence")),
        )
        for item in current_observation.get("observed_anchor_evidence") or []
        if isinstance(item, Mapping)
    )
    resolution_binding = {
        key: value
        for key, value in resolution.items()
        if key not in {"evidence_refs", "resolution_sha256"}
    }
    resolution_ref = _content_ref(
        asset_sha,
        "state-resolution",
        json.dumps(resolution_binding, sort_keys=True, separators=(",", ":")),
        json.dumps(anchor_bindings, separators=(",", ":")),
    )
    anchor_refs = [
        _content_ref(asset_sha, "anchor", capture_id, screenshot_sha, *binding)
        for binding in anchor_bindings
    ]
    return resolution_ref, capture_ref, anchor_refs


def _fact_payloads(
    interface: Mapping[str, Any],
    *,
    current_capture_id: str,
) -> tuple[list[dict[str, object]], list[str]]:
    facts: list[dict[str, object]] = []
    refs: list[str] = []
    for source, fact_type in (("identity_anchors", "identity_anchor"), ("dynamic_content", "current_content")):
        for item in _as_list(interface.get(source)):
            source_id = str(item.get("content_id") or item.get("source_id") or "").strip()
            label = str(item.get("label") or item.get("description") or "").strip()
            if not source_id or not label:
                continue
            status = str(item.get("observation_status") or "").strip()
            if fact_type == "identity_anchor":
                status = "reviewed"
            elif status not in {"current", "current_redacted", "requires_observation"}:
                status = "requires_observation"
            if status in {"current", "current_redacted"} and str(item.get("capture_id") or "") != current_capture_id:
                status = "requires_observation"
            value = item.get("value")
            if fact_type == "identity_anchor" and not isinstance(value, str):
                value = label
            if status in {"current_redacted", "requires_observation"}:
                value = None
            elif isinstance(value, str):
                value = " ".join(value.split())
                if not value or len(value) > 512:
                    status = "requires_observation"
                    value = None
            else:
                status = "requires_observation"
                value = None
            source_sha = str(interface.get("source_asset_sha256") or "")
            evidence_refs = [_content_ref(source_sha, "fact", source_id, label)]
            capture_id = current_capture_id if status in {"current", "current_redacted"} else None
            value_sha256 = None
            if status == "current_redacted":
                value_sha256 = str(item.get("value_sha256") or "").lower()
                if not re.fullmatch(r"[0-9a-f]{64}", value_sha256):
                    status, capture_id, value_sha256 = "requires_observation", None, None
            facts.append({
                "fact_id": f"fact.{source_id}", "fact_type": fact_type, "label": label,
                "value": value, "observation_status": status, "capture_id": capture_id,
                "value_sha256": value_sha256, "evidence_refs": evidence_refs,
            })
            refs.extend(evidence_refs)
    return facts, refs


def _find_interface(context: Mapping[str, Any], *, workflow_id: str, source_node_id: str) -> Mapping[str, Any] | None:
    matches: list[Mapping[str, Any]] = []
    for workflow in _as_list(context.get("agent_evidence_workflows")):
        if str(workflow.get("workflow_id") or "") != workflow_id:
            continue
        if workflow.get("contract_version") != "workflow_agent_evidence_v1":
            raise ValueError("invalid workflow agent evidence contract")
        for interface in _as_list(workflow.get("interfaces")):
            if interface.get("contract_version") != "agent_evidence_context_v1":
                raise ValueError("invalid interface agent evidence contract")
            metadata = _mapping(interface.get("interface"), "interface evidence metadata")
            if str(metadata.get("interface_id") or "") == source_node_id:
                matches.append(interface)
    if len(matches) > 1:
        raise ValueError("reviewed state must map to exactly one evidence interface")
    return matches[0] if matches else None


def _trusted_reviewed_blockers(
    context: Mapping[str, Any],
    *,
    workflow_id: str,
    source_node_id: str,
    projected: object,
) -> list[Mapping[str, Any]]:
    workflow_matches = [
        item
        for item in _as_list(context.get("workflows"))
        if str((item.get("workflow") or {}).get("workflow_id") or "") == workflow_id
    ]
    if len(workflow_matches) != 1:
        raise ValueError("reviewed blocker workflow integrity mismatch")
    workflow = workflow_matches[0]
    if workflow.get("contract_version") != "single_application_workflow_review_v1":
        raise ValueError("reviewed blocker workflow contract mismatch")
    node_matches = [
        item
        for item in _as_list(workflow.get("nodes"))
        if str(item.get("node_id") or "") == source_node_id
    ]
    if len(node_matches) != 1:
        raise ValueError("reviewed blocker node integrity mismatch")
    raw = node_matches[0].get("blockers")
    if not isinstance(raw, list):
        raise ValueError("reviewed blockers must be an array")
    blockers: list[Mapping[str, Any]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise ValueError("reviewed blocker must be an object")
        if type(item.get("safe_stop_required")) is not bool:
            raise ValueError("reviewed blocker safe_stop_required must be boolean")
        blockers.append(item)
    projected_items = _as_list(projected)
    if len(projected_items) != len(blockers):
        raise ValueError("reviewed blocker projection integrity mismatch")
    return blockers


def adapt_reviewed_context_to_agent_observation_v1(
    *,
    observation_id: str,
    session_id: str,
    workflow_id: str,
    reviewed_asset: Mapping[str, Any],
    current_observation: Mapping[str, Any],
    state_resolution: Mapping[str, Any],
    project_root: str | Path,
    application_identity_key: str,
) -> AgentObservationV1:
    """Build a geometry-free web observation from canonical reviewed evidence only."""
    asset = validate_reviewed_workflow_asset(reviewed_asset)
    expected_resolution = resolve_current_state(asset, current_observation)
    if dict(state_resolution) != expected_resolution:
        raise ValueError("state resolution does not match current authoritative resolution")
    context = load_interface_workflow_agent_context(
        project_root=Path(project_root), application_identity_key=application_identity_key,
    )
    if context.get("contract_version") != "interface_workflow_agent_context_v1":
        raise ValueError("invalid interface workflow agent context")
    if context.get("artifact_is_authorization") is not False or context.get("execute_binding_enabled") is not False:
        raise ValueError("interface workflow context must be non-authorizing")

    application = _mapping(asset.get("application"), "reviewed asset application")
    application_key = _expected_application_key(application)
    context_application = _mapping(context.get("application_identity"), "context application identity")
    if application_identity_key != application_key or str(context.get("application_identity_key") or "") != application_key or str(context_application.get("identity_key") or "") != application_key:
        raise ValueError("application identity mismatch")

    lineage = _mapping(asset.get("source_review_lineage"), "reviewed asset lineage")
    asset_hash = content_sha256(asset)
    workflow = {
        "workflow_id": workflow_id,
        "asset_id": asset["asset_id"],
        "asset_content_sha256": asset_hash,
        "source_workflow_sha256": lineage["source_workflow_sha256"],
        "reviewed_revision_hash": lineage["reviewed_revision_hash"],
    }
    capture = _mapping(expected_resolution.get("capture_lineage"), "state resolution capture lineage")
    state_resolution_ref, current_capture_evidence_ref, anchor_refs = _capture_bound_refs(
        asset_hash,
        current_observation,
        expected_resolution,
    )
    evidence_refs = [state_resolution_ref, current_capture_evidence_ref, *anchor_refs]

    resolved = expected_resolution.get("status") == "resolved"
    state_id = str(expected_resolution.get("state_id") or "") if resolved else ""
    state = next((item for item in asset["states"] if item.get("state_id") == state_id), None)
    interface: Mapping[str, Any] | None = None
    if state is not None and state.get("availability") == "reviewed":
        interface = _find_interface(context, workflow_id=workflow_id, source_node_id=str(state.get("source_node_id") or ""))
        if interface is not None:
            metadata = _mapping(interface.get("interface"), "interface evidence metadata")
            if str(metadata.get("application_identity_key") or "") != application_key:
                raise ValueError("application identity mismatch")
            if str(interface.get("source_asset_sha256") or "") != str(lineage.get("source_workflow_sha256") or ""):
                raise ValueError("source asset mismatch")
            if (interface.get("readiness") or {}).get("status") != "agent_usable":
                raise ValueError("current interface is not agent_usable")
            elif interface.get("artifact_is_authorization") is not False or interface.get("execute_binding_enabled") is not False:
                raise ValueError("current interface evidence must be non-authorizing")
            projection = _mapping(interface.get("projection_contract"), "interface projection contract")
            if (
                projection.get("projection_is_read_only") is not True
                or projection.get("authoritative_source") != "server_persisted_canonical_workflow_revision"
                or projection.get("reverse_write_forbidden") is not True
            ):
                raise ValueError("current interface projection is not trusted")

    facts: list[dict[str, object]] = []
    blockers: list[dict[str, object]] = []
    actions: list[dict[str, object]] = []
    safe_reason: str | None = None
    if not resolved:
        failure = str(expected_resolution.get("failure_code") or "current_state_unresolved")
        safe_reason = "state_ambiguous" if failure == "current_state_ambiguous" else "state_unknown"
    elif state is not None and state.get("availability") == "stop_boundary":
        safe_reason = "stop_boundary"
    elif state is None or interface is None:
        safe_reason = "human_review_required"
    else:
        facts, fact_refs = _fact_payloads(
            interface,
            current_capture_id=str(capture.get("capture_id") or ""),
        )
        evidence_refs.extend(fact_refs)
        source_sha = str(interface.get("source_asset_sha256") or "")
        reviewed_blockers = _trusted_reviewed_blockers(
            context,
            workflow_id=workflow_id,
            source_node_id=str(state.get("source_node_id") or ""),
            projected=interface.get("blockers"),
        )
        for index, item in enumerate(reviewed_blockers):
            raw_blocker_id = str(item.get("blocker_id") or item.get("rule_id") or f"reviewed.{index}")
            blocker_id = _stable_suffix(raw_blocker_id, f"reviewed.{index}")
            description = " ".join(str(item.get("description") or item.get("reason") or "Reviewed workflow blocker.").split())
            safe_required = item.get("safe_stop_required") is True
            blockers.append({
                "blocker_id": f"blocker.{blocker_id}",
                "blocker_type": "policy",
                "description": description[:512] or "Reviewed workflow blocker.",
                "safe_stop_required": safe_required,
                "evidence_refs": [_content_ref(source_sha, "blocker", raw_blocker_id, description)],
            })
            evidence_refs.extend(blockers[-1]["evidence_refs"])
            if safe_required:
                safe_reason = "policy_blocked"
        allowed_ids = {str(item) for item in state.get("allowed_transition_ids") or []}
        trusted_actions = [
            item
            for item in _as_list(interface.get("available_actions"))
            if item.get("review_status") == "human_approved"
        ]
        transitions = {str(item.get("transition_id") or ""): item for item in asset["transitions"]}
        trusted_transition_ids = {
            transition_id
            for transition_id in allowed_ids
            if transition_id in transitions
            and any(
                str(action.get("action_id") or "")
                == str(transitions[transition_id].get("display_name") or "")
                and str(action.get("action_type") or "")
                == str(transitions[transition_id].get("semantic_action") or "")
                for action in trusted_actions
            )
        }
        for transition_id in sorted(trusted_transition_ids):
            transition = transitions.get(transition_id)
            if transition is None:
                continue
            semantic_action = str(transition.get("semantic_action") or "")
            rule_refs = [
                _content_ref(
                    asset_hash,
                    "transition",
                    transition_id,
                    "rule",
                    str(item.get("rule_id") or ""),
                )
                for item in transition["post_action_verification"]["semantic_success_rules"]
                if isinstance(item, Mapping) and str(item.get("rule_id") or "")
            ]
            if not rule_refs or semantic_action not in {"open_detail", "open_apply_flow", "back", "close_modal"}:
                continue
            target_state = str(transition.get("target_state_id") or "")
            actions.append({
                "action_id": transition_id, "semantic_action": semantic_action,
                "description": str(transition.get("display_name") or transition_id),
                "target_state_id": target_state,
                "expected_effect": f"Reach reviewed state: {target_state}.",
                "verification_rule_refs": rule_refs,
                "risk_level": transition["risk_policy"].get("risk_level"),
                "requires_user_confirmation": transition["risk_policy"].get("requires_user_confirmation"),
            })
        if not actions and safe_reason is None:
            safe_reason = "no_available_action"

    evidence_refs = list(dict.fromkeys(evidence_refs))
    if safe_reason:
        if not any(item["safe_stop_required"] for item in blockers):
            blockers.append(_safe_blocker(safe_reason, [state_resolution_ref]))
        actions = [_safe_stop_action()]
    else:
        actions.append(_safe_stop_action())
    status = "matched"
    availability = "reviewed"
    resolution_sha = expected_resolution.get("resolution_sha256")
    if not resolved:
        status = "ambiguous" if safe_reason == "state_ambiguous" else "unknown"
        availability = None
        state_id = None
        resolution_sha = None
    elif state is not None and state.get("availability") == "stop_boundary":
        status = "stop_boundary"
        availability = "stop_boundary"

    readable = {"source_interface_id": None, "display_name": None, "surface_type": None, "responsibility": None}
    if state is not None and resolved:
        if state.get("availability") == "stop_boundary":
            readable = {"source_interface_id": state["source_node_id"], "display_name": state["display_name"], "surface_type": state["state_type"], "responsibility": "Stop at the reviewed terminal boundary."}
        elif interface is not None:
            meta = _mapping(interface["interface"], "interface evidence metadata")
            readable = {"source_interface_id": meta["interface_id"], "display_name": meta["display_name"], "surface_type": meta["surface_type"], "responsibility": meta["responsibility"]}
    payload = {
        "contract_version": "agent_observation_v1", "observation_id": observation_id,
        "session_id": session_id, "workflow": workflow,
        "application": {"identity_ref": f"application:{application_key}", "kind": application["kind"], "display_name": application_key},
        "state_resolution_ref": state_resolution_ref,
        "current_capture": {"capture_id": capture["capture_id"], "screenshot_sha256": capture["screenshot_sha256"], "evidence_ref": current_capture_evidence_ref},
        "state": {"status": status, "state_id": state_id, "state_availability": availability, "resolution_sha256": resolution_sha, **readable},
        "semantic_facts": facts, "evidence_refs": evidence_refs, "blockers": blockers,
        "available_actions": actions,
        "safe_stop": {"required": bool(safe_reason), "reason_code": safe_reason or "none"},
        "artifact_is_authorization": False,
    }
    return validate_agent_observation_v1(payload)


__all__ = ["adapt_reviewed_context_to_agent_observation_v1"]
