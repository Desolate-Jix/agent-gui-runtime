"""空字段拒绝须说明缺少的当前证据，不能让合成框代替真实 Edit。"""
from copy import deepcopy

import pytest
from PIL import Image

from app.api import vision
from app.core.runtime_artifacts import pinned_runtime_output_root
from app.operation.recognition.decision import decide_pre_click
from app.operation.recognition.schemas import CandidateRankResult, LocalGroundingResult
from app.vision.schemas import ImageSize
from modules.ocr.contracts import OCRResult


def _uia(*, field=False):
    controls = [{"control_id": "document", "control_type": "Document", "name": None,
                 "bbox": {"x": 0, "y": 0, "w": 200, "h": 150}, "patterns": [],
                 "visible": True, "enabled": True, "runtime_id": [42, 1]}]
    if field:
        controls.append({"control_id": "field", "control_type": "Edit", "name": "Search",
                         "bbox": {"x": 50, "y": 60, "w": 110, "h": 30},
                         "patterns": ["Value", "Text"], "visible": True, "enabled": True,
                         "runtime_id": [42, 2], "ancestor_control_ids": ["document"]})
    return {"status": "ok", "scan_complete": True, "truncated": False, "controls": controls}


@pytest.mark.parametrize("field,expected", [(False, "current_editable_control_missing"),
                                           (True, "current_editable_control_unverified")])
def test_empty_field_reports_current_identity_without_granting_click(tmp_path, monkeypatch, field, expected):
    image = tmp_path / "fresh.png"
    Image.new("RGB", (200, 150), "white").save(image)
    point = {"x": 80, "y": 75}
    goal = "Click the search input box"
    candidate = vision._recognition_candidate_from_vista_direct(
        goal=goal, point=point, image_size=ImageSize(width=200, height=150), bbox_size=24)
    original_bbox = candidate.element.bbox.to_dict()
    uia = _uia(field=field)
    original = deepcopy(uia)
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda path: OCRResult(image_path=path, matches=[]))
    import app.agent.native_control_hit_context as owner
    monkeypatch.setattr(owner, "collect_current_control_hit", lambda **kwargs: None)
    with pinned_runtime_output_root(tmp_path / "output"):
        local = vision._corroborate_vista_direct_point(image_path=image, goal=goal,
            candidate=candidate, point=point, app_name="synthetic", uia_snapshot=uia)
    fact = candidate.element.evidence["editable_target_diagnostic"]
    assert fact["status"] == expected
    assert fact["action_executed"] is False and fact["automatic_retry_allowed"] is False
    assert fact["control_ids_at_point"] == (["field"] if field else [])
    assert local.status == "unverified" and local.matched_text is None
    assert candidate.element.bbox.to_dict() == original_bbox
    assert candidate.role == "button" and uia == original
    ranked = CandidateRankResult(goal=goal, candidates=[candidate], rejected=[],
        recommended_candidate_id=candidate.candidate_id, margin_to_second=None, summary={})
    grounding = LocalGroundingResult(goal=goal, results=[local], recommended_candidate_id=None, summary={})
    assert decide_pre_click(goal=goal, candidates=ranked, grounding=grounding).allowed is False


def test_inventory_preserves_raw_snapshot_separately_from_filtered_controls(tmp_path, monkeypatch):
    image = tmp_path / "fresh.png"
    Image.new("RGB", (200, 150), "white").save(image)
    uia = _uia(field=True)
    uia["controls"].append({"control_id": "hidden", "control_type": "Edit", "name": "Hidden",
        "bbox": {"x": 50, "y": 60, "w": 110, "h": 30}, "visible": False, "enabled": True})
    monkeypatch.setattr(vision.uia_provider, "snapshot_bound_window", lambda **kwargs: deepcopy(uia))
    result = vision._execute_fast_inventory_from_uia(image_path=image,
        image_size=ImageSize(width=200, height=150), app_name="synthetic", goal="search input box", metadata={})
    assert result["raw_uia_snapshot"] == uia
    assert "hidden" not in [c["control_id"] for c in result["screen_reading"]["source_layers"]["windows_uia"]["controls"]]
