from __future__ import annotations

import hashlib
from pathlib import Path

from app.operation.form_file_upload_executor import (
    execute_form_file_upload,
    verify_form_file_upload_effect,
)


def _candidate(*, capture_id: str = "capture-current") -> dict:
    return {
        "candidate_id": "resume-upload",
        "question_id": "resume",
        "bbox": {"x": 100, "y": 220, "w": 260, "h": 44},
        "click_point": {"x": 230, "y": 242},
        "candidate_freshness": {
            "contract_version": "action_candidate_freshness_v1",
            "capture_id": capture_id,
            "viewport_size": {"width": 720, "height": 760},
            "source": "windows_uia",
            "freshness": "current_capture",
        },
    }


def _gate(*, allowed: bool = True, semantic_action: str = "upload_file") -> dict:
    return {
        "contract_version": "pre_click_decision_v1",
        "allowed": allowed,
        "semantic_action": semantic_action,
        "selected_candidate_id": "resume-upload",
        "selected_click_point": {"x": 230, "y": 242},
    }


def _reviewed_file(path: Path, *, approved: bool = True, sha256: str | None = None) -> dict:
    payload = path.read_bytes()
    return {
        "contract_version": "reviewed_file_evidence_v1",
        "absolute_path": str(path.resolve()),
        "sha256": sha256 or hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
        "extension": path.suffix.casefold(),
        "human_approved": approved,
        "single_use": True,
        "artifact_is_authorization": False,
    }


def _execute(path: Path, dispatch, **overrides) -> dict:
    candidate = overrides.pop("candidate", _candidate())
    payload = {
        "question": {
            "contract_version": "form_question_contract_v1",
            "question_id": "resume",
            "label": "Upload resume",
            "field_type": "file_upload",
            "risk": "reviewed_file_upload",
            "source_capture_id": "capture-current",
        },
        "reviewed_file": _reviewed_file(path),
        "candidate": candidate,
        "current_capture_id": "capture-current",
        "current_viewport_size": {"width": 720, "height": 760},
        "action_gate": _gate(),
        "dispatch": dispatch,
    }
    payload.update(overrides)
    return execute_form_file_upload(**payload)


def test_reviewed_current_file_upload_dispatches_once_without_leaking_path(tmp_path: Path) -> None:
    file_path = tmp_path / "synthetic_resume.pdf"
    file_path.write_bytes(b"%PDF-1.4\nsynthetic fixture\n%%EOF\n")
    calls: list[dict] = []

    result = _execute(file_path, lambda **kwargs: calls.append(kwargs) or {"success": True})

    assert calls == [
        {
            "file_path": str(file_path.resolve()),
            "x": 230,
            "y": 242,
            "click_before_selecting": True,
            "submit": False,
        }
    ]
    assert result["contract_version"] == "form_file_upload_action_result_v1"
    assert result["dispatch_attempted"] is True
    assert result["dispatch_success"] is True
    assert result["upload_effect_success"] is None
    assert result["file_sha256"] == hashlib.sha256(file_path.read_bytes()).hexdigest()
    assert result["file_size_bytes"] == file_path.stat().st_size
    assert result["file_extension"] == ".pdf"
    assert str(file_path.resolve()) not in str(result)
    assert file_path.name not in str(result)


def test_unapproved_or_changed_file_is_rejected_before_dispatch(tmp_path: Path) -> None:
    file_path = tmp_path / "resume.pdf"
    file_path.write_bytes(b"fixture")
    calls: list[dict] = []

    unapproved = _execute(
        file_path,
        lambda **kwargs: calls.append(kwargs),
        reviewed_file=_reviewed_file(file_path, approved=False),
    )
    changed = _execute(
        file_path,
        lambda **kwargs: calls.append(kwargs),
        reviewed_file=_reviewed_file(file_path, sha256="0" * 64),
    )

    assert calls == []
    assert unapproved["blocked_reason"] == "file_not_human_approved"
    assert changed["blocked_reason"] == "reviewed_file_checksum_mismatch"


def test_upload_rejects_stale_candidate_wrong_gate_and_unsupported_extension(tmp_path: Path) -> None:
    pdf_path = tmp_path / "resume.pdf"
    pdf_path.write_bytes(b"fixture")
    exe_path = tmp_path / "resume.exe"
    exe_path.write_bytes(b"not allowed")
    calls: list[dict] = []

    stale = _execute(
        pdf_path,
        lambda **kwargs: calls.append(kwargs),
        candidate=_candidate(capture_id="capture-old"),
    )
    wrong_gate = _execute(
        pdf_path,
        lambda **kwargs: calls.append(kwargs),
        action_gate=_gate(semantic_action="final_submit"),
    )
    extension = _execute(exe_path, lambda **kwargs: calls.append(kwargs))

    assert calls == []
    assert stale["blocked_reason"] == "candidate_freshness_rejected"
    assert wrong_gate["blocked_reason"] == "action_gate_semantic_action_mismatch"
    assert extension["blocked_reason"] == "file_extension_not_allowed"


def test_upload_effect_requires_new_capture_matching_name_hash_and_size(tmp_path: Path) -> None:
    file_path = tmp_path / "synthetic_resume.pdf"
    file_path.write_bytes(b"fixture")
    dispatched = _execute(file_path, lambda **kwargs: {"success": True})
    filename_hash = hashlib.sha256(file_path.name.encode("utf-8")).hexdigest()

    verified = verify_form_file_upload_effect(
        upload_result=dispatched,
        current_capture_id="capture-after-upload",
        observed_question_id="resume",
        observed_filename_hash=filename_hash,
        observed_size_bytes=file_path.stat().st_size,
    )
    stale = verify_form_file_upload_effect(
        upload_result=dispatched,
        current_capture_id="capture-current",
        observed_question_id="resume",
        observed_filename_hash=filename_hash,
        observed_size_bytes=file_path.stat().st_size,
    )
    mismatch = verify_form_file_upload_effect(
        upload_result=dispatched,
        current_capture_id="capture-after-upload",
        observed_question_id="resume",
        observed_filename_hash="f" * 64,
        observed_size_bytes=file_path.stat().st_size,
    )

    assert verified["verified"] is True
    assert verified["status"] == "file_upload_effect_verified"
    assert stale["verified"] is False
    assert "upload_reobserve_required" in stale["failure_reasons"]
    assert mismatch["verified"] is False
    assert "observed_filename_mismatch" in mismatch["failure_reasons"]
    assert str(file_path.resolve()) not in str(verified)
    assert file_path.name not in str(verified)
