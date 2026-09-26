"""结构化具名字段的当前控件主定位，不伪造视觉模型验证。"""
import pytest
from PIL import Image
from app.api import vision
from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
from app.vision.schemas import ImageSize


@pytest.mark.parametrize("kind,patterns", [("Edit", ["Value", "Text"]),
    ("ComboBox", ["Value", "Text", "ExpandCollapse"])])
def test_named_form_primary_uses_current_box_without_model(tmp_path, monkeypatch, kind, patterns):
    path = tmp_path / "form.png"
    Image.new("RGB", (1278, 1285), "white").save(path)
    box = {"x": 461, "y": 238, "w": 356, "h": 38}
    snapshot = {"status": "ok", "scan_complete": True, "truncated": False,
        "controls": [{"control_id": "field", "runtime_id": [42, 354], "name": "Place",
            "control_type": kind, "patterns": patterns, "bbox": box, "visible": True, "enabled": True}]}
    def unexpected(**kwargs):
        pytest.fail("current unique field primary route must not call VISTA")
    monkeypatch.setattr(vision, "_call_vista_point_prompt", unexpected)
    goal = 'Click the input labelled "Place"'
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(path), task="locate_element", goal=goal,
        agent_mode="execute", provider_mode="local_grounding", top_k=5,
        metadata={"text_focus_route": "current_uia_primary"},
        write_policy={"path_graph": False, "element_memory": False, "trace": False})
    with pinned_uia_snapshot(snapshot), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}}, local_config={"model_name": "isolated", "endpoint": "http://unused.invalid"},
            image_path=path, input_image_size=ImageSize(width=1278, height=1285), goal=goal,
            observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []})
    plan = response.data["result"]
    from app.core.local_recognition_policy import local_recognition_selection
    chosen = local_recognition_selection(plan, image_path=path, viewport_size={"width": 1278, "height": 1285})
    assert chosen["selected_click_point"] == {"x": 639, "y": 257}
    assert plan["execution_path"]["vision_model_used"] is False
    assert plan["execution_path"]["coordinate_source"] == "current_uia_named_text_center"
    assert plan["parse_result"]["vista_point_grounding"] is None
    assert plan["model_io"]["status"] == "skipped"


def test_form_fill_opts_in_only_for_explicit_text_labels(monkeypatch):
    from app.desktop_review import form_fill
    seen = []
    def run(coordinator, target, request, **kwargs):
        seen.append((request, kwargs))
        return {"status": "completed", "phase": "returned", "steps": [], "action_executed": True,
            "input_check": {"status": "matched"}}
    monkeypatch.setattr(form_fill, "run_input_sequence", run)
    form_fill.run_form_fill(object(), {"handle": 1, "process_id": 2}, {"fields": [
        {"kind": "text", "field_goal": "Place", "label": "Place", "text": "A"},
        {"kind": "text", "field_goal": "The next input", "text": "B"}]})
    assert seen[0][0]["field_goal"] == 'Click the input labelled "Place"'
    assert seen[0][1].get("_prefer_current_uia") is True
    assert seen[1][0]["field_goal"] == "The next input"
    assert not seen[1][1].get("_prefer_current_uia", False)


@pytest.mark.parametrize("label,expected", [
    ("与以下字词完全匹配：", {"x": 408, "y": 455}),
    ("以下所有字词：", {"x": 408, "y": 372}),
])
def test_real_form_named_fields_use_current_uia_primary(tmp_path, monkeypatch, label, expected):
    path = tmp_path / "form.png"
    Image.new("RGB", (2412, 1040), "white").save(path)
    first_box = {"x": 238, "y": 348, "w": 340, "h": 48}
    second_box = {"x": 238, "y": 431, "w": 340, "h": 48}
    first_id = [42, 4588064, 4, 6, 8, 4]
    snapshot = {"status": "ok", "scan_complete": True, "truncated": False,
        "controls": [
            {"control_id": "first", "runtime_id": first_id, "name": "以下所有字词：",
                "control_type": "Edit", "patterns": ["Value", "Text"], "bbox": first_box,
                "visible": True, "enabled": True,
                "form_label_binding": {"control_id": "first", "runtime_id": first_id,
                    "label": "使用以下条件来搜索网页", "source": "visible_label_geometry", "bbox": first_box}},
            {"control_id": "second", "runtime_id": [42, 4588064, 4, 6, 8, 5],
                "name": "与以下字词完全匹配：", "control_type": "Edit",
                "patterns": ["Value", "Text"], "bbox": second_box,
                "visible": True, "enabled": True, "form_label_binding": None},
        ]}
    def unexpected(**kwargs):
        pytest.fail("unique current UIA field must be selected before VISTA")
    monkeypatch.setattr(vision, "_call_vista_point_prompt", unexpected)
    goal = f'Click the input labelled "{label}"'
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(path), task="locate_element",
        goal=goal, agent_mode="execute", provider_mode="local_grounding", top_k=5,
        metadata={"text_focus_route": "current_uia_primary"},
        write_policy={"path_graph": False, "element_memory": False, "trace": False})
    with pinned_uia_snapshot(snapshot), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}},
            local_config={"model_name": "isolated", "endpoint": "http://unused.invalid"},
            image_path=path, input_image_size=ImageSize(width=2412, height=1040), goal=goal,
            observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []})
    plan = response.data["result"]
    from app.core.local_recognition_policy import local_recognition_selection
    chosen = local_recognition_selection(plan, image_path=path,
        viewport_size={"width": 2412, "height": 1040})
    assert chosen["selected_click_point"] == expected
    assert plan["execution_path"]["coordinate_source"] == "current_uia_named_text_center"
    assert plan["execution_path"]["vision_model_used"] is False
    assert plan["model_io"]["status"] == "skipped"


def test_duplicate_named_fields_do_not_use_unique_uia_primary(tmp_path, monkeypatch):
    path = tmp_path / "form.png"
    Image.new("RGB", (2412, 1040), "white").save(path)
    controls = [{"control_id": f"field-{index}", "runtime_id": [42, index],
        "name": "与以下字词完全匹配：", "control_type": "Edit",
        "patterns": ["Value", "Text"],
        "bbox": {"x": 238, "y": y, "w": 340, "h": 48},
        "visible": True, "enabled": True} for index, y in enumerate((431, 514), 1)]
    snapshot = {"status": "ok", "scan_complete": True, "truncated": False,
        "controls": controls}
    model_calls = []
    def model_called(**kwargs):
        model_calls.append(kwargs)
        raise RuntimeError("model path reached after unique UIA check failed")
    monkeypatch.setattr(vision, "_call_vista_point_prompt", model_called)
    goal = 'Click the input labelled "与以下字词完全匹配："'
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(path), task="locate_element",
        goal=goal, agent_mode="execute", provider_mode="local_grounding", top_k=5,
        metadata={"text_focus_route": "current_uia_primary"},
        write_policy={"path_graph": False, "element_memory": False, "trace": False})
    with pinned_uia_snapshot(snapshot), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}},
            local_config={"model_name": "isolated", "endpoint": "http://unused.invalid"},
            image_path=path, input_image_size=ImageSize(width=2412, height=1040), goal=goal,
            observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []})
    plan = response.data["result"]
    assert model_calls
    assert plan["candidate_result"]["summary"]["current_uia_primary_candidate_used"] is False
    assert plan["execution_path"].get("coordinate_source") != "current_uia_named_text_center"
