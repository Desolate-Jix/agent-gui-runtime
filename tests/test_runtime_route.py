from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.api import runtime as runtime_api
from app.core import model_server
from app.core.model_server import profile_for_stage
from app.api.models.request import ModelServerRequest, RuntimePrepareRequest
from app.main import app


def test_model_status_reports_profiles(monkeypatch) -> None:
    monkeypatch.setattr(runtime_api, "load_model_profiles", lambda: [{"profile_id": "demo"}])
    monkeypatch.setattr(runtime_api, "check_model_server", lambda profile: {"status": "running", "model_id": "demo.gguf"})

    response = runtime_api.model_status()

    assert response.success is True
    assert response.data["contract_version"] == "runtime_model_status_v1"
    assert response.data["models"][0]["status"]["status"] == "running"
    assert response.data["timings"]["steps"][0]["name"] == "load_model_profiles"


def test_model_status_checks_only_requested_profile(monkeypatch) -> None:
    checked: list[str] = []
    monkeypatch.setattr(
        runtime_api,
        "load_model_profiles",
        lambda: [
            {"profile_id": "qwen3_vl_8b_q4_k_m"},
            {"profile_id": "vista_4b_transformers"},
            {"profile_id": "unused_model"},
        ],
    )

    def fake_check(profile):
        checked.append(profile["profile_id"])
        return {"status": "running", "model_id": profile["profile_id"]}

    monkeypatch.setattr(runtime_api, "check_model_server", fake_check)

    response = runtime_api.model_status(profile_id="vista_4b_transformers")

    assert response.success is True
    assert checked == ["vista_4b_transformers"]
    assert [item["profile"]["profile_id"] for item in response.data["models"]] == ["vista_4b_transformers"]
    assert response.data["requested_profile_id"] == "vista_4b_transformers"


def test_observe_stage_defaults_to_learning_quality_understanding_profile() -> None:
    observe = profile_for_stage("observe")
    locate = profile_for_stage("locate")

    assert observe["profile_id"] == "qwen3_vl_8b_q4_k_m"
    assert observe["provider_mode"] == "local_understanding"
    assert "learning" in observe["role"]
    assert locate["profile_id"] == "vista_4b_transformers"
    assert locate["provider_mode"] == "local_grounding"


def test_vision_config_uses_learning_quality_understanding_profile() -> None:
    vision_config = json.loads(Path("configs/vision.json").read_text(encoding="utf-8"))
    local_understanding = vision_config["vision"]["local_understanding"]

    assert local_understanding["profile_id"] == "qwen3_vl_8b_q4_k_m"
    assert local_understanding["model_name"] == "Qwen3VL-8B-Instruct-Q4_K_M.gguf"
    assert local_understanding["endpoint"] == "http://127.0.0.1:1240/v1/chat/completions"


def test_removed_learning_draft_routes_are_not_exposed() -> None:
    client = TestClient(app)

    for path in (
        "/runtime/learning/seek/draft",
        "/runtime/learning/seek/tune",
        "/runtime/learning/fixtures/generic_list_detail_fixture/draft",
        "/runtime/learning/generalization",
    ):
        assert client.get(path).status_code == 404


def test_vista_transformers_profile_is_launchable() -> None:
    profile = profile_for_stage("locate", "vista_4b_transformers")

    assert profile["runtime"] == "transformers"
    assert profile["output_contract"] == "vista_point_v1"
    assert profile["start_script"] == "scripts/model_servers/start_transformers_vision_server.ps1"
    assert profile["endpoint"] == "http://127.0.0.1:1244/v1/chat/completions"
    assert Path(profile["model_path"]).exists()
    assert (Path(profile["model_path"]) / "model.safetensors.index.json").exists()


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
            "gpu_memory_gib": 6,
            "cpu_memory_gib": 6,
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
    assert command[command.index("-GpuMemoryGiB") + 1] == "6"
    assert command[command.index("-CpuMemoryGiB") + 1] == "6"


def test_start_model_server_refreshes_pid_file_from_health(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []
    script_path = tmp_path / "start.ps1"
    model_path = tmp_path / "model"
    pid_path = tmp_path / "server.pid"
    script_path.write_text("# test", encoding="utf-8")
    model_path.mkdir()

    class DummyProcess:
        pid = 111

        def poll(self):
            return None

    def fake_popen(command, **_kwargs):
        calls.append(command)
        return DummyProcess()

    monkeypatch.setattr(model_server.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(model_server.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(
        model_server,
        "check_model_server",
        lambda profile, timeout=1.0: {
            "status": "running",
            "health": {"pid": 222, "model": "osunlp/UGround-V1-2B"},
        },
    )

    result = model_server.start_model_server(
        {
            "profile_id": "learn_mode_uground_2b",
            "runtime": "transformers",
            "model_name": "osunlp/UGround-V1-2B",
            "model_path": str(model_path),
            "start_script": str(script_path),
            "pid_file": str(pid_path),
            "endpoint": "http://127.0.0.1:1245/v1/chat/completions",
            "startup_exit_check_seconds": 0,
            "startup_health_timeout_seconds": 0,
        }
    )

    assert calls
    assert result["pid"] == 111
    assert result["service_pid"] == 222
    assert result["pid_source"] == "health"
    assert pid_path.read_text(encoding="utf-8") == "222"


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


def test_ensure_model_server_stops_running_conflict_in_exclusive_resource_group(monkeypatch) -> None:
    target = {
        "profile_id": "vista_4b_transformers",
        "exclusive_resource_group": "gpu_vision",
    }
    running_conflict = {
        "profile_id": "qwen3_vl_8b_q4_k_m",
        "exclusive_resource_group": "gpu_vision",
    }
    unrelated = {
        "profile_id": "cpu_ocr",
        "exclusive_resource_group": "cpu_ocr",
    }
    stopped: list[str] = []
    started: list[str] = []

    monkeypatch.setattr(model_server, "profile_for_stage", lambda stage, profile_id=None: target)
    monkeypatch.setattr(model_server, "load_model_profiles", lambda: [target, running_conflict, unrelated])

    def fake_check(profile, timeout=1.0):
        if profile["profile_id"] == "qwen3_vl_8b_q4_k_m":
            return {"status": "running"}
        return {"status": "unreachable"}

    monkeypatch.setattr(model_server, "check_model_server", fake_check)
    monkeypatch.setattr(
        model_server,
        "stop_model_server",
        lambda profile: stopped.append(profile["profile_id"]) or {"stopped": True, "returncode": 0},
    )
    monkeypatch.setattr(
        model_server,
        "start_model_server",
        lambda profile: started.append(profile["profile_id"]) or {"pid": 456},
    )

    result = model_server.ensure_model_server(stage="locate", profile_id="vista_4b_transformers")

    assert stopped == ["qwen3_vl_8b_q4_k_m"]
    assert started == ["vista_4b_transformers"]
    assert result["resource_switch"]["stopped_profile_ids"] == ["qwen3_vl_8b_q4_k_m"]
    assert result["started"] is True


def test_wait_for_model_server_refreshes_pid_file_from_health(monkeypatch, tmp_path: Path) -> None:
    pid_path = tmp_path / "uground.pid"
    monkeypatch.setattr(
        model_server,
        "check_model_server",
        lambda profile: {
            "status": "running",
            "health": {"pid": 333, "model": "osunlp/UGround-V1-2B"},
        },
    )

    result = model_server.wait_for_model_server(
        {
            "profile_id": "learn_mode_uground_2b",
            "runtime": "transformers",
            "pid_file": str(pid_path),
        },
        wait_seconds=0,
    )

    assert result["status"] == "running"
    assert pid_path.read_text(encoding="utf-8") == "333"


def test_wait_for_model_server_retries_health_when_running_status_lacks_pid(monkeypatch, tmp_path: Path) -> None:
    pid_path = tmp_path / "uground.pid"
    statuses = [
        {"status": "running", "health": None},
        {
            "status": "running",
            "health": {"pid": 444, "model": "osunlp/UGround-V1-2B"},
        },
    ]

    def fake_check(_profile, timeout=1.0):
        return statuses.pop(0)

    monkeypatch.setattr(model_server, "check_model_server", fake_check)

    result = model_server.wait_for_model_server(
        {
            "profile_id": "learn_mode_uground_2b",
            "runtime": "transformers",
            "pid_file": str(pid_path),
        },
        wait_seconds=0,
    )

    assert result["health"]["pid"] == 444
    assert pid_path.read_text(encoding="utf-8") == "444"


def test_wait_for_model_server_stops_when_started_process_exits(monkeypatch) -> None:
    checks: list[int] = []
    monkeypatch.setattr(
        model_server,
        "check_model_server",
        lambda profile: checks.append(1) or {"status": "unreachable", "error": "connection refused"},
    )
    monkeypatch.setattr(model_server, "_process_is_alive", lambda pid: False)

    result = model_server.wait_for_model_server(
        {"profile_id": "vista_4b_transformers"},
        wait_seconds=180,
        expected_pid=12345,
        log_path="logs/vista-start.log",
    )

    assert result["status"] == "startup_failed"
    assert result["reason"] == "started_process_exited"
    assert result["log_path"] == "logs/vista-start.log"
    assert len(checks) == 1


def test_start_model_reports_waited_startup_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        runtime_api,
        "ensure_model_server",
        lambda **kwargs: {
            "stage": kwargs["stage"],
            "started": True,
            "profile": {"profile_id": kwargs["profile_id"]},
            "after": {"status": "startup_failed", "reason": "started_process_exited"},
        },
    )
    monkeypatch.setattr(runtime_api, "write_trace", lambda **kwargs: "logs/traces/runtime/start-failed.json")

    response = runtime_api.start_model(
        ModelServerRequest(
            stage="locate",
            profile_id="vista_4b_transformers",
            wait_until_ready=True,
            wait_seconds=180,
        )
    )

    assert response.success is False
    assert response.error.code == "model_server_not_ready"
    assert response.data["after"]["status"] == "startup_failed"


def test_stop_script_keeps_explicit_port_scope() -> None:
    script = Path("scripts/model_servers/stop_local_vision_server.ps1").read_text(encoding="utf-8")

    assert '$explicitPort = $PSBoundParameters.ContainsKey("Port")' in script
    assert '$explicitPidFile = $PSBoundParameters.ContainsKey("PidFile") -and $PidFile' in script
    assert "$ports = if ($explicitPort)" in script
    assert "if (-not $explicitPidFile -and (Test-Path $profileDir))" in script
    assert "if (-not $explicitPidFile)" in script
    assert "@($Port) + $profilePorts" in script


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
