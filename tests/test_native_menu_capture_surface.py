"""原生菜单采集与输入必须使用同一新鲜窗口原点。"""
from types import SimpleNamespace
import pytest
import app.core.window_manager as module
from app.core.screenshot import ScreenshotService
from app.core.window_manager import BoundWindow, WindowManager, WindowRect


def gui_scene(items=(), *, menu=10):
    return SimpleNamespace(
        GetClientRect=lambda h: (0, 0, 400, 300),
        ClientToScreen=lambda h, p: (100 + p[0], 200 + p[1]),
        GetWindowRect=lambda h: (92, 152, 508, 508),
        GetMenu=lambda h: menu,
        GetMenuItemCount=lambda m: len(items),
        GetMenuItemRect=lambda h, m, i: (1, items[i]),
    )


def test_no_native_menu_preserves_client_surface():
    assert WindowManager._capture_surface_rect(7, gui=gui_scene(menu=0)) == (100, 200, 500, 500)


@pytest.mark.parametrize("items,top", [
    ([(100, 180, 150, 200), (150, 180, 200, 200)], 180),
    ([(100, 160, 450, 180), (100, 180, 150, 200)], 160),
])
def test_attached_menu_includes_its_rows_but_excludes_frame(items, top):
    assert WindowManager._capture_surface_rect(7, gui=gui_scene(items)) == (100, top, 500, 500)


@pytest.mark.parametrize("box", [
    (99, 180, 150, 200), (100, 180, 501, 200),
    (100, 180, 150, 201), (100, 151, 150, 200),
    (100, 180, 100, 200), (100, 180.5, 150, 200),
])
def test_invalid_native_menu_geometry_never_silently_uses_client(box):
    with pytest.raises(ValueError, match="native_capture_menu_area_invalid"):
        WindowManager._capture_surface_rect(7, gui=gui_scene([box]))


def test_changed_attached_menu_rejects_mixed_layout():
    gui = gui_scene([(100, 180, 150, 200)])
    values = iter([10, 11])
    gui.GetMenu = lambda h: next(values)
    with pytest.raises(ValueError, match="native_capture_menu_changed"):
        WindowManager._capture_surface_rect(7, gui=gui)


def test_changed_menu_item_geometry_rejects_mixed_layout():
    gui = gui_scene([(100, 180, 150, 200)])
    values = iter([(100, 180, 150, 200), (100, 175, 150, 200)])
    gui.GetMenuItemRect = lambda h, m, i: (1, next(values))
    with pytest.raises(ValueError, match="native_capture_menu_changed"):
        WindowManager._capture_surface_rect(7, gui=gui)


def test_failed_native_query_never_uses_undefined_rectangle():
    gui = gui_scene([(100, 180, 150, 200)])
    gui.GetMenuItemRect = lambda *args: (0, (100, 180, 150, 200))
    with pytest.raises(ValueError, match="native_capture_menu_query_failed"):
        WindowManager._capture_surface_rect(7, gui=gui)


def test_native_query_failure_is_visible_without_fallback():
    gui = gui_scene([(100, 180, 150, 200)])
    def fail(*args):
        raise OSError("native menu query failed")
    gui.GetMenuItemRect = fail
    with pytest.raises(OSError, match="native menu query failed"):
        WindowManager._capture_surface_rect(7, gui=gui)


def test_menu_capture_and_gate_share_positive_coordinate_origin(monkeypatch):
    gui = gui_scene([(100, 180, 150, 200)])
    manager = WindowManager()
    rect = WindowRect(*manager._capture_surface_rect(7, gui=gui))
    bound = BoundWindow(7, "Fresh native window", 70, "test.exe", rect, True)
    monkeypatch.setattr(module, "WINDOWS_BACKEND_AVAILABLE", True)
    monkeypatch.setattr(module, "win32gui", gui)
    monkeypatch.setattr(manager, "_get_process_id", lambda h: 70)
    monkeypatch.setattr(manager, "_get_process_name", lambda p: "test.exe")
    gui.WindowFromPoint = lambda p: 7
    gui.GetAncestor = lambda h, flag: 7
    gui.IsChild = lambda owner, h: False
    gui.GetWindowText = lambda h: bound.title
    monitor = ScreenshotService(window_manager=manager)._resolve_capture_rect(
        left=rect.left, top=rect.top, right=rect.right, bottom=rect.bottom, roi=None)
    assert (monitor["left"], monitor["top"], monitor["width"], monitor["height"]) == (100, 180, 400, 320)
    hit = manager.validate_bound_point_visibility(bound=bound, x=25, y=10)
    assert hit["allowed"] and hit["screen_point"] == {"x": 125, "y": 190}
    assert not manager.validate_bound_point_visibility(bound=bound, x=25, y=-1)["allowed"]
