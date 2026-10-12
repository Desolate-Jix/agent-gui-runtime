"""语义加载观察可显式提前采图，保持旧计划与原生条件预算。"""
from copy import deepcopy

import pytest

from app.execution.task_plan_backend import TaskPlanBackend
from app.execution.task_plan_contract import validate_task_plan


def source():
    return {"schema_version": "task_plan.v2", "title": "Open results", "inputs": {}, "steps": [{
        "step_id": "open", "action": {"kind": "click", "goal": "Open results"},
        "verification": {"kind": "agent_judgment", "decision_condition": "Results are visible",
            "wait_policy": {"loading_condition": "The results are visibly loading",
                "completion_excludes_loading": True}, "render_grace_ms": 0}}]}


@pytest.mark.parametrize("wait", [0, 200, 2000])
def test_semantic_render_grace_is_explicit_and_frozen(wait):
    value = source()
    value["steps"][0]["verification"]["render_grace_ms"] = wait
    frozen = validate_task_plan(value)
    value["steps"][0]["verification"]["render_grace_ms"] = 1000
    command = TaskPlanBackend._command(frozen["steps"][0], {})
    assert command["observation_wait_ms"] == wait
    assert "observation_condition" not in command
    assert "task_effect_verified" not in command


@pytest.mark.parametrize("wait", [-1, 2001, True, 0.5, "0", None])
def test_invalid_render_grace_is_rejected(wait):
    value = source()
    value["steps"][0]["verification"]["render_grace_ms"] = wait
    with pytest.raises(ValueError):
        validate_task_plan(value)


@pytest.mark.parametrize("mutation", ["no_loading", "overlap", "v1", "native", "read", "plain_input"])
def test_fast_capture_requires_explicit_semantic_loading_contract(mutation):
    value = source()
    step = value["steps"][0]
    if mutation == "no_loading":
        step["verification"].pop("wait_policy")
    elif mutation == "overlap":
        step["verification"]["wait_policy"]["completion_excludes_loading"] = False
    elif mutation == "v1":
        value["schema_version"] = "task_plan.v1"
    elif mutation == "read":
        step["action"] = {"kind": "read_text", "goal": "Read results"}
    elif mutation == "plain_input":
        step["action"] = {"kind": "input_sequence", "field_goal": "Query", "text": "sample",
                          "clear_existing": True, "submit_search": False}
    else:
        step["verification"].update(kind="native_condition", condition={"text": "Ready", "control_type": "Text"})
    with pytest.raises(ValueError):
        validate_task_plan(value)


def test_existing_commands_keep_original_wait_behavior():
    value = source()
    value["steps"][0]["verification"].pop("render_grace_ms")
    frozen = validate_task_plan(value)
    command = TaskPlanBackend._command(frozen["steps"][0], {})
    assert "observation_wait_ms" not in command
    native = deepcopy(frozen["steps"][0])
    native["verification"] = {"kind": "native_condition", "condition": {"text": "Ready", "control_type": "Text"}}
    command = TaskPlanBackend._command(native, {})
    assert command["observation_wait_ms"] == 2000
    assert command["observation_condition"] == native["verification"]["condition"]
