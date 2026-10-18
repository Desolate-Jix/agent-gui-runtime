"""Agent 首次学习入口必须复用原生宿主且无批准权限。"""

import pytest

from app.agent_link.contracts import AgentLinkError
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
from tests.test_fresh_learning_action_preview import _setup
from tests.test_formal_fresh_graph_source import _stage


def test_fresh_capability_exists_only_with_actual_coordinator(tmp_path):
    host, owner, runtime, backend, claims, source, old, intent = _setup(tmp_path)
    runtime.cancel_session_preparation(preparation_id="fresh.preview")
    reference = source.reference()
    connection = host._service._store.read(lambda state: state["connections"][reference["connection_id"]])
    coordinator = None
    try:
        assert host._service._learning_runtime_provider is None
        coordinator = NativeSingleStepCoordinator(host.fresh_learning.archive.project_root, host.facade, host,
            enable_agent_learning=True, thread_initializer=lambda: None, thread_finalizer=lambda: None)
        provider = host._service._learning_runtime_provider
        assert callable(getattr(provider, "prepare_fresh", None)), "public fresh preparation is missing"
        assert callable(getattr(provider, "request_fresh", None))
        assert callable(getattr(provider, "get_fresh", None))
        assert callable(getattr(provider, "cancel_fresh", None))
        assert connection["task_id"] == reference["task_id"]
    finally:
        if coordinator is not None:
            coordinator.shutdown()
        host.close()


def test_fresh_public_operations_are_capability_scoped_and_reject_geometry(tmp_path):
    host, connection, segment, packet, args, staged = _stage(tmp_path)
    coordinator = None
    service, token = host._service, connection["token"]
    try:
        assert "fresh_learning_runtime" not in service.agent_call(token, "status", {})
        coordinator = NativeSingleStepCoordinator(host.fresh_learning.archive.project_root, host.facade, host,
            enable_agent_learning=True, thread_initializer=lambda: None, thread_finalizer=lambda: None)
        status = service.agent_call(token, "status", {})
        assert "fresh_learning_runtime" in status, "fresh tools are not advertised"
        assert set(status["fresh_learning_runtime"]["operations"]) == {
            "prepare_fresh_learning_runtime", "request_fresh_learning_action",
            "get_fresh_learning_runtime", "cancel_fresh_learning_runtime"}
        with pytest.raises(AgentLinkError) as rejected:
            service.agent_call(token, "request_fresh_learning_action", {"segment_id": segment["segment_id"],
                "preparation_id": "missing", "intent_id": "intent.new", "action_id": "action.view",
                "semantic_action": "open_detail", "goal": "View details", "x": 60, "y": 30})
        assert rejected.value.code == "invalid_arguments"
        for operation in ("approve_fresh_learning_action", "execute_fresh_learning_action"):
            with pytest.raises(AgentLinkError) as denied:
                service.agent_call(token, operation, {})
            assert denied.value.code == "operation_forbidden"
    finally:
        if coordinator is not None:
            coordinator.shutdown()
        host.close()
