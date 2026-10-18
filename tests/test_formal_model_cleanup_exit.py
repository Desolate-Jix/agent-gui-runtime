"""Job 清空不是进程退出；只跟踪终止前的确切身份，不处理复用 PID。"""
import json
from types import SimpleNamespace

import pytest

from app.learn.hybrid import windows_process_scope as scopes
from app.vision.model_service import FormalModelService, ModelServiceConfiguration, ModelServiceError


@pytest.fixture
def exiting_job(monkeypatch):
    state = SimpleNamespace(members=[431], identity=1000, terminated=0, identity_reads=[], rounds=0, exit_after=None, closed=[])

    class Scope:
        def __init__(self, name, *, create=False):
            self.name = name

        def pids(self):
            return list(state.members)

        def terminate(self):
            state.terminated += 1
            state.members.clear()

        def close(self):
            state.closed.append(self)

    def identities(pids):
        state.identity_reads.append((list(pids), state.terminated))
        if state.terminated and pids:
            state.rounds += 1
        if state.exit_after is not None and state.rounds >= state.exit_after:
            return []
        return [{"pid": pid, "create_time_ns": state.identity} for pid in pids]

    monkeypatch.setattr(scopes, "WindowsProcessScope", Scope)
    monkeypatch.setattr(scopes, "_identities_for_pids", identities)
    monkeypatch.setattr(scopes, "_listeners", lambda ports: [])
    monkeypatch.setattr(scopes.time, "sleep", lambda seconds: None)
    state.scope_type = Scope
    return state


def test_empty_job_does_not_prove_original_process_has_exited(exiting_job):
    result = scopes.observe_process_scope_cleanup("scope", terminate=True)
    assert result["cleanup_status"] == "indeterminate"
    assert result["remaining_owned_process_identities"] == [{"pid": 431, "create_time_ns": 1000}]
    assert exiting_job.identity_reads[0] == ([431], 0)


def test_cleanup_waits_for_exact_identity_to_disappear_then_stable_zero(exiting_job):
    exiting_job.exit_after = 4
    result = scopes.observe_process_scope_cleanup("scope", terminate=True)
    assert result["cleanup_status"] == "verified"
    assert exiting_job.rounds >= 6
    assert len(result["samples"]) >= 6
    assert result["remaining_owned_process_identities"] == []


def test_cleanup_does_not_wait_for_reused_pid_or_foreign_port(exiting_job, monkeypatch):
    original = scopes._identities_for_pids

    def identities(pids):
        if exiting_job.terminated:
            exiting_job.identity = 2000
        return original(pids)

    monkeypatch.setattr(scopes, "_identities_for_pids", identities)
    result = scopes.observe_process_scope_cleanup("scope", terminate=True, listener_ports=[])
    assert result["cleanup_status"] == "verified"
    assert result["observed_member_identities_before"] == [{"pid": 431, "create_time_ns": 1000}]
    assert exiting_job.terminated == 1


def test_owner_retains_original_identities_when_job_is_empty_on_cleanup_retry(tmp_path, exiting_job):
    owner = FormalModelService(ModelServiceConfiguration(1, json.dumps({"profile_id": "fixture", "port": 17321})), output_root=tmp_path)
    original_scope = exiting_job.scope_type("scope")
    owner._scope = original_scope
    owner._ownership = "owned"
    with pytest.raises(ModelServiceError, match="model_service_cleanup_pending"):
        owner.close()
    assert original_scope not in exiting_job.closed
    with pytest.raises(ModelServiceError, match="model_service_cleanup_pending"):
        owner.close()
    assert original_scope not in exiting_job.closed
    exiting_job.exit_after = 0
    assert owner.close() == {"cleanup_verified": True, "ownership": "owned"}
    assert original_scope in exiting_job.closed
    assert exiting_job.terminated == 1


def test_unobservable_owned_identity_never_terminates_or_claims_cleanup(exiting_job, monkeypatch):
    def unobservable(pids):
        raise scopes.HybridProcessScopeError("identity unavailable")

    monkeypatch.setattr(scopes, "_identities_for_pids", unobservable)
    result = scopes.observe_process_scope_cleanup("scope", terminate=True)
    assert result["cleanup_status"] == "indeterminate"
    assert exiting_job.terminated == 0


def test_owner_retains_members_first_seen_inside_cleanup_helper(tmp_path, exiting_job, monkeypatch):
    owner = FormalModelService(ModelServiceConfiguration(1, json.dumps({"profile_id": "fixture", "port": 17321})), output_root=tmp_path)
    outer = exiting_job.scope_type(owner._scope_name)
    owner._scope, owner._ownership = outer, "owned"

    def caller_snapshot():
        members = list(exiting_job.members)
        if 431 in members and 432 not in members:
            exiting_job.members.append(432)
        return members

    def identities(pids):
        return [{"pid": pid, "create_time_ns": 1000} for pid in pids
                if exiting_job.exit_after != 0 and (not exiting_job.terminated or pid == 432)]

    monkeypatch.setattr(outer, "pids", caller_snapshot)
    monkeypatch.setattr(scopes, "_identities_for_pids", identities)
    with pytest.raises(ModelServiceError, match="model_service_cleanup_pending"):
        owner.close()
    with pytest.raises(ModelServiceError, match="model_service_cleanup_pending"):
        owner.close()
    exiting_job.exit_after = 0
    assert owner.close()["cleanup_verified"] is True


def test_sampling_error_preserves_pretermination_identities(exiting_job, monkeypatch):
    original = scopes._identities_for_pids

    def unreadable_after_termination(pids):
        if exiting_job.terminated:
            raise scopes.HybridProcessScopeError("observation unavailable")
        return original(pids)

    monkeypatch.setattr(scopes, "_identities_for_pids", unreadable_after_termination)
    result = scopes.observe_process_scope_cleanup("scope", terminate=True)
    assert result["cleanup_status"] == "indeterminate"
    assert result["observed_member_identities_before"] == [{"pid": 431, "create_time_ns": 1000}]


def test_launch_cleanup_error_carries_scope_identities(tmp_path, monkeypatch):
    from app.core import model_server

    proof = {"scope_name": "scope", "cleanup_status": "indeterminate",
             "observed_member_identities_before": [{"pid": 432, "create_time_ns": 1000}]}
    process = SimpleNamespace(pid=432, poll=lambda: 1, close=lambda: None)
    monkeypatch.setattr(scopes, "spawn_process_in_scope", lambda *a, **k: process)
    monkeypatch.setattr(scopes, "observe_process_scope_cleanup", lambda *a, **k: proof)
    monkeypatch.setattr(model_server.time, "sleep", lambda seconds: None)
    with pytest.raises(model_server.HybridModelLaunchCleanupError) as captured:
        model_server._launch_model_server_process(profile={"pid_file": str(tmp_path / "model.pid")},
            log_path=tmp_path / "model.log", command=["fixture-not-executable"], scope_name="scope")
    assert captured.value.cleanup_evidence["scope_cleanup_evidence"] == proof


def test_prepare_retains_lower_launcher_cleanup_identities(tmp_path, exiting_job, monkeypatch):
    from threading import Event
    from app.core import model_server

    owner = FormalModelService(ModelServiceConfiguration(1, json.dumps({"profile_id": "fixture", "port": 17321})), output_root=tmp_path)

    def failed_start(*args, **kwargs):
        exiting_job.members.clear()
        raise model_server.HybridModelLaunchCleanupError({"scope_cleanup_evidence": {
            "scope_name": owner._scope_name, "cleanup_status": "indeterminate",
            "observed_member_identities_before": [{"pid": 432, "create_time_ns": 1000}]}})

    monkeypatch.setattr(model_server, "check_model_server", lambda *a, **k: {"status": "unreachable"})
    monkeypatch.setattr(model_server, "start_model_server", failed_start)
    monkeypatch.setattr(scopes, "scoped_process_launch_ready", lambda: True)
    with pytest.raises(ModelServiceError, match="model_service_cleanup_pending"):
        owner.prepare(Event())
    with pytest.raises(ModelServiceError, match="model_service_cleanup_pending"):
        owner.close()
    exiting_job.exit_after = 0
    assert owner.close()["cleanup_verified"] is True
