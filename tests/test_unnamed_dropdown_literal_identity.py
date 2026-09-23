"""无名下拉的同帧标签只能选定真实控件框，不能把标签几何当点击框。"""
from copy import deepcopy

import pytest
from PIL import Image

from app.api import vision
from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
from modules.ocr.contracts import OCRResult


GOAL = "Click the dropdown labelled Eligibility to work"
BOX = {"x": 451, "y": 857, "w": 433, "h": 30}


def _snapshot():
    field = dict(control_id="eligibility-field", runtime_id=[42, 3], name="",
        bbox=dict(BOX), control_type="ComboBox", patterns=["ExpandCollapse", "Selection"],
        enabled=True, visible=True, ancestor_control_ids=["form-group"])
    field["form_label_binding"] = dict(control_id="eligibility-field", runtime_id=[42, 3],
        label="Eligibility to work", source="visible_label_geometry", bbox=dict(BOX))
    controls = [dict(control_id="eligibility-label", runtime_id=[42, 2], name="Eligibility to work",
        control_type="Text", bbox={"x": 451, "y": 837, "w": 180, "h": 18},
        enabled=True, visible=True, ancestor_control_ids=["form-group"]), field]
    for index in range(20):
        controls.append(dict(control_id=f"other-{index}", runtime_id=[42, 10 + index],
            name=f"Other action {index}", control_type="Button", patterns=["Invoke"],
            bbox={"x": 10, "y": 10 + index * 35, "w": 120, "h": 25},
            enabled=True, visible=True))
    return dict(status="ok", scan_complete=True, truncated=False, controls=controls)


@pytest.mark.parametrize("fault", [None, "stale_bbox", "duplicate", "outside_point"])
def test_literal_dropdown_uses_only_unique_validated_field_candidate(tmp_path, monkeypatch, fault):
    image = tmp_path / "synthetic.png"
    Image.new("RGB", (1278, 1399), "white").save(image)
    snapshot = _snapshot()
    if fault == "stale_bbox":
        snapshot["controls"][1]["form_label_binding"]["bbox"]["y"] += 20
    elif fault == "duplicate":
        duplicate = deepcopy(snapshot["controls"][1])
        duplicate["control_id"] = "eligibility-field-2"
        duplicate["runtime_id"] = [42, 4]
        duplicate["bbox"]["y"] += 50
        duplicate["form_label_binding"].update(control_id="eligibility-field-2",
            runtime_id=[42, 4], bbox=dict(duplicate["bbox"]))
        snapshot["controls"].append(duplicate)
    calls = []
    point = {"x": 442, "y": 481} if fault == "outside_point" else {"x": 638, "y": 871}
    monkeypatch.setattr(vision, "_call_vista_point_prompt", lambda **kw: calls.append(kw) or {
        "point": point, "provider": "isolated-model-boundary"})
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda path: OCRResult(image_path=str(path), matches=[]))
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(image), task="locate_element", goal=GOAL,
        agent_mode="execute", provider_mode="local_grounding", top_k=5,
        write_policy={"path_graph": False, "element_memory": False, "trace": False})
    with pinned_uia_snapshot(snapshot), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}},
            local_config={"model_name": "isolated", "endpoint": "http://unused.invalid"},
            image_path=image, input_image_size=vision.ImageSize(width=1278, height=1399), goal=GOAL,
            observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []})
    result = response.data["result"]
    literal = result["candidate_result"]["summary"]["current_uia_literal_identity"]
    if fault in {None, "outside_point"}:
        assert literal["match_count"] == 1
        assert calls[0]["vista_stage"] == "pathgraph_candidate_roi_refine", literal
        if fault is None:
            assert result["recommended_target"]["element"]["bbox"] == BOX
            assert result["recommended_target"]["element"]["evidence"]["screen_inventory_action"]["source_id"] == "eligibility-field"
            assert result["recommended_target"]["label"] == "Eligibility to work"
            assert result["recommended_target"]["element"]["evidence"]["current_uia_form_label_binding"]["runtime_id"] == [42, 3]
            assert result["candidate_result"]["summary"]["vista_direct_current_uia_identity_rejection"] is None
        else:
            from app.core.local_recognition_policy import local_recognition_selection
            with pytest.raises(ValueError):
                local_recognition_selection(result, image_path=image,
                    viewport_size={"width": 1278, "height": 1399})
    else:
        assert literal["match_count"] != 1
        assert calls[0]["vista_stage"] == "coarse_full"


def test_file_button_visible_label_alias_selects_one_of_duplicate_raw_names(tmp_path, monkeypatch):
    image = tmp_path / "synthetic-file.png"
    Image.new("RGB", (1278, 1399), "white").save(image)
    box = {"x": 451, "y": 857, "w": 433, "h": 30}
    raw_name = "选择文件: 未选择文件"
    first = dict(control_id="cover-file", runtime_id=[42, 3], name=raw_name,
        control_type="Button", patterns=["Value", "Invoke"], bbox=dict(box),
        enabled=True, visible=True, ancestor_control_ids=["form-group"])
    first["form_label_binding"] = dict(control_id="cover-file", runtime_id=[42, 3],
        label="Cover Letter", source="visible_label_geometry", bbox=dict(box))
    second = {**first, "control_id": "resume-file", "runtime_id": [42, 4],
        "bbox": {"x": 451, "y": 1006, "w": 433, "h": 30}}
    second.pop("form_label_binding")
    snapshot = dict(status="ok", scan_complete=True, truncated=False, controls=[first, second])
    calls = []
    monkeypatch.setattr(vision, "_call_vista_point_prompt", lambda **kw: calls.append(kw) or {
        "point": {"x": 638, "y": 871}, "provider": "isolated-model-boundary"})
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda path: OCRResult(image_path=str(path), matches=[]))
    goal = "Click the button labelled Cover Letter"
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(image), task="locate_element", goal=goal,
        agent_mode="execute", provider_mode="local_grounding", top_k=5,
        write_policy={"path_graph": False, "element_memory": False, "trace": False})
    with pinned_uia_snapshot(snapshot), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}},
            local_config={"model_name": "isolated", "endpoint": "http://unused.invalid"},
            image_path=image, input_image_size=vision.ImageSize(width=1278, height=1399), goal=goal,
            observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []})
    result = response.data["result"]
    assert result["candidate_result"]["summary"]["current_uia_literal_identity"]["match_count"] == 1
    assert calls[0]["vista_stage"] == "pathgraph_candidate_roi_refine"
    assert result["recommended_target"]["element"]["bbox"] == box
    assert result["recommended_target"]["element"]["evidence"]["screen_inventory_action"]["source_id"] == "cover-file"
    assert result["recommended_target"]["label"] == "Cover Letter"
    assert result["candidate_result"]["summary"]["vista_direct_current_uia_identity_rejection"] is None
    assert first["name"] == raw_name
    assert "associated label" in calls[0]["prompt"].casefold()
    assert raw_name in calls[0]["prompt"]
    assert "locate the button itself" in calls[0]["prompt"].casefold()
    from app.vision.model_workers.vista_openai_server import _vista_prompt
    effective = _vista_prompt(calls[0]["prompt"])
    assert "associated label" in effective.casefold()
    assert raw_name in effective
    assert "role='button'" in effective
    assert "bbox=[0,0,1299,90]" in calls[0]["prompt"]
    assert calls[0]["image_preprocess"]["crop_bounds_original"] == box
    assert "bbox=[" not in effective
    assert "pixel" not in effective.casefold()
    assert "Goal: Click the button associated with the visible field label" in calls[0]["prompt"]
    assert f"accessibility name={raw_name!r}" in effective
    assert "not the printed label" in effective.casefold()


def test_direct_point_identity_accepts_only_current_verified_alias():
    from app.operation.page_structure.schemas import PageStructure
    from app.operation.recognition.candidate_ranker import rank_candidates
    from app.operation.recognition.schemas import CandidateRankRequest
    from app.operation.screen_inventory.builder import _action_from_uia
    control = _snapshot()["controls"][1]
    goal = GOAL
    action = _action_from_uia(control, source_index=1)
    reading = {"image_size": {"width": 1278, "height": 1399},
        "screen_inventory": {"available_actions": [action]}}
    ranked = rank_candidates(CandidateRankRequest(goal=goal,
        page_structure=PageStructure(image_size=vision.ImageSize(width=1278, height=1399),
            screen_summary="current snapshot", state_guess=None, elements=[], texts=[]),
        top_k=1, screen_reading=reading))
    assert len(ranked.candidates) == 1
    candidate = ranked.candidates[0]
    candidate.label = "Eligibility to work"
    candidate.element.label = candidate.label
    fast_inventory = {"status": "ready", "uia_scan_truncated": False, "uia_scan_complete": True,
        "screen_reading": {"source_layers": {"windows_uia": {"status": "ok",
            "scan_complete": True, "truncated": False, "controls": [control]}}}}
    selected, reason = vision._vista_direct_current_uia_identity(goal=goal, target_text=None,
        point={"x": 638, "y": 871}, fast_inventory=fast_inventory, candidates=[candidate])
    assert selected is candidate and reason is None
    control["form_label_binding"]["bbox"]["y"] += 1
    selected, reason = vision._vista_direct_current_uia_identity(goal=goal, target_text=None,
        point={"x": 638, "y": 871}, fast_inventory=fast_inventory, candidates=[candidate])
    assert selected is None and reason is None


def test_plain_named_input_field_uses_current_alias_primary_roi(tmp_path, monkeypatch):
    image = tmp_path / "synthetic-notice.png"
    Image.new("RGB", (1278, 1399), "white").save(image)
    snapshot = _snapshot()
    field = snapshot["controls"][1]
    field.update(name="To be discussed - test only", control_type="Edit", patterns=["Value", "Text"])
    field["form_label_binding"]["label"] = "Notice period"
    snapshot["controls"][0]["name"] = "Notice period"
    calls = []
    monkeypatch.setattr(vision, "_call_vista_point_prompt", lambda **kw: calls.append(kw) or {
        "point": {"x": 638, "y": 871}, "provider": "isolated-model-boundary"})
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda path: OCRResult(image_path=str(path), matches=[]))
    goal = "Click the Notice period input field"
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(image), task="locate_element", goal=goal,
        agent_mode="execute", provider_mode="local_grounding", top_k=5,
        write_policy={"path_graph": False, "element_memory": False, "trace": False})
    with pinned_uia_snapshot(snapshot), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}},
            local_config={"model_name": "isolated", "endpoint": "http://unused.invalid"},
            image_path=image, input_image_size=vision.ImageSize(width=1278, height=1399), goal=goal,
            observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []})
    result = response.data["result"]
    assert result["candidate_result"]["summary"]["current_uia_literal_identity"]["match_count"] == 1
    assert calls[0]["vista_stage"] == "pathgraph_candidate_roi_refine"
    assert "editable text input field labeled 'Notice period'" in calls[0]["prompt"]
    from app.vision.model_workers.vista_openai_server import _vista_prompt
    effective = _vista_prompt(calls[0]["prompt"])
    assert "To be discussed - test only" not in effective
    assert "bbox=[" not in effective
    assert result["recommended_target"]["element"]["bbox"] == BOX
