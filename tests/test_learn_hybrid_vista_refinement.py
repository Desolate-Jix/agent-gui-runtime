from __future__ import annotations

from copy import deepcopy

import pytest

from app.learn.hybrid.vista_refinement import (
    build_vista_requests,
    validate_vista_proposal,
)
from app.learn.recognition.uei.canonical import seal_immutable


def _capture_identity() -> dict:
    return {
        "capture_id": "capture/test-7",
        "screenshot_sha256": "a" * 64,
        "artifact_sha256": "a" * 64,
        "workflow_revision": "7",
        "image_size": {"width": 300, "height": 220},
        "capture_lineage_ref": {
            "id": "capture-lineage/test-7",
            "content_sha256": "b" * 64,
        },
    }


def _capture_bundle() -> dict:
    return seal_immutable(
        {
            "contract_version": "hybrid_capture_bundle_v1",
            "capture_identity": _capture_identity(),
            "workflow_revision": 7,
        }
    )


def _fusion_result() -> dict:
    return seal_immutable(
        {
            "contract_version": "hybrid_fusion_result_v1",
            "capture_identity": _capture_identity(),
            "config_sha256": "c" * 64,
            "candidates": [
                {
                    "candidate_id": "candidate/bound",
                    "bbox_original": [100, 100, 140, 130],
                    "coordinate_space": "capture_pixel_xyxy",
                    "state": "BOUND",
                    "vista_eligible": True,
                },
                {
                    "candidate_id": "candidate/ambiguous",
                    "bbox_original": [10, 10, 40, 40],
                    "coordinate_space": "capture_pixel_xyxy",
                    "state": "AMBIGUOUS",
                    "vista_eligible": False,
                },
            ],
        }
    )


def _request() -> dict:
    return build_vista_requests(_fusion_result(), _capture_bundle())[0]


def _raw_result(request: dict, **overrides) -> dict:
    value = {
        "status": "PROPOSED",
        "candidate_id": request["candidate_id"],
        "capture_id": request["capture_id"],
        "capture_sha256": request["capture_sha256"],
        "source_revision": request["source_revision"],
        "affine_transform_ref": deepcopy(request["affine_transform_ref"]),
        "point_coordinate_space": "capture_pixel_xyxy",
        "point": [120, 112],
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
    requests = build_vista_requests(_fusion_result(), _capture_bundle())

    assert len(requests) == 1
    request = requests[0]
    assert request["candidate_id"] == "candidate/bound"
    assert request["submission_status"] == "SUBMITTED"
    assert request["candidate_bbox_ref"]["xyxy"] == [100, 100, 140, 130]
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
    assert request["source_revision"] == "c" * 64
    assert request["capture_sha256"] == "a" * 64
    assert request["qwen_release_prerequisite"] == {
        "provider": "qwen",
        "required_status": "cleanup_verified",
        "purpose": "before_vista_acquisition",
    }


def test_build_vista_requests_rejects_unsealed_or_cross_capture_input() -> None:
    fusion = _fusion_result()
    fusion.pop("content_sha256")
    with pytest.raises(ValueError, match="sealed"):
        build_vista_requests(fusion, _capture_bundle())

    fusion = _fusion_result()
    bundle = _capture_bundle()
    bundle["capture_identity"]["capture_id"] = "capture/stale"
    bundle.pop("content_sha256")
    bundle = seal_immutable(bundle)
    with pytest.raises(ValueError, match="capture lineage"):
        build_vista_requests(fusion, bundle)


def test_validate_vista_proposal_preserves_exact_lineage_and_raw_provenance() -> None:
    request = _request()
    raw_result = _raw_result(request)

    result = validate_vista_proposal(request=request, raw_result=raw_result)

    assert result["status"] == "PROPOSED"
    assert result["review_status"] == "REVIEW_REQUIRED"
    assert result["automatic_acceptance"] is False
    assert result["canonical_point"] == {
        "coordinate_space": "capture_pixel_xyxy",
        "xy": [120, 112],
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
    request = _request()
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


def test_vision_bridge_uses_exact_request_roi_and_preserves_fake_provider_result(
    tmp_path,
    monkeypatch,
) -> None:
    from PIL import Image

    from app.api import vision

    request = _request()
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
    }

    result = vision._run_hybrid_vista_validation(
        target,
        image_path=str(image_path),
        image_size={"width": 300, "height": 220},
        local_config={"profile_id": "fake-vista"},
        timeout_seconds=5.0,
    )

    assert len(calls) == 1
    assert calls[0]["image_preprocess"]["source_bbox"] == {
        "x": request["roi_ref"]["xyxy"][0],
        "y": request["roi_ref"]["xyxy"][1],
        "w": request["roi_ref"]["xyxy"][2] - request["roi_ref"]["xyxy"][0],
        "h": request["roi_ref"]["xyxy"][3] - request["roi_ref"]["xyxy"][1],
    }
    proposal = result["hybrid_vista_proposal"]
    assert proposal["status"] == "PROPOSED"
    assert proposal["candidate_bbox_ref"] == request["candidate_bbox_ref"]
    assert proposal["roi_ref"] == request["roi_ref"]
    assert proposal["affine_transform_ref"] == request["affine_transform_ref"]
    assert proposal["raw_provider_result"]["provider_payload"]["raw_output"] == "[120,112]"
