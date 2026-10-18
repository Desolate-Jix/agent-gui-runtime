"""真实输入边界替换为记录器，取消仅允许同次按钮清理。"""
from contextvars import copy_context
from copy import deepcopy
from threading import Thread
from types import SimpleNamespace
import ctypes

import pytest

from app.core import input_controller as module
from app.core.local_input_policy import _local_operator_input_scope
from app.core.window_manager import BoundWindow, WindowRect


@pytest.fixture
def local_click(monkeypatch):
    bound = BoundWindow(321, "fixture", 12, "fixture.exe", WindowRect(100, 200, 900, 800), True)
    identity = {"contract_version": "windows_native_identity_observation_v1", "provider": "windows_native_identity",
        "status": "observed", "target_window_handle": 321, "process_id": 12,
        "process_create_time": 123.5, "executable_path": "c:\\fixture\\editor.exe"}
    manager = SimpleNamespace(get_bound_window=lambda: bound,
        validate_bound_point_visibility=lambda **kw: {"allowed": True})
    state = SimpleNamespace(enabled=True, events=[], on_down=lambda: None)
    controller = module.InputController()
    monkeypatch.setattr(module, "WINDOWS_INPUT_AVAILABLE", True)
    monkeypatch.setattr(module, "window_manager", manager)
    monkeypatch.setattr(module, "runtime_backend_input_is_active", lambda: False)
    monkeypatch.setattr(module, "win32gui", SimpleNamespace(GetForegroundWindow=lambda: 321))
    monkeypatch.setattr(module, "win32api", SimpleNamespace(GetCursorPos=lambda: (120, 230)))
    monkeypatch.setattr(controller, "_require_bound_window", lambda: bound)
    monkeypatch.setattr(controller, "_focus_window", lambda handle: True)
    monkeypatch.setattr(controller, "_resolve_window_and_screen_point", lambda **kw:
        {"window_x": 20, "window_y": 30, "screen_x": 120, "screen_y": 230})
    def send(_count, pointer, _size):
        flags = ctypes.cast(pointer, ctypes.POINTER(module.INPUT)).contents.union.mi.dwFlags
        state.events.append(flags)
        if flags in {module.MOUSEEVENTF_LEFTDOWN, module.MOUSEEVENTF_RIGHTDOWN, module.MOUSEEVENTF_MIDDLEDOWN}:
            state.on_down()
        return 1
    monkeypatch.setattr(module.ctypes, "windll", SimpleNamespace(user32=SimpleNamespace(SendInput=send)))
    monkeypatch.setattr(module, "time", SimpleNamespace(sleep=lambda seconds: None))
    with _local_operator_input_scope(manager=manager, identity_reader=SimpleNamespace(read_identity=lambda h: deepcopy(identity)),
            identity=identity, window_rect=(100, 200, 900, 800), enabled=lambda: state.enabled):
        yield controller, state, bound


@pytest.mark.parametrize("button", ["left", "right", "middle"])
@pytest.mark.parametrize("change", ["cancel", "geometry"])
def test_same_button_releases_after_cancel_or_geometry_change(local_click, button, change):
    controller, state, bound = local_click
    def change_after_down():
        if change == "cancel": state.enabled = False
        else: bound.rect.left += 1
    state.on_down = change_after_down
    result = controller.click_point(20, 30, button=button, move_before_click=False, hold_ms=0)
    assert result["up"]["state"] == "up"
    assert state.events == [controller._button_down_flag(button), controller._button_up_flag(button)]
    for operation in (lambda: controller.mouse_down(button), lambda: controller.mouse_up(button)):
        with pytest.raises(PermissionError): operation()
    assert len(state.events) == 2


def test_uncertain_down_still_releases_and_preserves_original_failure(local_click):
    controller, state, _bound = local_click
    def down_error():
        state.enabled = False
        raise RuntimeError("dispatch outcome unknown")
    state.on_down = down_error
    with pytest.raises(RuntimeError, match="dispatch outcome unknown"):
        controller.click_point(20, 30, move_before_click=False, hold_ms=0)
    assert state.events == [module.MOUSEEVENTF_LEFTDOWN, module.MOUSEEVENTF_LEFTUP]


def test_cancel_before_down_never_dispatches_cleanup_input(local_click, monkeypatch):
    controller, state, _bound = local_click
    monkeypatch.setattr(controller, "_focus_window", lambda handle: setattr(state, "enabled", False))
    with pytest.raises(PermissionError):
        controller.click_point(20, 30, move_before_click=False, hold_ms=0)
    assert state.events == []


def test_cleanup_cannot_release_other_button_repeat_or_cross_thread(local_click, monkeypatch):
    controller, state, _bound = local_click
    state.on_down = lambda: setattr(state, "enabled", False)
    original_up = controller.mouse_up
    captured = []
    def guarded_up(button):
        with pytest.raises(PermissionError): original_up("right")
        with pytest.raises(PermissionError): controller.mouse_down(button)
        context = copy_context()
        captured.append(context)
        errors = []
        def worker():
            try: context.run(original_up, button)
            except PermissionError: errors.append("denied")
        thread = Thread(target=worker)
        thread.start(); thread.join()
        assert errors == ["denied"]
        result = original_up(button)
        with pytest.raises(PermissionError): original_up(button)
        return result
    monkeypatch.setattr(controller, "mouse_up", guarded_up)
    controller.click_point(20, 30, move_before_click=False, hold_ms=0)
    with pytest.raises(PermissionError): captured[0].run(original_up, "left")
    assert state.events == [module.MOUSEEVENTF_LEFTDOWN, module.MOUSEEVENTF_LEFTUP]
