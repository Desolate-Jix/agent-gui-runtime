"""原生审核中的渐进展开与就地帮助。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QToolButton, QVBoxLayout, QWidget


class DetailsSection(QWidget):
    def __init__(self, title: str, body: QWidget, parent=None):
        super().__init__(parent)
        self.body = body
        self.toggle = QToolButton()
        self.toggle.setText(title)
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle.setObjectName("detailsToggle")
        self.toggle.setAccessibleName(title)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.addWidget(self.toggle)
        layout.addWidget(body)
        body.hide()
        self.toggle.toggled.connect(self._toggle)

    def _toggle(self, expanded: bool) -> None:
        self.body.setVisible(expanded)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)


class ReviewHelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("操作指南 · 从这里开始")
        self.resize(640, 520)
        layout = QVBoxLayout(self)
        title = QLabel("Agent 学习与决策，你随时修正和复用")
        title.setObjectName("helpTitle")
        title.setWordWrap(True)
        layout.addWidget(title)
        for heading, body in (
            ("01  新学内容", "在 Agent 中发起学习，提交后在这里接收和查看。一个界面可以独立存在，不会被强制变成流程图。"),
            ("02  点任意框修改具体信息", "右侧可编辑框名称、类型、识别文字、含义和坐标。拖框移动，拖边角改大小，也可新增或删除框。Ctrl+滚轮缩放，中键平移；原始像素100%检查清晰文字。"),
            ("03  保存即可，不用另行审核", "点“保存修改”或 Ctrl+S；内容可直接供 Agent 读取。应用信息是可选项。切换页面前先保存或放弃修改，不会偷偷丢失编辑。"),
            ("04  用流程项目组织和修改", "在“流程项目”点“＋ 添加已有界面”，按缩略图搜索、多选加入；加入不会自动补跳转。点击节点看界面、点击连线改动作和条件。项目保存后仍可继续修改，没有定稿或发布步骤。"),
            ("05  修正与持续复用", "保存的界面可“交给 Agent 修正”，比较建议后由你选择采用。项目刷新读取最新保存内容，Agent 可读取界面记忆和固定项目快照。真实操作另需确切预览和独立确认；手写连线不等于已经验证可执行。"),
        ):
            text = QLabel(f"<b>{heading}</b><br>{body}")
            text.setWordWrap(True)
            text.setMargin(8)
            layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
