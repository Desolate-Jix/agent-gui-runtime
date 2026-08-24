from __future__ import annotations

import base64
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
import os
import psutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from app.learn.hybrid.contracts import validate_omni_inventory
from app.learn.recognition.uei.canonical import content_sha256, seal_immutable

ROOT_DIR = Path(__file__).resolve().parents[2]
MODEL_PROFILE_DIR = ROOT_DIR / "configs" / "model_profiles"
MODEL_SERVER_LEASE_DIR = ROOT_DIR / "logs" / "model_server_leases"
_QWEN_HTTP_RESPONSE_MAX_BYTES = 1024 * 1024
_ACTIVE_SERVER_STATUSES = {"running", "loading", "busy"}
_QWEN_LOCAL_LEASE_LOCK = threading.Lock()
_QWEN_LOCAL_ACQUISITION_LOCK = threading.Lock()
_QWEN_PROCESS_TERMINATE_SECONDS = 3.0
_QWEN_PROCESS_KILL_SECONDS = 2.0
_QWEN_LEASE_FIELDS = {
    "contract_version",
    "lease_id",
    "owner_request_id",
    "profile_id",
    "incarnation_id",
    "server_base_url",
    "server_model_id",
    "profile_sha256",
    "server_process_identity",
}


class QwenModelRequestTimeout(TimeoutError):
    """Qwen HTTP 请求在适配器边界统一归类为超时。"""


class QwenModelRequestCancelled(RuntimeError):
    """Qwen HTTP 请求由精确受管请求取消。"""

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
    owner_record = _find_qwen_owner_record(normalized_request_id)
    if owner_record is not None or str(task_kind or "").strip() == "panel_learning_hybrid_qwen_binding":
        if owner_record is None or owner_record["kind"] == "tombstone":
            receipt = (
                deepcopy(owner_record["receipt"])
                if owner_record is not None
                else {
                    "contract_version": "qwen_model_request_owner_receipt_v1",
                    "status": "not_found",
                    "owner_request_id": normalized_request_id,
                }
            )
            return {
                "contract_version": "model_request_cancellation_v1",
                "status": "request_not_active",
                "request_id": normalized_request_id,
                "model_service_compute_termination": "request_not_active",
                "provider_results": [{
                    "profile_id": receipt.get("profile_id", "qwen"),
                    "status": "request_not_active",
                    "model_service_compute_termination": "request_not_active",
                    "server_termination": receipt.get("server_termination", "not_required"),
                    "owner_receipt": receipt,
                }],
            }
        owner = (owner_record["state"], owner_record["lease"])
        owner_profile = owner[0].get("profile")
        matching_profiles = [deepcopy(owner_profile)] if isinstance(owner_profile, dict) else []
    else:
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
        if owner_record is not None:
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
        return []
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
            request_id=request_id,
            request_cancelled=True,
        )
        return {**request_result, **lease_release}

    try:
        lease_release = _release_qwen_request_lease(
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
        raise QwenModelRequestCancelled("Qwen binding request cancelled")
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
    if model_lease is not None:
        _mark_qwen_model_request_in_flight(model_lease)
    try:
        with urllib.request.urlopen(http_request, timeout=float(timeout_seconds)) as response:
            response_bytes = response.read(_QWEN_HTTP_RESPONSE_MAX_BYTES + 1)
            if len(response_bytes) > _QWEN_HTTP_RESPONSE_MAX_BYTES:
                raise ValueError("Qwen HTTP response byte limit exceeded")
            if model_lease is not None:
                _mark_qwen_model_compute_complete(model_lease)
            response_payload = json.loads(response_bytes.decode("utf-8"))
    except (TimeoutError, QwenModelRequestTimeout) as error:
        raise QwenModelRequestTimeout("Qwen binding request timed out") from error
    except urllib.error.URLError as error:
        if cancellation_event is not None and cancellation_event.is_set():
            raise QwenModelRequestCancelled("Qwen binding request cancelled") from error
        if isinstance(error.reason, TimeoutError):
            raise QwenModelRequestTimeout("Qwen binding request timed out") from error
        raise RuntimeError(f"Qwen binding request failed: {error}") from error
    except (ValueError, UnicodeError):
        raise
    except Exception as error:
        if cancellation_event is not None and cancellation_event.is_set():
            raise QwenModelRequestCancelled("Qwen binding request cancelled") from error
        raise RuntimeError(f"Qwen binding request failed: {error}") from error
    if cancellation_event is not None and cancellation_event.is_set():
        raise QwenModelRequestCancelled("Qwen binding request cancelled")
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


def ensure_and_acquire_qwen_model_lease(
    *,
    stage: str,
    profile_id: str | None,
    request_id: str,
    wait_seconds: float,
    profile_validator: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """跨进程串行化 Qwen 首启与租约发布，避免无主启动副作用。"""
    with _qwen_acquisition_lock():
        profile = deepcopy(profile_for_stage(stage, profile_id))
        if profile_validator is not None:
            profile_validator(deepcopy(profile))
        readiness = _ensure_model_server_for_profile(
            profile=profile,
            stage=stage,
            wait_until_ready=True,
            wait_seconds=wait_seconds,
        )
        after = readiness.get("after")
        before = readiness.get("before")
        status = str(
            (after.get("status") if isinstance(after, dict) else "")
            or (before.get("status") if isinstance(before, dict) else "")
        ).strip()
        if status != "running":
            raise RuntimeError(
                f"Qwen model service is not ready for lease publication: {status or 'unknown'}"
            )
        if readiness.get("profile") != _public_profile(profile):
            raise RuntimeError("Qwen readiness profile does not match acquisition snapshot")
        return acquire_qwen_model_lease(
            profile=profile,
            request_id=request_id,
            readiness=readiness,
        )


def acquire_qwen_model_lease(
    *,
    profile: dict[str, Any],
    request_id: str,
    readiness: dict[str, Any],
) -> dict[str, Any]:
    profile_id = str(profile.get("profile_id") or "").strip()
    owner_request_id = str(request_id or "").strip()
    if not profile_id or not owner_request_id:
        raise ValueError("Qwen model lease identity is incomplete")
    incarnation = _qwen_server_incarnation(profile, readiness)
    with _qwen_lease_lock():
        for existing in _load_all_qwen_lease_states():
            if not existing["leases"]:
                continue
            existing_incarnation = existing["incarnation"]
            same_listener_process = (
                existing_incarnation.get("server_process_identity")
                == incarnation["server_process_identity"]
            )
            if same_listener_process and existing_incarnation.get("incarnation_id") != incarnation["incarnation_id"]:
                raise RuntimeError("Qwen exact process is partitioned across ownership domains")
            if same_listener_process and not _compatible_qwen_incarnations(
                existing_incarnation,
                incarnation,
            ):
                raise ValueError("Qwen server incarnation mismatch for exact process lease")
            if existing["profile_id"] == profile_id and not same_listener_process:
                raise ValueError("Qwen server incarnation mismatch for existing profile lease")
        state = _load_qwen_lease_state(incarnation["incarnation_id"])
        if state is None:
            state = {
                "contract_version": "qwen_model_server_lease_state_v2",
                "profile_id": profile_id,
                "profile": deepcopy(profile),
                "incarnation": incarnation,
                "server_started_by_runtime": bool(readiness.get("started")),
                "revision": 0,
                "finalization": None,
                "leases": [],
            }
        elif not _compatible_qwen_incarnations(state["incarnation"], incarnation):
            raise ValueError("Qwen server incarnation mismatch")
        else:
            incarnation = deepcopy(state["incarnation"])
        lease = {
            "contract_version": "qwen_model_server_lease_v2",
            "lease_id": uuid4().hex,
            "owner_request_id": owner_request_id,
            "profile_id": profile_id,
            "incarnation_id": incarnation["incarnation_id"],
            "server_base_url": incarnation["server_base_url"],
            "server_model_id": incarnation["server_model_id"],
            "profile_sha256": content_sha256(_public_profile(profile)),
            "server_process_identity": deepcopy(incarnation["server_process_identity"]),
        }
        if state.get("finalization") is not None:
            raise RuntimeError("Qwen server incarnation finalization is pending")
        if any(item.get("owner_request_id") == owner_request_id for item in state["leases"]):
            raise ValueError("Qwen request already owns a server lease")
        state["server_started_by_runtime"] = bool(
            state.get("server_started_by_runtime") or readiness.get("started")
        )
        state["revision"] = int(state.get("revision") or 0) + 1
        state["leases"].append({**deepcopy(lease), "lifecycle_state": "not_started"})
        _write_qwen_lease_state(state)
    return lease


def qwen_model_lease_is_active(model_lease: object) -> bool:
    if not isinstance(model_lease, dict):
        return False
    incarnation_id = str(model_lease.get("incarnation_id") or "")
    if not incarnation_id:
        return False
    with _qwen_lease_lock():
        state = _load_qwen_lease_state(incarnation_id)
        return _find_exact_lease(state, model_lease) is not None


def release_qwen_model_server(
    *,
    sealed_artifact: dict[str, Any],
    omni_inventory: dict[str, Any],
    model_lease: dict[str, Any],
) -> dict[str, Any]:
    _validate_sealed_qwen_release_artifact(sealed_artifact, omni_inventory)
    return _release_exact_qwen_lease(model_lease, reason="completed")


def release_managed_qwen_model_lease(
    model_lease: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    """释放已完成的受管 Qwen 消费者租约，不绕过共享引用计数。"""
    _mark_qwen_model_compute_complete(model_lease)
    return _release_exact_qwen_lease(model_lease, reason=reason)


def reconcile_qwen_model_lease_failure(
    *,
    model_lease: dict[str, Any],
    compute_completed: bool,
    reason: str,
) -> dict[str, Any]:
    if compute_completed or _qwen_model_compute_is_complete(model_lease):
        return _release_exact_qwen_lease(model_lease, reason=reason)
    request_id = str(model_lease.get("owner_request_id") or "")
    return _release_qwen_request_lease(
        request_id=request_id,
        request_cancelled=False,
    )


def _release_exact_qwen_lease(
    model_lease: object,
    *,
    reason: str,
) -> dict[str, Any]:
    if not isinstance(model_lease, dict):
        raise ValueError("exact Qwen model lease is required before release")
    if set(model_lease) != _QWEN_LEASE_FIELDS:
        raise ValueError("exact Qwen model lease is required before release")
    incarnation_id = str(model_lease.get("incarnation_id") or "")
    with _qwen_lease_lock():
        state = _load_qwen_lease_state(incarnation_id)
        exact = _find_exact_lease(state, model_lease)
        if exact is None:
            receipt = _load_qwen_owner_tombstone(
                str(model_lease.get("owner_request_id") or "")
            )
            if (
                isinstance(receipt, dict)
                and receipt.get("lease_id") == model_lease.get("lease_id")
                and isinstance(receipt.get("release_result"), dict)
            ):
                return deepcopy(receipt["release_result"])
            raise ValueError("exact Qwen model lease is not active")
        finalization = state.get("finalization")
        if isinstance(finalization, dict):
            resume_state = deepcopy(state)
            resume_token = str(finalization.get("token") or "")
            resume_revision = int(finalization.get("revision") or 0)
        else:
            resume_state = None
            resume_token = ""
            resume_revision = 0
        if resume_state is None:
            remaining = [item for item in state["leases"] if item is not exact]
            if remaining:
                state["leases"] = remaining
                state["revision"] += 1
                result = {
                    "status": "released",
                    "lease": deepcopy(model_lease),
                    "shared_server_retained": True,
                    "server_termination": "not_required_shared",
                    "reason": reason,
                }
                _write_qwen_owner_tombstone(model_lease, result=result)
                _write_qwen_lease_state(state)
                return result
            if not state.get("server_started_by_runtime"):
                result = {
                    "status": "released",
                    "lease": deepcopy(model_lease),
                    "shared_server_retained": True,
                    "server_termination": "not_owned",
                    "reason": reason,
                }
                _write_qwen_owner_tombstone(model_lease, result=result)
                _delete_qwen_lease_state(incarnation_id)
                return result
            token = uuid4().hex
            state["revision"] += 1
            revision = state["revision"]
            state["finalization"] = {
                "token": token,
                "revision": revision,
                "lease_id": model_lease["lease_id"],
                "phase": "stop_pending",
                "reason": reason,
                "finalizer_pid": os.getpid(),
            }
            _write_qwen_lease_state(state)
            stop_state = deepcopy(state)
    if resume_state is not None:
        return _resume_qwen_finalization(
            resume_state,
            token=resume_token,
            revision=resume_revision,
            reason=reason,
        )
    return _stop_and_finalize_qwen_incarnation(stop_state, token=token, revision=revision)


def _stop_and_finalize_qwen_incarnation(
    state: dict[str, Any],
    *,
    token: str,
    revision: int,
) -> dict[str, Any]:
    incarnation = state["incarnation"]
    expected_process = incarnation["server_process_identity"]
    before = _probe_exact_qwen_process(expected_process)
    if before["status"] == "unobservable":
        _record_qwen_finalization_failure(state, token, revision, "process_identity_unobservable")
        raise RuntimeError("Qwen exact server process identity is unobservable before stop")
    if before["status"] == "proven_absent" and before.get("identity") is not None:
        _record_qwen_finalization_failure(state, token, revision, "ownership_changed")
        raise RuntimeError("Qwen server incarnation ownership changed before stop")
    if before["status"] == "proven_absent":
        release = before
    else:
        try:
            release = _terminate_exact_qwen_server_process(expected_process)
        except RuntimeError as error:
            failure_reason = str(getattr(error, "qwen_failure_reason", "stop_failed"))
            _record_qwen_finalization_failure(state, token, revision, failure_reason)
            raise
    if release.get("status") != "proven_absent":
        failure_reason = (
            "process_exit_unobservable"
            if release.get("status") == "unobservable"
            else "process_still_running"
        )
        _record_qwen_finalization_failure(state, token, revision, failure_reason)
        if failure_reason == "process_exit_unobservable":
            raise RuntimeError("Qwen exact server process exit is unobservable")
        raise RuntimeError("Qwen exact server process is still running after release")
    health = check_model_server(state["profile"])
    result = {
        "status": "released",
        "lease": _qwen_public_lease(state["leases"][0]),
        "shared_server_retained": False,
        "server_termination": "verified_exact_process_exited",
        "release": release,
        "after": health,
        "process_identity": expected_process,
    }
    _persist_qwen_termination_proof(
        state,
        token=token,
        revision=revision,
        result=result,
    )
    return _finish_qwen_finalization_cleanup(
        state["incarnation"]["incarnation_id"],
        token=token,
        revision=revision,
    )


def _persist_qwen_termination_proof(
    state: dict[str, Any],
    *,
    token: str,
    revision: int,
    result: dict[str, Any],
) -> None:
    incarnation_id = state["incarnation"]["incarnation_id"]
    with _qwen_lease_lock():
        current_state = _load_qwen_lease_state(incarnation_id)
        finalization = current_state.get("finalization") if isinstance(current_state, dict) else None
        if (
            not isinstance(finalization, dict)
            or finalization.get("token") != token
            or finalization.get("revision") != revision
        ):
            raise RuntimeError("Qwen finalization token changed")
        finalization["phase"] = "termination_proven"
        finalization["termination_result"] = deepcopy(result)
        current_state["revision"] = max(int(current_state.get("revision") or 0), revision)
        _write_qwen_lease_state(current_state)


def _finish_qwen_finalization_cleanup(
    incarnation_id: str,
    *,
    token: str,
    revision: int,
) -> dict[str, Any]:
    with _qwen_lease_lock():
        current_state = _load_qwen_lease_state(incarnation_id)
        finalization = current_state.get("finalization") if isinstance(current_state, dict) else None
        if (
            not isinstance(finalization, dict)
            or finalization.get("token") != token
            or finalization.get("revision") != revision
            or finalization.get("phase") != "termination_proven"
            or not isinstance(finalization.get("termination_result"), dict)
        ):
            raise RuntimeError("Qwen terminal finalization evidence is unavailable")
        result = deepcopy(finalization["termination_result"])
        lease = {key: deepcopy(current_state["leases"][0].get(key)) for key in _QWEN_LEASE_FIELDS}
        _write_qwen_owner_tombstone(
            lease,
            result=result,
            finalization_token=token,
        )
        _delete_qwen_lease_state(incarnation_id)
    return result


def _resume_qwen_finalization(
    state: dict[str, Any],
    *,
    token: str,
    revision: int,
    reason: str,
) -> dict[str, Any]:
    finalization = state.get("finalization")
    if isinstance(finalization, dict) and finalization.get("phase") == "termination_proven":
        return _finish_qwen_finalization_cleanup(
            state["incarnation"]["incarnation_id"],
            token=token,
            revision=revision,
        )
    if not isinstance(finalization, dict) or not isinstance(finalization.get("finalizer_pid"), int):
        return _qwen_finalization_pending_result(state, reason=reason)
    proof = _probe_exact_qwen_process(state["incarnation"]["server_process_identity"])
    if proof.get("status") != "proven_absent":
        return _qwen_finalization_pending_result(state, reason=reason)
    result = {
        "status": "released",
        "lease": {
            key: deepcopy(state["leases"][0].get(key)) for key in _QWEN_LEASE_FIELDS
        },
        "shared_server_retained": False,
        "server_termination": "verified_exact_process_proven_absent_on_retry",
        "release": proof,
        "after": check_model_server(state["profile"]),
        "process_identity": deepcopy(state["incarnation"]["server_process_identity"]),
    }
    _persist_qwen_termination_proof(
        state,
        token=token,
        revision=revision,
        result=result,
    )
    return _finish_qwen_finalization_cleanup(
        state["incarnation"]["incarnation_id"],
        token=token,
        revision=revision,
    )


def _qwen_finalization_pending_result(
    state: dict[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    lease = {key: deepcopy(state["leases"][0].get(key)) for key in _QWEN_LEASE_FIELDS}
    return {
        "status": "cancellation_acknowledged_pending",
        "model_service_compute_termination": "cancellation_acknowledged_pending",
        "lease": lease,
        "shared_server_retained": True,
        "server_termination": "finalization_pending",
        "finalization": deepcopy(state.get("finalization")),
        "reason": reason,
    }


def _record_qwen_finalization_failure(
    state: dict[str, Any],
    token: str,
    revision: int,
    reason: str,
) -> None:
    incarnation_id = state["incarnation"]["incarnation_id"]
    with _qwen_lease_lock():
        current = _load_qwen_lease_state(incarnation_id)
        finalization = current.get("finalization") if isinstance(current, dict) else None
        if isinstance(finalization, dict) and finalization.get("token") == token:
            finalization["phase"] = "owned_pending"
            finalization["failure_reason"] = reason
            current["revision"] = max(int(current.get("revision") or 0), revision)
            _write_qwen_lease_state(current)


def _mark_qwen_lease_pending(model_lease: object, *, reason: str) -> dict[str, Any]:
    if not isinstance(model_lease, dict):
        raise ValueError("exact Qwen model lease is required")
    incarnation_id = str(model_lease.get("incarnation_id") or "")
    with _qwen_lease_lock():
        state = _load_qwen_lease_state(incarnation_id)
        exact = _find_exact_lease(state, model_lease)
        if exact is None:
            return {"status": "request_not_active", "model_service_compute_termination": "request_not_active"}
        lifecycle_state = str(exact.get("lifecycle_state") or "not_started")
        if lifecycle_state == "compute_complete":
            raise RuntimeError("completed Qwen lease cannot be overwritten as pending")
        exact["pending_reason"] = str(reason)
        exact["capability_blocker"] = str(reason)
        exact["reconciliation_trigger"] = "worker_http_completion_or_explicit_retry"
        state["revision"] += 1
        _write_qwen_lease_state(state)
    return {
        "status": "cancellation_acknowledged_pending",
        "model_service_compute_termination": "cancellation_acknowledged_pending",
        "lease": deepcopy(model_lease),
        "shared_server_retained": True,
        "server_termination": "owned_pending",
        "pending_reason": str(reason),
        "capability_blocker": str(reason),
        "reconciliation_trigger": "worker_http_completion_or_explicit_retry",
        "lifecycle_state": lifecycle_state,
    }


def _mark_qwen_model_request_in_flight(model_lease: object) -> None:
    if not isinstance(model_lease, dict):
        raise ValueError("exact Qwen model lease is required")
    incarnation_id = str(model_lease.get("incarnation_id") or "")
    with _qwen_lease_lock():
        state = _load_qwen_lease_state(incarnation_id)
        exact = _find_exact_lease(state, model_lease)
        if exact is None:
            raise ValueError("exact Qwen model lease is not active")
        lifecycle_state = str(exact.get("lifecycle_state") or "not_started")
        if lifecycle_state == "compute_complete":
            return
        if lifecycle_state not in {"not_started", "request_in_flight"}:
            raise RuntimeError("Qwen request lifecycle state is invalid")
        exact["lifecycle_state"] = "request_in_flight"
        state["revision"] += 1
        _write_qwen_lease_state(state)


def _mark_qwen_model_compute_complete(model_lease: object) -> None:
    if not isinstance(model_lease, dict):
        return
    incarnation_id = str(model_lease.get("incarnation_id") or "")
    with _qwen_lease_lock():
        state = _load_qwen_lease_state(incarnation_id)
        exact = _find_exact_lease(state, model_lease)
        if exact is None:
            raise ValueError("exact Qwen model lease is not active")
        exact["lifecycle_state"] = "compute_complete"
        exact.pop("pending_reason", None)
        exact.pop("capability_blocker", None)
        exact.pop("reconciliation_trigger", None)
        state["revision"] += 1
        _write_qwen_lease_state(state)


def _qwen_model_compute_is_complete(model_lease: object) -> bool:
    if not isinstance(model_lease, dict):
        return False
    incarnation_id = str(model_lease.get("incarnation_id") or "")
    with _qwen_lease_lock():
        state = _load_qwen_lease_state(incarnation_id)
        exact = _find_exact_lease(state, model_lease)
        return bool(exact is not None and exact.get("lifecycle_state") == "compute_complete")


def _release_qwen_request_lease(
    *,
    request_id: str,
    request_cancelled: bool,
) -> dict[str, Any]:
    match = _find_qwen_lease_by_owner(request_id)
    if match is None:
        return {
            "status": "request_not_active",
            "model_service_compute_termination": "request_not_active",
            "shared_server_retained": True,
        }
    state, lease = match
    exact = _find_exact_lease(state, lease)
    if exact is None:
        raise RuntimeError("Qwen request lease changed during cancellation")
    lifecycle_state = str(exact.get("lifecycle_state") or "not_started")
    if not request_cancelled and lifecycle_state in {"not_started", "compute_complete"}:
        result = _release_exact_qwen_lease(
            {key: deepcopy(lease.get(key)) for key in _QWEN_LEASE_FIELDS},
            reason=(
                "explicit_retry_compute_complete"
                if lifecycle_state == "compute_complete"
                else "explicit_retry_no_dispatch"
            ),
        )
        if result.get("status") == "cancellation_acknowledged_pending":
            return result
        owner_receipt = _load_qwen_owner_tombstone(request_id)
        return {
            **result,
            "status": "request_not_active",
            "model_service_compute_termination": "request_not_active",
            "owner_receipt": deepcopy(owner_receipt),
        }
    if not request_cancelled and len(state["leases"]) > 1:
        return _mark_qwen_lease_pending(lease, reason="request_cancel_endpoint_unavailable")
    if not request_cancelled and not state.get("server_started_by_runtime"):
        return _mark_qwen_lease_pending(lease, reason="external_server_request_unproven")
    result = _release_exact_qwen_lease(lease, reason="cancelled")
    if result.get("status") == "cancellation_acknowledged_pending":
        return result
    return {
        **result,
        "status": "terminated",
        "model_service_compute_termination": "terminated",
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
    validate_omni_inventory(sealed_inventory)
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


def _qwen_server_incarnation(
    profile: dict[str, Any],
    readiness: dict[str, Any],
) -> dict[str, Any]:
    observed = readiness.get("after") if isinstance(readiness.get("after"), dict) else readiness.get("before")
    observed = observed if isinstance(observed, dict) else {}
    expected_model = str(profile.get("model_name") or profile.get("model_id") or "").strip()
    observed_model = str(observed.get("model_id") or "").strip()
    if expected_model and observed_model and expected_model != observed_model:
        raise RuntimeError("Qwen readiness model does not match acquisition profile")
    binding = _observe_qwen_server_binding(profile, readiness)
    if binding is None:
        raise RuntimeError("Qwen readiness endpoint does not match acquisition profile")
    process_identity = binding["server_process_identity"]
    server_socket = binding["server_socket"]
    body = {
        "profile_id": str(profile.get("profile_id") or ""),
        "profile_sha256": content_sha256(_public_profile(profile)),
        "server_endpoint": str(profile.get("endpoint") or ""),
        "server_base_url": _canonical_qwen_base_url(profile, observed, server_socket),
        "server_model_id": str(observed.get("model_id") or profile.get("model_name") or "") or None,
        "server_socket": deepcopy(server_socket),
        "server_process_identity": {
            "pid": int(process_identity["pid"]),
            "create_time_ns": int(process_identity["create_time_ns"]),
        },
    }
    ownership_identity = {
        "server_process_identity": body["server_process_identity"],
    }
    return {**body, "incarnation_id": content_sha256(ownership_identity)}


def _observe_qwen_server_process(
    profile: dict[str, Any],
    readiness: dict[str, Any],
) -> dict[str, int] | None:
    binding = _observe_qwen_server_binding(profile, readiness)
    return deepcopy(binding["server_process_identity"]) if binding is not None else None


def _observe_qwen_server_binding(
    profile: dict[str, Any],
    readiness: dict[str, Any],
) -> dict[str, Any] | None:
    observed = readiness.get("after") if isinstance(readiness.get("after"), dict) else readiness.get("before")
    observed = observed if isinstance(observed, dict) else {}
    resolved = _resolved_qwen_endpoint_addresses(profile, observed)
    if not resolved:
        return None
    explicit_identity = observed.get("server_process_identity")
    try:
        connections = list(psutil.net_connections(kind="tcp"))
    except (psutil.AccessDenied, OSError):
        return None
    owners: dict[int, set[tuple[str, int]]] = {}
    for connection in connections:
        address = connection.laddr
        if connection.status != psutil.CONN_LISTEN or not address or not connection.pid:
            continue
        socket_key = (str(address.ip), int(address.port))
        if socket_key in resolved:
            owners.setdefault(int(connection.pid), set()).add(socket_key)
    start = readiness.get("start")
    start = start if isinstance(start, dict) else {}
    service_pid = start.get("service_pid")
    if service_pid:
        try:
            expected_pid = int(service_pid)
        except (TypeError, ValueError):
            return None
        if set(owners) != {expected_pid}:
            return None
        identity = _current_process_identity(expected_pid)
        if not _valid_process_identity(identity):
            return None
        socket_key = sorted(owners[expected_pid])[0]
        return {
            "server_process_identity": identity,
            "server_socket": {"host": socket_key[0], "port": socket_key[1]},
        }
    if _valid_process_identity(explicit_identity):
        expected_pid = int(explicit_identity["pid"])
        if set(owners) != {expected_pid}:
            return None
        identity = _current_process_identity(expected_pid)
        if identity != explicit_identity:
            return None
        socket_key = sorted(owners[expected_pid])[0]
        return {
            "server_process_identity": identity,
            "server_socket": {"host": socket_key[0], "port": socket_key[1]},
        }
    if len(owners) != 1:
        return None
    pid, sockets = next(iter(owners.items()))
    identity = _current_process_identity(pid)
    if not _valid_process_identity(identity):
        return None
    socket_key = sorted(sockets)[0]
    return {
        "server_process_identity": identity,
        "server_socket": {"host": socket_key[0], "port": socket_key[1]},
    }


def _resolved_qwen_endpoint_addresses(
    profile: dict[str, Any],
    observed: dict[str, Any],
) -> set[tuple[str, int]]:
    profile_addresses = _resolved_qwen_url_addresses(model_base_url(profile))
    observed_addresses = _resolved_qwen_url_addresses(
        str(observed.get("base_url") or model_base_url(profile))
    )
    return profile_addresses.intersection(observed_addresses)


def _resolved_qwen_url_addresses(raw_url: str) -> set[tuple[str, int]]:
    parsed = urlsplit(raw_url)
    host = parsed.hostname
    port = parsed.port
    if not host:
        return set()
    if port is None:
        port = 443 if parsed.scheme.casefold() == "https" else 80
    try:
        values = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, OSError):
        return set()
    return {(str(value[4][0]), int(value[4][1])) for value in values}


def _valid_qwen_server_socket(value: object) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("host"), str)
        and bool(value["host"])
        and isinstance(value.get("port"), int)
        and value["port"] > 0
    )


def _canonical_qwen_base_url(
    profile: dict[str, Any],
    observed: dict[str, Any],
    server_socket: dict[str, Any],
) -> str:
    parsed = urlsplit(str(observed.get("base_url") or model_base_url(profile)))
    host = str(server_socket["host"])
    bracketed_host = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return urlunsplit(
        (
            parsed.scheme.casefold() or "http",
            f"{bracketed_host}:{int(server_socket['port'])}",
            parsed.path.rstrip("/"),
            "",
            "",
        )
    )


def _compatible_qwen_incarnations(
    first: dict[str, Any],
    second: dict[str, Any],
) -> bool:
    if first.get("server_process_identity") != second.get("server_process_identity"):
        return False
    if first.get("server_socket") != second.get("server_socket"):
        return False
    first_model = str(first.get("server_model_id") or "")
    second_model = str(second.get("server_model_id") or "")
    return not first_model or not second_model or first_model == second_model


def _current_process_identity(pid: object) -> dict[str, int] | None:
    try:
        process = psutil.Process(int(pid))
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            return None
        return {
            "pid": int(process.pid),
            "create_time_ns": int(round(process.create_time() * 1_000_000_000)),
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError, TypeError, OSError):
        return None


def _probe_exact_qwen_process(expected: dict[str, int]) -> dict[str, Any]:
    """区分精确存活、已证实不存在与当前不可观测三种状态。"""
    try:
        process = psutil.Process(int(expected["pid"]))
        if not process.is_running() or process.status() == psutil.STATUS_ZOMBIE:
            return {"status": "proven_absent", "identity": None, "reason": "not_running"}
        identity = {
            "pid": int(process.pid),
            "create_time_ns": int(round(process.create_time() * 1_000_000_000)),
        }
    except psutil.NoSuchProcess:
        return {"status": "proven_absent", "identity": None, "reason": "no_such_process"}
    except (psutil.AccessDenied, OSError) as error:
        return {
            "status": "unobservable",
            "identity": None,
            "reason": type(error).__name__,
        }
    except (ValueError, TypeError) as error:
        return {
            "status": "unobservable",
            "identity": None,
            "reason": type(error).__name__,
        }
    if identity != expected:
        return {"status": "proven_absent", "identity": identity, "reason": "pid_reused"}
    return {"status": "exact_live", "identity": identity}


def _terminate_exact_qwen_server_process(
    expected: dict[str, int],
) -> dict[str, Any]:
    """仅终止已验证 PID+创建时间的进程，不按端口或 PID 文件扩大。"""
    before = _probe_exact_qwen_process(expected)
    if before["status"] != "exact_live":
        return before
    try:
        process = psutil.Process(int(expected["pid"]))
        identity = {
            "pid": int(process.pid),
            "create_time_ns": int(round(process.create_time() * 1_000_000_000)),
        }
        if identity != expected or not process.is_running():
            return _probe_exact_qwen_process(expected)
        process.terminate()
        try:
            process.wait(timeout=_QWEN_PROCESS_TERMINATE_SECONDS)
        except psutil.TimeoutExpired:
            before_kill = _probe_exact_qwen_process(expected)
            if before_kill["status"] != "exact_live":
                return before_kill
            process.kill()
            process.wait(timeout=_QWEN_PROCESS_KILL_SECONDS)
    except psutil.NoSuchProcess:
        return {"status": "proven_absent", "identity": None, "reason": "no_such_process"}
    except (psutil.AccessDenied, OSError) as error:
        return {
            "status": "unobservable",
            "identity": None,
            "reason": type(error).__name__,
        }
    except psutil.TimeoutExpired:
        return _probe_exact_qwen_process(expected)
    return _probe_exact_qwen_process(expected)


def _valid_process_identity(value: object) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("pid"), int)
        and value["pid"] > 0
        and isinstance(value.get("create_time_ns"), int)
        and value["create_time_ns"] > 0
    )


def _qwen_lease_state_path(incarnation_id: str) -> Path:
    return MODEL_SERVER_LEASE_DIR / f"{incarnation_id}.json"


def _qwen_owner_tombstone_path(request_id: str) -> Path:
    digest = sha256(request_id.encode("utf-8")).hexdigest()
    return MODEL_SERVER_LEASE_DIR / "finalized_owners" / f"{digest}.json"


@contextmanager
def _exclusive_qwen_file_lock(local_lock: threading.Lock, lock_name: str):
    MODEL_SERVER_LEASE_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = MODEL_SERVER_LEASE_DIR / lock_name
    with local_lock:
        handle = lock_path.open("a+b")
        try:
            if lock_path.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


@contextmanager
def _qwen_acquisition_lock():
    with _exclusive_qwen_file_lock(
        _QWEN_LOCAL_ACQUISITION_LOCK,
        ".acquisition-transaction.lock",
    ):
        yield


@contextmanager
def _qwen_lease_lock():
    with _exclusive_qwen_file_lock(_QWEN_LOCAL_LEASE_LOCK, ".lease-state.lock"):
        yield


def _load_qwen_lease_state(incarnation_id: str) -> dict[str, Any] | None:
    if not incarnation_id:
        return None
    path = _qwen_lease_state_path(incarnation_id)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("Qwen model lease state is unreadable") from error
    if not isinstance(value, dict) or value.get("content_sha256") != content_sha256(value):
        raise RuntimeError("Qwen model lease state seal mismatch")
    value = deepcopy(value)
    value.pop("content_sha256")
    if (
        value.get("contract_version") != "qwen_model_server_lease_state_v2"
        or value.get("incarnation", {}).get("incarnation_id") != incarnation_id
        or not isinstance(value.get("leases"), list)
        or not isinstance(value.get("revision"), int)
    ):
        raise RuntimeError("Qwen model lease state identity mismatch")
    return value


def _load_all_qwen_lease_states() -> list[dict[str, Any]]:
    states = []
    if not MODEL_SERVER_LEASE_DIR.exists():
        return states
    for path in MODEL_SERVER_LEASE_DIR.glob("*.json"):
        state = _load_qwen_lease_state(path.stem)
        if state is not None:
            states.append(state)
    return states


def _write_qwen_lease_state(state: dict[str, Any]) -> None:
    incarnation_id = state["incarnation"]["incarnation_id"]
    path = _qwen_lease_state_path(incarnation_id)
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    sealed = seal_immutable(state)
    temporary.write_text(
        json.dumps(sealed, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _delete_qwen_lease_state(incarnation_id: str) -> None:
    _qwen_lease_state_path(incarnation_id).unlink(missing_ok=True)


def _write_qwen_owner_tombstone(
    model_lease: dict[str, Any],
    *,
    result: dict[str, Any],
    finalization_token: str | None = None,
) -> None:
    request_id = str(model_lease.get("owner_request_id") or "")
    if not request_id:
        raise ValueError("Qwen owner request identity is required")
    path = _qwen_owner_tombstone_path(request_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    receipt = {
        "contract_version": "qwen_model_request_owner_receipt_v1",
        "status": "finalized",
        "owner_request_id": request_id,
        "profile_id": model_lease.get("profile_id"),
        "lease_id": model_lease.get("lease_id"),
        "incarnation_id": model_lease.get("incarnation_id"),
        "server_termination": result.get("server_termination"),
        "release_result": deepcopy(result),
        "finalization_token": finalization_token,
    }
    existing = _load_qwen_owner_tombstone(request_id)
    if existing is not None:
        if (
            existing.get("lease_id") != receipt["lease_id"]
            or existing.get("incarnation_id") != receipt["incarnation_id"]
            or existing.get("finalization_token") != finalization_token
            or existing.get("release_result") != receipt["release_result"]
        ):
            raise RuntimeError("Qwen owner receipt conflicts with finalized ownership")
        return
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(
            seal_immutable(receipt),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _load_qwen_owner_tombstone(request_id: str) -> dict[str, Any] | None:
    if not request_id:
        return None
    path = _qwen_owner_tombstone_path(request_id)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError("Qwen owner receipt is unreadable") from error
    if not isinstance(value, dict) or value.get("content_sha256") != content_sha256(value):
        raise RuntimeError("Qwen owner receipt seal mismatch")
    receipt = deepcopy(value)
    receipt.pop("content_sha256")
    if (
        receipt.get("contract_version") != "qwen_model_request_owner_receipt_v1"
        or receipt.get("owner_request_id") != request_id
        or receipt.get("status") != "finalized"
    ):
        raise RuntimeError("Qwen owner receipt identity mismatch")
    return receipt


def _find_exact_lease(
    state: dict[str, Any] | None,
    model_lease: dict[str, Any],
) -> dict[str, Any] | None:
    if set(model_lease) != _QWEN_LEASE_FIELDS:
        return None
    leases = state.get("leases") if isinstance(state, dict) else None
    if not isinstance(leases, list):
        return None
    for lease in leases:
        if isinstance(lease, dict) and all(lease.get(key) == value for key, value in model_lease.items()):
            return lease
    return None


def _find_qwen_lease_by_owner(
    request_id: str,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    with _qwen_lease_lock():
        matches = []
        for state in _load_all_qwen_lease_states():
            for lease in state["leases"]:
                if isinstance(lease, dict) and lease.get("owner_request_id") == request_id:
                    matches.append((state, _qwen_public_lease(lease)))
        if len(matches) > 1:
            raise RuntimeError("Qwen request ownership is ambiguous")
        return matches[0] if matches else None


def _find_qwen_owner_record(request_id: str) -> dict[str, Any] | None:
    with _qwen_lease_lock():
        matches = []
        for state in _load_all_qwen_lease_states():
            for lease in state["leases"]:
                if isinstance(lease, dict) and lease.get("owner_request_id") == request_id:
                    matches.append((state, _qwen_public_lease(lease)))
        if len(matches) > 1:
            raise RuntimeError("Qwen request ownership is ambiguous")
        if matches:
            return {"kind": "active", "state": matches[0][0], "lease": matches[0][1]}
        receipt = _load_qwen_owner_tombstone(request_id)
        if receipt is not None:
            return {"kind": "tombstone", "receipt": receipt}
        return None


def _qwen_public_lease(lease: dict[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(lease.get(key)) for key in _QWEN_LEASE_FIELDS}


def _profile_for_qwen_model_lease(model_lease: object) -> dict[str, Any]:
    if not isinstance(model_lease, dict):
        raise ValueError("exact Qwen model lease is required")
    incarnation_id = str(model_lease.get("incarnation_id") or "")
    with _qwen_lease_lock():
        state = _load_qwen_lease_state(incarnation_id)
        if _find_exact_lease(state, model_lease) is None:
            raise ValueError("exact Qwen model lease is not active")
        profile = state.get("profile") if isinstance(state, dict) else None
        expected_process = (
            deepcopy(state.get("incarnation", {}).get("server_process_identity"))
            if isinstance(state, dict)
            else None
        )
        if not isinstance(profile, dict):
            raise RuntimeError("Qwen model lease profile is unavailable")
        acquired_profile = deepcopy(profile)
    if (
        not _valid_process_identity(expected_process)
        or _current_process_identity(expected_process["pid"]) != expected_process
    ):
        raise RuntimeError("Qwen server incarnation ownership changed before request")
    return acquired_profile


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
    return _ensure_model_server_for_profile(
        profile=profile,
        stage=stage,
        wait_until_ready=wait_until_ready,
        wait_seconds=wait_seconds,
    )


def _ensure_model_server_for_profile(
    *,
    profile: dict[str, Any],
    stage: str,
    wait_until_ready: bool,
    wait_seconds: float,
) -> dict[str, Any]:
    """使用同一不可变 profile 快照完成检查、启动与就绪。"""
    profile = deepcopy(profile)
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
