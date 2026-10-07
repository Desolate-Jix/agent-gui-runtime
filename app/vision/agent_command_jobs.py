"""会话内 Agent 命令暂停器；交接识别时不重放已完成输入。"""

from app.core.vision_admission_contract import AgentCommandError, AgentCommandVisionAdmissionError
from app.core.receipt_action import _receipt_action
from copy import deepcopy
from hashlib import sha256
from app.desktop_review.external_mapping import canonical_json_bytes
from pathlib import Path
import re
from threading import Condition, Thread
from time import monotonic, perf_counter_ns
from uuid import uuid4

from app.core.agent_grounding_target import AgentGroundingTarget
from app.core.json_snapshot import write_json_snapshot
from app.execution.form_fill import run_form_fill
from app.execution.input_sequence import run_input_sequence
from app.vision.grounding_contract import GroundingResult
from app.vision.recognition_source import ClientVisionCapabilities, resolve_recognition_route






class _Cancelled(AgentCommandError):
    pass


def _merge_action(previous, current):
    if previous is True or current is True:
        return True
    if previous is None or current is None:
        return None
    return False




class _CoordinatorProxy:
    def __init__(self, job):
        self._job = job

    def __getattr__(self, name):
        return getattr(self._job.manager.coordinator, name)

    def execute_local_step(self, **kwargs):
        job = self._job
        manager = job.manager
        kwargs.pop("learning_context", None)
        if job.learning_context is not None:
            kwargs["learning_context"] = deepcopy(job.learning_context)
        with manager._condition:
            if job.cancelled:
                raise _Cancelled("agent_command_cancelled")
            if kwargs.get("operation") != "execute_recognition_plan":
                attempt_index = manager._begin_dispatch(job, kwargs["operation"])
            else:
                manager._update(job, observation={"status": "unavailable", "reason": "action_in_progress"})
        if kwargs.get("operation") != "execute_recognition_plan":
            try:
                receipt = manager.coordinator.execute_local_step(**kwargs)
            except Exception:
                manager._record_unknown(job, kwargs["operation"], attempt_index)
                raise
            manager._record_receipt(job, receipt, kwargs["operation"], attempt_index)
            return receipt
        request = kwargs.get("request") or {}
        goal = request.get("goal")
        if not isinstance(goal, str) or not goal.strip():
            raise AgentCommandError("recognition_goal_invalid")
        if request.get("target_memory") is not None:
            if job.workflow_bindings is not None:
                kwargs["memory_bindings"] = deepcopy(job.workflow_bindings)
            memory_target, resolution = manager.coordinator.prepare_memory_grounding(
                target_window_handle=kwargs["target_window_handle"],
                target_process_id=kwargs["target_process_id"], request=request,
                action=kwargs.get("memory_action"),
                **({"memory_bindings": kwargs["memory_bindings"]} if "memory_bindings" in kwargs else {}))
            kwargs["memory_resolution"] = resolution
            if memory_target is not None:
                return self._execute_memory(kwargs, memory_target)
            if resolution["status"] in {"miss", "ambiguous", "unsupported"}:
                if request.get('selection_intent') is not None:
                    raise AgentCommandError('selection_unique_bound_row_required')
                goal = resolution.get("grounding_goal", goal)
                request = deepcopy(request)
                request["goal"] = goal
                request.pop("target_memory", None)
                kwargs["request"] = request
                kwargs.pop("memory_action", None)
                kwargs.pop("memory_bindings", None)
        route = resolve_recognition_route(manager.configuration, job.capabilities)
        if route.status != "eligible":
            raise AgentCommandError(route.code)
        capture = manager.coordinator._owner.call(manager.capture_current)
        if not isinstance(capture, dict):
            raise AgentCommandError("capture_invalid")
        # 每次交接以新 ID 绑定不可复用的截图，旧定位不能用于下一步。
        capture = deepcopy(capture)
        capture["capture_id"] = "capture-" + uuid4().hex
        request_id = "ag-" + uuid4().hex
        pending = manager.store.prepare(request_id, goal=goal, capture=capture,
            configuration=manager.configuration, capabilities=job.capabilities)
        if manager.api_grounder is not None:
            manager._resolve_api(job, pending)
        with manager._condition:
            if job.cancelled:
                if job.resume_state is not None and manager.api_grounder is not None:
                    manager.store.finish_execution(request_id, job.execution_id,
                        {"phase": "cancelled_before_dispatch"}, input_attempted=False)
                else:
                    manager.store.cancel(request_id)
                raise _Cancelled("agent_command_cancelled")
            if manager.api_grounder is None:
                job.pending_id = request_id
                job.resume_state = None
                job.execution_id = None
                manager._update(job, status="awaiting_grounding", pending_grounding={
                    **pending, "output_schema": GroundingResult.model_json_schema()},
                    grounding_wait={"request_id": request_id,
                        "capture_id": pending["capture"]["capture_id"],
                        "source": manager.configuration.source, "started_ns": perf_counter_ns()},
                    observation={"status": "captured", "capture": pending["capture"]})
            manager._condition.notify_all()
            try:
                while job.resume_state is None and not job.cancelled:
                    manager._condition.wait(timeout=.1)
                    if job.resume_state is None and not job.cancelled:
                        phase = manager.store.get(request_id)["phase"]
                        if phase in {"expired", "cancelled", "absent", "ambiguous", "unsupported", "error"}:
                            job.failure_code = "request_" + phase
                            job.cancelled = True
            finally:
                if manager.api_grounder is None:
                    manager._finish_grounding_wait(job)
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
                attempt_index = manager._begin_dispatch(job, "execute_recognition_plan")
                dispatch_started = True
            receipt = manager.coordinator.execute_local_step(**kwargs, grounding_target=grounding_target)
        except Exception as error:
            if not isinstance(error, _Cancelled):
                manager.store.finish_execution(request_id, execution_id,
                    {"phase": "result_unknown" if dispatch_started else "failed_before_dispatch",
                        "error": {"code": type(error).__name__}},
                    input_attempted=dispatch_started)
                if dispatch_started:
                    manager._record_unknown(job, "execute_recognition_plan", attempt_index)
                else:
                    with manager._condition:
                        manager._update(job, observation={"status": "unavailable", "reason": "failed_before_dispatch"})
            raise
        manager._record_receipt(job, receipt, "execute_recognition_plan", attempt_index)
        manager.store.finish_execution(request_id, execution_id, receipt,
            input_attempted=grounding_target.input_claimed)
        return receipt

    def _execute_memory(self, kwargs, target):
        job = self._job
        manager = job.manager
        if kwargs['request'].get('selection_intent') is not None:
            attempted = []
            def boundary():
                with manager._condition:
                    if job.cancelled:
                        raise _Cancelled('agent_command_cancelled')
                    attempted.append(manager._begin_dispatch(job, 'execute_recognition_plan'))
            try:
                receipt = manager.coordinator.execute_local_step(**kwargs, memory_target=target,
                                                               selection_dispatch_boundary=boundary)
            except Exception:
                if attempted:
                    manager._record_unknown(job, 'execute_recognition_plan', attempted[0])
                raise
            if attempted:
                manager._record_receipt(job, receipt, 'execute_recognition_plan', attempted[0])
            else:
                from app.learning_memory.selection_satisfaction import validate_selection_receipt
                if not validate_selection_receipt(receipt, kwargs['request'], command=job.command, action_executed=False,
                        session_dir=manager.store.session_root, expected_context=job.workflow_bindings):
                    raise AgentCommandError('selection_no_input_proof_invalid')
                with manager._condition:
                    if job.cancelled:
                        raise _Cancelled('agent_command_cancelled')
                    manager._update(job, last_execution={'attempt_index': None, 'operation': 'execute_recognition_plan',
                                    'receipt': deepcopy(receipt)}, observation=deepcopy(receipt['observation']))
            return receipt
        # 与原识图路线共用派发线性化点，取消不得重放可能已经发生的输入。
        with manager._condition:
            if job.cancelled:
                raise _Cancelled("agent_command_cancelled")
            attempt_index = manager._begin_dispatch(job, "execute_recognition_plan")
        try:
            receipt = manager.coordinator.execute_local_step(**kwargs, memory_target=target)
        except Exception:
            manager._record_unknown(job, "execute_recognition_plan", attempt_index)
            raise
        manager._record_receipt(job, receipt, "execute_recognition_plan", attempt_index)
        return receipt


class _Job:
    def __init__(self, manager, command_id, command, target, capabilities, workflow_bindings=None,
                 learning_context=None):
        self.manager = manager
        self.command_id = command_id
        self.command = deepcopy(command)
        self.target = deepcopy(target)
        self.capabilities = capabilities
        self.workflow_bindings = deepcopy(workflow_bindings)
        self.learning_context = deepcopy(learning_context)
        self.pending_id = None
        self.resume_state = None
        self.execution_id = None
        self.cancelled = False
        self.failure_code = None
        self.measurement_changes = {}
        self.thread = None


class AgentCommandJobs:
    """单宿主单活动命令；磁盘记录只供诊断，重启绝不恢复输入。"""

    def __init__(self, coordinator, store, capture_current, configuration, *, api_grounder=None):
        self.coordinator = coordinator
        self.store = store
        self.capture_current = capture_current
        self.configuration = configuration
        self.api_grounder = api_grounder
        if (configuration.source == "external_api") != (api_grounder is not None):
            raise AgentCommandError("api_grounder_configuration_mismatch")
        self._condition = Condition()
        self._jobs = {}
        self._snapshots = {}
        self._active_id = None
        self._closed = False
        self._root = Path(store.session_root) / "agent-commands"

    def _resolve_api(self, job, pending):
        request_id = pending["request_id"]
        with self._condition:
            if job.cancelled:
                self.store.cancel(request_id)
                raise _Cancelled("agent_command_cancelled")
            job.pending_id = request_id
            job.resume_state = None
            job.execution_id = None
            self._update(job, status="running", pending_grounding=None,
                observation={"status": "captured", "capture": pending["capture"]},
                api_request={"request_id": request_id, "phase": "requesting"})
        # 网络等待不持有命令锁，取消和状态查询仍可处理；只发送此步冻结原图。
        response_received = False
        try:
            response = self.api_grounder.ground(request_id=request_id,
                capture=pending["capture"], goal=pending["goal"])
            response_received = True
            provider = response.get("provider")
            self._record_recognition_call(job, request_id, pending["capture"]["capture_id"],
                provider=provider, attempt=provider.get("attempt") if isinstance(provider, dict) else None)
            with self._condition:
                if job.cancelled:
                    raise _Cancelled("agent_command_cancelled")
                state = self.store.resolve(request_id, response["result"])
                self._update(job, api_request={"request_id": request_id, "phase": state["phase"]})
                if state["phase"] != "grounding_ready":
                    raise AgentCommandError("request_" + state["phase"])
                job.execution_id = "api-" + uuid4().hex
                job.resume_state = self.store.claim_execution(request_id, job.execution_id)
        except Exception as error:
            with self._condition:
                if not response_received:
                    attempt = getattr(error, "attempt", None)
                    if attempt is not None:
                        self._record_recognition_call(job, request_id,
                            pending["capture"]["capture_id"], attempt=attempt)
                self.store.cancel(request_id)
                self._update(job, api_request={"request_id": request_id,
                    "phase": "cancelled" if job.cancelled else "failed"})
                if job.cancelled:
                    raise _Cancelled("agent_command_cancelled") from None
                job.failure_code = getattr(error, "code", None) or str(error)
            raise

    def _record_recognition_call(self, job, request_id, capture_id, *, provider=None, attempt=None):
        call = {"request_id": request_id, "capture_id": capture_id}
        call["source"] = "external_api"
        if provider is not None:
            call["provider"] = deepcopy(provider)
        if attempt is not None:
            call["attempt"] = deepcopy(attempt)
        with self._condition:
            calls = self._snapshots[job.command_id].get("recognition_calls", [])
            existing = next((item for item in calls if item.get("request_id") == request_id), None)
            if existing is not None:
                if existing != call:
                    raise AgentCommandError("recognition_attempt_conflict")
                return
            self._update(job, recognition_calls=[*calls, call])

    def _finish_grounding_wait(self, job):
        # 这里只观测交接等待，包含调用方空档；不能推定模型调用数或推理耗时。
        state = self._snapshots[job.command_id]
        wait = state.get("grounding_wait")
        if wait is None:
            return
        status = ("timeout" if job.failure_code == "request_expired" else
                  "cancelled" if job.failure_code == "request_cancelled" or job.cancelled and not job.failure_code else
                  "failure" if job.failure_code or job.resume_state is None else "success")
        handoff = {key: wait[key] for key in ("request_id", "capture_id", "source")}
        handoff["wait"] = {"started_ns": wait["started_ns"], "ended_ns": perf_counter_ns(), "status": status}
        # 合入原有命令状态提交，不为辅助计量新增派发前的独立写盘。
        job.measurement_changes = {"grounding_wait": None,
            "recognition_handoffs": [*state.get("recognition_handoffs", []), handoff]}

    def _path(self, command_id):
        if not isinstance(command_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", command_id):
            raise AgentCommandError("command_id_invalid")
        return self._root / (command_id + ".json")

    def _update(self, job, **changes):
        state = deepcopy(self._snapshots[job.command_id])
        state.update(deepcopy(job.measurement_changes))
        state.update(deepcopy(changes))
        write_json_snapshot(self._path(job.command_id), state)
        self._snapshots[job.command_id] = state
        job.measurement_changes = {}
        return deepcopy(state)

    def _begin_dispatch(self, job, operation):
        with self._condition:
            state = self._snapshots[job.command_id]
            attempts = deepcopy(state["dispatch_attempts"])
            if attempts and attempts[-1]["status"] == "started":
                raise AgentCommandError("dispatch_attempt_unresolved")
            index = len(attempts) + 1
            attempts.append({"index": index, "operation": operation, "status": "started",
                             "previous_action_executed": state["action_executed"], "action_executed": None})
            # 输入前先保存未结算边界；后续明确返回 False 可恢复此前的已知事实。
            self._update(job, dispatch_attempts=attempts, dispatch_in_progress=True,
                action_executed=_merge_action(state["action_executed"], None),
                observation={"status": "unavailable", "reason": "action_in_progress"})
            return index

    def _dispatch_attempt(self, job, operation, attempt_index):
        attempts = deepcopy(self._snapshots[job.command_id]["dispatch_attempts"])
        if (not attempts or attempts[-1]["index"] != attempt_index
                or attempts[-1]["operation"] != operation or attempts[-1]["status"] != "started"):
            raise AgentCommandError("dispatch_attempt_identity_mismatch")
        return attempts

    def _record_unknown(self, job, operation, attempt_index):
        with self._condition:
            attempts = self._dispatch_attempt(job, operation, attempt_index)
            attempts[-1].update(status="unknown", action_executed=None)
            self._update(job, dispatch_attempts=attempts, dispatch_in_progress=False,
                action_executed=_merge_action(attempts[-1]["previous_action_executed"], None),
                observation={"status": "unavailable", "reason": "execution_result_unknown"})

    def _record_receipt(self, job, receipt, operation, attempt_index):
        with self._condition:
            attempts = self._dispatch_attempt(job, operation, attempt_index)
            executed = _receipt_action(receipt, operation)
            attempts[-1].update(status="returned", action_executed=executed)
            # 原回执、动作事实和关闭边界必须在同一原子快照中发布。
            self._update(job, dispatch_attempts=attempts, dispatch_in_progress=False,
                last_execution={"attempt_index": attempt_index, "operation": operation, "receipt": deepcopy(receipt)},
                action_executed=_merge_action(attempts[-1]["previous_action_executed"], executed),
                observation=deepcopy(receipt.get("observation") or
                    {"status": "unavailable", "reason": "post_action_observation_unavailable"}))

    @property
    def active(self):
        with self._condition:
            return self._active_id is not None

    def start(self, command_id, command, target, capabilities, *, workflow_bindings=None,
              learning_context=None):
        path = self._path(command_id)
        capabilities = ClientVisionCapabilities.model_validate(capabilities)
        route = resolve_recognition_route(self.configuration, capabilities)
        if route.status != "eligible":
            request = command.get("request") if isinstance(command, dict) else None
            memory_reference = request.get("target_memory") if isinstance(request, dict) else None
            memory_command = isinstance(command, dict) and (
                command.get("kind") == "input_sequence" or
                (command.get("kind") == "step" and
                 command.get("operation") == "execute_recognition_plan"))
            if route.code != "capability_unknown" or not memory_command:
                raise AgentCommandVisionAdmissionError(command_id, command, self.configuration, capabilities, route.code)
            from app.learning_memory.target_recipe import validate_target_reference
            try:
                validate_target_reference(memory_reference)
            except ValueError:
                raise AgentCommandVisionAdmissionError(command_id, command, self.configuration, capabilities, route.code) from None
        if route.dispatch_owner != "agent_client" and self.configuration.source != "external_api":
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
        from app.execution.form_fill import FormFillRequest
        from app.execution.input_sequence import InputSequenceRequest
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
            job = _Job(self, command_id, frozen, target, capabilities, workflow_bindings,
                       learning_context)
            state = {"contract_version": "agent_command.v1", "command_id": command_id,
                "status": "running", "pending_grounding": None, "progress": None,
                "result": None, "observation": {"status": "not_requested", "capture": None},
                "action_executed": False, "cancel_requested": False,
                "dispatch_in_progress": False,
                "dispatch_attempts": [], "last_execution": None,
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
                    persist=lambda progress: self._progress(job, progress),
                    **({"memory_bindings": job.workflow_bindings}
                       if job.workflow_bindings is not None and command["request"].get("target_memory") is not None else {}))
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
            selection_completed = False
            if command.get('request', {}).get('selection_intent') is not None:
                from app.learning_memory.selection_satisfaction import validate_selection_receipt
                selection_completed = validate_selection_receipt(result, command['request'], command=command,
                    action_executed=action_executed, session_dir=self.store.session_root,
                    expected_context=job.workflow_bindings)
            status = ("completed" if result.get("status", "completed") == "completed"
                and (command["kind"] != "step" or (result.get("response") or {}).get("success") is True
                    and result.get("phase") == "returned" and
                    (selection_completed if command.get('request', {}).get('selection_intent') is not None else action_executed is True))
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
        if self.api_grounder is not None:
            raise AgentCommandError("api_grounding_managed_by_host")
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
