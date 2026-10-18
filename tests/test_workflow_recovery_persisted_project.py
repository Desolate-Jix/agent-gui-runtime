"""恢复入口必须加载真实持久项目依赖，不能依赖 read_project 替身。"""
from copy import deepcopy
from types import SimpleNamespace

from app.core.json_snapshot import write_json_snapshot
from app.learning_memory.event_store import LearningEventStore
from app.learning_memory.graph_source import logical_id
from app.learning_memory.workspace import MemoryWorkspace
from app.learning_memory.workflow_program import WorkflowProgramService
from app.learning_memory.workflow_trial import TrialService
from app.learning_memory.workflow_run_client import WorkflowRunClient
from tests.test_learning_memory_v1 import record_search
from tests.test_workflow_terminal_recovery import recovery_scene, terminal
from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_trial import services


def test_real_pinned_project_preview_settlement_and_readonly_reopening(recovery_scene, tmp_path, monkeypatch):
    from app.learning_memory.reader import read_project
    monkeypatch.setattr("app.learning_memory.workflow_program.read_project", read_project)
    monkeypatch.setattr("app.learning_memory.workflow_runner.MemoryWorkspace", MemoryWorkspace)
    _, _, _, _, _, host, runner_pid = recovery_scene
    data = tmp_path / "persisted-project"
    session = data / ("session-" + "b" * 32)
    (session / "responses").mkdir(parents=True)
    (session / "commands").mkdir()
    store = LearningEventStore(session)
    store.control("learning_start", {"scope": "workflow", "title": "本轮新项目", "project_id": "fresh-persisted"}, "learn-start")
    record_search(store, "fresh-observed-search")
    store.control("learning_stop", {}, "learn-stop")
    library = data / "memory-library"
    workflow = logical_id("fresh-persisted")
    with MemoryWorkspace(library) as memory:
        programs = WorkflowProgramService(memory)
        draft = programs.load(workflow)
        definition = deepcopy(draft["definition"])
        step = definition["steps"][0]
        saved = programs.save(workflow, draft["content_sha256"], definition, "save-program")
        trials = TrialService(memory, session)
        run = trials.start(workflow, saved["program_id"], step["step_id"], {"place": "new live value"}, "trial-start")
    from app.learning_memory.workflow_runtime import WorkflowRuntime
    runtime = WorkflowRuntime(session, SimpleNamespace(_memory_library_root=library))
    snapshot = runtime.control({"action": "run", "run_id": run["run_id"], "mode": "until_wait"}, "runner-start")
    ticket = trials.status(run["run_id"])["pending"]
    terminal((runtime, trials, run, session, ticket, host, runner_pid))
    write_json_snapshot(data / "latest-session.json", {"name": session.name, "host_identity": host,
        "recognition_source": "agent_current", "delegate_profile": None, "api_profile": None})
    write_json_snapshot(session / "report.json", {"phase": "ready", "runner_pid": runner_pid, "workflow_run": snapshot})
    client = WorkflowRunClient(session, library)
    assert client.connect()["host_alive"] is False
    preview = client.preview_recovery(run["run_id"])
    assert preview["program_id"] == saved["program_id"]
    settled = client.settle_recovery(preview, request_id="real-project-recovery")
    assert settled["workflow_run"]["recovery_settlement"]["action_executed"] is True
    raw = trials._path(run["run_id"]).read_bytes()
    client.close()
    reopened = WorkflowRunClient(session, library)
    assert reopened.connect()["workflow_run"]["wait_reason"] == "recovery_paused"
    assert trials._path(run["run_id"]).read_bytes() == raw
