from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
from pathlib import Path

import pytest

from app.learn.hybrid import benchmark_v2_lifecycle as lifecycle
from app.learn.hybrid.benchmark_v2_lifecycle import (
    collect_raw_gpu_sample,
    verify_lifecycle_from_raw,
)
from app.learn.recognition.uei.canonical import canonical_json_bytes, seal_immutable


SHA0 = "0" * 64
DEVICE = "GPU-a"


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _ref(character: str) -> dict[str, str]:
    return {"content_sha256": character * 64}


def _write_json(path: Path, value: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))
    return path.resolve()


def _stream(raw: bytes) -> dict[str, object]:
    return {
        "encoding": "base64",
        "byte_length": len(raw),
        "sha256": _sha(raw),
        "data_base64": base64.b64encode(raw).decode("ascii"),
    }


def _observer(kind: str = "test_fixture") -> dict[str, object]:
    return seal_immutable(
        {
            "contract_version": "benchmark_v2_gpu_observer_identity_v1",
            "kind": kind,
            "platform": "test",
            "collector_module_ref": {
                "canonical_path": "test-fixture/benchmark_v2_lifecycle.py",
                "file_sha256": "a" * 64,
            },
            "nvidia_smi_ref": None,
            "collector_process_identity": {"pid": 9001, "create_time_ns": 9001000},
        }
    )


def _sample(
    path: Path,
    *,
    at: datetime,
    total_mib: int = 600,
    rows: list[tuple[int, str, int, int]] | None = None,
    observer_kind: str = "test_fixture",
    exits: tuple[int, int] = (0, 0),
    timed_out: tuple[bool, bool] = (False, False),
    gpu_raw: bytes | None = None,
    compute_raw: bytes | None = None,
    unobserved_pids: list[int] | None = None,
) -> Path:
    rows = list(rows or [])
    gpu_raw = gpu_raw if gpu_raw is not None else f"{DEVICE}, {total_mib}\n".encode("ascii")
    compute_raw = compute_raw if compute_raw is not None else b"".join(
        f"{pid}, {gpu_uuid}, {memory}\n".encode("ascii")
        for pid, _create_time, gpu_uuid, memory in rows
    )
    commands: list[dict[str, object]] = []
    for index, (role, argv, raw, exit_code) in enumerate(
        (
            (
                "gpu_totals",
                [
                    "nvidia-smi.exe",
                    "--query-gpu=uuid,memory.used",
                    "--format=csv,noheader,nounits",
                ],
                gpu_raw,
                exits[0],
            ),
            (
                "compute_apps",
                [
                    "nvidia-smi.exe",
                    "--query-compute-apps=pid,gpu_uuid,used_gpu_memory",
                    "--format=csv,noheader,nounits",
                ],
                compute_raw,
                exits[1],
            ),
        )
    ):
        commands.append(
            {
                "role": role,
                "argv": argv,
                "started_at_utc": (at + timedelta(microseconds=index)).isoformat().replace("+00:00", "Z"),
                "finished_at_utc": (at + timedelta(microseconds=index + 1)).isoformat().replace("+00:00", "Z"),
                "execution_status": "timed_out" if timed_out[index] else "completed",
                "exit_code": None if timed_out[index] else exit_code,
                "os_error_code": None,
                "timed_out": timed_out[index],
                "stdout_raw": _stream(raw),
                "stderr_raw": _stream(b"timeout" if timed_out[index] else b"error" if exit_code else b""),
            }
        )
    unobserved = sorted(set(unobserved_pids or []))
    identities = [
        {"pid": pid, "create_time_ns": create_time}
        for pid, create_time in sorted(
            {
                (pid, create_time)
                for pid, create_time, _gpu_uuid, _memory in rows
                if pid not in unobserved
            }
        )
    ]
    process_snapshot = seal_immutable(
        {
            "contract_version": "benchmark_v2_process_identity_snapshot_v1",
            "observed_at_utc": (at + timedelta(microseconds=3)).isoformat().replace("+00:00", "Z"),
            "status": "partial" if unobserved else "complete",
            "identities": identities,
            "unobserved_pids": unobserved,
        }
    )
    return _write_json(
        path,
        seal_immutable(
            {
                "contract_version": "benchmark_v2_raw_gpu_sample_v1",
                "collection_mode": "production_direct" if observer_kind == "production_direct" else "test_fixture",
                "device_uuid": DEVICE,
                "observer_identity": _observer(observer_kind),
                "sample_started_at_utc": at.isoformat().replace("+00:00", "Z"),
                "sample_finished_at_utc": (at + timedelta(microseconds=4)).isoformat().replace("+00:00", "Z"),
                "commands": commands,
                "process_snapshot": process_snapshot,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        ),
    )


def _event(
    *, sequence: int, event_type: str, owner_id: str, previous: str, root_sha: str, payload: dict[str, object]
) -> dict[str, object]:
    return seal_immutable(
        {
            "contract_version": "portfolio_hybrid_benchmark_v2_window_owner_event_v1",
            "sequence": sequence,
            "event_type": event_type,
            "owner_id": owner_id,
            "previous_event_sha256": previous,
            "root_anchor_sha256": root_sha,
            "payload": payload,
        }
    )


def _parent_bundle(tmp_path: Path, *, operation_id: str = "operation-a") -> list[Path]:
    run_id = "run-a"
    stage = "screen_understanding"
    worker_id = "worker-a"
    model_request_id = "request-a"
    payload_sha = "1" * 64
    reservation_sha = "2" * 64
    window_identity = {"pid": 3101, "create_time_ns": 3101000}
    worker_identity = {"pid": 4101, "create_time_ns": 4101000}
    provider_identity = {"pid": 4201, "create_time_ns": 4201000}

    root_path = (tmp_path / "window-owner.json").resolve()
    events_path = root_path.with_name(root_path.name + ".events.jsonl")
    anchor_path = root_path.with_name(root_path.name + ".root-anchor.json")
    root = seal_immutable(
        {
            "contract_version": "portfolio_hybrid_benchmark_v2_window_owner_journal_v1",
            "owner_id": "window-owner-a",
            "operation_id": operation_id,
            "screenshot_path": str((tmp_path / "capture.png").resolve()),
            "screenshot_sha256": "3" * 64,
            "image_dimensions": {"width": 100, "height": 80},
            "bitmap_pixel_sha256": "4" * 64,
            "scope_name": "Local\\AgentGuiHybrid-window-owner-a",
            "window_class": "Task7FixtureWindow",
            "window_title": "Task 7 fixture",
            "shutdown_event_name": "Local\\Task7FixtureShutdown",
            "shutdown_nonce": "nonce-a",
            "journal_path": str(root_path),
            "events_path": str(events_path),
            "publication_path": str(root_path.with_name(root_path.name + ".publication.json")),
            "publication_permit_path": str(root_path.with_name(root_path.name + ".publication-permit.json")),
            "helper_path": str((tmp_path / "window-helper.exe").resolve()),
            "root_anchor_path": str(anchor_path),
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "display_only": True,
        }
    )
    _write_json(root_path, root)
    anchor_path.write_bytes(canonical_json_bytes(root))
    root_raw_sha = _sha(canonical_json_bytes(root))
    events: list[dict[str, object]] = []
    previous = SHA0
    for event_type, payload in (
        ("launch_intent", {"journal_root_sha256": root["content_sha256"]}),
        ("job_created", {"scope_name": root["scope_name"]}),
        ("process_created", {"process_identity": window_identity}),
    ):
        item = _event(
            sequence=len(events),
            event_type=event_type,
            owner_id=str(root["owner_id"]),
            previous=previous,
            root_sha=root_raw_sha,
            payload=payload,
        )
        events.append(item)
        previous = str(item["content_sha256"])
    publication = seal_immutable(
        {
            "contract_version": "portfolio_hybrid_benchmark_v2_hwnd_publication_v1",
            "owner_id": root["owner_id"],
            "screenshot_sha256": root["screenshot_sha256"],
            "raw_file_sha256": root["screenshot_sha256"],
            "bitmap_pixel_sha256": root["bitmap_pixel_sha256"],
            "shutdown_nonce_sha256": _sha(str(root["shutdown_nonce"]).encode("utf-8")),
            "process_identity": window_identity,
            "hwnd": 7001,
            "hwnds": [7001],
            "window_class": root["window_class"],
            "window_title": root["window_title"],
            "window_rect": {"left": 0, "top": 0, "right": 100, "bottom": 80},
            "client_rect": {"left": 0, "top": 0, "right": 100, "bottom": 80},
            "dpi": 96,
            "image_dimensions": root["image_dimensions"],
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "journal_root_sha256": root["content_sha256"],
            "expected_predecessor_sha256": previous,
            "permit_content_sha256": "5" * 64,
        }
    )
    publication_event = _event(
        sequence=len(events),
        event_type="hwnd_published",
        owner_id=str(root["owner_id"]),
        previous=previous,
        root_sha=root_raw_sha,
        payload={"publication": publication},
    )
    events.append(publication_event)
    previous = str(publication_event["content_sha256"])
    owner_binding = seal_immutable(
        {
            "contract_version": "portfolio_hybrid_benchmark_v2_window_binding_v1",
            "owner_id": root["owner_id"],
            "operation_id": operation_id,
            "screenshot_path": root["screenshot_path"],
            "screenshot_sha256": root["screenshot_sha256"],
            "bitmap_pixel_sha256": root["bitmap_pixel_sha256"],
            "scope_name": root["scope_name"],
            "process_identity": window_identity,
            "job_member_pids": [window_identity["pid"]],
            "hwnd": 7001,
            "window_class": root["window_class"],
            "window_title": root["window_title"],
            "window_rect": publication["window_rect"],
            "client_rect": publication["client_rect"],
            "dpi": 96,
            "image_dimensions": root["image_dimensions"],
            "journal_path": str(root_path),
            "journal_root_sha256": root["content_sha256"],
            "journal_root": root,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "display_only": True,
            "uia_root_identity": {"content_sha256": "6" * 64},
        }
    )
    ready_event = _event(
        sequence=len(events),
        event_type="ready",
        owner_id=str(root["owner_id"]),
        previous=previous,
        root_sha=root_raw_sha,
        payload={
            "binding": owner_binding,
            "pre_raw_identity_sha256": "7" * 64,
            "post_raw_identity_sha256": "7" * 64,
        },
    )
    events.append(ready_event)
    previous = str(ready_event["content_sha256"])
    finalization_event = _event(
        sequence=len(events),
        event_type="finalization_intent",
        owner_id=str(root["owner_id"]),
        previous=previous,
        root_sha=root_raw_sha,
        payload={"reason": "completed"},
    )
    events.append(finalization_event)
    previous = str(finalization_event["content_sha256"])
    cleanup = seal_immutable(
        {
            "contract_version": "portfolio_hybrid_benchmark_v2_window_cleanup_v1",
            "owner_id": root["owner_id"],
            "reason": "completed",
            "exact_hwnd": 7001,
            "process_identity": window_identity,
            "cleanup_subject_kind": "ready_window",
            "finalization_intent_sha256": events[-1]["content_sha256"],
            "process_event_sha256": events[2]["content_sha256"],
            "ready_event_sha256": ready_event["content_sha256"],
            "publication_content_sha256": publication["content_sha256"],
            "cleanup_status": "verified",
            "shutdown_event_name": root["shutdown_event_name"],
            "shutdown_event_signaled": True,
            "shutdown_event_error_code": None,
            "shutdown_event_handle_closed": True,
            "enum_windows_exact_hwnd_absent": True,
            "matching_owned_windows_after": [],
            "member_pids_after": [],
            "stable_zero_observations": 3,
            "scope_absent_after_owner_close": True,
            "process_handle_closed": True,
            "job_handle_closed": True,
            "active_listeners_after": [],
            "listener_or_lease_residue": [],
            "outer_owner_python_finally_observed": True,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    cleanup_event = _event(
        sequence=len(events),
        event_type="cleanup_verified",
        owner_id=str(root["owner_id"]),
        previous=previous,
        root_sha=root_raw_sha,
        payload=cleanup,
    )
    events.append(cleanup_event)
    events_path.write_bytes(b"".join(canonical_json_bytes(item) + b"\n" for item in events))

    serialized = {
        "contract_version": "portfolio_hybrid_benchmark_v2_worker_window_binding_v1",
        "operation_id": operation_id,
        "exact_hwnd": 7001,
        "process_identity": window_identity,
        "job_name": root["scope_name"],
        "job_membership_ref": seal_immutable(
            {
                "contract_version": "portfolio_hybrid_benchmark_v2_worker_job_membership_ref_v1",
                "job_name": root["scope_name"],
                "process_identity": window_identity,
                "member_pids": [window_identity["pid"]],
            }
        ),
        "screenshot_sha256": root["screenshot_sha256"],
        "capture_sha256": "5" * 64,
        "capture_image_path": root["screenshot_path"],
        "image_dimensions": root["image_dimensions"],
        "owner_journal_path": str(root_path),
        "owner_journal_content_sha256": root["content_sha256"],
        "owner_ready_event_sha256": ready_event["content_sha256"],
        "owner_binding_content_sha256": owner_binding["content_sha256"],
        "owner_id": root["owner_id"],
        "expected_uia_root_hwnd": 7001,
        "expected_uia_owner_pid": window_identity["pid"],
        "expected_uia_root_content_sha256": "7" * 64,
        "window_class": root["window_class"],
        "window_title": root["window_title"],
        "window_rect": {"left": 0, "top": 0, "right": 100, "bottom": 80},
        "client_rect": {"left": 0, "top": 0, "right": 100, "bottom": 80},
        "dpi": 96,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "display_only": True,
    }
    serialized["payload_sha256"] = _sha(canonical_json_bytes(serialized))
    authority = seal_immutable(
        {
            "contract_version": "benchmark_v2_worker_window_binding_authority_v1",
            "authority_kind": "test_fixture",
            "run_id": run_id,
            "stage": stage,
            "operation_id": operation_id,
            "window_binding_ref": {"id": root["owner_id"], "content_sha256": serialized["payload_sha256"]},
            "capture_ref": {"capture_id": "capture-a", "content_sha256": "5" * 64},
            "serialized_window_binding": serialized,
            "owner_binding_ref": {"content_sha256": owner_binding["content_sha256"]},
            "owner_journal_ref": {"content_sha256": root["content_sha256"]},
            "owner_ready_event_ref": {"content_sha256": ready_event["content_sha256"]},
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "predecessor_content_sha256": SHA0,
        }
    )
    authority_path = _write_json(tmp_path / "binding-authority.json", authority)
    normal_clear = seal_immutable(
        {
            "contract_version": "portfolio_hybrid_benchmark_v2_worker_window_binding_normal_clear_v1",
            "operation_id": operation_id,
            "binding_payload_sha256": serialized["payload_sha256"],
            "worker_pid": worker_identity["pid"],
            "cleared": True,
            "prior_binding_restored": False,
            "restored_hwnd": None,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    normal_clear_path = _write_json(tmp_path / "normal-clear.json", normal_clear)

    assignment = seal_immutable(
        {
            "contract_version": "benchmark_worker_scope_assignment_v1",
            "scope_name": "Local\\AgentGuiBenchmarkWorker-a",
            "process_identity": worker_identity,
            "observed_member_identities": [worker_identity],
            "job_policy": {"kill_on_close": True},
            "temporary_process_handle_close": _ref("8"),
            "temporary_job_handle_close": _ref("9"),
            "predecessor_content_sha256": "a" * 64,
        }
    )
    assignment_path = _write_json(tmp_path / "worker-assignment.json", assignment)
    worker_owner = seal_immutable(
        {
            "contract_version": "benchmark_worker_owner_journal_v1",
            "authority_kind": "test_fixture",
            "operation_anchor_ref": _ref("b"),
            "reservation_ref": {"content_sha256": reservation_sha},
            "supervision_ref": _ref("c"),
            "run_id": run_id,
            "stage": stage,
            "operation_id": operation_id,
            "worker_id": worker_id,
            "model_request_id": model_request_id,
            "payload_sha256": payload_sha,
            "execution_nonce": "nonce-worker-a",
            "scope_name": assignment["scope_name"],
            "supervisor_process_identity": {"pid": 4001, "create_time_ns": 4001000},
            "phase": "cleanup_finalization_intent",
            "process_identity": worker_identity,
            "beacon_ref": _ref("d"),
            "assignment_observation_ref": {"content_sha256": assignment["content_sha256"]},
            "job_policy": assignment["job_policy"],
            "gate_state": "released",
            "exit_observation_ref": _ref("e"),
            "stable_zero_observation_ref": _ref("f"),
            "exact_handle_observation_refs": [_ref("1"), _ref("2")],
            "cleanup_finalization_intent": _ref("3"),
            "cleanup_receipt_ref": None,
            "predecessor_content_sha256": assignment["content_sha256"],
        }
    )
    worker_owner_path = _write_json(tmp_path / "worker-owner.json", worker_owner)
    worker_cleanup = seal_immutable(
        {
            "contract_version": "benchmark_worker_cleanup_receipt_v1",
            "outcome": "verified_exact_worker_exited",
            "operation_anchor_ref": worker_owner["operation_anchor_ref"],
            "reservation_ref": worker_owner["reservation_ref"],
            "supervision_ref": worker_owner["supervision_ref"],
            "run_id": run_id,
            "stage": stage,
            "operation_id": operation_id,
            "worker_id": worker_id,
            "process_identity": worker_identity,
            "assignment_proven_ref": {"content_sha256": assignment["content_sha256"]},
            "finalization_intent_ref": worker_owner["cleanup_finalization_intent"],
            "exact_handle_observation_refs": worker_owner["exact_handle_observation_refs"],
            "job_absence_observation_ref": _ref("4"),
            "worker_absence_observation_ref": _ref("5"),
            "supervisor_absence_observation_ref": None,
            "reservation_abort_ref": None,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    worker_cleanup_path = _write_json(tmp_path / "worker-cleanup.json", worker_cleanup)

    runtime_owner = seal_immutable(
        {
            "contract_version": "benchmark_provider_runtime_owner_v1",
            "authority_kind": "test_fixture",
            "run_id": run_id,
            "stage": stage,
            "operation_id": operation_id,
            "worker_id": worker_id,
            "model_request_id": model_request_id,
            "reservation_ref": worker_owner["reservation_ref"],
            "payload_sha256": payload_sha,
        }
    )
    runtime_owner_path = _write_json(tmp_path / "runtime-owner.json", runtime_owner)
    ledger = seal_immutable(
        {
            "contract_version": "qwen_model_request_materialization_ledger_v1",
            "model_request_id": model_request_id,
            "acquisition_intent_ref": _ref("6"),
            "runtime_owner_ref": {"content_sha256": runtime_owner["content_sha256"]},
            "state": "materialization_possible",
            "revision": 1,
            "transition": "launch",
            "predecessor_content_sha256": "7" * 64,
        }
    )
    ledger_path = _write_json(tmp_path / "materialization-ledger.json", ledger)
    provider_journal = seal_immutable(
        {
            "contract_version": "benchmark_provider_registry_journal_v1",
            "authority_kind": "test_fixture",
            "run_id": run_id,
            "stage": stage,
            "operation_id": operation_id,
            "worker_id": worker_id,
            "model_request_id": model_request_id,
            "payload_sha256": payload_sha,
            "reservation_ref": worker_owner["reservation_ref"],
            "runtime_owner_ref": {"content_sha256": runtime_owner["content_sha256"]},
            "acquisition_owner_ref": _ref("8"),
            "acquisition_intent_ref": ledger["acquisition_intent_ref"],
            "prepared_acquisition_observation_ref": _ref("9"),
            "prepared_materialization_ledger_ref": _ref("a"),
            "acquisition_observation_ref": _ref("b"),
            "materialization_ledger_ref": {"content_sha256": ledger["content_sha256"]},
        }
    )
    provider_journal_path = _write_json(tmp_path / "provider-journal.json", provider_journal)
    provider_cleanup = seal_immutable(
        {
            "contract_version": "qwen_model_request_cleanup_receipt_v1",
            "outcome": "verified_exact_process_exited",
            "model_request_id": model_request_id,
            "acquisition_intent_ref": ledger["acquisition_intent_ref"],
            "runtime_owner_ref": {"content_sha256": runtime_owner["content_sha256"]},
            "lease_ref": _ref("c"),
            "profile_ref": _ref("d"),
            "server_process_identity": provider_identity,
            "socket_ref": _ref("e"),
            "job_scope_ref": _ref("f"),
            "finalization_token": "token-a",
            "lease_state_ref": _ref("1"),
            "owner_tombstone_ref": _ref("2"),
            "release_reason": "completed",
            "termination_observation_ref": _ref("3"),
            "scope_stable_zero_ref": _ref("4"),
            "listener_stable_zero_ref": _ref("5"),
            "no_active_lease_observation_ref": _ref("6"),
            "no_owned_runtime_observation_ref": None,
        }
    )
    provider_cleanup_path = _write_json(tmp_path / "provider-cleanup.json", provider_cleanup)
    return [
        root_path,
        authority_path,
        normal_clear_path,
        assignment_path,
        worker_owner_path,
        worker_cleanup_path,
        runtime_owner_path,
        ledger_path,
        provider_journal_path,
        provider_cleanup_path,
    ]


def _probe(path: Path, *, provider: str, kind: str, body_state: str = "not_complete", residue: str | None = None) -> Path:
    profile = {"provider_id": provider, "profile_id": f"{provider}-profile"}
    profile_sha = _sha(canonical_json_bytes(profile))
    pid = 7000 + {"omni": 1, "qwen": 2, "vista": 3}[provider]
    identity = {"pid": pid, "create_time_ns": pid * 1000}
    start = datetime(2026, 8, 27, 1, 0, tzinfo=timezone.utc)
    zero = {"job_members": [], "active_listeners": [], "active_leases": []}
    if residue == "job":
        zero["job_members"] = [identity]
    elif residue == "listener":
        zero["active_listeners"] = [{"pid": pid, "port": 9000}]
    elif residue == "lease":
        zero["active_leases"] = ["lease-a"]
    receipt = seal_immutable(
        {
            "contract_version": "benchmark_v2_lifecycle_probe_receipt_v1",
            "probe_id": f"probe/{provider}/{kind}",
            "probe_kind": kind,
            "provider": {**profile, "profile_sha256": profile_sha},
            "run_id": "run-a",
            "stage": "screen_understanding",
            "operation_id": "operation-a",
            "model_request_id": "request-a",
            "request_in_flight_observation": {
                "state": "request_in_flight",
                "observed_at_utc": start.isoformat().replace("+00:00", "Z"),
                "evidence_ref": _ref("1"),
            },
            "trigger": {
                "kind": kind,
                "triggered_at_utc": (start + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
                "request_in_flight_ref": _ref("1"),
            },
            "body_completion_observation": {
                "state": body_state,
                "observed_at_utc": (start + timedelta(seconds=2)).isoformat().replace("+00:00", "Z"),
                "evidence_ref": _ref("2"),
            },
            "lease_or_owner": {
                "lease_ref": _ref("3"),
                "socket_ref": _ref("4"),
                "process_identity": identity,
                "job_scope_ref": _ref("5"),
            },
            "termination_observation": {
                "outcome": "same_incarnation_exited",
                "process_identity": identity,
                "evidence_ref": _ref("6"),
            },
            "stable_zero_observation": {
                **zero,
                "stable_zero_observations": 3,
                "process_absence_ref": _ref("7"),
                "listener_absence_ref": _ref("8"),
                "lease_absence_ref": _ref("9"),
            },
            "observer_identity": seal_immutable(
                {
                    "kind": "test_fixture",
                    "module_ref": {
                        "canonical_path": "test-fixture/probe-runner.py",
                        "file_sha256": "a" * 64,
                    },
                }
            ),
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "predecessor_content_sha256": SHA0,
        }
    )
    return _write_json(path, receipt)


def _happy_inputs(tmp_path: Path) -> tuple[list[Path], list[Path], list[Path]]:
    parents = _parent_bundle(tmp_path / "parents")
    start = datetime(2026, 8, 27, tzinfo=timezone.utc)
    external = (5101, 5101000, DEVICE, 100)
    owned = [
        (3101, 3101000, DEVICE, 0),
        (4101, 4101000, DEVICE, 400),
        (4201, 4201000, DEVICE, 0),
    ]
    samples = [
        _sample(tmp_path / "baseline.json", at=start, rows=[external]),
        _sample(tmp_path / "in-flight.json", at=start + timedelta(seconds=1), total_mib=1000, rows=[*owned, external]),
        _sample(tmp_path / "post.json", at=start + timedelta(seconds=2), rows=[external]),
    ]
    probes = [
        _probe(tmp_path / f"probe-{provider}-{kind}.json", provider=provider, kind=kind)
        for provider in ("omni", "qwen", "vista")
        for kind in ("cancel", "timeout")
    ]
    return parents, samples, probes


def _verify(parents: list[Path], samples: list[Path], probes: list[Path], *, actual_mode: bool = False) -> dict[str, object]:
    return verify_lifecycle_from_raw(
        owner_journal_paths=parents,
        sampler_transcript_paths=samples,
        probe_receipt_paths=probes,
        actual_mode=actual_mode,
    )


def _mutate(path: Path, update) -> None:
    import json

    value = json.loads(path.read_bytes().decode("utf-8"))
    update(value)
    _write_json(path, seal_immutable({key: item for key, item in value.items() if key != "content_sha256"}))


def test_collect_raw_gpu_sample_runs_only_two_fixed_nvidia_smi_queries_and_preserves_raw_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], bool, float]] = []
    outputs = [(b"GPU-a, 1000\n", b"\xffwarn", 0), (b"4101, GPU-a, 400\n", b"", 0)]

    def fake_run(argv: list[str], *, shell: bool, timeout_seconds: float) -> dict[str, object]:
        calls.append((list(argv), shell, timeout_seconds))
        stdout, stderr, code = outputs[len(calls) - 1]
        return {
            "execution_status": "completed",
            "exit_code": code,
            "os_error_code": None,
            "timed_out": False,
            "stdout": stdout,
            "stderr": stderr,
        }

    monkeypatch.setattr(lifecycle, "_run_fixed_nvidia_smi_query", fake_run)
    monkeypatch.setattr(lifecycle, "_observe_pid_create_times", lambda pids: ({4101: 4101000}, []))
    monkeypatch.setattr(lifecycle, "_production_gpu_observer_identity", lambda: _observer("production_direct"))
    path = tmp_path / "sample.json"
    result = collect_raw_gpu_sample(device_uuid="GPU-a", transcript_path=path)
    assert [item[0] for item in calls] == [
        ["nvidia-smi.exe", "--query-gpu=uuid,memory.used", "--format=csv,noheader,nounits"],
        ["nvidia-smi.exe", "--query-compute-apps=pid,gpu_uuid,used_gpu_memory", "--format=csv,noheader,nounits"],
    ]
    assert all(shell is False and 0 < timeout <= 30 for _argv, shell, timeout in calls)
    assert base64.b64decode(result["commands"][0]["stdout_raw"]["data_base64"]) == outputs[0][0]
    assert base64.b64decode(result["commands"][0]["stderr_raw"]["data_base64"]) == outputs[0][1]
    assert path.read_bytes() == canonical_json_bytes(result)
    assert collect_raw_gpu_sample(device_uuid="GPU-a", transcript_path=path) == result
    assert len(calls) == 2


def test_collect_raw_gpu_sample_preserves_nonzero_exit_and_never_converts_failure_to_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    replies = iter(
        [
            {"execution_status": "completed", "exit_code": 9, "os_error_code": None, "timed_out": False, "stdout": b"", "stderr": b"driver error"},
            {"execution_status": "timed_out", "exit_code": None, "os_error_code": None, "timed_out": True, "stdout": b"partial", "stderr": b"timeout"},
        ]
    )
    monkeypatch.setattr(lifecycle, "_run_fixed_nvidia_smi_query", lambda *args, **kwargs: next(replies))
    monkeypatch.setattr(lifecycle, "_observe_pid_create_times", lambda pids: ({}, []))
    monkeypatch.setattr(lifecycle, "_production_gpu_observer_identity", lambda: _observer("production_direct"))
    path = tmp_path / "failed-sample.json"
    result = collect_raw_gpu_sample(device_uuid=DEVICE, transcript_path=path)
    assert result["commands"][0]["exit_code"] == 9
    assert result["commands"][1]["timed_out"] is True
    assert "parsed_zero" not in result


@pytest.mark.parametrize("gpu_stdout", [b"GPU-b, 1000\n", b"GPU-a, 1000\nGPU-a, 1000\n"])
def test_collect_raw_gpu_sample_requires_one_exact_requested_gpu_uuid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gpu_stdout: bytes,
) -> None:
    def fake_run(argv: list[str], *, shell: bool, timeout_seconds: float) -> dict[str, object]:
        return {
            "execution_status": "completed",
            "exit_code": 0,
            "os_error_code": None,
            "timed_out": False,
            "stdout": gpu_stdout if "--query-gpu=uuid,memory.used" in argv else b"",
            "stderr": b"",
        }

    monkeypatch.setattr(lifecycle, "_run_fixed_nvidia_smi_query", fake_run)
    monkeypatch.setattr(lifecycle, "_observe_pid_create_times", lambda pids: ({}, []))
    monkeypatch.setattr(lifecycle, "_production_gpu_observer_identity", lambda: _observer("production_direct"))
    path = tmp_path / "requested-device-failure.json"
    with pytest.raises(ValueError, match="requested GPU UUID|GPU totals are malformed"):
        collect_raw_gpu_sample(device_uuid=DEVICE, transcript_path=path)
    assert path.is_file()
    assert b"parsed_zero" not in path.read_bytes()


def test_lifecycle_public_api_exposes_no_command_observer_or_cleanup_injection() -> None:
    assert list(inspect.signature(collect_raw_gpu_sample).parameters) == ["device_uuid", "transcript_path"]
    assert list(inspect.signature(verify_lifecycle_from_raw).parameters) == [
        "owner_journal_paths",
        "sampler_transcript_paths",
        "probe_receipt_paths",
        "actual_mode",
    ]
    assert lifecycle.__all__ == ["collect_raw_gpu_sample", "verify_lifecycle_from_raw"]


def test_verify_lifecycle_canonical_fixture_is_deterministic_and_non_authorizing(tmp_path: Path) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    before = {path: path.read_bytes() for path in [*parents, *samples, *probes]}
    first = _verify(parents, samples, probes)
    second = _verify(list(reversed(parents)), list(reversed(samples)), list(reversed(probes)))
    assert first == second
    assert first["status"] == "verified_fixture"
    assert first["release_eligible"] is False
    assert first["artifact_is_authorization"] is False
    assert first["execute_binding_enabled"] is False
    assert first["content_sha256"] == lifecycle._content_sha256(first)
    assert {path: path.read_bytes() for path in [*parents, *samples, *probes]} == before


def test_verify_lifecycle_attributes_owned_vram_and_reports_residual_separately(tmp_path: Path) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    result = _verify(parents, samples, probes)
    gpu = result["gpu_summary"]
    assert gpu["owned_peak_mib"] == 400
    assert gpu["owned_post_mib"] == 0
    assert gpu["device_used_baseline_mib"] == 600
    assert gpu["device_residual_baseline_mib"] == 500
    assert gpu["device_residual_post_mib"] == 500
    assert gpu["external_fingerprint_baseline"] == [[5101, 5101000, DEVICE, 100]]


def test_verify_lifecycle_keeps_non_target_gpu_rows_separate(tmp_path: Path) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    start = datetime(2026, 8, 27, tzinfo=timezone.utc)
    samples[1] = _sample(
        tmp_path / "mixed-device.json",
        at=start + timedelta(seconds=1),
        total_mib=1000,
        rows=[
            (3101, 3101000, DEVICE, 0),
            (4101, 4101000, DEVICE, 400),
            (4101, 4101000, "GPU-b", 900),
            (4201, 4201000, DEVICE, 0),
            (5101, 5101000, DEVICE, 100),
        ],
        gpu_raw=b"GPU-a, 1000\nGPU-b, 900\n",
    )
    result = _verify(parents, samples, probes)
    assert result["gpu_summary"]["owned_peak_mib"] == 400


@pytest.mark.parametrize("mode", ["memory", "pid", "incarnation", "device"])
def test_verify_lifecycle_external_fingerprint_change_is_indeterminate_not_zero(tmp_path: Path, mode: str) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    start = datetime(2026, 8, 27, tzinfo=timezone.utc)
    external = {
        "memory": (5101, 5101000, DEVICE, 101),
        "pid": (5102, 5102000, DEVICE, 100),
        "incarnation": (5101, 5101001, DEVICE, 100),
        "device": (5101, 5101000, "GPU-b", 100),
    }[mode]
    gpu_raw = b"GPU-a, 600\nGPU-b, 100\n" if mode == "device" else None
    samples[2] = _sample(tmp_path / f"post-{mode}.json", at=start + timedelta(seconds=2), rows=[external], gpu_raw=gpu_raw)
    result = _verify(parents, samples, probes)
    assert result["status"] == "indeterminate"
    assert result["gpu_summary"]["external_fingerprint_status"] == "changed"


def test_verify_lifecycle_pid_reuse_is_not_attributed_to_old_owner(tmp_path: Path) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    start = datetime(2026, 8, 27, tzinfo=timezone.utc)
    samples[1] = _sample(
        tmp_path / "pid-reuse.json",
        at=start + timedelta(seconds=1),
        total_mib=1000,
        rows=[
            (3101, 3101000, DEVICE, 0),
            (4101, 9999999, DEVICE, 400),
            (4201, 4201000, DEVICE, 0),
            (5101, 5101000, DEVICE, 100),
        ],
    )
    result = _verify(parents, samples, probes)
    assert result["status"] == "failed"
    assert result["gpu_summary"]["owned_peak_mib"] == 0
    assert any(item["code"] == "owned_pid_reuse" for item in result["findings"])


def test_verify_lifecycle_total_zero_missing_identity_never_becomes_verified_cleanup(tmp_path: Path) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    start = datetime(2026, 8, 27, tzinfo=timezone.utc)
    samples[2] = _sample(
        tmp_path / "post-zero.json",
        at=start + timedelta(seconds=2),
        total_mib=0,
        rows=[],
        unobserved_pids=[4101],
    )
    result = _verify(parents, samples, probes)
    assert result["status"] == "indeterminate"
    assert result["gpu_summary"]["owned_post_mib"] is None


@pytest.mark.parametrize(
    ("gpu_raw", "compute_raw", "exits", "timed_out"),
    [
        (b"GPU-a, N/A\n", b"", (0, 0), (False, False)),
        (b"GPU-a, 600\n", b"bad,row\n", (0, 0), (False, False)),
        (b"GPU-a, 600\nGPU-a, 600\n", b"", (0, 0), (False, False)),
        (b"GPU-a, 600\n", b"", (3, 0), (False, False)),
        (b"GPU-a, 600\n", b"", (0, 0), (True, False)),
    ],
)
def test_command_failure_na_malformed_and_duplicate_rows_never_become_zero(
    tmp_path: Path,
    gpu_raw: bytes,
    compute_raw: bytes,
    exits: tuple[int, int],
    timed_out: tuple[bool, bool],
) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    start = datetime(2026, 8, 27, tzinfo=timezone.utc)
    samples[0] = _sample(
        tmp_path / "bad-baseline.json",
        at=start,
        rows=[],
        gpu_raw=gpu_raw,
        compute_raw=compute_raw,
        exits=exits,
        timed_out=timed_out,
    )
    result = _verify(parents, samples, probes)
    assert result["status"] in {"failed", "indeterminate"}
    assert result["gpu_summary"]["device_used_baseline_mib"] is None


def test_verify_lifecycle_rejects_forged_and_cross_operation_parent_chain(tmp_path: Path) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    authority = next(path for path in parents if path.name == "binding-authority.json")
    _mutate(authority, lambda value: value.__setitem__("operation_id", "operation-b"))
    result = _verify(parents, samples, probes)
    assert result["status"] == "failed"
    assert any(item["code"] == "cross_operation_parent" for item in result["findings"])


def test_verify_lifecycle_rejects_forged_task5_owner_event_parent(tmp_path: Path) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    authority = next(path for path in parents if path.name == "binding-authority.json")
    _mutate(
        authority,
        lambda value: value.__setitem__("owner_ready_event_ref", {"content_sha256": "f" * 64}),
    )
    result = _verify(parents, samples, probes)
    assert result["status"] == "failed"
    assert any(item["code"] == "task4_task5_parent_mismatch" for item in result["findings"])


def test_verify_lifecycle_rejects_self_hash_drift(tmp_path: Path) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    raw = bytearray(samples[0].read_bytes())
    raw[-2] = ord("0") if raw[-2] != ord("0") else ord("1")
    samples[0].write_bytes(bytes(raw))
    assert _verify(parents, samples, probes)["status"] == "failed"


def test_verify_lifecycle_same_kind_owner_overlap_count_two_is_failed(tmp_path: Path) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    owner_path = next(path for path in parents if path.name == "worker-owner.json")
    import json

    duplicate = json.loads(owner_path.read_text(encoding="utf-8"))
    duplicate["worker_id"] = "worker-b"
    duplicate["process_identity"] = {"pid": 4102, "create_time_ns": 4102000}
    duplicate["content_sha256"] = lifecycle._content_sha256(duplicate)
    parents.append(_write_json(tmp_path / "second-worker-owner.json", duplicate))
    start = datetime(2026, 8, 27, tzinfo=timezone.utc)
    samples[1] = _sample(
        tmp_path / "overlap.json",
        at=start + timedelta(seconds=1),
        total_mib=1000,
        rows=[
            (3101, 3101000, DEVICE, 0),
            (4101, 4101000, DEVICE, 200),
            (4102, 4102000, DEVICE, 200),
            (4201, 4201000, DEVICE, 0),
            (5101, 5101000, DEVICE, 100),
        ],
    )
    result = _verify(parents, samples, probes)
    assert result["status"] == "failed"
    assert result["owner_summary"]["max_concurrent_by_kind"]["outer_worker"] == 2


def test_verify_lifecycle_missing_owner_interval_bound_is_indeterminate(tmp_path: Path) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    samples = samples[1:]
    result = _verify(parents, samples, probes)
    assert result["status"] == "indeterminate"
    assert result["owner_summary"]["overlap_status"] == "indeterminate"


@pytest.mark.parametrize("case", ["missing", "duplicate", "extra"])
def test_probe_matrix_requires_exact_six_cells(tmp_path: Path, case: str) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    if case == "missing":
        probes.pop()
    elif case == "duplicate":
        probes.append(probes[0])
    else:
        extra = _probe(tmp_path / "probe-extra.json", provider="omni", kind="cancel")
        _mutate(extra, lambda value: value["provider"].__setitem__("provider_id", "other"))
        probes.append(extra)
    result = _verify(parents, samples, probes)
    assert result["status"] == "failed"


def test_unknown_timeout_body_is_indeterminate_but_relabelled_completion_is_failed(tmp_path: Path) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    timeout_probe = next(path for path in probes if path.name == "probe-qwen-timeout.json")
    _mutate(timeout_probe, lambda value: value["body_completion_observation"].__setitem__("state", "unknown"))
    assert _verify(parents, samples, probes)["status"] == "indeterminate"
    _mutate(timeout_probe, lambda value: value["body_completion_observation"].__setitem__("state", "complete"))
    assert _verify(parents, samples, probes)["status"] == "failed"


@pytest.mark.parametrize("residue", ["job", "listener", "lease"])
def test_positive_probe_residue_is_failed(tmp_path: Path, residue: str) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    probes[-1] = _probe(tmp_path / f"probe-residue-{residue}.json", provider="vista", kind="timeout", residue=residue)
    result = _verify(parents, samples, probes)
    assert result["status"] == "failed"
    assert any(item["code"] == "probe_residue" for item in result["findings"])


def test_materialized_without_lease_or_terminal_sidecar_remains_indeterminate(tmp_path: Path) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    parents = [path for path in parents if path.name != "provider-cleanup.json"]
    result = _verify(parents, samples, probes)
    assert result["status"] == "indeterminate"
    assert result["cleanup_summary"]["provider"] == "pending_materialized"


def test_verify_lifecycle_accepts_b2_cleanup_registry_journal_as_raw_parent(tmp_path: Path) -> None:
    import json

    parents, samples, probes = _happy_inputs(tmp_path)
    provider_journal_path = next(path for path in parents if path.name == "provider-journal.json")
    provider_journal = json.loads(provider_journal_path.read_text(encoding="utf-8"))
    provider_cleanup = json.loads(
        next(path for path in parents if path.name == "provider-cleanup.json").read_text(encoding="utf-8")
    )
    cleanup_journal = seal_immutable(
        {
            "contract_version": "benchmark_provider_cleanup_registry_journal_v1",
            "authority_kind": provider_journal["authority_kind"],
            "run_id": provider_journal["run_id"],
            "stage": provider_journal["stage"],
            "operation_id": provider_journal["operation_id"],
            "worker_id": provider_journal["worker_id"],
            "model_request_id": provider_journal["model_request_id"],
            "payload_sha256": provider_journal["payload_sha256"],
            "reservation_ref": provider_journal["reservation_ref"],
            "runtime_owner_ref": provider_journal["runtime_owner_ref"],
            "acquisition_owner_ref": provider_journal["acquisition_owner_ref"],
            "acquisition_intent_ref": provider_journal["acquisition_intent_ref"],
            "cleanup_receipt_ref": {"content_sha256": provider_cleanup["content_sha256"]},
        }
    )
    parents.remove(provider_journal_path)
    parents.append(_write_json(tmp_path / "provider-cleanup-journal.json", cleanup_journal))
    assert _verify(parents, samples, probes)["status"] == "verified_fixture"


def test_verify_lifecycle_not_launched_not_acquired_is_not_fabricated_zero(tmp_path: Path) -> None:
    import json

    parents, samples, probes = _happy_inputs(tmp_path)
    parents = [
        path
        for path in parents
        if path.name not in {"worker-assignment.json", "normal-clear.json"}
    ]
    owner_path = next(path for path in parents if path.name == "worker-owner.json")
    _mutate(
        owner_path,
        lambda value: value.update(
            {
                "phase": "acquiring",
                "scope_name": None,
                "process_identity": None,
                "assignment_observation_ref": None,
                "job_policy": None,
                "gate_state": "not_released",
                "exit_observation_ref": None,
                "stable_zero_observation_ref": None,
                "exact_handle_observation_refs": [],
                "cleanup_finalization_intent": None,
            }
        ),
    )
    cleanup_path = next(path for path in parents if path.name == "worker-cleanup.json")
    _mutate(
        cleanup_path,
        lambda value: value.update(
            {
                "outcome": "verified_not_launched",
                "process_identity": None,
                "assignment_proven_ref": None,
                "finalization_intent_ref": None,
                "exact_handle_observation_refs": [],
                "job_absence_observation_ref": None,
                "worker_absence_observation_ref": None,
                "reservation_abort_ref": _ref("a"),
            }
        ),
    )
    ledger_path = next(path for path in parents if path.name == "materialization-ledger.json")
    _mutate(
        ledger_path,
        lambda value: value.update(
            {"state": "aborted_never_materialized", "transition": "abort"}
        ),
    )
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    journal_path = next(path for path in parents if path.name == "provider-journal.json")
    _mutate(
        journal_path,
        lambda value: value.__setitem__(
            "materialization_ledger_ref", {"content_sha256": ledger["content_sha256"]}
        ),
    )
    provider_cleanup_path = next(path for path in parents if path.name == "provider-cleanup.json")
    _mutate(
        provider_cleanup_path,
        lambda value: value.update(
            {
                "outcome": "verified_not_acquired",
                "lease_ref": None,
                "profile_ref": None,
                "server_process_identity": None,
                "socket_ref": None,
                "job_scope_ref": None,
                "finalization_token": None,
                "lease_state_ref": None,
                "termination_observation_ref": None,
                "no_owned_runtime_observation_ref": _ref("b"),
            }
        ),
    )
    start = datetime(2026, 8, 27, tzinfo=timezone.utc)
    external = (5101, 5101000, DEVICE, 100)
    samples[1] = _sample(
        tmp_path / "not-launched-in-flight.json",
        at=start + timedelta(seconds=1),
        rows=[(3101, 3101000, DEVICE, 0), external],
    )
    result = _verify(parents, samples, probes)
    assert result["status"] == "verified_fixture"
    assert result["cleanup_summary"]["worker"] == "verified_not_launched"
    assert result["cleanup_summary"]["provider"] == "verified_not_acquired"
    assert all(item["pid"] not in {4101, 4201} for item in result["gpu_summary"]["owned_process_vram"])


def test_actual_mode_rejects_fixture_or_relabelled_observer_identity(tmp_path: Path) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    result = _verify(parents, samples, probes, actual_mode=True)
    assert result["status"] == "failed"
    assert result["release_eligible"] is False
    _mutate(samples[0], lambda value: value["observer_identity"].__setitem__("kind", "production_direct"))
    relabelled = _verify(parents, samples, probes, actual_mode=True)
    assert relabelled["status"] == "failed"


def test_path_alias_duplicate_and_noncanonical_json_are_rejected(tmp_path: Path) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    duplicate = _verify(parents, [samples[0], samples[0], *samples[1:]], probes)
    assert duplicate["status"] == "failed"
    samples[0].write_bytes(samples[0].read_bytes() + b"\n")
    assert _verify(parents, samples, probes)["status"] == "failed"
