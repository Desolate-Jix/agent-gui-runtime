"""从冻结计划重建条件快照；不读取桌面或调用判断服务。"""
from copy import deepcopy
from hashlib import sha256
import json

from app.judgment.condition_templates import (
    resolve_condition_binding, validate_condition_binding, validate_condition_snapshot,
)


def _digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def resolve_plan_condition(rule, inputs):
    if "condition_binding" not in rule:
        return {"condition": rule.get("decision_condition")}
    declarations = {name: "string" for name, value in inputs.items() if type(value) is str}
    checked = validate_condition_binding(rule["condition_binding"], input_types=declarations)
    snapshot = resolve_condition_binding(checked, inputs)
    if "allowed_states" in rule and rule["allowed_states"] != snapshot["allowed_states"]:
        raise ValueError("task_plan_condition_states_conflict")
    return {"condition": snapshot["condition"], "condition_snapshot": snapshot}


def semantic_binding(plan, step):
    return resolve_plan_condition(step["verification"], plan["inputs"])


def effective_plan_review_policy(rule, *, condition_snapshot=None, host_policy=None, host_enabled=False):
    host_policy = host_policy or {}
    return "always_main" if (rule.get("review_policy") == "always_main"
        or (condition_snapshot or {}).get("review_policy") == "always_main"
        or host_enabled and host_policy.get("contract_version") == "decision_profile.v2"
        and host_policy.get("review_policy") == "always_main") else "adaptive"


def condition_snapshots(plan):
    return {step["step_id"]: semantic_binding(plan, step)["condition_snapshot"]
        for step in plan["steps"] if "condition_binding" in step["verification"]}


def validate_source_conditions(source, state):
    expected = condition_snapshots(source["plan"])
    if expected:
        if (source.get("condition_snapshots") != expected
                or state.get("condition_snapshots_sha256") != _digest(expected)
                or source.get("plan_sha256") != _digest(source["plan"])
                or state.get("plan_sha256") != source.get("plan_sha256")):
            raise ValueError("task_plan_condition_source_binding_invalid")
        for value in source["condition_snapshots"].values():
            validate_condition_snapshot(value)
    elif "condition_snapshots" in source or "condition_snapshots_sha256" in state:
        raise ValueError("task_plan_condition_source_binding_invalid")
    return deepcopy(expected)


def validate_packet_condition(packet, source, state):
    snapshots = validate_source_conditions(source, state)
    expected = snapshots.get(packet["step_id"])
    if expected is not None:
        if (packet.get("condition_snapshot") != expected
                or packet.get("expected_condition") != expected["condition"]):
            raise ValueError("task_plan_condition_packet_binding_invalid")
    elif "condition_snapshot" in packet:
        raise ValueError("task_plan_condition_packet_binding_invalid")


__all__ = ["resolve_plan_condition", "semantic_binding", "effective_plan_review_policy", "condition_snapshots",
           "validate_source_conditions", "validate_packet_condition"]
