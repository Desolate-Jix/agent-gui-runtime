from types import SimpleNamespace

import pytest

from app.agent.desktop_backend import ExistingWindowsBackendAdapter
from app.core import clipboard_transaction as clipboard_module
from app.core import input_controller as input_module
from app.core.input_controller import InputController, VK_A, VK_CONTROL, VK_RETURN, VK_V
from app.core.runtime_input_authority import runtime_backend_input_is_active
from test_text_dispatch_authority import command_and_authority, prepared


def unicode_bytes(text):
    return text.encode("utf-16-le") + b"\x00\x00"


def logical_text(raw):
    for index in range(0, len(raw) - 1, 2):
        if raw[index:index + 2] == b"\x00\x00":
            return raw[:index].decode("utf-16-le")
    raise AssertionError("clipboard text has no UTF-16 terminator")


def compose(monkeypatch, *, fault=None, formats=None):
    from test_clipboard_transaction import FakeWin32Api, build_windows_backend

    original = formats if formats is not None else {
        clipboard_module.CF_UNICODETEXT: unicode_bytes("original"),
        clipboard_module.CF_DIB: b"original-dib-bytes",
        clipboard_module.CF_HDROP: b"original-drop-bytes",
    }
    api = FakeWin32Api(original)
    clipboard_backend = build_windows_backend(api)
    controller = InputController()
    bound = SimpleNamespace(
        handle=4242, process_id=42, title="isolated-text-target",
        rect=SimpleNamespace(left=100, top=200, right=420, bottom=400),
    )
    state = SimpleNamespace(cursor=(0, 0), foreground=4242, keys=set(), pasted=[], mouse=[], field="before")
    manager = SimpleNamespace(get_bound_window=lambda: bound,
                              validate_bound_point_visibility=lambda **kwargs: {"allowed": True})

    def focus(handle):
        state.foreground = handle

    def move(x, y):
        assert runtime_backend_input_is_active()
        state.cursor = (x, y)

    def mouse(flags):
        assert runtime_backend_input_is_active()
        state.mouse.append(flags)

    def key(value, *, key_up):
        assert runtime_backend_input_is_active()
        assert value != VK_RETURN, "formal text must never send Enter"
        if key_up:
            state.keys.discard(value)
            return
        state.keys.add(value)
        if value == VK_A:
            assert VK_CONTROL in state.keys
            state.field = ""
            if fault == "target-drift":
                bound.rect.right += 1
        if value == VK_V:
            assert VK_CONTROL in state.keys
            value_text = logical_text(api.current_bytes(clipboard_module.CF_UNICODETEXT))
            state.pasted.append(value_text)
            state.field += value_text
            if fault == "concurrent-copy":
                api.external_copy("newer-user-copy")
            if fault == "partial-send":
                raise OSError("keyboard receipt lost after paste")

    # 保留真实事务、输入流程、点击几何和一次性 authority，仅替换系统边界。
    monkeypatch.setattr(clipboard_module, "WindowsClipboardBackend", lambda: clipboard_backend)
    monkeypatch.setattr(input_module, "window_manager", manager)
    monkeypatch.setattr(input_module, "WINDOWS_INPUT_AVAILABLE", True)
    monkeypatch.setattr(input_module, "win32gui", SimpleNamespace(
        SetForegroundWindow=focus, GetForegroundWindow=lambda: state.foreground))
    monkeypatch.setattr(input_module, "win32api", SimpleNamespace(GetCursorPos=lambda: state.cursor))
    monkeypatch.setattr(controller, "_send_move", move)
    monkeypatch.setattr(controller, "_send_mouse_flags", mouse)
    monkeypatch.setattr(controller, "_send_key", key)
    monkeypatch.setattr(input_module.time, "sleep", lambda seconds: None)
    adapter = ExistingWindowsBackendAdapter(input_controller=controller, window_manager=manager)
    return adapter, api, state, original


def assert_restored(api, original):
    assert set(api.formats) == set(original)
    for format_id, expected in original.items():
        # 内存分配可以向上取整；原字节前缀必须完整保留。
        assert api.current_bytes(format_id).startswith(expected)


@pytest.mark.parametrize("text", ["", "\u4f60\u597d", "\u7b2c\u4e00\u884c\r\nnext\n\tend"])
def test_fixed_text_uses_real_transaction_and_input_path_once(monkeypatch, text):
    adapter, api, state, original = compose(monkeypatch)
    command, authority = command_and_authority(prepared(content={"kind": "literal", "text": text}))

    receipt = adapter.dispatch(command, authority=authority)

    assert receipt.status == "dispatched"
    assert state.pasted == [text]
    assert state.field == text
    assert state.cursor == (170, 280)
    assert state.mouse == [input_module.MOUSEEVENTF_LEFTDOWN, input_module.MOUSEEVENTF_LEFTUP]
    assert state.keys == set()
    assert_restored(api, original)
    with pytest.raises(PermissionError, match="already consumed"):
        adapter.dispatch(command, authority=authority)
    assert state.pasted == [text]


def test_variable_dispatch_consumes_frozen_value_not_later_mapping(monkeypatch):
    adapter, api, state, original = compose(monkeypatch)
    variables = {"query_text": "\u672c\u6b21\u5185\u5bb9"}
    parameters = prepared(content={"kind": "variable", "name": "query_text"}, variables=variables)
    command, authority = command_and_authority(parameters)
    variables["query_text"] = "mutated-after-confirmation"

    assert adapter.dispatch(command, authority=authority).status == "dispatched"
    assert state.pasted == ["\u672c\u6b21\u5185\u5bb9"]
    assert_restored(api, original)


@pytest.mark.parametrize("fault", ["target-drift", "concurrent-copy", "partial-send"])
def test_input_failure_cleans_up_without_reusing_consumed_authority(monkeypatch, fault):
    adapter, api, state, original = compose(monkeypatch, fault=fault)
    command, authority = command_and_authority(prepared())

    receipt = adapter.dispatch(command, authority=authority)

    assert receipt.status == "indeterminate"
    assert len(state.pasted) == (0 if fault == "target-drift" else 1)
    assert state.keys == set()
    if fault == "concurrent-copy":
        assert logical_text(api.current_bytes(clipboard_module.CF_UNICODETEXT)) == "newer-user-copy"
    else:
        assert_restored(api, original)
    with pytest.raises(PermissionError, match="already consumed"):
        adapter.dispatch(command, authority=authority)
    assert len(state.pasted) == (0 if fault == "target-drift" else 1)


def test_uncopyable_clipboard_stops_before_target_click_or_keyboard(monkeypatch):
    adapter, api, state, original = compose(monkeypatch, formats={14: b"unsupported-handle-format"})
    command, authority = command_and_authority(prepared())

    assert adapter.dispatch(command, authority=authority).status == "indeterminate"
    assert state.mouse == []
    assert state.pasted == []
    assert_restored(api, original)
