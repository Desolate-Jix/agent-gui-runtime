"""提前采图只缩短渲染宽限；静止、超时和像素变化均不证明任务成功。"""
from hashlib import sha256

from PIL import Image, ImageDraw
import pytest

from tests.test_local_step_timings import timed_scene


class Clock:
    def __init__(self):
        self.seconds = 0.0
        self.cancelled = False

    def now(self):
        return self.seconds

    def wait(self, seconds):
        self.seconds += seconds
        return self.cancelled

    def is_set(self):
        return self.cancelled


def frame(tmp_path, name, *, changed=False, caret=False):
    image = Image.new("RGB", (400, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 399, 30), fill="gray")
    if changed:
        draw.rectangle((50, 50, 180, 160), fill="navy")
    if caret:
        draw.line((210, 90, 210, 105), fill="black")
    path = tmp_path / f"{name}.png"
    image.save(path)
    return {"image_path": str(path), "sha256": sha256(path.read_bytes()).hexdigest(),
            "window_size": {"width": 400, "height": 300}, "window_rect": [0, 0, 400, 300]}


def observe(before, samples, clock):
    from app.execution.adaptive_observation import observe_after_transition
    captures = []
    def capture():
        value = samples(len(captures))
        captures.append(value)
        clock.seconds += .005
        return value
    after, evidence = observe_after_transition(capture, before=before, timeout_ms=2000,
                                               cancel=clock, clock=clock.now)
    return after, evidence, captures


def test_changed_scene_can_finish_early_but_never_authorizes_success(tmp_path):
    before = frame(tmp_path, "before")
    after = frame(tmp_path, "after", changed=True)
    clock = Clock()
    final, evidence, captures = observe(before, lambda _: after, clock)
    assert 400 <= evidence["elapsed_ms"] < 800
    assert final == after and len(captures) >= 3
    assert evidence["reason"] == "changed_then_stable"
    assert evidence["readiness"] == "unassessed"
    assert evidence["authorizes_action"] is False
    assert evidence["effect_verified"] is False
    assert evidence["samples"][-1]["sha256"] == after["sha256"]


def test_unchanged_screen_waits_full_budget_and_returns_a_fresh_capture(tmp_path):
    before = frame(tmp_path, "before")
    after = frame(tmp_path, "same")
    clock = Clock()
    final, evidence, captures = observe(before, lambda _: after, clock)
    assert clock.seconds >= 2
    assert evidence["reason"] == "budget_exhausted"
    assert final["image_path"] != before["image_path"]
    assert evidence["effect_verified"] is False


def test_caret_only_change_does_not_end_wait_early(tmp_path):
    before = frame(tmp_path, "before")
    caret = frame(tmp_path, "caret", caret=True)
    _, evidence, _ = observe(before, lambda _: caret, Clock())
    assert evidence["elapsed_ms"] >= 2000
    assert not any(row["substantial_change"] for row in evidence["samples"])


def test_transient_change_back_to_original_is_not_a_completed_transition(tmp_path):
    before = frame(tmp_path, "before")
    transient = frame(tmp_path, "transient", changed=True)
    _, evidence, _ = observe(before, lambda n: transient if n == 0 else before, Clock())
    assert evidence["reason"] == "budget_exhausted"
    assert evidence["elapsed_ms"] >= 2000


def test_animation_never_ends_wait_early(tmp_path):
    before = frame(tmp_path, "before")
    first = frame(tmp_path, "first", changed=True)
    second = frame(tmp_path, "second", changed=True, caret=True)
    _, evidence, _ = observe(before, lambda n: (first, second)[n % 2], Clock())
    assert evidence["reason"] == "budget_exhausted"
    assert evidence["elapsed_ms"] >= 2000


@pytest.mark.parametrize("mutation", ["hash", "geometry", "path"])
def test_capture_binding_failure_is_explicit(tmp_path, mutation):
    before = frame(tmp_path, "before")
    after = frame(tmp_path, "after", changed=True)
    if mutation == "hash":
        after["sha256"] = "0" * 64
    elif mutation == "geometry":
        after["window_rect"] = [10, 0, 410, 300]
    else:
        after["image_path"] = str(tmp_path / "missing.png")
    with pytest.raises(ValueError, match="adaptive_observation_"):
        observe(before, lambda _: after, Clock())


def test_cancelled_wait_never_takes_a_followup_capture(tmp_path):
    before = frame(tmp_path, "before")
    clock = Clock()
    clock.cancelled = True
    calls = []
    def capture(_):
        calls.append(True)
        return before
    with pytest.raises(ValueError, match="cancelled"):
        observe(before, capture, clock)
    assert calls == []


def test_capture_failure_is_not_retried_or_hidden(tmp_path):
    before = frame(tmp_path, "before")
    calls = []
    def unavailable(_):
        calls.append(True)
        raise RuntimeError("capture failed")
    with pytest.raises(RuntimeError, match="capture failed"):
        observe(before, unavailable, Clock())
    assert calls == [True]


def test_execution_plan_default_wait_uses_adaptive_observation(timed_scene, monkeypatch, tmp_path):
    from app.execution import local_direct_step as direct
    co, state, clock, _ = timed_scene
    before = frame(tmp_path, "route-before")
    after = frame(tmp_path, "route-after", changed=True)
    rule = {"kind": "agent_judgment", "decision_condition": "The requested panel is open."}
    plan = {"schema_version": "task_plan.v3", "title": "Open panel", "goal": "Open panel",
            "inputs": {}, "steps": [{"step_id": "open", "action": {"kind": "click", "goal": "Open panel"},
                                      "verification": rule}],
            "completion": {"step_id": "open", "verification": rule}}
    context = {"schema": "action_review_context.v1", "plan": plan, "step_id": "open",
               "run_id": "test-run", "attempt_id": "test-attempt", "budget_ms": 60000}
    class Capture:
        def __init__(self, **kwargs):
            pass
        def capture_window(self, **kwargs):
            state.events.append("adaptive_before")
            return before
    monkeypatch.setattr(direct, "ScreenshotService", Capture)
    monkeypatch.setattr(direct, "_capture_observation", lambda *args: after)
    monkeypatch.setattr(co._cancel_wait, "wait", lambda seconds: clock.advance(seconds * 1000) or False)
    result = co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation="execute_recognition_plan", request={"goal": "Open panel"},
        include_observation=True, action_review=context)
    assert result["phase"] == "returned"
    assert state.events.count("route") == 1
    assert result["observation"]["adaptive_wait"]["early"] is True
    assert result["observation"]["capture"]["observation_stage"] == "after_transition_observation"
    assert result["observation"]["readiness"] == "unassessed"
    assert result["effect_verified"] is False


@pytest.mark.parametrize("outside_scope", ["input_sequence", "wait_policy", "native_condition", "explicit_wait"])
def test_adaptive_observation_does_not_change_other_pinned_step_waits(timed_scene, monkeypatch, tmp_path, outside_scope):
    from app.execution import local_direct_step as direct
    co, state, clock, _ = timed_scene
    before = frame(tmp_path, "scope-before")
    after = frame(tmp_path, "scope-after", changed=True)
    rule = {"kind": "agent_judgment", "decision_condition": "The requested panel is open."}
    action = {"kind": "click", "goal": "Open panel"}
    if outside_scope == "input_sequence":
        action = {"kind": "input_sequence", "field_goal": "Search field", "text": "fresh", "clear_existing": True, "submit_search": True}
    elif outside_scope == "wait_policy":
        rule["wait_policy"] = {"loading_condition": "A loading indicator is visible.", "completion_excludes_loading": True}
    elif outside_scope == "native_condition":
        rule = {"kind": "native_condition", "condition": {"text": "Panel", "control_type": "Text"}}
    plan = {"schema_version": "task_plan.v3", "title": "Open panel", "goal": "Open panel", "inputs": {},
        "steps": [{"step_id": "open", "action": action, "verification": rule}],
        "completion": {"step_id": "open", "verification": rule}}
    context = {"schema": "action_review_context.v1", "plan": plan, "step_id": "open", "run_id": "test-run",
        "attempt_id": "test-attempt", "budget_ms": 60000}
    class Capture:
        def __init__(self, **kwargs):
            pass
        def capture_window(self, **kwargs):
            return before
    waits = []
    def wait(seconds):
        waits.append(seconds)
        clock.advance(seconds * 1000)
        return False
    monkeypatch.setattr(direct, "ScreenshotService", Capture)
    monkeypatch.setattr(direct, "_capture_observation", lambda *args: after)
    monkeypatch.setattr(co._cancel_wait, "wait", wait)
    result = co.execute_local_step(target_window_handle=321, target_process_id=12,
        operation="execute_recognition_plan", request={"goal": "Open panel"}, include_observation=True,
        action_review=context, **({"observation_wait_ms": 2000} if outside_scope == "explicit_wait" else {}))
    assert result["phase"] == "returned" and state.events.count("route") == 1
    assert waits == [2.0]
    assert "adaptive_wait" not in result["observation"]
    assert result["observation"]["capture"]["observation_stage"] == "after_render_wait"


@pytest.mark.parametrize("caret_only", [False, True])
def test_large_canvas_local_list_change_can_activate_but_single_caret_cannot(tmp_path, caret_only):
    def large(name, changed):
        image = Image.new("RGB", (2560, 1377), "white")
        draw = ImageDraw.Draw(image)
        if changed:
            if caret_only:
                draw.line((100, 100, 100, 120), fill="black")
            else:
                draw.rectangle((70, 130, 170, 150), fill="navy")
        path = tmp_path / (name + ".png")
        image.save(path)
        return {"image_path": str(path), "sha256": sha256(path.read_bytes()).hexdigest(),
            "window_size": {"width": 2560, "height": 1377}, "window_rect": [0, 0, 2560, 1377]}
    before, after = large("large-before", False), large("large-after", True)
    _, evidence, _ = observe(before, lambda _: after, Clock())
    assert evidence["early"] is (not caret_only)
    if not caret_only:
        assert .0005 <= evidence["samples"][-1]["changed_fraction"] < .002
        assert evidence["samples"][-1]["changed_pixels"] >= 128


@pytest.mark.parametrize("last_time,early", [(1.9999996, True), (2.0000004, False)])
def test_deadline_classification_uses_the_same_unrounded_finish_time(tmp_path, last_time, early):
    from app.execution.adaptive_observation import observe_after_transition
    before, after = frame(tmp_path, "edge-before"), frame(tmp_path, "edge-after", changed=True)
    clock = Clock()
    ticks = iter((1.7, 1.81, last_time))
    def wait(seconds):
        clock.seconds = next(ticks)
        return False
    clock.wait = wait
    _, evidence = observe_after_transition(lambda: after, before=before, timeout_ms=2000,
        cancel=clock, clock=clock.now)
    assert evidence["early"] is early
    assert evidence["elapsed_ms"] == last_time * 1000
    assert evidence["samples"][-1]["elapsed_ms"] == 2000.0
