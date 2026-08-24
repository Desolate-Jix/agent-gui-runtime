from __future__ import annotations

import json
import base64
import socket
import urllib.error
from copy import deepcopy

import pytest

from app.core import model_server
from app.learn.recognition.uei.canonical import seal_immutable


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        raw = json.dumps(self._payload).encode("utf-8")
        return raw if size < 0 else raw[:size]


def _valid_binding_artifacts() -> tuple[dict, dict]:
    from app.learn.hybrid.qwen_binding import parse_qwen_candidate_bindings
    from tests.test_learn_hybrid_contracts import inventory_fixture

    inventory = seal_immutable(inventory_fixture())
    candidate_id = inventory["candidates"][0]["candidate_id"]
    parsed = parse_qwen_candidate_bindings(
        {
            "bindings": [{
                "candidate_id": candidate_id,
                "role": "button",
                "label": "申请职位",
                "description": "打开申请流程",
                "semantic_confidence": 0.94,
                "task_relevance": 0.88,
                "relation": "primary_action",
                "ambiguity": None,
            }],
            "orphan_semantics": [],
        },
        inventory,
    )
    return inventory, seal_immutable(parsed)


def test_cancel_model_request_verifies_vista_request_termination(monkeypatch) -> None:
    requested: list[dict] = []
    profile = {
        "profile_id": "vista",
        "role": ["grounding", "locate"],
        "endpoint": "http://127.0.0.1:13244/v1/chat/completions",
        "request_cancel_supported": True,
        "request_cancel_endpoint": "http://127.0.0.1:13244/v1/cancel",
    }
    monkeypatch.setattr(model_server, "load_model_profiles", lambda: [profile])

    def fake_urlopen(request, timeout):
        requested.append(
            {
                "url": request.full_url,
                "body": json.loads(request.data.decode("utf-8")),
                "timeout": timeout,
            }
        )
        return _FakeResponse(
            {
                "contract_version": "model_request_cancel_response_v1",
                "status": "cancellation_acknowledged",
                "request_id": "learn-worker-123",
            }
        )

    monkeypatch.setattr(model_server.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(
        model_server,
        "check_model_server",
        lambda profile, timeout=1.0: {
            "status": "running",
            "health": {"status": "ok", "active_request": None},
        },
    )

    result = model_server.cancel_model_request(
        request_id="learn-worker-123",
        task_kind="vision_locate_target",
        payload={"provider_mode": "local_grounding"},
    )

    assert requested == [
        {
            "url": "http://127.0.0.1:13244/v1/cancel",
            "body": {"request_id": "learn-worker-123"},
            "timeout": 1.0,
        }
    ]
    assert result["status"] == "terminated"
    assert result["model_service_compute_termination"] == "terminated"
    assert result["provider_results"][0]["profile_id"] == "vista"


def test_cancel_model_request_reports_unsupported_without_guessing(monkeypatch) -> None:
    monkeypatch.setattr(model_server, "load_model_profiles", lambda: [])

    result = model_server.cancel_model_request(
        request_id="learn-worker-456",
        task_kind="panel_learning_model_review_repair",
        payload={},
    )

    assert result["status"] == "not_supported"
    assert result["model_service_compute_termination"] == "not_supported"
    assert result["provider_results"] == []


def test_calibration_sequence_cancellation_uses_nested_locate_payload(
    monkeypatch,
) -> None:
    profile = {
        "profile_id": "vista",
        "role": ["grounding", "locate"],
        "request_cancel_supported": True,
        "request_cancel_endpoint": "http://127.0.0.1:13244/v1/cancel",
    }
    monkeypatch.setattr(model_server, "load_model_profiles", lambda: [profile])

    profiles = model_server._request_cancel_profiles(
        task_kind="panel_learning_calibration_sequence",
        payload={
            "contract_version": "learning_calibration_sequence_request_v1",
            "locate_payload": {"provider_mode": "local_grounding"},
        },
    )

    assert profiles == [profile]


def test_qwen_cancellation_uses_exact_request_endpoint_and_retains_other_operation(
    tmp_path,
    monkeypatch,
) -> None:
    profile = {
        "profile_id": "qwen3_vl_8b_q4_k_m",
        "role": ["understanding", "learning"],
        "provider_mode": "local_understanding",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
        "request_cancel_supported": True,
        "request_cancel_endpoint": "http://127.0.0.1:13240/v1/cancel",
    }
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease_a = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="learn-qwen-a",
        readiness={"started": True, "after": {"status": "running", "model_id": "qwen"}},
    )
    lease_b = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="learn-qwen-b",
        readiness={"started": False, "before": {"status": "running", "model_id": "qwen"}},
    )
    changed_profile = {**profile, "request_cancel_endpoint": "http://127.0.0.1:13240/v1/should-not-use"}
    monkeypatch.setattr(model_server, "profile_for_stage", lambda stage, profile_id=None: changed_profile)
    requested: list[dict] = []

    def fake_urlopen(request, timeout):
        requested.append({"url": request.full_url, "body": json.loads(request.data), "timeout": timeout})
        return _FakeResponse({
            "contract_version": "model_request_cancel_response_v1",
            "status": "cancellation_acknowledged",
            "request_id": "learn-qwen-a",
        })

    monkeypatch.setattr(model_server.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(model_server, "check_model_server", lambda selected, timeout=1.0: {
        "status": "running",
        "base_url": "http://127.0.0.1:13240/v1",
        "model_id": "qwen",
        "health": {"status": "ok", "active_request": {"request_id": "learn-qwen-b"}},
    })
    monkeypatch.setattr(model_server, "stop_model_server", lambda selected: pytest.fail("shared server stopped"))

    result = model_server.cancel_model_request(
        request_id="learn-qwen-a",
        task_kind="panel_learning_hybrid_qwen_binding",
        payload={},
    )

    assert result["status"] == "terminated"
    assert requested == [{
        "url": profile["request_cancel_endpoint"],
        "body": {"request_id": "learn-qwen-a"},
        "timeout": 1.0,
    }]
    assert result["provider_results"][0]["lease"]["lease_id"] == lease_a["lease_id"]
    assert result["provider_results"][0]["shared_server_retained"] is True
    assert model_server.qwen_model_lease_is_active(lease_b) is True
    assert model_server.qwen_model_lease_is_active(lease_a) is False


def test_qwen_release_refcounts_and_stops_only_after_last_runtime_owned_lease(
    tmp_path,
    monkeypatch,
) -> None:
    inventory, artifact = _valid_binding_artifacts()
    stopped: list[dict] = []
    profile = {"profile_id": "qwen3_vl_8b_q4_k_m", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease_a = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="request-a",
        readiness={"started": True, "after": {"status": "running", "model_id": "qwen"}},
    )
    lease_b = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="request-b",
        readiness={"started": False, "before": {"status": "running", "model_id": "qwen"}},
    )
    monkeypatch.setattr(
        model_server,
        "stop_model_server",
        lambda selected: stopped.append(selected) or {"stopped": True, "after": {"status": "unreachable"}},
    )
    monkeypatch.setattr(model_server, "check_model_server", lambda selected, timeout=1.0: {"status": "unreachable"})

    first = model_server.release_qwen_model_server(
        sealed_artifact=artifact,
        omni_inventory=inventory,
        model_lease=lease_a,
    )
    assert first["status"] == "released"
    assert first["shared_server_retained"] is True
    assert stopped == []
    assert model_server.qwen_model_lease_is_active(lease_b) is True

    second = model_server.release_qwen_model_server(
        sealed_artifact=artifact,
        omni_inventory=inventory,
        model_lease=lease_b,
    )
    assert second["status"] == "released"
    assert second["server_termination"] == "verified_stopped"
    assert stopped == [profile]


def test_qwen_last_request_cancel_stops_owned_server_then_new_external_lease_is_retained(
    tmp_path,
    monkeypatch,
) -> None:
    inventory, artifact = _valid_binding_artifacts()
    profile = {
        "profile_id": "qwen3_vl_8b_q4_k_m",
        "role": ["understanding"],
        "provider_mode": "local_understanding",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
        "request_cancel_supported": True,
        "request_cancel_endpoint": "http://127.0.0.1:13240/v1/cancel",
    }
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    monkeypatch.setattr(model_server, "profile_for_stage", lambda stage, profile_id=None: profile)
    first = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="owned-request",
        readiness={"started": True, "after": {"status": "running", "model_id": "qwen"}},
    )
    stopped: list[dict] = []
    monkeypatch.setattr(model_server.urllib.request, "urlopen", lambda request, timeout: _FakeResponse({
        "status": "cancellation_acknowledged",
        "request_id": "owned-request",
    }))
    monkeypatch.setattr(model_server, "stop_model_server", lambda selected: stopped.append(selected) or {"stopped": True})
    monkeypatch.setattr(model_server, "check_model_server", lambda selected, timeout=1.0: {
        "status": "unreachable",
        "health": {"active_request": None},
    })

    cancelled = model_server.cancel_model_request(
        request_id="owned-request",
        task_kind="panel_learning_hybrid_qwen_binding",
        payload={},
    )
    assert cancelled["status"] == "terminated"
    assert cancelled["provider_results"][0]["server_termination"] == "verified_stopped"
    assert stopped == [profile]
    assert model_server.qwen_model_lease_is_active(first) is False

    external = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="external-request",
        readiness={"started": False, "before": {"status": "running", "model_id": "qwen"}},
    )
    stopped.clear()
    released = model_server.release_qwen_model_server(
        sealed_artifact=artifact,
        omni_inventory=inventory,
        model_lease=external,
    )
    assert released["server_termination"] == "not_owned"
    assert stopped == []


def test_qwen_release_rejects_forged_or_wrong_capture_artifact(
    tmp_path,
    monkeypatch,
) -> None:
    inventory, artifact = _valid_binding_artifacts()
    profile = {"profile_id": "qwen3_vl_8b_q4_k_m", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="request-a",
        readiness={"started": False, "before": {"status": "running", "model_id": "qwen"}},
    )

    with pytest.raises(ValueError, match="sealed Qwen binding"):
        model_server.release_qwen_model_server(
            sealed_artifact=seal_immutable({"contract_version": "hybrid_qwen_bindings_v1"}),
            omni_inventory=inventory,
            model_lease=lease,
        )

    omitted = seal_immutable({
        **{key: deepcopy(value) for key, value in artifact.items() if key != "content_sha256"},
        "bindings": [],
    })
    with pytest.raises(ValueError, match="coverage|sealed Qwen binding"):
        model_server.release_qwen_model_server(
            sealed_artifact=omitted,
            omni_inventory=inventory,
            model_lease=lease,
        )

    wrong_inventory = seal_immutable({
        **{key: value for key, value in inventory.items() if key != "content_sha256"},
        "capture_identity": {**inventory["capture_identity"], "screenshot_sha256": "0" * 64},
    })
    with pytest.raises(ValueError, match="capture|screenshot|sealed Qwen binding"):
        model_server.release_qwen_model_server(
            sealed_artifact=artifact,
            omni_inventory=wrong_inventory,
            model_lease=lease,
        )


def test_qwen_stop_script_success_but_server_running_is_not_released(
    tmp_path,
    monkeypatch,
) -> None:
    inventory, artifact = _valid_binding_artifacts()
    profile = {"profile_id": "qwen3_vl_8b_q4_k_m", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="request-a",
        readiness={"started": True, "after": {"status": "running", "model_id": "qwen"}},
    )
    monkeypatch.setattr(model_server, "stop_model_server", lambda selected: {"stopped": True})
    monkeypatch.setattr(model_server, "check_model_server", lambda selected, timeout=1.0: {"status": "running", "model_id": "qwen"})

    with pytest.raises(RuntimeError, match="still running"):
        model_server.release_qwen_model_server(
            sealed_artifact=artifact,
            omni_inventory=inventory,
            model_lease=lease,
        )
    assert model_server.qwen_model_lease_is_active(lease) is True


def test_qwen_binding_runner_reuses_understanding_endpoint_and_request_id(
    tmp_path,
    monkeypatch,
) -> None:
    profile = {
        "profile_id": "qwen3_vl_8b_q4_k_m",
        "model_name": "Qwen3VL-8B-Instruct-Q4_K_M.gguf",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
    }
    seen: dict = {}
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path)
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="learn-qwen-request",
        readiness={"started": False, "before": {"status": "running", "model_id": profile["model_name"]}},
    )
    changed_profile = {**profile, "endpoint": "http://127.0.0.1:13240/v1/should-not-use"}
    monkeypatch.setattr(model_server, "profile_for_stage", lambda stage: changed_profile)
    monkeypatch.setenv("AGENT_GUI_MODEL_REQUEST_ID", "learn-qwen-request")
    screenshot_bytes = b"controlled-task2-image-bytes"

    def fake_urlopen(request, timeout):
        seen.update(
            url=request.full_url,
            headers=dict(request.headers),
            body=json.loads(request.data.decode("utf-8")),
            timeout=timeout,
        )
        return _FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {"bindings": [], "orphan_semantics": []},
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(model_server.urllib.request, "urlopen", fake_urlopen)
    result = model_server.run_qwen_binding_model(
        request={"label": "申请职位"},
        screenshot_bytes=screenshot_bytes,
        screenshot_media_type="image/png",
        screenshot_sha256=__import__("hashlib").sha256(screenshot_bytes).hexdigest(),
        model_lease=lease,
        timeout_seconds=3.0,
    )

    assert result == {"bindings": [], "orphan_semantics": []}
    assert seen["url"] == profile["endpoint"]
    assert seen["timeout"] == 3.0
    assert seen["body"]["request_id"] == "learn-qwen-request"
    assert seen["body"]["model"] == profile["model_name"]
    assert "申请职位" in seen["body"]["messages"][1]["content"][0]["text"]
    image_url = seen["body"]["messages"][1]["content"][1]["image_url"]["url"]
    assert base64.b64decode(image_url.split(",", 1)[1]) == screenshot_bytes


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("direct timeout"),
        socket.timeout("socket timeout"),
        urllib.error.URLError(socket.timeout("wrapped timeout")),
    ],
)
def test_qwen_binding_runner_normalizes_timeout_types(monkeypatch, error) -> None:
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "profile_for_stage", lambda stage: profile)
    monkeypatch.setattr(model_server.urllib.request, "urlopen", lambda *args, **kwargs: (_ for _ in ()).throw(error))

    with pytest.raises(model_server.QwenModelRequestTimeout):
        model_server.run_qwen_binding_model(
            request={},
            screenshot_bytes=b"same-bytes",
            screenshot_media_type="image/png",
            screenshot_sha256=__import__("hashlib").sha256(b"same-bytes").hexdigest(),
            timeout_seconds=0.1,
        )


def test_qwen_binding_runner_rejects_oversized_http_body(monkeypatch) -> None:
    profile = {"profile_id": "qwen", "endpoint": "http://127.0.0.1:13240/v1/chat/completions"}
    monkeypatch.setattr(model_server, "profile_for_stage", lambda stage: profile)

    class OversizedResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, size=-1):
            return b"x" * size

    monkeypatch.setattr(model_server.urllib.request, "urlopen", lambda *args, **kwargs: OversizedResponse())
    with pytest.raises(ValueError, match="response byte limit"):
        model_server.run_qwen_binding_model(
            request={},
            screenshot_bytes=b"same-bytes",
            screenshot_media_type="image/png",
            screenshot_sha256=__import__("hashlib").sha256(b"same-bytes").hexdigest(),
        )
