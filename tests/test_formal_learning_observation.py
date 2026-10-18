"""真实宿主首次观察入口的同根来源、重连和失败回归。"""

import base64
from contextlib import contextmanager
import asyncio
import os
from pathlib import Path
import sys

import pytest

from app.agent_link.contracts import AgentLinkError
from app.desktop_review.host import DesktopReviewHost
from tests.test_formal_fresh_learning_observation import _owner, _ScreenshotService
from tests.test_formal_learning_runtime_controls import _mcp_server
from mcp import ClientSession
from mcp.client.stdio import stdio_client


REVIEWER = "fresh-observation-reviewer"


@contextmanager
def _rig(root, monkeypatch):
    import app.agent.fresh_learning_factory as factory_module

    captures = []
    def factory(**kwargs):
        screenshot = _ScreenshotService(root / "capture")
        captures.append(screenshot)
        return _owner(kwargs["project_root"], application=kwargs["application_identity"], screenshot=screenshot)
    monkeypatch.setattr(factory_module, "create_fresh_learning_observation_owner", factory)
    host = DesktopReviewHost(root / "inbox.json", root / "review", REVIEWER)
    try:
        connection = host._service.reviewer_call(REVIEWER, "create_connection", {
            "task_id": "new-observation-task", "agent_name": "first-agent",
        })
        segment = host._service.agent_call(connection["token"], "start_learning_segment", {
            "idempotency_key": "new-segment", "title": "Fresh first-use learning",
        })
        yield host, connection, segment, captures
    finally:
        host.close()


def _request(segment):
    return {"segment_id": segment["segment_id"], "idempotency_key": "new-screen",
            "application_identity": {"kind": "web", "canonical_origin": "https://fresh.example"},
            "target_window_handle": 4242, "target_process_id": 9001,
            "title": "Fresh screen", "meaning": "\u5f85\u5ba1\u6838\u7684\u65b0\u89c2\u5bdf", "goal": None}


def test_agent_observes_without_asset_and_reopening_reuses_original_packet(tmp_path, monkeypatch):
    with _rig(tmp_path, monkeypatch) as (host, connection, segment, captures):
        status = host._service.agent_call(connection["token"], "status", {})
        assert status.get("learning_observation") == {
                "contract_version": "agent_learning_observation_v1", "operations": ["observe_learning_screen", "submit_observed_interface_learning"],
        }
        request = _request(segment)
        result = host._service.agent_call(connection["token"], "observe_learning_screen", request)
        assert result["contract_version"] == "agent_learning_observation_v1"
        assert result["action_executed"] is False and result["artifact_is_authorization"] is False
        image = base64.b64decode(result["screenshot"]["png_base64"], validate=True)
        assert image == captures[0].path.read_bytes()
        assert result["screenshot"]["width"] == 160 and result["screenshot"]["height"] == 100
        graph = host.facade.load_graph_revision(result["logical_workflow_id"])
        assert len(graph["graph"]["nodes"]) == 1 and graph["graph"]["edges"] == []
        assert graph["graph"]["nodes"][0]["reviewed_by_human"] is False
        repeated = host._service.agent_call(connection["token"], "observe_learning_screen", request)
        assert repeated == result
        assert len(captures) == 1 and len(captures[0].calls) == 1
        assert not (tmp_path / "review/runtime_state/reviewed-workflow-assets-v2").exists()
    reopened = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", REVIEWER)
    try:
        repeated = reopened._service.agent_call(connection["token"], "observe_learning_screen", request)
        assert repeated == result
        assert len(captures) == 1
    finally:
        reopened.close()


def test_observe_then_complete_interface_via_real_mcp_stdio(tmp_path, monkeypatch):
    with _rig(tmp_path, monkeypatch) as (host, connection, segment, _captures):
        host.start()
        async def run():
            async with stdio_client(_mcp_server(host.status()["base_url"], connection["token"])) as streams:
                async with ClientSession(*streams, read_timeout_seconds=30) as client:
                    await client.initialize()
                    observed = await client.call_tool("observe_learning_screen", _request(segment))
                    assert not observed.is_error
                    value = observed.structured_content
                    memory = value["interface_memory"]
                    payload = {"segment_id": segment["segment_id"], "batch_id": value["batch_id"],
                               "expected_revision": memory["revision"], "expected_sha256": memory["content_sha256"],
                               "meaning": "列表页", "recognition_text": "标题",
                               "regions": [{"bbox": [1, 2, 20, 20], "name": "按钮", "kind": "button", "meaning": "打开"}],
                               "idempotency_key": "interface-once"}
                    saved = await client.call_tool("submit_observed_interface_learning", payload)
                    assert not saved.is_error
                    repeated = await client.call_tool("submit_observed_interface_learning", payload)
                    assert not repeated.is_error and repeated.structured_content == saved.structured_content
                    conflict = {**payload, "meaning": "冲突"}
                    conflict_result = await client.call_tool("submit_observed_interface_learning", conflict)
                    assert conflict_result.is_error
                    empty = await client.call_tool("submit_observed_interface_learning", {**payload, "idempotency_key": "empty", "regions": []})
                    assert empty.is_error
                    loaded = await client.call_tool("get_interface_memory", {"interface_id": saved.structured_content["interface_id"]})
                    assert not loaded.is_error
                    return saved.structured_content, loaded.structured_content
        saved, loaded = asyncio.run(run())
        assert loaded["content"]["regions"][0]["region_id"].startswith("region-user-")


@pytest.mark.parametrize("case", ["same_task_other_connection", "foreign_task", "closed_segment", "outside_image", "human_revision", "mismatched_hash"])
def test_observed_interface_learning_real_host_negative_cases_do_not_create_version(tmp_path, monkeypatch, case):
    with _rig(tmp_path, monkeypatch) as (host, connection, segment, _captures):
        observed = host._service.agent_call(connection["token"], "observe_learning_screen", _request(segment))
        memory = observed["interface_memory"]
        interface_id = memory["interface_id"]
        payload = {
            "segment_id": segment["segment_id"], "batch_id": observed["batch_id"],
            "expected_revision": memory["revision"], "expected_sha256": memory["content_sha256"],
            "meaning": "列表页", "recognition_text": "标题",
            "regions": [{"bbox": [1, 2, 20, 20], "name": "按钮", "kind": "button", "meaning": "打开"}],
            "idempotency_key": "negative-case",
        }
        before = host.facade.get_interface_memory(connection["task_id"], interface_id)
        token = connection["token"]
        if case in {"same_task_other_connection", "foreign_task"}:
            other = host._service.reviewer_call(REVIEWER, "create_connection", {
                "task_id": connection["task_id"] if case == "same_task_other_connection" else "foreign-task",
                "agent_name": "negative-agent",
            })
            token = other["token"]
        elif case == "closed_segment":
            current_segment = host._service._store.read(lambda state: state["connections"][connection["connection_id"]]["learning_segments"][segment["segment_id"]])
            host._service.agent_call(token, "finish_learning_segment", {
                "segment_id": segment["segment_id"], "expected_revision": current_segment["revision"],
            })
        elif case == "outside_image":
            payload["regions"] = [{**payload["regions"][0], "bbox": [150, 90, 20, 20]}]
        elif case == "human_revision":
            host.facade.save_interface_content(interface_id, memory["revision"], memory["content_sha256"], {
                "meaning": "人工修订", "recognition_text": "", "regions": []}, "human-edit")
        elif case == "mismatched_hash":
            payload["expected_sha256"] = "0" * 64
        with pytest.raises(AgentLinkError) as denied:
            host._service.agent_call(token, "submit_observed_interface_learning", payload)
        assert denied.value.code in {"not_found", "stale_revision", "invalid_arguments"}
        after = host.facade.get_interface_memory(connection["task_id"], interface_id)
        assert after["version_id"] == before["version_id"] if case != "human_revision" else after["version_id"] != before["version_id"]


def test_invalid_or_foreign_observation_request_never_captures(tmp_path, monkeypatch):
    with _rig(tmp_path, monkeypatch) as (host, connection, segment, captures):
        request = _request(segment)
        for extra in ({"task_id": "injected"}, {"connection_id": "injected"},
                      {"screenshot_path": "C:/private.png"}, {"target_window_handle": True},
                      {"application_identity": {"kind": "web", "canonical_origin": "https://fresh.example/path"}}):
            with pytest.raises(AgentLinkError) as denied:
                host._service.agent_call(connection["token"], "observe_learning_screen", {**request, **extra})
            assert denied.value.code == "invalid_arguments"
        other = host._service.reviewer_call(REVIEWER, "create_connection", {
            "task_id": connection["task_id"], "agent_name": "another-agent",
        })
        with pytest.raises(AgentLinkError) as foreign:
            host._service.agent_call(other["token"], "observe_learning_screen", request)
        assert foreign.value.code == "not_found"
        assert captures == []


def test_changed_observation_request_is_not_an_implicit_new_capture(tmp_path, monkeypatch):
    with _rig(tmp_path, monkeypatch) as (host, connection, segment, captures):
        request = _request(segment)
        host._service.agent_call(connection["token"], "observe_learning_screen", request)
        for change in ({"meaning": "Different"}, {"goal": "Read this"}, {"target_window_handle": 5555}):
            with pytest.raises(AgentLinkError) as conflict:
                host._service.agent_call(connection["token"], "observe_learning_screen", {**request, **change})
            assert conflict.value.code == "idempotency_conflict"
        assert len(captures) == 1


def test_corrupt_committed_observation_is_not_repaired_by_recapture(tmp_path, monkeypatch):
    with _rig(tmp_path, monkeypatch) as (host, connection, segment, captures):
        request = _request(segment)
        host._service.agent_call(connection["token"], "observe_learning_screen", request)
        records = list((tmp_path / "review/runtime_state/fresh-learning-v1/records").glob("*.json"))
        assert len(records) == 1
        records[0].write_bytes(b"{}")
        with pytest.raises(AgentLinkError) as missing:
            host._service.agent_call(connection["token"], "observe_learning_screen", request)
        assert missing.value.code == "learning_source_unavailable"
        assert len(captures) == 1


def test_failed_observation_does_not_stage_a_success_or_expose_local_error(tmp_path, monkeypatch):
    import app.agent.fresh_learning_factory as factory_module
    with _rig(tmp_path, monkeypatch) as (host, connection, segment, captures):
        def failing(**kwargs):
            raise ValueError("private C:/Users/example/profile failure")
        monkeypatch.setattr(factory_module, "create_fresh_learning_observation_owner", failing)
        with pytest.raises(AgentLinkError) as failed:
            host._service.agent_call(connection["token"], "observe_learning_screen", _request(segment))
        assert failed.value.code == "observation_failed"
        assert "C:/" not in str(failed.value)
        assert host.facade.list_batches() == []
        assert captures == []


def test_real_mcp_observation_returns_original_image_and_same_native_graph(tmp_path, monkeypatch):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    with _rig(tmp_path, monkeypatch) as (host, connection, segment, captures):
        host.start()
        environment = {key: os.environ[key] for key in ("SystemRoot", "PATH", "TEMP", "TMP") if key in os.environ}
        environment.update(AGENT_LINK_BASE_URL=host.status()["base_url"], AGENT_LINK_TOKEN=connection["token"],
            PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1", AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=":memory:")
        server = StdioServerParameters(command=sys.executable,
            args=["-c", "from app.agent_link.mcp_bridge import run_stdio; run_stdio()"],
            cwd=str(Path(__file__).resolve().parents[1]), env=environment)
        async def check():
            async with stdio_client(server) as streams:
                async with ClientSession(*streams, read_timeout_seconds=30) as client:
                    await client.initialize()
                    assert "observe_learning_screen" in {tool.name for tool in (await client.list_tools()).tools}
                    reply = await client.call_tool("observe_learning_screen", _request(segment))
                    assert reply.is_error is False, reply
                    content = reply.structured_content
                    image = next(item for item in reply.content if item.type == "image")
                    assert base64.b64decode(image.data) == captures[0].path.read_bytes()
                    assert "png_base64" not in content["screenshot"]
                    assert all(image.data not in item.text for item in reply.content if item.type == "text")
                    assert content["action_executed"] is False
                    graph = host.facade.load_graph_revision(content["logical_workflow_id"])
                    assert len(graph["graph"]["nodes"]) == 1 and graph["graph"]["edges"] == []
                    repeated = await client.call_tool("observe_learning_screen", _request(segment))
                    assert repeated.is_error is False and repeated.structured_content == content
                    assert len(captures) == 1
        asyncio.run(asyncio.wait_for(check(), timeout=60))


@pytest.mark.parametrize("stop", ["close_segment", "revoke"])
def test_stopped_scope_cannot_capture_a_first_screen(tmp_path, monkeypatch, stop):
    with _rig(tmp_path, monkeypatch) as (host, connection, segment, captures):
        if stop == "close_segment":
            host._service.agent_call(connection["token"], "finish_learning_segment", {
                "segment_id": segment["segment_id"], "expected_revision": segment["revision"],
            })
        else:
            host._service.reviewer_call(REVIEWER, "revoke_connection", {
                "connection_id": connection["connection_id"], "idempotency_key": "revoke-first",
            })
        with pytest.raises(AgentLinkError):
            host._service.agent_call(connection["token"], "observe_learning_screen", _request(segment))
        assert captures == [] and host.facade.list_batches() == []


@pytest.mark.parametrize("revoke_during_capture", [False, True])
def test_busy_observation_does_not_start_another_capture(tmp_path, monkeypatch, revoke_during_capture):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    import app.agent.fresh_learning_factory as factory_module

    with _rig(tmp_path, monkeypatch) as (host, connection, segment, captures):
        factory = factory_module.create_fresh_learning_observation_owner
        entered, release = threading.Event(), threading.Event()
        def held(**kwargs):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test observation was not released")
            return factory(**kwargs)
        monkeypatch.setattr(factory_module, "create_fresh_learning_observation_owner", held)
        with ThreadPoolExecutor(max_workers=1) as pool:
            running = pool.submit(host._service.agent_call, connection["token"], "observe_learning_screen", _request(segment))
            try:
                assert entered.wait(5)
                with pytest.raises(AgentLinkError) as busy:
                    host._service.agent_call(connection["token"], "observe_learning_screen", _request(segment))
                assert busy.value.code == "learning_busy"
                if revoke_during_capture:
                    host._service.reviewer_call(REVIEWER, "revoke_connection", {
                        "connection_id": connection["connection_id"], "idempotency_key": "revoke-running",
                    })
            finally:
                release.set()
            if revoke_during_capture:
                with pytest.raises(AgentLinkError) as revoked:
                    running.result(timeout=10)
                assert revoked.value.code == "connection_revoked"
                assert host.facade.list_batches() == []
                assert not list((tmp_path / "review/runtime_state/fresh-learning-v1/records").glob("*.json"))
                return
            result = running.result(timeout=10)
        assert len(captures) == 1
        assert host._service.agent_call(connection["token"], "observe_learning_screen", _request(segment)) == result


def test_graph_creation_failure_reuses_committed_packet_on_retry(tmp_path, monkeypatch):
    from app.desktop_review.workspace import DesktopReviewError

    with _rig(tmp_path, monkeypatch) as (host, connection, segment, captures):
        create = host.facade.create_graph_revision
        def fail_graph(*args, **kwargs):
            raise DesktopReviewError("graph write unavailable")
        monkeypatch.setattr(host.facade, "create_graph_revision", fail_graph)
        with pytest.raises(AgentLinkError):
            host._service.agent_call(connection["token"], "observe_learning_screen", _request(segment))
        assert len(host.facade.list_batches()) == 1
        monkeypatch.setattr(host.facade, "create_graph_revision", create)
        recovered = host._service.agent_call(connection["token"], "observe_learning_screen", _request(segment))
        assert len(host.facade.load_graph_revision(recovered["logical_workflow_id"])["graph"]["nodes"]) == 1
        assert len(captures) == 1
