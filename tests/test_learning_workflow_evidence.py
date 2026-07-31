from __future__ import annotations

import hashlib
import json

import pytest

from app.learn.workflow_evidence import (
    LearningWorkflowEvidenceError,
    verify_learning_workflow_completion_evidence,
)


def _write_artifact(tmp_path, relative_path: str, content: bytes = b"workflow evidence"):
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _write_json_artifact(tmp_path, relative_path: str, payload: dict):
    return _write_artifact(
        tmp_path,
        relative_path,
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    )


def _previous_state_with_lineage(
    *,
    capture_sha256: str,
    source_graph_revision: str = "",
    numbering_report_sha256: str = "",
) -> dict:
    declared_revisions = {}
    if source_graph_revision:
        declared_revisions["source_graph_revision"] = source_graph_revision
    return {
        "stage_order": [
            "bind_capture",
            "screen_understanding",
            "numbered_map",
            "precise_calibration",
            "review_repair",
            "fusion",
            "page_details",
            "pathgraph_draft",
            "complete",
        ],
        "stages": {
            "bind_capture": {
                "evidence_refs": {
                    "workflow_lineage": {
                        "contract_version": "learning_workflow_lineage_v1",
                        "capture_anchor_sha256": capture_sha256,
                        "declared_revisions": {},
                    }
                }
            },
            "numbered_map": {
                "evidence_refs": {
                    "evidence_integrity": {
                        "artifacts": {
                            "report_path": {
                                "sha256": numbering_report_sha256,
                            }
                        }
                    },
                    "workflow_lineage": {
                        "contract_version": "learning_workflow_lineage_v1",
                        "capture_anchor_sha256": capture_sha256,
                        "declared_revisions": declared_revisions,
                    }
                }
            },
        },
    }


def test_workflow_evidence_verifies_allowed_artifact_and_records_sha256(tmp_path) -> None:
    artifact = _write_artifact(tmp_path, "artifacts/screenshots/capture.png")
    expected_sha256 = hashlib.sha256(artifact.read_bytes()).hexdigest()

    verified = verify_learning_workflow_completion_evidence(
        stage="bind_capture",
        outcome="completed",
        evidence_refs={
            "image_path": "artifacts/screenshots/capture.png",
            "screenshot_sha256": expected_sha256,
        },
        project_root=tmp_path,
    )

    integrity = verified["evidence_integrity"]
    assert integrity["contract_version"] == "learning_workflow_evidence_integrity_v1"
    assert integrity["verified"] is True
    assert integrity["artifacts"]["image_path"]["relative_path"] == "artifacts/screenshots/capture.png"
    assert integrity["artifacts"]["image_path"]["sha256"] == expected_sha256
    assert integrity["artifacts"]["image_path"]["size_bytes"] == len(artifact.read_bytes())
    lineage = verified["workflow_lineage"]
    assert lineage["contract_version"] == "learning_workflow_lineage_v1"
    assert lineage["status"] == "anchor_established"
    assert lineage["capture_anchor_sha256"] == expected_sha256


def test_workflow_evidence_rejects_missing_artifact(tmp_path) -> None:
    with pytest.raises(LearningWorkflowEvidenceError, match="evidence file does not exist"):
        verify_learning_workflow_completion_evidence(
            stage="bind_capture",
            outcome="completed",
            evidence_refs={"image_path": "artifacts/screenshots/missing.png"},
            project_root=tmp_path,
        )


def test_workflow_evidence_rejects_path_outside_runtime_roots(tmp_path) -> None:
    outside = _write_artifact(tmp_path, "private/capture.png")

    with pytest.raises(LearningWorkflowEvidenceError, match="outside allowed runtime roots"):
        verify_learning_workflow_completion_evidence(
            stage="bind_capture",
            outcome="completed",
            evidence_refs={"image_path": str(outside)},
            project_root=tmp_path,
        )


def test_workflow_evidence_rejects_checksum_mismatch(tmp_path) -> None:
    _write_artifact(tmp_path, "logs/learning/trial.json", b'{"ok": true}')

    with pytest.raises(LearningWorkflowEvidenceError, match="checksum mismatch"):
        verify_learning_workflow_completion_evidence(
            stage="screen_understanding",
            outcome="completed",
            evidence_refs={
                "trial_path": "logs/learning/trial.json",
                "trial_path_sha256": "0" * 64,
            },
            project_root=tmp_path,
        )


def test_non_completed_transition_does_not_require_filesystem_evidence(tmp_path) -> None:
    evidence = {"image_path": "artifacts/screenshots/not-created-yet.png"}

    verified = verify_learning_workflow_completion_evidence(
        stage="bind_capture",
        outcome="running",
        evidence_refs=evidence,
        project_root=tmp_path,
    )

    assert verified == evidence
    assert verified is not evidence


def test_workflow_evidence_verifies_declared_capture_against_bind_anchor(tmp_path) -> None:
    screenshot = _write_artifact(tmp_path, "artifacts/screenshots/capture.png", b"same capture")
    capture_sha256 = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    _write_json_artifact(
        tmp_path,
        "artifacts/learning-runs/trial.json",
        {
            "contract_version": "learning_trial_v1",
            "observe_bundle": {"source_image_path": str(screenshot)},
            "two_stage_understanding": {
                "stage2_numbering": {
                    "final_numbering": {
                        "capture_sha256": capture_sha256,
                        "source_graph_revision": "source-revision-1",
                    }
                }
            },
        },
    )

    verified = verify_learning_workflow_completion_evidence(
        stage="screen_understanding",
        outcome="completed",
        evidence_refs={"trial_path": "artifacts/learning-runs/trial.json"},
        project_root=tmp_path,
        previous_state=_previous_state_with_lineage(capture_sha256=capture_sha256),
    )

    lineage = verified["workflow_lineage"]
    assert lineage["status"] == "verified"
    assert lineage["capture_anchor_sha256"] == capture_sha256
    assert lineage["declared_capture_sha256"] == capture_sha256
    assert lineage["declared_revisions"]["source_graph_revision"] == "source-revision-1"
    assert lineage["artifact_fields_checked"] == ["trial_path"]


def test_workflow_evidence_rejects_artifact_from_another_capture(tmp_path) -> None:
    bound_screenshot = _write_artifact(tmp_path, "artifacts/screenshots/bound.png", b"bound")
    stale_screenshot = _write_artifact(tmp_path, "artifacts/screenshots/stale.png", b"stale")
    bound_sha256 = hashlib.sha256(bound_screenshot.read_bytes()).hexdigest()
    stale_sha256 = hashlib.sha256(stale_screenshot.read_bytes()).hexdigest()
    _write_json_artifact(
        tmp_path,
        "artifacts/learning-runs/stale-trial.json",
        {
            "observe_bundle": {"source_image_path": str(stale_screenshot)},
            "capture_sha256": stale_sha256,
        },
    )

    with pytest.raises(LearningWorkflowEvidenceError, match="capture lineage mismatch"):
        verify_learning_workflow_completion_evidence(
            stage="screen_understanding",
            outcome="completed",
            evidence_refs={"trial_path": "artifacts/learning-runs/stale-trial.json"},
            project_root=tmp_path,
            previous_state=_previous_state_with_lineage(capture_sha256=bound_sha256),
        )


def test_workflow_evidence_rejects_conflicting_graph_revision(tmp_path) -> None:
    screenshot = _write_artifact(tmp_path, "artifacts/screenshots/capture.png", b"capture")
    capture_sha256 = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    _write_json_artifact(
        tmp_path,
        "artifacts/learning-runs/final-stage2.json",
        {
            "source_identity": {
                "contract_version": "learning_repaired_source_identity_v1",
                "capture_sha256": capture_sha256,
                "screenshot_path": str(screenshot),
                "source_graph_revision": "source-revision-2",
            }
        },
    )
    _write_artifact(tmp_path, "artifacts/review-overlays/final.png", b"overlay")

    with pytest.raises(LearningWorkflowEvidenceError, match="source_graph_revision lineage mismatch"):
        verify_learning_workflow_completion_evidence(
            stage="review_repair",
            outcome="completed",
            evidence_refs={
                "final_stage2_report_path": "artifacts/learning-runs/final-stage2.json",
                "final_overlay_path": "artifacts/review-overlays/final.png",
            },
            project_root=tmp_path,
            previous_state=_previous_state_with_lineage(
                capture_sha256=capture_sha256,
                source_graph_revision="source-revision-1",
            ),
        )


def test_workflow_evidence_marks_legacy_json_lineage_not_covered(tmp_path) -> None:
    screenshot = _write_artifact(tmp_path, "artifacts/screenshots/capture.png", b"capture")
    capture_sha256 = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    _write_json_artifact(
        tmp_path,
        "artifacts/learning-runs/legacy-trial.json",
        {"contract_version": "legacy_learning_trial_v1", "status": "completed"},
    )

    verified = verify_learning_workflow_completion_evidence(
        stage="screen_understanding",
        outcome="completed",
        evidence_refs={"trial_path": "artifacts/learning-runs/legacy-trial.json"},
        project_root=tmp_path,
        previous_state=_previous_state_with_lineage(capture_sha256=capture_sha256),
    )

    lineage = verified["workflow_lineage"]
    assert lineage["status"] == "not_covered"
    assert lineage["capture_anchor_sha256"] == capture_sha256
    assert lineage["declared_capture_sha256"] == ""
    assert lineage["not_covered_reason"] == "artifact_did_not_declare_capture_identity"


def test_calibration_result_must_match_numbered_map_report(tmp_path) -> None:
    screenshot = _write_artifact(tmp_path, "artifacts/screenshots/capture.png", b"capture")
    capture_sha256 = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    numbering_report = _write_artifact(
        tmp_path,
        "artifacts/learning-runs/stage2.json",
        b"numbering",
    )
    numbering_sha256 = hashlib.sha256(numbering_report.read_bytes()).hexdigest()
    _write_json_artifact(
        tmp_path,
        "artifacts/learning-runs/calibration-result.json",
        {
            "contract_version": "learning_calibration_result_v1",
            "source_image_path": str(screenshot),
            "source_image_sha256": capture_sha256,
            "numbering_report_path": str(numbering_report),
            "numbering_report_sha256": numbering_sha256,
        },
    )
    _write_artifact(tmp_path, "artifacts/review-overlays/calibrated.png", b"overlay")

    verified = verify_learning_workflow_completion_evidence(
        stage="precise_calibration",
        outcome="completed",
        evidence_refs={
            "result_path": "artifacts/learning-runs/calibration-result.json",
            "overlay_path": "artifacts/review-overlays/calibrated.png",
        },
        project_root=tmp_path,
        previous_state=_previous_state_with_lineage(
            capture_sha256=capture_sha256,
            numbering_report_sha256=numbering_sha256,
        ),
    )

    lineage = verified["workflow_lineage"]
    assert lineage["status"] == "verified"
    assert lineage["source_numbering_report_sha256"] == numbering_sha256


def test_calibration_result_rejects_other_numbered_map_report(tmp_path) -> None:
    screenshot = _write_artifact(tmp_path, "artifacts/screenshots/capture.png", b"capture")
    capture_sha256 = hashlib.sha256(screenshot.read_bytes()).hexdigest()
    _write_json_artifact(
        tmp_path,
        "artifacts/learning-runs/calibration-result.json",
        {
            "contract_version": "learning_calibration_result_v1",
            "source_image_path": str(screenshot),
            "source_image_sha256": capture_sha256,
            "numbering_report_sha256": "b" * 64,
        },
    )
    _write_artifact(tmp_path, "artifacts/review-overlays/calibrated.png", b"overlay")

    with pytest.raises(
        LearningWorkflowEvidenceError,
        match="numbering report lineage mismatch",
    ):
        verify_learning_workflow_completion_evidence(
            stage="precise_calibration",
            outcome="completed",
            evidence_refs={
                "result_path": "artifacts/learning-runs/calibration-result.json",
                "overlay_path": "artifacts/review-overlays/calibrated.png",
            },
            project_root=tmp_path,
            previous_state=_previous_state_with_lineage(
                capture_sha256=capture_sha256,
                numbering_report_sha256="a" * 64,
            ),
        )
