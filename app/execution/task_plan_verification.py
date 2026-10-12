"""核验临时计划的原命令回执；不补执行、不重截图、不推断未知输入。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from time import perf_counter_ns

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from app.learning_memory.receipt_adapter import resolve_execution_receipt
from app.learning_memory.workflow_trial import (
    _actual_action_executed, _execution_identity, _receipt_state, _verified_observation,
)
from .decision_check import decision_frame, service_enabled
from .task_plan_contract import _identifier
from .task_plan_conditions import effective_plan_review_policy, semantic_binding
from .task_plan_review import assess, make_packet, policy_snapshot, review_context, validate_assessment, validate_review
from .task_plan_cancellation import assert_no_queued_plan_cancel
from .task_plan_native_condition import native_mismatch_eligible


def _reference(session, path):
    path = Path(path).resolve(strict=True)
    if not path.is_relative_to(session):
        raise ValueError("task_plan_evidence_outside_session")
    return {"path": path.relative_to(session).as_posix(), "sha256": sha256(path.read_bytes()).hexdigest()}


def _unchanged(session, references):
    for item in references:
        if _reference(session, session / item["path"]) != item:
            raise ValueError("task_plan_original_evidence_changed")


def _save_once(path, value):
    if path.is_file():
        if read_json_snapshot(path) != value:
            raise ValueError("task_plan_verification_artifact_conflict")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_json_snapshot(path, value)


def _native_success(rule, effective, frame):
    result = effective["result"]
    if effective["command"]["kind"] == "input_sequence":
        steps = result.get("steps") or []
        if (not isinstance(steps, list) or not steps or not isinstance(steps[-1], dict)
                or steps[-1].get("name") != "search"):
            return False
        receipt = steps[-1].get("receipt")
        if not isinstance(receipt, dict):
            return False
        observation = receipt.get("observation") or {}
    else:
        observation = result.get("observation") or {}
    if not isinstance(observation, dict):
        return False
    proof = observation.get("condition") or {}
    if (not isinstance(proof, dict) or proof.get("status") != "condition_met" or proof.get("source") != "uia_exact_name"
            or proof.get("expected") != rule["condition"]
            or proof.get("after_sha256") != frame["sha256"]
            or (observation.get("capture") or {}).get("sha256") != frame["sha256"]
            or proof.get("after_capture_rechecked") is not True):
        return False
    samples = proof.get("samples")
    if not isinstance(samples, list) or len(samples) < 3:
        return False
    if not ((proof.get("baseline") or {}).get("status") == "absent"
            or any(item.get("status") == "absent" for item in samples[:-3])):
        return False
    recent = samples[-3:]
    keys = [(s.get("runtime_id"), s.get("bbox"), s.get("target_window_handle"), s.get("process_id")) for s in recent]
    identity = frame["window_identity"]
    if (any(s.get("status") != "matched" for s in recent) or not keys[0][0] or not keys[0][1]
            or any(k != keys[0] for k in keys)
            or keys[0][2:] != (identity["handle"], identity["process_id"])):
        return False
    times = [s.get("elapsed_ms") for s in recent]
    return (all(type(t) in (int, float) for t in times)
            and times[1] - times[0] >= 99 and times[2] >= times[1])


def verify_task_plan_step(backend, *, session_dir, run_id, request_id, execution_id,
                          decision_service=None, review=None, coordinator=None, target_identity=None, api_grounder=None):
    session = Path(session_dir).resolve()
    _identifier(request_id, "request_id")
    _identifier(execution_id, "execution_request_id")
    backend.validate_resume(run_id, None)
    state = backend.status(run_id)
    assert_no_queued_plan_cancel(session, run_id)
    review_path = session / "task-plan-reviews" / (request_id + ".json")
    prior = state.get("verification_results", {}).get(request_id)
    if prior is not None:
        if prior.get("execution_request_id") != execution_id:
            raise ValueError("task_plan_verification_idempotency_conflict")
        if review is not None and (not review_path.is_file() or read_json_snapshot(review_path) != review
                or prior.get("judged_by") != "agent" or prior.get("step_id") != review["step_id"]
                or prior.get("verdict") != review["verdict"] or prior.get("reason") != review["reason"]):
            raise ValueError("task_plan_review_idempotency_conflict")
        if review is None and prior.get("judged_by") == "agent":
            raise ValueError("task_plan_review_idempotency_conflict")
        _unchanged(session, prior["evidence_refs"])
        return backend.record_verified_result(run_id, request_id, execution_id, prior, decision_service=decision_service,
            target_identity=target_identity)
    pending = state.get("pending")
    if pending is None or pending["execution_request_id"] != execution_id:
        raise ValueError("task_plan_pending_ticket_mismatch")
    step = backend.pinned_step(run_id, pending["step_id"])
    source = backend._source(state)
    v2 = source["plan"]["schema_version"] in {"task_plan.v2", "task_plan.v3"}
    semantic = semantic_binding(source["plan"], step)
    condition_snapshot = semantic.get("condition_snapshot")
    policy = policy_snapshot(decision_service) if v2 else {}
    always_main = v2 and effective_plan_review_policy(step["verification"],
        condition_snapshot=condition_snapshot, host_policy=policy,
        host_enabled=service_enabled(decision_service)) == "always_main"
    assessment = None
    observation = None
    observation_reason = None
    video_playback = None
    receipt_path = session / "responses" / (execution_id + ".json")
    receipt = read_json_snapshot(receipt_path)
    references = [_reference(session, receipt_path),
                  _reference(session, session / "commands" / (execution_id + ".json"))]
    succeeded, terminal, _ = _receipt_state(receipt, receipt_path, execution_id, pending["suggested_command"])
    effective, resolved_terminal = resolve_execution_receipt(receipt, receipt_path, execution_id)
    if terminal != resolved_terminal:
        raise ValueError("task_plan_terminal_receipt_changed")
    if terminal is not None:
        references.append(_reference(session, terminal["path"]))
    actual = False if step["action"]["kind"] == "read_text" else _actual_action_executed(effective.get("result"), terminal)
    from app.core.input_sequence_partial import original_input_status
    input_status = original_input_status(effective, pending["suggested_command"], succeeded=succeeded,
        action_executed=actual, target_identity=state["target_identity"])
    result = {"run_id": run_id, "step_id": step["step_id"], "execution_request_id": execution_id,
              "plan_id": state["plan_id"], "plan_sha256": state["plan_sha256"],
              "target_identity": deepcopy(state["target_identity"]), "verdict": "uncertain",
              "judged_by": "runtime", "evidence_refs": references,
              "reason": "original_input_not_verified", "action_executed": actual,
              "original_input_status": input_status}
    # 可信已知失败只停止，保留实际副作用；无终态证明的部分输入仍保留原票据。
    if input_status != "completed":
        from .task_plan_intervention import zero_input_verified
        if (review is None and state.get("recovery_policy") == "intervention_v1" and state["status"] == "pending"
                and actual is False and zero_input_verified(backend, state, pending)):
            _unchanged(session, references)
            return backend.record_pre_dispatch_block(run_id, request_id, execution_id, result)
        if review is not None:
            raise ValueError("task_plan_review_original_input_unverified")
        if input_status == "failed":
            result.update(verdict="failure", reason=("original_focus_partial_failed" if actual is True else "original_input_failed"))
        from .task_plan_review import field_main_handoff
        handoff = field_main_handoff(state, effective, references, session=session,
            service=decision_service, original_status=input_status)
        if handoff is not None:
            result.update(main_handoff=handoff, reason="visual_field_requested_main_review")
            references[:] = handoff["evidence_refs"]
        _unchanged(session, references)
        return backend.record_verified_result(run_id, request_id, execution_id, result, decision_service=decision_service,
            target_identity=target_identity)
    identity = _execution_identity(effective)
    if identity != state["target_identity"]:
        raise ValueError("task_plan_execution_target_mismatch")
    observed = _verified_observation(effective, session)
    capture = effective.get("observation") or (effective.get("result") or {}).get("capture")
    frame = decision_frame({**capture, **observed}, identity, role="after")
    references.append(_reference(session, frame["image_path"]))
    # 后图只能来自原命令；有前图时还必须排除把前图改名当作后图。
    before = (effective.get("result") or {}).get("capture") or {}
    if step["action"]["kind"] != "read_text" and before.get("image_path"):
        before_path = Path(before["image_path"])
        before_path = (before_path if before_path.is_absolute() else session / before_path).resolve()
        if before_path == Path(frame["image_path"]).resolve():
            raise ValueError("task_plan_post_action_capture_missing")
    if review is not None:
        reviewed_packet = None
        if v2:
            reviewed_packet = validate_review(review, state, session)
        if step["verification"]["kind"] in ("video_playback", "dynamic_content"):
            from .video_playback_verification import VideoPlaybackLedger
            ledger = VideoPlaybackLedger(backend, execution_id)
            if ledger.header() is not None:
                if callable(target_identity) and target_identity() != state["target_identity"]:
                    raise ValueError("task_plan_video_window_changed")
                video_playback = ledger.summary()
                references[:] = deepcopy(reviewed_packet["evidence_refs"])
                saved = ledger.last_assessment()
                assessment = saved["result"] if saved else None
                policy = ledger.header()["policy_snapshot"]
        if "wait_policy" in step["verification"]:
            from .task_plan_observation import ObservationLedger
            ledger = ObservationLedger(backend, execution_id)
            if ledger.header() is not None:
                if callable(target_identity) and target_identity() != state["target_identity"]:
                    raise ValueError("task_plan_observation_window_changed")
                observation = ledger.summary()
                references[:] = ledger.artifacts()
                saved = ledger.last_assessment()
                assessment = saved["result"] if saved else None
                policy = ledger.header()["policy_snapshot"]
        if reviewed_packet is not None and reviewed_packet.get("schema") == "review_packet.v3":
            for item in reviewed_packet["artifact_refs"]:
                if item not in references:
                    references.append(deepcopy(item))
        if (review["step_id"] != step["step_id"] or review["evidence_sha256"] != frame["sha256"]
                or state["status"] == "cancel_requested"):
            raise ValueError("task_plan_review_binding_mismatch")
        _save_once(review_path, review)
        references.append(_reference(session, review_path))
        result.update(verdict=review["verdict"], judged_by="agent", reason=review["reason"])
    elif state["status"] == "cancel_requested":
        result.update(verdict="failure", reason="cancel_requested_original_execution_terminal")
        if step["verification"]["kind"] in ("video_playback", "dynamic_content"):
            from .video_playback_verification import VideoPlaybackLedger, _finish
            ledger = VideoPlaybackLedger(backend, execution_id)
            if ledger.header() is not None:
                driven = _finish(ledger, "task_plan_video_cancelled")
                references[:] = driven["refs"]
                video_playback = driven["video_playback"]
    elif step["verification"]["kind"] in ("video_playback", "dynamic_content"):
        from .video_playback_verification import drive_video_playback
        driven = drive_video_playback(backend, state, step, frame,
            {**deepcopy(capture), **deepcopy(observed), **deepcopy(frame)}, references,
            decision_service, coordinator=coordinator, target_reader=target_identity, api_grounder=api_grounder)
        if driven["pending"]:
            return {"status": "verification_required", "observation_pending": True}
        references[:] = driven["refs"]
        video_playback, policy, assessment = driven["video_playback"], driven["policy"], driven["decision"]
        result["reason"] = driven["reason"]
        if driven["local_success"] and not always_main:
            result.update(verdict="success", judged_by="video_playback", reason="video_playback_confirmed")
        elif driven["local_success"]:
            result.update(reason="decision_always_main")
            assessment = {"status": "local_proof", "verdict": "success", "disposition": "review_required",
                "review_scope": "effect_and_plan", "local_proof_complete": True,
                "profile_sha256": policy.get("profile_sha256")}
        elif (driven["valid"] and driven["reason"] == "authenticated_decision" and not always_main
                and assessment.get("adopted") is True and assessment.get("disposition") == "continue"
                and assessment.get("verdict") in {"success", "failure"}):
            result.update(verdict=assessment["verdict"], judged_by="decision", reason="authenticated_decision")
    elif step["verification"]["kind"] == "native_condition" and _native_success(step["verification"], effective, frame):
        if always_main:
            result.update(reason="decision_always_main")
            assessment = {"status": "local_proof", "verdict": "success", "disposition": "review_required",
                "review_scope": "effect_and_plan", "local_proof_complete": True,
                "profile_sha256": policy.get("profile_sha256")}
        else:
            result.update(verdict="success", judged_by="native_condition", reason="declared_native_condition_met")
    elif step["verification"]["kind"] == "native_condition" and always_main:
        result.update(reason="decision_always_main")
    elif step["verification"]["kind"] == "native_condition" and not (
            v2 and service_enabled(decision_service) and native_mismatch_eligible(step["verification"], effective, frame,
                **({"condition_snapshot": condition_snapshot} if condition_snapshot is not None else {}))):
        result.update(reason="native_condition_requires_agent_review")
    else:
        condition = semantic["condition"]
        result.update(reason="agent_judgment_required")
        if v2 and condition and service_enabled(decision_service) and policy.get("contract_version") != "decision_profile.v2":
            result.update(reason="decision_profile_v2_required")
        elif condition and service_enabled(decision_service) and not (session / "closing.json").exists():
            if condition_snapshot is not None:
                current = backend.status(run_id)
                rebuilt = semantic_binding(backend._source(current)["plan"], step)
                if current != state or rebuilt != semantic:
                    raise ValueError("task_plan_condition_dispatch_binding_invalid")
                semantic = rebuilt
                assert_no_queued_plan_cancel(session, run_id)
            binding = {"request_id": "task-decision-" + sha256(execution_id.encode()).hexdigest()[:32],
                       "execution_request_id": execution_id, **semantic, "frames": [frame],
                       "mode": "execution", "phase": "after_action", "run_id": run_id, "step_id": step["step_id"]}
            if v2:
                binding["review_context"] = review_context(source["plan"], step,
                    source_id=state["plan_id"], source_sha256=state["plan_sha256"])
            decision_path = session / "task-plan-decisions" / (execution_id + ".json")
            if v2 and "wait_policy" in step["verification"]:
                from .task_plan_observation import drive_observation
                original_frame = {**deepcopy(capture), **deepcopy(observed), **deepcopy(frame)}
                driven = drive_observation(backend, state, step, frame, original_frame, references,
                    decision_service, coordinator=coordinator, target_reader=target_identity)
                if driven["pending"]:
                    return {"status": "verification_required", "observation_pending": True}
                decision = driven["decision"] or {"reason": driven["reason"]}
                valid_decision = driven["valid"] and driven["reason"] == "authenticated_decision"
                references[:] = driven["refs"]
                observation = driven["observation"]
                policy = driven["policy"]
                observation_reason = driven["reason"]
            elif decision_path.is_file():
                saved = read_json_snapshot(decision_path)
                from .task_result_annotation import task_result_click_action, task_result_decision_binding
                binding = task_result_decision_binding(binding, task_result_click_action(step, effective, frame),
                    saved_binding=saved["binding"])
                if saved["binding"] != binding:
                    raise ValueError("task_plan_decision_binding_changed")
                decision = saved["result"]
                policy = saved.get("policy_snapshot", policy)
                if saved.get("validated") is False:
                    valid_decision = False
                else:
                    decision, valid_decision = validate_assessment(decision_service, decision, binding, v2=v2)
            else:
                from .task_result_annotation import task_result_click_action, task_result_decision_binding
                binding = task_result_decision_binding(binding, task_result_click_action(step, effective, frame))
                started = perf_counter_ns()
                decision, valid_decision = assess(decision_service, binding, v2=v2)
                _save_once(decision_path, {"binding": binding, "result": decision,
                    "validated": valid_decision,
                    **({"policy_snapshot": policy} if v2 else {}),
                    "measurement": {"started_ns": started, "ended_ns": perf_counter_ns()}})
            if observation is None:
                references.append(_reference(session, decision_path))
            assessment = decision
            if (valid_decision and decision.get("adopted") is True
                    and decision.get("verdict") in {"success", "failure"}
                    and (not v2 or decision.get("disposition") == "continue")):
                result.update(verdict=decision["verdict"], judged_by="decision", reason="authenticated_decision")
            else:
                result.update(reason=(decision.get("reason", "decision_policy_requires_agent_review")
                    if valid_decision and v2 and decision.get("status") == "skipped" else
                    "decision_requested_agent_review" if valid_decision and v2
                    and decision.get("disposition") == "review_required" else
                    decision.get("reason", "decision_requires_agent_review")))
                if observation is not None:
                    result["reason"] = observation_reason
    if source["plan"]["schema_version"] == "task_plan.v3" and step["step_id"] == source["plan"]["completion"]["step_id"]:
        from .task_plan_contract import goal_completion_proof
        if (review is None and result["verdict"] == "success"
                and step["verification"] != source["plan"]["completion"]["verification"]):
            # 不同最终条件只交原 Main 只读复核，不再追加输入或隐式付费调用。
            result.update(verdict="uncertain", judged_by="runtime", reason="goal_completion_required")
        result["goal_completion"] = goal_completion_proof(source["plan"], result)
    assert_no_queued_plan_cancel(session, run_id)
    _unchanged(session, references)
    current = backend.status(run_id)
    if current.get("pending") != pending or current["status"] != state["status"]:
        raise ValueError("task_plan_changed_during_verification")
    if (session / "closing.json").exists() and current["status"] != "cancel_requested":
        result.update(verdict="uncertain", judged_by="runtime", reason="session_closing")
    artifact = session / "task-plan-verifications" / (request_id + ".json")
    if observation is not None:
        result["observation"] = observation
    if video_playback is not None:
        result["video_playback"] = video_playback
    _save_once(artifact, {"schema": "task_plan_verification.v1", "frame": frame, "result": result})
    references.append(_reference(session, artifact))
    if v2 and result["verdict"] == "uncertain" and current["status"] != "cancel_requested":
        result["review_packet"] = make_packet(backend, state, step, result, frame,
            assessment=assessment, policy=policy)
    try:
        return backend.record_verified_result(run_id, request_id, execution_id, result, decision_service=decision_service,
            target_identity=target_identity)
    except ValueError as error:
        if video_playback is not None and str(error) == "task_plan_video_budget_expired":
            from .video_playback_verification import VideoPlaybackLedger, now_ns
            ledger = VideoPlaybackLedger(backend, execution_id)
            if not ledger.payloads("adoption_rejected"):
                ledger.append("adoption_rejected", {"reason": "task_plan_video_budget_expired", "rejected_ns": now_ns()})
            references[:] = ledger.artifacts() + [_reference(session, artifact)]
            result.pop("review_packet", None)
            result.update(verdict="uncertain", judged_by="runtime", reason="task_plan_video_budget_expired",
                video_playback=ledger.summary())
            request_id += "-budget-review"
            rejected = session / "task-plan-verifications" / (request_id + ".json")
            _save_once(rejected, {"schema": "task_plan_verification.v1", "frame": frame, "result": result})
            references.append(_reference(session, rejected))
            result["review_packet"] = make_packet(backend, state, step, result, frame, assessment=assessment, policy=policy)
            return backend.record_verified_result(run_id, request_id, execution_id, result,
                decision_service=decision_service, target_identity=target_identity)
        if observation is None or str(error) != "task_plan_observation_adoption_budget_invalid":
            raise
        # 保留迟到候选原件；另存预算拒绝审核，不把认证晚返回记为采用。
        from .task_plan_observation import ObservationLedger, now_ns
        ledger = ObservationLedger(backend, execution_id)
        if not any(event["event"] == "adoption_rejected" for event in ledger.read()):
            ledger.append("adoption_rejected", {"reason": "task_plan_observation_budget_expired",
                "rejected_ns": now_ns()})
        references[:] = ledger.artifacts() + [_reference(session, artifact)]
        result.pop("review_packet", None)
        result.update(verdict="uncertain", judged_by="runtime", reason="task_plan_observation_budget_expired",
            observation=ledger.summary())
        request_id += "-budget-review"
        rejected_artifact = session / "task-plan-verifications" / (request_id + ".json")
        _save_once(rejected_artifact, {"schema": "task_plan_verification.v1", "frame": frame, "result": result})
        references.append(_reference(session, rejected_artifact))
        result["review_packet"] = make_packet(backend, state, step, result, frame,
            assessment=assessment, policy=policy)
        return backend.record_verified_result(run_id, request_id, execution_id, result, decision_service=decision_service,
            target_identity=target_identity)


__all__ = ["verify_task_plan_step"]
