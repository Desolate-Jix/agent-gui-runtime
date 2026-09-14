"""本地拒绝候选的独立原因确认。"""
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QPlainTextEdit, QVBoxLayout


class RejectionReasonDialog(QDialog):
    def __init__(self, comparison: dict, reason: str, parent=None):
        super().__init__(parent)
        self.setObjectName("candidateRejectionDialog")
        self.setWindowTitle("拒绝此候选")
        self.resize(560, 310)
        layout = QVBoxLayout(self)
        label = QLabel(f"人工修订 {comparison['workspace_revision']} · {comparison['candidate_id']}\n只记录拒绝此候选；不删除原始记录、不撤回整个问题、不自动重学或执行。")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.reason_edit = QPlainTextEdit(reason)
        self.reason_edit.setObjectName("candidateRejectionReason")
        self.reason_edit.setPlaceholderText("请说明拒绝原因（1–4000 字）")
        layout.addWidget(self.reason_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.confirm_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.confirm_button.setText("记录拒绝")
        self.confirm_button.setAutoDefault(False)
        self.cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self.cancel_button.setText("取消")
        self.cancel_button.setDefault(True)
        self.confirm_button.clicked.connect(self._confirm)
        buttons.rejected.connect(self.reject)
        self.reason_edit.textChanged.connect(self._controls)
        layout.addWidget(buttons)
        self._controls()

    @property
    def reason(self):
        return self.reason_edit.toPlainText().strip()

    def _controls(self):
        self.confirm_button.setEnabled(1 <= len(self.reason) <= 4000)

    def _confirm(self):
        if 1 <= len(self.reason) <= 4000:
            self.accept()
