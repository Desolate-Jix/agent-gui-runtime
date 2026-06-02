from __future__ import annotations

import json
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
    "locate": "qwen3_6_iq4_xs",
    "grounding": "qwen3_6_iq4_xs",
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
    request = urllib.request.Request(f"{base_url}/models", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return {
            "status": "running",
            "base_url": base_url,
            "response": payload,
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
    if before["status"] in {"running", "loading"}:
        result = {"stage": stage, "profile": _public_profile(profile), "before": before, "started": False}
        if wait_until_ready and before["status"] == "loading":
            result["after"] = wait_for_model_server(profile, wait_seconds=wait_seconds)
        return result

    start_result = start_model_server(profile)
    result = {
        "stage": stage,
        "profile": _public_profile(profile),
        "before": before,
        "started": True,
        "start": start_result,
    }
    if wait_until_ready:
        result["after"] = wait_for_model_server(profile, wait_seconds=wait_seconds)
    return result


def start_model_server(profile: dict[str, Any]) -> dict[str, Any]:
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
        ("port", "-Port"),
        ("context_size", "-ContextSize"),
        ("gpu_layers", "-GpuLayers"),
        ("image_min_tokens", "-ImageMinTokens"),
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
    pid_path = _profile_pid_path(profile)
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(process.pid), encoding="utf-8")
    return {
        "pid": process.pid,
        "command": command,
        "log_path": str(log_path),
        "pid_path": str(pid_path),
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


def wait_for_model_server(profile: dict[str, Any], *, wait_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + float(wait_seconds)
    last = check_model_server(profile)
    while time.monotonic() < deadline:
        if last["status"] == "running":
            return last
        time.sleep(1.0)
        last = check_model_server(profile)
    return last


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
