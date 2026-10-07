"""指定字段核验与键盘焦点分离；复用真实读取器的严格身份检查。"""
from types import SimpleNamespace as NS
import pytest
from app.agent import windows_text_field_reader as native
from app.learning_memory import verification_observation as observation
from tests.test_verification_observation import captured, fake_captures
from tests.test_windows_text_field_reader import field, NoPattern

@pytest.mark.parametrize("fault", ["none", "wrong_target", "changed_value"])
def test_verification_reads_selected_field_without_moving_focus(monkeypatch, fault):
    pairs = [captured("before"), captured("after")]
    for frame, scene in pairs:
        frame["window_rect"] = [300, 100, 1100, 700]
        control = scene["uia"]["snapshot"]["controls"][0]
        control["control_type"] = "Edit"
        control["automation_id"] = "1003"
    fake_captures(monkeypatch, *pairs)
    wrappers = []
    for index in range(2):
        value = "fresh" if index == 0 or fault != "changed_value" else "changed"
        wrapper = field(value=value, text=value)
        wrapper.element_info.runtime_id = [42, 8 if index and fault == "wrong_target" else 7]
        wrapper.element_info.process_id = 42
        wrapper.element_info.rectangle = NS(left=320, top=130, right=520, bottom=160)
        wrapper.element_info.element.CurrentHasKeyboardFocus = False
        wrapper.is_visible = lambda: True
        wrapper.is_enabled = lambda: True
        wrapper.parent = lambda: NS(element_info=NS(handle=91, process_id=42))
        wrappers.append(wrapper)
    monkeypatch.setattr(native, '_native_root_handle', lambda hwnd: {91: 91}.get(hwnd))
    windows = NS(get_bound_window=lambda: NS(handle=91, process_id=42,
        rect=NS(left=300, top=100, right=1100, bottom=700)))
    identity = NS(read_identity=lambda _: {
        "contract_version": "windows_native_identity_observation_v1",
        "provider": "windows_native_identity", "status": "observed",
        "target_window_handle": 91, "process_id": 42,
        "process_create_time": 17.5, "executable_path": "C:\\fixture.exe"})
    focused = NS(element_info=NS(runtime_id=[42, 999], control_type="List"))
    focus_reads, hits = [], []
    def current_focus():
        focus_reads.append(True)
        return focused
    monkeypatch.setattr(native, "_focused_field", current_focus)
    monkeypatch.setattr(native, "_selection", lambda _: None)
    monkeypatch.setattr(native, "_no_pattern_exception", lambda: NoPattern)
    sequence = iter(wrappers)
    def hit(x, y):
        hits.append((x, y))
        return next(sequence)
    def reader(**kwargs):
        return native.WindowsTextFieldReader(**kwargs,
            desktop_factory=lambda **_: NS(from_point=hit),
            clock_ns=lambda: 100, read_id_factory=lambda: "field-read")
    monkeypatch.setattr(observation, "WindowsTextFieldReader", reader)
    monkeypatch.setattr(observation, "WindowsNativeIdentityReader", lambda **_: identity)
    result = observation.read_step_observation(NS(_windows=lambda: windows),
        target={"handle": 91, "process_id": 42},
        selector={"control_type": "Edit", "automation_id": "1003"}, method="uia_value")
    if fault == "none":
        assert result["status"] == "ok", result
        assert result["values"] == {"field_value": "fresh"}
        assert hits == [(420, 145), (420, 145)]
        assert focus_reads == []
    else:
        assert result["status"] == "unavailable"
        assert result["values"] == {}
        assert result["reason"] == ("text_field_expected_identity_changed" if fault == "wrong_target"
                                    else "text_field_changed_during_read")
