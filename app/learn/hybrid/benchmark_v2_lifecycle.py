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
import struct
import subprocess
import sys
from threading import RLock
from typing import Any, Mapping, Sequence

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
_ATTEMPT_EVENT_CONTRACT = "benchmark_v2_attempt_resource_event_v1"
_ATTEMPT_CLEANUP_CONTRACT = "benchmark_v2_attempt_cleanup_receipt_v1"
_ATTEMPT_PHASES = {
    "prepared": 0,
    "request_in_flight": 1,
    "body_complete": 2,
    "terminal": 3,
}
_ATTEMPT_EVENT_PHASE = {
    "attempt_prepared": "prepared",
    "window_owned": "prepared",
    "service_start_intent": "prepared",
    "service_started": "prepared",
    "service_recovered": "prepared",
    "provider_request_in_flight": "request_in_flight",
    "probe_triggered": "request_in_flight",
    "provider_body_complete": "body_complete",
    "attempt_cleanup_prepared": "body_complete",
    "attempt_terminal": "terminal",
}
_ATTEMPT_EVENT_FIELDS = {
    "contract_version",
    "sequence",
    "attempt_ref",
    "phase",
    "event_kind",
    "provider_id",
    "probe_kind",
    "resource_ref",
    "predecessor_content_sha256",
    "artifact_is_authorization",
    "execute_binding_enabled",
    "content_sha256",
}
_ATTEMPT_JOURNAL_LOCK = RLock()
_S13_SAFETY = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
    "display_only": True,
}
_S13_ZERO_COUNTS = {
    "service_operations": 0,
    "windows": 0,
    "providers": 0,
    "listeners": 0,
    "leases": 0,
}

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
_TASK4_EVENT_PAYLOAD_FIELDS = {
    "launch_intent": {"journal_root_sha256"},
    "job_created": {"scope_name"},
    "process_created": {"process_identity"},
    "hwnd_published": {"publication"},
    "ready": {"binding", "pre_raw_identity_sha256", "post_raw_identity_sha256"},
    "finalization_intent": {"reason"},
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

_B1_SOURCE_FIELDS = {
    "contract_version", "provider_corpus_file_ref", "provider_case_ref",
    "projection_contract_version", "projection_rules_content_sha256",
    "window_binding_ref", "capture_ref", "handler_payload_sha256",
    "predecessor_content_sha256", "content_sha256",
}
_B1_RESERVATION_FIELDS = {
    "contract_version", "authority_kind", "run_id", "stage", "operation_id",
    "workflow_revision", "task_kind", "payload_sha256", "handler_payload_source",
    "handler_payload_source_ref", "worker_id", "model_request_id", "execution_nonce",
    "supervision_inputs_ref", "reservation_state", "abort_observation_ref",
    "predecessor_content_sha256", "content_sha256",
}
_B1_OPERATION_ANCHOR_FIELDS = {
    "contract_version", "run_id", "stage", "operation_id", "workflow_revision",
    "task_kind", "worker_id", "execution_nonce", "payload_sha256", "reservation_ref",
    "supervision_inputs_ref", "handler_payload_source_ref", "window_binding_ref",
    "capture_ref", "expected_supervision_ref", "anchor_identity_sha256",
    "predecessor_content_sha256", "content_sha256",
}
_B1_EXPECTED_SUPERVISION_FIELDS = {
    "contract_version", "authority_kind", "operation_anchor_ref", "reservation_ref",
    "supervision_inputs_ref", "handler_payload_source_ref", "run_id", "stage",
    "operation_id", "workflow_revision", "worker_id", "task_kind", "payload_sha256",
    "execution_nonce", "scope_name", "startup_gate_timeout_ms",
    "artifact_is_authorization", "execute_binding_enabled", "content_sha256",
}
_B1_ACTUAL_SUPERVISION_FIELDS = _B1_EXPECTED_SUPERVISION_FIELDS | {
    "expected_supervision_ref", "supervisor_process_identity",
}
_B1_BEACON_FIELDS = {
    "contract_version", "worker_id", "operation_anchor_ref", "process_identity",
    "predecessor_content_sha256", "content_sha256",
}
_B1_LAUNCH_ANCHOR_FIELDS = {
    "contract_version", "authority_kind", "anchored_reservation_ref",
    "launching_reservation_ref", "operation_anchor_ref", "actual_supervision_ref",
    "supervisor_process_identity", "beacon_ref", "process_identity",
    "assignment_observation_ref", "assignment_predecessor_content_sha256",
    "predecessor_content_sha256", "content_sha256",
}
_B1_HANDLE_FIELDS = {
    "contract_version", "handle_kind", "handle_identity", "call_result", "call_error",
    "observed_at", "worker_id", "predecessor_content_sha256", "content_sha256",
}
_B1_EXIT_FIELDS = {
    "contract_version", "worker_id", "process_identity", "exitcode", "join_result",
    "join_error", "observed_at", "predecessor_content_sha256", "content_sha256",
}
_B1_STABLE_ZERO_FIELDS = {
    "contract_version", "worker_id", "scope_name", "samples",
    "predecessor_content_sha256", "content_sha256",
}
_B1_FINALIZATION_FIELDS = {
    "contract_version", "supervision_ref", "assignment_proven_ref", "run_id", "stage",
    "operation_id", "worker_id", "supervisor_process_identity", "process_identity",
    "scope_name", "gate_state", "exit_observation_ref", "stable_zero_observation_ref",
    "exact_owned_handles", "exact_handle_observation_refs",
    "owner_job_handle_close_planned", "cleanup_receipt_id",
    "predecessor_content_sha256", "content_sha256",
}
_B1_ABSENCE_FIELDS = {
    "contract_version", "observation_kind", "outcome", "worker_id", "scope_name",
    "process_identity", "predecessor_content_sha256", "content_sha256",
}
_B1_NOT_LAUNCHED_FIELDS = {
    "contract_version", "outcome", "authority_kind", "reservation_ref", "run_id",
    "stage", "operation_id", "worker_id", "owner_absence_observation_ref",
    "process_event_job_beacon_absence_observation_ref", "result_absence_observation_ref",
    "provider_absence_observation_ref", "predecessor_content_sha256",
    "artifact_is_authorization", "execute_binding_enabled", "content_sha256",
}
_B1_PRE_ANCHOR_ABSENCE_FIELDS = {
    "contract_version", "observation_kind", "outcome", "reservation_ref", "run_id",
    "stage", "operation_id", "worker_id", "checks", "predecessor_content_sha256",
    "content_sha256",
}

_B2_INTENT_FIELDS = {"contract_version", "model_request_id", "runtime_owner_ref", "content_sha256"}
_B2_ACQUISITION_OWNER_FIELDS = {
    "contract_version", "model_request_id", "runtime_owner_ref", "acquisition_intent_ref",
    "owner_state", "content_sha256",
}
_B2_ACQUISITION_OBSERVATION_FIELDS = {
    "contract_version", "model_request_id", "acquisition_owner_ref",
    "acquisition_intent_ref", "runtime_owner_ref", "prepared_materialization_ledger_ref",
    "materialization_ledger_ref", "materialization_state", "materialization_revision",
    "content_sha256",
}
_B2_LEASE_BINDING_FIELDS = {
    "contract_version", "model_request_id", "acquisition_intent_ref", "runtime_owner_ref",
    "lease_ref", "profile_ref", "server_process_identity", "socket_ref", "job_scope_ref",
    "lease_state_ref", "content_sha256",
}
_B2_LEASE_FIELDS = {
    "contract_version", "lease_id", "owner_request_id", "profile_id", "incarnation_id",
    "server_base_url", "server_model_id", "profile_sha256", "server_process_identity",
    "content_sha256",
}
_B2_SOCKET_FIELDS = {"host", "port", "content_sha256"}
_B2_SCOPE_ACQUISITION_FIELDS = {
    "contract_version", "scope_name", "member_pids", "server_process_identity", "content_sha256",
}
_B2_RELEASE_OBSERVATION_FIELDS = {
    "contract_version", "model_request_id", "lease_ref", "finalization_token",
    "release_reason", "release_result_ref", "content_sha256",
}
_B2_TERMINATION_FIELDS = {
    "contract_version", "model_request_id", "lease_ref", "finalization_token",
    "release_result_ref", "termination_observation", "content_sha256",
}
_B2_TOMBSTONE_FIELDS = {
    "contract_version", "status", "owner_request_id", "profile_id", "lease_id",
    "incarnation_id", "server_termination", "release_result", "finalization_token",
    "content_sha256",
}
_B2_SCOPE_CLEANUP_FIELDS = {
    "contract_version", "scope_name", "authority", "scope_absent_after_owner_close",
    "cleanup_status", "observed_member_pids_before", "observed_member_identities_before",
    "member_pids_after", "member_identities_after", "active_listeners_after",
    "pid_file_after", "stable_zero_observations", "samples", "content_sha256",
}
_B2_NO_ACTIVE_FIELDS = {
    "contract_version", "model_request_id", "active_lease_count", "content_sha256",
}
_B2_LEASE_STATE_FIELDS = {
    "contract_version", "profile_id", "profile", "incarnation", "server_started_by_runtime",
    "process_scope_name", "process_scope_acquisition", "revision", "finalization", "leases",
    "content_sha256",
}
_B2_ABORT_TOMBSTONE_FIELDS = {
    "contract_version", "model_request_id", "acquisition_intent_ref", "runtime_owner_ref",
    "materialization_ledger_ref", "reason", "historical_process_identity",
    "historical_socket_ref", "historical_job_scope_ref", "content_sha256",
}
_B2_ABORT_FIELDS = {
    "contract_version", "model_request_id", "acquisition_intent_ref", "runtime_owner_ref",
    "materialization_ledger_ref", "owner_tombstone_ref", "reason", "owner_state",
    "content_sha256",
}
_B2_PRODUCTION_ABORT_TOMBSTONE_FIELDS = {
    "contract_version", "status", "model_request_id", "provider", "lineage",
    "process_scope_name", "profile_sha256", "listener_port", "pid_file",
    "scope_cleanup_evidence", "content_sha256",
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
_PROBE_PROFILE_FIELDS = {
    "contract_version", "provider_id", "profile_id", "attempt_id", "content_sha256",
}
_PROBE_REQUEST_FIELDS = {
    "contract_version", "provider_id", "run_id", "stage", "operation_id",
    "model_request_id", "attempt_id", "state", "observed_at_utc", "content_sha256",
}
_PROBE_BODY_PARENT_FIELDS = _PROBE_REQUEST_FIELDS
_PROBE_SOCKET_PARENT_FIELDS = {
    "contract_version", "provider_id", "attempt_id", "incarnation_id", "host", "port",
    "process_identity", "content_sha256",
}
_PROBE_JOB_PARENT_FIELDS = {
    "contract_version", "provider_id", "attempt_id", "incarnation_id", "scope_name",
    "member_identities", "content_sha256",
}
_PROBE_LEASE_PARENT_FIELDS = {
    "contract_version", "provider_id", "profile_ref", "attempt_id", "lease_id",
    "incarnation_id", "process_identity", "socket_ref", "job_scope_ref",
    "acquired_at_utc", "content_sha256",
}
_PROBE_TERMINATION_PARENT_FIELDS = {
    "contract_version", "provider_id", "attempt_id", "incarnation_id",
    "process_identity", "outcome", "terminated_at_utc", "predecessor_content_sha256",
    "content_sha256",
}
_PROBE_ZERO_SAMPLE_FIELDS = {
    "contract_version", "provider_id", "attempt_id", "incarnation_id", "sequence",
    "observed_at_utc", "job_members", "active_listeners", "active_leases",
    "predecessor_content_sha256", "content_sha256",
}
_PROBE_ZERO_BUNDLE_FIELDS = {
    "contract_version", "provider_id", "attempt_id", "incarnation_id", "sample_refs",
    "process_absent", "listener_absent", "lease_absent", "predecessor_content_sha256",
    "content_sha256",
}


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
    if not isinstance(value, Mapping) or set(value) not in (
        {"content_sha256"},
        {"id", "content_sha256"},
        {"contract_version", "content_sha256"},
        {"capture_id", "content_sha256"},
    ):
        raise _EvidenceError("invalid_content_ref", f"{name} must be a closed content ref")
    result = deepcopy(dict(value))
    _sha(result.get("content_sha256"), f"{name}.content_sha256")
    if "id" in result:
        _text(result["id"], f"{name}.id")
    if "contract_version" in result:
        _text(result["contract_version"], f"{name}.contract_version")
    if "capture_id" in result:
        _text(result["capture_id"], f"{name}.capture_id")
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
            cleanup_error: BaseException | None = None
            try:
                try:
                    running = process.poll() is None
                except BaseException as error:
                    running = False
                    cleanup_error = error
                if running:
                    try:
                        process.kill()
                    except BaseException as error:
                        cleanup_error = cleanup_error or error
                    try:
                        process.communicate()
                    except BaseException as error:
                        cleanup_error = cleanup_error or error
            finally:
                try:
                    process.wait()
                except BaseException as error:
                    cleanup_error = cleanup_error or error
                finally:
                    for pipe in (process.stdout, process.stderr):
                        if pipe is not None:
                            try:
                                pipe.close()
                            except BaseException as error:
                                cleanup_error = cleanup_error or error
            if cleanup_error is not None and sys.exc_info()[0] is None:
                raise cleanup_error


def _observe_process_inventory() -> tuple[dict[int, int], list[int], str]:
    try:
        pids = sorted({pid for pid in psutil.pids() if isinstance(pid, int) and not isinstance(pid, bool) and pid > 0})
    except (psutil.Error, OSError, ValueError):
        return {}, [], "unavailable"
    identities: dict[int, int] = {}
    unobserved: list[int] = []
    for pid in pids:
        try:
            created_ns = int(round(psutil.Process(pid).create_time() * 1_000_000_000))
            if created_ns <= 0:
                raise ValueError("invalid create time")
            identities[pid] = created_ns
        except (psutil.Error, OSError, ValueError):
            unobserved.append(pid)
    return identities, unobserved, "partial" if unobserved else "complete"


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
        create_time_ns = int(round(psutil.Process(os.getpid()).create_time() * 1_000_000_000))
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


def _observer_replay_compatible(recorded: object, current: object) -> bool:
    try:
        persisted = _validate_observer(recorded)
        live = _validate_observer(current)
    except (TypeError, ValueError, _EvidenceError):
        return False
    return (
        persisted.get("kind") == live.get("kind") == "production_direct"
        and persisted.get("platform") == live.get("platform") == "windows"
        and persisted.get("collector_module_ref") == live.get("collector_module_ref")
        and persisted.get("nvidia_smi_ref") == live.get("nvidia_smi_ref")
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
        try:
            resolved, raw = _read_input(path.resolve(), "transcript_path")
            existing = _decode_canonical_json(raw, "existing raw GPU transcript")
            validated = _validate_sample(existing)
        except (OSError, ValueError, TypeError) as error:
            raise FileExistsError(
                "raw GPU transcript is not an identical current production observation for the requested device"
            ) from error
        if (
            validated["device_uuid"] != requested_uuid
            or validated["collection_mode"] != "production_direct"
            or not _observer_replay_compatible(
                validated["observer_identity"], _production_gpu_observer_identity()
            )
        ):
            raise FileExistsError(
                "raw GPU transcript is not an identical current production observation for the requested device"
            )
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
    identities, unobserved, inventory_status = _observe_process_inventory()
    if parse_error is None:
        missing_compute_pids = sorted(set(pids) - set(identities) - set(unobserved))
        if missing_compute_pids:
            unobserved = sorted(set(unobserved) | set(missing_compute_pids))
            inventory_status = "partial"
    snapshot = seal_immutable(
        {
            "contract_version": _PROCESS_SNAPSHOT_CONTRACT,
            "observed_at_utc": _utc_now(),
            "status": inventory_status,
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


def _task4_bmp_identity(raw: bytes) -> dict[str, object]:
    if len(raw) < 54 or raw[:2] != b"BM":
        raise _EvidenceError("task4_capture_invalid", "Task 4 screenshot is not an exact BMP")
    try:
        file_size = struct.unpack_from("<I", raw, 2)[0]
        pixel_offset = struct.unpack_from("<I", raw, 10)[0]
        header_size, width, signed_height, planes, bit_count, compression, size_image = struct.unpack_from(
            "<IiiHHII", raw, 14
        )
    except struct.error as error:
        raise _EvidenceError("task4_capture_invalid", "Task 4 BMP header is truncated") from error
    if (
        file_size != len(raw)
        or header_size != 40
        or width <= 0
        or signed_height == 0
        or planes != 1
        or bit_count not in {24, 32}
        or compression != 0
        or pixel_offset < 54
    ):
        raise _EvidenceError("task4_capture_invalid", "Task 4 BMP dimensions differ")
    height = abs(signed_height)
    stride = ((width * bit_count + 31) // 32) * 4
    pixel_bytes = stride * height
    if size_image not in {0, pixel_bytes} or pixel_offset + pixel_bytes != len(raw):
        raise _EvidenceError("task4_capture_invalid", "Task 4 BMP pixel layout differs")
    return {
        "image_dimensions": {"width": width, "height": height},
        "bitmap_pixel_sha256": _sha_bytes(raw[pixel_offset : pixel_offset + pixel_bytes]),
    }


def _validate_task4_root_shape(root_path: Path, raw_root: Mapping[str, object]) -> tuple[Path, bytes]:
    root = _sealed(raw_root, _TASK4_ROOT_FIELDS, "Task 4 root")
    if root.get("contract_version") != "portfolio_hybrid_benchmark_v2_window_owner_journal_v1":
        raise _EvidenceError("task4_root_invalid", "Task 4 root contract differs")
    operation_id = root.get("operation_id")
    if not isinstance(operation_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", operation_id) is None:
        raise _EvidenceError("task4_root_invalid", "Task 4 operation identity differs")
    screenshot_sha = _sha(root.get("screenshot_sha256"), "Task 4 screenshot SHA")
    identity_digest = _sha_bytes(
        canonical_json_bytes(
            {
                "contract_version": "portfolio_hybrid_benchmark_v2_window_owner_journal_v1",
                "operation_id": operation_id,
                "screenshot_sha256": screenshot_sha,
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
    if any(root.get(field) != expected for field, expected in expected_identity.items()):
        raise _EvidenceError("task4_root_invalid", "Task 4 derived identity differs")
    root_anchor_digest = _sha_bytes(str(root_path).casefold().encode("utf-8"))
    expected_paths = {
        "journal_path": str(root_path),
        "events_path": str(root_path.with_name(root_path.name + ".events.jsonl")),
        "publication_path": str(root_path.with_name(root_path.name + ".publication.json")),
        "publication_permit_path": str(root_path.with_name(root_path.name + ".publication-permit.json")),
        "helper_path": str(
            (Path(__file__).resolve().parents[3] / "scripts" / "portfolio_hybrid_v1_1_test_window_v2.py").resolve()
        ),
        "root_anchor_path": str(
            root_path.with_name(f".{root_path.name}.{root_anchor_digest}.root-anchor.json")
        ),
    }
    if any(root.get(field) != expected for field, expected in expected_paths.items()):
        raise _EvidenceError("task4_path_mismatch", "Task 4 derived sibling path differs")
    capture_path, capture_raw = _read_input(Path(str(root.get("screenshot_path"))), "Task 4 screenshot")
    bitmap = _task4_bmp_identity(capture_raw)
    if (
        _sha_bytes(capture_raw) != screenshot_sha
        or root.get("image_dimensions") != bitmap["image_dimensions"]
        or root.get("bitmap_pixel_sha256") != bitmap["bitmap_pixel_sha256"]
    ):
        raise _EvidenceError("task4_capture_digest_mismatch", "Task 4 screenshot identity differs")
    if (
        root.get("artifact_is_authorization") is not False
        or root.get("execute_binding_enabled") is not False
        or root.get("display_only") is not True
    ):
        raise _EvidenceError("task4_safety_mismatch", "Task 4 root safety fields differ")
    return capture_path, capture_raw


def _validate_task4_events(root_path: Path, root: Mapping[str, object]) -> tuple[list[dict[str, Any]], dict[str, object]]:
    related_refs: list[dict[str, str]] = []
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
        expected_payload_fields = _TASK4_EVENT_PAYLOAD_FIELDS.get(str(event_type))
        if event_type == "cleanup_verified":
            cleanup = _sealed(payload, _TASK4_CLEANUP_FIELDS, "Task 4 cleanup")
            if cleanup.get("contract_version") != "portfolio_hybrid_benchmark_v2_window_cleanup_v1":
                raise _EvidenceError("task4_cleanup_invalid", "Task 4 cleanup contract differs")
        elif expected_payload_fields is None or set(payload) != expected_payload_fields:
            raise _EvidenceError("task4_event_payload_invalid", "Task 4 event payload fields differ")
        if event_type == "launch_intent" and payload.get("journal_root_sha256") != root.get("content_sha256"):
            raise _EvidenceError("task4_event_payload_invalid", "Task 4 launch root ref differs")
        if event_type == "job_created" and payload.get("scope_name") != root.get("scope_name"):
            raise _EvidenceError("task4_event_payload_invalid", "Task 4 Job scope differs")
        if event_type == "process_created":
            _process_identity(payload["process_identity"], "Task 4 process identity")
        if event_type == "ready":
            pre_raw = _sha(payload.get("pre_raw_identity_sha256"), "Task 4 pre-ready identity")
            post_raw = _sha(payload.get("post_raw_identity_sha256"), "Task 4 post-ready identity")
            if pre_raw != post_raw:
                raise _EvidenceError("task4_event_payload_invalid", "Task 4 raw HWND identity changed")
        if event_type == "finalization_intent":
            reason = payload.get("reason")
            if not isinstance(reason, str) or not reason or len(reason) > 128:
                raise _EvidenceError("task4_event_payload_invalid", "Task 4 finalization reason differs")
        events.append(event)
        previous = str(event["content_sha256"])
        previous_type = str(event_type)
    if previous_type != "cleanup_verified":
        raise _EvidenceError("task4_cleanup_missing", "Task 4 terminal cleanup event is absent")
    if [event["event_type"] for event in events] != [
        "launch_intent",
        "job_created",
        "process_created",
        "hwnd_published",
        "ready",
        "finalization_intent",
        "cleanup_verified",
    ]:
        raise _EvidenceError("task4_event_chain_invalid", "Task 4 conclusion requires the full owner event chain")
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
        or cleanup.get("reason") != finalizations[0]["payload"].get("reason")
        or cleanup.get("shutdown_event_name") != root.get("shutdown_event_name")
        or cleanup.get("process_identity") != expected_identity
        or cleanup.get("cleanup_subject_kind") != "ready_window"
        or cleanup.get("process_event_sha256") != process_events[0]["content_sha256"]
        or cleanup.get("finalization_intent_sha256") != finalizations[0]["content_sha256"]
    ):
        raise _EvidenceError("task4_cleanup_lineage_mismatch", "Task 4 cleanup lineage differs")
    if ready_events:
        if len(ready_events) != 1 or len(publication_events) != 1:
            raise _EvidenceError("task4_lineage_ambiguous", "Task 4 ready/publication lineage is ambiguous")
        publication = publication_events[0]["payload"].get("publication")
        binding = ready_events[0]["payload"].get("binding")
        publication_fields = {
            "contract_version", "owner_id", "screenshot_sha256", "raw_file_sha256",
            "bitmap_pixel_sha256", "shutdown_nonce_sha256", "process_identity", "hwnd",
            "hwnds", "window_class", "window_title", "window_rect", "client_rect", "dpi",
            "image_dimensions", "artifact_is_authorization", "execute_binding_enabled",
            "journal_root_sha256", "expected_predecessor_sha256", "permit_content_sha256",
            "content_sha256",
        }
        binding_fields = {
            "contract_version", "owner_id", "operation_id", "screenshot_path",
            "screenshot_sha256", "bitmap_pixel_sha256", "scope_name", "process_identity",
            "job_member_pids", "hwnd", "window_class", "window_title", "window_rect",
            "client_rect", "dpi", "image_dimensions", "journal_path", "journal_root_sha256",
            "journal_root", "artifact_is_authorization", "execute_binding_enabled",
            "display_only", "uia_root_identity", "content_sha256",
        }
        permit_path, permit_raw = _read_input(
            Path(str(root.get("publication_permit_path"))), "Task 4 publication permit"
        )
        publication_path, publication_raw = _read_input(
            Path(str(root.get("publication_path"))), "Task 4 publication"
        )
        permit = _sealed(
            _decode_canonical_json(permit_raw, "Task 4 publication permit"),
            {"contract_version", "owner_id", "journal_root_sha256", "expected_predecessor_sha256", "content_sha256"},
            "Task 4 publication permit",
        )
        persisted_publication = _sealed(
            _decode_canonical_json(publication_raw, "Task 4 publication"),
            publication_fields,
            "Task 4 publication",
        )
        related_refs.extend(
            [
                {"semantic_role": "task4_publication_permit", "canonical_path": str(permit_path), "content_sha256": str(permit["content_sha256"])},
                {"semantic_role": "task4_publication", "canonical_path": str(publication_path), "content_sha256": str(persisted_publication["content_sha256"])},
            ]
        )
        if (
            not isinstance(publication, Mapping)
            or not isinstance(binding, Mapping)
            or set(publication) != publication_fields
            or set(binding) != binding_fields
            or publication.get("content_sha256") != content_sha256(dict(publication))
            or binding.get("content_sha256") != content_sha256(dict(binding))
            or persisted_publication != publication
            or permit.get("contract_version")
            != "portfolio_hybrid_benchmark_v2_hwnd_publication_permit_v1"
            or permit.get("owner_id") != root.get("owner_id")
            or permit.get("journal_root_sha256") != root.get("content_sha256")
            or permit.get("expected_predecessor_sha256")
            != process_events[0].get("content_sha256")
            or publication.get("contract_version")
            != "portfolio_hybrid_benchmark_v2_hwnd_publication_v1"
            or publication.get("owner_id") != root.get("owner_id")
            or publication.get("screenshot_sha256") != root.get("screenshot_sha256")
            or publication.get("raw_file_sha256") != root.get("screenshot_sha256")
            or publication.get("bitmap_pixel_sha256") != root.get("bitmap_pixel_sha256")
            or publication.get("shutdown_nonce_sha256")
            != _sha_bytes(str(root.get("shutdown_nonce")).encode("utf-8"))
            or publication.get("process_identity") != expected_identity
            or not isinstance(publication.get("hwnd"), int)
            or isinstance(publication.get("hwnd"), bool)
            or int(publication.get("hwnd")) <= 0
            or publication.get("hwnds") != [publication.get("hwnd")]
            or publication.get("window_class") != root.get("window_class")
            or publication.get("window_title") != root.get("window_title")
            or publication.get("image_dimensions") != root.get("image_dimensions")
            or publication.get("journal_root_sha256") != root.get("content_sha256")
            or publication.get("expected_predecessor_sha256")
            != process_events[0].get("content_sha256")
            or publication.get("permit_content_sha256") != permit.get("content_sha256")
            or publication.get("artifact_is_authorization") is not False
            or publication.get("execute_binding_enabled") is not False
            or binding.get("contract_version")
            != "portfolio_hybrid_benchmark_v2_window_binding_v1"
            or binding.get("owner_id") != root.get("owner_id")
            or binding.get("operation_id") != root.get("operation_id")
            or binding.get("screenshot_path") != root.get("screenshot_path")
            or binding.get("screenshot_sha256") != root.get("screenshot_sha256")
            or binding.get("bitmap_pixel_sha256") != root.get("bitmap_pixel_sha256")
            or binding.get("scope_name") != root.get("scope_name")
            or binding.get("window_class") != root.get("window_class")
            or binding.get("window_title") != root.get("window_title")
            or binding.get("window_rect") != publication.get("window_rect")
            or binding.get("client_rect") != publication.get("client_rect")
            or binding.get("dpi") != publication.get("dpi")
            or binding.get("image_dimensions") != root.get("image_dimensions")
            or binding.get("journal_path") != root.get("journal_path")
            or binding.get("journal_root") != root
            or binding.get("journal_root_sha256") != root.get("content_sha256")
            or binding.get("job_member_pids") != [expected_identity["pid"]]
            or binding.get("artifact_is_authorization") is not False
            or binding.get("execute_binding_enabled") is not False
            or binding.get("display_only") is not True
            or cleanup.get("ready_event_sha256") != ready_events[0]["content_sha256"]
            or cleanup.get("publication_content_sha256") != publication.get("content_sha256")
            or cleanup.get("exact_hwnd") != publication.get("hwnd")
            or binding.get("process_identity") != expected_identity
            or binding.get("hwnd") != publication.get("hwnd")
        ):
            raise _EvidenceError("task4_cleanup_lineage_mismatch", "Task 4 ready cleanup lineage differs")
        uia = _sealed(
            binding.get("uia_root_identity"),
            {
                "provider", "provider_version", "window_handle", "window_process_id",
                "window_title", "root_control", "content_sha256",
            },
            "Task 4 UIA root identity",
        )
        if (
            uia.get("window_handle") != binding.get("hwnd")
            or uia.get("window_process_id") != expected_identity["pid"]
            or uia.get("window_title") != root.get("window_title")
        ):
            raise _EvidenceError("task4_uia_identity_mismatch", "Task 4 UIA identity differs")
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
    ) or (
        cleanup.get("shutdown_event_signaled") is not True
        or cleanup.get("shutdown_event_error_code") is not None
        or cleanup.get("outer_owner_python_finally_observed") is not True
    ) or _integer(cleanup.get("stable_zero_observations"), "Task 4 stable-zero") < 3:
        raise _EvidenceError("task4_cleanup_residue", "Task 4 cleanup retains process/window/handle residue")
    return events, {
        "path": str(event_path),
        "anchor_path": str(anchor_path),
        "raw_sha256": _sha_bytes(event_raw),
        "related_refs": related_refs,
    }


def _validate_parent_document(value: dict[str, Any]) -> str:
    contract = value.get("contract_version")
    if contract is None and set(value) == _B2_SOCKET_FIELDS:
        _sealed(value, _B2_SOCKET_FIELDS, "b2_socket")
        return "b2_socket"
    schemas: dict[str, tuple[str, set[str]]] = {
        "portfolio_hybrid_benchmark_v2_window_owner_journal_v1": ("task4_window_root", _TASK4_ROOT_FIELDS),
        "benchmark_v2_worker_window_binding_authority_v1": ("task5_binding_authority", _TASK5_AUTHORITY_FIELDS),
        "portfolio_hybrid_benchmark_v2_worker_window_binding_normal_clear_v1": ("task5_normal_clear", _TASK5_CLEAR_FIELDS),
        "benchmark_worker_scope_assignment_v1": ("b1_assignment", _B1_ASSIGNMENT_FIELDS),
        "benchmark_worker_owner_journal_v1": ("b1_owner", _B1_OWNER_FIELDS),
        "benchmark_worker_cleanup_receipt_v1": ("b1_cleanup", _B1_CLEANUP_FIELDS),
        "benchmark_v2_incumbent_handler_payload_source_v1": ("b1_source", _B1_SOURCE_FIELDS),
        "benchmark_worker_identity_reservation_v1": ("b1_reservation", _B1_RESERVATION_FIELDS),
        "benchmark_worker_operation_anchor_v1": ("b1_operation_anchor", _B1_OPERATION_ANCHOR_FIELDS),
        "benchmark_worker_expected_supervision_v1": ("b1_expected_supervision", _B1_EXPECTED_SUPERVISION_FIELDS),
        "benchmark_worker_supervision_v1": ("b1_actual_supervision", _B1_ACTUAL_SUPERVISION_FIELDS),
        "benchmark_worker_identity_beacon_v1": ("b1_beacon", _B1_BEACON_FIELDS),
        "benchmark_worker_launch_identity_anchor_v1": ("b1_launch_anchor", _B1_LAUNCH_ANCHOR_FIELDS),
        "benchmark_worker_handle_close_observation_v1": ("b1_handle_close", _B1_HANDLE_FIELDS),
        "benchmark_worker_exit_join_observation_v1": ("b1_exit_join", _B1_EXIT_FIELDS),
        "benchmark_worker_stable_zero_observation_v1": ("b1_stable_zero", _B1_STABLE_ZERO_FIELDS),
        "benchmark_worker_cleanup_finalization_intent_v1": ("b1_finalization_intent", _B1_FINALIZATION_FIELDS),
        "benchmark_worker_absence_observation_v1": ("b1_absence", _B1_ABSENCE_FIELDS),
        "benchmark_worker_not_launched_observation_v1": ("b1_not_launched", _B1_NOT_LAUNCHED_FIELDS),
        "benchmark_worker_pre_anchor_absence_observation_v1": ("b1_pre_anchor_absence", _B1_PRE_ANCHOR_ABSENCE_FIELDS),
        "benchmark_provider_runtime_owner_v1": ("b2_runtime_owner", _B2_RUNTIME_FIELDS),
        "qwen_model_request_materialization_ledger_v1": ("b2_materialization_ledger", _B2_LEDGER_FIELDS),
        "qwen_model_request_acquisition_intent_v1": ("b2_acquisition_intent", _B2_INTENT_FIELDS),
        "benchmark_provider_acquisition_owner_v1": ("b2_acquisition_owner", _B2_ACQUISITION_OWNER_FIELDS),
        "qwen_model_request_acquisition_observation_v1": ("b2_acquisition_observation", _B2_ACQUISITION_OBSERVATION_FIELDS),
        "qwen_model_request_acquisition_lease_binding_v1": ("b2_lease_binding", _B2_LEASE_BINDING_FIELDS),
        "qwen_model_server_lease_state_v3": ("b2_lease_state", _B2_LEASE_STATE_FIELDS),
        "qwen_model_server_lease_v2": ("b2_lease", _B2_LEASE_FIELDS),
        "hybrid_process_scope_acquisition_v1": ("b2_scope_acquisition", _B2_SCOPE_ACQUISITION_FIELDS),
        "qwen_model_request_exact_release_observation_v1": ("b2_release_observation", _B2_RELEASE_OBSERVATION_FIELDS),
        "qwen_model_request_exact_termination_observation_v1": ("b2_termination", _B2_TERMINATION_FIELDS),
        "qwen_model_request_owner_receipt_v1": ("b2_owner_tombstone", _B2_TOMBSTONE_FIELDS),
        "hybrid_windows_process_scope_v1": ("b2_scope_cleanup", _B2_SCOPE_CLEANUP_FIELDS),
        "qwen_model_request_no_active_lease_observation_v1": ("b2_no_active_lease", _B2_NO_ACTIVE_FIELDS),
        "benchmark_provider_aborted_acquisition_tombstone_v1": ("b2_abort_tombstone", _B2_ABORT_TOMBSTONE_FIELDS),
        "benchmark_provider_acquisition_abort_v1": ("b2_acquisition_abort", _B2_ABORT_FIELDS),
        "hybrid_qwen_aborted_acquisition_tombstone_v1": (
            "b2_production_abort_tombstone",
            _B2_PRODUCTION_ABORT_TOMBSTONE_FIELDS,
        ),
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
    if contract == "qwen_model_request_materialization_ledger_v1" and value.get("revision") == 0:
        role = "b2_prepared_materialization_ledger"
    _sealed(value, fields, role)
    for safety_field in ("artifact_is_authorization", "execute_binding_enabled"):
        if safety_field in value and value[safety_field] is not False:
            raise _EvidenceError("authorizing_artifact", f"{role} safety field differs")
    return role


def _index_sealed_values(
    value: object,
    *,
    source: str,
    digest_index: dict[str, tuple[str, object]],
) -> None:
    if isinstance(value, Mapping):
        digest = value.get("content_sha256")
        if isinstance(digest, str) and _SHA_RE.fullmatch(digest) and digest == content_sha256(dict(value)):
            existing = digest_index.get(digest)
            if existing is not None and canonical_json_bytes(existing[1]) != canonical_json_bytes(dict(value)):
                raise _EvidenceError("digest_parent_collision", "one digest resolves to conflicting raw parents")
            digest_index[digest] = (source, deepcopy(dict(value)))
        for nested in value.values():
            _index_sealed_values(nested, source=source, digest_index=digest_index)
    elif isinstance(value, list):
        for nested in value:
            _index_sealed_values(nested, source=source, digest_index=digest_index)


def _graph_ref_digests(role: str, value: Mapping[str, object]) -> list[str]:
    ref_fields: dict[str, tuple[str, ...]] = {
        "task5_binding_authority": (
            "window_binding_ref", "capture_ref", "owner_binding_ref", "owner_journal_ref",
            "owner_ready_event_ref",
        ),
        "b1_source": ("window_binding_ref", "capture_ref"),
        "b1_reservation": ("handler_payload_source_ref", "abort_observation_ref"),
        "b1_operation_anchor": (
            "reservation_ref", "handler_payload_source_ref", "window_binding_ref", "capture_ref",
            "expected_supervision_ref",
        ),
        "b1_expected_supervision": (
            "operation_anchor_ref", "reservation_ref", "handler_payload_source_ref",
        ),
        "b1_actual_supervision": (
            "expected_supervision_ref", "operation_anchor_ref", "reservation_ref",
            "handler_payload_source_ref",
        ),
        "b1_beacon": ("operation_anchor_ref",),
        "b1_launch_anchor": (
            "anchored_reservation_ref", "launching_reservation_ref", "operation_anchor_ref",
            "actual_supervision_ref", "beacon_ref", "assignment_observation_ref",
        ),
        "b1_owner": (
            "operation_anchor_ref", "reservation_ref", "supervision_ref", "beacon_ref",
            "assignment_observation_ref", "exit_observation_ref", "stable_zero_observation_ref",
            "cleanup_finalization_intent", "cleanup_receipt_ref",
        ),
        "b1_cleanup": (
            "operation_anchor_ref", "reservation_ref", "supervision_ref", "assignment_proven_ref",
            "finalization_intent_ref", "job_absence_observation_ref",
            "worker_absence_observation_ref", "supervisor_absence_observation_ref",
            "reservation_abort_ref",
        ),
        "b1_finalization_intent": (
            "supervision_ref", "assignment_proven_ref", "exit_observation_ref",
            "stable_zero_observation_ref",
        ),
        "b1_not_launched": (
            "reservation_ref", "owner_absence_observation_ref",
            "process_event_job_beacon_absence_observation_ref", "result_absence_observation_ref",
            "provider_absence_observation_ref",
        ),
        "b1_pre_anchor_absence": ("reservation_ref",),
        "b2_acquisition_intent": ("runtime_owner_ref",),
        "b2_acquisition_owner": ("runtime_owner_ref", "acquisition_intent_ref"),
        "b2_materialization_ledger": ("acquisition_intent_ref", "runtime_owner_ref"),
        "b2_prepared_materialization_ledger": ("acquisition_intent_ref", "runtime_owner_ref"),
        "b2_acquisition_observation": (
            "acquisition_owner_ref", "acquisition_intent_ref", "runtime_owner_ref",
            "prepared_materialization_ledger_ref", "materialization_ledger_ref",
        ),
        "b2_lease_binding": (
            "acquisition_intent_ref", "runtime_owner_ref", "lease_ref", "profile_ref",
            "socket_ref", "job_scope_ref", "lease_state_ref",
        ),
        "b2_release_observation": ("lease_ref", "release_result_ref"),
        "b2_termination": ("lease_ref", "release_result_ref"),
        "b2_cleanup": (
            "acquisition_intent_ref", "runtime_owner_ref", "lease_ref", "profile_ref",
            "socket_ref", "job_scope_ref", "lease_state_ref", "owner_tombstone_ref",
            "termination_observation_ref", "scope_stable_zero_ref", "listener_stable_zero_ref",
            "no_active_lease_observation_ref", "no_owned_runtime_observation_ref",
        ),
        "b2_provider_journal": (
            "reservation_ref", "runtime_owner_ref", "acquisition_owner_ref",
            "acquisition_intent_ref", "prepared_acquisition_observation_ref",
            "prepared_materialization_ledger_ref", "acquisition_observation_ref",
            "materialization_ledger_ref",
        ),
        "b2_provider_cleanup_journal": (
            "reservation_ref", "runtime_owner_ref", "acquisition_owner_ref",
            "acquisition_intent_ref", "cleanup_receipt_ref",
        ),
        "b2_abort_tombstone": (
            "acquisition_intent_ref", "runtime_owner_ref", "materialization_ledger_ref",
            "historical_socket_ref", "historical_job_scope_ref",
        ),
        "b2_acquisition_abort": (
            "acquisition_intent_ref", "runtime_owner_ref", "materialization_ledger_ref",
            "owner_tombstone_ref",
        ),
    }
    digests: list[str] = []
    for field in ref_fields.get(role, ()):
        raw_ref = value.get(field)
        if raw_ref is None:
            continue
        ref = _content_ref(raw_ref, f"{role}.{field}")
        assert ref is not None
        digests.append(str(ref["content_sha256"]))
    if role == "b1_source" and isinstance(value.get("provider_corpus_file_ref"), Mapping):
        corpus_parent = _content_ref(
            value["provider_corpus_file_ref"].get("source_parent_ref"),
            "b1_source.provider_corpus_file_ref.source_parent_ref",
        )
        assert corpus_parent is not None
        digests.append(str(corpus_parent["content_sha256"]))
    for container_field in ("exact_handle_observation_refs",):
        container = value.get(container_field)
        if isinstance(container, Mapping):
            for name, raw_ref in sorted(container.items()):
                ref = _content_ref(raw_ref, f"{role}.{container_field}.{name}")
                assert ref is not None
                digests.append(str(ref["content_sha256"]))
    predecessor = value.get("predecessor_content_sha256")
    if predecessor is not None:
        digests.append(_sha(predecessor, f"{role}.predecessor_content_sha256"))
    return digests


def _load_parent_graph(paths: list[Path]) -> tuple[
    dict[str, list[tuple[Path, dict[str, Any]]]],
    list[dict[str, str]],
    list[dict[str, object]],
    dict[str, tuple[str, object]],
]:
    roles: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    refs: list[dict[str, str]] = []
    findings: list[dict[str, object]] = []
    resolved_seen: set[str] = set()
    content_seen: set[str] = set()
    digest_index: dict[str, tuple[str, object]] = {}
    for index, input_path in enumerate(sorted(paths, key=lambda item: os.path.normcase(str(item)))):
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
        _index_sealed_values(value, source=str(resolved), digest_index=digest_index)
    task4_roots = roles.get("task4_window_root", [])
    if len(task4_roots) != 1:
        raise _EvidenceError("task4_root_cardinality", "exactly one Task 4 root is required")
    task4_path, task4_root = task4_roots[0]
    capture_path, capture_raw = _validate_task4_root_shape(task4_path, task4_root)
    task4_events, event_ref = _validate_task4_events(task4_path, task4_root)
    capture_digest = _sha_bytes(capture_raw)
    digest_index[capture_digest] = (str(capture_path), {"raw_file_sha256": capture_digest})
    roles["task4_events"] = [(Path(event_ref["path"]), {"events": task4_events, **event_ref})]
    for event in task4_events:
        _index_sealed_values(event, source=str(event_ref["path"]), digest_index=digest_index)
    refs.append(
        {
            "semantic_role": "task4_events",
            "canonical_path": str(event_ref["path"]),
            "content_sha256": str(event_ref["raw_sha256"]),
        }
    )
    refs.extend(deepcopy(event_ref.get("related_refs", [])))
    for role, required_count in (
        ("task5_binding_authority", 1),
        ("b1_cleanup", 1),
        ("b2_runtime_owner", 1),
        ("b2_materialization_ledger", 1),
    ):
        if len(roles.get(role, [])) != required_count:
            raise _EvidenceError("missing_owner_parent", f"{role} requires exactly {required_count} raw parent")
    b1_cleanup = roles.get("b1_cleanup", [])
    if len(b1_cleanup) == 1 and b1_cleanup[0][1].get("outcome") == "verified_exact_worker_exited" and not roles.get("b1_owner"):
        raise _EvidenceError("missing_owner_parent", "launched B1 cleanup requires an owner journal")
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
    serialized = roles["task5_binding_authority"][0][1].get("serialized_window_binding")
    if isinstance(serialized, Mapping):
        payload_sha = _sha(serialized.get("payload_sha256"), "Task 5 binding payload SHA")
        digest_index[payload_sha] = (str(roles["task5_binding_authority"][0][0]), deepcopy(dict(serialized)))
    for _path, anchor in roles.get("b1_operation_anchor", []):
        identity_sha = _sha(anchor.get("anchor_identity_sha256"), "B1 anchor identity SHA")
        digest_index[identity_sha] = (str(_path), deepcopy(anchor))
    for _path, state in roles.get("b2_lease_state", []):
        for embedded in (state.get("profile"), state.get("incarnation", {}).get("server_socket"), state.get("process_scope_acquisition")):
            if isinstance(embedded, Mapping):
                sealed = seal_immutable(dict(embedded))
                digest_index[str(sealed["content_sha256"])] = (str(_path), sealed)
        raw_leases = state.get("leases")
        if isinstance(raw_leases, list):
            for raw_lease in raw_leases:
                if isinstance(raw_lease, Mapping):
                    lease = {key: deepcopy(raw_lease[key]) for key in raw_lease if key != "lifecycle_state"}
                    sealed = seal_immutable(lease)
                    digest_index[str(sealed["content_sha256"])] = (str(_path), sealed)
    for _path, tombstone in roles.get("b2_owner_tombstone", []):
        release_result = tombstone.get("release_result")
        if isinstance(release_result, Mapping):
            sealed = seal_immutable(dict(release_result))
            digest_index[str(sealed["content_sha256"])] = (str(_path), sealed)
            for field in ("hybrid_process_scope_acquisition", "hybrid_process_scope_cleanup"):
                embedded = release_result.get(field)
                if isinstance(embedded, Mapping):
                    embedded_sealed = seal_immutable(dict(embedded))
                    digest_index[str(embedded_sealed["content_sha256"])] = (str(_path), embedded_sealed)
    for _path, tombstone in roles.get("b2_production_abort_tombstone", []):
        embedded = tombstone.get("scope_cleanup_evidence")
        if isinstance(embedded, Mapping):
            sealed = seal_immutable(dict(embedded))
            digest_index[str(sealed["content_sha256"])] = (str(_path), sealed)
    unresolved: list[str] = []
    for role, candidates in sorted(roles.items()):
        if role == "task4_events":
            continue
        candidates.sort(
            key=lambda item: (
                str(item[1].get("run_id", "")), str(item[1].get("stage", "")),
                str(item[1].get("operation_id", "")), str(item[1].get("worker_id", "")),
                str(item[1].get("model_request_id", "")), str(item[1].get("content_sha256", "")),
                str(item[0]),
            )
        )
        for _path, value in candidates:
            for digest in _graph_ref_digests(role, value):
                if digest not in digest_index:
                    unresolved.append(digest)
    if unresolved:
        raise _EvidenceError(
            "dangling_parent_ref",
            "owner graph contains content refs that do not resolve to supplied raw parents",
            refs=tuple(sorted(set(unresolved))),
        )
    return roles, sorted(refs, key=lambda item: (item["semantic_role"], item["content_sha256"], item["canonical_path"])), findings, digest_index


def _one(roles: Mapping[str, list[tuple[Path, dict[str, Any]]]], role: str) -> dict[str, Any] | None:
    values = roles.get(role, [])
    return values[0][1] if len(values) == 1 else None


def _same_ref(left: object, right: object) -> bool:
    return isinstance(left, Mapping) and isinstance(right, Mapping) and left.get("content_sha256") == right.get("content_sha256")


def _resolved_parent(
    digest_index: Mapping[str, tuple[str, object]], value: object, name: str
) -> dict[str, Any]:
    ref = _content_ref(value, name)
    assert ref is not None
    resolved = digest_index.get(str(ref["content_sha256"]))
    if resolved is None or not isinstance(resolved[1], Mapping):
        raise _EvidenceError("dangling_parent_ref", f"{name} does not resolve")
    return deepcopy(dict(resolved[1]))


def _validate_task5_binding_raw(
    *,
    authority: Mapping[str, object],
    serialized: Mapping[str, object],
    root: Mapping[str, object],
    window_identity: Mapping[str, int],
) -> None:
    membership = _sealed(
        serialized.get("job_membership_ref"),
        {"contract_version", "job_name", "process_identity", "member_pids", "content_sha256"},
        "Task 5 Job membership",
    )
    if (
        serialized.get("contract_version")
        != "portfolio_hybrid_benchmark_v2_worker_window_binding_v1"
        or serialized.get("capture_sha256") != root.get("screenshot_sha256")
        or serialized.get("screenshot_sha256") != root.get("screenshot_sha256")
        or serialized.get("capture_image_path") != root.get("screenshot_path")
        or serialized.get("expected_uia_root_hwnd") != serialized.get("exact_hwnd")
        or serialized.get("expected_uia_owner_pid") != window_identity.get("pid")
        or membership.get("contract_version")
        != "portfolio_hybrid_benchmark_v2_worker_job_membership_ref_v1"
        or membership.get("job_name") != serialized.get("job_name")
        or membership.get("process_identity") != window_identity
        or membership.get("member_pids") != [window_identity.get("pid")]
        or authority.get("predecessor_content_sha256") is not None
    ):
        raise _EvidenceError("task5_binding_constraint_mismatch", "Task 5 exact binding constraints differ")
    shapes = (
        (serialized.get("client_rect"), {"left", "top", "right", "bottom", "width", "height"}),
        (serialized.get("window_rect"), {"left", "top", "right", "bottom"}),
        (serialized.get("image_dimensions"), {"width", "height"}),
    )
    for value, fields in shapes:
        if not isinstance(value, Mapping) or set(value) != fields or any(
            isinstance(item, bool) or not isinstance(item, int) for item in value.values()
        ):
            raise _EvidenceError("task5_binding_constraint_mismatch", "Task 5 rectangle constraints differ")


def _validate_b1_source_anchor_raw(
    *,
    roles: Mapping[str, list[tuple[Path, dict[str, Any]]]],
    digest_index: Mapping[str, tuple[str, object]],
    reserved: Mapping[str, object],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    sources = [value for _path, value in roles.get("b1_source", [])]
    anchors = [value for _path, value in roles.get("b1_operation_anchor", [])]
    expected_documents = [value for _path, value in roles.get("b1_expected_supervision", [])]
    if len(sources) != 1 or len(anchors) != 1 or len(expected_documents) != 1:
        raise _EvidenceError("b1_anchor_parent_missing", "B1 source/anchor/expected supervision cardinality differs")
    source = sources[0]
    anchor = anchors[0]
    expected = expected_documents[0]
    corpus = _sealed(
        source.get("provider_corpus_file_ref"),
        {
            "contract_version", "relative_path", "file_sha256", "source_parent_ref",
            "content_sha256",
        },
        "B1 provider corpus ref",
    )
    case_ref = _closed(source.get("provider_case_ref"), {"case_id", "case_content_sha256"}, "B1 case ref")
    corpus_parent = _resolved_parent(digest_index, corpus.get("source_parent_ref"), "B1 corpus source parent")
    source_ref = {
        "contract_version": "benchmark_v2_incumbent_handler_payload_source_ref_v1",
        "content_sha256": source.get("content_sha256"),
    }
    for field in (
        "run_id", "stage", "operation_id", "workflow_revision", "task_kind", "worker_id",
        "execution_nonce", "payload_sha256", "supervision_inputs_ref",
    ):
        if anchor.get(field) != reserved.get(field):
            raise _EvidenceError("b1_operation_anchor_invalid", f"B1 operation anchor {field} differs")
    identity = {
        "contract_version": "benchmark_worker_operation_anchor_v1",
        "run_id": reserved.get("run_id"),
        "stage": reserved.get("stage"),
        "operation_id": reserved.get("operation_id"),
        "workflow_revision": reserved.get("workflow_revision"),
        "task_kind": reserved.get("task_kind"),
        "worker_id": reserved.get("worker_id"),
        "execution_nonce": reserved.get("execution_nonce"),
        "payload_sha256": reserved.get("payload_sha256"),
        "reservation_ref": {"content_sha256": reserved.get("content_sha256")},
        "supervision_inputs_ref": deepcopy(reserved.get("supervision_inputs_ref")),
        "handler_payload_source_ref": source_ref,
        "window_binding_ref": deepcopy(source.get("window_binding_ref")),
        "capture_ref": deepcopy(source.get("capture_ref")),
    }
    anchor_identity = content_sha256(identity)
    try:
        from app.learn.hybrid.windows_process_scope import benchmark_worker_scope_name_v1

        expected_scope = benchmark_worker_scope_name_v1(
            authority_kind=str(reserved.get("authority_kind")),
            run_id=str(reserved.get("run_id")),
            stage=str(reserved.get("stage")),
            operation_id=str(reserved.get("operation_id")),
            worker_id=str(reserved.get("worker_id")),
            payload_sha256=str(reserved.get("payload_sha256")),
            execution_nonce=str(reserved.get("execution_nonce")),
        )
    except (TypeError, ValueError) as error:
        raise _EvidenceError("b1_scope_identity_invalid", "B1 scope identity differs") from error
    expected_exact = seal_immutable(
        {
            "contract_version": "benchmark_worker_expected_supervision_v1",
            "authority_kind": reserved.get("authority_kind"),
            "operation_anchor_ref": {"content_sha256": anchor_identity},
            "reservation_ref": {"content_sha256": reserved.get("content_sha256")},
            "supervision_inputs_ref": deepcopy(reserved.get("supervision_inputs_ref")),
            "handler_payload_source_ref": source_ref,
            "run_id": reserved.get("run_id"),
            "stage": reserved.get("stage"),
            "operation_id": reserved.get("operation_id"),
            "workflow_revision": reserved.get("workflow_revision"),
            "worker_id": reserved.get("worker_id"),
            "task_kind": reserved.get("task_kind"),
            "payload_sha256": reserved.get("payload_sha256"),
            "execution_nonce": reserved.get("execution_nonce"),
            "scope_name": expected_scope,
            "startup_gate_timeout_ms": 15_000,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    if (
        corpus.get("contract_version") != "benchmark_v2_provider_corpus_file_ref_v1"
        or corpus.get("relative_path") != "provider-corpus.v2.json"
        or corpus_parent.get("contract_version")
        != "portfolio_hybrid_benchmark_v2_window_owner_journal_v1"
        or source.get("predecessor_content_sha256") != corpus.get("content_sha256")
        or source.get("projection_contract_version")
        != "benchmark_v2_observe_screen_payload_projection_v1"
        or not _text(case_ref.get("case_id"), "B1 case id")
        or not _sha(case_ref.get("case_content_sha256"), "B1 case digest")
        or not _sha(corpus.get("file_sha256"), "B1 corpus digest")
        or not _sha(source.get("projection_rules_content_sha256"), "B1 projection digest")
        or source.get("handler_payload_sha256") != reserved.get("payload_sha256")
        or reserved.get("handler_payload_source") != source
        or reserved.get("handler_payload_source_ref") != source_ref
        or reserved.get("predecessor_content_sha256") != source.get("content_sha256")
        or reserved.get("reservation_state") != "reserved"
        or reserved.get("abort_observation_ref") is not None
        or anchor.get("reservation_ref") != identity["reservation_ref"]
        or anchor.get("handler_payload_source_ref") != source_ref
        or anchor.get("window_binding_ref") != source.get("window_binding_ref")
        or anchor.get("capture_ref") != source.get("capture_ref")
        or anchor.get("anchor_identity_sha256") != anchor_identity
        or anchor.get("expected_supervision_ref")
        != {"content_sha256": expected_exact["content_sha256"]}
        or anchor.get("predecessor_content_sha256") != reserved.get("content_sha256")
        or expected != expected_exact
    ):
        raise _EvidenceError("b1_operation_anchor_invalid", "B1 source/anchor/supervision bytes differ")
    return source, anchor, expected


def _validate_b1_launched_raw(
    *,
    roles: Mapping[str, list[tuple[Path, dict[str, Any]]]],
    digest_index: Mapping[str, tuple[str, object]],
    primary_owner: Mapping[str, object],
    cleanup: Mapping[str, object],
    assignment: Mapping[str, object],
) -> None:
    expected_policy = {
        "kill_on_job_close": True,
        "breakaway_ok": False,
        "silent_breakaway_ok": False,
        "owner_handle_authority": "registry_parent",
    }
    identity = _process_identity(assignment.get("process_identity"), "B1 assignment process")
    if (
        assignment.get("job_policy") != expected_policy
        or assignment.get("temporary_process_handle_close")
        != {"handle_kind": "temporary_process", "status": "closed"}
        or assignment.get("temporary_job_handle_close")
        != {"handle_kind": "temporary_job", "status": "closed"}
        or assignment.get("observed_member_identities") != [identity]
    ):
        raise _EvidenceError("b1_assignment_constraint_mismatch", "B1 assignment exact constraints differ")
    reservations = [value for _path, value in roles.get("b1_reservation", [])]
    by_state = {str(value.get("reservation_state")): value for value in reservations}
    if set(by_state) != {"reserved", "anchored", "launching", "launched"} or len(reservations) != 4:
        raise _EvidenceError("b1_reservation_chain_invalid", "B1 launched reservation states differ")
    _source, operation_anchor, expected = _validate_b1_source_anchor_raw(
        roles=roles,
        digest_index=digest_index,
        reserved=by_state["reserved"],
    )
    previous = by_state["reserved"]
    for state in ("anchored", "launching", "launched"):
        current = by_state[state]
        transitioned = {key: deepcopy(value) for key, value in previous.items() if key != "content_sha256"}
        transitioned["reservation_state"] = state
        transitioned["predecessor_content_sha256"] = previous["content_sha256"]
        if current != seal_immutable(transitioned):
            raise _EvidenceError("b1_reservation_chain_invalid", "B1 reservation predecessor differs")
        previous = current
    if cleanup.get("reservation_ref", {}).get("content_sha256") != by_state["launched"]["content_sha256"]:
        raise _EvidenceError("b1_cleanup_lineage_mismatch", "B1 cleanup reservation differs")
    resolved_anchor = _resolved_parent(digest_index, cleanup.get("operation_anchor_ref"), "B1 operation anchor")
    actual = _resolved_parent(digest_index, cleanup.get("supervision_ref"), "B1 actual supervision")
    resolved_expected = _resolved_parent(
        digest_index, operation_anchor.get("expected_supervision_ref"), "B1 expected supervision"
    )
    if resolved_anchor != operation_anchor or resolved_expected != expected:
        raise _EvidenceError("b1_operation_anchor_invalid", "B1 anchor aliases do not resolve exactly")
    launch = _resolved_parent(digest_index, primary_owner.get("predecessor_content_sha256") and {"content_sha256": primary_owner["predecessor_content_sha256"]}, "B1 owner predecessor")
    if launch.get("contract_version") != "benchmark_worker_owner_journal_v1":
        raise _EvidenceError("b1_owner_predecessor_invalid", "B1 terminal owner does not follow the sealed owner state")
    launch_anchor_matches = [
        value
        for _path, value in roles.get("b1_launch_anchor", [])
        if value.get("process_identity") == identity
        and value.get("actual_supervision_ref", {}).get("content_sha256") == actual.get("content_sha256")
    ]
    if len(launch_anchor_matches) != 1:
        raise _EvidenceError("b1_launch_anchor_invalid", "B1 launch anchor is missing or ambiguous")
    launch_anchor = launch_anchor_matches[0]
    if (
        operation_anchor.get("contract_version") != "benchmark_worker_operation_anchor_v1"
        or expected.get("contract_version") != "benchmark_worker_expected_supervision_v1"
        or actual.get("contract_version") != "benchmark_worker_supervision_v1"
        or actual.get("expected_supervision_ref")
        != {"content_sha256": expected.get("content_sha256")}
        or actual.get("operation_anchor_ref") != cleanup.get("operation_anchor_ref")
        or actual.get("reservation_ref") != operation_anchor.get("reservation_ref")
        or actual.get("authority_kind") != by_state["reserved"].get("authority_kind")
        or actual.get("reservation_ref")
        != {"content_sha256": by_state["reserved"].get("content_sha256")}
        or actual.get("supervision_inputs_ref") != by_state["reserved"].get("supervision_inputs_ref")
        or actual.get("handler_payload_source_ref") != by_state["reserved"].get("handler_payload_source_ref")
        or any(actual.get(field) != by_state["reserved"].get(field) for field in (
            "run_id", "stage", "operation_id", "workflow_revision", "worker_id", "task_kind",
            "payload_sha256", "execution_nonce",
        ))
        or actual.get("scope_name") != expected.get("scope_name")
        or actual.get("startup_gate_timeout_ms") != 15_000
        or actual.get("artifact_is_authorization") is not False
        or actual.get("execute_binding_enabled") is not False
        or assignment.get("predecessor_content_sha256") != actual.get("content_sha256")
        or launch_anchor.get("assignment_observation_ref", {}).get("content_sha256")
        != assignment.get("content_sha256")
        or launch_anchor.get("process_identity") != identity
        or launch_anchor.get("predecessor_content_sha256") != assignment.get("content_sha256")
        or launch_anchor.get("anchored_reservation_ref")
        != {"content_sha256": by_state["anchored"].get("content_sha256")}
        or launch_anchor.get("launching_reservation_ref")
        != {"content_sha256": by_state["launching"].get("content_sha256")}
        or launch_anchor.get("operation_anchor_ref")
        != {"content_sha256": operation_anchor.get("anchor_identity_sha256")}
        or launch_anchor.get("beacon_ref") != primary_owner.get("beacon_ref")
        or launch_anchor.get("supervisor_process_identity")
        != actual.get("supervisor_process_identity")
        or launch_anchor.get("assignment_predecessor_content_sha256")
        != assignment.get("predecessor_content_sha256")
    ):
        raise _EvidenceError("b1_launch_anchor_invalid", "B1 launch identity joins differ")
    beacons = [value for _path, value in roles.get("b1_beacon", [])]
    if len(beacons) != 1:
        raise _EvidenceError("b1_beacon_invalid", "B1 beacon cardinality differs")
    beacon = beacons[0]
    if (
        primary_owner.get("beacon_ref") != {"content_sha256": beacon.get("content_sha256")}
        or beacon.get("worker_id") != primary_owner.get("worker_id")
        or beacon.get("operation_anchor_ref")
        != {"content_sha256": operation_anchor.get("anchor_identity_sha256")}
        or beacon.get("process_identity") != identity
        or beacon.get("predecessor_content_sha256") != actual.get("content_sha256")
    ):
        raise _EvidenceError("b1_beacon_invalid", "B1 beacon identity differs")
    if (
        launch.get("predecessor_content_sha256") != launch_anchor.get("content_sha256")
        or launch.get("phase") != "gate_released"
        or launch.get("gate_state") != "released"
        or launch.get("reservation_ref")
        != {"content_sha256": by_state["launched"].get("content_sha256")}
        or launch.get("supervision_ref") != {"content_sha256": actual.get("content_sha256")}
        or launch.get("operation_anchor_ref")
        != {"content_sha256": operation_anchor.get("anchor_identity_sha256")}
        or launch.get("process_identity") != identity
        or launch.get("assignment_observation_ref")
        != {"content_sha256": assignment.get("content_sha256")}
        or primary_owner.get("predecessor_content_sha256") != launch.get("content_sha256")
    ):
        raise _EvidenceError("b1_owner_predecessor_invalid", "B1 owner state lineage differs")
    intent = _resolved_parent(digest_index, cleanup.get("finalization_intent_ref"), "B1 finalization intent")
    exit_parent = _resolved_parent(digest_index, intent.get("exit_observation_ref"), "B1 exit observation")
    stable = _resolved_parent(digest_index, intent.get("stable_zero_observation_ref"), "B1 stable zero")
    cleanup_receipt_id = _sha_bytes(
        canonical_json_bytes({"worker_id": cleanup.get("worker_id"), "scope_name": assignment.get("scope_name")})
    )
    if (
        intent.get("contract_version") != "benchmark_worker_cleanup_finalization_intent_v1"
        or intent.get("supervision_ref") != cleanup.get("supervision_ref")
        or intent.get("assignment_proven_ref") != cleanup.get("assignment_proven_ref")
        or intent.get("process_identity") != identity
        or any(intent.get(field) != cleanup.get(field) for field in ("run_id", "stage", "operation_id", "worker_id"))
        or intent.get("supervisor_process_identity") != actual.get("supervisor_process_identity")
        or intent.get("scope_name") != assignment.get("scope_name")
        or intent.get("gate_state") != "released"
        or intent.get("exact_owned_handles")
        != {
            "worker_process": "closed_explicitly",
            "startup_event": "closed_explicitly",
            "beacon_file": "closed_explicitly",
            "owner_job": "open",
        }
        or not isinstance(intent.get("exact_handle_observation_refs"), Mapping)
        or set(intent["exact_handle_observation_refs"]) != {
            "worker_process", "startup_event", "beacon_file"
        }
        or intent.get("owner_job_handle_close_planned") is not True
        or intent.get("cleanup_receipt_id") != cleanup_receipt_id
        or intent.get("predecessor_content_sha256") != launch.get("content_sha256")
        or primary_owner.get("cleanup_finalization_intent")
        != {"content_sha256": intent.get("content_sha256")}
        or exit_parent.get("contract_version") != "benchmark_worker_exit_join_observation_v1"
        or exit_parent.get("process_identity") != identity
        or exit_parent.get("worker_id") != cleanup.get("worker_id")
        or exit_parent.get("join_result") != "joined"
        or exit_parent.get("join_error") is not None
        or exit_parent.get("predecessor_content_sha256") != launch.get("content_sha256")
        or stable.get("contract_version") != "benchmark_worker_stable_zero_observation_v1"
        or stable.get("worker_id") != cleanup.get("worker_id")
        or stable.get("scope_name") != assignment.get("scope_name")
        or stable.get("samples") != [[], [], []]
    ):
        raise _EvidenceError("b1_cleanup_residue", "B1 exit or stable-zero proof differs")
    terminal_body = {key: deepcopy(value) for key, value in launch.items() if key != "content_sha256"}
    terminal_body.update(
        {
            "phase": "cleanup_finalization_intent",
            "exit_observation_ref": {"content_sha256": exit_parent.get("content_sha256")},
            "stable_zero_observation_ref": {"content_sha256": stable.get("content_sha256")},
            "exact_handle_observation_refs": deepcopy(intent.get("exact_handle_observation_refs")),
            "cleanup_finalization_intent": {"content_sha256": intent.get("content_sha256")},
            "predecessor_content_sha256": launch.get("content_sha256"),
        }
    )
    if primary_owner != seal_immutable(terminal_body):
        raise _EvidenceError("b1_owner_predecessor_invalid", "B1 terminal owner state differs")
    raw_handle_refs = cleanup.get("exact_handle_observation_refs")
    if not isinstance(raw_handle_refs, Mapping) or set(raw_handle_refs) != {
        "worker_process", "startup_event", "beacon_file", "owner_job"
    }:
        raise _EvidenceError("b1_handle_close_invalid", "B1 exact handle set differs")
    handle_parents: dict[str, dict[str, Any]] = {}
    for kind, raw_ref in raw_handle_refs.items():
        parent = _resolved_parent(digest_index, raw_ref, f"B1 {kind} close")
        if (
            parent.get("contract_version") != "benchmark_worker_handle_close_observation_v1"
            or parent.get("handle_kind") != kind
            or parent.get("call_result") != "success"
            or parent.get("call_error") is not None
            or parent.get("worker_id") != cleanup.get("worker_id")
        ):
            raise _EvidenceError("b1_handle_close_invalid", "B1 exact handle close proof differs")
        handle_parents[str(kind)] = parent
    expected_handle_identities = {
        "worker_process": {"process_identity": identity},
        "startup_event": {
            "event_name": "Local\\AgentGuiBenchmarkWorkerGate-"
            + content_sha256({"scope_name": assignment.get("scope_name")})
        },
        "beacon_file": {"beacon_ref": {"content_sha256": beacon.get("content_sha256")}},
        "owner_job": {"scope_name": assignment.get("scope_name")},
    }
    if any(
        handle_parents[kind].get("handle_identity") != expected_identity
        for kind, expected_identity in expected_handle_identities.items()
    ):
        raise _EvidenceError("b1_handle_close_invalid", "B1 exact handle identities differ")
    if (
        intent.get("exact_handle_observation_refs")
        != {kind: raw_handle_refs[kind] for kind in ("worker_process", "startup_event", "beacon_file")}
        or handle_parents["worker_process"].get("predecessor_content_sha256")
        != exit_parent.get("content_sha256")
        or handle_parents["startup_event"].get("predecessor_content_sha256")
        != handle_parents["worker_process"].get("content_sha256")
        or handle_parents["beacon_file"].get("predecessor_content_sha256")
        != handle_parents["startup_event"].get("content_sha256")
        or stable.get("predecessor_content_sha256")
        != handle_parents["beacon_file"].get("content_sha256")
        or handle_parents["owner_job"].get("predecessor_content_sha256")
        != intent.get("content_sha256")
    ):
        raise _EvidenceError("b1_handle_close_invalid", "B1 exact handle predecessor chain differs")
    job_absence = _resolved_parent(digest_index, cleanup.get("job_absence_observation_ref"), "B1 Job absence")
    worker_absence = _resolved_parent(digest_index, cleanup.get("worker_absence_observation_ref"), "B1 worker absence")
    if (
        job_absence.get("observation_kind") != "job"
        or job_absence.get("outcome") != "absent"
        or job_absence.get("scope_name") != assignment.get("scope_name")
        or job_absence.get("process_identity") is not None
        or job_absence.get("predecessor_content_sha256")
        != handle_parents["owner_job"].get("content_sha256")
        or worker_absence.get("observation_kind") != "worker"
        or worker_absence.get("outcome") != "absent"
        or worker_absence.get("process_identity") != identity
        or worker_absence.get("predecessor_content_sha256") != job_absence.get("content_sha256")
        or cleanup.get("supervisor_absence_observation_ref") is not None
        or cleanup.get("reservation_abort_ref") is not None
        or cleanup.get("artifact_is_authorization") is not False
        or cleanup.get("execute_binding_enabled") is not False
    ):
        raise _EvidenceError("b1_absence_invalid", "B1 exact absence chain differs")
    _timestamp(exit_parent.get("observed_at"), "B1 exit time")


def _validate_b2_acquired_raw(
    *,
    roles: Mapping[str, list[tuple[Path, dict[str, Any]]]],
    digest_index: Mapping[str, tuple[str, object]],
    runtime_owner: Mapping[str, object],
    ledger: Mapping[str, object],
    cleanup: Mapping[str, object],
) -> None:
    intent, _acquisition_owner, prepared, _prepared_observation, _acquisition_observation = (
        _validate_b2_acquisition_chain(
            roles=roles,
            runtime_owner=runtime_owner,
            ledger=ledger,
        )
    )
    binding_candidates = [value for _path, value in roles.get("b2_lease_binding", [])]
    if len(binding_candidates) != 1:
        raise _EvidenceError("b2_lease_binding_invalid", "B2 lease binding cardinality differs")
    binding = binding_candidates[0]
    state = _resolved_parent(digest_index, binding.get("lease_state_ref"), "B2 lease state")
    lease = _resolved_parent(digest_index, cleanup.get("lease_ref"), "B2 exact lease")
    socket = _resolved_parent(digest_index, cleanup.get("socket_ref"), "B2 socket")
    scope = _resolved_parent(digest_index, cleanup.get("job_scope_ref"), "B2 Job scope")
    tombstone = _resolved_parent(digest_index, cleanup.get("owner_tombstone_ref"), "B2 owner tombstone")
    termination = _resolved_parent(digest_index, cleanup.get("termination_observation_ref"), "B2 termination")
    stable = _resolved_parent(digest_index, cleanup.get("scope_stable_zero_ref"), "B2 stable zero")
    listener_stable = _resolved_parent(digest_index, cleanup.get("listener_stable_zero_ref"), "B2 listener zero")
    no_active = _resolved_parent(digest_index, cleanup.get("no_active_lease_observation_ref"), "B2 no-active lease")
    release_result = tombstone.get("release_result")
    release_observations = [value for _path, value in roles.get("b2_release_observation", [])]
    profile = state.get("profile")
    incarnation = state.get("incarnation")
    state_leases = state.get("leases")
    if (
        intent.get("contract_version") != "qwen_model_request_acquisition_intent_v1"
        or intent.get("runtime_owner_ref", {}).get("content_sha256") != runtime_owner.get("content_sha256")
        or ledger.get("revision") != 1
        or ledger.get("transition") != "launch"
        or ledger.get("predecessor_content_sha256") != prepared.get("content_sha256")
        or binding.get("lease_ref") != cleanup.get("lease_ref")
        or binding.get("profile_ref") != cleanup.get("profile_ref")
        or binding.get("server_process_identity") != cleanup.get("server_process_identity")
        or binding.get("socket_ref") != cleanup.get("socket_ref")
        or binding.get("job_scope_ref") != cleanup.get("job_scope_ref")
        or binding.get("lease_state_ref") != cleanup.get("lease_state_ref")
        or state.get("contract_version") != "qwen_model_server_lease_state_v3"
        or state.get("finalization") is not None
        or not isinstance(profile, Mapping)
        or content_sha256(dict(profile)) != lease.get("profile_sha256")
        or cleanup.get("profile_ref") != {"content_sha256": content_sha256(dict(profile))}
        or not isinstance(incarnation, Mapping)
        or incarnation.get("incarnation_id") != lease.get("incarnation_id")
        or incarnation.get("server_process_identity") != lease.get("server_process_identity")
        or incarnation.get("server_socket") != {key: value for key, value in socket.items() if key != "content_sha256"}
        or not isinstance(state_leases, list)
        or len(state_leases) != 1
        or state_leases[0] != {**{key: value for key, value in lease.items() if key != "content_sha256"}, "lifecycle_state": "not_started"}
        or lease.get("owner_request_id") != cleanup.get("model_request_id")
        or lease.get("server_process_identity") != cleanup.get("server_process_identity")
        or socket.get("host") not in {"127.0.0.1", "localhost", "::1"}
        or isinstance(socket.get("port"), bool)
        or not isinstance(socket.get("port"), int)
        or socket.get("port") <= 0
        or scope.get("server_process_identity") != cleanup.get("server_process_identity")
        or cleanup.get("server_process_identity", {}).get("pid") not in scope.get("member_pids", [])
        or tombstone.get("lease_id") != lease.get("lease_id")
        or tombstone.get("incarnation_id") != lease.get("incarnation_id")
        or tombstone.get("status") != "finalized"
        or tombstone.get("owner_request_id") != cleanup.get("model_request_id")
        or tombstone.get("profile_id") != lease.get("profile_id")
        or tombstone.get("server_termination") != "terminated"
        or tombstone.get("finalization_token") != cleanup.get("finalization_token")
        or not isinstance(release_result, Mapping)
        or release_result.get("lease") != {key: value for key, value in lease.items() if key != "content_sha256"}
        or termination.get("lease_ref") != cleanup.get("lease_ref")
        or termination.get("finalization_token") != cleanup.get("finalization_token")
        or termination.get("termination_observation") != release_result.get("release")
        or len(release_observations) != 1
        or release_observations[0].get("lease_ref") != cleanup.get("lease_ref")
        or release_observations[0].get("finalization_token") != cleanup.get("finalization_token")
        or release_observations[0].get("release_result_ref")
        != {"content_sha256": content_sha256(dict(release_result))}
        or stable != listener_stable
        or stable.get("scope_name") != scope.get("scope_name")
        or stable.get("authority") != "windows_job_object"
        or stable.get("scope_absent_after_owner_close") is not True
        or stable.get("cleanup_status") != "verified"
        or stable.get("member_pids_after") != []
        or stable.get("member_identities_after") != []
        or stable.get("active_listeners_after") != []
        or stable.get("pid_file_after") is not None
        or stable.get("stable_zero_observations", 0) < 3
        or no_active.get("active_lease_count") != 0
        or no_active.get("model_request_id") != cleanup.get("model_request_id")
    ):
        raise _EvidenceError("b2_cleanup_lineage_mismatch", "B2 acquired raw parent chain differs")
    samples = stable.get("samples")
    if not isinstance(samples, list) or len(samples) < 3 or any(
        not isinstance(sample, Mapping)
        or sample.get("pids") != []
        or sample.get("process_identities") != []
        or sample.get("listeners") != []
        for sample in samples[-3:]
    ):
        raise _EvidenceError("b2_cleanup_residue", "B2 ordered stable-zero samples differ")


def _validate_b2_acquisition_chain(
    *,
    roles: Mapping[str, list[tuple[Path, dict[str, Any]]]],
    runtime_owner: Mapping[str, object],
    ledger: Mapping[str, object],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    intents = [value for _path, value in roles.get("b2_acquisition_intent", [])]
    owners = [value for _path, value in roles.get("b2_acquisition_owner", [])]
    prepared_ledgers = [value for _path, value in roles.get("b2_prepared_materialization_ledger", [])]
    observations = [value for _path, value in roles.get("b2_acquisition_observation", [])]
    if len(intents) != 1 or len(owners) != 1 or len(prepared_ledgers) != 1 or len(observations) != 2:
        raise _EvidenceError("b2_acquisition_parent_missing", "B2 acquisition parent cardinality differs")
    intent = intents[0]
    owner = owners[0]
    prepared = prepared_ledgers[0]
    by_revision = {value.get("materialization_revision"): value for value in observations}
    if set(by_revision) != {0, 1}:
        raise _EvidenceError("b2_acquisition_observation_invalid", "B2 acquisition revisions differ")
    prepared_observation = by_revision[0]
    acquisition_observation = by_revision[1]
    intent_ref = {"content_sha256": intent.get("content_sha256")}
    runtime_ref = {"content_sha256": runtime_owner.get("content_sha256")}
    owner_ref = {"content_sha256": owner.get("content_sha256")}
    prepared_ref = {"content_sha256": prepared.get("content_sha256")}
    ledger_ref = {"content_sha256": ledger.get("content_sha256")}
    common_observation = {
        "model_request_id": runtime_owner.get("model_request_id"),
        "acquisition_owner_ref": owner_ref,
        "acquisition_intent_ref": intent_ref,
        "runtime_owner_ref": runtime_ref,
        "prepared_materialization_ledger_ref": prepared_ref,
    }
    if (
        intent.get("model_request_id") != runtime_owner.get("model_request_id")
        or intent.get("runtime_owner_ref") != runtime_ref
        or owner.get("model_request_id") != runtime_owner.get("model_request_id")
        or owner.get("runtime_owner_ref") != runtime_ref
        or owner.get("acquisition_intent_ref") != intent_ref
        or owner.get("owner_state") != "acquisition_prepared"
        or prepared.get("model_request_id") != runtime_owner.get("model_request_id")
        or prepared.get("acquisition_intent_ref") != intent_ref
        or prepared.get("runtime_owner_ref") != runtime_ref
        or prepared.get("state") != "prepared_never_materialized"
        or prepared.get("revision") != 0
        or prepared.get("transition") != "prepare"
        or prepared.get("predecessor_content_sha256") is not None
        or ledger.get("model_request_id") != runtime_owner.get("model_request_id")
        or ledger.get("acquisition_intent_ref") != intent_ref
        or ledger.get("runtime_owner_ref") != runtime_ref
        or ledger.get("revision") != 1
        or ledger.get("predecessor_content_sha256") != prepared.get("content_sha256")
        or any(prepared_observation.get(field) != value for field, value in common_observation.items())
        or prepared_observation.get("materialization_ledger_ref") != prepared_ref
        or prepared_observation.get("materialization_state") != "prepared_never_materialized"
        or any(acquisition_observation.get(field) != value for field, value in common_observation.items())
        or acquisition_observation.get("materialization_ledger_ref") != ledger_ref
        or acquisition_observation.get("materialization_state") != ledger.get("state")
    ):
        raise _EvidenceError("b2_acquisition_lineage_mismatch", "B2 acquisition raw parent chain differs")
    return intent, owner, prepared, prepared_observation, acquisition_observation


def _validate_b1_not_launched_raw(
    *,
    roles: Mapping[str, list[tuple[Path, dict[str, Any]]]],
    digest_index: Mapping[str, tuple[str, object]],
    cleanup: Mapping[str, object],
) -> dict[str, Any]:
    reservations = [value for _path, value in roles.get("b1_reservation", [])]
    by_state = {str(value.get("reservation_state")): value for value in reservations}
    if set(by_state) != {"reserved", "anchored", "cancelled_before_launch"} or len(reservations) != 3:
        raise _EvidenceError("b1_not_launched_reservation_invalid", "B1 not-launched reservation states differ")
    reserved = by_state["reserved"]
    anchored = by_state["anchored"]
    cancelled = by_state["cancelled_before_launch"]
    _source, operation_anchor, _expected = _validate_b1_source_anchor_raw(
        roles=roles,
        digest_index=digest_index,
        reserved=reserved,
    )
    anchored_body = {key: deepcopy(value) for key, value in reserved.items() if key != "content_sha256"}
    anchored_body["reservation_state"] = "anchored"
    anchored_body["predecessor_content_sha256"] = reserved["content_sha256"]
    if (
        anchored != seal_immutable(anchored_body)
        or cancelled.get("predecessor_content_sha256") != anchored.get("content_sha256")
        or any(
            cancelled.get(field) != anchored.get(field)
            for field in _B1_RESERVATION_FIELDS
            - {"content_sha256", "reservation_state", "abort_observation_ref", "predecessor_content_sha256"}
        )
        or cleanup.get("operation_anchor_ref")
        != {"content_sha256": operation_anchor.get("anchor_identity_sha256")}
        or cleanup.get("reservation_ref") != {"content_sha256": cancelled.get("content_sha256")}
        or cleanup.get("run_id") != anchored.get("run_id")
        or cleanup.get("stage") != anchored.get("stage")
        or cleanup.get("operation_id") != anchored.get("operation_id")
        or cleanup.get("worker_id") != anchored.get("worker_id")
        or cleanup.get("supervision_ref") is not None
        or cleanup.get("process_identity") is not None
        or cleanup.get("assignment_proven_ref") is not None
        or cleanup.get("finalization_intent_ref") is not None
        or cleanup.get("exact_handle_observation_refs") is not None
        or cleanup.get("job_absence_observation_ref") is not None
        or cleanup.get("worker_absence_observation_ref") is not None
        or cleanup.get("supervisor_absence_observation_ref") is not None
    ):
        raise _EvidenceError("b1_not_launched_branch_contradiction", "B1 not-launched nullability differs")
    observation = _resolved_parent(digest_index, cleanup.get("reservation_abort_ref"), "B1 not-launched observation")
    if (
        observation.get("contract_version") != "benchmark_worker_not_launched_observation_v1"
        or observation.get("outcome") != "verified_no_launch_artifacts"
        or observation.get("authority_kind") != anchored.get("authority_kind")
        or observation.get("run_id") != anchored.get("run_id")
        or observation.get("stage") != anchored.get("stage")
        or observation.get("operation_id") != anchored.get("operation_id")
        or observation.get("worker_id") != anchored.get("worker_id")
        or observation.get("reservation_ref") != {"content_sha256": anchored.get("content_sha256")}
        or cancelled.get("abort_observation_ref") != {"content_sha256": observation.get("content_sha256")}
        or observation.get("artifact_is_authorization") is not False
        or observation.get("execute_binding_enabled") is not False
    ):
        raise _EvidenceError("b1_not_launched_observation_invalid", "B1 no-launch observation differs")
    from app.learn.hybrid.windows_process_scope import benchmark_worker_scope_name_v1

    expected_scope = benchmark_worker_scope_name_v1(
        authority_kind=str(anchored.get("authority_kind")),
        run_id=str(anchored.get("run_id")),
        stage=str(anchored.get("stage")),
        operation_id=str(anchored.get("operation_id")),
        worker_id=str(anchored.get("worker_id")),
        payload_sha256=str(anchored.get("payload_sha256")),
        execution_nonce=str(anchored.get("execution_nonce")),
    )
    expected_event = "Local\\AgentGuiBenchmarkWorkerGate-" + content_sha256(
        {"scope_name": expected_scope}
    )
    predecessor = str(anchored["content_sha256"])
    expected_kinds = (
        ("owner", "owner_absence_observation_ref"),
        ("process_event_job_beacon", "process_event_job_beacon_absence_observation_ref"),
        ("result", "result_absence_observation_ref"),
        ("provider", "provider_absence_observation_ref"),
    )
    expected_checks = {
        "owner": {"registry_record_absent": True, "owner_journal_absent": True},
        "process_event_job_beacon": {
            "worker_journal_absent": True,
            "startup_event_absent": True,
            "owner_job_absent": True,
            "beacon_absent": True,
            "scope_name": expected_scope,
            "event_name": expected_event,
        },
        "result": {"result_absent": True},
        "provider": {"provider_owner_absent": True},
    }
    for kind, field in expected_kinds:
        absence = _resolved_parent(digest_index, observation.get(field), f"B1 {kind} pre-anchor absence")
        if (
            absence.get("contract_version") != "benchmark_worker_pre_anchor_absence_observation_v1"
            or absence.get("observation_kind") != kind
            or absence.get("outcome") != "absent"
            or absence.get("reservation_ref") != {"content_sha256": anchored.get("content_sha256")}
            or absence.get("predecessor_content_sha256") != predecessor
            or absence.get("run_id") != anchored.get("run_id")
            or absence.get("stage") != anchored.get("stage")
            or absence.get("operation_id") != anchored.get("operation_id")
            or absence.get("worker_id") != anchored.get("worker_id")
            or absence.get("checks") != expected_checks[kind]
        ):
            raise _EvidenceError("b1_not_launched_absence_invalid", "B1 pre-anchor absence chain differs")
        predecessor = str(absence["content_sha256"])
    if observation.get("predecessor_content_sha256") != predecessor:
        raise _EvidenceError("b1_not_launched_absence_invalid", "B1 no-launch absence head differs")
    return cancelled


def _validate_b2_not_acquired_raw(
    *,
    roles: Mapping[str, list[tuple[Path, dict[str, Any]]]],
    digest_index: Mapping[str, tuple[str, object]],
    runtime_owner: Mapping[str, object],
    ledger: Mapping[str, object],
    cleanup: Mapping[str, object],
) -> None:
    forbidden = (
        "lease_ref", "profile_ref", "server_process_identity", "socket_ref", "job_scope_ref",
        "finalization_token", "lease_state_ref", "termination_observation_ref",
    )
    if any(cleanup.get(field) is not None for field in forbidden):
        raise _EvidenceError("b2_not_acquired_contains_owner", "B2 not-acquired branch contains owner resources")
    intent, acquisition_owner, prepared, prepared_observation, acquisition_observation = (
        _validate_b2_acquisition_chain(
            roles=roles,
            runtime_owner=runtime_owner,
            ledger=ledger,
        )
    )
    if (
        ledger.get("revision") != 1
        or ledger.get("transition") != "abort"
        or ledger.get("state") != "aborted_never_materialized"
        or ledger.get("predecessor_content_sha256") != prepared.get("content_sha256")
    ):
        raise _EvidenceError("b2_abort_ledger_invalid", "B2 abort materialization lineage differs")
    production_tombstone = _resolved_parent(
        digest_index, cleanup.get("owner_tombstone_ref"), "B2 no-owner tombstone"
    )
    no_owned = _resolved_parent(
        digest_index, cleanup.get("no_owned_runtime_observation_ref"), "B2 no-owned runtime"
    )
    stable = _resolved_parent(
        digest_index, cleanup.get("scope_stable_zero_ref"), "B2 not-acquired stable zero"
    )
    listener = _resolved_parent(
        digest_index, cleanup.get("listener_stable_zero_ref"), "B2 not-acquired listener zero"
    )
    no_active = _resolved_parent(
        digest_index, cleanup.get("no_active_lease_observation_ref"), "B2 not-acquired no-active lease"
    )
    abort_tombstones = [value for _path, value in roles.get("b2_abort_tombstone", [])]
    abort_results = [value for _path, value in roles.get("b2_acquisition_abort", [])]
    if len(abort_tombstones) != 1 or len(abort_results) != 1:
        raise _EvidenceError("b2_abort_parent_missing", "B2 abort parents are missing or ambiguous")
    tombstone = abort_tombstones[0]
    abort = abort_results[0]
    if (
        production_tombstone != no_owned
        or production_tombstone.get("contract_version")
        != "hybrid_qwen_aborted_acquisition_tombstone_v1"
        or production_tombstone.get("status") != "aborted_before_lease"
        or production_tombstone.get("model_request_id") != runtime_owner.get("model_request_id")
        or production_tombstone.get("provider") != "qwen"
        or production_tombstone.get("lineage")
        != {"run_id": runtime_owner.get("run_id"), "operation_id": runtime_owner.get("operation_id")}
        or production_tombstone.get("process_scope_name") != stable.get("scope_name")
        or production_tombstone.get("scope_cleanup_evidence")
        != {key: value for key, value in stable.items() if key != "content_sha256"}
        or tombstone.get("historical_process_identity") is not None
        or tombstone.get("historical_socket_ref") is not None
        or tombstone.get("historical_job_scope_ref") is not None
        or tombstone.get("materialization_ledger_ref") != {"content_sha256": ledger.get("content_sha256")}
        or tombstone.get("acquisition_intent_ref") != {"content_sha256": intent.get("content_sha256")}
        or tombstone.get("runtime_owner_ref") != {"content_sha256": runtime_owner.get("content_sha256")}
        or abort.get("owner_state") != "acquisition_aborted"
        or abort.get("acquisition_intent_ref") != {"content_sha256": intent.get("content_sha256")}
        or abort.get("runtime_owner_ref") != {"content_sha256": runtime_owner.get("content_sha256")}
        or abort.get("materialization_ledger_ref") != {"content_sha256": ledger.get("content_sha256")}
        or abort.get("owner_tombstone_ref")
        != {"content_sha256": production_tombstone.get("content_sha256")}
        or abort.get("reason") != tombstone.get("reason")
        or cleanup.get("release_reason") != tombstone.get("reason")
        or stable != listener
        or stable.get("authority") != "windows_job_object"
        or stable.get("scope_absent_after_owner_close") is not True
        or stable.get("cleanup_status") != "verified"
        or stable.get("member_pids_after") != []
        or stable.get("member_identities_after") != []
        or stable.get("active_listeners_after") != []
        or stable.get("pid_file_after") is not None
        or stable.get("stable_zero_observations", 0) < 3
        or no_active.get("active_lease_count") != 0
        or no_active.get("model_request_id") != runtime_owner.get("model_request_id")
        or prepared_observation.get("acquisition_owner_ref")
        != {"content_sha256": acquisition_owner.get("content_sha256")}
        or acquisition_observation.get("acquisition_owner_ref")
        != {"content_sha256": acquisition_owner.get("content_sha256")}
    ):
        raise _EvidenceError("b2_not_acquired_lineage_mismatch", "B2 not-acquired raw parent chain differs")
    samples = stable.get("samples")
    if not isinstance(samples, list) or len(samples) < 3 or any(
        not isinstance(sample, Mapping)
        or sample.get("pids") != []
        or sample.get("process_identities") != []
        or sample.get("listeners") != []
        for sample in samples[-3:]
    ):
        raise _EvidenceError("b2_cleanup_residue", "B2 not-acquired ordered stable-zero samples differ")


def _derive_parent_facts(
    roles: dict[str, list[tuple[Path, dict[str, Any]]]],
    digest_index: Mapping[str, tuple[str, object]],
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
    _validate_task5_binding_raw(
        authority=authority,
        serialized=serialized,
        root=root,
        window_identity=window_identity,
    )
    payload_unsealed = {key: value for key, value in serialized.items() if key != "payload_sha256"}
    if serialized.get("payload_sha256") != _sha_bytes(canonical_json_bytes(payload_unsealed)):
        findings.append(_finding("binding_payload_seal_mismatch", "failed", [str(authority["content_sha256"])]))
    source = _one(roles, "b1_source")
    if (
        source is None
        or source.get("window_binding_ref") != authority.get("window_binding_ref")
        or source.get("capture_ref", {}).get("content_sha256")
        != authority.get("capture_ref", {}).get("content_sha256")
        or source.get("capture_ref", {}).get("id")
        != authority.get("capture_ref", {}).get("capture_id")
    ):
        raise _EvidenceError("b1_source_binding_mismatch", "B1 source does not bind the exact Task 5 capture")
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

    if worker_cleanup.get("outcome") not in {"verified_exact_worker_exited", "verified_not_launched"}:
        findings.append(_finding("b1_cleanup_outcome_invalid", "failed", [str(worker_cleanup["content_sha256"])]))
    terminal_owner_candidates = [
        value
        for _path, value in roles.get("b1_owner", [])
        if value.get("phase") == "cleanup_finalization_intent"
    ]
    if worker_cleanup.get("outcome") == "verified_exact_worker_exited":
        primary_candidates = [
            value
            for value in terminal_owner_candidates
            if value.get("worker_id") == worker_cleanup.get("worker_id")
            and value.get("operation_id") == worker_cleanup.get("operation_id")
            and value.get("process_identity") == worker_cleanup.get("process_identity")
            and value.get("reservation_ref") == worker_cleanup.get("reservation_ref")
            and value.get("supervision_ref") == worker_cleanup.get("supervision_ref")
        ]
        if len(primary_candidates) != 1:
            raise _EvidenceError("b1_primary_owner_ambiguous", "B1 primary owner lineage is missing or ambiguous")
        primary_owner = primary_candidates[0]
        if assignment is None:
            raise _EvidenceError("missing_owner_parent", "launched B1 worker requires one assignment parent")
        assignment_identity = _process_identity(assignment.get("process_identity"), "B1 assignment identity")
        observed = assignment.get("observed_member_identities")
        if not isinstance(observed, list) or assignment_identity not in observed:
            findings.append(_finding("b1_assignment_membership_missing", "failed", [str(assignment["content_sha256"])]))
        for owner in terminal_owner_candidates:
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
        _validate_b1_launched_raw(
            roles=roles,
            digest_index=digest_index,
            primary_owner=primary_owner,
            cleanup=worker_cleanup,
            assignment=assignment,
        )
    else:
        if assignment is not None or roles.get("b1_owner"):
            raise _EvidenceError("b1_not_launched_branch_contradiction", "B1 not-launched branch contains launched owner evidence")
        assignment_identity = None
        primary_owner = _validate_b1_not_launched_raw(
            roles=roles,
            digest_index=digest_index,
            cleanup=worker_cleanup,
        )

    normal = _one(roles, "task5_normal_clear")
    binding_status = "verified"
    if normal is None:
        binding_status = (
            "not_applicable_not_launched"
            if worker_cleanup.get("outcome") == "verified_not_launched"
            else "inapplicable_strong_kill"
        )
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
    primary_reservation_ref = (
        primary_owner.get("reservation_ref")
        if worker_cleanup.get("outcome") == "verified_exact_worker_exited"
        else worker_cleanup.get("reservation_ref")
    )
    reservation_refs = [primary_reservation_ref, runtime_owner.get("reservation_ref"), provider_journal.get("reservation_ref")]
    if len({_content_ref(item, "reservation ref")["content_sha256"] for item in reservation_refs}) != 1:
        findings.append(_finding("cross_reservation_parent", "failed", [str(document["content_sha256"]) for document in lineage_documents]))
    if (
        provider_journal.get("runtime_owner_ref", {}).get("content_sha256") != runtime_owner.get("content_sha256")
        or ledger.get("runtime_owner_ref", {}).get("content_sha256") != runtime_owner.get("content_sha256")
        or provider_journal.get("acquisition_intent_ref") != ledger.get("acquisition_intent_ref")
    ):
        findings.append(_finding("b2_parent_lineage_mismatch", "failed", [str(runtime_owner["content_sha256"]), str(ledger["content_sha256"]), str(provider_journal["content_sha256"])]))
    intent = _one(roles, "b2_acquisition_intent")
    acquisition_owner = _one(roles, "b2_acquisition_owner")
    prepared_ledger = _one(roles, "b2_prepared_materialization_ledger")
    observations = [value for _path, value in roles.get("b2_acquisition_observation", [])]
    by_revision = {value.get("materialization_revision"): value for value in observations}
    if intent is None or acquisition_owner is None or prepared_ledger is None or set(by_revision) != {0, 1}:
        raise _EvidenceError("b2_acquisition_parent_missing", "B2 provider journal raw parents are incomplete")
    if (
        provider_journal.get("acquisition_owner_ref")
        != {"content_sha256": acquisition_owner.get("content_sha256")}
        or provider_journal.get("acquisition_intent_ref")
        != {"content_sha256": intent.get("content_sha256")}
        or provider_journal.get("authority_kind") != runtime_owner.get("authority_kind")
    ):
        findings.append(_finding("b2_parent_lineage_mismatch", "failed", [str(provider_journal["content_sha256"])]))
    if provider_journal.get("contract_version") == "benchmark_provider_registry_journal_v1" and (
        provider_journal.get("prepared_materialization_ledger_ref")
        != {"content_sha256": prepared_ledger.get("content_sha256")}
        or provider_journal.get("prepared_acquisition_observation_ref")
        != {"content_sha256": by_revision[0].get("content_sha256")}
        or provider_journal.get("acquisition_observation_ref")
        != {"content_sha256": by_revision[1].get("content_sha256")}
        or provider_journal.get("materialization_ledger_ref")
        != {"content_sha256": ledger.get("content_sha256")}
    ):
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
            _validate_b2_acquired_raw(
                roles=roles,
                digest_index=digest_index,
                runtime_owner=runtime_owner,
                ledger=ledger,
                cleanup=provider_cleanup,
            )
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
            _validate_b2_not_acquired_raw(
                roles=roles,
                digest_index=digest_index,
                runtime_owner=runtime_owner,
                ledger=ledger,
                cleanup=provider_cleanup,
            )
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
    for index, input_path in enumerate(sorted(paths, key=lambda item: os.path.normcase(str(item)))):
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
        "external_rows_by_sample": [],
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
    owner_keys: dict[tuple[int, int, str], list[dict[str, object]]] = {}
    for owner in owners:
        identity = owner["process_identity"]
        key = (int(identity["pid"]), int(identity["create_time_ns"]), device_uuid)
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
                "acquire_time_ns": int(identity["create_time_ns"]),
                "release_upper_at_utc": (
                    observations[next(
                        candidate
                        for candidate in range(observed_indices[-1] + 1, len(observations))
                        if str(observations[candidate]["sample"]["content_sha256"]) == release_ref
                    )]["sample"]["process_snapshot"]["observed_at_utc"]
                    if release_ref is not None
                    else None
                ),
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
    interval_overlap = False
    for index, left in enumerate(intervals):
        if left["status"] != "bounded":
            continue
        left_release = _timestamp(left["release_upper_at_utc"], "owner release upper")
        left_release_ns = int(round(left_release.timestamp() * 1_000_000_000))
        for right in intervals[index + 1 :]:
            if right["kind"] != left["kind"] or right["status"] != "bounded":
                continue
            right_release = _timestamp(right["release_upper_at_utc"], "owner release upper")
            right_release_ns = int(round(right_release.timestamp() * 1_000_000_000))
            if max(int(left["acquire_time_ns"]), int(right["acquire_time_ns"])) <= min(
                left_release_ns, right_release_ns
            ):
                interval_overlap = True
                findings.append(
                    _finding(
                        "same_kind_owner_interval_overlap",
                        "failed",
                        [str(left["subject_id"]), str(right["subject_id"])],
                    )
                )
    overlap_status = "failed" if any(value > 1 for value in max_concurrent.values()) or interval_overlap else "indeterminate" if any(interval_item["status"] != "bounded" for interval_item in intervals) else "verified"
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
            exact_claims = owner_keys.get((pid, created, gpu_uuid), [])
            target_device_pid_claimed = any(
                key[0] == pid and key[2] == device_uuid for key in owner_keys
            )
            if gpu_uuid == device_uuid and target_device_pid_claimed and not exact_claims:
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
    elif any(
        (int(owner["process_identity"]["pid"]), int(owner["process_identity"]["create_time_ns"]))
        in {
            (int(identity["pid"]), int(identity["create_time_ns"]))
            for identity in samples[-1]["process_snapshot"]["identities"]
        }
        for owner in owners
    ):
        owned_by_sample[-1] = None
        findings.append(_finding("owned_process_still_live", "failed", [str(samples[-1]["content_sha256"])]))
    elif owned_by_sample[-1] != 0:
        findings.append(_finding("owned_vram_residue", "failed", [str(samples[-1]["content_sha256"])]))
    for owner in owners:
        identity = owner["process_identity"]
        exact_key = (int(identity["pid"]), int(identity["create_time_ns"]), device_uuid)
        if not any(
            exact_key in {(pid, created, gpu_uuid) for pid, created, gpu_uuid, _memory in observation["rows"]}
            for observation in observations[1:-1]
        ):
            findings.append(_finding("launched_owner_gpu_row_missing", "indeterminate", [str(owner["evidence_ref"])]))
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
        "external_rows_by_sample": [
            {
                "sample_ref": observations[index]["sample"]["content_sha256"],
                "rows": rows,
            }
            for index, rows in enumerate(external_by_sample)
        ],
        "device_used_baseline_mib": used_by_sample[0],
        "device_used_post_mib": used_by_sample[-1],
        "device_residual_baseline_mib": residual_by_sample[0],
        "device_residual_post_mib": residual_by_sample[-1],
        "device_residual_status": residual_status,
    }
    return gpu_summary, owner_summary, findings


def _validate_probe_parent(value: dict[str, Any]) -> str:
    contracts: dict[str, tuple[str, set[str]]] = {
        "benchmark_v2_probe_provider_profile_v1": ("probe_profile", _PROBE_PROFILE_FIELDS),
        "benchmark_v2_probe_request_in_flight_v1": ("probe_request", _PROBE_REQUEST_FIELDS),
        "benchmark_v2_probe_body_observation_v1": ("probe_body", _PROBE_BODY_PARENT_FIELDS),
        "benchmark_v2_probe_socket_owner_v1": ("probe_socket", _PROBE_SOCKET_PARENT_FIELDS),
        "benchmark_v2_probe_job_membership_v1": ("probe_job", _PROBE_JOB_PARENT_FIELDS),
        "benchmark_v2_probe_lease_owner_v1": ("probe_lease", _PROBE_LEASE_PARENT_FIELDS),
        "benchmark_v2_probe_termination_v1": ("probe_termination", _PROBE_TERMINATION_PARENT_FIELDS),
        "benchmark_v2_probe_zero_sample_v1": ("probe_zero_sample", _PROBE_ZERO_SAMPLE_FIELDS),
        "benchmark_v2_probe_stable_zero_bundle_v1": ("probe_zero_bundle", _PROBE_ZERO_BUNDLE_FIELDS),
    }
    contract = value.get("contract_version")
    if contract not in contracts:
        raise _EvidenceError("unknown_probe_parent_contract", "probe raw parent contract differs")
    role, fields = contracts[str(contract)]
    parent = _sealed(value, fields, role)
    if role.startswith("probe_") and role not in {"probe_request", "probe_body"}:
        provider = parent.get("provider_id")
        if provider not in _PROVIDERS:
            raise _EvidenceError("extra_probe_cell", "probe parent provider differs")
    return role


def _probe_resolved(
    index: Mapping[str, tuple[str, dict[str, Any]]], value: object, name: str
) -> tuple[str, dict[str, Any]]:
    ref = _content_ref(value, name)
    assert ref is not None
    result = index.get(str(ref["content_sha256"]))
    if result is None:
        raise _EvidenceError("dangling_probe_ref", f"{name} does not resolve")
    return result


def _validate_probe_raw_parents(
    probe: Mapping[str, object],
    index: Mapping[str, tuple[str, dict[str, Any]]],
) -> None:
    provider_id = str(probe["provider"]["provider_id"])
    profile_role, profile = _probe_resolved(
        index,
        {"content_sha256": probe["provider"]["profile_sha256"]},
        "probe profile",
    )
    request_role, request = _probe_resolved(
        index, probe["request_in_flight_observation"]["evidence_ref"], "probe request"
    )
    body_role, body = _probe_resolved(
        index, probe["body_completion_observation"]["evidence_ref"], "probe body"
    )
    lease_role, lease = _probe_resolved(index, probe["lease_or_owner"]["lease_ref"], "probe lease")
    socket_role, socket = _probe_resolved(index, probe["lease_or_owner"]["socket_ref"], "probe socket")
    job_role, job = _probe_resolved(index, probe["lease_or_owner"]["job_scope_ref"], "probe Job")
    termination_role, termination = _probe_resolved(
        index, probe["termination_observation"]["evidence_ref"], "probe termination"
    )
    bundle_refs = {
        str(probe["stable_zero_observation"][field]["content_sha256"])
        for field in ("process_absence_ref", "listener_absence_ref", "lease_absence_ref")
    }
    if len(bundle_refs) != 1:
        raise _EvidenceError("probe_stable_zero_invalid", "probe stable-zero bundle refs differ")
    bundle_role, bundle = _probe_resolved(
        index, {"content_sha256": next(iter(bundle_refs))}, "probe stable-zero bundle"
    )
    expected_roles = (
        profile_role,
        request_role,
        body_role,
        lease_role,
        socket_role,
        job_role,
        termination_role,
        bundle_role,
    )
    if expected_roles != (
        "probe_profile", "probe_request", "probe_body", "probe_lease", "probe_socket",
        "probe_job", "probe_termination", "probe_zero_bundle",
    ):
        raise _EvidenceError("probe_parent_role_mismatch", "probe raw parent roles differ")
    attempt_id = profile.get("attempt_id")
    incarnation_id = lease.get("incarnation_id")
    identity = probe["lease_or_owner"]["process_identity"]
    lineage_fields = ("run_id", "stage", "operation_id", "model_request_id")
    if (
        profile.get("provider_id") != provider_id
        or profile.get("profile_id") != probe["provider"]["profile_id"]
        or request.get("provider_id") != provider_id
        or request.get("attempt_id") != attempt_id
        or any(request.get(field) != probe.get(field) for field in lineage_fields)
        or request.get("state") != "request_in_flight"
        or body.get("provider_id") != provider_id
        or body.get("attempt_id") != attempt_id
        or any(body.get(field) != probe.get(field) for field in lineage_fields)
        or body.get("state") != probe["body_completion_observation"]["state"]
        or lease.get("provider_id") != provider_id
        or lease.get("attempt_id") != attempt_id
        or lease.get("profile_ref") != {"content_sha256": profile.get("content_sha256")}
        or lease.get("process_identity") != identity
        or socket.get("provider_id") != provider_id
        or socket.get("attempt_id") != attempt_id
        or socket.get("incarnation_id") != incarnation_id
        or socket.get("process_identity") != identity
        or lease.get("socket_ref") != {"content_sha256": socket.get("content_sha256")}
        or job.get("provider_id") != provider_id
        or job.get("attempt_id") != attempt_id
        or job.get("incarnation_id") != incarnation_id
        or job.get("member_identities") != [identity]
        or lease.get("job_scope_ref") != {"content_sha256": job.get("content_sha256")}
        or termination.get("provider_id") != provider_id
        or termination.get("attempt_id") != attempt_id
        or termination.get("incarnation_id") != incarnation_id
        or termination.get("process_identity") != identity
        or termination.get("outcome") != "same_incarnation_exited"
        or termination.get("predecessor_content_sha256") != lease.get("content_sha256")
        or bundle.get("provider_id") != provider_id
        or bundle.get("attempt_id") != attempt_id
        or bundle.get("incarnation_id") != incarnation_id
        or bundle.get("predecessor_content_sha256") != termination.get("content_sha256")
        or probe.get("predecessor_content_sha256") != bundle.get("content_sha256")
    ):
        raise _EvidenceError("probe_parent_lineage_mismatch", "probe raw parent identity joins differ")
    if (
        bundle.get("process_absent") is not True
        or bundle.get("listener_absent") is not True
        or bundle.get("lease_absent") is not True
    ):
        raise _EvidenceError("probe_residue", "probe stable-zero bundle reports residue")
    request_at = _timestamp(request.get("observed_at_utc"), "probe request parent time")
    trigger_at = _timestamp(probe["trigger"]["triggered_at_utc"], "probe trigger time")
    termination_at = _timestamp(termination.get("terminated_at_utc"), "probe termination time")
    body_at = _timestamp(body.get("observed_at_utc"), "probe body parent time")
    lease_at = _timestamp(lease.get("acquired_at_utc"), "probe lease acquisition time")
    if (
        probe["request_in_flight_observation"].get("observed_at_utc")
        != request.get("observed_at_utc")
        or probe["body_completion_observation"].get("observed_at_utc")
        != body.get("observed_at_utc")
        or not lease_at <= request_at <= trigger_at < termination_at <= body_at
    ):
        raise _EvidenceError("probe_trigger_order_invalid", "probe trigger/termination ordering differs")
    raw_sample_refs = bundle.get("sample_refs")
    if not isinstance(raw_sample_refs, list) or len(raw_sample_refs) < 3:
        raise _EvidenceError("probe_stable_zero_invalid", "probe has fewer than three zero parents")
    samples: list[dict[str, Any]] = []
    for raw_ref in raw_sample_refs:
        role, sample = _probe_resolved(index, raw_ref, "probe zero sample")
        if role != "probe_zero_sample":
            raise _EvidenceError("probe_stable_zero_invalid", "probe zero sample role differs")
        samples.append(sample)
    previous = str(termination["content_sha256"])
    previous_at = termination_at
    for sequence, sample in enumerate(samples):
        observed_at = _timestamp(sample.get("observed_at_utc"), "probe zero sample time")
        if (
            sample.get("provider_id") != provider_id
            or sample.get("attempt_id") != attempt_id
            or sample.get("incarnation_id") != incarnation_id
            or sample.get("sequence") != sequence
            or sample.get("predecessor_content_sha256") != previous
            or observed_at <= previous_at
            or sample.get("job_members") != []
            or sample.get("active_listeners") != []
            or sample.get("active_leases") != []
        ):
            raise _EvidenceError("probe_residue", "probe ordered zero parent differs")
        previous = str(sample["content_sha256"])
        previous_at = observed_at
    if bundle.get("sample_refs")[-1] != {"content_sha256": previous}:
        raise _EvidenceError("probe_stable_zero_invalid", "probe zero bundle head differs")
    receipt_zero = probe["stable_zero_observation"]
    if (
        receipt_zero.get("stable_zero_observations") != len(samples)
        or receipt_zero.get("job_members") != samples[-1].get("job_members")
        or receipt_zero.get("active_listeners") != samples[-1].get("active_listeners")
        or receipt_zero.get("active_leases") != samples[-1].get("active_leases")
    ):
        raise _EvidenceError("probe_stable_zero_invalid", "probe receipt does not match raw zero parents")


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
    _sha(provider.get("profile_sha256"), "probe profile SHA")
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
    raw_receipts: list[tuple[Path, dict[str, Any]]] = []
    parent_index: dict[str, tuple[str, dict[str, Any]]] = {}
    seen_paths: set[str] = set()
    seen_content: set[str] = set()
    for index, input_path in enumerate(sorted(paths, key=lambda item: os.path.normcase(str(item)))):
        resolved, raw = _read_input(input_path, f"probe_receipt_paths[{index}]")
        path_key = os.path.normcase(str(resolved))
        if path_key in seen_paths:
            findings.append(_finding("duplicate_input_path", "failed"))
            continue
        seen_paths.add(path_key)
        try:
            value = _decode_canonical_json(raw, f"probe evidence {resolved}")
            digest = str(value.get("content_sha256") or "")
            if digest in seen_content:
                findings.append(_finding("duplicate_input_content", "failed", [digest]))
                continue
            seen_content.add(digest)
            if value.get("contract_version") == _PROBE_CONTRACT:
                probe = _validate_probe(value)
                raw_receipts.append((resolved, probe))
                refs.append(_source_ref(resolved, probe, "probe_receipt"))
            else:
                role = _validate_probe_parent(value)
                parent_index[str(value["content_sha256"])] = (role, value)
                refs.append(_source_ref(resolved, value, role))
        except _EvidenceError as error:
            findings.append(_finding(error.code, error.disposition, list(error.refs)))
    cells: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for resolved, probe in sorted(
        raw_receipts,
        key=lambda item: (
            str(item[1]["provider"]["provider_id"]), str(item[1]["probe_kind"]),
            str(item[1]["content_sha256"]), str(item[0]),
        ),
    ):
        digest = str(probe["content_sha256"])
        provider_id = str(probe["provider"]["provider_id"])
        kind = str(probe["probe_kind"])
        try:
            _validate_probe_raw_parents(probe, parent_index)
        except _EvidenceError as error:
            findings.append(_finding(error.code, error.disposition, [digest, *error.refs]))
            continue
        cells.setdefault((provider_id, kind), []).append(probe)
        probes.append(probe)
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
    verified = [
        list(cell)
        for cell in _REQUIRED_MATRIX
        if len(cells.get(cell, [])) == 1
        and cells[cell][0]["body_completion_observation"]["state"] == "not_complete"
    ]
    summary = {
        "required_matrix": [list(cell) for cell in _REQUIRED_MATRIX],
        "verified_matrix": verified,
        "missing_matrix": missing,
    }
    refs.sort(key=lambda item: (item["semantic_role"], item["content_sha256"], item["canonical_path"]))
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


def _actual_b1_expected_path(role: str, value: Mapping[str, object], worker_root: Path) -> Path | None:
    worker = value.get("worker_id")
    operation = value.get("operation_id")
    if role == "b1_reservation" and isinstance(operation, str):
        return worker_root / f"{operation}.benchmark-reservation.json"
    if not isinstance(worker, str) or not worker:
        return None
    fixed = {
        "b1_assignment": f"{worker}.benchmark-assignment.json",
        "b1_owner": f"{worker}.benchmark-owner.json",
        "b1_cleanup": f"{worker}.benchmark-cleanup.json",
        "b1_beacon": f"{worker}.benchmark-beacon.json",
        "b1_launch_anchor": f"{worker}.benchmark-launch-identity-anchor.json",
        "b1_exit_join": f"{worker}.exit-join.json",
        "b1_stable_zero": f"{worker}.stable-zero.json",
        "b1_finalization_intent": f"{worker}.benchmark-cleanup-intent.json",
        "b1_not_launched": f"{worker}.benchmark-not-launched.json",
    }
    if role in fixed:
        return worker_root / fixed[role]
    if role == "b1_handle_close":
        suffixes = {
            "worker_process": "worker-process-close.json",
            "startup_event": "startup-event-close.json",
            "beacon_file": "beacon-file-close.json",
            "owner_job": "owner-job-close.json",
        }
        suffix = suffixes.get(str(value.get("handle_kind")))
        return worker_root / f"{worker}.{suffix}" if suffix else None
    if role == "b1_absence":
        kind = value.get("observation_kind")
        return worker_root / f"{worker}.{kind}-absence.json" if isinstance(kind, str) and kind else None
    if role == "b1_pre_anchor_absence":
        kind = value.get("observation_kind")
        return worker_root / f"{worker}.pre-anchor-{kind}-absence.json" if isinstance(kind, str) and kind else None
    return None


def _actual_b2_expected_path(
    role: str,
    value: Mapping[str, object],
    *,
    request_paths: Mapping[str, Path],
    worker_root: Path,
) -> Path | None:
    keys = {
        "b2_acquisition_intent": "intent",
        "b2_acquisition_owner": "owner",
        "b2_prepared_materialization_ledger": "ledger_revision_zero",
        "b2_materialization_ledger": "ledger",
        "b2_acquisition_abort": "abort",
        "b2_abort_tombstone": "aborted_tombstone",
        "b2_lease_binding": "lease_binding",
        "b2_lease_state": "lease_state_snapshot",
        "b2_release_observation": "release_observation",
        "b2_termination": "termination_observation",
        "b2_cleanup": "cleanup_receipt",
    }
    if role in keys:
        return request_paths.get(keys[role])
    if role == "b2_owner_tombstone" or role == "b2_production_abort_tombstone":
        from app.core import model_server

        request_id = value.get("model_request_id")
        return model_server._qwen_owner_tombstone_path(str(request_id)) if isinstance(request_id, str) else None
    operation = value.get("operation_id")
    if role == "b2_provider_journal" and isinstance(operation, str):
        return worker_root / f"{operation}.benchmark-provider.json"
    if role == "b2_provider_cleanup_journal" and isinstance(operation, str):
        return worker_root / f"{operation}.benchmark-provider-cleanup.json"
    return None


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
    from app.learn.hybrid import benchmark_v2_worker_binding as worker_binding

    binding_parent = roles.get("task5_binding_authority", [])
    if len(binding_parent) != 1:
        findings.append(_finding("actual_task5_parent_path_not_canonical", "failed"))
    else:
        binding_path, binding = binding_parent[0]
        expected_binding_path = worker_binding._authority_file(
            worker_binding._PRODUCTION_SERVER_BINDING_AUTHORITY_ROOT,
            str(binding.get("window_binding_ref", {}).get("content_sha256") or ""),
        )
        if binding_path != expected_binding_path:
            findings.append(
                _finding(
                    "actual_task5_parent_path_not_canonical",
                    "failed",
                    [str(binding.get("content_sha256"))],
                )
            )
    worker_root = (Path(__file__).resolve().parents[3] / "logs" / "workflow-workers").resolve()
    b1_roles = {
        "b1_source",
        "b1_reservation",
        "b1_operation_anchor",
        "b1_expected_supervision",
        "b1_actual_supervision",
        "b1_assignment",
        "b1_beacon",
        "b1_launch_anchor",
        "b1_owner",
        "b1_exit_join",
        "b1_handle_close",
        "b1_stable_zero",
        "b1_finalization_intent",
        "b1_absence",
        "b1_pre_anchor_absence",
        "b1_not_launched",
        "b1_cleanup",
    }
    for role in sorted(b1_roles):
        for path, value in roles.get(role, []):
            expected = _actual_b1_expected_path(role, value, worker_root)
            if expected is None:
                findings.append(
                    _finding("actual_b1_parent_provenance_unavailable", "failed", [str(value["content_sha256"])])
                )
            elif path != expected.resolve():
                findings.append(
                    _finding("actual_b1_parent_path_not_canonical", "failed", [str(value["content_sha256"])])
                )
    from app.core import model_server

    request_id = str(_one(roles, "b2_runtime_owner").get("model_request_id") if _one(roles, "b2_runtime_owner") else "")
    expected_b2 = model_server._qwen_acquisition_artifact_paths(request_id) if request_id else {}
    b2_roles = {
        "b2_runtime_owner",
        "b2_acquisition_intent",
        "b2_acquisition_owner",
        "b2_acquisition_observation",
        "b2_prepared_materialization_ledger",
        "b2_materialization_ledger",
        "b2_lease_binding",
        "b2_lease_state",
        "b2_lease",
        "b2_socket",
        "b2_scope_acquisition",
        "b2_release_observation",
        "b2_termination",
        "b2_owner_tombstone",
        "b2_scope_cleanup",
        "b2_no_active_lease",
        "b2_abort_tombstone",
        "b2_acquisition_abort",
        "b2_production_abort_tombstone",
        "b2_provider_journal",
        "b2_provider_cleanup_journal",
        "b2_cleanup",
    }
    for role in sorted(b2_roles):
        for path, value in roles.get(role, []):
            expected = _actual_b2_expected_path(
                role, value, request_paths=expected_b2, worker_root=worker_root
            )
            if expected is None:
                findings.append(
                    _finding("actual_b2_parent_provenance_unavailable", "failed", [str(value["content_sha256"])])
                )
            elif path != expected.resolve():
                findings.append(
                    _finding("actual_b2_parent_path_not_canonical", "failed", [str(value["content_sha256"])])
                )
    root = _one(roles, "task4_window_root")
    expected_helper = Path(__file__).resolve().parents[3] / "scripts" / "portfolio_hybrid_v1_1_test_window_v2.py"
    root_path_value = roles.get("task4_window_root", [])[0][0] if roles.get("task4_window_root") else None
    if root is None or root.get("helper_path") != str(expected_helper.resolve()):
        findings.append(_finding("actual_task4_helper_not_canonical", "failed"))
    if root_path_value is None or root_path_value.parent != worker_binding._PRODUCTION_SERVER_BINDING_AUTHORITY_ROOT:
        findings.append(_finding("actual_task4_parent_path_not_canonical", "failed"))
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
    qwen_cleanup = _one(roles, "b2_cleanup")
    for probe in [item for item in probes if item.get("provider", {}).get("provider_id") == "qwen"]:
        lease_or_owner = probe.get("lease_or_owner")
        termination = probe.get("termination_observation")
        if (
            qwen_cleanup is None
            or not isinstance(lease_or_owner, Mapping)
            or not isinstance(termination, Mapping)
            or probe.get("model_request_id") != qwen_cleanup.get("model_request_id")
            or lease_or_owner.get("lease_ref") != qwen_cleanup.get("lease_ref")
            or lease_or_owner.get("socket_ref") != qwen_cleanup.get("socket_ref")
            or lease_or_owner.get("job_scope_ref") != qwen_cleanup.get("job_scope_ref")
            or lease_or_owner.get("process_identity") != qwen_cleanup.get("server_process_identity")
            or termination.get("process_identity") != qwen_cleanup.get("server_process_identity")
            or termination.get("evidence_ref") != qwen_cleanup.get("termination_observation_ref")
        ):
            findings.append(
                _finding("actual_qwen_probe_lineage_mismatch", "failed", [str(probe["content_sha256"])])
            )
    for provider in _PROVIDERS:
        refs = [
            str(probe["content_sha256"])
            for probe in probes
            if probe.get("provider", {}).get("provider_id") == provider
        ]
        findings.append(_finding(f"actual_{provider}_probe_authority_missing", "failed", refs))
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
                "external_rows_by_sample": [],
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
        roles, owner_refs, parent_findings, digest_index = _load_parent_graph(owner_journal_paths)
        owners, cleanup_summary, lineage_findings, lineage, authorities = _derive_parent_facts(
            roles, digest_index
        )
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


def _attempt_sealed_parent(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{name} must be a sealed object")
    parent = deepcopy(dict(value))
    digest = parent.get("content_sha256")
    if not isinstance(digest, str) or _SHA_RE.fullmatch(digest) is None:
        raise ValueError(f"{name} content SHA is invalid")
    if content_sha256(parent) != digest:
        raise ValueError(f"{name} content SHA differs")
    return parent


def _validate_benchmark_v2_attempt_event(value: object) -> dict[str, Any]:
    event = _closed(value, _ATTEMPT_EVENT_FIELDS, "benchmark attempt event")
    if (
        event["contract_version"] != _ATTEMPT_EVENT_CONTRACT
        or event["artifact_is_authorization"] is not False
        or event["execute_binding_enabled"] is not False
        or event["content_sha256"] != content_sha256(event)
    ):
        raise ValueError("benchmark attempt event is invalid")
    sequence = event["sequence"]
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise ValueError("benchmark attempt event sequence is invalid")
    event["attempt_ref"] = _attempt_sealed_parent(
        event["attempt_ref"], "benchmark attempt ref"
    )
    phase = str(event["phase"] or "")
    kind = str(event["event_kind"] or "")
    if _ATTEMPT_EVENT_PHASE.get(kind) != phase:
        raise ValueError("benchmark attempt event phase or kind is invalid")
    provider = event["provider_id"]
    probe_kind = event["probe_kind"]
    provider_event = kind in {
        "provider_request_in_flight",
        "probe_triggered",
        "provider_body_complete",
    }
    if provider_event:
        if provider not in _PROVIDERS or probe_kind not in _PROBE_KINDS:
            raise ValueError("benchmark attempt provider or probe is invalid")
    elif provider is not None or probe_kind is not None:
        raise ValueError("benchmark non-provider event cannot name a probe")
    if event["resource_ref"] is not None:
        event["resource_ref"] = _attempt_sealed_parent(
            event["resource_ref"], "benchmark attempt resource ref"
        )
    predecessor = event["predecessor_content_sha256"]
    if predecessor is not None and (
        not isinstance(predecessor, str) or _SHA_RE.fullmatch(predecessor) is None
    ):
        raise ValueError("benchmark attempt predecessor SHA is invalid")
    return event


def read_benchmark_v2_attempt_journal(
    *, journal_path: Path, attempt_ref: Mapping[str, object]
) -> list[dict[str, Any]]:
    path = Path(journal_path)
    if not path.is_absolute() or path != path.resolve() or not path.is_file():
        raise ValueError("benchmark attempt journal is unavailable")
    attempt = _attempt_sealed_parent(attempt_ref, "benchmark attempt ref")
    raw = path.read_bytes()
    if not raw or not raw.endswith(b"\n"):
        raise ValueError("benchmark attempt journal is incomplete")
    events: list[dict[str, Any]] = []
    for raw_line in raw.splitlines():
        try:
            decoded = json.loads(
                raw_line.decode("utf-8"),
                object_pairs_hook=_json_pairs,
                parse_constant=_reject_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
            raise ValueError("benchmark attempt journal is corrupt") from error
        if canonical_json_bytes(decoded) != raw_line:
            raise ValueError("benchmark attempt journal is not canonical")
        event = _validate_benchmark_v2_attempt_event(decoded)
        expected_sequence = len(events) + 1
        expected_predecessor = (
            events[-1]["content_sha256"] if events else None
        )
        if (
            event["sequence"] != expected_sequence
            or event["predecessor_content_sha256"] != expected_predecessor
            or event["attempt_ref"] != attempt
        ):
            raise ValueError("benchmark attempt journal chain or attempt differs")
        if events and _ATTEMPT_PHASES[event["phase"]] < _ATTEMPT_PHASES[
            events[-1]["phase"]
        ]:
            raise ValueError("benchmark attempt journal phase regressed")
        if events and events[-1]["phase"] == "terminal":
            raise ValueError("benchmark attempt journal continued after terminal")
        events.append(event)
    return events


def append_benchmark_v2_attempt_event(
    *,
    journal_path: Path,
    attempt_ref: Mapping[str, object],
    phase: str,
    event_kind: str,
    provider_id: str | None = None,
    probe_kind: str | None = None,
    resource_ref: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    path = Path(journal_path)
    if not path.is_absolute() or path != path.resolve():
        raise ValueError("benchmark attempt journal path must be canonical")
    attempt = _attempt_sealed_parent(attempt_ref, "benchmark attempt ref")
    with _ATTEMPT_JOURNAL_LOCK:
        events = (
            read_benchmark_v2_attempt_journal(
                journal_path=path,
                attempt_ref=attempt,
            )
            if path.exists()
            else []
        )
        normalized_resource = (
            _attempt_sealed_parent(resource_ref, "benchmark attempt resource ref")
            if resource_ref is not None
            else None
        )
        idempotency = {
            "phase": phase,
            "event_kind": event_kind,
            "provider_id": provider_id,
            "probe_kind": probe_kind,
            "resource_ref": normalized_resource,
        }
        if events:
            last = events[-1]
            if all(last[name] == value for name, value in idempotency.items()):
                return deepcopy(last)
            if last["phase"] == "terminal":
                raise ValueError("benchmark attempt is already terminal")
            if _ATTEMPT_PHASES.get(phase, -1) < _ATTEMPT_PHASES[last["phase"]]:
                raise ValueError("benchmark attempt journal phase regressed")
        body: dict[str, Any] = {
            "contract_version": _ATTEMPT_EVENT_CONTRACT,
            "sequence": len(events) + 1,
            "attempt_ref": attempt,
            "phase": phase,
            "event_kind": event_kind,
            "provider_id": provider_id,
            "probe_kind": probe_kind,
            "resource_ref": normalized_resource,
            "predecessor_content_sha256": (
                events[-1]["content_sha256"] if events else None
            ),
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
        body["content_sha256"] = content_sha256(body)
        event = _validate_benchmark_v2_attempt_event(body)
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = canonical_json_bytes(event) + b"\n"
        with path.open("ab") as stream:
            written = stream.write(raw)
            if written != len(raw):
                raise OSError("benchmark attempt journal short write")
            os.fsync(stream.fileno())
        return event


def compose_benchmark_v2_attempt_cleanup_receipt(
    *,
    attempt_ref: Mapping[str, object],
    reason: str,
    service_terminal_ref: Mapping[str, object] | None,
    window_cleanup_ref: Mapping[str, object] | None,
    provider_cleanup_refs: list[Mapping[str, object]],
    resource_counts: Mapping[str, int],
) -> dict[str, Any]:
    attempt = _attempt_sealed_parent(attempt_ref, "benchmark attempt ref")
    normalized_reason = str(reason or "").strip()
    if not normalized_reason:
        raise ValueError("benchmark cleanup reason is invalid")
    counts = dict(resource_counts)
    required_counts = {
        "service_operations",
        "windows",
        "providers",
        "listeners",
        "leases",
    }
    if set(counts) != required_counts or any(
        isinstance(value, bool) or not isinstance(value, int) or value != 0
        for value in counts.values()
    ):
        raise ValueError("benchmark cleanup resource counts are not stable-zero")
    if not isinstance(provider_cleanup_refs, list):
        raise ValueError("benchmark provider cleanup refs must be a list")
    body: dict[str, Any] = {
        "contract_version": _ATTEMPT_CLEANUP_CONTRACT,
        "attempt_ref": attempt,
        "reason": normalized_reason,
        "service_terminal_ref": (
            _attempt_sealed_parent(service_terminal_ref, "service terminal ref")
            if service_terminal_ref is not None
            else None
        ),
        "window_cleanup_ref": (
            _attempt_sealed_parent(window_cleanup_ref, "window cleanup ref")
            if window_cleanup_ref is not None
            else None
        ),
        "provider_cleanup_refs": [
            _attempt_sealed_parent(item, "provider cleanup ref")
            for item in provider_cleanup_refs
        ],
        "resource_counts": counts,
        "cleanup_status": "stable_zero",
        "lost_response_policy": "fresh_reconcile_safe_stop_no_blind_retry",
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    body["content_sha256"] = content_sha256(body)
    return body


def _s13_public_attempt_ref(value: object) -> dict[str, str]:
    attempt = _attempt_sealed_parent(value, "benchmark v2 runner attempt ref")
    expected = {
        "contract_version",
        "attempt_id",
        "partition",
        "mode",
        "provider_id",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    attempt_id = attempt.get("attempt_id")
    if (
        set(attempt) != expected
        or attempt.get("contract_version") != "benchmark_v2_runner_attempt_ref_v1"
        or not isinstance(attempt_id, str)
        or not attempt_id
        or attempt.get("partition") != "regression"
        or attempt.get("mode") != "actual_models"
        or attempt.get("provider_id") is not None
        or attempt.get("artifact_is_authorization") is not False
        or attempt.get("execute_binding_enabled") is not False
    ):
        raise ValueError("benchmark v2 runner attempt ref is invalid")
    return {
        "id": f"runner-attempt/{attempt_id}",
        "content_sha256": str(attempt["content_sha256"]),
    }


def _s13_cleanup_receipt(
    value: object, *, attempt_ref: Mapping[str, object] | None = None
) -> dict[str, Any]:
    receipt = _attempt_sealed_parent(value, "benchmark v2 cleanup receipt")
    expected = {
        "contract_version",
        "attempt_ref",
        "reason",
        "service_terminal_ref",
        "window_cleanup_ref",
        "provider_cleanup_refs",
        "resource_counts",
        "cleanup_status",
        "lost_response_policy",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    if (
        set(receipt) != expected
        or receipt.get("contract_version") != _ATTEMPT_CLEANUP_CONTRACT
        or not isinstance(receipt.get("reason"), str)
        or not str(receipt["reason"]).strip()
        or receipt.get("cleanup_status") != "stable_zero"
        or receipt.get("lost_response_policy")
        != "fresh_reconcile_safe_stop_no_blind_retry"
        or receipt.get("resource_counts") != _S13_ZERO_COUNTS
        or receipt.get("artifact_is_authorization") is not False
        or receipt.get("execute_binding_enabled") is not False
        or not isinstance(receipt.get("provider_cleanup_refs"), list)
    ):
        raise ValueError("benchmark v2 cleanup receipt is invalid")
    raw_attempt = receipt.get("attempt_ref")
    _s13_public_attempt_ref(raw_attempt)
    if attempt_ref is not None and dict(raw_attempt) != dict(attempt_ref):
        raise ValueError("benchmark v2 cleanup receipt attempt differs")
    for name in ("service_terminal_ref", "window_cleanup_ref"):
        parent = receipt.get(name)
        if parent is not None:
            _attempt_sealed_parent(parent, f"benchmark v2 cleanup receipt {name}")
    for parent in receipt["provider_cleanup_refs"]:
        _attempt_sealed_parent(parent, "benchmark v2 cleanup receipt provider ref")
    return receipt


def derive_benchmark_v2_cleanup_receipt_ref(
    *, cleanup_receipt: Mapping[str, object]
) -> dict[str, str]:
    """从已重新验证的 cleanup receipt 派生不可解析的公开引用。"""

    receipt = _s13_cleanup_receipt(cleanup_receipt)
    raw = canonical_json_bytes(receipt)
    return {
        "id": "attempt-cleanup-receipt/"
        + hashlib.sha256(
            b"benchmark-v2-attempt-cleanup-receipt\0" + raw
        ).hexdigest(),
        "content_sha256": hashlib.sha256(raw).hexdigest(),
    }


def project_benchmark_v2_cleanup_lifecycle(
    *,
    attempt_ref: Mapping[str, object],
    cleanup_receipt: Mapping[str, object],
) -> dict[str, object]:
    """把原始稳定零 cleanup receipt 投影成无路径 lifecycle 证据。"""

    public_attempt_ref = _s13_public_attempt_ref(attempt_ref)
    receipt = _s13_cleanup_receipt(cleanup_receipt, attempt_ref=attempt_ref)
    cleanup_ref = derive_benchmark_v2_cleanup_receipt_ref(
        cleanup_receipt=receipt
    )
    from app.learn.hybrid.benchmark_v2_pathless import seal_pathless_projection

    return seal_pathless_projection(
        contract_version="benchmark_v2_lifecycle_verified_projection_v1",
        semantic_payload={
            "attempt_ref": public_attempt_ref,
            "lifecycle_kind": "cleanup",
            "raw_evidence_sha256": hashlib.sha256(
                canonical_json_bytes(receipt)
            ).hexdigest(),
            "terminal_status": "stable_zero",
            "cleanup_stable_zero": True,
            "resource_counts": deepcopy(_S13_ZERO_COUNTS),
            "started_request_count": 0,
            "terminal_or_unknown_request_count": 0,
            "parent_refs": {"cleanup_receipt_ref": cleanup_ref},
            "safety": deepcopy(_S13_SAFETY),
        },
    )


def _s13_pathless_projection_ref(
    value: Mapping[str, object], *, contract_version: str
) -> dict[str, str]:
    from app.learn.hybrid.benchmark_v2_pathless import (
        pathless_artifact_ref,
        seal_pathless_envelope,
    )

    if value.get("contract_version") != contract_version:
        raise ValueError("benchmark v2 pathless projection contract differs")
    seal_pathless_envelope(value)
    return pathless_artifact_ref(value)


def _s13_attempt_journal_events(
    values: Sequence[Mapping[str, object]],
    *,
    attempt_ref: Mapping[str, object],
    forbid_provider_events: bool,
) -> list[dict[str, Any]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or not values:
        raise ValueError("benchmark v2 attempt journal is unavailable")
    raw_attempt = _attempt_sealed_parent(attempt_ref, "benchmark v2 runner attempt ref")
    result: list[dict[str, Any]] = []
    forbidden = {
        "provider_request_in_flight",
        "probe_triggered",
        "provider_body_complete",
    }
    for raw in values:
        event = _validate_benchmark_v2_attempt_event(raw)
        expected_sequence = len(result) + 1
        expected_predecessor = result[-1]["content_sha256"] if result else None
        if (
            event["sequence"] != expected_sequence
            or event["predecessor_content_sha256"] != expected_predecessor
            or event["attempt_ref"] != raw_attempt
            or (forbid_provider_events and event["event_kind"] in forbidden)
        ):
            raise ValueError("benchmark v2 attempt journal chain differs")
        if result and result[-1]["phase"] == "terminal":
            raise ValueError("benchmark v2 attempt journal continued after terminal")
        result.append(event)
    if result[-1]["phase"] != "terminal" or result[-1]["event_kind"] != "attempt_terminal":
        raise ValueError("benchmark v2 attempt journal is not terminal")
    return result


def project_benchmark_v2_attempt_journal_terminal_event(
    *,
    attempt_ref: Mapping[str, object],
    journal_events: Sequence[Mapping[str, object]],
    cleanup_receipt: Mapping[str, object],
    cleanup_projection: Mapping[str, object],
) -> dict[str, object]:
    """投影 attempt journal 的唯一终态事件，不公开嵌入的 receipt。"""

    public_attempt_ref = _s13_public_attempt_ref(attempt_ref)
    receipt = _s13_cleanup_receipt(cleanup_receipt, attempt_ref=attempt_ref)
    events = _s13_attempt_journal_events(
        journal_events,
        attempt_ref=attempt_ref,
        forbid_provider_events=False,
    )
    terminal = events[-1]
    resource = _attempt_sealed_parent(
        terminal.get("resource_ref"), "benchmark v2 terminal cleanup resource"
    )
    if (
        set(resource)
        != {
            "contract_version",
            "resource_kind",
            "value",
            "artifact_is_authorization",
            "execute_binding_enabled",
            "content_sha256",
        }
        or resource.get("contract_version") != "benchmark_v2_runtime_resource_ref_v1"
        or resource.get("resource_kind") != "attempt_cleanup_receipt"
        or resource.get("artifact_is_authorization") is not False
        or resource.get("execute_binding_enabled") is not False
        or not isinstance(resource.get("value"), Mapping)
        or set(resource["value"]) != {"cleanup_receipt"}
        or resource["value"].get("cleanup_receipt") != receipt
    ):
        raise ValueError("benchmark v2 terminal cleanup receipt differs")
    cleanup_ref = derive_benchmark_v2_cleanup_receipt_ref(cleanup_receipt=receipt)
    cleanup_projection_ref = _s13_pathless_projection_ref(
        cleanup_projection,
        contract_version="benchmark_v2_lifecycle_verified_projection_v1",
    )
    expected_cleanup_projection = {
        "attempt_ref": public_attempt_ref,
        "lifecycle_kind": "cleanup",
        "raw_evidence_sha256": hashlib.sha256(
            canonical_json_bytes(receipt)
        ).hexdigest(),
        "terminal_status": "stable_zero",
        "cleanup_stable_zero": True,
        "resource_counts": _S13_ZERO_COUNTS,
        "started_request_count": 0,
        "terminal_or_unknown_request_count": 0,
        "parent_refs": {"cleanup_receipt_ref": cleanup_ref},
        "safety": _S13_SAFETY,
    }
    if any(cleanup_projection.get(key) != value for key, value in expected_cleanup_projection.items()):
        raise ValueError("benchmark v2 cleanup lifecycle projection differs")
    from app.learn.hybrid.benchmark_v2_pathless import seal_pathless_projection

    return seal_pathless_projection(
        contract_version="benchmark_v2_attempt_journal_terminal_event_verified_projection_v1",
        semantic_payload={
            "attempt_ref": public_attempt_ref,
            "sequence": int(terminal["sequence"]),
            "phase": "terminal",
            "event_kind": "attempt_terminal",
            "raw_event_sha256": hashlib.sha256(
                canonical_json_bytes(terminal)
            ).hexdigest(),
            "predecessor_content_sha256": str(
                terminal["predecessor_content_sha256"]
            ),
            "cleanup_receipt_ref": cleanup_ref,
            "cleanup_projection_ref": cleanup_projection_ref,
            "safety": deepcopy(_S13_SAFETY),
        },
    )


def _s13_exact_ref(value: object, name: str) -> dict[str, str]:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"id", "content_sha256"}
        or not isinstance(value.get("id"), str)
        or not value["id"]
        or not isinstance(value.get("content_sha256"), str)
        or _SHA_RE.fullmatch(str(value["content_sha256"])) is None
    ):
        raise ValueError(f"{name} is invalid")
    return {"id": str(value["id"]), "content_sha256": str(value["content_sha256"])}


_S13_RELEASE_ID = "portfolio_hybrid_v1_1_benchmark_v2_release_1"
_S13_ARMS = (
    "qwen_only",
    "omni_only_discovery",
    "omni_to_qwen",
    "omni_to_qwen_vista",
)


def _s13_pre_vista_envelope(
    value: object,
    *,
    field_name: str,
    id_prefix: str,
    domain: bytes,
    contract_version: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"ref", "canonical_bytes_b64"}:
        raise ValueError(f"benchmark v2 {field_name} envelope is invalid")
    ref = _s13_exact_ref(value.get("ref"), f"benchmark v2 {field_name} ref")
    encoded = value.get("canonical_bytes_b64")
    if not isinstance(encoded, str) or not encoded:
        raise ValueError(f"benchmark v2 {field_name} bytes are invalid")
    try:
        raw = base64.b64decode(encoded, validate=True)
        decoded = json.loads(raw.decode("utf-8"))
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError(f"benchmark v2 {field_name} bytes are invalid") from None
    from app.learn.hybrid.benchmark_v2_contracts import (
        canonical_json_bytes as benchmark_canonical_json_bytes,
    )

    if (
        not isinstance(decoded, dict)
        or benchmark_canonical_json_bytes(decoded) != raw
        or decoded.get("contract_version") != contract_version
        or ref
        != {
            "id": f"{id_prefix}/{hashlib.sha256(domain + raw).hexdigest()}",
            "content_sha256": hashlib.sha256(raw).hexdigest(),
        }
    ):
        raise ValueError(f"benchmark v2 {field_name} envelope differs")
    return deepcopy(decoded)


def _s13_pre_vista_parent(
    value: object,
    *,
    provider_group_ref: Mapping[str, object],
    hybrid_capture_bundle_ref: Mapping[str, object],
) -> dict[str, Any]:
    evidence = _attempt_sealed_parent(value, "benchmark v2 pre-VISTA evidence")
    if (
        set(evidence)
        != {
            "contract_version",
            "provider_group_ref",
            "omni_inventory_envelope",
            "qwen_bindings_envelope",
            "fusion_result_envelope",
            "submitted_vista_request_envelopes",
            "safety",
            "content_sha256",
        }
        or evidence.get("contract_version")
        != "benchmark_v2_actual_pre_vista_evidence_v1"
        or evidence.get("provider_group_ref") != dict(provider_group_ref)
        or evidence.get("safety")
        != {
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    ):
        raise ValueError("benchmark v2 pre-VISTA evidence or provider group differs")
    raw_omni = _s13_pre_vista_envelope(
        evidence["omni_inventory_envelope"],
        field_name="Omni inventory",
        id_prefix="omni-inventory",
        domain=b"benchmark-v2-omni-inventory\0",
        contract_version="hybrid_omni_inventory_v1",
    )
    raw_qwen = _s13_pre_vista_envelope(
        evidence["qwen_bindings_envelope"],
        field_name="Qwen bindings",
        id_prefix="qwen-bindings",
        domain=b"benchmark-v2-qwen-bindings\0",
        contract_version="hybrid_qwen_bindings_v1",
    )
    raw_fusion = _s13_pre_vista_envelope(
        evidence["fusion_result_envelope"],
        field_name="fusion result",
        id_prefix="fusion-result",
        domain=b"benchmark-v2-fusion-result\0",
        contract_version="hybrid_fusion_result_v1",
    )
    raw_requests = evidence.get("submitted_vista_request_envelopes")
    if not isinstance(raw_requests, list):
        raise ValueError("benchmark v2 submitted VISTA request envelopes are invalid")
    raw_requests_decoded = [
        _s13_pre_vista_envelope(
            item,
            field_name="submitted VISTA request",
            id_prefix="submitted-vista-request",
            domain=b"benchmark-v2-submitted-vista-request\0",
            contract_version="hybrid_vista_refinement_request_v1",
        )
        for item in raw_requests
    ]

    def unseal_provider(item: Mapping[str, object], name: str) -> dict[str, object]:
        current = deepcopy(dict(item))
        declared = current.pop("content_sha256", None)
        if (
            not isinstance(declared, str)
            or _SHA_RE.fullmatch(declared) is None
            or declared != content_sha256(dict(item))
        ):
            raise ValueError(f"benchmark v2 {name} sealed identity differs")
        return current

    try:
        from app.learn.hybrid.contracts import (
            validate_fusion_result,
            validate_omni_inventory,
            validate_qwen_bindings,
        )
        from app.learn.hybrid.vista_refinement import _validated_request

        omni = validate_omni_inventory(unseal_provider(raw_omni, "Omni inventory"))
        qwen = validate_qwen_bindings(
            unseal_provider(raw_qwen, "Qwen bindings"), omni
        )
        fusion = validate_fusion_result(
            unseal_provider(raw_fusion, "fusion result"), omni, qwen
        )
        requests = [_validated_request(item) for item in raw_requests_decoded]
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"benchmark v2 pre-VISTA closed provider validation failed: {exc}"
        ) from exc

    capture = fusion.get("capture_identity")
    if (
        not isinstance(capture, Mapping)
        or capture != omni.get("capture_identity")
        or capture != qwen.get("capture_identity")
        or not isinstance(capture.get("workflow_revision"), str)
        or not str(capture["workflow_revision"]).isdigit()
    ):
        raise ValueError("benchmark v2 pre-VISTA capture/workflow lineage differs")
    expected_parent_refs = {
        "fusion_result": {
            "id": "fusion_result",
            "content_sha256": str(raw_fusion["content_sha256"]),
        },
        "capture_bundle": dict(hybrid_capture_bundle_ref),
        "omni_inventory": {
            "id": "omni_inventory",
            "content_sha256": str(raw_omni["content_sha256"]),
        },
        "qwen_bindings": {
            "id": "qwen_bindings",
            "content_sha256": str(raw_qwen["content_sha256"]),
        },
    }
    cleanup_hashes: set[str] = set()
    for request in requests:
        cleanup = request.get("qwen_cleanup_receipt")
        if not isinstance(cleanup, Mapping):
            raise ValueError("benchmark v2 submitted VISTA cleanup lineage is missing")
        cleanup_hashes.add(str(cleanup.get("content_sha256") or ""))
        if (
            request.get("authoritative_parent_refs") != expected_parent_refs
            or request.get("capture_id") != capture.get("capture_id")
            or request.get("capture_sha256") != capture.get("screenshot_sha256")
            or request.get("capture_image_size") != capture.get("image_size")
            or request.get("capture_lineage_ref")
            != capture.get("capture_lineage_ref")
            or request.get("source_revision") != fusion.get("config_sha256")
        ):
            raise ValueError("benchmark v2 submitted VISTA parent lineage differs")
    if requests and (
        len(cleanup_hashes) != 1
        or any(_SHA_RE.fullmatch(value) is None for value in cleanup_hashes)
    ):
        raise ValueError("benchmark v2 submitted VISTA cleanup lineage differs")
    candidates = fusion.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("benchmark v2 fusion candidates are invalid")
    bound_ids = [
        str(item.get("candidate_id"))
        for item in candidates
        if isinstance(item, Mapping) and item.get("state") == "BOUND"
    ]
    request_ids = [
        str(item.get("candidate_id"))
        for item in requests
        if item.get("submission_status") == "SUBMITTED"
    ]
    if (
        any(not value or value == "None" for value in [*bound_ids, *request_ids])
        or len(bound_ids) != len(set(bound_ids))
        or len(request_ids) != len(set(request_ids))
        or request_ids != sorted(request_ids)
        or request_ids != sorted(bound_ids)
    ):
        raise ValueError("benchmark v2 submitted VISTA request coverage differs")
    return evidence


def _s13_window_close_parent(value: object) -> dict[str, Any]:
    receipt = _attempt_sealed_parent(value, "benchmark v2 screen group window close ref")
    if (
        set(receipt) != _TASK4_CLEANUP_FIELDS
        or receipt.get("contract_version")
        != "portfolio_hybrid_benchmark_v2_window_cleanup_v1"
        or receipt.get("cleanup_status") != "verified"
        or receipt.get("shutdown_event_signaled") is not True
        or receipt.get("shutdown_event_error_code") != 0
        or receipt.get("shutdown_event_handle_closed") is not True
        or receipt.get("enum_windows_exact_hwnd_absent") is not True
        or receipt.get("matching_owned_windows_after") != []
        or receipt.get("member_pids_after") != []
        or not isinstance(receipt.get("stable_zero_observations"), int)
        or isinstance(receipt.get("stable_zero_observations"), bool)
        or int(receipt["stable_zero_observations"]) < 2
        or receipt.get("scope_absent_after_owner_close") is not True
        or receipt.get("process_handle_closed") is not True
        or receipt.get("job_handle_closed") is not True
        or receipt.get("active_listeners_after") != []
        or receipt.get("listener_or_lease_residue") != []
        or receipt.get("outer_owner_python_finally_observed") is not True
        or receipt.get("artifact_is_authorization") is not False
        or receipt.get("execute_binding_enabled") is not False
    ):
        raise ValueError("benchmark v2 screen group window close receipt differs")
    return receipt


def _s13_service_stable_zero_parent(
    value: object,
    *,
    request_ref: Mapping[str, object],
    case_refs: Sequence[Mapping[str, object]],
    window_binding_ref: Mapping[str, object],
    capture_ref: Mapping[str, object],
    execution_refs: Sequence[Mapping[str, object]],
) -> dict[str, Any]:
    receipt = _attempt_sealed_parent(
        value, "benchmark v2 service stable-zero attestation"
    )
    if (
        set(receipt)
        != {
            "contract_version",
            "operation_refs",
            "cleanup_entries",
            "window_binding_ref",
            "capture_ref",
            "cleanup_status",
            "artifact_is_authorization",
            "execute_binding_enabled",
            "content_sha256",
        }
        or receipt.get("contract_version")
        != "benchmark_v2_actual_operations_stable_zero_v1"
        or receipt.get("window_binding_ref") != dict(window_binding_ref)
        or receipt.get("capture_ref") != dict(capture_ref)
        or receipt.get("cleanup_status") != "stable_zero"
        or receipt.get("artifact_is_authorization") is not False
        or receipt.get("execute_binding_enabled") is not False
    ):
        raise ValueError("benchmark v2 service stable-zero attestation differs")
    raw_operations = receipt.get("operation_refs")
    raw_entries = receipt.get("cleanup_entries")
    if (
        not isinstance(raw_operations, list)
        or len(raw_operations) != 6
        or not isinstance(raw_entries, list)
        or len(raw_entries) != 6
    ):
        raise ValueError("benchmark v2 service stable-zero operation set differs")
    operations = [
        _attempt_sealed_parent(item, "benchmark v2 service operation ref")
        for item in raw_operations
    ]
    derived_execution_refs: list[dict[str, str]] = []
    hybrid_count = 0
    incumbent_requests: list[dict[str, str]] = []
    for operation in operations:
        mode = operation.get("mode")
        operation_id = operation.get("operation_id")
        status = operation.get("status")
        if (
            mode not in {"hybrid_v1_1", "incumbent_qwen_only"}
            or not isinstance(operation_id, str)
            or not operation_id
            or operation.get("window_binding_ref") != dict(window_binding_ref)
            or operation.get("capture_ref") != dict(capture_ref)
        ):
            raise ValueError("benchmark v2 service operation lineage differs")
        operation_request = _s13_exact_ref(
            operation.get("request_ref"), "benchmark v2 service operation request ref"
        )
        if mode == "hybrid_v1_1":
            hybrid_count += 1
            if status not in {"complete", "safe_stopped"} or operation_request != dict(
                request_ref
            ):
                raise ValueError("benchmark v2 Hybrid operation lineage differs")
        else:
            if status not in {"complete", "cancelled"}:
                raise ValueError("benchmark v2 incumbent operation is not terminal")
            incumbent_requests.append(operation_request)
        derived_execution_refs.append(
            {
                "id": f"{mode}/{operation_id}",
                "content_sha256": str(operation["content_sha256"]),
            }
        )
    expected_case_requests = [
        {
            "id": str(item["case_id"]),
            "content_sha256": str(item["case_content_sha256"]),
        }
        for item in case_refs
    ]
    if (
        hybrid_count != 1
        or sorted(
            incumbent_requests, key=lambda item: (item["id"], item["content_sha256"])
        )
        != sorted(
            expected_case_requests,
            key=lambda item: (item["id"], item["content_sha256"]),
        )
        or derived_execution_refs != list(execution_refs)
    ):
        raise ValueError("benchmark v2 service operation multiset differs")
    operation_hashes = {str(item["content_sha256"]) for item in operations}
    cleanup_hashes: list[str] = []
    for raw_entry in raw_entries:
        if (
            not isinstance(raw_entry, Mapping)
            or set(raw_entry)
            != {
                "operation_ref_sha256",
                "terminal_receipt_ref",
                "worker_cleanup_ref",
                "provider_cleanup_ref",
            }
            or raw_entry.get("operation_ref_sha256") not in operation_hashes
        ):
            raise ValueError("benchmark v2 service cleanup entry differs")
        cleanup_hashes.append(str(raw_entry["operation_ref_sha256"]))
        for field in (
            "terminal_receipt_ref",
            "worker_cleanup_ref",
            "provider_cleanup_ref",
        ):
            _attempt_sealed_parent(
                raw_entry.get(field), f"benchmark v2 service cleanup {field}"
            )
    if len(set(cleanup_hashes)) != 6:
        raise ValueError("benchmark v2 service cleanup entries are duplicated")
    return receipt


def _s13_screen_group_parent(
    value: object, *, attempt_ref: Mapping[str, object]
) -> tuple[str, dict[str, Any], dict[str, str], dict[str, str]]:
    projection = _attempt_sealed_parent(value, "benchmark v2 actual screen group projection")
    expected = {
        "contract_version",
        "benchmark_release_id",
        "partition",
        "screen_group",
        "request_ref",
        "shared_parent_refs",
        "pre_vista_evidence",
        "rows",
        "execution_refs",
        "window_close_ref",
        "lifecycle_ref",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    screen_group = projection.get("screen_group")
    shared = projection.get("shared_parent_refs")
    executions = projection.get("execution_refs")
    if (
        set(projection) != expected
        or projection.get("contract_version")
        != "benchmark_v2_actual_screen_group_projection_v1"
        or projection.get("benchmark_release_id") != _S13_RELEASE_ID
        or projection.get("partition") != "regression"
        or not isinstance(screen_group, str)
        or not screen_group
        or projection.get("artifact_is_authorization") is not False
        or projection.get("execute_binding_enabled") is not False
        or not isinstance(shared, Mapping)
        or set(shared)
        != {
            "screen_group_ref",
            "hybrid_capture_bundle_ref",
            "window_binding_ref",
            "capture_ref",
            "owner_journal_ref",
            "expected_uia_root_ref",
        }
        or not isinstance(projection.get("rows"), list)
        or len(projection["rows"]) != 20
        or not isinstance(executions, list)
        or len(executions) != 6
    ):
        raise ValueError("benchmark v2 actual screen group projection is invalid")
    normalized_executions = [
        _s13_exact_ref(item, "benchmark v2 screen group execution ref")
        for item in executions
    ]
    if (
        len({(item["id"], item["content_sha256"]) for item in normalized_executions})
        != 6
        or not normalized_executions[0]["id"].startswith("hybrid_v1_1/")
        or any(
            not item["id"].startswith("incumbent_qwen_only/")
            for item in normalized_executions[1:]
        )
    ):
        raise ValueError("benchmark v2 screen group execution refs are incomplete")
    request_ref = _s13_exact_ref(
        projection.get("request_ref"), "benchmark v2 screen group request ref"
    )
    normalized_shared = {
        "screen_group_ref": _s13_exact_ref(
            shared.get("screen_group_ref"), "benchmark v2 shared screen group ref"
        ),
        "hybrid_capture_bundle_ref": _s13_exact_ref(
            shared.get("hybrid_capture_bundle_ref"),
            "benchmark v2 shared capture bundle ref",
        ),
        "window_binding_ref": _s13_exact_ref(
            shared.get("window_binding_ref"),
            "benchmark v2 shared window binding ref",
        ),
        "capture_ref": _s13_exact_ref(
            shared.get("capture_ref"), "benchmark v2 shared capture ref"
        ),
        "owner_journal_ref": _attempt_sealed_parent(
            shared.get("owner_journal_ref"), "benchmark v2 shared owner journal ref"
        ),
        "expected_uia_root_ref": _attempt_sealed_parent(
            shared.get("expected_uia_root_ref"),
            "benchmark v2 shared expected UIA root ref",
        ),
    }
    if dict(shared) != normalized_shared:
        raise ValueError("benchmark v2 shared parent refs differ")
    shared_group_ref = normalized_shared["screen_group_ref"]
    if shared_group_ref["id"] != screen_group:
        raise ValueError("benchmark v2 shared screen group identity differs")
    evidence = _s13_pre_vista_parent(
        projection.get("pre_vista_evidence"),
        provider_group_ref=shared_group_ref,
        hybrid_capture_bundle_ref=normalized_shared["hybrid_capture_bundle_ref"],
    )
    provider_group_ref = _s13_exact_ref(
        evidence.get("provider_group_ref"), "benchmark v2 provider group ref"
    )
    if provider_group_ref != shared_group_ref:
        raise ValueError("benchmark v2 provider group lineage differs")

    rows = projection["rows"]
    case_order: list[dict[str, str]] = []
    row_pairs: list[tuple[str, str]] = []
    incumbent_execution_by_case: dict[str, dict[str, str]] = {}
    expected_dispatch_providers = {
        "qwen_only": {"qwen"},
        "omni_only_discovery": {"omni"},
        "omni_to_qwen": {"omni", "qwen"},
        "omni_to_qwen_vista": {"omni", "qwen", "vista"},
    }
    for row in rows:
        if (
            not isinstance(row, Mapping)
            or set(row)
            != {
                "case_ref",
                "arm_id",
                "observation",
                "execution_ref",
                "shared_parent_refs",
                "artifact_is_authorization",
                "execute_binding_enabled",
            }
            or row.get("arm_id") not in _S13_ARMS
            or row.get("shared_parent_refs") != normalized_shared
            or row.get("artifact_is_authorization") is not False
            or row.get("execute_binding_enabled") is not False
        ):
            raise ValueError("benchmark v2 screen group row is invalid")
        case = row.get("case_ref")
        if (
            not isinstance(case, Mapping)
            or set(case) != {"case_id", "case_content_sha256"}
            or not isinstance(case.get("case_id"), str)
            or not case["case_id"]
            or _SHA_RE.fullmatch(str(case.get("case_content_sha256") or "")) is None
        ):
            raise ValueError("benchmark v2 screen group case ref is invalid")
        case_ref = {
            "case_id": str(case["case_id"]),
            "case_content_sha256": str(case["case_content_sha256"]),
        }
        if case_ref not in case_order:
            case_order.append(case_ref)
        arm_id = str(row["arm_id"])
        row_pairs.append((case_ref["case_id"], arm_id))
        execution = _s13_exact_ref(
            row.get("execution_ref"), "benchmark v2 row execution ref"
        )
        if execution not in normalized_executions:
            raise ValueError("benchmark v2 row execution ref is stale")
        if arm_id == "qwen_only":
            if not execution["id"].startswith("incumbent_qwen_only/"):
                raise ValueError("benchmark v2 incumbent row execution differs")
            incumbent_execution_by_case[case_ref["case_id"]] = execution
        elif execution != normalized_executions[0]:
            raise ValueError("benchmark v2 Hybrid row execution differs")
        observation = row.get("observation")
        receipts = (
            observation.get("provider_dispatch_receipt_refs")
            if isinstance(observation, Mapping)
            else None
        )
        if not isinstance(receipts, list) or not receipts:
            raise ValueError("benchmark v2 row dispatch evidence is missing")
        providers: set[str] = set()
        for receipt in receipts:
            if (
                not isinstance(receipt, Mapping)
                or not isinstance(receipt.get("provider"), str)
                or _SHA_RE.fullmatch(
                    str(receipt.get("content_sha256") or "")
                )
                is None
            ):
                raise ValueError("benchmark v2 row dispatch evidence is invalid")
            providers.add(str(receipt["provider"]))
        if (
            providers != expected_dispatch_providers[arm_id]
            or len(receipts) != len(providers)
        ):
            raise ValueError("benchmark v2 row provider dispatch coverage differs")
    expected_pairs = {
        (case["case_id"], arm_id) for case in case_order for arm_id in _S13_ARMS
    }
    if (
        len(case_order) != 5
        or len(set(row_pairs)) != 20
        or set(row_pairs) != expected_pairs
        or list(incumbent_execution_by_case.values()) != normalized_executions[1:]
    ):
        raise ValueError("benchmark v2 screen group case-arm multiset differs")

    close_ref = _s13_window_close_parent(projection.get("window_close_ref"))
    stable = _attempt_sealed_parent(
        projection.get("lifecycle_ref"), "benchmark v2 raw screen group lifecycle"
    )
    stable_expected = {
        "contract_version",
        "attempt_ref",
        "provider_group_ref",
        "window_binding_ref",
        "execution_refs",
        "window_close_ref",
        "service_stable_zero_attestation",
        "diagnostic_resource_counts",
        "cleanup_status",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    if (
        set(stable) != stable_expected
        or stable.get("contract_version") != "benchmark_v2_actual_stable_zero_v1"
        or stable.get("attempt_ref") != dict(attempt_ref)
        or stable.get("provider_group_ref") != provider_group_ref
        or stable.get("window_binding_ref") != normalized_shared["window_binding_ref"]
        or stable.get("execution_refs") != normalized_executions
        or stable.get("window_close_ref") != close_ref
        or projection.get("window_close_ref") != close_ref
        or stable.get("diagnostic_resource_counts") != _S13_ZERO_COUNTS
        or stable.get("cleanup_status") != "stable_zero"
        or stable.get("artifact_is_authorization") is not False
        or stable.get("execute_binding_enabled") is not False
    ):
        raise ValueError("benchmark v2 raw screen group lifecycle differs")
    _s13_service_stable_zero_parent(
        stable.get("service_stable_zero_attestation"),
        request_ref=request_ref,
        case_refs=case_order,
        window_binding_ref=normalized_shared["window_binding_ref"],
        capture_ref=normalized_shared["capture_ref"],
        execution_refs=normalized_executions,
    )
    actual_screen_group_ref = {
        "id": str(screen_group),
        "content_sha256": str(projection["content_sha256"]),
    }
    return str(screen_group), stable, actual_screen_group_ref, provider_group_ref


def project_benchmark_v2_screen_group_lifecycles(
    *,
    attempt_ref: Mapping[str, object],
    screen_group_projections: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """重验并按 Unicode code-point 顺序投影 12 个 screen-group 生命周期。"""

    public_attempt_ref = _s13_public_attempt_ref(attempt_ref)
    if (
        not isinstance(screen_group_projections, Sequence)
        or isinstance(screen_group_projections, (str, bytes))
        or len(screen_group_projections) != 12
    ):
        raise ValueError("benchmark v2 requires 12 unique screen groups")
    parents = [
        _s13_screen_group_parent(item, attempt_ref=attempt_ref)
        for item in screen_group_projections
    ]
    ids = [item[0] for item in parents]
    if len(set(ids)) != 12:
        raise ValueError("benchmark v2 requires 12 unique screen groups")
    from app.learn.hybrid.benchmark_v2_pathless import seal_pathless_projection

    result: list[dict[str, object]] = []
    for _, stable, actual_ref, provider_ref in sorted(parents, key=lambda item: item[0]):
        result.append(
            seal_pathless_projection(
                contract_version="benchmark_v2_lifecycle_verified_projection_v1",
                semantic_payload={
                    "attempt_ref": public_attempt_ref,
                    "lifecycle_kind": "screen_group",
                    "raw_evidence_sha256": hashlib.sha256(
                        canonical_json_bytes(stable)
                    ).hexdigest(),
                    "terminal_status": "stable_zero",
                    "cleanup_stable_zero": True,
                    "resource_counts": deepcopy(_S13_ZERO_COUNTS),
                    "started_request_count": 0,
                    "terminal_or_unknown_request_count": 0,
                    "parent_refs": {
                        "actual_screen_group_ref": actual_ref,
                        "provider_group_ref": provider_ref,
                    },
                    "safety": deepcopy(_S13_SAFETY),
                },
            )
        )
    return result


def _s13_runner_file_ref(
    value: object,
    *,
    expected_content_sha256: str,
    name: str,
) -> dict[str, str]:
    if (
        not isinstance(value, Mapping)
        or set(value) != {"path", "file_sha256", "content_sha256"}
        or not isinstance(value.get("path"), str)
        or not Path(str(value["path"])).is_absolute()
        or _SHA_RE.fullmatch(str(value.get("file_sha256") or "")) is None
        or value.get("content_sha256") != expected_content_sha256
    ):
        raise ValueError(f"{name} is invalid")
    return {
        "file_sha256": str(value["file_sha256"]),
        "content_sha256": str(value["content_sha256"]),
    }


def _s13_raw_runner_ledger(
    values: Sequence[Mapping[str, object]],
) -> list[dict[str, Any]]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or not values:
        raise ValueError("benchmark v2 runner ledger is unavailable")
    result: list[dict[str, Any]] = []
    previous = "0" * 64
    for sequence, raw in enumerate(values):
        if (
            not isinstance(raw, Mapping)
            or set(raw) != {"contract_version", "event", "event_sha256"}
            or raw.get("contract_version")
            != "portfolio_hybrid_benchmark_v2_ledger_event_envelope_v2"
        ):
            raise ValueError("benchmark v2 runner ledger envelope is invalid")
        event = raw.get("event")
        if (
            not isinstance(event, Mapping)
            or set(event)
            != {
                "partition",
                "sequence",
                "event_type",
                "previous_envelope_sha256",
                "event_payload",
            }
            or event.get("partition") != "regression"
            or event.get("sequence") != sequence
            or event.get("previous_envelope_sha256") != previous
            or event.get("event_type")
            not in {"regression_attempt", "cleanup", "result"}
            or raw.get("event_sha256")
            != hashlib.sha256(canonical_json_bytes(event)).hexdigest()
        ):
            raise ValueError("benchmark v2 runner ledger hash chain is invalid")
        payload = _attempt_sealed_parent(
            event.get("event_payload"), "benchmark v2 runner event payload"
        )
        normalized = deepcopy(dict(raw))
        normalized["event"] = deepcopy(dict(event))
        normalized["event"]["event_payload"] = payload
        result.append(normalized)
        previous = hashlib.sha256(canonical_json_bytes(raw)).hexdigest()
    return result


def _s13_evidence_values(
    value: Mapping[str, object] | Sequence[Mapping[str, object]], *, name: str
) -> list[Mapping[str, object]]:
    if isinstance(value, Mapping):
        return [value]
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{name} evidence collection is invalid")
    return list(value)


def _s13_index_raw_attempt_evidence(
    value: Mapping[str, object] | Sequence[Mapping[str, object]],
    *,
    name: str,
    validator: Any,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in _s13_evidence_values(value, name=name):
        item = validator(raw)
        attempt = item.get("attempt_ref")
        public = _s13_public_attempt_ref(attempt)
        key = public["content_sha256"]
        if key in result:
            raise ValueError(f"{name} evidence is duplicated")
        result[key] = item
    return result


def _s13_index_cleanup_projections(
    value: Mapping[str, object] | Sequence[Mapping[str, object]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in _s13_evidence_values(value, name="cleanup projection"):
        item = deepcopy(dict(raw))
        _s13_pathless_projection_ref(
            item,
            contract_version="benchmark_v2_lifecycle_verified_projection_v1",
        )
        attempt = item.get("attempt_ref")
        if not isinstance(attempt, Mapping):
            raise ValueError("benchmark v2 cleanup projection attempt is invalid")
        key = str(attempt.get("content_sha256") or "")
        if item.get("lifecycle_kind") != "cleanup" or not key or key in result:
            raise ValueError("benchmark v2 cleanup projection evidence is invalid")
        result[key] = item
    return result


def _s13_runner_event_inputs(
    *,
    runner_ledger_events: Sequence[Mapping[str, object]],
    actual_body: Mapping[str, object] | Sequence[Mapping[str, object]],
    actual_result: Mapping[str, object] | Sequence[Mapping[str, object]],
    cleanup_receipt: Mapping[str, object] | Sequence[Mapping[str, object]],
    cleanup_projection: Mapping[str, object] | Sequence[Mapping[str, object]],
) -> tuple[list[dict[str, Any]], list[dict[str, object]]]:
    ledger = _s13_raw_runner_ledger(runner_ledger_events)
    bodies = _s13_index_raw_attempt_evidence(
        actual_body,
        name="actual body",
        validator=lambda item: _attempt_sealed_parent(item, "benchmark v2 actual body"),
    )
    results = _s13_index_raw_attempt_evidence(
        actual_result,
        name="actual result",
        validator=lambda item: _attempt_sealed_parent(item, "benchmark v2 actual result"),
    )
    cleanups = _s13_index_raw_attempt_evidence(
        cleanup_receipt,
        name="cleanup receipt",
        validator=_s13_cleanup_receipt,
    )
    cleanup_projections = _s13_index_cleanup_projections(cleanup_projection)
    used_bodies: set[str] = set()
    used_results: set[str] = set()
    used_cleanups: set[str] = set()
    used_cleanup_projections: set[str] = set()
    attempts: dict[str, dict[str, object]] = {}
    attempt_ids: dict[str, str] = {}
    attempt_dirs: dict[str, str] = {}
    descriptors: list[dict[str, object]] = []
    payload_fields = {
        "regression_attempt": {
            "contract_version",
            "attempt_ref",
            "attempt_dir",
            "mode",
            "provider_id",
            "status",
            "output_ref",
            "artifact_is_authorization",
            "execute_binding_enabled",
            "content_sha256",
        },
        "cleanup": {
            "contract_version",
            "attempt_ref",
            "attempt_dir",
            "mode",
            "provider_id",
            "status",
            "cleanup_receipt_ref",
            "resource_counts",
            "artifact_is_authorization",
            "execute_binding_enabled",
            "content_sha256",
        },
        "result": {
            "contract_version",
            "attempt_ref",
            "attempt_dir",
            "mode",
            "provider_id",
            "status",
            "output_ref",
            "artifact_is_authorization",
            "execute_binding_enabled",
            "content_sha256",
        },
    }
    payload_contracts = {
        "regression_attempt": "benchmark_v2_runner_regression_attempt_payload_v1",
        "cleanup": "benchmark_v2_runner_cleanup_payload_v1",
        "result": "benchmark_v2_runner_result_payload_v1",
    }
    for envelope in ledger:
        event = envelope["event"]
        event_type = str(event["event_type"])
        payload = event["event_payload"]
        if (
            set(payload) != payload_fields[event_type]
            or payload.get("contract_version") != payload_contracts[event_type]
            or payload.get("artifact_is_authorization") is not False
            or payload.get("execute_binding_enabled") is not False
        ):
            raise ValueError("benchmark v2 runner event payload is invalid")
        raw_attempt = payload.get("attempt_ref")
        public_attempt = _s13_public_attempt_ref(raw_attempt)
        key = public_attempt["content_sha256"]
        attempt_id = str(raw_attempt["attempt_id"])
        attempt_dir = str(payload.get("attempt_dir") or "")
        if (
            not Path(attempt_dir).is_absolute()
            or Path(attempt_dir).name != attempt_id
            or payload.get("mode") != raw_attempt.get("mode")
            or payload.get("provider_id") != raw_attempt.get("provider_id")
        ):
            raise ValueError("benchmark v2 runner event attempt lineage differs")
        if attempt_ids.setdefault(attempt_id, key) != key:
            raise ValueError("benchmark v2 runner attempt identity is ambiguous")
        if attempt_dirs.setdefault(attempt_dir, key) != key:
            raise ValueError("benchmark v2 runner attempt directory is ambiguous")
        state = attempts.get(key)
        status = str(payload.get("status") or "")
        parents: dict[str, object]
        if state is None:
            if event_type != "regression_attempt" or status != "opened":
                raise ValueError("benchmark v2 runner attempt starts before opened")
            if payload.get("output_ref") is not None:
                raise ValueError("benchmark v2 opened event already has output")
            attempts[key] = {
                "attempt_ref": deepcopy(dict(raw_attempt)),
                "public_attempt_ref": public_attempt,
                "attempt_dir": attempt_dir,
                "state": "opened",
                "body_ref": None,
                "cleanup_ref": None,
                "cleanup_sequence": None,
            }
            event_kind = "opened"
            parents = {"attempt_ref": public_attempt}
        else:
            if (
                state["attempt_ref"] != dict(raw_attempt)
                or state["attempt_dir"] != attempt_dir
            ):
                raise ValueError("benchmark v2 runner cross-attempt lineage differs")
            current_state = str(state["state"])
            if event_type == "regression_attempt":
                if status != "body_complete" or current_state != "opened":
                    raise ValueError("benchmark v2 runner body state differs")
                body = bodies.get(key)
                if (
                    body is None
                    or body.get("contract_version")
                    != "benchmark_v2_runner_actual_body_v1"
                    or body.get("attempt_ref") != raw_attempt
                    or body.get("partition") != "regression"
                    or body.get("body_status") != "complete"
                    or not isinstance(body.get("screen_group_results"), list)
                    or len(body["screen_group_results"]) != 12
                ):
                    raise ValueError("benchmark v2 actual body lineage differs")
                body_ref = _s13_runner_file_ref(
                    payload.get("output_ref"),
                    expected_content_sha256=str(body["content_sha256"]),
                    name="benchmark v2 runner body file ref",
                )
                used_bodies.add(key)
                state["state"] = "body_complete"
                state["body_ref"] = deepcopy(payload["output_ref"])
                event_kind = "body_complete"
                parents = {"body_file_ref": body_ref}
            elif event_type == "cleanup":
                if status != "terminal" or current_state not in {
                    "opened",
                    "body_complete",
                }:
                    raise ValueError("benchmark v2 runner cleanup state differs")
                cleanup = cleanups.get(key)
                projection = cleanup_projections.get(key)
                if cleanup is None or projection is None:
                    raise ValueError("benchmark v2 runner cleanup evidence is missing")
                cleanup_file_ref = _s13_runner_file_ref(
                    payload.get("cleanup_receipt_ref"),
                    expected_content_sha256=str(cleanup["content_sha256"]),
                    name="benchmark v2 runner cleanup file ref",
                )
                opaque_ref = derive_benchmark_v2_cleanup_receipt_ref(
                    cleanup_receipt=cleanup
                )
                projection_ref = _s13_pathless_projection_ref(
                    projection,
                    contract_version="benchmark_v2_lifecycle_verified_projection_v1",
                )
                if (
                    cleanup.get("attempt_ref") != raw_attempt
                    or payload.get("resource_counts") != _S13_ZERO_COUNTS
                    or projection.get("attempt_ref") != public_attempt
                    or projection.get("lifecycle_kind") != "cleanup"
                    or projection.get("parent_refs")
                    != {"cleanup_receipt_ref": opaque_ref}
                ):
                    raise ValueError("benchmark v2 runner cleanup lineage differs")
                used_cleanups.add(key)
                used_cleanup_projections.add(key)
                state["state"] = "cleanup"
                state["cleanup_ref"] = deepcopy(payload["cleanup_receipt_ref"])
                state["cleanup_sequence"] = int(event["sequence"])
                event_kind = "cleanup"
                parents = {
                    "cleanup_receipt_ref": opaque_ref,
                    "cleanup_projection_ref": projection_ref,
                }
                del cleanup_file_ref
            else:
                if status != "terminal" or current_state != "cleanup" or state["body_ref"] is None:
                    raise ValueError("benchmark v2 runner result state differs")
                result = results.get(key)
                if (
                    result is None
                    or result.get("contract_version")
                    != "benchmark_v2_runner_actual_result_v2"
                    or result.get("attempt_ref") != raw_attempt
                    or result.get("attempt_dir") != attempt_dir
                    or result.get("body_ref") != state["body_ref"]
                    or result.get("cleanup_receipt_ref") != state["cleanup_ref"]
                    or result.get("screen_group_count") != 12
                    or result.get("status") != "terminal"
                ):
                    raise ValueError("benchmark v2 actual result lineage differs")
                result_file_ref = _s13_runner_file_ref(
                    payload.get("output_ref"),
                    expected_content_sha256=str(result["content_sha256"]),
                    name="benchmark v2 runner result file ref",
                )
                cleanup_sequence = int(state["cleanup_sequence"])
                raw_prefix = b"".join(
                    canonical_json_bytes(item) + b"\n"
                    for item in ledger[: cleanup_sequence + 1]
                )
                cleanup_envelope = ledger[cleanup_sequence]
                native_pre_result_ref = {
                    "contract_version": "benchmark_v2_runner_ledger_pre_result_ref_v1",
                    "id": "runner-ledger-pre-result/"
                    + hashlib.sha256(
                        b"benchmark-v2-runner-ledger-pre-result\0" + raw_prefix
                    ).hexdigest(),
                    "attempt_ref": deepcopy(dict(raw_attempt)),
                    "terminal_sequence": cleanup_sequence,
                    "terminal_envelope_sha256": hashlib.sha256(
                        canonical_json_bytes(cleanup_envelope)
                    ).hexdigest(),
                    "prefix_sha256": hashlib.sha256(raw_prefix).hexdigest(),
                }
                if result.get("attempt_ledger_pre_result_ref") != native_pre_result_ref:
                    raise ValueError("benchmark v2 runner pre-result lineage differs")
                public_pre_result_ref = {
                    **native_pre_result_ref,
                    "attempt_ref": public_attempt,
                }
                used_results.add(key)
                state["state"] = "result"
                event_kind = "result"
                parents = {
                    "result_file_ref": result_file_ref,
                    "attempt_ledger_pre_result_ref": public_pre_result_ref,
                }
        descriptors.append(
            {
                "raw": envelope,
                "event_kind": event_kind,
                "attempt_ref": public_attempt,
                "load_bearing_refs": parents,
            }
        )
    if (
        set(bodies) != used_bodies
        or set(results) != used_results
        or set(cleanups) != used_cleanups
        or set(cleanup_projections) != used_cleanup_projections
    ):
        raise ValueError("benchmark v2 runner supplied evidence was not consumed")
    return ledger, descriptors


def project_benchmark_v2_runner_events(
    *,
    partition: str,
    runner_ledger_events: Sequence[Mapping[str, object]],
    actual_body: Mapping[str, object] | Sequence[Mapping[str, object]],
    actual_result: Mapping[str, object] | Sequence[Mapping[str, object]],
    cleanup_receipt: Mapping[str, object] | Sequence[Mapping[str, object]],
    cleanup_projection: Mapping[str, object] | Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """将已验证的 runner 事件链投影成按 sequence 单向链接的公开事件。"""

    if partition != "regression":
        raise ValueError("benchmark v2 runner event projection is regression-only")
    ledger, descriptors = _s13_runner_event_inputs(
        runner_ledger_events=runner_ledger_events,
        actual_body=actual_body,
        actual_result=actual_result,
        cleanup_receipt=cleanup_receipt,
        cleanup_projection=cleanup_projection,
    )
    from app.learn.hybrid.benchmark_v2_pathless import (
        pathless_artifact_ref,
        seal_pathless_projection,
    )

    projections: list[dict[str, object]] = []
    for descriptor in descriptors:
        raw = descriptor["raw"]
        projection = seal_pathless_projection(
            contract_version="benchmark_v2_runner_event_verified_projection_v1",
            semantic_payload={
                "partition": partition,
                "event_kind": descriptor["event_kind"],
                "sequence": int(raw["event"]["sequence"]),
                "attempt_ref": deepcopy(descriptor["attempt_ref"]),
                "previous_event_projection_ref": (
                    pathless_artifact_ref(projections[-1]) if projections else None
                ),
                "raw_event_sha256": hashlib.sha256(
                    canonical_json_bytes(raw)
                ).hexdigest(),
                "load_bearing_refs": deepcopy(descriptor["load_bearing_refs"]),
                "safety": deepcopy(_S13_SAFETY),
            },
        )
        projections.append(projection)
    return projections


def project_benchmark_v2_attempt_lifecycle(
    *,
    attempt_ref: Mapping[str, object],
    journal_events: Sequence[Mapping[str, object]],
    attempt_journal_projection: Mapping[str, object],
    cleanup_projection: Mapping[str, object],
    terminal_event_projection: Mapping[str, object],
    screen_group_lifecycle_projections: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """组合 actual-model attempt 的已验证、稳定零且无环的 lifecycle 投影。"""

    public_attempt_ref = _s13_public_attempt_ref(attempt_ref)
    events = _s13_attempt_journal_events(
        journal_events,
        attempt_ref=attempt_ref,
        forbid_provider_events=True,
    )
    raw_journal = b"".join(canonical_json_bytes(item) + b"\n" for item in events)
    cleanup_ref = _s13_pathless_projection_ref(
        cleanup_projection,
        contract_version="benchmark_v2_lifecycle_verified_projection_v1",
    )
    terminal_ref = _s13_pathless_projection_ref(
        terminal_event_projection,
        contract_version="benchmark_v2_attempt_journal_terminal_event_verified_projection_v1",
    )
    journal_ref = _s13_pathless_projection_ref(
        attempt_journal_projection,
        contract_version="benchmark_v2_attempt_journal_verified_projection_v1",
    )
    if (
        cleanup_projection.get("attempt_ref") != public_attempt_ref
        or cleanup_projection.get("lifecycle_kind") != "cleanup"
        or cleanup_projection.get("terminal_status") != "stable_zero"
        or cleanup_projection.get("cleanup_stable_zero") is not True
        or cleanup_projection.get("resource_counts") != _S13_ZERO_COUNTS
        or terminal_event_projection.get("attempt_ref") != public_attempt_ref
        or terminal_event_projection.get("sequence") != events[-1]["sequence"]
        or terminal_event_projection.get("raw_event_sha256")
        != hashlib.sha256(canonical_json_bytes(events[-1])).hexdigest()
        or terminal_event_projection.get("cleanup_projection_ref") != cleanup_ref
        or attempt_journal_projection.get("attempt_ref") != public_attempt_ref
        or attempt_journal_projection.get("raw_journal_sha256")
        != hashlib.sha256(raw_journal).hexdigest()
        or attempt_journal_projection.get("terminal_event_ref") != terminal_ref
        or attempt_journal_projection.get("cleanup_projection_ref") != cleanup_ref
        or attempt_journal_projection.get("started_request_count") != 0
        or attempt_journal_projection.get("terminal_or_unknown_request_count") != 0
        or attempt_journal_projection.get("verified") is not True
    ):
        raise ValueError("benchmark v2 attempt journal projection differs")
    if (
        not isinstance(screen_group_lifecycle_projections, Sequence)
        or isinstance(screen_group_lifecycle_projections, (str, bytes))
        or len(screen_group_lifecycle_projections) != 12
    ):
        raise ValueError("benchmark v2 requires 12 screen-group lifecycle projections")
    screen_refs: list[dict[str, str]] = []
    screen_ids: list[str] = []
    for projection in screen_group_lifecycle_projections:
        ref = _s13_pathless_projection_ref(
            projection,
            contract_version="benchmark_v2_lifecycle_verified_projection_v1",
        )
        parents = projection.get("parent_refs")
        actual_ref = (
            parents.get("actual_screen_group_ref")
            if isinstance(parents, Mapping)
            else None
        )
        if (
            projection.get("attempt_ref") != public_attempt_ref
            or projection.get("lifecycle_kind") != "screen_group"
            or not isinstance(actual_ref, Mapping)
            or not isinstance(actual_ref.get("id"), str)
        ):
            raise ValueError("benchmark v2 screen-group lifecycle projection differs")
        screen_refs.append(ref)
        screen_ids.append(str(actual_ref["id"]))
    if len(set(screen_ids)) != 12 or screen_ids != sorted(screen_ids):
        raise ValueError("benchmark v2 screen-group lifecycle order differs")
    from app.learn.hybrid.benchmark_v2_pathless import seal_pathless_projection

    return seal_pathless_projection(
        contract_version="benchmark_v2_lifecycle_verified_projection_v1",
        semantic_payload={
            "attempt_ref": public_attempt_ref,
            "lifecycle_kind": "attempt",
            "raw_evidence_sha256": hashlib.sha256(raw_journal).hexdigest(),
            "terminal_status": "terminal",
            "cleanup_stable_zero": True,
            "resource_counts": deepcopy(_S13_ZERO_COUNTS),
            "started_request_count": 0,
            "terminal_or_unknown_request_count": 0,
            "parent_refs": {
                "attempt_journal_projection_ref": journal_ref,
                "cleanup_projection_ref": cleanup_ref,
                "terminal_event_ref": terminal_ref,
                "screen_group_lifecycle_projection_refs": screen_refs,
            },
            "safety": deepcopy(_S13_SAFETY),
        },
    )


def project_benchmark_v2_attempt_ledger(
    *,
    benchmark_release_id: str,
    partition: str,
    runner_ledger_events: Sequence[Mapping[str, object]],
    runner_event_projections: Sequence[Mapping[str, object]],
    raw_ledger_prefix_projection: Mapping[str, object],
    attempt_lifecycle_projections: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """按 raw ledger 首次 open 顺序折叠 attempts，并只选择首个完整 lifecycle。"""

    if partition != "regression" or not isinstance(benchmark_release_id, str) or not benchmark_release_id:
        raise ValueError("benchmark v2 projected attempt ledger identity is invalid")
    ledger = _s13_raw_runner_ledger(runner_ledger_events)
    if (
        not isinstance(runner_event_projections, Sequence)
        or isinstance(runner_event_projections, (str, bytes))
        or len(runner_event_projections) != len(ledger)
    ):
        raise ValueError("benchmark v2 event projection order differs")
    from app.learn.hybrid.benchmark_v2_pathless import (
        pathless_artifact_ref,
        seal_pathless_projection,
    )

    event_refs: list[dict[str, str]] = []
    attempt_entries: dict[str, dict[str, object]] = {}
    attempt_order: list[str] = []
    previous_projection_ref: dict[str, str] | None = None
    state_for_kind = {
        "opened": "opened",
        "body_complete": "body_complete",
        "cleanup": "cleanup",
        "result": "result",
    }
    kind_for_raw = {
        ("regression_attempt", "opened"): "opened",
        ("regression_attempt", "body_complete"): "body_complete",
        ("cleanup", "terminal"): "cleanup",
        ("result", "terminal"): "result",
    }
    for raw, projection in zip(ledger, runner_event_projections, strict=True):
        ref = _s13_pathless_projection_ref(
            projection,
            contract_version="benchmark_v2_runner_event_verified_projection_v1",
        )
        payload = raw["event"]["event_payload"]
        event_kind = kind_for_raw.get(
            (str(raw["event"]["event_type"]), str(payload.get("status")))
        )
        public_attempt_ref = _s13_public_attempt_ref(payload.get("attempt_ref"))
        if (
            event_kind is None
            or projection.get("partition") != partition
            or projection.get("sequence") != raw["event"]["sequence"]
            or projection.get("event_kind") != event_kind
            or projection.get("attempt_ref") != public_attempt_ref
            or projection.get("previous_event_projection_ref")
            != previous_projection_ref
            or projection.get("raw_event_sha256")
            != hashlib.sha256(canonical_json_bytes(raw)).hexdigest()
        ):
            raise ValueError("benchmark v2 event projection order differs")
        previous_projection_ref = ref
        event_refs.append(ref)
        attempt_key = public_attempt_ref["content_sha256"]
        entry = attempt_entries.get(attempt_key)
        if entry is None:
            if event_kind != "opened":
                raise ValueError("benchmark v2 attempt starts before opened")
            attempt_order.append(attempt_key)
            entry = {
                "sequence": len(attempt_order) - 1,
                "attempt_ref": public_attempt_ref,
                "observed_state": "opened",
                "event_projection_refs": [],
                "lifecycle_ref": None,
                "selection_eligible": False,
            }
            attempt_entries[attempt_key] = entry
        entry["observed_state"] = state_for_kind[event_kind]
        entry["event_projection_refs"].append(ref)
    if (
        not isinstance(attempt_lifecycle_projections, Sequence)
        or isinstance(attempt_lifecycle_projections, (str, bytes))
        or not attempt_lifecycle_projections
    ):
        raise ValueError("benchmark v2 attempt lifecycle projections are unavailable")
    lifecycle_by_attempt: dict[str, tuple[dict[str, object], dict[str, str]]] = {}
    for raw_lifecycle in attempt_lifecycle_projections:
        lifecycle = deepcopy(dict(raw_lifecycle))
        lifecycle_ref = _s13_pathless_projection_ref(
            lifecycle,
            contract_version="benchmark_v2_lifecycle_verified_projection_v1",
        )
        lifecycle_attempt_ref = lifecycle.get("attempt_ref")
        if (
            lifecycle.get("lifecycle_kind") != "attempt"
            or lifecycle.get("terminal_status") != "terminal"
            or lifecycle.get("cleanup_stable_zero") is not True
            or lifecycle.get("resource_counts") != _S13_ZERO_COUNTS
            or lifecycle.get("started_request_count")
            != lifecycle.get("terminal_or_unknown_request_count")
            or not isinstance(lifecycle_attempt_ref, Mapping)
        ):
            raise ValueError("benchmark v2 attempt lifecycle is invalid")
        key = str(lifecycle_attempt_ref.get("content_sha256") or "")
        if not key or key in lifecycle_by_attempt:
            raise ValueError("benchmark v2 attempt lifecycle is duplicated")
        lifecycle_by_attempt[key] = (lifecycle, lifecycle_ref)
    complete_keys = {
        key
        for key, entry in attempt_entries.items()
        if entry["observed_state"] == "result"
    }
    if set(lifecycle_by_attempt) != complete_keys:
        raise ValueError("benchmark v2 complete-attempt lifecycle coverage differs")
    selected_key = next(
        (key for key in attempt_order if key in complete_keys),
        None,
    )
    if selected_key is None:
        raise ValueError("benchmark v2 runner has no eligible complete attempt")
    selected_lifecycle, selected_lifecycle_ref = lifecycle_by_attempt[selected_key]
    selected_attempt_ref = selected_lifecycle["attempt_ref"]
    selected_result_sequence = max(
        int(item["sequence"])
        for item in runner_event_projections
        if item.get("attempt_ref") == selected_attempt_ref
        and item.get("event_kind") == "result"
    )
    selected_prefix_ledger = ledger[: selected_result_sequence + 1]
    selected_prefix_projections = list(
        runner_event_projections[: selected_result_sequence + 1]
    )
    prefix_entries: dict[str, dict[str, object]] = {}
    prefix_order: list[str] = []
    for projection in selected_prefix_projections:
        attempt = projection["attempt_ref"]
        assert isinstance(attempt, Mapping)
        key = str(attempt["content_sha256"])
        entry = prefix_entries.get(key)
        if entry is None:
            prefix_order.append(key)
            entry = {
                "sequence": len(prefix_order) - 1,
                "attempt_ref": deepcopy(dict(attempt)),
                "observed_state": "opened",
                "event_projection_refs": [],
                "lifecycle_ref": None,
                "selection_eligible": False,
            }
            prefix_entries[key] = entry
        entry["observed_state"] = state_for_kind[str(projection["event_kind"])]
        entry["event_projection_refs"].append(pathless_artifact_ref(projection))
    selected_entry = prefix_entries[selected_key]
    if selected_entry["observed_state"] != "result":
        raise ValueError("benchmark v2 selected attempt prefix is incomplete")
    selected_entry["lifecycle_ref"] = selected_lifecycle_ref
    selected_entry["selection_eligible"] = True
    prefix_ref = _s13_pathless_projection_ref(
        raw_ledger_prefix_projection,
        contract_version="benchmark_v2_runner_ledger_prefix_verified_projection_v1",
    )
    raw_prefix = b"".join(
        canonical_json_bytes(item) + b"\n" for item in selected_prefix_ledger
    )
    selected_events = [
        item
        for item in selected_prefix_projections
        if item.get("attempt_ref") == selected_attempt_ref
    ]
    by_kind = {str(item["event_kind"]): item for item in selected_events}
    expected_prefix = {
        "partition": partition,
        "raw_prefix_sha256": hashlib.sha256(raw_prefix).hexdigest(),
        "attempt_ledger_pre_result_ref": by_kind["result"]["load_bearing_refs"][
            "attempt_ledger_pre_result_ref"
        ],
        "through_result_terminal_sequence": int(
            selected_events[-1]["sequence"]
        ),
        "through_result_terminal_envelope_sha256": hashlib.sha256(
            canonical_json_bytes(ledger[int(selected_events[-1]["sequence"])])
        ).hexdigest(),
        "attempt_ref": selected_attempt_ref,
        "body_file_ref": by_kind["body_complete"]["load_bearing_refs"][
            "body_file_ref"
        ],
        "cleanup_event_projection_ref": pathless_artifact_ref(by_kind["cleanup"]),
        "result_file_ref": by_kind["result"]["load_bearing_refs"][
            "result_file_ref"
        ],
        "result_event_projection_ref": pathless_artifact_ref(by_kind["result"]),
        "verified": True,
        "safety": _S13_SAFETY,
    }
    if any(raw_ledger_prefix_projection.get(key) != value for key, value in expected_prefix.items()):
        raise ValueError("benchmark v2 raw ledger prefix projection differs")
    entries = [prefix_entries[key] for key in prefix_order]
    return seal_pathless_projection(
        contract_version="benchmark_v2_projected_attempt_ledger_v1",
        semantic_payload={
            "benchmark_release_id": benchmark_release_id,
            "partition": partition,
            "raw_ledger_prefix_verification_ref": prefix_ref,
            "entries": deepcopy(entries),
            "selected_attempt_ref": deepcopy(dict(selected_attempt_ref)),
            "selected_lifecycle_ref": selected_lifecycle_ref,
            "safety": deepcopy(_S13_SAFETY),
        },
    )


def compose_benchmark_v2_lifecycle_bundle_v3(
    *,
    benchmark_release_id: str,
    partition: str,
    attempt_ref: Mapping[str, object],
    raw_ledger_prefix_projection: Mapping[str, object],
    projected_attempt_ledger: Mapping[str, object],
    selected_attempt_lifecycle_projection: Mapping[str, object],
    cleanup_lifecycle_projection: Mapping[str, object],
    journal_terminal_event_projection: Mapping[str, object],
    attempt_journal_projection: Mapping[str, object],
    screen_group_lifecycle_projections: Sequence[Mapping[str, object]],
    runner_event_projections: Sequence[Mapping[str, object]],
    cleanup_receipt: Mapping[str, object],
    cleanup_lifecycle_projections: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """组合并递归验证 lifecycle-bundle-v3 的精确无路径闭包。"""

    if (
        partition != "regression"
        or not isinstance(benchmark_release_id, str)
        or not benchmark_release_id
    ):
        raise ValueError("benchmark v2 lifecycle bundle identity is invalid")
    public_attempt_ref = _s13_public_attempt_ref(attempt_ref)
    receipt = _s13_cleanup_receipt(cleanup_receipt, attempt_ref=attempt_ref)
    opaque_cleanup_ref = derive_benchmark_v2_cleanup_receipt_ref(
        cleanup_receipt=receipt
    )
    if (
        not isinstance(screen_group_lifecycle_projections, Sequence)
        or isinstance(screen_group_lifecycle_projections, (str, bytes))
        or len(screen_group_lifecycle_projections) != 12
    ):
        raise ValueError("benchmark v2 lifecycle bundle requires 12 screen-group projections")
    if (
        not isinstance(runner_event_projections, Sequence)
        or isinstance(runner_event_projections, (str, bytes))
        or not runner_event_projections
    ):
        raise ValueError("benchmark v2 lifecycle bundle runner events are incomplete")

    from app.learn.hybrid.benchmark_v2_pathless import (
        pathless_artifact_ref,
        seal_pathless_envelope,
        seal_pathless_projection,
        validate_pathless_recursive,
    )

    prefix_ref = _s13_pathless_projection_ref(
        raw_ledger_prefix_projection,
        contract_version="benchmark_v2_runner_ledger_prefix_verified_projection_v1",
    )
    journal_ref = _s13_pathless_projection_ref(
        attempt_journal_projection,
        contract_version="benchmark_v2_attempt_journal_verified_projection_v1",
    )
    cleanup_ref = _s13_pathless_projection_ref(
        cleanup_lifecycle_projection,
        contract_version="benchmark_v2_lifecycle_verified_projection_v1",
    )
    raw_cleanup_lifecycles = (
        [cleanup_lifecycle_projection]
        if cleanup_lifecycle_projections is None
        else list(cleanup_lifecycle_projections)
    )
    if not raw_cleanup_lifecycles:
        raise ValueError("benchmark v2 lifecycle bundle cleanup projections are empty")
    cleanup_items: list[dict[str, object]] = []
    cleanup_refs_by_attempt: dict[str, dict[str, str]] = {}
    cleanup_receipt_refs_by_attempt: dict[str, dict[str, str]] = {}
    for value in raw_cleanup_lifecycles:
        item = deepcopy(dict(value))
        ref = _s13_pathless_projection_ref(
            item,
            contract_version="benchmark_v2_lifecycle_verified_projection_v1",
        )
        attempt = _s13_exact_ref(
            item.get("attempt_ref"), "cleanup lifecycle attempt ref"
        )
        parents = item.get("parent_refs")
        if (
            item.get("lifecycle_kind") != "cleanup"
            or not isinstance(parents, Mapping)
            or set(parents) != {"cleanup_receipt_ref"}
        ):
            raise ValueError("benchmark v2 lifecycle bundle cleanup projection differs")
        key = attempt["content_sha256"]
        if key in cleanup_refs_by_attempt:
            raise ValueError("benchmark v2 lifecycle bundle cleanup projection is duplicated")
        cleanup_items.append(item)
        cleanup_refs_by_attempt[key] = ref
        cleanup_receipt_refs_by_attempt[key] = _s13_exact_ref(
            parents["cleanup_receipt_ref"], "cleanup lifecycle receipt ref"
        )
    if cleanup_refs_by_attempt.get(public_attempt_ref["content_sha256"]) != cleanup_ref:
        raise ValueError("benchmark v2 lifecycle bundle selected cleanup projection differs")
    terminal_ref = _s13_pathless_projection_ref(
        journal_terminal_event_projection,
        contract_version="benchmark_v2_attempt_journal_terminal_event_verified_projection_v1",
    )
    selected_lifecycle_ref = _s13_pathless_projection_ref(
        selected_attempt_lifecycle_projection,
        contract_version="benchmark_v2_lifecycle_verified_projection_v1",
    )
    projected_ledger_ref = _s13_pathless_projection_ref(
        projected_attempt_ledger,
        contract_version="benchmark_v2_projected_attempt_ledger_v1",
    )

    screen_items: list[dict[str, object]] = []
    screen_refs: list[dict[str, str]] = []
    screen_actual_refs: list[dict[str, str]] = []
    screen_provider_refs: list[dict[str, str]] = []
    screen_ids: list[str] = []
    for value in screen_group_lifecycle_projections:
        item = deepcopy(dict(value))
        ref = _s13_pathless_projection_ref(
            item,
            contract_version="benchmark_v2_lifecycle_verified_projection_v1",
        )
        parents = item.get("parent_refs")
        actual_parent = (
            parents.get("actual_screen_group_ref")
            if isinstance(parents, Mapping)
            else None
        )
        provider_parent = (
            parents.get("provider_group_ref")
            if isinstance(parents, Mapping)
            else None
        )
        actual_ref = _s13_exact_ref(actual_parent, "screen-group actual parent ref")
        provider_ref = _s13_exact_ref(
            provider_parent, "screen-group provider parent ref"
        )
        if (
            item.get("attempt_ref") != public_attempt_ref
            or item.get("lifecycle_kind") != "screen_group"
        ):
            raise ValueError("benchmark v2 screen-group lifecycle projection differs")
        screen_items.append(item)
        screen_refs.append(ref)
        screen_actual_refs.append(actual_ref)
        screen_provider_refs.append(provider_ref)
        screen_ids.append(actual_ref["id"])
    if len(set(screen_ids)) != 12 or screen_ids != sorted(screen_ids):
        raise ValueError("benchmark v2 screen-group lifecycle order differs")

    all_runner_items: list[dict[str, object]] = []
    all_runner_refs: list[dict[str, str]] = []
    previous_ref: dict[str, str] | None = None
    for sequence, value in enumerate(runner_event_projections):
        item = deepcopy(dict(value))
        ref = _s13_pathless_projection_ref(
            item,
            contract_version="benchmark_v2_runner_event_verified_projection_v1",
        )
        if (
            item.get("partition") != partition
            or item.get("sequence") != sequence
            or item.get("previous_event_projection_ref") != previous_ref
        ):
            raise ValueError("benchmark v2 lifecycle bundle runner event order differs")
        all_runner_items.append(item)
        all_runner_refs.append(ref)
        previous_ref = ref

    through_sequence = raw_ledger_prefix_projection.get(
        "through_result_terminal_sequence"
    )
    if (
        not isinstance(through_sequence, int)
        or isinstance(through_sequence, bool)
        or through_sequence < 0
        or through_sequence >= len(all_runner_items)
    ):
        raise ValueError("benchmark v2 lifecycle bundle runner prefix is incomplete")
    runner_items = all_runner_items[: through_sequence + 1]
    runner_refs = all_runner_refs[: through_sequence + 1]

    entries = projected_attempt_ledger.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("benchmark v2 lifecycle bundle projected entries are invalid")
    ledger_event_refs: list[dict[str, str]] = []
    ledger_attempt_refs: list[dict[str, str]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ValueError("benchmark v2 lifecycle bundle projected entry is invalid")
        ledger_attempt_refs.append(
            _s13_exact_ref(entry.get("attempt_ref"), "projected ledger attempt ref")
        )
        event_refs = entry.get("event_projection_refs")
        if not isinstance(event_refs, list) or not event_refs:
            raise ValueError("benchmark v2 lifecycle bundle projected event refs are invalid")
        ledger_event_refs.extend(
            _s13_exact_ref(value, "projected ledger runner event ref")
            for value in event_refs
        )
    if ledger_event_refs != runner_refs:
        raise ValueError("benchmark v2 lifecycle bundle projected event prefix differs")

    cleanup_attempt_order: list[str] = []
    for item in runner_items:
        if item.get("event_kind") != "cleanup":
            continue
        attempt = _s13_exact_ref(item.get("attempt_ref"), "cleanup event attempt ref")
        key = attempt["content_sha256"]
        refs = item.get("load_bearing_refs")
        if (
            not isinstance(refs, Mapping)
            or cleanup_refs_by_attempt.get(key) != refs.get("cleanup_projection_ref")
            or cleanup_receipt_refs_by_attempt.get(key)
            != refs.get("cleanup_receipt_ref")
        ):
            raise ValueError("benchmark v2 lifecycle bundle cleanup event lineage differs")
        cleanup_attempt_order.append(key)
    if cleanup_attempt_order != list(cleanup_refs_by_attempt):
        raise ValueError("benchmark v2 lifecycle bundle cleanup projection order differs")

    selected_runner_items = [
        item for item in runner_items if item.get("attempt_ref") == public_attempt_ref
    ]
    expected_runner_kinds = ("opened", "body_complete", "cleanup", "result")
    if tuple(item.get("event_kind") for item in selected_runner_items) != expected_runner_kinds:
        raise ValueError("benchmark v2 lifecycle bundle selected runner events differ")
    if selected_runner_items[-1] is not runner_items[-1]:
        raise ValueError("benchmark v2 lifecycle bundle selected result is not prefix-terminal")

    if (
        cleanup_lifecycle_projection.get("attempt_ref") != public_attempt_ref
        or cleanup_lifecycle_projection.get("lifecycle_kind") != "cleanup"
        or cleanup_lifecycle_projection.get("parent_refs")
        != {"cleanup_receipt_ref": opaque_cleanup_ref}
        or journal_terminal_event_projection.get("attempt_ref")
        != public_attempt_ref
        or journal_terminal_event_projection.get("cleanup_receipt_ref")
        != opaque_cleanup_ref
        or journal_terminal_event_projection.get("cleanup_projection_ref")
        != cleanup_ref
        or attempt_journal_projection.get("attempt_ref") != public_attempt_ref
        or attempt_journal_projection.get("terminal_event_ref") != terminal_ref
        or attempt_journal_projection.get("cleanup_projection_ref") != cleanup_ref
        or selected_attempt_lifecycle_projection.get("attempt_ref")
        != public_attempt_ref
        or selected_attempt_lifecycle_projection.get("lifecycle_kind") != "attempt"
        or selected_attempt_lifecycle_projection.get("parent_refs")
        != {
            "attempt_journal_projection_ref": journal_ref,
            "cleanup_projection_ref": cleanup_ref,
            "terminal_event_ref": terminal_ref,
            "screen_group_lifecycle_projection_refs": screen_refs,
        }
    ):
        raise ValueError("benchmark v2 lifecycle bundle lifecycle lineage differs")
    if (
        projected_attempt_ledger.get("benchmark_release_id") != benchmark_release_id
        or projected_attempt_ledger.get("partition") != partition
        or projected_attempt_ledger.get("raw_ledger_prefix_verification_ref")
        != prefix_ref
        or projected_attempt_ledger.get("selected_attempt_ref")
        != public_attempt_ref
        or projected_attempt_ledger.get("selected_lifecycle_ref")
        != selected_lifecycle_ref
    ):
        raise ValueError("benchmark v2 lifecycle bundle projected ledger differs")

    opened_refs = selected_runner_items[0]["load_bearing_refs"]
    body_refs = selected_runner_items[1]["load_bearing_refs"]
    cleanup_refs = selected_runner_items[2]["load_bearing_refs"]
    result_refs = selected_runner_items[3]["load_bearing_refs"]
    assert isinstance(opened_refs, Mapping)
    assert isinstance(body_refs, Mapping)
    assert isinstance(cleanup_refs, Mapping)
    assert isinstance(result_refs, Mapping)
    if (
        opened_refs.get("attempt_ref") != public_attempt_ref
        or cleanup_refs.get("cleanup_receipt_ref") != opaque_cleanup_ref
        or cleanup_refs.get("cleanup_projection_ref") != cleanup_ref
    ):
        raise ValueError("benchmark v2 lifecycle bundle runner lineage differs")

    children = [
        *screen_items,
        *cleanup_items,
        deepcopy(dict(journal_terminal_event_projection)),
        deepcopy(dict(selected_attempt_lifecycle_projection)),
        *runner_items,
        deepcopy(dict(projected_attempt_ledger)),
    ]
    child_envelopes = [seal_pathless_envelope(item) for item in children]
    runner_attempt_refs = [
        _s13_exact_ref(item["attempt_ref"], "runner event attempt ref")
        for item in runner_items
    ]
    opened_attempt_refs = [
        _s13_exact_ref(
            item["load_bearing_refs"]["attempt_ref"],
            "opened runner event attempt ref",
        )
        for item in runner_items
        if item["event_kind"] == "opened"
    ]
    body_file_refs = [
        deepcopy(item["load_bearing_refs"]["body_file_ref"])
        for item in runner_items
        if item["event_kind"] == "body_complete"
    ]
    cleanup_receipt_refs = [
        deepcopy(item["load_bearing_refs"]["cleanup_receipt_ref"])
        for item in runner_items
        if item["event_kind"] == "cleanup"
    ]
    result_file_refs = [
        deepcopy(item["load_bearing_refs"]["result_file_ref"])
        for item in runner_items
        if item["event_kind"] == "result"
    ]
    ledger_pre_result_refs = [
        deepcopy(item["load_bearing_refs"]["attempt_ledger_pre_result_ref"])
        for item in runner_items
        if item["event_kind"] == "result"
    ]
    external_refs: dict[str, object] = {
        "benchmark_v2_projected_attempt_ledger_v1.raw_ledger_prefix_verification_ref": prefix_ref,
        "benchmark_v2_projected_attempt_ledger_v1.selected_attempt_ref": public_attempt_ref,
        "benchmark_v2_projected_attempt_ledger_v1.entries.attempt_ref": ledger_attempt_refs,
        "benchmark_v2_lifecycle_verified_projection_v1.attempt_ref": [
            public_attempt_ref,
            *[
                _s13_exact_ref(item["attempt_ref"], "cleanup lifecycle attempt ref")
                for item in cleanup_items
            ],
        ],
        "benchmark_v2_lifecycle_verified_projection_v1.parent_refs.cleanup_receipt_ref": list(
            cleanup_receipt_refs_by_attempt.values()
        ),
        "benchmark_v2_lifecycle_verified_projection_v1.parent_refs.actual_screen_group_ref": screen_actual_refs,
        "benchmark_v2_lifecycle_verified_projection_v1.parent_refs.provider_group_ref": screen_provider_refs,
        "benchmark_v2_lifecycle_verified_projection_v1.parent_refs.attempt_journal_projection_ref": journal_ref,
        "benchmark_v2_attempt_journal_terminal_event_verified_projection_v1.attempt_ref": public_attempt_ref,
        "benchmark_v2_attempt_journal_terminal_event_verified_projection_v1.cleanup_receipt_ref": opaque_cleanup_ref,
        "benchmark_v2_runner_event_verified_projection_v1.attempt_ref": runner_attempt_refs,
        "benchmark_v2_runner_event_verified_projection_v1.load_bearing_refs.attempt_ref": opened_attempt_refs,
        "benchmark_v2_runner_event_verified_projection_v1.load_bearing_refs.body_file_ref": body_file_refs,
        "benchmark_v2_runner_event_verified_projection_v1.load_bearing_refs.cleanup_receipt_ref": cleanup_receipt_refs,
        "benchmark_v2_runner_event_verified_projection_v1.load_bearing_refs.result_file_ref": result_file_refs,
        "benchmark_v2_runner_event_verified_projection_v1.load_bearing_refs.attempt_ledger_pre_result_ref": ledger_pre_result_refs,
    }
    ordered_envelopes = validate_pathless_recursive(
        registry_name="lifecycle_bundle_v3",
        roots=[projected_ledger_ref],
        envelopes=child_envelopes,
        external_refs=external_refs,
        context={},
    )
    runner_start = 14 + len(cleanup_items)
    if [
        item["ref"]
        for item in ordered_envelopes[
            runner_start : runner_start + len(runner_refs)
        ]
    ] != runner_refs:
        raise ValueError("benchmark v2 lifecycle bundle runner event order differs")
    if ordered_envelopes[-1]["ref"] != projected_ledger_ref:
        raise ValueError("benchmark v2 lifecycle bundle projected ledger rank differs")

    bundle = seal_pathless_projection(
        contract_version="benchmark_v2_lifecycle_bundle_v3",
        semantic_payload={
            "benchmark_release_id": benchmark_release_id,
            "partition": partition,
            "attempt_ref": public_attempt_ref,
            "projected_attempt_ledger_ref": projected_ledger_ref,
            "raw_ledger_prefix_verification_ref": prefix_ref,
            "selected_lifecycle_ref": selected_lifecycle_ref,
            "attempt_cleanup_projection_ref": cleanup_ref,
            "screen_group_lifecycle_projection_refs": screen_refs,
            "sealed_artifact_envelopes": ordered_envelopes,
            "safety": deepcopy(_S13_SAFETY),
        },
    )
    if pathless_artifact_ref(bundle)["id"] != bundle["artifact_id"]:
        raise ValueError("benchmark v2 lifecycle bundle identity differs")
    return bundle


__all__ = [
    "append_benchmark_v2_attempt_event",
    "collect_raw_gpu_sample",
    "compose_benchmark_v2_attempt_cleanup_receipt",
    "compose_benchmark_v2_lifecycle_bundle_v3",
    "derive_benchmark_v2_cleanup_receipt_ref",
    "project_benchmark_v2_cleanup_lifecycle",
    "project_benchmark_v2_attempt_journal_terminal_event",
    "project_benchmark_v2_screen_group_lifecycles",
    "project_benchmark_v2_runner_events",
    "project_benchmark_v2_attempt_lifecycle",
    "project_benchmark_v2_attempt_ledger",
    "read_benchmark_v2_attempt_journal",
    "verify_lifecycle_from_raw",
]
