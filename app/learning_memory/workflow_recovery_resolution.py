"""恢复选择和版本记录采用同一严格合同。"""

MARKER_KEYS = {"contract_version", "claim_id", "request_id", "source_session_name", "source_run_id",
    "source_step_id", "source_execution_request_id", "source_program_sha256", "source_settlement_sha256",
    "effect_evidence_ref", "effect_evidence_sha256", "verified_history_sha256", "consumed_step_ids", "status"}


def validate_resolution(value):
    if not isinstance(value, str) or value not in {"adopt_success", "resume_unexecuted"}:
        raise ValueError("workflow_takeover_resolution_invalid")
    return value


def marker_resolution(marker):
    if not isinstance(marker, dict) or marker.get("status") != "prepared":
        raise ValueError("workflow_takeover_import_marker_invalid")
    if marker.get("contract_version") == "workflow_recovery_import.v1" and set(marker) == MARKER_KEYS:
        return "adopt_success"
    if (marker.get("contract_version") == "workflow_recovery_import.v2"
            and set(marker) == MARKER_KEYS | {"resolution"}
            and marker.get("resolution") == "resume_unexecuted"):
        return "resume_unexecuted"
    raise ValueError("workflow_takeover_import_marker_invalid")
