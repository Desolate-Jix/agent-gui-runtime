from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import socket
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest
from fastapi.testclient import TestClient

from app.agent_link.http_app import create_agent_link_app
from app.agent_link.service import AgentLinkService
from app.agent_link.store import AgentLinkStore
from app.desktop_review.connections import NativeConnectionError
from app.desktop_review.host import DesktopHostError, DesktopReviewHost
from tests.test_agent_link_inbox import _batch


REVIEWER = "shared-reviewer-secret"


def _post(url: str, token: str, payload: dict) -> tuple[int, dict]:
    request = Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def test_agent_only_factory_keeps_default_reviewer_compatibility(tmp_path):
    store = AgentLinkStore(tmp_path / "inbox.json")
    service = AgentLinkService(store, REVIEWER)
    try:
        agent_only = TestClient(
            create_agent_link_app(service, reviewer_http=False),
            client=("127.0.0.1", 50201),
        )
        assert agent_only.post(
            "/reviewer/list_connections",
            headers={"Authorization": "Bearer " + REVIEWER}, json={},
        ).status_code == 404
        compatible = TestClient(
            create_agent_link_app(service), client=("127.0.0.1", 50202)
        )
        assert compatible.post(
            "/reviewer/list_connections",
            headers={"Authorization": "Bearer " + REVIEWER}, json={},
        ).status_code == 200
    finally:
        store.close()


def test_shared_host_real_http_and_facade_use_one_owner_then_release(tmp_path):
    state, root = tmp_path / "inbox.json", tmp_path / "review"
    host = DesktopReviewHost(state, root, REVIEWER, port=0)
    try:
        assert host.status() == {
            "contract_version": "native_review_host_v1",
            "host_id": host.status()["host_id"], "phase": "created",
            "base_url": None, "staging_only": True,
        }
        ready = host.start()
        assert ready == host.status() and ready["phase"] == "ready"
        assert ready["base_url"].startswith("http://127.0.0.1:")
        connection = host.connections.create_connection("task-a", "synthetic")
        status, receipt = _post(
            ready["base_url"] + "/agent/submit_batch", connection["token"], _batch()
        )
        assert status == 200 and receipt["status"] == "pending_review_proposal"
        assert host.facade.list_batches()[0]["batch_id"] == "batch-a"
        assert host.facade.load_batch("task-a", "batch-a")["batch"]["title"]
        reviewer_status, _ = _post(
            ready["base_url"] + "/reviewer/list_connections", REVIEWER, {}
        )
        assert reviewer_status == 404
        port = int(ready["base_url"].rsplit(":", 1)[1])
    finally:
        host.close()
    assert host.status()["phase"] == "stopped" and host.status()["base_url"] is None
    with socket.socket() as probe:
        probe.settimeout(0.2)
        assert probe.connect_ex(("127.0.0.1", port)) != 0
    reopened_store = AgentLinkStore(state)
    try:
        from app.desktop_review.workspace import NativeReviewFacade
        reopened_facade = NativeReviewFacade(
            AgentLinkService(reopened_store, REVIEWER), REVIEWER, root
        )
        reopened_facade.close()
    finally:
        reopened_store.close()
    host.close()


def test_connection_survives_host_restart_until_explicit_revoke(tmp_path):
    state, root = tmp_path / "inbox.json", tmp_path / "review"
    first = DesktopReviewHost(state, root, REVIEWER)
    try:
        first_ready = first.start()
        grant = first.connections.create_connection("task-a", "restart fixture")
        first_id = first_ready["host_id"]
    finally:
        first.close()

    second = DesktopReviewHost(state, root, REVIEWER)
    try:
        second_ready = second.start()
        assert second_ready["host_id"] != first_id
        status, payload = _post(
            second_ready["base_url"] + "/agent/status", grant["token"], {}
        )
        assert status == 200 and payload["connection_id"] == grant["connection_id"]
        second.connections.revoke_connection(grant["connection_id"], "revoke-restart")
        status, payload = _post(
            second_ready["base_url"] + "/agent/status", grant["token"], {}
        )
        assert status == 400 and payload["error"]["code"] == "connection_revoked"
    finally:
        second.close()

    third = DesktopReviewHost(state, root, REVIEWER)
    try:
        third_ready = third.start()
        assert third.connections.list_connections()[0]["revoked"] is True
        status, payload = _post(
            third_ready["base_url"] + "/agent/status", grant["token"], {}
        )
        assert status == 400 and payload["error"]["code"] == "connection_revoked"
    finally:
        third.close()


def test_close_timeout_keeps_both_owners_until_inflight_write_drains(tmp_path, monkeypatch):
    state, root = tmp_path / "inbox.json", tmp_path / "review"
    host = DesktopReviewHost(state, root, REVIEWER, port=0)
    ready = host.start()
    port = int(ready["base_url"].rsplit(":", 1)[1])
    connection = host.connections.create_connection("task-a", "synthetic")
    entered, release = threading.Event(), threading.Event()
    original = host._store._write_state

    def blocked_write(value):
        entered.set()
        assert release.wait(5)
        original(value)

    monkeypatch.setattr(host._store, "_write_state", blocked_write)
    result: list[tuple[int, dict]] = []
    request_thread = threading.Thread(
        target=lambda: result.append(_post(
            ready["base_url"] + "/agent/submit_batch",
            connection["token"], _batch(),
        )),
        name="owned-test-http-request",
    )
    request_thread.start()
    try:
        assert entered.wait(3)
        with pytest.raises(DesktopHostError) as failure:
            host.close(timeout=0.05)
        assert failure.value.code == "shutdown_timeout"
        assert host.status()["phase"] == "stopping"
        with socket.socket() as probe:
            probe.settimeout(0.5)
            assert probe.connect_ex(("127.0.0.1", port)) != 0
        with pytest.raises(NativeConnectionError) as no_mint:
            host.connections.create_connection("task-b", "must-not-mint")
        assert getattr(no_mint.value, "code", None) == "host_not_ready"
        with pytest.raises(NativeConnectionError) as no_revoke:
            host.connections.revoke_connection(connection["connection_id"], "must-not-revoke")
        assert getattr(no_revoke.value, "code", None) == "host_not_ready"
        with pytest.raises(Exception, match="owner|占用|in use"):
            AgentLinkStore(state)
        from app.desktop_review.workspace import DesktopReviewError, NativeReviewFacade
        with pytest.raises(DesktopReviewError, match="占用"):
            NativeReviewFacade(
                type("Service", (), {"reviewer_call": lambda *_: {}})(), REVIEWER, root
            )
    finally:
        release.set()
        request_thread.join(5)
        host.close(timeout=5)
    assert not request_thread.is_alive() and result[0][0] == 200
    reopened = AgentLinkStore(state)
    try:
        snapshot = reopened.snapshot()
        assert list(snapshot["batches"]) == ["batch-a"]
        assert len(snapshot["connections"]) == 1
    finally:
        reopened.close()


def test_bind_failure_cleans_store_and_workspace_owners(tmp_path):
    port = _free_port()
    listener = socket.socket()
    listener.bind(("127.0.0.1", port))
    listener.listen(1)
    state, root = tmp_path / "inbox.json", tmp_path / "review"
    host = DesktopReviewHost(state, root, REVIEWER, port=port)
    try:
        with pytest.raises(DesktopHostError) as failure:
            host.start(timeout=1)
        assert failure.value.code == "bind_failed"
        assert host.status()["phase"] == "failed"
        reopened = AgentLinkStore(state)
        reopened.close()
        from app.desktop_review.workspace import NativeReviewFacade
        temporary = AgentLinkStore(state)
        try:
            facade = NativeReviewFacade(
                AgentLinkService(temporary, REVIEWER), REVIEWER, root
            )
            facade.close()
        finally:
            temporary.close()
    finally:
        listener.close()
        host.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows exclusive bind contract")
def test_windows_owned_listener_rejects_reuseaddr_hijack_and_reopens_after_close(tmp_path):
    host = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", REVIEWER)
    try:
        ready = host.start()
        port = int(ready["base_url"].rsplit(":", 1)[1])
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as contender:
            contender.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            with pytest.raises(OSError):
                contender.bind(("127.0.0.1", port))
    finally:
        host.close()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as reopened:
        reopened.bind(("127.0.0.1", port))


def test_start_setup_failure_closes_listener_and_releases_both_owners(tmp_path, monkeypatch):
    state, root = tmp_path / "inbox.json", tmp_path / "review"
    host = DesktopReviewHost(state, root, REVIEWER)
    monkeypatch.setattr(
        "app.agent_link.host.create_agent_link_app",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("private setup")),
    )
    try:
        with pytest.raises(DesktopHostError) as failure:
            host.start(timeout=1)
        assert failure.value.code == "startup_failed"
        assert "private setup" not in str(failure.value)
        assert host.status()["phase"] == "failed"
        reopened = AgentLinkStore(state)
        try:
            from app.desktop_review.workspace import NativeReviewFacade
            facade = NativeReviewFacade(
                AgentLinkService(reopened, REVIEWER), REVIEWER, root
            )
            facade.close()
        finally:
            reopened.close()
    finally:
        if not host._resources_closed:
            host._http._close_listener()
            host.facade.close()
            host._store.close()


def test_server_thread_failure_closes_event_loop_and_releases_owners(tmp_path, monkeypatch):
    loops = []
    original_loop = asyncio.new_event_loop

    class FailedServer:
        def __init__(self, _config):
            self.started = False
            self.should_exit = False
            self.servers = []

        async def serve(self, *, sockets):
            del sockets
            raise RuntimeError("private server failure")

    def captured_loop():
        loop = original_loop()
        loops.append(loop)
        return loop

    monkeypatch.setattr("app.agent_link.host.uvicorn.Server", FailedServer)
    monkeypatch.setattr("app.agent_link.host.asyncio.new_event_loop", captured_loop)
    state, root = tmp_path / "inbox.json", tmp_path / "review"
    host = DesktopReviewHost(state, root, REVIEWER)
    try:
        with pytest.raises(DesktopHostError) as failure:
            host.start(timeout=1)
        assert failure.value.code == "startup_failed"
        assert "private server failure" not in str(failure.value)
        assert loops and loops[0].is_closed()
        reopened = AgentLinkStore(state)
        reopened.close()
    finally:
        host.close()


def test_post_ready_server_failure_disables_status_and_mint_until_explicit_close(
    tmp_path, monkeypatch,
):
    fail_server = threading.Event()

    class FailedAfterReadyServer:
        def __init__(self, _config):
            self.started = True
            self.should_exit = False
            self.servers = []

        async def serve(self, *, sockets):
            del sockets
            while not fail_server.is_set():
                await asyncio.sleep(0.01)
            raise RuntimeError("private post-ready failure")

    monkeypatch.setattr("app.agent_link.host.uvicorn.Server", FailedAfterReadyServer)
    state, root = tmp_path / "inbox.json", tmp_path / "review"
    host = DesktopReviewHost(state, root, REVIEWER)
    try:
        assert host.start()["phase"] == "ready"
        fail_server.set()
        host._http._thread.join(3)
        assert not host._http._thread.is_alive()
        with pytest.raises(DesktopHostError) as no_cached_restart:
            host.start()
        assert no_cached_restart.value.code == "invalid_phase"
        assert host.status()["phase"] == "failed"
        assert host.status()["base_url"] is None
        with pytest.raises(NativeConnectionError) as no_mint:
            host.connections.create_connection("task-a", "must-not-mint")
        assert no_mint.value.code == "host_not_ready"
        with pytest.raises(NativeConnectionError) as no_revoke:
            host.connections.revoke_connection("connection-none", "must-not-revoke")
        assert no_revoke.value.code == "host_not_ready"
        assert host._store.snapshot()["connections"] == {}
        with pytest.raises(Exception, match="owner|in use"):
            AgentLinkStore(state)
        from app.desktop_review.workspace import DesktopReviewError, NativeReviewFacade
        with pytest.raises(DesktopReviewError, match="占用"):
            NativeReviewFacade(
                type("Service", (), {"reviewer_call": lambda *_: {}})(), REVIEWER, root
            )
    finally:
        fail_server.set()
        host.close()
    reopened = AgentLinkStore(state)
    try:
        from app.desktop_review.workspace import NativeReviewFacade
        facade = NativeReviewFacade(
            AgentLinkService(reopened, REVIEWER), REVIEWER, root
        )
        facade.close()
    finally:
        reopened.close()


def test_duplicate_and_concurrent_start_reuse_one_owned_listener(tmp_path, monkeypatch):
    host = DesktopReviewHost(
        tmp_path / "inbox.json", tmp_path / "review", REVIEWER, port=0
    )
    entered, release = threading.Event(), threading.Event()
    results: list[dict] = []
    failures: list[BaseException] = []
    original_start = host._http.start

    def blocked_start(*, timeout):
        entered.set()
        assert release.wait(3)
        return original_start(timeout=timeout)

    monkeypatch.setattr(host._http, "start", blocked_start)

    def start() -> None:
        try:
            results.append(host.start(timeout=5))
        except BaseException as error:
            failures.append(error)

    thread = threading.Thread(target=start, name="owned-start")
    thread.start()
    try:
        assert entered.wait(3)
        with pytest.raises(DesktopHostError) as concurrent:
            host.start(timeout=5)
        assert concurrent.value.code == "lifecycle_busy"
        release.set()
        thread.join(6)
        assert not thread.is_alive()
        assert len(results) == 1 and failures == []
        assert results[0] == host.start()
        assert host._http._thread is not None and host._http._thread.is_alive()
        assert sum(
            thread.name == host._http._thread.name and thread.is_alive()
            for thread in threading.enumerate()
        ) == 1
    finally:
        release.set()
        thread.join(6)
        host.close()
    host.close()
    with pytest.raises(DesktopHostError) as stopped_start:
        host.start()
    assert stopped_start.value.code == "invalid_phase"


def test_start_timeout_keeps_owners_until_owned_thread_is_terminal(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()

    class BlockedServer:
        def __init__(self, _config):
            self.started = False
            self.should_exit = False
            self.servers = []

        async def serve(self, *, sockets):
            del sockets
            entered.set()
            while not release.is_set():
                await asyncio.sleep(0.01)

    monkeypatch.setattr("app.agent_link.host.uvicorn.Server", BlockedServer)
    state, root = tmp_path / "inbox.json", tmp_path / "review"
    host = DesktopReviewHost(state, root, REVIEWER)
    try:
        with pytest.raises(DesktopHostError) as failure:
            host.start(timeout=0.03)
        assert entered.is_set()
        assert failure.value.code == "startup_timeout"
        assert host.status()["phase"] == "stopping"
        with pytest.raises(Exception, match="owner|in use"):
            AgentLinkStore(state)
        from app.desktop_review.workspace import DesktopReviewError, NativeReviewFacade
        with pytest.raises(DesktopReviewError, match="占用"):
            NativeReviewFacade(
                type("Service", (), {"reviewer_call": lambda *_: {}})(), REVIEWER, root
            )
    finally:
        release.set()
        host.close(timeout=5)
    reopened = AgentLinkStore(state)
    try:
        facade = NativeReviewFacade(
            AgentLinkService(reopened, REVIEWER), REVIEWER, root
        )
        facade.close()
    finally:
        reopened.close()


@pytest.mark.parametrize("timeout", [True, 0, -1, "1", float("nan"), float("inf")])
def test_invalid_start_timeout_has_no_lifecycle_side_effect(tmp_path, timeout):
    host = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", REVIEWER)
    try:
        with pytest.raises(DesktopHostError) as failure:
            host.start(timeout=timeout)
        assert failure.value.code == "invalid_timeout"
        assert host.status()["phase"] == "created"
    finally:
        host.close()


def test_official_mcp_bridge_uses_owned_host_without_reviewer_environment(tmp_path):
    mcp = pytest.importorskip("mcp")
    host = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", REVIEWER)
    try:
        ready = host.start()
        grant = host.connections.create_connection("task-a", "sdk-fixture")
        environment = {
            key: value for key, value in os.environ.items()
            if key.upper() in {"PATH", "SYSTEMROOT", "TEMP", "TMP", "WINDIR"}
        }
        environment.update({
            "AGENT_LINK_BASE_URL": ready["base_url"],
            "AGENT_LINK_TOKEN": grant["token"], "PYTHONIOENCODING": "utf-8",
        })
        assert "AGENT_LINK_REVIEWER_TOKEN" not in environment
        parameters = mcp.StdioServerParameters(
            command=sys.executable, args=["scripts/start_agent_link_mcp.py"],
            env=environment, cwd=Path.cwd(),
        )

        async def exercise() -> None:
            async with mcp.Client(parameters) as client:
                status = await client.call_tool("agent_link_status", {})
                assert json.loads(status.content[0].text)["staging_only"] is True
                submitted = await client.call_tool("submit_learning_batch", {"batch": _batch()})
                assert json.loads(submitted.content[0].text)["status"] == "pending_review_proposal"
                original = host.facade.load_batch("task-a", "batch-a")
                host.facade.save_revision("task-a", "batch-a", 0, original["batch"])
                view = host.facade.request_relearn(
                    "task-a", "batch-a", 1, 0,
                    {"interface_ids": ["interface-list"], "relationship_ids": ["rel-a"]},
                    "复核", "request",
                )
                issue = view["issues"][0]
                feedback = await client.call_tool(
                    "read_learning_feedback", {"batch_id": "batch-a"}
                )
                assert json.loads(feedback.content[0].text)["revision"] == 1
                candidate = {
                    "contract_version": "agent_link_v1", "idempotency_key": "candidate",
                    "batch_id": "batch-a", "issue_id": issue["issue_id"],
                    "baseline_revision": 1,
                    "review_baseline_sha256": issue["review_baseline_sha256"],
                    "scope": issue["scope"], "changes": [{
                        "change_type": "geometry", "region_id": "region-row",
                        "bbox": [0.0, 0.0, 15.0, 11.0],
                    }],
                }
                receipt = await client.call_tool(
                    "submit_relearning_candidate", {"candidate": candidate}
                )
                assert json.loads(receipt.content[0].text)["status"] == "pending_review_proposal"

        asyncio.run(exercise())
    finally:
        host.close(timeout=5)
    assert host.status()["phase"] == "stopped"
