"""结算后的原账本拒绝所有控制写入，不依赖面板按钮。"""
from copy import deepcopy

import psutil
import pytest

from app.core.json_snapshot import write_json_snapshot
from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_trial import services
from tests.test_workflow_terminal_recovery import terminal, service


@pytest.fixture
def settled_scene(runtime_scene, monkeypatch):
    runtime, trials, run, session, _ = runtime_scene
    runtime.control({"action": "run", "run_id": run["run_id"], "mode": "until_wait"}, "run-original")
    ticket = trials.status(run["run_id"])["pending"]
    host = {"pid": 900001, "created": 123.0}
    write_json_snapshot(session.parent / "latest-session.json", {"name": session.name, "host_identity": host})
    write_json_snapshot(session / "report.json", {"runner_pid": host["pid"]})
    scene = runtime, trials, run, session, ticket, host, host["pid"]
    terminal(scene)

    def absent(pid):
        raise psutil.NoSuchProcess(pid)

    monkeypatch.setattr(psutil, "Process", absent)
    recovery = service(scene)
    preview = recovery.preview(run["run_id"])
    recovery.settle(preview, "settle-original")
    return scene, recovery, preview


@pytest.mark.parametrize("operation", ["trial_cancel", "runner_cancel", "runner_resume", "original_admit"])
def test_settled_original_controls_reject_before_any_persistent_change(settled_scene, operation):
    scene, recovery, preview = settled_scene
    runtime, trials, run, session, ticket, _, _ = scene
    before = {str(p.relative_to(session)): p.read_bytes() for p in session.rglob("*.json")}
    state = deepcopy(trials.status(run["run_id"]))
    wait_id = runtime.runner.status(run["run_id"])["wait"]["wait_id"]
    with pytest.raises(ValueError, match="recovery_paused"):
        if operation == "trial_cancel":
            trials.cancel(run["run_id"], "cancel-after-settle")
        elif operation == "runner_cancel":
            runtime.runner.cancel(run["run_id"], "cancel-after-settle")
        elif operation == "runner_resume":
            runtime.runner.resume(run["run_id"], "resume-after-settle", wait_id)
        else:
            runtime.admit(ticket["execution_request_id"], ticket["suggested_command"])
    assert trials.status(run["run_id"]) == state
    assert {str(p.relative_to(session)): p.read_bytes() for p in session.rglob("*.json")} == before
    assert recovery.preview(run["run_id"]) == preview
    assert recovery.settle(preview, "settle-original") == state
    assert runtime.runner.status(run["run_id"])["wait_reason"] == "recovery_paused"


@pytest.mark.parametrize("entry", ["control", "callback"])
def test_settled_verify_rejects_before_observation_capture_metrics_or_dispatch(settled_scene, monkeypatch, entry):
    scene, _, _ = settled_scene
    runtime, trials, run, session, ticket, _, _ = scene
    before = {str(p.relative_to(session)): p.read_bytes() for p in session.rglob("*") if p.is_file()}
    state = deepcopy(trials.status(run["run_id"]))
    calls = []

    def forbidden(name):
        def called(*args, **kwargs):
            calls.append(name)
            raise AssertionError("settled verification reached " + name)
        return called

    monkeypatch.setattr("app.learning_memory.runtime_verification.verify_trial_step", forbidden("verification"))
    monkeypatch.setattr("app.learning_memory.verification_observation.read_step_observation", forbidden("observation"))
    monkeypatch.setattr("app.learning_memory.memory_observation.capture_memory_observation", forbidden("capture"))
    monkeypatch.setattr("app.learning_memory.runtime_verification.record_rule_observation", forbidden("metrics"))
    monkeypatch.setattr(runtime, "_enqueue", forbidden("dispatch"))
    with pytest.raises(ValueError, match="workflow_runtime_recovery_paused"):
        if entry == "control":
            runtime.control({"action": "verify", "run_id": run["run_id"],
                             "execution_request_id": ticket["execution_request_id"]}, "verify-after-settle")
        else:
            runtime._verify(run["run_id"], "verify-after-settle", ticket["execution_request_id"])
    assert calls == []
    assert trials.status(run["run_id"]) == state
    assert {str(p.relative_to(session)): p.read_bytes() for p in session.rglob("*") if p.is_file()} == before
