"""已认证字段不重复审核像素表现，原生输入事实和真实选区继续复核。"""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import json
from time import perf_counter_ns

from PIL import Image, ImageDraw
import pytest

from tests.test_visual_field_proof import scene, assess, capture, controller_scene, focus_snapshot, FIELD, TEXT
from app.core import local_keyboard_target as keyboard


def native_read(s, monkeypatch, *, baseline=None, damage=None):
    baseline = baseline or focus_snapshot(s, selection=None)
    def read(frame, expected, manager):
        current = replace(baseline, capture_id=frame["capture_id"],
            read_id="fresh-" + str(perf_counter_ns()), observed_at_ns=perf_counter_ns())
        if damage == "runtime":
            current = replace(current, identity=replace(current.identity, runtime_id=(8, 9)))
        elif damage == "geometry":
            current = replace(current, identity=replace(current.identity, control_bbox=(11, 10, 139, 40)))
        elif damage == "value":
            current = replace(current, value="foreign")
        elif damage == "selection":
            current = replace(current, selection=(0, 1))
        elif damage == "read_id":
            current = replace(current, read_id=baseline.read_id)
        elif damage == "time":
            current = replace(current, observed_at_ns=baseline.observed_at_ns)
        elif damage == "capture":
            current = replace(current, capture_id="wrong-capture")
        elif damage == "unavailable":
            from app.agent.windows_text_field_reader import TextFieldReadError
            raise TextFieldReadError("text_field_provider_unavailable")
        return current
    monkeypatch.setattr(s.module, "_read_bounded_text", read)
    return baseline


def blinking_captures(s, monkeypatch, *, final="bounded", selection=False):
    calls = []
    def fresh(*args, **kwargs):
        calls.append(1)
        frame = capture(s.root, "blink-" + str(len(calls)))
        with Image.open(frame["image_path"]) as source:
            image = source.copy()
        draw = ImageDraw.Draw(image)
        if len(calls) == 1 or final == "stable":
            draw.rectangle((60, 18, 60, 35), fill="black")
        if len(calls) > 1 and final == "outside":
            draw.point((61, 20), fill="black")
        if selection and len(calls) >= 3:
            draw.rectangle((20, 20, 55, 35), fill="purple")
        image.save(frame["image_path"])
        frame["sha256"] = sha256(image.tobytes()).hexdigest() if final == "tampered" else sha256(Path(frame["image_path"]).read_bytes()).hexdigest()
        if len(calls) > 1 and final in {"occluded", "remote_occlusion"}:
            frame["capture_visibility"] = {"allowed": True, "masked": True, "coordinate_space": "window",
                "occluded_regions": [{"x": 160, "y": 60, "width": 5, "height": 5} if final == "remote_occlusion"
                    else {"x": 60, "y": 18, "width": 1, "height": 18}]}
        return frame
    monkeypatch.setattr(s.module, "capture_visual_field_frame", fresh)
    return calls


def reviewed_target(s, monkeypatch, *, phase="focus", final="bounded", damage=None, accepted=True):
    baseline = focus_snapshot(s, text=TEXT if phase == "value" else "old", selection=None)
    if phase == "value":
        baseline = replace(baseline, capture_id=s.typed["observation"]["capture"]["capture_id"])
    native_read(s, monkeypatch, baseline=baseline)
    if phase == "focus":
        proof = assess(s, focus_snapshot=baseline)
    else:
        reading = s.module.read_visual_value(frame=s.typed["observation"]["capture"], expected_field=FIELD,
            context=s.context, manager=object())
        proof = assess(s, phase="value", reading=reading)
        baseline = replace(baseline, read_id=reading.reference()["evidence"]["read_id"],
            observed_at_ns=reading.reference()["evidence"]["observed_at_ns"])
    native_read(s, monkeypatch, baseline=baseline, damage=damage)
    reviews = []
    def reviewer(original, frame, snapshot):
        reviews.append(1)
        s.probabilities[0] = .99 if accepted else .1
        return s.module.assess_visual_field_freshness(original, frame=frame, native_snapshot=snapshot)
    target = keyboard.issue_visual_keyboard_target(proof, "type_text" if phase == "focus" else "press_key",
        text=TEXT if phase == "focus" else None, submit_search=phase == "value", freshness_reviewer=reviewer)
    controller, events, _ = controller_scene(s, monkeypatch)
    captures = blinking_captures(s, monkeypatch, final=final)
    return target, controller, events, captures, reviews


@pytest.mark.parametrize("phase", ["focus", "value"])
def test_bounded_native_field_needs_no_repeated_caret_review(scene, monkeypatch, phase):
    s = scene
    target, controller, events, captures, reviews = reviewed_target(s, monkeypatch, phase=phase)
    with keyboard.local_keyboard_target_scope(target):
        request = {"x": 40, "y": 30, **({"text": TEXT, "clear_existing": True} if phase == "focus" else {"key": "Enter"})}
        keyboard.claim_keyboard_target(target.operation, request)
        from app.core.input_controller import window_manager
        target.verify(window_manager)
    assert reviews == [] and len(s.requests) == 1 and len(captures) == 1
    assert events == []
    assert target._freshness_proof is None
    with pytest.raises(ValueError, match="consumed"):
        keyboard.issue_visual_keyboard_target(target.proof, target.operation,
            text=TEXT if phase == "focus" else None, submit_search=phase == "value")
    with pytest.raises(ValueError, match="consumed"):
        with keyboard.local_keyboard_target_scope(target):
            pass


@pytest.mark.parametrize("damage", ["runtime", "geometry", "value", "selection", "read_id", "time", "capture", "unavailable"])
def test_native_drift_never_reaches_freshness_decision(scene, monkeypatch, damage):
    from app.core.input_controller import window_manager
    target, _, events, _, reviews = reviewed_target(scene, monkeypatch, damage=damage)
    with keyboard.local_keyboard_target_scope(target):
        keyboard.claim_keyboard_target("type_text", {"text": TEXT, "x": 40, "y": 30, "clear_existing": True})
        with pytest.raises(ValueError):
            target.verify(window_manager)
    assert reviews == [] and len(scene.requests) == 1 and events == []


@pytest.mark.parametrize("final", ["outside", "occluded"])
def test_native_continuity_accepts_new_visual_states_without_more_model_calls(scene, monkeypatch, final):
    from app.core.input_controller import window_manager
    target, _, events, _, reviews = reviewed_target(scene, monkeypatch, final=final)
    with keyboard.local_keyboard_target_scope(target):
        keyboard.claim_keyboard_target("type_text", {"text": TEXT, "x": 40, "y": 30, "clear_existing": True})
        target.verify(window_manager)
        target.verify(window_manager)
    assert reviews == [] and len(scene.requests) == 1 and events == []


def test_native_current_capture_integrity_is_still_checked(scene, monkeypatch):
    from app.core.input_controller import window_manager
    target, _, events, _, reviews = reviewed_target(scene, monkeypatch, final="tampered")
    with keyboard.local_keyboard_target_scope(target):
        keyboard.claim_keyboard_target("type_text", {"text": TEXT, "x": 40, "y": 30, "clear_existing": True})
        with pytest.raises(ValueError):
            target.verify(window_manager)
    assert reviews == [] and len(scene.requests) == 1 and events == []


def test_outside_field_occlusion_does_not_override_bound_field_review(scene, monkeypatch):
    from app.core.input_controller import window_manager
    target, _, events, _, reviews = reviewed_target(scene, monkeypatch, final="remote_occlusion")
    with keyboard.local_keyboard_target_scope(target):
        keyboard.claim_keyboard_target("type_text", {"text": TEXT, "x": 40, "y": 30, "clear_existing": True})
        target.verify(window_manager)
    assert reviews == [] and len(scene.requests) == 1 and events == []


def test_denied_original_focus_review_cannot_issue_keyboard_capability(scene, monkeypatch):
    scene.probabilities[0] = .1
    _, events, _ = controller_scene(scene, monkeypatch)
    with pytest.raises(ValueError, match="requires_review"):
        keyboard.issue_visual_keyboard_target(assess(scene), "type_text", text=TEXT)
    assert len(scene.requests) == 1 and events == []


def test_native_unavailable_selection_reaches_existing_explicit_decision(scene, monkeypatch):
    from app.core.input_controller import VK_CONTROL, VK_A, VK_V
    s = scene
    baseline = native_read(s, monkeypatch)
    proof = assess(s, focus_snapshot=baseline)
    selected = []
    def reviewer(original, frame, dispatch):
        selected.append(1)
        return s.module.assess_visual_selection(original, frame=frame, dispatch=dispatch)
    target = keyboard.issue_visual_keyboard_target(proof, "type_text", text=TEXT, selection_reviewer=reviewer)
    controller, events, captures = controller_scene(s, monkeypatch, selected_change=True)
    with keyboard.local_keyboard_target_scope(target):
        assert controller.type_text(TEXT, x=40, y=30, clear_existing=True)["typed"] is True
    assert selected == [1] and len(s.requests) == 2
    assert events.count((VK_CONTROL, VK_A)) == events.count((VK_CONTROL, VK_V)) == 1


def test_visual_only_approval_avoids_duplicate_capture_and_decision(scene, monkeypatch):
    from app.core.input_controller import window_manager
    s = scene
    target = keyboard.issue_visual_keyboard_target(assess(s), "type_text", text=TEXT,
        freshness_reviewer=lambda *args: pytest.fail("original approval needs no pixel exemption"))
    controller_scene(s, monkeypatch)
    captures = blinking_captures(s, monkeypatch)
    with keyboard.local_keyboard_target_scope(target):
        keyboard.claim_keyboard_target("type_text", {"text": TEXT, "x": 40, "y": 30, "clear_existing": True})
        target.verify(window_manager)
    assert len(s.requests) == 1 and captures == []


@pytest.mark.parametrize("stop", ["cancelled", "deadline"])
def test_native_revalidation_cannot_escape_original_deadline_or_cancel(scene, monkeypatch, stop):
    from app.core.input_controller import window_manager
    s = scene
    cancelled = [False]
    s.context["cancelled"] = lambda: cancelled[0]
    target, _, events, _, reviews = reviewed_target(s, monkeypatch)
    with keyboard.local_keyboard_target_scope(target):
        keyboard.claim_keyboard_target("type_text", {"text": TEXT, "x": 40, "y": 30, "clear_existing": True})
        if stop == "cancelled":
            cancelled[0] = True
        else:
            monkeypatch.setattr(s.module, "perf_counter_ns", lambda: s.context["deadline_ns"] + 1)
        with pytest.raises(ValueError):
            target.verify(window_manager)
    assert reviews == [] and len(s.requests) == 1 and events == []


def test_approved_native_field_uses_no_extra_request_when_service_cap_is_consumed(scene, monkeypatch):
    from app.core.input_controller import window_manager
    scene.service.profile = scene.service.profile.model_copy(update={"request_cap": 1})
    target, _, events, _, reviews = reviewed_target(scene, monkeypatch)
    with keyboard.local_keyboard_target_scope(target):
        keyboard.claim_keyboard_target("type_text", {"text": TEXT, "x": 40, "y": 30, "clear_existing": True})
        target.verify(window_manager)
    assert reviews == [] and len(scene.requests) == 1 and events == []


def test_sequence_reviews_real_selection_without_duplicate_focus_or_enter_checks(scene, monkeypatch):
    from types import SimpleNamespace as NS
    from tests.test_visual_field_proof import receipt
    from app.core.input_controller import VK_CONTROL, VK_A, VK_V, VK_RETURN, window_manager
    from app.execution import input_sequence
    s = scene
    # 本例验证显式原生连续性；普通视觉路线另有无 UIA 回归。
    s.context["native_field_evidence"] = True
    controller, events, captures = controller_scene(s, monkeypatch)
    baseline = focus_snapshot(s, selection=None)
    def read(frame, expected, manager):
        return replace(baseline, capture_id=frame["capture_id"], read_id="read-"+str(perf_counter_ns()),
            observed_at_ns=perf_counter_ns(), value=TEXT if (VK_CONTROL, VK_V) in events else "old")
    monkeypatch.setattr(s.module, "_read_bounded_text", read)
    monkeypatch.setattr(s.module, "read_visual_focus_snapshot", lambda **kwargs: read(kwargs["frame"], FIELD, window_manager))
    fresh_calls = []
    def fresh(*args, **kwargs):
        fresh_calls.append(1)
        frame = capture(s.root, "sequence-fresh-"+str(len(fresh_calls)))
        with Image.open(frame["image_path"]) as source:
            image = source.copy()
        draw = ImageDraw.Draw(image)
        if (VK_CONTROL, VK_V) in events:
            if len(fresh_calls) == 5:
                draw.rectangle((65, 18, 65, 35), fill="black")
        elif (VK_CONTROL, VK_A) in events:
            draw.rectangle((20, 20, 55, 35), fill="purple")
        elif len(fresh_calls) == 1:
            draw.rectangle((60, 18, 60, 35), fill="black")
        image.save(frame["image_path"])
        frame["sha256"] = sha256(Path(frame["image_path"]).read_bytes()).hexdigest()
        return frame
    monkeypatch.setattr(s.module, "capture_visual_field_frame", fresh)
    calls = []
    class Coordinator:
        _owner = NS(call=lambda callback: callback())
        def _windows(self):
            return window_manager
        def execute_local_step(self, **kwargs):
            calls.append(kwargs["operation"])
            operation = kwargs["operation"]
            if operation == "execute_recognition_plan":
                return deepcopy(s.focus)
            with keyboard.local_keyboard_target_scope(kwargs["keyboard_target"]):
                output = getattr(controller, operation)(**kwargs["request"])
            step = deepcopy(s.typed) if operation == "type_text" else receipt(s.root, "search", "press_key")
            step["response"]["data"].update(output)
            return step
    result = input_sequence.run_input_sequence(Coordinator(), {"handle": 10, "process_id": 20},
        {"field_goal": FIELD["field_goal"], "text": TEXT, "clear_existing": True, "submit_search": True},
        field_evidence_mode="visual", visual_field_context=s.context)
    assert result["status"] == "completed", (result.get("error"), result.get("field_evaluations"), result.get("input_check"))
    assert calls == ["execute_recognition_plan", "type_text", "press_key"]
    assert [row["stage"] for row in result["field_evaluations"]] == [
        "after_click", "after_selection", "after_type"]
    assert len(s.requests) == 3
    assert events.count((VK_CONTROL, VK_A)) == events.count((VK_CONTROL, VK_V)) == events.count((VK_RETURN,)) == 1
    assert not any("freshness_review" in row for row in result["field_proofs"])
