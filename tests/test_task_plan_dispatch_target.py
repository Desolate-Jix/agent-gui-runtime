"""结构化目标定位后被替换的真实门控调用回归；只隔离 UIA、原生身份与输入设备。"""
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest

from tests.test_task_plan_target import control, current_frame


TARGET = {"name": "Find", "control_type": "Button",
    "container": {"name": "Search form", "control_type": "Pane"}}


class NoPattern(Exception):
    pass


class ReadOnlyPattern:
    CurrentIsReadOnly = False
    @property
    def CurrentValue(self):
        pytest.fail("最终命中校验不得读取字段值")


def private_text(*args):
    pytest.fail("最终命中校验不得调用 GetText")


def wrapper(raw, *, parent=None):
    box = raw["screen_bbox"]
    x, y, w, h = (box[k] for k in ("x", "y", "w", "h"))
    result = NS(element_info=NS(handle=0, runtime_id=list(raw["runtime_id"]), control_type=raw["control_type"],
        name=raw["name"], process_id=22, rectangle=NS(left=x, top=y, right=x+w, bottom=y+h),
        element=NS(CurrentProcessId=22, CurrentIsPassword=False)),
        is_visible=lambda: True, is_enabled=lambda: True, iface_invoke=object(), parent=lambda: parent)
    if raw["control_type"] in {"Edit", "ComboBox"}:
        result.iface_value = ReadOnlyPattern()
        result.iface_text = NS(DocumentRange=NS(GetAttributeValue=lambda _: False, GetText=private_text))
    return result


def run_scene(current_frame, monkeypatch, defect=None, *, structured=True, kind="Button"):
    from app.api import action, vision
    from app.api.models.request import ExecuteRecognitionPlanRequest
    from app.agent import windows_control_hit_reader as hits, windows_text_field_reader as text
    from app.core.local_input_policy import _local_operator_input_scope
    from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
    from modules.ocr.contracts import OCRResult
    capture, snapshot = current_frame
    snapshot["controls"] = [control("form", "Search form", "Pane", (10, 10, 250, 190)),
        control("find", "Find", kind, (40, 80, 120, 40), ancestors=("form",),
            patterns=["Value", "Text"] if kind in {"Edit", "ComboBox"} else [])]
    target = {**TARGET, "control_type": kind}
    root = NS(element_info=NS(handle=11, process_id=22), parent=lambda: None)
    parent = wrapper(snapshot["controls"][0], parent=root)
    current = wrapper(snapshot["controls"][1], parent=parent)
    state = {"raw": current}
    identity = {"contract_version": "windows_native_identity_observation_v1", "provider": "windows_native_identity",
        "status": "observed", "target_window_handle": 11, "process_id": 22,
        "process_create_time": 123.0, "executable_path": "c:/fixture/editor.exe"}
    bound = NS(handle=11, process_id=22, title="Fixture", process_name="editor.exe",
        rect=NS(left=100, top=200, right=1000, bottom=800))
    manager = NS(get_bound_window=lambda: bound)
    monkeypatch.setattr(action, "window_manager", manager)
    monkeypatch.setattr(action.screenshot_service, "capture_window", lambda **kw:
        {"image_path": capture["image_path"], "window_size": capture["image_size"], "roi": None})
    monkeypatch.setattr(vision.VisionProviderFactory, "load_config", lambda: {"vision": {"mode": "local_grounding"}})
    monkeypatch.setattr(vision.VisionProviderFactory, "create", lambda **kw: object())
    monkeypatch.setattr(vision, "_selected_local_vision_config", lambda *args: {"model_name": "isolated"})
    monkeypatch.setattr(vision, "_uses_vista_point_grounding", lambda config: True)
    monkeypatch.setattr(vision, "_call_vista_point_prompt", lambda **kw:
        {"point": {"x": 100, "y": 100}, "provider": "isolated-model-boundary"})
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda path: OCRResult(image_path=str(path), matches=[]))
    native_reads, clicks = [], []
    def from_point(x, y):
        native_reads.append((x, y))
        if defect == "second_hit_runtime" and len(native_reads) == 2:
            current.element_info.runtime_id = [42, 999]
        return state["raw"]
    monkeypatch.setattr(hits, "_desktop_factory", lambda **kw: NS(from_point=from_point))
    monkeypatch.setattr(text, "_native_root_handle", lambda handle: handle if handle == 11 else None)
    monkeypatch.setattr(text, "_no_pattern_exception", lambda: NoPattern)
    monkeypatch.setattr(hits, "WindowsNativeIdentityReader", lambda **kw:
        NS(read_identity=lambda _: deepcopy(identity)))
    def recognize(request):
        result = vision.recognition_plan(request)
        if defect == "runtime": current.element_info.runtime_id = [42, 999]
        elif defect == "name": current.element_info.name = "Delete draft"
        elif defect == "type": current.element_info.control_type = "Hyperlink"
        elif defect == "disabled": current.is_enabled = lambda: False
        elif defect == "invisible": current.is_visible = lambda: False
        elif defect == "bbox": current.element_info.rectangle.right += 1
        elif defect == "pid": current.element_info.process_id = 99
        elif defect in {"overlay_text", "overlay_pane"}:
            overlay = wrapper(snapshot["controls"][1], parent=current)
            overlay.element_info.control_type = "Text" if defect == "overlay_text" else "Pane"
            overlay.element_info.runtime_id = [42, 998]
            state["raw"] = overlay
        elif defect == "container_runtime": parent.element_info.runtime_id = [42, 998]
        elif defect == "container_name": parent.element_info.name = "Different form"
        elif defect == "container_type": parent.element_info.control_type = "Group"
        elif defect == "container_bbox": parent.element_info.rectangle.right += 1
        elif defect == "container_missing": current.parent = lambda: root
        elif defect == "container_cycle": parent.parent = lambda: current
        elif defect == "field_readonly": current.iface_value.CurrentIsReadOnly = True
        elif defect == "field_unknown": current.iface_value.CurrentIsReadOnly = None
        elif defect == "provider": current.is_enabled = lambda: (_ for _ in ()).throw(RuntimeError("PRIVATE_SENTINEL"))
        return result
    monkeypatch.setattr(action, "_run_recognition_plan_for_execution", recognize)
    monkeypatch.setattr(action.input_controller, "click_point", lambda x, y, **kw:
        clicks.append((x, y)) or {"clicked": True, "window_point": {"x": x, "y": y}})
    monkeypatch.setattr(action, "_render_recognition_plan_overlay_for_execution", lambda plan: None)
    request = ExecuteRecognitionPlanRequest(goal="Click the Find button", enable_post_click_verification=False,
        max_execution_attempts=1, auto_observe_learning_artifacts=False,
        metadata={"task_plan_target": target} if structured else {},
        write_policy={"path_graph": False, "element_memory": False, "trace": False})
    with _local_operator_input_scope(manager=manager, identity_reader=NS(read_identity=lambda _: deepcopy(identity)),
            identity=identity, window_rect=(100, 200, 1000, 800), enabled=lambda: True), pinned_uia_snapshot(snapshot):
        response = action.execute_recognition_plan(request)
    return response, clicks, native_reads


def test_same_current_control_reaches_original_click_after_two_bound_direct_hits(current_frame, monkeypatch):
    response, clicks, hits = run_scene(current_frame, monkeypatch)
    assert response.success, response
    assert clicks == [(100, 100)] and hits == [(200, 300), (200, 300)]
    record = response.data["result"]["task_plan_dispatch_target_check"]
    assert record["status"] == "matched" and record["sample_count"] == 2
    assert record["validation_scope"] == "current_control_identity_before_dispatch_not_atomic"
    assert record["artifact_is_authorization"] is False


@pytest.mark.parametrize("defect", ["runtime", "name", "type", "disabled", "invisible", "bbox", "pid",
    "overlay_text", "overlay_pane", "container_runtime", "container_name", "container_type", "container_bbox",
    "container_missing", "container_cycle", "second_hit_runtime"])
def test_current_target_change_refuses_without_replaying_or_relocating_click(current_frame, monkeypatch, defect):
    response, clicks, hits = run_scene(current_frame, monkeypatch, defect)
    assert not response.success, response
    assert clicks == []
    assert len(hits) <= 2 and all(point == (200, 300) for point in hits)


def test_unstructured_original_click_has_no_added_native_hit_queries(current_frame, monkeypatch):
    response, clicks, hits = run_scene(current_frame, monkeypatch, "runtime", structured=False)
    assert response.success, response
    assert clicks == [(100, 100)] and hits == []


@pytest.mark.parametrize("kind", ["Button", "Hyperlink", "Edit", "ComboBox", "MenuItem", "TabItem"])
def test_original_six_types_pass_with_original_uia_capability_contract_without_reading_value(current_frame, monkeypatch, kind):
    response, clicks, hits = run_scene(current_frame, monkeypatch, kind=kind)
    assert response.success, response
    assert clicks == [(100, 100)] and len(hits) == 2


@pytest.mark.parametrize("kind", ["Edit", "ComboBox"])
@pytest.mark.parametrize("defect", ["field_readonly", "field_unknown"])
def test_current_field_readonly_or_unknown_refuses_as_not_writable(current_frame, monkeypatch, kind, defect):
    response, clicks, hits = run_scene(current_frame, monkeypatch, defect, kind=kind)
    assert not response.success and clicks == [] and len(hits) == 1
    assert "text_field_target_not_writable" in response.error.details


def test_provider_failure_retains_safe_provider_class_without_exception_text(current_frame, monkeypatch):
    response, clicks, hits = run_scene(current_frame, monkeypatch, "provider")
    assert not response.success and clicks == []
    assert "PRIVATE_SENTINEL" not in str(response)


@pytest.mark.parametrize("length", [259, 4096])
def test_strict_entry_keeps_original_long_capture_identity(current_frame, monkeypatch, length):
    from app.agent import windows_control_hit_reader as hits, windows_text_field_reader as text
    raw = current_frame[1]["controls"][0]
    root = NS(element_info=NS(handle=11, process_id=22))
    hit = wrapper(raw, parent=root)
    manager = NS(get_bound_window=lambda: NS(handle=11, process_id=22,
        rect=NS(left=100, top=200, right=1000, bottom=800)))
    fact = {"contract_version": "windows_native_identity_observation_v1", "provider": "windows_native_identity",
        "status": "observed", "target_window_handle": 11, "process_id": 22,
        "process_create_time": 123.0, "executable_path": "c:/fixture/editor.exe"}
    monkeypatch.setattr(text, "_native_root_handle", lambda handle: 11 if handle == 11 else None)
    reader = hits.WindowsControlHitReader(manager, native_identity_reader=NS(read_identity=lambda _: fact),
        desktop_factory=lambda **kw: NS(from_point=lambda x, y: hit))
    capture_id = "C:/" + "a" * (length-3)
    args = dict(window_handle=11, process_id=22, process_create_time=123.0, window_rect=(100, 200, 900, 600),
        capture_id=capture_id, control_id="find", point=(100, 100), expected_runtime_id=raw["runtime_id"],
        expected_control_type="Button", expected_bbox=(40, 80, 120, 40))
    record = reader.observe_target_hit(**args, expected_name="Find")
    assert record["capture_id"] == capture_id and record["sample_count"] == 2
    with pytest.raises(hits.NativeControlHitError, match="request_invalid"):
        reader.observe_control_hit(**args)
    with pytest.raises(hits.NativeControlHitError, match="request_invalid"):
        reader.observe_target_hit(**{**args, "capture_id": "a"*4097}, expected_name="Find")
    with pytest.raises(hits.NativeControlHitError, match="request_invalid"):
        reader.observe_target_hit(**{**args, "control_id": "a"*257}, expected_name="Find")
    with pytest.raises(hits.NativeControlHitError, match="request_invalid"):
        reader.observe_target_hit(**{**args, "expected_control_type": "Pane"}, expected_name="Find")
