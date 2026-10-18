from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import time

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from app.desktop_review.content_library import InterfaceContentLibrary, WorkflowCompositionDialog
from app.desktop_review.interface_pane import InterfaceReviewPane
from app.desktop_review.workflow_projects_pane import WorkflowProjectsPane
from app.agent_link import AgentLinkService, AgentLinkStore
from app.desktop_review.workspace import NativeReviewFacade
from tests.test_formal_graph_review_pane import TOKEN, _runtime, _wait


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _pump(qapp: QApplication, seconds: float = 0.05) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.005)


def _item(library: InterfaceContentLibrary, interface_id: str):
    return next(library.items.item(i) for i in range(library.items.count())
                if library.items.item(i).data(Qt.ItemDataRole.UserRole)["interface_id"] == interface_id)


def test_fresh_preview_panel_review_reuse_and_failure_paths(tmp_path: Path, qapp: QApplication, monkeypatch: pytest.MonkeyPatch) -> None:
    """离屏面板验收：独立内容、审核修改、持久化、搜索、复用及故障提示。"""
    store, _, facade, _ = _runtime(tmp_path)
    try:
        library = InterfaceContentLibrary(facade)
        assert library.items.count() == 3
        first = library.items.item(0).data(Qt.ItemDataRole.UserRole)
        pane = library.pane
        assert isinstance(pane, InterfaceReviewPane)
        assert pane.title.text()
        assert pane.meaning_edit.text() == first["content"]["meaning"]
        assert pane.recognition_text_edit.text() == ""

        # 逐框字段、OCR 与几何修改均通过原生控件/信号，未注入真实鼠标。
        region = first["content"]["regions"][0]
        pane._region_selected(region["region_id"])
        pane.region_name_edit.setText("新按钮")
        pane.region_kind_edit.setText("button")
        pane.region_text_edit.setText("保存")
        pane.region_meaning_edit.setText("保存当前界面")
        pane.canvas.regionGeometryChanged.emit(region["region_id"], [9, 10, 33, 22])
        assert pane.dirty
        assert pane.add_region_button.isEnabled()
        pane.add_region()
        added_id = pane._regions[-1]["region_id"]
        assert any(r["region_id"] == added_id for r in pane._regions)
        pane.remove_selected_region()
        assert not any(r["region_id"] == added_id for r in pane._regions)

        # 脏编辑保护：搜索/切换和加入流程均不得覆盖未保存草稿。
        pane.meaning_edit.setText("未保存草稿")
        library.search.setText("state-b")
        assert "请先保存" in library.error.text() or library.pane.dirty
        current_id = pane.snapshot["interface_id"]
        library.items.setCurrentRow(1)
        assert pane.snapshot["interface_id"] == current_id
        assert pane.meaning_edit.text() == "未保存草稿"
        pane.discard_changes()
        assert not pane.dirty

        # 保存后重开，验证版本/字段/识别文字与几何持久化。
        library.items.setCurrentItem(_item(library, first["interface_id"]))
        pane.meaning_edit.setText("新的界面含义")
        pane.recognition_text_edit.setText("整页 OCR：保存")
        pane._region_selected(region["region_id"])
        pane.region_name_edit.setText("保存按钮")
        pane.canvas.regionGeometryChanged.emit(region["region_id"], [11, 12, 34, 23])
        pane.save_changes()
        saved = pane.snapshot
        assert saved["revision"] == 2
        assert saved["content"]["meaning"] == "新的界面含义"
        assert saved["content"]["recognition_text"] == "整页 OCR：保存"
        assert saved["content"]["regions"][0]["bbox"] == [11, 12, 34, 23]
        assert not pane.dirty
        library.refresh()
        reopened = _item(library, first["interface_id"])
        library.items.setCurrentItem(reopened)
        assert pane.snapshot["content"]["meaning"] == "新的界面含义"
        assert pane.snapshot["content"]["recognition_text"] == "整页 OCR：保存"

        # 搜索应仅隐藏不匹配项，且不改变已保存内容。
        library.search.setText("保存")
        assert not _item(library, first["interface_id"]).isHidden()
        assert all(library.items.item(i).isHidden() for i in range(library.items.count())
                   if library.items.item(i).data(Qt.ItemDataRole.UserRole)["interface_id"] != first["interface_id"])
        library.search.clear()

        # 同 task 的两个流程项目复用同一界面；加入不创建边，移除不删除原件。
        graph_a = facade.create_workflow_graph("面板复用 A", first["source"]["task_id"])
        graph_b = facade.create_workflow_graph("面板复用 B", first["source"]["task_id"])
        for graph in (graph_a, graph_b):
            dialog = WorkflowCompositionDialog(facade, pane.snapshot)
            try:
                target = next(dialog.graphs.item(i) for i in range(dialog.graphs.count())
                              if dialog.graphs.item(i).data(Qt.ItemDataRole.UserRole)["logical_workflow_id"] == graph["logical_workflow_id"])
                dialog.graphs.setCurrentItem(target)
                dialog._attach()
                assert "未创建跳转边" in dialog.status.text()
            finally:
                dialog.close()
        current_a = facade.load_graph_revision(graph_a["logical_workflow_id"])
        current_b = facade.load_graph_revision(graph_b["logical_workflow_id"])
        assert not current_a["graph"]["edges"] and not current_b["graph"]["edges"]
        assert any(n["interface_reference"]["interface_id"] == first["interface_id"] for n in current_a["graph"]["nodes"])
        assert any(n["interface_reference"]["interface_id"] == first["interface_id"] for n in current_b["graph"]["nodes"])

        detach = WorkflowCompositionDialog(facade, pane.snapshot)
        try:
            target = next(detach.graphs.item(i) for i in range(detach.graphs.count())
                          if detach.graphs.item(i).data(Qt.ItemDataRole.UserRole)["logical_workflow_id"] == graph_a["logical_workflow_id"])
            detach.graphs.setCurrentItem(target)
            detach._detach()
            assert "源界面和其他流程保留" in detach.status.text()
        finally:
            detach.close()
        assert facade.load_interface_content(first["interface_id"])["content"]["meaning"] == "新的界面含义"
        assert facade.load_graph_revision(graph_b["logical_workflow_id"])["graph"]["nodes"]
        assert not facade.load_graph_revision(graph_a["logical_workflow_id"])["graph"]["nodes"]

        # 读取故障必须以用户可见提示暴露，不得静默清空/伪造内容。
        original = facade.list_interface_contents
        def broken(*args, **kwargs):
            raise RuntimeError("synthetic panel read failure")
        monkeypatch.setattr(facade, "list_interface_contents", broken)
        library.refresh()
        assert "独立界面读取失败" in library.error.text()
        monkeypatch.setattr(facade, "list_interface_contents", original)
    finally:
        library.close()
        qapp.processEvents()
        facade.close()
        store.close()

def test_panel_reopens_from_disk_and_native_project_picker_round_trip(tmp_path: Path, qapp: QApplication) -> None:
    store, service, facade, _ = _runtime(tmp_path)
    library = InterfaceContentLibrary(facade)
    pane = library.pane
    first = library.items.item(0).data(Qt.ItemDataRole.UserRole)
    region = first["content"]["regions"][0]
    pane._region_selected(region["region_id"])
    pane.meaning_edit.setText("全字段保存含义")
    pane.recognition_text_edit.setText("整页识别：保存")
    pane.region_name_edit.setText("保存按钮")
    pane.region_kind_edit.setText("button")
    pane.region_text_edit.setText("保存")
    pane.region_meaning_edit.setText("提交界面修改")
    pane.canvas.regionGeometryChanged.emit(region["region_id"], [13, 14, 35, 24])
    pane.save_changes()
    saved = pane.snapshot
    assert saved["content"]["regions"][0]["name"] == "保存按钮"
    assert saved["content"]["regions"][0]["kind"] == "button"
    assert saved["content"]["regions"][0]["recognition_text"] == "保存"
    assert saved["content"]["regions"][0]["meaning"] == "提交界面修改"
    assert saved["content"]["regions"][0]["bbox"] == [13, 14, 35, 24]

    # 画布缩放/原图/适配及离屏角点拖动。
    pane.show(); qapp.processEvents()
    pane.canvas.show_actual_size(); assert round(pane.canvas.zoom_percent()) == 100
    pane.canvas.set_zoom_percent(150); assert 149 <= pane.canvas.zoom_percent() <= 151
    pane.canvas.fit_image(); assert pane.canvas.zoom_percent() != 150
    pane.canvas.show_actual_size()
    item = pane.canvas._regions[region["region_id"]]
    pane.canvas.select_region(region["region_id"]); qapp.processEvents()
    before_drag = item.bbox()
    handle = item._handles[-1]
    start = pane.canvas.mapFromScene(handle.mapToScene(QPointF(0, 0)))
    QTest.mousePress(pane.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(pane.canvas.viewport(), start + QPoint(5, 4), delay=1)
    QTest.mouseRelease(pane.canvas.viewport(), Qt.MouseButton.LeftButton, pos=start + QPoint(5, 4))
    after_drag = item.bbox()
    assert after_drag != before_drag, "QtTest corner drag did not change the native resize handle"
    assert after_drag[2] > before_drag[2] and after_drag[3] > before_drag[3]
    assert pane.dirty
    pane.save_changes()
    saved_corner_bbox = pane.snapshot["content"]["regions"][0]["bbox"]
    assert saved_corner_bbox == after_drag

    # 宿主关闭保护：必须对可见 library 本身调用 close，而不是只关闭内部 pane。
    library.show(); qapp.processEvents()
    pane.meaning_edit.setText("关闭保护草稿")
    assert pane.dirty
    library.close()
    assert library.isVisible() and pane.meaning_edit.text() == "关闭保护草稿"
    pane.discard_changes()
    library.close(); assert not library.isVisible()
    facade.close(); store.close()

    # 关闭宿主后，用相同新数据根目录重开并读取磁盘状态。
    reopened_store = AgentLinkStore(tmp_path / "fresh-pane-inbox.json")
    reopened_service = AgentLinkService(reopened_store, TOKEN)
    reopened_facade = NativeReviewFacade(reopened_service, TOKEN, tmp_path / "fresh-pane-artifacts")
    reopened_library = InterfaceContentLibrary(reopened_facade)
    try:
        loaded = _item(reopened_library, first["interface_id"]).data(Qt.ItemDataRole.UserRole)
        assert loaded["revision"] == 3
        assert loaded["content"]["meaning"] == "全字段保存含义"
        assert loaded["content"]["recognition_text"] == "整页识别：保存"
        assert loaded["content"]["regions"][0]["name"] == "保存按钮"
        assert loaded["content"]["regions"][0]["kind"] == "button"
        assert loaded["content"]["regions"][0]["recognition_text"] == "保存"
        assert loaded["content"]["regions"][0]["meaning"] == "提交界面修改"
        assert loaded["content"]["regions"][0]["bbox"] == saved_corner_bbox

        graph = reopened_facade.create_workflow_graph("原生选择器验收", first["source"]["task_id"])
        projects = WorkflowProjectsPane(reopened_facade)
        try:
            _wait(qapp, lambda: not projects.is_busy)
            projects.project_list.setCurrentRow(next(i for i in range(projects.project_list.count())
                if projects.project_list.item(i).data(Qt.ItemDataRole.UserRole) == graph["logical_workflow_id"]))
            _wait(qapp, lambda: not projects.is_busy)
            projects.attach_interface(); picker = projects.interface_picker
            deadline = time.monotonic() + 5
            while picker.busy and time.monotonic() < deadline:
                qapp.processEvents(); time.sleep(0.01)
            assert not picker.busy
            picker.search.setText("state")
            available = [picker.items.item(i) for i in range(picker.items.count())
                         if picker.items.item(i).flags() & Qt.ItemFlag.ItemIsUserCheckable]
            assert len(available) >= 2
            available[0].setCheckState(Qt.CheckState.Checked)
            available[1].setCheckState(Qt.CheckState.Checked)
            assert len(picker.selected_references()) == 2
            picker.add_selected()
            deadline = time.monotonic() + 5
            while picker.busy and time.monotonic() < deadline:
                qapp.processEvents(); time.sleep(0.01)
            qapp.processEvents()
            current = reopened_facade.load_graph_revision(graph["logical_workflow_id"])
            assert len(current["graph"]["nodes"]) == 2 and not current["graph"]["edges"]

            projects._install(reopened_facade.load_workflow_project(graph["logical_workflow_id"]))
            projects.add_edge()
            projects.edge_result.setText("目标界面出现")
            projects.edge_condition.setText("前置条件满足")
            projects.save_current()
            saved_project = reopened_facade.load_workflow_project(graph["logical_workflow_id"])
            assert len(saved_project["graph"]["edges"]) == 1
            edge_id = saved_project["graph"]["edges"][0]["edge_id"]
            projects.close()
            reopened_projects = WorkflowProjectsPane(reopened_facade)
            try:
                _wait(qapp, lambda: not reopened_projects.is_busy)
                reopened_projects._install(reopened_facade.load_workflow_project(graph["logical_workflow_id"]))
                reopened_projects.edge_selected(edge_id)
                assert reopened_projects.edge_result.text() == "目标界面出现"
                assert reopened_projects.edge_condition.text() == "前置条件满足"
                reopened_projects.remove_edge(); reopened_projects.save_current()
                node_id = reopened_projects.snapshot["graph"]["nodes"][0]["node_id"]
                reopened_projects.node_selected(node_id); reopened_projects.detach_interface()
                after = reopened_facade.load_graph_revision(graph["logical_workflow_id"])
                assert len(after["graph"]["nodes"]) == 1
                assert reopened_facade.load_interface_content(first["interface_id"])["content"]["meaning"] == "全字段保存含义"
            finally:
                _wait(qapp, lambda: not reopened_projects.is_busy)
                reopened_projects.close()
        finally:
            _wait(qapp, lambda: not projects.is_busy)
            projects.close()
    finally:
        reopened_library.close(); reopened_facade.close(); reopened_store.close()
