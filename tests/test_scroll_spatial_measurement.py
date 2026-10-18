from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from app.gate import scroll_evidence
from app.gate.scroll import build_scroll_effect_validation


BBOX = {"x": 0, "y": 0, "width": 100, "height": 100}


def snapshot(tmp_path, name, time_ns, changes=()):
    image = Image.new("RGB", (200, 100), "white")
    draw = ImageDraw.Draw(image)
    for box in changes:
        draw.rectangle(box, fill="black")
    path = tmp_path / f"{name}.png"
    image.save(path)
    return {
        "contract_version": "scroll_capture_snapshot_v1", "captured": True,
        "capture_status": "observed", "capture_id": name, "capture_clock_id": "test-clock",
        "capture_started_ns": time_ns, "captured_at_ns": time_ns + 1,
        "image_path": str(path), "image_sha256": sha256(path.read_bytes()).hexdigest(),
        "viewport_size": {"width": 200, "height": 100}, "roi": None,
        "window_handle": 42, "window_rect": {"x": 10, "y": 10, "width": 200, "height": 100},
        "native_identity": {
            "contract_version": "windows_native_identity_observation_v1",
            "provider": "windows_native_identity", "status": "observed",
            "target_window_handle": 42, "process_id": 12,
            "process_create_time": 123.0, "executable_path": "c:\\fixture\\app.exe",
        },
    }


def measure(before, after, bbox=BBOX):
    return scroll_evidence.measure_scroll_spatial_evidence(
        before=before, after=after, target_bbox=bbox, target_container_id="pane",
    )


@pytest.mark.parametrize("changes,target_changed,outside_changed,status", [
    ([(10, 10, 29, 29)], True, False, "target_visual_change"),
    ([(120, 10, 139, 29)], False, True, "non_target_visual_change"),
    ([(10, 10, 29, 29), (120, 10, 139, 29)], True, True, "non_target_visual_change"),
    ([], False, False, "no_visual_change"),
    ([(10, 10, 10, 10)], None, False, "unknown"),
    ([(120, 10, 120, 10)], False, None, "unknown"),
])
def test_region_pixels_are_measured_without_claiming_scroll_semantics(tmp_path, changes, target_changed, outside_changed, status):
    before, after = snapshot(tmp_path, "before", 10), snapshot(tmp_path, "after", 20, changes)
    result = measure(before, after)
    assert result["available"] is True
    assert result["status"] == status
    assert result["target_changed"] is target_changed
    assert result["non_target_changed"] is outside_changed
    assert result["target_metrics"]["pixel_count"] == 10000
    assert result["non_target_metrics"]["pixel_count"] == 10000
    assert result["target_metrics"]["changed_pixel_count"] == (400 if target_changed else (1 if changes and changes[0][0] == 10 else 0))
    assert result["lineage"]["before"]["image_sha256"] == before["image_sha256"]
    assert result["direction_verified"] is None
    assert result["boundary_reached"] is None
    assert result["scroll_movement_verified"] is None
    assert result["should_retry"] is False


@pytest.mark.parametrize("mutation,reason", [
    ({"capture_id": "before"}, "capture_reused"),
    ({"capture_clock_id": "other-clock"}, "capture_clock_mismatch"),
    ({"capture_started_ns": 9}, "capture_order_invalid"),
    ({"captured_at_ns": 1}, "capture_interval_invalid"),
    ({"image_sha256": "0" * 64}, "image_hash_mismatch"),
    ({"roi": BBOX}, "full_window_capture_required"),
    ({"capture_status": "unavailable"}, "capture_unavailable"),
    ({"viewport_size": {"width": 201, "height": 100}}, "viewport_mismatch"),
    ({"window_rect": {"x": 11, "y": 10, "width": 200, "height": 100}}, "window_geometry_mismatch"),
    ({"window_handle": 43}, "native_identity_invalid"),
])
def test_invalid_capture_lineage_never_produces_scope_success(tmp_path, mutation, reason):
    before, after = snapshot(tmp_path, "before", 10), snapshot(tmp_path, "after", 20)
    after.update(mutation)
    result = measure(before, after)
    assert result["available"] is False
    assert result["status"] == "unknown"
    assert result["reason"] == reason
    assert result["wrong_scope_detected"] is None


@pytest.mark.parametrize("field,value", [("process_id", 13), ("process_create_time", 124.0), ("executable_path", "c:\\other\\app.exe")])
def test_process_instance_change_rejects_even_same_window_handle(tmp_path, field, value):
    before, after = snapshot(tmp_path, "before", 10), snapshot(tmp_path, "after", 20)
    after["native_identity"][field] = value
    assert measure(before, after)["reason"] == "native_identity_mismatch"


@pytest.mark.parametrize("bbox", [None, {"x": -1, "y": 0, "width": 100, "height": 100}, {"x": 0, "y": 0, "width": 201, "height": 100}, {"x": 0, "y": 0, "width": 0, "height": 100}])
def test_missing_or_invalid_bbox_is_not_clamped_or_replaced(tmp_path, bbox):
    assert measure(snapshot(tmp_path, "before", 10), snapshot(tmp_path, "after", 20), bbox)["reason"] == "target_bbox_invalid"


def test_missing_frame_or_modified_image_cannot_be_used(tmp_path):
    before, after = snapshot(tmp_path, "before", 10), snapshot(tmp_path, "after", 20)
    assert measure(None, after)["reason"] == "capture_missing"
    Image.new("RGB", (199, 100)).save(after["image_path"])
    from pathlib import Path
    after["image_sha256"] = sha256(Path(after["image_path"]).read_bytes()).hexdigest()
    assert measure(before, after)["reason"] == "image_dimensions_mismatch"


def test_missing_image_is_explicit_and_inputs_are_not_mutated(tmp_path):
    before, after = snapshot(tmp_path, "before", 10), snapshot(tmp_path, "after", 20)
    after["image_path"] = str(tmp_path / "missing.png")
    original = deepcopy(after)
    assert measure(before, after)["reason"] == "image_read_failed"
    assert after == original


def test_existing_effect_facade_measures_frames_instead_of_trusting_global_verified(tmp_path):
    before, after = snapshot(tmp_path, "before", 10), snapshot(tmp_path, "after", 20, [(10, 10, 29, 29)])
    result = build_scroll_effect_validation(
        request=SimpleNamespace(scroll_scope="container", target_container_id="pane", container_bbox=BBOX),
        post_scroll_verification={"before": before, "after": after, "verified": True},
        target_container={"container_id": "pane", "bbox": BBOX},
    )
    assert result["status"] == "target_visual_change"
    assert result["target_container_content_changed"] is True
    assert result["non_target_panes_stable"] is True
    assert result["scroll_movement_verified"] is None
    assert result["spatial_evidence"]["target_metrics"]["changed_pixel_count"] == 400
