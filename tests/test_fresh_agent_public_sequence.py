"""公开 MCP 新观察串联两次 fresh 动作的隔离回归。"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
import os
from pathlib import Path
from types import SimpleNamespace
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.desktop_review.fresh_runtime_callsite import FreshLearningRuntimeCallsite
from app.desktop_review.host import DesktopReviewHost
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
from tests.test_formal_fresh_graph_source import REVIEWER
from tests.test_formal_fresh_learning_observation import _OriginReader, _ScreenshotService, _WindowManager, _bound, _owner
from tests.test_formal_fresh_runtime_session import _runtime
from tests.test_fresh_dispatch_graph import _Visible
from tests.test_fresh_learning_action_preview import _CurrentUIA, _recognize


def _mcp_server(base_url: str, token: str) -> StdioServerParameters:
    environment = {key: os.environ[key] for key in ("SystemRoot", "PATH", "TEMP", "TMP") if key in os.environ}
    environment.update(
        AGENT_LINK_BASE_URL=base_url,
        AGENT_LINK_TOKEN=token,
        PYTHONIOENCODING="utf-8",
        PYTHONDONTWRITEBYTECODE="1",
        AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=":memory:",
    )
    return StdioServerParameters(
        command=sys.executable,
        args=["-c", "from app.agent_link.mcp_bridge import run_stdio; run_stdio()"],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=environment,
    )


@contextmanager
def _public_rig(tmp_path):
    host = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", REVIEWER)
    coordinator = None
    try:
        connection = host._service.reviewer_call(REVIEWER, "create_connection", {
            "task_id": "fresh-public-sequence", "agent_name": "fresh-agent",
        })
        segment = host._service.agent_call(connection["token"], "start_learning_segment", {
            "idempotency_key": "fresh-public-segment", "title": "Fresh public sequence",
        })
        root = host.fresh_learning.archive.project_root
        windows = SimpleNamespace(bound=SimpleNamespace(handle=4242, process_id=9001, is_active=True))
        windows.get_bound_window = lambda: windows.bound
        windows.bind_window_by_handle = lambda handle: windows.bound if handle == 4242 else None
        instances = []

        def factory(*, project_root, selection, window_manager, learning_binding):
            observation_owner = _owner(
                root,
                manager=_WindowManager(*[_bound() for _ in range(60)]),
                origin=_OriginReader(*["https://fresh.example"] * 60),
                runner=_recognize,
                uia=_CurrentUIA(),
            )
            runtime, backend, _claims, _source = _runtime(
                host,
                connection,
                segment,
                {"batch_id": selection.source.reference()["batch_id"]},
                observation_owner=observation_owner,
                source=selection.source,
            )
            runtime.set_action_learning_recorder(host.learning_segments.recorder)
            runtime._window_visibility_checker = _Visible()
            callsite = FreshLearningRuntimeCallsite(controller=runtime, learning_binding=learning_binding)
            instances.append((callsite, runtime, backend, observation_owner))
            return callsite

        factory.window_manager = windows
        coordinator = NativeSingleStepCoordinator(
            root,
            host.facade,
            host,
            runtime_factory=factory,
            enable_agent_learning=True,
            thread_initializer=lambda: None,
            thread_finalizer=lambda: None,
        )
        host.start()
        yield host, coordinator, connection, segment, instances
    finally:
        if coordinator is not None:
            coordinator.shutdown()
        else:
            host.close()


def _install_public_observation_owner(tmp_path, monkeypatch):
    public_owners = []

    def public_observation_owner(**kwargs):
        owner = _owner(
            Path(kwargs["project_root"]),
            application=kwargs["application_identity"],
            screenshot=_ScreenshotService(tmp_path / "public-observations" / str(len(public_owners))),
        )
        public_owners.append(owner)
        return owner

    monkeypatch.setattr(
        "app.agent.fresh_learning_factory.create_fresh_learning_observation_owner",
        public_observation_owner,
    )
    return public_owners


async def _run_public_two_action_sequence(*, host, coordinator, connection, segment, instances, public_owners):
    async with stdio_client(_mcp_server(host.status()["base_url"], connection["token"])) as streams:
        async with ClientSession(*streams, read_timeout_seconds=60) as client:
            await client.initialize()
            names = {tool.name for tool in (await client.list_tools()).tools}
            assert {
                "observe_learning_screen",
                "prepare_fresh_learning_runtime",
                "request_fresh_learning_action",
                "get_fresh_learning_runtime",
                "cancel_fresh_learning_runtime",
            } <= names

            async def observe_prepare_execute(suffix):
                request = {
                    "segment_id": segment["segment_id"],
                    "idempotency_key": f"public-observe.{suffix}",
                    "application_identity": {
                        "kind": "web",
                        "canonical_origin": "https://fresh.example",
                    },
                    "target_window_handle": 4242,
                    "target_process_id": 9001,
                    "title": f"Public screen {suffix}",
                    "meaning": f"Public observation {suffix}",
                    "goal": None,
                }
                observed = await client.call_tool("observe_learning_screen", request)
                assert observed.is_error is False, observed
                source = observed.structured_content
                retried_observation = await client.call_tool("observe_learning_screen", request)
                assert retried_observation.is_error is False
                assert retried_observation.structured_content == source

                prepared = await client.call_tool("prepare_fresh_learning_runtime", {
                    "segment_id": segment["segment_id"],
                    "batch_id": source["batch_id"],
                    "idempotency_key": f"public-prepare.{suffix}",
                })
                assert prepared.is_error is False, prepared
                prepared_value = prepared.structured_content
                assert prepared_value["phase"] == "observed"
                scope = {
                    "segment_id": segment["segment_id"],
                    "preparation_id": prepared_value["preparation_id"],
                }
                intent = {
                    **scope,
                    "intent_id": f"public-intent.{suffix}",
                    "action_id": "action.view",
                    "semantic_action": "open_detail",
                    "goal": "View details",
                }
                pending = await client.call_tool("request_fresh_learning_action", intent)
                assert pending.is_error is False, pending
                review = coordinator.current_fresh_review()
                assert review["confirmation_id"] == pending.structured_content["confirmation_id"]
                backend = instances[-1][2]
                before_dispatch = len(backend.commands)
                assert before_dispatch == 0
                retried_request = await client.call_tool("request_fresh_learning_action", intent)
                assert retried_request.is_error is False
                assert len(backend.commands) == before_dispatch

                # 隔离夹具模拟独立原生审批；不代表真人授权。
                coordinator.approve(
                    confirmation_id=review["confirmation_id"],
                    preview_sha256=review["preview"]["preview_sha256"],
                )
                receipt = coordinator.execute(confirmation_id=review["confirmation_id"])
                assert receipt["kind"] == "receipt"
                assert len(backend.commands) == before_dispatch + 1

                factual = await client.call_tool("get_fresh_learning_runtime", scope)
                assert factual.is_error is False, factual
                current = factual.structured_content
                assert current["receipt"] == receipt["payload"]
                assert current["observation"]["observation_id"] == current["receipt"]["next_observation_id"]
                repeated_read = await client.call_tool("get_fresh_learning_runtime", scope)
                assert repeated_read.is_error is False
                assert len(backend.commands) == before_dispatch + 1

                cancelled = await client.call_tool("cancel_fresh_learning_runtime", scope)
                assert cancelled.is_error is False
                assert cancelled.structured_content["cleanup_verified"] is True
                return source, prepared_value, current["receipt"]

            first = await observe_prepare_execute("first")
            assert len(public_owners) == 1
            second = await observe_prepare_execute("second")
            assert len(public_owners) == 2
            assert first[0]["logical_workflow_id"] == second[0]["logical_workflow_id"]
            assert first[0]["batch_id"] != second[0]["batch_id"]
            assert first[0]["observation"]["capture"]["capture_id"] != second[0]["observation"]["capture"]["capture_id"]
            assert first[1]["preparation_id"] != second[1]["preparation_id"]
            assert first[1]["session_id"] != second[1]["session_id"]

            current_segment = await client.call_tool("get_learning_segment", {
                "segment_id": segment["segment_id"],
            })
            assert current_segment.is_error is False
            finished = await client.call_tool("finish_learning_segment", {
                "segment_id": segment["segment_id"],
                "expected_revision": current_segment.structured_content["revision"],
            })
            assert finished.is_error is False
            assert finished.structured_content["status"] == "closed"
            return first, second


def test_two_public_observations_drive_two_fresh_actions_in_one_segment(tmp_path, monkeypatch):
    public_owners = _install_public_observation_owner(tmp_path, monkeypatch)

    with _public_rig(tmp_path) as (host, coordinator, connection, segment, instances):
        first, second = asyncio.run(asyncio.wait_for(
            _run_public_two_action_sequence(
                host=host,
                coordinator=coordinator,
                connection=connection,
                segment=segment,
                instances=instances,
                public_owners=public_owners,
            ),
            timeout=120,
        ))
        snapshot = host.facade.load_graph_revision(first[0]["logical_workflow_id"])
        graph = snapshot["graph"]
        assert len(graph["edges"]) == 2
        assert len(snapshot["source_refs"]["action_sources"]) == 2
        source_nodes = {edge["source_node_id"] for edge in graph["edges"]}
        target_nodes = {edge["target_node_id"] for edge in graph["edges"]}
        assert source_nodes.isdisjoint(target_nodes)
        assert first[2]["next_observation_id"] != second[2]["next_observation_id"]
