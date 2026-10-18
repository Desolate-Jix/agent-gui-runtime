import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtGui import QAccessible
from PySide6.QtWidgets import QApplication, QFormLayout, QHBoxLayout, QLineEdit, QWidget

from app.learning_memory.workbench_i18n import initialize_i18n, tr, ui


def test_translated_form_field_has_stable_accessible_label(tmp_path):
    app = QApplication.instance() or QApplication([])
    manager = initialize_i18n(app, tmp_path / 'language.json', 'en-US')
    window = QWidget()
    form = QFormLayout(window)
    field = QLineEdit('input_sequence')
    ui(form.addRow, tr('步骤名称'), field)
    accessible = QAccessible.queryAccessibleInterface(field)
    try:
        assert accessible.text(QAccessible.Text.Name) == 'Step name'
        assert form.labelForField(field).buddy() is field
        field.setText('Open reports folder')
        assert accessible.text(QAccessible.Text.Name) == 'Step name'
        manager.set_language('zh-CN', persist=False)
        app.processEvents()
        assert accessible.text(QAccessible.Text.Name) == '步骤名称'
        assert field.text() == 'Open reports folder'
        manager.set_language('en-US', persist=False)
        app.processEvents()
        assert accessible.text(QAccessible.Text.Name) == 'Step name'
    finally:
        window.close()
        window.deleteLater()
        app.processEvents()


def test_translated_form_preserves_layout_and_spanning_rows(tmp_path):
    app = QApplication.instance() or QApplication([])
    initialize_i18n(app, tmp_path / 'language.json', 'en-US')
    window = QWidget()
    form = QFormLayout(window)
    row = QHBoxLayout()
    row.addWidget(QLineEdit('unchanged'))
    ui(form.addRow, tr('步骤名称'), row)
    ui(form.addRow, tr('任务步骤'))
    assert form.labelForField(row).buddy() is None
    assert form.rowCount() == 2
    window.close()
    window.deleteLater()
    app.processEvents()
