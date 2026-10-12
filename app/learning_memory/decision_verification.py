"""把可选判断绑定到已审核步骤和原回执，不从谓词读取动态值。"""
from copy import deepcopy
from collections import deque
from hashlib import sha256
from pathlib import Path

from .workflow_verification import _evidence_current, _result, verify_step


class DecisionAuthenticationError(ValueError):
    def __init__(self, error_type):
        super().__init__("workflow_decision_authentication_failed")
        self.error_type = error_type


def authenticate_decision_result(service, decision, binding):
    try:
        return service.validate_result(decision, **binding) is True
    except Exception as error:
        raise DecisionAuthenticationError(type(error).__name__) from None


def decision_eligible(step, service, *, inputs=None):
    rule = step.get("verification") or {}
    profile = getattr(service, "profile", None)
    if "condition_binding" in rule:
        from .workflow_condition_templates import step_condition_snapshot
        if getattr(profile, "contract_version", None) != "decision_profile.v2":
            return False
        snapshot = step_condition_snapshot(step, inputs)
        condition = snapshot["condition"]
        if getattr(profile, "mode", None) == "auto":
            allowed = getattr(service, "auto_condition_allowed", None)
            if callable(allowed):
                approved = allowed(condition, condition_snapshot=snapshot) is True
            else:
                approved = any(all(getattr(identity, key, None) == snapshot[key] for key in
                    ("condition_template_id", "revision", "template_sha256")) for identity in
                    getattr(profile, "auto_condition_templates", ()))
            if not approved:
                return False
        return (getattr(service, "enabled", False) is True and step.get("review_status") == "reviewed"
            and rule.get("kind") == "agent_judgment" and not step.get("outputs")
            and "read_spec" not in step and step.get("action", {}).get("kind") != "read_text")
    if (getattr(profile, "contract_version", None) == "decision_profile.v2"
            and getattr(profile, "mode", None) == "auto"
            and rule.get("decision_condition") not in getattr(profile, "auto_conditions", ())):
        return False
    return (getattr(service, "enabled", False) is True and step.get("review_status") == "reviewed"
            and rule.get("kind") == "agent_judgment" and isinstance(rule.get("decision_condition"), str)
            and bool(rule["decision_condition"].strip()) and not step.get("outputs")
            and "read_spec" not in step and step.get("action", {}).get("kind") != "read_text")


def main_review_required(step, service):
    profile = getattr(service, "profile", None)
    return ((step.get("verification") or {}).get("review_policy") == "always_main"
            or step.get("verification", {}).get("condition_binding", {}).get("template", {}).get("review_policy") == "always_main"
            or (getattr(profile, "contract_version", None) == "decision_profile.v2"
                and getattr(service, "enabled", False) is True
                and getattr(profile, "mode", None) in {"auto", "shadow"}
                and getattr(profile, "review_policy", None) == "always_main"))


def decision_review_context(program, step, *, inputs=None):
    from app.judgment.adaptive_policy import normalize_review_context
    definition = program["definition"]
    steps = definition["steps"]
    by_id = {item["step_id"]: item for item in steps}
    if by_id.get(step["step_id"]) != step:
        raise ValueError("workflow_decision_review_step_mismatch")
    entry = step["branches"]["success"]
    pending, seen, remaining = deque([entry]), set(), []
    # 运行按分支跳转；列表位置不代表后继，共享节点只描述一次。
    while pending:
        target = pending.popleft()
        if target is None or target in seen:
            continue
        if target not in by_id:
            raise ValueError("workflow_decision_review_branch_invalid")
        seen.add(target)
        item = by_id[target]
        success, failure = item["branches"]["success"], item["branches"]["failure"]
        success_ref = "terminal" if success is None else "step:" + success
        failure_ref = "terminal" if failure is None else "step:" + failure
        remaining.append((target + " (entry=" + str(target == entry).lower()
            + "; success=" + success_ref + "; failure=" + failure_ref + "; uncertain=Main): "
            + item["title"] + " [" + item["action"]["kind"] + "] "
            + item.get("verification", {}).get("decision_condition", ""))[:2000])
        pending.extend((success, failure))
    context = {"goal": definition["title"], "step_goal": step["title"], "allowed_states": [],
               "remaining_plan": remaining,
               "source_id": program["program_id"], "source_sha256": program["content_sha256"]}
    if "review_policy" in (step.get("verification") or {}):
        context["review_policy"] = step["verification"]["review_policy"]
    from .workflow_condition_templates import step_condition_snapshot
    snapshot = step_condition_snapshot(step, inputs)
    if snapshot is not None:
        context["allowed_states"] = deepcopy(snapshot["allowed_states"])
        context["review_policy"] = ("always_main" if snapshot["review_policy"] == "always_main"
            or context.get("review_policy") == "always_main" else "adaptive")
    return normalize_review_context(context)


def decision_binding(step, envelope, *, program=None, inputs=None):
    observation, receipt, frame = envelope["observation"], envelope["receipt"], envelope["frame"]
    if (not _evidence_current(receipt, observation)
            or frame.get("capture_id") != observation["capture_id"]
            or frame.get("sha256") != observation["capture_sha256"]
            or frame.get("window_identity") != receipt["window_identity"]):
        raise ValueError("workflow_decision_evidence_binding_invalid")
    image = Path(frame["image_path"]).resolve()
    if sha256(image.read_bytes()).hexdigest() != frame["sha256"]:
        raise ValueError("workflow_decision_evidence_changed")
    from app.desktop_review.external_mapping import canonical_json_bytes
    # 服务发送身份由原执行票据决定，篡改工具请求索引也不能产生第二次付费发送。
    dispatch_id = "learning-decision-" + sha256(canonical_json_bytes([
        receipt["run_id"], step["step_id"], receipt["execution_request_id"]])).hexdigest()
    from .workflow_condition_templates import step_condition_snapshot
    snapshot = step_condition_snapshot(step, inputs)
    if snapshot is not None and envelope.get("condition_snapshot") != snapshot:
        raise ValueError("workflow_condition_observation_snapshot_mismatch")
    binding = {"request_id": dispatch_id, "execution_request_id": receipt["execution_request_id"],
            "condition": snapshot["condition"] if snapshot is not None else step["verification"]["decision_condition"], "mode": "learning", "phase": "after_action",
            "run_id": receipt["run_id"], "step_id": step["step_id"],
            "frames": [{key: deepcopy(frame[key]) for key in ("capture_id", "sha256", "window_identity")}
                       | {"image_path": str(image), "role": "after"}]}
    if snapshot is not None:
        binding["condition_snapshot"] = snapshot
    if "decision_review_context" in envelope:
        if program is None or envelope["decision_review_context"] != decision_review_context(program, step, inputs=inputs):
            raise ValueError("workflow_decision_review_context_mismatch")
        binding["review_context"] = decision_review_context(program, step, inputs=inputs)
    return binding


def validate_original_evidence(trials, state, pending, step, envelope, *, request_id, program=None):
    from .receipt_adapter import resolve_execution_receipt
    from .workflow_trial import _read, _receipt_state, _execution_identity, _actual_action_executed, _verified_observation
    execution_id = pending["execution_request_id"]
    receipt_path = trials.session / "responses" / (execution_id + ".json")
    original = _read(receipt_path)
    context = trials._receipt_context(state, pending)
    dispatched, terminal, _ = _receipt_state(original, receipt_path, execution_id,
        pending["suggested_command"], expected_context=context)
    effective, _ = resolve_execution_receipt(original, receipt_path, execution_id)
    receipt, frame = envelope.get("receipt"), envelope.get("frame")
    before = (effective.get("result") or {}).get("capture") or {}
    ids = {"run_id": state["run_id"], "step_id": step["step_id"], "request_id": request_id,
           "execution_request_id": execution_id}
    actual = _actual_action_executed(effective.get("result"), terminal)
    if (not dispatched or envelope.get("contract_version") != "workflow_observation.v1"
            or envelope.get("source_receipt_sha256") != sha256(receipt_path.read_bytes()).hexdigest()
            or envelope.get("terminal_receipt") != terminal or not isinstance(receipt, dict) or not isinstance(frame, dict)
            or any(receipt.get(key) != value for key, value in ids.items())
            or receipt.get("status") != "completed" or receipt.get("action_executed") is not actual
            or receipt.get("window_identity") != _execution_identity(effective)
            or frame.get("window_identity") != receipt.get("window_identity")
            or before.get("capture_id") and receipt.get("pre_capture_id") != before["capture_id"]
            or frame.get("capture_id") == receipt.get("pre_capture_id")
            or (trials.session / str(receipt.get("evidence_ref", ""))).resolve() != receipt_path
            or receipt.get("row_selection_proof") != (effective["result"].get("row_selection_proof") if context is not None else None)):
        raise ValueError("workflow_decision_original_evidence_mismatch")
    _verified_observation({"observation": frame}, trials.session)
    decision_binding(step, envelope, program=program, inputs=state["inputs"])


def adopted_verification(step, *, inputs, outputs, envelope, decision, service, program=None):
    if not decision_eligible(step, service, inputs=inputs):
        raise ValueError("workflow_decision_not_eligible")
    binding = decision_binding(step, envelope, program=program, inputs=inputs)
    v2 = getattr(getattr(service, "profile", None), "contract_version", None) == "decision_profile.v2"
    if (not isinstance(decision, dict) or decision.get("status") != "completed"
            or decision.get("adopted") is not True or decision.get("verdict") not in {"success", "failure"}
            or decision.get("authorizes_action") is not False or decision.get("automatic_retry_allowed") is not False
            or any(decision.get(key) != binding[key] for key in (
                "request_id", "execution_request_id", "condition", "mode", "phase", "run_id", "step_id", "frames"))
            or decision.get("evidence_hashes") != [frame["sha256"] for frame in binding["frames"]]
            or v2 and ("review_context" not in binding or decision.get("schema_version") != "decision_assessment.v2"
                       or decision.get("disposition") != "continue")
            or "disposition" in decision and decision["disposition"] != "continue"
            or main_review_required(step, service)
            or not authenticate_decision_result(service, decision, binding)):
        raise ValueError("workflow_decision_result_untrusted")
    local = verify_step(step, inputs=inputs, outputs=outputs,
                        receipt=envelope["receipt"], observation=envelope["observation"])
    if local["verdict"] != "uncertain" or local["reason"] != "agent_judgment_required":
        raise ValueError("workflow_decision_local_result_ineligible")
    from .workflow_trial import _conditions
    current_outputs = {key: item["value"] for key, item in outputs.items()
                       if isinstance(item, dict) and item.get("run_id") == binding["run_id"] and "value" in item}
    if decision["verdict"] == "success" and _conditions(step.get("success_conditions", []), inputs, current_outputs,
                                                        envelope["observation"]["values"]) != "true":
        raise ValueError("workflow_decision_success_conditions_require_agent")
    result = _result(decision["verdict"], "decision_condition_verified", envelope["receipt"],
                     envelope["observation"], {})
    result["source"] = "decision"
    return result


def decision_result_path(session, request_id):
    from .workflow_program import _id
    _id(request_id, "request_id")
    return Path(session) / "workflow-decisions" / (request_id + ".result.json")
