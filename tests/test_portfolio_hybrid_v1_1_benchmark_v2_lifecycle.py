from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
from pathlib import Path
import struct

import pytest

from app.learn.hybrid import benchmark_v2_lifecycle as lifecycle
from app.learn.hybrid import benchmark_v2_window_owner as window_owner
from app.learn.hybrid import benchmark_v2_worker_binding as worker_binding
from app.learn import workflow_worker
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


def _bmp(*, width: int = 100, height: int = 80) -> bytes:
    stride = ((width * 24 + 31) // 32) * 4
    pixels = bytes(stride * height)
    size = 54 + len(pixels)
    return b"".join(
        (
            b"BM",
            struct.pack("<IHHI", size, 0, 0, 54),
            struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(pixels), 0, 0, 0, 0),
            pixels,
        )
    )


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
            "platform": "windows" if kind == "production_direct" else "test",
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
    inventory: list[tuple[int, int]] | None = None,
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
    inventory_rows = inventory if inventory is not None else [
        (pid, create_time) for pid, create_time, _gpu_uuid, _memory in rows
    ]
    identities = [
        {"pid": pid, "create_time_ns": create_time}
        for pid, create_time in sorted(
            {
                (pid, create_time)
                for pid, create_time in inventory_rows
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
    capture_path = (tmp_path / "capture.bmp").resolve()
    capture_path.parent.mkdir(parents=True, exist_ok=True)
    capture_path.write_bytes(_bmp())
    capture_sha = _sha(capture_path.read_bytes())

    root_path = (tmp_path / "window-owner.json").resolve()
    events_path = root_path.with_name(root_path.name + ".events.jsonl")
    anchor_path = window_owner._root_anchor_path(root_path)
    root_identity = window_owner._identity(operation_id, capture_sha, root_path)
    bitmap = window_owner._parse_bmp(capture_path.read_bytes())
    root = seal_immutable(
        {
            "contract_version": "portfolio_hybrid_benchmark_v2_window_owner_journal_v1",
            "owner_id": root_identity["owner_id"],
            "operation_id": operation_id,
            "screenshot_path": str(capture_path),
            "screenshot_sha256": capture_sha,
            "image_dimensions": bitmap["dimensions"],
            "bitmap_pixel_sha256": bitmap["bitmap_pixel_sha256"],
            "scope_name": root_identity["scope_name"],
            "window_class": root_identity["window_class"],
            "window_title": root_identity["window_title"],
            "shutdown_event_name": root_identity["shutdown_event_name"],
            "shutdown_nonce": root_identity["shutdown_nonce"],
            "journal_path": str(root_path),
            "events_path": str(events_path),
            "publication_path": str(root_path.with_name(root_path.name + ".publication.json")),
            "publication_permit_path": str(root_path.with_name(root_path.name + ".publication-permit.json")),
            "helper_path": str(window_owner._helper_path()),
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
    permit = seal_immutable(
        {
            "contract_version": "portfolio_hybrid_benchmark_v2_hwnd_publication_permit_v1",
            "owner_id": root["owner_id"],
            "journal_root_sha256": root["content_sha256"],
            "expected_predecessor_sha256": previous,
        }
    )
    _write_json(Path(str(root["publication_permit_path"])), permit)
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
            "client_rect": {"left": 0, "top": 0, "right": 100, "bottom": 80, "width": 100, "height": 80},
            "dpi": 96,
            "image_dimensions": root["image_dimensions"],
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "journal_root_sha256": root["content_sha256"],
            "expected_predecessor_sha256": previous,
            "permit_content_sha256": permit["content_sha256"],
        }
    )
    _write_json(Path(str(root["publication_path"])), publication)
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
    uia_identity = seal_immutable(
        {
            "provider": "windows_uia",
            "provider_version": "fixture-v1",
            "window_handle": 7001,
            "window_process_id": window_identity["pid"],
            "window_title": root["window_title"],
            "root_control": {
                "control_id": "fixture-root",
                "name": root["window_title"],
                "control_type": "Window",
                "automation_id": None,
                "class_name": root["window_class"],
                "screen_bbox": publication["window_rect"],
            },
        }
    )
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
            "uia_root_identity": uia_identity,
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
        "capture_sha256": root["screenshot_sha256"],
        "capture_image_path": root["screenshot_path"],
        "image_dimensions": root["image_dimensions"],
        "owner_journal_path": str(root_path),
        "owner_journal_content_sha256": root["content_sha256"],
        "owner_ready_event_sha256": ready_event["content_sha256"],
        "owner_binding_content_sha256": owner_binding["content_sha256"],
        "owner_id": root["owner_id"],
        "expected_uia_root_hwnd": 7001,
        "expected_uia_owner_pid": window_identity["pid"],
        "expected_uia_root_content_sha256": owner_binding["uia_root_identity"]["content_sha256"],
        "window_class": root["window_class"],
        "window_title": root["window_title"],
        "window_rect": {"left": 0, "top": 0, "right": 100, "bottom": 80},
        "client_rect": {"left": 0, "top": 0, "right": 100, "bottom": 80, "width": 100, "height": 80},
        "dpi": 96,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "display_only": True,
    }
    serialized["payload_sha256"] = _sha(canonical_json_bytes(serialized))
    serialized = worker_binding._validate_serialized(serialized)
    authority = worker_binding._server_binding_authority(
        authority_kind="test_fixture",
        run_id=run_id,
        stage=stage,
        operation_id=operation_id,
        window_binding_ref={"id": root["owner_id"], "content_sha256": serialized["payload_sha256"]},
        capture_ref={"capture_id": "capture-a", "content_sha256": root["screenshot_sha256"]},
        serialized=serialized,
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

    corpus_ref = seal_immutable(
        {
            "contract_version": "benchmark_v2_provider_corpus_file_ref_v1",
            "relative_path": "provider-corpus.v2.json",
            "file_sha256": "8" * 64,
            "source_parent_ref": {"content_sha256": root["content_sha256"]},
        }
    )
    source = seal_immutable(
        {
            "contract_version": "benchmark_v2_incumbent_handler_payload_source_v1",
            "provider_corpus_file_ref": corpus_ref,
            "provider_case_ref": {"case_id": "case-a", "case_content_sha256": "9" * 64},
            "projection_contract_version": "benchmark_v2_observe_screen_payload_projection_v1",
            "projection_rules_content_sha256": "a" * 64,
            "window_binding_ref": authority["window_binding_ref"],
            "capture_ref": {"id": "capture-a", "content_sha256": root["screenshot_sha256"]},
            "handler_payload_sha256": payload_sha,
            "predecessor_content_sha256": corpus_ref["content_sha256"],
        }
    )
    source_path = _write_json(tmp_path / "handler-payload-source.json", source)

    class _Store:
        def get(self, run: str) -> dict[str, object]:
            return {"run_id": run}

    supervision_root = workflow_worker.compose_test_benchmark_worker_supervision_root(
        journal_root=tmp_path,
        test_capability=object(),
        workflow_store=_Store(),
        test_store_capability=object(),
    )
    supervision_inputs_ref = workflow_worker._benchmark_supervision_inputs_ref(supervision_root)
    reservation = seal_immutable(
        {
            "contract_version": "benchmark_worker_identity_reservation_v1",
            "authority_kind": "test_only",
            "run_id": run_id,
            "stage": stage,
            "operation_id": operation_id,
            "workflow_revision": 1,
            "task_kind": "vision_observe_screen",
            "payload_sha256": payload_sha,
            "handler_payload_source": source,
            "handler_payload_source_ref": workflow_worker._benchmark_source_ref(source),
            "worker_id": worker_id,
            "model_request_id": model_request_id,
            "execution_nonce": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "supervision_inputs_ref": supervision_inputs_ref,
            "reservation_state": "reserved",
            "abort_observation_ref": None,
            "predecessor_content_sha256": source["content_sha256"],
        }
    )
    reservation_path = _write_json(tmp_path / "operation-a.benchmark-reservation-r0.json", reservation)
    operation_anchor = workflow_worker.compose_benchmark_worker_operation_anchor_v1(
        supervision_root=supervision_root,
        reservation=reservation,
        handler_payload_source=source,
        window_binding_ref=source["window_binding_ref"],
        capture_ref=source["capture_ref"],
        predecessor_content_sha256=reservation["content_sha256"],
    )
    operation_anchor_path = _write_json(tmp_path / "operation-anchor.json", operation_anchor)
    scope_name = operation_anchor["expected_supervision_ref"]
    from app.learn.hybrid.windows_process_scope import benchmark_worker_scope_name_v1
    exact_scope_name = benchmark_worker_scope_name_v1(
        authority_kind="test_only",
        run_id=run_id,
        stage=stage,
        operation_id=operation_id,
        worker_id=worker_id,
        payload_sha256=payload_sha,
        execution_nonce="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )
    expected_supervision = seal_immutable(
        {
            "contract_version": "benchmark_worker_expected_supervision_v1",
            "authority_kind": "test_only",
            "operation_anchor_ref": {"content_sha256": operation_anchor["anchor_identity_sha256"]},
            "reservation_ref": {"content_sha256": reservation["content_sha256"]},
            "supervision_inputs_ref": supervision_inputs_ref,
            "handler_payload_source_ref": workflow_worker._benchmark_source_ref(source),
            "run_id": run_id,
            "stage": stage,
            "operation_id": operation_id,
            "workflow_revision": 1,
            "worker_id": worker_id,
            "task_kind": "vision_observe_screen",
            "payload_sha256": payload_sha,
            "execution_nonce": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "scope_name": exact_scope_name,
            "startup_gate_timeout_ms": 15_000,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    assert operation_anchor["expected_supervision_ref"] == {"content_sha256": expected_supervision["content_sha256"]}
    expected_supervision_path = _write_json(tmp_path / "expected-supervision.json", expected_supervision)
    supervisor_identity = {"pid": 4001, "create_time_ns": 4001000}
    actual_supervision = workflow_worker.compose_benchmark_worker_supervision_v1(
        supervision_root=supervision_root,
        reservation=reservation,
        expected_operation_anchor=operation_anchor,
        supervisor_process_identity=supervisor_identity,
        startup_gate_timeout_ms=15_000,
    )
    actual_supervision_path = _write_json(tmp_path / "actual-supervision.json", actual_supervision)
    anchored_reservation = workflow_worker._benchmark_transitioned_reservation(reservation, "anchored")
    launching_reservation = workflow_worker._benchmark_transitioned_reservation(anchored_reservation, "launching")
    launched_reservation = workflow_worker._benchmark_transitioned_reservation(launching_reservation, "launched")
    anchored_path = _write_json(tmp_path / "operation-a.benchmark-reservation-anchored.json", anchored_reservation)
    launching_path = _write_json(tmp_path / "operation-a.benchmark-reservation-launching.json", launching_reservation)
    launched_path = _write_json(tmp_path / "operation-a.benchmark-reservation.json", launched_reservation)
    assignment = seal_immutable(
        {
            "contract_version": "benchmark_worker_scope_assignment_v1",
            "scope_name": exact_scope_name,
            "process_identity": worker_identity,
            "observed_member_identities": [worker_identity],
            "job_policy": {
                "kill_on_job_close": True,
                "breakaway_ok": False,
                "silent_breakaway_ok": False,
                "owner_handle_authority": "registry_parent",
            },
            "temporary_process_handle_close": {"handle_kind": "temporary_process", "status": "closed"},
            "temporary_job_handle_close": {"handle_kind": "temporary_job", "status": "closed"},
            "predecessor_content_sha256": actual_supervision["content_sha256"],
        }
    )
    assignment_path = _write_json(tmp_path / "worker-assignment.json", assignment)
    beacon = seal_immutable(
        {
            "contract_version": "benchmark_worker_identity_beacon_v1",
            "worker_id": worker_id,
            "operation_anchor_ref": {"content_sha256": operation_anchor["anchor_identity_sha256"]},
            "process_identity": worker_identity,
            "predecessor_content_sha256": actual_supervision["content_sha256"],
        }
    )
    beacon_path = _write_json(tmp_path / "worker-a.benchmark-beacon.json", beacon)
    launch_anchor = workflow_worker._compose_benchmark_launch_identity_anchor(
        anchored_reservation=anchored_reservation,
        launching_reservation=launching_reservation,
        operation_anchor=operation_anchor,
        supervision=actual_supervision,
        supervisor_process_identity=supervisor_identity,
        beacon_ref={"content_sha256": beacon["content_sha256"]},
        process_identity=worker_identity,
        assignment=assignment,
    )
    launch_anchor_path = _write_json(tmp_path / "worker-a.benchmark-launch-identity-anchor.json", launch_anchor)
    owner_gate = seal_immutable(
        {
            "contract_version": "benchmark_worker_owner_journal_v1",
            "authority_kind": "test_only",
            "operation_anchor_ref": {"content_sha256": operation_anchor["anchor_identity_sha256"]},
            "reservation_ref": {"content_sha256": launched_reservation["content_sha256"]},
            "supervision_ref": {"content_sha256": actual_supervision["content_sha256"]},
            "run_id": run_id,
            "stage": stage,
            "operation_id": operation_id,
            "worker_id": worker_id,
            "model_request_id": model_request_id,
            "payload_sha256": payload_sha,
            "execution_nonce": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "scope_name": assignment["scope_name"],
            "supervisor_process_identity": supervisor_identity,
            "phase": "gate_released",
            "process_identity": worker_identity,
            "beacon_ref": {"content_sha256": beacon["content_sha256"]},
            "assignment_observation_ref": {"content_sha256": assignment["content_sha256"]},
            "job_policy": assignment["job_policy"],
            "gate_state": "released",
            "exit_observation_ref": None,
            "stable_zero_observation_ref": None,
            "exact_handle_observation_refs": {},
            "cleanup_finalization_intent": None,
            "cleanup_receipt_ref": None,
            "predecessor_content_sha256": launch_anchor["content_sha256"],
        }
    )
    owner_gate_path = _write_json(tmp_path / "worker-owner-gate.json", owner_gate)
    exit_observation = seal_immutable(
        {
            "contract_version": "benchmark_worker_exit_join_observation_v1",
            "worker_id": worker_id,
            "process_identity": worker_identity,
            "exitcode": 0,
            "join_result": "joined",
            "join_error": None,
            "observed_at": "2026-08-27T00:00:01.500000Z",
            "predecessor_content_sha256": owner_gate["content_sha256"],
        }
    )
    exit_path = _write_json(tmp_path / "worker-a.exit-join.json", exit_observation)
    handle_refs: dict[str, dict[str, str]] = {}
    predecessor = exit_observation["content_sha256"]
    handle_paths: list[Path] = []
    startup_event_name = workflow_worker._benchmark_worker_gate_event_name(exact_scope_name)
    for handle_kind, handle_identity in (
        ("worker_process", {"process_identity": worker_identity}),
        ("startup_event", {"event_name": startup_event_name}),
        ("beacon_file", {"beacon_ref": {"content_sha256": beacon["content_sha256"]}}),
    ):
        observation = seal_immutable(
            {
                "contract_version": "benchmark_worker_handle_close_observation_v1",
                "handle_kind": handle_kind,
                "handle_identity": handle_identity,
                "call_result": "success",
                "call_error": None,
                "observed_at": "2026-08-27T00:00:01.600000Z",
                "worker_id": worker_id,
                "predecessor_content_sha256": predecessor,
            }
        )
        handle_paths.append(_write_json(tmp_path / f"worker-a.{handle_kind}-close.json", observation))
        handle_refs[handle_kind] = {"content_sha256": observation["content_sha256"]}
        predecessor = observation["content_sha256"]
    stable_zero = seal_immutable(
        {
            "contract_version": "benchmark_worker_stable_zero_observation_v1",
            "worker_id": worker_id,
            "scope_name": assignment["scope_name"],
            "samples": [[], [], []],
            "predecessor_content_sha256": predecessor,
        }
    )
    stable_zero_path = _write_json(tmp_path / "worker-a.stable-zero.json", stable_zero)
    finalization_intent = seal_immutable(
        {
            "contract_version": "benchmark_worker_cleanup_finalization_intent_v1",
            "supervision_ref": {"content_sha256": actual_supervision["content_sha256"]},
            "assignment_proven_ref": {"content_sha256": assignment["content_sha256"]},
            "run_id": run_id,
            "stage": stage,
            "operation_id": operation_id,
            "worker_id": worker_id,
            "supervisor_process_identity": supervisor_identity,
            "process_identity": worker_identity,
            "scope_name": assignment["scope_name"],
            "gate_state": "released",
            "exit_observation_ref": {"content_sha256": exit_observation["content_sha256"]},
            "stable_zero_observation_ref": {"content_sha256": stable_zero["content_sha256"]},
            "exact_owned_handles": {
                "worker_process": "closed_explicitly",
                "startup_event": "closed_explicitly",
                "beacon_file": "closed_explicitly",
                "owner_job": "open",
            },
            "exact_handle_observation_refs": handle_refs,
            "owner_job_handle_close_planned": True,
            "cleanup_receipt_id": _sha(canonical_json_bytes({"worker_id": worker_id, "scope_name": assignment["scope_name"]})),
            "predecessor_content_sha256": owner_gate["content_sha256"],
        }
    )
    intent_path = _write_json(tmp_path / "worker-a.benchmark-cleanup-intent.json", finalization_intent)
    worker_owner = seal_immutable(
        {
            **{key: deepcopy(value) for key, value in owner_gate.items() if key != "content_sha256"},
            "phase": "cleanup_finalization_intent",
            "exit_observation_ref": {"content_sha256": exit_observation["content_sha256"]},
            "stable_zero_observation_ref": {"content_sha256": stable_zero["content_sha256"]},
            "exact_handle_observation_refs": handle_refs,
            "cleanup_finalization_intent": {"content_sha256": finalization_intent["content_sha256"]},
            "predecessor_content_sha256": owner_gate["content_sha256"],
        }
    )
    worker_owner_path = _write_json(tmp_path / "worker-owner.json", worker_owner)
    owner_job_close = seal_immutable(
        {
            "contract_version": "benchmark_worker_handle_close_observation_v1",
            "handle_kind": "owner_job",
            "handle_identity": {"scope_name": assignment["scope_name"]},
            "call_result": "success",
            "call_error": None,
            "observed_at": "2026-08-27T00:00:01.700000Z",
            "worker_id": worker_id,
            "predecessor_content_sha256": finalization_intent["content_sha256"],
        }
    )
    owner_job_path = _write_json(tmp_path / "worker-a.owner-job-close.json", owner_job_close)
    cleanup_handle_refs = {**handle_refs, "owner_job": {"content_sha256": owner_job_close["content_sha256"]}}
    job_absence = seal_immutable(
        {
            "contract_version": "benchmark_worker_absence_observation_v1",
            "observation_kind": "job",
            "outcome": "absent",
            "worker_id": worker_id,
            "scope_name": assignment["scope_name"],
            "process_identity": None,
            "predecessor_content_sha256": owner_job_close["content_sha256"],
        }
    )
    job_absence_path = _write_json(tmp_path / "worker-a.job-absence.json", job_absence)
    worker_absence = seal_immutable(
        {
            "contract_version": "benchmark_worker_absence_observation_v1",
            "observation_kind": "worker",
            "outcome": "absent",
            "worker_id": worker_id,
            "scope_name": None,
            "process_identity": worker_identity,
            "predecessor_content_sha256": job_absence["content_sha256"],
        }
    )
    worker_absence_path = _write_json(tmp_path / "worker-a.worker-absence.json", worker_absence)
    worker_cleanup = seal_immutable(
        {
            "contract_version": "benchmark_worker_cleanup_receipt_v1",
            "outcome": "verified_exact_worker_exited",
            "operation_anchor_ref": {"content_sha256": operation_anchor["anchor_identity_sha256"]},
            "reservation_ref": {"content_sha256": launched_reservation["content_sha256"]},
            "supervision_ref": {"content_sha256": actual_supervision["content_sha256"]},
            "run_id": run_id,
            "stage": stage,
            "operation_id": operation_id,
            "worker_id": worker_id,
            "process_identity": worker_identity,
            "assignment_proven_ref": {"content_sha256": assignment["content_sha256"]},
            "finalization_intent_ref": {"content_sha256": finalization_intent["content_sha256"]},
            "exact_handle_observation_refs": cleanup_handle_refs,
            "job_absence_observation_ref": {"content_sha256": job_absence["content_sha256"]},
            "worker_absence_observation_ref": {"content_sha256": worker_absence["content_sha256"]},
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
    acquisition_intent = seal_immutable(
        {
            "contract_version": "qwen_model_request_acquisition_intent_v1",
            "model_request_id": model_request_id,
            "runtime_owner_ref": {"content_sha256": runtime_owner["content_sha256"]},
        }
    )
    intent_artifact_path = _write_json(tmp_path / "acquisition-intent.json", acquisition_intent)
    acquisition_owner = seal_immutable(
        {
            "contract_version": "benchmark_provider_acquisition_owner_v1",
            "model_request_id": model_request_id,
            "runtime_owner_ref": {"content_sha256": runtime_owner["content_sha256"]},
            "acquisition_intent_ref": {"content_sha256": acquisition_intent["content_sha256"]},
            "owner_state": "acquisition_prepared",
        }
    )
    acquisition_owner_path = _write_json(tmp_path / "acquisition-owner.json", acquisition_owner)
    prepared_ledger = seal_immutable(
        {
            "contract_version": "qwen_model_request_materialization_ledger_v1",
            "model_request_id": model_request_id,
            "acquisition_intent_ref": {"content_sha256": acquisition_intent["content_sha256"]},
            "runtime_owner_ref": {"content_sha256": runtime_owner["content_sha256"]},
            "state": "prepared_never_materialized",
            "revision": 0,
            "transition": "prepare",
            "predecessor_content_sha256": None,
        }
    )
    prepared_ledger_path = _write_json(tmp_path / "materialization-ledger-r0.json", prepared_ledger)
    ledger = seal_immutable(
        {
            **{key: deepcopy(value) for key, value in prepared_ledger.items() if key != "content_sha256"},
            "state": "materialization_possible",
            "revision": 1,
            "transition": "launch",
            "predecessor_content_sha256": prepared_ledger["content_sha256"],
        }
    )
    ledger_path = _write_json(tmp_path / "materialization-ledger.json", ledger)
    prepared_acquisition = seal_immutable(
        {
            "contract_version": "qwen_model_request_acquisition_observation_v1",
            "model_request_id": model_request_id,
            "acquisition_owner_ref": {"content_sha256": acquisition_owner["content_sha256"]},
            "acquisition_intent_ref": {"content_sha256": acquisition_intent["content_sha256"]},
            "runtime_owner_ref": {"content_sha256": runtime_owner["content_sha256"]},
            "prepared_materialization_ledger_ref": {"content_sha256": prepared_ledger["content_sha256"]},
            "materialization_ledger_ref": {"content_sha256": prepared_ledger["content_sha256"]},
            "materialization_state": "prepared_never_materialized",
            "materialization_revision": 0,
        }
    )
    prepared_acquisition_path = _write_json(tmp_path / "prepared-acquisition-observation.json", prepared_acquisition)
    acquisition_observation = seal_immutable(
        {
            **{key: deepcopy(value) for key, value in prepared_acquisition.items() if key != "content_sha256"},
            "materialization_ledger_ref": {"content_sha256": ledger["content_sha256"]},
            "materialization_state": "materialization_possible",
            "materialization_revision": 1,
        }
    )
    acquisition_observation_path = _write_json(tmp_path / "acquisition-observation.json", acquisition_observation)
    profile = {"profile_id": "qwen-profile-a", "provider": "qwen", "model": "qwen-a"}
    profile_sha = lifecycle.content_sha256(profile)
    socket = {"host": "127.0.0.1", "port": 9401}
    scope_acquisition = {
        "contract_version": "hybrid_process_scope_acquisition_v1",
        "scope_name": "Local\\AgentGuiQwen-a",
        "member_pids": [provider_identity["pid"]],
        "server_process_identity": provider_identity,
    }
    incarnation = {
        "profile_id": profile["profile_id"],
        "profile_sha256": profile_sha,
        "server_endpoint": "http://127.0.0.1:9401/v1",
        "server_base_url": "http://127.0.0.1:9401/v1",
        "server_model_id": "qwen-a",
        "server_socket": socket,
        "server_process_identity": provider_identity,
        "incarnation_id": "incarnation-a",
    }
    lease = {
        "contract_version": "qwen_model_server_lease_v2",
        "lease_id": "lease-a",
        "owner_request_id": model_request_id,
        "profile_id": profile["profile_id"],
        "incarnation_id": incarnation["incarnation_id"],
        "server_base_url": incarnation["server_base_url"],
        "server_model_id": incarnation["server_model_id"],
        "profile_sha256": profile_sha,
        "server_process_identity": provider_identity,
    }
    lease_ref = {"content_sha256": lifecycle.content_sha256(lease)}
    lease_state = seal_immutable(
        {
            "contract_version": "qwen_model_server_lease_state_v3",
            "profile_id": profile["profile_id"],
            "profile": profile,
            "incarnation": incarnation,
            "server_started_by_runtime": True,
            "process_scope_name": scope_acquisition["scope_name"],
            "process_scope_acquisition": scope_acquisition,
            "revision": 1,
            "finalization": None,
            "leases": [{**lease, "lifecycle_state": "not_started"}],
        }
    )
    lease_state_path = _write_json(tmp_path / "acquisition-lease-state-snapshot.json", lease_state)
    lease_binding = seal_immutable(
        {
            "contract_version": "qwen_model_request_acquisition_lease_binding_v1",
            "model_request_id": model_request_id,
            "acquisition_intent_ref": {"content_sha256": acquisition_intent["content_sha256"]},
            "runtime_owner_ref": {"content_sha256": runtime_owner["content_sha256"]},
            "lease_ref": lease_ref,
            "profile_ref": {"content_sha256": profile_sha},
            "server_process_identity": provider_identity,
            "socket_ref": {"content_sha256": lifecycle.content_sha256(socket)},
            "job_scope_ref": {"content_sha256": lifecycle.content_sha256(scope_acquisition)},
            "lease_state_ref": {"content_sha256": lease_state["content_sha256"]},
        }
    )
    lease_binding_path = _write_json(tmp_path / "acquisition-lease-binding.json", lease_binding)
    scope_cleanup = {
        "contract_version": "hybrid_windows_process_scope_v1",
        "scope_name": scope_acquisition["scope_name"],
        "authority": "windows_job_object",
        "scope_absent_after_owner_close": True,
        "cleanup_status": "verified",
        "observed_member_pids_before": [provider_identity["pid"]],
        "observed_member_identities_before": [provider_identity],
        "member_pids_after": [],
        "member_identities_after": [],
        "active_listeners_after": [],
        "pid_file_after": None,
        "stable_zero_observations": 3,
        "samples": [
            {"pids": [], "process_identities": [], "listeners": []},
            {"pids": [], "process_identities": [], "listeners": []},
            {"pids": [], "process_identities": [], "listeners": []},
        ],
    }
    termination_raw = {"status": "proven_absent", "identity": None, "reason": "no_such_process"}
    release_result = {
        "status": "released",
        "lease": lease,
        "shared_server_retained": False,
        "server_termination": "terminated",
        "release": termination_raw,
        "after": {"leases": []},
        "process_identity": provider_identity,
        "hybrid_descendant_cleanup": {
            "status": "verified",
            "descendant_identities": [],
            "probes": [],
            "process_scope_cleanup": scope_cleanup,
        },
        "hybrid_process_scope_name": scope_acquisition["scope_name"],
        "hybrid_process_scope_acquisition": scope_acquisition,
        "hybrid_process_scope_cleanup": scope_cleanup,
    }
    release_result_ref = {"content_sha256": lifecycle.content_sha256(release_result)}
    finalization_token = "token-a"
    release_observation = seal_immutable(
        {
            "contract_version": "qwen_model_request_exact_release_observation_v1",
            "model_request_id": model_request_id,
            "lease_ref": lease_ref,
            "finalization_token": finalization_token,
            "release_reason": "completed",
            "release_result_ref": release_result_ref,
        }
    )
    release_observation_path = _write_json(tmp_path / "exact-release-observation.json", release_observation)
    termination = seal_immutable(
        {
            "contract_version": "qwen_model_request_exact_termination_observation_v1",
            "model_request_id": model_request_id,
            "lease_ref": lease_ref,
            "finalization_token": finalization_token,
            "release_result_ref": release_result_ref,
            "termination_observation": termination_raw,
        }
    )
    termination_path = _write_json(tmp_path / "exact-termination-observation.json", termination)
    owner_tombstone = seal_immutable(
        {
            "contract_version": "qwen_model_request_owner_receipt_v1",
            "status": "finalized",
            "owner_request_id": model_request_id,
            "profile_id": profile["profile_id"],
            "lease_id": lease["lease_id"],
            "incarnation_id": lease["incarnation_id"],
            "server_termination": release_result["server_termination"],
            "release_result": release_result,
            "finalization_token": finalization_token,
        }
    )
    tombstone_path = _write_json(tmp_path / "owner-tombstone.json", owner_tombstone)
    no_active = seal_immutable(
        {
            "contract_version": "qwen_model_request_no_active_lease_observation_v1",
            "model_request_id": model_request_id,
            "active_lease_count": 0,
        }
    )
    no_active_path = _write_json(tmp_path / "no-active-lease.json", no_active)
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
            "acquisition_owner_ref": {"content_sha256": acquisition_owner["content_sha256"]},
            "acquisition_intent_ref": {"content_sha256": acquisition_intent["content_sha256"]},
            "prepared_acquisition_observation_ref": {"content_sha256": prepared_acquisition["content_sha256"]},
            "prepared_materialization_ledger_ref": {"content_sha256": prepared_ledger["content_sha256"]},
            "acquisition_observation_ref": {"content_sha256": acquisition_observation["content_sha256"]},
            "materialization_ledger_ref": {"content_sha256": ledger["content_sha256"]},
        }
    )
    provider_journal_path = _write_json(tmp_path / "provider-journal.json", provider_journal)
    scope_cleanup_ref = {"content_sha256": lifecycle.content_sha256(scope_cleanup)}
    provider_cleanup = seal_immutable(
        {
            "contract_version": "qwen_model_request_cleanup_receipt_v1",
            "outcome": "verified_exact_process_exited",
            "model_request_id": model_request_id,
            "acquisition_intent_ref": {"content_sha256": acquisition_intent["content_sha256"]},
            "runtime_owner_ref": {"content_sha256": runtime_owner["content_sha256"]},
            "lease_ref": lease_ref,
            "profile_ref": {"content_sha256": profile_sha},
            "server_process_identity": provider_identity,
            "socket_ref": lease_binding["socket_ref"],
            "job_scope_ref": lease_binding["job_scope_ref"],
            "finalization_token": finalization_token,
            "lease_state_ref": {"content_sha256": lease_state["content_sha256"]},
            "owner_tombstone_ref": {"content_sha256": owner_tombstone["content_sha256"]},
            "release_reason": "completed",
            "termination_observation_ref": {"content_sha256": termination["content_sha256"]},
            "scope_stable_zero_ref": scope_cleanup_ref,
            "listener_stable_zero_ref": scope_cleanup_ref,
            "no_active_lease_observation_ref": {"content_sha256": no_active["content_sha256"]},
            "no_owned_runtime_observation_ref": None,
        }
    )
    provider_cleanup_path = _write_json(tmp_path / "provider-cleanup.json", provider_cleanup)
    return [
        root_path,
        authority_path,
        normal_clear_path,
        source_path,
        reservation_path,
        anchored_path,
        launching_path,
        launched_path,
        operation_anchor_path,
        expected_supervision_path,
        actual_supervision_path,
        assignment_path,
        beacon_path,
        launch_anchor_path,
        owner_gate_path,
        worker_owner_path,
        exit_path,
        *handle_paths,
        stable_zero_path,
        intent_path,
        owner_job_path,
        job_absence_path,
        worker_absence_path,
        worker_cleanup_path,
        runtime_owner_path,
        intent_artifact_path,
        acquisition_owner_path,
        prepared_ledger_path,
        ledger_path,
        prepared_acquisition_path,
        acquisition_observation_path,
        lease_state_path,
        lease_binding_path,
        release_observation_path,
        termination_path,
        tombstone_path,
        no_active_path,
        provider_journal_path,
        provider_cleanup_path,
    ]


def _not_launched_parent_bundle(tmp_path: Path) -> list[Path]:
    import json

    launched = _parent_bundle(tmp_path)
    by_name = {path.name: path for path in launched}

    def load(name: str) -> dict[str, object]:
        return json.loads(by_name[name].read_text(encoding="utf-8"))

    root = load("window-owner.json")
    source = load("handler-payload-source.json")
    reserved = load("operation-a.benchmark-reservation-r0.json")
    anchored = load("operation-a.benchmark-reservation-anchored.json")
    operation_anchor = load("operation-anchor.json")
    worker_id = str(reserved["worker_id"])
    absence_paths: list[Path] = []
    predecessor = anchored["content_sha256"]
    absence_refs: dict[str, dict[str, str]] = {}
    specs = workflow_worker._benchmark_pre_anchor_absence_specs(anchored)
    for kind, checks, field in specs:
        absence = seal_immutable(
            {
                "contract_version": "benchmark_worker_pre_anchor_absence_observation_v1",
                "observation_kind": kind,
                "outcome": "absent",
                "reservation_ref": {"content_sha256": anchored["content_sha256"]},
                "run_id": anchored["run_id"],
                "stage": anchored["stage"],
                "operation_id": anchored["operation_id"],
                "worker_id": worker_id,
                "checks": checks,
                "predecessor_content_sha256": predecessor,
            }
        )
        absence_paths.append(_write_json(tmp_path / f"{worker_id}.pre-anchor-{kind}-absence.json", absence))
        absence_refs[field] = {"content_sha256": absence["content_sha256"]}
        predecessor = absence["content_sha256"]
    not_launched = seal_immutable(
        {
            "contract_version": "benchmark_worker_not_launched_observation_v1",
            "outcome": "verified_no_launch_artifacts",
            "authority_kind": anchored["authority_kind"],
            "reservation_ref": {"content_sha256": anchored["content_sha256"]},
            "run_id": anchored["run_id"],
            "stage": anchored["stage"],
            "operation_id": anchored["operation_id"],
            "worker_id": worker_id,
            **absence_refs,
            "predecessor_content_sha256": predecessor,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    not_launched_path = _write_json(tmp_path / f"{worker_id}.benchmark-not-launched.json", not_launched)
    cancelled_body = {key: deepcopy(value) for key, value in anchored.items() if key != "content_sha256"}
    cancelled_body.update(
        {
            "reservation_state": "cancelled_before_launch",
            "abort_observation_ref": {"content_sha256": not_launched["content_sha256"]},
            "predecessor_content_sha256": anchored["content_sha256"],
        }
    )
    cancelled = seal_immutable(cancelled_body)
    cancelled_path = _write_json(tmp_path / "operation-a.benchmark-reservation.json", cancelled)
    worker_cleanup = workflow_worker._compose_benchmark_not_launched_receipt(
        cancelled_reservation=cancelled,
        operation_anchor=operation_anchor,
        observation=not_launched,
    )
    worker_cleanup_path = _write_json(tmp_path / "worker-cleanup.json", worker_cleanup)
    runtime_owner = seal_immutable(
        {
            "contract_version": "benchmark_provider_runtime_owner_v1",
            "authority_kind": "test_fixture",
            "run_id": cancelled["run_id"],
            "stage": cancelled["stage"],
            "operation_id": cancelled["operation_id"],
            "worker_id": cancelled["worker_id"],
            "model_request_id": cancelled["model_request_id"],
            "reservation_ref": {"content_sha256": cancelled["content_sha256"]},
            "payload_sha256": cancelled["payload_sha256"],
        }
    )
    runtime_path = _write_json(tmp_path / "runtime-owner.json", runtime_owner)
    intent = seal_immutable(
        {
            "contract_version": "qwen_model_request_acquisition_intent_v1",
            "model_request_id": cancelled["model_request_id"],
            "runtime_owner_ref": {"content_sha256": runtime_owner["content_sha256"]},
        }
    )
    intent_path = _write_json(tmp_path / "acquisition-intent.json", intent)
    acquisition_owner = seal_immutable(
        {
            "contract_version": "benchmark_provider_acquisition_owner_v1",
            "model_request_id": cancelled["model_request_id"],
            "runtime_owner_ref": {"content_sha256": runtime_owner["content_sha256"]},
            "acquisition_intent_ref": {"content_sha256": intent["content_sha256"]},
            "owner_state": "acquisition_prepared",
        }
    )
    acquisition_owner_path = _write_json(tmp_path / "acquisition-owner.json", acquisition_owner)
    prepared = seal_immutable(
        {
            "contract_version": "qwen_model_request_materialization_ledger_v1",
            "model_request_id": cancelled["model_request_id"],
            "acquisition_intent_ref": {"content_sha256": intent["content_sha256"]},
            "runtime_owner_ref": {"content_sha256": runtime_owner["content_sha256"]},
            "state": "prepared_never_materialized",
            "revision": 0,
            "transition": "prepare",
            "predecessor_content_sha256": None,
        }
    )
    prepared_path = _write_json(tmp_path / "materialization-ledger-r0.json", prepared)
    ledger = seal_immutable(
        {
            **{key: deepcopy(value) for key, value in prepared.items() if key != "content_sha256"},
            "state": "aborted_never_materialized",
            "revision": 1,
            "transition": "abort",
            "predecessor_content_sha256": prepared["content_sha256"],
        }
    )
    ledger_path = _write_json(tmp_path / "materialization-ledger.json", ledger)
    prepared_observation = seal_immutable(
        {
            "contract_version": "qwen_model_request_acquisition_observation_v1",
            "model_request_id": cancelled["model_request_id"],
            "acquisition_owner_ref": {"content_sha256": acquisition_owner["content_sha256"]},
            "acquisition_intent_ref": {"content_sha256": intent["content_sha256"]},
            "runtime_owner_ref": {"content_sha256": runtime_owner["content_sha256"]},
            "prepared_materialization_ledger_ref": {"content_sha256": prepared["content_sha256"]},
            "materialization_ledger_ref": {"content_sha256": prepared["content_sha256"]},
            "materialization_state": "prepared_never_materialized",
            "materialization_revision": 0,
        }
    )
    prepared_observation_path = _write_json(tmp_path / "prepared-acquisition-observation.json", prepared_observation)
    acquisition_observation = seal_immutable(
        {
            **{key: deepcopy(value) for key, value in prepared_observation.items() if key != "content_sha256"},
            "materialization_ledger_ref": {"content_sha256": ledger["content_sha256"]},
            "materialization_state": "aborted_never_materialized",
            "materialization_revision": 1,
        }
    )
    acquisition_observation_path = _write_json(tmp_path / "acquisition-observation.json", acquisition_observation)
    scope_cleanup = {
        "contract_version": "hybrid_windows_process_scope_v1",
        "scope_name": "Local\\NoProvider-a",
        "authority": "windows_job_object",
        "scope_absent_after_owner_close": True,
        "cleanup_status": "verified",
        "observed_member_pids_before": [],
        "observed_member_identities_before": [],
        "member_pids_after": [],
        "member_identities_after": [],
        "active_listeners_after": [],
        "pid_file_after": None,
        "stable_zero_observations": 3,
        "samples": [
            {"pids": [], "process_identities": [], "listeners": []},
            {"pids": [], "process_identities": [], "listeners": []},
            {"pids": [], "process_identities": [], "listeners": []},
        ],
    }
    production_tombstone = seal_immutable(
        {
            "contract_version": "hybrid_qwen_aborted_acquisition_tombstone_v1",
            "status": "aborted_before_lease",
            "model_request_id": cancelled["model_request_id"],
            "provider": "qwen",
            "lineage": {"run_id": cancelled["run_id"], "operation_id": cancelled["operation_id"]},
            "process_scope_name": scope_cleanup["scope_name"],
            "profile_sha256": "b" * 64,
            "listener_port": 9601,
            "pid_file": str((tmp_path / "not-created.pid").resolve()),
            "scope_cleanup_evidence": scope_cleanup,
        }
    )
    production_tombstone_path = _write_json(tmp_path / "production-aborted-owner-tombstone.json", production_tombstone)
    abort_tombstone = seal_immutable(
        {
            "contract_version": "benchmark_provider_aborted_acquisition_tombstone_v1",
            "model_request_id": cancelled["model_request_id"],
            "acquisition_intent_ref": {"content_sha256": intent["content_sha256"]},
            "runtime_owner_ref": {"content_sha256": runtime_owner["content_sha256"]},
            "materialization_ledger_ref": {"content_sha256": ledger["content_sha256"]},
            "reason": "cancelled_before_launch",
            "historical_process_identity": None,
            "historical_socket_ref": None,
            "historical_job_scope_ref": None,
        }
    )
    abort_tombstone_path = _write_json(tmp_path / "aborted-owner-tombstone.json", abort_tombstone)
    acquisition_abort = seal_immutable(
        {
            "contract_version": "benchmark_provider_acquisition_abort_v1",
            "model_request_id": cancelled["model_request_id"],
            "acquisition_intent_ref": {"content_sha256": intent["content_sha256"]},
            "runtime_owner_ref": {"content_sha256": runtime_owner["content_sha256"]},
            "materialization_ledger_ref": {"content_sha256": ledger["content_sha256"]},
            "owner_tombstone_ref": {"content_sha256": production_tombstone["content_sha256"]},
            "reason": abort_tombstone["reason"],
            "owner_state": "acquisition_aborted",
        }
    )
    acquisition_abort_path = _write_json(tmp_path / "acquisition-abort.json", acquisition_abort)
    no_active = seal_immutable(
        {
            "contract_version": "qwen_model_request_no_active_lease_observation_v1",
            "model_request_id": cancelled["model_request_id"],
            "active_lease_count": 0,
        }
    )
    no_active_path = _write_json(tmp_path / "no-active-lease.json", no_active)
    provider_journal = seal_immutable(
        {
            "contract_version": "benchmark_provider_registry_journal_v1",
            "authority_kind": "test_fixture",
            "run_id": cancelled["run_id"],
            "stage": cancelled["stage"],
            "operation_id": cancelled["operation_id"],
            "worker_id": cancelled["worker_id"],
            "model_request_id": cancelled["model_request_id"],
            "payload_sha256": cancelled["payload_sha256"],
            "reservation_ref": {"content_sha256": cancelled["content_sha256"]},
            "runtime_owner_ref": {"content_sha256": runtime_owner["content_sha256"]},
            "acquisition_owner_ref": {"content_sha256": acquisition_owner["content_sha256"]},
            "acquisition_intent_ref": {"content_sha256": intent["content_sha256"]},
            "prepared_acquisition_observation_ref": {"content_sha256": prepared_observation["content_sha256"]},
            "prepared_materialization_ledger_ref": {"content_sha256": prepared["content_sha256"]},
            "acquisition_observation_ref": {"content_sha256": acquisition_observation["content_sha256"]},
            "materialization_ledger_ref": {"content_sha256": ledger["content_sha256"]},
        }
    )
    provider_journal_path = _write_json(tmp_path / "provider-journal.json", provider_journal)
    scope_ref = {"content_sha256": lifecycle.content_sha256(scope_cleanup)}
    provider_cleanup = seal_immutable(
        {
            "contract_version": "qwen_model_request_cleanup_receipt_v1",
            "outcome": "verified_not_acquired",
            "model_request_id": cancelled["model_request_id"],
            "acquisition_intent_ref": {"content_sha256": intent["content_sha256"]},
            "runtime_owner_ref": {"content_sha256": runtime_owner["content_sha256"]},
            "lease_ref": None,
            "profile_ref": None,
            "server_process_identity": None,
            "socket_ref": None,
            "job_scope_ref": None,
            "finalization_token": None,
            "lease_state_ref": None,
            "owner_tombstone_ref": {"content_sha256": production_tombstone["content_sha256"]},
            "release_reason": abort_tombstone["reason"],
            "termination_observation_ref": None,
            "scope_stable_zero_ref": scope_ref,
            "listener_stable_zero_ref": scope_ref,
            "no_active_lease_observation_ref": {"content_sha256": no_active["content_sha256"]},
            "no_owned_runtime_observation_ref": {"content_sha256": production_tombstone["content_sha256"]},
        }
    )
    provider_cleanup_path = _write_json(tmp_path / "provider-cleanup.json", provider_cleanup)
    keep = [
        by_name["window-owner.json"],
        by_name["binding-authority.json"],
        by_name["handler-payload-source.json"],
        by_name["operation-a.benchmark-reservation-r0.json"],
        by_name["operation-a.benchmark-reservation-anchored.json"],
        by_name["operation-anchor.json"],
        by_name["expected-supervision.json"],
    ]
    return [
        *keep,
        *absence_paths,
        not_launched_path,
        cancelled_path,
        worker_cleanup_path,
        runtime_path,
        intent_path,
        acquisition_owner_path,
        prepared_path,
        ledger_path,
        prepared_observation_path,
        acquisition_observation_path,
        production_tombstone_path,
        abort_tombstone_path,
        acquisition_abort_path,
        no_active_path,
        provider_journal_path,
        provider_cleanup_path,
    ]


def _probe_bundle(
    path: Path,
    *,
    provider: str,
    kind: str,
    body_state: str = "not_complete",
    residue: str | None = None,
) -> list[Path]:
    attempt_id = f"attempt-{provider}-{kind}"
    profile = seal_immutable(
        {
            "contract_version": "benchmark_v2_probe_provider_profile_v1",
            "provider_id": provider,
            "profile_id": f"{provider}-profile",
            "attempt_id": attempt_id,
        }
    )
    pid = 7000 + {"omni": 1, "qwen": 2, "vista": 3}[provider]
    identity = {"pid": pid, "create_time_ns": pid * 1000 + (1 if kind == "cancel" else 2)}
    start = datetime(2026, 8, 27, 1, 0, tzinfo=timezone.utc)
    request = seal_immutable(
        {
            "contract_version": "benchmark_v2_probe_request_in_flight_v1",
            "provider_id": provider,
            "run_id": "run-a",
            "stage": "screen_understanding",
            "operation_id": "operation-a",
            "model_request_id": "request-a",
            "attempt_id": attempt_id,
            "state": "request_in_flight",
            "observed_at_utc": start.isoformat().replace("+00:00", "Z"),
        }
    )
    body = seal_immutable(
        {
            **{key: deepcopy(value) for key, value in request.items() if key != "content_sha256"},
            "contract_version": "benchmark_v2_probe_body_observation_v1",
            "state": body_state,
            "observed_at_utc": (start + timedelta(seconds=2)).isoformat().replace("+00:00", "Z"),
        }
    )
    socket = seal_immutable(
        {
            "contract_version": "benchmark_v2_probe_socket_owner_v1",
            "provider_id": provider,
            "attempt_id": attempt_id,
            "incarnation_id": f"incarnation-{attempt_id}",
            "host": "127.0.0.1",
            "port": 9500 + pid,
            "process_identity": identity,
        }
    )
    job = seal_immutable(
        {
            "contract_version": "benchmark_v2_probe_job_membership_v1",
            "provider_id": provider,
            "attempt_id": attempt_id,
            "incarnation_id": socket["incarnation_id"],
            "scope_name": f"Local\\Probe-{attempt_id}",
            "member_identities": [identity],
        }
    )
    lease = seal_immutable(
        {
            "contract_version": "benchmark_v2_probe_lease_owner_v1",
            "provider_id": provider,
            "profile_ref": {"content_sha256": profile["content_sha256"]},
            "attempt_id": attempt_id,
            "lease_id": f"lease-{attempt_id}",
            "incarnation_id": socket["incarnation_id"],
            "process_identity": identity,
            "socket_ref": {"content_sha256": socket["content_sha256"]},
            "job_scope_ref": {"content_sha256": job["content_sha256"]},
            "acquired_at_utc": (start - timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
        }
    )
    termination = seal_immutable(
        {
            "contract_version": "benchmark_v2_probe_termination_v1",
            "provider_id": provider,
            "attempt_id": attempt_id,
            "incarnation_id": socket["incarnation_id"],
            "process_identity": identity,
            "outcome": "same_incarnation_exited",
            "terminated_at_utc": (start + timedelta(seconds=1, milliseconds=500)).isoformat().replace("+00:00", "Z"),
            "predecessor_content_sha256": lease["content_sha256"],
        }
    )
    paths: list[Path] = []
    for suffix, value in (
        ("profile", profile),
        ("request", request),
        ("body", body),
        ("socket", socket),
        ("job", job),
        ("lease", lease),
        ("termination", termination),
    ):
        paths.append(_write_json(path.with_name(f"{path.stem}-{suffix}.json"), value))
    sample_refs: list[dict[str, str]] = []
    predecessor = termination["content_sha256"]
    zero_members: list[object] = []
    zero_listeners: list[object] = []
    zero_leases: list[object] = []
    for sequence in range(3):
        job_members = [identity] if residue == "job" and sequence == 2 else []
        active_listeners = [{"pid": pid, "port": socket["port"]}] if residue == "listener" and sequence == 2 else []
        active_leases = [lease["lease_id"]] if residue == "lease" and sequence == 2 else []
        sample = seal_immutable(
            {
                "contract_version": "benchmark_v2_probe_zero_sample_v1",
                "provider_id": provider,
                "attempt_id": attempt_id,
                "incarnation_id": socket["incarnation_id"],
                "sequence": sequence,
                "observed_at_utc": (start + timedelta(seconds=3 + sequence)).isoformat().replace("+00:00", "Z"),
                "job_members": job_members,
                "active_listeners": active_listeners,
                "active_leases": active_leases,
                "predecessor_content_sha256": predecessor,
            }
        )
        paths.append(_write_json(path.with_name(f"{path.stem}-zero-{sequence}.json"), sample))
        sample_refs.append({"content_sha256": sample["content_sha256"]})
        predecessor = sample["content_sha256"]
        zero_members = job_members
        zero_listeners = active_listeners
        zero_leases = active_leases
    bundle = seal_immutable(
        {
            "contract_version": "benchmark_v2_probe_stable_zero_bundle_v1",
            "provider_id": provider,
            "attempt_id": attempt_id,
            "incarnation_id": socket["incarnation_id"],
            "sample_refs": sample_refs,
            "process_absent": not bool(zero_members),
            "listener_absent": not bool(zero_listeners),
            "lease_absent": not bool(zero_leases),
            "predecessor_content_sha256": termination["content_sha256"],
        }
    )
    paths.append(_write_json(path.with_name(f"{path.stem}-zero-bundle.json"), bundle))
    receipt = seal_immutable(
        {
            "contract_version": "benchmark_v2_lifecycle_probe_receipt_v1",
            "probe_id": f"probe/{provider}/{kind}",
            "probe_kind": kind,
            "provider": {
                "provider_id": provider,
                "profile_id": profile["profile_id"],
                "profile_sha256": profile["content_sha256"],
            },
            "run_id": "run-a",
            "stage": "screen_understanding",
            "operation_id": "operation-a",
            "model_request_id": "request-a",
            "request_in_flight_observation": {
                "state": "request_in_flight",
                "observed_at_utc": request["observed_at_utc"],
                "evidence_ref": {"content_sha256": request["content_sha256"]},
            },
            "trigger": {
                "kind": kind,
                "triggered_at_utc": (start + timedelta(seconds=1)).isoformat().replace("+00:00", "Z"),
                "request_in_flight_ref": {"content_sha256": request["content_sha256"]},
            },
            "body_completion_observation": {
                "state": body_state,
                "observed_at_utc": body["observed_at_utc"],
                "evidence_ref": {"content_sha256": body["content_sha256"]},
            },
            "lease_or_owner": {
                "lease_ref": {"content_sha256": lease["content_sha256"]},
                "socket_ref": {"content_sha256": socket["content_sha256"]},
                "process_identity": identity,
                "job_scope_ref": {"content_sha256": job["content_sha256"]},
            },
            "termination_observation": {
                "outcome": "same_incarnation_exited",
                "process_identity": identity,
                "evidence_ref": {"content_sha256": termination["content_sha256"]},
            },
            "stable_zero_observation": {
                "job_members": zero_members,
                "active_listeners": zero_listeners,
                "active_leases": zero_leases,
                "stable_zero_observations": 3,
                "process_absence_ref": {"content_sha256": bundle["content_sha256"]},
                "listener_absence_ref": {"content_sha256": bundle["content_sha256"]},
                "lease_absence_ref": {"content_sha256": bundle["content_sha256"]},
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
            "predecessor_content_sha256": bundle["content_sha256"],
        }
    )
    paths.append(_write_json(path, receipt))
    return paths


def _probe(path: Path, *, provider: str, kind: str, body_state: str = "not_complete", residue: str | None = None) -> Path:
    return _probe_bundle(path, provider=provider, kind=kind, body_state=body_state, residue=residue)[-1]


def _set_probe_body_state(paths: list[Path], *, provider: str, kind: str, state: str) -> None:
    import json

    stem = f"probe-{provider}-{kind}"
    body_path = next(path for path in paths if path.name == f"{stem}-body.json")
    _mutate(body_path, lambda value: value.__setitem__("state", state))
    body = json.loads(body_path.read_text(encoding="utf-8"))
    receipt_path = next(path for path in paths if path.name == f"{stem}.json")
    _mutate(
        receipt_path,
        lambda value: value["body_completion_observation"].update(
            {"state": state, "evidence_ref": {"content_sha256": body["content_sha256"]}}
        ),
    )


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
        path
        for provider in ("omni", "qwen", "vista")
        for kind in ("cancel", "timeout")
        for path in _probe_bundle(
            tmp_path / f"probe-{provider}-{kind}.json", provider=provider, kind=kind
        )
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
    monkeypatch.setattr(
        lifecycle,
        "_observe_process_inventory",
        lambda: ({4101: 4101000, 6101: 6101000}, [], "complete"),
    )
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
    assert result["process_snapshot"]["identities"] == [
        {"pid": 4101, "create_time_ns": 4101000},
        {"pid": 6101, "create_time_ns": 6101000},
    ]
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
    monkeypatch.setattr(lifecycle, "_observe_process_inventory", lambda: ({}, [], "complete"))
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
    monkeypatch.setattr(lifecycle, "_observe_process_inventory", lambda: ({}, [], "complete"))
    monkeypatch.setattr(lifecycle, "_production_gpu_observer_identity", lambda: _observer("production_direct"))
    path = tmp_path / "requested-device-failure.json"
    with pytest.raises(ValueError, match="requested GPU UUID|GPU totals are malformed"):
        collect_raw_gpu_sample(device_uuid=DEVICE, transcript_path=path)
    assert path.is_file()
    assert b"parsed_zero" not in path.read_bytes()


def test_process_inventory_uses_round_canonicalization_and_marks_access_denied_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeProcess:
        def __init__(self, pid: int) -> None:
            self.pid = pid

        def create_time(self) -> float:
            if self.pid == 12:
                raise lifecycle.psutil.AccessDenied(self.pid)
            return 1.0000000016

    monkeypatch.setattr(lifecycle.psutil, "pids", lambda: [12, 11, 0])
    monkeypatch.setattr(lifecycle.psutil, "Process", FakeProcess)
    identities, unobserved, status = lifecycle._observe_process_inventory()
    assert identities == {11: 1_000_000_002}
    assert unobserved == [12]
    assert status == "partial"


def test_process_inventory_enumeration_failure_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        lifecycle.psutil,
        "pids",
        lambda: (_ for _ in ()).throw(lifecycle.psutil.Error("enumeration failed")),
    )
    assert lifecycle._observe_process_inventory() == ({}, [], "unavailable")


class _FakePipe:
    def __init__(self, *, close_error: BaseException | None = None) -> None:
        self.closed = False
        self.close_error = close_error

    def close(self) -> None:
        self.closed = True
        if self.close_error is not None:
            raise self.close_error


class _FakePopen:
    def __init__(
        self,
        *,
        returncode: int = 0,
        timeout_once: bool = False,
        wait_error: BaseException | None = None,
        stdout_close_error: BaseException | None = None,
    ) -> None:
        self.returncode = returncode
        self.timeout_once = timeout_once
        self.wait_error = wait_error
        self.communicate_calls = 0
        self.kill_calls = 0
        self.wait_calls = 0
        self.stdout = _FakePipe(close_error=stdout_close_error)
        self.stderr = _FakePipe()

    def communicate(self, timeout: float | None = None) -> tuple[bytes, bytes]:
        self.communicate_calls += 1
        if self.timeout_once and self.communicate_calls == 1:
            raise lifecycle.subprocess.TimeoutExpired(cmd="nvidia-smi.exe", timeout=timeout)
        return b"out", b"err"

    def poll(self) -> int | None:
        return self.returncode

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9

    def wait(self) -> int:
        self.wait_calls += 1
        if self.wait_error is not None:
            raise self.wait_error
        return self.returncode


@pytest.mark.parametrize("returncode", [0, 7])
def test_fixed_query_reaps_and_closes_pipes_on_success_and_nonzero(
    monkeypatch: pytest.MonkeyPatch, returncode: int
) -> None:
    fake = _FakePopen(returncode=returncode)
    monkeypatch.setattr(lifecycle.subprocess, "Popen", lambda *args, **kwargs: fake)
    result = lifecycle._run_fixed_nvidia_smi_query(
        list(lifecycle._GPU_COMMANDS[0][1]), shell=False, timeout_seconds=1.0
    )
    assert result["exit_code"] == returncode
    assert fake.wait_calls >= 1
    assert fake.stdout.closed is True and fake.stderr.closed is True


def test_fixed_query_timeout_kills_reaps_and_closes_pipes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakePopen(timeout_once=True)
    monkeypatch.setattr(lifecycle.subprocess, "Popen", lambda *args, **kwargs: fake)
    result = lifecycle._run_fixed_nvidia_smi_query(
        list(lifecycle._GPU_COMMANDS[0][1]), shell=False, timeout_seconds=1.0
    )
    assert result["execution_status"] == "timed_out"
    assert fake.kill_calls == 1 and fake.communicate_calls == 2 and fake.wait_calls >= 1
    assert fake.stdout.closed is True and fake.stderr.closed is True


def test_fixed_query_launch_failure_preserves_os_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = OSError(5, "launch failed")
    monkeypatch.setattr(lifecycle.subprocess, "Popen", lambda *args, **kwargs: (_ for _ in ()).throw(error))
    result = lifecycle._run_fixed_nvidia_smi_query(
        list(lifecycle._GPU_COMMANDS[0][1]), shell=False, timeout_seconds=1.0
    )
    assert result["execution_status"] == "launch_failed"
    assert result["os_error_code"] == 5


def test_fixed_query_cleanup_exception_still_closes_both_pipes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakePopen(wait_error=RuntimeError("wait failed"))
    monkeypatch.setattr(lifecycle.subprocess, "Popen", lambda *args, **kwargs: fake)
    with pytest.raises(RuntimeError, match="wait failed"):
        lifecycle._run_fixed_nvidia_smi_query(
            list(lifecycle._GPU_COMMANDS[0][1]), shell=False, timeout_seconds=1.0
        )
    assert fake.stdout.closed is True and fake.stderr.closed is True


def test_fixed_query_pipe_close_exception_does_not_skip_other_pipe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _FakePopen(stdout_close_error=RuntimeError("stdout close failed"))
    monkeypatch.setattr(lifecycle.subprocess, "Popen", lambda *args, **kwargs: fake)
    with pytest.raises(RuntimeError, match="stdout close failed"):
        lifecycle._run_fixed_nvidia_smi_query(
            list(lifecycle._GPU_COMMANDS[0][1]), shell=False, timeout_seconds=1.0
        )
    assert fake.stdout.closed is True and fake.stderr.closed is True


def test_collect_replay_requires_current_full_production_observer_identity_and_conflicting_bytes_fail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "existing.json"
    existing = _sample(
        path,
        at=datetime(2026, 8, 27, tzinfo=timezone.utc),
        observer_kind="production_direct",
    )
    expected_observer = _observer("production_direct")
    monkeypatch.setattr(lifecycle, "_production_gpu_observer_identity", lambda: expected_observer)
    assert collect_raw_gpu_sample(device_uuid=DEVICE, transcript_path=existing)["observer_identity"] == expected_observer
    _mutate(existing, lambda value: value["observer_identity"].__setitem__("collector_process_identity", {"pid": 0, "create_time_ns": 9999000}))
    with pytest.raises(FileExistsError, match="current production observation"):
        collect_raw_gpu_sample(device_uuid=DEVICE, transcript_path=existing)

    conflicting = tmp_path / "conflicting.json"
    conflicting.write_bytes(b"different bytes")
    with pytest.raises((FileExistsError, ValueError)):
        lifecycle._write_create_only(conflicting, b"expected bytes")


def test_collect_replay_compatibility_ignores_current_collector_incarnation_but_rejects_code_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    path = _sample(
        tmp_path / "cross-process-replay.json",
        at=datetime(2026, 8, 27, tzinfo=timezone.utc),
        observer_kind="production_direct",
    )
    value = json.loads(path.read_text(encoding="utf-8"))
    recorded = seal_immutable(
        {
            "contract_version": "benchmark_v2_gpu_observer_identity_v1",
            "kind": "production_direct",
            "platform": "windows",
            "collector_module_ref": {
                "canonical_path": "C:\\repo\\benchmark_v2_lifecycle.py",
                "file_sha256": "a" * 64,
            },
            "nvidia_smi_ref": {
                "canonical_path": "C:\\Windows\\System32\\nvidia-smi.exe",
                "file_sha256": "b" * 64,
            },
            "collector_process_identity": {"pid": 9001, "create_time_ns": 9001000},
        }
    )
    value["observer_identity"] = recorded
    path.write_bytes(canonical_json_bytes(seal_immutable({key: item for key, item in value.items() if key != "content_sha256"})))
    compatible = seal_immutable(
        {
            **{key: deepcopy(item) for key, item in recorded.items() if key != "content_sha256"},
            "collector_process_identity": {"pid": 9901, "create_time_ns": 9901000},
        }
    )
    monkeypatch.setattr(lifecycle, "_production_gpu_observer_identity", lambda: compatible)
    replayed = collect_raw_gpu_sample(device_uuid=DEVICE, transcript_path=path)
    assert replayed["observer_identity"] == recorded

    for field, replacement in (
        (
            "collector_module_ref",
            {"canonical_path": "C:\\repo\\benchmark_v2_lifecycle.py", "file_sha256": "c" * 64},
        ),
        (
            "nvidia_smi_ref",
            {"canonical_path": "C:\\Windows\\System32\\nvidia-smi.exe", "file_sha256": "d" * 64},
        ),
    ):
        drifted = seal_immutable(
            {
                **{key: deepcopy(item) for key, item in compatible.items() if key != "content_sha256"},
                field: replacement,
            }
        )
        monkeypatch.setattr(lifecycle, "_production_gpu_observer_identity", lambda value=drifted: value)
        with pytest.raises(FileExistsError, match="current production observation"):
            collect_raw_gpu_sample(device_uuid=DEVICE, transcript_path=path)


def test_lifecycle_public_api_exposes_no_command_observer_or_cleanup_injection() -> None:
    assert list(inspect.signature(collect_raw_gpu_sample).parameters) == ["device_uuid", "transcript_path"]
    assert list(inspect.signature(verify_lifecycle_from_raw).parameters) == [
        "owner_journal_paths",
        "sampler_transcript_paths",
        "probe_receipt_paths",
        "actual_mode",
    ]
    assert lifecycle.__all__ == [
        "append_benchmark_v2_attempt_event",
        "collect_raw_gpu_sample",
        "compose_benchmark_v2_attempt_cleanup_receipt",
        "read_benchmark_v2_attempt_journal",
        "verify_lifecycle_from_raw",
    ]


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


def test_task4_fixture_uses_current_upstream_derived_root_and_rejects_identity_drift(tmp_path: Path) -> None:
    import json

    parents = _parent_bundle(tmp_path)
    root_path = next(path for path in parents if path.name == "window-owner.json")
    root = json.loads(root_path.read_text(encoding="utf-8"))
    expected_identity = window_owner._identity(
        str(root["operation_id"]), str(root["screenshot_sha256"]), root_path
    )
    assert all(root[key] == value for key, value in expected_identity.items())
    assert root["root_anchor_path"] == str(window_owner._root_anchor_path(root_path))
    assert root["helper_path"] == str(window_owner._helper_path())
    lifecycle._validate_task4_root_shape(root_path, root)

    wrong = seal_immutable(
        {
            **{key: deepcopy(value) for key, value in root.items() if key != "content_sha256"},
            "scope_name": "Local\\wrong-scope",
        }
    )
    with pytest.raises(lifecycle._EvidenceError, match="derived identity"):
        lifecycle._validate_task4_root_shape(root_path, wrong)


def test_task4_cleanup_reason_must_equal_finalization_reason(tmp_path: Path) -> None:
    import json

    parents = _parent_bundle(tmp_path)
    root_path = next(path for path in parents if path.name == "window-owner.json")
    root = json.loads(root_path.read_text(encoding="utf-8"))
    events_path = Path(str(root["events_path"]))
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    cleanup_body = {key: deepcopy(value) for key, value in events[-1]["payload"].items() if key != "content_sha256"}
    cleanup_body["reason"] = "different"
    cleanup = seal_immutable(cleanup_body)
    event_body = {key: deepcopy(value) for key, value in events[-1].items() if key != "content_sha256"}
    event_body["payload"] = cleanup
    events[-1] = seal_immutable(event_body)
    events_path.write_bytes(b"".join(canonical_json_bytes(event) + b"\n" for event in events))

    result = _verify(
        parents,
        [
            _sample(tmp_path / "baseline.json", at=datetime(2026, 8, 27, tzinfo=timezone.utc)),
        ],
        [],
    )
    assert result["status"] == "failed"
    assert any(item["code"] == "task4_cleanup_lineage_mismatch" for item in result["findings"])


def test_task4_every_outer_event_payload_is_closed(tmp_path: Path) -> None:
    import json

    parents = _parent_bundle(tmp_path)
    root_path = next(path for path in parents if path.name == "window-owner.json")
    root = json.loads(root_path.read_text(encoding="utf-8"))
    events_path = Path(str(root["events_path"]))
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    finalization_body = {
        key: deepcopy(value) for key, value in events[-2].items() if key != "content_sha256"
    }
    finalization_body["payload"]["unexpected"] = True
    events[-2] = seal_immutable(finalization_body)
    cleanup_body = {
        key: deepcopy(value) for key, value in events[-1]["payload"].items() if key != "content_sha256"
    }
    cleanup_body["finalization_intent_sha256"] = events[-2]["content_sha256"]
    cleanup = seal_immutable(cleanup_body)
    cleanup_event_body = {
        key: deepcopy(value) for key, value in events[-1].items() if key != "content_sha256"
    }
    cleanup_event_body["previous_event_sha256"] = events[-2]["content_sha256"]
    cleanup_event_body["payload"] = cleanup
    events[-1] = seal_immutable(cleanup_event_body)
    events_path.write_bytes(b"".join(canonical_json_bytes(event) + b"\n" for event in events))

    result = _verify(parents, [], [])
    assert result["status"] == "failed"
    assert any(item["code"] == "task4_event_payload_invalid" for item in result["findings"])


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
    assert result["status"] == "verified_fixture"
    assert result["gpu_summary"]["owned_peak_mib"] == 400
    assert [4101, 4101000, "GPU-b", 900] in result["gpu_summary"]["external_rows_by_sample"][1]["rows"]
    assert all(item["gpu_uuid"] == DEVICE for item in result["gpu_summary"]["owned_process_vram"])


def test_non_gpu_owner_still_alive_is_not_inferred_absent_from_compute_rows(tmp_path: Path) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    start = datetime(2026, 8, 27, tzinfo=timezone.utc)
    samples[2] = _sample(
        tmp_path / "post-owner-live.json",
        at=start + timedelta(seconds=2),
        rows=[(5101, 5101000, DEVICE, 100)],
        inventory=[(4101, 4101000), (5101, 5101000)],
    )
    result = _verify(parents, samples, probes)
    assert result["status"] == "failed"
    assert any(item["code"] == "owned_process_still_live" for item in result["findings"])


def test_launched_owner_without_exact_in_flight_device_row_is_indeterminate(tmp_path: Path) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    start = datetime(2026, 8, 27, tzinfo=timezone.utc)
    samples[1] = _sample(
        tmp_path / "in-flight-no-worker-gpu-row.json",
        at=start + timedelta(seconds=1),
        total_mib=600,
        rows=[
            (3101, 3101000, DEVICE, 0),
            (4201, 4201000, DEVICE, 0),
            (5101, 5101000, DEVICE, 100),
        ],
        inventory=[
            (3101, 3101000),
            (4101, 4101000),
            (4201, 4201000),
            (5101, 5101000),
        ],
    )
    result = _verify(parents, samples, probes)
    assert result["status"] == "indeterminate"
    assert any(item["code"] == "launched_owner_gpu_row_missing" for item in result["findings"])


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
    assert any(item["code"] == "dangling_parent_ref" for item in result["findings"])


@pytest.mark.parametrize(
    "missing_name",
    [
        "worker-a.worker_process-close.json",
        "exact-termination-observation.json",
        "no-active-lease.json",
    ],
)
def test_conclusion_parent_ref_must_resolve_to_explicit_raw_path(
    tmp_path: Path, missing_name: str
) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    parents = [path for path in parents if path.name != missing_name]
    result = _verify(parents, samples, probes)
    assert result["status"] == "failed"
    assert any(item["code"] == "dangling_parent_ref" for item in result["findings"])


def test_task5_capture_sha_and_client_rect_are_exact_upstream_constraints(tmp_path: Path) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    authority = next(path for path in parents if path.name == "binding-authority.json")
    _mutate(
        authority,
        lambda value: value["serialized_window_binding"].update(
            {"capture_sha256": "f" * 64, "client_rect": {"left": 0, "top": 0, "right": 100, "bottom": 80}}
        ),
    )
    result = _verify(parents, samples, probes)
    assert result["status"] == "failed"
    assert any(
        item["code"] in {"task5_binding_constraint_mismatch", "closed_schema_mismatch"}
        for item in result["findings"]
    )


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
    assert result == _verify(list(reversed(parents)), list(reversed(samples)), list(reversed(probes)))


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
    _set_probe_body_state(probes, provider="qwen", kind="timeout", state="unknown")
    assert _verify(parents, samples, probes)["status"] == "indeterminate"
    _set_probe_body_state(probes, provider="qwen", kind="timeout", state="complete")
    assert _verify(parents, samples, probes)["status"] == "failed"


@pytest.mark.parametrize("residue", ["job", "listener", "lease"])
def test_positive_probe_residue_is_failed(tmp_path: Path, residue: str) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    probes = [path for path in probes if not path.name.startswith("probe-vista-timeout")]
    probes.extend(
        _probe_bundle(
            tmp_path / "probe-vista-timeout.json",
            provider="vista",
            kind="timeout",
            residue=residue,
        )
    )
    result = _verify(parents, samples, probes)
    assert result["status"] == "failed"
    assert any(item["code"] == "probe_residue" for item in result["findings"])


def test_probe_receipt_without_one_raw_zero_parent_never_verifies_cell(tmp_path: Path) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    probes = [path for path in probes if path.name != "probe-omni-cancel-zero-1.json"]
    result = _verify(parents, samples, probes)
    assert result["status"] == "failed"
    assert any(item["code"] == "dangling_probe_ref" for item in result["findings"])
    assert ["omni", "cancel"] in result["probe_summary"]["missing_matrix"]


def test_probe_trigger_after_same_incarnation_termination_is_failed(tmp_path: Path) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    receipt = next(path for path in probes if path.name == "probe-qwen-cancel.json")
    _mutate(
        receipt,
        lambda value: value["trigger"].__setitem__("triggered_at_utc", "2026-08-27T01:00:01.800000Z"),
    )
    result = _verify(parents, samples, probes)
    assert result["status"] == "failed"
    assert any(item["code"] == "probe_trigger_order_invalid" for item in result["findings"])


def test_duplicate_probe_parent_content_is_deterministic_under_path_permutation(tmp_path: Path) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    original = next(path for path in probes if path.name == "probe-vista-timeout-profile.json")
    duplicate = tmp_path / "duplicate-probe-profile.json"
    duplicate.write_bytes(original.read_bytes())
    inputs = [*probes, duplicate.resolve()]
    first = _verify(parents, samples, inputs)
    second = _verify(list(reversed(parents)), list(reversed(samples)), list(reversed(inputs)))
    assert first == second
    assert first["status"] == "failed"


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
    parents = _not_launched_parent_bundle(tmp_path / "parents")
    start = datetime(2026, 8, 27, tzinfo=timezone.utc)
    external = (5101, 5101000, DEVICE, 100)
    samples = [
        _sample(tmp_path / "baseline.json", at=start, rows=[external]),
        _sample(
            tmp_path / "not-launched-in-flight.json",
            at=start + timedelta(seconds=1),
            rows=[(3101, 3101000, DEVICE, 0), external],
        ),
        _sample(tmp_path / "post.json", at=start + timedelta(seconds=2), rows=[external]),
    ]
    probes = [
        path
        for provider in ("omni", "qwen", "vista")
        for kind in ("cancel", "timeout")
        for path in _probe_bundle(
            tmp_path / f"probe-{provider}-{kind}.json", provider=provider, kind=kind
        )
    ]
    result = _verify(parents, samples, probes)
    assert result["status"] == "verified_fixture"
    assert result["cleanup_summary"]["worker"] == "verified_not_launched"
    assert result["cleanup_summary"]["provider"] == "verified_not_acquired"
    assert result["cleanup_summary"]["binding"] == "not_applicable_not_launched"
    assert all(item["pid"] not in {4101, 4201} for item in result["gpu_summary"]["owned_process_vram"])


def test_verify_lifecycle_not_launched_requires_production_none_semantics(tmp_path: Path) -> None:
    import json

    parents = _not_launched_parent_bundle(tmp_path / "parents")
    cleanup_path = next(
        path
        for path in parents
        if (value := json.loads(path.read_text(encoding="utf-8"))).get("contract_version")
        == "benchmark_worker_cleanup_receipt_v1"
        and value.get("outcome") == "verified_not_launched"
    )
    _mutate(cleanup_path, lambda value: value.__setitem__("exact_handle_observation_refs", []))
    start = datetime(2026, 8, 27, tzinfo=timezone.utc)
    external = (5101, 5101000, DEVICE, 100)
    samples = [
        _sample(tmp_path / "baseline.json", at=start, rows=[external]),
        _sample(
            tmp_path / "in-flight.json",
            at=start + timedelta(seconds=1),
            rows=[(3101, 3101000, DEVICE, 0), external],
        ),
        _sample(tmp_path / "post.json", at=start + timedelta(seconds=2), rows=[external]),
    ]
    probes = [
        path
        for provider in ("omni", "qwen", "vista")
        for kind in ("cancel", "timeout")
        for path in _probe_bundle(tmp_path / f"probe-{provider}-{kind}.json", provider=provider, kind=kind)
    ]

    result = _verify(parents, samples, probes)
    assert result["status"] == "failed"
    assert any(item["code"] == "b1_not_launched_branch_contradiction" for item in result["findings"])


def test_b1_not_launched_absence_recomputes_exact_scope_and_event(tmp_path: Path) -> None:
    parents = _not_launched_parent_bundle(tmp_path)
    roles, _refs, _findings, digest_index = lifecycle._load_parent_graph(parents)
    cleanup = roles["b1_cleanup"][0][1]
    observation = lifecycle._resolved_parent(
        digest_index, cleanup["reservation_abort_ref"], "B1 not-launched observation"
    )
    absence_ref = observation["process_event_job_beacon_absence_observation_ref"]
    digest = absence_ref["content_sha256"]
    source, absence = digest_index[digest]
    wrong = deepcopy(absence)
    wrong["checks"]["scope_name"] = "Local\\wrong-scope"
    wrong["checks"]["event_name"] = "Local\\AgentGuiBenchmarkWorkerGate-" + "f" * 64
    corrupted_index = dict(digest_index)
    corrupted_index[digest] = (source, wrong)

    with pytest.raises(lifecycle._EvidenceError, match="pre-anchor absence chain"):
        lifecycle._validate_b1_not_launched_raw(
            roles=roles,
            digest_index=corrupted_index,
            cleanup=cleanup,
        )


def test_actual_mode_rejects_fixture_or_relabelled_observer_identity(tmp_path: Path) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    result = _verify(parents, samples, probes, actual_mode=True)
    assert result["status"] == "failed"
    assert result["release_eligible"] is False
    _mutate(samples[0], lambda value: value["observer_identity"].__setitem__("kind", "production_direct"))
    relabelled = _verify(parents, samples, probes, actual_mode=True)
    assert relabelled["status"] == "failed"
    assert any(
        item["code"] in {
            "actual_task5_parent_path_not_canonical",
            "actual_b1_parent_path_not_canonical",
            "actual_b2_parent_path_not_canonical",
        }
        for item in result["findings"]
    )


def test_actual_mode_rejects_task7_self_signed_probe_parents_even_if_runner_ref_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    monkeypatch.setattr(lifecycle, "_file_ref_matches", lambda _value, _path: True)
    result = _verify(parents, samples, probes, actual_mode=True)
    codes = {item["code"] for item in result["findings"]}
    assert result["status"] == "failed"
    assert result["release_eligible"] is False
    assert {
        "actual_omni_probe_authority_missing",
        "actual_qwen_probe_authority_missing",
        "actual_vista_probe_authority_missing",
    } <= codes


def test_path_alias_duplicate_and_noncanonical_json_are_rejected(tmp_path: Path) -> None:
    parents, samples, probes = _happy_inputs(tmp_path)
    duplicate = _verify(parents, [samples[0], samples[0], *samples[1:]], probes)
    assert duplicate["status"] == "failed"
    samples[0].write_bytes(samples[0].read_bytes() + b"\n")
    assert _verify(parents, samples, probes)["status"] == "failed"
