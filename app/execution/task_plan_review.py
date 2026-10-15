"""审核包只投影原证据；不读取桌面、不执行输入、不创建主会话。"""
from copy import deepcopy
from hashlib import sha256
import json

from .task_plan_conditions import semantic_binding, validate_packet_condition

def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _goal(step):
    return step["action"].get("goal", step["action"].get("field_goal", ""))


def _step_summary(step):
    """只投影已声明的动作语义；输入值、目标和未知字段均不进入远端上下文。"""
    action = step["action"]
    projected = {"kind": action["kind"]}
    if action["kind"] == "input_sequence":
        text = action["text"]
        source = text["source"] if isinstance(text, dict) else "literal"
        projected.update(field_goal=action["field_goal"], clear_existing=action["clear_existing"],
            submit_search=action["submit_search"], text={"source": "input", "name": text["name"]}
            if source == "input" else {"source": source, "redacted": True})
    else:
        projected["goal"] = action["goal"]
        if action["kind"] == "click":
            projected["click_kind"] = action.get("click_kind", "single")
    verification = {"kind": step["verification"]["kind"]}
    for key in ("decision_condition", "condition"):
        if key in step["verification"]:
            verification[key] = deepcopy(step["verification"][key])
    if "condition_binding" in step["verification"]:
        template = step["verification"]["condition_binding"]["template"]
        verification["condition_template"] = {key: template[key] for key in
            ("condition_template_id", "revision", "template_sha256")}
    return json.dumps({"step_id": step["step_id"], "action": projected, "verification": verification},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def review_context(plan, step, *, source_id, source_sha256):
    index = next(i for i, item in enumerate(plan["steps"]) if item["step_id"] == step["step_id"])
    v2 = plan["schema_version"] in {"task_plan.v2", "task_plan.v3"}
    snapshot = semantic_binding(plan, step).get("condition_snapshot")
    context = {"goal": plan.get("goal", plan["title"]), "step_goal": _step_summary(step) if v2 else _goal(step),
        "remaining_plan": [_step_summary(item) if v2 else (item["action"]["kind"] + ": " + _goal(item))[:2000]
                           for item in plan["steps"][index + 1:]],
        "allowed_states": deepcopy(snapshot["allowed_states"] if snapshot is not None
            else step["verification"].get("allowed_states", [])),
        "source_sha256": source_sha256, "source_id": source_id}
    if plan["schema_version"] == "task_plan.v3" and plan["completion"]["verification"] != step["verification"]:
        context["remaining_plan"].append(json.dumps({"completion": plan["completion"]},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
    if "review_policy" in step["verification"]:
        context["review_policy"] = step["verification"]["review_policy"]
    if snapshot is not None:
        context["review_policy"] = ("always_main" if snapshot["review_policy"] == "always_main"
            or context.get("review_policy") == "always_main" else "adaptive")
    if "wait_policy" in step["verification"]:
        context["wait_policy"] = deepcopy(step["verification"]["wait_policy"])
    if v2:
        from app.judgment.adaptive_policy import normalize_review_context
        return normalize_review_context(context)
    encoded = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > 65536:
        raise ValueError("task_plan_review_context_too_large")
    return context


def policy_snapshot(service):
    if service is None:
        return {"configured": False}
    try:
        status = service.status() if callable(getattr(service, "status", None)) else {}
        if not isinstance(status, dict):
            raise ValueError("decision_status_contract_invalid")
    except Exception as error:
        return {"configured": True, "status": "unavailable", "error_type": type(error).__name__}
    return {key: deepcopy(status[key]) for key in ("contract_version", "profile_sha256", "mode",
        "adoption_mode", "review_policy", "proactive_review", "decision_format") if key in status}


def assess(service, binding, *, v2):
    """提供者或认证异常只成为明确等待，不能改写原输入事实。"""
    try:
        value = service.evaluate(**binding)
    except Exception as error:
        return {"status": "error", "reason": "decision_service_failed", "error_type": type(error).__name__}, False
    return validate_assessment(service, value, binding, v2=v2)


def validate_assessment(service, value, binding, *, v2):
    if (not isinstance(value, dict) or value.get("request_id") != binding["request_id"]
            or value.get("execution_request_id") != binding["execution_request_id"]
            or value.get("phase") != binding["phase"]
            or not isinstance(value.get("verdict"), str)
            or value.get("verdict") not in {"success", "failure", "uncertain"}
            or value.get("authorizes_action") is not False):
        return {"status": "invalid", "reason": "decision_result_binding_invalid"}, False
    if v2 and (value.get("schema_version") != "decision_assessment.v2"
            or not isinstance(value.get("disposition"), str)
            or value.get("disposition") not in {"continue", "review_required", "observe"}
            or not isinstance(value.get("review_scope"), str)
            or value.get("review_scope") not in {"effect", "remaining_plan", "effect_and_plan", "runtime_diagnostic"}
            or not isinstance(value.get("reason_codes"), list)
            or any(not isinstance(item, str) for item in value["reason_codes"])
            or not isinstance(value.get("enabled_predicates"), list)
            or any(not isinstance(item, str) for item in value["enabled_predicates"])):
        return {"status": "invalid", "reason": "decision_result_contract_invalid"}, False
    if v2 and value.get("disposition") == "observe" and (not binding.get("review_context", {}).get("wait_policy")
            or "assessment_context" not in binding or value.get("verdict") != "uncertain" or value.get("adopted") is not False):
        return {"status": "invalid", "reason": "decision_observe_contract_invalid"}, False
    if v2 or value.get("adopted") is True:
        try:
            valid = service.validate_result(value, **binding) is True
        except Exception as error:
            return {"status": "invalid", "reason": "decision_result_authentication_failed",
                "error_type": type(error).__name__}, False
        if not valid:
            return {"status": "invalid", "reason": "decision_result_authentication_invalid"}, False
    return deepcopy(value), True


def assessment_summary(value):
    if not isinstance(value, dict):
        return None
    return {key: deepcopy(value[key]) for key in ("schema_version", "status", "verdict", "disposition",
        "review_scope", "reason", "error_type", "reason_codes", "enabled_predicates", "profile_sha256",
        "budget", "local_proof_complete", "probabilities", "predicates", "suggested_disposition",
        "suggested_reason_codes", "decision_format", "choice_result", "identity_result", "ordinary_review", "primary_usage",
        "usage", "judged_by") if key in value}


def field_main_handoff(state, effective, references, *, session, service, original_status):
    """投影原字段拒绝及原输入事实，不创建可继续的审核票据。"""
    from .input_sequence import _action_data
    from .task_plan_verification import _reference
    sequence = effective.get("result") or {}
    handoff = sequence.get("main_handoff")
    if handoff is None:
        return None
    invalid = "task_plan_field_handoff_binding_invalid"
    if (not isinstance(handoff, dict) or set(handoff) != {"schema", "reason", "request", "assessment",
            "automatic_retry_allowed", "authorizes_action", "allowed_next_steps", "stage", "original_input"}
            or handoff.get("schema") != "visual_field_main_handoff.v1"
            or handoff.get("automatic_retry_allowed") is not False or handoff.get("authorizes_action") is not False
            or handoff.get("allowed_next_steps") != ["inspect_original_evidence", "close_or_explicitly_replan"]
            or effective.get("command", {}).get("kind") != "input_sequence"
            or sequence.get("contract_version") != "input_sequence_v1" or sequence.get("status") != "interrupted"
            or sequence.get("automatic_retry_allowed") is not False or original_status not in {"failed", "unknown"}):
        raise ValueError(invalid)
    request, assessment = handoff["request"], handoff["assessment"]
    if not isinstance(request, dict) or not isinstance(assessment, dict):
        raise ValueError(invalid)
    action = request.get("action") or {}
    pending = state["pending"]
    stage = handoff["stage"]
    expected_stage = {"after_click": ("focus", "after_click"), "after_selection": ("focus", "after_selection"),
        "after_type": ("value", None), "before_type_freshness": ("focus", "before_keyboard_freshness"),
        "before_enter_freshness": ("value", "before_keyboard_freshness")}.get(stage)
    rows = sequence.get("steps") or []
    compound = bool(rows) and rows[0].get("name") == "focus_type"
    if (expected_stage is None or (action.get("field_phase"), action.get("focus_stage")) != expected_stage
            or request.get("execution_request_id") != pending["execution_request_id"] or request.get("phase") != "after_action"
            or (action.get("field") or {}).get("window_identity") != state["target_identity"]
            or assessment.get("adopted") is not False or assessment.get("disposition") != "review_required"
            or not rows or action.get("focus_receipt_sha256") != digest(rows[0].get("receipt"))
            or not callable(getattr(service, "validate_result", None))
            or service.validate_result(assessment, **request) is not True):
        raise ValueError(invalid)
    last = rows[-1].get("receipt")
    data = _action_data(last) if isinstance(last, dict) else {}
    if compound:
        from app.core.input_sequence_partial import _compound_input_fact, _request
        try:
            spec = _request(effective["command"].get("request"))
            fact = _compound_input_fact(sequence, spec, state["target_identity"], allow_unknown_row=True)
        except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
            fact = None
        if (len(rows) != 1 or fact is None or not fact["completed"]
                or stage not in {"after_type", "before_enter_freshness"}
                or fact["fact"]["execution_request_id"] != pending["execution_request_id"]
                or action.get("input_receipt_sha256") != digest(last)
                or action.get("field", {}).get("field_goal") != spec["field_goal"]
                or action.get("field", {}).get("expected_text") != spec["text"]):
            raise ValueError(invalid)
        dispatch = fact["fact"]["typing_dispatch"]
        input_receipt = last
    else:
        dispatch = data.get("typing_dispatch") or (data.get("type_result") or {}).get("typing_dispatch")
        input_receipt = rows[1].get("receipt") if len(rows) > 1 else None
    original_input = {"completed_steps": sequence.get("completed_steps"), "interrupted_at": sequence.get("interrupted_at"),
        "action_executed": sequence.get("action_executed"), "input_check": sequence.get("input_check"),
        "typing_dispatch": dispatch}
    if (handoff["original_input"] != original_input
            or action.get("field_phase") == "value" and action.get("input_receipt_sha256") != digest(input_receipt)
            or stage == "after_selection" and action.get("selection_dispatch") != dispatch):
        raise ValueError(invalid)
    refs = deepcopy(references)
    for frame in request.get("frames", []):
        ref = _reference(session, frame["image_path"])
        if ref["sha256"] != frame["sha256"] or frame.get("window_identity") != state["target_identity"]:
            raise ValueError(invalid)
        if ref not in refs:
            refs.append(ref)
    if dispatch and dispatch.get("selection_evidence"):
        fact = dispatch["selection_evidence"]
        ref = _reference(session, fact["path"])
        if ref["sha256"] != fact["sha256"]:
            raise ValueError(invalid)
        if ref not in refs:
            refs.append(ref)
    return {"schema": "task_plan_main_handoff.v1", "run_id": state["run_id"], "step_id": pending["step_id"],
        "execution_request_id": pending["execution_request_id"], "plan_id": state["plan_id"],
        "plan_sha256": state["plan_sha256"], "owner_id": state["owner_id"], "session_directory": state["session_directory"],
        "target_identity": deepcopy(state["target_identity"]), "original_input_status": original_status,
        "action_executed": sequence["action_executed"], "field_review": deepcopy(handoff),
        "evidence_refs": refs, "evidence_set_sha256": digest(refs),
        "allowed_next_steps": deepcopy(handoff["allowed_next_steps"]),
        "automatic_retry_allowed": False, "authorizes_action": False}


def make_packet(backend, state, step, result, frame, *, assessment=None, policy=None):
    refs = deepcopy(result["evidence_refs"])
    source_path = backend._source_path(state["plan_id"])
    source_ref = {"path": source_path.relative_to(backend.session).as_posix(),
        "sha256": sha256(source_path.read_bytes()).hexdigest()}
    source = backend._source(state)
    semantic = semantic_binding(source["plan"], step)
    context = review_context(source["plan"], step,
        source_id=state["plan_id"], source_sha256=state["plan_sha256"])
    packet = {"schema": "review_packet.v1", "run_id": state["run_id"],
        "step_id": step["step_id"], "execution_request_id": result["execution_request_id"],
        "wait_id": "workflow-wait-" + digest([state["run_id"], "verification_required",
            result["execution_request_id"], step["step_id"]])[:32],
        "plan_id": state["plan_id"], "plan_sha256": state["plan_sha256"],
        "source_ref": source_ref, "owner_id": state["owner_id"], "session_directory": state["session_directory"],
        "target_identity": deepcopy(state["target_identity"]), "goal": context["goal"],
        "step_goal": context["step_goal"], "remaining_plan": context["remaining_plan"],
        "expected_condition": deepcopy(semantic["condition"] if semantic["condition"] is not None
            else step["verification"].get("condition")),
        "original_input_status": result["original_input_status"], "action_executed": result["action_executed"],
        "reason": result["reason"], "suggested_verdict": (assessment or {}).get("verdict", "uncertain"),
        "policy_snapshot": deepcopy(policy or {}),
        "profile_sha256": (assessment or {}).get("profile_sha256", (policy or {}).get("profile_sha256")),
        "budget": deepcopy((assessment or {}).get("budget")),
        "assessment": assessment_summary(assessment), "after": deepcopy(frame), "evidence_refs": refs,
        "assessment_ref": next((deepcopy(item) for item in refs if item["path"].startswith("task-plan-decisions/")), None),
        "evidence_set_sha256": digest(refs), "assessment_round": 0,
        "allowed_controls": ["review", "cancel"], "automatic_retry_allowed": False,
        "authorizes_action": False}
    if source["plan"]["schema_version"] == "task_plan.v3":
        from .task_plan_contract import completion_snapshot
        packet["completion"] = completion_snapshot(source["plan"])
        packet["completion_snapshot_sha256"] = digest(packet["completion"])
    if result.get("reason") in {"blocked_before_dispatch", "repeated_obstruction"}:
        packet["allowed_controls"] = (["recover", "resume_pre_dispatch", "cancel"]
            if result["reason"] == "blocked_before_dispatch" else ["cancel"])
    if "condition_snapshot" in semantic:
        packet["condition_snapshot"] = deepcopy(semantic["condition_snapshot"])
    observation = result.get("observation")
    if observation is not None:
        packet.update(schema="review_packet.v2", observation=deepcopy(observation),
            input_evidence_refs=deepcopy(observation["input_evidence_refs"]),
            evidence_set_sha256=observation["evidence_set_sha256"],
            artifact_refs=deepcopy(refs), artifact_set_sha256=digest(refs),
            assessment_round=observation["assessment_round"],
            assessment_ref=deepcopy(observation["assessment_ref"]),
            original_receipt_sha256=observation["original_receipt_sha256"])
    video = result.get("video_playback")
    if video is not None:
        packet.update(schema="review_packet.v4", video_playback=deepcopy(video),
            input_evidence_refs=deepcopy(video["input_evidence_refs"]),
            evidence_set_sha256=video["evidence_set_sha256"], artifact_refs=deepcopy(refs),
            artifact_set_sha256=digest(refs), assessment_round=video["assessment_round"],
            assessment_ref=deepcopy(video["assessment_ref"]),
            original_receipt_sha256=video["original_receipt_sha256"])
    packet["packet_sha256"] = digest(packet)
    if len(json.dumps(packet, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 262144:
        raise ValueError("task_plan_review_packet_too_large")
    return packet


def pending_packet(state):
    pending = state.get("pending")
    if not pending:
        return None
    packets = [value["review_packet"] for value in state.get("verification_results", {}).values()
        if value.get("execution_request_id") == pending["execution_request_id"] and value.get("review_packet")]
    if not packets:
        return None
    packet = packets[0]
    if any(item != packet for item in packets):
        raise ValueError("task_plan_review_packet_revision_conflict")
    from .task_plan_observation_evidence import project_packet
    from pathlib import Path
    return project_packet(state, packet, Path(state["session_directory"]))


def caller_controls(state):
    """投影已验证状态的调用参数；不写入签名审核包，也不代填审核结论。"""
    wait = state.get("wait") or {}
    if (state.get("runner_state") != "waiting" or state.get("wait_reason") != "verification_required"
            or state.get("status") == "cancel_requested" or state.get("observation_pending") is True
            or wait.get("run_id") != state["run_id"]):
        return {}
    packet = state.get("review_packet")
    if packet is not None:
        if ("review" not in state.get("allowed_controls", packet.get("allowed_controls", []))
                or "review" not in packet.get("allowed_controls", [])
                or packet.get("original_input_status") != "completed" or not isinstance(packet.get("after"), dict)):
            return {}
        request = {"action": "review", **{key: packet[key] for key in
            ("run_id", "step_id", "execution_request_id", "evidence_set_sha256", "assessment_round")},
            "evidence_sha256": packet["after"]["sha256"], "review_packet_sha256": packet["packet_sha256"]}
        return {"schema": "task_plan_caller_controls.v1", "authorizes_action": False,
            "review": {"request": request, "caller_supplied_fields": ["verdict", "reason"]}}
    history = state.get("history") or []
    settled = history[-1] if history else {}
    if (state.get("pending") is None and state.get("status") in {"ready", "completed"}
            and settled.get("judged_by") == "agent" and settled.get("verdict") == "success"
            and settled.get("original_input_status") == "completed"
            and settled.get("step_id") == wait.get("step_id")
            and settled.get("execution_request_id") == wait.get("command_id")):
        return {"schema": "task_plan_caller_controls.v1", "authorizes_action": False,
            "continue": {"request": {"action": "continue", "run_id": state["run_id"], "wait_id": wait["wait_id"]}}}
    return {}


def validate_packet(packet, state, session):
    body = {key: value for key, value in packet.items() if key != "packet_sha256"}
    v2 = packet.get("schema") in {"review_packet.v2", "review_packet.v3", "review_packet.v4"}
    if (packet.get("schema") not in {"review_packet.v1", "review_packet.v2", "review_packet.v3", "review_packet.v4"} or packet.get("packet_sha256") != digest(body)
            or packet.get("evidence_set_sha256") != digest(packet.get("input_evidence_refs" if v2 else "evidence_refs"))
            or type(packet.get("assessment_round")) is not int or packet["assessment_round"] not in ((0, 1, 2) if v2 else (0,))
            or v2 and (packet.get("artifact_refs") != packet.get("evidence_refs")
                or packet.get("artifact_set_sha256") != digest(packet.get("artifact_refs")))
            or any(packet.get(key) != state.get(key) for key in
                   ("run_id", "plan_id", "plan_sha256", "owner_id", "session_directory", "target_identity"))):
        raise ValueError("task_plan_review_packet_binding_invalid")
    if packet.get("schema") == "review_packet.v3":
        from .task_plan_observation_evidence import validate_manual_packet
        validate_manual_packet(packet, state, session)
    for item in [packet["source_ref"], *packet["evidence_refs"]]:
        path = (session / item["path"]).resolve(strict=True)
        if not path.is_relative_to(session) or sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("task_plan_review_packet_evidence_changed")
    if state.get("plan_schema_version") == "task_plan.v3":
        from app.core.json_snapshot import read_json_snapshot
        from .task_plan_contract import completion_snapshot
        source = read_json_snapshot(session / packet["source_ref"]["path"])
        completion = completion_snapshot(source["plan"])
        if (packet.get("completion") != completion
                or packet.get("completion_snapshot_sha256") != digest(completion)
                or state.get("completion_snapshot_sha256") != digest(completion)):
            raise ValueError("task_plan_goal_review_packet_binding_invalid")
    if packet.get("schema") == "review_packet.v4":
        from .video_playback_verification import VideoPlaybackLedger
        from types import SimpleNamespace
        ledger = VideoPlaybackLedger(SimpleNamespace(session=session), packet["execution_request_id"])
        video = packet.get("video_playback")
        if (ledger.header() is None or video != ledger.summary() or ledger.finished() is None
                or packet["assessment_round"] not in (0, 1)
                or packet["input_evidence_refs"] != video["input_evidence_refs"]
                or packet["assessment_ref"] != video["assessment_ref"]
                or packet["original_receipt_sha256"] != video["original_receipt_sha256"]
                or any(ref not in packet["evidence_refs"] for ref in ledger.artifacts())):
            raise ValueError("task_plan_video_review_packet_binding_invalid")
    if "condition_snapshots_sha256" in state or "condition_snapshot" in packet:
        from app.core.json_snapshot import read_json_snapshot
        source = read_json_snapshot(session / packet["source_ref"]["path"])
        validate_packet_condition(packet, source, state)


def validate_review(review, state, session):
    from .task_plan_manual_observation import assert_no_unsettled_capture
    assert_no_unsettled_capture(state, review["execution_request_id"])
    packet = pending_packet(state)
    if packet is None:
        raise ValueError("task_plan_review_packet_required")
    validate_packet(packet, state, session)
    if any(review.get(key) != packet.get(key) for key in
           ("evidence_set_sha256", "assessment_round")) or review.get("review_packet_sha256") != packet["packet_sha256"]:
        raise ValueError("task_plan_review_packet_binding_mismatch")
    return packet
