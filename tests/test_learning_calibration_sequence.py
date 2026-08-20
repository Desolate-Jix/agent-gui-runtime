from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from app.learn.calibration_sequence import (
    LearningCalibrationSequenceError,
    run_learning_calibration_sequence,
)


def _locate_response(
    *,
    completed_ids: list[str],
    remaining_count: int,
    resumable: bool,
    abort_reason: str = "",
) -> dict[str, Any]:
    results = [
        {
            "contract_version": "learn_vista_coordinate_result_v1",
            "status": "completed",
            "failure_category": "",
            "candidate_id": candidate_id,
            "final_numbering_revision": "revision-1",
            "label": candidate_id,
            "role": "button",
            "bbox": {"x": 10, "y": 20, "width": 30, "height": 40},
            "updated_click_point": {"x": 20, "y": 30},
            "precise_locator_evidence": {
                "selected_candidate": {"candidate_id": candidate_id},
                "dry_run_gate": {"allowed": True},
                "evidence_availability": "covered",
            },
        }
        for candidate_id in completed_ids
    ]
    return {
        "success": True,
        "message": "located",
        "data": {
            "result": {
                "trace_path": "logs/traces/vision/locate.json",
                "learn_all_targets": {
                    "overlay_path": "artifacts/review-overlays/locate.png",
                    "vista_coordinate_validation": {
                        "abort_reason": abort_reason,
                        "results": results,
                        "batch": {
                            "completed_candidate_ids": completed_ids,
                            "completed_count": len(completed_ids),
                            "remaining_count": remaining_count,
                            "resumable": resumable,
                        },
                    },
                },
            }
        },
    }


def _sequence_payload() -> dict[str, Any]:
    return {
        "contract_version": "learning_calibration_sequence_request_v1",
        "profile_id": "vista-test",
        "candidate_count": 2,
        "calibration_source_revision": "revision-1",
        "locate_payload": {
            "goal": "learn all visible controls",
            "provider_mode": "local_grounding",
            "capture_live": False,
            "image_path": "artifacts/screenshots/source.png",
            "dry_run": True,
            "trace": True,
            "metadata": {
                "learn_all_targets": True,
                "two_stage_report_path": "artifacts/learning-runs/stage2.json",
            },
        },
    }


def _normal_preflight(_profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "resource_mode": "normal",
        "model_launch_allowed": True,
        "recommended_batch_size": 8,
    }


def test_calibration_sequence_completes_single_batch() -> None:
    requests: list[dict[str, Any]] = []

    def locate(payload: dict[str, Any]) -> dict[str, Any]:
        requests.append(deepcopy(payload))
        return _locate_response(
            completed_ids=["candidate-1", "candidate-2"],
            remaining_count=0,
            resumable=False,
        )

    response = run_learning_calibration_sequence(
        _sequence_payload(),
        locate_runner=locate,
        profile_loader=lambda _stage, _profile_id: {"profile_id": "vista-test"},
        resource_preflight_builder=_normal_preflight,
    )

    assert response["success"] is True
    result = response["data"]["result"]
    assert result["calibration_sequence"]["batch_count"] == 1
    assert result["calibration_sequence"]["completed_count"] == 2
    assert result["calibration_sequence"]["remaining_count"] == 0
    assert result["calibration_sequence"]["artifact_inputs"] == {
        "trace_path": "logs/traces/vision/locate.json",
        "source_image_path": "artifacts/screenshots/source.png",
        "numbering_report_path": "artifacts/learning-runs/stage2.json",
        "overlay_path": "artifacts/review-overlays/locate.png",
    }
    validation = requests[0]["metadata"]["learn_vista_coordinate_validation"]
    assert validation["batch_size"] == 8
    assert validation["resume_results"] == []


def test_calibration_sequence_rejects_locate_payload_without_goal() -> None:
    payload = _sequence_payload()
    payload["locate_payload"].pop("goal")

    with pytest.raises(
        LearningCalibrationSequenceError,
        match="locate_payload goal is required",
    ):
        run_learning_calibration_sequence(payload)


def test_calibration_sequence_resumes_with_completed_evidence() -> None:
    requests: list[dict[str, Any]] = []
    responses = [
        _locate_response(
            completed_ids=["candidate-1"],
            remaining_count=1,
            resumable=True,
        ),
        _locate_response(
            completed_ids=["candidate-1", "candidate-2"],
            remaining_count=0,
            resumable=False,
        ),
    ]

    def locate(payload: dict[str, Any]) -> dict[str, Any]:
        requests.append(deepcopy(payload))
        return responses.pop(0)

    response = run_learning_calibration_sequence(
        _sequence_payload(),
        locate_runner=locate,
        profile_loader=lambda _stage, _profile_id: {"profile_id": "vista-test"},
        resource_preflight_builder=_normal_preflight,
    )

    assert response["success"] is True
    assert response["data"]["result"]["calibration_sequence"]["batch_count"] == 2
    second_validation = requests[1]["metadata"][
        "learn_vista_coordinate_validation"
    ]
    assert [
        item["candidate_id"] for item in second_validation["resume_results"]
    ] == ["candidate-1"]
    assert second_validation["resume_revision"] == "revision-1"


def test_calibration_sequence_rejects_resumable_batch_without_progress() -> None:
    response = run_learning_calibration_sequence(
        _sequence_payload(),
        locate_runner=lambda _payload: _locate_response(
            completed_ids=[],
            remaining_count=2,
            resumable=True,
        ),
        profile_loader=lambda _stage, _profile_id: {"profile_id": "vista-test"},
        resource_preflight_builder=_normal_preflight,
    )

    assert response["success"] is False
    assert response["data"]["failure_category"] == "calibration_batch_no_progress"
    assert response["data"]["batch_count"] == 1


def test_calibration_sequence_stops_when_resource_preflight_is_critical() -> None:
    locate_called = False

    def locate(_payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal locate_called
        locate_called = True
        return {}

    response = run_learning_calibration_sequence(
        _sequence_payload(),
        locate_runner=locate,
        profile_loader=lambda _stage, _profile_id: {"profile_id": "vista-test"},
        resource_preflight_builder=lambda _profile: {
            "resource_mode": "critical",
            "model_launch_allowed": False,
            "recommended_batch_size": 1,
        },
    )

    assert response["success"] is False
    assert response["data"]["failure_category"] == "calibration_batch_resource_blocked"
    assert locate_called is False


def test_calibration_sequence_retries_transient_model_busy_without_losing_results() -> None:
    responses = [
        _locate_response(
            completed_ids=["candidate-1"],
            remaining_count=1,
            resumable=True,
            abort_reason="model_busy",
        ),
        _locate_response(
            completed_ids=["candidate-1", "candidate-2"],
            remaining_count=0,
            resumable=False,
        ),
    ]
    sleeps: list[float] = []

    response = run_learning_calibration_sequence(
        _sequence_payload(),
        locate_runner=lambda _payload: responses.pop(0),
        profile_loader=lambda _stage, _profile_id: {"profile_id": "vista-test"},
        resource_preflight_builder=_normal_preflight,
        model_status_checker=lambda _profile: {"status": "running"},
        sleep=lambda seconds: sleeps.append(seconds),
    )

    assert response["success"] is True
    sequence = response["data"]["result"]["calibration_sequence"]
    assert sequence["transient_recovery_attempts"] == 1
    assert sequence["completed_count"] == 2
    assert sleeps == []
