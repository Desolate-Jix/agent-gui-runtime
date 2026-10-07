"""原会话客户端专用结算入口与普通只读刷新分离。"""
from copy import deepcopy
import shutil
from types import SimpleNamespace

import pytest

from app.core.json_snapshot import write_json_snapshot
from app.learning_memory.workflow_run_client import WorkflowRunClient
from app.learning_memory.workflow_trial import TrialService
from tests.test_workflow_terminal_recovery import recovery_scene, terminal, originals
from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_trial import services


@pytest.fixture
def client_scene(recovery_scene):
    _, old_trials, run, old_session, ticket, host, runner_pid = recovery_scene
    terminal(recovery_scene)
    session = old_session.with_name("session-" + "a" * 32)
    old_session.rename(session)
    library = session.parent / "memory-library"
    shutil.copytree(old_trials.programs.library._workspace_root, library / "desktop-review")
    trials = TrialService(SimpleNamespace(_workspace_root=library / "desktop-review"), session)
    pointer = {"name": session.name, "host_identity": host,
        "recognition_source": "agent_delegate", "delegate_profile": "existing-profile", "api_profile": None}
    snapshot = {**trials.status(run["run_id"]), "runner_state": "waiting", "wait_reason": "execution_pending"}
    write_json_snapshot(session.parent / "latest-session.json", pointer)
    write_json_snapshot(session / "report.json", {"phase": "ready", "runner_pid": runner_pid,
        "workflow_run": snapshot})
    return WorkflowRunClient(session, library), trials, run, session, ticket


def test_explicit_recovery_persists_and_fresh_client_reads_ledger_without_dispatch(client_scene, monkeypatch):
    client, trials, run, session, ticket = client_scene
    monkeypatch.setattr("app.instant_mcp.InstantSession.submit", lambda *a, **k: pytest.fail("recovery submitted input"))
    assert client.connect()["host_alive"] is False
    before = trials._path(run["run_id"]).read_bytes()
    raw = originals(session)
    preview = client.preview_recovery(run["run_id"])
    assert trials._path(run["run_id"]).read_bytes() == before
    settled = client.settle_recovery(preview, request_id="explicit-settlement")
    assert settled["host_alive"] is False
    assert settled["workflow_run"]["wait_reason"] == "recovery_paused"
    assert settled["workflow_run"]["pending"] == ticket
    assert settled["workflow_run"]["recovery_settlement"]["action_executed"] is True
    saved = trials._path(run["run_id"]).read_bytes()
    client.close()
    reopened = WorkflowRunClient(session, client.library_root)
    assert reopened.connect()["workflow_run"] == settled["workflow_run"]
    assert reopened.settle_recovery(preview, request_id="explicit-settlement")["workflow_run"] == settled["workflow_run"]
    assert trials._path(run["run_id"]).read_bytes() == saved
    assert originals(session) == raw
    with pytest.raises(ValueError):
        reopened.control({"action": "continue", "run_id": run["run_id"], "wait_id": "old-wait"}, "unsafe-continue")


def test_pointer_change_or_closed_client_cannot_settle(client_scene):
    client, trials, run, session, _ = client_scene
    client.connect()
    preview = client.preview_recovery(run["run_id"])
    before = trials._path(run["run_id"]).read_bytes()
    pointer_path = session.parent / "latest-session.json"
    original_pointer = pointer_path.read_bytes()
    pointer_path.write_bytes(original_pointer.replace(b"existing-profile", b"another-profile"))
    with pytest.raises(ValueError, match="attachment_changed"):
        client.settle_recovery(preview, request_id="changed-attachment")
    pointer_path.write_bytes(original_pointer)
    client.close()
    with pytest.raises(RuntimeError, match="closed"):
        client.settle_recovery(preview, request_id="closed-client")
    assert trials._path(run["run_id"]).read_bytes() == before
