"""固定本次运行的复用策略，不修改已审核程序或另建执行器。"""
from copy import deepcopy


def validate_execution_strategy(value):
    if not isinstance(value, str) or value not in {"learned", "steps_only"}:
        raise ValueError("workflow_trial_execution_strategy_invalid")
    return value


def execution_strategy(state):
    return validate_execution_strategy(state.get("execution_strategy", "learned"))


def command_step(library, step, state):
    """模型仍接收本次目标含义，但不接入记忆定位器。"""
    effective = deepcopy(step)
    if execution_strategy(state) == "learned":
        return effective
    # 仅修改本次策略复制体，原已审核图像配置和程序版本保持不变。
    if isinstance(effective.get('verification'), dict):
        effective['verification'].pop('image_check', None)
    action = effective["action"]
    reference = action.pop("target_memory", None)
    if reference is not None:
        from .target_recipe import action_semantics_sha256, load_target_recipe
        from .workflow_target_bindings import describe_bound_target_goal
        recipe = load_target_recipe(library, reference)
        if action_semantics_sha256(step["action"], scope=recipe["scope"], strategies=recipe["strategies"]) != recipe["action_semantics_sha256"]:
            raise ValueError("action_semantics_changed")
        bindings = {"run_id": state["run_id"], "inputs": state["inputs"],
                    "outputs": {key: {"run_id": state["run_id"], "value": value}
                                for key, value in state["outputs"].items()}}
        goal_key = "goal" if action["kind"] == "click" else "field_goal"
        action[goal_key] = describe_bound_target_goal(recipe, step["action"], bindings)
    return effective
