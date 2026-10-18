"""仅本地原生人审持有原文；接受只冻结本次值，不批准或执行动作。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from app.agent.text_parameters import ReviewedTextParameters, resolve_text_parameters


class TextInputDialog(QDialog):
    def __init__(self, parameters: ReviewedTextParameters, parent=None):
        if type(parameters) is not ReviewedTextParameters:
            raise ValueError("text input requires reviewed parameters")
        super().__init__(parent)
        self._parameters = parameters
        self._resolved = None
        self.setWindowTitle("本次文本 · 生成预览前填写")
        self.resize(680, 440)
        layout = QVBoxLayout(self)
        source = parameters.content
        for text in (
            f"目标字段：{parameters.target_field_id}",
            "固定内容（如需修改，请返回流程审核）" if source.kind == "literal" else f"本次变量：{source.value}",
        ):
            label = QLabel(text, self)
            label.setTextFormat(Qt.TextFormat.PlainText)
            label.setWordWrap(True)
            layout.addWidget(label)
        self.mode_label = QLabel("写入方式：清空后替换" if parameters.clear_existing else "写入方式：保留原内容，在字段光标处插入", self)
        layout.addWidget(self.mode_label)
        self.text_editor = QPlainTextEdit(self)
        self.text_editor.setAccessibleName("本次实际文本")
        self.text_editor.setReadOnly(source.kind == "literal")
        if source.kind == "literal":
            self.text_editor.setPlainText(source.value)
        layout.addWidget(self.text_editor, 1)
        notice = QLabel("本窗口只准备文本，不批准也不执行。下一步仍需核对完整定位预览。\n空值是明确的本次输入；不会复用上次值。", self)
        notice.setWordWrap(True)
        layout.addWidget(notice)
        if parameters.sensitive:
            layout.addWidget(QLabel("敏感原文仅供本地人审核对，不加入 Agent 观察或普通日志。", self))
        self.error_label = QLabel("", self)
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.cancel_button = QPushButton("取消", self)
        self.continue_button = QPushButton("使用本次值生成预览", self)
        for button in (self.cancel_button, self.continue_button):
            button.setAutoDefault(False)
            buttons.addWidget(button)
        self.cancel_button.clicked.connect(self.reject)
        self.continue_button.clicked.connect(self.accept)
        layout.addLayout(buttons)

    @property
    def resolved(self):
        if self.result() != QDialog.DialogCode.Accepted or self._resolved is None:
            raise ValueError("text input has not been accepted")
        return self._resolved

    @property
    def text_values(self):
        resolved = self.resolved
        source = resolved.reviewed.content
        return {source.value: resolved.text} if source.kind == "variable" else {}

    def accept(self):
        source = self._parameters.content
        # 固定原文不从 Qt 编辑区回读，避免未编辑的 CRLF/CR 被规范成 LF。
        variables = {source.value: self.text_editor.toPlainText()} if source.kind == "variable" else {}
        try:
            self._resolved = resolve_text_parameters(self._parameters, variables)
        except ValueError:
            self.error_label.setText("内容须不超过 32768 个字符，且不能包含不支持的控制字符。")
            return
        super().accept()

    def reject(self):
        self._resolved = None
        super().reject()
