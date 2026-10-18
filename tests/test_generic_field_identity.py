"""动态字段值不等于输入框身份；模型点必须命中唯一当前字段。"""
import pytest

from app.api import vision
from app.operation.recognition.control_target import uia_action_identity_matches
from tests.test_uia_action_identity_context import _rig


GOAL = "Right click the search input box at the top of the page"


@pytest.mark.parametrize("goal", [GOAL, "Locate the search input box at the top of the page",
    "Right click inside the search input box containing Wikipedia Nelson",
    "Click within the search field", "Focus in the text area"])
def test_generic_field_can_match_dynamic_value_without_echoing_goal(goal):
    control = {"name": "TimaruDunedin", "control_type": "ComboBox", "patterns": ["Text", "Value"]}
    assert uia_action_identity_matches(control, goal=goal)
    assert control["name"] == "TimaruDunedin"


@pytest.mark.parametrize("goal", [
    "Double click the word Dunedin inside the Google search input box",
    'Right click the input labelled "Email"',
    "Click the link inside the search input box",
    "Click Save inside the input box",
    "Do not click the search input box",
    "Locate the word Dunedin inside the search input box",
    "Locate the button inside the search input box",
    'Locate the input labelled "Email"',
    "Right click inside the word Nelson in the search input box",
    "Click inside the button within the input box",
    "Click the link inside the text area",
])
def test_field_context_is_not_field_target(goal):
    assert not uia_action_identity_matches(
        {"name": "TimaruDunedin", "control_type": "ComboBox", "patterns": ["Text", "Value"]}, goal=goal)


def test_generic_field_reconciles_outside_top_k(tmp_path):
    fast, args = _rig(tmp_path, label="TimaruDunedin", kind="ComboBox")
    args.update(goal=GOAL, candidates=[])
    candidate, reason = vision._vista_direct_current_uia_identity(fast_inventory=fast, **args)
    assert reason is None and candidate is not None
    assert candidate.element.evidence["screen_inventory_action"]["source_id"] == "selected"
    assert candidate.label == "TimaruDunedin"
    assert candidate.role == "combobox"
    assert candidate.element.bbox.to_dict() == fast["screen_reading"]["source_layers"]["windows_uia"]["controls"][-1]["bbox"]


def test_single_field_also_reconciles_outside_top_k(tmp_path):
    fast, args = _rig(tmp_path, label="current query", kind="ComboBox")
    fast["screen_reading"]["source_layers"]["windows_uia"]["controls"].pop(1)
    args.update(goal=GOAL, candidates=[])
    candidate, reason = vision._vista_direct_current_uia_identity(fast_inventory=fast, **args)
    assert reason is None and candidate is not None
    assert "current_uia_point_disambiguation" not in candidate.element.evidence


def test_off_point_generic_fields_are_not_exact_label_conflicts(tmp_path):
    fast, args = _rig(tmp_path, label="Address bar", kind="Edit")
    args.update(goal=GOAL, candidates=[], point={"x": 580, "y": 480})
    candidate, reason = vision._vista_direct_current_uia_identity(fast_inventory=fast, **args)
    assert candidate is None and reason is None


@pytest.mark.parametrize("mutation", ["overlap", "incomplete", "outside", "disabled", "select_only"])
def test_generic_field_needs_current_unique_geometry(tmp_path, mutation):
    fast, args = _rig(tmp_path, label="query", kind="ComboBox", overlapping=mutation == "overlap")
    args.update(goal=GOAL, candidates=[])
    uia = fast["screen_reading"]["source_layers"]["windows_uia"]
    if mutation == "incomplete":
        uia["scan_complete"] = False
    elif mutation == "outside":
        args["point"] = {"x": 590, "y": 490}
    elif mutation == "disabled":
        uia["controls"][-1]["enabled"] = False
    elif mutation == "select_only":
        uia["controls"][-1]["patterns"] = ["ExpandCollapse"]
    candidate, _ = vision._vista_direct_current_uia_identity(fast_inventory=fast, **args)
    assert candidate is None


@pytest.mark.parametrize("field_visible_in_tree", [True, False])
@pytest.mark.parametrize("goal", [GOAL, "Locate the search input box at the top of the page",
    "Right click inside the search input box containing Wikipedia Nelson"])
def test_full_plan_uses_field_geometry_without_changing_click_to_fill(tmp_path, monkeypatch, field_visible_in_tree, goal):
    from PIL import Image
    from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
    from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
    from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch

    path = tmp_path / "frame.png"
    Image.new("RGB", (2560, 1400)).save(path)
    field = {"control_id": "search-field", "name": "TimaruDunedin", "control_type": "ComboBox",
             "bbox": {"x": 235, "y": 107, "w": 702, "h": 50}, "patterns": ["Text", "Value"],
             "enabled": True, "visible": True, "runtime_id": [42, 2, 12]}
    snapshot = {"provider": "windows_uia", "status": "ok", "scan_complete": True,
                "truncated": False, "controls": [field] if field_visible_in_tree else [
                    {**field, "control_id": "browser-tab", "name": "Wikipedia Timaru - Google Search - 内存使用率 - 373 MB",
                     "control_type": "TabItem", "patterns": ["Selection"],
                     "bbox": {"x": 32, "y": 0, "w": 256, "h": 41}}]}
    monkeypatch.setattr(vision, "_call_vista_point_prompt",
                        lambda **kwargs: {"point": {"x": 331, "y": 128}, "provider": "test-boundary"})
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda p: OCRResult(image_path=str(p), matches=[
        OCRTextMatch("TimaruDunedin", .99, OCRBoundingBox(30, 38, 120, 18))]))
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(path), task="locate_element",
        goal=goal, provider_mode="local_grounding", agent_mode="execute", app_name=None,
        write_policy={"path_graph": False, "element_memory": False, "trace": False},
        metadata={"vista_direct_grounding": {"refine": False}})
    with pinned_uia_snapshot(snapshot), pinned_runtime_output_root(tmp_path):
        result = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}}, local_config={"model_name": "test-boundary"},
            image_path=path, input_image_size=vision.ImageSize(width=2560, height=1400), goal=goal,
            observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []}).data["result"]
    candidates = result["candidate_result"]["candidates"]
    if not field_visible_in_tree:
        assert candidates[0]["candidate_id"].startswith("vista_direct_")
        assert result["narrow_search_result"]["recommended_candidate_id"] == candidates[0]["candidate_id"]
        assert candidates[0]["bbox_refine_reason"] == "synthetic_bbox_around_vista_direct_point"
        assert "screen_inventory_action" not in candidates[0]["element"]["evidence"]
        return
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["label"] == "TimaruDunedin"
    assert candidate["element"]["evidence"]["screen_inventory_action"]["source_id"] == "search-field"
    assert candidate["element"]["bbox"] == field["bbox"]
    assert candidate["element"]["interaction_type"] == "click"
    assert request.metadata.get("semantic_action") is None
    local = result["narrow_search_result"]["results"][0]
    assert local["status"] == "grounded"
    assert local["refined_click_point"] == {"x": 331, "y": 128}
