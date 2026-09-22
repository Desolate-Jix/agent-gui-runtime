import json
from types import SimpleNamespace

import pytest

from app.learn.hybrid import windows_process_scope as scopes
from app.vision.model_service import FormalModelService, ModelServiceConfiguration, ModelServiceError


def delayed_scope(monkeypatch, survives_until):
    clock = {'now': 0.0, 'terminated': False}
    scope = SimpleNamespace(pids=lambda: [] if clock['terminated'] else [901],
        terminate=lambda: clock.update(terminated=True), close=lambda: None)
    monkeypatch.setattr(scopes, 'WindowsProcessScope', lambda *a, **k: scope)
    monkeypatch.setattr(scopes.time, 'monotonic', lambda: clock['now'])
    monkeypatch.setattr(scopes.time, 'sleep', lambda seconds: clock.update(now=clock['now'] + seconds))
    monkeypatch.setattr(scopes, '_listeners', lambda ports: [])
    monkeypatch.setattr(scopes, '_identities_for_pids', lambda pids: [
        {'pid': pid, 'create_time_ns': 100} for pid in pids if clock['now'] < survives_until])
    return clock


def test_wait_budget_covers_delayed_process_exit_without_lowering_zero_requirement(monkeypatch):
    clock = delayed_scope(monkeypatch, 1.6)
    result = scopes.observe_process_scope_cleanup('test', terminate=True,
        interval_seconds=.1, stable_zero_observations=3, timeout_seconds=3)
    assert result['cleanup_status'] == 'verified'
    assert result['stable_zero_observations'] == 3
    assert 1.8 <= clock['now'] < 3


def test_timeout_keeps_live_owned_identity(monkeypatch):
    clock = delayed_scope(monkeypatch, 100)
    result = scopes.observe_process_scope_cleanup('test', terminate=True,
        interval_seconds=.1, timeout_seconds=1)
    assert result['cleanup_status'] == 'indeterminate'
    assert result['remaining_owned_process_identities'] == [{'pid': 901, 'create_time_ns': 100}]
    assert clock['now'] <= 1.01


def test_pid_unlink_error_is_visible_and_never_treated_as_verified(monkeypatch, tmp_path):
    delayed_scope(monkeypatch, 0)
    pid = tmp_path / 'model.pid'
    pid.write_text('901', encoding='utf-8')
    monkeypatch.setattr(scopes.psutil, 'pid_exists', lambda pid: False)
    def denied(self, *args, **kwargs):
        raise PermissionError(13, 'SECRET NOT LOGGED')
    monkeypatch.setattr(type(pid), 'unlink', denied)
    result = scopes.observe_process_scope_cleanup('test', terminate=True,
        pid_file=pid, remove_owned_pid_file=True, interval_seconds=.1, include_diagnostics=True)
    assert result['cleanup_status'] == 'indeterminate'
    assert result['pid_file_cleanup']['reason'] == 'unlink_failed'
    assert result['pid_file_cleanup']['errno'] == 13
    assert 'SECRET' not in json.dumps(result)


def test_model_close_persists_diagnostic_evidence_and_keeps_retry_owner(monkeypatch, tmp_path):
    service = FormalModelService(ModelServiceConfiguration(1, json.dumps({'profile_id': 'vista'})), output_root=tmp_path)
    service._scope = SimpleNamespace(pids=lambda: [], close=lambda: None)
    service._ownership = 'owned'
    evidence = {'scope_name': service._scope_name, 'cleanup_status': 'indeterminate',
        'stable_zero_observations': 3, 'member_pids_after': [], 'remaining_owned_process_identities': [],
        'active_listeners_after': [], 'pid_file_after': str(service._pid_path),
        'pid_file_cleanup': {'reason': 'unlink_failed', 'errno': 13}, 'samples': []}
    monkeypatch.setattr(scopes, 'observe_process_scope_cleanup', lambda *a, **k: evidence)
    with pytest.raises(ModelServiceError) as caught:
        service.close()
    diagnostic = caught.value.diagnostics
    assert diagnostic['contract_version'] == 'model_service_cleanup_diagnostics_v1'
    assert diagnostic['evidence']['pid_file_cleanup']['reason'] == 'unlink_failed'
    assert service._scope is not None and not service._closed
    saved = json.loads((service._output_root / 'cleanup-evidence.json').read_text(encoding='utf-8'))
    assert saved['evidence'] == diagnostic['evidence']
    evidence['cleanup_status'] = 'verified'
    assert service.close()['cleanup_verified']
    assert service._scope is None


def test_coordinator_preserves_typed_cleanup_diagnostics():
    from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
    error = ModelServiceError('model_service_cleanup_pending')
    error.diagnostics = {'contract_version': 'model_service_cleanup_diagnostics_v1', 'evidence': {'pid_file_after': 'owned.pid'}}
    mapped = NativeSingleStepCoordinator._mapped(error, 'fallback', 'Pending')
    assert mapped.diagnostics == error.diagnostics
