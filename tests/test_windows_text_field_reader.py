"""Chromium 字段对象标记语义的隔离回归；不读取浏览器或执行输入。"""
from types import SimpleNamespace as NS

import pytest

from app.agent import windows_text_field_reader as module


class NoPattern(Exception):
    pass


@pytest.fixture(autouse=True)
def fake_com_boundary(monkeypatch):
    monkeypatch.setattr(module, "_no_pattern_exception", lambda: NoPattern)


def field(*, kind="Edit", role="textbox", value="", text="\ufffc", fault=None):
    element = NS(CurrentFrameworkId="Chrome", CurrentAriaRole=role, CurrentName="Address:",
                 CurrentProcessId=20, CurrentIsPassword=False)
    enclosing = NS(**vars(element), GetRuntimeId=lambda: [42, 1])
    range_ = NS(GetAttributeValue=lambda _: False, GetText=lambda _: text,
                GetEnclosingElement=lambda: enclosing, GetChildren=lambda: NS(Length=0))
    pattern = NS(DocumentRange=range_)
    value_pattern = NS(CurrentIsReadOnly=False, CurrentValue=value)
    info = NS(element=element, runtime_id=[42, 1], control_type=kind)
    wrapper = NS(element_info=info, iface_value=value_pattern, iface_text=pattern)
    if fault == "framework":
        element.CurrentFrameworkId = "Other"
    elif fault == "role":
        element.CurrentAriaRole = "combobox"
    elif fault == "enclosing_role":
        enclosing.CurrentAriaRole = "combobox"
    elif fault == "enclosing_framework":
        enclosing.CurrentFrameworkId = "Other"
    elif fault == "enclosing_identity":
        enclosing.GetRuntimeId = lambda: [42, 2]
    elif fault == "enclosing_process":
        enclosing.CurrentProcessId = 21
    elif fault == "enclosing_name":
        enclosing.CurrentName = "other"
    elif fault == "children":
        range_.GetChildren = lambda: NS(Length=1)
    elif fault == "unknown_children":
        del range_.GetChildren
    elif fault == "value_readonly":
        value_pattern.CurrentIsReadOnly = True
    elif fault == "text_readonly":
        range_.GetAttributeValue = lambda _: True
    elif fault == "value_readonly_unknown":
        value_pattern.CurrentIsReadOnly = None
    elif fault == "text_readonly_unknown":
        range_.GetAttributeValue = lambda _: None
    return wrapper


def read(wrapper, kind="Edit"):
    reader = module.WindowsTextFieldReader(window_manager=None, native_identity_reader=None)
    return reader._read_text(wrapper, kind)


@pytest.mark.parametrize("value", ["", "https://example.org/", "\u4e2d\u6587"])
def test_chromium_edit_object_range_uses_actual_value_not_object_selection(value):
    wrapper = field(value=value)

    def forbidden():
        pytest.fail("对象范围不能被当作文本选区")

    wrapper.iface_text.GetSelection = forbidden
    assert read(wrapper) == (value, "uia_value", None)


@pytest.mark.parametrize("fault", [
    "framework", "role", "enclosing_role", "enclosing_framework", "enclosing_identity",
    "enclosing_process", "enclosing_name", "children", "unknown_children",
    "value_readonly", "text_readonly", "value_readonly_unknown", "text_readonly_unknown",
])
def test_edit_object_range_never_relaxes_scope_or_writability(fault):
    with pytest.raises(module.TextFieldReadError):
        read(field(fault=fault))


@pytest.mark.parametrize("text", ["Address:", "different", "\ufffc\ufffc", "\ufffc\n"])
def test_edit_real_text_disagreement_still_fails(text):
    with pytest.raises(module.TextFieldReadError, match="text_field_value_patterns_disagree"):
        read(field(text=text))


def test_edit_object_marker_requires_authoritative_value_pattern():
    base = field()

    class Wrapper:
        element_info = base.element_info
        iface_text = base.iface_text

        @property
        def iface_value(self):
            raise NoPattern()

    with pytest.raises(module.TextFieldReadError):
        read(Wrapper())


@pytest.mark.parametrize("text", ["\ufffc", "Address:"])
def test_existing_combo_noncontent_range_behavior_remains_exact(text):
    assert read(field(kind="ComboBox", role="combobox", text=text), "ComboBox") == ("", "uia_value", None)


def test_matching_edit_text_keeps_existing_content_selection(monkeypatch):
    wrapper = field(value="exact", text="exact")
    monkeypatch.setattr(module, "_selection", lambda _: (1, 3))
    assert read(wrapper) == ("exact", "uia_value", (1, 3))


@pytest.mark.parametrize("changed", [False, True])
def test_full_field_read_rechecks_value_and_identity_for_object_marker(changed):
    wrapper = field()
    wrapper.element_info.process_id = 20
    wrapper.element_info.rectangle = NS(left=20, top=30, right=120, bottom=55)
    wrapper.is_visible = lambda: True
    wrapper.is_enabled = lambda: True
    wrapper.top_level_parent = lambda: NS(element_info=NS(handle=10))
    values = iter(["", "changed" if changed else ""])

    class ValuePattern:
        CurrentIsReadOnly = False

        @property
        def CurrentValue(self):
            return next(values)

    wrapper.iface_value = ValuePattern()
    native = NS(read_identity=lambda _: {
        "contract_version": "windows_native_identity_observation_v1",
        "provider": "windows_native_identity", "status": "observed",
        "target_window_handle": 10, "process_id": 20,
        "process_create_time": 123.0, "executable_path": "C:\\fixture.exe",
    })
    windows = NS(get_bound_window=lambda: NS(handle=10, process_id=20,
        rect=NS(left=0, top=0, right=600, bottom=500)))
    reader = module.WindowsTextFieldReader(window_manager=windows, native_identity_reader=native,
        desktop_factory=lambda **kw: NS(from_point=lambda *args: wrapper),
        clock_ns=lambda: 100, read_id_factory=lambda: "read-1")
    kwargs = dict(target_field_id="address", capture_id="fresh", target_window_handle=10,
        target_process_id=20, process_create_time=123.0, window_rect=(0, 0, 600, 500),
        target_bbox=(20, 30, 100, 25), click_point=(50, 40),
        expected_runtime_id=(42, 1), expected_control_type="Edit")
    if changed:
        with pytest.raises(module.TextFieldReadError, match="text_field_changed_during_read"):
            reader.read_field(**kwargs)
    else:
        result = reader.read_field(**kwargs)
        assert result.value == ""
        assert result.selection is None


@pytest.mark.parametrize("read_index", [1, 2])
@pytest.mark.parametrize("fault,phase,check", [
    ("visible", "describe_target", "visible"), ("enabled", "describe_target", "enabled"),
    ("password", "describe_target", "password"),
    ("value_readonly", "read_text", "value_readonly"), ("text_readonly", "read_text", "text_readonly"),
    ("resolve", "resolve_field", None),
])
def test_read_failure_records_exact_stage_without_private_text(monkeypatch, read_index, fault, phase, check):
    import json
    wrappers = []
    for index in (1, 2):
        wrapper = field(kind="ComboBox", role="combobox", value="PRIVATE_SENTINEL")
        wrapper.element_info.process_id = 20
        wrapper.element_info.rectangle = NS(left=20, top=30, right=120, bottom=55)
        wrapper.is_visible = lambda: True
        wrapper.is_enabled = lambda: True
        wrapper.top_level_parent = lambda: NS(element_info=NS(handle=10))
        if index == read_index:
            if fault == "visible": wrapper.is_visible = lambda: False
            elif fault == "enabled": wrapper.is_enabled = lambda: False
            elif fault == "password": wrapper.element_info.element.CurrentIsPassword = True
            elif fault == "value_readonly": wrapper.iface_value.CurrentIsReadOnly = True
            elif fault == "text_readonly": wrapper.iface_text.DocumentRange.GetAttributeValue = lambda _: True
            elif fault == "resolve":
                wrapper.element_info.control_type = "Button"
                wrapper.parent = lambda: None
        wrappers.append(wrapper)
    hits = iter(wrappers)
    reader = module.WindowsTextFieldReader(window_manager=None, native_identity_reader=None,
        desktop_factory=lambda **kw: NS(from_point=lambda *args: next(hits)))
    monkeypatch.setattr(reader, "_verify_binding", lambda *args: None)
    with pytest.raises(module.TextFieldReadError) as raised:
        reader.read_field(target_field_id="field", capture_id="fresh", target_window_handle=10,
            target_process_id=20, process_create_time=123.0, window_rect=(0,0,600,500),
            target_bbox=(50,40,1,1), click_point=(50,40))
    assert raised.value.reason_code == "text_field_target_not_writable"
    diagnostic = raised.value.to_reference()["diagnostic"]
    assert diagnostic["phase"] == phase
    assert diagnostic["read_index"] == read_index
    assert diagnostic.get("check") == check
    assert "PRIVATE_SENTINEL" not in json.dumps(raised.value.to_reference())


def test_error_diagnostic_rejects_non_whitelisted_data():
    error = module.TextFieldReadError("text_field_target_not_writable", diagnostic={
        "phase": "read_text", "read_index": 1, "check": "value_readonly",
        "value": "PRIVATE_SENTINEL", "name": "PRIVATE_SENTINEL", "attribute_state": "PRIVATE_SENTINEL"})
    assert error.to_reference() == {"reason_code": "text_field_target_not_writable", "diagnostic": {
        "phase": "read_text", "read_index": 1, "check": "value_readonly"}}


@pytest.mark.parametrize("kinds", [["Window"], ["Text", "Group", "Pane", "Window"],
    ["Button", "Group", "Pane", "Group", "Pane", "Window"], ["PRIVATE_SENTINEL", "Window"]])
def test_failed_resolve_reports_only_original_visited_types_without_extra_reads(kinds):
    visits = []
    parent_calls = []
    wrappers = []
    for index, kind in enumerate(kinds):
        class Info:
            handle = 10
            @property
            def control_type(self, index=index, kind=kind):
                visits.append(index)
                return kind
        wrapper = NS(element_info=Info())
        wrappers.append(wrapper)
    for index, wrapper in enumerate(wrappers):
        wrapper.top_level_parent = lambda: wrappers[-1]
        def parent(index=index):
            parent_calls.append(index)
            return wrappers[index+1]
        wrapper.parent = parent
    with pytest.raises(module.TextFieldReadError) as raised:
        module.WindowsTextFieldReader._resolve_field(wrappers[0], 10)
    expected_count = min(5, len(kinds))
    expected = [{"control_type": kind if kind != "PRIVATE_SENTINEL" else "other", "depth": index,
                 "is_root": index == len(kinds)-1} for index, kind in enumerate(kinds[:5])]
    assert raised.value.to_reference()["diagnostic"]["resolve_visits"] == expected
    assert visits == list(range(expected_count))
    assert parent_calls == list(range(expected_count-1))


def test_resolve_visits_projection_rejects_private_or_unbounded_payload():
    safe = {"control_type": "Pane", "depth": 0, "is_root": False}
    error = module.TextFieldReadError("text_field_target_not_writable", diagnostic={
        "resolve_visits": [{**safe, "name": "PRIVATE_SENTINEL"}]})
    assert error.to_reference()["diagnostic"]["resolve_visits"] == [safe]
    for invalid in ([{**safe, "control_type": "PRIVATE_SENTINEL"}], [safe]*6,
                    [{**safe, "depth": True}], [{**safe, "is_root": 1}]):
        error = module.TextFieldReadError("text_field_target_not_writable", diagnostic={"resolve_visits": invalid})
        assert "resolve_visits" not in error.to_reference().get("diagnostic", {})


@pytest.mark.parametrize("stage,clock_values,kind,expected_hits,expected_attempt,elapsed,matched,expected_waits", [
    ("before_sample", [0, .001, .01, .3], "Text", 1, 2, 300.0, False, 1),
    ("before_wait", [0, .001, .3], "Text", 1, 1, 300.0, False, 0),
    ("attempt_limit", [0]*23, "Text", 11, 11, 0.0, False, 10),
])
def test_hit_timeout_identifies_existing_deadline_without_more_sampling(monkeypatch, stage, clock_values,
    kind, expected_hits, expected_attempt, elapsed, matched, expected_waits):
    wrapper = field(kind=kind, role="combobox")
    wrapper.element_info.process_id = 20
    wrapper.element_info.rectangle = NS(left=20, top=30, right=120, bottom=55)
    wrapper.top_level_parent = lambda: NS(element_info=NS(handle=10))
    wrapper.is_visible = lambda: True
    wrapper.is_enabled = lambda: True
    wrapper.parent = lambda: None
    times = iter(clock_values)
    clocks, hits, waits = [], [], []
    def clock():
        clocks.append(True)
        return next(times)
    reader = module.WindowsTextFieldReader(window_manager=None, native_identity_reader=None,
        readiness_clock=clock, readiness_wait=waits.append)
    monkeypatch.setattr(reader, "_verify_binding", lambda *args: None)
    desktop = NS(from_point=lambda *args: hits.append(args) or wrapper)
    with pytest.raises(module.TextFieldReadError) as raised:
        reader._bound_field_hit(desktop, 50, 40, 10, 20, 123.0, (0,0,600,500), (20,30,100,25),
            ((42,1), "ComboBox"), allow_readiness=True)
    assert raised.value.reason_code == "text_field_hit_not_ready"
    assert raised.value.to_reference()["diagnostic"] == {"deadline_stage": stage, "attempt": expected_attempt,
        "elapsed_ms": elapsed, "matched": matched}
    assert len(hits) == expected_hits and len(clocks) == len(clock_values)
    assert len(waits) == expected_waits


def test_timeout_diagnostic_rejects_arbitrary_or_nonfinite_values():
    error = module.TextFieldReadError("text_field_hit_not_ready", diagnostic={"deadline_stage": "PRIVATE_SENTINEL",
        "attempt": True, "elapsed_ms": float("inf"), "matched": 1})
    assert error.to_reference() == {"reason_code": "text_field_hit_not_ready"}


@pytest.mark.parametrize("times", [[0, .001, .3], [0, .3, .4]])
def test_completed_valid_first_hit_is_not_discarded_by_elapsed_budget(monkeypatch, times):
    wrapper = field(kind="ComboBox", role="combobox")
    wrapper.element_info.process_id = 20
    wrapper.element_info.rectangle = NS(left=20, top=30, right=120, bottom=55)
    wrapper.top_level_parent = lambda: NS(element_info=NS(handle=10))
    clock = iter(times)
    hits, verifies, waits = [], [], []
    reader = module.WindowsTextFieldReader(window_manager=None, native_identity_reader=None,
        readiness_clock=lambda: next(clock), readiness_wait=waits.append)
    monkeypatch.setattr(reader, "_verify_binding", lambda *args: verifies.append(args))
    desktop = NS(from_point=lambda *args: hits.append(args) or wrapper)
    assert reader._bound_field_hit(desktop, 50, 40, 10, 20, 123.0, (0,0,600,500),
        (20,30,100,25), ((42,1), "ComboBox"), allow_readiness=True) is wrapper
    assert len(hits) == 1 and len(verifies) == 2 and waits == []


@pytest.mark.parametrize("fault", ["identity", "geometry", "process", "window", "post_binding"])
def test_late_wrong_hit_is_never_accepted(monkeypatch, fault):
    wrapper = field(kind="ComboBox", role="combobox")
    wrapper.element_info.process_id = 20
    wrapper.element_info.rectangle = NS(left=20, top=30, right=120, bottom=55)
    wrapper.top_level_parent = lambda: NS(element_info=NS(handle=11 if fault == "window" else 10))
    if fault == "identity": wrapper.element_info.runtime_id = [42, 99]
    if fault == "geometry": wrapper.element_info.rectangle.right = 121
    if fault == "process": wrapper.element_info.process_id = 21
    clock = iter([0, .3, .4])
    hits, verifies, waits = [], [], []
    def verify(*args):
        verifies.append(args)
        if fault == "post_binding" and len(verifies) == 2:
            raise module.TextFieldReadError("text_field_window_binding_changed")
    reader = module.WindowsTextFieldReader(window_manager=None, native_identity_reader=None,
        readiness_clock=lambda: next(clock), readiness_wait=waits.append)
    monkeypatch.setattr(reader, "_verify_binding", verify)
    desktop = NS(from_point=lambda *args: hits.append(args) or wrapper)
    with pytest.raises(module.TextFieldReadError) as raised:
        reader._bound_field_hit(desktop, 50, 40, 10, 20, 123.0, (0,0,600,500),
            (20,30,100,25), ((42,1), "ComboBox"), allow_readiness=True)
    assert raised.value.reason_code in {"text_field_expected_identity_changed", "text_field_window_or_process_changed",
                                        "text_field_window_binding_changed"}
    assert len(hits) == 1 and waits == []


def post_input_case(monkeypatch, *, new_box=(985,457,533,50), fault=None):
    wrappers = []
    for index in (1, 2):
        wrapper = field(kind="ComboBox", role="combobox", value="museum")
        wrapper.element_info.process_id = 20
        x, y, w, h = new_box
        if fault == "changing_geometry" and index == 2: w += 1
        wrapper.element_info.rectangle = NS(left=x, top=y, right=x+w, bottom=y+h)
        wrapper.element_info.element.CurrentHasKeyboardFocus = not (fault == "unfocused" or fault == "focus_second" and index == 2)
        wrapper.is_visible = lambda: True
        wrapper.is_enabled = lambda: True
        wrapper.top_level_parent = lambda: NS(element_info=NS(handle=10))
        if fault == "runtime" or fault == "runtime_second" and index == 2: wrapper.element_info.runtime_id = [42,99]
        if fault == "type": wrapper.element_info.control_type = "Edit"
        if fault == "readonly": wrapper.iface_value.CurrentIsReadOnly = True
        if fault == "process": wrapper.element_info.process_id = 21
        if fault == "value_change" and index == 2: wrapper.iface_value.CurrentValue = "changed"
        wrappers.append(wrapper)
    pending = iter(wrappers)
    monkeypatch.setattr(module, "_focused_field", lambda: next(pending), raising=False)
    reader = module.WindowsTextFieldReader(window_manager=None, native_identity_reader=None,
        desktop_factory=lambda **kw: NS(from_point=lambda *args: next(pending)))
    monkeypatch.setattr(reader, "_verify_binding", lambda *args: None)
    kwargs = dict(target_field_id="field", capture_id="fresh", target_window_handle=10,
        target_process_id=20, process_create_time=123.0, window_rect=(0,0,2560,1400),
        target_bbox=(985,457,453,50), click_point=(1100,480), require_keyboard_focus=True,
        expected_runtime_id=(42,1), expected_control_type="ComboBox")
    return reader, kwargs


@pytest.mark.parametrize("new_box", [(985,457,533,50), (985,457,373,50), (1010,457,453,50)])
def test_post_input_same_focused_field_can_rebind_stable_geometry(monkeypatch, new_box):
    reader, kwargs = post_input_case(monkeypatch, new_box=new_box)
    result = reader.read_field(**kwargs, allow_post_input_geometry_rebind=True)
    assert result.value == "museum" and result.identity.runtime_id == (42,1)
    assert result.identity.control_bbox == new_box


def test_original_strict_geometry_remains_default(monkeypatch):
    reader, kwargs = post_input_case(monkeypatch)
    with pytest.raises(module.TextFieldReadError, match="text_field_expected_identity_changed"):
        reader.read_field(**kwargs)


@pytest.mark.parametrize("fault", ["runtime", "runtime_second", "type", "unfocused", "focus_second", "readonly", "process", "changing_geometry", "value_change", "point_outside"])
def test_post_input_rebind_does_not_relax_identity_focus_or_stability(monkeypatch, fault):
    reader, kwargs = post_input_case(monkeypatch, fault=fault,
        new_box=(1200,457,373,50) if fault == "point_outside" else (985,457,533,50))
    with pytest.raises(module.TextFieldReadError):
        reader.read_field(**kwargs, allow_post_input_geometry_rebind=True)


@pytest.mark.parametrize("fault", ["missing_identity", "no_focus_requirement", "non_boolean"])
def test_post_input_rebind_requires_explicit_bound_focused_read(monkeypatch, fault):
    reader, kwargs = post_input_case(monkeypatch)
    enabled = True
    if fault == "missing_identity":
        kwargs.update(expected_runtime_id=None, expected_control_type=None)
    elif fault == "no_focus_requirement": kwargs["require_keyboard_focus"] = False
    else: enabled = 1
    with pytest.raises(module.TextFieldReadError, match="text_field_post_input_binding_invalid"):
        reader.read_field(**kwargs, allow_post_input_geometry_rebind=enabled)


def focused_overlay_case(monkeypatch, *, fault=None, fault_read=1):
    wrappers = []
    for index in (1, 2):
        wrapper = field(kind="Edit", value="", text="\ufffc")
        info = wrapper.element_info
        info.runtime_id = [42,5771270,4,7,1,5]
        wrapper.iface_text.DocumentRange.GetEnclosingElement().GetRuntimeId = lambda: [42,5771270,4,7,1,5]
        info.process_id = 20
        info.rectangle = NS(left=1017, top=412, right=1609, bottom=437)
        info.element.CurrentHasKeyboardFocus = True
        wrapper.is_visible = lambda: True
        wrapper.is_enabled = lambda: True
        wrapper.top_level_parent = lambda: NS(element_info=NS(handle=10))
        if index == fault_read:
            if fault == "runtime": info.runtime_id = [42,99]
            elif fault == "type": info.control_type = "ComboBox"
            elif fault == "process": info.process_id = 21
            elif fault == "window": wrapper.top_level_parent = lambda: NS(element_info=NS(handle=99))
            elif fault == "geometry": info.rectangle.right += 10
            elif fault == "unfocused": info.element.CurrentHasKeyboardFocus = False
            elif fault == "unknown_focus": info.element.CurrentHasKeyboardFocus = None
            elif fault == "invisible": wrapper.is_visible = lambda: False
            elif fault == "disabled": wrapper.is_enabled = lambda: False
            elif fault == "password": info.element.CurrentIsPassword = True
            elif fault == "readonly": wrapper.iface_value.CurrentIsReadOnly = True
        wrappers.append(wrapper)
    calls = []
    overlay = NS(element_info=NS(control_type="Pane", process_id=20,
        rectangle=NS(left=1047, top=433, right=1385, bottom=706), element=NS(CurrentProcessId=20)),
        top_level_parent=lambda: NS(element_info=NS(handle=10)), parent=lambda: None)
    def hit(*args):
        calls.append("hit")
        return overlay
    pending = iter(wrappers)
    def focused():
        calls.append("focused")
        return next(pending)
    monkeypatch.setattr(module, "_focused_field", focused, raising=False)
    reader = module.WindowsTextFieldReader(window_manager=None, native_identity_reader=None,
        desktop_factory=lambda **kw: NS(from_point=hit))
    monkeypatch.setattr(reader, "_verify_binding", lambda *args: calls.append("binding"))
    kwargs = dict(target_field_id="field", capture_id="fresh", target_window_handle=10,
        target_process_id=20, process_create_time=123.0, window_rect=(879,80,800,1155),
        target_bbox=(138,332,592,25), click_point=(401,354), require_keyboard_focus=True,
        expected_runtime_id=(42,5771270,4,7,1,5), expected_control_type="Edit")
    return reader, kwargs, calls


def test_bound_focused_read_ignores_post_click_overlay_without_new_hit_authority(monkeypatch):
    reader, kwargs, calls = focused_overlay_case(monkeypatch)
    result = reader.read_field(**kwargs)
    assert result.value == "" and result.identity.control_bbox == (138,332,592,25)
    assert result.identity.window_rect == (879,80,800,1155)
    assert calls.count("focused") == 2 and "hit" not in calls


@pytest.mark.parametrize("fault", ["runtime", "type", "process", "window", "geometry", "unfocused",
    "unknown_focus", "invisible", "disabled", "password", "readonly"])
@pytest.mark.parametrize("fault_read", [1, 2])
def test_bound_focused_read_never_relaxes_field_contract(monkeypatch, fault, fault_read):
    reader, kwargs, calls = focused_overlay_case(monkeypatch, fault=fault, fault_read=fault_read)
    with pytest.raises(module.TextFieldReadError):
        reader.read_field(**kwargs)
    assert calls.count("focused") == fault_read and "hit" not in calls


@pytest.mark.parametrize("mode", ["pixel", "no_focus_requirement", "pre_click_hit"])
def test_unbound_and_pre_click_paths_still_require_point_hit(monkeypatch, mode):
    reader, kwargs, calls = focused_overlay_case(monkeypatch)
    if mode == "pixel": kwargs.update(expected_runtime_id=None, expected_control_type=None)
    elif mode == "no_focus_requirement": kwargs["require_keyboard_focus"] = False
    else: kwargs.pop("require_keyboard_focus")
    with pytest.raises(module.TextFieldReadError):
        (reader.observe_field_hit if mode == "pre_click_hit" else reader.read_field)(**kwargs)
    assert "hit" in calls and "focused" not in calls


@pytest.mark.parametrize("missing", [False, True])
def test_focused_element_com_boundary_only_wraps_observed_current_element(monkeypatch, missing):
    import sys
    raw, info, wrapper = object(), object(), object()
    calls = []
    monkeypatch.setitem(sys.modules, "pywinauto.uia_defines", NS(IUIA=lambda: NS(iuia=NS(
        GetFocusedElement=lambda: calls.append("focused") or (None if missing else raw)))))
    monkeypatch.setitem(sys.modules, "pywinauto.uia_element_info", NS(UIAElementInfo=lambda element:
        calls.append(("info", element)) or info))
    monkeypatch.setitem(sys.modules, "pywinauto.controls.uiawrapper", NS(UIAWrapper=lambda element_info:
        calls.append(("wrapper", element_info)) or wrapper))
    if missing:
        with pytest.raises(module.TextFieldReadError, match="text_field_keyboard_focus_unavailable"):
            module._focused_field()
        assert calls == ["focused"]
    else:
        assert module._focused_field() is wrapper
        assert calls == ["focused", ("info", raw), ("wrapper", info)]


def test_focused_provider_failure_is_sanitized_without_point_fallback(monkeypatch):
    reader, kwargs, calls = focused_overlay_case(monkeypatch)
    def failed():
        raise RuntimeError("private provider text")
    monkeypatch.setattr(module, "_focused_field", failed)
    with pytest.raises(module.TextFieldReadError) as failure:
        reader.read_field(**kwargs)
    assert failure.value.reason_code == "text_field_provider_unavailable"
    assert failure.value.diagnostic == {"phase": "resolve_field", "read_index": 1}
    assert "hit" not in calls
