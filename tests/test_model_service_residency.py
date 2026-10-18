"""驻留模型仅复用精确实例；所有进程与健康探测均为离线替身。"""

import json
from threading import Event
from types import SimpleNamespace

import pytest

from app.vision.model_service import FormalModelService, ModelServiceConfiguration, ModelServiceError, freeze_model_service
from tests.test_formal_model_service import _configuration, _owner, backend


def _grouped_owner(tmp_path, **kwargs):
    snapshot, path = _configuration(tmp_path)
    profile = json.loads(path.read_text(encoding="utf-8"))
    profile["exclusive_resource_group"] = "fixture-gpu"
    path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    return FormalModelService(freeze_model_service(snapshot), output_root=tmp_path / "output", **kwargs)


@pytest.mark.parametrize("value", [None, 0, 1, "true", [], {}])
def test_coexistence_option_requires_a_real_bool(tmp_path, value):
    with pytest.raises(ModelServiceError, match="model_service_config_invalid"):
        _owner(tmp_path, allow_resource_coexistence=value)


@pytest.mark.parametrize("kwargs", [{}, {"allow_resource_coexistence": False}])
def test_default_and_explicit_exclusive_mode_still_reject_group_conflicts(tmp_path, backend, kwargs):
    backend.conflicts = [{"profile_id": "other", "exclusive_resource_group": "fixture-gpu",
                          "endpoint": "http://127.0.0.1:17322/v1/chat/completions"}]
    with pytest.raises(ModelServiceError, match="model_service_resource_conflict"):
        _grouped_owner(tmp_path, **kwargs).prepare(Event())
    assert backend.starts == backend.scopes == backend.cleanups == []


def test_opt_in_skips_only_resource_group_discovery_and_starts_owned_job(tmp_path, monkeypatch, backend):
    from app.core import model_server

    monkeypatch.setattr(model_server, "load_model_profiles", lambda: pytest.fail("group probe forbidden"))
    owner = _grouped_owner(tmp_path, allow_resource_coexistence=True)
    assert owner.prepare(Event()) == {"status": "ready", "ownership": "owned"}
    assert len(backend.starts) == 1
    assert owner.close()["cleanup_verified"] is True
    assert len(backend.cleanups) == 1


def test_two_profiles_in_same_resource_group_retain_independent_ports_and_jobs(tmp_path, monkeypatch, backend):
    from app.core import model_server
    from app.learn.hybrid import windows_process_scope as scopes

    instances = {}
    owner = _grouped_owner(tmp_path, allow_resource_coexistence=True)
    second_profile = owner._configuration.profile()
    second_profile.update(profile_id="other", model_name="other-model", port=17322,
                          endpoint="http://127.0.0.1:17322/v1/chat/completions")
    other = FormalModelService(ModelServiceConfiguration(0.1, json.dumps(second_profile)),
                               output_root=tmp_path / "output", allow_resource_coexistence=True)

    class Scope:
        def __init__(self, name, *, create):
            assert create is True
            self.name, self.closed = name, False
            backend.scopes.append(self)

        def pids(self):
            return [item["pid"] for item in instances.values() if item["scope_name"] == self.name]

        def close(self):
            self.closed = True

    def launch(profile, **kwargs):
        backend.starts.append((profile, kwargs))
        instances[profile["port"]] = {"pid": 430 + len(backend.starts), "scope_name": kwargs["scope_name"],
                                      "model_id": profile["model_name"]}

    def check(profile, *, timeout):
        assert 0 < timeout <= 0.050001
        instance = instances.get(profile["port"])
        return {"status": "running" if instance else "unreachable",
                "model_id": instance["model_id"] if instance else None}

    def cleanup(name, **kwargs):
        backend.cleanups.append((name, kwargs))
        for port, instance in tuple(instances.items()):
            if instance["scope_name"] == name:
                instances.pop(port)
        return {"cleanup_status": "verified"}

    monkeypatch.setattr(scopes, "WindowsProcessScope", Scope)
    monkeypatch.setattr(scopes, "_listeners", lambda ports: [
        {"pid": instances[port]["pid"], "port": port} for port in ports if port in instances])
    monkeypatch.setattr(scopes, "observe_process_scope_cleanup", cleanup)
    monkeypatch.setattr(model_server, "start_model_server", launch)
    monkeypatch.setattr(model_server, "check_model_server", check)
    monkeypatch.setattr(model_server, "load_model_profiles", lambda: pytest.fail("group probe forbidden"))
    assert owner.prepare(Event())["ownership"] == other.prepare(Event())["ownership"] == "owned"
    assert owner.can_retain() is other.can_retain() is True
    assert owner._scope_name != other._scope_name and owner._instance_identity != other._instance_identity
    assert set(instances) == {17321, 17322}
    assert owner.reuse_ready(Event())["reused"] is other.reuse_ready(Event())["reused"] is True
    assert len(backend.starts) == 2 and backend.cleanups == []
    owner.close()
    assert set(instances) == {17322} and other.reuse_ready(Event())["reused"] is True
    other.close()
    assert not instances and len(backend.cleanups) == 2


@pytest.mark.parametrize("failure,expected", [
    ("endpoint", "model_service_endpoint_in_use"),
    ("model", "model_service_identity_mismatch"),
    ("owner", "model_service_owner_mismatch"),
    ("scope", "model_service_scope_unavailable"),
    ("resource", "model_service_prepare_failed"),
])
def test_coexistence_does_not_relax_endpoint_model_job_or_resource_failures(tmp_path, monkeypatch, backend,
                                                                         failure, expected):
    from app.learn.hybrid import windows_process_scope as scopes

    if failure == "endpoint":
        backend.listeners = [{"pid": 999, "port": 17321}]
    elif failure == "model":
        backend.statuses, backend.model_id = ["running"], "wrong-model"
    elif failure == "owner":
        backend.owned_listeners = False
    elif failure == "scope":
        monkeypatch.setattr(scopes, "scoped_process_launch_ready", lambda: False)
    else:
        backend.fail_start = True
    owner = _grouped_owner(tmp_path, allow_resource_coexistence=True)
    with pytest.raises(ModelServiceError, match=expected):
        owner.prepare(Event())
    if failure in {"owner", "resource"}:
        assert len(backend.cleanups) == 1 and backend.scopes[0].closed
    else:
        assert backend.starts == backend.scopes == backend.cleanups == []


def test_retainability_is_a_pure_state_query_across_request_lifecycle(tmp_path, monkeypatch, backend):
    owner = _owner(tmp_path)
    assert owner.can_retain() is False
    owner.prepare(Event())
    monkeypatch.setattr(owner, "_probe", lambda *args: pytest.fail("retainability performed health IO"))
    monkeypatch.setattr(owner, "_listener_identity", lambda: pytest.fail("retainability observed processes"))
    with monkeypatch.context() as guard:
        guard.setattr(owner._scope, "pids", lambda: pytest.fail("retainability queried the Job"))
        assert owner.can_retain() is True
        owner.begin_request("first")
        assert owner.can_retain() is False
        owner.complete_request("first")
        assert owner.can_retain() is True
    owner.close()
    assert owner.can_retain() is False


@pytest.mark.parametrize("field,value", [
    ("_ownership", "external"), ("_prepared", False), ("_closed", True),
    ("_pending_request_id", "pending"), ("_scope", None), ("_initialization_cleanup", object()),
])
def test_any_missing_retention_state_prevents_pool_admission(tmp_path, backend, field, value):
    owner = _owner(tmp_path)
    owner.prepare(Event())
    original = getattr(owner, field)
    try:
        setattr(owner, field, value)
        assert owner.can_retain() is False
    finally:
        setattr(owner, field, original)
        owner.close()


def test_same_owned_service_reuses_after_completed_requests_without_relaunch(tmp_path, backend):
    owner = _owner(tmp_path)
    owner.prepare(Event())
    identity, scope = owner._instance_identity, owner._scope
    for request_id in ("first", "second"):
        owner.begin_request(request_id)
        owner.complete_request(request_id)
        assert owner.reuse_ready(Event()) == {"status": "ready", "ownership": "owned", "reused": True}
        assert owner.can_retain() is True
        assert owner._instance_identity == identity and owner._scope is scope
    assert len(backend.starts) == len(backend.scopes) == 1
    assert backend.cleanups == []
    owner.close()


def test_external_service_may_be_revalidated_but_never_retained_or_adopted(tmp_path, backend):
    backend.statuses = ["running"]
    owner = _owner(tmp_path)
    owner.prepare(Event())
    assert owner.can_retain() is False
    assert owner.reuse_ready(Event()) == {"status": "ready", "ownership": "external", "reused": True}
    assert owner.can_retain() is False
    owner.close()
    assert backend.starts == backend.scopes == backend.cleanups == []


@pytest.mark.parametrize("phase", ["new", "closed", "pending", "identity_missing", "scope_missing",
                                   "initialization_cleanup", "ownership_missing"])
def test_invalid_reuse_phase_never_probes_or_cleans_owner(tmp_path, monkeypatch, backend, phase):
    owner = _owner(tmp_path)
    if phase != "new":
        owner.prepare(Event())
    scope, ownership = owner._scope, owner._ownership
    if phase == "closed":
        owner.close()
    elif phase == "pending":
        owner.begin_request("pending")
    elif phase == "identity_missing":
        owner._instance_identity = None
    elif phase == "scope_missing":
        owner._scope = None
    elif phase == "initialization_cleanup":
        owner._initialization_cleanup = object()
    elif phase == "ownership_missing":
        owner._ownership = "none"
    cleanup_count = len(backend.cleanups)
    monkeypatch.setattr(owner, "_probe", lambda *args: pytest.fail("invalid reuse performed health IO"))
    monkeypatch.setattr(owner, "_listener_identity", lambda: pytest.fail("invalid reuse observed processes"))
    expected = "model_service_request_pending" if phase == "pending" else "model_service_invalid_phase"
    with pytest.raises(ModelServiceError, match=expected) as error:
        owner.reuse_ready(Event())
    assert error.value.result_unknown is (phase == "pending")
    assert len(backend.cleanups) == cleanup_count
    if phase != "closed":
        owner._scope, owner._ownership = scope, ownership
    owner._initialization_cleanup = None
    owner.close()


@pytest.mark.parametrize("when", ["before", "during_probe", "after_probe"])
def test_reuse_cancellation_preserves_holder_for_coordinator_cleanup(tmp_path, monkeypatch, backend, when):
    owner = _owner(tmp_path)
    owner.prepare(Event())
    cancelled = Event()
    if when == "before":
        cancelled.set()
        monkeypatch.setattr(owner, "_probe", lambda *args: pytest.fail("cancelled reuse performed health IO"))
        monkeypatch.setattr(owner, "_listener_identity", lambda: pytest.fail("cancelled reuse observed processes"))
    elif when == "during_probe":
        backend.check_hook = cancelled.set
    else:
        observe = owner._listener_identity
        calls = []

        def identity():
            calls.append(True)
            result = observe()
            if len(calls) == 2:
                cancelled.set()
            return result

        monkeypatch.setattr(owner, "_listener_identity", identity)
    with pytest.raises(ModelServiceError, match="model_service_cancelled"):
        owner.reuse_ready(cancelled)
    assert not owner._closed and owner._ownership == "owned" and owner._scope is backend.scopes[0]
    assert len(backend.starts) == 1 and backend.cleanups == []
    owner.close()


@pytest.mark.parametrize("when", ["before", "during_probe"])
@pytest.mark.parametrize("coexist", [False, True])
def test_pid_reuse_with_different_creation_time_is_rejected_without_rebinding(tmp_path, monkeypatch, backend, when, coexist):
    from app.learn.hybrid import windows_process_scope as scopes

    owner = _owner(tmp_path, allow_resource_coexistence=coexist)
    owner.prepare(Event())
    original = owner._instance_identity
    created = [2000 if when == "before" else 1000]
    monkeypatch.setattr(scopes, "_identities_for_pids", lambda pids:
                        [{"pid": pid, "create_time_ns": created[0]} for pid in pids])
    if when == "before":
        backend.check_hook = lambda: pytest.fail("changed instance must fail before health IO")
    else:
        backend.check_hook = lambda: created.__setitem__(0, 2000)
    with pytest.raises(ModelServiceError, match="model_service_instance_changed"):
        owner.reuse_ready(Event())
    assert owner._instance_identity == original and owner._ownership == "owned"
    assert len(backend.starts) == 1 and backend.cleanups == []
    owner.close()


def test_reuse_rejects_listener_outside_retained_job(tmp_path, backend):
    owner = _owner(tmp_path)
    owner.prepare(Event())
    backend.owned_listeners = False
    with pytest.raises(ModelServiceError, match="model_service_owner_mismatch"):
        owner.reuse_ready(Event())
    assert backend.cleanups == [] and len(backend.starts) == 1
    owner.close()


@pytest.mark.parametrize("status", ["unreachable", "loading", "busy", "error"])
def test_reuse_requires_running_and_does_not_restart_unhealthy_service(tmp_path, backend, status):
    owner = _owner(tmp_path)
    owner.prepare(Event())
    backend.statuses = [status]
    with pytest.raises(ModelServiceError, match="model_service_not_ready"):
        owner.reuse_ready(Event())
    assert not owner._closed and owner._ownership == "owned"
    assert len(backend.starts) == 1 and backend.cleanups == []
    owner.close()


def test_reuse_requires_exact_model_identity(tmp_path, backend):
    owner = _owner(tmp_path)
    owner.prepare(Event())
    backend.model_id = "wrong-model"
    with pytest.raises(ModelServiceError, match="model_service_identity_mismatch"):
        owner.reuse_ready(Event())
    assert len(backend.starts) == 1 and backend.cleanups == []
    owner.close()


def test_reuse_health_error_is_explicit_and_preserves_cleanup_owner(tmp_path, backend):
    owner = _owner(tmp_path)
    owner.prepare(Event())

    def resource_error():
        raise OSError("private backend failure")

    backend.check_hook = resource_error
    with pytest.raises(ModelServiceError, match="model_service_reuse_failed") as error:
        owner.reuse_ready(Event())
    assert isinstance(error.value.__cause__, OSError)
    assert owner._scope is backend.scopes[0] and not owner._closed
    assert len(backend.starts) == 1 and backend.cleanups == []
    owner.close()


@pytest.mark.parametrize("late_at", ["before_probe", "during_probe", "after_probe"])
def test_reuse_deadline_includes_instance_validation_and_health(tmp_path, monkeypatch, backend, late_at):
    from app.vision import model_service

    owner = _owner(tmp_path)
    owner.prepare(Event())
    now = [0.0]
    monkeypatch.setattr(model_service, "time", SimpleNamespace(monotonic=lambda: now[0]))
    if late_at == "during_probe":
        backend.check_hook = lambda: now.__setitem__(0, 1.0)
    else:
        observe = owner._listener_identity
        calls = []

        def identity():
            calls.append(True)
            result = observe()
            if len(calls) == (1 if late_at == "before_probe" else 2):
                now[0] = 1.0
            return result

        monkeypatch.setattr(owner, "_listener_identity", identity)
    with pytest.raises(ModelServiceError, match="model_service_readiness_timeout"):
        owner.reuse_ready(Event())
    assert len(backend.starts) == 1 and backend.cleanups == []
    owner.close()


def test_reuse_health_uses_remaining_configuration_budget(tmp_path, monkeypatch, backend):
    from app.core import model_server
    from app.vision import model_service

    owner = _owner(tmp_path)
    owner.prepare(Event())
    now, budgets = [0.0], []
    monkeypatch.setattr(model_service, "time", SimpleNamespace(monotonic=lambda: now[0]))
    observe = owner._listener_identity

    def identity():
        result = observe()
        now[0] = 0.04
        return result

    monkeypatch.setattr(owner, "_listener_identity", identity)
    monkeypatch.setattr(model_server, "check_model_server", lambda profile, *, timeout:
                        budgets.append(timeout) or {"status": "running", "model_id": "fixture-model"})
    assert owner.reuse_ready(Event())["reused"] is True
    assert len(budgets) == 1 and 0 < budgets[0] <= 0.030001
    owner.close()
