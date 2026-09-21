"""前台丢失要保留拒绝当刻的事实，不能冒充派发成功或允许重放。"""
from types import SimpleNamespace

import pytest

from app.core import input_controller as inputs
from app.desktop_review.local_keyboard_action import LocalKeyRequest, press_local_key
from app.desktop_review import local_direct_step as direct
from tests.test_local_step_timings import timed_scene, saved_report


@pytest.fixture
def focus_scene(monkeypatch):
    controller = inputs.InputController()
    events = []
    state = SimpleNamespace(foreground=99)
    bound = SimpleNamespace(handle=7, process_id=9, rect=SimpleNamespace(left=0, top=0, right=320, bottom=200))
    monkeypatch.setattr(inputs, "input_controller", controller)
    monkeypatch.setattr(controller, "_ensure_windows_input", lambda: None)
    monkeypatch.setattr(controller, "_require_bound_window", lambda: bound)
    monkeypatch.setattr(inputs.win32gui, "GetForegroundWindow", lambda: state.foreground)
    monkeypatch.setattr(inputs.window_manager, "validate_bound_point_visibility", lambda **kw: {"allowed": True})
    monkeypatch.setattr(controller, "_focus_window", lambda h: events.append("focus"))
    monkeypatch.setattr(controller, "_send_key", lambda key, *, key_up: events.append((key, key_up)))
    return controller, state, events


def test_focus_loss_reports_no_dispatch_and_original_foreground(focus_scene):
    _, state, events = focus_scene
    result = press_local_key(LocalKeyRequest(key="Shift+Home", x=70, y=80)).model_dump()
    state.foreground = 7
    assert result["success"] is False and result["error"]["code"] == "keyboard_target_not_foreground"
    assert result["data"]["dispatch_status"] == "not_dispatched"
    assert result["data"]["pressed"] is False
    assert result["data"]["diagnostics"]["expected_window_handle"] == 7
    assert result["data"]["diagnostics"]["observed_foreground_handle"] == 99
    assert result["data"]["automatic_retry_allowed"] is False
    assert result["data"]["next_action"] == "select_target_and_inspect_before_new_request"
    assert events == []
    # 明确恢复后的新请求才派发，旧回执不被当前前台状态改写。
    new = press_local_key(LocalKeyRequest(key="Shift+Home", x=70, y=80))
    assert new.success is True and new.data["pressed"] is True
    assert len(events) == 4


def test_interrupted_dispatch_never_claims_no_input(focus_scene, monkeypatch):
    controller, state, events = focus_scene
    state.foreground = 7
    def fail(key, *, key_up):
        events.append((key, key_up))
        if not key_up:
            raise RuntimeError("input outcome unknown")
    monkeypatch.setattr(controller, "_send_key", fail)
    result = press_local_key(LocalKeyRequest(key="Home", x=70, y=80))
    assert result.success is False and result.error.code == "key_dispatch_failed"
    assert result.data is None
    assert events


@pytest.mark.parametrize("missing_observation", [False, True])
def test_owner_preserves_known_no_dispatch_with_observation(timed_scene, focus_scene, monkeypatch, missing_observation):
    co, _, _, _ = timed_scene
    _, _, events = focus_scene
    monkeypatch.setattr(direct, "_post_action", lambda operation, request, manager:
        press_local_key(LocalKeyRequest(**request)).model_dump())
    if missing_observation:
        def unavailable(*args):
            raise ValueError("observation unavailable")
        monkeypatch.setattr(direct, "_capture_observation", unavailable)
    result = co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation="press_key", request={"key": "Shift+Home", "x": 70, "y": 80},
        include_observation=True, observation_wait_ms=0)
    assert result["phase"] == "not_dispatched"
    assert result["response"]["data"]["pressed"] is False
    assert result["automatic_retry_allowed"] is False
    assert result["observation"]["status"] == ("unavailable" if missing_observation else "captured")
    assert result == saved_report(co)
    assert events == []
