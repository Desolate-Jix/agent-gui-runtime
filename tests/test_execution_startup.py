"""选窗外层失败不得提交计划，成功证据必须对应当前目标。"""
import asyncio
from copy import deepcopy
from hashlib import sha256

import pytest


def scenario(tmp_path):
    image = tmp_path / "current.png"
    image.write_bytes(b"current capture")
    select = {"request_id": "select-one", "command": {"kind": "select", "handle": 10, "process_id": 20}}
    plan = {"request_id": "plan-one", "command": {"kind": "task_plan", "request": {"action": "start"}}}
    response = {"request_id": "select-one", "status": "returned", "operation_succeeded": True,
        "client_state": "terminal", "result": {"status": "focused", "window": {"handle": 10, "process_id": 20}},
        "preparation_preview": {"identity": {"target_window_handle": 10, "process_id": 20, "process_create_time": 50.0}},
        "observation": {"image_path": str(image), "sha256": sha256(image.read_bytes()).hexdigest(),
            "window_identity": {"handle": 10, "process_id": 20, "process_create_time": 50.0},
            "capture_visibility": {"allowed": True, "bound_window_handle": 10}}}
    calls = []
    class Client:
        async def execute(self, message):
            calls.append(deepcopy(message))
            return deepcopy(response) if message["command"]["kind"] == "select" else {"status": "completed"}
    return Client(), select, plan, response, calls, image


@pytest.mark.parametrize("fault", ["outer_failure", "not_success", "pending", "missing_image", "wrong_window", "occluded", "changed_image", "wrong_request", "reused_pid"])
def test_failed_or_unbound_selection_never_submits_plan(tmp_path, fault):
    from scripts.execution_startup import run_selected_plan
    client, select, plan, response, calls, image = scenario(tmp_path)
    if fault == "outer_failure": response["status"] = "failed"
    elif fault == "not_success": response["operation_succeeded"] = False
    elif fault == "pending": response["client_state"] = "pending"
    elif fault == "missing_image": response.pop("observation")
    elif fault == "wrong_window": response["observation"]["window_identity"]["handle"] = 11
    elif fault == "occluded": response["observation"]["capture_visibility"]["allowed"] = False
    elif fault == "changed_image": image.write_bytes(b"changed")
    elif fault == "wrong_request": response["request_id"] = "old-select"
    elif fault == "reused_pid": response["observation"]["window_identity"]["process_create_time"] = 51.0
    before = deepcopy(plan)
    result = asyncio.run(run_selected_plan(client, select, plan))
    assert result["stage"] == "selection" and result["plan_submitted"] is False
    assert len(calls) == 1 and calls[0]["command"]["kind"] == "select"
    assert plan == before


def test_ready_selection_submits_original_plan_once(tmp_path):
    from scripts.execution_startup import run_selected_plan
    client, select, plan, response, calls, image = scenario(tmp_path)
    result = asyncio.run(run_selected_plan(client, select, plan))
    assert result["stage"] == "plan" and result["response"] == {"status": "completed"}
    assert calls == [{**select, "detail": "full"}, plan]


def test_transport_failure_never_retries_or_starts_plan(tmp_path):
    from scripts.execution_startup import run_selected_plan
    client, select, plan, response, calls, image = scenario(tmp_path)
    async def fail(message):
        calls.append(message)
        raise OSError("connection lost")
    client.execute = fail
    with pytest.raises(OSError):
        asyncio.run(run_selected_plan(client, select, plan))
    assert len(calls) == 1
