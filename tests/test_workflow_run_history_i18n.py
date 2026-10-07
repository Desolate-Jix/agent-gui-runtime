"""运行历史表头切换语言时保留原步骤和原回执。"""
from copy import deepcopy
import gc
import pytest
from PySide6.QtWidgets import QApplication
from app.learning_memory.workbench_i18n import initialize_i18n
from tests.test_workflow_run_panel import panel, connect, wait, PROGRAM
from tests.test_workflow_run_history import snapshot


@pytest.mark.parametrize('initial', ['zh-CN', 'en-US'])
def test_history_headers_survive_language_connect_refresh_and_reset(tmp_path, initial):
    app = QApplication.instance() or QApplication([])
    manager = initialize_i18n(app, preferences_path=tmp_path / 'preferences.json', system_locale=initial)
    manager.set_language(initial, persist=False)
    app, widget, clients = panel(tmp_path)
    widget.set_context({**PROGRAM, 'definition': {'steps': [
        {'step_id': 'read', 'title': '原用户标题 Read failed: 步骤'}]}}, 'read')
    table = widget.history_table
    expected = {'zh-CN': ['步骤', '结果', '核验方式', '已观测时长', '已记录模型调用'],
                'en-US': ['Steps', 'Result', 'Verification method', 'Observed duration', 'Recorded model calls']}
    def headers():
        return [table.horizontalHeaderItem(i).text() for i in range(5)]
    try:
        gc.collect()
        assert headers() == expected[initial]
        manager.set_language('en-US', persist=False)
        assert headers() == expected['en-US']
        client = connect(app, widget, clients)
        original = snapshot()
        original['history'][0]['raw_log'] = 'Read failed: 步骤'
        client.report = deepcopy(original)
        for language in ['zh-CN', 'en-US', 'zh-CN', 'en-US']:
            widget.refresh()
            wait(app, lambda: not widget.is_busy)
            gc.collect()
            manager.set_language(language, persist=False)
            assert headers() == expected[language]
            assert table.item(0, 0).text() == '原用户标题 Read failed: 步骤'
            assert widget._run == original
            assert client.report == original
            assert not client.calls
        client.report = {'run_id': 'new-run', 'status': 'ready', 'history': [], 'outputs': {}}
        widget.refresh()
        wait(app, lambda: not widget.is_busy)
        assert table.rowCount() == 0
        assert headers() == expected['en-US']
    finally:
        widget.close_client()
        widget.close()
        manager.set_language('zh-CN', persist=False)
