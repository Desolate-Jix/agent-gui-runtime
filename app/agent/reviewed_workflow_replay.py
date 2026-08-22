"""纯离线的 Reviewed Workflow Replay v2 协调合同。

当前观察必须使用 ``reviewed_workflow_current_observation_v1``，并绑定 asset_id、
asset content SHA、capture_id、截图 SHA、viewport、origin 和严格 anchor evidence。
当前 grounding 必须使用 ``reviewed_workflow_current_grounding_v1``，Gate 必须使用
``pre_click_decision_v1``，两者都绑定同一 selection/capture/candidate。Operation 必须是
由服务端补入 ``replay_context`` 的可信 adapter envelope；原始 adapter 返回值不能直接
作为 replay 证据。``source_freshness`` 只允许 capture/SHA、一个 viewport alias，以及
trace_path/interface_id/surface_type/contract_version。本模块不调用 GUI/API、不写文件，
也不把 asset、selection 或 grounding 结果视为执行授权。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from copy import deepcopy
from typing import Any
from urllib.parse import urlsplit

from app.agent.reviewed_workflow_asset import (
    content_sha256,
    validate_reviewed_workflow_asset,
)


_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_MVP_ACTIONS = {"open_detail", "open_apply_flow", "back", "close_modal"}
_ANCHOR_EVIDENCE_KEYS = {"anchor_id", "matched", "confidence", "evidence_ref"}
_CAPTURE_LINEAGE_KEYS = {"capture_id", "screenshot_sha256", "viewport_size"}
_VIEWPORT_KEYS = {"width", "height"}
_OBSERVATION_KEYS = {
    "contract_version", "asset_id", "expected_asset_content_sha256", "capture_id",
    "screenshot_sha256", "viewport_size", "origin", "observed_anchor_evidence",
}
_GROUNDING_KEYS = {
    "contract_version", "asset_content_sha256", "transition_id", "source_state_id",
    "capture_id", "screenshot_sha256", "viewport_size", "element_ref", "candidate_id",
    "candidate_current", "eligible", "confidence", "score_margin", "bbox", "click_point",
    "evidence_refs",
}
_GATE_KEYS = {
    "contract_version", "allowed", "asset_content_sha256", "transition_id", "selection_sha256",
    "selected_candidate_id", "selected_element_id", "selected_click_point", "capture_id",
    "screenshot_sha256", "viewport_size", "evidence_refs",
}
_SOURCE_FRESHNESS_TRACE_KEYS = {"trace_path", "interface_id", "surface_type", "contract_version"}
_RESOLUTION_KEYS = {
    "contract_version", "status", "artifact_is_authorization", "execute_binding_enabled",
    "asset_id", "asset_content_sha256", "source_workflow_sha256", "reviewed_revision_hash",
    "canonical_origin", "state_id", "state_availability", "score", "capture_lineage",
    "observed_origin", "matched_anchor_ids", "evidence_refs", "resolution_sha256",
}
_SELECTION_KEYS = {
    "contract_version", "status", "artifact_is_authorization", "execute_binding_enabled",
    "asset_id", "asset_content_sha256", "source_workflow_sha256", "reviewed_revision_hash",
    "canonical_origin", "transition_id", "source_state_id", "target_state_id", "semantic_action",
    "element_ref", "capture_lineage", "requirements", "requires_user_confirmation",
    "human_confirmation_evidence_ref", "selection_sha256",
}


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _finite_number(value: Any, *, minimum: float | None = None, maximum: float | None = None) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        return False
    if minimum is not None and value < minimum:
        return False
    if maximum is not None and value > maximum:
        return False
    return True


def _canonical_sha(value: Any) -> str:
    text = _text(value)
    return text.lower() if _SHA256_RE.fullmatch(text) else ""


def _capture_lineage(payload: Mapping[str, Any], *, require_exact: bool = False) -> dict[str, Any] | None:
    if require_exact and set(payload) != _CAPTURE_LINEAGE_KEYS:
        return None
    capture_id = _text(payload.get("capture_id"))
    screenshot_sha256 = _canonical_sha(payload.get("screenshot_sha256"))
    viewport = payload.get("viewport_size")
    if not capture_id or not screenshot_sha256 or not isinstance(viewport, Mapping) or set(viewport) != _VIEWPORT_KEYS:
        return None
    width, height = viewport.get("width"), viewport.get("height")
    if not isinstance(width, int) or isinstance(width, bool) or width <= 0:
        return None
    if not isinstance(height, int) or isinstance(height, bool) or height <= 0:
        return None
    return {
        "capture_id": capture_id,
        "screenshot_sha256": screenshot_sha256,
        "viewport_size": {"width": width, "height": height},
    }


def _same_lineage(left: Mapping[str, Any] | None, right: Mapping[str, Any] | None) -> bool:
    return bool(left and right and dict(left) == dict(right))


def _normalize_origin(value: Any) -> str | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return None
    scheme = parsed.scheme.lower()
    hostname = parsed.hostname.lower() if parsed.hostname else ""
    if (
        scheme not in {"http", "https"}
        or not hostname
        or any(character.isspace() for character in hostname)
        or "%" in hostname
        or "\\" in parsed.netloc
    ):
        return None
    if parsed.username is not None or parsed.password is not None:
        return None
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        return None
    if port is not None and not (1 <= port <= 65535):
        return None
    default_port = 80 if scheme == "http" else 443
    port_suffix = "" if port in {None, default_port} else f":{port}"
    display_hostname = f"[{hostname}]" if ":" in hostname else hostname
    return f"{scheme}://{display_hostname}{port_suffix}"


def _result(contract_version: str, *, status: str, **payload: Any) -> dict[str, Any]:
    return {
        "contract_version": contract_version,
        "status": status,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        **payload,
    }


def _failure(contract_version: str, failure_code: str, **payload: Any) -> dict[str, Any]:
    return _result(contract_version, status="blocked", failure_code=failure_code, **payload)


def _semantic_hash(payload: Mapping[str, Any], *, excluded: set[str]) -> str:
    binding = {key: value for key, value in payload.items() if key not in excluded}
    serialized = json.dumps(binding, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _asset_context(asset: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    canonical = validate_reviewed_workflow_asset(asset)
    application = canonical["application"]
    canonical_origin = ""
    if application.get("kind") == "web":
        canonical_origin = _normalize_origin(application.get("canonical_origin")) or ""
    context = {
        "asset_id": _text(canonical.get("asset_id")),
        "asset_content_sha256": content_sha256(canonical),
        "source_workflow_sha256": _canonical_sha(canonical["source_review_lineage"].get("source_workflow_sha256")),
        "reviewed_revision_hash": _canonical_sha(canonical["source_review_lineage"].get("reviewed_revision_hash")),
        "canonical_origin": canonical_origin,
    }
    return canonical, context


def _validate_observation(
    canonical: Mapping[str, Any],
    context: Mapping[str, str],
    observation: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, str | None, str | None]:
    if set(observation) != _OBSERVATION_KEYS or observation.get("contract_version") != "reviewed_workflow_current_observation_v1":
        return None, None, "invalid_observation_contract"
    if _text(observation.get("asset_id")) != context["asset_id"]:
        return None, None, "asset_lineage_mismatch"
    if _canonical_sha(observation.get("expected_asset_content_sha256")) != context["asset_content_sha256"]:
        return None, None, "asset_lineage_mismatch"
    lineage = _capture_lineage(observation)
    if lineage is None:
        return None, None, "capture_missing"
    normalized_origin: str | None = None
    application = canonical["application"]
    if application.get("kind") == "web":
        normalized_origin = _normalize_origin(observation.get("origin"))
        if normalized_origin is None:
            return None, None, "unexpected_origin"
        if application.get("allow_external_sites") is not True and normalized_origin != context["canonical_origin"]:
            return None, normalized_origin, "unexpected_origin"
    return lineage, normalized_origin, None


def _state_by_id(asset: Mapping[str, Any], state_id: str) -> Mapping[str, Any] | None:
    return next((state for state in asset["states"] if state.get("state_id") == state_id), None)


def _transition_by_id(asset: Mapping[str, Any], transition_id: str) -> Mapping[str, Any] | None:
    return next((item for item in asset["transitions"] if item.get("transition_id") == transition_id), None)


def _transition_target_ref(transition: Mapping[str, Any]) -> str:
    for key in ("element_ref", "action_ref", "memory_ref", "locator_anchor"):
        reference = _text(transition.get(key))
        if reference:
            return reference
    return ""


def resolve_current_state(asset: Mapping[str, Any], observation: Mapping[str, Any]) -> dict[str, Any]:
    """用严格 current observation 唯一解析 reviewed 或 stop-boundary state。"""
    canonical, context = _asset_context(asset)
    lineage, normalized_origin, observation_error = _validate_observation(canonical, context, observation)
    if observation_error:
        return _failure("current_state_resolution_v1", observation_error, **context)
    assert lineage is not None

    declared_anchor_ids = {
        _text(anchor.get("anchor_id"))
        for state in canonical["states"]
        for anchor in state["identity_anchors"]
    }
    evidence = observation.get("observed_anchor_evidence")
    if not isinstance(evidence, list):
        return _failure("current_state_resolution_v1", "invalid_anchor_evidence", capture_lineage=lineage, **context)
    evidence_by_anchor: dict[str, dict[str, Any]] = {}
    for record in evidence:
        if not isinstance(record, Mapping):
            return _failure("current_state_resolution_v1", "invalid_anchor_evidence", capture_lineage=lineage, **context)
        if set(record) != _ANCHOR_EVIDENCE_KEYS:
            return _failure("current_state_resolution_v1", "invalid_anchor_evidence", capture_lineage=lineage, **context)
        anchor_id = _text(record.get("anchor_id"))
        confidence = record.get("confidence")
        evidence_ref = _text(record.get("evidence_ref"))
        if (
            anchor_id not in declared_anchor_ids
            or record.get("matched") is not True
            or not _finite_number(confidence, minimum=0.0, maximum=1.0)
            or not evidence_ref
        ):
            return _failure("current_state_resolution_v1", "invalid_anchor_evidence", capture_lineage=lineage, **context)
        candidate = {"anchor_id": anchor_id, "confidence": float(confidence), "evidence_ref": evidence_ref}
        previous = evidence_by_anchor.get(anchor_id)
        if previous is None or (candidate["confidence"], candidate["evidence_ref"]) > (previous["confidence"], previous["evidence_ref"]):
            evidence_by_anchor[anchor_id] = candidate

    matches: list[dict[str, Any]] = []
    for state in canonical["states"]:
        records = [
            evidence_by_anchor[anchor_id]
            for anchor_id in (_text(anchor.get("anchor_id")) for anchor in state["identity_anchors"])
            if anchor_id in evidence_by_anchor
        ]
        if records:
            matches.append({"state": state, "score": sum(record["confidence"] for record in records), "evidence": records})
    if not matches:
        return _failure("current_state_resolution_v1", "current_state_unresolved", capture_lineage=lineage, evidence_refs=[], **context)
    top_score = max(match["score"] for match in matches)
    best = [match for match in matches if match["score"] == top_score]
    if len(best) != 1:
        return _failure(
            "current_state_resolution_v1",
            "current_state_ambiguous",
            capture_lineage=lineage,
            candidate_state_ids=sorted(_text(match["state"].get("state_id")) for match in best),
            evidence_refs=sorted({record["evidence_ref"] for match in best for record in match["evidence"]}),
            **context,
        )
    selected = best[0]
    result = _result(
        "current_state_resolution_v1",
        status="resolved",
        state_id=selected["state"]["state_id"],
        state_availability=selected["state"]["availability"],
        score=selected["score"],
        capture_lineage=lineage,
        observed_origin=normalized_origin or "",
        matched_anchor_ids=sorted(record["anchor_id"] for record in selected["evidence"]),
        evidence_refs=sorted(record["evidence_ref"] for record in selected["evidence"]),
        **context,
    )
    result["resolution_sha256"] = _semantic_hash(result, excluded={"resolution_sha256"})
    return result


def _selection_requirements(transition: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "current_capture_required": True,
        "fresh_grounding_required": True,
        "gate_required": transition["risk_policy"].get("requires_gate") is True,
        "gate_endpoint": transition["preconditions"]["gate"]["endpoint"],
        "post_action_verification_required": transition["post_action_verification"].get("requires_new_capture") is True,
        "semantic_success_rule_ids": sorted(
            _text(rule.get("rule_id")) for rule in transition["post_action_verification"]["semantic_success_rules"]
        ),
    }


def _selection_hash(payload: Mapping[str, Any]) -> str:
    binding_keys = (
        "asset_id", "asset_content_sha256", "source_workflow_sha256", "reviewed_revision_hash", "canonical_origin",
        "transition_id", "source_state_id", "target_state_id", "semantic_action", "element_ref",
        "capture_lineage", "requirements", "requires_user_confirmation", "human_confirmation_evidence_ref",
    )
    binding = {key: payload.get(key) for key in binding_keys}
    serialized = json.dumps(binding, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def select_verified_transition(
    asset: Mapping[str, Any],
    state_resolution: Mapping[str, Any],
    *,
    semantic_action: str | None = None,
    transition_id: str | None = None,
    human_confirmation: object | None = None,
    current_observation: Mapping[str, Any],
) -> dict[str, Any]:
    """公开选择器永远不接受调用方提供的确认权限。"""
    return _select_verified_transition_impl(
        asset,
        state_resolution,
        semantic_action=semantic_action,
        transition_id=transition_id,
        human_confirmation=None,
        current_observation=current_observation,
    )


def _select_server_confirmed_transition(
    asset: Mapping[str, Any],
    state_resolution: Mapping[str, Any],
    *,
    semantic_action: str | None = None,
    transition_id: str | None = None,
    confirmation_evidence: object,
    current_observation: Mapping[str, Any],
) -> dict[str, Any]:
    """仅供 controller 使用已从权威 ledger 重读的确认快照。"""
    from app.agent.runtime_intent_claim_store import (
        _unwrap_server_confirmed_transition_evidence,
    )

    confirmation = _unwrap_server_confirmed_transition_evidence(
        confirmation_evidence
    )
    return _select_verified_transition_impl(
        asset,
        state_resolution,
        semantic_action=semantic_action,
        transition_id=transition_id,
        human_confirmation=confirmation,
        current_observation=current_observation,
    )


def _select_verified_transition_impl(
    asset: Mapping[str, Any],
    state_resolution: Mapping[str, Any],
    *,
    semantic_action: str | None = None,
    transition_id: str | None = None,
    human_confirmation: object | None = None,
    current_observation: Mapping[str, Any],
) -> dict[str, Any]:
    """从严格 resolution 选择双向声明 transition；结果不含任何坐标。"""
    canonical, context = _asset_context(asset)
    authoritative_resolution = resolve_current_state(canonical, current_observation)
    if (
        state_resolution.get("contract_version") != "current_state_resolution_v1"
        or state_resolution.get("status") != "resolved"
        or set(state_resolution) != _RESOLUTION_KEYS
        or _canonical_sha(state_resolution.get("resolution_sha256"))
        != _semantic_hash(state_resolution, excluded={"resolution_sha256"})
        or dict(state_resolution) != authoritative_resolution
    ):
        return _failure("verified_transition_selection_v1", "invalid_state_resolution", **context)
    for key in (
        "asset_id",
        "asset_content_sha256",
        "source_workflow_sha256",
        "reviewed_revision_hash",
        "canonical_origin",
    ):
        if state_resolution.get(key) != context[key]:
            return _failure("verified_transition_selection_v1", "asset_lineage_mismatch", **context)
    lineage = _capture_lineage(state_resolution.get("capture_lineage") if isinstance(state_resolution.get("capture_lineage"), Mapping) else {})
    if lineage is None:
        return _failure("verified_transition_selection_v1", "capture_missing", **context)
    state_id = _text(state_resolution.get("state_id"))
    source = _state_by_id(canonical, state_id)
    if source is None:
        return _failure("verified_transition_selection_v1", "invalid_state_resolution", **context)
    if source.get("availability") != "reviewed":
        return _failure("verified_transition_selection_v1", "stop_boundary", source_state_id=state_id, **context)
    allowed_ids = {_text(item) for item in source.get("allowed_transition_ids", [])}
    candidates = [
        item for item in canonical["transitions"]
        if item.get("source_state_id") == state_id
        and _text(item.get("transition_id")) in allowed_ids
        and _text(item.get("semantic_action")) in _MVP_ACTIONS
    ]
    if transition_id is not None:
        candidates = [item for item in candidates if item.get("transition_id") == transition_id]
    if semantic_action is not None:
        candidates = [item for item in candidates if item.get("semantic_action") == semantic_action]
    if not candidates:
        return _failure("verified_transition_selection_v1", "transition_not_available", source_state_id=state_id, **context)
    if len(candidates) != 1:
        return _failure(
            "verified_transition_selection_v1",
            "transition_ambiguous",
            candidate_transition_ids=sorted(_text(item.get("transition_id")) for item in candidates),
            source_state_id=state_id,
            **context,
        )
    transition = candidates[0]
    confirmation_ref = ""
    if transition["risk_policy"].get("requires_user_confirmation") is True:
        try:
            from app.agent.runtime_intent_claim_store import RuntimeIntentConfirmationSnapshot

            confirmed = isinstance(human_confirmation, RuntimeIntentConfirmationSnapshot)
        except ImportError:
            confirmed = False
        if (
            not confirmed
            or human_confirmation.decision != "approved"
            or not human_confirmation.evidence_ref
            or human_confirmation.workflow.asset_id != context["asset_id"]
            or human_confirmation.workflow.asset_content_sha256 != context["asset_content_sha256"]
            or human_confirmation.workflow.source_workflow_sha256 != context["source_workflow_sha256"]
            or human_confirmation.workflow.reviewed_revision_hash != context["reviewed_revision_hash"]
            or human_confirmation.transition_id != transition["transition_id"]
            or human_confirmation.semantic_action != transition["semantic_action"]
        ):
            return _failure("verified_transition_selection_v1", "human_review_required", transition_id=transition["transition_id"], **context)
        confirmation_ref = human_confirmation.evidence_ref
    target_ref = _transition_target_ref(transition)
    if not target_ref:
        return _failure("verified_transition_selection_v1", "target_unresolved", transition_id=transition["transition_id"], **context)
    payload = {
        **context,
        "transition_id": transition["transition_id"],
        "source_state_id": transition["source_state_id"],
        "target_state_id": transition["target_state_id"],
        "semantic_action": transition["semantic_action"],
        "element_ref": target_ref,
        "capture_lineage": deepcopy(lineage),
        "requirements": _selection_requirements(transition),
        "requires_user_confirmation": transition["risk_policy"].get("requires_user_confirmation") is True,
        "human_confirmation_evidence_ref": confirmation_ref,
    }
    payload["selection_sha256"] = _selection_hash(payload)
    return _result("verified_transition_selection_v1", status="selected", **payload)


def _validated_selection(
    asset: Mapping[str, Any],
    selection: Mapping[str, Any],
    *,
    expected_confirmation_evidence_ref: str | None = None,
) -> tuple[dict[str, Any] | None, Mapping[str, Any] | None, str | None]:
    canonical, context = _asset_context(asset)
    if (
        set(selection) != _SELECTION_KEYS
        or selection.get("contract_version") != "verified_transition_selection_v1"
        or selection.get("status") != "selected"
        or selection.get("artifact_is_authorization") is not False
        or selection.get("execute_binding_enabled") is not False
    ):
        return None, None, "selection_lineage_mismatch"
    for key in ("asset_id", "asset_content_sha256", "source_workflow_sha256", "reviewed_revision_hash", "canonical_origin"):
        if selection.get(key) != context[key]:
            return None, None, "selection_lineage_mismatch"
    transition = _transition_by_id(canonical, _text(selection.get("transition_id")))
    if transition is None:
        return None, None, "selection_lineage_mismatch"
    requires_confirmation = transition["risk_policy"].get("requires_user_confirmation") is True
    confirmation_ref = selection.get("human_confirmation_evidence_ref")
    if requires_confirmation and (
        not isinstance(expected_confirmation_evidence_ref, str)
        or not expected_confirmation_evidence_ref
        or confirmation_ref != expected_confirmation_evidence_ref
    ):
        return None, None, "human_review_required"
    target_ref = _transition_target_ref(transition)
    if not target_ref:
        return None, None, "selection_lineage_mismatch"
    expected = {
        "source_state_id": transition["source_state_id"],
        "target_state_id": transition["target_state_id"],
        "semantic_action": transition["semantic_action"],
        "element_ref": target_ref,
        "requirements": _selection_requirements(transition),
        "requires_user_confirmation": transition["risk_policy"].get("requires_user_confirmation") is True,
    }
    if any(selection.get(key) != value for key, value in expected.items()):
        return None, None, "selection_lineage_mismatch"
    if _capture_lineage(
        selection.get("capture_lineage") if isinstance(selection.get("capture_lineage"), Mapping) else {},
        require_exact=True,
    ) is None:
        return None, None, "selection_lineage_mismatch"
    if not requires_confirmation and confirmation_ref != "":
        return None, None, "selection_lineage_mismatch"
    if _canonical_sha(selection.get("selection_sha256")) != _selection_hash(selection):
        return None, None, "selection_lineage_mismatch"
    return canonical, transition, None


def validate_current_grounding(
    asset: Mapping[str, Any],
    selection: Mapping[str, Any],
    grounding_evidence: Mapping[str, Any],
    gate_decision: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """公开 grounding 不接受调用方提供的确认权限。"""
    return _validate_current_grounding_impl(
        asset,
        selection,
        grounding_evidence,
        gate_decision,
        policy=policy,
        expected_confirmation_evidence_ref=None,
    )


def _validate_server_confirmed_grounding(
    asset: Mapping[str, Any],
    selection: Mapping[str, Any],
    grounding_evidence: Mapping[str, Any],
    gate_decision: Mapping[str, Any],
    *,
    confirmation_evidence: object,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """仅供 controller 校验 ledger-bound confirmation selection。"""
    from app.agent.runtime_intent_claim_store import (
        _unwrap_server_confirmed_transition_evidence,
    )

    confirmation = _unwrap_server_confirmed_transition_evidence(
        confirmation_evidence
    )
    return _validate_current_grounding_impl(
        asset,
        selection,
        grounding_evidence,
        gate_decision,
        policy=policy,
        expected_confirmation_evidence_ref=(
            confirmation.evidence_ref if confirmation is not None else None
        ),
    )


def _validate_current_grounding_impl(
    asset: Mapping[str, Any],
    selection: Mapping[str, Any],
    grounding_evidence: Mapping[str, Any],
    gate_decision: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
    expected_confirmation_evidence_ref: str | None = None,
) -> dict[str, Any]:
    """校验当前 candidate 的严格 lineage、阈值、viewport 几何和 Gate 绑定。"""
    _, transition, selection_error = _validated_selection(
        asset,
        selection,
        expected_confirmation_evidence_ref=expected_confirmation_evidence_ref,
    )
    if selection_error or transition is None:
        return _failure("current_grounding_validation_v1", selection_error or "selection_lineage_mismatch")
    expected_lineage = _capture_lineage(
        selection.get("capture_lineage") if isinstance(selection.get("capture_lineage"), Mapping) else {},
        require_exact=True,
    )
    if selection.get("contract_version") != "verified_transition_selection_v1" or selection.get("status") != "selected" or expected_lineage is None:
        return _failure("current_grounding_validation_v1", "capture_missing")
    if _canonical_sha(selection.get("selection_sha256")) != _selection_hash(selection):
        return _failure("current_grounding_validation_v1", "target_unresolved")
    if set(grounding_evidence) != _GROUNDING_KEYS or grounding_evidence.get("contract_version") != "reviewed_workflow_current_grounding_v1":
        return _failure("current_grounding_validation_v1", "target_unresolved")
    binding = {
        "asset_content_sha256": selection.get("asset_content_sha256"),
        "transition_id": selection.get("transition_id"),
        "source_state_id": selection.get("source_state_id"),
        "element_ref": selection.get("element_ref"),
    }
    if any(grounding_evidence.get(key) != value for key, value in binding.items()):
        return _failure("current_grounding_validation_v1", "target_unresolved")
    grounding_lineage = _capture_lineage(grounding_evidence)
    if grounding_lineage is None:
        return _failure("current_grounding_validation_v1", "capture_missing")
    if not _same_lineage(expected_lineage, grounding_lineage):
        return _failure("current_grounding_validation_v1", "capture_lineage_mismatch", capture_lineage=grounding_lineage)
    candidate_id = _text(grounding_evidence.get("candidate_id"))
    if not candidate_id or grounding_evidence.get("eligible") is not True:
        return _failure("current_grounding_validation_v1", "target_unresolved", capture_lineage=grounding_lineage)
    if grounding_evidence.get("candidate_current") is not True:
        return _failure("current_grounding_validation_v1", "stale_candidate", capture_lineage=grounding_lineage)
    policy = policy if isinstance(policy, Mapping) else {}
    minimum_confidence, minimum_margin = policy.get("minimum_confidence"), policy.get("minimum_score_margin")
    confidence, margin = grounding_evidence.get("confidence"), grounding_evidence.get("score_margin")
    if not all(_finite_number(value, minimum=0.0, maximum=1.0) for value in (minimum_confidence, minimum_margin, confidence, margin)):
        return _failure("current_grounding_validation_v1", "grounding_ambiguous", capture_lineage=grounding_lineage)
    if confidence < minimum_confidence or margin < minimum_margin:
        return _failure("current_grounding_validation_v1", "grounding_ambiguous", capture_lineage=grounding_lineage)
    bbox, point = grounding_evidence.get("bbox"), grounding_evidence.get("click_point")
    if (
        not isinstance(bbox, Mapping)
        or set(bbox) != {"x", "y", "w", "h"}
        or not isinstance(point, Mapping)
        or set(point) != {"x", "y"}
    ):
        return _failure("current_grounding_validation_v1", "target_unresolved", capture_lineage=grounding_lineage)
    if not all(_finite_number(bbox.get(field), minimum=0.0) for field in ("x", "y", "w", "h")) or bbox["w"] <= 0 or bbox["h"] <= 0:
        return _failure("current_grounding_validation_v1", "target_unresolved", capture_lineage=grounding_lineage)
    if not all(_finite_number(point.get(field), minimum=0.0) for field in ("x", "y")):
        return _failure("current_grounding_validation_v1", "target_unresolved", capture_lineage=grounding_lineage)
    viewport = grounding_lineage["viewport_size"]
    if bbox["x"] + bbox["w"] > viewport["width"] or bbox["y"] + bbox["h"] > viewport["height"]:
        return _failure("current_grounding_validation_v1", "target_unresolved", capture_lineage=grounding_lineage)
    if not (bbox["x"] <= point["x"] <= bbox["x"] + bbox["w"] and bbox["y"] <= point["y"] <= bbox["y"] + bbox["h"]):
        return _failure("current_grounding_validation_v1", "target_unresolved", capture_lineage=grounding_lineage)
    if point["x"] > viewport["width"] or point["y"] > viewport["height"]:
        return _failure("current_grounding_validation_v1", "target_unresolved", capture_lineage=grounding_lineage)
    grounding_refs = grounding_evidence.get("evidence_refs")
    if not isinstance(grounding_refs, list) or not any(isinstance(ref, str) and ref.strip() for ref in grounding_refs):
        return _failure("current_grounding_validation_v1", "target_unresolved", capture_lineage=grounding_lineage)
    if set(gate_decision) != _GATE_KEYS:
        return _failure("current_grounding_validation_v1", "pre_click_rejected", capture_lineage=grounding_lineage)
    gate_lineage = _capture_lineage(gate_decision)
    gate_binding = {
        "asset_content_sha256": selection.get("asset_content_sha256"),
        "transition_id": selection.get("transition_id"),
        "selection_sha256": selection.get("selection_sha256"),
        "selected_candidate_id": candidate_id,
        "selected_element_id": selection.get("element_ref"),
        "selected_click_point": dict(point),
    }
    if gate_decision.get("contract_version") != "pre_click_decision_v1" or gate_decision.get("allowed") is not True:
        return _failure("current_grounding_validation_v1", "pre_click_rejected", capture_lineage=grounding_lineage)
    if not _same_lineage(expected_lineage, gate_lineage):
        return _failure("current_grounding_validation_v1", "capture_lineage_mismatch", capture_lineage=grounding_lineage)
    if any(gate_decision.get(key) != value for key, value in gate_binding.items()):
        return _failure("current_grounding_validation_v1", "pre_click_rejected", capture_lineage=grounding_lineage)
    gate_refs = gate_decision.get("evidence_refs")
    if not isinstance(gate_refs, list) or not any(isinstance(ref, str) and ref.strip() for ref in gate_refs):
        return _failure("current_grounding_validation_v1", "pre_click_rejected", capture_lineage=grounding_lineage)
    refs = {
        ref for source in (grounding_evidence, gate_decision)
        for ref in source.get("evidence_refs", [])
        if isinstance(ref, str) and ref.strip()
    }
    return _result(
        "current_grounding_validation_v1",
        status="validated",
        asset_content_sha256=selection.get("asset_content_sha256"),
        selection_sha256=selection.get("selection_sha256"),
        transition_id=selection.get("transition_id"),
        capture_lineage=grounding_lineage,
        element_ref=selection.get("element_ref"),
        candidate_id=candidate_id,
        evidence_refs=sorted(refs),
    )


def verify_transition_result(
    asset: Mapping[str, Any],
    selection: Mapping[str, Any],
    operation_result: Mapping[str, Any],
    post_observation: Mapping[str, Any],
) -> dict[str, Any]:
    """校验可信 enriched adapter envelope，并只凭新 capture 的目标语义状态推进。"""
    canonical, transition, selection_error = _validated_selection(
        asset,
        selection,
        expected_confirmation_evidence_ref=(
            selection.get("human_confirmation_evidence_ref")
            if selection.get("requires_user_confirmation") is True
            else None
        ),
    )
    if selection_error:
        return _failure("transition_verification_v1", selection_error, state_advanced=False)
    assert canonical is not None and transition is not None
    if operation_result.get("contract_version") != "navigation_reading_operation_result_v1" or operation_result.get("action_type") != transition["semantic_action"]:
        return _failure("transition_verification_v1", "operation_lineage_mismatch", state_advanced=False)
    replay_context = operation_result.get("replay_context")
    expected_replay_context = {
        "contract_version": "reviewed_workflow_replay_execution_context_v1",
        "asset_content_sha256": selection["asset_content_sha256"],
        "transition_id": selection["transition_id"],
        "selection_sha256": selection["selection_sha256"],
    }
    if (
        not isinstance(replay_context, Mapping)
        or set(replay_context) != set(expected_replay_context)
        or any(replay_context.get(key) != value for key, value in expected_replay_context.items())
    ):
        return _failure("transition_verification_v1", "operation_lineage_mismatch", state_advanced=False)
    if not _text(operation_result.get("approved_plan_id")):
        return _failure("transition_verification_v1", "operation_lineage_mismatch", state_advanced=False)
    freshness = operation_result.get("source_freshness")
    before = selection["capture_lineage"]
    freshness_viewports: list[Any] = []
    if isinstance(freshness, Mapping):
        freshness_viewports = [freshness[key] for key in ("viewport", "viewport_size") if key in freshness]
    freshness_keys = set(freshness) if isinstance(freshness, Mapping) else set()
    allowed_freshness_keys = {
        "capture_id",
        "screenshot_sha256",
        "viewport",
        "viewport_size",
        *_SOURCE_FRESHNESS_TRACE_KEYS,
    }
    if (
        not isinstance(freshness, Mapping)
        or not freshness_keys.issubset(allowed_freshness_keys)
        or not {"capture_id", "screenshot_sha256"}.issubset(freshness_keys)
        or len(freshness_viewports) != 1
        or _text(freshness.get("capture_id")) != before["capture_id"]
        or _canonical_sha(freshness.get("screenshot_sha256")) != before["screenshot_sha256"]
        or any(viewport != before["viewport_size"] for viewport in freshness_viewports)
    ):
        return _failure("transition_verification_v1", "capture_lineage_mismatch", state_advanced=False)
    gate_result = operation_result.get("gate_result")
    if not isinstance(gate_result, Mapping):
        return _failure("transition_verification_v1", "operation_lineage_mismatch", state_advanced=False)
    if operation_result.get("action_executed") is not True:
        gate_reason = _text(gate_result.get("reason"))
        preserved_reason = gate_reason if gate_reason in {
            "stale_approved_plan",
            "capture_lineage_mismatch",
            "pre_click_rejected",
            "foreground_window_changed",
            "foreground_changed",
            "foreground_change",
        } else "post_action_failure"
        return _failure("transition_verification_v1", preserved_reason, state_advanced=False, gate_reason=gate_reason)
    if gate_result.get("allowed") is not True:
        return _failure("transition_verification_v1", "pre_click_rejected", state_advanced=False, gate_reason=_text(gate_result.get("reason")))
    operation_evidence = operation_result.get("evidence_refs")
    if not isinstance(operation_evidence, list) or not any(isinstance(ref, str) and ref.strip() for ref in operation_evidence):
        return _failure("transition_verification_v1", "operation_evidence_missing", state_advanced=False)
    post_lineage = _capture_lineage(post_observation)
    if post_lineage is None:
        return _failure("transition_verification_v1", "post_capture_missing", state_advanced=False)
    if post_lineage["capture_id"] == before["capture_id"]:
        return _failure("transition_verification_v1", "post_capture_not_new", state_advanced=False)
    post_resolution = resolve_current_state(canonical, post_observation)
    strict_post_failure = post_resolution.get("failure_code")
    if strict_post_failure in {
        "unexpected_origin",
        "asset_lineage_mismatch",
        "invalid_observation_contract",
        "capture_missing",
        "invalid_anchor_evidence",
    }:
        return _failure("transition_verification_v1", strict_post_failure, state_advanced=False, post_state_resolution=post_resolution)
    if post_resolution.get("status") != "resolved":
        return _failure("transition_verification_v1", "post_action_failure", state_advanced=False, post_state_resolution=post_resolution)
    if post_resolution.get("state_id") != transition["target_state_id"]:
        return _failure("transition_verification_v1", "destination_mismatch", state_advanced=False, post_state_resolution=post_resolution)
    refs = {ref for ref in operation_evidence if isinstance(ref, str) and ref.strip()}
    refs.update(post_resolution.get("evidence_refs", []))
    return _result(
        "transition_verification_v1",
        status="verified",
        state_advanced=True,
        asset_content_sha256=selection["asset_content_sha256"],
        selection_sha256=selection["selection_sha256"],
        transition_id=transition["transition_id"],
        source_state_id=transition["source_state_id"],
        target_state_id=transition["target_state_id"],
        post_capture_lineage=post_lineage,
        post_state_resolution=post_resolution,
        evidence_refs=sorted(refs),
    )


def verify_server_dispatched_transition_result(
    asset: Mapping[str, Any],
    selection: Mapping[str, Any],
    before_observation: Mapping[str, Any],
    post_observation: Mapping[str, Any],
    *,
    server_evidence_refs: list[str],
) -> dict[str, Any]:
    """只凭服务端证据和 C1/C2 观察校验已派发 transition 的目标状态。"""
    canonical, transition, selection_error = _validated_selection(
        asset,
        selection,
        expected_confirmation_evidence_ref=(
            selection.get("human_confirmation_evidence_ref")
            if selection.get("requires_user_confirmation") is True
            else None
        ),
    )
    if selection_error:
        return _failure("transition_verification_v1", selection_error, state_advanced=False)
    assert canonical is not None and transition is not None

    post_policy = transition.get("post_action_verification")
    rules = post_policy.get("semantic_success_rules") if isinstance(post_policy, Mapping) else None
    rule_ids: set[str] = set()
    if (
        not isinstance(post_policy, Mapping)
        or set(post_policy) != {"requires_new_capture", "semantic_success_rules"}
        or post_policy.get("requires_new_capture") is not True
        or not isinstance(rules, list)
        or not rules
    ):
        return _failure("transition_verification_v1", "unsupported_semantic_success_rule", state_advanced=False)
    for rule in rules:
        if (
            not isinstance(rule, Mapping)
            or set(rule) != {"rule_id", "type"}
            or not _text(rule.get("rule_id"))
            or rule.get("type") != "target_state_identity"
            or _text(rule.get("rule_id")) in rule_ids
        ):
            return _failure("transition_verification_v1", "unsupported_semantic_success_rule", state_advanced=False)
        rule_ids.add(_text(rule.get("rule_id")))

    if (
        not isinstance(server_evidence_refs, list)
        or not server_evidence_refs
        or any(not isinstance(ref, str) or not ref.strip() for ref in server_evidence_refs)
    ):
        return _failure("transition_verification_v1", "server_evidence_missing", state_advanced=False)

    before_resolution = resolve_current_state(canonical, before_observation)
    if before_resolution.get("status") != "resolved":
        return _failure(
            "transition_verification_v1",
            _text(before_resolution.get("failure_code")) or "selection_lineage_mismatch",
            state_advanced=False,
            pre_state_resolution=before_resolution,
        )
    before_lineage = before_resolution.get("capture_lineage")
    if (
        not isinstance(before_lineage, Mapping)
        or not _same_lineage(before_lineage, selection.get("capture_lineage"))
    ):
        return _failure("transition_verification_v1", "capture_lineage_mismatch", state_advanced=False)
    if before_resolution.get("state_id") != transition["source_state_id"]:
        return _failure("transition_verification_v1", "selection_lineage_mismatch", state_advanced=False)

    post_resolution = resolve_current_state(canonical, post_observation)
    strict_post_failure = post_resolution.get("failure_code")
    if strict_post_failure in {
        "unexpected_origin",
        "asset_lineage_mismatch",
        "invalid_observation_contract",
        "capture_missing",
        "invalid_anchor_evidence",
    }:
        return _failure(
            "transition_verification_v1",
            strict_post_failure,
            state_advanced=False,
            post_state_resolution=post_resolution,
        )
    post_lineage = post_resolution.get("capture_lineage")
    if not isinstance(post_lineage, Mapping):
        return _failure(
            "transition_verification_v1",
            "post_action_failure",
            state_advanced=False,
            post_state_resolution=post_resolution,
        )
    if _text(post_lineage.get("capture_id")) == _text(before_lineage.get("capture_id")):
        return _failure("transition_verification_v1", "post_capture_not_new", state_advanced=False)
    if post_resolution.get("status") != "resolved":
        return _failure(
            "transition_verification_v1",
            "post_action_failure",
            state_advanced=False,
            post_state_resolution=post_resolution,
        )
    if post_resolution.get("state_id") != transition["target_state_id"]:
        return _failure(
            "transition_verification_v1",
            "destination_mismatch",
            state_advanced=False,
            post_state_resolution=post_resolution,
        )

    evidence_refs = set(server_evidence_refs)
    evidence_refs.update(
        ref for ref in post_resolution.get("evidence_refs", [])
        if isinstance(ref, str) and ref.strip()
    )
    return _result(
        "transition_verification_v1",
        status="verified",
        state_advanced=True,
        asset_content_sha256=selection["asset_content_sha256"],
        selection_sha256=selection["selection_sha256"],
        transition_id=transition["transition_id"],
        source_state_id=transition["source_state_id"],
        target_state_id=transition["target_state_id"],
        post_capture_lineage=dict(post_lineage),
        post_state_resolution=post_resolution,
        evidence_refs=sorted(evidence_refs),
    )


def build_recovery_decision(transition: Mapping[str, Any], failure_code: str, *, attempts_used: int) -> dict[str, Any]:
    """生成最多一次且绝不重放 action 的恢复决策。"""
    if not isinstance(attempts_used, int) or isinstance(attempts_used, bool) or attempts_used < 0:
        attempts_used = 1
    if attempts_used >= 1 or transition.get("recovery_policy", {}).get("max_attempts") != 1:
        return _result(
            "recovery_decision_v1",
            status="blocked",
            failure_code="recovery_exhausted",
            decision="safe_stop_human_review",
            repeat_action=False,
            attempts_used=attempts_used,
        )
    if failure_code in {
        "stale_capture",
        "stale_approved_plan",
        "target_not_found",
        "target_unresolved",
        "capture_missing",
        "capture_lineage_mismatch",
        "stale_candidate",
    }:
        decision = "reobserve_and_reground_once"
    elif failure_code in {"post_action_failure", "post_capture_not_new"}:
        decision = "observe_without_repeat"
    else:
        decision = "safe_stop_human_review"
    return _result(
        "recovery_decision_v1",
        status="recovery_planned" if decision != "safe_stop_human_review" else "blocked",
        failure_code=failure_code,
        decision=decision,
        repeat_action=False,
        attempts_used=attempts_used,
        max_attempts=1,
    )
