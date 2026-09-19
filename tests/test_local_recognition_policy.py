"""测试策略只在现有本地会话生效，原拒绝证据不能被改成通过。"""
from copy import deepcopy
import pytest
from app.core.local_recognition_policy import local_recognition_selection


def plan_fixture(path="capture.png"):
    candidate = {"candidate_id": "current", "element_id": "element", "element": {
        "element_id": "element", "bbox": {"x": 160, "y": 492, "w": 48, "h": 48}}}
    return {"image_path": path, "parse_result": {"vision_regions": {"image_size": {"width": 1000, "height": 690}}},
        "candidate_result": {"recommended_candidate_id": "current", "candidates": [candidate]},
        "narrow_search_result": {"results": [{"candidate_id": "current", "element_id": "element",
            "status": "unverified", "refined_click_point": {"x": 184, "y": 516}, "matched_text": "停止"}]},
        "pre_click_decision": {"allowed": False, "reasons": ["local_ocr_text_mismatch", "narrow_search_status:unverified"]}}


def select(plan):
    return local_recognition_selection(plan, image_path="capture.png", viewport_size={"width": 1000, "height": 690})


@pytest.mark.parametrize("stale", [False, True])
def test_diagnostics_include_rejected_candidates_without_minting_points(stale):
    from app.core.local_recognition_policy import local_recognition_diagnostics
    plan = plan_fixture("old.png" if stale else "capture.png")
    ranking = plan["candidate_result"]
    candidate = ranking["candidates"][0]
    candidate.update(text="Search", score=0.9, reasons=["vista_direct_current_uia_identity_ambiguous"])
    ranking.update(candidates=[], rejected=[candidate], recommended_candidate_id=None)
    original = deepcopy(plan)
    result = local_recognition_diagnostics(plan, image_path="capture.png", viewport_size={"width": 1000, "height": 690})
    assert result["selection_status"] == "no_eligible_candidates"
    assert result["candidate_count"] == 0 and result["rejected_count"] == 1
    assert result["candidates"][0]["text"] == "Search"
    assert result["candidates"][0]["eligible"] is False
    assert result["candidates"][0]["bbox"] == (None if stale else candidate["element"]["bbox"])
    assert result["current_capture_bound"] is not stale
    assert result["executable"] is False and result["automatic_retry_allowed"] is False
    assert plan == original


def test_risk_rejection_is_observed_not_rewritten():
    plan = plan_fixture(); original = deepcopy(plan)
    result = select(plan)
    assert result["allowed"] and result["selected_click_point"] == {"x": 184, "y": 516}
    assert result["original_policy"]["allowed"] is False
    assert result["coordinate_space"] == "capture_image_pixels"
    assert plan == original


@pytest.mark.parametrize("defect", ["old_image", "size", "float", "outside", "outside_box", "missing", "duplicate", "identity"])
def test_disabled_policy_still_requires_valid_current_geometry(defect):
    p = plan_fixture(); local = p["narrow_search_result"]["results"][0]
    if defect == "old_image": p["image_path"] = "old.png"
    elif defect == "size": p["parse_result"]["vision_regions"]["image_size"]["width"] = 800
    elif defect == "float": local["refined_click_point"]["x"] = 184.0
    elif defect == "outside": local["refined_click_point"]["x"] = 1001
    elif defect == "outside_box": local["refined_click_point"]["x"] = 20
    elif defect == "missing": p["candidate_result"]["recommended_candidate_id"] = None
    elif defect == "duplicate": p["candidate_result"]["candidates"] *= 2
    else: local["element_id"] = "different"
    with pytest.raises(ValueError): select(p)


@pytest.mark.parametrize("diff_changed", [False, True])
def test_real_route_scoped_policy_dry_run_does_not_mint_strict_approval(monkeypatch, tmp_path, diff_changed):
    from types import SimpleNamespace
    from app.api import action
    from app.api.models.request import ExecuteRecognitionPlanRequest
    from app.api.models.response import APIResponse
    from app.core.local_input_policy import _local_operator_input_scope
    identity = {"contract_version": "windows_native_identity_observation_v1", "provider": "windows_native_identity",
        "status": "observed", "target_window_handle": 321, "process_id": 12,
        "process_create_time": 123.5, "executable_path": "c:\\fixture\\editor.exe"}
    bound = SimpleNamespace(handle=321, process_id=12, title="Fixture", process_name="editor.exe",
        rect=SimpleNamespace(left=100, top=200, right=1100, bottom=890))
    manager = SimpleNamespace(get_bound_window=lambda: bound)
    monkeypatch.setattr(action, "window_manager", manager)
    monkeypatch.setattr(action.screenshot_service, "capture_window", lambda **kw: {
        "image_path": "capture.png", "window_size": {"width": 1000, "height": 690}, "roi": None})
    monkeypatch.setattr(action, "_run_recognition_plan_for_execution", lambda req:
        APIResponse(success=True, message="fixture", data={"result": plan_fixture()}))
    monkeypatch.setattr(action, "_render_recognition_plan_overlay_for_execution", lambda p: None)
    monkeypatch.setattr(action, "write_trace", lambda **kw: str(tmp_path / "trace.json"))
    monkeypatch.setattr(action, "_rewrite_execute_trace_result", lambda **kw: None)
    monkeypatch.setattr(action, "_save_approved_plan", lambda **kw: pytest.fail("policy-off must not mint reusable authority"))
    request = ExecuteRecognitionPlanRequest(goal="Fixture control", dry_run=True, auto_observe_learning_artifacts=False,
        write_policy={"path_graph": False, "element_memory": False, "trace": True})
    ordinary = action.execute_recognition_plan(request)
    assert not ordinary.success
    reader = SimpleNamespace(read_identity=lambda handle: deepcopy(identity))
    with _local_operator_input_scope(manager=manager, identity_reader=reader, identity=identity,
            window_rect=(100, 200, 1100, 890), enabled=lambda: True):
        response = action.execute_recognition_plan(request)
    assert response.success, response
    result = response.data["result"]
    assert result["automatic_safety_interception"] is False
    assert result["automatic_policy_observation"]["allowed"] is False
    assert result["approved_plan_id"] is None
    clicks = []
    monkeypatch.setattr(action.input_controller, "click_point", lambda x, y, **kw:
        clicks.append((x, y)) or {"clicked": True, "window_point": {"x": x, "y": y}})
    with _local_operator_input_scope(manager=manager, identity_reader=reader, identity=identity,
            window_rect=(100, 200, 1100, 890), enabled=lambda: True):
        executed = action.execute_recognition_plan(request.model_copy(update={"dry_run": False, "enable_post_click_verification": False}))
    assert executed.success
    assert executed.data['result']['agent_step_result']['status'] == 'executed'
    assert executed.data['result']['verification_scope']['task_effect_verified'] is False
    assert executed.data['result']['verification_scope']['post_click_checks_passed'] is None
    assert executed.data['result']['agent_execution_guidance']['next_action'] == 'inspect_post_action_image'
    assert 'executed and verified' not in executed.message
    assert clicks == [(184, 516)]
    monkeypatch.setattr(action, '_capture_pre_action_state_with_foreground_retry',
        lambda **kw: ({'image_path': 'before.png'}, 0))
    monkeypatch.setattr(action.verifier, 'verify_action', lambda *a, **kw: {
        'verified': True, 'diff': {'changed': diff_changed},
        'verification_basis': {'diff_changed': diff_changed, 'cursor_and_focus': True},
        'before': {'image_path': 'before.png'}, 'after': {'image_path': 'after.png'}})
    with _local_operator_input_scope(manager=manager, identity_reader=reader, identity=identity,
            window_rect=(100, 200, 1100, 890), enabled=lambda: True):
        observed = action.execute_recognition_plan(request.model_copy(update={
            'dry_run': False, 'enable_post_click_verification': True, 'max_execution_attempts': 3}))
    assert observed.success
    observed_result = observed.data['result']
    assert len(observed_result['attempts']) == 1
    assert observed_result['attempts'][0]['verified'] is None
    assert observed_result['attempts'][0]['retry_reason'] == 'awaiting_agent_review'
    assert observed_result['attempts'][0]['retry_allowed'] is False
    assert observed_result['post_click_verification']['verified'] is None
    assert observed_result['post_click_verification']['diff']['changed'] is diff_changed
    assert observed_result['verification_scope']['judged_by'] == 'agent'
    assert observed_result['verification_scope']['post_click_checks_passed'] is None
    assert len(clicks) == 2
    broken = plan_fixture()
    broken["candidate_result"]["rejected"] = broken["candidate_result"]["candidates"]
    broken["candidate_result"]["candidates"] = []
    monkeypatch.setattr(action, "_run_recognition_plan_for_execution", lambda req:
        APIResponse(success=True, message="fixture", data={"result": broken}))
    with _local_operator_input_scope(manager=manager, identity_reader=reader, identity=identity,
            window_rect=(100, 200, 1100, 890), enabled=lambda: True):
        rejected = action.execute_recognition_plan(request)
    assert not rejected.success and rejected.error.code == "local_recognition_invalid"
    assert rejected.data["recognition_diagnostics"]["selection_status"] == "no_eligible_candidates"
    assert rejected.data["recognition_diagnostics"]["rejected_count"] == 1
    assert rejected.data["recognition_diagnostics"]["candidates"][0]["eligible"] is False
    assert rejected.data["action_executed"] is False and clicks == [(184, 516), (184, 516)]
    assert not action.execute_recognition_plan(request).success
