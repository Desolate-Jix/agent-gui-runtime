from __future__ import annotations

from copy import deepcopy

import pytest

from app.learn.hybrid.vista_refinement import (
    build_vista_requests,
    validate_vista_proposal,
)
from app.core.model_server import build_qwen_cleanup_receipt
from app.learn.hybrid.fusion import fuse_hybrid_candidates
from app.learn.recognition.uei.canonical import seal_immutable
from tests.test_learn_hybrid_fusion import _inputs


def _lease() -> dict:
    process = {"pid": 4123, "create_time": 100.5, "executable": "qwen-server.exe"}
    return {
        "contract_version": "qwen_model_server_lease_v1", "lease_id": "lease-vista",
        "owner_request_id": "request-vista", "profile_id": "qwen", "incarnation_id": "inc-vista",
        "server_base_url": "http://127.0.0.1:12345", "server_model_id": "qwen",
        "profile_sha256": "1" * 64, "server_process_identity": process,
    }


def _cleanup_receipt() -> dict:
    lease = _lease()
    return build_qwen_cleanup_receipt(
        model_lease=lease,
        release_result={"status": "released", "lease": lease, "shared_server_retained": False,
            "server_termination": "verified_exact_process_exited",
            "release": {"status": "proven_absent", "identity": lease["server_process_identity"]},
            "process_identity": lease["server_process_identity"]},
    )


def _authoritative_inputs() -> tuple[dict, dict, dict, dict, dict]:
    config, bundle, inventory, bindings = _inputs(candidate_count=1)
    sealed_inventory = seal_immutable(inventory)
    sealed_bindings = seal_immutable(bindings)
    fusion = seal_immutable(fuse_hybrid_candidates(config=config, capture_bundle=bundle,
        omni_inventory=sealed_inventory, qwen_bindings=sealed_bindings))
    return fusion, bundle, sealed_inventory, sealed_bindings, _cleanup_receipt()


def _stored_authoritative_inputs(tmp_path):
    from tests.test_learning_calibration_sequence import _hybrid_sequence_payload
    payload = _hybrid_sequence_payload(tmp_path)
    values = (payload["hybrid_fusion_result"], payload["capture_bundle"], payload["omni_inventory"],
        payload["qwen_bindings"], payload["qwen_cleanup_receipt"])
    context = {"fusion_result":values[0], "capture_bundle":values[1], "omni_inventory":values[2],
        "qwen_bindings":values[3], "qwen_cleanup_receipt":values[4],
        "workflow_revision":payload["workflow_revision"], "project_root":payload["project_root"],
        "hybrid_capture_bundle_ref":payload["hybrid_capture_bundle_ref"], "run_id":payload["run_id"]}
    return (*values, context)


def _request() -> dict:
    fusion, bundle, inventory, bindings, receipt = _authoritative_inputs()
    return build_vista_requests(fusion, bundle, omni_inventory=inventory,
        qwen_bindings=bindings, qwen_cleanup_receipt=receipt,
        expected_workflow_revision=bundle["workflow_revision"])[0]


def _raw_result(request: dict, **overrides) -> dict:
    value = {
        "status": "PROPOSED",
        "candidate_id": request["candidate_id"],
        "capture_id": request["capture_id"],
        "capture_sha256": request["capture_sha256"],
        "source_revision": request["source_revision"],
        "affine_transform_ref": deepcopy(request["affine_transform_ref"]),
        "point_coordinate_space": "capture_pixel_xyxy",
        "point": [
            sum(request["candidate_bbox_ref"]["xyxy"][::2]) / 2,
            sum(request["candidate_bbox_ref"]["xyxy"][1::2]) / 2,
        ],
        "provenance": {"provider": "fake-vista", "request_id": "fake-1"},
    }
    value.update(overrides)
    return value


def _request_with_geometry(*, candidate_bbox: list[int], roi: list[int]) -> dict:
    request = deepcopy(_request())
    request["candidate_bbox_ref"] = seal_immutable(
        {
            "contract_version": "hybrid_candidate_bbox_ref_v1",
            "candidate_id": request["candidate_id"],
            "source_revision": request["source_revision"],
            "capture_sha256": request["capture_sha256"],
            "coordinate_space": "capture_pixel_xyxy",
            "xyxy": candidate_bbox,
        }
    )
    request["roi_ref"] = seal_immutable(
        {
            "contract_version": "hybrid_permitted_roi_v1",
            "roi_id": f"roi/{request['candidate_id']}",
            "candidate_id": request["candidate_id"],
            "source_revision": request["source_revision"],
            "capture_sha256": request["capture_sha256"],
            "capture_lineage_ref": deepcopy(request["capture_lineage_ref"]),
            "coordinate_space": "capture_pixel_xyxy",
            "xyxy": roi,
            "permitted_for_refinement": True,
        }
    )
    request["affine_transform_ref"] = seal_immutable(
        {
            "contract_version": "hybrid_roi_affine_transform_v1",
            "candidate_id": request["candidate_id"],
            "source_revision": request["source_revision"],
            "capture_sha256": request["capture_sha256"],
            "roi_ref": {
                "id": request["roi_ref"]["roi_id"],
                "content_sha256": request["roi_ref"]["content_sha256"],
            },
            "source_space": "roi_pixel_xy",
            "target_space": "capture_pixel_xyxy",
            "matrix": [1.0, 0.0, float(roi[0]), 0.0, 1.0, float(roi[1])],
        }
    )
    request.pop("content_sha256", None)
    return seal_immutable(request)


def test_build_vista_requests_submits_only_exact_bound_candidate_lineage() -> None:
    fusion, bundle, inventory, bindings, receipt = _authoritative_inputs()
    requests = build_vista_requests(fusion, bundle, omni_inventory=inventory,
        qwen_bindings=bindings, qwen_cleanup_receipt=receipt,
        expected_workflow_revision=bundle["workflow_revision"])

    assert len(requests) == 1
    request = requests[0]
    assert request["candidate_id"] == fusion["candidates"][0]["candidate_id"]
    assert request["submission_status"] == "SUBMITTED"
    assert request["candidate_bbox_ref"]["xyxy"] == fusion["candidates"][0]["bbox_original"]
    assert request["roi_ref"]["candidate_id"] == request["candidate_id"]
    assert request["affine_transform_ref"]["roi_ref"]["content_sha256"] == request["roi_ref"]["content_sha256"]
    assert request["affine_transform_ref"]["matrix"] == [
        1.0,
        0.0,
        float(request["roi_ref"]["xyxy"][0]),
        0.0,
        1.0,
        float(request["roi_ref"]["xyxy"][1]),
    ]
    assert request["source_revision"] == fusion["config_sha256"]
    assert request["capture_sha256"] == bundle["capture_identity"]["screenshot_sha256"]
    assert request["qwen_cleanup_receipt"] == receipt


def test_build_vista_requests_rejects_unsealed_or_cross_capture_input() -> None:
    fusion, bundle, inventory, bindings, receipt = _authoritative_inputs()
    fusion.pop("content_sha256")
    with pytest.raises(ValueError, match="sealed"):
        build_vista_requests(fusion, bundle, omni_inventory=inventory, qwen_bindings=bindings,
            qwen_cleanup_receipt=receipt, expected_workflow_revision=bundle["workflow_revision"])

    fusion, bundle, inventory, bindings, receipt = _authoritative_inputs()
    fusion["candidates"][0]["candidate_id"] = "candidate/fabricated"
    fusion.pop("content_sha256")
    fusion = seal_immutable(fusion)
    with pytest.raises(ValueError, match="candidate|coverage|identity"):
        build_vista_requests(fusion, bundle, omni_inventory=inventory, qwen_bindings=bindings,
            qwen_cleanup_receipt=receipt, expected_workflow_revision=bundle["workflow_revision"])


def test_validate_vista_proposal_preserves_exact_lineage_and_raw_provenance() -> None:
    fusion, bundle, inventory, bindings, receipt = _authoritative_inputs()
    request = build_vista_requests(fusion, bundle, omni_inventory=inventory,
        qwen_bindings=bindings, qwen_cleanup_receipt=receipt,
        expected_workflow_revision=bundle["workflow_revision"])[0]
    raw_result = _raw_result(request)

    result = validate_vista_proposal(request=request, raw_result=raw_result)

    assert result["status"] == "PROPOSED"
    assert result["review_status"] == "REVIEW_REQUIRED"
    assert result["automatic_acceptance"] is False
    assert result["canonical_point"] == {
        "coordinate_space": "capture_pixel_xyxy",
        "xy": _raw_result(request)["point"],
    }
    for field in ("candidate_id", "candidate_bbox_ref", "roi_ref", "affine_transform_ref", "source_revision", "capture_sha256"):
        assert result[field] == request[field]
    assert result["raw_provider_result"] == raw_result
    assert result["provider_provenance"] == raw_result["provenance"]


def test_vista_point_inside_roi_but_outside_candidate_is_rejected() -> None:
    request = _request_with_geometry(
        candidate_bbox=[100, 100, 140, 130],
        roi=[80, 80, 180, 160],
    )
    result = validate_vista_proposal(
        request=request,
        raw_result=_raw_result(request, point=[90, 90]),
    )

    assert result["status"] == "VISTA_OUT_OF_BOUNDS"
    assert result["review_status"] == "REVIEW_REQUIRED"
    assert result.get("canonical_point") is None


def test_vista_point_inside_candidate_but_outside_exact_roi_is_rejected() -> None:
    request = _request_with_geometry(
        candidate_bbox=[100, 100, 180, 160],
        roi=[120, 110, 170, 150],
    )
    result = validate_vista_proposal(
        request=request,
        raw_result=_raw_result(request, point=[110, 105]),
    )

    assert result["status"] == "VISTA_OUT_OF_BOUNDS"
    assert result.get("canonical_point") is None


@pytest.mark.parametrize("point", [[100, 115], [140, 115], [120, 100], [120, 130], [100, 100], [140, 130]])
def test_vista_rejects_every_candidate_boundary(point: list[int]) -> None:
    request = _request_with_geometry(candidate_bbox=[100, 100, 140, 130], roi=[80, 80, 180, 160])
    result = validate_vista_proposal(request=request, raw_result=_raw_result(request, point=point))
    assert result["status"] == "VISTA_OUT_OF_BOUNDS"
    assert result.get("canonical_point") is None


@pytest.mark.parametrize("point", [[0, 20], [100, 20], [20, 0], [20, 80]])
def test_vista_rejects_affine_roi_endpoints(point: list[int]) -> None:
    request = _request_with_geometry(candidate_bbox=[1, 1, 99, 79], roi=[0, 0, 100, 80])
    result = validate_vista_proposal(
        request=request,
        raw_result=_raw_result(request, point=point, point_coordinate_space="roi_pixel_xy"),
    )
    assert result["status"] == "VISTA_OUT_OF_BOUNDS"
    assert result.get("canonical_point") is None


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("candidate_id", "candidate/wrong"),
        ("capture_id", "capture/stale"),
        ("capture_sha256", "d" * 64),
        ("source_revision", "stale-revision"),
    ],
)
def test_vista_wrong_or_stale_lineage_is_review_required(
    field: str,
    wrong_value: str,
) -> None:
    fusion, bundle, inventory, bindings, receipt = _authoritative_inputs()
    request = build_vista_requests(fusion, bundle, omni_inventory=inventory,
        qwen_bindings=bindings, qwen_cleanup_receipt=receipt,
        expected_workflow_revision=bundle["workflow_revision"])[0]
    result = validate_vista_proposal(
        request=request,
        raw_result=_raw_result(request, **{field: wrong_value}),
    )

    assert result["status"] == "TRANSFORM_INVALID"
    assert result["review_status"] == "REVIEW_REQUIRED"
    assert result.get("canonical_point") is None


def test_vista_transform_mismatch_and_unsubmitted_status_are_rejected() -> None:
    request = _request()
    mismatched_transform = deepcopy(request["affine_transform_ref"])
    mismatched_transform["matrix"][2] += 1.0
    mismatched_transform.pop("content_sha256")
    mismatched_transform = seal_immutable(mismatched_transform)

    transform_result = validate_vista_proposal(
        request=request,
        raw_result=_raw_result(request, affine_transform_ref=mismatched_transform),
    )
    unsubmitted = deepcopy(request)
    unsubmitted["submission_status"] = "NOT_SUBMITTED"
    unsubmitted.pop("content_sha256")
    unsubmitted_result = validate_vista_proposal(
        request=seal_immutable(unsubmitted),
        raw_result=_raw_result(request),
    )

    assert transform_result["status"] == "TRANSFORM_INVALID"
    assert transform_result.get("canonical_point") is None
    assert unsubmitted_result["status"] == "TRANSFORM_INVALID"
    assert unsubmitted_result.get("canonical_point") is None


def test_vista_never_clips_or_uses_a_nearest_point_correction() -> None:
    request = _request_with_geometry(
        candidate_bbox=[100, 100, 140, 130],
        roi=[80, 80, 180, 160],
    )
    result = validate_vista_proposal(
        request=request,
        raw_result=_raw_result(
            request,
            point=[99, 99],
            clipped_point=[100, 100],
            correction="nearest_inside_point",
        ),
    )

    assert result["status"] == "VISTA_OUT_OF_BOUNDS"
    assert result.get("canonical_point") is None
    assert result["raw_provider_result"]["clipped_point"] == [100, 100]


def test_vista_failure_never_preserves_automatic_acceptance() -> None:
    request = _request()
    result = validate_vista_proposal(
        request=request,
        raw_result=_raw_result(request, status="VISTA_FAILED", error="fake failure"),
    )

    assert result["status"] == "VISTA_FAILED"
    assert result["review_status"] == "REVIEW_REQUIRED"
    assert result["automatic_acceptance"] is False
    assert result.get("canonical_point") is None


def test_vision_bridge_rejects_wrong_actual_capture_before_provider_call(
    tmp_path,
    monkeypatch,
) -> None:
    from PIL import Image

    from app.api import vision

    fusion, bundle, inventory, bindings, receipt, context = _stored_authoritative_inputs(tmp_path)
    request = build_vista_requests(fusion, bundle, omni_inventory=inventory,
        qwen_bindings=bindings, qwen_cleanup_receipt=receipt,
        expected_workflow_revision=bundle["workflow_revision"])[0]
    image_path = tmp_path / "capture.png"
    Image.new("RGB", (300, 220), "white").save(image_path)
    calls: list[dict] = []

    def fake_vista_call(**kwargs):
        calls.append(kwargs)
        return {
            "point": {"x": 120, "y": 112},
            "provider": "fake-vista",
            "raw_output": "[120,112]",
            "request_id": "fake-request-1",
        }

    monkeypatch.setattr(vision, "_call_vista_point_prompt", fake_vista_call)
    monkeypatch.setattr(vision, "VISTA_DIRECT_IMAGES_DIR", tmp_path / "vista-direct")
    target = {
        "candidate_id": request["candidate_id"],
        "label": request["candidate_id"],
        "role": "control",
        "bbox": {"x": 100, "y": 100, "w": 40, "h": 30},
        "hybrid_vista_request": request,
        "hybrid_vista_authoritative_context": context,
    }

    result = vision._run_hybrid_vista_validation(
        target,
        image_path=str(image_path),
        image_size={"width": 300, "height": 220},
        local_config={"profile_id": "fake-vista"},
        timeout_seconds=5.0,
    )

    assert len(calls) == 0
    proposal = result["hybrid_vista_proposal"]
    assert proposal["status"] == "VISTA_FAILED"
    assert proposal["candidate_bbox_ref"] == request["candidate_bbox_ref"]
    assert proposal["roi_ref"] == request["roi_ref"]
    assert proposal["affine_transform_ref"] == request["affine_transform_ref"]
    assert "actual capture SHA mismatch" in proposal["raw_provider_result"]["error"]


def test_review_projection_rejects_missing_cross_attached_or_forged_failed_point() -> None:
    from app.learn.workflow_tasks.hybrid_review import run_hybrid_review_projection_task
    fusion, bundle, inventory, bindings, receipt = _authoritative_inputs()
    request = build_vista_requests(fusion, bundle, omni_inventory=inventory,
        qwen_bindings=bindings, qwen_cleanup_receipt=receipt,
        expected_workflow_revision=bundle["workflow_revision"])[0]
    raw = _raw_result(request, status="VISTA_FAILED", success=False)
    proposal = validate_vista_proposal(request=request, raw_result=raw)
    forged = deepcopy(proposal)
    forged["canonical_point"] = {"coordinate_space": "capture_pixel_xyxy", "xy": [1, 1]}
    payload = {"hybrid_vista_requests":[request], "hybrid_vista_results":[{
        "candidate_id":request["candidate_id"], "hybrid_vista_request":request,
        "hybrid_vista_proposal":forged}], "qwen_cleanup_receipt":receipt}
    with pytest.raises(ValueError, match="raw provider evidence"):
        run_hybrid_review_projection_task(payload)
    payload["hybrid_vista_results"] = []
    with pytest.raises(ValueError, match="requires VISTA results"):
        run_hybrid_review_projection_task(payload)


@pytest.mark.parametrize("mutation", ["unsealed", "not_submitted", "stale", "wrong_candidate", "missing_cleanup"])
def test_vision_pre_acquisition_invalid_lineage_has_zero_provider_calls(tmp_path, monkeypatch, mutation: str) -> None:
    from PIL import Image
    from app.api import vision
    fusion, bundle, inventory, bindings, receipt, context = _stored_authoritative_inputs(tmp_path)
    request = build_vista_requests(fusion, bundle, omni_inventory=inventory,
        qwen_bindings=bindings, qwen_cleanup_receipt=receipt,
        expected_workflow_revision=bundle["workflow_revision"])[0]
    mutated = deepcopy(request)
    mutated.pop("content_sha256")
    if mutation == "unsealed":
        pass
    elif mutation == "not_submitted":
        mutated["submission_status"] = "NOT_SUBMITTED"; mutated = seal_immutable(mutated)
    elif mutation == "stale":
        mutated["source_revision"] = "f" * 64; mutated = seal_immutable(mutated)
    elif mutation == "missing_cleanup":
        mutated.pop("qwen_cleanup_receipt"); mutated = seal_immutable(mutated)
    else:
        mutated["candidate_id"] = "candidate/" + "f" * 64; mutated = seal_immutable(mutated)
    image_path = tmp_path / "capture.png"; Image.new("RGB", (1280, 720), "white").save(image_path)
    calls = []
    monkeypatch.setattr(vision, "_call_vista_point_prompt", lambda **kwargs: calls.append(kwargs))
    target = {"candidate_id":request["candidate_id"], "label":"target", "hybrid_vista_request":mutated,
        "hybrid_vista_authoritative_context":context}
    vision._run_hybrid_vista_validation(target, image_path=str(image_path), image_size={"width":1280,"height":720},
        local_config={"profile_id":"fake"}, timeout_seconds=1)
    assert calls == []
