"""组合编排的契约回归；替换桌面边界，真实执行参数、分支和回执代码。"""
from copy import deepcopy
import pytest

from app.agent.text_field_evidence import TextFieldIdentity, TextFieldSnapshot
from app.desktop_review import input_sequence as module
from app.instant_mcp import InstantCommand


class Coordinator:
    def __init__(self, *, failure=None, missing_image=None):
        self.calls = []
        self.failure = failure
        self.missing_image = missing_image

    def execute_local_step(self, **kwargs):
        self.calls.append(kwargs)
        operation = kwargs["operation"]
        if self.failure == operation:
            raise RuntimeError("test dispatch failure")
        data = {"execution_path": {"action_executed": True}, "pressed": True,
            "selected_click_point": {"x": 10, "y": 20},
            "selected_click_point_coordinate_space": "capture_image_pixels"}
        frame = {"image_path": operation + ".png", "sha256": "a" * 64,
                 "window_size": {"width": 800, "height": 600}}
        return {"contract_version": "local_direct_step_v1", "phase": "returned",
            "capture": {"image_path": "before.png", "sha256": "b" * 64},
            "target_identity": {"target_window_handle": 1, "process_id": 2},
            "response": {"success": True, "data": data if operation == "press_key" else {"result": data}},
            "observation": {"status": "captured", "capture": frame} if operation != self.missing_image
                else {"status": "unavailable"}}


def snapshots(monkeypatch, values, *, selection=None, changed_identity=False):
    pending = iter(values)
    reads = []

    def read(coordinator, target, point, capture, field_id, expected_identity, **kwargs):
        reads.append(point)
        value = next(pending)
        if isinstance(value, Exception):
            raise value
        identity = TextFieldIdentity(field_id, 1, 2, 100.0,
            (1 if not changed_identity or len(reads) == 1 else 2,), (0, 0, 800, 600), (1, 1, 300, 40))
        return TextFieldSnapshot(identity, capture["sha256"], str(len(reads)), len(reads),
            "uia_value", value, selection)

    monkeypatch.setattr(module, "_read_field", read)
    monkeypatch.setattr(module, "_focus_field_binding", lambda located, receipt, target: {
        "control_type": "Edit", "runtime_id": [1], "bbox": {"x": 1, "y": 1, "w": 300, "h": 40}})
    return reads


def run(coordinator, **overrides):
    request = {"field_goal": "Search input", "text": "maps", "submit_search": True, **overrides}
    return module.run_input_sequence(coordinator, {"handle": 1, "process_id": 2}, request)


def test_sequence_dispatches_once_in_order_and_preserves_first_and_last_frames(monkeypatch):
    co = Coordinator()
    snapshots(monkeypatch, ["old", "maps"])
    result = run(co)
    assert [x["operation"] for x in co.calls] == ["execute_recognition_plan", "type_text", "press_key"]
    assert co.calls[1]["request"]["click_before_typing"] is False
    assert co.calls[2]["request"] == {"key": "Enter", "x": 10, "y": 20}
    assert result["completed_steps"] == ["focus", "type", "check_input", "search"]
    assert result["status"] == "completed" and result["task_effect_verified"] is None
    assert result["capture"]["image_path"] == "before.png"
    assert result["observation"]["capture"]["image_path"] == "press_key.png"


def test_fill_only_never_dispatches_enter(monkeypatch):
    co = Coordinator()
    snapshots(monkeypatch, ["", "maps"])
    assert run(co, submit_search=False)["status"] == "completed"
    assert len(co.calls) == 2


def test_focus_reuses_plain_click_semantics_instead_of_strict_fill_route(monkeypatch):
    co = Coordinator()
    snapshots(monkeypatch, ["", "maps"])
    run(co)
    assert co.calls[0]["request"] == {"goal": "Search input", "click_kind": "single"}


def test_explicit_recognition_rejection_is_zero_input_not_unknown(monkeypatch):
    co = Coordinator()
    co.execute_local_step = lambda **kwargs: {"phase": "result_unknown",
        "capture": {"sha256": "a" * 64}, "response": {"success": False,
            "data": {"action_executed": False}, "error": {"code": "local_recognition_invalid"}},
        "observation": {"status": "captured", "capture": {"sha256": "b" * 64}}}
    result = run(co)
    assert result["action_executed"] is False
    assert result["steps"][0]["action_executed"] is False


def test_focus_read_waits_for_uia_publication_without_reclick(monkeypatch):
    from app.agent.windows_text_field_reader import TextFieldReadError
    answers = iter([TextFieldReadError("text_field_keyboard_focus_unavailable"), "snapshot"])
    def read():
        value = next(answers)
        if isinstance(value, Exception):
            raise value
        return value
    monkeypatch.setattr(module, "sleep", lambda seconds: None, raising=False)
    assert module._wait_for_focused_field(read) == "snapshot"


def test_focus_read_does_not_retry_identity_failure(monkeypatch):
    from app.agent.windows_text_field_reader import TextFieldReadError
    calls = []
    def read():
        calls.append(1)
        raise TextFieldReadError("text_field_process_identity_changed")
    with pytest.raises(TextFieldReadError, match="identity_changed"):
        module._wait_for_focused_field(read)
    assert len(calls) == 1


@pytest.mark.parametrize("value,changed_identity,reason", [
    ("wrong", False, "input_value_mismatch"),
    ("maps", True, "input_field_changed"),
])
def test_failed_content_check_preserves_partial_input_and_does_not_submit(monkeypatch, value, changed_identity, reason):
    co = Coordinator()
    snapshots(monkeypatch, ["old", value], changed_identity=changed_identity)
    result = run(co)
    assert result["status"] == "interrupted" and result["error"]["code"] == reason
    assert result["interrupted_at"] == "check_input"
    assert result["action_executed"] is True and len(co.calls) == 2


def test_unreadable_focus_returns_click_evidence_without_typing(monkeypatch):
    co = Coordinator()
    snapshots(monkeypatch, [ValueError("unreadable")])
    result = run(co)
    assert result["input_check"]["status"] == "unavailable"
    assert result["completed_steps"] == ["focus"] and len(co.calls) == 1


def test_reader_stage_diagnostic_survives_without_private_exception_data(monkeypatch):
    from app.agent.windows_text_field_reader import TextFieldReadError
    error = TextFieldReadError("text_field_target_not_writable", diagnostic={
        "phase": "describe_target", "read_index": 1, "check": "password", "attribute_state": 1})
    error.diagnostic["name"] = "PRIVATE_SENTINEL"
    co = Coordinator()
    snapshots(monkeypatch, [error])
    result = run(co)
    assert result["error"] == {"code": "text_field_target_not_writable", "type": "TextFieldReadError",
        "diagnostic": {"phase": "describe_target", "read_index": 1, "check": "password", "attribute_state": 1}}
    assert len(co.calls) == 1


def test_arbitrary_exception_diagnostic_is_not_exported(monkeypatch):
    error = ValueError("PRIVATE_SENTINEL")
    error.diagnostic = {"phase": "read_text", "name": "PRIVATE_SENTINEL"}
    snapshots(monkeypatch, [error])
    assert "diagnostic" not in run(Coordinator())["error"]


def test_insert_uses_observed_selection_not_whole_field_assumption(monkeypatch):
    co = Coordinator()
    snapshots(monkeypatch, ["old query", "maps query"], selection=(0, 3))
    result = run(co, clear_existing=False)
    assert result["status"] == "completed"
    assert co.calls[1]["request"]["clear_existing"] is False


def test_unknown_insert_selection_stops_before_typing(monkeypatch):
    co = Coordinator()
    snapshots(monkeypatch, ["old query"])
    result = run(co, clear_existing=False)
    assert result["error"]["code"] == "input_selection_unavailable" and len(co.calls) == 1


def test_dispatch_exception_keeps_progress_and_never_reuses_previous_after(monkeypatch):
    co = Coordinator(failure="type_text")
    snapshots(monkeypatch, [""])
    progress = []
    result = module.run_input_sequence(co, {"handle": 1, "process_id": 2},
        {"field_goal": "Search", "text": "maps", "submit_search": True},
        persist=lambda x: progress.append(deepcopy(x)))
    assert result["status"] == "interrupted" and result["action_executed"] is True
    assert result["observation"].get("capture") is None
    assert result["steps"][-1]["status"] == "result_unknown"
    assert any(x["steps"][-1]["status"] == "dispatching" for x in progress if x["steps"])
    assert len(co.calls) == 2


def test_missing_final_image_is_not_complete(monkeypatch):
    co = Coordinator(missing_image="press_key")
    snapshots(monkeypatch, ["", "maps"])
    result = run(co)
    assert result["status"] == "interrupted"
    assert result["completed_steps"][-1] == "search"
    assert result["error"]["code"] == "search_observation_unavailable"


@pytest.mark.parametrize("payload", [
    {"field_goal": "Search", "text": "maps"},
    {"field_goal": "Search", "text": "maps", "submit_search": True, "invented": 1},
    {"field_goal": "", "text": "maps", "submit_search": False},
])
def test_invalid_sequence_cannot_be_queued(payload):
    with pytest.raises(ValueError):
        InstantCommand(kind="input_sequence", request=payload).command()
