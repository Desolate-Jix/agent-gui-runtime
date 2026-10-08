"""从原执行回执采集并记账当前结果，不派发或重放输入。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from time import perf_counter_ns

from app.desktop_review.external_mapping import canonical_json_bytes
from app.desktop_review.workspace import _write_immutable
from .receipt_adapter import resolve_execution_receipt
from .workflow_program import _id
from .workflow_trial import TrialService, _read, _receipt_state, _execution_identity, _actual_action_executed, _verified_observation
from .workflow_verification import verify_step
from .workflow_metrics import record_rule_observation
from .workflow_execution_strategy import execution_strategy


def verify_trial_step(coordinator, *, session_dir, request, request_id):
    from .workspace import MemoryWorkspace
    from .verification_observation import read_step_observation
    from .workflow_control import validate_request
    validate_request(request)
    if request["action"] != "verify":
        raise ValueError("workflow_verification_action_required")
    _id(request_id, "request_id")
    run_id, execution_id = request["run_id"], request["execution_request_id"]
    session = Path(session_dir).resolve()
    service = getattr(coordinator, "_decision_service", None)
    from .decision_verification import (decision_eligible, decision_binding, adopted_verification,
                                        decision_result_path, validate_original_evidence)
    with MemoryWorkspace(coordinator._memory_library_root) as library:
        trials = TrialService(library, session)
        state = trials.status(run_id)
        if state.get("recovery_settlement"):
            raise ValueError("workflow_runtime_recovery_paused")
        if request_id in state["requests"]:
            matches = [item for item in state["history"] if
                (item.get("verification", {}).get("observations", {}).get("request_id") == request_id
                 or item.get("runtime_settlement_request_id") == request_id)]
            if len(matches) != 1 or matches[0]["execution_request_id"] != execution_id:
                raise ValueError("workflow_trial_idempotency_conflict")
            return state
        pending = state["pending"]
        if pending is None and any(item.get("execution_request_id") == execution_id and (
                item.get("judged_by") == "decision" or item.get("runtime_reason") == "cancel_requested_original_execution_terminal"
                and (session / "workflow-decisions" / (execution_id + ".request.json")).is_file())
                for item in state["history"]):
            return state
        if pending is None or pending["execution_request_id"] != execution_id:
            raise ValueError("workflow_trial_pending_ticket_mismatch")
        if execution_strategy(state) == "steps_only":
            return {"run_id": run_id, "status": "verification_required",
                    "reason": "steps_only_agent_review_required", "execution_strategy": "steps_only",
                    "execution_request_id": execution_id, "automatic_retry_allowed": False}
        program = trials.programs.load(state["workflow_id"], state["program_id"])
        step = next(item for item in program["definition"]["steps"] if item["step_id"] == pending["step_id"])
        image_check = step.get("verification", {}).get("image_check")
        use_decision = decision_eligible(step, service)
        if use_decision:
            cancel = getattr(coordinator, "_cancel_wait", None)
            if (cancel is not None and cancel.is_set()) or (session / "closing.json").exists():
                return {"run_id": run_id, "status": "verification_required", "reason": "workflow_decision_cancelled",
                        "execution_request_id": execution_id, "automatic_retry_allowed": False}
            link = session / "workflow-decisions" / (execution_id + ".request.json")
            if link.is_file():
                previous = _read(link)
                if any(previous.get(key) != value for key, value in {
                        "run_id": run_id, "step_id": step["step_id"], "execution_request_id": execution_id}.items()):
                    raise ValueError("workflow_decision_request_binding_mismatch")
                request_id = _id(previous.get("request_id"), "request_id")
            readiness = getattr(service, "readiness", None)
            if not (session / "workflow-observations" / (request_id + ".json")).is_file() and callable(readiness):
                readiness_state = readiness()
                if readiness_state.get("ready") is not True:
                    use_decision = False
                    if image_check is None:
                        return {"run_id": run_id, "status": "verification_required", "reason": "workflow_decision_not_connected",
                                "execution_request_id": execution_id, "automatic_retry_allowed": False,
                                "decision_status": readiness_state["status"]}
            if use_decision and not link.is_file():
                _write_immutable(link, canonical_json_bytes({"run_id": run_id, "step_id": step["step_id"],
                    "execution_request_id": execution_id, "request_id": request_id}) + b"\n")
        context = trials._receipt_context(state, pending)
        reference_raw, reference_error = None, None
        if image_check is not None:
            from .image_verification import load_reference_image
            try:
                reference_raw = load_reference_image(library, image_check)
            except (OSError, ValueError) as error:
                reference_error = str(error)
    artifact = session / "workflow-observations" / (request_id + ".json")
    if artifact.is_file():
        envelope = _read(artifact)
    else:
        rule, read_spec = step.get("verification"), step.get("read_spec")
        if (rule and rule["kind"] == "agent_judgment" and image_check is None and not use_decision) or not (rule or read_spec):
            return {"run_id": run_id, "status": "verification_required", "reason": "agent_judgment_required",
                    "execution_strategy": execution_strategy(state),
                    "execution_request_id": execution_id, "automatic_retry_allowed": False}
        selector = None if image_check is not None or use_decision else (read_spec or rule)["target"]
        method = ("image_template" if image_check is not None else "decision_capture" if use_decision else read_spec["method"] if read_spec else "uia_value" if rule["kind"] == "field_equals"
                  else "presence" if rule["kind"] in {"target_present", "target_absent"} else "visible_text")
        if method == "agent_read":
            return {"run_id": run_id, "status": "verification_required", "reason": "agent_read_required",
                    "execution_strategy": execution_strategy(state),
                    "execution_request_id": execution_id, "automatic_retry_allowed": False}
        receipt_path = session / "responses" / (execution_id + ".json")
        receipt = _read(receipt_path)
        receipt_hash = sha256(receipt_path.read_bytes()).hexdigest()
        succeeded, terminal, _ = _receipt_state(receipt, receipt_path, execution_id,
            pending["suggested_command"], expected_context=context)
        effective, _ = resolve_execution_receipt(receipt, receipt_path, execution_id)
        identity = _execution_identity(effective)
        if not isinstance(identity, dict) or not succeeded:
            return {"run_id": run_id, "status": "verification_required", "reason": "execution_not_verified",
                    "execution_strategy": execution_strategy(state),
                    "execution_request_id": execution_id, "automatic_retry_allowed": False}
        # 原生观察不持库锁；只核对原回执窗口，不创建新动作或切换任务。
        def observe():
            from app.core.local_input_policy import _local_operator_step_scope
            with _local_operator_step_scope():
                if image_check is not None:
                    from .image_verification import observe_image_check
                    if reference_error is not None:
                        return {"frame": None, "scope_id": "image-check:unavailable", "source": "image_template",
                                "complete": False, "reason": reference_error, "values": {}, "evidence": {"attempts": []}}
                    return observe_image_check(coordinator,
                        target={"handle": identity["handle"], "process_id": identity["process_id"]},
                        identity=identity, check=image_check, reference_raw=reference_raw)
                if use_decision:
                    from .memory_observation import capture_memory_observation
                    frame, native = capture_memory_observation(coordinator, identity["handle"], identity["process_id"], recipe=None)
                    return {"frame": frame, "scope_id": "decision:" + step["step_id"], "source": "decision_capture",
                            "complete": True, "reason": "semantic_check_pending", "values": {}, "evidence": native}
                return read_step_observation(coordinator,
                    target={"handle": identity["handle"], "process_id": identity["process_id"]},
                    selector=selector, method=method)
        started_ns = perf_counter_ns()
        live = coordinator._owner.call(observe)
        ended_ns = perf_counter_ns()
        frame = live["frame"]
        if use_decision and image_check is not None and live.get("reason") == "image_not_matched" and reference_raw is not None:
            from .image_verification import match_image_check
            proof = match_image_check(image_check, reference_raw, frame)
            if (proof.get("reason") == "image_not_matched" and proof.get("matched") is False
                    and proof == live.get("evidence", {}).get("attempts", [None])[-1]):
                live = {**live, "complete": True, "values": {"image_check": proof}}
        if image_check is not None and not live["complete"]:
            failure = {"contract_version": "workflow_image_observation_attempt.v1", "request_id": request_id,
                       "run_id": run_id, "execution_request_id": execution_id, "check": deepcopy(image_check),
                       "source_receipt_sha256": receipt_hash, "live": deepcopy(live),
                       "receipt": {"run_id": run_id, "step_id": step["step_id"], "request_id": request_id,
                                   "execution_request_id": execution_id, "evidence_ref": str(receipt_path.relative_to(session))},
                       "observation": {"evidence_ref": str(artifact.relative_to(session))},
                       "measurement": {"started_ns": started_ns, "ended_ns": ended_ns}}
            _write_immutable(artifact, canonical_json_bytes(failure) + b"\n")
            record_rule_observation(session, failure, "uncertain")
            return {"run_id": run_id, "status": "verification_required", "reason": live["reason"],
                    "execution_request_id": execution_id, "automatic_retry_allowed": False,
                    "evidence_ref": str(artifact.relative_to(session))}
        if frame is None or frame["window_identity"] != identity:
            raise ValueError("workflow_verification_window_identity_changed")
        before = (effective.get("result") or {}).get("capture") or {}
        if use_decision:
            _verified_observation({"observation": frame}, session)
            if frame["capture_id"] == before.get("capture_id"):
                raise ValueError("workflow_decision_capture_stale")
        ids = {"run_id": run_id, "step_id": step["step_id"], "request_id": request_id, "execution_request_id": execution_id}
        actual = False if pending["suggested_command"]["kind"] == "read_text" else _actual_action_executed(effective.get("result"), terminal)
        normalized = {**ids, "status": "completed", "action_executed": actual,
            "pre_capture_id": before.get("capture_id") or execution_id + ":before:" + str(before.get("sha256", "no_input")),
            "post_capture_id": frame["capture_id"], "post_capture_sha256": frame["sha256"],
            "window_identity": identity, "scope_id": live["scope_id"], "evidence_ref": str(receipt_path.relative_to(session))}
        if context is not None:
            normalized["row_selection_proof"] = deepcopy(effective["result"]["row_selection_proof"])
        observation = {**ids, "capture_id": frame["capture_id"], "capture_sha256": frame["sha256"],
            "window_identity": identity, "scope_id": live["scope_id"], "complete": live["complete"],
            "source": live["source"], "values": deepcopy(live["values"]), "reason": live["reason"],
            "evidence_ref": str(artifact.relative_to(session))}
        envelope = {"contract_version": "workflow_observation.v1", "receipt": normalized, "observation": observation,
                    "frame": deepcopy(frame), "source_receipt_sha256": receipt_hash,
                    "terminal_receipt": terminal, "native_evidence": deepcopy(live["evidence"]),
                    "measurement": {"started_ns": started_ns, "ended_ns": ended_ns}}
        _write_immutable(artifact, canonical_json_bytes(envelope) + b"\n")
    if envelope.get("contract_version") == "workflow_image_observation_attempt.v1":
        record_rule_observation(session, envelope, "uncertain")
        return {"run_id": run_id, "status": "verification_required", "reason": envelope["live"]["reason"],
                "execution_request_id": execution_id, "automatic_retry_allowed": False,
                "evidence_ref": str(artifact.relative_to(session))}
    outputs = {key: {"run_id": run_id, "value": value} for key, value in state["outputs"].items()}
    if image_check is not None:
        from .image_verification import match_image_check
        proof = None if reference_raw is None else match_image_check(image_check, reference_raw, envelope["frame"])
        if proof is None or proof != envelope["observation"].get("values", {}).get("image_check"):
            return {"run_id": run_id, "status": "verification_required", "reason": "image_evidence_changed",
                    "execution_request_id": execution_id, "automatic_retry_allowed": False}
    result = verify_step(step, inputs=state["inputs"], outputs=outputs,
                         receipt=envelope["receipt"], observation=envelope["observation"])
    record_rule_observation(session, envelope, result["verdict"])
    if use_decision and result["verdict"] == "uncertain" and result["reason"] == "agent_judgment_required":
        # 判断等待期间不持库锁；回到原结算入口再核对票据、取消态与证据。
        with MemoryWorkspace(coordinator._memory_library_root) as library:
            trials = TrialService(library, session)
            current = trials.status(run_id)
            if current.get("recovery_settlement"):
                raise ValueError("workflow_runtime_recovery_paused")
            if current.get("pending") != pending or current.get("program_id") != state["program_id"]:
                raise ValueError("workflow_trial_pending_ticket_mismatch")
            if current["status"] == "cancel_requested":
                return trials.record_cancelled_execution(run_id, request_id, execution_id)
            validate_original_evidence(trials, current, pending, step, envelope, request_id=request_id)
            cancel = getattr(coordinator, "_cancel_wait", None)
            if (cancel is not None and cancel.is_set()) or (session / "closing.json").exists():
                return {"run_id": run_id, "status": "verification_required", "reason": "workflow_decision_cancelled",
                        "execution_request_id": execution_id, "automatic_retry_allowed": False}
        binding = decision_binding(step, envelope)
        decision_path = decision_result_path(session, request_id)
        if decision_path.is_file():
            saved = _read(decision_path)
            if saved.get("binding") != binding:
                raise ValueError("workflow_decision_request_binding_mismatch")
            decision = saved.get("result")
        else:
            decision = service.evaluate(**binding)
            if not isinstance(decision, dict):
                raise ValueError("workflow_decision_result_invalid")
            _write_immutable(decision_path, canonical_json_bytes({"binding": binding, "result": decision}) + b"\n")
        if not isinstance(decision, dict):
            raise ValueError("workflow_decision_result_invalid")
        with MemoryWorkspace(coordinator._memory_library_root) as library:
            trials = TrialService(library, session)
            current = trials.status(run_id)
            if current.get("recovery_settlement"):
                raise ValueError("workflow_runtime_recovery_paused")
            if current.get("pending") != pending or current.get("program_id") != state["program_id"]:
                raise ValueError("workflow_trial_pending_ticket_mismatch")
            if current["status"] == "cancel_requested":
                return trials.record_cancelled_execution(run_id, request_id, execution_id)
            validate_original_evidence(trials, current, pending, step, envelope, request_id=request_id)
            cancel = getattr(coordinator, "_cancel_wait", None)
            if (cancel is not None and cancel.is_set()) or (session / "closing.json").exists():
                return {"run_id": run_id, "status": "verification_required", "reason": "workflow_decision_cancelled",
                        "execution_request_id": execution_id, "automatic_retry_allowed": False,
                        "decision_advice": deepcopy(decision)}
            if decision.get("adopted") is not True and not service.validate_result(decision, **binding):
                return {"run_id": run_id, "status": "verification_required", "reason": "workflow_decision_result_untrusted",
                        "execution_request_id": execution_id, "automatic_retry_allowed": False}
            if decision.get("adopted") is True:
                try:
                    computed = adopted_verification(step, inputs=current["inputs"], outputs=outputs,
                        envelope=envelope, decision=decision, service=service)
                except ValueError as error:
                    if str(error) != "workflow_decision_success_conditions_require_agent":
                        raise
                else:
                    return trials.record_verified_result(run_id, request_id, execution_id, computed, decision_service=service)
        return {"run_id": run_id, "status": "verification_required", "reason": "agent_judgment_required",
                "execution_strategy": execution_strategy(state), "execution_request_id": execution_id,
                "automatic_retry_allowed": False, "decision_advice": deepcopy(decision)}
    if image_check is not None and result["verdict"] != "success":
        return {"run_id": run_id, "status": "verification_required", "reason": result["reason"],
                "execution_request_id": execution_id, "automatic_retry_allowed": False}
    with MemoryWorkspace(coordinator._memory_library_root) as library:
        return TrialService(library, session).record_verified_result(run_id, request_id, execution_id, result)
