"""原生快捷字母标签不能被后置用途说明改成另一个动作目标。"""
import pytest
from PIL import Image

from app.api import vision
from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
from app.core.local_recognition_policy import local_recognition_selection
from app.operation.recognition.candidate_ranker import _explicit_goal_action_terms, _goal_label_match
from app.operation.recognition.text_match import explicit_target_label, explicit_target_role
from app.operation.screen_reading.uia_provider import pinned_uia_snapshot


GOAL = "Click the 打开(O) button at the bottom right of the Windows file picker dialog to confirm the selected file"


@pytest.mark.parametrize("goal,label,role", [
    (GOAL, "打开(O)", "button"),
    ("Click the Save (&S) button to continue editing", "Save (&S)", "button"),
    ("Select Options(O) tab in the settings window", "Options(O)", "tab"),
    ("Click 保存（S） button to continue", "保存（S）", "button"),
])
def test_native_mnemonic_is_the_action_object(goal, label, role):
    assert explicit_target_label(goal) == label
    assert explicit_target_role(goal) == role


def test_confirmation_purpose_does_not_replace_open_identity():
    assert _explicit_goal_action_terms(GOAL) == set()
    assert _goal_label_match(GOAL, ["打开(O)"], negated=False)
    assert not _goal_label_match(GOAL, ["打开"], negated=False)


@pytest.mark.parametrize("goal", [
    "Click the submit button in Account details",
    "Click the continue button to leave Advanced options",
    "Click the file upload button next to File input",
    "Click 打开(O) or 取消(C) button",
    "Click 打开(O) button or 取消(C) button",
    "Click the input inside 打开(O) button",
    "Do not click 打开(O) button",
    "Click 打开(O) button then click Submit",
    "Click 打开(O) button and click Submit",
    "Click 打开(O) button then press Enter",
    "Click Save (Draft) button",
    "Click Save (SS) button",
    "Click Open(O) button or Cancel",
    "Click Open(O) button in the dialog and submit the form",
    "Click Open(O) button to confirm the file and send the message",
    "Click Open(O) button in the dialog; do not do that",
    "Click Open(O) button beside Cancel(C) button",
])
def test_context_alternatives_and_multi_action_are_not_literal_targets(goal):
    assert explicit_target_label(goal) is None


@pytest.mark.parametrize("case", ["correct", "wrong_control", "outside", "duplicate"])
def test_native_confirm_button_keeps_current_identity(tmp_path, monkeypatch, case):
    path = tmp_path / "native.png"
    Image.new("RGB", (1184, 681), "white").save(path)
    controls = [
        {"control_id": "arrow1", "name": "打开", "control_type": "Button",
         "bbox": {"x": 951, "y": 613, "w": 15, "h": 24}},
        {"control_id": "arrow2", "name": "打开", "control_type": "Button",
         "bbox": {"x": 1144, "y": 613, "w": 15, "h": 24}},
        {"control_id": "open", "name": "打开(O)", "control_type": "Button",
         "bbox": {"x": 979, "y": 643, "w": 88, "h": 26}},
    ]
    for index, control in enumerate(controls):
        control.update(visible=True, enabled=True, patterns=["Invoke"], runtime_id=[42, index + 1])
    if case == "duplicate":
        controls.append({**controls[-1], "control_id": "duplicate", "runtime_id": [42, 4]})
    calls = []

    def model(**kwargs):
        calls.append(kwargs)
        point = {"x": 1025, "y": 653} if len(calls) == 1 else {"x": 979, "y": 655}
        if case == "wrong_control":
            point = {"x": 958, "y": 625}
        if case == "outside":
            point = {"x": 960, "y": 655}
        return {"point": point,
                "provider": "recorded-model-boundary"}

    monkeypatch.setattr(vision, "_call_vista_point_prompt", model)
    monkeypatch.setattr(vision, "_call_vista_point_grounding", model)
    from modules.ocr.contracts import OCRResult
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda image: OCRResult(image_path=str(image), matches=[]))
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(path), task="locate_element",
        goal=GOAL, provider_mode="local_grounding", agent_mode="execute",
        write_policy={"path_graph": False, "element_memory": False, "trace": False},
        metadata={"vista_direct_grounding": {"refine": True, "max_edge": 640}})
    snapshot = {"provider": "windows_uia", "status": "ok", "scan_complete": True,
                "truncated": False, "controls": controls}
    with pinned_uia_snapshot(snapshot), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}}, local_config={"model_name": "offline"},
            image_path=path, input_image_size=vision.ImageSize(width=1184, height=681),
            goal=GOAL, observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []})
    result = response.data["result"]
    if case == "duplicate":
        assert result["recommended_target"] is None
        with pytest.raises(ValueError, match="no unique recommended candidate"):
            local_recognition_selection(result, image_path=path,
                viewport_size={"width": 1184, "height": 681})
        return
    if case in {"wrong_control", "outside"}:
        # 推荐仅作诊断；即时模式也必须拒绝未落入当前目标的模型点。
        assert result["narrow_search_result"]["results"][0]["status"] == "point_outside_candidate"
        with pytest.raises(ValueError, match="local recognition point outside candidate"):
            local_recognition_selection(result, image_path=path,
                viewport_size={"width": 1184, "height": 681})
        return
    assert result["recommended_target"] is not None
    assert result["recommended_target"]["label"] == "打开(O)"
    assert result["candidate_result"]["summary"]["current_uia_literal_identity"]["match_count"] == 1
    selected = next(item for item in result["candidate_result"]["candidates"]
                    if item["candidate_id"] == result["recommended_target"]["candidate_id"])
    assert selected["element"]["evidence"]["screen_inventory_action"]["source_id"] == "open"
    assert local_recognition_selection(result, image_path=path,
        viewport_size={"width": 1184, "height": 681})["selected_click_point"] == {"x": 1025, "y": 653}
