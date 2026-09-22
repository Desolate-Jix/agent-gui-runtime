"""选择控件的裁图包含说明，但目标框与模型点门控保持不变。"""
from copy import deepcopy
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from app.api import vision
from app.core.runtime_artifacts import RuntimeTimer, pinned_runtime_output_root
from app.vision.schemas import BBox, ImageSize


CASES = [
    ("checkbox", "Show Source", {"x":72,"y":518,"w":14,"h":13},
     {"x":95,"y":516,"w":82,"h":18}, {"x":50,"y":558}),
    ("checkbox", "Show Source", {"x":72,"y":518,"w":14,"h":13},
     {"x":95,"y":516,"w":82,"h":18}, {"x":41,"y":512}),
    ("combobox", "Character Encoding", {"x":237,"y":416,"w":285,"h":19},
     {"x":75,"y":415,"w":139,"h":20}, {"x":284,"y":397}),
]


def candidate(role, label, bbox):
    return SimpleNamespace(candidate_id="current-control", label=label, role=role, score=.9,
        refined_bbox=None, element=SimpleNamespace(bbox=BBox(**bbox)))


@pytest.mark.parametrize("role,width,height", [("checkbox",14,13),("radio",14,14),
    ("combobox",285,19),("checkbox",40,40),("combobox",512,1),
    ("listitem",213,24),("listitem",512,24)])
def test_small_selection_is_upscaled_once_with_exact_inverse_transform(tmp_path,role,width,height):
    image=tmp_path/"synthetic-scale.png"
    Image.new("RGB",(1200,900),"white").save(image)
    box={"x":300,"y":300,"w":width,"h":height}
    target=candidate(role,"Choice",box)
    with pinned_runtime_output_root(tmp_path):
        result=vision._prepare_vista_candidate_roi_image(image,ImageSize(width=1200,height=900),
            candidates=[target],padding=12,min_size=96,max_edge=448,roi_source="current_uia_candidate_v1")
    roi=result["crop_bounds_original"]
    scale=min(3.0,max(1.0,40.0/min(width,height)))
    expected={"width":round(roi["w"]*scale),"height":round(roi["h"]*scale)}
    assert result["processed_size"]==expected
    assert expected["width"]<=2304 and expected["height"]<=768
    with Image.open(result["processed_image_path"]) as crop:
        assert crop.size==(expected["width"],expected["height"])
    assert result["pathgraph_candidates"][0]["bbox_original"]==box
    assert target.element.bbox.to_dict()==box
    forward=result["transform"]["scale_original_to_processed"]
    reverse=result["transform"]["scale_processed_to_original"]
    assert forward["x"]*reverse["x"]==pytest.approx(1.0)
    assert forward["y"]*reverse["y"]==pytest.approx(1.0)
    processed_box=vision._candidate_bbox_for_prompt(target,coordinate_transform=result["transform"])
    assert processed_box["x"]==round((box["x"]-roi["x"])*forward["x"])
    for original in ({"x":box["x"]+width//2,"y":box["y"]+height//2},
                     {"x":box["x"]-25,"y":box["y"]-6}):
        parsed={"point":{"x":(original["x"]-roi["x"])*1000/roi["w"],
                         "y":(original["y"]-roi["y"])*1000/roi["h"],"coordinate_space":"normalized_0_1000"}}
        point=vision._vista_point_to_original_pixel(parsed,image_size=ImageSize(**expected))
        mapped=vision._map_vista_processed_point_to_original(point,coordinate_transform=result["transform"],
            original_image_size=ImageSize(width=1200,height=900))
        assert mapped==original


@pytest.mark.parametrize("role,label,bbox,label_bbox,bad_point", CASES)
@pytest.mark.parametrize("with_label", [True, False])
def test_preprocessing_retains_label_context_and_inverse_mapping(tmp_path, role, label, bbox, label_bbox, bad_point, with_label):
    image = tmp_path / "synthetic.png"
    original = Image.new("RGB", (900,700), "white")
    draw = ImageDraw.Draw(original)
    draw.rectangle((label_bbox["x"],label_bbox["y"],label_bbox["x"]+label_bbox["w"]-1,label_bbox["y"]+label_bbox["h"]-1), fill="red")
    original.save(image)
    target = candidate(role,label,bbox)
    before = deepcopy(bbox)
    snapshot = dict(scan_complete=True,truncated=False,controls=[dict(
        name=label,control_type="Text",bbox=label_bbox,visible=True)] if with_label else [])
    with pinned_runtime_output_root(tmp_path):
        result = vision._prepare_vista_candidate_roi_image(image,ImageSize(width=900,height=700),
            candidates=[target],padding=12,min_size=96,max_edge=448,roi_source="current_uia_candidate_v1",
            uia_snapshot=snapshot)
    roi=result["crop_bounds_original"]
    assert roi["x"] <= label_bbox["x"] and roi["x"]+roi["w"] >= label_bbox["x"]+label_bbox["w"]
    assert roi["y"] <= label_bbox["y"] and roi["y"]+roi["h"] >= label_bbox["y"]+label_bbox["h"]
    assert roi["w"] <= 768 and roi["h"] <= 256
    scale=min(3.0,max(1.0,40.0/min(bbox["w"],bbox["h"])))
    assert result["processed_size"] == {"width":round(roi["w"]*scale),"height":round(roi["h"]*scale)}
    forward=result["transform"]["scale_original_to_processed"]
    reverse=result["transform"]["scale_processed_to_original"]
    assert forward["x"]*reverse["x"]==pytest.approx(1.0)
    assert forward["y"]*reverse["y"]==pytest.approx(1.0)
    assert target.element.bbox.to_dict() == before
    assert result["pathgraph_candidates"][0]["bbox_original"] == before
    with Image.open(result["processed_image_path"]) as crop:
        label_center=(round((label_bbox["x"]+label_bbox["w"]//2-roi["x"])*forward["x"]),
                      round((label_bbox["y"]+label_bbox["h"]//2-roi["y"])*forward["y"]))
        assert crop.getpixel(label_center) == (255,0,0)


@pytest.mark.parametrize("role,label,bbox,label_bbox,bad_point", CASES)
def test_first_recognition_crop_has_context_but_recorded_wrong_point_still_rejected(tmp_path, monkeypatch, role,label,bbox,label_bbox,bad_point):
    from app.core.local_control_target import LocalControlTarget, LocalControlTargetError
    from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
    from modules.ocr.contracts import OCRResult
    image=tmp_path/"synthetic-route.png"
    Image.new("RGB",(900,700),"white").save(image)
    kind="checkbox" if role=="checkbox" else "dropdown"
    goal=f'Click the {kind} labelled "{label}"'
    patterns=["Toggle"] if role=="checkbox" else ["Value","Text","ExpandCollapse"]
    controls=[dict(control_id="control",runtime_id=[42,1],name=label,
        control_type="CheckBox" if role=="checkbox" else "ComboBox",patterns=patterns,bbox=bbox,enabled=True,visible=True),
        dict(control_id="label",name=label,control_type="Text",patterns=[],bbox=label_bbox,enabled=True,visible=True)]
    snapshot=dict(status="ok",scan_complete=True,truncated=False,controls=controls)
    calls=[]
    monkeypatch.setattr(vision,"_call_vista_point_prompt",lambda **kw:calls.append(kw) or {
        "point":bad_point,"provider":"recorded-point-only"})
    monkeypatch.setattr(vision.ocr_service,"scan_image",lambda p:OCRResult(image_path=str(p),matches=[]))
    request=vision.VisionRecognitionPlanRequestModel(image_path=str(image),task="locate_element",goal=goal,
        agent_mode="execute",provider_mode="local_grounding",top_k=5,
        write_policy={"path_graph":False,"element_memory":False,"trace":False})
    with pinned_uia_snapshot(snapshot),pinned_runtime_output_root(tmp_path):
        response=vision._recognition_plan_from_vista_point(request=request,timer=RuntimeTimer(),
            config={"vision":{"mode":"local_grounding"}},local_config={"model_name":"isolated","endpoint":"http://unused.invalid"},
            image_path=image,input_image_size=ImageSize(width=900,height=700),goal=goal,
            observe_reuse={},path_graph_recall={"status":"not_requested","candidates":[]})
    assert len(calls)==1 and calls[0]["vista_stage"]=="pathgraph_candidate_roi_refine"
    roi=calls[0]["image_preprocess"]["crop_bounds_original"]
    assert roi["x"] <= label_bbox["x"] and roi["x"]+roi["w"] >= label_bbox["x"]+label_bbox["w"]
    result=response.data["result"]
    chosen=result["recommended_target"]
    # 候选的 UIA 中心不是派发点；实际模型点在窄搜索结果中。
    local=result["narrow_search_result"]["results"][0]
    assert local["refined_click_point"] == bad_point
    assert chosen["element"]["bbox"] == bbox
    from app.core.local_recognition_policy import local_recognition_selection
    with pytest.raises(ValueError,match="outside candidate"):
        local_recognition_selection(result,image_path=image,viewport_size={"width":900,"height":700})
    state=dict(source="windows_uia",runtime_id=[42,1],window_identity={"handle":1},window_rect=[0,0,900,700],kind=kind,
        label=label,bbox=bbox,state_available=True,checked=False,value="utf-8",expanded=False)
    guard=LocalControlTarget(lambda:state,state)
    with pytest.raises(LocalControlTargetError,match="point"):
        guard(bad_point)


@pytest.mark.parametrize("role,source,expanded", [("radio","current_uia_candidate_v1",True),
    ("listitem","current_uia_candidate_v1",True),("listitem","top1_only",False),
    ("button","current_uia_candidate_v1",False),("input","current_uia_candidate_v1",False),
    ("link","current_uia_candidate_v1",False),("checkbox","top1_only",False)])
def test_context_policy_is_limited_to_current_selection_controls(tmp_path,role,source,expanded):
    image=tmp_path/"negative-controls.png"
    Image.new("RGB",(900,700),"white").save(image)
    with pinned_runtime_output_root(tmp_path):
        result=vision._prepare_vista_candidate_roi_image(image,ImageSize(width=900,height=700),
            candidates=[candidate(role,"Choice",{"x":500,"y":300,"w":14,"h":14})],
            padding=12,min_size=96,max_edge=448,roi_source=source)
    assert (result.get("context_reason")=="selection_control_label_context") is expanded
    if not expanded:
        assert result["crop_bounds_original"]=={"x":459,"y":259,"w":96,"h":96}


@pytest.mark.parametrize("x,y",[(0,0),(386,0),(0,186),(386,186)])
def test_context_stays_inside_small_viewport_and_preserves_coordinate_mapping(tmp_path,x,y):
    image=tmp_path/"viewport-edge.png"
    Image.new("RGB",(400,200),"white").save(image)
    box={"x":x,"y":y,"w":14,"h":14}
    with pinned_runtime_output_root(tmp_path):
        result=vision._prepare_vista_candidate_roi_image(image,ImageSize(width=400,height=200),
            candidates=[candidate("radio","Choice",box)],padding=12,min_size=96,max_edge=448,
            roi_source="current_uia_candidate_v1")
    roi=result["crop_bounds_original"]
    assert 0<=roi["x"]<=x and x+14<=roi["x"]+roi["w"]<=400
    assert 0<=roi["y"]<=y and y+14<=roi["y"]+roi["h"]<=200
    transform=result["transform"]
    forward=transform["scale_original_to_processed"]
    reverse=transform["scale_processed_to_original"]
    assert forward["x"]*reverse["x"]==pytest.approx(1.0)
    assert forward["y"]*reverse["y"]==pytest.approx(1.0)
    assert transform["origin_original"]=={"x":roi["x"],"y":roi["y"]}
    assert result["pathgraph_candidates"][0]["bbox_original"]==box


@pytest.mark.parametrize("fault",["different_name","far_label","huge_label","hidden","incomplete","invalid_box"])
def test_context_does_not_expand_to_unrelated_or_unusable_text(tmp_path,fault):
    image=tmp_path/"unrelated-label.png"
    Image.new("RGB",(900,700),"white").save(image)
    text=dict(name="Choice",control_type="Text",bbox={"x":530,"y":300,"w":70,"h":20},visible=True)
    snapshot=dict(scan_complete=True,truncated=False,controls=[text])
    if fault=="different_name":
        text["name"]="Unrelated"
    elif fault=="far_label":
        text["bbox"]["y"]=600
    elif fault=="huge_label":
        text["bbox"]["w"]=800
    elif fault=="hidden":
        text["visible"]=False
    elif fault=="incomplete":
        snapshot["scan_complete"]=False
    else:
        text["bbox"]["w"]=None
    with pinned_runtime_output_root(tmp_path):
        result=vision._prepare_vista_candidate_roi_image(image,ImageSize(width=900,height=700),
            candidates=[candidate("radio","Choice",{"x":500,"y":300,"w":14,"h":14})],
            padding=12,min_size=96,max_edge=448,roi_source="current_uia_candidate_v1",uia_snapshot=snapshot)
    assert result["context_label_count"]==0
    assert result["crop_bounds_original"]["w"]<=768
    assert result["crop_bounds_original"]["h"]<=256


@pytest.mark.parametrize("width,height,count", [(513,24,1),(213,65,1),(213,24,2)])
def test_listitem_context_does_not_expand_large_or_multiple_candidates(tmp_path,width,height,count):
    image=tmp_path/"large-list.png"
    Image.new("RGB",(1200,900),"white").save(image)
    targets=[candidate("listitem",str(i),{"x":300,"y":300+i*30,"w":width,"h":height})
             for i in range(count)]
    with pinned_runtime_output_root(tmp_path):
        result=vision._prepare_vista_candidate_roi_image(image,ImageSize(width=1200,height=900),
            candidates=targets,padding=12,min_size=96,max_edge=448,roi_source="current_uia_candidate_v1")
    assert "context_reason" not in result
    assert result["processed_size"]["width"]<=448


@pytest.mark.parametrize("point_y,allowed", [(511,False),(524,True),(536,False)])
def test_live_option_geometry_gets_primary_context_without_relaxing_point_gate(tmp_path,monkeypatch,point_y,allowed):
    from app.core.local_recognition_policy import local_recognition_selection
    from app.operation.screen_reading.uia_provider import pinned_uia_snapshot
    from modules.ocr.contracts import OCRResult
    image=tmp_path/"recorded-option-geometry.png"
    Image.new("RGB",(800,1155),"white").save(image)
    bbox={"x":238,"y":512,"w":213,"h":24}
    label="iso-8859-1 (Western Europe)"
    goal=f'Click the option "{label}" in the open dropdown labelled "Character Encoding"'
    snapshot=dict(status="ok",scan_complete=True,truncated=False,controls=[dict(
        control_id="current-option",runtime_id=[42,8,4],name=label,control_type="ListItem",
        patterns=["SelectionItem"],bbox=bbox,enabled=True,visible=True)])
    calls=[]
    point={"x":271,"y":point_y}
    monkeypatch.setattr(vision,"_call_vista_point_prompt",lambda **kw:calls.append(kw) or
        {"point":point,"provider":"recorded-point-only"})
    monkeypatch.setattr(vision.ocr_service,"scan_image",lambda p:OCRResult(image_path=str(p),matches=[]))
    request=vision.VisionRecognitionPlanRequestModel(image_path=str(image),task="locate_element",goal=goal,
        agent_mode="execute",provider_mode="local_grounding",top_k=5,
        write_policy={"path_graph":False,"element_memory":False,"trace":False})
    with pinned_uia_snapshot(snapshot),pinned_runtime_output_root(tmp_path):
        response=vision._recognition_plan_from_vista_point(request=request,timer=RuntimeTimer(),
            config={"vision":{"mode":"local_grounding"}},local_config={"model_name":"isolated","endpoint":"http://unused.invalid"},
            image_path=image,input_image_size=ImageSize(width=800,height=1155),goal=goal,
            observe_reuse={},path_graph_recall={"status":"not_requested","candidates":[]})
    assert len(calls)==1
    prep=calls[0]["image_preprocess"]
    assert prep["roi_source"]=="current_uia_candidate_v1"
    assert prep["strategy"]=="current_selection_control_context_upscale"
    assert prep["small_control_upscale_factor"]==pytest.approx(5/3)
    assert prep["crop_bounds_original"]["h"]>=128
    assert prep["pathgraph_candidates"][0]["bbox_original"]==bbox
    result=response.data["result"]
    assert result["recommended_target"]["element"]["bbox"]==bbox
    assert result["narrow_search_result"]["results"][0]["refined_click_point"]==point
    if allowed:
        assert local_recognition_selection(result,image_path=image,viewport_size={"width":800,"height":1155})["selected_click_point"]==point
    else:
        with pytest.raises(ValueError,match="outside candidate"):
            local_recognition_selection(result,image_path=image,viewport_size={"width":800,"height":1155})
