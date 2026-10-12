"""父窗点击须有 Decision 票据及实时几何证明；全部系统输入均为离线替身。"""
from types import SimpleNamespace as NS

import pytest

from app.core import input_controller as inputs
from app.core import window_manager as windows


@pytest.fixture
def scene(monkeypatch):
    bound = windows.BoundWindow(100, "Browser", 10, "browser.exe",
        windows.WindowRect(0, 0, 2560, 1400), False)
    state = NS(foreground=200, owner=100, popup_pid=10, hit=100, enabled=True,
        enabled_error=False, region=True, events=[], dismiss=False)

    def ancestor(handle, flag):
        if handle == 101:
            return 100
        return state.owner if flag == 3 and handle == 200 else handle

    def enabled(handle):
        if state.enabled_error:
            raise OSError("enabled state unavailable")
        return state.enabled

    gui = NS(GetForegroundWindow=lambda: state.foreground, GetAncestor=ancestor,
        IsWindow=lambda h: True, IsWindowVisible=lambda h: True, IsIconic=lambda h: False,
        IsWindowEnabled=enabled, GetWindowText=lambda h: "Notice", GetClassName=lambda h: "Window",
        WindowFromPoint=lambda p: state.hit, IsChild=lambda p, h: p == 100 and h == 101,
        GetWindowRect=lambda h: (2166, 80, 2486, 215) if h == 200 else (0, 0, 2560, 1400))
    manager = windows.WindowManager()
    monkeypatch.setattr(windows, "win32gui", gui)
    monkeypatch.setattr(windows, "win32con", NS(GA_ROOT=2, GA_ROOTOWNER=3))
    monkeypatch.setattr(manager, "_ensure_windows_backend", lambda: None)
    monkeypatch.setattr(manager, "get_bound_window", lambda: bound)
    monkeypatch.setattr(manager, "_get_process_id", lambda h: state.popup_pid if h == 200 else 10)
    monkeypatch.setattr(manager, "_get_process_name", lambda p: "browser.exe")
    monkeypatch.setattr(manager, "validate_bound_region_visibility", lambda **k:
        {"allowed": state.region, "reason": "target_region_visible" if state.region else "target_region_occluded"})
    controller = inputs.InputController()
    monkeypatch.setattr(inputs, "window_manager", manager)
    monkeypatch.setattr(inputs, "win32gui", gui)
    monkeypatch.setattr(inputs, "win32api", NS(GetCursorPos=lambda: (1008, 49)))
    monkeypatch.setattr(controller, "_ensure_windows_input", lambda: None)
    monkeypatch.setattr(controller, "_require_bound_window", lambda: bound)
    monkeypatch.setattr(controller, "_resolve_window_and_screen_point", lambda **k:
        {"window_x": 1008, "window_y": 49, "screen_x": 1008, "screen_y": 49})
    monkeypatch.setattr(controller, "_focus_window", lambda h: state.events.append("focus"))
    monkeypatch.setattr(controller, "_send_move", lambda *a: None)
    monkeypatch.setattr(controller, "_double_click_time_ms", lambda: 500)
    monkeypatch.setattr(inputs.time, "sleep", lambda *a: None)

    def down(button):
        state.events.append("down")
        if state.dismiss:
            state.foreground = 100
        return {"dispatched_monotonic_ns": inputs.time.monotonic_ns()}

    monkeypatch.setattr(controller, "mouse_down", down)
    monkeypatch.setattr(controller, "mouse_up", lambda b: state.events.append("up"))
    return controller, manager, bound, state


def click(controller, **kwargs):
    return controller.click_point(1008, 49, hold_ms=0,
        target_bbox=(300, 30, 1500, 38), **kwargs)


def guard(scene, *, click_count=1, verify=lambda: None, scope=None):
    from app.execution.popup_decision import PopupContinuationGuard, _ISSUER

    return PopupContinuationGuard(_ISSUER, scope=scope or {"active": True}, bound=scene[2],
        point=(1008, 49), bbox=(300, 30, 1500, 38), popup_handle=200,
        click_count=click_count, verify=verify)


@pytest.mark.parametrize("hit", [100, 101])
def test_unobscured_parent_still_rejects_without_decision_guard(scene, hit):
    controller, manager, bound, state = scene
    state.hit = hit
    assert manager.validate_nonmodal_parent_click(bound=bound, x=1008, y=49,
        bbox=(300, 30, 1500, 38), popup_handle=200)["allowed"] is True
    with pytest.raises(inputs.TargetPointOccludedError) as error:
        click(controller)
    assert error.value.button_down_attempted is False
    assert state.events == []


def test_double_click_revalidates_parent_after_first_click_dismisses_popup(scene):
    controller, _, _, state = scene
    state.dismiss = True
    assert click(controller, click_count=2, popup_continuation_guard=guard(scene, click_count=2))["clicked"] is True
    assert state.events == ["down", "up", "down", "up"]


@pytest.mark.parametrize("damage", ["disabled", "enabled_unknown", "enabled_error", "occluded", "foreign_hit", "explicit_popup"])
def test_unsafe_or_explicit_parent_click_is_rejected_without_mouse_down(scene, damage):
    controller, _, _, state = scene
    if damage == "disabled":
        state.enabled = False
    elif damage == "enabled_unknown":
        state.enabled = None
    elif damage == "enabled_error":
        state.enabled_error = True
    elif damage == "occluded":
        state.region = False
    elif damage == "foreign_hit":
        state.hit = 999
    with pytest.raises((inputs.TargetPointOccludedError, RuntimeError, ValueError)):
        click(controller, popup_continuation_guard=guard(scene),
            **({"expected_owned_popup_handle": 200} if damage == "explicit_popup" else {}))
    assert "down" not in state.events


def test_parent_click_requires_complete_target_bbox(scene):
    controller, _, _, state = scene
    with pytest.raises(inputs.TargetPointOccludedError):
        controller.click_point(1008, 49, hold_ms=0)
    assert "down" not in state.events


@pytest.mark.parametrize("damage", ["disabled", "foreground", "point", "region", "owner", "pid"])
def test_pre_input_validator_cannot_make_nonmodal_proof_stale(scene, damage):
    controller, _, _, state = scene

    def change():
        if damage == "disabled":
            state.enabled = False
        elif damage == "foreground":
            state.foreground = 999
        elif damage == "point":
            state.hit = 999
        elif damage == "region":
            state.region = False
        elif damage == "owner":
            state.owner = 999
        else:
            state.popup_pid = 99
        return True

    with pytest.raises((inputs.TargetPointOccludedError, RuntimeError)):
        click(controller, pre_input_validator=change, popup_continuation_guard=guard(scene))
    assert "down" not in state.events


def test_double_click_does_not_reuse_proof_after_parent_becomes_disabled(scene):
    controller, _, _, state = scene
    state.dismiss = True
    calls = []

    def change():
        calls.append(1)
        if len(calls) == 2:
            state.enabled = False
        return True

    with pytest.raises((inputs.TargetPointOccludedError, RuntimeError)) as error:
        click(controller, click_count=2, pre_input_validator=change,
            popup_continuation_guard=guard(scene, click_count=2))
    assert state.events == ["down", "up"]
    assert error.value.click_sequence["completed_clicks"] == 1
    assert error.value.button_down_attempted is True


@pytest.mark.parametrize("hit", [100, 101])
def test_decision_guard_allows_only_unobscured_enabled_parent_or_child(scene, hit):
    controller, _, _, state = scene
    state.hit = hit
    assert click(controller, popup_continuation_guard=guard(scene))["clicked"] is True
    assert state.events == ["down", "up"]


@pytest.mark.parametrize("invalid", [True, {}, object()])
def test_public_values_cannot_replace_host_guard(scene, invalid):
    controller, _, _, state = scene
    with pytest.raises(ValueError):
        click(controller, popup_continuation_guard=invalid)
    assert state.events == []


def test_guard_is_consumed_for_one_complete_click_call(scene):
    controller, _, _, state = scene
    approved = guard(scene)
    click(controller, popup_continuation_guard=approved)
    with pytest.raises(inputs.TargetPointOccludedError) as error:
        click(controller, popup_continuation_guard=approved)
    assert error.value.button_down_attempted is False
    assert state.events == ["down", "up"]


def test_guard_reverification_precedes_final_geometry_check(scene):
    controller, _, _, state = scene

    def changed():
        state.enabled = False

    with pytest.raises(inputs.TargetPointOccludedError) as error:
        click(controller, popup_continuation_guard=guard(scene, verify=changed))
    assert error.value.button_down_attempted is False
    assert state.events == []


def test_owned_popup_intersection_cannot_be_hidden_by_generic_region_success(scene, monkeypatch):
    controller, _, _, state = scene
    monkeypatch.setattr(inputs.win32gui, "GetWindowRect", lambda h:
        (900, 40, 1100, 70) if h == 200 else (0, 0, 2560, 1400))
    with pytest.raises(inputs.TargetPointOccludedError) as error:
        click(controller, popup_continuation_guard=guard(scene))
    assert error.value.evidence["reason"] == "nonmodal_parent_popup_overlaps_target"
    assert error.value.button_down_attempted is False
    assert state.events == []


def test_occlusion_error_defaults_to_unknown_button_attempt():
    assert inputs.TargetPointOccludedError({"reason": "unknown"}).button_down_attempted is None


def test_occlusion_error_accepts_internal_explicit_no_button_attempt():
    error = inputs.TargetPointOccludedError({"reason": "blocked"}, button_down_attempted=False)
    assert error.button_down_attempted is False


def test_initial_occlusion_proves_no_button_down(scene):
    controller, _, _, state = scene
    state.hit = 999
    with pytest.raises(inputs.TargetPointOccludedError) as error:
        click(controller)
    assert error.value.button_down_attempted is False
    assert "down" not in state.events


def test_second_click_occlusion_proves_prior_button_attempt(scene, monkeypatch):
    controller, manager, _, state = scene
    state.foreground = 100
    calls = []
    original = manager.validate_bound_point_visibility

    def visibility(**kwargs):
        calls.append(1)
        return original(**kwargs) if len(calls) == 1 else {"allowed": False, "reason": "changed"}

    monkeypatch.setattr(manager, "validate_bound_point_visibility", visibility)
    with pytest.raises(inputs.TargetPointOccludedError) as error:
        click(controller, click_count=2)
    assert error.value.button_down_attempted is True
    assert error.value.click_sequence["completed_clicks"] == 1
    assert state.events == ["focus", "down", "up"]


def test_validator_cannot_reuse_false_proof_after_first_button_attempt(scene):
    controller, _, _, state = scene
    state.foreground = 100
    calls = []

    def validator():
        calls.append(1)
        if len(calls) == 2:
            raise inputs.TargetPointOccludedError({"reason": "changed"}, button_down_attempted=False)

    with pytest.raises(inputs.TargetPointOccludedError) as error:
        click(controller, click_count=2, pre_input_validator=validator)
    assert error.value.button_down_attempted is True
    assert error.value.click_sequence["completed_clicks"] == 1


@pytest.mark.parametrize("enabled", [True, False])
def test_popup_snapshot_reports_enabled_fact_without_policy(scene, enabled):
    _, manager, bound, state = scene
    state.enabled = enabled
    assert manager.read_owned_foreground_popup(bound) == {"handle": 200, "parent_handle": 100,
        "process_id": 10, "rect": [2166, 80, 2486, 215], "parent_enabled": enabled}


def test_popup_snapshot_returns_none_when_no_owned_popup(scene):
    _, manager, bound, state = scene
    state.foreground = 100
    assert manager.read_owned_foreground_popup(bound) is None


@pytest.mark.parametrize("damage", ["enabled_unknown", "enabled_error", "owner_drift", "rect_unknown"])
def test_popup_snapshot_rejects_unknown_or_changed_native_facts(scene, monkeypatch, damage):
    _, manager, bound, state = scene
    if damage == "enabled_unknown":
        state.enabled = None
    elif damage == "enabled_error":
        state.enabled_error = True
    elif damage == "rect_unknown":
        monkeypatch.setattr(inputs.win32gui, "GetWindowRect", lambda h: None)
    else:
        def moved(handle):
            state.owner = 999
            return (2166, 80, 2486, 215)
        monkeypatch.setattr(inputs.win32gui, "GetWindowRect", moved)
    with pytest.raises(RuntimeError):
        manager.read_owned_foreground_popup(bound)


def test_first_guard_refusal_proves_zero_button_attempt(scene):
    controller, _, _, state = scene
    with pytest.raises(inputs.TargetPointOccludedError) as error:
        click(controller, popup_continuation_guard=guard(scene, scope={"active": False}))
    assert error.value.evidence["reason"] == "popup_continuation_guard_invalid"
    assert error.value.button_down_attempted is False
    assert state.events == []


def test_second_guard_refusal_retains_prior_button_attempt(scene):
    controller, _, _, state = scene
    calls = []

    def verify():
        calls.append(1)
        if len(calls) == 2:
            raise ValueError("popup_changed")

    with pytest.raises(inputs.TargetPointOccludedError) as error:
        click(controller, click_count=2,
            popup_continuation_guard=guard(scene, click_count=2, verify=verify))
    assert error.value.evidence["reason"] == "popup_continuation_guard_invalid"
    assert error.value.button_down_attempted is True
    assert error.value.click_sequence["completed_clicks"] == 1
    assert state.events == ["down", "up"]
