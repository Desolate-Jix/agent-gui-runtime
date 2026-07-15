from __future__ import annotations

import json
import psutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
MODEL_PROFILE_DIR = ROOT_DIR / "configs" / "model_profiles"

STAGE_PROFILE_IDS = {
    "observe": "qwen3_vl_8b_q4_k_m",
    "understanding": "qwen3_vl_8b_q4_k_m",
    "locate": "vista_4b_transformers",
    "grounding": "vista_4b_transformers",
}


def load_model_profiles() -> list[dict[str, Any]]:
    profiles: list[dict[str, Any]] = []
    if not MODEL_PROFILE_DIR.exists():
        return profiles
    for path in sorted(MODEL_PROFILE_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            payload["_profile_path"] = str(path)
            profiles.append(payload)
    return profiles


def profile_for_stage(stage: str, profile_id: str | None = None) -> dict[str, Any]:
    profiles = load_model_profiles()
    selected_profile_id = profile_id or STAGE_PROFILE_IDS.get(str(stage).casefold(), stage)
    for profile in profiles:
        if profile.get("profile_id") == selected_profile_id:
            return profile
    for profile in profiles:
        roles = [str(item).casefold() for item in profile.get("role") or []]
        if str(stage).casefold() in roles:
            return profile
    raise ValueError(f"Model profile not found for stage: {stage}")


def model_base_url(profile: dict[str, Any]) -> str:
    endpoint = str(profile.get("endpoint") or "").rstrip("/")
    for suffix in ["/chat/completions", "/completions"]:
        if endpoint.endswith(suffix):
            return endpoint[: -len(suffix)]
    if endpoint:
        return endpoint
    port = int(profile.get("port") or 1234)
    return f"http://127.0.0.1:{port}/v1"


def check_model_server(profile: dict[str, Any], *, timeout: float = 1.0) -> dict[str, Any]:
    base_url = model_base_url(profile)
    health_payload: dict[str, Any] | None = None
    if _profile_supports_health_status(profile):
        health_request = urllib.request.Request(f"{base_url}/health", headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(health_request, timeout=timeout) as response:
                health_payload = json.loads(response.read().decode("utf-8"))
            health_status = str(health_payload.get("status") or "").casefold()
            if health_status == "busy":
                return {
                    "status": "busy",
                    "base_url": base_url,
                    "health": health_payload,
                    "model_id": str(health_payload.get("model") or "") or None,
                }
        except Exception:
            health_payload = None
    request = urllib.request.Request(f"{base_url}/models", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return {
            "status": "running",
            "base_url": base_url,
            "response": payload,
            "health": health_payload,
            "model_id": _model_id(payload),
        }
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if "loading model" in body.casefold():
            return {"status": "loading", "base_url": base_url, "error": body}
        return {"status": "unreachable", "base_url": base_url, "error": body}
    except Exception as exc:
        return {"status": "unreachable", "base_url": base_url, "error": str(exc)}


def ensure_model_server(
    *,
    stage: str,
    profile_id: str | None = None,
    wait_until_ready: bool = False,
    wait_seconds: float = 0.0,
) -> dict[str, Any]:
    profile = profile_for_stage(stage, profile_id)
    before = check_model_server(profile)
    if before["status"] in {"running", "loading", "busy"}:
        result = {"stage": stage, "profile": _public_profile(profile), "before": before, "started": False}
        if wait_until_ready and before["status"] == "loading":
            result["after"] = wait_for_model_server(profile, wait_seconds=wait_seconds)
        return result

    resource_switch = _stop_exclusive_resource_conflicts(profile)
    start_result = start_model_server(profile)
    result = {
        "stage": stage,
        "profile": _public_profile(profile),
        "before": before,
        "resource_switch": resource_switch,
        "started": True,
        "start": start_result,
    }
    if wait_until_ready:
        result["after"] = wait_for_model_server(
            profile,
            wait_seconds=wait_seconds,
            expected_pid=start_result.get("pid"),
            log_path=start_result.get("log_path"),
        )
    return result


def _stop_exclusive_resource_conflicts(profile: dict[str, Any]) -> dict[str, Any]:
    group = str(profile.get("exclusive_resource_group") or "").strip()
    target_profile_id = str(profile.get("profile_id") or "").strip()
    result: dict[str, Any] = {
        "exclusive_resource_group": group or None,
        "target_profile_id": target_profile_id or None,
        "checked_profile_ids": [],
        "stopped_profile_ids": [],
    }
    if not group:
        return result

    for candidate in load_model_profiles():
        candidate_profile_id = str(candidate.get("profile_id") or "").strip()
        if not candidate_profile_id or candidate_profile_id == target_profile_id:
            continue
        if str(candidate.get("exclusive_resource_group") or "").strip() != group:
            continue
        result["checked_profile_ids"].append(candidate_profile_id)
        status = check_model_server(candidate, timeout=0.5)
        if status.get("status") not in {"running", "loading", "busy"}:
            continue
        stop_result = stop_model_server(candidate)
        if not stop_result.get("stopped"):
            raise RuntimeError(
                f"Could not release exclusive model resource {group} from profile {candidate_profile_id}"
            )
        result["stopped_profile_ids"].append(candidate_profile_id)
    return result


def start_model_server(profile: dict[str, Any]) -> dict[str, Any]:
    if profile.get("launchable") is False:
        profile_id = str(profile.get("profile_id") or "unknown")
        raise ValueError(f"Model profile is not launchable: {profile_id}")
    script = _resolve_path(str(profile.get("start_script") or "scripts/model_servers/start_llama_vision_server.ps1"))
    if not script.exists():
        raise FileNotFoundError(f"Model start script not found: {script}")
    logs_dir = ROOT_DIR / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"local-vision-server-{profile.get('profile_id')}-{time.strftime('%Y%m%d-%H%M%S')}.log"
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
    ]
    for key, parameter in [
        ("model_path", "-ModelPath"),
        ("mmproj_path", "-MmprojPath"),
        ("server_path", "-ServerPath"),
        ("model_name", "-ModelName"),
        ("host", "-Host"),
        ("port", "-Port"),
        ("context_size", "-ContextSize"),
        ("gpu_layers", "-GpuLayers"),
        ("image_min_tokens", "-ImageMinTokens"),
        ("chat_template", "-ChatTemplate"),
        ("device", "-Device"),
        ("dtype", "-DType"),
        ("max_new_tokens", "-MaxNewTokens"),
        ("gpu_memory_gib", "-GpuMemoryGiB"),
        ("cpu_memory_gib", "-CpuMemoryGiB"),
    ]:
        value = profile.get(key)
        if value not in (None, ""):
            if key.endswith("_path"):
                resolved = _resolve_path(str(value))
                if not resolved.exists():
                    raise FileNotFoundError(f"Model profile path not found for {key}: {resolved}")
                command.extend([parameter, str(resolved)])
            else:
                command.extend([parameter, str(value)])

    log_file = log_path.open("a", encoding="utf-8")
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        command,
        cwd=str(ROOT_DIR),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=creationflags,
    )
    time.sleep(float(profile.get("startup_exit_check_seconds") or 0.75))
    returncode = process.poll()
    if returncode is not None:
        log_file.close()
        raise RuntimeError(f"Model start script exited immediately with code {returncode}; see log: {log_path}")
    pid_path = _profile_pid_path(profile)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(process.pid), encoding="utf-8")
    health_status: dict[str, Any] | None = None
    pid_sync = None
    if _profile_supports_health_status(profile):
        health_timeout = float(profile.get("startup_health_timeout_seconds") or 0.25)
        health_status = check_model_server(profile, timeout=health_timeout)
        pid_sync = _sync_pid_file_from_health(profile, health_status, pid_path=pid_path)
    return {
        "pid": process.pid,
        "pid_source": "health" if pid_sync else "wrapper_process",
        "service_pid": pid_sync["pid"] if pid_sync else None,
        "command": command,
        "log_path": str(log_path),
        "pid_path": str(pid_path),
        "health_after_start": health_status,
    }


def stop_model_server(profile: dict[str, Any]) -> dict[str, Any]:
    script = _resolve_path(str(profile.get("stop_script") or "scripts/model_servers/stop_local_vision_server.ps1"))
    if not script.exists():
        raise FileNotFoundError(f"Model stop script not found: {script}")
    command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script),
    ]
    port = profile.get("port")
    if port not in (None, ""):
        command.extend(["-Port", str(port)])
    pid_file = str(profile.get("pid_file") or "").strip()
    if pid_file:
        command.extend(["-PidFile", str(_resolve_path(pid_file))])
    completed = subprocess.run(
        command,
        cwd=str(ROOT_DIR),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return {
        "profile": _public_profile(profile),
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "stopped": completed.returncode == 0,
        "after": check_model_server(profile),
    }


def wait_for_model_server(
    profile: dict[str, Any],
    *,
    wait_seconds: float,
    expected_pid: int | None = None,
    log_path: str | None = None,
) -> dict[str, Any]:
    deadline = time.monotonic() + float(wait_seconds)
    last = check_model_server(profile)
    while time.monotonic() < deadline:
        if last["status"] == "running":
            last = _refresh_running_status_health(profile, last)
            _sync_pid_file_from_health(profile, last)
            return last
        if expected_pid and not _process_is_alive(expected_pid):
            return {
                **last,
                "status": "startup_failed",
                "reason": "started_process_exited",
                "expected_pid": expected_pid,
                "log_path": log_path,
            }
        time.sleep(1.0)
        last = check_model_server(profile)
    if last.get("status") == "running":
        last = _refresh_running_status_health(profile, last)
    _sync_pid_file_from_health(profile, last)
    return last


def _process_is_alive(pid: int) -> bool:
    try:
        process = psutil.Process(int(pid))
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError, TypeError):
        return False


def _profile_supports_health_status(profile: dict[str, Any]) -> bool:
    return str(profile.get("runtime") or "").casefold() == "transformers" or str(profile.get("output_contract") or "").casefold() == "vista_point_v1"


def _sync_pid_file_from_health(
    profile: dict[str, Any],
    status: dict[str, Any],
    *,
    pid_path: Path | None = None,
) -> dict[str, Any] | None:
    health = status.get("health")
    if not isinstance(health, dict):
        return None
    pid_value = health.get("pid")
    try:
        pid = int(pid_value)
    except (TypeError, ValueError):
        return None
    target = pid_path or _profile_pid_path(profile)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(pid), encoding="utf-8")
    return {"pid": pid, "pid_path": str(target), "source": "health"}


def _refresh_running_status_health(profile: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    if status.get("status") != "running" or status.get("health"):
        return status
    if not _profile_supports_health_status(profile):
        return status
    refreshed = check_model_server(profile, timeout=1.0)
    if refreshed.get("status") == "running" and refreshed.get("health"):
        return refreshed
    return status


def _resolve_path(path: str) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return ROOT_DIR / candidate


def _profile_pid_path(profile: dict[str, Any]) -> Path:
    pid_file = str(profile.get("pid_file") or "").strip()
    if pid_file:
        return _resolve_path(pid_file)
    profile_id = str(profile.get("profile_id") or "local-vision").strip() or "local-vision"
    safe_id = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in profile_id)
    return ROOT_DIR / "logs" / f"{safe_id}-server.pid"


def _public_profile(profile: dict[str, Any]) -> dict[str, Any]:
    public = dict(profile)
    public.pop("_profile_path", None)
    return public


def _model_id(payload: dict[str, Any]) -> str | None:
    data = payload.get("data")
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return str(data[0].get("id") or "") or None
    models = payload.get("models")
    if isinstance(models, list) and models and isinstance(models[0], dict):
        return str(models[0].get("name") or models[0].get("model") or "") or None
    return None
