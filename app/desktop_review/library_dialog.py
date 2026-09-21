"""已发布学习内容的检索和确切版本只读浏览。"""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .friendly_controls import DetailsSection
from .jobs import FacadeJob, make_job
from .published_graph_dialog import PublishedGraphDialog


class WorkflowLibraryDialog(QDialog):
    def __init__(self, facade: Any, parent=None) -> None:
        super().__init__(parent)
        self.facade = facade
        self._busy = False
        self._jobs: set[FacadeJob] = set()
        self._assets: list[dict] = []
        self.setWindowTitle("已学内容 · 工作流库（只读）")
        self.resize(940, 620)
        layout = QVBoxLayout(self)
        heading = QLabel("把学过的流程，留作下一次的依据")
        heading.setObjectName("helpTitle")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        hint = QLabel("选择内容和已发布版本，查看流程图与原始截图。需要复用时向 Agent 提出目标；这里不会启动执行。")
        hint.setWordWrap(True)
        hint.setProperty("role", "muted")
        layout.addWidget(hint)
        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("assetSearch")
        self.search_edit.setPlaceholderText("搜索流程名称或应用")
        self.search_edit.textChanged.connect(self._render)
        layout.addWidget(self.search_edit)
        self.asset_table = QTableWidget(0, 5)
        self.asset_table.setObjectName("assetTable")
        self.asset_table.setHorizontalHeaderLabels(["学习内容", "所属应用", "内容摘要", "内部资产 ID", "图版本"])
        self.asset_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.asset_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.asset_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.asset_table.setShowGrid(False)
        self.asset_table.setAlternatingRowColors(True)
        self.asset_table.verticalHeader().hide()
        self.asset_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.asset_table.setColumnWidth(1, 250)
        self.asset_table.setColumnWidth(4, 155)
        self.asset_table.setColumnHidden(2, True)
        self.asset_table.setColumnHidden(3, True)
        self.asset_table.itemSelectionChanged.connect(self._show_detail)
        layout.addWidget(self.asset_table, 1)
        self.selection_summary = QLabel("选中一项内容，查看可用的已发布版本。")
        self.selection_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.selection_summary.setWordWrap(True)
        layout.addWidget(self.selection_summary)
        self.asset_detail = QPlainTextEdit()
        self.asset_detail.setObjectName("assetDetail")
        self.asset_detail.setReadOnly(True)
        self.asset_detail.setMaximumHeight(125)
        self.technical = DetailsSection("查看版本指纹与技术信息", self.asset_detail)
        layout.addWidget(self.technical)
        controls = QHBoxLayout()
        self.refresh_button = QPushButton("刷新库")
        self.refresh_button.setObjectName("refreshAssetLibraryButton")
        self.refresh_button.clicked.connect(self.refresh)
        controls.addWidget(self.refresh_button)
        controls.addStretch(1)
        self.version_combo = QComboBox()
        self.version_combo.setObjectName("publishedVersionSelector")
        self.version_combo.setMinimumWidth(190)
        self.version_combo.setAccessibleName("选择已发布版本")
        self.version_combo.setPlaceholderText("请选择已发布版本")
        controls.addWidget(self.version_combo)
        self.view_graph_button = QPushButton("查看流程图")
        self.view_graph_button.setObjectName("viewPublishedGraphButton")
        self.view_graph_button.setProperty("role", "primary")
        self.view_graph_button.clicked.connect(self._view_graph)
        self.version_combo.currentIndexChanged.connect(self._version_changed)
        controls.addWidget(self.view_graph_button)
        close_buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, rejected=self.reject)
        close_buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        controls.addWidget(close_buttons)
        layout.addLayout(controls)
        self.status = QLabel("尚未读取库。")
        self.status.setWordWrap(True)
        self.status.setProperty("role", "muted")
        layout.addWidget(self.status)
        self._clear_selection()
        self.refresh()

    def _clear_selection(self) -> None:
        self.version_combo.clear()
        self.version_combo.setEnabled(False)
        self.view_graph_button.setEnabled(False)
        self.asset_detail.clear()
        self.selection_summary.setText("选中一项内容，查看可用的已发布版本。")

    def refresh(self) -> None:
        if self._busy or self._jobs:
            return
        self._busy = True
        self.refresh_button.setEnabled(False)
        self.asset_table.setEnabled(False)
        self._clear_selection()
        self.status.setText("正在读取已入库内容…")
        job = make_job(1, self.facade.list_reviewed_assets, self)
        self._jobs.add(job)
        job.succeeded.connect(self._loaded)
        job.failed.connect(self._failed)
        job.finished.connect(lambda: self._jobs.discard(job))
        job.finished.connect(job.deleteLater)
        job.start()

    def _loaded(self, _: int, assets: object) -> None:
        self._busy = False
        self.refresh_button.setEnabled(True)
        self.asset_table.setEnabled(True)
        if not isinstance(assets, list) or any(not isinstance(item, dict) for item in assets):
            self._failed(0, "库返回格式无效")
            return
        self._assets = deepcopy(assets)
        self._render()

    def _render(self) -> None:
        query = self.search_edit.text().strip().casefold()
        self.asset_table.blockSignals(True)
        try:
            self.asset_table.clearSelection()
            self.asset_table.setRowCount(0)
            for asset in self._assets:
                words = " ".join(str(asset.get(key, "")) for key in ("display_name", "application", "asset_id"))
                if query and query not in words.casefold():
                    continue
                row = self.asset_table.rowCount()
                self.asset_table.insertRow(row)
                versions = asset.get("published_graph_versions") or []
                values = (
                    asset.get("display_name", ""), asset.get("application", ""),
                    asset.get("content_sha256", ""), asset.get("asset_id", ""),
                    f"{len(versions)} 个已发布版本" if versions else "无可验证图版本",
                )
                for column, value in enumerate(values):
                    cell = QTableWidgetItem(str(value))
                    cell.setToolTip(str(value))
                    if column == 0:
                        cell.setData(Qt.ItemDataRole.UserRole, deepcopy(asset))
                    self.asset_table.setItem(row, column, cell)
        finally:
            self.asset_table.blockSignals(False)
        self._clear_selection()
        count = self.asset_table.rowCount()
        if not self._assets:
            self.status.setText("还没有入库内容。先让 Agent 提交学习结果，完成审核后再明确入库。")
        elif not count:
            self.status.setText("没有匹配的内容，换个名称或清空搜索试试。")
        else:
            self.status.setText(f"显示 {count} 项已入库内容 · 只读浏览，不会运行外部软件。")

    def _selected_asset(self) -> dict | None:
        rows = self.asset_table.selectionModel().selectedRows()
        if not rows:
            return None
        cell = self.asset_table.item(rows[0].row(), 0)
        return cell.data(Qt.ItemDataRole.UserRole) if cell is not None else None

    @staticmethod
    def _valid_versions(asset: dict) -> bool:
        versions = asset.get("published_graph_versions") or []
        if not isinstance(versions, list):
            return False
        required = ("version_id", "logical_workflow_id", "graph_sha256", "asset_id", "asset_sha256")
        return all(
            isinstance(version, dict)
            and all(isinstance(version.get(key), str) and version[key].strip() for key in required)
            and type(version.get("graph_revision")) is int and version["graph_revision"] >= 0
            and version["asset_id"] == asset.get("asset_id")
            and version["asset_sha256"] == asset.get("content_sha256")
            for version in versions
        )

    def _version_changed(self) -> None:
        self.view_graph_button.setEnabled(not self._busy and isinstance(self.version_combo.currentData(), dict))

    def _show_detail(self) -> None:
        self._clear_selection()
        asset = self._selected_asset()
        if asset is None or self._busy:
            return
        self.asset_detail.setPlainText(json.dumps(asset, ensure_ascii=False, indent=2))
        if not self._valid_versions(asset):
            self.selection_summary.setText("版本不可用：记录不完整或与当前内容不匹配。请刷新，或在开发者工具中检查。")
            return
        versions = asset.get("published_graph_versions") or []
        for version in versions:
            label = f"图修订 {version['graph_revision']} · {version['version_id'][:18]}…"
            self.version_combo.addItem(label, deepcopy(version))
            self.version_combo.setItemData(self.version_combo.count() - 1, version["version_id"], Qt.ItemDataRole.ToolTipRole)
        self.version_combo.setEnabled(bool(versions))
        self.version_combo.setCurrentIndex(-1)
        self.view_graph_button.setEnabled(False)
        name = asset.get("display_name") or "未命名内容"
        self.selection_summary.setText(
            f"{name} · 选择下方的已发布版本，再查看流程图。"
            if versions else f"{name} · 此资产没有可验证的图版本，仅可查看技术摘要。"
        )
        self.asset_detail.setPlainText(json.dumps(asset, ensure_ascii=False, indent=2))

    def _view_graph(self) -> None:
        asset = self._selected_asset()
        publication = self.version_combo.currentData()
        if self._busy or asset is None or not isinstance(publication, dict):
            return
        if (publication not in asset.get("published_graph_versions", [])
                or publication.get("asset_id") != asset.get("asset_id")
                or publication.get("asset_sha256") != asset.get("content_sha256")):
            self.status.setText("所选版本与当前资产不匹配，请刷新后重新选择。")
            return
        dialog = PublishedGraphDialog(self.facade, deepcopy(publication), self)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def _failed(self, _: int, message: str) -> None:
        self._busy = False
        self.refresh_button.setEnabled(True)
        self.asset_table.setEnabled(False)
        self._clear_selection()
        self.status.setText(f"读取工作流库失败：{message}。请刷新重试。")

    def _can_close(self) -> bool:
        if self._busy or self._jobs:
            QMessageBox.information(self, "工作流库仍在读取", "请等待本地读取结束后关闭。")
            return False
        return True

    def closeEvent(self, event) -> None:
        if not self._can_close():
            event.ignore()
            return
        event.accept()

    def reject(self) -> None:
        if self._can_close():
            super().reject()

    def done(self, result: int) -> None:
        if self._can_close():
            super().done(result)
