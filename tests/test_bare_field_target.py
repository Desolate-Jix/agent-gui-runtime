"""字段名词短语保留同帧 UIA 身份，不依赖调用方补 Click。"""
import pytest

from app.operation.recognition.control_target import _field_target_label, generic_field_target, uia_action_identity_matches
from app.operation.recognition.text_match import explicit_target_label
from tests.test_named_field_target import field


@pytest.mark.parametrize("goal", ["Search box at the top-left of Google Maps", "search box", "The search field",
    "Input box at the top of the webpage", "An input field on the left", "Search input box in the webpage",
    "The text box below the toolbar", "Text field beside the label", "Text area", "Textbox", "Textarea"])
def test_bare_field_head_is_generic_and_keeps_dynamic_field_identity(goal):
    assert _field_target_label(goal) == ""
    assert generic_field_target(goal)
    assert uia_action_identity_matches(field("\ufffc", kind="ComboBox"), goal=goal)
    assert not uia_action_identity_matches(field("\ufffc", kind="Button", patterns=["Invoke"]), goal=goal)
    assert _field_target_label("Click " + goal) == ""


@pytest.mark.parametrize("goal", ['Input box labelled "Customer Email" at the top of the webpage',
    'Search box named "Google search"', 'Text field labeled "Address:"'])
def test_bare_explicit_labels_remain_exact_not_generic(goal):
    label = explicit_target_label(goal)
    assert label and not generic_field_target(goal)
    assert uia_action_identity_matches(field(label), goal=goal)
    assert not uia_action_identity_matches(field("different current value"), goal=goal)


@pytest.mark.parametrize("goal", ["Back button near the search box", "Search button", "Search box button",
    "Search box icon", "Search box label", "Text inside the search box", "Word inside the input box",
    "The word Search inside the input field", "Navigate to the input box", "Open the search box",
    "Do not focus the search box", "Not the search box", "Search box, then click Back",
    "Search box at the top then click Back", "Click the word Search inside the input box"])
def test_bare_nonfield_or_compound_target_is_not_promoted(goal):
    assert _field_target_label(goal) is None
    assert not generic_field_target(goal)


@pytest.mark.parametrize("point", [{"x":100,"y":113}, {"x":97,"y":113}, {"x":100,"y":140}])
@pytest.mark.parametrize("duplicate", [False, True])
def test_candidate05_bare_goal_preserves_real_uia_identity_through_field_binding(tmp_path,monkeypatch,point,duplicate):
    from PIL import Image
    from app.api import vision
    from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
    from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
    from app.desktop_review.input_sequence import _focus_field_binding
    from modules.ocr.contracts import OCRResult
    image=tmp_path/"synthetic-bare-field.png"
    Image.new("RGB",(800,1155),"white").save(image)
    goal="Search box at the top-left of Google Maps"
    control={**field("\ufffc",kind="ComboBox"),"control_id":"uia_57_ucc_1",
        "runtime_id":[42,7606418,4,60,24,4621],"bbox":{"x":84,"y":103,"w":206,"h":24}}
    raw={"status":"ok","scan_complete":True,"truncated":False,
        "window":{"handle":11,"process_id":22,"bbox":{"x":0,"y":0,"w":800,"h":1155}},
        "controls":[control]}
    if duplicate:
        raw["controls"].append({**control,"control_id":"other-field","runtime_id":[42,999]})
    calls=[]
    monkeypatch.setattr(vision,"_call_vista_point_prompt",lambda **kw:calls.append(kw) or
        {"point":dict(point),"provider":"recorded-point-only"})
    monkeypatch.setattr(vision.ocr_service,"scan_image",lambda p:OCRResult(image_path=str(p),matches=[]))
    request=vision.VisionRecognitionPlanRequestModel(image_path=str(image),task="locate_element",goal=goal,
        agent_mode="execute",provider_mode="local_grounding",top_k=5,
        write_policy={"path_graph":False,"element_memory":False,"trace":False})
    with pinned_uia_snapshot(raw),pinned_runtime_output_root(tmp_path):
        response=vision._recognition_plan_from_vista_point(request=request,timer=RuntimeTimer(),
            config={"vision":{"mode":"local_grounding"}},local_config={"model_name":"isolated","endpoint":"http://unused.invalid"},
            image_path=image,input_image_size=vision.ImageSize(width=800,height=1155),goal=goal,
            observe_reuse={},path_graph_recall={"status":"not_requested","candidates":[]})
    plan=response.data["result"]
    assert len(calls)==1
    if point["y"]==140 or duplicate:
        assert plan["recommended_target"] is None
        assert plan["candidate_result"]["summary"]["vista_direct_current_uia_identity_rejection"]==(
            "generic_field_current_uia_point_missing" if point["y"]==140 else "vista_direct_current_uia_identity_ambiguous")
        return
    selected=plan["recommended_target"]
    assert selected["element"]["evidence"]["screen_inventory_action"]["source_id"]==control["control_id"]
    assert selected["element"]["bbox"]==control["bbox"]
    identity={"contract_version":"windows_native_identity_observation_v1","provider":"windows_native_identity",
        "status":"observed","target_window_handle":11,"process_id":22,"process_create_time":123.0,
        "executable_path":"c:\\fixture.exe"}
    binding=_focus_field_binding({"recognition_plan":plan,"selected_click_point":point,
        "selected_click_point_coordinate_space":"capture_image_pixels",
        "live_capture":{"image_path":str(image),"window_size":{"width":800,"height":1155}}},
        {"target_identity":identity,"target_window_geometry":{"coordinate_space":"screen_pixels",
            "rect_format":"ltrb","rect":[889,90,1689,1245]}},{"handle":11,"process_id":22})
    assert binding["runtime_id"]==control["runtime_id"] and binding["bbox"]==control["bbox"]
