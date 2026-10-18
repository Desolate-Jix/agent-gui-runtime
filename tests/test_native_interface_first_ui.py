from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from app.desktop_review.interface_pane import InterfaceReviewPane
from app.desktop_review.content_library import InterfaceContentLibrary
from app.desktop_review.window import ReviewMainWindow, ensure_application
from tests.test_formal_graph_review_pane import _runtime, _wait


_APP = QApplication.instance() or QApplication([])


def _snapshot() -> dict:
    return {
        "interface_id": "interface-1", "version_id": "version-1", "revision": 1,
        "content_sha256": "a" * 64, "review_status": "draft", "application_binding": None,
        "source": {"task_id": "task", "batch_id": "batch", "source_ref": "ref", "external_interface_id": "external", "screenshot_id": "shot", "screenshot_sha256": "b" * 64},
        "content": {"meaning": "列表界面", "recognition_text": "列表", "regions": [{"region_id": "region-1", "bbox": [1, 2, 30, 20]}]},
    }


class _Facade:
    def __init__(self):
        self.saved_args = None
        self.review_args = None

    def save_interface_content(self, *args):
        self.saved_args = args
        value = _snapshot()
        value["revision"] = 2
        value["content_sha256"] = "c" * 64
        value["content"] = args[3]
        return value

    def review_interface_content(self, *args):
        self.review_args = args
        value = _snapshot()
        value["review_status"] = "reviewed"
        value["application_binding"] = args[3]
        return value


def test_interface_pane_edits_regions_and_saves_atomically() -> None:
    facade = _Facade()
    pane = InterfaceReviewPane(facade)
    pane.set_snapshot(_snapshot())
    pane.meaning_edit.setText("新的界面")
    pane.canvas.regionGeometryChanged.emit("region-1", [2, 3, 31, 21])
    pane.save_changes()
    assert facade.saved_args[0:3] == ("interface-1", 1, "a" * 64)
    assert facade.saved_args[3]["meaning"] == "新的界面"
    assert facade.saved_args[3]["regions"][0]["region_id"] == "region-1"
    assert facade.saved_args[3]["regions"][0]["bbox"] == [2, 3, 31, 21]


def test_interface_pane_review_requires_explicit_binding_and_never_executes() -> None:
    facade = _Facade()
    pane = InterfaceReviewPane(facade)
    pane.set_snapshot(_snapshot())
    binding = {"application_id": "app", "window_title": "窗口", "process_id": 1}
    pane.review(binding)
    assert facade.review_args[0:3] == ("interface-1", 1, "a" * 64)
    assert facade.review_args[3] == binding
    assert pane.snapshot["review_status"] == "reviewed"


def test_interface_pane_save_failure_reports_error_and_keeps_draft() -> None:
    class FailingFacade(_Facade):
        def save_interface_content(self, *args):
            raise RuntimeError("stale_revision")

    facade = FailingFacade()
    pane = InterfaceReviewPane(facade)
    pane.set_snapshot(_snapshot())
    pane.meaning_edit.setText("保留此草稿")
    errors = []
    pane.errorRaised.connect(errors.append)
    pane.save_changes()
    assert errors and "stale_revision" in errors[-1]
    assert pane.meaning_edit.text() == "保留此草稿"


def test_native_window_batch_entry_imports_each_interface_without_creating_graph(tmp_path) -> None:
    app = ensure_application()
    store, _, facade, _graph = _runtime(tmp_path)
    window = ReviewMainWindow(facade)
    try:
        window.load_batch("fresh-pane-task", "fresh-pane-batch")
        _wait(app, lambda: window.workspace is not None and not window._jobs)
        library = InterfaceContentLibrary(facade, window, pending_batch=window.workspace)
        assert library.items.count() == len(window.workspace["batch"]["interfaces"])
        assert library.items.count() >= 1
        library.items.setCurrentRow(0)
        app.processEvents()
        assert library.pane.snapshot["interface_id"]
        library.close()
    finally:
        _wait(app, lambda: not window._jobs)
        window.close()
        facade.close()
        store.close()


def test_interface_entry_scans_incoming_batches_without_selected_workspace(tmp_path) -> None:
    app = ensure_application()
    store, _, facade, _graph = _runtime(tmp_path)
    window = ReviewMainWindow(facade)
    try:
        assert window.workspace is None
        library = InterfaceContentLibrary(facade, window)
        assert library.items.count() == 3
        assert library.error.text() == ""
        library.close()
    finally:
        _wait(app, lambda: not window._jobs)
        window.close()
        facade.close()
        store.close()
