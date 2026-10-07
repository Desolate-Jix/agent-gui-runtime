"""同一 Instant MCP 连接上的基准调用与原请求回读。"""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from time import monotonic, monotonic_ns
from uuid import uuid4

from scripts.smoke_instant_mcp import server_arguments


_READ_ONLY_KINDS = frozenset({
    "discover", "capture", "read_text", "grounding_status", "agent_command_status",
    "learning_start", "learning_status", "learning_stop", "learning_recover",
    "learning_event", "learning_review", "learning_projection", "learning_import",
    "learning_library", "learning_memory", "learning_save_interface", "learning_commit",
    "learning_project", "learning_reuse", "learning_adopt_source", "learning_template",
    "learning_feedback",
})
_READ_ONLY_WORKFLOW_ACTIONS = frozenset({
    "compile", "read", "save", "start", "prepare", "review", "verify", "status", "cancel",
    "synthesis_prepare", "synthesis_status", "synthesis_complete", "synthesis_resume",
})
_TOOLS = frozenset({"instant_status", "instant_submit", "instant_result", "instant_run", "instant_image"})


class BenchmarkCallError(RuntimeError):
    def __init__(self, tool: str, status: str, request_id: str | None, *, response: dict | None = None):
        self.tool, self.status, self.request_id = tool, status, request_id
        self.response = deepcopy(response)
        super().__init__(f"{tool} returned {status} for request_id={request_id}")


class LearningBenchmarkClient:
    def __init__(self, *, root: Path, data_root: Path, evidence_dir: Path,
                 recognition_source: str = "local", model_directory: Path | None = None,
                 delegate_profile: str | None = None, api_profile: Path | None = None,
                 administrator: bool = False, allow_actions: bool = False,
                 ready_timeout: float = 90, cleanup_timeout: float = 60,
                 poll_interval: float = .1, transport_factory=None, client_factory=None,
                 params_factory=None):
        if type(allow_actions) is not bool or type(administrator) is not bool:
            raise ValueError("benchmark_client_options_invalid")
        for name, value in (("ready_timeout", ready_timeout), ("cleanup_timeout", cleanup_timeout),
                            ("poll_interval", poll_interval)):
            if type(value) not in (int, float) or value <= 0:
                raise ValueError(name + "_invalid")
        self.root = Path(root).resolve()
        self.data_root = Path(data_root).resolve()
        self.evidence_dir = Path(evidence_dir).resolve()
        self.recognition_source = recognition_source
        self.model_directory = Path(model_directory).resolve() if model_directory is not None else None
        self.delegate_profile = delegate_profile
        self.api_profile = Path(api_profile).resolve() if api_profile is not None else None
        self.administrator = administrator
        self.allow_actions = allow_actions
        self.ready_timeout = ready_timeout
        self.cleanup_timeout = cleanup_timeout
        self.poll_interval = poll_interval
        self._transport_factory = transport_factory
        self._client_factory = client_factory
        self._params_factory = params_factory
        self._stack = None
        self._session = None
        self._status = None
        self._start_attempted = False
        self.cleanup_error = None

    @property
    def status(self):
        return deepcopy(self._status)

    @property
    def session_directory(self):
        return self._status.get("session_directory") if self._status else None

    def _journal(self, tool, request_id, status, elapsed_ms):
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        row = {"tool": tool, "request_id": request_id, "status": status, "elapsed_ms": round(elapsed_ms, 3)}
        with (self.evidence_dir / "calls.jsonl").open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

    async def _invoke(self, tool, args):
        if self._session is None:
            raise ValueError("benchmark_client_not_connected")
        request_id = args.get("request_id") if isinstance(args, dict) else None
        started = monotonic_ns()
        try:
            response = await self._session.call_tool(tool, args)
            value = getattr(response, "structuredContent", None)
            if not isinstance(value, dict):
                blocks = [block.text for block in response.content if block.type == "text"]
                if not blocks:
                    raise ValueError("benchmark_client_response_missing")
                value = json.loads(blocks[0])
            status = str(value.get("status") or value.get("phase") or "returned")
            self._journal(tool, request_id, status, (monotonic_ns() - started) / 1_000_000)
            if getattr(response, "is_error", False) or getattr(response, "isError", False):
                raise BenchmarkCallError(tool, status, request_id, response=value)
            return value
        except BenchmarkCallError:
            raise
        except Exception:
            self._journal(tool, request_id, "transport_error", (monotonic_ns() - started) / 1_000_000)
            raise

    async def __aenter__(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        transport = self._transport_factory or stdio_client
        client = self._client_factory or ClientSession
        params = self._params_factory or (lambda **kwargs: StdioServerParameters(**kwargs))
        arguments = server_arguments(self.root, self.model_directory, self.data_root,
            self.administrator, self.recognition_source, self.delegate_profile, self.api_profile)
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
        env.pop("PYTHONPATH", None)
        self._stack = AsyncExitStack()
        try:
            streams = await self._stack.enter_async_context(transport(params(
                command=sys.executable, args=arguments, env=env, cwd=str(self.root))))
            self._session = await self._stack.enter_async_context(client(*streams))
            await self._session.initialize()
            self._start_attempted = True
            await self._invoke("instant_start", {"new_session": True})
            deadline = monotonic() + self.ready_timeout
            while True:
                self._status = await self._invoke("instant_status", {})
                if self._status.get("phase") == "ready":
                    return self
                if self._status.get("host_alive") is False or monotonic() >= deadline:
                    raise TimeoutError("benchmark_host_not_ready")
                await asyncio.sleep(self.poll_interval)
        except BaseException:
            if self._start_attempted and self._session is not None:
                try:
                    await self._stop_and_wait()
                except BaseException as error:
                    self.cleanup_error = error
            await self._stack.aclose()
            self._session = None
            raise

    async def _stop_and_wait(self):
        await self._invoke("instant_stop", {})
        deadline = monotonic() + self.cleanup_timeout
        while True:
            self._status = await self._invoke("instant_status", {})
            if self._status.get("cleanup_verified") is True:
                return
            if monotonic() >= deadline:
                raise TimeoutError("benchmark_cleanup_not_verified")
            await asyncio.sleep(self.poll_interval)

    async def __aexit__(self, exc_type, exc, tb):
        cleanup_error = None
        try:
            if self._session is not None and self._start_attempted:
                await self._stop_and_wait()
        except BaseException as error:
            cleanup_error = error
            self.cleanup_error = error
        finally:
            if self._stack is not None:
                await self._stack.aclose()
            self._session = None
            self._stack = None
        if cleanup_error is not None and exc_type is None:
            raise cleanup_error
        return False

    def _check_command(self, tool, args):
        if not isinstance(args, dict) or not isinstance(args.get("request_id"), str) or not args["request_id"]:
            raise ValueError("benchmark_request_id_required")
        command = args.get("command")
        if not isinstance(command, dict) or not isinstance(command.get("kind"), str):
            raise ValueError("benchmark_command_invalid")
        safe = command["kind"] in _READ_ONLY_KINDS
        if command["kind"] == "learning_workflow":
            request = command.get("request")
            action = request.get("action") if isinstance(request, dict) else None
            safe = isinstance(action, str) and action in _READ_ONLY_WORKFLOW_ACTIONS
        if not self.allow_actions and not safe:
            self._journal(tool, args["request_id"], "client_read_only_rejected", 0)
            raise ValueError("benchmark_client_read_only")

    async def call(self, name: str, args: dict | None = None):
        if name not in _TOOLS:
            raise ValueError("benchmark_tool_invalid")
        arguments = args or {}
        if name in {"instant_run", "instant_submit"}:
            self._check_command(name, arguments)
        value = await self._invoke(name, arguments)
        if name == "instant_status":
            self._status = deepcopy(value)
        return value

    async def run(self, request_id: str, command: dict, *, total_timeout: float = 120):
        if type(total_timeout) not in (int, float) or total_timeout < 0:
            raise ValueError("benchmark_total_timeout_invalid")
        deadline = monotonic() + total_timeout
        original_request_id = request_id
        # 控制回执属于外层请求，worker 身份只能来自明确的原输入引用。
        controls_worker = command.get("kind") in {"agent_command_status", "agent_command_continue"}
        expected_command_id = ((command.get("request") or {}).get("command_id")
                               if controls_worker else original_request_id)
        if not isinstance(expected_command_id, str) or not expected_command_id:
            raise ValueError("benchmark_agent_command_identity_missing")
        status_request_id = original_request_id if controls_worker else None
        command_id = expected_command_id if controls_worker else None
        value = await self.call("instant_run", {"request_id": request_id, "command": command,
                                                "wait_ms": min(int(total_timeout * 1000), 25000),
                                                "detail": "full", "images": "none"})
        while True:
            expected_id = status_request_id or original_request_id
            if value.get("request_id") != expected_id:
                raise ValueError("benchmark_receipt_request_id_mismatch")
            result = value.get("result") if isinstance(value, dict) else None
            if isinstance(result, dict) and result.get("contract_version") == "agent_command.v1":
                if result.get("command_id") != expected_command_id:
                    raise ValueError("benchmark_agent_command_identity_mismatch")
                command_id = expected_command_id
                state = result.get("status")
                if state in {"completed", "failed", "cancelled"}:
                    return self._result(value, original_request_id, status_request_id, command_id, "terminal")
                if state == "awaiting_grounding":
                    return self._result(value, original_request_id, status_request_id, command_id, "awaiting_grounding")
                if state != "running":
                    raise ValueError("benchmark_agent_command_state_invalid")
                if monotonic() >= deadline:
                    return self._result(value, original_request_id, status_request_id, command_id, "pending")
                await asyncio.sleep(min(self.poll_interval, max(0, deadline - monotonic())))
                if monotonic() >= deadline:
                    return self._result(value, original_request_id, status_request_id, command_id, "pending")
                status_request_id = "agent-status-" + uuid4().hex
                value = await self.call("instant_run", {"request_id": status_request_id,
                    "command": {"kind": "agent_command_status", "request": {"command_id": command_id}},
                    "wait_ms": min(int(max(0, deadline - monotonic()) * 1000), 25000),
                    "detail": "full", "images": "none"})
                continue
            if value.get("status") == "pending":
                if monotonic() >= deadline:
                    return self._result(value, original_request_id, status_request_id, command_id, "pending")
                await asyncio.sleep(min(self.poll_interval, max(0, deadline - monotonic())))
                if monotonic() >= deadline:
                    return self._result(value, original_request_id, status_request_id, command_id, "pending")
                # 尚未形成回执的查询只回读它自己的 ID；执行命令不会重交。
                current_id = status_request_id or original_request_id
                value = await self.call("instant_result", {"request_id": current_id,
                                                           "detail": "full", "images": "none"})
                continue
            if status_request_id is not None:
                raise ValueError("benchmark_agent_status_contract_invalid")
            return self._result(value, original_request_id, status_request_id, command_id, "terminal")

    @staticmethod
    def _result(receipt, original_request_id, status_request_id, command_id, client_state):
        value = deepcopy(receipt)
        value.update(original_request_id=original_request_id,
                     current_status_request_id=status_request_id,
                     client_state=client_state, automatic_retry_allowed=False)
        if command_id is not None:
            value["command_id"] = command_id
        if client_state == "pending":
            current_id = status_request_id or original_request_id
            if value.get("status") == "pending":
                value["next"] = {"tool": "instant_result", "arguments": {"request_id": current_id,
                    "detail": "full", "images": "none"}}
            elif command_id is not None:
                value["next"] = {"tool": "instant_run", "arguments": {
                    "request_id": "agent-status-" + uuid4().hex,
                    "command": {"kind": "agent_command_status", "request": {"command_id": command_id}},
                    "detail": "full", "images": "none"}}
            value["no_replay"] = True
        return value


__all__ = ["BenchmarkCallError", "LearningBenchmarkClient"]
