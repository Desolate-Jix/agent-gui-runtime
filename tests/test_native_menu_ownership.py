"""真实 Win32 菜单的归属来自 GUI 线程，不一定来自 GW_OWNER。"""
import pytest
import app.core.window_manager as module
from test_capture_window_ownership import _setup


def menu_setup(monkeypatch, *, menu_class="#32768", flags=0x14, owner=101,
               active=100, candidate_thread=7, candidate_pid=10):
    manager, bound, gui = _setup(monkeypatch, overlay=(75, 65, 180, 120))
    gui.GetAncestor = lambda hwnd, mode: 100 if hwnd == 101 else hwnd
    gui.GetClassName = lambda hwnd: menu_class
    gui.GetForegroundWindow = lambda: 100
    monkeypatch.setattr(module.win32process, "GetWindowThreadProcessId",
        lambda hwnd: [7, 10] if hwnd in (100, 101) else [candidate_thread, candidate_pid])
    monkeypatch.setattr(manager, "_read_gui_menu_state",
        lambda thread: {"flags": flags, "active": active, "menu_owner": owner}, raising=False)
    return manager, bound, gui


def test_ownerless_active_native_menu_is_visible(monkeypatch):
    manager, bound, _ = menu_setup(monkeypatch)
    result = manager.validate_bound_capture_visibility(bound=bound,
        rect={"left": 10, "top": 20, "width": 200, "height": 100}, allow_partial=True)
    assert result["reason"] == "capture_window_visible"


def test_active_menu_shadow_is_visible_but_not_an_input_popup(monkeypatch):
    manager, bound, _ = menu_setup(monkeypatch, menu_class="SysShadow")
    result = manager.validate_bound_capture_visibility(bound=bound,
        rect={"left": 10, "top": 20, "width": 200, "height": 100}, allow_partial=True)
    assert result["reason"] == "capture_window_visible"
    assert not manager._is_owned_popup(200, bound.handle)


@pytest.mark.parametrize("changes", [
    {"flags": 0}, {"owner": 300}, {"active": 300}, {"candidate_thread": 8},
    {"candidate_pid": 99}, {"menu_class": "AnotherWindow"},
])
def test_unrelated_window_is_not_a_native_menu(monkeypatch, changes):
    manager, bound, _ = menu_setup(monkeypatch, **changes)
    result = manager.validate_bound_capture_visibility(bound=bound,
        rect={"left": 10, "top": 20, "width": 200, "height": 100}, allow_partial=True)
    assert result["reason"] == "capture_window_partially_visible"


def test_menu_query_failure_preserves_occlusion(monkeypatch):
    manager, bound, _ = menu_setup(monkeypatch)
    def unavailable(thread):
        raise OSError("query failed")
    monkeypatch.setattr(manager, "_read_gui_menu_state", unavailable)
    result = manager.validate_bound_capture_visibility(bound=bound,
        rect={"left": 10, "top": 20, "width": 200, "height": 100}, allow_partial=True)
    assert result["reason"] == "capture_window_partially_visible"


def test_menu_point_requires_exact_observed_menu(monkeypatch):
    manager, bound, gui = menu_setup(monkeypatch)
    gui.WindowFromPoint = lambda point: 200
    gui.IsChild = lambda *_: False
    gui.GetWindowText = lambda _: ""
    monkeypatch.setattr(manager, "_get_process_name", lambda _: "notepad.exe")
    assert not manager.validate_bound_point_visibility(bound=bound, x=80, y=50)["allowed"]
    assert manager.validate_bound_point_visibility(bound=bound, x=80, y=50,
        expected_owned_popup_handle=200)["allowed"]
    assert not manager.validate_bound_point_visibility(bound=bound, x=80, y=50,
        expected_owned_popup_handle=201)["allowed"]


def test_uia_collects_ownerless_menu_but_not_shadow(monkeypatch):
    import app.operation.screen_reading.uia_provider as provider
    manager, bound, gui = menu_setup(monkeypatch)
    gui.EnumWindows = lambda callback, context: [callback(h, context) for h in (100, 200, 201)]
    gui.GetClassName = lambda hwnd: "SysShadow" if hwnd == 201 else "#32768"
    monkeypatch.setattr(provider, "window_manager", manager)
    import win32gui
    for name in ("IsWindow", "IsWindowVisible", "GetAncestor", "EnumWindows"):
        monkeypatch.setattr(win32gui, name, getattr(gui, name))
    assert provider.WindowsUIAProvider._owned_popup_handles(bound) == [200]
