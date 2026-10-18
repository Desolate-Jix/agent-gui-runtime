from app.agent.grounded_action_preview import GroundedActionPreview
from app.agent.live_controller import LiveControllerDecision
from app.agent.runtime_contracts import validate_agent_intent_v1
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimSnapshot
from tests.test_live_controller_grounded_preview import _intent, _review_controller


def test_controller_publishes_one_grounded_request_and_retry_does_not_recapture(tmp_path):
    controller, source, _resolver, _gate, backend = _review_controller(
        tmp_path,
        target_window_handle=6101,
    )
    session = controller.start_session()
    intent = _intent(session)

    try:
        first = controller.request_grounded_confirmation(
            intent,
            target_process_id=9001,
        )
        assert isinstance(first, RuntimeIntentClaimSnapshot)
        assert first.phase == "grounded_confirmation_pending"
        assert isinstance(first.grounded_confirmation.preview, GroundedActionPreview)
        request_bytes = next(
            controller._intent_claim_store.grounded_requests_root.iterdir()
        ).read_bytes()

        again = controller.request_grounded_confirmation(
            intent,
            target_process_id=9001,
        )

        assert again == first
        assert next(
            controller._intent_claim_store.grounded_requests_root.iterdir()
        ).read_bytes() == request_bytes
        assert source.projected_calls == 1
        assert backend.attempt_count == 0
        assert not list(controller._intent_claim_store.dispatch_started_root.iterdir())
        assert not list(controller._intent_claim_store.terminal_root.iterdir())
    finally:
        controller.cancel_grounded_review(session_id=session.session_id)


def test_controller_denial_is_durable_before_exact_window_lease_release(tmp_path):
    controller, _source, _resolver, _gate, backend = _review_controller(
        tmp_path,
        target_window_handle=6102,
    )
    session = controller.start_session()
    pending = controller.request_grounded_confirmation(
        _intent(session),
        target_process_id=9001,
    )
    assert isinstance(pending, RuntimeIntentClaimSnapshot)
    confirmation_id = pending.grounded_confirmation.confirmation_id

    denied = controller.record_grounded_confirmation_decision(
        confirmation_id=confirmation_id,
        decision="denied",
    )

    assert isinstance(denied, RuntimeIntentClaimSnapshot)
    assert denied.phase == "grounded_confirmation_denied"
    assert session.session_id not in controller._sessions
    assert backend.attempt_count == 0

    replacement, *_rest = _review_controller(
        tmp_path / "replacement",
        target_window_handle=6102,
    )
    replacement_session = replacement.start_session()
    replacement.abandon_session(session_id=replacement_session.session_id)


def test_controller_rejects_old_execution_paths_while_publication_is_active(tmp_path):
    controller, source, _resolver, _gate, backend = _review_controller(
        tmp_path,
        target_window_handle=6103,
    )
    session = controller.start_session()
    intent = _intent(session)
    try:
        pending = controller.request_grounded_confirmation(
            intent,
            target_process_id=9001,
        )
        assert isinstance(pending, RuntimeIntentClaimSnapshot)

        replay = controller.submit_intent(intent)
        preview = controller.prepare_grounded_review(intent, target_process_id=9001)

        assert isinstance(replay, LiveControllerDecision)
        assert replay.status == "RECOVERY_REQUIRED"
        assert replay.reason_code == "grounded_confirmation_active"
        assert isinstance(preview, LiveControllerDecision)
        assert preview.reason_code == "grounded_confirmation_active"
        assert source.projected_calls == 1
        assert backend.attempt_count == 0
    finally:
        controller.cancel_grounded_review(session_id=session.session_id)


def test_durable_denial_release_failure_keeps_exact_owner_for_retry(tmp_path, monkeypatch):
    controller, _source, _resolver, _gate, backend = _review_controller(
        tmp_path,
        target_window_handle=6104,
    )
    session = controller.start_session()
    pending = controller.request_grounded_confirmation(
        _intent(session),
        target_process_id=9001,
    )
    confirmation_id = pending.grounded_confirmation.confirmation_id
    release = controller._release_window_lease
    calls = 0

    def fail_once(lease):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic exact lease release failure")
        release(lease)

    monkeypatch.setattr(controller, "_release_window_lease", fail_once)
    uncertain = controller.record_grounded_confirmation_decision(
        confirmation_id=confirmation_id,
        decision="denied",
    )
    assert isinstance(uncertain, LiveControllerDecision)
    assert uncertain.reason_code == "grounded_confirmation_cleanup_required"
    assert session.session_id in controller._sessions
    assert controller._intent_claim_store.get_for_grounded_confirmation(
        confirmation_id=confirmation_id
    ).phase == "grounded_confirmation_denied"

    recovered = controller.record_grounded_confirmation_decision(
        confirmation_id=confirmation_id,
        decision="denied",
    )
    assert recovered.phase == "grounded_confirmation_denied"
    assert session.session_id not in controller._sessions
    assert calls == 2
    assert backend.attempt_count == 0


def test_existing_claim_without_controller_publication_context_never_recaptures(tmp_path):
    controller, source, _resolver, _gate, backend = _review_controller(
        tmp_path,
        target_window_handle=6105,
    )
    session = controller.start_session()
    intent = validate_agent_intent_v1(
        _intent(session),
        observation=session.current_observation,
    )
    controller._intent_claim_store.claim(
        observation=session.current_observation,
        intent=intent,
        server_binding={
            "workflow_id": controller._binding.workflow_id,
            "asset_id": controller._binding.asset_id,
            "application_identity_key": controller._binding.application_identity_key,
            "target_window_handle": controller._binding.target_window_handle,
        },
    )

    result = controller.request_grounded_confirmation(
        _intent(session),
        target_process_id=9001,
    )

    assert isinstance(result, LiveControllerDecision)
    assert result.status == "RECOVERY_REQUIRED"
    assert result.reason_code == "grounded_confirmation_owner_unavailable"
    assert source.projected_calls == 0
    assert backend.attempt_count == 0
    assert not controller._grounded_publications
    assert not list(controller._intent_claim_store.grounded_requests_root.iterdir())


def test_request_retry_observes_external_denial_and_releases_exact_lease(tmp_path):
    controller, source, _resolver, _gate, backend = _review_controller(
        tmp_path,
        target_window_handle=6106,
    )
    session = controller.start_session()
    intent = _intent(session)
    pending = controller.request_grounded_confirmation(intent, target_process_id=9001)
    denied = controller._intent_claim_store.record_grounded_confirmation_decision(
        confirmation_id=pending.grounded_confirmation.confirmation_id,
        decision="denied",
    )
    assert denied.phase == "grounded_confirmation_denied"

    observed = controller.request_grounded_confirmation(intent, target_process_id=9001)

    assert observed == denied
    assert session.session_id not in controller._sessions
    assert source.projected_calls == 1
    assert backend.attempt_count == 0
