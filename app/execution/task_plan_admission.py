"""临时计划控制面；复用工作流队列与运行器，不建立第二个输入执行器。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import re

from app.core.instant_command_queue import command_queue_lock
from app.core.json_snapshot import read_json_snapshot
from app.learning_memory.workflow_program import _id
from app.learning_memory.workflow_runner import WorkflowRunner, _run_id
from app.learning_memory.workflow_runtime import WorkflowRuntime, _INPUT_KINDS, _TERMINAL
from .task_plan_backend import TaskPlanBackend
from .task_plan_contract import validate_task_plan, validate_task_plan_target
from .task_plan_verification import verify_task_plan_step


def validate_task_plan_request(value):
    if not isinstance(value, dict):
        raise ValueError("task_plan_request_invalid")
    action = value.get("action")
    fields = {
        "start": ({"action", "plan"}, {"vision_capabilities"}),
        "status": ({"action", "run_id"}, set()),
        "cancel": ({"action", "run_id"}, set()),
        "continue": ({"action", "run_id", "wait_id"}, set()),
        "review": ({"action", "run_id", "execution_request_id", "step_id", "verdict",
                    "reason", "evidence_sha256"}, set()),
    }
    if action not in fields:
        raise ValueError("task_plan_control_action_unsupported")
    required, optional = fields[action]
    if not required <= set(value) or set(value) - required - optional:
        raise ValueError("task_plan_control_fields_invalid")
    if action == "start":
        validate_task_plan(value["plan"])
        if "vision_capabilities" in value:
            from app.vision.recognition_source import ClientVisionCapabilities
            ClientVisionCapabilities.model_validate(value["vision_capabilities"])
    else:
        _run_id(value["run_id"])
    for field in ("wait_id", "step_id", "execution_request_id"):
        if field in value:
            _id(value[field], field)
    if action == "review":
        if (value["verdict"] not in {"success", "failure"}
                or not isinstance(value["reason"], str) or not value["reason"].strip()
                or len(value["reason"]) > 4000
                or not isinstance(value["evidence_sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", value["evidence_sha256"])):
            raise ValueError("task_plan_review_invalid")
    return deepcopy(value)


class TaskPlanRuntime(WorkflowRuntime):
    def __init__(self, session_dir, coordinator, *, owner_id, target_identity, reviewed_runtime,
                 agent_jobs=None, requires_client_vision=False):
        self.session = Path(session_dir).resolve()
        self.coordinator = coordinator
        self.agent_jobs = agent_jobs
        self._target_identity = target_identity
        self.reviewed_runtime = reviewed_runtime
        self.requires_client_vision = requires_client_vision
        self._enabled_run = None
        self._control_id = None
        self._next_tick = 0.0
        self.backend = TaskPlanBackend(self.session, owner_id=owner_id)
        self.runner = WorkflowRunner(self.session, backend=self.backend,
            submit_command=self._enqueue, read_result=self._read_result, verify_step=self._verify,
            settle_failed=self._verify)

    def _enqueue(self, execution_id, command):
        run_id = self.runner._active_run()
        if run_id is None:
            raise ValueError("task_plan_active_run_missing")
        state = self.backend.status(run_id)
        if validate_task_plan_target(self._target_identity()) != state["target_identity"]:
            raise ValueError("task_plan_target_changed_before_dispatch")
        self.reviewed_runtime._admit_input(execution_id, command)
        super()._enqueue(execution_id, command)

    def _verify(self, run_id, request_id, execution_id):
        if self.backend.status(run_id)["status"] == "cancel_requested":
            request_id = "task-cancel-" + sha256((run_id + execution_id).encode()).hexdigest()[:32]
        return verify_task_plan_step(self.backend, session_dir=self.session, run_id=run_id,
            request_id=request_id, execution_id=execution_id,
            decision_service=getattr(self.coordinator, "_decision_service", None))

    def _remember_active(self, snapshot):
        if (snapshot.get("status") == "cancel_requested"
                and snapshot.get("wait_reason") == "verification_required"
                and snapshot.get("runner_state") != "cancel_requested"):
            error = (snapshot.get("wait") or {}).get("error") or {}
            # 原审核等待上的取消先结算原票据；结算后仍未知才停止自动轮询。
            if error.get("message") != "task_plan_changed_during_verification":
                self._enabled_run = None
                return snapshot
        return super()._remember_active(snapshot)

    def _admit_input(self, request_id, command):
        run_id = self.runner._active_run()
        if run_id is None:
            return
        state = self.runner._load(run_id)
        if state is None:
            raise ValueError("task_plan_active_state_missing")
        if state["runner_state"] in _TERMINAL:
            return
        ticket = state.get("ticket")
        if (ticket and ticket["execution_request_id"] == request_id
                and ticket["suggested_command"] == command):
            if validate_task_plan_target(self._target_identity()) != self.backend.status(run_id)["target_identity"]:
                raise ValueError("task_plan_target_changed_before_execution")
            return
        raise ValueError("task_plan_run_active: finish or cancel the original plan before competing input")

    def admit(self, request_id, command):
        kind = command.get("kind")
        request = command.get("request") or {}
        competes = (kind in _INPUT_KINDS or kind == "learning_workflow"
                    and request.get("action") in {"start", "prepare", "run", "continue", "takeover_commit"})
        if competes:
            with command_queue_lock(self.session):
                self._admit_input(request_id, command)
        if kind == "task_plan" and request.get("action") in {"start", "continue"}:
            with command_queue_lock(self.session):
                self.reviewed_runtime._admit_input(request_id, command)

    def control(self, request, request_id):
        request = validate_task_plan_request(request)
        _id(request_id, "request_id")
        action = request["action"]
        self._control_id = request_id
        try:
            if action == "start":
                if (self.requires_client_vision and "vision_capabilities" not in request
                        and any(step["action"]["kind"] in {"click", "input_sequence"}
                                for step in request["plan"]["steps"])):
                    raise ValueError("task_plan_client_vision_capabilities_required")
                self.reviewed_runtime._admit_input(request_id, {"kind": "task_plan", "request": request})
                state = self.backend.start(request["plan"], validate_task_plan_target(self._target_identity()), request_id)
                kwargs = {"vision_capabilities": request["vision_capabilities"]} if "vision_capabilities" in request else {}
                return self._remember_active(self.runner.start(state["run_id"], request_id, "until_wait", **kwargs))
            run_id = request["run_id"]
            if action == "status":
                return self.runner.status(run_id)
            if action == "cancel":
                snapshot = self.runner.cancel(run_id, request_id)
                pending = snapshot.get("pending")
                if self.agent_jobs is not None and pending:
                    path = self.session / "agent-commands" / (pending["execution_request_id"] + ".json")
                    if path.is_file() and read_json_snapshot(path).get("status") not in _TERMINAL:
                        self.agent_jobs.cancel(pending["execution_request_id"])
                return self._remember_active(snapshot)
            if action == "review":
                snapshot = self.runner.status(run_id)
                if (snapshot.get("wait_reason") != "verification_required"
                        and request_id not in snapshot.get("verification_results", {})):
                    raise ValueError("task_plan_review_requires_verification_wait")
                verify_task_plan_step(self.backend, session_dir=self.session, run_id=run_id,
                    request_id=request_id, execution_id=request["execution_request_id"], review=request)
                # 审核只结算原票据；调用方用原 wait_id 明确继续，避免状态查询产生输入。
                return self.runner.status(run_id)
            return self._remember_active(self.runner.resume(run_id, request_id, request["wait_id"]))
        finally:
            self._control_id = None


__all__ = ["TaskPlanRuntime", "validate_task_plan_request"]
