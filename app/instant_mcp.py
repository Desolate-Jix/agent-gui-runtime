"""即时模式的本地 STDIO 适配；动作仍交给原串行会话执行。"""

import base64
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

INSTANT_VERSION = "0.1.0-test.4"


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
    """仅表示创建宿主之前的配置错误，不判断既有会话的执行结果。"""

    def __init__(self, code, message, next_step):
        super().__init__(message)
        self.code = code
        self.next = next_step


class InstantCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    kind: Literal["discover", "launch", "select", "maximize", "capture", "read_text", "prepare_models", "release_models", "step", "close_launched_window"]
    app_id: str | None = None
    url: str | None = None
    handle: int | None = Field(default=None, gt=0)
    process_id: int | None = Field(default=None, gt=0)
    operation: Literal["execute_recognition_plan", "type_text", "scroll", "press_key"] | None = None
    request: dict | None = None
    observation_wait_ms: int | None = Field(default=None, ge=0, le=2000)
    max_chars: int | None = Field(default=None, ge=1, le=20000)

    def command(self):
        value = self.model_dump(exclude_none=True)
        fields = {
            "launch": ({"app_id"}, {"app_id", "url"}),
            "select": ({"handle", "process_id"}, {"handle", "process_id"}),
            "close_launched_window": ({"handle", "process_id"}, {"handle", "process_id"}),
            "step": ({"operation", "request"}, {"operation", "request", "observation_wait_ms"}),
            "read_text": (set(), {"max_chars"}),
        }
        required, allowed = fields.get(self.kind, (set(), set()))
        present = set(value) - {"kind"}
        if not required <= present or present - allowed:
            raise ValueError("command fields do not match kind")
        if self.kind == "step":
            from app.desktop_review.local_action_contract import _validated_request
            # 只验证，运行时再次验证；不在桥接层重写执行请求。
            _validated_request(self.operation, self.request)
        return value


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path, value):
    path = Path(path)
    temp = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


class InstantSession:
    def __init__(self, root, data_root, model_directory, *, allow_local_input=False):
        self.root = Path(root).resolve()
        self.data_root = Path(data_root).resolve()
        self.model_directory = Path(model_directory).resolve()
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
            if not self.model_directory.is_dir():
                raise InstantStartError("model_directory_unavailable", "configured model directory does not exist",
                    "Check --model-directory is an existing directory; use forward slashes or escaped backslashes in configuration, then reconnect.")
            self._lock()
            pointer = self.data_root / "latest-session.json"
            if self.session is None and pointer.is_file():
                saved = read_json(pointer)
                previous = (self.data_root / saved["name"]).resolve()
                if previous.parent != self.data_root or not re.fullmatch(r"session-[0-9a-f]{32}", previous.name):
                    raise ValueError("invalid persisted session pointer")
                self.session = previous
                self.host_identity = saved.get("host_identity")
            if self.session is not None:
                status = self.status()
                if not new_session:
                    return status
                if not status["cleanup_verified"] or status["pending_ids"]:
                    raise ValueError("previous session needs verified cleanup and resolved receipts before a new session")
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
            self.process = subprocess.Popen([sys.executable, str(self.root / "scripts/run_local_step_session.py"),
                "--output", str(self.session), "--model-directory", str(self.model_directory),
                "--local-no-learning", "--parent-pid", str(os.getpid())], cwd=self.root,
                stdin=subprocess.DEVNULL, stdout=self.log_file, stderr=self.log_file,
                env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.host_identity = {"pid": self.process.pid, "created": psutil.Process(self.process.pid).create_time()}
            write_json(pointer, {"name": self.session.name, "host_identity": self.host_identity})
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
                "learning_enabled": False, "automatic_safety_interception": False if alive else None,
                "local_input_enabled_by_operator": self.allow_local_input,
                "host_is_admin": report.get("host_is_admin"),
                "session_directory": str(self.session) if self.session else None,
                "target": report.get("target"), "pending_ids": pending,
                "cleanup_verified": bool(report.get("finished_at") and report.get("phase") == "stopped"
                    and report.get("host_phase") == "stopped" and report.get("cleanup_errors") == []
                    and report.get("sampler_stopped") is True and not alive),
                "cleanup_errors": report.get("cleanup_errors"), "error_type": report.get("error_type"),
                "automatic_retry_allowed": False}

    def _path(self, request_id, folder):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", request_id):
            raise ValueError("request_id must be 1-80 lowercase ASCII letters/digits/dashes/underscores")
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
                return {"request_id": request_id, "status": "pending" if self.status()["host_alive"] else "result_unknown",
                        "automatic_retry_allowed": False}
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
            if result.get("contract_version") == "local_direct_step_v1":
                receipt["operation_succeeded"] = ok and api.get("success") is True
                before = result.get("capture") or {}
                after = (result.get("observation") or {}).get("capture") or {}
                receipt.update(operation_success_scope="input_route_only",
                               input_route_succeeded=api.get("success") if type(api.get("success")) is bool else None,
                               observation_status=(result.get("observation") or {}).get("status", "not_requested"))
                receipt["agent_review"] = {
                    "status": "awaiting_agent_review" if before and after else "evidence_incomplete",
                    "verified": None, "judged_by": "agent",
                    "before": {"tool": "instant_image", "arguments": {"request_id": request_id, "view": "before"},
                               "frame_id": "before_input", "image_path": before.get("image_path"),
                               "available": bool(before), "sha256": before.get("sha256")},
                    "after": {"tool": "instant_image", "arguments": {"request_id": request_id, "view": "after"},
                              "frame_id": "after_settled", "image_path": after.get("image_path"),
                              "observation_stage": "after_render_wait", "render_completion_verified": False,
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
            capture = (response.get("result") or {}).get("capture") or {}
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
        try:
            validated = command.command()
        except ValueError as error:
            # 只捕获入队前校验，日志不写输入值，执行异常不能伪装成未执行。
            detail = {"code": "invalid_command", "message": str(error)}
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
            return CallToolResult(isError=True, content=[TextContent(type="text", text=json.dumps(value, ensure_ascii=False))])
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

    def instant_result(request_id: str) -> dict:
        return session.result(request_id)

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
        "instant_start": "Start isolated host or reattach last session after reconnect, without launching apps/input. Poll status. new_session=true starts a fresh session ONLY after previous cleanup is verified and receipts resolved; request IDs are session-scoped. Requires operator --allow-local-input option. Known preflight configuration failures return isError=true, status=start_rejected, error.code and next guidance; host_launch_attempted=false refers only to this call, not existing sessions.",
        "instant_status": "Read host, target, pending IDs and cleanup status; no screenshot or input.",
        "instant_submit": "Submit exactly one command with a unique durable ID. discover lists apps/windows; launch uses app_id/url; select focuses handle/process_id; maximize/capture use selected target; read_text={max_chars:10000} captures the selected window NOW and returns OCR text/line boxes plus exact image evidence (1..20000 chars). Read-only, no VISTA or learning; only captured visible pixels, NOT full page/DOM or guaranteed exact text. Overlays/browser chrome may be included; inspect instant_image for the same request ID; close_launched_window={handle,process_id} explicitly requests graceful close ONLY for a new window launched in this session. window_close_pending is not closed: inspect before disconnecting, never force or auto-confirm unsaved prompts. prepare_models/release_models manage residency. step operations: execute_recognition_plan request={goal,click_kind:'single'|'double'|'right'} (default single; fresh non-learning input only); type_text={text,x,y,click_before_typing:true,clear_existing:false} (explicit click_before_typing:false keeps CURRENT FOCUS/selection; coordinates do not set focus in that mode; clear_existing:true replaces the whole field; never implicitly submits); press_key={key,x,y}, supported keys: Enter, Tab, Shift+Tab, Escape, Backspace, Delete, Left, Right, Up, Down, Home, End, Ctrl+A, Ctrl+Z, Ctrl+Y, Shift+Left, Shift+Right, Shift+Up, Shift+Down, Shift+Home, Shift+End, Ctrl+Home, Ctrl+End. Keys go to CURRENT FOCUS; x/y is an observed window point, not a click or focus instruction. scroll={direction:'down'|'up',wheel_clicks:3,x,y}. Coordinates are current original window screenshot pixels, NOT desktop or resized image coordinates. No arbitrary hotkeys, learning, or shell commands. Submission is NOT completion. Poll same ID; inspect image before next input. Avoid payment/send/delete/final submission.",
        "instant_result": "Read original response without executing again. pending means wait; result_unknown means inspect, never retry blindly. For local steps operation_success_scope=input_route_only; check observation_status and agent_review.recovery separately. operation_succeeded is not proof of task outcome.",
        "instant_image": "Return exact original PNG from a recorded response, without new capture or input. view=before returns the pre-input frame; view=after (default) returns the post-input observation. Missing/pending/corrupt evidence returns isError=true with status=image_unavailable, error.code and next guidance; it says nothing about whether the original input happened. Do not replay automatically. Compare both frames against the goal and report success/failure/uncertain yourself. Pixel change or no change alone does not prove task outcome.",
        "instant_stop": "Request graceful stop after current command. Does not undo or interrupt inflight input. Poll status until cleanup_verified=true. Does not close user apps itself; a Windows MCP client may terminate its launched descendants on disconnect. Explicitly close test-created windows first using close_launched_window and verify window_closed.",
    }
    for fn in (instant_start, instant_status, instant_submit, instant_result, instant_image, instant_stop):
        server.add_tool(fn, name=fn.__name__, description=descriptions[fn.__name__])
    return server
