"""早图非成功只补原渲染宽限一次；复用原观察账本，不重派输入。"""
from copy import deepcopy
from hashlib import sha256
from math import isfinite
from pathlib import Path

from app.core.json_snapshot import read_json_snapshot
from app.learning_memory.receipt_adapter import resolve_execution_receipt
from .task_plan_conditions import semantic_binding
from .task_plan_review import assess, digest, policy_snapshot, review_context, validate_assessment
from . import task_plan_observation as observation


def _sequence_submit_receipt(effective, frame, review, step):
    """外层早图只接受同一完成序列最后一次真实视觉 Enter 子回执。"""
    from app.core.input_sequence_partial import original_input_status
    from .input_sequence import _completed_visual_submit
    from .decision_check import decision_frame
    from .task_plan_contract import resolve_action_text
    invalid = "task_plan_adaptive_grace_binding_invalid"
    command, result = effective.get("command") or {}, effective.get("result") or {}
    rows = result.get("steps")
    action, request = step.get("action") or {}, command.get("request") or {}
    if (effective.get("status") != "returned" or command.get("field_evidence_mode") != "visual"
            or result.get("contract_version") != "input_sequence_v1" or result.get("status") != "completed"
            or result.get("phase") != "returned" or result.get("evidence_kind") != "visual"
            or action.get("kind") != "input_sequence" or action.get("submit_search") is not True
            or action.get("clear_existing", True) is not True
            or request.get("submit_search") is not True or request.get("clear_existing") is not True
            or action.get("field_goal") != request.get("field_goal")
            or resolve_action_text(action.get("text"), review["plan"]["inputs"]) != request.get("text")
            or not isinstance(rows, list) or len(rows) != 2 or not isinstance(rows[-1], dict)
            or rows[-1].get("name") != "search" or rows[-1].get("operation") != "execute_recognition_plan"
            or original_input_status(effective, command, succeeded=True,
                action_executed=result.get("action_executed"), target_identity=frame["window_identity"]) != "completed"):
        raise ValueError(invalid)
    local = rows[-1]["receipt"]
    expected = {"schema": "input_sequence_submit_observation.v1", "sequence_id": result["sequence_id"],
        "substep_index": len(rows) - 1, "execution_request_id": review.get("attempt_id"),
        "local_step_id": local["step_id"], "receipt_sha256": digest(local)}
    after = local.get("observation") or {}
    capture = after.get("capture") or {}
    observed = effective.get("observation") or {}
    marker = result.get("adaptive_submit")
    rect = (local.get("target_window_geometry") or {}).get("rect")
    if (not isinstance(marker, dict) or type(marker.get("substep_index")) is not int or marker != expected
            or _completed_visual_submit(local, review.get("attempt_id")) is None
            or result.get("observation") != after
            or capture.get("window_rect") != rect
            or capture.get("window_size") != {"width": rect[2] - rect[0], "height": rect[3] - rect[1]}
            or any(capture.get(key) != observed.get(key) for key in ("capture_id", "sha256", "image_path", "window_rect"))
            or decision_frame(capture, frame["window_identity"], role="after") != frame):
        raise ValueError(invalid)
    return local


def adaptive_grace(effective, frame):
    result = effective.get("result") or {}
    after = result.get("observation") or {}
    capture = after.get("capture") or {}
    value = after.get("adaptive_wait")
    if "adaptive_wait" not in after and capture.get("observation_stage") != "after_transition_observation":
        return None
    if not isinstance(value, dict) or value.get("schema") != "adaptive_observation.v1":
        raise ValueError("task_plan_adaptive_grace_binding_invalid")
    command = effective.get("command") or {}
    review = command.get("action_review") or {}
    request = command.get("request") or {}
    reviewed_steps = [item for item in (review.get("plan") or {}).get("steps", []) if item.get("step_id") == review.get("step_id")]
    sequence = command.get("kind") == "input_sequence"
    if sequence:
        if len(reviewed_steps) != 1:
            raise ValueError("task_plan_adaptive_grace_binding_invalid")
        result = _sequence_submit_receipt(effective, frame, review, reviewed_steps[0])
        after = result.get("observation") or {}
        capture, value = after.get("capture") or {}, after.get("adaptive_wait")
    samples = value.get("samples")
    start, deadline, budget = value.get("started_ns"), value.get("deadline_ns"), value.get("budget_ms")
    elapsed = value.get("elapsed_ms")
    if (result.get("contract_version") != "local_direct_step_v1" or result.get("phase") != "returned"
            or not sequence and (command.get("kind") != "step" or command.get("operation") != "execute_recognition_plan")
            or command.get("observation_wait_ms") is not None or command.get("observation_condition") is not None
            or review.get("schema") != "action_review_context.v1"
            or (review.get("plan") or {}).get("schema_version") != "task_plan.v3"
            or len(reviewed_steps) != 1 or reviewed_steps[0]["action"]["kind"] != ("input_sequence" if sequence else "click")
            or reviewed_steps[0]["verification"]["kind"] != "agent_judgment"
            or "wait_policy" in reviewed_steps[0]["verification"]
            or any(request.get(key) is not None for key in ("capture_roi", "target_memory", "selection_intent"))
            or after.get("status") != "captured" or after.get("source") != "post_action"
            or after.get("authorizes_action") is not False or after.get("render_grace_ms") != 2000
            or type(value.get("early")) is not bool
            or value.get("reason") not in {"changed_then_stable", "budget_exhausted"}
            or value["early"] and value.get("reason") != "changed_then_stable"
            or not isinstance(value.get("clock_id"), str) or not value["clock_id"]
            or type(start) is not int or start < 0
            or type(deadline) is not int or type(budget) is not int or budget != 2000
            or type(elapsed) not in (int, float) or not isfinite(elapsed) or elapsed < 400
            or (elapsed >= budget if value["early"] else elapsed < budget)
            or deadline - start != budget * 1_000_000 or value.get("effect_verified") is not False
            or value.get("authorizes_action") is not False or value.get("automatic_retry_allowed") is not False
            or not isinstance(samples, list) or not samples or not isinstance(samples[-1], dict)
            or samples[-1].get("sha256") != frame["sha256"] or capture.get("sha256") != frame["sha256"]
            or samples[-1].get("image_path") != capture.get("image_path")):
        raise ValueError("task_plan_adaptive_grace_binding_invalid")
    if value["early"] is False:
        return None
    if value["clock_id"] != observation.CLOCK_ID:
        raise ValueError("task_plan_adaptive_grace_clock_changed")
    return {key: deepcopy(value[key]) for key in ("clock_id", "started_ns", "deadline_ns", "budget_ms")}


def semantic_nonpass(value, valid):
    review = value.get("ordinary_review") or {}
    return (valid and value.get("status") == "completed" and value.get("verdict") in {"failure", "uncertain"}
            and (not review or review.get("status") == "completed"))


def _binding(backend, state, step, frames, *, final, effective=None, original_frame=None):
    source = backend._source(state)
    execution_id = state["pending"]["execution_request_id"]
    # 末帧仍是这次原输入之后的当前图；独立观察原件的角色在账本中保持不变。
    frames = [{**deepcopy(item), "role": "after"} for item in frames] if final else deepcopy(frames)
    binding = {"request_id": "task-decision-" + sha256(execution_id.encode()).hexdigest()[:32] + ("-grace-final" if final else ""),
        "execution_request_id": execution_id, **semantic_binding(source["plan"], step), "frames": frames,
        "mode": "execution", "phase": "after_action", "run_id": state["run_id"], "step_id": step["step_id"],
        "review_context": review_context(source["plan"], step, source_id=state["plan_id"], source_sha256=state["plan_sha256"])}
    if final:
        from .task_result_annotation import task_result_followup_click_action, task_result_decision_binding
        binding = task_result_decision_binding(binding,
            task_result_followup_click_action(step, effective, original_frame, frames[0]))
    return binding


def _header_guard(backend, state, ledger, frame, effective, service, target_reader):
    header = ledger.header()
    grace = adaptive_grace(effective, frame)
    receipt_ref = observation.reference(backend.session, backend.session / "responses" / (state["pending"]["execution_request_id"] + ".json"))
    source = backend._source(state)
    step = backend.pinned_step(state["run_id"], state["pending"]["step_id"])
    review = (effective.get("command") or {}).get("action_review") or {}
    if (grace is None or header.get("mode") != "adaptive_grace" or header.get("grace") != grace
            or source["plan"]["schema_version"] != "task_plan.v3" or step["action"]["kind"] not in {"click", "input_sequence"}
            or "wait_policy" in step["verification"] or review.get("plan") != source["plan"]
            or review.get("run_id") != state["run_id"] or review.get("step_id") != step["step_id"]
            or review.get("attempt_id") != state["pending"]["execution_request_id"]
            or header.get("clock_id") != grace["clock_id"] or header.get("started_ns") != grace["started_ns"]
            or header.get("after") != frame or header.get("original_receipt_sha256") != receipt_ref["sha256"]
            or header.get("run_id") != state["run_id"] or header.get("step_id") != state["pending"]["step_id"]
            or header.get("execution_request_id") != state["pending"]["execution_request_id"]
            or header.get("session_directory") != str(backend.session)
            or header.get("initial_assessment_ref") != observation.reference(backend.session,
                backend.session / "task-plan-decisions" / (state["pending"]["execution_request_id"] + ".json"))):
        raise ValueError("task_plan_adaptive_grace_binding_invalid")
    return observation._guard(backend, state, ledger, service, target_reader, allow_expired=True)


def complete_adaptive_grace(backend, state, step, frame, original_frame, refs, service, *,
                            coordinator, target_reader, effective, initial_path):
    execution_id = state["pending"]["execution_request_id"]
    ledger = observation.ObservationLedger(backend, execution_id)
    if ledger.header() is None:
        grace = adaptive_grace(effective, frame)
        source_ref = observation.reference(backend.session, backend._source_path(state["plan_id"]))
        initial_ref = observation.reference(backend.session, initial_path)
        input_refs = deepcopy(refs) + [source_ref]
        receipt_ref = next(item for item in refs if item["path"] == "responses/" + execution_id + ".json")
        ledger.append("opened", {"mode": "adaptive_grace", "grace": grace, "run_id": state["run_id"],
            "step_id": step["step_id"], "execution_request_id": execution_id, "plan_id": state["plan_id"],
            "plan_sha256": state["plan_sha256"], "source_ref": source_ref, "owner_id": state["owner_id"],
            "session_directory": state["session_directory"], "target_identity": deepcopy(state["target_identity"]),
            "after": deepcopy(frame), "original_frame": deepcopy(original_frame), "input_evidence_refs": input_refs,
            "original_receipt_sha256": receipt_ref["sha256"], "policy_snapshot": policy_snapshot(service),
            "clock_id": grace["clock_id"], "started_ns": grace["started_ns"], "initial_assessment_ref": initial_ref,
            **({"condition_snapshot": semantic_binding(backend._source(state)["plan"], step)["condition_snapshot"]}
                if "condition_snapshot" in semantic_binding(backend._source(state)["plan"], step) else {})})
        ledger.append("assessed", {"round": 0, "assessment_ref": initial_ref})
    try:
        _, remaining = _header_guard(backend, state, ledger, frame, effective, service, target_reader)
        if ledger.finished() is not None:
            return observation._outcome(ledger, reason=ledger.finished()["reason"])
        events = ledger.read()
        claims = [event for event in events if event["event"] == "capture_claimed"]
        captures = [event["payload"] for event in events if event["event"] == "captured"]
        api_claims = [event for event in events if event["event"] == "assessment_claimed"]
        assessed = [event for event in events if event["event"] == "assessed" and event["payload"]["round"] == 1]
        if len(claims) > len(captures) or len(api_claims) > len(assessed):
            return observation._finish(ledger, "task_plan_adaptive_grace_result_unknown")
        if not captures:
            if remaining > 0:
                return observation._outcome(ledger, pending=True)
            ledger.append("capture_claimed", {"round": 1, "claimed_ns": observation.now_ns()})
            def cancelled():
                _header_guard(backend, state, ledger, frame, effective, service, target_reader)
                return False
            captured = observation.capture_followup(coordinator, session_dir=backend.session,
                target_identity=state["target_identity"], original_frame=original_frame,
                observation_id="grace-final-" + digest([state["run_id"], execution_id])[:32],
                cancelled=cancelled, remaining_seconds=lambda: observation._remaining(ledger.header())[1],
                wait_budget_exhausted=True)
            current = captured["frame"]
            if (set(current) != {"capture_id", "sha256", "image_path", "window_identity", "role"}
                    or current["role"] != "observation" or current["window_identity"] != state["target_identity"]
                    or current["capture_id"] == frame["capture_id"]
                    or Path(current["image_path"]).resolve() == Path(frame["image_path"]).resolve()
                    or Path(current["image_path"]).samefile(frame["image_path"])):
                raise ValueError("task_plan_adaptive_grace_capture_binding_invalid")
            image_ref = observation.reference(backend.session, current["image_path"])
            if image_ref["sha256"] != current["sha256"]:
                raise ValueError("task_plan_adaptive_grace_capture_hash_invalid")
            ledger.append("captured", {"round": 1, "frame": current, "image_ref": image_ref,
                "capture_elapsed_ms": captured["capture_elapsed_ms"], "completed_ns": observation.now_ns()})
            captures = [{"frame": current}]
        _header_guard(backend, state, ledger, frame, effective, service, target_reader)
        current = captures[-1]["frame"]
        if not api_claims and current["sha256"] != frame["sha256"]:
            binding = _binding(backend, state, step, [current], final=True, effective=effective, original_frame=frame)
            ledger.append("assessment_claimed", {"round": 1, "binding": binding, "input_evidence_refs": ledger.input_refs()})
            value, valid = assess(service, binding, v2=True)
            path = backend.session / "task-plan-decisions" / (execution_id + "-grace-final.json")
            observation._put(path, {"binding": binding, "result": value, "validated": valid,
                "policy_snapshot": ledger.header()["policy_snapshot"]})
            ledger.append("assessed", {"round": 1, "assessment_ref": observation.reference(backend.session, path)})
        elif not api_claims:
            ledger.append("reused_assessment", {"round": 1, "sha256": current["sha256"],
                "assessment_ref": ledger.header()["initial_assessment_ref"]})
        _header_guard(backend, state, ledger, frame, effective, service, target_reader)
        saved = ledger.last_assessment()
        value = saved["result"]
        return observation._finish(ledger, "authenticated_decision" if saved["validated"]
            and value.get("adopted") is True and value.get("disposition") == "continue" else
            value.get("reason", "decision_requires_agent_review"))
    except observation.TaskPlanCancelPending:
        raise
    except (ValueError, OSError) as error:
        reason = getattr(error, "reason_code", None) or (str(error) if str(error).startswith("task_plan_")
            else "task_plan_adaptive_grace_capture_failed")
        return observation._finish(ledger, reason)


def validate_grace_adoption(backend, state, ledger, frame, saved, *, service, target_reader):
    execution_id = state["pending"]["execution_request_id"]
    path = backend.session / "responses" / (execution_id + ".json")
    effective, _ = resolve_execution_receipt(read_json_snapshot(path), path, execution_id)
    _header_guard(backend, state, ledger, frame, effective, service, target_reader)
    header, events = ledger.header(), ledger.read()
    captures = [event["payload"] for event in events if event["event"] == "captured"]
    capture_claims = [event["payload"] for event in events if event["event"] == "capture_claimed"]
    api_claims = [event["payload"] for event in events if event["event"] == "assessment_claimed"]
    initial_path = backend.session / "task-plan-decisions" / (execution_id + ".json")
    initial = read_json_snapshot(initial_path)
    step = backend.pinned_step(state["run_id"], state["pending"]["step_id"])
    from .task_result_annotation import task_result_click_action, task_result_decision_binding
    original_binding = task_result_decision_binding(_binding(backend, state, step, [frame], final=False),
        task_result_click_action(step, effective, frame), saved_binding=initial.get("binding"))
    value, valid = validate_assessment(service, initial["result"], original_binding, v2=True)
    if (initial["binding"] != original_binding or not semantic_nonpass(value, valid)
            or header["initial_assessment_ref"] != observation.reference(backend.session, initial_path)
            or len(captures) != 1 or len(capture_claims) != 1 or len(api_claims) > 1
            or capture_claims[0]["claimed_ns"] < header["grace"]["deadline_ns"]
            or ledger.finished()["reason"] != "authenticated_decision"):
        raise ValueError("task_plan_adaptive_grace_adoption_invalid")
    current = captures[0]["frame"]
    if api_claims:
        binding = _binding(backend, state, step, [current], final=True, effective=effective, original_frame=frame)
        if (api_claims[0]["binding"] != binding or api_claims[0]["input_evidence_refs"] != ledger.input_refs()
                or saved["binding"] != binding or saved["policy_snapshot"] != header["policy_snapshot"]):
            raise ValueError("task_plan_adaptive_grace_adoption_invalid")
    else:
        reuse = [event["payload"] for event in events if event["event"] == "reused_assessment"]
        if (len(reuse) != 1 or current["sha256"] != frame["sha256"] or saved != initial
                or reuse[0] != {"round": 1, "sha256": current["sha256"], "assessment_ref": header["initial_assessment_ref"]}):
            raise ValueError("task_plan_adaptive_grace_reuse_invalid")
        binding = original_binding
    _header_guard(backend, state, ledger, frame, effective, service, target_reader)
    return binding
