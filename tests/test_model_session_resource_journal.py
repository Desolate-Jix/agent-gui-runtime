"""资源登记必须先于启动、请求状态和完成发布；不启动真实模型。"""
import json
from threading import Event, RLock
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from app.core import model_server
from app.learn.hybrid import windows_process_scope as scopes
from app.vision.model_service import FormalModelService, ModelServiceConfiguration


class Journal:
    def __init__(self, fail=None):
        self.rows = []
        self.fail = fail

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.rows.append((name, args, kwargs))
            if self.fail == name:
                raise OSError('journal unavailable')
        return record


def service(tmp_path, journal):
    return FormalModelService(ModelServiceConfiguration(2, json.dumps({
        'profile_id': 'fresh', 'port': 13333, 'model_name': 'test',
        'endpoint': 'http://127.0.0.1:13333', 'request_cancel_supported': True})),
        output_root=tmp_path, allow_resource_coexistence=True, resource_journal=journal)


def test_owned_launch_records_scope_before_creation_and_child_before_ready(tmp_path, monkeypatch):
    journal = Journal()
    value = service(tmp_path, journal)
    identity = {'pid': 12345, 'create_time_ns': 444}
    created = []
    monkeypatch.setattr(scopes, '_listeners', lambda ports: [])
    monkeypatch.setattr(scopes, 'scoped_process_launch_ready', lambda: True)
    def scope(*args, **kwargs):
        assert journal.rows[-1][0] == 'begin_model_scope'
        created.append(True)
        return SimpleNamespace(pids=lambda: [12345], job_policy=lambda: {'breakaway_allowed': False})
    monkeypatch.setattr(scopes, 'WindowsProcessScope', scope)
    monkeypatch.setattr(scopes, '_identities_for_pids', lambda pids: [identity])
    probes = iter([{'status': 'unreachable'}, {'status': 'running', 'model_id': 'test'},
                   {'status': 'running', 'model_id': 'test'}])
    monkeypatch.setattr(value, '_probe', lambda deadline: next(probes))
    monkeypatch.setattr(value, '_listener_identity', lambda: ((12345, 444),))
    def launch(*args, **kwargs):
        assert journal.rows[-1][0] == 'begin_model_launch'
        kwargs['before_resume'](identity)
        return {}
    monkeypatch.setattr(model_server, 'start_model_server', launch)
    assert value.prepare(Event())['ownership'] == 'owned'
    assert [row[0] for row in journal.rows] == ['register_model', 'begin_model_scope',
        'model_scope_acquired', 'begin_model_launch', 'model_process_created', 'model_ready']
    assert journal.rows[-1][2]['member_identities'] == [identity]
    assert created


@pytest.mark.parametrize('stage', ['begin_model_scope', 'begin_model_launch'])
def test_failed_registration_never_launches(tmp_path, monkeypatch, stage):
    journal = Journal(stage)
    value = service(tmp_path, journal)
    monkeypatch.setattr(value, '_probe', lambda deadline: {'status': 'unreachable'})
    monkeypatch.setattr(value, 'close', Mock(return_value={'cleanup_verified': True}))
    monkeypatch.setattr(scopes, '_listeners', lambda ports: [])
    monkeypatch.setattr(scopes, 'scoped_process_launch_ready', lambda: True)
    scope = Mock(return_value=SimpleNamespace(job_policy=lambda: {}, pids=lambda: []))
    monkeypatch.setattr(scopes, 'WindowsProcessScope', scope)
    launch = Mock(side_effect=AssertionError('must not launch'))
    monkeypatch.setattr(model_server, 'start_model_server', launch)
    with pytest.raises(Exception):
        value.prepare(Event())
    launch.assert_not_called()
    if stage == 'begin_model_scope':
        scope.assert_not_called()


def test_external_ready_registers_listener_without_scope_or_launch(tmp_path, monkeypatch):
    journal = Journal()
    value = service(tmp_path, journal)
    monkeypatch.setattr(value, '_probe', lambda deadline: {'status': 'running', 'model_id': 'test'})
    monkeypatch.setattr(value, '_listener_identity', lambda: ((12, 34),))
    monkeypatch.setattr(scopes, 'WindowsProcessScope', lambda *a, **k: pytest.fail('external scope acquired'))
    value.prepare(Event())
    assert journal.rows[-1][2] == {'ownership': 'external', 'member_identities': [{'pid': 12, 'create_time_ns': 34}]}


def test_request_persistence_failure_keeps_pending_identity(tmp_path):
    journal = Journal('model_request_started')
    value = service(tmp_path, journal)
    value._prepared = True
    with pytest.raises(OSError):
        value.begin_request('original-request')
    assert value._pending_request_id is None
    journal.fail = None
    value.begin_request('original-request')
    journal.fail = 'model_request_finished'
    with pytest.raises(OSError):
        value.complete_request('original-request')
    assert value._pending_request_id == 'original-request'
    journal.fail = None
    value.complete_request('original-request')
    value.close()
    assert journal.rows[-1][0] == 'model_closed'


@pytest.mark.parametrize('entry', ['start', 'launch'])
def test_before_resume_requires_explicit_scope_before_launch(tmp_path, entry):
    with pytest.raises(ValueError, match='scope'):
        if entry == 'start':
            model_server.start_model_server({}, before_resume=lambda identity: None)
        else:
            model_server._launch_model_server_process(profile={}, log_path=tmp_path/'never.log',
                command=['never'], before_resume=lambda identity: None)
    assert not (tmp_path/'never.log').exists()


def test_wrapper_propagates_failing_registration_before_resume(tmp_path, monkeypatch):
    resumed = []
    journal = Journal('model_process_created')
    def spawn(*args, **kwargs):
        kwargs['before_resume']({'pid': 42, 'create_time_ns': 99})
        resumed.append(True)
        raise AssertionError('must not resume')
    monkeypatch.setattr(scopes, 'spawn_process_in_scope', spawn)
    monkeypatch.setattr(model_server.subprocess, 'Popen', lambda *a, **k: pytest.fail('unscoped launch'))
    with pytest.raises(OSError, match='journal unavailable'):
        model_server._launch_model_server_process(profile={'pid_file': str(tmp_path/'never.pid')},
            log_path=tmp_path/'launch.log', command=['never'], scope_name='Local\\fresh-owned',
            before_resume=lambda identity: journal.model_process_created('resource', identity))
    assert not resumed
    assert journal.rows[0][0] == 'model_process_created'


def test_owned_ready_rejects_partial_member_identities(tmp_path, monkeypatch):
    journal = Journal()
    value = service(tmp_path, journal)
    value._ownership = 'owned'
    value._scope = SimpleNamespace(pids=lambda: [12, 13])
    monkeypatch.setattr(scopes, '_identities_for_pids', lambda pids: [{'pid': 12, 'create_time_ns': 34}])
    with pytest.raises(Exception, match='instance_unobservable'):
        value._journal_ready()
    assert all(row[0] != 'model_ready' for row in journal.rows)


def test_cancel_persists_finished_only_after_verified_stop(tmp_path, monkeypatch):
    journal = Journal()
    value = service(tmp_path, journal)
    value._prepared = True
    value.begin_request('original')
    monkeypatch.setattr(model_server, '_cancel_profile_request', lambda **kw: {'status': 'unverified'})
    assert not value.cancel_request('original')['computation_stopped']
    assert value._pending_request_id == 'original'
    assert journal.rows[-1][0] == 'model_request_started'
    monkeypatch.setattr(model_server, '_cancel_profile_request', lambda **kw: {'status': 'terminated'})
    journal.fail = 'model_request_finished'
    with pytest.raises(OSError):
        value.cancel_request('original')
    assert value._pending_request_id == 'original'
    journal.fail = None
    assert value.cancel_request('original')['computation_stopped']
    assert value._pending_request_id is None


def test_close_publication_failure_does_not_claim_closed(tmp_path):
    journal = Journal('model_closed')
    value = service(tmp_path, journal)
    with pytest.raises(OSError):
        value.close()
    assert not value._closed
    journal.fail = None
    assert value.close()['cleanup_verified'] is True
    assert value._closed


@pytest.mark.parametrize('journal_enabled', [False, True])
def test_coordinator_passes_journal_only_when_configured(tmp_path, monkeypatch, journal_enabled):
    from app.desktop_review import single_step_coordinator as module
    co = module.NativeSingleStepCoordinator.__new__(module.NativeSingleStepCoordinator)
    co._guard = RLock()
    co._keep_models_loaded = False
    co._resident_model_cleanup_pending = False
    co._resident_model_services = {}
    co._runtime_output_root = tmp_path
    co._cancel_wait = Event()
    journal = Journal() if journal_enabled else None
    co._resource_journal = journal
    calls = []
    def factory(configuration, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(prepare=lambda cancelled: None)
    monkeypatch.setattr(module, 'FormalModelService', factory)
    co._prepare_model_service_on_owner('configuration')
    assert ('resource_journal' in calls[0]) is journal_enabled
    if journal_enabled:
        assert calls[0]['resource_journal'] is journal


POLICY = {'kill_on_job_close': True, 'breakaway_ok': False,
          'silent_breakaway_ok': False, 'owner_handle_authority': 'registry_parent'}


def real_service(tmp_path):
    from app.execution.session_resources import SessionResourceJournal
    session = tmp_path/'session-fresh'
    session.mkdir()
    journal = SessionResourceJournal(session, recognition_source='local',
        host_identity={'pid': 123, 'created': 1.5},
        runner_identity={'pid': 124, 'create_time_ns': 1600000000})
    value = service(session/'runtime-output', journal)
    return value, journal


def saved_model(journal, value):
    from app.execution.session_resources import read_session_resources
    return read_session_resources(journal.session_dir)['resources'][value._resource_id]


def mock_owned(value, monkeypatch, *, launch_failure=False):
    members = [{'pid': 12345, 'create_time_ns': 444}]
    scope = SimpleNamespace(pids=lambda: [row['pid'] for row in members],
                           job_policy=lambda: dict(POLICY), close=lambda: None)
    monkeypatch.setattr(scopes, '_listeners', lambda ports: [])
    monkeypatch.setattr(scopes, 'scoped_process_launch_ready', lambda: True)
    monkeypatch.setattr(scopes, 'WindowsProcessScope', lambda *a, **k: scope)
    monkeypatch.setattr(scopes, '_identities_for_pids', lambda pids: [dict(row) for row in members if row['pid'] in pids])
    probes = iter([{'status': 'unreachable'}, {'status': 'running', 'model_id': 'test'},
                   {'status': 'running', 'model_id': 'test'}])
    monkeypatch.setattr(value, '_probe', lambda deadline: next(probes))
    monkeypatch.setattr(value, '_listener_identity', lambda: ((12345, 444),))
    def launch(*a, **kwargs):
        kwargs['before_resume'](dict(members[0]))
        if launch_failure:
            raise RuntimeError('synthetic launch failure')
        return {}
    monkeypatch.setattr(model_server, 'start_model_server', launch)
    monkeypatch.setattr(scopes, 'observe_process_scope_cleanup', lambda *a, **k: {
        'scope_name': value._scope_name, 'cleanup_status': 'verified'})
    return scope, members


def test_real_journal_owned_prepare_uses_native_four_field_policy(tmp_path, monkeypatch):
    value, journal = real_service(tmp_path)
    mock_owned(value, monkeypatch)
    assert value.prepare(Event())['ownership'] == 'owned'
    assert saved_model(journal, value)['policy'] == POLICY
    value.close()
    assert saved_model(journal, value)['closed_from_phase'] == 'ready'


def test_real_cancel_before_scope_preserves_cancelled_error_and_registered_origin(tmp_path):
    from app.vision.model_service import ModelServiceError
    value, journal = real_service(tmp_path)
    cancelled = Event()
    cancelled.set()
    with pytest.raises(ModelServiceError, match='model_service_cancelled'):
        value.prepare(cancelled)
    model = saved_model(journal, value)
    assert model['phase'] == 'closed' and model['closed_from_phase'] == 'registered'


def test_real_launch_failure_retains_original_launch_identity_after_cleanup(tmp_path, monkeypatch):
    from app.vision.model_service import ModelServiceError
    value, journal = real_service(tmp_path)
    mock_owned(value, monkeypatch, launch_failure=True)
    with pytest.raises(ModelServiceError) as caught:
        value.prepare(Event())
    assert caught.value.__cause__.args == ('synthetic launch failure',)
    model = saved_model(journal, value)
    assert model['closed_from_phase'] == 'launch_registered'
    assert model['member_identities'] == [{'pid': 12345, 'create_time_ns': 444}]


def test_real_cleanup_new_members_persist_before_effect_and_failure_retry(tmp_path, monkeypatch):
    import app.execution.session_resources as resources
    value, journal = real_service(tmp_path)
    scope, members = mock_owned(value, monkeypatch)
    value.prepare(Event())
    added = {'pid': 12346, 'create_time_ns': 555}
    members.append(added)
    calls = []
    def cleanup(*args, **kwargs):
        calls.append(kwargs)
        assert added in saved_model(journal, value)['cleanup_member_identities']
        assert added in kwargs['retained_process_identities']
        return {'scope_name': value._scope_name, 'cleanup_status': 'verified'}
    monkeypatch.setattr(scopes, 'observe_process_scope_cleanup', cleanup)
    original = resources.write_json_snapshot
    monkeypatch.setattr(resources, 'write_json_snapshot', lambda *a, **k: (_ for _ in ()).throw(OSError('disk unavailable')))
    with pytest.raises(Exception):
        value.close()
    assert not calls and value._scope is scope
    assert added in value._cleanup_member_identities.values()
    members.clear()
    monkeypatch.setattr(resources, 'write_json_snapshot', original)
    value.close()
    assert len(calls) == 1
    assert added in saved_model(journal, value)['cleanup_member_identities']


def test_real_retain_new_cleanup_evidence_survives_failed_publication(tmp_path, monkeypatch):
    import app.execution.session_resources as resources
    value, journal = real_service(tmp_path)
    mock_owned(value, monkeypatch)
    value.prepare(Event())
    added = {'pid': 12347, 'create_time_ns': 666}
    evidence = {'scope_name': value._scope_name, 'observed_member_identities_before': [added]}
    original = resources.write_json_snapshot
    monkeypatch.setattr(resources, 'write_json_snapshot', lambda *a, **k: (_ for _ in ()).throw(OSError('disk unavailable')))
    with pytest.raises(OSError):
        value._retain_cleanup_identities(evidence)
    assert added in value._cleanup_member_identities.values()
    monkeypatch.setattr(resources, 'write_json_snapshot', original)
    value._retain_cleanup_identities(evidence)
    assert added in saved_model(journal, value)['cleanup_member_identities']


def test_real_cleanup_observer_discovers_late_member_without_rewriting_launch_members(tmp_path, monkeypatch):
    value, journal = real_service(tmp_path)
    scope, members = mock_owned(value, monkeypatch)
    value.prepare(Event())
    launch_members = saved_model(journal, value)['member_identities']
    added = {'pid': 12348, 'create_time_ns': 777}
    monkeypatch.setattr(scopes, 'observe_process_scope_cleanup', lambda *a, **k: {
        'scope_name': value._scope_name, 'cleanup_status': 'verified',
        'observed_member_identities_before': [added]})
    value.close()
    model = saved_model(journal, value)
    assert model['member_identities'] == launch_members
    assert added in model['cleanup_member_identities']
    assert model['closed_from_phase'] == 'ready'
