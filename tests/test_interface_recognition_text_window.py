from __future__ import annotations

from copy import deepcopy

from PySide6.QtTest import QTest

from app.desktop_review.window import ReviewMainWindow, ensure_application
from test_desktop_review_window import _Facade, _batch, _wait_loaded, _wait_workers


def _two_interfaces():
    value = _batch()
    other = deepcopy(value["interfaces"][0]); other["interface_id"] = "screen-2"; other["meaning"] = "第二用途"
    value["interfaces"].append(other)
    return value


def test_interface_recognition_text_switch_save_clear_and_busy():
    app = ensure_application()
    facade = _Facade([_two_interfaces()])
    window = ReviewMainWindow(facade); window.show()
    window.batch_tree.setCurrentItem(window.batch_tree.topLevelItem(0)); _wait_loaded(window)
    first = window.batch_tree.topLevelItem(0).child(0)
    second = window.batch_tree.topLevelItem(0).child(1)
    window.batch_tree.setCurrentItem(first); QTest.qWait(10)
    assert window.interface_recognition_text.objectName() == "interfaceRecognitionTextField"
    original = window.interface_meaning.text()
    window.interface_recognition_text.setText("Notepad")
    window.interface_recognition_text.editingFinished.emit()
    assert window.workspace["batch"]["interfaces"][0]["meaning"] == original
    assert window.workspace["batch"]["interfaces"][0]["recognition_text"] == "Notepad"
    window.batch_tree.setCurrentItem(second); QTest.qWait(10)
    assert window.interface_recognition_text.text() == ""
    window.interface_recognition_text.setText("Second title")
    window.batch_tree.setCurrentItem(first); QTest.qWait(10)
    assert window.interface_recognition_text.text() == "Notepad"
    assert window.workspace["batch"]["interfaces"][1]["recognition_text"] == "Second title"
    window.save_current(); _wait_workers(window)
    assert facade.saved[-1]["interfaces"][0]["recognition_text"] == "Notepad"
    window.interface_recognition_text.clear(); window.interface_recognition_text.editingFinished.emit()
    assert "recognition_text" not in window.workspace["batch"]["interfaces"][0]
    window._set_busy(True, "test")
    assert not window.interface_recognition_text.isEnabled()
    window._set_busy(False, "")
    window._dirty = False
    _wait_workers(window)
    window.close(); app.processEvents()


def test_absent_optional_identity_does_not_dirty_unchanged_workspace():
    app = ensure_application()
    facade = _Facade([_batch()])
    window = ReviewMainWindow(facade)
    try:
        window.batch_tree.setCurrentItem(window.batch_tree.topLevelItem(0))
        _wait_loaded(window)
        window.batch_tree.setCurrentItem(window.batch_tree.topLevelItem(0).child(0))
        QTest.qWait(10)
        window._dirty = False
        assert window.interface_recognition_text.text() == ""
        assert window._commit_interface_meaning()
        assert not window.is_dirty
        assert "recognition_text" not in window.workspace["batch"]["interfaces"][0]
    finally:
        window._dirty = False
        _wait_workers(window)
        window.close()
        app.processEvents()
