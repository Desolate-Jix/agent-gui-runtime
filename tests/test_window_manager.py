from __future__ import annotations

import pytest

from app.core.window_manager import BoundWindow, WindowManager, WindowRect
import app.core.window_manager as window_manager_module


def test_window_title_match_normalization_removes_format_controls() -> None:
    manager = WindowManager()

    assert manager._normalize_match_text("Microsoft\u200b Edge") == "microsoft edge"


def test_validate_bound_point_visibility_accepts_descendant_window(monkeypatch) -> None:
    manager = WindowManager()
    bound = BoundWindow(
        handle=100,
        title="Browser",
        process_id=10,
        process_name="msedge.exe",
        rect=WindowRect(left=-8, top=-8, right=1192, bottom=792),
        is_active=True,
    )

    class DescendantWin32Gui:
        @staticmethod
        def WindowFromPoint(point):
            assert point == (307, 238)
            return 101

        @staticmethod
        def IsChild(parent, child):
            return parent == 100 and child == 101

        @staticmethod
        def GetAncestor(handle, flag):
            return 100

        @staticmethod
        def GetWindowText(handle):
            return "Browser renderer"

    monkeypatch.setattr(window_manager_module, "WINDOWS_BACKEND_AVAILABLE", True)
    monkeypatch.setattr(window_manager_module, "win32gui", DescendantWin32Gui)
    monkeypatch.setattr(manager, "_get_process_id", lambda handle: 10)
    monkeypatch.setattr(manager, "_get_process_name", lambda process_id: "msedge.exe")

    result = manager.validate_bound_point_visibility(bound=bound, x=315, y=246)

    assert result["allowed"] is True
    assert result["reason"] == "target_point_owned_by_bound_window"
    assert result["screen_point"] == {"x": 307, "y": 238}
    assert result["hit_window"]["handle"] == 101


def test_validate_bound_point_visibility_rejects_foreign_top_level_window(monkeypatch) -> None:
    manager = WindowManager()
    bound = BoundWindow(
        handle=100,
        title="Browser",
        process_id=10,
        process_name="msedge.exe",
        rect=WindowRect(left=-8, top=-8, right=1192, bottom=792),
        is_active=True,
    )

    class OccludedWin32Gui:
        @staticmethod
        def WindowFromPoint(point):
            assert point == (307, 238)
            return 900

        @staticmethod
        def IsChild(parent, child):
            return False

        @staticmethod
        def GetAncestor(handle, flag):
            return 900

        @staticmethod
        def GetWindowText(handle):
            return "QQ notification"

    monkeypatch.setattr(window_manager_module, "WINDOWS_BACKEND_AVAILABLE", True)
    monkeypatch.setattr(window_manager_module, "win32gui", OccludedWin32Gui)
    monkeypatch.setattr(manager, "_get_process_id", lambda handle: 99)
    monkeypatch.setattr(manager, "_get_process_name", lambda process_id: "QQ.exe")

    result = manager.validate_bound_point_visibility(bound=bound, x=315, y=246)

    assert result["allowed"] is False
    assert result["reason"] == "target_point_occluded"
    assert result["bound_window"]["handle"] == 100
    assert result["hit_window"] == {
        "handle": 900,
        "root_handle": 900,
        "root_owner_handle": 900,
        "title": "QQ notification",
        "process_id": 99,
        "process_name": "QQ.exe",
    }


def test_candidate_window_filter_accepts_visible_top_level_titled_window(monkeypatch) -> None:
    manager = WindowManager()

    class Wrapper:
        handle = 123

        def window_text(self):
            return "Demo window"

    class FakeWin32Gui:
        @staticmethod
        def IsWindowVisible(handle):
            return True

        @staticmethod
        def GetParent(handle):
            return 0

    monkeypatch.setattr(window_manager_module, "WINDOWS_BACKEND_AVAILABLE", True)
    monkeypatch.setattr(window_manager_module, "win32gui", FakeWin32Gui)

    assert manager._is_candidate_window(Wrapper()) is True


def test_candidate_window_filter_rejects_hidden_child_or_untitled(monkeypatch) -> None:
    manager = WindowManager()

    class Wrapper:
        handle = 123

        def __init__(self, title):
            self._title = title

        def window_text(self):
            return self._title

    class HiddenWin32Gui:
        @staticmethod
        def IsWindowVisible(handle):
            return False

        @staticmethod
        def GetParent(handle):
            return 0

    class ChildWin32Gui:
        @staticmethod
        def IsWindowVisible(handle):
            return True

        @staticmethod
        def GetParent(handle):
            return 99

    class VisibleWin32Gui:
        @staticmethod
        def IsWindowVisible(handle):
            return True

        @staticmethod
        def GetParent(handle):
            return 0

    monkeypatch.setattr(window_manager_module, "WINDOWS_BACKEND_AVAILABLE", True)
    monkeypatch.setattr(window_manager_module, "win32gui", HiddenWin32Gui)
    assert manager._is_candidate_window(Wrapper("Demo")) is False

    monkeypatch.setattr(window_manager_module, "win32gui", ChildWin32Gui)
    assert manager._is_candidate_window(Wrapper("Demo")) is False

    monkeypatch.setattr(window_manager_module, "win32gui", VisibleWin32Gui)
    assert manager._is_candidate_window(Wrapper("")) is False


def test_get_bound_window_clears_binding_when_handle_is_invalid(monkeypatch) -> None:
    manager = WindowManager()
    manager._bound_window = BoundWindow(
        handle=456,
        title="Old browser",
        process_id=10,
        process_name="msedge.exe",
        rect=WindowRect(left=0, top=0, right=800, bottom=600),
        is_active=False,
    )

    class InvalidWin32Gui:
        @staticmethod
        def IsWindow(handle):
            return False

        @staticmethod
        def IsWindowVisible(handle):
            return True

        @staticmethod
        def GetParent(handle):
            return 0

    monkeypatch.setattr(window_manager_module, "WINDOWS_BACKEND_AVAILABLE", True)
    monkeypatch.setattr(window_manager_module, "win32gui", InvalidWin32Gui)

    assert manager.get_bound_window() is None
    assert manager._bound_window is None


def test_get_bound_window_clears_binding_when_refresh_fails(monkeypatch) -> None:
    manager = WindowManager()
    manager._bound_window = BoundWindow(
        handle=789,
        title="Old browser",
        process_id=11,
        process_name="msedge.exe",
        rect=WindowRect(left=0, top=0, right=800, bottom=600),
        is_active=False,
    )

    class ValidWin32Gui:
        @staticmethod
        def IsWindow(handle):
            return True

        @staticmethod
        def IsWindowVisible(handle):
            return True

        @staticmethod
        def GetParent(handle):
            return 0

    def failing_wrapper(handle):
        raise RuntimeError("window handle disappeared")

    monkeypatch.setattr(window_manager_module, "WINDOWS_BACKEND_AVAILABLE", True)
    monkeypatch.setattr(window_manager_module, "win32gui", ValidWin32Gui)
    monkeypatch.setattr(window_manager_module, "HwndWrapper", failing_wrapper)

    assert manager.get_bound_window() is None
    assert manager._bound_window is None


def test_focus_bound_window_preserves_non_minimized_window_state(monkeypatch) -> None:
    manager = WindowManager()
    manager._bound_window = BoundWindow(
        handle=321,
        title="Maximized browser",
        process_id=12,
        process_name="msedge.exe",
        rect=WindowRect(left=-8, top=-8, right=2568, bottom=1408),
        is_active=False,
    )
    show_calls: list[tuple[int, int]] = []

    class FocusWin32Gui:
        active_handle = 0

        @staticmethod
        def IsWindow(handle):
            return True

        @staticmethod
        def IsWindowVisible(handle):
            return True

        @staticmethod
        def GetParent(handle):
            return 0

        @staticmethod
        def GetWindowRect(handle):
            return (-8, -8, 2568, 1408)

        @staticmethod
        def GetForegroundWindow():
            return FocusWin32Gui.active_handle

        @staticmethod
        def IsIconic(handle):
            return False

        @staticmethod
        def ShowWindow(handle, command):
            show_calls.append((handle, command))

        @staticmethod
        def BringWindowToTop(handle):
            return None

        @staticmethod
        def SetWindowPos(*_args):
            return None

        @staticmethod
        def SetForegroundWindow(handle):
            FocusWin32Gui.active_handle = handle

    class FocusWin32Process:
        @staticmethod
        def GetWindowThreadProcessId(handle):
            return (1, 12)

    class Wrapper:
        def __init__(self, handle):
            self.handle = handle

        def window_text(self):
            return "Maximized browser"

    monkeypatch.setattr(window_manager_module, "WINDOWS_BACKEND_AVAILABLE", True)
    monkeypatch.setattr(window_manager_module, "win32gui", FocusWin32Gui)
    monkeypatch.setattr(window_manager_module, "win32process", FocusWin32Process)
    monkeypatch.setattr(window_manager_module, "HwndWrapper", Wrapper)
    monkeypatch.setattr(window_manager_module.time, "sleep", lambda _seconds: None)

    focused = manager.focus_bound_window()

    assert focused.handle == 321
    assert show_calls == []


def test_focus_bound_window_restores_minimized_window(monkeypatch) -> None:
    manager = WindowManager()
    manager._bound_window = BoundWindow(
        handle=654,
        title="Minimized browser",
        process_id=13,
        process_name="msedge.exe",
        rect=WindowRect(left=0, top=0, right=800, bottom=600),
        is_active=False,
    )
    show_calls: list[tuple[int, int]] = []

    class MinimizedWin32Gui:
        active_handle = 0

        @staticmethod
        def IsWindow(handle):
            return True

        @staticmethod
        def IsWindowVisible(handle):
            return True

        @staticmethod
        def GetParent(handle):
            return 0

        @staticmethod
        def GetWindowRect(handle):
            return (0, 0, 800, 600)

        @staticmethod
        def GetForegroundWindow():
            return MinimizedWin32Gui.active_handle

        @staticmethod
        def IsIconic(handle):
            return True

        @staticmethod
        def ShowWindow(handle, command):
            show_calls.append((handle, command))

        @staticmethod
        def BringWindowToTop(handle):
            return None

        @staticmethod
        def SetWindowPos(*_args):
            return None

        @staticmethod
        def SetForegroundWindow(handle):
            MinimizedWin32Gui.active_handle = handle

    class FocusWin32Process:
        @staticmethod
        def GetWindowThreadProcessId(handle):
            return (1, 13)

    class Wrapper:
        def __init__(self, handle):
            self.handle = handle

        def window_text(self):
            return "Minimized browser"

    monkeypatch.setattr(window_manager_module, "WINDOWS_BACKEND_AVAILABLE", True)
    monkeypatch.setattr(window_manager_module, "win32gui", MinimizedWin32Gui)
    monkeypatch.setattr(window_manager_module, "win32process", FocusWin32Process)
    monkeypatch.setattr(window_manager_module, "HwndWrapper", Wrapper)
    monkeypatch.setattr(window_manager_module.time, "sleep", lambda _seconds: None)

    focused = manager.focus_bound_window()

    assert focused.handle == 654
    assert show_calls == [(654, window_manager_module.win32con.SW_RESTORE)]


def test_focus_bound_window_rejects_foreground_mismatch(monkeypatch) -> None:
    manager = WindowManager()
    bound = BoundWindow(
        handle=777,
        title="Target window",
        process_id=77,
        process_name="target.exe",
        rect=WindowRect(left=10, top=20, right=810, bottom=620),
        is_active=False,
    )

    class MismatchedForegroundWin32Gui:
        @staticmethod
        def IsIconic(handle):
            return False

        @staticmethod
        def BringWindowToTop(handle):
            return None

        @staticmethod
        def SetWindowPos(*_args):
            return None

        @staticmethod
        def SetForegroundWindow(handle):
            return None

        @staticmethod
        def GetForegroundWindow():
            return 999

    monkeypatch.setattr(window_manager_module, "WINDOWS_BACKEND_AVAILABLE", True)
    monkeypatch.setattr(window_manager_module, "win32gui", MismatchedForegroundWin32Gui)
    monkeypatch.setattr(window_manager_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(manager, "get_bound_window", lambda: bound)

    with pytest.raises(RuntimeError, match="foreground verification failed"):
        manager.focus_bound_window()


def test_activate_window_temporarily_attaches_input_threads(monkeypatch) -> None:
    manager = WindowManager()
    attach_calls = []

    class FocusWin32Gui:
        @staticmethod
        def IsIconic(handle):
            return False

        @staticmethod
        def GetForegroundWindow():
            return 999

        @staticmethod
        def BringWindowToTop(handle):
            return None

        @staticmethod
        def SetWindowPos(*_args):
            return None

        @staticmethod
        def SetForegroundWindow(handle):
            return None

    class FocusWin32Process:
        @staticmethod
        def GetWindowThreadProcessId(handle):
            return (21 if handle == 999 else 22, 1)

        @staticmethod
        def AttachThreadInput(source_thread, target_thread, attach):
            attach_calls.append((source_thread, target_thread, attach))

    class FocusWin32Api:
        @staticmethod
        def GetCurrentThreadId():
            return 20

    monkeypatch.setattr(window_manager_module, "WINDOWS_BACKEND_AVAILABLE", True)
    monkeypatch.setattr(window_manager_module, "win32gui", FocusWin32Gui)
    monkeypatch.setattr(window_manager_module, "win32process", FocusWin32Process)
    monkeypatch.setattr(window_manager_module, "win32api", FocusWin32Api, raising=False)

    manager._activate_window(777)

    assert attach_calls == [
        (20, 21, True),
        (20, 22, True),
        (20, 22, False),
        (20, 21, False),
    ]


def test_activate_window_continues_after_foreground_thread_attach_failure(monkeypatch) -> None:
    manager = WindowManager()
    attach_calls = []

    class FocusWin32Gui:
        @staticmethod
        def IsIconic(handle):
            return False

        @staticmethod
        def GetForegroundWindow():
            return 999

        @staticmethod
        def BringWindowToTop(handle):
            return None

        @staticmethod
        def SetWindowPos(*_args):
            return None

        @staticmethod
        def SetForegroundWindow(handle):
            return None

    class FocusWin32Process:
        @staticmethod
        def GetWindowThreadProcessId(handle):
            return (21 if handle == 999 else 22, 1)

        @staticmethod
        def AttachThreadInput(source_thread, target_thread, attach):
            attach_calls.append((source_thread, target_thread, attach))
            if target_thread == 21 and attach:
                raise OSError("access denied")

    class FocusWin32Api:
        @staticmethod
        def GetCurrentThreadId():
            return 20

    monkeypatch.setattr(window_manager_module, "WINDOWS_BACKEND_AVAILABLE", True)
    monkeypatch.setattr(window_manager_module, "win32gui", FocusWin32Gui)
    monkeypatch.setattr(window_manager_module, "win32process", FocusWin32Process)
    monkeypatch.setattr(window_manager_module, "win32api", FocusWin32Api, raising=False)

    manager._activate_window(777)

    assert attach_calls == [
        (20, 21, True),
        (20, 22, True),
        (20, 22, False),
    ]


def test_activate_window_retries_foreground_with_alt_unlock_after_access_denied(monkeypatch) -> None:
    manager = WindowManager()
    foreground_calls = []
    key_calls = []

    class FocusWin32Gui:
        @staticmethod
        def IsIconic(handle):
            return False

        @staticmethod
        def GetForegroundWindow():
            return 999

        @staticmethod
        def BringWindowToTop(handle):
            return None

        @staticmethod
        def SetWindowPos(*_args):
            return None

        @staticmethod
        def SetForegroundWindow(handle):
            foreground_calls.append(handle)
            if len(foreground_calls) == 1:
                raise OSError("access denied")

    class FocusWin32Process:
        @staticmethod
        def GetWindowThreadProcessId(handle):
            return (21 if handle == 999 else 22, 1)

        @staticmethod
        def AttachThreadInput(_source_thread, _target_thread, _attach):
            raise OSError("access denied")

    class FocusWin32Api:
        @staticmethod
        def GetCurrentThreadId():
            return 20

        @staticmethod
        def keybd_event(key, scan, flags, extra):
            key_calls.append((key, scan, flags, extra))

    monkeypatch.setattr(window_manager_module, "WINDOWS_BACKEND_AVAILABLE", True)
    monkeypatch.setattr(window_manager_module, "win32gui", FocusWin32Gui)
    monkeypatch.setattr(window_manager_module, "win32process", FocusWin32Process)
    monkeypatch.setattr(window_manager_module, "win32api", FocusWin32Api, raising=False)

    manager._activate_window(777)

    assert foreground_calls == [777, 777]
    assert key_calls == [
        (window_manager_module.win32con.VK_MENU, 0, 0, 0),
        (
            window_manager_module.win32con.VK_MENU,
            0,
            window_manager_module.win32con.KEYEVENTF_KEYUP,
            0,
        ),
    ]


def test_activate_window_cycles_past_shell_notification_after_foreground_retry_fails(monkeypatch) -> None:
    manager = WindowManager()
    foreground = {"handle": 999}
    key_calls = []

    class FocusWin32Gui:
        @staticmethod
        def IsIconic(handle):
            return False

        @staticmethod
        def GetForegroundWindow():
            return foreground["handle"]

        @staticmethod
        def BringWindowToTop(handle):
            return None

        @staticmethod
        def SetWindowPos(*_args):
            return None

        @staticmethod
        def SetForegroundWindow(handle):
            raise OSError("access denied")

    class FocusWin32Process:
        @staticmethod
        def GetWindowThreadProcessId(handle):
            return (21 if handle == 999 else 22, 1)

        @staticmethod
        def AttachThreadInput(_source_thread, _target_thread, _attach):
            raise OSError("access denied")

    class FocusWin32Api:
        @staticmethod
        def GetCurrentThreadId():
            return 20

        @staticmethod
        def keybd_event(key, scan, flags, extra):
            key_calls.append((key, scan, flags, extra))
            if key == window_manager_module.win32con.VK_TAB and flags == 0:
                foreground["handle"] = 777

    monkeypatch.setattr(window_manager_module, "WINDOWS_BACKEND_AVAILABLE", True)
    monkeypatch.setattr(window_manager_module, "win32gui", FocusWin32Gui)
    monkeypatch.setattr(window_manager_module, "win32process", FocusWin32Process)
    monkeypatch.setattr(window_manager_module, "win32api", FocusWin32Api, raising=False)
    monkeypatch.setattr(manager, "_get_process_id", lambda handle: 42 if handle == 999 else 43)
    monkeypatch.setattr(manager, "_get_process_name", lambda process_id: "ShellExperienceHost.exe" if process_id == 42 else "msedge.exe")
    monkeypatch.setattr(window_manager_module.time, "sleep", lambda _seconds: None)

    manager._activate_window(777)

    assert foreground["handle"] == 777
    assert key_calls[-4:] == [
        (window_manager_module.win32con.VK_MENU, 0, 0, 0),
        (window_manager_module.win32con.VK_TAB, 0, 0, 0),
        (
            window_manager_module.win32con.VK_TAB,
            0,
            window_manager_module.win32con.KEYEVENTF_KEYUP,
            0,
        ),
        (
            window_manager_module.win32con.VK_MENU,
            0,
            window_manager_module.win32con.KEYEVENTF_KEYUP,
            0,
        ),
    ]
