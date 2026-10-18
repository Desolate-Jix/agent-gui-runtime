"""学习工作台进程的中英文混排字体。"""
from PySide6.QtGui import QFont, QFontDatabase


def configure_workbench_font(application):
    available = set(QFontDatabase.families())
    preferred = ['Segoe UI Variable Text', 'Segoe UI', 'Microsoft YaHei UI',
                 'Microsoft YaHei', 'Noto Sans CJK SC']
    font = QFont(application.font())
    families = [family for family in preferred if family in available]
    if families:
        font.setFamilies(families)
    # Qt 逻辑像素随屏幕缩放；仅设置本工作台进程，不修改 Windows 字体配置。
    font.setPixelSize(14)
    font.setWeight(QFont.Weight.Normal)
    application.setFont(font)
    return font
