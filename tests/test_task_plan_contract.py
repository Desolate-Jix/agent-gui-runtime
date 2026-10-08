"""临时计划只接收显式线性语义，不把调用方内容当学习审核。"""
from copy import deepcopy

import pytest

from app.execution.task_plan_admission import validate_task_plan_request
from app.execution.task_plan_contract import (
    resolve_action_text, validate_task_plan, validate_task_plan_target,
)


def plan(*, verification=None, count=2):
    return {"schema_version": "task_plan.v1", "title": "Open fresh details", "inputs": {},
            "steps": [{"step_id": f"step-{i}", "action": {"kind": "click", "goal": f"Open panel {i}"},
                       "verification": deepcopy(verification or {"kind": "native_condition", "condition": {
                           "text": f"Panel {i}", "control_type": "Text"}})} for i in range(count)]}


def test_valid_plan_is_frozen_and_preserves_unicode():
    value = plan()
    value["inputs"]["query"] = "\u65b0\u67e5\u8be2"
    frozen = validate_task_plan(value)
    value["inputs"]["query"] = "changed"
    value["steps"][0]["action"]["goal"] = "changed"
    assert frozen["inputs"]["query"] == "\u65b0\u67e5\u8be2"
    assert frozen["steps"][0]["action"]["goal"] == "Open panel 0"


@pytest.mark.parametrize("field,value", [("source_kind", "reviewed_program"), ("review_status", "reviewed"),
                                         ("workflow_id", "learned"), ("outputs", {}), ("branches", {})])
def test_caller_plan_cannot_claim_learning_review(field, value):
    value_plan = plan()
    value_plan[field] = value
    with pytest.raises(ValueError):
        validate_task_plan(value_plan)


@pytest.mark.parametrize("count", [0, 9])
def test_plan_step_count_is_bounded(count):
    with pytest.raises(ValueError, match="steps_invalid"):
        validate_task_plan(plan(count=count))


@pytest.mark.parametrize("mutation", ["duplicate", "coordinates", "target_memory", "dynamic", "read_spec"])
def test_unbound_or_unsupported_actions_are_rejected(mutation):
    value = plan()
    if mutation == "duplicate":
        value["steps"][1]["step_id"] = value["steps"][0]["step_id"]
    elif mutation == "dynamic":
        value["steps"][0]["action"] = {"kind": "input_sequence", "field_goal": "Query", "text": {
            "source": "output", "name": "previous"}, "clear_existing": True, "submit_search": True}
    elif mutation == "read_spec":
        value["steps"][0]["read_spec"] = {"field": "value"}
    else:
        value["steps"][0]["action"][mutation] = {"x": 10, "y": 20}
    with pytest.raises(ValueError):
        validate_task_plan(value)


@pytest.mark.parametrize("value", [[], {}, None, float("nan"), float("inf")])
def test_input_values_are_finite_scalars(value):
    source = plan()
    source["inputs"]["query"] = value
    with pytest.raises(ValueError, match="input_value_invalid"):
        validate_task_plan(source)


def test_required_string_input_and_explicit_flags():
    source = plan()
    action = {"kind": "input_sequence", "field_goal": "Search", "text": {"source": "input", "name": "query"},
              "clear_existing": True, "submit_search": True}
    source["steps"][0]["action"] = action
    with pytest.raises(ValueError, match="required_input_missing"):
        validate_task_plan(source)
    source["inputs"]["query"] = 123
    with pytest.raises(ValueError, match="input_text_invalid"):
        validate_task_plan(source)
    source["inputs"]["query"] = "fresh"
    assert resolve_action_text(action["text"], validate_task_plan(source)["inputs"]) == "fresh"
    action["clear_existing"] = 1
    with pytest.raises(ValueError, match="input_flags_invalid"):
        validate_task_plan(source)


@pytest.mark.parametrize("action,verification", [
    ({"kind": "read_text", "goal": "Read result"}, {"kind": "agent_judgment", "decision_condition": "Result read"}),
    ({"kind": "read_text", "goal": "Read result"}, {"kind": "native_condition", "condition": {"text": "Ready", "control_type": "Text"}}),
    ({"kind": "input_sequence", "field_goal": "Query", "text": "fresh", "clear_existing": True, "submit_search": False},
     {"kind": "native_condition", "condition": {"text": "Ready", "control_type": "Text"}}),
])
def test_predicate_cannot_fabricate_dynamic_output_or_verify_plain_typing(action, verification):
    source = plan()
    source["steps"][0].update(action=action, verification=verification)
    with pytest.raises(ValueError):
        validate_task_plan(source)


@pytest.mark.parametrize("patch", [{"process_create_time": 0}, {"process_id": True}, {"handle": -1},
                                    {"process_create_time": float("nan")}, {"x": 10}])
def test_target_requires_exact_process_birth_identity(patch):
    with pytest.raises(ValueError, match="target_identity_invalid"):
        validate_task_plan_target({"handle": 11, "process_id": 22, "process_create_time": 33.0, **patch})


@pytest.mark.parametrize("patch", [{"verdict": "uncertain"}, {"reason": " "}, {"evidence_sha256": "missing"}, {"extra": True}])
def test_review_control_requires_bound_explicit_verdict(patch):
    review = {"action": "review", "run_id": "trial-" + "a" * 64, "step_id": "one", "execution_request_id": "exec-one",
              "verdict": "success", "reason": "Observed expected state", "evidence_sha256": "b" * 64, **patch}
    with pytest.raises(ValueError):
        validate_task_plan_request(review)
