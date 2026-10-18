"""审核工作流版本钉扎经 MCP 准备后的隔离回归。"""

from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

from mcp import ClientSession
from mcp.client.stdio import stdio_client

from app.agent.desktop_backend import DeterministicFakeBackend
from app.agent.live_controller import LiveController
from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from app.api.agent_runtime import LocalAgentRuntimeCallsite
from app.desktop_review.host import DesktopReviewHost
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
from tests.test_formal_graph_exact_review import BATCH, TASK, _batch, _node
from tests.test_formal_graph_publication import _review_compile
from tests.test_fresh_agent_public_sequence import _mcp_server
from tests.test_fresh_published_runtime_reuse import _FreshVersionObservations, _FreshVersionResolver
from tests.test_live_controller_w4 import _Gate, _WindowVisibilityChecker


REVIEWER = "reviewed-version-pin-reviewer"
WEB_BINDING = {
    "kind": "web",
    "display_name": "Synthetic reviewed version fixture",
    "canonical_origin": "https://fresh.example",
}


def _publish_v1(host, connection):
    service = host._service
    service.agent_call(connection["token"], "submit_batch", _batch())
    graph = host.facade.create_graph_revision(TASK, BATCH, 0, {"open-result": ["rel-open"]})
    _, _, compiled = _review_compile(host.facade, graph, WEB_BINDING)
    return graph, host.facade.publish_exact_review(compiled["compile_receipt_id"])


def _publish_v2(host, v1_graph, v1):
    edge = v1_graph["graph"]["edges"][0]
    c_node = _node(v1_graph, "state-c")
    retargeted = host.facade.apply_graph_edit(
        v1_graph["logical_workflow_id"],
        v1_graph["revision"],
        v1_graph["content_sha256"],
        {
            "type": "update_edge_target",
            "edge_id": edge["edge_id"],
            "target_node_id": c_node["node_id"],
        },
        "synthetic-human-v2-retarget",
    )
    v2_graph = host.facade.apply_graph_edit(
        retargeted["logical_workflow_id"],
        retargeted["revision"],
        retargeted["content_sha256"],
        {
            "type": "update_edge_semantics",
            "edge_id": edge["edge_id"],
            "prerequisites": ["Synthetic A visible"],
            "expected_result": "Synthetic C visible",
            "stop_condition": "Synthetic C absent",
            "relationship_kinds": {"rel-open": "opens synthetic C"},
        },
        "synthetic-human-v2-semantics",
    )
    _, _, compiled = _review_compile(host.facade, v2_graph, WEB_BINDING)
    v2 = host.facade.publish_exact_review(compiled["compile_receipt_id"])
    updated_edge = next(item for item in v2_graph["graph"]["edges"] if item["edge_id"] == edge["edge_id"])
    assert updated_edge["external_step_id"] == edge["external_step_id"]
    assert updated_edge["target_node_id"] != edge["target_node_id"]
    assert updated_edge["success_conditions"] == ["Synthetic C visible"]
    assert updated_edge["success_conditions"] != edge["success_conditions"]
    assert v1["logical_workflow_id"] == v2["logical_workflow_id"]
    assert v1["version_id"] != v2["version_id"]
    assert v1["asset_id"] != v2["asset_id"]
    assert v1["asset_sha256"] != v2["asset_sha256"]
    return v2


def _runtime_factory(root, asset_store, v1_asset, windows, backend, claims, instances, gate_factory=_Gate, source_factory=None):
    source = _FreshVersionObservations(root, v1_asset) if source_factory is None else source_factory(root, v1_asset)
    resolver = _FreshVersionResolver()

    def factory(*, project_root, selection, window_manager, learning_binding):
        assert project_root == root.resolve()
        assert window_manager is windows
        bind = getattr(source, "bind_learning", None)
        if callable(bind):
            bind(learning_binding)
        runtime = LocalAgentRuntimeCallsite(
            project_root=project_root,
            asset_store=asset_store,
            claim_store=claims,
            window_manager=windows,
            controller_factory=lambda binding: LiveController(
                binding=binding,
                asset_loader=asset_store,
                observation_source=source,
                target_resolver=resolver,
                gate=gate_factory(allowed=True),
                window_visibility_checker=_WindowVisibilityChecker(bound_window_handle=4242),
                backend=backend,
                intent_claim_store=claims,
                grounding_policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2},
                verification_max_capture_attempts=1,
                verification_poll_interval_seconds=0.0,
                verification_sleeper=lambda _seconds: None,
                verification_monotonic_clock=lambda: 0.0,
            ),
            selection=selection,
            learning_binding=learning_binding,
        )
        instances.append(runtime)
        return runtime

    factory.window_manager = windows
    return factory


def test_mcp_selected_v1_preparation_stays_pinned_after_v2_publication(tmp_path):
    from tests.test_reviewed_agent_actions_stdio import (
        _PinnedReviewedObservations, _ReviewedActionGate,
    )

    root = tmp_path / "review"
    host = DesktopReviewHost(tmp_path / "inbox.json", root, REVIEWER)
    coordinator = None
    try:
        connection = host._service.reviewer_call(REVIEWER, "create_connection", {
            "task_id": TASK,
            "agent_name": "synthetic-version-pin-agent",
        })
        v1_graph, v1 = _publish_v1(host, connection)
        host._service.reviewer_call(REVIEWER, "set_workflow_memory_scope", {
            "connection_id": connection["connection_id"],
            "expected_revision": 0,
            "workflow_ids": [v1_graph["logical_workflow_id"]],
            "idempotency_key": "synthetic-version-pin-scope",
        })
        assets = ReviewedWorkflowAssetStore(project_root=root)
        v1_asset = assets.load_workflow_version(v1_graph["logical_workflow_id"], v1["version_id"])["asset"]
        windows = SimpleNamespace(bound=SimpleNamespace(handle=4242, process_id=9001, is_active=True))
        windows.get_bound_window = lambda: windows.bound
        windows.bind_window_by_handle = lambda handle: windows.bound if handle == 4242 else None
        backend = DeterministicFakeBackend()
        claims = RuntimeIntentClaimStore(
            project_root=root,
            receipt_store=RuntimeReceiptStore(project_root=root),
        )
        instances = []
        coordinator = NativeSingleStepCoordinator(
            root,
            host.facade,
            host,
            runtime_factory=_runtime_factory(
                root, assets, v1_asset, windows, backend, claims, instances,
                _ReviewedActionGate, _PinnedReviewedObservations,
            ),
            enable_agent_learning=True,
            thread_initializer=lambda: None,
            thread_finalizer=lambda: None,
        )
        started = host.start()

        async def run():
            async with stdio_client(_mcp_server(started["base_url"], connection["token"])) as streams:
                async with ClientSession(*streams, read_timeout_seconds=60) as client:
                    await client.initialize()
                    names = {tool.name for tool in (await client.list_tools()).tools}
                    assert {"get_workflow_memory", "start_learning_segment", "prepare_learning_runtime", "get_learning_runtime", "cancel_learning_runtime"} <= names
                    memory = await client.call_tool("get_workflow_memory", {
                        "workflow_id": v1_graph["logical_workflow_id"],
                        "version": v1["version_id"],
                    })
                    assert memory.is_error is False, memory
                    selected = memory.structured_content
                    assert selected["version_id"] == v1["version_id"]
                    assert selected["asset_id"] == v1["asset_id"]
                    assert selected["asset_sha256"] == v1["asset_sha256"]
                    segment = await client.call_tool("start_learning_segment", {
                        "idempotency_key": "synthetic-version-pin-segment",
                        "title": "Synthetic version pin",
                    })
                    assert segment.is_error is False, segment
                    prepare_args = {
                        "segment_id": segment.structured_content["segment_id"],
                        "idempotency_key": "synthetic-v1-prepare",
                        "asset_id": selected["asset_id"],
                        "asset_content_sha256": selected["asset_sha256"],
                        "target_window_handle": 4242,
                        "target_process_id": 9001,
                    }
                    prepared = await client.call_tool("prepare_learning_runtime", prepare_args)
                    assert prepared.is_error is False, prepared
                    v1_preparation = prepared.structured_content
                    assert v1_preparation["phase"] == "observed", v1_preparation
                    assert v1_preparation["actions"]
                    assert len(instances) == 1 and backend.attempt_count == 0

                    # 本地检查只核对已准备运行的来源；不代表动作请求或已生成预览，也不批准或执行。
                    assert coordinator._selection.asset_id == v1["asset_id"]
                    assert coordinator._selection.asset_content_sha256 == v1["asset_sha256"]
                    assert instances[0]._selection.asset_content_sha256 == v1["asset_sha256"]
                    assert instances[0]._observation.workflow.asset_content_sha256 == v1["asset_sha256"]

                    # V2 在 V1 准备之后由显式模拟人工审核发布为当前版本；旧准备不得静默改指向它。
                    v2 = _publish_v2(host, v1_graph, v1)
                    current_v2 = assets.load_workflow_version(v1_graph["logical_workflow_id"])
                    assert current_v2["version_id"] == v2["version_id"]
                    factual = await client.call_tool("get_learning_runtime", {
                        "segment_id": prepare_args["segment_id"],
                        "preparation_id": v1_preparation["preparation_id"],
                    })
                    assert factual.is_error is False, factual
                    assert factual.structured_content["preparation_id"] == v1_preparation["preparation_id"]
                    assert factual.structured_content["phase"] == "observed"
                    assert factual.structured_content["session_id"] == v1_preparation["session_id"]
                    assert factual.structured_content["actions"] == v1_preparation["actions"]
                    assert coordinator._selection.asset_content_sha256 == v1["asset_sha256"]
                    assert instances[0]._observation.workflow.asset_content_sha256 == v1["asset_sha256"]
                    # 再经过实际注册表读取核验，而不只检查之前保存的内存字段。
                    rebound = coordinator._owner.call(instances[0]._resolve_server_binding)
                    assert rebound.workflow.asset_id == v1["asset_id"]
                    assert rebound.workflow.asset_content_sha256 == v1["asset_sha256"]
                    assert backend.attempt_count == 0

                    requested = await client.call_tool("request_learning_action", {
                        "segment_id": prepare_args["segment_id"],
                        "preparation_id": v1_preparation["preparation_id"],
                        "intent_id": "intent-v1-after-v2-publication",
                        "action_id": v1_preparation["actions"][0]["action_id"],
                    })
                    assert requested.is_error is False, requested
                    native = coordinator.current_agent_review()
                    assert native["source_kind"] == "reviewed_learning"
                    assert native["preview"]["workflow"]["asset_id"] == v1["asset_id"]
                    assert native["preview"]["workflow"]["asset_content_sha256"] == v1["asset_sha256"]
                    assert native["preview"]["workflow"]["asset_id"] != v2["asset_id"]
                    coordinator.deny(
                        confirmation_id=native["confirmation_id"],
                        preview_content_sha256=native["preview"]["content_sha256"],
                    )
                    assert backend.attempt_count == 0

                    cancelled = await client.call_tool("cancel_learning_runtime", {
                        "segment_id": prepare_args["segment_id"],
                        "preparation_id": v1_preparation["preparation_id"],
                    })
                    assert cancelled.is_error is False, cancelled
                    assert cancelled.structured_content["cleanup_verified"] is True

                    # 交换到 V2 的错误摘要不得成功启动或派发；失败记录仍需按原所有权清理。
                    corrupted = await client.call_tool("prepare_learning_runtime", {
                        **prepare_args,
                        "idempotency_key": "synthetic-v2-swapped-hash",
                        "asset_id": v2["asset_id"],
                        "asset_content_sha256": v1["asset_sha256"],
                    })
                    assert corrupted.is_error is False, corrupted
                    failed = corrupted.structured_content
                    assert failed["phase"] == "failed"
                    assert failed["error_code"] == "runtime_prepare_failed"
                    assert len(instances) == 2
                    assert instances[-1]._observation is None
                    assert backend.attempt_count == 0
                    failed_cancel = await client.call_tool("cancel_learning_runtime", {
                        "segment_id": prepare_args["segment_id"],
                        "preparation_id": failed["preparation_id"],
                    })
                    assert failed_cancel.is_error is False, failed_cancel
                    assert failed_cancel.structured_content["cleanup_verified"] is True
                    return selected, v1_preparation, failed

        selected, v1_preparation, failed = asyncio.run(asyncio.wait_for(run(), timeout=120))
        assert selected["version_id"] == v1["version_id"]
        assert v1_preparation["preparation_id"] != failed["preparation_id"]
        assert backend.attempt_count == 0
    finally:
        if coordinator is not None:
            primary = sys.exc_info()[0] is not None
            try:
                coordinator.shutdown()
            except Exception:
                if not primary:
                    raise
        else:
            host.close()
