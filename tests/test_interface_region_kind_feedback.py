"""框类型错误必须与 bbox 错误分离，并保留面板未保存内容。"""

from copy import deepcopy

import pytest
from PySide6.QtWidgets import QApplication

from app.desktop_review.interface_pane import InterfaceReviewPane
from app.desktop_review.workspace import DesktopReviewError
from test_formal_graph_exact_review import BATCH, TASK, _runtime


_APP = QApplication.instance() or QApplication([])


def test_valid_bbox_with_invalid_kind_reports_kind_and_keeps_revision(tmp_path):
    store, _, facade, _ = _runtime(tmp_path)
    try:
        first = facade.import_interface_content(TASK, BATCH, "state-a")
        region = deepcopy(first["content"]["regions"][0])
        region["bbox"] = [2, 3, 15, 10]
        region["kind"] = "radio_button"

        with pytest.raises(DesktopReviewError, match="interface_content_region_kind_invalid"):
            facade.save_interface_content(
                first["interface_id"], first["revision"], first["content_sha256"],
                {"regions": [region]}, "invalid-kind",
            )

        assert facade.load_interface_content(first["interface_id"]) == first
    finally:
        facade.close()
        store.close()


def test_pane_lists_supported_kinds_and_preserves_invalid_pending_value(tmp_path):
    store, _, facade, _ = _runtime(tmp_path)
    pane = InterfaceReviewPane(facade)
    errors = []
    pane.errorRaised.connect(errors.append)
    try:
        first = facade.import_interface_content(TASK, BATCH, "state-a")
        pane.set_snapshot(first)
        region_id = first["content"]["regions"][0]["region_id"]
        pane._region_selected(region_id)
        pane.region_kind_edit.setText("radio_button")

        pane.save_changes()

        assert errors and "框类型不支持" in errors[-1]
        assert "unknown" in errors[-1] and "button" in errors[-1]
        assert "unknown" in pane.region_kind_edit.placeholderText()
        assert pane.region_kind_edit.text() == "radio_button"
        assert pane.dirty is True
        assert pane.snapshot["revision"] == first["revision"]
        assert facade.load_interface_content(first["interface_id"]) == first
    finally:
        pane.close()
        facade.close()
        store.close()
