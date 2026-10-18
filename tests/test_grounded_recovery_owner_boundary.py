import pytest

from app.api.agent_runtime import AgentRuntimeCallsiteError, AgentRuntimeConfirmationDecisionRequest
from tests.test_agent_runtime_grounded_preview import live, _request
from tests.test_agent_runtime_grounded_recovery import _checkpoint, _reopen, _release_test_processes


@pytest.mark.parametrize("entry", ["consume", "decide", "cancel", "close", "prepare", "request", "submit", "start", "cancel_prepared", "cancel_local", "legacy_decide"])
def test_non_recovery_lifecycle_cannot_drop_terminal_cleanup_owner(live, tmp_path, monkeypatch, entry):
    cid = _checkpoint(live, monkeypatch)
    runtime, _, built = _reopen(live, tmp_path)
    build = runtime._controller_factory
    releases = []

    def factory(binding):
        controller = build(binding)
        release = controller._release_window_lease

        def fail_once(lease):
            releases.append(lease)
            if len(releases) == 1:
                raise RuntimeError("synthetic terminal recovery cleanup")
            return release(lease)

        monkeypatch.setattr(controller, "_release_window_lease", fail_once)
        return controller

    runtime._controller_factory = factory
    assert runtime.recover_grounded_confirmation(confirmation_id=cid).reason_code == "grounded_confirmation_cleanup_required"
    owner = runtime._controller
    observation = runtime._observation
    request = _request(observation)
    calls = {
        "consume": lambda: runtime.consume_grounded_confirmation(confirmation_id=cid),
        "decide": lambda: runtime.decide_grounded_confirmation(confirmation_id=cid, decision="approved"),
        "cancel": lambda: runtime.cancel_grounded_review(session_id=observation.session_id),
        "close": lambda: runtime.close_grounded_confirmation(confirmation_id=cid),
        "prepare": lambda: runtime.prepare_grounded_review(request),
        "request": lambda: runtime.request_grounded_confirmation(request),
        "submit": lambda: runtime.submit_intent(request),
        "start": runtime.start_session,
        "cancel_prepared": lambda: runtime.cancel_prepared_session(session_id=observation.session_id),
        "cancel_local": runtime.cancel_local_preparation,
        "legacy_decide": lambda: runtime.decide_confirmation(AgentRuntimeConfirmationDecisionRequest(confirmation_id=cid, decision="approved")),
    }
    try:
        with pytest.raises(AgentRuntimeCallsiteError) as error:
            calls[entry]()
        assert error.value.code == "grounded_recovery_owner_busy"
        assert runtime._controller is owner
        assert runtime._grounded_recovery_id == cid
        assert cid in owner._grounded_recovery_sessions
        assert len(releases) == 1
        captured = live.sources[0].projected_calls
        runtime.recover_grounded_confirmation(confirmation_id=cid)
        assert runtime._grounded_recovery_id is None
        assert runtime._controller is None
        assert not owner._grounded_recovery_sessions
        assert live.sources[0].projected_calls == captured
        assert len(releases) == 2
    finally:
        # 即使红测暴露 owner 丢失，也只释放同一个纯测试 controller 的 lease。
        if owner._grounded_recovery_sessions:
            owner.consume_grounded_confirmation(confirmation_id=cid)
    assert len(built) == 1 and built[0][1].attempt_count == 0
