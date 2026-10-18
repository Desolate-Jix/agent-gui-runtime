from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
from threading import Event, Thread
from types import ModuleType

import pytest
from fastapi.testclient import TestClient

from app.agent_link import mcp_bridge
from app.agent_link.contracts import AgentLinkError
from app.agent_link.http_app import create_agent_link_app
from app.agent_link.host import OwnedAgentLinkHttpHost
from app.agent_link.service import AgentLinkService
from app.agent_link.store import AgentLinkStore
from app.desktop_review.host import DesktopReviewHost
from test_formal_graph_exact_review import TOKEN as GRAPH_REVIEWER
from test_formal_agent_memory_reuse import _published_pair


REVIEWER = "formal-memory-reviewer-token"
WORKFLOW_A = "workflow-" + "a" * 64
WORKFLOW_B = "workflow-" + "b" * 64
WORKFLOW_C = "workflow-" + "c" * 64
MEMORY_CAPABILITY = {
    "contract_version": "agent_workflow_memory_v1",
    "operations": ["search_workflow_memory", "get_workflow_memory"],
}


class Reader:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def search_workflow_memory(self, allowed, application_scope, query="", cursor=None):
        self.calls.append(("search", deepcopy(allowed), deepcopy(application_scope), query, cursor))
        return {
            "contract_version": "agent_workflow_memory_v1",
            "items": [{"workflow_id": item} for item in allowed],
            "next_cursor": None,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "requires_current_grounding": True,
        }

    def get_workflow_memory(self, allowed, workflow_id, version=None):
        self.calls.append(("get", deepcopy(allowed), workflow_id, version))
        if workflow_id not in allowed:
            raise AssertionError("service must reject an ID outside its captured grant")
        return {
            "contract_version": "agent_workflow_memory_v1",
            "workflow_id": workflow_id,
            "selected_version": version or "current",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "requires_current_grounding": True,
        }


def _connection(service: AgentLinkService, name: str = "memory-agent") -> dict:
    return service.reviewer_call(REVIEWER, "create_connection", {
        "task_id": "formal-memory-task", "agent_name": name,
    })


def _grant(service: AgentLinkService, connection_id: str, workflows: list[str], *,
           revision: int = 0, key: str = "memory-scope-key") -> dict:
    return service.reviewer_call(REVIEWER, "set_workflow_memory_scope", {
        "connection_id": connection_id,
        "expected_revision": revision,
        "workflow_ids": workflows,
        "idempotency_key": key,
    })


def test_default_connection_has_only_legacy_capabilities_and_memory_is_forbidden(tmp_path: Path) -> None:
    store = AgentLinkStore(tmp_path / "memory-default.json")
    service = AgentLinkService(store, REVIEWER)
    reader = Reader()
    service.bind_workflow_memory_reader(REVIEWER, reader)
    connection = _connection(service)
    try:
        status = service.agent_call(connection["token"], "status", {})
        assert status["capabilities"] == ["read_feedback", "status", "submit_batch", "submit_candidate"]
        assert "workflow_memory" not in status
        for operation, arguments in (
            ("search_workflow_memory", {"application_scope": {"application_id": "app-a"}}),
            ("get_workflow_memory", {"workflow_id": WORKFLOW_A}),
        ):
            with pytest.raises(AgentLinkError) as failure:
                service.agent_call(connection["token"], operation, arguments)
            assert failure.value.code == "operation_forbidden"
        assert reader.calls == []
        _grant(service, connection["connection_id"], [], key="empty-memory-scope")
        assert "workflow_memory" not in service.agent_call(connection["token"], "status", {})
        with pytest.raises(AgentLinkError) as empty:
            service.agent_call(connection["token"], "search_workflow_memory", {"application_scope": {}})
        assert empty.value.code == "operation_forbidden"
    finally:
        store.close()


def test_explicit_scope_exposes_reads_and_caller_selects_one_allowed_workflow(tmp_path: Path) -> None:
    store = AgentLinkStore(tmp_path / "memory-allowed.json")
    service = AgentLinkService(store, REVIEWER)
    reader = Reader()
    service.bind_workflow_memory_reader(REVIEWER, reader)
    first, other = _connection(service), _connection(service, "other-memory-agent")
    try:
        receipt = _grant(service, first["connection_id"], [WORKFLOW_A, WORKFLOW_B])
        assert receipt == {
            "contract_version": "agent_link_v1",
            "connection_id": first["connection_id"],
            "revision": 1,
            "status": "memory_scope_updated",
            "staging_only": True,
        }
        status = service.agent_call(first["token"], "status", {})
        assert status["workflow_memory"] == MEMORY_CAPABILITY
        assert status["capabilities"] == ["read_feedback", "status", "submit_batch", "submit_candidate"]
        search = service.agent_call(first["token"], "search_workflow_memory", {
            "application_scope": {"application_id": "app-a"},
            "query": "invoice", "cursor": None,
        })
        assert [item["workflow_id"] for item in search["items"]] == [WORKFLOW_A, WORKFLOW_B]
        detail = service.agent_call(first["token"], "get_workflow_memory", {
            "workflow_id": WORKFLOW_B, "version": "version-2",
        })
        assert detail["workflow_id"] == WORKFLOW_B
        assert reader.calls == [
            ("search", [WORKFLOW_A, WORKFLOW_B], {"application_id": "app-a"}, "invoice", None),
            ("get", [WORKFLOW_A, WORKFLOW_B], WORKFLOW_B, "version-2"),
        ]
        with pytest.raises(AgentLinkError) as outside:
            service.agent_call(first["token"], "get_workflow_memory", {"workflow_id": WORKFLOW_C})
        assert outside.value.code == "not_found"
        with pytest.raises(AgentLinkError) as denied:
            service.agent_call(other["token"], "get_workflow_memory", {"workflow_id": WORKFLOW_A})
        assert denied.value.code == "operation_forbidden"
        assert len(reader.calls) == 2
    finally:
        store.close()


def test_scope_is_strict_idempotent_and_survives_restart_without_changing_legacy_shape(tmp_path: Path) -> None:
    path = tmp_path / "memory-restart.json"
    store = AgentLinkStore(path)
    service = AgentLinkService(store, REVIEWER)
    connection = _connection(service)
    request = {
        "connection_id": connection["connection_id"], "expected_revision": 0,
        "workflow_ids": [WORKFLOW_A, WORKFLOW_B], "idempotency_key": "restart-key",
    }
    receipt = service.reviewer_call(REVIEWER, "set_workflow_memory_scope", request)
    assert service.reviewer_call(REVIEWER, "set_workflow_memory_scope", deepcopy(request)) == receipt
    with pytest.raises(AgentLinkError) as conflict:
        service.reviewer_call(REVIEWER, "set_workflow_memory_scope", {
            **request, "workflow_ids": [WORKFLOW_A],
        })
    assert conflict.value.code == "idempotency_conflict"
    with pytest.raises(AgentLinkError) as stale:
        _grant(service, connection["connection_id"], [], revision=0, key="stale-key")
    assert stale.value.code == "stale_revision"
    for invalid in ([WORKFLOW_B, WORKFLOW_A], [WORKFLOW_A, WORKFLOW_A], ["workflow-x"]):
        with pytest.raises(AgentLinkError) as malformed:
            _grant(service, connection["connection_id"], invalid, revision=1, key="bad-" + str(len(invalid)))
        assert malformed.value.code == "invalid_arguments"
    snapshot = store.snapshot()
    assert "memory_scope" in snapshot["connections"][connection["connection_id"]]
    legacy = _connection(service, "legacy-shape")
    assert "memory_scope" not in store.snapshot()["connections"][legacy["connection_id"]]
    store.close()

    reopened = AgentLinkStore(path)
    restarted = AgentLinkService(reopened, REVIEWER)
    restarted.bind_workflow_memory_reader(REVIEWER, Reader())
    try:
        assert restarted.reviewer_call(REVIEWER, "set_workflow_memory_scope", request) == receipt
        assert restarted.agent_call(connection["token"], "status", {})["workflow_memory"] == MEMORY_CAPABILITY
    finally:
        reopened.close()


@pytest.mark.parametrize("damage", ["scope", "receipt"])
def test_restart_strictly_rejects_damaged_memory_scope_and_receipt(tmp_path: Path, damage: str) -> None:
    path = tmp_path / f"memory-corrupt-{damage}.json"
    store = AgentLinkStore(path)
    service = AgentLinkService(store, REVIEWER)
    connection = _connection(service)
    _grant(service, connection["connection_id"], [WORKFLOW_A, WORKFLOW_B])
    store.close()
    payload = json.loads(path.read_text(encoding="utf-8"))
    if damage == "scope":
        payload["connections"][connection["connection_id"]]["memory_scope"]["workflow_ids"].reverse()
    else:
        ledger = "reviewer:set_workflow_memory_scope:memory-scope-key"
        payload["idempotency"][ledger]["receipt"]["status"] = "unexpected"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(AgentLinkError) as failure:
        AgentLinkStore(path)
    assert failure.value.code == "corrupt_store"


@pytest.mark.parametrize("change", ["revoke", "scope"])
def test_concurrent_revoke_or_scope_change_rejects_inflight_result(tmp_path: Path, change: str) -> None:
    entered, release = Event(), Event()

    class BlockingReader(Reader):
        def get_workflow_memory(self, allowed, workflow_id, version=None):
            entered.set()
            assert release.wait(3)
            return super().get_workflow_memory(allowed, workflow_id, version)

    store = AgentLinkStore(tmp_path / f"memory-race-{change}.json")
    service = AgentLinkService(store, REVIEWER)
    service.bind_workflow_memory_reader(REVIEWER, BlockingReader())
    connection = _connection(service)
    _grant(service, connection["connection_id"], [WORKFLOW_A])
    observed: list[object] = []

    def read() -> None:
        try:
            observed.append(service.agent_call(
                connection["token"], "get_workflow_memory", {"workflow_id": WORKFLOW_A},
            ))
        except BaseException as error:
            observed.append(error)

    worker = Thread(target=read)
    try:
        worker.start()
        assert entered.wait(3)
        if change == "revoke":
            service.reviewer_call(REVIEWER, "revoke_connection", {
                "connection_id": connection["connection_id"], "idempotency_key": "race-revoke",
            })
        else:
            _grant(service, connection["connection_id"], [WORKFLOW_B], revision=1, key="race-scope")
        release.set()
        worker.join(3)
        assert not worker.is_alive()
        assert len(observed) == 1 and isinstance(observed[0], AgentLinkError)
        assert observed[0].code in {"connection_revoked", "stale_revision"}
    finally:
        release.set()
        worker.join(3)
        store.close()


def test_loopback_memory_error_preserves_safe_code_after_grant_changes(tmp_path: Path) -> None:
    entered, release = Event(), Event()

    class BlockingReader(Reader):
        def get_workflow_memory(self, allowed, workflow_id, version=None):
            entered.set()
            assert release.wait(3)
            return super().get_workflow_memory(allowed, workflow_id, version)

    store = AgentLinkStore(tmp_path / "memory-http-race.json")
    service = AgentLinkService(store, REVIEWER)
    service.bind_workflow_memory_reader(REVIEWER, BlockingReader())
    connection = _connection(service)
    _grant(service, connection["connection_id"], [WORKFLOW_A])
    host = OwnedAgentLinkHttpHost(service)
    observed: list[object] = []

    def read() -> None:
        try:
            observed.append(mcp_bridge._call(
                host.base_url, connection["token"], "get_workflow_memory", {"workflow_id": WORKFLOW_A},
            ))
        except BaseException as error:
            observed.append(error)

    worker = Thread(target=read)
    try:
        host.start()
        worker.start()
        assert entered.wait(3)
        _grant(service, connection["connection_id"], [WORKFLOW_B], revision=1, key="http-race-scope")
        release.set()
        worker.join(3)
        assert not worker.is_alive()
        assert len(observed) == 1 and isinstance(observed[0], mcp_bridge.AgentLinkMemoryError)
        assert observed[0].code == "stale_revision"
    finally:
        release.set()
        worker.join(3)
        host.close()
        store.close()


def test_http_cannot_grant_scope_and_agent_arguments_cannot_supply_allowed_ids(tmp_path: Path) -> None:
    store = AgentLinkStore(tmp_path / "memory-http.json")
    service = AgentLinkService(store, REVIEWER)
    service.bind_workflow_memory_reader(REVIEWER, Reader())
    connection = _connection(service)
    _grant(service, connection["connection_id"], [WORKFLOW_A])
    client = TestClient(create_agent_link_app(service), client=("127.0.0.1", 50261))
    try:
        grant_attempt = client.post(
            "/reviewer/set_workflow_memory_scope",
            headers={"Authorization": "Bearer " + REVIEWER},
            json={"connection_id": connection["connection_id"], "expected_revision": 1,
                  "workflow_ids": [], "idempotency_key": "http-grant"},
        )
        assert grant_attempt.status_code == 404
        assert grant_attempt.json()["error"]["code"] == "operation_not_found"
        injected = client.post(
            "/agent/search_workflow_memory",
            headers={"Authorization": "Bearer " + connection["token"]},
            json={"application_scope": {"application_id": "app-a"},
                  "allowed_workflow_ids": [WORKFLOW_C]},
        )
        assert injected.status_code == 400
        assert injected.json()["error"]["code"] == "invalid_arguments"
    finally:
        store.close()


@pytest.mark.parametrize("invalid_value", [float("nan"), object()])
def test_non_json_reader_result_is_safely_rejected(tmp_path: Path, invalid_value: object) -> None:
    class InvalidReader(Reader):
        def get_workflow_memory(self, allowed, workflow_id, version=None):
            result = super().get_workflow_memory(allowed, workflow_id, version)
            result["invalid_value"] = invalid_value
            return result

    store = AgentLinkStore(tmp_path / "memory-invalid-result.json")
    service = AgentLinkService(store, REVIEWER)
    service.bind_workflow_memory_reader(REVIEWER, InvalidReader())
    connection = _connection(service)
    _grant(service, connection["connection_id"], [WORKFLOW_A])
    try:
        with pytest.raises(AgentLinkError) as failure:
            service.agent_call(connection["token"], "get_workflow_memory", {"workflow_id": WORKFLOW_A})
        assert failure.value.code == "memory_source_unavailable"
        assert str(invalid_value) not in failure.value.message
    finally:
        store.close()


@pytest.mark.parametrize(
    "code",
    ["invalid_arguments", "not_found", "memory_source_unavailable", "stale_revision", "memory_too_large"],
)
def test_known_reader_errors_keep_only_safe_codes_and_messages(tmp_path: Path, code: str) -> None:
    from app.desktop_review.workflow_memory import WorkflowMemoryError

    class FailingReader(Reader):
        def search_workflow_memory(self, allowed, application_scope, query="", cursor=None):
            raise WorkflowMemoryError(code) from RuntimeError("private path D:/secret/workflow.json")

    store = AgentLinkStore(tmp_path / f"memory-error-{code}.json")
    service = AgentLinkService(store, REVIEWER)
    service.bind_workflow_memory_reader(REVIEWER, FailingReader())
    connection = _connection(service)
    _grant(service, connection["connection_id"], [WORKFLOW_A])
    try:
        with pytest.raises(AgentLinkError) as failure:
            service.agent_call(connection["token"], "search_workflow_memory", {"application_scope": {}})
        assert failure.value.code == code
        assert "D:/secret" not in failure.value.message
        assert failure.value.message in {
            "workflow memory request is invalid", "workflow memory was not found",
            "workflow memory source is unavailable", "workflow memory revision is stale",
            "workflow memory response exceeds limit",
        }
    finally:
        store.close()


def test_mcp_registers_memory_tools_only_for_exact_advertised_capability(monkeypatch) -> None:
    registered: dict[str, object] = {}

    class FakeServer:
        def __init__(self, **_: object) -> None:
            pass

        def add_tool(self, function, *, name: str, description: str) -> None:
            assert description
            registered[name] = function

        def run(self, *, transport: str) -> None:
            assert transport == "stdio"

    fake_mcp, fake_server = ModuleType("mcp"), ModuleType("mcp.server")
    fake_server.MCPServer = FakeServer
    monkeypatch.setitem(sys.modules, "mcp", fake_mcp)
    monkeypatch.setitem(sys.modules, "mcp.server", fake_server)
    monkeypatch.delenv("AGENT_LINK_ARTIFACT_BUNDLE", raising=False)
    monkeypatch.setattr(mcp_bridge, "_configuration", lambda: ("http://127.0.0.1:1234", "a" * 32))
    calls: list[tuple[str, dict]] = []

    def backend(_url: str, _token: str, operation: str, arguments: dict) -> dict:
        calls.append((operation, deepcopy(arguments)))
        if operation == "status":
            return {"contract_version": "agent_link_v1", "workflow_memory": deepcopy(MEMORY_CAPABILITY)}
        return {"contract_version": "agent_workflow_memory_v1"}

    monkeypatch.setattr(mcp_bridge, "_call", backend)
    mcp_bridge.run_stdio()
    assert set(registered) == {
        "agent_link_status", "submit_learning_batch", "read_learning_feedback",
        "submit_relearning_candidate", "search_workflow_memory", "get_workflow_memory",
    }
    registered["search_workflow_memory"]({"application_id": "app-a"}, "needle", "cursor-a")
    registered["get_workflow_memory"](WORKFLOW_B, "version-2")
    assert calls[-2:] == [
        ("search_workflow_memory", {
            "application_scope": {"application_id": "app-a"}, "query": "needle", "cursor": "cursor-a",
        }),
        ("get_workflow_memory", {"workflow_id": WORKFLOW_B, "version": "version-2"}),
    ]

    registered.clear()
    monkeypatch.setattr(mcp_bridge, "_call", lambda *_: {
        "workflow_memory": {"contract_version": "wrong", "operations": MEMORY_CAPABILITY["operations"]},
    })
    with pytest.raises(RuntimeError, match="workflow-memory capability is invalid"):
        mcp_bridge.run_stdio()


def test_desktop_host_binds_reader_after_facade_creation(tmp_path: Path) -> None:
    host = DesktopReviewHost(
        tmp_path / "host-inbox.json", tmp_path / "host-review", REVIEWER, port=0,
    )
    try:
        base_url = host.start()["base_url"]
        connection = host.connections.create_connection("host-memory-task", "host-memory-agent")
        host.facade._service.reviewer_call(REVIEWER, "set_workflow_memory_scope", {
            "connection_id": connection["connection_id"], "expected_revision": 0,
            "workflow_ids": [WORKFLOW_A], "idempotency_key": "host-memory-scope",
        })
        assert mcp_bridge._call(base_url, connection["token"], "status", {})["workflow_memory"] == MEMORY_CAPABILITY
    finally:
        host.close()


def test_real_published_memory_round_trips_over_loopback_without_paths_or_authority(
    tmp_path: Path, monkeypatch,
) -> None:
    inbox, facade, x, _, y, second = _published_pair(tmp_path)
    service = facade._service
    service.bind_workflow_memory_reader(GRAPH_REVIEWER, facade)
    connection = service.reviewer_call(GRAPH_REVIEWER, "create_connection", {
        "task_id": "formal-memory-task", "agent_name": "real-memory-agent",
    })
    allowed = sorted([x["logical_workflow_id"], y["logical_workflow_id"]])
    service.reviewer_call(GRAPH_REVIEWER, "set_workflow_memory_scope", {
        "connection_id": connection["connection_id"], "expected_revision": 0,
        "workflow_ids": allowed, "idempotency_key": "real-memory-scope",
    })
    host = OwnedAgentLinkHttpHost(service)
    try:
        base_url = host.start()
        search = mcp_bridge._call(base_url, connection["token"], "search_workflow_memory", {
            "application_scope": {}, "query": "", "cursor": None,
        })
        assert {item["workflow_id"] for item in search["items"]} == set(allowed)
        registered: dict[str, object] = {}

        class FakeServer:
            def __init__(self, **_: object) -> None:
                pass

            def add_tool(self, function, *, name: str, description: str) -> None:
                assert description
                registered[name] = function

            def run(self, *, transport: str) -> None:
                assert transport == "stdio"

        fake_mcp, fake_server = ModuleType("mcp"), ModuleType("mcp.server")
        fake_server.MCPServer = FakeServer
        monkeypatch.setitem(sys.modules, "mcp", fake_mcp)
        monkeypatch.setitem(sys.modules, "mcp.server", fake_server)
        monkeypatch.setenv("AGENT_LINK_BASE_URL", base_url)
        monkeypatch.setenv("AGENT_LINK_TOKEN", connection["token"])
        monkeypatch.delenv("AGENT_LINK_ARTIFACT_BUNDLE", raising=False)
        mcp_bridge.run_stdio()
        selected = registered["get_workflow_memory"](y["logical_workflow_id"], second["version_id"])
        assert selected["workflow_id"] == y["logical_workflow_id"]
        assert selected["version_id"] == second["version_id"]
        assert selected["artifact_is_authorization"] is False
        assert selected["execute_binding_enabled"] is False
        assert selected["requires_current_grounding"] is True
        encoded = json.dumps(selected, ensure_ascii=False)
        assert "png_base64" not in encoded and str(tmp_path) not in encoded
        source = tmp_path / "fresh-artifacts" / y["source_refs"]["original_batch_path"]
        source.write_bytes(source.read_bytes() + b"damaged")
        with pytest.raises(mcp_bridge.AgentLinkMemoryError) as damaged:
            mcp_bridge._call(base_url, connection["token"], "get_workflow_memory", {
                "workflow_id": y["logical_workflow_id"], "version": second["version_id"],
            })
        assert damaged.value.code == "memory_source_unavailable"
    finally:
        host.close()
        facade.close()
        inbox.close()
