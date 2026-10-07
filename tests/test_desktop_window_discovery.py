"""桌面图标宿主可无标题；壁纸层和普通无标题窗口不能冒充桌面。"""
from types import SimpleNamespace

import pytest

import app.core.window_manager as module
from app.core.window_manager import WindowManager


@pytest.fixture
def desktop_scene(monkeypatch):
    rows = {
        100: ["Progman", "Program Manager", 10],
        110: ["WorkerW", "", 10],
        120: ["WorkerW", "", 10],
        130: ["WorkerW", "", 20],
        200: ["Notepad", "Document", 30],
        210: ["HiddenHelper", "", 30],
    }
    state = SimpleNamespace(icon_host=110, foreground=200)
    wrappers = {h: SimpleNamespace(handle=h, window_text=lambda h=h: rows[h][1]) for h in rows}
    gui = SimpleNamespace(
        IsWindow=lambda h: h in rows,
        IsWindowVisible=lambda h: h in rows,
        GetAncestor=lambda h, flag: h,
        GetClassName=lambda h: rows[h][0],
        GetForegroundWindow=lambda: state.foreground,
        FindWindowEx=lambda h, after, cls, title: (
            111 if h == state.icon_host and cls == "SHELLDLL_DefView" else
            112 if h == 111 and cls == "SysListView32" else 0),
        GetMenu=lambda h: 0,
        GetClientRect=lambda h: (0, 0, 1920, 1080),
        ClientToScreen=lambda h, pt: pt,
    )
    monkeypatch.setattr(module, "WINDOWS_BACKEND_AVAILABLE", True)
    monkeypatch.setattr(module, "win32gui", gui)
    monkeypatch.setattr(module, "HwndWrapper", lambda h: wrappers[h])
    monkeypatch.setattr(module, "Desktop", lambda **kw: SimpleNamespace(windows=lambda: list(wrappers.values())))
    manager = WindowManager()
    monkeypatch.setattr(manager, "_get_process_id", lambda h: rows[h][2])
    monkeypatch.setattr(manager, "_get_process_name", lambda p: "explorer.exe" if p == 10 else "app.exe")
    # GetShellWindow 在此固定为已核验的系统 Shell；不模拟生产候选筛选。
    monkeypatch.setattr(manager, "_shell_window_handle", lambda: 100, raising=False)
    return manager, state, rows


def test_discovery_returns_icon_host_not_titled_program_manager(desktop_scene):
    manager, _, _ = desktop_scene
    windows = manager.list_visible_windows()
    assert [w["handle"] for w in windows] == [110, 200]
    desktop = windows[0]
    assert desktop["title"] is None
    assert desktop["window_kind"] == "desktop"
    assert desktop["display_name"] == "Windows Desktop"


def test_untitled_desktop_can_bind_and_refresh_without_switching_handles(desktop_scene):
    manager, _, _ = desktop_scene
    bound = manager.bind_window_by_handle(110)
    assert bound.handle == 110 and bound.process_id == 10
    assert manager.get_bound_window().handle == 110


def test_program_manager_is_valid_when_it_really_owns_icons(desktop_scene):
    manager, state, _ = desktop_scene
    state.icon_host = 100
    windows = manager.list_visible_windows()
    assert [w["handle"] for w in windows] == [100, 200]
    assert windows[0]["window_kind"] == "desktop"


@pytest.mark.parametrize("handle", [100, 120, 130, 210])
def test_background_and_unrelated_untitled_windows_are_not_bindable(desktop_scene, handle):
    manager, _, _ = desktop_scene
    with pytest.raises(ValueError):
        manager.bind_window_by_handle(handle)


def test_lookalike_desktop_tree_in_another_process_is_not_trusted(desktop_scene):
    manager, state, _ = desktop_scene
    state.icon_host = 130
    assert [w["handle"] for w in manager.list_visible_windows()] == [200]


def test_moved_icon_tree_invalidates_old_desktop_binding(desktop_scene):
    manager, state, _ = desktop_scene
    manager.bind_window_by_handle(110)
    state.icon_host = 120
    assert manager.get_bound_window() is None
    assert manager.bind_window_by_handle(120).handle == 120


def test_shell_query_failure_does_not_expose_program_manager_as_desktop(desktop_scene, monkeypatch):
    manager, _, _ = desktop_scene
    def unavailable():
        raise OSError("shell query unavailable")
    monkeypatch.setattr(manager, "_shell_window_handle", unavailable)
    assert [w["handle"] for w in manager.list_visible_windows()] == [200]


def test_bound_window_can_refresh_current_empty_title_and_recover_title(desktop_scene):
    manager, _, rows = desktop_scene
    original = manager.bind_window_by_handle(200)
    rows[200][1] = ''
    refreshed = manager.get_bound_window()
    assert refreshed is not None
    assert refreshed.handle == original.handle and refreshed.process_id == original.process_id
    assert refreshed.title is None
    rows[200][1] = 'Saved document'
    assert manager.get_bound_window().title == 'Saved document'


def test_new_untitled_regular_window_stays_unlisted_and_unbindable(desktop_scene):
    manager, _, rows = desktop_scene
    rows[200][1] = ''
    assert [row['handle'] for row in manager.list_visible_windows()] == [110]
    with pytest.raises(ValueError, match='not a supported'):
        manager.bind_window_by_handle(200)


@pytest.mark.parametrize('pid', [None, 0, False, '30', 31])
@pytest.mark.parametrize('title', ['', 'Document'])
def test_bound_refresh_rejects_changed_or_unverifiable_pid(desktop_scene, monkeypatch, pid, title):
    manager, _, rows = desktop_scene
    manager.bind_window_by_handle(200)
    rows[200][1] = title
    monkeypatch.setattr(manager, '_get_process_id', lambda handle: pid)
    assert manager.get_bound_window() is None


@pytest.mark.parametrize('invalid', ['hidden', 'destroyed', 'child'])
def test_bound_refresh_rejects_invalid_window_even_with_same_pid(desktop_scene, monkeypatch, invalid):
    manager, _, rows = desktop_scene
    manager.bind_window_by_handle(200)
    rows[200][1] = ''
    if invalid == 'hidden':
        monkeypatch.setattr(module.win32gui, 'IsWindowVisible', lambda h: h != 200)
    elif invalid == 'destroyed':
        monkeypatch.setattr(module.win32gui, 'IsWindow', lambda h: h != 200)
    else:
        monkeypatch.setattr(module.win32gui, 'GetAncestor', lambda h, flag: 100 if h == 200 else h)
    assert manager.get_bound_window() is None


def test_bound_refresh_rejects_pid_change_during_state_rebuild(desktop_scene, monkeypatch):
    manager, _, _ = desktop_scene
    manager.bind_window_by_handle(200)
    identities = iter([30, 31])
    monkeypatch.setattr(manager, '_get_process_id', lambda h: next(identities))
    assert manager.get_bound_window() is None
