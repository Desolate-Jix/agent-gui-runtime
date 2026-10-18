"""新建真实 façade 数据，验证候选比较不能隐藏证据失败或覆盖人工修改。"""
from copy import deepcopy

import pytest
from PySide6.QtWidgets import QApplication

from app.desktop_review.interface_relearning_dialog import InterfaceRelearningDialog
from app.desktop_review.interface_relearning import InterfaceRelearningService
from tests.test_formal_graph_exact_review import _runtime, TASK, BATCH

APP = QApplication.instance() or QApplication([])


@pytest.fixture
def journey(tmp_path):
    store, _, facade, _ = _runtime(tmp_path)
    snap = facade.import_interface_content(TASK, BATCH, "state-a")
    issue = facade.request_interface_relearning(snap["interface_id"], snap["revision"],
        snap["content_sha256"], [], "修改界面与框内容", "panel-real-issue")
    regions = deepcopy(snap["content"]["regions"])
    regions[0].update(name="修正框名", meaning="修正框含义", recognition_text="修正识别字", bbox=[4, 5, 20, 12])
    proposal = InterfaceRelearningService(facade).submit_candidate(TASK, issue["issue_id"],
        snap["content_sha256"], {"meaning": "修正后的独立界面", "regions": regions}, "panel-real-candidate")
    dialog = InterfaceRelearningDialog(facade, snap)
    dialog.issues.setCurrentRow(0)
    dialog.candidates.setCurrentRow(0)
    yield facade, snap, issue, proposal, dialog
    dialog.close()
    facade.close()
    store.close()


def test_real_panel_compares_same_baseline_readonly_canvases_and_latest_memory(journey):
    facade, snap, issue, proposal, dialog = journey
    assert not dialog.adopt_button.isEnabled()
    dialog.compare()
    assert dialog.adopt_button.isEnabled(), dialog.status.text()
    assert not dialog.baseline_canvas.isInteractive() and not dialog.candidate_canvas.isInteractive()
    assert dialog.baseline_canvas._pixmap_item is not None
    assert dialog.candidate_canvas._pixmap_item is not None
    assert dialog.diff_table.rowCount() >= 4
    assert "修改界面与框内容" in dialog.issues.item(0).text()
    dialog.adopt()
    assert facade.read_interface_relearning(issue["issue_id"])["status"] == "adopted"
    memory = facade.get_interface_memory(TASK, snap["interface_id"])
    assert memory["content"] == proposal["content"]
    assert memory["execute_binding_enabled"] is False


def test_failed_image_read_cannot_enable_adoption(journey, monkeypatch):
    facade, snap, issue, proposal, dialog = journey
    def missing(*_args):
        raise OSError("synthetic missing comparison image")
    monkeypatch.setattr(facade, "load_interface_content_evidence", missing)
    dialog.compare()
    assert not dialog.adopt_button.isEnabled()
    assert "失败" in dialog.status.text()
    dialog.adopt()
    assert facade.load_interface_content(snap["interface_id"])["revision"] == snap["revision"]


def test_reopened_dialog_cannot_use_latest_sha_instead_of_issue_baseline(journey):
    facade, snap, issue, proposal, dialog = journey
    latest = facade.save_interface_content(snap["interface_id"], snap["revision"],
        snap["content_sha256"], {"meaning": "人工之后又修改"}, "later-human")
    reopened = InterfaceRelearningDialog(facade, latest)
    try:
        reopened.issues.setCurrentRow(0)
        reopened.candidates.setCurrentRow(0)
        reopened.compare()
        reopened.adopt()
        assert "新修改" in reopened.status.text()
        assert facade.load_interface_content(snap["interface_id"])["content_sha256"] == latest["content_sha256"]
        assert facade.read_interface_relearning(issue["issue_id"])["status"] == "open"
    finally:
        reopened.close()
