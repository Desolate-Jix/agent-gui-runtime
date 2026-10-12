"""真实动作与识图路由联调；只替换模型传输、窗口设备和鼠标。"""
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest

from app.api import action, vision
from app.api.models.request import ExecuteRecognitionPlanRequest
from app.core.local_input_policy import _local_operator_input_scope
from tests.test_execution_direct_visual import direct_scene


@pytest.fixture
def visual_action_scene(direct_scene, monkeypatch):
    _, model_calls, state, _, image = direct_scene
    identity = {"contract_version": "windows_native_identity_observation_v1", "provider": "windows_native_identity",
        "status": "observed", "target_window_handle": 11, "process_id": 22,
        "process_create_time": 123.0, "executable_path": "c:/fixture/msedge.exe"}
    bound = NS(handle=11, process_id=22, title="Fixture", process_name="msedge.exe",
        rect=NS(left=100, top=200, right=900, bottom=800))
    manager = NS(get_bound_window=lambda: bound)
    clicks = []
    monkeypatch.setattr(action, "window_manager", manager)
    monkeypatch.setattr(action.screenshot_service, "capture_window", lambda **kw:
        {"image_path": str(image), "window_size": {"width": 800, "height": 600}, "roi": None})
    monkeypatch.setattr(action, "prepare_browser_content", lambda *a, **kw: pytest.fail("不应扫描网页树"))
    monkeypatch.setattr(action, "_render_recognition_plan_overlay_for_execution", lambda *a, **kw: None)
    def click(x, y, **kwargs):
        if kwargs.get("pre_input_validator"):
            kwargs["pre_input_validator"]()
        clicks.append((x, y))
        return {"clicked": True, "window_point": {"x": x, "y": y}}
    monkeypatch.setattr(action.input_controller, "click_point", click)
    def run(goal="Click the reports button", **kwargs):
        request = ExecuteRecognitionPlanRequest(goal=goal, enable_post_click_verification=False,
            max_execution_attempts=1, write_policy={"path_graph": False, "element_memory": False, "trace": False},
            **kwargs)
        with _local_operator_input_scope(manager=manager,
                identity_reader=NS(read_identity=lambda _: deepcopy(identity)), identity=identity,
                window_rect=(100, 200, 900, 800), enabled=lambda: True):
            return action.execute_recognition_plan(request)
    return run, clicks, model_calls, state, bound


def test_real_action_uses_one_visual_call_and_one_click_without_uia(visual_action_scene):
    run, clicks, calls, _, _ = visual_action_scene
    result = run(metadata={"task_plan_target": {"name": "reports", "control_type": "Button"}})
    assert result.success, result
    assert len(calls) == 1 and clicks == [(200, 300)]
    assert result.data["result"]["direct_visual_capture_check"]["source"] == "direct_visual"


@pytest.mark.parametrize("raw", ["[-1, 500]", '{"point":{"x":200,"y":300,"coordinate_space":"pixel"},"confidence":0.2}'])
def test_model_rejection_never_reaches_input_even_with_local_policy(visual_action_scene, raw):
    run, clicks, calls, state, _ = visual_action_scene
    state["raw"] = raw
    result = run()
    assert not result.success and len(calls) == 1 and clicks == []


@pytest.mark.parametrize("defect", ["window", "geometry", "file"])
def test_change_after_grounding_is_rejected_before_mouse_input(visual_action_scene, monkeypatch, defect):
    from PIL import Image
    run, clicks, calls, _, bound = visual_action_scene
    def recognize(request):
        result = vision.recognition_plan(request)
        if defect == "window":
            bound.handle = 99
        elif defect == "geometry":
            bound.rect.right += 10
        else:
            Image.new("RGB", (800, 600), "black").save(request.image_path)
        return result
    monkeypatch.setattr(action, "_run_recognition_plan_for_execution", recognize)
    result = run()
    assert not result.success and len(calls) == 1 and clicks == []
