"""几何拒绝仅补同次读取诊断，不改变定位、等待或放行。"""
import json
from types import SimpleNamespace as NS

import pytest

from app.agent import windows_text_field_reader as module


WINDOW = (18, 10, 1249, 1372)
POINT = (550, 59)
TARGET = (*POINT, 1, 1)


def wrapper(rectangle):
    return NS(element_info=NS(control_type="Edit", runtime_id=[42, 1], rectangle=rectangle,
        element=NS(CurrentIsPassword=False, CurrentName="PRIVATE_FIELD_NAME",
            CurrentHasKeyboardFocus=True)), is_visible=lambda: True, is_enabled=lambda: True)


def rectangle(raw):
    return NS(**dict(zip(("left", "top", "right", "bottom"), raw)))


def describe(field, target=TARGET, *, focused_binding=None):
    reader = module.WindowsTextFieldReader(window_manager=None, native_identity_reader=None)
    return module._read_stage_call("describe_target", 1, reader._describe_target,
        field, 10, 20, WINDOW, target, POINT, focused_binding=focused_binding)


@pytest.mark.parametrize("raw,target,binding,branch,normalized", [
    ((142, 58, 142, 82), TARGET, None, "invalid_rect", [124, 48, 0, 24]),
    ((17, 58, 1023, 82), TARGET, None, "outside_window", [-1, 48, 1006, 24]),
    ((700, 58, 1023, 82), TARGET, None, "point_outside", [682, 48, 323, 24]),
    ((142, 58, 1023, 82), (100, 48, 1000, 24), None, "target_not_contained", [124, 48, 881, 24]),
    ((142, 58, 1023, 82), (124, 48, 885, 24), ((42, 1), "Edit"),
        "focused_geometry_mismatch", [124, 48, 881, 24]),
])
def test_geometry_refusal_preserves_exact_coordinate_contract(raw, target, binding, branch, normalized):
    with pytest.raises(module.TextFieldReadError, match="^text_field_geometry_changed$") as caught:
        describe(wrapper(rectangle(raw)), target, focused_binding=binding)
    diagnostic = caught.value.to_reference()["diagnostic"]
    assert diagnostic["phase"] == "describe_target" and diagnostic["read_index"] == 1
    geometry = diagnostic["geometry"]
    assert geometry["failure_branch"] == branch
    assert geometry["window_rect"] == list(WINDOW) and geometry["window_rect_format"] == "xywh"
    assert geometry["click_point"] == list(POINT) and geometry["target_bbox"] == list(target)
    assert geometry["raw_screen_rect"] == list(raw) and geometry["raw_screen_rect_format"] == "ltrb"
    assert geometry["normalized_bbox"] == normalized
    assert geometry["control_type"] == "Edit"
    assert "PRIVATE_FIELD_NAME" not in json.dumps(diagnostic)


def test_refusal_diagnostic_never_reloads_rectangle_or_its_edges():
    class Edges:
        def __init__(self):
            self.reads = []

        def __getattr__(self, name):
            assert name not in self.reads
            self.reads.append(name)
            return dict(left=700, top=58, right=1023, bottom=82)[name]

    edges = Edges()
    original = wrapper(edges)

    class Info:
        def __init__(self):
            self.reads = 0

        def __getattr__(self, name):
            return getattr(original.element_info, name)

        @property
        def rectangle(self):
            self.reads += 1
            assert self.reads == 1
            return edges

    field = NS(element_info=Info(), is_visible=original.is_visible, is_enabled=original.is_enabled)
    with pytest.raises(module.TextFieldReadError) as caught:
        describe(field)
    assert caught.value.diagnostic["geometry"]["raw_screen_rect"] == [700, 58, 1023, 82]
    assert field.element_info.reads == 1 and edges.reads == ["left", "top", "right", "bottom"]


def test_missing_or_throwing_rectangle_still_reports_original_refusal():
    class BrokenEdges:
        @property
        def left(self):
            raise RuntimeError("PRIVATE_COM_MESSAGE")

    with pytest.raises(module.TextFieldReadError, match="^text_field_geometry_changed$") as caught:
        describe(wrapper(BrokenEdges()))
    geometry = caught.value.diagnostic["geometry"]
    assert geometry["failure_branch"] == "invalid_rect"
    assert "raw_screen_rect" not in geometry and "normalized_bbox" not in geometry
    assert "PRIVATE_COM_MESSAGE" not in json.dumps(caught.value.to_reference())


def test_geometry_diagnostic_failure_never_replaces_original_refusal(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("PRIVATE_DIAGNOSTIC_MESSAGE")

    monkeypatch.setattr(module, "_geometry_failure_diagnostic", broken, raising=False)
    with pytest.raises(module.TextFieldReadError, match="^text_field_geometry_changed$") as caught:
        describe(wrapper(rectangle((700, 58, 1023, 82))))
    assert "PRIVATE_DIAGNOSTIC_MESSAGE" not in json.dumps(caught.value.to_reference())


def test_geometry_diagnostic_white_list_rejects_text_objects_and_unbounded_numbers():
    value = module.TextFieldReadError("text_field_geometry_changed", diagnostic={"geometry": {
        "contract_version": "text_field_geometry_diagnostic.v1", "failure_branch": "point_outside",
        "window_rect": WINDOW, "click_point": (True, 59), "target_bbox": (0, 0, 2**40, 24),
        "raw_screen_rect": object(), "normalized_bbox": (124, 48, 881, 24),
        "control_type": "PRIVATE_CONTROL_NAME", "name": "PRIVATE_FIELD_NAME", "value": "PRIVATE_VALUE"}})
    geometry = value.to_reference()["diagnostic"]["geometry"]
    assert geometry["window_rect"] == list(WINDOW)
    assert "click_point" not in geometry and "target_bbox" not in geometry and "raw_screen_rect" not in geometry
    assert geometry["control_type"] == "other"
    assert "PRIVATE_" not in json.dumps(value.to_reference())


def test_valid_geometry_keeps_result_and_does_not_build_failure_diagnostic(monkeypatch):
    monkeypatch.setattr(module, "_top_window_handle", lambda _: 10)
    monkeypatch.setattr(module, "_process_id", lambda *args: 20)
    monkeypatch.setattr(module, "_geometry_failure_diagnostic", lambda *args, **kwargs:
        pytest.fail("有效字段不得构建拒绝诊断"), raising=False)
    result = describe(wrapper(rectangle((142, 58, 1023, 82))))
    assert result == {"runtime_id": (42, 1), "control_bbox": (124, 48, 881, 24), "control_type": "Edit"}
