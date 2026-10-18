"""实际 MCP、原生协调器和 HTTP 单步链；仅隔离系统输入和识别。"""

import asyncio
import json
from contextlib import contextmanager
from types import SimpleNamespace

from mcp import ClientSession
from mcp.client.stdio import stdio_client
import pytest
from app.agent_link.contracts import AgentLinkError

from app.desktop_review.fresh_runtime_callsite import FreshLearningRuntimeCallsite
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator, NativeSingleStepCoordinatorError
from tests.test_formal_fresh_graph_source import _stage
from tests.test_formal_fresh_runtime_session import _runtime
from tests.test_formal_fresh_learning_observation import _owner, _WindowManager, _OriginReader, _bound
from tests.test_fresh_learning_action_preview import _recognize, _CurrentUIA
from tests.test_fresh_dispatch_graph import _Visible
from tests.test_formal_learning_runtime_controls import _mcp_server


@contextmanager
def _rig(tmp_path):
    host, connection, segment, packet, args, staged = _stage(tmp_path)
    root = host.fresh_learning.archive.project_root
    windows = SimpleNamespace(bound=SimpleNamespace(handle=4242, process_id=9001, is_active=True))
    windows.get_bound_window = lambda: windows.bound
    windows.bind_window_by_handle = lambda handle: windows.bound if handle == 4242 else None
    instances = []
    def factory(*, project_root, selection, window_manager, learning_binding):
        observation_owner = _owner(root, manager=_WindowManager(*[_bound() for _ in range(60)]),
            origin=_OriginReader(*["https://fresh.example"] * 60), runner=_recognize, uia=_CurrentUIA())
        runtime, backend, claims, source = _runtime(host, connection, segment, staged,
            observation_owner=observation_owner, source=selection.source)
        runtime.set_action_learning_recorder(host.learning_segments.recorder)
        runtime._window_visibility_checker = _Visible()
        callsite = FreshLearningRuntimeCallsite(controller=runtime, learning_binding=learning_binding)
        instances.append((callsite, runtime, backend, observation_owner))
        return callsite
    factory.window_manager = windows
    coordinator = NativeSingleStepCoordinator(root, host.facade, host, runtime_factory=factory,
        enable_agent_learning=True, thread_initializer=lambda: None, thread_finalizer=lambda: None)
    try:
        host.start()
        yield host, coordinator, connection, segment, staged, instances
    finally:
        coordinator.shutdown()


@pytest.mark.parametrize('use_learned_control', [False, True])
def test_fresh_stdio_proposal_native_execution_and_agent_factual_read(tmp_path, use_learned_control):
    with _rig(tmp_path) as (host, coordinator, connection, segment, staged, instances):
        async def check():
            async with stdio_client(_mcp_server(host.status()["base_url"], connection["token"])) as streams:
                async with ClientSession(*streams, read_timeout_seconds=60) as client:
                    await client.initialize()
                    tools = {item.name: item for item in (await client.list_tools()).tools}
                    assert "prepare_fresh_learning_runtime" in tools, "fresh MCP capability is missing"
                    assert not any(name.startswith(("approve_fresh", "execute_fresh")) for name in tools)
                    assert set(tools["request_fresh_learning_action"].input_schema["properties"]) == {
                        "segment_id", "preparation_id", "intent_id", "action_id", "semantic_action", "goal",
                        "text_parameters", "text_values", "learned_control", "scroll_parameters"}
                    assert set(tools["request_fresh_learning_action"].input_schema["required"]) == {
                        "segment_id", "preparation_id", "intent_id", "action_id", "semantic_action", "goal"}
                    prepare = {"segment_id": segment["segment_id"], "batch_id": staged["batch_id"],
                               "idempotency_key": "prepare.first"}
                    prepared = await client.call_tool("prepare_fresh_learning_runtime", prepare)
                    assert not prepared.is_error, prepared
                    value = prepared.structured_content
                    assert value["phase"] == "observed", value
                    assert any(item.type == "image" for item in prepared.content)
                    assert len(instances) == 1
                    scope = {"segment_id": segment["segment_id"], "preparation_id": value["preparation_id"]}
                    repeated = await client.call_tool("prepare_fresh_learning_runtime", prepare)
                    assert not repeated.is_error and len(instances) == 1
                    intent = {**scope, "intent_id": "intent.first", "action_id": "action.view",
                              "semantic_action": "open_detail", "goal": "View details"}
                    if use_learned_control:
                        from tests.test_learned_control_reference import _saved
                        original, saved, selection = _saved(host, instances[0][1]._binding.source)
                        intent['learned_control'] = selection
                        wrong = {**intent, 'learned_control': {**selection, 'version_id': original['version_id']}}
                        rejected = await client.call_tool('request_fresh_learning_action', wrong)
                        assert rejected.is_error
                        assert instances[0][2].commands == []
                    pending = await client.call_tool("request_fresh_learning_action", intent)
                    assert not pending.is_error, pending
                    view = coordinator.current_fresh_review()
                    assert view["confirmation_id"] == pending.structured_content["confirmation_id"]
                    if use_learned_control:
                        assert view['preview']['intent']['learned_control']['reference'] == selection
                        assert view['preview']['intent']['learned_control']['content_sha256'] == saved['content_sha256']
                    backend = instances[0][2]
                    assert backend.commands == []
                    count = len(instances[0][3]._screenshot_service.calls)
                    replay = await client.call_tool("request_fresh_learning_action", intent)
                    assert not replay.is_error
                    assert len(instances[0][3]._screenshot_service.calls) == count
                    conflicting = await client.call_tool("request_fresh_learning_action", {**intent, "goal": "Other details"})
                    assert conflicting.is_error
                    assert len(instances[0][3]._screenshot_service.calls) == count and backend.commands == []
                    coordinator.approve(confirmation_id=view["confirmation_id"],
                        preview_content_sha256=view["preview"]["preview_sha256"])
                    assert backend.commands == []
                    result = coordinator.execute(confirmation_id=view["confirmation_id"])
                    assert result["kind"] == "receipt", result
                    assert len(backend.commands) == 1
                    if use_learned_control:
                        claim = instances[0][1]._intent_claim_store.get_for_grounded_confirmation(
                            confirmation_id=view['confirmation_id'])
                        assert claim.intent.learned_control == view['preview']['intent']['learned_control']
                    retried_after_execution = await client.call_tool("request_fresh_learning_action", intent)
                    assert not retried_after_execution.is_error, retried_after_execution
                    assert retried_after_execution.structured_content["claim_phase"] == "terminal"
                    assert retried_after_execution.structured_content["receipt"] == result["payload"]
                    assert len(backend.commands) == 1
                    current = await client.call_tool("get_fresh_learning_runtime", scope)
                    assert not current.is_error, current
                    factual = current.structured_content
                    assert factual["receipt"]["outcome"] == "ACTION_RECORDED"
                    assert factual["observation"]["observation_id"] == factual["receipt"]["next_observation_id"]
                    assert factual["operation_dispatches_input"] is False and factual["execution_ready"] is False
                    assert "action_executed" not in factual
                    coordinator.cancel()
                    after_release = await client.call_tool("get_fresh_learning_runtime", scope)
                    assert not after_release.is_error, after_release
                    assert after_release.structured_content["receipt"] == factual["receipt"]
                    assert after_release.structured_content["cleanup_verified"] is True
                    assert len(backend.commands) == 1
        asyncio.run(asyncio.wait_for(check(), timeout=120))


def test_fresh_provider_cancel_poll_and_foreign_scope_without_input(tmp_path):
    with _rig(tmp_path) as (host, coordinator, connection, segment, staged, instances):
        service, token = host._service, connection["token"]
        args = {"segment_id": segment["segment_id"], "batch_id": staged["batch_id"], "idempotency_key": "empty.first"}
        prepared = service.agent_call(token, "prepare_fresh_learning_runtime", args)
        assert prepared["phase"] == "observed", prepared
        scope = {"segment_id": segment["segment_id"], "preparation_id": prepared["preparation_id"]}
        for operation in ("get_learning_runtime", "cancel_learning_runtime"):
            with pytest.raises(AgentLinkError) as wrong_family:
                service.agent_call(token, operation, scope)
            assert wrong_family.value.code == "not_found"
            assert coordinator.learning_runtime_state()["phase"] == "observed"
        with pytest.raises(AgentLinkError) as busy:
            service.agent_call(token, "prepare_fresh_learning_runtime", {**args, "idempotency_key": "other"})
        assert busy.value.code == "learning_busy" and len(instances) == 1
        other = service.reviewer_call("fresh-graph-reviewer", "create_connection", {
            "task_id": connection["task_id"], "agent_name": "foreign-fresh-agent"})
        with pytest.raises(AgentLinkError) as foreign:
            service.agent_call(other["token"], "get_fresh_learning_runtime", scope)
        assert foreign.value.code == "not_found"
        cancelled = service.agent_call(token, "cancel_fresh_learning_runtime", scope)
        assert cancelled["cleanup_verified"] is True
        polled = service.agent_call(token, "get_fresh_learning_runtime", scope)
        assert polled["phase"] == "cancelled" and polled["cleanup_verified"] is True
        assert instances[0][2].commands == []
        next_prepared = service.agent_call(token, "prepare_fresh_learning_runtime", {**args, "idempotency_key": "empty.second"})
        assert next_prepared["phase"] == "observed", next_prepared
        old = service.agent_call(token, "get_fresh_learning_runtime", scope)
        assert old["session_id"] == prepared["session_id"] and old["cleanup_verified"] is True
        assert old["session_id"] != next_prepared["session_id"]
        service.agent_call(token, "cancel_fresh_learning_runtime", {**scope, "preparation_id": next_prepared["preparation_id"]})
        service.reviewer_call("fresh-graph-reviewer", "revoke_connection", {
            "connection_id": connection["connection_id"], "idempotency_key": "revoke"})
        with pytest.raises(AgentLinkError) as revoked:
            service.agent_call(token, "get_fresh_learning_runtime", scope)
        assert revoked.value.code == "connection_revoked"


def test_cancelled_pending_action_reports_closed_claim_not_cached_pending(tmp_path):
    with _rig(tmp_path) as (host, coordinator, connection, segment, staged, instances):
        service, token = host._service, connection["token"]
        prepared = service.agent_call(token, "prepare_fresh_learning_runtime", {
            "segment_id": segment["segment_id"], "batch_id": staged["batch_id"], "idempotency_key": "pending.cancel"})
        scope = {"segment_id": segment["segment_id"], "preparation_id": prepared["preparation_id"]}
        service.agent_call(token, "request_fresh_learning_action", {**scope, "intent_id": "intent.cancel",
            "action_id": "action.view", "semantic_action": "open_detail", "goal": "View details"})
        cancelled = service.agent_call(token, "cancel_fresh_learning_runtime", scope)
        assert cancelled["cleanup_verified"] is True
        assert cancelled["claim_phase"] == "grounded_confirmation_closed"
        polled = service.agent_call(token, "get_fresh_learning_runtime", scope)
        assert polled["cleanup_verified"] is True
        assert polled["claim_phase"] == "grounded_confirmation_closed"
        assert instances[0][2].commands == []


@pytest.mark.parametrize("kind,code,expected", [
    ("native", "foreground_wait_timeout", "foreground_wait_timeout"),
    ("native", "foreground_wait_cancelled", "foreground_wait_cancelled"),
    ("native", "private-detail-code", "runtime_prepare_failed"),
    ("other", "private-detail-code", "runtime_prepare_failed"),
])
def test_fresh_prepare_public_error_is_actionable_without_private_details(tmp_path, monkeypatch, kind, code, expected):
    with _rig(tmp_path) as (host, coordinator, connection, segment, staged, instances):
        private = "private-runtime-detail-must-not-leak"
        failure = NativeSingleStepCoordinatorError(code, private) if kind == "native" else RuntimeError(private)
        attempts = []

        def fail_prepare(selection):
            attempts.append(selection)
            raise failure

        monkeypatch.setattr(coordinator, "_create_runtime_on_owner", fail_prepare)

        async def check():
            async with stdio_client(_mcp_server(host.status()["base_url"], connection["token"])) as streams:
                async with ClientSession(*streams, read_timeout_seconds=60) as client:
                    await client.initialize()
                    args = {"segment_id": segment["segment_id"], "batch_id": staged["batch_id"],
                            "idempotency_key": "prepare.error"}
                    response = await client.call_tool("prepare_fresh_learning_runtime", args)
                    assert not response.is_error, response
                    payload = json.loads(next(item.text for item in response.content if item.type == "text"))
                    assert payload["phase"] == "failed", payload
                    assert payload["error_code"] == expected
                    assert private not in response.model_dump_json()
                    assert payload["operation_dispatches_input"] is False
                    repeated = await client.call_tool("prepare_fresh_learning_runtime", args)
                    assert not repeated.is_error, repeated
                    assert private not in repeated.model_dump_json()
                    assert len(attempts) == 1 and instances == []
                    cancelled = await client.call_tool("cancel_fresh_learning_runtime", {
                        "segment_id": segment["segment_id"], "preparation_id": payload["preparation_id"]})
                    assert not cancelled.is_error, cancelled
                    assert coordinator.learning_runtime_state()["phase"] == "idle"

        asyncio.run(asyncio.wait_for(check(), timeout=120))
