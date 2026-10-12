"""真实控件拒绝贯通输入前证明、owner、序列与队列终结，不替换证明生产者。"""
from copy import deepcopy

import pytest

from app.core import local_control_target as controls
from app.core.recognition_dispatch import recognition_plan_rejected_before_dispatch
from tests.test_form_fill import control
from tests.test_recognition_dispatch_boundary import route, owner, sequence
from tests.test_local_step_timings import timed_scene


@pytest.fixture
def rejected(route):
    identity = {"contract_version": "windows_native_identity_observation_v1", "provider": "windows_native_identity",
        "status": "observed", "target_window_handle": 321, "process_id": 12,
        "process_create_time": 123.5, "executable_path": "c:\\fixture\\editor.exe"}
    before = control(window_identity=identity, window_rect=[100, 200, 1000, 690],
                     bbox={"x": 160, "y": 492, "w": 48, "h": 48})
    guard = controls.LocalControlTarget(lambda: {**deepcopy(before), "runtime_id": [999]}, before)
    with controls.local_control_target_scope(guard):
        response = route.run("success")
    assert route.events == []
    return response


def test_real_control_guard_exports_complete_consistent_zero_input_proof(rejected):
    data = rejected["data"]
    assert data["control_target_check"]["status"] == "rejected"
    assert data["control_target_check"]["action_executed"] is False
    assert data["execution_path"]["action_executed"] is False
    assert data.get("pre_click_input_rejection") == {
        "contract_version": "recognition_pre_click_rejection.v1", "validator": "control_target",
        "reason_code": data["control_target_check"]["error_code"], "click_dispatch_started": False}
    assert recognition_plan_rejected_before_dispatch(rejected)


@pytest.mark.parametrize("damage", ["missing_check", "matched", "check_true", "check_unknown", "reason",
    "missing_proof", "wrong_validator", "started", "action_true", "click_sequence", "attempt"])
def test_conflicting_control_rejection_cannot_prove_zero_input(rejected, timed_scene, monkeypatch, damage):
    from app.learning_memory.workflow_trial import _actual_action_executed
    response = deepcopy(rejected)
    data = response["data"]
    if damage == "missing_check": data.pop("control_target_check", None)
    elif damage == "matched": data["control_target_check"]["status"] = "matched"
    elif damage == "check_true": data["control_target_check"]["action_executed"] = True
    elif damage == "check_unknown": data["control_target_check"]["action_executed"] = None
    elif damage == "reason": data["control_target_check"]["error_code"] = "other"
    elif damage == "missing_proof": data.pop("pre_click_input_rejection", None)
    elif damage == "wrong_validator": data.setdefault("pre_click_input_rejection", {})["validator"] = "other"
    elif damage == "started": data["input_started"] = True
    elif damage == "action_true": data["execution_path"]["action_executed"] = True
    elif damage == "click_sequence": data["click_sequence"] = {"input_attempted": True}
    else: data["attempts"] = [{"click_result": {"clicked": True}}]
    assert recognition_plan_rejected_before_dispatch(response) is False
    local = owner(timed_scene, monkeypatch, response)
    assert local["phase"] == "result_unknown"
    assert _actual_action_executed(local) is (True if damage == "action_true" else None)


@pytest.mark.parametrize("cancel", [False, True])
def test_control_proof_settles_original_queue_without_replay(rejected, timed_scene, monkeypatch, tmp_path, cancel):
    from app.core.json_snapshot import write_json_snapshot
    from tests.test_task_plan_contract import plan
    from tests.test_task_plan_runner import scene
    result = sequence(timed_scene, monkeypatch, rejected)
    assert result["action_executed"] is False and result["completed_steps"] == []
    assert result["steps"][0]["status"] == "not_dispatched"
    source = plan(verification={"kind": "agent_judgment"})
    source["schema_version"] = "task_plan.v2"
    source["steps"][0]["action"] = {"kind": "input_sequence", "field_goal": "Focus the fresh field",
        "text": "fresh synthetic text", "clear_existing": True, "submit_search": False}
    s = scene(tmp_path, monkeypatch, source=source)
    pending = s.runtime.backend.status(s.run_id)["pending"]
    path = s.session / "responses" / (pending["execution_request_id"] + ".json")
    write_json_snapshot(path, {"status": "returned", "command": deepcopy(pending["suggested_command"]), "result": result})
    original = path.read_bytes()
    if cancel: s.runtime.control({"action": "cancel", "run_id": s.run_id}, "cancel-original")
    final = s.runtime.tick(force=True)
    assert final["status"] == ("cancelled" if cancel else "failed") and final["pending"] is None
    assert final["history"][0]["action_executed"] is False
    s.runtime.admit("owned-close", {"kind": "close_launched_window", "request": {}})
    assert s.runtime.tick(force=True) is None
    assert len(list(s.session.glob("commands/*.json"))) == 1 and path.read_bytes() == original
