from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import json
from pathlib import Path
import struct

import pytest

from app.learn.hybrid import benchmark_v2_lifecycle as lifecycle
from app.learn.hybrid import benchmark_v2_window_owner as window_owner
from app.learn.hybrid import benchmark_v2_worker_binding as worker_binding
from app.learn.hybrid.benchmark_v2_contracts import (
    canonical_json_bytes as benchmark_canonical_json_bytes,
)
from app.learn.hybrid.vista_refinement import build_vista_requests
from app.learn import workflow_worker
from app.learn.hybrid.benchmark_v2_lifecycle import (
    collect_raw_gpu_sample,
    verify_lifecycle_from_raw,
)
from app.learn.recognition.uei.canonical import canonical_json_bytes, seal_immutable
from tests.test_learn_hybrid_vista_refinement import _authoritative_inputs


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
        "BenchmarkV2AttemptLedgerProjectionMaterialization",
        "BenchmarkV2AttemptLedgerSelectionHorizon",
        "append_benchmark_v2_attempt_event",
        "collect_raw_gpu_sample",
        "compose_benchmark_v2_attempt_cleanup_receipt",
        "compose_benchmark_v2_lifecycle_probe_receipt_v2",
        "compose_benchmark_v2_lifecycle_bundle_v3",
        "compose_benchmark_v2_probe_stable_zero_evidence_v1",
        "derive_benchmark_v2_cleanup_receipt_ref",
        "materialize_benchmark_v2_attempt_ledger_projections",
        "project_benchmark_v2_cleanup_lifecycle",
        "project_benchmark_v2_attempt_journal_terminal_event",
        "project_benchmark_v2_attempt_journal",
        "project_benchmark_v2_screen_group_lifecycles",
        "project_benchmark_v2_runner_events",
        "project_benchmark_v2_attempt_lifecycle",
        "project_benchmark_v2_attempt_ledger",
        "read_benchmark_v2_attempt_journal",
        "select_benchmark_v2_attempt_ledger_horizon",
        "validate_benchmark_v2_lifecycle_probe_receipt_v2",
        "validate_benchmark_v2_probe_stable_zero_evidence_v1",
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


def _s13_attempt(*, attempt_id: str = "attempt-regression-1") -> dict[str, object]:
    return seal_immutable(
        {
            "contract_version": "benchmark_v2_runner_attempt_ref_v1",
            "attempt_id": attempt_id,
            "partition": "regression",
            "mode": "actual_models",
            "provider_id": None,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )


def _s13_cleanup(attempt: dict[str, object]) -> dict[str, object]:
    return lifecycle.compose_benchmark_v2_attempt_cleanup_receipt(
        attempt_ref=attempt,
        reason="benchmark_v2_actual_runner_finished",
        service_terminal_ref=seal_immutable({"kind": "service-terminal"}),
        window_cleanup_ref=seal_immutable({"kind": "window-cleanup"}),
        provider_cleanup_refs=[seal_immutable({"kind": "provider-cleanup"})],
        resource_counts={
            "service_operations": 0,
            "windows": 0,
            "providers": 0,
            "listeners": 0,
            "leases": 0,
        },
    )


def test_s13_cleanup_receipt_ref_and_projection_are_opaque_and_pathless() -> None:
    attempt = _s13_attempt()
    cleanup = _s13_cleanup(attempt)

    cleanup_ref = lifecycle.derive_benchmark_v2_cleanup_receipt_ref(
        cleanup_receipt=cleanup
    )
    compact = canonical_json_bytes(cleanup)
    assert cleanup_ref == {
        "id": "attempt-cleanup-receipt/"
        + hashlib.sha256(
            b"benchmark-v2-attempt-cleanup-receipt\0" + compact
        ).hexdigest(),
        "content_sha256": hashlib.sha256(compact).hexdigest(),
    }

    projection = lifecycle.project_benchmark_v2_cleanup_lifecycle(
        attempt_ref=attempt,
        cleanup_receipt=cleanup,
    )
    assert projection["contract_version"] == "benchmark_v2_lifecycle_verified_projection_v1"
    assert projection["lifecycle_kind"] == "cleanup"
    assert projection["terminal_status"] == "stable_zero"
    assert projection["cleanup_stable_zero"] is True
    assert projection["resource_counts"] == cleanup["resource_counts"]
    assert projection["started_request_count"] == 0
    assert projection["terminal_or_unknown_request_count"] == 0
    assert projection["parent_refs"] == {"cleanup_receipt_ref": cleanup_ref}
    serialized = canonical_json_bytes(projection)
    assert b"path" not in serialized.lower()
    assert b"benchmark_v2_actual_runner_finished" not in serialized


def test_s13_cleanup_projection_rejects_tampered_raw_parent() -> None:
    attempt = _s13_attempt()
    cleanup = _s13_cleanup(attempt)
    cleanup["reason"] = "tampered"
    with pytest.raises(ValueError, match="cleanup receipt"):
        lifecycle.project_benchmark_v2_cleanup_lifecycle(
            attempt_ref=attempt,
            cleanup_receipt=cleanup,
        )


def _s13_journal(
    *, attempt: dict[str, object], cleanup: dict[str, object]
) -> list[dict[str, object]]:
    prepared = seal_immutable(
        {
            "contract_version": "benchmark_v2_attempt_resource_event_v1",
            "sequence": 1,
            "attempt_ref": attempt,
            "phase": "prepared",
            "event_kind": "attempt_prepared",
            "provider_id": None,
            "probe_kind": None,
            "resource_ref": None,
            "predecessor_content_sha256": None,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    resource = seal_immutable(
        {
            "contract_version": "benchmark_v2_runtime_resource_ref_v1",
            "resource_kind": "attempt_cleanup_receipt",
            "value": {"cleanup_receipt": cleanup},
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    terminal = seal_immutable(
        {
            "contract_version": "benchmark_v2_attempt_resource_event_v1",
            "sequence": 2,
            "attempt_ref": attempt,
            "phase": "terminal",
            "event_kind": "attempt_terminal",
            "provider_id": None,
            "probe_kind": None,
            "resource_ref": resource,
            "predecessor_content_sha256": prepared["content_sha256"],
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    return [prepared, terminal]


def test_s13_journal_terminal_projection_consumes_exact_cleanup_parent() -> None:
    attempt = _s13_attempt()
    cleanup = _s13_cleanup(attempt)
    cleanup_projection = lifecycle.project_benchmark_v2_cleanup_lifecycle(
        attempt_ref=attempt, cleanup_receipt=cleanup
    )
    journal = _s13_journal(attempt=attempt, cleanup=cleanup)

    projection = lifecycle.project_benchmark_v2_attempt_journal_terminal_event(
        attempt_ref=attempt,
        journal_events=journal,
        cleanup_receipt=cleanup,
        cleanup_projection=cleanup_projection,
    )

    assert projection["phase"] == "terminal"
    assert projection["event_kind"] == "attempt_terminal"
    assert projection["sequence"] == 2
    assert projection["predecessor_content_sha256"] == journal[0]["content_sha256"]
    assert projection["raw_event_sha256"] == hashlib.sha256(
        canonical_json_bytes(journal[-1])
    ).hexdigest()
    assert projection["cleanup_receipt_ref"] == lifecycle.derive_benchmark_v2_cleanup_receipt_ref(
        cleanup_receipt=cleanup
    )
    assert projection["cleanup_projection_ref"] == {
        "id": cleanup_projection["artifact_id"],
        "content_sha256": cleanup_projection["content_sha256"],
    }
    assert b"reason" not in canonical_json_bytes(projection)


def test_s13_journal_terminal_projection_rejects_cleanup_byte_drift() -> None:
    attempt = _s13_attempt()
    embedded = _s13_cleanup(attempt)
    supplied = lifecycle.compose_benchmark_v2_attempt_cleanup_receipt(
        attempt_ref=attempt,
        reason="different-valid-receipt",
        service_terminal_ref=seal_immutable({"kind": "service-terminal"}),
        window_cleanup_ref=seal_immutable({"kind": "window-cleanup"}),
        provider_cleanup_refs=[seal_immutable({"kind": "provider-cleanup"})],
        resource_counts=dict(embedded["resource_counts"]),
    )
    supplied_projection = lifecycle.project_benchmark_v2_cleanup_lifecycle(
        attempt_ref=attempt, cleanup_receipt=supplied
    )
    with pytest.raises(ValueError, match="terminal cleanup receipt differs"):
        lifecycle.project_benchmark_v2_attempt_journal_terminal_event(
            attempt_ref=attempt,
            journal_events=_s13_journal(attempt=attempt, cleanup=embedded),
            cleanup_receipt=supplied,
            cleanup_projection=supplied_projection,
        )


def _s13_screen_projection(
    *,
    attempt: dict[str, object],
    screen_group: str,
    case_refs_override: list[dict[str, str]] | None = None,
    evidence_width: int | None = None,
) -> dict[str, object]:
    def ref(name: str) -> dict[str, str]:
        return {
            "id": name,
            "content_sha256": hashlib.sha256(name.encode("utf-8")).hexdigest(),
        }

    def raw_envelope(
        value: dict[str, object], *, id_prefix: str, domain: bytes
    ) -> dict[str, object]:
        raw = canonical_json_bytes(value)
        return {
            "ref": {
                "id": f"{id_prefix}/{hashlib.sha256(domain + raw).hexdigest()}",
                "content_sha256": hashlib.sha256(raw).hexdigest(),
            },
            "canonical_bytes_b64": base64.b64encode(raw).decode("ascii"),
        }

    provider_group_ref = {
        "id": screen_group,
        "content_sha256": hashlib.sha256(screen_group.encode("utf-8")).hexdigest(),
    }
    request_ref = ref(f"request/{screen_group}")
    window_binding_ref = ref(f"binding/{screen_group}")
    capture_ref = ref(f"capture/{screen_group}")
    case_refs = (
        deepcopy(case_refs_override)
        if case_refs_override is not None
        else [
            {
                "case_id": f"{screen_group}-case-{index}",
                "case_content_sha256": hashlib.sha256(
                    f"case:{screen_group}:{index}".encode()
                ).hexdigest(),
            }
            for index in range(5)
        ]
    )
    if len(case_refs) != 5:
        raise ValueError("screen projection helper requires five case refs")
    operations = [
        seal_immutable(
            {
                "mode": "hybrid_v1_1",
                "operation_id": f"{screen_group}-hybrid",
                "status": "complete",
                "request_ref": request_ref,
                "window_binding_ref": window_binding_ref,
                "capture_ref": capture_ref,
            }
        ),
        *[
            seal_immutable(
                {
                    "mode": "incumbent_qwen_only",
                    "operation_id": f"{screen_group}-incumbent-{index}",
                    "status": "complete",
                    "request_ref": {
                        "id": case["case_id"],
                        "content_sha256": case["case_content_sha256"],
                    },
                    "window_binding_ref": window_binding_ref,
                    "capture_ref": capture_ref,
                }
            )
            for index, case in enumerate(case_refs)
        ],
    ]
    executions = [
        {
            "id": f"{operation['mode']}/{operation['operation_id']}",
            "content_sha256": operation["content_sha256"],
        }
        for operation in operations
    ]
    close_ref = seal_immutable(
        {
            "contract_version": "portfolio_hybrid_benchmark_v2_window_cleanup_v1",
            "owner_id": f"owner/{screen_group}",
            "reason": "screen_group_complete",
            "exact_hwnd": 101,
            "process_identity": {"pid": 10, "create_time_ns": 20},
            "cleanup_subject_kind": "ready_window",
            "finalization_intent_sha256": "1" * 64,
            "process_event_sha256": "2" * 64,
            "ready_event_sha256": "3" * 64,
            "publication_content_sha256": "4" * 64,
            "cleanup_status": "verified",
            "shutdown_event_name": f"shutdown-{screen_group}",
            "shutdown_event_signaled": True,
            "shutdown_event_error_code": 0,
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
    service_stable = seal_immutable(
        {
            "contract_version": "benchmark_v2_actual_operations_stable_zero_v1",
            "operation_refs": operations,
            "cleanup_entries": [
                {
                    "operation_ref_sha256": operation["content_sha256"],
                    "terminal_receipt_ref": seal_immutable(
                        {"kind": "terminal", "index": index}
                    ),
                    "worker_cleanup_ref": seal_immutable(
                        {"kind": "worker-cleanup", "index": index}
                    ),
                    "provider_cleanup_ref": seal_immutable(
                        {"kind": "provider-cleanup", "index": index}
                    ),
                }
                for index, operation in enumerate(operations)
            ],
            "window_binding_ref": window_binding_ref,
            "capture_ref": capture_ref,
            "cleanup_status": "stable_zero",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    stable = seal_immutable(
        {
            "contract_version": "benchmark_v2_actual_stable_zero_v1",
            "attempt_ref": attempt,
            "provider_group_ref": provider_group_ref,
            "window_binding_ref": window_binding_ref,
            "execution_refs": executions,
            "window_close_ref": close_ref,
            "service_stable_zero_attestation": service_stable,
            "diagnostic_resource_counts": {
                "service_operations": 0,
                "windows": 0,
                "providers": 0,
                "listeners": 0,
                "leases": 0,
            },
            "cleanup_status": "stable_zero",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    if evidence_width is None:
        fusion, capture_bundle, omni, qwen, qwen_cleanup = _authoritative_inputs()
    else:
        from app.learn.hybrid.fusion import fuse_hybrid_candidates
        from tests.test_learn_hybrid_fusion import _inputs
        from tests.test_learn_hybrid_vista_refinement import _cleanup_receipt

        config, capture_bundle, raw_omni, raw_qwen = _inputs(width=evidence_width)
        omni = seal_immutable(raw_omni)
        qwen = seal_immutable(raw_qwen)
        fusion = seal_immutable(
            fuse_hybrid_candidates(
                config=config,
                capture_bundle=capture_bundle,
                omni_inventory=omni,
                qwen_bindings=qwen,
            )
        )
        qwen_cleanup = _cleanup_receipt()
    vista_requests = build_vista_requests(
        fusion,
        capture_bundle,
        omni_inventory=omni,
        qwen_bindings=qwen,
        qwen_cleanup_receipt=qwen_cleanup,
        expected_workflow_revision=capture_bundle["workflow_revision"],
    )
    shared = {
        "screen_group_ref": provider_group_ref,
        "hybrid_capture_bundle_ref": vista_requests[0]["authoritative_parent_refs"][
            "capture_bundle"
        ],
        "window_binding_ref": window_binding_ref,
        "capture_ref": capture_ref,
        "owner_journal_ref": seal_immutable(
            {"kind": "owner-journal", "screen_group": screen_group}
        ),
        "expected_uia_root_ref": seal_immutable(
            {"kind": "expected-uia-root", "screen_group": screen_group}
        ),
    }
    provider_sets = {
        "qwen_only": ("qwen",),
        "omni_only_discovery": ("omni",),
        "omni_to_qwen": ("omni", "qwen"),
        "omni_to_qwen_vista": ("omni", "qwen", "vista"),
    }
    rows = []
    for case_index, case in enumerate(case_refs):
        for arm_id in (
            "qwen_only",
            "omni_only_discovery",
            "omni_to_qwen",
            "omni_to_qwen_vista",
        ):
            rows.append(
                {
                    "case_ref": case,
                    "arm_id": arm_id,
                    "observation": {
                        "provider_dispatch_receipt_refs": [
                            {
                                "provider": provider,
                                "content_sha256": hashlib.sha256(
                                    f"{screen_group}:{case_index}:{arm_id}:{provider}".encode()
                                ).hexdigest(),
                            }
                            for provider in provider_sets[arm_id]
                        ]
                    },
                    "execution_ref": (
                        executions[case_index + 1]
                        if arm_id == "qwen_only"
                        else executions[0]
                    ),
                    "shared_parent_refs": shared,
                    "artifact_is_authorization": False,
                    "execute_binding_enabled": False,
                }
            )
    pre_vista = seal_immutable(
        {
            "contract_version": "benchmark_v2_actual_pre_vista_evidence_v1",
            "provider_group_ref": provider_group_ref,
            "omni_inventory_envelope": raw_envelope(
                omni,
                id_prefix="omni-inventory",
                domain=b"benchmark-v2-omni-inventory\0",
            ),
            "qwen_bindings_envelope": raw_envelope(
                qwen,
                id_prefix="qwen-bindings",
                domain=b"benchmark-v2-qwen-bindings\0",
            ),
            "fusion_result_envelope": raw_envelope(
                fusion,
                id_prefix="fusion-result",
                domain=b"benchmark-v2-fusion-result\0",
            ),
            "submitted_vista_request_envelopes": [
                raw_envelope(
                    request,
                    id_prefix="submitted-vista-request",
                    domain=b"benchmark-v2-submitted-vista-request\0",
                )
                for request in vista_requests
            ],
            "safety": {
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            },
        }
    )
    return seal_immutable(
        {
            "contract_version": "benchmark_v2_actual_screen_group_projection_v1",
            "benchmark_release_id": "portfolio_hybrid_v1_1_benchmark_v2_release_1",
            "partition": "regression",
            "screen_group": screen_group,
            "request_ref": request_ref,
            "shared_parent_refs": shared,
            "pre_vista_evidence": pre_vista,
            "rows": rows,
            "execution_refs": executions,
            "window_close_ref": close_ref,
            "lifecycle_ref": stable,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )


def test_s13_screen_group_lifecycle_projection_uses_unique_unicode_order() -> None:
    attempt = _s13_attempt()
    ids = [
        "screen-中",
        "screen-ä",
        "screen-z",
        "screen-a",
        "screen-09",
        "screen-10",
        "screen-B",
        "screen-b",
        "screen-é",
        "screen-Ω",
        "screen-あ",
        "screen-😀",
    ]
    raw = [_s13_screen_projection(attempt=attempt, screen_group=item) for item in ids]

    projections = lifecycle.project_benchmark_v2_screen_group_lifecycles(
        attempt_ref=attempt,
        screen_group_projections=list(reversed(raw)),
    )

    assert len(projections) == 12
    ordered_ids = [
        item["parent_refs"]["actual_screen_group_ref"]["id"] for item in projections
    ]
    assert ordered_ids == sorted(ids)
    assert len(set(ordered_ids)) == 12
    for projection in projections:
        assert projection["lifecycle_kind"] == "screen_group"
        assert projection["resource_counts"] == {
            "service_operations": 0,
            "windows": 0,
            "providers": 0,
            "listeners": 0,
            "leases": 0,
        }
        assert projection["parent_refs"]["actual_screen_group_ref"]["id"] == projection[
            "parent_refs"
        ]["provider_group_ref"]["id"]
        assert (
            projection["parent_refs"]["actual_screen_group_ref"]["content_sha256"]
            != projection["parent_refs"]["provider_group_ref"]["content_sha256"]
        )


def test_s13_screen_group_lifecycle_rejects_duplicate_and_cross_group_lineage() -> None:
    attempt = _s13_attempt()
    raw = [
        _s13_screen_projection(attempt=attempt, screen_group=f"screen-{index:02d}")
        for index in range(12)
    ]
    with pytest.raises(ValueError, match="12 unique"):
        lifecycle.project_benchmark_v2_screen_group_lifecycles(
            attempt_ref=attempt,
            screen_group_projections=[*raw[:-1], raw[0]],
        )

    tampered = deepcopy(raw)
    tampered[0]["pre_vista_evidence"]["provider_group_ref"] = {
        "id": "other",
        "content_sha256": "f" * 64,
    }
    tampered[0]["pre_vista_evidence"]["content_sha256"] = lifecycle.content_sha256(
        tampered[0]["pre_vista_evidence"]
    )
    tampered[0]["content_sha256"] = lifecycle.content_sha256(tampered[0])
    with pytest.raises(ValueError, match="provider group"):
        lifecycle.project_benchmark_v2_screen_group_lifecycles(
            attempt_ref=attempt,
            screen_group_projections=tampered,
        )


@pytest.mark.parametrize(
    "fault",
    (
        "release",
        "case_arm_multiset",
        "qwen_capture_lineage",
        "fusion_semantics",
        "vista_parent_lineage",
        "vista_cleanup_lineage",
        "service_capture",
        "window_close_status",
        "attempt_lineage",
    ),
)
def test_s13_screen_group_lifecycle_rejects_reminted_raw_parent_tamper(
    fault: str,
) -> None:
    attempt = _s13_attempt()
    raw = [
        _s13_screen_projection(attempt=attempt, screen_group=f"screen-{index:02d}")
        for index in range(12)
    ]
    target = raw[0]

    def remint_pre_vista_envelope(
        field: str,
        mutate: object,
        *,
        id_prefix: str,
        domain: bytes,
    ) -> None:
        evidence = target["pre_vista_evidence"]
        envelope = evidence[field]
        if isinstance(envelope, list):
            envelope = envelope[0]
        decoded = json.loads(
            base64.b64decode(envelope["canonical_bytes_b64"], validate=True)
        )
        assert callable(mutate)
        mutate(decoded)
        decoded["content_sha256"] = lifecycle.content_sha256(decoded)
        encoded = benchmark_canonical_json_bytes(decoded)
        envelope["canonical_bytes_b64"] = base64.b64encode(encoded).decode("ascii")
        envelope["ref"] = {
            "id": f"{id_prefix}/{hashlib.sha256(domain + encoded).hexdigest()}",
            "content_sha256": hashlib.sha256(encoded).hexdigest(),
        }
        evidence["content_sha256"] = lifecycle.content_sha256(evidence)

    def tamper_cleanup_lineage(decoded: dict[str, object]) -> None:
        cleanup = decoded["qwen_cleanup_receipt"]
        cleanup["cleanup_status"] = "unverified"
        cleanup["content_sha256"] = lifecycle.content_sha256(cleanup)

    if fault == "release":
        target["benchmark_release_id"] = "other-release"
    elif fault == "case_arm_multiset":
        target["rows"][-1]["arm_id"] = "qwen_only"
    elif fault == "qwen_capture_lineage":
        remint_pre_vista_envelope(
            "qwen_bindings_envelope",
            lambda decoded: decoded["capture_identity"].__setitem__(
                "capture_id", "capture/reminted-other"
            ),
            id_prefix="qwen-bindings",
            domain=b"benchmark-v2-qwen-bindings\0",
        )
    elif fault == "fusion_semantics":
        remint_pre_vista_envelope(
            "fusion_result_envelope",
            lambda decoded: decoded["candidates"][0].__setitem__(
                "vista_eligible", False
            ),
            id_prefix="fusion-result",
            domain=b"benchmark-v2-fusion-result\0",
        )
    elif fault == "vista_parent_lineage":
        remint_pre_vista_envelope(
            "submitted_vista_request_envelopes",
            lambda decoded: decoded["authoritative_parent_refs"][
                "qwen_bindings"
            ].__setitem__("content_sha256", "f" * 64),
            id_prefix="submitted-vista-request",
            domain=b"benchmark-v2-submitted-vista-request\0",
        )
    elif fault == "vista_cleanup_lineage":
        remint_pre_vista_envelope(
            "submitted_vista_request_envelopes",
            tamper_cleanup_lineage,
            id_prefix="submitted-vista-request",
            domain=b"benchmark-v2-submitted-vista-request\0",
        )
    elif fault == "service_capture":
        stable = target["lifecycle_ref"]
        service = stable["service_stable_zero_attestation"]
        service["capture_ref"] = {
            "id": "capture/other",
            "content_sha256": "f" * 64,
        }
        service["content_sha256"] = lifecycle.content_sha256(service)
        stable["content_sha256"] = lifecycle.content_sha256(stable)
    elif fault == "window_close_status":
        close = target["window_close_ref"]
        close["cleanup_status"] = "indeterminate"
        close["content_sha256"] = lifecycle.content_sha256(close)
        target["lifecycle_ref"]["window_close_ref"] = close
        target["lifecycle_ref"]["content_sha256"] = lifecycle.content_sha256(
            target["lifecycle_ref"]
        )
    else:
        target["lifecycle_ref"]["attempt_ref"] = _s13_attempt(
            attempt_id="attempt-regression-reminted-other"
        )
        target["lifecycle_ref"]["content_sha256"] = lifecycle.content_sha256(
            target["lifecycle_ref"]
        )
    target["content_sha256"] = lifecycle.content_sha256(target)

    with pytest.raises(ValueError, match="benchmark v2"):
        lifecycle.project_benchmark_v2_screen_group_lifecycles(
            attempt_ref=attempt,
            screen_group_projections=raw,
        )


def _s13_file_ref(*, name: str, value: dict[str, object]) -> dict[str, str]:
    return {
        "path": f"C:\\private\\benchmark\\{name}.json",
        "file_sha256": hashlib.sha256(
            canonical_json_bytes(value) + b"\n"
        ).hexdigest(),
        "content_sha256": str(value["content_sha256"]),
    }


def _s13_runner_payload(
    *,
    attempt: dict[str, object],
    status: str,
    contract_version: str,
    output_ref: dict[str, str] | None = None,
    cleanup_receipt_ref: dict[str, str] | None = None,
) -> dict[str, object]:
    body: dict[str, object] = {
        "contract_version": contract_version,
        "attempt_ref": attempt,
        "attempt_dir": f"C:\\private\\benchmark\\{attempt['attempt_id']}",
        "mode": "actual_models",
        "provider_id": None,
        "status": status,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    if cleanup_receipt_ref is not None:
        body["cleanup_receipt_ref"] = cleanup_receipt_ref
        body["resource_counts"] = {
            "service_operations": 0,
            "windows": 0,
            "providers": 0,
            "listeners": 0,
            "leases": 0,
        }
    else:
        body["output_ref"] = output_ref
    return seal_immutable(body)


def _s13_runner_ledger(
    *,
    attempt: dict[str, object],
    body: dict[str, object],
    cleanup: dict[str, object],
    result: dict[str, object],
) -> list[dict[str, object]]:
    payloads = [
        (
            "regression_attempt",
            _s13_runner_payload(
                attempt=attempt,
                status="opened",
                contract_version="benchmark_v2_runner_regression_attempt_payload_v1",
            ),
        ),
        (
            "regression_attempt",
            _s13_runner_payload(
                attempt=attempt,
                status="body_complete",
                contract_version="benchmark_v2_runner_regression_attempt_payload_v1",
                output_ref=_s13_file_ref(name="body", value=body),
            ),
        ),
        (
            "cleanup",
            _s13_runner_payload(
                attempt=attempt,
                status="terminal",
                contract_version="benchmark_v2_runner_cleanup_payload_v1",
                cleanup_receipt_ref=_s13_file_ref(name="cleanup", value=cleanup),
            ),
        ),
        (
            "result",
            _s13_runner_payload(
                attempt=attempt,
                status="terminal",
                contract_version="benchmark_v2_runner_result_payload_v1",
                output_ref=_s13_file_ref(name="result", value=result),
            ),
        ),
    ]
    ledger: list[dict[str, object]] = []
    previous = "0" * 64
    for sequence, (event_type, payload) in enumerate(payloads):
        event = {
            "partition": "regression",
            "sequence": sequence,
            "event_type": event_type,
            "previous_envelope_sha256": previous,
            "event_payload": payload,
        }
        envelope = {
            "contract_version": "portfolio_hybrid_benchmark_v2_ledger_event_envelope_v2",
            "event": event,
            "event_sha256": hashlib.sha256(canonical_json_bytes(event)).hexdigest(),
        }
        ledger.append(envelope)
        previous = hashlib.sha256(canonical_json_bytes(envelope)).hexdigest()
    return ledger


def _s13_runner_inputs() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    list[dict[str, object]],
]:
    attempt = _s13_attempt()
    cleanup = _s13_cleanup(attempt)
    screen_groups = [
        _s13_screen_projection(attempt=attempt, screen_group=f"screen-{index:02d}")
        for index in range(12)
    ]
    body = seal_immutable(
        {
            "contract_version": "benchmark_v2_runner_actual_body_v1",
            "attempt_ref": attempt,
            "partition": "regression",
            "screen_group_results": screen_groups,
            "body_status": "complete",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    provisional_result = {
        "contract_version": "benchmark_v2_runner_actual_result_v2",
        "attempt_ref": attempt,
        "attempt_dir": "C:\\private\\benchmark\\attempt-regression-1",
        "body_ref": _s13_file_ref(name="body", value=body),
        "cleanup_receipt_ref": _s13_file_ref(name="cleanup", value=cleanup),
        "attempt_ledger_pre_result_ref": {
            "contract_version": "benchmark_v2_runner_ledger_pre_result_ref_v1",
            "id": "runner-ledger-pre-result/" + "6" * 64,
            "attempt_ref": attempt,
            "terminal_sequence": 2,
            "terminal_envelope_sha256": "7" * 64,
            "prefix_sha256": "8" * 64,
        },
        "screen_group_count": 12,
        "status": "terminal",
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    temporary = seal_immutable(provisional_result)
    preliminary_ledger = _s13_runner_ledger(
        attempt=attempt, body=body, cleanup=cleanup, result=temporary
    )
    raw_prefix = b"".join(
        canonical_json_bytes(item) + b"\n" for item in preliminary_ledger[:3]
    )
    provisional_result["attempt_ledger_pre_result_ref"] = {
        "contract_version": "benchmark_v2_runner_ledger_pre_result_ref_v1",
        "id": "runner-ledger-pre-result/"
        + hashlib.sha256(
            b"benchmark-v2-runner-ledger-pre-result\0" + raw_prefix
        ).hexdigest(),
        "attempt_ref": attempt,
        "terminal_sequence": 2,
        "terminal_envelope_sha256": hashlib.sha256(
            canonical_json_bytes(preliminary_ledger[2])
        ).hexdigest(),
        "prefix_sha256": hashlib.sha256(raw_prefix).hexdigest(),
    }
    result = seal_immutable(provisional_result)
    ledger = _s13_runner_ledger(attempt=attempt, body=body, cleanup=cleanup, result=result)
    return attempt, body, cleanup, result, ledger


def test_s13_runner_event_projections_are_ordered_discriminated_and_pathless() -> None:
    attempt, body, cleanup, result, ledger = _s13_runner_inputs()
    cleanup_projection = lifecycle.project_benchmark_v2_cleanup_lifecycle(
        attempt_ref=attempt, cleanup_receipt=cleanup
    )

    projections = lifecycle.project_benchmark_v2_runner_events(
        partition="regression",
        runner_ledger_events=ledger,
        actual_body=body,
        actual_result=result,
        cleanup_receipt=cleanup,
        cleanup_projection=cleanup_projection,
    )

    assert [item["sequence"] for item in projections] == [0, 1, 2, 3]
    assert [item["event_kind"] for item in projections] == [
        "opened",
        "body_complete",
        "cleanup",
        "result",
    ]
    assert projections[0]["previous_event_projection_ref"] is None
    for previous, current in zip(projections[:-1], projections[1:], strict=True):
        assert current["previous_event_projection_ref"] == {
            "id": previous["artifact_id"],
            "content_sha256": previous["content_sha256"],
        }
    assert set(projections[0]["load_bearing_refs"]) == {"attempt_ref"}
    assert set(projections[1]["load_bearing_refs"]) == {"body_file_ref"}
    assert set(projections[2]["load_bearing_refs"]) == {
        "cleanup_receipt_ref",
        "cleanup_projection_ref",
    }
    assert set(projections[3]["load_bearing_refs"]) == {
        "result_file_ref",
        "attempt_ledger_pre_result_ref",
    }
    serialized = canonical_json_bytes(projections)
    assert b"C:\\\\private" not in serialized
    assert b'"path"' not in serialized


def test_s13_runner_event_projection_rejects_hash_chain_drift() -> None:
    attempt, body, cleanup, result, ledger = _s13_runner_inputs()
    cleanup_projection = lifecycle.project_benchmark_v2_cleanup_lifecycle(
        attempt_ref=attempt, cleanup_receipt=cleanup
    )
    ledger[2]["event"]["previous_envelope_sha256"] = "f" * 64
    ledger[2]["event_sha256"] = hashlib.sha256(
        canonical_json_bytes(ledger[2]["event"])
    ).hexdigest()
    with pytest.raises(ValueError, match="hash chain"):
        lifecycle.project_benchmark_v2_runner_events(
            partition="regression",
            runner_ledger_events=ledger,
            actual_body=body,
            actual_result=result,
            cleanup_receipt=cleanup,
            cleanup_projection=cleanup_projection,
        )


def _s13_journal_projection(
    *,
    attempt: dict[str, object],
    journal: list[dict[str, object]],
    terminal_projection: dict[str, object],
    cleanup_projection: dict[str, object],
) -> dict[str, object]:
    from app.learn.hybrid.benchmark_v2_pathless import seal_pathless_projection

    raw = b"".join(canonical_json_bytes(item) + b"\n" for item in journal)
    return seal_pathless_projection(
        contract_version="benchmark_v2_attempt_journal_verified_projection_v1",
        semantic_payload={
            "attempt_ref": {
                "id": f"runner-attempt/{attempt['attempt_id']}",
                "content_sha256": attempt["content_sha256"],
            },
            "raw_journal_sha256": hashlib.sha256(raw).hexdigest(),
            "terminal_event_ref": {
                "id": terminal_projection["artifact_id"],
                "content_sha256": terminal_projection["content_sha256"],
            },
            "started_request_count": 0,
            "terminal_or_unknown_request_count": 0,
            "cleanup_projection_ref": {
                "id": cleanup_projection["artifact_id"],
                "content_sha256": cleanup_projection["content_sha256"],
            },
            "verified": True,
            "safety": {
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
                "display_only": True,
            },
        },
    )


def test_s13_attempt_lifecycle_closes_journal_cleanup_terminal_and_12_screens() -> None:
    attempt, body, cleanup, _result, _ledger = _s13_runner_inputs()
    cleanup_projection = lifecycle.project_benchmark_v2_cleanup_lifecycle(
        attempt_ref=attempt, cleanup_receipt=cleanup
    )
    journal = _s13_journal(attempt=attempt, cleanup=cleanup)
    terminal = lifecycle.project_benchmark_v2_attempt_journal_terminal_event(
        attempt_ref=attempt,
        journal_events=journal,
        cleanup_receipt=cleanup,
        cleanup_projection=cleanup_projection,
    )
    journal_projection = _s13_journal_projection(
        attempt=attempt,
        journal=journal,
        terminal_projection=terminal,
        cleanup_projection=cleanup_projection,
    )
    screen_projections = lifecycle.project_benchmark_v2_screen_group_lifecycles(
        attempt_ref=attempt,
        screen_group_projections=body["screen_group_results"],
    )

    projection = lifecycle.project_benchmark_v2_attempt_lifecycle(
        attempt_ref=attempt,
        journal_events=journal,
        attempt_journal_projection=journal_projection,
        cleanup_projection=cleanup_projection,
        terminal_event_projection=terminal,
        screen_group_lifecycle_projections=screen_projections,
    )

    assert projection["lifecycle_kind"] == "attempt"
    assert projection["terminal_status"] == "terminal"
    assert projection["cleanup_stable_zero"] is True
    assert projection["started_request_count"] == 0
    assert projection["terminal_or_unknown_request_count"] == 0
    assert set(projection["parent_refs"]) == {
        "attempt_journal_projection_ref",
        "cleanup_projection_ref",
        "terminal_event_ref",
        "screen_group_lifecycle_projection_refs",
    }
    resolved_ids = [
        item["parent_refs"]["actual_screen_group_ref"]["id"]
        for item in screen_projections
    ]
    assert resolved_ids == sorted(resolved_ids)


def test_s13_attempt_lifecycle_rejects_provider_request_events_in_frozen_v1() -> None:
    attempt, body, cleanup, _result, _ledger = _s13_runner_inputs()
    cleanup_projection = lifecycle.project_benchmark_v2_cleanup_lifecycle(
        attempt_ref=attempt, cleanup_receipt=cleanup
    )
    journal = _s13_journal(attempt=attempt, cleanup=cleanup)
    request = seal_immutable(
        {
            "contract_version": "benchmark_v2_attempt_resource_event_v1",
            "sequence": 2,
            "attempt_ref": attempt,
            "phase": "request_in_flight",
            "event_kind": "provider_request_in_flight",
            "provider_id": "qwen",
            "probe_kind": "timeout",
            "resource_ref": seal_immutable({"kind": "request"}),
            "predecessor_content_sha256": journal[0]["content_sha256"],
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    journal[-1]["sequence"] = 3
    journal[-1]["predecessor_content_sha256"] = request["content_sha256"]
    journal[-1]["content_sha256"] = lifecycle.content_sha256(journal[-1])
    journal = [journal[0], request, journal[-1]]
    terminal = lifecycle.project_benchmark_v2_attempt_journal_terminal_event(
        attempt_ref=attempt,
        journal_events=journal,
        cleanup_receipt=cleanup,
        cleanup_projection=cleanup_projection,
    )
    journal_projection = _s13_journal_projection(
        attempt=attempt,
        journal=journal,
        terminal_projection=terminal,
        cleanup_projection=cleanup_projection,
    )
    screens = lifecycle.project_benchmark_v2_screen_group_lifecycles(
        attempt_ref=attempt,
        screen_group_projections=body["screen_group_results"],
    )
    with pytest.raises(ValueError, match="journal chain"):
        lifecycle.project_benchmark_v2_attempt_lifecycle(
            attempt_ref=attempt,
            journal_events=journal,
            attempt_journal_projection=journal_projection,
            cleanup_projection=cleanup_projection,
            terminal_event_projection=terminal,
            screen_group_lifecycle_projections=screens,
        )


def _s13_runner_prefix_projection(
    *,
    ledger: list[dict[str, object]],
    events: list[dict[str, object]],
) -> dict[str, object]:
    from app.learn.hybrid.benchmark_v2_pathless import seal_pathless_projection

    raw_prefix = b"".join(canonical_json_bytes(item) + b"\n" for item in ledger)
    selected_attempt = events[-1]["attempt_ref"]
    selected_events = [
        item for item in events if item["attempt_ref"] == selected_attempt
    ]
    by_kind = {str(item["event_kind"]): item for item in selected_events}
    return seal_pathless_projection(
        contract_version="benchmark_v2_runner_ledger_prefix_verified_projection_v1",
        semantic_payload={
            "partition": "regression",
            "raw_prefix_sha256": hashlib.sha256(raw_prefix).hexdigest(),
            "attempt_ledger_pre_result_ref": events[-1]["load_bearing_refs"][
                "attempt_ledger_pre_result_ref"
            ],
            "through_result_terminal_sequence": events[-1]["sequence"],
            "through_result_terminal_envelope_sha256": hashlib.sha256(
                canonical_json_bytes(ledger[-1])
            ).hexdigest(),
            "attempt_ref": selected_attempt,
            "body_file_ref": by_kind["body_complete"]["load_bearing_refs"][
                "body_file_ref"
            ],
            "cleanup_event_projection_ref": {
                "id": by_kind["cleanup"]["artifact_id"],
                "content_sha256": by_kind["cleanup"]["content_sha256"],
            },
            "result_file_ref": by_kind["result"]["load_bearing_refs"][
                "result_file_ref"
            ],
            "result_event_projection_ref": {
                "id": by_kind["result"]["artifact_id"],
                "content_sha256": by_kind["result"]["content_sha256"],
            },
            "verified": True,
            "safety": {
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
                "display_only": True,
            },
        },
    )


def _s13_complete_graph() -> dict[str, object]:
    attempt, body, cleanup, result, ledger = _s13_runner_inputs()
    cleanup_projection = lifecycle.project_benchmark_v2_cleanup_lifecycle(
        attempt_ref=attempt, cleanup_receipt=cleanup
    )
    journal = _s13_journal(attempt=attempt, cleanup=cleanup)
    terminal = lifecycle.project_benchmark_v2_attempt_journal_terminal_event(
        attempt_ref=attempt,
        journal_events=journal,
        cleanup_receipt=cleanup,
        cleanup_projection=cleanup_projection,
    )
    journal_projection = _s13_journal_projection(
        attempt=attempt,
        journal=journal,
        terminal_projection=terminal,
        cleanup_projection=cleanup_projection,
    )
    screens = lifecycle.project_benchmark_v2_screen_group_lifecycles(
        attempt_ref=attempt,
        screen_group_projections=body["screen_group_results"],
    )
    attempt_lifecycle = lifecycle.project_benchmark_v2_attempt_lifecycle(
        attempt_ref=attempt,
        journal_events=journal,
        attempt_journal_projection=journal_projection,
        cleanup_projection=cleanup_projection,
        terminal_event_projection=terminal,
        screen_group_lifecycle_projections=screens,
    )
    events = lifecycle.project_benchmark_v2_runner_events(
        partition="regression",
        runner_ledger_events=ledger,
        actual_body=body,
        actual_result=result,
        cleanup_receipt=cleanup,
        cleanup_projection=cleanup_projection,
    )
    prefix = _s13_runner_prefix_projection(ledger=ledger, events=events)
    return {
        "attempt": attempt,
        "body": body,
        "cleanup": cleanup,
        "result": result,
        "ledger": ledger,
        "cleanup_projection": cleanup_projection,
        "journal": journal,
        "terminal": terminal,
        "journal_projection": journal_projection,
        "screens": screens,
        "attempt_lifecycle": attempt_lifecycle,
        "events": events,
        "prefix": prefix,
    }


def test_s13_projected_attempt_ledger_selects_first_complete_actual_attempt() -> None:
    graph = _s13_complete_graph()
    projected = lifecycle.project_benchmark_v2_attempt_ledger(
        benchmark_release_id="portfolio_hybrid_v1_1_benchmark_v2_release_1",
        partition="regression",
        runner_ledger_events=graph["ledger"],
        runner_event_projections=graph["events"],
        raw_ledger_prefix_projection=graph["prefix"],
        attempt_lifecycle_projections=[graph["attempt_lifecycle"]],
    )

    assert projected["contract_version"] == "benchmark_v2_projected_attempt_ledger_v1"
    assert projected["entries"] == [
        {
            "sequence": 0,
            "attempt_ref": graph["events"][0]["attempt_ref"],
            "observed_state": "result",
            "event_projection_refs": [
                {"id": item["artifact_id"], "content_sha256": item["content_sha256"]}
                for item in graph["events"]
            ],
            "lifecycle_ref": {
                "id": graph["attempt_lifecycle"]["artifact_id"],
                "content_sha256": graph["attempt_lifecycle"]["content_sha256"],
            },
            "selection_eligible": True,
        }
    ]
    assert projected["selected_attempt_ref"] == graph["events"][0]["attempt_ref"]


def test_s13_projected_attempt_ledger_rejects_reordered_projected_events() -> None:
    graph = _s13_complete_graph()
    reordered = deepcopy(graph["events"])
    reordered[1], reordered[2] = reordered[2], reordered[1]
    with pytest.raises(ValueError, match="event projection order"):
        lifecycle.project_benchmark_v2_attempt_ledger(
            benchmark_release_id="portfolio_hybrid_v1_1_benchmark_v2_release_1",
            partition="regression",
            runner_ledger_events=graph["ledger"],
            runner_event_projections=reordered,
            raw_ledger_prefix_projection=graph["prefix"],
            attempt_lifecycle_projections=[graph["attempt_lifecycle"]],
        )


def test_s13_lifecycle_bundle_v3_is_exact_ranked_closed_and_pathless() -> None:
    import json

    graph = _s13_complete_graph()
    ledger = lifecycle.project_benchmark_v2_attempt_ledger(
        benchmark_release_id="portfolio_hybrid_v1_1_benchmark_v2_release_1",
        partition="regression",
        runner_ledger_events=graph["ledger"],
        runner_event_projections=graph["events"],
        raw_ledger_prefix_projection=graph["prefix"],
        attempt_lifecycle_projections=[graph["attempt_lifecycle"]],
    )
    bundle = lifecycle.compose_benchmark_v2_lifecycle_bundle_v3(
        benchmark_release_id="portfolio_hybrid_v1_1_benchmark_v2_release_1",
        partition="regression",
        attempt_ref=graph["attempt"],
        raw_ledger_prefix_projection=graph["prefix"],
        projected_attempt_ledger=ledger,
        selected_attempt_lifecycle_projection=graph["attempt_lifecycle"],
        cleanup_lifecycle_projection=graph["cleanup_projection"],
        journal_terminal_event_projection=graph["terminal"],
        attempt_journal_projection=graph["journal_projection"],
        screen_group_lifecycle_projections=graph["screens"],
        runner_event_projections=graph["events"],
        cleanup_receipt=graph["cleanup"],
    )

    decoded = [
        json.loads(base64.b64decode(item["canonical_bytes_b64"]).decode("utf-8"))
        for item in bundle["sealed_artifact_envelopes"]
    ]
    assert [item["lifecycle_kind"] for item in decoded[:12]] == [
        "screen_group"
    ] * 12
    assert decoded[12]["lifecycle_kind"] == "cleanup"
    assert decoded[13]["contract_version"] == (
        "benchmark_v2_attempt_journal_terminal_event_verified_projection_v1"
    )
    assert decoded[14]["lifecycle_kind"] == "attempt"
    assert [item["event_kind"] for item in decoded[15:19]] == [
        "opened",
        "body_complete",
        "cleanup",
        "result",
    ]
    assert decoded[19]["contract_version"] == "benchmark_v2_projected_attempt_ledger_v1"
    assert bundle["screen_group_lifecycle_projection_refs"] == [
        {"id": item["artifact_id"], "content_sha256": item["content_sha256"]}
        for item in graph["screens"]
    ]
    serialized = canonical_json_bytes(bundle)
    assert b'"path"' not in serialized
    assert b"C:\\\\private" not in serialized
    assert b"benchmark_v2_actual_runner_finished" not in serialized


def test_s13_lifecycle_bundle_v3_rejects_missing_screen_and_orphan_envelope() -> None:
    graph = _s13_complete_graph()
    ledger = lifecycle.project_benchmark_v2_attempt_ledger(
        benchmark_release_id="portfolio_hybrid_v1_1_benchmark_v2_release_1",
        partition="regression",
        runner_ledger_events=graph["ledger"],
        runner_event_projections=graph["events"],
        raw_ledger_prefix_projection=graph["prefix"],
        attempt_lifecycle_projections=[graph["attempt_lifecycle"]],
    )
    with pytest.raises(ValueError, match="12 screen-group"):
        lifecycle.compose_benchmark_v2_lifecycle_bundle_v3(
            benchmark_release_id="portfolio_hybrid_v1_1_benchmark_v2_release_1",
            partition="regression",
            attempt_ref=graph["attempt"],
            raw_ledger_prefix_projection=graph["prefix"],
            projected_attempt_ledger=ledger,
            selected_attempt_lifecycle_projection=graph["attempt_lifecycle"],
            cleanup_lifecycle_projection=graph["cleanup_projection"],
            journal_terminal_event_projection=graph["terminal"],
            attempt_journal_projection=graph["journal_projection"],
            screen_group_lifecycle_projections=graph["screens"][:-1],
            runner_event_projections=graph["events"],
            cleanup_receipt=graph["cleanup"],
        )


def _s13_append_runner_event(
    ledger: list[dict[str, object]],
    *,
    event_type: str,
    payload: dict[str, object],
) -> None:
    previous = (
        hashlib.sha256(canonical_json_bytes(ledger[-1])).hexdigest()
        if ledger
        else "0" * 64
    )
    event = {
        "partition": "regression",
        "sequence": len(ledger),
        "event_type": event_type,
        "previous_envelope_sha256": previous,
        "event_payload": payload,
    }
    ledger.append(
        {
            "contract_version": "portfolio_hybrid_benchmark_v2_ledger_event_envelope_v2",
            "event": event,
            "event_sha256": hashlib.sha256(canonical_json_bytes(event)).hexdigest(),
        }
    )


def _s13_complete_attempt_artifacts(
    ledger: list[dict[str, object]], *, attempt_id: str
) -> dict[str, object]:
    attempt = _s13_attempt(attempt_id=attempt_id)
    cleanup = _s13_cleanup(attempt)
    body = seal_immutable(
        {
            "contract_version": "benchmark_v2_runner_actual_body_v1",
            "attempt_ref": attempt,
            "partition": "regression",
            "screen_group_results": [
                _s13_screen_projection(
                    attempt=attempt, screen_group=f"{attempt_id}-screen-{index:02d}"
                )
                for index in range(12)
            ],
            "body_status": "complete",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    _s13_append_runner_event(
        ledger,
        event_type="regression_attempt",
        payload=_s13_runner_payload(
            attempt=attempt,
            status="opened",
            contract_version="benchmark_v2_runner_regression_attempt_payload_v1",
        ),
    )
    _s13_append_runner_event(
        ledger,
        event_type="regression_attempt",
        payload=_s13_runner_payload(
            attempt=attempt,
            status="body_complete",
            contract_version="benchmark_v2_runner_regression_attempt_payload_v1",
            output_ref=_s13_file_ref(name=f"{attempt_id}-body", value=body),
        ),
    )
    _s13_append_runner_event(
        ledger,
        event_type="cleanup",
        payload=_s13_runner_payload(
            attempt=attempt,
            status="terminal",
            contract_version="benchmark_v2_runner_cleanup_payload_v1",
            cleanup_receipt_ref=_s13_file_ref(
                name=f"{attempt_id}-cleanup", value=cleanup
            ),
        ),
    )
    raw_prefix = b"".join(canonical_json_bytes(item) + b"\n" for item in ledger)
    cleanup_event = ledger[-1]
    pre_result_ref = {
        "contract_version": "benchmark_v2_runner_ledger_pre_result_ref_v1",
        "id": "runner-ledger-pre-result/"
        + hashlib.sha256(
            b"benchmark-v2-runner-ledger-pre-result\0" + raw_prefix
        ).hexdigest(),
        "attempt_ref": attempt,
        "terminal_sequence": cleanup_event["event"]["sequence"],
        "terminal_envelope_sha256": hashlib.sha256(
            canonical_json_bytes(cleanup_event)
        ).hexdigest(),
        "prefix_sha256": hashlib.sha256(raw_prefix).hexdigest(),
    }
    result = seal_immutable(
        {
            "contract_version": "benchmark_v2_runner_actual_result_v2",
            "attempt_ref": attempt,
            "attempt_dir": f"C:\\private\\benchmark\\{attempt_id}",
            "body_ref": _s13_file_ref(name=f"{attempt_id}-body", value=body),
            "cleanup_receipt_ref": _s13_file_ref(
                name=f"{attempt_id}-cleanup", value=cleanup
            ),
            "attempt_ledger_pre_result_ref": pre_result_ref,
            "screen_group_count": 12,
            "status": "terminal",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    _s13_append_runner_event(
        ledger,
        event_type="result",
        payload=_s13_runner_payload(
            attempt=attempt,
            status="terminal",
            contract_version="benchmark_v2_runner_result_payload_v1",
            output_ref=_s13_file_ref(name=f"{attempt_id}-result", value=result),
        ),
    )
    cleanup_projection = lifecycle.project_benchmark_v2_cleanup_lifecycle(
        attempt_ref=attempt, cleanup_receipt=cleanup
    )
    journal = _s13_journal(attempt=attempt, cleanup=cleanup)
    terminal = lifecycle.project_benchmark_v2_attempt_journal_terminal_event(
        attempt_ref=attempt,
        journal_events=journal,
        cleanup_receipt=cleanup,
        cleanup_projection=cleanup_projection,
    )
    journal_projection = _s13_journal_projection(
        attempt=attempt,
        journal=journal,
        terminal_projection=terminal,
        cleanup_projection=cleanup_projection,
    )
    screens = lifecycle.project_benchmark_v2_screen_group_lifecycles(
        attempt_ref=attempt,
        screen_group_projections=body["screen_group_results"],
    )
    attempt_lifecycle = lifecycle.project_benchmark_v2_attempt_lifecycle(
        attempt_ref=attempt,
        journal_events=journal,
        attempt_journal_projection=journal_projection,
        cleanup_projection=cleanup_projection,
        terminal_event_projection=terminal,
        screen_group_lifecycle_projections=screens,
    )
    return {
        "attempt": attempt,
        "body": body,
        "cleanup": cleanup,
        "result": result,
        "cleanup_projection": cleanup_projection,
        "terminal": terminal,
        "journal_projection": journal_projection,
        "screens": screens,
        "attempt_lifecycle": attempt_lifecycle,
    }


def _s13_project_multi_attempt_events(
    *, ledger: list[dict[str, object]], complete: list[dict[str, object]]
) -> list[dict[str, object]]:
    return lifecycle.project_benchmark_v2_runner_events(
        partition="regression",
        runner_ledger_events=ledger,
        actual_body=[item["body"] for item in complete],
        actual_result=[item["result"] for item in complete],
        cleanup_receipt=[item["cleanup"] for item in complete],
        cleanup_projection=[item["cleanup_projection"] for item in complete],
    )


def test_s13_projected_ledger_keeps_prior_incomplete_attempt_before_later_complete() -> None:
    ledger: list[dict[str, object]] = []
    incomplete = _s13_attempt(attempt_id="attempt-regression-incomplete")
    _s13_append_runner_event(
        ledger,
        event_type="regression_attempt",
        payload=_s13_runner_payload(
            attempt=incomplete,
            status="opened",
            contract_version="benchmark_v2_runner_regression_attempt_payload_v1",
        ),
    )
    complete = _s13_complete_attempt_artifacts(
        ledger, attempt_id="attempt-regression-complete"
    )
    events = _s13_project_multi_attempt_events(ledger=ledger, complete=[complete])
    prefix = _s13_runner_prefix_projection(ledger=ledger, events=events)

    projected = lifecycle.project_benchmark_v2_attempt_ledger(
        benchmark_release_id="portfolio_hybrid_v1_1_benchmark_v2_release_1",
        partition="regression",
        runner_ledger_events=ledger,
        runner_event_projections=events,
        raw_ledger_prefix_projection=prefix,
        attempt_lifecycle_projections=[complete["attempt_lifecycle"]],
    )

    assert [item["observed_state"] for item in projected["entries"]] == [
        "opened",
        "result",
    ]
    assert [item["selection_eligible"] for item in projected["entries"]] == [
        False,
        True,
    ]
    assert projected["selected_attempt_ref"] == events[1]["attempt_ref"]
    assert [item["sequence"] for item in events] == [0, 1, 2, 3, 4]
    bundle = lifecycle.compose_benchmark_v2_lifecycle_bundle_v3(
        benchmark_release_id="portfolio_hybrid_v1_1_benchmark_v2_release_1",
        partition="regression",
        attempt_ref=complete["attempt"],
        raw_ledger_prefix_projection=prefix,
        projected_attempt_ledger=projected,
        selected_attempt_lifecycle_projection=complete["attempt_lifecycle"],
        cleanup_lifecycle_projection=complete["cleanup_projection"],
        journal_terminal_event_projection=complete["terminal"],
        attempt_journal_projection=complete["journal_projection"],
        screen_group_lifecycle_projections=complete["screens"],
        runner_event_projections=events,
        cleanup_receipt=complete["cleanup"],
    )
    decoded = [
        json.loads(base64.b64decode(item["canonical_bytes_b64"]).decode("utf-8"))
        for item in bundle["sealed_artifact_envelopes"]
    ]
    assert [item["event_kind"] for item in decoded[15:20]] == [
        "opened",
        "opened",
        "body_complete",
        "cleanup",
        "result",
    ]
    assert decoded[20]["contract_version"] == "benchmark_v2_projected_attempt_ledger_v1"


def test_s13_bundle_closes_prior_cleaned_incomplete_attempt_before_selected_complete() -> None:
    incomplete = _s13_complete_attempt_artifacts(
        [], attempt_id="attempt-regression-cleaned-incomplete"
    )
    ledger: list[dict[str, object]] = []
    _s13_append_runner_event(
        ledger,
        event_type="regression_attempt",
        payload=_s13_runner_payload(
            attempt=incomplete["attempt"],
            status="opened",
            contract_version="benchmark_v2_runner_regression_attempt_payload_v1",
        ),
    )
    _s13_append_runner_event(
        ledger,
        event_type="regression_attempt",
        payload=_s13_runner_payload(
            attempt=incomplete["attempt"],
            status="body_complete",
            contract_version="benchmark_v2_runner_regression_attempt_payload_v1",
            output_ref=_s13_file_ref(
                name="cleaned-incomplete-body", value=incomplete["body"]
            ),
        ),
    )
    _s13_append_runner_event(
        ledger,
        event_type="cleanup",
        payload=_s13_runner_payload(
            attempt=incomplete["attempt"],
            status="terminal",
            contract_version="benchmark_v2_runner_cleanup_payload_v1",
            cleanup_receipt_ref=_s13_file_ref(
                name="cleaned-incomplete-cleanup", value=incomplete["cleanup"]
            ),
        ),
    )
    complete = _s13_complete_attempt_artifacts(
        ledger, attempt_id="attempt-regression-selected-after-cleanup"
    )
    events = lifecycle.project_benchmark_v2_runner_events(
        partition="regression",
        runner_ledger_events=ledger,
        actual_body=[incomplete["body"], complete["body"]],
        actual_result=[complete["result"]],
        cleanup_receipt=[incomplete["cleanup"], complete["cleanup"]],
        cleanup_projection=[
            incomplete["cleanup_projection"],
            complete["cleanup_projection"],
        ],
    )
    prefix = _s13_runner_prefix_projection(ledger=ledger, events=events)
    projected = lifecycle.project_benchmark_v2_attempt_ledger(
        benchmark_release_id="portfolio_hybrid_v1_1_benchmark_v2_release_1",
        partition="regression",
        runner_ledger_events=ledger,
        runner_event_projections=events,
        raw_ledger_prefix_projection=prefix,
        attempt_lifecycle_projections=[complete["attempt_lifecycle"]],
    )

    assert [item["observed_state"] for item in projected["entries"]] == [
        "cleanup",
        "result",
    ]
    assert [item["selection_eligible"] for item in projected["entries"]] == [
        False,
        True,
    ]
    bundle = lifecycle.compose_benchmark_v2_lifecycle_bundle_v3(
        benchmark_release_id="portfolio_hybrid_v1_1_benchmark_v2_release_1",
        partition="regression",
        attempt_ref=complete["attempt"],
        raw_ledger_prefix_projection=prefix,
        projected_attempt_ledger=projected,
        selected_attempt_lifecycle_projection=complete["attempt_lifecycle"],
        cleanup_lifecycle_projection=complete["cleanup_projection"],
        cleanup_lifecycle_projections=[
            incomplete["cleanup_projection"],
            complete["cleanup_projection"],
        ],
        journal_terminal_event_projection=complete["terminal"],
        attempt_journal_projection=complete["journal_projection"],
        screen_group_lifecycle_projections=complete["screens"],
        runner_event_projections=events,
        cleanup_receipt=complete["cleanup"],
    )
    decoded = [
        json.loads(base64.b64decode(item["canonical_bytes_b64"]).decode("utf-8"))
        for item in bundle["sealed_artifact_envelopes"]
    ]
    cleanup_items = [
        item
        for item in decoded
        if item.get("contract_version")
        == "benchmark_v2_lifecycle_verified_projection_v1"
        and item.get("lifecycle_kind") == "cleanup"
    ]
    assert len(cleanup_items) == 2
    assert [item["attempt_ref"] for item in cleanup_items] == [
        events[0]["attempt_ref"],
        events[3]["attempt_ref"],
    ]


def test_s13_two_complete_attempts_select_first_open_and_do_not_publish_later_suffix() -> None:
    ledger: list[dict[str, object]] = []
    first = _s13_complete_attempt_artifacts(
        ledger, attempt_id="attempt-regression-first"
    )
    second = _s13_complete_attempt_artifacts(
        ledger, attempt_id="attempt-regression-second"
    )
    events = _s13_project_multi_attempt_events(
        ledger=ledger, complete=[first, second]
    )
    selected_prefix = ledger[:4]
    prefix = _s13_runner_prefix_projection(
        ledger=selected_prefix, events=events[:4]
    )

    projected = lifecycle.project_benchmark_v2_attempt_ledger(
        benchmark_release_id="portfolio_hybrid_v1_1_benchmark_v2_release_1",
        partition="regression",
        runner_ledger_events=ledger,
        runner_event_projections=events,
        raw_ledger_prefix_projection=prefix,
        attempt_lifecycle_projections=[
            second["attempt_lifecycle"],
            first["attempt_lifecycle"],
        ],
    )
    materialized = lifecycle.materialize_benchmark_v2_attempt_ledger_projections(
        benchmark_release_id="portfolio_hybrid_v1_1_benchmark_v2_release_1",
        partition="regression",
        runner_ledger_events=ledger,
        runner_event_projections=events,
        attempt_lifecycle_projections=[
            second["attempt_lifecycle"],
            first["attempt_lifecycle"],
        ],
    )
    assert materialized.runner_ledger_prefix_projection == prefix
    assert materialized.projected_attempt_ledger == projected

    assert len(events) == 8
    assert len(projected["entries"]) == 1
    assert projected["selected_attempt_ref"] == events[0]["attempt_ref"]
    assert projected["entries"][0]["event_projection_refs"] == [
        {"id": item["artifact_id"], "content_sha256": item["content_sha256"]}
        for item in events[:4]
    ]
    bundle = lifecycle.compose_benchmark_v2_lifecycle_bundle_v3(
        benchmark_release_id="portfolio_hybrid_v1_1_benchmark_v2_release_1",
        partition="regression",
        attempt_ref=first["attempt"],
        raw_ledger_prefix_projection=prefix,
        projected_attempt_ledger=projected,
        selected_attempt_lifecycle_projection=first["attempt_lifecycle"],
        cleanup_lifecycle_projection=first["cleanup_projection"],
        journal_terminal_event_projection=first["terminal"],
        attempt_journal_projection=first["journal_projection"],
        screen_group_lifecycle_projections=first["screens"],
        runner_event_projections=events,
        cleanup_receipt=first["cleanup"],
    )
    decoded = [
        json.loads(base64.b64decode(item["canonical_bytes_b64"]).decode("utf-8"))
        for item in bundle["sealed_artifact_envelopes"]
    ]
    assert [item["event_kind"] for item in decoded[15:19]] == [
        "opened",
        "body_complete",
        "cleanup",
        "result",
    ]
    assert len(decoded) == 20


def _c4_interleaved_complete_ledger() -> tuple[
    list[dict[str, object]], dict[str, object], dict[str, object]
]:
    first_chain: list[dict[str, object]] = []
    second_chain: list[dict[str, object]] = []
    first = _s13_complete_attempt_artifacts(
        first_chain, attempt_id="attempt-regression-first-open"
    )
    second = _s13_complete_attempt_artifacts(
        second_chain, attempt_id="attempt-regression-first-result"
    )
    ledger: list[dict[str, object]] = []
    for envelope in [
        first_chain[0],
        *second_chain,
        *first_chain[1:],
    ]:
        _s13_append_runner_event(
            ledger,
            event_type=str(envelope["event"]["event_type"]),
            payload=deepcopy(envelope["event"]["event_payload"]),
        )
    return ledger, first, second


def test_c4_selection_horizon_uses_first_open_not_first_result() -> None:
    ledger, first, _second = _c4_interleaved_complete_ledger()

    horizon = lifecycle.select_benchmark_v2_attempt_ledger_horizon(
        runner_ledger_events=ledger
    )

    assert horizon.selected_attempt_ref == {
        "id": "runner-attempt/attempt-regression-first-open",
        "content_sha256": first["attempt"]["content_sha256"],
    }
    assert horizon.selected_result_terminal_sequence == 7


def test_c4_selection_horizon_skips_prior_incomplete_attempt() -> None:
    complete_chain: list[dict[str, object]] = []
    complete = _s13_complete_attempt_artifacts(
        complete_chain, attempt_id="attempt-regression-complete-after-incomplete"
    )
    incomplete = _s13_attempt(attempt_id="attempt-regression-incomplete-before")
    ledger: list[dict[str, object]] = []
    _s13_append_runner_event(
        ledger,
        event_type="regression_attempt",
        payload=_s13_runner_payload(
            attempt=incomplete,
            status="opened",
            contract_version="benchmark_v2_runner_regression_attempt_payload_v1",
        ),
    )
    for envelope in complete_chain:
        _s13_append_runner_event(
            ledger,
            event_type=str(envelope["event"]["event_type"]),
            payload=deepcopy(envelope["event"]["event_payload"]),
        )

    horizon = lifecycle.select_benchmark_v2_attempt_ledger_horizon(
        runner_ledger_events=ledger
    )

    assert horizon.selected_attempt_ref["content_sha256"] == complete["attempt"][
        "content_sha256"
    ]
    assert horizon.selected_result_terminal_sequence == 4


def test_c4_selection_horizon_rejects_corrupt_structural_suffix() -> None:
    ledger, _first, _second = _c4_interleaved_complete_ledger()
    ledger[-1]["event_sha256"] = "f" * 64

    with pytest.raises(ValueError, match="hash chain"):
        lifecycle.select_benchmark_v2_attempt_ledger_horizon(
            runner_ledger_events=ledger
        )


def test_c4_selection_horizon_rejects_noncanonical_suffix_file_ref() -> None:
    ledger, _first, _second = _c4_interleaved_complete_ledger()
    payload = deepcopy(ledger[2]["event"]["event_payload"])
    payload["output_ref"]["path"] = "relative-body.json"
    ledger[2]["event"]["event_payload"] = seal_immutable(
        {key: value for key, value in payload.items() if key != "content_sha256"}
    )
    rebuilt: list[dict[str, object]] = []
    for envelope in ledger:
        _s13_append_runner_event(
            rebuilt,
            event_type=str(envelope["event"]["event_type"]),
            payload=deepcopy(envelope["event"]["event_payload"]),
        )

    with pytest.raises(ValueError, match="structure"):
        lifecycle.select_benchmark_v2_attempt_ledger_horizon(
            runner_ledger_events=rebuilt
        )


def test_c4_projection_never_replaces_selected_raw_complete_without_lifecycle() -> None:
    ledger: list[dict[str, object]] = []
    first = _s13_complete_attempt_artifacts(
        ledger, attempt_id="attempt-regression-selected-no-lifecycle"
    )
    second = _s13_complete_attempt_artifacts(
        ledger, attempt_id="attempt-regression-later-with-lifecycle"
    )
    events = _s13_project_multi_attempt_events(
        ledger=ledger, complete=[first, second]
    )

    with pytest.raises(ValueError, match="selected.*lifecycle|lifecycle.*selected"):
        lifecycle.materialize_benchmark_v2_attempt_ledger_projections(
            benchmark_release_id="portfolio_hybrid_v1_1_benchmark_v2_release_1",
            partition="regression",
            runner_ledger_events=ledger,
            runner_event_projections=events,
            attempt_lifecycle_projections=[second["attempt_lifecycle"]],
        )


def test_c4_interleaved_cleanup_children_follow_first_open_order() -> None:
    from app.learn.hybrid.benchmark_v2_pathless import (
        pathless_artifact_ref,
        seal_pathless_projection,
    )

    first_chain: list[dict[str, object]] = []
    first = _s13_complete_attempt_artifacts(
        first_chain, attempt_id="attempt-regression-first-open-late-result"
    )
    second_chain: list[dict[str, object]] = []
    second = _s13_complete_attempt_artifacts(
        second_chain, attempt_id="attempt-regression-second-open-early-result"
    )
    ledger: list[dict[str, object]] = []
    source_by_key: dict[tuple[str, str], dict[str, object]] = {}
    for artifacts, chain in ((first, first_chain), (second, second_chain)):
        projected = _s13_project_multi_attempt_events(
            ledger=chain, complete=[artifacts]
        )
        for item in projected:
            source_by_key[
                (str(item["attempt_ref"]["content_sha256"]), str(item["event_kind"]))
            ] = item
    for envelope in [first_chain[0], *second_chain, *first_chain[1:]]:
        _s13_append_runner_event(
            ledger,
            event_type=str(envelope["event"]["event_type"]),
            payload=deepcopy(envelope["event"]["event_payload"]),
        )
    events: list[dict[str, object]] = []
    kind_for_raw = {
        ("regression_attempt", "opened"): "opened",
        ("regression_attempt", "body_complete"): "body_complete",
        ("cleanup", "terminal"): "cleanup",
        ("result", "terminal"): "result",
    }
    for envelope in ledger:
        raw_event = envelope["event"]
        raw_payload = raw_event["event_payload"]
        event_kind = kind_for_raw[
            (str(raw_event["event_type"]), str(raw_payload["status"]))
        ]
        public_attempt = {
            "id": f"runner-attempt/{raw_payload['attempt_ref']['attempt_id']}",
            "content_sha256": raw_payload["attempt_ref"]["content_sha256"],
        }
        source = source_by_key[
            (str(public_attempt["content_sha256"]), event_kind)
        ]
        events.append(
            seal_pathless_projection(
                contract_version="benchmark_v2_runner_event_verified_projection_v1",
                semantic_payload={
                    "partition": "regression",
                    "event_kind": event_kind,
                    "sequence": int(raw_event["sequence"]),
                    "attempt_ref": public_attempt,
                    "previous_event_projection_ref": (
                        pathless_artifact_ref(events[-1]) if events else None
                    ),
                    "raw_event_sha256": hashlib.sha256(
                        canonical_json_bytes(envelope)
                    ).hexdigest(),
                    "load_bearing_refs": deepcopy(source["load_bearing_refs"]),
                    "safety": {
                        "artifact_is_authorization": False,
                        "execute_binding_enabled": False,
                        "display_only": True,
                    },
                },
            )
        )
    materialized = lifecycle.materialize_benchmark_v2_attempt_ledger_projections(
        benchmark_release_id="portfolio_hybrid_v1_1_benchmark_v2_release_1",
        partition="regression",
        runner_ledger_events=ledger,
        runner_event_projections=events,
        attempt_lifecycle_projections=[first["attempt_lifecycle"]],
    )

    bundle = lifecycle.compose_benchmark_v2_lifecycle_bundle_v3(
        benchmark_release_id="portfolio_hybrid_v1_1_benchmark_v2_release_1",
        partition="regression",
        attempt_ref=first["attempt"],
        raw_ledger_prefix_projection=materialized.runner_ledger_prefix_projection,
        projected_attempt_ledger=materialized.projected_attempt_ledger,
        selected_attempt_lifecycle_projection=first["attempt_lifecycle"],
        cleanup_lifecycle_projection=first["cleanup_projection"],
        cleanup_lifecycle_projections=[
            first["cleanup_projection"],
            second["cleanup_projection"],
        ],
        journal_terminal_event_projection=first["terminal"],
        attempt_journal_projection=first["journal_projection"],
        screen_group_lifecycle_projections=first["screens"],
        runner_event_projections=events,
        cleanup_receipt=first["cleanup"],
    )

    decoded = [
        json.loads(base64.b64decode(item["canonical_bytes_b64"], validate=True))
        for item in bundle["sealed_artifact_envelopes"]
    ]
    cleanup_children = [
        item
        for item in decoded
        if item.get("contract_version")
        == "benchmark_v2_lifecycle_verified_projection_v1"
        and item.get("lifecycle_kind") == "cleanup"
    ]
    assert [item["attempt_ref"]["content_sha256"] for item in cleanup_children] == [
        first["attempt"]["content_sha256"],
        second["attempt"]["content_sha256"],
    ]


def test_c4_runner_prefix_wrapper_uses_existing_first_complete_selector() -> None:
    graph = _s13_complete_graph()
    materialized = lifecycle.materialize_benchmark_v2_attempt_ledger_projections(
        benchmark_release_id="portfolio_hybrid_v1_1_benchmark_v2_release_1",
        partition="regression",
        runner_ledger_events=graph["ledger"],
        runner_event_projections=graph["events"],
        attempt_lifecycle_projections=[graph["attempt_lifecycle"]],
    )
    assert materialized.runner_ledger_prefix_projection == graph["prefix"]
    assert materialized.projected_attempt_ledger == lifecycle.project_benchmark_v2_attempt_ledger(
        benchmark_release_id="portfolio_hybrid_v1_1_benchmark_v2_release_1",
        partition="regression",
        runner_ledger_events=graph["ledger"],
        runner_event_projections=graph["events"],
        raw_ledger_prefix_projection=graph["prefix"],
        attempt_lifecycle_projections=[graph["attempt_lifecycle"]],
    )


def test_c4_attempt_journal_projection_rejects_terminal_cleanup_swap() -> None:
    from app.learn.hybrid.benchmark_v2_pathless import seal_pathless_projection

    graph = _s13_complete_graph()
    projected = lifecycle.project_benchmark_v2_attempt_journal(
        attempt_ref=graph["attempt"],
        journal_events=graph["journal"],
        terminal_event_projection=graph["terminal"],
        cleanup_projection=graph["cleanup_projection"],
    )
    assert projected == graph["journal_projection"]
    semantic = {
        key: deepcopy(value)
        for key, value in graph["terminal"].items()
        if key not in {"contract_version", "artifact_id", "content_sha256"}
    }
    semantic["cleanup_projection_ref"] = {
        "id": "verified-lifecycle/" + "f" * 64,
        "content_sha256": "e" * 64,
    }
    swapped = seal_pathless_projection(
        contract_version="benchmark_v2_attempt_journal_terminal_event_verified_projection_v1",
        semantic_payload=semantic,
    )
    with pytest.raises(ValueError, match="journal parent lineage"):
        lifecycle.project_benchmark_v2_attempt_journal(
            attempt_ref=graph["attempt"],
            journal_events=graph["journal"],
            terminal_event_projection=swapped,
            cleanup_projection=graph["cleanup_projection"],
        )
