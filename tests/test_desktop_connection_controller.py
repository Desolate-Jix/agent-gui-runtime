from __future__ import annotations

import copy

import pytest

from app.agent_link.contracts import AgentLinkError
from app.desktop_review.connections import (
    NativeConnectionController,
    NativeConnectionError,
)
from app.desktop_review.host import DesktopHostError, DesktopReviewHost


REVIEWER = "connection-reviewer-secret"


def test_connection_controller_create_list_revoke_and_stopped_rejection(tmp_path):
    host = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", REVIEWER)
    try:
        assert host.connections.host_status() == host.status()
        with pytest.raises(NativeConnectionError) as not_ready:
            host.connections.create_connection("task-a", "Agent display")
        assert not_ready.value.code == "host_not_ready"
        host.start()
        grant = host.connections.create_connection("task-a", "Agent display")
        assert set(grant) == {
            "contract_version", "connection_id", "task_id", "agent_name", "token",
            "staging_only",
        }
        assert grant["task_id"] == "task-a" and grant["agent_name"] == "Agent display"
        assert grant["token"].isascii() and 16 <= len(grant["token"]) <= 512
        listed = host.connections.list_connections()
        assert listed == [{
            "connection_id": grant["connection_id"], "task_id": "task-a",
            "agent_name": "Agent display", "revoked": False,
            "created_at": listed[0]["created_at"],
        }]
        assert "token" not in repr(listed) and "digest" not in repr(listed)
        revoked = host.connections.revoke_connection(grant["connection_id"], "revoke-key")
        assert revoked == {
            "contract_version": "agent_link_v1", "connection_id": grant["connection_id"],
            "status": "revoked", "staging_only": True,
        }
        assert host.connections.list_connections()[0]["revoked"] is True
    finally:
        host.close()
    assert host.connections.host_status()["phase"] == "stopped"
    for operation in (
        host.connections.list_connections,
        lambda: host.connections.create_connection("task-b", "Other"),
        lambda: host.connections.revoke_connection(grant["connection_id"], "again"),
    ):
        with pytest.raises(NativeConnectionError) as stopped:
            operation()
        assert stopped.value.code == "host_not_ready"


class _FakeService:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def reviewer_call(self, token, operation, arguments):
        self.calls.append((token, operation, copy.deepcopy(arguments)))
        if self.error is not None:
            raise self.error
        return copy.deepcopy(self.response)


def _ready():
    return {
        "contract_version": "native_review_host_v1", "host_id": "host-fixture",
        "phase": "ready", "base_url": "http://127.0.0.1:12345",
        "staging_only": True,
    }


@pytest.mark.parametrize("tamper", ["identity", "secret", "bool", "contract"])
def test_connection_list_strictly_rejects_tampered_or_secret_response(tamper):
    record = {
        "connection_id": "connection-a", "task_id": "task-a", "agent_name": "agent",
        "revoked": False, "created_at": 1,
    }
    response = {
        "contract_version": "agent_link_v1", "connections": [record],
        "staging_only": True,
    }
    if tamper == "identity":
        record["connection_id"] = ""
    elif tamper == "secret":
        record["token_digest"] = "a" * 64
    elif tamper == "bool":
        record["created_at"] = True
    else:
        response["contract_version"] = "agent_link_v2"
    controller = NativeConnectionController(_FakeService(response), REVIEWER, _ready)
    with pytest.raises(NativeConnectionError) as failure:
        controller.list_connections()
    assert failure.value.code == "invalid_response"
    assert REVIEWER not in str(failure.value) and "a" * 64 not in str(failure.value)


def test_create_failure_is_called_once_and_marked_result_unknown_without_echo():
    secret = "synthetic-agent-token-that-must-not-echo"
    service = _FakeService(error=AgentLinkError("persistence_failed", secret))
    controller = NativeConnectionController(service, REVIEWER, _ready)
    with pytest.raises(NativeConnectionError) as failure:
        controller.create_connection("task-a", "Agent name")
    assert failure.value.code == "persistence_failed"
    assert failure.value.result_unknown is True
    assert len(service.calls) == 1
    assert secret not in str(failure.value) and REVIEWER not in str(failure.value)
    assert failure.value.__cause__ is None and failure.value.__suppress_context__ is True


def test_unexpected_service_failures_are_redacted_without_retry():
    secret = "unexpected-private-service-payload"
    service = _FakeService(error=Exception(secret))
    controller = NativeConnectionController(service, REVIEWER, _ready)
    with pytest.raises(NativeConnectionError) as create_failure:
        controller.create_connection("task-a", "Agent name")
    assert create_failure.value.code == "connection_create_failed"
    assert create_failure.value.result_unknown is True
    assert len(service.calls) == 1 and secret not in str(create_failure.value)
    assert create_failure.value.__cause__ is None

    service.calls.clear()
    with pytest.raises(NativeConnectionError) as list_failure:
        controller.list_connections()
    assert list_failure.value.code == "connection_operation_failed"
    assert list_failure.value.result_unknown is False
    assert len(service.calls) == 1 and secret not in str(list_failure.value)
    assert list_failure.value.__cause__ is None


@pytest.mark.parametrize("field,value", [
    ("token", "short"), ("task_id", "other"), ("agent_name", "other"),
    ("staging_only", 1),
])
def test_create_rejects_malformed_receipt_as_unknown_without_retry(field, value):
    response = {
        "contract_version": "agent_link_v1", "connection_id": "connection-a",
        "task_id": "task-a", "agent_name": "Agent name",
        "token": "valid-agent-token-value", "staging_only": True,
    }
    response[field] = value
    service = _FakeService(response)
    controller = NativeConnectionController(service, REVIEWER, _ready)
    with pytest.raises(NativeConnectionError) as failure:
        controller.create_connection("task-a", "Agent name")
    assert failure.value.code == "invalid_response"
    assert failure.value.result_unknown is True and len(service.calls) == 1
    assert "valid-agent-token-value" not in str(failure.value)


@pytest.mark.parametrize("tamper", ["target", "status", "secret", "contract"])
def test_revoke_strictly_rejects_wrong_or_secret_receipt(tamper):
    response = {
        "contract_version": "agent_link_v1", "connection_id": "connection-a",
        "status": "revoked", "staging_only": True,
    }
    if tamper == "target":
        response["connection_id"] = "connection-b"
    elif tamper == "status":
        response["status"] = "active"
    elif tamper == "secret":
        response["token"] = "private-token-value"
    else:
        response["contract_version"] = "agent_link_v2"
    controller = NativeConnectionController(_FakeService(response), REVIEWER, _ready)
    with pytest.raises(NativeConnectionError) as failure:
        controller.revoke_connection("connection-a", "revoke-key")
    assert failure.value.code == "invalid_response"
    assert "private-token-value" not in str(failure.value)


def test_list_rejects_duplicate_connection_identity():
    record = {
        "connection_id": "connection-a", "task_id": "task-a", "agent_name": "agent",
        "revoked": False, "created_at": 1,
    }
    controller = NativeConnectionController(
        _FakeService({
            "contract_version": "agent_link_v1",
            "connections": [record, copy.deepcopy(record)], "staging_only": True,
        }),
        REVIEWER,
        _ready,
    )
    with pytest.raises(NativeConnectionError) as failure:
        controller.list_connections()
    assert failure.value.code == "invalid_response"


def test_host_rejects_bool_port_and_constructor_failure_releases_store_owner(tmp_path):
    with pytest.raises(DesktopHostError) as invalid:
        DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", REVIEWER, port=True)
    assert invalid.value.code == "invalid_port"

    from app.agent_link.store import AgentLinkStore
    from app.desktop_review.workspace import NativeReviewFacade
    state, root = tmp_path / "other.json", tmp_path / "review-owner"
    seed = AgentLinkStore(state)
    facade = NativeReviewFacade(
        type("Service", (), {"reviewer_call": lambda *_: {}})(), REVIEWER, root
    )
    seed.close()
    try:
        with pytest.raises(DesktopHostError) as conflict:
            DesktopReviewHost(state, root, REVIEWER)
        assert conflict.value.code == "workspace_in_use"
        reopened = AgentLinkStore(state)
        reopened.close()
    finally:
        facade.close()
