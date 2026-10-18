"""把工作流调度接入宿主原命令队列，不直接派发桌面输入。"""
from copy import deepcopy
from pathlib import Path
from time import monotonic

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from app.core.instant_command_queue import CommandQueueBusy, command_queue_lock, enqueue_command
from .workflow_program import _id
from .workflow_runner import WorkflowRunner, _run_id
from .workflow_control import validate_request


_INPUT_KINDS = frozenset({"launch", "select", "maximize", "step", "input_sequence", "form_fill",
    "close_launched_window", "desktop_capture", "desktop_click", "grounding_execute", "prepare_models", "release_models"})
_AUTO_WAITS = frozenset({None, "execution_pending", "grounding_required", "queue_busy"})
_TERMINAL = frozenset({"completed", "failed", "cancelled"})


class WorkflowRuntime:
    def __init__(self, session_dir, coordinator, *, agent_jobs=None):
        self.session = Path(session_dir).resolve()
        self.coordinator = coordinator
        self.agent_jobs = agent_jobs
        self._enabled_run = None
        self._control_id = None
        self._next_tick = 0.0
        self.runner = WorkflowRunner(self.session, library_root=coordinator._memory_library_root,
            submit_command=self._enqueue, read_result=self._read_result, verify_step=self._verify,
            settle_failed=self._settle_failed)

    def handles(self, request):
        action = request.get("action")
        if action in {"run", "continue", "verify", "takeover_preview", "takeover_commit"}:
            return True
        if action not in {"status", "cancel"}:
            return False
        return self.runner._path(request.get("run_id")).is_file()

    def _enqueue(self, execution_id, command):
        from app.instant_mcp import InstantCommand
        _id(execution_id, "execution_request_id")
        checked = InstantCommand.model_validate(command).command()
        if checked != command:
            raise ValueError("workflow_command_normalization_mismatch")
        if command["kind"] not in {"step", "input_sequence", "read_text"}:
            raise ValueError("workflow_command_kind_unsupported")
        enqueue_command(self.session, execution_id, deepcopy(command),
                        ignore_request_ids=(self._control_id,) if self._control_id else ())

    def _cancel_unsubmitted(self, run_id):
        state = self.runner._load(run_id)
        ticket = state.get("ticket") if state else None
        if not state or not state.get("cancel_request_id") or not ticket or ticket["dispatch_state"] != "deferred":
            return
        execution_id = ticket["execution_request_id"]
        command_path = self.session / "commands" / (execution_id + ".json")
        response_path = self.session / "responses" / command_path.name
        with command_queue_lock(self.session):
            if command_path.exists():
                # 已入队则只能回读原结果；不能从 deferred 标签猜测尚未执行。
                return
            receipt = {"command": deepcopy(ticket["suggested_command"]), "status": "returned",
                "result": {"status": "cancelled", "success": False, "action_executed": False,
                    "reason": "cancelled_before_submission", "run_id": run_id}}
            if response_path.exists() and read_json_snapshot(response_path) != receipt:
                raise ValueError("workflow_unsubmitted_cancel_receipt_conflict")
            # 先写无输入的取消事实，再保留原 ID，宿主不会把该命令当待执行。
            write_json_snapshot(response_path, receipt)
            write_json_snapshot(command_path, deepcopy(ticket["suggested_command"]))

    def _read_result(self, execution_id):
        _id(execution_id, "execution_request_id")
        command_path = self.session / "commands" / (execution_id + ".json")
        path = self.session / "responses" / command_path.name
        if not command_path.is_file():
            return {"command_id": execution_id, "status": "not_found"}
        if not path.is_file():
            return {"command_id": execution_id, "status": "pending"}
        original = read_json_snapshot(command_path)
        receipt = read_json_snapshot(path)
        if receipt.get("command") != original:
            raise ValueError("workflow_original_receipt_mismatch")
        result = receipt.get("result") or {}
        if result.get("contract_version") == "agent_command.v1":
            current_path = self.session / "agent-commands" / command_path.name
            current = read_json_snapshot(current_path) if current_path.is_file() else result
            if (current.get("contract_version") != "agent_command.v1"
                    or current.get("command_id") != execution_id or result.get("command_id") != execution_id):
                raise ValueError("workflow_async_receipt_identity_mismatch")
            return {"command_id": execution_id, "status": current.get("status"), "raw": current}
        status = "failed" if receipt.get("status") == "failed" else "completed" if receipt.get("status") == "returned" else "result_unknown"
        return {"command_id": execution_id, "status": status, "raw": receipt}

    def _verify(self, run_id, request_id, execution_id):
        trial = self.runner._trial("status", run_id)
        if trial.get("recovery_settlement"):
            raise ValueError("workflow_runtime_recovery_paused")
        from .runtime_verification import verify_trial_step
        if trial.get("status") == "cancel_requested":
            from .workspace import MemoryWorkspace
            from .workflow_trial import TrialService
            with MemoryWorkspace(self.coordinator._memory_library_root) as library:
                return TrialService(library, self.session).record_cancelled_execution(run_id, request_id, execution_id)
        return verify_trial_step(self.coordinator, session_dir=self.session, request_id=request_id,
            request={"action": "verify", "run_id": run_id, "execution_request_id": execution_id})

    def _settle_failed(self, run_id, request_id, execution_id):
        from .workspace import MemoryWorkspace
        from .workflow_trial import TrialService
        with MemoryWorkspace(self.coordinator._memory_library_root) as library:
            trials = TrialService(library, self.session)
            if trials.status(run_id)["status"] == "cancel_requested":
                return trials.record_cancelled_execution(run_id, request_id, execution_id)
            return trials.record_failed_execution(run_id, request_id, execution_id)

    def _remember_active(self, snapshot):
        settling_cancel = snapshot.get("status") == "cancel_requested" and snapshot.get("pending")
        if snapshot["runner_state"] in _TERMINAL or (not settling_cancel and snapshot.get("wait_reason") not in _AUTO_WAITS):
            self._enabled_run = None
        else:
            self._enabled_run = snapshot["run_id"]
        return snapshot

    def control(self, request, request_id):
        validate_request(request)
        _id(request_id, "request_id")
        action = request["action"]
        self._control_id = request_id
        try:
            if action in {'takeover_preview', 'takeover_commit'}:
                from .workflow_takeover_runtime import takeover_preview, takeover_commit
                handler = takeover_preview if action == 'takeover_preview' else takeover_commit
                return handler(self, request, request_id)
            run_id = _run_id(request["run_id"])
            if action == "verify":
                return self._verify(run_id, request_id, request["execution_request_id"])
            if action == "status":
                return self.runner.status(run_id)
            if action == "cancel":
                snapshot = self.runner.cancel(run_id, request_id)
                pending = snapshot.get("pending")
                if self.agent_jobs is not None and pending:
                    execution_id = pending["execution_request_id"]
                    path = self.session / "agent-commands" / (execution_id + ".json")
                    if path.is_file() and read_json_snapshot(path).get("status") not in _TERMINAL:
                        self.agent_jobs.cancel(execution_id)
                return self._remember_active(snapshot)
            if action == "run":
                kwargs = ({"vision_capabilities": request["vision_capabilities"]}
                          if "vision_capabilities" in request else {})
                return self._remember_active(self.runner.start(run_id, request_id, request["mode"], **kwargs))
            if action == "continue":
                return self._remember_active(self.runner.resume(run_id, request_id, request["wait_id"]))
            raise ValueError("workflow_runtime_action_unsupported")
        finally:
            self._control_id = None

    def tick(self, *, force=False):
        if self._enabled_run is None or (not force and monotonic() < self._next_tick):
            return None
        if (self.session / "closing.json").exists():
            self.stop()
            return None
        self._next_tick = monotonic() + .2
        try:
            self._cancel_unsubmitted(self._enabled_run)
        except CommandQueueBusy:
            return self.runner.status(self._enabled_run)
        return self._remember_active(self.runner.advance(self._enabled_run))

    def admit(self, request_id, command):
        if command.get("kind") not in _INPUT_KINDS:
            return
        from .workflow_recovery_import import ensure_session_takeover_ready
        ensure_session_takeover_ready(self.session)
        with command_queue_lock(self.session):
            self._admit_input(request_id, command)

    def _admit_input(self, request_id, command):
        from .workflow_recovery_import import ensure_session_takeover_ready
        ensure_session_takeover_ready(self.session)
        run_id = self.runner._active_run()
        if run_id is None:
            return
        state = self.runner._load(run_id)
        if state is None:
            raise ValueError("workflow_active_state_missing")
        if self.runner._trial("status", run_id).get("recovery_settlement"):
            raise ValueError("workflow_runtime_recovery_paused")
        if state["runner_state"] in _TERMINAL:
            return
        ticket = state.get("ticket")
        if (ticket and ticket["execution_request_id"] == request_id
                and ticket["suggested_command"] == command):
            return
        raise ValueError("workflow_run_active: finish or cancel the original workflow before competing input")

    def stop(self):
        # 重开只显示原账本，显式继续之前不得恢复调度。
        self._enabled_run = None


__all__ = ["WorkflowRuntime"]
