from __future__ import annotations

import pytest

from app.core import input_controller as input_controller_module
from app.core import runtime_input_authority


class _RecordingUser32:
    def __init__(self) -> None:
        self.send_input_calls = 0

    def SendInput(self, *_args: object) -> int:
        self.send_input_calls += 1
        return 1


class _RecordingWin32Gui:
    def __init__(self) -> None:
        self.foreground_calls = 0

    def SetForegroundWindow(self, _handle: int) -> None:
        self.foreground_calls += 1


class _RecordingClipboard:
    def __init__(self) -> None:
        self.open_calls = 0
        self.empty_calls = 0
        self.text_calls = 0
        self.data_calls = 0

    def OpenClipboard(self, _owner: object) -> None:
        self.open_calls += 1

    def EmptyClipboard(self) -> None:
        self.empty_calls += 1

    def SetClipboardText(self, *_args: object) -> None:
        self.text_calls += 1

    def SetClipboardData(self, *_args: object) -> None:
        self.data_calls += 1

    def CloseClipboard(self) -> None:
        return None


def test_raw_input_controller_rejects_calls_outside_runtime_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = input_controller_module.InputController()
    monkeypatch.setattr(input_controller_module, "WINDOWS_INPUT_AVAILABLE", True)

    with pytest.raises(PermissionError, match="LiveController authority"):
        controller._ensure_windows_input()


def test_runtime_backend_scope_is_process_private_and_short_lived(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = input_controller_module.InputController()
    monkeypatch.setattr(input_controller_module, "WINDOWS_INPUT_AVAILABLE", True)

    with runtime_input_authority._runtime_backend_input_scope():
        controller._ensure_windows_input()

    with pytest.raises(PermissionError, match="LiveController authority"):
        controller._ensure_windows_input()


def test_private_send_input_sinks_reject_before_raw_api_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = input_controller_module.InputController()
    user32 = _RecordingUser32()
    monkeypatch.setattr(input_controller_module, "WINDOWS_INPUT_AVAILABLE", True)
    monkeypatch.setattr(
        input_controller_module.ctypes,
        "windll",
        type("_Windll", (), {"user32": user32})(),
    )

    with pytest.raises(PermissionError, match="LiveController authority"):
        controller._send_mouse_input(dx=0, dy=0, flags=0)
    with pytest.raises(PermissionError, match="LiveController authority"):
        controller._send_key(0x41, key_up=False)

    assert user32.send_input_calls == 0


def test_private_foreground_sink_rejects_before_raw_api_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = input_controller_module.InputController()
    win32gui = _RecordingWin32Gui()
    monkeypatch.setattr(input_controller_module, "WINDOWS_INPUT_AVAILABLE", True)
    monkeypatch.setattr(input_controller_module, "win32gui", win32gui)

    with pytest.raises(PermissionError, match="LiveController authority"):
        controller._focus_window(123)

    assert win32gui.foreground_calls == 0


def test_private_clipboard_write_sinks_reject_before_clipboard_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controller = input_controller_module.InputController()
    clipboard = _RecordingClipboard()
    monkeypatch.setattr(input_controller_module, "WINDOWS_INPUT_AVAILABLE", True)
    monkeypatch.setattr(input_controller_module, "win32clipboard", clipboard)

    with pytest.raises(PermissionError, match="LiveController authority"):
        controller._set_clipboard_text("blocked")
    with pytest.raises(PermissionError, match="LiveController authority"):
        controller._set_clipboard_image_dib(b"blocked")

    assert clipboard.open_calls == 0
    assert clipboard.empty_calls == 0
    assert clipboard.text_calls == 0
    assert clipboard.data_calls == 0
