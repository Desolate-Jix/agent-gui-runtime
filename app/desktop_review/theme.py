"""原生审核界面的共享浅色主题。"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget


WHITE = "#ffffff"
BACKGROUND = "#f4f7fb"
ACCENT = "#2563eb"
TEXT = "#172b4d"
MUTED_TEXT = "#52627a"
BORDER = "#dbe3ef"


REVIEW_THEME_QSS = f"""
QWidget {{
    background-color: {BACKGROUND};
    color: {TEXT};
    font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
    font-size: 14px;
}}
QWidget#graphReviewPane {{
    background-color: {BACKGROUND};
}}
QLabel {{
    background: transparent;
}}
QLabel[role="muted"] {{
    color: {MUTED_TEXT};
}}
QLabel[role="sectionTitle"] {{
    color: {TEXT};
    font-weight: 600;
}}
QWidget#reviewHeader {{
    background-color: {WHITE};
    border: none;
    border-bottom: 1px solid {BORDER};
    min-height: 28px;
    padding: 12px 18px;
}}
QLabel#reviewHeaderTitle {{
    color: {TEXT};
    font-size: 20px;
    font-weight: 600;
    margin-right: 18px;
}}
QLabel#reviewBrand {{
    color: {TEXT};
    font-size: 17px;
    font-weight: 600;
    padding-bottom: 8px;
}}
QWidget#navSpacer {{
    background: transparent;
}}
QWidget#headerSpacer {{
    background: transparent;
}}
QToolBar#reviewHeader QToolButton {{
    background: {WHITE};
    color: {MUTED_TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    margin-left: 7px;
    padding: 7px 12px;
}}
QToolBar#reviewHeader QToolButton:hover {{
    background: #eaf1ff;
    color: {ACCENT};
}}
QLabel#graphRevisionIdentity,
QLabel#graphSelectionTitle {{
    color: {TEXT};
    font-size: 17px;
    font-weight: 600;
}}
QGroupBox {{
    background-color: {WHITE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    font-weight: 600;
    margin-top: 13px;
    padding-top: 8px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 5px;
    color: {TEXT};
}}
QGroupBox#graphCard,
QGroupBox#beforeCanvasCard,
QGroupBox#afterCanvasCard {{
    margin-top: 0;
    padding-top: 0;
}}
QScrollArea,
QScrollArea > QWidget > QWidget,
QStackedWidget {{
    background: transparent;
    border: none;
}}
QScrollArea#graphInspectorScroll,
QScrollArea#graphInspectorScroll > QWidget > QWidget,
QWidget#graphInspectorWrapper,
QWidget#graphInspector,
QWidget#graphInspectorFooter,
QWidget#nodeEditor,
QWidget#nodeEditorButtons,
QWidget#edgeEditor,
QWidget#edgeEditorButtons {{
    background-color: {WHITE};
}}
QScrollArea#graphInspectorScroll {{
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QLineEdit,
QPlainTextEdit,
QComboBox {{
    background-color: {WHITE};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: {ACCENT};
    selection-color: {WHITE};
}}
QLineEdit:focus,
QPlainTextEdit:focus,
QComboBox:focus {{
    border: 1px solid {ACCENT};
}}
QLineEdit:disabled,
QPlainTextEdit:disabled,
QComboBox:disabled {{
    background-color: #eef2f7;
    color: #6f7f95;
    border-color: {BORDER};
}}
QPushButton {{
    min-height: 28px;
    background-color: {WHITE};
    color: {TEXT};
    border: 1px solid #b8c5d8;
    border-radius: 6px;
    padding: 3px 11px;
}}
QPushButton:hover {{
    border-color: {ACCENT};
    color: {ACCENT};
}}
QPushButton:pressed {{
    background-color: #e8f0ff;
}}
QPushButton:focus,
QToolButton:focus {{
    border: 2px solid {ACCENT};
}}
QPushButton[role="primary"] {{
    background-color: {ACCENT};
    color: {WHITE};
    border-color: {ACCENT};
    font-weight: 600;
}}
QPushButton[role="primary"]:hover {{
    background-color: #1d4ed8;
    color: {WHITE};
}}
QPushButton:disabled,
QPushButton[role="primary"]:disabled {{
    background-color: #e7ecf3;
    color: #718096;
    border-color: #cbd5e1;
}}
QSplitter::handle {{
    background-color: {BACKGROUND};
}}
QSplitter::handle:horizontal {{
    width: 7px;
}}
QSplitter::handle:vertical {{
    height: 7px;
}}
QGraphicsView {{
    background-color: {WHITE};
    border: 1px solid {BORDER};
    border-radius: 6px;
}}
QToolBar#reviewNavigation {{
    background-color: {WHITE};
    border: none;
    border-right: 1px solid {BORDER};
    spacing: 5px;
    padding: 10px 7px;
}}
QToolBar#reviewNavigation QToolButton {{
    color: {MUTED_TEXT};
    background: transparent;
    border: none;
    border-radius: 7px;
    padding: 8px 10px;
    text-align: left;
}}
QToolBar#reviewNavigation QToolButton:hover {{
    background-color: #edf3ff;
    color: {ACCENT};
}}
QToolBar#reviewNavigation QToolButton:checked {{
    background-color: #e6efff;
    color: {ACCENT};
    font-weight: 600;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #bdc9d9;
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
}}
QLabel#reviewNextStep {{
    background-color: #eaf1ff;
    color: #23447d;
    border-radius: 7px;
    padding: 7px 12px;
}}
QLabel#helpTitle {{
    font-size: 21px;
    font-weight: 600;
    padding: 10px 8px;
}}
QToolButton#detailsToggle {{
    background: transparent;
    color: {MUTED_TEXT};
    border: none;
    padding: 8px 2px;
    font-size: 13px;
    text-align: left;
}}
QToolButton#detailsToggle:hover {{
    color: {ACCENT};
}}
QToolButton#detailsToggle:focus {{
    border: 1px solid {ACCENT};
}}
QTableWidget, QTreeWidget {{
    background-color: {WHITE};
    alternate-background-color: #f8faff;
    border: 1px solid {BORDER};
    border-radius: 8px;
    selection-background-color: #eaf1ff;
    selection-color: {TEXT};
}}
QTreeWidget::item {{
    padding: 7px 4px;
}}
QHeaderView::section {{
    background-color: #f0f4fa;
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 9px 7px;
    color: {MUTED_TEXT};
}}
"""


def apply_review_theme(widget: QWidget) -> None:
    """将共享主题应用到窗口或独立审核控件。"""

    widget.setProperty("reviewTheme", "light-blue")
    widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    widget.setStyleSheet(REVIEW_THEME_QSS)
