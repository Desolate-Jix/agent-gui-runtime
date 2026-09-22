"""表单编排真实分支回归；只替换桌面执行与 UIA 读取边界。"""
from copy import deepcopy
from types import SimpleNamespace
import sys

import pytest

from app.agent.text_field_evidence import TextFieldIdentity, TextFieldSnapshot
from app.desktop_review import input_sequence


TARGET = {"handle": 1, "process_id": 2}
IDENTITY = {"target_window_handle": 1, "process_id": 2}


def module():
    from app.desktop_review import form_fill
    return form_fill


class Coordinator:
    def __init__(self, *, fail_at=None, missing_image=None, dispatched=True):
        self.calls = []
        self.fail_at = fail_at
        self.missing_image = missing_image
        self.dispatched = dispatched

    def execute_local_step(self, **kwargs):
        self.calls.append(kwargs)
        index = len(self.calls)
        if index == self.fail_at:
            raise RuntimeError("dispatch failed")
        data = {"execution_path": {"action_executed": self.dispatched},
            "selected_click_point": {"x": 10, "y": 35 if kwargs["request"].get("goal", "").startswith("Click the option") else 20},
            "selected_click_point_coordinate_space": "capture_image_pixels"}
        return {"phase": "returned", "capture": {"sha256": f"before-{index}"},
            "target_identity": IDENTITY,
            "response": {"success": True, "data": {"result": data}},
            "observation": {"status": "unavailable"} if self.missing_image == index else
                {"status": "captured", "capture": {"sha256": f"after-{index}"}}}


def control(*, label="Remember", kind="checkbox", checked=False, value=None, options=None,
            runtime_id=None, state_available=True, **changes):
    return {"source": "windows_uia", "runtime_id": [1, 3] if runtime_id is None else runtime_id,
        "bbox": {"x": 1, "y": 2, "w": 20, "h": 20}, "window_identity": IDENTITY,
        "window_rect": [0, 0, 800, 600], "kind": kind, "label": label, "value": value,
        "checked": checked, "options": options or [], "state_available": state_available,
        **({"expanded": bool(options)} if kind == "dropdown" else {}),
        **changes}


class ReadError(ValueError):
    def __init__(self, reason_code):
        self.reason_code = reason_code
        super().__init__(reason_code)


def reader(monkeypatch, *answers):
    pending = iter(answers)
    calls = []

    def read(coordinator, target, label, kind, *, expected_runtime_id=None):
        calls.append({"label": label, "kind": kind, "expected_runtime_id": expected_runtime_id})
        answer = next(pending)
        if isinstance(answer, Exception):
            raise answer
        return deepcopy(answer)

    monkeypatch.setitem(sys.modules, "app.agent.windows_form_control_reader",
        SimpleNamespace(read_form_control=read, FormControlReadError=ReadError))
    return calls


def text_reader(monkeypatch, *values):
    pending = iter(values)

    def read(coordinator, target, point, capture, field_id, expected_identity):
        value = next(pending)
        identity = TextFieldIdentity(field_id, 1, 2, 100.0, (1,),
            (0, 0, 800, 600), (1, 1, 300, 40))
        return TextFieldSnapshot(identity, capture["sha256"], "read", 1, "uia_value", value, None)

    monkeypatch.setattr(input_sequence, "_read_field", read)


def run(coordinator, *fields, **kwargs):
    return module().run_form_fill(coordinator, TARGET, {"fields": list(fields)}, **kwargs)


CHECK = {"kind": "checkbox", "label": "Remember", "checked": True}
TEXT = {"kind": "text", "field_goal": "Name", "text": "Ada"}
DROP = {"kind": "dropdown", "label": "Country", "option": "NZ"}
RADIO = {"kind": "radio", "label": "Email"}


@pytest.mark.parametrize("payload", [
    {"fields": []}, {"fields": [CHECK] * 13}, {"fields": [CHECK], "submit": True},
    {"fields": [{**CHECK, "checked": "true"}]}, {"fields": [{**CHECK, "label": "  "}]},
    {"fields": [{**CHECK, "label": "a" * 501}]}, {"fields": [{**TEXT, "text": " "}]},
    {"fields": [{**TEXT, "text": "a" * 20001}]}, {"fields": [{**TEXT, "field_goal": "\n"}]},
    {"fields": [{**TEXT, "submit_search": True}]}, {"fields": [{**TEXT, "clear_existing": 1}]},
    {"fields": [{**DROP, "option": ""}]}, {"fields": [{**RADIO, "checked": False}]},
    {"fields": [{"kind": "submit", "label": "Submit"}]},
])
def test_strict_bounded_request_rejects_before_input(payload):
    co = Coordinator()
    with pytest.raises(ValueError):
        module().run_form_fill(co, TARGET, payload)
    assert not co.calls


def test_missing_target_is_rejected():
    with pytest.raises(ValueError):
        module().run_form_fill(Coordinator(), None, {"fields": [CHECK]})


def test_mixed_fields_execute_in_order_without_enter_and_keep_receipts(monkeypatch):
    co = Coordinator()
    text_reader(monkeypatch, "", "Ada")
    reads = reader(monkeypatch, control(), control(checked=True),
        control(kind="radio", label="Email"), control(kind="radio", label="Email", checked=True))
    progress = []
    result = run(co, TEXT, CHECK, RADIO, persist=lambda value: progress.append(deepcopy(value)))
    assert result["status"] == "completed"
    assert result["completed_fields"] == [0, 1, 2] and result["interrupted_at"] is None
    assert [x["operation"] for x in co.calls] == ["execute_recognition_plan", "type_text",
        "execute_recognition_plan", "execute_recognition_plan"]
    assert all("key" not in x["request"] for x in co.calls)
    assert result["capture"]["sha256"] == "before-1"
    assert result["observation"]["capture"]["sha256"] == "after-4"
    assert result["fields"][0]["check"]["status"] == "matched"
    assert all(x["check"]["status"] == "matched" for x in result["fields"])
    assert reads[1]["expected_runtime_id"] == [1, 3]
    assert result["task_effect_verified"] is None and result["automatic_retry_allowed"] is False
    assert result["action_executed"] is True
    assert any(p["fields"][-1]["steps"][-1]["status"] == "dispatching"
        for p in progress if p["fields"] and p["fields"][-1]["steps"])


@pytest.mark.parametrize("field,snapshot", [
    (CHECK, control(checked=True)),
    ({**CHECK, "checked": False}, control(checked=False)),
    (RADIO, control(kind="radio", label="Email", checked=True)),
    (DROP, control(kind="dropdown", label="Country", value="NZ")),
])
def test_already_satisfied_fields_never_toggle(monkeypatch, field, snapshot):
    co = Coordinator()
    reader(monkeypatch, snapshot)
    result = run(co, field)
    assert result["status"] == "completed" and result["completed_fields"] == [0]
    assert not co.calls and result["action_executed"] is False
    assert result["fields"][0]["check"]["already_satisfied"] is True


@pytest.mark.parametrize("field", [CHECK, RADIO])
@pytest.mark.parametrize("snapshot", [control(checked=None), control(state_available=False)])
def test_unknown_toggle_state_stops_without_click(monkeypatch, field, snapshot):
    co = Coordinator()
    reader(monkeypatch, {**snapshot, "kind": field["kind"], "label": field["label"]})
    result = run(co, field, TEXT)
    assert result["error"]["code"] == "form_control_state_unavailable"
    assert result["status"] == "interrupted" and not co.calls
    assert result["interrupted_at"] == 0 and len(result["fields"]) == 1


def option(label="NZ", selected=False):
    return {"label": label, "bbox": {"x": 1, "y": 30, "w": 80, "h": 20},
        "runtime_id": [1, 3, 4], "selected": selected}


@pytest.mark.parametrize("selected_value,selected", [("NZ", False), (None, True)])
def test_dropdown_selects_unique_scoped_option_then_verifies(monkeypatch, selected_value, selected):
    co = Coordinator()
    before = control(kind="dropdown", label="Country", value="AU")
    reads = reader(monkeypatch, before, {**before, "options": [option()], "expanded": True},
        {**before, "value": selected_value, "options": [option(selected=selected)]})
    result = run(co, DROP)
    assert result["status"] == "completed" and len(co.calls) == 2
    assert all(x["operation"] == "execute_recognition_plan" for x in co.calls)
    assert all(x["request"]["click_kind"] == "single" for x in co.calls)
    assert '"Country"' in co.calls[1]["request"]["goal"]
    assert '"NZ"' in co.calls[1]["request"]["goal"]
    assert all(x["expected_runtime_id"] == [1, 3] for x in reads[1:])
    assert result["observation"]["capture"]["sha256"] == "after-2"


@pytest.mark.parametrize("options,reason", [([], "form_option_not_visible"),
    ([option(), option()], "form_option_ambiguous"),
    ([option("nz")], "form_option_not_visible")])
def test_missing_or_duplicate_option_stops_after_open(monkeypatch, options, reason):
    co = Coordinator()
    before = control(kind="dropdown", label="Country", value="AU")
    reader(monkeypatch, before, {**before, "options": options, "expanded": True})
    result = run(co, DROP, TEXT)
    assert result["error"]["code"] == reason and len(co.calls) == 1
    assert result["completed_fields"] == [] and len(result["fields"]) == 1
    assert result["observation"]["capture"]["sha256"] == "after-1"


@pytest.mark.parametrize("changes,reason", [
    ({"runtime_id": [9]}, "form_control_runtime_id_changed"),
    ({"window_identity": {"process_id": 4}}, "form_control_window_identity_changed"),
    ({"window_rect": [1, 2, 300, 400]}, "form_control_window_rect_changed"),
    ({"checked": False}, "form_control_state_mismatch"),
])
def test_changed_field_or_failed_state_interrupts_after_one_click(monkeypatch, changes, reason):
    co = Coordinator()
    reader(monkeypatch, control(), control(checked=True, **changes) if "checked" not in changes
        else control(**changes))
    result = run(co, CHECK, TEXT)
    assert result["error"]["code"] == reason
    assert result["action_executed"] is True and len(co.calls) == 1


def test_reader_reason_is_preserved(monkeypatch):
    co = Coordinator()
    reader(monkeypatch, ReadError("form_control_target_changed"))
    result = run(co, CHECK)
    assert result["error"]["code"] == "form_control_target_changed"
    assert not co.calls


@pytest.mark.parametrize("fail_at,expected_completed,expected_action", [(1, [], None), (2, [0], True)])
def test_failed_click_keeps_partial_state_and_drops_old_after(monkeypatch, fail_at, expected_completed, expected_action):
    co = Coordinator(fail_at=fail_at)
    reader(monkeypatch, control(), control(checked=True), control())
    result = run(co, CHECK, CHECK, TEXT)
    assert result["status"] == "interrupted" and result["completed_fields"] == expected_completed
    assert result["action_executed"] is expected_action
    assert result["observation"].get("capture") is None
    assert result["fields"][-1]["steps"][-1]["status"] == "result_unknown"
    assert len(co.calls) == fail_at


def test_text_partial_unknown_reuses_real_sequence_and_stops_later_fields(monkeypatch):
    co = Coordinator(fail_at=2)
    text_reader(monkeypatch, "")
    progress = []
    result = run(co, TEXT, CHECK, persist=lambda value: progress.append(deepcopy(value)))
    assert result["status"] == "interrupted" and result["interrupted_at"] == 0
    assert result["fields"][0]["steps"][-1]["status"] == "result_unknown"
    assert result["fields"][0]["error"]["code"] == "input_sequence_failed"
    assert result["observation"].get("capture") is None
    assert result["capture"]["sha256"] == "before-1"
    assert result["action_executed"] is True and len(co.calls) == 2
    assert any(p["fields"][0]["steps"][-1]["name"] == "type"
        and p["fields"][0]["steps"][-1]["status"] == "dispatching"
        for p in progress if p["fields"] and p["fields"][0]["steps"])


@pytest.mark.parametrize("dispatched,missing_image,reason", [(False, None, "form_input_not_confirmed"),
    (True, 1, "form_observation_unavailable"), (None, None, "form_input_not_confirmed")])
def test_dispatch_and_after_are_required_before_state_read(monkeypatch, dispatched, missing_image, reason):
    co = Coordinator(dispatched=dispatched, missing_image=missing_image)
    reads = reader(monkeypatch, control())
    result = run(co, CHECK)
    assert result["error"]["code"] == reason and len(reads) == 1
    assert result["action_executed"] is dispatched


def test_goal_quotes_labels_as_data(monkeypatch):
    co = Coordinator()
    label = 'Remember "this"\nfield'
    reader(monkeypatch, control(label=label), control(label=label, checked=True))
    result = run(co, {**CHECK, "label": label})
    assert result["status"] == "completed"
    assert '\\"this\\"\\n' in co.calls[0]["request"]["goal"]


def test_real_native_identity_shape_is_compatible_with_local_receipt(monkeypatch):
    from app.agent.native_identity import validate_native_identity_fact
    identity = validate_native_identity_fact({
        "contract_version": "windows_native_identity_observation_v1",
        "provider": "windows_native_identity", "status": "observed",
        "target_window_handle": 1, "process_id": 2, "process_create_time": 100.0,
        "executable_path": "C:\\Windows\\System32\\notepad.exe"},
        target_window_handle=1, expected_process_id=2)

    class NativeReceiptCoordinator(Coordinator):
        def execute_local_step(self, **kwargs):
            receipt = super().execute_local_step(**kwargs)
            receipt["target_identity"] = identity
            return receipt

    reader(monkeypatch, control(window_identity=identity), control(checked=True, window_identity=identity))
    assert run(NativeReceiptCoordinator(), CHECK)["status"] == "completed"


def test_later_window_read_failure_does_not_publish_old_after_as_current(monkeypatch, tmp_path):
    import json
    from app.instant_mcp import InstantSession
    reader(monkeypatch, control(), control(checked=True), ReadError("form_control_window_mismatch"))
    result = run(Coordinator(), CHECK, RADIO)
    assert result["status"] == "interrupted" and result["completed_fields"] == [0]
    session = InstantSession(tmp_path, tmp_path, tmp_path)
    session.session = tmp_path
    responses = tmp_path / "responses"
    responses.mkdir()
    (responses / "form-read-failure.json").write_text(json.dumps({"status": "returned", "result": result,
        "observation": result["observation"].get("capture")}), encoding="utf-8")
    receipt = session.result("form-read-failure")
    assert receipt["operation_succeeded"] is False
    assert receipt["agent_review"]["after"]["available"] is False
    assert result["fields"][0]["steps"][0]["receipt"]["observation"]["capture"]["sha256"] == "after-1"


@pytest.mark.parametrize("field,snapshot,reason", [
    (CHECK, control(checked=None, state_available=False), "form_control_state_unavailable"),
    (DROP, control(kind="dropdown", label="Country", value="AU", expanded=None),
        "form_control_expansion_unavailable"),
])
def test_later_unknown_state_clears_top_after_but_preserves_partial_evidence(monkeypatch, field, snapshot, reason):
    co = Coordinator()
    reader(monkeypatch, control(), control(checked=True), snapshot)
    progress = []
    result = run(co, CHECK, field, TEXT, persist=lambda value: progress.append(deepcopy(value)))
    assert result["error"]["code"] == reason and result["interrupted_at"] == 1
    assert result["completed_fields"] == [0] and result["action_executed"] is True
    assert len(co.calls) == 1 and len(result["fields"]) == 2
    assert result["observation"]["status"] == "unavailable"
    assert result["observation"].get("capture") is None
    assert result["observation"]["error_code"] == reason
    assert result["fields"][1]["check"] == {"status": "unavailable", "reason": reason}
    assert result["fields"][0]["steps"][0]["receipt"]["observation"]["capture"]["sha256"] == "after-1"
    assert progress[-1]["observation"] == result["observation"]


def test_dropdown_outside_scoped_option_click_cannot_be_declared_completed(monkeypatch):
    class OutsideOptionCoordinator(Coordinator):
        def execute_local_step(self, **kwargs):
            receipt = super().execute_local_step(**kwargs)
            if len(self.calls) == 2:
                receipt["response"]["data"]["result"]["selected_click_point"] = {"x": 700, "y": 500}
            return receipt

    before = control(kind="dropdown", label="Country", value="AU")
    # 同名选项的 UIA 范围为 (1,30,80,20)；事后字段值变化不能证明窗口其他位置的点击安全。
    reader(monkeypatch, before, {**before, "options": [option()], "expanded": True}, {**before, "value": "NZ"})
    result = run(OutsideOptionCoordinator(), DROP)
    assert result["status"] == "interrupted"


@pytest.mark.parametrize("field,answers,count", [
    (CHECK, [control(), control(checked=True)], 1),
    (RADIO, [control(kind="radio", label="Email"), control(kind="radio", label="Email", checked=True)], 1),
    (DROP, [control(kind="dropdown", label="Country", value="AU"),
        control(kind="dropdown", label="Country", value="AU", options=[option()]),
        control(kind="dropdown", label="Country", value="NZ")], 2),
])
def test_every_choice_action_binds_internal_target_not_public_metadata(monkeypatch, field, answers, count):
    co = Coordinator()
    reader(monkeypatch, *answers)
    run(co, field)
    assert len(co.calls) == count
    assert all(call.get("control_target") is not None for call in co.calls)
    assert all(set(call["request"]) == {"goal", "click_kind"} for call in co.calls)


def test_choice_state_changing_during_recognition_rejects_without_toggle(monkeypatch):
    from app.core.local_control_target import LocalControlTargetError

    class GuardedCoordinator(Coordinator):
        def execute_local_step(self, **kwargs):
            try:
                kwargs["control_target"]({"x": 10, "y": 20})
            except LocalControlTargetError as error:
                return {"phase": "result_unknown", "response": {"success": False,
                    "data": {"execution_path": {"action_executed": False},
                        "control_target_check": {"status": "rejected", "error_code": error.reason_code}},
                    "error": {"code": "recognition_plan_click_failed"}}, "observation": {"status": "unavailable"}}
            return super().execute_local_step(**kwargs)

    co = GuardedCoordinator()
    reader(monkeypatch, control(), control(checked=True))
    result = run(co, CHECK, TEXT)
    assert not co.calls and result["action_executed"] is False
    assert result["error"]["code"] == "local_control_target_state_changed"
    assert result["interrupted_at"] == 0


def test_invalid_option_then_valid_option_recovers_same_expanded_dropdown(monkeypatch):
    state = {"expanded": False, "value": "AU"}
    def current(*args, **kwargs):
        return control(kind="dropdown", label="Country", value=state["value"],
            options=[option()] if state["expanded"] else [], expanded=state["expanded"])
    monkeypatch.setitem(sys.modules, "app.agent.windows_form_control_reader", SimpleNamespace(read_form_control=current))

    class StatefulCoordinator(Coordinator):
        def execute_local_step(self, **kwargs):
            goal = kwargs["request"]["goal"]
            selecting = goal.startswith("Click the option")
            kwargs["control_target"]({"x": 10, "y": 35 if selecting else 20})
            if selecting:
                state.update(expanded=False, value="NZ")
            else:
                state["expanded"] = not state["expanded"]
            return super().execute_local_step(**kwargs)

    co = StatefulCoordinator()
    first = run(co, {**DROP, "option": "MISSING"})
    assert first["error"]["code"] == "form_option_not_visible" and state["expanded"] is True
    second = run(co, DROP)
    assert second["status"] == "completed" and state == {"expanded": False, "value": "NZ"}
    assert len(co.calls) == 2
    assert [step["name"] for step in second["fields"][0]["steps"]] == ["select_option"]
    assert second["capture"]["sha256"] == "before-2" and second["observation"]["capture"]["sha256"] == "after-2"
    assert first["status"] == "interrupted" and first["automatic_retry_allowed"] is False


@pytest.mark.parametrize("expanded", [None, 2, 3, "expanded"])
def test_unknown_dropdown_expansion_never_guesses_a_toggle(monkeypatch, expanded):
    co = Coordinator()
    reader(monkeypatch, control(kind="dropdown", label="Country", value="AU", expanded=expanded))
    result = run(co, DROP)
    assert result["error"]["code"] == "form_control_expansion_unavailable"
    assert not co.calls and result["action_executed"] is False


def test_already_expanded_missing_option_stops_without_click(monkeypatch):
    co = Coordinator()
    reader(monkeypatch, control(kind="dropdown", label="Country", value="AU", expanded=True))
    result = run(co, DROP)
    assert result["error"]["code"] == "form_option_not_visible"
    assert not co.calls


def test_open_dropdown_must_verify_expanded_before_selecting(monkeypatch):
    co = Coordinator()
    before = control(kind="dropdown", label="Country", value="AU", expanded=False)
    reader(monkeypatch, before, {**before, "options": [option()]})
    result = run(co, DROP)
    assert result["error"]["code"] == "form_control_not_expanded"
    assert len(co.calls) == 1
