"""审核面板遮挡目标时可读取确切缓存预览，但不授予后台动作权限。"""
import pytest

from app.api.agent_runtime import AgentRuntimeCallsiteError
from tests.test_agent_runtime_grounded_preview import live, _request


@pytest.fixture
def grounded_image_runtime(live):
    # 此测试仅隔离 callsite 前台规则；图片来源校验由既有组件及实机复验负责。
    live.cached_png = b'synthetic-cache-boundary-material'
    try:
        yield live
    finally:
        for controller in live.controllers:
            for session_id in list(controller._sessions):
                controller.cancel_grounded_review(session_id=session_id)


def _pending(runtime):
    observation = runtime.service.start_session()
    pending = runtime.service.request_grounded_confirmation(_request(observation))
    runtime.sources[0].read_cached_grounded_image = lambda **_kwargs: runtime.cached_png
    return observation, pending


@pytest.mark.parametrize('approved', [False, True])
def test_cached_review_remains_readable_when_panel_owns_foreground(grounded_image_runtime, approved):
    runtime = grounded_image_runtime
    observation, pending = _pending(runtime)
    confirmation_id = pending.grounded_confirmation.confirmation_id
    expected = runtime.service.get_local_grounded_image(confirmation_id=confirmation_id)
    claim = runtime.service.decide_grounded_confirmation(confirmation_id=confirmation_id, decision='approved') if approved else pending
    calls = runtime.sources[0].projected_calls
    runtime.service._window_manager.bound.is_active = False
    assert runtime.service.get_local_grounded_confirmation(confirmation_id=confirmation_id) == claim
    assert runtime.service.get_local_grounded_image(confirmation_id=confirmation_id) == expected
    assert runtime.sources[0].projected_calls == calls
    assert runtime.backends[0].attempt_count == 0
    runtime.service.cancel_grounded_review(session_id=observation.session_id)


def test_cached_review_still_rejects_changed_window_identity(grounded_image_runtime):
    runtime = grounded_image_runtime
    _observation, pending = _pending(runtime)
    runtime.service._window_manager.bound.is_active = False
    runtime.service._window_manager.bound.process_id += 1
    with pytest.raises(AgentRuntimeCallsiteError) as error:
        runtime.service.get_local_grounded_image(confirmation_id=pending.grounded_confirmation.confirmation_id)
    assert error.value.code == 'agent_runtime_selection_binding_mismatch'
    assert runtime.backends[0].attempt_count == 0


def test_inactive_target_still_rejects_approval(grounded_image_runtime):
    runtime = grounded_image_runtime
    _observation, pending = _pending(runtime)
    runtime.service._window_manager.bound.is_active = False
    with pytest.raises(AgentRuntimeCallsiteError) as error:
        runtime.service.decide_grounded_confirmation(confirmation_id=pending.grounded_confirmation.confirmation_id,
                                                     decision='approved')
    assert error.value.code == 'agent_runtime_bound_window_inactive'
    assert runtime.backends[0].attempt_count == 0


def test_inactive_target_still_rejects_confirmed_execution(grounded_image_runtime):
    runtime = grounded_image_runtime
    _observation, pending = _pending(runtime)
    confirmation_id = pending.grounded_confirmation.confirmation_id
    runtime.service.decide_grounded_confirmation(confirmation_id=confirmation_id, decision='approved')
    runtime.service._window_manager.bound.is_active = False
    with pytest.raises(AgentRuntimeCallsiteError) as error:
        runtime.service.consume_grounded_confirmation(confirmation_id=confirmation_id)
    assert error.value.code == 'agent_runtime_bound_window_inactive'
    assert runtime.backends[0].attempt_count == 0
