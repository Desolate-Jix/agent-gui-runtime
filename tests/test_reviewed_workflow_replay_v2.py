from __future__ import annotations

import copy
import math

import pytest

from tests.test_reviewed_workflow_asset_v2 import _asset


def _asset_hash(asset: dict) -> str:
    from app.agent.reviewed_workflow_asset import content_sha256

    return content_sha256(asset)


def _observation(asset: dict, capture_id: str, screenshot: str, *anchors: str, origin: str = "https://nz.seek.com") -> dict:
    return {
        "contract_version": "reviewed_workflow_current_observation_v1",
        "asset_id": asset["asset_id"],
        "expected_asset_content_sha256": _asset_hash(asset),
        "capture_id": capture_id,
        "screenshot_sha256": screenshot,
        "viewport_size": {"width": 1440, "height": 900},
        "origin": origin,
        "observed_anchor_evidence": [
            {"anchor_id": anchor, "matched": True, "evidence_ref": f"evidence:{capture_id}:{anchor}", "confidence": 0.95}
            for anchor in anchors
        ],
    }


def _resolution(asset: dict | None = None) -> dict:
    from app.agent.reviewed_workflow_replay import resolve_current_state

    asset = asset or _asset()
    return resolve_current_state(asset, _observation(asset, "capture-1", "a" * 64, "anchor_homepage", "job_card"))


def _selection(asset: dict | None = None) -> dict:
    from app.agent.reviewed_workflow_replay import select_verified_transition

    asset = asset or _asset()
    observation = _observation(asset, "capture-1", "a" * 64, "anchor_homepage", "job_card")
    return select_verified_transition(
        asset,
        _resolution(asset),
        transition_id="open_detail",
        current_observation=observation,
    )


def _grounding(asset: dict, capture_id: str = "capture-1", screenshot: str = "a" * 64) -> dict:
    return {
        "contract_version": "reviewed_workflow_current_grounding_v1",
        "asset_content_sha256": _asset_hash(asset),
        "transition_id": "open_detail",
        "source_state_id": "homepage",
        "capture_id": capture_id,
        "screenshot_sha256": screenshot,
        "viewport_size": {"width": 1440, "height": 900},
        "element_ref": "job_card",
        "candidate_id": "candidate-current",
        "candidate_current": True,
        "eligible": True,
        "confidence": 0.95,
        "score_margin": 0.40,
        "bbox": {"x": 100, "y": 200, "w": 300, "h": 80},
        "click_point": {"x": 220, "y": 240},
        "evidence_refs": ["grounding:capture-1:job_card"],
    }


def _gate(asset: dict, selection: dict, capture_id: str = "capture-1", screenshot: str = "a" * 64) -> dict:
    return {
        "contract_version": "pre_click_decision_v1",
        "allowed": True,
        "asset_content_sha256": _asset_hash(asset),
        "transition_id": selection["transition_id"],
        "selection_sha256": selection["selection_sha256"],
        "selected_candidate_id": "candidate-current",
        "selected_element_id": selection["element_ref"],
        "selected_click_point": {"x": 220, "y": 240},
        "capture_id": capture_id,
        "screenshot_sha256": screenshot,
        "viewport_size": {"width": 1440, "height": 900},
        "evidence_refs": ["gate:capture-1"],
    }


def _operation(selection: dict) -> dict:
    lineage = selection["capture_lineage"]
    return {
        "contract_version": "navigation_reading_operation_result_v1",
        "action_type": selection["semantic_action"],
        "action_executed": True,
        "post_action_verified": True,
        "gate_result": {"allowed": True, "reason": "approved_plan"},
        "approved_plan_id": "approved-plan-1",
        "source_freshness": {
            "capture_id": lineage["capture_id"],
            "screenshot_sha256": lineage["screenshot_sha256"],
            "viewport": lineage["viewport_size"],
            "trace_path": "logs/traces/capture-1.json",
        },
        "replay_context": {
            "contract_version": "reviewed_workflow_replay_execution_context_v1",
            "asset_content_sha256": selection["asset_content_sha256"],
            "transition_id": selection["transition_id"],
            "selection_sha256": selection["selection_sha256"],
        },
        "evidence_refs": ["operation:1"],
    }


def test_resolve_current_state_returns_strict_asset_and_capture_lineage() -> None:
    asset = _asset()
    resolution = _resolution(asset)
    assert resolution["contract_version"] == "current_state_resolution_v1"
    assert resolution["status"] == "resolved"
    assert resolution["state_id"] == "homepage"
    assert resolution["asset_id"] == asset["asset_id"]
    assert resolution["asset_content_sha256"] == _asset_hash(asset)
    assert resolution["source_workflow_sha256"] == "a" * 64
    assert resolution["canonical_origin"] == "https://nz.seek.com"
    assert resolution["capture_lineage"]["capture_id"] == "capture-1"
    assert resolution["artifact_is_authorization"] is False
    assert len(resolution["resolution_sha256"]) == 64
    assert set(resolution) == {
        "contract_version", "status", "artifact_is_authorization", "execute_binding_enabled",
        "asset_id", "asset_content_sha256", "source_workflow_sha256", "reviewed_revision_hash",
        "canonical_origin", "state_id", "state_availability", "score", "capture_lineage",
        "observed_origin", "matched_anchor_ids", "evidence_refs", "resolution_sha256",
    }


def test_resolve_rejects_unresolved_and_ambiguous_evidence() -> None:
    from app.agent.reviewed_workflow_replay import resolve_current_state

    asset = _asset()
    assert resolve_current_state(asset, _observation(asset, "capture-1", "a" * 64))["failure_code"] == "current_state_unresolved"
    ambiguous = resolve_current_state(asset, _observation(asset, "capture-1", "a" * 64, "anchor_homepage", "anchor_detail"))
    assert ambiguous["failure_code"] == "current_state_ambiguous"


@pytest.mark.parametrize("bad_sha", ["short", "g" * 64, "a" * 63])
def test_observation_rejects_malformed_sha(bad_sha: str) -> None:
    from app.agent.reviewed_workflow_replay import resolve_current_state

    asset = _asset()
    assert resolve_current_state(asset, _observation(asset, "capture-1", bad_sha, "anchor_homepage"))["failure_code"] == "capture_missing"


@pytest.mark.parametrize("bad_number", [True, math.nan, math.inf, -math.inf, 0, -1])
def test_observation_rejects_invalid_viewport_numbers(bad_number: float) -> None:
    from app.agent.reviewed_workflow_replay import resolve_current_state

    asset = _asset()
    observation = _observation(asset, "capture-1", "a" * 64, "anchor_homepage")
    observation["viewport_size"]["width"] = bad_number
    assert resolve_current_state(asset, observation)["failure_code"] == "capture_missing"


def test_observation_rejects_cross_asset_contract_and_invalid_anchor_evidence() -> None:
    from app.agent.reviewed_workflow_replay import resolve_current_state

    asset = _asset()
    observation = _observation(asset, "capture-1", "a" * 64, "anchor_homepage")
    observation["expected_asset_content_sha256"] = "d" * 64
    assert resolve_current_state(asset, observation)["failure_code"] == "asset_lineage_mismatch"
    observation = _observation(asset, "capture-1", "a" * 64, "anchor_homepage")
    observation["observed_anchor_evidence"][0]["evidence_ref"] = ""
    assert resolve_current_state(asset, observation)["failure_code"] == "invalid_anchor_evidence"
    observation = _observation(asset, "capture-1", "a" * 64, "anchor_homepage")
    observation["observed_anchor_evidence"][0]["matched"] = False
    assert resolve_current_state(asset, observation)["failure_code"] == "invalid_anchor_evidence"
    observation = _observation(asset, "capture-1", "a" * 64, "anchor_homepage")
    observation["observed_anchor_evidence"][0]["bbox"] = {"x": 1, "y": 2, "w": 3, "h": 4}
    assert resolve_current_state(asset, observation)["failure_code"] == "invalid_anchor_evidence"
    observation = _observation(asset, "capture-1", "a" * 64, "anchor_homepage")
    observation["click_point"] = {"x": 1, "y": 2}
    assert resolve_current_state(asset, observation)["failure_code"] == "invalid_observation_contract"


@pytest.mark.parametrize("confidence", [True, -0.01, 1.01, math.nan, math.inf])
def test_observation_rejects_nonfinite_or_out_of_range_anchor_confidence(confidence: float) -> None:
    from app.agent.reviewed_workflow_replay import resolve_current_state

    asset = _asset()
    observation = _observation(asset, "capture-1", "a" * 64, "anchor_homepage")
    observation["observed_anchor_evidence"][0]["confidence"] = confidence
    assert resolve_current_state(asset, observation)["failure_code"] == "invalid_anchor_evidence"


def test_web_origin_normalizes_default_port_and_rejects_credentials_or_other_origin() -> None:
    from app.agent.reviewed_workflow_replay import resolve_current_state

    asset = _asset()
    equivalent = _observation(asset, "capture-1", "a" * 64, "anchor_homepage", origin="HTTPS://NZ.SEEK.COM:443")
    assert resolve_current_state(asset, equivalent)["status"] == "resolved"
    credentialed = _observation(asset, "capture-1", "a" * 64, "anchor_homepage", origin="https://user@nz.seek.com")
    assert resolve_current_state(asset, credentialed)["failure_code"] == "unexpected_origin"
    external = _observation(asset, "capture-1", "a" * 64, "anchor_homepage", origin="https://evil.example")
    assert resolve_current_state(asset, external)["failure_code"] == "unexpected_origin"


def test_web_origin_normalizes_ipv6_with_brackets() -> None:
    from app.agent.reviewed_workflow_replay import resolve_current_state

    asset = _asset()
    asset["application"]["canonical_origin"] = "https://[2001:db8::1]"
    asset["application"]["canonical_domain"] = "2001:db8::1"
    observation = _observation(asset, "capture-1", "a" * 64, "anchor_homepage", origin="HTTPS://[2001:DB8::1]:443")
    result = resolve_current_state(asset, observation)
    assert result["status"] == "resolved"
    assert result["canonical_origin"] == "https://[2001:db8::1]"


def test_select_transition_revalidates_resolution_and_emits_hashed_non_authorizing_plan() -> None:
    asset = _asset()
    selection = _selection(asset)
    assert selection["contract_version"] == "verified_transition_selection_v1"
    assert selection["status"] == "selected"
    assert selection["asset_content_sha256"] == _asset_hash(asset)
    assert len(selection["selection_sha256"]) == 64
    assert selection["element_ref"] == "job_card"
    assert "bbox" not in selection and "click_point" not in selection
    assert selection["artifact_is_authorization"] is False


@pytest.mark.parametrize("semantic_action", ["read", "scroll"])
def test_v2_milestone_rejects_read_and_scroll_transitions(semantic_action: str) -> None:
    from app.agent.reviewed_workflow_replay import resolve_current_state

    asset = _asset()
    asset["transitions"][0]["semantic_action"] = semantic_action
    observation = _observation(asset, "capture-1", "a" * 64, "anchor_homepage", "job_card")
    with pytest.raises(ValueError, match="unsupported semantic action"):
        resolve_current_state(asset, observation)


@pytest.mark.parametrize("semantic_action", ["back", "close_modal"])
def test_v2_milestone_keeps_safe_navigation_transitions(semantic_action: str) -> None:
    from app.agent.reviewed_workflow_replay import resolve_current_state, select_verified_transition

    asset = _asset()
    asset["transitions"][0]["semantic_action"] = semantic_action
    observation = _observation(asset, "capture-1", "a" * 64, "anchor_homepage", "job_card")
    resolution = resolve_current_state(asset, observation)
    result = select_verified_transition(
        asset,
        resolution,
        semantic_action=semantic_action,
        current_observation=observation,
    )
    assert result["status"] == "selected"
    assert result["semantic_action"] == semantic_action


def test_select_rejects_forged_or_cross_asset_resolution() -> None:
    from app.agent.reviewed_workflow_replay import select_verified_transition

    asset = _asset()
    observation = _observation(asset, "capture-1", "a" * 64, "anchor_homepage", "job_card")
    forged = _resolution(asset)
    forged["asset_content_sha256"] = "d" * 64
    assert select_verified_transition(asset, forged, transition_id="open_detail", current_observation=observation)["failure_code"] == "invalid_state_resolution"
    forged = _resolution(asset)
    forged["contract_version"] = "forged"
    assert select_verified_transition(asset, forged, transition_id="open_detail", current_observation=observation)["failure_code"] == "invalid_state_resolution"
    forged = _resolution(asset)
    forged["reviewed_revision_hash"] = "e" * 64
    assert select_verified_transition(asset, forged, transition_id="open_detail", current_observation=observation)["failure_code"] == "invalid_state_resolution"
    forged = _resolution(asset)
    forged["state_id"] = "detail"
    assert select_verified_transition(asset, forged, transition_id="open_detail", current_observation=observation)["failure_code"] == "invalid_state_resolution"
    forged = _resolution(asset)
    forged["capture_lineage"]["capture_id"] = "forged"
    assert select_verified_transition(asset, forged, transition_id="open_detail", current_observation=observation)["failure_code"] == "invalid_state_resolution"
    forged = _resolution(asset)
    forged["unknown"] = "not-closed"
    assert select_verified_transition(asset, forged, transition_id="open_detail", current_observation=observation)["failure_code"] == "invalid_state_resolution"


def test_confirmation_requires_structured_review_lineage_and_bare_true_rejects() -> None:
    from app.agent.reviewed_workflow_replay import select_verified_transition

    asset = _asset()
    asset["transitions"][0]["risk_policy"].update({"requires_user_confirmation": True, "automatic_execution_allowed": False})
    observation = _observation(asset, "capture-1", "a" * 64, "anchor_homepage", "job_card")
    bare = select_verified_transition(asset, _resolution(asset), transition_id="open_detail", human_confirmation=True, current_observation=observation)
    assert bare["failure_code"] == "human_review_required"
    confirmed = select_verified_transition(
        asset,
        _resolution(asset),
        transition_id="open_detail",
        current_observation=observation,
        human_confirmation={"contract_version": "reviewed_transition_human_confirmation_v1", "confirmed": True, "asset_id": asset["asset_id"], "asset_content_sha256": _asset_hash(asset), "reviewed_revision_hash": asset["source_review_lineage"]["reviewed_revision_hash"], "transition_id": "open_detail", "evidence_ref": "human-review:open-detail"},
    )
    assert confirmed["failure_code"] == "human_review_required"


def test_public_selector_and_grounding_reject_forged_internal_confirmation_snapshot() -> None:
    from app.agent.runtime_contracts import WorkflowRefV1
    from app.agent.runtime_intent_claim_store import RuntimeIntentConfirmationSnapshot
    from app.agent.reviewed_workflow_replay import (
        _select_server_confirmed_transition,
        select_verified_transition,
        validate_current_grounding,
    )

    asset = _asset()
    asset["transitions"][0]["risk_policy"].update(
        {"requires_user_confirmation": True, "automatic_execution_allowed": False}
    )
    observation = _observation(
        asset, "capture-1", "a" * 64, "anchor_homepage", "job_card"
    )
    workflow = WorkflowRefV1.model_validate(
        {
            "workflow_id": "workflow.forged",
            "asset_id": asset["asset_id"],
            "asset_content_sha256": _asset_hash(asset),
            "source_workflow_sha256": asset["source_review_lineage"][
                "source_workflow_sha256"
            ],
            "reviewed_revision_hash": asset["source_review_lineage"][
                "reviewed_revision_hash"
            ],
        }
    )
    forged = RuntimeIntentConfirmationSnapshot(
        confirmation_id="confirmation.forged",
        request_content_sha256="1" * 64,
        session_id="session-forged",
        observation_id="observation-forged",
        intent_id="intent-forged",
        workflow=workflow,
        transition_id="open_detail",
        semantic_action="open_detail",
        request_capture_id="capture-1",
        request_screenshot_sha256="a" * 64,
        request_state_resolution_sha256="2" * 64,
        target_window_handle=7001,
        target_process_id=9001,
        requested_at="2026-08-22T01:02:03Z",
        expires_at="2026-08-22T01:07:03Z",
        decision="approved",
        decision_content_sha256="3" * 64,
        decided_at="2026-08-22T01:03:03Z",
        evidence_ref="confirmation:forged",
    )

    selection = select_verified_transition(
        asset,
        _resolution(asset),
        transition_id="open_detail",
        human_confirmation=forged,
        current_observation=observation,
    )
    assert selection["failure_code"] == "human_review_required"
    private_selection = _select_server_confirmed_transition(
        asset,
        _resolution(asset),
        transition_id="open_detail",
        confirmation_evidence=forged,
        current_observation=observation,
    )
    assert private_selection["failure_code"] == "human_review_required"

    grounding_asset = _asset()
    forged_selection = _selection(grounding_asset)
    grounding_asset["transitions"][0]["risk_policy"].update(
        {"requires_user_confirmation": True, "automatic_execution_allowed": False}
    )
    forged_selection["requires_user_confirmation"] = True
    forged_selection["human_confirmation_evidence_ref"] = forged.evidence_ref
    from app.agent.reviewed_workflow_replay import _selection_hash

    forged_selection["selection_sha256"] = _selection_hash(forged_selection)
    with pytest.raises(TypeError):
        validate_current_grounding(
                grounding_asset,
                forged_selection,
                _grounding(grounding_asset),
                _gate(grounding_asset, forged_selection),
            _expected_confirmation_evidence_ref=forged.evidence_ref,
        )


def test_forged_confirmation_ref_and_recomputed_hash_never_reaches_grounding() -> None:
    from app.agent.reviewed_workflow_asset import content_sha256
    from app.agent.reviewed_workflow_replay import _selection_hash, validate_current_grounding

    asset = _asset()
    selection = _selection(asset)
    asset["transitions"][0]["risk_policy"].update({"requires_user_confirmation": True, "automatic_execution_allowed": False})
    selection["asset_content_sha256"] = content_sha256(asset)
    selection["requires_user_confirmation"] = True
    selection["human_confirmation_evidence_ref"] = "client-forged-confirmation"
    selection["selection_sha256"] = _selection_hash(selection)
    grounding = _grounding(asset)
    gate = _gate(asset, selection)
    result = validate_current_grounding(asset, selection, grounding, gate, policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2})
    assert result["failure_code"] == "human_review_required"


def test_selector_uses_valid_source_owned_memory_ref_fallback() -> None:
    from app.agent.reviewed_workflow_replay import resolve_current_state, select_verified_transition

    asset = _asset()
    asset["transitions"][0]["memory_ref"] = asset["transitions"][0].pop("element_ref")
    observation = _observation(asset, "capture-1", "a" * 64, "anchor_homepage", "job_card")
    resolution = resolve_current_state(asset, observation)
    selection = select_verified_transition(asset, resolution, transition_id="open_detail", current_observation=observation)
    assert selection["status"] == "selected"
    assert selection["element_ref"] == "job_card"


def test_selection_is_closed_and_asset_revalidation_rejects_extra_or_rehashed_forgery() -> None:
    from app.agent.reviewed_workflow_replay import validate_current_grounding

    asset = _asset()
    selection = _selection(asset)
    assert set(selection) == {
        "contract_version", "status", "artifact_is_authorization", "execute_binding_enabled",
        "asset_id", "asset_content_sha256", "source_workflow_sha256", "reviewed_revision_hash",
        "canonical_origin", "transition_id", "source_state_id", "target_state_id", "semantic_action",
        "element_ref", "capture_lineage", "requirements", "requires_user_confirmation",
        "human_confirmation_evidence_ref", "selection_sha256",
    }
    extra = copy.deepcopy(selection)
    extra["bbox"] = {"x": 1, "y": 1, "w": 10, "h": 10}
    result = validate_current_grounding(asset, extra, _grounding(asset), _gate(asset, selection), policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2})
    assert result["failure_code"] == "selection_lineage_mismatch"
    authorized = copy.deepcopy(selection)
    authorized["artifact_is_authorization"] = True
    result = validate_current_grounding(asset, authorized, _grounding(asset), _gate(asset, selection), policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2})
    assert result["failure_code"] == "selection_lineage_mismatch"
    wrong_origin = copy.deepcopy(selection)
    wrong_origin["canonical_origin"] = "https://evil.example"
    result = validate_current_grounding(asset, wrong_origin, _grounding(asset), _gate(asset, selection), policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2})
    assert result["failure_code"] == "selection_lineage_mismatch"
    forged = copy.deepcopy(selection)
    forged["element_ref"] = "quick_apply"
    from app.agent.reviewed_workflow_replay import _selection_hash
    forged["selection_sha256"] = _selection_hash(forged)
    forged_grounding = _grounding(asset)
    forged_grounding["element_ref"] = "quick_apply"
    forged_gate = _gate(asset, forged)
    result = validate_current_grounding(asset, forged, forged_grounding, forged_gate, policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2})
    assert result["failure_code"] == "selection_lineage_mismatch"
    nested_injection = copy.deepcopy(selection)
    nested_injection["capture_lineage"]["bbox"] = {"x": 1, "y": 1, "w": 2, "h": 2}
    nested_injection["selection_sha256"] = _selection_hash(nested_injection)
    result = validate_current_grounding(asset, nested_injection, _grounding(asset), _gate(asset, nested_injection), policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2})
    assert result["failure_code"] == "selection_lineage_mismatch"


def test_grounding_and_gate_bind_all_selection_fields_and_numeric_geometry() -> None:
    from app.agent.reviewed_workflow_replay import validate_current_grounding

    asset = _asset()
    selection = _selection(asset)
    policy = {"minimum_confidence": 0.9, "minimum_score_margin": 0.2}
    assert validate_current_grounding(asset, selection, _grounding(asset), _gate(asset, selection), policy=policy)["status"] == "validated"
    wrong_candidate = _gate(asset, selection)
    wrong_candidate["selected_candidate_id"] = "other"
    assert validate_current_grounding(asset, selection, _grounding(asset), wrong_candidate, policy=policy)["failure_code"] == "pre_click_rejected"
    wrong_transition = _grounding(asset)
    wrong_transition["transition_id"] = "open_apply_flow"
    assert validate_current_grounding(asset, selection, wrong_transition, _gate(asset, selection), policy=policy)["failure_code"] == "target_unresolved"
    out_of_view = _grounding(asset)
    out_of_view["bbox"] = {"x": 1400, "y": 200, "w": 100, "h": 80}
    assert validate_current_grounding(asset, selection, out_of_view, _gate(asset, selection), policy=policy)["failure_code"] == "target_unresolved"
    forged_selection = copy.deepcopy(selection)
    forged_selection["element_ref"] = "quick_apply"
    forged_grounding = _grounding(asset)
    forged_grounding["element_ref"] = "quick_apply"
    forged_gate = _gate(asset, selection)
    forged_gate["selected_element_id"] = "quick_apply"
    assert validate_current_grounding(asset, forged_selection, forged_grounding, forged_gate, policy=policy)["failure_code"] == "selection_lineage_mismatch"
    wrong_point = _gate(asset, selection)
    wrong_point["selected_click_point"] = {"x": 221, "y": 240}
    assert validate_current_grounding(asset, selection, _grounding(asset), wrong_point, policy=policy)["failure_code"] == "pre_click_rejected"
    missing_grounding_ref = _grounding(asset)
    missing_grounding_ref["evidence_refs"] = []
    assert validate_current_grounding(asset, selection, missing_grounding_ref, _gate(asset, selection), policy=policy)["failure_code"] == "target_unresolved"
    missing_gate_ref = _gate(asset, selection)
    missing_gate_ref["evidence_refs"] = []
    assert validate_current_grounding(asset, selection, _grounding(asset), missing_gate_ref, policy=policy)["failure_code"] == "pre_click_rejected"
    grounding_injection = _grounding(asset)
    grounding_injection["unexpected_lineage"] = "forged"
    assert validate_current_grounding(asset, selection, grounding_injection, _gate(asset, selection), policy=policy)["failure_code"] == "target_unresolved"
    gate_injection = _gate(asset, selection)
    gate_injection["bbox"] = {"x": 1, "y": 1, "w": 2, "h": 2}
    assert validate_current_grounding(asset, selection, _grounding(asset), gate_injection, policy=policy)["failure_code"] == "pre_click_rejected"


@pytest.mark.parametrize("field,value", [("confidence", math.nan), ("score_margin", math.inf), ("confidence", True)])
def test_grounding_rejects_nonfinite_numbers(field: str, value: float) -> None:
    from app.agent.reviewed_workflow_replay import validate_current_grounding

    asset = _asset()
    grounding = _grounding(asset)
    grounding[field] = value
    selection = _selection(asset)
    result = validate_current_grounding(asset, selection, grounding, _gate(asset, selection), policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2})
    assert result["failure_code"] == "grounding_ambiguous"


def test_post_verification_accepts_trusted_enriched_adapter_envelope_and_new_semantic_capture() -> None:
    from app.agent.reviewed_workflow_replay import verify_transition_result

    asset = _asset()
    selection = _selection(asset)
    verified = verify_transition_result(asset, selection, _operation(selection), _observation(asset, "capture-2", "d" * 64, "anchor_detail", "quick_apply", origin="HTTPS://NZ.SEEK.COM:443"))
    assert verified["status"] == "verified"
    assert verified["state_advanced"] is True
    alias_operation = _operation(selection)
    alias_operation["source_freshness"]["viewport_size"] = alias_operation["source_freshness"].pop("viewport")
    assert verify_transition_result(asset, selection, alias_operation, _observation(asset, "capture-2", "d" * 64, "anchor_detail"))["status"] == "verified"


@pytest.mark.parametrize("post_action_verified", [False, None])
def test_post_verification_ignores_caller_supplied_post_action_verified(post_action_verified: bool | None) -> None:
    from app.agent.reviewed_workflow_replay import verify_transition_result

    asset = _asset()
    selection = _selection(asset)
    operation = _operation(selection)
    if post_action_verified is None:
        operation.pop("post_action_verified")
    else:
        operation["post_action_verified"] = post_action_verified

    result = verify_transition_result(
        asset,
        selection,
        operation,
        _observation(asset, "capture-2", "d" * 64, "anchor_detail"),
    )

    assert result["status"] == "verified", result
    assert result["state_advanced"] is True


def test_post_rejects_forged_selection_old_capture_wrong_state_and_operation_shortcut() -> None:
    from app.agent.reviewed_workflow_replay import verify_transition_result

    asset = _asset()
    selection = _selection(asset)
    forged = copy.deepcopy(selection)
    forged["target_state_id"] = "apply_entry"
    assert verify_transition_result(asset, forged, _operation(selection), _observation(asset, "capture-2", "d" * 64, "anchor_detail"))["failure_code"] == "selection_lineage_mismatch"
    same_id = _observation(asset, "capture-1", "d" * 64, "anchor_detail")
    assert verify_transition_result(asset, selection, _operation(selection), same_id)["failure_code"] == "post_capture_not_new"
    wrong = _observation(asset, "capture-2", "d" * 64, "anchor_homepage")
    assert verify_transition_result(asset, selection, _operation(selection), wrong)["failure_code"] == "destination_mismatch"
    shortcut = {"success": True, "executed_verified": True}
    assert verify_transition_result(asset, selection, shortcut, _observation(asset, "capture-2", "d" * 64, "anchor_detail"))["failure_code"] == "operation_lineage_mismatch"
    cross_asset = _observation(asset, "capture-2", "d" * 64, "anchor_detail")
    cross_asset["expected_asset_content_sha256"] = "e" * 64
    assert verify_transition_result(asset, selection, _operation(selection), cross_asset)["failure_code"] == "asset_lineage_mismatch"
    unbound = _operation(selection)
    unbound.pop("replay_context")
    assert verify_transition_result(asset, selection, unbound, _observation(asset, "capture-2", "d" * 64, "anchor_detail"))["failure_code"] == "operation_lineage_mismatch"
    missing_replay_contract = _operation(selection)
    missing_replay_contract["replay_context"].pop("contract_version")
    assert verify_transition_result(asset, selection, missing_replay_contract, _observation(asset, "capture-2", "d" * 64, "anchor_detail"))["failure_code"] == "operation_lineage_mismatch"
    wrong_replay_contract = _operation(selection)
    wrong_replay_contract["replay_context"]["contract_version"] = "forged_replay_context"
    assert verify_transition_result(asset, selection, wrong_replay_contract, _observation(asset, "capture-2", "d" * 64, "anchor_detail"))["failure_code"] == "operation_lineage_mismatch"
    extra_replay_context = _operation(selection)
    extra_replay_context["replay_context"]["extra"] = "forged"
    assert verify_transition_result(asset, selection, extra_replay_context, _observation(asset, "capture-2", "d" * 64, "anchor_detail"))["failure_code"] == "operation_lineage_mismatch"
    no_plan = _operation(selection)
    no_plan["approved_plan_id"] = ""
    assert verify_transition_result(asset, selection, no_plan, _observation(asset, "capture-2", "d" * 64, "anchor_detail"))["failure_code"] == "operation_lineage_mismatch"
    wrong_viewport = _operation(selection)
    wrong_viewport["source_freshness"]["viewport"] = {"width": 1, "height": 1}
    assert verify_transition_result(asset, selection, wrong_viewport, _observation(asset, "capture-2", "d" * 64, "anchor_detail"))["failure_code"] == "capture_lineage_mismatch"
    conflicting_alias = _operation(selection)
    conflicting_alias["source_freshness"]["viewport_size"] = selection["capture_lineage"]["viewport_size"]
    conflicting_alias["source_freshness"]["viewport"] = {"width": 1, "height": 1}
    assert verify_transition_result(asset, selection, conflicting_alias, _observation(asset, "capture-2", "d" * 64, "anchor_detail"))["failure_code"] == "capture_lineage_mismatch"
    freshness_injection = _operation(selection)
    freshness_injection["source_freshness"]["click_point"] = {"x": 220, "y": 240}
    assert verify_transition_result(asset, selection, freshness_injection, _observation(asset, "capture-2", "d" * 64, "anchor_detail"))["failure_code"] == "capture_lineage_mismatch"
    missing_evidence = _operation(selection)
    missing_evidence["evidence_refs"] = []
    assert verify_transition_result(asset, selection, missing_evidence, _observation(asset, "capture-2", "d" * 64, "anchor_detail"))["failure_code"] == "operation_evidence_missing"


@pytest.mark.parametrize(
    "reason",
    [
        "stale_approved_plan", "capture_lineage_mismatch", "pre_click_rejected",
        "foreground_window_changed", "foreground_changed", "foreground_change",
    ],
)
def test_nonexecuted_operation_preserves_gate_rejection_reason(reason: str) -> None:
    from app.agent.reviewed_workflow_replay import verify_transition_result

    asset = _asset()
    selection = _selection(asset)
    operation = _operation(selection)
    operation["action_executed"] = False
    operation["post_action_verified"] = False
    operation["gate_result"] = {"allowed": False, "reason": reason}
    result = verify_transition_result(asset, selection, operation, _observation(asset, "capture-2", "d" * 64, "anchor_detail"))
    assert result["failure_code"] == reason


def test_server_dispatch_verifier_uses_only_observations_and_server_evidence() -> None:
    import inspect

    from app.agent.reviewed_workflow_replay import verify_server_dispatched_transition_result

    asset = _asset()
    selection = _selection(asset)
    before = _observation(asset, "capture-1", "a" * 64, "anchor_homepage", "job_card")
    after = _observation(asset, "capture-2", "d" * 64, "anchor_detail", "quick_apply")

    assert list(inspect.signature(verify_server_dispatched_transition_result).parameters) == [
        "asset", "selection", "before_observation", "post_observation", "server_evidence_refs",
    ]
    result = verify_server_dispatched_transition_result(
        asset,
        selection,
        before,
        after,
        server_evidence_refs=["server:dispatch:2", "server:dispatch:1", "server:dispatch:2"],
    )

    assert result == {
        "contract_version": "transition_verification_v1",
        "status": "verified",
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "state_advanced": True,
        "asset_content_sha256": selection["asset_content_sha256"],
        "selection_sha256": selection["selection_sha256"],
        "transition_id": "open_detail",
        "source_state_id": "homepage",
        "target_state_id": "detail",
        "post_capture_lineage": {
            "capture_id": "capture-2",
            "screenshot_sha256": "d" * 64,
            "viewport_size": {"width": 1440, "height": 900},
        },
        "post_state_resolution": result["post_state_resolution"],
        "evidence_refs": [
            "evidence:capture-2:anchor_detail",
            "evidence:capture-2:quick_apply",
            "server:dispatch:1",
            "server:dispatch:2",
        ],
    }
    assert result["post_state_resolution"]["status"] == "resolved"
    assert result["post_state_resolution"]["state_id"] == "detail"


def test_server_dispatch_verifier_maps_only_semantic_post_outcomes() -> None:
    from app.agent.reviewed_workflow_replay import verify_server_dispatched_transition_result

    asset = _asset()
    selection = _selection(asset)
    before = _observation(asset, "capture-1", "a" * 64, "anchor_homepage", "job_card")

    same_capture = verify_server_dispatched_transition_result(
        asset,
        selection,
        before,
        _observation(asset, "capture-1", "a" * 64, "anchor_detail"),
        server_evidence_refs=["server:dispatch"],
    )
    assert same_capture == {
        "contract_version": "transition_verification_v1",
        "status": "blocked",
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "failure_code": "post_capture_not_new",
        "state_advanced": False,
    }

    wrong = verify_server_dispatched_transition_result(
        asset,
        selection,
        before,
        _observation(asset, "capture-2", "d" * 64, "anchor_homepage"),
        server_evidence_refs=["server:dispatch"],
    )
    assert wrong["failure_code"] == "destination_mismatch"
    assert wrong["post_state_resolution"]["status"] == "resolved"
    assert wrong["post_state_resolution"]["state_id"] == "homepage"

    for after in (
        _observation(asset, "capture-2", "d" * 64),
        _observation(asset, "capture-2", "d" * 64, "anchor_homepage", "anchor_detail"),
    ):
        unresolved = verify_server_dispatched_transition_result(
            asset, selection, before, after, server_evidence_refs=["server:dispatch"]
        )
        assert unresolved["failure_code"] == "post_action_failure"
        assert unresolved["post_state_resolution"]["status"] == "blocked"
        assert unresolved["post_state_resolution"]["failure_code"] in {
            "current_state_unresolved", "current_state_ambiguous",
        }


def test_server_dispatch_verifier_preserves_strict_post_observation_failures() -> None:
    from app.agent.reviewed_workflow_replay import verify_server_dispatched_transition_result

    asset = _asset()
    selection = _selection(asset)
    before = _observation(asset, "capture-1", "a" * 64, "anchor_homepage", "job_card")
    cases = []
    cross_asset = _observation(asset, "capture-2", "d" * 64, "anchor_detail")
    cross_asset["expected_asset_content_sha256"] = "e" * 64
    cases.append((cross_asset, "asset_lineage_mismatch"))
    wrong_origin = _observation(asset, "capture-2", "d" * 64, "anchor_detail", origin="https://evil.example")
    cases.append((wrong_origin, "unexpected_origin"))
    malformed_capture = _observation(asset, "capture-2", "not-a-sha", "anchor_detail")
    cases.append((malformed_capture, "capture_missing"))
    malformed_contract = _observation(asset, "capture-2", "d" * 64, "anchor_detail")
    malformed_contract["approved_plan_id"] = "caller-forged"
    cases.append((malformed_contract, "invalid_observation_contract"))

    for after, failure_code in cases:
        result = verify_server_dispatched_transition_result(
            asset, selection, before, after, server_evidence_refs=["server:dispatch"]
        )
        assert result["failure_code"] == failure_code
        assert result["post_state_resolution"]["failure_code"] == failure_code
        assert result["state_advanced"] is False
        assert result["artifact_is_authorization"] is False
        assert result["execute_binding_enabled"] is False


@pytest.mark.parametrize(
    "rules",
    [
        [{"rule_id": "detail_identity", "type": "caller_verification_flag"}],
        [{"rule_id": "detail_identity", "type": "target_state_identity", "approved_plan_id": "forged"}],
        [{"rule_id": "detail_identity"}],
    ],
)
def test_server_dispatch_verifier_rejects_nonexact_semantic_rules_before_success(rules: list[dict]) -> None:
    from app.agent.reviewed_workflow_replay import verify_server_dispatched_transition_result

    asset = _asset()
    asset["transitions"][0]["post_action_verification"]["semantic_success_rules"] = rules
    selection = _selection(asset)
    result = verify_server_dispatched_transition_result(
        asset,
        selection,
        _observation(asset, "capture-1", "a" * 64, "anchor_homepage", "job_card"),
        _observation(asset, "capture-2", "d" * 64, "anchor_detail"),
        server_evidence_refs=["server:dispatch"],
    )
    assert result["failure_code"] == "unsupported_semantic_success_rule"
    assert result["state_advanced"] is False


@pytest.mark.parametrize(
    "failure_code,expected",
    [
        ("stale_capture", "reobserve_and_reground_once"), ("stale_approved_plan", "reobserve_and_reground_once"),
        ("target_not_found", "reobserve_and_reground_once"), ("target_unresolved", "reobserve_and_reground_once"), ("capture_missing", "reobserve_and_reground_once"),
        ("capture_lineage_mismatch", "reobserve_and_reground_once"), ("stale_candidate", "reobserve_and_reground_once"),
        ("post_action_failure", "observe_without_repeat"), ("post_capture_not_new", "observe_without_repeat"),
        ("unexpected_origin", "safe_stop_human_review"), ("destination_mismatch", "safe_stop_human_review"),
        ("foreground_window_changed", "safe_stop_human_review"), ("foreground_changed", "safe_stop_human_review"),
        ("foreground_change", "safe_stop_human_review"), ("pre_click_rejected", "safe_stop_human_review"),
        ("dangerous", "safe_stop_human_review"),
    ],
)
def test_recovery_matrix_never_repeats_action(failure_code: str, expected: str) -> None:
    from app.agent.reviewed_workflow_replay import build_recovery_decision

    result = build_recovery_decision(_asset()["transitions"][0], failure_code, attempts_used=0)
    assert result["decision"] == expected
    assert result["repeat_action"] is False
    exhausted = build_recovery_decision(_asset()["transitions"][0], failure_code, attempts_used=1)
    assert exhausted["failure_code"] == "recovery_exhausted"
    assert exhausted["repeat_action"] is False
