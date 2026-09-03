from __future__ import annotations

import base64
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
import math
import os
import psutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from app.learn.hybrid.contracts import validate_omni_inventory
from app.learn.recognition.uei.canonical import canonical_json_bytes, content_sha256, seal_immutable

ROOT_DIR = Path(__file__).resolve().parents[2]
MODEL_PROFILE_DIR = ROOT_DIR / "configs" / "model_profiles"
MODEL_SERVER_LEASE_DIR = ROOT_DIR / "logs" / "model_server_leases"
_QWEN_HTTP_RESPONSE_MAX_BYTES = 1024 * 1024
_SIMPLE_NATIVE_HTTP_REQUEST_MAX_BYTES = 32 * 1024 * 1024
_ACTIVE_SERVER_STATUSES = {"running", "loading", "busy"}
_QWEN_LOCAL_LEASE_LOCK = threading.Lock()
_QWEN_LOCAL_ACQUISITION_LOCK = threading.Lock()
_QWEN_PROCESS_TERMINATE_SECONDS = 3.0
_QWEN_PROCESS_KILL_SECONDS = 2.0
_QWEN_LEASE_STATE_CONTRACT = "qwen_model_server_lease_state_v3"
_QWEN_LEGACY_LEASE_STATE_CONTRACT = "qwen_model_server_lease_state_v2"
_QWEN_LIFECYCLE_STATES = {
    "not_started",
    "request_in_flight",
    "compute_complete",
    "unknown_in_flight",
}
_QWEN_UNPROVEN_FINALIZATION_PHASES = {"stop_pending", "owned_pending"}
_MANAGED_QWEN_TASK_KINDS = {
    "panel_learning_recognition_trial",
    "panel_learning_two_stage_understanding",
    "panel_learning_model_review_repair",
    "panel_learning_hybrid_qwen_binding",
    "vision_observe_screen",
}
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
_QWEN_RUNTIME_OWNER_FIELDS = {
    "contract_version",
    "authority_kind",
    "run_id",
    "stage",
    "operation_id",
    "worker_id",
    "model_request_id",
    "reservation_ref",
    "payload_sha256",
    "content_sha256",
}
_QWEN_MATERIALIZATION_LEDGER_FIELDS = {
    "contract_version",
    "model_request_id",
    "acquisition_intent_ref",
    "runtime_owner_ref",
    "state",
    "revision",
    "transition",
    "predecessor_content_sha256",
    "content_sha256",
}
_QWEN_CLEANUP_RECEIPT_FIELDS = {
    "contract_version",
    "outcome",
    "model_request_id",
    "acquisition_intent_ref",
    "runtime_owner_ref",
    "lease_ref",
    "profile_ref",
    "server_process_identity",
    "socket_ref",
    "job_scope_ref",
    "finalization_token",
    "lease_state_ref",
    "owner_tombstone_ref",
    "release_reason",
    "termination_observation_ref",
    "scope_stable_zero_ref",
    "listener_stable_zero_ref",
    "no_active_lease_observation_ref",
    "no_owned_runtime_observation_ref",
    "content_sha256",
}
_QWEN_OWNER_TOMBSTONE_FIELDS = {
    "contract_version",
    "status",
    "owner_request_id",
    "profile_id",
    "lease_id",
    "incarnation_id",
    "server_termination",
    "release_result",
    "finalization_token",
}
_QWEN_SCOPE_CLEANUP_FIELDS = {
    "contract_version",
    "scope_name",
    "authority",
    "scope_absent_after_owner_close",
    "cleanup_status",
    "observed_member_pids_before",
    "observed_member_identities_before",
    "member_pids_after",
    "member_identities_after",
    "active_listeners_after",
    "pid_file_after",
    "stable_zero_observations",
    "samples",
}


class QwenModelRequestTimeout(TimeoutError):
    """Qwen HTTP 请求在适配器边界统一归类为超时。"""


class QwenModelRequestCancelled(RuntimeError):
    """Qwen HTTP 请求由精确受管请求取消。"""


class HybridModelLaunchCleanupError(RuntimeError):
    """Hybrid 模型启动后的句柄清理无法证明为完成。"""

    def __init__(self, evidence: dict[str, Any]) -> None:
        super().__init__("Hybrid model launch handle cleanup is indeterminate")
        self.cleanup_evidence = deepcopy(evidence)

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
    if owner_record is not None or str(task_kind or "").strip() in _MANAGED_QWEN_TASK_KINDS:
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


def _qwen_binding_response_schema(request: Mapping[str, Any]) -> dict[str, Any]:
    """把当前候选闭集投影为 llama.cpp 可执行的 JSON Schema。"""
    raw_candidates = request.get("candidates")
    if not isinstance(raw_candidates, list):
        raise ValueError("Qwen binding request candidates must be a list")
    candidate_ids: list[str] = []
    for candidate in raw_candidates:
        candidate_id = candidate.get("candidate_id") if isinstance(candidate, Mapping) else None
        if not isinstance(candidate_id, str) or not candidate_id.startswith("candidate/"):
            raise ValueError("Qwen binding request candidates contain invalid candidate_id")
        if candidate_id in candidate_ids:
            raise ValueError("Qwen binding request candidates contain duplicate candidate_id")
        candidate_ids.append(candidate_id)

    binding_fields = [
        "candidate_id",
        "role",
        "label",
        "binding_status",
        "confidence",
    ]

    def _binding_schema(candidate_id: str) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "candidate_id": {"const": candidate_id},
                "role": {"type": "string", "minLength": 1, "maxLength": 64},
                "label": {"type": "string", "minLength": 1, "maxLength": 256},
                "binding_status": {
                    "enum": ["BOUND", "UNBOUND", "AMBIGUOUS", "CONFLICT"]
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": binding_fields,
            "additionalProperties": False,
        }

    return {
        "type": "object",
        "properties": {
            "bindings": {
                "type": "array",
                "prefixItems": [
                    _binding_schema(candidate_id) for candidate_id in candidate_ids
                ],
                "minItems": len(candidate_ids),
                "maxItems": len(candidate_ids),
            },
        },
        "required": ["bindings"],
        "additionalProperties": False,
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
        "Act only as a semantic classifier and binder for the supplied candidate_id values. Return exactly one "
        "JSON object with the single top-level field bindings. Every supplied candidate_id must appear exactly "
        "once in the given order. Each binding may contain only candidate_id, role, label, binding_status, and "
        "confidence. binding_status must be BOUND, UNBOUND, AMBIGUOUS, or CONFLICT. Do not output descriptions, "
        "reasoning, explanations, relationships, geometry, action authority, new candidate IDs, or prose. "
        "Canonical request: "
        + json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    body_payload: dict[str, Any] = {
        "model": str(profile.get("model_name") or profile.get("model_id") or "qwen"),
        "temperature": 0.0,
        "max_tokens": 1536,
        "response_format": {
            "type": "json_object",
            "schema": _qwen_binding_response_schema(request),
        },
        "messages": [
            {"role": "system", "content": "Return one compact closed JSON object only."},
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
    request_attempt = None

    def _open_attested_response() -> Any:
        nonlocal request_attempt
        from app.learn.hybrid.benchmark_v2_dispatch_attestation import (
            attest_managed_model_dispatch,
            current_benchmark_dispatch_context,
        )

        dispatch_context = current_benchmark_dispatch_context()
        if dispatch_context is not None and model_lease is None:
            raise ValueError("benchmark Qwen dispatch requires the exact managed lease")
        if model_lease is not None:
            if dispatch_context is not None:
                attest_managed_model_dispatch(
                    model_lease=model_lease,
                    dispatch_context=dispatch_context,
                )
            request_attempt = _mark_qwen_model_request_in_flight(model_lease)
        return urllib.request.urlopen(http_request, timeout=float(timeout_seconds))

    try:
        if cancellation_event is not None and hasattr(
            cancellation_event, "run_if_not_cancelled"
        ):
            allowed, opened_response = cancellation_event.run_if_not_cancelled(
                "qwen_provider_dispatch",
                _open_attested_response,
            )
            if not allowed:
                raise QwenModelRequestCancelled("Qwen binding request cancelled")
        else:
            if cancellation_event is not None and cancellation_event.is_set():
                raise QwenModelRequestCancelled("Qwen binding request cancelled")
            opened_response = _open_attested_response()
        with opened_response as response:
            response_bytes = response.read(_QWEN_HTTP_RESPONSE_MAX_BYTES + 1)
            if len(response_bytes) > _QWEN_HTTP_RESPONSE_MAX_BYTES:
                raise ValueError("Qwen HTTP response byte limit exceeded")
            if model_lease is not None:
                _mark_qwen_model_compute_complete(
                    model_lease,
                    request_attempt=request_attempt,
                )
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
        raw_content_bytes = content.encode("utf-8")
        choice = choices[0]
        usage = response_payload.get("usage")
        diagnostics = seal_immutable(
            {
                "contract_version": "qwen_binding_response_failure_trace_v1",
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
                "evidence_use": "benchmark_non_authorizing_diagnostic",
                "request_lineage": {
                    "model_request_id": request_id or None,
                    "request_content_sha256": content_sha256(request),
                    "screenshot_sha256": screenshot_sha256,
                    "profile_id": str(profile.get("profile_id") or ""),
                    "model_id": str(body_payload["model"]),
                },
                "http_response": {
                    "response_body_bytes": len(response_bytes),
                    "response_body_sha256": sha256(response_bytes).hexdigest(),
                    "raw_message_content": content,
                    "raw_message_content_utf8_bytes": len(raw_content_bytes),
                    "raw_message_content_sha256": sha256(raw_content_bytes).hexdigest(),
                    "finish_reason": (
                        choice.get("finish_reason")
                        if isinstance(choice.get("finish_reason"), str)
                        else None
                    ),
                    "usage": deepcopy(usage) if isinstance(usage, dict) else None,
                },
                "parse_error": {
                    "type": type(error).__name__,
                    "message": str(error),
                    "line": error.lineno,
                    "column": error.colno,
                    "position": error.pos,
                },
            }
        )
        failure = ValueError("Qwen binding response is not a closed JSON object")
        failure.diagnostics = diagnostics
        raise failure from error
    if not isinstance(parsed, dict):
        raise ValueError("Qwen binding response is not an object")
    return parsed


def run_qwen_projection_model(
    *,
    projection: Mapping[str, Any],
    screenshot_bytes: bytes,
    screenshot_media_type: str,
    screenshot_sha256: str,
    model_lease: dict[str, Any],
    timeout_seconds: float = 120.0,
) -> dict[str, Any]:
    """Send the closed simple-native per-goal projection under an exact lease."""
    compact = deepcopy(dict(projection)) if isinstance(projection, Mapping) else None
    if not isinstance(compact, dict) or set(compact) != {"image_size", "goals", "candidates"}:
        raise ValueError("Qwen model projection is not closed")
    image_size, goals, candidates = compact["image_size"], compact["goals"], compact["candidates"]
    if (
        not isinstance(image_size, list)
        or len(image_size) != 2
        or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in image_size)
        or not isinstance(goals, list)
        or not isinstance(candidates, list)
    ):
        raise ValueError("Qwen model projection image, goals, or candidates are invalid")
    for index, goal in enumerate(goals):
        if (
            not isinstance(goal, dict)
            or set(goal) != {"goal_index", "role", "label"}
            or isinstance(goal.get("goal_index"), bool)
            or goal.get("goal_index") != index
            or not isinstance(goal.get("role"), str)
            or not goal["role"].strip()
            or not isinstance(goal.get("label"), str)
            or not goal["label"].strip()
        ):
            raise ValueError("Qwen model projection goal is invalid")
    for index, candidate in enumerate(candidates):
        if (
            not isinstance(candidate, dict)
            or set(candidate) != {"candidate_index", "bbox", "active"}
            or isinstance(candidate.get("candidate_index"), bool)
            or candidate.get("candidate_index") != index
            or not isinstance(candidate.get("active"), bool)
            or not isinstance(candidate.get("bbox"), list)
            or len(candidate["bbox"]) != 4
            or any(isinstance(edge, bool) or not isinstance(edge, int) for edge in candidate["bbox"])
        ):
            raise ValueError("Qwen model projection candidate is invalid")
    if not isinstance(screenshot_bytes, bytes) or not screenshot_bytes:
        raise ValueError("verified screenshot bytes are required")
    if screenshot_media_type not in {"image/png", "image/jpeg"}:
        raise ValueError("verified screenshot media type is invalid")
    if sha256(screenshot_bytes).hexdigest() != screenshot_sha256:
        raise ValueError("verified screenshot hash mismatch")
    profile = _profile_for_qwen_model_lease(model_lease)
    endpoint = str(profile.get("endpoint") or "").strip() or model_base_url(profile) + "/chat/completions"
    image_url = "data:" + screenshot_media_type + ";base64," + base64.b64encode(screenshot_bytes).decode("ascii")
    prompt = (
        "For every fixed goal exactly once in order, bind one existing candidate index or abstain. "
        "Return only the closed bindings JSON with goal_index,candidate_index,status,confidence; "
        "BOUND requires an existing candidate_index and UNBOUND requires null. Projection: "
        + json.dumps(compact, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    body_payload = {
        "model": str(profile.get("model_name") or profile.get("model_id") or "qwen"),
        "temperature": 0.0,
        "max_tokens": 1536,
        "response_format": {
            "type": "json_object",
            "schema": _qwen_model_projection_response_schema(compact),
        },
        "messages": [
            {"role": "system", "content": "Return one compact closed JSON object only."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            },
        ],
    }
    body = json.dumps(body_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > _SIMPLE_NATIVE_HTTP_REQUEST_MAX_BYTES:
        raise ValueError("Qwen projection HTTP request byte limit exceeded")
    http_request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    request_attempt = mark_qwen_model_request_in_flight(model_lease=model_lease)
    if request_attempt is None:
        raise ValueError("exact Qwen model lease could not be marked in flight")
    try:
        with urllib.request.urlopen(http_request, timeout=float(timeout_seconds)) as response:
            response_bytes = response.read(_QWEN_HTTP_RESPONSE_MAX_BYTES + 1)
            if len(response_bytes) > _QWEN_HTTP_RESPONSE_MAX_BYTES:
                raise ValueError("Qwen HTTP response byte limit exceeded")
            mark_qwen_model_response_body_complete(
                model_lease=model_lease,
                request_attempt=request_attempt,
            )
    except urllib.error.URLError as error:
        raise RuntimeError(f"Qwen projection request failed: {error}") from error
    response_payload = json.loads(response_bytes.decode("utf-8"))
    choices = response_payload.get("choices") if isinstance(response_payload, dict) else None
    message = choices[0].get("message") if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise ValueError("Qwen projection response has no JSON message content")
    parsed = json.loads(content)
    if not isinstance(parsed, dict) or set(parsed) != {"bindings"}:
        raise ValueError("Qwen projection response is not closed JSON")
    return parsed


def run_hybrid_vista_bare_point(
    *,
    roi_bytes: bytes,
    roi_media_type: str,
    roi_sha256: str,
    target_text: str,
    model_lease: dict[str, Any],
    timeout_seconds: float = 120.0,
) -> str:
    """使用精确 VISTA 租约发送单条 ROI 点定位请求。"""
    if not isinstance(roi_bytes, bytes) or not roi_bytes:
        raise ValueError("verified VISTA ROI bytes are required")
    if roi_media_type not in {"image/png", "image/jpeg"}:
        raise ValueError("verified VISTA ROI media type is invalid")
    if sha256(roi_bytes).hexdigest() != roi_sha256:
        raise ValueError("verified VISTA ROI hash mismatch")
    prompt = str(target_text or "").strip()
    if not prompt or len(prompt) > 512:
        raise ValueError("VISTA target text is invalid")
    request_timeout_seconds = float(timeout_seconds)
    if not math.isfinite(request_timeout_seconds) or request_timeout_seconds <= 0:
        raise ValueError("VISTA request timeout is invalid")
    profile = _profile_for_hybrid_vista_model_lease(model_lease)
    endpoint = str(profile.get("endpoint") or "").strip() or model_base_url(profile) + "/chat/completions"
    image_url = "data:" + roi_media_type + ";base64," + base64.b64encode(roi_bytes).decode("ascii")
    try:
        max_tokens = int(profile.get("max_new_tokens") or 32)
    except (TypeError, ValueError) as error:
        raise ValueError("VISTA max token limit is invalid") from error
    wire_prompt = prompt + "\nReturn only [x,y] normalized to 0..1000."
    body_payload = {
        "model": str(profile.get("model_name") or profile.get("model_id") or "vista"),
        "temperature": 0.0,
        "max_tokens": min(32, max(1, max_tokens)),
        "request_timeout_seconds": request_timeout_seconds,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": wire_prompt},
                    {"type": "image_url", "image_url": {"url": image_url}},
                ],
            }
        ],
    }
    body = json.dumps(body_payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(body) > _SIMPLE_NATIVE_HTTP_REQUEST_MAX_BYTES:
        raise ValueError("VISTA HTTP request byte limit exceeded")
    request = urllib.request.Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=request_timeout_seconds) as response:
            response_bytes = response.read(_QWEN_HTTP_RESPONSE_MAX_BYTES + 1)
            if len(response_bytes) > _QWEN_HTTP_RESPONSE_MAX_BYTES:
                raise ValueError("VISTA HTTP response byte limit exceeded")
    except urllib.error.URLError as error:
        raise RuntimeError(f"VISTA point request failed: {error}") from error
    response_payload = json.loads(response_bytes.decode("utf-8"))
    choices = response_payload.get("choices") if isinstance(response_payload, dict) else None
    message = choices[0].get("message") if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str):
        raise ValueError("VISTA point response has no message content")
    return content


def prepare_qwen_model_request_acquisition_owner(
    request_id: str, *, runtime_owner_ref: Mapping[str, object]
) -> dict[str, Any]:
    """在零 provider 副作用边界持久化 benchmark Qwen 获取所有者。"""
    normalized_request_id = _normalized_qwen_request_id(request_id)
    runtime_owner = _validate_qwen_runtime_owner(
        runtime_owner_ref, request_id=normalized_request_id
    )
    intent = seal_immutable(
        {
            "contract_version": "qwen_model_request_acquisition_intent_v1",
            "model_request_id": normalized_request_id,
            "runtime_owner_ref": deepcopy(runtime_owner),
        }
    )
    intent_ref = _qwen_content_ref(intent)
    owner = seal_immutable(
        {
            "contract_version": "benchmark_provider_acquisition_owner_v1",
            "model_request_id": normalized_request_id,
            "runtime_owner_ref": deepcopy(runtime_owner),
            "acquisition_intent_ref": intent_ref,
            "owner_state": "acquisition_prepared",
        }
    )
    prepared = _qwen_prepared_materialization_ledger(
        normalized_request_id,
        acquisition_intent_ref=intent_ref,
        runtime_owner_ref=runtime_owner,
    )
    with _qwen_acquisition_lock():
        paths = _qwen_acquisition_artifact_paths(normalized_request_id)
        prefix = [
            (paths["intent"], intent),
            (paths["owner"], owner),
            (paths["ledger_revision_zero"], prepared),
            (paths["ledger"], prepared),
        ]
        loaded_prefix = [
            _load_optional_qwen_sealed_artifact(path) for path, _ in prefix
        ]
        if all(value is not None for value in loaded_prefix):
            persisted_intent = _load_qwen_acquisition_intent(normalized_request_id)
            persisted_owner = _load_qwen_acquisition_owner(normalized_request_id)
            ledger = _load_qwen_model_request_materialization_ledger(
                normalized_request_id,
                acquisition_intent_ref=intent_ref,
                runtime_owner_ref=runtime_owner,
            )
            if (
                persisted_intent != intent
                or persisted_owner != owner
                or loaded_prefix[2] != prepared
            ):
                raise RuntimeError("Qwen acquisition owner replay conflicts with durable owner")
            with _qwen_lease_lock():
                _validate_qwen_prepare_owner_collision_locked(
                    normalized_request_id,
                    owner=owner,
                    allow_matching_binding=True,
                )
            return deepcopy(persisted_owner)
        missing_seen = False
        for loaded, (_, expected) in zip(loaded_prefix, prefix):
            if loaded is None:
                missing_seen = True
            elif missing_seen:
                raise RuntimeError("Qwen acquisition prepare prefix has a revision gap")
            elif loaded != expected:
                raise RuntimeError("Qwen acquisition prepare prefix conflicts")
        post_prepare_keys = {
            "ledger_winner",
            "abort",
            "aborted_tombstone",
            "lease_binding",
            "lease_state_snapshot",
            "release_observation",
            "termination_observation",
            "cleanup_receipt",
        }
        if any(paths[key].exists() for key in post_prepare_keys):
            raise RuntimeError("Qwen acquisition prepare prefix has post-prepare artifacts")
        with _qwen_lease_lock():
            _validate_qwen_prepare_owner_collision_locked(
                normalized_request_id,
                owner=owner,
                allow_matching_binding=False,
            )
        for loaded, (path, expected) in zip(loaded_prefix, prefix):
            if loaded is None:
                _write_qwen_acquisition_artifact(path, expected)
        return deepcopy(owner)


def observe_qwen_model_request_acquisition(
    request_id: str,
    *,
    acquisition_intent_ref: Mapping[str, object],
    runtime_owner_ref: Mapping[str, object],
) -> dict[str, Any]:
    """只读观察精确 acquisition owner 与当前 materialization head。"""
    normalized_request_id = _normalized_qwen_request_id(request_id)
    with _qwen_acquisition_lock():
        supplied_intent_ref = _validate_qwen_content_ref(acquisition_intent_ref)
        supplied_runtime_owner = _validate_qwen_runtime_owner(
            runtime_owner_ref,
            request_id=normalized_request_id,
        )
        intent = _load_qwen_acquisition_intent(normalized_request_id)
        owner = _load_qwen_acquisition_owner(normalized_request_id)
        exact_intent_ref = _qwen_content_ref(intent)
        if (
            exact_intent_ref != supplied_intent_ref
            or owner.get("acquisition_intent_ref") != supplied_intent_ref
            or intent.get("runtime_owner_ref") != supplied_runtime_owner
            or owner.get("runtime_owner_ref") != supplied_runtime_owner
        ):
            raise RuntimeError("Qwen acquisition observation owner substitution rejected")
        ledger = _load_qwen_model_request_materialization_ledger(
            normalized_request_id,
            acquisition_intent_ref=supplied_intent_ref,
            runtime_owner_ref=supplied_runtime_owner,
        )
        prepared_ledger = _load_qwen_prepared_materialization_ledger(
            normalized_request_id,
            acquisition_intent_ref=supplied_intent_ref,
            runtime_owner_ref=supplied_runtime_owner,
        )
        return seal_immutable(
            {
                "contract_version": "qwen_model_request_acquisition_observation_v1",
                "model_request_id": normalized_request_id,
                "acquisition_owner_ref": _qwen_content_ref(owner),
                "acquisition_intent_ref": deepcopy(supplied_intent_ref),
                "runtime_owner_ref": deepcopy(supplied_runtime_owner),
                "prepared_materialization_ledger_ref": _qwen_content_ref(
                    prepared_ledger
                ),
                "materialization_ledger_ref": _qwen_content_ref(ledger),
                "materialization_state": ledger["state"],
                "materialization_revision": ledger["revision"],
            }
        )


def abort_qwen_model_request_acquisition(
    request_id: str,
    *,
    acquisition_intent_ref: Mapping[str, object],
    runtime_owner_ref: Mapping[str, object],
    reason: str,
) -> dict[str, Any]:
    """只允许 prepared_never_materialized 单调转为 aborted。"""
    normalized_request_id = _normalized_qwen_request_id(request_id)
    normalized_reason = str(reason or "").strip()
    if not normalized_reason:
        raise ValueError("Qwen acquisition abort reason is required")
    supplied_intent_ref = _validate_qwen_content_ref(acquisition_intent_ref)
    supplied_runtime_owner = _validate_qwen_runtime_owner(
        runtime_owner_ref, request_id=normalized_request_id
    )
    with _qwen_acquisition_lock():
        owner = _load_qwen_acquisition_owner(normalized_request_id)
        if (
            owner["acquisition_intent_ref"] != supplied_intent_ref
            or owner["runtime_owner_ref"] != supplied_runtime_owner
        ):
            raise RuntimeError("Qwen acquisition abort owner substitution rejected")
        head = _transition_qwen_model_request_materialization_locked(
            normalized_request_id,
            transition="abort",
            acquisition_intent_ref=supplied_intent_ref,
            runtime_owner_ref=supplied_runtime_owner,
        )
        paths = _qwen_acquisition_artifact_paths(normalized_request_id)
        tombstone = seal_immutable(
            {
                "contract_version": "benchmark_provider_aborted_acquisition_tombstone_v1",
                "model_request_id": normalized_request_id,
                "acquisition_intent_ref": supplied_intent_ref,
                "runtime_owner_ref": supplied_runtime_owner,
                "materialization_ledger_ref": _qwen_content_ref(head),
                "reason": normalized_reason,
                "historical_process_identity": None,
                "historical_socket_ref": None,
                "historical_job_scope_ref": None,
            }
        )
        existing_tombstone = _load_optional_qwen_sealed_artifact(
            paths["aborted_tombstone"]
        )
        if existing_tombstone is None:
            _write_qwen_acquisition_artifact(paths["aborted_tombstone"], tombstone)
        elif existing_tombstone != tombstone:
            raise RuntimeError("Qwen aborted acquisition tombstone conflicts")
        abort_result = seal_immutable(
            {
                "contract_version": "benchmark_provider_acquisition_abort_v1",
                "model_request_id": normalized_request_id,
                "acquisition_intent_ref": supplied_intent_ref,
                "runtime_owner_ref": supplied_runtime_owner,
                "materialization_ledger_ref": _qwen_content_ref(head),
                "owner_tombstone_ref": _qwen_content_ref(tombstone),
                "reason": normalized_reason,
                "owner_state": "acquisition_aborted",
            }
        )
        existing_abort = _load_optional_qwen_sealed_artifact(paths["abort"])
        if existing_abort is None:
            _write_qwen_acquisition_artifact(paths["abort"], abort_result)
        elif existing_abort != abort_result:
            raise RuntimeError("Qwen acquisition abort replay conflicts")
        return deepcopy(abort_result)


def _transition_qwen_model_request_materialization(
    request_id: str,
    *,
    transition: str,
    acquisition_intent_ref: Mapping[str, object] | None = None,
    runtime_owner_ref: Mapping[str, object] | None = None,
) -> dict[str, Any] | None:
    normalized_request_id = _normalized_qwen_request_id(request_id)
    with _qwen_acquisition_lock():
        return _transition_qwen_model_request_materialization_locked(
            normalized_request_id,
            transition=transition,
            acquisition_intent_ref=acquisition_intent_ref,
            runtime_owner_ref=runtime_owner_ref,
        )


def _transition_qwen_model_request_materialization_locked(
    request_id: str,
    *,
    transition: str,
    acquisition_intent_ref: Mapping[str, object] | None = None,
    runtime_owner_ref: Mapping[str, object] | None = None,
) -> dict[str, Any] | None:
    paths = _qwen_acquisition_artifact_paths(request_id)
    if not paths["owner"].exists():
        if acquisition_intent_ref is not None or runtime_owner_ref is not None:
            raise RuntimeError("Qwen benchmark acquisition owner is missing")
        return None
    owner = _load_qwen_acquisition_owner(request_id)
    intent_ref = owner["acquisition_intent_ref"]
    exact_runtime_owner = owner["runtime_owner_ref"]
    intent = _load_qwen_acquisition_intent(request_id)
    if (
        _qwen_content_ref(intent) != intent_ref
        or intent.get("runtime_owner_ref") != exact_runtime_owner
    ):
        raise RuntimeError("Qwen acquisition intent lineage is invalid")
    if (
        acquisition_intent_ref is not None
        and _validate_qwen_content_ref(acquisition_intent_ref) != intent_ref
    ):
        raise RuntimeError("Qwen materialization acquisition intent substitution rejected")
    if (
        runtime_owner_ref is not None
        and _validate_qwen_runtime_owner(runtime_owner_ref, request_id=request_id)
        != exact_runtime_owner
    ):
        raise RuntimeError("Qwen materialization runtime owner substitution rejected")
    if transition not in {"abort", "launch"}:
        raise ValueError("Qwen materialization transition is invalid")
    raw_head = _load_optional_qwen_sealed_artifact(paths["ledger"])
    raw_winner = _load_optional_qwen_sealed_artifact(paths["ledger_winner"])
    if isinstance(raw_head, dict) and raw_head.get("revision") == 0 and raw_winner is not None:
        prepared_head = _validate_qwen_materialization_ledger(
            raw_head,
            request_id=request_id,
            acquisition_intent_ref=intent_ref,
            runtime_owner_ref=exact_runtime_owner,
        )
        if _load_optional_qwen_sealed_artifact(paths["ledger_revision_zero"]) != prepared_head:
            raise RuntimeError("Qwen materialization revision-zero lineage is invalid")
        winner = _validate_qwen_materialization_ledger(
            raw_winner,
            request_id=request_id,
            acquisition_intent_ref=intent_ref,
            runtime_owner_ref=exact_runtime_owner,
        )
        if winner.get("transition") != transition:
            raise RuntimeError("Qwen materialization transition conflicts with durable winner")
        _write_qwen_acquisition_artifact(paths["ledger"], winner)
        return deepcopy(winner)
    head = _load_qwen_model_request_materialization_ledger(
        request_id,
        acquisition_intent_ref=intent_ref,
        runtime_owner_ref=exact_runtime_owner,
    )
    target_state = (
        "aborted_never_materialized"
        if transition == "abort"
        else "materialization_possible"
    )
    if head["revision"] == 1:
        if head["transition"] == transition and head["state"] == target_state:
            return deepcopy(head)
        raise RuntimeError("Qwen materialization transition conflicts with durable winner")
    if head["revision"] != 0 or head["state"] != "prepared_never_materialized":
        raise RuntimeError("Qwen materialization ledger cannot transition")
    next_head = seal_immutable(
        {
            "contract_version": "qwen_model_request_materialization_ledger_v1",
            "model_request_id": request_id,
            "acquisition_intent_ref": deepcopy(intent_ref),
            "runtime_owner_ref": deepcopy(exact_runtime_owner),
            "state": target_state,
            "revision": 1,
            "transition": transition,
            "predecessor_content_sha256": head["content_sha256"],
        }
    )
    existing_winner = _load_optional_qwen_sealed_artifact(paths["ledger_winner"])
    if existing_winner is None:
        _write_qwen_acquisition_artifact(paths["ledger_winner"], next_head)
    elif existing_winner != next_head:
        raise RuntimeError("Qwen materialization winner conflicts")
    _write_qwen_acquisition_artifact(paths["ledger"], next_head)
    return deepcopy(next_head)


def ensure_and_acquire_qwen_model_lease(
    *,
    stage: str,
    profile_id: str | None,
    request_id: str,
    wait_seconds: float,
    profile_validator: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """跨进程串行化 Qwen 首启与租约发布，避免无主启动副作用。"""
    _validate_qwen_runtime_acquiring(request_id)
    with _qwen_acquisition_lock():
        _transition_qwen_model_request_materialization_locked(
            _normalized_qwen_request_id(request_id),
            transition="launch",
        )
        profile = deepcopy(profile_for_stage(stage, profile_id))
        if profile_validator is not None:
            profile_validator(deepcopy(profile))
        runtime_path_text = os.environ.get(
            "AGENT_GUI_HYBRID_PROVIDER_RUNTIME_PATH", ""
        ).strip()
        if runtime_path_text:
            _publish_qwen_runtime_start_intent(
                Path(runtime_path_text),
                request_id=request_id,
                profile=profile,
                expected_lineage=json.loads(
                    os.environ.get("AGENT_GUI_HYBRID_LINEAGE_JSON", "{}")
                ),
                expected_scope_name=os.environ.get(
                    "AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", ""
                ).strip(),
            )
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
        process_scope_name = os.environ.get(
            "AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", ""
        ).strip()
        if process_scope_name:
            if readiness.get("started") is not True:
                raise RuntimeError(
                    "Hybrid Qwen cannot adopt a provider outside its exact process scope"
                )
            from app.learn.hybrid.windows_process_scope import WindowsProcessScope

            scope = WindowsProcessScope(process_scope_name, create=False)
            try:
                binding = _observe_qwen_server_binding(profile, readiness)
                identity = (
                    binding.get("server_process_identity")
                    if isinstance(binding, dict)
                    else None
                )
                if (
                    not _valid_process_identity(identity)
                    or identity["pid"] not in scope.pids()
                ):
                    raise RuntimeError(
                        "Hybrid Qwen provider identity is outside its exact process scope"
                    )
            finally:
                scope.close()
        return _acquire_qwen_model_lease_under_acquisition_lock(
            profile=profile,
            request_id=request_id,
            readiness=readiness,
        )


def ensure_and_acquire_scoped_qwen_model_lease(
    *,
    stage: str,
    profile_id: str | None,
    request_id: str,
    wait_seconds: float,
    profile_validator: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """不创建 benchmark owner/materialization 的精确 scoped Qwen 租约。"""
    owner_request_id = _normalized_qwen_request_id(request_id)
    with _qwen_acquisition_lock():
        paths = _qwen_acquisition_artifact_paths(owner_request_id)
        if any(path.exists() for path in paths.values()):
            raise ValueError("scoped Qwen request collides with benchmark acquisition artifacts")
        profile = deepcopy(profile_for_stage(stage, profile_id))
        if profile_validator is not None:
            profile_validator(deepcopy(profile))
        scope_name = os.environ.get("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", "").strip()
        if not scope_name:
            raise ValueError("scoped Qwen acquisition requires an exact process scope")
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
        if status != "running" or readiness.get("profile") != _public_profile(profile):
            raise RuntimeError("scoped Qwen model service readiness is not exact")
        if readiness.get("started") is not True:
            raise RuntimeError("scoped Qwen cannot adopt a provider outside its exact process scope")
        from app.learn.hybrid.windows_process_scope import WindowsProcessScope

        scope = WindowsProcessScope(scope_name, create=False)
        try:
            member_pids = scope.pids()
        finally:
            scope.close()
        binding = _observe_qwen_server_binding(profile, readiness)
        identity = binding.get("server_process_identity") if isinstance(binding, dict) else None
        if not _valid_process_identity(identity) or identity["pid"] not in member_pids:
            raise RuntimeError("scoped Qwen provider identity is outside its exact process scope")
        return _acquire_qwen_model_lease_under_acquisition_lock(
            profile=profile,
            request_id=owner_request_id,
            readiness=readiness,
            publish_runtime_acquired=False,
        )


def acquire_qwen_model_lease(
    *,
    profile: dict[str, Any],
    request_id: str,
    readiness: dict[str, Any],
) -> dict[str, Any]:
    owner_request_id = _normalized_qwen_request_id(request_id)
    with _qwen_acquisition_lock():
        _transition_qwen_model_request_materialization_locked(
            owner_request_id,
            transition="launch",
        )
        return _acquire_qwen_model_lease_under_acquisition_lock(
            profile=profile,
            request_id=owner_request_id,
            readiness=readiness,
        )


def _acquire_qwen_model_lease_under_acquisition_lock(
    *,
    profile: dict[str, Any],
    request_id: str,
    readiness: dict[str, Any],
    publish_runtime_acquired: bool = True,
) -> dict[str, Any]:
    profile_id = str(profile.get("profile_id") or "").strip()
    owner_request_id = str(request_id or "").strip()
    if not profile_id or not owner_request_id:
        raise ValueError("Qwen model lease identity is incomplete")
    incarnation = _qwen_server_incarnation(profile, readiness)
    process_scope_name = os.environ.get(
        "AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", ""
    ).strip() or None
    process_scope_acquisition = None
    if process_scope_name:
        from app.learn.hybrid.windows_process_scope import WindowsProcessScope

        scope = WindowsProcessScope(process_scope_name, create=False)
        try:
            member_pids = scope.pids()
        finally:
            scope.close()
        exact_pid = int(incarnation["server_process_identity"]["pid"])
        if exact_pid not in member_pids:
            raise RuntimeError(
                "Qwen exact server process is outside its provider scope"
            )
        process_scope_acquisition = {
            "contract_version": "hybrid_process_scope_acquisition_v1",
            "scope_name": process_scope_name,
            "member_pids": member_pids,
            "server_process_identity": deepcopy(
                incarnation["server_process_identity"]
            ),
        }
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
        owner_matches = _find_qwen_owner_leases_locked(owner_request_id)
        if owner_matches:
            acquisition_paths = _qwen_acquisition_artifact_paths(owner_request_id)
            if not acquisition_paths["owner"].exists():
                raise ValueError("Qwen request already owns a server lease")
            recovery_owner = _load_qwen_acquisition_owner(owner_request_id)
            recovery_ledger = _load_qwen_model_request_materialization_ledger(
                owner_request_id,
                acquisition_intent_ref=recovery_owner["acquisition_intent_ref"],
                runtime_owner_ref=recovery_owner["runtime_owner_ref"],
            )
            if (
                recovery_ledger.get("state") != "materialization_possible"
                or acquisition_paths["lease_binding"].exists()
            ):
                raise ValueError("Qwen request already owns a server lease")
            state, lease = owner_matches[0]
            persisted_scope = state.get("process_scope_acquisition")
            if (
                state.get("profile_id") != profile_id
                or not _compatible_qwen_incarnations(state["incarnation"], incarnation)
                or lease.get("profile_sha256")
                != content_sha256(_public_profile(profile))
                or state.get("process_scope_name") != process_scope_name
                or not isinstance(persisted_scope, dict)
                or persisted_scope.get("scope_name") != process_scope_name
                or persisted_scope.get("server_process_identity")
                != lease.get("server_process_identity")
                or state.get("finalization") is not None
            ):
                raise RuntimeError("Qwen existing request lease cannot recover binding")
        else:
            state = _load_qwen_lease_state(incarnation["incarnation_id"])
            if state is None:
                state = {
                    "contract_version": _QWEN_LEASE_STATE_CONTRACT,
                    "profile_id": profile_id,
                    "profile": deepcopy(profile),
                    "incarnation": incarnation,
                    "server_started_by_runtime": bool(readiness.get("started")),
                    "process_scope_name": process_scope_name,
                    "process_scope_acquisition": process_scope_acquisition,
                    "revision": 0,
                    "finalization": None,
                    "leases": [],
                }
            elif not _compatible_qwen_incarnations(state["incarnation"], incarnation):
                raise ValueError("Qwen server incarnation mismatch")
            else:
                incarnation = deepcopy(state["incarnation"])
                if state.get("process_scope_name") != process_scope_name:
                    raise ValueError("Qwen process scope mismatch for existing lease")
                if state.get("process_scope_acquisition") != process_scope_acquisition:
                    raise ValueError("Qwen process scope acquisition mismatch")
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
            state["server_started_by_runtime"] = bool(
                state.get("server_started_by_runtime") or readiness.get("started")
            )
            state["revision"] = int(state.get("revision") or 0) + 1
            state["leases"].append({**deepcopy(lease), "lifecycle_state": "not_started"})
            _write_qwen_lease_state(state)
        _write_qwen_acquisition_lease_binding_locked(
            owner_request_id,
            model_lease=lease,
            state=state,
        )
    runtime_path = os.environ.get("AGENT_GUI_HYBRID_PROVIDER_RUNTIME_PATH", "").strip()
    if publish_runtime_acquired and process_scope_name and runtime_path:
        _publish_qwen_runtime_acquired(
            Path(runtime_path),
            request_id=owner_request_id,
            model_lease=lease,
            process_scope_name=process_scope_name,
        )
    return lease


def reconcile_hybrid_qwen_owner(
    path: Path,
    *,
    expected_lineage: dict[str, Any],
    expected_scope_name: str,
) -> dict[str, Any]:
    """异常 worker 退出时仅按持久化精确 Qwen owner 完成原有 tombstone 流程。"""
    from app.learn.hybrid.gpu_lifecycle import validate_hybrid_lineage
    from app.learn.hybrid.windows_process_scope import (
        observe_process_scope_cleanup,
        process_scope_name,
    )

    lineage = validate_hybrid_lineage(expected_lineage)
    document = _load_qwen_runtime_owner(path)
    if (
        document.get("lineage") != lineage
        or document.get("process_scope_name") != expected_scope_name
        or process_scope_name(lineage, "qwen") != expected_scope_name
    ):
        raise RuntimeError("Hybrid Qwen owner lineage mismatch")
    if document.get("contract_version") == "hybrid_qwen_aborted_acquisition_v1":
        tombstone = _load_qwen_aborted_acquisition_tombstone(
            path,
            expected_lineage=lineage,
            expected_scope_name=expected_scope_name,
        )
        return {
            "contract_version": "hybrid_qwen_abnormal_reconciliation_v2",
            "status": "verified",
            "aborted_acquisition_tombstone": tombstone,
            "scope_cleanup_evidence": deepcopy(tombstone["scope_cleanup_evidence"]),
        }
    if document.get("contract_version") == "hybrid_supervised_provider_runtime_v1":
        request_id = str(document.get("model_request_id") or "")
        match = _find_qwen_lease_by_owner(request_id)
        if match is None:
            raise RuntimeError("Hybrid Qwen acquiring owner has no exact durable lease")
        state, exact_lease = match
        document = seal_immutable({
            "contract_version": "hybrid_qwen_model_owner_v1",
            "state": "acquired",
            "model_request_id": request_id,
            "lineage": lineage,
            "process_scope_name": expected_scope_name,
            "model_lease": deepcopy(exact_lease),
            "profile": deepcopy(state["profile"]),
            "release_result": None,
            "tombstone_sha256": None,
            "scope_cleanup": None,
        })
        _write_hybrid_qwen_runtime(path, document)
    if document.get("contract_version") == "hybrid_qwen_acquisition_intent_v1":
        request_id = str(document.get("model_request_id") or "")
        match = _find_qwen_lease_by_owner(request_id)
        if match is None:
            return _abort_qwen_acquisition_without_lease(
                path,
                document=document,
                expected_lineage=lineage,
                expected_scope_name=expected_scope_name,
            )
        state, exact_lease = match
        document = seal_immutable({
            "contract_version": "hybrid_qwen_model_owner_v1",
            "state": "acquired",
            "model_request_id": request_id,
            "lineage": lineage,
            "process_scope_name": expected_scope_name,
            "model_lease": deepcopy(exact_lease),
            "profile": deepcopy(state["profile"]),
            "release_result": None,
            "tombstone_sha256": None,
            "scope_cleanup": None,
        })
        _write_hybrid_qwen_runtime(path, document)
    lease = document.get("model_lease")
    if not isinstance(lease, dict) or set(lease) != _QWEN_LEASE_FIELDS:
        raise RuntimeError("Hybrid Qwen exact model lease is unavailable")
    if document.get("model_request_id") != lease.get("owner_request_id"):
        raise RuntimeError("Hybrid Qwen model request identity mismatch")
    if document.get("state") == "released":
        release_result = document.get("release_result")
        if not isinstance(release_result, dict):
            raise RuntimeError("Hybrid Qwen released owner lost terminal proof")
    else:
        release_result = _release_exact_qwen_lease(
            lease,
            reason="outer_worker_terminated",
        )
    tombstone = _load_qwen_owner_tombstone(str(lease["owner_request_id"]))
    if (
        not isinstance(tombstone, dict)
        or tombstone.get("lease_id") != lease.get("lease_id")
        or tombstone.get("incarnation_id") != lease.get("incarnation_id")
        or tombstone.get("profile_id") != lease.get("profile_id")
        or tombstone.get("release_result") != release_result
    ):
        raise RuntimeError("Hybrid Qwen owner tombstone is inconsistent")
    _validate_exact_qwen_cleanup_evidence(release_result, lease)
    tombstone = seal_immutable(tombstone)
    if qwen_model_lease_is_active(lease) or _qwen_lease_state_path(
        str(lease["incarnation_id"])
    ).exists():
        raise RuntimeError("Hybrid Qwen durable lease remains active")
    parsed = urlsplit(str(lease.get("server_base_url") or ""))
    port = int(parsed.port or 0)
    profile = document.get("profile")
    pid_file = model_profile_pid_path(profile) if isinstance(profile, dict) else None
    scope_cleanup = observe_process_scope_cleanup(
        expected_scope_name,
        terminate=False,
        listener_ports=[port] if port > 0 else [],
        pid_file=pid_file,
        stable_zero_observations=3,
    )
    if scope_cleanup.get("cleanup_status") != "verified":
        raise RuntimeError("Hybrid Qwen scope cleanup is indeterminate")
    document.pop("content_sha256", None)
    document["state"] = "released"
    document["release_result"] = deepcopy(release_result)
    document["tombstone_sha256"] = tombstone["content_sha256"]
    document["scope_cleanup"] = scope_cleanup
    _write_hybrid_qwen_runtime(path, seal_immutable(document))
    return {
        "contract_version": "hybrid_qwen_abnormal_reconciliation_v1",
        "status": "verified",
        "model_lease": deepcopy(lease),
        "owner_tombstone": tombstone,
        "scope_cleanup_evidence": scope_cleanup,
    }


def _validate_qwen_runtime_acquiring(request_id: str) -> None:
    path_text = os.environ.get("AGENT_GUI_HYBRID_PROVIDER_RUNTIME_PATH", "").strip()
    scope_name = os.environ.get("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", "").strip()
    lineage_text = os.environ.get("AGENT_GUI_HYBRID_LINEAGE_JSON", "").strip()
    if not (path_text or scope_name or lineage_text):
        return
    try:
        document = json.loads(Path(path_text).read_text(encoding="utf-8"))
        lineage = json.loads(lineage_text)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Hybrid Qwen acquiring owner is unreadable") from error
    if (
        not isinstance(document, dict)
        or document.get("content_sha256") != content_sha256(document)
        or document.get("contract_version") != "hybrid_supervised_provider_runtime_v1"
        or document.get("state") != "acquiring"
        or document.get("provider") != "qwen"
        or document.get("model_request_id") != request_id
        or document.get("process_scope_name") != scope_name
        or document.get("lineage") != lineage
    ):
        raise RuntimeError("Hybrid Qwen acquiring owner is invalid")


def _publish_qwen_runtime_start_intent(
    path: Path,
    *,
    request_id: str,
    profile: dict[str, Any],
    expected_lineage: dict[str, Any],
    expected_scope_name: str,
) -> None:
    from app.learn.hybrid.gpu_lifecycle import validate_hybrid_lineage
    from app.learn.hybrid.windows_process_scope import process_scope_name

    lineage = validate_hybrid_lineage(expected_lineage)
    current = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(current, dict)
        or current.get("content_sha256") != content_sha256(current)
        or current.get("contract_version")
        != "hybrid_supervised_provider_runtime_v1"
        or current.get("state") != "acquiring"
        or current.get("provider") != "qwen"
        or current.get("model_request_id") != request_id
        or current.get("lineage") != lineage
        or current.get("process_scope_name") != expected_scope_name
        or process_scope_name(lineage, "qwen") != expected_scope_name
    ):
        raise RuntimeError("Hybrid Qwen start intent owner is invalid")
    parsed = urlsplit(
        str(profile.get("endpoint") or profile.get("base_url") or "")
    )
    port = int(profile.get("port") or parsed.port or 0)
    if port <= 0:
        raise RuntimeError("Hybrid Qwen start intent listener is invalid")
    intent = seal_immutable({
        "contract_version": "hybrid_qwen_acquisition_intent_v1",
        "state": "starting",
        "worker_id": current.get("worker_id"),
        "model_request_id": request_id,
        "provider": "qwen",
        "lineage": lineage,
        "process_scope_name": expected_scope_name,
        "profile": deepcopy(profile),
        "profile_sha256": content_sha256(_public_profile(profile)),
        "listener_port": port,
        "pid_file": str(model_profile_pid_path(profile)),
        "aborted_tombstone_sha256": None,
    })
    _write_hybrid_qwen_runtime(path, intent)


def _abort_qwen_acquisition_without_lease(
    path: Path,
    *,
    document: dict[str, Any],
    expected_lineage: dict[str, Any],
    expected_scope_name: str,
) -> dict[str, Any]:
    from app.learn.hybrid.windows_process_scope import observe_process_scope_cleanup

    profile = document.get("profile")
    if not isinstance(profile, dict):
        raise RuntimeError("Hybrid Qwen acquisition profile is unavailable")
    tombstone_path = path.with_name(f"{path.stem}.aborted.json")
    if tombstone_path.exists():
        tombstone = json.loads(tombstone_path.read_text(encoding="utf-8"))
        if (
            not isinstance(tombstone, dict)
            or tombstone.get("content_sha256") != content_sha256(tombstone)
            or tombstone.get("contract_version")
            != "hybrid_qwen_aborted_acquisition_tombstone_v1"
            or tombstone.get("status") != "aborted_before_lease"
            or tombstone.get("model_request_id") != document["model_request_id"]
            or tombstone.get("provider") != "qwen"
            or tombstone.get("lineage") != expected_lineage
            or tombstone.get("process_scope_name") != expected_scope_name
            or tombstone.get("profile_sha256") != document["profile_sha256"]
            or tombstone.get("listener_port") != document["listener_port"]
            or tombstone.get("pid_file") != document["pid_file"]
            or tombstone.get("scope_cleanup_evidence", {}).get(
                "cleanup_status"
            )
            != "verified"
        ):
            raise RuntimeError("Hybrid Qwen aborted acquisition tombstone conflicts")
    else:
        evidence = observe_process_scope_cleanup(
            expected_scope_name,
            terminate=True,
            listener_ports=[int(document.get("listener_port") or 0)],
            pid_file=str(document.get("pid_file") or ""),
            remove_owned_pid_file=True,
            stable_zero_observations=3,
        )
        if evidence.get("cleanup_status") != "verified":
            raise RuntimeError(
                "Hybrid Qwen aborted acquisition cleanup is indeterminate"
            )
        tombstone = seal_immutable({
            "contract_version": "hybrid_qwen_aborted_acquisition_tombstone_v1",
            "status": "aborted_before_lease",
            "model_request_id": document["model_request_id"],
            "provider": "qwen",
            "lineage": deepcopy(expected_lineage),
            "process_scope_name": expected_scope_name,
            "profile_sha256": document["profile_sha256"],
            "listener_port": document["listener_port"],
            "pid_file": document["pid_file"],
            "scope_cleanup_evidence": evidence,
        })
        _write_hybrid_qwen_runtime(tombstone_path, tombstone)
    evidence = deepcopy(tombstone["scope_cleanup_evidence"])
    aborted = seal_immutable({
        "contract_version": "hybrid_qwen_aborted_acquisition_v1",
        "state": "aborted",
        "model_request_id": document["model_request_id"],
        "provider": "qwen",
        "lineage": deepcopy(expected_lineage),
        "process_scope_name": expected_scope_name,
        "profile": deepcopy(profile),
        "aborted_tombstone_file": tombstone_path.name,
        "aborted_tombstone_sha256": tombstone["content_sha256"],
    })
    _write_hybrid_qwen_runtime(path, aborted)
    return {
        "contract_version": "hybrid_qwen_abnormal_reconciliation_v2",
        "status": "verified",
        "aborted_acquisition_tombstone": tombstone,
        "scope_cleanup_evidence": evidence,
    }


def _load_qwen_aborted_acquisition_tombstone(
    path: Path,
    *,
    expected_lineage: dict[str, Any],
    expected_scope_name: str,
) -> dict[str, Any]:
    owner = _load_qwen_runtime_owner(path)
    filename = str(owner.get("aborted_tombstone_file") or "")
    if Path(filename).name != filename or not filename:
        raise RuntimeError("Hybrid Qwen aborted tombstone path is invalid")
    tombstone = json.loads(path.with_name(filename).read_text(encoding="utf-8"))
    if (
        not isinstance(tombstone, dict)
        or tombstone.get("content_sha256") != content_sha256(tombstone)
        or tombstone.get("content_sha256")
        != owner.get("aborted_tombstone_sha256")
        or tombstone.get("contract_version")
        != "hybrid_qwen_aborted_acquisition_tombstone_v1"
        or tombstone.get("model_request_id") != owner.get("model_request_id")
        or tombstone.get("lineage") != expected_lineage
        or tombstone.get("process_scope_name") != expected_scope_name
        or tombstone.get("scope_cleanup_evidence", {}).get("cleanup_status")
        != "verified"
    ):
        raise RuntimeError("Hybrid Qwen aborted acquisition tombstone is invalid")
    return tombstone


def _consume_qwen_abort_without_lease_primitive(
    request_id: str,
    *,
    invoke: bool,
) -> dict[str, Any] | None:
    """消费生产侧无租约 abort 证明；配置缺失时保持不可判定。"""
    path_text = os.environ.get("AGENT_GUI_HYBRID_PROVIDER_RUNTIME_PATH", "").strip()
    scope_name = os.environ.get("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", "").strip()
    lineage_text = os.environ.get("AGENT_GUI_HYBRID_LINEAGE_JSON", "").strip()
    if not (path_text and scope_name and lineage_text):
        return None
    try:
        lineage = json.loads(lineage_text)
        path = Path(path_text)
        document = _load_qwen_runtime_owner(path)
        if (
            document.get("model_request_id") != request_id
            or document.get("lineage") != lineage
            or document.get("process_scope_name") != scope_name
        ):
            raise RuntimeError("Hybrid Qwen abort primitive owner mismatch")
        if document.get("contract_version") == "hybrid_qwen_acquisition_intent_v1":
            if not invoke:
                return None
            result = _abort_qwen_acquisition_without_lease(
                path,
                document=document,
                expected_lineage=lineage,
                expected_scope_name=scope_name,
            )
            tombstone = result.get("aborted_acquisition_tombstone")
        elif document.get("contract_version") == "hybrid_qwen_aborted_acquisition_v1":
            tombstone = _load_qwen_aborted_acquisition_tombstone(
                path,
                expected_lineage=lineage,
                expected_scope_name=scope_name,
            )
        else:
            return None
    except (OSError, RuntimeError, ValueError, UnicodeError, json.JSONDecodeError):
        return None
    tombstone_fields = {
        "contract_version",
        "status",
        "model_request_id",
        "provider",
        "lineage",
        "process_scope_name",
        "profile_sha256",
        "listener_port",
        "pid_file",
        "scope_cleanup_evidence",
        "content_sha256",
    }
    evidence = tombstone.get("scope_cleanup_evidence") if isinstance(tombstone, dict) else None
    if (
        not isinstance(tombstone, dict)
        or set(tombstone) != tombstone_fields
        or tombstone.get("content_sha256") != content_sha256(tombstone)
        or tombstone.get("contract_version")
        != "hybrid_qwen_aborted_acquisition_tombstone_v1"
        or tombstone.get("status") != "aborted_before_lease"
        or tombstone.get("model_request_id") != request_id
        or tombstone.get("provider") != "qwen"
        or tombstone.get("lineage") != lineage
        or tombstone.get("process_scope_name") != scope_name
        or not isinstance(tombstone.get("listener_port"), int)
        or tombstone["listener_port"] <= 0
        or not isinstance(tombstone.get("pid_file"), str)
        or not tombstone["pid_file"]
        or not isinstance(evidence, dict)
        or set(evidence) != _QWEN_SCOPE_CLEANUP_FIELDS
        or evidence.get("scope_name") != scope_name
        or evidence.get("authority") != "windows_job_object"
        or evidence.get("cleanup_status") != "verified"
        or evidence.get("member_pids_after") != []
        or evidence.get("member_identities_after") != []
        or evidence.get("active_listeners_after") != []
        or evidence.get("pid_file_after") is not None
        or not isinstance(evidence.get("stable_zero_observations"), int)
        or evidence["stable_zero_observations"] < 3
    ):
        return None
    return deepcopy(tombstone)


def _publish_qwen_runtime_acquired(
    path: Path,
    *,
    request_id: str,
    model_lease: dict[str, Any],
    process_scope_name: str,
) -> None:
    lineage_text = os.environ.get("AGENT_GUI_HYBRID_LINEAGE_JSON", "").strip()
    try:
        lineage = json.loads(lineage_text)
    except json.JSONDecodeError as error:
        raise RuntimeError("Hybrid Qwen lineage is unavailable") from error
    document = seal_immutable({
        "contract_version": "hybrid_qwen_model_owner_v1",
        "state": "acquired",
        "model_request_id": request_id,
        "lineage": lineage,
        "process_scope_name": process_scope_name,
        "model_lease": deepcopy(model_lease),
        "profile": _profile_from_qwen_lease(model_lease),
        "release_result": None,
        "tombstone_sha256": None,
        "scope_cleanup": None,
    })
    _write_hybrid_qwen_runtime(path, document)


def _profile_from_qwen_lease(model_lease: dict[str, Any]) -> dict[str, Any]:
    with _qwen_lease_lock():
        state = _load_qwen_lease_state(str(model_lease.get("incarnation_id") or ""))
    if not isinstance(state, dict) or not isinstance(state.get("profile"), dict):
        raise RuntimeError("Hybrid Qwen profile ownership is unavailable")
    return deepcopy(state["profile"])


def _load_qwen_runtime_owner(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Hybrid Qwen owner is unreadable") from error
    if (
        not isinstance(document, dict)
        or document.get("content_sha256") != content_sha256(document)
        or document.get("contract_version") not in {
            "hybrid_qwen_model_owner_v1",
            "hybrid_supervised_provider_runtime_v1",
            "hybrid_qwen_acquisition_intent_v1",
            "hybrid_qwen_aborted_acquisition_v1",
        }
        or document.get("state") not in {
            "acquiring", "starting", "acquired", "released", "aborted"
        }
        or (
            document.get("contract_version") == "hybrid_supervised_provider_runtime_v1"
            and document.get("provider") != "qwen"
        )
    ):
        raise RuntimeError("Hybrid Qwen owner is invalid")
    return document


def _write_hybrid_qwen_runtime(path: Path, document: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def qwen_model_lease_is_active(model_lease: object) -> bool:
    if not isinstance(model_lease, dict):
        return False
    incarnation_id = str(model_lease.get("incarnation_id") or "")
    if not incarnation_id:
        return False
    with _qwen_lease_lock():
        state = _load_qwen_lease_state(incarnation_id)
        return _find_exact_lease(state, model_lease) is not None


def observe_qwen_model_request_cleanup(request_id: str) -> dict[str, Any]:
    """按 acquisition→lease 锁序观察一个 benchmark Qwen 清理快照。"""
    normalized_request_id = _normalized_qwen_request_id(request_id)
    pending = {
        "contract_version": "qwen_model_request_cleanup_observation_v1",
        "status": "cleanup_pending",
        "outcome": "indeterminate",
        "model_request_id": normalized_request_id,
    }
    with _qwen_acquisition_lock():
        try:
            owner = _load_qwen_acquisition_owner(normalized_request_id)
            intent = _load_qwen_acquisition_intent(normalized_request_id)
            if (
                _qwen_content_ref(intent) != owner["acquisition_intent_ref"]
                or intent["runtime_owner_ref"] != owner["runtime_owner_ref"]
            ):
                return pending
            ledger = _load_qwen_model_request_materialization_ledger(
                normalized_request_id,
                acquisition_intent_ref=owner["acquisition_intent_ref"],
                runtime_owner_ref=owner["runtime_owner_ref"],
            )
        except (OSError, RuntimeError, ValueError, UnicodeError, json.JSONDecodeError):
            return pending
        with _qwen_lease_lock():
            try:
                active_matches = _find_qwen_owner_leases_locked(normalized_request_id)
                terminal_owner = _load_qwen_owner_tombstone(normalized_request_id)
                binding = (
                    _load_qwen_acquisition_lease_binding(
                        normalized_request_id,
                        owner=owner,
                    )
                    if ledger.get("state") == "materialization_possible"
                    else None
                )
                lease_state_snapshot = (
                    _load_qwen_acquisition_lease_state_snapshot(
                        normalized_request_id,
                        binding=binding,
                    )
                    if binding is not None
                    else None
                )
                candidate = _build_qwen_model_request_cleanup_receipt_locked(
                    normalized_request_id,
                    owner=owner,
                    ledger=ledger,
                    active_matches=active_matches,
                    terminal_owner=terminal_owner,
                    binding=binding,
                    lease_state_snapshot=lease_state_snapshot,
                )
                if candidate is None:
                    return pending
                receipt_path = _qwen_acquisition_artifact_paths(normalized_request_id)[
                    "cleanup_receipt"
                ]
                existing = _load_optional_qwen_sealed_artifact(receipt_path)
                if existing is None:
                    _write_qwen_acquisition_artifact(receipt_path, candidate)
                elif existing != candidate:
                    return pending
                return deepcopy(candidate)
            except (OSError, RuntimeError, ValueError, UnicodeError, json.JSONDecodeError):
                return pending


def _build_qwen_model_request_cleanup_receipt_locked(
    request_id: str,
    *,
    owner: dict[str, Any],
    ledger: dict[str, Any],
    active_matches: list[tuple[dict[str, Any], dict[str, Any]]],
    terminal_owner: dict[str, Any] | None,
    binding: dict[str, Any] | None,
    lease_state_snapshot: dict[str, Any] | None,
) -> dict[str, Any] | None:
    no_active = seal_immutable(
        {
            "contract_version": "qwen_model_request_no_active_lease_observation_v1",
            "model_request_id": request_id,
            "active_lease_count": len(active_matches),
        }
    )
    if active_matches:
        return None
    paths = _qwen_acquisition_artifact_paths(request_id)
    if ledger["state"] == "aborted_never_materialized":
        if terminal_owner is not None:
            return None
        tombstone = _load_optional_qwen_sealed_artifact(paths["aborted_tombstone"])
        abort_result = _load_optional_qwen_sealed_artifact(paths["abort"])
        if (
            not isinstance(tombstone, dict)
            or set(tombstone)
            != {
                "contract_version",
                "model_request_id",
                "acquisition_intent_ref",
                "runtime_owner_ref",
                "materialization_ledger_ref",
                "reason",
                "historical_process_identity",
                "historical_socket_ref",
                "historical_job_scope_ref",
                "content_sha256",
            }
            or tombstone.get("contract_version")
            != "benchmark_provider_aborted_acquisition_tombstone_v1"
            or tombstone.get("model_request_id") != request_id
            or tombstone.get("acquisition_intent_ref")
            != owner["acquisition_intent_ref"]
            or tombstone.get("runtime_owner_ref") != owner["runtime_owner_ref"]
            or tombstone.get("materialization_ledger_ref")
            != _qwen_content_ref(ledger)
            or tombstone.get("historical_process_identity") is not None
            or tombstone.get("historical_socket_ref") is not None
            or tombstone.get("historical_job_scope_ref") is not None
            or not isinstance(abort_result, dict)
            or set(abort_result)
            != {
                "contract_version",
                "model_request_id",
                "acquisition_intent_ref",
                "runtime_owner_ref",
                "materialization_ledger_ref",
                "owner_tombstone_ref",
                "reason",
                "owner_state",
                "content_sha256",
            }
            or abort_result.get("contract_version")
            != "benchmark_provider_acquisition_abort_v1"
            or abort_result.get("model_request_id") != request_id
            or abort_result.get("acquisition_intent_ref")
            != owner["acquisition_intent_ref"]
            or abort_result.get("runtime_owner_ref") != owner["runtime_owner_ref"]
            or abort_result.get("materialization_ledger_ref")
            != _qwen_content_ref(ledger)
            or abort_result.get("owner_tombstone_ref")
            != _qwen_content_ref(tombstone)
            or abort_result.get("reason") != tombstone.get("reason")
            or abort_result.get("owner_state") != "acquisition_aborted"
        ):
            return None
        owner_tombstone_ref = _qwen_content_ref(tombstone)
        receipt = {
            "contract_version": "qwen_model_request_cleanup_receipt_v1",
            "outcome": "verified_not_acquired",
            "model_request_id": request_id,
            "acquisition_intent_ref": deepcopy(owner["acquisition_intent_ref"]),
            "runtime_owner_ref": deepcopy(owner["runtime_owner_ref"]),
            "lease_ref": None,
            "profile_ref": None,
            "server_process_identity": None,
            "socket_ref": None,
            "job_scope_ref": None,
            "finalization_token": None,
            "lease_state_ref": None,
            "owner_tombstone_ref": deepcopy(owner_tombstone_ref),
            "release_reason": tombstone["reason"],
            "termination_observation_ref": None,
            "scope_stable_zero_ref": None,
            "listener_stable_zero_ref": None,
            "no_active_lease_observation_ref": _qwen_content_ref(no_active),
            "no_owned_runtime_observation_ref": deepcopy(owner_tombstone_ref),
        }
        return _validate_qwen_model_request_cleanup_receipt(
            seal_immutable(receipt), owner=owner, ledger=ledger
        )
    if (
        ledger["state"] != "materialization_possible"
        or terminal_owner is None
        or binding is None
        or lease_state_snapshot is None
    ):
        return None
    release_result = terminal_owner.get("release_result")
    lease = release_result.get("lease") if isinstance(release_result, dict) else None
    release_result_fields = {
        "status",
        "lease",
        "shared_server_retained",
        "server_termination",
        "release",
        "after",
        "process_identity",
        "hybrid_descendant_cleanup",
        "hybrid_process_scope_name",
        "hybrid_process_scope_acquisition",
        "hybrid_process_scope_cleanup",
    }
    if not isinstance(release_result, dict) or set(release_result) != release_result_fields:
        return None
    try:
        exact_lease = _validate_exact_qwen_cleanup_evidence(release_result, lease)
    except ValueError:
        return None
    if (
        exact_lease.get("owner_request_id") != request_id
        or terminal_owner.get("profile_id") != exact_lease.get("profile_id")
        or terminal_owner.get("lease_id") != exact_lease.get("lease_id")
        or terminal_owner.get("incarnation_id") != exact_lease.get("incarnation_id")
        or terminal_owner.get("server_termination")
        != release_result.get("server_termination")
        or release_result.get("process_identity")
        != exact_lease.get("server_process_identity")
        or not isinstance(terminal_owner.get("finalization_token"), str)
        or not terminal_owner["finalization_token"]
        or binding.get("lease_ref") != _qwen_content_ref(exact_lease)
        or binding.get("profile_ref")
        != {"content_sha256": exact_lease.get("profile_sha256")}
        or binding.get("server_process_identity")
        != exact_lease.get("server_process_identity")
    ):
        return None
    process_identity = exact_lease["server_process_identity"]
    process_probe = _probe_exact_qwen_process(process_identity)
    if (
        process_probe.get("status") != "proven_absent"
        or process_probe.get("identity") is not None
    ):
        return None
    parsed = urlsplit(str(exact_lease.get("server_base_url") or ""))
    port = int(parsed.port or 0)
    socket_identity = {"host": str(parsed.hostname or ""), "port": port}
    if (
        not _valid_qwen_server_socket(socket_identity)
        or binding.get("socket_ref")
        != _qwen_content_ref(seal_immutable(socket_identity))
    ):
        return None
    listener_pids = _listening_pids_for_port(port) if port > 0 else []
    if listener_pids:
        return None
    scope_acquisition = release_result.get("hybrid_process_scope_acquisition")
    scope_cleanup = release_result.get("hybrid_process_scope_cleanup")
    descendant_cleanup = release_result.get("hybrid_descendant_cleanup")
    if (
        not isinstance(scope_acquisition, dict)
        or set(scope_acquisition)
        != {
            "contract_version",
            "scope_name",
            "member_pids",
            "server_process_identity",
        }
        or process_identity.get("pid") not in scope_acquisition.get("member_pids", [])
        or scope_acquisition.get("server_process_identity") != process_identity
        or not isinstance(scope_cleanup, dict)
        or scope_cleanup.get("cleanup_status") != "verified"
        or scope_cleanup.get("scope_name") != scope_acquisition.get("scope_name")
        or scope_cleanup.get("authority") != "windows_job_object"
        or scope_cleanup.get("member_pids_after") != []
        or scope_cleanup.get("member_identities_after") != []
        or scope_cleanup.get("active_listeners_after") != []
        or scope_cleanup.get("pid_file_after") is not None
        or not isinstance(scope_cleanup.get("stable_zero_observations"), int)
        or scope_cleanup["stable_zero_observations"] < 3
        or set(scope_cleanup) != _QWEN_SCOPE_CLEANUP_FIELDS
        or binding.get("job_scope_ref")
        != _qwen_content_ref(seal_immutable(scope_acquisition))
        or release_result.get("hybrid_process_scope_name")
        != scope_acquisition.get("scope_name")
        or not isinstance(descendant_cleanup, dict)
        or set(descendant_cleanup)
        != {
            "status",
            "descendant_identities",
            "probes",
            "process_scope_cleanup",
        }
        or descendant_cleanup.get("status") != "verified"
        or descendant_cleanup.get("descendant_identities") != []
        or descendant_cleanup.get("probes") != []
        or descendant_cleanup.get("process_scope_cleanup") != scope_cleanup
    ):
        return None
    release_observation = _load_optional_qwen_sealed_artifact(
        paths["release_observation"]
    )
    if (
        not isinstance(release_observation, dict)
        or set(release_observation)
        != {
            "contract_version",
            "model_request_id",
            "lease_ref",
            "finalization_token",
            "release_reason",
            "release_result_ref",
            "content_sha256",
        }
        or release_observation.get("contract_version")
        != "qwen_model_request_exact_release_observation_v1"
        or release_observation.get("model_request_id") != request_id
        or release_observation.get("lease_ref") != _qwen_content_ref(exact_lease)
        or release_observation.get("finalization_token")
        != terminal_owner.get("finalization_token")
        or release_observation.get("release_result_ref")
        != _qwen_content_ref(seal_immutable(release_result))
        or not isinstance(release_observation.get("release_reason"), str)
        or not release_observation["release_reason"]
    ):
        return None
    try:
        termination_parent = _load_qwen_termination_observation_parent(
            request_id,
            model_lease=exact_lease,
            release_result=release_result,
            finalization_token=terminal_owner["finalization_token"],
        )
    except ValueError:
        return None
    receipt = {
        "contract_version": "qwen_model_request_cleanup_receipt_v1",
        "outcome": "verified_exact_process_exited",
        "model_request_id": request_id,
        "acquisition_intent_ref": deepcopy(owner["acquisition_intent_ref"]),
        "runtime_owner_ref": deepcopy(owner["runtime_owner_ref"]),
        "lease_ref": _qwen_content_ref(exact_lease),
        "profile_ref": deepcopy(binding["profile_ref"]),
        "server_process_identity": deepcopy(process_identity),
        "socket_ref": deepcopy(binding["socket_ref"]),
        "job_scope_ref": deepcopy(binding["job_scope_ref"]),
        "finalization_token": terminal_owner.get("finalization_token"),
        "lease_state_ref": deepcopy(binding["lease_state_ref"]),
        "owner_tombstone_ref": _qwen_content_ref(seal_immutable(terminal_owner)),
        "release_reason": release_observation["release_reason"],
        "termination_observation_ref": _qwen_content_ref(termination_parent),
        "scope_stable_zero_ref": _qwen_content_ref(seal_immutable(scope_cleanup)),
        "listener_stable_zero_ref": _qwen_content_ref(seal_immutable(scope_cleanup)),
        "no_active_lease_observation_ref": _qwen_content_ref(no_active),
        "no_owned_runtime_observation_ref": None,
    }
    return _validate_qwen_model_request_cleanup_receipt(
        seal_immutable(receipt), owner=owner, ledger=ledger
    )


def _validate_qwen_model_request_cleanup_receipt(
    receipt: object,
    *,
    owner: dict[str, Any],
    ledger: dict[str, Any],
) -> dict[str, Any]:
    if (
        not isinstance(receipt, dict)
        or set(receipt) != _QWEN_CLEANUP_RECEIPT_FIELDS
        or receipt.get("content_sha256") != content_sha256(receipt)
        or receipt.get("contract_version")
        != "qwen_model_request_cleanup_receipt_v1"
        or receipt.get("model_request_id") != owner.get("model_request_id")
        or receipt.get("acquisition_intent_ref")
        != owner.get("acquisition_intent_ref")
        or receipt.get("runtime_owner_ref") != owner.get("runtime_owner_ref")
    ):
        raise ValueError("Qwen cleanup sidecar identity is invalid")
    outcome = receipt.get("outcome")
    if outcome == "verified_not_acquired":
        if ledger.get("state") != "aborted_never_materialized":
            raise ValueError("Qwen not-acquired receipt has incompatible ledger")
        null_fields = {
            "lease_ref",
            "profile_ref",
            "server_process_identity",
            "socket_ref",
            "job_scope_ref",
            "finalization_token",
            "lease_state_ref",
            "termination_observation_ref",
            "scope_stable_zero_ref",
            "listener_stable_zero_ref",
        }
        if any(receipt.get(field) is not None for field in null_fields):
            raise ValueError("Qwen not-acquired receipt shape is invalid")
        if (
            receipt.get("owner_tombstone_ref") is None
            or receipt.get("no_active_lease_observation_ref") is None
            or receipt.get("no_owned_runtime_observation_ref") is None
        ):
            raise ValueError("Qwen not-acquired receipt evidence is incomplete")
    elif outcome == "verified_exact_process_exited":
        if ledger.get("state") != "materialization_possible":
            raise ValueError("Qwen process-exited receipt has incompatible ledger")
        required = {
            "lease_ref",
            "profile_ref",
            "server_process_identity",
            "socket_ref",
            "job_scope_ref",
            "finalization_token",
            "lease_state_ref",
            "owner_tombstone_ref",
            "release_reason",
            "termination_observation_ref",
            "scope_stable_zero_ref",
            "listener_stable_zero_ref",
            "no_active_lease_observation_ref",
        }
        if any(receipt.get(field) is None for field in required):
            raise ValueError("Qwen process-exited receipt evidence is incomplete")
        if receipt.get("no_owned_runtime_observation_ref") is not None:
            raise ValueError("Qwen acquired owner cannot be classified as not acquired")
    else:
        raise ValueError("Qwen cleanup sidecar outcome is invalid")
    return deepcopy(receipt)


def release_qwen_model_server(
    *,
    sealed_artifact: dict[str, Any],
    omni_inventory: dict[str, Any],
    model_lease: dict[str, Any],
) -> dict[str, Any]:
    _validate_sealed_qwen_release_artifact(sealed_artifact, omni_inventory)
    return _release_exact_qwen_lease(model_lease, reason="completed")


def build_qwen_cleanup_receipt(
    *,
    release_result: object,
    model_lease: object,
) -> dict[str, Any]:
    """只在既有生命周期已经证明精确进程退出后签发清理回执。"""
    lease = _validate_exact_qwen_cleanup_evidence(release_result, model_lease)
    result = release_result
    assert isinstance(result, dict)
    return seal_immutable(
        {
            "contract_version": "hybrid_qwen_cleanup_receipt_v1",
            "provider": "qwen",
            "cleanup_status": "verified_exact_process_exited",
            "lease": deepcopy(lease),
            "process_identity": deepcopy(result["process_identity"]),
            "termination_proof": deepcopy(result["release"]),
            "server_termination": result["server_termination"],
        }
    )


def validate_qwen_cleanup_receipt(receipt: object) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise ValueError("sealed Qwen cleanup receipt is required")
    normalized = deepcopy(receipt)
    digest = normalized.pop("content_sha256", None)
    if digest != content_sha256(receipt):
        raise ValueError("sealed Qwen cleanup receipt is required")
    if set(normalized) != {
        "contract_version",
        "provider",
        "cleanup_status",
        "lease",
        "process_identity",
        "termination_proof",
        "server_termination",
    }:
        raise ValueError("Qwen cleanup receipt contract is invalid")
    if (
        normalized.get("contract_version") != "hybrid_qwen_cleanup_receipt_v1"
        or normalized.get("provider") != "qwen"
        or normalized.get("cleanup_status") != "verified_exact_process_exited"
        or normalized.get("server_termination")
        not in {"verified_exact_process_exited", "verified_exact_process_proven_absent_on_retry"}
    ):
        raise ValueError("Qwen cleanup receipt does not prove exact cleanup")
    lease = normalized.get("lease")
    if not isinstance(lease, dict) or set(lease) != _QWEN_LEASE_FIELDS:
        raise ValueError("Qwen cleanup receipt lease is invalid")
    if canonical_json_bytes(normalized.get("process_identity")) != canonical_json_bytes(
        lease.get("server_process_identity")
    ):
        raise ValueError("Qwen cleanup receipt process identity mismatch")
    proof = normalized.get("termination_proof")
    if not isinstance(proof, dict) or proof.get("status") != "proven_absent":
        raise ValueError("Qwen cleanup receipt termination proof is indeterminate")
    if proof.get("identity") is not None and canonical_json_bytes(
        proof.get("identity")
    ) != canonical_json_bytes(normalized.get("process_identity")):
        raise ValueError("Qwen cleanup receipt termination identity mismatch")
    return deepcopy(receipt)


def observe_hybrid_qwen_cleanup(
    receipt: object,
    *,
    lineage: dict[str, Any],
    predecessor_sha256: str,
    provider_result_sha256: str,
) -> dict[str, Any]:
    """从既有精确 Qwen 回执和当前 OS/lease 事实构造 Hybrid observer inventory。"""
    from app.learn.hybrid.gpu_lifecycle import validate_hybrid_lineage

    exact_lineage = validate_hybrid_lineage(lineage)
    from app.learn.hybrid.windows_process_scope import (
        observe_process_scope_cleanup,
        process_scope_name,
    )

    expected_scope_name = process_scope_name(exact_lineage, "qwen")
    exact_receipt = validate_qwen_cleanup_receipt(receipt)
    lease = exact_receipt["lease"]
    process_identity = exact_receipt["process_identity"]
    owner_receipt = _load_qwen_owner_tombstone(
        str(lease.get("owner_request_id") or "")
    )
    lifecycle_verified = False
    descendant_cleanup: dict[str, Any] = {
        "status": "indeterminate",
        "descendant_identities": [],
        "probes": [],
    }
    if (
        isinstance(owner_receipt, dict)
        and owner_receipt.get("lease_id") == lease.get("lease_id")
        and owner_receipt.get("incarnation_id") == lease.get("incarnation_id")
        and owner_receipt.get("profile_id") == lease.get("profile_id")
        and isinstance(owner_receipt.get("release_result"), dict)
    ):
        try:
            _validate_exact_qwen_cleanup_evidence(
                owner_receipt["release_result"], lease
            )
        except ValueError:
            lifecycle_verified = False
        else:
            observed_descendants = owner_receipt["release_result"].get(
                "hybrid_descendant_cleanup"
            )
            if isinstance(observed_descendants, dict):
                descendant_cleanup = deepcopy(observed_descendants)
            persisted_scope_cleanup = owner_receipt["release_result"].get(
                "hybrid_process_scope_cleanup"
            )
            persisted_scope_acquisition = owner_receipt["release_result"].get(
                "hybrid_process_scope_acquisition"
            )
            identities = descendant_cleanup.get("descendant_identities")
            probes = descendant_cleanup.get("probes")
            lifecycle_verified = (
                descendant_cleanup.get("status") == "verified"
                and isinstance(identities, list)
                and isinstance(probes, list)
                and len(identities) == len(probes)
                and all(
                    _valid_process_identity(identity)
                    and isinstance(probe, dict)
                    and probe.get("status") == "proven_absent"
                    for identity, probe in zip(identities, probes)
                )
                and owner_receipt["release_result"].get(
                    "hybrid_process_scope_name"
                )
                == expected_scope_name
                and isinstance(persisted_scope_cleanup, dict)
                and persisted_scope_cleanup.get("scope_name") == expected_scope_name
                and persisted_scope_cleanup.get("cleanup_status") == "verified"
                and isinstance(persisted_scope_acquisition, dict)
                and persisted_scope_acquisition.get("scope_name")
                == expected_scope_name
                and process_identity.get("pid")
                in persisted_scope_acquisition.get("member_pids", [])
            )
    process_probe = _probe_exact_qwen_process(process_identity)
    parsed = urlsplit(str(lease.get("server_base_url") or ""))
    port = int(parsed.port or 0)
    listener_pids = _listening_pids_for_port(port) if port > 0 else []
    lease_active = qwen_model_lease_is_active(lease)
    observable = process_probe.get("status") != "unobservable"
    provider_processes = (
        [deepcopy(process_identity)]
        if process_probe.get("status") == "exact_live"
        else []
    )
    listeners = [{"port": port, "pid": pid} for pid in listener_pids]
    lease_files = [f"active-qwen-lease:{lease['lease_id']}"] if lease_active else []
    scope_cleanup = observe_process_scope_cleanup(
        expected_scope_name,
        terminate=False,
        listener_ports=[port] if port > 0 else [],
        stable_zero_observations=3,
    )
    verified = (
        lifecycle_verified
        and scope_cleanup.get("cleanup_status") == "verified"
        and observable
        and not provider_processes
        and not listeners
        and not lease_files
    )
    return {
        "contract_version": "hybrid_provider_process_inventory_v2",
        "provider": "qwen",
        "observer_contract": "hybrid_qwen_cleanup_observer_v1",
        "release_status": "verified" if verified else "failed",
        "termination_reason": "completed" if verified else "cleanup_failed",
        "lineage": exact_lineage,
        "provider_lease_identity": {
            "lease_id": lease["lease_id"],
            "incarnation_id": lease["incarnation_id"],
            "profile_id": lease["profile_id"],
            "server_process_identity": deepcopy(process_identity),
            "process_scope_name": expected_scope_name,
        },
        "predecessor_sha256": predecessor_sha256,
        "provider_result_sha256": provider_result_sha256,
        "provider_processes_after": provider_processes,
        "helper_processes_after": [
            deepcopy(identity)
            for identity, probe in zip(
                descendant_cleanup.get("descendant_identities", []),
                descendant_cleanup.get("probes", []),
            )
            if isinstance(probe, dict) and probe.get("status") == "exact_live"
        ],
        "orphan_descendant_pids": [
            int(identity["pid"])
            for identity, probe in zip(
                descendant_cleanup.get("descendant_identities", []),
                descendant_cleanup.get("probes", []),
            )
            if isinstance(identity, dict)
            and isinstance(identity.get("pid"), int)
            and isinstance(probe, dict)
            and probe.get("status") == "exact_live"
        ],
        "active_listeners_after": listeners,
        "lease_files_after": lease_files,
        "source_cleanup_evidence": {
            "contract_version": "hybrid_qwen_cleanup_evidence_v2",
            "status": "verified" if verified else "failed",
            "qwen_cleanup_receipt": exact_receipt,
            "owner_lifecycle_receipt": deepcopy(owner_receipt),
            "lifecycle_verified": lifecycle_verified,
            "descendant_cleanup": descendant_cleanup,
            "process_probe": process_probe,
            "lease_active": lease_active,
            "process_scope_cleanup": scope_cleanup,
        },
    }


def _validate_exact_qwen_cleanup_evidence(
    release_result: object,
    model_lease: object,
) -> dict[str, Any]:
    if not isinstance(model_lease, dict) or set(model_lease) != _QWEN_LEASE_FIELDS:
        raise ValueError("exact Qwen model lease is required for cleanup receipt")
    if not isinstance(release_result, dict):
        raise ValueError("Qwen release evidence is required")
    if (
        release_result.get("status") != "released"
        or release_result.get("shared_server_retained") is not False
        or release_result.get("server_termination")
        not in {"verified_exact_process_exited", "verified_exact_process_proven_absent_on_retry"}
        or release_result.get("release", {}).get("status") != "proven_absent"
    ):
        raise ValueError("Qwen release did not prove exact process cleanup")
    if canonical_json_bytes(release_result.get("lease")) != canonical_json_bytes(model_lease):
        raise ValueError("Qwen release lease mismatch")
    if canonical_json_bytes(release_result.get("process_identity")) != canonical_json_bytes(
        model_lease.get("server_process_identity")
    ):
        raise ValueError("Qwen release process identity mismatch")
    return deepcopy(model_lease)


def release_managed_qwen_model_lease(
    model_lease: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    """释放已完成的受管 Qwen 消费者租约，不绕过共享引用计数。"""
    return reconcile_qwen_model_lease_failure(
        model_lease=model_lease,
        compute_completed=False,
        reason=reason,
    )


def release_scoped_qwen_model_lease(
    model_lease: dict[str, Any], reason: str
) -> dict[str, Any]:
    """释放不带 benchmark acquisition artifact 的 scoped Qwen 租约。"""
    return _release_exact_qwen_lease(
        model_lease,
        reason=reason,
        persist_benchmark_artifacts=False,
    )


def mark_qwen_model_response_body_complete(
    *,
    model_lease: dict[str, Any] | None = None,
    request_id: str | None = None,
    request_attempt: int | None = None,
) -> bool:
    """仅在提供者响应体完整读取后推进精确 Qwen 租约。"""
    selected_lease = deepcopy(model_lease) if isinstance(model_lease, dict) else None
    if selected_lease is None:
        owner_request_id = str(request_id or "").strip()
        if not owner_request_id:
            return False
        match = _find_qwen_lease_by_owner(owner_request_id)
        if match is None:
            return False
        selected_lease = match[1]
    _mark_qwen_model_compute_complete(
        selected_lease,
        request_attempt=request_attempt,
    )
    return True


def mark_qwen_model_request_in_flight(
    *,
    model_lease: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> int | None:
    """在每次真实 HTTP 派发前重新打开精确 Qwen 请求生命周期。"""
    selected_lease = deepcopy(model_lease) if isinstance(model_lease, dict) else None
    if selected_lease is None:
        owner_request_id = str(request_id or "").strip()
        if not owner_request_id:
            return None
        match = _find_qwen_lease_by_owner(owner_request_id)
        if match is None:
            return None
        selected_lease = match[1]
    return _mark_qwen_model_request_in_flight(selected_lease)


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
    persist_benchmark_artifacts: bool = True,
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
                if persist_benchmark_artifacts:
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
                if persist_benchmark_artifacts:
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
            descendants, descendants_observable = _descendant_identities_for_parents(
                [state["incarnation"]["server_process_identity"]]
            )
            if not descendants_observable:
                raise RuntimeError(
                    "Qwen descendant process inventory is unobservable before stop"
                )
            state["finalization"]["descendant_identities"] = descendants
            _write_qwen_lease_state(state)
            stop_state = deepcopy(state)
    if resume_state is not None:
        return _resume_qwen_finalization(
            resume_state,
            token=resume_token,
            revision=resume_revision,
            reason=reason,
            persist_benchmark_artifacts=persist_benchmark_artifacts,
        )
    return _stop_and_finalize_qwen_incarnation(
        stop_state,
        token=token,
        revision=revision,
        persist_benchmark_artifacts=persist_benchmark_artifacts,
    )


def _stop_and_finalize_qwen_incarnation(
    state: dict[str, Any],
    *,
    token: str,
    revision: int,
    persist_benchmark_artifacts: bool = True,
) -> dict[str, Any]:
    incarnation = state["incarnation"]
    expected_process = incarnation["server_process_identity"]
    finalization = state.get("finalization")
    known_descendants = (
        deepcopy(finalization.get("descendant_identities"))
        if isinstance(finalization, dict)
        and isinstance(finalization.get("descendant_identities"), list)
        else []
    )
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
    process_scope_name = state.get("process_scope_name")
    scope_cleanup = None
    if isinstance(process_scope_name, str) and process_scope_name:
        from app.learn.hybrid.windows_process_scope import observe_process_scope_cleanup

        parsed = urlsplit(str(incarnation.get("server_base_url") or ""))
        port = int(parsed.port or 0)
        scope_cleanup = observe_process_scope_cleanup(
            process_scope_name,
            terminate=True,
            listener_ports=[port] if port > 0 else [],
            pid_file=model_profile_pid_path(state["profile"]),
            remove_owned_pid_file=True,
            stable_zero_observations=3,
        )
        descendant_cleanup = {
            "status": (
                "verified"
                if scope_cleanup.get("cleanup_status") == "verified"
                else "indeterminate"
            ),
            "descendant_identities": [],
            "probes": [],
            "process_scope_cleanup": scope_cleanup,
        }
    else:
        descendant_cleanup = _observe_known_qwen_descendant_cleanup(known_descendants)
    if descendant_cleanup["status"] != "verified":
        _record_qwen_finalization_failure(
            state, token, revision, "descendant_cleanup_unverified"
        )
        raise RuntimeError("Qwen descendant cleanup is unverified")
    health = check_model_server(state["profile"])
    result = {
        "status": "released",
        "lease": _qwen_public_lease(state["leases"][0]),
        "shared_server_retained": False,
        "server_termination": "verified_exact_process_exited",
        "release": release,
        "after": health,
        "process_identity": expected_process,
        "hybrid_descendant_cleanup": descendant_cleanup,
        "hybrid_process_scope_name": process_scope_name,
        "hybrid_process_scope_acquisition": deepcopy(
            state.get("process_scope_acquisition")
        ),
        "hybrid_process_scope_cleanup": scope_cleanup,
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
        model_lease=_qwen_public_lease(state["leases"][0]),
        persist_benchmark_artifacts=persist_benchmark_artifacts,
    )


def _persist_qwen_termination_proof(
    state: dict[str, Any],
    *,
    token: str,
    revision: int,
    result: dict[str, Any],
) -> dict[str, Any]:
    incarnation_id = state["incarnation"]["incarnation_id"]
    model_lease = _qwen_public_lease(state["leases"][0])
    with _qwen_lease_lock():
        current_state = _load_qwen_lease_state(incarnation_id)
        if current_state is None:
            return _recover_qwen_finalization_tombstone(model_lease, token=token)
        finalization = current_state.get("finalization") if isinstance(current_state, dict) else None
        if (
            not isinstance(finalization, dict)
            or finalization.get("token") != token
            or finalization.get("revision") != revision
        ):
            raise RuntimeError("Qwen finalization token changed")
        if finalization.get("phase") == "termination_proven":
            existing_result = finalization.get("termination_result")
            if not isinstance(existing_result, dict):
                raise RuntimeError("Qwen terminal finalization evidence is unavailable")
            return deepcopy(existing_result)
        if finalization.get("phase") not in _QWEN_UNPROVEN_FINALIZATION_PHASES:
            raise RuntimeError("Qwen finalization phase cannot accept terminal proof")
        finalization["phase"] = "termination_proven"
        finalization["termination_result"] = deepcopy(result)
        current_state["revision"] = max(int(current_state.get("revision") or 0), revision)
        _write_qwen_lease_state(current_state)
        return deepcopy(result)


def _finish_qwen_finalization_cleanup(
    incarnation_id: str,
    *,
    token: str,
    revision: int,
    model_lease: dict[str, Any],
    persist_benchmark_artifacts: bool = True,
) -> dict[str, Any]:
    with _qwen_lease_lock():
        current_state = _load_qwen_lease_state(incarnation_id)
        if current_state is None:
            return _recover_qwen_finalization_tombstone(model_lease, token=token)
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
        lease = _qwen_public_lease(current_state["leases"][0])
        if lease != model_lease:
            raise RuntimeError("Qwen finalization lease changed before cleanup")
        if persist_benchmark_artifacts:
            _write_qwen_benchmark_release_observation(
                lease,
                result=result,
                finalization_token=token,
                release_reason=str(finalization.get("reason") or ""),
            )
            _write_qwen_owner_tombstone(
                lease,
                result=result,
                finalization_token=token,
            )
        _delete_qwen_lease_state(incarnation_id)
    return result


def _validate_qwen_termination_observation(value: object) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != {"status", "identity", "reason"}
        or value.get("status") != "proven_absent"
        or value.get("identity") is not None
        or value.get("reason") not in {"no_such_process", "not_running"}
    ):
        raise ValueError("Qwen exact termination observation is invalid")
    return deepcopy(value)


def _load_qwen_termination_observation_parent(
    request_id: str,
    *,
    model_lease: Mapping[str, object],
    release_result: Mapping[str, object],
    finalization_token: str,
) -> dict[str, Any]:
    parent = _load_optional_qwen_sealed_artifact(
        _qwen_acquisition_artifact_paths(request_id)["termination_observation"]
    )
    fields = {
        "contract_version",
        "model_request_id",
        "lease_ref",
        "finalization_token",
        "release_result_ref",
        "termination_observation",
        "content_sha256",
    }
    if (
        not isinstance(parent, dict)
        or set(parent) != fields
        or parent.get("contract_version")
        != "qwen_model_request_exact_termination_observation_v1"
        or parent.get("model_request_id") != request_id
        or parent.get("lease_ref") != _qwen_content_ref(model_lease)
        or parent.get("finalization_token") != finalization_token
        or parent.get("release_result_ref")
        != _qwen_content_ref(seal_immutable(dict(release_result)))
    ):
        raise ValueError("Qwen exact termination parent is invalid")
    termination = _validate_qwen_termination_observation(
        parent.get("termination_observation")
    )
    if termination != release_result.get("release"):
        raise ValueError("Qwen exact termination parent lineage is invalid")
    return parent


def _write_qwen_benchmark_release_observation(
    model_lease: dict[str, Any],
    *,
    result: dict[str, Any],
    finalization_token: str,
    release_reason: str,
) -> None:
    request_id = str(model_lease.get("owner_request_id") or "")
    paths = _qwen_acquisition_artifact_paths(request_id)
    if not paths["owner"].exists():
        return
    termination = _validate_qwen_termination_observation(result.get("release"))
    release_result_ref = _qwen_content_ref(seal_immutable(result))
    termination_parent = seal_immutable(
        {
            "contract_version": "qwen_model_request_exact_termination_observation_v1",
            "model_request_id": request_id,
            "lease_ref": _qwen_content_ref(model_lease),
            "finalization_token": finalization_token,
            "release_result_ref": release_result_ref,
            "termination_observation": termination,
        }
    )
    existing_termination = _load_optional_qwen_sealed_artifact(
        paths["termination_observation"]
    )
    if existing_termination is None:
        _write_qwen_acquisition_artifact(
            paths["termination_observation"],
            termination_parent,
        )
    elif existing_termination != termination_parent:
        raise RuntimeError("Qwen exact termination observation conflicts")
    observation = seal_immutable(
        {
            "contract_version": "qwen_model_request_exact_release_observation_v1",
            "model_request_id": request_id,
            "lease_ref": _qwen_content_ref(model_lease),
            "finalization_token": finalization_token,
            "release_reason": release_reason,
            "release_result_ref": release_result_ref,
        }
    )
    existing = _load_optional_qwen_sealed_artifact(paths["release_observation"])
    if existing is None:
        _write_qwen_acquisition_artifact(paths["release_observation"], observation)
    elif existing != observation:
        raise RuntimeError("Qwen exact release observation conflicts")


def _resume_qwen_finalization(
    state: dict[str, Any],
    *,
    token: str,
    revision: int,
    reason: str,
    persist_benchmark_artifacts: bool = True,
) -> dict[str, Any]:
    finalization = state.get("finalization")
    if isinstance(finalization, dict) and finalization.get("phase") == "termination_proven":
        return _finish_qwen_finalization_cleanup(
            state["incarnation"]["incarnation_id"],
            token=token,
            revision=revision,
            model_lease=_qwen_public_lease(state["leases"][0]),
            persist_benchmark_artifacts=persist_benchmark_artifacts,
        )
    if not isinstance(finalization, dict):
        return _qwen_finalization_pending_result(state, reason=reason)
    proof = _probe_exact_qwen_process(state["incarnation"]["server_process_identity"])
    if proof.get("status") != "proven_absent":
        return _qwen_finalization_pending_result(state, reason=reason)
    known_descendants = finalization.get("descendant_identities")
    descendant_cleanup = _observe_known_qwen_descendant_cleanup(
        known_descendants if isinstance(known_descendants, list) else []
    )
    if descendant_cleanup["status"] != "verified":
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
        "hybrid_descendant_cleanup": descendant_cleanup,
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
        model_lease=_qwen_public_lease(state["leases"][0]),
        persist_benchmark_artifacts=persist_benchmark_artifacts,
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
        if (
            isinstance(finalization, dict)
            and finalization.get("token") == token
            and finalization.get("phase") in _QWEN_UNPROVEN_FINALIZATION_PHASES
        ):
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
        lifecycle_state = str(exact.get("lifecycle_state") or "unknown_in_flight")
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


def _mark_qwen_model_request_in_flight(model_lease: object) -> int:
    if not isinstance(model_lease, dict):
        raise ValueError("exact Qwen model lease is required")
    incarnation_id = str(model_lease.get("incarnation_id") or "")
    with _qwen_lease_lock():
        state = _load_qwen_lease_state(incarnation_id)
        exact = _find_exact_lease(state, model_lease)
        if exact is None:
            raise ValueError("exact Qwen model lease is not active")
        if isinstance(state.get("finalization"), dict):
            raise RuntimeError("Qwen server finalization already started before request")
        lifecycle_state = str(exact.get("lifecycle_state") or "unknown_in_flight")
        if lifecycle_state not in {
            "not_started",
            "request_in_flight",
            "compute_complete",
        }:
            raise RuntimeError("Qwen request lifecycle state is invalid")
        request_attempt = int(exact.get("request_attempt") or 0) + 1
        exact["lifecycle_state"] = "request_in_flight"
        exact["request_attempt"] = request_attempt
        exact.pop("completed_request_attempt", None)
        exact.pop("pending_reason", None)
        exact.pop("capability_blocker", None)
        exact.pop("reconciliation_trigger", None)
        state["revision"] += 1
        _write_qwen_lease_state(state)
        return request_attempt


def _mark_qwen_model_compute_complete(
    model_lease: object,
    *,
    request_attempt: int | None = None,
) -> None:
    if not isinstance(model_lease, dict):
        return
    incarnation_id = str(model_lease.get("incarnation_id") or "")
    with _qwen_lease_lock():
        state = _load_qwen_lease_state(incarnation_id)
        exact = _find_exact_lease(state, model_lease)
        if exact is None:
            raise ValueError("exact Qwen model lease is not active")
        active_attempt = int(exact.get("request_attempt") or 0)
        if request_attempt is not None and active_attempt != request_attempt:
            raise RuntimeError("Qwen response body completion attempt is stale")
        exact["lifecycle_state"] = "compute_complete"
        exact["completed_request_attempt"] = active_attempt
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
    lifecycle_state = str(exact.get("lifecycle_state") or "unknown_in_flight")
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

        if not isinstance(artifact.get("bindings"), list):
            raise ValueError("binding artifact is not a compact projection")
        wire_bindings: list[dict[str, Any]] = []
        for binding in artifact["bindings"]:
            if not isinstance(binding, dict):
                raise ValueError("binding artifact is not a compact projection")
            ambiguity = binding.get("ambiguity")
            confidence = binding.get("semantic_confidence")
            if ambiguity == "qwen_binding_ambiguous":
                status = "AMBIGUOUS"
            elif ambiguity == "qwen_binding_conflict":
                status = "CONFLICT"
            elif ambiguity is None:
                status = "BOUND" if confidence != 0 else "UNBOUND"
            else:
                raise ValueError("binding artifact is not a compact projection")
            wire_bindings.append(
                {
                    "candidate_id": binding.get("candidate_id"),
                    "role": binding.get("role"),
                    "label": binding.get("label"),
                    "binding_status": status,
                    "confidence": confidence,
                }
            )
        parsed = parse_qwen_candidate_bindings(
            {"bindings": wire_bindings},
            deepcopy(omni_inventory),
            context_ref=deepcopy(artifact.get("context_ref")),
        )
        if parsed != artifact:
            raise ValueError("binding artifact is not a compact projection")
    except ValueError as error:
        raise ValueError(
            f"sealed Qwen binding artifact is invalid compact projection: {error}"
        ) from error


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


def _attest_exact_qwen_socket_owner(
    server_socket: object,
    process_identity: object,
) -> bool:
    if (
        not _valid_qwen_server_socket(server_socket)
        or not _valid_process_identity(process_identity)
        or _current_process_identity(process_identity["pid"]) != process_identity
    ):
        return False
    expected_socket = (
        str(server_socket["host"]),
        int(server_socket["port"]),
    )
    try:
        connections = list(psutil.net_connections(kind="tcp"))
    except (psutil.AccessDenied, OSError):
        return False
    owners = {
        int(connection.pid)
        for connection in connections
        if connection.status == psutil.CONN_LISTEN
        and connection.laddr
        and connection.pid
        and (str(connection.laddr.ip), int(connection.laddr.port)) == expected_socket
    }
    return owners == {int(process_identity["pid"])}


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


def _normalized_qwen_request_id(request_id: object) -> str:
    normalized = str(request_id or "").strip()
    if not normalized:
        raise ValueError("Qwen model request identity is required")
    return normalized


def _qwen_content_ref(value: Mapping[str, object]) -> dict[str, str]:
    digest = value.get("content_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        digest = content_sha256(dict(value))
    return {"content_sha256": digest}


def _validate_qwen_content_ref(value: object) -> dict[str, str]:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"content_sha256"}
        or not isinstance(value.get("content_sha256"), str)
        or len(value["content_sha256"]) != 64
        or any(character not in "0123456789abcdef" for character in value["content_sha256"])
    ):
        raise ValueError("Qwen content reference is invalid")
    return {"content_sha256": value["content_sha256"]}


def _validate_qwen_runtime_owner(
    value: object, *, request_id: str
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("Qwen benchmark runtime owner is required")
    owner = deepcopy(dict(value))
    if (
        set(owner) != _QWEN_RUNTIME_OWNER_FIELDS
        or owner.get("contract_version") != "benchmark_provider_runtime_owner_v1"
        or owner.get("model_request_id") != request_id
        or owner.get("content_sha256") != content_sha256(owner)
        or any(
            not isinstance(owner.get(field), str) or not owner[field].strip()
            for field in {
                "authority_kind",
                "run_id",
                "stage",
                "operation_id",
                "worker_id",
                "model_request_id",
                "payload_sha256",
            }
        )
        or len(owner["payload_sha256"]) != 64
    ):
        raise ValueError("Qwen benchmark runtime owner is invalid")
    _validate_qwen_content_ref(owner.get("reservation_ref"))
    return owner


def _qwen_acquisition_artifact_directory(request_id: str) -> Path:
    digest = sha256(request_id.encode("utf-8")).hexdigest()
    return MODEL_SERVER_LEASE_DIR / "benchmark_acquisitions" / digest


def _qwen_acquisition_artifact_paths(request_id: str) -> dict[str, Path]:
    directory = _qwen_acquisition_artifact_directory(request_id)
    return {
        "intent": directory / "acquisition-intent.json",
        "owner": directory / "acquisition-owner.json",
        "ledger": directory / "materialization-ledger.json",
        "ledger_revision_zero": directory / "materialization-ledger-r0.json",
        "ledger_winner": directory / "materialization-ledger-r1.json",
        "abort": directory / "acquisition-abort.json",
        "aborted_tombstone": directory / "aborted-owner-tombstone.json",
        "lease_binding": directory / "acquisition-lease-binding.json",
        "lease_state_snapshot": directory / "acquisition-lease-state-snapshot.json",
        "release_observation": directory / "exact-release-observation.json",
        "termination_observation": directory / "exact-termination-observation.json",
        "cleanup_receipt": directory / "cleanup-receipt.json",
    }


def _qwen_materialization_ledger_path(request_id: str) -> Path:
    return _qwen_acquisition_artifact_paths(
        _normalized_qwen_request_id(request_id)
    )["ledger"]


def _write_qwen_acquisition_lease_binding_locked(
    request_id: str,
    *,
    model_lease: Mapping[str, object],
    state: Mapping[str, object],
) -> dict[str, Any] | None:
    paths = _qwen_acquisition_artifact_paths(request_id)
    if not paths["owner"].exists():
        return None
    owner = _load_qwen_acquisition_owner(request_id)
    ledger = _load_qwen_model_request_materialization_ledger(
        request_id,
        acquisition_intent_ref=owner["acquisition_intent_ref"],
        runtime_owner_ref=owner["runtime_owner_ref"],
    )
    if ledger.get("state") != "materialization_possible":
        raise RuntimeError("Qwen acquisition lease binding requires launch winner")
    lease = deepcopy(dict(model_lease))
    incarnation = state.get("incarnation")
    profile = state.get("profile")
    if (
        set(lease) != _QWEN_LEASE_FIELDS
        or not isinstance(incarnation, Mapping)
        or not isinstance(profile, Mapping)
        or lease.get("owner_request_id") != request_id
        or lease.get("server_process_identity")
        != incarnation.get("server_process_identity")
        or lease.get("profile_sha256")
        != content_sha256(_public_profile(dict(profile)))
    ):
        raise RuntimeError("Qwen acquisition lease binding inputs are invalid")
    server_socket = incarnation.get("server_socket")
    process_scope_acquisition = state.get("process_scope_acquisition")
    lease_state_snapshot = seal_immutable(dict(state))
    existing_snapshot = _load_optional_qwen_sealed_artifact(
        paths["lease_state_snapshot"]
    )
    if existing_snapshot is None:
        _write_qwen_acquisition_artifact(
            paths["lease_state_snapshot"],
            lease_state_snapshot,
        )
    elif existing_snapshot != lease_state_snapshot:
        raise RuntimeError("Qwen acquisition lease-state snapshot conflicts")
    binding = seal_immutable(
        {
            "contract_version": "qwen_model_request_acquisition_lease_binding_v1",
            "model_request_id": request_id,
            "acquisition_intent_ref": deepcopy(owner["acquisition_intent_ref"]),
            "runtime_owner_ref": deepcopy(owner["runtime_owner_ref"]),
            "lease_ref": _qwen_content_ref(lease),
            "profile_ref": {"content_sha256": lease["profile_sha256"]},
            "server_process_identity": deepcopy(lease["server_process_identity"]),
            "socket_ref": _qwen_content_ref(seal_immutable(server_socket)),
            "job_scope_ref": (
                _qwen_content_ref(seal_immutable(process_scope_acquisition))
                if isinstance(process_scope_acquisition, Mapping)
                else None
            ),
            "lease_state_ref": _qwen_content_ref(lease_state_snapshot),
        }
    )
    existing = _load_optional_qwen_sealed_artifact(paths["lease_binding"])
    if existing is None:
        _write_qwen_acquisition_artifact(paths["lease_binding"], binding)
    elif existing != binding:
        raise RuntimeError("Qwen acquisition lease binding conflicts")
    return deepcopy(binding)


def _load_qwen_acquisition_lease_binding(
    request_id: str,
    *,
    owner: Mapping[str, object],
) -> dict[str, Any]:
    value = _load_optional_qwen_sealed_artifact(
        _qwen_acquisition_artifact_paths(request_id)["lease_binding"]
    )
    fields = {
        "contract_version",
        "model_request_id",
        "acquisition_intent_ref",
        "runtime_owner_ref",
        "lease_ref",
        "profile_ref",
        "server_process_identity",
        "socket_ref",
        "job_scope_ref",
        "lease_state_ref",
        "content_sha256",
    }
    if (
        not isinstance(value, dict)
        or set(value) != fields
        or value.get("contract_version")
        != "qwen_model_request_acquisition_lease_binding_v1"
        or value.get("model_request_id") != request_id
        or value.get("acquisition_intent_ref")
        != owner.get("acquisition_intent_ref")
        or value.get("runtime_owner_ref") != owner.get("runtime_owner_ref")
    ):
        raise RuntimeError("Qwen acquisition lease binding is invalid")
    for field in {"lease_ref", "profile_ref", "socket_ref", "lease_state_ref"}:
        _validate_qwen_content_ref(value.get(field))
    if value.get("job_scope_ref") is not None:
        _validate_qwen_content_ref(value["job_scope_ref"])
    if not _valid_process_identity(value.get("server_process_identity")):
        raise RuntimeError("Qwen acquisition lease binding process is invalid")
    return value


def _load_qwen_acquisition_lease_state_snapshot(
    request_id: str,
    *,
    binding: Mapping[str, object],
) -> dict[str, Any]:
    snapshot = _load_optional_qwen_sealed_artifact(
        _qwen_acquisition_artifact_paths(request_id)["lease_state_snapshot"]
    )
    if (
        not isinstance(snapshot, dict)
        or binding.get("lease_state_ref") != _qwen_content_ref(snapshot)
    ):
        raise RuntimeError("Qwen acquisition lease-state parent is invalid")
    state = deepcopy(snapshot)
    state.pop("content_sha256")
    state_fields = {
        "contract_version",
        "profile_id",
        "profile",
        "incarnation",
        "server_started_by_runtime",
        "process_scope_name",
        "process_scope_acquisition",
        "revision",
        "finalization",
        "leases",
    }
    incarnation_fields = {
        "profile_id",
        "profile_sha256",
        "server_endpoint",
        "server_base_url",
        "server_model_id",
        "server_socket",
        "server_process_identity",
        "incarnation_id",
    }
    incarnation = state.get("incarnation")
    profile = state.get("profile")
    leases = state.get("leases")
    if (
        set(state) != state_fields
        or state.get("contract_version") != _QWEN_LEASE_STATE_CONTRACT
        or not isinstance(state.get("revision"), int)
        or state["revision"] < 1
        or state.get("finalization") is not None
        or not isinstance(profile, dict)
        or state.get("profile_id") != profile.get("profile_id")
        or not isinstance(incarnation, dict)
        or set(incarnation) != incarnation_fields
        or incarnation.get("profile_id") != state.get("profile_id")
        or incarnation.get("profile_sha256")
        != content_sha256(_public_profile(profile))
        or not _valid_process_identity(incarnation.get("server_process_identity"))
        or not _valid_qwen_server_socket(incarnation.get("server_socket"))
        or not isinstance(leases, list)
    ):
        raise RuntimeError("Qwen acquisition lease-state snapshot is invalid")
    exact_matches = []
    for lease_state in leases:
        if (
            not isinstance(lease_state, dict)
            or set(lease_state) != _QWEN_LEASE_FIELDS | {"lifecycle_state"}
            or lease_state.get("lifecycle_state") not in _QWEN_LIFECYCLE_STATES
        ):
            raise RuntimeError("Qwen acquisition lease-state lease is invalid")
        lease = {
            key: deepcopy(lease_state[key]) for key in _QWEN_LEASE_FIELDS
        }
        if _qwen_content_ref(lease) == binding.get("lease_ref"):
            exact_matches.append((lease_state, lease))
    if len(exact_matches) != 1 or exact_matches[0][0]["lifecycle_state"] != "not_started":
        raise RuntimeError("Qwen acquisition lease-state lineage is ambiguous")
    lease = exact_matches[0][1]
    scope = state.get("process_scope_acquisition")
    if (
        lease.get("owner_request_id") != request_id
        or lease.get("profile_id") != state.get("profile_id")
        or lease.get("profile_sha256") != incarnation.get("profile_sha256")
        or lease.get("incarnation_id") != incarnation.get("incarnation_id")
        or lease.get("server_base_url") != incarnation.get("server_base_url")
        or lease.get("server_model_id") != incarnation.get("server_model_id")
        or lease.get("server_process_identity")
        != incarnation.get("server_process_identity")
        or binding.get("profile_ref")
        != {"content_sha256": lease.get("profile_sha256")}
        or binding.get("server_process_identity")
        != lease.get("server_process_identity")
        or binding.get("socket_ref")
        != _qwen_content_ref(seal_immutable(incarnation["server_socket"]))
        or binding.get("job_scope_ref")
        != (
            _qwen_content_ref(seal_immutable(scope))
            if isinstance(scope, dict)
            else None
        )
    ):
        raise RuntimeError("Qwen acquisition lease-state binding is incoherent")
    return state


def _validate_qwen_prepare_owner_collision_locked(
    request_id: str,
    *,
    owner: Mapping[str, object],
    allow_matching_binding: bool,
) -> None:
    """在 acquisition→lease 锁内拒绝跨代 request id 复用。"""
    active_matches = _find_qwen_owner_leases_locked(request_id)
    terminal_owner = _load_qwen_owner_tombstone(request_id)
    if not active_matches and terminal_owner is None:
        return
    if not allow_matching_binding:
        raise RuntimeError("Qwen request ownership already exists")
    binding = _load_qwen_acquisition_lease_binding(request_id, owner=owner)
    _load_qwen_acquisition_lease_state_snapshot(
        request_id,
        binding=binding,
    )
    if len(active_matches) > 1:
        raise RuntimeError("Qwen request ownership is ambiguous")
    if active_matches:
        _, lease = active_matches[0]
        if binding["lease_ref"] != _qwen_content_ref(lease):
            raise RuntimeError("Qwen active ownership does not match acquisition binding")
    if terminal_owner is not None:
        release_result = terminal_owner.get("release_result")
        lease = release_result.get("lease") if isinstance(release_result, dict) else None
        if (
            not isinstance(lease, dict)
            or set(lease) != _QWEN_LEASE_FIELDS
            or binding["lease_ref"] != _qwen_content_ref(lease)
        ):
            raise RuntimeError("Qwen finalized ownership does not match acquisition binding")


def _write_qwen_acquisition_artifact(path: Path, document: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    raw = json.dumps(
        dict(document), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    try:
        with temporary.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory_handle = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_handle = None
        if directory_handle is not None:
            try:
                os.fsync(directory_handle)
            finally:
                os.close(directory_handle)
    finally:
        temporary.unlink(missing_ok=True)


def _load_optional_qwen_sealed_artifact(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RuntimeError("Qwen acquisition artifact is unreadable") from error
    if (
        not isinstance(value, dict)
        or value.get("content_sha256") != content_sha256(value)
    ):
        raise RuntimeError("Qwen acquisition artifact seal mismatch")
    return value


def _load_qwen_acquisition_intent(request_id: str) -> dict[str, Any]:
    value = _load_optional_qwen_sealed_artifact(
        _qwen_acquisition_artifact_paths(request_id)["intent"]
    )
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "contract_version",
            "model_request_id",
            "runtime_owner_ref",
            "content_sha256",
        }
        or value.get("contract_version")
        != "qwen_model_request_acquisition_intent_v1"
        or value.get("model_request_id") != request_id
    ):
        raise RuntimeError("Qwen acquisition intent is invalid")
    _validate_qwen_runtime_owner(value.get("runtime_owner_ref"), request_id=request_id)
    return value


def _load_qwen_acquisition_owner(request_id: str) -> dict[str, Any]:
    value = _load_optional_qwen_sealed_artifact(
        _qwen_acquisition_artifact_paths(request_id)["owner"]
    )
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "contract_version",
            "model_request_id",
            "runtime_owner_ref",
            "acquisition_intent_ref",
            "owner_state",
            "content_sha256",
        }
        or value.get("contract_version")
        != "benchmark_provider_acquisition_owner_v1"
        or value.get("model_request_id") != request_id
        or value.get("owner_state") != "acquisition_prepared"
    ):
        raise RuntimeError("Qwen acquisition owner is invalid")
    _validate_qwen_runtime_owner(value.get("runtime_owner_ref"), request_id=request_id)
    _validate_qwen_content_ref(value.get("acquisition_intent_ref"))
    return value


def _qwen_prepared_materialization_ledger(
    request_id: str,
    *,
    acquisition_intent_ref: Mapping[str, object],
    runtime_owner_ref: Mapping[str, object],
) -> dict[str, Any]:
    return seal_immutable(
        {
            "contract_version": "qwen_model_request_materialization_ledger_v1",
            "model_request_id": request_id,
            "acquisition_intent_ref": deepcopy(dict(acquisition_intent_ref)),
            "runtime_owner_ref": deepcopy(dict(runtime_owner_ref)),
            "state": "prepared_never_materialized",
            "revision": 0,
            "transition": "prepare",
            "predecessor_content_sha256": None,
        }
    )


def _validate_qwen_materialization_ledger(
    value: object,
    *,
    request_id: str,
    acquisition_intent_ref: Mapping[str, object],
    runtime_owner_ref: Mapping[str, object],
) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value) != _QWEN_MATERIALIZATION_LEDGER_FIELDS
        or value.get("content_sha256") != content_sha256(value)
        or value.get("contract_version")
        != "qwen_model_request_materialization_ledger_v1"
        or value.get("model_request_id") != request_id
        or value.get("acquisition_intent_ref") != dict(acquisition_intent_ref)
        or value.get("runtime_owner_ref") != dict(runtime_owner_ref)
    ):
        raise RuntimeError("Qwen materialization ledger identity is invalid")
    prepared = _qwen_prepared_materialization_ledger(
        request_id,
        acquisition_intent_ref=acquisition_intent_ref,
        runtime_owner_ref=runtime_owner_ref,
    )
    if value.get("revision") == 0:
        if value != prepared:
            raise RuntimeError("Qwen materialization prepare head is invalid")
    elif value.get("revision") == 1:
        pair = (value.get("transition"), value.get("state"))
        if (
            pair
            not in {
                ("abort", "aborted_never_materialized"),
                ("launch", "materialization_possible"),
            }
            or value.get("predecessor_content_sha256")
            != prepared["content_sha256"]
        ):
            raise RuntimeError("Qwen materialization winner head is invalid")
    else:
        raise RuntimeError("Qwen materialization ledger revision is invalid")
    return deepcopy(value)


def _load_qwen_prepared_materialization_ledger(
    request_id: str,
    *,
    acquisition_intent_ref: Mapping[str, object],
    runtime_owner_ref: Mapping[str, object],
) -> dict[str, Any]:
    revision_zero = _load_optional_qwen_sealed_artifact(
        _qwen_acquisition_artifact_paths(request_id)["ledger_revision_zero"]
    )
    prepared = _validate_qwen_materialization_ledger(
        revision_zero,
        request_id=request_id,
        acquisition_intent_ref=acquisition_intent_ref,
        runtime_owner_ref=runtime_owner_ref,
    )
    if prepared.get("revision") != 0:
        raise RuntimeError("Qwen materialization revision-zero lineage is invalid")
    return prepared


def _load_qwen_model_request_materialization_ledger(
    request_id: str,
    *,
    acquisition_intent_ref: Mapping[str, object] | None = None,
    runtime_owner_ref: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    normalized_request_id = _normalized_qwen_request_id(request_id)
    if acquisition_intent_ref is None or runtime_owner_ref is None:
        owner = _load_qwen_acquisition_owner(normalized_request_id)
        acquisition_intent_ref = owner["acquisition_intent_ref"]
        runtime_owner_ref = owner["runtime_owner_ref"]
    paths = _qwen_acquisition_artifact_paths(normalized_request_id)
    value = _load_optional_qwen_sealed_artifact(paths["ledger"])
    head = _validate_qwen_materialization_ledger(
        value,
        request_id=normalized_request_id,
        acquisition_intent_ref=acquisition_intent_ref,
        runtime_owner_ref=runtime_owner_ref,
    )
    prepared = _load_qwen_prepared_materialization_ledger(
        normalized_request_id,
        acquisition_intent_ref=acquisition_intent_ref,
        runtime_owner_ref=runtime_owner_ref,
    )
    winner = _load_optional_qwen_sealed_artifact(paths["ledger_winner"])
    if head["revision"] == 0:
        if winner is not None:
            raise RuntimeError("Qwen materialization head is a stale rollback")
    elif winner != head:
        raise RuntimeError("Qwen materialization winner lineage is incoherent")
    return head


def _find_qwen_owner_leases_locked(
    request_id: str,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    matches = []
    for state in _load_all_qwen_lease_states():
        for lease in state["leases"]:
            if isinstance(lease, dict) and lease.get("owner_request_id") == request_id:
                matches.append((state, _qwen_public_lease(lease)))
    if len(matches) > 1:
        raise RuntimeError("Qwen request ownership is ambiguous")
    return matches


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
    contract_version = value.get("contract_version")
    if (
        contract_version not in {
            _QWEN_LEASE_STATE_CONTRACT,
            _QWEN_LEGACY_LEASE_STATE_CONTRACT,
        }
        or value.get("incarnation", {}).get("incarnation_id") != incarnation_id
        or not isinstance(value.get("leases"), list)
        or not isinstance(value.get("revision"), int)
    ):
        raise RuntimeError("Qwen model lease state identity mismatch")
    for lease in value["leases"]:
        if not isinstance(lease, dict):
            raise RuntimeError("Qwen model lease lifecycle is invalid")
        lifecycle_state = lease.get("lifecycle_state")
        if (
            contract_version == _QWEN_LEGACY_LEASE_STATE_CONTRACT
            and lifecycle_state is None
        ):
            lifecycle_state = "unknown_in_flight"
            lease["lifecycle_state"] = lifecycle_state
        if lifecycle_state not in _QWEN_LIFECYCLE_STATES:
            raise RuntimeError("Qwen model lease lifecycle is invalid")
    finalization = value.get("finalization")
    if isinstance(finalization, dict):
        if (
            contract_version == _QWEN_LEGACY_LEASE_STATE_CONTRACT
            and finalization.get("phase") is None
        ):
            finalization["phase"] = "owned_pending"
        phase = finalization.get("phase")
        if phase not in {*_QWEN_UNPROVEN_FINALIZATION_PHASES, "termination_proven"}:
            raise RuntimeError("Qwen model finalization phase is invalid")
        if (
            not isinstance(finalization.get("token"), str)
            or not finalization["token"]
            or not isinstance(finalization.get("revision"), int)
            or not isinstance(finalization.get("lease_id"), str)
        ):
            raise RuntimeError("Qwen model finalization identity is invalid")
        if phase == "termination_proven" and not isinstance(
            finalization.get("termination_result"), dict
        ):
            raise RuntimeError("Qwen terminal finalization evidence is unavailable")
    elif finalization is not None:
        raise RuntimeError("Qwen model finalization state is invalid")
    value["contract_version"] = _QWEN_LEASE_STATE_CONTRACT
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
        set(receipt) != _QWEN_OWNER_TOMBSTONE_FIELDS
        or receipt.get("contract_version") != "qwen_model_request_owner_receipt_v1"
        or receipt.get("owner_request_id") != request_id
        or receipt.get("status") != "finalized"
    ):
        raise RuntimeError("Qwen owner receipt identity mismatch")
    return receipt


def _recover_qwen_finalization_tombstone(
    model_lease: dict[str, Any],
    *,
    token: str,
) -> dict[str, Any]:
    receipt = _load_qwen_owner_tombstone(
        str(model_lease.get("owner_request_id") or "")
    )
    if (
        not isinstance(receipt, dict)
        or receipt.get("lease_id") != model_lease.get("lease_id")
        or receipt.get("incarnation_id") != model_lease.get("incarnation_id")
        or receipt.get("finalization_token") != token
        or not isinstance(receipt.get("release_result"), dict)
    ):
        raise RuntimeError("Qwen terminal finalization evidence is unavailable")
    return deepcopy(receipt["release_result"])


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
        expected_socket = (
            deepcopy(state.get("incarnation", {}).get("server_socket"))
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
    if not _attest_exact_qwen_socket_owner(expected_socket, expected_process):
        raise RuntimeError("Qwen endpoint socket ownership changed before request")
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
    if os.environ.get("AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER") == "1":
        raise RuntimeError(
            "model server wrapper disabled by inherited test safety sentinel"
        )
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

    return _launch_model_server_process(
        profile=profile,
        log_path=log_path,
        command=command,
    )


def _launch_model_server_process(
    *, profile: dict[str, Any], log_path: Path, command: list[str]
) -> dict[str, Any]:
    log_file = log_path.open("a", encoding="utf-8")
    process = None
    hybrid_scope_name = os.environ.get(
        "AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", ""
    ).strip()
    pid_path = model_profile_pid_path(profile)
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
        subprocess, "CREATE_NO_WINDOW", 0
    )
    scope_cleanup_evidence = None
    try:
        if hybrid_scope_name:
            from app.learn.hybrid.windows_process_scope import spawn_process_in_scope

            process = spawn_process_in_scope(
                command,
                scope_name=hybrid_scope_name,
                cwd=str(ROOT_DIR),
                stdout=log_file,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
        else:
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
            raise RuntimeError(
                f"Model start script exited immediately with code {returncode}; see log: {log_path}"
            )
        _write_model_profile_pid(pid_path, int(process.pid))
        health_status: dict[str, Any] | None = None
        pid_sync = None
        if _profile_supports_health_status(profile):
            health_timeout = float(
                profile.get("startup_health_timeout_seconds") or 0.25
            )
            health_status = check_model_server(profile, timeout=health_timeout)
            pid_sync = _sync_pid_file_from_health(
                profile, health_status, pid_path=pid_path
            )
        return {
            "pid": process.pid,
            "pid_source": "health" if pid_sync else "wrapper_process",
            "service_pid": pid_sync["pid"] if pid_sync else None,
            "command": command,
            "log_path": str(log_path),
            "pid_path": str(pid_path),
            "health_after_start": health_status,
        }
    except BaseException as error:
        if hybrid_scope_name and process is not None:
            from app.learn.hybrid.windows_process_scope import (
                observe_process_scope_cleanup,
            )

            scope_cleanup_evidence = observe_process_scope_cleanup(
                hybrid_scope_name,
                terminate=True,
                listener_ports=[int(profile.get("port") or 0)],
                pid_file=pid_path,
                remove_owned_pid_file=True,
                stable_zero_observations=3,
            )
            if scope_cleanup_evidence.get("cleanup_status") != "verified":
                raise RuntimeError(
                    "Hybrid model start failure cleanup is indeterminate"
                ) from error
        elif process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        raise
    finally:
        process_close_error = None
        log_close_error = None
        try:
            close_process = getattr(process, "close", None)
            if callable(close_process):
                close_process()
        except BaseException as error:
            process_close_error = error
        try:
            log_file.close()
        except BaseException as error:
            log_close_error = error
        if process_close_error is not None or log_close_error is not None:
            if hybrid_scope_name and (
                not isinstance(scope_cleanup_evidence, dict)
                or scope_cleanup_evidence.get("cleanup_status") != "verified"
            ):
                try:
                    from app.learn.hybrid.windows_process_scope import (
                        observe_process_scope_cleanup,
                    )

                    scope_cleanup_evidence = observe_process_scope_cleanup(
                        hybrid_scope_name,
                        terminate=True,
                        listener_ports=[int(profile.get("port") or 0)],
                        pid_file=pid_path,
                        remove_owned_pid_file=True,
                        stable_zero_observations=3,
                    )
                except BaseException as scope_error:
                    scope_cleanup_evidence = {
                        "contract_version": "hybrid_windows_process_scope_v1",
                        "scope_name": hybrid_scope_name,
                        "cleanup_status": "indeterminate",
                        "error_type": type(scope_error).__name__,
                        "message": str(scope_error),
                    }
            cleanup_evidence = {
                "contract_version": "hybrid_model_launch_handle_cleanup_v1",
                "cleanup_status": "indeterminate",
                "process_handle_close": (
                    "failed" if process_close_error is not None else "closed"
                ),
                "log_handle_close": (
                    "failed" if log_close_error is not None else "closed"
                ),
                "process_close_error": (
                    {
                        "error_type": type(process_close_error).__name__,
                        "message": str(process_close_error),
                    }
                    if process_close_error is not None
                    else None
                ),
                "log_close_error": (
                    {
                        "error_type": type(log_close_error).__name__,
                        "message": str(log_close_error),
                    }
                    if log_close_error is not None
                    else None
                ),
                "scope_cleanup_evidence": deepcopy(scope_cleanup_evidence),
            }
            raise HybridModelLaunchCleanupError(cleanup_evidence) from (
                process_close_error or log_close_error
            )


def _write_model_profile_pid(path: Path, pid: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pid), encoding="utf-8")


def stop_model_server(profile: dict[str, Any]) -> dict[str, Any]:
    if os.environ.get("AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER") == "1":
        raise RuntimeError(
            "model server wrapper disabled by inherited test safety sentinel"
        )
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


def build_hybrid_vista_model_lease(
    profile: dict[str, Any],
    readiness: dict[str, Any],
) -> dict[str, Any]:
    """从同一次 VISTA 启动/就绪观测提取精确释放身份。"""
    if not isinstance(profile, dict) or not str(profile.get("profile_id") or "").strip():
        raise ValueError("Hybrid VISTA profile is required")
    if not isinstance(readiness, dict):
        raise ValueError("Hybrid VISTA readiness is required")
    process_scope_name = os.environ.get(
        "AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", ""
    ).strip()
    if not process_scope_name:
        raise ValueError("Hybrid VISTA process scope is required")
    identities: dict[tuple[int, int], dict[str, int]] = {}

    def collect_identity(value: object) -> None:
        if _valid_process_identity(value):
            identity = deepcopy(value)
        else:
            identity = _current_process_identity(value)
        if _valid_process_identity(identity):
            identities[(identity["pid"], identity["create_time_ns"])] = identity

    start = readiness.get("start")
    if isinstance(start, dict):
        for field in ("pid", "service_pid"):
            collect_identity(start.get(field))
    for section in ("before", "after"):
        observed = readiness.get(section)
        if not isinstance(observed, dict):
            continue
        collect_identity(observed.get("expected_pid"))
        collect_identity(observed.get("server_process_identity"))
        health = observed.get("health")
        if isinstance(health, dict):
            collect_identity(health.get("pid"))
            collect_identity(health.get("server_process_identity"))
    process_identities = sorted(identities.values(), key=lambda item: (item["pid"], item["create_time_ns"]))
    if not process_identities:
        raise ValueError("Hybrid VISTA readiness has no exact process identity")
    from app.learn.hybrid.windows_process_scope import WindowsProcessScope

    scope = WindowsProcessScope(process_scope_name, create=False)
    try:
        member_pids = scope.pids()
    finally:
        scope.close()
    if any(identity["pid"] not in member_pids for identity in process_identities):
        raise ValueError("Hybrid VISTA process identity is outside its exact scope")
    incarnation_id = content_sha256({
        "profile_id": profile["profile_id"],
        "process_identities": process_identities,
    })
    return {
        "contract_version": "hybrid_vista_model_lease_v2",
        "provider": "vista",
        "incarnation_id": incarnation_id,
        "profile": _public_profile(deepcopy(profile)),
        "process_identities": process_identities,
        "process_scope_name": process_scope_name,
        "process_scope_acquisition": {
            "contract_version": "hybrid_process_scope_acquisition_v1",
            "scope_name": process_scope_name,
            "member_pids": member_pids,
            "process_identities": deepcopy(process_identities),
        },
    }


def _profile_for_hybrid_vista_model_lease(model_lease: object) -> dict[str, Any]:
    if not isinstance(model_lease, dict):
        raise ValueError("exact Hybrid VISTA model lease is required")
    fields = {
        "contract_version",
        "provider",
        "incarnation_id",
        "profile",
        "process_identities",
        "process_scope_name",
        "process_scope_acquisition",
    }
    profile = model_lease.get("profile")
    identities = model_lease.get("process_identities")
    scope_name = model_lease.get("process_scope_name")
    acquisition = model_lease.get("process_scope_acquisition")
    if (
        set(model_lease) != fields
        or model_lease.get("contract_version") != "hybrid_vista_model_lease_v2"
        or model_lease.get("provider") != "vista"
        or not isinstance(profile, dict)
        or not str(profile.get("profile_id") or "").strip()
        or not isinstance(identities, list)
        or not identities
        or any(not _valid_process_identity(identity) for identity in identities)
        or not isinstance(scope_name, str)
        or not scope_name
        or not isinstance(acquisition, dict)
        or acquisition.get("contract_version") != "hybrid_process_scope_acquisition_v1"
        or acquisition.get("scope_name") != scope_name
        or acquisition.get("process_identities") != identities
        or not isinstance(acquisition.get("member_pids"), list)
        or any(identity["pid"] not in acquisition["member_pids"] for identity in identities)
        or model_lease.get("incarnation_id")
        != content_sha256({"profile_id": profile["profile_id"], "process_identities": identities})
    ):
        raise ValueError("exact Hybrid VISTA model lease is invalid")
    installed_profile = _public_profile(
        profile_for_stage("grounding", str(profile["profile_id"]))
    )
    if installed_profile != profile:
        raise ValueError("Hybrid VISTA model lease profile no longer matches installed configuration")
    if any(_current_process_identity(identity["pid"]) != identity for identity in identities):
        raise RuntimeError("VISTA provider process ownership changed before request")
    from app.learn.hybrid.windows_process_scope import WindowsProcessScope

    scope = WindowsProcessScope(scope_name, create=False)
    try:
        member_pids = scope.pids()
    finally:
        scope.close()
    expected_pids = {identity["pid"] for identity in identities}
    if not expected_pids.issubset(set(member_pids)):
        raise RuntimeError("VISTA provider process left its exact scope before request")
    try:
        port = int(profile.get("port") or 0)
    except (TypeError, ValueError) as error:
        raise ValueError("VISTA provider port is invalid") from error
    listening_pids = set(_listening_pids_for_port(port))
    if port <= 0 or not listening_pids or not listening_pids.issubset(expected_pids):
        raise RuntimeError("VISTA endpoint socket ownership changed before request")
    return deepcopy(profile)


def release_hybrid_vista_model_lease(
    model_lease: dict[str, Any],
    *,
    lineage: dict[str, Any],
    predecessor_sha256: str,
    provider_result_sha256: str,
) -> dict[str, Any]:
    """停止同一 VISTA profile，并把进程、监听和 pid 文件事实返回给协调器。"""
    if (
        not isinstance(model_lease, dict)
        or model_lease.get("contract_version") != "hybrid_vista_model_lease_v2"
        or model_lease.get("provider") != "vista"
        or not isinstance(model_lease.get("incarnation_id"), str)
        or not isinstance(model_lease.get("profile"), dict)
        or not isinstance(model_lease.get("process_identities"), list)
        or not model_lease.get("process_identities")
        or not isinstance(model_lease.get("process_scope_name"), str)
        or not model_lease.get("process_scope_name")
        or not isinstance(model_lease.get("process_scope_acquisition"), dict)
    ):
        raise ValueError("exact Hybrid VISTA model lease is required")
    from app.learn.hybrid.gpu_lifecycle import validate_hybrid_lineage

    profile = deepcopy(model_lease["profile"])
    expected_identities = deepcopy(model_lease["process_identities"])
    if any(not _valid_process_identity(identity) for identity in expected_identities):
        raise ValueError("Hybrid VISTA model lease identity is invalid")
    from app.learn.hybrid.windows_process_scope import (
        observe_process_scope_cleanup,
        process_scope_name as expected_process_scope_name,
    )

    exact_lineage = validate_hybrid_lineage(lineage)
    scope_name = model_lease["process_scope_name"]
    if scope_name != expected_process_scope_name(exact_lineage, "vista"):
        raise ValueError("Hybrid VISTA process scope lineage mismatch")
    acquisition = model_lease["process_scope_acquisition"]
    if (
        acquisition.get("contract_version")
        != "hybrid_process_scope_acquisition_v1"
        or acquisition.get("scope_name") != scope_name
        or not isinstance(acquisition.get("member_pids"), list)
        or any(
            identity["pid"] not in acquisition["member_pids"]
            for identity in expected_identities
        )
    ):
        raise ValueError("Hybrid VISTA process scope acquisition is invalid")
    try:
        stop_result = stop_model_server(profile)
    except BaseException as error:
        stop_result = {
            "stopped": False,
            "error_type": type(error).__name__,
            "details": str(error),
        }
    port = profile.get("port")
    try:
        normalized_port = int(port)
    except (TypeError, ValueError):
        normalized_port = 0
    scope_cleanup = observe_process_scope_cleanup(
        scope_name,
        terminate=True,
        listener_ports=[normalized_port] if normalized_port > 0 else [],
        pid_file=model_profile_pid_path(profile),
        remove_owned_pid_file=True,
        stable_zero_observations=3,
    )
    provider_probes = [_probe_exact_qwen_process(identity) for identity in expected_identities]
    inventory_observable = scope_cleanup.get("cleanup_status") == "verified" and all(
        probe.get("status") != "unobservable" for probe in provider_probes
    )
    active_provider = [
        deepcopy(identity)
        for identity, probe in zip(expected_identities, provider_probes)
        if probe.get("status") == "exact_live"
    ]
    listeners = deepcopy(scope_cleanup.get("active_listeners_after") or [])
    pid_path = model_profile_pid_path(profile)
    lease_files = [str(pid_path)] if pid_path.exists() else []
    orphan_descendants = list(scope_cleanup.get("member_pids_after") or [])
    scoped_identities = scope_cleanup.get("member_identities_after")
    orphan_descendant_identities = (
        deepcopy(scoped_identities)
        if isinstance(scoped_identities, list)
        else [{"pid": int(pid), "create_time_ns": 0} for pid in orphan_descendants]
    )
    verified = (
        scope_cleanup.get("cleanup_status") == "verified"
        and inventory_observable
        and not active_provider
        and not orphan_descendants
        and not listeners
        and not lease_files
    )
    return {
        "contract_version": "hybrid_provider_process_inventory_v2",
        "provider": "vista",
        "observer_contract": "hybrid_vista_cleanup_observer_v1",
        "release_status": "verified" if verified else "failed",
        "termination_reason": "completed" if verified else "cleanup_failed",
        "lineage": exact_lineage,
        "provider_lease_identity": {
            "incarnation_id": model_lease["incarnation_id"],
            "profile_id": profile["profile_id"],
            "process_identities": expected_identities,
            "process_scope_name": scope_name,
        },
        "predecessor_sha256": predecessor_sha256,
        "provider_result_sha256": provider_result_sha256,
        "provider_processes_after": active_provider,
        "helper_processes_after": orphan_descendant_identities,
        "orphan_descendant_pids": orphan_descendants,
        "active_listeners_after": listeners,
        "lease_files_after": lease_files,
        "source_cleanup_evidence": {
            "contract_version": "hybrid_vista_cleanup_evidence_v2",
            "status": "verified" if verified else "failed",
            "model_lease": deepcopy(model_lease),
            "stop_result": deepcopy(stop_result),
            "inventory_observable": inventory_observable,
            "process_scope_cleanup": scope_cleanup,
            "provider_probes": provider_probes,
        },
    }


def _listening_pids_for_port(port: int) -> list[int]:
    if port <= 0:
        return []
    try:
        connections = list(psutil.net_connections(kind="tcp"))
    except (psutil.AccessDenied, OSError) as error:
        raise RuntimeError("Hybrid VISTA listener inventory is unobservable") from error
    pids: set[int] = set()
    for connection in connections:
        address = getattr(connection, "laddr", None)
        if (
            connection.status == psutil.CONN_LISTEN
            and address
            and int(getattr(address, "port", address[1])) == port
            and connection.pid
        ):
            pids.add(int(connection.pid))
    return sorted(pids)


def _descendant_identities_for_parents(
    parent_identities: list[dict[str, int]],
) -> tuple[list[dict[str, int]], bool]:
    descendants: dict[tuple[int, int], dict[str, int]] = {}
    observable = True
    for parent_identity in parent_identities:
        try:
            process = psutil.Process(parent_identity["pid"])
            current = {
                "pid": int(process.pid),
                "create_time_ns": int(round(process.create_time() * 1_000_000_000)),
            }
            if current != parent_identity:
                continue
            for child in process.children(recursive=True):
                identity = {
                    "pid": int(child.pid),
                    "create_time_ns": int(round(child.create_time() * 1_000_000_000)),
                }
                descendants[(identity["pid"], identity["create_time_ns"])] = identity
        except psutil.NoSuchProcess:
            continue
        except (psutil.AccessDenied, OSError):
            observable = False
    return sorted(descendants.values(), key=lambda item: (item["pid"], item["create_time_ns"])), observable


def _observe_known_qwen_descendant_cleanup(
    identities: list[dict[str, int]],
) -> dict[str, Any]:
    if any(not _valid_process_identity(identity) for identity in identities):
        return {
            "status": "indeterminate",
            "descendant_identities": deepcopy(identities),
            "probes": [],
        }
    probes = [_probe_exact_qwen_process(identity) for identity in identities]
    verified = all(probe.get("status") == "proven_absent" for probe in probes)
    return {
        "status": "verified" if verified else "indeterminate",
        "descendant_identities": deepcopy(identities),
        "probes": probes,
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


def _qwen_model_projection_response_schema(projection: Mapping[str, Any]) -> dict[str, Any]:
    """Build the exact per-goal simple-native binder response schema."""
    goals = projection.get("goals")
    candidates = projection.get("candidates")
    if not isinstance(goals, list) or not isinstance(candidates, list):
        raise ValueError("Qwen model projection goals or candidates must be lists")
    for index, goal in enumerate(goals):
        if not isinstance(goal, Mapping) or goal.get("goal_index") != index:
            raise ValueError("Qwen model projection goal ordinal is invalid")
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping) or candidate.get("candidate_index") != index:
            raise ValueError("Qwen model projection candidate ordinal is invalid")
    fields = ["goal_index", "candidate_index", "status", "confidence"]
    candidate_index = {"anyOf": [
        {"type": "integer", "minimum": 0, "maximum": len(candidates) - 1},
        {"type": "null"},
    ]} if candidates else {"type": "null"}
    return {
        "type": "object",
        "properties": {
            "bindings": {
                "type": "array",
                "prefixItems": [
                    {
                        "type": "object",
                        "properties": {
                            "goal_index": {"const": index},
                            "candidate_index": candidate_index,
                            "status": {"enum": ["BOUND", "UNBOUND"]},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        },
                        "required": fields,
                        "additionalProperties": False,
                    }
                    for index in range(len(goals))
                ],
                "minItems": len(goals),
                "maxItems": len(goals),
            }
        },
        "required": ["bindings"],
        "additionalProperties": False,
    }
