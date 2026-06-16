from __future__ import annotations

from types import SimpleNamespace

from app.api import action as action_api
from app.models.request import ExecuteRecognitionPlanRequest
from app.models.response import APIResponse, VisionResultData


def _bound_window(
    *,
    title: str = "Example Domain - Microsoft Edge",
    process_name: str | None = "msedge.exe",
    handle: int = 100,
    rect: tuple[int, int, int, int] = (0, 0, 1200, 800),
) -> SimpleNamespace:
    left, top, right, bottom = rect
    return SimpleNamespace(
        handle=handle,
        title=title,
        process_id=1234,
        process_name=process_name,
        rect=SimpleNamespace(left=left, top=top, right=right, bottom=bottom),
        is_active=True,
    )


def _allowed_plan(*, goal: str = "Click Learn more link", point: dict[str, int] | None = None) -> dict:
    selected_point = point or {"x": 315, "y": 246}
    return {
        "contract_version": "recognition_plan_v1",
        "agent_mode": "execute",
        "learn_depth": None,
        "mode_contract_version": "execute_plan_v1",
        "image_path": "capture.png",
        "goal": goal,
        "candidate_result": {
            "summary": {"returned_count": 1, "has_recommendation": True},
            "candidates": [
                {
                    "candidate_id": "learn_more_link",
                    "rank": 1,
                    "score": 0.95,
                    "label": "Learn more",
                    "element": {"bbox": {"x": 270, "y": 232, "w": 100, "h": 28}},
                }
            ],
        },
        "parse_result": {"vision_regions": {"image_size": {"width": 1200, "height": 800}, "screen_summary": "Example page"}},
        "recommended_target": {
            "candidate_id": "learn_more_link",
            "label": "Learn more",
            "text": "Learn more",
            "element": {"bbox": {"x": 270, "y": 232, "w": 100, "h": 28}},
        },
        "narrow_search_result": {
            "results": [
                {
                    "candidate_id": "learn_more_link",
                    "refined_click_point": selected_point,
                    "matched_text": "Learn more",
                    "coordinate_source": "vista_point_v1",
                }
            ]
        },
        "pre_click_decision": {
            "contract_version": "pre_click_decision_v1",
            "allowed": True,
            "selected_candidate_id": "learn_more_link",
            "selected_click_point": selected_point,
            "reasons": ["pre_click_candidate_allowed"],
        },
        "execution_path": {"vision_model_used": True, "action_executed": False, "vista_direct_point_grounding_used": True},
        "trace_path": "logs/traces/vision/execute-mode-recognition-plan-edge.json",
    }


def _blocked_plan(*, goal: str = "Click Learn more link") -> dict:
    plan = _allowed_plan(goal=goal)
    plan["pre_click_decision"] = {
        "contract_version": "pre_click_decision_v1",
        "allowed": False,
        "selected_candidate_id": None,
        "selected_click_point": None,
        "reasons": ["no_candidate_passed_pre_click_checks"],
        "candidate_decisions": [],
        "summary": {"candidate_count": 0, "allowed_candidate_count": 0},
    }
    plan["candidate_result"] = {"summary": {"returned_count": 0}, "candidates": []}
    plan["recommended_target"] = None
    return plan


def _capture() -> dict:
    return {
        "image_path": "capture.png",
        "roi": None,
        "roi_adjusted": False,
        "window_size": {"width": 1200, "height": 800},
    }


def test_execute_mode_dry_run_builds_agent_ready_preview(monkeypatch, tmp_path) -> None:
    captured_request: dict[str, object] = {}
    written_traces: list[dict[str, object]] = []
    monkeypatch.setattr(action_api, "APPROVED_PLANS_DIR", tmp_path / "approved-plans")
    action_api.APPROVED_PLANS_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(action_api.window_manager, "get_bound_window", lambda: _bound_window())
    monkeypatch.setattr(action_api.screenshot_service, "capture_window", lambda **kwargs: _capture())

    def fake_recognition_plan(request):
        captured_request["goal"] = request.goal
        captured_request["provider_mode"] = request.provider_mode
        captured_request["metadata"] = request.metadata
        captured_request["observe_trace_path"] = request.observe_trace_path
        return APIResponse(success=True, message="ok", data=VisionResultData(result=_allowed_plan(goal=request.goal)).model_dump(), error=None)

    monkeypatch.setattr(action_api, "_run_recognition_plan_for_execution", fake_recognition_plan)
    monkeypatch.setattr(
        action_api,
        "_render_recognition_plan_overlay_for_execution",
        lambda trace_path: {
            "trace_path": trace_path,
            "image_path": "capture.png",
            "output_path": "overlay.png",
            "candidate_count": 1,
            "decision_count": 1,
            "selected_candidate_id": "learn_more_link",
        },
    )
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: written_traces.append(kwargs) or f"logs/traces/actions/{kwargs['operation']}.json")

    response = action_api.execute_recognition_plan(
        ExecuteRecognitionPlanRequest(
            goal="Click Learn more link",
            app_name="edge",
            state_hint="Example Domain page",
            observe_trace_path="observe-trace.json",
            dry_run=True,
        )
    )

    assert response.success is True
    result = response.data["result"]
    assert captured_request["goal"] == "Click Learn more link"
    assert captured_request["provider_mode"] == "local_grounding"
    assert captured_request["metadata"]["vista_direct_grounding"] == {
        "enabled": True,
        "timeout_seconds": 45.0,
        "max_edge": 640,
        "refine": True,
        "refine_roi_size": 512,
        "refine_max_edge": 640,
    }
    assert captured_request["observe_trace_path"] == "observe-trace.json"
    assert result["recognition_plan_overlay"]["output_path"] == "overlay.png"
    assert result["approved_plan_id"]
    guidance = result["agent_execution_guidance"]
    assert guidance["status"] == "dry_run_ready"
    assert guidance["next_action"] == "execute_approved_plan"
    assert guidance["next_request"]["body"]["approved_plan_id"] == result["approved_plan_id"]
    step_result = result["agent_step_result"]
    assert step_result["contract_version"] == "agent_step_result_v1"
    assert step_result["status"] == "dry_run_ready"
    assert step_result["action_executed"] is False
    assert step_result["next_agent_action"] == "execute_approved_plan"
    assert step_result["selected_click_point"] == {"x": 315, "y": 246}
    assert step_result["evidence"]["coordinate_overlay_path"] == "overlay.png"
    assert step_result["evidence"]["action_trace_path"].endswith("execute_mode_plan_preview.json")
    assert written_traces[-1]["operation"] == "execute_mode_plan_preview"


def test_execute_mode_reuses_approved_plan_for_next_call(monkeypatch, tmp_path) -> None:
    recognition_calls = {"count": 0}
    clicked: dict[str, int] = {}
    written_operations: list[str] = []
    monkeypatch.setattr(action_api, "APPROVED_PLANS_DIR", tmp_path / "approved-plans")
    action_api.APPROVED_PLANS_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(action_api.window_manager, "get_bound_window", lambda: _bound_window())
    monkeypatch.setattr(action_api.screenshot_service, "capture_window", lambda **kwargs: _capture())

    def fake_recognition_plan(request):
        recognition_calls["count"] += 1
        return APIResponse(success=True, message="ok", data=VisionResultData(result=_allowed_plan(goal=request.goal)).model_dump(), error=None)

    monkeypatch.setattr(action_api, "_run_recognition_plan_for_execution", fake_recognition_plan)
    monkeypatch.setattr(action_api, "_render_recognition_plan_overlay_for_execution", lambda trace_path: {"output_path": "overlay.png"})
    monkeypatch.setattr(action_api.verifier, "capture_pre_action_state", lambda action_name=None: {"image_path": "before.png"})
    monkeypatch.setattr(
        action_api.verifier,
        "verify_action",
        lambda *args, **kwargs: {
            "verified": True,
            "before": {"image_path": "before.png"},
            "after": {"image_path": "after.png"},
            "diff": {"diff_image_path": "diff.png"},
            "verification_basis": {"pixel_change_ratio": 0.2},
        },
    )
    monkeypatch.setattr(action_api.input_controller, "click_point", lambda x, y, **kwargs: clicked.update({"x": x, "y": y}) or {"clicked": True})
    monkeypatch.setattr(action_api.transition_memory, "save", lambda record: str(tmp_path / "transition.json"))
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: written_operations.append(kwargs["operation"]) or f"logs/traces/actions/{kwargs['operation']}.json")

    dry = action_api.execute_recognition_plan(ExecuteRecognitionPlanRequest(goal="Click Learn more link", app_name="edge", dry_run=True))
    approved_plan_id = dry.data["result"]["approved_plan_id"]
    real = action_api.execute_recognition_plan(
        ExecuteRecognitionPlanRequest(goal="Click Learn more link", app_name="edge", approved_plan_id=approved_plan_id, dry_run=False)
    )

    assert dry.success is True
    assert real.success is True
    assert recognition_calls["count"] == 1
    assert clicked == {"x": 315, "y": 246}
    assert real.data["result"]["execution_path"]["approved_plan_reused"] is True
    assert real.data["result"]["agent_execution_guidance"]["next_action"] == "done"
    step_result = real.data["result"]["agent_step_result"]
    assert step_result["status"] == "executed_verified"
    assert step_result["action_executed"] is True
    assert step_result["next_agent_action"] == "done"
    assert step_result["post_click"]["verified"] is True
    assert step_result["post_click"]["before_image_path"] == "before.png"
    assert step_result["post_click"]["after_image_path"] == "after.png"
    assert step_result["post_click"]["diff_image_path"] == "diff.png"
    assert step_result["evidence"]["coordinate_overlay_path"] == "overlay.png"
    assert step_result["evidence"]["action_trace_path"].endswith("execute_mode_click.json")
    assert written_operations == ["execute_mode_plan_preview", "execute_mode_click"]


def test_approved_plan_reuse_uses_capture_size_when_saved_bound_rect_is_placeholder(monkeypatch, tmp_path) -> None:
    recognition_calls = {"count": 0}
    clicked: dict[str, int] = {}
    window_reads = {"count": 0}
    monkeypatch.setattr(action_api, "APPROVED_PLANS_DIR", tmp_path / "approved-plans")
    action_api.APPROVED_PLANS_DIR.mkdir(parents=True, exist_ok=True)

    def bound_window_sequence():
        window_reads["count"] += 1
        if window_reads["count"] == 1:
            return _bound_window(rect=(-32000, -32000, -31840, -31972))
        return _bound_window()

    monkeypatch.setattr(action_api.window_manager, "get_bound_window", bound_window_sequence)
    monkeypatch.setattr(action_api.screenshot_service, "capture_window", lambda **kwargs: _capture())

    def fake_recognition_plan(request):
        recognition_calls["count"] += 1
        return APIResponse(success=True, message="ok", data=VisionResultData(result=_allowed_plan(goal=request.goal)).model_dump(), error=None)

    monkeypatch.setattr(action_api, "_run_recognition_plan_for_execution", fake_recognition_plan)
    monkeypatch.setattr(action_api, "_render_recognition_plan_overlay_for_execution", lambda trace_path: {"output_path": "overlay.png"})
    monkeypatch.setattr(action_api.verifier, "capture_pre_action_state", lambda action_name=None: {"image_path": "before.png"})
    monkeypatch.setattr(
        action_api.verifier,
        "verify_action",
        lambda *args, **kwargs: {"verified": True, "before": {"image_path": "before.png"}, "after": {"image_path": "after.png"}},
    )
    monkeypatch.setattr(action_api.input_controller, "click_point", lambda x, y, **kwargs: clicked.update({"x": x, "y": y}) or {"clicked": True})
    monkeypatch.setattr(action_api.transition_memory, "save", lambda record: str(tmp_path / "transition.json"))
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: f"logs/traces/actions/{kwargs['operation']}.json")

    dry = action_api.execute_recognition_plan(ExecuteRecognitionPlanRequest(goal="Click Learn more link", app_name="edge", dry_run=True))
    approved_plan_id = dry.data["result"]["approved_plan_id"]
    approved_record = action_api._load_approved_plan(approved_plan_id)
    real = action_api.execute_recognition_plan(
        ExecuteRecognitionPlanRequest(goal="Click Learn more link", app_name="edge", approved_plan_id=approved_plan_id, dry_run=False)
    )

    assert dry.success is True
    assert approved_record["bound_window"]["rect"] == {"left": -32000, "top": -32000, "width": 160, "height": 28}
    assert approved_record["coordinate_window_size"] == {"width": 1200, "height": 800}
    assert real.success is True
    assert recognition_calls["count"] == 1
    assert clicked == {"x": 315, "y": 246}
    assert real.data["result"]["approved_plan_reuse_validation"]["approved_coordinate_window_size"] == {"width": 1200, "height": 800}


def test_execute_mode_rejects_mismatched_bound_window_before_capture(monkeypatch) -> None:
    capture_called = {"value": False}
    written_traces: list[dict[str, object]] = []
    monkeypatch.setattr(action_api.window_manager, "get_bound_window", lambda: _bound_window(title="QQ", process_name="QQ.exe"))

    def fail_capture(**kwargs):
        capture_called["value"] = True
        raise AssertionError("mismatched execute-mode request must stop before screenshot")

    monkeypatch.setattr(action_api.screenshot_service, "capture_window", fail_capture)
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: written_traces.append(kwargs) or "logs/traces/actions/bound-window-mismatch.json")

    response = action_api.execute_recognition_plan(ExecuteRecognitionPlanRequest(goal="Click Learn more link", app_name="edge", dry_run=True))

    assert response.success is False
    assert response.error is not None
    assert response.error.code == "bound_window_mismatch"
    assert capture_called["value"] is False
    assert response.data["bound_window_validation"]["actual_process_name"] == "QQ.exe"
    assert written_traces[-1]["operation"] == "execute_mode_plan_preview"


def test_execute_mode_blocked_plan_returns_fallback_and_overlay(monkeypatch) -> None:
    monkeypatch.setattr(action_api.window_manager, "get_bound_window", lambda: _bound_window())
    monkeypatch.setattr(action_api.screenshot_service, "capture_window", lambda **kwargs: _capture())
    monkeypatch.setattr(
        action_api,
        "_run_recognition_plan_for_execution",
        lambda request: APIResponse(success=True, message="ok", data=VisionResultData(result=_blocked_plan(goal=request.goal)).model_dump(), error=None),
    )
    monkeypatch.setattr(action_api, "_render_recognition_plan_overlay_for_execution", lambda trace_path: {"output_path": "blocked-overlay.png", "candidate_count": 0})
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/execute-mode-plan-preview.json")

    response = action_api.execute_recognition_plan(ExecuteRecognitionPlanRequest(goal="Click Learn more link", app_name="edge", dry_run=True))

    assert response.success is False
    assert response.error is not None
    assert response.error.code == "pre_click_rejected"
    assert response.data["recognition_plan_overlay"]["output_path"] == "blocked-overlay.png"
    assert response.data["fallback_plan"]["contract_version"] == "execute_fallback_plan_v1"
    fallback_steps = response.data["fallback_plan"]["steps"]
    scroll_step = next(step for step in fallback_steps if step["name"] == "request_scroll")
    assert scroll_step["endpoint"] == "POST /action/scroll"
    assert scroll_step["suggested_request"] == {
        "direction": "down",
        "wheel_clicks": 4,
        "dry_run": False,
        "enable_verification": True,
    }
    assert scroll_step["next_after_success"]["endpoint"] == "POST /action/execute_recognition_plan"
    assert response.data["agent_execution_guidance"]["next_action"] == "recover_with_fallback_plan"
    assert response.data["agent_step_result"]["status"] == "blocked"
    assert response.data["agent_step_result"]["failure_reason"] == "pre_click_rejected"
    assert response.data["agent_step_result"]["next_agent_action"] == "recover_with_fallback_plan"


def test_execute_mode_trace_write_policy_can_disable_action_trace(monkeypatch) -> None:
    monkeypatch.setattr(action_api.window_manager, "get_bound_window", lambda: _bound_window())
    monkeypatch.setattr(action_api.screenshot_service, "capture_window", lambda **kwargs: _capture())
    monkeypatch.setattr(
        action_api,
        "_run_recognition_plan_for_execution",
        lambda request: APIResponse(success=True, message="ok", data=VisionResultData(result=_allowed_plan(goal=request.goal)).model_dump(), error=None),
    )
    monkeypatch.setattr(action_api, "_render_recognition_plan_overlay_for_execution", lambda trace_path: {"output_path": "overlay.png"})

    def fail_write_trace(**kwargs):
        raise AssertionError("write_trace must not run when write_policy.trace is false")

    monkeypatch.setattr(action_api, "write_trace", fail_write_trace)

    response = action_api.execute_recognition_plan(
        ExecuteRecognitionPlanRequest(
            goal="Click Learn more link",
            app_name="edge",
            dry_run=True,
            write_policy={"path_graph": False, "element_memory": True, "trace": False},
        )
    )

    assert response.success is True
    assert response.data["result"]["trace_path"] is None


def test_execute_mode_blocks_real_saved_image_without_override(monkeypatch) -> None:
    monkeypatch.setattr(action_api.window_manager, "get_bound_window", lambda: None)
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/saved-image-blocked.json")

    response = action_api.execute_recognition_plan(
        ExecuteRecognitionPlanRequest(
            goal="Click Learn more link",
            app_name="edge",
            image_path="capture.png",
            capture_live=False,
            dry_run=False,
        )
    )

    assert response.success is False
    assert response.error is not None
    assert response.error.code == "saved_image_execution_not_allowed"
    assert response.data["trace_path"].endswith("saved-image-blocked.json")
