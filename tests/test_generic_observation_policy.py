"""公共等待规则不认识网站，也不产生或重放输入权限。"""
from types import SimpleNamespace

import pytest

from app.core.observation_policy import resolve_render_grace_ms
from app.agent.desktop_backend import (
    DesktopDispatchCommand, ExistingWindowsBackendAdapter, _mint_execution_authority,
)


@pytest.mark.parametrize("action,expected", [
    ("open_detail", 2000), ("open_apply_flow", 2000), ("back", 2000),
    ("close_modal", 2000), ("execute_recognition_plan", 2000), ("press_enter", 2000),
    ("fill_field", 0), ("type_text", 0), ("scroll_region", 0), ("scroll", 0),
    ("taskbar_activate", 0), ("unknown", 0),
])
def test_action_defaults(action, expected):
    assert resolve_render_grace_ms(action) == expected


@pytest.mark.parametrize("override", [0, 1, 1500, 2000])
def test_explicit_override_is_not_replaced_by_default(override):
    assert resolve_render_grace_ms("open_detail", override) == override


@pytest.mark.parametrize("override", [-1, 2001, True, False, 1.5, "2000"])
def test_invalid_override_rejected(override):
    with pytest.raises(ValueError):
        resolve_render_grace_ms("open_detail", override)


def command_and_authority():
    command = DesktopDispatchCommand("open_detail", "capture-current", "candidate-current", (22., 24.), 4242)
    authority = _mint_execution_authority(session_id="session", observation_id="observation", intent_id="intent",
        workflow_revision_hash="b" * 64, semantic_action=command.semantic_action, selection_sha256="a" * 64,
        capture_id=command.capture_id, candidate_id=command.candidate_id, click_point=command.click_point,
        target_window_handle=command.target_window_handle, gate_decision_ref="gate")
    return command, authority


@pytest.mark.parametrize("application", ["browser.exe", "native-editor.exe"])
def test_common_backend_waits_once_and_preserves_once_only_authority(application):
    events = []
    def click(x, y):
        events.append("input")
        return {"clicked": True}
    backend = ExistingWindowsBackendAdapter(input_controller=SimpleNamespace(click_point=click),
        window_manager=SimpleNamespace(get_bound_window=lambda: SimpleNamespace(handle=4242, title=application)),
        sleeper=lambda seconds: events.append(("wait", seconds)))
    command, authority = command_and_authority()
    result = backend.dispatch(command, authority=authority)
    assert result.status == "dispatched"
    assert events == ["input", ("wait", 2.)]
    with pytest.raises(PermissionError, match="already consumed"):
        backend.dispatch(command, authority=authority)
    assert events == ["input", ("wait", 2.)]


def test_unknown_input_result_is_not_retried_or_misreported_as_ready():
    calls = []
    def fail(x, y):
        calls.append("input")
        raise RuntimeError("lost response")
    backend = ExistingWindowsBackendAdapter(input_controller=SimpleNamespace(click_point=fail),
        window_manager=SimpleNamespace(get_bound_window=lambda: SimpleNamespace(handle=4242)), sleeper=calls.append)
    command, authority = command_and_authority()
    result = backend.dispatch(command, authority=authority)
    assert (result.status, result.reason_code) == ("indeterminate", "backend_result_lost")
    assert calls == ["input"]


def test_explicit_zero_preserves_no_wait_backend_contract():
    events = []
    backend = ExistingWindowsBackendAdapter(
        input_controller=SimpleNamespace(click_point=lambda x, y: {"clicked": True}),
        window_manager=SimpleNamespace(get_bound_window=lambda: SimpleNamespace(handle=4242)),
        post_dispatch_settle_seconds=0, sleeper=events.append)
    command, authority = command_and_authority()
    assert backend.dispatch(command, authority=authority).status == "dispatched"
    assert events == []


def test_agent_proposal_native_confirmation_wait_then_fresh_image(tmp_path):
    from tests.test_fresh_agent_stdio import _rig

    with _rig(tmp_path) as (host, coordinator, connection, segment, staged, instances):
        service, token = host._service, connection["token"]
        prepared = service.agent_call(token, "prepare_fresh_learning_runtime", {
            "segment_id": segment["segment_id"], "batch_id": staged["batch_id"],
            "idempotency_key": "generic.wait.prepare"})
        _callsite, controller, _fake_backend, owner = instances[0]
        events = []
        def click(x, y, **kwargs):
            events.append("input")
            return {"clicked": True}
        controller._backend = ExistingWindowsBackendAdapter(
            input_controller=SimpleNamespace(click_point=click), window_manager=owner._window_manager,
            sleeper=lambda seconds: events.append(("wait", seconds)))
        original_capture = owner._screenshot_service.capture_window
        def capture(**kwargs):
            events.append("capture")
            return original_capture(**kwargs)
        owner._screenshot_service.capture_window = capture
        scope = {"segment_id": segment["segment_id"], "preparation_id": prepared["preparation_id"]}
        intent = {**scope, "intent_id": "generic.wait.intent", "action_id": "action.view",
                  "semantic_action": "open_detail", "goal": "View details"}
        service.agent_call(token, "request_fresh_learning_action", intent)
        view = coordinator.current_fresh_review()
        assert "input" not in events and not any(isinstance(item, tuple) for item in events)
        coordinator.approve(confirmation_id=view["confirmation_id"],
            preview_content_sha256=view["preview"]["preview_sha256"])
        events.clear()
        receipt = coordinator.execute(confirmation_id=view["confirmation_id"])
        assert receipt["kind"] == "receipt", receipt
        dispatched = events.index("input")
        assert events[dispatched:dispatched + 3] == ["input", ("wait", 2.), "capture"]
        assert events.count("input") == 1
        value = service.agent_call(token, "get_fresh_learning_runtime", scope)
        assert value["receipt"]["outcome"] == "ACTION_RECORDED"
        assert value["receipt"]["destination_status"] == "not_evaluated"
        assert value["receipt"]["next_observation_id"] == value["observation"]["observation_id"]
        previous = list(events)
        retry = service.agent_call(token, "request_fresh_learning_action", intent)
        assert retry["receipt"] == value["receipt"]
        assert events == previous
