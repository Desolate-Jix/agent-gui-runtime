"""Benchmark v2 原始 GPU 生命周期采集与只读验证。"""

from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any, Mapping

import psutil

from app.learn.recognition.uei.canonical import canonical_json_bytes, content_sha256, seal_immutable


_SAMPLE_CONTRACT = "benchmark_v2_raw_gpu_sample_v1"
_RESULT_CONTRACT = "benchmark_v2_lifecycle_verification_v1"
_PROBE_CONTRACT = "benchmark_v2_lifecycle_probe_receipt_v1"
_GPU_OBSERVER_CONTRACT = "benchmark_v2_gpu_observer_identity_v1"
_PROCESS_SNAPSHOT_CONTRACT = "benchmark_v2_process_identity_snapshot_v1"
_MAX_STREAM_BYTES = 1024 * 1024
_MAX_ARTIFACT_BYTES = 4 * 1024 * 1024
_COMMAND_TIMEOUT_SECONDS = 15.0
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_PROVIDERS = ("omni", "qwen", "vista")
_PROBE_KINDS = ("cancel", "timeout")
_REQUIRED_MATRIX = tuple((provider, kind) for provider in _PROVIDERS for kind in _PROBE_KINDS)
_GPU_COMMANDS = (
    (
        "gpu_totals",
        (
            "nvidia-smi.exe",
            "--query-gpu=uuid,memory.used",
            "--format=csv,noheader,nounits",
        ),
    ),
    (
        "compute_apps",
        (
            "nvidia-smi.exe",
            "--query-compute-apps=pid,gpu_uuid,used_gpu_memory",
            "--format=csv,noheader,nounits",
        ),
    ),
)

_SAMPLE_FIELDS = {
    "contract_version",
    "collection_mode",
    "device_uuid",
    "observer_identity",
    "sample_started_at_utc",
    "sample_finished_at_utc",
    "commands",
    "process_snapshot",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "content_sha256",
}
_COMMAND_FIELDS = {
    "role",
    "argv",
    "started_at_utc",
    "finished_at_utc",
    "execution_status",
    "exit_code",
    "os_error_code",
    "timed_out",
    "stdout_raw",
    "stderr_raw",
}
_RAW_FIELDS = {"encoding", "byte_length", "sha256", "data_base64"}
_OBSERVER_FIELDS = {
    "contract_version",
    "kind",
    "platform",
    "collector_module_ref",
    "nvidia_smi_ref",
    "collector_process_identity",
    "content_sha256",
}
_FILE_REF_FIELDS = {"canonical_path", "file_sha256"}
_SNAPSHOT_FIELDS = {
    "contract_version",
    "observed_at_utc",
    "status",
    "identities",
    "unobserved_pids",
    "content_sha256",
}
_PROCESS_FIELDS = {"pid", "create_time_ns"}

_TASK4_ROOT_FIELDS = {
    "contract_version",
    "owner_id",
    "operation_id",
    "screenshot_path",
    "screenshot_sha256",
    "image_dimensions",
    "bitmap_pixel_sha256",
    "scope_name",
    "window_class",
    "window_title",
    "shutdown_event_name",
    "shutdown_nonce",
    "journal_path",
    "events_path",
    "publication_path",
    "publication_permit_path",
    "helper_path",
    "root_anchor_path",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "display_only",
    "content_sha256",
}
_TASK4_EVENT_FIELDS = {
    "contract_version",
    "sequence",
    "event_type",
    "owner_id",
    "previous_event_sha256",
    "root_anchor_sha256",
    "payload",
    "content_sha256",
}
_TASK4_CLEANUP_FIELDS = {
    "contract_version",
    "owner_id",
    "reason",
    "exact_hwnd",
    "process_identity",
    "cleanup_subject_kind",
    "finalization_intent_sha256",
    "process_event_sha256",
    "ready_event_sha256",
    "publication_content_sha256",
    "cleanup_status",
    "shutdown_event_name",
    "shutdown_event_signaled",
    "shutdown_event_error_code",
    "shutdown_event_handle_closed",
    "enum_windows_exact_hwnd_absent",
    "matching_owned_windows_after",
    "member_pids_after",
    "stable_zero_observations",
    "scope_absent_after_owner_close",
    "process_handle_closed",
    "job_handle_closed",
    "active_listeners_after",
    "listener_or_lease_residue",
    "outer_owner_python_finally_observed",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "content_sha256",
}
_TASK5_AUTHORITY_FIELDS = {
    "contract_version",
    "authority_kind",
    "run_id",
    "stage",
    "operation_id",
    "window_binding_ref",
    "capture_ref",
    "serialized_window_binding",
    "owner_binding_ref",
    "owner_journal_ref",
    "owner_ready_event_ref",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "predecessor_content_sha256",
    "content_sha256",
}
_SERIALIZED_BINDING_FIELDS = {
    "contract_version",
    "operation_id",
    "exact_hwnd",
    "process_identity",
    "job_name",
    "job_membership_ref",
    "screenshot_sha256",
    "capture_sha256",
    "capture_image_path",
    "image_dimensions",
    "owner_journal_path",
    "owner_journal_content_sha256",
    "owner_ready_event_sha256",
    "owner_binding_content_sha256",
    "owner_id",
    "expected_uia_root_hwnd",
    "expected_uia_owner_pid",
    "expected_uia_root_content_sha256",
    "window_class",
    "window_title",
    "window_rect",
    "client_rect",
    "dpi",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "display_only",
    "payload_sha256",
}
_TASK5_CLEAR_FIELDS = {
    "contract_version",
    "operation_id",
    "binding_payload_sha256",
    "worker_pid",
    "cleared",
    "prior_binding_restored",
    "restored_hwnd",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "content_sha256",
}
_B1_ASSIGNMENT_FIELDS = {
    "contract_version",
    "scope_name",
    "process_identity",
    "observed_member_identities",
    "job_policy",
    "temporary_process_handle_close",
    "temporary_job_handle_close",
    "predecessor_content_sha256",
    "content_sha256",
}
_B1_OWNER_FIELDS = {
    "contract_version",
    "authority_kind",
    "operation_anchor_ref",
    "reservation_ref",
    "supervision_ref",
    "run_id",
    "stage",
    "operation_id",
    "worker_id",
    "model_request_id",
    "payload_sha256",
    "execution_nonce",
    "scope_name",
    "supervisor_process_identity",
    "phase",
    "process_identity",
    "beacon_ref",
    "assignment_observation_ref",
    "job_policy",
    "gate_state",
    "exit_observation_ref",
    "stable_zero_observation_ref",
    "exact_handle_observation_refs",
    "cleanup_finalization_intent",
    "cleanup_receipt_ref",
    "predecessor_content_sha256",
    "content_sha256",
}
_B1_CLEANUP_FIELDS = {
    "contract_version",
    "outcome",
    "operation_anchor_ref",
    "reservation_ref",
    "supervision_ref",
    "run_id",
    "stage",
    "operation_id",
    "worker_id",
    "process_identity",
    "assignment_proven_ref",
    "finalization_intent_ref",
    "exact_handle_observation_refs",
    "job_absence_observation_ref",
    "worker_absence_observation_ref",
    "supervisor_absence_observation_ref",
    "reservation_abort_ref",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "content_sha256",
}
_B2_RUNTIME_FIELDS = {
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
_B2_LEDGER_FIELDS = {
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
_B2_JOURNAL_FIELDS = {
    "contract_version",
    "authority_kind",
    "run_id",
    "stage",
    "operation_id",
    "worker_id",
    "model_request_id",
    "payload_sha256",
    "reservation_ref",
    "runtime_owner_ref",
    "acquisition_owner_ref",
    "acquisition_intent_ref",
    "prepared_acquisition_observation_ref",
    "prepared_materialization_ledger_ref",
    "acquisition_observation_ref",
    "materialization_ledger_ref",
    "content_sha256",
}
_B2_CLEANUP_JOURNAL_FIELDS = {
    "contract_version",
    "authority_kind",
    "run_id",
    "stage",
    "operation_id",
    "worker_id",
    "model_request_id",
    "payload_sha256",
    "reservation_ref",
    "runtime_owner_ref",
    "acquisition_owner_ref",
    "acquisition_intent_ref",
    "cleanup_receipt_ref",
    "content_sha256",
}
_B2_CLEANUP_FIELDS = {
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

_PROBE_FIELDS = {
    "contract_version",
    "probe_id",
    "probe_kind",
    "provider",
    "run_id",
    "stage",
    "operation_id",
    "model_request_id",
    "request_in_flight_observation",
    "trigger",
    "body_completion_observation",
    "lease_or_owner",
    "termination_observation",
    "stable_zero_observation",
    "observer_identity",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "predecessor_content_sha256",
    "content_sha256",
}
_PROBE_PROVIDER_FIELDS = {"provider_id", "profile_id", "profile_sha256"}
_IN_FLIGHT_FIELDS = {"state", "observed_at_utc", "evidence_ref"}
_TRIGGER_FIELDS = {"kind", "triggered_at_utc", "request_in_flight_ref"}
_BODY_FIELDS = {"state", "observed_at_utc", "evidence_ref"}
_LEASE_OWNER_FIELDS = {"lease_ref", "socket_ref", "process_identity", "job_scope_ref"}
_TERMINATION_FIELDS = {"outcome", "process_identity", "evidence_ref"}
_STABLE_ZERO_FIELDS = {
    "job_members",
    "active_listeners",
    "active_leases",
    "stable_zero_observations",
    "process_absence_ref",
    "listener_absence_ref",
    "lease_absence_ref",
}
_PROBE_OBSERVER_FIELDS = {"kind", "module_ref", "content_sha256"}


class _EvidenceError(ValueError):
    def __init__(self, code: str, message: str, *, disposition: str = "failed", refs: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.disposition = disposition
        self.refs = refs


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _content_sha256(value: Mapping[str, object]) -> str:
    return content_sha256(dict(value))


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha(value: object, name: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        raise _EvidenceError("invalid_sha256", f"{name} must be lowercase SHA-256")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise _EvidenceError("invalid_text", f"{name} must be non-empty canonical text")
    return value


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise _EvidenceError("invalid_integer", f"{name} must be an integer >= {minimum}")
    return value


def _closed(value: object, fields: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise _EvidenceError("closed_schema_mismatch", f"{name} must contain exactly {sorted(fields)}")
    return deepcopy(dict(value))


def _sealed(value: object, fields: set[str], name: str) -> dict[str, Any]:
    result = _closed(value, fields, name)
    if result.get("content_sha256") != content_sha256(result):
        raise _EvidenceError("seal_mismatch", f"{name} seal differs")
    return result


def _process_identity(value: object, name: str) -> dict[str, int]:
    result = _closed(value, _PROCESS_FIELDS, name)
    return {
        "pid": _integer(result["pid"], f"{name}.pid", minimum=1),
        "create_time_ns": _integer(result["create_time_ns"], f"{name}.create_time_ns", minimum=1),
    }


def _content_ref(value: object, name: str, *, nullable: bool = False) -> dict[str, Any] | None:
    if value is None and nullable:
        return None
    if not isinstance(value, Mapping) or set(value) not in ({"content_sha256"}, {"id", "content_sha256"}):
        raise _EvidenceError("invalid_content_ref", f"{name} must be a closed content ref")
    result = deepcopy(dict(value))
    _sha(result.get("content_sha256"), f"{name}.content_sha256")
    if "id" in result:
        _text(result["id"], f"{name}.id")
    return result


def _timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise _EvidenceError("invalid_timestamp", f"{name} must be an explicit UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise _EvidenceError("invalid_timestamp", f"{name} is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise _EvidenceError("invalid_timestamp", f"{name} is not UTC")
    return parsed


def _json_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _EvidenceError("duplicate_json_key", f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise _EvidenceError("nonfinite_json_number", f"non-finite JSON number: {value}")


def _decode_canonical_json(raw: bytes, name: str) -> dict[str, Any]:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise _EvidenceError("noncanonical_json", f"{name} must not contain a UTF-8 BOM")
    try:
        decoded = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_json_pairs,
            parse_constant=_reject_constant,
        )
    except _EvidenceError:
        raise
    except (UnicodeError, json.JSONDecodeError) as error:
        raise _EvidenceError("invalid_json", f"{name} is not strict UTF-8 JSON") from error
    if not isinstance(decoded, dict) or raw != canonical_json_bytes(decoded):
        raise _EvidenceError("noncanonical_json", f"{name} bytes are not canonical JSON")
    return decoded


def _resolve_input_path(path: Path, name: str) -> Path:
    if not isinstance(path, Path) or not path.is_absolute():
        raise _EvidenceError("noncanonical_path", f"{name} must be an absolute Path")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as error:
        raise _EvidenceError("missing_input_path", f"{name} does not resolve") from error
    if str(path) != str(resolved) or not resolved.is_file():
        raise _EvidenceError("noncanonical_path", f"{name} must be a canonical regular file")
    return resolved


def _read_input(path: Path, name: str, *, maximum: int = _MAX_ARTIFACT_BYTES) -> tuple[Path, bytes]:
    resolved = _resolve_input_path(path, name)
    try:
        size = resolved.stat().st_size
        if size > maximum:
            raise _EvidenceError("oversize_input", f"{name} exceeds {maximum} bytes")
        with resolved.open("rb") as stream:
            raw = stream.read(maximum + 1)
    except _EvidenceError:
        raise
    except OSError as error:
        raise _EvidenceError("input_read_failed", f"{name} cannot be read") from error
    if len(raw) > maximum:
        raise _EvidenceError("oversize_input", f"{name} exceeds {maximum} bytes")
    return resolved, raw


def _raw_stream(raw: bytes) -> dict[str, object]:
    if len(raw) > _MAX_STREAM_BYTES:
        raise ValueError("nvidia-smi stream exceeds 1 MiB")
    return {
        "encoding": "base64",
        "byte_length": len(raw),
        "sha256": _sha_bytes(raw),
        "data_base64": base64.b64encode(raw).decode("ascii"),
    }


def _decode_raw_stream(value: object, name: str) -> bytes:
    stream = _closed(value, _RAW_FIELDS, name)
    if stream.get("encoding") != "base64":
        raise _EvidenceError("invalid_raw_stream", f"{name} encoding differs")
    length = _integer(stream.get("byte_length"), f"{name}.byte_length")
    if length > _MAX_STREAM_BYTES:
        raise _EvidenceError("oversize_raw_stream", f"{name} exceeds 1 MiB")
    _sha(stream.get("sha256"), f"{name}.sha256")
    data = stream.get("data_base64")
    if not isinstance(data, str):
        raise _EvidenceError("invalid_raw_stream", f"{name}.data_base64 must be text")
    try:
        raw = base64.b64decode(data.encode("ascii"), validate=True)
    except (UnicodeError, ValueError) as error:
        raise _EvidenceError("invalid_raw_stream", f"{name} base64 differs") from error
    if len(raw) != length or _sha_bytes(raw) != stream["sha256"]:
        raise _EvidenceError("invalid_raw_stream", f"{name} raw byte evidence differs")
    return raw


def _run_fixed_nvidia_smi_query(
    argv: list[str], *, shell: bool, timeout_seconds: float
) -> dict[str, object]:
    if shell is not False or tuple(argv) not in tuple(command for _role, command in _GPU_COMMANDS):
        raise ValueError("only the fixed nvidia-smi queries are permitted")
    process: subprocess.Popen[bytes] | None = None
    stdout = b""
    stderr = b""
    try:
        process = subprocess.Popen(
            argv,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
            process.wait()
            return {
                "execution_status": "completed",
                "exit_code": int(process.returncode),
                "os_error_code": None,
                "timed_out": False,
                "stdout": stdout,
                "stderr": stderr,
            }
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            process.wait()
            return {
                "execution_status": "timed_out",
                "exit_code": None,
                "os_error_code": None,
                "timed_out": True,
                "stdout": bytes(stdout or b""),
                "stderr": bytes(stderr or b""),
            }
    except OSError as error:
        return {
            "execution_status": "launch_failed",
            "exit_code": None,
            "os_error_code": int(error.winerror if getattr(error, "winerror", None) is not None else error.errno or 0),
            "timed_out": False,
            "stdout": stdout,
            "stderr": stderr,
        }
    finally:
        if process is not None:
            if process.poll() is None:
                process.kill()
                process.communicate()
            process.wait()
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()


def _observe_pid_create_times(pids: list[int]) -> tuple[dict[int, int], list[int]]:
    identities: dict[int, int] = {}
    unobserved: list[int] = []
    for pid in sorted(set(pids)):
        try:
            created_ns = int(psutil.Process(pid).create_time() * 1_000_000_000)
            if created_ns <= 0:
                raise ValueError("invalid create time")
            identities[pid] = created_ns
        except (psutil.Error, OSError, ValueError):
            unobserved.append(pid)
    return identities, unobserved


def _production_gpu_observer_identity() -> dict[str, object]:
    module_path = Path(__file__).resolve()
    executable = shutil.which("nvidia-smi.exe")
    executable_ref: dict[str, object] | None = None
    if executable:
        executable_path = Path(executable).resolve()
        try:
            executable_ref = {
                "canonical_path": str(executable_path),
                "file_sha256": _sha_bytes(executable_path.read_bytes()),
            }
        except OSError:
            executable_ref = None
    try:
        create_time_ns = int(psutil.Process(os.getpid()).create_time() * 1_000_000_000)
    except psutil.Error as error:
        raise RuntimeError("collector process identity is unavailable") from error
    return seal_immutable(
        {
            "contract_version": _GPU_OBSERVER_CONTRACT,
            "kind": "production_direct",
            "platform": "windows",
            "collector_module_ref": {
                "canonical_path": str(module_path),
                "file_sha256": _sha_bytes(module_path.read_bytes()),
            },
            "nvidia_smi_ref": executable_ref,
            "collector_process_identity": {"pid": os.getpid(), "create_time_ns": create_time_ns},
        }
    )


def _write_create_only(path: Path, raw: bytes) -> None:
    if len(raw) > _MAX_ARTIFACT_BYTES:
        raise ValueError("raw GPU transcript exceeds 4 MiB")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.read_bytes() != raw:
            raise FileExistsError("raw GPU transcript already exists with different bytes")
        return
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise


def collect_raw_gpu_sample(*, device_uuid: str, transcript_path: Path) -> dict[str, object]:
    """顺序执行两个固定命令并封存逐字节 transcript。"""
    if os.name != "nt":
        raise RuntimeError("production raw GPU collection is Windows-only")
    requested_uuid = _text(device_uuid, "device_uuid")
    path = Path(transcript_path)
    if not path.is_absolute():
        raise ValueError("transcript_path must be absolute")
    if path.exists():
        resolved, raw = _read_input(path.resolve(), "transcript_path")
        existing = _decode_canonical_json(raw, "existing raw GPU transcript")
        validated = _validate_sample(existing)
        if (
            validated["device_uuid"] != requested_uuid
            or validated["collection_mode"] != "production_direct"
            or validated["observer_identity"]["kind"] != "production_direct"
        ):
            raise FileExistsError("raw GPU transcript is not an identical production observation for the requested device")
        return deepcopy(validated)
    started = _utc_now()
    commands: list[dict[str, object]] = []
    raw_results: list[dict[str, object]] = []
    for role, fixed_argv in _GPU_COMMANDS:
        command_started = _utc_now()
        result = _run_fixed_nvidia_smi_query(
            list(fixed_argv), shell=False, timeout_seconds=_COMMAND_TIMEOUT_SECONDS
        )
        command_finished = _utc_now()
        stdout = result.get("stdout")
        stderr = result.get("stderr")
        if not isinstance(stdout, bytes) or not isinstance(stderr, bytes):
            raise TypeError("raw command seam must return bytes")
        observation = {
            "role": role,
            "argv": list(fixed_argv),
            "started_at_utc": command_started,
            "finished_at_utc": command_finished,
            "execution_status": result.get("execution_status"),
            "exit_code": result.get("exit_code"),
            "os_error_code": result.get("os_error_code"),
            "timed_out": result.get("timed_out"),
            "stdout_raw": _raw_stream(stdout),
            "stderr_raw": _raw_stream(stderr),
        }
        commands.append(observation)
        raw_results.append(result)
    pids: list[int] = []
    parse_error: Exception | None = None
    if raw_results[1].get("execution_status") == "completed" and raw_results[1].get("exit_code") == 0:
        try:
            pids = sorted({row[0] for row in _parse_compute_rows(bytes(raw_results[1]["stdout"]))})
        except (ValueError, _EvidenceError) as error:
            parse_error = error
    identities, unobserved = _observe_pid_create_times(pids) if parse_error is None else ({}, pids)
    snapshot = seal_immutable(
        {
            "contract_version": _PROCESS_SNAPSHOT_CONTRACT,
            "observed_at_utc": _utc_now(),
            "status": "unavailable" if parse_error is not None else "partial" if unobserved else "complete",
            "identities": [
                {"pid": pid, "create_time_ns": identities[pid]} for pid in sorted(identities)
            ],
            "unobserved_pids": sorted(unobserved),
        }
    )
    transcript = seal_immutable(
        {
            "contract_version": _SAMPLE_CONTRACT,
            "collection_mode": "production_direct",
            "device_uuid": requested_uuid,
            "observer_identity": _production_gpu_observer_identity(),
            "sample_started_at_utc": started,
            "sample_finished_at_utc": _utc_now(),
            "commands": commands,
            "process_snapshot": snapshot,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    raw = canonical_json_bytes(transcript)
    _write_create_only(path, raw)
    gpu_result = raw_results[0]
    if gpu_result.get("execution_status") == "completed" and gpu_result.get("exit_code") == 0:
        try:
            totals = _parse_gpu_rows(bytes(gpu_result["stdout"]))
        except (ValueError, _EvidenceError) as error:
            raise ValueError("raw GPU totals are malformed; transcript retained") from error
        if requested_uuid not in totals:
            raise ValueError("requested GPU UUID is absent; transcript retained")
    if parse_error is not None:
        raise ValueError("raw compute-app rows are malformed; transcript retained") from parse_error
    return transcript


def _validate_observer(value: object) -> dict[str, Any]:
    observer = _sealed(value, _OBSERVER_FIELDS, "GPU observer identity")
    if observer.get("contract_version") != _GPU_OBSERVER_CONTRACT or observer.get("kind") not in {
        "production_direct",
        "test_fixture",
    }:
        raise _EvidenceError("invalid_gpu_observer", "GPU observer identity contract differs")
    _text(observer.get("platform"), "GPU observer platform")
    module_ref = _closed(observer.get("collector_module_ref"), _FILE_REF_FIELDS, "collector module ref")
    _text(module_ref["canonical_path"], "collector module path")
    _sha(module_ref["file_sha256"], "collector module SHA")
    executable_ref = observer.get("nvidia_smi_ref")
    if executable_ref is not None:
        executable = _closed(executable_ref, _FILE_REF_FIELDS, "nvidia-smi ref")
        _text(executable["canonical_path"], "nvidia-smi path")
        _sha(executable["file_sha256"], "nvidia-smi SHA")
    _process_identity(observer.get("collector_process_identity"), "collector process identity")
    return observer


def _validate_sample(value: object) -> dict[str, Any]:
    sample = _sealed(value, _SAMPLE_FIELDS, "raw GPU sample")
    if sample.get("contract_version") != _SAMPLE_CONTRACT:
        raise _EvidenceError("wrong_sample_contract", "raw GPU sample contract differs")
    observer = _validate_observer(sample.get("observer_identity"))
    expected_mode = "production_direct" if observer["kind"] == "production_direct" else "test_fixture"
    if sample.get("collection_mode") != expected_mode:
        raise _EvidenceError("observer_mode_mismatch", "sample collection mode and observer differ")
    _text(sample.get("device_uuid"), "sample device_uuid")
    started = _timestamp(sample.get("sample_started_at_utc"), "sample start")
    finished = _timestamp(sample.get("sample_finished_at_utc"), "sample finish")
    if finished < started:
        raise _EvidenceError("timestamp_order", "sample finishes before it starts")
    if sample.get("artifact_is_authorization") is not False or sample.get("execute_binding_enabled") is not False:
        raise _EvidenceError("authorizing_artifact", "sample safety fields differ")
    commands = sample.get("commands")
    if not isinstance(commands, list) or len(commands) != 2:
        raise _EvidenceError("wrong_command_count", "sample must contain exactly two commands")
    for index, ((expected_role, expected_argv), raw_command) in enumerate(zip(_GPU_COMMANDS, commands)):
        command = _closed(raw_command, _COMMAND_FIELDS, f"command[{index}]")
        if command.get("role") != expected_role or command.get("argv") != list(expected_argv):
            raise _EvidenceError("wrong_command", "sample command order or argv differs")
        command_started = _timestamp(command.get("started_at_utc"), f"command[{index}] start")
        command_finished = _timestamp(command.get("finished_at_utc"), f"command[{index}] finish")
        if command_finished < command_started or command_started < started or command_finished > finished:
            raise _EvidenceError("timestamp_order", "command timestamp is outside sample")
        status = command.get("execution_status")
        timed_out = command.get("timed_out")
        exit_code = command.get("exit_code")
        os_error = command.get("os_error_code")
        if status == "completed":
            if timed_out is not False or isinstance(exit_code, bool) or not isinstance(exit_code, int) or os_error is not None:
                raise _EvidenceError("command_state_contradiction", "completed command fields contradict")
        elif status == "timed_out":
            if timed_out is not True or exit_code is not None or os_error is not None:
                raise _EvidenceError("command_state_contradiction", "timeout command fields contradict")
        elif status == "launch_failed":
            if timed_out is not False or exit_code is not None or isinstance(os_error, bool) or not isinstance(os_error, int):
                raise _EvidenceError("command_state_contradiction", "launch failure fields contradict")
        else:
            raise _EvidenceError("command_state_contradiction", "command execution status differs")
        _decode_raw_stream(command.get("stdout_raw"), f"command[{index}] stdout")
        _decode_raw_stream(command.get("stderr_raw"), f"command[{index}] stderr")
    snapshot = _sealed(sample.get("process_snapshot"), _SNAPSHOT_FIELDS, "process snapshot")
    if snapshot.get("contract_version") != _PROCESS_SNAPSHOT_CONTRACT or snapshot.get("status") not in {
        "complete",
        "partial",
        "unavailable",
    }:
        raise _EvidenceError("invalid_process_snapshot", "process snapshot contract differs")
    _timestamp(snapshot.get("observed_at_utc"), "process snapshot timestamp")
    raw_identities = snapshot.get("identities")
    raw_unobserved = snapshot.get("unobserved_pids")
    if not isinstance(raw_identities, list) or not isinstance(raw_unobserved, list):
        raise _EvidenceError("invalid_process_snapshot", "process snapshot lists differ")
    identities = [_process_identity(item, "snapshot identity") for item in raw_identities]
    identity_keys = [(item["pid"], item["create_time_ns"]) for item in identities]
    unobserved = [_integer(pid, "unobserved PID", minimum=1) for pid in raw_unobserved]
    if identity_keys != sorted(set(identity_keys)) or unobserved != sorted(set(unobserved)):
        raise _EvidenceError("invalid_process_snapshot", "process snapshot is not sorted and unique")
    if len({pid for pid, _created in identity_keys}) != len(identity_keys):
        raise _EvidenceError("pid_incarnation_ambiguous", "one sample contains multiple incarnations for one PID")
    if set(unobserved) & {pid for pid, _created in identity_keys}:
        raise _EvidenceError("invalid_process_snapshot", "observed and unobserved PID sets overlap")
    expected_status = "partial" if unobserved else "complete"
    if snapshot["status"] == "unavailable":
        if identities:
            raise _EvidenceError("invalid_process_snapshot", "unavailable snapshot contains identities")
    elif snapshot["status"] != expected_status:
        raise _EvidenceError("invalid_process_snapshot", "process snapshot status differs")
    return sample


def _csv_lines(raw: bytes, name: str) -> list[list[str]]:
    if raw == b"":
        return []
    if b"\r" in raw or not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        raise _EvidenceError("malformed_gpu_csv", f"{name} must have one LF after each non-empty row")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise _EvidenceError("malformed_gpu_csv", f"{name} is not UTF-8") from error
    result: list[list[str]] = []
    for line in text[:-1].split("\n"):
        fields = [field.strip(" ") for field in line.split(",")]
        if any(not field or "\t" in field for field in fields):
            raise _EvidenceError("malformed_gpu_csv", f"{name} contains an empty or noncanonical field")
        result.append(fields)
    return result


def _parse_memory(value: str, name: str) -> int:
    if value in {"N/A", "[Not Supported]"} or not value.isascii() or not value.isdecimal():
        raise _EvidenceError("unobservable_gpu_memory", f"{name} is not an observed integer", disposition="indeterminate")
    return int(value)


def _parse_gpu_rows(raw: bytes) -> dict[str, int]:
    totals: dict[str, int] = {}
    for fields in _csv_lines(raw, "GPU totals CSV"):
        if len(fields) != 2:
            raise _EvidenceError("malformed_gpu_csv", "GPU totals row must contain exactly two fields")
        device_uuid, memory = fields
        if device_uuid in totals:
            raise _EvidenceError("duplicate_gpu_row", "GPU totals contain a duplicate UUID")
        totals[device_uuid] = _parse_memory(memory, "GPU memory")
    return totals


def _parse_compute_rows(raw: bytes) -> list[tuple[int, str, int]]:
    rows: list[tuple[int, str, int]] = []
    seen: set[tuple[int, str]] = set()
    for fields in _csv_lines(raw, "compute-app CSV"):
        if len(fields) != 3 or not fields[0].isascii() or not fields[0].isdecimal():
            raise _EvidenceError("malformed_compute_csv", "compute-app row must contain PID, UUID, and memory")
        pid = int(fields[0])
        if pid <= 0:
            raise _EvidenceError("malformed_compute_csv", "compute-app PID must be positive")
        key = (pid, fields[1])
        if key in seen:
            raise _EvidenceError("duplicate_compute_row", "compute-app rows contain a duplicate PID/device tuple")
        seen.add(key)
        rows.append((pid, fields[1], _parse_memory(fields[2], "compute-app memory")))
    return rows


def _finding(code: str, disposition: str, refs: list[str] | tuple[str, ...] = ()) -> dict[str, object]:
    return {"code": code, "disposition": disposition, "evidence_refs": sorted(set(refs))}


def _source_ref(path: Path, value: Mapping[str, object], role: str) -> dict[str, str]:
    return {
        "semantic_role": role,
        "canonical_path": str(path),
        "content_sha256": str(value["content_sha256"]),
    }


def _validate_task4_events(root_path: Path, root: Mapping[str, object]) -> tuple[list[dict[str, Any]], dict[str, object]]:
    declared_event_path = Path(str(root.get("events_path")))
    declared_anchor_path = Path(str(root.get("root_anchor_path")))
    expected_events = root_path.with_name(root_path.name + ".events.jsonl")
    if declared_event_path != expected_events or not declared_event_path.is_absolute():
        raise _EvidenceError("task4_path_mismatch", "Task 4 event path differs")
    if Path(str(root.get("journal_path"))) != root_path:
        raise _EvidenceError("task4_path_mismatch", "Task 4 root path differs")
    anchor_path, anchor_raw = _read_input(declared_anchor_path, "Task 4 root anchor")
    if anchor_raw != canonical_json_bytes(dict(root)):
        raise _EvidenceError("task4_anchor_mismatch", "Task 4 immutable root anchor differs")
    event_path, event_raw = _read_input(declared_event_path, "Task 4 event stream")
    if not event_raw or not event_raw.endswith(b"\n") or event_raw.endswith(b"\n\n"):
        raise _EvidenceError("task4_event_stream_invalid", "Task 4 event stream framing differs")
    raw_lines = event_raw[:-1].split(b"\n")
    events: list[dict[str, Any]] = []
    previous = "0" * 64
    previous_type: str | None = None
    transitions = {
        None: {"launch_intent"},
        "launch_intent": {"job_created", "finalization_intent"},
        "job_created": {"process_created", "finalization_intent"},
        "process_created": {"hwnd_published", "finalization_intent"},
        "hwnd_published": {"ready", "finalization_intent"},
        "ready": {"finalization_intent"},
        "finalization_intent": {"cleanup_verified"},
        "cleanup_verified": set(),
    }
    root_raw_sha = _sha_bytes(canonical_json_bytes(dict(root)))
    for sequence, raw_line in enumerate(raw_lines):
        event = _decode_canonical_json(raw_line, f"Task 4 event {sequence}")
        event = _sealed(event, _TASK4_EVENT_FIELDS, f"Task 4 event {sequence}")
        event_type = event.get("event_type")
        if (
            event.get("contract_version") != "portfolio_hybrid_benchmark_v2_window_owner_event_v1"
            or event.get("sequence") != sequence
            or event.get("owner_id") != root.get("owner_id")
            or event.get("previous_event_sha256") != previous
            or event.get("root_anchor_sha256") != root_raw_sha
            or event_type not in transitions.get(previous_type, set())
        ):
            raise _EvidenceError("task4_event_chain_invalid", "Task 4 event predecessor or transition differs")
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            raise _EvidenceError("task4_event_payload_invalid", "Task 4 event payload is not an object")
        if event_type == "process_created":
            if set(payload) != {"process_identity"}:
                raise _EvidenceError("task4_event_payload_invalid", "Task 4 process event fields differ")
            _process_identity(payload["process_identity"], "Task 4 process identity")
        elif event_type == "cleanup_verified":
            cleanup = _sealed(payload, _TASK4_CLEANUP_FIELDS, "Task 4 cleanup")
            if cleanup.get("contract_version") != "portfolio_hybrid_benchmark_v2_window_cleanup_v1":
                raise _EvidenceError("task4_cleanup_invalid", "Task 4 cleanup contract differs")
        events.append(event)
        previous = str(event["content_sha256"])
        previous_type = str(event_type)
    if previous_type != "cleanup_verified":
        raise _EvidenceError("task4_cleanup_missing", "Task 4 terminal cleanup event is absent")
    cleanup = deepcopy(dict(events[-1]["payload"]))
    process_events = [event for event in events if event["event_type"] == "process_created"]
    finalizations = [event for event in events if event["event_type"] == "finalization_intent"]
    publication_events = [event for event in events if event["event_type"] == "hwnd_published"]
    ready_events = [event for event in events if event["event_type"] == "ready"]
    if len(process_events) != 1 or len(finalizations) != 1:
        raise _EvidenceError("task4_lineage_ambiguous", "Task 4 process/finalization lineage is ambiguous")
    expected_identity = process_events[0]["payload"]["process_identity"]
    if (
        cleanup.get("owner_id") != root.get("owner_id")
        or cleanup.get("process_identity") != expected_identity
        or cleanup.get("process_event_sha256") != process_events[0]["content_sha256"]
        or cleanup.get("finalization_intent_sha256") != finalizations[0]["content_sha256"]
    ):
        raise _EvidenceError("task4_cleanup_lineage_mismatch", "Task 4 cleanup lineage differs")
    if ready_events:
        if len(ready_events) != 1 or len(publication_events) != 1:
            raise _EvidenceError("task4_lineage_ambiguous", "Task 4 ready/publication lineage is ambiguous")
        publication = publication_events[0]["payload"].get("publication")
        binding = ready_events[0]["payload"].get("binding")
        if (
            not isinstance(publication, Mapping)
            or not isinstance(binding, Mapping)
            or publication.get("content_sha256") != content_sha256(dict(publication))
            or binding.get("content_sha256") != content_sha256(dict(binding))
            or cleanup.get("ready_event_sha256") != ready_events[0]["content_sha256"]
            or cleanup.get("publication_content_sha256") != publication.get("content_sha256")
            or cleanup.get("exact_hwnd") != publication.get("hwnd")
            or binding.get("process_identity") != expected_identity
            or binding.get("hwnd") != publication.get("hwnd")
        ):
            raise _EvidenceError("task4_cleanup_lineage_mismatch", "Task 4 ready cleanup lineage differs")
    if (
        cleanup.get("cleanup_status") != "verified"
        or cleanup.get("artifact_is_authorization") is not False
        or cleanup.get("execute_binding_enabled") is not False
    ):
        raise _EvidenceError("task4_cleanup_invalid", "Task 4 cleanup is not verified")
    residue_fields = (
        "matching_owned_windows_after",
        "member_pids_after",
        "active_listeners_after",
        "listener_or_lease_residue",
    )
    if any(cleanup.get(field) for field in residue_fields) or any(
        cleanup.get(field) is not True
        for field in (
            "shutdown_event_handle_closed",
            "enum_windows_exact_hwnd_absent",
            "scope_absent_after_owner_close",
            "process_handle_closed",
            "job_handle_closed",
        )
    ) or _integer(cleanup.get("stable_zero_observations"), "Task 4 stable-zero") < 3:
        raise _EvidenceError("task4_cleanup_residue", "Task 4 cleanup retains process/window/handle residue")
    return events, {
        "path": str(event_path),
        "anchor_path": str(anchor_path),
        "raw_sha256": _sha_bytes(event_raw),
    }


def _validate_parent_document(value: dict[str, Any]) -> str:
    contract = value.get("contract_version")
    schemas: dict[str, tuple[str, set[str]]] = {
        "portfolio_hybrid_benchmark_v2_window_owner_journal_v1": ("task4_window_root", _TASK4_ROOT_FIELDS),
        "benchmark_v2_worker_window_binding_authority_v1": ("task5_binding_authority", _TASK5_AUTHORITY_FIELDS),
        "portfolio_hybrid_benchmark_v2_worker_window_binding_normal_clear_v1": ("task5_normal_clear", _TASK5_CLEAR_FIELDS),
        "benchmark_worker_scope_assignment_v1": ("b1_assignment", _B1_ASSIGNMENT_FIELDS),
        "benchmark_worker_owner_journal_v1": ("b1_owner", _B1_OWNER_FIELDS),
        "benchmark_worker_cleanup_receipt_v1": ("b1_cleanup", _B1_CLEANUP_FIELDS),
        "benchmark_provider_runtime_owner_v1": ("b2_runtime_owner", _B2_RUNTIME_FIELDS),
        "qwen_model_request_materialization_ledger_v1": ("b2_materialization_ledger", _B2_LEDGER_FIELDS),
        "benchmark_provider_registry_journal_v1": ("b2_provider_journal", _B2_JOURNAL_FIELDS),
        "benchmark_provider_cleanup_registry_journal_v1": (
            "b2_provider_cleanup_journal",
            _B2_CLEANUP_JOURNAL_FIELDS,
        ),
        "qwen_model_request_cleanup_receipt_v1": ("b2_cleanup", _B2_CLEANUP_FIELDS),
    }
    if contract not in schemas:
        raise _EvidenceError("unknown_parent_contract", f"unsupported owner parent contract: {contract!r}")
    role, fields = schemas[str(contract)]
    _sealed(value, fields, role)
    for safety_field in ("artifact_is_authorization", "execute_binding_enabled"):
        if safety_field in value and value[safety_field] is not False:
            raise _EvidenceError("authorizing_artifact", f"{role} safety field differs")
    return role


def _load_parent_graph(paths: list[Path]) -> tuple[dict[str, list[tuple[Path, dict[str, Any]]]], list[dict[str, str]], list[dict[str, object]]]:
    roles: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    refs: list[dict[str, str]] = []
    findings: list[dict[str, object]] = []
    resolved_seen: set[str] = set()
    content_seen: set[str] = set()
    for index, input_path in enumerate(paths):
        resolved, raw = _read_input(input_path, f"owner_journal_paths[{index}]")
        key = os.path.normcase(str(resolved))
        if key in resolved_seen:
            raise _EvidenceError("duplicate_input_path", "owner input path is duplicated or aliased")
        resolved_seen.add(key)
        value = _decode_canonical_json(raw, f"owner parent {resolved}")
        role = _validate_parent_document(value)
        digest = str(value["content_sha256"])
        if digest in content_seen:
            raise _EvidenceError("duplicate_input_content", "owner input content is duplicated under another path")
        content_seen.add(digest)
        roles.setdefault(role, []).append((resolved, value))
        refs.append(_source_ref(resolved, value, role))
    task4_roots = roles.get("task4_window_root", [])
    if len(task4_roots) != 1:
        raise _EvidenceError("task4_root_cardinality", "exactly one Task 4 root is required")
    task4_path, task4_root = task4_roots[0]
    if task4_root.get("artifact_is_authorization") is not False or task4_root.get("execute_binding_enabled") is not False or task4_root.get("display_only") is not True:
        raise _EvidenceError("task4_safety_mismatch", "Task 4 root safety fields differ")
    task4_events, event_ref = _validate_task4_events(task4_path, task4_root)
    roles["task4_events"] = [(Path(event_ref["path"]), {"events": task4_events, **event_ref})]
    refs.append(
        {
            "semantic_role": "task4_events",
            "canonical_path": str(event_ref["path"]),
            "content_sha256": str(event_ref["raw_sha256"]),
        }
    )
    for role, required_count in (
        ("task5_binding_authority", 1),
        ("b1_cleanup", 1),
        ("b2_runtime_owner", 1),
        ("b2_materialization_ledger", 1),
    ):
        if len(roles.get(role, [])) != required_count:
            raise _EvidenceError("missing_owner_parent", f"{role} requires exactly {required_count} raw parent")
    if not roles.get("b1_owner"):
        raise _EvidenceError("missing_owner_parent", "at least one B1 owner journal is required")
    if len(roles.get("b2_provider_journal", [])) + len(roles.get("b2_provider_cleanup_journal", [])) != 1:
        raise _EvidenceError(
            "missing_owner_parent",
            "exactly one B2 provider or cleanup registry journal is required",
        )
    for singleton in (
        "task5_binding_authority",
        "task5_normal_clear",
        "b1_assignment",
        "b1_cleanup",
        "b2_runtime_owner",
        "b2_materialization_ledger",
        "b2_provider_journal",
        "b2_provider_cleanup_journal",
        "b2_cleanup",
    ):
        if len(roles.get(singleton, [])) > 1:
            raise _EvidenceError("duplicate_owner_parent", f"{singleton} is duplicated")
    return roles, sorted(refs, key=lambda item: (item["semantic_role"], item["content_sha256"], item["canonical_path"])), findings


def _one(roles: Mapping[str, list[tuple[Path, dict[str, Any]]]], role: str) -> dict[str, Any] | None:
    values = roles.get(role, [])
    return values[0][1] if len(values) == 1 else None


def _same_ref(left: object, right: object) -> bool:
    return isinstance(left, Mapping) and isinstance(right, Mapping) and left.get("content_sha256") == right.get("content_sha256")


def _derive_parent_facts(
    roles: dict[str, list[tuple[Path, dict[str, Any]]]]
) -> tuple[list[dict[str, object]], dict[str, str], list[dict[str, object]], dict[str, str], dict[str, str]]:
    findings: list[dict[str, object]] = []
    owners: list[dict[str, object]] = []
    root = _one(roles, "task4_window_root")
    authority = _one(roles, "task5_binding_authority")
    assignment = _one(roles, "b1_assignment")
    worker_cleanup = _one(roles, "b1_cleanup")
    runtime_owner = _one(roles, "b2_runtime_owner")
    ledger = _one(roles, "b2_materialization_ledger")
    provider_journal = _one(roles, "b2_provider_journal") or _one(
        roles, "b2_provider_cleanup_journal"
    )
    provider_cleanup = _one(roles, "b2_cleanup")
    assert root is not None and authority is not None
    assert worker_cleanup is not None and runtime_owner is not None and ledger is not None and provider_journal is not None

    events = roles["task4_events"][0][1]["events"]
    process_event = next(event for event in events if event["event_type"] == "process_created")
    ready_events = [event for event in events if event["event_type"] == "ready"]
    window_identity = _process_identity(process_event["payload"]["process_identity"], "Task 4 owner identity")
    owners.append({"kind": "window", "subject_id": root["owner_id"], "process_identity": window_identity, "evidence_ref": root["content_sha256"]})

    serialized = _closed(authority.get("serialized_window_binding"), _SERIALIZED_BINDING_FIELDS, "Task 5 serialized binding")
    payload_unsealed = {key: value for key, value in serialized.items() if key != "payload_sha256"}
    if serialized.get("payload_sha256") != _sha_bytes(canonical_json_bytes(payload_unsealed)):
        findings.append(_finding("binding_payload_seal_mismatch", "failed", [str(authority["content_sha256"])]))
    ready_event = ready_events[0] if len(ready_events) == 1 else None
    ready_binding = ready_event["payload"].get("binding") if ready_event is not None else None
    if (
        serialized.get("operation_id") != root.get("operation_id")
        or serialized.get("owner_journal_path") != root.get("journal_path")
        or serialized.get("owner_journal_content_sha256") != root.get("content_sha256")
        or serialized.get("owner_id") != root.get("owner_id")
        or serialized.get("process_identity") != window_identity
        or authority.get("owner_journal_ref", {}).get("content_sha256") != root.get("content_sha256")
        or ready_event is None
        or not isinstance(ready_binding, Mapping)
        or authority.get("owner_ready_event_ref", {}).get("content_sha256") != ready_event.get("content_sha256")
        or serialized.get("owner_ready_event_sha256") != ready_event.get("content_sha256")
        or authority.get("owner_binding_ref", {}).get("content_sha256") != ready_binding.get("content_sha256")
        or serialized.get("owner_binding_content_sha256") != ready_binding.get("content_sha256")
    ):
        findings.append(_finding("task4_task5_parent_mismatch", "failed", [str(root["content_sha256"]), str(authority["content_sha256"])]))

    primary_owner = roles["b1_owner"][0][1]
    if worker_cleanup.get("outcome") not in {"verified_exact_worker_exited", "verified_not_launched"}:
        findings.append(_finding("b1_cleanup_outcome_invalid", "failed", [str(worker_cleanup["content_sha256"])]))
    if worker_cleanup.get("outcome") == "verified_exact_worker_exited":
        if assignment is None:
            raise _EvidenceError("missing_owner_parent", "launched B1 worker requires one assignment parent")
        assignment_identity = _process_identity(assignment.get("process_identity"), "B1 assignment identity")
        observed = assignment.get("observed_member_identities")
        if not isinstance(observed, list) or assignment_identity not in observed:
            findings.append(_finding("b1_assignment_membership_missing", "failed", [str(assignment["content_sha256"])]))
        for _path, owner in roles["b1_owner"]:
            identity = _process_identity(owner.get("process_identity"), "B1 owner identity")
            owners.append({"kind": "outer_worker", "subject_id": owner["worker_id"], "process_identity": identity, "evidence_ref": owner["content_sha256"]})
            if owner.get("assignment_observation_ref", {}).get("content_sha256") != assignment.get("content_sha256") or identity != assignment_identity:
                findings.append(_finding("b1_assignment_identity_mismatch", "failed", [str(owner["content_sha256"]), str(assignment["content_sha256"])]))
        if (
            worker_cleanup.get("process_identity") != primary_owner.get("process_identity")
            or worker_cleanup.get("operation_id") != primary_owner.get("operation_id")
            or worker_cleanup.get("worker_id") != primary_owner.get("worker_id")
            or not worker_cleanup.get("exact_handle_observation_refs")
            or worker_cleanup.get("job_absence_observation_ref") is None
            or worker_cleanup.get("worker_absence_observation_ref") is None
        ):
            findings.append(_finding("b1_cleanup_lineage_mismatch", "failed", [str(worker_cleanup["content_sha256"])]))
    else:
        assignment_identity = None
        if assignment is not None or any(
            owner.get(field) is not None
            for _path, owner in roles["b1_owner"]
            for field in ("process_identity", "scope_name", "assignment_observation_ref", "job_policy")
        ) or any(
            worker_cleanup.get(field) is not None
            for field in (
                "process_identity",
                "assignment_proven_ref",
                "finalization_intent_ref",
                "job_absence_observation_ref",
                "worker_absence_observation_ref",
            )
        ) or worker_cleanup.get("exact_handle_observation_refs") != [] or worker_cleanup.get("reservation_abort_ref") is None:
            findings.append(_finding("b1_not_launched_branch_contradiction", "failed", [str(worker_cleanup["content_sha256"])]))

    normal = _one(roles, "task5_normal_clear")
    binding_status = "verified"
    if normal is None:
        binding_status = "inapplicable_strong_kill"
    else:
        if (
            assignment_identity is None
            or
            normal.get("operation_id") != authority.get("operation_id")
            or normal.get("binding_payload_sha256") != serialized.get("payload_sha256")
            or normal.get("worker_pid") != assignment_identity["pid"]
            or normal.get("cleared") is not True
            or normal.get("prior_binding_restored") is not False
            or normal.get("restored_hwnd") is not None
        ):
            findings.append(_finding("task5_normal_clear_mismatch", "failed", [str(normal["content_sha256"])]))

    lineage_fields = ("run_id", "stage", "operation_id", "worker_id", "model_request_id", "payload_sha256")
    lineage_documents = [primary_owner, runtime_owner, provider_journal]
    for field in lineage_fields:
        values = {document.get(field) for document in lineage_documents}
        if len(values) != 1:
            code = "cross_operation_parent" if field == "operation_id" else f"cross_{field}_parent"
            findings.append(_finding(code, "failed", [str(document["content_sha256"]) for document in lineage_documents]))
    if authority.get("operation_id") != primary_owner.get("operation_id") or root.get("operation_id") != primary_owner.get("operation_id"):
        findings.append(_finding("cross_operation_parent", "failed", [str(root["content_sha256"]), str(authority["content_sha256"]), str(primary_owner["content_sha256"])]))
    reservation_refs = [primary_owner.get("reservation_ref"), runtime_owner.get("reservation_ref"), provider_journal.get("reservation_ref")]
    if len({_content_ref(item, "reservation ref")["content_sha256"] for item in reservation_refs}) != 1:
        findings.append(_finding("cross_reservation_parent", "failed", [str(document["content_sha256"]) for document in lineage_documents]))
    if (
        provider_journal.get("runtime_owner_ref", {}).get("content_sha256") != runtime_owner.get("content_sha256")
        or ledger.get("runtime_owner_ref", {}).get("content_sha256") != runtime_owner.get("content_sha256")
        or provider_journal.get("acquisition_intent_ref") != ledger.get("acquisition_intent_ref")
    ):
        findings.append(_finding("b2_parent_lineage_mismatch", "failed", [str(runtime_owner["content_sha256"]), str(ledger["content_sha256"]), str(provider_journal["content_sha256"])]))
    if provider_journal.get("contract_version") == "benchmark_provider_registry_journal_v1" and provider_journal.get(
        "materialization_ledger_ref", {}
    ).get("content_sha256") != ledger.get("content_sha256"):
        findings.append(_finding("b2_parent_lineage_mismatch", "failed", [str(ledger["content_sha256"]), str(provider_journal["content_sha256"])]))
    if provider_journal.get("contract_version") == "benchmark_provider_cleanup_registry_journal_v1":
        if provider_cleanup is None or provider_journal.get("cleanup_receipt_ref", {}).get(
            "content_sha256"
        ) != provider_cleanup.get("content_sha256"):
            findings.append(_finding("b2_cleanup_registry_ref_mismatch", "failed", [str(provider_journal["content_sha256"])]))

    provider_status = "pending"
    if ledger.get("state") == "materialization_possible":
        if provider_cleanup is None:
            provider_status = "pending_materialized"
            findings.append(_finding("materialized_without_terminal_sidecar", "indeterminate", [str(ledger["content_sha256"])]))
        elif provider_cleanup.get("outcome") != "verified_exact_process_exited":
            provider_status = "contradictory"
            findings.append(_finding("b2_materialization_cleanup_contradiction", "failed", [str(ledger["content_sha256"]), str(provider_cleanup["content_sha256"])]))
        else:
            provider_status = "verified_exact_process_exited"
            provider_identity = _process_identity(provider_cleanup.get("server_process_identity"), "B2 server identity")
            owners.append({"kind": "qwen_runtime", "subject_id": runtime_owner["model_request_id"], "process_identity": provider_identity, "evidence_ref": provider_cleanup["content_sha256"]})
            if (
                provider_cleanup.get("model_request_id") != runtime_owner.get("model_request_id")
                or provider_cleanup.get("runtime_owner_ref", {}).get("content_sha256") != runtime_owner.get("content_sha256")
                or provider_cleanup.get("acquisition_intent_ref") != ledger.get("acquisition_intent_ref")
                or any(provider_cleanup.get(field) is None for field in (
                    "lease_ref",
                    "profile_ref",
                    "socket_ref",
                    "job_scope_ref",
                    "lease_state_ref",
                    "owner_tombstone_ref",
                    "termination_observation_ref",
                    "scope_stable_zero_ref",
                    "listener_stable_zero_ref",
                    "no_active_lease_observation_ref",
                ))
                or provider_cleanup.get("no_owned_runtime_observation_ref") is not None
            ):
                findings.append(_finding("b2_cleanup_lineage_mismatch", "failed", [str(provider_cleanup["content_sha256"])]))
    elif ledger.get("state") == "aborted_never_materialized":
        if provider_cleanup is None or provider_cleanup.get("outcome") != "verified_not_acquired":
            provider_status = "contradictory"
            findings.append(_finding("b2_not_acquired_cleanup_contradiction", "failed", [str(ledger["content_sha256"])]))
        else:
            provider_status = "verified_not_acquired"
            forbidden_owned = (
                "lease_ref",
                "profile_ref",
                "server_process_identity",
                "socket_ref",
                "job_scope_ref",
                "finalization_token",
                "lease_state_ref",
                "termination_observation_ref",
            )
            if any(provider_cleanup.get(field) is not None for field in forbidden_owned):
                findings.append(_finding("b2_not_acquired_contains_owner", "failed", [str(provider_cleanup["content_sha256"])]))
    else:
        provider_status = "pending_materialization"
        findings.append(_finding("b2_materialization_state_pending", "indeterminate", [str(ledger["content_sha256"])]))

    cleanup_summary = {
        "window": "verified",
        "binding": binding_status,
        "worker": str(worker_cleanup.get("outcome")),
        "provider": provider_status,
        "stable_zero": "verified" if not any(item["code"].endswith("residue") for item in findings) else "failed",
    }
    lineage = {field: str(primary_owner.get(field)) for field in lineage_fields}
    authorities = {
        "task5": str(authority.get("authority_kind")),
        "b1": str(primary_owner.get("authority_kind")),
        "b2_runtime": str(runtime_owner.get("authority_kind")),
        "b2_journal": str(provider_journal.get("authority_kind")),
    }
    return owners, cleanup_summary, findings, lineage, authorities


def _load_samples(paths: list[Path]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    samples: list[dict[str, Any]] = []
    refs: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    seen_content: set[str] = set()
    for index, input_path in enumerate(paths):
        resolved, raw = _read_input(input_path, f"sampler_transcript_paths[{index}]")
        path_key = os.path.normcase(str(resolved))
        if path_key in seen_paths:
            raise _EvidenceError("duplicate_input_path", "sampler path is duplicated or aliased")
        seen_paths.add(path_key)
        sample = _validate_sample(_decode_canonical_json(raw, f"raw GPU sample {resolved}"))
        digest = str(sample["content_sha256"])
        if digest in seen_content:
            raise _EvidenceError("duplicate_input_content", "sampler content is duplicated")
        seen_content.add(digest)
        sample["_path"] = str(resolved)
        samples.append(sample)
        refs.append(_source_ref(resolved, sample, "raw_gpu_sample"))
    samples.sort(key=lambda item: (str(item["sample_started_at_utc"]), str(item["content_sha256"])))
    refs.sort(key=lambda item: (item["content_sha256"], item["canonical_path"]))
    return samples, refs


def _sample_observation(sample: Mapping[str, Any]) -> tuple[dict[str, int], list[tuple[int, int, str, int]], set[int], list[dict[str, object]]]:
    findings: list[dict[str, object]] = []
    commands = sample["commands"]
    for command in commands:
        if command["execution_status"] != "completed" or command["exit_code"] != 0:
            findings.append(_finding("raw_gpu_command_unavailable", "indeterminate", [str(sample["content_sha256"])]))
            return {}, [], set(), findings
    totals = _parse_gpu_rows(_decode_raw_stream(commands[0]["stdout_raw"], "GPU totals stdout"))
    rows = _parse_compute_rows(_decode_raw_stream(commands[1]["stdout_raw"], "compute-app stdout"))
    if sample["device_uuid"] not in totals:
        raise _EvidenceError("requested_gpu_uuid_absent", "requested GPU UUID is absent")
    snapshot = sample["process_snapshot"]
    identities_by_pid = {int(item["pid"]): int(item["create_time_ns"]) for item in snapshot["identities"]}
    unobserved = set(int(pid) for pid in snapshot["unobserved_pids"])
    exact_rows: list[tuple[int, int, str, int]] = []
    for pid, gpu_uuid, memory in rows:
        if pid in unobserved or pid not in identities_by_pid:
            findings.append(_finding("pid_create_time_unobserved", "indeterminate", [str(sample["content_sha256"])]))
            continue
        exact_rows.append((pid, identities_by_pid[pid], gpu_uuid, memory))
    for gpu_uuid in {row[2] for row in exact_rows}:
        if gpu_uuid not in totals:
            raise _EvidenceError("compute_device_total_missing", "compute-app device has no GPU total")
    return totals, sorted(exact_rows), unobserved, findings


def _account_gpu(
    samples: list[dict[str, Any]], owners: list[dict[str, object]]
) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    findings: list[dict[str, object]] = []
    empty = {
        "device_uuid": None,
        "baseline_ref": None,
        "in_flight_refs": [],
        "post_ref": None,
        "owned_process_vram": [],
        "owned_peak_mib": None,
        "owned_post_mib": None,
        "external_fingerprint_baseline": [],
        "external_fingerprint_post": [],
        "external_fingerprint_status": "indeterminate",
        "device_used_baseline_mib": None,
        "device_used_post_mib": None,
        "device_residual_baseline_mib": None,
        "device_residual_post_mib": None,
        "device_residual_status": "indeterminate",
    }
    max_concurrent = {"window": 0, "outer_worker": 0, "qwen_runtime": 0}
    owner_summary: dict[str, object] = {"intervals": [], "max_concurrent_by_kind": max_concurrent, "overlap_status": "indeterminate"}
    if len(samples) < 3:
        findings.append(_finding("missing_sample_interval", "indeterminate"))
        return empty, owner_summary, findings
    device_uuids = {str(sample["device_uuid"]) for sample in samples}
    if len(device_uuids) != 1:
        findings.append(_finding("cross_device_samples", "failed", [str(sample["content_sha256"]) for sample in samples]))
        return empty, owner_summary, findings
    device_uuid = next(iter(device_uuids))
    observations: list[dict[str, Any]] = []
    for sample in samples:
        try:
            totals, rows, unobserved, sample_findings = _sample_observation(sample)
            findings.extend(sample_findings)
            observations.append({"sample": sample, "totals": totals, "rows": rows, "unobserved": unobserved})
        except _EvidenceError as error:
            findings.append(_finding(error.code, error.disposition, [str(sample["content_sha256"])]))
            observations.append({"sample": sample, "totals": {}, "rows": [], "unobserved": set()})
    owner_keys: dict[tuple[int, int], list[dict[str, object]]] = {}
    for owner in owners:
        identity = owner["process_identity"]
        key = (int(identity["pid"]), int(identity["create_time_ns"]))
        owner_keys.setdefault(key, []).append(owner)
    for key, claims in owner_keys.items():
        if len(claims) > 1:
            findings.append(_finding("duplicate_exact_owner_claim", "failed", [str(claim["evidence_ref"]) for claim in claims]))

    presence: dict[tuple[str, str, int, int], list[int]] = {}
    for index, observation in enumerate(observations):
        snapshot = observation["sample"]["process_snapshot"]
        identities = {(int(item["pid"]), int(item["create_time_ns"])) for item in snapshot["identities"]}
        for owner in owners:
            identity = owner["process_identity"]
            key = (str(owner["kind"]), str(owner["subject_id"]), int(identity["pid"]), int(identity["create_time_ns"]))
            if (key[2], key[3]) in identities:
                presence.setdefault(key, []).append(index)
    intervals: list[dict[str, object]] = []
    for owner in sorted(owners, key=lambda item: (str(item["kind"]), str(item["subject_id"]), int(item["process_identity"]["pid"]), int(item["process_identity"]["create_time_ns"]))):
        identity = owner["process_identity"]
        key = (str(owner["kind"]), str(owner["subject_id"]), int(identity["pid"]), int(identity["create_time_ns"]))
        observed_indices = presence.get(key, [])
        interval_status = "bounded"
        acquire_ref: str | None = None
        release_ref: str | None = None
        if not observed_indices or observed_indices[0] == 0:
            interval_status = "indeterminate"
        else:
            acquire_ref = str(observations[observed_indices[0]]["sample"]["content_sha256"])
            for candidate in range(observed_indices[-1] + 1, len(observations)):
                snapshot = observations[candidate]["sample"]["process_snapshot"]
                if snapshot["status"] == "complete":
                    release_ref = str(observations[candidate]["sample"]["content_sha256"])
                    break
            if release_ref is None:
                interval_status = "indeterminate"
        if interval_status == "indeterminate":
            findings.append(_finding("missing_owner_interval_bound", "indeterminate", [str(owner["evidence_ref"])]))
        intervals.append(
            {
                "kind": owner["kind"],
                "subject_id": owner["subject_id"],
                "process_identity": deepcopy(identity),
                "acquire_sample_ref": acquire_ref,
                "release_sample_ref": release_ref,
                "status": interval_status,
            }
        )
    for index, observation in enumerate(observations):
        identities = {
            (int(item["pid"]), int(item["create_time_ns"]))
            for item in observation["sample"]["process_snapshot"]["identities"]
        }
        for kind in max_concurrent:
            count = sum(
                1
                for owner in owners
                if owner["kind"] == kind
                and (int(owner["process_identity"]["pid"]), int(owner["process_identity"]["create_time_ns"])) in identities
            )
            max_concurrent[kind] = max(max_concurrent[kind], count)
            if count > 1:
                findings.append(_finding("same_kind_owner_overlap", "failed", [str(observation["sample"]["content_sha256"])]))
    overlap_status = "failed" if any(value > 1 for value in max_concurrent.values()) else "indeterminate" if any(interval_item["status"] != "bounded" for interval_item in intervals) else "verified"
    owner_summary = {"intervals": intervals, "max_concurrent_by_kind": max_concurrent, "overlap_status": overlap_status}

    per_owner: dict[tuple[int, int, str], list[int]] = {}
    external_by_sample: list[list[list[object]]] = []
    residual_by_sample: list[int | None] = []
    used_by_sample: list[int | None] = []
    owned_by_sample: list[int | None] = []
    for observation in observations:
        sample = observation["sample"]
        totals: dict[str, int] = observation["totals"]
        rows: list[tuple[int, int, str, int]] = observation["rows"]
        if device_uuid not in totals:
            external_by_sample.append([])
            residual_by_sample.append(None)
            used_by_sample.append(None)
            owned_by_sample.append(None)
            continue
        external: list[list[object]] = []
        owned_total = 0
        for pid, created, gpu_uuid, memory in rows:
            exact_claims = owner_keys.get((pid, created), [])
            numeric_claims = [key for key in owner_keys if key[0] == pid]
            if numeric_claims and not exact_claims:
                findings.append(_finding("owned_pid_reuse", "failed", [str(sample["content_sha256"])]))
                external.append([pid, created, gpu_uuid, memory])
                continue
            if exact_claims:
                if gpu_uuid == device_uuid:
                    owned_total += memory
                per_owner.setdefault((pid, created, gpu_uuid), []).append(memory)
            else:
                external.append([pid, created, gpu_uuid, memory])
        target_compute = sum(memory for _pid, _created, gpu_uuid, memory in rows if gpu_uuid == device_uuid)
        residual = totals[device_uuid] - target_compute
        if residual < 0:
            findings.append(_finding("negative_device_residual", "failed", [str(sample["content_sha256"])]))
            residual_by_sample.append(None)
        else:
            residual_by_sample.append(residual)
        used_by_sample.append(totals[device_uuid])
        owned_by_sample.append(owned_total)
        external_by_sample.append(sorted(external, key=lambda item: (int(item[0]), int(item[1]), str(item[2]), int(item[3]))))
    baseline_external = external_by_sample[0]
    post_external = external_by_sample[-1]
    external_status = "stable" if baseline_external == post_external else "changed"
    if external_status == "changed":
        findings.append(_finding("external_fingerprint_changed", "indeterminate", [str(samples[0]["content_sha256"]), str(samples[-1]["content_sha256"])]))
    residual_status = "stable" if residual_by_sample[0] is not None and residual_by_sample[0] == residual_by_sample[-1] else "changed_or_unavailable"
    if residual_status != "stable":
        findings.append(_finding("device_residual_changed_or_unavailable", "indeterminate", [str(samples[0]["content_sha256"]), str(samples[-1]["content_sha256"])]))
    if samples[-1]["process_snapshot"]["status"] != "complete" or any(
        int(owner["process_identity"]["pid"]) in set(samples[-1]["process_snapshot"]["unobserved_pids"])
        for owner in owners
    ):
        owned_by_sample[-1] = None
        findings.append(_finding("owned_post_identity_unobservable", "indeterminate", [str(samples[-1]["content_sha256"])]))
    elif owned_by_sample[-1] != 0:
        findings.append(_finding("owned_vram_residue", "failed", [str(samples[-1]["content_sha256"])]))
    owned_process_vram = [
        {
            "pid": pid,
            "create_time_ns": created,
            "gpu_uuid": gpu_uuid,
            "peak_mib": max(values),
        }
        for (pid, created, gpu_uuid), values in sorted(per_owner.items())
    ]
    gpu_summary = {
        "device_uuid": device_uuid,
        "baseline_ref": samples[0]["content_sha256"],
        "in_flight_refs": [sample["content_sha256"] for sample in samples[1:-1]],
        "post_ref": samples[-1]["content_sha256"],
        "owned_process_vram": owned_process_vram,
        "owned_peak_mib": max((value for value in owned_by_sample if value is not None), default=None),
        "owned_post_mib": owned_by_sample[-1],
        "external_fingerprint_baseline": baseline_external,
        "external_fingerprint_post": post_external,
        "external_fingerprint_status": external_status,
        "device_used_baseline_mib": used_by_sample[0],
        "device_used_post_mib": used_by_sample[-1],
        "device_residual_baseline_mib": residual_by_sample[0],
        "device_residual_post_mib": residual_by_sample[-1],
        "device_residual_status": residual_status,
    }
    return gpu_summary, owner_summary, findings


def _validate_probe(value: object) -> dict[str, Any]:
    probe = _sealed(value, _PROBE_FIELDS, "probe receipt")
    if probe.get("contract_version") != _PROBE_CONTRACT:
        raise _EvidenceError("wrong_probe_contract", "probe receipt contract differs")
    _text(probe.get("probe_id"), "probe_id")
    if probe.get("probe_kind") not in _PROBE_KINDS:
        raise _EvidenceError("extra_probe_cell", "probe kind differs")
    provider = _closed(probe.get("provider"), _PROBE_PROVIDER_FIELDS, "probe provider")
    provider_id = provider.get("provider_id")
    if provider_id not in _PROVIDERS:
        raise _EvidenceError("extra_probe_cell", "probe provider differs")
    profile_id = _text(provider.get("profile_id"), "profile_id")
    expected_profile_sha = _sha_bytes(canonical_json_bytes({"provider_id": provider_id, "profile_id": profile_id}))
    if provider.get("profile_sha256") != expected_profile_sha:
        raise _EvidenceError("probe_profile_unsealed", "probe profile SHA differs")
    for field in ("run_id", "stage", "operation_id", "model_request_id"):
        _text(probe.get(field), f"probe {field}")
    inflight = _closed(probe.get("request_in_flight_observation"), _IN_FLIGHT_FIELDS, "request-in-flight observation")
    trigger = _closed(probe.get("trigger"), _TRIGGER_FIELDS, "probe trigger")
    body = _closed(probe.get("body_completion_observation"), _BODY_FIELDS, "body completion observation")
    lease = _closed(probe.get("lease_or_owner"), _LEASE_OWNER_FIELDS, "probe lease/owner")
    termination = _closed(probe.get("termination_observation"), _TERMINATION_FIELDS, "termination observation")
    stable = _closed(probe.get("stable_zero_observation"), _STABLE_ZERO_FIELDS, "stable-zero observation")
    observer = _sealed(probe.get("observer_identity"), _PROBE_OBSERVER_FIELDS, "probe observer")
    if inflight.get("state") != "request_in_flight" or trigger.get("kind") != probe.get("probe_kind"):
        raise _EvidenceError("probe_trigger_parent_mismatch", "probe trigger does not bind the in-flight request")
    if not _same_ref(trigger.get("request_in_flight_ref"), inflight.get("evidence_ref")):
        raise _EvidenceError("probe_trigger_parent_mismatch", "probe trigger in-flight ref differs")
    in_at = _timestamp(inflight.get("observed_at_utc"), "request-in-flight timestamp")
    trigger_at = _timestamp(trigger.get("triggered_at_utc"), "trigger timestamp")
    body_at = _timestamp(body.get("observed_at_utc"), "body timestamp")
    if not in_at <= trigger_at < body_at:
        raise _EvidenceError("probe_trigger_order_invalid", "probe trigger is outside the in-flight interval")
    lease_identity = _process_identity(lease.get("process_identity"), "probe lease process identity")
    termination_identity = _process_identity(termination.get("process_identity"), "probe termination process identity")
    if termination.get("outcome") != "same_incarnation_exited" or termination_identity != lease_identity:
        raise _EvidenceError("probe_process_incarnation_mismatch", "probe termination does not prove the exact incarnation")
    for field in ("lease_ref", "socket_ref", "job_scope_ref"):
        _content_ref(lease.get(field), f"probe {field}")
    for field in ("evidence_ref",):
        _content_ref(termination.get(field), "termination evidence ref")
    if not isinstance(stable.get("job_members"), list) or not isinstance(stable.get("active_listeners"), list) or not isinstance(stable.get("active_leases"), list):
        raise _EvidenceError("probe_stable_zero_invalid", "probe stable-zero lists differ")
    for field in ("process_absence_ref", "listener_absence_ref", "lease_absence_ref"):
        _content_ref(stable.get(field), f"stable-zero {field}")
    if observer.get("kind") not in {"production_runner", "test_fixture"}:
        raise _EvidenceError("invalid_probe_observer", "probe observer kind differs")
    module_ref = _closed(observer.get("module_ref"), _FILE_REF_FIELDS, "probe observer module ref")
    _text(module_ref.get("canonical_path"), "probe observer module path")
    _sha(module_ref.get("file_sha256"), "probe observer module SHA")
    _sha(probe.get("predecessor_content_sha256"), "probe predecessor SHA")
    if probe.get("artifact_is_authorization") is not False or probe.get("execute_binding_enabled") is not False:
        raise _EvidenceError("authorizing_artifact", "probe safety fields differ")
    return probe


def _verify_probes(
    paths: list[Path], lineage: Mapping[str, str]
) -> tuple[dict[str, object], list[dict[str, object]], list[dict[str, str]], list[dict[str, Any]]]:
    findings: list[dict[str, object]] = []
    refs: list[dict[str, str]] = []
    probes: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    seen_content: set[str] = set()
    cells: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for index, input_path in enumerate(paths):
        resolved, raw = _read_input(input_path, f"probe_receipt_paths[{index}]")
        path_key = os.path.normcase(str(resolved))
        if path_key in seen_paths:
            findings.append(_finding("duplicate_input_path", "failed"))
            continue
        seen_paths.add(path_key)
        try:
            probe = _validate_probe(_decode_canonical_json(raw, f"probe receipt {resolved}"))
        except _EvidenceError as error:
            findings.append(_finding(error.code, error.disposition))
            continue
        digest = str(probe["content_sha256"])
        if digest in seen_content:
            findings.append(_finding("duplicate_input_content", "failed", [digest]))
            continue
        seen_content.add(digest)
        provider_id = str(probe["provider"]["provider_id"])
        kind = str(probe["probe_kind"])
        cells.setdefault((provider_id, kind), []).append(probe)
        probes.append(probe)
        refs.append(_source_ref(resolved, probe, "probe_receipt"))
        for field in ("run_id", "stage", "operation_id", "model_request_id"):
            if probe.get(field) != lineage.get(field):
                findings.append(_finding("cross_attempt_probe", "failed", [digest]))
        body_state = probe["body_completion_observation"]["state"]
        if body_state == "unknown":
            findings.append(_finding("probe_body_unknown", "indeterminate", [digest]))
        elif body_state != "not_complete":
            findings.append(_finding("probe_body_relabelled_complete", "failed", [digest]))
        stable = probe["stable_zero_observation"]
        if (
            _integer(stable.get("stable_zero_observations"), "probe stable-zero count") < 3
            or stable.get("job_members")
            or stable.get("active_listeners")
            or stable.get("active_leases")
        ):
            findings.append(_finding("probe_residue", "failed", [digest]))
    missing = [list(cell) for cell in _REQUIRED_MATRIX if len(cells.get(cell, [])) == 0]
    duplicate = [list(cell) for cell, values in sorted(cells.items()) if len(values) > 1]
    extra = [list(cell) for cell in sorted(cells) if cell not in _REQUIRED_MATRIX]
    if missing:
        findings.append(_finding("missing_probe_cells", "failed"))
    if duplicate:
        findings.append(_finding("duplicate_probe_cells", "failed"))
    if extra:
        findings.append(_finding("extra_probe_cells", "failed"))
    verified = [list(cell) for cell in _REQUIRED_MATRIX if len(cells.get(cell, [])) == 1 and cells[cell][0]["body_completion_observation"]["state"] == "not_complete"]
    summary = {
        "required_matrix": [list(cell) for cell in _REQUIRED_MATRIX],
        "verified_matrix": verified,
        "missing_matrix": missing,
    }
    refs.sort(key=lambda item: (item["content_sha256"], item["canonical_path"]))
    probes.sort(key=lambda item: (str(item["provider"]["provider_id"]), str(item["probe_kind"]), str(item["content_sha256"])))
    return summary, findings, refs, probes


def _file_ref_matches(value: object, expected_path: Path) -> bool:
    if not isinstance(value, Mapping) or set(value) != _FILE_REF_FIELDS:
        return False
    try:
        resolved = expected_path.resolve(strict=True)
        return value.get("canonical_path") == str(resolved) and value.get("file_sha256") == _sha_bytes(resolved.read_bytes())
    except OSError:
        return False


def _actual_mode_findings(
    *,
    roles: Mapping[str, list[tuple[Path, dict[str, Any]]]],
    samples: list[dict[str, Any]],
    probes: list[dict[str, Any]],
    authorities: Mapping[str, str],
) -> list[dict[str, object]]:
    findings: list[dict[str, object]] = []
    if os.name != "nt":
        findings.append(_finding("actual_mode_requires_windows", "failed"))
    module_path = Path(__file__).resolve()
    executable = shutil.which("nvidia-smi.exe")
    executable_path = Path(executable).resolve() if executable else None
    for sample in samples:
        observer = sample["observer_identity"]
        if (
            observer.get("kind") != "production_direct"
            or observer.get("platform") != "windows"
            or not _file_ref_matches(observer.get("collector_module_ref"), module_path)
            or executable_path is None
            or not _file_ref_matches(observer.get("nvidia_smi_ref"), executable_path)
        ):
            findings.append(_finding("actual_gpu_observer_not_production", "failed", [str(sample["content_sha256"])]))
    if not samples:
        findings.append(_finding("actual_gpu_observer_missing", "failed"))
    if any(value != "production_workflow_service" for value in authorities.values()):
        findings.append(_finding("actual_parent_authority_not_production", "failed"))
    root = _one(roles, "task4_window_root")
    expected_helper = Path(__file__).resolve().parents[3] / "scripts" / "portfolio_hybrid_v1_1_test_window_v2.py"
    if root is None or root.get("helper_path") != str(expected_helper.resolve()):
        findings.append(_finding("actual_task4_helper_not_canonical", "failed"))
    elif roles.get("task4_window_root"):
        root_path = roles["task4_window_root"][0][0]
        identity_digest = _sha_bytes(
            canonical_json_bytes(
                {
                    "contract_version": "portfolio_hybrid_benchmark_v2_window_owner_journal_v1",
                    "operation_id": root.get("operation_id"),
                    "screenshot_sha256": root.get("screenshot_sha256"),
                    "journal_path": str(root_path),
                }
            )
        )
        expected_identity = {
            "owner_id": f"window-owner-{identity_digest}",
            "scope_name": f"Local\\AgentGuiHybrid-vista-{identity_digest}",
            "window_class": f"AgentGuiBenchmarkV2_{identity_digest[:32]}",
            "window_title": f"AgentGui Benchmark v2 {identity_digest[:24]}",
            "shutdown_event_name": f"Local\\AgentGuiBenchmarkV2-window-shutdown-{identity_digest}",
            "shutdown_nonce": _sha_bytes(f"shutdown\0{identity_digest}".encode("utf-8")),
        }
        anchor_digest = _sha_bytes(str(root_path).casefold().encode("utf-8"))
        expected_anchor = root_path.with_name(f".{root_path.name}.{anchor_digest}.root-anchor.json")
        if any(root.get(field) != value for field, value in expected_identity.items()) or root.get(
            "root_anchor_path"
        ) != str(expected_anchor):
            findings.append(_finding("actual_task4_authority_not_canonical", "failed", [str(root["content_sha256"])]))
    runner_path = Path(__file__).resolve().with_name("benchmark_v2_actual.py")
    for probe in probes:
        observer = probe["observer_identity"]
        if observer.get("kind") != "production_runner" or not _file_ref_matches(observer.get("module_ref"), runner_path):
            findings.append(_finding("actual_probe_observer_not_production", "failed", [str(probe["content_sha256"])]))
    if len(probes) != 6:
        findings.append(_finding("actual_probe_evidence_missing", "failed"))
    return findings


def _deduplicate_findings(findings: list[dict[str, object]]) -> list[dict[str, object]]:
    merged: dict[tuple[str, str], set[str]] = {}
    for finding in findings:
        key = (str(finding["code"]), str(finding["disposition"]))
        merged.setdefault(key, set()).update(str(item) for item in finding.get("evidence_refs", []))
    return [
        {"code": code, "disposition": disposition, "evidence_refs": sorted(refs)}
        for (code, disposition), refs in sorted(merged.items())
    ]


def _empty_result(*, actual_mode: bool, findings: list[dict[str, object]]) -> dict[str, object]:
    status = "failed" if any(item["disposition"] == "failed" for item in findings) else "indeterminate"
    return seal_immutable(
        {
            "contract_version": _RESULT_CONTRACT,
            "status": status,
            "actual_mode": actual_mode,
            "release_eligible": False,
            "source_refs": {"owner_journals": [], "sampler_transcripts": [], "probe_receipts": []},
            "owner_summary": {"intervals": [], "max_concurrent_by_kind": {"window": 0, "outer_worker": 0, "qwen_runtime": 0}, "overlap_status": "indeterminate"},
            "gpu_summary": {
                "device_uuid": None,
                "baseline_ref": None,
                "in_flight_refs": [],
                "post_ref": None,
                "owned_process_vram": [],
                "owned_peak_mib": None,
                "owned_post_mib": None,
                "external_fingerprint_baseline": [],
                "external_fingerprint_post": [],
                "external_fingerprint_status": "indeterminate",
                "device_used_baseline_mib": None,
                "device_used_post_mib": None,
                "device_residual_baseline_mib": None,
                "device_residual_post_mib": None,
                "device_residual_status": "indeterminate",
            },
            "probe_summary": {"required_matrix": [list(cell) for cell in _REQUIRED_MATRIX], "verified_matrix": [], "missing_matrix": [list(cell) for cell in _REQUIRED_MATRIX]},
            "cleanup_summary": {"window": "unknown", "binding": "unknown", "worker": "unknown", "provider": "unknown", "stable_zero": "unknown"},
            "findings": _deduplicate_findings(findings),
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )


def verify_lifecycle_from_raw(
    *,
    owner_journal_paths: list[Path],
    sampler_transcript_paths: list[Path],
    probe_receipt_paths: list[Path],
    actual_mode: bool,
) -> dict[str, object]:
    """从显式原始路径重算生命周期、显存与 probe 覆盖。"""
    if not isinstance(actual_mode, bool):
        raise TypeError("actual_mode must be bool")
    if not all(isinstance(paths, list) for paths in (owner_journal_paths, sampler_transcript_paths, probe_receipt_paths)):
        raise TypeError("lifecycle inputs must be lists of explicit Path values")
    try:
        roles, owner_refs, parent_findings = _load_parent_graph(owner_journal_paths)
        owners, cleanup_summary, lineage_findings, lineage, authorities = _derive_parent_facts(roles)
        samples, sample_refs = _load_samples(sampler_transcript_paths)
        gpu_summary, owner_summary, gpu_findings = _account_gpu(samples, owners)
        probe_summary, probe_findings, probe_refs, probes = _verify_probes(probe_receipt_paths, lineage)
        findings = [*parent_findings, *lineage_findings, *gpu_findings, *probe_findings]
        if actual_mode:
            findings.extend(
                _actual_mode_findings(
                    roles=roles,
                    samples=samples,
                    probes=probes,
                    authorities=authorities,
                )
            )
        findings = _deduplicate_findings(findings)
        if any(item["disposition"] == "failed" for item in findings):
            status = "failed"
        elif any(item["disposition"] == "indeterminate" for item in findings):
            status = "indeterminate"
        else:
            status = "verified_actual" if actual_mode else "verified_fixture"
        result = {
            "contract_version": _RESULT_CONTRACT,
            "status": status,
            "actual_mode": actual_mode,
            "release_eligible": status == "verified_actual",
            "source_refs": {
                "owner_journals": owner_refs,
                "sampler_transcripts": sample_refs,
                "probe_receipts": probe_refs,
            },
            "owner_summary": owner_summary,
            "gpu_summary": gpu_summary,
            "probe_summary": probe_summary,
            "cleanup_summary": cleanup_summary,
            "findings": findings,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
        return seal_immutable(result)
    except _EvidenceError as error:
        return _empty_result(
            actual_mode=actual_mode,
            findings=[_finding(error.code, error.disposition, list(error.refs))],
        )
    except (OSError, ValueError, TypeError) as error:
        return _empty_result(
            actual_mode=actual_mode,
            findings=[_finding("raw_verification_error", "failed")],
        )


__all__ = ["collect_raw_gpu_sample", "verify_lifecycle_from_raw"]
