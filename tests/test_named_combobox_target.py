"""命名输入框保留角色和当前模式证据；不把只读下拉框当作可填写字段。"""
from types import SimpleNamespace

import pytest

from app.operation.recognition.text_match import explicit_target_label, explicit_target_role
from app.operation.recognition.control_target import uia_action_identity_matches
from app.operation.recognition.candidate_ranker import _page_element_from_screen_inventory_action, _is_text_entry_element


GOAL = 'Click the search input box labelled "Auckland Museum" at the top of the webpage'


@pytest.mark.parametrize("phrase", ["search input box", "input field", "text input box", "text area", "search field"])
def test_compound_field_role_keeps_exact_label(phrase):
    goal = f'Click the {phrase} labelled "Example query" at the top of the webpage'
    assert explicit_target_role(goal) == "input"
    assert explicit_target_label(goal) == "Example query"


@pytest.mark.parametrize("patterns,expected", [(["Value", "Text", "ExpandCollapse"], True),
    (["ExpandCollapse", "Selection"], False), (["Value"], False), (["Text"], False), ([], False)])
def test_combobox_field_identity_and_classification_require_both_current_patterns(patterns, expected):
    control = dict(name="Auckland Museum", control_type="ComboBox", patterns=patterns,
                   visible=True, enabled=True)
    assert uia_action_identity_matches(control, goal=GOAL) is expected
    action = dict(id="field", label=control["name"], role="combobox", action_type="select",
        source="windows_uia.controls", bbox={"x":235,"y":107,"w":658,"h":50},
        metadata={"control_type":"ComboBox", "patterns":patterns})
    element = _page_element_from_screen_inventory_action(action, index=0, goal=GOAL)
    assert _is_text_entry_element(element) is expected
    assert element.interaction_type == ("focus" if expected else "click")
    assert not uia_action_identity_matches({**control, "control_type":"Button", "patterns":["Invoke"]}, goal=GOAL)


@pytest.mark.parametrize("pattern", ["value", "text"])
def test_combo_readonly_pattern_still_blocks_reader(pattern):
    from app.agent.windows_text_field_reader import WindowsTextFieldReader, TextFieldReadError
    wrapper = SimpleNamespace(
        iface_value=SimpleNamespace(CurrentIsReadOnly=pattern == "value", CurrentValue=""),
        iface_text=SimpleNamespace(DocumentRange=SimpleNamespace(GetAttributeValue=lambda _:pattern == "text")))
    reader = WindowsTextFieldReader(window_manager=None, native_identity_reader=None)
    with pytest.raises(TextFieldReadError, match="text_field_target_not_writable"):
        reader._read_text(wrapper, "ComboBox")


@pytest.mark.parametrize("fault", [None, "duplicate", "incomplete", "disabled", "dropdown", "point_outside"])
def test_named_combobox_is_primary_before_model_without_weakening_identity(tmp_path, monkeypatch, fault):
    from PIL import Image
    from app.api import vision
    from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
    from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
    from modules.ocr.contracts import OCRResult
    control = dict(control_id="field", runtime_id=[42, 1], name="Auckland Museum",
        bbox={"x":235,"y":107,"w":658,"h":50}, control_type="ComboBox",
        patterns=["Value","Text","ExpandCollapse"], enabled=True, visible=True)
    controls = [control, dict(control_id="same-title", name="Auckland Museum",
        bbox={"x":235,"y":207,"w":658,"h":50}, control_type="Button",
        patterns=["Invoke"], enabled=True, visible=True)]
    snapshot = dict(status="ok", scan_complete=True, truncated=False, controls=controls)
    if fault == "duplicate":
        controls.append({**control, "control_id":"second-field", "runtime_id":[42,2]})
    elif fault == "incomplete":
        snapshot["scan_complete"] = False
    elif fault == "disabled":
        control["enabled"] = False
    elif fault == "dropdown":
        control["patterns"] = ["ExpandCollapse","Selection"]
    image = tmp_path / "synthetic.png"
    Image.new("RGB", (2560,1400), "white").save(image)
    calls = []
    point = {"x":1012,"y":120} if fault == "point_outside" else {"x":564,"y":132}
    monkeypatch.setattr(vision, "_call_vista_point_prompt", lambda **kw: calls.append(kw) or {
        "point":point, "provider":"isolated-model-boundary"})
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda p: OCRResult(image_path=str(p), matches=[]))
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(image), task="locate_element", goal=GOAL,
        agent_mode="execute", provider_mode="local_grounding", top_k=5,
        write_policy={"path_graph":False,"element_memory":False,"trace":False})
    with pinned_uia_snapshot(snapshot), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision":{"mode":"local_grounding"}}, local_config={"model_name":"isolated","endpoint":"http://unused.invalid"},
            image_path=image,input_image_size=vision.ImageSize(width=2560,height=1400),goal=GOAL,
            observe_reuse={},path_graph_recall={"status":"not_requested","candidates":[]})
    result = response.data["result"]
    assert calls
    if fault in {"duplicate", "incomplete", "disabled", "dropdown"}:
        assert calls[0]["vista_stage"] == "coarse_full"
        assert not result["candidate_result"]["summary"]["current_uia_primary_candidate_used"]
    else:
        assert calls[0]["vista_stage"] == "pathgraph_candidate_roi_refine"
        assert result["candidate_result"]["summary"]["current_uia_primary_candidate_used"]
        if fault is None:
            chosen = result["recommended_target"]
            assert chosen["element"]["evidence"]["screen_inventory_action"]["source_id"] == "field"
        else:
            from app.core.local_recognition_policy import local_recognition_selection
            with pytest.raises(ValueError):
                local_recognition_selection(result,image_path=image,viewport_size={"width":2560,"height":1400})


@pytest.mark.parametrize("number,goal,point,source_sha256", [
    ("060", "The Google Search input box containing Auckland Museum at the top of the page",
     {"x":913,"y":128}, "72082e3e0a62dfee1ea2799f00c23287c33bf7e87f9cfd2c7f86386c09bca581"),
    ("061", GOAL, {"x":1012,"y":120}, "bc2083aa78b84e9525dcf1dd9cc1e563d09bb50640f437ec5239088f7c8b7783"),
])
def test_sanitized_frozen_trace_replay_preserves_bad_point_rejection(tmp_path, monkeypatch, number, goal, point, source_sha256):
    """只重放原回执字段几何和最终模型点；不用原图、浏览历史或模型服务。"""
    from PIL import Image
    from app.api import vision
    from app.core.local_recognition_policy import local_recognition_selection
    from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
    from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
    from modules.ocr.contracts import OCRResult
    image = tmp_path / "sanitized-trace.png"
    Image.new("RGB", (2560,1400), "white").save(image)
    snapshot = dict(status="ok", scan_complete=True, truncated=False, controls=[dict(
        control_id="trace-field", name="Auckland Museum", control_type="ComboBox",
        bbox={"x":235,"y":107,"w":658,"h":50}, patterns=["Value","Text","ExpandCollapse"],
        enabled=True, visible=True)])
    calls = []
    monkeypatch.setattr(vision, "_call_vista_point_prompt", lambda **kw: calls.append(kw) or {
        "point":point, "provider":"recorded-point-only"})
    monkeypatch.setattr(vision.ocr_service, "scan_image", lambda p: OCRResult(image_path=str(p), matches=[]))
    request = vision.VisionRecognitionPlanRequestModel(image_path=str(image), task="locate_element", goal=goal,
        agent_mode="execute", provider_mode="local_grounding", top_k=5,
        write_policy={"path_graph":False,"element_memory":False,"trace":False})
    with pinned_uia_snapshot(snapshot), pinned_runtime_output_root(tmp_path):
        response = vision._recognition_plan_from_vista_point(request=request, timer=RuntimeTimer(),
            config={"vision":{"mode":"local_grounding"}}, local_config={"model_name":"isolated","endpoint":"http://unused.invalid"},
            image_path=image,input_image_size=vision.ImageSize(width=2560,height=1400),goal=goal,
            observe_reuse={},path_graph_recall={"status":"not_requested","candidates":[]})
    result = response.data["result"]
    if number == "061":
        assert calls[0]["vista_stage"] == "pathgraph_candidate_roi_refine"
        literal = result["candidate_result"]["summary"]["current_uia_literal_identity"]
        assert literal["role"] == "input" and literal["match_count"] == 1
    else:
        assert not result["candidate_result"]["summary"]["current_uia_literal_identity"]["entered"]
    with pytest.raises(ValueError):
        local_recognition_selection(result,image_path=image,viewport_size={"width":2560,"height":1400})
    print({"trace":number, "source_sha256":source_sha256, "first_stage":calls[0]["vista_stage"],
           "original_point_rejected":True, "input_executed":False, "original_image_used":False})
