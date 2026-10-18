"""长控制请求使用足够等待预算；超时不证明未执行，也不触发重发。"""
from io import BytesIO
import json
from urllib.error import HTTPError, URLError

import pytest

from app.agent_link import mcp_bridge


BASE = "http://127.0.0.1:49199"
TOKEN = "synthetic-transport-test-token"
LONG_OPERATIONS = (
    "prepare_learning_runtime", "request_learning_action", "observe_learning_screen",
    "prepare_fresh_learning_runtime", "request_fresh_learning_action",
    "cancel_learning_runtime", "cancel_fresh_learning_runtime", "finish_learning_segment",
    "inspect_learning_content", "read_learning_content",
    "get_workflow_project_memory",
)


@pytest.mark.parametrize("operation", LONG_OPERATIONS)
def test_known_long_operation_passes_long_budget_to_single_request(monkeypatch, operation):
    calls = []
    result = {"synthetic": True}

    class Opener:
        def open(self, request, timeout):
            calls.append((request.full_url, timeout))
            return BytesIO(json.dumps(result).encode("utf-8"))

    monkeypatch.setattr(mcp_bridge, "build_opener", lambda *_: Opener())
    assert mcp_bridge._call(BASE, TOKEN, operation, {}) == result
    assert calls == [(BASE + "/agent/" + operation, 180)]


@pytest.mark.parametrize("operation", (
    "status", "start_learning_segment", "get_learning_segment", "get_learning_runtime",
    "get_fresh_learning_runtime", "get_learning_action_result", "unknown_operation",
))
def test_lightweight_and_unknown_operations_keep_short_budget(operation):
    assert mcp_bridge._timeout_seconds(operation) == 10


@pytest.mark.parametrize("operation", ['cancel_fresh_learning_runtime', 'inspect_learning_content', 'read_learning_content'])
@pytest.mark.parametrize("wrapped", [False, True])
def test_transport_timeout_reports_unknown_outcome_without_retry(monkeypatch, wrapped, operation):
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append(request.full_url)
            error = TimeoutError("private runtime path must not escape")
            raise URLError(error) if wrapped else error

    monkeypatch.setattr(mcp_bridge, "build_opener", lambda *_: Opener())
    with pytest.raises(RuntimeError, match="outcome is unknown") as caught:
        mcp_bridge._call(BASE, TOKEN, operation, {})
    assert len(calls) == 1
    assert "private runtime path" not in str(caught.value)
    assert "unavailable" not in str(caught.value)


def test_cleanup_pending_service_error_stays_distinct_and_is_not_retried(monkeypatch):
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append(timeout)
            raise HTTPError(request.full_url, 409, "Conflict", {}, BytesIO(
                b'{"error":{"code":"runtime_cleanup_pending"}}'))

    monkeypatch.setattr(mcp_bridge, "build_opener", lambda *_: Opener())
    with pytest.raises(mcp_bridge.AgentLinkLearningRuntimeError) as caught:
        mcp_bridge._call(BASE, TOKEN, "cancel_fresh_learning_runtime", {})
    assert caught.value.code == "runtime_cleanup_pending"
    assert calls == [180]


def test_connection_failure_is_not_claimed_to_be_a_timeout(monkeypatch):
    class Opener:
        def open(self, request, timeout):
            raise URLError(ConnectionRefusedError("synthetic refused connection"))

    monkeypatch.setattr(mcp_bridge, "build_opener", lambda *_: Opener())
    with pytest.raises(RuntimeError, match="service is unavailable"):
        mcp_bridge._call(BASE, TOKEN, "status", {})


@pytest.mark.parametrize("error_response", [False, True])
def test_response_body_timeout_keeps_unknown_outcome(monkeypatch, error_response):
    calls = []

    class StalledBody(BytesIO):
        def read(self, *_):
            raise TimeoutError("synthetic body timeout")

    class Opener:
        def open(self, request, timeout):
            calls.append(timeout)
            if error_response:
                raise HTTPError(request.full_url, 409, "Conflict", {}, StalledBody())
            return StalledBody()

    monkeypatch.setattr(mcp_bridge, "build_opener", lambda *_: Opener())
    with pytest.raises(mcp_bridge.AgentLinkTransportTimeout) as caught:
        mcp_bridge._call(BASE, TOKEN, "finish_learning_segment", {})
    assert caught.value.code == "transport_timeout_outcome_unknown"
    assert calls == [180]


@pytest.mark.parametrize("operation, helper", (
    ("cancel_learning_runtime", mcp_bridge._learning_runtime_tool_call),
    ("cancel_fresh_learning_runtime", mcp_bridge._learning_runtime_tool_call),
    ("finish_learning_segment", mcp_bridge._learning_tool_call),
))
def test_public_control_timeout_remains_actionable_without_error_detail_leak(monkeypatch, operation, helper):
    from mcp.server.mcpserver.exceptions import ToolError
    calls = []

    class Opener:
        def open(self, request, timeout):
            calls.append(request.full_url)
            raise TimeoutError("private transport details")

    monkeypatch.setattr(mcp_bridge, "build_opener", lambda *_: Opener())
    with pytest.raises(ToolError, match="transport_timeout_outcome_unknown") as caught:
        helper(BASE, TOKEN, operation, {})
    assert "outcome is unknown" in str(caught.value)
    assert "Read the same operation status" in str(caught.value)
    assert "private transport details" not in str(caught.value)
    assert len(calls) == 1


def test_cleanup_receipt_is_not_upgraded_by_longer_transport_budget(monkeypatch):
    result = {"phase": "cleanup_required", "cleanup_verified": False,
              "artifact_is_authorization": False, "operation_dispatches_input": False}

    class Opener:
        def open(self, request, timeout):
            return BytesIO(json.dumps(result).encode("utf-8"))

    monkeypatch.setattr(mcp_bridge, "build_opener", lambda *_: Opener())
    assert mcp_bridge._call(BASE, TOKEN, "cancel_fresh_learning_runtime", {}) == result
