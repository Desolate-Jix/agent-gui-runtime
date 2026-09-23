"""点击前字段身份与点击后重排焦点的隔离契约。"""
from types import SimpleNamespace as NS

import pytest

from app.agent.text_field_evidence import TextFieldIdentity, TextFieldSnapshot
from app.agent import windows_text_field_reader as reader_module
from app.desktop_review import input_sequence
from tests.test_windows_text_field_reader import field
from tests.test_input_sequence import Coordinator as SequenceCoordinator


def snapshot(box=(20, 30, 100, 40), rid=(42, 7), value=""):
    identity = TextFieldIdentity("field", 10, 20, 123.0, rid, (0, 0, 600, 500), box)
    return TextFieldSnapshot(identity, "capture", "read", 1, "uia_text", value, (0, 0))


def test_preclick_scope_records_only_reader_proven_binding(monkeypatch):
    from app.core import local_text_focus
    expected = {"runtime_id": [42, 7], "control_type": "Group", "bbox": [20, 30, 100, 40],
        "window_handle": 10, "process_id": 20, "process_create_time": 123.0,
        "window_rect": [0, 0, 600, 500]}
    calls = []
    monkeypatch.setattr(local_text_focus, "probe_local_focus_target",
        lambda manager, handle, pid, point: calls.append((handle, pid, point)) or expected)
    monkeypatch.setattr(local_text_focus, "require_local_operator_input", lambda manager: True)
    target = local_text_focus.LocalTextFocusTarget(10, 20)
    with local_text_focus.local_text_focus_scope(target):
        local_text_focus.check_local_text_focus({"x": 40, "y": 45}, object())
    assert calls == [(10, 20, (40, 45))]
    assert target.binding == expected
    assert local_text_focus.check_local_text_focus({"x": 40, "y": 45}, object()) is None


def test_wrong_focus_rid_is_rejected_even_when_inside_same_window(monkeypatch):
    field = snapshot(rid=(42, 8))
    monkeypatch.setattr(reader_module, "_focused_field", lambda: NS(element_info=NS(
        runtime_id=[42, 8], control_type="Group")))
    instance = reader_module.WindowsTextFieldReader(window_manager=None, native_identity_reader=None)
    monkeypatch.setattr(instance, "_verify_binding", lambda *args: None)
    with pytest.raises(reader_module.TextFieldReadError, match="expected_identity_changed"):
        instance.read_bound_focus(target_field_id="field", capture_id="capture",
            target_window_handle=10, target_process_id=20, process_create_time=123.0,
            window_rect=(0, 0, 600, 500), expected_runtime_id=(42, 7),
            expected_control_type="Group")


def test_group_document_range_must_be_explicitly_writable(monkeypatch):
    monkeypatch.setattr(reader_module, "_no_pattern_exception", lambda: RuntimeError)
    instance = reader_module.WindowsTextFieldReader(window_manager=None, native_identity_reader=None)
    for readonly in (True, object(), None):
        wrapper = NS(iface_text=NS(DocumentRange=NS(GetAttributeValue=lambda _: readonly,
            GetText=lambda _: "")))
        with pytest.raises(reader_module.TextFieldReadError, match="target_not_writable"):
            instance._read_text(wrapper, "Group")


def test_reserved_uia_readonly_values_remain_distinct_in_safe_diagnostic(monkeypatch):
    from pywinauto.uia_defines import IUIA
    uia = IUIA().iuia
    monkeypatch.setattr(reader_module, "_no_pattern_exception", lambda: RuntimeError)
    instance = reader_module.WindowsTextFieldReader(window_manager=None, native_identity_reader=None)
    for value, expected in ((uia.ReservedMixedAttributeValue, "mixed"),
                            (uia.ReservedNotSupportedValue, "not_supported")):
        wrapper = NS(iface_text=NS(DocumentRange=NS(GetAttributeValue=lambda _: value)))
        with pytest.raises(reader_module.TextFieldReadError) as raised:
            instance._read_text(wrapper, "Group")
        assert raised.value.to_reference()["diagnostic"]["attribute_class"] == expected


def test_keyboard_anchor_uses_new_verified_box_not_original_click(monkeypatch):
    from app.core.local_keyboard_target import LocalKeyboardTarget
    from hashlib import sha256
    before = snapshot(box=(100, 100, 200, 100))
    anchor = (200, 150)
    target = LocalKeyboardTarget(before, "Group", anchor, "type_text",
        text_sha256=sha256(b"next").hexdigest(), clear_existing=True, focus_reflow=True)
    assert target.point == anchor
    with pytest.raises(ValueError):
        LocalKeyboardTarget(before, "Group", (40, 45), "type_text",
            text_sha256=sha256(b"next").hexdigest(), clear_existing=True, focus_reflow=True)


def test_bound_focus_accepts_layout_shift_only_for_same_focused_writable_group(monkeypatch):
    wrapper = field(kind="Group", text="clean")
    wrapper.element_info.process_id = 20
    wrapper.element_info.rectangle = NS(left=100, top=100, right=300, bottom=200)
    wrapper.element_info.element.CurrentHasKeyboardFocus = 1
    wrapper.is_visible = lambda: True
    wrapper.is_enabled = lambda: True
    wrapper.top_level_parent = lambda: NS(element_info=NS(handle=10))
    monkeypatch.setattr(reader_module, "_focused_field", lambda: wrapper)
    monkeypatch.setattr(reader_module, "_selection", lambda _: (5, 5))
    instance = reader_module.WindowsTextFieldReader(window_manager=None, native_identity_reader=None,
        clock_ns=lambda: 100, read_id_factory=lambda: "read-1")
    monkeypatch.setattr(instance, "_verify_binding", lambda *args: None)
    result = instance.read_bound_focus(target_field_id="field", capture_id="capture",
        target_window_handle=10, target_process_id=20, process_create_time=123.0,
        window_rect=(0, 0, 600, 500), expected_runtime_id=(42, 1),
        expected_control_type="Group")
    assert result.identity.control_bbox == (100, 100, 200, 100)
    assert result.value == "clean" and result.selection == (5, 5)


def test_bound_focus_refuses_mixed_group_even_with_exact_rid(monkeypatch):
    wrapper = field(kind="Group", text="clean")
    wrapper.element_info.process_id = 20
    wrapper.element_info.rectangle = NS(left=100, top=100, right=300, bottom=200)
    wrapper.element_info.element.CurrentHasKeyboardFocus = 1
    wrapper.is_visible = lambda: True
    wrapper.is_enabled = lambda: True
    wrapper.top_level_parent = lambda: NS(element_info=NS(handle=10))
    wrapper.iface_text.DocumentRange.GetAttributeValue = lambda _: object()
    monkeypatch.setattr(reader_module, "_focused_field", lambda: wrapper)
    instance = reader_module.WindowsTextFieldReader(window_manager=None, native_identity_reader=None)
    monkeypatch.setattr(instance, "_verify_binding", lambda *args: None)
    with pytest.raises(reader_module.TextFieldReadError, match="target_not_writable"):
        instance.read_bound_focus(target_field_id="field", capture_id="capture",
            target_window_handle=10, target_process_id=20, process_create_time=123.0,
            window_rect=(0, 0, 600, 500), expected_runtime_id=(42, 1),
            expected_control_type="Group")


def test_sequence_uses_postfocus_anchor_without_reclicking_original_point(monkeypatch):
    class BoundCoordinator(SequenceCoordinator):
        def execute_local_step(self, **kwargs):
            if kwargs["operation"] == "execute_recognition_plan":
                kwargs["focus_target"].binding = {"runtime_id": [42, 7], "control_type": "Group",
                    "bbox": [10, 10, 100, 50], "window_handle": 1, "process_id": 2,
                    "process_create_time": 100.0, "window_rect": [0, 0, 800, 600]}
            return super().execute_local_step(**kwargs)

    reads = iter([snapshot(box=(100, 100, 200, 100), value=""),
        snapshot(box=(100, 100, 200, 100), value="next")])
    def local_read(*args):
        item = next(reads)
        identity = item.identity
        identity = TextFieldIdentity(args[3], 1, 2, 100.0, (42, 7),
            (0, 0, 800, 600), identity.control_bbox)
        return TextFieldSnapshot(identity, "capture", "read", 1, "uia_text", item.value, (0, 0))
    monkeypatch.setattr(input_sequence, "_read_local_focus", local_read)
    co = BoundCoordinator()
    result = input_sequence.run_input_sequence(co, {"handle": 1, "process_id": 2},
        {"field_goal": "Editor", "text": "next", "clear_existing": True, "submit_search": False})
    assert result["status"] == "completed"
    assert result["selected_click_point"] == {"x": 10, "y": 20}
    assert result["keyboard_anchor_point"] == {"x": 200, "y": 150}
    assert co.calls[1]["request"]["x"] == 200 and co.calls[1]["request"]["y"] == 150
    assert co.calls[1]["keyboard_target"].focus_reflow is True
    assert [call["operation"] for call in co.calls] == ["execute_recognition_plan", "type_text"]


def test_sequence_rejects_changed_bound_focus_before_keyboard(monkeypatch):
    class BoundCoordinator(SequenceCoordinator):
        def execute_local_step(self, **kwargs):
            if kwargs["operation"] == "execute_recognition_plan":
                kwargs["focus_target"].binding = {"runtime_id": [42, 7], "control_type": "Group",
                    "bbox": [10, 10, 100, 50], "window_handle": 1, "process_id": 2,
                    "process_create_time": 100.0, "window_rect": [0, 0, 800, 600]}
            return super().execute_local_step(**kwargs)
    from app.agent.windows_text_field_reader import TextFieldReadError
    def wrong_focus(*args):
        raise TextFieldReadError("text_field_expected_identity_changed")
    monkeypatch.setattr(input_sequence, "_read_local_focus", wrong_focus)
    co = BoundCoordinator()
    result = input_sequence.run_input_sequence(co, {"handle": 1, "process_id": 2},
        {"field_goal": "Editor", "text": "next", "clear_existing": True, "submit_search": False})
    assert result["status"] == "interrupted"
    assert result["error"]["code"] == "text_field_expected_identity_changed"
    assert len(co.calls) == 1


def test_sequence_rejects_disagreement_between_uia_plan_and_preclick_hit(monkeypatch):
    class BoundCoordinator(SequenceCoordinator):
        def execute_local_step(self, **kwargs):
            if kwargs["operation"] == "execute_recognition_plan":
                kwargs["focus_target"].binding = {"runtime_id": [42, 7], "control_type": "Edit",
                    "bbox": [10, 10, 100, 50], "window_handle": 1, "process_id": 2,
                    "process_create_time": 100.0, "window_rect": [0, 0, 800, 600]}
            return super().execute_local_step(**kwargs)
    monkeypatch.setattr(input_sequence, "_focus_field_binding", lambda *args: {
        "runtime_id": [42, 8], "control_type": "Edit"})
    co = BoundCoordinator()
    result = input_sequence.run_input_sequence(co, {"handle": 1, "process_id": 2},
        {"field_goal": "Editor", "text": "next", "clear_existing": True, "submit_search": False})
    assert result["status"] == "interrupted"
    assert result["error"]["code"] == "input_preclick_binding_conflict"
    assert len(co.calls) == 1


@pytest.mark.parametrize("readonly,allowed", [(False, True), (True, False), (None, False), ("mixed", False)])
def test_preclick_group_requires_full_range_explicit_writable_and_same_window(monkeypatch, readonly, allowed):
    wrapper = field(kind="Group", text="")
    wrapper.element_info.process_id = 20
    wrapper.element_info.rectangle = NS(left=20, top=30, right=120, bottom=70)
    wrapper.is_visible = lambda: True
    wrapper.is_enabled = lambda: True
    wrapper.top_level_parent = lambda: NS(element_info=NS(handle=10))
    wrapper.iface_text.DocumentRange.GetAttributeValue = lambda _: object() if readonly == "mixed" else readonly
    del wrapper.iface_value
    manager = NS(get_bound_window=lambda: NS(handle=10, process_id=20,
        rect=NS(left=0, top=0, right=600, bottom=500)))
    identity = {"contract_version": "windows_native_identity_observation_v1",
        "provider": "windows_native_identity", "status": "observed", "target_window_handle": 10,
        "process_id": 20, "process_create_time": 123.0, "executable_path": "C:\\fixture.exe"}
    monkeypatch.setattr(reader_module, "WindowsNativeIdentityReader",
        lambda **kw: NS(read_identity=lambda _: identity))
    monkeypatch.setattr(reader_module, "_no_pattern_exception", lambda: AttributeError)
    monkeypatch.setattr(reader_module, "_desktop_factory",
        lambda **kw: NS(from_point=lambda *args: wrapper))
    monkeypatch.setattr(reader_module.WindowsTextFieldReader, "_verify_binding", lambda *args: None)
    call = lambda: reader_module.probe_local_focus_target(manager, 10, 20, (40, 45))
    if allowed:
        binding = call()
        assert binding["runtime_id"] == [42, 1] and binding["control_type"] == "Group"
        assert binding["bbox"] == [20, 30, 100, 40]
    else:
        with pytest.raises(reader_module.TextFieldReadError):
            call()
