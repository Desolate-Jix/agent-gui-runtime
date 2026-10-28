"""Native HTTP lifecycle regressions using a real, never launched session.

All installation/data paths are temporary. Real process creation is forbidden;
these checks never reach desktop, model, or provider execution.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import secrets
from threading import Event
from types import SimpleNamespace

import pytest
from starlette.responses import JSONResponse
from starlette.testclient import TestClient

from app.instant_mcp import InstantSession, InstantStartError
from app.instant_mcp_http import create_instant_http_app


def _headers(token, owner=None):
    result = {"Authorization": "Bearer " + token,
              "Accept": "application/json, text/event-stream"}
    if owner is not None:
        result.update({"MCP-Session-Id": owner,
                       "MCP-Protocol-Version": "2025-11-25"})
    return result


def _initialize_response(client, token, request_id=1):
    return client.post("/mcp", headers=_headers(token), json={
        "jsonrpc": "2.0", "id": request_id, "method": "initialize", "params": {
            "protocolVersion": "2025-11-25", "capabilities": {},
            "clientInfo": {"name": "real-initial-lifecycle-test", "version": "1"}}})


def _initialize(client, token, request_id=1):
    response = _initialize_response(client, token, request_id)
    assert response.status_code == 200, response.text
    assert response.json()["result"]["protocolVersion"] == "2025-11-25"
    owner = response.headers["mcp-session-id"]
    initialized = client.post("/mcp", headers=_headers(token, owner), json={
        "jsonrpc": "2.0", "method": "notifications/initialized"})
    assert initialized.status_code == 202, initialized.text
    return owner


def _call(client, token, owner, name, arguments=None, request_id=2):
    return client.post("/mcp", headers=_headers(token, owner), json={
        "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
        "params": {"name": name, "arguments": arguments or {}}})


def _tool_value(response):
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert not result.get("isError", False), result
    return result.get("structuredContent") or json.loads(result["content"][0]["text"])


@pytest.fixture
def real_transport(tmp_path, monkeypatch):
    def forbidden_process(*args, **kwargs):
        pytest.fail("initial lifecycle checks must never create a real process")

    monkeypatch.setattr("app.instant_mcp.subprocess.Popen", forbidden_process)
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("AGENT_GUI_MCP_TOKEN", token)
    monkeypatch.delenv("AGENT_GUI_DECISION_PROFILE", raising=False)
    root = tmp_path / "installation"
    root.mkdir()
    session = InstantSession(root, tmp_path / "data", recognition_source="agent_current")
    app = create_instant_http_app(session)
    try:
        with TestClient(app, base_url="http://127.0.0.1",
                        client=("127.0.0.1", 51000)) as client:
            yield app, client, session, token
    finally:
        app.close()
        assert session._installation_lease._stream is None


@pytest.mark.parametrize("stop_first", [False, True], ids=["read-only", "stop-first"])
def test_real_cold_session_delete_releases_owner_without_start(real_transport, stop_first):
    app, client, session, token = real_transport
    owner = _initialize(client, token)
    listed = client.post("/mcp", headers=_headers(token, owner), json={
        "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    assert listed.status_code == 200
    assert "instant_status" in {row["name"] for row in listed.json()["result"]["tools"]}
    status = _tool_value(_call(client, token, owner, "instant_status", request_id=3))
    assert status["host_alive"] is False and status["pending_ids"] == []
    # A cold connection has no cleanup report; never claim cleanup was run.
    assert status["cleanup_verified"] is False
    if stop_first:
        stopped = _tool_value(_call(client, token, owner, "instant_stop", request_id=4))
        assert stopped["host_alive"] is False and stopped["pending_ids"] == []
        assert stopped["cleanup_verified"] is False
    assert all(getattr(session, name) is None for name in
               ("session", "host_identity", "process", "lock_file", "log_file"))
    assert not session.data_root.exists()
    deleted = client.delete("/mcp", headers=_headers(token, owner))
    assert deleted.status_code == 200, deleted.text
    assert app._owner is None
    assert session._installation_lease._stream is not None
    new_owner = _initialize(client, token, request_id=5)
    assert new_owner != owner and app._owner == new_owner
    assert _call(client, token, owner, "instant_status").status_code == 409
    assert client.delete("/mcp", headers=_headers(token, new_owner)).status_code == 200
    assert all(getattr(session, name) is None for name in
               ("session", "host_identity", "process", "lock_file", "log_file"))
    assert not session.data_root.exists()


def _data_snapshot(session):
    result = {}
    for path in session.data_root.rglob("*"):
        if not path.is_file():
            continue
        if path.name == "owner.lock":
            # Windows range locking deliberately forbids a separate reader.
            facts = path.stat()
            value = (facts.st_size, facts.st_mtime_ns)
        else:
            value = path.read_bytes()
        result[str(path.relative_to(session.data_root))] = value
    return result


def _assert_owner_retained(app, client, session, token, owner, code="runtime_cleanup_required"):
    before = _data_snapshot(session)
    resources = tuple(getattr(session, name) for name in
                      ("session", "host_identity", "process", "lock_file", "log_file"))
    rejected = client.delete("/mcp", headers=_headers(token, owner))
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["error"]["code"] == code
    assert app._owner == owner and app._deleting is False
    competing = _initialize_response(client, token, request_id=99)
    assert competing.status_code == 409
    assert competing.json()["error"]["code"] == "owner_already_initialized"
    assert app._owner == owner
    assert _data_snapshot(session) == before, "DELETE must preserve original receipts and never replay input"
    assert resources == tuple(getattr(session, name) for name in
                              ("session", "host_identity", "process", "lock_file", "log_file"))


class _HarmlessProcess:
    """Only a local lifecycle result; no subprocess or OS process exists."""

    def __init__(self, alive=False):
        self.alive = alive

    def poll(self):
        return None if self.alive else 0

    def wait(self, timeout):
        return 0


def _set_session_directory(session):
    session.session = session.data_root / ("session-" + "a" * 32)
    session.session.mkdir(parents=True)
    return session.session


@pytest.mark.parametrize("resource", ["session", "host_identity", "process", "lock_file", "log_file"])
def test_any_real_runtime_resource_trace_prevents_cold_release(real_transport, monkeypatch, resource):
    app, client, session, token = real_transport
    owner = _initialize(client, token)
    if resource == "session":
        _set_session_directory(session)
    elif resource == "host_identity":
        import psutil

        session.host_identity = {"pid": 123, "created": 1.0}

        def absent_process(pid):
            raise psutil.NoSuchProcess(pid)

        monkeypatch.setattr(psutil, "Process", absent_process)
    elif resource == "process":
        session.process = _HarmlessProcess()
    else:
        session.data_root.mkdir()
        setattr(session, resource, (session.data_root / (resource + ".trace")).open("a+b"))
    status = session.status()
    assert status["host_alive"] is False and status["pending_ids"] == []
    assert status["cleanup_verified"] is False
    _assert_owner_retained(app, client, session, token, owner)


@pytest.mark.parametrize("entrypoint", ["start", "recover", "admission-recover", "launch"])
def test_failed_start_entrypoint_cannot_become_never_started_again(real_transport, entrypoint):
    app, client, session, token = real_transport
    owner = _initialize(client, token)
    if entrypoint == "start":
        with pytest.raises(InstantStartError, match="allow-local-input"):
            session.start()
    elif entrypoint == "recover":
        with pytest.raises(InstantStartError, match="allow-local-input"):
            session.recover_session("recover-once", "0" * 64)
    elif entrypoint == "admission-recover":
        from app.execution.session_epoch_admission import SessionEpochAdmission

        with pytest.raises(InstantStartError, match="allow-local-input"):
            SessionEpochAdmission(session).recover("recover-once", "0" * 64)
    else:
        with pytest.raises(ValueError, match="invalid or existing new session directory"):
            session._launch_session(SimpleNamespace(), session_name="invalid")
    assert all(getattr(session, name) is None for name in
               ("session", "host_identity", "process", "lock_file", "log_file"))
    assert session.status()["cleanup_verified"] is False
    assert session.stop()["cleanup_verified"] is False
    _assert_owner_retained(app, client, session, token, owner)


def test_unknown_process_construction_preserves_owner_and_original_launch(real_transport, monkeypatch):
    app, client, session, token = real_transport
    owner = _initialize(client, token)
    attempts = []

    def harmless_unknown_construction(*args, **kwargs):
        attempts.append(args)
        raise OSError("synthetic unknown process construction result")

    monkeypatch.setattr("app.instant_mcp.subprocess.Popen", harmless_unknown_construction)
    session.allow_local_input = True
    with pytest.raises(OSError, match="unknown process construction"):
        session.start()
    assert len(attempts) == 1 and session.process is None
    assert session.session is not None and session.log_file is not None
    assert session.status()["phase"] == "host_exited_without_cleanup_proof"
    assert session.stop()["cleanup_verified"] is False
    _assert_owner_retained(app, client, session, token, owner)
    assert len(attempts) == 1


_COMPLETE_REPORT = {"finished_at": "2026-10-28T00:00:00Z", "phase": "stopped",
                    "host_phase": "stopped", "cleanup_errors": [], "sampler_stopped": True}


@pytest.mark.parametrize("runtime_state", [
    "host-alive", "pending-input", "dead-no-report", "unfinished-report",
    "sampler-active", "cleanup-errors", "cleanup-pending", "host-phase-missing",
])
def test_real_runtime_cleanup_evidence_remains_required(real_transport, runtime_state):
    app, client, session, token = real_transport
    owner = _initialize(client, token)
    directory = _set_session_directory(session)
    report = dict(_COMPLETE_REPORT)
    if runtime_state == "host-alive":
        session.process = _HarmlessProcess(alive=True)
    elif runtime_state == "pending-input":
        (directory / "commands").mkdir()
        (directory / "commands" / "original-input.json").write_text(
            json.dumps({"kind": "capture"}), encoding="utf-8")
    elif runtime_state == "unfinished-report":
        report.pop("finished_at")
    elif runtime_state == "sampler-active":
        report["sampler_stopped"] = False
    elif runtime_state == "cleanup-errors":
        report["cleanup_errors"] = ["synthetic unresolved cleanup"]
    elif runtime_state == "cleanup-pending":
        report["phase"] = "cleanup_pending"
    elif runtime_state == "host-phase-missing":
        report.pop("host_phase")
    if runtime_state != "dead-no-report":
        (directory / "report.json").write_text(json.dumps(report), encoding="utf-8")
    status = session.status()
    if runtime_state == "pending-input":
        assert status["cleanup_verified"] is True
        assert status["pending_ids"] == ["original-input"]
    else:
        assert status["cleanup_verified"] is False
    _assert_owner_retained(app, client, session, token, owner)


def test_real_status_read_failure_cannot_release_owner(real_transport, monkeypatch):
    app, client, session, token = real_transport
    owner = _initialize(client, token)
    directory = _set_session_directory(session)
    (directory / "report.json").write_text("{}", encoding="utf-8")

    def failed_snapshot(path):
        raise OSError("synthetic status snapshot read failure")

    with monkeypatch.context() as patch:
        patch.setattr("app.core.instant_attachment_transport.read_json", failed_snapshot)
        _assert_owner_retained(app, client, session, token, owner)


def test_native_start_inflight_blocks_delete_without_replay(real_transport, monkeypatch):
    app, client, session, token = real_transport
    owner = _initialize(client, token)
    entered, release = Event(), Event()
    attempts = []
    original_configuration = session._startup_configuration

    def blocked_configuration():
        attempts.append("configuration")
        entered.set()
        assert release.wait(5), "test did not release harmless startup"
        return original_configuration()

    monkeypatch.setattr(session, "_startup_configuration", blocked_configuration)
    with ThreadPoolExecutor(max_workers=1) as pool:
        starting = pool.submit(_call, client, token, owner, "instant_start", {}, 10)
        try:
            assert entered.wait(2)
            _assert_owner_retained(app, client, session, token, owner, code="requests_inflight")
        finally:
            release.set()
        result = starting.result(timeout=3)
    assert result.status_code == 200 and result.json()["result"]["isError"] is True
    assert attempts == ["configuration"]
    _assert_owner_retained(app, client, session, token, owner)
    assert attempts == ["configuration"]


def test_delete_inflight_blocks_start_and_competing_owner(real_transport, monkeypatch):
    app, client, session, token = real_transport
    owner = _initialize(client, token)
    entered, release = Event(), Event()
    original_status = session.status
    status_reads = []

    def blocked_status():
        status_reads.append("read")
        entered.set()
        assert release.wait(5), "test did not release status evidence read"
        return original_status()

    with monkeypatch.context() as patch:
        patch.setattr(session, "status", blocked_status)
        with ThreadPoolExecutor(max_workers=1) as pool:
            deleting = pool.submit(client.delete, "/mcp", headers=_headers(token, owner))
            try:
                assert entered.wait(2)
                start = _call(client, token, owner, "instant_start", request_id=10)
                assert start.status_code == 409
                assert start.json()["error"]["code"] == "owner_transition_pending"
                competing = _initialize_response(client, token, request_id=11)
                assert competing.status_code == 409
                assert app._owner == owner
            finally:
                release.set()
            deleted = deleting.result(timeout=3)
    assert deleted.status_code == 200, deleted.text
    assert status_reads == ["read"] and app._owner is None
    assert all(getattr(session, name) is None for name in
               ("session", "host_identity", "process", "lock_file", "log_file"))
    new_owner = _initialize(client, token, request_id=12)
    assert new_owner != owner
    assert client.delete("/mcp", headers=_headers(token, new_owner)).status_code == 200


@pytest.mark.parametrize("failure", ["http-500", "exception"])
def test_native_delete_failure_keeps_original_owner_for_retry(real_transport, monkeypatch, failure):
    app, client, session, token = real_transport
    owner = _initialize(client, token)
    native = app._native_app
    deletes = []

    async def fail_first_native_delete(scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "DELETE":
            deletes.append(dict(scope["headers"])[b"mcp-session-id"].decode("ascii"))
            if len(deletes) == 1:
                if failure == "exception":
                    raise OSError("synthetic native DELETE failure")
                response = JSONResponse({"error": "synthetic native DELETE failure"}, status_code=500)
                await response(scope, receive, send)
                return
        await native(scope, receive, send)

    monkeypatch.setattr(app, "_native_app", fail_first_native_delete)
    if failure == "exception":
        with pytest.raises(OSError, match="synthetic native DELETE failure"):
            client.delete("/mcp", headers=_headers(token, owner))
    else:
        assert client.delete("/mcp", headers=_headers(token, owner)).status_code == 500
    assert app._owner == owner and app._deleting is False
    assert _initialize_response(client, token, request_id=10).status_code == 409
    original_status = _tool_value(_call(client, token, owner, "instant_status", request_id=11))
    assert original_status["host_alive"] is False and original_status["cleanup_verified"] is False
    assert client.delete("/mcp", headers=_headers(token, owner)).status_code == 200
    assert deletes == [owner, owner] and app._owner is None
    new_owner = _initialize(client, token, request_id=12)
    assert new_owner != owner
    assert client.delete("/mcp", headers=_headers(token, new_owner)).status_code == 200
    assert deletes == [owner, owner, new_owner]
    assert all(getattr(session, name) is None for name in
               ("session", "host_identity", "process", "lock_file", "log_file"))
    assert not session.data_root.exists()
