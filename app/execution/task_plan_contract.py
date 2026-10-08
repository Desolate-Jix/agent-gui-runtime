"""临时调用方计划的严格合同；不推断参数、不导入学习资产。"""

from copy import deepcopy
from math import isfinite
import re


_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,159}\Z")
_SCALARS = (str, int, float, bool)


def _identifier(value, label):
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"task_plan_{label}_invalid")
    return value


def _text(value, label, maximum=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError(f"task_plan_{label}_invalid")
    return value


def resolve_action_text(value, inputs):
    """只解析已冻结的字面值或本次输入，不接受输出依赖。"""
    if isinstance(value, str):
        resolved = value
    elif isinstance(value, dict) and value.get("source") == "constant" and set(value) == {"source", "value"}:
        resolved = value["value"]
    elif isinstance(value, dict) and value.get("source") == "input" and set(value) == {"source", "name"}:
        name = _identifier(value["name"], "input_reference")
        if name not in inputs:
            raise ValueError("task_plan_required_input_missing")
        resolved = inputs[name]
    else:
        raise ValueError("task_plan_dynamic_output_unsupported" if isinstance(value, dict)
                         and value.get("source") == "output" else "task_plan_text_reference_invalid")
    if not isinstance(resolved, str) or not 1 <= len(resolved) <= 20000:
        raise ValueError("task_plan_input_text_invalid")
    return resolved


def _action(value, inputs):
    if not isinstance(value, dict):
        raise ValueError("task_plan_action_invalid")
    if "target_memory" in value:
        raise ValueError("task_plan_target_memory_unsupported")
    kind = value.get("kind")
    if kind == "click":
        if not {"kind", "goal"} <= set(value) or set(value) - {"kind", "goal", "click_kind", "target"}:
            raise ValueError("task_plan_action_fields_invalid")
        _text(value["goal"], "goal", 2000)
        if value.get("click_kind", "single") not in {"single", "double"}:
            raise ValueError("task_plan_click_kind_invalid")
    elif kind == "input_sequence":
        if set(value) - {"target"} != {"kind", "field_goal", "text", "clear_existing", "submit_search"}:
            raise ValueError("task_plan_action_fields_invalid")
        _text(value["field_goal"], "field_goal", 2000)
        if type(value["clear_existing"]) is not bool or type(value["submit_search"]) is not bool:
            raise ValueError("task_plan_input_flags_invalid")
        resolve_action_text(value["text"], inputs)
    elif kind == "read_text":
        if set(value) != {"kind", "goal"}:
            raise ValueError("task_plan_action_fields_invalid")
        _text(value["goal"], "goal", 2000)
    else:
        raise ValueError("task_plan_action_unsupported")
    if "target" in value:
        from .task_plan_target import validate_task_plan_control_target
        validate_task_plan_control_target(value["target"], for_input=kind == "input_sequence")


def _verification(value, action):
    if not isinstance(value, dict):
        raise ValueError("task_plan_verification_invalid")
    kind = value.get("kind")
    if kind == "agent_judgment":
        if "kind" not in value or set(value) - {"kind", "decision_condition"}:
            raise ValueError("task_plan_verification_fields_invalid")
        if "decision_condition" in value:
            if action["kind"] == "read_text":
                raise ValueError("task_plan_decision_dynamic_read_forbidden")
            _text(value["decision_condition"], "decision_condition")
    elif kind == "native_condition":
        if set(value) != {"kind", "condition"} or not isinstance(value["condition"], dict):
            raise ValueError("task_plan_verification_fields_invalid")
        if not (action["kind"] == "click" or action["kind"] == "input_sequence" and action["submit_search"]):
            raise ValueError("task_plan_native_condition_action_unsupported")
        from .conditional_observation import validate_condition
        if not isinstance(value["condition"], dict):
            raise ValueError("task_plan_native_condition_invalid")
        validate_condition(value["condition"], 2000)
    else:
        raise ValueError("task_plan_verification_unsupported")


def validate_task_plan(value: dict) -> dict:
    """返回独立副本；来源、分支、坐标和动态输出均不能由调用方扩充。"""
    if not isinstance(value, dict):
        raise ValueError("task_plan_invalid")
    if {"outputs", "read_spec"}.intersection(value):
        raise ValueError("task_plan_dynamic_output_unsupported")
    if set(value) != {"schema_version", "title", "inputs", "steps"} or value["schema_version"] != "task_plan.v1":
        raise ValueError("task_plan_fields_invalid")
    _text(value["title"], "title")
    inputs = value["inputs"]
    if not isinstance(inputs, dict) or len(inputs) > 128:
        raise ValueError("task_plan_inputs_invalid")
    for name, item in inputs.items():
        _identifier(name, "input_name")
        if (type(item) not in _SCALARS or isinstance(item, str) and len(item) > 20000
                or type(item) is float and not isfinite(item)):
            raise ValueError("task_plan_input_value_invalid")
    steps = value["steps"]
    if not isinstance(steps, list) or not 1 <= len(steps) <= 8:
        raise ValueError("task_plan_steps_invalid")
    seen = set()
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("task_plan_step_invalid")
        if {"outputs", "read_spec"}.intersection(step):
            raise ValueError("task_plan_dynamic_output_unsupported")
        if set(step) != {"step_id", "action", "verification"}:
            raise ValueError("task_plan_step_fields_invalid")
        step_id = _identifier(step["step_id"], "step_id")
        if step_id in seen:
            raise ValueError("task_plan_step_duplicate")
        seen.add(step_id)
        _action(step["action"], inputs)
        _verification(step["verification"], step["action"])
    return deepcopy(value)


def validate_task_plan_target(value: dict) -> dict:
    """绑定完整进程出生身份；不接收截图坐标或弱身份别名。"""
    if (not isinstance(value, dict) or set(value) != {"handle", "process_id", "process_create_time"}
            or type(value["handle"]) is not int or value["handle"] <= 0
            or type(value["process_id"]) is not int or value["process_id"] <= 0
            or type(value["process_create_time"]) not in (int, float)
            or not isfinite(value["process_create_time"]) or value["process_create_time"] <= 0):
        raise ValueError("task_plan_target_identity_invalid")
    return deepcopy(value)


__all__ = ["validate_task_plan", "validate_task_plan_target", "resolve_action_text"]
