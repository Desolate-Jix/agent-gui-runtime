"""长计划完成回执经真实客户端状态轮询认证，不启动宿主或输入。"""
import asyncio
from copy import deepcopy

import pytest

from tests.test_execution_client import PlanSDK, RUN_ID, client, snapshot
from tests.test_task_plan_client import COMMAND


def command_and_terminal(count):
    command = deepcopy(COMMAND)
    prototype = command["request"]["plan"]["steps"][0]
    steps = []
    history = []
    for index in range(count):
        step = deepcopy(prototype)
        step["step_id"] = f"step-{index}"
        step["action"]["goal"] = f"Open panel {index}"
        steps.append(step)
        history.append({"step_id": step["step_id"], "execution_request_id": f"input-{index}",
            "verdict": "success", "judged_by": "native_condition"})
    command["request"]["plan"]["steps"] = steps
    terminal = snapshot(completed=2)
    terminal["history"] = history
    terminal["metrics"].update(planned_steps=count, settled_steps=count, successful_steps=count)
    return command, terminal


def through_client_status(tmp_path, terminal, command):
    sdk = PlanSDK([snapshot(), terminal])

    async def scenario():
        async with client(tmp_path, sdk, allow_actions=True) as opened:
            return await opened.execute({"request_id": "original-start",
                "command": command, "total_timeout": 1})

    return asyncio.run(scenario()), sdk


@pytest.mark.parametrize("count", [9, 10, 258])
def test_completed_long_plan_is_adopted_from_actual_client_status(tmp_path, count):
    command, terminal = command_and_terminal(count)
    result, sdk = through_client_status(tmp_path, terminal, command)
    assert result["client_state"] == "terminal"
    assert result["status_source"] == "instant_status"
    assert result["run_id"] == RUN_ID
    assert result["result"]["status"] == result["result"]["runner_state"] == "completed"
    assert len(result["result"]["history"]) == count
    assert [ref["arguments"]["request_id"] for ref in result["execution_receipts"]] == [
        f"input-{index}" for index in range(count)]
    submits = [args for name, args in sdk.calls if name == "instant_run"]
    assert len(submits) == 1 and submits[0]["request_id"] == "original-start"
    assert sdk.session_enters == sdk.session_exits == 1


@pytest.mark.parametrize("count", [None, True, False, 0, -1, 9.0, "9"])
def test_completed_plan_count_must_remain_positive_integer(tmp_path, count):
    command, terminal = command_and_terminal(9)
    terminal["metrics"]["planned_steps"] = count
    with pytest.raises(ValueError, match="completion_unproven"):
        through_client_status(tmp_path, terminal, command)


@pytest.mark.parametrize("fault", ["short_history", "extra_history", "successful_count",
    "failed_history", "missing_execution_id", "remaining_current_step"])
def test_long_completion_still_requires_matching_all_success_history(tmp_path, fault):
    command, terminal = command_and_terminal(9)
    if fault == "short_history":
        terminal["history"].pop()
    elif fault == "extra_history":
        terminal["history"].append({"step_id": "extra", "execution_request_id": "input-extra", "verdict": "success"})
    elif fault == "successful_count":
        terminal["metrics"]["successful_steps"] = 8
    elif fault == "failed_history":
        terminal["history"][-1]["verdict"] = "failure"
    elif fault == "missing_execution_id":
        del terminal["history"][-1]["execution_request_id"]
    else:
        terminal["current_step_id"] = "step-8"
    with pytest.raises(ValueError, match="completion_unproven|history_invalid"):
        through_client_status(tmp_path, terminal, command)


@pytest.mark.parametrize("field", ["run_id", "plan_id", "plan_sha256", "start_request_id", "target_identity"])
def test_long_plan_completion_keeps_original_binding(tmp_path, field):
    command, terminal = command_and_terminal(9)
    if field == "target_identity":
        terminal[field]["pid"] += 1
    else:
        terminal[field] += "-changed"
    with pytest.raises(ValueError, match="identity_mismatch|binding_mismatch"):
        through_client_status(tmp_path, terminal, command)
