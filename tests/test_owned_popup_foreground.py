"""模拟前台和像素，避免截图准备自己改变弹窗，再核对输入前归属。"""
from types import SimpleNamespace as NS

import pytest

from app.core import input_controller as inputs
from app.core import screenshot
from app.core import window_manager as windows


@pytest.fixture
def popup_scene(monkeypatch):
    bound = windows.BoundWindow(100, "Editor", 10, "editor.exe",
                               windows.WindowRect(0, 0, 200, 150), False)
    state = NS(foreground=200, owner=100, popup_pid=10, visible=True,
               valid=True, query_error=False, hit_root=200, events=[])

    def ancestor(handle, flag):
        if state.query_error:
            raise OSError("ownership unavailable")
        return state.owner if flag == 3 and handle == 200 else handle

    gui = NS(GetForegroundWindow=lambda: state.foreground,
             GetAncestor=ancestor, IsWindow=lambda h: state.valid,
             IsWindowVisible=lambda h: state.visible, IsIconic=lambda h: False,
             GetClassName=lambda h: "Dialog", GetWindowText=lambda h: "Notice",
             WindowFromPoint=lambda p: state.hit_root,
             IsChild=lambda parent, child: False,
             GetWindowRect=lambda h: (20, 20, 180, 120))
    monkeypatch.setattr(windows, "win32gui", gui)
    monkeypatch.setattr(windows, "win32con", NS(GA_ROOT=2, GA_ROOTOWNER=3))
    manager = windows.WindowManager()
    monkeypatch.setattr(manager, "_ensure_windows_backend", lambda: None)
    monkeypatch.setattr(manager, "_ensure_window_mutation_authority", lambda **k: None)
    monkeypatch.setattr(manager, "get_bound_window", lambda: bound)
    monkeypatch.setattr(manager, "_get_process_id", lambda h: 10 if h == 100 else state.popup_pid)
    monkeypatch.setattr(manager, "_get_process_name", lambda p: "editor.exe")
    monkeypatch.setattr(windows.time, "sleep", lambda seconds: None)

    def activate(handle):
        state.events.append(("activate", handle))
        state.foreground = handle

    monkeypatch.setattr(manager, "_activate_window", activate)
    return manager, bound, state, gui


def test_grounding_capture_preserves_owned_popup_pixels(popup_scene, monkeypatch):
    manager, _, state, _ = popup_scene
    service = screenshot.ScreenshotService(window_manager=manager)
    monkeypatch.setattr(service, "_ensure_capture_backend", lambda: None)
    monkeypatch.setattr(service, "_require_capture_visibility", lambda *a: {"allowed": True})
    monkeypatch.setattr(service, "_wait_after_focus", lambda: None)

    class Screen:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def grab(self, monitor):
            color = bytes((0, 0, 255) if state.foreground == 200 else (128, 128, 128))
            return NS(size=(200, 150), rgb=color * 200 * 150)

    pixels = []
    original = screenshot.Image.frombytes

    def image(*args):
        value = original(*args)
        pixels.append(value.getpixel((30, 30)))
        return value

    monkeypatch.setattr(screenshot, "mss", Screen)
    monkeypatch.setattr(screenshot.Image, "frombytes", image)
    service.capture_window(save_image=False, focus_window=False)
    service.capture_window(save_image=False)
    assert pixels == [(0, 0, 255), (0, 0, 255)]
    assert state.foreground == 200 and state.events == []


@pytest.mark.parametrize("field,value", [("owner", 999), ("popup_pid", 99),
    ("visible", False), ("valid", False)])
def test_unproven_popup_does_not_suppress_parent_preparation(popup_scene, field, value):
    manager, bound, state, _ = popup_scene
    setattr(state, field, value)
    assert manager.focus_bound_window() is bound
    assert state.events == [("activate", 100)]
    assert state.foreground == 100


def test_unavailable_popup_ownership_stops_preparation(popup_scene):
    manager, _, state, _ = popup_scene
    state.query_error = True
    with pytest.raises(RuntimeError, match="foreground_popup_ownership_unavailable"):
        manager.focus_bound_window()
    assert state.events == []


@pytest.mark.parametrize("drift", [None, "foreground", "owner", "pid", "hit", "expected"])
def test_click_preserves_exact_owned_popup_and_rejects_drift(popup_scene, monkeypatch, drift):
    manager, bound, state, gui = popup_scene
    controller = inputs.InputController()
    monkeypatch.setattr(inputs, "window_manager", manager)
    monkeypatch.setattr(inputs, "win32gui", gui)
    monkeypatch.setattr(inputs, "win32api", NS(GetCursorPos=lambda: (50, 50)))
    monkeypatch.setattr(controller, "_ensure_windows_input", lambda: None)
    monkeypatch.setattr(controller, "_require_bound_window", lambda: bound)
    monkeypatch.setattr(controller, "_resolve_window_and_screen_point", lambda **k:
                        {"window_x": 50, "window_y": 50, "screen_x": 50, "screen_y": 50})
    monkeypatch.setattr(controller, "_focus_window", manager._activate_window)
    monkeypatch.setattr(controller, "_send_move", lambda *a: None)
    monkeypatch.setattr(controller, "mouse_down", lambda button: state.events.append("down"))
    monkeypatch.setattr(controller, "mouse_up", lambda button: state.events.append("up"))

    def settle(seconds):
        if drift == "foreground":
            state.foreground = 201
        elif drift == "owner":
            state.owner = 999
        elif drift == "pid":
            state.popup_pid = 99
        elif drift == "hit":
            state.hit_root = 201

    monkeypatch.setattr(inputs.time, "sleep", settle)
    expected = 201 if drift == "expected" else None
    if drift:
        with pytest.raises((RuntimeError, inputs.TargetPointOccludedError)):
            controller.click_point(50, 50, hold_ms=0, expected_owned_popup_handle=expected)
        assert "down" not in state.events
    else:
        result = controller.click_point(50, 50, hold_ms=0)
        assert result["clicked"] is True
        assert state.events == ["down", "up"]
        assert state.foreground == 200


def test_parent_target_cannot_use_owned_popup_foreground(popup_scene, monkeypatch):
    manager, bound, state, gui = popup_scene
    state.hit_root = 100
    controller = inputs.InputController()
    monkeypatch.setattr(inputs, "window_manager", manager)
    monkeypatch.setattr(inputs, "win32gui", gui)
    monkeypatch.setattr(controller, "_ensure_windows_input", lambda: None)
    monkeypatch.setattr(controller, "_require_bound_window", lambda: bound)
    monkeypatch.setattr(controller, "_resolve_window_and_screen_point", lambda **k:
                        {"window_x": 50, "window_y": 50, "screen_x": 50, "screen_y": 50})
    monkeypatch.setattr(controller, "_focus_window", manager._activate_window)
    monkeypatch.setattr(controller, "mouse_down", lambda button: state.events.append("down"))
    with pytest.raises(inputs.TargetPointOccludedError):
        controller.click_point(50, 50, move_before_click=False, hold_ms=0)
    assert state.events == []
