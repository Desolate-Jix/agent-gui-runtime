from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.api import action as action_api
from app.models.request import ExecuteConfirmedPointRequest, ExecuteRecognitionPlanRequest, ROIModel
from app.models.response import APIResponse, VisionResultData
from modules.ocr.contracts import OCRBoundingBox, OCRResult, OCRTextMatch


def _allowed_plan(point: dict[str, int] | None = None) -> dict:
    selected_point = point or {"x": 320, "y": 240}
    return {
        "contract_version": "recognition_plan_v1",
        "image_path": "capture.png",
        "goal": "点击此处测试",
        "candidate_result": {"candidates": []},
        "parse_result": {"vision_regions": {"image_size": {"width": 800, "height": 600}, "screen_summary": "Demo page"}},
        "recommended_target": {
            "label": "Target test",
            "text": "Target test",
            "element": {"bbox": {"x": selected_point["x"] - 30, "y": selected_point["y"] - 10, "w": 60, "h": 20}},
            "refined_bbox": None,
        },
        "narrow_search_result": {"results": []},
        "pre_click_decision": {
            "contract_version": "pre_click_decision_v1",
            "allowed": True,
            "selected_candidate_id": "candidate_1",
            "selected_click_point": selected_point,
            "reasons": ["pre_click_candidate_allowed"],
        },
        "execution_path": {"vision_model_used": True, "action_executed": False},
        "trace_path": "logs/traces/vision/recognition-plan.json",
    }


def test_execute_recognition_plan_preserves_unicode_goal_for_internal_recognition(monkeypatch) -> None:
    goal = "\u70b9\u51fb\u6b64\u5904\u6d4b\u8bd5"
    captured: dict[str, str] = {}

    monkeypatch.setattr(
        action_api.window_manager,
        "get_bound_window",
        lambda: SimpleNamespace(
            handle=1,
            title="MouseTester",
            rect=SimpleNamespace(left=0, top=0, right=800, bottom=600),
            is_active=True,
        ),
    )
    monkeypatch.setattr(
        action_api.screenshot_service,
        "capture_window",
        lambda **kwargs: {
            "image_path": "capture.png",
            "roi": None,
            "roi_adjusted": False,
            "window_size": {"width": 800, "height": 600},
        },
    )

    def fake_recognition_plan(request):
        captured["goal"] = request.goal
        plan = _allowed_plan()
        plan["goal"] = request.goal
        plan["trace_path"] = "logs/traces/vision/unicode-goal-recognition-plan.json"
        return APIResponse(
            success=True,
            message="ok",
            data=VisionResultData(result=plan).model_dump(),
            error=None,
        )

    monkeypatch.setattr(action_api, "_run_recognition_plan_for_execution", fake_recognition_plan)
    monkeypatch.setattr(action_api, "_render_recognition_plan_overlay_for_execution", lambda trace_path: None)
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/unicode-goal-execute.json")

    response = action_api.execute_recognition_plan(
        ExecuteRecognitionPlanRequest(goal=goal, app_name="mousetesterweb", dry_run=True)
    )

    assert captured["goal"] == goal
    assert response.success is True
    result = response.data["result"]
    assert result["goal"] == goal
    assert result["recognition_plan"]["goal"] == goal
    assert result["recognition_plan_trace_path"].endswith("unicode-goal-recognition-plan.json")


def test_execute_recognition_plan_clicks_allowed_live_capture(monkeypatch) -> None:
    monkeypatch.setattr(
        action_api.window_manager,
        "get_bound_window",
        lambda: SimpleNamespace(
            handle=1,
            title="MouseTester",
            rect=SimpleNamespace(left=0, top=0, right=800, bottom=600),
            is_active=True,
        ),
    )
    monkeypatch.setattr(
        action_api.screenshot_service,
        "capture_window",
        lambda **kwargs: {
            "image_path": "capture.png",
            "roi": None,
            "roi_adjusted": False,
            "window_size": {"width": 800, "height": 600},
        },
    )
    monkeypatch.setattr(
        action_api,
        "_run_recognition_plan_for_execution",
        lambda request: APIResponse(
            success=True,
            message="ok",
            data=VisionResultData(result=_allowed_plan()).model_dump(),
            error=None,
        ),
    )
    monkeypatch.setattr(action_api, "_render_recognition_plan_overlay_for_execution", lambda trace_path: {"overlay_path": "overlay.png"})
    monkeypatch.setattr(action_api.verifier, "capture_pre_action_state", lambda action_name=None: {"image_path": "before.png"})
    monkeypatch.setattr(action_api.verifier, "verify_action", lambda *args, **kwargs: {"verified": True})
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/execute-recognition-plan.json")

    clicked: dict[str, int] = {}

    def fake_click(x: int, y: int, **kwargs):
        clicked["x"] = x
        clicked["y"] = y
        return {"clicked": True, "window_point": {"x": x, "y": y}}

    monkeypatch.setattr(action_api.input_controller, "click_point", fake_click)

    response = action_api.execute_recognition_plan(
        ExecuteRecognitionPlanRequest(goal="点击此处测试", app_name="demo")
    )

    assert response.success is True
    assert clicked == {"x": 320, "y": 240}
    result = response.data["result"]
    assert result["execution_path"]["action_executed"] is True
    assert result["post_click_verification"]["verified"] is True
    assert result["recognition_plan_overlay"]["overlay_path"] == "overlay.png"
    assert result["trace_path"].endswith("execute-recognition-plan.json")


def test_execute_recognition_plan_reuses_approved_dry_run_plan(monkeypatch, tmp_path) -> None:
    bound = SimpleNamespace(
        handle=1,
        title="MouseTester",
        process_id=1234,
        process_name="msedge.exe",
        rect=SimpleNamespace(left=0, top=0, right=800, bottom=600),
        is_active=True,
    )
    monkeypatch.setattr(action_api, "APPROVED_PLANS_DIR", tmp_path / "approved-plans")
    action_api.APPROVED_PLANS_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(action_api.window_manager, "get_bound_window", lambda: bound)
    monkeypatch.setattr(
        action_api.screenshot_service,
        "capture_window",
        lambda **kwargs: {
            "image_path": "capture.png",
            "roi": None,
            "roi_adjusted": False,
            "window_size": {"width": 800, "height": 600},
        },
    )
    recognition_calls = {"count": 0}

    def fake_recognition_plan(request):
        recognition_calls["count"] += 1
        return APIResponse(
            success=True,
            message="ok",
            data=VisionResultData(result=_allowed_plan({"x": 320, "y": 240})).model_dump(),
            error=None,
        )

    monkeypatch.setattr(action_api, "_run_recognition_plan_for_execution", fake_recognition_plan)
    monkeypatch.setattr(action_api, "_render_recognition_plan_overlay_for_execution", lambda trace_path: None)
    monkeypatch.setattr(action_api.verifier, "capture_pre_action_state", lambda action_name=None: {"image_path": "before.png"})
    monkeypatch.setattr(action_api.verifier, "verify_action", lambda *args, **kwargs: {"verified": True})
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/execute-recognition-plan.json")
    clicked: dict[str, int] = {}
    monkeypatch.setattr(
        action_api.input_controller,
        "click_point",
        lambda x, y, **kwargs: clicked.update({"x": x, "y": y}) or {"clicked": True, "window_point": {"x": x, "y": y}},
    )

    dry = action_api.execute_recognition_plan(ExecuteRecognitionPlanRequest(goal="Target test", app_name="demo", dry_run=True))
    approved_plan_id = dry.data["result"]["approved_plan_id"]

    real = action_api.execute_recognition_plan(
        ExecuteRecognitionPlanRequest(goal="Target test", app_name="demo", approved_plan_id=approved_plan_id, dry_run=False)
    )

    assert dry.success is True
    assert real.success is True
    assert recognition_calls["count"] == 1
    assert clicked == {"x": 320, "y": 240}
    result = real.data["result"]
    assert result["execution_path"]["approved_plan_reused"] is True
    assert result["execution_path"]["vision_model_used"] is False
    assert result["approved_plan_reuse_validation"]["valid"] is True
    assert "recognition_plan" not in [step["name"] for step in result["timings"]["steps"]]


def test_execute_recognition_plan_rejects_approved_plan_window_mismatch(monkeypatch, tmp_path) -> None:
    original_bound = SimpleNamespace(
        handle=1,
        title="MouseTester",
        process_id=1234,
        process_name="msedge.exe",
        rect=SimpleNamespace(left=0, top=0, right=800, bottom=600),
        is_active=True,
    )
    current_bound = SimpleNamespace(
        handle=2,
        title="Other Window",
        process_id=5678,
        process_name="msedge.exe",
        rect=SimpleNamespace(left=0, top=0, right=800, bottom=600),
        is_active=True,
    )
    monkeypatch.setattr(action_api, "APPROVED_PLANS_DIR", tmp_path / "approved-plans")
    action_api.APPROVED_PLANS_DIR.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(action_api.window_manager, "get_bound_window", lambda: original_bound)
    monkeypatch.setattr(action_api.screenshot_service, "capture_window", lambda **kwargs: {"image_path": "capture.png"})
    monkeypatch.setattr(
        action_api,
        "_run_recognition_plan_for_execution",
        lambda request: APIResponse(
            success=True,
            message="ok",
            data=VisionResultData(result=_allowed_plan()).model_dump(),
            error=None,
        ),
    )
    monkeypatch.setattr(action_api, "_render_recognition_plan_overlay_for_execution", lambda trace_path: None)
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/execute-recognition-plan.json")

    dry = action_api.execute_recognition_plan(ExecuteRecognitionPlanRequest(goal="Target test", app_name="demo", dry_run=True))
    approved_plan_id = dry.data["result"]["approved_plan_id"]
    monkeypatch.setattr(action_api.window_manager, "get_bound_window", lambda: current_bound)

    real = action_api.execute_recognition_plan(
        ExecuteRecognitionPlanRequest(goal="Target test", app_name="demo", approved_plan_id=approved_plan_id, dry_run=False)
    )

    assert real.success is False
    assert real.error is not None
    assert real.error.code == "approved_plan_reuse_failed"
    assert real.error.details == "approved_plan_window_handle_mismatch"


def test_execute_recognition_plan_records_and_reuses_instruction_learning(monkeypatch, tmp_path) -> None:
    bound = SimpleNamespace(
        handle=1,
        title="MouseTester",
        process_id=1234,
        process_name="msedge.exe",
        rect=SimpleNamespace(left=0, top=0, right=800, bottom=600),
        is_active=True,
    )
    monkeypatch.setattr(action_api, "LEARNED_INSTRUCTIONS_DIR", tmp_path / "learned-instructions")
    action_api.LEARNED_INSTRUCTIONS_DIR.mkdir(parents=True, exist_ok=True)
    capture_path = tmp_path / "capture.png"
    before_path = tmp_path / "before.png"
    after_path = tmp_path / "after.png"
    diff_path = tmp_path / "diff.png"
    if action_api.Image is not None:
        for path in [capture_path, before_path, after_path, diff_path]:
            action_api.Image.new("RGB", (800, 600), color="white").save(path)
    else:
        for path in [capture_path, before_path, after_path, diff_path]:
            path.write_bytes(b"placeholder")
    monkeypatch.setattr(action_api.window_manager, "get_bound_window", lambda: bound)
    monkeypatch.setattr(
        action_api.screenshot_service,
        "capture_window",
        lambda **kwargs: {
            "image_path": str(capture_path),
            "roi": None,
            "roi_adjusted": False,
            "window_size": {"width": 800, "height": 600},
        },
    )
    recognition_calls = {"count": 0}

    def fake_recognition_plan(request):
        recognition_calls["count"] += 1
        return APIResponse(
            success=True,
            message="ok",
            data=VisionResultData(result=_allowed_plan({"x": 320, "y": 240})).model_dump(),
            error=None,
        )

    monkeypatch.setattr(action_api, "_run_recognition_plan_for_execution", fake_recognition_plan)
    monkeypatch.setattr(action_api, "_render_recognition_plan_overlay_for_execution", lambda trace_path: None)
    monkeypatch.setattr(action_api.verifier, "capture_pre_action_state", lambda action_name=None: {"image_path": str(before_path)})
    monkeypatch.setattr(
        action_api.verifier,
        "verify_action",
        lambda *args, **kwargs: {
            "verified": True,
            "before": {"image_path": str(before_path)},
            "after": {"image_path": str(after_path)},
            "diff": {"diff_image_path": str(diff_path)},
        },
    )
    monkeypatch.setattr(
        action_api,
        "_verify_mouse_tester_post_click_semantics",
        lambda **kwargs: {"applicable": True, "verified": True, "profile": "mousetester_target_text_change_v1"},
    )
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/execute-recognition-plan.json")
    clicked: list[dict[str, int]] = []
    monkeypatch.setattr(
        action_api.input_controller,
        "click_point",
        lambda x, y, **kwargs: clicked.append({"x": x, "y": y}) or {"clicked": True, "window_point": {"x": x, "y": y}},
    )

    learned = action_api.execute_recognition_plan(
        ExecuteRecognitionPlanRequest(goal="点击此处测试", app_name="mousetesterweb", learning_mode="instruction")
    )
    learned_instruction_id = learned.data["result"]["learned_instruction_id"]

    replay = action_api.execute_recognition_plan(
        ExecuteRecognitionPlanRequest(
            goal="点击此处测试",
            app_name="mousetesterweb",
            learning_mode="instruction",
            learned_instruction_id=learned_instruction_id,
        )
    )

    assert learned.success is True
    assert replay.success is True
    assert recognition_calls["count"] == 1
    assert clicked == [{"x": 320, "y": 240}, {"x": 320, "y": 240}]
    learned_bundle_dir = tmp_path / "learned-instructions" / learned_instruction_id
    learned_record_path = learned_bundle_dir / "learned_instruction.json"
    assert learned_record_path.exists()
    assert (learned_bundle_dir / "source_window.png").exists()
    assert (learned_bundle_dir / "pre_action.png").exists()
    assert (learned_bundle_dir / "post_action.png").exists()
    assert (learned_bundle_dir / "post_action_diff.png").exists()
    if action_api.Image is not None:
        assert (learned_bundle_dir / "target_crop.png").exists()
    record = action_api.json.loads(learned_record_path.read_text(encoding="utf-8"))
    assert record["learning_artifacts"]["bundle_dir"] == str(learned_bundle_dir.resolve())
    assert Path(record["learning_artifacts"]["source_image_path"]).exists()
    result = replay.data["result"]
    assert result["learned_instruction_id"] == learned_instruction_id
    assert result["learned_instruction_artifacts"]["bundle_dir"] == str(learned_bundle_dir.resolve())
    assert result["execution_path"]["instruction_learning_reused"] is True
    assert result["execution_path"]["vision_model_used"] is False
    assert result["learned_instruction_reuse_validation"]["valid"] is True
    assert "recognition_plan" not in [step["name"] for step in result["timings"]["steps"]]
    assert "save_learned_instruction" not in [step["name"] for step in result["timings"]["steps"]]


def test_execute_recognition_plan_uses_mouse_tester_semantic_verification(monkeypatch) -> None:
    monkeypatch.setattr(
        action_api.window_manager,
        "get_bound_window",
        lambda: SimpleNamespace(
            handle=1,
            title="MouseTester",
            rect=SimpleNamespace(left=0, top=0, right=800, bottom=600),
            is_active=True,
        ),
    )
    monkeypatch.setattr(action_api.screenshot_service, "capture_window", lambda **kwargs: {"image_path": "capture.png"})
    monkeypatch.setattr(
        action_api,
        "_run_recognition_plan_for_execution",
        lambda request: APIResponse(
            success=True,
            message="ok",
            data=VisionResultData(result=_allowed_plan({"x": 320, "y": 240})).model_dump(),
            error=None,
        ),
    )
    monkeypatch.setattr(action_api, "_render_recognition_plan_overlay_for_execution", lambda trace_path: None)
    monkeypatch.setattr(action_api.verifier, "capture_pre_action_state", lambda action_name=None: {"image_path": "before.png"})
    monkeypatch.setattr(
        action_api.verifier,
        "verify_action",
        lambda *args, **kwargs: {
            "verified": True,
            "before": {"image_path": "before.png"},
            "after": {"image_path": "after.png"},
            "diff": {"regions": [{"x": 300, "y": 230, "w": 40, "h": 20}]},
        },
    )
    monkeypatch.setattr(action_api.input_controller, "click_point", lambda x, y, **kwargs: {"clicked": True, "window_point": {"x": x, "y": y}})
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/execute-recognition-plan.json")

    def fake_scan(path: str) -> OCRResult:
        text = "Target test" if path == "before.png" else "Timeout single click"
        return OCRResult(
            image_path=path,
            matches=[OCRTextMatch(text=text, score=0.99, bbox=OCRBoundingBox(x=300, y=230, width=70, height=18))],
        )

    monkeypatch.setattr(action_api.ocr_service, "scan_image", fake_scan)

    response = action_api.execute_recognition_plan(
        ExecuteRecognitionPlanRequest(goal="Target test", app_name="mousetesterweb")
    )

    assert response.success is True
    result = response.data["result"]
    assert result["execution_path"]["semantic_post_click_verification_used"] is True
    assert result["semantic_post_click_verification"]["verified"] is True
    assert "target_text_replaced" in result["semantic_post_click_verification"]["reasons"]


def test_execute_recognition_plan_retries_verification_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        action_api.window_manager,
        "get_bound_window",
        lambda: SimpleNamespace(
            handle=1,
            title="Demo",
            rect=SimpleNamespace(left=0, top=0, right=800, bottom=600),
            is_active=True,
        ),
    )
    monkeypatch.setattr(action_api.screenshot_service, "capture_window", lambda **kwargs: {"image_path": "capture.png"})
    monkeypatch.setattr(
        action_api,
        "_run_recognition_plan_for_execution",
        lambda request: APIResponse(
            success=True,
            message="ok",
            data=VisionResultData(result=_allowed_plan({"x": 320, "y": 240})).model_dump(),
            error=None,
        ),
    )
    monkeypatch.setattr(action_api, "_render_recognition_plan_overlay_for_execution", lambda trace_path: None)
    monkeypatch.setattr(action_api.verifier, "capture_pre_action_state", lambda action_name=None: {"image_path": "before.png"})
    verification_results = iter([{"verified": False}, {"verified": True}])
    monkeypatch.setattr(action_api.verifier, "verify_action", lambda *args, **kwargs: next(verification_results))
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/execute-recognition-plan.json")

    clicked_points: list[tuple[int, int]] = []

    def fake_click(x: int, y: int, **kwargs):
        clicked_points.append((x, y))
        return {"clicked": True, "window_point": {"x": x, "y": y}}

    monkeypatch.setattr(action_api.input_controller, "click_point", fake_click)

    response = action_api.execute_recognition_plan(
        ExecuteRecognitionPlanRequest(goal="Target test", app_name="demo", max_execution_attempts=2)
    )

    assert response.success is True
    assert clicked_points == [(320, 240), (320, 240)]
    result = response.data["result"]
    assert result["execution_path"]["execution_attempt_count"] == 2
    assert result["execution_path"]["retry_count"] == 1
    assert result["attempts"][0]["retry_allowed"] is True
    assert result["attempts"][0]["retry_reason"] == "verification_failed_retry_safe"
    assert result["attempts"][1]["verified"] is True


def test_execute_recognition_plan_rejects_unrelated_mouse_tester_diff(monkeypatch) -> None:
    monkeypatch.setattr(
        action_api.window_manager,
        "get_bound_window",
        lambda: SimpleNamespace(
            handle=1,
            title="MouseTester",
            rect=SimpleNamespace(left=0, top=0, right=800, bottom=600),
            is_active=True,
        ),
    )
    monkeypatch.setattr(action_api.screenshot_service, "capture_window", lambda **kwargs: {"image_path": "capture.png"})
    monkeypatch.setattr(
        action_api,
        "_run_recognition_plan_for_execution",
        lambda request: APIResponse(
            success=True,
            message="ok",
            data=VisionResultData(result=_allowed_plan({"x": 320, "y": 240})).model_dump(),
            error=None,
        ),
    )
    monkeypatch.setattr(action_api, "_render_recognition_plan_overlay_for_execution", lambda trace_path: None)
    monkeypatch.setattr(action_api.verifier, "capture_pre_action_state", lambda action_name=None: {"image_path": "before.png"})
    monkeypatch.setattr(
        action_api.verifier,
        "verify_action",
        lambda *args, **kwargs: {
            "verified": True,
            "before": {"image_path": "before.png"},
            "after": {"image_path": "after.png"},
            "diff": {"regions": [{"x": 20, "y": 20, "w": 40, "h": 20}]},
        },
    )
    monkeypatch.setattr(action_api.input_controller, "click_point", lambda x, y, **kwargs: {"clicked": True, "window_point": {"x": x, "y": y}})
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/execute-recognition-plan.json")
    monkeypatch.setattr(
        action_api.ocr_service,
        "scan_image",
        lambda path: OCRResult(
            image_path=path,
            matches=[OCRTextMatch(text="Target test", score=0.99, bbox=OCRBoundingBox(x=300, y=230, width=70, height=18))],
        ),
    )

    response = action_api.execute_recognition_plan(
        ExecuteRecognitionPlanRequest(goal="Target test", app_name="mousetesterweb")
    )

    assert response.success is False
    assert response.error is not None
    assert response.error.code == "semantic_post_click_verification_failed"
    assert response.data["execution_path"]["action_executed"] is True
    assert response.data["semantic_post_click_verification"]["diff_overlaps_target"] is False


def test_execute_recognition_plan_does_not_click_when_pre_click_rejects(monkeypatch) -> None:
    monkeypatch.setattr(
        action_api.window_manager,
        "get_bound_window",
        lambda: SimpleNamespace(
            handle=1,
            title="MouseTester",
            rect=SimpleNamespace(left=0, top=0, right=800, bottom=600),
            is_active=True,
        ),
    )
    monkeypatch.setattr(action_api.screenshot_service, "capture_window", lambda **kwargs: {"image_path": "capture.png"})
    rejected = _allowed_plan()
    rejected["pre_click_decision"] = {
        "contract_version": "pre_click_decision_v1",
        "allowed": False,
        "selected_click_point": None,
        "reasons": ["no_candidate_passed_pre_click_checks"],
    }
    monkeypatch.setattr(
        action_api,
        "_run_recognition_plan_for_execution",
        lambda request: APIResponse(
            success=True,
            message="ok",
            data=VisionResultData(result=rejected).model_dump(),
            error=None,
        ),
    )
    monkeypatch.setattr(action_api, "_render_recognition_plan_overlay_for_execution", lambda trace_path: None)
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/pre-click-rejected.json")

    clicked = False

    def fake_click(*args, **kwargs):
        nonlocal clicked
        clicked = True
        return {"clicked": True}

    monkeypatch.setattr(action_api.input_controller, "click_point", fake_click)

    response = action_api.execute_recognition_plan(ExecuteRecognitionPlanRequest(goal="点击此处测试"))

    assert response.success is False
    assert response.error is not None
    assert response.error.code == "pre_click_rejected"
    assert clicked is False
    assert response.data["execution_path"]["action_executed"] is False


def test_execute_recognition_plan_blocks_saved_image_execution_without_override(monkeypatch) -> None:
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/saved-image-blocked.json")

    response = action_api.execute_recognition_plan(
        ExecuteRecognitionPlanRequest(
            goal="点击此处测试",
            image_path="old-capture.png",
            capture_live=False,
        )
    )

    assert response.success is False
    assert response.error is not None
    assert response.error.code == "saved_image_execution_not_allowed"
    assert response.data["trace_path"].endswith("saved-image-blocked.json")


def test_execute_confirmed_point_dry_run_validates_bbox_without_clicking(monkeypatch) -> None:
    monkeypatch.setattr(
        action_api.window_manager,
        "get_bound_window",
        lambda: SimpleNamespace(
            handle=5,
            title="QQ",
            rect=SimpleNamespace(left=100, top=200, right=920, bottom=1503),
        ),
    )
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/confirmed-dry-run.json")
    clicked = False

    def fake_click(*args, **kwargs):
        nonlocal clicked
        clicked = True
        return {"clicked": True}

    monkeypatch.setattr(action_api.input_controller, "click_point", fake_click)

    response = action_api.execute_confirmed_point(
        ExecuteConfirmedPointRequest(
            x=800,
            y=26,
            bbox=ROIModel(x=792, y=13, width=16, height=26),
            label="close window button",
            dry_run=True,
        )
    )

    assert response.success is True
    assert clicked is False
    assert response.data["result"]["confirmed_point"] == {"x": 800, "y": 26}
    assert response.data["result"]["execution_path"]["action_executed"] is False


def test_execute_confirmed_point_dispatches_real_window_relative_click(monkeypatch) -> None:
    monkeypatch.setattr(
        action_api.window_manager,
        "get_bound_window",
        lambda: SimpleNamespace(
            handle=5,
            title="QQ",
            rect=SimpleNamespace(left=100, top=200, right=920, bottom=1503),
        ),
    )
    monkeypatch.setattr(action_api, "write_trace", lambda **kwargs: "logs/traces/actions/confirmed-real-click.json")
    clicked: dict[str, int] = {}

    def fake_click(x: int, y: int, **kwargs):
        clicked.update({"x": x, "y": y})
        return {"clicked": True, "window_point": {"x": x, "y": y}}

    monkeypatch.setattr(action_api.input_controller, "click_point", fake_click)

    response = action_api.execute_confirmed_point(
        ExecuteConfirmedPointRequest(
            x=800,
            y=26,
            bbox=ROIModel(x=792, y=13, width=16, height=26),
            label="close window button",
            dry_run=False,
        )
    )

    assert response.success is True
    assert clicked == {"x": 800, "y": 26}
    assert response.data["result"]["execution_path"]["coordinate_source"] == "human_confirmed_candidate_center"
    assert response.data["result"]["execution_path"]["action_executed"] is True
