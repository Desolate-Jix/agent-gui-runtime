"""当前 UIA 与 VISTA 直接点收敛的原生契约（不启动模型或 GUI）。"""

from copy import deepcopy

from PIL import Image

from app.agent.live_runtime_composition import _parse_recognition
from app.api import vision
from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
from app.vision.schemas import ImageSize
from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch


def _control(*, control_id="fresh-help", name="帮助(H)", bbox=None):
    return {
        "provider": "windows_uia",
        "control_id": control_id,
        "name": name,
        "control_type": "MenuItem",
        "enabled": True,
        "visible": True,
        "bbox": bbox or {"x": 223, "y": 31, "w": 55, "h": 19},
        "patterns": ["Invoke", "ExpandCollapse"],
    }


def _recognize(
    tmp_path,
    monkeypatch,
    *,
    controls=(),
    point={"x": 254, "y": 41},
    ocr_grounded=True,
    top_k=5,
    observe_reuse=None,
    uia_status="ok",
    target_text="帮助(H)",
    goal="帮助(H)",
):
    image_path = tmp_path / "fresh-notepad.png"
    Image.new("RGB", (500, 260), "white").save(image_path)
    snapshot = {
        "provider": "windows_uia",
        "provider_version": "windows_uia_provider_v1",
        "status": uia_status,
        "controls": [deepcopy(item) for item in controls],
    }
    calls = []

    def model_reply(**kwargs):
        calls.append(kwargs["vista_stage"])
        return {"point": dict(point), "provider": "synthetic-vista-boundary"}

    def scan_image(path):
        if not ocr_grounded:
            return OCRResult(image_path=str(path), matches=[])
        # 同一张截图中的 Help 文本框为 (223, 31, 55, 19)：直接候选和
        # 已收敛的 UIA 候选裁剪原点不同，外部 OCR 需返回各自裁剪坐标。
        if "vista_direct_" in str(path):
            text_bbox = OCRBoundingBox(x=17, y=31, width=55, height=19)
        else:
            text_bbox = OCRBoundingBox(x=24, y=24, width=55, height=19)
        return OCRResult(
            image_path=str(path),
            matches=[
                OCRTextMatch(
                    text="帮助(H)",
                    score=0.99,
                    bbox=text_bbox,
                )
            ],
        )

    monkeypatch.setattr(vision, "_call_vista_point_prompt", model_reply)
    monkeypatch.setattr(vision.ocr_service, "scan_image", scan_image)
    request = vision.VisionRecognitionPlanRequestModel(
        image_path=str(image_path),
        task="locate_element",
        goal=goal,
        provider_mode="local_grounding",
        agent_mode="execute",
        app_name="notepad.exe",
        top_k=top_k,
        write_policy={"path_graph": False, "element_memory": False, "trace": False},
        metadata={
            "target_text": target_text,
            "vista_direct_grounding": {"enabled": True, "refine": False, "max_edge": 1024},
        },
    )
    with pinned_uia_snapshot(snapshot), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(
            request=request,
            timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}},
            local_config={"model_name": "isolated-test-vista"},
            image_path=image_path,
            input_image_size=ImageSize(width=500, height=260),
            goal=request.goal,
            observe_reuse=observe_reuse or {},
            path_graph_recall={"status": "not_requested", "candidates": []},
        )
    assert response.success is True
    assert calls == ["coarse_full"]
    return response.data["result"]


def _uia_candidate(result):
    return next(
        item
        for item in result["candidate_result"]["candidates"]
        if "screen_inventory_action" in item["candidate_id"]
    )


def test_exact_current_uia_identity_replaces_synthetic_direct_candidate(tmp_path, monkeypatch):
    result = _recognize(tmp_path, monkeypatch, controls=[_control()])
    ranked = result["candidate_result"]
    local = result["narrow_search_result"]
    decision = result["pre_click_decision"]

    assert len(ranked["candidates"]) == 1
    candidate = ranked["candidates"][0]
    assert candidate["role"] == "menu_item"
    assert not candidate["candidate_id"].startswith("vista_direct_")
    assert candidate["candidate_id"] == ranked["recommended_candidate_id"]
    assert candidate["candidate_id"] == local["recommended_candidate_id"]
    assert candidate["candidate_id"] == decision["selected_candidate_id"]
    assert all(not item["candidate_id"].startswith("vista_direct_") for item in ranked["candidates"])
    assert len(local["results"]) == 1
    assert ranked["summary"]["vista_point_inside_candidate_bbox"] is True
    assert local["results"][0]["candidate_id"] == candidate["candidate_id"]
    assert local["results"][0]["status"] == "grounded"
    assert decision["allowed"] is True
    _parse_recognition(result)


def test_reconciled_identity_does_not_inflate_small_score_margin(tmp_path, monkeypatch):
    result = _recognize(
        tmp_path, monkeypatch,
        goal="Locate the 帮助(H) Help menu in the Notepad menu bar. Locate only, do not execute input.",
        controls=[_control(), _control(control_id="file", name="文件(F)", bbox={"x": 8, "y": 31, "w": 52, "h": 19})],
    )
    ranked = result["candidate_result"]
    assert ranked["summary"]["vista_direct_current_uia_identity_reconciled"] is True
    expected_margin = round(ranked["candidates"][0]["score"] - ranked["candidates"][1]["score"], 4)
    assert ranked["margin_to_second"] == expected_margin < 0.2
    assert result["pre_click_decision"]["allowed"] is False
    assert "top_candidate_margin_too_small" in result["pre_click_decision"]["reasons"]
    _parse_recognition(result)


def test_exact_current_uia_without_ocr_remains_unverified_and_not_executable(tmp_path, monkeypatch):
    result = _recognize(tmp_path, monkeypatch, controls=[_control()], ocr_grounded=False)
    ranked = result["candidate_result"]
    local = result["narrow_search_result"]
    decision = result["pre_click_decision"]

    assert len(ranked["candidates"]) == len(local["results"]) == 1
    assert ranked["recommended_candidate_id"] == local["recommended_candidate_id"]
    assert local["results"][0]["status"] == "unverified"
    assert decision["allowed"] is False
    assert decision["selected_click_point"] is None
    _parse_recognition(result)


def test_duplicate_exact_current_uia_is_explicitly_rejected_before_top_k(tmp_path, monkeypatch):
    result = _recognize(
        tmp_path,
        monkeypatch,
        controls=[_control(control_id="help-a"), _control(control_id="help-b")],
        top_k=1,
    )
    ranked = result["candidate_result"]
    local = result["narrow_search_result"]
    decision = result["pre_click_decision"]

    assert ranked["candidates"] == []
    assert ranked["recommended_candidate_id"] is None
    assert ranked["rejected"]
    assert all(item["eligible"] is False for item in ranked["rejected"])
    assert local["recommended_candidate_id"] is None
    assert all(item["status"] != "grounded" for item in local["results"])
    assert decision["allowed"] is False
    assert decision["selected_candidate_id"] is None
    _parse_recognition(result)


def test_exact_current_uia_point_outside_retains_full_rejection(tmp_path, monkeypatch):
    result = _recognize(tmp_path, monkeypatch, controls=[_control()], point={"x": 100, "y": 40})
    ranked = result["candidate_result"]

    assert ranked["candidates"] == []
    assert ranked["recommended_candidate_id"] is None
    assert ranked["rejected"]
    assert result["narrow_search_result"]["recommended_candidate_id"] is None
    assert result["pre_click_decision"]["allowed"] is False
    assert result["pre_click_decision"]["selected_candidate_id"] is None
    _parse_recognition(result)


def test_unrelated_overlapping_uia_is_not_promoted_or_labeled_outside(tmp_path, monkeypatch):
    result = _recognize(
        tmp_path,
        monkeypatch,
        controls=[_control(name="无关菜单")],
        ocr_grounded=False,
    )
    ranked = result["candidate_result"]
    local = result["narrow_search_result"]
    decision = result["pre_click_decision"]

    uia = _uia_candidate(result)
    uia_local = next(item for item in local["results"] if item["candidate_id"] == uia["candidate_id"])
    assert uia["candidate_id"] != local["recommended_candidate_id"]
    assert uia_local["status"] not in {"grounded", "point_outside_candidate"}
    assert decision["allowed"] is False
    assert decision["selected_candidate_id"] is None
    _parse_recognition(result)


def test_no_current_uia_retains_direct_candidate_path(tmp_path, monkeypatch):
    result = _recognize(tmp_path, monkeypatch, controls=[], uia_status="failed")
    ranked = result["candidate_result"]

    assert len(ranked["candidates"]) == 1
    assert ranked["candidates"][0]["candidate_id"].startswith("vista_direct_")
    assert result["narrow_search_result"]["recommended_candidate_id"] == ranked["recommended_candidate_id"]
    _parse_recognition(result)


def test_old_observe_inventory_cannot_promote_uia_identity(tmp_path, monkeypatch):
    old_inventory = {
        "contract_version": "screen_inventory_v1",
        "source_contract": "screen_reading_v1",
        "goal": "帮助(H)",
        "summary": {"available_action_count": 1, "page_element_count": 0},
        "available_actions": [
            {
                "id": "old-help",
                "contract_version": "available_action_v1",
                "label": "帮助(H)",
                "role": "menu_item",
                "action_type": "click",
                "bbox": {"x": 223, "y": 31, "w": 55, "h": 19},
                "click_point": {"x": 250, "y": 40},
                "confidence": 0.9,
                "coordinate_confidence": "high",
                "source": "windows_uia.controls",
                "source_id": "old-help",
                "metadata": {"control_type": "MenuItem", "patterns": ["Invoke"]},
            }
        ],
        "page_elements": [],
        "cards": [],
    }
    result = _recognize(
        tmp_path,
        monkeypatch,
        controls=[],
        observe_reuse={"screen_inventory": old_inventory},
    )
    ranked = result["candidate_result"]
    local = result["narrow_search_result"]
    decision = result["pre_click_decision"]

    direct = next(item for item in ranked["candidates"] if item["candidate_id"].startswith("vista_direct_"))
    assert local["recommended_candidate_id"] == direct["candidate_id"]
    assert decision["selected_candidate_id"] == direct["candidate_id"]
    _parse_recognition(result)
