from dataclasses import replace
from types import SimpleNamespace

import pytest

import app.core.input_controller as input_module
from app.agent.desktop_backend import (
    ExistingWindowsBackendAdapter,
    DesktopDispatchCommand,
    _mint_execution_authority,
)
from app.agent.text_field_evidence import (
    TextFieldIdentity,
    TextFieldSnapshot,
    prepare_text_field_expectation,
)
from app.agent.text_input_guard import TextInputGuard
from app.agent.text_parameters import (
    ReviewedTextParameters,
    TextDispatchParameters,
    resolve_text_parameters,
)
from app.core.input_controller import InputController, VK_A, VK_CONTROL, VK_V


class ClipboardSession:
    def __init__(self, events):
        self.events = events
        self.status = "not_started"

    def __enter__(self):
        self.events.append("clipboard-prepared")
        self.status = "pending_restore"
        return self

    def verify_current_text(self):
        self.events.append("clipboard-verified")
        return 1

    def __exit__(self, *exception):
        self.status = "restored"
        self.events.append("clipboard-restored")


def reviewed(*, text=None, variable=None, clear_existing=True):
    content = {"kind": "literal", "text": text} if variable is None else {"kind": "variable", "name": variable}
    return ReviewedTextParameters.from_payload({
        "contract_version": "reviewed_text_parameters_v1", "target_field_id": "query",
        "content": content, "clear_existing": clear_existing, "sensitive": False,
        "submit": False, "clipboard_policy": "restore_previous",
    })


def compose(monkeypatch, *, resolved, value="before", selection=(0, 6), focus_mutation=None, ctrl_a_mutation=None,
            reader_requires_focus=False):
    controller = InputController()
    events, pasted = [], []
    state = SimpleNamespace(value=value, selection=selection, foreground=4242, reads=0, focused=False)
    bound = SimpleNamespace(
        handle=4242, process_id=42, title="text-field",
        rect=SimpleNamespace(left=0, top=0, right=320, bottom=200),
    )
    identity = TextFieldIdentity("query", 4242, 42, 1.0, (1, 2), (0, 0, 320, 200), (40, 50, 120, 40))

    def read_current():
        events.append("reader")
        if reader_requires_focus and not state.focused:
            raise RuntimeError("reader requires keyboard focus")
        state.reads += 1
        return TextFieldSnapshot(identity, "capture", f"read-{state.reads}", 100 + state.reads, "uia_value", state.value, state.selection)

    before = TextFieldSnapshot(identity, "capture", "before-read", 100, "uia_value", value, selection)
    expectation = prepare_text_field_expectation(before, resolved)
    guard = TextInputGuard(expectation=expectation, read_current=read_current)
    session = ClipboardSession(events)

    def focus(_handle):
        state.foreground = 4242
        state.focused = True
        if focus_mutation is not None:
            focus_mutation(state)
        return True

    def chord(keys):
        events.append(tuple(keys))
        if keys == [VK_CONTROL, VK_A]:
            state.selection = ctrl_a_mutation(state) if ctrl_a_mutation else (0, len(state.value))
        if keys == [VK_CONTROL, VK_V]:
            pasted.append(resolved.text)

    monkeypatch.setattr(controller, "_ensure_windows_input", lambda: None)
    monkeypatch.setattr(controller, "_require_bound_window", lambda: bound)
    monkeypatch.setattr(controller, "_focus_window", focus)
    monkeypatch.setattr(controller, "_clipboard_text_transaction", lambda *args, **kwargs: session, raising=False)
    def click(*args, **kwargs):
        state.focused = True
        events.append("click")
        return {"clicked": True}

    monkeypatch.setattr(controller, "click_point", click)
    monkeypatch.setattr(controller, "_press_chord", chord)
    monkeypatch.setattr(input_module, "win32gui", SimpleNamespace(GetForegroundWindow=lambda: state.foreground))
    monkeypatch.setattr(input_module.window_manager, "validate_bound_point_visibility", lambda **kwargs: {"allowed": True})
    monkeypatch.setattr(input_module.window_manager, "validate_bound_region_visibility", lambda **kwargs: {"allowed": True})
    monkeypatch.setattr(input_module.time, "sleep", lambda _seconds: None)

    params = TextDispatchParameters(parameters=resolved, target_bbox=(40.0, 50.0, 120.0, 40.0), viewport_size=(320, 200))
    command = DesktopDispatchCommand(
        semantic_action="fill_field", capture_id="capture-current", candidate_id="candidate-current",
        click_point=(70.0, 80.0), target_window_handle=4242, text_input=params, text_guard=guard,
    )
    authority = _mint_execution_authority(
        session_id="session", observation_id="observation", intent_id="intent", workflow_revision_hash="a" * 64,
        semantic_action=command.semantic_action, selection_sha256="b" * 64, capture_id=command.capture_id,
        candidate_id=command.candidate_id, click_point=command.click_point, target_window_handle=4242,
        gate_decision_ref="gate", text_input=params, text_guard=guard,
    )
    adapter = ExistingWindowsBackendAdapter(input_controller=controller, window_manager=SimpleNamespace(get_bound_window=lambda: bound))
    return adapter, command, authority, guard, session, events, pasted


def test_fixed_replacement_uses_guarded_real_input_pipeline_once(monkeypatch):
    resolved = resolve_text_parameters(reviewed(text="\u4f60\u597d\uff0c\u4e16\u754c", clear_existing=True), {})
    adapter, command, authority, _, _, events, pasted = compose(monkeypatch, resolved=resolved)

    assert adapter.dispatch(command, authority=authority).status == "dispatched"
    assert pasted == ["\u4f60\u597d\uff0c\u4e16\u754c"]
    assert events.count("click") == 1
    assert events.count((VK_CONTROL, VK_V)) == 1


def test_guard_defers_focus_required_reads_until_after_click(monkeypatch):
    resolved = resolve_text_parameters(reviewed(text="approved", clear_existing=True), {})
    adapter, command, authority, _, _, events, pasted = compose(
        monkeypatch, resolved=resolved, reader_requires_focus=True,
    )

    assert adapter.dispatch(command, authority=authority).status == "dispatched"
    assert pasted == ["approved"]
    assert events.index("click") < events.index("reader")
    assert events.count("reader") == 2


def test_variable_insertion_uses_same_guarded_pipeline_without_mouse_click(monkeypatch):
    variables = {"approved": "frozen value"}
    resolved = resolve_text_parameters(reviewed(variable="approved", clear_existing=False), variables)
    variables["approved"] = "changed later"
    adapter, command, authority, _, _, events, pasted = compose(monkeypatch, resolved=resolved, selection=(3, 3))

    assert adapter.dispatch(command, authority=authority).status == "dispatched"
    assert pasted == ["frozen value"]
    assert "click" not in events
    assert events.count((VK_CONTROL, VK_V)) == 1


def test_guard_rejects_selection_drift_after_focus_before_paste(monkeypatch):
    resolved = resolve_text_parameters(reviewed(text="x", clear_existing=False), {})
    adapter, command, authority, _, session, _, pasted = compose(
        monkeypatch, resolved=resolved, selection=(3, 3), focus_mutation=lambda state: setattr(state, "selection", (0, 0)),
    )

    receipt = adapter.dispatch(command, authority=authority)
    assert receipt.status == "indeterminate"
    assert pasted == []
    assert session.status == "restored"


def test_guard_rejects_wrong_ctrl_a_range_before_paste(monkeypatch):
    resolved = resolve_text_parameters(reviewed(text="x", clear_existing=True), {})
    adapter, command, authority, _, _, _, pasted = compose(
        monkeypatch, resolved=resolved, ctrl_a_mutation=lambda state: (0, len(state.value) - 1),
    )

    assert adapter.dispatch(command, authority=authority).status == "indeterminate"
    assert pasted == []


def test_wrong_command_is_rejected_before_clipboard_transaction(monkeypatch):
    resolved = resolve_text_parameters(reviewed(text="approved", clear_existing=True), {})
    _, _, _, guard, session, _, _ = compose(monkeypatch, resolved=resolved)
    controller = InputController()
    monkeypatch.setattr(controller, "_ensure_windows_input", lambda: None)
    monkeypatch.setattr(controller, "_require_bound_window", lambda: SimpleNamespace(
        handle=4242, process_id=42, title="text-field", rect=SimpleNamespace(left=0, top=0, right=320, bottom=200),
    ))
    monkeypatch.setattr(controller, "_clipboard_text_transaction", lambda *args, **kwargs: session, raising=False)

    with pytest.raises(ValueError, match="precondition"):
        controller.type_text("forged", x=70, y=80, click_before_typing=True, clear_existing=True, field_guard=guard)
    assert session.status == "not_started"


def test_authority_rejects_guard_object_swap_without_second_dispatch(monkeypatch):
    resolved = resolve_text_parameters(reviewed(text="approved", clear_existing=True), {})
    adapter, command, authority, guard, _, _, pasted = compose(monkeypatch, resolved=resolved)
    other_guard = TextInputGuard(expectation=guard.expectation, read_current=guard.read_current)
    forged = replace(command, text_guard=other_guard)

    with pytest.raises(PermissionError, match="does not match"):
        adapter.dispatch(forged, authority=authority)
    assert pasted == []
    assert adapter.dispatch(command, authority=authority).status == "dispatched"
    with pytest.raises(PermissionError, match="already consumed"):
        adapter.dispatch(command, authority=authority)
    assert pasted == ["approved"]
