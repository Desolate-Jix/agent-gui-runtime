"""编辑键契约及真实后端的事件顺序；不发送桌面输入。"""
from types import SimpleNamespace

import pytest

import app.core.input_controller as inputs
from app.instant_mcp import InstantCommand


CASES = [
    ("Enter", [0x0D]), ("Tab", [0x09]), ("Shift+Tab", [0x10, 0x09]),
    ("Escape", [0x1B]), ("Backspace", [0x08]), ("Delete", [0x2E]),
    ("Left", [0x25]), ("Right", [0x27]), ("Up", [0x26]), ("Down", [0x28]),
    ("Home", [0x24]), ("End", [0x23]), ("Ctrl+A", [0x11, 0x41]),
    ("Ctrl+Z", [0x11, 0x5A]), ("Ctrl+Y", [0x11, 0x59]),
    ("Shift+Left", [0x10, 0x25]), ("Shift+Right", [0x10, 0x27]),
    ("Shift+Up", [0x10, 0x26]), ("Shift+Down", [0x10, 0x28]),
    ("Shift+Home", [0x10, 0x24]), ("Shift+End", [0x10, 0x23]),
    ("Ctrl+Home", [0x11, 0x24]), ("Ctrl+End", [0x11, 0x23]),
]


def test_schema_and_backend_have_identical_key_sets():
    from typing import get_args
    from app.core.editing_keys import EditingKey, EDITING_KEY_CHORDS
    assert set(get_args(EditingKey)) == set(EDITING_KEY_CHORDS) == {name for name, _ in CASES}


@pytest.fixture
def keyboard(monkeypatch):
    controller = inputs.InputController()
    bound = SimpleNamespace(handle=7, process_id=9, rect=SimpleNamespace(left=0, top=0, right=320, bottom=200))
    monkeypatch.setattr(controller, "_ensure_windows_input", lambda: None)
    monkeypatch.setattr(controller, "_require_bound_window", lambda: bound)
    monkeypatch.setattr(inputs.win32gui, "GetForegroundWindow", lambda: 7)
    monkeypatch.setattr(inputs.window_manager, "validate_bound_point_visibility", lambda **kw: {"allowed": True})
    return controller


@pytest.mark.parametrize("name,keys", CASES)
def test_command_contract_and_backend_dispatch_the_same_editing_key(keyboard, monkeypatch, name, keys):
    command = InstantCommand.model_validate({"kind": "step", "operation": "press_key",
        "request": {"key": name, "x": 70, "y": 80}}).command()
    events = []
    monkeypatch.setattr(keyboard, "_send_key", lambda key, *, key_up: events.append((key, key_up)))
    result = keyboard.press_key(command["request"]["key"], x=70, y=80)
    assert result["pressed"] is True and result["key"] == name
    assert result["text_retyped"] is False
    assert events == [(key, False) for key in keys] + [(key, True) for key in reversed(keys)]


@pytest.mark.parametrize("name,keys", [(name, keys) for name, keys in CASES if len(keys) > 1])
def test_failed_editing_chord_releases_modifier_without_replay(keyboard, monkeypatch, name, keys):
    events = []
    def send(key, *, key_up):
        events.append((key, key_up))
        if key == keys[-1] and not key_up:
            raise RuntimeError("dispatch interrupted")
    monkeypatch.setattr(keyboard, "_send_key", send)
    with pytest.raises(RuntimeError, match="dispatch interrupted"):
        keyboard.press_key(name, x=70, y=80)
    assert events == [(key, False) for key in keys] + [(key, True) for key in reversed(keys)]


@pytest.mark.parametrize("key", [0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2E, 0x09, 0x41])
@pytest.mark.parametrize("key_up", [False, True])
def test_navigation_keys_encode_extended_flag(keyboard, monkeypatch, key, key_up):
    sent = []
    def send(count, pointer, size):
        value = pointer._obj.union.ki
        sent.append((value.wVk, value.dwFlags))
        return 1
    monkeypatch.setattr(inputs.ctypes.windll.user32, "SendInput", send)
    keyboard._send_key(key, key_up=key_up)
    expected = (2 if key_up else 0) | (1 if key in {0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2E} else 0)
    assert sent == [(key, expected)]
