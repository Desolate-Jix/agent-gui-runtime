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


def _action(value, inputs, *, version="task_plan.v1"):
    if not isinstance(value, dict):
        raise ValueError("task_plan_action_invalid")
    if "target_memory" in value:
        raise ValueError("task_plan_target_memory_unsupported")
    kind = value.get("kind")
    if "target_identity" in value:
        if version != "task_plan.v3" or kind not in {"click", "input_sequence"}:
            raise ValueError("task_plan_target_identity_unsupported")
        from app.judgment.target_identity import normalize_target_identity
        normalize_target_identity(value["target_identity"])
    if kind == "click":
        if not {"kind", "goal"} <= set(value) or set(value) - {"kind", "goal", "click_kind", "target", "target_identity"}:
            raise ValueError("task_plan_action_fields_invalid")
        _text(value["goal"], "goal", 2000)
        if value.get("click_kind", "single") not in {"single", "double"}:
            raise ValueError("task_plan_click_kind_invalid")
    elif kind == "input_sequence":
        if set(value) - {"target", "target_identity"} != {"kind", "field_goal", "text", "clear_existing", "submit_search"}:
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


def _verification(value, action, *, version="task_plan.v1", inputs=None):
    if not isinstance(value, dict):
        raise ValueError("task_plan_verification_invalid")
    kind = value.get("kind")
    if kind == "agent_judgment":
        allowed = {"kind", "decision_condition"}
        if version in {"task_plan.v2", "task_plan.v3"}:
            allowed.update({"allowed_states", "review_policy", "wait_policy", "condition_binding", "render_grace_ms"})
        if "kind" not in value or set(value) - allowed:
            raise ValueError("task_plan_verification_fields_invalid")
        if {"decision_condition", "condition_binding"} <= set(value):
            raise ValueError("task_plan_condition_sources_conflict")
        if "condition_binding" in value:
            if action["kind"] == "read_text":
                raise ValueError("task_plan_decision_dynamic_read_forbidden")
            from .task_plan_conditions import resolve_plan_condition
            resolve_plan_condition(value, {} if inputs is None else inputs)
        if "allowed_states" in value:
            states = value["allowed_states"]
            if not isinstance(states, list) or len(states) > 32:
                raise ValueError("task_plan_allowed_states_invalid")
            for item in states:
                _text(item, "allowed_state", 1000)
        if "review_policy" in value and value["review_policy"] != "always_main":
            raise ValueError("task_plan_review_policy_cannot_expand_authority")
        if "wait_policy" in value:
            wait = value["wait_policy"]
            if (not {"decision_condition", "condition_binding"}.intersection(value) or not isinstance(wait, dict)
                    or set(wait) != {"loading_condition", "completion_excludes_loading"}
                    or type(wait["completion_excludes_loading"]) is not bool):
                raise ValueError("task_plan_wait_policy_invalid")
            _text(wait["loading_condition"], "loading_condition")
        if "render_grace_ms" in value:
            from app.core.observation_policy import resolve_render_grace_ms
            resolve_render_grace_ms("", value["render_grace_ms"])
            if (type(value["render_grace_ms"]) is not int
                    or not value.get("wait_policy", {}).get("completion_excludes_loading")
                    or not (action["kind"] == "click"
                            or action["kind"] == "input_sequence" and action["submit_search"])):
                raise ValueError("task_plan_render_grace_requires_loading_contract")
        if "decision_condition" in value:
            if action["kind"] == "read_text":
                raise ValueError("task_plan_decision_dynamic_read_forbidden")
            _text(value["decision_condition"], "decision_condition")
    elif kind in {"video_playback", "dynamic_content"}:
        allowed = {"kind", "decision_condition", "allowed_states", "review_policy", "render_grace_ms"}
        required = {"kind", "decision_condition"}
        if kind == "dynamic_content":
            allowed.add("target_description")
            required.add("target_description")
        if (version not in {"task_plan.v2", "task_plan.v3"} or not required <= set(value)
                or set(value) - allowed):
            raise ValueError(f"task_plan_{kind}_contract_invalid")
        if kind == "dynamic_content":
            _text(value["target_description"], "dynamic_content_target_description", 1000)
        _verification({"kind": "agent_judgment", **{key: value[key] for key in
            ("decision_condition", "allowed_states", "review_policy") if key in value}},
            action, version=version, inputs=inputs)
        if not (action["kind"] == "click" or action["kind"] == "input_sequence" and action["submit_search"]):
            raise ValueError(f"task_plan_{kind}_action_unsupported")
        if "render_grace_ms" in value:
            from app.core.observation_policy import resolve_render_grace_ms
            if type(value["render_grace_ms"]) is not int:
                prefix = "video" if kind == "video_playback" else "dynamic_content"
                raise ValueError(f"task_plan_{prefix}_render_grace_invalid")
            resolve_render_grace_ms("", value["render_grace_ms"])
    elif kind == "native_condition":
        options = {"decision_condition", "condition_binding", "allowed_states", "review_policy", "wait_policy"}
        allowed = {"kind", "condition"} | (options if version in {"task_plan.v2", "task_plan.v3"} else set())
        if (not {"kind", "condition"} <= set(value) or set(value) - allowed
                or not isinstance(value["condition"], dict)):
            raise ValueError("task_plan_verification_fields_invalid")
        if options.intersection(value):
            if not {"decision_condition", "condition_binding"}.intersection(value):
                raise ValueError("task_plan_native_decision_condition_required")
            _verification({"kind": "agent_judgment", **{key: value[key] for key in options if key in value}},
                action, version=version, inputs=inputs)
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
    version = value.get("schema_version")
    fields = {"schema_version", "title", "inputs", "steps"}
    if version == "task_plan.v3":
        fields.update({"goal", "completion"})
    if set(value) != fields or version not in {"task_plan.v1", "task_plan.v2", "task_plan.v3"}:
        raise ValueError("task_plan_fields_invalid")
    if version == "task_plan.v3":
        _text(value["goal"], "final_goal")
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
    if not isinstance(steps, list) or not steps:
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
        _action(step["action"], inputs, version=version)
        _verification(step["verification"], step["action"], version=value["schema_version"], inputs=inputs)
    if version == "task_plan.v3":
        completion = value["completion"]
        if (not isinstance(completion, dict) or set(completion) != {"step_id", "verification"}
                or completion.get("step_id") != steps[-1]["step_id"]):
            raise ValueError("task_plan_completion_final_step_required")
        _verification(completion["verification"], steps[-1]["action"], version=version, inputs=inputs)
        if (completion["verification"]["kind"] == "agent_judgment"
                and not {"decision_condition", "condition_binding"}.intersection(completion["verification"])):
            raise ValueError("task_plan_completion_observable_condition_required")
    if version in {"task_plan.v2", "task_plan.v3"}:
        from .task_plan_review import review_context
        # 所有步骤先完成结构校验，再以真实来源标识长度核验输入前的摘要边界。
        for step in steps:
            review_context(value, step, source_id="task-plan-" + "0" * 64, source_sha256="0" * 64)
    return deepcopy(value)


def completion_snapshot(plan):
    """最终条件与解析结果一起冻结，不能只绑定最后一次点击。"""
    if plan["schema_version"] != "task_plan.v3":
        return None
    from .task_plan_conditions import resolve_plan_condition
    return {"schema": "task_plan_completion.v1", "goal": plan["goal"],
        **deepcopy(plan["completion"]),
        "semantic": resolve_plan_condition(plan["completion"]["verification"], plan["inputs"])}


def goal_completion_proof(plan, result):
    snapshot = completion_snapshot(plan)
    if snapshot is None or result["step_id"] != snapshot["step_id"]:
        return None
    from .task_plan_review import digest
    same = snapshot["verification"] == plan["steps"][-1]["verification"]
    proof = ("main_review" if result["judged_by"] == "agent" else "final_step"
        if result["verdict"] == "success" and same else "not_proven")
    return {"schema": "task_plan_goal_completion.v1", "completion_snapshot_sha256": digest(snapshot),
        "step_id": snapshot["step_id"], "execution_request_id": result["execution_request_id"], "proof": proof}


def validate_task_plan_target(value: dict) -> dict:
    """绑定完整进程出生身份；不接收截图坐标或弱身份别名。"""
    if (not isinstance(value, dict) or set(value) != {"handle", "process_id", "process_create_time"}
            or type(value["handle"]) is not int or value["handle"] <= 0
            or type(value["process_id"]) is not int or value["process_id"] <= 0
            or type(value["process_create_time"]) not in (int, float)
            or not isfinite(value["process_create_time"]) or value["process_create_time"] <= 0):
        raise ValueError("task_plan_target_identity_invalid")
    return deepcopy(value)


__all__ = ["validate_task_plan", "validate_task_plan_target", "resolve_action_text", "completion_snapshot", "goal_completion_proof"]
