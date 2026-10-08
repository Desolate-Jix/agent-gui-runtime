"""把可选判断绑定到已审核步骤和原回执，不从谓词读取动态值。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from .workflow_verification import _evidence_current, _result, verify_step


def decision_eligible(step, service):
    rule = step.get("verification") or {}
    return (getattr(service, "enabled", False) is True and step.get("review_status") == "reviewed"
            and rule.get("kind") == "agent_judgment" and isinstance(rule.get("decision_condition"), str)
            and bool(rule["decision_condition"].strip()) and not step.get("outputs")
            and "read_spec" not in step and step.get("action", {}).get("kind") != "read_text")


def decision_binding(step, envelope):
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
    return {"request_id": dispatch_id, "execution_request_id": receipt["execution_request_id"],
            "condition": step["verification"]["decision_condition"], "mode": "learning", "phase": "after_action",
            "run_id": receipt["run_id"], "step_id": step["step_id"],
            "frames": [{key: deepcopy(frame[key]) for key in ("capture_id", "sha256", "window_identity")}
                       | {"image_path": str(image), "role": "after"}]}


def validate_original_evidence(trials, state, pending, step, envelope, *, request_id):
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
    decision_binding(step, envelope)


def adopted_verification(step, *, inputs, outputs, envelope, decision, service):
    if not decision_eligible(step, service):
        raise ValueError("workflow_decision_not_eligible")
    binding = decision_binding(step, envelope)
    if (not isinstance(decision, dict) or decision.get("status") != "completed"
            or decision.get("adopted") is not True or decision.get("verdict") not in {"success", "failure"}
            or decision.get("authorizes_action") is not False or decision.get("automatic_retry_allowed") is not False
            or any(decision.get(key) != binding[key] for key in (
                "request_id", "execution_request_id", "condition", "mode", "phase", "run_id", "step_id", "frames"))
            or decision.get("evidence_hashes") != [frame["sha256"] for frame in binding["frames"]]
            or not service.validate_result(decision, **binding)):
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
