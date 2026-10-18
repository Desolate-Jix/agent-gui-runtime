"""实际工作台连接隔离会话；不启动宿主或执行桌面输入。"""
import json
import os
from pathlib import Path
from uuid import uuid4

import psutil
import pytest

from app.core.json_snapshot import write_json_snapshot
from app.learning_memory.event_store import LearningEventStore
from tests.test_learning_memory_v1 import record_search
from tests.test_workflow_steps_ui import qt_app, _wait
from tests.test_workflow_user_journey import _run_main


def _session(root):
    session = root / ('session-' + uuid4().hex)
    (session / 'commands').mkdir(parents=True)
    (session / 'responses').mkdir()
    identity = {'pid': os.getpid(), 'created': psutil.Process().create_time()}
    write_json_snapshot(root / 'latest-session.json', {
        'name': session.name, 'host_identity': identity,
        'recognition_source': 'agent_current', 'delegate_profile': None, 'api_profile': None})
    report = {'phase': 'ready', 'runner_pid': identity['pid'], 'target': None,
              'learning_recording': {'status': 'disabled', 'recording_enabled': False}}
    write_json_snapshot(session / 'report.json', report)
    return session


@pytest.fixture
def attached_learning(tmp_path):
    session = _session(tmp_path)
    store = LearningEventStore(session)
    store.control('learning_start', {'scope': 'workflow', 'title': '查询测试记录',
                                    'project_id': 'run-ui'}, 'record-start')
    record_search(store, 'record-search')
    store.control('learning_stop', {}, 'record-stop')
    return tmp_path, session


def test_main_connects_existing_session_and_closes_only_editor(monkeypatch, qt_app, attached_learning):
    root, session = attached_learning
    report = (session / 'report.json').read_bytes()
    def inspect(window):
        pane = window.steps
        assert hasattr(pane, 'run_panel'), '普通主窗口尚未连接运行页面'
        panel = pane.run_panel
        pane.editor_tabs.setCurrentWidget(panel)
        assert not panel.run_button.isEnabled()
        pane.save_button.click()
        assert pane.snapshot['program_id']
        panel.connect_button.click()
        _wait(qt_app, lambda: not pane.is_busy and panel.run_button.isEnabled())
        assert pane.session_dir == session
        assert not list((session / 'commands').glob('*.json'))
        pane.step_title.setText('只修改下一版本')
        assert pane.dirty and not panel.run_button.isEnabled()
        pane.discard()
        assert panel.run_button.isEnabled()
    _run_main(monkeypatch, qt_app, root, inspect, session=session)
    assert (session / 'report.json').read_bytes() == report
    assert not list((session / 'commands').glob('*.json'))
    assert not (session / 'closing.json').exists()
    assert sorted(root.glob('session-*')) == [session]


def test_main_rejects_wrong_library_session_without_dispatch(monkeypatch, qt_app, attached_learning, tmp_path):
    root, session = attached_learning
    foreign = _session(tmp_path / 'foreign-data')
    def inspect(window):
        pane = window.steps
        assert hasattr(pane, 'run_panel'), '普通主窗口尚未连接运行页面'
        pane.save_button.click()
        panel = pane.run_panel
        panel.session_path.setText(str(foreign))
        panel.connect_button.click()
        _wait(qt_app, lambda: not pane.is_busy)
        assert not panel.run_button.isEnabled()
        assert pane.session_dir == session
        assert not list((foreign / 'commands').glob('*.json'))
    _run_main(monkeypatch, qt_app, root, inspect, session=session)


def test_main_connects_current_agent_session_without_manual_path(monkeypatch, qt_app, attached_learning):
    root, session = attached_learning
    def inspect(window):
        pane = window.steps
        pane.save_button.click()
        panel = pane.run_panel
        panel.connect_button.click()
        _wait(qt_app, lambda: not pane.is_busy)
        assert pane.session_dir == session
        assert panel.run_button.isEnabled()
        assert pane.learning_refresh_button.isEnabled()
        pane.learning_status.setText('草稿可审核')
        panel.refresh()
        _wait(qt_app, lambda: not pane.is_busy)
        assert pane.learning_status.text() == '草稿可审核'
        assert not list((session / 'commands').glob('*.json'))
    _run_main(monkeypatch, qt_app, root, inspect)


def _next_control(qt_app, session, action):
    def matching():
        found = []
        for path in (session / 'commands').glob('*.json'):
            command = json.loads(path.read_text(encoding='utf-8'))
            if command.get('kind') == 'learning_workflow' and command['request']['action'] == action:
                found.append((path, command))
        return found
    _wait(qt_app, lambda: bool(matching()))
    result = matching()
    assert len(result) == 1
    return result[0]


def test_main_reopen_recovers_original_start_without_creating_another_trial(monkeypatch, qt_app, attached_learning):
    root, session = attached_learning
    from app.learning_memory.workspace import MemoryWorkspace
    from app.learning_memory.workflow_control import workflow_control
    remembered = {}
    def start(window):
        pane = window.steps
        pane.save_button.click()
        panel = pane.run_panel
        pane.editor_tabs.setCurrentWidget(panel)
        panel.inputs_provider = lambda: {'place': '关闭前固定的查询词'}
        panel.connect_button.click()
        _wait(qt_app, lambda: not pane.is_busy and panel.single_button.isEnabled())
        panel.single_button.click()
        path, command = _next_control(qt_app, session, 'start')
        _wait(qt_app, lambda: not pane.is_busy)
        remembered.update(path=path, command=command)
    _run_main(monkeypatch, qt_app, root, start, session=session)
    assert not (session / 'closing.json').exists()
    with MemoryWorkspace(root / 'memory-library') as library:
        value = workflow_control(library, session, remembered['command']['request'], remembered['path'].stem)
    write_json_snapshot(session / 'responses' / remembered['path'].name,
                        {'status': 'returned', 'command': remembered['command'], 'result': value})
    commands = {p.name: p.read_bytes() for p in (session / 'commands').glob('*.json')}
    def restore(window):
        pane = window.steps
        panel = pane.run_panel
        pane.editor_tabs.setCurrentWidget(panel)
        panel.connect_button.click()
        _wait(qt_app, lambda: not pane.is_busy and panel._run is not None)
        assert panel._run['run_id'] == value['run_id']
        assert panel._run['inputs'] == {'place': '关闭前固定的查询词'}
        assert panel.single_button.isEnabled()
        assert {p.name: p.read_bytes() for p in (session / 'commands').glob('*.json')} == commands
        if os.environ.get('WORKFLOW_RUN_ENTRY_CAPTURE'):
            qt_app.processEvents()
            assert window.grab().save(os.environ['WORKFLOW_RUN_ENTRY_CAPTURE'])
        panel.single_button.click()
        path, command = _next_control(qt_app, session, 'run')
        _wait(qt_app, lambda: not pane.is_busy)
        assert command['request'] == {'action': 'run', 'run_id': value['run_id'], 'mode': 'single'}
        assert len(list((session / 'workflow-trials').glob('trial-*.json'))) == 1
        assert len(list((session / 'commands').glob('*.json'))) == 2
    _run_main(monkeypatch, qt_app, root, restore, session=session)


def test_main_run_uses_original_queue_and_recovers_pinned_result(monkeypatch, qt_app, attached_learning):
    root, session = attached_learning
    from app.learning_memory.workspace import MemoryWorkspace
    from app.learning_memory.workflow_control import workflow_control
    from app.learning_memory.workflow_runtime import WorkflowRuntime
    from types import SimpleNamespace
    runtime = WorkflowRuntime(session, SimpleNamespace(_memory_library_root=root / 'memory-library'))
    recorded = {}
    def respond(path, command, result):
        write_json_snapshot(session / 'responses' / path.name,
                            {'status': 'returned', 'command': command, 'result': result})
    def inspect(window):
        pane = window.steps
        assert hasattr(pane, 'run_panel'), '普通主窗口尚未连接运行页面'
        pane.save_button.click()
        panel = pane.run_panel
        pane.editor_tabs.setCurrentWidget(panel)
        panel.inputs_provider = lambda: {'place': '本轮新的查询词'}
        panel.connect_button.click()
        _wait(qt_app, lambda: not pane.is_busy and panel.single_button.isEnabled())
        panel.single_button.click()
        path, command = _next_control(qt_app, session, 'start')
        with MemoryWorkspace(root / 'memory-library') as library:
            started = workflow_control(library, session, command['request'], path.stem)
        assert started['program_id'] == pane.snapshot['program_id']
        assert started['inputs'] == {'place': '本轮新的查询词'}
        respond(path, command, started)
        path, command = _next_control(qt_app, session, 'run')
        snapshot = runtime.control(command['request'], path.stem)
        respond(path, command, snapshot)
        report = json.loads((session / 'report.json').read_text(encoding='utf-8'))
        report['workflow_run'] = snapshot
        write_json_snapshot(session / 'report.json', report)
        recorded.update(snapshot=snapshot, program_id=pane.snapshot['program_id'])
        _wait(qt_app, lambda: not pane.is_busy and panel._run is not None
              and panel._run.get('runner_state') == snapshot['runner_state'])
        # 本测试仅检查真实队列与调度状态，不消费任何输入命令。
        assert snapshot['runner_state'] in {'waiting', 'single_complete', 'completed'}
        assert command['request']['run_id'] == started['run_id']
    _run_main(monkeypatch, qt_app, root, inspect, session=session)
    commands = {p.name: p.read_bytes() for p in (session / 'commands').glob('*.json')}
    def reopened(window):
        pane = window.steps
        panel = pane.run_panel
        panel.connect_button.click()
        _wait(qt_app, lambda: not pane.is_busy and panel._run is not None)
        assert pane.snapshot['program_id'] == recorded['program_id']
        assert panel._run['run_id'] == recorded['snapshot']['run_id']
        assert {p.name: p.read_bytes() for p in (session / 'commands').glob('*.json')} == commands
    _run_main(monkeypatch, qt_app, root, reopened, session=session)
    assert not (session / 'closing.json').exists()
