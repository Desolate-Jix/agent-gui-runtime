"""同一 Instant MCP 连接上的基准调用与原请求回读。"""
from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from copy import deepcopy
import json
import inspect
import math
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
_READ_ONLY_PLAN_ACTIONS = frozenset({"status", "cancel"})
_PLAN_TERMINAL = frozenset({"completed", "failed", "cancelled"})
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
                 decision_profile: Path | None = None,
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
        if decision_profile is not None and not Path(decision_profile).is_absolute():
            raise ValueError("benchmark_decision_profile_absolute_path_required")
        self.decision_profile = Path(decision_profile).resolve() if decision_profile is not None else None
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
        self._plan_bindings = {}
        self._plan_progress = {}
        self._plan_events = set()

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
            self.administrator, self.recognition_source, self.delegate_profile, self.api_profile,
            self.decision_profile)
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
        elif command["kind"] == "task_plan":
            request = command.get("request")
            action = request.get("action") if isinstance(request, dict) else None
            safe = isinstance(action, str) and action in _READ_ONLY_PLAN_ACTIONS
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

    def _plan_snapshot(self, value, *, run_id, start_request_id, previous):
        if (not isinstance(value, dict) or value.get("schema") != "task_plan_trial.v1"
                or value.get("source_kind") != "caller_plan"
                or any(not isinstance(value.get(key), str) or not value[key]
                       for key in ("run_id", "plan_id", "plan_sha256", "start_request_id"))
                or not isinstance(value.get("target_identity"), dict)
                or not isinstance(value.get("history"), list)):
            raise ValueError("benchmark_task_plan_contract_invalid")
        if (run_id is not None and value["run_id"] != run_id
                or start_request_id is not None and value["start_request_id"] != start_request_id):
            raise ValueError("benchmark_task_plan_identity_mismatch")
        binding = {key: deepcopy(value.get(key)) for key in (
            "run_id", "plan_id", "plan_sha256", "start_request_id", "target_identity", "owner_id", "session_directory")}
        known = self._plan_bindings.get(value["run_id"])
        if known is not None and known != binding:
            raise ValueError("benchmark_task_plan_binding_mismatch")
        history = value["history"]
        if any(not isinstance(row, dict) or not isinstance(row.get("execution_request_id"), str)
               or not row["execution_request_id"] or row.get("verdict") not in {"success", "failure", "cancelled"}
               for row in history):
            raise ValueError("benchmark_task_plan_history_invalid")
        previous = previous or self._plan_progress.get(value["run_id"])
        if previous is not None:
            if history[:len(previous["history"])] != previous["history"]:
                raise ValueError("benchmark_task_plan_stale_history")
            if (len(history) == len(previous["history"]) and previous.get("active_command_id")
                    and value.get("active_command_id") and previous["active_command_id"] != value["active_command_id"]):
                raise ValueError("benchmark_task_plan_original_ticket_changed")
        status, runner = value.get("status"), value.get("runner_state")
        if (status not in {"ready", "pending", "paused_uncertain", "cancel_requested", *_PLAN_TERMINAL}
                or runner not in {"ready", "dispatching", "waiting", "cancel_requested", *_PLAN_TERMINAL}):
            raise ValueError("benchmark_task_plan_state_invalid")
        wait = value.get("wait")
        reviewed_wait = False
        if (previous is not None and isinstance(wait, dict) and runner == "waiting"
                and status in {"ready", "completed", "failed"} and value.get("pending") is None
                and value.get("wait_reason") == "verification_required" and history):
            prior_wait = previous.get("wait") or {}
            settled = history[-1]
            same_wait = all(wait.get(key) == prior_wait.get(key) and wait.get(key) is not None
                for key in ("wait_id", "run_id", "step_id", "command_id", "reason"))
            history_added = len(history) == len(previous["history"]) + 1
            history_retained = previous.get("reviewed_wait") is True and history == previous["history"]
            reviewed_wait = (same_wait and (history_added or history_retained)
                and settled.get("step_id") == wait["step_id"]
                and settled.get("execution_request_id") == wait["command_id"]
                and settled.get("judged_by") == "agent" and settled.get("original_input_status") == "completed"
                and isinstance(settled.get("verification_request_id"), str) and bool(settled["verification_request_id"]))
        if runner == "waiting" and (not isinstance(value.get("wait_reason"), str) or not value["wait_reason"]):
            raise ValueError("benchmark_task_plan_wait_missing")
        if wait is not None:
            if (not isinstance(wait, dict) or not isinstance(wait.get("wait_id"), str) or not wait["wait_id"]
                    or wait.get("run_id") != value["run_id"] or wait.get("reason") != value.get("wait_reason")
                    or wait.get("command_id") != value.get("active_command_id")
                    or not reviewed_wait and wait.get("step_id") != value.get("current_step_id")):
                raise ValueError("benchmark_task_plan_wait_binding_mismatch")
        if value.get("wait_reason") in {"grounding_required", "verification_required", "execution_pending"}:
            pending = value.get("pending")
            if (wait is None or not isinstance(value.get("active_command_id"), str)
                    or not reviewed_wait and (not isinstance(pending, dict)
                        or pending.get("execution_request_id") != value.get("active_command_id")
                        or pending.get("step_id") != value.get("current_step_id"))):
                raise ValueError("benchmark_task_plan_ticket_binding_mismatch")
        if value.get("wait_reason") == "grounding_required":
            grounding = wait.get("pending_grounding")
            capture = grounding.get("capture") if isinstance(grounding, dict) else None
            if (not isinstance(grounding, dict) or not isinstance(grounding.get("request_id"), str)
                    or not grounding["request_id"] or not isinstance(capture, dict)
                    or any(not isinstance(capture.get(key), str) or not capture[key]
                           for key in ("capture_id", "image_path", "sha256"))):
                raise ValueError("benchmark_task_plan_grounding_evidence_invalid")
        if status in _PLAN_TERMINAL or runner in _PLAN_TERMINAL:
            if not reviewed_wait and (status != runner or wait is not None or value.get("pending") is not None
                    or value.get("active_command_id") is not None):
                raise ValueError("benchmark_task_plan_terminal_invalid")
            if status == "completed":
                metrics = value.get("metrics") or {}
                count = metrics.get("planned_steps")
                if (value.get("current_step_id") is not None or type(count) is not int or not 1 <= count <= 8
                        or len(history) != count or metrics.get("successful_steps") != count
                        or any(row["verdict"] != "success" for row in history)):
                    raise ValueError("benchmark_task_plan_completion_unproven")
        self._plan_bindings[value["run_id"]] = binding
        self._plan_progress[value["run_id"]] = {**binding, **self._compact_plan(value),
            "history": deepcopy(history), "wait": deepcopy(value.get("wait")), "reviewed_wait": reviewed_wait}
        return deepcopy(value)

    @staticmethod
    def _compact_plan(snapshot):
        value = {key: deepcopy(snapshot[key]) for key in (
            "schema", "source_kind", "run_id", "plan_id", "plan_sha256", "start_request_id", "status",
            "runner_state", "mode", "current_step_id", "active_command_id", "wait_reason", "metrics")
            if key in snapshot}
        wait = snapshot.get("wait")
        if wait is not None:
            value["wait"] = {key: deepcopy(wait[key]) for key in (
                "wait_id", "reason", "run_id", "step_id", "command_id", "error") if key in wait}
        value["history"] = [{key: deepcopy(row[key]) for key in (
            "step_id", "execution_request_id", "verdict", "judged_by", "reason", "action_executed",
            "original_input_status", "verification_request_id", "verification_result_sha256", "evidence_refs")
            if key in row} for row in snapshot["history"]]
        return value

    @staticmethod
    def _receipt_reference(request_id):
        return {"tool": "instant_result", "arguments": {"request_id": request_id,
            "detail": "full", "images": "none"}}

    def _plan_result(self, receipt, *, original_request_id, status_request_id, snapshot, client_state, known_run_id=None):
        value = {key: deepcopy(receipt[key]) for key in (
            "request_id", "status", "error", "error_type", "operation_success_scope", "command_wall_ms",
            "started_at", "finished_at", "wait_expired", "command_cancelled", "partial_execution",
            "accepted", "action_executed", "status_source", "snapshot_unavailable", "host_status", "next") if key in receipt}
        value.update(original_request_id=original_request_id, current_status_request_id=status_request_id,
                     client_state=client_state, automatic_retry_allowed=False, no_replay=True,
                     original_receipt=self._receipt_reference(original_request_id),
                     current_receipt=self._receipt_reference(receipt["request_id"]))
        if snapshot is not None:
            value["result"] = self._compact_plan(snapshot)
            value.update({key: deepcopy(snapshot.get(key)) for key in (
                "run_id", "plan_id", "start_request_id", "active_command_id", "wait_reason")})
            value["wait_id"] = (snapshot.get("wait") or {}).get("wait_id")
            value["start_receipt"] = self._receipt_reference(snapshot["start_request_id"])
            executions = list(dict.fromkeys([row["execution_request_id"] for row in snapshot["history"]]
                + ([snapshot["active_command_id"]] if snapshot.get("active_command_id") else [])))
            value["execution_receipts"] = [self._receipt_reference(item) for item in executions]
            value["images"] = [{"tool": "instant_image", "arguments": {"request_id": item, "view": "after"}}
                               for item in executions]
        else:
            value["execution_receipts"], value["images"] = [], []
            if known_run_id is not None:
                value.update(run_id=known_run_id, run_binding_verified=False)
        if client_state in {"pending", "result_unknown", "control_failed"}:
            value.setdefault("command_cancelled", False)
            if client_state == "control_failed" and isinstance(receipt.get("next"), dict):
                value["next"] = deepcopy(receipt["next"])
            elif receipt.get("status") in {"pending", "not_found", "result_unknown"} or snapshot is None:
                value["next"] = self._receipt_reference(receipt["request_id"])
            else:
                value["next"] = {"tool": "instant_run", "arguments": {
                    "request_id": "plan-status-" + uuid4().hex, "command": {"kind": "task_plan",
                        "request": {"action": "status", "run_id": snapshot["run_id"]}},
                        "detail": "full", "images": "none", "wait_ms": 25000}}
        if receipt.get("status_source") == "instant_status":
            value["current_status"] = {"tool": "instant_status", "arguments": {},
                "field": "task_plan_run", "run_id": value.get("run_id")}
            if client_state != "terminal":
                value["next"] = {"tool": "instant_status", "arguments": {}}
        return value

    async def _plan_event(self, result, snapshot, callback):
        if callback is None:
            return
        wait = (snapshot or {}).get("wait") or {}
        grounding = wait.get("pending_grounding") or {}
        key = (result.get("run_id") or result["original_request_id"], wait.get("wait_id"),
               result["client_state"], grounding.get("request_id"),
               None if wait.get("wait_id") else result["request_id"])
        if key in self._plan_events:
            return
        self._plan_events.add(key)
        event = {"schema": "task_plan_client_event.v1", **deepcopy(result)}
        event["command_id"] = result.get("active_command_id")
        event["timing"] = {key: result[key] for key in ("command_wall_ms", "started_at", "finished_at") if key in result}
        if grounding:
            event["grounding"] = {key: deepcopy(grounding[key]) for key in (
                "contract_version", "request_id", "phase", "goal", "capture", "configuration", "expires_at",
                "requires_live_revalidation", "next_action") if key in grounding}
            event["grounding_status"] = {"kind": "grounding_status", "request": {"request_id": grounding["request_id"]}}
        returned = callback(event)
        if inspect.isawaitable(returned):
            await returned

    async def run_plan(self, request_id: str, command: dict, *, event_callback=None, total_timeout: float = 120):
        """提交一次短计划；只回读原请求，正常推进不交接主 Agent。"""
        if (type(total_timeout) not in (int, float) or not math.isfinite(total_timeout) or total_timeout < 0
                or event_callback is not None and not callable(event_callback)):
            raise ValueError("benchmark_task_plan_options_invalid")
        request = command.get("request") if isinstance(command, dict) else None
        if (not isinstance(command, dict) or command.get("kind") != "task_plan" or not isinstance(request, dict)
                or request.get("action") not in {"start", "status", "continue", "cancel", "review"}):
            raise ValueError("benchmark_task_plan_command_invalid")
        self._check_command("instant_run", {"request_id": request_id, "command": command})
        run_id = request.get("run_id")
        if request["action"] != "start" and (not isinstance(run_id, str) or not run_id):
            raise ValueError("benchmark_task_plan_run_id_required")
        deadline = monotonic() + total_timeout
        current_id = request_id
        status_id = request_id if request["action"] != "start" else None
        snapshot, signature = deepcopy(self._plan_progress.get(run_id)), None
        tool = "instant_run"
        args = {"request_id": request_id, "command": deepcopy(command), "detail": "full", "images": "none",
                "wait_ms": min(int(total_timeout * 1000), 25000)}
        while True:
            try:
                # 本地等待结束只中断调用方等待；不发送任何取消或替换动作。
                value = await asyncio.wait_for(self.call(tool, args), timeout=max(.001, deadline - monotonic()))
            except BenchmarkCallError as error:
                value = error.response
                if not isinstance(value, dict) or value.get("request_id") != current_id:
                    raise ValueError("benchmark_task_plan_receipt_identity_mismatch") from error
                result = self._plan_result(value, original_request_id=request_id, status_request_id=status_id,
                    snapshot=snapshot, client_state="control_failed", known_run_id=run_id)
                await self._plan_event(result, snapshot, event_callback)
                return result
            except TimeoutError:
                value = {"request_id": current_id, "status": "result_unknown", "wait_expired": True,
                         "command_cancelled": False}
                if tool == "instant_status":
                    value["status_source"] = "instant_status"
                result = self._plan_result(value, original_request_id=request_id, status_request_id=status_id,
                                           snapshot=snapshot, client_state="pending", known_run_id=run_id)
                await self._plan_event(result, snapshot, event_callback)
                return result
            if tool == "instant_status":
                if not isinstance(value, dict):
                    raise ValueError("benchmark_task_plan_status_projection_invalid")
                projected = value.get("task_plan_run")
                if projected is not None:
                    snapshot = self._plan_snapshot(projected, run_id=run_id,
                        start_request_id=request_id if request["action"] == "start" else None, previous=snapshot)
                host = {key: deepcopy(value[key]) for key in (
                    "phase", "host_alive", "task_plan_runtime_error") if key in value}
                if value.get("host_alive") is not True:
                    value = {"request_id": current_id, "status": "result_unknown", "host_status": host}
                elif value.get("task_plan_runtime_error"):
                    value = {"request_id": current_id, "status": "failed", "host_status": host,
                        "error": deepcopy(value["task_plan_runtime_error"])}
                elif projected is None:
                    value = {"request_id": current_id, "status": "pending", "snapshot_unavailable": True}
                else:
                    value = {"request_id": current_id, "status": "returned", "result": projected}
                value["status_source"] = "instant_status"
            if not isinstance(value, dict) or value.get("request_id") != current_id:
                raise ValueError("benchmark_task_plan_receipt_identity_mismatch")
            if value.get("status") in {"result_unknown", "not_found"}:
                state = "result_unknown"
            elif value.get("status") == "pending":
                if monotonic() < deadline:
                    await asyncio.sleep(min(self.poll_interval, deadline - monotonic()))
                    if monotonic() < deadline:
                        tool, args = (("instant_status", {}) if value.get("status_source") == "instant_status" else
                            ("instant_result", {"request_id": current_id, "detail": "full", "images": "none"}))
                        continue
                state = "pending"
            elif value.get("status") == "returned":
                snapshot = self._plan_snapshot(value.get("result"), run_id=run_id,
                    start_request_id=request_id if request["action"] == "start" else None, previous=snapshot)
                run_id = snapshot["run_id"]
                runner, reason = snapshot["runner_state"], snapshot.get("wait_reason")
                if runner in _PLAN_TERMINAL:
                    state = "terminal"
                elif self._plan_progress[run_id].get("reviewed_wait"):
                    if request["action"] == "review":
                        settled = snapshot["history"][-1]
                        if (any(settled.get(key) != request.get(key) for key in (
                                "execution_request_id", "step_id", "verdict", "reason"))
                                or settled.get("verification_request_id") != request_id):
                            raise ValueError("benchmark_task_plan_review_receipt_mismatch")
                    state = "continue_required"
                elif reason and reason != "execution_pending" and snapshot["status"] != "cancel_requested" and runner != "cancel_requested":
                    state = reason
                elif monotonic() >= deadline:
                    state = "pending"
                else:
                    current_signature = (snapshot["status"], runner, snapshot.get("current_step_id"),
                        snapshot.get("active_command_id"), (snapshot.get("wait") or {}).get("wait_id"),
                        len(snapshot["history"]))
                    if current_signature == signature:
                        await asyncio.sleep(min(self.poll_interval, deadline - monotonic()))
                        if monotonic() >= deadline:
                            result = self._plan_result(value, original_request_id=request_id, status_request_id=status_id,
                                                       snapshot=snapshot, client_state="pending", known_run_id=run_id)
                            await self._plan_event(result, snapshot, event_callback)
                            return result
                    signature = current_signature
                    # 宿主投影不进输入队列，原步骤尚在执行也能安全观察计划推进。
                    tool, args = "instant_status", {}
                    continue
            elif value.get("status") in {"failed", "validation_rejected", "state_rejected"}:
                state = "runtime_error" if value.get("host_status", {}).get("task_plan_runtime_error") else "control_failed"
            else:
                raise ValueError("benchmark_task_plan_receipt_invalid")
            result = self._plan_result(value, original_request_id=request_id, status_request_id=status_id,
                                       snapshot=snapshot, client_state=state, known_run_id=run_id)
            if state not in {"terminal", "continue_required"}:
                await self._plan_event(result, snapshot, event_callback)
            return result

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
