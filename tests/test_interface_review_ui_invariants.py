"""从普通原生内容入口验证直接保存、版本复用和未保存保护。"""
import pytest
from PySide6.QtWidgets import QApplication

from app.desktop_review.content_library import InterfaceContentLibrary
from test_formal_graph_exact_review import _runtime, TASK

_APP = QApplication.instance() or QApplication([])


@pytest.fixture
def library(tmp_path):
    store, _, facade, _ = _runtime(tmp_path)
    dialog = InterfaceContentLibrary(facade)
    try:
        dialog.items.setCurrentRow(0)
        _APP.processEvents()
        yield facade, dialog
    finally:
        dialog.pane.discard_changes()
        dialog.close()
        facade.close()
        store.close()


def test_real_region_edit_save_and_agent_read_without_review(library):
    facade, dialog = library
    pane = dialog.pane
    before = pane.snapshot
    pane.meaning_edit.setText("New saved independent interface")
    region_id = before["content"]["regions"][0]["region_id"]
    pane.canvas.regionGeometryChanged.emit(region_id, [2, 3, 15, 10])
    assert pane.dirty
    pane.save_button.click()
    assert dialog.error.text() == ""
    after = facade.load_interface_content(before["interface_id"])
    assert after["revision"] == 2
    assert after["content"]["regions"][0]["bbox"] == [2, 3, 15, 10]
    assert after["content"]["meaning"] == "New saved independent interface"
    assert pane.review_button.isHidden()
    assert facade.get_interface_memory(TASK, after["interface_id"])["content"] == after["content"]
    pane.binding_name.setText("Fixture")
    pane.binding_identity.setText("fixture.exe")
    pane.save_button.click()
    assert not pane.dirty
    with_binding = facade.load_interface_content(before["interface_id"])
    assert with_binding["revision"] == 3
    assert with_binding["application_binding"]["display_name"] == "Fixture"
    assert facade.get_interface_memory(TASK, after["interface_id"])["content"] == with_binding["content"]
    assert facade.get_interface_memory(TASK, after["interface_id"], after["version_id"])["content"] == after["content"]


def test_dirty_text_prevents_switch_and_close(library):
    _, dialog = library
    pane = dialog.pane
    before = pane.snapshot
    pane.meaning_edit.setText("Keep unsaved")
    dialog.items.setCurrentRow(1)
    assert pane.snapshot["interface_id"] == before["interface_id"]
    assert pane.meaning_edit.text() == "Keep unsaved"
    assert dialog.items.currentRow() == 0
    assert dialog.error.text()
    dialog.show()
    dialog.close()
    assert dialog.isVisible()


def test_stale_save_keeps_input_and_shows_error(library):
    facade, dialog = library
    pane = dialog.pane
    old = pane.snapshot
    facade.save_interface_content(old["interface_id"], old["revision"], old["content_sha256"],
        {"meaning": "Other editor"}, "other-editor")
    pane.meaning_edit.setText("Keep my pending correction")
    pane.save_button.click()
    assert "stale_revision" in dialog.error.text()
    assert pane.meaning_edit.text() == "Keep my pending correction"
    assert pane.dirty


def test_clearing_recognition_text_is_an_explicit_revision(library):
    facade, dialog = library
    pane = dialog.pane
    pane.recognition_text_edit.setText("Temporary recognition")
    pane.save_button.click()
    assert not pane.dirty, dialog.error.text()
    pane.recognition_text_edit.clear()
    pane.save_button.click()
    assert not pane.dirty, dialog.error.text()
    assert "recognition_text" not in facade.load_interface_content(pane.snapshot["interface_id"])["content"]
