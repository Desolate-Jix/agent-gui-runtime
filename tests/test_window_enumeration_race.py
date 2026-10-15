"""窗口清单逐项处理已消失的 HWND，不吞掉其他发现错误。"""
from copy import deepcopy
from types import SimpleNamespace
import time

import pytest

import app.core.window_manager as windows_module
from app.core.window_manager import WindowManager
from app.desktop_review import window_preparation as preparation
from tests.test_launched_window_close import Coordinator, IDENTITY


class GoneWindow(RuntimeError):
    pass


@pytest.fixture
def scene(monkeypatch):
    state = SimpleNamespace(
        rows={10: "Existing", 20: "Other"}, exists={10, 20},
        wrap_errors={}, title_errors={}, title_calls={}, desktop_calls=0,
        enum_error=None, wrap_calls=[],
    )

    def enum_windows(callback, extra):
        if state.enum_error is not None:
            raise state.enum_error
        for handle in list(state.rows):
            callback(handle, extra)

    def wrap(handle):
        state.wrap_calls.append(handle)
        if handle in state.wrap_errors:
            error = state.wrap_errors[handle]
            if isinstance(error, GoneWindow):
                state.exists.discard(handle)
            raise error
        if handle not in state.exists:
            raise GoneWindow(f"stale {handle}")

        def title():
            count = state.title_calls.get(handle, 0) + 1
            state.title_calls[handle] = count
            failure = state.title_errors.get((handle, count))
            if failure is not None:
                if getattr(failure, "winerror", None) == 1400:
                    state.exists.discard(handle)
                raise failure
            return state.rows[handle]

        return SimpleNamespace(handle=handle, window_text=title)

    def eager_windows():
        state.desktop_calls += 1
        return [wrap(handle) for handle in list(state.rows)]

    monkeypatch.setattr(windows_module, "WINDOWS_BACKEND_AVAILABLE", True)
    monkeypatch.setattr(windows_module, "_INVALID_WINDOW_ERRORS", (GoneWindow,), raising=False)
    monkeypatch.setattr(windows_module, "HwndWrapper", wrap)
    monkeypatch.setattr(windows_module, "Desktop", lambda **_: SimpleNamespace(windows=eager_windows))
    monkeypatch.setattr(windows_module, "win32gui", SimpleNamespace(
        EnumWindows=enum_windows, IsWindow=lambda handle: handle in state.exists,
        IsWindowVisible=lambda handle: handle in state.exists,
        GetAncestor=lambda handle, _: handle,
    ))
    manager = WindowManager()
    monkeypatch.setattr(manager, "_desktop_window_role", lambda _: None)
    monkeypatch.setattr(manager, "_get_process_id", lambda _: 202)
    monkeypatch.setattr(manager, "_get_process_name", lambda _: "demo.exe")
    state.manager = manager
    return state


@pytest.mark.parametrize("operation", ["inventory", "matching"])
def test_disappearance_during_wrapper_construction_does_not_abort_other_windows(scene, operation):
    scene.wrap_errors[10] = GoneWindow("closed after snapshot")
    if operation == "inventory":
        assert [row["handle"] for row in scene.manager.list_visible_windows()] == [20]
    else:
        assert scene.manager._find_window("demo.exe", "Other").handle == 20
    assert scene.desktop_calls == 0
    assert scene.wrap_calls == [10, 20]


@pytest.mark.parametrize("read_number", [1, 2])
def test_disappearance_during_candidate_or_final_title_read_is_skipped(scene, read_number):
    error = OSError("invalid window handle")
    error.winerror = 1400
    scene.title_errors[(10, read_number)] = error
    assert [row["handle"] for row in scene.manager.list_visible_windows()] == [20]


@pytest.mark.parametrize("phase", ["wrapper", "candidate_title", "final_title"])
def test_non_disappearance_errors_are_not_reported_as_empty_inventory(scene, phase):
    error = RuntimeError("backend unavailable")
    if phase == "wrapper":
        scene.wrap_errors[10] = error
    else:
        scene.title_errors[(10, 1 if phase == "candidate_title" else 2)] = error
    with pytest.raises(RuntimeError, match="backend unavailable"):
        scene.manager.list_visible_windows()


def _coordinator(scene, monkeypatch):
    coordinator = Coordinator(scene.manager)
    coordinator._attached = False
    coordinator._history_confirmation_id = None
    coordinator._window_preparations = {}
    coordinator._launched_window_identities.clear()
    coordinator._LAUNCH_PRESENTATION_WAIT_SECONDS = 0
    monkeypatch.setattr(coordinator, "_revalidate_window_preparation", lambda intent: intent)

    def bind(handle):
        if handle not in scene.exists:
            raise GoneWindow(f"stale {handle}")
        return SimpleNamespace(handle=handle, process_id=202, title=scene.rows[handle])

    monkeypatch.setattr(scene.manager, "bind_window_by_handle", bind)
    monkeypatch.setattr(preparation.WindowsNativeIdentityReader, "read_identity",
                        lambda self, handle: {**deepcopy(IDENTITY), "target_window_handle": handle})
    monkeypatch.setattr(preparation, "window_handle_exists", lambda handle: handle in scene.exists)
    monkeypatch.setattr(preparation, "post_window_close", lambda handle: scene.exists.remove(handle))
    return coordinator


def _intent(coordinator, name):
    coordinator._window_preparations[name] = {
        "expires_at": time.monotonic() + 60, "mode": "launch", "source": "app_catalog",
        "executable_path": IDENTITY["executable_path"], "prefer_existing": False,
    }


def test_global_enumeration_failure_prevents_launch_dispatch(scene, monkeypatch):
    import app.core.application_launch as launch

    coordinator = _coordinator(scene, monkeypatch)
    _intent(coordinator, "first")
    scene.enum_error = OSError("EnumWindows failed")
    dispatched = []
    monkeypatch.setattr(launch, "launch_process", lambda *_: dispatched.append(True))
    with pytest.raises(OSError, match="EnumWindows failed"):
        coordinator._confirm_window_preparation_on_owner("first")
    assert dispatched == []
    assert "first" not in coordinator._window_preparations


def test_same_session_launch_observe_close_then_launch_survives_unrelated_stale_window(scene, monkeypatch):
    import app.core.application_launch as launch

    coordinator = _coordinator(scene, monkeypatch)
    dispatched = []

    def launch_once(_):
        handle = 101 + len(dispatched)
        dispatched.append(handle)
        scene.rows[handle] = f"Launched {handle}"
        scene.exists.add(handle)
        return SimpleNamespace(pid=202)

    monkeypatch.setattr(launch, "launch_process", launch_once)
    _intent(coordinator, "first")
    first = coordinator._confirm_window_preparation_on_owner("first")
    assert first["status"] == "launched_window_ready"
    handle = first["window"]["handle"]
    observations = [scene.manager.bind_window_by_handle(handle).handle for _ in range(2)]
    assert observations == [101, 101]
    closed = coordinator.close_launched_window(target_window_handle=handle, target_process_id=202)
    assert closed["status"] == "window_closed"
    assert not coordinator._launched_window_identities

    scene.rows[99] = "Unrelated transient window"
    scene.exists.add(99)
    scene.wrap_errors[99] = GoneWindow("closed during next launch inventory")
    _intent(coordinator, "second")
    second = coordinator._confirm_window_preparation_on_owner("second")
    assert second["status"] == "launched_window_ready"
    assert second["window"]["handle"] == 102
    assert second["launch_ownership"]["identity"]["target_window_handle"] == 102
    assert dispatched == [101, 102]
    assert coordinator._unverified_window_launch is None
