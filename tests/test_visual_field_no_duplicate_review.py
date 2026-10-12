"""已认证字段的输入事实继续核对；像素表现不重复触发语义审核。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

from PIL import Image, ImageDraw
import pytest

from app.core import local_keyboard_target as keyboard
from tests.test_visual_field_proof import scene, assess, capture, controller_scene, focus_snapshot, TEXT
from tests.test_visual_field_freshness import native_read


@pytest.mark.parametrize("change", ["caret", "field", "outside", "edge_occlusion"])
def test_approved_field_visual_changes_do_not_request_another_decision(scene, monkeypatch, change):
    from app.core.input_controller import window_manager
    s = scene
    baseline = focus_snapshot(s, selection=(0, 0))
    proof = assess(s, focus_snapshot=baseline)
    controller_scene(s, monkeypatch)
    native_read(s, monkeypatch, baseline=baseline)
    frame = capture(s.root, "approved-current")
    with Image.open(frame["image_path"]) as source:
        image = source.copy()
    if change == "caret":
        ImageDraw.Draw(image).rectangle((60, 18, 60, 37), fill="black")
    elif change == "field":
        ImageDraw.Draw(image).rectangle((60, 18, 90, 37), fill="purple")
    elif change == "outside":
        ImageDraw.Draw(image).rectangle((160, 60, 175, 75), fill="black")
    else:
        frame["capture_visibility"] = {"allowed": True, "masked": True, "coordinate_space": "window",
            "occluded_regions": [{"x": 140, "y": 10, "width": 5, "height": 5}]}
    image.save(frame["image_path"])
    frame["sha256"] = sha256(Path(frame["image_path"]).read_bytes()).hexdigest()
    monkeypatch.setattr(s.module, "capture_visual_field_frame", lambda *args: deepcopy(frame))
    target = keyboard.issue_visual_keyboard_target(proof, "type_text", text=TEXT,
        freshness_reviewer=lambda *args: pytest.fail("approved field must not request another semantic review"))
    with keyboard.local_keyboard_target_scope(target):
        keyboard.claim_keyboard_target("type_text", {"text": TEXT, "x": 40, "y": 30, "clear_existing": True})
        target.verify(window_manager)
    assert len(s.requests) == 1


def test_approved_visual_only_field_does_not_capture_again_before_keyboard(scene, monkeypatch):
    from app.core.input_controller import window_manager
    s = scene
    target = keyboard.issue_visual_keyboard_target(assess(s), "type_text", text=TEXT)
    controller_scene(s, monkeypatch)
    monkeypatch.setattr(s.module, "capture_visual_field_frame",
        lambda *args: pytest.fail("no native fact or selection needs another capture"))
    with keyboard.local_keyboard_target_scope(target):
        keyboard.claim_keyboard_target("type_text", {"text": TEXT, "x": 40, "y": 30, "clear_existing": True})
        target.verify(window_manager)
    assert len(s.requests) == 1


def test_native_focus_loss_still_blocks_approved_field_without_redecision(scene, monkeypatch):
    from app.agent.windows_text_field_reader import TextFieldReadError
    from app.core.input_controller import window_manager
    s = scene
    proof = assess(s, focus_snapshot=focus_snapshot(s))
    controller_scene(s, monkeypatch)
    def lost_focus(*args):
        raise TextFieldReadError("text_field_target_not_focused")
    monkeypatch.setattr(s.module, "_read_bounded_text", lost_focus)
    target = keyboard.issue_visual_keyboard_target(proof, "type_text", text=TEXT,
        freshness_reviewer=lambda *args: pytest.fail("focus loss must not request semantic override"))
    with keyboard.local_keyboard_target_scope(target):
        keyboard.claim_keyboard_target("type_text", {"text": TEXT, "x": 40, "y": 30, "clear_existing": True})
        with pytest.raises(TextFieldReadError, match="not_focused"):
            target.verify(window_manager)
    assert len(s.requests) == 1
