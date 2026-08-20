from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable

from app.gate.candidates import validate_action_candidate_freshness


_ALLOWED_REVIEWED_FILE_EXTENSIONS = frozenset({".pdf", ".doc", ".docx", ".rtf"})


def execute_form_file_upload(
    *,
    question: dict[str, Any],
    reviewed_file: dict[str, Any],
    candidate: dict[str, Any],
    current_capture_id: str,
    current_viewport_size: dict[str, Any],
    action_gate: dict[str, Any],
    dispatch: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    result = _base_upload_result(question=question, candidate=candidate, current_capture_id=current_capture_id)

    blocked_reason = _validate_upload_contracts(question=question, reviewed_file=reviewed_file)
    if blocked_reason:
        return _blocked(result, blocked_reason)

    file_path = Path(str(reviewed_file["absolute_path"]))
    blocked_reason, file_evidence = _validate_reviewed_file(file_path=file_path, reviewed_file=reviewed_file)
    if blocked_reason:
        return _blocked(result, blocked_reason)
    result.update(file_evidence)

    freshness = validate_action_candidate_freshness(
        candidate,
        current_capture_id=current_capture_id,
        current_viewport_size=current_viewport_size,
    )
    result["candidate_freshness_decision"] = freshness
    if not freshness.get("allowed"):
        return _blocked(result, "candidate_freshness_rejected")

    blocked_reason = _validate_action_gate(action_gate=action_gate, candidate=candidate)
    if blocked_reason:
        return _blocked(result, blocked_reason)

    point = candidate["click_point"]
    result["dispatch_attempted"] = True
    try:
        dispatch_result = dispatch(
            file_path=str(file_path),
            x=int(point["x"]),
            y=int(point["y"]),
            click_before_selecting=True,
            submit=False,
        )
    except Exception as exc:  # 边界适配器异常必须转成结构化失败，不能泄露文件路径。
        result.update(
            {
                "dispatch_success": False,
                "blocked_reason": "file_upload_dispatch_failed",
                "dispatch_error_type": type(exc).__name__,
            }
        )
        return result
    result["dispatch_success"] = bool(isinstance(dispatch_result, dict) and dispatch_result.get("success"))
    if isinstance(dispatch_result, dict) and dispatch_result.get("trace_path"):
        result["dispatch_trace_path"] = str(dispatch_result["trace_path"])
    if not result["dispatch_success"]:
        result["blocked_reason"] = "file_upload_dispatch_failed"
    return result


def verify_form_file_upload_effect(
    *,
    upload_result: dict[str, Any],
    current_capture_id: str,
    observed_question_id: str,
    observed_filename_hash: str,
    observed_size_bytes: int,
) -> dict[str, Any]:
    failure_reasons: list[str] = []
    if upload_result.get("dispatch_success") is not True:
        failure_reasons.append("upload_dispatch_not_successful")
    source_capture_id = upload_result.get("capture_id")
    if not current_capture_id or current_capture_id == source_capture_id:
        failure_reasons.append("upload_reobserve_required")
    if observed_question_id != upload_result.get("question_id"):
        failure_reasons.append("observed_question_mismatch")
    if observed_filename_hash != upload_result.get("filename_hash"):
        failure_reasons.append("observed_filename_mismatch")
    if _safe_int(observed_size_bytes) != _safe_int(upload_result.get("file_size_bytes")):
        failure_reasons.append("observed_file_size_mismatch")
    verified = not failure_reasons
    return {
        "contract_version": "form_file_upload_effect_verification_v1",
        "verified": verified,
        "status": "file_upload_effect_verified" if verified else "file_upload_effect_not_verified",
        "failure_reasons": failure_reasons,
        "question_id": upload_result.get("question_id"),
        "source_capture_id": source_capture_id,
        "observed_capture_id": current_capture_id,
        "file_sha256": upload_result.get("file_sha256"),
        "file_size_bytes": upload_result.get("file_size_bytes"),
        "file_extension": upload_result.get("file_extension"),
        "pii_redacted": True,
        "artifact_is_authorization": False,
    }


def _base_upload_result(
    *,
    question: dict[str, Any],
    candidate: dict[str, Any],
    current_capture_id: str,
) -> dict[str, Any]:
    return {
        "contract_version": "form_file_upload_action_result_v1",
        "question_id": question.get("question_id"),
        "candidate_id": candidate.get("candidate_id"),
        "capture_id": current_capture_id,
        "dispatch_attempted": False,
        "dispatch_success": False,
        "upload_effect_success": None,
        "pii_redacted": True,
        "artifact_is_authorization": False,
        "unsafe_prevented": False,
    }


def _validate_upload_contracts(*, question: dict[str, Any], reviewed_file: dict[str, Any]) -> str | None:
    if question.get("contract_version") != "form_question_contract_v1":
        return "question_contract_invalid"
    if question.get("field_type") != "file_upload":
        return "question_not_file_upload"
    if reviewed_file.get("contract_version") != "reviewed_file_evidence_v1":
        return "reviewed_file_contract_invalid"
    if reviewed_file.get("human_approved") is not True:
        return "file_not_human_approved"
    if reviewed_file.get("single_use") is not True:
        return "reviewed_file_not_single_use"
    return None


def _validate_reviewed_file(
    *,
    file_path: Path,
    reviewed_file: dict[str, Any],
) -> tuple[str | None, dict[str, Any]]:
    if not file_path.is_absolute():
        return "reviewed_file_path_not_absolute", {}
    if not file_path.is_file():
        return "reviewed_file_not_found", {}
    extension = file_path.suffix.casefold()
    if extension not in _ALLOWED_REVIEWED_FILE_EXTENSIONS:
        return "file_extension_not_allowed", {}
    if str(reviewed_file.get("extension") or "").casefold() != extension:
        return "reviewed_file_extension_mismatch", {}
    payload = file_path.read_bytes()
    checksum = hashlib.sha256(payload).hexdigest()
    if checksum != reviewed_file.get("sha256"):
        return "reviewed_file_checksum_mismatch", {}
    if len(payload) != _safe_int(reviewed_file.get("size_bytes")):
        return "reviewed_file_size_mismatch", {}
    return None, {
        "file_sha256": checksum,
        "file_size_bytes": len(payload),
        "file_extension": extension,
        "filename_hash": hashlib.sha256(file_path.name.encode("utf-8")).hexdigest(),
    }


def _validate_action_gate(*, action_gate: dict[str, Any], candidate: dict[str, Any]) -> str | None:
    if action_gate.get("contract_version") != "pre_click_decision_v1":
        return "action_gate_contract_invalid"
    if action_gate.get("allowed") is not True:
        return "action_gate_rejected"
    if action_gate.get("semantic_action") != "upload_file":
        return "action_gate_semantic_action_mismatch"
    if action_gate.get("selected_candidate_id") != candidate.get("candidate_id"):
        return "action_gate_candidate_mismatch"
    selected = action_gate.get("selected_click_point")
    point = candidate.get("click_point")
    if not isinstance(selected, dict) or not isinstance(point, dict):
        return "action_gate_click_point_missing"
    if _safe_int(selected.get("x")) != _safe_int(point.get("x")) or _safe_int(selected.get("y")) != _safe_int(
        point.get("y")
    ):
        return "action_gate_click_point_mismatch"
    return None


def _blocked(result: dict[str, Any], reason: str) -> dict[str, Any]:
    result["blocked_reason"] = reason
    result["unsafe_prevented"] = True
    return result


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
