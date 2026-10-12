"""字段已被本帧粗定位命中时，不让裁图细化重新选择另一个控件。"""
import pytest
from app.api import vision
from app.core import local_text_focus
from tests.test_input_focus_prompt import DESCRIPTIVE_FIELD_GOAL


def snapshot():
    return {"status": "ok", "scan_complete": True, "truncated": False, "controls": [
        {"control_id": "search", "runtime_id": [42, 1], "name": "搜索",
         "control_type": "ComboBox", "patterns": ["Value", "Text"],
         "enabled": True, "visible": True, "bbox": {"x": 235, "y": 113, "w": 700, "h": 40}},
        {"control_id": "address", "runtime_id": [42, 2], "name": "地址和搜索栏",
         "control_type": "Edit", "patterns": ["Value", "Text"],
         "enabled": True, "visible": True, "bbox": {"x": 104, "y": 48, "w": 2152, "h": 24}},
    ]}


@pytest.mark.parametrize("goal,expected", [
    ("Click the Google search input field at the top of the results page", True),
    ("Click inside the text area", True),
    ("Click the search button next to the input box", False),
    ("Double click the word museum inside the search input box", False),
    ("Click the icon inside the search input box", False),
])
def test_only_field_focus_uses_full_context(goal, expected):
    assert vision._field_focus_uses_full_context(goal) is expected


def test_internal_descriptive_field_focus_keeps_full_context():
    with local_text_focus.local_text_focus_scope(local_text_focus.LocalTextFocusTarget(10, 20)):
        assert vision._field_focus_uses_full_context(DESCRIPTIVE_FIELD_GOAL) is True
    assert vision._field_focus_uses_full_context(DESCRIPTIVE_FIELD_GOAL) is False


@pytest.mark.parametrize("target", [None, {"role": "button", "label": "Search"}])
def test_internal_focus_does_not_override_explicit_geometry_exclusions(target):
    goal = "Double click the word museum inside the search input box" if target is None else "Search"
    with local_text_focus.local_text_focus_scope(local_text_focus.LocalTextFocusTarget(10, 20)):
        assert vision._field_focus_uses_full_context(goal, target) is False


def test_claimed_focus_does_not_keep_full_context(monkeypatch):
    monkeypatch.setattr(local_text_focus, "require_local_operator_input", lambda manager: True)
    monkeypatch.setattr(local_text_focus, "probe_local_focus_target", lambda *args, **kwargs:
        {"control_type": "Edit", "runtime_id": [42, 1]})
    with local_text_focus.local_text_focus_scope(local_text_focus.LocalTextFocusTarget(10, 20)):
        local_text_focus.check_local_text_focus({"x": 90, "y": 87}, object())
        assert vision._field_focus_uses_full_context(DESCRIPTIVE_FIELD_GOAL) is False


@pytest.mark.parametrize("metadata", [{}, {"vista_direct_grounding": True},
                                    {"vista_direct_grounding": {"timeout_seconds": 30}},
                                    {"control_target": {"contract_version": "recognition_control_target_v1",
                                        "role": "input", "label": "Address", "source_binding_sha256": "a" * 64}}])
def test_internal_focus_defaults_preserve_field_detail_without_mutating_request(metadata):
    from app.api import action
    request = action.ExecuteRecognitionPlanRequest(goal=DESCRIPTIVE_FIELD_GOAL, metadata=metadata)
    original = request.model_dump()
    with local_text_focus.local_text_focus_scope(local_text_focus.LocalTextFocusTarget(10, 20)):
        provider, effective = action._execute_plan_request_defaults(request)
    assert provider == "local_grounding"
    assert effective["vista_direct_grounding"]["max_edge"] == 1024
    assert effective["vista_direct_grounding"]["refine_max_edge"] == 640
    assert request.model_dump() == original


@pytest.mark.parametrize("goal,metadata", [
    ("Click Reports", {}),
    ("Click the search input field", {}),
    (DESCRIPTIVE_FIELD_GOAL, {"semantic_action": "fill_field"}),
    (DESCRIPTIVE_FIELD_GOAL, {"control_target": {"role": "input", "label": "Address"}}),
])
def test_unscoped_navigation_and_strict_fill_keep_existing_default_scale(goal, metadata):
    from app.api import action
    request = action.ExecuteRecognitionPlanRequest(goal=goal, metadata=metadata)
    assert action._execute_plan_request_defaults(request)[1]["vista_direct_grounding"]["max_edge"] == 640


@pytest.mark.parametrize("goal,metadata", [
    ("Double click the word museum inside the search input box", {}),
    (DESCRIPTIVE_FIELD_GOAL, {"control_target": {"contract_version": "recognition_control_target_v1",
        "role": "button", "label": "Search", "source_binding_sha256": "a" * 64}}),
    (DESCRIPTIVE_FIELD_GOAL, {"control_target": "Address"}),
    (DESCRIPTIVE_FIELD_GOAL, {"semantic_action": "fill_field"}),
])
def test_internal_focus_scale_keeps_explicit_target_and_strict_fill_exclusions(goal, metadata):
    from app.api import action
    request = action.ExecuteRecognitionPlanRequest(goal=goal, metadata=metadata)
    with local_text_focus.local_text_focus_scope(local_text_focus.LocalTextFocusTarget(10, 20)):
        assert action._execute_plan_request_defaults(request)[1]["vista_direct_grounding"]["max_edge"] == 640


@pytest.mark.parametrize("override", [False, {"max_edge": 640}, {"max_edge": 1280}])
def test_internal_focus_scale_respects_explicit_vista_override(override):
    from app.api import action
    request = action.ExecuteRecognitionPlanRequest(goal=DESCRIPTIVE_FIELD_GOAL,
        metadata={"vista_direct_grounding": override})
    with local_text_focus.local_text_focus_scope(local_text_focus.LocalTextFocusTarget(10, 20)):
        effective = action._execute_plan_request_defaults(request)[1]["vista_direct_grounding"]
    if override is False:
        assert effective is False
    else:
        assert effective["max_edge"] == override["max_edge"]


def test_internal_focus_scale_does_not_change_nonexecute_defaults():
    from app.api import action
    request = action.ExecuteRecognitionPlanRequest(goal=DESCRIPTIVE_FIELD_GOAL, agent_mode="learn")
    with local_text_focus.local_text_focus_scope(local_text_focus.LocalTextFocusTarget(10, 20)):
        assert action._execute_plan_request_defaults(request) == (None, {})


def test_claimed_exited_or_other_thread_focus_does_not_change_default_scale(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from contextvars import copy_context
    from app.api import action
    request = action.ExecuteRecognitionPlanRequest(goal=DESCRIPTIVE_FIELD_GOAL)
    monkeypatch.setattr(local_text_focus, "require_local_operator_input", lambda manager: True)
    monkeypatch.setattr(local_text_focus, "probe_local_focus_target", lambda *args, **kwargs:
        {"control_type": "Edit", "runtime_id": [42, 1]})
    with local_text_focus.local_text_focus_scope(local_text_focus.LocalTextFocusTarget(10, 20)):
        copied = copy_context()
        with ThreadPoolExecutor(max_workers=1) as worker:
            effective = worker.submit(copied.run, action._execute_plan_request_defaults, request).result()[1]
        assert effective["vista_direct_grounding"]["max_edge"] == 640
        local_text_focus.check_local_text_focus({"x": 90, "y": 87}, object())
        assert action._execute_plan_request_defaults(request)[1]["vista_direct_grounding"]["max_edge"] == 640
    assert action._execute_plan_request_defaults(request)[1]["vista_direct_grounding"]["max_edge"] == 640


def test_internal_long_field_goal_does_not_enter_roi_after_coarse_miss(tmp_path, monkeypatch):
    from app.api import action
    from PIL import Image
    from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
    from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
    from modules.ocr.contracts import OCRResult
    image = tmp_path / "current.png"
    Image.new("RGB", (2412, 1017), "white").save(image)
    calls = []
    def infer(**kwargs):
        calls.append(kwargs)
        return {"point": {"x": 264, "y": 68} if len(calls) == 1 else {"x": 90, "y": 102},
                "provider": "isolated-model-boundary"}
    monkeypatch.setattr(vision, "_call_vista_point_prompt", infer)
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda p: OCRResult(image_path=str(p), matches=[]))
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(image), task="click_target",
        goal=DESCRIPTIVE_FIELD_GOAL, agent_mode="execute", provider_mode="local_grounding", top_k=5,
        metadata={"vista_direct_grounding": {"refine": True}},
        write_policy={"path_graph": False, "element_memory": False, "trace": False})
    unavailable = {"status": "unavailable", "scan_complete": None, "truncated": False, "controls": []}
    with local_text_focus.local_text_focus_scope(local_text_focus.LocalTextFocusTarget(10, 20)), \
            pinned_uia_snapshot(unavailable), pinned_runtime_output_root(tmp_path):
        _, effective = action._execute_plan_request_defaults(action.ExecuteRecognitionPlanRequest(
            goal=DESCRIPTIVE_FIELD_GOAL, metadata=request.metadata))
        request = request.model_copy(update={"metadata": effective})
        response = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}},
            local_config={"model_name": "isolated", "endpoint": "http://unused.invalid"},
            image_path=image, input_image_size=vision.ImageSize(width=2412, height=1017),
            goal=DESCRIPTIVE_FIELD_GOAL, observe_reuse={},
            path_graph_recall={"status": "not_requested", "candidates": []})
    assert len(calls) == 1
    assert calls[0]["vista_stage"] == "coarse_full"
    assert calls[0]["image_size"] == vision.ImageSize(width=1024, height=432)
    assert "interior of the editable field" in calls[0]["prompt"]
    result = response.data["result"]
    assert result["parse_result"]["vista_point_grounding"]["point"] == {"x": 264, "y": 68}
    assert result["execution_path"]["action_executed"] is False


@pytest.mark.parametrize("uia_ready", [True, False])
def test_recognition_does_not_refine_a_field_into_the_address_bar(tmp_path, monkeypatch, uia_ready):
    from PIL import Image
    from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
    from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
    from modules.ocr.contracts import OCRResult
    image = tmp_path / "page.png"
    Image.new("RGB", (2560, 1400), "white").save(image)
    calls = []
    def infer(**kwargs):
        calls.append(kwargs)
        return {"point": {"x": 496, "y": 140} if len(calls) == 1 else {"x": 299, "y": 51},
                "provider": "isolated-model-boundary"}
    monkeypatch.setattr(vision, "_call_vista_point_prompt", infer)
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda p: OCRResult(image_path=str(p), matches=[]))
    goal = "Click the search input field at the top of the results page"
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(image), task="locate_element", goal=goal,
        agent_mode="execute", provider_mode="local_grounding", top_k=5,
        metadata={"vista_direct_grounding": {"refine": True}},
        write_policy={"path_graph": False, "element_memory": False, "trace": False})
    uia = snapshot()
    if not uia_ready:
        # 未提供 UIA 与完整树未命中字段不同；此项只覆盖真正不可用时的像素路径。
        uia = {"status": "unavailable", "scan_complete": None, "truncated": False, "controls": []}
    with pinned_uia_snapshot(uia), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}}, local_config={"model_name": "isolated", "endpoint": "http://unused.invalid"},
            image_path=image, input_image_size=vision.ImageSize(width=2560, height=1400), goal=goal,
            observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []})
    assert len(calls) == 1
    result = response.data["result"]
    chosen = result["recommended_target"]
    # UIA 元素仍保存原中心；实际模型点保存在对应的细化结果，不能把两者混用。
    local = [item for item in result["narrow_search_result"]["results"]
             if item["candidate_id"] == chosen["candidate_id"]]
    assert len(local) == 1
    assert local[0]["refined_click_point"] == {"x": 496, "y": 140}
