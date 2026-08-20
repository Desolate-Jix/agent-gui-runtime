from __future__ import annotations

import hashlib
import json

import pytest

from app.learn.calibration_artifact import (
    LearningCalibrationArtifactError,
    create_learning_calibration_artifact,
)


def _write_file(tmp_path, relative_path: str, content: bytes):
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _write_complete_trace(
    tmp_path,
    *,
    source_image,
    numbering_report,
    overlay,
    remaining_count: int = 0,
    resumable: bool = False,
):
    trace_path = tmp_path / "logs/traces/vision/calibration.json"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text(
        json.dumps(
            {
                "success": True,
                "request": {
                    "image_path": str(source_image),
                    "metadata": {
                        "two_stage_report_path": str(numbering_report),
                        "learning_interface_flow": True,
                        "no_live_click_authorization": True,
                    },
                },
                "result": {
                    "contract_version": "target_location_v1",
                    "image_path": str(source_image),
                    "learn_all_targets": {
                        "overlay_path": str(overlay),
                        "vista_coordinate_validation": {
                            "contract_version": "learn_vista_coordinate_validation_v1",
                            "validated_count": 3,
                            "failed_count": 1,
                            "batch": {
                                "contract_version": "learn_vista_calibration_batch_v1",
                                "resumable": resumable,
                                "completed_count": 4,
                                "remaining_count": remaining_count,
                            },
                        },
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return trace_path


def test_learning_calibration_artifact_binds_capture_numbering_and_trace(tmp_path) -> None:
    source_image = _write_file(
        tmp_path,
        "artifacts/screenshots/capture.png",
        b"capture",
    )
    numbering_report = _write_file(
        tmp_path,
        "artifacts/learning-runs/run-demo/stage2.json",
        b'{"contract_version":"stage2_v1"}',
    )
    overlay = _write_file(
        tmp_path,
        "artifacts/review-overlays/calibrated.png",
        b"overlay",
    )
    trace_path = _write_complete_trace(
        tmp_path,
        source_image=source_image,
        numbering_report=numbering_report,
        overlay=overlay,
    )

    result = create_learning_calibration_artifact(
        run_id="run-demo",
        trace_path=trace_path,
        source_image_path=source_image,
        numbering_report_path=numbering_report,
        overlay_path=overlay,
        project_root=tmp_path,
    )

    result_path = tmp_path / result["result_path"]
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["contract_version"] == "learning_calibration_result_v1"
    assert payload["source_image_sha256"] == hashlib.sha256(source_image.read_bytes()).hexdigest()
    assert payload["numbering_report_sha256"] == hashlib.sha256(
        numbering_report.read_bytes()
    ).hexdigest()
    assert payload["calibration_trace_sha256"] == hashlib.sha256(trace_path.read_bytes()).hexdigest()
    assert payload["overlay_sha256"] == hashlib.sha256(overlay.read_bytes()).hexdigest()
    assert payload["calibration_summary"] == {
        "validated_count": 3,
        "failed_count": 1,
        "completed_count": 4,
        "remaining_count": 0,
        "resumable": False,
    }
    assert payload["display_only"] is True
    assert payload["artifact_is_authorization"] is False
    assert payload["execute_binding_enabled"] is False
    assert payload["final_submit_forbidden"] is True


def test_learning_calibration_artifact_rejects_partial_batch(tmp_path) -> None:
    source_image = _write_file(tmp_path, "artifacts/screenshots/capture.png", b"capture")
    numbering_report = _write_file(
        tmp_path,
        "artifacts/learning-runs/run-demo/stage2.json",
        b"stage2",
    )
    overlay = _write_file(tmp_path, "artifacts/review-overlays/calibrated.png", b"overlay")
    trace_path = _write_complete_trace(
        tmp_path,
        source_image=source_image,
        numbering_report=numbering_report,
        overlay=overlay,
        remaining_count=2,
        resumable=True,
    )

    with pytest.raises(
        LearningCalibrationArtifactError,
        match="calibration trace is incomplete",
    ):
        create_learning_calibration_artifact(
            run_id="run-demo",
            trace_path=trace_path,
            source_image_path=source_image,
            numbering_report_path=numbering_report,
            overlay_path=overlay,
            project_root=tmp_path,
        )


def test_learning_calibration_artifact_rejects_missing_remaining_count(tmp_path) -> None:
    source_image = _write_file(tmp_path, "artifacts/screenshots/capture.png", b"capture")
    numbering_report = _write_file(
        tmp_path,
        "artifacts/learning-runs/run-demo/stage2.json",
        b"stage2",
    )
    overlay = _write_file(tmp_path, "artifacts/review-overlays/calibrated.png", b"overlay")
    trace_path = _write_complete_trace(
        tmp_path,
        source_image=source_image,
        numbering_report=numbering_report,
        overlay=overlay,
    )
    trace_payload = json.loads(trace_path.read_text(encoding="utf-8"))
    trace_payload["result"]["learn_all_targets"]["vista_coordinate_validation"]["batch"].pop(
        "remaining_count"
    )
    trace_path.write_text(
        json.dumps(trace_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    with pytest.raises(
        LearningCalibrationArtifactError,
        match="batch.remaining_count is required",
    ):
        create_learning_calibration_artifact(
            run_id="run-demo",
            trace_path=trace_path,
            source_image_path=source_image,
            numbering_report_path=numbering_report,
            overlay_path=overlay,
            project_root=tmp_path,
        )


def test_learning_calibration_artifact_rejects_trace_from_other_numbering_report(
    tmp_path,
) -> None:
    source_image = _write_file(tmp_path, "artifacts/screenshots/capture.png", b"capture")
    numbering_report = _write_file(
        tmp_path,
        "artifacts/learning-runs/run-demo/stage2.json",
        b"stage2",
    )
    stale_report = _write_file(
        tmp_path,
        "artifacts/learning-runs/run-demo/stale-stage2.json",
        b"stale",
    )
    overlay = _write_file(tmp_path, "artifacts/review-overlays/calibrated.png", b"overlay")
    trace_path = _write_complete_trace(
        tmp_path,
        source_image=source_image,
        numbering_report=stale_report,
        overlay=overlay,
    )

    with pytest.raises(
        LearningCalibrationArtifactError,
        match="numbering report does not match",
    ):
        create_learning_calibration_artifact(
            run_id="run-demo",
            trace_path=trace_path,
            source_image_path=source_image,
            numbering_report_path=numbering_report,
            overlay_path=overlay,
            project_root=tmp_path,
        )
