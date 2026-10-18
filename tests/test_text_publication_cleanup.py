"""发布重试遇到已拒绝确认时，释放失败保留原 owner 并能继续清理。"""
from app.agent.text_parameters import resolve_text_parameters
from test_text_local_publication import local


def test_closed_publication_retry_retains_cleanup_without_undefined_confirmation_id(local, monkeypatch):
    reviewed = local.service.get_local_reviewed_text_parameters(action_id=local.request.action_id)
    resolved = resolve_text_parameters(reviewed, {"query": "不会执行的审核值"})
    claim = local.service.request_grounded_confirmation(local.request, text_input=resolved)
    cid = claim.grounded_confirmation.confirmation_id
    local.claims.record_grounded_confirmation_decision(confirmation_id=cid, decision="denied")
    controller = local.controllers[-1]

    def unavailable(_lease):
        raise RuntimeError("synthetic lease release unavailable")

    with monkeypatch.context() as patch:
        patch.setattr(controller, "_release_window_lease", unavailable)
        result = local.service.request_grounded_confirmation(local.request, text_input=resolved)
    assert result.status == "RECOVERY_REQUIRED"
    assert result.reason_code == "grounded_confirmation_cleanup_required"
    assert local.backend.attempt_count == 0
    assert local.observation.session_id in controller._sessions
    fresh = local.service.start_session()
    assert fresh.session_id != local.observation.session_id
    assert local.observation.session_id not in controller._sessions
    assert controller._grounded_publications == {}
    assert local.backend.attempt_count == 0
