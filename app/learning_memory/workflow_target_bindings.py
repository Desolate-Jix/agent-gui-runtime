"""从宿主固定试运行票据恢复动态目标的当次变量。"""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import re

from app.desktop_review.external_mapping import canonical_json_bytes

from .target_selectors import _value
from .uia_rows import validate_visible_row_strategy
from .workflow_program import _type
from .workflow_trial import TrialService, _command
from .workspace import MemoryWorkspace


_REQUEST = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,159}\Z")


def _outputs(state, program):
    history = state.get("history")
    if not isinstance(history, list):
        raise ValueError("workflow_target_history_invalid")
    steps = {step["step_id"]: step for step in program["definition"]["steps"]}
    expected = {}
    for entry in history:
        if not isinstance(entry, dict) or entry.get("step_id") not in steps:
            raise ValueError("workflow_target_history_invalid")
        if entry.get("verdict") != "success":
            continue
        declarations = {row["name"]: row["type"] for row in steps[entry["step_id"]]["outputs"]}
        values = entry.get("outputs")
        if (not isinstance(values, dict) or set(values) != set(declarations)
                or any(not _type(value, declarations[name]) for name, value in values.items())):
            raise ValueError("workflow_target_history_outputs_invalid")
        for name, value in values.items():
            key = entry["step_id"] + "." + name
            if key in expected:
                raise ValueError("workflow_target_output_duplicate")
            expected[key] = value
    if state.get("outputs") != expected:
        raise ValueError("workflow_target_outputs_mismatch")
    return {key: {"run_id": state["run_id"], "value": deepcopy(value)} for key, value in expected.items()}


def load_workflow_target_bindings(library_root, session_dir, *, execution_request_id, command) -> dict | None:
    """只绑定本会话唯一 pending 原票据，不采信调用方传入的变量。"""
    if (not isinstance(execution_request_id, str) or not _REQUEST.fullmatch(execution_request_id)
            or not isinstance(command, dict)):
        raise ValueError("workflow_target_request_invalid")
    session = Path(session_dir).resolve()
    paths = sorted((session / "workflow-trials").glob("trial-*.json"))
    if len(paths) > 512:
        raise ValueError("workflow_target_trial_catalog_unbounded")
    with MemoryWorkspace(library_root) as library:
        trials = TrialService(library, session)
        matches = []
        for path in paths:
            state = trials.status(path.stem)
            pending = state.get("pending")
            history = state.get("history", [])
            prepared = state.get("prepare_requests", {})
            if (isinstance(pending, dict) and pending.get("execution_request_id") == execution_request_id
                    or isinstance(history, list) and any(isinstance(row, dict) and row.get("execution_request_id") == execution_request_id for row in history)
                    or isinstance(prepared, dict) and any(isinstance(row, dict) and isinstance(row.get("result"), dict)
                        and row["result"].get("execution_request_id") == execution_request_id for row in prepared.values())):
                matches.append(state)
        if not matches:
            return None
        if len(matches) != 1:
            raise ValueError("workflow_target_ticket_ambiguous")
        state = matches[0]
        from .workflow_execution_strategy import execution_strategy
        if execution_strategy(state) == "steps_only":
            raise ValueError("workflow_target_memory_disabled_by_strategy")
        pending = state.get("pending")
        if state.get("status") != "pending" or not isinstance(pending, dict) or pending.get("execution_request_id") != execution_request_id:
            raise ValueError("workflow_target_ticket_not_pending")
        if pending.get("suggested_command") != command:
            raise ValueError("workflow_target_command_mismatch")
        if pending.get("step_id") != state.get("current_step_id"):
            raise ValueError("workflow_target_step_mismatch")
        program = trials.programs.load(state["workflow_id"], state["program_id"])
        if program["program_id"] != state["program_id"] or program["project_snapshot_id"] != state["project_snapshot_id"]:
            raise ValueError("workflow_target_program_mismatch")
        steps = [row for row in program["definition"]["steps"] if row["step_id"] == pending["step_id"]]
        if len(steps) != 1:
            raise ValueError("workflow_target_step_mismatch")
        step = steps[0]
        action = step["action"]
        reference = action.get("target_memory")
        if (reference is None or command.get("request", {}).get("target_memory") != reference
                or pending.get("preview", {}).get("action") != action):
            raise ValueError("workflow_target_reference_mismatch")
        outputs = _outputs(state, program)
        base = deepcopy(command)
        base.pop("vision_capabilities", None)
        expected = _command(step, state["inputs"], {key: row["value"] for key, row in outputs.items()})
        if expected != base:
            raise ValueError("workflow_target_compiled_command_mismatch")
        return {"run_id": state["run_id"], "step_id": step["step_id"],
                "execution_request_id": execution_request_id,
                "command_sha256": sha256(canonical_json_bytes(command)).hexdigest(),
                "action": deepcopy(action), "inputs": deepcopy(state["inputs"]),
                "outputs": outputs}


def contextual_target_goal(recipe, bindings) -> str:
    """将当前可见行的有限条件写入未命中时的定位描述。"""
    required = {"run_id", "step_id", "execution_request_id", "command_sha256", "action", "inputs", "outputs"}
    if (not isinstance(recipe, dict) or not isinstance(bindings, dict) or set(bindings) != required
            or not isinstance(bindings["run_id"], str) or not bindings["run_id"]
            or not isinstance(bindings["inputs"], dict) or not isinstance(bindings["outputs"], dict)):
        raise ValueError("workflow_target_bindings_invalid")
    return describe_bound_target_goal(recipe, bindings["action"],
                                      {key: bindings[key] for key in ("run_id", "inputs", "outputs")})


def describe_bound_target_goal(recipe, action, bindings) -> str:
    """编译阶段与现场未命中共用描述，不使用旧坐标或旧输出。"""
    goal = action.get("goal") if isinstance(action, dict) and action.get("kind") == "click" else (
        action.get("field_goal") if isinstance(action, dict) and action.get("kind") == "input_sequence" else None)
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("workflow_target_goal_invalid")
    strategies = recipe.get("strategies")
    if not isinstance(strategies, list):
        raise ValueError("workflow_target_recipe_invalid")
    descriptions = []
    values = {key: bindings[key] for key in ("run_id", "inputs", "outputs")}
    for strategy in strategies:
        if not isinstance(strategy, dict):
            raise ValueError("workflow_target_recipe_invalid")
        if strategy.get("kind") != "visible_row":
            continue
        rule = validate_visible_row_strategy(strategy)
        conditions = []
        for item in rule["constraints"]:
            value = _value(item["value"], values)
            if item["operator"] == "contains" and not isinstance(value, str):
                raise ValueError("constraint_contains_invalid")
            conditions.append({"property": item["property"], "operator": item["operator"], "value": value})
        descriptions.append({"container": rule["container"], "row": rule["row"],
                             "properties": rule["properties"], "constraints": conditions,
                             "action": rule["action"]})
    if not descriptions:
        return goal
    return goal + "；本次可见行定位条件：" + json.dumps(descriptions, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = ["load_workflow_target_bindings", "contextual_target_goal"]
