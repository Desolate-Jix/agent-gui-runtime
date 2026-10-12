"""共享输入合同保持原序列格式，学习侧校验不加载执行器。"""
import json
from pathlib import Path
import subprocess
import sys

import pytest


REQUEST = {"field_goal": "Current detail", "text": "学习样本", "submit_search": False}
EXPECTED = {**REQUEST, "clear_existing": True, "target_memory": None, "target": None}


def test_shared_request_keeps_public_aliases_and_original_serialization():
    from app.core.input_sequence_contract import InputSequenceRequest
    from app.execution.input_sequence import InputSequenceRequest as execution_request
    from app.desktop_review.input_sequence import InputSequenceRequest as compatibility_request
    from app.core.input_sequence_partial import _request

    assert execution_request is InputSequenceRequest
    assert compatibility_request is InputSequenceRequest
    assert InputSequenceRequest.model_validate(REQUEST).model_dump(mode="json") == EXPECTED
    assert _request(REQUEST) == EXPECTED


@pytest.mark.parametrize("change", [
    {"clear_existing": 1}, {"submit_search": "false"}, {"text": ""},
    {"text": "x" * 20001}, {"field_goal": "x" * 2001}, {"unknown": True},
    {"target": {"name": "Submit", "control_type": "Button"}},
    {"target": {"name": "Detail", "control_type": "Edit", "bbox": [0, 0, 10, 10]}},
    {"target_memory": {"recipe_id": "unbound"}},
])
def test_shared_request_retains_existing_rejections(change):
    from app.core.input_sequence_contract import InputSequenceRequest

    with pytest.raises(ValueError):
        InputSequenceRequest.model_validate({**REQUEST, **change})


def test_shared_target_validator_preserves_legacy_entrypoint():
    from app.core.control_target_contract import validate_task_plan_control_target
    from app.execution.task_plan_target import validate_task_plan_control_target as legacy

    assert legacy is validate_task_plan_control_target
    target = {"name": "Detail", "control_type": "Edit",
              "container": {"name": "Record", "control_type": "Window"}}
    result = legacy(target, for_input=True)
    assert result == target
    result["container"]["name"] = "Changed copy"
    assert target["container"]["name"] == "Record"


def test_request_and_partial_proof_validation_do_not_import_executor(tmp_path):
    # 新解释器同时走两个嵌套字段校验，避免已导入模块掩盖反向依赖。
    code = r'''
import importlib.abc
import json
import sys

sys.path.insert(0, sys.argv[1])

class NoExecution(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "app.execution" or fullname.startswith("app.execution."):
            raise AssertionError("unexpected executor import: " + fullname)
        return None

sys.meta_path.insert(0, NoExecution())
from app.core.input_sequence_partial import _request
request = json.loads(sys.argv[2])
result = _request(request)
assert result["target"] == request["target"]
assert result["target_memory"] == request["target_memory"]
assert result["clear_existing"] is True
print(json.dumps(result, ensure_ascii=False))
'''
    request = {**REQUEST, "target": {"name": "Detail", "control_type": "Edit"},
               "target_memory": {"recipe_id": "target-recipe-" + "a" * 64,
                                 "interface_key": "record", "state_key": "detail"}}
    completed = subprocess.run(
        [sys.executable, "-I", "-B", "-X", "utf8", "-c", code,
         str(Path(__file__).resolve().parents[1]), json.dumps(request, ensure_ascii=False)],
        cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", timeout=20)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {**EXPECTED, **request}
