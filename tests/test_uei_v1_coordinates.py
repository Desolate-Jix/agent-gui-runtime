from __future__ import annotations

import hashlib
import math

from app.learn.recognition.uei.canonical import canonical_json_bytes, seal_immutable

import pytest

from app.learn.recognition.uei.contracts import UEIProjectionFailure


SHA = "a" * 64
PROVIDER = "local.acme.vision/ocr"
PROFILE = "local.acme.vision/ocr/latin-desktop"
BINDING = {"artifact_sha256": SHA, "image_size": {"width": 10, "height": 10}}


def _transform(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "contract_version": "affine_coordinate_transform_v1",
        "source_space": "image_pixel_xyxy",
        "target_space": "capture_pixel_xyxy",
        "source_size": {"width": 10, "height": 10},
        "target_size": {"width": 10, "height": 10},
        "scale": {"x": 1, "y": 1},
        "offset": {"x": 0, "y": 0},
        "rounding": "outward",
        "clipping": "reject_if_outside",
        "source_capture_artifact_sha256": SHA,
        "target_capture_artifact_sha256": SHA,
    }
    value.update(overrides)
    return seal_immutable(value)


def _project(**overrides: object):
    from app.learn.recognition.uei.projections import project_capture_bbox

    arguments: dict[str, object] = {
        "source_bbox": [1, 2, 8, 9],
        "source_coordinate_space": "image_pixel_xyxy",
        "binding": BINDING,
        "request_artifact_sha256": SHA,
        "request_image_size": {"width": 10, "height": 10},
        "transform": _transform(),
    }
    arguments.update(overrides)
    return project_capture_bbox(**arguments)


def _item(**overrides: object) -> dict[str, object]:
    from app.learn.recognition.uei.projections import make_source_item

    arguments: dict[str, object] = {
        "provider_id": PROVIDER,
        "profile_id": PROFILE,
        "capture_lineage_ref": {"id": "capture/test", "content_sha256": SHA},
        "source_index": 0,
        "source_item_id": None,
        "source_id_origin": "uei_deterministic_projection",
        "kind": "text",
        "safe_text": "Label",
        "safe_role": None,
        "safe_states": [],
        "source_bbox": [1, 2, 8, 9],
        "source_coordinate_space": "image_pixel_xyxy",
        "capture_bbox": [1, 2, 8, 9],
        "coordinate_transform_ref": {"id": "b" * 64, "content_sha256": "b" * 64},
        "opaque_attributes": {},
        "provider_confidence": None,
    }
    arguments.update(overrides)
    return make_source_item(**arguments)


def test_missing_transform_retains_source_bbox_but_has_no_capture_bbox():
    from app.learn.recognition.uei.projections import project_capture_bbox

    capture_bbox, transform_ref, review_only = project_capture_bbox(
        source_bbox=[1, 2, 8, 9],
        source_coordinate_space="image_pixel_xyxy",
        binding=BINDING,
        request_artifact_sha256=SHA,
        request_image_size={"width": 10, "height": 10},
        transform=None,
    )
    item = _item(capture_bbox=capture_bbox, coordinate_transform_ref=transform_ref)
    assert (capture_bbox, transform_ref, review_only) == (None, None, True)
    assert item["source_bbox"] == [1, 2, 8, 9] and item["capture_bbox"] is None


def test_identity_projection_requires_exact_capture_binding():
    assert _project(
        source_coordinate_space="capture_pixel_xyxy",
        transform=None,
    ) == ([1, 2, 8, 9], None, False)
    assert _project(
        source_coordinate_space="capture_pixel_xyxy",
        binding={"artifact_sha256": SHA, "image_size": {"width": 9, "height": 10}},
        transform=None,
    ) == (None, None, True)


@pytest.mark.parametrize(
    ("rounding", "source_bbox", "expected"),
    [
        ("outward", [1, 2, 8, 9], [1, 2, 9, 10]),
        ("nearest", [3, 5, 7, 9], [2, 3, 4, 5]),
        ("none", [1, 2, 8, 9], [1, 2, 8, 9]),
    ],
)
def test_transform_rounding_is_explicit_and_deterministic(rounding, source_bbox, expected):
    transform = _transform(
        rounding=rounding,
        scale={"x": 1.1, "y": 1.1} if rounding == "outward" else {"x": 0.5, "y": 0.5} if rounding == "nearest" else {"x": 1, "y": 1},
    )
    result = _project(source_bbox=source_bbox, transform=transform)
    assert result[0] == expected
    assert result[2] is False


def test_proven_transform_reference_uses_its_content_addressed_store_identity():
    capture_bbox, transform_ref, review_only = _project()
    assert capture_bbox == [1, 2, 8, 9]
    assert transform_ref == {
        "id": _transform()["content_sha256"],
        "content_sha256": _transform()["content_sha256"],
    }
    assert review_only is False


def test_none_rounding_rejects_non_integral_edges():
    with pytest.raises(UEIProjectionFailure, match="coordinate_invalid"):
        _project(source_bbox=[1, 2, 8, 9], transform=_transform(rounding="none", scale={"x": 1.1, "y": 1}))


def test_clip_to_target_applies_after_affine_projection():
    assert _project(
        source_bbox=[1, 1, 9, 9],
        transform=_transform(scale={"x": 2, "y": 1}, offset={"x": -5, "y": 0}, clipping="clip_to_target"),
    )[0] == [0, 1, 10, 9]
    with pytest.raises(UEIProjectionFailure, match="coordinate_invalid"):
        _project(source_bbox=[1, 1, 9, 9], transform=_transform(scale={"x": 2, "y": 1}, offset={"x": -5, "y": 0}))


@pytest.mark.parametrize(
    "source_space",
    [
        "screen_pixel_xyxy",
        "window_outer_pixel_xyxy",
        "window_client_pixel_xyxy",
        "capture_pixel_xyxy",
        "image_pixel_xyxy",
        "image_normalized_xyxy",
    ],
)
def test_every_declared_source_space_projects_with_same_capture_affine(source_space):
    source_bbox = [0.1, 0.2, 0.8, 0.9] if source_space == "image_normalized_xyxy" else [1, 2, 8, 9]
    transform = _transform(
        source_space=source_space,
        scale={"x": 10, "y": 10} if source_space == "image_normalized_xyxy" else {"x": 1, "y": 1},
        source_size={"width": 1, "height": 1} if source_space == "image_normalized_xyxy" else {"width": 10, "height": 10},
    )
    assert _project(source_bbox=source_bbox, source_coordinate_space=source_space, transform=transform)[0] == [1, 2, 8, 9]


@pytest.mark.parametrize(
    "invalid_bbox",
    [[1, 2, 1, 9], [1, 2, math.inf, 9], [1, 2, 8], [1, -1, 8, 9]],
)
def test_source_bbox_must_be_finite_xyxy_and_within_declared_source_bounds(invalid_bbox):
    with pytest.raises(UEIProjectionFailure, match="coordinate_invalid"):
        _project(source_bbox=invalid_bbox)


@pytest.mark.parametrize(
    "transform",
    [
        _transform(source_capture_artifact_sha256="c" * 64),
        _transform(target_capture_artifact_sha256="c" * 64),
        _transform(target_size={"width": 9, "height": 10}),
        _transform(source_space="screen_pixel_xyxy"),
        _transform(target_space="image_pixel_xyxy"),
        _transform(scale={"x": 0, "y": 1}),
    ],
)
def test_conflicting_or_unusable_transform_is_projection_failure(transform):
    with pytest.raises(UEIProjectionFailure, match="coordinate_invalid") as error:
        _project(transform=transform)
    assert getattr(error.value, "code") == "coordinate_invalid"
    assert getattr(error.value, "stage") == "coordinate"


def test_absent_or_harmless_unproven_transform_is_review_only():
    assert _project(transform={"hint": "not an affine proof"}) == (None, None, True)


def test_deterministic_ocr_ids_use_safe_projection_identity_and_source_index():
    first = _item(capture_bbox=None, coordinate_transform_ref=None)
    second = _item(source_index=1, capture_bbox=None, coordinate_transform_ref=None)
    expected_record = {
        "provider_id": PROVIDER,
        "profile_id": PROFILE,
        "capture_lineage_ref": {"id": "capture/test", "content_sha256": SHA},
        "source_index": 0,
        "kind": "text",
        "safe_text": "Label",
        "safe_role": None,
        "safe_states": [],
        "source_bbox": [1, 2, 8, 9],
        "source_coordinate_space": "image_pixel_xyxy",
    }
    assert first["source_item_id"] == "sha256:" + hashlib.sha256(canonical_json_bytes(expected_record)).hexdigest()
    assert first["source_item_id"] != second["source_item_id"]
    assert first["source_id_origin"] == "uei_deterministic_projection"


def test_make_source_item_preserves_provider_id_and_excludes_action_or_auth_fields():
    item = _item(source_item_id="provider-item", source_id_origin="provider")
    assert item["source_item_id"] == "provider-item"
    assert item["source_id_origin"] == "provider"
    assert set(item) == {
        "source_item_id", "source_id_origin", "kind", "safe_text", "safe_role", "safe_states",
        "source_bbox", "capture_bbox", "source_coordinate_space", "coordinate_transform_ref",
        "opaque_attributes", "provider_confidence",
    }


def test_safe_item_keeps_only_schema_valid_source_coordinate_edges():
    with pytest.raises(UEIProjectionFailure, match="coordinate_invalid"):
        _item(source_bbox=[1.1, 2, 8, 9])
    assert _item(
        source_coordinate_space="image_normalized_xyxy",
        source_bbox=[0.1, 0.2, 0.8, 0.9],
    )["source_bbox"] == [0.1, 0.2, 0.8, 0.9]


def test_pixel_source_boxes_require_non_negative_integer_edges_before_projection():
    with pytest.raises(UEIProjectionFailure, match="coordinate_invalid"):
        _project(source_bbox=[1.1, 2, 8, 9])


def test_safe_item_rejects_non_safe_or_out_of_contract_item_fields():
    for overrides in (
        {"kind": "action"},
        {"safe_states": ["visible", "visible"]},
        {"source_bbox": [1, 2, 100001, 9]},
        {"capture_bbox": [1, 2, 100001, 9]},
    ):
        with pytest.raises(UEIProjectionFailure, match="coordinate_invalid"):
            _item(**overrides)


def test_supplied_transform_is_a_sealed_closed_affine_contract():
    transform = _transform()
    transform["scale"] = {"x": 2, "y": 1}
    with pytest.raises(UEIProjectionFailure, match="coordinate_invalid"):
        _project(transform=transform)

    transform = _transform()
    transform["unexpected"] = True
    with pytest.raises(UEIProjectionFailure, match="coordinate_invalid"):
        _project(transform=transform)

    transform = _transform()
    transform["content_sha256"] = "0" * 64
    with pytest.raises(UEIProjectionFailure, match="coordinate_invalid"):
        _project(transform=transform)


def test_safe_item_rejects_invalid_refs_text_states_and_opaque_payload():
    too_deep: object = "too_deep"
    for _ in range(9):
        too_deep = [too_deep]
    invalid_calls = (
        {"provider_id": ""},
        {"capture_lineage_ref": {"id": "capture/test", "content_sha256": "A" * 64}},
        {"capture_lineage_ref": {"id": "capture/test", "content_sha256": SHA, "extra": True}},
        {"safe_text": "x" * 4097},
        {"safe_states": ["x"] * 65},
        {"opaque_attributes": {"bad": float("inf")}},
        {"opaque_attributes": {"nested": too_deep}},
    )
    for overrides in invalid_calls:
        with pytest.raises(UEIProjectionFailure, match="coordinate_invalid"):
            _item(**overrides)


@pytest.mark.parametrize(
    "binding",
    [
        {"artifact_sha256": "c" * 64, "image_size": {"width": 10, "height": 10}},
        {"artifact_sha256": SHA, "image_size": {"width": 9, "height": 10}},
        {"artifact_sha256": SHA, "image_size": {"width": 10, "height": 11}},
    ],
)
def test_affine_projection_requires_exact_fixture_binding_to_the_request_capture(binding):
    with pytest.raises(UEIProjectionFailure, match="coordinate_invalid"):
        _project(binding=binding)


def test_safe_item_converts_canonicalization_failures_to_projection_failure():
    with pytest.raises(UEIProjectionFailure, match="coordinate_invalid"):
        _item(source_index=(1 << 80) + 1)


def test_reserved_partial_transform_and_scalar_transform_fail_closed():
    with pytest.raises(UEIProjectionFailure, match="coordinate_invalid"):
        _project(transform={"source_space": "image_pixel_xyxy"})
    with pytest.raises(UEIProjectionFailure, match="coordinate_invalid"):
        _project(transform="unproven")
    transform = _transform()
    del transform["contract_version"]
    with pytest.raises(UEIProjectionFailure, match="coordinate_invalid"):
        _project(transform=transform)

def test_safe_item_rejects_lone_surrogates_in_provider_and_output_fields():
    with pytest.raises(UEIProjectionFailure, match="coordinate_invalid"):
        _item(provider_id="local/\ud800", source_item_id="provider-item", source_id_origin="provider")
    with pytest.raises(UEIProjectionFailure, match="coordinate_invalid"):
        _item(safe_text="safe\ud800")
