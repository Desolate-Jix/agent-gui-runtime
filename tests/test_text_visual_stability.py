from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from io import BytesIO

import pytest
from PIL import Image

from app.agent.text_field_evidence import (
    TextFieldExpectation,
    TextFieldIdentity,
    TextFieldSnapshot,
    prepare_text_field_expectation,
)
from app.agent.text_parameters import (
    ReviewedTextParameters,
    ReviewedTextSource,
    ResolvedTextParameters,
)
from app.agent.text_visual_stability import (
    TextVisualPixelsChanged,
    TextVisualStabilityAttestation,
    TextVisualStabilityScope,
    verify_text_visual_stability_reference,
)


SIZE = (360, 260)
FIELD_BBOX = (80, 60, 100, 30)


def _png(*, changes: tuple[tuple[int, int], ...] = (), size=SIZE) -> bytes:
    image = Image.new("RGB", size, "white")
    for point in changes:
        image.putpixel(point, (0, 0, 0))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _expectation(*, capture_id="capture-before", pid=22, created=33.5, bbox=FIELD_BBOX):
    identity = TextFieldIdentity(
        target_field_id="field-search",
        window_handle=11,
        process_id=pid,
        process_create_time=created,
        runtime_id=(42, 7, 9),
        window_rect=(0, 0, *SIZE),
        control_bbox=bbox,
    )
    before = TextFieldSnapshot(
        identity=identity,
        capture_id=capture_id,
        read_id="read-before",
        observed_at_ns=150,
        source="uia_value",
        value="",
        selection=None,
    )
    reviewed = ReviewedTextParameters(
        target_field_id="field-search",
        content=ReviewedTextSource(kind="literal", value="map"),
        clear_existing=True,
        sensitive=False,
    )
    return prepare_text_field_expectation(
        before,
        ResolvedTextParameters(reviewed=reviewed, text="map"),
    )


def _evidence(png: bytes, *, capture_id: str, started: int) -> dict:
    return {
        "contract_version": "fresh_learning_observation_v1",
        "target": {
            "window_handle": 11,
            "process_id": 22,
            "rect": {"x": 0, "y": 0, "width": SIZE[0], "height": SIZE[1]},
        },
        "application": {
            "kind": "native",
            "executable_path": r"C:\Program Files\Example\example.exe",
            "process_create_time": 33.5,
        },
        "uia": {
            "provider": "windows_uia",
            "provider_version": "1",
            "status": "ok",
            "control_count": 4,
            "snapshot_sha256": "a" * 64,
        },
        "capture": {
            "capture_id": capture_id,
            "capture_started_ns": started,
            "capture_clock_id": "windows-perf-counter-v1",
            "viewport_size": {"width": SIZE[0], "height": SIZE[1]},
            "screenshot_sha256": sha256(png).hexdigest(),
        },
        # 模型前没有这些字段；稳定摘要必须忽略后续附加内容。
        "recognition": {"result_sha256": "b" * 64},
        "artifact_is_authorization": False,
    }


def _scope():
    before_png = _png()
    before = _evidence(before_png, capture_id="capture-before", started=100)
    return TextVisualStabilityScope(
        expectation=_expectation(),
        original_evidence=before,
        original_png_bytes=before_png,
    ), before, before_png


def _connected_68_pixels() -> tuple[tuple[int, int], ...]:
    points = [(260 + x, 180 + y) for y in range(7) for x in range(10)]
    return tuple(points[:-2])


def test_identical_png_is_attested_and_full_packet_binding_revalidates():
    scope, before, before_png = _scope()
    current_png = _png()
    current = _evidence(current_png, capture_id="capture-after", started=200)

    proof = scope.validate(current_evidence=current, current_png_bytes=current_png)
    reference = proof.to_reference()

    assert type(proof) is TextVisualStabilityAttestation
    assert reference["policy"] == "fill_field_protected_pixels_v1"
    assert reference["protected_bbox"] == [72, 52, 116, 46]
    assert reference["changed_pixels"] == 0
    assert reference["changed_bbox"] is None
    full_current = deepcopy(current)
    full_current["recognition"] = {"different_derived_content": True}
    proof.validate_binding(before, full_current, _expectation().to_reference())


def test_connected_68_pixel_far_animation_is_attested():
    scope, before, _ = _scope()
    current_png = _png(changes=_connected_68_pixels())
    current = _evidence(current_png, capture_id="capture-after", started=200)

    proof = scope.validate(current_evidence=current, current_png_bytes=current_png)

    assert proof.to_reference()["changed_pixels"] == 68
    assert proof.to_reference()["changed_bbox"] == [260, 180, 10, 7]
    proof.validate_binding(before, current, _expectation().to_reference())


@pytest.mark.parametrize(
    "changes",
    [
        ((80, 60),),  # 字段内部
        ((72, 52),),  # 固定八像素边缘
        ((251, 75),),  # 距保护框不足 64px
        ((260, 180), (310, 230)),  # 两个分散变化区域
        tuple((250 + x, 170 + y) for y in range(11) for x in range(12)),  # 132px
    ],
)
def test_unsafe_pixel_changes_are_rejected(changes):
    scope, _, _ = _scope()
    current_png = _png(changes=changes)
    current = _evidence(current_png, capture_id="capture-after", started=200)

    with pytest.raises(TextVisualPixelsChanged):
        scope.validate(current_evidence=current, current_png_bytes=current_png)


def test_viewport_or_png_hash_mismatch_is_rejected():
    scope, _, _ = _scope()
    current_png = _png()
    wrong_viewport = _evidence(current_png, capture_id="capture-after", started=200)
    wrong_viewport["capture"]["viewport_size"]["width"] += 1
    with pytest.raises(ValueError):
        scope.validate(current_evidence=wrong_viewport, current_png_bytes=current_png)

    wrong_hash = _evidence(current_png, capture_id="capture-after", started=200)
    wrong_hash["capture"]["screenshot_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        scope.validate(current_evidence=wrong_hash, current_png_bytes=current_png)


def test_image_size_is_rejected():
    scope, _, _ = _scope()
    different_size = _png(size=(SIZE[0] + 1, SIZE[1]))
    size_evidence = _evidence(different_size, capture_id="capture-after", started=200)
    with pytest.raises(ValueError):
        scope.validate(current_evidence=size_evidence, current_png_bytes=different_size)


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("target", "window_handle", 12),
        ("target", "process_id", 23),
        ("application", "process_create_time", 34.5),
        ("uia", "snapshot_sha256", "c" * 64),
        ("capture", "capture_id", "capture-before"),
        ("capture", "capture_started_ns", 99),
        ("capture", "capture_clock_id", "other-clock"),
    ],
)
def test_live_identity_and_capture_binding_drift_is_rejected(section, key, value):
    scope, _, _ = _scope()
    current_png = _png()
    drift = _evidence(current_png, capture_id="capture-after", started=200)
    drift[section][key] = value
    with pytest.raises(ValueError):
        scope.validate(current_evidence=drift, current_png_bytes=current_png)


def test_scope_rejects_field_binding_drift_and_non_typed_expectation():
    before_png = _png()
    before = _evidence(before_png, capture_id="capture-before", started=100)
    with pytest.raises((TypeError, ValueError)):
        TextVisualStabilityScope(
            expectation=_expectation(pid=23),
            original_evidence=before,
            original_png_bytes=before_png,
        )
    with pytest.raises((TypeError, ValueError)):
        TextVisualStabilityScope(
            expectation=_expectation().to_reference(),
            original_evidence=before,
            original_png_bytes=before_png,
        )


def test_proof_binding_rejects_changed_evidence_or_field_reference():
    scope, before, _ = _scope()
    current_png = _png(changes=_connected_68_pixels())
    current = _evidence(current_png, capture_id="capture-after", started=200)
    proof = scope.validate(current_evidence=current, current_png_bytes=current_png)

    changed = deepcopy(current)
    changed["capture"]["capture_id"] = "capture-other"
    with pytest.raises(ValueError):
        proof.validate_binding(before, changed, _expectation().to_reference())
    other_field = _expectation(bbox=(81, 60, 100, 30)).to_reference()
    with pytest.raises(ValueError):
        proof.validate_binding(before, current, other_field)
    with pytest.raises(TypeError):
        TextVisualStabilityAttestation(**proof.to_reference())


def test_persisted_reference_recomputes_without_restoring_typed_proof():
    scope, before, before_png = _scope()
    current_png = _png(changes=_connected_68_pixels())
    current = _evidence(current_png, capture_id="capture-after", started=200)
    reference = scope.validate(
        current_evidence=current, current_png_bytes=current_png
    ).to_reference()

    result = verify_text_visual_stability_reference(
        reference,
        original_evidence=before,
        current_evidence=current,
        field_expectation_reference=scope.expectation_reference,
        original_png_bytes=before_png,
        current_png_bytes=current_png,
    )

    assert result is None
    assert type(reference) is dict
    assert not isinstance(reference, TextVisualStabilityAttestation)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("changed_pixels", 67),
        ("changed_bbox", [260, 180, 9, 7]),
        ("after_evidence_sha256", "0" * 64),
        ("field_expectation_sha256", "0" * 64),
        ("policy", "fill_field_unbounded_v2"),
    ],
)
def test_persisted_reference_tampering_is_rejected(key, value):
    scope, before, before_png = _scope()
    current_png = _png(changes=_connected_68_pixels())
    current = _evidence(current_png, capture_id="capture-after", started=200)
    reference = scope.validate(
        current_evidence=current, current_png_bytes=current_png
    ).to_reference()
    reference[key] = value

    with pytest.raises(ValueError):
        verify_text_visual_stability_reference(
            reference,
            original_evidence=before,
            current_evidence=current,
            field_expectation_reference=scope.expectation_reference,
            original_png_bytes=before_png,
            current_png_bytes=current_png,
        )


def test_persisted_reference_rejects_different_png_even_with_matching_evidence_hash():
    scope, before, before_png = _scope()
    current_png = _png(changes=_connected_68_pixels())
    current = _evidence(current_png, capture_id="capture-after", started=200)
    reference = scope.validate(
        current_evidence=current, current_png_bytes=current_png
    ).to_reference()
    other_png = _png(changes=((260, 180),))
    other_current = deepcopy(current)
    other_current["capture"]["screenshot_sha256"] = sha256(other_png).hexdigest()

    with pytest.raises(ValueError):
        verify_text_visual_stability_reference(
            reference,
            original_evidence=before,
            current_evidence=other_current,
            field_expectation_reference=scope.expectation_reference,
            original_png_bytes=before_png,
            current_png_bytes=other_png,
        )
