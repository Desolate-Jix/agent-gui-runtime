from __future__ import annotations

from dataclasses import fields

import pytest


def _profile(
    provider_id: str,
    native_shape: str,
    coordinate_space: str = "normalized_0_1000",
    **extra: object,
) -> dict[str, object]:
    profile = {
        "contract_version": "goal_binding_native_profile_v1",
        "provider_id": provider_id,
        "native_shape": native_shape,
        "coordinate_space": coordinate_space,
        **extra,
    }
    if coordinate_space == "capture_pixels":
        profile["image_size"] = [100, 80]
    return profile


def test_ui_venus_parses_one_official_point_and_rejects_extra_points() -> None:
    from app.learn.hybrid.goal_binding_native_adapters import parse_ui_venus_point

    profile = _profile("ui_venus_1_5_2b_f16", "ui_venus_point_v1")
    proposal = parse_ui_venus_point({"point": [250, 375]}, goal_index=0, profile=profile)

    assert proposal.point == (250.0, 375.0)
    assert proposal.coordinate_space == "normalized_0_1000"
    assert proposal.confidence is None
    assert proposal.status == "OK"
    assert parse_ui_venus_point(
        {"point": [250, 375], "points": [[1, 2]]}, goal_index=0, profile=profile
    ).status == "PROVIDER_FAILURE"


def test_gui_actor_uses_topk_points_zero_only() -> None:
    from app.learn.hybrid.goal_binding_native_adapters import parse_gui_actor_top1

    profile = _profile("gui_actor_3b_bf16", "gui_actor_topk_points_v1", "normalized_0_1")
    proposal = parse_gui_actor_top1(
        {"topk_points": [[0.25, 0.375], ["not", "a point"]]}, goal_index=2, profile=profile
    )

    assert proposal.goal_index == 2
    assert proposal.point == (0.25, 0.375)
    assert proposal.coordinate_space == "normalized_0_1"
    assert proposal.status == "OK"


def test_gui_actor_does_not_fallback_when_top1_is_invalid() -> None:
    from app.learn.hybrid.goal_binding_native_adapters import parse_gui_actor_top1

    proposal = parse_gui_actor_top1(
        {"topk_points": [[float("nan"), 0.1], [0.25, 0.375]]},
        goal_index=0,
        profile=_profile("gui_actor_3b_bf16", "gui_actor_topk_points_v1", "normalized_0_1"),
    )

    assert proposal.status == "PROVIDER_FAILURE"
    assert proposal.point is None


def test_phi_point_and_bbox_normalize_by_sealed_profile_mode() -> None:
    from app.learn.hybrid.goal_binding_native_adapters import parse_phi_ground_any

    point = parse_phi_ground_any(
        {"point": [250, 375]},
        goal_index=1,
        profile=_profile(
            "phi_ground_any_bf16", "phi_ground_any_v1", "normalized_0_1000", output_mode="point"
        ),
    )
    bbox = parse_phi_ground_any(
        {"bbox": [100, 200, 400, 600]},
        goal_index=1,
        profile=_profile(
            "phi_ground_any_bf16", "phi_ground_any_v1", "normalized_0_1000", output_mode="bbox"
        ),
    )

    assert point.point == (250.0, 375.0)
    assert bbox.point == (250.0, 400.0)
    assert parse_phi_ground_any(
        {"bbox": [100, 200, 400, 600]},
        goal_index=1,
        profile=_profile(
            "phi_ground_any_bf16", "phi_ground_any_v1", "normalized_0_1000", output_mode="point"
        ),
    ).status == "PROVIDER_FAILURE"


def test_phi_bbox_center_rejects_degenerate_or_out_of_range_box() -> None:
    from app.learn.hybrid.goal_binding_native_adapters import parse_phi_ground_any

    profile = _profile(
        "phi_ground_any_bf16", "phi_ground_any_v1", "normalized_0_1", output_mode="bbox"
    )
    for bbox in ([0.1, 0.2, 0.1, 0.4], [-0.1, 0.2, 0.4, 0.6], [0.1, 0.2, 1.1, 0.6]):
        proposal = parse_phi_ground_any({"bbox": bbox}, goal_index=0, profile=profile)
        assert proposal.status == "PROVIDER_FAILURE"
        assert proposal.point is None


def test_gguf_parser_accepts_only_the_profile_native_short_form() -> None:
    from app.learn.hybrid.goal_binding_native_adapters import parse_gguf_grounding

    profile = _profile("ui_venus_2_9b_q6_k", "gguf_bare_point_pair_v1", "capture_pixels")
    proposal = parse_gguf_grounding(" [25, 30]\n", goal_index=0, profile=profile)

    assert proposal.point == (25.0, 30.0)
    for raw in ({"point": [25, 30]}, "[25, 30] trailing prose", "[25, 30, 40]"):
        assert parse_gguf_grounding(raw, goal_index=0, profile=profile).status == "PROVIDER_FAILURE"


def test_capture_pixel_profile_rejects_point_outside_sealed_size() -> None:
    from app.learn.hybrid.goal_binding_native_adapters import parse_ui_venus_point

    proposal = parse_ui_venus_point(
        {"point": [100, 40]},
        goal_index=0,
        profile=_profile("ui", "ui_venus_point_v1", "capture_pixels"),
    )

    assert proposal.status == "PROVIDER_FAILURE"
    assert proposal.point is None


def test_all_native_parsers_preserve_raw_utf8_without_reasoning_fields() -> None:
    from app.learn.hybrid.goal_binding_native_adapters import (
        parse_gguf_grounding,
        parse_gui_actor_top1,
        parse_phi_ground_any,
        parse_ui_venus_point,
    )

    cases = (
        (parse_ui_venus_point, '{"point":[250,375]}', _profile("ui", "ui_venus_point_v1")),
        (parse_gui_actor_top1, '{"topk_points":[[0.25,0.375],"后续原始项"]}', _profile("gui", "gui_actor_topk_points_v1", "normalized_0_1")),
        (parse_phi_ground_any, '{"point":[250,375]}', _profile("phi", "phi_ground_any_v1", output_mode="point")),
        (parse_gguf_grounding, "[250,375]", _profile("gguf", "gguf_bare_point_pair_v1")),
    )
    for parser, raw, profile in cases:
        proposal = parser(raw, goal_index=0, profile=profile)
        assert proposal.status == "OK"
        assert proposal.confidence is None
        assert not hasattr(proposal, "raw_output")
        assert not hasattr(proposal, "reasoning")
    assert parse_ui_venus_point(
        '{"point":[250,375],"reasoning":"\u4e0d\u4fdd\u7559"}',
        goal_index=0,
        profile=_profile("ui", "ui_venus_point_v1"),
    ).status == "PROVIDER_FAILURE"


def test_native_parsers_cannot_emit_candidate_id_action_or_authority() -> None:
    from app.learn.hybrid.goal_binding_native_adapters import parse_ui_venus_point

    proposal = parse_ui_venus_point(
        {"point": [250, 375], "candidate_id": "candidate/forged"},
        goal_index=0,
        profile=_profile("ui", "ui_venus_point_v1"),
    )

    assert proposal.status == "PROVIDER_FAILURE"
    assert {field.name for field in fields(type(proposal))} == {
        "goal_index", "point", "coordinate_space", "confidence", "status", "failure_reason"
    }


@pytest.mark.parametrize("bad_profile", [
    {"coordinate_space": "normalized_0_1000"},
    _profile("ui", "ui_venus_point_v1", "unknown"),
    _profile("ui", "wrong_shape"),
])
def test_profile_seals_ui_venus_shape_and_coordinate_space(bad_profile: dict[str, object]) -> None:
    from app.learn.hybrid.goal_binding_native_adapters import parse_ui_venus_point

    with pytest.raises(ValueError):
        parse_ui_venus_point({"point": [1, 2]}, goal_index=0, profile=bad_profile)
