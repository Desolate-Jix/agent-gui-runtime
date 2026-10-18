"""填写只走本地 grounded 人审，旧四字段执行入口不得占用持久意图。"""
from tests.test_text_formal_execution import formal_text
from dataclasses import asdict


def test_generic_fill_intent_is_rejected_before_claim_and_keeps_grounded_path_available(formal_text):
    f = formal_text(variable=True)
    for _ in range(2):
        result = f.service.submit_intent(f.request)
        assert result.status == "REJECTED"
        assert result.reason_code == "text_grounded_confirmation_required"
        assert f.claims.list_unresolved_claims() == ()
        assert f.state.pasted == []
    claim = f.service.request_grounded_confirmation(f.request, text_input=f.resolved)
    assert claim.phase == "grounded_confirmation_pending"
    assert f.state.pasted == []


def test_old_approved_fill_cannot_enter_legacy_resume_marker(formal_text):
    f = formal_text()
    controller = f.controllers[-1]
    session = controller._sessions[f.request.session_id]
    observation = session.snapshot.current_observation
    intent = f.service._active_intent(f.request)
    f.claims.claim(observation=observation, intent=intent, server_binding=asdict(controller._binding))
    projection = controller._capture_current_resolution(session=session, expected_process_id=9001)
    pending = f.claims.mark_confirmation_pending(session_id=f.request.session_id,
        observation_id=f.request.observation_id, current_observation=projection.current,
        state_resolution=projection.state_resolution, transition_id=f.request.action_id,
        semantic_action="fill_field", target_process_id=9001)
    cid = pending.confirmation.confirmation_id
    f.claims.record_confirmation_decision(confirmation_id=cid, decision="approved")
    # 重开历史 legacy 记录，释放进程内 lease，但不改动持久阶段。
    controller._release_window_lease(session.window_lease)
    controller._sessions.clear()
    result = f.service.submit_intent(f.request)
    assert result.status == "REJECTED"
    assert result.reason_code == "confirmation_stale"
    assert f.claims.get_for_confirmation(confirmation_id=cid).phase == "confirmation_closed"
    assert f.claims.list_unresolved_claims() == ()
    assert f.state.pasted == []
    fresh_observation = f.service.start_session()
    assert fresh_observation.session_id != f.request.session_id
    f.service.cancel_prepared_session(session_id=fresh_observation.session_id)
