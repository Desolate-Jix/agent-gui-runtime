"""合成图与真实服务认证的视觉字段合同；不运行桌面或模型。"""
from contextvars import copy_context
from copy import deepcopy
from hashlib import sha256
import importlib
import json
from pathlib import Path
from time import perf_counter_ns
from types import SimpleNamespace as NS

import httpx
from PIL import Image, ImageDraw
import pytest

from app.agent.windows_text_field_reader import TextFieldReadError
from app.core import local_keyboard_target as keyboard, local_text_focus as focus
from app.judgment import DecisionProfile, DecisionService, OpenAIDecisionsProvider


IDENTITY = {"handle": 10, "process_id": 20, "process_create_time": 123.0}
NATIVE = {"contract_version": "windows_native_identity_observation_v1", "provider": "windows_native_identity",
    "status": "observed", "target_window_handle": 10, "process_id": 20, "process_create_time": 123.0,
    "executable_path": "C:/fixture.exe"}
TEXT = "fresh \u4e2d\u6587"
SELECTION_CONDITION = (
    "The specified ordinary readable text field retains keyboard focus and the same complete existing text shown "
    "in the original post-click image is now visibly selected for replacement; it is enabled, editable, unmasked, "
    "and no other field or popup has taken focus.")
FIELD = {"field_goal": "Search field", "bbox": {"x": 10, "y": 10, "w": 140, "h": 40},
    "click_point": {"x": 40, "y": 30}, "window_identity": IDENTITY, "window_rect": [0, 0, 180, 90],
    "field_kind": "search", "expected_text": TEXT}


def module():
    return importlib.import_module("app.execution.visual_field_proof")


def capture(root, name, *, changed=False):
    path = root / "captures" / (name + ".png")
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (180, 90), "white")
    ImageDraw.Draw(image).rectangle((10, 10, 149, 49), outline="red" if changed else "blue", width=2)
    image.save(path)
    return {"capture_id": name, "image_path": str(path), "sha256": sha256(path.read_bytes()).hexdigest(),
        "image_size": {"width": 180, "height": 90}, "window_size": {"width": 180, "height": 90},
        "window_identity": deepcopy(IDENTITY)}


def executed_focus(value):
    point = deepcopy(FIELD["click_point"])
    value["response"]["data"]["click_result"].update(window_point=deepcopy(point), screen_point=deepcopy(point),
        down={"cursor": deepcopy(point)}, up={"cursor": deepcopy(point)}, window_handle=10, button="left", click_count=1)
    return value


def receipt(root, name, operation="execute_recognition_plan", *, before=None):
    after = capture(root, name + "-after")
    data = {"execution_path": {"action_executed": True}, "action_executed": True,
        "selected_click_point": deepcopy(FIELD["click_point"]),
        "selected_click_point_coordinate_space": "capture_image_pixels",
        "recognition_plan": {"recommended_target": {"candidate_id": "field", "bbox": deepcopy(FIELD["bbox"])}}}
    if operation == "execute_recognition_plan":
        data["click_result"] = {"clicked": True}
    else:
        data["typed"] = True
    return {"contract_version": "local_direct_step_v1", "step_id": name, "phase": "returned",
        "operation": operation, "target_identity": deepcopy(NATIVE), "local_input_scope_closed": True,
        "finished_at": "2026-10-11T00:00:00Z", "capture": before or capture(root, name + "-before"),
        "target_window_geometry": {"coordinate_space": "screen_pixels", "rect_format": "ltrb", "rect": [0, 0, 180, 90]},
        "request": {"goal": FIELD["field_goal"]} if operation == "execute_recognition_plan" else {
            "text": TEXT, "clear_existing": True, "click_before_typing": False},
        "response": {"success": True, "data": data}, "observation": {"status": "captured", "capture": after}}


@pytest.fixture
def scene(tmp_path, monkeypatch):
    monkeypatch.setenv("VISUAL_FIELD_TEST_KEY", "offline-only")
    requests, probabilities, during = [], [.99], []
    def handle(request):
        requests.append(request)
        if during:
            during[0]()
        body = json.loads(request.content)
        return httpx.Response(200, json={"model": "gpt-6-luna", "answers": [
            {"type": "predicate", "name": q["name"], "probability": probabilities[0] if q["name"] == "condition_met" else .01}
            for q in body["questions"]], "usage": {"input_tokens": 4, "output_tokens": 0, "total_tokens": 4}})
    client = httpx.Client(transport=httpx.MockTransport(handle))
    m = module()
    service = DecisionService(tmp_path, profile=DecisionProfile.model_validate({
        "contract_version": "decision_profile.v2", "mode": "auto", "api_key_env": "VISUAL_FIELD_TEST_KEY",
        "request_cap": 20, "auto_conditions": [m.VISUAL_FOCUS_CONDITION, m.VISUAL_VALUE_CONDITION, m.VISUAL_TEXT_VALUE_CONDITION, SELECTION_CONDITION,
            m.VISUAL_FIELD_FRESHNESS_CONDITION,
            "The recorded click is inside the intended visible text input.",
            "The marked click is inside the intended visible text input and the field is usable for typing now.",
            "The intended text input is empty or its complete existing text is selected for replacement."]}),
        provider=OpenAIDecisionsProvider(api_key_env="VISUAL_FIELD_TEST_KEY", client=client))
    context = {"service": service, "execution_request_id": "visual-sequence-one",
        "deadline_ns": perf_counter_ns() + 30_000_000_000, "review_context": {
            "goal": "Search for the supplied text", "step_goal": "Fill search field", "remaining_plan": [],
            "allowed_states": [], "source_id": "visual-sequence-one"}, "field_kind": "search", "ocr_enabled": False}
    s = NS(root=tmp_path, module=m, service=service, requests=requests, probabilities=probabilities, during=during,
        context=context, focus=receipt(tmp_path, "focus"), typed=receipt(tmp_path, "typed", "type_text"))
    yield s
    service.close()
    client.close()


def assess(s, *, phase="focus", reading=None, frame=None, **kwargs):
    selected = s.focus if phase == "focus" else s.typed
    return s.module.assess_visual_field(phase=phase, focus_receipt=s.focus,
        input_receipt=s.typed if phase == "value" else None,
        frame=frame or selected["observation"]["capture"], expected_field=deepcopy(FIELD),
        context=s.context, value_reading=reading, **kwargs)


def bounded_read(s, monkeypatch, *, text=TEXT, failure=None):
    def read(*args, **kwargs):
        if failure:
            raise TextFieldReadError(failure)
        return NS(value=text, source="uia_value", to_reference=lambda: {"source": "uia_value", "read_id": "bounded-one"})
    monkeypatch.setattr(s.module, "_read_bounded_text", read)
    return s.module.read_visual_value(frame=s.typed["observation"]["capture"], expected_field=FIELD,
        context=s.context, manager=object())


def test_missing_uia_uses_proven_visual_focus(scene, monkeypatch):
    s = scene
    monkeypatch.setattr(focus, "probe_local_focus_target", lambda *a, **kw: pytest.fail("visual route must not probe UIA"))
    monkeypatch.setattr(focus, "require_local_operator_input", lambda _: True)
    target = focus.VisualTextFocusTarget(10, 20)
    with focus.visual_text_focus_scope(target):
        assert focus.has_local_text_focus() is False
        assert focus.check_local_text_focus(FIELD["click_point"], object())["evidence_kind"] == "visual"
    proof = assess(s)
    assert proof.to_reference()["phase"] == "focus" and proof.to_reference()["artifact_is_authorization"] is False
    assert len(s.requests) == 1 and target.binding is None


def test_preclick_pass_is_not_postclick_focus(scene):
    with pytest.raises(ValueError, match="new_after"):
        assess(scene, frame=scene.focus["capture"])
    assert scene.requests == []


def test_value_requires_actual_completed_typing_and_exact_independent_read(scene, monkeypatch):
    s = scene
    with pytest.raises(ValueError, match="value_reading"):
        assess(s, phase="value")
    reading = bounded_read(s, monkeypatch)
    proof = assess(s, phase="value", reading=reading)
    ref = proof.to_reference()
    assert ref["phase"] == "value" and ref["value_sha256"] == sha256(TEXT.encode("utf-8")).hexdigest()
    body = json.loads(s.requests[-1].content)
    context_text = next(item["text"] for item in body["input"][0]["content"] if
                        item["type"] == "input_text" and item["text"].startswith("Proposed action context"))
    assert TEXT in context_text and '"actual_text"' in context_text and '"source": "uia_value"' in context_text


def test_unreadable_or_mismatched_value_requires_review(scene, monkeypatch):
    s = scene
    with pytest.raises(TextFieldReadError, match="unavailable"):
        bounded_read(s, monkeypatch, failure="text_field_uia_unavailable")
    reading = bounded_read(s, monkeypatch, text=TEXT + " ")
    with pytest.raises(ValueError, match="value_mismatch"):
        assess(s, phase="value", reading=reading)
    assert s.requests == []


def controller_scene(s, monkeypatch, *, selected_change=False):
    import app.core.input_controller as native
    from app.core.input_controller import InputController
    controller, events, captures = InputController(), [], []
    bound = NS(handle=10, process_id=20, title="isolated", rect=NS(left=0, top=0, right=180, bottom=90))
    class Clipboard:
        status = "not_started"
        def __enter__(self):
            events.append("clipboard-prepared")
            return self
        def verify_current_text(self):
            events.append("clipboard-verified")
            return 1
        def __exit__(self, *error):
            self.status = "restored"
            events.append("clipboard-restored")
    monkeypatch.setattr(controller, "_ensure_windows_input", lambda: None)
    monkeypatch.setattr(controller, "_require_bound_window", lambda: bound)
    monkeypatch.setattr(controller, "_clipboard_text_transaction", lambda *a, **kw: Clipboard())
    monkeypatch.setattr(controller, "_focus_window", lambda *a: pytest.fail("private visual route must not refocus"))
    monkeypatch.setattr(controller, "_press_chord", lambda keys: events.append(tuple(keys)))
    monkeypatch.setattr(native.win32gui, "GetForegroundWindow", lambda: 10)
    monkeypatch.setattr(native.window_manager, "get_bound_window", lambda: bound)
    monkeypatch.setattr(native.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(s.module, "current_local_operator_identity", lambda manager: deepcopy(NATIVE))
    monkeypatch.setattr(s.module, "require_local_operator_input", lambda manager: True)
    def fresh(*args, **kwargs):
        captures.append(1)
        return capture(s.root, "keyboard-fresh-" + str(len(captures)),
            changed=selected_change and (native.VK_CONTROL, native.VK_A) in events)
    monkeypatch.setattr(s.module, "capture_visual_field_frame", fresh)
    return controller, events, captures


def test_real_controller_verifies_twice_without_inner_decision(scene, monkeypatch):
    from app.core.input_controller import VK_CONTROL, VK_A, VK_V
    from dataclasses import replace
    s = scene
    target = keyboard.issue_visual_keyboard_target(assess(s, focus_snapshot=focus_snapshot(s)), "type_text", text=TEXT)
    controller, events, captures = controller_scene(s, monkeypatch)
    def read(frame, *args):
        return replace(focus_snapshot(s, selection=(0, 3) if (VK_CONTROL, VK_A) in events else (0, 0)),
            capture_id=frame["capture_id"])
    monkeypatch.setattr(s.module, "_read_bounded_text", read)
    with keyboard.local_keyboard_target_scope(target):
        assert controller.type_text(TEXT, x=40, y=30, clear_existing=True)["typed"] is True
    assert len(captures) == 2 and len(s.requests) == 1
    assert events.count((VK_CONTROL, VK_A)) == 1 and events.count((VK_CONTROL, VK_V)) == 1
    assert events[-1] == "clipboard-restored"


def test_real_controller_unproven_selection_change_stops_before_paste(scene, monkeypatch):
    from app.core.input_controller import VK_CONTROL, VK_A, VK_V
    s = scene
    target = keyboard.issue_visual_keyboard_target(assess(s), "type_text", text=TEXT)
    controller, events, captures = controller_scene(s, monkeypatch, selected_change=True)
    with keyboard.local_keyboard_target_scope(target):
        with pytest.raises(ValueError, match="fresh_proof_required"):
            controller.type_text(TEXT, x=40, y=30, clear_existing=True)
    assert len(captures) == 1 and len(s.requests) == 1
    assert events.count((VK_CONTROL, VK_A)) == 1 and (VK_CONTROL, VK_V) not in events
    assert events[-1] == "clipboard-restored"


def test_real_controller_search_enter_uses_value_proof_without_inner_decision(scene, monkeypatch):
    from app.core.input_controller import VK_RETURN
    s = scene
    target = keyboard.issue_visual_keyboard_target(assess(s, phase="value", reading=bounded_read(s, monkeypatch)),
        "press_key", submit_search=True)
    controller, events, captures = controller_scene(s, monkeypatch)
    with keyboard.local_keyboard_target_scope(target):
        assert controller.press_key("Enter", x=40, y=30)["pressed"] is True
    assert captures == [] and len(s.requests) == 1 and events == [(VK_RETURN,)]


def focus_snapshot(s, *, text="old", selection=(0, 0), runtime_id=(1, 2)):
    from app.agent.text_field_evidence import TextFieldIdentity, TextFieldSnapshot
    identity = TextFieldIdentity("visual-field", 10, 20, 123.0, runtime_id, (0, 0, 180, 90), (10, 10, 140, 40))
    return TextFieldSnapshot(identity, s.focus["observation"]["capture"]["capture_id"],
        "reading-" + str(perf_counter_ns()), perf_counter_ns(), "uia_value", text, selection)


def test_expected_select_all_uses_bounded_proof_without_extra_decision(scene, monkeypatch):
    from app.core.input_controller import VK_CONTROL, VK_A, VK_V
    s = scene
    target = keyboard.issue_visual_keyboard_target(assess(s, focus_snapshot=focus_snapshot(s)), "type_text", text=TEXT)
    controller, events, captures = controller_scene(s, monkeypatch, selected_change=True)
    from dataclasses import replace
    def read(frame, *args):
        selected = (VK_CONTROL, VK_A) in events
        return replace(focus_snapshot(s, selection=(0, 3) if selected else (0, 0)), capture_id=frame["capture_id"])
    monkeypatch.setattr(s.module, "_read_bounded_text", read)
    with keyboard.local_keyboard_target_scope(target):
        assert controller.type_text(TEXT, x=40, y=30, clear_existing=True)["typed"] is True
    assert len(s.requests) == 1 and len(captures) == 2
    assert events.count((VK_CONTROL, VK_A)) == events.count((VK_CONTROL, VK_V)) == 1


@pytest.mark.parametrize("fault", ["value", "focus", "partial_selection"])
def test_bounded_selection_drift_never_pastes_or_falls_back_to_model(scene, monkeypatch, fault):
    from app.core.input_controller import VK_CONTROL, VK_A, VK_V
    s = scene
    target = keyboard.issue_visual_keyboard_target(assess(s, focus_snapshot=focus_snapshot(s)), "type_text", text=TEXT,
        selection_reviewer=lambda *a: pytest.fail("known negative cannot fall back to model"))
    controller, events, _ = controller_scene(s, monkeypatch, selected_change=True)
    from dataclasses import replace
    def read(frame, *args):
        selected = (VK_CONTROL, VK_A) in events
        current = focus_snapshot(s, text="foreign" if selected and fault == "value" else "old",
            runtime_id=(4, 5) if selected and fault == "focus" else (1, 2),
            selection=((0, 1) if fault == "partial_selection" else (0, 3)) if selected else (0, 0))
        return replace(current, capture_id=frame["capture_id"])
    monkeypatch.setattr(s.module, "_read_bounded_text", read)
    with keyboard.local_keyboard_target_scope(target):
        with pytest.raises(ValueError, match="selection|native_changed"):
            controller.type_text(TEXT, x=40, y=30, clear_existing=True)
    assert (VK_CONTROL, VK_A) in events and (VK_CONTROL, VK_V) not in events and len(s.requests) == 1


@pytest.mark.parametrize("accepted", [True, False])
def test_visual_selection_is_one_explicit_additional_decision_in_same_type_call(scene, monkeypatch, accepted):
    from app.core.input_controller import VK_CONTROL, VK_A, VK_V
    s = scene
    proof = assess(s)
    s.probabilities[0] = .99 if accepted else .5
    reviews = []
    def review(original, frame, dispatch):
        assert dispatch.reference()["selection_dispatch"] == "completed"
        reviews.append(1)
        return s.module.assess_visual_selection(original, frame=frame, dispatch=dispatch)
    target = keyboard.issue_visual_keyboard_target(proof, "type_text", text=TEXT, selection_reviewer=review)
    controller, events, _ = controller_scene(s, monkeypatch, selected_change=True)
    with keyboard.local_keyboard_target_scope(target):
        if accepted:
            output = controller.type_text(TEXT, x=40, y=30, clear_existing=True)
            assert output["typed"] is True and output["typing_dispatch"]["text_dispatch"] == "completed"
        else:
            with pytest.raises(ValueError, match="requires_review"):
                controller.type_text(TEXT, x=40, y=30, clear_existing=True)
    assert len(s.requests) == 2 and reviews == [1] and events.count((VK_CONTROL, VK_A)) == 1
    assert events.count((VK_CONTROL, VK_V)) == int(accepted)
    assert list((s.root / "visual-field-proof" / "typing-dispatch").glob("*.json"))
    assert events[-1] == "clipboard-restored"


@pytest.mark.parametrize("failure_at,expected", [("selection_started", None), ("selection_completed", True), ("text_started", True)])
def test_real_type_route_preserves_partial_dispatch_facts(scene, monkeypatch, failure_at, expected):
    from app.api import action
    from app.core.input_controller import VK_CONTROL, VK_A, VK_V
    s = scene
    target = keyboard.issue_visual_keyboard_target(assess(s), "type_text", text=TEXT)
    controller, events, _ = controller_scene(s, monkeypatch, selected_change=failure_at == "selection_completed")
    def chord(keys):
        events.append(tuple(keys))
        if (failure_at == "selection_started" and keys == [VK_CONTROL, VK_A]
                or failure_at == "text_started" and keys == [VK_CONTROL, VK_V]):
            raise RuntimeError("synthetic native input interruption")
    monkeypatch.setattr(controller, "_press_chord", chord)
    monkeypatch.setattr(action, "input_controller", controller)
    monkeypatch.setattr(action, "write_trace", lambda **kw: "offline-trace.json")
    with keyboard.local_keyboard_target_scope(target):
        response = action.type_text(action.TypeTextRequest(text=TEXT, x=40, y=30, clear_existing=True))
    assert response.success is False and response.data["execution_path"]["action_executed"] is expected
    assert response.data["typing_dispatch"]["input_started"] is True
    assert events[-1] == "clipboard-restored"


def test_known_negative_uia_does_not_fall_back_to_ocr(scene, monkeypatch):
    s = scene
    s.context["ocr_enabled"] = True
    monkeypatch.setattr(s.module, "_read_roi_text", lambda *a, **kw: pytest.fail("known negative must remain blocked"))
    with pytest.raises(TextFieldReadError, match="target_not_writable"):
        bounded_read(s, monkeypatch, failure="text_field_target_not_writable")


def test_visual_boolean_cannot_be_used_as_extracted_text(scene):
    with pytest.raises(ValueError, match="value_reading"):
        assess(scene, phase="value", reading={"text": TEXT, "source": "roi_ocr", "trusted": True})
    assert scene.requests == []


def test_forged_assessment_cannot_issue_field_proof(scene):
    s = scene
    proof = assess(s)
    request = proof.request()
    forged = deepcopy(proof.assessment())
    forged["request_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="authentication"):
        s.module.build_visual_field_proof(phase="focus", focus_receipt=s.focus, input_receipt=None,
            frame=s.focus["observation"]["capture"], assessment=forged, expected_field=FIELD,
            context=s.context)
    assert s.service.validate_result(proof.assessment(), **request)


@pytest.mark.parametrize("fault", ["before", "unknown_input", "different_window", "tampered_image"])
def test_proof_rejects_wrong_temporal_or_window_binding(scene, fault):
    s = scene
    if fault == "before":
        s.focus["observation"]["capture"] = deepcopy(s.focus["capture"])
    elif fault == "unknown_input":
        s.focus["response"]["data"]["execution_path"]["action_executed"] = None
    elif fault == "different_window":
        s.focus["observation"]["capture"]["window_identity"]["handle"] = 11
    else:
        Path(s.focus["observation"]["capture"]["image_path"]).write_bytes(b"changed")
    with pytest.raises(ValueError):
        assess(s)
    assert s.requests == []


def test_ambiguous_focus_types_nothing(scene):
    s = scene
    s.probabilities[0] = .5
    with pytest.raises(ValueError, match="requires_review"):
        assess(s)
    assert len(s.requests) == 1


def test_expired_deadline_does_not_call_decision(scene):
    scene.context["deadline_ns"] = perf_counter_ns() - 1
    with pytest.raises(ValueError, match="deadline"):
        assess(scene)
    assert scene.requests == []


def test_focus_change_before_type_blocks_without_more_decisions(scene, monkeypatch):
    s = scene
    proof = assess(s, focus_snapshot=focus_snapshot(s))
    target = keyboard.issue_visual_keyboard_target(proof, "type_text", text=TEXT, clear_existing=True)
    monkeypatch.setattr(s.module, "capture_visual_field_frame", lambda *a, **kw: capture(s.root, "fresh", changed=True))
    def lost_focus(*args):
        raise TextFieldReadError("text_field_target_not_focused")
    monkeypatch.setattr(s.module, "_read_bounded_text", lost_focus)
    monkeypatch.setattr(s.module, "current_local_operator_identity", lambda manager: deepcopy(NATIVE))
    monkeypatch.setattr(s.module, "require_local_operator_input", lambda manager: True)
    manager = NS(get_bound_window=lambda: NS(handle=10, process_id=20,
        rect=NS(left=0, top=0, right=180, bottom=90)))
    with keyboard.local_keyboard_target_scope(target):
        claimed = keyboard.claim_keyboard_target("type_text", {"text": TEXT, "x": 40, "y": 30,
            "clear_existing": True, "click_before_typing": False, "submit": False})
        with pytest.raises(TextFieldReadError, match="not_focused"):
            claimed.verify(manager)
    assert len(s.requests) == 1


def test_nonsearch_enter_not_promoted(scene, monkeypatch):
    s = scene
    proof = assess(s, phase="value", reading=bounded_read(s, monkeypatch))
    with pytest.raises(ValueError, match="search"):
        keyboard.issue_visual_keyboard_target(proof, "press_key", submit_search=False)
    with pytest.raises(ValueError, match="visual"):
        keyboard.VisualKeyboardTarget(proof, "press_key")


def test_keyboard_scope_is_one_use_and_owner_thread_bound(scene):
    s = scene
    target = keyboard.issue_visual_keyboard_target(assess(s), "type_text", text=TEXT, clear_existing=True)
    request = {"text": TEXT, "x": 40, "y": 30, "clear_existing": True}
    with keyboard.local_keyboard_target_scope(target):
        copied = copy_context()
        assert keyboard.claim_keyboard_target("type_text", request) is target
        with pytest.raises(ValueError, match="consumed"):
            keyboard.claim_keyboard_target("type_text", request)
    with pytest.raises(ValueError, match="scope unavailable"):
        copied.run(keyboard.claim_keyboard_target, "type_text", request)


def sequence_scene(s, monkeypatch, *, type_timeout=False, real_type=False, review_options=None):
    from app.execution import input_sequence
    calls = []
    s.context["native_field_evidence"] = True
    bounded_read(s, monkeypatch)
    monkeypatch.setattr(s.module, "read_visual_focus_snapshot", lambda **kw: None)
    controller = events = None
    if real_type:
        controller, events, _ = controller_scene(s, monkeypatch, selected_change=True)
    class Coordinator:
        _owner = NS(call=lambda callback: callback())
        def _windows(self):
            return object()
        def execute_local_step(self, **kwargs):
            calls.append(kwargs)
            operation = kwargs["operation"]
            if operation == "execute_recognition_plan":
                assert type(kwargs["focus_target"]) is focus.VisualTextFocusTarget
                return deepcopy(s.focus)
            assert type(kwargs["keyboard_target"]) is keyboard.VisualKeyboardTarget
            kwargs["keyboard_target"].validate_command(operation, kwargs["request"])
            if operation == "type_text":
                if type_timeout:
                    raise TimeoutError("synthetic partial paste timeout")
                if real_type:
                    from app.api import action
                    with keyboard.local_keyboard_target_scope(kwargs["keyboard_target"]):
                        monkeypatch.setattr(action, "input_controller", controller)
                        monkeypatch.setattr(action, "write_trace", lambda **kw: "offline-sequence-trace.json")
                        response = action.type_text(action.TypeTextRequest(**kwargs["request"]))
                    step = deepcopy(s.typed)
                    step["response"] = response.model_dump(mode="json")
                    return step
                return deepcopy(s.typed)
            response = receipt(s.root, "search", "press_key")
            response["response"]["data"]["pressed"] = True
            return response
    result = input_sequence.run_input_sequence(Coordinator(), {"handle": 10, "process_id": 20},
        {"field_goal": FIELD["field_goal"], "text": TEXT, "clear_existing": True, "submit_search": True},
        field_evidence_mode="visual", visual_field_context=s.context, **(review_options or {}))
    return result, calls


def test_sequence_uses_one_focus_and_one_value_decision(scene, monkeypatch):
    result, calls = sequence_scene(scene, monkeypatch)
    assert result["status"] == "completed" and result["input_check"]["status"] == "matched"
    assert [call["operation"] for call in calls] == ["execute_recognition_plan", "type_text", "press_key"]
    assert len(scene.requests) == 2 and result["completed_steps"] == ["focus", "type", "check_input", "search"]


def test_sequence_records_explicit_selection_stage_and_never_replays(scene, monkeypatch):
    result, calls = sequence_scene(scene, monkeypatch, real_type=True)
    assert result["status"] == "completed", (result.get("error"), result.get("input_check"), result.get("field_evaluations"))
    assert len(scene.requests) == 3
    assert [row["stage"] for row in result["field_evaluations"]] == ["after_click", "after_selection", "after_type"]
    assert all(row["status"] == "adopted" for row in result["field_evaluations"])
    assert [row["focus_stage"] for row in result["field_proofs"]] == ["after_click", "after_selection", None]
    assert len(result["field_proofs"][1]["frames"]) == 2
    assert sum(row["operation"] == "type_text" for row in calls) == 1


def test_sequence_selection_cannot_escape_same_service_request_cap(scene, monkeypatch):
    scene.service.profile = scene.service.profile.model_copy(update={"request_cap": 1})
    result, calls = sequence_scene(scene, monkeypatch, real_type=True)
    assert result["status"] == "interrupted" and result["completed_steps"] == ["focus"]
    assert len(scene.requests) == 1 and len(calls) == 2
    assert result["field_evaluations"][-1]["stage"] == "after_selection"
    assert result["field_evaluations"][-1]["status"] == "not_adopted"
    partial = result["steps"][-1]["receipt"]["response"]["data"]["typing_dispatch"]
    assert partial["action_executed"] is True and partial["text_dispatch"] == "not_started"
    assert result["automatic_retry_allowed"] is False


def test_action_review_options_reach_only_the_focus_click(scene, monkeypatch):
    options = {"action_review": {"opaque": "fixture"}, "action_review_deadline_ns": scene.context["deadline_ns"]}
    result, calls = sequence_scene(scene, monkeypatch, review_options=options)
    assert result["status"] == "completed"
    assert all(calls[0][key] == value for key, value in options.items())
    assert all(not any(key in call for key in options) for call in calls[1:])


def test_sequence_ambiguous_focus_never_types(scene, monkeypatch):
    scene.probabilities[0] = .5
    result, calls = sequence_scene(scene, monkeypatch)
    assert result["status"] == "interrupted" and result["action_executed"] is True
    assert result["completed_steps"] == ["focus"] and result["automatic_retry_allowed"] is False
    assert len(calls) == 1 and len(scene.requests) == 1


def test_partial_text_timeout_never_retypes(scene, monkeypatch):
    result, calls = sequence_scene(scene, monkeypatch, type_timeout=True)
    assert result["status"] == "interrupted" and result["action_executed"] is True
    assert result["completed_steps"] == ["focus"] and result["steps"][-1]["status"] == "result_unknown"
    assert len(calls) == 2 and len(scene.requests) == 1 and result["task_effect_verified"] is None


@pytest.mark.parametrize("fault", ["append", "password", "nonsearch_enter"])
def test_unsupported_visual_input_is_refused_before_focus(scene, fault):
    from app.execution.input_sequence import run_input_sequence
    context = dict(scene.context)
    request = {"field_goal": "Search field", "text": TEXT, "clear_existing": fault != "append", "submit_search": True}
    if fault == "password":
        context["field_kind"] = "password"
    elif fault == "nonsearch_enter":
        context["field_kind"] = "text"
    co = NS(execute_local_step=lambda **kw: pytest.fail("unsupported input must not focus"))
    with pytest.raises(ValueError, match="visual"):
        run_input_sequence(co, {"handle": 10, "process_id": 20}, request,
            field_evidence_mode="visual", visual_field_context=context)
    assert scene.requests == []


def test_one_field_proof_cannot_issue_two_keyboard_capabilities(scene):
    proof = assess(scene)
    keyboard.issue_visual_keyboard_target(proof, "type_text", text=TEXT)
    with pytest.raises(ValueError, match="consumed"):
        keyboard.issue_visual_keyboard_target(proof, "type_text", text=TEXT)


def test_consumed_visual_target_cannot_be_reinstalled(scene):
    target = keyboard.issue_visual_keyboard_target(assess(scene), "type_text", text=TEXT)
    with keyboard.local_keyboard_target_scope(target):
        keyboard.claim_keyboard_target("type_text", {"text": TEXT, "x": 40, "y": 30, "clear_existing": True})
    with pytest.raises(ValueError, match="consumed"):
        with keyboard.local_keyboard_target_scope(target):
            pytest.fail("consumed target reinstalled")


def test_value_cannot_alias_the_focus_after_file_even_with_new_capture_id(scene, monkeypatch):
    s = scene
    copied = deepcopy(s.focus["observation"]["capture"])
    copied["capture_id"] = "forged-new-id"
    s.typed["observation"]["capture"] = copied
    with pytest.raises(ValueError, match="new_after"):
        assess(s, phase="value", reading=bounded_read(s, monkeypatch))
    assert s.requests == []


@pytest.mark.parametrize("unavailable", ["text_field_uia_unavailable", "text_field_control_unavailable"])
def test_roi_ocr_only_reads_current_field_and_preserves_exact_unicode(scene, monkeypatch, unavailable):
    from app.core.ocr_service import ocr_service
    s = scene
    s.context["ocr_enabled"] = True
    monkeypatch.setattr(ocr_service, "_rapid_engine", object())
    monkeypatch.setattr(s.module, "_verify_read_window", lambda *a: None, raising=False)
    monkeypatch.setattr(s.module, "_read_bounded_text", lambda *a: (_ for _ in ()).throw(
        TextFieldReadError(unavailable)))
    def engine(path):
        with Image.open(path) as image:
            assert image.size == (140, 40)
        return "synthetic row"
    monkeypatch.setattr(ocr_service, "_scan_with_rapidocr", engine)
    monkeypatch.setattr(ocr_service, "_parse_matches", lambda raw: [NS(text=TEXT, score=.999)])
    reading = s.module.read_visual_value(frame=s.typed["observation"]["capture"], expected_field=FIELD,
        context=s.context, manager=object())
    proof = assess(s, phase="value", reading=reading)
    assert proof.to_reference()["reading"]["source"] == "roi_ocr"
    assert proof.to_reference()["reading"]["text"] == TEXT and len(s.requests) == 1


@pytest.mark.parametrize("fault", ["multiple_rows", "low_score", "nan"])
def test_ambiguous_roi_ocr_is_not_exact_value_evidence(scene, monkeypatch, fault):
    from app.core.ocr_service import ocr_service
    s = scene
    s.context["ocr_enabled"] = True
    monkeypatch.setattr(ocr_service, "_rapid_engine", object())
    monkeypatch.setattr(s.module, "_verify_read_window", lambda *a: None, raising=False)
    monkeypatch.setattr(s.module, "_read_bounded_text", lambda *a: (_ for _ in ()).throw(
        TextFieldReadError("text_field_uia_unavailable")))
    matches = [NS(text=TEXT, score=float("nan") if fault == "nan" else .8 if fault == "low_score" else .999)]
    if fault == "multiple_rows":
        matches.append(matches[0])
    monkeypatch.setattr(ocr_service, "_scan_with_rapidocr", lambda path: [])
    monkeypatch.setattr(ocr_service, "_parse_matches", lambda raw: matches)
    with pytest.raises(TextFieldReadError, match="value_unavailable"):
        s.module.read_visual_value(frame=s.typed["observation"]["capture"], expected_field=FIELD,
            context=s.context, manager=object())
    assert s.requests == []


@pytest.mark.parametrize("ready", [False, True])
def test_visual_value_lazily_loads_only_target_roi_rapidocr(scene, monkeypatch, ready):
    from app.core.ocr_service import ocr_service
    s = scene
    s.context["ocr_enabled"] = True
    monkeypatch.setattr(s.module, "_read_bounded_text", lambda *a: (_ for _ in ()).throw(
        TextFieldReadError("text_field_uia_unavailable")))
    monkeypatch.setattr(s.module, "_verify_read_window", lambda *a: None)
    calls = []
    def engine(path):
        with Image.open(path) as image:
            assert image.size == (140, 40)
        calls.append("roi_scan")
        return "synthetic", None
    def get():
        calls.append("get_rapidocr")
        ocr_service._rapid_engine = engine
        return engine
    monkeypatch.setattr(ocr_service, "_rapid_engine", engine if ready else None)
    monkeypatch.setattr(ocr_service, "_get_rapidocr_engine", get)
    monkeypatch.setattr(ocr_service, "_scan_with_paddle", lambda *a: pytest.fail("ROI must not load another engine"))
    monkeypatch.setattr(ocr_service, "_parse_matches", lambda raw: [NS(text=TEXT, score=.999)])
    reading = s.module.read_visual_value(frame=s.typed["observation"]["capture"], expected_field=FIELD,
        context=s.context, manager=object())
    reference = reading.reference()
    assert calls == ["get_rapidocr", "roi_scan"]
    assert reference["text"] == TEXT and reference["source"] == "roi_ocr"
    assert reference["evidence"]["engine_reused"] is ready and reference["elapsed_ms"] >= 0
    proof = assess(s, phase="value", reading=reading)
    assert proof.to_reference()["reading"]["text"] == TEXT and len(s.requests) == 1


@pytest.mark.parametrize("failure", ["load", "deadline"])
def test_roi_cold_load_failure_or_expired_deadline_never_reaches_decision(scene, monkeypatch, failure):
    from app.core.ocr_service import ocr_service
    s = scene
    s.context["ocr_enabled"] = True
    monkeypatch.setattr(s.module, "_read_bounded_text", lambda *a: (_ for _ in ()).throw(
        TextFieldReadError("text_field_uia_unavailable")))
    monkeypatch.setattr(s.module, "_verify_read_window", lambda *a: None)
    calls = []
    def get():
        calls.append("load")
        if failure == "load":
            raise RuntimeError("synthetic unavailable engine")
        monkeypatch.setattr(s.module, "perf_counter_ns", lambda: s.context["deadline_ns"] + 1)
        return lambda path: ("synthetic", None)
    monkeypatch.setattr(ocr_service, "_rapid_engine", None)
    monkeypatch.setattr(ocr_service, "_get_rapidocr_engine", get)
    monkeypatch.setattr(ocr_service, "_parse_matches", lambda raw: [NS(text=TEXT, score=.999)])
    with pytest.raises(ValueError, match="value_unavailable" if failure == "load" else "deadline_expired"):
        s.module.read_visual_value(frame=s.typed["observation"]["capture"], expected_field=FIELD,
            context=s.context, manager=object())
    assert calls == ["load"] and s.requests == []


def test_rebuilt_authenticated_proof_cannot_reissue_keyboard_capability(scene):
    s = scene
    proof = assess(s)
    rebuilt = s.module.build_visual_field_proof(phase="focus", focus_receipt=s.focus, input_receipt=None,
        frame=s.focus["observation"]["capture"], assessment=proof.assessment(), expected_field=FIELD, context=s.context)
    keyboard.issue_visual_keyboard_target(proof, "type_text", text=TEXT)
    with pytest.raises(ValueError, match="consumed"):
        keyboard.issue_visual_keyboard_target(rebuilt, "type_text", text=TEXT)


@pytest.mark.parametrize("stop", ["cancelled", "deadline"])
def test_cancel_during_selection_decision_keeps_selection_and_never_pastes(scene, monkeypatch, stop):
    from app.core.input_controller import VK_CONTROL, VK_A, VK_V
    s = scene
    cancelled = [False]
    s.context["cancelled"] = lambda: cancelled[0]
    proof = assess(s)
    target = keyboard.issue_visual_keyboard_target(proof, "type_text", text=TEXT,
        selection_reviewer=lambda original, frame, dispatch: s.module.assess_visual_selection(original, frame=frame, dispatch=dispatch))
    controller, events, _ = controller_scene(s, monkeypatch, selected_change=True)
    s.during.append((lambda: cancelled.__setitem__(0, True)) if stop == "cancelled" else
        lambda: monkeypatch.setattr(s.module, "perf_counter_ns", lambda: s.context["deadline_ns"] + 1))
    with keyboard.local_keyboard_target_scope(target):
        with pytest.raises(ValueError, match=stop):
            controller.type_text(TEXT, x=40, y=30, clear_existing=True)
    assert len(s.requests) == 2 and events.count((VK_CONTROL, VK_A)) == 1
    assert (VK_CONTROL, VK_V) not in events and events[-1] == "clipboard-restored"


@pytest.mark.parametrize("fault", ["geometry", "jpeg"])
def test_selection_fresh_frame_requires_original_png_geometry_before_model(scene, monkeypatch, fault):
    from app.core.input_controller import VK_CONTROL, VK_A, VK_V
    s = scene
    target = keyboard.issue_visual_keyboard_target(assess(s), "type_text", text=TEXT,
        selection_reviewer=lambda original, frame, dispatch: s.module.assess_visual_selection(original, frame=frame, dispatch=dispatch))
    controller, events, captures = controller_scene(s, monkeypatch, selected_change=True)
    maintained_capture = s.module.capture_visual_field_frame
    def invalid_selection(*args, **kwargs):
        frame = maintained_capture(*args, **kwargs)
        if (VK_CONTROL, VK_A) in events:
            path = Path(frame["image_path"])
            Image.new("RGB", (181, 90) if fault == "geometry" else (180, 90), "red").save(
                path, format="JPEG" if fault == "jpeg" else "PNG")
            frame["sha256"] = sha256(path.read_bytes()).hexdigest()
        return frame
    monkeypatch.setattr(s.module, "capture_visual_field_frame", invalid_selection)
    with keyboard.local_keyboard_target_scope(target):
        with pytest.raises(ValueError, match="image_geometry_invalid"):
            controller.type_text(TEXT, x=40, y=30, clear_existing=True)
    assert len(s.requests) == 1 and len(captures) == 1
    assert events.count((VK_CONTROL, VK_A)) == 1 and (VK_CONTROL, VK_V) not in events
    assert events[-1] == "clipboard-restored"


def test_raw_post_action_capture_normalizes_before_bounded_focus_read_and_decision(scene, monkeypatch):
    from dataclasses import replace
    from app.agent.windows_text_field_reader import WindowsTextFieldReader
    s = scene
    original_snapshot = focus_snapshot(s)
    frame = s.focus["observation"]["capture"]
    frame.pop("capture_id")
    frame.pop("window_identity")
    frame.update(frame_id="after_settled", observation_stage="after_render_wait")
    original = deepcopy(frame)
    from app.execution.decision_check import decision_frame
    normalized_id = decision_frame(frame, FIELD["window_identity"], role="after")["capture_id"]
    calls = []
    def read(self, **kwargs):
        calls.append(kwargs)
        return replace(original_snapshot, capture_id=kwargs["capture_id"])
    monkeypatch.setattr(WindowsTextFieldReader, "read_focused_at_point", read)
    snapshot = s.module.read_visual_focus_snapshot(frame=frame, expected_field=FIELD, manager=object())
    assert snapshot.capture_id == normalized_id and calls[0]["capture_id"] == normalized_id
    assert calls[0]["click_point"] == (40, 30) and "target_bbox" not in calls[0]
    proof = assess(s, frame=frame, focus_snapshot=snapshot)
    assert proof.to_reference()["frame"]["capture_id"] == normalized_id
    assert len(s.requests) == 1 and frame == original


@pytest.mark.parametrize("fault", ["hash", "identity"])
def test_focus_capture_integrity_is_checked_before_bounded_reader(scene, monkeypatch, fault):
    from app.agent.windows_text_field_reader import WindowsTextFieldReader
    s = scene
    frame = deepcopy(s.focus["observation"]["capture"])
    frame.pop("capture_id")
    if fault == "hash":
        frame["sha256"] = "0" * 64
    else:
        frame["window_identity"]["handle"] = 11
    monkeypatch.setattr(WindowsTextFieldReader, "read_focused_at_point", lambda *args, **kwargs:
        pytest.fail("invalid capture must not reach the native field reader"))
    with pytest.raises(ValueError, match="capture (hash|window identity) mismatch"):
        s.module.read_visual_focus_snapshot(frame=frame, expected_field=FIELD, manager=object())
    assert s.requests == []


@pytest.fixture
def unresolved_control_reader(monkeypatch):
    from app.agent import windows_text_field_reader as reader_module
    calls = []
    def unavailable():
        calls.append("focused")
        raise TextFieldReadError("text_field_control_unavailable")
    monkeypatch.setattr(reader_module, "_focused_field", unavailable)
    monkeypatch.setattr(reader_module, "_desktop_factory", lambda **kwargs:
        pytest.fail("post-click reading must not scan or use from_point"))
    monkeypatch.setattr(reader_module.WindowsTextFieldReader, "_verify_binding", lambda *a: None)
    return calls


def test_unresolved_control_visual_focus_uses_existing_authenticated_decision(
        scene, monkeypatch, unresolved_control_reader):
    s = scene
    snapshot = s.module.read_visual_focus_snapshot(frame=s.focus["observation"]["capture"],
        expected_field=FIELD, manager=object())
    assert snapshot is None and unresolved_control_reader == ["focused"]
    proof = assess(s, focus_snapshot=snapshot)
    assert proof.to_reference()["phase"] == "focus" and len(s.requests) == 1
    assert "focus_value_snapshot" not in proof.request()["action"]


def test_unresolved_control_visual_value_without_ocr_stays_unavailable(scene, unresolved_control_reader):
    s = scene
    with pytest.raises(TextFieldReadError, match="visual_field_value_unavailable"):
        s.module.read_visual_value(frame=s.typed["observation"]["capture"], expected_field=FIELD,
            context=s.context, manager=object())
    assert s.requests == [] and unresolved_control_reader == ["focused"]


@pytest.mark.parametrize("negative", ["readonly", "password", "disabled", "window"])
def test_visual_focus_known_negative_still_blocks_before_decision(scene, monkeypatch, negative):
    s = scene
    reason = "text_field_window_or_process_changed" if negative == "window" else "text_field_target_not_writable"
    def reject(*args):
        raise TextFieldReadError(reason, diagnostic={"check": negative})
    monkeypatch.setattr(s.module, "_read_bounded_text", reject)
    with pytest.raises(TextFieldReadError, match=reason):
        s.module.read_visual_focus_snapshot(frame=s.focus["observation"]["capture"],
            expected_field=FIELD, manager=object())
    assert s.requests == []


@pytest.fixture
def native_point_field(scene, monkeypatch):
    from app.agent import native_identity, windows_text_field_reader as reader
    s = scene
    expected = deepcopy(FIELD)
    state = NS(origin=(0, 0), focused=True, enabled=True, password=False, readonly=False,
        root=10, bbox=(20, 20, 100, 20), runtime=[42, 1], text="old", hits=[], focus_reads=[])
    element = NS(CurrentIsPassword=False)
    info = NS(element=element, handle=10, process_id=20, runtime_id=state.runtime, control_type="Edit")
    wrapper = NS(element_info=info, is_visible=lambda: True, is_enabled=lambda: state.enabled,
        has_keyboard_focus=lambda: state.focused)
    wrapper.top_level_parent = lambda: wrapper
    class MissingPattern(Exception):
        pass
    class ValuePattern:
        @property
        def CurrentIsReadOnly(self):
            return state.readonly
        @property
        def CurrentValue(self):
            return state.text
    class Field:
        element_info = info
        iface_value = ValuePattern()
        is_visible = wrapper.is_visible
        is_enabled = wrapper.is_enabled
        has_keyboard_focus = wrapper.has_keyboard_focus
        top_level_parent = wrapper.top_level_parent
        @property
        def iface_text(self):
            raise MissingPattern()
    field = Field()
    field.is_visible = lambda: True
    field.is_enabled = lambda: state.enabled
    field.has_keyboard_focus = lambda: state.focused
    field.top_level_parent = lambda: wrapper
    def focused():
        state.focus_reads.append(1)
        ox, oy = state.origin
        bx, by, bw, bh = state.bbox
        info.rectangle = NS(left=ox+bx, top=oy+by, right=ox+bx+bw, bottom=oy+by+bh)
        info.runtime_id = list(state.runtime)
        element.CurrentIsPassword = state.password
        element.CurrentHasKeyboardFocus = state.focused
        info.handle = state.root
        return field
    monkeypatch.setattr(reader, "_focused_field", focused)
    monkeypatch.setattr(reader, "_desktop_factory", lambda **kwargs:
        pytest.fail("coarse point Pane must not replace the current focused Edit"))
    monkeypatch.setattr(reader, "_native_root_handle", lambda handle: handle if handle in {10, 11} else None)
    monkeypatch.setattr(reader, "_no_pattern_exception", lambda: MissingPattern)
    monkeypatch.setattr(native_identity.WindowsNativeIdentityReader, "read_identity", lambda *a: deepcopy(NATIVE))
    def bound():
        x, y = state.origin
        return NS(handle=10, process_id=20, rect=NS(left=x, top=y, right=x+180, bottom=y+90))
    manager = NS(get_bound_window=bound)
    return NS(state=state, manager=manager, expected=expected)


@pytest.mark.parametrize("origin", [(0, 0), (100, 200)])
def test_visual_native_point_binds_smaller_edit_without_shrinking_decision_region(scene, native_point_field, origin):
    s, n = scene, native_point_field
    n.state.origin = origin
    n.expected["window_rect"] = [*origin, 180, 90]
    s.focus["target_window_geometry"]["rect"] = [origin[0], origin[1], origin[0]+180, origin[1]+90]
    snapshot = s.module.read_visual_focus_snapshot(frame=s.focus["observation"]["capture"],
        expected_field=n.expected, manager=n.manager)
    assert snapshot.identity.control_bbox == (20, 20, 100, 20)
    assert n.state.hits == [] and n.state.focus_reads == [1, 1]
    proof = s.module.assess_visual_field(phase="focus", focus_receipt=s.focus, input_receipt=None,
        frame=s.focus["observation"]["capture"], expected_field=n.expected,
        context=s.context, focus_snapshot=snapshot)
    action = proof.request()["action"]
    assert action["field"]["bbox"] == {"x": 10, "y": 10, "w": 140, "h": 40}
    assert action["focus_value_snapshot"]["identity"]["control_bbox"] == [20, 20, 100, 20]
    assert len(s.requests) == 1


@pytest.mark.parametrize("fault,reason", [
    ("focus", "keyboard_focus_unavailable"), ("password", "target_not_writable"),
    ("readonly", "target_not_writable"), ("disabled", "target_not_writable"),
    ("window", "window_or_process_changed"), ("point", "geometry_changed"),
])
def test_visual_native_point_preserves_known_negative_refusals(scene, native_point_field, fault, reason):
    s, n = scene, native_point_field
    n.state.bbox = (10, 10, 140, 40)
    if fault == "focus":
        n.state.focused = False
    elif fault == "password":
        n.state.password = True
    elif fault == "readonly":
        n.state.readonly = True
    elif fault == "disabled":
        n.state.enabled = False
    elif fault == "window":
        n.state.root = 11
    else:
        n.state.bbox = (50, 20, 100, 20)
    with pytest.raises(TextFieldReadError, match=reason):
        s.module.read_visual_focus_snapshot(frame=s.focus["observation"]["capture"],
            expected_field=n.expected, manager=n.manager)
    assert s.requests == []


def test_visual_focus_proof_accepts_native_field_containing_original_point(scene):
    from dataclasses import replace
    s = scene
    snapshot = focus_snapshot(s)
    snapshot = replace(snapshot, identity=replace(snapshot.identity, control_bbox=(20, 20, 100, 20)))
    proof = assess(s, focus_snapshot=snapshot)
    assert proof.request()["action"]["field"]["bbox"] == {"x": 10, "y": 10, "w": 140, "h": 40}
    assert len(s.requests) == 1


@pytest.mark.parametrize("mode", ["raw", "redacted", "both"])
def test_typed_receipt_text_binding_accepts_real_audit_request_without_mutation(scene, monkeypatch, mode):
    from app.execution.local_direct_step import _audit_request
    s = scene
    original = deepcopy(s.typed["request"])
    if mode != "raw":
        s.typed["request"] = _audit_request(original)
        assert s.typed["request"]["text_length"] == len(TEXT)
        assert s.typed["request"]["text_sha256"] == sha256(TEXT.encode("utf-8")).hexdigest()
        assert "text" not in s.typed["request"]
        if mode == "both":
            s.typed["request"]["text"] = TEXT
    before = deepcopy(s.typed)
    proof = assess(s, phase="value", reading=bounded_read(s, monkeypatch))
    assert proof.to_reference()["phase"] == "value" and len(s.requests) == 1
    assert s.typed == before and original["text"] == TEXT
    if mode == "redacted":
        assert "text" not in s.typed["request"]


@pytest.mark.parametrize("fault", ["missing", "length_missing", "hash_missing", "bool_length", "wrong_length",
    "wrong_hash", "hash_type", "raw_conflict", "both_hash_conflict", "both_length_conflict"])
def test_typed_receipt_text_binding_rejects_missing_malformed_or_conflicting_summary(scene, monkeypatch, fault):
    from app.execution.local_direct_step import _audit_request
    s = scene
    s.typed["request"] = _audit_request(s.typed["request"])
    command = s.typed["request"]
    if fault == "missing":
        command.pop("text_length")
        command.pop("text_sha256")
    elif fault == "length_missing": command.pop("text_length")
    elif fault == "hash_missing": command.pop("text_sha256")
    elif fault == "bool_length": command["text_length"] = True
    elif fault == "wrong_length": command["text_length"] = len(TEXT.encode("utf-8"))
    elif fault == "wrong_hash": command["text_sha256"] = "0" * 64
    elif fault == "hash_type": command["text_sha256"] = True
    elif fault == "raw_conflict": command["text"] = TEXT + "changed"
    else:
        command["text"] = TEXT
        if fault == "both_hash_conflict": command["text_sha256"] = "0" * 64
        else: command["text_length"] = len(TEXT) + 1
    before = deepcopy(s.typed)
    with pytest.raises(ValueError, match="visual_field_input_binding_invalid"):
        assess(s, phase="value", reading=bounded_read(s, monkeypatch))
    assert s.requests == [] and s.typed == before


@pytest.mark.parametrize("fault", [None, "value", "identity"])
def test_empty_native_value_needs_no_visible_selection_review(scene, monkeypatch, fault):
    from dataclasses import replace
    from app.core.input_controller import VK_CONTROL, VK_A, VK_V
    s = scene
    target = keyboard.issue_visual_keyboard_target(
        assess(s, focus_snapshot=focus_snapshot(s, text="", selection=None)),
        "type_text", text=TEXT, selection_reviewer=lambda *a: pytest.fail("empty native value needs no selection model"))
    controller, events, _ = controller_scene(s, monkeypatch)
    def read(frame, *args):
        selected = (VK_CONTROL, VK_A) in events
        snapshot = focus_snapshot(s, text="changed" if selected and fault == "value" else "",
            selection=None, runtime_id=(8, 9) if selected and fault == "identity" else (1, 2))
        return replace(snapshot, capture_id=frame["capture_id"])
    monkeypatch.setattr(s.module, "_read_bounded_text", read)
    with keyboard.local_keyboard_target_scope(target):
        if fault is None:
            assert controller.type_text(TEXT, x=40, y=30, clear_existing=True)["typed"] is True
        else:
            with pytest.raises(ValueError, match="native_changed|selection"):
                controller.type_text(TEXT, x=40, y=30, clear_existing=True)
    assert len(s.requests) == 1
    assert events.count((VK_CONTROL, VK_A)) == 1
    assert events.count((VK_CONTROL, VK_V)) == int(fault is None)
