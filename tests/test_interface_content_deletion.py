from __future__ import annotations

from copy import deepcopy
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from app.desktop_review import interface_content
from app.desktop_review.content_library import InterfaceContentLibrary
from app.desktop_review.workspace import DesktopReviewError, NativeReviewFacade
from test_formal_graph_exact_review import BATCH, BINDING, TASK, TOKEN, _runtime


_APP = QApplication.instance() or QApplication([])


@pytest.fixture
def runtime(tmp_path):
    store, service, facade, original = _runtime(tmp_path)
    try:
        yield facade, service, original
    finally:
        facade.close()
        store.close()


def _request(value):
    return {"interface_id": value["interface_id"], "expected_revision": value["revision"],
            "expected_sha256": value["content_sha256"]}


def _contents(facade):
    return [facade.import_interface_content(TASK, BATCH, name) for name in ("state-a", "state-b", "state-c")]


def _registry_path(tmp_path):
    return tmp_path / "fresh-artifacts" / "desktop-review" / "interface-contents" / "registry.json"


def test_delete_survives_refresh_and_reopen_without_losing_history_or_screenshots(runtime, tmp_path):
    facade, service, original = runtime
    values = _contents(facade)
    first = values[0]
    reviewed = facade.review_interface_content(first["interface_id"], first["revision"], first["content_sha256"], deepcopy(BINDING))
    latest = facade.save_interface_content(first["interface_id"], first["revision"], first["content_sha256"], {"meaning": "Saved deletion candidate"}, "delete-save")
    evidence = facade.load_interface_content_evidence(first["interface_id"], first["version_id"])
    image = facade._artifact_file(evidence["image_path"], "synthetic screenshot")
    image_before = image.read_bytes()
    versions = list((_registry_path(tmp_path).parent / first["interface_id"] / "revisions").glob("*.json"))
    version_bytes = {path: path.read_bytes() for path in versions}
    result = facade.delete_interface_content(latest["interface_id"], latest["revision"], latest["content_sha256"])
    assert result["deleted_count"] == 1 and result["graph_references_preserved"]
    assert facade.delete_interface_contents([_request(latest)])["already_deleted_count"] == 1
    assert first["interface_id"] not in {item["interface_id"] for item in facade.list_interface_contents()}
    assert facade.list_interface_contents(True) == []
    assert facade.search_interface_memory(TASK, "Saved deletion candidate") == []
    assert facade.load_interface_content(first["interface_id"], first["version_id"]) == reviewed
    assert facade.load_interface_content(first["interface_id"]) == latest
    assert image.read_bytes() == image_before
    assert all(path.read_bytes() == raw for path, raw in version_bytes.items())
    with pytest.raises(DesktopReviewError, match="interface_content_deleted"):
        facade.import_interface_content(TASK, BATCH, "state-a")
    with pytest.raises(DesktopReviewError, match="interface_content_deleted"):
        facade.save_interface_content(latest["interface_id"], latest["revision"], latest["content_sha256"], {"meaning": "revive"}, "revive")
    with pytest.raises(DesktopReviewError, match="interface_content_deleted"):
        facade.review_interface_content(latest["interface_id"], latest["revision"], latest["content_sha256"], deepcopy(BINDING))
    facade.close()
    reopened = NativeReviewFacade(service, TOKEN, tmp_path / "fresh-artifacts")
    try:
        assert len(reopened.list_interface_contents()) == 2
        assert len(reopened.list_interface_contents_for_reference(TASK)) == 3
        with pytest.raises(DesktopReviewError, match="interface_content_deleted"):
            reopened.import_interface_content(TASK, BATCH, "state-a")
        assert service.reviewer_call(TOKEN, "get_batch", {"task_id": TASK, "batch_id": BATCH})["batch"]["interfaces"]
        assert reopened.load_interface_content(first["interface_id"], first["version_id"]) == reviewed
    finally:
        reopened.close()


def test_batch_stale_or_duplicate_selection_writes_nothing(runtime, tmp_path):
    facade, _, _ = runtime
    values = _contents(facade)
    latest = facade.save_interface_content(values[1]["interface_id"], 1, values[1]["content_sha256"], {"meaning": "Changed elsewhere"}, "outside-save")
    before = _registry_path(tmp_path).read_bytes()
    with pytest.raises(DesktopReviewError, match="stale_revision"):
        facade.delete_interface_contents([_request(values[0]), _request(values[1])])
    with pytest.raises(DesktopReviewError, match="selection_duplicate"):
        facade.delete_interface_contents([_request(values[0]), _request(values[0])])
    with pytest.raises(DesktopReviewError, match="selection_invalid"):
        facade.delete_interface_contents([])
    assert _registry_path(tmp_path).read_bytes() == before
    assert len(facade.list_interface_contents()) == 3
    result = facade.delete_interface_contents([_request(values[0]), _request(latest)])
    assert result["deleted_count"] == 2
    assert [item["interface_id"] for item in facade.list_interface_contents()] == [values[2]["interface_id"]]


def test_batch_write_failure_does_not_partially_delete(runtime, tmp_path, monkeypatch):
    facade, _, _ = runtime
    values = _contents(facade)
    before = _registry_path(tmp_path).read_bytes()
    original_write = interface_content._atomic_write_bytes
    writes = []

    def fail(path, data):
        if path.name == "registry.json":
            writes.append(path)
            raise OSError("synthetic deletion write failure")
        return original_write(path, data)

    monkeypatch.setattr(interface_content, "_atomic_write_bytes", fail)
    with pytest.raises(OSError, match="synthetic deletion"):
        facade.delete_interface_contents([_request(item) for item in values])
    assert len(writes) == 1
    assert _registry_path(tmp_path).read_bytes() == before
    assert len(facade.list_interface_contents()) == 3
    monkeypatch.setattr(interface_content, "_atomic_write_bytes", original_write)
    assert facade.delete_interface_contents([_request(item) for item in values])["deleted_count"] == 3


def test_tombstone_corruption_is_not_silently_reimported(runtime, tmp_path):
    facade, _, _ = runtime
    item = _contents(facade)[0]
    facade.delete_interface_contents([_request(item)])
    path = _registry_path(tmp_path)
    value = json.loads(path.read_text(encoding="utf-8"))
    value["tombstones"][item["interface_id"]]["content_sha256"] = "broken"
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(DesktopReviewError, match="tombstones_invalid"):
        facade.import_interface_content(TASK, BATCH, "state-a")
    with pytest.raises(DesktopReviewError, match="tombstones_invalid"):
        facade.list_interface_contents()


@pytest.mark.parametrize("detach", [False, True])
def test_delete_retains_current_and_historical_graph_references(runtime, tmp_path, detach):
    facade, _, _ = runtime
    item = _contents(facade)[0]
    graph = facade.create_workflow_graph("Synthetic retained project", TASK)
    attached = facade.attach_interface_to_workflow(graph["logical_workflow_id"], item["interface_id"], item["version_id"],
        graph["revision"], graph["content_sha256"], "attach-before-delete")
    latest = attached
    if detach:
        latest = facade.detach_interface_from_workflow(attached["logical_workflow_id"], item["interface_id"], item["version_id"],
            attached["revision"], attached["content_sha256"], "detach-before-delete")
    graph_files = {path: path.read_bytes() for path in (tmp_path / "fresh-artifacts" / "desktop-review" / "graph-revisions").rglob("*.json")}
    preview = facade.preview_interface_content_deletion([_request(item)])
    ref = preview["items"][0]["references"][0]
    assert ref["title"] == "Synthetic retained project"
    assert ref["current_reference"] is not detach
    assert ref["revisions"] == [attached["revision"]]
    facade.delete_interface_contents([_request(item)])
    assert facade.load_graph_revision(graph["logical_workflow_id"]) == latest
    assert facade.load_graph_revision(graph["logical_workflow_id"], attached["revision"]) == attached
    assert all(path.read_bytes() == raw for path, raw in graph_files.items())
    if not detach:
        assert facade.load_workflow_project(graph["logical_workflow_id"])["graph"]["nodes"][0]["regions"]


def test_delete_preview_finds_indirect_source_reference(runtime):
    facade, _, _ = runtime
    item = _contents(facade)[0]
    graph = facade.create_graph_revision(TASK, BATCH, 0, {"open-result": ["rel-open"]})
    preview = facade.preview_interface_content_deletion([_request(item)])
    assert preview["items"][0]["references"][0]["logical_workflow_id"] == graph["logical_workflow_id"]
    facade.delete_interface_contents([_request(item)])
    assert facade.load_graph_revision(graph["logical_workflow_id"]) == graph


def test_offscreen_delete_confirmation_names_referenced_project(runtime, monkeypatch):
    facade, _, _ = runtime
    item = _contents(facade)[0]
    graph = facade.create_workflow_graph("必须保留的流程项目", TASK)
    facade.attach_interface_to_workflow(graph["logical_workflow_id"], item["interface_id"], item["version_id"],
        graph["revision"], graph["content_sha256"], "confirm-project-reference")
    library = InterfaceContentLibrary(facade)
    try:
        target = next(index for index in range(library.items.count())
                      if library.items.item(index).data(256)["interface_id"] == item["interface_id"])
        library.items.setCurrentRow(target)
        prompts = []
        monkeypatch.setattr(QMessageBox, "question", lambda *args: prompts.append(args) or QMessageBox.StandardButton.Cancel)
        library.delete_button.click()
        assert "引用项目：必须保留的流程项目" in prompts[0][2]
        assert "流程引用、所有历史版本及截图仍保留" in prompts[0][2]
        assert len(facade.list_interface_contents()) == 3
    finally:
        library.close()


def test_offscreen_single_delete_cancel_then_confirm_and_pending_refresh(runtime, monkeypatch, tmp_path):
    facade, _, _ = runtime
    library = InterfaceContentLibrary(facade, pending_batch=facade.load_batch(TASK, BATCH))
    try:
        selected = library.pane.snapshot
        assert library.delete_button.text() == "删除界面"
        assert library.batch_delete_button.text() == "批量删除"
        assert library.delete_button.isEnabled()
        prompts = []

        def cancel(parent, title, message, buttons, default):
            prompts.append(message)
            assert default == QMessageBox.StandardButton.Cancel
            return QMessageBox.StandardButton.Cancel

        monkeypatch.setattr(QMessageBox, "question", cancel)
        library.delete_button.click()
        assert len(prompts) == 1 and "历史版本及截图仍保留" in prompts[0]
        assert library.items.count() == 3 and library.pane.snapshot == selected
        assert "已取消" in library.error.text()
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
        library.delete_button.click()
        assert library.items.count() == 2
        assert "已删除 1 个界面" in library.error.text()
        library.refresh()
        assert library.items.count() == 2 and "导入失败" not in library.error.text()
        library.show()
        _APP.processEvents()
        screenshot = tmp_path / "interface-deletion-offscreen.png"
        assert library.grab().save(str(screenshot)) and screenshot.stat().st_size > 1000
    finally:
        library.close()


def test_offscreen_multi_selection_dirty_protection_and_clear_empty_state(runtime, monkeypatch):
    facade, _, _ = runtime
    library = InterfaceContentLibrary(facade)
    try:
        library.items.item(1).setSelected(True)
        assert len(library.items.selectedItems()) == 2
        assert not library.delete_button.isEnabled() and library.batch_delete_button.isEnabled()
        library.pane.meaning_edit.setText("未保存的修改")
        prompts = []
        monkeypatch.setattr(QMessageBox, "question", lambda *args: prompts.append(args) or QMessageBox.StandardButton.Yes)
        library.batch_delete_button.click()
        assert not prompts and "未保存" in library.error.text()
        assert library.pane.meaning_edit.text() == "未保存的修改"
        assert len(facade.list_interface_contents()) == 3
        library.pane.discard_changes()
        library.items.selectAll()
        library.batch_delete_button.click()
        assert len(prompts) == 1 and "删除 3 个界面" in prompts[0][2]
        assert library.items.count() == 0 and library.pane.snapshot is None
        assert not library.delete_button.isEnabled() and not library.batch_delete_button.isEnabled()
        library.refresh()
        assert library.items.count() == 0
    finally:
        library.pane.discard_changes()
        library.close()


def test_offscreen_stale_selection_aborts_before_confirmation(runtime, monkeypatch):
    facade, _, _ = runtime
    library = InterfaceContentLibrary(facade)
    try:
        value = library.pane.snapshot
        facade.save_interface_content(value["interface_id"], value["revision"], value["content_sha256"], {"meaning": "External newer edit"}, "delete-ui-stale")
        prompts = []
        monkeypatch.setattr(QMessageBox, "question", lambda *args: prompts.append(args) or QMessageBox.StandardButton.Yes)
        library.items.selectAll()
        library.batch_delete_button.click()
        assert not prompts and "stale_revision" in library.error.text()
        assert library.items.count() == 3 and len(facade.list_interface_contents()) == 3
    finally:
        library.close()


def test_offscreen_search_deselects_hidden_items(runtime, monkeypatch):
    facade, _, _ = runtime
    library = InterfaceContentLibrary(facade)
    try:
        library.items.selectAll()
        value = library.items.item(0).data(256)
        library.search.setText(value["content"]["meaning"])
        assert len(library.items.selectedItems()) == 1
        monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
        library.batch_delete_button.click()
        assert len(facade.list_interface_contents()) == 2
    finally:
        library.close()


def test_offscreen_observation_filter_and_learning_flow_keep_ordinary_empty_content(runtime, monkeypatch):
    from app.desktop_review import learning_catalog

    facade, _, _ = runtime
    values = _contents(facade)
    empty = values[2]
    facade.save_interface_content(empty["interface_id"], empty["revision"], empty["content_sha256"], {"regions": []}, "ordinary-empty")
    annotate = learning_catalog.annotate_learning_content

    def annotated(owner, value):
        result = annotate(owner, value)
        if value["source"]["external_interface_id"] == "state-a":
            result["learning_status"] = "observation_only"
            result["learning_flow"] = {"logical_workflow_id": "synthetic-observation-flow", "title": "Synthetic flow"}
        return result

    monkeypatch.setattr(learning_catalog, "annotate_learning_content", annotated)
    library = InterfaceContentLibrary(facade)
    try:
        assert library.items.count() == 2
        assert any(not library.items.item(index).data(256)["content"]["regions"] for index in range(2))
        assert not library.learning_flow_button.isEnabled()
        assert len(facade.search_interface_memory(TASK)) == 2
        original_memory = facade.get_interface_memory(TASK, values[0]["interface_id"])
        assert original_memory["learning_status"] == "observation_only"
        assert original_memory["learning_flow"]["logical_workflow_id"] == "synthetic-observation-flow"
        assert original_memory["artifact_is_authorization"] is False
        opened = []
        library.openLearningFlow.connect(opened.append)
        library.filter.setCurrentIndex(3)
        assert library.items.count() == 1 and "原始观察" in library.items.item(0).text()
        assert library.learning_flow_button.isEnabled()
        library.learning_flow_button.click()
        assert opened == ["synthetic-observation-flow"]
        library.pane.meaning_edit.setText("尚未保存")
        library.learning_flow_button.click()
        assert opened == ["synthetic-observation-flow"] and "先保存" in library.error.text()
        library.pane.discard_changes()
    finally:
        library.close()
