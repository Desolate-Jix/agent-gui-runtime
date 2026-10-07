"""接管处置必须由预览明确选择，旧记录保持严格兼容。"""
from copy import deepcopy

import pytest

from app.learning_memory.workflow_control import validate_request
from app.learning_memory.workflow_recovery_import import _prepared_marker


def preview_request():
    return {"action": "takeover_preview", "admission_request_id": "epoch-admission",
            "source_run_id": "trial-" + "a" * 64}


def prepared_marker(version="workflow_recovery_import.v1"):
    marker = {"contract_version": version, "claim_id": "c" * 64, "request_id": "takeover-one",
        "source_session_name": "session-" + "a" * 32, "source_run_id": "trial-" + "a" * 64,
        "source_step_id": "search", "source_execution_request_id": "original-input",
        "source_program_sha256": "d" * 64, "source_settlement_sha256": "e" * 64,
        "effect_evidence_ref": "workflow-effects/effect.json", "effect_evidence_sha256": "f" * 64,
        "verified_history_sha256": "b" * 64, "consumed_step_ids": ["prefix"], "status": "prepared"}
    return {"trial_state": {"recovery_import": marker}, "admission_request_id": "epoch-admission",
            "admission_record_sha256": "1" * 64, "source_files": {}, "new_input_files": {},
            "effect_files": {}}


@pytest.mark.parametrize("resolution", ["adopt_success", "resume_unexecuted"])
def test_public_preview_accepts_only_explicit_supported_resolution(resolution):
    request = {**preview_request(), "resolution": resolution}
    assert validate_request(request) == request


def test_omitted_resolution_keeps_original_request_and_marker_unchanged():
    request = preview_request()
    original = deepcopy(request)
    assert validate_request(request) == original and request == original
    prepared = prepared_marker()
    before = deepcopy(prepared)
    assert _prepared_marker(prepared) == prepared["trial_state"]["recovery_import"]
    assert prepared == before and "resolution" not in prepared["trial_state"]["recovery_import"]


@pytest.mark.parametrize("resolution", [None, True, 0, "", "retry", [], {}, "RESUME_UNEXECUTED"])
def test_invalid_resolution_is_rejected_as_a_clear_value_error(resolution):
    with pytest.raises(ValueError):
        validate_request({**preview_request(), "resolution": resolution})


def test_commit_cannot_override_the_signed_preview_choice():
    with pytest.raises(ValueError):
        validate_request({"action": "takeover_commit", "preview_request_id": "takeover-one",
            "preview_sha256": "a" * 64, "mode": "until_wait", "resolution": "resume_unexecuted"})


def test_v2_marker_accepts_only_the_explicit_unexecuted_resolution():
    prepared = prepared_marker("workflow_recovery_import.v2")
    marker = prepared["trial_state"]["recovery_import"]
    marker["resolution"] = "resume_unexecuted"
    marker["consumed_step_ids"] = []
    assert _prepared_marker(prepared) == marker


@pytest.mark.parametrize("change", ["v1_choice", "v2_missing", "v2_adopt", "v2_unknown", "v3", "extra", "status"])
def test_marker_version_and_choice_cannot_be_reinterpreted(change):
    prepared = prepared_marker()
    marker = prepared["trial_state"]["recovery_import"]
    if change == "v1_choice":
        marker["resolution"] = "resume_unexecuted"
    elif change in {"v2_missing", "v2_adopt", "v2_unknown"}:
        marker["contract_version"] = "workflow_recovery_import.v2"
        if change != "v2_missing":
            marker["resolution"] = "adopt_success" if change == "v2_adopt" else "retry"
    elif change == "v3":
        marker["contract_version"] = "workflow_recovery_import.v3"
    elif change == "extra":
        marker["automatic_retry_allowed"] = True
    else:
        marker["status"] = "ready"
    with pytest.raises(ValueError):
        _prepared_marker(prepared)

@pytest.mark.parametrize("version,choice", [
    ("workflow_recovery_import.v1", "adopt_success"),
    ("workflow_recovery_import.v2", "resume_unexecuted")])
def test_same_preview_control_cannot_change_persisted_choice(tmp_path, version, choice):
    from hashlib import sha256
    from app.core.json_snapshot import write_json_snapshot
    from app.desktop_review.external_mapping import canonical_json_bytes
    from app.learning_memory.workflow_takeover_controls import _matches, preview_path
    session = tmp_path / ("session-" + "a" * 32)
    session.mkdir()
    prepared = prepared_marker(version)
    if choice == "resume_unexecuted":
        prepared["trial_state"]["recovery_import"]["resolution"] = choice
    payload = {"request_id": "takeover-one", "admission_request_id": "epoch-admission",
        "source_run_id": "trial-" + "a" * 64, "prepared": prepared, "observation": {}}
    path = preview_path(session, "takeover-one")
    path.parent.mkdir()
    write_json_snapshot(path, {"contract_version": "workflow_takeover_preview.v1", "payload": payload,
        "preview_sha256": sha256(canonical_json_bytes(payload)).hexdigest()})
    scope = {"preview_request_id": "takeover-one", "admission_request_id": "epoch-admission",
             "source_run_id": "trial-" + "a" * 64}
    original = path.read_bytes()
    command = {"kind": "learning_workflow", "request": {**preview_request(), "resolution": choice}}
    assert _matches(session, "takeover-one", command, scope)
    command["request"]["resolution"] = "adopt_success" if choice == "resume_unexecuted" else "resume_unexecuted"
    assert not _matches(session, "takeover-one", command, scope)
    assert path.read_bytes() == original
