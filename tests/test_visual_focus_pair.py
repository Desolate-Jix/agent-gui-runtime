"""初始焦点双帧只读补图，不启动桌面或模型。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from time import perf_counter_ns
from types import SimpleNamespace as NS

import pytest
from PIL import Image, ImageDraw

from tests.test_visual_field_proof import scene, FIELD, IDENTITY, NATIVE, capture, assess, executed_focus
from tests.test_visual_input_no_uia import visual_sequence


def prepare(scene, monkeypatch):
    s = scene
    executed_focus(s.focus)
    s.context.update(native_field_evidence=False, focus_observation_delay_ms=500)
    bound = NS(handle=10, process_id=20, is_active=True,
        rect=NS(left=0, top=0, right=180, bottom=90))
    manager = NS(get_bound_window=lambda: bound)
    events = []
    clock = [perf_counter_ns()]
    monkeypatch.setattr(s.module, "perf_counter_ns", lambda: clock[0])
    monkeypatch.setattr(s.module, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + int(seconds * 1e9)))
    monkeypatch.setattr("app.agent.native_identity.WindowsNativeIdentityReader.read_identity", lambda *args: deepcopy(NATIVE))
    def screenshot(self, **kwargs):
        events.append(kwargs)
        return {**capture(s.root, "focus-second", changed=True), "window_rect": [0, 0, 180, 90]}
    monkeypatch.setattr("app.core.screenshot.ScreenshotService.capture_window", screenshot)
    monkeypatch.setattr(s.module, "_read_bounded_text", lambda *args: pytest.fail("no UIA read"))
    return manager, bound, events, clock


def observe(s, manager):
    return s.module.capture_visual_focus_observation(manager, s.context,
        focus_receipt=s.focus, expected_field=FIELD)


def test_auxiliary_pair_cannot_issue_new_ready_proof_and_original_receipt_is_immutable(scene, monkeypatch):
    s = scene
    manager, _, events, _ = prepare(s, monkeypatch)
    original = deepcopy(s.focus)
    extra = observe(s, manager)
    with pytest.raises(ValueError, match="single_frame_required"):
        assess(s, focus_observation=extra)
    assert s.requests == [] and len(events) == 1
    assert events == [{"focus_window": False, "purpose": "visual-field-focus-observation"}]
    assert extra["capture_id"] != original["observation"]["capture"]["capture_id"]
    assert s.focus == original


@pytest.mark.parametrize("problem", ["cancel", "deadline", "window", "foreground", "geometry"])
def test_cancel_deadline_or_window_change_never_captures_or_calls_decision(scene, monkeypatch, problem):
    s = scene
    manager, bound, events, clock = prepare(s, monkeypatch)
    if problem == "cancel":
        s.context["cancelled"] = lambda: True
    elif problem == "deadline":
        s.context["deadline_ns"] = clock[0] + 100_000_000
    elif problem == "window":
        bound.handle = 11
    elif problem == "foreground":
        bound.is_active = False
    else:
        bound.rect.right = 181
    with pytest.raises(ValueError):
        observe(s, manager)
    assert events == [] and s.requests == []


@pytest.mark.parametrize("problem", ["cancel", "deadline", "window", "foreground", "geometry", "changed_image", "duplicate_id", "duplicate_path"])
def test_post_capture_change_or_bad_frame_never_calls_decision(scene, monkeypatch, problem):
    s = scene
    manager, bound, events, clock = prepare(s, monkeypatch)
    if problem in {"cancel", "deadline", "window", "foreground", "geometry"}:
        from app.core.screenshot import ScreenshotService
        original = ScreenshotService.capture_window
        def screenshot(self, **kwargs):
            extra = original(self, **kwargs)
            if problem == "cancel":
                s.context["cancelled"] = lambda: True
            elif problem == "deadline":
                clock[0] = s.context["deadline_ns"]
            elif problem == "window":
                bound.handle = 11
            elif problem == "foreground":
                bound.is_active = False
            else:
                bound.rect.right = 181
            return extra
        monkeypatch.setattr(ScreenshotService, "capture_window", screenshot)
        with pytest.raises(ValueError):
            observe(s, manager)
    else:
        extra = observe(s, manager)
        if problem == "changed_image":
            Path(extra["image_path"]).write_bytes(b"changed")
        elif problem == "duplicate_id":
            extra["capture_id"] = s.focus["observation"]["capture"]["capture_id"]
        else:
            extra = deepcopy(s.focus["observation"]["capture"])
            extra["window_rect"] = [0, 0, 180, 90]
        with pytest.raises(ValueError):
            assess(s, focus_observation=extra)
    assert len(events) == 1 and s.requests == []


def test_old_single_frame_route_unchanged_without_observation_option(scene):
    proof = assess(scene)
    assert len(proof.request()["frames"]) == len(scene.requests) == 1
    assert "focus_observation" not in proof.request()["action"]


@pytest.mark.parametrize("accepted", [True, False])
def test_partial_capture_mask_reaches_decision_and_does_not_override_its_verdict(scene, monkeypatch, accepted):
    s = scene
    manager, _, events, _ = prepare(s, monkeypatch)
    from app.core.screenshot import ScreenshotService
    original = ScreenshotService.capture_window
    def screenshot(self, **kwargs):
        extra = original(self, **kwargs)
        with Image.open(extra["image_path"]) as source:
            image = source.copy()
        ImageDraw.Draw(image).rectangle((10, 10, 24, 24), fill=(32, 32, 32))
        image.save(extra["image_path"])
        extra["sha256"] = sha256(Path(extra["image_path"]).read_bytes()).hexdigest()
        extra["capture_visibility"] = {"allowed": True, "masked": True, "coordinate_space": "window",
            "occluded_regions": [{"x": 10, "y": 10, "width": 15, "height": 15}]}
        return extra
    monkeypatch.setattr(ScreenshotService, "capture_window", screenshot)
    extra = observe(s, manager)
    s.focus["observation"]["capture"] = deepcopy(extra)
    s.probabilities[0] = .99 if accepted else .01
    if accepted:
        proof = assess(s)
        assert proof.to_reference()["frame"]["sha256"] == extra["sha256"]
    else:
        with pytest.raises(ValueError, match="visual_field_requires_review"):
            assess(s)
    assert len(events) == len(s.requests) == 1


@pytest.mark.parametrize("problem", ["cancel", "deadline", "window"])
def test_wait_is_cancellable_and_rechecks_window_before_capture(scene, monkeypatch, problem):
    s = scene
    manager, bound, events, clock = prepare(s, monkeypatch)
    def tick(seconds):
        clock[0] += int(seconds * 1e9)
        if problem == "cancel":
            s.context["cancelled"] = lambda: True
        elif problem == "deadline":
            clock[0] = s.context["deadline_ns"]
        else:
            bound.handle = 11
    monkeypatch.setattr(s.module, "sleep", tick)
    with pytest.raises(ValueError):
        observe(s, manager)
    assert events == s.requests == []


def test_full_sequence_ignores_old_pair_option_without_selection_review(visual_sequence, monkeypatch):
    from app.core.input_controller import window_manager, VK_CONTROL, VK_A, VK_V, VK_RETURN
    v = visual_sequence
    _, bound, observations, _ = prepare(v.scene, monkeypatch)
    monkeypatch.setattr(window_manager, "get_bound_window", lambda: bound)
    original = deepcopy(v.scene.focus)
    result = v.run()
    assert result["status"] == "completed", result
    assert len(v.scene.requests) == 2 and observations == []
    assert [row["operation"] for row in v.calls] == ["execute_recognition_plan", "execute_recognition_plan"]
    assert v.events.count((VK_CONTROL, VK_A)) == v.events.count((VK_CONTROL, VK_V)) == v.events.count((VK_RETURN,)) == 1
    [value] = result["field_proofs"]
    assert len(value["frames"]) == 1
    assert all(proof.get("phase") != "after_selection" for proof in result["field_proofs"])
    assert value["frame"]["capture_id"] == v.scene.typed["observation"]["capture"]["capture_id"]
    assert v.scene.focus == original and v.forbidden_calls == []
