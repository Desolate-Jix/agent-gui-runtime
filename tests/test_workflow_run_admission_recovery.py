"""未入队的执行请求保留原任务，恢复后只接受明确的继续操作。"""
from copy import deepcopy

import pytest

from tests.test_workflow_run_panel import connect, panel, receipt, wait


@pytest.mark.parametrize('mode', ['single', 'until_wait'])
@pytest.mark.parametrize('reason', ['command_pending', 'host_not_ready'])
def test_unsubmitted_run_can_explicitly_resume_prepared_trial(tmp_path, mode, reason):
    app, widget, clients = panel(tmp_path)
    client = connect(app, widget, clients)
    widget.inputs_provider = lambda: {'query': '原输入'}
    try:
        widget.run_button.click()
        wait(app, lambda: len(client.calls) == 1 and not widget.is_busy)
        start_id = client.calls[0][1]
        ready = {'run_id': 'original-trial', 'status': 'ready',
                 'workflow_id': 'workflow-1', 'program_id': 'program-1',
                 'start_step_id': 'step-1', 'inputs': {'query': '原输入'}}
        client.results[start_id] = receipt(start_id, ready)
        widget.refresh()
        wait(app, lambda: len(client.calls) == 2 and not widget.is_busy)
        run_id = client.calls[1][1]
        client.results[run_id] = {'request_id': run_id, 'status': 'not_submitted',
                                  'reason': reason, 'pending_ids': ['other-command']}
        widget.refresh()
        wait(app, lambda: not widget.is_busy)
        assert not widget.single_button.isEnabled()
        assert not widget.run_button.isEnabled()
        client.report = deepcopy(ready)
        client.pending_ids = []
        widget.refresh()
        wait(app, lambda: not widget.is_busy)
        assert len(client.calls) == 2, '队列恢复不能自动重发输入'
        assert widget.single_button.isEnabled()
        assert widget.run_button.isEnabled()
        widget.inputs_provider = lambda: pytest.fail('原任务不得再次索取输入')
        (widget.single_button if mode == 'single' else widget.run_button).click()
        wait(app, lambda: len(client.calls) == 3 and not widget.is_busy)
        assert client.calls[-1][0] == {'action': 'run', 'run_id': 'original-trial', 'mode': mode}
        assert sum(call[0]['action'] == 'start' for call in client.calls) == 1
        assert client.calls[-1][1] != run_id
    finally:
        widget.close_client()
