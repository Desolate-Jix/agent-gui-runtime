"""真实客户端协议由替身 MCP 边界验证，不启动宿主。"""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path

import pytest

from scripts.learning_benchmark_client import LearningBenchmarkClient
from scripts.smoke_instant_mcp import server_arguments


class ToolResult:
    def __init__(self, value, *, error=False):
        self.structuredContent = value
        self.is_error = error


class FakeSDK:
    def __init__(self):
        self.calls = []
        self.session_enters = 0
        self.session_exits = 0
        self.progress = 0
        self.ready = True
        self.stopped = False
        self.agent_initial = None
        self.agent_statuses = []
        self.pending_agent_status = False
        self.misbind_agent_status = False

    @staticmethod
    def agent_receipt(request_id, command_id, state):
        return {"request_id": request_id, "status": "returned", "result": {
            "contract_version": "agent_command.v1", "command_id": command_id, "status": state}}

    @asynccontextmanager
    async def transport(self, params):
        self.params = params
        yield "read", "write"

    def client(self, read, write):
        assert (read, write) == ("read", "write")
        sdk = self

        class Session:
            async def __aenter__(self):
                sdk.session_enters += 1
                return self

            async def __aexit__(self, *args):
                sdk.session_exits += 1

            async def initialize(self):
                return None

            async def call_tool(self, name, args):
                sdk.calls.append((name, args))
                if name == "instant_start":
                    return ToolResult({"status": "starting"})
                if name == "instant_status":
                    sdk.progress += 1
                    return ToolResult({"phase": "stopped", "cleanup_verified": True, "host_alive": False}
                                      if sdk.stopped else
                                      {"phase": "ready" if sdk.ready else "starting",
                                       "session_directory": "new-session", "host_alive": True,
                                       "cleanup_verified": False})
                if name == "instant_run":
                    command = args["command"]
                    if command["kind"] == "step" and sdk.agent_initial is not None:
                        return ToolResult(sdk.agent_receipt(args["request_id"], args["request_id"], sdk.agent_initial))
                    if command["kind"] == "agent_command_status":
                        if sdk.pending_agent_status:
                            return ToolResult({"request_id": args["request_id"], "status": "pending"})
                        state = sdk.agent_statuses.pop(0)
                        command_id = "different-command" if sdk.misbind_agent_status else command["request"]["command_id"]
                        return ToolResult(sdk.agent_receipt(args["request_id"], command_id, state))
                    return ToolResult({"request_id": args["request_id"], "status": "pending", "wait_expired": True})
                if name == "instant_result":
                    if sdk.pending_agent_status and args["request_id"].startswith("agent-status-"):
                        return ToolResult({"request_id": args["request_id"], "status": "pending"})
                    return ToolResult({"request_id": args["request_id"], "status": "returned", "operation_succeeded": True})
                if name == "instant_stop":
                    sdk.stopped = True
                    return ToolResult({"status": "stopping"})
                return ToolResult({"status": "returned", "request_id": args.get("request_id")})

        return Session()


class ControlSDK(FakeSDK):
    def __init__(self, states, *, pending=False, wrong_worker=False):
        super().__init__()
        self.states = list(states)
        self.control_pending = pending
        self.wrong_worker = wrong_worker

    def client(self, read, write):
        session = super().client(read, write)
        original = session.call_tool

        async def call_tool(name, args):
            if name == "instant_run" and args["command"]["kind"] in {"agent_command_status", "agent_command_continue"}:
                self.calls.append((name, args))
                if self.control_pending:
                    return ToolResult({"request_id": args["request_id"], "status": "pending"})
                worker = "wrong-worker" if self.wrong_worker else args["command"]["request"]["command_id"]
                return ToolResult(self.agent_receipt(args["request_id"], worker, self.states.pop(0)))
            if name == "instant_result" and self.control_pending:
                self.calls.append((name, args))
                self.control_pending = False
                return ToolResult(self.agent_receipt(args["request_id"], "original-input", self.states.pop(0)))
            return await original(name, args)

        session.call_tool = call_tool
        return session


def client(tmp_path, sdk, *, allow_actions=False, ready_timeout=1, decision_profile=None):
    return LearningBenchmarkClient(root=Path(__file__).resolve().parents[1], data_root=tmp_path / "data",
        evidence_dir=tmp_path / "evidence", recognition_source="agent_current", allow_actions=allow_actions,
        transport_factory=sdk.transport, client_factory=sdk.client,
        params_factory=lambda **kwargs: kwargs, poll_interval=.001,
        ready_timeout=ready_timeout, cleanup_timeout=1, decision_profile=decision_profile)


def test_optional_decision_profile_reaches_actual_server_arguments_without_loading_key(tmp_path, monkeypatch):
    sdk = FakeSDK()
    profile = tmp_path / "not-read-decision-profile.json"
    monkeypatch.setenv("BENCHMARK_INHERITED_SENTINEL", "original-environment")
    async def scenario():
        async with client(tmp_path, sdk, decision_profile=profile):
            pass
    asyncio.run(scenario())
    arguments = sdk.params["args"]
    assert arguments[arguments.index("--decision-profile") + 1] == str(profile.resolve())
    assert not profile.exists()
    assert sdk.params["env"]["BENCHMARK_INHERITED_SENTINEL"] == "original-environment"
    assert [name for name, args in sdk.calls] == ["instant_start", "instant_status", "instant_stop", "instant_status"]


def test_missing_decision_profile_keeps_original_startup_arguments(tmp_path):
    sdk = FakeSDK()
    async def scenario():
        async with client(tmp_path, sdk):
            pass
    asyncio.run(scenario())
    assert sdk.params["args"] == [str(Path(__file__).resolve().parents[1] / "scripts" / "start_instant_mcp.py"),
        "--data-dir", str((tmp_path / "data").resolve()), "--recognition-source", "agent_current", "--allow-local-input"]


def test_decision_profile_requires_absolute_path_before_transport(tmp_path):
    sdk = FakeSDK()
    with pytest.raises(ValueError, match="decision_profile"):
        client(tmp_path, sdk, decision_profile=Path("relative-decision.json"))
    assert sdk.calls == [] and sdk.session_enters == 0
    with pytest.raises(ValueError, match="absolute"):
        server_arguments(tmp_path, None, tmp_path / "data", recognition_source="agent_current",
                         decision_profile=Path("relative-decision.json"))


def test_one_connection_original_id_and_cleanup(tmp_path):
    sdk = FakeSDK()
    async def scenario():
        async with client(tmp_path, sdk) as opened:
            assert opened.session_directory == "new-session"
            result = await opened.run("capture-1", {"kind": "capture"}, total_timeout=1)
            assert result["status"] == "returned"
            assert opened.status["phase"] == "ready"
    asyncio.run(scenario())
    assert sdk.session_enters == sdk.session_exits == 1
    assert [name for name, _ in sdk.calls].count("instant_run") == 1
    assert ("instant_result", {"request_id": "capture-1", "detail": "full", "images": "none"}) in sdk.calls
    assert sdk.calls[-2][0] == "instant_stop" and sdk.calls[-1][0] == "instant_status"
    rows = [json.loads(line) for line in (tmp_path / "evidence" / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all(set(row) == {"tool", "request_id", "status", "elapsed_ms"} for row in rows)
    assert "capture-1" in [row["request_id"] for row in rows]


def test_read_only_rejects_input_before_transport_and_never_logs_values(tmp_path):
    sdk = FakeSDK()
    async def scenario():
        async with client(tmp_path, sdk) as opened:
            with pytest.raises(ValueError, match="read_only"):
                await opened.run("click-1", {"kind": "step", "operation": "execute_recognition_plan",
                                             "request": {"goal": "SECRET-VALUE"}})
            result = await opened.run("meta-1", {"kind": "learning_start", "request": {"scope": "interface", "title": "SECRET-VALUE"}})
            assert result["status"] == "returned"
    asyncio.run(scenario())
    assert not any(args.get("request_id") == "click-1" for _, args in sdk.calls)
    assert "SECRET-VALUE" not in (tmp_path / "evidence" / "calls.jsonl").read_text(encoding="utf-8")


def test_timeout_returns_pending_original_id_without_resubmit(tmp_path):
    sdk = FakeSDK()
    async def scenario():
        async with client(tmp_path, sdk) as opened:
            result = await opened.run("capture-2", {"kind": "capture"}, total_timeout=0)
            assert result["request_id"] == "capture-2" and result["status"] == "pending"
    asyncio.run(scenario())
    assert [name for name, _ in sdk.calls].count("instant_run") == 1
    assert not any(name == "instant_result" for name, _ in sdk.calls)
    assert next(args for name, args in sdk.calls if name == "instant_run")["wait_ms"] == 0


def test_startup_timeout_still_stops_same_connection(tmp_path):
    sdk = FakeSDK()
    sdk.ready = False
    async def scenario():
        with pytest.raises(TimeoutError, match="not_ready"):
            async with client(tmp_path, sdk, ready_timeout=.01):
                pass
    asyncio.run(scenario())
    assert [name for name, _ in sdk.calls].count("instant_start") == 1
    assert [name for name, _ in sdk.calls].count("instant_stop") == 1
    assert sdk.session_enters == sdk.session_exits == 1


def test_direct_submit_is_guarded_and_explicit_action_mode_is_distinct(tmp_path):
    sdk = FakeSDK()
    command = {"kind": "step", "operation": "execute_recognition_plan", "request": {"goal": "Open"}}
    async def scenario():
        async with client(tmp_path / "read", sdk) as opened:
            with pytest.raises(ValueError, match="read_only"):
                await opened.call("instant_submit", {"request_id": "step-1", "command": command})
        active = FakeSDK()
        async with client(tmp_path / "action", active, allow_actions=True) as opened:
            assert (await opened.call("instant_submit", {"request_id": "step-2", "command": command}))["status"] == "returned"
        return active
    active = asyncio.run(scenario())
    assert not any(name == "instant_submit" for name, _ in sdk.calls)
    assert [name for name, _ in active.calls].count("instant_submit") == 1


def test_agent_running_uses_new_status_ids_until_terminal(tmp_path):
    sdk = FakeSDK()
    sdk.agent_initial = "running"
    sdk.agent_statuses = ["running", "completed"]
    async def scenario():
        async with client(tmp_path, sdk, allow_actions=True) as opened:
            return await opened.run("original-1", {"kind": "step", "operation": "execute_recognition_plan",
                                                  "request": {"goal": "Open"}}, total_timeout=1)
    result = asyncio.run(scenario())
    statuses = [args for name, args in sdk.calls if name == "instant_run"
                and args["command"]["kind"] == "agent_command_status"]
    assert result["client_state"] == "terminal"
    assert result["result"]["status"] == "completed"
    assert result["original_request_id"] == result["command_id"] == "original-1"
    assert len(statuses) == 2 and len({row["request_id"] for row in statuses}) == 2
    assert all(row["command"]["request"]["command_id"] == "original-1" for row in statuses)
    assert result["current_status_request_id"] == statuses[-1]["request_id"] == result["request_id"]
    assert not any(name == "instant_result" and args["request_id"] == "original-1" for name, args in sdk.calls)


def test_agent_awaiting_grounding_returns_without_status_or_input_replay(tmp_path):
    sdk = FakeSDK()
    sdk.agent_initial = "awaiting_grounding"
    async def scenario():
        async with client(tmp_path, sdk, allow_actions=True) as opened:
            return await opened.run("original-2", {"kind": "step", "operation": "execute_recognition_plan",
                                                  "request": {"goal": "Open"}}, total_timeout=1)
    result = asyncio.run(scenario())
    assert result["client_state"] == "awaiting_grounding"
    assert result["original_request_id"] == result["command_id"] == "original-2"
    assert [name for name, _ in sdk.calls].count("instant_run") == 1


def test_agent_status_query_timeout_reuses_only_that_query_id(tmp_path):
    sdk = FakeSDK()
    sdk.agent_initial = "running"
    sdk.pending_agent_status = True
    async def scenario():
        async with client(tmp_path, sdk, allow_actions=True) as opened:
            return await opened.run("original-3", {"kind": "step", "operation": "execute_recognition_plan",
                                                  "request": {"goal": "Open"}}, total_timeout=.02)
    result = asyncio.run(scenario())
    current = result["current_status_request_id"]
    assert result["client_state"] == "pending" and result["no_replay"] is True
    assert result["original_request_id"] == result["command_id"] == "original-3"
    assert current.startswith("agent-status-") and result["next"]["arguments"]["request_id"] == current
    assert all(args["request_id"] == current for name, args in sdk.calls if name == "instant_result")
    assert [args["command"]["kind"] for name, args in sdk.calls if name == "instant_run"] == [
        "step", "agent_command_status"]


def test_workflow_action_allowlist_blocks_future_execution_actions(tmp_path):
    sdk = FakeSDK()
    async def scenario():
        async with client(tmp_path, sdk) as opened:
            with pytest.raises(ValueError, match="read_only"):
                await opened.call("instant_submit", {"request_id": "future-run", "command": {
                    "kind": "learning_workflow", "request": {"action": "run", "run_id": "trial"}}})
            return await opened.call("instant_submit", {"request_id": "verify-one", "command": {
                "kind": "learning_workflow", "request": {"action": "verify", "run_id": "trial",
                                                       "execution_request_id": "original"}}})
    assert asyncio.run(scenario())["status"] == "returned"
    assert not any(args.get("request_id") == "future-run" for _, args in sdk.calls)


def test_readonly_client_can_compile_recorded_evidence(tmp_path):
    sdk = FakeSDK()
    command = {"kind": "learning_workflow", "request": {"action": "compile",
        "learning_session_id": "learning-" + "a" * 32}}
    async def scenario():
        async with client(tmp_path, sdk) as opened:
            return await opened.call("instant_submit", {"request_id": "compile-read", "command": command})
    assert asyncio.run(scenario())["status"] == "returned"
    assert ("instant_submit", {"request_id": "compile-read", "command": command}) in sdk.calls


@pytest.mark.parametrize("command_request", [
    {"action": "synthesis_prepare", "learning_session_id": "learning-" + "a" * 32},
    {"action": "synthesis_status", "synthesis_id": "synthesis-" + "b" * 32},
    {"action": "synthesis_complete", "synthesis_id": "synthesis-" + "b" * 32,
     "source_sha256": "c" * 64, "parameter_bindings": {}, "annotations": {}},
])
def test_readonly_client_allows_learning_synthesis_handoff(tmp_path, command_request):
    sdk = FakeSDK()
    command = {"kind": "learning_workflow", "request": command_request}

    async def scenario():
        async with client(tmp_path, sdk) as opened:
            return await opened.call("instant_submit", {"request_id": "synthesis-safe", "command": command})

    assert asyncio.run(scenario())["status"] == "returned"
    assert ("instant_submit", {"request_id": "synthesis-safe", "command": command}) in sdk.calls


def test_agent_status_cannot_switch_original_command_identity(tmp_path):
    sdk = FakeSDK()
    sdk.agent_initial = "running"
    sdk.agent_statuses = ["completed"]
    sdk.misbind_agent_status = True
    async def scenario():
        async with client(tmp_path, sdk, allow_actions=True) as opened:
            with pytest.raises(ValueError, match="identity_mismatch"):
                await opened.run("original-4", {"kind": "step", "operation": "execute_recognition_plan",
                                                "request": {"goal": "Open"}}, total_timeout=1)
    asyncio.run(scenario())
    assert [name for name, _ in sdk.calls].count("instant_run") == 2


def test_agent_status_can_return_awaiting_grounding_without_another_probe(tmp_path):
    sdk = FakeSDK()
    sdk.agent_initial = "running"
    sdk.agent_statuses = ["awaiting_grounding"]
    async def scenario():
        async with client(tmp_path, sdk, allow_actions=True) as opened:
            return await opened.run("original-5", {"kind": "step", "operation": "execute_recognition_plan",
                                                  "request": {"goal": "Open"}}, total_timeout=1)
    result = asyncio.run(scenario())
    assert result["client_state"] == "awaiting_grounding"
    assert result["result"]["status"] == "awaiting_grounding"
    assert result["current_status_request_id"] == result["request_id"]
    assert [name for name, _ in sdk.calls].count("instant_run") == 2


@pytest.mark.parametrize("kind", ["agent_command_status", "agent_command_continue"])
@pytest.mark.parametrize("state", ["completed", "awaiting_grounding", "running"])
def test_explicit_worker_control_preserves_outer_and_input_identities(tmp_path, kind, state):
    sdk = ControlSDK([state, "completed"])
    command = {"kind": kind, "request": {"command_id": "original-input"}}
    if kind == "agent_command_continue":
        command["request"]["grounding_request_id"] = "original-grounding"
    async def scenario():
        async with client(tmp_path, sdk, allow_actions=True) as opened:
            return await opened.run("original-control", command, total_timeout=1)
    result = asyncio.run(scenario())
    assert result["original_request_id"] == "original-control"
    assert result["command_id"] == "original-input"
    calls = [args for name, args in sdk.calls if name == "instant_run"]
    assert calls[0]["request_id"] == "original-control"
    if state == "running":
        assert len(calls) == 2 and calls[1]["command"] == {
            "kind": "agent_command_status", "request": {"command_id": "original-input"}}
        assert result["current_status_request_id"] == calls[1]["request_id"]
    else:
        assert len(calls) == 1 and result["current_status_request_id"] == "original-control"


@pytest.mark.parametrize("kind", ["agent_command_status", "agent_command_continue"])
def test_pending_original_control_reads_only_its_outer_id(tmp_path, kind):
    sdk = ControlSDK(["completed"], pending=True)
    async def scenario():
        async with client(tmp_path, sdk, allow_actions=True) as opened:
            return await opened.run("original-control", {"kind": kind, "request": {
                "command_id": "original-input", **({"grounding_request_id": "grounding-one"}
                if kind == "agent_command_continue" else {})}}, total_timeout=1)
    result = asyncio.run(scenario())
    assert result["command_id"] == "original-input"
    assert [args["request_id"] for name, args in sdk.calls if name == "instant_result"] == ["original-control"]
    assert len([1 for name, _ in sdk.calls if name == "instant_run"]) == 1


@pytest.mark.parametrize("kind", ["agent_command_status", "agent_command_continue"])
def test_explicit_control_rejects_different_worker(tmp_path, kind):
    sdk = ControlSDK(["completed"], wrong_worker=True)
    async def scenario():
        async with client(tmp_path, sdk, allow_actions=True) as opened:
            with pytest.raises(ValueError, match="identity_mismatch"):
                await opened.run("control-one", {"kind": kind, "request": {
                    "command_id": "original-input"}}, total_timeout=1)
    asyncio.run(scenario())


@pytest.mark.parametrize("kind", ["agent_command_status", "agent_command_continue"])
@pytest.mark.parametrize("pending", [False, True])
def test_control_timeout_next_never_replays_input_or_continue(tmp_path, kind, pending):
    sdk = ControlSDK(["running"], pending=pending)
    async def scenario():
        async with client(tmp_path, sdk, allow_actions=True) as opened:
            return await opened.run("control-timeout", {"kind": kind, "request": {
                "command_id": "original-input"}}, total_timeout=0)
    result = asyncio.run(scenario())
    assert result["no_replay"] is True and result["command_id"] == "original-input"
    assert result["current_status_request_id"] == "control-timeout"
    if pending:
        assert result["next"]["tool"] == "instant_result"
        assert result["next"]["arguments"]["request_id"] == "control-timeout"
    else:
        assert result["next"]["arguments"]["request_id"] != "control-timeout"
        assert result["next"]["arguments"]["command"] == {
            "kind": "agent_command_status", "request": {"command_id": "original-input"}}
    assert len([1 for name, _ in sdk.calls if name == "instant_run"]) == 1


@pytest.mark.parametrize("transport", ["structured", "text"])
def test_error_preserves_original_payload_without_replay_or_journal_payload(tmp_path, transport):
    from types import SimpleNamespace
    from scripts.learning_benchmark_client import BenchmarkCallError
    payload = {"status": "recovery_preview_rejected",
               "error": {"code": "session_input_response_unproven",
                         "details": ["original-control"]}}
    calls = []

    async def call_tool(tool, arguments):
        calls.append((tool, arguments))
        if transport == "structured":
            return SimpleNamespace(structuredContent=payload, isError=True)
        return SimpleNamespace(structuredContent=None, isError=True,
                               content=[SimpleNamespace(type="text", text=json.dumps(payload))])

    opened = LearningBenchmarkClient(root=tmp_path, data_root=tmp_path / "data",
                                     evidence_dir=tmp_path / "evidence")
    opened._session = SimpleNamespace(call_tool=call_tool)
    with pytest.raises(BenchmarkCallError) as caught:
        asyncio.run(opened._invoke("instant_recovery_preview", {}))
    error = caught.value
    assert (error.tool, error.status, error.request_id) == (
        "instant_recovery_preview", "recovery_preview_rejected", None)
    assert str(error) == "instant_recovery_preview returned recovery_preview_rejected for request_id=None"
    assert error.response == {"status": "recovery_preview_rejected",
                              "error": {"code": "session_input_response_unproven",
                                        "details": ["original-control"]}}
    payload["error"]["details"].append("caller-mutated")
    assert error.response["error"]["details"] == ["original-control"]
    error.response["error"]["details"].append("diagnostic-mutated")
    assert payload["error"]["details"] == ["original-control", "caller-mutated"]
    assert calls == [("instant_recovery_preview", {})]
    journal = (tmp_path / "evidence" / "calls.jsonl").read_text(encoding="utf-8")
    assert "session_input_response_unproven" not in journal
    assert "original-control" not in journal


def test_call_error_optional_payload_preserves_legacy_constructor():
    from scripts.learning_benchmark_client import BenchmarkCallError
    legacy = BenchmarkCallError("instant_result", "failed", "original")
    assert legacy.response is None
    assert str(legacy) == "instant_result returned failed for request_id=original"
    payload = {"error": {"details": ["original"]}}
    error = BenchmarkCallError("instant_result", "failed", "original", response=payload)
    payload["error"]["details"].append("changed")
    assert error.response == {"error": {"details": ["original"]}}
