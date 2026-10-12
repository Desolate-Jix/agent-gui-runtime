"""普通执行只走当前图像定位；学习复用与输入门禁保持独立。"""
from copy import deepcopy

import pytest

from app.api import action
from app.api.models.request import ExecuteRecognitionPlanRequest
from app.api.models.response import APIResponse
from tests.test_browser_content_readiness import harness
from tests.test_local_recognition_policy import plan_fixture


def test_execution_default_converts_control_hint_without_mutating_request():
    target = {"name": "地址和搜索栏", "control_type": "Edit"}
    request = ExecuteRecognitionPlanRequest(goal="Microsoft Edge 顶部地址和搜索栏",
        metadata={"task_plan_target": target, "text_focus_route": "current_uia_primary"})
    original = deepcopy(request.model_dump())
    provider, metadata = action._execute_plan_request_defaults(request)
    assert provider == "local_grounding"
    assert metadata["execution_grounding"] == "direct_visual"
    assert metadata["visual_target"] == target
    assert "task_plan_target" not in metadata and "text_focus_route" not in metadata
    assert metadata["vista_direct_grounding"]["refine"] is False
    assert request.model_dump() == original


@pytest.mark.parametrize("reuse", [
    {"agent_mode": "learn"}, {"interface_memory_id": "approved-interface"},
    {"learned_instruction_id": "approved-instruction"}, {"approved_plan_id": "previewed-plan"},
])
def test_explicit_reuse_keeps_its_own_grounding_contract(reuse):
    request = ExecuteRecognitionPlanRequest(goal="Find", metadata={"execution_grounding": "direct_visual"}, **reuse)
    _, metadata = action._execute_plan_request_defaults(request)
    assert metadata.get("execution_grounding") != "direct_visual"


@pytest.mark.parametrize("goal", ["Microsoft Edge 顶部地址和搜索栏", "Click the search field in the webpage"])
def test_execution_action_captures_and_recognizes_without_document_scan(monkeypatch, harness, tmp_path, goal):
    from app.operation.screen_reading.uia_provider import _PINNED_UIA_SNAPSHOT
    calls = []
    image = str((tmp_path / "fresh.png").resolve())
    from PIL import Image
    Image.new("RGB", (1000, 690), "white").save(image)
    monkeypatch.setattr(action, "window_manager", harness.manager)
    def no_scan(*args, **kwargs):
        pytest.fail("普通执行不得准备整页控件树")
    monkeypatch.setattr(action, "prepare_browser_content", no_scan)
    def capture(**kwargs):
        calls.append("capture")
        return {"image_path": image, "window_size": {"width": 1000, "height": 690}, "roi": None}
    monkeypatch.setattr(action.screenshot_service, "capture_window", capture)
    def recognize(request):
        calls.append("vision")
        assert request.image_path == image
        assert request.metadata["execution_grounding"] == "direct_visual"
        assert _PINNED_UIA_SNAPSHOT.get() is None
        return APIResponse(success=True, message="fixture", data={"result": plan_fixture(image)})
    monkeypatch.setattr(action, "_run_recognition_plan_for_execution", recognize)
    monkeypatch.setattr(action, "_render_recognition_plan_overlay_for_execution", lambda p: None)
    monkeypatch.setattr(action, "write_trace", lambda **kw: str(tmp_path / "trace.json"))
    monkeypatch.setattr(action, "_rewrite_execute_trace_result", lambda **kw: None)
    monkeypatch.setattr(action.input_controller, "click_point", lambda *args, **kwargs:
        calls.append("click") or {"clicked": True, "window_point": {"x": 184, "y": 516}})
    request = ExecuteRecognitionPlanRequest(goal=goal, enable_post_click_verification=False,
        auto_observe_learning_artifacts=True, observe_trace_path="unused-old-trace.json",
        max_execution_attempts=1)
    with harness.scope():
        response = action.execute_recognition_plan(request)
    assert response.success, response
    assert calls == ["capture", "vision", "click"]
