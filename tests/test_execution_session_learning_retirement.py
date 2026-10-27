"""执行宿主消费真实命令队列；模型、窗口和输入边界均为合成实现。"""
from copy import deepcopy
import sys
from types import SimpleNamespace

import pytest

from app.core import decision_configuration, process_sampler
from app.core.json_snapshot import read_json_snapshot
from app.desktop_review import host, single_step_coordinator
from app.execution import task_plan_admission
from app.learning_memory import workflow_runtime, workflow_target_bindings
from app.vision import agent_command_jobs
from scripts import run_local_step_session as runner


@pytest.fixture
def execution_session(tmp_path, monkeypatch):
    out = tmp_path / "session"
    calls, reports = [], []
    original_write = runner.write
    commands = {
        "01-learning": {"kind": "learning_start", "request": {}},
        "02-workflow": {"kind": "learning_workflow", "request": {"action": "run"}},
        "03-enable": {"kind": "enable_agent_learning"},
        "04-enable-option": {"kind": "discover", "enable_agent_learning": True},
        "05-discover": {"kind": "discover"},
        "06-prepare": {"kind": "prepare_models"},
        "07-blocked": {"kind": "release_models"},
        "08-plan": {"kind": "task_plan", "request": {"action": "status"}},
        "09-launch": {"kind": "launch", "app_id": "synthetic-app"},
        "10-step": {"kind": "step", "operation": "press_key",
            "request": {"key": "Tab", "target_memory": {"interface_id": "reviewed-interface"}},
            "action_review": {"review_id": "reviewed-action"}, "decision_check": {"id": "decision"}},
    }

    def publish(path, payload):
        original_write(path, payload)
        if path.name == "report.json":
            reports.append(deepcopy(payload))
            if len(reports) == 1:
                for request_id, command in commands.items():
                    original_write(out / "commands" / (request_id + ".json"), command)

    class Coordinator:
        def __init__(self, *args, **kwargs):
            assert kwargs["enable_agent_learning"] is False

        def set_automatic_safety_interception(self, value):
            assert value is False

        def set_keep_models_loaded(self, value):
            assert value is True

        def discover_applications(self):
            calls.append("discover")
            return {"applications": []}

        def release_resident_models(self):
            calls.append("release_models")

        def preview_application_launch(self, **kwargs):
            return {"preparation_id": "synthetic-launch"}

        def confirm_window_preparation(self, preparation_id):
            assert preparation_id == "synthetic-launch"
            return {"window": {"handle": 1, "process_id": 2}}

        def execute_local_step(self, **kwargs):
            calls.append(("step", kwargs))
            return {"status": "completed"}

        def shutdown(self):
            calls.append("coordinator_stop")

    class Store:
        def __init__(self, *args):
            calls.append("learning_store_init")

        def prepare(self, *args):
            calls.append("learning_prepare")
            return None

        def control(self, *args):
            calls.append("learning_control")
            return {"status": "enabled", "recording_enabled": True}

        def snapshot(self):
            return {"status": "disabled", "recording_enabled": False}

        status = snapshot

        def close(self):
            calls.append("learning_store_close")

    class ReviewedRuntime:
        def __init__(self, *args, **kwargs):
            calls.append("reviewed_init")

        def admit(self, request_id, command):
            calls.append(("reviewed_admit", request_id))
            if command["kind"] == "release_models":
                raise ValueError("workflow_run_active")

        def handles(self, request):
            return True

        def control(self, *args):
            calls.append("reviewed_control")
            return {"runner_state": "paused"}

        def tick(self):
            calls.append("reviewed_tick")

        def stop(self):
            calls.append("reviewed_stop")

    class PlanRuntime:
        def __init__(self, *args, reviewed_runtime, **kwargs):
            assert isinstance(reviewed_runtime, ReviewedRuntime)

        def admit(self, request_id, command):
            calls.append(("plan_admit", request_id))

        def control(self, request, request_id, *, before_control=None):
            if before_control is not None:
                before_control()
            calls.append("plan_control")
            return {"status": "idle"}

        def tick(self):
            calls.append("plan_tick")
            original_write(out / "commands/99-close.json", {"kind": "close"})

        def stop(self):
            calls.append("plan_stop")

    fake_host = SimpleNamespace(facade=object(), start=lambda: None,
        close=lambda: calls.append("host_stop"), status=lambda: {"phase": "stopped"})
    monkeypatch.setattr(host, "DesktopReviewHost", lambda *args: fake_host)
    monkeypatch.setattr(single_step_coordinator, "NativeSingleStepCoordinator", Coordinator)
    monkeypatch.setattr(process_sampler, "ProcessSampler", lambda *args, **kwargs: SimpleNamespace(snapshot=lambda: {}))
    monkeypatch.setattr(decision_configuration, "create_session_decision_service", lambda *args, **kwargs: None)
    monkeypatch.setattr(runner, "initialize_session_resources", lambda *args, **kwargs: SimpleNamespace(mark_ready=lambda: None))
    monkeypatch.setattr(runner, "write", publish)
    monkeypatch.setattr(workflow_runtime, "WorkflowRuntime", ReviewedRuntime)
    bindings = object()

    def load_bindings(library, session, *, execution_request_id, command):
        assert library == out.parent / "memory-library" and session == out
        assert execution_request_id == "10-step" and command == commands["10-step"]
        calls.append("reviewed_bindings")
        return bindings

    monkeypatch.setattr(workflow_target_bindings, "load_workflow_target_bindings", load_bindings)
    monkeypatch.setattr(task_plan_admission, "TaskPlanRuntime", PlanRuntime)
    monkeypatch.setattr(agent_command_jobs, "AgentCommandJobs", lambda *args, **kwargs: None)
    # 即使退役模块已裁掉，测试仍可识别错误地重新启用的旧记录路径。
    monkeypatch.setitem(sys.modules, "app.learning_memory.event_store", SimpleNamespace(
        LearningEventStore=Store, CONTROL_KINDS={"learning_start", "learning_workflow"}))
    monkeypatch.setattr(sys, "argv", ["host", "--output", str(out), "--local-no-learning",
        "--recognition-source", "agent_current"])
    runner.main()
    return out, calls, reports, bindings


def test_execution_session_never_opens_or_schedules_learning(execution_session):
    out, calls, reports, _ = execution_session
    assert not any(isinstance(call, str) and call.startswith("learning_") for call in calls)
    assert "reviewed_control" not in calls
    assert "reviewed_tick" not in calls
    assert all(report["learning_enabled"] is False for report in reports)
    assert not (out / "learning").exists()


@pytest.mark.parametrize("request_id", ["01-learning", "02-workflow", "03-enable", "04-enable-option"])
def test_retired_session_commands_fail_before_execution_admission(execution_session, request_id):
    out, calls, _, _ = execution_session
    receipt = read_json_snapshot(out / "responses" / (request_id + ".json"))
    assert receipt["status"] == "failed"
    assert receipt["error"] == "learning_mode_retired: use execution commands"
    assert receipt["automatic_retry_allowed"] is False
    assert ("reviewed_admit", request_id) not in calls
    assert ("plan_admit", request_id) not in calls


def test_execution_admission_plan_tick_and_cleanup_remain(execution_session):
    out, calls, _, _ = execution_session
    for request_id in ("05-discover", "06-prepare", "08-plan"):
        assert read_json_snapshot(out / "responses" / (request_id + ".json"))["status"] == "returned"
        assert calls.index(("reviewed_admit", request_id)) < calls.index(("plan_admit", request_id))
    assert calls.count("discover") == 1
    assert calls.count("plan_control") == 1
    assert calls.count("plan_tick") == 1
    assert "release_models" not in calls
    assert ("plan_admit", "07-blocked") not in calls
    assert read_json_snapshot(out / "responses/07-blocked.json")["error"] == "workflow_run_active"
    assert calls[-4:] == ["reviewed_stop", "plan_stop", "coordinator_stop", "host_stop"]
    final = read_json_snapshot(out / "report.json")
    assert final["phase"] == "stopped" and final["sampler_stopped"] is True


def test_execution_reuses_reviewed_bindings_and_original_action_checks(execution_session):
    out, calls, _, bindings = execution_session
    steps = [call[1] for call in calls if isinstance(call, tuple) and call[0] == "step"]
    assert len(steps) == 1
    assert steps[0]["target_window_handle"] == 1 and steps[0]["target_process_id"] == 2
    assert steps[0]["memory_bindings"] is bindings
    assert steps[0]["action_review"] == {"review_id": "reviewed-action"}
    assert steps[0]["decision_check"] == {"id": "decision"}
    assert steps[0]["execution_request_id"] == "10-step"
    assert "learning_context" not in steps[0]
    assert read_json_snapshot(out / "responses/10-step.json")["status"] == "returned"
