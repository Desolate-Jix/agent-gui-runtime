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

from app.core.instant_attachment_transport import InstantAttachmentTransport, InstantAdmissionError, _validate_request_id

INSTANT_VERSION = "0.1.5"


def _run_wait_budget(kind, requested):
    # 只延长回执等待，不延长动作等待、不持锁，也不重发输入。
    if requested is None:
        return 45000 if kind == "form_fill" else 25000
    if type(requested) is not int or not 0 <= requested <= 120000:
        raise ValueError("wait_ms must be an integer from 0 to 120000, or null for command defaults")
    return requested




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




class InstantCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["discover", "launch", "select", "maximize", "capture", "read_text", "prepare_models", "release_models", "step", "input_sequence", "form_fill", "close_launched_window", "desktop_capture", "desktop_click", "grounding_prepare", "grounding_resolve", "grounding_status", "grounding_cancel", "grounding_execute", "agent_command_status", "agent_command_continue", "agent_command_cancel", "task_plan"]
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
    decision_check: dict | None = None
    action_review: dict | None = None
    field_evidence_mode: Literal["legacy", "visual"] | None = None

    def command(self):
        from app.vision.grounding_commands import GROUNDING_COMMANDS, validate_grounding_command
        from app.vision.agent_command_contract import AGENT_COMMANDS
        value = self.model_dump(exclude_none=True)
        fields = {
            "launch": (set(), {"app_id", "name", "path", "url", "prefer_existing"}),
            "select": ({"handle", "process_id"}, {"handle", "process_id"}),
            "close_launched_window": ({"handle", "process_id"}, {"handle", "process_id", "request"}),
            "step": ({"operation", "request"}, {"operation", "request", "observation_wait_ms", "observation_condition", "vision_capabilities", "decision_check", "action_review"}),
            "input_sequence": ({"request"}, {"request", "observation_wait_ms", "observation_condition", "vision_capabilities", "action_review", "field_evidence_mode"}),
            "form_fill": ({"request"}, {"request", "vision_capabilities"}),
            "read_text": (set(), {"max_chars"}),
            "task_plan": ({"request"}, {"request"}),
            "desktop_click": ({"request"}, {"request", "observation_wait_ms", "observation_condition", "vision_capabilities"}),
        }
        required, allowed = (({"request"}, {"request"}) if self.kind in GROUNDING_COMMANDS or self.kind in AGENT_COMMANDS
                             else fields.get(self.kind, (set(), set())))
        present = set(value) - {"kind"}
        if not required <= present or present - allowed:
            raise ValueError("command fields do not match kind")
        if self.decision_check is not None:
            from app.execution.decision_check import validate_decision_check
            check = validate_decision_check(self.decision_check)
            if check["phase"] == "before_action" and self.operation != "execute_recognition_plan":
                raise ValueError("decision_before_action_route_unsupported")
        if self.action_review is not None:
            from app.execution.action_review import normalize_action_review_context
            from app.execution.task_plan_contract import resolve_action_text
            context = normalize_action_review_context(self.action_review)
            action = next(row["action"] for row in context["plan"]["steps"] if row["step_id"] == context["step_id"])
            if self.kind == "step":
                if (self.operation != "execute_recognition_plan" or action["kind"] != "click"
                        or action["goal"] != self.request.get("goal")
                        or action.get("click_kind", "single") != self.request.get("click_kind", "single")):
                    raise ValueError("action_review_command_mismatch")
            elif self.kind == "input_sequence":
                if action["kind"] != "input_sequence":
                    raise ValueError("action_review_command_mismatch")
                expected = {key: action[key] for key in ("field_goal", "clear_existing", "submit_search")}
                expected["text"] = resolve_action_text(action["text"], context["plan"]["inputs"])
                if any(self.request.get(key) != val for key, val in expected.items()):
                    raise ValueError("action_review_command_mismatch")
            value["action_review"] = context
        if self.field_evidence_mode == "visual" and self.action_review is None:
            raise ValueError("visual_field_requires_action_review_context")
        if self.kind in GROUNDING_COMMANDS:
            validate_grounding_command(self.kind, self.request)
        if self.kind in AGENT_COMMANDS:
            AGENT_COMMANDS[self.kind].model_validate(self.request)
        if self.vision_capabilities is not None:
            from app.vision.recognition_source import ClientVisionCapabilities
            ClientVisionCapabilities.model_validate(self.vision_capabilities)
        if self.kind == "close_launched_window" and "request" in self.model_fields_set:
            from app.execution.launched_window_ownership import validate_close_ownership_request
            validate_close_ownership_request(self.request)
        if self.kind == "launch":
            selectors = [value[key] for key in ("app_id", "name", "path") if key in value]
            if len(selectors) != 1 or not selectors[0].strip():
                raise ValueError("launch requires exactly one non-empty app_id, name or path")
        if self.kind in {"step", "desktop_click"}:
            from app.execution.local_action_contract import _validated_request
            # 只验证，运行时再次验证；不在桥接层重写执行请求。
            _validated_request("execute_recognition_plan" if self.kind == "desktop_click" else self.operation, self.request)
        elif self.kind == "input_sequence":
            from app.execution.input_sequence import InputSequenceRequest
            InputSequenceRequest.model_validate(self.request)
        elif self.kind == "task_plan":
            from app.execution.task_plan_admission import validate_task_plan_request
            validate_task_plan_request(self.request)
        elif self.kind == "form_fill":
            from app.execution.form_fill import FormFillRequest
            FormFillRequest.model_validate(self.request)
        if self.observation_condition is not None:
            from app.core.observation_policy import resolve_render_grace_ms, local_action_observation_kind
            from app.execution.conditional_observation import validate_condition
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


class InstantSession(InstantAttachmentTransport):
    def __init__(self, root, data_root, model_directory=None, *, allow_local_input=False,
                 recognition_source="local", delegate_profile=None, api_profile=None, decision_profile=None):
        self.root = Path(root).resolve()
        self.data_root = Path(data_root).resolve()
        self.model_directory = Path(model_directory).resolve() if model_directory is not None else None
        self.recognition_source = recognition_source
        self.delegate_profile = delegate_profile
        self.api_profile = str(Path(api_profile).resolve()) if api_profile is not None else None
        configured_decision = decision_profile or os.environ.get("AGENT_GUI_DECISION_PROFILE")
        self.decision_profile = str(Path(configured_decision).resolve()) if configured_decision else None
        self.decision_profile_sha256 = None
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

    def _startup_configuration(self):
        if self.decision_profile is not None:
            from app.judgment.profile import load_decision_profile
            try:
                load_decision_profile(self.decision_profile)
                self.decision_profile_sha256 = hashlib.sha256(Path(self.decision_profile).read_bytes()).hexdigest()
            except (OSError, ValueError):
                raise InstantStartError("decision_profile_invalid", "invalid decision profile",
                    "Check --decision-profile JSON; credentials belong in its named environment variable.") from None
        if not self.allow_local_input:
            raise InstantStartError("local_input_not_enabled",
                "Local operator must explicitly launch with --allow-local-input; tools cannot change this",
                "Ask the operator to check the MCP launch configuration; do not change input authorization automatically.")
        from app.vision.recognition_source import RecognitionSourceConfig
        from pydantic import ValidationError
        try:
            config = RecognitionSourceConfig.model_validate({"source": self.recognition_source,
                "delegate_profile": self.delegate_profile, "api_profile": self.api_profile})
        except ValidationError:
            raise InstantStartError("invalid_recognition_configuration",
                "invalid recognition source or profile",
                "Check --recognition-source, --delegate-profile and --api-profile match the chosen route.") from None
        if config.source == "external_api":
            from app.vision.external_grounding_api import load_api_grounding_profile, ApiGroundingError
            try:
                profile = load_api_grounding_profile(config.api_profile)
                if not os.environ.get(profile.api_key_env, "").strip():
                    raise ApiGroundingError("api_key_missing")
            except ApiGroundingError as error:
                raise InstantStartError(error.code, error.code,
                    "Check the API profile JSON and its named environment variable in the server process; then reconnect.") from None
        if config.source == "local" and (self.model_directory is None or not self.model_directory.is_dir()):
            raise InstantStartError("model_directory_unavailable", "configured model directory does not exist",
                "Check --model-directory is an existing directory; use forward slashes or escaped backslashes in configuration, then reconnect.")
        return config

    def start(self, new_session=False):
        with self.guard:
            config = self._startup_configuration()
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
                if (saved.get("decision_profile") != self.decision_profile
                        or saved.get("decision_profile_sha256") != self.decision_profile_sha256):
                    if not new_session or not status["cleanup_verified"] or status["pending_ids"]:
                        raise InstantStartError("decision_profile_mismatch", "existing session uses a different decision profile",
                            "Finish the original session and verify cleanup, then start a new session with the chosen profile.")
                if (saved.get("recognition_source", "local") != config.source
                        or saved.get("delegate_profile") != config.delegate_profile
                        or saved.get("api_profile") != config.api_profile):
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
            self._check_peer_hosts()
            return self._launch_session(config)

    def _check_peer_hosts(self, *, exclude_session=None):
        # 已核验的原死会话仅由显式准入排除，普通 start 保持原清理门控。
        import psutil
        excluded = Path(exclude_session).resolve() if exclude_session is not None else None
        for path in self.data_root.glob("session-*/report.json"):
            if path.parent.resolve() == excluded:
                continue
            old = read_json(path)
            if not old.get("finished_at") and psutil.pid_exists(old.get("runner_pid", -1)):
                raise ValueError("previous host still active or cleaning up; inspect its report before restarting")

    def _launch_session(self, config, *, session_name=None, on_created=None, before_publish=None):
        import psutil
        name = session_name or "session-" + uuid4().hex
        target = (self.data_root / name).resolve()
        if not re.fullmatch(r"session-[0-9a-f]{32}", name) or target.parent != self.data_root or target.exists():
            raise ValueError("invalid or existing new session directory")
        if self.log_file:
            self.log_file.close()
        self.session = target
        self.log_file = (self.data_root / (name + ".log")).open("ab")
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", HF_HUB_OFFLINE="1")
        env.pop("PYTHONPATH", None)
        command = [sys.executable, str(self.root / "scripts/run_local_step_session.py"),
            "--output", str(self.session), "--recognition-source", config.source,
            "--local-no-learning", "--parent-pid", str(os.getpid())]
        if config.source == "local":
            command.extend(["--model-directory", str(self.model_directory)])
        if config.delegate_profile:
            command.extend(["--delegate-profile", config.delegate_profile])
        if config.api_profile:
            command.extend(["--api-profile", config.api_profile])
        if self.decision_profile:
            command.extend(["--decision-profile", self.decision_profile])
        self.process = subprocess.Popen(command, cwd=self.root,
            stdin=subprocess.DEVNULL, stdout=self.log_file, stderr=self.log_file,
            env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.host_identity = {"pid": self.process.pid, "created": psutil.Process(self.process.pid).create_time()}
        if on_created is not None:
            on_created(self.host_identity)
        if before_publish is not None:
            before_publish()
        write_json(self.data_root / "latest-session.json", {"name": self.session.name, "host_identity": self.host_identity,
            "recognition_source": config.source, "delegate_profile": config.delegate_profile,
            "api_profile": config.api_profile,
            **({"decision_profile": self.decision_profile, "decision_profile_sha256": self.decision_profile_sha256}
               if self.decision_profile is not None else {})})
        return self.status()

    def preview_recovery(self):
        from app.execution.session_epoch_admission import SessionEpochAdmission
        with self.guard:
            return SessionEpochAdmission(self).preview()

    def recover_session(self, request_id, preview_sha256):
        from app.execution.session_epoch_admission import SessionEpochAdmission
        return SessionEpochAdmission(self).recover(request_id, preview_sha256)




    def submit(self, request_id, command):
        command = InstantCommand.model_validate(command).command()
        with self.guard:
            from app.execution.public_input_defaults import adopt_session_input_command
            command = adopt_session_input_command(self, request_id, command)
            path = self._path(request_id, "commands")
            if path.exists():
                if read_json(path) != command:
                    raise ValueError("request_id already belongs to a different command")
                return self.result(request_id)
            status = self.status()
            return self._live_submit(request_id, command, status)



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
        result = response.get("result") or {}
        if result.get("contract_version") == "agent_command.v1":
            if result.get("command_id") == request_id:
                # 原接收快照不含最终图；复用同命令终态回执解析，不重派或补截图。
                from app.learning_memory.receipt_adapter import ExecutionReceiptPending, resolve_execution_receipt
                try:
                    response, _ = resolve_execution_receipt(response, self._path(request_id, "responses"), request_id)
                except ExecutionReceiptPending as error:
                    raise InstantImageError("image_request_pending", "the agent command has no terminal evidence yet",
                                            "Poll the original command status; do not resubmit its input.") from error
                except (OSError, ValueError) as error:
                    raise InstantImageError("image_frame_unavailable", "the recorded agent evidence is unavailable or mismatched",
                                            "Inspect the original receipt and worker evidence; do not replay or substitute a new capture.") from error
                result = response.get("result") or {}
            else:
                try:
                    command = read_json(self._path(request_id, "commands"))
                    if (not isinstance(command, dict)
                            or command.get("kind") not in {"agent_command_status", "agent_command_continue", "agent_command_cancel"}
                            or (command.get("request") or {}).get("command_id") != result.get("command_id")):
                        raise ValueError("agent image command identity mismatch")
                except (OSError, ValueError) as error:
                    raise InstantImageError("image_frame_unavailable", "the recorded agent command identity is mismatched",
                                            "Inspect the original command and receipt; do not read another command's image or replay input.") from error
                result = result.get("result") or {}
        if view == "before":
            capture = result.get("capture") or {}
        else:
            capture = response.get("observation") or {}
            if not capture.get("image_path"):
                capture = capture.get("capture") or {}
            if not capture:
                capture = (result.get("observation") or {}).get("capture") or {}
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
    server = MCPServer(name="agent-review-instant", version=INSTANT_VERSION, description="Windows instant runtime. Default bounded v2 plans use local verification, optional adaptive Decision and review by the existing Main; standalone input remains available. Start explicitly and keep one input owner. Advance only on declared verified outcomes; inspect original evidence when review is returned. Optional receipt recording starts disabled. No input replay, implicit authority or automatic retries.")

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

    def instant_recovery_preview() -> CallToolResult:
        try:
            value = session.preview_recovery()
        except (ValueError, OSError) as error:
            value = {"status": "recovery_preview_rejected", "read_only": True,
                "automatic_retry_allowed": False, "error": {"type": type(error).__name__, "message": str(error)}}
            return CallToolResult(isError=True, content=[TextContent(type="text", text=json.dumps(value, ensure_ascii=False))],
                structuredContent=value)
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(value, ensure_ascii=False))],
            structuredContent=value)

    def instant_recover_session(request_id: str, preview_sha256: str) -> CallToolResult:
        try:
            value = session.recover_session(request_id, preview_sha256)
        except (ValueError, OSError) as error:
            # 此错误可能发生在创建之后，不能推断未启动或原输入未执行。
            value = {"request_id": request_id, "status": "recovery_unresolved", "host_launch_attempted": None,
                "automatic_retry_allowed": False, "error": {"type": type(error).__name__, "message": str(error)},
                "next": "Inspect the original admission record and host status; keep the same request_id and preview hash. Do not create another admission or replay input."}
            return CallToolResult(isError=True, content=[TextContent(type="text", text=json.dumps(value, ensure_ascii=False))],
                structuredContent=value)
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(value, ensure_ascii=False))],
            structuredContent=value)

    def instant_submit(request_id: str, command: InstantCommand) -> CallToolResult:
        validation_code = "invalid_request_id"
        try:
            _validate_request_id(request_id)
            validation_code = "invalid_command"
            validated = command.command()
            if validated["kind"] == "input_sequence":
                from app.execution.public_input_defaults import adopt_session_input_command
                with session.guard:
                    validated = adopt_session_input_command(session, request_id, validated)
        except ValueError as error:
            # 只捕获入队前校验，日志不写输入值，执行异常不能伪装成未执行。
            detail = {"code": validation_code, "message": str(error)}
            if isinstance(error, ValidationError):
                detail = {"code": "invalid_command", "message": "Invalid action field values",
                          "issues": [{"field": list(e["loc"]), "type": e["type"]}
                                     for e in error.errors(include_input=False, include_context=False)]}
            for key in ("missing_fields", "unknown_fields", "invalid_fields", "allowed_fields"):
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
        feedback_image = (receipt.get("learning_control") == "learning_feedback"
                          and (receipt.get("result") or {}).get("image_role") == "feedback_baseline_not_live_observation")
        plan_control = receipt.get("operation_success_scope") == "task_plan_control"
        manual = (receipt.get("result") or {}).get("manual_observation") if plan_control else None
        video_packet = ((receipt.get("result") or {}).get("review_packet") or {}) if plan_control else {}
        if images != "none" and video_packet.get("schema") == "review_packet.v4":
            from app.execution.task_plan_observation_delivery import video_playback_images
            from PIL import Image
            try:
                samples = video_playback_images(session.session, receipt["result"])
            except (OSError, ValueError, TypeError, KeyError, Image.DecompressionBombError) as error:
                value["image_delivery"] = [{"view": "video_playback", "status": "unavailable",
                    "error": {"code": "video_playback_images_unavailable", "error_type": type(error).__name__},
                    "automatic_retry_allowed": False}]
            else:
                value["image_delivery"] = []
                for data, frame, elapsed_ms in samples:
                    value["image_delivery"].append({"view": "observation", "status": "included",
                        "sha256": frame["sha256"], "capture_id": frame["capture_id"],
                        "elapsed_ms": elapsed_ms, "packet_sha256": video_packet["packet_sha256"],
                        "content_index": len(image_blocks) + 1, "original_pixels": True,
                        "original_action_after": False})
                    image_blocks.append(ImageContent(type="image", data=base64.b64encode(data).decode("ascii"),
                        mimeType="image/png"))
        if images != "none" and isinstance(manual, dict) and manual.get("status") == "captured":
            from app.execution.task_plan_observation_delivery import manual_observation_image
            from PIL import Image
            try:
                data, frame = manual_observation_image(session.session, receipt["result"])
            except (OSError, ValueError, TypeError, KeyError, Image.DecompressionBombError) as error:
                value["image_delivery"] = [{"view": "observation", "status": "unavailable",
                    "error": {"code": "task_plan_observation_image_unavailable", "error_type": type(error).__name__},
                    "automatic_retry_allowed": False,
                    "next": "Read the current plan status and inspect its evidence; do not repeat input or observation automatically."}]
            else:
                value["image_delivery"] = [{"view": "observation", "status": "included", "sha256": frame["sha256"],
                    "capture_id": frame["capture_id"], "packet_sha256": manual["packet_sha256"],
                    "content_index": 1, "original_pixels": True, "original_action_after": False}]
                image_blocks.append(ImageContent(type="image", data=base64.b64encode(data).decode("ascii"),
                    mimeType="image/png"))
        if images != "none" and not plan_control and (not receipt.get("learning_control") or feedback_image) and receipt.get("status") not in {"pending", "not_found", "result_unknown"}:
            delivery = []
            views = ("before",) if feedback_image else (("before", "after") if images == "both" else ("after",))
            for view in views:
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
        "instant_recovery_preview": "Experimental read-only recovery preview after the original host exits: verify original resource cleanup and all input terminal/settlement facts, returning preview_sha256. Does not modify the old session, start a host, grant input, replay commands or take over a workflow. Unknown dispatch or unverifiable resources reject. Ordinary instant_start cleanup requirements remain unchanged.",
        "instant_recover_session": "Experimental explicit new-epoch admission: use the exact preview_sha256 from instant_recovery_preview and a unique durable request_id. Reuses the original launcher only after resource and input proofs; requires the existing operator --allow-local-input and route configuration. Re-read this SAME request_id/hash to inspect a starting host or recover interrupted pointer publication; NEVER create another request ID for an unresolved admission. launch_unknown cannot be replayed. Exceptions after launch may mean a host exists: inspect the durable admission, not zero-input or restart assumptions. Before submitting ANY new command, this SAME recovery request must return recovery_admission.phase=ready and new_epoch_ready=true; instant_status.phase=ready alone is insufficient. Premature commands return state_rejected/recovery_admission_not_ready with this original request/hash in next; original receipt reads remain available. Readiness does not complete workflow takeover, and old commands are never consumed.",
        "instant_submit": "Submit exactly one command with a unique durable ID. desktop_capture and desktop_click require NO prior select or caller handle: auto-resolve the current desktop icon host. desktop_click request={goal,click_kind:'double'} uses a FRESH desktop capture and the existing recognition route; no raw/stale coordinates. Desktop occlusion may remain; inspect images. After an icon opens an app, discover/select its new window; input dispatch is NOT app-launch verification. discover lists configured plus installed desktop apps/windows (Start Menu/Desktop shortcuts and App Paths); launch requires exactly one of app_id, name or absolute local .exe/.lnk path, optional url for configured browsers. Names resolve exactly then by substring; ambiguity returns diagnostics.candidates, choose app_id. prefer_existing defaults true for argument-free launches: reuse a unique identity-matched window, never silently choose among multiple windows. URL/shortcut arguments still dispatch their intended launch. UWP-only links and launcher-to-different-executable window binding are not guaranteed; unavailable is not launch failure proof. select focuses handle/process_id; maximize/capture use selected target; read_text={max_chars:10000} captures the selected window NOW and returns OCR text/line boxes plus exact image evidence (1..20000 chars). Read-only, no VISTA or learning; only captured visible pixels, NOT full page/DOM or guaranteed exact text. Overlays/browser chrome may be included; inspect instant_image for the same request ID; close_launched_window={handle,process_id} explicitly requests graceful close ONLY for a new window launched in this session. window_close_pending is not closed: inspect before disconnecting, never force or auto-confirm unsaved prompts. prepare_models/release_models manage residency. step operations: execute_recognition_plan request={goal,click_kind:'single'|'double'|'right'} (default single; fresh non-learning input only); type_text={text,x,y,click_before_typing:true,clear_existing:false} (explicit click_before_typing:false keeps CURRENT FOCUS/selection; coordinates do not set focus in that mode; clear_existing:true replaces the whole field; never implicitly submits); press_key={key,x,y}, supported keys: Enter, Tab, Shift+Tab, Escape, Backspace, Delete, Left, Right, Up, Down, Home, End, Ctrl+A, Ctrl+Z, Ctrl+Y, Shift+Left, Shift+Right, Shift+Up, Shift+Down, Shift+Home, Shift+End, Ctrl+Home, Ctrl+End. Keys go to CURRENT FOCUS; x/y is an observed window point, not a click or focus instruction. scroll={direction:'down'|'up',wheel_clicks:3,x,y}. Coordinates are current original window screenshot pixels, NOT desktop or resized image coordinates. No arbitrary hotkeys, learning, or shell commands. Submission is NOT completion. Poll same ID; inspect image before next input. Avoid payment/send/delete/final submission.",
        "instant_result": "Read original response without executing again. pending means wait; result_unknown means inspect, never retry blindly. For local steps operation_success_scope=input_route_only; check observation_status and agent_review.recovery separately. operation_succeeded is not proof of task outcome.",
        "instant_image": "Return exact original PNG from a recorded response, without new capture or input. view=before returns the pre-input frame; view=after (default) returns the post-input observation. Missing/pending/corrupt evidence returns isError=true with status=image_unavailable, error.code and next guidance; it says nothing about whether the original input happened. Do not replay automatically. Compare both frames against the goal and report success/failure/uncertain yourself. Pixel change or no change alone does not prove task outcome.",
        "instant_stop": "Request graceful stop after current command. Does not undo or interrupt inflight input. Poll status until cleanup_verified=true. If phase=cleanup_pending, inspect cleanup diagnostics and resolve the blocker before calling stop again: it explicitly retries cleanup only, never input. The owner may remain alive while cleanup is unresolved; do not delete session records. Does not close user apps itself; a Windows MCP client may terminate its launched descendants on disconnect. Explicitly close test-created windows first using close_launched_window and verify window_closed.",
    }
    descriptions["instant_submit"] += " Source v3 plans add goal and completion={step_id:final_step_id,verification:existing_v2_verification}. With external Luna target_description enabled, new v3 actions need no manually prepared identity options. Grounding returns coordinates plus one unverified appearance/container description in the same response. The unchanged original action goal defines the target: input_sequence checks only whether the marker is inside that input field; a click checks the marked graphic/button against the original goal. These are mutually exclusive question routes, not competing identity classes. Each sends one marked image and one fixed Choice question; nonpass gets one ordinary Luna review of the same evidence/question, then returns to the existing Main when unresolved. Explicit legacy target_identity remains diagnostic compatibility; identity_options no longer generates automatic classes. Neither locator hints nor candidate labels redefine the original goal. They default to recovery_policy=intervention_v1 and inject a 60s shared action-review budget. All click/input focus actions use one combined candidate Decision; allowlist and profile caps remain explicit. Optional scene_precheck=parallel remains off by default. start accepts recovery_policy=legacy|intervention_v1. A proven zero-input wait offers recover (packet bindings, recovery_request_id and a fresh gated step command) or resume_pre_dispatch (same bindings plus reason); the old failed attempt is retained and a new execution ID is created. Partial/unknown input never uses zero-input resume. A final different completion condition returns to the existing Main for read-only review, without another action. Standalone step/input_sequence may carry action_review={schema:action_review_context.v1,plan,step_id,run_id,attempt_id,budget_ms}; only input_sequence accepts field_evidence_mode=visual. Visual field proof can add focus/value and one selection assessment; it does not make every keyboard verification a model call."
    for name in ("instant_submit", "instant_run"):
        descriptions[name] += " Target wording contract: action.goal and field_goal describe only the current visible target, with every required qualifier preserved. State filtering and ordering explicitly: first matching result with domain X means filter by X then take the first; first result overall is a different requirement. Keep task-wide objectives in plan.goal, expected outcomes in verification, and retry/recovery policy out of the target description. Use one concise target description for both visual grounding and candidate Decision; never replace it with the model candidate label or silently drop a required constraint."
    descriptions["instant_submit"] += " Also supports kind=input_sequence, request={field_goal,text,clear_existing:true,submit_search:true|false}; observation_wait_ms applies to the final Enter observation. Use instant_run for bounded waiting and inline final image without separate polling/image calls."
    for name in ("instant_submit", "instant_run"):
        descriptions[name] += " For the configured combined visual/Decision route use task_plan.v3 with explicit goal and completion; v1/v2 retain their original semantics and remain the no-Decision compatibility route. It retains v1 action limits and permits agent_judgment allowed_states and review_policy='always_main' (tightening only). V2 semantic adoption requires decision_profile.v2; new v2 profiles default to auto with proactive_review=true and adaptive review. Exact conditions or template identities still need approval. With no configured profile or explicit off, complete local proof continues without Decision; otherwise return the original wait to the existing Main. Preserve explicit shadow/always_main, v1 profiles and frozen sessions. Success with review_required cannot advance the suffix. With decision_condition, optional wait_policy={loading_condition:explicit_visible_loading_condition,completion_excludes_loading:boolean} allows bounded read-only follow-up in auto mode when the authenticated judgment says observe. Poll task_plan_run while observation_pending=true; do not review, resend input or create a Main session during this wait. The original after image stays unchanged. At most two extra captures and two total assessments per step use a 12-second scheduling/adoption budget, not hard interruption of synchronous calls. At review waits, read the current review_packet.v1 or v2 from task_plan_run; review additionally requires its current review_packet_sha256=packet_sha256, evidence_set_sha256 and assessment_round (copy it, do not assume zero). Review returns to the existing caller; continue remains explicit with the original wait_id. To replan, close the parent and prove terminal/quiescent input, then start a new v2 plan with request.successor={successor_request_id,successor_of,parent_plan_sha256,prefix_sha256,lineage_generation,reason}. Copy hashes/generation from parent status. Keep this logical successor ID across transport retries; matching retries only read the original successor, never switch another active run. Partial/unknown input and identical completed-parent commands block admission, including intentional repeated navigation. Same host/target only. At an existing v2 review wait, action='observe' takes run_id, step_id, execution_request_id, wait_id, observation_request_id and the current review_packet_sha256/evidence_set_sha256/assessment_round. Keep the logical observation_request_id across transport retries. Observe captures read-only evidence, never input, inference, settlement or continuation. It shares the two-capture attempt cap with automatic observation, has a separate 12-second adoption deadline after Main intervention, and never resets the original automatic deadline. Unknown capture is not retried. New review_packet.v3 preserves original after, adds latest_observation and packet revision/ancestry; prior model advice still belongs to assessment_basis. Review must bind the new packet; old reviews are rejected. Use images='after' on the observe receipt to view the explicitly labeled observation. Native_condition may explicitly declare the same v2 semantic options: complete native proof remains local; only a valid maintained native timeout can continue to Decision. Versioned condition_binding templates are connected to execution and learning. Auto adoption requires the exact approved template ID/revision/SHA; edits create a new reviewable revision."
    for name in ("instant_submit", "instant_run"):
        descriptions[name] += " Linear task_plan control: request={action:'start',plan:{schema_version:'task_plan.v2',title,inputs,steps},vision_capabilities?}. A nonempty linear plan has no fixed step-count cap; existing context-size and API/time budgets still apply. Steps use explicit step_id/action/verification. Actions are click(goal,click_kind?,target?), input_sequence(field_goal,text,clear_existing,submit_search,target?), or read_text(goal); target={name,control_type,container?:{name,control_type}} is a current semantic selector, not stored coordinates. No learned target_memory, branches or dynamic output references. Verification is native_condition(condition:{text,control_type}) for click/search transitions, or agent_judgment(decision_condition?). The host queues the original gated commands and advances only on verified success. Read instant_status.task_plan_run while execution is pending; status polling must not compete with input or resubmit start. Wait reason grounding_required still needs the existing client grounding protocol on active_command_id. Decision is optional and auto requires the frozen exact allowlist. For verification_required, review requires run_id/execution_request_id/step_id/verdict/reason/evidence_sha256 of the original after image, followed by explicit continue with the original wait_id. cancel preserves partial/unknown input; cancel_requested is not completion. No automatic cross-host resume. Plan status is not task success. See docs/development/TASK_PLAN.md and docs/verification/CONTINUOUS_EXECUTION_ACCEPTANCE.md for the tested scope and remaining limits."
    for name in ("instant_submit", "instant_run"):
        descriptions[name] += " Experimental target_memory={recipe_id,interface_key,state_key} is accepted on recognition clicks and input_sequence field focus. Only the configured host library resolves it against current window/context evidence before visual model work. A valid current match reuses the original action API; expected misses retain their reason and use the selected source. Corrupt assets or conflicting identities fail explicitly. Standalone HTTP target_memory use requires the host. No stored coordinate replay or silent provider switching. Dynamic row recipes still require trusted run-binding integration; internal scheduling is not yet a public run/continue action."
    for name in ("instant_submit", "instant_run"):
        descriptions[name] += " With an agent_current/agent_delegate session, step recognition, desktop_click, input_sequence and form_fill require top-level vision_capabilities (same fields as grounding capabilities). They return agent_command.v1 rather than blocking for vision. Poll agent_command_status request={command_id} using a NEW outer request_id. At awaiting_grounding read the returned original image and pending_grounding.output_schema; submit grounding_resolve for pending_grounding.request_id, then agent_command_continue request={command_id,grounding_request_id} with another new outer request_id. Never resubmit the original batch or use grounding_execute for a suspended batch. It resumes the original worker and may request further grounding. agent_command_cancel request={command_id} requests cooperative cancellation; wait for terminal status, since input may already have occurred. Active jobs reject competing input or target changes. Read_text on Agent sources returns agent_read_required plus original PNG, text=null, with no local OCR; the agent must read it. Agent routes do not automatically invoke another model or assume image capability."
        descriptions[name] += " Experimental grounding handoff: grounding_prepare request={goal,configuration:{source:'agent_current'|'agent_delegate',delegate_profile?:name},capabilities:{image_transport:'supported'|'unsupported'|'unknown',current_vision?:state,delegation?:state,model_selection?:state,delegate_vision?:state}} captures selected window and returns awaiting_grounding plus immutable image. grounding_resolve request={grounding_request_id:original_prepare_id,result:grounding.v1_object}; grounding_status/grounding_cancel request={grounding_request_id}. These four commands never click. Explicit grounding_execute request={grounding_request_id} dispatches one click through the existing action route only when the candidate is ready and live identity, viewport and target-region consistency checks pass. It does not load a local vision model or prove semantic hit. Execution is claimed durably before input and cannot be replayed: poll the original execution request ID and inspect its before/after images. Never turn coordinates into unchecked input."
        descriptions[name] += " form_fill accepts request={fields:[...],text_navigation:'recognize_each'|'tab_sequence'|'tab_groups'}, 1..32 declared fields: text {kind,field_goal,text,clear_existing,label?,tab_group?}, date {kind,field_goal,value,format}, dropdown {kind,label,option}, checkbox {kind,label,checked}, radio {kind,label}. Prefer one grouped call for all currently known fields, not one tool call per field; missing facts need not block independent known fields. Optional tab_sequence requires ONLY consecutive text fields with distinct exact accessible labels. tab_groups accepts mixed fields: assign identical tab_group strings only to adjacent text fields whose actual Tab order is known; labels must be exact and distinct within each run. New group, non-text or omitted tab_group always starts fresh recognition; tab_group is invalid outside tab_groups mode. Recognize each group head, then Tab, verify focused field label/identity, fill and read back locally; return one batch receipt and final image. Wrong focus interrupts BEFORE typing; never guesses/skips fields or auto-replays. Default recognize_each preserves mixed control handling. Compact fields include aggregate timings; full diagnostics remain available by ID. Date value must be a real ISO YYYY-MM-DD date; format is explicitly YYYY-MM-DD, DD/MM/YYYY or MM/DD/YYYY. Date fills an editable text field and checks exact displayed text; it does NOT navigate calendars, guess locale or verify server acceptance. Exact current accessible labels are required for choices; read current screenshots first. It never submits a form; already-satisfied choices are not toggled. Unknown/ambiguous/unreadable states interrupt with partial receipts. Dropdown options must belong to the opened control. Inspect original images; completion is not task success."
    for name in ("instant_submit", "instant_run", "instant_status", "instant_result"):
        descriptions[name] += " At a supported task-plan review wait, task_plan_run.caller_controls.review.request (or result.caller_controls in a control receipt) contains the exact current bindings. Inspect the evidence, copy that request and add only verdict='success'|'failure' and your reason; never add wait_id to review or use the latest observation SHA as evidence_sha256. The original after SHA remains required. After a successful bound review, caller_controls.continue.request contains the original wait_id for a separate explicit continue. These are unsigned parameter projections, not approval or input authorization; blocked, unresolved and failed states have no review/continue recipe."
    descriptions["instant_result"] += " Optional detail=compact omits verbose traces; full (default) keeps the old receipt fields. images=after|both includes original PNGs in this same call; default none preserves JSON-only delivery. A review_packet.v4 video-playback wait delivers its complete ordered observation sequence, labeled by capture_id and elapsed_ms, without recapturing or replacing the original after."
    for name in ("instant_submit", "instant_run"):
        descriptions[name] += " Explicit task_plan.v2 video verification uses verification={kind:'video_playback',decision_condition:exact_playback_condition,review_policy?:'always_main',render_grace_ms?:500}. After settled input and render grace, it waits at least1s then captures exactly3 fresh images at least500ms apart and sends all3 once to Decision within a shared8s budget. A visible change in the target video picture confirms playback; controls, OCR and separate player localization are not required. Generic verification={kind:'dynamic_content',target_description:explicit_content_target,decision_condition:exact_change_condition} reuses this path to judge change in the named content only, not overall task completion. No API or always_main delivers the3 images to the existing Main via review_packet.v4; uncertainty never repeats input. No wait_policy, hover or repeated assessment. Source-level limited live evidence is documented; general accuracy and installed acceptance are not established."
    for name in ("instant_submit", "instant_run"):
        descriptions[name] += " Optional step.decision_check={phase:'after_action'|'before_action',condition:explicit_observable_condition} uses the host's configured Decision service. Absent/off remains inactive; configured default shadow only records advice. Automatic adoption requires auto mode and an exact allowlisted condition. After-action checks reuse original evidence and preserve input status; uncertainty never retries input. Before-action is supported only by step/execute_recognition_plan at the fresh candidate boundary, never by input_sequence/form_fill/grounding_execute. API judgment cannot authorize input. Poll the original execution result; asynchronous status uses its command_id. Learning agent_judgment verification may include a reviewed decision_condition alongside image_check; local image success remains zero API in adaptive mode, dynamic output extraction still requires the existing reader/Agent. Explicit decision_profile.v2 separates verdict from disposition: a successful outcome with review_required still needs the existing Main Agent and cannot advance input. proactive_review adds an independent needs_agent_review question; always_main skips the paid pre-check and preserves review. In v2 auto mode an unallowlisted explicit pre-action condition also stops for Main; it cannot silently bypass the check. Always use the active host's reported contract; v1 snapshots retain their semantics."
    for name in ("instant_submit", "instant_run"):
        descriptions[name] += " Optional command.observation_condition={text:exact_accessible_name,control_type:Text|Hyperlink|Button|Document} enables read-only early observation for step or submit_search sequences. Requires a positive observation_wait_ms budget (navigation defaults to 2000). Only a newly appearing unique visible match, repeated and rechecked after capture, ends early. Accessible names can differ from screenshot captions. Missing/ambiguous/old matches time out and still return an image; inspect observation.condition, not operation_succeeded, for this outcome. This is not full-page readiness or task verification. Synchronous UIA and capture I/O are outside a hard timeout; no input replay. Omit the condition when no reliable marker is known."
    for fn in (instant_start, instant_status, instant_submit, instant_result, instant_image, instant_stop, instant_run,
               instant_recovery_preview, instant_recover_session):
        server.add_tool(fn, name=fn.__name__, description=descriptions[fn.__name__])
    return server
