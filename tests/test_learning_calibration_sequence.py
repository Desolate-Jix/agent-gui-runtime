from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from app.learn.calibration_sequence import (
    LearningCalibrationSequenceError,
    run_learning_calibration_sequence,
)
from app.learn.recognition.uei.canonical import seal_immutable


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


def _hybrid_sequence_payload() -> dict[str, Any]:
    capture_identity = {
        "capture_id": "capture/hybrid-calibration",
        "screenshot_sha256": "a" * 64,
        "artifact_sha256": "a" * 64,
        "workflow_revision": "9",
        "image_size": {"width": 400, "height": 300},
        "capture_lineage_ref": {
            "id": "capture-lineage/hybrid-calibration",
            "content_sha256": "b" * 64,
        },
    }
    fusion = seal_immutable(
        {
            "contract_version": "hybrid_fusion_result_v1",
            "capture_identity": deepcopy(capture_identity),
            "config_sha256": "c" * 64,
            "candidates": [
                {
                    "candidate_id": candidate_id,
                    "bbox_original": bbox,
                    "coordinate_space": "capture_pixel_xyxy",
                    "state": "BOUND",
                    "vista_eligible": True,
                }
                for candidate_id, bbox in (
                    ("candidate/one", [40, 50, 100, 90]),
                    ("candidate/two", [180, 120, 260, 180]),
                )
            ],
        }
    )
    bundle = seal_immutable(
        {
            "contract_version": "hybrid_capture_bundle_v1",
            "capture_identity": deepcopy(capture_identity),
            "workflow_revision": 9,
        }
    )
    payload = _sequence_payload()
    payload.update(
        {
            "learning_pipeline_mode": "hybrid_v1_1",
            "candidate_count": 2,
            "calibration_source_revision": "c" * 64,
            "hybrid_fusion_result": fusion,
            "capture_bundle": bundle,
        }
    )
    payload["locate_payload"]["metadata"].pop("two_stage_report_path")
    return payload


def _hybrid_locate_response(
    requests: list[dict[str, Any]],
    *,
    completed_ids: list[str],
    remaining_count: int,
    resumable: bool,
) -> dict[str, Any]:
    request_by_id = {item["candidate_id"]: item for item in requests}
    results = []
    for candidate_id in completed_ids:
        request = request_by_id[candidate_id]
        results.append(
            {
                "contract_version": "learn_vista_target_coordinate_validation_v1",
                "status": "needs_review",
                "candidate_id": candidate_id,
                "final_numbering_revision": request["source_revision"],
                "hybrid_vista_request": deepcopy(request),
                "hybrid_vista_proposal": {
                    "candidate_id": candidate_id,
                    "candidate_bbox_ref": deepcopy(request["candidate_bbox_ref"]),
                    "roi_ref": deepcopy(request["roi_ref"]),
                    "affine_transform_ref": deepcopy(request["affine_transform_ref"]),
                    "source_revision": request["source_revision"],
                    "capture_sha256": request["capture_sha256"],
                    "status": "PROPOSED",
                    "review_status": "REVIEW_REQUIRED",
                },
            }
        )
    return {
        "success": True,
        "message": "located",
        "data": {
            "result": {
                "trace_path": "logs/traces/vision/hybrid-locate.json",
                "learn_all_targets": {
                    "overlay_path": "artifacts/review-overlays/hybrid-locate.png",
                    "vista_coordinate_validation": {
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


def test_hybrid_calibration_batch_resume_preserves_exact_request_lineage() -> None:
    submitted_batches: list[list[dict[str, Any]]] = []

    def locate(payload: dict[str, Any]) -> dict[str, Any]:
        requests = deepcopy(payload["metadata"]["learn_hybrid_vista_requests"])
        submitted_batches.append(requests)
        if len(submitted_batches) == 1:
            return _hybrid_locate_response(
                requests,
                completed_ids=["candidate/one"],
                remaining_count=1,
                resumable=True,
            )
        return _hybrid_locate_response(
            requests,
            completed_ids=["candidate/one", "candidate/two"],
            remaining_count=0,
            resumable=False,
        )

    response = run_learning_calibration_sequence(
        _hybrid_sequence_payload(),
        locate_runner=locate,
        profile_loader=lambda _stage, _profile_id: {"profile_id": "vista-test"},
        resource_preflight_builder=_normal_preflight,
    )

    assert response["success"] is True
    first_by_id = {item["candidate_id"]: item for item in submitted_batches[0]}
    second_by_id = {item["candidate_id"]: item for item in submitted_batches[1]}
    for field in ("candidate_bbox_ref", "roi_ref", "affine_transform_ref", "source_revision", "capture_sha256"):
        assert second_by_id["candidate/one"][field] == first_by_id["candidate/one"][field]
    resume = submitted_batches and response["data"]["result"]["calibration_sequence"]
    assert resume["hybrid_vista_results"][0]["hybrid_vista_request"] == first_by_id["candidate/one"]


def test_hybrid_calibration_cancellation_stops_before_vista_acquisition() -> None:
    class Cancelled:
        @staticmethod
        def is_set() -> bool:
            return True

    locate_called = False

    def locate(_payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal locate_called
        locate_called = True
        return {}

    response = run_learning_calibration_sequence(
        _hybrid_sequence_payload(),
        locate_runner=locate,
        profile_loader=lambda _stage, _profile_id: {"profile_id": "vista-test"},
        resource_preflight_builder=_normal_preflight,
        cancellation_event=Cancelled(),
    )

    assert response["success"] is False
    assert response["data"]["failure_category"] == "calibration_cancelled"
    assert response["data"]["remaining_count"] == 2
    assert locate_called is False
