"""选择控件不得被改写成可编辑字段，约束必须穿过真实服务端提示词边界。"""
from types import SimpleNamespace

import pytest

from app.api import vision
from app.vision.model_workers.vista_openai_server import _vista_prompt
from app.vision.schemas import BBox


def test_generic_input_prompt_does_not_invent_a_label_from_the_instruction():
    goal = "Click the search input field at the top left of the webpage"
    candidate = SimpleNamespace(candidate_id="current-field", label="", role="input",
        refined_bbox=None, element=SimpleNamespace(bbox=BBox(x=116, y=103, w=246, h=24)))
    effective = _vista_prompt(vision._vista_point_prompt(goal, [candidate]))
    assert "editable text input field" in effective
    assert f"Original instruction: {goal}" in effective
    assert f"labeled {goal!r}" not in effective


@pytest.mark.parametrize("role,goal", [
    ("combobox", 'Click the dropdown labelled "Character Encoding"'),
    ("combobox", 'Click the combobox labelled "Character Encoding"'),
    ("combobox", "Character Encoding"),
    ("checkbox", 'Click the checkbox labelled "Show Source"'),
    ("radio", 'Click the radio button labelled "Errors only"'),
    ("input", 'Click the dropdown labelled "Character Encoding"'),
])
def test_selection_goal_is_not_rewritten_as_editable_area(role, goal):
    candidate = SimpleNamespace(candidate_id="current-control", label="Character Encoding", role=role,
        refined_bbox=None, element=SimpleNamespace(bbox=BBox(x=237,y=416,w=285,h=19)))
    outer = vision._vista_point_prompt(goal, [candidate])
    effective = _vista_prompt(outer)
    assert f"Goal: {goal}\n" in outer
    assert goal in effective
    assert "editable" not in effective
    assert "Target constraints:" not in outer


@pytest.mark.parametrize("role", ["input", "combobox"])
def test_explicit_input_goal_keeps_editable_constraint_and_exact_label(role):
    candidate = SimpleNamespace(candidate_id="current-control", label="Auckland Museum", role=role,
        refined_bbox=None, element=SimpleNamespace(bbox=BBox(x=235,y=107,w=658,h=50)))
    goal = 'Click the search input box labelled "Auckland Museum" at the top of the webpage'
    effective = _vista_prompt(vision._vista_point_prompt(goal, [candidate]))
    assert "editable area of an input field" in effective
    assert goal in effective
    assert "not the printed label" in effective


@pytest.mark.parametrize("role",["input","combobox"])
@pytest.mark.parametrize("label",["Google Maps Auckland","Customer's email","邮件地址"])
def test_explicit_field_prompt_labels_only_the_literal_not_the_whole_instruction(role,label):
    candidate=SimpleNamespace(candidate_id="current-control",label=label,role=role,
        refined_bbox=None,element=SimpleNamespace(bbox=BBox(x=235,y=107,w=658,h=50)))
    goal=f'Click the search input box labelled "{label}" at the top of the webpage'
    outer=vision._vista_point_prompt(goal,[candidate])
    effective=_vista_prompt(outer)
    assert f"Goal: the editable text input field labeled {label!r}." in outer
    assert f"labeled {goal!r}" not in effective
    assert f"the editable text input field labeled {label!r}." in effective
    assert goal in effective
    assert "not the printed label" in effective


def test_map9_primary_prompt_is_corrected_without_accepting_recorded_outside_point(tmp_path,monkeypatch):
    from PIL import Image
    from app.core.local_recognition_policy import local_recognition_selection
    from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
    from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
    from modules.ocr.contracts import OCRResult
    image=tmp_path/"synthetic-map9.png"
    Image.new("RGB",(2560,1400),"white").save(image)
    label="Google Maps Auckland"
    goal=f'Click the search input box labelled "{label}" at the top of the webpage'
    box={"x":235,"y":107,"w":658,"h":50}
    point={"x":298,"y":99}
    snapshot={"status":"ok","scan_complete":True,"truncated":False,"controls":[{
        "control_id":"current-field","runtime_id":[42,1],"name":label,"control_type":"ComboBox",
        "patterns":["Value","Text","ExpandCollapse"],"visible":True,"enabled":True,"bbox":box}]}
    calls=[]
    monkeypatch.setattr(vision,"_call_vista_point_prompt",lambda **kw:calls.append(kw) or
        {"point":dict(point),"provider":"recorded-point-only"})
    monkeypatch.setattr(vision.ocr_service,"scan_image",lambda p:OCRResult(image_path=str(p),matches=[]))
    request=vision.VisionRecognitionPlanRequestModel(image_path=str(image),task="locate_element",goal=goal,
        agent_mode="execute",provider_mode="local_grounding",top_k=5,
        write_policy={"path_graph":False,"element_memory":False,"trace":False})
    with pinned_uia_snapshot(snapshot), pinned_runtime_output_root(tmp_path):
        response=vision._recognition_plan_from_vista_point(request=request,timer=RuntimeTimer(),
            config={"vision":{"mode":"local_grounding"}},local_config={"model_name":"isolated","endpoint":"http://unused.invalid"},
            image_path=image,input_image_size=vision.ImageSize(width=2560,height=1400),goal=goal,
            observe_reuse={},path_graph_recall={"status":"not_requested","candidates":[]})
    assert len(calls)==1 and calls[0]["vista_stage"]=="pathgraph_candidate_roi_refine"
    effective=_vista_prompt(calls[0]["prompt"])
    assert f"editable text input field labeled {label!r}." in effective
    assert f"labeled {goal!r}" not in effective
    result=response.data["result"]
    assert result["candidate_result"]["summary"]["current_uia_literal_identity"]["match_count"]==1
    assert result["recommended_target"]["element"]["bbox"]==box
    local=[item for item in result["narrow_search_result"]["results"]
        if item["candidate_id"]==result["recommended_target"]["candidate_id"]]
    assert len(local)==1 and local[0]["refined_click_point"]==point
    with pytest.raises(ValueError):
        local_recognition_selection(result,image_path=image,viewport_size={"width":2560,"height":1400})
