"""同一学习段中两次 fresh Agent 动作的真实连续链。"""

from __future__ import annotations

import asyncio

from mcp import ClientSession
from mcp.client.stdio import stdio_client

from tests.test_fresh_agent_stdio import _rig
from tests.test_formal_fresh_learning_observation import _owner
from tests.test_formal_learning_runtime_controls import _mcp_server


def test_two_fresh_agent_actions_join_one_active_segment_graph(tmp_path):
    """每次动作都由本地人独立确认；重试和轮询绝不增加输入。"""
    with _rig(tmp_path) as (host, coordinator, connection, segment, staged, instances):
        async def run():
            async with stdio_client(_mcp_server(host.status()["base_url"], connection["token"])) as streams:
                async with ClientSession(*streams, read_timeout_seconds=60) as client:
                    await client.initialize()

                    async def prepare_and_execute(*, batch_id, suffix):
                        prepare = {"segment_id": segment["segment_id"], "batch_id": batch_id,
                                   "idempotency_key": f"prepare.{suffix}"}
                        prepared = await client.call_tool("prepare_fresh_learning_runtime", prepare)
                        assert not prepared.is_error, prepared
                        value = prepared.structured_content
                        assert value["phase"] == "observed"
                        scope = {"segment_id": segment["segment_id"], "preparation_id": value["preparation_id"]}
                        intent = {**scope, "intent_id": f"intent.{suffix}", "action_id": "action.view",
                                  "semantic_action": "open_detail", "goal": "View details"}
                        pending = await client.call_tool("request_fresh_learning_action", intent)
                        assert not pending.is_error, pending
                        review = coordinator.current_fresh_review()
                        assert review["confirmation_id"] == pending.structured_content["confirmation_id"]
                        backend = instances[-1][2]
                        before_retry = len(backend.commands)
                        repeated = await client.call_tool("request_fresh_learning_action", intent)
                        assert not repeated.is_error and len(backend.commands) == before_retry
                        coordinator.approve(confirmation_id=review["confirmation_id"],
                                            preview_sha256=review["preview"]["preview_sha256"])
                        assert len(backend.commands) == before_retry
                        try:
                            receipt = coordinator.execute(confirmation_id=review["confirmation_id"])
                        except Exception as error:
                            print(f"S31_EXECUTION_FAILURE {suffix}: {type(error).__name__}: {error}; "
                                  f"context={error.__context__!r}", flush=True)
                            raise AssertionError(
                                f"{suffix} execute failed code={getattr(error, 'code', None)} "
                                f"context={error.__context__!r} state={coordinator.learning_runtime_state()}"
                            ) from error
                        assert receipt["kind"] == "receipt" and len(backend.commands) == before_retry + 1
                        polled = await client.call_tool("get_fresh_learning_runtime", scope)
                        assert not polled.is_error and polled.structured_content["receipt"] == receipt["payload"]
                        repeated_poll = await client.call_tool("get_fresh_learning_runtime", scope)
                        assert not repeated_poll.is_error and len(backend.commands) == before_retry + 1
                        released = await client.call_tool("cancel_fresh_learning_runtime", scope)
                        assert not released.is_error and released.structured_content["cleanup_verified"] is True
                        return value, receipt["payload"], backend

                    first, first_receipt, first_backend = await prepare_and_execute(
                        batch_id=staged["batch_id"], suffix="first")
                    assert len(instances) == 1 and len(first_backend.commands) == 1

                    # 通过既有公开 fresh observation 入图路径提交新的 capture，而不是复用第一张来源。
                    packet = _owner(host.fresh_learning.archive.project_root / "sequence-second").observe(
                        target_window_handle=4242, target_process_id=9001)
                    second_stage = host.fresh_learning.stage(
                        connection_id=connection["connection_id"], task_id=connection["task_id"],
                        segment_id=segment["segment_id"], idempotency_key="sequence.second-screen",
                        title="Second screen", meaning="Second independently captured screen", packet=packet,
                    )
                    assert second_stage["logical_workflow_id"] == staged["logical_workflow_id"]
                    assert second_stage["source"]["reference"]["capture_id"] != staged["source"]["reference"]["capture_id"]

                    second, second_receipt, second_backend = await prepare_and_execute(
                        batch_id=second_stage["batch_id"], suffix="second")
                    assert len(instances) == 2
                    assert len(first_backend.commands) + len(second_backend.commands) == 2
                    return first, second, first_receipt, second_receipt

        first, second, first_receipt, second_receipt = asyncio.run(asyncio.wait_for(run(), timeout=120))
        current = host._service.agent_call(connection["token"], "get_learning_segment", {
            "segment_id": segment["segment_id"]})
        finished = host._service.agent_call(connection["token"], "finish_learning_segment", {
            "segment_id": segment["segment_id"], "expected_revision": current["revision"]})
        graph = host.facade.load_graph_revision(finished["graph"]["logical_workflow_id"])["graph"]
        node_ids = {node["node_id"] for node in graph["nodes"]}
        assert len(graph["edges"]) == 2 and len(graph["nodes"]) == 6
        assert all(edge["source_node_id"] in node_ids and edge["target_node_id"] in node_ids for edge in graph["edges"])
        assert len({edge["source_node_id"] for edge in graph["edges"]}) == 2
        assert {first_receipt["next_observation_id"], second_receipt["next_observation_id"]}.isdisjoint(
            {first["observation"]["observation_id"], second["observation"]["observation_id"]})
        assert finished["status"] == "closed"
