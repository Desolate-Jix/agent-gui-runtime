"""执行宿主暂停学习入口，同时保留只读记忆、应用准备和输入门禁。"""

import asyncio
import hashlib
import sys
from types import SimpleNamespace

import httpx
import pytest

from app.agent_link.http_app import create_agent_link_app
from app.desktop_review.host import DesktopHostError, DesktopReviewHost
from app.desktop_review.single_step_coordinator import (
    NativeSingleStepCoordinator, NativeSingleStepCoordinatorError,
)


REVIEWER = "execution-only-reviewer-0123456789"
LEARNING_OPERATIONS = [
    "submit_batch", "submit_candidate", "start_learning_segment", "get_learning_segment",
    "finish_learning_segment", "prepare_learning_runtime", "get_learning_runtime",
    "cancel_learning_runtime", "observe_learning_screen", "submit_observed_interface_learning",
    "inspect_learning_content", "read_learning_content", "prepare_fresh_learning_runtime",
    "request_fresh_learning_action", "get_fresh_learning_runtime", "cancel_fresh_learning_runtime",
    "request_learning_action", "get_learning_action_result", "request_interface_membership",
    "list_interface_relearning_feedback", "get_interface_relearning_feedback",
    "submit_interface_relearning_candidate",
]


def host_at(tmp_path):
    return DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", REVIEWER)


def post(app, path, *, token=None, body=None, headers=None):
    async def request():
        transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 51000))
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as client:
            supplied = {**(headers or {})}
            if token is not None:
                supplied["authorization"] = "Bearer " + token
            return await client.post(path, json={} if body is None else body, headers=supplied)

    return asyncio.run(request())


def test_host_constructs_and_closes_without_learning_dependencies(tmp_path, monkeypatch):
    for name in (
        "app.agent.action_learning_recorder", "app.agent.action_learning_capture_archive",
        "app.agent_link.learning_segments", "app.agent_link.fresh_graph_source",
        "app.desktop_review.learning_observation", "app.desktop_review.learning_runtime",
    ):
        monkeypatch.setitem(sys.modules, name, None)
    host = host_at(tmp_path)
    try:
        assert host.status()["phase"] == "created"
        assert not any(hasattr(host, name) for name in (
            "learning_segments", "fresh_learning", "learning_observation"))
        assert host._service._learning_owner is None
        assert host._service._learning_runtime_provider is None
        assert host._service._learning_observation_provider is None
        with pytest.raises(DesktopHostError) as rejected:
            host.enable_learning_runtime(object())
        assert rejected.value.code == "learning_mode_retired"
    finally:
        host.close()
    replacement = host_at(tmp_path)
    replacement.close()


def test_coordinator_does_not_install_learning_by_default(tmp_path):
    calls = []
    host = SimpleNamespace(status=lambda: {}, close=lambda: None,
        enable_learning_runtime=lambda coordinator: calls.append("learning"),
        enable_application_startup=lambda coordinator: calls.append("startup"))
    coordinator = NativeSingleStepCoordinator(tmp_path,
        SimpleNamespace(list_reviewed_assets=lambda: []), host)
    try:
        assert calls == ["startup"]
    finally:
        coordinator.shutdown()


def test_explicit_learning_is_rejected_before_allocating_runtime_owner(tmp_path, monkeypatch):
    from app.desktop_review import single_step_coordinator as module

    def forbidden_owner(**kwargs):
        raise AssertionError("a rejected learning request must not allocate a runtime owner")

    monkeypatch.setattr(module, "SerialRuntimeOwner", forbidden_owner)
    with pytest.raises(NativeSingleStepCoordinatorError) as rejected:
        NativeSingleStepCoordinator(tmp_path, SimpleNamespace(list_reviewed_assets=lambda: []),
            SimpleNamespace(status=lambda: {}), enable_agent_learning=True)
    assert rejected.value.code == "learning_mode_retired"


def test_startup_binding_failure_closes_the_coordinator_owner(tmp_path, monkeypatch):
    from app.desktop_review import single_step_coordinator as module
    from app.execution.single_step_runtime_owner import RuntimeOwnerError, SerialRuntimeOwner

    owners = []

    def owner(**kwargs):
        result = SerialRuntimeOwner(**kwargs)
        owners.append(result)
        return result

    def broken_startup(coordinator):
        assert coordinator._owner.call(lambda: "started") == "started"
        raise ValueError("synthetic startup binding failure")

    monkeypatch.setattr(module, "SerialRuntimeOwner", owner)
    try:
        with pytest.raises(ValueError, match="startup binding failure"):
            NativeSingleStepCoordinator(tmp_path, SimpleNamespace(list_reviewed_assets=lambda: []),
                SimpleNamespace(status=lambda: {}, enable_application_startup=broken_startup),
                thread_initializer=lambda: None, thread_finalizer=lambda: None)
        assert len(owners) == 1
        with pytest.raises(RuntimeOwnerError) as closed:
            owners[0].call(lambda: "must not restart")
        assert closed.value.code == "runtime_owner_closed"
    finally:
        for captured in owners:
            captured.close()


def test_host_construction_failure_releases_workspace_and_store(tmp_path, monkeypatch):
    from app.desktop_review import host as module
    from app.agent_link.host import AgentLinkHttpHostError

    original = module.OwnedAgentLinkHttpHost

    def unavailable_http(*args, **kwargs):
        raise AgentLinkHttpHostError("synthetic_http_failure", "synthetic host failure")

    monkeypatch.setattr(module, "OwnedAgentLinkHttpHost", unavailable_http)
    with pytest.raises(DesktopHostError) as failed:
        host_at(tmp_path)
    assert failed.value.code == "synthetic_http_failure"
    monkeypatch.setattr(module, "OwnedAgentLinkHttpHost", original)
    replacement = host_at(tmp_path)
    replacement.close()


@pytest.mark.parametrize("operation", LEARNING_OPERATIONS)
def test_http_does_not_publish_learning_operations(tmp_path, operation):
    host = host_at(tmp_path)
    try:
        app = create_agent_link_app(host._service)
        response = post(app, "/agent/" + operation, token=REVIEWER)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "operation_not_found"
    finally:
        host.close()


@pytest.mark.parametrize("operation", ["record_feedback", "withdraw_issue"])
def test_http_does_not_publish_learning_feedback_mutations(tmp_path, operation):
    host = host_at(tmp_path)
    try:
        response = post(create_agent_link_app(host._service), "/reviewer/" + operation, token=REVIEWER)
        assert response.status_code == 404
    finally:
        host.close()


def test_http_retains_memory_application_startup_and_execution_authentication(tmp_path, monkeypatch):
    host = host_at(tmp_path)
    coordinator = NativeSingleStepCoordinator(tmp_path / "review", host.facade, host)
    try:
        connection = host._service.reviewer_call(REVIEWER, "create_connection",
            {"task_id": "execution-read", "agent_name": "synthetic-reader"})
        token = connection["token"]
        execution_token = "execution-only-secret"
        host._single_step_controller.set_accepting(True)
        app = create_agent_link_app(host._service,
            execution_controller=host._single_step_controller,
            execution_token_digest=hashlib.sha256(execution_token.encode("utf-8")).hexdigest())
        status = post(app, "/agent/status", token=token)
        assert status.status_code == 200
        advertised = status.json()
        assert not set(LEARNING_OPERATIONS).intersection(advertised["capabilities"])
        assert not any(name in advertised for name in (
            "learning_segments", "learning_runtime", "fresh_learning_runtime", "reviewed_learning_actions",
            "learning_observation", "learning_content", "interface_relearning", "graph_contracts",
            "candidate_change_types"))
        assert advertised["interface_content"]["operations"] == ["search_interface_memory", "get_interface_memory"]
        assert advertised["application_startup"]["operations"] == [
            "discover_applications", "request_application_launch", "get_application_launch"]
        memory = post(app, "/agent/search_interface_memory", token=token)
        assert memory.status_code == 200 and memory.json() == []
        monkeypatch.setattr(coordinator, "discover_applications", lambda: {
            "contract_version": "native_application_discovery_v1", "apps": [], "running_windows": []})
        applications = post(app, "/agent/discover_applications", token=token)
        assert applications.status_code == 200
        assert applications.json()["apps"] == []
        action = "/action/execute_recognition_plan"
        body = {"confirmation_id": "grounded-confirmation." + "a" * 64}
        assert post(app, action, body=body).status_code == 401
        assert post(app, action, body=body, token=token).status_code == 401
        assert post(app, action, body=body, token=execution_token,
            headers={"origin": "http://127.0.0.1"}).status_code == 403
        unattached = post(app, action, body=body, token=execution_token)
        assert unattached.status_code == 409
        assert unattached.json()["error"]["code"] == "runtime_not_attached"
    finally:
        coordinator.shutdown()
