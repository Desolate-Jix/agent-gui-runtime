from __future__ import annotations

from copy import deepcopy
import time

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMessageBox

from app.desktop_review.published_graph_dialog import PublishedGraphDialog
from app.desktop_review.window import ensure_application
from app.desktop_review.workflow_memory import WorkflowMemoryError
from test_formal_graph_exact_review import BINDING, _correct_graph, _node, _runtime
from test_formal_graph_publication import _review_compile


_APP = ensure_application()


def _wait_loaded(dialog: PublishedGraphDialog) -> None:
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        _APP.processEvents()
        if not dialog._pending():
            return
        time.sleep(0.01)
    raise AssertionError("已发布图版本读取未在期限内完成")


def _dispose(dialog: PublishedGraphDialog) -> None:
    """在父测试仍持有 Python 引用时完成 Qt 的延迟销毁。"""
    assert not dialog._pending()
    destroyed: list[bool] = []
    dialog.destroyed.connect(lambda: destroyed.append(True))
    dialog.close()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    _APP.processEvents()
    assert destroyed


class _TrackingFacade:
    def __init__(self, delegate) -> None:
        self._delegate = delegate
        self.calls: list[tuple[object, ...]] = []

    def get_workflow_memory(self, allowed, workflow_id, version):
        self.calls.append(("memory", tuple(allowed), workflow_id, version))
        return self._delegate.get_workflow_memory(allowed, workflow_id, version)

    def load_graph_revision(self, workflow_id, revision):
        self.calls.append(("graph", workflow_id, revision))
        return self._delegate.load_graph_revision(workflow_id, revision)

    def __getattr__(self, name):
        return getattr(self._delegate, name)


@pytest.fixture
def _published_v1_with_v2_draft(tmp_path):
    store, _, facade, _ = _runtime(tmp_path)
    try:
        graph = _correct_graph(facade, "native-published-browse-v1")
        _, _, compiled = _review_compile(facade, graph, BINDING)
        published = facade.publish_exact_review(compiled["compile_receipt_id"])
        source = _node(graph, "state-a")
        draft = facade.apply_graph_edit(
            graph["logical_workflow_id"], graph["revision"], graph["content_sha256"],
            {
                "type": "update_node_meaning",
                "node_id": source["node_id"],
                "meaning": "Synthetic V2 draft only",
            },
            "native-published-browse-v2-draft",
        )
        assert draft["revision"] == published["graph_revision"] + 1
        yield facade, published, draft
    finally:
        facade.close()
        store.close()


def test_published_dialog_loads_the_pinned_v1_not_newer_unpublished_draft(
    _published_v1_with_v2_draft,
) -> None:
    facade, published, draft = _published_v1_with_v2_draft
    dialog = PublishedGraphDialog(facade, published)
    try:
        _wait_loaded(dialog)
        assert dialog.pane.read_only is True
        assert dialog.pane._snapshot is not None, dialog.status.text()
        assert dialog.pane._snapshot["revision"] == published["graph_revision"]
        assert dialog.pane._snapshot["content_sha256"] == published["graph_sha256"]
        assert dialog.pane._snapshot["revision"] != draft["revision"]
        assert facade.load_graph_revision(published["logical_workflow_id"])["revision"] == draft["revision"]
        assert dialog.status.toolTip() == published["version_id"]
    finally:
        _wait_loaded(dialog)
        _dispose(dialog)


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("asset_id", "asset-" + "0" * 64),
        ("asset_sha256", "0" * 64),
        ("graph_sha256", "0" * 64),
        ("graph_revision", 999),
        ("version_id", "version-" + "0" * 64),
    ),
)
def test_exact_loader_refuses_wrong_publication_binding_without_current_fallback(
    monkeypatch, _published_v1_with_v2_draft, field, replacement,
) -> None:
    facade, published, _ = _published_v1_with_v2_draft
    tracked = _TrackingFacade(facade)
    item = deepcopy(published)
    item[field] = replacement
    monkeypatch.setattr(PublishedGraphDialog, "_start", lambda self, operation, completed: None)
    dialog = PublishedGraphDialog(tracked, item)
    try:
        with pytest.raises((ValueError, WorkflowMemoryError)):
            dialog._load_exact(item)
        assert tracked.calls == [
            ("memory", (published["logical_workflow_id"],), published["logical_workflow_id"], item["version_id"]),
        ]
        assert dialog.pane._snapshot is None
    finally:
        _dispose(dialog)


@pytest.mark.parametrize("operation", ("reject", "done", "close_event"))
def test_published_dialog_refuses_close_while_async_load_is_pending(
    monkeypatch, _published_v1_with_v2_draft, operation,
) -> None:
    facade, published, _ = _published_v1_with_v2_draft
    messages = []
    monkeypatch.setattr(PublishedGraphDialog, "_start", lambda self, callback, completed: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args))
    dialog = PublishedGraphDialog(facade, published)
    dialog._jobs.add(object())
    dialog.show()
    _APP.processEvents()
    try:
        if operation == "reject":
            dialog.reject()
        elif operation == "done":
            dialog.done(1)
        else:
            event = QCloseEvent()
            dialog.closeEvent(event)
            assert not event.isAccepted()
        assert dialog.isVisible()
        assert len(messages) == 1
        assert "加载" in messages[0][-1]
    finally:
        dialog._jobs.clear()
        _dispose(dialog)
