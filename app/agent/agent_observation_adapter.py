"""Projects server-trusted reviewed workflow evidence into AgentObservationV1."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.agent.reviewed_workflow_asset import content_sha256, validate_reviewed_workflow_asset
from app.agent.reviewed_workflow_replay import resolve_current_state
from app.agent.runtime_contracts import AgentObservationV1, validate_agent_observation_v1


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
            if status == "current" and str(item.get("capture_id") or "") != current_capture_id:
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
            evidence_refs = [str(ref) for ref in item.get("evidence_refs") or [] if isinstance(ref, str) and ref]
            if not evidence_refs:
                source_sha = str(interface.get("source_asset_sha256") or "")
                evidence_refs = [f"reviewed-evidence:{source_sha}:{source_id}"]
            facts.append({
                "fact_id": f"fact.{source_id}", "fact_type": fact_type, "label": label,
                "value": value, "observation_status": status, "evidence_refs": evidence_refs,
            })
            refs.extend(evidence_refs)
    return facts, refs


def _find_interface(context: Mapping[str, Any], *, workflow_id: str, source_node_id: str) -> Mapping[str, Any] | None:
    matches: list[Mapping[str, Any]] = []
    for workflow in _as_list(context.get("agent_evidence_workflows")):
        if str(workflow.get("workflow_id") or "") != workflow_id:
            continue
        for interface in _as_list(workflow.get("interfaces")):
            metadata = _mapping(interface.get("interface"), "interface evidence metadata")
            if str(metadata.get("interface_id") or "") == source_node_id:
                matches.append(interface)
    if len(matches) > 1:
        raise ValueError("reviewed state must map to exactly one evidence interface")
    return matches[0] if matches else None


def adapt_reviewed_context_to_agent_observation_v1(
    *,
    observation_id: str,
    session_id: str,
    workflow_id: str,
    reviewed_asset: Mapping[str, Any],
    current_observation: Mapping[str, Any],
    state_resolution: Mapping[str, Any],
    interface_workflow_agent_context: Mapping[str, Any],
    state_resolution_ref: str,
    current_capture_evidence_ref: str,
) -> AgentObservationV1:
    """Build a geometry-free observation from canonical reviewed evidence only."""
    asset = validate_reviewed_workflow_asset(reviewed_asset)
    expected_resolution = resolve_current_state(asset, current_observation)
    if dict(state_resolution) != expected_resolution:
        raise ValueError("state resolution does not match current authoritative resolution")
    context = _mapping(interface_workflow_agent_context, "interface workflow agent context")
    if context.get("contract_version") != "interface_workflow_agent_context_v1":
        raise ValueError("invalid interface workflow agent context")
    if context.get("agent_ready") is not True:
        raise ValueError("interface workflow context is not agent-ready")
    if context.get("artifact_is_authorization") is not False or context.get("execute_binding_enabled") is not False:
        raise ValueError("interface workflow context must be non-authorizing")

    application = _mapping(asset.get("application"), "reviewed asset application")
    application_key = _expected_application_key(application)
    context_application = _mapping(context.get("application_identity"), "context application identity")
    if str(context.get("application_identity_key") or "") != application_key or str(context_application.get("identity_key") or "") != application_key:
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
    evidence_refs = [state_resolution_ref, current_capture_evidence_ref]
    evidence_refs.extend(str(ref) for ref in expected_resolution.get("evidence_refs") or [] if isinstance(ref, str) and ref)

    resolved = expected_resolution.get("status") == "resolved"
    state_id = str(expected_resolution.get("state_id") or "") if resolved else ""
    state = next((item for item in asset["states"] if item.get("state_id") == state_id), None)
    interface: Mapping[str, Any] | None = None
    if state is not None:
        interface = _find_interface(context, workflow_id=workflow_id, source_node_id=str(state.get("source_node_id") or ""))
        if interface is not None:
            metadata = _mapping(interface.get("interface"), "interface evidence metadata")
            if str(metadata.get("application_identity_key") or "") != application_key:
                raise ValueError("application identity mismatch")
            if str(interface.get("source_asset_sha256") or "") != str(lineage.get("source_workflow_sha256") or ""):
                raise ValueError("source asset mismatch")
            if (interface.get("readiness") or {}).get("status") != "agent_usable":
                interface = None
            elif interface.get("artifact_is_authorization") is not False or interface.get("execute_binding_enabled") is not False:
                interface = None
            elif (interface.get("projection_contract") or {}).get("projection_is_read_only") is not True:
                interface = None

    facts: list[dict[str, object]] = []
    blockers: list[dict[str, object]] = []
    actions: list[dict[str, object]] = []
    safe_reason: str | None = None
    if not resolved:
        failure = str(expected_resolution.get("failure_code") or "current_state_unresolved")
        safe_reason = "state_ambiguous" if failure == "current_state_ambiguous" else "state_unknown"
    elif state is None or interface is None:
        safe_reason = "human_review_required"
    elif state.get("availability") == "stop_boundary":
        safe_reason = "stop_boundary"
    else:
        facts, fact_refs = _fact_payloads(
            interface,
            current_capture_id=str(capture.get("capture_id") or ""),
        )
        evidence_refs.extend(fact_refs)
        for item in _as_list(interface.get("blockers")):
            if item.get("safe_stop_required") is True:
                safe_reason = "policy_blocked"
                break
        allowed_ids = {str(item) for item in state.get("allowed_transition_ids") or []}
        transitions = {str(item.get("transition_id") or ""): item for item in asset["transitions"]}
        for transition_id in sorted(allowed_ids):
            transition = transitions.get(transition_id)
            if transition is None:
                continue
            semantic_action = str(transition.get("semantic_action") or "")
            rule_refs = [
                f"workflow-rule:{item.get('rule_id')}"
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
        if not actions:
            safe_reason = "no_available_action"

    evidence_refs = list(dict.fromkeys(evidence_refs))
    if safe_reason:
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

    payload = {
        "contract_version": "agent_observation_v1", "observation_id": observation_id,
        "session_id": session_id, "workflow": workflow,
        "application": {"identity_ref": f"application:{application_key}", "kind": application["kind"], "display_name": application_key},
        "state_resolution_ref": state_resolution_ref,
        "current_capture": {"capture_id": capture["capture_id"], "screenshot_sha256": capture["screenshot_sha256"], "evidence_ref": current_capture_evidence_ref},
        "state": {"status": status, "state_id": state_id, "state_availability": availability, "resolution_sha256": resolution_sha},
        "semantic_facts": facts, "evidence_refs": evidence_refs, "blockers": blockers,
        "available_actions": actions,
        "safe_stop": {"required": bool(safe_reason), "reason_code": safe_reason or "none"},
        "artifact_is_authorization": False,
    }
    return validate_agent_observation_v1(payload)


__all__ = ["adapt_reviewed_context_to_agent_observation_v1"]
