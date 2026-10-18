import pytest

from app.agent.runtime_contracts import RuntimeResultReceiptV1
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStoreError
from app.api.agent_runtime import AgentRuntimeCallsiteError
from tests.test_agent_runtime_grounded_preview import _request, live
from tests.test_live_controller_w4 import _current_observation


def test_callsite_consumes_only_selected_local_grounded_confirmation(live):
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
        first = live.service.consume_grounded_confirmation(confirmation_id=confirmation_id)
        second = live.service.consume_grounded_confirmation(confirmation_id=confirmation_id)

        assert isinstance(first, RuntimeResultReceiptV1)
        assert second == first
        assert live.backends[0].attempt_count == 1
        assert live.sources[0].projected_calls == 3
    finally:
        claim = live.claims.get_for_grounded_confirmation(confirmation_id=confirmation_id)
        if claim.phase == "grounded_confirmation_approved":
            live.service.cancel_grounded_review(session_id=observation.session_id)


def test_terminal_release_failure_keeps_exact_owner_until_start_retries(live, monkeypatch):
    observation = live.service.start_session()
    source = live.sources[0]
    source.post_current_sequence = [
        _current_observation(
            source.asset,
            capture_id="capture-release-fresh",
            anchors=("anchor_detail", "quick_apply"),
        ),
        _current_observation(
            source.asset,
            capture_id="capture-release-post",
            anchors=("anchor_apply_entry",),
        ),
    ]
    pending = live.service.request_grounded_confirmation(_request(observation))
    confirmation_id = pending.grounded_confirmation.confirmation_id
    live.service.decide_grounded_confirmation(
        confirmation_id=confirmation_id, decision="approved"
    )
    controller = live.controllers[0]
    release = controller._release_window_lease
    calls = 0

    def fail_once(lease):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic exact release failure")
        return release(lease)

    monkeypatch.setattr(controller, "_release_window_lease", fail_once)
    try:
        first = live.service.consume_grounded_confirmation(confirmation_id=confirmation_id)

        assert first.status == "RECOVERY_REQUIRED"
        assert first.reason_code == "grounded_confirmation_cleanup_required"
        assert observation.session_id in controller._sessions
        assert live.claims.get_for_grounded_confirmation(
            confirmation_id=confirmation_id
        ).phase == "terminal"
        restarted = live.service.start_session()
        assert calls == 2
        assert live.backends[0].attempt_count == 1
        live.service.cancel_prepared_session(session_id=restarted.session_id)
    finally:
        if observation.session_id in controller._sessions:
            controller.consume_grounded_confirmation(confirmation_id=confirmation_id)


def test_checkpoint_recovery_never_redispatches_grounded_action(live, monkeypatch):
    observation = live.service.start_session()
    source = live.sources[0]
    source.post_current_sequence = [
        _current_observation(
            source.asset,
            capture_id="capture-checkpoint-fresh",
            anchors=("anchor_detail", "quick_apply"),
        ),
        _current_observation(
            source.asset,
            capture_id="capture-checkpoint-post",
            anchors=("anchor_apply_entry",),
        ),
    ]
    pending = live.service.request_grounded_confirmation(_request(observation))
    confirmation_id = pending.grounded_confirmation.confirmation_id
    live.service.decide_grounded_confirmation(
        confirmation_id=confirmation_id, decision="approved"
    )
    persist = live.claims.persist_grounded_terminal
    calls = 0

    def fail_once(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeIntentClaimStoreError("synthetic terminal publish failure")
        return persist(**kwargs)

    monkeypatch.setattr(live.claims, "persist_grounded_terminal", fail_once)
    try:
        first = live.service.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert first.status == "RECOVERY_REQUIRED"
        assert first.reason_code == "receipt_persistence_failed"
        assert live.claims.get_for_grounded_confirmation(
            confirmation_id=confirmation_id
        ).phase == "verification_pending"
        assert live.backends[0].attempt_count == 1

        second = live.service.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert isinstance(second, RuntimeResultReceiptV1)
        assert live.backends[0].attempt_count == 1
        assert calls == 2
    finally:
        claim = live.claims.get_for_grounded_confirmation(confirmation_id=confirmation_id)
        if claim.phase == "verification_pending":
            live.controllers[0].consume_grounded_confirmation(
                confirmation_id=confirmation_id
            )


def test_terminal_receipt_reread_failure_keeps_then_clears_exact_active_owner(
    live, monkeypatch
):
    observation = live.service.start_session()
    source = live.sources[0]
    source.post_current_sequence = [
        _current_observation(
            source.asset,
            capture_id="capture-reread-fresh",
            anchors=("anchor_detail", "quick_apply"),
        ),
        _current_observation(
            source.asset,
            capture_id="capture-reread-post",
            anchors=("anchor_apply_entry",),
        ),
    ]
    pending = live.service.request_grounded_confirmation(_request(observation))
    confirmation_id = pending.grounded_confirmation.confirmation_id
    live.service.decide_grounded_confirmation(
        confirmation_id=confirmation_id, decision="approved"
    )
    load = live.claims.load_terminal_receipt
    calls = 0

    def fail_second(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeIntentClaimStoreError("synthetic terminal receipt reread failure")
        return load(**kwargs)

    monkeypatch.setattr(live.claims, "load_terminal_receipt", fail_second)
    with pytest.raises(AgentRuntimeCallsiteError):
        live.service.consume_grounded_confirmation(confirmation_id=confirmation_id)
    assert live.backends[0].attempt_count == 1
    projected_calls = source.projected_calls

    replay = live.service.consume_grounded_confirmation(confirmation_id=confirmation_id)
    assert isinstance(replay, RuntimeResultReceiptV1)
    assert source.projected_calls == projected_calls
    assert live.backends[0].attempt_count == 1
    restarted = live.service.start_session()
    live.service.cancel_prepared_session(session_id=restarted.session_id)
