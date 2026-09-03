from __future__ import annotations

from copy import deepcopy

import pytest


def _runtime_request() -> dict[str, object]:
    return {
        "contract_version": "hybrid_qwen_binding_request_v1",
        "screenshot": {"image_size": {"width": 1280, "height": 720}},
        "candidates": [
            {"candidate_id": "candidate/one", "bbox_original": [1, 2, 30, 40], "active": True},
            {"candidate_id": "candidate/two", "bbox_original": [50, 60, 80, 90], "active": False},
        ],
        "capture_identity": {"capture_id": "capture/test"},
        "context_ref": {"id": "ctx/test", "content_sha256": "1" * 64},
    }


def test_omni_native_contract_accepts_only_official_minimal_fields() -> None:
    from app.learn.hybrid.simple_native_contracts import parse_omni_native_output

    parsed = parse_omni_native_output({"items": [{"bbox": [0.1, 0.2, 0.3, 0.4], "type": "text", "content": "搜索", "interactivity": True}]})
    assert parsed[0].content == "搜索"
    assert parsed[0].bbox == (0.1, 0.2, 0.3, 0.4)


def test_omni_native_contract_rejects_invalid_normalized_boxes_and_extra_fields() -> None:
    from app.learn.hybrid.simple_native_contracts import parse_omni_native_output

    with pytest.raises(ValueError, match="bbox"):
        parse_omni_native_output({"items": [{"bbox": [0, 0, 1.1, 1], "type": "text", "content": "x", "interactivity": False}]})
    with pytest.raises(ValueError, match="closed"):
        parse_omni_native_output({"items": [{"bbox": [0, 0, 1, 1], "type": "text", "content": "x", "interactivity": False, "source_item_id": "bad"}]})


def test_qwen_projection_keeps_full_runtime_request_unchanged() -> None:
    from app.learn.hybrid.simple_native_contracts import build_qwen_model_projection

    request = _runtime_request(); before = deepcopy(request)
    projection = build_qwen_model_projection(request)
    assert request == before
    assert projection is not request


def test_qwen_projection_uses_short_ordinals_and_exact_geometry() -> None:
    from app.learn.hybrid.simple_native_contracts import build_qwen_model_projection

    assert build_qwen_model_projection(_runtime_request()) == {"image_size": [1280, 720], "candidates": [{"i": 0, "box": [1, 2, 30, 40], "active": True}, {"i": 1, "box": [50, 60, 80, 90], "active": False}]}


def test_qwen_expansion_restores_stable_ids_and_existing_contract() -> None:
    from app.learn.hybrid.simple_native_contracts import build_qwen_model_projection, expand_qwen_model_response

    request = _runtime_request(); projection = build_qwen_model_projection(request)
    result = expand_qwen_model_response({"bindings": [{"i": 0, "role": "button", "label": "新建", "status": "BOUND", "confidence": .9}, {"i": 1, "role": "button", "label": "取消", "status": "UNBOUND", "confidence": .1}]}, projection=projection, runtime_request=request)
    assert [item["candidate_id"] for item in result["bindings"]] == ["candidate/one", "candidate/two"]


def test_qwen_expansion_rejects_missing_duplicate_unknown_and_reordered_ordinals() -> None:
    from app.learn.hybrid.simple_native_contracts import build_qwen_model_projection, expand_qwen_model_response

    request = _runtime_request(); projection = build_qwen_model_projection(request)
    base = [{"i": 0, "role": "button", "label": "a", "status": "BOUND", "confidence": .9}, {"i": 1, "role": "button", "label": "b", "status": "BOUND", "confidence": .9}]
    for bindings in (base[:1], [base[0], base[0]], [{**base[0], "i": 3}, base[1]], list(reversed(base))):
        with pytest.raises(ValueError, match="ordinal"):
            expand_qwen_model_response({"bindings": bindings}, projection=projection, runtime_request=request)


def test_vista_contract_accepts_only_bare_normalized_pair() -> None:
    from app.learn.hybrid.simple_native_contracts import parse_vista_normalized_point

    assert parse_vista_normalized_point("[437, 612]\n") == (437.0, 612.0)
    for raw in ('{"x": 1}', '[1,2,3]', '[NaN, 2]', '[1, 2] prose'):
        with pytest.raises(ValueError):
            parse_vista_normalized_point(raw)


def test_vista_restore_rejects_outside_roi_without_clipping() -> None:
    from app.learn.hybrid.simple_native_contracts import restore_vista_point_to_capture

    assert restore_vista_point_to_capture((0, 1000), roi_xyxy=(10, 20, 110, 220)) == (10, 220)
    with pytest.raises(ValueError, match="outside"):
        restore_vista_point_to_capture((1001, 0), roi_xyxy=(10, 20, 110, 220))


def test_native_contracts_preserve_utf8_text() -> None:
    from app.learn.hybrid.simple_native_contracts import parse_omni_native_output, parse_vista_normalized_point

    assert parse_omni_native_output({"items": [{"bbox": [0, 0, 1, 1], "type": "文本", "content": "申请职位", "interactivity": False}]})[0].content == "申请职位"
    assert parse_vista_normalized_point("[1, 2]") == (1.0, 2.0)


def _goal_binding_request() -> dict[str, object]:
    return {
        "contract_version": "simple_native_qwen_goal_binding_request_v1",
        "screenshot": {"image_size": {"width": 1280, "height": 720}},
        "goals": [
            {"goal_index": 0, "role": "button", "label": "Open"},
            {"goal_index": 1, "role": "button", "label": "Cancel"},
        ],
        "candidates": [
            {"candidate_id": "candidate/one", "bbox_original": [1, 2, 30, 40], "active": True},
            {"candidate_id": "candidate/two", "bbox_original": [50, 60, 80, 90], "active": False},
        ],
    }


def test_goal_binding_projection_contains_fixed_goals_and_omni_ordinals_only() -> None:
    from app.learn.hybrid.simple_native_contracts import build_qwen_goal_binding_projection

    assert build_qwen_goal_binding_projection(_goal_binding_request()) == {
        "image_size": [1280, 720],
        "goals": [
            {"goal_index": 0, "role": "button", "label": "Open"},
            {"goal_index": 1, "role": "button", "label": "Cancel"},
        ],
        "candidates": [
            {"candidate_index": 0, "bbox": [1, 2, 30, 40], "active": True},
            {"candidate_index": 1, "bbox": [50, 60, 80, 90], "active": False},
        ],
    }


def test_goal_binding_expansion_derives_semantics_and_restores_stable_candidate_ids() -> None:
    from app.learn.hybrid.simple_native_contracts import (
        build_qwen_goal_binding_projection,
        expand_qwen_goal_binding_response,
    )

    request = _goal_binding_request()
    result = expand_qwen_goal_binding_response(
        [
            {"goal_index": 0, "candidate_index": 0, "status": "BOUND", "confidence": 0.9},
            {"goal_index": 1, "candidate_index": None, "status": "UNBOUND", "confidence": 0.1},
        ],
        projection=build_qwen_goal_binding_projection(request),
        runtime_request=request,
    )
    assert result == {"bindings": [
        {"goal_index": 0, "candidate_id": "candidate/one", "role": "button", "label": "Open", "status": "BOUND", "confidence": 0.9},
        {"goal_index": 1, "candidate_id": None, "role": "button", "label": "Cancel", "status": "UNBOUND", "confidence": 0.1},
    ]}


@pytest.mark.parametrize("bindings", [
    [{"goal_index": 0, "candidate_index": 0, "status": "BOUND", "confidence": 1}],
    [{"goal_index": 0, "candidate_index": 0, "status": "BOUND", "confidence": 1}, {"goal_index": 0, "candidate_index": None, "status": "UNBOUND", "confidence": 1}],
    [{"goal_index": 1, "candidate_index": None, "status": "UNBOUND", "confidence": 1}, {"goal_index": 0, "candidate_index": 0, "status": "BOUND", "confidence": 1}],
    [{"goal_index": 0, "candidate_index": 9, "status": "BOUND", "confidence": 1}, {"goal_index": 1, "candidate_index": None, "status": "UNBOUND", "confidence": 1}],
    [{"goal_index": 0, "candidate_index": None, "status": "BOUND", "confidence": 1}, {"goal_index": 1, "candidate_index": 0, "status": "UNBOUND", "confidence": 1}],
    [{"goal_index": 0, "candidate_index": False, "status": "BOUND", "confidence": 1}, {"goal_index": 1, "candidate_index": None, "status": "UNBOUND", "confidence": 1}],
    [{"goal_index": 0, "candidate_index": 0, "status": "AMBIGUOUS", "confidence": 1}, {"goal_index": 1, "candidate_index": None, "status": "UNBOUND", "confidence": 1}],
    [{"goal_index": 0, "candidate_index": 0, "status": "BOUND", "confidence": 1, "role": "bad"}, {"goal_index": 1, "candidate_index": None, "status": "UNBOUND", "confidence": 1}],
])
def test_goal_binding_expansion_fails_closed_on_non_closed_or_invalid_bindings(bindings: list[dict[str, object]]) -> None:
    from app.learn.hybrid.simple_native_contracts import (
        build_qwen_goal_binding_projection,
        expand_qwen_goal_binding_response,
    )

    request = _goal_binding_request()
    with pytest.raises(ValueError):
        expand_qwen_goal_binding_response(
            bindings,
            projection=build_qwen_goal_binding_projection(request),
            runtime_request=request,
        )


def test_goal_binding_expansion_accepts_bare_array_and_reused_candidate() -> None:
    from app.learn.hybrid.simple_native_contracts import (
        build_qwen_goal_binding_projection,
        expand_qwen_goal_binding_response,
    )

    request = _goal_binding_request()
    result = expand_qwen_goal_binding_response(
        [
            {"goal_index": 0, "candidate_index": 0, "status": "BOUND", "confidence": 0.9},
            {"goal_index": 1, "candidate_index": 0, "status": "BOUND", "confidence": 0.8},
        ],
        projection=build_qwen_goal_binding_projection(request),
        runtime_request=request,
    )
    assert [binding["candidate_id"] for binding in result["bindings"]] == [
        "candidate/one", "candidate/one"
    ]


def _native_point_request() -> dict[str, object]:
    return {
        "contract_version": "simple_native_qwen_goal_binding_request_v1",
        "capture_identity": {
            "capture_id": "capture/native-point",
            "screenshot_sha256": "1" * 64,
            "artifact_ref": {"id": "artifact/native-point", "content_sha256": "2" * 64},
            "image_size": {"width": 100, "height": 80},
        },
        "screenshot": {
            "screenshot_sha256": "1" * 64,
            "image_size": {"width": 100, "height": 80},
        },
        "goals": [{"goal_index": 0, "role": "button", "label": "Apply"}],
        "candidates": [
            {"candidate_id": "candidate/inactive", "bbox_original": [0, 0, 30, 30], "active": False},
            {"candidate_id": "candidate/apply", "bbox_original": [10, 10, 40, 40], "active": True},
            {"candidate_id": "candidate/other", "bbox_original": [60, 10, 90, 40], "active": True},
        ],
    }


def _native_source_capture_identity(request: dict[str, object]) -> dict[str, object]:
    from app.learn.recognition.uei.canonical import content_sha256

    identity = request["capture_identity"]
    assert isinstance(identity, dict)
    return {
        "capture_id": identity["capture_id"],
        "screenshot_sha256": identity["screenshot_sha256"],
        "artifact_ref": deepcopy(identity["artifact_ref"]),
        "capture_identity_content_sha256": content_sha256(identity),
    }


def test_native_ui_venus_unique_active_hit_becomes_bound_with_inherited_semantics() -> None:
    from app.learn.hybrid.simple_native_contracts import bind_native_grounding_output

    request = _native_point_request()
    result = bind_native_grounding_output(
        {"point": [250, 375]},
        provider_format="ui_venus_point",
        coordinate_space="normalized_0_1000",
        source_image_size=(100, 80),
        runtime_request=request,
        source_capture_identity=_native_source_capture_identity(request),
        goal_index=0,
        confidence=0.91,
    )

    assert result == {
        "goal_index": 0,
        "candidate_index": 1,
        "candidate_id": "candidate/apply",
        "role": "button",
        "label": "Apply",
        "status": "BOUND",
        "confidence": 0.91,
        "capture_point": [25.0, 30.0],
    }


def test_native_point_with_no_active_hit_becomes_unbound() -> None:
    from app.learn.hybrid.simple_native_contracts import bind_native_grounding_output

    request = _native_point_request()
    result = bind_native_grounding_output(
        {"point": [50, 70]},
        provider_format="ui_venus_point",
        coordinate_space="capture_pixels",
        source_image_size=(100, 80),
        runtime_request=request,
        source_capture_identity=_native_source_capture_identity(request),
        goal_index=0,
        confidence=0.7,
    )

    assert result["status"] == "UNBOUND"
    assert result["candidate_index"] is None
    assert result["candidate_id"] is None
    assert result["capture_point"] == [50.0, 70.0]


def test_native_point_overlapping_multiple_active_candidates_becomes_unbound() -> None:
    from app.learn.hybrid.simple_native_contracts import bind_native_grounding_output

    request = _native_point_request()
    request["candidates"].append(  # type: ignore[union-attr]
        {"candidate_id": "candidate/overlap", "bbox_original": [20, 20, 50, 50], "active": True}
    )
    result = bind_native_grounding_output(
        {"point": [25, 30]},
        provider_format="ui_venus_point",
        coordinate_space="capture_pixels",
        source_image_size=(100, 80),
        runtime_request=request,
        source_capture_identity=_native_source_capture_identity(request),
        goal_index=0,
        confidence=0.8,
    )

    assert result["status"] == "UNBOUND"
    assert result["candidate_index"] is None
    assert result["candidate_id"] is None


def test_native_point_ignores_inactive_candidate_and_requires_strict_box_interior() -> None:
    from app.learn.hybrid.simple_native_contracts import bind_native_grounding_output

    request = _native_point_request()
    inactive_only = bind_native_grounding_output(
        {"point": [5, 5]},
        provider_format="ui_venus_point",
        coordinate_space="capture_pixels",
        source_image_size=(100, 80),
        runtime_request=request,
        source_capture_identity=_native_source_capture_identity(request),
        goal_index=0,
        confidence=0.8,
    )
    right_edge = bind_native_grounding_output(
        {"point": [40, 20]},
        provider_format="ui_venus_point",
        coordinate_space="capture_pixels",
        source_image_size=(100, 80),
        runtime_request=request,
        source_capture_identity=_native_source_capture_identity(request),
        goal_index=0,
        confidence=0.8,
    )

    assert inactive_only["status"] == "UNBOUND"
    assert right_edge["status"] == "UNBOUND"

    left_edge = bind_native_grounding_output(
        {"point": [10, 20]},
        provider_format="ui_venus_point",
        coordinate_space="capture_pixels",
        source_image_size=(100, 80),
        runtime_request=request,
        source_capture_identity=_native_source_capture_identity(request),
        goal_index=0,
        confidence=0.8,
    )
    assert left_edge["status"] == "UNBOUND"


@pytest.mark.parametrize(
    ("raw", "provider_format", "coordinate_space", "source_image_size", "confidence"),
    [
        ({"point": [float("nan"), 0.5]}, "ui_venus_point", "normalized_0_1", (100, 80), 0.5),
        ({"point": [1.1, 0.5]}, "ui_venus_point", "normalized_0_1", (100, 80), 0.5),
        ({"point": [100, 40]}, "ui_venus_point", "capture_pixels", (100, 80), 0.5),
        ({"point": [20, 20], "reasoning": "bad"}, "ui_venus_point", "capture_pixels", (100, 80), 0.5),
        ({"point": [20]}, "ui_venus_point", "capture_pixels", (100, 80), 0.5),
        ({"point": [20, 20]}, "ui_venus_point", "capture_pixels", (101, 80), 0.5),
        ({"point": [20, 20]}, "ui_venus_point", "unknown", (100, 80), 0.5),
        ({"point": [20, 20]}, "ui_venus_point", "capture_pixels", (100, 80), float("nan")),
    ],
)
def test_native_grounding_malformed_or_capture_mismatch_fails_closed(
    raw: object,
    provider_format: str,
    coordinate_space: str,
    source_image_size: tuple[int, int],
    confidence: float,
) -> None:
    from app.learn.hybrid.simple_native_contracts import bind_native_grounding_output

    request = _native_point_request()
    result = bind_native_grounding_output(
        raw,
        provider_format=provider_format,
        coordinate_space=coordinate_space,
        source_image_size=source_image_size,
        runtime_request=request,
        source_capture_identity=_native_source_capture_identity(request),
        goal_index=0,
        confidence=confidence,
    )

    assert result["status"] == "PROVIDER_FAILURE"
    assert result["candidate_index"] is None
    assert result["candidate_id"] is None
    assert result["capture_point"] is None


def test_gui_actor_uses_top_one_only_and_never_cherry_picks_later_hit() -> None:
    from app.learn.hybrid.simple_native_contracts import bind_native_grounding_output

    request = _native_point_request()
    result = bind_native_grounding_output(
        {"topk_points": [[0.5, 0.875], [0.25, 0.375]]},
        provider_format="gui_actor_topk_points",
        coordinate_space="normalized_0_1",
        source_image_size=(100, 80),
        runtime_request=request,
        source_capture_identity=_native_source_capture_identity(request),
        goal_index=0,
        confidence=0.8,
    )

    assert result["status"] == "UNBOUND"
    assert result["capture_point"] == [50.0, 70.0]


def test_gui_actor_top_one_is_not_polluted_by_malformed_later_points() -> None:
    from app.learn.hybrid.simple_native_contracts import bind_native_grounding_output

    request = _native_point_request()
    for malformed_later_point in ([float("nan"), 0.3], [0.2], "bad"):
        result = bind_native_grounding_output(
            {"topk_points": [[0.25, 0.375], malformed_later_point]},
            provider_format="gui_actor_topk_points",
            coordinate_space="normalized_0_1",
            source_image_size=(100, 80),
            runtime_request=request,
            source_capture_identity=_native_source_capture_identity(request),
            goal_index=0,
            confidence=0.8,
        )
        assert result["status"] == "BOUND"
        assert result["candidate_id"] == "candidate/apply"


def test_phi_ground_point_or_bbox_uses_bbox_center_before_unique_binding() -> None:
    from app.learn.hybrid.simple_native_contracts import bind_native_grounding_output

    request = _native_point_request()
    result = bind_native_grounding_output(
        {"bbox": [0.1, 0.125, 0.4, 0.5]},
        provider_format="phi_ground_point_or_bbox",
        coordinate_space="normalized_0_1",
        source_image_size=(100, 80),
        runtime_request=request,
        source_capture_identity=_native_source_capture_identity(request),
        goal_index=0,
        confidence=0.85,
    )

    assert result["status"] == "BOUND"
    assert result["candidate_id"] == "candidate/apply"
    assert result["capture_point"] == [25.0, 25.0]


@pytest.mark.parametrize(
    ("bbox", "coordinate_space"),
    [
        ([-0.1, 0.1, 0.4, 0.5], "normalized_0_1"),
        ([0.1, 0.1, 1.1, 0.5], "normalized_0_1"),
        ([0, 0, 101, 40], "capture_pixels"),
        ([0, -1, 40, 40], "capture_pixels"),
    ],
)
def test_phi_ground_bbox_edges_are_validated_before_centering(
    bbox: list[float], coordinate_space: str
) -> None:
    from app.learn.hybrid.simple_native_contracts import bind_native_grounding_output

    request = _native_point_request()
    result = bind_native_grounding_output(
        {"bbox": bbox},
        provider_format="phi_ground_point_or_bbox",
        coordinate_space=coordinate_space,
        source_image_size=(100, 80),
        runtime_request=request,
        source_capture_identity=_native_source_capture_identity(request),
        goal_index=0,
        confidence=0.8,
    )
    assert result["status"] == "PROVIDER_FAILURE"
    assert result["capture_point"] is None


@pytest.mark.parametrize("changed_field", ["capture_id", "screenshot_sha256", "artifact_ref"])
def test_native_grounding_rejects_same_size_but_different_capture_lineage(
    changed_field: str,
) -> None:
    from app.learn.hybrid.simple_native_contracts import bind_native_grounding_output

    request = _native_point_request()
    source_identity = _native_source_capture_identity(request)
    if changed_field == "capture_id":
        source_identity[changed_field] = "capture/other"
    elif changed_field == "screenshot_sha256":
        source_identity[changed_field] = "3" * 64
    else:
        source_identity[changed_field] = {
            "id": "artifact/other",
            "content_sha256": "4" * 64,
        }
    result = bind_native_grounding_output(
        {"point": [25, 30]},
        provider_format="ui_venus_point",
        coordinate_space="capture_pixels",
        source_image_size=(100, 80),
        runtime_request=request,
        source_capture_identity=source_identity,
        goal_index=0,
        confidence=0.8,
    )
    assert result["status"] == "PROVIDER_FAILURE"
    assert result["capture_point"] is None


def test_native_grounding_rejects_forged_capture_identity_content_hash() -> None:
    from app.learn.hybrid.simple_native_contracts import bind_native_grounding_output

    request = _native_point_request()
    source_identity = _native_source_capture_identity(request)
    source_identity["capture_identity_content_sha256"] = "f" * 64
    result = bind_native_grounding_output(
        {"point": [25, 30]},
        provider_format="ui_venus_point",
        coordinate_space="capture_pixels",
        source_image_size=(100, 80),
        runtime_request=request,
        source_capture_identity=source_identity,
        goal_index=0,
        confidence=0.8,
    )
    assert result["status"] == "PROVIDER_FAILURE"
    assert result["capture_point"] is None


def test_native_grounding_rejects_unknown_provider_format_explicitly() -> None:
    from app.learn.hybrid.simple_native_contracts import bind_native_grounding_output

    request = _native_point_request()
    with pytest.raises(ValueError, match="provider_format"):
        bind_native_grounding_output(
            {"point": [20, 20]},
            provider_format="future_provider",
            coordinate_space="capture_pixels",
            source_image_size=(100, 80),
            runtime_request=request,
            source_capture_identity=_native_source_capture_identity(request),
            goal_index=0,
            confidence=0.5,
        )
