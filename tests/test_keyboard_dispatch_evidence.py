"""只读键盘诊断不能改变原派发、释放、异常或授权。"""
import importlib
import json
from types import SimpleNamespace

import pytest

from app.core import input_controller as inputs


class FakeUser32:
    def __init__(self):
        self.calls = []
        self.down = set()
        self.foreground = 701
        self.active, self.focus = 702, 703
        self.gui_available = True
        self.bad_modifier = None
        self.failure = None

    def GetForegroundWindow(self):
        return self.foreground

    def GetWindowThreadProcessId(self, handle, process):
        assert handle == self.foreground
        return 77

    def GetGUIThreadInfo(self, thread, info):
        assert thread == 77
        if not self.gui_available:
            return 0
        info._obj.hwndActive, info._obj.hwndFocus = self.active, self.focus
        info._obj.flags, info._obj.hwndCaret = 3, 706
        return 1

    def GetAsyncKeyState(self, key):
        if key == self.bad_modifier:
            raise OSError("private error detail must not escape")
        return 0x8000 if key in self.down else 1

    def SendInput(self, count, data, size):
        assert count == 1 and size == inputs.ctypes.sizeof(inputs.INPUT)
        key, flags = int(data._obj.union.ki.wVk), int(data._obj.union.ki.dwFlags)
        self.calls.append((key, flags))
        if not flags & 2:
            self.down.add(key)
        else:
            self.down.discard(key)
        self.focus += 1
        failure, self.failure = self.failure, None
        if isinstance(failure, BaseException):
            raise failure
        return 1 if failure is None else failure


class EventLogger:
    def __init__(self):
        self.events = []
        self.fail = False

    def bind(self, **extra):
        if self.fail:
            raise OSError("log sink unavailable")
        self.events.append(extra["keyboard_dispatch_diagnostics"])
        return self

    def info(self, message, *args):
        pass


@pytest.fixture
def scene(monkeypatch):
    native, log = FakeUser32(), EventLogger()
    controller = inputs.InputController()
    bound = SimpleNamespace(handle=701, process_id=9,
        rect=SimpleNamespace(left=0, top=0, right=900, bottom=700))
    monkeypatch.setattr(inputs.ctypes, "windll", SimpleNamespace(user32=native), raising=False)
    monkeypatch.setattr(controller, "_ensure_windows_input", lambda: None)
    monkeypatch.setattr(controller, "_require_bound_window", lambda: bound)
    monkeypatch.setattr(controller, "_verify_text_target", lambda *args, **kwargs: None)
    def forbidden(*args, **kwargs):
        pytest.fail("diagnostics must not activate, click or wait")
    monkeypatch.setattr(controller, "_focus_window", forbidden)
    monkeypatch.setattr(controller, "click_point", forbidden)
    monkeypatch.setattr(inputs.time, "sleep", forbidden)
    try:
        diagnostics = importlib.import_module("app.core.keyboard_dispatch_diagnostics")
    except ModuleNotFoundError:
        diagnostics = None
    if diagnostics is not None:
        monkeypatch.setattr(diagnostics, "_user32", lambda: native)
        monkeypatch.setattr(diagnostics, "logger", log)
    return controller, native, log, diagnostics


def test_enter_receipt_records_actual_native_events_and_readonly_window_snapshots(scene):
    controller, native, log, _ = scene
    result = controller.press_key("Enter", x=300, y=60)
    assert native.calls == [(13, 0), (13, 2)]
    assert result["pressed"] is True and result["text_retyped"] is False
    evidence = result["keyboard_dispatch_diagnostics"]
    assert evidence["schema"] == "keyboard_dispatch_diagnostics.v1"
    assert evidence["artifact_is_authorization"] is False
    assert evidence["diagnostic_elapsed_ms"] >= 0
    events = evidence["events"]
    assert [(e["vk"], e["flags"], e["sent"]) for e in events] == [(13, 0, 1), (13, 2, 1)]
    assert events[0]["before"]["foreground_hwnd"] == 701
    assert events[0]["before"]["gui_thread"] == {
        "active_hwnd": 702, "focus_hwnd": 703, "caret_hwnd": 706, "flags": 3}
    assert events[0]["after"]["gui_thread"]["focus_hwnd"] == 704
    assert events[1]["before"]["gui_thread"]["focus_hwnd"] == 704
    assert events[1]["after"]["gui_thread"]["focus_hwnd"] == 705
    assert events[0]["before"]["modifiers"] == {"ctrl": False, "alt": False, "shift": False, "win": False}
    assert len(log.events) == 2


def test_selection_and_paste_log_modifier_transitions_without_extra_input(scene):
    controller, native, log, _ = scene
    native.down.update((0x12, 0x10, 0x5C))
    controller._press_chord([0x11, 0x41])
    controller._press_chord([0x11, 0x56])
    assert native.calls == [(17, 0), (65, 0), (65, 2), (17, 2),
        (17, 0), (86, 0), (86, 2), (17, 2)]
    assert len(log.events) == 8
    assert log.events[1]["before"]["modifiers"] == {"ctrl": True, "alt": True, "shift": True, "win": True}
    assert log.events[3]["after"]["modifiers"]["ctrl"] is False
    assert log.events[5]["before"]["modifiers"]["ctrl"] is True
    assert log.events[7]["after"]["modifiers"]["ctrl"] is False


def test_partial_read_failure_preserves_available_facts_and_success(scene):
    controller, native, _, _ = scene
    native.gui_available, native.bad_modifier = False, 0x12
    result = controller.press_key("Enter", x=300, y=60)
    before = result["keyboard_dispatch_diagnostics"]["events"][0]["before"]
    assert result["pressed"] is True
    assert before["status"] == "partial"
    assert before["foreground_hwnd"] == 701
    assert before["gui_thread"] == {"active_hwnd": None, "focus_hwnd": None, "caret_hwnd": None, "flags": None}
    assert before["modifiers"]["alt"] is None
    assert before["modifiers"]["ctrl"] is False
    assert set(before["unavailable"]) == {"gui_thread", "modifiers.alt"}
    assert "private error detail" not in json.dumps(before)


@pytest.mark.parametrize("failure", [0, RuntimeError("native input failure")])
def test_unavailable_diagnostics_never_masks_sendinput_failure_or_key_release(scene, monkeypatch, failure):
    controller, native, log, diagnostics = scene
    assert diagnostics is not None, "keyboard dispatch diagnostics are missing"
    def unavailable():
        raise OSError("native diagnostic API unavailable")
    monkeypatch.setattr(diagnostics, "_user32", unavailable)
    native.failure = failure
    with pytest.raises(RuntimeError) as caught:
        controller.press_key("Enter", x=300, y=60)
    if isinstance(failure, RuntimeError):
        assert caught.value is failure
    else:
        assert str(caught.value) == "SendInput keyboard failed, sent=0, key=13, key_up=False"
    assert native.calls == [(13, 0), (13, 2)]
    assert log.events[0]["before"]["status"] == "unavailable"
    assert log.events[0]["after"]["status"] == "unavailable"
    assert log.events[0]["sent"] == (None if isinstance(failure, RuntimeError) else 0)


def test_log_sink_failure_cannot_change_successful_dispatch(scene):
    controller, native, log, _ = scene
    log.fail = True
    result = controller.press_key("Enter", x=300, y=60)
    assert result["pressed"] is True
    assert len(result["keyboard_dispatch_diagnostics"]["events"]) == 2
    assert native.calls == [(13, 0), (13, 2)]
