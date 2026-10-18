"""原 Runtime 的接管入口自己采集现场并导入暂停账本。"""
from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.core.instant_command_queue import enqueue_command
from app.core.json_snapshot import write_json_snapshot, read_json_snapshot
from app.learning_memory.workflow_runtime import WorkflowRuntime
from tests.test_workflow_recovery_import import import_scene
from tests.test_instant_epoch_recovery import epoch_scene, old_bytes
from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_trial import services


@pytest.fixture
def public_scene(import_scene, monkeypatch):
    from app.learning_memory import workflow_takeover_observation as observer
    scene = import_scene
    calls = []
    changes = {}
    def read(coordinator, **kwargs):
        calls.append(kwargs)
        value = deepcopy(scene.envelope)
        frame = value['frame']
        control = {'control_id': 'query', 'runtime_id': [1, 71, 8],
            'control_type': 'Edit', 'automation_id': 'query', 'name': '当前字段',
            'bbox': {'x': 10, 'y': 10, 'w': 80, 'h': 20}}
        if changes.get('control'):
            control['runtime_id'] = [1, 71, 9]
        if changes.get('value'):
            value['observation']['values']['field_value'] = '另一个值'
        return {'frame': frame, 'window_identity': frame['window_identity'], 'capture_id': frame['capture_id'],
            'capture_sha256': frame['sha256'], 'scope_id': 'search-field', 'source': 'uia_value',
            'complete': True, 'values': value['observation']['values'], 'evidence': {'selected_control': control}}
    monkeypatch.setattr(observer, 'read_step_observation', read)
    co = SimpleNamespace(_memory_library_root=scene.library_root, _owner=SimpleNamespace(call=lambda fn: fn()))
    return SimpleNamespace(scene=scene, runtime=WorkflowRuntime(scene.new, co), calls=calls, changes=changes)


def run_control(public, request_id, request):
    command = {'kind': 'learning_workflow', 'request': deepcopy(request)}
    enqueue_command(public.scene.new, request_id, command)
    result = public.runtime.control(request, request_id)
    write_json_snapshot(public.scene.new / 'responses' / (request_id + '.json'),
        {'command': command, 'status': 'returned', 'result': result})
    return result


def preview(public):
    return run_control(public, 'public-preview', {'action': 'takeover_preview',
        'admission_request_id': 'epoch-admission', 'source_run_id': public.scene.source_run_id})


def commit(public, view, request_id='public-commit'):
    return run_control(public, request_id, {'action': 'takeover_commit', 'preview_request_id': 'public-preview',
        'preview_sha256': view['preview_sha256'], 'mode': 'until_wait'})


def test_public_preview_commit_reobserves_and_only_imports_paused_run(public_scene):
    public = public_scene
    view = preview(public)
    assert view['status'] == 'preview_ready' and len(public.calls) == 1
    assert not list((public.scene.new / 'workflow-trials').glob('trial-*.json'))
    snapshot = commit(public, view)
    assert snapshot['wait_reason'] == 'takeover_ready' and len(public.calls) == 2
    assert public.runtime._enabled_run is None
    commands = [read_json_snapshot(path) for path in (public.scene.new / 'commands').glob('*.json')]
    assert all(row['kind'] == 'learning_workflow' for row in commands)
    assert old_bytes(public.scene.epoch) == public.scene.old_before
    again = commit(public, view, 'public-commit-retry')
    assert again == snapshot and len(public.calls) == 2


@pytest.mark.parametrize('change', ['control', 'value'])
def test_commit_rejects_changed_current_object_or_result(public_scene, change):
    public = public_scene
    view = preview(public)
    public.changes[change] = True
    with pytest.raises(ValueError):
        commit(public, view)
    assert not list((public.scene.new.parent / 'workflow-takeovers').glob('*.json'))
    assert not list((public.scene.new / 'workflow-trials').glob('trial-*.json'))
    assert old_bytes(public.scene.epoch) == public.scene.old_before


def test_commit_rejects_wrong_preview_hash_before_observation(public_scene):
    public = public_scene
    view = preview(public)
    view['preview_sha256'] = '0' * 64
    with pytest.raises(ValueError):
        commit(public, view)
    assert len(public.calls) == 1


def test_preview_never_accepts_client_supplied_observation(public_scene):
    from app.learning_memory.workflow_control import validate_request
    with pytest.raises(ValueError):
        validate_request({'action': 'takeover_preview', 'admission_request_id': 'epoch-admission',
            'source_run_id': public_scene.scene.source_run_id, 'observation': public_scene.scene.envelope})


def test_public_actions_require_live_host(public_scene):
    from app.learning_memory.workspace import MemoryWorkspace
    from app.learning_memory.workflow_control import workflow_control
    with MemoryWorkspace(public_scene.scene.library_root) as library, pytest.raises(ValueError, match='requires_live_host'):
        workflow_control(library, public_scene.scene.new, {'action': 'takeover_preview',
            'admission_request_id': 'epoch-admission', 'source_run_id': public_scene.scene.source_run_id}, 'public-preview')
