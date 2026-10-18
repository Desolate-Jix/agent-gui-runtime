"""附着已选 Instant 宿主的薄客户端，不拥有宿主进程。"""
from __future__ import annotations

from copy import deepcopy
from contextlib import contextmanager
import os
from pathlib import Path
import re
import tempfile

import psutil

from app.core.instant_attachment_transport import InstantAdmissionError, InstantAttachmentTransport, read_json, _validate_request_id
from app.desktop_review.external_mapping import canonical_json_bytes
from app.desktop_review.workspace import _atomic_write_bytes
from .workflow_control import validate_request
from .execution_installation import load_execution_installation


_SESSION = re.compile(r"session-[0-9a-f]{32}\Z")
_ACTIONS = frozenset({"start", "run", "continue", "status", "cancel", "verify", "takeover_preview", "takeover_commit"})
_STATUS_FIELDS = ("host_alive", "phase", "recognition_source", "session_directory", "target",
                  "pending_ids", "workflow_run", "workflow_runtime_error")
_MARKER_SCHEMA = "workflow_editor_request.v1"
_RUN = re.compile(r"trial-[0-9a-f]{64}\Z")


class WorkflowRunClient:
    def __init__(self, session_dir, library_root, transport=None, *, execution_root=None):
        self.session_dir = Path(session_dir).resolve()
        self.library_root = Path(library_root).resolve()
        self._transport = transport
        self._instant = None
        self._attachment = None
        self._runner_identity = None
        self._recovery_ids = None
        self._connected = False
        self._closed = False
        self._source_root = Path(__file__).resolve().parents[2]
        self._execution_root = Path(execution_root).resolve() if execution_root is not None else self._source_root
        self._explicit_execution_root = execution_root is not None
        self._installation = None

    def _verify_installation(self):
        installation = load_execution_installation(self._execution_root,
            source_root=None if self._explicit_execution_root else self._source_root)
        if self._installation is not None and installation != self._installation:
            raise ValueError("execution_installation_changed")
        self._installation = installation
        return installation

    def _verify_attachment(self):
        session = self.session_dir
        parent = session.parent
        if not _SESSION.fullmatch(session.name) or not session.is_dir():
            raise ValueError("workflow_run_session_invalid")
        if self.library_root != (parent / "memory-library").resolve() or not self.library_root.is_dir():
            raise ValueError("workflow_run_library_mismatch")
        pointer_path, report_path = parent / "latest-session.json", session / "report.json"
        try:
            pointer = read_json(pointer_path)
            report = read_json(report_path)
        except (OSError, ValueError, TypeError) as error:
            raise ValueError("workflow_run_host_evidence_invalid") from error
        if not isinstance(pointer, dict) or pointer.get("name") != session.name:
            raise ValueError("workflow_run_session_pointer_mismatch")
        identity = pointer.get("host_identity")
        if (not isinstance(identity, dict) or set(identity) != {"pid", "created"}
                or type(identity["pid"]) is not int or identity["pid"] <= 0
                or type(identity["created"]) not in (int, float) or identity["created"] <= 0):
            raise ValueError("workflow_run_host_identity_invalid")
        if (not isinstance(report, dict)
                or not isinstance(report.get("phase"), str)
                or report.get("phase") not in {"starting", "ready", "stopped", "failed", "cleanup_pending"}
                or type(report.get("runner_pid")) is not int or report["runner_pid"] <= 0
                or report.get("finished_at") is not None and not isinstance(report["finished_at"], str)
                or any(report.get(key) is not None and not isinstance(report[key], dict)
                       for key in ("workflow_run", "workflow_runtime_error", "target"))):
            raise ValueError("workflow_run_host_evidence_invalid")
        from app.vision.recognition_source import RecognitionSourceConfig
        from pydantic import ValidationError
        try:
            RecognitionSourceConfig.model_validate({"source": pointer.get("recognition_source"),
                "delegate_profile": pointer.get("delegate_profile"), "api_profile": pointer.get("api_profile")})
        except ValidationError as error:
            raise ValueError("workflow_run_recognition_source_invalid") from error
        return pointer, identity, report

    def _verify_live(self):
        self._verify_installation()
        pointer, identity, report = self._verify_attachment()
        if report.get("phase") != "ready" or report.get("finished_at"):
            raise ValueError("workflow_run_host_not_ready")
        try:
            process = psutil.Process(identity["pid"])
            alive = process.is_running() and process.status() != psutil.STATUS_ZOMBIE
            created = process.create_time()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as error:
            raise ValueError("workflow_run_host_identity_stale") from error
        if not alive or created != identity["created"]:
            raise ValueError("workflow_run_host_identity_stale")
        runner_identity = self._verify_runner(report["runner_pid"], identity, self.session_dir)
        self._runner_identity = runner_identity
        return pointer, identity

    def _verify_runner(self, runner_pid, owner, session):
        if type(runner_pid) is not int or runner_pid <= 0:
            raise ValueError("workflow_run_runner_identity_invalid")
        try:
            runner = psutil.Process(runner_pid)
            identity = (runner.pid, runner.create_time())
            if not runner.is_running() or runner.status() == psutil.STATUS_ZOMBIE:
                raise ValueError("workflow_run_runner_identity_invalid")
            if runner.pid != owner["pid"] or self._installation.mode == "installed":
                # Windows 虚拟环境启动器与实际宿主 PID 不同，须核对直接父进程及确切入口/会话。
                command = runner.cmdline()
                entry = self._installation.runner_entry
                outputs = [command[index + 1] for index, value in enumerate(command[:-1]) if value == "--output"]
                entries = [value for value in command[1:] if Path(value).resolve() == entry]
                installed_entry_invalid = (self._installation.mode == "installed"
                    and (len(command) < 2 or Path(command[1]).resolve() != entry))
                if ((runner.pid != owner["pid"] and runner.ppid() != owner["pid"]) or identity[1] < owner["created"]
                        or len(entries) != 1 or installed_entry_invalid or command.count("--output") != 1
                        or len(outputs) != 1 or Path(outputs[0]).resolve() != session):
                    raise ValueError("workflow_run_runner_identity_invalid")
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as error:
            raise ValueError("workflow_run_runner_identity_invalid") from error
        if self._runner_identity is not None and identity != self._runner_identity:
            raise ValueError("workflow_run_runner_identity_changed")
        return identity

    def connect(self) -> dict:
        if self._closed:
            raise RuntimeError("workflow_run_client_closed")
        installation = self._verify_installation()
        pointer, identity, _report = self._verify_attachment()
        attachment = {key: deepcopy(pointer.get(key)) for key in
                      ("name", "host_identity", "recognition_source", "delegate_profile", "api_profile")}
        if self._attachment is not None and self._attachment != attachment:
            raise ValueError("workflow_run_attachment_changed")
        if self._instant is None:
            self._instant = InstantAttachmentTransport(installation.root, self.session_dir.parent,
                recognition_source=pointer["recognition_source"],
                delegate_profile=pointer.get("delegate_profile"), api_profile=pointer.get("api_profile"))
        self._instant.session = self.session_dir
        self._instant.host_identity = deepcopy(identity)
        self._instant.recognition_source = pointer["recognition_source"]
        self._instant.delegate_profile = pointer.get("delegate_profile")
        self._instant.api_profile = pointer.get("api_profile")
        status = self._instant.status()
        # 旧会话可只读附着；仍存活的宿主必须通过完整身份和运行器核验。
        if status["host_alive"]:
            self._verify_live()
        self._connected = True
        self._attachment = attachment
        if not status["host_alive"]:
            status["workflow_run"] = self._saved_recovery_run(status.get("workflow_run"))
        takeover_sources = []
        if status["host_alive"]:
            from .workflow_takeover_sources import read_takeover_sources
            takeover_sources = read_takeover_sources(self.session_dir, self.library_root)
        return {**{key: deepcopy(status[key]) for key in _STATUS_FIELDS},
                "takeover_sources": deepcopy(takeover_sources),
                "recoverable_controls": self._recoverable_controls()}

    @contextmanager
    def _recovery_service(self):
        if self._closed:
            raise RuntimeError("workflow_run_client_closed")
        if not self._connected:
            self.connect()
        pointer, identity, report = self._verify_attachment()
        attachment = {key: deepcopy(pointer.get(key)) for key in
                      ("name", "host_identity", "recognition_source", "delegate_profile", "api_profile")}
        if attachment != self._attachment:
            raise ValueError("workflow_run_attachment_changed")
        from .workflow_terminal_recovery import WorkflowTerminalRecovery
        from .workflow_trial import TrialService
        from .workspace import MemoryWorkspace
        # 固定项目读取也需要完整记忆库依赖，复用同一短事务及跨进程锁。
        with MemoryWorkspace(self.library_root) as library:
            yield WorkflowTerminalRecovery(TrialService(library, self.session_dir),
                host_identity=identity, runner_pid=report["runner_pid"])

    def _saved_recovery_run(self, reported):
        path = self.session_dir / "workflow-runners" / "active.json"
        if not path.is_file():
            return reported
        active = read_json(path)
        if not isinstance(active, dict) or active.get("schema") != "workflow_runner.v1":
            raise ValueError("workflow_runner_active_invalid")
        run_id = active.get("run_id")
        with self._recovery_service() as recovery:
            state = recovery.status(run_id)
        if state is None:
            return reported
        runner = read_json(self.session_dir / "workflow-runners" / (run_id + ".json"))
        saved = reported if isinstance(reported, dict) and reported.get("run_id") == run_id else {}
        return {**saved, **state, "runner_state": "waiting", "wait_reason": "recovery_paused",
                "wait": deepcopy(runner.get("wait")), "mode": runner["mode"],
                "active_command_id": state["pending"]["execution_request_id"]}

    def preview_recovery(self, run_id):
        with self._recovery_service() as recovery:
            return recovery.preview(run_id)

    def settle_recovery(self, preview, *, request_id):
        # 专用短事务只写原账本；不复用 control 或队列提交入口。
        with self._recovery_service() as recovery:
            recovery.settle(deepcopy(preview), request_id)
        return self.connect()

    def _marker_path(self, request_id):
        return self.session_dir / "workflow-editor-requests" / (request_id + ".json")

    def _read_marker(self, request_id):
        path = self._marker_path(request_id)
        if not path.is_file():
            return None
        marker = read_json(path)
        if (not isinstance(marker, dict) or marker.get("schema") != _MARKER_SCHEMA
                or marker.get("request_id") != request_id or marker.get("attachment") != self._attachment
                or marker.get("submission") not in {"attempt", "not_submitted"}
                or not isinstance(marker.get("request"), dict)):
            raise ValueError("workflow_run_marker_invalid")
        return marker

    def _record_attempt(self, request_id, request):
        path = self._marker_path(request_id)
        existing = self._read_marker(request_id)
        if existing is not None:
            if existing["request"] != request:
                raise ValueError("workflow_run_request_id_conflict")
            return False
        marker = {"schema": _MARKER_SCHEMA, "request_id": request_id,
                  "request": deepcopy(request), "attachment": deepcopy(self._attachment),
                  "submission": "attempt"}
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".workflow-editor-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(canonical_json_bytes(marker) + b"\n")
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                existing = self._read_marker(request_id)
                if existing is None or existing["request"] != request:
                    raise ValueError("workflow_run_request_id_conflict")
                return False
        finally:
            os.unlink(temporary)
        return True

    def _record_not_submitted(self, request_id, receipt):
        marker = self._read_marker(request_id)
        if marker is None:
            raise ValueError("workflow_run_marker_missing")
        marker.update(submission="not_submitted", receipt=deepcopy(receipt))
        _atomic_write_bytes(self._marker_path(request_id), canonical_json_bytes(marker) + b"\n")

    def _original_receipt(self, request_id, marker):
        command_path = self.session_dir / "commands" / (request_id + ".json")
        if command_path.is_file():
            expected = {"kind": "learning_workflow", "request": marker["request"]}
            if read_json(command_path) != expected:
                raise ValueError("workflow_run_marker_command_mismatch")
            response_path = self.session_dir / "responses" / (request_id + ".json")
            if response_path.is_file():
                original = read_json(response_path)
                if not isinstance(original, dict) or original.get("command") != expected:
                    raise ValueError("workflow_run_original_receipt_mismatch")
            receipt = (self._transport or self._instant).result(request_id)
            run_id = marker["request"].get("run_id")
            if run_id is not None and receipt.get("status") == "returned":
                result = receipt.get("result")
                if not isinstance(result, dict) or result.get("run_id") != run_id:
                    raise ValueError("workflow_run_result_identity_mismatch")
            if marker["request"].get("action") == "start":
                self._start_ready_without_runner(receipt, marker["request"])
            return receipt
        if marker["submission"] == "not_submitted":
            receipt = marker.get("receipt")
            if (not isinstance(receipt, dict) or receipt.get("request_id") != request_id
                    or receipt.get("status") != "not_submitted"):
                raise ValueError("workflow_run_marker_invalid")
            return deepcopy(receipt)
        return {"request_id": request_id, "status": "not_found"}

    def _start_ready_without_runner(self, receipt, request):
        result = receipt.get("result")
        run_id = result.get("run_id") if isinstance(result, dict) else None
        if (receipt.get("status") != "returned" or not isinstance(result, dict)
                or result.get("status") != "ready" or not isinstance(run_id, str)
                or _RUN.fullmatch(run_id) is None):
            return False
        trial_path = self.session_dir / "workflow-trials" / (run_id + ".json")
        trial = read_json(trial_path)
        if trial.get("run_id") != run_id:
            raise ValueError("workflow_run_trial_identity_mismatch")
        for key in ("workflow_id", "program_id", "start_step_id", "inputs"):
            if trial.get(key) != request.get(key) or result.get(key) != request.get(key):
                raise ValueError("workflow_run_trial_binding_mismatch")
        if trial.get("status") != "ready" or trial.get("pending") is not None:
            return False
        runner_path = self.session_dir / "workflow-runners" / (run_id + ".json")
        if not runner_path.is_file():
            return True
        runner = read_json(runner_path)
        if runner.get("schema") != "workflow_runner.v1" or runner.get("run_id") != run_id:
            raise ValueError("workflow_run_runner_identity_mismatch")
        return False

    def _recoverable_controls(self):
        directory = self.session_dir / "workflow-editor-requests"
        if self._recovery_ids is None:
            self._recovery_ids = {path.stem for path in directory.glob("*.json")} if directory.is_dir() else set()
        # 提交标记绑定原预览；不能把同一事务的两条控制误当两个未决事务。
        commits = {}
        for path in directory.glob("*.json"):
            _validate_request_id(path.stem)
            marker = self._read_marker(path.stem)
            if marker is not None and marker["request"].get("action") == "takeover_commit":
                request = validate_request(marker["request"])
                commits.setdefault(request["preview_request_id"], set()).add(path.stem)
        active, rows = set(), []
        for request_id in sorted(self._recovery_ids):
            _validate_request_id(request_id)
            marker = self._read_marker(request_id)
            if marker is None:
                raise ValueError("workflow_run_marker_missing")
            action = marker["request"].get("action")
            if action == "takeover_preview" and request_id in commits:
                continue
            receipt = self._original_receipt(request_id, marker)
            if action == "takeover_commit":
                result = receipt.get("result")
                request = validate_request(marker["request"])
                preview_id = request["preview_request_id"]
                original = self._read_marker(preview_id)
                if original is None or original["request"].get("action") != "takeover_preview":
                    raise ValueError("workflow_run_takeover_preview_missing")
                validate_request(original["request"])
                preview_receipt = self._original_receipt(preview_id, original)
                preview = preview_receipt.get("result")
                if (preview_receipt.get("status") != "returned" or not isinstance(preview, dict)
                        or preview.get("status") != "preview_ready"
                        or preview.get("preview_request_id") != preview_id
                        or preview.get("preview_sha256") != request["preview_sha256"]):
                    raise ValueError("workflow_run_takeover_preview_not_ready")
                # 仅原预览绑定的真实接管等待或完成快照可交回报告恢复。
                if (receipt.get("status") == "returned" and isinstance(result, dict)
                        and receipt.get("operation_succeeded") is not False
                        and isinstance(result.get("run_id"), str) and _RUN.fullmatch(result["run_id"])
                        and result["run_id"] == preview.get("new_run_id")
                        and result.get("current_step_id") == preview.get("next_step_id")):
                    next_step = preview.get("next_step_id")
                    wait = result.get("wait")
                    waiting = (isinstance(next_step, str) and bool(next_step)
                               and result.get("runner_state") == "waiting"
                               and result.get("wait_reason") == "takeover_ready"
                               and isinstance(wait, dict) and wait.get("reason") == "takeover_ready"
                               and isinstance(wait.get("wait_id"), str)
                               and re.fullmatch(r"workflow-wait-[0-9a-f]{32}", wait["wait_id"]) is not None)
                    completed = (next_step is None and result.get("runner_state") == "completed"
                                 and result.get("status") == "completed")
                    if waiting or completed:
                        continue
                rows.append({"request_id": request_id, "action": action,
                    "request": deepcopy(request), "receipt": deepcopy(receipt), "takeover_preview": deepcopy(preview)})
                active.add(request_id)
                continue
            # 失败或未入队的预览仍须交回原请求，不能在重开时丢失事务身份。
            if action == "takeover_preview":
                result = receipt.get("result")
                if (isinstance(result, dict) and result.get("status") == "preview_ready"
                        and result.get("preview_request_id") != request_id):
                    raise ValueError("workflow_run_takeover_preview_identity_mismatch")
                rows.append({"request_id": request_id, "action": action,
                             "request": deepcopy(marker["request"]), "receipt": deepcopy(receipt)})
                active.add(request_id)
                continue
            if marker["submission"] == "not_submitted" and receipt["status"] == "not_submitted":
                continue
            result = receipt.get("result")
            preview_ready = (action == "takeover_preview" and receipt.get("status") == "returned"
                             and isinstance(result, dict) and result.get("status") == "preview_ready")
            if preview_ready and result.get("preview_request_id") != request_id:
                raise ValueError("workflow_run_takeover_preview_identity_mismatch")
            if preview_ready or receipt.get("status") in {"pending", "result_unknown", "not_found"} or (
                    action == "start" and self._start_ready_without_runner(receipt, marker["request"])):
                rows.append({"request_id": request_id, "action": action,
                             "request": deepcopy(marker["request"]), "receipt": deepcopy(receipt)})
                active.add(request_id)
        self._recovery_ids = active
        return rows

    def control(self, request: dict, request_id: str) -> dict:
        if self._closed:
            raise RuntimeError("workflow_run_client_closed")
        if not self._connected:
            raise RuntimeError("workflow_run_client_not_connected")
        pointer, _identity = self._verify_live()
        if self._attachment != {key: pointer.get(key) for key in
                                ("name", "host_identity", "recognition_source", "delegate_profile", "api_profile")}:
            raise ValueError("workflow_run_attachment_changed")
        _validate_request_id(request_id)
        validated = validate_request(request)
        if validated["action"] not in _ACTIONS:
            raise ValueError("workflow_run_action_unsupported")
        command = {"kind": "learning_workflow", "request": deepcopy(validated)}
        command_path = self.session_dir / "commands" / (request_id + ".json")
        marker = self._read_marker(request_id)
        if marker is not None:
            if marker["request"] != validated:
                raise ValueError("workflow_run_request_id_conflict")
            return self._original_receipt(request_id, marker)
        if command_path.is_file():
            if read_json(command_path) != command:
                raise ValueError("request_id already belongs to a different command")
            return self.result(request_id)
        if not self._record_attempt(request_id, validated):
            return self._original_receipt(request_id, self._read_marker(request_id))
        if self._recovery_ids is not None:
            self._recovery_ids.add(request_id)
        try:
            return (self._transport or self._instant).submit(request_id, command)
        except InstantAdmissionError as error:
            if error.code not in {"host_not_ready", "command_pending", "command_queue_busy", "session_closing"}:
                raise
            # 原 admission 异常保证本次未入队；并发同 ID 写入仍须回读真实命令。
            if command_path.is_file():
                if read_json(command_path) != command:
                    raise ValueError("request_id already belongs to a different command")
                return self.result(request_id)
            pending_id = error.next.get("arguments", {}).get("request_id")
            receipt = {"request_id": request_id, "status": "not_submitted", "reason": error.code,
                       "pending_ids": [pending_id] if isinstance(pending_id, str) else [],
                       "automatic_retry_allowed": False}
            self._record_not_submitted(request_id, receipt)
            if self._recovery_ids is not None:
                self._recovery_ids.discard(request_id)
            return receipt

    def result(self, request_id: str) -> dict:
        if self._closed:
            raise RuntimeError("workflow_run_client_closed")
        if not self._connected:
            raise RuntimeError("workflow_run_client_not_connected")
        _validate_request_id(request_id)
        marker = self._read_marker(request_id)
        return (self._original_receipt(request_id, marker) if marker is not None
                else (self._transport or self._instant).result(request_id))

    def close(self) -> None:
        self._closed = True


__all__ = ["WorkflowRunClient"]
