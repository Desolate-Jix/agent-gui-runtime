"""本轮新建：模型点与 UIA 冲突时，拒绝结果仍须满足正式消费者契约。"""

from copy import deepcopy

import pytest
from PIL import Image

from app.agent.live_runtime_composition import _parse_recognition
from app.api import vision
from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
from app.operation.recognition.schemas import LocalGroundingCandidateResult
from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
from app.vision.schemas import ImageSize


def _recognize(tmp_path, monkeypatch, *, point, label="帮助(H)", goal="Locate the 帮助(H) Help menu"):
    image_path = tmp_path / "new-screen.png"
    Image.new("RGB", (500, 260), "white").save(image_path)
    snapshot = {
        "provider": "windows_uia", "status": "ok",
        "controls": [{
            "control_id": "fresh_help", "name": label,
            "control_type": "MenuItem", "enabled": True, "visible": True,
            "bbox": {"x": 300, "y": 30, "w": 55, "h": 20},
            "patterns": ["Invoke", "ExpandCollapse"],
        }] if label is not None else [],
    }
    calls = []

    # 仅替换外部模型/OCR 边界；候选生成、冲突检测和严格消费者均为生产实现。
    def model_reply(**kwargs):
        calls.append(kwargs["vista_stage"])
        return {"point": dict(point), "provider": "synthetic-model-boundary"}

    def local_ocr(**kwargs):
        candidate = kwargs["candidate"]
        return LocalGroundingCandidateResult(
            candidate_id=candidate.candidate_id, element_id=candidate.element_id,
            status="unverified", crop_path=None, crop_bbox=None,
            refined_click_point=dict(point), coordinate_source="synthetic-local-ocr",
            confidence=0.0, matched_text=None, matched_text_bbox=None,
            reasons=["local_ocr_not_corroborated"],
        )

    monkeypatch.setattr(vision, "_call_vista_point_prompt", model_reply)
    monkeypatch.setattr(vision, "_corroborate_vista_direct_point", local_ocr)
    request = vision.VisionRecognitionPlanRequestModel(
        image_path=str(image_path), task="locate_element",
        goal=goal, provider_mode="local_grounding",
        agent_mode="execute", app_name="notepad.exe",
        write_policy={"path_graph": False, "element_memory": False, "trace": False},
        metadata={"vista_direct_grounding": {"refine": False}},
    )
    with pinned_uia_snapshot(snapshot), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(
            request=request, timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}},
            local_config={"model_name": "isolated-test-model"},
            image_path=image_path, input_image_size=ImageSize(width=500, height=260),
            goal=request.goal, observe_reuse={},
            path_graph_recall={"status": "not_requested", "candidates": []},
        )
    assert response.success is True
    assert calls == ["coarse_full"]
    return response.data["result"]


def test_conflict_is_parseable_rejection_without_automatic_uia_fallback(tmp_path, monkeypatch):
    result = _recognize(tmp_path, monkeypatch, point={"x": 100, "y": 40})
    ranked = result["candidate_result"]
    assert ranked["summary"]["vista_direct_uia_conflict_candidate_ids"]
    assert ranked["candidates"] == []
    assert ranked["recommended_candidate_id"] is None
    assert ranked["margin_to_second"] is None
    assert len(ranked["rejected"]) == 2
    assert [item["rank"] for item in ranked["rejected"]] == [1, 2]
    assert all(item["eligible"] is False for item in ranked["rejected"])
    assert all(item["element"]["interaction_policy"]["allowed"] is False for item in ranked["rejected"])
    direct = next(item for item in ranked["rejected"] if item["candidate_id"].startswith("vista_direct_"))
    assert "vista_direct_conflicts_with_exact_uia_candidate_bbox" in direct["reasons"]
    assert all("vista_direct_uia_conflict_blocks_fallback" in item["reasons"] for item in ranked["rejected"])
    assert result["recommended_target"] is None
    assert result["narrow_search_result"]["results"] == []
    assert result["narrow_search_result"]["recommended_candidate_id"] is None
    assert result["pre_click_decision"]["allowed"] is False
    assert result["pre_click_decision"]["candidate_decisions"] == []
    candidates, grounding = _parse_recognition(result)
    assert candidates.candidates == []
    assert len(candidates.rejected) == 2
    assert grounding.results == []


@pytest.mark.parametrize("point,label", [
    ({"x": 325, "y": 40}, "帮助(H)"),
    ({"x": 100, "y": 40}, "无关菜单"),
])
def test_agreement_or_unrelated_label_is_not_blanket_rejected(tmp_path, monkeypatch, point, label):
    result = _recognize(tmp_path, monkeypatch, point=point, label=label)
    ranked = result["candidate_result"]
    assert ranked["summary"]["vista_direct_uia_conflict_candidate_ids"] == []
    assert ranked["candidates"]
    assert ranked["rejected"] == []
    _parse_recognition(result)


def test_consumer_still_rejects_ineligible_item_in_eligible_collection(tmp_path, monkeypatch):
    result = deepcopy(_recognize(tmp_path, monkeypatch, point={"x": 325, "y": 40}))
    result["candidate_result"]["candidates"][0]["eligible"] = False
    with pytest.raises(ValueError, match="candidate eligibility does not match"):
        _parse_recognition(result)


def test_unverified_observation_is_reportable_but_never_executable(tmp_path, monkeypatch):
    result = _recognize(tmp_path, monkeypatch, point={"x": 100, "y": 40}, label=None)
    local = result["narrow_search_result"]
    assert len(local["results"]) == 1
    assert local["results"][0]["status"] == "unverified"
    assert local["recommended_candidate_id"] == local["results"][0]["candidate_id"]
    assert result["pre_click_decision"]["allowed"] is False
    assert result["pre_click_decision"]["selected_click_point"] is None
    assert "narrow_search_status:unverified" in result["pre_click_decision"]["candidate_decisions"][0]["reasons"]
    _, grounding = _parse_recognition(result)
    assert grounding.results[0].status == "unverified"


def test_consumer_still_rejects_inconsistent_local_recommendation(tmp_path, monkeypatch):
    result = _recognize(tmp_path, monkeypatch, point={"x": 100, "y": 40}, label=None)
    result["narrow_search_result"]["recommended_candidate_id"] = None
    with pytest.raises(ValueError, match="local grounding recommendation is inconsistent"):
        _parse_recognition(result)


def test_local_ocr_corroboration_has_its_own_timing_without_weakening_rejection(tmp_path, monkeypatch):
    result = _recognize(tmp_path, monkeypatch, point={"x": 100, "y": 40}, label=None)
    stages = [step for step in result["timings"]["steps"]
              if step["name"] == "vista_local_ocr_corroboration"]
    assert len(stages) == 1 and stages[0]["elapsed_ms"] >= 0
    assert result["pre_click_decision"]["allowed"] is False
