from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QComboBox, QDialog, QLineEdit, QScrollArea

from app.learning_memory.workflow_input_dialog import WorkflowInputDialog


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    return QApplication.instance() or QApplication([])


def declaration(name, kind="text", required=True):
    return {"name": name, "type": kind, "required": required}


def test_validates_real_editors_and_preserves_original_text(app):
    dialog = WorkflowInputDialog([declaration("query")])
    editor = dialog.editors["query"]
    assert isinstance(editor, QLineEdit)
    editor.setText("  North  ")
    dialog.buttons.button(dialog.buttons.StandardButton.Ok).click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.values() == {"query": "  North  "}


def test_required_blank_keeps_dialog_open_input_and_focus(app):
    dialog = WorkflowInputDialog([declaration("record_id")])
    dialog.show()
    editor = dialog.editors["record_id"]
    editor.setText("   ")
    dialog.buttons.button(dialog.buttons.StandardButton.Ok).click()
    app.processEvents()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.isVisible()
    assert editor.text() == "   "
    assert editor.hasFocus()
    assert "record_id" in dialog.error_label.text()
    assert dialog.values() == {}
    dialog.reject()


def test_optional_blanks_are_omitted_but_nonblank_text_is_not_trimmed(app):
    blank = chr(32) * 2
    padded = chr(32) + "value" + chr(32)
    dialog = WorkflowInputDialog([
        declaration("optional_text", required=False),
        declaration("optional_number", "number", required=False),
        declaration("optional_boolean", "boolean", required=False),
        declaration("note", required=False),
    ])
    dialog.editors["optional_text"].setText(blank)
    dialog.editors["optional_number"].setText(blank)
    dialog.editors["note"].setText(padded)
    dialog.accept()
    assert dialog.values() == {"note": padded}


@pytest.mark.parametrize("raw", ["oops", "NaN", "inf", "-Infinity"])
def test_invalid_numbers_are_rejected_without_closing(app, raw):
    dialog = WorkflowInputDialog([declaration("amount", "number")])
    dialog.show()
    app.processEvents()
    dialog.editors["amount"].setText(raw)
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.isVisible()
    assert dialog.editors["amount"].text() == raw
    assert "amount" in dialog.error_label.text()
    assert dialog.values() == {}
    dialog.reject()


def test_number_zero_and_boolean_false_are_valid_values(app):
    dialog = WorkflowInputDialog([declaration("count", "number"), declaration("enabled", "boolean")])
    dialog.editors["count"].setText("0")
    boolean = dialog.editors["enabled"]
    assert isinstance(boolean, QComboBox)
    boolean.setCurrentIndex(boolean.findData(False))
    dialog.accept()
    assert dialog.values() == {"count": 0.0, "enabled": False}


def test_boolean_unanswered_required_and_cancel_never_returns_values(app):
    dialog = WorkflowInputDialog([declaration("enabled", "boolean")])
    editor = dialog.editors["enabled"]
    assert isinstance(editor, QComboBox)
    assert editor.currentData() is None
    dialog.accept()
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert "enabled" in dialog.error_label.text()
    editor.setCurrentIndex(editor.findData(True))
    dialog.reject()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert dialog.values() == {}


def test_many_inputs_use_scroll_area_and_reasonable_window_size(app):
    dialog = WorkflowInputDialog([declaration(f"field_{i}") for i in range(40)])
    assert dialog.findChild(QScrollArea) is not None
    assert dialog.height() <= 720
    dialog.reject()
