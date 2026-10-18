"""能力前置拒绝必须有原零派发证明，历史字符串错误不能代替。"""
from copy import deepcopy
from types import SimpleNamespace
import json
import pytest
from app.vision.agent_command_jobs import AgentCommandError, AgentCommandJobs
from app.vision.recognition_source import RecognitionSourceConfig
from app.execution.session_input_terminal import inspect_session_input_terminal
from scripts.run_local_step_session import dispatch_agent_command, preserve_input_admission_rejection
from tests.test_session_input_terminal import save


def setup_rejection(tmp_path, *, source='agent_current', capabilities=None):
    root = tmp_path / 'session-fresh'
    root.mkdir()
    config = RecognitionSourceConfig(source=source,
        delegate_profile='fresh-delegate' if source == 'agent_delegate' else None)
    command = {'kind': 'step', 'operation': 'execute_recognition_plan',
               'request': {'goal': 'Select fresh row', 'click_kind': 'single'}}
    if capabilities is not None:
        command['vision_capabilities'] = capabilities
    def forbidden_capture():
        pytest.fail('route rejection must precede capture or input')
    jobs = AgentCommandJobs(None, SimpleNamespace(session_root=root), forbidden_capture, config)
    with pytest.raises(AgentCommandError) as caught:
        dispatch_agent_command(jobs, 'first', command, {'handle': 100, 'process_id': 200})
    error = caught.value
    assert hasattr(error, 'before_dispatch_result'), 'capability rejection needs typed producer evidence'
    assert type(error).__name__ == 'AgentCommandVisionAdmissionError'
    result = error.before_dispatch_result('first')
    assert not jobs._jobs and not jobs._snapshots and not (root / 'agent-commands').exists()
    response = {'command': command, 'status': 'failed', 'error_type': type(error).__name__,
                'error': str(error)}
    preserve_input_admission_rejection(response, error, 'first')
    assert response['result'] == result
    save(root, 'commands', 'first', command)
    save(root, 'responses', 'first', response)
    journal = {'contract_version': 'session_resources.v1', 'session_name': root.name,
               'recognition_source': source, 'host_identity': {'pid': 100, 'created': 1.0},
               'runner_identity': {'pid': 200, 'create_time_ns': 1000000000},
               'phase': 'ready', 'resources': {}}
    (root / 'session-resources.json').write_text(json.dumps(journal), encoding='utf-8')
    report = {'recognition_source': config.source, 'delegate_profile': config.delegate_profile,
              'api_profile': config.api_profile, 'phase': 'stopped'}
    (root / 'report.json').write_text(json.dumps(report), encoding='utf-8')
    return root, command, response


@pytest.mark.parametrize('source,caps,reason', [
    ('agent_current', None, 'capability_unknown'),
    ('agent_current', {'image_transport': 'supported', 'current_vision': 'unsupported'}, 'vision_unsupported'),
    ('agent_delegate', {'image_transport': 'supported'}, 'capability_unknown'),
])
def test_real_manager_rejection_settles_zero_input_with_original_source(tmp_path, source, caps, reason):
    root, _, response = setup_rejection(tmp_path, source=source, capabilities=caps)
    assert response['error'] == reason
    before = {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}
    result = inspect_session_input_terminal(root, root.parent / 'memory-library')
    assert result['commands']['first'] == {'kind': 'step', 'terminal_status': 'failed', 'action_executed': False}
    assert before == {str(p): p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('change', ['legacy', 'error_type', 'returned', 'command_id', 'reason',
    'input', 'action', 'phase', 'extra', 'worker', 'command_sha', 'caps', 'config',
    'resource_source', 'missing_resource', 'report_source', 'report_profile', 'missing_report',
    'response_command'])
def test_forged_or_unbound_vision_rejection_remains_unknown(tmp_path, change):
    root, command, response = setup_rejection(tmp_path)
    result = response['result']
    if change == 'legacy': response.pop('result')
    if change == 'error_type': response['error_type'] = 'AgentCommandError'
    if change == 'returned': response['status'] = 'returned'
    if change == 'command_id': result['command_id'] = 'other'
    if change == 'reason': result['reason'] = 'vision_unsupported'
    if change == 'input': result['input_attempted'] = None
    if change == 'action': result['action_executed'] = True
    if change == 'phase': result['phase'] = 'after_worker'
    if change == 'extra': result['extra'] = True
    if change == 'worker': save(root, 'agent-commands', 'first', {'command_id': 'first', 'status': 'running'})
    if change == 'command_sha': result['command_sha256'] = '0' * 64
    if change == 'caps': result['capabilities']['image_transport'] = 'supported'
    if change == 'config': result['configuration']['source'] = 'local'
    if change == 'response_command': response['command'] = {'kind': 'capture'}
    if change in {'resource_source', 'missing_resource'}:
        path = root / 'session-resources.json'
        if change == 'missing_resource': path.unlink()
        else:
            j = json.loads(path.read_text(encoding='utf-8')); j['recognition_source'] = 'local'
            path.write_text(json.dumps(j), encoding='utf-8')
    if change in {'report_source', 'report_profile', 'missing_report'}:
        path = root / 'report.json'
        if change == 'missing_report': path.unlink()
        else:
            r = json.loads(path.read_text(encoding='utf-8'))
            r['recognition_source' if change == 'report_source' else 'delegate_profile'] = 'local' if change == 'report_source' else 'other'
            path.write_text(json.dumps(r), encoding='utf-8')
    save(root, 'responses', 'first', response)
    with pytest.raises(ValueError, match='session_input_'):
        inspect_session_input_terminal(root, root.parent / 'memory-library')


def test_plain_historical_capability_error_still_blocks(tmp_path):
    root = tmp_path / 'session'
    command = {'kind': 'step', 'operation': 'execute_recognition_plan', 'request': {'goal': 'fresh'}}
    save(root, 'commands', 'original', command)
    save(root, 'responses', 'original', {'command': command, 'status': 'failed',
         'error_type': 'AgentCommandError', 'error': 'capability_unknown', 'automatic_retry_allowed': False})
    with pytest.raises(ValueError, match='session_input_synchronous_unknown'):
        inspect_session_input_terminal(root, root.parent / 'memory-library')


def test_eligible_route_cannot_claim_zero_input_rejection(tmp_path):
    root, command, response = setup_rejection(tmp_path)
    command['vision_capabilities'] = {'image_transport': 'supported', 'current_vision': 'supported'}
    response['command'] = command
    save(root, 'commands', 'first', command)
    save(root, 'responses', 'first', response)
    with pytest.raises(ValueError, match='session_input_vision_admission_route_available'):
        inspect_session_input_terminal(root, root.parent / 'memory-library')


def test_memory_unknown_route_exception_cannot_be_forged_as_rejection(tmp_path):
    root, command, response = setup_rejection(tmp_path)
    command['request']['target_memory'] = {'recipe_id': 'target-recipe-' + 'a' * 64,
        'interface_key': 'fresh-list', 'state_key': 'fresh'}
    response['command'] = command
    from app.vision.agent_command_jobs import AgentCommandVisionAdmissionError
    from app.vision.recognition_source import ClientVisionCapabilities
    error = AgentCommandVisionAdmissionError('first', command,
        RecognitionSourceConfig(source='agent_current'), ClientVisionCapabilities(), 'capability_unknown')
    response['result'] = error.before_dispatch_result('first')
    save(root, 'commands', 'first', command)
    save(root, 'responses', 'first', response)
    with pytest.raises(ValueError, match='session_input_vision_admission_memory_exception'):
        inspect_session_input_terminal(root, root.parent / 'memory-library')


def test_bound_source_report_drift_rejected_without_writing_input(tmp_path, monkeypatch):
    root, _, _ = setup_rejection(tmp_path)
    import app.execution.session_resources as resources
    original = resources.decode_session_resources
    def drift(session, raw):
        state = original(session, raw)
        path = root / 'report.json'
        value = json.loads(path.read_text(encoding='utf-8'))
        value['phase'] = 'changed'
        path.write_text(json.dumps(value), encoding='utf-8')
        return state
    monkeypatch.setattr(resources, 'decode_session_resources', drift)
    with pytest.raises(ValueError, match='session_input_catalog_changed'):
        inspect_session_input_terminal(root, root.parent / 'memory-library')


def test_epoch_input_inspection_reuses_strict_typed_guard(tmp_path):
    root, _, _ = setup_rejection(tmp_path)
    from app.execution.session_epoch_admission import _inspect_inputs
    result = _inspect_inputs(root, root.parent / 'memory-library')
    assert result['input_terminal_settlement_verified'] is True
    assert result['commands']['first']['action_executed'] is False
