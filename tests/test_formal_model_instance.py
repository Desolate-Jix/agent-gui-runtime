"""就绪实例与请求实际端点的绑定；进程查询使用隔离边界。"""

from threading import Event

import pytest

from app.vision.model_service import ModelServiceError
from tests.test_formal_model_service import _owner, backend


def test_request_accepts_only_ready_endpoint_model_and_instance(tmp_path, backend):
    owner = _owner(tmp_path)
    owner.prepare(Event())
    try:
        owner.verify_request_instance(owner._profile["endpoint"], "fixture-model")
        for endpoint, model in (("http://127.0.0.1:7/v1/chat/completions", "fixture-model"),
                                (owner._profile["endpoint"], "different")):
            with pytest.raises(ModelServiceError, match="model_service_request_mismatch"):
                owner.verify_request_instance(endpoint, model)
    finally:
        owner.close()


@pytest.mark.parametrize("change", ["pid", "creation", "missing", "membership"])
def test_request_rejects_replacement_or_unobservable_instance(tmp_path, monkeypatch, backend, change):
    from app.learn.hybrid import windows_process_scope as scopes

    owner = _owner(tmp_path)
    owner.prepare(Event())
    if change == "pid":
        backend.owned_listeners = False
    elif change == "creation":
        monkeypatch.setattr(scopes, "_identities_for_pids", lambda pids: [{"pid": 431, "create_time_ns": 9}])
    elif change == "missing":
        monkeypatch.setattr(scopes, "_identities_for_pids", lambda pids: [])
    else:
        backend.members = []
    try:
        with pytest.raises(ModelServiceError):
            owner.verify_request_instance(owner._profile["endpoint"], "fixture-model")
        assert backend.cleanups == []
    finally:
        owner.close()


def test_external_instance_replacement_is_rejected_without_stopping_it(tmp_path, monkeypatch, backend):
    from app.learn.hybrid import windows_process_scope as scopes

    backend.statuses = ["running"]
    owner = _owner(tmp_path)
    owner.prepare(Event())
    monkeypatch.setattr(scopes, "_identities_for_pids", lambda pids: [{"pid": 431, "create_time_ns": 9}])
    with pytest.raises(ModelServiceError, match="model_service_instance_changed"):
        owner.verify_request_instance(owner._profile["endpoint"], "fixture-model")
    owner.close()
    assert backend.starts == backend.cleanups == []


def test_instance_cannot_be_used_after_owner_closes(tmp_path, backend):
    owner = _owner(tmp_path)
    owner.prepare(Event())
    owner.close()
    with pytest.raises(ModelServiceError, match="model_service_invalid_phase"):
        owner.verify_request_instance(owner._profile["endpoint"], "fixture-model")


def test_ready_health_must_be_bracketed_by_same_instance(tmp_path, monkeypatch, backend):
    from app.learn.hybrid import windows_process_scope as scopes

    backend.statuses = ["running"]
    generation = [1000]
    probes = []

    def health_hook():
        probes.append(1)
        if len(probes) == 2:
            generation[0] = 2000

    backend.check_hook = health_hook
    monkeypatch.setattr(scopes, "_identities_for_pids", lambda pids:
                        [{"pid": pid, "create_time_ns": generation[0]} for pid in pids])
    owner = _owner(tmp_path)
    try:
        with pytest.raises(ModelServiceError, match="model_service_instance_changed"):
            owner.prepare(Event())
    finally:
        owner.close()
    assert backend.starts == backend.cleanups == []
