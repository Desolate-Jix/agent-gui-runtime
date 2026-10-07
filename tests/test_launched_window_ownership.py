"""新 launch 归属只能沿原 ready epoch 证明用于正常关闭。"""
from copy import deepcopy
from types import SimpleNamespace
from pathlib import Path
import hashlib
import json
import pytest
from tests.test_launched_window_close import Coordinator, Windows, IDENTITY
from app.desktop_review import window_preparation as windows_module


def test_new_launch_records_final_fresh_ownership(monkeypatch):
    co = Coordinator(Windows())
    co._launched_window_identities.clear()
    monkeypatch.setattr(windows_module.WindowsNativeIdentityReader, 'read_identity',
                        lambda self, handle: deepcopy(IDENTITY))
    result = co._await_launched_window({'executable_path': IDENTITY['executable_path'], 'source': 'app_catalog'},
                                     SimpleNamespace(pid=202), set())
    assert result.get('launch_ownership') == {'contract_version': 'launched_window_ownership.v1',
           'newly_launched': True, 'identity': IDENTITY}


def test_new_coordinator_cannot_close_without_explicit_recovery_contract(monkeypatch):
    co = Coordinator(Windows())
    co._launched_window_identities.clear()
    monkeypatch.setattr(windows_module, 'post_window_close', lambda handle: pytest.fail('no ownership must not close'))
    with pytest.raises(RuntimeError) as caught:
        co.close_launched_window(target_window_handle=101, target_process_id=202)
    assert caught.value.code == 'window_close_not_launched'

from app.core.json_snapshot import write_json_snapshot, read_json_snapshot
from app.execution import launched_window_ownership as ownership
from app.execution import session_epoch_admission as epoch
from app.execution.session_resources import SessionResourceJournal
from app.execution.session_input_terminal import inspect_session_input_terminal
from app.vision.recognition_source import RecognitionSourceConfig


@pytest.fixture
def admitted(tmp_path, monkeypatch):
    old = tmp_path / ('session-' + 'a' * 32)
    new = tmp_path / ('session-' + 'b' * 32)
    old.mkdir()
    new.mkdir()
    origin = {'pid': 301, 'created': 123.0}
    current = {'pid': 303, 'created': 456.0}
    config = RecognitionSourceConfig(source='agent_current')
    pointer = {'name': old.name, 'host_identity': origin, 'recognition_source': config.source,
               'delegate_profile': None, 'api_profile': None}
    write_json_snapshot(tmp_path / 'latest-session.json', pointer)
    write_json_snapshot(old / 'report.json', {'phase': 'stopped', 'runner_pid': 301})
    SessionResourceJournal(old, recognition_source=config.source, host_identity=origin,
        runner_identity={'pid': 301, 'create_time_ns': 123000000000}).mark_ready()
    command = {'kind': 'launch', 'path': IDENTITY['executable_path'], 'prefer_existing': False}
    result = {'status': 'launched_window_ready', 'process_id': 202,
              'window': {'handle': 101, 'process_id': 202},
              'launch_ownership': {'contract_version': 'launched_window_ownership.v1',
                                  'newly_launched': True, 'identity': deepcopy(IDENTITY)}}
    (old / 'commands').mkdir()
    (old / 'responses').mkdir()
    write_json_snapshot(old / 'commands/launch-one.json', command)
    write_json_snapshot(old / 'responses/launch-one.json', {'status': 'returned', 'command': command, 'result': result})
    inputs = inspect_session_input_terminal(old, tmp_path / 'memory-library')
    from app.desktop_review.external_mapping import canonical_json_bytes
    resource = {'resources_cleanup_verified': True, 'session_name': old.name, 'host_identity': origin,
        'runner_identity': {'pid': 301, 'create_time_ns': 123000000000}, 'recognition_source': config.source,
        'original_snapshots': {key: hashlib.sha256(path.read_bytes()).hexdigest() for key, path in {
            'pointer': tmp_path / 'latest-session.json', 'report': old / 'report.json',
            'resources': old / 'session-resources.json'}.items()}}
    preview = {'contract_version': 'session_epoch_admission_preview.v1', 'source_session': str(old),
        'original_pointer_raw_utf8': (tmp_path / 'latest-session.json').read_bytes().decode('utf-8'),
        'resource_proof': resource, 'input_proof': inputs}
    digest = hashlib.sha256(canonical_json_bytes(preview)).hexdigest()
    preview['preview_sha256'] = digest
    record = {'contract_version': 'session_epoch_admission.v1', 'request_id': 'admit-one',
        'preview_sha256': digest, 'preview': preview, 'new_session_name': new.name,
        'phase': 'ready', 'new_host_identity': current}
    (tmp_path / 'recovery-admissions').mkdir()
    write_json_snapshot(tmp_path / 'recovery-admissions/admit-one.json', record)
    write_json_snapshot(tmp_path / 'latest-session.json', {**pointer, 'name': new.name, 'host_identity': current})
    write_json_snapshot(new / 'report.json', {'phase': 'ready', 'runner_pid': 303})
    SessionResourceJournal(new, recognition_source=config.source, host_identity=current,
        runner_identity={'pid': 303, 'create_time_ns': 456000000000}).mark_ready()
    code = tmp_path / 'code'
    argv = ['python.exe', str(code / 'scripts/run_local_step_session.py'), '--output', str(new),
            '--recognition-source', config.source, '--local-no-learning', '--parent-pid', '999']
    process = SimpleNamespace(create_time=lambda: 456.0, is_running=lambda: True,
        status=lambda: 'running', cmdline=lambda: argv, ppid=lambda: 999)
    monkeypatch.setattr(epoch.psutil, 'Process', lambda pid: process)
    monkeypatch.setattr(epoch, '_inactive', lambda *args: None)
    co = Coordinator(Windows())
    co._launched_window_identities.clear()
    monkeypatch.setattr(windows_module.WindowsNativeIdentityReader, 'read_identity',
                        lambda self, handle: deepcopy(IDENTITY))
    posted = []
    monkeypatch.setattr(windows_module, 'post_window_close', lambda handle: posted.append(handle))
    monkeypatch.setattr(windows_module, 'window_handle_exists', lambda handle: not posted)
    def verify():
        return ownership.verify_recovered_launch_ownership(new, code, config,
            {'admission_request_id': 'admit-one', 'launch_request_id': 'launch-one'}, co)
    return SimpleNamespace(old=old, new=new, root=tmp_path, co=co, verify=verify, posted=posted,
                           argv=argv, record=record)


def test_original_epoch_proof_closes_without_importing_registry(admitted):
    before = {p: p.read_bytes() for p in admitted.old.rglob('*') if p.is_file()}
    proof = admitted.verify()
    assert admitted.co._launched_window_identities == {}
    result = admitted.co.close_launched_window(target_window_handle=101, target_process_id=202,
                                               recovery_proof=proof)
    assert result['status'] == 'window_closed'
    assert admitted.posted == [101]
    claims = list((admitted.new / 'launched-window-close-claims').glob('*.json'))
    assert len(claims) == 1
    assert read_json_snapshot(claims[0])['status'] == 'window_closed'
    assert {p: p.read_bytes() for p in admitted.old.rglob('*') if p.is_file()} == before
    with pytest.raises(ValueError, match='claim_unresolved'):
        admitted.co.close_launched_window(target_window_handle=101, target_process_id=202,
                                          recovery_proof=admitted.verify())
    assert admitted.posted == [101]


@pytest.mark.parametrize('change', ['response', 'command', 'report', 'resources', 'pointer',
                                    'phase', 'host', 'configuration'])
def test_source_and_epoch_drift_refuse_without_close(admitted, change):
    proof = admitted.verify()
    path = {'response': admitted.old / 'responses/launch-one.json',
            'command': admitted.old / 'commands/launch-one.json',
            'report': admitted.old / 'report.json',
            'resources': admitted.old / 'session-resources.json',
            'pointer': admitted.root / 'latest-session.json'}.get(change)
    if path:
        path.write_bytes(path.read_bytes() + b' ')
        if change == 'pointer':
            write_json_snapshot(path, {'name': 'session-' + 'c' * 32})
    elif change == 'phase':
        write_json_snapshot(admitted.new / 'report.json', {'phase': 'stopped', 'runner_pid': 303})
    elif change == 'host':
        admitted.argv[admitted.argv.index('--parent-pid') + 1] = '111'
    else:
        admitted.argv[admitted.argv.index('--recognition-source') + 1] = 'local'
    with pytest.raises(ValueError):
        admitted.co.close_launched_window(target_window_handle=101, target_process_id=202, recovery_proof=proof)
    assert admitted.posted == []


@pytest.mark.parametrize('field,value', [('process_create_time', 13.5),
    ('executable_path', r'c:\\other.exe'), ('process_id', 999), ('target_window_handle', 999)])
def test_fresh_identity_drift_precedes_claim(admitted, monkeypatch, field, value):
    proof = admitted.verify()
    changed = {**IDENTITY, field: value}
    monkeypatch.setattr(windows_module.WindowsNativeIdentityReader, 'read_identity', lambda *args: changed)
    with pytest.raises(RuntimeError):
        admitted.co.close_launched_window(target_window_handle=101, target_process_id=202, recovery_proof=proof)
    assert admitted.posted == []
    assert not (admitted.new / 'launched-window-close-claims').exists()


def test_unknown_claim_cannot_resend_even_same_co(admitted):
    proof = admitted.verify()
    proof.claim(admitted.co)
    with pytest.raises(ValueError, match='claim_unresolved'):
        admitted.co.close_launched_window(target_window_handle=101, target_process_id=202,
                                          recovery_proof=admitted.verify())
    assert admitted.posted == []


def test_raw_dictionary_cannot_grant_ownership_even_existing_owner(monkeypatch):
    co = Coordinator(Windows())
    with pytest.raises(ValueError, match='proof_invalid'):
        co.close_launched_window(target_window_handle=101, target_process_id=202, recovery_proof=deepcopy(IDENTITY))


@pytest.mark.parametrize('payload', [None, {}, {'source_session': 'x'},
    {'admission_request_id': '../bad', 'launch_request_id': 'launch'},
    {'admission_request_id': 'a', 'launch_request_id': 'b', 'identity': IDENTITY}])
def test_public_recovery_request_is_exact_and_never_falls_back(payload):
    from app.instant_mcp import InstantCommand
    with pytest.raises(ValueError):
        InstantCommand.model_validate({'kind': 'close_launched_window', 'handle': 101,
                                       'process_id': 202, 'request': payload}).command()


def test_public_normal_and_recovered_requests_keep_original_fields():
    from app.instant_mcp import InstantCommand
    ordinary = {'kind': 'close_launched_window', 'handle': 101, 'process_id': 202}
    assert InstantCommand.model_validate(ordinary).command() == ordinary
    explicit = {**ordinary, 'request': {'admission_request_id': 'admit-one', 'launch_request_id': 'launch-one'}}
    assert InstantCommand.model_validate(explicit).command() == explicit

def reseal_source(scene):
    from app.desktop_review.external_mapping import canonical_json_bytes
    path = scene.root / 'recovery-admissions/admit-one.json'
    record = read_json_snapshot(path)
    record['preview']['input_proof'] = inspect_session_input_terminal(scene.old, scene.root / 'memory-library')
    value = {k: v for k, v in record['preview'].items() if k != 'preview_sha256'}
    digest = hashlib.sha256(canonical_json_bytes(value)).hexdigest()
    record['preview']['preview_sha256'] = digest
    record['preview_sha256'] = digest
    write_json_snapshot(path, record)


@pytest.mark.parametrize('change', ['legacy', 'focus', 'select', 'not_new', 'bad_identity', 'window_pid',
                                    'response_failed', 'command_mismatch'])
def test_original_launch_must_prove_new_complete_identity(admitted, change):
    path = admitted.old / 'responses/launch-one.json'
    response = read_json_snapshot(path)
    if change == 'legacy':
        response['result'].pop('launch_ownership')
    elif change in {'focus', 'select'}:
        response['result']['status'] = change + '_window_ready'
    elif change == 'not_new':
        response['result']['launch_ownership']['newly_launched'] = False
    elif change == 'bad_identity':
        response['result']['launch_ownership']['identity'].pop('process_create_time')
    elif change == 'window_pid':
        response['result']['window']['process_id'] = 999
    elif change == 'response_failed':
        response['status'] = 'failed'
    else:
        response['command']['prefer_existing'] = True
    write_json_snapshot(path, response)
    if change == 'command_mismatch':
        with pytest.raises(ValueError, match='response_unproven'):
            reseal_source(admitted)
    else:
        reseal_source(admitted)
    with pytest.raises(ValueError):
        admitted.verify()
    assert admitted.posted == []


@pytest.mark.parametrize('change', ['not_ready', 'different_session', 'outside_root', 'digest', 'source_sha'])
def test_admission_relation_must_remain_strict(admitted, change):
    path = admitted.root / 'recovery-admissions/admit-one.json'
    record = read_json_snapshot(path)
    if change == 'not_ready':
        record['phase'] = 'pointer_published'
    elif change == 'different_session':
        record['new_session_name'] = 'session-' + 'c' * 32
    elif change == 'outside_root':
        record['preview']['source_session'] = str(admitted.root.parent / admitted.old.name)
    elif change == 'digest':
        record['preview_sha256'] = '0' * 64
    else:
        record['preview']['input_proof']['files']['responses/launch-one.json'] = '0' * 64
    write_json_snapshot(path, record)
    with pytest.raises(ValueError):
        admitted.verify()
    assert admitted.posted == []


def test_unknown_close_failure_preserves_claim_and_never_replays(admitted, monkeypatch):
    def fail(handle):
        admitted.posted.append(handle)
        raise OSError('unknown after close request')
    monkeypatch.setattr(windows_module, 'post_window_close', fail)
    with pytest.raises(OSError):
        admitted.co.close_launched_window(target_window_handle=101, target_process_id=202,
                                          recovery_proof=admitted.verify())
    claim = next((admitted.new / 'launched-window-close-claims').glob('*.json'))
    assert read_json_snapshot(claim)['status'] == 'started'
    with pytest.raises(ValueError, match='claim_unresolved'):
        admitted.co.close_launched_window(target_window_handle=101, target_process_id=202,
                                          recovery_proof=admitted.verify())
    assert admitted.posted == [101]

def test_recovered_pending_close_can_confirm_without_second_dispatch(admitted, monkeypatch):
    monkeypatch.setattr(windows_module, 'window_handle_exists', lambda handle: True)
    monkeypatch.setattr(windows_module, 'observe_close_wait',
        lambda *args: {'status': 'window_still_present', 'parent_enabled': True, 'owned_windows': []})
    result = admitted.co.close_launched_window(target_window_handle=101, target_process_id=202,
                                               recovery_proof=admitted.verify())
    assert result['status'] == 'window_close_pending'
    result2 = admitted.co.close_launched_window(target_window_handle=101, target_process_id=202,
                                                recovery_proof=admitted.verify())
    assert result2['status'] == 'window_close_pending'
    assert admitted.posted == [101]
    monkeypatch.setattr(windows_module, 'window_handle_exists', lambda handle: False)
    result3 = admitted.co.close_launched_window(target_window_handle=101, target_process_id=202,
                                                recovery_proof=admitted.verify())
    assert result3['status'] == 'window_closed'
    assert admitted.posted == [101]


def test_modal_dismissal_allows_existing_explicit_close_path(admitted, monkeypatch):
    monkeypatch.setattr(windows_module, 'window_handle_exists', lambda handle: True)
    monkeypatch.setattr(windows_module, 'observe_close_wait',
        lambda *args: {'status': 'owned_modal_visible', 'parent_enabled': False,
                       'owned_windows': [{'handle': 909}]})
    result = admitted.co.close_launched_window(target_window_handle=101, target_process_id=202,
                                               recovery_proof=admitted.verify())
    assert result['status'] == 'window_close_pending'
    monkeypatch.setattr(windows_module, 'observe_close_wait',
        lambda *args: {'status': 'window_still_present', 'parent_enabled': True, 'owned_windows': []})
    monkeypatch.setattr(windows_module, 'window_handle_exists', lambda handle: len(admitted.posted) < 2)
    result = admitted.co.close_launched_window(target_window_handle=101, target_process_id=202,
                                               recovery_proof=admitted.verify())
    assert result['status'] == 'window_closed'
    assert admitted.posted == [101, 101]


def test_identity_changes_during_claim_validation_never_dispatch(admitted, monkeypatch):
    proof = admitted.verify()
    original_claim = proof.claim
    def claim(co, **kwargs):
        original_claim(co, **kwargs)
        monkeypatch.setattr(windows_module.WindowsNativeIdentityReader, 'read_identity',
                            lambda *args: {**IDENTITY, 'process_create_time': 99.0})
    monkeypatch.setattr(proof, 'claim', claim)
    with pytest.raises(RuntimeError) as caught:
        admitted.co.close_launched_window(target_window_handle=101, target_process_id=202, recovery_proof=proof)
    assert caught.value.code == 'window_close_identity_changed'
    assert admitted.posted == []

def test_pending_claim_without_owner_wait_state_cannot_resend(admitted, monkeypatch):
    monkeypatch.setattr(windows_module, 'window_handle_exists', lambda handle: True)
    monkeypatch.setattr(windows_module, 'observe_close_wait',
        lambda *args: {'status': 'window_still_present', 'parent_enabled': True, 'owned_windows': []})
    admitted.co.close_launched_window(target_window_handle=101, target_process_id=202,
                                     recovery_proof=admitted.verify())
    admitted.co._launched_window_close_state.clear()
    with pytest.raises(ValueError, match='claim_unresolved'):
        admitted.co.close_launched_window(target_window_handle=101, target_process_id=202,
                                          recovery_proof=admitted.verify())
    assert admitted.posted == [101]

@pytest.mark.parametrize('field', ['admission_request_id', 'launch_request_id'])
@pytest.mark.parametrize('invalid', ['Uppercase', 'a' * 81])
def test_recovery_ids_use_original_instant_contract(field, invalid):
    payload = {'admission_request_id': 'admit-one', 'launch_request_id': 'launch-one', field: invalid}
    with pytest.raises(ValueError):
        ownership.validate_close_ownership_request(payload)


@pytest.mark.parametrize('operation', ['claim', 'finish'])
def test_claim_path_outside_session_refuses_before_any_write(admitted, operation):
    proof = admitted.verify()
    outside = admitted.root / 'outside-claims'
    proof.path = outside / 'claim.json'
    with pytest.raises(ValueError, match='claim_path_outside_session'):
        if operation == 'claim':
            proof.claim(admitted.co)
        else:
            proof.finish({'status': 'window_closed'})
    assert not outside.exists()
    assert admitted.posted == []
