"""新合成 PNG 独立验证完整性、目标与上下文新鲜度，不接触桌面。"""
from copy import deepcopy
from hashlib import sha256
from importlib import import_module
from pathlib import Path
import json
import subprocess
import sys

from PIL import Image, ImageDraw
from PIL.PngImagePlugin import PngInfo
import pytest


IDENTITY = {"handle": 100, "process_id": 200, "process_create_time": 1234.5}
SIZE = {"width": 120, "height": 80}
TARGET = {"x": 10, "y": 30, "w": 35, "h": 15}
ANCHOR = {"x": 5, "y": 5, "w": 55, "h": 15}


def frame(tmp_path, name, image):
    path = tmp_path / (name + ".png")
    image.save(path)
    return {"capture_id": name, "image_path": str(path), "sha256": sha256(path.read_bytes()).hexdigest(),
        "window_identity": dict(IDENTITY), "role": "before", "image_size": dict(SIZE),
        "window_rect": [20, 30, 140, 110]}


@pytest.fixture
def scene(tmp_path):
    image = Image.new("RGB", (120, 80), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 30, 44, 44), fill="blue")
    draw.text((8, 7), "Search", fill="black")
    before = frame(tmp_path, "before", image)
    current = frame(tmp_path, "current", image)
    candidate = {"candidate_id": "target", "capture_id": "before", "viewport_size": dict(SIZE),
        "bbox": dict(TARGET), "click_point": {"x": 20, "y": 35}, "source": "luna"}
    return {"before": before, "current": current, "candidate": candidate,
        "context_regions": [{"kind": "anchor", "bbox": dict(ANCHOR)}]}


def check(scene):
    return import_module("app.execution.target_freshness").check_target_freshness(**scene)


def repaint(scene, box, color):
    current = scene["current"]
    with Image.open(current["image_path"]) as source:
        image = source.copy()
    ImageDraw.Draw(image).rectangle(box, fill=color)
    image.save(current["image_path"])
    current["sha256"] = sha256(Path(current["image_path"]).read_bytes()).hexdigest()


def test_unchanged_target_and_context_are_valid(scene):
    assert check(scene)["status"] == "valid"


def test_distinct_png_artifact_hashes_with_identical_pixels_are_valid(scene):
    current = scene["current"]
    with Image.open(current["image_path"]) as image:
        pixels = image.copy()
    note = PngInfo()
    note.add_text("capture", "new lossless encoding")
    pixels.save(current["image_path"], pnginfo=note, compress_level=9)
    current["sha256"] = sha256(Path(current["image_path"]).read_bytes()).hexdigest()
    assert current["sha256"] != scene["before"]["sha256"]
    result = check(scene)
    assert result["status"] == "valid"
    assert result["authorizes_action"] is False


def test_freshness_import_and_evaluation_attempt_zero_native_imports(scene):
    script = """
import importlib.abc, json, sys
class NoNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('win32', 'comtypes', 'pywinauto', 'app.core.screenshot',
                                'app.core.window_manager', 'app.core.input_controller')):
            raise AssertionError('native import attempted: ' + fullname)
sys.meta_path.insert(0, NoNative())
from app.execution.target_freshness import check_target_freshness
print(json.dumps(check_target_freshness(**json.loads(sys.argv[1]))))
"""
    completed = subprocess.run([sys.executable, "-B", "-X", "utf8", "-c", script, json.dumps(scene)],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, encoding="utf-8", timeout=15)
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == ""
    assert json.loads(completed.stdout)["status"] == "valid"


def test_target_move_invalidates_candidate(scene):
    repaint(scene, (10, 30, 44, 44), "white")
    repaint(scene, (55, 30, 89, 44), "blue")
    assert check(scene)["status"] == "changed"


def test_context_text_change_invalidates_candidate(scene):
    repaint(scene, (8, 7, 9, 8), "red")
    assert check(scene)["status"] == "changed"


def test_new_occlusion_invalidates_candidate(scene):
    repaint(scene, (18, 32, 24, 38), "black")
    assert check(scene)["status"] == "changed"


def test_modified_original_artifact_rejected(scene):
    Image.new("RGB", (120, 80), "red").save(scene["before"]["image_path"])
    assert check(scene)["status"] == "unknown"


def test_modified_current_artifact_rejected(scene):
    Image.new("RGB", (120, 80), "red").save(scene["current"]["image_path"])
    assert check(scene)["status"] == "unknown"


def test_unexplained_remote_change_is_not_assumed_irrelevant(scene):
    repaint(scene, (90, 55, 110, 70), "red")
    assert check(scene)["status"] == "unknown"


def test_untrusted_irrelevant_mask_not_accepted(scene):
    repaint(scene, (90, 55, 110, 70), "red")
    scene["context_regions"].append({"kind": "irrelevant_animation",
        "bbox": {"x": 85, "y": 50, "w": 30, "h": 25}, "verified": True})
    assert check(scene)["status"] == "unknown"


def test_new_native_mask_over_target_is_not_hidden_by_identical_pixels(scene):
    scene["current"]["capture_visibility"] = {"allowed": True, "masked": True,
        "coordinate_space": "window", "occluded_regions": [{"x": 10, "y": 30, "width": 35, "height": 15}]}
    assert check(scene)["status"] in {"changed", "unknown"}


@pytest.mark.parametrize("damage", ["missing_identity", "bad_birth", "missing_geometry", "cropped",
    "declared_size", "animated", "not_png", "missing_file", "one_pixel", "alpha_only"])
def test_invalid_evidence_or_even_small_protected_change_never_passes(scene, damage):
    current = scene["current"]
    if damage == "missing_identity":
        current.pop("window_identity")
    elif damage == "bad_birth":
        current["window_identity"]["process_create_time"] = float("nan")
    elif damage == "missing_geometry":
        current.pop("window_rect")
    elif damage == "cropped":
        current["roi"] = {"x": 10, "y": 30, "width": 35, "height": 15}
    elif damage == "declared_size":
        current["image_size"]["width"] += 1
    elif damage == "missing_file":
        current["image_path"] += ".missing"
    elif damage == "one_pixel":
        repaint(scene, (20, 35, 20, 35), (0, 0, 254))
    else:
        path = Path(current["image_path"])
        with Image.open(path) as image:
            changed = image.convert("RGBA")
        if damage == "alpha_only":
            changed.putpixel((20, 35), (0, 0, 255, 254))
            changed.save(path)
        elif damage == "animated":
            changed.save(path, save_all=True, append_images=[Image.new("RGBA", changed.size, "red")], duration=100)
        else:
            changed.convert("RGB").save(path, format="JPEG")
        current["sha256"] = sha256(path.read_bytes()).hexdigest()
    assert check(scene)["status"] in {"changed", "unknown"}


@pytest.mark.parametrize("field", ["handle", "process_id", "process_create_time"])
def test_window_birth_identity_change_invalidates_candidate(scene, field):
    scene["current"]["window_identity"][field] += 1
    assert check(scene)["status"] == "changed"


def test_window_geometry_change_invalidates_candidate(scene):
    scene["current"]["window_rect"] = [21, 30, 141, 110]
    assert check(scene)["status"] == "changed"


@pytest.mark.parametrize("damage", ["viewport", "capture", "point", "bbox", "missing_context", "invalid_context"])
def test_incomplete_or_mismatched_binding_is_unknown(scene, damage):
    if damage == "viewport":
        scene["candidate"]["viewport_size"]["width"] += 1
    elif damage == "capture":
        scene["candidate"]["capture_id"] = "other"
    elif damage == "point":
        scene["candidate"]["click_point"] = {"x": 95, "y": 65}
    elif damage == "bbox":
        scene["candidate"]["bbox"]["w"] = 0
    elif damage == "missing_context":
        scene["context_regions"] = []
    else:
        scene["context_regions"][0]["bbox"]["x"] = -1
    assert check(scene)["status"] == "unknown"


def test_inputs_are_not_mutated(scene):
    original = deepcopy(scene)
    check(scene)
    assert scene == original


def test_outside_pixel_changes_do_not_hide_changed_capture_masks(scene):
    repaint(scene, (90, 55, 110, 70), "red")
    scene["current"]["capture_visibility"] = {"allowed": True, "masked": True,
        "coordinate_space": "window", "occluded_regions": [{"x": 95, "y": 60, "width": 5, "height": 5}]}
    result = check(scene)
    assert result["status"] == "unknown"
    assert result["reason"] == "unexplained_outside_occlusion_change"
    assert result["uncovered_change_bbox"] == {"x": 90, "y": 55, "w": 21, "h": 16}


def _set_visibility(capture, regions):
    capture["capture_visibility"] = {"allowed": True, "masked": bool(regions),
        "coordinate_space": "window", "occluded_regions": regions}


@pytest.mark.parametrize("before_regions,current_regions,expected", [
    ([], [{"x": 80, "y": 50, "width": 10, "height": 10}], {"x": 80, "y": 50, "w": 10, "h": 10}),
    ([{"x": 80, "y": 50, "width": 10, "height": 10}], [], {"x": 80, "y": 50, "w": 10, "h": 10}),
    ([{"x": 80, "y": 50, "width": 10, "height": 10}],
     [{"x": 100, "y": 50, "width": 10, "height": 10}], {"x": 80, "y": 50, "w": 30, "h": 10}),
])
def test_outside_occlusion_changes_are_bounded_and_require_review(scene, before_regions, current_regions, expected):
    _set_visibility(scene["before"], before_regions)
    _set_visibility(scene["current"], current_regions)
    result = check(scene)
    assert result["status"] == "unknown"
    assert result["reason"] == "unexplained_outside_occlusion_change"
    assert result["uncovered_change_bbox"] == expected
    assert result["authorizes_action"] is False


@pytest.mark.parametrize("capture_key,region,reason", [
    ("before", {"x": 10, "y": 30, "width": 1, "height": 1}, "original_protected_region_occluded"),
    ("current", {"x": 10, "y": 30, "width": 1, "height": 1}, "protected_region_occluded"),
    ("before", {"x": 5, "y": 5, "width": 1, "height": 1}, "original_protected_region_occluded"),
    ("current", {"x": 5, "y": 5, "width": 1, "height": 1}, "protected_region_occluded"),
])
def test_original_or_current_protected_occlusion_never_enters_relevance_review(scene, capture_key, region, reason):
    _set_visibility(scene[capture_key], [region])
    result = check(scene)
    assert result["reason"] == reason
    assert result["status"] != "valid"
    assert result["uncovered_change_bbox"] is None
    assert result["authorizes_action"] is False


@pytest.mark.parametrize("damage", ["allowed", "space", "boolean_coordinate", "outside", "empty_mask"])
def test_invalid_occlusion_metadata_never_becomes_reviewable(scene, damage):
    _set_visibility(scene["current"], [{"x": 80, "y": 50, "width": 10, "height": 10}])
    visibility = scene["current"]["capture_visibility"]
    if damage == "allowed":
        visibility["allowed"] = False
    elif damage == "space":
        visibility["coordinate_space"] = "screen"
    elif damage == "boolean_coordinate":
        visibility["occluded_regions"][0]["x"] = True
    elif damage == "outside":
        visibility["occluded_regions"][0]["width"] = 100
    else:
        visibility["occluded_regions"] = []
    result = check(scene)
    assert result["reason"] == "evidence_invalid"
    assert result["uncovered_change_bbox"] is None
    assert result["authorizes_action"] is False


def test_disjoint_outside_occlusion_coverage_not_its_bounding_box_is_protected(scene):
    _set_visibility(scene["current"], [{"x": 0, "y": 0, "width": 2, "height": 2},
        {"x": 110, "y": 70, "width": 2, "height": 2}])
    result = check(scene)
    assert result["reason"] == "unexplained_outside_occlusion_change"
    assert result["uncovered_change_bbox"] == {"x": 0, "y": 0, "w": 112, "h": 72}
    assert result["authorizes_action"] is False
