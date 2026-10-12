"""普通直接视觉审核使用定位原帧；动态页面不触发整图重复像素否决。"""
import base64
from hashlib import sha256
from time import perf_counter_ns

from PIL import Image, ImageDraw
import pytest

from app.api import action
from app.api.models.request import ExecuteRecognitionPlanRequest
from app.api.models.response import APIResponse
from app.execution.action_review import action_review_scope, CANDIDATE_CONDITION
from app.judgment import DecisionProfile, DecisionService
from tests.test_action_review_contract import Provider
from tests.test_browser_content_readiness import harness
from tests.test_local_recognition_policy import plan_fixture


@pytest.fixture
def direct_review(tmp_path, monkeypatch, harness):
    original = tmp_path / "original.png"
    changed = tmp_path / "animated.png"
    Image.new("RGB", (1000, 690), "white").save(original)
    image = Image.open(original).copy()
    ImageDraw.Draw(image).rectangle((900, 100, 950, 150), fill="red")
    image.save(changed)
    source_hash = sha256(original.read_bytes()).hexdigest()
    calls, clicks = [], []
    provider = Provider()
    service = DecisionService(tmp_path, provider=provider, profile=DecisionProfile(
        contract_version="decision_profile.v2", mode="auto",
        auto_conditions=[CANDIDATE_CONDITION], request_cap=3))
    monkeypatch.setattr(action, "window_manager", harness.manager)
    monkeypatch.setattr(action, "prepare_browser_content",
        lambda *args, **kwargs: pytest.fail("普通执行不能准备控件树"))
    def capture(**kwargs):
        calls.append(kwargs["purpose"])
        path = original if len(calls) == 1 else changed
        return {"image_path": str(path), "capture_id": path.stem,
            "window_size": {"width": 1000, "height": 690}, "roi": None}
    monkeypatch.setattr(action.screenshot_service, "capture_window", capture)
    monkeypatch.setattr(action, "_run_recognition_plan_for_execution", lambda request:
        APIResponse(success=True, message="fixture", data={"result": plan_fixture(request.image_path)}))
    monkeypatch.setattr(action, "_render_recognition_plan_overlay_for_execution", lambda plan: None)
    monkeypatch.setattr(action, "write_trace", lambda **kwargs: str(tmp_path / "trace.json"))
    monkeypatch.setattr(action, "_rewrite_execute_trace_result", lambda **kwargs: None)
    def click(x, y, **kwargs):
        if kwargs.get("pre_input_validator"):
            kwargs["pre_input_validator"]()
        clicks.append((x, y))
        return {"clicked": True, "window_point": {"x": x, "y": y}}
    monkeypatch.setattr(action.input_controller, "click_point", click)
    context = {"schema": "action_review_context.v1", "run_id": "direct-one",
        "attempt_id": "attempt-one", "step_id": "click", "budget_ms": 5000,
        "plan": {"schema_version": "task_plan.v2", "title": "Current click",
            "inputs": {}, "steps": [{"step_id": "click",
                "action": {"kind": "click", "goal": "Click Search"},
                "verification": {"kind": "agent_judgment"}}]}}
    def run(*, mutate=None):
        provider.during = mutate
        with harness.scope(), action_review_scope(service, context=context,
                deadline_ns=perf_counter_ns() + 5_000_000_000):
            return action.execute_recognition_plan(ExecuteRecognitionPlanRequest(
                goal="Click Search", enable_post_click_verification=False,
                max_execution_attempts=1, auto_observe_learning_artifacts=False))
    yield run, calls, clicks, provider, original, source_hash, harness
    service.close()


def test_direct_visual_uses_one_original_frame_for_grounding_and_review(direct_review):
    run, calls, clicks, provider, original, source_hash, _ = direct_review
    result = run()
    assert result.success, result
    assert calls == ["recognition_plan_execution"]
    assert clicks == [(184, 516)] and len(provider.calls) == 1
    frame = provider.calls[0]["frames"][0]
    assert sha256(base64.b64decode(frame["data_url"].split(",", 1)[1])).hexdigest() == source_hash
    assert frame["candidate_annotation"]["metadata"]["source_sha256"] == source_hash
    assert result.data["result"]["direct_visual_capture_check"]["status"] == "matched"


@pytest.mark.parametrize("change", ["source", "geometry", "process"])
def test_same_frame_review_still_rejects_source_or_window_drift(direct_review, change):
    run, _, clicks, provider, original, _, harness = direct_review
    def mutate():
        if change == "source":
            Image.new("RGB", (1000, 690), "black").save(original)
        elif change == "geometry":
            harness.bound.rect.right += 1
        else:
            harness.identity["process_create_time"] += 1
    result = run(mutate=mutate)
    assert not result.success and clicks == []
    assert len(provider.calls) == 1


def test_final_capture_validation_crossing_deadline_cannot_dispatch(direct_review, monkeypatch):
    from app.execution import action_review_dispatch, task_plan_target
    run, _, clicks, provider, _, _, _ = direct_review
    validate = task_plan_target.validate_task_plan_dispatch_capture
    real_clock = action_review_dispatch.perf_counter_ns
    expired, calls = [False], []
    monkeypatch.setattr(action_review_dispatch, "perf_counter_ns",
        lambda: 10**30 if expired[0] else real_clock())
    def slow_final_hash(*args, **kwargs):
        value = validate(*args, **kwargs)
        calls.append(1)
        if len(calls) == 3:
            expired[0] = True
        return value
    monkeypatch.setattr(task_plan_target, "validate_task_plan_dispatch_capture", slow_final_hash)
    result = run()
    assert expired[0] and len(provider.calls) == 1
    assert not result.success and clicks == []
