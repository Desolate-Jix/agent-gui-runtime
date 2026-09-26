"""Agent 组合动作协议、回执和宿主路由；不调用真实键鼠。"""
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.instant_mcp import InstantCommand, InstantSession, write_json


CAPS = {'image_transport': 'supported', 'current_vision': 'supported'}


@pytest.mark.parametrize('kind', ['agent_command_status', 'agent_command_cancel', 'agent_command_continue'])
def test_command_reference_schema(kind):
    request = {'command_id': 'batch-1'}
    if kind == 'agent_command_continue':
        request['grounding_request_id'] = 'ground-1'
    value = {'kind': kind, 'request': request}
    assert InstantCommand.model_validate(value).command() == value
    with pytest.raises(ValueError):
        InstantCommand.model_validate({'kind': kind, 'request': {**request, 'replacement_x': 1}}).command()


def test_batch_capability_declaration_not_available_on_unrelated_commands():
    value = {'kind': 'input_sequence', 'request': {'field_goal': 'Search', 'text': 'test', 'submit_search': False},
             'vision_capabilities': CAPS}
    assert InstantCommand.model_validate(value).command() == value
    with pytest.raises(ValueError):
        InstantCommand.model_validate({'kind': 'discover', 'vision_capabilities': CAPS}).command()


@pytest.mark.parametrize('status,ok', [('running', None), ('awaiting_grounding', None),
    ('completed', True), ('failed', False), ('cancelled', False)])
def test_agent_command_receipt_never_calls_waiting_or_failed_work_success(tmp_path, status, ok):
    session = InstantSession(tmp_path, tmp_path, None, recognition_source='agent_current')
    session.session = tmp_path
    (tmp_path / 'responses').mkdir()
    write_json(tmp_path / 'responses/status-1.json', {'status': 'returned', 'result': {
        'contract_version': 'agent_command.v1', 'command_id': 'batch-1', 'status': status,
        'action_executed': None, 'result': {'status': 'completed'} if status == 'completed' else None}})
    receipt = session.result('status-1')
    assert receipt['operation_succeeded'] is ok
    assert receipt['task_effect_verified'] is None
    assert receipt['action_executed'] is None
    assert receipt['operation_success_scope'] == 'agent_command_progress'
    if status in {'running', 'awaiting_grounding'}:
        assert receipt['next']['tool'] == 'instant_run'
        assert receipt['next']['arguments']['command']['kind'] == 'agent_command_status'


def test_agent_read_text_returns_original_for_agent_without_local_ocr(monkeypatch):
    from scripts.run_local_step_session import run_read_text_command
    import app.operation.screen_reading.captured_text as text
    monkeypatch.setattr(text, 'read_captured_text', lambda *a, **k: pytest.fail('must not load OCR'))
    result, observation = run_read_text_command(lambda: {'image_path': 'original.png', 'sha256': 'digest'},
        {'kind': 'read_text'}, recognition_source='agent_current')
    assert result['status'] == 'agent_read_required'
    assert result['text'] is None
    assert observation['image_path'] == 'original.png'
    assert result['recognition_source'] == 'agent_current'


def test_active_job_blocks_other_input_before_coordinator_dispatch():
    from scripts.run_local_step_session import check_agent_command_admission
    jobs = SimpleNamespace(active=True)
    for kind in ('step', 'launch', 'select', 'maximize', 'form_fill', 'grounding_execute', 'desktop_click'):
        with pytest.raises(ValueError, match='agent_command_in_progress'):
            check_agent_command_admission(jobs, kind)
    for kind in ('close', 'agent_command_status', 'agent_command_continue', 'agent_command_cancel',
                 'grounding_resolve', 'grounding_status', 'grounding_cancel'):
        check_agent_command_admission(jobs, kind)


def test_host_routes_batches_and_recognition_but_not_keys_to_agent_jobs():
    from scripts.run_local_step_session import dispatch_agent_command
    calls = []
    jobs = SimpleNamespace(active=False, start=lambda *args: calls.append(args) or {'status': 'running'},
        get=lambda key: {'command_id': key}, cancel=lambda key: {'cancel_requested': True},
        resume=lambda *args: calls.append(args) or {'status': 'running'})
    target = {'handle': 1, 'process_id': 2}
    for kind in ('form_fill', 'input_sequence', 'step'):
        cmd = {'kind': kind, 'operation': 'execute_recognition_plan', 'request': {}, 'vision_capabilities': CAPS}
        assert dispatch_agent_command(jobs, 'batch-1', cmd, target)['status'] == 'running'
        assert calls[-1] == ('batch-1', cmd, target, CAPS)
    assert dispatch_agent_command(jobs, 'key-1', {'kind': 'step', 'operation': 'press_key'}, target) is None
    assert dispatch_agent_command(None, 'local-1', {'kind': 'form_fill'}, target) is None
    assert dispatch_agent_command(jobs, 'status-1', {'kind': 'agent_command_status',
        'request': {'command_id': 'batch-1'}}, target) == {'command_id': 'batch-1'}
    dispatch_agent_command(jobs, 'continue-1', {'kind': 'agent_command_continue',
        'request': {'command_id': 'batch-1', 'grounding_request_id': 'ag-1'}}, target)
    assert calls[-1] == ('batch-1', 'ag-1', 'continue-1')
    with pytest.raises(ValueError, match='requires_agent_source'):
        dispatch_agent_command(None, 'status-2', {'kind': 'agent_command_status'}, target)


def test_agent_job_before_image_unwraps_completed_original_receipt(tmp_path):
    from hashlib import sha256
    from PIL import Image
    image = tmp_path / 'before.png'
    Image.new('RGB', (10, 10), 'white').save(image)
    capture = {'image_path': str(image), 'sha256': sha256(image.read_bytes()).hexdigest()}
    session = InstantSession(tmp_path, tmp_path, None, recognition_source='agent_current')
    session.session = tmp_path
    (tmp_path / 'responses').mkdir()
    write_json(tmp_path / 'responses/completed-1.json', {'status': 'returned', 'result': {
        'contract_version': 'agent_command.v1', 'command_id': 'batch-1', 'status': 'completed',
        'action_executed': True, 'result': {'capture': capture}}})
    assert session.image('completed-1', 'before') == image.read_bytes()


def test_compact_agent_job_retains_handoff_and_compacts_terminal_batch():
    from app.instant_receipt import compact_receipt
    pending = {'request_id': 'ag-1', 'goal': 'Search', 'capture': {'sha256': 'one'},
               'output_schema': {'type': 'object'}}
    value = compact_receipt({'request_id': 'status-1', 'result': {
        'contract_version': 'agent_command.v1', 'command_id': 'batch-1',
        'status': 'awaiting_grounding', 'pending_grounding': pending,
        'progress': {'contract_version': 'form_fill_v1', 'completed_fields': [0],
                     'fields': [], 'unneeded_trace': 'x' * 10000}}})
    assert value['agent_command']['pending_grounding'] == pending
    assert value['agent_command']['progress']['form']['completed_fields'] == [0]
    assert 'unneeded_trace' not in str(value)
    value = compact_receipt({'request_id': 'status-2', 'result': {
        'contract_version': 'agent_command.v1', 'command_id': 'batch-1', 'status': 'completed',
        'result': {'contract_version': 'input_sequence_v1', 'status': 'completed',
            'completed_steps': ['focus', 'type'], 'steps': [], 'unneeded_trace': 'x' * 10000}}})
    assert value['agent_command']['result']['sequence']['completed_steps'] == ['focus', 'type']
    assert 'unneeded_trace' not in str(value)
