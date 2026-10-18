from app.agent.desktop_backend import DeterministicFakeBackend
from app.agent.live_controller import LiveController
from app.agent.runtime_contracts import RuntimeResultReceiptV1
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStoreError
from tests.test_agent_runtime_grounded_preview import _request, live
from tests.test_live_controller_grounded_preview import _review_controller
from tests.test_live_controller_w4 import _current_observation, _intent


def test_controller_consumes_approved_grounded_review_once(live):
    observation = live.service.start_session()
    source = live.sources[0]
    source.post_current_sequence = [
        _current_observation(
            source.asset,
            capture_id="capture-consume-fresh",
            anchors=("anchor_detail", "quick_apply"),
        ),
        _current_observation(
            source.asset,
            capture_id="capture-consume-post",
            anchors=("anchor_apply_entry",),
        ),
    ]
    pending = live.service.request_grounded_confirmation(_request(observation))
    confirmation_id = pending.grounded_confirmation.confirmation_id
    live.service.decide_grounded_confirmation(
        confirmation_id=confirmation_id,
        decision="approved",
    )

    try:
        result = live.controllers[0].consume_grounded_confirmation(
            confirmation_id=confirmation_id
        )

        assert result.attempt_count == 1
        assert live.backends[0].attempt_count == 1
        assert live.sources[0].projected_calls == 3
        assert any(ref.startswith("grounded-consume:") for ref in result.evidence.trace_refs)
    finally:
        claim = live.claims.get_for_grounded_confirmation(confirmation_id=confirmation_id)
        if claim.phase == "grounded_confirmation_approved":
            live.service.cancel_grounded_review(session_id=observation.session_id)


def test_grounded_consume_without_live_publication_owner_never_recaptures(live):
    observation = live.service.start_session()
    pending = live.service.request_grounded_confirmation(_request(observation))
    confirmation_id = pending.grounded_confirmation.confirmation_id
    live.service.decide_grounded_confirmation(
        confirmation_id=confirmation_id, decision="approved"
    )
    controller = live.controllers[0]
    context = controller._grounded_publications.pop(observation.session_id)
    try:
        result = controller.consume_grounded_confirmation(
            confirmation_id=confirmation_id
        )
        assert result.status == "RECOVERY_REQUIRED"
        assert result.reason_code == "grounded_confirmation_owner_unavailable"
        assert live.sources[0].projected_calls == 1
        assert live.backends[0].attempt_count == 0
    finally:
        controller._grounded_publications[observation.session_id] = context
        live.service.cancel_grounded_review(session_id=observation.session_id)


def test_execution_gate_must_be_recomputed_before_consume_and_dispatch(live, monkeypatch):
    observation = live.service.start_session()
    source = live.sources[0]
    source.post_current_sequence = [
        _current_observation(
            source.asset,
            capture_id="capture-gate-fresh",
            anchors=("anchor_detail", "quick_apply"),
        )
    ]
    pending = live.service.request_grounded_confirmation(_request(observation))
    confirmation_id = pending.grounded_confirmation.confirmation_id
    live.service.decide_grounded_confirmation(
        confirmation_id=confirmation_id, decision="approved"
    )
    controller = live.controllers[0]

    def reject_execution_gate(**_kwargs):
        raise ValueError("synthetic missing execution gate")

    monkeypatch.setattr(controller._gate, "evaluate", reject_execution_gate)
    try:
        result = controller.consume_grounded_confirmation(
            confirmation_id=confirmation_id
        )
        assert result.status == "RECOVERY_REQUIRED"
        assert result.reason_code == "grounded_execution_validation_failed"
        assert live.backends[0].attempt_count == 0
        assert not tuple(live.claims.grounded_consume_root.iterdir())
    finally:
        live.service.cancel_grounded_review(session_id=observation.session_id)


def test_non_risky_transition_still_requires_grounded_approval_and_two_fresh_gates(tmp_path):
    controller, source, resolver, gate, backend = _review_controller(
        tmp_path, target_window_handle=88501
    )
    session = controller.start_session()
    source.post_current_sequence = [
        _current_observation(source.asset, capture_id="capture-fresh-home"),
        _current_observation(
            source.asset,
            capture_id="capture-post-detail",
            anchors=("anchor_detail", "quick_apply"),
        ),
    ]
    pending = controller.request_grounded_confirmation(
        _intent(session), target_process_id=9001
    )
    confirmation_id = pending.grounded_confirmation.confirmation_id
    controller.record_grounded_confirmation_decision(
        confirmation_id=confirmation_id, decision="approved"
    )

    result = controller.consume_grounded_confirmation(confirmation_id=confirmation_id)

    assert isinstance(result, RuntimeResultReceiptV1)
    assert result.attempt_count == 1
    assert backend.attempt_count == 1
    assert source.projected_calls == 3
    assert resolver.calls == 2
    assert gate.calls == 3


def test_reopened_controller_checkpoint_recovery_retains_exact_lease_cleanup(
    tmp_path, monkeypatch
):
    controller, source, resolver, gate, backend = _review_controller(
        tmp_path, target_window_handle=88502
    )
    session = controller.start_session()
    source.post_current_sequence = [
        _current_observation(source.asset, capture_id="capture-recovery-fresh"),
        _current_observation(
            source.asset,
            capture_id="capture-recovery-post",
            anchors=("anchor_detail", "quick_apply"),
        ),
    ]
    pending = controller.request_grounded_confirmation(
        _intent(session), target_process_id=9001
    )
    confirmation_id = pending.grounded_confirmation.confirmation_id
    controller.record_grounded_confirmation_decision(
        confirmation_id=confirmation_id, decision="approved"
    )
    persist = controller._intent_claim_store.persist_grounded_terminal
    persist_calls = 0

    def fail_terminal_once(**kwargs):
        nonlocal persist_calls
        persist_calls += 1
        if persist_calls == 1:
            raise RuntimeIntentClaimStoreError("synthetic terminal write failure")
        return persist(**kwargs)

    monkeypatch.setattr(
        controller._intent_claim_store,
        "persist_grounded_terminal",
        fail_terminal_once,
    )
    first = controller.consume_grounded_confirmation(confirmation_id=confirmation_id)
    assert first.reason_code == "receipt_persistence_failed"
    assert backend.attempt_count == 1

    original_session = controller._sessions[session.session_id]
    controller._release_window_lease(original_session.window_lease)
    recovery_backend = DeterministicFakeBackend()
    recovery = LiveController(
        binding=controller._binding,
        asset_loader=controller._asset_loader,
        observation_source=source,
        target_resolver=resolver,
        gate=gate,
        window_visibility_checker=controller._window_visibility_checker,
        backend=recovery_backend,
        intent_claim_store=controller._intent_claim_store,
        grounding_policy=controller._grounding_policy,
    )
    release = recovery._release_window_lease
    release_calls = 0

    def fail_release_once(lease):
        nonlocal release_calls
        release_calls += 1
        if release_calls == 1:
            raise RuntimeError("synthetic recovery lease release failure")
        return release(lease)

    monkeypatch.setattr(recovery, "_release_window_lease", fail_release_once)
    try:
        recovered = recovery.consume_grounded_confirmation(
            confirmation_id=confirmation_id
        )
        assert recovered.status == "RECOVERY_REQUIRED"
        assert recovered.reason_code == "grounded_confirmation_cleanup_required"
        assert recovery_backend.attempt_count == 0
        projected_calls = source.projected_calls
        replay = recovery.consume_grounded_confirmation(
            confirmation_id=confirmation_id
        )
        assert isinstance(replay, RuntimeResultReceiptV1)
        assert release_calls == 2
        assert source.projected_calls == projected_calls
        assert recovery_backend.attempt_count == 0
    finally:
        if confirmation_id in recovery._grounded_recovery_sessions:
            recovery.consume_grounded_confirmation(confirmation_id=confirmation_id)
