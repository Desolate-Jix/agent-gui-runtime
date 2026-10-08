"""点击后字段拒绝的只读现场诊断；不执行输入或读取字段值。"""
from types import SimpleNamespace as NS

import pytest

from app.agent import windows_text_field_reader as module


class PrivateField:
    @property
    def CurrentName(self):
        pytest.fail("诊断不得读取字段名称")

    @property
    def CurrentValue(self):
        pytest.fail("诊断不得读取字段值")

    CurrentHasKeyboardFocus = True
    CurrentProcessId = 20
    CurrentNativeWindowHandle = 0


def case(monkeypatch, fault):
    element = PrivateField()
    info = NS(runtime_id=[42, 1], control_type="ComboBox", process_id=20,
        handle=0, rectangle=NS(left=971, top=96, right=1487, bottom=120), element=element)
    wrapper = NS(element_info=info)
    root = 10
    if fault == "runtime_id":
        info.runtime_id = [42, 2]
    elif fault == "control_type":
        info.control_type = "Edit"
    elif fault == "geometry":
        info.rectangle.left += 24
    elif fault == "point_outside":
        info.rectangle.left = 1100
    elif fault == "bbox_unavailable":
        info.rectangle = None
    elif fault == "window_or_process":
        root = 99
    calls = []
    def focused():
        calls.append("focused")
        return wrapper
    monkeypatch.setattr(module, "_focused_field", focused)
    monkeypatch.setattr(module, "_top_window_handle", lambda value: root)
    monkeypatch.setattr(module, "_native_window_process_id", lambda handle: {10: 20, 99: 90}.get(handle), raising=False)
    reader = module.WindowsTextFieldReader(window_manager=None, native_identity_reader=None)
    monkeypatch.setattr(reader, "_verify_binding", lambda *args: calls.append("binding"))
    monkeypatch.setattr(reader, "_read_text", lambda *args: pytest.fail("解析失败不得读取字段值"))
    return reader, calls, dict(target_field_id="field", capture_id="fresh",
        target_window_handle=10, target_process_id=20, process_create_time=123.0,
        window_rect=(0, 0, 2560, 1400), target_bbox=(971, 96, 516, 24),
        click_point=(1045, 98), expected_runtime_id=(42, 1), expected_control_type="ComboBox",
        require_keyboard_focus=True)


@pytest.mark.parametrize("fault", ["runtime_id", "control_type", "geometry", "point_outside",
    "bbox_unavailable", "window_or_process"])
def test_failure_keeps_original_reason_and_exact_focused_object(monkeypatch, fault):
    reader, calls, kwargs = case(monkeypatch, fault)
    with pytest.raises(module.TextFieldReadError) as raised:
        reader.read_field(**kwargs)
    expected_reason = ("text_field_window_or_process_changed" if fault == "window_or_process"
        else "text_field_expected_identity_changed")
    assert raised.value.reason_code == expected_reason
    diagnostic = raised.value.to_reference()["diagnostic"]
    assert diagnostic["phase"] == "resolve_field" and diagnostic["read_index"] == 1
    record = diagnostic["focused_field_identity"]
    assert record["contract_version"] == "text_focused_field_diagnostic.v1"
    assert record["failure_branch"] == fault
    assert record["expected"] == {"runtime_id": [42, 1], "control_type": "ComboBox",
        "bbox": [971, 96, 516, 24], "window_handle": 10, "process_id": 20}
    assert record["actual"]["runtime_id"] == ([42, 2] if fault == "runtime_id" else [42, 1])
    assert record["actual"]["control_type"] == ("Edit" if fault == "control_type" else "ComboBox")
    assert record["actual"]["keyboard_focus"] is True
    assert record["actual"]["process_id"] == 20
    assert record["actual"]["native_window_handle"] == 0
    assert record["actual"]["native_root_handle"] == (99 if fault == "window_or_process" else 10)
    assert record["actual"]["native_root_process_id"] == (90 if fault == "window_or_process" else 20)
    assert record["point"] == [1045, 98]
    assert record["allow_geometry_rebind"] is False
    assert calls.count("focused") == 1


def test_geometry_diagnostic_retains_original_and_actual_bboxes(monkeypatch):
    reader, calls, kwargs = case(monkeypatch, "geometry")
    with pytest.raises(module.TextFieldReadError) as raised:
        reader.read_field(**kwargs)
    record = raised.value.diagnostic["focused_field_identity"]
    assert record["actual"]["bbox"] == [995, 96, 492, 24]
    assert record["actual"]["point_inside"] is True


def test_diagnostic_failure_never_masks_original_refusal(monkeypatch):
    reader, calls, kwargs = case(monkeypatch, "runtime_id")
    def unavailable(*args):
        raise RuntimeError("PRIVATE_SENTINEL")
    monkeypatch.setattr(module, "_top_window_handle", unavailable)
    monkeypatch.setattr(module, "_native_window_process_id", unavailable)
    with pytest.raises(module.TextFieldReadError, match="text_field_expected_identity_changed") as raised:
        reader.read_field(**kwargs)
    actual = raised.value.diagnostic["focused_field_identity"]["actual"]
    assert "native_root_handle" not in actual and "native_root_process_id" not in actual
    assert "PRIVATE_SENTINEL" not in str(raised.value.to_reference())
    assert calls.count("focused") == 1


def test_focused_field_projection_strips_names_values_and_unbounded_data():
    record = {"contract_version": "text_focused_field_diagnostic.v1", "failure_branch": "geometry",
        "point": [1045, 98], "allow_geometry_rebind": False,
        "expected": {"runtime_id": [42, 1], "control_type": "ComboBox", "bbox": [971, 96, 516, 24],
            "window_handle": 10, "process_id": 20, "name": "PRIVATE_SENTINEL"},
        "actual": {"runtime_id": [True], "control_type": "PRIVATE_SENTINEL", "bbox": [0, 0, -1, 1],
            "keyboard_focus": "PRIVATE_SENTINEL", "process_id": True, "native_window_handle": -1,
            "native_root_handle": 2 ** 64, "native_root_process_id": -1, "value": "PRIVATE_SENTINEL"}}
    result = module.TextFieldReadError("text_field_expected_identity_changed",
        diagnostic={"focused_field_identity": record, "value": "PRIVATE_SENTINEL"}).to_reference()
    projected = result["diagnostic"]["focused_field_identity"]
    assert projected["actual"] == {"control_type": "other"}
    assert "PRIVATE_SENTINEL" not in str(result)


def test_unknown_focused_diagnostic_contract_is_not_projected():
    result = module.TextFieldReadError("text_field_expected_identity_changed",
        diagnostic={"focused_field_identity": {"contract_version": "PRIVATE_SENTINEL"}}).to_reference()
    assert result == {"reason_code": "text_field_expected_identity_changed"}


@pytest.mark.parametrize("box", [[0, 0, "PRIVATE_SENTINEL", 1], [0, 0, None, 1], [0, 0, True, 1]])
def test_malformed_diagnostic_geometry_cannot_raise_or_escape(box):
    result = module.TextFieldReadError("text_field_expected_identity_changed", diagnostic={
        "focused_field_identity": {"contract_version": "text_focused_field_diagnostic.v1",
            "actual": {"bbox": box}}}).to_reference()
    assert result["diagnostic"]["focused_field_identity"]["actual"] == {}


def test_failure_diagnostic_reuses_already_observed_element_info(monkeypatch):
    reader, calls, kwargs = case(monkeypatch, "runtime_id")
    original = module._focused_field().element_info
    calls.clear()
    class Wrapper:
        reads = 0
        @property
        def element_info(self):
            self.reads += 1
            if self.reads > 1:
                raise RuntimeError("PRIVATE_SENTINEL")
            return original
    wrapper = Wrapper()
    monkeypatch.setattr(module, "_focused_field", lambda: wrapper)
    with pytest.raises(module.TextFieldReadError, match="text_field_expected_identity_changed") as raised:
        reader.read_field(**kwargs)
    assert raised.value.diagnostic["focused_field_identity"]["actual"]["runtime_id"] == [42, 2]
    assert wrapper.reads == 1


def test_success_does_not_query_failure_diagnostics(monkeypatch):
    reader, calls, kwargs = case(monkeypatch, None)
    def forbidden(*args, **kw):
        pytest.fail("成功路径不得增加失败诊断查询")
    monkeypatch.setattr(module, "_focused_field_failure_diagnostic", forbidden)
    monkeypatch.setattr(module, "_native_window_process_id", forbidden)
    field = reader._bound_focused_field(10, 20, 123.0, (0, 0, 2560, 1400),
        (971, 96, 516, 24), (1045, 98), ((42, 1), "ComboBox"), allow_geometry_rebind=False)
    assert field.element_info.runtime_id == [42, 1]
    assert calls == ["binding", "focused", "binding"]


def test_native_root_pid_diagnostic_uses_pointer_sized_handle(monkeypatch):
    calls = []
    def query(handle, output):
        calls.append(handle)
        output._obj.value = 20
        return 3
    monkeypatch.setattr(module.ctypes, "windll", NS(user32=NS(GetWindowThreadProcessId=query)), raising=False)
    handle = 2 ** 40 + 10
    assert module._native_window_process_id(handle) == 20
    assert calls == [handle]
    assert query.argtypes[0] is module.ctypes.c_void_p


@pytest.mark.parametrize("handle", [None, False, 0, -1, "PRIVATE_SENTINEL"])
def test_invalid_native_root_pid_diagnostic_does_not_query_system(monkeypatch, handle):
    def forbidden(*args):
        pytest.fail("无效诊断句柄不得调用系统")
    monkeypatch.setattr(module.ctypes, "windll", NS(user32=NS(GetWindowThreadProcessId=forbidden)), raising=False)
    assert module._native_window_process_id(handle) is None
