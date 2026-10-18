from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage

import app.desktop_review.grounded_preview_widget as widget_module
from app.agent.text_execution import text_execution_reference
from app.agent.text_field_evidence import TextFieldIdentity, TextFieldSnapshot, prepare_text_field_expectation
from app.agent.text_parameters import ReviewedTextParameters, resolve_text_parameters, text_parameter_reference
from app.desktop_review.grounded_preview_widget import GroundedPreviewWidget, validate_review_view
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator, NativeSingleStepCoordinatorError
from app.desktop_review.window import ensure_application


def _resolved(*, clear_existing, variable=False):
    content = {"kind": "variable", "name": "value"} if variable else {"kind": "literal", "text": "fixed\r\nvalue"}
    reviewed = ReviewedTextParameters.from_payload({
        "contract_version": "reviewed_text_parameters_v1", "target_field_id": "query", "content": content,
        "clear_existing": clear_existing, "sensitive": False, "submit": False, "clipboard_policy": "restore_previous",
    })
    return resolve_text_parameters(reviewed, {"value": "inserted"})


def _expectation(resolved, *, value="before\r\nvalue", selection=(0, 13)):
    identity = TextFieldIdentity("query", 42, 7, 1.0, (1, 2), (0, 0, 20, 20), (2, 3, 10, 10))
    before = TextFieldSnapshot(identity, "capture", "read-before", 1, "uia_value", value, selection)
    return prepare_text_field_expectation(before, resolved)


def _png():
    image = QImage(20, 20, QImage.Format.Format_ARGB32)
    image.fill(0xFFFFFFFF)
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert image.save(buffer, "PNG")
    return bytes(buffer.data())


def _view(resolved, expectation):
    raw = _png()
    return {
        "phase": "pending_review", "confirmation_id": "grounded-confirmation." + "a" * 64,
        "preview": {
            "review_selection": {"semantic_action": "fill_field", "text_parameters_ref": text_parameter_reference(resolved.reviewed)},
            "target_window_handle": 42, "target_process_id": 7, "content_sha256": "b" * 64,
            "text_execution_ref": text_execution_reference(resolved),
            "grounding_preview": {
                "semantic_action": "fill_field", "element_ref": "query", "source_state_id": "source", "target_state_id": "target",
                "asset_id": "asset", "asset_content_sha256": "c" * 64, "reviewed_revision_hash": "d" * 64,
                "gate_decision_ref": "gate", "confidence": 1.0, "score_margin": 1.0,
                "bbox": {"x": 2, "y": 3, "w": 10, "h": 10}, "click_point": {"x": 5, "y": 5},
                "capture_lineage": {"capture_id": "capture", "screenshot_sha256": sha256(raw).hexdigest(), "viewport_size": {"width": 20, "height": 20}},
                "text_parameters_ref": text_parameter_reference(resolved.reviewed),
            },
            "text_field_expectation_ref": expectation.to_reference(),
        },
        "requested_at": "2026-09-07T00:00:00Z", "expires_at": "2026-09-07T00:05:00Z",
        "owner_is_current": True, "png_bytes": raw, "text_input_local": resolved, "text_field_local": expectation,
    }


def _patch_preview_parser(monkeypatch):
    monkeypatch.setattr(widget_module.GroundedActionPreview, "from_dict", classmethod(
        lambda _cls, value: SimpleNamespace(to_dict=lambda: deepcopy(value))
    ))


@pytest.mark.parametrize("variable,clear_existing,selection", [(False, True, (0, 13)), (True, False, (6, 6))])
def test_widget_displays_local_before_and_expected_values(monkeypatch, variable, clear_existing, selection):
    ensure_application()
    _patch_preview_parser(monkeypatch)
    resolved = _resolved(clear_existing=clear_existing, variable=variable)
    expected = _expectation(resolved, selection=selection)
    widget = GroundedPreviewWidget()
    try:
        widget.set_review(_view(resolved, expected))
        assert widget.text_before_editor.isReadOnly()
        assert widget.text_expected_editor.isReadOnly()
        assert widget.review["text_field_local"] == expected
        assert widget.review["text_field_local"].before.value == "before\r\nvalue"
        assert widget.text_before_editor.toPlainText() == "before\nvalue"
        assert widget.text_expected_editor.toPlainText() == expected.expected_value.replace("\r\n", "\n")
        assert expected.expected_value != expected.before.value
    finally:
        widget.close()


def test_widget_rejects_wrong_local_expectation_reference(monkeypatch):
    _patch_preview_parser(monkeypatch)
    resolved = _resolved(clear_existing=True)
    expected = _expectation(resolved)
    wrong = _expectation(resolved, value="other", selection=(0, 5))
    view = _view(resolved, expected)
    view["text_field_local"] = wrong

    with pytest.raises(ValueError):
        validate_review_view(view)


def test_coordinator_attaches_matching_local_expectation_and_rejects_mismatch():
    resolved = _resolved(clear_existing=False, variable=True)
    expected = _expectation(resolved, selection=(6, 6))
    coordinator = NativeSingleStepCoordinator.__new__(NativeSingleStepCoordinator)
    coordinator._owner = SimpleNamespace(call=lambda action: action())
    runtime = SimpleNamespace(
        get_local_grounded_text_input=lambda *, confirmation_id: resolved,
        get_local_grounded_text_field_expectation=lambda *, confirmation_id: expected,
    )
    view = {"confirmation_id": "grounded-confirmation." + "a" * 64, "preview": {
        "grounding_preview": {"semantic_action": "fill_field"},
        "review_selection": {"text_parameters_ref": text_parameter_reference(resolved.reviewed)},
        "text_execution_ref": text_execution_reference(resolved),
        "text_field_expectation_ref": expected.to_reference(),
    }}

    coordinator._attach_local_text(runtime, view)
    assert view["text_field_local"] == expected
    runtime.get_local_grounded_text_field_expectation = lambda *, confirmation_id: _expectation(resolved, value="wrong", selection=(0, 5))
    with pytest.raises(NativeSingleStepCoordinatorError, match="text field"):
        coordinator._attach_local_text(runtime, deepcopy(view))
