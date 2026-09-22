"""命名字段不能借任意输入框的角色或模型落点丢失完整标签。"""
import pytest

from app.operation.recognition.control_target import generic_field_target, uia_action_identity_matches


def field(name, *, kind="Edit", patterns=None):
    return {"name": name, "control_type": kind, "patterns": patterns or ["Value", "Text"],
            "visible": True, "enabled": True}


@pytest.mark.parametrize("goal,label", [
    ("Click the Quick search input box", "Quick search"),
    ("Right click inside the Google search input box", "Google search"),
    ("Locate the Email input field", "Email"),
    ("Focus in the Message text area", "Message"),
    ("Click the Quick search box", "Quick search"),
])
def test_named_field_requires_complete_label_and_field_role(goal, label):
    assert generic_field_target(goal) is False
    assert uia_action_identity_matches(field(label), goal=goal) is True
    for wrong in ["Address bar", "地址和搜索栏", "Search", "Quick", "current query", ""]:
        assert uia_action_identity_matches(field(wrong), goal=goal) is False
    assert uia_action_identity_matches(field(label, kind="Button", patterns=["Invoke"]), goal=goal) is False


@pytest.mark.parametrize("goal", [
    "Click the input box", "Right click inside the text area of the document",
    "Click the search input box", "Click within the search field", "Focus in the text area",
    "Locate an input field", "Click a textbox", "Click the textarea", "Click the combobox",
])
def test_genuine_generic_field_keeps_dynamic_value_identity(goal):
    assert generic_field_target(goal) is True
    assert uia_action_identity_matches(field("dynamic value"), goal=goal) is True


@pytest.mark.parametrize("goal", [
    "Click the word Quick inside the search input box",
    "Click Save inside the input box", "Click the button inside the text area",
    "Do not click the Quick search input box",
])
def test_contained_target_and_negation_do_not_become_named_field(goal):
    assert generic_field_target(goal) is False
    assert uia_action_identity_matches(field("dynamic value"), goal=goal) is False


def test_named_field_label_normalization_preserves_unicode_and_full_words():
    goal = "Click the Customer Email input box"
    assert uia_action_identity_matches(field("customer   email"), goal=goal)
    assert not uia_action_identity_matches(field("Email"), goal=goal)
    assert not uia_action_identity_matches(field("Customer Email backup"), goal=goal)
    assert uia_action_identity_matches(field("邮件地址"), goal="Click the 邮件地址 input box")


@pytest.mark.parametrize("label", ["Address:", "Address :", "Address："])
def test_named_field_accepts_terminal_label_separator(label):
    assert uia_action_identity_matches(field(label), goal="Click the Address input field")


@pytest.mark.parametrize("label", ["Address: backup", "Address backup:", "Add:ress", "Address::", "Address?"])
def test_named_field_separator_normalization_does_not_drop_label_content(label):
    assert not uia_action_identity_matches(field(label), goal="Click the Address input field")


def test_quoted_label_keeps_existing_separator_matching_and_structured_target_stays_exact():
    target = {"contract_version": "recognition_control_target_v1", "label": "Address",
              "role": "input", "source_binding_sha256": "a" * 64}
    assert uia_action_identity_matches(field("Address:"), goal='Click the input labelled "Address"')
    assert not uia_action_identity_matches(field("Address:"), goal="Click the Address input field", control_target=target)


def test_structured_and_quoted_targets_keep_existing_exact_label_contract():
    target = {"contract_version": "recognition_control_target_v1", "label": "Quick search",
              "role": "input", "source_binding_sha256": "a" * 64}
    goal = "Click the Quick search input box"
    assert uia_action_identity_matches(field("Quick search"), goal=goal, control_target=target)
    assert not uia_action_identity_matches(field("Address bar"), goal=goal, control_target=target)
    assert not generic_field_target('Click the input labelled "Quick search"')
    assert uia_action_identity_matches(field("Quick search"), goal='Click the input labelled "Quick search"')


@pytest.mark.parametrize("goal", [
    "Right click the Google search input box at the top of the page",
    "Locate the Google search input box at the top of the page",
    "Right click inside the Google search input box containing Wikipedia Nelson",
])
def test_previously_generic_qualified_field_does_not_bind_arbitrary_dynamic_value(goal):
    assert generic_field_target(goal) is False
    assert not uia_action_identity_matches(field("TimaruDunedin", kind="ComboBox"), goal=goal)
    assert uia_action_identity_matches(field("Google search", kind="ComboBox"), goal=goal)


@pytest.mark.parametrize("goal,expected", [
    ("Click the Google search input field", "named_field_current_uia_missing"),
    ("Click the Quick search input box", "named_field_current_uia_missing"),
    ("Click the input field", "generic_field_current_uia_point_missing"),
    ("Click the word Quick inside the input box", None),
])
def test_zero_identity_match_is_not_a_synthetic_button_for_named_field(goal,expected):
    from app.api import vision
    inventory={"status":"ready","uia_scan_complete":True,"uia_scan_truncated":False,
        "screen_reading":{"source_layers":{"windows_uia":{"status":"ok",
            "scan_complete":True,"truncated":False,"controls":[field("Google Maps",kind="ComboBox")]}}}}
    found,error=vision._vista_direct_current_uia_identity(goal=goal,target_text=None,
        point={"x":1012,"y":120},fast_inventory=inventory,candidates=[])
    assert found is None
    assert error==expected


def test_structured_field_missing_keeps_its_existing_reason():
    from app.api import vision
    target={"contract_version":"recognition_control_target_v1","label":"Quick search",
        "role":"input","source_binding_sha256":"a"*64}
    inventory={"status":"ready","screen_reading":{"source_layers":{"windows_uia":{
        "status":"ok","scan_complete":True,"truncated":False,"controls":[]}}}}
    assert vision._vista_direct_current_uia_identity(goal="Click the Quick search input box",target_text=None,
        control_target=target,point={"x":5,"y":5},fast_inventory=inventory,candidates=[]) == (
            None,"control_target_current_uia_missing")


@pytest.mark.parametrize("point",[{"x":1012,"y":120},{"x":500,"y":130}])
def test_map8_sanitized_replay_keeps_named_field_missing_without_operator_click(tmp_path,monkeypatch,point):
    from PIL import Image
    from app.api import vision
    from app.core.local_recognition_policy import local_recognition_selection
    from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
    from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
    from modules.ocr.contracts import OCRResult
    image=tmp_path/"synthetic-map8.png"
    Image.new("RGB",(2560,1400),"white").save(image)
    goal="Click the Google search input field"
    controls=[{**field("Google Maps",kind="ComboBox"),"control_id":"current-field",
        "runtime_id":[42,1],"bbox":{"x":235,"y":107,"w":658,"h":50}},
        {**field("Search by image",kind="Button",patterns=["Invoke"]),"control_id":"adjacent-button",
         "runtime_id":[42,2],"bbox":{"x":988,"y":96,"w":48,"h":48}}]
    calls=[]
    monkeypatch.setattr(vision,"_call_vista_point_prompt",lambda **kw:calls.append(kw) or
        {"point":dict(point),"provider":"recorded-model-point-only"})
    monkeypatch.setattr(vision.ocr_service,"scan_image",lambda p:OCRResult(image_path=str(p),matches=[]))
    request=vision.VisionRecognitionPlanRequestModel(image_path=str(image),task="locate_element",goal=goal,
        agent_mode="execute",provider_mode="local_grounding",top_k=5,
        write_policy={"path_graph":False,"element_memory":False,"trace":False})
    with pinned_uia_snapshot({"status":"ok","scan_complete":True,"truncated":False,"controls":controls}), pinned_runtime_output_root(tmp_path):
        response=vision._recognition_plan_from_vista_point(request=request,timer=RuntimeTimer(),
            config={"vision":{"mode":"local_grounding"}},local_config={"model_name":"isolated","endpoint":"http://unused.invalid"},
            image_path=image,input_image_size=vision.ImageSize(width=2560,height=1400),goal=goal,
            observe_reuse={},path_graph_recall={"status":"not_requested","candidates":[]})
    result=response.data["result"]
    assert len(calls)==1
    assert result["recommended_target"] is None
    assert result["candidate_result"]["recommended_candidate_id"] is None
    assert result["candidate_result"]["summary"]["vista_direct_current_uia_identity_rejection"]=="named_field_current_uia_missing"
    rejected=result["candidate_result"]["rejected"]
    assert any(item["label"]=="Google Maps" for item in rejected)
    direct=[item for item in rejected if item["candidate_id"].startswith("vista_direct_")]
    assert len(direct)==1 and direct[0]["element"]["click_point"]==point
    with pytest.raises(ValueError):
        local_recognition_selection(result,image_path=image,viewport_size={"width":2560,"height":1400})
