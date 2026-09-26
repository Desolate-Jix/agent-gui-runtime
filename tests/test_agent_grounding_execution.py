"""公共动作路由接线验证；系统窗口和输入边界用替身，不点击桌面。"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.core.agent_grounding_target import AgentGroundingTarget, agent_grounding_scope
from tests.test_agent_grounding_target import scene
from tests.test_local_step_timings import timed_scene


def test_coordinator_skips_local_model_configuration_for_agent_target(timed_scene, scene):
    co, state, _, _ = timed_scene
    target_state = scene[0]
    target_state["capture"]["window_identity"].update(handle=321, process_id=12, process_create_time=123.5)
    target = AgentGroundingTarget(target_state)
    receipt = co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation="execute_recognition_plan", request={"goal":"Search"}, grounding_target=target)
    assert receipt["phase"] == "returned"
    assert "configuration_load" not in state.events
    assert "configuration_freeze" not in state.events
    assert state.events.count("route") == 1


def test_grounded_batch_focus_keeps_uia_binding_without_model(timed_scene, scene):
    from app.core.local_text_focus import LocalTextFocusTarget
    co, state, _, _ = timed_scene
    target_state = scene[0]
    target_state['capture']['window_identity'].update(handle=321, process_id=12, process_create_time=123.5)
    receipt = co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation='execute_recognition_plan', request={'goal': 'Search'},
        grounding_target=AgentGroundingTarget(target_state), focus_target=LocalTextFocusTarget(321, 12))
    assert receipt['phase'] == 'returned'
    assert 'configuration_load' not in state.events
    assert state.events.count('route') == 1


@pytest.mark.parametrize("changed", [False, True, "after_plan", "focus_error"])
def test_existing_action_route_uses_agent_plan_or_rejects_stale_target(scene, monkeypatch, changed):
    from PIL import ImageDraw
    from app.api import action
    from app.api.models.request import ExecuteRecognitionPlanRequest
    from app.desktop_review.local_action_contract import _validated_request
    from app.core.local_input_policy import _local_operator_input_scope
    state, _, im, root = scene
    current = root / "current.png"
    if changed is True:
        ImageDraw.Draw(im).rectangle((30,40,100,70), fill="red")
    im.save(current)
    identity={"contract_version":"windows_native_identity_observation_v1", "provider":"windows_native_identity",
        "status":"observed", "target_window_handle":10, "process_id":20,"process_create_time":30.0,
        "executable_path":"c:\\fixture\\editor.exe"}
    bound=SimpleNamespace(handle=10,process_id=20,title="Fixture",process_name="editor.exe",
        rect=SimpleNamespace(left=100,top=200,right=300,bottom=350))
    manager=SimpleNamespace(get_bound_window=lambda:bound)
    monkeypatch.setattr(action,"window_manager",manager)
    monkeypatch.setattr(action.screenshot_service,"capture_window",lambda **kwargs:{
        "image_path":str(current),"window_size":{"width":200,"height":150},"roi":None})
    monkeypatch.setattr(action,"prepare_browser_content",lambda *args:None)
    monkeypatch.setattr(action,"_render_recognition_plan_overlay_for_execution",lambda p:None)
    monkeypatch.setattr(action,"write_trace",lambda **kwargs:str(root/"trace.json"))
    monkeypatch.setattr(action,"_rewrite_execute_trace_result",lambda **kwargs:None)
    if changed == "after_plan":
        from app.core import local_text_focus
        def change_before_input(*args):
            ImageDraw.Draw(im).rectangle((30,40,100,70), fill="red")
            im.save(current)
        monkeypatch.setattr(local_text_focus, "check_local_text_focus", change_before_input)
    if changed == 'focus_error':
        from app.core import local_text_focus
        from app.agent.windows_text_field_reader import TextFieldReadError
        def unavailable(*args):
            raise TextFieldReadError('text_field_target_not_writable', diagnostic={
                'check': 'value_readonly', 'control_type': 'Edit', 'private_text': 'must not leak'})
        monkeypatch.setattr(local_text_focus, 'check_local_text_focus', unavailable)
    calls=[]
    monkeypatch.setattr(action.input_controller,"click_point",lambda x,y,**kwargs:
        calls.append((x,y)) or {"clicked":True,"point":{"x":x,"y":y}})
    target=AgentGroundingTarget(state)
    request=ExecuteRecognitionPlanRequest.model_validate(_validated_request("execute_recognition_plan",{
        "goal":"Search","enable_post_click_verification":False}))
    reader=SimpleNamespace(read_identity=lambda handle:deepcopy(identity))
    with agent_grounding_scope(target), _local_operator_input_scope(manager=manager,
            identity_reader=reader,identity=identity,window_rect=(100,200,300,350),enabled=lambda:True):
        receipt=action.execute_recognition_plan(request)
    if changed == 'focus_error':
        assert not receipt.success and not calls
        assert receipt.data['text_field_diagnostic'] == {'reason_code': 'text_field_target_not_writable',
            'diagnostic': {'check': 'value_readonly', 'control_type': 'Edit'}}
    elif changed:
        assert not receipt.success
        assert not calls
        assert "agent_grounding_target_region_changed" in str(receipt.error)
    else:
        assert receipt.success, receipt
        assert calls==[(65,55)]
        assert target.input_claimed is True
        assert receipt.data["result"]["recognition_plan"]["grounding_evidence"]["source"]=="agent_current"


def test_execute_command_uses_stored_candidate_and_refuses_second_dispatch(tmp_path):
    from app.instant_mcp import InstantCommand
    from tests.test_grounding_handoff import handoff, prepare, found
    from app.vision.grounding_handoff import GroundingHandoffStore, GroundingHandoffError
    from app.vision.recognition_source import RecognitionSourceConfig, ClientVisionCapabilities
    from scripts.run_local_step_session import run_grounding_execution
    from PIL import Image
    from hashlib import sha256
    frame = tmp_path / "frame.png"
    Image.new("RGB", (100, 80), "white").save(frame)
    store = GroundingHandoffStore(tmp_path, owner_id="host-1")
    store.prepare("ground-1", goal="Search", capture={"capture_id":"capture-1",
        "image_path":str(frame), "sha256":sha256(frame.read_bytes()).hexdigest(),
        "window_identity":{"handle":100,"process_id":200,"process_create_time":1.5}},
        configuration=RecognitionSourceConfig(source="agent_current"),
        capabilities=ClientVisionCapabilities(image_transport="supported",current_vision="supported"))
    store.resolve("ground-1", found())
    command = {"kind":"grounding_execute","request":{"grounding_request_id":"ground-1"}}
    assert InstantCommand.model_validate(command).command() == command
    calls = []
    def execute(**kwargs):
        calls.append(kwargs)
        assert kwargs["grounding_target"].goal == "Search"
        assert kwargs["operation"] == "execute_recognition_plan"
        assert kwargs["include_observation"] is True
        assert store.get("ground-1")["phase"] == "executing"
        return {"contract_version":"local_direct_step_v1", "phase":"returned", "response":{"success":True}}
    coordinator = SimpleNamespace(execute_local_step=execute)
    with pytest.raises(GroundingHandoffError, match="selected_target_changed"):
        run_grounding_execution(store,coordinator,{"handle":101,"process_id":200},"exec-1",command)
    assert store.get("ground-1")["phase"] == "grounding_ready"
    receipt = run_grounding_execution(store,coordinator,{"handle":100,"process_id":200},"exec-1",command)
    assert receipt["contract_version"] == "local_direct_step_v1"
    assert receipt["grounding_request_id"] == "ground-1"
    assert store.get("ground-1")["phase"] == "completed"
    with pytest.raises(GroundingHandoffError, match="execution_already_claimed"):
        run_grounding_execution(store,coordinator,{"handle":100,"process_id":200},"exec-2",command)
    assert len(calls) == 1
