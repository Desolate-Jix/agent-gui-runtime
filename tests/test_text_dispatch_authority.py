from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.agent import desktop_backend as backend_module


FIXED_TEXT = "\u4f60\u597d\uff0c\u4e16\u754c"


def reviewed_payload(*, content=None, clear_existing=True, submit=False):
    return {
        "contract_version": "reviewed_text_parameters_v1",
        "target_field_id": "query",
        "content": content or {"kind": "literal", "text": FIXED_TEXT},
        "clear_existing": clear_existing,
        "sensitive": False,
        "submit": submit,
        "clipboard_policy": "restore_previous",
    }


def prepared(*, content=None, variables=None, clear_existing=True):
    from app.agent.text_parameters import (
        ReviewedTextParameters,
        TextDispatchParameters,
        resolve_text_parameters,
    )

    reviewed = ReviewedTextParameters.from_payload(
        reviewed_payload(content=content, clear_existing=clear_existing)
    )
    resolved = resolve_text_parameters(reviewed, variables or {})
    return TextDispatchParameters(
        parameters=resolved,
        target_bbox=(40.0, 50.0, 120.0, 40.0),
        viewport_size=(320, 200),
    )


def command_and_authority(text_input):
    command = backend_module.DesktopDispatchCommand(
        semantic_action="fill_field",
        capture_id="capture-current",
        candidate_id="candidate-current",
        click_point=(70.0, 80.0),
        target_window_handle=4242,
        text_input=text_input,
    )
    authority = backend_module._mint_execution_authority(
        session_id="session-1",
        observation_id="observation-1",
        intent_id="intent-1",
        workflow_revision_hash="b" * 64,
        semantic_action=command.semantic_action,
        selection_sha256="a" * 64,
        capture_id=command.capture_id,
        candidate_id=command.candidate_id,
        click_point=command.click_point,
        target_window_handle=command.target_window_handle,
        gate_decision_ref="gate:current",
        text_input=text_input,
    )
    return command, authority


class InputBoundary:
    def __init__(self, result="success"):
        self.calls = []
        self.result = result

    def click_point(self, *args, **kwargs):
        raise AssertionError("text dispatch must use type_text only")

    def type_text(self, **kwargs):
        from app.core.runtime_input_authority import runtime_backend_input_is_active

        self.calls.append((kwargs, runtime_backend_input_is_active()))
        if self.result == "lost":
            raise OSError("result lost after paste")
        if self.result != "success":
            return self.result
        return {
            "typed": True,
            "window_handle": 4242,
            "text_length": len(kwargs["text"]),
            "click_before_typing": True,
            "clear_existing": kwargs["clear_existing"],
            "submit": False,
            "restore_clipboard": True,
            "clipboard_restore_status": "restored",
            "clipboard_verified_before_paste": True,
        }


def backend(boundary, *, width=320, handle=4242):
    bound = SimpleNamespace(handle=handle, rect=SimpleNamespace(left=0, top=0, right=width, bottom=200))
    return backend_module.ExistingWindowsBackendAdapter(
        input_controller=boundary,
        window_manager=SimpleNamespace(get_bound_window=lambda: bound),
    )


def test_fixed_multilingual_text_dispatches_once_via_type_text():
    text_input = prepared(clear_existing=False)
    command, authority = command_and_authority(text_input)
    boundary = InputBoundary()

    receipt = backend(boundary).dispatch(command, authority=authority)

    assert receipt.status == "dispatched"
    assert boundary.calls == [(
        {
            "text": FIXED_TEXT,
            "x": 70,
            "y": 80,
            "click_before_typing": True,
            "clear_existing": False,
            "submit": False,
            "restore_clipboard": True,
        },
        True,
    )]


def test_variable_value_is_resolved_snapshot_before_mapping_changes_and_dispatches():
    variables = {"query_text": "first value"}
    text_input = prepared(
        content={"kind": "variable", "name": "query_text"}, variables=variables
    )
    variables["query_text"] = "changed after review"
    command, authority = command_and_authority(text_input)
    boundary = InputBoundary()

    assert text_input.parameters.text == "first value"
    assert backend(boundary).dispatch(command, authority=authority).status == "dispatched"
    assert boundary.calls[0][0]["text"] == "first value"


def test_variable_value_drift_or_authority_reuse_never_types_more_than_once():
    text_input = prepared(
        content={"kind": "variable", "name": "query_text"},
        variables={"query_text": "approved"},
    )
    command, authority = command_and_authority(text_input)
    forged = replace(
        command,
        text_input=prepared(
            content={"kind": "variable", "name": "query_text"},
            variables={"query_text": "forged"},
        ),
    )
    boundary = InputBoundary()
    adapter = backend(boundary)

    with pytest.raises(PermissionError, match="does not match"):
        adapter.dispatch(forged, authority=authority)
    assert boundary.calls == []
    assert adapter.dispatch(command, authority=authority).status == "dispatched"
    with pytest.raises(PermissionError, match="already consumed"):
        adapter.dispatch(command, authority=authority)
    assert len(boundary.calls) == 1


def test_missing_variable_and_submit_payload_are_rejected():
    from app.agent.text_parameters import ReviewedTextParameters, resolve_text_parameters

    variable = ReviewedTextParameters.from_payload(
        reviewed_payload(content={"kind": "variable", "name": "query_text"})
    )
    with pytest.raises(ValueError, match="variable"):
        resolve_text_parameters(variable, {})
    with pytest.raises(ValueError):
        ReviewedTextParameters.from_payload(reviewed_payload(submit=True))


@pytest.mark.parametrize(
    "content",
    [
        {"kind": "literal", "text": ""},
        {"kind": "literal", "text": "\u4f60\u597d\n\u4e16\u754c\r\n\tend"},
    ],
)
def test_fixed_empty_and_multiline_text_payloads_round_trip_losslessly(content):
    from app.agent.text_parameters import ReviewedTextParameters, resolve_text_parameters

    payload = reviewed_payload(content=content)
    reviewed = ReviewedTextParameters.from_payload(payload)

    assert reviewed.to_payload() == payload
    assert resolve_text_parameters(reviewed, {"ignored": "value"}).text == content["text"]


@pytest.mark.parametrize("result", ["lost", {"typed": True}])
def test_lost_or_malformed_type_text_receipt_is_indeterminate_and_not_repeated(result):
    command, authority = command_and_authority(prepared())
    boundary = InputBoundary(result=result)
    adapter = backend(boundary)

    receipt = adapter.dispatch(command, authority=authority)

    assert receipt.status == "indeterminate"
    assert receipt.reason_code == "backend_result_lost"
    with pytest.raises(PermissionError, match="already consumed"):
        adapter.dispatch(command, authority=authority)
    assert len(boundary.calls) == 1


def test_text_backend_does_not_treat_clipboard_restore_conflict_as_clean_success():
    command, authority = command_and_authority(prepared())
    result = {
        "typed": True, "window_handle": 4242, "text_length": len(FIXED_TEXT),
        "click_before_typing": True, "clear_existing": True, "submit": False,
        "restore_clipboard": True, "clipboard_verified_before_paste": True,
        "clipboard_restore_status": "conflict",
    }
    boundary = InputBoundary(result=result)
    assert backend(boundary).dispatch(command, authority=authority).status == "indeterminate"
    assert len(boundary.calls) == 1
