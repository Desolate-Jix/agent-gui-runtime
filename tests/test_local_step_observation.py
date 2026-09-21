"""结果合并回传只增加观察，不改变输入派发次数或默认权限。"""
import json
import pytest

from app.desktop_review import local_direct_step as direct
from tests.test_local_step_timings import timed_scene, run_step, saved_report, stages


def observed(co):
    return co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation="press_key", request={"key": "Enter", "x": 30, "y": 20}, include_observation=True)


def test_optional_observation_is_after_one_dispatch_and_persisted(timed_scene):
    co, state, _clock, _frozen = timed_scene
    result = observed(co)
    assert result["phase"] == "returned"
    assert result["observation"]["status"] == "captured"
    assert result["observation"]["authorizes_action"] is False
    assert result["observation"]["readiness"] == "unassessed"
    assert result["effect_verified"] is False
    assert result["capture"]["frame_id"] == "before_input"
    assert result["observation"]["capture"]["frame_id"] == "after_settled"
    assert result["observation"]["capture"]["render_completion_verified"] is False
    assert state.events.count("route") == 1 and state.events.count("capture") == 2
    assert state.events.index("route") < len(state.events) - 1 - state.events[::-1].index("capture")
    assert saved_report(co) == result
    assert "post_action_observation" in stages(result["local_step_timings"])


def test_observation_failure_is_explicit_without_retry(timed_scene, monkeypatch):
    co, state, _clock, _frozen = timed_scene
    def unavailable(*args):
        raise ValueError("private target title")
    monkeypatch.setattr(direct, "_capture_observation", unavailable)
    result = observed(co)
    assert result["response"]["success"] is True
    assert result["phase"] == "returned_observation_unavailable"
    assert result["observation"]["status"] == "unavailable"
    assert result["observation"]["error_type"] == "ValueError"
    assert "private target title" not in json.dumps(result)
    assert state.events.count("route") == 1
    assert result["automatic_retry_allowed"] is False
    assert saved_report(co) == result


def test_visibility_failure_keeps_reason_and_reports_input_dispatched(timed_scene, monkeypatch):
    from app.core.screenshot import CaptureVisibilityError
    co, state, _clock, _frozen = timed_scene
    def unavailable(*args):
        raise CaptureVisibilityError("capture_visibility_changed")
    monkeypatch.setattr(direct, "_capture_observation", unavailable)
    result = observed(co)
    assert result["response"]["success"] is True
    assert result["observation"]["error_code"] == "capture_visibility_changed"
    assert result["observation"]["next_action"] == "capture_current_state_without_replaying_input"
    assert result["automatic_retry_allowed"] is False
    assert state.events.count("route") == 1
    assert saved_report(co) == result


def test_observation_rejects_reused_process_identity(timed_scene, monkeypatch):
    co, state, _clock, _frozen = timed_scene
    original = direct.WindowsNativeIdentityReader
    def reader(**kwargs):
        base = original(**kwargs)
        original_read = base.read_identity
        calls = 0
        def read(handle):
            nonlocal calls
            result = original_read(handle)
            calls += 1
            if calls > 1:
                result["process_create_time"] += 1
            return result
        base.read_identity = read
        return base
    monkeypatch.setattr(direct, "WindowsNativeIdentityReader", reader)
    result = observed(co)
    assert result["observation"]["status"] == "unavailable"
    assert state.events.count("route") == state.events.count("capture") == 1


def test_default_has_no_extra_observation(timed_scene):
    co, state, _clock, _frozen = timed_scene
    assert "observation" not in run_step(co)
    assert state.events.count("capture") == 1


def test_explicit_model_preparation_never_dispatches_input(timed_scene):
    co, state, _clock, _frozen = timed_scene
    co._keep_models_loaded = True
    result = co.prepare_local_step_models(prepare_ocr=False)
    assert result["status"] == "ready" and result["input_dispatched"] is False
    assert state.events.count("model_prepare") == state.events.count("model_release") == 1
    assert "route" not in state.events and "capture" not in state.events


def test_model_preparation_requires_explicit_residency(timed_scene):
    co, state, _clock, _frozen = timed_scene
    with pytest.raises(ValueError, match="residency"):
        co.prepare_local_step_models(prepare_ocr=False)
    assert "model_prepare" not in state.events and "route" not in state.events


def test_render_grace_is_bounded_observation_only(timed_scene, monkeypatch):
    from scripts.run_local_step_session import run_step_command
    co, state, clock, _frozen = timed_scene
    waits = []
    def wait(seconds):
        state.events.append("render_wait")
        waits.append(seconds)
        clock.advance(seconds * 1000)
        return False
    monkeypatch.setattr(co._cancel_wait, "wait", wait)
    result = run_step_command(co, {"handle": 321, "process_id": 12},
        {"operation": "press_key", "request": {"key": "Enter", "x": 30, "y": 20}})
    assert waits == [2] and state.events.count("route") == 1
    last_capture = len(state.events) - 1 - state.events[::-1].index("capture")
    assert state.events.index("route") < state.events.index("render_wait") < last_capture
    assert result["observation"]["readiness"] == "unassessed"
    assert result["observation"]["render_grace_ms"] == 2000
    assert stages(result["local_step_timings"])["post_action_observation"]["elapsed_ms"] >= 2000


@pytest.mark.parametrize("operation,payload,override", [
    ("execute_recognition_plan", {}, None),
    ("press_key", {"key": "Enter"}, None),
    ("press_key", {"key": "Tab"}, None),
    ("type_text", {}, None),
    ("scroll", {}, None),
    ("press_key", {"key": "Enter"}, 0),
    ("press_key", {"key": "Enter"}, 2000),
    ("press_key", {"key": "Enter"}, 1500),
])
def test_session_delegates_defaults_and_preserves_overrides(operation, payload, override):
    from types import SimpleNamespace
    from scripts.run_local_step_session import run_step_command
    calls = []
    def execute(**kwargs):
        calls.append(kwargs)
        return {"test_receipt": True}
    command = {"operation": operation, "request": payload}
    if override is not None:
        command["observation_wait_ms"] = override
    result = run_step_command(SimpleNamespace(execute_local_step=execute),
        {"handle": 321, "process_id": 12}, command)
    assert result == {"test_receipt": True}
    assert calls == [{"target_window_handle": 321, "target_process_id": 12,
        "operation": operation, "request": payload, "include_observation": True,
        "observation_wait_ms": override}]


def test_direct_coordinator_uses_shared_default_without_demo(timed_scene, monkeypatch):
    co, state, _clock, _frozen = timed_scene
    waits = []
    monkeypatch.setattr(co._cancel_wait, "wait", lambda seconds: waits.append(seconds) or False)
    result = observed(co)
    assert waits == [2]
    assert result["observation"]["render_grace_ms"] == 2000
    assert state.events.count("route") == 1


@pytest.mark.parametrize("value", [-1, 2001, True, 1.5])
def test_invalid_render_grace_rejected_before_input(timed_scene, value):
    co, state, _clock, _frozen = timed_scene
    with pytest.raises(ValueError):
        co.execute_local_step(target_window_handle=321, target_process_id=12, operation="press_key",
            request={"key": "Enter", "x": 30, "y": 20}, include_observation=True, observation_wait_ms=value)
    assert "route" not in state.events


def test_route_error_not_persisted_as_private_text(timed_scene):
    co, state, _clock, _frozen = timed_scene
    state.error_at = "route"
    with pytest.raises(RuntimeError) as raised:
        run_step(co)
    assert raised.value is state.failure
    assert "private text" not in json.dumps(saved_report(co))
