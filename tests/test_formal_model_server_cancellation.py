"""正式模型拥有者只取消自己登记的请求，并保留未核验的结果。"""

import json
from threading import Event

import pytest

from app.vision.model_service import ModelServiceError, FormalModelService, freeze_model_service
from tests.test_formal_model_service import _configuration, _owner, backend


def test_unknown_request_blocks_next_request_until_owned_cleanup(tmp_path, backend):
    owner = _owner(tmp_path)
    owner.prepare(Event())
    owner.begin_request("request-1")
    with pytest.raises(ModelServiceError, match="model_service_request_pending"):
        owner.begin_request("request-2")
    proof = owner.cancel_request("request-1")
    assert proof["computation_stopped"] is False and proof["status"] == "unsupported"
    assert backend.cleanups == []
    assert owner.close()["cleanup_verified"] is True


def test_successful_request_clears_only_its_own_pending_identity(tmp_path, backend):
    owner = _owner(tmp_path)
    owner.prepare(Event())
    try:
        owner.begin_request("request-1")
        with pytest.raises(ModelServiceError, match="model_service_request_mismatch"):
            owner.complete_request("different")
        owner.complete_request("request-1")
        owner.begin_request("request-2")
    finally:
        owner.close()


def test_external_unknown_computation_is_not_reported_as_cleaned(tmp_path, backend):
    backend.statuses = ["running"]
    owner = _owner(tmp_path)
    owner.prepare(Event())
    owner.begin_request("request-1")
    with pytest.raises(ModelServiceError, match="model_service_compute_pending"):
        owner.close()
    assert not owner._closed and backend.cleanups == []


@pytest.mark.parametrize("cancel_endpoint", ["http://127.0.0.1:7/cancel", "http://example.invalid/cancel"])
def test_cancel_endpoint_must_belong_to_frozen_inference_service(tmp_path, cancel_endpoint):
    snapshot, path = _configuration(tmp_path)
    profile = json.loads(path.read_text(encoding="utf-8"))
    profile.update(request_cancel_supported=True, request_cancel_endpoint=cancel_endpoint)
    path.write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ModelServiceError, match="model_service_cancel_endpoint_mismatch"):
        freeze_model_service(snapshot)


def test_scope_cancellation_attaches_server_proof_without_resetting_event():
    from app.vision.request_control import ModelRequestContext, ModelRequestError

    event = Event()
    calls = []
    context = ModelRequestContext(event,
        on_started=lambda rid: calls.append(("start", rid)),
        on_cancelled=lambda rid: {"request_id": rid, "status": "terminated", "computation_stopped": True})
    with pytest.raises(ModelRequestError) as error:
        with context.request_scope("request-1"):
            event.set()
            context.check_cancelled()
    assert calls == [("start", "request-1")]
    assert event.is_set()
    assert error.value.computation_stopped is True and error.value.request_id == "request-1"
