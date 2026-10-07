"""重开后只恢复原控制事实；开始执行仍需明确选择。"""
from tests.test_workflow_run_panel import panel, connect, wait, receipt, PROGRAM
import pytest


def _saved_start(widget, client, *, completed=False):
    request = {'action': 'start', 'workflow_id': 'workflow-1', 'program_id': 'program-1',
               'start_step_id': 'step-1', 'inputs': {'query': '已固定的输入'}}
    value = {'run_id': 'run-recovered', 'status': 'ready', 'workflow_id': 'workflow-1',
             'program_id': 'program-1', 'start_step_id': 'step-1', 'inputs': request['inputs']}
    client.recoverable_controls = [{'request_id': 'original-start', 'action': 'start',
        'request': request, 'receipt': receipt('original-start', value) if completed else
        {'request_id': 'original-start', 'status': 'pending'}}]
    return value


def test_reopened_pending_start_is_read_without_automatic_run(tmp_path):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    value = _saved_start(widget, client)
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    assert widget._pending is not None and widget._pending['request_id'] == 'original-start'
    client.results['original-start'] = receipt('original-start', value)
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    assert widget._run['run_id'] == 'run-recovered'
    assert not client.calls
    assert widget.single_button.isEnabled()
    widget.start_single()
    wait(app, lambda: not widget.is_busy)
    assert len(client.calls) == 1
    assert client.calls[0][0] == {'action': 'run', 'run_id': 'run-recovered', 'mode': 'single'}
    widget.close_client()


@pytest.mark.parametrize("finished", [False, True])
def test_actual_client_panel_reopens_dead_host_readonly(tmp_path, monkeypatch, finished):
    import psutil
    from PySide6.QtWidgets import QApplication
    from app.learning_memory.workflow_run_panel import WorkflowRunPanel
    from app.learning_memory.workflow_run_client import WorkflowRunClient
    from tests.test_workflow_run_client import _live, _write
    session, library, pointer, report = _live(tmp_path)
    client = WorkflowRunClient(session, library)
    client.connect()
    request = {"action": "status", "run_id": "trial-" + "c" * 64}
    client.control(request, "original-control")
    report["workflow_run"] = {"run_id": request["run_id"], "runner_state": "waiting", "status": "blocked",
        "wait_reason": "verification_required", "wait": {"wait_id": "original-wait"}, "outputs": {"result": "original"}}
    if finished:
        report.update(phase="stopped", finished_at="fixture")
    _write(session / "report.json", report)
    actual = psutil.Process

    def dead(pid=None):
        if pid == pointer["host_identity"]["pid"]:
            raise psutil.NoSuchProcess(pid)
        return actual(pid)

    monkeypatch.setattr(psutil, "Process", dead)
    app = QApplication.instance() or QApplication([])
    widget = WorkflowRunPanel(library, session)
    widget.set_context(PROGRAM, "step-1")
    widget.connect_session()
    wait(app, lambda: not widget.is_busy)
    assert widget._client._connected and not widget._host_alive
    assert widget._run["run_id"] == request["run_id"]
    assert widget._pending["request_id"] == "original-control"
    assert widget._client.result("original-control")["status"] == "result_unknown"
    assert not any(button.isEnabled() for button in (widget.single_button, widget.run_button,
                                                    widget.continue_button, widget.cancel_button))
    assert "original" in widget.outputs.toPlainText()
    widget.start_single()
    widget.continue_run()
    widget.cancel_run()
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    assert [p.stem for p in (session / "commands").glob("*.json")] == ["original-control"]
    assert "宿主未运行" in widget.status_label.text()
    assert "已保存状态" in widget.status_label.text()
    assert "输入可能已发生" in widget.status_label.text()
    assert "不能重发" in widget.status_label.text()
    assert widget._run["wait"]["wait_id"] == "original-wait"
    assert not (tmp_path / "owner.lock").exists()
    widget.close_client()


def test_multiple_recovery_controls_do_not_guess_or_start_another_trial(tmp_path):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    _saved_start(widget, client, completed=True)
    other = {**client.recoverable_controls[0], 'request_id': 'other-start'}
    client.recoverable_controls.append(other)
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    assert not widget.run_button.isEnabled()
    assert not widget.single_button.isEnabled()
    assert not client.calls
    assert '多个' in widget.status_label.text()
    widget.close_client()


def test_current_results_are_readable_and_unknown_total_usage_stays_unknown(tmp_path):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    client.report = {'run_id': 'run-1', 'runner_state': 'completed', 'status': 'completed',
        'outputs': {'read.status': {'run_id': 'run-1', 'value': '已更新'}},
        'metrics': {'total_model_calls': None, 'total_usage': None, 'coverage': {},
                    'observed': {'event_count': 2}}}
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    assert widget.outputs.toPlainText() == 'read.status：已更新'
    assert '模型调用总量未知' in widget.metrics_label.text()
    assert 'token 总量未知' in widget.metrics_label.text()
    assert 'completed' not in widget.status_label.text()
    assert '已完成' in widget.status_label.text()
    widget.close_client()


def test_recovered_run_requires_its_pinned_start_step(tmp_path):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    _saved_start(widget, client, completed=True)
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    widget.set_context(PROGRAM, 'other-step')
    assert not widget.single_button.isEnabled()
    widget.start_single()
    assert not client.calls
    widget.set_context(PROGRAM, 'step-1')
    assert widget.single_button.isEnabled()
    widget.close_client()


def test_edited_session_path_cannot_dispatch_to_old_connection(tmp_path):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    widget.inputs_provider = lambda: {}
    assert widget.run_button.isEnabled()
    widget.session_path.setText(str(tmp_path / 'another-session'))
    assert not widget.run_button.isEnabled()
    widget.start_continuous()
    assert not client.calls
    widget.session_path.setText(str(tmp_path))
    assert widget.run_button.isEnabled()
    client.report = {'run_id': 'run-old', 'status': 'blocked', 'runner_state': 'waiting',
                     'wait_reason': 'single_step_complete', 'wait': {'wait_id': 'original-wait'}}
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    assert widget.continue_button.isEnabled() and widget.cancel_button.isEnabled()
    widget.session_path.setText(str(tmp_path / 'another-session'))
    assert not widget.continue_button.isEnabled() and not widget.cancel_button.isEnabled()
    widget.continue_run()
    widget.cancel_run()
    assert not client.calls
    widget.close_client()


def test_switching_to_empty_session_clears_previous_run_display(tmp_path):
    app, widget, clients = panel(tmp_path)
    first = connect(app, widget, clients)
    first.report = {'run_id': 'run-old', 'status': 'blocked', 'runner_state': 'waiting',
                    'current_step_id': 'old-step', 'wait_reason': 'single_step_complete',
                    'outputs': {'read.value': '上一会话的值'}, 'metrics': {'steps_completed': 1}}
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    assert '上一会话的值' in widget.outputs.toPlainText()
    other = tmp_path / 'another-session'
    other.mkdir()
    widget.session_path.setText(str(other))
    widget.connect_button.click()
    wait(app, lambda: len(clients) == 2 and not widget.is_busy)
    assert first.closed and widget._run is None
    assert widget.outputs.toPlainText() == ''
    assert widget.outputs.toolTip() == ''
    assert widget.step_label.text() == '当前步骤：尚未运行'
    assert widget.step_label.toolTip() == ''
    assert widget.wait_label.text() == '等待原因：无'
    assert widget.metrics_label.text() == '统计：暂无'
    assert widget.metrics_label.toolTip() == ''
    assert widget.status_label.toolTip() == ''
    assert not clients[1].calls
    widget.close_client()


def test_new_run_with_no_outputs_does_not_retain_old_tooltip(tmp_path):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    client.report = {'run_id': 'run-one', 'status': 'completed',
                     'outputs': {'read.value': '旧运行的值'}, 'metrics': {'steps_completed': 1}}
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    assert '旧运行的值' in widget.outputs.toolTip()
    client.report = {'run_id': 'run-two', 'status': 'ready', 'outputs': {}}
    widget.refresh()
    wait(app, lambda: not widget.is_busy)
    assert widget.outputs.toPlainText() == '当前没有输出。'
    assert widget.outputs.toolTip() == ''
    assert widget.metrics_label.toolTip() == ''
    widget.close_client()
