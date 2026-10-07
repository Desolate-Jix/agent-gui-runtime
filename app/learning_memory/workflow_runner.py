"""在原 Trial 账本之上连续调度已定义步骤，不另建输入执行器。"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
import os
import re
from pathlib import Path
from time import perf_counter_ns
from uuid import uuid4

from app.desktop_review.workspace import _atomic_write_bytes
from app.core.instant_command_queue import CommandQueueBusy

from .workspace import MemoryWorkspace
from .workflow_program import _id
from .workflow_trial import _RUN


_SCHEMA = "workflow_runner.v1"
_CLOCK_ID = uuid4().hex
_TERMINAL = frozenset({"completed", "failed", "cancelled"})
_RESULT_STATUSES = frozenset({"pending", "running", "awaiting_grounding", "completed", "failed", "cancelled", "result_unknown", "not_found"})


def _digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(raw).hexdigest()


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _run_id(value):
    return _id(value, "run_id", _RUN)


def _callback_error(error, command=None):
    message = str(error).strip()[:240] or type(error).__name__
    def leaves(value):
        if isinstance(value, dict):
            for child in value.values():
                yield from leaves(child)
        elif isinstance(value, list):
            for child in value:
                yield from leaves(child)
        elif isinstance(value, str) and len(value) >= 3:
            yield value
    for secret in sorted(set(leaves(command)), key=len, reverse=True):
        message = message.replace(secret, "[redacted]")
    return {"error_type": type(error).__name__, "message": message}


@contextmanager
def _exclusive(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0)
        if not stream.read(1):
            stream.seek(0)
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise ValueError("workflow_runner_busy") from error
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise ValueError("workflow_runner_busy") from error
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class WorkflowRunner:
    def __init__(self, session_dir, *, library_root, submit_command, read_result, verify_step, settle_failed=None):
        if not all(callable(item) for item in (submit_command, read_result, verify_step)):
            raise ValueError("workflow_runner_callbacks_required")
        self.session = Path(session_dir).resolve()
        self.library_root = Path(library_root).resolve()
        self.submit_command = submit_command
        self.read_result = read_result
        self.verify_step = verify_step
        self.settle_failed = settle_failed
        self.root = self.session / "workflow-runners"
        self.active_path = self.root / "active.json"
        self.lock_path = self.root / "active.lock"

    def _path(self, run_id):
        return self.root / (_run_id(run_id) + ".json")

    def _load(self, run_id):
        path = self._path(run_id)
        if not path.exists():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema") != _SCHEMA or value.get("run_id") != run_id:
            raise ValueError("workflow_runner_state_invalid")
        return value

    def _active_run(self):
        if not self.active_path.exists():
            return None
        value = json.loads(self.active_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema") != _SCHEMA:
            raise ValueError("workflow_runner_active_invalid")
        return _run_id(value.get("run_id"))

    def _set_active(self, run_id):
        _atomic_write_bytes(self.active_path, json.dumps({"schema": _SCHEMA, "run_id": run_id},
                                             sort_keys=True).encode("utf-8") + b"\n")

    def _save(self, state):
        _atomic_write_bytes(self._path(state["run_id"]), json.dumps(state, ensure_ascii=False, sort_keys=True,
                                                  separators=(",", ":")).encode("utf-8") + b"\n")

    def _trial(self, action, run_id, *args, **kwargs):
        with MemoryWorkspace(self.library_root) as library:
            method = getattr(library, action + "_workflow_trial")
            return method(self.session, run_id, *args, **kwargs)

    def _step_vision_capabilities(self, state, trial):
        capabilities = state.get("vision_capabilities")
        if capabilities is None:
            return None
        with MemoryWorkspace(self.library_root) as library:
            program = library.load_workflow_program(trial["workflow_id"], trial["program_id"])
        steps = program["definition"]["steps"]
        matches = [step for step in steps if step["step_id"] == trial["current_step_id"]]
        if len(matches) != 1:
            raise ValueError("workflow_runner_step_not_in_pinned_program")
        return deepcopy(capabilities) if matches[0]["action"]["kind"] in {"click", "input_sequence"} else None

    def _snapshot(self, state, *, trial=None):
        from .workflow_metrics import load_run_metrics
        if trial is None:
            trial = self._trial("status", state["run_id"])
        snapshot = {**trial, "runner_state": state["runner_state"], "mode": state["mode"],
                "wait_reason": state.get("wait", {}).get("reason") if state.get("wait") else None,
                "wait": deepcopy(state.get("wait")), "active_command_id": state["ticket"]["execution_request_id"] if state.get("ticket") else None,
                "metrics": load_run_metrics(self.session, state["run_id"], trial=trial)}
        if trial.get("recovery_settlement"):
            snapshot.update(runner_state="waiting", wait_reason="recovery_paused")
        return snapshot

    def _wait(self, state, reason, *, raw=None):
        ticket = state.get("ticket")
        command_id = ticket["execution_request_id"] if ticket else None
        step_id = ticket["step_id"] if ticket else state.get("current_step_id")
        wait = {"wait_id": "workflow-wait-" + _digest([state["run_id"], reason, command_id, step_id])[:32],
                "reason": reason, "run_id": state["run_id"], "step_id": step_id, "command_id": command_id}
        if reason == "grounding_required":
            pending = raw.get("pending_grounding") if isinstance(raw, dict) else None
            wait["pending_grounding"] = deepcopy(pending)
        if ticket and ticket.get("callback_error"):
            wait["error"] = deepcopy(ticket["callback_error"])
        if (reason == "verification_required" and ticket and not state.get("cancel_request_id")
                and "verification_wait" in state and state["verification_wait"] is None):
            state["verification_wait"] = {
                "execution_request_id": command_id, "step_id": step_id,
                "command_sha256": ticket["command_sha256"],
                "clock_id": _CLOCK_ID, "started_ns": perf_counter_ns()}
        state["wait"] = wait
        state["runner_state"] = "single_complete" if reason == "single_step_complete" else "waiting"
        self._save(state)

    def _prepared(self, state, prepared):
        if not isinstance(prepared, dict):
            raise ValueError("workflow_runner_prepare_invalid")
        if prepared.get("status") == "blocked":
            state["current_step_id"] = prepared.get("current_step_id")
            reason = str(prepared.get("reason", ""))
            self._wait(state, "input_required" if "input" in reason or "output" in reason else "uncertain")
            return False
        if prepared.get("status") != "pending" or not isinstance(prepared.get("suggested_command"), dict):
            raise ValueError("workflow_runner_prepare_invalid")
        step_id, command_id = prepared.get("step_id"), prepared.get("execution_request_id")
        if not _text(step_id) or not _text(command_id):
            raise ValueError("workflow_runner_ticket_invalid")
        if step_id in state["seen_steps"] or len(state["seen_steps"]) >= 256:
            self._wait(state, "failed")
            return False
        command = deepcopy(prepared["suggested_command"])
        state["seen_steps"].append(step_id)
        state["ticket"] = {"step_id": step_id, "execution_request_id": command_id,
                           "prepare_request_id": "wr-prepare-" + _digest([state["run_id"], step_id, len(state["seen_steps"])])[:32],
                           "verify_request_id": "wr-verify-" + _digest([state["run_id"], command_id])[:32],
                           "command_sha256": _digest(command), "suggested_command": command,
                           "dispatch_state": "dispatching"}
        state["current_step_id"] = step_id
        state["runner_state"] = "dispatching"
        state["wait"] = None
        self._save(state)
        return True

    def _adopt_pending(self, state, trial):
        pending = trial.get("pending")
        if not isinstance(pending, dict):
            return False
        if not self._prepared(state, {"status": "pending", **pending}):
            return False
        state["ticket"]["dispatch_state"] = "externally_pending"
        self._save(state)
        self._wait(state, "execution_pending")
        return True

    def _reconcile(self, state):
        if state.get("recovery_import") is not None:
            self._recovery_guard(self._trial("status", state["run_id"]), state)
        ticket = state["ticket"]
        command_id = ticket["execution_request_id"]
        trial = self._trial("status", state["run_id"])
        if self._reviewed_ticket(trial, ticket):
            return self._settle_reviewed(state, trial)
        try:
            result = self.read_result(command_id)
        except Exception as error:
            ticket["callback_error"] = _callback_error(error)
            self._wait(state, "result_unknown")
            return False
        if (not isinstance(result, dict) or result.get("status") not in _RESULT_STATUSES
                or result.get("command_id") != command_id):
            self._wait(state, "result_unknown")
            return False
        status = result["status"]
        if status in {"pending", "running"}:
            self._wait(state, "execution_pending")
            return False
        if status == "awaiting_grounding":
            self._wait(state, "grounding_required", raw=result.get("raw"))
            return False
        if status in {"result_unknown", "not_found"}:
            self._wait(state, "result_unknown")
            return False
        try:
            callback = self.settle_failed if status == "failed" and self.settle_failed is not None else self.verify_step
            verified = callback(state["run_id"], ticket["verify_request_id"], command_id)
        except Exception as error:
            ticket["callback_error"] = _callback_error(error)
            self._wait(state, "verification_required")
            return False
        if not isinstance(verified, dict) or verified.get("status") == "verification_required":
            self._wait(state, "verification_required")
            return False
        trial = self._trial("status", state["run_id"])
        if not self._reviewed_ticket(trial, ticket):
            self._wait(state, "verification_required")
            return False
        return self._settle_reviewed(state, trial)

    @staticmethod
    def _reviewed_ticket(trial, ticket):
        history = trial.get("history")
        return (trial.get("pending") is None and isinstance(history, list) and bool(history)
                and isinstance(history[-1], dict)
                and history[-1].get("execution_request_id") == ticket["execution_request_id"]
                and history[-1].get("step_id") == ticket["step_id"])

    def _settle_reviewed(self, state, trial):
        verdict = trial["history"][-1].get("verdict")
        self._finish_verification_wait(state, {"success": "success", "failure": "failure"}.get(verdict, "waiting"))
        state["ticket"] = None
        state["wait"] = None
        state["steps_completed"] += 1
        state["current_step_id"] = trial.get("current_step_id")
        if trial["status"] in {"completed", "failed", "cancelled"}:
            state["runner_state"] = trial["status"]
        elif trial["status"] == "paused_uncertain":
            self._wait(state, "uncertain")
            return False
        elif state.get("cancel_request_id"):
            state["runner_state"] = "cancel_requested"
        elif state["mode"] == "single":
            self._wait(state, "single_step_complete")
            return False
        elif trial["status"] == "ready":
            state["runner_state"] = "ready"
        else:
            self._wait(state, "failed")
            return False
        self._save(state)
        return state["runner_state"] == "ready"

    @staticmethod
    def _finish_verification_wait(state, status):
        pending = state.get("verification_wait")
        if pending is None:
            return
        # 跨宿主不拼接单调时钟；旧账本没有起点时也不补造历史。
        closed = {**pending, "status": status, "measurement": None}
        if pending["clock_id"] == _CLOCK_ID:
            closed["measurement"] = {"started_ns": pending["started_ns"], "ended_ns": perf_counter_ns()}
        else:
            closed["unmeasured_reason"] = "clock_changed"
        state.setdefault("verification_waits", []).append(closed)
        state["verification_wait"] = None

    def _drive(self, state, *, allow_new_dispatch=True):
        trial = self._trial("status", state["run_id"])
        self._recovery_guard(trial, state)
        if trial.get("recovery_settlement"):
            return
        for _ in range(257):
            if state["runner_state"] in _TERMINAL or state["runner_state"] == "single_complete" or state["runner_state"] == "cancel_requested" and not state.get("ticket"):
                return
            if state.get("ticket") is not None:
                if state["ticket"]["dispatch_state"] == "deferred" and not state.get("cancel_request_id"):
                    if not self._submit_ticket(state):
                        return
                if not self._reconcile(state):
                    return
                if not allow_new_dispatch:
                    return
                continue
            if state.get("wait") is not None and state["wait"]["reason"] not in {"execution_pending", "grounding_required"}:
                return
            if not allow_new_dispatch or state.get("cancel_request_id"):
                return
            trial = self._trial("status", state["run_id"])
            if trial.get("pending") is not None:
                self._adopt_pending(state, trial)
                return
            if trial.get("status") in {"completed", "failed", "cancelled"}:
                state["runner_state"] = trial["status"]
                self._save(state)
                return
            if trial.get("status") != "ready":
                self._wait(state, "uncertain" if trial.get("status") == "paused_uncertain" else "failed")
                return
            step_id = trial.get("current_step_id")
            if not _text(step_id) or step_id in state["seen_steps"] or len(state["seen_steps"]) >= 256:
                self._wait(state, "failed")
                return
            request_id = "wr-prepare-" + _digest([state["run_id"], step_id, len(state["seen_steps"]) + 1])[:32]
            capabilities = self._step_vision_capabilities(state, trial)
            prepared = self._trial("prepare", state["run_id"], request_id,
                                   vision_capabilities=capabilities) if capabilities is not None else self._trial("prepare", state["run_id"], request_id)
            if not self._prepared(state, prepared):
                return
            if not self._submit_ticket(state):
                return
            if not self._reconcile(state):
                return
            if not allow_new_dispatch:
                return
        self._wait(state, "failed")

    def _submit_ticket(self, state):
        if state.get("recovery_import") is not None:
            self._recovery_guard(self._trial("status", state["run_id"]), state)
        ticket = state["ticket"]
        # 先落盘不确定派发状态；只有明确未写队列的忙碌错误允许重试原 ID。
        ticket["dispatch_state"] = "dispatching"
        ticket.pop("callback_error", None)
        self._save(state)
        try:
            self.submit_command(ticket["execution_request_id"], deepcopy(ticket["suggested_command"]))
        except CommandQueueBusy as error:
            ticket["dispatch_state"] = "deferred"
            ticket["callback_error"] = _callback_error(error)
            self._wait(state, "queue_busy")
            return False
        except Exception as error:
            ticket["callback_error"] = _callback_error(error, ticket["suggested_command"])
        else:
            ticket["dispatch_state"] = "submitted"
        self._save(state)
        return True

    def start(self, run_id, request_id, mode, *, vision_capabilities=None):
        _run_id(run_id)
        if not _text(request_id) or mode not in {"single", "until_wait"}:
            raise ValueError("workflow_runner_start_invalid")
        control_request = {"action": "run", "run_id": run_id, "mode": mode}
        if vision_capabilities is not None:
            control_request["vision_capabilities"] = deepcopy(vision_capabilities)
        if vision_capabilities is not None:
            from app.vision.recognition_source import ClientVisionCapabilities
            if not isinstance(vision_capabilities, dict):
                raise ValueError("workflow_runner_vision_capabilities_invalid")
            vision_capabilities = ClientVisionCapabilities.model_validate(vision_capabilities).model_dump(exclude_none=True)
        with _exclusive(self.lock_path):
            state = self._load(run_id)
            self._recovery_guard(self._trial("status", run_id), state)
            if state is not None:
                if (state["start_request_id"] != request_id or state["mode"] != mode
                        or state.get("vision_capabilities") != vision_capabilities):
                    raise ValueError("workflow_runner_start_conflict")
                return self._snapshot(state)
            active = self._active_run()
            if active is not None:
                active_state = self._load(active)
                if active_state is None or active_state["runner_state"] not in _TERMINAL:
                    raise ValueError("workflow_runner_session_active")
            self._trial("status", run_id)
            state = {"schema": _SCHEMA, "run_id": run_id, "start_request_id": request_id,
                     "mode": mode, "vision_capabilities": vision_capabilities,
                     "runner_state": "ready", "current_step_id": None,
                     "ticket": None, "wait": None, "seen_steps": [], "steps_completed": 0,
                     "verification_wait": None, "verification_waits": [],
                     "cancel_request_id": None, "resume_requests": {},
                     "control_requests": {request_id: {"schema": "workflow_runner_control.v1",
                         "command_sha256": _digest({"kind": "learning_workflow", "request": control_request})}}}
            self._save(state)
            self._set_active(run_id)
            self._drive(state)
            return self._snapshot(state)

    def advance(self, run_id):
        with _exclusive(self.lock_path):
            state = self._load(run_id)
            if state is None or state["run_id"] != run_id:
                raise ValueError("workflow_runner_run_unknown")
            self._recovery_guard(self._trial("status", run_id), state, revalidate_initial=True)
            self._drive(state)
            return self._snapshot(state)

    def status(self, run_id):
        state = self._load(run_id)
        if state is None or state["run_id"] != run_id:
            raise ValueError("workflow_runner_run_unknown")
        return self._snapshot(state)

    def cancel(self, run_id, request_id):
        if not _text(request_id):
            raise ValueError("workflow_runner_cancel_request_invalid")
        with _exclusive(self.lock_path):
            state = self._load(run_id)
            if state is None or state["run_id"] != run_id:
                raise ValueError("workflow_runner_run_unknown")
            if self._trial("status", run_id).get("recovery_settlement"):
                raise ValueError("workflow_runner_recovery_paused")
            if state.get("cancel_request_id") not in (None, request_id):
                raise ValueError("workflow_runner_cancel_conflict")
            if state["runner_state"] in _TERMINAL:
                return self._snapshot(state)
            trial = self._trial("cancel", run_id, request_id)
            self._finish_verification_wait(state, "cancelled")
            state["cancel_request_id"] = request_id
            if state.get("ticket") and self._reviewed_ticket(trial, state["ticket"]):
                # 外部审核可先清空 Trial 待处理项；取消时结算原票据，不派发下一步。
                self._settle_reviewed(state, trial)
            else:
                state["runner_state"] = "cancel_requested" if state.get("ticket") else "cancelled"
                self._save(state)
            return self._snapshot(state)

    def resume(self, run_id, request_id, wait_id):
        if not _text(request_id) or not _text(wait_id):
            raise ValueError("workflow_runner_resume_invalid")
        with _exclusive(self.lock_path):
            state = self._load(run_id)
            if state is None or state["run_id"] != run_id:
                raise ValueError("workflow_runner_run_unknown")
            if state["runner_state"] in _TERMINAL and state.get("wait") is not None:
                raise ValueError("workflow_runner_terminal_wait_invalid")
            self._recovery_guard(self._trial("status", run_id), state, revalidate_initial=True)
            if self._trial("status", run_id).get("recovery_settlement"):
                raise ValueError("workflow_runner_recovery_paused")
            prior = state["resume_requests"].get(request_id)
            if prior is not None:
                if prior != wait_id:
                    raise ValueError("workflow_runner_resume_conflict")
                return self._snapshot(state)
            if not state.get("wait") or state["wait"]["wait_id"] != wait_id:
                raise ValueError("workflow_runner_wait_id_mismatch")
            if state.get("ticket") is None:
                trial = self._trial("status", run_id)
                if trial.get("status") not in {"ready", "completed", "failed", "cancelled"}:
                    return self._snapshot(state)
            controls = state.setdefault("control_requests", {})
            if request_id in controls:
                raise ValueError("workflow_runner_control_conflict")
            controls[request_id] = {"schema": "workflow_runner_control.v1", "command_sha256": _digest({
                "kind": "learning_workflow", "request": {"action": "continue", "run_id": run_id, "wait_id": wait_id}})}
            state["resume_requests"][request_id] = wait_id
            state["wait"] = None
            state["runner_state"] = "ready" if state.get("ticket") is None else "dispatching"
            self._save(state)
            self._drive(state, allow_new_dispatch=state["mode"] == "single" and state.get("ticket") is None)
            return self._snapshot(state)

    def _recovery_claim(self, trial, phases):
        marker = trial.get("recovery_import")
        from .workflow_recovery_resolution import marker_resolution
        try:
            resolution = marker_resolution(marker)
        except ValueError as error:
            raise ValueError("workflow_runner_recovery_import_invalid") from error
        def require(condition):
            if not condition:
                raise ValueError("workflow_runner_recovery_import_invalid")
        for key in ("claim_id", "source_program_sha256", "source_settlement_sha256", "effect_evidence_sha256", "verified_history_sha256"):
            require(isinstance(marker[key], str) and re.fullmatch(r"[0-9a-f]{64}", marker[key]) is not None)
        require(all(_text(marker[key]) for key in ("request_id", "source_step_id", "source_execution_request_id", "effect_evidence_ref")))
        require(isinstance(marker["source_session_name"], str) and re.fullmatch(r"session-[0-9a-f]{32}", marker["source_session_name"]) is not None)
        _run_id(marker["source_run_id"])
        steps = marker["consumed_step_ids"]
        minimum = 0 if resolution == "resume_unexecuted" else 1
        require(isinstance(steps, list) and minimum <= len(steps) <= 256
                and all(_text(step) for step in steps) and len(set(steps)) == len(steps))
        require(resolution != "resume_unexecuted" or marker["source_step_id"] not in steps)
        ref = Path(marker["effect_evidence_ref"])
        require(not ref.is_absolute() and (self.session / ref).resolve().is_relative_to(self.session))
        path = self.session.parent / "workflow-takeovers" / (marker["claim_id"] + ".json")
        require(path.resolve().parent == self.session.parent / "workflow-takeovers")
        try:
            claim = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise ValueError("workflow_runner_recovery_claim_invalid") from error
        require(isinstance(claim, dict) and claim.get("contract_version") == "workflow_takeover_claim.v1"
                and claim.get("phase") in phases and claim.get("claim_id") == marker["claim_id"]
                and claim.get("request_id") == marker["request_id"] and claim.get("new_session_name") == self.session.name
                and claim.get("new_run_id") == trial["run_id"])
        require(claim.get("recovery_import") == marker)
        history = trial.get("history")
        require(isinstance(history, list) and len(history) >= len(steps))
        prefix = history[:len(steps)]
        require(all(isinstance(row, dict) for row in prefix) and [row.get("step_id") for row in prefix] == steps)
        require(isinstance(claim.get("imported_history_sha256"), str) and re.fullmatch(r"[0-9a-f]{64}", claim["imported_history_sha256"]) is not None
                and _digest(prefix) == claim["imported_history_sha256"])
        if claim["phase"] == "importing":
            require(claim.get("trial_state_sha256") == _digest(trial))
        return marker

    def _recovery_guard(self, trial, state, *, revalidate_initial=False):
        if trial.get("recovery_import") is None:
            if state is not None and state.get("recovery_import") is not None:
                raise ValueError("workflow_runner_recovery_import_invalid")
            return
        marker = self._recovery_claim(trial, {"ready"})
        if state is None or state.get("recovery_import") != {"claim_id": marker["claim_id"], "request_id": marker["request_id"]}:
            raise ValueError("workflow_runner_recovery_import_required")
        if (revalidate_initial and marker.get("resolution") == "resume_unexecuted"
                and state.get("ticket") is None and state.get("runner_state") not in _TERMINAL):
            from .workflow_recovery_import import validate_recovery_progress
            with MemoryWorkspace(self.library_root) as library:
                verified = validate_recovery_progress(library, self.session, trial)
            consumed = verified["consumed_step_ids"]
            if (state.get("seen_steps") != consumed or state.get("steps_completed") != len(consumed)
                    or consumed == marker["consumed_step_ids"]
                    and state.get("current_step_id") != marker["source_step_id"]):
                raise ValueError("workflow_runner_recovery_initial_state_invalid")

    def import_recovery(self, run_id, request_id, *, mode, claim_id, seen_steps, vision_capabilities=None, trial_service=None):
        _run_id(run_id)
        if not _text(request_id) or mode not in {"single", "until_wait"}:
            raise ValueError("workflow_runner_recovery_import_invalid")
        if vision_capabilities is not None:
            from app.vision.recognition_source import ClientVisionCapabilities
            if not isinstance(vision_capabilities, dict):
                raise ValueError("workflow_runner_vision_capabilities_invalid")
            vision_capabilities = ClientVisionCapabilities.model_validate(vision_capabilities).model_dump(exclude_none=True)
        with _exclusive(self.lock_path):
            if trial_service is not None:
                from .workflow_trial import TrialService
                if (not isinstance(trial_service, TrialService) or trial_service.session != self.session
                        or Path(trial_service.programs.library._artifact_root).resolve() != self.library_root):
                    raise ValueError("workflow_runner_recovery_trial_service_invalid")
                # 导入调用者已持有库锁，复用该服务而不二次打开同库。
                trial = trial_service.status(run_id)
            else:
                trial = self._trial("status", run_id)
            marker = self._recovery_claim(trial, {"importing"})
            if (trial.get("status") not in {"ready", "completed"} or trial.get("pending") is not None or trial.get("recovery_settlement") is not None
                    or marker["claim_id"] != claim_id or marker["request_id"] != request_id or seen_steps != marker["consumed_step_ids"]):
                raise ValueError("workflow_runner_recovery_import_invalid")
            active = self._active_run()
            if active is not None and active != run_id:
                other = self._load(active)
                if other is None or other["runner_state"] not in _TERMINAL:
                    raise ValueError("workflow_runner_session_active")
            state = self._load(run_id)
            binding = {"claim_id": claim_id, "request_id": request_id}
            if state is not None:
                if (state.get("recovery_import") != binding or state["start_request_id"] != request_id or state["mode"] != mode
                        or state.get("vision_capabilities") != vision_capabilities or state["seen_steps"] != seen_steps
                        or state.get("ticket") is not None or state["current_step_id"] != trial.get("current_step_id")):
                    raise ValueError("workflow_runner_recovery_import_conflict")
            else:
                state = {"schema": _SCHEMA, "run_id": run_id, "start_request_id": request_id, "mode": mode,
                    "vision_capabilities": vision_capabilities, "runner_state": "completed" if trial["status"] == "completed" else "ready",
                    "current_step_id": trial.get("current_step_id"), "ticket": None, "wait": None, "seen_steps": deepcopy(seen_steps),
                    "steps_completed": len(seen_steps), "verification_wait": None, "verification_waits": [],
                    "cancel_request_id": None, "resume_requests": {}, "recovery_import": binding}
                if trial["status"] == "ready":
                    self._wait(state, "takeover_ready")
                else:
                    self._save(state)
            if active != run_id:
                self._set_active(run_id)
            return self._snapshot(state, trial=trial)


__all__ = ["WorkflowRunner"]
