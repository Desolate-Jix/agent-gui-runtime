from __future__ import annotations

from app.core.window_manager import BoundWindow, WindowManager, WindowRect
import app.core.window_manager as window_manager_module


def test_window_title_match_normalization_removes_format_controls() -> None:
    manager = WindowManager()

    assert manager._normalize_match_text("Microsoft\u200b Edge") == "microsoft edge"


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
            return 0

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
            return None

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
            return 0

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
            return None

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
