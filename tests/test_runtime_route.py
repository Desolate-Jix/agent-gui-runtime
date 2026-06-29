from __future__ import annotations

import json
from pathlib import Path

from app.api import runtime as runtime_api
from app.core import model_server
from app.core.model_server import profile_for_stage
from app.api.models.request import ModelServerRequest, RuntimePrepareRequest


def test_model_status_reports_profiles(monkeypatch) -> None:
    monkeypatch.setattr(runtime_api, "load_model_profiles", lambda: [{"profile_id": "demo"}])
    monkeypatch.setattr(runtime_api, "check_model_server", lambda profile: {"status": "running", "model_id": "demo.gguf"})

    response = runtime_api.model_status()

    assert response.success is True
    assert response.data["contract_version"] == "runtime_model_status_v1"
    assert response.data["models"][0]["status"]["status"] == "running"
    assert response.data["timings"]["steps"][0]["name"] == "load_model_profiles"


def test_observe_stage_defaults_to_small_understanding_profile() -> None:
    observe = profile_for_stage("observe")
    locate = profile_for_stage("locate")

    assert observe["profile_id"] == "qwen3_vl_4b_q4_k_m"
    assert observe["provider_mode"] == "local_understanding"
    assert locate["profile_id"] == "vista_4b_transformers"
    assert locate["provider_mode"] == "local_grounding"


def test_vista_transformers_profile_is_launchable() -> None:
    profile = profile_for_stage("locate", "vista_4b_transformers")

    assert profile["runtime"] == "transformers"
    assert profile["output_contract"] == "vista_point_v1"
    assert profile["start_script"] == "scripts/model_servers/start_transformers_vision_server.ps1"
    assert profile["endpoint"] == "http://127.0.0.1:1244/v1/chat/completions"
    assert Path(profile["model_path"]).exists()


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


def test_start_model_server_passes_transformers_profile_args(monkeypatch) -> None:
    calls: list[list[str]] = []

    class DummyProcess:
        pid = 12345

        def poll(self):
            return None

    def fake_popen(command, **_kwargs):
        calls.append(command)
        return DummyProcess()

    monkeypatch.setattr(model_server.subprocess, "Popen", fake_popen)

    result = model_server.start_model_server(
        {
            "profile_id": "vista_4b_transformers",
            "model_name": "inclusionAI/VISTA-4B",
            "model_path": "models/vista-4b-safetensors",
            "start_script": "scripts/model_servers/start_transformers_vision_server.ps1",
            "pid_file": "logs/test-vista-transformers.pid",
            "host": "127.0.0.1",
            "port": 1244,
            "device": "auto",
            "dtype": "bfloat16",
            "max_new_tokens": 32,
            "startup_exit_check_seconds": 0,
        }
    )

    command = calls[0]
    assert result["pid"] == 12345
    assert "start_transformers_vision_server.ps1" in command[5]
    assert command[command.index("-ModelName") + 1] == "inclusionAI/VISTA-4B"
    assert command[command.index("-Port") + 1] == "1244"
    assert command[command.index("-Device") + 1] == "auto"
    assert command[command.index("-DType") + 1] == "bfloat16"
    assert command[command.index("-MaxNewTokens") + 1] == "32"


def test_start_model_server_rejects_non_launchable_profile(monkeypatch) -> None:
    def fail_popen(*_args, **_kwargs):
        raise AssertionError("non-launchable profiles must not spawn a process")

    monkeypatch.setattr(model_server.subprocess, "Popen", fail_popen)

    try:
        model_server.start_model_server(
            {
                "profile_id": "minicpm_v_4_6_transformers",
                "launchable": False,
                "model_path": "models/minicpm-v-4.6-safetensors",
            }
        )
    except ValueError as exc:
        assert "Model profile is not launchable: minicpm_v_4_6_transformers" in str(exc)
    else:
        raise AssertionError("start_model_server should reject non-launchable profiles")


def test_start_model_server_rejects_immediate_script_exit(monkeypatch) -> None:
    class FailedProcess:
        pid = 12345

        def poll(self):
            return 2

    monkeypatch.setattr(model_server.subprocess, "Popen", lambda *_args, **_kwargs: FailedProcess())

    try:
        model_server.start_model_server(
            {
                "profile_id": "vista_4b_transformers",
                "model_path": "models/vista-4b-safetensors",
                "start_script": "scripts/model_servers/start_transformers_vision_server.ps1",
                "pid_file": "logs/test-vista-transformers-failed.pid",
                "port": 1244,
                "startup_exit_check_seconds": 0,
            }
        )
    except RuntimeError as exc:
        assert "exited immediately with code 2" in str(exc)
    else:
        raise AssertionError("start_model_server should reject an immediately exited script")


def test_check_model_server_reports_vista_busy_health(monkeypatch) -> None:
    class DummyResponse:
        def __init__(self, payload: dict):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(self.payload).encode("utf-8")

    requested_urls: list[str] = []

    def fake_urlopen(request, timeout=1.0):
        requested_urls.append(request.full_url)
        return DummyResponse({"status": "busy", "model": "inclusionAI/VISTA-4B", "pid": 123})

    monkeypatch.setattr(model_server.urllib.request, "urlopen", fake_urlopen)

    result = model_server.check_model_server(
        {
            "profile_id": "vista_4b_transformers",
            "runtime": "transformers",
            "output_contract": "vista_point_v1",
            "endpoint": "http://127.0.0.1:1244/v1/chat/completions",
        }
    )

    assert result["status"] == "busy"
    assert result["health"]["pid"] == 123
    assert requested_urls == ["http://127.0.0.1:1244/v1/health"]


def test_ensure_model_server_does_not_start_second_vista_when_busy(monkeypatch) -> None:
    monkeypatch.setattr(
        model_server,
        "profile_for_stage",
        lambda stage, profile_id=None: {
            "profile_id": profile_id or "vista_4b_transformers",
            "runtime": "transformers",
            "output_contract": "vista_point_v1",
        },
    )
    monkeypatch.setattr(model_server, "check_model_server", lambda profile: {"status": "busy", "health": {"pid": 123}})

    def fail_start(_profile):
        raise AssertionError("busy VISTA service must not start another process")

    monkeypatch.setattr(model_server, "start_model_server", fail_start)

    result = model_server.ensure_model_server(stage="locate", profile_id="vista_4b_transformers")

    assert result["started"] is False
    assert result["before"]["status"] == "busy"


def test_start_model_accepts_panel_preflight_wait(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_ensure(**kwargs):
        calls.append(kwargs)
        return {"stage": kwargs["stage"], "started": False, "profile": {"profile_id": kwargs["profile_id"]}}

    monkeypatch.setattr(runtime_api, "ensure_model_server", fake_ensure)
    monkeypatch.setattr(runtime_api, "write_trace", lambda **kwargs: "logs/traces/runtime/start.json")

    response = runtime_api.start_model(
        ModelServerRequest(
            stage="locate",
            profile_id="vista_4b_transformers",
            wait_until_ready=True,
            wait_seconds=180,
        )
    )

    assert response.success is True
    assert calls[0]["wait_until_ready"] is True
    assert calls[0]["wait_seconds"] == 180


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
