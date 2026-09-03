from __future__ import annotations

from copy import deepcopy
import math

import pytest


def _refs() -> dict[str, dict[str, str]]:
    return {
        "capture_ref": {"id": "capture/case-001", "sha256": "a" * 64},
        "native_output_ref": {"id": "native-output/case-001/0", "sha256": "b" * 64},
        "omni_snapshot_ref": {"id": "omni-snapshot/case-001", "sha256": "c" * 64},
    }


def _candidates() -> list[dict[str, object]]:
    return [
        {"candidate_id": "candidate/inactive", "bbox_original": [0, 0, 20, 20], "active": False},
        {"candidate_id": "candidate/apply", "bbox_original": [10, 10, 40, 40], "active": True},
        {"candidate_id": "candidate/other", "bbox_original": [60, 10, 90, 40], "active": True},
    ]


def _proposal(**changes: object) -> object:
    from app.learn.hybrid.goal_binding_provider import NativePointProposal

    values: dict[str, object] = {
        "goal_index": 0,
        "point": (0.25, 0.375),
        "coordinate_space": "normalized_0_1",
        "confidence": 0.91,
        "status": "OK",
        "failure_reason": None,
    }
    values.update(changes)
    return NativePointProposal(**values)  # type: ignore[arg-type]


def _map(
    proposal: object,
    candidates: list[dict[str, object]] | None = None,
    image_size: tuple[int, int] = (100, 80),
) -> dict[str, object]:
    from app.learn.hybrid.goal_binding_provider import map_native_point_to_candidate

    return map_native_point_to_candidate(
        proposal=proposal,  # type: ignore[arg-type]
        image_size=image_size,
        candidates=_candidates() if candidates is None else candidates,
        provider_id="ui_venus_1_5_2b_f16",
        **_refs(),
    )


def test_one_strict_active_hit_binds_existing_candidate() -> None:
    result = _map(_proposal())

    assert result == {
        "contract_version": "goal_binding_provider_result_v1",
        "goal_index": 0,
        "candidate_index": 1,
        "candidate_id": "candidate/apply",
        "status": "BOUND",
        "reason": None,
        "binding_basis": "native_point",
        "confidence": 0.91,
        "canonical_capture_pixel_point": [25.0, 30.0],
        "provider_id": "ui_venus_1_5_2b_f16",
        "native_output_ref": _refs()["native_output_ref"],
        "omni_snapshot_ref": _refs()["omni_snapshot_ref"],
        "capture_ref": _refs()["capture_ref"],
        "artifact_is_authorization": False,
    }


def test_zero_hit_and_overlapping_hits_are_unbound() -> None:
    no_hit = _map(_proposal(point=(50, 70), coordinate_space="capture_pixels"))
    overlapping = _map(
        _proposal(point=(25, 30), coordinate_space="capture_pixels"),
        _candidates() + [{"candidate_id": "candidate/overlap", "bbox_original": [20, 20, 50, 50], "active": True}],
    )

    assert no_hit["status"] == overlapping["status"] == "UNBOUND"
    assert no_hit["candidate_index"] is no_hit["candidate_id"] is None
    assert overlapping["candidate_index"] is overlapping["candidate_id"] is None
    assert no_hit["canonical_capture_pixel_point"] == [50.0, 70.0]
    assert no_hit["reason"] == "no_active_candidate_hit"
    assert overlapping["reason"] == "ambiguous_active_candidate_hit"


def test_boundary_and_inactive_hits_are_unbound() -> None:
    inactive = _map(_proposal(point=(5, 5), coordinate_space="capture_pixels"))
    boundary = _map(_proposal(point=(10, 20), coordinate_space="capture_pixels"))

    assert inactive["status"] == boundary["status"] == "UNBOUND"
    assert inactive["candidate_id"] is boundary["candidate_id"] is None


def test_provider_failure_never_carries_candidate_or_point() -> None:
    result = _map(
        _proposal(
            status="PROVIDER_FAILURE",
            point=None,
            confidence=None,
            failure_reason="provider_timeout",
        )
    )

    assert result["status"] == "PROVIDER_FAILURE"
    assert result["candidate_index"] is result["candidate_id"] is None
    assert result["canonical_capture_pixel_point"] is None
    assert result["confidence"] is None
    assert result["reason"] == "provider_timeout"

    malformed_success = _map(_proposal(failure_reason="provider_timeout"))
    assert malformed_success["status"] == "PROVIDER_FAILURE"
    assert malformed_success["reason"] == "malformed_native_output"


@pytest.mark.parametrize(
    "proposal",
    [
        {"point": (math.nan, 0.5)},
        {"point": (math.inf, 0.5)},
        {"point": (1.1, 0.5)},
        {"point": (10 ** 1000, 0.5)},
        {"point": (100, 20), "coordinate_space": "capture_pixels"},
        {"point": (1001, 1), "coordinate_space": "normalized_0_1000"},
    ],
)
def test_mapper_rejects_nan_infinity_bad_space_and_out_of_bounds(proposal: dict[str, object]) -> None:
    result = _map(_proposal(**proposal))
    assert result["status"] == "PROVIDER_FAILURE"
    assert result["canonical_capture_pixel_point"] is None

    with pytest.raises(ValueError, match="coordinate_space"):
        _map(_proposal(coordinate_space="unknown"))
    with pytest.raises(ValueError, match="coordinate_space"):
        _map(_proposal(coordinate_space=[]))
    with pytest.raises(ValueError, match="image_size"):
        _map(_proposal(), image_size=(10 ** 1000, 80))


def test_mapper_never_mutates_or_expands_omni_geometry() -> None:
    candidates = _candidates()
    frozen = deepcopy(candidates)
    _map(_proposal(point=(40, 20), coordinate_space="capture_pixels"), candidates)

    assert candidates == frozen
    assert candidates[1]["bbox_original"] == [10, 10, 40, 40]


def test_canonical_result_is_closed_non_authorizing_and_lineage_bound() -> None:
    from app.learn.hybrid.goal_binding_provider import validate_goal_binding_provider_result

    result = _map(_proposal())
    assert validate_goal_binding_provider_result(result) == result
    assert result["artifact_is_authorization"] is False

    widened = dict(result, action="click")
    with pytest.raises(ValueError, match="closed"):
        validate_goal_binding_provider_result(widened)
    broken_lineage = deepcopy(result)
    broken_lineage["capture_ref"] = {"id": "capture/case-001", "sha256": "not-a-hash"}
    with pytest.raises(ValueError, match="lineage"):
        validate_goal_binding_provider_result(broken_lineage)
    with pytest.raises(ValueError, match="status"):
        validate_goal_binding_provider_result(dict(result, status=[]))
    with pytest.raises(ValueError, match="binding_basis"):
        validate_goal_binding_provider_result(dict(result, binding_basis=[]))
    unbound = _map(_proposal(point=(50, 70), coordinate_space="capture_pixels"))
    with pytest.raises(ValueError, match="reason"):
        validate_goal_binding_provider_result(dict(unbound, reason="provider_timeout"))


def test_missing_provider_confidence_remains_null_not_fabricated() -> None:
    result = _map(_proposal(confidence=None))

    assert result["status"] == "BOUND"
    assert result["confidence"] is None


def test_incumbent_direct_index_basis_is_closed_and_has_no_invented_point() -> None:
    from app.learn.hybrid.goal_binding_provider import validate_goal_binding_provider_result

    result = _map(_proposal())
    control = dict(
        result,
        binding_basis="direct_candidate_index",
        canonical_capture_pixel_point=None,
        provider_id="qwen3_vl_8b_q4_k_m",
    )
    assert validate_goal_binding_provider_result(control) == control

    with pytest.raises(ValueError, match="direct_candidate_index"):
        validate_goal_binding_provider_result(dict(control, canonical_capture_pixel_point=[25.0, 30.0]))
    with pytest.raises(ValueError, match="direct_candidate_index"):
        validate_goal_binding_provider_result(
            dict(control, provider_id="ui_venus_1_5_2b_f16")
        )
