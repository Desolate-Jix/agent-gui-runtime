"""审核摘要保留步骤语义、隐藏输入值，并在输入入队前验证完整边界。"""
from copy import deepcopy
from hashlib import sha256
import json
from types import SimpleNamespace

import httpx
from PIL import Image
import pytest

from app.execution.task_plan_admission import TaskPlanRuntime
from app.execution.task_plan_backend import TaskPlanBackend
from app.execution.task_plan_contract import validate_task_plan
from app.execution.task_plan_review import review_context
from app.judgment import DecisionProfile, DecisionService, OpenAIDecisionsProvider
from app.learning_memory.workflow_runtime import WorkflowRuntime


SOURCE_ID = "task-plan-" + "a" * 64
SOURCE_HASH = "b" * 64
FIELD_GOAL = "定位工具栏下方的目录地址输入框"
TARGET = {"handle": 11, "process_id": 22, "process_create_time": 33.0}


def step(step_id, name):
    return {"step_id": step_id, "action": {"kind": "input_sequence", "field_goal": FIELD_GOAL,
        "text": {"source": "input", "name": name}, "clear_existing": True, "submit_search": True},
        "verification": {"kind": "agent_judgment", "decision_condition": "目录内容可见"}}


def plan(count=2):
    return {"schema_version": "task_plan.v2", "title": "打开报告目录后返回收件目录",
        "inputs": {"reports_dir": "RESOLVED-REPORTS-SECRET", "inbox_dir": "RESOLVED-INBOX-SECRET"},
        "steps": [step("open_reports", "reports_dir"), step("return_inbox", "inbox_dir")][:count]}


def context(value, index=0):
    return review_context(value, value["steps"][index], source_id=SOURCE_ID, source_sha256=SOURCE_HASH)


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def test_same_field_goal_retains_distinct_step_and_input_intents_without_reading_inputs(monkeypatch):
    value = plan()
    value["steps"][0]["action"]["target"] = {"name": "TARGET-SECRET"}
    value["steps"][0]["action"]["unknown"] = "UNKNOWN-SECRET"
    class UnreadableInputs(dict):
        def __getitem__(self, key):
            pytest.fail("review projection must not resolve inputs")
        def get(self, *args):
            pytest.fail("review projection must not read inputs")
        def items(self):
            pytest.fail("review projection must not enumerate inputs")
    value["inputs"] = UnreadableInputs()
    monkeypatch.setattr("app.execution.task_plan_contract.resolve_action_text",
        lambda *args: pytest.fail("review projection must not resolve action text"))
    result = context(value)
    current, remaining = json.loads(result["step_goal"]), json.loads(result["remaining_plan"][0])
    assert current == {"step_id": "open_reports", "action": {"kind": "input_sequence", "field_goal": FIELD_GOAL,
        "text": {"source": "input", "name": "reports_dir"}, "clear_existing": True, "submit_search": True},
        "verification": {"kind": "agent_judgment", "decision_condition": "目录内容可见"}}
    assert remaining["step_id"] == "return_inbox"
    assert remaining["action"]["text"] == {"source": "input", "name": "inbox_dir"}
    assert current["action"]["field_goal"] == remaining["action"]["field_goal"]
    assert result["step_goal"] == encoded(current)
    assert FIELD_GOAL in result["step_goal"] and "\\u5b9a" not in result["step_goal"]
    assert "SECRET" not in encoded(result) and "unknown" not in current["action"]


@pytest.mark.parametrize("kind", ["click", "read_text"])
def test_other_actions_and_native_condition_have_only_declared_semantics(kind):
    value = plan(1)
    value["steps"][0]["action"] = {"kind": kind, "goal": "打开报告"}
    value["steps"][0]["verification"] = ({"kind": "native_condition",
        "condition": {"text": "报告", "control_type": "Text"}} if kind == "click" else {"kind": "agent_judgment"})
    assert validate_task_plan(value) == value
    summary = json.loads(context(value)["step_goal"])
    expected_action = {"kind": kind, "goal": "打开报告"}
    if kind == "click":
        expected_action["click_kind"] = "single"
    assert summary["action"] == expected_action
    assert summary["verification"] == value["steps"][0]["verification"]
    if kind == "click":
        value["steps"][0]["action"]["click_kind"] = "double"
        assert json.loads(context(value)["step_goal"])["action"]["click_kind"] == "double"


def test_context_is_deterministic_and_isolated_from_caller_mutation():
    value = plan()
    value["steps"][0]["verification"]["allowed_states"] = ["报告目录"]
    original = context(value)
    assert context(deepcopy(value)) == original
    saved = deepcopy(original)
    value["steps"][0]["action"]["field_goal"] = "changed"
    value["steps"][1]["action"]["text"]["name"] = "changed"
    value["steps"][0]["verification"]["allowed_states"].append("changed")
    assert original == saved


def oversized(position):
    value = plan(1 if position == "current" else 2)
    index = 0 if position == "current" else 1
    value["steps"][index]["verification"]["decision_condition"] = "x" * (4000 if index == 0 else 2000)
    return value


@pytest.mark.parametrize("position,limit", [("current", 4000), ("remaining", 2000)])
def test_summary_limits_are_exact_and_never_truncate(position, limit):
    value = plan(1 if position == "current" else 2)
    index = 0 if position == "current" else 1
    result = context(value)
    initial = result["step_goal"] if index == 0 else result["remaining_plan"][0]
    value["steps"][index]["verification"]["decision_condition"] += "界" * (limit - len(initial))
    assert validate_task_plan(value) == value
    result = context(value)
    summary = result["step_goal"] if index == 0 else result["remaining_plan"][0]
    assert len(summary) == limit
    assert json.loads(summary)["verification"]["decision_condition"] == value["steps"][index]["verification"]["decision_condition"]
    value["steps"][index]["verification"]["decision_condition"] += "x"
    with pytest.raises(ValueError, match="decision_review_context_(text|list)_invalid"):
        validate_task_plan(value)


def byte_boundary_plan():
    value = plan(1)
    states = value["steps"][0]["verification"]["allowed_states"] = ["a"] * 32
    remaining = 65536 - len(encoded(context(value)).encode("utf-8"))
    for index in range(len(states)):
        delta = min(2997, remaining)
        count, rest = divmod(delta + 1, 3)
        states[index] = "界" * count + "a" * rest
        remaining -= delta
        if remaining == 0:
            break
    assert remaining == 0
    return value


def test_full_byte_limit_includes_real_source_id_overhead_before_admission():
    value = byte_boundary_plan()
    assert len(encoded(context(value)).encode("utf-8")) == 65536
    assert validate_task_plan(value) == value
    states = value["steps"][0]["verification"]["allowed_states"]
    index = next(i for i, item in enumerate(states) if len(item) < 1000)
    states[index] += "x"
    with pytest.raises(ValueError, match="decision_review_context_too_large"):
        validate_task_plan(value)


@pytest.mark.parametrize("entry", ["admission", "backend"])
@pytest.mark.parametrize("position", ["current", "remaining", "total_bytes"])
def test_oversized_context_fails_before_any_command_is_admitted(tmp_path, monkeypatch, entry, position):
    value = oversized(position) if position != "total_bytes" else byte_boundary_plan()
    if position == "total_bytes":
        states = value["steps"][0]["verification"]["allowed_states"]
        index = next(i for i, item in enumerate(states) if len(item) < 1000)
        states[index] += "x"
    (tmp_path / "commands").mkdir()
    admitted = []
    if entry == "admission":
        coordinator = SimpleNamespace(_memory_library_root=tmp_path / "absent", _decision_service=None)
        reviewed = WorkflowRuntime(tmp_path, coordinator)
        monkeypatch.setattr(reviewed, "_admit_input", lambda *args: admitted.append(args))
        runtime = TaskPlanRuntime(tmp_path, coordinator, owner_id="owner", target_identity=lambda: deepcopy(TARGET),
            reviewed_runtime=reviewed)
        invoke = lambda: runtime.control({"action": "start", "plan": value}, "start-invalid")
    else:
        backend = TaskPlanBackend(tmp_path, owner_id="owner")
        invoke = lambda: backend.start(value, TARGET, "start-invalid")
    with pytest.raises(ValueError, match="decision_review_context_"):
        invoke()
    assert admitted == [] and list((tmp_path / "commands").glob("*.json")) == []
    assert not (tmp_path / "task-plans").exists()


@pytest.mark.parametrize("action,error", [("bad", "task_plan_action_invalid"),
    ({"goal": "missing kind"}, "task_plan_action_unsupported")])
def test_malformed_successor_reports_contract_error_before_context_projection(action, error):
    value = plan()
    value["steps"][1]["action"] = action
    with pytest.raises(ValueError, match=error):
        validate_task_plan(value)


def test_v1_original_strings_and_validation_do_not_use_v2_normalizer(monkeypatch):
    value = plan()
    value["schema_version"] = "task_plan.v1"
    value["steps"][1]["action"]["field_goal"] = "界" * 2000
    monkeypatch.setattr("app.judgment.adaptive_policy.normalize_review_context",
        lambda *args: pytest.fail("v1 must not adopt v2 context constraints"))
    assert validate_task_plan(value) == value
    assert context(value) == {"goal": value["title"], "step_goal": FIELD_GOAL,
        "remaining_plan": [("input_sequence: " + "界" * 2000)[:2000]], "allowed_states": [],
        "source_id": SOURCE_ID, "source_sha256": SOURCE_HASH}


@pytest.mark.parametrize("terminal", [False, True])
def test_provider_omits_plan_history_but_authenticates_local_v2_context(tmp_path, monkeypatch, terminal):
    value = plan()
    value["steps"].extend([step("literal", "reports_dir"), step("constant", "reports_dir")])
    value["steps"][2]["action"]["text"] = "LITERAL-SECRET"
    value["steps"][3]["action"]["text"] = {"source": "constant", "value": "CONSTANT-SECRET"}
    assert validate_task_plan(value) == value
    ctx = context(value, 3 if terminal else 0)
    condition = "目录内容可见"
    image = tmp_path / "current.png"
    Image.new("RGB", (12, 8), "white").save(image)
    binding = {"request_id": "review-1", "execution_request_id": "execute-1", "condition": condition,
        "frames": [{"capture_id": "current", "image_path": str(image), "sha256": sha256(image.read_bytes()).hexdigest(),
                    "window_identity": TARGET, "role": "after"}], "review_context": ctx}
    expected = deepcopy(binding)
    captured = []
    monkeypatch.setenv("REVIEW_CONTEXT_TEST_KEY", "synthetic-test-key")
    def handle(request):
        captured.append(json.loads(request.content))
        ctx["remaining_plan"].append("caller mutation")
        return httpx.Response(200, json={"model": "gpt-6-luna", "answers": [
            {"type": "predicate", "name": "condition_met", "probability": 1.0},
            {"type": "predicate", "name": "visible_error", "probability": 0.0},
            {"type": "predicate", "name": "needs_agent_review", "probability": 0.23}],
            "usage": {"input_tokens": 12, "output_tokens": 0, "total_tokens": 12}})
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        provider = OpenAIDecisionsProvider(api_key_env="REVIEW_CONTEXT_TEST_KEY", client=client)
        service = DecisionService(tmp_path, profile=DecisionProfile.model_validate({"contract_version": "decision_profile.v2",
            "mode": "auto", "api_key_env": "REVIEW_CONTEXT_TEST_KEY", "auto_conditions": [condition]}), provider=provider)
        result = service.evaluate(**binding)
        assert service.validate_result(result, **expected) is True
        assert result["review_context"] == expected["review_context"]
        assert result["verdict"] == "success" and result["disposition"] == "review_required"
        assert result["predicates"]["needs_agent_review"]["probability"] == 0.23
        changed = deepcopy(expected)
        changed["review_context"]["step_goal"] += "changed"
        assert service.validate_result(result, **changed) is False
    assert len(captured) == 1
    body = captured[0]
    assert "SECRET" not in encoded(body)
    assert [q["name"] for q in body["questions"]] == ["condition_met", "visible_error", "needs_agent_review"]
    review_question = body["questions"][2]["instructions"]
    assert "Assess only this current result" in review_question
    assert "do not reconsider earlier workflow steps" in review_question
    assert "remaining plan" not in review_question
    assert not any(part.get("text", "").startswith("Frozen scoped task")
        for part in body["input"][0]["content"])
    assert condition in body["questions"][0]["instructions"]
    # 计划仍完整绑定在本地回执，远端结果判断不再重复审核它。
    sent_context = result["review_context"]
    if terminal:
        assert sent_context["remaining_plan"] == []
        assert json.loads(sent_context["step_goal"])["action"]["text"] == {"source": "constant", "redacted": True}
    else:
        assert json.loads(sent_context["step_goal"])["action"]["text"] == {"source": "input", "name": "reports_dir"}
        suffix = [json.loads(item) for item in sent_context["remaining_plan"]]
        assert suffix[0]["action"]["text"] == {"source": "input", "name": "inbox_dir"}
        assert suffix[1]["action"]["text"] == {"source": "literal", "redacted": True}
        assert suffix[2]["action"]["text"] == {"source": "constant", "redacted": True}
