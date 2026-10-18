"""直接引号标签不能丢成整句指令，也不能命中相反的按钮。"""
import pytest

from app.operation.recognition.text_match import explicit_target_label
from app.operation.recognition.candidate_ranker import _goal_label_match
from app.operation.recognition.control_target import uia_action_identity_matches


@pytest.mark.parametrize("goal,label", [
    ("Click the '不保存' (Don't save) button in the save-changes dialog", "不保存"),
    ('Click the "Discard" button in the dialog', "Discard"),
    ("Select 'Don't save' in the dialog", "Don't save"),
    ("Click ‘Don't save’ in the dialog", "Don't save"),
    ('Click the button "Keep editing"', "Keep editing"),
])
def test_direct_quoted_target_is_extracted(goal, label):
    assert explicit_target_label(goal) == label


@pytest.mark.parametrize("label,expected", [("不保存(N)", True), ("保存(S)", False), ("取消", False)])
def test_negated_label_identity_preserved_with_accelerator(label, expected):
    goal = "Click the '不保存' (Don't save) button in the save-changes dialog"
    control = {"name": label, "control_type": "Button", "patterns": ["Invoke"], "visible": True, "enabled": True}
    assert _goal_label_match(goal, [label], negated=False) is expected
    assert uia_action_identity_matches(control, goal=goal) is expected


@pytest.mark.parametrize("goal", [
    'Click near the text "Save"',
    'Read "Save", then decide what to click',
    'Click "Save" or "Discard"',
    'Click "Save" button or "Discard" button',
    "Click 'unterminated",
])
def test_context_and_ambiguous_quotes_are_not_exact_target(goal):
    assert explicit_target_label(goal) is None


def test_negative_instruction_is_not_positive_target():
    goal = 'Do not click "Save"'
    assert _goal_label_match(goal, ["Save"], negated=False) is False
    assert _goal_label_match(goal, ["Save"], negated=True) is True


@pytest.mark.parametrize("goal", ['Click the link "Settings"', 'Click "Settings" link',
                                  'Click the field "Settings"', 'Click "Settings" input'])
def test_direct_quote_role_does_not_match_homonymous_button(goal):
    control = dict(name="Settings", control_type="Button", patterns=["Invoke"], visible=True, enabled=True)
    assert uia_action_identity_matches(control, goal=goal) is False


def test_recognition_prompt_keeps_literal_label_ahead_of_translation():
    from app.api.vision import _vista_direct_prompt
    goal = "Click the '不保存' (Don't save) button in the save-changes dialog"
    prompt = _vista_direct_prompt(goal)
    assert prompt.startswith('Locate the exact visible target labelled "不保存".')
    assert goal in prompt


@pytest.mark.parametrize("fault", [None, "duplicate", "offscreen_duplicate", "partly_visible_duplicate", "incomplete", "disabled", "wrong_role", "caption_suffix", "point_outside"])
def test_real_recognition_route_binds_quoted_link_to_exact_hyperlink(tmp_path, monkeypatch, fault):
    from PIL import Image
    from app.api import vision
    from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
    from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
    from modules.ocr.contracts import OCRResult

    goal = 'Click the result link labelled "csv — CSV File Reading and Writing"'
    controls = [
        dict(control_id="target", name="csv — CSV File Reading and Writing",
             bbox={"x": 429, "y": 443, "w": 273, "h": 22}, control_type="Hyperlink",
             patterns=["Invoke", "Value"], visible=True, enabled=True),
        dict(control_id="other", name="csv", bbox={"x": 429, "y": 406, "w": 24, "h": 22},
             control_type="Hyperlink", patterns=["Invoke", "Value"], visible=True, enabled=True),
    ]
    image = tmp_path / "page.png"
    Image.new("RGB", (800, 600), "white").save(image)
    calls = []
    point = {"x": 416, "y": 463} if fault == "point_outside" else {"x": 565, "y": 454}
    monkeypatch.setattr(vision, "_call_vista_point_prompt",
                        lambda **kwargs: calls.append(kwargs) or {"point": point,
                                                                   "provider": "isolated-model-boundary"})
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda p: OCRResult(image_path=str(p), matches=[]))
    snapshot = dict(status="ok", provider="windows_uia", scan_complete=True, truncated=False, controls=controls)
    if fault == "duplicate":
        controls.append({**controls[0], "control_id": "duplicate"})
    elif fault in {"offscreen_duplicate", "partly_visible_duplicate"}:
        controls.append({**controls[0], "control_id": "duplicate", "visible": False,
                         "bbox": {"x": 429, "y": 4493 if fault == "offscreen_duplicate" else 590, "w": 273, "h": 22}})
    elif fault == "incomplete":
        snapshot["scan_complete"] = False
    elif fault == "disabled":
        controls[0]["enabled"] = False
    elif fault == "wrong_role":
        controls[0]["control_type"] = "Button"
    elif fault == "caption_suffix":
        controls[0]["name"] += " (A)"
    request = vision.VisionRecognitionPlanRequestModel(
        image_path=str(image), task="locate_element", goal=goal, app_name="msedge.exe",
        agent_mode="execute", provider_mode="local_grounding", top_k=5,
        write_policy={"path_graph": False, "element_memory": False, "trace": False})
    with pinned_uia_snapshot(snapshot), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(
            request=request, timer=RuntimeTimer(), config={"vision": {"mode": "local_grounding"}},
            local_config={"model_name": "isolated", "endpoint": "http://unused.invalid"},
            image_path=image, input_image_size=vision.ImageSize(width=800, height=600), goal=goal,
            observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []})
    result = response.data["result"]
    assert len(calls) == 1
    if fault not in {None, "offscreen_duplicate", "point_outside"}:
        assert result["candidate_result"]["summary"]["current_uia_primary_candidate_used"] is False
        return
    assert calls[0]["vista_stage"] == "pathgraph_candidate_roi_refine"
    assert result["candidate_result"]["summary"]["current_uia_primary_candidate_used"] is True
    crop = calls[0]["image_preprocess"]["crop_bounds_original"]
    assert crop["y"] > 428
    assert crop["y"] <= 443 and crop["y"] + crop["h"] >= 465
    if fault == "point_outside":
        from app.core.local_recognition_policy import local_recognition_selection
        with pytest.raises(ValueError, match="outside candidate"):
            local_recognition_selection(result, image_path=image, viewport_size={"width": 800, "height": 600})
        return
    chosen = next(c for c in result["candidate_result"]["candidates"]
                  if c["candidate_id"] == result["candidate_result"]["recommended_candidate_id"])
    assert chosen["element"]["evidence"]["screen_inventory_action"]["source_id"] == "target"


@pytest.mark.parametrize("point,expected", [({"x": 214, "y": 82}, True), ({"x": 161, "y": 84}, False)])
@pytest.mark.parametrize("tree_case", ["unique", "duplicate", "truncated", "disabled"])
def test_real_recognition_route_binds_quoted_button_not_opposite(tmp_path, monkeypatch, point, expected, tree_case):
    from PIL import Image
    from app.api import vision
    from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
    from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
    from modules.ocr.contracts import OCRResult
    goal = "Click the '不保存' (Don't save) button in the save-changes dialog"
    controls = []
    for cid, name, box in [
        ("save", "保存(S)", {"x": 88, "y": 70, "w": 75, "h": 25}),
        ("discard", "不保存(N)", {"x": 169, "y": 70, "w": 90, "h": 25}),
        ("cancel", "取消", {"x": 265, "y": 70, "w": 75, "h": 25}),
    ]:
        control = dict(control_id=cid, name=name, bbox=box, control_type="Button", patterns=["Invoke"],
                       visible=True, enabled=True)
        controls.append(control)
    image = tmp_path / "dialog.png"
    Image.new("RGB", (350, 104), "white").save(image)
    calls = []
    def infer(**kwargs):
        calls.append(kwargs)
        return {"point": dict(point), "provider": "isolated-model-boundary"}
    monkeypatch.setattr(vision, "_call_vista_point_prompt", infer)
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda p: OCRResult(image_path=str(p), matches=[]))
    snapshot = dict(status="ok", provider="windows_uia", scan_complete=True, truncated=False, controls=controls)
    if tree_case == "duplicate":
        controls.append({**controls[1], "control_id": "second-discard"})
    if tree_case == "truncated":
        snapshot.update(scan_complete=False, truncated=True)
    if tree_case == "disabled":
        controls[1]["enabled"] = False
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(image), task="locate_element", goal=goal,
        app_name="notepad.exe", agent_mode="execute", provider_mode="local_grounding", top_k=5,
        write_policy={"path_graph": False, "element_memory": False, "trace": False})
    with pinned_uia_snapshot(snapshot), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision": {"mode": "local_grounding"}}, local_config={"model_name": "isolated", "endpoint": "http://unused.invalid"},
            image_path=image, input_image_size=vision.ImageSize(width=350, height=104), goal=goal,
            observe_reuse={}, path_graph_recall={"status": "not_requested", "candidates": []})
    result = response.data["result"]
    # 已有唯一明确标签时，首次模型输入就应包含本帧真实控件，不能先失败再回退。
    assert len(calls) == 1
    if tree_case != "unique":
        assert calls[0]["vista_stage"] == "coarse_full"
        assert result["candidate_result"]["summary"]["current_uia_primary_candidate_used"] is False
        return
    assert calls[0]["vista_stage"] == "pathgraph_candidate_roi_refine"
    assert "不保存(N)" in calls[0]["prompt"]
    ranking = result["candidate_result"]
    if expected:
        chosen = next(c for c in ranking["candidates"] if c["candidate_id"] == ranking["recommended_candidate_id"])
        assert chosen["element"]["evidence"]["screen_inventory_action"]["source_id"] == "discard"
        assert not chosen["candidate_id"].startswith("vista_direct_")
    else:
        assert result["pre_click_decision"]["allowed"] is False
        from app.core.local_recognition_policy import local_recognition_selection
        with pytest.raises(ValueError, match="outside candidate"):
            local_recognition_selection(result, image_path=image, viewport_size={"width": 350, "height": 104})
    # UIA 与模型点的双重来源不冒充 OCR 证据。
    local = result["narrow_search_result"]["results"][0]
    assert local["coordinate_source"] == "vista_point_v1"
    assert "matched_local_ocr_text" not in local["reasons"]
