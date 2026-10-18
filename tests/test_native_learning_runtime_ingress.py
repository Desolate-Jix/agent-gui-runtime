"""原生宿主到真实学习调用点的隔离集成，不发送操作系统输入。"""

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from app.agent_link.contracts import AgentLinkError
from app.api.agent_runtime import LocalAgentRuntimeCallsite
from app.desktop_review.host import DesktopReviewHost
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
from tests.test_formal_learning_runtime_binding import _make_callsite


REVIEWER = "native-learning-reviewer"


@contextmanager
def _rig(tmp_path):
    root = tmp_path / "review"
    host = DesktopReviewHost(tmp_path / "inbox.json", root, REVIEWER)
    coordinator = None
    try:
        assert hasattr(host, "learning_segments"), "native host has no real learning owner"
        service = host._service
        connection = service.reviewer_call(REVIEWER, "create_connection", {
            "task_id": "fresh-native-learning", "agent_name": "fresh-codex-fixture",
        })
        segment = service.agent_call(connection["token"], "start_learning_segment", {
            "idempotency_key": "segment-one", "title": "Fresh isolated flow",
        })
        template, windows, selection, backend = _make_callsite(root, None)
        instances = []

        def factory(*, project_root, selection, window_manager, learning_binding):
            assert project_root == root.resolve()
            assert window_manager is windows
            runtime = LocalAgentRuntimeCallsite(
                project_root=project_root, asset_store=template._asset_store,
                claim_store=template._claim_store, window_manager=windows,
                controller_factory=template._controller_factory, selection=selection,
                learning_binding=learning_binding,
            )
            instances.append(runtime)
            return runtime

        factory.window_manager = windows
        coordinator = NativeSingleStepCoordinator(
            root, host.facade, host, runtime_factory=factory, enable_agent_learning=True,
            thread_initializer=lambda: None, thread_finalizer=lambda: None,
        )
        host.start()
        yield host, coordinator, service, connection, segment, selection, backend, instances
    finally:
        if coordinator is not None:
            coordinator.shutdown()
        else:
            host.close()


def _prepare_args(segment, selection, key="prepare-one"):
    return {
        "segment_id": segment["segment_id"], "idempotency_key": key,
        "asset_id": selection.asset_id, "asset_content_sha256": selection.asset_content_sha256,
        "target_window_handle": selection.target_window_handle,
        "target_process_id": selection.target_process_id,
    }


def test_native_provider_prepares_actual_runtime_once_and_cancels_empty_child(tmp_path):
    with _rig(tmp_path) as (host, coordinator, service, connection, segment, selection, backend, instances):
        provider = host.learning_runtime
        identity = {"connection_id": connection["connection_id"], "task_id": connection["task_id"]}
        prepared = provider.prepare(**identity, **_prepare_args(segment, selection))
        assert prepared["phase"] == "observed", prepared
        assert prepared["action_executed"] is False
        assert len(instances) == 1 and backend.attempt_count == 0
        current = service.agent_call(connection["token"], "get_learning_segment", {"segment_id": segment["segment_id"]})
        assert current["children"][0]["runtime_session_id"] == instances[0]._observation.session_id
        assert provider.prepare(**identity, **_prepare_args(segment, selection))["preparation_id"] == prepared["preparation_id"]
        assert len(instances) == 1
        scope = {**identity, "segment_id": segment["segment_id"], "preparation_id": prepared["preparation_id"]}
        cancelled = provider.cancel(**scope)
        assert cancelled["phase"] == "cancelled" and cancelled["cleanup_verified"] is True
        assert provider.cancel(**scope) == cancelled
        assert provider.prepare(**identity, **_prepare_args(segment, selection))["phase"] == "cancelled"
        assert len(instances) == 1 and backend.attempt_count == 0
        current = service.agent_call(connection["token"], "get_learning_segment", {"segment_id": segment["segment_id"]})
        assert current["children"][0]["phase"] == "cancelled"
        closed = service.agent_call(connection["token"], "finish_learning_segment", {
            "segment_id": segment["segment_id"], "expected_revision": current["revision"],
        })
        assert closed["status"] == "closed" and closed["source_status"] == "empty"


def test_native_provider_foreign_and_stale_cancel_cannot_release_new_runtime(tmp_path):
    with _rig(tmp_path) as (host, coordinator, service, connection, segment, selection, backend, instances):
        provider = host.learning_runtime
        identity = {"connection_id": connection["connection_id"], "task_id": connection["task_id"]}
        first = provider.prepare(**identity, **_prepare_args(segment, selection))
        scope = {**identity, "segment_id": segment["segment_id"], "preparation_id": first["preparation_id"]}
        other = service.reviewer_call(REVIEWER, "create_connection", {
            "task_id": connection["task_id"], "agent_name": "other-agent",
        })
        with pytest.raises(AgentLinkError) as denied:
            provider.cancel(**{**scope, "connection_id": other["connection_id"]})
        assert denied.value.code == "not_found"
        provider.cancel(**scope)
        second = provider.prepare(**identity, **_prepare_args(segment, selection, "prepare-two"))
        assert second["phase"] == "observed", second
        assert second["preparation_id"] != first["preparation_id"]
        assert provider.cancel(**scope)["phase"] == "cancelled"
        assert instances[-1]._observation is not None
        assert backend.attempt_count == 0


def test_inflight_prepare_retry_and_cancel_do_not_duplicate_runtime_or_claim_cleanup(tmp_path):
    with _rig(tmp_path) as (host, coordinator, service, connection, segment, selection, backend, instances):
        entered, release = Event(), Event()
        original = coordinator._runtime_factory

        def delayed(**kwargs):
            entered.set()
            assert release.wait(10)
            return original(**kwargs)

        coordinator._runtime_factory = delayed
        identity = {"connection_id": connection["connection_id"], "task_id": connection["task_id"]}
        args = {**identity, **_prepare_args(segment, selection)}
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(host.learning_runtime.prepare, **args)
            try:
                assert entered.wait(10)
                repeated = host.learning_runtime.prepare(**args)
                assert repeated["phase"] == "preparing"
                scope = {**identity, "segment_id": segment["segment_id"],
                         "preparation_id": repeated["preparation_id"]}
                cancelled = host.learning_runtime.cancel(**scope)
                assert cancelled["cancellation_requested"] is True
                assert cancelled["cleanup_verified"] is False
            finally:
                release.set()
            result = future.result(timeout=10)
        assert result["phase"] == "cancelled" and result["cleanup_verified"] is True
        assert len(instances) == 1 and backend.attempt_count == 0


def test_revoked_agent_cannot_call_tools_but_retained_owner_can_finish_cleanup(tmp_path):
    with _rig(tmp_path) as (host, coordinator, service, connection, segment, selection, backend, instances):
        identity = {"connection_id": connection["connection_id"], "task_id": connection["task_id"]}
        prepared = host.learning_runtime.prepare(**identity, **_prepare_args(segment, selection))
        service.reviewer_call(REVIEWER, "revoke_connection", {
            "connection_id": connection["connection_id"], "idempotency_key": "revoke-one",
        })
        args = {"segment_id": segment["segment_id"], "preparation_id": prepared["preparation_id"]}
        with pytest.raises(AgentLinkError) as denied:
            service.agent_call(connection["token"], "cancel_learning_runtime", args)
        assert denied.value.code == "connection_revoked"
        cleanup = host.learning_runtime.cancel(**identity, **args)
        assert cleanup["cleanup_verified"] is True
        assert instances[0]._observation is None and backend.attempt_count == 0
