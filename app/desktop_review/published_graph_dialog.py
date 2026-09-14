"""已发布图版本的只读浏览器。"""
from __future__ import annotations

from typing import Any

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QMessageBox, QVBoxLayout

from .graph_review_pane import GraphReviewPane
from .jobs import FacadeJob, make_job


class PublishedGraphDialog(QDialog):
    def __init__(self, facade: Any, publication: dict[str, Any], parent: Any = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("已发布流程图（只读）")
        self.resize(1100, 760)
        self.facade = facade
        self.publication = dict(publication)
        self._jobs: set[FacadeJob] = set()
        self.status = QLabel("正在校验已发布版本…")
        self.status.setWordWrap(True)
        self.pane = GraphReviewPane(facade, self, read_only=True)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, rejected=self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addWidget(self.pane, 1)
        layout.addWidget(close)
        self._load()

    def _load(self) -> None:
        item = self.publication
        self._start(lambda: self._load_exact(item), self._loaded)

    def _load_exact(self, item: dict[str, Any]) -> dict[str, Any]:
        logical = item.get("logical_workflow_id")
        version = item.get("version_id")
        memory = self.facade.get_workflow_memory([logical], logical, version)
        if memory.get("workflow_id") != logical or memory.get("version_id") != version:
            raise ValueError("已发布版本身份不一致")
        for key in ("asset_id", "asset_sha256", "graph_sha256", "graph_revision"):
            if memory.get(key) != item.get(key):
                raise ValueError("已发布版本绑定摘要不一致")
        snapshot = self.facade.load_graph_revision(logical, item["graph_revision"])
        if (snapshot.get("logical_workflow_id") != logical
                or snapshot.get("revision") != item["graph_revision"]
                or snapshot.get("content_sha256") != item["graph_sha256"]):
            raise ValueError("已发布图修订摘要不一致")
        return snapshot

    def _start(self, operation, completed) -> None:
        job = make_job(1, operation, self)
        self._jobs.add(job)
        job.succeeded.connect(lambda _request, result: completed(result))
        job.failed.connect(lambda _request, message: self._failed(message))
        job.finished.connect(lambda: self._jobs.discard(job))
        job.finished.connect(job.deleteLater)
        job.start()

    def _loaded(self, snapshot: object) -> None:
        if not isinstance(snapshot, dict):
            self._failed("图修订返回格式无效")
            return
        if not self.pane.set_revision(snapshot):
            self._failed("图修订无效，未替换当前只读内容")
            return
        self.status.setText(f"已发布图修订 {self.publication['graph_revision']} · 只读查看 · 不会修改或执行")
        self.status.setToolTip(self.publication["version_id"])

    def _failed(self, message: str) -> None:
        self.status.setText(f"无法打开已发布图：{message}")

    def _pending(self) -> bool:
        return bool(self._jobs or self.pane.is_busy or self.pane._jobs)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._pending():
            QMessageBox.information(self, "流程图仍在读取", "请等待只读流程图加载结束后关闭。")
            event.ignore()
            return
        event.accept()

    def reject(self) -> None:
        if self._pending():
            QMessageBox.information(self, "流程图仍在读取", "请等待只读流程图加载结束后关闭。")
            return
        super().reject()

    def done(self, result: int) -> None:
        if self._pending():
            QMessageBox.information(self, "流程图仍在读取", "请等待只读流程图加载结束后关闭。")
            return
        super().done(result)
