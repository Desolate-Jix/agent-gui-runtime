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
        seen.append(kwargs)
        return {"status": "completed", "phase": "returned", "steps": [], "action_executed": True,
            "input_check": {"status": "matched"}}
    monkeypatch.setattr(form_fill, "run_input_sequence", run)
    form_fill.run_form_fill(object(), {"handle": 1, "process_id": 2}, {"fields": [
        {"kind": "text", "field_goal": "Place", "label": "Place", "text": "A"},
        {"kind": "text", "field_goal": "The next input", "text": "B"}]})
    assert seen[0].get("_prefer_current_uia") is True
    assert not seen[1].get("_prefer_current_uia", False)
