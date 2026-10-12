"""复合字段只换到同帧唯一真实 Edit，仍须通过原只读命中守卫。"""
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace as NS

import pytest
from PIL import Image

from app.api import vision
from app.core import local_text_focus
from app.core.local_recognition_policy import local_recognition_selection
from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
from modules.ocr.contracts import OCRResult


GOAL = ("The long empty folder path address input at the top of the application, "
        "directly below the toolbar and above the file list. Enter the test directory here.")
POINT = {"x": 256, "y": 77}
PARENT_BOX = {"x": 33, "y": 74, "w": 2527, "h": 26}
CHILD_BOX = {"x": 57, "y": 79, "w": 2483, "h": 17}
CHILD_POINT = {"x": 1298, "y": 87}


def controls():
    return [
        dict(control_id="combo", runtime_id=[42, 100], name=None, control_type="ComboBox",
             bbox=dict(PARENT_BOX), enabled=True, visible=True, patterns=["Value", "ExpandCollapse"],
             ancestor_control_ids=["pane", "window"]),
        dict(control_id="edit", runtime_id=[42, 101], name=None, control_type="Edit",
             bbox=dict(CHILD_BOX), enabled=True, visible=True, patterns=["Value"],
             ancestor_control_ids=["combo", "pane", "window"]),
    ]


def binding():
    return dict(runtime_id=[42, 101], control_type="Edit", bbox=[57, 79, 2483, 17],
                window_handle=10, process_id=20, process_create_time=123.0,
                window_rect=[0, 23, 2560, 1377])


def fixture(tmp_path, monkeypatch, *, items=None, point=None, complete=True, hit=None, source_window=None, metadata=None):
    image = tmp_path / "current.png"
    Image.new("RGB", (2560, 1377), "white").save(image)
    snapshot = dict(status="ok", scan_complete=complete, truncated=not complete,
                    scan_scope="bound_window", controls=items if items is not None else controls(),
                    window=source_window or dict(handle=10, process_id=20, bbox=dict(x=0, y=0, w=2560, h=1377)))
    model_point = dict(point or POINT)
    monkeypatch.setattr(vision, "_call_vista_point_prompt", lambda **kw: {
        "point": model_point.copy(), "provider": "isolated-model-boundary"})
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda path: OCRResult(image_path=str(path), matches=[]))
    manager = NS(get_bound_window=lambda: NS(handle=10, process_id=20,
        rect=NS(left=0, top=23, right=2560, bottom=1400)))
    monkeypatch.setattr("app.core.window_manager.window_manager", manager)
    monkeypatch.setattr(local_text_focus, "require_local_operator_input", lambda manager: True)
    monkeypatch.setattr("app.core.local_input_policy.current_local_operator_identity", lambda manager:
        dict(target_window_handle=10, process_id=20, process_create_time=123.0))
    calls = []
    def probe(manager, handle, pid, point, **kwargs):
        calls.append((point, kwargs))
        if isinstance(hit, Exception):
            raise hit
        return deepcopy(hit if hit is not None else binding())
    monkeypatch.setattr(local_text_focus, "probe_local_focus_target", probe)
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(image), task="locate_element", goal=GOAL,
        agent_mode="execute", provider_mode="local_grounding", top_k=5,
        metadata=metadata or {},
        write_policy={"path_graph": False, "element_memory": False, "trace": False})
    def recognize():
        with pinned_uia_snapshot(snapshot), pinned_runtime_output_root(tmp_path):
            return vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
                config={"vision": {"mode": "local_grounding"}},
                local_config={"model_name": "isolated", "endpoint": "http://unused.invalid"},
                image_path=image, input_image_size=vision.ImageSize(width=2560, height=1377), goal=GOAL,
                observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []}).data["result"]
    return image, calls, recognize, manager


def test_recorded_parent_border_is_resolved_before_selection_and_rechecked_before_input(tmp_path, monkeypatch):
    image, calls, recognize, manager = fixture(tmp_path, monkeypatch)
    target = local_text_focus.LocalTextFocusTarget(10, 20)
    with local_text_focus.local_text_focus_scope(target):
        plan = recognize()
        chosen = plan["recommended_target"]
        assert chosen["element"]["bbox"] == CHILD_BOX
        evidence = chosen["element"]["evidence"]["current_composite_field_target"]
        assert evidence["raw_model_point"] == POINT
        assert evidence["point"] == CHILD_POINT
        assert evidence["parent"]["runtime_id"] == [42, 100]
        assert evidence["child"]["runtime_id"] == [42, 101]
        assert evidence["capture_id"] == str(image.resolve())
        assert evidence["screenshot_sha256"] == sha256(image.read_bytes()).hexdigest()
        assert evidence["binding"] == binding()
        assert plan["pre_click_decision"]["contract_version"] == "pre_click_decision_v1"
        selected = local_recognition_selection(plan, image_path=image, viewport_size={"width": 2560, "height": 1377})
        assert selected["selected_click_point"] == CHILD_POINT
        assert len(calls) == 1
        local_text_focus.check_local_text_focus(CHILD_POINT, manager)
        assert len(calls) == 2
        assert target.binding == binding()
    assert not local_text_focus.has_local_text_focus()
    assert local_text_focus.check_local_text_focus(CHILD_POINT, manager) is None


def test_ordinary_click_never_inherits_composite_resolution(tmp_path, monkeypatch):
    image, calls, recognize, _ = fixture(tmp_path, monkeypatch,
        metadata={"current_composite_field_target": {"binding": binding(), "point": CHILD_POINT}})
    plan = recognize()
    assert plan["recommended_target"]["element"]["click_point"] == POINT
    assert "current_composite_field_target" not in plan["recommended_target"]["element"]["evidence"]
    assert calls == []


@pytest.mark.parametrize("fault", ["window", "process", "geometry"])
def test_old_source_window_identity_is_not_rebound_to_current_window(fault, tmp_path, monkeypatch):
    source = dict(handle=10, process_id=20, bbox=dict(x=0, y=0, w=2560, h=1377))
    if fault == "window": source["handle"] = 11
    elif fault == "process": source["process_id"] = 21
    else: source["bbox"]["w"] -= 1
    image, calls, recognize, _ = fixture(tmp_path, monkeypatch, source_window=source)
    with local_text_focus.local_text_focus_scope(local_text_focus.LocalTextFocusTarget(10, 20)):
        plan = recognize()
        with pytest.raises(ValueError):
            local_recognition_selection(plan, image_path=image, viewport_size={"width": 2560, "height": 1377})
    assert calls == []


@pytest.mark.parametrize("reason", ["text_field_target_not_writable", "text_field_window_or_process_changed",
    "text_field_process_identity_changed", "text_field_identity_unavailable"])
def test_current_probe_failure_remains_explicit_and_never_selects_original_parent(reason, tmp_path, monkeypatch):
    from app.agent.windows_text_field_reader import TextFieldReadError
    image, calls, recognize, _ = fixture(tmp_path, monkeypatch, hit=TextFieldReadError(reason))
    with local_text_focus.local_text_focus_scope(local_text_focus.LocalTextFocusTarget(10, 20)):
        plan = recognize()
        assert plan["candidate_result"]["summary"]["vista_direct_current_uia_identity_rejection"] == reason
        with pytest.raises(ValueError):
            local_recognition_selection(plan, image_path=image, viewport_size={"width": 2560, "height": 1377})
    assert len(calls) == 1


def test_model_point_already_in_edit_keeps_original_point_path(tmp_path, monkeypatch):
    accurate = {"x": 256, "y": 87}
    image, calls, recognize, manager = fixture(tmp_path, monkeypatch, point=accurate)
    with local_text_focus.local_text_focus_scope(local_text_focus.LocalTextFocusTarget(10, 20)):
        plan = recognize()
        assert plan["recommended_target"]["element"]["click_point"] == accurate
        assert "current_composite_field_target" not in plan["recommended_target"]["element"]["evidence"]
        assert calls == []
        local_text_focus.check_local_text_focus(accurate, manager)
    assert len(calls) == 1 and calls[0][0] == (256, 87)


def test_exception_revokes_composite_scope_and_later_ordinary_click_is_unchanged(tmp_path, monkeypatch):
    _, calls, recognize, _ = fixture(tmp_path, monkeypatch)
    target = local_text_focus.LocalTextFocusTarget(10, 20)
    with pytest.raises(RuntimeError, match="interrupted"):
        with local_text_focus.local_text_focus_scope(target):
            recognize()
            raise RuntimeError("interrupted")
    assert not local_text_focus.has_local_text_focus()
    assert target.composite_binding is None
    assert recognize()["recommended_target"]["element"]["click_point"] == POINT
    assert len(calls) == 1


def test_candidate_eligibility_failure_after_binding_is_closed_and_scope_is_revoked(tmp_path, monkeypatch):
    image, calls, recognize, _ = fixture(tmp_path, monkeypatch)
    original_rank = vision.rank_candidates
    def rank(request):
        if request.page_structure.screen_summary == "current composite field child":
            return NS(candidates=[])
        return original_rank(request)
    monkeypatch.setattr(vision, "rank_candidates", rank)
    target = local_text_focus.LocalTextFocusTarget(10, 20)
    with local_text_focus.local_text_focus_scope(target):
        plan = recognize()
        assert target.composite_binding is not None
        assert plan["candidate_result"]["summary"]["vista_direct_current_uia_identity_rejection"] == "composite_field_current_candidate_not_eligible"
        with pytest.raises(ValueError):
            local_recognition_selection(plan, image_path=image, viewport_size={"width": 2560, "height": 1377})
    assert target.composite_binding is None and len(calls) == 1


def test_source_capture_change_during_final_probe_is_rejected(tmp_path, monkeypatch):
    image, _, recognize, manager = fixture(tmp_path, monkeypatch)
    with local_text_focus.local_text_focus_scope(local_text_focus.LocalTextFocusTarget(10, 20)):
        recognize()
        def changed(*args, **kwargs):
            image.write_bytes(b"changed during final probe")
            return binding()
        monkeypatch.setattr(local_text_focus, "probe_local_focus_target", changed)
        with pytest.raises(ValueError, match="source_capture_changed"):
            local_text_focus.check_local_text_focus(CHILD_POINT, manager)


@pytest.mark.parametrize("variant", ["two_children", "no_parent", "disabled", "unknown_enabled", "readonly",
    "overlay", "incomplete", "duplicate_rid", "outside_parent"])
def test_unproven_composite_never_dispatches_an_adjusted_or_original_point(variant, tmp_path, monkeypatch):
    items = controls()
    complete = True
    if variant == "two_children":
        extra = deepcopy(items[1]); extra.update(control_id="second", runtime_id=[42, 102]); items.append(extra)
    elif variant == "no_parent": items[1]["ancestor_control_ids"] = ["pane", "window"]
    elif variant == "disabled": items[1]["enabled"] = False
    elif variant == "unknown_enabled": items[1]["enabled"] = None
    elif variant == "readonly": items[1]["is_read_only"] = True
    elif variant == "overlay":
        items.append(dict(control_id="overlay", runtime_id=[42, 103], name="Other", control_type="Button",
            bbox=dict(CHILD_BOX), enabled=True, visible=True, patterns=["Invoke"], ancestor_control_ids=[]))
    elif variant == "incomplete": complete = False
    elif variant == "duplicate_rid": items[0]["runtime_id"] = items[1]["runtime_id"][:]
    elif variant == "outside_parent": items[1]["bbox"]["y"] = 100
    image, calls, recognize, _ = fixture(tmp_path, monkeypatch, items=items, complete=complete)
    with local_text_focus.local_text_focus_scope(local_text_focus.LocalTextFocusTarget(10, 20)):
        plan = recognize()
        with pytest.raises(ValueError):
            local_recognition_selection(plan, image_path=image, viewport_size={"width": 2560, "height": 1377})
    assert calls == []


@pytest.mark.parametrize("changed", ["rid", "bbox", "birth", "parent_point", "image"])
def test_bound_child_change_or_original_parent_point_is_rejected_before_input(changed, tmp_path, monkeypatch):
    from app.agent.windows_text_field_reader import TextFieldReadError
    image, calls, recognize, manager = fixture(tmp_path, monkeypatch)
    with local_text_focus.local_text_focus_scope(local_text_focus.LocalTextFocusTarget(10, 20)):
        recognize()
        actual = binding()
        if changed == "rid": actual["runtime_id"] = [42, 999]
        elif changed == "bbox": actual["bbox"][0] += 1
        elif changed == "birth": actual["process_create_time"] += 1
        elif changed == "image": image.write_bytes(b"changed")
        monkeypatch.setattr(local_text_focus, "probe_local_focus_target", lambda *args, **kw: actual)
        with pytest.raises((ValueError, TextFieldReadError)):
            local_text_focus.check_local_text_focus(POINT if changed == "parent_point" else CHILD_POINT, manager)


class NoPattern(Exception):
    pass


class ValueWithoutText:
    CurrentIsReadOnly = False

    @property
    def CurrentValue(self):
        raise AssertionError("probe must not read field values")


class NativeField:
    def __init__(self, kind, rid, box, *, parent=None, hwnd=0):
        self.element_info = NS(control_type=kind, runtime_id=rid, handle=hwnd, process_id=20,
            rectangle=NS(left=box[0], top=box[1]+23, right=box[0]+box[2], bottom=box[1]+box[3]+23),
            element=NS(CurrentIsPassword=False, CurrentProcessId=20))
        self._parent = parent
        self.iface_value = ValueWithoutText()
        self.visible = True
        self.enabled = True

    @property
    def iface_text(self):
        raise NoPattern()

    def parent(self): return self._parent
    def is_visible(self): return self.visible
    def is_enabled(self): return self.enabled


def native_fixture(monkeypatch):
    from app.agent import windows_text_field_reader as reader
    window = NativeField("Window", [42, 10], (0, 0, 2560, 1377), hwnd=10)
    parent = NativeField("ComboBox", [42, 100], (33, 74, 2527, 26), parent=window, hwnd=100)
    child = NativeField("Edit", [42, 101], (57, 79, 2483, 17), parent=parent, hwnd=101)
    manager = NS(get_bound_window=lambda: NS(handle=10, process_id=20,
        rect=NS(left=0, top=23, right=2560, bottom=1400)))
    monkeypatch.setattr(reader, "_no_pattern_exception", lambda: NoPattern)
    monkeypatch.setattr(reader, "_native_root_handle", lambda hwnd: 10 if hwnd in (10, 100, 101) else None)
    monkeypatch.setattr(reader, "_desktop_factory", lambda **kw: NS(from_point=lambda x, y: child if y >= 102 else parent))
    fact = dict(contract_version="windows_native_identity_observation_v1", provider="windows_native_identity",
        status="observed", target_window_handle=10, process_id=20, process_create_time=123.0,
        executable_path="C:/isolated/application.exe")
    monkeypatch.setattr(reader, "WindowsNativeIdentityReader", lambda **kw: NS(read_identity=lambda h: fact))
    return reader, manager, parent, child


def test_real_common_probe_retains_parent_refusal_and_binds_edit_without_reading_value(monkeypatch):
    reader, manager, _, _ = native_fixture(monkeypatch)
    with pytest.raises(reader.TextFieldReadError) as raised:
        reader.probe_local_focus_target(manager, 10, 20, (256, 77))
    assert raised.value.reason_code == "text_field_target_not_writable"
    assert raised.value.diagnostic["check"] == "text_pattern_missing"
    actual = reader.probe_local_focus_target(manager, 10, 20, (1298, 87), expected_ancestor=controls()[0])
    assert actual == binding()


def test_recognition_uses_real_common_probe_then_original_sequence_binding(tmp_path, monkeypatch):
    from app.execution.input_sequence import _focus_field_binding
    image, _, recognize, _ = fixture(tmp_path, monkeypatch)
    reader, manager, _, _ = native_fixture(monkeypatch)
    monkeypatch.setattr(local_text_focus, "probe_local_focus_target", reader.probe_local_focus_target)
    monkeypatch.setattr("app.core.window_manager.window_manager", manager)
    target = local_text_focus.LocalTextFocusTarget(10, 20)
    with local_text_focus.local_text_focus_scope(target):
        plan = recognize()
        selected = local_recognition_selection(plan, image_path=image, viewport_size={"width": 2560, "height": 1377})
        local_text_focus.check_local_text_focus(selected["selected_click_point"], manager)
        located = dict(recognition_plan=plan, selected_click_point=selected["selected_click_point"],
            selected_click_point_coordinate_space="capture_image_pixels",
            live_capture=dict(image_path=str(image), window_size=dict(width=2560, height=1377)))
        receipt = dict(target_identity=dict(contract_version="windows_native_identity_observation_v1",
            provider="windows_native_identity", status="observed", target_window_handle=10, process_id=20,
            process_create_time=123.0, executable_path="C:/isolated/application.exe"),
            target_window_geometry=dict(coordinate_space="screen_pixels", rect_format="ltrb", rect=[0, 23, 2560, 1400]))
        actual = _focus_field_binding(located, receipt, {"handle": 10, "process_id": 20})
        assert actual["runtime_id"] == [42, 101]
        assert actual["control_type"] == "Edit"
        assert actual["bbox"] == CHILD_BOX
        assert actual["source_control_id"] == "edit"
        assert target.binding == binding()


def test_focus_completed_then_identity_drift_blocks_keyboard_and_preserves_focus_fact(tmp_path, monkeypatch):
    from app.execution import input_sequence
    from app.agent.windows_text_field_reader import TextFieldReadError
    image, _, recognize, manager = fixture(tmp_path, monkeypatch)
    class Coordinator:
        def __init__(self): self.calls = []
        def execute_local_step(self, **kwargs):
            self.calls.append(kwargs["operation"])
            assert kwargs["operation"] == "execute_recognition_plan"
            with local_text_focus.local_text_focus_scope(kwargs["focus_target"]):
                plan = recognize()
                local_text_focus.check_local_text_focus(CHILD_POINT, manager)
            capture = dict(image_path=str(image), sha256=sha256(image.read_bytes()).hexdigest(),
                window_size=dict(width=2560, height=1377))
            return dict(target_identity=dict(contract_version="windows_native_identity_observation_v1",
                provider="windows_native_identity", status="observed", target_window_handle=10, process_id=20,
                process_create_time=123.0, executable_path="C:/isolated/application.exe"),
                target_window_geometry=dict(coordinate_space="screen_pixels", rect_format="ltrb", rect=[0, 23, 2560, 1400]),
                response=dict(success=True, data=dict(result=dict(recognition_plan=plan, live_capture=capture,
                    selected_click_point=dict(CHILD_POINT), selected_click_point_coordinate_space="capture_image_pixels",
                    execution_path=dict(action_executed=True)))),
                observation=dict(status="captured", capture=capture))
    def stale(*args, **kwargs): raise TextFieldReadError("text_field_expected_identity_changed")
    monkeypatch.setattr(input_sequence, "_read_field", stale)
    coordinator = Coordinator()
    result = input_sequence.run_input_sequence(coordinator, {"handle": 10, "process_id": 20},
        {"field_goal": GOAL, "text": "fresh directory", "submit_search": False})
    assert result["status"] == "interrupted"
    assert result["error"]["code"] == "text_field_expected_identity_changed"
    assert result["phase"] == "check_focus"
    assert result["action_executed"] is True
    assert result["steps"][0]["action_executed"] is True
    assert coordinator.calls == ["execute_recognition_plan"]


@pytest.mark.parametrize("fault", ["readonly", "unknown_readonly", "password", "unknown_password", "hidden",
    "disabled", "unknown_enabled", "parent_rid", "parent_box", "parent_pid", "no_parent", "cycle", "overlay"])
def test_real_common_probe_refuses_invalid_child_or_current_parent(fault, monkeypatch):
    reader, manager, parent, child = native_fixture(monkeypatch)
    if fault == "readonly": child.iface_value.CurrentIsReadOnly = True
    elif fault == "unknown_readonly": child.iface_value.CurrentIsReadOnly = None
    elif fault == "password": child.element_info.element.CurrentIsPassword = True
    elif fault == "unknown_password": child.element_info.element.CurrentIsPassword = None
    elif fault == "hidden": child.visible = False
    elif fault == "disabled": child.enabled = False
    elif fault == "unknown_enabled": child.enabled = object()
    elif fault == "parent_rid": parent.element_info.runtime_id = [42, 999]
    elif fault == "parent_box": parent.element_info.rectangle.left += 1
    elif fault == "parent_pid": parent.element_info.process_id = 21
    elif fault == "no_parent": child._parent = parent.parent()
    elif fault == "cycle": child._parent = child
    elif fault == "overlay":
        reader._desktop_factory = lambda **kw: NS(from_point=lambda x, y: parent)
    with pytest.raises(reader.TextFieldReadError):
        reader.probe_local_focus_target(manager, 10, 20, (1298, 87), expected_ancestor=controls()[0])
