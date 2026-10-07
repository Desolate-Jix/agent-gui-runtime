"""原排队的接管控制只能按确切 ID 和命令字节核验。"""
from hashlib import sha256

import pytest

from app.core.instant_command_queue import enqueue_command
from app.execution.session_input_terminal import inspect_session_input_terminal
from tests.test_workflow_recovery_import import import_scene
from tests.test_instant_epoch_recovery import epoch_scene
from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_trial import services


def current(scene, action='takeover_preview'):
    command = {'kind': 'learning_workflow', 'request': {'action': action,
        'admission_request_id': 'epoch-admission', 'source_run_id': scene.source_run_id}}
    enqueue_command(scene.new, 'current-preview', command)
    raw = (scene.new / 'commands/current-preview.json').read_bytes()
    return {'request_id': 'current-preview', 'command_sha256': sha256(raw).hexdigest()}


def test_pending_takeover_control_requires_exact_explicit_current_binding(import_scene):
    scene = import_scene
    binding = current(scene)
    with pytest.raises(ValueError, match='response_unproven'):
        inspect_session_input_terminal(scene.new, scene.library_root)
    proof = inspect_session_input_terminal(scene.new, scene.library_root, current_workflow_control=binding)
    assert proof['commands']['current-preview'] == {'kind': 'learning_workflow',
        'terminal_status': 'current_takeover_control', 'action_executed': None}
    assert proof['files']['commands/current-preview.json'] == binding['command_sha256']


@pytest.mark.parametrize('change', ['sha', 'id', 'action'])
def test_current_control_cannot_ignore_other_command_or_bytes(import_scene, change):
    scene = import_scene
    binding = current(scene, action='run' if change == 'action' else 'takeover_preview')
    if change == 'sha':
        binding['command_sha256'] = '0' * 64
    elif change == 'id':
        binding['request_id'] = 'another-request'
    with pytest.raises(ValueError):
        inspect_session_input_terminal(scene.new, scene.library_root, current_workflow_control=binding)
