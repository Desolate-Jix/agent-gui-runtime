"""网页字段的首次定位使用本帧角色与祖先范围，不臆造字段名称。"""
from copy import deepcopy

import pytest

from app.api import vision


GOAL = "Click the search input field at the top left of the webpage"


def snapshot():
    address = {"control_id": "address", "runtime_id": [42, 2], "name": "Address", "control_type": "Edit",
        "patterns": ["Value", "Text"], "visible": True, "enabled": True,
        "bbox": {"x": 104, "y": 48, "w": 1917, "h": 24}, "ancestor_control_ids": []}
    window = {"handle": 123, "process_id": 456, "process_name": "msedge.exe"}
    return {"status": "ok", "scan_complete": True, "truncated": False, "window": window,
        "browser_chrome_scope": {"status": "ok", "scan_scope": "browser_chrome", "scan_complete": True,
            "truncated": False, "window": deepcopy(window), "controls": [deepcopy(address)]},
        "controls": [address,
            {"control_id": "document", "runtime_id": [42, 3], "name": "Page", "control_type": "Document",
             "patterns": ["Text"], "visible": True, "enabled": True,
             "bbox": {"x": 4, "y": 80, "w": 2552, "h": 1316}, "ancestor_control_ids": []},
            {"control_id": "field", "runtime_id": [42, 4], "name": "\ufffc", "control_type": "ComboBox",
             "patterns": ["Value", "Text", "ExpandCollapse"], "visible": True, "enabled": True,
             "bbox": {"x": 116, "y": 103, "w": 246, "h": 24}, "ancestor_control_ids": ["document"]},
            *[{"control_id": f"button-{i}", "runtime_id": [42, 5+i], "name": "Search input field",
               "control_type": "Button", "patterns": ["Invoke"], "visible": True, "enabled": True,
               "bbox": {"x": 600+i*80, "y": 200, "w": 70, "h": 40}, "ancestor_control_ids": ["document"]}
              for i in range(7)]]}


def run_primary(tmp_path, monkeypatch, uia, *, goal=GOAL, point=None):
    from PIL import Image
    from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
    from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
    from modules.ocr.contracts import OCRResult
    image = tmp_path / "synthetic-page.png"
    Image.new("RGB", (2560, 1400), "white").save(image)
    calls = []
    monkeypatch.setattr(vision, "_call_vista_point_prompt", lambda **kw: calls.append(kw) or
        {"point": dict(point or {"x": 200, "y": 115}), "provider": "isolated-primary-model"})
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda p: OCRResult(image_path=str(p), matches=[]))
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(image), task="locate_element", goal=goal,
        agent_mode="execute", provider_mode="local_grounding", top_k=1,
        write_policy={"path_graph": False, "element_memory": False, "trace": False})
    with pinned_uia_snapshot(uia), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}},
            local_config={"model_name": "isolated", "endpoint": "http://unused.invalid"},
            image_path=image, input_image_size=vision.ImageSize(width=2560, height=1400), goal=goal,
            observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []})
    return response.data["result"], calls, image


@pytest.mark.parametrize("goal", [GOAL, "Click the search input field in the webpage", "Click the search input field on the web page"])
def test_unnamed_page_field_is_primary_before_top_k(tmp_path, monkeypatch, goal):
    result, calls, _ = run_primary(tmp_path, monkeypatch, snapshot(), goal=goal)
    assert len(calls) == 1
    assert result["candidate_result"]["summary"]["current_uia_primary_candidate_used"] is True
    target = result["recommended_target"]
    assert target["element"]["evidence"]["screen_inventory_action"]["source_id"] == "field"
    assert target["label"] == "\ufffc"
    assert target["element"]["bbox"] == {"x": 116, "y": 103, "w": 246, "h": 24}
    preprocess = calls[0]["image_preprocess"]
    assert preprocess["fallback_tier"] == "primary"
    assert preprocess["crop_bounds_original"] is not None
    assert preprocess["processed_size"]["width"] < 2560
    assert result["candidate_result"]["summary"]["current_uia_generic_page_field_primary"] is True
    assert result["candidate_result"]["summary"]["current_uia_literal_identity"]["entered"] is False


@pytest.mark.parametrize("fault", ["two_fields", "two_documents", "no_field", "incomplete", "missing_ancestry",
    "unclassified_field", "chrome_unavailable", "wrong_window", "value_only"])
def test_unproven_page_scope_never_becomes_unique_primary(tmp_path, monkeypatch, fault):
    uia = snapshot()
    if fault == "two_fields":
        uia["controls"].append({**deepcopy(uia["controls"][2]), "control_id": "other", "runtime_id": [42, 90]})
    elif fault == "two_documents":
        uia["controls"].append({**deepcopy(uia["controls"][1]), "control_id": "other-doc", "runtime_id": [42, 90]})
    elif fault == "no_field":
        uia["controls"] = [c for c in uia["controls"] if c["control_id"] != "field"]
    elif fault == "incomplete":
        uia.update(scan_complete=False, truncated=True)
    elif fault == "missing_ancestry":
        uia["controls"][2]["ancestor_control_ids"] = []
    elif fault == "unclassified_field":
        uia["controls"].append({**deepcopy(uia["controls"][2]), "control_id": "unknown", "runtime_id": [42, 90], "ancestor_control_ids": []})
    elif fault == "chrome_unavailable":
        uia["browser_chrome_scope"]["status"] = "unavailable"
    elif fault == "wrong_window":
        uia["browser_chrome_scope"]["window"]["handle"] = 999
    elif fault == "value_only":
        uia["controls"][2]["patterns"] = ["Value"]
    result, _, _ = run_primary(tmp_path, monkeypatch, uia)
    assert result["candidate_result"]["summary"]["current_uia_primary_candidate_used"] is False


@pytest.mark.parametrize("goal", ["Click the search input field", "Click the Address input field on the webpage",
    'Click the input field labelled "Page search" on the webpage', "Click the word Search in the input field on the webpage",
    "Click the address bar", "Click the search input field, not on the webpage"])
def test_other_target_contracts_do_not_enter_page_primary(tmp_path, monkeypatch, goal):
    result, _, _ = run_primary(tmp_path, monkeypatch, snapshot(), goal=goal)
    assert result["candidate_result"]["summary"]["current_uia_primary_candidate_used"] is False


def test_primary_crop_never_accepts_the_recorded_outside_point(tmp_path, monkeypatch):
    from app.core.local_recognition_policy import local_recognition_selection
    result, calls, image = run_primary(tmp_path, monkeypatch, snapshot(), point={"x": 128, "y": 140})
    assert len(calls) == 1
    assert result["candidate_result"]["summary"]["current_uia_primary_candidate_used"] is True
    assert result["recommended_target"] is None
    with pytest.raises(ValueError):
        local_recognition_selection(result, image_path=image, viewport_size={"width": 2560, "height": 1400})


@pytest.mark.parametrize("fault", ["missing", "duplicate", "geometry"])
def test_page_primary_requires_one_original_action(tmp_path, fault):
    from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
    size = vision.ImageSize(width=2560, height=1400)
    with pinned_uia_snapshot(snapshot()):
        inventory = vision._execute_fast_inventory_from_uia(image_path=tmp_path / "not-read.png",
            image_size=size, app_name=None, goal=GOAL, metadata={})
    actions = inventory["screen_inventory"]["available_actions"]
    action = next(a for a in actions if a.get("source_id") == "field")
    if fault == "missing":
        actions.remove(action)
    elif fault == "duplicate":
        actions.append(deepcopy(action))
    else:
        action["bbox"] = {"x": 116, "y": 103, "w": 500, "h": 24}
    assert vision._generic_page_field_primary_candidate(goal=GOAL, target_text=None,
        control_target=None, fast_inventory=inventory, image_size=size) is None
