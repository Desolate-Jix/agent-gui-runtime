from pathlib import Path
from threading import RLock
from uuid import uuid4
import hashlib
import json
import re

from .json_snapshot import read_json_snapshot as read_json

class InstantAdmissionError(ValueError):
    """仅用于尚未写入命令队列的可预期状态拒绝。"""

    def __init__(self, code, message, next_tool, next_arguments=None):
        super().__init__(message)
        self.code = code
        self.next = {"tool": next_tool, "arguments": next_arguments or {}}


def _validate_request_id(request_id):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", request_id):
        raise ValueError("request_id must be 1-80 lowercase ASCII letters/digits/dashes/underscores")


class InstantAttachmentTransport:
    def __init__(self, root, data_root, *, recognition_source="local", delegate_profile=None, api_profile=None):
        self.root = Path(root).resolve()
        self.data_root = Path(data_root).resolve()
        self.recognition_source = recognition_source
        self.delegate_profile = delegate_profile
        self.api_profile = api_profile
        self.guard = RLock()
        self.process = None
        self.session = None
        self.host_identity = None
        self.allow_local_input = False

    def submit(self, request_id, command):
        with self.guard:
            path = self._path(request_id, "commands")
            if path.exists():
                if read_json(path) != command:
                    raise ValueError("request_id already belongs to a different command")
                return self.result(request_id)
            return self._live_submit(request_id, command, self.status())

    def _live_submit(self, request_id, command, status):
        if status["phase"] != "ready" or not status["host_alive"]:
            raise InstantAdmissionError("host_not_ready", "host is not ready; poll instant_status", "instant_status")
        if status["pending_ids"]:
            raise InstantAdmissionError("command_pending",
                "one command is still pending; query its original ID, do not queue input",
                "instant_result", {"request_id": status["pending_ids"][0]})
        if (self.session / "closing.json").exists():
            raise InstantAdmissionError("session_closing", "session is closing", "instant_status")
        from app.core.session_epoch_read_contract import SessionEpochReadContract
        try:
            pending_admission = SessionEpochReadContract(self).pending_request()
        except (ValueError, OSError) as error:
            raise InstantAdmissionError("recovery_admission_invalid", str(error), "instant_status") from error
        if pending_admission is not None:
            raise InstantAdmissionError("recovery_admission_not_ready",
                "Finish the original recovery admission before submitting commands",
                "instant_recover_session", pending_admission)
        from app.core.instant_command_queue import CommandQueueBusy, enqueue_command
        try:
            created = enqueue_command(self.session, request_id, command)
        except CommandQueueBusy as error:
            if error.pending_ids:
                raise InstantAdmissionError("command_pending",
                    "one command is still pending; query its original ID, do not queue input",
                    "instant_result", {"request_id": error.pending_ids[0]}) from error
            raise InstantAdmissionError("command_queue_busy", "command queue admission is busy; no command was submitted",
                "instant_status") from error
        if not created:
            return self.result(request_id)
        return {"request_id": request_id, "status": "pending", "automatic_retry_allowed": False,
                "next": "Poll instant_result with this exact request_id"}

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
            learning_state = report.get("learning_recording", {"status": "disabled", "recording_enabled": False})
            if self.session and (self.session / "learning-memory" / "current.json").is_file():
                try:
                    from app.learning_memory.event_store import LearningEventStore
                    learning_state = LearningEventStore(self.session).snapshot()
                except (OSError, ValueError, KeyError, TypeError) as error:
                    learning_state = {"status": "unavailable", "recording_enabled": None,
                                      "error_type": type(error).__name__}
            phase = report.get("phase", "starting" if alive else "not_started")
            if self.session is not None and not alive and not report.get("finished_at"):
                phase = "host_exited_without_cleanup_proof"
            pending = []
            if self.session:
                pending = [p.stem for p in (self.session / "commands").glob("*.json")
                           if not (self.session / "responses" / p.name).exists()]
            return {"mode": "instant-local-operator-preview", "phase": phase, "host_alive": alive,
                "recognition_source": self.recognition_source, "delegate_profile": self.delegate_profile,
                "api_profile": self.api_profile,
                "learning_enabled": learning_state.get("recording_enabled") if alive else False,
                "legacy_learning_executor_enabled": False,
                "learning_recording": learning_state,
                "learning_recording_error": report.get("learning_recording_error"),
                "workflow_run": report.get("workflow_run"),
                "workflow_runtime_error": report.get("workflow_runtime_error"),
                "automatic_safety_interception": False if alive else None,
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


    def _saved_agent_worker_evidence(self, request_id, command, result):
        command_id = result.get("command_id")
        if not isinstance(command_id, str):
            raise ValueError("instant_agent_worker_evidence_invalid")
        _validate_request_id(command_id)
        original = read_json(self._path(request_id, "commands"))
        if original != command or not isinstance(command, dict):
            raise ValueError("instant_agent_worker_evidence_invalid")
        if command.get("kind") in {"step", "input_sequence", "form_fill"}:
            matches = command_id == request_id
        else:
            matches = (command.get("kind") in {"agent_command_status", "agent_command_continue", "agent_command_cancel"}
                       and isinstance(command.get("request"), dict)
                       and (command.get("request") or {}).get("command_id") == command_id
                       and self._path(command_id, "commands").is_file())
        if not matches:
            raise ValueError("instant_agent_worker_evidence_invalid")
        try:
            job_command = read_json(self._path(command_id, "commands"))
            acceptance = read_json(self._path(command_id, "responses"))
        except (OSError, ValueError) as error:
            raise ValueError("instant_agent_worker_evidence_invalid") from error
        accepted = acceptance.get("result") if isinstance(acceptance, dict) else None
        if (not isinstance(job_command, dict) or job_command.get("kind") not in {"step", "input_sequence", "form_fill"}
                or not isinstance(acceptance, dict) or acceptance.get("command") != job_command
                or not isinstance(accepted, dict) or accepted.get("contract_version") != "agent_command.v1"
                or accepted.get("command_id") != command_id):
            raise ValueError("instant_agent_worker_evidence_invalid")
        path = self._path(command_id, "agent-commands")
        evidence = {"scope": "saved_worker_diagnostic_not_execution_receipt", "command_id": command_id,
                    "path": str(path), "sha256": None, "status": "unavailable", "action_executed": None}
        if not path.is_file():
            return evidence
        try:
            raw = path.read_bytes()
            state = json.loads(raw.decode("utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError("instant_agent_worker_evidence_invalid") from error
        if (not isinstance(state, dict) or state.get("contract_version") != "agent_command.v1"
                or state.get("command_id") != command_id
                or state.get("status") not in {"running", "awaiting_grounding", "completed", "failed", "cancelled"}
                or state.get("action_executed") is not None and type(state["action_executed"]) is not bool):
            raise ValueError("instant_agent_worker_evidence_invalid")
        return {**evidence, "sha256": hashlib.sha256(raw).hexdigest(), "status": state["status"],
                "action_executed": state.get("action_executed")}


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
            original_command = response.get("command")
            # 此处只读取宿主发布的学习状态，绝不把轮询当成新的学习事件。
            recording_path = self.session / "learning-status" / path.name
            if recording_path.is_file():
                try:
                    response["learning_recording"] = read_json(recording_path)
                except (OSError, ValueError) as error:
                    response["learning_recording"] = {"status": "unavailable", "error_type": type(error).__name__}
            elif response.get("learning_binding"):
                response["learning_recording"] = {"status": "pending" if self._host_alive() else "recovery_needed",
                    "learning_id": response["learning_binding"]["learning_id"],
                    "next": "Read the same receipt; use learning_recover to retry recording only, never input."}
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
                    if not self._host_alive():
                        evidence = self._saved_agent_worker_evidence(request_id, original_command, result)
                        # 原接收快照不是退出后的执行事实；只读原 worker，不结算、不重派。
                        receipt.update(worker_status=("terminal_available" if evidence["status"] in
                            {"completed", "failed", "cancelled"} else "result_unknown"),
                            action_executed=True if (evidence["action_executed"] is True
                                or result.get("action_executed") is True) else None,
                            persisted_worker_evidence=evidence,
                            next_action="inspect_original_worker_evidence_no_replay")
                        receipt.pop("next", None)
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

