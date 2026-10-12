"""原生字段事实未变时，光标和遮挡元数据不重复否决已认证语义。"""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256

from PIL import Image, ImageDraw
import pytest

from app.execution import visual_field_proof as m
from tests.test_visual_field_proof import scene, assess, capture, controller_scene, focus_snapshot, FIELD
from tests.test_visual_field_freshness import native_read


def pair(tmp_path, fault=None):
    before = Image.new("RGBA", (180, 90), "white")
    after = before.copy()
    box = (60, 18, 60, 37)
    if fault == "wide": box = (60, 18, 62, 37)
    if fault == "short": box = (60, 18, 60, 24)
    if fault == "tall": box = (60, 10, 60, 50)
    if fault == "edge": box = (10, 18, 10, 37)
    ImageDraw.Draw(after).rectangle(box, fill="black")
    if fault == "hole": after.putpixel((60, 25), (255, 255, 255, 255))
    if fault == "multiple": after.putpixel((62, 25), (0, 0, 0, 255))
    if fault == "outside": after.putpixel((160, 70), (0, 0, 0, 255))
    if fault == "old_color": before.putpixel((60, 25), (255, 0, 0, 255))
    if fault == "new_color": after.putpixel((60, 25), (255, 0, 0, 255))
    if fault == "alpha": ImageDraw.Draw(after).rectangle(box, fill=(255, 255, 255, 0))
    frames = []
    for name, image in (("before", before), ("after", after)):
        path = tmp_path / (name + ".png")
        image.save(path)
        frames.append({"image_path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()})
    baseline = {"selection": [3, 3], "identity": {"control_bbox": [10, 10, 140, 40]}}
    if fault == "selection": baseline["selection"] = [0, 3]
    if fault == "missing_selection": baseline["selection"] = None
    if fault == "native_height": baseline["identity"]["control_bbox"] = [10, 18, 140, 19]
    if fault == "native_outside": baseline["identity"]["control_bbox"] = [70, 10, 80, 40]
    changed = m._field_difference(*frames, FIELD)
    return frames, changed, baseline


@pytest.mark.parametrize("reverse", [False, True])
def test_exact_native_caret_rectangle_accepts_blink_in_either_direction(tmp_path, reverse):
    frames, changed, baseline = pair(tmp_path)
    assert m._native_bound_caret_change(*frames[::(-1 if reverse else 1)], changed, baseline)


@pytest.mark.parametrize("fault", ["wide", "short", "tall", "edge", "hole", "multiple", "outside",
    "old_color", "new_color", "alpha", "selection", "missing_selection", "native_height", "native_outside"])
def test_other_changes_never_receive_local_caret_exemption(tmp_path, fault):
    frames, changed, baseline = pair(tmp_path, fault)
    assert not m._native_bound_caret_change(*frames, changed, baseline)


@pytest.mark.parametrize("fixed_mask", [False, True])
def test_authenticated_collapsed_field_caret_needs_no_second_decision(scene, monkeypatch, fixed_mask):
    s = scene
    visibility = {"allowed": True, "masked": fixed_mask, "coordinate_space": "window",
        "occluded_regions": [{"x": 160, "y": 60, "width": 5, "height": 5}] if fixed_mask else []}
    s.focus["observation"]["capture"]["capture_visibility"] = deepcopy(visibility)
    baseline = focus_snapshot(s, selection=(3, 3))
    proof = assess(s, focus_snapshot=baseline)
    controller, events, _ = controller_scene(s, monkeypatch)
    native_read(s, monkeypatch, baseline=baseline)
    frame = capture(s.root, "local-caret")
    frame["capture_visibility"] = deepcopy(visibility)
    with Image.open(frame["image_path"]) as image:
        image = image.copy()
    ImageDraw.Draw(image).rectangle((60, 18, 60, 37), fill="black")
    image.save(frame["image_path"])
    frame["sha256"] = sha256(__import__("pathlib").Path(frame["image_path"]).read_bytes()).hexdigest()
    monkeypatch.setattr(s.module, "capture_visual_field_frame", lambda *args: deepcopy(frame))
    from app.core.input_controller import window_manager
    assert m.revalidate_visual_field(proof, window_manager)["capture_id"]
    assert len(s.requests) == 1 and events == []
    frame["capture_visibility"] = {"allowed": True, "masked": True, "coordinate_space": "window",
        "occluded_regions": [{"x": 165, "y": 60, "width": 5, "height": 5}]}
    assert m.revalidate_visual_field(proof, window_manager)["capture_id"]
    frame["capture_visibility"]["occluded_regions"][0].update(x=60, y=18)
    assert m.revalidate_visual_field(proof, window_manager)["capture_id"]
    assert len(s.requests) == 1 and events == []
