"""结构化目标拒绝贯通严格零输入证明，保留真实派发的不确定与成功事实。"""
from copy import deepcopy

import pytest

from app.core.recognition_dispatch import recognition_plan_rejected_before_dispatch
from tests.test_local_step_timings import timed_scene
from tests.test_recognition_dispatch_boundary import owner
from tests.test_task_plan_dispatch_target import run_scene
from tests.test_task_plan_target import current_frame


@pytest.fixture
def rejected(current_frame, monkeypatch):
    response, clicks, hits = run_scene(current_frame, monkeypatch, "pid")
    assert clicks == [] and len(hits) == 1
    return response.model_dump()


@pytest.mark.parametrize("defect", ["pid", "runtime", "name", "disabled", "bbox",
                                     "second_hit_runtime", "container_missing", "provider"])
def test_public_guard_typed_rejection_produces_complete_zero_input_proof(current_frame, monkeypatch, defect):
    response, clicks, hits = run_scene(current_frame, monkeypatch, defect)
    response = response.model_dump()
    data = response["data"]
    assert response["success"] is False and clicks == [] and 1 <= len(hits) <= 2
    assert data["execution_path"]["action_executed"] is False
    assert data["agent_step_result"]["action_executed"] is False
    assert data["attempts"] == [] and data["fallback_plan"]["attempt_count"] == 0
    assert data["dispatch_status"] == "not_dispatched" and data["input_started"] is False
    reason = response["error"]["details"]
    assert data["task_plan_dispatch_target_check"] == {
        "status": "rejected", "error_code": reason, "action_executed": False}
    assert data["pre_click_input_rejection"] == {
        "contract_version": "recognition_pre_click_rejection.v1", "validator": "structured_target",
        "reason_code": reason, "click_dispatch_started": False}
    assert recognition_plan_rejected_before_dispatch(response)


def test_real_producer_owner_and_terminal_preserve_zero_without_rewriting_response(
        rejected, timed_scene, monkeypatch, tmp_path):
    from app.learning_memory.workflow_trial import _actual_action_executed
    from tests.test_session_input_terminal import save, inspect
    original = deepcopy(rejected)
    local = owner(timed_scene, monkeypatch, rejected)
    assert local["phase"] == "not_dispatched" and local["action_executed"] is False
    assert _actual_action_executed(local) is False
    root = tmp_path / "terminal"
    command = {"kind": "step", "operation": "execute_recognition_plan", "request": {"goal": "Click Find"}}
    save(root, "commands", "original", command)
    save(root, "responses", "original", {"status": "returned", "command": command, "result": local})
    before = {str(p): p.read_bytes() for p in root.rglob("*.json")}
    row = inspect(root)["commands"]["original"]
    assert row["terminal_status"] == "not_dispatched" and row["action_executed"] is False
    assert before == {str(p): p.read_bytes() for p in root.rglob("*.json")}
    assert rejected == original


@pytest.mark.parametrize("damage", ["missing_check", "matched_check", "check_true", "check_unknown",
    "check_reason", "missing_proof", "proof_reason", "wrong_validator", "proof_started", "input_started",
    "no_stage", "path_true", "step_true", "fallback_attempt", "attempt", "click_sequence", "nested_false_only"])
def test_missing_tampered_or_conflicting_proof_stays_unknown(rejected, timed_scene, monkeypatch, damage):
    from app.learning_memory.workflow_trial import _actual_action_executed
    response = deepcopy(rejected)
    data = response["data"]
    if damage == "missing_check": data.pop("task_plan_dispatch_target_check", None)
    elif damage == "matched_check": data["task_plan_dispatch_target_check"]["status"] = "matched"
    elif damage == "check_true": data["task_plan_dispatch_target_check"]["action_executed"] = True
    elif damage == "check_unknown": data["task_plan_dispatch_target_check"]["action_executed"] = None
    elif damage == "check_reason": data["task_plan_dispatch_target_check"]["error_code"] = "other"
    elif damage == "missing_proof": data.pop("pre_click_input_rejection", None)
    elif damage == "proof_reason": data["pre_click_input_rejection"]["reason_code"] = "other"
    elif damage == "wrong_validator": data["pre_click_input_rejection"]["validator"] = "other"
    elif damage == "proof_started": data["pre_click_input_rejection"]["click_dispatch_started"] = True
    elif damage == "input_started": data["input_started"] = True
    elif damage == "no_stage": data.pop("dispatch_stage", None)
    elif damage == "path_true": data["execution_path"]["action_executed"] = True
    elif damage == "step_true": data["agent_step_result"]["action_executed"] = True
    elif damage == "fallback_attempt": data["fallback_plan"]["attempt_count"] = 1
    elif damage == "attempt": data["attempts"] = [{"click_result": {"clicked": True}}]
    elif damage == "click_sequence": data["click_sequence"] = {"input_attempted": True}
    else:
        for key in ("pre_click_input_rejection", "dispatch_status", "dispatch_stage", "input_started"):
            data.pop(key, None)
    assert recognition_plan_rejected_before_dispatch(response) is False
    local = owner(timed_scene, monkeypatch, response)
    assert local["phase"] == "result_unknown"
    assert _actual_action_executed(local) is (True if damage == "path_true" else None)


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
def test_untyped_guard_failure_does_not_claim_no_dispatch(current_frame, monkeypatch, error_type):
    from app.execution import task_plan_target
    def reject(*args, **kwargs):
        raise error_type("synthetic untyped guard failure")
    monkeypatch.setattr(task_plan_target, "validate_task_plan_dispatch_target", reject)
    response, clicks, hits = run_scene(current_frame, monkeypatch)
    assert clicks == [] and hits == []
    data = response.data
    assert data["execution_path"]["action_executed"] is None
    assert data["agent_step_result"]["action_executed"] is None
    assert data.get("pre_click_input_rejection") is None
    assert not recognition_plan_rejected_before_dispatch(response.model_dump())


def test_same_typed_error_outside_the_structured_guard_remains_unknown(current_frame, monkeypatch):
    from app.agent.windows_control_hit_reader import NativeControlHitError
    from app.core import local_text_focus
    def reject(*args, **kwargs):
        raise NativeControlHitError("native_control_hit_window_or_process_changed")
    monkeypatch.setattr(local_text_focus, "check_local_text_focus", reject)
    response, clicks, hits = run_scene(current_frame, monkeypatch)
    assert clicks == [] and hits == []
    assert response.data["execution_path"]["action_executed"] is None
    assert response.data.get("pre_click_input_rejection") is None
    assert not recognition_plan_rejected_before_dispatch(response.model_dump())


@pytest.mark.parametrize("stage,expected", [("dispatch", None), ("confirmed", True)])
def test_dispatch_boundary_and_confirmed_click_keep_original_facts(current_frame, monkeypatch, stage, expected):
    from app.api import action
    from app.agent.windows_control_hit_reader import NativeControlHitError
    from app.execution import task_plan_target
    original = task_plan_target.validate_task_plan_dispatch_target
    dispatches = []
    def reject(*args, **kwargs):
        raise NativeControlHitError("native_control_hit_window_or_process_changed")
    def guard(*args, **kwargs):
        result = original(*args, **kwargs)
        if stage == "dispatch":
            def click(*args, **kwargs):
                dispatches.append("started")
                return reject()
            monkeypatch.setattr(action.input_controller, "click_point", click)
        else:
            monkeypatch.setattr(action, "_apply_metadata_post_click_policy", reject)
        return result
    monkeypatch.setattr(task_plan_target, "validate_task_plan_dispatch_target", guard)
    response, clicks, hits = run_scene(current_frame, monkeypatch)
    assert len(hits) == 2
    assert (dispatches == ["started"] and clicks == []) if stage == "dispatch" else clicks == [(100, 100)]
    assert response.data["execution_path"]["action_executed"] is expected
    assert response.data["agent_step_result"]["action_executed"] is expected
    assert response.data.get("pre_click_input_rejection") is None
    assert response.data.get("dispatch_status") != "not_dispatched"
    assert not recognition_plan_rejected_before_dispatch(response.model_dump())


@pytest.mark.parametrize("popup", [777, True, -1, "777", None])
def test_explicit_popup_scope_is_validated_before_final_input(current_frame, monkeypatch, popup):
    from app.api import action
    from app.execution import task_plan_target
    seen = []
    def guard(*args, **kwargs):
        def click(x, y, **options):
            seen.append(options)
            return {"clicked": True, "window_point": {"x": x, "y": y}}
        monkeypatch.setattr(action.input_controller, "click_point", click)
        return {"status": "matched", "expected_owned_popup_handle": popup}
    monkeypatch.setattr(task_plan_target, "validate_task_plan_dispatch_target", guard)
    response, _, _ = run_scene(current_frame, monkeypatch, kind="MenuItem")
    if type(popup) is int and popup > 0:
        assert response.success and len(seen) == 1
        assert seen[0]["expected_owned_popup_handle"] == popup
    else:
        assert not response.success and seen == []
        assert response.error.details == "task_plan_target_popup_scope_invalid"
        assert response.data["execution_path"]["action_executed"] is None
        assert response.data.get("pre_click_input_rejection") is None


def test_conflicting_already_bound_popup_is_rejected_without_overwriting(current_frame, monkeypatch):
    from app.core import local_control_target
    from app.execution import task_plan_target
    monkeypatch.setattr(local_control_target, "check_local_control_target", lambda *args: {
        "status": "matched", "option_runtime_id": [42, 1], "expanded": True,
        "expected_owned_popup_handle": 555})
    monkeypatch.setattr(task_plan_target, "validate_task_plan_dispatch_target", lambda *args, **kwargs: {
        "status": "matched", "expected_owned_popup_handle": 777})
    response, clicks, hits = run_scene(current_frame, monkeypatch, kind="MenuItem")
    assert not response.success and clicks == [] and hits == []
    assert response.error.details == "task_plan_target_popup_scope_conflict"
    assert response.data["execution_path"]["action_executed"] is None
    assert response.data.get("pre_click_input_rejection") is None


def test_popup_field_on_other_control_is_rejected_without_expanding_scope(current_frame, monkeypatch):
    from app.api import action
    from app.execution import task_plan_target
    seen = []
    def guard(*args, **kwargs):
        monkeypatch.setattr(action.input_controller, "click_point", lambda x, y, **options:
            seen.append(options) or {"clicked": True, "window_point": {"x": x, "y": y}})
        return {"status": "matched", "expected_owned_popup_handle": 777}
    monkeypatch.setattr(task_plan_target, "validate_task_plan_dispatch_target", guard)
    response, _, _ = run_scene(current_frame, monkeypatch, kind="Button")
    assert not response.success and seen == []
    assert response.error.details == "task_plan_target_popup_scope_invalid"
    assert response.data["execution_path"]["action_executed"] is None
    assert response.data.get("pre_click_input_rejection") is None


def test_same_already_bound_popup_remains_unchanged(current_frame, monkeypatch):
    from app.api import action
    from app.core import local_control_target
    from app.execution import task_plan_target
    seen = []
    monkeypatch.setattr(local_control_target, "check_local_control_target", lambda *args: {
        "status": "matched", "option_runtime_id": [42, 1], "expanded": True,
        "expected_owned_popup_handle": 777})
    def guard(*args, **kwargs):
        monkeypatch.setattr(action.input_controller, "click_point", lambda x, y, **options:
            seen.append(options) or {"clicked": True, "window_point": {"x": x, "y": y}})
        return {"status": "matched", "expected_owned_popup_handle": 777}
    monkeypatch.setattr(task_plan_target, "validate_task_plan_dispatch_target", guard)
    response, _, _ = run_scene(current_frame, monkeypatch, kind="MenuItem")
    assert response.success and len(seen) == 1
    assert seen[0]["expected_owned_popup_handle"] == 777


@pytest.mark.parametrize("status", ["rejected", None, False])
def test_explicit_popup_scope_with_unmatched_proof_is_rejected(current_frame, monkeypatch, status):
    from app.execution import task_plan_target
    monkeypatch.setattr(task_plan_target, "validate_task_plan_dispatch_target", lambda *args, **kwargs: {
        "status": status, "expected_owned_popup_handle": 777})
    response, clicks, hits = run_scene(current_frame, monkeypatch, kind="MenuItem")
    assert not response.success and clicks == [] and hits == []
    assert response.error.details == "task_plan_target_popup_scope_invalid"
    assert response.data["execution_path"]["action_executed"] is None
    assert response.data.get("pre_click_input_rejection") is None


def test_root_without_popup_key_keeps_original_dispatch(current_frame, monkeypatch):
    response, clicks, hits = run_scene(current_frame, monkeypatch)
    assert response.success and clicks == [(100, 100)] and len(hits) == 2
    check = response.data["result"]["task_plan_dispatch_target_check"]
    assert check["status"] == "matched" and "expected_owned_popup_handle" not in check
