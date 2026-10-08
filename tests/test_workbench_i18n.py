import importlib.util
import os
import json
from copy import deepcopy
import pytest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QLineEdit


@pytest.fixture(autouse=True)
def restore_language():
    yield
    from app.learning_memory.workbench_i18n import language_manager
    manager = language_manager()
    if manager is not None:
        manager.set_language('zh-CN', persist=False)


def test_first_start_defaults_to_english_on_chinese_system(tmp_path, monkeypatch):
    from PySide6.QtCore import QLocale
    from app.learning_memory.workbench_i18n import initialize_i18n, ui
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(QLocale, 'system', lambda: QLocale('zh_CN'))
    assert QLocale.system().name() == 'zh_CN'
    preferences = tmp_path / 'workbench-preferences.json'
    manager = initialize_i18n(app, preferences)
    assert manager.language == 'en-US'
    assert ui(QLabel, '任务步骤').text() == 'Task steps'
    assert not preferences.exists()


@pytest.mark.parametrize('language', ['zh-CN', 'zh_CN'])
def test_explicit_chinese_language_remains_supported(tmp_path, language):
    from app.learning_memory.workbench_i18n import initialize_i18n, ui
    app = QApplication.instance() or QApplication([])
    manager = initialize_i18n(app, tmp_path / 'workbench-preferences.json', language)
    assert manager.language == 'zh-CN'
    assert ui(QLabel, '任务步骤').text() == '任务步骤'


@pytest.mark.parametrize('initial_language', [None, 'en_US'])
def test_saved_chinese_survives_fresh_initialization(tmp_path, initial_language):
    from app.learning_memory.workbench_i18n import initialize_i18n, ui
    app = QApplication.instance() or QApplication([])
    preferences = tmp_path / 'workbench-preferences.json'
    first = initialize_i18n(app, preferences, 'en_US')
    first.set_language('zh-CN')
    initialize_i18n(app, tmp_path / 'separate-preferences.json', 'en_US')
    reopened = initialize_i18n(app, preferences, initial_language)
    assert reopened is not first
    assert reopened.language == 'zh-CN'
    assert ui(QLabel, '任务步骤').text() == '任务步骤'
    assert json.loads(preferences.read_text(encoding='utf-8')) == {'language': 'zh-CN'}


def test_language_switch_preserves_input_and_semantics(tmp_path):
    assert importlib.util.find_spec("app.learning_memory.workbench_i18n"), "language switching is missing"
    from app.learning_memory.workbench_i18n import initialize_i18n, ui
    app = QApplication.instance() or QApplication([])
    manager = initialize_i18n(app, tmp_path / "workbench-preferences.json", "zh_CN")
    label = ui(QLabel, "任务步骤")
    combo = QComboBox()
    ui(combo.addItem, "待审核", "pending")
    ui(combo.addItem, "已审核", "reviewed")
    combo.setCurrentIndex(1)
    edit = QLineEdit("用户的未保存修改")
    changes = []
    combo.currentIndexChanged.connect(changes.append)
    manager.set_language("en-US")
    assert label.text() == "Task steps"
    assert combo.currentText() == "Reviewed"
    assert combo.currentData() == "reviewed"
    assert combo.currentIndex() == 1 and changes == []
    assert edit.text() == "用户的未保存修改"
    manager.set_language("zh-CN")
    assert label.text() == "任务步骤"
    assert initialize_i18n(app, tmp_path / "workbench-preferences.json", "en_US").language == "zh-CN"


def test_external_clear_and_user_title_invalidate_old_binding(tmp_path):
    from app.learning_memory.workbench_i18n import initialize_i18n, ui, tr, user_text
    app = QApplication.instance() or QApplication([])
    manager = initialize_i18n(app, tmp_path / "workbench-preferences.json", "zh_CN")
    error = ui(QLabel, tr("读取失败：") + "raw user log")
    heading = ui(QLabel, "选择步骤")
    identical_user_title = ui(QLabel, "选择步骤")
    user_text(identical_user_title.setText, "选择步骤")
    error.clear()
    heading.setText("用户标题：任务步骤")
    manager.set_language("en-US")
    assert error.text() == ""
    assert heading.text() == "用户标题：任务步骤"
    assert identical_user_title.text() == "选择步骤"


def test_preferences_remember_language_without_touching_legacy_settings(tmp_path):
    from app.learning_memory.workbench_i18n import initialize_i18n
    app = QApplication.instance() or QApplication([])
    legacy = tmp_path / "workbench-settings.json"
    legacy.write_text(json.dumps({"data_dir": "用户学习库"}, ensure_ascii=False), encoding="utf-8")
    original = legacy.read_bytes()
    preferences = tmp_path / "workbench-preferences.json"
    manager = initialize_i18n(app, preferences, "fr_FR")
    assert manager.language == "en-US"
    manager.set_language("zh-CN")
    assert json.loads(preferences.read_text(encoding="utf-8")) == {"language": "zh-CN"}
    assert legacy.read_bytes() == original
    assert initialize_i18n(app) is manager
    invalid = tmp_path / "invalid-preferences.json"
    invalid.write_text('{"language":"invalid"}', encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid workbench language preferences"):
        initialize_i18n(app, invalid, "zh_CN")


def test_active_application_dialog_retranslates_and_keeps_user_input(tmp_path):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QInputDialog, QDialogButtonBox
    from app.learning_memory.workbench_i18n import initialize_i18n, translated_dialog, tr
    app = QApplication.instance() or QApplication([])
    manager = initialize_i18n(app, tmp_path / "workbench-preferences.json", "zh_CN")
    parent = QLabel()
    seen = []
    def change():
        dialogs = [widget for widget in app.topLevelWidgets() if isinstance(widget, QInputDialog)]
        dialog = dialogs[0]
        try:
            dialog.setTextValue("用户标题：任务步骤")
            manager.set_language("en-US")
            seen.append((dialog.windowTitle(), dialog.labelText(), dialog.textValue()))
        finally:
            dialog.accept()
    QTimer.singleShot(0, change)
    value, accepted = translated_dialog(QInputDialog.getText, parent, tr("选择界面"), tr("任务名称"))
    assert seen == [("Select an interface", "Task name", "用户标题：任务步骤")]
    assert accepted and value == "用户标题：任务步骤"
    manager.set_language("zh-CN")
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
    assert buttons.button(QDialogButtonBox.StandardButton.Cancel).text() == "取消"
    manager.set_language("en-US")
    assert buttons.button(QDialogButtonBox.StandardButton.Cancel).text() == "Cancel"


def test_target_removed_variable_and_preview_status_follow_language(tmp_path):
    from tests.test_workflow_target_editor import _editor, STEP, DEFINITION
    from app.learning_memory.workbench_i18n import initialize_i18n
    app, facade, editor = _editor(tmp_path)
    manager = initialize_i18n(app, tmp_path / 'workbench-preferences.json', 'zh_CN')
    editor.set_step(STEP, DEFINITION)
    editor._install_context(deepcopy(facade.context))
    editor.mode.setCurrentIndex(1)
    editor.row_type.setCurrentIndex(editor.row_type.findData('ListItem'))
    editor.value_source.setCurrentIndex(1)
    editor.refresh_definition({**DEFINITION, 'inputs': [{'name': 'new', 'type': 'text'}]})
    manager.set_language('en-US')
    assert editor.binding.currentData() is None
    assert editor.binding.currentText() == 'The original variable is no longer declared; select it again'
    manager.set_language('zh-CN')
    editor._show_status('无法预览：', 'raw user error: 任务步骤')
    manager.set_language('en-US')
    assert editor.status.text().startswith('Cannot preview: ')
    assert 'raw user error: 任务步骤' in editor.status.text()
    editor._show_status('无法预览：', '任务步骤')
    assert editor.status.text() == 'Cannot preview: 任务步骤'
    editor.close()


def test_help_and_graph_feedback_switch_without_changing_user_feedback(tmp_path, monkeypatch):
    import re
    from PySide6.QtWidgets import QAbstractButton
    from app.desktop_review.friendly_controls import ReviewHelpDialog
    from app.desktop_review.graph_relearn_dialog import GraphRelearnDialog
    from app.learning_memory.workbench_i18n import initialize_i18n
    app = QApplication.instance() or QApplication([])
    manager = initialize_i18n(app, tmp_path / 'workbench-preferences.json', 'zh_CN')
    monkeypatch.setattr(GraphRelearnDialog, 'refresh_feedback', lambda self: None)
    snapshot = {'contract_version': 'formal_graph_revision_v1', 'logical_workflow_id': '用户图名',
                'revision': 1, 'content_sha256': 'a' * 64,
                'graph': {'nodes': [{'node_id': '用户节点'}], 'edges': []}}
    graph = GraphRelearnDialog(object(), snapshot, ('node', '用户节点'))
    graph.issue_message.setPlainText('用户反馈：任务步骤')
    help_dialog = ReviewHelpDialog()
    for language in ['en-US', 'zh-CN'] * 3:
        manager.set_language(language)
        assert graph.issue_message.toPlainText() == '用户反馈：任务步骤'
        assert graph.snapshot == snapshot
        assert '用户图名' in graph.identity_label.text() and '用户节点' in graph.identity_label.text()
        if language == 'en-US':
            assert 'revision' in graph.identity_label.text().lower()
            for dialog in (graph, help_dialog):
                assert not re.search('[\u4e00-\u9fff]', dialog.windowTitle())
                for button in dialog.findChildren(QAbstractButton):
                    assert not re.search('[\u4e00-\u9fff]', button.text()), button.text()
                for label in dialog.findChildren(QLabel):
                    if label is graph.identity_label:
                        continue
                    assert not re.search('[\u4e00-\u9fff]', label.text()), label.text()
    graph.close()
    help_dialog.close()


def test_joined_display_handles_many_values_and_preserves_user_values(tmp_path):
    from app.learning_memory.workbench_i18n import initialize_i18n, join_text, tr, ui
    app = QApplication.instance() or QApplication([])
    manager = initialize_i18n(app, tmp_path / 'workbench-preferences.json', 'zh_CN')
    label = ui(QLabel, join_text('\n', [tr('{title}的跳转', title='任务步骤') for _ in range(1500)]))
    manager.set_language('en-US')
    assert label.text().splitlines() == ['Branches from 任务步骤'] * 1500
    manager.set_language('zh-CN')
    assert label.text().splitlines() == ['任务步骤的跳转'] * 1500


def test_execution_installation_row_errors_and_pending_switch_without_dispatch(tmp_path):
    from tests.test_workflow_run_panel import panel, connect
    from app.learning_memory.workbench_i18n import initialize_i18n
    app, widget, clients = panel(tmp_path)
    manager = initialize_i18n(app, tmp_path / 'workbench-preferences.json', 'zh_CN')
    original = connect(app, widget, clients)
    widget._timer.stop()
    widget._pending = {'request_id': 'existing-original-id', 'action': 'continue'}
    pending = deepcopy(widget._pending)
    context = deepcopy(widget._context)
    selected = tmp_path / '用户执行安装'
    selected.mkdir()
    widget.execution_path.setText(str(selected))
    widget.connect_session()
    for language in ['en-US', 'zh-CN'] * 3:
        manager.set_language(language)
        assert widget._pending == pending and widget._context == context
        assert widget.execution_path.text() == str(selected)
        assert widget._client is original and not original.calls
        if language == 'en-US':
            assert widget.execution_browse_button.text() == 'Select execution installation'
            assert 'compatible execution mode' in widget.execution_path.placeholderText()
            assert widget.status_label.text().startswith('The original request is not settled.')
        else:
            assert widget.execution_browse_button.text() == '选择执行安装'
            assert widget.status_label.text().startswith('原请求尚未结算')
    widget._show_error('无法连接，请检查执行安装、会话与学习库：', '原始日志：任务步骤')
    manager.set_language('en-US')
    assert widget.status_label.text() == 'Cannot connect. Check the execution installation, session, and learning library: 原始日志：任务步骤'
    assert widget.status_label.toolTip() == '原始日志：任务步骤'
    assert widget._pending == pending and not original.calls
    widget.close_client()


def test_existing_localized_template_keeps_source_when_values_are_added(tmp_path):
    from app.learning_memory.workbench_i18n import initialize_i18n, ui, tr
    app = QApplication.instance() or QApplication([])
    manager = initialize_i18n(app, tmp_path / 'workbench-preferences.json', 'en_US')
    label = ui(QLabel, tr(tr('图修订响应无效：{v0}'), v0='用户日志'))
    manager.set_language('zh-CN')
    assert label.text() == '图修订响应无效：用户日志'


def test_template_local_image_error_translates_and_keeps_raw_external_error(tmp_path):
    from hashlib import sha256
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidgetItem
    from app.learning_memory.template_dialog import ControlTemplateDialog
    from app.learning_memory.workbench_i18n import initialize_i18n
    app = QApplication.instance() or QApplication([])
    manager = initialize_i18n(app, tmp_path / 'workbench-preferences.json', 'en_US')
    image = tmp_path / 'invalid.png'
    image.write_bytes(b'invalid-png')
    class Facade:
        def list_control_templates(self, *args):
            return {'templates': []}
        def load_control_template_evidence(self, identity):
            return {'image_path': str(image), 'png_sha256': sha256(image.read_bytes()).hexdigest()}
        def _artifact_file(self, *args):
            return image
        def save_control_template(self, *args):
            raise ValueError('任务步骤')
    dialog = ControlTemplateDialog(Facade(), {'interface_id': 'i', 'version_id': 'v', 'content': {'regions': []}})
    item = QListWidgetItem()
    item.setData(Qt.ItemDataRole.UserRole, 'template')
    dialog.preview(item)
    assert dialog.status.text() == 'Preview failed: Cannot display the template PNG'
    manager.set_language('zh-CN')
    assert dialog.status.text() == '预览失败：模板 PNG 无法显示'
    manager.set_language('en-US')
    dialog.save()
    assert dialog.status.text() == 'Save failed: 任务步骤'
    dialog.close()


def test_source_dialog_local_image_error_and_external_log_remain_distinct(tmp_path):
    from hashlib import sha256
    from tests.test_workflow_run_panel import wait
    from app.learning_memory.source_dialog import SourceAdoptionDialog
    from app.learning_memory.workbench_i18n import initialize_i18n
    app = QApplication.instance() or QApplication([])
    manager = initialize_i18n(app, tmp_path / 'workbench-preferences.json', 'en_US')
    image = tmp_path / 'invalid-source.png'
    image.write_bytes(b'invalid-png')
    class Facade:
        external_error = None
        def list_source_candidates(self, *args):
            if self.external_error:
                raise ValueError(self.external_error)
            return {'candidates': [], 'truncated': False, 'errors': []}
        def load_interface_content_evidence(self, *args):
            return {'image_path': str(image), 'sha256': sha256(image.read_bytes()).hexdigest()}
        def _artifact_file(self, *args):
            return image
    facade = Facade()
    dialog = SourceAdoptionDialog(facade, {'interface_id': 'i', 'version_id': 'v'})
    wait(app, lambda: not dialog.busy)
    assert dialog.status.text() == 'Operation failed: Cannot display PNG'
    manager.set_language('zh-CN')
    assert dialog.status.text() == '操作失败：PNG 无法显示'
    facade.external_error = '任务步骤'
    manager.set_language('en-US')
    dialog.refresh()
    wait(app, lambda: not dialog.busy)
    assert dialog.status.text().startswith('Operation failed: 任务步骤\nTraceback')
    original_detail = dialog.status.text().removeprefix('Operation failed: ')
    manager.set_language('zh-CN')
    assert dialog.status.text() == '操作失败：' + original_detail
    dialog.close()


def test_region_kind_hint_switches_without_translating_user_value(tmp_path):
    from app.desktop_review.interface_pane import InterfaceReviewPane
    from app.desktop_review.interface_content import SUPPORTED_REGION_KINDS
    from app.learning_memory.workbench_i18n import initialize_i18n
    app = QApplication.instance() or QApplication([])
    manager = initialize_i18n(app, tmp_path / "workbench-preferences.json", "zh_CN")
    pane = InterfaceReviewPane(object())
    kinds = ", ".join(SUPPORTED_REGION_KINDS)
    pane.region_kind_edit.setText("unknown")
    try:
        for locale, prefix in [("zh-CN", "支持类型："), ("en-US", "Supported types: "), ("zh-CN", "支持类型：")]:
            manager.set_language(locale)
            app.processEvents()
            assert (pane.region_kind_edit.placeholderText(), pane.region_kind_edit.toolTip()) == (prefix + kinds, prefix + kinds)
            assert pane.region_kind_edit.text() == "unknown"
        pane.region_kind_edit.setText("支持类型：")
        manager.set_language("en-US")
        assert pane.region_kind_edit.text() == "支持类型："
    finally:
        pane.close()
        pane.deleteLater()
        app.processEvents()
