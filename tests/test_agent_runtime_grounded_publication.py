import pytest

from app.agent.live_controller import ServerWorkflowBinding
from app.agent.live_runtime_composition import build_existing_windows_live_controller
from app.agent.runtime_intent_claim_store import (
    RuntimeIntentClaimSnapshot,
    RuntimeIntentClaimStore,
    RuntimeIntentClaimStoreError,
)
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from app.api.agent_runtime import AgentRuntimeCallsiteError
from tests.test_agent_runtime_grounded_preview import _request, live


def test_callsite_publication_decision_and_cancel_use_exact_live_owner(live):
    observation = live.service.start_session()
    request = _request(observation)
    try:
        pending = live.service.request_grounded_confirmation(request)
        assert isinstance(pending, RuntimeIntentClaimSnapshot)
        confirmation_id = pending.grounded_confirmation.confirmation_id

        approved = live.service.decide_grounded_confirmation(
            confirmation_id=confirmation_id,
            decision="approved",
        )
        assert approved.phase == "grounded_confirmation_approved"
        assert live.backends[0].attempt_count == 0

        replay = live.service.submit_intent(request)
        assert replay.status == "RECOVERY_REQUIRED"
        assert replay.reason_code == "grounded_confirmation_active"

        closed = live.service.close_grounded_confirmation(
            confirmation_id=confirmation_id,
        )
        assert closed.phase == "grounded_confirmation_closed"
        assert live.service.start_session().session_id != observation.session_id
    finally:
        for controller in live.controllers:
            for session_id in list(controller._sessions):
                try:
                    controller.cancel_grounded_review(session_id=session_id)
                except (ValueError, RuntimeError):
                    controller.abandon_session(session_id=session_id)


def test_callsite_grounded_operations_require_explicit_selection(live):
    observation = live.service.start_session()
    selection = live.service._selection
    live.service._selection = None
    try:
        with pytest.raises(AgentRuntimeCallsiteError) as raised:
            live.service.request_grounded_confirmation(_request(observation))
        assert raised.value.code == "agent_runtime_selection_required"
        assert live.sources[0].projected_calls == 0
    finally:
        live.service._selection = selection
        live.controllers[0].abandon_session(session_id=observation.session_id)


def test_binding_failure_before_publication_leaves_prepared_session_cancellable(live):
    observation = live.service.start_session()
    live.windows.bound.process_id = 9302
    with pytest.raises(AgentRuntimeCallsiteError) as raised:
        live.service.request_grounded_confirmation(_request(observation))
    assert raised.value.code == "agent_runtime_selection_binding_mismatch"
    assert live.sources[0].projected_calls == 0

    live.windows.bound.process_id = 9301
    live.service.cancel_prepared_session(session_id=observation.session_id)
    assert observation.session_id not in live.controllers[0]._sessions


def test_actual_preflight_rejection_clears_grounded_mode_without_claim(live):
    observation = live.service.start_session()
    live.sources[0].target_process_id = 9302

    rejected = live.service.request_grounded_confirmation(_request(observation))

    assert rejected.status == "REJECTED"
    assert rejected.reason_code == "target_process_changed"
    assert live.service._grounded_intent is None
    assert live.claims.list_unresolved_claims() == ()
    live.service.cancel_prepared_session(session_id=observation.session_id)


def test_preflight_recovery_before_context_still_allows_prepared_cancel(live, monkeypatch):
    observation = live.service.start_session()

    def unavailable(**_kwargs):
        raise RuntimeError("synthetic passive capture failure")

    monkeypatch.setattr(live.sources[0], "capture_projected", unavailable)
    failed = live.service.request_grounded_confirmation(_request(observation))

    assert failed.status == "RECOVERY_REQUIRED"
    assert failed.reason_code == "current_capture_failed"
    assert live.claims.list_unresolved_claims() == ()
    live.service.cancel_prepared_session(session_id=observation.session_id)


def test_post_publication_window_drift_closes_stale_and_releases_exact_owner(live, monkeypatch):
    observation = live.service.start_session()
    capture = live.sources[0].capture_projected

    def drift(**kwargs):
        projected = capture(**kwargs)
        live.windows.bound.process_id = 9302
        return projected

    monkeypatch.setattr(live.sources[0], "capture_projected", drift)
    with pytest.raises(AgentRuntimeCallsiteError) as raised:
        live.service.request_grounded_confirmation(_request(observation))
    assert raised.value.code == "agent_runtime_selection_binding_mismatch"
    claim = live.claims.find_for_observation(
        session_id=observation.session_id,
        observation_id=observation.observation_id,
    )
    assert claim.phase == "grounded_confirmation_closed"
    assert claim.grounded_confirmation.closed_reason_code == "grounded_confirmation_stale"
    assert observation.session_id not in live.controllers[0]._sessions
    assert live.backends[0].attempt_count == 0

    live.windows.bound.process_id = 9301
    assert live.service.start_session().session_id != observation.session_id


def test_existing_windows_builder_rejects_foreign_root_claim_store(tmp_path):
    claims = RuntimeIntentClaimStore(
        project_root=tmp_path / "foreign",
        receipt_store=RuntimeReceiptStore(project_root=tmp_path / "foreign"),
    )
    with pytest.raises(ValueError, match="same project root"):
        build_existing_windows_live_controller(
            tmp_path,
            ServerWorkflowBinding(
                workflow_id="workflow.shared-store",
                asset_id="asset.shared-store",
                application_identity_key="native:editor.exe",
                target_window_handle=99102,
            ),
            intent_claim_store=claims,
        )


def test_live_approval_post_binding_drift_closes_stale_without_dispatch(live, monkeypatch):
    observation = live.service.start_session()
    pending = live.service.request_grounded_confirmation(_request(observation))
    confirmation_id = pending.grounded_confirmation.confirmation_id
    record = live.controllers[0].record_grounded_confirmation_decision

    def approve_then_drift(**kwargs):
        result = record(**kwargs)
        live.windows.bound.process_id = 9302
        return result

    monkeypatch.setattr(
        live.controllers[0],
        "record_grounded_confirmation_decision",
        approve_then_drift,
    )
    with pytest.raises(AgentRuntimeCallsiteError) as raised:
        live.service.decide_grounded_confirmation(
            confirmation_id=confirmation_id,
            decision="approved",
        )
    assert raised.value.code == "agent_runtime_selection_binding_mismatch"
    closed = live.claims.get_for_grounded_confirmation(confirmation_id=confirmation_id)
    assert closed.phase == "grounded_confirmation_closed"
    assert closed.grounded_confirmation.closed_reason_code == "grounded_confirmation_stale"
    assert observation.session_id not in live.controllers[0]._sessions
    assert live.backends[0].attempt_count == 0


def test_claim_publish_failure_keeps_context_until_explicit_cancel_releases_lease(
    live,
    monkeypatch,
):
    observation = live.service.start_session()
    publish = live.claims._publish_bytes

    def fail_claim(path, contents):
        if path.parent == live.claims.claims_root:
            raise RuntimeIntentClaimStoreError("synthetic claim publication failure")
        return publish(path, contents)

    with monkeypatch.context() as patch:
        patch.setattr(live.claims, "_publish_bytes", fail_claim)
        failed = live.service.request_grounded_confirmation(_request(observation))
    assert failed.status == "RECOVERY_REQUIRED"
    assert failed.reason_code == "grounded_confirmation_persistence_failed"
    assert observation.session_id in live.controllers[0]._grounded_publications
    assert live.claims.list_unresolved_claims() == ()

    assert live.service.cancel_grounded_review(session_id=observation.session_id) is None
    restarted = live.service.start_session()
    assert restarted.session_id != observation.session_id
    live.service.cancel_prepared_session(session_id=restarted.session_id)


def test_callsite_start_retries_exact_release_after_durable_denial(live, monkeypatch):
    observation = live.service.start_session()
    pending = live.service.request_grounded_confirmation(_request(observation))
    controller = live.controllers[0]
    release = controller._release_window_lease
    calls = 0

    def fail_once(lease):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic release failure")
        release(lease)

    monkeypatch.setattr(controller, "_release_window_lease", fail_once)
    failed = live.service.decide_grounded_confirmation(
        confirmation_id=pending.grounded_confirmation.confirmation_id,
        decision="denied",
    )
    assert failed.status == "RECOVERY_REQUIRED"
    assert live.service._grounded_cleanup[0] is controller
    assert observation.session_id in controller._sessions

    restarted = live.service.start_session()
    assert restarted.session_id != observation.session_id
    assert len(live.controllers) == 2
    assert calls == 2
    live.service.cancel_prepared_session(session_id=restarted.session_id)


def test_existing_windows_builder_accepts_the_exact_shared_claim_store(tmp_path):
    from tests.test_native_vision_configuration import _config
    _config(tmp_path / "configs/vision.json")
    claims = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
    )
    controller = build_existing_windows_live_controller(
        tmp_path,
        ServerWorkflowBinding(
            workflow_id="workflow.shared-store",
            asset_id="asset.shared-store",
            application_identity_key="native:editor.exe",
            target_window_handle=99101,
        ),
        intent_claim_store=claims,
    )
    assert controller._intent_claim_store is claims
