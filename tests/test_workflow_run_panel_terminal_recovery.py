from copy import deepcopy
import pytest

from test_workflow_run_panel import panel, connect, wait, FakeClient


def dead_scene(tmp_path, monkeypatch):
    monkeypatch.setattr(FakeClient, 'connect', lambda self: {
        'session_directory': str(self.session), 'host_alive': False,
        'pending_ids': ['eid-original'], 'recoverable_controls': [],
        'workflow_run': deepcopy(self.report or {
            'run_id': 'run-original', 'current_step_id': 'step-original',
            'runner_state': 'waiting', 'active_command_id': 'eid-original',
            'wait_reason': 'result_unknown'})})
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    client.previews = []
    client.settlements = []
    preview = {'contract_version': 'workflow_terminal_recovery_preview.v1',
        'run_id': 'run-original', 'step_id': 'step-original',
        'execution_request_id': 'eid-original', 'terminal_status': 'completed',
        'action_executed': True, 'task_effect_verified': None,
        'original3': {'receipt_sha256': 'a' * 64, 'command_sha256': 'b' * 64,
                      'terminal_sha256': 'c' * 64}, 'host_epoch': 'original-epoch'}
    def read(run_id):
        client.previews.append(run_id)
        return deepcopy(preview)
    def settle(value, *, request_id):
        client.settlements.append((deepcopy(value), request_id))
        client.report = {'run_id': 'run-original', 'current_step_id': 'step-original',
            'runner_state': 'recovery_paused', 'recovery_settlement': deepcopy(value)}
        return client.connect()
    client.preview_recovery = read
    client.settle_recovery = settle
    return app, widget, client, preview


@pytest.mark.parametrize('action', [True, False, None])
def test_explicit_preview_then_settlement_never_controls(tmp_path, monkeypatch, action):
    app, widget, client, preview = dead_scene(tmp_path, monkeypatch)
    preview['action_executed'] = action
    try:
        assert widget.recovery_button.isEnabled()
        assert not client.previews
        widget.recovery_button.click()
        wait(app, lambda: not widget.is_busy)
        assert client.previews == ['run-original'] and not client.settlements
        assert widget.recovery_button.text() == '结算已保存结果'
        assert 'step-original' in widget.recovery_label.text()
        assert '业务结果仍未核验' in widget.recovery_label.text()
        assert {True: '已发生', False: '未发生', None: '未知'}[action] in widget.recovery_label.text()
        widget.recovery_button.click()
        wait(app, lambda: not widget.is_busy)
        assert len(client.settlements) == 1 and client.settlements[0][0] == preview
        assert not client.calls
        widget.refresh()
        wait(app, lambda: not widget.is_busy)
        assert '已结算' in widget.recovery_label.text()
        assert not widget.recovery_button.isEnabled()
        for button in (widget.single_button, widget.run_button, widget.continue_button, widget.cancel_button):
            assert not button.isEnabled()
    finally:
        widget.close_client()


def test_settlement_failure_reuses_preview_and_request_id(tmp_path, monkeypatch):
    app, widget, client, preview = dead_scene(tmp_path, monkeypatch)
    try:
        widget.recovery_button.click()
        wait(app, lambda: not widget.is_busy)
        def fail(value, *, request_id):
            client.settlements.append((deepcopy(value), request_id))
            raise ValueError('saved outcome unavailable')
        client.settle_recovery = fail
        for _ in range(2):
            widget.recovery_button.click()
            wait(app, lambda: not widget.is_busy)
        assert len(client.settlements) == 2
        assert client.settlements[0] == client.settlements[1]
        assert client.settlements[0][0] == preview
        assert not client.calls
    finally:
        widget.close_client()


def test_preview_failure_does_not_offer_settlement(tmp_path, monkeypatch):
    app, widget, client, _ = dead_scene(tmp_path, monkeypatch)
    try:
        def fail(run_id):
            raise ValueError('original terminal unknown')
        client.preview_recovery = fail
        widget.recovery_button.click()
        wait(app, lambda: not widget.is_busy)
        assert widget.recovery_button.text() == '核对已保存结果'
        assert not client.settlements and not client.calls
    finally:
        widget.close_client()


@pytest.mark.parametrize('key,value', [('run_id', 'other'), ('step_id', 'other'),
    ('execution_request_id', 'other'), ('terminal_status', 'result_unknown'),
    ('action_executed', 0), ('task_effect_verified', True)])
def test_bad_preview_never_becomes_settlement(tmp_path, monkeypatch, key, value):
    app, widget, client, preview = dead_scene(tmp_path, monkeypatch)
    preview[key] = value
    try:
        widget.recovery_button.click()
        wait(app, lambda: not widget.is_busy)
        assert widget.recovery_button.text() == '核对已保存结果'
        assert widget._terminal_preview is None
        assert not client.settlements and not client.calls
    finally:
        widget.close_client()


def test_reopened_settlement_blocks_even_reported_live_host(tmp_path, monkeypatch):
    app, widget, client, preview = dead_scene(tmp_path, monkeypatch)
    try:
        client.report = {'run_id': 'run-original', 'runner_state': 'recovery_paused',
            'recovery_settlement': {**preview, 'status': 'recovery_paused'}}
        widget._accept_status({**client.connect(), 'host_alive': True})
        widget._sync()
        assert '已结算' in widget.recovery_label.text()
        widget.start_single()
        widget.continue_run()
        widget.cancel_run()
        widget._control({'action': 'run'}, 'run')
        assert not client.calls
        for button in (widget.single_button, widget.run_button, widget.continue_button,
                       widget.cancel_button, widget.recovery_button):
            assert not button.isEnabled()
    finally:
        widget.close_client()
