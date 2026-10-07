"""接管的队列指纹只排除同一事务的确切控制。"""
from hashlib import sha256

import pytest

from app.core.instant_command_queue import enqueue_command
from app.core.json_snapshot import write_json_snapshot, read_json_snapshot
from app.desktop_review.external_mapping import canonical_json_bytes
from tests.test_workflow_recovery_import import import_scene
from tests.test_instant_epoch_recovery import epoch_scene
from tests.test_workflow_runtime import runtime_scene
from tests.test_workflow_trial import services
from tests.test_workflow_takeover_public import public_scene, preview, commit


def scope(scene):
    return {'preview_request_id': 'public-preview', 'admission_request_id': 'epoch-admission',
            'source_run_id': scene.source_run_id}


def resource_fingerprint(scene):
    return {'report.json': sha256(canonical_json_bytes(read_json_snapshot(scene.new / 'report.json'))).hexdigest(),
            'session-resources.json': sha256((scene.new / 'session-resources.json').read_bytes()).hexdigest()}


def command(scene, request_id='public-preview'):
    value = {'kind': 'learning_workflow', 'request': {'action': 'takeover_preview',
        'admission_request_id': 'epoch-admission', 'source_run_id': scene.source_run_id}}
    enqueue_command(scene.new, request_id, value)
    return value


def test_exact_pending_preview_and_later_response_do_not_change_input_fingerprint(import_scene):
    from app.learning_memory.workflow_takeover_controls import scoped_input_files
    scene = import_scene
    value = command(scene)
    first = scoped_input_files(scene.new, scene.library_root, scope(scene), current_request_id='public-preview')
    assert first == resource_fingerprint(scene)
    write_json_snapshot(scene.new / 'responses/public-preview.json',
                        {'command': value, 'status': 'returned', 'result': {'status': 'preview_ready'}})
    assert scoped_input_files(scene.new, scene.library_root, scope(scene)) == first


def test_another_preview_is_not_excluded(import_scene):
    from app.learning_memory.workflow_takeover_controls import scoped_input_files
    scene = import_scene
    value = command(scene, 'other-preview')
    with pytest.raises(ValueError):
        scoped_input_files(scene.new, scene.library_root, scope(scene), current_request_id='other-preview')
    write_json_snapshot(scene.new / 'responses/other-preview.json',
                        {'command': value, 'status': 'returned', 'result': {}})
    fingerprint = scoped_input_files(scene.new, scene.library_root, scope(scene))
    assert set(fingerprint) == set(resource_fingerprint(scene)) | {
        'commands/other-preview.json', 'responses/other-preview.json'}
    assert all(fingerprint[name] == value for name, value in resource_fingerprint(scene).items())


def test_commit_control_requires_the_original_preview_digest(import_scene):
    from app.learning_memory.workflow_takeover_controls import scoped_input_files, preview_path
    scene = import_scene
    payload = {'request_id': 'public-preview', 'source_run_id': scene.source_run_id,
        'admission_request_id': 'epoch-admission', 'prepared': {}, 'observation': {}}
    digest = sha256(canonical_json_bytes(payload)).hexdigest()
    preview_path(scene.new, 'public-preview').parent.mkdir()
    write_json_snapshot(preview_path(scene.new, 'public-preview'), {
        'contract_version': 'workflow_takeover_preview.v1', 'payload': payload, 'preview_sha256': digest})
    value = {'kind': 'learning_workflow', 'request': {'action': 'takeover_commit',
        'preview_request_id': 'public-preview', 'preview_sha256': digest, 'mode': 'until_wait'}}
    enqueue_command(scene.new, 'public-commit', value)
    assert scoped_input_files(scene.new, scene.library_root, scope(scene), current_request_id='public-commit') == resource_fingerprint(scene)
    value['request']['preview_sha256'] = '0' * 64
    write_json_snapshot(scene.new / 'commands/public-commit.json', value)
    with pytest.raises(ValueError):
        scoped_input_files(scene.new, scene.library_root, scope(scene), current_request_id='public-commit')


def preview_with_report_completion(public):
    from scripts.run_local_step_session import record_workflow_snapshot
    view = preview(public)
    path = public.scene.new / 'report.json'
    report = read_json_snapshot(path)
    record_workflow_snapshot(report, view, clear_error=False)
    report.setdefault('completed_commands', []).append({'name': 'public-preview.json', 'status': 'returned'})
    write_json_snapshot(path, report)
    return view


def test_public_preview_report_completion_preserves_input_binding(public_scene):
    public = public_scene
    view = preview_with_report_completion(public)
    snapshot = commit(public, view)
    assert snapshot['wait_reason'] == 'takeover_ready'
    assert public.runtime._enabled_run is None
    assert all(read_json_snapshot(path)['kind'] == 'learning_workflow'
               for path in (public.scene.new / 'commands').glob('*.json'))


@pytest.mark.parametrize('change', ['runner_pid', 'target', 'other_completed', 'status', 'workflow_result',
                                   'real_input', 'other_scope', 'worker', 'unproven_response'])
def test_report_normalization_does_not_hide_other_drift(public_scene, change):
    public = public_scene
    view = preview_with_report_completion(public)
    path = public.scene.new / 'report.json'
    report = read_json_snapshot(path)
    if change == 'runner_pid': report['runner_pid'] = 777777
    if change == 'target': report['target'] = {'handle': 999, 'process_id': 998}
    if change == 'other_completed': report['completed_commands'].append({'name': 'other.json', 'status': 'returned'})
    if change == 'status': report['completed_commands'][0]['status'] = 'failed'
    if change == 'workflow_result': report['workflow_run']['status'] = 'invented'
    if change == 'real_input':
        value = {'kind': 'step', 'operation': 'type_text', 'request': {'text': 'fresh'}}
        enqueue_command(public.scene.new, 'real-input', value)
        write_json_snapshot(public.scene.new / 'responses/real-input.json', {'command': value,
            'status': 'returned', 'result': {'phase': 'returned', 'response': {'data': {'action_executed': True}}}})
    if change == 'other_scope':
        value = command(public.scene, 'other-preview')
        write_json_snapshot(public.scene.new / 'responses/other-preview.json',
                            {'command': value, 'status': 'returned', 'result': {'status': 'preview_ready'}})
        report['workflow_run'] = {'status': 'preview_ready'}
        report['completed_commands'].append({'name': 'other-preview.json', 'status': 'returned'})
    if change == 'worker':
        (public.scene.new / 'agent-commands').mkdir(exist_ok=True)
        write_json_snapshot(public.scene.new / 'agent-commands/orphan.json', {'status': 'running'})
    if change == 'unproven_response':
        original = read_json_snapshot(public.scene.new / 'responses/public-preview.json')
        original['result'] = {'status': 'different_projection'}
        write_json_snapshot(public.scene.new / 'responses/public-preview.json', original)
    write_json_snapshot(path, report)
    with pytest.raises(ValueError):
        commit(public, view)
    assert not list((public.scene.new / 'workflow-trials').glob('trial-*.json'))


def test_pending_preview_cannot_claim_completed_report_without_receipt(import_scene):
    from app.learning_memory.workflow_takeover_controls import scoped_input_files
    scene = import_scene
    command(scene)
    path = scene.new / 'report.json'
    report = read_json_snapshot(path)
    report['completed_commands'] = [{'name': 'public-preview.json', 'status': 'returned'}]
    report['workflow_run'] = {'status': 'preview_ready'}
    write_json_snapshot(path, report)
    with pytest.raises(ValueError, match='workflow_takeover_control_binding_invalid'):
        scoped_input_files(scene.new, scene.library_root, scope(scene), current_request_id='public-preview')
