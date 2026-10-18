"""独立于待收件箱的流程图库；只组合已保存界面，不推断跳转。"""
from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .graph_view import NativeWorkflowGraphView
from .interface_pane import InterfaceReviewPane


class WorkflowLibraryDialog(QDialog):
    """从持久化图列表读取图和精确界面修订，不依赖当前工作区。"""

    reviewRequested = Signal(str)

    def __init__(self, facade: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.facade = facade
        self._snapshot: dict[str, Any] | None = None
        self._selected_node: dict[str, Any] | None = None
        self._reference: dict[str, str] | None = None
        self._syncing_selection = False
        self.setWindowTitle("流程图库（仅组合与审核）")
        self.resize(1180, 760)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.status = QLabel("正在读取已保存流程图。")
        self.status.setObjectName("workflowLibraryStatus")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.addWidget(QLabel("所有已保存流程图"))
        self.graph_list = QListWidget()
        self.graph_list.setObjectName("workflowLibraryGraphList")
        sidebar_layout.addWidget(self.graph_list, 2)
        sidebar_layout.addWidget(QLabel("当前图的界面节点"))
        self.node_list = QListWidget()
        self.node_list.setObjectName("workflowLibraryNodeList")
        sidebar_layout.addWidget(self.node_list, 1)
        splitter.addWidget(sidebar)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        self.graph_view = NativeWorkflowGraphView()
        self.graph_view.setObjectName("workflowLibraryGraphView")
        center_layout.addWidget(self.graph_view, 3)
        center_layout.addWidget(QLabel("添加已有界面版本（不创建跳转）"))
        self.interface_versions = QComboBox()
        self.interface_versions.setObjectName("workflowLibraryInterfaceVersions")
        center_layout.addWidget(self.interface_versions)
        membership = QHBoxLayout()
        self.add_button = QPushButton("添加已有界面")
        self.add_button.setObjectName("workflowLibraryAttachButton")
        self.remove_button = QPushButton("移除选中引用")
        self.remove_button.setObjectName("workflowLibraryDetachButton")
        membership.addWidget(self.add_button)
        membership.addWidget(self.remove_button)
        center_layout.addLayout(membership)
        splitter.addWidget(center)

        detail = QWidget()
        detail_layout = QVBoxLayout(detail)
        detail_layout.addWidget(QLabel("界面内容（精确版本）"))
        self.interface_pane = InterfaceReviewPane(self.facade)
        self.interface_pane.setObjectName("workflowLibraryInterfacePane")
        self.interface_pane.errorRaised.connect(
            lambda message: self.status.setText(f"界面内容操作失败：{message}；流程图引用未变更。")
        )
        self.interface_pane.saved.connect(self._latest_interface_changed)
        self.interface_pane.reviewed.connect(self._latest_interface_changed)
        detail_layout.addWidget(self.interface_pane, 1)
        interface_actions = QHBoxLayout()
        self.open_reference_button = QPushButton("查看界面内容")
        self.open_reference_button.setObjectName("workflowLibraryOpenReferenceButton")
        self.edit_latest_button = QPushButton("修改最新版本")
        self.edit_latest_button.setObjectName("workflowLibraryEditLatestButton")
        interface_actions.addWidget(self.open_reference_button)
        interface_actions.addWidget(self.edit_latest_button)
        detail_layout.addLayout(interface_actions)
        splitter.addWidget(detail)
        splitter.setSizes([260, 470, 450])
        layout.addWidget(splitter, 1)

        buttons = QHBoxLayout()
        self.refresh_button = QPushButton("刷新流程图库")
        self.review_button = QPushButton("审核流程")
        self.close_button = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.review_button)
        buttons.addStretch(1)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

        self.graph_list.currentItemChanged.connect(self._graph_selected)
        self.node_list.currentItemChanged.connect(self._node_selected)
        self.node_list.itemDoubleClicked.connect(lambda _item: self.open_exact_reference())
        self.graph_view.nodeSelected.connect(self._graph_node_selected)
        self.refresh_button.clicked.connect(self.refresh)
        self.add_button.clicked.connect(self.attach_selected_interface)
        self.remove_button.clicked.connect(self.detach_selected_reference)
        self.open_reference_button.clicked.connect(self.open_exact_reference)
        self.edit_latest_button.clicked.connect(self.edit_latest_interface)
        self.review_button.clicked.connect(self.request_review)
        self.close_button.rejected.connect(self.reject)
        self._set_action_state()

    def refresh(self) -> None:
        if not self._allow_replace_interface():
            return
        selected = self._snapshot.get("logical_workflow_id") if self._snapshot else None
        try:
            graphs = self.facade.list_workflow_graphs()
            if not isinstance(graphs, list):
                raise ValueError("流程图库返回无效列表")
        except Exception as error:
            self._show_error("读取流程图库失败", error)
            return
        self.graph_list.blockSignals(True)
        self.graph_list.clear()
        restore_row = -1
        for index, graph in enumerate(graphs):
            if not isinstance(graph, dict) or not isinstance(graph.get("logical_workflow_id"), str):
                continue
            title = str(graph.get("title") or graph["logical_workflow_id"])
            item = QListWidgetItem(f"{title} · r{graph.get('revision', '?')}")
            item.setData(Qt.ItemDataRole.UserRole, deepcopy(graph))
            self.graph_list.addItem(item)
            if graph["logical_workflow_id"] == selected:
                restore_row = index
        self.graph_list.blockSignals(False)
        if self.graph_list.count() == 0:
            self._clear_graph("当前没有已保存流程图。请先在界面内容的“加入流程”中明确新建流程；不会从待收件箱或当前工作区推断流程。")
            return
        self.graph_list.setCurrentRow(restore_row if restore_row >= 0 else 0)

    def _graph_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        graph = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        logical_id = graph.get("logical_workflow_id") if isinstance(graph, dict) else None
        if not isinstance(logical_id, str):
            self._clear_graph("请选择一个已保存流程图。")
            return
        if self._snapshot is not None and logical_id != self._snapshot.get("logical_workflow_id") and not self._allow_replace_interface():
            self._restore_graph_selection()
            return
        try:
            snapshot = self.facade.load_graph_revision(logical_id)
            if snapshot.get("logical_workflow_id") != logical_id:
                raise ValueError("流程图身份不匹配")
            self._set_snapshot(snapshot)
        except Exception as error:
            self._clear_graph(f"加载流程图失败：{error}")

    def _set_snapshot(self, snapshot: dict[str, Any]) -> None:
        self._snapshot = deepcopy(snapshot)
        self._selected_node = None
        self._reference = None
        self.graph_view.set_revision(snapshot)
        self.interface_pane.setVisible(False)
        self.node_list.blockSignals(True)
        self.node_list.clear()
        for node in snapshot.get("graph", {}).get("nodes", []):
            if not isinstance(node, dict) or not isinstance(node.get("node_id"), str):
                continue
            item = QListWidgetItem(str(node.get("display_name") or node["node_id"]))
            item.setData(Qt.ItemDataRole.UserRole, deepcopy(node))
            self.node_list.addItem(item)
        self.node_list.blockSignals(False)
        self._load_interface_versions()
        edges = snapshot.get("graph", {}).get("edges", [])
        if not edges:
            self.status.setText("此流程仅组合界面，尚未学习跳转；不能执行或发布。")
        else:
            self.status.setText(f"已加载流程图 r{snapshot.get('revision')}；仅供人工审核，不执行动作。")
        self.interface_pane.set_read_only(True)
        self._set_action_state()

    def _load_interface_versions(self) -> None:
        self.interface_versions.clear()
        try:
            current = self.facade.list_interface_contents(False)
            reviewed = self.facade.list_interface_contents(True)
            values: dict[tuple[str, str], dict] = {}
            for value in [*current, *reviewed]:
                if isinstance(value, dict) and isinstance(value.get("interface_id"), str) and isinstance(value.get("version_id"), str):
                    values[(value["interface_id"], value["version_id"])] = deepcopy(value)
            for value in sorted(values.values(), key=lambda item: (item["interface_id"], item["version_id"])):
                label = str(value.get("content", {}).get("meaning") or value["interface_id"])
                self.interface_versions.addItem(f"{label} · r{value.get('revision')} · {value.get('review_status')}", value)
        except Exception as error:
            self.interface_versions.clear()
            self._show_error("读取可加入界面失败", error)

    def _node_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None) -> None:
        node = current.data(Qt.ItemDataRole.UserRole) if current is not None else None
        if (isinstance(node, dict) and self._selected_node is not None
                and node.get("node_id") != self._selected_node.get("node_id")
                and not self._allow_replace_interface()):
            self._restore_node_selection()
            return
        if not isinstance(node, dict) or self._selected_node is None or node.get("node_id") != self._selected_node.get("node_id"):
            self._reference = None
            self.interface_pane.setVisible(False)
        self._selected_node = deepcopy(node) if isinstance(node, dict) else None
        if self._selected_node is not None and not self._syncing_selection:
            try:
                self._syncing_selection = True
                self.graph_view.select_node(self._selected_node["node_id"])
            except (KeyError, ValueError):
                pass
            finally:
                self._syncing_selection = False
        self._set_action_state()

    def _graph_node_selected(self, node_id: str) -> None:
        if self._syncing_selection:
            return
        for row in range(self.node_list.count()):
            item = self.node_list.item(row)
            node = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(node, dict) and node.get("node_id") == node_id:
                if self._selected_node is not None and node_id != self._selected_node["node_id"] and not self._allow_replace_interface():
                    self.graph_view.select_node(self._selected_node["node_id"])
                    return
                self._syncing_selection = True
                try:
                    self.node_list.setCurrentRow(row)
                finally:
                    self._syncing_selection = False
                self._selected_node = deepcopy(node)
                self._set_action_state()
                return

    def _selected_reference(self) -> dict[str, str] | None:
        reference = self._selected_node.get("interface_reference") if isinstance(self._selected_node, dict) else None
        if not isinstance(reference, dict) or set(reference) != {"interface_id", "version_id", "content_sha256"}:
            return None
        if not all(isinstance(reference.get(key), str) and reference[key] for key in reference):
            return None
        return {key: reference[key] for key in ("interface_id", "version_id", "content_sha256")}

    def open_exact_reference(self) -> None:
        if not self._allow_replace_interface():
            return
        reference = self._selected_reference()
        if reference is None:
            self.status.setText("选中的节点没有独立界面版本引用，不能打开界面内容。")
            return
        try:
            snapshot = self.facade.load_interface_content(reference["interface_id"], reference["version_id"])
            if (snapshot.get("interface_id"), snapshot.get("version_id"), snapshot.get("content_sha256")) != (
                reference["interface_id"], reference["version_id"], reference["content_sha256"],
            ):
                raise ValueError("界面版本引用不匹配")
            self.interface_pane.set_snapshot(snapshot)
            self.interface_pane.set_read_only(True)
            self.interface_pane.setVisible(True)
            self._reference = reference
            self.status.setText("已打开本图引用的精确界面版本；该版本只读，不能保存或审核。")
        except Exception as error:
            self._show_error("打开精确界面版本失败", error)
        self._set_action_state()

    def edit_latest_interface(self) -> None:
        if not self._allow_replace_interface():
            return
        if self._reference is None:
            self.status.setText("请先查看本图引用的精确界面版本。")
            return
        try:
            latest = self.facade.load_interface_content(self._reference["interface_id"])
            self.interface_pane.set_snapshot(latest)
            self.interface_pane.set_read_only(False)
            self.status.setText("正在修改最新界面版本；本图仍引用旧版，不会自动采用修改结果。")
        except Exception as error:
            self._show_error("打开最新界面版本失败", error)
        self._set_action_state()

    def attach_selected_interface(self) -> None:
        if not self._allow_replace_interface():
            return
        if self._snapshot is None:
            self.status.setText("请先选择一个流程图。")
            return
        value = self.interface_versions.currentData()
        if not isinstance(value, dict):
            self.status.setText("请先选择一个已保存界面版本。")
            return
        try:
            snapshot = self.facade.attach_interface_to_workflow(
                self._snapshot["logical_workflow_id"], value["interface_id"], value["version_id"],
                self._snapshot["revision"], self._snapshot["content_sha256"], uuid4().hex,
            )
            self._set_snapshot(snapshot)
            self.status.setText("已加入界面版本；未创建或推断跳转。")
        except Exception as error:
            self._show_error("添加已有界面失败", error)

    def detach_selected_reference(self) -> None:
        if not self._allow_replace_interface():
            return
        reference = self._selected_reference()
        if self._snapshot is None or reference is None:
            self.status.setText("请选择一个带独立界面引用的节点。")
            return
        try:
            snapshot = self.facade.detach_interface_from_workflow(
                self._snapshot["logical_workflow_id"], reference["interface_id"], reference["version_id"],
                self._snapshot["revision"], self._snapshot["content_sha256"], uuid4().hex,
            )
            self._set_snapshot(snapshot)
            self.status.setText("已移除界面引用；未修改独立界面内容。")
        except Exception as error:
            self._show_error("移除界面引用失败", error)

    def request_review(self) -> None:
        if not self._allow_replace_interface():
            return
        if self._snapshot is None:
            self.status.setText("请先选择一个流程图。")
            return
        logical_id = self._snapshot["logical_workflow_id"]
        self.reviewRequested.emit(logical_id)
        self.status.setText("已请求打开流程审核；审核、发布和执行仍是独立步骤。")
        self.accept()

    def _set_action_state(self) -> None:
        reference = self._selected_reference()
        has_graph = self._snapshot is not None
        self.add_button.setEnabled(has_graph and self.interface_versions.count() > 0)
        self.remove_button.setEnabled(has_graph and reference is not None)
        self.open_reference_button.setEnabled(reference is not None)
        self.edit_latest_button.setEnabled(self._reference is not None)
        self.review_button.setEnabled(has_graph)

    def _clear_graph(self, message: str) -> None:
        self._snapshot = None
        self._selected_node = None
        self._reference = None
        self.node_list.clear()
        self.interface_versions.clear()
        self.graph_view.clear_graph()
        self.interface_pane.set_read_only(True)
        self.interface_pane.setVisible(False)
        self.status.setText(message)
        self._set_action_state()

    def _show_error(self, action: str, error: Exception) -> None:
        self.status.setText(f"{action}：{error}；当前已显示内容未被替换。")

    def _latest_interface_changed(self, _snapshot: object) -> None:
        self._load_interface_versions()
        if self._reference is not None:
            self.status.setText("最新界面版本已更新；本图仍引用旧版，不会自动采用修改结果。")

    def _allow_replace_interface(self) -> bool:
        if not self.interface_pane.dirty:
            return True
        self.status.setText("界面内容有未保存修改：请先保存或放弃，再切换、刷新、审核或关闭流程图库。")
        return False

    def _restore_graph_selection(self) -> None:
        if self._snapshot is None:
            return
        logical_id = self._snapshot.get("logical_workflow_id")
        self.graph_list.blockSignals(True)
        try:
            for row in range(self.graph_list.count()):
                item = self.graph_list.item(row)
                graph = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(graph, dict) and graph.get("logical_workflow_id") == logical_id:
                    self.graph_list.setCurrentRow(row)
                    return
        finally:
            self.graph_list.blockSignals(False)

    def _restore_node_selection(self) -> None:
        if self._selected_node is None:
            return
        node_id = self._selected_node.get("node_id")
        self.node_list.blockSignals(True)
        try:
            for row in range(self.node_list.count()):
                item = self.node_list.item(row)
                node = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(node, dict) and node.get("node_id") == node_id:
                    self.node_list.setCurrentRow(row)
                    return
        finally:
            self.node_list.blockSignals(False)

    def reject(self) -> None:
        if self._allow_replace_interface():
            super().reject()

    def closeEvent(self, event: Any) -> None:
        if self._allow_replace_interface():
            super().closeEvent(event)
        else:
            event.ignore()


__all__ = ["WorkflowLibraryDialog"]
