from __future__ import annotations

import hashlib
import json
import os
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.desktop_review import library_dialog
from app.desktop_review.exact_review import ExactReviewService
from app.desktop_review.library_dialog import WorkflowLibraryDialog
from app.desktop_review.window import ensure_application


_APP = ensure_application()


def _wait_idle(dialog: WorkflowLibraryDialog) -> None:
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        _APP.processEvents()
        if not dialog._jobs and not dialog._busy:
            return
        time.sleep(0.01)
    raise AssertionError("工作流库读取未在期限内完成")


def _dispose(dialog: WorkflowLibraryDialog) -> None:
    """在测试仍持有包装对象时清空后台作业并完成延迟销毁。"""
    _wait_idle(dialog)
    destroyed: list[bool] = []
    dialog.destroyed.connect(lambda: destroyed.append(True))
    dialog.close()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()
    assert destroyed


def _publication(asset_id: str, asset_sha256: str, revision: int) -> dict:
    version_id = "version-" + f"{revision:064x}"
    return {
        "version_id": version_id,
        "logical_workflow_id": "workflow-" + f"{revision:064x}",
        "graph_revision": revision,
        "graph_sha256": f"{revision:064x}",
        "asset_id": asset_id,
        "asset_sha256": asset_sha256,
        "review_ref": f"{revision + 10:064x}",
        "approval_revision": revision,
    }


class _LibraryFacade:
    def __init__(self, assets: list[dict]) -> None:
        self._assets = assets

    def list_reviewed_assets(self) -> list[dict]:
        return self._assets


def _asset_with_two_versions() -> tuple[dict, dict, dict]:
    asset_id = "asset-" + "a" * 64
    asset_sha256 = "b" * 64
    v1, v2 = _publication(asset_id, asset_sha256, 1), _publication(asset_id, asset_sha256, 2)
    return {
        "asset_id": asset_id,
        "application": "Synthetic Editor",
        "display_name": "Synthetic workflow",
        "content_sha256": asset_sha256,
        "published_graph_versions": [v1, v2],
    }, v1, v2


def test_assets_exposes_only_registry_bound_graph_versions(monkeypatch):
    service = object.__new__(ExactReviewService)
    service.project_root = __import__("pathlib").Path(".")
    asset_sha = hashlib.sha256(json.dumps({"asset_id": "asset-1", "application": {"kind": "native", "executable": "note.exe"}}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    class Store:
        def registry(self):
            return {"active_by_asset": {"asset-1": "a" * 64, "asset-2": "b" * 64}, "workflow_versions": {
                "version-1": {"version_id": "version-1", "logical_workflow_id": "workflow-1", "graph_revision": 2, "graph_sha256": "c" * 64, "asset_id": "asset-1", "asset_sha256": asset_sha, "review_ref": "e" * 64, "approval_revision": 1}
            }}

        def load_active(self, asset_id):
            return {"asset_id": asset_id, "application": {"kind": "native", "executable": "note.exe"}}

    monkeypatch.setattr("app.desktop_review.exact_review.ReviewedWorkflowAssetStore", lambda project_root: Store())
    monkeypatch.setattr("app.desktop_review.exact_review._verified_asset_source_identity", lambda *args: None)
    rows = ExactReviewService.assets(service)
    assert rows[0]["asset_id"] == "asset-1"
    assert rows[0]["published_graph_versions"] == [{"version_id": "version-1", "logical_workflow_id": "workflow-1", "graph_revision": 2, "graph_sha256": "c" * 64, "asset_id": "asset-1", "asset_sha256": asset_sha, "review_ref": "e" * 64, "approval_revision": 1}]
    assert "published_graph_versions" not in rows[1]


def test_library_requires_explicit_version_selection_and_opens_selected_version(monkeypatch):
    asset, v1, v2 = _asset_with_two_versions()
    opened: list[dict] = []

    class PublishedDialog:
        def __init__(self, facade, publication, parent) -> None:
            opened.append(publication)

        def exec(self) -> int:
            return 0

        def deleteLater(self) -> None:
            return None

    monkeypatch.setattr(library_dialog, "PublishedGraphDialog", PublishedDialog)
    dialog = WorkflowLibraryDialog(_LibraryFacade([asset]))
    try:
        _wait_idle(dialog)
        dialog.asset_table.selectRow(0)
        _APP.processEvents()
        assert dialog.version_combo.count() == 2
        assert dialog.version_combo.currentIndex() == -1
        assert not dialog.view_graph_button.isEnabled()
        dialog.version_combo.setCurrentIndex(1)
        _APP.processEvents()
        assert dialog.version_combo.currentData()["version_id"] == v2["version_id"]
        assert dialog.view_graph_button.isEnabled()
        dialog._view_graph()
        assert opened == [v2]
        assert v1["version_id"] != v2["version_id"]
    finally:
        _dispose(dialog)


def test_library_search_clears_old_asset_and_version_selection() -> None:
    asset, _, _ = _asset_with_two_versions()
    dialog = WorkflowLibraryDialog(_LibraryFacade([asset]))
    try:
        _wait_idle(dialog)
        dialog.asset_table.selectRow(0)
        _APP.processEvents()
        assert dialog.version_combo.count() == 2
        dialog.search_edit.setText("not-present")
        _APP.processEvents()
        assert dialog.asset_table.rowCount() == 0
        assert dialog.asset_table.selectionModel().selectedRows() == []
        assert dialog.version_combo.count() == 0
        assert not dialog.version_combo.isEnabled()
        assert not dialog.view_graph_button.isEnabled()
    finally:
        _dispose(dialog)



def test_library_rejects_incomplete_published_version_without_ui_key_error() -> None:
    asset, _, _ = _asset_with_two_versions()
    asset["published_graph_versions"] = [{
        "version_id": "version-" + "1" * 64,
        "logical_workflow_id": "workflow-" + "2" * 64,
        "graph_revision_hint": -1,
        "graph_sha256": "3" * 64,
        "asset_id": asset["asset_id"],
        "asset_sha256": asset["content_sha256"],
        "review_ref": "4" * 64,
        "approval_revision": 0,
    }]
    dialog = WorkflowLibraryDialog(_LibraryFacade([asset]))
    try:
        _wait_idle(dialog)
        dialog.asset_table.selectRow(0)
        _APP.processEvents()
        dialog._show_detail()
        assert dialog.version_combo.count() == 0
        assert not dialog.version_combo.isEnabled()
        assert not dialog.view_graph_button.isEnabled()
        assert "版本不可用" in dialog.selection_summary.text()
    finally:
        _dispose(dialog)
