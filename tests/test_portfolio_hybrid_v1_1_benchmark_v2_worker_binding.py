from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import struct
import sys
import time

import pytest

from app.core.window_manager import window_manager
from app.learn.hybrid.benchmark_v2_contracts import canonical_json_bytes, content_sha256
from app.learn.hybrid.benchmark_v2_window_owner import (
    close_owned_window,
    launch_owned_window,
)
from app.learn.hybrid.windows_process_scope import (
    WindowsProcessScope,
    observe_process_scope_cleanup,
    spawn_process_in_scope,
)
from app.learn.hybrid.benchmark_v2_worker_binding import (
    ADOPTED_RECEIPT_CONTRACT,
    NORMAL_CLEAR_RECEIPT_CONTRACT,
    WORKER_BINDING_CONTRACT,
    install_spawned_worker_window_binding,
    serialize_worker_window_binding,
    validate_spawned_worker_observation_payload,
)
from app.learn.workflow_service import (
    LearningWorkflowStageOperationError,
    build_learning_pipeline_initial_worker_request,
    inject_benchmark_v2_worker_window_binding,
    validate_benchmark_v2_worker_window_binding_adoption,
)
from app.learn.workflow_worker import _run_learning_stage_worker_entry
from app.operation.screen_reading.uia_provider import uia_provider


pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows exact HWND required")


def _bmp(path: Path, *, width: int = 96, height: int = 64) -> str:
    stride = (width * 3 + 3) & ~3
    pixels = bytearray()
    for y in range(height):
        row = bytearray()
        for x in range(width):
            row.extend(((x * 3) % 256, (y * 5) % 256, (x + y) % 256))
        row.extend(b"\0" * (stride - width * 3))
        pixels.extend(row)
    header = struct.pack(
        "<2sIHHI", b"BM", 54 + len(pixels), 0, 0, 54
    ) + struct.pack(
        "<IIIHHIIIIII", 40, width, height, 1, 24, 0, len(pixels), 2835, 2835, 0, 0
    )
    raw = header + pixels
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _assert_window_cleanup(receipt: dict[str, object]) -> None:
    assert receipt["cleanup_status"] == "verified"
    assert receipt["enum_windows_exact_hwnd_absent"] is True
    assert receipt["matching_owned_windows_after"] == []
    assert receipt["member_pids_after"] == []
    assert receipt["stable_zero_observations"] >= 3
    assert receipt["scope_absent_after_owner_close"] is True
    assert receipt["process_handle_closed"] is True
    assert receipt["job_handle_closed"] is True
    assert receipt["active_listeners_after"] == []
    assert receipt["listener_or_lease_residue"] == []


@contextmanager
def _owned(tmp_path: Path, name: str):
    image = tmp_path / f"{name}.bmp"
    digest = _bmp(image)
    journal = (tmp_path / f"{name}.owner.json").resolve()
    owner = None
    try:
        owner = launch_owned_window(
            image_path=image,
            expected_sha256=digest,
            operation_id=f"operation-{name}",
            journal_path=journal,
        )
        yield owner, journal
    finally:
        if journal.exists():
            _assert_window_cleanup(
                close_owned_window(journal_path=journal, reason="test_finally")
            )


def _serialized(owner: dict[str, object]) -> dict[str, object]:
    return serialize_worker_window_binding(
        operation_ref={"operation_id": owner["operation_id"]},
        owner=owner,
        capture_ref={
            "capture_sha256": owner["screenshot_sha256"],
            "capture_image_path": owner["screenshot_path"],
        },
    )


def _payload_sha(value: dict[str, object]) -> str:
    unhashed = {key: item for key, item in value.items() if key != "payload_sha256"}
    return hashlib.sha256(canonical_json_bytes(unhashed)).hexdigest()


def _reseal(value: dict[str, object]) -> dict[str, object]:
    value["payload_sha256"] = _payload_sha(value)
    return value


def _spawn_snapshot(path: str) -> None:
    snapshot = uia_provider.snapshot_bound_window()
    Path(path).write_bytes(canonical_json_bytes(snapshot))


def _spawn_install_probe(
    serialized: dict[str, object],
    operation_id: str,
    adopted_path: str,
    normal_path: str,
    ready_event,
    release_event,
) -> None:
    lifecycle: dict[str, object] | None = None
    with install_spawned_worker_window_binding(
        serialized=serialized,
        worker_operation_id=operation_id,
    ) as lifecycle:
        Path(adopted_path).write_bytes(canonical_json_bytes(lifecycle["adopted_receipt"]))
        ready_event.set()
        if release_event is not None:
            release_event.wait(20)
    Path(normal_path).write_bytes(canonical_json_bytes(lifecycle["normal_clear_receipt"]))


def _spawn_install_must_fail(
    serialized: dict[str, object], operation_id: str, marker_path: str
) -> None:
    try:
        with install_spawned_worker_window_binding(
            serialized=serialized,
            worker_operation_id=operation_id,
        ):
            Path(marker_path).write_text("provider-dispatched", encoding="utf-8")
    except BaseException:
        return
    raise AssertionError("invalid binding reached provider dispatch marker")


def _strong_kill_worker_cli(
    serialized_path: str,
    operation_id: str,
    adopted_path: str,
    normal_path: str,
    ready_path: str,
) -> None:
    serialized = json.loads(Path(serialized_path).read_text(encoding="utf-8"))
    lifecycle = None
    with install_spawned_worker_window_binding(
        serialized=serialized,
        worker_operation_id=operation_id,
    ) as lifecycle:
        Path(adopted_path).write_bytes(canonical_json_bytes(lifecycle["adopted_receipt"]))
        Path(ready_path).write_text("ready", encoding="utf-8")
        while True:
            time.sleep(1)
    Path(normal_path).write_bytes(canonical_json_bytes(lifecycle["normal_clear_receipt"]))


def _join_or_kill(process, *, timeout: float = 30.0) -> None:
    process.join(timeout)
    if process.is_alive():
        process.terminate()
        process.join(10)
    assert not process.is_alive()


def test_contracts_and_service_cut_point_are_closed_and_server_owned(tmp_path: Path) -> None:
    with _owned(tmp_path, "service") as (owner, _journal):
        serialized = _serialized(owner)
        assert serialized["contract_version"] == WORKER_BINDING_CONTRACT
        assert serialized["payload_sha256"] == _payload_sha(serialized)
        assert serialized["exact_hwnd"] == owner["hwnd"]
        assert serialized["process_identity"] == owner["process_identity"]
        assert serialized["job_name"] == owner["scope_name"]
        assert serialized["screenshot_sha256"] == owner["screenshot_sha256"]
        assert serialized["capture_sha256"] == owner["screenshot_sha256"]
        assert serialized["capture_image_path"] == owner["screenshot_path"]
        assert serialized["image_dimensions"] == owner["image_dimensions"]
        assert serialized["window_rect"] == owner["window_rect"]
        assert serialized["owner_id"] == owner["owner_id"]
        assert serialized["owner_journal_path"] == str(Path(owner["journal_path"]).resolve())
        assert serialized["owner_journal_content_sha256"] == owner["journal_root_sha256"]
        assert serialized["expected_uia_root_hwnd"] == owner["hwnd"]
        assert serialized["expected_uia_owner_pid"] == owner["process_identity"]["pid"]
        assert serialized["artifact_is_authorization"] is False
        assert serialized["execute_binding_enabled"] is False

        child = inject_benchmark_v2_worker_window_binding(
            payload={
                "capture_live": False,
                "image_path": owner["screenshot_path"],
            },
            operation_ref={"operation_id": owner["operation_id"]},
            owner=owner,
            capture_ref={
                "capture_sha256": owner["screenshot_sha256"],
                "capture_image_path": owner["screenshot_path"],
            },
        )
        assert child == {
            "capture_live": False,
            "image_path": owner["screenshot_path"],
            "_benchmark_v2_window_binding": serialized,
        }
        with pytest.raises(
            LearningWorkflowStageOperationError,
            match="server-owned",
        ):
            build_learning_pipeline_initial_worker_request(
                payload={"_benchmark_v2_window_binding": serialized}
            )
        with pytest.raises(
            LearningWorkflowStageOperationError,
            match="server-owned",
        ):
            inject_benchmark_v2_worker_window_binding(
                payload={"_benchmark_v2_window_binding": serialized},
                operation_ref={"operation_id": owner["operation_id"]},
                owner=owner,
                capture_ref={
                    "capture_sha256": owner["screenshot_sha256"],
                    "capture_image_path": owner["screenshot_path"],
                },
            )


def test_parent_only_binding_is_not_inherited_by_real_spawn(tmp_path: Path) -> None:
    with _owned(tmp_path, "parent-only") as (owner, _journal):
        previous = window_manager._bound_window
        output = tmp_path / "parent-only.json"
        process = None
        try:
            window_manager.bind_window_by_handle(int(owner["hwnd"]))
            process = multiprocessing.get_context("spawn").Process(
                target=_spawn_snapshot,
                args=(str(output),),
            )
            process.start()
            _join_or_kill(process)
            snapshot = json.loads(output.read_text(encoding="utf-8"))
            assert snapshot["status"] == "unavailable"
            assert snapshot["reason"] == "no_bound_window"
        finally:
            if process is not None and process.is_alive():
                process.terminate()
                process.join(10)
            window_manager._bound_window = previous


def test_real_spawn_installs_exact_pinned_snapshot_and_writes_normal_clear(
    tmp_path: Path,
) -> None:
    with _owned(tmp_path, "spawn-success") as (owner, _journal):
        serialized = _serialized(owner)
        adopted_path = tmp_path / "adopted.json"
        normal_path = tmp_path / "normal.json"
        context = multiprocessing.get_context("spawn")
        ready = context.Event()
        process = context.Process(
            target=_spawn_install_probe,
            args=(
                serialized,
                owner["operation_id"],
                str(adopted_path),
                str(normal_path),
                ready,
                None,
            ),
        )
        try:
            process.start()
            _join_or_kill(process)
            assert process.exitcode == 0
            adopted = json.loads(adopted_path.read_text(encoding="utf-8"))
            normal = json.loads(normal_path.read_text(encoding="utf-8"))
            assert adopted["contract_version"] == ADOPTED_RECEIPT_CONTRACT
            assert adopted["binding_payload_sha256"] == serialized["payload_sha256"]
            assert adopted["capture_sha256"] == owner["screenshot_sha256"]
            assert adopted["uia_root_hwnd"] == owner["hwnd"]
            assert adopted["uia_owner_pid"] == owner["process_identity"]["pid"]
            assert adopted["snapshot_ref"]["content_sha256"]
            assert adopted["content_sha256"] == content_sha256(adopted)
            assert normal["contract_version"] == NORMAL_CLEAR_RECEIPT_CONTRACT
            assert normal["binding_payload_sha256"] == serialized["payload_sha256"]
            assert normal["cleared"] is True
            assert normal["content_sha256"] == content_sha256(normal)
        finally:
            if process.is_alive():
                process.terminate()
                process.join(10)


def test_binding_holds_screenshot_no_write_no_delete_and_validates_observe_payload(
    tmp_path: Path,
) -> None:
    with _owned(tmp_path, "sharing") as (owner, _journal):
        serialized = _serialized(owner)
        image = Path(str(owner["screenshot_path"]))
        replacement = tmp_path / "replacement.bmp"
        replacement.write_bytes(image.read_bytes())
        validate_spawned_worker_observation_payload(
            payload={"capture_live": False, "image_path": str(image)},
            serialized=serialized,
        )
        for payload in (
            {"capture_live": True, "image_path": str(image)},
            {"capture_live": False, "image_path": str(replacement.resolve())},
        ):
            with pytest.raises(ValueError, match="capture_live|image_path"):
                validate_spawned_worker_observation_payload(
                    payload=payload,
                    serialized=serialized,
                )
        with install_spawned_worker_window_binding(
            serialized=serialized,
            worker_operation_id=str(owner["operation_id"]),
        ) as lifecycle:
            with pytest.raises(PermissionError):
                image.write_bytes(b"changed")
            with pytest.raises(PermissionError):
                image.unlink()
            assert lifecycle["snapshot"]["window"]["handle"] == owner["hwnd"]
        assert image.exists()


@pytest.mark.parametrize("raised", [RuntimeError("handler failed"), KeyboardInterrupt()])
def test_python_exception_and_baseexception_unwind_mint_normal_clear(
    tmp_path: Path, raised: BaseException
) -> None:
    with _owned(tmp_path, "unwind-" + type(raised).__name__) as (owner, _journal):
        lifecycle = None
        with pytest.raises(type(raised), match=str(raised) or None):
            with install_spawned_worker_window_binding(
                serialized=_serialized(owner),
                worker_operation_id=str(owner["operation_id"]),
            ) as lifecycle:
                raise raised
        assert lifecycle["normal_clear_receipt"]["cleared"] is True
        assert lifecycle["normal_clear_receipt"]["content_sha256"] == content_sha256(
            lifecycle["normal_clear_receipt"]
        )
        assert window_manager._bound_window is None


def test_service_rebuilds_benchmark_adoption_from_server_refs_and_generic_digest(
    tmp_path: Path,
) -> None:
    with _owned(tmp_path, "adoption") as (owner, _journal):
        operation_ref = {"operation_id": owner["operation_id"]}
        capture_ref = {
            "capture_sha256": owner["screenshot_sha256"],
            "capture_image_path": owner["screenshot_path"],
        }
        worker_payload = inject_benchmark_v2_worker_window_binding(
            payload={
                "capture_live": False,
                "image_path": owner["screenshot_path"],
            },
            operation_ref=operation_ref,
            owner=owner,
            capture_ref=capture_ref,
        )
        lifecycle = None
        with install_spawned_worker_window_binding(
            serialized=worker_payload["_benchmark_v2_window_binding"],
            worker_operation_id=str(owner["operation_id"]),
        ) as lifecycle:
            assert lifecycle["snapshot"]["status"] == "ok"
        evidence = {
            "adopted_receipt": lifecycle["adopted_receipt"],
            "normal_clear_receipt": lifecycle["normal_clear_receipt"],
            "snapshot": lifecycle["snapshot"],
        }
        generic = {
            "contract_version": "learning_stage_worker_result_adoption_v1",
            "status": "adopted",
            "receipt": {
                "contract_version": "learning_stage_worker_result_adoption_v1",
                "worker_id": "worker-adoption",
                "run_id": "run-adoption",
                "stage": "screen_understanding",
                "operation_id": owner["operation_id"],
                "task_kind": "vision_observe_screen",
                "model_request_id": "model-adoption",
                "payload_sha256": _payload_sha(worker_payload),
                "result_sha256": "3" * 64,
                "adopted_at": "2026-08-26T00:00:00+00:00",
            },
            "response": {
                "_benchmark_v2_window_binding_evidence": evidence,
            },
        }
        receipt = validate_benchmark_v2_worker_window_binding_adoption(
            worker_payload=worker_payload,
            generic_adoption=generic,
            operation_ref=operation_ref,
            owner=owner,
            capture_ref=capture_ref,
        )
        assert receipt["binding_payload_sha256"] == worker_payload[
            "_benchmark_v2_window_binding"
        ]["payload_sha256"]
        assert receipt["worker_payload_sha256"] == generic["receipt"][
            "payload_sha256"
        ]
        assert receipt["worker_result_sha256"] == "3" * 64
        assert receipt["snapshot_ref"] == lifecycle["adopted_receipt"]["snapshot_ref"]
        assert receipt["normal_clear_receipt_ref"] == lifecycle[
            "normal_clear_receipt"
        ]["content_sha256"]
        assert receipt["content_sha256"] == content_sha256(receipt)

        tampered = deepcopy(generic)
        tampered["response"]["_benchmark_v2_window_binding_evidence"][
            "adopted_receipt"
        ]["capture_sha256"] = "0" * 64
        with pytest.raises(LearningWorkflowStageOperationError, match="adoption"):
            validate_benchmark_v2_worker_window_binding_adoption(
                worker_payload=worker_payload,
                generic_adoption=tampered,
                operation_ref=operation_ref,
                owner=owner,
                capture_ref=capture_ref,
            )

        reminted = deepcopy(generic)
        reminted_evidence = reminted["response"][
            "_benchmark_v2_window_binding_evidence"
        ]
        reminted_evidence["snapshot"]["unexpected"] = "self-minted"
        reminted_adopted = reminted_evidence["adopted_receipt"]
        reminted_adopted["snapshot_ref"]["content_sha256"] = hashlib.sha256(
            canonical_json_bytes(reminted_evidence["snapshot"])
        ).hexdigest()
        reminted_adopted["content_sha256"] = content_sha256(reminted_adopted)
        with pytest.raises(LearningWorkflowStageOperationError, match="adoption"):
            validate_benchmark_v2_worker_window_binding_adoption(
                worker_payload=worker_payload,
                generic_adoption=reminted,
                operation_ref=operation_ref,
                owner=owner,
                capture_ref=capture_ref,
            )


@pytest.mark.parametrize(
    ("mutation", "expected_fragment"),
    [
        (lambda value: value["process_identity"].__setitem__("pid", os.getpid()), "process"),
        (
            lambda value: value["process_identity"].__setitem__("create_time_ns", 1),
            "process",
        ),
        (lambda value: value.__setitem__("job_name", value["job_name"] + "-wrong"), "Job"),
        (lambda value: value.__setitem__("exact_hwnd", 1), "HWND"),
        (lambda value: value.__setitem__("capture_sha256", "0" * 64), "capture"),
        (
            lambda value: value.__setitem__(
                "owner_journal_path", str(Path(value["owner_journal_path"]).with_name("missing.json"))
            ),
            "journal",
        ),
    ],
)
def test_wrong_serialized_identity_fails_before_dispatch(
    tmp_path: Path, mutation, expected_fragment: str
) -> None:
    with _owned(tmp_path, "wrong-" + expected_fragment.lower()) as (owner, _journal):
        serialized = deepcopy(_serialized(owner))
        mutation(serialized)
        _reseal(serialized)
        marker = tmp_path / f"{expected_fragment}.dispatch"
        process = multiprocessing.get_context("spawn").Process(
            target=_spawn_install_must_fail,
            args=(serialized, owner["operation_id"], str(marker)),
        )
        try:
            process.start()
            _join_or_kill(process)
            assert process.exitcode == 0
            assert not marker.exists()
        finally:
            if process.is_alive():
                process.terminate()
                process.join(10)


def test_wrong_payload_sha_and_ambient_or_nested_binding_fail_closed(tmp_path: Path) -> None:
    with _owned(tmp_path, "ambient") as (owner, _journal):
        serialized = _serialized(owner)
        wrong_sha = deepcopy(serialized)
        wrong_sha["payload_sha256"] = "0" * 64
        with pytest.raises(ValueError, match="payload SHA"):
            with install_spawned_worker_window_binding(
                serialized=wrong_sha,
                worker_operation_id=str(owner["operation_id"]),
            ):
                pytest.fail("wrong payload SHA reached dispatch")

        previous = window_manager._bound_window
        try:
            window_manager.bind_window_by_handle(int(owner["hwnd"]))
            with pytest.raises(ValueError, match="ambient"):
                with install_spawned_worker_window_binding(
                    serialized=serialized,
                    worker_operation_id=str(owner["operation_id"]),
                ):
                    pytest.fail("ambient binding reached dispatch")
        finally:
            window_manager._bound_window = previous

        with install_spawned_worker_window_binding(
            serialized=serialized,
            worker_operation_id=str(owner["operation_id"]),
        ):
            with pytest.raises(ValueError, match="ambient|multiple"):
                with install_spawned_worker_window_binding(
                    serialized=serialized,
                    worker_operation_id=str(owner["operation_id"]),
                ):
                    pytest.fail("nested binding reached dispatch")


def test_stale_owner_and_worker_entry_invalid_binding_fail_before_provider(tmp_path: Path) -> None:
    with _owned(tmp_path, "worker-invalid") as (owner, _journal):
        serialized = _serialized(owner)
        invalid = deepcopy(serialized)
        invalid["payload_sha256"] = "0" * 64
        result_path = tmp_path / "worker-invalid.result.json"
        identity = {
            "worker_id": "worker-invalid",
            "run_id": "run-invalid",
            "stage": "screen_understanding",
            "operation_id": owner["operation_id"],
            "task_kind": "vision_observe_screen",
            "model_request_id": "model-invalid",
            "payload_sha256": "1" * 64,
        }
        process = multiprocessing.get_context("spawn").Process(
            target=_run_learning_stage_worker_entry,
            args=(
                str(result_path),
                "vision_observe_screen",
                {"_benchmark_v2_window_binding": invalid},
                "model-invalid",
                identity,
                None,
                None,
            ),
        )
        try:
            process.start()
            _join_or_kill(process)
            envelope = json.loads(result_path.read_text(encoding="utf-8"))
            assert envelope["status"] == "failed"
            assert "payload SHA" in envelope["error"]["details"]
            assert "benchmark_v2_window_binding_adopted_receipt" not in envelope
            assert "normal_clear_receipt" not in envelope
        finally:
            if process.is_alive():
                process.terminate()
                process.join(10)

    stale_dir = tmp_path / "stale"
    stale_dir.mkdir()
    with _owned(stale_dir, "closed") as (stale_owner, stale_journal):
        stale_serialized = _serialized(stale_owner)
        _assert_window_cleanup(
            close_owned_window(journal_path=stale_journal, reason="make_stale")
        )
    with pytest.raises(ValueError, match="missing|stale|journal"):
        with install_spawned_worker_window_binding(
            serialized=stale_serialized,
            worker_operation_id=str(stale_owner["operation_id"]),
        ):
            pytest.fail("stale binding reached dispatch")


def test_spawn_entry_rejects_present_null_reserved_key_instead_of_ignoring_it(
    tmp_path: Path,
) -> None:
    result_path = tmp_path / "null-reserved.result.json"
    identity = {
        "worker_id": "worker-null-reserved",
        "run_id": "run-null-reserved",
        "stage": "precise_calibration",
        "operation_id": "operation-null-reserved",
        "task_kind": "vision_locate_target",
        "model_request_id": "model-null-reserved",
        "payload_sha256": "4" * 64,
    }
    process = multiprocessing.get_context("spawn").Process(
        target=_run_learning_stage_worker_entry,
        args=(
            str(result_path),
            "vision_locate_target",
            {"_benchmark_v2_window_binding": None},
            "model-null-reserved",
            identity,
            None,
            None,
        ),
    )
    try:
        process.start()
        _join_or_kill(process)
        envelope = json.loads(result_path.read_text(encoding="utf-8"))
        assert envelope["status"] == "failed"
        assert any(
            fragment in envelope["error"]["details"]
            for fragment in ("limited to vision_observe_screen", "sealed object")
        )
    finally:
        if process.is_alive():
            process.terminate()
            process.join(10)


def test_real_strong_kill_has_no_false_normal_receipt_and_cleanup_is_stable_zero(
    tmp_path: Path,
) -> None:
    journal = (tmp_path / "strong-kill.owner.json").resolve()
    image = tmp_path / "strong-kill.bmp"
    digest = _bmp(image)
    owner = None
    process = None
    worker_scope = None
    cleanup = None
    adopted_path = tmp_path / "strong-kill.adopted.json"
    normal_path = tmp_path / "strong-kill.normal.json"
    ready_path = tmp_path / "strong-kill.ready"
    serialized_path = tmp_path / "strong-kill.binding.json"
    worker_scope_name = (
        "Local\\AgentGuiHybrid-vista-"
        + hashlib.sha256(str(tmp_path).encode("utf-8")).hexdigest()
    )
    worker_cleanup = None
    process_identity = None
    members_before_kill = None
    try:
        owner = launch_owned_window(
            image_path=image,
            expected_sha256=digest,
            operation_id="operation-strong-kill",
            journal_path=journal,
        )
        serialized = _serialized(owner)
        serialized_path.write_bytes(canonical_json_bytes(serialized))
        worker_scope = WindowsProcessScope(worker_scope_name, create=True)
        env = dict(os.environ)
        root = str(Path(__file__).resolve().parents[1])
        env["PYTHONPATH"] = root + os.pathsep + env.get("PYTHONPATH", "")
        process = spawn_process_in_scope(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--strong-kill-worker",
                str(serialized_path),
                str(owner["operation_id"]),
                str(adopted_path),
                str(normal_path),
                str(ready_path),
            ],
            scope_name=worker_scope_name,
            cwd=root,
            env=env,
            creationflags=0x08000000,
        )
        process_identity = dict(process.process_identity)
        deadline = time.monotonic() + 20
        while not ready_path.exists() and process.poll() is None:
            if time.monotonic() >= deadline:
                raise TimeoutError("strong-kill worker did not install binding")
            time.sleep(0.02)
        assert ready_path.exists()
        assert adopted_path.exists()
        members_before_kill = worker_scope.pids()
        assert process_identity["pid"] in members_before_kill
        process.kill()
        assert process.wait(20) != 0
        process.close()
        process = None
        worker_cleanup = observe_process_scope_cleanup(
            worker_scope_name,
            terminate=True,
            stable_zero_observations=3,
        )
        assert worker_cleanup["cleanup_status"] == "verified"
        assert worker_cleanup["member_pids_after"] == []
        assert worker_cleanup["stable_zero_observations"] >= 3
        assert not normal_path.exists()
    finally:
        if process is not None:
            try:
                if process.poll() is None:
                    process.kill()
            finally:
                process.close()
        if worker_scope is not None:
            worker_scope.close()
        absent = observe_process_scope_cleanup(
            worker_scope_name,
            terminate=True,
            stable_zero_observations=3,
        )
        assert absent["cleanup_status"] == "verified"
        assert absent["scope_absent_after_owner_close"] is True
        if journal.exists():
            cleanup = close_owned_window(journal_path=journal, reason="strong_kill_reconcile")
            _assert_window_cleanup(cleanup)
    assert cleanup is not None
    assert process_identity is not None
    assert members_before_kill is not None
    assert process_identity["pid"] in members_before_kill
    assert worker_cleanup is not None
    assert all(
        identity["pid"] in members_before_kill
        for identity in worker_cleanup["observed_member_identities_before"]
    )
    assert cleanup["member_pids_after"] == []
    assert cleanup["enum_windows_exact_hwnd_absent"] is True


if __name__ == "__main__" and len(sys.argv) == 7 and sys.argv[1] == "--strong-kill-worker":
    _strong_kill_worker_cli(*sys.argv[2:])
