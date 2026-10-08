"""回读已完成的判断，不在轮询中采图、调用模型或重做输入。"""
from copy import deepcopy
import json
from pathlib import Path


def project_decision_receipt(receipt, *, session_dir, profile_path=None):
    result = receipt.get("result") or {}
    execution_id = receipt.get("request_id")
    if result.get("contract_version") == "agent_command.v1":
        if result.get("status") != "completed":
            return receipt
        execution_id = result.get("command_id")
        result = result.get("result") or {}
    advice = result.get("decision_judgment")
    if not isinstance(advice, dict):
        return receipt
    receipt["decision_judgment"] = deepcopy(advice)
    if advice.get("adopted") is not True or advice.get("phase") != "after_action":
        return receipt
    raw = advice.get("judgment_result")
    if advice.get("execution_request_id") != execution_id:
        receipt["decision_validation"] = "execution_binding_mismatch"
        return receipt
    if (not isinstance(raw, dict) or raw.get("mode") != "execution"
            or any(advice.get(key) != raw.get(key) for key in
                   ("status", "phase", "request_id", "execution_request_id", "verdict", "adopted"))):
        receipt["decision_validation"] = "judgment_wrapper_mismatch"
        return receipt
    service = None
    try:
        from app.execution.decision_check import decision_frame, validate_decision_check, validate_execution_request_id
        from app.judgment.service import DecisionService
        validate_execution_request_id(execution_id)
        command = json.loads((Path(session_dir) / "commands" / (execution_id + ".json")).read_text(encoding="utf-8"))
        check = validate_decision_check(command.get("decision_check") or
            ((command.get("request") or {}).get("metadata") or {}).get("decision_check"))
        if (command.get("kind") != "step" or check is None or check["phase"] != "after_action"
                or receipt.get("operation_succeeded") is not True or result.get("phase") != "returned"
                or (result.get("response") or {}).get("success") is not True
                or (result.get("observation") or {}).get("status") != "captured"):
            raise ValueError("original_input_or_check_unavailable")
        frames = [decision_frame(result["observation"].get("capture"), result.get("target_identity"), role="after")]
        if any(frame.get("role") == "before" for frame in raw.get("frames", [])):
            frames.insert(0, decision_frame(result.get("capture"), result.get("target_identity"), role="before"))
        from .decision_configuration import PROFILE_SNAPSHOT
        service = DecisionService.from_environment(session_dir, profile_path=Path(session_dir) / PROFILE_SNAPSHOT)
        valid = service.validate_result(raw, request_id=raw.get("request_id"), execution_request_id=execution_id,
            condition=check["condition"], frames=frames, mode="execution", phase="after_action",
            run_id=None, step_id=result.get("step_id"), action=None)
    except (OSError, ValueError, RuntimeError, TypeError, KeyError):
        valid = False
    finally:
        if service is not None:
            service.close()
    receipt["decision_validation"] = "authenticated" if valid else "unverified"
    if not valid or advice.get("verdict") not in {"success", "failure"}:
        return receipt
    verified = advice["verdict"] == "success"
    receipt["task_effect_verified"] = verified
    review = receipt.setdefault("agent_review", {})
    review.update(status="decision_verified" if verified else "decision_failed", verified=verified,
                  judged_by="decision_api", automatic_retry_allowed=False,
                  next="Continue from this verified result." if verified else
                       "Inspect the failed task condition and original evidence; never replay input automatically.")
    return receipt
