from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

import pytest
from PIL import Image

import app.learn.scoped_capture as scoped_capture
from app.learn.scoped_capture import (
    ScopedCaptureCompositionError,
    ScopedCaptureError,
    build_scoped_capture_artifact,
)


ROI = {"x": 0, "y": 0, "width": 10, "height": 6}
VIEWPORT = {"width": 10, "height": 6}


def _save_rows(path, rows: list[int]) -> None:
    image = Image.new("L", (10, len(rows)))
    image.putdata([(value + column * 17) % 256 for value in rows for column in range(10)])
    image.convert("RGB").save(path)


def _build(tmp_path, records: list[dict], *, stop_reason: str = "reached_bottom") -> dict:
    return build_scoped_capture_artifact(
        segment_records=records,
        output_dir=tmp_path / "artifact",
        roi=ROI,
        viewport=VIEWPORT,
        stop_reason=stop_reason,
    )


def test_stitches_two_segments_with_deterministic_vertical_overlap(tmp_path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first_rows = [(index * 37 + 11) % 251 for index in range(32)]
    second_rows = first_rows[-16:] + [(index * 53 + 19) % 251 for index in range(16)]
    _save_rows(first, first_rows)
    _save_rows(second, second_rows)

    artifact = _build(tmp_path, [{"image_path": first}, {"image_path": second}])

    with Image.open(artifact["composite_path"]) as composite:
        assert composite.size == (10, 48)
    assert artifact["overlap_evidence"] == [
        {
            "from_index": 0,
            "to_index": 1,
            "overlap_pixels": 16,
            "mean_absolute_error": 0.0,
            "confidence": "high",
        }
    ]


def test_records_the_measured_error_when_no_credible_overlap_exists(tmp_path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    _save_rows(first, [10 + (index * 7) % 120 for index in range(32)])
    _save_rows(second, [180 + (index * 5) % 60 for index in range(32)])

    artifact = _build(tmp_path, [{"image_path": first}, {"image_path": second}])

    evidence = artifact["overlap_evidence"][0]
    assert evidence["overlap_pixels"] == 0
    assert evidence["confidence"] == "none"
    assert evidence["mean_absolute_error"] > 12.0



def test_exact_duplicate_is_retained_but_not_stitched(tmp_path) -> None:
    first = tmp_path / "first.png"
    _save_rows(first, [11, 43, 79, 103, 151, 197])

    artifact = _build(
        tmp_path,
        [
            {"image_path": first, "capture_id": "capture-0"},
            {"image_path": first, "capture_id": "capture-1"},
        ],
    )

    assert [(segment["accepted"], segment["duplicate_of"]) for segment in artifact["segments"]] == [
        (True, None),
        (False, 0),
    ]
    assert [segment["capture_id"] for segment in artifact["segments"]] == ["capture-0", "capture-1"]
    with Image.open(artifact["composite_path"]) as composite:
        assert composite.size == (10, 6)


@pytest.mark.parametrize("record", [{"image_path": "missing.png"}, {"image_path": "not-image.txt"}])
def test_rejects_missing_or_unreadable_segments_with_index_and_path(tmp_path, record: dict) -> None:
    if record["image_path"] == "not-image.txt":
        (tmp_path / record["image_path"]).write_bytes(b"not a PNG")
    record["image_path"] = tmp_path / record["image_path"]

    with pytest.raises(ScopedCaptureError) as exc_info:
        _build(tmp_path, [record])

    message = str(exc_info.value)
    assert "segment 0" in message
    assert str(record["image_path"]) in message


def test_manifest_round_trip_preserves_raw_segments_and_optional_fields(tmp_path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    _save_rows(first, [11, 43, 79, 103, 151, 197])
    _save_rows(second, [151, 197, 29, 67, 113, 173])
    raw_before = {path: path.read_bytes() for path in (first, second)}
    trace_first = tmp_path / "trace-first.json"
    records = [
        {
            "image_path": first,
            "capture_id": "capture-first",
            "scroll_trace_path": trace_first,
            "scroll_effect": {"changed": True},
        },
        {
            "image_path": second,
            "capture_id": "capture-second",
            "scroll_trace_path": "trace-second.json",
            "scroll_effect": {"changed": True, "delta": 4},
        },
    ]

    artifact = _build(tmp_path, records)

    manifest_path = Path(artifact["manifest_path"])
    assert manifest_path.read_bytes().endswith(b"\n")
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == artifact
    assert {path: path.read_bytes() for path in raw_before} == raw_before
    assert artifact["segments"][0]["image_path"] == str(first.resolve())
    assert artifact["segments"][0]["scroll_trace_path"] == str(trace_first)
    assert artifact["segments"][1]["scroll_effect"] == {"changed": True, "delta": 4}
    assert artifact["segments"][0]["sha256"] == hashlib.sha256(first.read_bytes()).hexdigest()


@pytest.mark.parametrize(
    ("stop_reason", "status"),
    [
        ("reached_bottom", "complete"),
        ("max_captures", "incomplete"),
        ("cancelled", "incomplete"),
        ("wrong_scope", "incomplete"),
        ("blocked_surface", "incomplete"),
        ("no_new_content", "unknown"),
    ],
)
def test_maps_stop_reason_to_content_completeness(tmp_path, stop_reason: str, status: str) -> None:
    segment = tmp_path / f"{stop_reason}.png"
    _save_rows(segment, [11, 43, 79, 103, 151, 197])

    artifact = _build(tmp_path, [{"image_path": segment}], stop_reason=stop_reason)

    assert artifact["content_completeness"]["status"] == status
    assert artifact["content_completeness"]["reason"] == stop_reason


def test_marks_artifact_as_non_authorizing_and_coordinates_as_priors(tmp_path) -> None:
    segment = tmp_path / "segment.png"
    _save_rows(segment, [11, 43, 79, 103, 151, 197])

    artifact = _build(tmp_path, [{"image_path": segment}])

    assert artifact["artifact_is_authorization"] is False
    assert artifact["historical_coordinates_are_priors"] is True



def _save_fixed_band(path: Path, right_color: tuple[int, int, int]) -> None:
    image = Image.new("RGB", (300, 20))
    pixels = []
    for row in range(20):
        for column in range(300):
            if column < 256:
                value = (column * 19 + row * 37) % 256
                pixels.append((value, (value * 3) % 256, (value * 7) % 256))
            else:
                pixels.append(right_color)
    image.putdata(pixels)
    image.save(path)


def _call_builder(tmp_path: Path, *, records: list[dict], roi: dict | None = None, viewport: dict | None = None, stop_reason: str = "reached_bottom", output_dir: Path | None = None) -> dict:
    return build_scoped_capture_artifact(
        segment_records=records,
        output_dir=output_dir or tmp_path / "artifact",
        roi=ROI if roi is None else roi,
        viewport=VIEWPORT if viewport is None else viewport,
        stop_reason=stop_reason,
    )


def test_fixed_left_band_cannot_fabricate_full_segment_overlap(tmp_path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    _save_fixed_band(first, (255, 0, 0))
    _save_fixed_band(second, (0, 0, 255))

    artifact = _call_builder(tmp_path, records=[{"image_path": first}, {"image_path": second}], roi={"x": 0, "y": 0, "width": 300, "height": 20}, viewport={"width": 300, "height": 20})

    assert artifact["overlap_evidence"][0]["overlap_pixels"] == 0
    assert artifact["overlap_evidence"][0]["confidence"] == "none"
    with Image.open(artifact["composite_path"]) as composite:
        assert composite.size == (300, 40)


def test_low_information_blank_images_are_appended_without_overlap_claim(tmp_path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.new("RGB", (40, 8), "white").save(first)
    Image.new("RGB", (40, 8), "white").save(second)
    second.write_bytes(second.read_bytes() + b"blank-metadata")

    artifact = _call_builder(tmp_path, records=[{"image_path": first}, {"image_path": second}], roi={"x": 0, "y": 0, "width": 40, "height": 8}, viewport={"width": 40, "height": 8})

    assert artifact["overlap_evidence"][0]["overlap_pixels"] == 0
    assert artifact["overlap_evidence"][0]["confidence"] == "none"
    with Image.open(artifact["composite_path"]) as composite:
        assert composite.height == 16


def test_ambiguous_periodic_rows_are_appended_without_alignment_claim(tmp_path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    rows = [20, 220, 20, 220, 20, 220, 20, 220]
    _save_rows(first, rows)
    _save_rows(second, rows)
    second.write_bytes(second.read_bytes() + b"periodic-metadata")

    artifact = _call_builder(tmp_path, records=[{"image_path": first}, {"image_path": second}])

    assert [segment["accepted"] for segment in artifact["segments"]] == [True, True]
    assert artifact["overlap_evidence"][0]["overlap_pixels"] == 0
    with Image.open(artifact["composite_path"]) as composite:
        assert composite.height == 16


def test_one_matching_row_is_insufficient_overlap_evidence(tmp_path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    _save_rows(first, [11, 43, 79, 103, 151, 197])
    _save_rows(second, [197, 3, 31, 59, 89, 127])

    artifact = _build(tmp_path, [{"image_path": first}, {"image_path": second}])

    assert artifact["overlap_evidence"][0]["overlap_pixels"] == 0
    with Image.open(artifact["composite_path"]) as composite:
        assert composite.height == 12


def test_raw_sha_not_decoded_rgb_pixels_controls_exact_duplicate_detection(tmp_path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    Image.new("RGBA", (10, 6), (20, 40, 60, 255)).save(first)
    Image.new("RGBA", (10, 6), (20, 40, 60, 0)).save(second)

    artifact = _build(tmp_path, [{"image_path": first}, {"image_path": second}])

    assert artifact["segments"][0]["sha256"] != artifact["segments"][1]["sha256"]
    assert [segment["accepted"] for segment in artifact["segments"]] == [True, True]


def test_rejects_any_existing_output_directory_without_touching_it(tmp_path) -> None:
    segment = tmp_path / "segment.png"
    _save_rows(segment, [11, 43, 79, 103, 151, 197])
    output_dir = tmp_path / "artifact"
    output_dir.mkdir()
    sentinel = output_dir / "sentinel.txt"
    sentinel.write_bytes(b"existing directory")

    with pytest.raises(ScopedCaptureCompositionError, match="must be new"):
        _call_builder(tmp_path, records=[{"image_path": segment}], output_dir=output_dir)

    assert sentinel.read_bytes() == b"existing directory"


@pytest.mark.parametrize("invalid_value", [float("nan"), float("inf"), -float("inf")])
def test_rejects_non_finite_json_values_before_creating_artifacts(tmp_path, invalid_value: float) -> None:
    segment = tmp_path / "segment.png"
    _save_rows(segment, [11, 43, 79, 103, 151, 197])
    output_dir = tmp_path / "artifact"

    with pytest.raises(ScopedCaptureError):
        _call_builder(tmp_path, records=[{"image_path": segment, "scroll_effect": {"score": invalid_value}}], output_dir=output_dir)

    assert not output_dir.exists()


def test_rejects_unserializable_roi_before_creating_any_artifact(tmp_path) -> None:
    segment = tmp_path / "segment.png"
    _save_rows(segment, [11, 43, 79, 103, 151, 197])
    output_dir = tmp_path / "artifact"

    with pytest.raises(ScopedCaptureError):
        _call_builder(tmp_path, records=[{"image_path": segment}], roi={**ROI, "extra": {"not-json"}}, output_dir=output_dir)

    assert not output_dir.exists()


@pytest.mark.parametrize(
    ("records", "roi", "viewport", "stop_reason"),
    [
        ([], ROI, VIEWPORT, "reached_bottom"),
        ([{}], ROI, VIEWPORT, "reached_bottom"),
        (None, {"x": 0, "y": 0, "width": True, "height": 6}, VIEWPORT, "reached_bottom"),
        (None, {"x": 8, "y": 0, "width": 3, "height": 6}, VIEWPORT, "reached_bottom"),
        (None, ROI, {"width": True, "height": 6}, "reached_bottom"),
        (None, ROI, VIEWPORT, "unknown_stop_reason"),
    ],
)
def test_rejects_input_contract_violations_before_creating_artifacts(tmp_path, records, roi, viewport, stop_reason: str) -> None:
    segment = tmp_path / "segment.png"
    _save_rows(segment, [11, 43, 79, 103, 151, 197])
    actual_records = [{"image_path": segment}] if records is None else records
    output_dir = tmp_path / "artifact"

    with pytest.raises(ScopedCaptureError):
        _call_builder(tmp_path, records=actual_records, roi=roi, viewport=viewport, stop_reason=stop_reason, output_dir=output_dir)

    assert not output_dir.exists()


def test_manifest_uses_stable_absolute_paths_lf_and_unescaped_utf8(tmp_path) -> None:
    segment = tmp_path / "segment.png"
    _save_rows(segment, [11, 43, 79, 103, 151, 197])

    artifact = _call_builder(tmp_path, records=[{"image_path": segment, "capture_id": "\u6d4b\u8bd5"}])

    composite_path = Path(artifact["composite_path"])
    manifest_path = Path(artifact["manifest_path"])
    manifest_bytes = manifest_path.read_bytes()
    assert composite_path.name == "scoped_capture_composite.png"
    assert manifest_path.name == "scoped_capture_manifest.json"
    assert composite_path.is_absolute() and manifest_path.is_absolute()
    assert b"\r\n" not in manifest_bytes
    assert "\u6d4b\u8bd5".encode("utf-8") in manifest_bytes


def test_optional_segment_fields_are_present_when_omitted(tmp_path) -> None:
    segment = tmp_path / "segment.png"
    _save_rows(segment, [11, 43, 79, 103, 151, 197])

    artifact = _build(tmp_path, [{"image_path": segment}])

    entry = artifact["segments"][0]
    assert entry["capture_id"] is None
    assert entry["scroll_trace_path"] is None
    assert entry["scroll_effect"] is None



def test_publish_failure_leaves_no_output_directory_or_staging_directory(tmp_path, monkeypatch) -> None:
    segment = tmp_path / "segment.png"
    _save_rows(segment, [11, 43, 79, 103, 151, 197])
    output_dir = tmp_path / "artifact"
    original_rename = scoped_capture.os.rename

    def fail_directory_publish(source, destination) -> None:
        if Path(destination) == output_dir:
            raise OSError("simulated directory publish failure")
        original_rename(source, destination)

    monkeypatch.setattr(scoped_capture.os, "rename", fail_directory_publish)

    with pytest.raises(ScopedCaptureCompositionError, match="failed to publish"):
        _call_builder(tmp_path, records=[{"image_path": segment}], output_dir=output_dir)

    assert not output_dir.exists()
    assert not list(tmp_path.glob(".scoped_capture_staging_*"))



def _save_rgb_rows(path: Path, width: int, rows: list[int]) -> None:
    image = Image.new("L", (width, len(rows)))
    image.putdata([(value + column * 13) % 256 for value in rows for column in range(width)])
    image.convert("RGB").save(path)


def test_size_mismatch_never_crops_the_larger_segment(tmp_path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    _save_rgb_rows(first, 10, [11, 43, 79, 103, 151, 197, 23, 59, 97, 131, 173, 211])
    _save_rgb_rows(second, 20, [23, 59, 97, 131, 173, 211, 29, 67, 113, 149, 191, 227])

    artifact = _call_builder(tmp_path, records=[{"image_path": first}, {"image_path": second}], roi={"x": 0, "y": 0, "width": 20, "height": 12}, viewport={"width": 20, "height": 12})

    assert artifact["overlap_evidence"][0]["overlap_pixels"] == 0
    with Image.open(artifact["composite_path"]) as composite:
        assert composite.size == (20, 24)


def test_full_width_verification_rejects_a_1000_pixel_sampling_blind_spot(tmp_path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    width = 1000
    height = 20
    first_image = Image.new("L", (width, height))
    second_image = Image.new("L", (width, height))
    first_pixels = [(column * 17 + row * 29) % 256 for row in range(height) for column in range(width)]
    second_pixels = [255 - value for value in first_pixels]
    for start, end in ((0, 51), (237, 288), (474, 525), (711, 762), (949, 1000)):
        for row in range(height):
            second_pixels[row * width + start:row * width + end] = first_pixels[row * width + start:row * width + end]
    first_image.putdata(first_pixels)
    second_image.putdata(second_pixels)
    first_image.convert("RGB").save(first)
    second_image.convert("RGB").save(second)

    artifact = _call_builder(tmp_path, records=[{"image_path": first}, {"image_path": second}], roi={"x": 0, "y": 0, "width": width, "height": height}, viewport={"width": width, "height": height})

    assert artifact["overlap_evidence"][0]["overlap_pixels"] == 0
    with Image.open(artifact["composite_path"]) as composite:
        assert composite.height == 40


def test_one_sided_blank_overlap_evidence_is_rejected(tmp_path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    _save_rgb_rows(first, 20, [15, 40, 75, 110, 145, 180, 120, 124, 128, 132, 136, 140])
    Image.new("L", (20, 12), 128).convert("RGB").save(second)

    artifact = _call_builder(tmp_path, records=[{"image_path": first}, {"image_path": second}], roi={"x": 0, "y": 0, "width": 20, "height": 12}, viewport={"width": 20, "height": 12})

    assert artifact["overlap_evidence"][0]["overlap_pixels"] == 0


def test_five_row_periodic_boundary_is_insufficient_overlap_proof(tmp_path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    _save_rgb_rows(first, 20, [11, 33, 57, 83, 111, 139, 20, 80, 140, 200, 20, 61])
    _save_rgb_rows(second, 20, [80, 140, 200, 20, 61, 170, 190, 210, 230, 250, 30, 50])

    artifact = _call_builder(tmp_path, records=[{"image_path": first}, {"image_path": second}], roi={"x": 0, "y": 0, "width": 20, "height": 12}, viewport={"width": 20, "height": 12})

    assert artifact["overlap_evidence"][0]["overlap_pixels"] == 0


def test_surrogate_string_is_rejected_before_output_directory_exists(tmp_path) -> None:
    segment = tmp_path / "segment.png"
    _save_rows(segment, [11, 43, 79, 103, 151, 197])
    output_dir = tmp_path / "artifact"

    with pytest.raises(ScopedCaptureError):
        _call_builder(tmp_path, records=[{"image_path": segment, "capture_id": "\ud800"}], output_dir=output_dir)

    assert not output_dir.exists()


def test_concurrent_output_directory_creation_preserves_the_other_publisher(tmp_path, monkeypatch) -> None:
    segment = tmp_path / "segment.png"
    _save_rows(segment, [11, 43, 79, 103, 151, 197])
    output_dir = tmp_path / "artifact"
    original_rename = scoped_capture.os.rename

    def create_competing_directory(source, destination) -> None:
        if Path(destination) == output_dir:
            output_dir.mkdir()
            (output_dir / "other-publisher.txt").write_bytes(b"do not touch")
            raise FileExistsError(destination)
        original_rename(source, destination)

    monkeypatch.setattr(scoped_capture.os, "rename", create_competing_directory)

    with pytest.raises(ScopedCaptureCompositionError, match="failed to publish"):
        _call_builder(tmp_path, records=[{"image_path": segment}], output_dir=output_dir)

    assert (output_dir / "other-publisher.txt").read_bytes() == b"do not touch"
    assert not list(tmp_path.glob(".scoped_capture_staging_*"))


def test_directory_cleanup_failure_is_reported_without_final_artifacts(tmp_path, monkeypatch) -> None:
    segment = tmp_path / "segment.png"
    _save_rows(segment, [11, 43, 79, 103, 151, 197])
    output_dir = tmp_path / "artifact"
    original_rename = scoped_capture.os.rename
    original_rmtree = scoped_capture.shutil.rmtree

    def fail_directory_publish(source, destination) -> None:
        if Path(destination) == output_dir:
            raise OSError("publish failure")
        original_rename(source, destination)

    def fail_cleanup(path, *args, **kwargs) -> None:
        raise RuntimeError("cleanup failure")

    monkeypatch.setattr(scoped_capture.os, "rename", fail_directory_publish)
    monkeypatch.setattr(scoped_capture.shutil, "rmtree", fail_cleanup)

    with pytest.raises(ScopedCaptureCompositionError, match="cleanup"):
        _call_builder(tmp_path, records=[{"image_path": segment}], output_dir=output_dir)

    assert not output_dir.exists()
    monkeypatch.setattr(scoped_capture.shutil, "rmtree", original_rmtree)
    for staging_dir in tmp_path.glob(".scoped_capture_staging_*"):
        original_rmtree(staging_dir)


def test_segment_is_decoded_from_the_same_bytes_used_for_its_sha(tmp_path, monkeypatch) -> None:
    segment = tmp_path / "segment.png"
    _save_rows(segment, [11, 43, 79, 103, 151, 197])
    original_sha = hashlib.sha256(segment.read_bytes()).hexdigest()
    original_open = scoped_capture.Image.open

    def mutate_path_before_open(source, *args, **kwargs):
        if isinstance(source, (str, Path)) and Path(source) == segment:
            Image.new("RGB", (20, 6), "black").save(segment)
        return original_open(source, *args, **kwargs)

    monkeypatch.setattr(scoped_capture.Image, "open", mutate_path_before_open)

    artifact = _build(tmp_path, [{"image_path": segment}])

    assert artifact["segments"][0]["sha256"] == original_sha
    assert artifact["segments"][0]["width"] == 10


def test_non_string_stop_reason_raises_scoped_capture_error_before_output(tmp_path) -> None:
    segment = tmp_path / "segment.png"
    _save_rows(segment, [11, 43, 79, 103, 151, 197])
    output_dir = tmp_path / "artifact"

    with pytest.raises(ScopedCaptureError):
        _call_builder(tmp_path, records=[{"image_path": segment}], stop_reason=[], output_dir=output_dir)

    assert not output_dir.exists()



def test_single_full_width_pixel_difference_forces_full_append(tmp_path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    _save_rgb_rows(first, 20, [11, 43, 79, 103, 151, 197, 23, 59, 97, 131, 173, 211])
    _save_rgb_rows(second, 20, [23, 59, 97, 131, 173, 211, 29, 67, 113, 149, 191, 227])
    with Image.open(second) as source:
        changed = source.copy()
    changed.putpixel((0, 0), (255, 255, 255))
    changed.save(second)

    artifact = _call_builder(tmp_path, records=[{"image_path": first}, {"image_path": second}], roi={"x": 0, "y": 0, "width": 20, "height": 12}, viewport={"width": 20, "height": 12})

    assert artifact["overlap_evidence"][0]["overlap_pixels"] == 0
    assert artifact["overlap_evidence"][0]["confidence"] == "none"
    with Image.open(artifact["composite_path"]) as composite:
        assert composite.height == 24
        assert composite.getpixel((0, 12)) == (255, 255, 255)



def test_chroma_one_pixel_change_with_same_grayscale_forces_full_append(tmp_path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first_rows = [(index * 37 + 11) % 251 for index in range(32)]
    second_rows = first_rows[-16:] + [(index * 53 + 19) % 251 for index in range(16)]
    _save_rgb_rows(first, 20, first_rows)
    _save_rgb_rows(second, 20, second_rows)
    with Image.open(second) as source:
        changed = source.copy()
    changed.putpixel((0, 0), (95, 101, 104))
    changed.save(second)

    artifact = _call_builder(tmp_path, records=[{"image_path": first}, {"image_path": second}], roi={"x": 0, "y": 0, "width": 20, "height": 32}, viewport={"width": 20, "height": 32})

    assert artifact["overlap_evidence"][0]["overlap_pixels"] == 0
    with Image.open(artifact["composite_path"]) as composite:
        assert composite.height == 64
        assert composite.getpixel((0, 32)) == (95, 101, 104)


def test_local_period_six_rows_is_below_the_overlap_proof_threshold(tmp_path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    periodic = [20, 80, 140, 200, 20, 80]
    _save_rgb_rows(first, 20, [((index * 37) + 11) % 251 for index in range(26)] + periodic)
    _save_rgb_rows(second, 20, periodic + [((index * 53) + 19) % 251 for index in range(26)])

    artifact = _call_builder(tmp_path, records=[{"image_path": first}, {"image_path": second}], roi={"x": 0, "y": 0, "width": 20, "height": 32}, viewport={"width": 20, "height": 32})

    assert artifact["overlap_evidence"][0]["overlap_pixels"] == 0


def test_low_information_one_pixel_boundary_is_not_overlap_evidence(tmp_path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first_image = Image.new("RGB", (20, 32), "white")
    second_image = Image.new("RGB", (20, 32), "white")
    first_image.putpixel((0, 16), (0, 0, 0))
    second_image.putpixel((0, 0), (0, 0, 0))
    first_image.save(first)
    second_image.save(second)

    artifact = _call_builder(tmp_path, records=[{"image_path": first}, {"image_path": second}], roi={"x": 0, "y": 0, "width": 20, "height": 32}, viewport={"width": 20, "height": 32})

    assert artifact["overlap_evidence"][0]["overlap_pixels"] == 0
    with Image.open(artifact["composite_path"]) as composite:
        assert composite.height == 64


def test_cyclic_manifest_value_raises_scoped_capture_error_before_output(tmp_path) -> None:
    segment = tmp_path / "segment.png"
    _save_rows(segment, [11, 43, 79, 103, 151, 197])
    cyclic: list[object] = []
    cyclic.append(cyclic)
    output_dir = tmp_path / "artifact"

    with pytest.raises(ScopedCaptureError, match="cyclic"):
        _call_builder(tmp_path, records=[{"image_path": segment, "scroll_effect": cyclic}], output_dir=output_dir)

    assert not output_dir.exists()


@pytest.mark.parametrize("pixel_limit", [1, 40])
def test_decompression_bomb_rejection_is_a_segment_scoped_capture_error(tmp_path, monkeypatch, pixel_limit: int) -> None:
    segment = tmp_path / "segment.png"
    _save_rows(segment, [11, 43, 79, 103, 151, 197])
    output_dir = tmp_path / "artifact"
    monkeypatch.setattr(scoped_capture.Image, "MAX_IMAGE_PIXELS", pixel_limit)

    with pytest.raises(ScopedCaptureError) as exc_info:
        _call_builder(tmp_path, records=[{"image_path": segment}], output_dir=output_dir)

    assert "segment 0" in str(exc_info.value)
    assert str(segment) in str(exc_info.value)
    assert not output_dir.exists()



def test_exact_overlap_with_twenty_percent_informative_tiles_stitches_page_whitespace(tmp_path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first_image = Image.new("RGB", (80, 32), "white")
    second_image = Image.new("RGB", (80, 32), "white")
    for row in range(16):
        for column in range(16):
            pixel = ((column * 17 + row * 23) % 256,) * 3
            first_image.putpixel((column, row + 16), pixel)
            second_image.putpixel((column, row), pixel)
    first_image.save(first)
    second_image.save(second)

    artifact = _call_builder(tmp_path, records=[{"image_path": first}, {"image_path": second}], roi={"x": 0, "y": 0, "width": 80, "height": 32}, viewport={"width": 80, "height": 32})

    assert artifact["overlap_evidence"][0]["overlap_pixels"] == 16
    assert artifact["overlap_evidence"][0]["confidence"] == "high"
    with Image.open(artifact["composite_path"]) as composite:
        assert composite.size == (80, 48)


def test_real_size_overlap_composition_finishes_within_loose_budget(tmp_path) -> None:
    width = 2048
    height = 1046
    overlap = 384
    source_height = (height * 2) - overlap
    red = Image.frombytes(
        "L",
        (width, source_height),
        b"".join(bytes([row & 0xFF]) * width for row in range(source_height)),
    )
    green = Image.frombytes(
        "L",
        (width, source_height),
        b"".join(bytes([(row >> 8) & 0xFF]) * width for row in range(source_height)),
    )
    blue_row = bytes(
        (column * 17 + column // 251 * 31) % 256
        for column in range(width)
    )
    blue = Image.frombytes("L", (width, source_height), blue_row * source_height)
    source = Image.merge("RGB", (red, green, blue))
    first = tmp_path / "first-large.png"
    second = tmp_path / "second-large.png"
    source.crop((0, 0, width, height)).save(first)
    source.crop((0, height - overlap, width, source_height)).save(second)

    started_at = time.perf_counter()
    artifact = _call_builder(
        tmp_path,
        records=[{"image_path": first}, {"image_path": second}],
        roi={"x": 0, "y": 0, "width": width, "height": height},
        viewport={"width": width, "height": height},
    )
    elapsed_seconds = time.perf_counter() - started_at

    assert elapsed_seconds < 20.0
    assert artifact["overlap_evidence"][0]["overlap_pixels"] == overlap
    assert artifact["overlap_evidence"][0]["confidence"] == "high"
    assert artifact["artifact_is_authorization"] is False
    with Image.open(artifact["composite_path"]) as composite:
        assert composite.size == (width, source_height)


def test_output_directory_resolution_failure_is_a_composition_error(monkeypatch) -> None:
    class FailingOutputPath:
        def expanduser(self):
            return self

        def resolve(self):
            raise OSError("output resolution failed")

    monkeypatch.setattr(scoped_capture, "Path", lambda value: FailingOutputPath())

    with pytest.raises(ScopedCaptureCompositionError, match="output_dir"):
        scoped_capture._resolve_output_dir("server-generated-output")


def test_stitch_runtime_failure_is_a_composition_error(tmp_path, monkeypatch) -> None:
    segment = tmp_path / "segment.png"
    _save_rows(segment, [11, 43, 79, 103, 151, 197])

    def fail_stitch(*args, **kwargs):
        raise RuntimeError("stitch runtime failure")

    monkeypatch.setattr(scoped_capture, "_stitch_accepted_segments", fail_stitch)

    with pytest.raises(ScopedCaptureCompositionError, match="compose"):
        _call_builder(tmp_path, records=[{"image_path": segment}])

    assert not (tmp_path / "artifact").exists()


def test_output_directory_resolution_runtime_failure_is_a_composition_error(monkeypatch) -> None:
    class FailingOutputPath:
        def expanduser(self):
            return self

        def resolve(self):
            raise RuntimeError("output resolution runtime failure")

    monkeypatch.setattr(scoped_capture, "Path", lambda value: FailingOutputPath())

    with pytest.raises(ScopedCaptureCompositionError, match="output_dir"):
        scoped_capture._resolve_output_dir("server-generated-output")


def test_publish_exists_runtime_failure_is_a_composition_error() -> None:
    class FailingArtifactDirectory:
        def exists(self):
            raise RuntimeError("output exists runtime failure")

    with pytest.raises(ScopedCaptureCompositionError, match="publish"):
        scoped_capture._publish_artifact_directory(
            artifact_dir=FailingArtifactDirectory(),
            composite=Image.new("RGB", (1, 1)),
            manifest_bytes=b"{}",
        )
