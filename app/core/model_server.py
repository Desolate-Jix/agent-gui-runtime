from __future__ import annotations

import base64
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
import os
import psutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.learn.hybrid.contracts import validate_omni_inventory
from app.learn.recognition.uei.canonical import content_sha256

ROOT_DIR = Path(__file__).resolve().parents[2]
MODEL_PROFILE_DIR = ROOT_DIR / "configs" / "model_profiles"
MODEL_SERVER_LEASE_DIR = ROOT_DIR / "logs" / "model_server_leases"
_QWEN_HTTP_RESPONSE_MAX_BYTES = 1024 * 1024
_ACTIVE_SERVER_STATUSES = {"running", "loading", "busy"}


class QwenModelRequestTimeout(TimeoutError):
    """Qwen HTTP 请求在适配器边界统一归类为超时。"""

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


def cancel_model_request(
    *,
    request_id: str,
    task_kind: str,
    payload: dict[str, Any],
    timeout: float = 1.0,
    verify_seconds: float = 1.5,
) -> dict[str, Any]:
    normalized_request_id = str(request_id or "").strip()
    if not normalized_request_id:
        raise ValueError("request_id is required")
    matching_profiles = _request_cancel_profiles(task_kind=task_kind, payload=payload)
    if not matching_profiles:
        return {
            "contract_version": "model_request_cancellation_v1",
            "status": "not_supported",
            "request_id": normalized_request_id,
            "model_service_compute_termination": "not_supported",
            "provider_results": [],
        }

    provider_results = []
    for profile in matching_profiles:
        if str(task_kind or "").strip() == "panel_learning_hybrid_qwen_binding":
            provider_results.append(_cancel_qwen_profile(
                profile,
                request_id=normalized_request_id,
                timeout=timeout,
                verify_seconds=verify_seconds,
            ))
        else:
            provider_results.append(_cancel_profile_request(
                profile=profile,
                request_id=normalized_request_id,
                timeout=timeout,
                verify_seconds=verify_seconds,
            ))
    terminations = {
        str(item.get("model_service_compute_termination") or "")
        for item in provider_results
    }
    if "terminated" in terminations:
        status = "terminated"
    elif "cancellation_acknowledged_pending" in terminations:
        status = "cancellation_acknowledged_pending"
    elif "cancel_failed" in terminations:
        status = "cancel_failed"
    else:
        status = "request_not_active"
    return {
        "contract_version": "model_request_cancellation_v1",
        "status": status,
        "request_id": normalized_request_id,
        "model_service_compute_termination": status,
        "provider_results": provider_results,
    }


def _request_cancel_profiles(
    *,
    task_kind: str,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    normalized_task_kind = str(task_kind or "").strip()
    if normalized_task_kind == "panel_learning_hybrid_qwen_binding":
        try:
            profile = profile_for_stage("understanding")
        except ValueError:
            return []
        if str(profile.get("provider_mode") or "").strip().casefold() != "local_understanding":
            return []
        return [profile]
    effective_payload = payload
    if normalized_task_kind == "panel_learning_calibration_sequence":
        nested_payload = payload.get("locate_payload")
        effective_payload = nested_payload if isinstance(nested_payload, dict) else {}
        normalized_task_kind = "vision_locate_target"
    provider_mode = (
        str(effective_payload.get("provider_mode") or "").strip().casefold()
    )
    if (
        normalized_task_kind != "vision_locate_target"
        or provider_mode != "local_grounding"
    ):
        return []
    profiles = []
    for profile in load_model_profiles():
        if profile.get("request_cancel_supported") is not True:
            continue
        if not str(profile.get("request_cancel_endpoint") or "").strip():
            continue
        roles = {str(item).casefold() for item in profile.get("role") or []}
        if roles.intersection({"locate", "grounding"}):
            profiles.append(profile)
    return profiles


def _cancel_qwen_profile(
    profile: dict[str, Any],
    *,
    request_id: str,
    timeout: float,
    verify_seconds: float,
) -> dict[str, Any]:
    profile_id = str(profile.get("profile_id") or "unknown")
    acquired_profile = _qwen_acquired_profile_for_request(profile_id, request_id)
    if acquired_profile is not None:
        profile = acquired_profile
    endpoint = str(profile.get("request_cancel_endpoint") or "").strip()
    if profile.get("request_cancel_supported") is True and endpoint:
        request_result = _cancel_profile_request(
            profile=profile,
            request_id=request_id,
            timeout=timeout,
            verify_seconds=verify_seconds,
        )
        if request_result["model_service_compute_termination"] not in {
            "terminated",
            "request_not_active",
        }:
            return request_result
        lease_release = _release_qwen_request_lease(
            profile_id=profile_id,
            request_id=request_id,
            request_cancelled=True,
        )
        return {**request_result, **lease_release}

    try:
        lease_release = _release_qwen_request_lease(
            profile_id=profile_id,
            request_id=request_id,
            request_cancelled=False,
        )
    except Exception as error:
        return {
            "profile_id": profile_id,
            "status": "cancel_failed",
            "model_service_compute_termination": "cancel_failed",
            "error": str(error),
        }
    return {
        "profile_id": profile_id,
        **lease_release,
    }


def run_qwen_binding_model(
    *,
    request: dict[str, Any],
    screenshot_bytes: bytes,
    screenshot_media_type: str,
    screenshot_sha256: str,
    cancellation_event: Any | None = None,
    model_lease: dict[str, Any] | None = None,
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """使用既有 understanding profile 发出一次封闭的 Qwen JSON 请求。"""
    if cancellation_event is not None and cancellation_event.is_set():
        raise RuntimeError("Qwen binding request cancelled")
    profile = (
        _profile_for_qwen_model_lease(model_lease)
        if model_lease is not None
        else profile_for_stage("understanding")
    )
    endpoint = str(profile.get("endpoint") or "").strip()
    if not endpoint:
        endpoint = model_base_url(profile) + "/chat/completions"
    if not isinstance(screenshot_bytes, bytes) or not screenshot_bytes:
        raise ValueError("verified screenshot bytes are required")
    if screenshot_media_type not in {"image/png", "image/jpeg"}:
        raise ValueError("verified screenshot media type is invalid")
    if sha256(screenshot_bytes).hexdigest() != screenshot_sha256:
        raise ValueError("verified screenshot hash mismatch")
    image_url = (
        "data:"
        + screenshot_media_type
        + ";base64,"
        + base64.b64encode(screenshot_bytes).decode("ascii")
    )
    prompt = (
        "Bind semantics only to the supplied candidate_id values. Return exactly one JSON object with "
        "bindings and orphan_semantics. Never output geometry, action authority, new candidate IDs, or prose. "
        "Every supplied candidate_id must appear exactly once. Important visible semantics without a candidate "
        "must use reason ORPHAN_SEMANTIC. Canonical request: "
        + json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    body_payload: dict[str, Any] = {
        "model": str(profile.get("model_name") or profile.get("model_id") or "qwen"),
        "temperature": 0.0,
        "max_tokens": 4096,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "Return one closed JSON object only."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ],
    }
    request_id = str(os.environ.get("AGENT_GUI_MODEL_REQUEST_ID") or "").strip()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if request_id:
        body_payload["request_id"] = request_id
        headers["X-Agent-GUI-Request-ID"] = request_id
    http_request = urllib.request.Request(
        endpoint,
        data=json.dumps(body_payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(http_request, timeout=float(timeout_seconds)) as response:
            response_bytes = response.read(_QWEN_HTTP_RESPONSE_MAX_BYTES + 1)
            if len(response_bytes) > _QWEN_HTTP_RESPONSE_MAX_BYTES:
                raise ValueError("Qwen HTTP response byte limit exceeded")
            response_payload = json.loads(response_bytes.decode("utf-8"))
    except (TimeoutError, QwenModelRequestTimeout) as error:
        raise QwenModelRequestTimeout("Qwen binding request timed out") from error
    except urllib.error.URLError as error:
        if isinstance(error.reason, TimeoutError):
            raise QwenModelRequestTimeout("Qwen binding request timed out") from error
        raise RuntimeError(f"Qwen binding request failed: {error}") from error
    except (ValueError, UnicodeError):
        raise
    except Exception as error:
        raise RuntimeError(f"Qwen binding request failed: {error}") from error
    if cancellation_event is not None and cancellation_event.is_set():
        raise RuntimeError("Qwen binding request cancelled")
    choices = response_payload.get("choices") if isinstance(response_payload, dict) else None
    message = choices[0].get("message") if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise ValueError("Qwen binding response has no JSON message content")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError("Qwen binding response is not a closed JSON object") from error
    if not isinstance(parsed, dict):
        raise ValueError("Qwen binding response is not an object")
    return parsed


def acquire_qwen_model_lease(
    *,
    profile: dict[str, Any],
    request_id: str,
    readiness: dict[str, Any],
) -> dict[str, Any]:
    """为一个受管请求记录精确的 profile/server 所有权租约。"""
    profile_id = str(profile.get("profile_id") or "").strip()
    owner_request_id = str(request_id or "").strip()
    if not profile_id or not owner_request_id:
        raise ValueError("Qwen model lease identity is incomplete")
    observed = readiness.get("after") if isinstance(readiness.get("after"), dict) else readiness.get("before")
    observed = observed if isinstance(observed, dict) else {}
    lease = {
        "contract_version": "qwen_model_server_lease_v1",
        "lease_id": uuid4().hex,
        "owner_request_id": owner_request_id,
        "profile_id": profile_id,
        "server_base_url": str(observed.get("base_url") or model_base_url(profile)),
        "server_model_id": str(observed.get("model_id") or profile.get("model_name") or "") or None,
    }
    with _qwen_lease_lock(profile_id):
        state = _load_qwen_lease_state(profile_id)
        if state is None:
            state = {
                "contract_version": "qwen_model_server_lease_state_v1",
                "profile_id": profile_id,
                "profile": deepcopy(profile),
                "server_started_by_runtime": bool(readiness.get("started")),
                "leases": [],
            }
        state["server_started_by_runtime"] = bool(
            state.get("server_started_by_runtime") or readiness.get("started")
        )
        leases = state.get("leases")
        if not isinstance(leases, list):
            raise RuntimeError("Qwen model lease state is invalid")
        leases.append(deepcopy(lease))
        _write_qwen_lease_state(profile_id, state)
    return lease


def qwen_model_lease_is_active(model_lease: object) -> bool:
    if not isinstance(model_lease, dict):
        return False
    profile_id = str(model_lease.get("profile_id") or "")
    if not profile_id:
        return False
    with _qwen_lease_lock(profile_id):
        state = _load_qwen_lease_state(profile_id)
        return _find_exact_lease(state, model_lease) is not None


def release_qwen_model_server(
    *,
    sealed_artifact: dict[str, Any],
    omni_inventory: dict[str, Any],
    model_lease: dict[str, Any],
) -> dict[str, Any]:
    """验证完整绑定与精确租约后，仅释放本请求持有的服务引用。"""
    _validate_sealed_qwen_release_artifact(sealed_artifact, omni_inventory)
    if not isinstance(model_lease, dict):
        raise ValueError("exact Qwen model lease is required before release")
    profile_id = str(model_lease.get("profile_id") or "")
    with _qwen_lease_lock(profile_id):
        state = _load_qwen_lease_state(profile_id)
        exact = _find_exact_lease(state, model_lease)
        if exact is None:
            raise ValueError("exact Qwen model lease is not active")
        leases = state["leases"]
        remaining = [item for item in leases if item is not exact]
        if remaining:
            state["leases"] = remaining
            _write_qwen_lease_state(profile_id, state)
            return {
                "status": "released",
                "lease": deepcopy(model_lease),
                "shared_server_retained": True,
                "server_termination": "not_required_shared",
            }
        if not state.get("server_started_by_runtime"):
            _delete_qwen_lease_state(profile_id)
            return {
                "status": "released",
                "lease": deepcopy(model_lease),
                "shared_server_retained": True,
                "server_termination": "not_owned",
            }
        profile = state.get("profile")
        if not isinstance(profile, dict):
            raise RuntimeError("Qwen model lease profile is unavailable")
        stop_result = stop_model_server(profile)
        after = check_model_server(profile)
        if after.get("status") in _ACTIVE_SERVER_STATUSES:
            raise RuntimeError("Qwen model server is still running after release")
        _delete_qwen_lease_state(profile_id)
        return {
            "status": "released",
            "lease": deepcopy(model_lease),
            "shared_server_retained": False,
            "server_termination": "verified_stopped",
            "release": stop_result,
            "after": after,
        }


def _release_qwen_request_lease(
    *,
    profile_id: str,
    request_id: str,
    request_cancelled: bool,
) -> dict[str, Any]:
    with _qwen_lease_lock(profile_id):
        state = _load_qwen_lease_state(profile_id)
        leases = state.get("leases") if isinstance(state, dict) else None
        if not isinstance(leases, list):
            return {
                "status": "request_not_active",
                "model_service_compute_termination": "request_not_active",
                "shared_server_retained": True,
            }
        owned = [item for item in leases if item.get("owner_request_id") == request_id]
        if not owned:
            return {
                "status": "request_not_active",
                "model_service_compute_termination": "request_not_active",
                "shared_server_retained": True,
            }
        remaining = [item for item in leases if item not in owned]
        if remaining:
            if not request_cancelled:
                raise RuntimeError("request-specific cancellation is unavailable while Qwen server is shared")
            state["leases"] = remaining
            _write_qwen_lease_state(profile_id, state)
            return {
                "status": "terminated",
                "model_service_compute_termination": "terminated",
                "lease": deepcopy(owned[0]),
                "shared_server_retained": True,
                "server_termination": "not_required_shared",
            }
        if not state.get("server_started_by_runtime"):
            if not request_cancelled:
                raise RuntimeError("request-specific cancellation is unavailable for an externally owned Qwen server")
            _delete_qwen_lease_state(profile_id)
            return {
                "status": "terminated",
                "model_service_compute_termination": "terminated",
                "lease": deepcopy(owned[0]),
                "shared_server_retained": True,
                "server_termination": "not_owned_request_cancelled",
            }
        profile = state.get("profile")
        if not isinstance(profile, dict):
            raise RuntimeError("Qwen model lease profile is unavailable")
        release = stop_model_server(profile)
        after = check_model_server(profile)
        if after.get("status") in _ACTIVE_SERVER_STATUSES:
            raise RuntimeError("Qwen model server is still running after cancellation")
        _delete_qwen_lease_state(profile_id)
        return {
            "status": "terminated",
            "model_service_compute_termination": "terminated",
            "lease": deepcopy(owned[0]),
            "shared_server_retained": False,
            "server_termination": "verified_stopped",
            "release": release,
            "after": after,
        }


def _validate_sealed_qwen_release_artifact(
    sealed_artifact: object,
    omni_inventory: object,
) -> None:
    if not isinstance(omni_inventory, dict):
        raise ValueError("sealed Omni inventory is required before release")
    sealed_inventory = deepcopy(omni_inventory)
    inventory_digest = sealed_inventory.pop("content_sha256", None)
    if inventory_digest != content_sha256(omni_inventory):
        raise ValueError("sealed Omni inventory is required before release")
    inventory = validate_omni_inventory(sealed_inventory)
    if not isinstance(sealed_artifact, dict):
        raise ValueError("sealed Qwen binding artifact is required before release")
    artifact = deepcopy(sealed_artifact)
    artifact_digest = artifact.pop("content_sha256", None)
    if artifact_digest != content_sha256(sealed_artifact):
        raise ValueError("sealed Qwen binding artifact is required before release")
    try:
        from app.learn.hybrid.qwen_binding import parse_qwen_candidate_bindings

        parsed = parse_qwen_candidate_bindings(
            {
                "bindings": deepcopy(artifact.get("bindings")),
                "orphan_semantics": deepcopy(artifact.get("orphan_semantics")),
            },
            omni_inventory,
        )
        if parsed != artifact:
            raise ValueError("binding artifact does not match canonical parser output")
    except ValueError as error:
        raise ValueError(f"sealed Qwen binding artifact is invalid: {error}") from error


def _qwen_lease_state_path(profile_id: str) -> Path:
    digest = sha256(profile_id.encode("utf-8")).hexdigest()
    return MODEL_SERVER_LEASE_DIR / f"{digest}.json"


@contextmanager
def _qwen_lease_lock(profile_id: str):
    if not profile_id:
        raise ValueError("Qwen model lease profile_id is required")
    MODEL_SERVER_LEASE_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = _qwen_lease_state_path(profile_id).with_suffix(".lock")
    deadline = time.monotonic() + 5.0
    descriptor: int | None = None
    while descriptor is None:
        try:
            descriptor = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(descriptor, f"{os.getpid()} {time.time()}".encode("ascii"))
        except FileExistsError:
            try:
                if time.time() - lock_path.stat().st_mtime > 30.0:
                    lock_path.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise RuntimeError("Qwen model lease lock timed out")
            time.sleep(0.01)
    try:
        yield
    finally:
        os.close(descriptor)
        lock_path.unlink(missing_ok=True)


def _load_qwen_lease_state(profile_id: str) -> dict[str, Any] | None:
    path = _qwen_lease_state_path(profile_id)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("Qwen model lease state is unreadable") from error
    if not isinstance(value, dict) or value.get("profile_id") != profile_id:
        raise RuntimeError("Qwen model lease state identity mismatch")
    return value


def _write_qwen_lease_state(profile_id: str, state: dict[str, Any]) -> None:
    path = _qwen_lease_state_path(profile_id)
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _delete_qwen_lease_state(profile_id: str) -> None:
    _qwen_lease_state_path(profile_id).unlink(missing_ok=True)


def _find_exact_lease(
    state: dict[str, Any] | None,
    model_lease: dict[str, Any],
) -> dict[str, Any] | None:
    leases = state.get("leases") if isinstance(state, dict) else None
    if not isinstance(leases, list):
        return None
    for lease in leases:
        if isinstance(lease, dict) and lease == model_lease:
            return lease
    return None


def _qwen_acquired_profile_for_request(
    profile_id: str,
    request_id: str,
) -> dict[str, Any] | None:
    with _qwen_lease_lock(profile_id):
        state = _load_qwen_lease_state(profile_id)
        leases = state.get("leases") if isinstance(state, dict) else None
        if not isinstance(leases, list) or not any(
            isinstance(item, dict) and item.get("owner_request_id") == request_id
            for item in leases
        ):
            return None
        profile = state.get("profile")
        return deepcopy(profile) if isinstance(profile, dict) else None


def _profile_for_qwen_model_lease(model_lease: object) -> dict[str, Any]:
    if not isinstance(model_lease, dict):
        raise ValueError("exact Qwen model lease is required")
    profile_id = str(model_lease.get("profile_id") or "")
    with _qwen_lease_lock(profile_id):
        state = _load_qwen_lease_state(profile_id)
        if _find_exact_lease(state, model_lease) is None:
            raise ValueError("exact Qwen model lease is not active")
        profile = state.get("profile") if isinstance(state, dict) else None
        if not isinstance(profile, dict):
            raise RuntimeError("Qwen model lease profile is unavailable")
        return deepcopy(profile)


def _cancel_profile_request(
    *,
    profile: dict[str, Any],
    request_id: str,
    timeout: float,
    verify_seconds: float,
) -> dict[str, Any]:
    profile_id = str(profile.get("profile_id") or "unknown")
    endpoint = str(profile.get("request_cancel_endpoint") or "").strip()
    body = json.dumps({"request_id": request_id}).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            acknowledgement = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {
            "profile_id": profile_id,
            "status": "cancel_failed",
            "model_service_compute_termination": "cancel_failed",
            "error": str(exc),
        }

    acknowledgement_status = str(acknowledgement.get("status") or "").strip()
    if acknowledgement_status == "request_not_active":
        return {
            "profile_id": profile_id,
            "status": "request_not_active",
            "model_service_compute_termination": "request_not_active",
            "acknowledgement": acknowledgement,
        }
    if acknowledgement_status != "cancellation_acknowledged":
        return {
            "profile_id": profile_id,
            "status": "cancel_failed",
            "model_service_compute_termination": "cancel_failed",
            "acknowledgement": acknowledgement,
        }

    deadline = time.monotonic() + max(0.0, float(verify_seconds))
    last_health: dict[str, Any] | None = None
    while True:
        server_status = check_model_server(profile, timeout=timeout)
        health = server_status.get("health")
        last_health = health if isinstance(health, dict) else None
        active_request = (
            last_health.get("active_request")
            if isinstance(last_health, dict)
            else None
        )
        active_request_id = (
            str(active_request.get("request_id") or "")
            if isinstance(active_request, dict)
            else ""
        )
        if active_request_id != request_id:
            return {
                "profile_id": profile_id,
                "status": "terminated",
                "model_service_compute_termination": "terminated",
                "acknowledgement": acknowledgement,
                "health": last_health,
            }
        if time.monotonic() >= deadline:
            break
        time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))
    return {
        "profile_id": profile_id,
        "status": "cancellation_acknowledged_pending",
        "model_service_compute_termination": "cancellation_acknowledged_pending",
        "acknowledgement": acknowledgement,
        "health": last_health,
    }


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
    pid_path = model_profile_pid_path(profile)
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
    target = pid_path or model_profile_pid_path(profile)
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


def model_profile_pid_path(
    profile: dict[str, Any],
    *,
    root_dir: Path | None = None,
) -> Path:
    root = root_dir or ROOT_DIR
    pid_file = str(profile.get("pid_file") or "").strip()
    if pid_file:
        candidate = Path(pid_file)
        return candidate if candidate.is_absolute() else root / candidate
    profile_id = str(profile.get("profile_id") or "local-vision").strip() or "local-vision"
    safe_id = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in profile_id)
    return root / "logs" / f"{safe_id}-server.pid"


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
