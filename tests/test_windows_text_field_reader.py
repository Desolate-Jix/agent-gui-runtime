from types import SimpleNamespace
import traceback

import pytest
from pywinauto.uia_defines import NoPatternInterfaceError
from comtypes.gen.UIAutomationClient import UIA_IsReadOnlyAttributeId

from app.agent.windows_text_field_reader import UIA_IS_READONLY_ATTRIBUTE_ID, TextFieldReadError, WindowsTextFieldReader, _selection


class _Rect:
    left, top, right, bottom = 100, 200, 300, 240


class _Range:
    def __init__(self, text, endpoint=None, start=0, end=0, readonly=False): self.text, self.endpoint, self.start, self.end, self.readonly = text, endpoint, start, end, readonly
    def Clone(self): return _Range(self.text)
    def MoveEndpointByRange(self, endpoint, selected, selected_endpoint): self.endpoint = selected.start if selected_endpoint == 0 else selected.end
    def GetText(self, _): return self.text if self.endpoint is None else self.text[:self.endpoint]
    def GetAttributeValue(self, attribute):
        assert attribute == UIA_IS_READONLY_ATTRIBUTE_ID
        return self.readonly


class _Text:
    def __init__(self, value, start=0, end=0, readonly=False): self.value, self.start, self.end = value, start, end; self.DocumentRange = _Range(value, readonly=readonly)
    def GetSelection(self): return _RangeArray([_Range(self.value, start=self.start, end=self.end)])


class _RangeArray:
    def __init__(self, ranges): self._ranges = ranges; self.Length = len(ranges)
    def GetElement(self, index): return self._ranges[index]


class _Value:
    def __init__(self, value, readonly=False): self.CurrentValue = value; self.CurrentIsReadOnly = readonly


class _Wrapper:
    def __init__(self, value="hello", *, control_type="Edit", handle=7, pid=8, text=True,
                 value_pattern=None, value_readonly=False, text_readonly=False,
                 password=False, visible=True, enabled=True):
        element = SimpleNamespace(CurrentIsPassword=password, CurrentProcessId=pid)
        self.element_info = SimpleNamespace(control_type=control_type, runtime_id=(1, 2), rectangle=_Rect(), handle=handle, process_id=pid, element=element)
        has_value = control_type == "Edit" if value_pattern is None else value_pattern
        self._value = _Value(value, value_readonly) if has_value else None
        self._text = _Text(value, 1, 4, text_readonly) if text else None
        self._visible, self._enabled = visible, enabled
    def is_visible(self): return self._visible
    def is_enabled(self): return self._enabled
    def parent(self): return None
    def top_level_parent(self): return self
    @property
    def iface_value(self):
        if self._value is None:
            raise NoPatternInterfaceError()
        return self._value
    @property
    def iface_text(self):
        if self._text is None:
            raise NoPatternInterfaceError()
        return self._text


def _raise_no_pattern():
    raise NoPatternInterfaceError()


class _Desktop:
    def __init__(self, wrapper): self.wrapper = wrapper; self.calls = []
    def from_point(self, x, y): self.calls.append((x, y)); return self.wrapper


class _Native:
    def read_identity(self, handle):
        return {"contract_version": "windows_native_identity_observation_v1", "provider": "windows_native_identity", "status": "observed", "target_window_handle": handle, "process_id": 8, "process_create_time": 2.0, "executable_path": "C:\\fake.exe"}


def _reader(wrapper):
    bound = SimpleNamespace(handle=7, process_id=8, rect=SimpleNamespace(left=100, top=200, right=500, bottom=500))
    desktop = _Desktop(wrapper)
    return WindowsTextFieldReader(window_manager=SimpleNamespace(get_bound_window=lambda: bound), native_identity_reader=_Native(), desktop_factory=lambda **_: desktop, clock_ns=lambda: 9, read_id_factory=lambda: "read"), desktop


def _read(reader):
    return reader.read_field(target_field_id="field", capture_id="capture", target_window_handle=7, target_process_id=8, process_create_time=2.0, window_rect=(100, 200, 400, 300), target_bbox=(0, 0, 200, 40), click_point=(10, 10))


def test_value_and_text_agree_and_selection_is_unicode_safe():
    reader, desktop = _reader(_Wrapper("a😀bc"))
    got = _read(reader)
    assert (got.value, got.source, got.selection, got.read_id) == ("a😀bc", "uia_value", (1, 4), "read")
    assert desktop.calls == [(110, 210), (110, 210)]


def test_readonly_constant_matches_generated_uia_contract():
    assert UIA_IS_READONLY_ATTRIBUTE_ID == UIA_IsReadOnlyAttributeId == 40015


def test_text_only_document_preserves_crlf_and_uses_text_source():
    reader, _ = _reader(_Wrapper("甲\r\n乙", control_type="Document"))
    got = _read(reader)
    assert got.value == "甲\r\n乙" and got.source == "uia_text"


def test_editable_combobox_requires_matching_value_and_text_and_preserves_binding():
    reader, desktop = _reader(_Wrapper("OpenStreetMap", control_type="ComboBox", value_pattern=True))

    got = _read(reader)

    assert (got.value, got.source, got.selection) == ("OpenStreetMap", "uia_value", (1, 4))
    assert got.identity.runtime_id == (1, 2)
    assert got.identity.control_bbox == (0, 0, 200, 40)
    assert desktop.calls == [(110, 210), (110, 210)]


@pytest.mark.parametrize("value_pattern,text", [(False, True), (True, False), (False, False)])
def test_combobox_without_both_value_and_text_patterns_is_rejected(value_pattern, text):
    reader, _ = _reader(_Wrapper(
        control_type="ComboBox", value_pattern=value_pattern, text=text,
    ))

    with pytest.raises(TextFieldReadError, match="target_not_writable"):
        _read(reader)


def test_combobox_value_and_text_must_agree():
    wrapper = _Wrapper("value", control_type="ComboBox", value_pattern=True)
    wrapper._text = _Text("different")
    reader, _ = _reader(wrapper)

    with pytest.raises(TextFieldReadError, match="value_patterns_disagree"):
        _read(reader)


@pytest.mark.parametrize("attribute", ["value_readonly", "text_readonly", "password", "visible", "enabled"])
def test_combobox_requires_explicitly_writable_visible_enabled_control(attribute):
    options = {"control_type": "ComboBox", "value_pattern": True}
    options[attribute] = False if attribute in {"visible", "enabled"} else True
    reader, _ = _reader(_Wrapper(**options))

    with pytest.raises(TextFieldReadError, match="target_not_writable"):
        _read(reader)


@pytest.mark.parametrize("attribute", ["password", "value_readonly", "text_readonly"])
def test_combobox_rejects_unknown_writable_flags(attribute):
    wrapper = _Wrapper(control_type="ComboBox", value_pattern=True)
    if attribute == "password":
        del wrapper.element_info.element.CurrentIsPassword
    elif attribute == "value_readonly":
        wrapper._value.CurrentIsReadOnly = None
    else:
        wrapper._text.DocumentRange.readonly = None
    reader, _ = _reader(wrapper)

    with pytest.raises(TextFieldReadError, match="target_not_writable"):
        _read(reader)


def test_combobox_second_read_runtime_identity_drift_is_rejected():
    first = _Wrapper("same", control_type="ComboBox", value_pattern=True)
    second = _Wrapper("same", control_type="ComboBox", value_pattern=True)
    second.element_info.runtime_id = (9,)
    calls = {"count": 0}

    def from_point(*_):
        calls["count"] += 1
        return first if calls["count"] == 1 else second

    bound = SimpleNamespace(
        handle=7, process_id=8,
        rect=SimpleNamespace(left=100, top=200, right=500, bottom=500),
    )
    reader = WindowsTextFieldReader(
        window_manager=SimpleNamespace(get_bound_window=lambda: bound),
        native_identity_reader=_Native(),
        desktop_factory=lambda **_: SimpleNamespace(from_point=from_point),
        clock_ns=lambda: 9,
        read_id_factory=lambda: "read",
    )

    with pytest.raises(TextFieldReadError, match="changed"):
        _read(reader)


def test_hit_text_child_resolves_its_edit_parent_without_walking_to_desktop():
    field = _Wrapper("child value")
    child = SimpleNamespace(
        element_info=SimpleNamespace(control_type="Text", handle=0),
        top_level_parent=lambda: field,
        parent=lambda: field,
    )
    reader, _ = _reader(child)
    assert _read(reader).value == "child value"


def test_broken_com_does_not_fall_back_and_never_leaks_raw_value():
    wrapper = _Wrapper("secret")
    class Broken:
        CurrentIsReadOnly = False
        @property
        def CurrentValue(self): raise RuntimeError("secret")
    wrapper._value = Broken()
    reader, _ = _reader(wrapper)
    with pytest.raises(TextFieldReadError) as error:
        _read(reader)
    assert error.value.reason_code == "text_field_value_unavailable"
    assert "secret" not in repr(error.value) and "secret" not in str(error.value)


def test_wrong_window_or_process_is_rejected_before_value_read():
    wrapper = _Wrapper(handle=9)
    reader, _ = _reader(wrapper)
    with pytest.raises(TextFieldReadError, match="window_or_process_changed"):
        _read(reader)


def test_public_boundary_redacts_secret_from_provider_getter_traceback():
    wrapper = _Wrapper()
    class Info:
        control_type = "Edit"
        rectangle = _Rect()
        handle = 7
        process_id = 8
        element = SimpleNamespace(CurrentIsPassword=False, CurrentProcessId=8)
        @property
        def runtime_id(self):
            raise RuntimeError("secret-local-value")
    wrapper.element_info = Info()
    reader, _ = _reader(wrapper)
    with pytest.raises(TextFieldReadError) as error:
        _read(reader)
    rendered = "".join(traceback.format_exception(error.type, error.value, error.tb))
    assert error.value.reason_code == "text_field_provider_unavailable"
    assert "secret-local-value" not in rendered


@pytest.mark.parametrize("change", ["runtime", "process"])
def test_second_from_point_field_identity_drift_is_rejected(change):
    first, second = _Wrapper("same"), _Wrapper("same")
    if change == "runtime":
        second.element_info.runtime_id = (9,)
    else:
        second.element_info.process_id = second.element_info.element.CurrentProcessId = 99
    desktop = SimpleNamespace(from_point=lambda *_: first if not hasattr(desktop, "seen") else second)
    desktop.seen = False
    def from_point(*_):
        if desktop.seen:
            return second
        desktop.seen = True
        return first
    desktop.from_point = from_point
    bound = SimpleNamespace(handle=7, process_id=8, rect=SimpleNamespace(left=100, top=200, right=500, bottom=500))
    reader = WindowsTextFieldReader(window_manager=SimpleNamespace(get_bound_window=lambda: bound), native_identity_reader=_Native(), desktop_factory=lambda **_: desktop, clock_ns=lambda: 9, read_id_factory=lambda: "read")
    with pytest.raises(TextFieldReadError, match="changed|window_or_process"):
        _read(reader)


def test_final_binding_check_rejects_window_rect_drift_after_second_read():
    wrapper = _Wrapper("same")
    calls = {"count": 0}
    good = SimpleNamespace(handle=7, process_id=8, rect=SimpleNamespace(left=100, top=200, right=500, bottom=500))
    bad = SimpleNamespace(handle=7, process_id=8, rect=SimpleNamespace(left=101, top=200, right=501, bottom=500))
    def bound():
        calls["count"] += 1
        return bad if calls["count"] >= 3 else good
    reader, _ = _reader(wrapper)
    reader._window_manager = SimpleNamespace(get_bound_window=bound)
    with pytest.raises(TextFieldReadError, match="window_binding_changed"):
        _read(reader)


@pytest.mark.parametrize("ranges, reason", [(None, "selection_unavailable"), ([], "selection_ambiguous"), ([_Range("x"), _Range("x")], "selection_ambiguous")])
def test_null_empty_and_multiple_uia_selection_arrays_are_explicit(ranges, reason):
    class Text:
        def GetSelection(self):
            return None if ranges is None else _RangeArray(ranges)
    with pytest.raises(TextFieldReadError, match=reason):
        _selection(Text())
