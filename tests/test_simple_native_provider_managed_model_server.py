from __future__ import annotations

from contextlib import nullcontext
from hashlib import sha256
import json
from pathlib import Path

import pytest


def _qwen_projection() -> dict[str, object]:
    return {
        "image_size": [100, 80],
        "candidates": [{"i": 0, "box": [10, 10, 20, 20], "active": True}],
    }


def test_scoped_qwen_acquisition_skips_benchmark_materialization(monkeypatch, tmp_path: Path) -> None:
    from app.core import model_server
    from app.learn.hybrid import windows_process_scope

    profile = {"profile_id": "qwen-test", "model_name": "qwen", "endpoint": "http://127.0.0.1:8080/v1/chat/completions"}
    readiness = {"started": True, "profile": profile, "after": {"status": "running"}}
    lease = {"lease_id": "lease/test"}
    acquired: list[dict[str, object]] = []

    class Scope:
        def __init__(self, _name: str, *, create: bool) -> None:
            assert create is False

        def pids(self) -> list[int]:
            return [123]

        def close(self) -> None:
            return None

    monkeypatch.setenv("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", "Local\\AgentGuiHybrid-qwen-" + "a" * 64)
    monkeypatch.delenv("AGENT_GUI_HYBRID_PROVIDER_RUNTIME_PATH", raising=False)
    monkeypatch.setattr(windows_process_scope, "WindowsProcessScope", Scope)
    monkeypatch.setattr(model_server, "profile_for_stage", lambda _stage, _profile_id: dict(profile))
    monkeypatch.setattr(model_server, "_ensure_model_server_for_profile", lambda **_kwargs: dict(readiness))
    monkeypatch.setattr(model_server, "_observe_qwen_server_binding", lambda _profile, _readiness: {"server_process_identity": {"pid": 123, "create_time_ns": 456}})
    monkeypatch.setattr(model_server, "_qwen_acquisition_lock", nullcontext)
    monkeypatch.setattr(model_server, "_qwen_acquisition_artifact_paths", lambda _request_id: {"owner": tmp_path / "missing-owner"})
    monkeypatch.setattr(model_server, "_validate_qwen_runtime_acquiring", lambda _request_id: (_ for _ in ()).throw(AssertionError("benchmark validation reached")))
    monkeypatch.setattr(model_server, "_transition_qwen_model_request_materialization_locked", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("benchmark materialization reached")))
    monkeypatch.setattr(
        model_server,
        "_acquire_qwen_model_lease_under_acquisition_lock",
        lambda **kwargs: acquired.append(kwargs) or dict(lease),
    )

    result = model_server.ensure_and_acquire_scoped_qwen_model_lease(
        stage="understanding",
        profile_id="qwen-test",
        request_id="simple-native-qwen-test",
        wait_seconds=1,
    )

    assert result == lease
    assert acquired == [{"profile": profile, "request_id": "simple-native-qwen-test", "readiness": readiness, "publish_runtime_acquired": False}]


def test_qwen_projection_wire_is_compact_bounded_and_marks_each_serial_body_complete(monkeypatch) -> None:
    from app.core import model_server

    events: list[object] = []
    requests: list[dict[str, object]] = []
    lease = {"lease_id": "same-lease"}
    response_payload = {
        "choices": [{"message": {"content": json.dumps({"bindings": [{"i": 0, "role": "button", "label": "Open", "status": "BOUND", "confidence": 1}]})}}]
    }

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read(self, limit: int) -> bytes:
            events.append(("read", limit))
            return json.dumps(response_payload).encode("utf-8")

    def urlopen(request, *, timeout: float):
        events.append(("open", timeout))
        requests.append(json.loads(request.data.decode("utf-8")))
        return Response()

    monkeypatch.setattr(model_server, "_profile_for_qwen_model_lease", lambda selected: events.append(("attest", selected)) or {"profile_id": "qwen", "model_name": "qwen", "endpoint": "http://127.0.0.1:8080/v1/chat/completions"})
    monkeypatch.setattr(model_server, "mark_qwen_model_request_in_flight", lambda **kwargs: events.append(("in_flight", kwargs["model_lease"])) or len(requests) + 1)
    monkeypatch.setattr(model_server, "mark_qwen_model_response_body_complete", lambda **kwargs: events.append(("complete", kwargs["model_lease"], kwargs["request_attempt"])) or True)
    monkeypatch.setattr(model_server.urllib.request, "urlopen", urlopen)
    image = b"verified-png"

    for _ in range(5):
        assert model_server.run_qwen_projection_model(
            projection=_qwen_projection(),
            screenshot_bytes=image,
            screenshot_media_type="image/png",
            screenshot_sha256=sha256(image).hexdigest(),
            model_lease=lease,
            timeout_seconds=2,
        ) == {"bindings": [{"i": 0, "role": "button", "label": "Open", "status": "BOUND", "confidence": 1}]}

    assert len(requests) == 5
    for body in requests:
        wire = json.dumps(body, sort_keys=True)
        assert set(body) == {"model", "temperature", "max_tokens", "response_format", "messages"}
        assert body["temperature"] == 0.0 and body["max_tokens"] == 1536
        assert body["response_format"]["schema"] == model_server._qwen_model_projection_response_schema(_qwen_projection())
        assert "candidate/" not in wire and "context_ref" not in wire and "capture_id" not in wire
        assert body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert [event[0] for event in events].count("attest") == 5
    assert [event[0] for event in events].count("in_flight") == 5
    assert [event[0] for event in events].count("complete") == 5
    for index in range(5):
        names = [event[0] for event in events[index * 5:(index + 1) * 5]]
        assert names == ["attest", "in_flight", "open", "read", "complete"]


def test_scoped_qwen_release_uses_exact_release_without_benchmark_artifacts(monkeypatch) -> None:
    from app.core import model_server

    calls: list[dict[str, object]] = []
    lease = {"lease_id": "lease/test"}
    monkeypatch.setattr(
        model_server,
        "_release_exact_qwen_lease",
        lambda selected, **kwargs: calls.append({"lease": selected, **kwargs}) or {"status": "released"},
    )

    assert model_server.release_scoped_qwen_model_lease(lease, "completed") == {"status": "released"}
    assert calls == [{"lease": lease, "reason": "completed", "persist_benchmark_artifacts": False}]


def test_vista_bare_point_wire_uses_one_user_message_and_reuses_exact_lease(monkeypatch) -> None:
    from app.core import model_server

    events: list[object] = []
    requests: list[dict[str, object]] = []
    lease = {"contract_version": "hybrid_vista_model_lease_v2", "provider": "vista"}
    response_payload = {"choices": [{"message": {"content": "[500,500]"}}]}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def read(self, limit: int) -> bytes:
            events.append(("read", limit))
            return json.dumps(response_payload).encode("utf-8")

    def urlopen(request, *, timeout: float):
        events.append(("open", timeout))
        requests.append(json.loads(request.data.decode("utf-8")))
        return Response()

    profile = {
        "profile_id": "vista-test",
        "model_name": "vista",
        "endpoint": "http://127.0.0.1:13244/v1/chat/completions",
        "max_new_tokens": 32,
    }
    monkeypatch.setattr(
        model_server,
        "_profile_for_hybrid_vista_model_lease",
        lambda selected: events.append(("attest", selected)) or profile,
    )
    monkeypatch.setattr(model_server.urllib.request, "urlopen", urlopen)
    roi = b"verified-roi"

    for _ in range(3):
        assert model_server.run_hybrid_vista_bare_point(
            roi_bytes=roi,
            roi_media_type="image/png",
            roi_sha256=sha256(roi).hexdigest(),
            target_text="button labeled 'Open'",
            model_lease=lease,
            timeout_seconds=2,
        ) == "[500,500]"

    assert len(requests) == 3
    for body in requests:
        assert set(body) == {
            "model",
            "temperature",
            "max_tokens",
            "request_timeout_seconds",
            "messages",
        }
        assert body["temperature"] == 0.0 and body["max_tokens"] == 32
        assert body["request_timeout_seconds"] == 2.0
        assert len(body["messages"]) == 1 and body["messages"][0]["role"] == "user"
        content = body["messages"][0]["content"]
        assert content[0] == {
            "type": "text",
            "text": "button labeled 'Open'\nReturn only [x,y] normalized to 0..1000.",
        }
        assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
        assert "response_format" not in body
    for index in range(3):
        assert [event[0] for event in events[index * 3:(index + 1) * 3]] == [
            "attest",
            "open",
            "read",
        ]


def test_vista_exact_lease_rejects_mutated_profile_before_process_or_wire(monkeypatch) -> None:
    from app.core import model_server

    profile = {
        "profile_id": "vista-test",
        "endpoint": "http://127.0.0.1:13244/v1/chat/completions",
        "port": 13244,
    }
    identities = [{"pid": 123, "create_time_ns": 456}]
    lease = {
        "contract_version": "hybrid_vista_model_lease_v2",
        "provider": "vista",
        "incarnation_id": model_server.content_sha256(
            {"profile_id": "vista-test", "process_identities": identities}
        ),
        "profile": profile,
        "process_identities": identities,
        "process_scope_name": "scope-vista",
        "process_scope_acquisition": {
            "contract_version": "hybrid_process_scope_acquisition_v1",
            "scope_name": "scope-vista",
            "member_pids": [123],
            "process_identities": identities,
        },
    }
    monkeypatch.setattr(
        model_server,
        "profile_for_stage",
        lambda _stage, _profile_id: {**profile, "endpoint": "http://127.0.0.1:1/v1/chat/completions"},
    )

    with pytest.raises(ValueError, match="installed configuration"):
        model_server._profile_for_hybrid_vista_model_lease(lease)
