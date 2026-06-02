from __future__ import annotations

from app.api import runtime as runtime_api
from app.models.request import ModelServerRequest, RuntimePrepareRequest


def test_model_status_reports_profiles(monkeypatch) -> None:
    monkeypatch.setattr(runtime_api, "load_model_profiles", lambda: [{"profile_id": "demo"}])
    monkeypatch.setattr(runtime_api, "check_model_server", lambda profile: {"status": "running", "model_id": "demo.gguf"})

    response = runtime_api.model_status()

    assert response.success is True
    assert response.data["contract_version"] == "runtime_model_status_v1"
    assert response.data["models"][0]["status"]["status"] == "running"
    assert response.data["timings"]["steps"][0]["name"] == "load_model_profiles"


def test_start_model_ensures_stage(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_api,
        "ensure_model_server",
        lambda **kwargs: {"stage": kwargs["stage"], "started": True, "profile": {"profile_id": "demo"}},
    )
    monkeypatch.setattr(runtime_api, "write_trace", lambda **kwargs: "logs/traces/runtime/start.json")

    response = runtime_api.start_model(ModelServerRequest(stage="observe"))

    assert response.success is True
    assert response.data["started"] is True
    assert response.data["trace_path"].endswith("start.json")
    assert response.data["timings"]["steps"][0]["name"] == "ensure_model_server"


def test_stop_model_stops_profile(monkeypatch) -> None:
    monkeypatch.setattr(runtime_api, "profile_for_stage", lambda stage, profile_id=None: {"profile_id": profile_id or stage})
    monkeypatch.setattr(
        runtime_api,
        "stop_model_server",
        lambda profile: {
            "profile": profile,
            "returncode": 0,
            "stdout": "stopped",
            "stderr": "",
            "stopped": True,
            "after": {"status": "unreachable"},
        },
    )
    monkeypatch.setattr(runtime_api, "write_trace", lambda **kwargs: "logs/traces/runtime/stop.json")

    response = runtime_api.stop_model(ModelServerRequest(stage="locate"))

    assert response.success is True
    assert response.data["stopped"] is True
    assert response.data["trace_path"].endswith("stop.json")
    assert [step["name"] for step in response.data["timings"]["steps"]] == ["resolve_model_profile", "stop_model_server"]


def test_prepare_runtime_starts_requested_model_stages(monkeypatch) -> None:
    calls: list[str] = []

    def fake_ensure(**kwargs):
        calls.append(kwargs["stage"])
        return {"stage": kwargs["stage"], "started": False, "profile": {"profile_id": kwargs["stage"]}}

    monkeypatch.setattr(runtime_api, "ensure_model_server", fake_ensure)
    monkeypatch.setattr(runtime_api, "write_trace", lambda **kwargs: "logs/traces/runtime/prepare.json")

    response = runtime_api.prepare_runtime(RuntimePrepareRequest(stages=["observe", "locate"], start_models=True))

    assert response.success is True
    assert calls == ["observe", "locate"]
    assert response.data["contract_version"] == "runtime_prepare_v1"
    assert response.data["trace_path"].endswith("prepare.json")
    assert [step["stage"] for step in response.data["timings"]["steps"]] == ["observe", "locate"]
