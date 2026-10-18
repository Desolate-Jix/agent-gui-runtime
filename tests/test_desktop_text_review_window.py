from __future__ import annotations

import copy

from app.desktop_review.window import ReviewMainWindow, ensure_application
from test_desktop_review_window import _Facade, _batch, _wait_loaded, _wait_workers


PARAMETERS = {
    "contract_version": "reviewed_text_parameters_v1", "target_field_id": "apply",
    "content": {"kind": "literal", "text": "\u4e2d\u6587\nsecond line"},
    "clear_existing": True, "sensitive": False, "submit": False,
    "clipboard_policy": "restore_previous",
}


def test_native_editor_saves_fixed_text_and_switches_to_variable_without_old_content():
    application = ensure_application()
    batch = _batch()
    batch["steps"][0].update(action_type="fill_field", text_parameters=copy.deepcopy(PARAMETERS))
    facade = _Facade([batch])
    window = ReviewMainWindow(facade)
    window.show()
    window.load_batch("task-1", "batch-1")
    try:
        _wait_loaded(window)
        _wait_workers(window)
        window.step_table.selectRow(0)
        application.processEvents()
        assert window.text_content_kind.currentData() == "literal"
        assert window.text_literal.toPlainText() == PARAMETERS["content"]["text"]
        window.text_literal.setPlainText("  \u4fee\u6539\n  ")
        window.save_current()
        _wait_workers(window)
        assert facade.saved[-1]["steps"][0]["text_parameters"]["content"] == {"kind": "literal", "text": "  \u4fee\u6539\n  "}
        window.text_content_kind.setCurrentIndex(window.text_content_kind.findData("variable"))
        window.text_variable.setText("query_text")
        window.text_clear_existing.setChecked(False)
        window.text_sensitive.setChecked(True)
        window.save_current()
        _wait_workers(window)
        params = facade.saved[-1]["steps"][0]["text_parameters"]
        assert params == {**PARAMETERS, "content": {"kind": "variable", "name": "query_text"}, "clear_existing": False, "sensitive": True}
        assert not window.text_literal.isEnabled()
        window.step_action.setText("open_detail")
        assert "text_parameters" not in window.workspace["batch"]["steps"][0]
    finally:
        _wait_workers(window)
        window._dirty = False
        window.close()
        application.processEvents()


def test_native_editor_preserves_unedited_line_endings_and_clears_text_on_workspace_reset():
    application = ensure_application()
    batch = _batch()
    original = "\u539f\u6587\r\nsecond\rthird"
    params = {**PARAMETERS, "content": {"kind": "literal", "text": original}, "sensitive": True}
    batch["steps"][0].update(action_type="fill_field", text_parameters=params)
    facade = _Facade([batch])
    window = ReviewMainWindow(facade)
    window.show()
    window.load_batch("task-1", "batch-1")
    try:
        _wait_loaded(window)
        _wait_workers(window)
        window.step_table.selectRow(0)
        application.processEvents()
        window.text_clear_existing.setChecked(False)
        window.save_current()
        _wait_workers(window)
        assert facade.saved[-1]["steps"][0]["text_parameters"]["content"]["text"] == original
        window._clear_step_fields()
        assert window.text_literal.toPlainText() == ""
        assert window.text_variable.text() == ""
        assert window._text_literal_original == ""
        assert not window.text_sensitive.isChecked()
    finally:
        _wait_workers(window)
        window._dirty = False
        window.close()
        application.processEvents()
