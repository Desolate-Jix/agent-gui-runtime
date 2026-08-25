from __future__ import annotations

from copy import deepcopy
from pathlib import Path
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


def _hybrid_sequence_payload(tmp_path) -> dict[str, Any]:
    from app.core.model_server import build_qwen_cleanup_receipt
    from app.learn.hybrid.capture import load_and_verify_hybrid_capture_bundle, seal_hybrid_capture_bundle
    from app.learn.hybrid.contracts import load_hybrid_config
    from app.learn.hybrid.fusion import fuse_hybrid_candidates
    from app.learn.hybrid.qwen_binding import parse_qwen_candidate_bindings
    from tests.test_learn_hybrid_capture import _context, _identity, _window
    from tests.test_learn_hybrid_fusion import _inventory_for_capture
    from tests.test_learn_hybrid_qwen_binding import _raw_for

    run_id, revision = "run-hybrid-calibration", 9
    image, identity = _identity(tmp_path, run_id=run_id, revision=revision, name="hybrid.png", size=(400, 300))
    saved = seal_hybrid_capture_bundle(project_root=tmp_path, image_path=image, run_id=run_id,
        workflow_revision=revision, window_binding=_window(),
        ocr_uia_context=_context(tmp_path, identity, run_id=run_id, revision=revision),
        capture_envelope=identity.capture_envelope)
    bundle = load_and_verify_hybrid_capture_bundle(project_root=tmp_path, bundle_ref=saved["bundle_ref"],
        expected_run_id=run_id, expected_workflow_revision=revision)
    inventory = seal_immutable(_inventory_for_capture(bundle["capture_identity"], candidate_count=2))
    bindings = seal_immutable(parse_qwen_candidate_bindings(_raw_for(inventory), inventory, context_ref=bundle["context_ref"]))
    fusion = seal_immutable(fuse_hybrid_candidates(config=load_hybrid_config(Path(__file__).resolve().parents[1]),
        capture_bundle=bundle, omni_inventory=inventory, qwen_bindings=bindings))
    process = {"pid": 4123, "create_time": 100.5, "executable": "qwen-server.exe"}
    lease = {"contract_version": "qwen_model_server_lease_v1", "lease_id": "lease-calibration",
        "owner_request_id": "request-calibration", "profile_id": "qwen", "incarnation_id": "inc-calibration",
        "server_base_url": "http://127.0.0.1:12345", "server_model_id": "qwen", "profile_sha256": "1" * 64,
        "server_process_identity": process}
    receipt = build_qwen_cleanup_receipt(model_lease=lease, release_result={"status":"released", "lease":lease,
        "shared_server_retained":False, "server_termination":"verified_exact_process_exited",
        "release":{"status":"proven_absent", "identity":process}, "process_identity":process})
    payload = _sequence_payload()
    payload.update(
        {
            "learning_pipeline_mode": "hybrid_v1_1",
            "candidate_count": 2,
            "calibration_source_revision": fusion["config_sha256"],
            "hybrid_fusion_result": fusion,
            "capture_bundle": bundle,
            "omni_inventory": inventory,
            "qwen_bindings": bindings,
            "qwen_cleanup_receipt": receipt,
            "project_root": str(tmp_path),
            "hybrid_capture_bundle_ref": saved["bundle_ref"],
            "run_id": run_id,
            "workflow_revision": revision,
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
        bbox = request["candidate_bbox_ref"]["xyxy"]
        raw = {
            "status": "PROPOSED", "candidate_id": candidate_id, "capture_id": request["capture_id"],
            "capture_sha256": request["capture_sha256"], "source_revision": request["source_revision"],
            "affine_transform_ref": deepcopy(request["affine_transform_ref"]),
            "point_coordinate_space": "capture_pixel_xyxy",
            "point": [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2],
            "provenance": {"provider": "fake-vista"},
        }
        from app.learn.hybrid.vista_refinement import validate_vista_proposal
        results.append(
            {
                "contract_version": "learn_vista_target_coordinate_validation_v1",
                "status": "needs_review",
                "candidate_id": candidate_id,
                "final_numbering_revision": request["source_revision"],
                "hybrid_vista_request": deepcopy(request),
                "hybrid_vista_proposal": validate_vista_proposal(request=request, raw_result=raw),
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


def test_hybrid_calibration_batch_resume_preserves_exact_request_lineage(tmp_path) -> None:
    submitted_batches: list[list[dict[str, Any]]] = []

    def locate(payload: dict[str, Any]) -> dict[str, Any]:
        requests = deepcopy(payload["metadata"]["learn_hybrid_vista_requests"])
        submitted_batches.append(requests)
        ids = [item["candidate_id"] for item in requests]
        if len(submitted_batches) == 1:
            return _hybrid_locate_response(
                requests,
                completed_ids=ids[:1],
                remaining_count=1,
                resumable=True,
            )
        return _hybrid_locate_response(
            requests,
            completed_ids=ids,
            remaining_count=0,
            resumable=False,
        )

    response = run_learning_calibration_sequence(
        _hybrid_sequence_payload(tmp_path),
        locate_runner=locate,
        profile_loader=lambda _stage, _profile_id: {"profile_id": "vista-test"},
        resource_preflight_builder=_normal_preflight,
    )

    assert response["success"] is True
    first_by_id = {item["candidate_id"]: item for item in submitted_batches[0]}
    second_by_id = {item["candidate_id"]: item for item in submitted_batches[1]}
    candidate_id = next(iter(first_by_id))
    for field in ("candidate_bbox_ref", "roi_ref", "affine_transform_ref", "source_revision", "capture_sha256"):
        assert second_by_id[candidate_id][field] == first_by_id[candidate_id][field]
    resume = submitted_batches and response["data"]["result"]["calibration_sequence"]
    assert resume["hybrid_vista_results"][0]["hybrid_vista_request"] == first_by_id[candidate_id]


def test_hybrid_calibration_cancellation_stops_before_vista_acquisition(tmp_path) -> None:
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
        _hybrid_sequence_payload(tmp_path),
        locate_runner=locate,
        profile_loader=lambda _stage, _profile_id: {"profile_id": "vista-test"},
        resource_preflight_builder=_normal_preflight,
        cancellation_event=Cancelled(),
    )

    assert response["success"] is False
    assert response["data"]["failure_category"] == "calibration_cancelled"
    assert response["data"]["remaining_count"] == 2
    assert locate_called is False


def test_hybrid_terminal_batch_rejects_completed_ids_without_exact_results(tmp_path) -> None:
    def locate(payload: dict[str, Any]) -> dict[str, Any]:
        requests = deepcopy(payload["metadata"]["learn_hybrid_vista_requests"])
        response = _hybrid_locate_response(requests, completed_ids=[requests[0]["candidate_id"]],
            remaining_count=0, resumable=False)
        batch = response["data"]["result"]["learn_all_targets"]["vista_coordinate_validation"]["batch"]
        batch["completed_candidate_ids"] = [item["candidate_id"] for item in requests]
        batch["completed_count"] = len(requests)
        return response

    response = run_learning_calibration_sequence(_hybrid_sequence_payload(tmp_path), locate_runner=locate,
        profile_loader=lambda *_: {"profile_id": "vista-test"}, resource_preflight_builder=_normal_preflight)
    assert response["success"] is False
    assert response["data"]["failure_category"] == "calibration_hybrid_batch_coverage_mismatch"
