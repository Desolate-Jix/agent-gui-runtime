"""即时模式的本地 STDIO 适配；动作仍交给原串行会话执行。"""

import base64
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from threading import RLock
import time
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

INSTANT_VERSION = "0.1.0-test.8"


def _run_wait_budget(kind, requested):
    # 只延长回执等待，不延长动作等待、不持锁，也不重发输入。
    if requested is None:
        return 45000 if kind == "form_fill" else 25000
    if type(requested) is not int or not 0 <= requested <= 120000:
        raise ValueError("wait_ms must be an integer from 0 to 120000, or null for command defaults")
    return requested


class InstantAdmissionError(ValueError):
    """仅用于尚未写入命令队列的可预期状态拒绝。"""

    def __init__(self, code, message, next_tool, next_arguments=None):
        super().__init__(message)
        self.code = code
        self.next = {"tool": next_tool, "arguments": next_arguments or {}}


class InstantImageError(ValueError):
    """只读证据错误，不判断原动作是否执行，也不触发重放。"""

    def __init__(self, code, message, next_step):
        super().__init__(message)
        self.code = code
        self.next = next_step


class InstantStartError(ValueError):
    """仅表示创建宿主之前的配置或状态拒绝，不判断既有会话的执行结果。"""

    def __init__(self, code, message, next_step):
        super().__init__(message)
        self.code = code
        self.next = next_step


def _validate_request_id(request_id):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", request_id):
        raise ValueError("request_id must be 1-80 lowercase ASCII letters/digits/dashes/underscores")


class InstantCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["discover", "launch", "select", "maximize", "capture", "read_text", "prepare_models", "release_models", "step", "input_sequence", "form_fill", "close_launched_window", "desktop_capture", "desktop_click", "grounding_prepare", "grounding_resolve", "grounding_status", "grounding_cancel", "grounding_execute", "agent_command_status", "agent_command_continue", "agent_command_cancel"]
    app_id: str | None = None
    name: str | None = None
    path: str | None = None
    prefer_existing: bool | None = None
    url: str | None = None
    handle: int | None = Field(default=None, gt=0)
    process_id: int | None = Field(default=None, gt=0)
    operation: Literal["execute_recognition_plan", "type_text", "scroll", "press_key"] | None = None
    request: dict | None = None
    observation_wait_ms: int | None = Field(default=None, ge=0, le=2000)
    observation_condition: dict | None = None
    max_chars: int | None = Field(default=None, ge=1, le=20000)
    vision_capabilities: dict | None = None

    def command(self):
        from app.vision.grounding_commands import GROUNDING_COMMANDS, validate_grounding_command
        from app.vision.agent_command_contract import AGENT_COMMANDS
        value = self.model_dump(exclude_none=True)
        fields = {
            "launch": (set(), {"app_id", "name", "path", "url", "prefer_existing"}),
            "select": ({"handle", "process_id"}, {"handle", "process_id"}),
            "close_launched_window": ({"handle", "process_id"}, {"handle", "process_id"}),
            "step": ({"operation", "request"}, {"operation", "request", "observation_wait_ms", "observation_condition", "vision_capabilities"}),
            "input_sequence": ({"request"}, {"request", "observation_wait_ms", "observation_condition", "vision_capabilities"}),
            "form_fill": ({"request"}, {"request", "vision_capabilities"}),
            "read_text": (set(), {"max_chars"}),
            "desktop_click": ({"request"}, {"request", "observation_wait_ms", "observation_condition", "vision_capabilities"}),
        }
        required, allowed = (({"request"}, {"request"}) if self.kind in GROUNDING_COMMANDS or self.kind in AGENT_COMMANDS
                             else fields.get(self.kind, (set(), set())))
        present = set(value) - {"kind"}
        if not required <= present or present - allowed:
            raise ValueError("command fields do not match kind")
        if self.kind in GROUNDING_COMMANDS:
            validate_grounding_command(self.kind, self.request)
        if self.kind in AGENT_COMMANDS:
            AGENT_COMMANDS[self.kind].model_validate(self.request)
        if self.vision_capabilities is not None:
            from app.vision.recognition_source import ClientVisionCapabilities
            ClientVisionCapabilities.model_validate(self.vision_capabilities)
        if self.kind == "launch":
            selectors = [value[key] for key in ("app_id", "name", "path") if key in value]
            if len(selectors) != 1 or not selectors[0].strip():
                raise ValueError("launch requires exactly one non-empty app_id, name or path")
        if self.kind in {"step", "desktop_click"}:
            from app.desktop_review.local_action_contract import _validated_request
            # 只验证，运行时再次验证；不在桥接层重写执行请求。
            _validated_request("execute_recognition_plan" if self.kind == "desktop_click" else self.operation, self.request)
        elif self.kind == "input_sequence":
            from app.desktop_review.input_sequence import InputSequenceRequest
            InputSequenceRequest.model_validate(self.request)
        elif self.kind == "form_fill":
            from app.desktop_review.form_fill import FormFillRequest
            FormFillRequest.model_validate(self.request)
        if self.observation_condition is not None:
            from app.core.observation_policy import resolve_render_grace_ms, local_action_observation_kind
            from app.desktop_review.conditional_observation import validate_condition
            if self.kind == "input_sequence" and not self.request.get("submit_search"):
                raise ValueError("input_sequence condition requires submit_search")
            action = ("press_enter" if self.kind == "input_sequence" else
                      local_action_observation_kind("execute_recognition_plan" if self.kind == "desktop_click" else self.operation, self.request))
            validate_condition(self.observation_condition, resolve_render_grace_ms(action, self.observation_wait_ms))
        return value


def read_json(path):
    from app.core.json_snapshot import read_json_snapshot
    return read_json_snapshot(path)


def write_json(path, value):
    from app.core.json_snapshot import write_json_snapshot
    write_json_snapshot(path, value)


class InstantSession:
    def __init__(self, root, data_root, model_directory=None, *, allow_local_input=False,
                 recognition_source="local", delegate_profile=None):
        self.root = Path(root).resolve()
        self.data_root = Path(data_root).resolve()
        self.model_directory = Path(model_directory).resolve() if model_directory is not None else None
        self.recognition_source = recognition_source
        self.delegate_profile = delegate_profile
        self.allow_local_input = allow_local_input
        self.guard = RLock()
        self.process = None
        self.session = None
        self.lock_file = None
        self.log_file = None
        self.host_identity = None

    def _lock(self):
        if self.lock_file is not None:
            return
        import msvcrt
        self.data_root.mkdir(parents=True, exist_ok=True)
        stream = (self.data_root / "owner.lock").open("a+b")
        try:
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            stream.close()
            raise ValueError("another MCP owns this data directory; use that connection") from None
        self.lock_file = stream

    def start(self, new_session=False):
        with self.guard:
            if not self.allow_local_input:
                raise InstantStartError("local_input_not_enabled",
                    "Local operator must explicitly launch with --allow-local-input; tools cannot change this",
                    "Ask the operator to check the MCP launch configuration; do not change input authorization automatically.")
            if self.recognition_source == "external_api":
                raise InstantStartError("external_api_not_implemented",
                    "external_api recognition source is not implemented",
                    "Choose local, agent_current or agent_delegate; external_api cannot be started yet.")
            from app.vision.recognition_source import RecognitionSourceConfig
            from pydantic import ValidationError
            try:
                config = RecognitionSourceConfig.model_validate({"source": self.recognition_source,
                    "delegate_profile": self.delegate_profile})
            except ValidationError:
                raise InstantStartError("invalid_recognition_configuration",
                    "invalid recognition source or delegate profile",
                    "Check --recognition-source and use --delegate-profile only with agent_delegate.") from None
            if config.source == "local" and (self.model_directory is None or not self.model_directory.is_dir()):
                raise InstantStartError("model_directory_unavailable", "configured model directory does not exist",
                    "Check --model-directory is an existing directory; use forward slashes or escaped backslashes in configuration, then reconnect.")
            self._lock()
            pointer = self.data_root / "latest-session.json"
            saved = read_json(pointer) if pointer.is_file() else {}
            if self.session is None and pointer.is_file():
                previous = (self.data_root / saved["name"]).resolve()
                if previous.parent != self.data_root or not re.fullmatch(r"session-[0-9a-f]{32}", previous.name):
                    raise ValueError("invalid persisted session pointer")
                self.session = previous
                self.host_identity = saved.get("host_identity")
            if self.session is not None:
                status = self.status()
                if (saved.get("recognition_source", "local") != config.source
                        or saved.get("delegate_profile") != config.delegate_profile):
                    if not new_session or not status["cleanup_verified"] or status["pending_ids"]:
                        raise InstantStartError("recognition_source_mismatch",
                            "existing session uses a different recognition source",
                            "Verify previous cleanup and receipts, then start a new session with the chosen source.")
                if not new_session:
                    return status
                if not status["cleanup_verified"] or status["pending_ids"]:
                    raise InstantStartError("previous_session_not_resolved",
                        "previous session needs verified cleanup and resolved receipts before a new session",
                        "Inspect instant_status and use instant_result for pending IDs; verify cleanup and resolve receipts before requesting a new session. Do not delete session records or replay commands.")
                if self.log_file:
                    self.log_file.close()
                self.session = None
                self.process = None
                self.host_identity = None
            # 新桥接进程不能覆盖仍在清理的旧宿主，也不续跑旧命令。
            import psutil
            for path in self.data_root.glob("session-*/report.json"):
                old = read_json(path)
                if not old.get("finished_at") and psutil.pid_exists(old.get("runner_pid", -1)):
                    raise ValueError("previous host still active or cleaning up; inspect its report before restarting")
            self.session = self.data_root / ("session-" + uuid4().hex)
            self.log_file = (self.data_root / (self.session.name + ".log")).open("ab")
            env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1")
            env.pop("PYTHONPATH", None)
            command = [sys.executable, str(self.root / "scripts/run_local_step_session.py"),
                "--output", str(self.session), "--recognition-source", config.source,
                "--local-no-learning", "--parent-pid", str(os.getpid())]
            if config.source == "local":
                command.extend(["--model-directory", str(self.model_directory)])
            if config.delegate_profile:
                command.extend(["--delegate-profile", config.delegate_profile])
            self.process = subprocess.Popen(command, cwd=self.root,
                stdin=subprocess.DEVNULL, stdout=self.log_file, stderr=self.log_file,
                env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.host_identity = {"pid": self.process.pid, "created": psutil.Process(self.process.pid).create_time()}
            write_json(pointer, {"name": self.session.name, "host_identity": self.host_identity,
                "recognition_source": config.source, "delegate_profile": config.delegate_profile})
            return self.status()

    def _host_alive(self):
        if self.process is not None:
            return self.process.poll() is None
        if self.host_identity:
            import psutil
            try:
                return psutil.Process(self.host_identity["pid"]).create_time() == self.host_identity["created"]
            except psutil.NoSuchProcess:
                return False
        return False

    def status(self):
        with self.guard:
            report = {}
            if self.session and (self.session / "report.json").is_file():
                report = read_json(self.session / "report.json")
            alive = self._host_alive()
            phase = report.get("phase", "starting" if alive else "not_started")
            if self.session is not None and not alive and not report.get("finished_at"):
                phase = "host_exited_without_cleanup_proof"
            pending = []
            if self.session:
                pending = [p.stem for p in (self.session / "commands").glob("*.json")
                           if not (self.session / "responses" / p.name).exists()]
            return {"mode": "instant-local-operator-preview", "phase": phase, "host_alive": alive,
                "recognition_source": self.recognition_source, "delegate_profile": self.delegate_profile,
                "learning_enabled": False, "automatic_safety_interception": False if alive else None,
                "local_input_enabled_by_operator": self.allow_local_input,
                "host_is_admin": report.get("host_is_admin"),
                "session_directory": str(self.session) if self.session else None,
                "target": report.get("target"), "pending_ids": pending,
                "cleanup_verified": bool(report.get("finished_at") and report.get("phase") == "stopped"
                    and report.get("host_phase") == "stopped" and report.get("cleanup_errors") == []
                    and report.get("sampler_stopped") is True and not alive),
                "cleanup_errors": report.get("cleanup_errors"), "error_type": report.get("error_type"),
                **({'next': report['cleanup_next']} if report.get('cleanup_next') else {}),
                "automatic_retry_allowed": False}

    def _path(self, request_id, folder):
        _validate_request_id(request_id)
        if self.session is None:
            raise ValueError("start a session first")
        return self.session / folder / (request_id + ".json")

    def submit(self, request_id, command):
        with self.guard:
            path = self._path(request_id, "commands")
            if path.exists():
                if read_json(path) != command:
                    raise ValueError("request_id already belongs to a different command")
                return self.result(request_id)
            status = self.status()
            if status["phase"] != "ready" or not status["host_alive"]:
                raise InstantAdmissionError("host_not_ready", "host is not ready; poll instant_status", "instant_status")
            if status["pending_ids"]:
                raise InstantAdmissionError("command_pending",
                    "one command is still pending; query its original ID, do not queue input",
                    "instant_result", {"request_id": status["pending_ids"][0]})
            if (self.session / "closing.json").exists():
                raise InstantAdmissionError("session_closing", "session is closing", "instant_status")
            write_json(path, command)
            return {"request_id": request_id, "status": "pending", "automatic_retry_allowed": False,
                    "next": "Poll instant_result with this exact request_id"}

    def result(self, request_id):
        with self.guard:
            path = self._path(request_id, "responses")
            if not path.exists():
                if not self._path(request_id, "commands").exists():
                    return {"request_id": request_id, "status": "not_found"}
                pending = {"request_id": request_id, "status": "pending" if self.status()["host_alive"] else "result_unknown",
                           "automatic_retry_allowed": False}
                progress_path = self._path(request_id, "sequence-progress")
                if progress_path.is_file():
                    progress = read_json(progress_path)
                    pending["partial_execution"] = {"completed_steps": progress.get("completed_steps", []),
                        "completed_fields": progress.get("completed_fields", []),
                        "phase": progress.get("phase"), "action_executed": progress.get("action_executed"),
                        "progress_path": str(progress_path), "task_effect_verified": None}
                return pending
            response = read_json(path)
            # 输入可能含个人文本，桥接回执不重复回显原始命令。
            response.pop("command", None)
            result = response.get("result") or {}
            result.pop("request", None)
            ok = response.get("status") == "returned"
            api = result.get("response") or {}
            outcome = result.get("status", "")
            if (result.get("phase") in {"result_unknown", "failed", "rejected"}
                    or result.get("result_unknown") is True or result.get("success") is False
                    or api.get("success") is False
                    or outcome in {"failed", "rejected", "result_unknown"}
                    or str(outcome).endswith("_unavailable")):
                ok = False
            if outcome in {"launched_window_ready", "focused", "maximized"}:
                # 返回成功必须包含有效窗口身份，不能把命令返回当作选中成功。
                window = result.get("window")
                ok = ok and isinstance(window, dict) and all(
                    type(window.get(key)) is int and window[key] > 0
                    for key in ("handle", "process_id"))
            receipt = {"request_id": request_id, **response, "operation_succeeded": ok,
                       "task_effect_verified": False, "automatic_retry_allowed": False}
            if result.get("contract_version") == "agent_command.v1":
                waiting = outcome in {"running", "awaiting_grounding"}
                receipt.update(operation_succeeded=None if waiting else ok and outcome == "completed",
                    operation_success_scope="agent_command_progress", task_effect_verified=None,
                    action_executed=result.get("action_executed"))
                if waiting:
                    receipt['next_action'] = ('read_pending_image_then_grounding_resolve_and_agent_command_continue'
                        if outcome == 'awaiting_grounding' else 'poll_agent_command_status_with_new_request_id')
                    receipt["next"] = {"tool": "instant_run", "arguments": {
                        "request_id": "agent-status-" + uuid4().hex,
                        "command": {"kind": "agent_command_status", "request": {
                            "command_id": result["command_id"]}}, "images": "after"}}
            if outcome == "agent_read_required":
                receipt.update(operation_succeeded=None, operation_success_scope="image_for_agent_reading",
                               task_effect_verified=None, action_executed=False)
            if result.get("contract_version") == "grounding_handoff.v1":
                receipt.update(operation_success_scope="grounding_only", task_effect_verified=None,
                               action_executed=False if result.get("input_dispatched") is False else None)
                if result.get("execution_id"):
                    receipt.update(input_attempted=result.get("input_attempted"),
                                   execution_request_id=result["execution_id"])
            sequence = result.get("contract_version") in {"input_sequence_v1", "form_fill_v1"}
            if result.get("contract_version") == "local_direct_step_v1" or sequence:
                receipt["operation_succeeded"] = (ok and result.get("status") == "completed" if sequence
                                                   else ok and api.get("success") is True)
                before = result.get("capture") or {}
                after = (result.get("observation") or {}).get("capture") or {}
                receipt.update(operation_success_scope="input_route_only",
                               input_route_succeeded=api.get("success") if type(api.get("success")) is bool else None,
                               observation_status=(result.get("observation") or {}).get("status", "not_requested"))
                if sequence:
                    receipt.update(operation_success_scope="declared_sequence_only",
                        input_route_succeeded=None, task_effect_verified=None,
                        action_executed=result.get("action_executed"))
                receipt["agent_review"] = {
                    "status": "awaiting_agent_review" if before and after else "evidence_incomplete",
                    "verified": None, "judged_by": "agent",
                    "before": {"tool": "instant_image", "arguments": {"request_id": request_id, "view": "before"},
                               "frame_id": "before_input", "image_path": before.get("image_path"),
                               "available": bool(before), "sha256": before.get("sha256")},
                    "after": {"tool": "instant_image", "arguments": {"request_id": request_id, "view": "after"},
                              "frame_id": "after_settled", "image_path": after.get("image_path"),
                              "observation_stage": after.get("observation_stage", "after_render_wait"), "render_completion_verified": False,
                              "render_grace_ms": (result.get("observation") or {}).get("render_grace_ms"),
                              "available": bool(after), "sha256": after.get("sha256")},
                    "comparison": {"frame_pair": ["before_input", "after_settled"],
                        "diff_available": False, "reason": "immediate_diagnostic_diff_is_for_a_different_frame_pair"},
                    "automatic_retry_allowed": False,
                    "next": "Read before/after images, judge success/failure/uncertain against the goal. The internal immediate diagnostic diff uses a different frame pair. No change is not necessarily failure. Never replay automatically.",
                }
                if not after:
                    receipt["agent_review"]["recovery"] = (result.get("observation") or {}).get("recovery")
                    receipt["agent_review"]["next"] = (
                        "After image is unavailable; input route outcome is separate from task effect. "
                        "Inspect recovery candidates (same process, not proven successors), then explicitly select "
                        "the intended current window and capture it under a new request_id. If no candidates are "
                        "available, discover current windows. Do not replay the original input; retain this receipt.")
            return receipt

    def image(self, request_id, view="after"):
        if view not in {"before", "after"}:
            raise ValueError("image view must be before or after")
        if self.session is None:
            raise InstantImageError("image_session_unavailable", "start or reattach a session first",
                                    "Use instant_start to attach the intended session; do not replay its actions.")
        try:
            self._path(request_id, "responses")
        except ValueError as error:
            raise InstantImageError("invalid_request_id", str(error),
                                    "Use the exact request_id returned by instant_submit.") from error
        response = self.result(request_id)
        status = response.get("status")
        if status == "not_found":
            raise InstantImageError("image_request_unknown", "no recorded request or response for this ID",
                                    "Check the request ID, session, and submission receipt. A rejected command has no image; do not replay automatically.")
        if status == "pending":
            raise InstantImageError("image_request_pending", "the request has not returned its evidence yet",
                                    "Poll instant_result with the same request_id, then request its image; do not resubmit.")
        if status == "result_unknown":
            raise InstantImageError("image_result_unknown", "the request has no completed receipt and its host is not alive",
                                    "Inspect instant_status and the original request receipt; input may have occurred. Do not replay automatically.")
        if view == "before":
            result = response.get('result') or {}
            if result.get('contract_version') == 'agent_command.v1':
                result = result.get('result') or {}
            capture = result.get("capture") or {}
        else:
            capture = response.get("observation") or {}
            if not capture:
                capture = ((response.get("result") or {}).get("observation") or {}).get("capture") or {}
        path = Path(capture.get("image_path", "")).resolve()
        if self.session is None or not path.is_relative_to(self.session.resolve()) or not path.is_file():
            raise InstantImageError("image_frame_unavailable", "no recorded image for this response",
                                    "Inspect instant_result and agent_review availability. A new capture is a separate observation, not replacement evidence or permission to replay.")
        try:
            data = path.read_bytes()
        except OSError as error:
            raise InstantImageError("image_read_failed", "recorded image could not be read",
                                    "Check local evidence storage and permissions; preserve the receipt and do not replay the action.") from error
        if len(data) > 32 * 1024 * 1024 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise InstantImageError("image_format_invalid", "recorded image is not a supported PNG",
                                    "Preserve the invalid evidence for diagnosis; do not use it to judge or replay the action.")
        if capture.get("sha256") != hashlib.sha256(data).hexdigest():
            raise InstantImageError("image_digest_mismatch", "recorded image digest mismatch",
                                    "Preserve the receipt and mismatched frame for diagnosis; do not substitute another frame or replay the action.")
        return data

    def stop(self):
        with self.guard:
            status = self.status()
            if self.session and status['host_alive'] and (status['phase'] == 'cleanup_pending'
                    or (self.session / 'closing.json').is_file()):
                write_json(self.session / 'cleanup-retry.json', {'request_id': 'cleanup-' + uuid4().hex})
                return {**status, 'cleanup_retry_requested': True,
                        'next': 'Poll instant_status; cleanup retry never replays input.'}
            if self.session and status["host_alive"] and (self.session / "commands").is_dir():
                # 不把关闭排到正在执行的动作前面，也不把排队关闭当作已清理。
                marker = self.session / "closing.json"
                if not marker.exists():
                    request_id = "close-" + uuid4().hex
                    write_json(marker, {"request_id": request_id})
                    write_json(self._path(request_id, "commands"), {"kind": "close"})
                return {**self.status(), "stop_requested": True, "interrupts_inflight_input": False}
            return status

    def close(self):
        self.stop()
        if self.process:
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                # 不杀正在执行的输入；父进程退出后宿主在当前命令结束时自行清理。
                pass
        if self.log_file:
            self.log_file.close()
        if self.lock_file:
            self.lock_file.close()


def build_server(session):
    from mcp.server import MCPServer
    from mcp.types import CallToolResult, ImageContent, TextContent
    server = MCPServer(name="agent-review-instant", version=INSTANT_VERSION, description="Windows instant-mode preview. Local operator input; no learning. Start explicitly, submit ONE command, poll its ID, inspect image before next action. No automatic retries.")

    def instant_start(new_session: bool = False) -> CallToolResult:
        try:
            value = session.start(new_session=new_session)
        except InstantStartError as error:
            # 不捕获启动后的异常，不能把未知宿主状态伪装成未启动。
            value = {"status": "start_rejected", "host_launch_attempted": False,
                     "automatic_retry_allowed": False,
                     "error": {"code": error.code, "message": str(error)}, "next": error.next}
            with session.guard:
                try:
                    session.data_root.mkdir(parents=True, exist_ok=True)
                    with (session.data_root / "startup-errors.jsonl").open("a", encoding="utf-8") as log:
                        log.write(json.dumps({"timestamp_unix": time.time(), **value}, ensure_ascii=False) + "\n")
                except OSError as log_error:
                    value["diagnostic_log_error"] = type(log_error).__name__
            return CallToolResult(isError=True, content=[TextContent(type="text", text=json.dumps(value, ensure_ascii=False))],
                                  structuredContent=value)
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(value, ensure_ascii=False))],
                              structuredContent=value)

    def instant_status() -> dict:
        return session.status()

    def instant_submit(request_id: str, command: InstantCommand) -> CallToolResult:
        validation_code = "invalid_request_id"
        try:
            _validate_request_id(request_id)
            validation_code = "invalid_command"
            validated = command.command()
        except ValueError as error:
            # 只捕获入队前校验，日志不写输入值，执行异常不能伪装成未执行。
            detail = {"code": validation_code, "message": str(error)}
            if isinstance(error, ValidationError):
                detail = {"code": "invalid_command", "message": "Invalid action field values",
                          "issues": [{"field": list(e["loc"]), "type": e["type"]}
                                     for e in error.errors(include_input=False, include_context=False)]}
            for key in ("unknown_fields", "invalid_fields", "allowed_fields"):
                if hasattr(error, key):
                    detail[key] = getattr(error, key)
            value = {"request_id": request_id, "status": "validation_rejected", "accepted": False,
                     "action_executed": False, "automatic_retry_allowed": False, "error": detail,
                     "next": "Correct the listed fields and submit again; this command was not queued. "
                             "Keep the current connection and host; no model restart is required."}
            with session.guard:
                try:
                    root = session.session or session.data_root
                    root.mkdir(parents=True, exist_ok=True)
                    with (root / "validation-errors.jsonl").open("a", encoding="utf-8") as log:
                        log.write(json.dumps({"timestamp_unix": time.time(), **value}, ensure_ascii=False) + "\n")
                except OSError as log_error:
                    value["diagnostic_log_error"] = type(log_error).__name__
            return CallToolResult(isError=True, content=[TextContent(type="text", text=json.dumps(value, ensure_ascii=False))],
                                  structuredContent=value)
        try:
            value = session.submit(request_id, validated)
        except InstantAdmissionError as error:
            # 只转换确定未入队的状态；磁盘写入或执行异常仍不能谎报零输入。
            value = {"request_id": request_id, "status": "state_rejected", "accepted": False,
                     "action_executed": False, "automatic_retry_allowed": False,
                     "error": {"code": error.code, "message": str(error)}, "next": error.next}
            return CallToolResult(isError=True, content=[TextContent(type="text", text=json.dumps(value, ensure_ascii=False))],
                                  structuredContent=value)
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(value, ensure_ascii=False))],
                              structuredContent=value)

    def result_bundle(request_id, *, detail="compact", images="after", receipt=None):
        from app.instant_receipt import compact_receipt
        receipt = session.result(request_id) if receipt is None else receipt
        value = (compact_receipt(receipt, full_receipt_path=session._path(request_id, "responses"))
                 if detail == "compact" else receipt)
        image_blocks = []
        if images != "none" and receipt.get("status") not in {"pending", "not_found", "result_unknown"}:
            delivery = []
            for view in (("before", "after") if images == "both" else ("after",)):
                try:
                    data = session.image(request_id, view=view)
                except InstantImageError as error:
                    delivery.append({"view": view, "status": "unavailable", "error": {
                        "code": error.code, "message": str(error)}, "next": error.next})
                else:
                    delivery.append({"view": view, "status": "included", "sha256": hashlib.sha256(data).hexdigest(),
                                     "content_index": len(image_blocks) + 1, "original_pixels": True})
                    image_blocks.append(ImageContent(type="image", data=base64.b64encode(data).decode("ascii"),
                                                     mimeType="image/png"))
            value["image_delivery"] = delivery
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(value, ensure_ascii=False)),
                                       *image_blocks], structuredContent=value)

    def instant_result(request_id: str, detail: Literal["full", "compact"] = "full",
                       images: Literal["none", "after", "both"] = "none") -> CallToolResult:
        return result_bundle(request_id, detail=detail, images=images)

    async def instant_run(request_id: str, command: InstantCommand, wait_ms: int | None = None,
                          detail: Literal["compact", "full"] = "compact",
                          images: Literal["after", "both", "none"] = "after") -> CallToolResult:
        # 等待只查磁盘回执，不占用会话锁、不重新派发；超时后原命令仍可能在执行。
        try:
            wait_ms = _run_wait_budget(command.kind, wait_ms)
        except ValueError as error:
            value = {"request_id": request_id, "status": "validation_rejected", "accepted": False,
                "automatic_retry_allowed": False, "error": {"code": "invalid_wait_ms",
                "message": str(error)}}
            return CallToolResult(isError=True, content=[TextContent(type="text", text=json.dumps(value))],
                                  structuredContent=value)
        sent = instant_submit(request_id, command)
        if sent.is_error:
            return sent
        deadline = time.monotonic() + wait_ms / 1000
        while True:
            value = session.result(request_id)
            if value.get("status") != "pending":
                return result_bundle(request_id, detail=detail, images=images, receipt=value)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                value.update(wait_expired=True, command_cancelled=False,
                    next={"tool": "instant_result", "arguments": {
                        "request_id": request_id, "detail": detail, "images": images}})
                return result_bundle(request_id, detail=detail, images=images, receipt=value)
            await asyncio.sleep(min(.1, remaining))

    def instant_image(request_id: str, view: Literal["before", "after"] = "after") -> CallToolResult:
        try:
            data = session.image(request_id, view=view)
        except InstantImageError as error:
            value = {"request_id": request_id, "view": view, "status": "image_unavailable",
                     "read_only": True, "automatic_retry_allowed": False,
                     "error": {"code": error.code, "message": str(error)}, "next": error.next}
            return CallToolResult(isError=True, content=[TextContent(type="text", text=json.dumps(value, ensure_ascii=False))],
                                  structuredContent=value)
        return CallToolResult(content=[ImageContent(type="image", data=base64.b64encode(data).decode("ascii"), mimeType="image/png")])

    def instant_stop() -> dict:
        return session.stop()

    descriptions = {
        "instant_run": "Preferred one-call execution: submit one durable command, wait up to wait_ms (0..120000; omitted/null uses 45000 for form_fill, 25000 otherwise), return compact receipt plus exact original after PNG together. This is a maximum receipt wait, NOT an added action delay: ready results return immediately. Configure client timeout above this budget. images=both adds before; detail=full preserves diagnostics. Same commands as instant_submit, including input_sequence request={field_goal,text,clear_existing:true,submit_search:true|false}. A sequence focuses the field through recognition, types, checks the actual focused UIA value, optionally presses Enter for search, then observes. No arbitrary batch, next-result click or task-success claim. Unsupported/unreadable fields interrupt with partial receipts; do not blindly replay. A wait timeout is NOT cancellation: use next to read the same ID, keeping this MCP connection alive.",
        "instant_start": "Start isolated host or reattach last session after reconnect, without launching apps/input. Poll status. new_session=true starts a fresh session ONLY after previous cleanup is verified and receipts resolved; request IDs are session-scoped. Requires operator --allow-local-input option. Known preflight configuration failures and unresolved previous-session rejection return isError=true, status=start_rejected, error.code and next guidance; host_launch_attempted=false refers only to this call, not existing sessions.",
        "instant_status": "Read host, target, pending IDs and cleanup status; no screenshot or input.",
        "instant_submit": "Submit exactly one command with a unique durable ID. desktop_capture and desktop_click require NO prior select or caller handle: auto-resolve the current desktop icon host. desktop_click request={goal,click_kind:'double'} uses a FRESH desktop capture and the existing recognition route; no raw/stale coordinates. Desktop occlusion may remain; inspect images. After an icon opens an app, discover/select its new window; input dispatch is NOT app-launch verification. discover lists configured plus installed desktop apps/windows (Start Menu/Desktop shortcuts and App Paths); launch requires exactly one of app_id, name or absolute local .exe/.lnk path, optional url for configured browsers. Names resolve exactly then by substring; ambiguity returns diagnostics.candidates, choose app_id. prefer_existing defaults true for argument-free launches: reuse a unique identity-matched window, never silently choose among multiple windows. URL/shortcut arguments still dispatch their intended launch. UWP-only links and launcher-to-different-executable window binding are not guaranteed; unavailable is not launch failure proof. select focuses handle/process_id; maximize/capture use selected target; read_text={max_chars:10000} captures the selected window NOW and returns OCR text/line boxes plus exact image evidence (1..20000 chars). Read-only, no VISTA or learning; only captured visible pixels, NOT full page/DOM or guaranteed exact text. Overlays/browser chrome may be included; inspect instant_image for the same request ID; close_launched_window={handle,process_id} explicitly requests graceful close ONLY for a new window launched in this session. window_close_pending is not closed: inspect before disconnecting, never force or auto-confirm unsaved prompts. prepare_models/release_models manage residency. step operations: execute_recognition_plan request={goal,click_kind:'single'|'double'|'right'} (default single; fresh non-learning input only); type_text={text,x,y,click_before_typing:true,clear_existing:false} (explicit click_before_typing:false keeps CURRENT FOCUS/selection; coordinates do not set focus in that mode; clear_existing:true replaces the whole field; never implicitly submits); press_key={key,x,y}, supported keys: Enter, Tab, Shift+Tab, Escape, Backspace, Delete, Left, Right, Up, Down, Home, End, Ctrl+A, Ctrl+Z, Ctrl+Y, Shift+Left, Shift+Right, Shift+Up, Shift+Down, Shift+Home, Shift+End, Ctrl+Home, Ctrl+End. Keys go to CURRENT FOCUS; x/y is an observed window point, not a click or focus instruction. scroll={direction:'down'|'up',wheel_clicks:3,x,y}. Coordinates are current original window screenshot pixels, NOT desktop or resized image coordinates. No arbitrary hotkeys, learning, or shell commands. Submission is NOT completion. Poll same ID; inspect image before next input. Avoid payment/send/delete/final submission.",
        "instant_result": "Read original response without executing again. pending means wait; result_unknown means inspect, never retry blindly. For local steps operation_success_scope=input_route_only; check observation_status and agent_review.recovery separately. operation_succeeded is not proof of task outcome.",
        "instant_image": "Return exact original PNG from a recorded response, without new capture or input. view=before returns the pre-input frame; view=after (default) returns the post-input observation. Missing/pending/corrupt evidence returns isError=true with status=image_unavailable, error.code and next guidance; it says nothing about whether the original input happened. Do not replay automatically. Compare both frames against the goal and report success/failure/uncertain yourself. Pixel change or no change alone does not prove task outcome.",
        "instant_stop": "Request graceful stop after current command. Does not undo or interrupt inflight input. Poll status until cleanup_verified=true. If phase=cleanup_pending, inspect cleanup diagnostics and resolve the blocker before calling stop again: it explicitly retries cleanup only, never input. The owner may remain alive while cleanup is unresolved; do not delete session records. Does not close user apps itself; a Windows MCP client may terminate its launched descendants on disconnect. Explicitly close test-created windows first using close_launched_window and verify window_closed.",
    }
    descriptions["instant_submit"] += " Also supports kind=input_sequence, request={field_goal,text,clear_existing:true,submit_search:true|false}; observation_wait_ms applies to the final Enter observation. Use instant_run for bounded waiting and inline final image without separate polling/image calls."
    for name in ("instant_submit", "instant_run"):
        descriptions[name] += " With an agent_current/agent_delegate session, step recognition, desktop_click, input_sequence and form_fill require top-level vision_capabilities (same fields as grounding capabilities). They return agent_command.v1 rather than blocking for vision. Poll agent_command_status request={command_id} using a NEW outer request_id. At awaiting_grounding read the returned original image and pending_grounding.output_schema; submit grounding_resolve for pending_grounding.request_id, then agent_command_continue request={command_id,grounding_request_id} with another new outer request_id. Never resubmit the original batch or use grounding_execute for a suspended batch. It resumes the original worker and may request further grounding. agent_command_cancel request={command_id} requests cooperative cancellation; wait for terminal status, since input may already have occurred. Active jobs reject competing input or target changes. Read_text on Agent sources returns agent_read_required plus original PNG, text=null, with no local OCR; the agent must read it. Agent routes do not automatically invoke another model or assume image capability."
        descriptions[name] += " Experimental grounding handoff: grounding_prepare request={goal,configuration:{source:'agent_current'|'agent_delegate',delegate_profile?:name},capabilities:{image_transport:'supported'|'unsupported'|'unknown',current_vision?:state,delegation?:state,model_selection?:state,delegate_vision?:state}} captures selected window and returns awaiting_grounding plus immutable image. grounding_resolve request={grounding_request_id:original_prepare_id,result:grounding.v1_object}; grounding_status/grounding_cancel request={grounding_request_id}. These four commands never click. Explicit grounding_execute request={grounding_request_id} dispatches one click through the existing action route only when the candidate is ready and live identity, viewport and target-region consistency checks pass. It does not load a local vision model or prove semantic hit. Execution is claimed durably before input and cannot be replayed: poll the original execution request ID and inspect its before/after images. Never turn coordinates into unchecked input."
        descriptions[name] += " form_fill accepts request={fields:[...],text_navigation:'recognize_each'|'tab_sequence'|'tab_groups'}, 1..32 declared fields: text {kind,field_goal,text,clear_existing,label?,tab_group?}, date {kind,field_goal,value,format}, dropdown {kind,label,option}, checkbox {kind,label,checked}, radio {kind,label}. Prefer one grouped call for all currently known fields, not one tool call per field; missing facts need not block independent known fields. Optional tab_sequence requires ONLY consecutive text fields with distinct exact accessible labels. tab_groups accepts mixed fields: assign identical tab_group strings only to adjacent text fields whose actual Tab order is known; labels must be exact and distinct within each run. New group, non-text or omitted tab_group always starts fresh recognition; tab_group is invalid outside tab_groups mode. Recognize each group head, then Tab, verify focused field label/identity, fill and read back locally; return one batch receipt and final image. Wrong focus interrupts BEFORE typing; never guesses/skips fields or auto-replays. Default recognize_each preserves mixed control handling. Compact fields include aggregate timings; full diagnostics remain available by ID. Date value must be a real ISO YYYY-MM-DD date; format is explicitly YYYY-MM-DD, DD/MM/YYYY or MM/DD/YYYY. Date fills an editable text field and checks exact displayed text; it does NOT navigate calendars, guess locale or verify server acceptance. Exact current accessible labels are required for choices; read current screenshots first. It never submits a form; already-satisfied choices are not toggled. Unknown/ambiguous/unreadable states interrupt with partial receipts. Dropdown options must belong to the opened control. Inspect original images; completion is not task success."
    descriptions["instant_result"] += " Optional detail=compact omits verbose traces; full (default) keeps the old receipt fields. images=after|both includes original PNGs in this same call; default none preserves JSON-only delivery."
    for name in ("instant_submit", "instant_run"):
        descriptions[name] += " Optional command.observation_condition={text:exact_accessible_name,control_type:Text|Hyperlink|Button|Document} enables read-only early observation for step or submit_search sequences. Requires a positive observation_wait_ms budget (navigation defaults to 2000). Only a newly appearing unique visible match, repeated and rechecked after capture, ends early. Accessible names can differ from screenshot captions. Missing/ambiguous/old matches time out and still return an image; inspect observation.condition, not operation_succeeded, for this outcome. This is not full-page readiness or task verification. Synchronous UIA and capture I/O are outside a hard timeout; no input replay. Omit the condition when no reliable marker is known."
    for fn in (instant_start, instant_status, instant_submit, instant_result, instant_image, instant_stop, instant_run):
        server.add_tool(fn, name=fn.__name__, description=descriptions[fn.__name__])
    return server
