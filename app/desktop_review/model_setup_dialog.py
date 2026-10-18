"""原生首次配置入口；显式保存，不启动服务或操作外部窗口。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QDialog, QVBoxLayout, QFormLayout, QLabel, QLineEdit, QSpinBox, QPushButton, QFileDialog

from .jobs import make_job


_ERRORS = {
    "model_setup_config_exists": "配置已存在，未覆盖。请关闭此窗口后使用现有配置。",
    "model_setup_model_directory_invalid": "请选择本机已存在的模型文件夹，不能填写相对路径。",
    "model_setup_model_metadata_invalid": "模型文件缺失或元数据无效。请选择完整的 VISTA-4B 分片模型目录。",
    "model_setup_port_invalid": "端口须为 1 到 65535 之间的整数。",
    "model_setup_template_missing": "安装包缺少模型模板。请检查安装包完整性。",
    "model_setup_template_invalid": "安装包模型模板无效。请检查安装包完整性。",
    "model_setup_publish_failed": "无法保存配置。请检查配置目录的写入权限和磁盘空间。",
    "model_setup_cleanup_pending": "配置可能已保存，但暂存文件清理未完成。请先检查配置目录，不要重复操作。",
    "lifecycle_busy": "当前仍有操作在进行，请等待完成后重新打开首次配置。",
    "invalid_phase": "当前目标尚未释放，请先取消本次单步验证再配置模型。",
}


def _safe_result(operation):
    try:
        return {"ok": True, "value": operation()}
    except Exception as error:
        # 不将底层 traceback、路径异常正文或未来提供器凭据送入界面。
        return {"ok": False, "code": getattr(error, "code", "model_setup_failed")}


class ModelSetupDialog(QDialog):
    def __init__(self, coordinator, parent=None):
        super().__init__(parent)
        self.coordinator = coordinator
        self._job = None
        self.setWindowTitle("首次模型配置 · VISTA-4B")
        self.setMinimumWidth(600)
        self.resize(780, 340)
        status_result = _safe_result(coordinator.model_setup_status)
        self._status_available = status_result["ok"]
        self._setup_status = status_result.get("value", {})
        layout = QVBoxLayout(self)
        layout.addWidget(self._label("选择已经下载好的 VISTA-4B 分片模型。此处仅检查必要文件并保存配置，不下载、不加载模型，也不操作外部软件。"))
        form = QFormLayout()
        self.path = QLineEdit(self)
        self.path.setAccessibleName("VISTA 模型目录")
        self.choose = QPushButton("选择模型目录…", self)
        self.destination = self._label(self._setup_status.get("config_path", "当前配置位置不可用"))
        self.port = QSpinBox(self)
        self.port.setRange(1, 65535)
        self.port.setValue(self._setup_status.get("default_port", 13244))
        self.port.setAccessibleName("本地模型端口")
        form.addRow("模型目录", self.path)
        form.addRow("", self.choose)
        form.addRow("配置保存位置", self.destination)
        form.addRow("本地端口", self.port)
        layout.addLayout(form)
        self.status = self._label("核对以上模型目录、配置位置和端口后，再点击保存。文件检查不等于模型已能推理。")
        layout.addWidget(self.status)
        self.save = QPushButton("检查并保存配置", self)
        self.save.setAutoDefault(False)
        self.close_button = QPushButton("关闭", self)
        self.close_button.setAutoDefault(False)
        layout.addWidget(self.save); layout.addWidget(self.close_button)
        self.choose.clicked.connect(self._choose)
        self.save.clicked.connect(self._save)
        self.close_button.clicked.connect(self.reject)
        self.path.textChanged.connect(self._controls)
        if not self._status_available:
            self._show_error(status_result["code"])
        elif self._setup_status.get("config_exists"):
            self._show_error("model_setup_config_exists")
        self._controls()

    def _label(self, text):
        label = QLabel(str(text), self)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setWordWrap(True)
        return label

    def _choose(self):
        selected = QFileDialog.getExistingDirectory(self, "选择 VISTA-4B 模型目录", self.path.text())
        if selected:
            self.path.setText(selected)

    def _controls(self, *_args):
        busy = self._job is not None
        editable = self._status_available and not self._setup_status.get("config_exists") and not busy
        self.save.setEnabled(editable and bool(self.path.text().strip()))
        self.choose.setEnabled(editable)
        self.path.setReadOnly(not editable)
        self.port.setEnabled(editable)
        self.close_button.setEnabled(not busy)

    def _save(self):
        if not self.save.isEnabled() or self._job is not None:
            return
        directory, port = self.path.text().strip(), self.port.value()
        self.status.setText("正在检查本地模型文件并保存配置…")
        job = make_job(1, lambda: _safe_result(lambda: self.coordinator.configure_vista_model(model_directory=directory, port=port)), self)
        self._job = job
        job.succeeded.connect(self._done)
        job.failed.connect(self._failed)
        # 必须在 start 前连接完成信号；后台可能早于 GUI 处理结果而结束。
        job.finished.connect(self._finished)
        self._controls()
        job.start()

    @Slot(int, object)
    def _done(self, _request_id, envelope):
        if envelope.get("ok") and envelope.get("value", {}).get("status") == "configured_unverified":
            self._setup_status["config_exists"] = True
            self.status.setText("配置已保存。模型尚未加载；稍后对已发布流程进行显式预检时才会启动。")
        else:
            self._show_error(envelope.get("code", "model_setup_failed"))

    def _show_error(self, code):
        if code == "model_setup_config_exists":
            self._setup_status["config_exists"] = True
        elif code == "model_setup_cleanup_pending":
            self._status_available = False
        self.status.setText(_ERRORS.get(code, "无法完成首次配置，请检查模型目录和本地运行状态后重试。"))

    @Slot(int, str)
    def _failed(self, _request_id, _traceback):
        self._show_error("model_setup_failed")

    @Slot()
    def _finished(self):
        job, self._job = self._job, None
        self._controls()
        if job is not None:
            job.deleteLater()

    def done(self, result):
        if self._job is None:
            super().done(result)

    def reject(self):
        if self._job is None:
            super().reject()

    def accept(self):
        if self._job is None:
            super().accept()

    def closeEvent(self, event):
        if self._job is not None:
            event.ignore()
        else:
            super().closeEvent(event)

