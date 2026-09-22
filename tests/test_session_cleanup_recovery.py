from types import SimpleNamespace
import json

from app.instant_mcp import InstantSession, write_json


def test_shutdown_pending_remains_observable_and_retries_only_cleanup(tmp_path):
    from app.desktop_review.session_cleanup import shutdown_retaining_owner
    calls, observations = [], []
    report = {'phase': 'ready'}
    token = {'value': None}
    error = RuntimeError('not used in diagnostics')
    error.code = 'model_service_cleanup_pending'
    error.diagnostics = {'contract_version': 'model_service_cleanup_diagnostics_v1', 'evidence': {'pid_file_after': 'owned.pid'}}
    def shutdown():
        calls.append('shutdown')
        if len(calls) == 1:
            raise error
    def save():
        observations.append(json.loads(json.dumps(report)))
    def wait(seconds):
        assert len(calls) == 1
        assert report['phase'] == 'cleanup_pending' and 'finished_at' not in report
        token['value'] = 'retry-1'
    shutdown_retaining_owner(SimpleNamespace(shutdown=shutdown), report, save,
                             lambda: token['value'], wait=wait)
    assert calls == ['shutdown', 'shutdown']
    assert observations[0]['cleanup_errors'][0]['diagnostics'] == error.diagnostics
    assert report['cleanup_errors'] == []
    assert len(report['cleanup_attempts']) == 1


def test_stop_pending_signals_retry_without_replaying_commands(tmp_path):
    session = InstantSession(tmp_path, tmp_path, tmp_path, allow_local_input=True)
    session.session = tmp_path / ('session-' + 'a' * 32)
    (session.session / 'commands').mkdir(parents=True)
    write_json(session.session / 'closing.json', {'request_id': 'close-original'})
    session.status = lambda: {'phase': 'cleanup_pending', 'host_alive': True, 'cleanup_verified': False}
    response = session.stop()
    first = json.loads((session.session / 'cleanup-retry.json').read_text(encoding='utf-8'))
    assert response['cleanup_retry_requested'] is True
    assert list((session.session / 'commands').iterdir()) == []
    session.stop()
    second = json.loads((session.session / 'cleanup-retry.json').read_text(encoding='utf-8'))
    assert first['request_id'] != second['request_id']


def test_signal_and_report_io_errors_do_not_abandon_original_owner():
    from app.desktop_review.session_cleanup import shutdown_retaining_owner
    calls = []
    state = {'readable': False}
    report = {}
    def token():
        if not state['readable']:
            raise PermissionError('private text')
        return 'explicit-retry'
    def shutdown():
        calls.append('shutdown')
        if len(calls) == 1:
            raise RuntimeError('pending')
    def save():
        raise PermissionError('private text')
    def wait(_):
        state['readable'] = True
    shutdown_retaining_owner(SimpleNamespace(shutdown=shutdown), report, save, token, wait=wait)
    assert calls == ['shutdown', 'shutdown']
    assert report['cleanup_errors'] == []
    assert 'private text' not in json.dumps(report)
