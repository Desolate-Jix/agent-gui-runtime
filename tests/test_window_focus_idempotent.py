"""前台准备幂等，不用缓存状态跳过身份核验或后台激活。"""
from types import SimpleNamespace as NS

import pytest

from app.core import window_manager as windows


@pytest.fixture
def scene(monkeypatch):
    state = NS(foreground=100, snapshot_foreground=None, foreground_reads=0,
               pid=10, popup_pid=10, popup_owner=100, activation_effect=True,
               mutations=[])

    def foreground():
        state.foreground_reads += 1
        if state.foreground_reads == 1 and state.snapshot_foreground is not None:
            return state.snapshot_foreground
        return state.foreground

    def ancestor(handle, flag):
        return state.popup_owner if handle == 200 and flag == 3 else handle

    def thread_identity(handle):
        pid = state.pid if handle == 100 else state.popup_pid if handle == 200 else 99
        return handle + 10, pid

    def activate(handle):
        state.mutations.append(("foreground", handle))
        if state.activation_effect:
            state.foreground = handle

    monkeypatch.setattr(windows, "WINDOWS_BACKEND_AVAILABLE", True)
    monkeypatch.setattr(windows, "win32gui", NS(
        GetForegroundWindow=foreground, GetAncestor=ancestor,
        IsWindow=lambda handle: True, IsWindowVisible=lambda handle: True,
        IsIconic=lambda handle: False, GetClassName=lambda handle: "EditorWindow",
        BringWindowToTop=lambda handle: state.mutations.append(("bring", handle)),
        SetWindowPos=lambda handle, order, *args: state.mutations.append(("position", handle, order)),
        SetForegroundWindow=activate))
    monkeypatch.setattr(windows, "win32process", NS(
        GetWindowThreadProcessId=thread_identity,
        AttachThreadInput=lambda current, target, enabled:
            state.mutations.append(("attach", current, target, enabled))))
    monkeypatch.setattr(windows, "win32api", NS(
        GetCurrentThreadId=lambda: 1, SetLastError=lambda code: None))
    monkeypatch.setattr(windows, "win32con", NS(
        GA_ROOT=2, GA_ROOTOWNER=3, HWND_TOPMOST=-1, HWND_NOTOPMOST=-2,
        SWP_NOMOVE=2, SWP_NOSIZE=1, SWP_SHOWWINDOW=64))
    monkeypatch.setattr(windows, "HwndWrapper", lambda handle:
                        NS(handle=handle, window_text=lambda: "Current title"))
    monkeypatch.setattr(windows.time, "sleep", lambda seconds: None)
    manager = windows.WindowManager()
    manager._bound_window = windows.BoundWindow(
        100, "Cached title", 10, "editor.exe", windows.WindowRect(0, 0, 200, 150), False)
    monkeypatch.setattr(manager, "_ensure_window_mutation_authority", lambda **kwargs: None)
    monkeypatch.setattr(manager, "_capture_surface_rect", lambda handle: (0, 0, 200, 150))
    monkeypatch.setattr(manager, "_get_process_name", lambda pid: "editor.exe")
    return manager, state


@pytest.mark.parametrize("cached_active", [False, True])
def test_same_foreground_window_is_refreshed_without_reactivation(scene, cached_active):
    manager, state = scene
    manager._bound_window.is_active = cached_active
    for _ in range(2):
        current = manager.focus_bound_window()
        assert (current.handle, current.process_id, current.title) == (100, 10, "Current title")
    assert state.foreground == 100
    assert state.mutations == []


@pytest.mark.parametrize("snapshot,current,activated", [(100, 999, True), (999, 100, False)])
def test_fresh_foreground_controls_activation_instead_of_refreshed_active_flag(
        scene, snapshot, current, activated):
    manager, state = scene
    state.snapshot_foreground, state.foreground = snapshot, current
    result = manager.focus_bound_window()
    assert result.handle == 100
    assert (("foreground", 100) in state.mutations) is activated
    if not activated:
        assert state.mutations == []


@pytest.mark.parametrize("foreground", [0, 999])
def test_background_or_unknown_foreground_still_activates_and_verifies(scene, foreground):
    manager, state = scene
    manager._bound_window.is_active = True
    state.foreground = foreground
    result = manager.focus_bound_window()
    assert result.handle == 100 and result.is_active is True
    assert state.mutations.count(("foreground", 100)) == 1
    assert ("bring", 100) in state.mutations
    assert ("position", 100, -1) in state.mutations
    assert ("position", 100, -2) in state.mutations
    assert ("attach", 1, 110, True) in state.mutations
    assert ("attach", 1, 110, False) in state.mutations


def test_activation_api_return_without_actual_foreground_still_refuses(scene):
    manager, state = scene
    state.foreground, state.activation_effect = 999, False
    with pytest.raises(RuntimeError, match="foreground verification failed"):
        manager.focus_bound_window()
    assert state.foreground == 999
    assert state.mutations.count(("foreground", 100)) == 1


@pytest.mark.parametrize("owner,pid,preserved", [(100, 10, True), (999, 10, False), (100, 99, False)])
def test_only_exact_owned_foreground_popup_is_preserved(scene, owner, pid, preserved):
    manager, state = scene
    state.foreground, state.popup_owner, state.popup_pid = 200, owner, pid
    assert manager.focus_bound_window().handle == 100
    if preserved:
        assert state.foreground == 200 and state.mutations == []
    else:
        assert state.foreground == 100
        assert state.mutations.count(("foreground", 100)) == 1


@pytest.mark.parametrize("pid", [None, 20])
def test_same_foreground_handle_cannot_bypass_original_process_identity(scene, pid):
    manager, state = scene
    state.pid = pid
    with pytest.raises(ValueError, match="No bound window available to focus"):
        manager.focus_bound_window()
    assert manager._bound_window is None and state.mutations == []


def test_same_foreground_window_still_requires_mutation_authority(scene, monkeypatch):
    manager, state = scene

    def denied(**kwargs):
        raise RuntimeError("window mutation denied")

    monkeypatch.setattr(manager, "_ensure_window_mutation_authority", denied)
    with pytest.raises(RuntimeError, match="window mutation denied"):
        manager.focus_bound_window()
    assert state.foreground_reads == 0 and state.mutations == []
