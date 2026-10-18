"""粗定位后的裁图保留完整目标，父结果项不冒充明确请求的链接。"""
from copy import deepcopy

from PIL import Image
import pytest

from app.api import vision
from app.agent.live_runtime_composition import _parse_recognition
from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
from app.operation.recognition.control_target import uia_action_identity_matches
from app.operation.screen_reading.uia_provider import pinned_uia_snapshot


LABEL = "Library — Object-oriented filesystem paths"
GOAL = "Click the second search result link titled Library - Object-oriented filesystem paths, directly above the snippet Added in version 3.4. Do not click the first module index result."


@pytest.mark.parametrize("kind,expected", [("Hyperlink", True), ("ListItem", False), ("Button", False), ("Document", False)])
def test_explicit_link_identity_does_not_include_same_named_containers(kind, expected):
    assert uia_action_identity_matches({"name": LABEL, "control_type": kind, "patterns": ["Invoke"]}, goal=GOAL) is expected


def _run(tmp_path, monkeypatch, *, refined=None, incomplete=False, duplicate=False, ocr_proof=False):
    image_path = tmp_path / "new.png"
    Image.new("RGB", (2560, 1400), "white").save(image_path)
    box = {"x": 429, "y": 443, "w": 332, "h": 22}
    target = {"control_id": "link", "name": LABEL, "control_type": "Hyperlink", "bbox": box,
              "visible": True, "enabled": True, "patterns": ["Invoke"],
              "runtime_id": [42, 1], "ancestor_control_ids": ["container"]}
    parent = {**target, "control_id": "container", "control_type": "ListItem",
              "name": LABEL + " summary", "bbox": {"x": 429, "y": 436, "w": 761, "h": 116}, "patterns": [],
              "runtime_id": [42, 2], "ancestor_control_ids": []}
    controls = [parent, target]
    if duplicate:
        controls.append({**deepcopy(target), "control_id": "another-link"})
    calls = []

    def model(**kwargs):
        calls.append(kwargs)
        return {"point": {"x": 488, "y": 448} if len(calls) == 1 else dict(refined or {"x": 595, "y": 454}),
                "provider": "synthetic-model-boundary"}

    monkeypatch.setattr(vision, "_call_vista_point_prompt", model)
    # 无 OCR 佐证仍不宣称可执行；此回归只证明裁图和身份契约。
    from modules.ocr.contracts import OCRResult, OCRTextMatch, OCRBoundingBox
    matches = [OCRTextMatch(LABEL, .99, OCRBoundingBox(30, 26, 310, 12))] if ocr_proof else []
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda path: OCRResult(image_path=str(path), matches=matches))
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(image_path), task="locate_element",
        goal=GOAL, provider_mode="local_grounding", agent_mode="execute",
        write_policy={"path_graph": False, "element_memory": False, "trace": False},
        metadata={"vista_direct_grounding": {"refine": True, "max_edge": 640}})
    snapshot = {"provider": "windows_uia", "status": "ok", "scan_complete": not incomplete,
                "truncated": incomplete, "controls": controls}
    with pinned_uia_snapshot(snapshot), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}}, local_config={"model_name": "offline"},
            image_path=image_path, input_image_size=vision.ImageSize(width=2560, height=1400),
            goal=GOAL, observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []})
    assert response.success
    result = response.data["result"]
    _parse_recognition(result)
    return result, calls, box


def test_refine_crop_contains_full_current_target_not_only_coarse_point(tmp_path, monkeypatch):
    result, calls, box = _run(tmp_path, monkeypatch)
    assert len(calls) == 2
    crop = calls[1]["image_preprocess"]["crop_bounds_original"]
    assert crop["x"] <= box["x"] and crop["x"] + crop["w"] >= box["x"] + box["w"]
    assert crop["y"] <= box["y"] and crop["y"] + crop["h"] >= box["y"] + box["h"]
    assert calls[1]["goal"] == calls[0]["goal"] == GOAL
    assert calls[1]["image_preprocess"]["roi_source"] == "coarse_point_current_uia_identity"
    assert result["candidate_result"]["summary"]["vista_direct_current_uia_identity_reconciled"]
    assert result["pre_click_decision"]["allowed"] is False


@pytest.mark.parametrize("case", ["outside", "incomplete", "duplicate"])
def test_unconfirmed_or_refined_outside_identity_does_not_become_a_click(tmp_path, monkeypatch, case):
    result, calls, _ = _run(tmp_path, monkeypatch, refined={"x": 416, "y": 455} if case == "outside" else None,
                           incomplete=case == "incomplete", duplicate=case == "duplicate")
    assert not result["candidate_result"]["candidates"]
    assert result["pre_click_decision"]["allowed"] is False
    if case != "outside":
        assert calls[1]["image_preprocess"].get("roi_source") != "coarse_point_current_uia_identity"


def test_current_independent_control_proof_finishes_before_destructive_refinement(tmp_path, monkeypatch):
    result, calls, _ = _run(tmp_path, monkeypatch, ocr_proof=True, refined={"x": 416, "y": 455})
    assert len(calls) == 1
    grounding = result["parse_result"]["vista_point_grounding"]
    assert grounding["point"] == {"x": 488, "y": 448}
    assert grounding["refine_skipped_reason"] == "current_control_ocr_already_grounded"
    assert grounding["coarse_control_ocr_binding"]["point"] == grounding["point"]
    assert result["narrow_search_result"]["results"][0]["status"] == "grounded"


@pytest.mark.parametrize("case", ["incomplete", "duplicate"])
def test_ocr_alone_does_not_skip_refinement_without_unique_complete_identity(tmp_path, monkeypatch, case):
    result, calls, _ = _run(tmp_path, monkeypatch, ocr_proof=True,
        incomplete=case == "incomplete", duplicate=case == "duplicate")
    assert len(calls) == 2
    assert not result["candidate_result"]["candidates"]
