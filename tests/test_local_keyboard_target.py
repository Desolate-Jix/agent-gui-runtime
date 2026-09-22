"""组合字段键盘范围的离线契约；不派发真实输入。"""
from contextvars import copy_context
from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace as NS

import pytest

from app.agent.text_field_evidence import TextFieldIdentity, TextFieldSnapshot
from tests.test_text_input_guard import prepared
from app.core import input_controller as inputs
from tests.test_local_step_timings import timed_scene


def scene(monkeypatch, operation="type_text"):
    from app.core import local_keyboard_target as module
    controller, bound, events, _ = prepared(monkeypatch)
    before = TextFieldSnapshot(TextFieldIdentity("field",7,9,123.0,(42,1),(0,0,320,200),(20,30,100,80)),
        "capture", "before", 1, "uia_value", "old" if operation == "type_text" else "next", None)
    target = module.LocalKeyboardTarget(before, "Edit", (70,80), operation,
        text_sha256=sha256(b"next").hexdigest() if operation == "type_text" else None,
        clear_existing=operation == "type_text")
    samples = []
    def read(**kwargs):
        samples.append(kwargs)
        events.append("field-read")
        return before
    monkeypatch.setattr(module, "WindowsTextFieldReader", lambda **kw: NS(read_field=read))
    monkeypatch.setattr(module, "require_local_operator_input", lambda manager: True)
    monkeypatch.setattr(inputs.window_manager, "validate_bound_point_visibility", lambda **kw:
        events.append("point-check") or {"allowed": False, "reason": "target_point_occluded"})
    monkeypatch.setattr(controller, "_focus_window", lambda hwnd: events.append("focus"))
    return module, controller, bound, events, before, target, samples


@pytest.mark.parametrize("operation", ["type_text", "press_key"])
def test_exact_focused_keyboard_target_replaces_pointer_visibility_only_in_scope(monkeypatch, operation):
    module, controller, _, events, before, target, samples = scene(monkeypatch, operation)
    with module.local_keyboard_target_scope(target):
        if operation == "type_text":
            assert controller.type_text("next", x=70,y=80,clear_existing=True)["typed"]
        else:
            assert controller.press_key("Enter",x=70,y=80)["pressed"]
    assert "focus" not in events and "point-check" not in events and "click" not in events
    assert len(samples) == (2 if operation == "type_text" else 1)
    for call in samples:
        assert call["expected_runtime_id"] == (42,1) and call["require_keyboard_focus"] is True
        assert call["target_bbox"] == before.identity.control_bbox
        assert call.get("allow_post_input_geometry_rebind", False) is False
    for index,event in enumerate(events):
        if isinstance(event,tuple): assert events[index-1] == "field-read"


@pytest.mark.parametrize("fault", ["runtime", "bbox", "value", "source", "focus_failure"])
@pytest.mark.parametrize("after_selection", [False, True])
def test_field_change_blocks_paste_without_replaying_input(monkeypatch, fault, after_selection):
    module, controller, _, events, before, target, _ = scene(monkeypatch)
    calls = []
    def read(**kwargs):
        calls.append(kwargs)
        if len(calls) == (2 if after_selection else 1):
            if fault == "focus_failure": raise ValueError("focus unavailable")
            if fault == "runtime": return replace(before,identity=replace(before.identity,runtime_id=(42,2)))
            if fault == "bbox": return replace(before,identity=replace(before.identity,control_bbox=(21,30,100,80)))
            if fault == "value": return replace(before,value="changed")
            return replace(before,source="uia_text")
        return before
    monkeypatch.setattr(module,"WindowsTextFieldReader",lambda **kw:NS(read_field=read))
    with module.local_keyboard_target_scope(target), pytest.raises(ValueError):
        controller.type_text("next",x=70,y=80,clear_existing=True)
    assert (inputs.VK_CONTROL,inputs.VK_V) not in events
    assert events.count((inputs.VK_CONTROL,inputs.VK_A)) == int(after_selection)
    assert events[-1] == "clipboard-restored"


@pytest.mark.parametrize("fault", ["point", "text", "clear", "click", "submit", "key"])
def test_private_target_cannot_be_repurposed(monkeypatch, fault):
    module, controller, _, events, _, target, _ = scene(monkeypatch)
    kwargs=dict(x=70,y=80,clear_existing=True)
    text="next"
    if fault == "point": kwargs["x"]=71
    elif fault == "text": text="other"
    elif fault == "clear": kwargs["clear_existing"]=False
    elif fault == "click": kwargs["click_before_typing"]=True
    elif fault == "submit": kwargs["submit"]=True
    with module.local_keyboard_target_scope(target),pytest.raises(ValueError):
        if fault == "key": controller.press_key("Tab",x=70,y=80)
        else: controller.type_text(text,**kwargs)
    assert not any(isinstance(event,tuple) for event in events) and "click" not in events


def test_scope_is_single_command_and_revoked_in_copied_context(monkeypatch):
    module, controller, _, events, _, target, _ = scene(monkeypatch,"press_key")
    with module.local_keyboard_target_scope(target):
        copied=copy_context()
        controller.press_key("Enter",x=70,y=80)
        with pytest.raises(ValueError): controller.press_key("Enter",x=70,y=80)
    with pytest.raises(ValueError): copied.run(controller.press_key,"Enter",x=70,y=80)
    assert events.count((inputs.VK_RETURN,)) == 1


@pytest.mark.parametrize("operation", ["type_text", "press_key"])
def test_bare_keyboard_path_keeps_point_occlusion_rejection(monkeypatch,operation):
    _,controller,_,events,_,_,_=scene(monkeypatch,operation)
    with pytest.raises(inputs.TargetPointOccludedError):
        if operation == "type_text": controller.type_text("next",x=70,y=80)
        else: controller.press_key("Enter",x=70,y=80)
    assert "point-check" in events and not any(isinstance(event,tuple) for event in events)


def test_copied_active_scope_cannot_dispatch_on_another_thread(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    module,controller,_,events,_,target,_=scene(monkeypatch,"press_key")
    with module.local_keyboard_target_scope(target):
        context=copy_context()
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending=pool.submit(context.run,controller.press_key,"Enter",x=70,y=80)
            with pytest.raises(ValueError,match="scope unavailable"): pending.result()
        controller.press_key("Enter",x=70,y=80)
    assert events.count((inputs.VK_RETURN,)) == 1


@pytest.mark.parametrize("fault", ["window", "foreground", "policy"])
def test_target_revalidation_cannot_dispatch_after_native_state_changes(monkeypatch,fault):
    module,controller,bound,events,before,target,_=scene(monkeypatch,"press_key")
    def read(**kwargs):
        if fault == "window": bound.rect.left += 1
        elif fault == "foreground": monkeypatch.setattr(inputs.win32gui,"GetForegroundWindow",lambda:999)
        else: monkeypatch.setattr(module,"require_local_operator_input",lambda manager:False)
        return before
    monkeypatch.setattr(module,"WindowsTextFieldReader",lambda **kw:NS(read_field=read))
    with module.local_keyboard_target_scope(target),pytest.raises((ValueError,RuntimeError)):
        controller.press_key("Enter",x=70,y=80)
    assert not any(isinstance(event,tuple) for event in events)


@pytest.mark.parametrize("operation", ["type_text", "press_key"])
def test_local_step_transports_private_target_to_existing_owner_route(monkeypatch,timed_scene,operation):
    from app.desktop_review import local_direct_step as direct
    module,controller,bound,events,before,_,_=scene(monkeypatch,operation)
    coordinator,_,_,_=timed_scene
    bound.handle,bound.process_id=321,12
    bound.rect=NS(left=0,top=0,right=800,bottom=600)
    before=replace(before,identity=replace(before.identity,window_handle=321,process_id=12,window_rect=(0,0,800,600)))
    target=module.LocalKeyboardTarget(before,"Edit",(70,80),operation,
        text_sha256=sha256(b"next").hexdigest() if operation=="type_text" else None,
        clear_existing=operation=="type_text")
    monkeypatch.setattr(inputs.win32gui,"GetForegroundWindow",lambda:321)
    monkeypatch.setattr(module,"WindowsTextFieldReader",lambda **kw:NS(read_field=lambda **args:before))
    original_owner=coordinator._owner.call
    owner_active=[]
    def owner(callback):
        assert not owner_active, "字段复读不可嵌套 owner.call"
        owner_active.append(True)
        try:return original_owner(callback)
        finally:owner_active.pop()
    coordinator._owner.call=owner
    def route(op,request,manager):
        assert owner_active
        assert "keyboard_target" not in request
        result=(controller.type_text(request["text"],x=70,y=80,clear_existing=True)
            if op=="type_text" else controller.press_key(request["key"],x=70,y=80))
        return {"success":True,"data":result}
    monkeypatch.setattr(direct,"_post_action",route)
    request={"x":70,"y":80,**({"text":"next","clear_existing":True,"click_before_typing":False}
        if operation=="type_text" else {"key":"Enter"})}
    result=coordinator.execute_local_step(target_window_handle=321,target_process_id=12,
        operation=operation,request=request,keyboard_target=target)
    assert result["response"]["success"] is True
    assert module._SCOPE.get() is None and "point-check" not in events
    assert "keyboard_target" not in result["request"]


def test_public_json_cannot_install_internal_keyboard_target():
    from app.desktop_review.local_action_contract import _validated_request
    with pytest.raises(ValueError):
        _validated_request("type_text",{"text":"next","x":70,"y":80,"keyboard_target":{}})


@pytest.mark.parametrize("changed_selection", [False, True])
def test_append_mode_preserves_original_selection_without_select_all(monkeypatch,changed_selection):
    module,controller,_,events,before,_,samples=scene(monkeypatch)
    before=replace(before,selection=(3,3))
    target=module.LocalKeyboardTarget(before,"Edit",(70,80),"type_text",text_sha256=sha256(b"next").hexdigest())
    monkeypatch.setattr(module,"WindowsTextFieldReader",lambda **kw:NS(read_field=lambda **args:
        replace(before,selection=(0,0)) if changed_selection else before))
    with module.local_keyboard_target_scope(target):
        if changed_selection:
            with pytest.raises(ValueError):controller.type_text("next",x=70,y=80)
        else:assert controller.type_text("next",x=70,y=80)["typed"]
    assert (inputs.VK_CONTROL,inputs.VK_A) not in events
    assert events.count((inputs.VK_CONTROL,inputs.VK_V)) == int(not changed_selection)
