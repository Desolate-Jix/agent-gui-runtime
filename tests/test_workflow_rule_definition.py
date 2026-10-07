"""结果规则保存与变量引用必须受程序定义校验。"""
from copy import deepcopy

import pytest

from app.learning_memory.workflow_program import validate_definition
from tests.test_workflow_trial import services, WORKFLOW


def definition(saved):
    value = deepcopy(saved["definition"])
    step = value["steps"][0]
    step["success_conditions"] = []
    step["verification"] = {"kind": "field_equals", "target": {"control_type": "Edit", "name": "Search"},
        "expected": {"source": "input", "name": "query"}, "output_name": "result_title"}
    return value


def test_rules_save_reopen_and_edit_invalidate_downstream_review(services):
    programs, _, saved, _ = services
    value = definition(saved)
    result = programs.save(WORKFLOW, saved["content_sha256"], value, "rule-save")
    assert programs.load(WORKFLOW, result["program_id"])["definition"]["steps"][0]["verification"] == value["steps"][0]["verification"]
    assert result["definition"]["steps"][1]["review_status"] == "pending"
    assert "verification" not in programs.load(WORKFLOW, saved["program_id"])["definition"]["steps"][0]


@pytest.mark.parametrize("change", ["unknown_rule", "stale_output", "missing_input", "unscoped", "undeclared_output", "mixed_targets"])
def test_invalid_rule_cannot_be_saved(services, change):
    value = definition(services[2])
    step = value["steps"][0]
    rule = step["verification"]
    if change == "unknown_rule": rule["python"] = "run()"
    if change == "stale_output": rule["expected"] = {"source": "output", "step_id": "previous-run", "name": "title"}
    if change == "missing_input": rule["expected"]["name"] = "missing"
    if change == "unscoped": rule["target"] = {"control_type": "Edit"}
    if change == "undeclared_output": rule["output_name"] = "different"
    if change == "mixed_targets": step["read_spec"] = {"method": "visible_text", "output_name": "result_title", "target": {"name": "Other", "control_type": "Text"}}
    with pytest.raises(ValueError):
        validate_definition(value, {"home", "results"})


def test_read_rule_requires_declared_current_output_and_exact_locator(services):
    value = definition(services[2])
    step = value["steps"][0]
    step.pop("verification")
    step["action"] = {"kind": "read_text", "goal": "Read current result"}
    step["read_spec"] = {"method": "visible_text", "output_name": "result_title",
                         "target": {"control_type": "Text", "automation_id": "result"}}
    assert validate_definition(value, {"home", "results"}) == value
