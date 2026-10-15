"""线性执行计划按内容预算约束，不把固定步骤数当作执行上限。"""
from copy import deepcopy

import pytest

from app.execution.task_plan_contract import validate_task_plan
from app.judgment.adaptive_policy import normalize_review_context
from app.learning_memory.workflow_runner import WorkflowRunner
from tests.test_task_plan_runner import complete_original, scene


def linear_plan(count, version="task_plan.v1"):
    verification = {"kind": "agent_judgment", "decision_condition": "Panel visible"}
    value = {"schema_version": version, "title": "Continue task", "inputs": {},
        "steps": [{"step_id": f"s{i}", "action": {"kind": "click", "goal": "Open panel"},
            "verification": deepcopy(verification)} for i in range(count)]}
    if version == "task_plan.v3":
        value.update(goal="Reach final panel", completion={"step_id": value["steps"][-1]["step_id"],
            "verification": deepcopy(verification)})
    return value


@pytest.mark.parametrize("version", ["task_plan.v1", "task_plan.v2", "task_plan.v3"])
@pytest.mark.parametrize("count", [9, 258])
def test_plan_accepts_steps_beyond_old_count_limits(version, count):
    value = linear_plan(count, version)
    frozen = validate_task_plan(value)
    assert frozen == value and frozen is not value


def test_remaining_plan_has_byte_budget_without_item_count_limit():
    context = {"goal": "Continue task", "step_goal": "Open panel", "remaining_plan": ["Open panel"] * 258,
        "allowed_states": []}
    frozen = normalize_review_context(context)
    assert len(frozen["remaining_plan"]) == 258
    context["remaining_plan"].clear()
    assert len(frozen["remaining_plan"]) == 258
    with pytest.raises(ValueError, match="context_too_large"):
        normalize_review_context({**frozen, "remaining_plan": ["x" * 2000] * 40})
    with pytest.raises(ValueError, match="context_list_invalid"):
        normalize_review_context({**frozen, "allowed_states": ["panel"] * 33})


def test_twelve_step_plan_uses_original_queue_and_receipts(tmp_path, monkeypatch):
    from tests.test_task_plan_contract import plan
    source = plan(count=12)
    source["schema_version"] = "task_plan.v2"
    state = scene(tmp_path, monkeypatch, source=source)
    command_ids = []
    for index in range(12):
        original = complete_original(state)
        assert original.pending["step_id"] == f"step-{index}"
        command_ids.append(original.command_id)
        snapshot = state.runtime.tick(force=True)
    assert snapshot["runner_state"] == "completed"
    assert [row["execution_request_id"] for row in snapshot["history"]] == command_ids
    assert all(row["judged_by"] == "native_condition" for row in snapshot["history"])
    assert len(list(tmp_path.glob("commands/*.json"))) == 12
    assert state.runtime.tick(force=True) is None


def test_long_plan_still_stops_at_failed_step(tmp_path, monkeypatch):
    from tests.test_task_plan_contract import plan
    state = scene(tmp_path, monkeypatch, source=plan(count=12))
    for _ in range(8):
        complete_original(state)
        state.runtime.tick(force=True)
    complete_original(state, status="failure")
    snapshot = state.runtime.tick(force=True)
    assert snapshot["runner_state"] == "failed"
    assert len(snapshot["history"]) == 9
    assert len(list(tmp_path.glob("commands/*.json"))) == 9


def test_status_reads_fresh_source_without_revalidating_unchanged_plan(tmp_path, monkeypatch):
    from app.execution import task_plan_backend as module
    from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
    from tests.test_task_plan_contract import plan
    calls, reads = [], []
    original_validate, original_read = module.validate_task_plan, module._read

    def validate(value):
        calls.append(None)
        return original_validate(value)

    def read(path):
        if path.name.startswith("task-plan-"):
            reads.append(path)
        return original_read(path)

    monkeypatch.setattr(module, "validate_task_plan", validate)
    monkeypatch.setattr(module, "_read", read)
    value = plan(count=20)
    value["schema_version"] = "task_plan.v2"
    state = scene(tmp_path, monkeypatch, source=value)
    complete_original(state)
    state.runtime.tick(force=True)
    calls.clear()
    reads.clear()
    snapshot = state.runtime.backend.status(state.run_id)
    assert calls == [] and len(reads) == 1
    path = state.runtime.backend._source_path(snapshot["plan_id"])
    original = read_json_snapshot(path)
    changed = deepcopy(original)
    changed["plan"]["steps"][-1]["action"]["goal"] = "Tampered goal"
    write_json_snapshot(path, changed)
    with pytest.raises(ValueError, match="source_binding_mismatch"):
        state.runtime.backend.status(state.run_id)
    assert len(calls) == 1
    write_json_snapshot(path, original)
    state.runtime.backend.status(state.run_id)
    calls.clear()
    changed = deepcopy(original)
    changed["target_identity"]["process_create_time"] += 1
    write_json_snapshot(path, changed)
    with pytest.raises(ValueError, match="source_binding_mismatch"):
        state.runtime.backend.status(state.run_id)
    assert calls == []
    changed = deepcopy(original)
    changed["plan"]["steps"] = []
    write_json_snapshot(path, changed)
    with pytest.raises(ValueError, match="steps_invalid"):
        state.runtime.backend.status(state.run_id)


class SequentialBackend:
    def __init__(self, source_kind):
        self.source_kind = source_kind
        self.run_id = "trial-" + "a" * 64
        self.value = {"run_id": self.run_id, "source_kind": source_kind, "status": "ready", "pending": None,
            "current_step_id": "s0", "history": [], "inputs": {}, "outputs": {}}

    def status(self, run_id):
        assert run_id == self.run_id
        return deepcopy(self.value)

    def prepare(self, run_id, request_id, **kwargs):
        step_id = self.value["current_step_id"]
        ticket = {"step_id": step_id, "execution_request_id": "exec-" + step_id,
            "suggested_command": {"kind": "step", "request": {"goal": step_id}}}
        self.value.update(status="pending", pending=deepcopy(ticket))
        return {"status": "pending", **ticket}

    def cancel(self, run_id, request_id):
        self.value["status"] = "cancelled"
        return self.status(run_id)

    def pinned_step(self, run_id, step_id):
        return {"step_id": step_id, "action": {"kind": "click", "goal": step_id}}

    def metrics(self, run_id, trial):
        return {}

    def validate_resume(self, run_id, state, **kwargs):
        assert run_id == self.run_id


@pytest.mark.parametrize("source_kind", ["caller_plan", "reviewed_program"])
def test_runner_yields_long_caller_plan_without_weakening_learning_limit(tmp_path, source_kind):
    backend = SequentialBackend(source_kind)
    submitted = []

    def verify(run_id, request_id, command_id):
        row = {"step_id": backend.value["current_step_id"], "execution_request_id": command_id, "verdict": "success"}
        backend.value["history"].append(row)
        index = len(backend.value["history"])
        backend.value.update(pending=None, status="completed" if index == 260 else "ready",
            current_step_id=None if index == 260 else f"s{index}")
        return backend.status(run_id)

    runner = WorkflowRunner(tmp_path, backend=backend,
        submit_command=lambda command_id, command: submitted.append(command_id),
        read_result=lambda command_id: {"status": "completed", "command_id": command_id}, verify_step=verify)
    first = runner.start(backend.run_id, "start-long-plan", "until_wait")
    if source_kind == "reviewed_program":
        assert len(submitted) == 256 and first["wait_reason"] == "failed"
        return
    assert first["runner_state"] == "ready" and len(submitted) == 257
    final = runner.advance(backend.run_id)
    assert final["runner_state"] == "completed"
    assert submitted == [f"exec-s{i}" for i in range(260)]
    assert len(final["history"]) == 260
    assert runner.status(backend.run_id)["runner_state"] == "completed"
