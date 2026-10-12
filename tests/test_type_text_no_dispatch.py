"""真实键入派发记录经本地路由认证；不派发桌面输入。"""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from app.desktop_review import local_direct_step as direct
from app.core.recognition_dispatch import local_receipt_zero_input_verified
from tests.test_local_step_timings import timed_scene
from tests.test_text_input_guard import ClipboardSession, prepared


_POST_ACTION = direct._post_action
REQUEST = {"text": "fresh text", "x": 70, "y": 80,
           "click_before_typing": False, "clear_existing": True}


@pytest.fixture
def route(timed_scene, monkeypatch, tmp_path):
    from app.api import action
    from app.core import input_controller as inputs
    controller, bound, events, clipboard = prepared(monkeypatch)
    bound.handle, bound.process_id = 321, 12
    bound.rect.right, bound.rect.bottom = 800, 600
    co = timed_scene[0]
    manager = co._windows()
    manager.get_bound_window = lambda: bound
    monkeypatch.setattr(action, "window_manager", manager)
    monkeypatch.setattr(action, "input_controller", controller)
    monkeypatch.setattr(action, "write_trace", lambda **kw: str(tmp_path / "trace.json"))
    monkeypatch.setattr(direct, "_post_action", _POST_ACTION)
    state = SimpleNamespace(failure="before", reads=0, mutate=None, response=None)

    def verify(*args, **kwargs):
        state.reads += 1
        if state.failure == "before" or state.failure == "after_selection" and state.reads == 2:
            raise ValueError("visual_field_fresh_proof_required")

    def chord(keys):
        events.append(tuple(keys))
        if state.failure == "selection_started" and keys == [inputs.VK_CONTROL, inputs.VK_A]:
            raise RuntimeError("selection_interrupted")
        if state.failure == "paste_started" and keys == [inputs.VK_CONTROL, inputs.VK_V]:
            raise RuntimeError("paste_interrupted")

    class RestoreFailure(ClipboardSession):
        def __exit__(self, *exception):
            super().__exit__(*exception)
            if state.failure == "paste_completed":
                raise RuntimeError("restore_failed")

    monkeypatch.setattr(controller, "_verify_text_target", verify)
    monkeypatch.setattr(controller, "_press_chord", chord)
    monkeypatch.setattr(controller, "_clipboard_text_transaction", lambda *a, **kw: RestoreFailure(events))

    def post(operation, request, manager):
        response = _POST_ACTION(operation, request, manager)
        state.response = response
        if state.mutate is not None:
            state.mutate(response)
        return response

    monkeypatch.setattr(direct, "_post_action", post)

    def run(**changes):
        return co.execute_local_step(target_window_handle=321, target_process_id=12,
            operation="type_text", request={**REQUEST, **changes})

    return SimpleNamespace(run=run, state=state, events=events, coordinator=co, manager=manager)


def test_first_keyboard_rejection_is_verified_zero_input_and_survives_json(route):
    receipt = route.run()
    assert receipt["response"]["success"] is False
    assert receipt["response"]["data"]["typing_dispatch"]["events"] == []
    assert receipt["phase"] == "not_dispatched"
    assert receipt["action_executed"] is False
    assert local_receipt_zero_input_verified(receipt, "type_text")
    assert local_receipt_zero_input_verified(json.loads(json.dumps(receipt)), "type_text")
    assert not any(isinstance(item, tuple) for item in route.events)


@pytest.mark.parametrize("failure,clear_existing,executed", [
    ("selection_started", True, None), ("after_selection", True, True),
    ("paste_started", False, None), ("paste_completed", False, True)])
def test_partial_selection_or_paste_never_becomes_zero(route, failure, clear_existing, executed):
    route.state.failure = failure
    receipt = route.run(clear_existing=clear_existing)
    assert receipt["phase"] == "result_unknown"
    assert receipt["response"]["data"]["execution_path"]["action_executed"] is executed
    assert not local_receipt_zero_input_verified(receipt, "type_text")


def test_arbitrary_response_dictionary_cannot_get_same_call_attestation(route, monkeypatch):
    original = route.run()
    response = json.loads(json.dumps(original["response"]))
    monkeypatch.setattr(direct, "_post_action", lambda *a: deepcopy(response))
    forged = route.run()
    assert forged["phase"] == "result_unknown"
    assert not local_receipt_zero_input_verified(forged, "type_text")


def test_unconsumed_original_route_response_cannot_be_replayed_in_another_local_call(route, monkeypatch):
    response = _POST_ACTION('type_text', direct._validated_request('type_text', REQUEST), route.manager)
    monkeypatch.setattr(direct, '_post_action', lambda *a: response)
    replayed = route.run()
    assert replayed['phase'] == 'result_unknown'
    assert not local_receipt_zero_input_verified(replayed, 'type_text')


@pytest.mark.parametrize("damage", ["missing_dispatch", "events", "started", "executed", "point",
                                      "window", "viewport", "length"])
def test_live_response_mutation_does_not_downgrade_unknown_to_zero(route, damage):
    def mutate(response):
        data = response["data"]
        if damage == "missing_dispatch": data.pop("typing_dispatch")
        elif damage == "events": data["typing_dispatch"]["events"] = [{"phase": "selection", "status": "started"}]
        elif damage == "started": data["input_started"] = True
        elif damage == "executed": data["execution_path"]["action_executed"] = True
        elif damage == "point": data["point"]["x"] += 1
        elif damage == "window": data["operation_context"]["window_binding_id"] = "window:999"
        elif damage == "viewport": data["operation_context"]["viewport_size"]["width"] += 1
        else: data["text_length"] += 1
    route.state.mutate = mutate
    receipt = route.run()
    assert receipt["phase"] == "result_unknown"
    assert not local_receipt_zero_input_verified(receipt, "type_text")


@pytest.mark.parametrize("damage", ["request", "identity", "geometry", "proof", "response", "returned"])
def test_persisted_zero_input_proof_rejects_changed_binding(route, damage):
    receipt = json.loads(json.dumps(route.run()))
    if damage == "request": receipt["request"]["text_sha256"] = "f" * 64
    elif damage == "identity": receipt["target_identity"]["process_create_time"] += 1
    elif damage == "geometry": receipt["target_window_geometry"]["rect"][2] += 1
    elif damage == "proof": receipt.pop("type_text_no_dispatch", None)
    elif damage == "returned": receipt.update(phase='returned', type_text_no_dispatch=None)
    else: receipt["response"]["data"]["typing_dispatch"]["text_dispatch"] = "started"
    assert not local_receipt_zero_input_verified(receipt, "type_text")


def test_sequence_keeps_completed_focus_input_and_classifies_only_type_as_not_dispatched(route, monkeypatch):
    from app.agent.text_field_evidence import TextFieldIdentity, TextFieldSnapshot
    from app.desktop_review import input_sequence as sequence
    from tests.test_input_sequence import Coordinator
    original = route.coordinator.execute_local_step

    class SequenceCoordinator(Coordinator):
        def execute_local_step(self, **kwargs):
            if kwargs["operation"] == "type_text":
                return original(**kwargs)
            return super().execute_local_step(**kwargs)

    identity = TextFieldIdentity("field", 321, 12, 123.5, (1,), (0, 0, 800, 600), (1, 1, 300, 120))
    monkeypatch.setattr(sequence, "_read_field", lambda *a, **kw:
        TextFieldSnapshot(identity, "capture", "before", 1, "uia_value", "old", None))
    monkeypatch.setattr(sequence, "_focus_field_binding", lambda *a: {
        "control_type": "Edit", "runtime_id": [1], "bbox": {"x": 1, "y": 1, "w": 300, "h": 120}})
    result = sequence.run_input_sequence(SequenceCoordinator(), {"handle": 321, "process_id": 12},
        {"field_goal": "Fresh field", "text": REQUEST["text"], "submit_search": False})
    assert result["status"] == "interrupted" and result["action_executed"] is True
    assert result["completed_steps"] == ["focus"]
    assert result.get("error", {}).get("code") == "type_input_not_confirmed", result.get("error")
    assert result["steps"][0]["action_executed"] is True
    assert result["steps"][1]["status"] == "not_dispatched"
    assert result["steps"][1]["action_executed"] is False
    assert result["automatic_retry_allowed"] is False
