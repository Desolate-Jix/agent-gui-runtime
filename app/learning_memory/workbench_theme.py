"""仅作用于学习工作台子树的浅色主题。"""
from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QPushButton, QWidget

from .workbench_icons import workbench_icon
from .workbench_i18n import bound_text


_STYLE = """
QWidget { color: #252525; font-size: 14px; }
QMainWindow, QDialog { background: #f6f6f6; }
QMainWindow#memoryWindow { background: transparent; }
QWidget#memoryHeader { background: #f6f6f6; border-bottom: 1px solid #e7e7e7; }
QToolBar#memoryHeader { background: #f6f6f6; border: none; border-bottom: 1px solid #e7e7e7; spacing: 6px; padding: 6px 8px; }
QToolBar#memoryHeader QToolButton { background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 8px; }
QToolBar#memoryHeader QToolButton:hover { background: #eeeeee; }
QToolBar#memoryHeader QToolButton:pressed { background: #e7e7e7; }
QToolBar#memoryHeader QToolButton:focus { border-color: #2563eb; }
QToolBar#memoryHeader QToolButton:disabled { color: #989898; }
QLabel#memoryBrand { font-size: 18px; font-weight: 600; padding: 0 10px; }
QLabel { background: transparent; }
QLabel[role="muted"] { color: #737373; }
QGroupBox { background: white; border: 1px solid #e5e5e5; border-radius: 10px; margin-top: 12px; padding: 14px 10px 10px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 4px; font-weight: 600; }
QPushButton { background: white; border: 1px solid #dedede; border-radius: 8px; min-height: 30px; padding: 0 10px; }
QPushButton:hover { background: #f0f0f0; border-color: #c8c8c8; }
QPushButton:pressed { background: #e7e7e7; }
QPushButton:focus { border-color: #2563eb; }
QPushButton:disabled { background: #f5f5f5; color: #989898; border-color: #e7e7e7; }
QPushButton[primary="true"], QPushButton[role="primary"] { background: #2563eb; color: white; border-color: #2563eb; }
QPushButton[primary="true"]:hover, QPushButton[role="primary"]:hover { background: #1d4ed8; border-color: #1d4ed8; }
QPushButton[primary="true"]:pressed, QPushButton[role="primary"]:pressed { background: #1e40af; border-color: #1e40af; }
QPushButton[primary="true"]:disabled, QPushButton[role="primary"]:disabled { background: #e2e8f0; color: #8c99ab; border-color: #e2e8f0; }
QPushButton[role="destructive"]:hover { color: #b42318; background: #fff1f0; border-color: #f4b7b2; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: white; border: 1px solid #dedede; border-radius: 7px; min-height: 30px; padding: 0 8px; selection-background-color: #2563eb; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #2563eb; }
QLineEdit:disabled, QComboBox:disabled { background: #f5f5f5; color: #989898; }
QComboBox::drop-down { border: none; width: 22px; }
QTextEdit, QPlainTextEdit, QListWidget, QTreeWidget, QTableWidget, QScrollArea { background: white; border: 1px solid #e5e5e5; border-radius: 9px; }
QAbstractScrollArea > QWidget#qt_scrollarea_viewport { background: white; }
QGraphicsView { border: 1px solid #e5e5e5; border-radius: 9px; }
QListWidget { padding: 4px; outline: none; }
QListWidget::item { min-height: 34px; margin: 2px 0; padding: 6px 9px; border: 1px solid transparent; border-radius: 7px; }
QListWidget::item:hover { background: #f5f5f5; }
QListWidget::item:selected { background: #eaf2ff; color: #214d91; border-color: #d5e4fc; }
QTreeWidget::item:selected, QTableWidget::item:selected { background: #eaf2ff; color: #214d91; }
QTabWidget::pane { background: white; border: 1px solid #e5e5e5; border-radius: 10px; top: -1px; }
QTabBar::tab { background: transparent; border: 1px solid transparent; border-radius: 8px; padding: 8px 12px; margin: 3px 3px 5px 0; }
QTabBar::tab:hover { background: #eeeeee; }
QTabBar::tab:selected { background: #eaf2ff; color: #214d91; }
QHeaderView::section { background: #fafafa; padding: 6px; border: none; border-bottom: 1px solid #e5e5e5; }
QSplitter::handle { background: #f6f6f6; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #cecece; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
"""

_BUTTON_ICONS = {
    "刷新": "refresh", "刷新最近学习": "refresh", "保存任务步骤": "save",
    "放弃修改": "undo", "运行工作流": "play", "添加": "plus", "删除": "trash",
    "上移": "arrow-up", "下移": "arrow-down", "添加条件": "plus", "移除选中条件": "trash",
    "添加输出": "plus", "移除输出": "trash", "添加输入": "plus", "移除输入": "trash",
    "打开学习草稿": "edit", "准备单步试运行": "play", "回读试运行": "refresh",
    "准备下一步": "play", "保存": "save", "搜索": "search",
    "保存修改": "save", "审核界面": "check", "加入流程项目": "link",
    "交给Agent修正": "edit", "交给 Agent 修正": "edit", "新增框": "plus",
    "删除选中框": "trash", "修改此步骤的定位规则": "edit",
    "接收新内容 / 刷新": "refresh", "打开并继续修改": "edit",
    "删除界面": "trash", "批量删除": "trash", "查看所属学习流程": "graph",
    "适应窗口": "zoom", "原始像素 100%": "zoom",
    "保存项目": "save", "保存项目修改": "save", "新建项目": "plus",
    "新建流程项目": "plus", "加入已有界面": "link", "添加已有界面": "link",
    "＋ 添加已有界面": "link", "刷新项目": "refresh", "查看全图": "zoom",
    "新增跳转关系": "link", "移除选中界面": "trash", "删除这条关系": "trash",
    "放弃项目修改": "undo", "加入选中项目": "link", "新建并加入": "plus",
    "从选中流程移除": "trash",
}


def apply_workbench_theme(window: QWidget) -> None:
    """统一已构造工作台；不修改 QApplication 或共享审核主题。"""
    # 只移除拥有共享整树主题的根节点，保留标题等局部样式。
    for widget in [window, *window.findChildren(QWidget)]:
        if widget.property("reviewTheme") is not None:
            widget.setStyleSheet("")
            widget.setProperty("reviewTheme", None)
    window.setProperty("workbenchTheme", "codex-light")
    window.setStyleSheet(_STYLE)
    for button in window.findChildren(QPushButton):
        text = bound_text(button)
        source = getattr(text, "source", text)
        name = _BUTTON_ICONS.get(source)
        if name is None:
            continue
        if source in {"保存任务步骤", "保存", "保存修改", "保存项目", "保存项目修改"}:
            button.setProperty("primary", True)
        if name == "trash":
            button.setProperty("role", "destructive")
        primary = button.property("primary") is True or button.property("role") == "primary"
        button.setIcon(workbench_icon(name, "#ffffff" if primary else "#525252"))
        button.setIconSize(QSize(16, 16))
        button.style().unpolish(button)
        button.style().polish(button)
