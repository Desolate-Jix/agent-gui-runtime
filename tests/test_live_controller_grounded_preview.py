from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from app.agent.grounded_action_preview import GroundedActionPreview
from app.agent.live_controller import LiveControllerDecision
from app.agent.runtime_contracts import (
    validate_agent_intent_v1,
    validate_agent_observation_v1,
)
from tests.test_live_controller_w4 import (
    _Gate,
    _WindowVisibilityChecker,
    _controller,
    _current_observation,
    _intent,
)
from tests.test_reviewed_workflow_asset_v2 import _asset


class _ReviewGate(_Gate):
    def evaluate_review(self, *, selection: dict, grounding: dict, **context) -> dict:
        return super().evaluate(selection=selection, grounding=grounding)


class _RiskConsistentObservationSource:
    def __init__(self, inner, *, requires_confirmation: bool) -> None:
        self._inner = inner
        self._requires_confirmation = requires_confirmation

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def create_initial(self, **kwargs):
        return self._inner.create_initial(**kwargs)

    def capture_projected(self, **kwargs):
        projected = self._inner.capture_projected(**kwargs)
        payload = projected.agent_observation.model_dump(mode="json")
        action = next(
            item for item in payload["available_actions"] if item["action_id"] == "open_detail"
        )
        action["requires_user_confirmation"] = self._requires_confirmation
        action["risk_level"] = "medium" if self._requires_confirmation else "low"
        return replace(
            projected,
            agent_observation=validate_agent_observation_v1(payload),
        )


def _review_controller(tmp_path, **kwargs):
    result = _controller(tmp_path, **kwargs)
    result[0]._gate = _ReviewGate(allowed=result[3].allowed)
    source = result[1]
    asset = kwargs.get("asset_override")
    if asset is not None:
        transition = next(
            item for item in asset["transitions"] if item["transition_id"] == "open_detail"
        )
        source = _RiskConsistentObservationSource(
            source,
            requires_confirmation=transition["risk_policy"][
                "requires_user_confirmation"
            ],
        )
        result[0]._observation_source = source
    return result[0], source, result[2], result[0]._gate, result[4]


def _canonical_hash(payload: dict, *excluded: str) -> str:
    encoded = json.dumps(
        {key: value for key, value in payload.items() if key not in set(excluded)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _rehash_outer(payload: dict) -> None:
    payload["content_sha256"] = _canonical_hash(payload, "content_sha256")


@pytest.mark.parametrize("requires_confirmation", [False, True])
def test_real_controller_prepares_immutable_grounded_review_without_dispatch_or_claim(
    tmp_path,
    requires_confirmation: bool,
) -> None:
    asset = _asset()
    asset["transitions"][0]["risk_policy"]["requires_user_confirmation"] = (
        requires_confirmation
    )
    if requires_confirmation:
        asset["transitions"][0]["risk_policy"]["automatic_execution_allowed"] = False
    controller, source, resolver, gate, backend = _review_controller(
        tmp_path,
        asset_override=asset,
        target_window_handle=5000 + int(requires_confirmation),
    )
    session = controller.start_session()
    payload = _intent(session)
    payload_before = deepcopy(payload)

    result = controller.prepare_grounded_review(payload, target_process_id=9001)

    assert isinstance(result, GroundedActionPreview)
    first = result.to_dict()
    assert set(first) == {
        "contract_version",
        "status",
        "review_only",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "grants_action_authority",
        "session_id",
        "observation_id",
        "intent_id",
        "workflow",
        "target_window_handle",
        "target_process_id",
        "current_observation",
        "review_selection",
        "grounding_preview",
        "content_sha256",
    }
    assert first["contract_version"] == "grounded_action_preview_v1"
    assert first["status"] == "prepared"
    assert first["review_only"] is True
    assert first["artifact_is_authorization"] is False
    assert first["execute_binding_enabled"] is False
    assert first["grants_action_authority"] is False
    assert first["session_id"] == session.session_id
    assert first["observation_id"] == session.current_observation.observation_id
    assert first["intent_id"] == "intent.open-detail"
    assert first["workflow"] == session.workflow.model_dump(mode="json")
    assert first["target_window_handle"] == 5000 + int(requires_confirmation)
    assert first["target_process_id"] == 9001
    assert first["current_observation"]["current_capture"]["capture_id"] == "capture-current"
    assert first["grounding_preview"]["candidate_id"] == "candidate-current"
    assert first["grounding_preview"]["bbox"] == {
        "x": 100,
        "y": 200,
        "w": 300,
        "h": 80,
    }
    assert first["grounding_preview"]["click_point"] == {"x": 220, "y": 240}
    first["workflow"]["workflow_id"] = "mutated"
    first["grounding_preview"]["bbox"]["x"] = 0
    second = result.to_dict()
    assert second["workflow"]["workflow_id"] == "workflow.seek.portfolio"
    assert second["grounding_preview"]["bbox"]["x"] == 100
    assert payload == payload_before
    assert source.projected_calls == 1
    assert resolver.calls == 1
    assert gate.calls == 1
    assert backend.attempt_count == 0
    assert (
        controller._intent_claim_store.find_for_observation(
            session_id=session.session_id,
            observation_id=session.current_observation.observation_id,
        )
        is None
    )

    controller.abandon_session(session_id=session.session_id)


@pytest.mark.parametrize(
    "target_process_id,target_window_handle",
    [(True, 5101), (0, 5102), (-1, 5103), (1.0, 5104), ("9001", 5105)],
)
def test_prepare_rejects_invalid_server_process_id_before_capture(
    tmp_path,
    target_process_id,
    target_window_handle: int,
) -> None:
    controller, source, resolver, gate, backend = _review_controller(
        tmp_path,
        target_window_handle=target_window_handle,
    )
    session = controller.start_session()

    result = controller.prepare_grounded_review(
        _intent(session),
        target_process_id=target_process_id,
    )

    assert isinstance(result, LiveControllerDecision)
    assert result.status == "REJECTED"
    assert result.reason_code == "invalid_target_process_id"
    assert result.confirmation_id is None
    assert source.projected_calls == 0
    assert resolver.calls == 0
    assert gate.calls == 0
    assert backend.attempt_count == 0
    controller.abandon_session(session_id=session.session_id)


def test_prepare_rejects_pid_drift_and_capture_reuse_without_consuming_session(tmp_path) -> None:
    controller, source, resolver, gate, backend = _review_controller(
        tmp_path,
        target_window_handle=5200,
    )
    session = controller.start_session()

    wrong_pid = controller.prepare_grounded_review(_intent(session), target_process_id=9002)

    assert isinstance(wrong_pid, LiveControllerDecision)
    assert wrong_pid.status == "REJECTED"
    assert wrong_pid.reason_code == "target_process_changed"
    assert wrong_pid.confirmation_id is None
    assert resolver.calls == gate.calls == backend.attempt_count == 0
    controller.abandon_session(session_id=session.session_id)


def test_unknown_and_claimed_sessions_never_prepare_or_dispatch(tmp_path) -> None:
    controller, source, resolver, gate, backend = _review_controller(
        tmp_path,
        target_window_handle=5300,
    )
    session = controller.start_session()
    unknown = _intent(session)
    unknown["session_id"] = "session.unknown"

    rejected = controller.prepare_grounded_review(unknown, target_process_id=9001)

    assert isinstance(rejected, LiveControllerDecision)
    assert rejected.status == "REJECTED"
    assert rejected.reason_code == "unknown_session"
    assert rejected.confirmation_id is None
    assert source.projected_calls == resolver.calls == gate.calls == backend.attempt_count == 0

    controller._intent_claim_store.claim(
        observation=session.current_observation,
        intent=validate_agent_intent_v1(
            _intent(session), observation=session.current_observation
        ),
        server_binding={
            "workflow_id": controller._binding.workflow_id,
            "asset_id": controller._binding.asset_id,
            "application_identity_key": controller._binding.application_identity_key,
            "target_window_handle": controller._binding.target_window_handle,
        },
    )
    claimed = controller.prepare_grounded_review(_intent(session), target_process_id=9001)
    assert isinstance(claimed, LiveControllerDecision)
    assert claimed.status == "REJECTED"
    assert claimed.reason_code == "observation_consumed"
    assert claimed.confirmation_id is None
    assert source.projected_calls == resolver.calls == gate.calls == backend.attempt_count == 0


def test_foreign_consumed_and_stale_capture_previews_fail_before_grounding(tmp_path) -> None:
    foreign_controller, _, _, _, foreign_backend = _review_controller(
        tmp_path / "foreign",
        target_window_handle=5400,
    )
    owner, _, _, _, owner_backend = _review_controller(
        tmp_path / "owner",
        target_window_handle=5401,
    )
    owner_session = owner.start_session()
    foreign = foreign_controller.prepare_grounded_review(
        _intent(owner_session),
        target_process_id=9001,
    )
    assert isinstance(foreign, LiveControllerDecision)
    assert foreign.reason_code == "unknown_session"
    assert foreign_backend.attempt_count == owner_backend.attempt_count == 0

    consumed_controller, source, resolver, gate, backend = _review_controller(
        tmp_path / "consumed",
        target_window_handle=5402,
    )
    consumed_session = consumed_controller.start_session()
    consumed_controller._sessions[consumed_session.session_id].consumed = True
    consumed = consumed_controller.prepare_grounded_review(
        _intent(consumed_session),
        target_process_id=9001,
    )
    assert isinstance(consumed, LiveControllerDecision)
    assert consumed.reason_code == "observation_consumed"
    assert source.projected_calls == resolver.calls == gate.calls == backend.attempt_count == 0

    asset = _asset()
    stale_controller, source, resolver, gate, backend = _review_controller(
        tmp_path / "stale",
        asset_override=asset,
        current=_current_observation(asset, capture_id="capture-initial"),
        target_window_handle=5403,
    )
    stale_session = stale_controller.start_session()
    stale = stale_controller.prepare_grounded_review(
        _intent(stale_session),
        target_process_id=9001,
    )
    assert isinstance(stale, LiveControllerDecision)
    assert stale.reason_code == "stale_candidate"
    assert resolver.calls == gate.calls == backend.attempt_count == 0
    owner.abandon_session(session_id=owner_session.session_id)
    stale_controller.abandon_session(session_id=stale_session.session_id)


@pytest.mark.parametrize(
    "options,reason_code,target_window_handle",
    [
        ({"resolver_status": "ambiguous"}, "grounding_ambiguous", 5501),
        ({"gate_allowed": False}, "pre_click_rejected", 5502),
        (
            {
                "visibility_checker": _WindowVisibilityChecker(
                    bound_window_handle=5503,
                    visible=False,
                )
            },
            "target_occluded",
            5503,
        ),
    ],
)
def test_grounding_gate_and_visibility_failures_never_dispatch(
    tmp_path,
    options: dict,
    reason_code: str,
    target_window_handle: int,
) -> None:
    controller, _, _, _, backend = _review_controller(
        tmp_path,
        target_window_handle=target_window_handle,
        **options,
    )
    session = controller.start_session()

    result = controller.prepare_grounded_review(_intent(session), target_process_id=9001)

    assert isinstance(result, LiveControllerDecision)
    assert result.status == "REJECTED"
    assert result.reason_code == reason_code
    assert result.confirmation_id is None
    assert backend.attempt_count == 0
    controller.abandon_session(session_id=session.session_id)


def test_missing_review_gate_is_not_bypassed_through_execution_gate(tmp_path) -> None:
    controller, source, resolver, gate, backend = _controller(
        tmp_path,
        target_window_handle=5600,
    )
    session = controller.start_session()

    result = controller.prepare_grounded_review(_intent(session), target_process_id=9001)

    assert isinstance(result, LiveControllerDecision)
    assert result.status == "RECOVERY_REQUIRED"
    assert result.reason_code == "review_gate_unavailable"
    assert result.confirmation_id is None
    assert resolver.calls == gate.calls == backend.attempt_count == 0
    controller.abandon_session(session_id=session.session_id)


def test_preview_cannot_be_submitted_as_confirmation_or_execution_authority(tmp_path) -> None:
    controller, _, _, _, backend = _review_controller(
        tmp_path,
        target_window_handle=5700,
    )
    session = controller.start_session()
    intent = _intent(session)
    preview = controller.prepare_grounded_review(intent, target_process_id=9001)
    assert isinstance(preview, GroundedActionPreview)
    forged = deepcopy(intent)
    forged["human_confirmation"] = preview.to_dict()

    result = controller.submit_intent(forged)

    assert isinstance(result, LiveControllerDecision)
    assert result.status == "REJECTED"
    assert result.reason_code == "invalid_intent"
    assert result.confirmation_id is None
    assert backend.attempt_count == 0
    controller.abandon_session(session_id=session.session_id)


def test_preview_constructor_and_hash_reject_forged_bytes(tmp_path) -> None:
    with pytest.raises(ValueError, match="preview"):
        GroundedActionPreview(b"{}")

    controller, _, _, _, _ = _review_controller(
        tmp_path,
        target_window_handle=5800,
    )
    session = controller.start_session()
    preview = controller.prepare_grounded_review(_intent(session), target_process_id=9001)
    assert isinstance(preview, GroundedActionPreview)
    forged = preview.to_dict()
    forged["target_process_id"] = 9999
    forged_bytes = json.dumps(
        forged,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")

    with pytest.raises(ValueError, match="hash"):
        GroundedActionPreview(forged_bytes)
    controller.abandon_session(session_id=session.session_id)


def test_preview_rejects_bbox_tamper_even_when_outer_hash_is_recomputed(tmp_path) -> None:
    controller, _, _, _, _ = _review_controller(
        tmp_path,
        target_window_handle=5900,
    )
    session = controller.start_session()
    try:
        preview = controller.prepare_grounded_review(
            _intent(session), target_process_id=9001
        )
        assert isinstance(preview, GroundedActionPreview)
        forged = preview.to_dict()
        forged["grounding_preview"]["bbox"]["x"] = 877
        _rehash_outer(forged)

        with pytest.raises(ValueError, match="grounding preview"):
            GroundedActionPreview.from_dict(forged)
        with pytest.raises(ValueError, match="grounding preview"):
            GroundedActionPreview(
                json.dumps(
                    forged,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            )
    finally:
        controller.abandon_session(session_id=session.session_id)


@pytest.mark.parametrize(
    "target,mutation,target_window_handle",
    [
        ("review_selection", lambda value: value.update(extra=True), 5911),
        ("review_selection", lambda value: value.pop("requirements"), 5912),
        ("grounding_preview", lambda value: value.update(extra=True), 5913),
        ("grounding_preview", lambda value: value.pop("candidate_id"), 5914),
    ],
)
def test_preview_rejects_missing_or_extra_nested_fields_with_fresh_outer_hash(
    tmp_path,
    target: str,
    mutation,
    target_window_handle: int,
) -> None:
    controller, _, _, _, _ = _review_controller(
        tmp_path,
        target_window_handle=target_window_handle,
    )
    session = controller.start_session()
    try:
        preview = controller.prepare_grounded_review(
            _intent(session), target_process_id=9001
        )
        assert isinstance(preview, GroundedActionPreview)
        forged = preview.to_dict()
        mutation(forged[target])
        _rehash_outer(forged)

        with pytest.raises(ValueError, match="shape"):
            GroundedActionPreview.from_dict(forged)
    finally:
        controller.abandon_session(session_id=session.session_id)


@pytest.mark.parametrize(
    "mutation,target_window_handle",
    [
        (
            lambda value: value["review_selection"].update(
                transition_id="open_apply_flow"
            ),
            5921,
        ),
        (
            lambda value: value["review_selection"]["capture_lineage"].update(
                capture_id="capture-rebound"
            ),
            5922,
        ),
    ],
)
def test_preview_rejects_independently_rehashed_nested_cross_binding(
    tmp_path,
    mutation,
    target_window_handle: int,
) -> None:
    controller, _, _, _, _ = _review_controller(
        tmp_path,
        target_window_handle=target_window_handle,
    )
    session = controller.start_session()
    try:
        preview = controller.prepare_grounded_review(
            _intent(session), target_process_id=9001
        )
        assert isinstance(preview, GroundedActionPreview)
        forged = preview.to_dict()
        mutation(forged)
        selection = forged["review_selection"]
        review_hash = _canonical_hash(
            selection,
            "review_selection_sha256",
            "selection_sha256",
        )
        selection["review_selection_sha256"] = review_hash
        selection["selection_sha256"] = review_hash
        _rehash_outer(forged)

        with pytest.raises(ValueError, match="binding"):
            GroundedActionPreview.from_dict(forged)
    finally:
        controller.abandon_session(session_id=session.session_id)


def test_preview_rejects_candidate_and_workflow_rebinding_and_roundtrips_valid_bytes(
    tmp_path,
) -> None:
    controller, _, _, _, _ = _review_controller(
        tmp_path,
        target_window_handle=5930,
    )
    session = controller.start_session()
    try:
        preview = controller.prepare_grounded_review(
            _intent(session), target_process_id=9001
        )
        assert isinstance(preview, GroundedActionPreview)
        assert GroundedActionPreview.from_dict(preview.to_dict()) == preview

        candidate = preview.to_dict()
        candidate["grounding_preview"]["candidate_id"] = "candidate-forged"
        _rehash_outer(candidate)
        with pytest.raises(ValueError, match="grounding preview"):
            GroundedActionPreview.from_dict(candidate)

        workflow = preview.to_dict()
        workflow["workflow"]["reviewed_revision_hash"] = "0" * 64
        _rehash_outer(workflow)
        with pytest.raises(ValueError, match="binding"):
            GroundedActionPreview.from_dict(workflow)
    finally:
        controller.abandon_session(session_id=session.session_id)
