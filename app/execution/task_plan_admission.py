"""临时计划控制面；复用工作流队列与运行器，不建立第二个输入执行器。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import re

from app.core.instant_command_queue import CommandQueueBusy, command_queue_lock
from app.core.json_snapshot import read_json_snapshot
from app.learning_memory.workflow_program import _id
from app.learning_memory.workflow_runner import WorkflowRunner, _run_id, _exclusive
from app.learning_memory.workflow_runtime import WorkflowRuntime, _INPUT_KINDS, _TERMINAL
from .task_plan_backend import TaskPlanBackend, _digest
from .task_plan_contract import validate_task_plan, validate_task_plan_target
from .task_plan_verification import verify_task_plan_step
from .task_plan_review import pending_packet, validate_packet
from .task_plan_cancellation import assert_no_queued_plan_cancel


def validate_task_plan_request(value):
    if not isinstance(value, dict):
        raise ValueError("task_plan_request_invalid")
    action = value.get("action")
    fields = {
        "start": ({"action", "plan"}, {"vision_capabilities", "successor", "recovery_policy"}),
        "recover": ({"action", "run_id", "wait_id", "step_id", "execution_request_id",
            "review_packet_sha256", "evidence_set_sha256", "assessment_round", "recovery_request_id", "command"}, set()),
        "resume_pre_dispatch": ({"action", "run_id", "wait_id", "step_id", "execution_request_id",
            "review_packet_sha256", "evidence_set_sha256", "assessment_round", "reason"}, set()),
        "status": ({"action", "run_id"}, set()),
        "cancel": ({"action", "run_id"}, set()),
        "continue": ({"action", "run_id", "wait_id"}, set()),
        "observe": ({"action", "run_id", "step_id", "execution_request_id", "wait_id",
                     "observation_request_id", "review_packet_sha256", "evidence_set_sha256", "assessment_round"}, set()),
        "review": ({"action", "run_id", "execution_request_id", "step_id", "verdict",
                     "reason", "evidence_sha256"}, {"review_packet_sha256", "evidence_set_sha256", "assessment_round"}),
    }
    if action not in fields:
        raise ValueError("task_plan_control_action_unsupported")
    required, optional = fields[action]
    if not required <= set(value) or set(value) - required - optional:
        missing = sorted(required - set(value))
        unknown = sorted(set(value) - required - optional)
        allowed = sorted(required | optional)
        error = ValueError(f"task_plan_control_fields_invalid: action={action}; "
            f"missing_fields={missing}; unknown_fields={unknown}; allowed_fields={allowed}")
        error.missing_fields = missing
        error.unknown_fields = unknown
        error.allowed_fields = allowed
        raise error
    if action == "start":
        validate_task_plan(value["plan"])
        if value.get("recovery_policy", "legacy") not in {"legacy", "intervention_v1"}:
            raise ValueError("task_plan_recovery_policy_invalid")
        if "successor" in value:
            successor = value["successor"]
            if (value["plan"]["schema_version"] not in {"task_plan.v2", "task_plan.v3"} or not isinstance(successor, dict)
                    or set(successor) != {"successor_request_id", "successor_of", "parent_plan_sha256",
                        "prefix_sha256", "lineage_generation", "reason"}):
                raise ValueError("task_plan_successor_fields_invalid")
            _id(successor["successor_request_id"], "successor_request_id")
            _run_id(successor["successor_of"])
            if (any(not isinstance(successor[key], str) or not re.fullmatch(r"[0-9a-f]{64}", successor[key])
                    for key in ("parent_plan_sha256", "prefix_sha256"))
                    or type(successor["lineage_generation"]) is not int or successor["lineage_generation"] < 0
                    or not isinstance(successor["reason"], str) or not successor["reason"].strip()
                    or len(successor["reason"]) > 4000):
                raise ValueError("task_plan_successor_binding_invalid")
        if "vision_capabilities" in value:
            from app.vision.recognition_source import ClientVisionCapabilities
            ClientVisionCapabilities.model_validate(value["vision_capabilities"])
    else:
        _run_id(value["run_id"])
    for field in ("wait_id", "step_id", "execution_request_id", "observation_request_id", "recovery_request_id"):
        if field in value:
            _id(value[field], field)
    if action == "review":
        if (value["verdict"] not in {"success", "failure"}
                or not isinstance(value["reason"], str) or not value["reason"].strip()
                or len(value["reason"]) > 4000
                or not isinstance(value["evidence_sha256"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", value["evidence_sha256"])):
            raise ValueError("task_plan_review_invalid")
    if action == "recover":
        from .task_plan_intervention import recovery_command
        recovery_command(value["command"])
    if action == "resume_pre_dispatch" and (not isinstance(value["reason"], str)
            or not value["reason"].strip() or len(value["reason"]) > 4000):
        raise ValueError("task_plan_intervention_reason_invalid")
    if action in {"review", "observe", "recover", "resume_pre_dispatch"}:
        packet_fields = {"review_packet_sha256", "evidence_set_sha256", "assessment_round"}
        present = packet_fields.intersection(value)
        if present and (present != packet_fields
                or any(not isinstance(value[key], str) or not re.fullmatch(r"[0-9a-f]{64}", value[key])
                       for key in ("review_packet_sha256", "evidence_set_sha256"))
                or type(value["assessment_round"]) is not int or value["assessment_round"] < 0):
            raise ValueError("task_plan_review_packet_binding_invalid")
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
        if self.agent_jobs is not None:
            self.agent_jobs.field_review_plan_validator = self._field_review_plan_matches
            self.agent_jobs.pre_action_plan_validator = self._pre_action_plan_matches

    def _pre_action_plan_matches(self, execution_id, action_review):
        job = getattr(self.agent_jobs, '_jobs', {}).get(execution_id)
        def rejected(reason):
            if job is not None:
                job.pre_action_binding_failure = reason
            return False
        failure = self._field_review_plan_failure(execution_id, action_review, retry_queue_busy=True)
        if failure is not None:
            return rejected(failure)
        # Original command and this read/control are allowed; competing or unknown
        # queued work cannot inherit Main's approval.
        try:
            for path in (self.session / 'commands').glob('*.json'):
                if path.stem in {execution_id, self._control_id}:
                    continue
                command = read_json_snapshot(path)
                response_path = self.session / 'responses' / path.name
                if response_path.is_file():
                    if command.get('kind') in {'step', 'input_sequence', 'form_fill', 'grounding_execute'}:
                        from app.learning_memory.workflow_trial import _receipt_state, _actual_action_executed
                        from app.learning_memory.receipt_adapter import resolve_execution_receipt
                        receipt = read_json_snapshot(response_path)
                        succeeded, terminal, _ = _receipt_state(receipt, response_path, path.stem, command)
                        effective, resolved = resolve_execution_receipt(receipt, response_path, path.stem)
                        if terminal != resolved or not succeeded and _actual_action_executed(effective.get('result'), terminal) is not False:
                            return rejected('prior_input_unsettled:' + path.stem)
                    continue
                live = getattr(job, 'pre_action_review_state', None)
                from .main_pre_action_approval import digest
                if live is not None and live['accepted_controls'].get(path.stem) == digest(command):
                    continue
                from .task_plan_pre_action_review import queued_pre_action_control
                if queued_pre_action_control(live, command, self.runner.status(action_review['run_id']).get('wait')):
                    continue
                if (command.get('kind') == 'agent_command_status'
                        or command.get('kind') == 'task_plan' and (command.get('request') or {}).get('action') == 'status'):
                    continue
                return rejected('queued_command_not_bound:' + path.stem)
            for path in (self.session / 'agent-commands').glob('*.json'):
                if path.stem != execution_id and read_json_snapshot(path).get('status') not in _TERMINAL:
                    return rejected('other_agent_job_active:' + path.stem)
            if job is not None:
                job.pre_action_binding_failure = None
            return True
        except (OSError, ValueError, TypeError) as error:
            return rejected('queue_validation_error:' + type(error).__name__)

    def _field_review_plan_matches(self, execution_id, action_review):
        return self._field_review_plan_failure(execution_id, action_review) is None

    def _field_review_plan_failure(self, execution_id, action_review, *, retry_queue_busy=False):
        # 只有真实原计划的待处理命令可暂停；自声明上下文不能创建无人可审核的等待。
        if not isinstance(action_review, dict):
            return 'action_review_context_invalid'
        if (self.session / "closing.json").exists():
            return 'session_closing'
        try:
            state = self.backend.status(action_review["run_id"])
            pending = state.get("pending")
            if state.get('status') != 'pending':
                return 'plan_not_pending:' + str(state.get('status'))
            if not pending:
                return 'pending_ticket_missing'
            if pending['execution_request_id'] != execution_id:
                return 'execution_id_mismatch'
            if pending['step_id'] != action_review.get('step_id'):
                return 'step_id_mismatch'
            if pending['suggested_command'].get('action_review') != action_review:
                return 'action_review_context_mismatch'
            self.backend.validate_resume(state["run_id"], None)
            source = self.backend._source(state)
            original = read_json_snapshot(self.session / "commands" / (execution_id + ".json"))
            assert_no_queued_plan_cancel(self.session, state["run_id"])
            if source['plan'] != action_review.get('plan'):
                return 'frozen_plan_mismatch'
            if original != pending['suggested_command']:
                return 'original_command_mismatch'
            return None
        except CommandQueueBusy as error:
            # A queued cancel inherits this exception: it must still revoke the
            # capability. Only actual lock contention may be rechecked later.
            if retry_queue_busy and type(error) is CommandQueueBusy:
                raise
            return 'plan_validation_error:' + type(error).__name__
        except (KeyError, ValueError, OSError) as error:
            return 'plan_validation_error:' + type(error).__name__

    def _enqueue(self, execution_id, command):
        run_id = self.runner._active_run()
        if run_id is None:
            raise ValueError("task_plan_active_run_missing")
        state = self.backend.status(run_id)
        assert_no_queued_plan_cancel(self.session, run_id,
            ignore_request_ids=(self._control_id,) if self._control_id else ())
        if validate_task_plan_target(self._target_identity()) != state["target_identity"]:
            raise ValueError("task_plan_target_changed_before_dispatch")
        self.reviewed_runtime._admit_input(execution_id, command)
        super()._enqueue(execution_id, command)

    def _verify(self, run_id, request_id, execution_id):
        if self.backend.status(run_id)["status"] == "cancel_requested":
            request_id = "task-cancel-" + sha256((run_id + execution_id).encode()).hexdigest()[:32]
        try:
            return verify_task_plan_step(self.backend, session_dir=self.session, run_id=run_id,
                request_id=request_id, execution_id=execution_id,
                decision_service=getattr(self.coordinator, "_decision_service", None),
                coordinator=self.coordinator, target_identity=self._target_identity,
                api_grounder=getattr(self.agent_jobs, "api_grounder", None),
                grounding_prefetch=getattr(self.agent_jobs, "task_grounding_prefetch", None))
        except Exception as error:
            prefetch = getattr(self.agent_jobs, "task_grounding_prefetch", None)
            if prefetch is not None:
                prefetch.discard("verification_interrupted", run_id=run_id)
            from .task_plan_cancellation import TaskPlanCancelPending
            if not isinstance(error, TaskPlanCancelPending):
                from .task_plan_observation import abort_observation
                abort_observation(self.backend, execution_id, error)
                from .video_playback_verification import abort_video_playback
                abort_video_playback(self.backend, execution_id, error)
            raise

    def _remember_active(self, snapshot):
        snapshot = self._review_snapshot(snapshot)
        if (snapshot.get("field_review_pending_settlement") is True
                or snapshot.get('pre_action_review_pending_settlement') is True):
            self._enabled_run = snapshot["run_id"]
            return snapshot
        if snapshot.get("observation_pending") is True and snapshot.get("status") != "cancel_requested":
            self._enabled_run = snapshot["run_id"]
            return snapshot
        if (snapshot.get("status") == "cancel_requested"
                and snapshot.get("wait_reason") == "verification_required"
                and snapshot.get("runner_state") != "cancel_requested"):
            error = (snapshot.get("wait") or {}).get("error") or {}
            # 原审核等待上的取消先结算原票据；结算后仍未知才停止自动轮询。
            if error.get("message") != "task_plan_changed_during_verification":
                self._enabled_run = None
                return snapshot
        return super()._remember_active(snapshot)

    def _review_snapshot(self, snapshot):
        value = deepcopy(snapshot)
        value["prefix_sha256"] = self.backend.prefix_sha256(value["run_id"])
        from .task_plan_pre_action_review import project_pre_action_review
        pre_action = project_pre_action_review(self, value)
        if pre_action is not None:
            return pre_action
        from .task_plan_field_review import project_field_review
        field_review = project_field_review(self, value)
        if field_review is not None:
            return field_review
        from .task_plan_observation import projection
        observed = projection(self.backend, value)
        if observed is None:
            from .video_playback_verification import projection as video_projection
            observed = video_projection(self.backend, value)
        if observed is not None:
            value.update(observed)
        packet = pending_packet(value)
        if packet is not None and value.get("wait_reason") == "verification_required":
            validate_packet(packet, value, self.session)
            if packet["wait_id"] != value["wait"]["wait_id"]:
                raise ValueError("task_plan_review_packet_wait_mismatch")
            value["review_packet"] = packet
            value["review_required"] = True
        handoffs = [row["main_handoff"] for row in value.get("verification_results", {}).values()
            if row.get("main_handoff")]
        if handoffs:
            # 原运行仍按真实输入结算；该摘要仅要求 Main 检查，不是继续许可。
            value["main_handoff"] = deepcopy(handoffs[-1])
            value["review_required"] = True
        from .task_plan_manual_observation import manual_observation_status
        value.update(manual_observation_status(self.backend, value))
        from .task_plan_review import caller_controls
        controls = caller_controls(value)
        if controls:
            value["caller_controls"] = controls
        return value

    def _successor(self, request):
        plan, successor = request["plan"], request["successor"]
        target = self.backend.status(successor["successor_of"])["target_identity"]
        prior = self.backend.successor_lookup(plan, target, successor, vision_capabilities=request.get("vision_capabilities"),
            recovery_policy=request.get("recovery_policy", "intervention_v1" if request["plan"]["schema_version"] == "task_plan.v3" else "legacy"))
        if prior is not None:
            state = self.runner._load(prior["run_id"])
            if state is not None:
                return self._review_snapshot(self.runner.status(prior["run_id"]))
        with command_queue_lock(self.session):
            self.reviewed_runtime._admit_input(self._control_id, {"kind": "task_plan", "request": request})
            parent = self.runner.status(successor["successor_of"])
            state = self.runner._load(successor["successor_of"])
            if (parent["status"] not in _TERMINAL or parent["runner_state"] not in _TERMINAL
                    or parent.get("pending") is not None or state.get("ticket") is not None):
                raise ValueError("task_plan_successor_parent_not_terminal")
            for path in (self.session / "commands").glob("*.json"):
                if path.stem == self._control_id:
                    continue
                command = read_json_snapshot(path)
                if not (self.session / "responses" / path.name).is_file():
                    raise ValueError("task_plan_successor_queue_not_quiescent")
                if command.get("kind") in _INPUT_KINDS or command.get("kind") == "read_text":
                    result = self._read_result(path.stem)
                    if result["status"] not in {"completed", "failed", "cancelled"}:
                        raise ValueError("task_plan_successor_queue_not_quiescent")
                    if command.get("kind") in {"step", "input_sequence", "form_fill", "grounding_execute"}:
                        from app.learning_memory.receipt_adapter import resolve_execution_receipt
                        from app.learning_memory.workflow_trial import _actual_action_executed, _receipt_state
                        receipt_path = self.session / "responses" / path.name
                        receipt = read_json_snapshot(receipt_path)
                        succeeded, terminal, _ = _receipt_state(receipt, receipt_path, path.stem, command)
                        effective, _ = resolve_execution_receipt(receipt, receipt_path, path.stem)
                        if not succeeded and _actual_action_executed(effective.get("result"), terminal) is not False:
                            raise ValueError("task_plan_successor_original_input_not_quiescent")
            for path in (self.session / "agent-commands").glob("*.json"):
                if read_json_snapshot(path).get("status") not in _TERMINAL:
                    raise ValueError("task_plan_successor_agent_job_not_quiescent")
            target = validate_task_plan_target(self._target_identity())
            child = self.backend.start_successor(plan, target, successor, transport_request_id=self._control_id,
                vision_capabilities=request.get("vision_capabilities"),
            recovery_policy=request.get("recovery_policy", "intervention_v1" if request["plan"]["schema_version"] == "task_plan.v3" else "legacy"))
        kwargs = {"vision_capabilities": request["vision_capabilities"]} if "vision_capabilities" in request else {}
        return self._remember_active(self.runner.start(child["run_id"], successor["successor_request_id"], "until_wait", **kwargs))

    def _admit_input(self, request_id, command):
        run_id = self.runner._active_run()
        if run_id is None:
            if any(self.backend.status(path.stem)["status"] not in _TERMINAL
                    for path in self.backend.root.glob("trial-*.json")):
                raise ValueError("task_plan_run_active: persisted admission owns input")
            if any(value.get("status") == "reserved" for value in self.backend._lineage()["requests"].values()):
                raise ValueError("task_plan_run_active: successor admission requires reconciliation")
            return
        state = self.runner._load(run_id)
        if state is None:
            raise ValueError("task_plan_active_state_missing")
        if state["runner_state"] in _TERMINAL:
            active = [self.backend.status(path.stem) for path in self.backend.root.glob("trial-*.json")]
            if (any(value["status"] not in _TERMINAL for value in active)
                    or any(value.get("status") == "reserved" for value in self.backend._lineage()["requests"].values())):
                raise ValueError("task_plan_run_active: successor admission owns pending input")
            return
        ticket = state.get("ticket")
        if (ticket and ticket["execution_request_id"] == request_id
                and ticket["suggested_command"] == command):
            if validate_task_plan_target(self._target_identity()) != self.backend.status(run_id)["target_identity"]:
                raise ValueError("task_plan_target_changed_before_execution")
            return
        trial = self.backend.status(run_id)
        permit = trial.get("intervention_recovery")
        if permit and permit["recovery_request_id"] == request_id and permit["command"] == command:
            from .task_plan_intervention import checked_block, assert_queue_quiet
            checked_block(self.backend, trial, permit["request"])
            if validate_task_plan_target(self._target_identity()) != trial["target_identity"]:
                raise ValueError("task_plan_recovery_target_changed")
            assert_queue_quiet(self, ignore=(request_id,))
            self.backend.consume_recovery(run_id, request_id, command)
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

    def _intervention_control(self, request, request_id):
        from .task_plan_intervention import assert_queue_quiet, checked_block
        run_id = request["run_id"]
        if request["action"] == "recover" and request["recovery_request_id"] == request_id:
            raise ValueError("task_plan_recovery_request_id_must_be_independent")
        if request["action"] == "resume_pre_dispatch":
            trial = self.backend.status(run_id)
            if request_id not in trial.get("intervention_resumes", {}):
                state = self.runner._load(run_id)
                if not state or not state.get("wait") or state["wait"]["wait_id"] != request["wait_id"]:
                    raise ValueError("task_plan_intervention_wait_id_mismatch")
                assert_no_queued_plan_cancel(self.session, run_id, ignore_request_ids=(request_id,))
                if validate_task_plan_target(self._target_identity()) != trial["target_identity"]:
                    raise ValueError("task_plan_recovery_target_changed")
                with command_queue_lock(self.session):
                    assert_queue_quiet(self, ignore=(request_id,))
            return self._remember_active(self.runner.resume_pre_dispatch(run_id, request_id, request["wait_id"], request))
        # 与取消共用运行器锁；队列锁只覆盖检查，原 enqueue 自行再次加锁。
        with _exclusive(self.runner.lock_path):
            trial = self.backend.status(run_id)
            state = self.runner._load(run_id)
            if (state is None or state.get("cancel_request_id") or not state.get("wait")
                    or state["wait"]["wait_id"] != request["wait_id"]):
                raise ValueError("task_plan_recovery_intervention_wait_invalid")
            checked_block(self.backend, trial, request)
            assert_no_queued_plan_cancel(self.session, run_id, ignore_request_ids=(request_id,))
            if validate_task_plan_target(self._target_identity()) != trial["target_identity"]:
                raise ValueError("task_plan_recovery_target_changed")
            controls = state.setdefault("control_requests", {})
            digest = _digest({"kind": "task_plan", "request": request})
            prior_control = controls.get(request_id)
            if prior_control is not None and prior_control.get("command_sha256") != digest:
                raise ValueError("workflow_runner_control_conflict")
            if self.requires_client_vision and "vision_capabilities" not in request["command"]:
                raise ValueError("task_plan_recovery_client_vision_capabilities_required")
            if prior_control is None:
                controls[request_id] = {"schema": "workflow_runner_control.v1", "command_sha256": digest}
                self.runner._save(state)
            prior = trial.get("intervention_recovery")
            recovery_id = request["recovery_request_id"]
            if recovery_id in controls or recovery_id in trial["verification_requests"] or recovery_id in trial["prepare_requests"]:
                raise ValueError("task_plan_recovery_request_id_already_used")
            if prior is not None:
                permit = self.backend.permit_recovery(run_id, request_id, request)
                if (self.session / "commands" / (recovery_id + ".json")).is_file():
                    if read_json_snapshot(self.session / "commands" / (recovery_id + ".json")) != permit["command"]:
                        raise ValueError("task_plan_recovery_command_changed")
                    return self._review_snapshot(self.runner._snapshot(state, trial=trial))
            else:
                if (self.session / "commands" / (recovery_id + ".json")).exists() or (self.session / "responses" / (recovery_id + ".json")).exists():
                    raise ValueError("task_plan_recovery_request_id_already_used")
                with command_queue_lock(self.session):
                    assert_queue_quiet(self, ignore=(request_id,))
                permit = self.backend.permit_recovery(run_id, request_id, request)
            # 使用既有队列，实际执行仍由宿主原 owner、分类与动作 API 授权。
            self._enqueue(permit["recovery_request_id"], permit["command"])
            return self._review_snapshot(self.runner._snapshot(state))

    def control(self, request, request_id):
        request = validate_task_plan_request(request)
        _id(request_id, "request_id")
        action = request["action"]
        if action in {"start", "cancel", "review", "recover", "resume_pre_dispatch"}:
            prefetch = getattr(self.agent_jobs, "task_grounding_prefetch", None)
            if prefetch is not None:
                prefetch.discard("control_" + action, run_id=request.get("run_id"))
        self._control_id = request_id
        try:
            if action == "start":
                if (self.requires_client_vision and "vision_capabilities" not in request
                        and any(step["action"]["kind"] in {"click", "input_sequence"}
                                for step in request["plan"]["steps"])):
                    raise ValueError("task_plan_client_vision_capabilities_required")
                if "successor" in request:
                    return self._successor(request)
                self.reviewed_runtime._admit_input(request_id, {"kind": "task_plan", "request": request})
                run_id = "trial-" + _digest([str(self.session), request_id])
                def prepare_trial():
                    self.backend.start(request["plan"], validate_task_plan_target(self._target_identity()), request_id,
                        recovery_policy=request.get("recovery_policy", "intervention_v1" if request["plan"]["schema_version"] == "task_plan.v3" else "legacy"))
                kwargs = {"vision_capabilities": request["vision_capabilities"]} if "vision_capabilities" in request else {}
                return self._remember_active(self.runner.start(run_id, request_id, "until_wait",
                    _prepare_trial=prepare_trial, **kwargs))
            run_id = request["run_id"]
            if action in {"recover", "resume_pre_dispatch"}:
                return self._intervention_control(request, request_id)
            if action == "status":
                return self._review_snapshot(self.runner.status(run_id))
            if action == "observe":
                from .task_plan_manual_observation import observe_task_plan
                observation = observe_task_plan(self, request)
                snapshot = self._review_snapshot(self.runner.status(run_id))
                snapshot["manual_observation"] = observation
                return snapshot
            if action == "cancel":
                snapshot = self.runner.cancel(run_id, request_id)
                pending = snapshot.get("pending")
                recovery = snapshot.get("intervention_recovery")
                execution_ids = ([pending["execution_request_id"]] if pending else [])
                if recovery:
                    execution_ids.append(recovery["recovery_request_id"])
                if self.agent_jobs is not None:
                    for execution_id in execution_ids:
                        path = self.session / "agent-commands" / (execution_id + ".json")
                        if path.is_file() and read_json_snapshot(path).get("status") not in _TERMINAL:
                            self.agent_jobs.cancel(execution_id)
                return self._remember_active(snapshot)
            if action == "review":
                snapshot = self.runner.status(run_id)
                from .task_plan_pre_action_review import control_pre_action_review
                pre_action = control_pre_action_review(self, snapshot, request, request_id)
                if pre_action is not None:
                    return pre_action
                from .task_plan_field_review import control_field_review
                field_result = control_field_review(self, snapshot, request, request_id)
                if field_result is not None:
                    return field_result
                source = self.backend._source(self.backend.status(run_id))
                if source["plan"]["schema_version"] == "task_plan.v1" and any(key in request for key in
                        ("review_packet_sha256", "evidence_set_sha256", "assessment_round")):
                    raise ValueError("task_plan_v1_review_fields_invalid")
                if (snapshot.get("wait_reason") != "verification_required"
                        and request_id not in snapshot.get("verification_results", {})):
                    raise ValueError("task_plan_review_requires_verification_wait")
                verify_task_plan_step(self.backend, session_dir=self.session, run_id=run_id,
                    request_id=request_id, execution_id=request["execution_request_id"], review=request,
                    coordinator=self.coordinator, target_identity=self._target_identity)
                # 审核只结算原票据；调用方用原 wait_id 明确继续，避免状态查询产生输入。
                return self._review_snapshot(self.runner.status(run_id))
            from .task_plan_field_review import control_field_review
            from .task_plan_pre_action_review import control_pre_action_review
            pre_action = control_pre_action_review(self, self.runner.status(run_id), request, request_id)
            if pre_action is not None:
                return pre_action
            field_result = control_field_review(self, self.runner.status(run_id), request, request_id)
            if field_result is not None:
                return field_result
            return self._remember_active(self.runner.resume(run_id, request_id, request["wait_id"]))
        finally:
            self._control_id = None

    def stop(self):
        prefetch = getattr(self.agent_jobs, "task_grounding_prefetch", None)
        if prefetch is not None:
            prefetch.discard("runtime_stopped")
        super().stop()


__all__ = ["TaskPlanRuntime", "validate_task_plan_request"]
