"""驻留只保存模型 owner，不保留动作授权；所有进程与窗口均隔离。"""

from dataclasses import replace
import json
from threading import get_ident
from types import SimpleNamespace

import pytest

from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinatorError
from app.vision.model_service import freeze_model_service
from tests.test_formal_model_service import _configuration, backend
from tests.test_native_model_service import _coordinator, _prepare


def test_opt_in_is_lazy_and_default_still_releases(tmp_path, monkeypatch, backend):
    co, _, _ = _coordinator(tmp_path, monkeypatch)
    try:
        assert co.model_residency_settings() == {
            "keep_models_loaded": False, "allow_multiple_models": False,
            "resident_model_count": 0, "session_only": True,
        }
        assert co.set_keep_models_loaded(True)["keep_models_loaded"] is True
        assert backend.starts == backend.cleanups == []
        co.set_keep_models_loaded(False)
        _prepare(co)
        co.cancel()
        assert len(backend.cleanups) == 1
    finally:
        co.shutdown()


def test_three_steps_reuse_one_owned_model_but_clear_runtime(tmp_path, monkeypatch, backend):
    co, windows, calls = _coordinator(tmp_path, monkeypatch)
    threads = []
    backend.check_hook = lambda: threads.append(get_ident())
    try:
        co.set_keep_models_loaded(True)
        for _ in range(3):
            _prepare(co)
            result = co.cancel()
            assert result["cleanup_verified"] is True
            assert result["model_residency"]["resident_model_count"] == 1
            assert co._runtime is co._confirmation_id is co._model_service is None
        assert len(backend.starts) == 1
        assert backend.cleanups == []
        assert len({*threads, *(thread_id for _, thread_id in calls + windows.calls)}) == 1
        result = co.release_resident_models()
        assert result["resident_model_count"] == 0
        assert result["keep_models_loaded"] is True
        assert len(backend.cleanups) == 1
    finally:
        co.shutdown()


def test_disable_releases_residents_and_changes_only_after_verified(tmp_path, monkeypatch, backend):
    co, _, _ = _coordinator(tmp_path, monkeypatch)
    try:
        co.set_keep_models_loaded(True)
        _prepare(co)
        co.cancel()
        backend.cleanup_status = "indeterminate"
        with pytest.raises(NativeSingleStepCoordinatorError, match="cleanup"):
            co.set_keep_models_loaded(False)
        assert co.model_residency_settings()["keep_models_loaded"] is True
        assert co.model_residency_settings()["resident_model_count"] == 1
        with pytest.raises(NativeSingleStepCoordinatorError):
            _prepare(co)
        backend.cleanup_status = "verified"
        assert co.set_keep_models_loaded(False)["resident_model_count"] == 0
        assert co.model_residency_settings()["keep_models_loaded"] is False
    finally:
        backend.cleanup_status = "verified"
        co.shutdown()


def test_busy_and_pending_step_cannot_change_or_release_models(tmp_path, monkeypatch, backend):
    co, _, _ = _coordinator(tmp_path, monkeypatch)
    try:
        co.set_keep_models_loaded(True)
        _prepare(co)
        for operation in (lambda: co.set_keep_models_loaded(False), co.release_resident_models):
            with pytest.raises(NativeSingleStepCoordinatorError) as error:
                operation()
            assert error.value.code == "model_residency_change_unavailable"
        assert backend.cleanups == []
        co.cancel()
        co._busy = True
        with pytest.raises(NativeSingleStepCoordinatorError):
            co.release_resident_models()
    finally:
        co._busy = False
        co.shutdown()


def test_shutdown_closes_idle_resident_without_touching_external(tmp_path, monkeypatch, backend):
    co, _, _ = _coordinator(tmp_path, monkeypatch)
    co.set_keep_models_loaded(True)
    _prepare(co)
    co.cancel()
    co.shutdown()
    assert len(backend.cleanups) == 1
    assert all(scope.closed for scope in backend.scopes)
    assert co.model_residency_settings()["resident_model_count"] == 0


def test_external_service_not_adopted_into_resident_pool(tmp_path, monkeypatch, backend):
    co, _, _ = _coordinator(tmp_path, monkeypatch)
    backend.statuses = ["running"]
    try:
        co.set_keep_models_loaded(True)
        _prepare(co)
        co.cancel()
        assert co.model_residency_settings()["resident_model_count"] == 0
        assert backend.starts == backend.cleanups == []
    finally:
        co.shutdown()


def test_reused_service_drift_is_reported_not_silently_relaunched(tmp_path, monkeypatch, backend):
    co, _, calls = _coordinator(tmp_path, monkeypatch)
    try:
        co.set_keep_models_loaded(True)
        _prepare(co)
        co.cancel()
        before_factories = len(calls)
        backend.model_id = "wrong-model"
        with pytest.raises(NativeSingleStepCoordinatorError) as error:
            _prepare(co)
        assert error.value.code == "model_service_identity_mismatch"
        assert len(calls) == before_factories
        assert len(backend.starts) == 1
        co.cancel()
        assert co.model_residency_settings()["resident_model_count"] == 0
        assert len(backend.cleanups) == 1
    finally:
        co.shutdown()


@pytest.mark.parametrize("invalid", [1, "true", None])
def test_residency_requires_bool(tmp_path, monkeypatch, invalid):
    co, _, _ = _coordinator(tmp_path, monkeypatch)
    try:
        with pytest.raises(TypeError):
            co.set_keep_models_loaded(invalid)
    finally:
        co.shutdown()


def test_passive_goal_observations_reuse_model_but_not_packets(tmp_path, monkeypatch, backend):
    from app.agent import fresh_learning_factory
    from app.vision.request_control import current_model_request

    co, _, _ = _coordinator(tmp_path, monkeypatch)
    observations = []

    def observe(**kwargs):
        assert current_model_request() is not None
        observations.append(kwargs)
        return {"fresh_observation": len(observations)}

    monkeypatch.setattr(fresh_learning_factory, "create_fresh_learning_observation_owner",
                        lambda **kwargs: SimpleNamespace(observe=observe))
    try:
        co.set_keep_models_loaded(True)
        for index in range(3):
            packet = co.observe_learning_target_passively(application_identity={"kind": "web"},
                target_window_handle=4242, target_process_id=9001, goal="Read current screen")
            assert packet == {"fresh_observation": index + 1}
            assert co.learning_runtime_state()["phase"] == "idle"
        assert len(backend.starts) == 1
        assert backend.cleanups == []
        assert len(observations) == 3
    finally:
        co.shutdown()


def test_passive_failure_does_not_park_failed_active_service(tmp_path, monkeypatch, backend):
    from app.agent import fresh_learning_factory

    co, _, _ = _coordinator(tmp_path, monkeypatch)
    def fail(**kwargs):
        raise ValueError("synthetic capture failure")
    monkeypatch.setattr(fresh_learning_factory, "create_fresh_learning_observation_owner", fail)
    try:
        co.set_keep_models_loaded(True)
        with pytest.raises(NativeSingleStepCoordinatorError):
            co.observe_learning_target_passively(application_identity={"kind": "web"},
                target_window_handle=4242, target_process_id=9001, goal="Read current screen")
        assert co.model_residency_settings()["resident_model_count"] == 0
        assert len(backend.cleanups) == 1
    finally:
        co.shutdown()


def test_two_distinct_models_remain_owned_and_are_reused_independently(tmp_path, monkeypatch, backend):
    from app.core import model_server
    from app.learn.hybrid import windows_process_scope as scopes

    co, _, _ = _coordinator(tmp_path, monkeypatch)
    snapshot, _ = _configuration(tmp_path)
    first = freeze_model_service(snapshot)
    profile = first.profile()
    profile.update(profile_id="fixture-two", model_name="fixture-two-model", port=17322,
                   endpoint="http://127.0.0.1:17322/v1/chat/completions")
    second = replace(first, _profile_json=json.dumps(profile, sort_keys=True))
    running = {}
    original_cleanup = scopes.observe_process_scope_cleanup

    def launch(profile, **kwargs):
        pid = 4000 + profile["port"]
        running[profile["port"]] = (pid, profile["model_name"], kwargs["scope_name"])
        backend.scopes[-1].pids = lambda: [pid]
        backend.starts.append((profile, kwargs))
        return {"pid": pid}

    def cleanup(name, **kwargs):
        for port in [p for p, value in running.items() if value[2] == name]:
            del running[port]
        return original_cleanup(name, **kwargs)

    monkeypatch.setattr(model_server, "start_model_server", launch)
    monkeypatch.setattr(model_server, "check_model_server", lambda profile, **kwargs:
        {"status": "running", "model_id": running[profile["port"]][1]}
        if profile["port"] in running else {"status": "unreachable"})
    monkeypatch.setattr(scopes, "_listeners", lambda ports:
        [{"pid": running[p][0], "port": p} for p in ports if p in running])
    monkeypatch.setattr(scopes, "observe_process_scope_cleanup", cleanup)
    try:
        co.set_keep_models_loaded(True)
        for configuration in (first, second, first, second):
            co._owner.call(lambda: co._prepare_model_service_on_owner(configuration))
            co._release_model_service()
        assert len(backend.starts) == 2
        assert len(running) == 2
        assert co.model_residency_settings()["resident_model_count"] == 2
        assert backend.cleanups == []
        co.release_resident_models()
        assert running == {}
        assert len(backend.cleanups) == 2
    finally:
        co.shutdown()


def test_changed_weights_on_resident_port_cannot_be_accepted_as_external(tmp_path, monkeypatch, backend):
    co, _, _ = _coordinator(tmp_path, monkeypatch)
    snapshot, _ = _configuration(tmp_path)
    first = freeze_model_service(snapshot)
    profile = first.profile()
    profile["model_path"] = str(tmp_path / "different-weights")
    changed = replace(first, _profile_json=json.dumps(profile, sort_keys=True))
    try:
        co.set_keep_models_loaded(True)
        co._owner.call(lambda: co._prepare_model_service_on_owner(first))
        co._release_model_service()
        with pytest.raises(NativeSingleStepCoordinatorError) as error:
            co._owner.call(lambda: co._prepare_model_service_on_owner(changed))
        assert error.value.code == "model_service_resident_configuration_conflict"
        assert co._model_service is None
        assert co.model_residency_settings()["resident_model_count"] == 1
        assert len(backend.starts) == 1
        assert backend.cleanups == []
    finally:
        co.shutdown()


def test_partial_resident_cleanup_retries_only_unreleased_owner(tmp_path, monkeypatch):
    co, _, _ = _coordinator(tmp_path, monkeypatch)
    calls = []
    fail = [True]

    def close(name):
        calls.append((name, get_ident()))
        return {"cleanup_verified": not (name == "second" and fail[0])}

    try:
        co.set_keep_models_loaded(True)
        co._resident_model_services = {
            "first": SimpleNamespace(close=lambda: close("first")),
            "second": SimpleNamespace(close=lambda: close("second")),
        }
        with pytest.raises(NativeSingleStepCoordinatorError):
            co.release_resident_models()
        assert co.model_residency_settings()["resident_model_count"] == 1
        fail[0] = False
        assert co.release_resident_models()["resident_model_count"] == 0
        assert [name for name, _ in calls] == ["first", "second", "second"]
        assert len({thread_id for _, thread_id in calls}) == 1
    finally:
        fail[0] = False
        co.shutdown()
