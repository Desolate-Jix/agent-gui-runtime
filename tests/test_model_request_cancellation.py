from __future__ import annotations

import json

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

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


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


def test_qwen_binding_cancellation_releases_existing_qwen_server(monkeypatch) -> None:
    profile = {
        "profile_id": "qwen3_vl_8b_q4_k_m",
        "role": ["understanding", "learning"],
        "provider_mode": "local_understanding",
    }
    stopped: list[dict] = []
    monkeypatch.setattr(model_server, "load_model_profiles", lambda: [profile])
    monkeypatch.setattr(
        model_server,
        "stop_model_server",
        lambda selected: stopped.append(selected) or {"stopped": True},
    )

    result = model_server.cancel_model_request(
        request_id="learn-qwen-123",
        task_kind="panel_learning_hybrid_qwen_binding",
        payload={},
    )

    assert result["status"] == "terminated"
    assert result["model_service_compute_termination"] == "terminated"
    assert result["provider_results"] == [
        {
            "profile_id": "qwen3_vl_8b_q4_k_m",
            "status": "terminated",
            "model_service_compute_termination": "terminated",
            "release": {"stopped": True},
        }
    ]
    assert stopped == [profile]


def test_qwen_release_requires_sealed_binding_before_stopping(monkeypatch) -> None:
    stopped: list[dict] = []
    profile = {"profile_id": "qwen3_vl_8b_q4_k_m"}
    monkeypatch.setattr(model_server, "profile_for_stage", lambda stage: profile)
    monkeypatch.setattr(
        model_server,
        "stop_model_server",
        lambda selected: stopped.append(selected) or {"stopped": True},
    )

    with pytest.raises(ValueError, match="sealed Qwen binding"):
        model_server.release_qwen_model_server(
            sealed_artifact={"contract_version": "hybrid_qwen_bindings_v1"}
        )
    assert stopped == []

    artifact = seal_immutable({"contract_version": "hybrid_qwen_bindings_v1"})
    result = model_server.release_qwen_model_server(sealed_artifact=artifact)
    assert result["stopped"] is True
    assert stopped == [profile]


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
    image = tmp_path / "capture.png"
    image.write_bytes(b"controlled-image")
    monkeypatch.setattr(model_server, "profile_for_stage", lambda stage: profile)
    monkeypatch.setenv("AGENT_GUI_MODEL_REQUEST_ID", "learn-qwen-request")

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
        image_path=image,
        timeout_seconds=3.0,
    )

    assert result == {"bindings": [], "orphan_semantics": []}
    assert seen["url"] == profile["endpoint"]
    assert seen["timeout"] == 3.0
    assert seen["body"]["request_id"] == "learn-qwen-request"
    assert seen["body"]["model"] == profile["model_name"]
    assert "申请职位" in seen["body"]["messages"][1]["content"][0]["text"]
