"""全新临时内容的成员管理与删除入口回归；仅使用离屏 Qt 输入。"""
import hashlib
import time

import pytest

from test_learning_memory_v1 import learned, record_search
from app.learning_memory.editor_client import MemoryEditorClient
from app.learning_memory.reader import read_project
from app.learning_memory.workspace import MemoryWorkspace


@pytest.fixture
def qt_app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def two_interfaces(learned):
    store, root, first, _ = learned
    record_search(store, "second-interface")
    second = store.control("learning_import", {"event_id": "second-interface", "view": "after",
        "regions": [{"region_id": "result", "bbox": [20, 20, 30, 20], "name": "结果",
                     "kind": "button", "meaning": "查看结果", "recognition_text": "结果"}]}, "import-second")
    return root, [first, second]


def click(widget, app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    assert widget.isVisible() and widget.isEnabled()
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton)
    app.processEvents()


def select_interface(library, interface_id, app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    item = next(library.items.item(i) for i in range(library.items.count())
                if library.items.item(i).data(256)["interface_id"] == interface_id)
    QTest.mouseClick(library.items.viewport(), Qt.MouseButton.LeftButton,
                     pos=library.items.visualItemRect(item).center())
    app.processEvents()
    assert library.pane.snapshot["interface_id"] == interface_id
    wait_idle(library.pane, app)


def composition(library, app, exercise):
    from PySide6.QtCore import QTimer
    from app.desktop_review.content_library import WorkflowCompositionDialog
    errors = []

    def respond():
        dialog = next(w for w in app.topLevelWidgets()
                      if isinstance(w, WorkflowCompositionDialog) and w.isVisible())
        try:
            exercise(dialog)
        except BaseException as error:
            errors.append(error)
        finally:
            dialog.reject()

    QTimer.singleShot(0, respond)
    click(library.pane.compose_button, app)
    if errors:
        raise errors[0]


def wait_idle(panel, app):
    deadline = time.monotonic() + 5
    while panel.is_busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    assert not panel.is_busy, panel.status.text()
    app.processEvents()


def test_membership_create_add_duplicate_and_remove_from_normal_ui(two_interfaces, qt_app):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from app.desktop_review.content_library import InterfaceContentLibrary
    from app.desktop_review.workflow_projects_pane import WorkflowProjectsPane
    root, contents = two_interfaces
    app = qt_app
    with MemoryEditorClient(root) as editor:
        library = InterfaceContentLibrary(editor, embedded=True, task_id="memory-local")
        library.show(); app.processEvents()
        panel = None
        try:
            assert editor.list_workflow_graphs() == []
            select_interface(library, contents[0]["interface_id"], app)

            def create(dialog):
                assert dialog.graphs.count() == 0
                dialog.title_edit.setText("临时成员管理项目")
                click(dialog.create, app)
                assert "已新建并加入" in dialog.status.text()
            composition(library, app, create)
            graph_id = editor.list_workflow_graphs()[0]["logical_workflow_id"]
            first_graph = editor.load_graph_revision(graph_id)
            assert len(first_graph["graph"]["nodes"]) == 1
            assert first_graph["graph"]["edges"] == []
            select_interface(library, contents[1]["interface_id"], app)

            def attach(dialog):
                assert dialog.graphs.count() == 1
                dialog.graphs.setCurrentRow(0)
                click(dialog.attach, app)
                assert "已加入流程图" in dialog.status.text()
            composition(library, app, attach)
            both = editor.load_graph_revision(graph_id)
            assert len(both["graph"]["nodes"]) == 2
            assert both["graph"]["edges"] == []
            pins = {n["interface_reference"]["interface_id"]: n["interface_reference"]["version_id"]
                    for n in both["graph"]["nodes"]}
            assert pins == {c["interface_id"]: c["version_id"] for c in contents}

            def duplicate(dialog):
                dialog.graphs.setCurrentRow(0)
                click(dialog.attach, app)
                assert "已在这个项目" in dialog.status.text()
                assert "固定版本" in dialog.status.text()
                assert "读取最新保存内容" not in dialog.status.text()
            composition(library, app, duplicate)
            assert editor.load_graph_revision(graph_id) == both

            panel = WorkflowProjectsPane(editor)
            panel.resize(1380, 900); panel.show(); wait_idle(panel, app)
            QTest.mouseClick(panel.project_list.viewport(), Qt.MouseButton.LeftButton,
                pos=panel.project_list.visualItemRect(panel.project_list.item(0)).center())
            wait_idle(panel, app)
            with MemoryWorkspace(root) as workspace:
                historical = read_project(workspace, graph_id)
            node = panel.snapshot["graph"]["nodes"][0]
            item = panel.graph_view._node_items[node["node_id"]]
            QTest.mouseClick(panel.graph_view.viewport(), Qt.MouseButton.LeftButton,
                pos=panel.graph_view.mapFromScene(item.sceneBoundingRect().center()))
            assert panel._node_id == node["node_id"]
            click(panel.remove_node_button, app)
            assert "独立界面仍在" in panel.status.text()
            assert len(panel.snapshot["graph"]["nodes"]) == 1
            assert panel.snapshot["graph"]["edges"] == []
            assert len(editor.list_interface_contents(False, "memory-local")) == 2
            with MemoryWorkspace(root) as workspace:
                assert read_project(workspace, graph_id, historical["snapshot_id"])["graph"] == historical["graph"]
        finally:
            if panel is not None:
                panel.discard_changes(); panel.cancel_loading(); wait_idle(panel, app)
                panel.close()
            library.pane.cancel_loading(); wait_idle(library.pane, app)
            library.close(); app.processEvents()


def test_open_latest_preserves_fixed_project_pin_and_explains_explicit_update(learned, qt_app):
    from app.desktop_review.content_library import InterfaceContentLibrary
    _, root, original, _ = learned
    app = qt_app
    with MemoryEditorClient(root) as editor:
        graph = editor.create_workflow_graph("固定版本项目", "memory-local")
        graph = editor.attach_interface_to_workflow(graph["logical_workflow_id"], original["interface_id"],
            original["version_id"], graph["revision"], graph["content_sha256"], "initial-pin")
        library = InterfaceContentLibrary(editor, embedded=True, task_id="memory-local")
        library.show(); app.processEvents()
        try:
            latest = editor.save_interface_content(original["interface_id"], original["revision"],
                original["content_sha256"], {"meaning": "修改后的最新界面"}, "new-revision")
            library.items.setCurrentRow(-1)
            select_interface(library, original["interface_id"], app)
            assert library.pane._read_only
            assert library.pane.snapshot["version_id"] == original["version_id"]
            click(library.latest_button, app)
            wait_idle(library.pane, app)
            assert library.pane.snapshot["version_id"] == latest["version_id"]
            assert not library.pane._read_only
            assert "固定版本" in library.error.text()
            assert "明确更新" in library.error.text()
            assert editor.load_graph_revision(graph["logical_workflow_id"]) == graph
        finally:
            library.pane.cancel_loading(); wait_idle(library.pane, app)
            library.close(); app.processEvents()


@pytest.mark.parametrize("count", [1, 2], ids=["single", "batch"])
def test_deletion_confirmation_cancel_then_delete_keeps_history(two_interfaces, qt_app, count):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QMessageBox
    from app.desktop_review.content_library import InterfaceContentLibrary
    root, contents = two_interfaces
    app = qt_app
    with MemoryEditorClient(root) as editor:
        graph = editor.create_workflow_graph("删除历史引用项目", "memory-local")
        for content in contents:
            graph = editor.attach_interface_to_workflow(graph["logical_workflow_id"], content["interface_id"],
                content["version_id"], graph["revision"], graph["content_sha256"], content["interface_id"])
        with MemoryWorkspace(root) as workspace:
            history = read_project(workspace, graph["logical_workflow_id"])
        images = {}
        for content in contents:
            evidence = editor.load_interface_content_evidence(content["interface_id"], content["version_id"])
            path = editor._artifact_file(evidence["image_path"], "历史截图")
            images[path] = hashlib.sha256(path.read_bytes()).hexdigest()
        library = InterfaceContentLibrary(editor, embedded=True, task_id="memory-local")
        library.show(); app.processEvents()
        errors = []
        prompts = []
        try:
            select_interface(library, contents[0]["interface_id"], app)
            if count == 2:
                item = next(library.items.item(i) for i in range(library.items.count())
                            if library.items.item(i).data(256)["interface_id"] == contents[1]["interface_id"])
                QTest.mouseClick(library.items.viewport(), Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.ControlModifier, pos=library.items.visualItemRect(item).center())
            selected = {item.data(256)["interface_id"] for item in library.items.selectedItems()}
            assert len(selected) == count
            assert library.delete_button.isEnabled() == (count == 1)

            def confirm(answer):
                def respond():
                    box = app.activeModalWidget()
                    try:
                        assert isinstance(box, QMessageBox)
                        assert box.defaultButton() is box.button(QMessageBox.StandardButton.Cancel)
                        assert "所有历史版本及截图仍保留" in box.text()
                        assert "删除历史引用项目" in box.text()
                        prompts.append(box.text())
                        click(box.button(answer), app)
                    except BaseException as error:
                        errors.append(error)
                        if box is not None:
                            box.reject()
                QTimer.singleShot(0, respond)
                click(library.delete_button if count == 1 else library.batch_delete_button, app)
                if errors:
                    raise errors[0]

            confirm(QMessageBox.StandardButton.Cancel)
            assert "已取消删除" in library.error.text()
            assert library.items.count() == 2
            assert {item.data(256)["interface_id"] for item in library.items.selectedItems()} == selected
            assert len(editor.list_interface_contents(False, "memory-local")) == 2
            confirm(QMessageBox.StandardButton.Yes)
            assert len(prompts) == 2
            assert f"已删除 {count} 个界面" in library.error.text()
            assert library.items.count() == 2 - count
            library.refresh()
            assert library.items.count() == 2 - count
            assert editor.load_graph_revision(graph["logical_workflow_id"]) == graph
            with MemoryWorkspace(root) as workspace:
                assert read_project(workspace, graph["logical_workflow_id"], history["snapshot_id"])["graph"] == history["graph"]
            for content in contents:
                old = editor.load_interface_content(content["interface_id"], content["version_id"])
                assert old["content_sha256"] == content["content_sha256"]
            assert all(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == sha
                       for path, sha in images.items())
        finally:
            library.pane.cancel_loading(); wait_idle(library.pane, app)
            library.close(); app.processEvents()
    with MemoryEditorClient(root) as reopened:
        library = InterfaceContentLibrary(reopened, embedded=True, task_id="memory-local")
        try:
            assert library.items.count() == 2 - count
        finally:
            library.pane.cancel_loading(); wait_idle(library.pane, app)
            library.close(); app.processEvents()
