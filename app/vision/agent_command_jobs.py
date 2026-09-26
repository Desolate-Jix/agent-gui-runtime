"""会话内 Agent 命令暂停器；交接识别时不重放已完成输入。"""

from copy import deepcopy
from pathlib import Path
import re
from threading import Condition, Thread
from time import monotonic
from uuid import uuid4

from app.core.agent_grounding_target import AgentGroundingTarget
from app.core.json_snapshot import write_json_snapshot
from app.desktop_review.form_fill import run_form_fill
from app.desktop_review.input_sequence import run_input_sequence
from app.vision.grounding_contract import GroundingResult
from app.vision.recognition_source import ClientVisionCapabilities, resolve_recognition_route


class AgentCommandError(ValueError):
    pass


class _Cancelled(AgentCommandError):
    pass


def _merge_action(previous, current):
    if previous is True or current is True:
        return True
    if previous is None or current is None:
        return None
    return False


def _receipt_action(receipt, operation):
    data = (receipt.get("response") or {}).get("data") or {}
    data = data.get("result", data)
    value = (data.get("pressed") if operation == "press_key" else
        (data.get("execution_path") or {}).get("action_executed", data.get("action_executed")))
    return value if type(value) is bool else None


class _CoordinatorProxy:
    def __init__(self, job):
        self._job = job

    def __getattr__(self, name):
        return getattr(self._job.manager.coordinator, name)

    def execute_local_step(self, **kwargs):
        job = self._job
        manager = job.manager
        with manager._condition:
            if job.cancelled:
                raise _Cancelled("agent_command_cancelled")
            manager._update(job, observation={"status": "unavailable", "reason": "action_in_progress"},
                dispatch_in_progress=kwargs.get("operation") != "execute_recognition_plan")
        if kwargs.get("operation") != "execute_recognition_plan":
            try:
                receipt = manager.coordinator.execute_local_step(**kwargs)
            except Exception:
                with manager._condition:
                    previous = manager._snapshots[job.command_id]["action_executed"]
                    manager._update(job, action_executed=_merge_action(previous, None),
                        observation={"status": "unavailable", "reason": "execution_result_unknown"})
                raise
            finally:
                with manager._condition:
                    manager._update(job, dispatch_in_progress=False)
            manager._record_receipt(job, receipt, kwargs["operation"])
            return receipt
        request = kwargs.get("request") or {}
        goal = request.get("goal")
        if not isinstance(goal, str) or not goal.strip():
            raise AgentCommandError("recognition_goal_invalid")
        capture = manager.coordinator._owner.call(manager.capture_current)
        if not isinstance(capture, dict):
            raise AgentCommandError("capture_invalid")
        # 每次交接以新 ID 绑定不可复用的截图，旧定位不能用于下一步。
        capture = deepcopy(capture)
        capture["capture_id"] = "capture-" + uuid4().hex
        request_id = "ag-" + uuid4().hex
        pending = manager.store.prepare(request_id, goal=goal, capture=capture,
            configuration=manager.configuration, capabilities=job.capabilities)
        with manager._condition:
            if job.cancelled:
                manager.store.cancel(request_id)
                raise _Cancelled("agent_command_cancelled")
            job.pending_id = request_id
            job.resume_state = None
            job.execution_id = None
            manager._update(job, status="awaiting_grounding", pending_grounding={
                **pending, "output_schema": GroundingResult.model_json_schema()},
                observation={"status": "captured", "capture": pending["capture"]})
            manager._condition.notify_all()
            while job.resume_state is None and not job.cancelled:
                manager._condition.wait(timeout=.1)
                if job.resume_state is None and not job.cancelled:
                    phase = manager.store.get(request_id)["phase"]
                    if phase in {"expired", "cancelled", "absent", "ambiguous", "unsupported", "error"}:
                        job.failure_code = "request_" + phase
                        job.cancelled = True
                        manager._update(job, status="failed", pending_grounding=None,
                            error={"code": job.failure_code})
            if job.cancelled:
                if job.resume_state is not None:
                    manager.store.finish_execution(request_id, job.execution_id,
                        {"phase": "cancelled_before_dispatch"}, input_attempted=False)
                else:
                    try:
                        manager.store.cancel(request_id)
                    except ValueError:
                        pass
                raise _Cancelled("agent_command_cancelled")
            claimed = job.resume_state
            execution_id = job.execution_id
            job.pending_id = None
            manager._update(job, status="running", pending_grounding=None,
                observation={"status": "unavailable", "reason": "action_in_progress"})
        dispatch_started = False
        try:
            with manager._condition:
                if job.cancelled:
                    manager.store.finish_execution(request_id, execution_id,
                        {"phase": "cancelled_before_dispatch"}, input_attempted=False)
                    raise _Cancelled("agent_command_cancelled")
            grounding_target = AgentGroundingTarget(claimed)
            # 此锁内标志是派发线性化点；之后取消只能请求停止，不能撤回已开始的原生调用。
            with manager._condition:
                if job.cancelled:
                    manager.store.finish_execution(request_id, execution_id,
                        {"phase": "cancelled_before_dispatch"}, input_attempted=False)
                    raise _Cancelled("agent_command_cancelled")
                dispatch_started = True
                manager._update(job, dispatch_in_progress=True)
            try:
                receipt = manager.coordinator.execute_local_step(**kwargs, grounding_target=grounding_target)
            finally:
                with manager._condition:
                    manager._update(job, dispatch_in_progress=False)
        except Exception as error:
            if not isinstance(error, _Cancelled):
                manager.store.finish_execution(request_id, execution_id,
                    {"phase": "result_unknown" if dispatch_started else "failed_before_dispatch",
                        "error": {"code": type(error).__name__}},
                    input_attempted=dispatch_started)
                with manager._condition:
                    previous = manager._snapshots[job.command_id]["action_executed"]
                    manager._update(job, action_executed=(True if previous is True else
                        None if dispatch_started else previous),
                        observation={"status": "unavailable", "reason":
                            "execution_result_unknown" if dispatch_started else "failed_before_dispatch"})
            raise
        manager.store.finish_execution(request_id, execution_id, receipt,
            input_attempted=grounding_target.input_claimed)
        manager._record_receipt(job, receipt, "execute_recognition_plan")
        return receipt


class _Job:
    def __init__(self, manager, command_id, command, target, capabilities):
        self.manager = manager
        self.command_id = command_id
        self.command = deepcopy(command)
        self.target = deepcopy(target)
        self.capabilities = capabilities
        self.pending_id = None
        self.resume_state = None
        self.execution_id = None
        self.cancelled = False
        self.failure_code = None
        self.thread = None


class AgentCommandJobs:
    """单宿主单活动命令；磁盘记录只供诊断，重启绝不恢复输入。"""

    def __init__(self, coordinator, store, capture_current, configuration):
        self.coordinator = coordinator
        self.store = store
        self.capture_current = capture_current
        self.configuration = configuration
        self._condition = Condition()
        self._jobs = {}
        self._snapshots = {}
        self._active_id = None
        self._closed = False
        self._root = Path(store.session_root) / "agent-commands"

    def _path(self, command_id):
        if not isinstance(command_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", command_id):
            raise AgentCommandError("command_id_invalid")
        return self._root / (command_id + ".json")

    def _update(self, job, **changes):
        state = deepcopy(self._snapshots[job.command_id])
        state.update(deepcopy(changes))
        write_json_snapshot(self._path(job.command_id), state)
        self._snapshots[job.command_id] = state
        return deepcopy(state)

    def _record_receipt(self, job, receipt, operation):
        with self._condition:
            previous = self._snapshots[job.command_id]["action_executed"]
            self._update(job, action_executed=_merge_action(
                previous, _receipt_action(receipt, operation)),
                observation=deepcopy(receipt.get("observation") or
                    {"status": "unavailable", "reason": "post_action_observation_unavailable"}))

    @property
    def active(self):
        with self._condition:
            return self._active_id is not None

    def start(self, command_id, command, target, capabilities):
        path = self._path(command_id)
        capabilities = ClientVisionCapabilities.model_validate(capabilities)
        route = resolve_recognition_route(self.configuration, capabilities)
        if route.status != "eligible":
            raise AgentCommandError(route.code)
        if route.dispatch_owner != "agent_client":
            raise AgentCommandError("handoff_requires_agent_source")
        if not isinstance(target, dict) or any(type(target.get(k)) is not int or target[k] <= 0
                for k in ("handle", "process_id")):
            raise AgentCommandError("target_invalid")
        if not isinstance(command, dict) or command.get("kind") not in {
                "form_fill", "input_sequence", "step"}:
            raise AgentCommandError("command_invalid")
        if not isinstance(command.get("request"), dict):
            raise AgentCommandError("command_request_invalid")
        # 在副本上验证，避免线程启动后才发现请求合同无效。
        frozen = deepcopy(command)
        from app.desktop_review.form_fill import FormFillRequest
        from app.desktop_review.input_sequence import InputSequenceRequest
        if frozen["kind"] == "form_fill":
            FormFillRequest.model_validate(frozen["request"])
        elif frozen["kind"] == "input_sequence":
            InputSequenceRequest.model_validate(frozen["request"])
        elif (frozen.get("operation") != "execute_recognition_plan"
                or not isinstance(frozen["request"].get("goal"), str)
                or not frozen["request"]["goal"].strip()):
            raise AgentCommandError("recognition_goal_invalid")
        with self._condition:
            if self._closed:
                raise AgentCommandError("manager_closed")
            if command_id in self._snapshots or path.exists():
                raise AgentCommandError("command_already_exists")
            if self._active_id is not None:
                raise AgentCommandError("command_active")
            self._root.mkdir(parents=True, exist_ok=True)
            job = _Job(self, command_id, frozen, target, capabilities)
            state = {"contract_version": "agent_command.v1", "command_id": command_id,
                "status": "running", "pending_grounding": None, "progress": None,
                "result": None, "observation": {"status": "not_requested", "capture": None},
                "action_executed": False, "cancel_requested": False,
                "dispatch_in_progress": False,
                "automatic_retry_allowed": False}
            write_json_snapshot(path, state)
            self._snapshots[command_id] = state
            self._jobs[command_id] = job
            self._active_id = command_id
            job.thread = Thread(target=self._run, args=(job,), name="agent-command-" + command_id,
                daemon=True)
            job.thread.start()
            return deepcopy(state)

    def _run(self, job):
        try:
            proxy = _CoordinatorProxy(job)
            command = job.command
            if command["kind"] == "form_fill":
                result = run_form_fill(proxy, job.target, command["request"],
                    persist=lambda progress: self._progress(job, progress))
            elif command["kind"] == "input_sequence":
                result = run_input_sequence(proxy, job.target, command["request"],
                    observation_wait_ms=command.get("observation_wait_ms"),
                    observation_condition=command.get("observation_condition"),
                    persist=lambda progress: self._progress(job, progress))
            else:
                result = proxy.execute_local_step(target_window_handle=job.target["handle"],
                    target_process_id=job.target["process_id"], operation="execute_recognition_plan",
                    request=command["request"], include_observation=True,
                    observation_wait_ms=command.get("observation_wait_ms"),
                    observation_condition=command.get("observation_condition"))
            action_executed = result.get("action_executed")
            if command["kind"] == "step":
                action_executed = _receipt_action(result, "execute_recognition_plan")
            if type(action_executed) is not bool:
                action_executed = None
            status = ("completed" if result.get("status", "completed") == "completed"
                and (command["kind"] != "step" or (result.get("response") or {}).get("success") is True
                    and result.get("phase") == "returned" and action_executed is True)
                else "failed")
            with self._condition:
                current_observation = self._snapshots[job.command_id]["observation"]
                observation = (current_observation if current_observation.get("reason") ==
                    "execution_result_unknown" else result.get("observation") or current_observation)
                self._update(job, status="failed" if job.failure_code else "cancelled" if job.cancelled else status,
                    pending_grounding=None, result=result,
                    action_executed=_merge_action(self._snapshots[job.command_id]["action_executed"],
                        action_executed),
                    observation=deepcopy(observation))
        except Exception as error:
            with self._condition:
                self._update(job, status="failed" if job.failure_code else "cancelled" if job.cancelled else "failed",
                    pending_grounding=None, error={"code": job.failure_code or str(error),
                        "type": type(error).__name__})
        finally:
            with self._condition:
                self._active_id = None
                self._condition.notify_all()

    def _progress(self, job, progress):
        with self._condition:
            previous = self._snapshots[job.command_id]
            changes = {"progress": progress,
                "action_executed": _merge_action(previous["action_executed"],
                    progress.get("action_executed", False))}
            if ("observation" in progress and previous["observation"].get("reason") !=
                    "execution_result_unknown"):
                changes["observation"] = progress["observation"]
            self._update(job, **changes)

    def get(self, command_id):
        self._path(command_id)
        with self._condition:
            if command_id not in self._snapshots:
                raise AgentCommandError("command_unknown")
            return deepcopy(self._snapshots[command_id])

    def resume(self, command_id, grounding_request_id, execution_id):
        self._path(command_id)
        with self._condition:
            job = self._jobs.get(command_id)
            if job is None:
                raise AgentCommandError("command_unknown")
            if (job.cancelled or self._snapshots[command_id]["status"] != "awaiting_grounding"
                    or job.resume_state is not None):
                raise AgentCommandError("command_not_awaiting_grounding")
            if grounding_request_id != job.pending_id:
                raise AgentCommandError("grounding_request_mismatch")
            claimed = self.store.claim_execution(grounding_request_id, execution_id)
            job.resume_state = claimed
            job.execution_id = execution_id
            resumed = self._update(job, status="running", pending_grounding=None,
                observation={"status": "unavailable", "reason": "action_in_progress"})
            self._condition.notify_all()
            return resumed

    def cancel(self, command_id):
        self._path(command_id)
        with self._condition:
            job = self._jobs.get(command_id)
            if job is None:
                raise AgentCommandError("command_unknown")
            if self._snapshots[command_id]["status"] in {"completed", "failed", "cancelled"}:
                return deepcopy(self._snapshots[command_id])
            job.cancelled = True
            if job.pending_id is not None and job.resume_state is None:
                self.store.cancel(job.pending_id)
            self._update(job, cancel_requested=True,
                **({"pending_grounding": None} if job.pending_id is not None else {}))
            self._condition.notify_all()
            return deepcopy(self._snapshots[command_id])

    def close(self, timeout=30):
        if type(timeout) not in (int, float) or timeout < 0:
            raise ValueError("close_timeout_invalid")
        deadline = monotonic() + timeout
        with self._condition:
            self._closed = True
            active = self._active_id
        if active is not None:
            self.cancel(active)
        threads = [job.thread for job in self._jobs.values() if job.thread is not None]
        for thread in threads:
            thread.join(timeout=max(0, deadline - monotonic()))
        return all(not thread.is_alive() for thread in threads)
