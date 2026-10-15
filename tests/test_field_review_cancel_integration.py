"""复用冻结的真实整合场景，取消必须结算原已输入前缀。"""
from copy import deepcopy
from pathlib import Path

import pytest

from app.core.input_controller import VK_CONTROL, VK_A, VK_V, VK_RETURN
from app.core.input_sequence_partial import original_input_status
from app.core.json_snapshot import read_json_snapshot
from app.execution.task_plan_admission import TaskPlanRuntime
from app.learning_memory.receipt_adapter import resolve_execution_receipt
from tests.test_field_review_integration import (
    test_same_runtime_plan_resumes_real_field_input_from_original_review as _run_scenario,
    wait_for, visual_sequence, scene, IDENTITY,
)


class _CancellationChecked(Exception):
    pass


@pytest.mark.parametrize("submit", [False, True])
@pytest.mark.parametrize("timing", ["waiting", "after_continue"])
def test_cancel_real_field_wait_settles_original_plan_without_replaying_input(visual_sequence, monkeypatch, submit, timing):
    original = TaskPlanRuntime.control
    def cancel_instead_of_review(runtime, request, request_id):
        if request.get("action") != "review":
            return original(runtime, request, request_id)
        execution = request["execution_request_id"]
        with runtime.agent_jobs._condition:
            if timing == "after_continue":
                reviewed = original(runtime, request, request_id)
                original(runtime, reviewed["caller_controls"]["continue"]["request"], "continue-before-cancel")
                assert runtime.agent_jobs.get(execution)["field_review"]["continued"] is True
            original(runtime, {"action": "cancel", "run_id": request["run_id"]}, "cancel-original-field-wait")
        job = wait_for(runtime.agent_jobs, execution, "cancelled")
        assert job["action_executed"] is True
        receipt_path = Path(runtime.session) / "responses" / (execution + ".json")
        effective, _ = resolve_execution_receipt(read_json_snapshot(receipt_path), receipt_path, execution)
        assert original_input_status(effective, effective["command"], succeeded=False,
            action_executed=True, target_identity=IDENTITY) == "failed"
        unknown = deepcopy(effective)
        unknown["result"]["steps"][0]["action_executed"] = None
        assert original_input_status(unknown, unknown["command"], succeeded=False,
            action_executed=True, target_identity=IDENTITY) == "unknown"
        assert effective["result"]["status"] == "interrupted"
        assert effective["result"]["phase"] == effective["result"]["interrupted_at"] == "check_input"
        terminal = runtime.tick(force=True)
        assert terminal["runner_state"] == "cancelled", terminal
        assert terminal["pending"] is None and len(terminal["history"]) == 1
        assert terminal["history"][0]["original_input_status"] == "failed"
        assert terminal["history"][0]["action_executed"] is True
        assert visual_sequence.events.count((VK_CONTROL, VK_A)) == 1
        assert visual_sequence.events.count((VK_CONTROL, VK_V)) == 1
        assert (VK_RETURN,) not in visual_sequence.events
        assert visual_sequence.events.count("gate-click") == 1
        assert len(list((Path(runtime.session) / "commands").glob("trial-exec-*.json"))) == 1
        raise _CancellationChecked
    monkeypatch.setattr(TaskPlanRuntime, "control", cancel_instead_of_review)
    with pytest.raises(_CancellationChecked):
        _run_scenario(visual_sequence, monkeypatch, submit)
