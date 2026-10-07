from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.learning_memory import workflow_runner as module

RUN_ONE = "trial-" + "a" * 64
RUN_TWO = "trial-" + "b" * 64


class FakeWorkspace:
    opened = 0
    states = {}
    prepares = []
    actions = {}

    def __init__(self, root):
        self.root = root

    def __enter__(self):
        type(self).opened += 1
        return self

    def __exit__(self, *_):
        type(self).opened -= 1

    def status_workflow_trial(self, session, run_id):
        return deepcopy(self.states[run_id])

    def load_workflow_program(self, workflow_id, program_id):
        return {"definition": {"steps": [{"step_id": key, "action": {"kind": kind}}
                                         for key, kind in self.actions.items()]}}

    def prepare_workflow_trial(self, session, run_id, request_id, observations=None, vision_capabilities=None):
        state = self.states[run_id]
        step_id = state["current_step_id"]
        self.prepares.append((run_id, request_id, step_id, deepcopy(vision_capabilities)))
        command_id = "exec-" + step_id
        ticket = {"step_id": step_id, "execution_request_id": command_id,
                  "suggested_command": {"kind": "step", "operation": "execute_recognition_plan", "request": {"goal": step_id}}}
        if vision_capabilities is not None:
            ticket["suggested_command"]["vision_capabilities"] = deepcopy(vision_capabilities)
        state["pending"] = deepcopy(ticket)
        state["status"] = "pending"
        return {"run_id": run_id, "status": "pending", **deepcopy(ticket)}

    def cancel_workflow_trial(self, session, run_id, request_id):
        state = self.states[run_id]
        state["status"] = "cancel_requested" if state["pending"] else "cancelled"
        return deepcopy(state)


@pytest.fixture(autouse=True)
def fake_workspace(monkeypatch):
    FakeWorkspace.opened = 0
    FakeWorkspace.prepares = []
    FakeWorkspace.actions = {"one": "click", "two": "click", "three": "click"}
    FakeWorkspace.states = {RUN_ONE: {"run_id": RUN_ONE, "workflow_id": "workflow-1", "program_id": "program-1", "inputs": {}, "outputs": {},
                                      "current_step_id": "one", "status": "ready", "pending": None, "history": []}}
    monkeypatch.setattr(module, "MemoryWorkspace", FakeWorkspace)


def runner(tmp_path, submit, read, verify):
    return module.WorkflowRunner(tmp_path, library_root=tmp_path / "library",
                                 submit_command=submit, read_result=read, verify_step=verify)


def test_until_wait_runs_three_defined_steps_without_per_step_agent_rounds(tmp_path):
    submitted = []
    order = {"one": "two", "two": "three", "three": None}
    def submit(command_id, command):
        assert FakeWorkspace.opened == 0
        submitted.append(command_id)
    def read(command_id):
        assert FakeWorkspace.opened == 0
        return {"status": "completed", "command_id": command_id}
    def verify(run_id, request_id, command_id):
        assert FakeWorkspace.opened == 0
        state = FakeWorkspace.states[run_id]
        step_id = state["current_step_id"]
        state["history"].append({"step_id": step_id, "execution_request_id": command_id, "verdict": "success"})
        state["pending"] = None
        state["current_step_id"] = order[step_id]
        state["status"] = "ready" if order[step_id] else "completed"
        return deepcopy(state)
    control = runner(tmp_path, submit, read, verify)
    final = control.start(RUN_ONE, "start-1", "until_wait")
    assert final["runner_state"] == "completed"
    assert submitted == ["exec-one", "exec-two", "exec-three"]
    assert len(FakeWorkspace.prepares) == 3
    assert control.start(RUN_ONE, "start-1", "until_wait")["runner_state"] == "completed"
    assert control.status(RUN_ONE)["runner_state"] == "completed"
    assert len(submitted) == 3
    metrics = control.status(RUN_ONE)["metrics"]
    assert metrics["observed"]["event_count"] == 0
    assert metrics["coverage"]["planning"] == "unobserved"
    assert metrics["total_model_calls"] is None


def test_single_mode_stops_after_one_step(tmp_path):
    submitted = []
    def verify(run_id, request_id, command_id):
        state = FakeWorkspace.states[run_id]
        state["history"].append({"step_id": "one", "execution_request_id": command_id, "verdict": "success"})
        state.update(pending=None, current_step_id="two", status="ready")
        return deepcopy(state)
    control = runner(tmp_path, lambda command_id, command: submitted.append(command_id),
                     lambda command_id: {"status": "completed", "command_id": command_id}, verify)
    result = control.start(RUN_ONE, "start-1", "single")
    assert result["runner_state"] == "single_complete"
    assert submitted == ["exec-one"]
    assert control.advance(RUN_ONE)["runner_state"] == "single_complete"


def test_pending_and_reopen_reconcile_original_id_without_duplicate_dispatch(tmp_path):
    submitted = []
    results = {"exec-one": {"status": "pending", "command_id": "exec-one"}}
    def submit(command_id, command):
        submitted.append(command_id)
    def verify(run_id, request_id, command_id):
        state = FakeWorkspace.states[run_id]
        state["history"].append({"step_id": "one", "execution_request_id": command_id, "verdict": "uncertain"})
        state.update(pending=None, status="paused_uncertain")
        return deepcopy(state)
    first = runner(tmp_path, submit, lambda command_id: results[command_id], verify)
    waiting = first.start(RUN_ONE, "start-1", "until_wait")
    assert waiting["wait_reason"] == "execution_pending"
    reopened = runner(tmp_path, submit, lambda command_id: results[command_id], verify)
    assert reopened.status(RUN_ONE)["wait_reason"] == "execution_pending"
    assert submitted == ["exec-one"]
    results["exec-one"] = {"status": "completed", "command_id": "exec-one"}
    final = reopened.advance(RUN_ONE)
    assert final["wait_reason"] == "uncertain"
    assert submitted == ["exec-one"]


def test_submit_exception_or_not_found_never_replays_input(tmp_path):
    submitted = []
    def submit(command_id, command):
        submitted.append(command_id)
        raise RuntimeError("response lost after possible input")
    control = runner(tmp_path, submit, lambda command_id: {"status": "not_found", "command_id": command_id},
                     lambda *args: pytest.fail("must not verify unknown input"))
    waiting = control.start(RUN_ONE, "start-1", "until_wait")
    assert waiting["wait_reason"] == "result_unknown"
    assert control.advance(RUN_ONE)["wait_reason"] == "result_unknown"
    assert submitted == ["exec-one"]


def test_cancel_pending_keeps_original_execution_for_reconciliation(tmp_path):
    submitted = []
    control = runner(tmp_path, lambda command_id, command: submitted.append(command_id),
                     lambda command_id: {"status": "awaiting_grounding", "command_id": command_id,
                                         "raw": {"pending_grounding": {"request_id": "ground-1"}}},
                     lambda *args: pytest.fail("pending input cannot be verified"))
    waiting = control.start(RUN_ONE, "start-1", "until_wait")
    assert waiting["wait_reason"] == "grounding_required"
    assert waiting["wait"]["command_id"] == "exec-one"
    assert waiting["wait"]["pending_grounding"] == {"request_id": "ground-1"}
    cancelled = control.cancel(RUN_ONE, "cancel-1")
    assert cancelled["runner_state"] == "cancel_requested"
    assert cancelled["pending"]["execution_request_id"] == "exec-one"
    assert submitted == ["exec-one"]
    with pytest.raises(ValueError, match="wait_id"):
        control.resume(RUN_ONE, "resume-1", "wrong")


def test_dispatch_record_must_be_durable_before_submit(tmp_path, monkeypatch):
    submitted = []
    original = module._atomic_write_bytes
    def fail_dispatch(path, data):
        if b'"runner_state":"dispatching"' in data:
            raise OSError("disk full")
        return original(path, data)
    monkeypatch.setattr(module, "_atomic_write_bytes", fail_dispatch)
    control = runner(tmp_path, lambda command_id, command: submitted.append(command_id),
                     lambda command_id: pytest.fail("must not read"), lambda *args: pytest.fail("must not verify"))
    with pytest.raises(OSError, match="disk full"):
        control.start(RUN_ONE, "start-1", "until_wait")
    assert submitted == []
    assert control.status(RUN_ONE)["runner_state"] == "ready"


def test_late_result_and_resume_reconcile_without_replay(tmp_path):
    submitted = []
    result = {"status": "pending", "command_id": "exec-one"}
    verified = []
    def verify(run_id, request_id, command_id):
        verified.append(command_id)
        state = FakeWorkspace.states[run_id]
        state["history"].append({"step_id": "one", "execution_request_id": command_id, "verdict": "uncertain"})
        state.update(pending=None, status="paused_uncertain")
        return deepcopy(state)
    control = runner(tmp_path, lambda command_id, command: submitted.append(command_id),
                     lambda command_id: result.copy(), verify)
    waiting = control.start(RUN_ONE, "start-1", "until_wait")
    assert waiting["wait_reason"] == "execution_pending"
    result.update(status="completed")
    resumed = control.resume(RUN_ONE, "resume-1", waiting["wait"]["wait_id"])
    assert resumed["wait_reason"] == "uncertain"
    assert submitted == ["exec-one"]
    assert verified == ["exec-one"]
    with pytest.raises(ValueError, match="wait_id"):
        control.resume(RUN_ONE, "resume-2", waiting["wait"]["wait_id"])
    assert control.advance(RUN_ONE)["wait_reason"] == "uncertain"
    assert verified == ["exec-one"]


def test_active_run_and_terminal_cancel_do_not_change_trial(tmp_path):
    result = {"status": "pending", "command_id": "exec-one"}
    def verify(run_id, request_id, command_id):
        state = FakeWorkspace.states[run_id]
        state["history"].append({"step_id": "one", "execution_request_id": command_id, "verdict": "success"})
        state.update(pending=None, current_step_id=None, status="completed")
        return deepcopy(state)
    control = runner(tmp_path, lambda command_id, command: None,
                     lambda command_id: result.copy(), verify)
    control.start(RUN_ONE, "start-1", "until_wait")
    FakeWorkspace.states[RUN_TWO] = deepcopy(FakeWorkspace.states[RUN_ONE])
    with pytest.raises(ValueError, match="session_active"):
        control.start(RUN_TWO, "start-2", "single")
    result["status"] = "completed"
    control.advance(RUN_ONE)
    assert control.cancel(RUN_ONE, "cancel-after-complete")["runner_state"] == "completed"
    assert FakeWorkspace.states[RUN_ONE]["status"] == "completed"


def test_unresolved_non_execution_wait_cannot_be_cleared_by_resume(tmp_path):
    control = runner(tmp_path, lambda *args: None,
                     lambda command_id: {"status": "completed", "command_id": command_id},
                     lambda run_id, request_id, command_id: _uncertain_trial(run_id, command_id))
    waiting = control.start(RUN_ONE, "start-1", "until_wait")
    assert waiting["wait_reason"] == "uncertain"
    resumed = control.resume(RUN_ONE, "resume-1", waiting["wait"]["wait_id"])
    assert resumed["wait_reason"] == "uncertain"


def test_runs_have_separate_durable_files_and_prior_idempotency(tmp_path):
    def verify(run_id, request_id, command_id):
        state = FakeWorkspace.states[run_id]
        state["history"].append({"step_id": "one", "execution_request_id": command_id, "verdict": "success"})
        state.update(pending=None, current_step_id=None, status="completed")
        return deepcopy(state)
    control = runner(tmp_path, lambda *args: None,
                     lambda command_id: {"status": "completed", "command_id": command_id}, verify)
    control.start(RUN_ONE, "start-1", "until_wait")
    FakeWorkspace.states[RUN_TWO] = {**deepcopy(FakeWorkspace.states[RUN_ONE]), "run_id": RUN_TWO,
                                     "current_step_id": "one", "status": "ready", "history": []}
    control.start(RUN_TWO, "start-2", "until_wait")
    assert (tmp_path / "workflow-runners" / (RUN_ONE + ".json")).exists()
    assert (tmp_path / "workflow-runners" / (RUN_TWO + ".json")).exists()
    assert (tmp_path / "workflow-runners" / "active.json").exists()
    assert control.status(RUN_ONE)["runner_state"] == "completed"
    assert control.start(RUN_ONE, "start-1", "until_wait")["runner_state"] == "completed"
    assert control.status(RUN_TWO)["runner_state"] == "completed"
    assert json.loads((tmp_path / "workflow-runners" / "active.json").read_text(encoding="utf-8"))["run_id"] == RUN_TWO
    with pytest.raises(ValueError, match="run_id"):
        control.status("../outside")


def test_single_step_requires_exact_resume_and_resumes_once(tmp_path):
    sent = []
    def verify(run_id, request_id, command_id):
        state = FakeWorkspace.states[run_id]
        step = state["current_step_id"]
        state["history"].append({"step_id": step, "execution_request_id": command_id, "verdict": "success"})
        state.update(pending=None, current_step_id="two" if step == "one" else None,
                     status="ready" if step == "one" else "completed")
        return deepcopy(state)
    control = runner(tmp_path, lambda command_id, command: sent.append(command_id),
                     lambda command_id: {"status": "completed", "command_id": command_id}, verify)
    first = control.start(RUN_ONE, "start-1", "single")
    assert first["wait_reason"] == "single_step_complete"
    assert control.advance(RUN_ONE)["wait"]["wait_id"] == first["wait"]["wait_id"]
    assert sent == ["exec-one"]
    with pytest.raises(ValueError, match="wait_id"):
        control.resume(RUN_ONE, "resume-wrong", "wrong")
    second = control.resume(RUN_ONE, "resume-1", first["wait"]["wait_id"])
    assert second["runner_state"] == "completed"
    assert sent == ["exec-one", "exec-two"]
    assert control.resume(RUN_ONE, "resume-1", first["wait"]["wait_id"])["runner_state"] == "completed"
    assert sent == ["exec-one", "exec-two"]


def test_single_pause_cancel_is_terminal_without_more_input(tmp_path):
    sent = []
    def verify(run_id, request_id, command_id):
        state = FakeWorkspace.states[run_id]
        state["history"].append({"step_id": "one", "execution_request_id": command_id, "verdict": "success"})
        state.update(pending=None, current_step_id="two", status="ready")
        return deepcopy(state)
    control = runner(tmp_path, lambda command_id, command: sent.append(command_id),
                     lambda command_id: {"status": "completed", "command_id": command_id}, verify)
    paused = control.start(RUN_ONE, "start-1", "single")
    assert paused["runner_state"] == "single_complete"
    assert control.cancel(RUN_ONE, "cancel-1")["runner_state"] == "cancelled"
    assert control.advance(RUN_ONE)["runner_state"] == "cancelled"
    assert sent == ["exec-one"]


def test_callback_error_has_actionable_type_without_command_payload(tmp_path):
    def fail_submit(command_id, command):
        raise TimeoutError("queue timeout")
    control = runner(tmp_path, fail_submit,
                     lambda command_id: {"status": "not_found", "command_id": command_id},
                     lambda *args: pytest.fail("must not verify"))
    result = control.start(RUN_ONE, "start-1", "until_wait")
    assert result["wait"]["error"] == {"error_type": "TimeoutError", "message": "queue timeout"}
    assert "suggested_command" not in str(result["wait"])


@pytest.mark.parametrize("input_kind", ["click", "input_sequence"])
def test_capabilities_are_pinned_for_input_steps_but_not_read_text(tmp_path, input_kind):
    FakeWorkspace.actions = {"one": input_kind, "two": "read_text"}
    sent = []
    def verify(run_id, request_id, command_id):
        state = FakeWorkspace.states[run_id]
        step = state["current_step_id"]
        state["history"].append({"step_id": step, "execution_request_id": command_id, "verdict": "success"})
        state.update(pending=None, current_step_id="two" if step == "one" else None,
                     status="ready" if step == "one" else "completed")
        return deepcopy(state)
    control = runner(tmp_path, lambda command_id, command: sent.append(command),
                     lambda command_id: {"status": "completed", "command_id": command_id}, verify)
    caps = {"image_transport": "supported", "current_vision": "supported"}
    assert control.start(RUN_ONE, "start-1", "until_wait", vision_capabilities=caps)["runner_state"] == "completed"
    assert FakeWorkspace.prepares[0][3]["image_transport"] == "supported"
    assert FakeWorkspace.prepares[1][3] is None
    assert "vision_capabilities" in sent[0]
    assert "vision_capabilities" not in sent[1]
    assert control.start(RUN_ONE, "start-1", "until_wait", vision_capabilities=caps)["runner_state"] == "completed"
    with pytest.raises(ValueError, match="start_conflict"):
        control.start(RUN_ONE, "start-1", "until_wait", vision_capabilities={"image_transport": "unsupported"})
    with pytest.raises(Exception):
        control.start(RUN_ONE, "other", "until_wait", vision_capabilities={"bogus": "supported"})


def test_external_review_reconciles_without_second_verification_or_input(tmp_path):
    sent = []
    control = runner(tmp_path, lambda command_id, command: sent.append(command_id),
                     lambda command_id: {"status": "pending", "command_id": command_id},
                     lambda *args: pytest.fail("manual review must not be repeated"))
    control.start(RUN_ONE, "start-1", "until_wait")
    state = FakeWorkspace.states[RUN_ONE]
    state["history"].append({"step_id": "one", "execution_request_id": "exec-one", "verdict": "success"})
    state.update(pending=None, current_step_id=None, status="completed")
    assert control.advance(RUN_ONE)["runner_state"] == "completed"
    assert sent == ["exec-one"]


def test_cancelled_result_uses_verifier_to_close_original_ticket(tmp_path):
    submitted = []
    result = {"status": "pending", "command_id": "exec-one"}
    def verify(run_id, request_id, command_id):
        state = FakeWorkspace.states[run_id]
        state["history"].append({"step_id": "one", "execution_request_id": command_id,
                                 "verdict": "uncertain", "judged_by": "runtime"})
        state.update(pending=None, status="cancelled")
        return deepcopy(state)
    control = runner(tmp_path, lambda command_id, command: submitted.append(command_id),
                     lambda command_id: result.copy(), verify)
    control.start(RUN_ONE, "start-1", "until_wait")
    assert control.cancel(RUN_ONE, "cancel-1")["runner_state"] == "cancel_requested"
    result["status"] = "cancelled"
    assert control.advance(RUN_ONE)["runner_state"] == "cancelled"
    assert control.status(RUN_ONE)["pending"] is None
    assert submitted == ["exec-one"]
    FakeWorkspace.states[RUN_TWO] = {**deepcopy(FakeWorkspace.states[RUN_ONE]), "run_id": RUN_TWO,
                                     "current_step_id": "two", "status": "ready", "history": []}
    result.update(status="pending", command_id="exec-two")
    assert control.start(RUN_TWO, "start-2", "until_wait")["wait_reason"] == "execution_pending"
    assert submitted == ["exec-one", "exec-two"]


def _uncertain_trial(run_id, command_id):
    state = FakeWorkspace.states[run_id]
    state["history"].append({"step_id": "one", "execution_request_id": command_id, "verdict": "uncertain"})
    state.update(pending=None, status="paused_uncertain")
    return deepcopy(state)
