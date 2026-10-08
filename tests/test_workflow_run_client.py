"""运行客户端只附着原 Instant 宿主并复用其原命令票据。"""
import json
import os

import psutil
import pytest

from app.learning_memory.workflow_run_client import WorkflowRunClient
from app.core.instant_command_queue import command_queue_lock


def _write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _live(tmp_path):
    session = tmp_path / ("session-" + "a" * 32)
    session.mkdir()
    (session / "commands").mkdir()
    (session / "responses").mkdir()
    library = tmp_path / "memory-library"
    library.mkdir()
    identity = {"pid": os.getpid(), "created": psutil.Process().create_time()}
    pointer = {"name": session.name, "host_identity": identity,
               "recognition_source": "agent_delegate", "delegate_profile": "existing-profile", "api_profile": None}
    report = {"runner_pid": identity["pid"], "phase": "ready", "started_at": "fixture"}
    _write(tmp_path / "latest-session.json", pointer)
    _write(session / "report.json", report)
    return session, library, pointer, report


def _start_request():
    return {"action": "start", "workflow_id": "workflow-" + "a" * 64,
            "program_id": "task-program-" + "b" * 64, "start_step_id": "step-1", "inputs": {}}


@pytest.mark.parametrize("change", ["wrong_library", "wrong_pointer", "wrong_report", "finished"])
def test_attach_rejects_stale_or_wrong_library_without_dispatch(tmp_path, change):
    session, library, pointer, report = _live(tmp_path)
    if change == "wrong_library":
        library = tmp_path / "other-library"
        library.mkdir()
    elif change == "wrong_pointer":
        pointer["name"] = "session-" + "b" * 32
        _write(tmp_path / "latest-session.json", pointer)
    elif change == "wrong_identity":
        pointer["host_identity"]["created"] += 1
        _write(tmp_path / "latest-session.json", pointer)
    elif change == "wrong_report":
        report["runner_pid"] += 1
        _write(session / "report.json", report)
    else:
        report["finished_at"] = "fixture"
        _write(session / "report.json", report)
    client = WorkflowRunClient(session, library)
    with pytest.raises(ValueError):
        client.connect()
    assert not list((session / "commands").glob("*.json"))
    assert not (tmp_path / "owner.lock").exists()


def test_control_rechecks_host_and_closed_client_never_dispatches(tmp_path):
    session, library, _, report = _live(tmp_path)
    client = WorkflowRunClient(session, library)
    assert client.connect()["recognition_source"] == "agent_delegate"
    report["phase"] = "stopped"
    _write(session / "report.json", report)
    with pytest.raises(ValueError):
        client.control(_start_request(), "start-one")
    client.close()
    with pytest.raises(RuntimeError):
        client.control(_start_request(), "start-two")
    assert not list((session / "commands").glob("*.json"))


def test_real_instant_queue_and_resume_original_request_without_duplicate_dispatch(tmp_path):
    session, library, _, _ = _live(tmp_path)
    client = WorkflowRunClient(session, library)
    client.connect()
    request = _start_request()
    first = client.control(request, "start-one")
    assert first["status"] == "pending" and first["request_id"] == "start-one"
    command = {"kind": "learning_workflow", "request": request}
    assert json.loads((session / "commands" / "start-one.json").read_text(encoding="utf-8")) == command
    assert client.control(request, "start-one")["status"] == "pending"
    with pytest.raises(ValueError):
        client.control({"action": "status", "run_id": "other"}, "start-one")
    _write(session / "responses" / "start-one.json", {"command": command, "status": "returned",
        "result": {"status": "completed", "run_id": "run-one"}})
    result = client.result("start-one")
    assert result["status"] == "returned" and result["result"]["run_id"] == "run-one"
    assert client.control(request, "start-one") == result
    assert len(list((session / "commands").glob("*.json"))) == 1
    assert not (session.parent / "owner.lock").exists()


def test_result_unknown_after_host_exit_and_close_leaves_owned_external_host_alive(tmp_path):
    session, library, _, report = _live(tmp_path)
    client = WorkflowRunClient(session, library)
    client.connect()
    client.control(_start_request(), "start-one")
    client._instant.host_identity["created"] += 1
    assert client.result("start-one")["status"] == "result_unknown"
    client.close()
    assert psutil.Process().is_running()
    assert (session / "commands" / "start-one.json").exists()
    assert not (session / "closing.json").exists()


@pytest.mark.parametrize("finished", [False, True])
def test_fresh_dead_host_attachment_reads_original_ledger_without_dispatch(tmp_path, monkeypatch, finished):
    session, library, pointer, report = _live(tmp_path)
    client = WorkflowRunClient(session, library)
    client.connect()
    request = {"action": "status", "run_id": "trial-" + "c" * 64}
    client.control(request, "original-status")
    report["workflow_run"] = {"run_id": request["run_id"], "runner_state": "waiting",
        "status": "blocked", "wait_reason": "verification_required", "wait": {"wait_id": "original-wait"}}
    if finished:
        report.update(phase="stopped", finished_at="fixture")
    _write(session / "report.json", report)
    actual = psutil.Process

    def dead(pid=None):
        if pid == pointer["host_identity"]["pid"]:
            raise psutil.NoSuchProcess(pid)
        return actual(pid)

    monkeypatch.setattr(psutil, "Process", dead)
    monkeypatch.setattr("app.instant_mcp.InstantSession.start", lambda *a, **k: pytest.fail("readonly attach started host"))
    reopened = WorkflowRunClient(session, library)
    status = reopened.connect()
    assert status["host_alive"] is False
    assert status["workflow_run"] == report["workflow_run"]
    assert status["recoverable_controls"][0]["request_id"] == "original-status"
    assert reopened.result("original-status")["status"] == "result_unknown"
    command = {"kind": "learning_workflow", "request": request}
    _write(session / "responses" / "original-status.json", {"command": command, "status": "returned",
        "result": {"run_id": request["run_id"], "status": "completed"}})
    assert reopened.result("original-status")["result"]["status"] == "completed"
    with pytest.raises(ValueError):
        reopened.control(request, "new-status")
    assert [p.stem for p in (session / "commands").glob("*.json")] == ["original-status"]
    assert not (tmp_path / "owner.lock").exists()


def test_pid_reuse_is_readonly_and_cannot_admit_new_control(tmp_path):
    session, library, pointer, _ = _live(tmp_path)
    pointer["host_identity"]["created"] += 1
    _write(tmp_path / "latest-session.json", pointer)
    client = WorkflowRunClient(session, library)
    assert client.connect()["host_alive"] is False
    with pytest.raises(ValueError, match="workflow_run_host_identity_stale"):
        client.control(_start_request(), "no-dispatch")
    assert not list((session / "commands").glob("*.json"))


@pytest.mark.parametrize("field,value", [("phase", 1), ("phase", {}), ("runner_pid", "bad"), ("workflow_run", []),
                                          ("finished_at", 1)])
def test_dead_attachment_rejects_malformed_report(tmp_path, field, value):
    session, library, pointer, report = _live(tmp_path)
    pointer["host_identity"]["created"] += 1
    report[field] = value
    _write(tmp_path / "latest-session.json", pointer)
    _write(session / "report.json", report)
    with pytest.raises(ValueError):
        WorkflowRunClient(session, library).connect()
    assert not list((session / "commands").glob("*.json"))


@pytest.mark.parametrize("change", ["pointer", "source", "profile", "receipt"])
def test_dead_readonly_attachment_preserves_original_bindings(tmp_path, monkeypatch, change):
    session, library, pointer, report = _live(tmp_path)
    client = WorkflowRunClient(session, library)
    client.connect()
    request = {"action": "status", "run_id": "trial-" + "c" * 64}
    client.control(request, "original-control")
    actual = psutil.Process

    def dead(pid=None):
        if pid == pointer["host_identity"]["pid"]:
            raise psutil.NoSuchProcess(pid)
        return actual(pid)

    monkeypatch.setattr(psutil, "Process", dead)
    if change == "pointer":
        pointer["name"] = "session-" + "b" * 32
    elif change == "source":
        pointer["recognition_source"] = "invalid"
    elif change == "profile":
        pointer["delegate_profile"] = None
    else:
        _write(session / "responses" / "original-control.json", {"status": "returned",
            "command": {"kind": "learning_workflow", "request": {"action": "status", "run_id": "different"}},
            "result": {"run_id": "different"}})
    _write(tmp_path / "latest-session.json", pointer)
    with pytest.raises(ValueError):
        WorkflowRunClient(session, library).connect()
    assert len(list((session / "commands").glob("*.json"))) == 1


def test_invalid_recognition_pointer_does_not_attach(tmp_path):
    session, library, pointer, _ = _live(tmp_path)
    pointer["recognition_source"] = "agent"
    _write(tmp_path / "latest-session.json", pointer)
    with pytest.raises(ValueError, match="workflow_run_recognition_source_invalid"):
        WorkflowRunClient(session, library).connect()
    assert not list((session / "commands").glob("*.json"))


@pytest.mark.parametrize("changed", ["recognition", "decision"])
def test_changed_attached_configuration_rejects_new_control_but_keeps_original_result(tmp_path, changed):
    session, library, pointer, _ = _live(tmp_path)
    client = WorkflowRunClient(session, library)
    client.connect()
    if changed == "recognition":
        pointer.update(recognition_source="local", delegate_profile=None)
    else:
        pointer.update(decision_profile="C:/changed.json", decision_profile_sha256="a" * 64)
    _write(tmp_path / "latest-session.json", pointer)
    with pytest.raises(ValueError, match="workflow_run_attachment_changed"):
        client.control(_start_request(), "start-one")
    assert client.result("start-one")["status"] == "not_found"
    assert not list((session / "commands").glob("*.json"))


@pytest.mark.parametrize("action", ["status", "cancel"])
def test_pending_queue_rejects_new_control_without_creating_a_false_pending_id(tmp_path, action):
    session, library, _, _ = _live(tmp_path)
    client = WorkflowRunClient(session, library)
    client.connect()
    original = client.control(_start_request(), "start-one")
    original_command = (session / "commands" / "start-one.json").read_bytes()
    rejected = client.control({"action": action, "run_id": "run-one"}, "control-two")
    assert rejected == {"request_id": "control-two", "status": "not_submitted",
                        "reason": "command_pending", "pending_ids": ["start-one"],
                        "automatic_retry_allowed": False}
    assert original["status"] == "pending"
    assert client.result("start-one")["status"] == "pending"
    assert (session / "commands" / "start-one.json").read_bytes() == original_command
    assert client.result("control-two") == rejected
    assert sorted(path.stem for path in (session / "commands").glob("*.json")) == ["start-one"]


def test_queue_lock_busy_is_known_non_submission_and_io_error_is_not(tmp_path):
    session, library, _, _ = _live(tmp_path)
    client = WorkflowRunClient(session, library)
    client.connect()
    with command_queue_lock(session):
        rejected = client.control({"action": "status", "run_id": "run-one"}, "status-one")
    assert rejected == {"request_id": "status-one", "status": "not_submitted",
                        "reason": "command_queue_busy", "pending_ids": [],
                        "automatic_retry_allowed": False}
    assert not list((session / "commands").glob("*.json"))

    class BrokenTransport:
        def submit(self, request_id, command):
            raise OSError("unknown write state")

        def result(self, request_id):
            raise AssertionError("unexpected result lookup")

    unknown = WorkflowRunClient(session, library, transport=BrokenTransport())
    unknown.connect()
    with pytest.raises(OSError, match="unknown write state"):
        unknown.control({"action": "status", "run_id": "run-one"}, "status-two")


def test_reopen_recovers_original_pending_id_without_new_dispatch(tmp_path):
    session, library, _, _ = _live(tmp_path)
    first = WorkflowRunClient(session, library)
    first.connect()
    first.control(_start_request(), "start-one")
    first.close()
    reopened = WorkflowRunClient(session, library)
    controls = reopened.connect()["recoverable_controls"]
    assert len(controls) == 1
    assert controls[0] == {"request_id": "start-one", "action": "start",
                           "request": _start_request(), "receipt": reopened.result("start-one")}
    assert controls[0]["receipt"]["status"] == "pending"
    assert reopened.control(_start_request(), "start-one")["status"] == "pending"
    assert len(list((session / "commands").glob("*.json"))) == 1


def test_unknown_attempt_without_command_stays_not_found_on_reopen(tmp_path):
    session, library, _, _ = _live(tmp_path)

    class UnknownTransport:
        def submit(self, request_id, command):
            raise OSError("write outcome unknown")

        def result(self, request_id):
            raise AssertionError("unexpected")

    client = WorkflowRunClient(session, library, transport=UnknownTransport())
    client.connect()
    with pytest.raises(OSError, match="write outcome unknown"):
        client.control(_start_request(), "start-one")
    reopened = WorkflowRunClient(session, library)
    controls = reopened.connect()["recoverable_controls"]
    assert len(controls) == 1 and controls[0]["receipt"]["status"] == "not_found"
    assert reopened.control(_start_request(), "start-one")["status"] == "not_found"
    assert not list((session / "commands").glob("*.json"))


def test_returned_start_is_recoverable_only_until_runner_state_exists(tmp_path):
    session, library, _, _ = _live(tmp_path)
    client = WorkflowRunClient(session, library)
    client.connect()
    client.control(_start_request(), "start-one")
    run_id = "trial-" + "c" * 64
    fields = {key: value for key, value in _start_request().items() if key != "action"}
    _write(session / "responses" / "start-one.json", {"command": {"kind": "learning_workflow",
        "request": _start_request()}, "status": "returned",
        "result": {**fields, "run_id": run_id, "status": "ready", "pending": None}})
    (session / "workflow-trials").mkdir()
    _write(session / "workflow-trials" / (run_id + ".json"),
           {**fields, "run_id": run_id, "status": "ready", "pending": None})
    reopened = WorkflowRunClient(session, library)
    assert [row["request_id"] for row in reopened.connect()["recoverable_controls"]] == ["start-one"]
    (session / "workflow-runners").mkdir()
    _write(session / "workflow-runners" / (run_id + ".json"),
           {"schema": "workflow_runner.v1", "run_id": run_id, "runner_state": "ready"})
    assert reopened.connect()["recoverable_controls"] == []
    assert WorkflowRunClient(session, library).connect()["recoverable_controls"] == []


def test_known_not_submitted_survives_reopen_without_becoming_unknown(tmp_path):
    session, library, _, _ = _live(tmp_path)
    client = WorkflowRunClient(session, library)
    client.connect()
    client.control(_start_request(), "start-one")
    rejected = client.control({"action": "status", "run_id": "run-one"}, "status-two")
    assert rejected["status"] == "not_submitted"
    reopened = WorkflowRunClient(session, library)
    controls = reopened.connect()["recoverable_controls"]
    assert all(row["request_id"] != "status-two" for row in controls)
    assert reopened.result("status-two") == rejected
    assert reopened.control({"action": "status", "run_id": "run-one"}, "status-two") == rejected
    assert not (session / "commands" / "status-two.json").exists()


def test_orphan_response_without_original_command_does_not_complete_unknown_attempt(tmp_path):
    session, library, _, _ = _live(tmp_path)

    class UnknownTransport:
        def submit(self, request_id, command):
            raise OSError("write outcome unknown")

        def result(self, request_id):
            raise AssertionError("unexpected")

    client = WorkflowRunClient(session, library, transport=UnknownTransport())
    client.connect()
    with pytest.raises(OSError):
        client.control(_start_request(), "start-one")
    _write(session / "responses" / "start-one.json", {"status": "returned", "result": {"status": "ready"}})
    reopened = WorkflowRunClient(session, library)
    recovered = reopened.connect()["recoverable_controls"]
    assert recovered[0]["receipt"]["status"] == "not_found"
    assert reopened.result("start-one")["status"] == "not_found"


def test_recovery_rejects_command_payload_that_disagrees_with_marker(tmp_path):
    session, library, _, _ = _live(tmp_path)
    client = WorkflowRunClient(session, library)
    client.connect()
    client.control(_start_request(), "start-one")
    _write(session / "commands" / "start-one.json", {"kind": "learning_workflow",
        "request": {"action": "status", "run_id": "other"}})
    with pytest.raises(ValueError, match="workflow_run_marker_command_mismatch"):
        WorkflowRunClient(session, library).connect()


def test_recovery_rejects_response_from_a_different_command(tmp_path):
    session, library, _, _ = _live(tmp_path)
    client = WorkflowRunClient(session, library)
    client.connect()
    client.control(_start_request(), 'start-one')
    _write(session / 'responses' / 'start-one.json', {'status': 'returned',
        'command': {'kind': 'learning_workflow', 'request': {'action': 'status', 'run_id': 'other'}},
        'result': {'run_id': 'other', 'status': 'ready'}})
    with pytest.raises(ValueError, match='workflow_run_original_receipt_mismatch'):
        client.result('start-one')


def test_ready_recovery_rejects_a_trial_with_changed_original_inputs(tmp_path):
    session, library, _, _ = _live(tmp_path)
    client = WorkflowRunClient(session, library)
    client.connect()
    request = _start_request()
    client.control(request, 'start-one')
    state = {key: value for key, value in request.items() if key != 'action'}
    state.update(run_id='trial-' + 'c' * 64, status='ready', pending=None)
    _write(session / 'responses' / 'start-one.json', {'status': 'returned',
        'command': {'kind': 'learning_workflow', 'request': request}, 'result': state})
    (session / 'workflow-trials').mkdir()
    _write(session / 'workflow-trials' / (state['run_id'] + '.json'),
           {**state, 'inputs': {'injected': 'another-run'}})
    with pytest.raises(ValueError, match='workflow_run_trial_binding_mismatch'):
        WorkflowRunClient(session, library).connect()


@pytest.mark.parametrize('action', ['run', 'continue', 'status', 'cancel', 'verify'])
def test_control_receipt_cannot_replace_original_run_identity(tmp_path, action):
    session, library, _, _ = _live(tmp_path)
    client = WorkflowRunClient(session, library)
    client.connect()
    request = {'action': action, 'run_id': 'trial-' + 'c' * 64}
    if action == 'run':
        request['mode'] = 'single'
    elif action == 'continue':
        request['wait_id'] = 'original-wait'
    elif action == 'verify':
        request['execution_request_id'] = 'original-execution'
    original = client.control(request, 'original-control')
    assert original['status'] == 'pending'
    payload = {'status': 'returned', 'command': {'kind': 'learning_workflow', 'request': request},
               'result': {'run_id': 'trial-' + 'd' * 64, 'status': 'completed',
                          'outputs': {'value': '另一个运行的值'}}}
    _write(session / 'responses' / 'original-control.json', payload)
    with pytest.raises(ValueError, match='workflow_run_result_identity_mismatch'):
        client.result('original-control')
    with pytest.raises(ValueError, match='workflow_run_result_identity_mismatch'):
        WorkflowRunClient(session, library).connect()
    assert len(list((session / 'commands').glob('*.json'))) == 1
    payload['result']['run_id'] = request['run_id']
    _write(session / 'responses' / 'original-control.json', payload)
    assert client.result('original-control')['result']['run_id'] == request['run_id']
    assert client.control(request, 'original-control')['result']['run_id'] == request['run_id']
    assert len(list((session / 'commands').glob('*.json'))) == 1


@pytest.mark.parametrize('variant', ['owned', 'unrelated', 'wrong_session', 'wrong_entry', 'exited'])
def test_attach_checks_actual_runner_under_python_launcher(tmp_path, monkeypatch, variant):
    from pathlib import Path
    from types import SimpleNamespace
    session, library, pointer, report = _live(tmp_path)
    real_process = psutil.Process
    owner = real_process(pointer['host_identity']['pid'])
    runner_pid = 2147483000
    report['runner_pid'] = runner_pid
    _write(session / 'report.json', report)
    entry = Path(__file__).resolve().parents[1] / 'scripts' / 'run_local_step_session.py'
    command = ['python.exe', str(entry), '--output', str(session)]
    if variant == 'wrong_entry':
        command[1] = str(entry.with_name('unrelated.py'))
    if variant == 'wrong_session':
        command[-1] = str(session.parent / 'another-session')
    runner = SimpleNamespace(pid=runner_pid, is_running=lambda: variant != 'exited',
        status=lambda: psutil.STATUS_RUNNING, create_time=lambda: owner.create_time() + 1,
        ppid=lambda: owner.pid if variant != 'unrelated' else owner.pid + 1,
        cmdline=lambda: command)
    import app.learning_memory.workflow_run_client as module
    proxy = SimpleNamespace(**vars(psutil))
    proxy.Process = lambda pid=None: runner if pid == runner_pid else real_process(pid)
    monkeypatch.setattr(module, 'psutil', proxy)
    client = WorkflowRunClient(session, library)
    if variant == 'owned':
        assert client.connect()['host_alive'] is True
        assert client.control(_start_request(), 'owned-start')['status'] == 'pending'
        runner.create_time = lambda: owner.create_time() + 2
        with pytest.raises(ValueError, match='workflow_run_runner_identity_changed'):
            client.control({'action': 'status', 'run_id': 'run-one'}, 'changed-runner')
        assert not (session / 'commands' / 'changed-runner.json').exists()
    else:
        with pytest.raises(ValueError, match='workflow_run_runner_identity_invalid'):
            client.connect()
        assert not list((session / 'commands').glob('*.json'))
