import pytest

from app.api.agent_runtime import AgentRuntimeCallsiteError
from tests.test_agent_runtime_grounded_preview import _request, live


def test_owner_query_is_read_only_for_pending_and_approved(live):
    observation = live.service.start_session()
    pending = live.service.request_grounded_confirmation(_request(observation))
    confirmation_id = pending.grounded_confirmation.confirmation_id
    captures = live.sources[0].projected_calls
    try:
        queried = live.service.get_local_grounded_confirmation(
            confirmation_id=confirmation_id
        )
        assert queried == pending
        approved = live.service.decide_grounded_confirmation(
            confirmation_id=confirmation_id, decision="approved"
        )
        assert live.service.get_local_grounded_confirmation(
            confirmation_id=confirmation_id
        ) == approved
        assert live.sources[0].projected_calls == captures
        assert live.backends[0].attempt_count == 0
    finally:
        live.service.cancel_grounded_review(session_id=observation.session_id)


def test_owner_query_rejects_cleanup_pending_before_closed_phase(live, monkeypatch):
    observation = live.service.start_session()
    pending = live.service.request_grounded_confirmation(_request(observation))
    confirmation_id = pending.grounded_confirmation.confirmation_id
    controller = live.controllers[0]
    release = controller._release_window_lease
    calls = 0

    def fail_once(lease):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("synthetic exact cleanup failure")
        return release(lease)

    monkeypatch.setattr(controller, "_release_window_lease", fail_once)
    decision = live.service.cancel_grounded_review(session_id=observation.session_id)
    assert decision.reason_code == "grounded_confirmation_cleanup_required"
    with pytest.raises(AgentRuntimeCallsiteError) as failure:
        live.service.get_local_grounded_confirmation(confirmation_id=confirmation_id)
    assert failure.value.code == "agent_runtime_cleanup_pending"
    restarted = live.service.start_session()
    live.service.cancel_prepared_session(session_id=restarted.session_id)


def test_owner_query_rejects_foreign_confirmation_before_capture(live):
    observation = live.service.start_session()
    captures = live.sources[0].projected_calls
    try:
        with pytest.raises(AgentRuntimeCallsiteError):
            live.service.get_local_grounded_confirmation(
                confirmation_id="grounded-confirmation." + "a" * 64
            )
        assert live.sources[0].projected_calls == captures
        assert live.backends[0].attempt_count == 0
    finally:
        live.service.cancel_prepared_session(session_id=observation.session_id)
