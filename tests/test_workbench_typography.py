"""工作台中英文混排使用明确字体，不依赖测试夹具遮掩默认字体。"""
from PySide6.QtGui import QFont, QTextLayout
from PySide6.QtWidgets import QLabel, QPushButton, QWidget

from tests.test_workflow_steps_ui import qt_app


def test_workbench_font_reaches_controls_and_renders_mixed_text(qt_app):
    from app.learning_memory.workbench_typography import configure_workbench_font
    from app.learning_memory.workbench_theme import apply_workbench_theme
    original = QFont(qt_app.font())
    window = None
    try:
        qt_app.setFont(QFont('Times New Roman', 8))
        selected = configure_workbench_font(qt_app)
        window = QWidget()
        label = QLabel('学习工作台 Workflow 123', window)
        button = QPushButton('保存修改', window)
        apply_workbench_theme(window)
        window.ensurePolished()
        label.ensurePolished()
        button.ensurePolished()
        assert selected.pixelSize() == 14
        assert label.font().pixelSize() == 14
        assert button.font().pixelSize() == 14
        assert 'Microsoft YaHei UI' in label.font().families()
        layout = QTextLayout(label.text(), label.font())
        layout.beginLayout()
        layout.createLine()
        layout.endLayout()
        runs = layout.glyphRuns()
        assert runs
        assert all(index != 0 for run in runs for index in run.glyphIndexes())
    finally:
        if window is not None:
            window.close()
            window.deleteLater()
        qt_app.setFont(original)
