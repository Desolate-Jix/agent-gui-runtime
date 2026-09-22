"""表单选项只复用固定的原生 owned popup，不按被遮挡的点击临时授权。"""
from copy import deepcopy

import pytest

from app.agent import windows_form_control_reader as reader
from app.core.local_control_target import LocalControlTarget, LocalControlTargetError
from tests.test_form_fill import control, option
from tests.test_windows_form_control_reader import setup


IDENTITY={"target_window_handle":1,"process_id":2,"process_create_time":123.5}
POPUP={"handle":90,"process_id":2,"owner_handle":1,"root_owner_handle":1,
       "class_name":"NativeChoicePopup","rect":[100,230,300,400]}


def associate(monkeypatch,popups=None,options=None):
    calls=[]
    monkeypatch.setattr(reader,"_native_owned_popups",lambda handle,pid:calls.append((handle,pid)) or
        deepcopy([POPUP] if popups is None else popups),raising=False)
    result=reader._associate_option_popups(options or [option()],handle=1,pid=2,
        window=(100,200,800,600),identity=IDENTITY)
    assert calls==[(1,2)]
    return result


def test_all_options_share_one_native_popup_scan_and_screen_origin(monkeypatch):
    items=associate(monkeypatch,options=[option(),{**option(),"runtime_id":[9]}])
    assert len(items)==2
    expected={**POPUP,"association":"native_owner_and_geometry",
        "contract_version":"form_option_native_popup_v1","bound_process_create_time":123.5,
        "coordinate_space":"screen_pixels","rect_format":"ltrb"}
    assert items[0]["native_popup"]==expected
    assert items[1]["native_popup"]==expected
    assert items[0]["runtime_id"]==option()["runtime_id"]


def test_inline_options_do_not_gain_popup_authority(monkeypatch):
    assert associate(monkeypatch,popups=[])[0].get("native_popup") is None
    assert associate(monkeypatch,popups=[{**POPUP,"rect":[400,400,500,500]}])[0].get("native_popup") is None


def test_negative_screen_origin_is_not_misread_as_window_right_bottom(monkeypatch):
    popup={**POPUP,"rect":[-100,-170,100,0]}
    monkeypatch.setattr(reader,"_native_owned_popups",lambda handle,pid:[popup])
    selected=reader._associate_option_popups([option()],handle=1,pid=2,
        window=(-100,-200,800,600),identity=IDENTITY)[0]
    before=control(kind="dropdown",label="Country",value="AU",options=[selected],
        window_identity=IDENTITY,window_rect=[-100,-200,800,600])
    result=LocalControlTarget(lambda:before,before,expected_option=selected)({"x":10,"y":35})
    assert result["native_popup_association"]["rect"]==[-100,-170,100,0]
    assert result["native_popup_association"]["coordinate_space"]=="screen_pixels"
    assert result["native_popup_association"]["rect_format"]=="ltrb"


def test_two_containing_owned_popups_are_ambiguous(monkeypatch):
    with pytest.raises(reader.FormControlReadError,match="popup_ambiguous"):
        associate(monkeypatch,popups=[POPUP,{**POPUP,"handle":91}])


@pytest.mark.parametrize("changed",[{"process_id":3},{"root_owner_handle":5},{"class_name":""},
    {"rect":[100,230,90,400]},{"handle":False}])
def test_invalid_native_popup_facts_are_not_trusted(monkeypatch,changed):
    with pytest.raises(reader.FormControlReadError,match="popup_unavailable"):
        associate(monkeypatch,popups=[{**POPUP,**changed}])


def bound_option(monkeypatch):
    selected=associate(monkeypatch)[0]
    before=control(kind="dropdown",label="Country",value="AU",options=[selected],
        window_identity=IDENTITY,window_rect=[100,200,800,600])
    return selected,before


def test_guard_returns_fixed_popup_only_for_current_option(monkeypatch):
    selected,before=bound_option(monkeypatch)
    guard=LocalControlTarget(lambda:deepcopy(before),before,expected_option=selected)
    result=guard({"x":10,"y":35})
    assert result["expected_owned_popup_handle"]==90
    assert result["native_popup_association"]["association"]=="native_owner_and_geometry"
    plain=LocalControlTarget(lambda:before,before)
    assert "expected_owned_popup_handle" not in plain({"x":10,"y":20})


@pytest.mark.parametrize("key,value",[("handle",91),("process_id",3),("owner_handle",9),
    ("root_owner_handle",9),("class_name","Other"),("rect",[100,231,300,400]),
    ("bound_process_create_time",124.0)])
def test_guard_rejects_popup_identity_or_geometry_drift(monkeypatch,key,value):
    selected,before=bound_option(monkeypatch)
    current=deepcopy(before)
    current["options"][0]["native_popup"][key]=value
    guard=LocalControlTarget(lambda:current,before,expected_option=selected)
    with pytest.raises(LocalControlTargetError,match="option_popup_changed"):
        guard({"x":10,"y":35})


@pytest.mark.parametrize("remove",[True,False])
def test_popup_presence_cannot_change_between_observation_and_dispatch(monkeypatch,remove):
    selected,before=bound_option(monkeypatch)
    current=deepcopy(before)
    if remove: current["options"][0].pop("native_popup")
    else:
        selected.pop("native_popup")
        before["options"][0].pop("native_popup",None)
    guard=LocalControlTarget(lambda:current,before,expected_option=selected)
    with pytest.raises(LocalControlTargetError,match="option_popup_changed"):
        guard({"x":10,"y":35})


@pytest.mark.parametrize("fault",[None,"changed","unavailable"])
def test_native_collection_reads_only_eligible_window_identity_once_per_scan(monkeypatch,fault):
    import sys
    from types import SimpleNamespace as NS
    enumerations=[]
    reads=[]
    windows={1:(2,1,True),90:(2,1,True),91:(3,1,True),92:(2,8,True),93:(2,1,False)}
    def enumerate_windows(callback,arg):
        enumerations.append(1)
        if fault=="unavailable": raise OSError("private provider message")
        for handle in windows:callback(handle,arg)
    def read_rect(handle):
        reads.append(handle)
        return (100,230,300,401 if fault=="changed" and len(reads)==2 else 400)
    monkeypatch.setitem(sys.modules,"win32gui",NS(EnumWindows=enumerate_windows,
        IsWindowVisible=lambda h:windows[h][2],GetAncestor=lambda h,flag:windows[h][1],
        IsWindow=lambda h:True,GetWindow=lambda h,flag:1,
        GetClassName=lambda h:"NativeChoicePopup",GetWindowRect=read_rect))
    monkeypatch.setitem(sys.modules,"win32process",NS(GetWindowThreadProcessId=lambda h:(5,windows[h][0])))
    if fault:
        with pytest.raises(reader.FormControlReadError,match="popup_changed" if fault=="changed" else "popup_unavailable") as error:
            reader._native_owned_popups(1,2)
        assert "private" not in str(error.value)
    else:
        assert reader._native_owned_popups(1,2)==[POPUP]
        assert reads==[90,90]
    assert enumerations==[1]


@pytest.mark.parametrize("expanded",[False,True])
def test_real_reader_attaches_popup_only_after_complete_expanded_option_scan(setup,monkeypatch,expanded):
    from types import SimpleNamespace as NS
    from tests.test_windows_form_control_reader import Node, TARGET
    selected=Node("NZ","ListItem",(1,4))
    selected.iface_selection_item=NS(CurrentIsSelected=0)
    combo=Node("Country","ComboBox",children=[selected])
    combo.iface_value=NS(CurrentValue="AU")
    combo.iface_expand_collapse=NS(CurrentExpandCollapseState=int(expanded))
    coordinator=setup(combo)
    calls=[]
    monkeypatch.setattr(reader,"_native_owned_popups",lambda handle,pid:calls.append((handle,pid)) or
        [{**POPUP,"process_id":20,"owner_handle":10,"root_owner_handle":10}])
    result=reader.read_form_control(coordinator,TARGET,"Country","dropdown")
    assert calls==([(10,20)] if expanded else [])
    assert (result["options"][0].get("native_popup") is not None) is expanded
    if expanded:
        assert result["options"][0]["native_popup"]["bound_process_create_time"]==123.0


@pytest.mark.parametrize("scope",["popup","inline","control","changed"])
def test_real_action_route_only_forwards_fixed_matched_option_popup(monkeypatch,tmp_path,scope):
    from types import SimpleNamespace as NS
    from app.api import action
    from app.api.models.response import APIResponse
    from app.api.action import ExecuteRecognitionPlanRequest
    from app.core.local_input_policy import _local_operator_input_scope
    from app.core.local_control_target import local_control_target_scope
    from tests.test_local_recognition_policy import plan_fixture
    identity={"contract_version":"windows_native_identity_observation_v1","provider":"windows_native_identity",
        "status":"observed","target_window_handle":321,"process_id":12,"process_create_time":123.5,
        "executable_path":"c:\\fixture\\editor.exe"}
    bound=NS(handle=321,process_id=12,title="Fixture",process_name="editor.exe",
        rect=NS(left=100,top=200,right=1100,bottom=890))
    manager=NS(get_bound_window=lambda:bound)
    monkeypatch.setattr(action,"window_manager",manager)
    monkeypatch.setattr(action.screenshot_service,"capture_window",lambda **kw:{
        "image_path":"capture.png","window_size":{"width":1000,"height":690},"roi":None})
    monkeypatch.setattr(action,"_run_recognition_plan_for_execution",lambda req:
        APIResponse(success=True,message="fixture",data={"result":deepcopy(plan_fixture())}))
    monkeypatch.setattr(action,"_render_recognition_plan_overlay_for_execution",lambda p:None)
    monkeypatch.setattr(action,"write_trace",lambda **kw:str(tmp_path/"trace.json"))
    monkeypatch.setattr(action,"_rewrite_execute_trace_result",lambda **kw:None)
    calls=[]
    monkeypatch.setattr(action.input_controller,"click_point",lambda x,y,**kw:calls.append(kw) or
        {"clicked":True,"window_point":{"x":x,"y":y}})
    box={"x":160,"y":492,"w":48,"h":48}
    popup={**POPUP,"handle":900,"process_id":12,"owner_handle":321,"root_owner_handle":321,
        "rect":[250,680,500,850],"contract_version":"form_option_native_popup_v1",
        "association":"native_owner_and_geometry","bound_process_create_time":123.5,
        "coordinate_space":"screen_pixels","rect_format":"ltrb"}
    selected={**option(),"bbox":box,**({"native_popup":popup} if scope!="inline" else {})}
    before=control(kind="dropdown",label="Choice",value="old",bbox=box,options=[selected],
        window_identity=identity,window_rect=[100,200,1000,690])
    current=deepcopy(before)
    if scope=="changed":current["options"][0]["native_popup"]["handle"]=901
    guard=LocalControlTarget(lambda:current,before,expected_option=None if scope=="control" else selected)
    request=ExecuteRecognitionPlanRequest(goal="Fixture option",enable_post_click_verification=False,
        max_execution_attempts=1,auto_observe_learning_artifacts=False,
        write_policy={"path_graph":False,"element_memory":False,"trace":True})
    with _local_operator_input_scope(manager=manager,identity_reader=NS(read_identity=lambda _:identity),
            identity=identity,window_rect=(100,200,1100,890),enabled=lambda:True):
        with local_control_target_scope(guard):
            response=action.execute_recognition_plan(request)
    if scope=="changed":
        assert not response.success and calls==[]
    else:
        assert response.success and len(calls)==1
        assert calls[0].get("expected_owned_popup_handle")== (900 if scope=="popup" else None)
