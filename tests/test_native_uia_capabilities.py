"""UIA 包装方法不是真实 pattern 能力，静态同名标签也不是动作身份。"""
from types import SimpleNamespace

import pytest

from app.operation.screen_reading.uia_provider import _patterns
from tests.test_native_vista_identity_reconciliation import _control, _recognize


class _InheritedMethods:
    def invoke(self): raise AssertionError("must not invoke")
    def get_value(self): raise AssertionError("must not read content")
    def set_value(self): raise AssertionError("must not write")
    def texts(self): raise AssertionError("must not read content")
    def select(self): raise AssertionError("must not select")
    def expand(self): raise AssertionError("must not expand")
    def collapse(self): raise AssertionError("must not collapse")
    def toggle(self): raise AssertionError("must not toggle")

    def __getattr__(self, name):
        if name.startswith("iface_"):
            raise RuntimeError("pattern not supported")
        raise AttributeError(name)


def test_inherited_wrapper_methods_are_not_pattern_evidence():
    assert _patterns(_InheritedMethods()) == ()


def test_only_resolved_non_null_pattern_interfaces_are_reported():
    wrapper = _InheritedMethods()
    wrapper.iface_value = object()
    wrapper.iface_text = object()
    wrapper.iface_invoke = None
    wrapper.iface_toggle = False
    assert _patterns(wrapper) == ("Value", "Text")


@pytest.mark.parametrize("point,allowed", [({"x": 254, "y": 41}, True), ({"x": 250, "y": 10}, False)])
def test_static_same_name_label_is_not_action_but_point_still_must_hit_control(tmp_path, monkeypatch, point, allowed):
    label = {**_control(control_id="static-label", bbox={"x": 223, "y": 0, "w": 55, "h": 19}),
        "control_type": "Text", "patterns": ["Text"]}
    result = _recognize(tmp_path, monkeypatch, controls=[label, _control()], point=point)
    assert result["pre_click_decision"]["allowed"] is allowed


def test_same_name_text_with_real_invoke_still_creates_ambiguity(tmp_path, monkeypatch):
    label = {**_control(control_id="clickable-text"), "control_type": "Text", "patterns": ["Invoke"]}
    result = _recognize(tmp_path, monkeypatch, controls=[label, _control()])
    assert result["pre_click_decision"]["allowed"] is False


@pytest.mark.parametrize("value", ["", "预览版固定文本 S71", "运行时变量"])
def test_edit_identity_uses_accessible_name_not_mutable_value(value):
    from app.operation.screen_reading.uia_provider import WindowsUIAProvider
    rect = SimpleNamespace(left=100, top=120, right=400, bottom=141)
    wrapper = SimpleNamespace(rectangle=lambda: rect, window_text=lambda: value,
        element_info=SimpleNamespace(name="搜索词", rich_text=value, control_type="Edit",
            automation_id="searchQuery", class_name="QLineEdit"),
        is_enabled=lambda: True, is_visible=lambda: True, iface_value=object())
    bound = SimpleNamespace(rect=SimpleNamespace(left=80, top=100))
    control = WindowsUIAProvider()._control_from_wrapper(wrapper, bound=bound, index=1)
    assert control.name == "搜索词"
    assert control.control_id == "uia_1_searchquery"
    assert control.patterns == ("Value",)


def test_empty_field_and_same_name_static_label_use_current_uia_primary(tmp_path, monkeypatch):
    from tests.test_current_uia_primary_grounding import _control as field, _recognize as recognize_field
    label = field(control_id="field-label", control_type="Text", patterns=[],
        bbox={"x": 100, "y": 60, "w": 300, "h": 20}, screen_bbox={"x": 100, "y": 60, "w": 300, "h": 20})
    result, calls = recognize_field(tmp_path, monkeypatch, controls=[label, field()], semantic_action="fill_field")
    assert result["pre_click_decision"]["allowed"] is True
    assert result["candidate_result"]["summary"]["vista_roi_source"] == "current_uia_candidate_v1"
    assert result["execution_path"]["vista_direct_point_grounding_used"] is False
    assert len(calls) == 1


def test_chromium_combobox_field_uses_current_uia_primary(tmp_path, monkeypatch):
    """Chromium 搜索框常公开为 ComboBox，仍必须走唯一当前输入字段。"""
    from tests.test_current_uia_primary_grounding import _control as field, _recognize as recognize_field

    control = field(
        name="Search",
        control_type="ComboBox",
        automation_id="ti6dpd",
        class_name="gLFyf",
        patterns=["Value", "Text", "ExpandCollapse"],
        bbox={"x": 100, "y": 100, "w": 300, "h": 50},
        screen_bbox={"x": 100, "y": 100, "w": 300, "h": 50},
    )
    result, calls = recognize_field(
        tmp_path,
        monkeypatch,
        controls=[control],
        goal="Search",
        raw="[500, 312]",
        semantic_action="fill_field",
    )

    assert result["pre_click_decision"]["allowed"] is True
    assert result["candidate_result"]["candidates"][0]["role"] == "combobox"
    assert result["candidate_result"]["summary"]["current_uia_primary_candidate_used"] is True
    assert result["execution_path"]["vista_direct_point_grounding_used"] is False
    assert result["candidate_result"]["summary"]["vista_roi_source"] == "current_uia_candidate_v1"
    assert len(calls) == 1


def test_chromium_combobox_near_border_model_point_reconciles_to_current_uia(tmp_path, monkeypatch):
    """模型量化点贴近框外时，只允许唯一当前 UIA 字段提供框内点。"""
    from tests.test_current_uia_primary_grounding import _control as field, _recognize as recognize_field

    control = field(
        name="Search",
        control_type="ComboBox",
        automation_id="ti6dpd",
        class_name="gLFyf",
        patterns=["Value", "Text", "ExpandCollapse"],
        bbox={"x": 100, "y": 100, "w": 300, "h": 50},
        screen_bbox={"x": 100, "y": 100, "w": 300, "h": 50},
    )
    result, _ = recognize_field(
        tmp_path,
        monkeypatch,
        controls=[control],
        goal="Search",
        raw="[500, 198]",
        semantic_action="fill_field",
    )

    grounding = result["narrow_search_result"]["results"][0]
    assert result["pre_click_decision"]["allowed"] is True
    assert result["pre_click_decision"]["selected_click_point"] == {"x": 250, "y": 125}
    assert grounding["coordinate_source"] == "current_uia_vista_near_bbox_reconciled_v1"
    assert "current_capture_uia_point_reconciled" in grounding["reasons"]


@pytest.mark.parametrize("case", ["label_invoke", "duplicate_fields", "model_outside"])
def test_fill_intent_chooses_field_role_not_same_name_invoke_label(tmp_path, monkeypatch, case):
    from tests.test_current_uia_primary_grounding import _control as field, _recognize as recognize_field
    label = field(control_id="field-label", control_type="Text", patterns=["Invoke"],
        bbox={"x": 100, "y": 60, "w": 300, "h": 20}, screen_bbox={"x": 100, "y": 60, "w": 300, "h": 20})
    controls = [label, field()]
    if case == "duplicate_fields":
        controls.append(field(control_id="second-field", automation_id="16"))
    result, _ = recognize_field(tmp_path, monkeypatch, controls=controls, semantic_action="fill_field",
        raw="[0, 0]" if case == "model_outside" else "[500, 500]")
    assert result["pre_click_decision"]["allowed"] is (case == "label_invoke")
    if case == "label_invoke":
        assert result["candidate_result"]["candidates"][0]["role"] == "input"
        assert result["candidate_result"]["summary"]["vista_roi_source"] == "current_uia_candidate_v1"


def test_thin_input_primary_preserves_window_context(tmp_path, monkeypatch):
    from PIL import Image
    from tests.test_current_uia_primary_grounding import _control as field, _recognize as recognize_field
    control = field(bbox={"x": 11, "y": 100, "w": 578, "h": 21},
        screen_bbox={"x": 11, "y": 100, "w": 578, "h": 21})
    result, calls = recognize_field(tmp_path, monkeypatch, controls=[control], semantic_action="fill_field", raw="[500, 275]")
    with Image.open(calls[0]["path"]) as pixels:
        assert pixels.width == 600 and pixels.height == 400
    assert len(calls) == 1
    assert result["model_io"]["attempts"][0]["image_preprocess"]["roi_policy"] == "thin_input_window_context_primary"
    assert result["pre_click_decision"]["allowed"] is True


def test_thin_input_context_still_rejects_model_point_on_label(tmp_path, monkeypatch):
    from tests.test_current_uia_primary_grounding import _control as field, _recognize as recognize_field
    control = field(bbox={"x": 11, "y": 100, "w": 578, "h": 21},
        screen_bbox={"x": 11, "y": 100, "w": 578, "h": 21})
    result, calls = recognize_field(tmp_path, monkeypatch, controls=[control], semantic_action="fill_field", raw="[500, 210]")
    assert len(calls) == 1
    assert result["pre_click_decision"]["allowed"] is False
    assert result["pre_click_decision"]["selected_click_point"] is None
