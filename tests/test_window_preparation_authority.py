"""本地窗口准备只复用聚焦，不授予键鼠或其他窗口变更。"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.core import window_manager as wm
from app.core.runtime_input_authority import runtime_backend_input_is_active


@pytest.fixture
def scene(monkeypatch):
    manager = wm.WindowManager()
    state = SimpleNamespace(active=0, iconic=False, mutations=[], blocked=[], fail=False)
    identity = {
        "contract_version": "windows_native_identity_observation_v1",
        "provider": "windows_native_identity", "status": "observed",
        "target_window_handle": 321, "process_id": 12,
        "process_create_time": 123.5, "executable_path": "c:\\fixture\\editor.exe",
    }

    def mutation(name, *args):
        assert not runtime_backend_input_is_active()
        state.mutations.append((name, *args))

    def foreground(handle):
        mutation("foreground", handle)
        if state.fail:
            raise OSError("synthetic foreground denial")
        state.active = handle

    class Wrapper:
        def __init__(self, handle): self.handle = handle
        def window_text(self): return "Synthetic editor"

    gui = SimpleNamespace(
        IsWindow=lambda h: h == 321, IsWindowVisible=lambda h: True,
        GetAncestor=lambda h, flag: h, GetWindowRect=lambda h: (0, 0, 800, 600),
        GetClientRect=lambda h: (0, 0, 800, 600), ClientToScreen=lambda h, p: p,
        GetForegroundWindow=lambda: state.active, IsIconic=lambda h: state.iconic,
        ShowWindow=lambda *args: mutation("restore", *args),
        BringWindowToTop=lambda h: mutation("top", h),
        SetWindowPos=lambda *args: mutation("position", *args), SetForegroundWindow=foreground,
    )
    def forbidden_input(*_args):
        state.blocked.append("input")
        raise AssertionError("local preparation must not generate input")
    monkeypatch.setattr(wm, "WINDOWS_BACKEND_AVAILABLE", True)
    monkeypatch.setattr(wm, "win32gui", gui)
    monkeypatch.setattr(wm, "win32api", SimpleNamespace(GetCurrentThreadId=lambda: 1, keybd_event=forbidden_input))
    monkeypatch.setattr(wm, "win32process", SimpleNamespace(GetWindowThreadProcessId=lambda h: (1, 12)))
    monkeypatch.setattr(wm, "HwndWrapper", Wrapper)
    # 仅替换窗口模块的时钟引用，不能让 HTTP 拥有者的等待变成忙循环。
    monkeypatch.setattr(wm, "time", SimpleNamespace(sleep=lambda _s: None))
    monkeypatch.setattr(manager, "_get_process_name", lambda _pid: "editor.exe")
    manager.bind_window_by_handle(321)
    reader = SimpleNamespace(read_identity=lambda h: deepcopy(identity))
    return manager, state, identity, reader


def permit_for(manager, identity, reader):
    assert callable(getattr(manager, "prepare_bound_window", None)), "formal window preparation is not connected"
    from app.core.window_preparation import _mint_window_preparation_permit
    return _mint_window_preparation_permit(manager, identity, reader)


@pytest.mark.parametrize("minimized", [False, True])
def test_local_confirmed_prepare_restores_and_focuses_once_without_input(scene, minimized):
    manager, state, identity, reader = scene
    state.iconic = minimized
    permit = permit_for(manager, identity, reader)
    assert state.mutations == []
    result = manager.prepare_bound_window(permit)
    assert result.handle == 321 and result.is_active is True
    assert [call for call in state.mutations if call[0] == "restore"] == (
        [("restore", 321, wm.win32con.SW_RESTORE)] if minimized else []
    )
    before = list(state.mutations)
    with pytest.raises(PermissionError):
        manager.prepare_bound_window(permit)
    assert state.mutations == before and state.blocked == []
    with pytest.raises(PermissionError):
        manager.focus_bound_window()
    assert not runtime_backend_input_is_active()


@pytest.mark.parametrize("field,value", [
    ("process_id", 99), ("process_create_time", 124.0),
    ("executable_path", "c:\\other\\editor.exe"), ("target_window_handle", 999),
])
def test_identity_drift_consumes_prepare_without_mutation(scene, field, value):
    manager, state, identity, reader = scene
    permit = permit_for(manager, identity, reader)
    identity[field] = value
    with pytest.raises(PermissionError):
        manager.prepare_bound_window(permit)
    assert state.mutations == []
    with pytest.raises(PermissionError):
        manager.prepare_bound_window(permit)


def test_preparation_never_opens_resize_maximize_or_different_window_authority(scene, monkeypatch):
    manager, state, identity, reader = scene
    permit = permit_for(manager, identity, reader)
    original = wm.win32gui.BringWindowToTop
    denied = []
    def top(handle):
        for operation in (lambda: manager.resize_bound_window(width=80, height=60),
                          manager.maximize_bound_window,
                          lambda: manager._activate_window(999)):
            with pytest.raises(PermissionError): operation()
            denied.append(True)
        original(handle)
    monkeypatch.setattr(wm.win32gui, "BringWindowToTop", top)
    manager.prepare_bound_window(permit)
    assert len(denied) == 3 and state.blocked == []


def test_foreground_denial_does_not_inject_alt_or_report_success(scene):
    manager, state, identity, reader = scene
    state.fail = True
    permit = permit_for(manager, identity, reader)
    with pytest.raises(RuntimeError, match="foreground"):
        manager.prepare_bound_window(permit)
    assert state.active == 0 and state.blocked == []
    assert not runtime_backend_input_is_active()


def test_forged_or_cross_manager_permit_has_no_effect(scene):
    manager, state, identity, reader = scene
    permit = permit_for(manager, identity, reader)
    for wrong in (object(), deepcopy(identity)):
        with pytest.raises(PermissionError): manager.prepare_bound_window(wrong)
    with pytest.raises(PermissionError): wm.WindowManager().prepare_bound_window(permit)
    assert state.mutations == []


def test_post_focus_process_replacement_is_not_reported_as_prepared(scene, monkeypatch):
    manager, state, identity, reader = scene
    permit = permit_for(manager, identity, reader)
    original = wm.win32gui.SetForegroundWindow
    def replaced(handle):
        original(handle)
        identity["process_create_time"] = 900.0
    monkeypatch.setattr(wm.win32gui, "SetForegroundWindow", replaced)
    with pytest.raises(PermissionError, match="identity changed"):
        manager.prepare_bound_window(permit)
    assert state.active == 321 and state.blocked == []
    with pytest.raises(PermissionError): manager.focus_bound_window()


def test_expired_and_immutable_permit_cannot_be_retargeted(scene, monkeypatch):
    manager, state, identity, reader = scene
    permit = permit_for(manager, identity, reader)
    with pytest.raises(AttributeError): permit.manager = wm.WindowManager()
    with pytest.raises(AttributeError): permit._used = False
    with pytest.raises(AttributeError): del permit._used
    with pytest.raises(TypeError): permit.identity["process_id"] = 77
    import app.core.window_preparation as preparation
    monkeypatch.setattr(preparation, "monotonic", lambda: permit.expires + 1)
    with pytest.raises(PermissionError): manager.prepare_bound_window(permit)
    assert state.mutations == []
