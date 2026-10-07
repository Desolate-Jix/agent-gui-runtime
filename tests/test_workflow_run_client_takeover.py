"""薄客户端公开接管合同；来源 helper 在本文件隔离替身，不代表实机。"""
import sys
import json
from types import ModuleType
import pytest
from app.learning_memory.workflow_run_client import WorkflowRunClient
from tests.test_workflow_run_client import _live, _write

RUN = "trial-" + "c" * 64

@pytest.fixture(autouse=True)
def sources(monkeypatch):
    module = ModuleType("app.learning_memory.workflow_takeover_sources")
    module.read_takeover_sources = lambda session, library: []
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return module

def preview(admission="admission-one"):
    return {"action": "takeover_preview", "admission_request_id": admission,
            "source_run_id": RUN, "resolution": "resume_unexecuted"}

def commit(pid="preview-one"):
    return {"action": "takeover_commit", "preview_request_id": pid,
            "preview_sha256": "d" * 64, "mode": "single"}

def ready(pid="preview-one"):
    return {"status": "preview_ready", "preview_request_id": pid, "preview_sha256": "d" * 64,
            "source_run_id": RUN, "new_run_id": "trial-" + "e" * 64, "next_step_id": "step-two"}

def marker(client, rid, request, status="returned", result=None):
    client._record_attempt(rid, request)
    command = {"kind": "learning_workflow", "request": request}
    _write(client.session_dir / "commands" / (rid + ".json"), command)
    _write(client.session_dir / "responses" / (rid + ".json"),
           {"command": command, "status": status, "result": result})

def client_scene(tmp_path):
    session, library, pointer, report = _live(tmp_path)
    client = WorkflowRunClient(session, library)
    client.connect()
    return client, session, library, report

@pytest.mark.parametrize("action", ["preview", "commit"])
def test_public_actions_queue_once_and_same_id_reads_original(tmp_path, action):
    client, session, _, _ = client_scene(tmp_path)
    request = preview() if action == "preview" else commit()
    result = client.control(request, "new-one")
    assert result["status"] == "pending"
    assert client.control(request, "new-one")["status"] == "pending"
    assert client.result("new-one")["status"] == "pending"
    assert len(list((session / "commands").glob("*.json"))) == 1
    assert client._instant.allow_local_input is False

def test_connect_reads_sources_only_live(tmp_path, sources):
    calls = []
    sources.read_takeover_sources = lambda session, library: calls.append((session, library)) or [{"source_run_id": RUN}]
    client, session, library, report = client_scene(tmp_path)
    assert client.connect()["takeover_sources"] == [{"source_run_id": RUN}]
    assert calls
    report.update(phase="stopped", finished_at="fixture")
    _write(session / "report.json", report)
    pointer = json.loads((session.parent / "latest-session.json").read_text(encoding="utf-8"))
    pointer["host_identity"] = {"pid": 2147483647, "created": 1.0}
    _write(session.parent / "latest-session.json", pointer)
    report["runner_pid"] = 2147483647
    _write(session / "report.json", report)
    count = len(calls)
    assert WorkflowRunClient(session, library).connect()["takeover_sources"] == []
    assert len(calls) == count

def test_returned_preview_reopens_without_run_or_commit(tmp_path):
    client, session, library, _ = client_scene(tmp_path)
    marker(client, "preview-one", preview(), result=ready())
    rows = WorkflowRunClient(session, library).connect()["recoverable_controls"]
    assert len(rows) == 1 and rows[0]["request"] == preview()
    assert rows[0]["receipt"]["result"] == ready()
    assert len(list((session / "commands").glob("*.json"))) == 1

@pytest.mark.parametrize("status,result", [("failed", None), ("returned", {"status": "verification_required"}),
                                         ("pending", None)])
def test_preview_commit_is_one_transaction_and_failed_commit_keeps_original_id(tmp_path, status, result):
    client, session, library, _ = client_scene(tmp_path)
    marker(client, "preview-one", preview(), result=ready())
    marker(client, "commit-one", commit(), status=status, result=result)
    reopened = WorkflowRunClient(session, library)
    rows = reopened.connect()["recoverable_controls"]
    assert len(rows) == 1 and rows[0]["request_id"] == "commit-one"
    assert rows[0]["takeover_preview"] == ready()
    before = {p: p.read_bytes() for p in (session / "commands").glob("*.json")}
    reopened.control(commit(), "commit-one")
    assert {p: p.read_bytes() for p in (session / "commands").glob("*.json")} == before

def test_ready_commit_returns_report_run_not_old_preview(tmp_path):
    client, session, library, report = client_scene(tmp_path)
    marker(client, "preview-one", preview(), result=ready())
    run = commit_ready()
    marker(client, "commit-one", commit(), result=run)
    report["workflow_run"] = run
    _write(session / "report.json", report)
    state = WorkflowRunClient(session, library).connect()
    assert state["recoverable_controls"] == [] and state["workflow_run"] == run

@pytest.mark.parametrize("change", ["missing", "unknown", "hash"])
def test_commit_without_exact_ready_preview_never_guesses(tmp_path, change):
    client, session, library, _ = client_scene(tmp_path)
    if change != "missing":
        value = ready()
        if change == "hash": value["preview_sha256"] = "f" * 64
        marker(client, "preview-one", preview(), status="returned" if change == "hash" else "pending", result=value)
    marker(client, "commit-one", commit(), status="failed")
    with pytest.raises(ValueError):
        WorkflowRunClient(session, library).connect()

def test_multiple_transactions_are_preserved_not_selected_by_filename(tmp_path):
    client, session, library, _ = client_scene(tmp_path)
    marker(client, "preview-one", preview(), result=ready())
    marker(client, "preview-two", preview("admission-two"), result=ready("preview-two"))
    rows = WorkflowRunClient(session, library).connect()["recoverable_controls"]
    assert {row["request_id"] for row in rows} == {"preview-one", "preview-two"}

def test_unknown_submission_reopens_original_id_without_second_queue(tmp_path):
    client, session, library, _ = client_scene(tmp_path)
    client._record_attempt("preview-unknown", preview())
    reopened = WorkflowRunClient(session, library)
    rows = reopened.connect()["recoverable_controls"]
    assert rows[0]["request_id"] == "preview-unknown"
    assert reopened.control(preview(), "preview-unknown")["status"] == "not_found"
    assert not list((session / "commands").glob("*.json"))


def test_not_submitted_commit_still_preserves_original_transaction(tmp_path):
    client, session, library, _ = client_scene(tmp_path)
    marker(client, "preview-one", preview(), result=ready())
    client._record_attempt("commit-one", commit())
    client._record_not_submitted("commit-one", {"request_id": "commit-one", "status": "not_submitted"})
    reopened = WorkflowRunClient(session, library)
    rows = reopened.connect()["recoverable_controls"]
    assert len(rows) == 1 and rows[0]["request_id"] == "commit-one"
    assert rows[0]["takeover_preview"] == ready()
    assert reopened.control(commit(), "commit-one")["status"] == "not_submitted"
    assert not (session / "commands/commit-one.json").exists()

def commit_ready():
    return {"run_id": "trial-" + "e" * 64, "current_step_id": "step-two",
            "runner_state": "waiting", "wait_reason": "takeover_ready",
            "wait": {"wait_id": "workflow-wait-" + "a" * 32, "reason": "takeover_ready"}}

@pytest.mark.parametrize("change", ["run", "operation", "failed", "wait"])
def test_invalid_commit_snapshot_keeps_original_transaction(tmp_path, change):
    client, session, library, _ = client_scene(tmp_path)
    marker(client, "preview-one", preview(), result=ready())
    result = commit_ready()
    if change == "run": result["run_id"] = "trial-" + "f" * 64
    if change == "operation": result["success"] = False
    if change == "failed": result["runner_state"] = "failed"
    if change == "wait": result["wait_reason"] = "other"
    marker(client, "commit-one", commit(), result=result)
    reopened = WorkflowRunClient(session, library)
    rows = reopened.connect()["recoverable_controls"]
    assert len(rows) == 1 and rows[0]["request_id"] == "commit-one"
    assert rows[0]["takeover_preview"] == ready()
    before = {p: p.read_bytes() for p in (session / "commands").glob("*.json")}
    reopened.control(commit(), "commit-one")
    assert {p: p.read_bytes() for p in (session / "commands").glob("*.json")} == before

@pytest.mark.parametrize("change", ["outer_failure", "nested_wait"])
def test_receipt_and_nested_wait_must_both_allow_ready(tmp_path, change):
    client, session, library, _ = client_scene(tmp_path)
    marker(client, "preview-one", preview(), result=ready())
    result = commit_ready()
    result["wait"]["reason"] = "takeover_ready"
    if change == "outer_failure":
        result["success"] = False
    else:
        result["wait"]["reason"] = "other"
    marker(client, "commit-one", commit(), result=result)
    reopened = WorkflowRunClient(session, library)
    rows = reopened.connect()["recoverable_controls"]
    assert len(rows) == 1 and rows[0]["request_id"] == "commit-one"
    assert rows[0]["takeover_preview"] == ready()
    before = {p: p.read_bytes() for p in (session / "commands").glob("*.json")}
    reopened.control(commit(), "commit-one")
    assert {p: p.read_bytes() for p in (session / "commands").glob("*.json")} == before

@pytest.mark.parametrize("kind", ["failed", "returned_failure", "not_submitted"])
def test_failed_preview_reopens_same_request_without_retry(tmp_path, kind):
    client, session, library, _ = client_scene(tmp_path)
    if kind == "not_submitted":
        client._record_attempt("preview-one", preview())
        client._record_not_submitted("preview-one", {"request_id": "preview-one", "status": "not_submitted"})
    else:
        marker(client, "preview-one", preview(), status="failed" if kind == "failed" else "returned",
               result={"status": "failed"})
    reopened = WorkflowRunClient(session, library)
    rows = reopened.connect()["recoverable_controls"]
    assert len(rows) == 1 and rows[0]["request_id"] == "preview-one"
    assert rows[0]["request"] == preview()
    before = {p: p.read_bytes() for p in (session / "commands").glob("*.json")}
    reopened.control(preview(), "preview-one")
    assert {p: p.read_bytes() for p in (session / "commands").glob("*.json")} == before
