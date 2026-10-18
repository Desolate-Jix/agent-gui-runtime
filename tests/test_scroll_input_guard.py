from types import SimpleNamespace

import pytest

from app.core import input_controller as input_module
from app.core.runtime_input_authority import _runtime_backend_input_scope


@pytest.fixture
def input_boundary(monkeypatch):
    bound = SimpleNamespace(handle=4242, title="fixture", process_id=12,
                            rect=SimpleNamespace(left=10, top=20, right=810, bottom=620))
    state = SimpleNamespace(bound=bound, foreground=4242, visible=True, events=[], after_move=None, visibility_calls=0)

    def visible(**kwargs):
        state.visibility_calls += 1
        return {"allowed": state.visible, "reason": "fixture_visibility", "bound_window": {"handle": kwargs["bound"].handle}}

    def move(x, y):
        state.events.append(("move", x, y))
        if state.after_move:
            state.after_move()

    monkeypatch.setattr(input_module, "WINDOWS_INPUT_AVAILABLE", True)
    monkeypatch.setattr(input_module, "window_manager", SimpleNamespace(get_bound_window=lambda: state.bound, validate_bound_point_visibility=visible))
    monkeypatch.setattr(input_module, "win32api", SimpleNamespace(GetCursorPos=lambda: (80, 100)))
    monkeypatch.setattr(input_module, "win32gui", SimpleNamespace(GetForegroundWindow=lambda: state.foreground, SetForegroundWindow=lambda handle: None))
    runtime = input_module.InputController()
    monkeypatch.setattr(runtime, "_send_move", move)
    monkeypatch.setattr(runtime, "_send_mouse_input", lambda **kwargs: state.events.append(("wheel", kwargs)))
    state.runtime = runtime
    return state


@pytest.mark.parametrize("direction,delta", [("up", 240), ("down", -240)])
def test_real_scroll_method_emits_exact_bounded_delta_after_current_visibility_check(input_boundary, direction, delta):
    with _runtime_backend_input_scope():
        result = input_boundary.runtime.scroll_window(direction=direction, wheel_clicks=2, x=70, y=80, settle_ms=0)
    assert result["scrolled"] is True
    assert result["wheel_delta"] == delta
    assert result["point_visibility"]["allowed"] is True
    assert input_boundary.visibility_calls == 1
    assert input_boundary.events == [("move", 80, 100), ("wheel", {"dx": 0, "dy": 0, "flags": input_module.MOUSEEVENTF_WHEEL, "mouse_data": delta})]


def test_scroll_remains_unavailable_without_runtime_input_authority(input_boundary):
    with pytest.raises(PermissionError, match="one-time"):
        input_boundary.runtime.scroll_window(direction="down", wheel_clicks=2, x=70, y=80, settle_ms=0)
    assert input_boundary.events == []


@pytest.mark.parametrize("change", ["occluded", "foreground", "window", "geometry", "cursor"])
def test_drift_after_pointer_move_blocks_wheel_event(input_boundary, monkeypatch, change):
    def drift():
        if change == "occluded":
            input_boundary.visible = False
        elif change == "foreground":
            input_boundary.foreground = 9999
        elif change == "window":
            input_boundary.bound = SimpleNamespace(handle=9999, rect=input_boundary.bound.rect)
        elif change == "geometry":
            input_boundary.bound.rect.left = 11
        else:
            monkeypatch.setattr(input_module, "win32api", SimpleNamespace(GetCursorPos=lambda: (150, 150)))
    input_boundary.after_move = drift
    with _runtime_backend_input_scope(), pytest.raises((RuntimeError, input_module.TargetPointOccludedError)):
        input_boundary.runtime.scroll_window(direction="down", wheel_clicks=2, x=70, y=80, settle_ms=0)
    assert not any(event[0] == "wheel" for event in input_boundary.events)


@pytest.mark.parametrize("kwargs", [{"wheel_clicks": 0}, {"wheel_clicks": 21}, {"wheel_clicks": True}, {"wheel_clicks": 2.0}, {"direction": "LEFT"}])
def test_invalid_scroll_parameters_reject_before_any_pointer_input(input_boundary, kwargs):
    with _runtime_backend_input_scope(), pytest.raises(ValueError):
        input_boundary.runtime.scroll_window(x=70, y=80, settle_ms=0, **kwargs)
    assert input_boundary.events == []


@pytest.mark.parametrize("direction,delta", [("up", 240), ("down", -240)])
def test_internal_authority_through_real_backend_and_input_method_reaches_only_fake_os(input_boundary, direction, delta):
    from app.agent.desktop_backend import DesktopDispatchCommand, ExistingWindowsBackendAdapter, _mint_execution_authority
    from app.agent.scroll_parameters import ReviewedScrollParameters, ScrollDispatchParameters

    scroll = ScrollDispatchParameters(
        parameters=ReviewedScrollParameters(target_container_id="pane", axis="vertical", direction=direction, wheel_clicks=2, unit="wheel_detent"),
        target_bbox=(20.0, 30.0, 100.0, 100.0), viewport_size=(800, 600),
    )
    command = DesktopDispatchCommand(semantic_action="scroll_region", capture_id="capture-current", candidate_id="candidate-current", click_point=(70.0, 80.0), target_window_handle=4242, scroll=scroll)
    authority = _mint_execution_authority(
        session_id="s", observation_id="o", intent_id="i", workflow_revision_hash="b" * 64,
        semantic_action=command.semantic_action, selection_sha256="a" * 64, capture_id=command.capture_id,
        candidate_id=command.candidate_id, click_point=command.click_point, target_window_handle=4242,
        gate_decision_ref="gate:current", scroll=scroll,
    )
    adapter = ExistingWindowsBackendAdapter(input_controller=input_boundary.runtime, window_manager=input_module.window_manager)
    assert adapter.dispatch(command, authority=authority).status == "dispatched"
    with pytest.raises(PermissionError, match="already consumed"):
        adapter.dispatch(command, authority=authority)
    wheels = [event[1] for event in input_boundary.events if event[0] == "wheel"]
    assert wheels == [{"dx": 0, "dy": 0, "flags": input_module.MOUSEEVENTF_WHEEL, "mouse_data": delta}]
