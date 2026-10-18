"""在后台读取同身份的新图；明确采用后旧版本与流程引用仍保留。"""
from app.learning_memory.workbench_i18n import ui, tr, bind_text, initialize_i18n, language_manager
import hashlib
from uuid import uuid4

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QVBoxLayout)
from app.desktop_review.jobs import make_job


def _local_error(error):
    raw = str(error)
    return tr(raw) if raw in {"PNG 无法显示", "原图摘要不一致", "后台任务没有返回结果"} else raw


class SourceAdoptionDialog(QDialog):
    def __init__(self, facade, snapshot, parent=None):
        super().__init__(parent)
        self.facade, self.snapshot = facade, snapshot
        self.adopted_snapshot = None
        self._job = None
        self._outcome = None
        self._closing = False
        self._candidate = None
        ui(self.setWindowTitle, tr('对比并采用新截图'))
        self.resize(1100, 720)
        layout = QVBoxLayout(self)
        help_text = ui(QLabel, tr('只列出 Agent 已标明为同一界面、同一状态的新截图。选择后对比两图。\n采用会清空旧识别框和整页识别文字，保留界面含义；之后可在界面库重新标注或交给 Agent 修正。\n旧截图和旧版本保留，现有流程仍引用原版本。此操作不截图、不操作外部软件。'))
        help_text.setWordWrap(True); layout.addWidget(help_text)
        self.items = QListWidget(); self.items.setMaximumHeight(140)
        self.items.currentItemChanged.connect(self.select_candidate); layout.addWidget(self.items)
        images = QHBoxLayout()
        self.old_image, self.new_image = ui(QLabel, tr('原图')), ui(QLabel, tr('选择新图'))
        for label in (self.old_image, self.new_image):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            scroll = QScrollArea(); scroll.setWidget(label); scroll.setWidgetResizable(True)
            images.addWidget(scroll)
        layout.addLayout(images, 1)
        self.confirm = ui(QCheckBox, tr('我确认采用此新图，并清空旧框和识别文字（旧版本仍保留）'))
        self.confirm.toggled.connect(self.sync); layout.addWidget(self.confirm)
        self.status = QLabel(); self.status.setWordWrap(True); layout.addWidget(self.status)
        controls = QHBoxLayout()
        self.refresh_button = ui(QPushButton, tr('刷新新截图')); self.refresh_button.clicked.connect(self.refresh)
        self.adopt_button = ui(QPushButton, tr('采用所选新图')); self.adopt_button.clicked.connect(self.adopt)
        controls.addWidget(self.refresh_button); controls.addWidget(self.adopt_button)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close.rejected.connect(self.reject); controls.addWidget(close); layout.addLayout(controls)
        self.refresh()

    @property
    def busy(self):
        return self._job is not None

    def sync(self):
        self.items.setEnabled(not self.busy)
        self.refresh_button.setEnabled(not self.busy)
        self.confirm.setEnabled(not self.busy and self._candidate is not None)
        self.adopt_button.setEnabled(not self.busy and self._candidate is not None and self.confirm.isChecked())

    def start(self, operation, callback):
        if self.busy:
            return
        self._operation, self._outcome = operation, None
        job = make_job(1, callback, self)
        self._job = job
        job.succeeded.connect(self._succeeded)
        job.failed.connect(self._failed)
        job.finished.connect(self._job_finished)
        ui(self.status.setText, tr('正在读取或保存，请稍候…'))
        self.sync(); job.start()

    def received(self, success, value):
        self._outcome = success, value

    # 使用有 QObject 接收者的槽，避免任务析构时释放捕获对话框的 lambda。
    @Slot(int, object)
    def _succeeded(self, request_id, value):
        self.received(True, value)

    @Slot(int, str)
    def _failed(self, request_id, value):
        self.received(False, value)

    @staticmethod
    def display(label, raw):
        image = QPixmap()
        if not image.loadFromData(raw, "PNG"):
            raise ValueError("PNG 无法显示")
        label.setPixmap(image); label.setMinimumSize(image.size())

    @Slot()
    def _job_finished(self):
        job, operation, outcome = self._job, self._operation, self._outcome
        self._job = None
        # 模态返回可能先释放对话框包装对象；在 Qt 延迟析构前解除任务的接收者引用。
        job.succeeded.disconnect(self._succeeded)
        job.failed.disconnect(self._failed)
        job.finished.disconnect(self._job_finished)
        job.deleteLater()
        try:
            if outcome is None or not outcome[0]:
                raise ValueError(outcome[1] if outcome else "后台任务没有返回结果")
            value = outcome[1]
            if operation == "list":
                self.display(self.old_image, value["old_png"])
                for row in value["candidates"]:
                    item = QListWidgetItem(row["meaning"] + " · " + row["event_id"] + " / " + row["view"])
                    item.setData(Qt.ItemDataRole.UserRole, row); self.items.addItem(item)
                ui(self.status.setText, tr('找到 {v0} 张新图。', v0=len(value['candidates'])) + (tr('扫描达到上限，当前列表不完整。') if value['truncated'] else '') + (tr('部分记录读取失败：') + str(value['errors']) if value['errors'] else ''))
            elif operation == "preview":
                self.display(self.new_image, value["png"])
                self._candidate = value["candidate"]
                ui(self.status.setText, tr('请核对两图；勾选说明后可采用。'))
            else:
                self.adopted_snapshot = value
                self.accept()
        except Exception as error:
            ui(self.status.setText, tr('操作失败：') + _local_error(error))
        self.sync()
        if self._closing:
            super().reject()

    def refresh(self):
        if self.busy:
            return
        self.items.clear(); self._candidate = None; self.confirm.setChecked(False)
        facade, interface_id, version_id = self.facade, self.snapshot["interface_id"], self.snapshot["version_id"]
        def load():
            listing = facade.list_source_candidates(interface_id)
            evidence = facade.load_interface_content_evidence(interface_id, version_id)
            raw = facade._artifact_file(evidence["image_path"], "原界面截图").read_bytes()
            if hashlib.sha256(raw).hexdigest() != evidence["sha256"]:
                raise ValueError("原图摘要不一致")
            return {**listing, "old_png": raw}
        self.start("list", load)

    def select_candidate(self, current, previous=None):
        self._candidate = None; self.confirm.setChecked(False); self.new_image.clear()
        if current is None:
            self.sync(); return
        candidate = current.data(Qt.ItemDataRole.UserRole)
        facade, interface_id = self.facade, self.snapshot["interface_id"]
        self.start("preview", lambda: facade.preview_source_candidate(interface_id, candidate))

    def adopt(self):
        if not self.adopt_button.isEnabled():
            return
        candidate = dict(self._candidate)
        # 后台闭包只持有服务和数据，不持有其所属 Qt 对话框，避免子任务析构反向销毁父对象。
        facade, interface_id = self.facade, self.snapshot["interface_id"]
        revision, digest = self.snapshot["revision"], self.snapshot["content_sha256"]
        self.start("adopt", lambda: facade.adopt_source_candidate(interface_id, candidate,
            revision, digest, "ui-source-" + uuid4().hex))

    def reject(self):
        if self.busy:
            self._closing = True
            ui(self.status.setText, tr('等待当前读取或保存结束后关闭，不中断写入。'))
            return
        super().reject()

    def closeEvent(self, event):
        if self.busy:
            self.reject(); event.ignore(); return
        super().closeEvent(event)
