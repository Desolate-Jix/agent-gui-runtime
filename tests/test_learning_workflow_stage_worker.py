from __future__ import annotations

import json
import hashlib
from copy import deepcopy
import multiprocessing
import os
import subprocess
import sys
from threading import Event, Lock, Thread
import time
from pathlib import Path

import pytest

from app.learn.workflow_worker import (
    BENCHMARK_WORKER_CONTROLLER_DEFAULT_TIMEOUT_MS,
    BenchmarkWorkerSupervisionRoot,
    LearningStageWorkerError,
    LearningStageWorkerRegistry,
    compose_benchmark_worker_operation_anchor_v1,
    compose_benchmark_worker_supervision_v1,
    compose_test_benchmark_worker_supervision_root,
    execute_learning_stage_worker_task,
    hold_benchmark_worker_controller,
    validate_benchmark_worker_operation_anchor_v1,
    validate_benchmark_worker_supervision_v1,
)
from app.learn.workflow_store import LearningWorkflowRunStore


def _hybrid_lineage(
    *,
    run_id: str,
    task_kind: str,
    operation_id: str | None = None,
    stage: str = "screen_understanding",
) -> dict:
    operation = operation_id or f"operation-{run_id}"
    execution_id = hashlib.sha256(
        json.dumps(
            {
                "run_id": run_id,
                "workflow_revision": 7,
                "operation_id": operation,
                "stage": stage,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return {
        "run_id": run_id,
        "workflow_revision": 7,
        "operation_id": operation,
        "stage": stage,
        "stage_execution_id": execution_id,
    }


def _hybrid_supervisor(*, run_id: str, task_kind: str, lease_path: Path) -> dict:
    from app.learn.hybrid.windows_process_scope import process_scope_name

    lineage = _hybrid_lineage(run_id=run_id, task_kind=task_kind)
    provider = {
        "panel_learning_hybrid_omni_discovery": "omni",
        "panel_learning_hybrid_qwen_binding": "qwen",
        "panel_learning_calibration_sequence": "vista",
    }.get(task_kind, "vista")
    return {
        "contract_version": "hybrid_worker_supervisor_context_v1",
        "worker_id": f"worker-{run_id}",
        "provider_lease_path": str(lease_path),
        "lineage": lineage,
        "process_scope_name": process_scope_name(lineage, provider),
    }


def _hybrid_cleanup_inventory(
    provider: str,
    *,
    lineage: dict,
    predecessor_sha256: str,
    provider_result_sha256: str,
    termination_reason: str = "completed",
) -> dict:
    from app.learn.hybrid.windows_process_scope import process_scope_name

    process_identity = {
        "pid": 4100 + len(provider),
        "create_time_ns": 100_000_000_000,
    }
    if provider == "omni":
        provider_identity = {
            "provider_invocation_id": "invocation/controlled-omni",
            "provider_receipt_ref": {
                "id": "receipt/controlled-omni",
                "content_sha256": "a" * 64,
            },
            "process_identity": process_identity,
            "process_scope_name": process_scope_name(lineage, provider),
        }
    elif provider == "qwen":
        provider_identity = {
            "lease_id": "controlled-qwen-lease",
            "incarnation_id": "qwen-incarnation",
            "profile_id": "qwen-profile",
            "server_process_identity": process_identity,
            "process_scope_name": process_scope_name(lineage, provider),
        }
    else:
        provider_identity = {
            "incarnation_id": "vista-incarnation",
            "profile_id": "vista-profile",
            "process_identities": [process_identity],
            "process_scope_name": process_scope_name(lineage, provider),
        }
    return {
        "contract_version": "hybrid_provider_process_inventory_v2",
        "provider": provider,
        "observer_contract": f"hybrid_{provider}_cleanup_observer_v1",
        "release_status": "verified",
        "termination_reason": termination_reason,
        "lineage": lineage,
        "provider_lease_identity": provider_identity,
        "predecessor_sha256": predecessor_sha256,
        "provider_result_sha256": provider_result_sha256,
        "provider_processes_after": [],
        "helper_processes_after": [],
        "orphan_descendant_pids": [],
        "active_listeners_after": [],
        "lease_files_after": [],
        "source_cleanup_evidence": {"status": "verified"},
    }


def _hybrid_cleanup_receipt(
    provider: str,
    *,
    lineage: dict,
    predecessor: dict,
    provider_result: dict,
) -> dict:
    from app.learn.hybrid.gpu_lifecycle import release_hybrid_provider
    from app.learn.recognition.uei.canonical import content_sha256

    inventory = _hybrid_cleanup_inventory(
        provider,
        lineage=lineage,
        predecessor_sha256=content_sha256(predecessor),
        provider_result_sha256=content_sha256(provider_result),
    )
    return release_hybrid_provider(provider, process_inventory=lambda _: inventory)


@pytest.fixture(autouse=True)
def _deny_real_model_server_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_GUI_TEST_DENY_REAL_MODEL_WRAPPER", "1")
    monkeypatch.setattr(
        "app.core.model_server.start_model_server",
        lambda profile: pytest.fail(
            f"real model server start is forbidden in Task 4 tests: {profile.get('profile_id')}"
        ),
    )



def _spawned_managed_omni_test_entry(target, args, control: dict[str, str]) -> None:
    from app.learn.hybrid import omni_discovery
    from app.learn.recognition.uei.omniparser_shadow_adapter import (
        OmniParserShadowAdapter,
        ProcessResourceLeaseManager,
        TrustedOmniParserConfiguration,
    )
    from app.learn.workflow_tasks import hybrid_omni

    configuration = TrustedOmniParserConfiguration(
        interpreter=Path(control["interpreter"]),
        worker_script=Path(control["worker_script"]),
        code_path=Path(control["code_path"]),
        weights_path=Path(control["weights_path"]),
        cache_path=Path(control["cache_path"]),
        minimum_free_gpu_gib=0,
    )
    original_terminate_tree = OmniParserShadowAdapter._terminate_tree

    def blocked_terminate_tree(process) -> None:
        original_terminate_tree(process)
        Path(control["cleanup_entered"]).write_text("entered", encoding="utf-8")
        deadline = time.monotonic() + 15
        release = Path(control["cleanup_release"])
        while not release.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        if not release.exists():
            raise RuntimeError("controlled cleanup release timed out")

    OmniParserShadowAdapter._terminate_tree = staticmethod(blocked_terminate_tree)
    omni_discovery.OmniParserShadowAdapter = lambda: OmniParserShadowAdapter(
        configuration=configuration,
        resource_lease_manager=ProcessResourceLeaseManager(
            root=Path(control["lease_root"])
        ),
        gpu_free_gib=lambda: 99.0,
    )
    hybrid_omni._PROJECT_ROOT = Path(control["project_root"])
    target(*args)


def _pid_is_active(pid: int) -> bool:
    if os.name == "nt":
        from app.learn.recognition.uei.omniparser_shadow_adapter import (
            _windows_pid_is_active,
        )

        return _windows_pid_is_active(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True

class _FakeProcess:
    def __init__(self, *, target: object, args: tuple[object, ...], name: str) -> None:
        self.target = target
        self.args = args
        self.name = name
        self.pid = 4321
        self.started = False
        self.alive = False
        self.terminated = False
        self.killed = False
        self.exitcode: int | None = None

    def start(self) -> None:
        self.started = True
        self.alive = True

    def is_alive(self) -> bool:
        return self.alive

    def terminate(self) -> None:
        self.terminated = True
        self.alive = False
        self.exitcode = -15

    def kill(self) -> None:
        self.killed = True
        self.alive = False
        self.exitcode = -9

    def join(self, timeout: float | None = None) -> None:
        del timeout


class _CooperativeFakeProcess(_FakeProcess):
    def start(self) -> None:
        super().start()

        def run_after_cancellation() -> None:
            while not self.args[5].is_set():
                time.sleep(0.001)
            self.target(*self.args)
            self.alive = False
            self.exitcode = 0

        self._thread = Thread(target=run_after_cancellation, daemon=True)
        self._thread.start()

    def join(self, timeout: float | None = None) -> None:
        self._thread.join(timeout=timeout)


def _fake_process_factory(*, target: object, args: tuple[object, ...], name: str) -> _FakeProcess:
    return _FakeProcess(target=target, args=args, name=name)


def _cooperative_fake_process_factory(
    *, target: object, args: tuple[object, ...], name: str
) -> _CooperativeFakeProcess:
    return _CooperativeFakeProcess(target=target, args=args, name=name)


def _sleeping_process_entry() -> None:
    time.sleep(30)


def _sleeping_process_factory(
    *,
    target: object,
    args: tuple[object, ...],
    name: str,
) -> multiprocessing.Process:
    del target, args
    return multiprocessing.get_context("spawn").Process(
        target=_sleeping_process_entry,
        name=name,
    )


def _finish_fake_worker(
    registry: LearningStageWorkerRegistry,
    started: dict[str, object],
    *,
    response: dict[str, object] | None = None,
) -> dict[str, object]:
    record = registry._records[str(started["worker_id"])]
    process = record["process"]
    process.alive = False
    process.exitcode = 0
    Path(record["result_path"]).write_text(
        json.dumps(
            {
                "contract_version": "learning_stage_worker_result_v2",
                "worker_id": started["worker_id"],
                "run_id": record["run_id"],
                "stage": record["stage"],
                "operation_id": record["operation_id"],
                "task_kind": record["task_kind"],
                "model_request_id": record["model_request_id"],
                "payload_sha256": record["payload_sha256"],
                "status": "completed",
                "response": response or {"success": True},
            }
        ),
        encoding="utf-8",
    )
    return registry.status(
        worker_id=str(started["worker_id"]),
        run_id=str(record["run_id"]),
        operation_id=str(record["operation_id"]),
    )


def _write_completed_result_for_identity_inspection(
    registry: LearningStageWorkerRegistry,
    started: dict[str, object],
    *,
    response: object = None,
    overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    record = registry._records[str(started["worker_id"])]
    process = record["process"]
    process.alive = False
    process.exitcode = 0
    envelope: dict[str, object] = {
        "contract_version": "learning_stage_worker_result_v2",
        "worker_id": started["worker_id"],
        "run_id": record["run_id"],
        "stage": record["stage"],
        "operation_id": record["operation_id"],
        "task_kind": record["task_kind"],
        "model_request_id": record["model_request_id"],
        "payload_sha256": record["payload_sha256"],
        "status": "completed",
        "response": (
            response
            if response is not None
            else {"success": True, "data": {"value": 1}}
        ),
        "normal_binding_evidence_ref": {"content_sha256": "a" * 64},
        "provider_cleanup_evidence_ref": None,
    }
    if overrides:
        envelope.update(overrides)
    Path(record["result_path"]).write_text(
        json.dumps(envelope, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return envelope


def _identity_inspection_registry(
    root: Path,
    *,
    suffix: str,
) -> tuple[LearningStageWorkerRegistry, dict[str, object]]:
    registry = LearningStageWorkerRegistry(
        result_root=root,
        process_factory=_fake_process_factory,
    )
    started = registry.start(
        run_id=f"run-inspect-{suffix}",
        stage="fusion",
        operation_id=f"operation-inspect-{suffix}",
        task_kind="panel_learning_recognition_trial",
        payload={"image_path": f"{suffix}.png"},
    )
    return registry, started


def _benchmark_handler_payload_source(
    handler_payload: dict[str, object] | None = None,
) -> dict[str, object]:
    from app.learn.recognition.uei.canonical import seal_immutable

    corpus_ref = seal_immutable({
        "contract_version": "benchmark_v2_provider_corpus_file_ref_v1",
        "relative_path": "provider-corpus.v2.json",
        "file_sha256": "1" * 64,
        "source_parent_ref": {"content_sha256": "2" * 64},
    })
    payload = handler_payload or {"capture_live": False}
    payload_sha256 = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return seal_immutable({
        "contract_version": "benchmark_v2_incumbent_handler_payload_source_v1",
        "provider_corpus_file_ref": corpus_ref,
        "provider_case_ref": {
            "case_id": "case-provider-safe",
            "case_content_sha256": "3" * 64,
        },
        "projection_contract_version": (
            "benchmark_v2_observe_screen_payload_projection_v1"
        ),
        "projection_rules_content_sha256": "4" * 64,
        "window_binding_ref": {"id": "binding", "content_sha256": "5" * 64},
        "capture_ref": {"id": "capture", "content_sha256": "6" * 64},
        "handler_payload_sha256": payload_sha256,
        "predecessor_content_sha256": corpus_ref["content_sha256"],
    })


def _benchmark_registry_fixture(
    tmp_path: Path,
) -> tuple[
    LearningStageWorkerRegistry,
    BenchmarkWorkerSupervisionRoot,
    LearningWorkflowRunStore,
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    store = LearningWorkflowRunStore()
    root = compose_test_benchmark_worker_supervision_root(
        journal_root=tmp_path,
        test_capability=object(),
        workflow_store=store,
        test_store_capability=object(),
    )
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
        benchmark_supervision_root=root,
    )
    source = _benchmark_handler_payload_source()
    reservation = registry.prepare_benchmark_worker_identity(
        run_id="run-benchmark-worker",
        stage="screen_understanding",
        operation_id="operation-benchmark-worker",
        workflow_revision=7,
        task_kind="vision_observe_screen",
        handler_payload_source=source,
        supervision_root=root,
    )
    anchor = compose_benchmark_worker_operation_anchor_v1(
        supervision_root=root,
        reservation=reservation,
        handler_payload_source=source,
        window_binding_ref=source["window_binding_ref"],
        capture_ref=source["capture_ref"],
        predecessor_content_sha256=None,
    )
    return registry, root, store, source, reservation, anchor


def _anchored_benchmark_provider_fixture(
    tmp_path: Path,
) -> tuple[
    LearningStageWorkerRegistry,
    BenchmarkWorkerSupervisionRoot,
    dict[str, object],
    dict[str, object],
]:
    registry, root, _store, _source, reservation, anchor = (
        _benchmark_registry_fixture(tmp_path)
    )
    confirmation = registry.confirm_prepared_benchmark_worker_anchor(
        reservation_ref={"content_sha256": reservation["content_sha256"]},
        expected_operation_anchor=anchor,
        supervision_root=root,
    )
    anchored = registry.inspect_prepared_benchmark_worker_identity(
        run_id=reservation["run_id"],
        stage=reservation["stage"],
        operation_id=reservation["operation_id"],
        supervision_root=root,
    )
    from app.learn.recognition.uei.canonical import seal_immutable

    runtime_owner = seal_immutable(
        {
            "contract_version": "benchmark_provider_runtime_owner_v1",
            "authority_kind": anchored["authority_kind"],
            "run_id": anchored["run_id"],
            "stage": anchored["stage"],
            "operation_id": anchored["operation_id"],
            "worker_id": anchored["worker_id"],
            "model_request_id": anchored["model_request_id"],
            "reservation_ref": deepcopy(confirmation["anchored_reservation_ref"]),
            "payload_sha256": anchored["payload_sha256"],
        }
    )
    return registry, root, anchored, runtime_owner


def _install_benchmark_provider_abort_primitive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    request_id: str,
) -> Path:
    from app.core import model_server
    from app.learn.hybrid.windows_process_scope import process_scope_name
    from app.learn.recognition.uei.canonical import seal_immutable

    lineage = {
        "run_id": "run-benchmark-provider-abort",
        "workflow_revision": 7,
        "operation_id": f"operation-{request_id}",
        "stage": "screen_understanding",
        "stage_execution_id": f"execution-{request_id}",
    }
    scope_name = process_scope_name(lineage, "qwen")
    runtime_path = tmp_path / f"{request_id}-qwen-runtime.json"
    profile = {
        "profile_id": f"profile-{request_id}",
        "endpoint": "http://127.0.0.1:54990/v1/chat/completions",
        "pid_file": str(tmp_path / f"{request_id}.pid"),
    }
    model_server._write_hybrid_qwen_runtime(
        runtime_path,
        seal_immutable(
            {
                "contract_version": "hybrid_qwen_acquisition_intent_v1",
                "state": "starting",
                "worker_id": f"worker-{request_id}",
                "model_request_id": request_id,
                "provider": "qwen",
                "lineage": lineage,
                "process_scope_name": scope_name,
                "profile": profile,
                "profile_sha256": model_server.content_sha256(
                    model_server._public_profile(profile)
                ),
                "listener_port": 54990,
                "pid_file": profile["pid_file"],
                "aborted_tombstone_sha256": None,
            }
        ),
    )
    monkeypatch.setenv("AGENT_GUI_HYBRID_PROVIDER_RUNTIME_PATH", str(runtime_path))
    monkeypatch.setenv("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", scope_name)
    monkeypatch.setenv(
        "AGENT_GUI_HYBRID_LINEAGE_JSON",
        json.dumps(lineage, sort_keys=True, separators=(",", ":")),
    )
    return runtime_path


def _cancel_anchored_benchmark_without_launch(
    registry: LearningStageWorkerRegistry,
    root: BenchmarkWorkerSupervisionRoot,
    anchored: dict[str, object],
) -> dict[str, object]:
    source = anchored["handler_payload_source"]
    original = {
        **anchored,
        "reservation_state": "reserved",
        "abort_observation_ref": None,
        "predecessor_content_sha256": source["content_sha256"],
        "content_sha256": anchored["predecessor_content_sha256"],
    }
    anchor = compose_benchmark_worker_operation_anchor_v1(
        supervision_root=root,
        reservation=original,
        handler_payload_source=source,
        window_binding_ref=source["window_binding_ref"],
        capture_ref=source["capture_ref"],
        predecessor_content_sha256=None,
    )
    registry.observe_benchmark_worker_cleanup(
        worker_id=anchored["worker_id"],
        run_id=anchored["run_id"],
        stage=anchored["stage"],
        operation_id=anchored["operation_id"],
        terminate=True,
        expected_operation_anchor=anchor,
        supervision_root=root,
    )
    return anchor


def _read_benchmark_artifact_by_ref(
    root: Path,
    ref: dict[str, object],
) -> dict[str, object]:
    from app.learn.recognition.uei.canonical import content_sha256

    expected = ref["content_sha256"]
    matches: list[dict[str, object]] = []
    for path in root.glob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(value, dict) and value.get("content_sha256") == expected:
            assert content_sha256(value) == value["content_sha256"]
            matches.append(value)
    assert len(matches) == 1
    return matches[0]


def _benchmark_parent_death_helper(
    root_path: str, ready_queue, cut: str = "gate_released"
) -> None:
    """测试拥有的 outer parent；真实被终止以验证 creator Job 关闭。"""
    try:
        root_dir = Path(root_path)
        root = compose_test_benchmark_worker_supervision_root(
            journal_root=root_dir, test_capability=object(),
            workflow_store=LearningWorkflowRunStore(),
            test_store_capability=object(),
        )
        registry = LearningStageWorkerRegistry(
            result_root=root_dir, benchmark_supervision_root=root,
        )
        source = _benchmark_handler_payload_source()
        reservation = registry.prepare_benchmark_worker_identity(
            run_id="run-parent-death", stage="screen_understanding",
            operation_id="operation-parent-death", workflow_revision=1,
            task_kind="vision_observe_screen", handler_payload_source=source,
            supervision_root=root,
        )
        anchor = compose_benchmark_worker_operation_anchor_v1(
            supervision_root=root, reservation=reservation,
            handler_payload_source=source,
            window_binding_ref=source["window_binding_ref"],
            capture_ref=source["capture_ref"], predecessor_content_sha256=None,
        )
        confirmation = registry.confirm_prepared_benchmark_worker_anchor(
            reservation_ref={"content_sha256": reservation["content_sha256"]},
            expected_operation_anchor=anchor, supervision_root=root,
        )
        if cut == "pre_assignment":
            from app.learn.hybrid import windows_process_scope
            real_assign = windows_process_scope.assign_exact_process_identity_to_scope

            def pause_before_assignment(**kwargs):
                ready_queue.put({
                    "cut_ready": True, "anchor": anchor,
                    "worker_id": reservation["worker_id"],
                })
                time.sleep(60)
                return real_assign(**kwargs)

            windows_process_scope.assign_exact_process_identity_to_scope = (
                pause_before_assignment
            )
        if cut == "assignment_proven":
            import win32event
            real_set_event = win32event.SetEvent

            def pause_before_gate_release(handle):
                ready_queue.put({
                    "cut_ready": True,
                    "started": {"worker_id": reservation["worker_id"]},
                    "anchor": anchor,
                })
                time.sleep(60)
                return real_set_event(handle)

            win32event.SetEvent = pause_before_gate_release
        started = registry.launch_prepared_benchmark_worker(
            reservation_ref=confirmation["anchored_reservation_ref"],
            expected_operation_anchor=anchor,
            authoritative_payload={"capture_live": False},
            supervision_root=root,
        )
        if cut == "result_write":
            deadline = time.monotonic() + 20
            result_path = root_dir / f"{started['worker_id']}.result.json"
            while time.monotonic() < deadline and not result_path.exists():
                time.sleep(0.02)
            ready_queue.put({"cut_ready": result_path.exists(), "started": started, "anchor": anchor})
            time.sleep(60)
        receipt_cut = cut.startswith("receipt_")
        if cut in {"before_intent", "after_intent", "after_job_close"} or receipt_cut:
            from app.learn import workflow_worker as worker_module
            from app.learn.hybrid.windows_process_scope import WindowsProcessScope
            real_write = worker_module._write_json_atomic
            real_close = WindowsProcessScope.close

            if cut == "before_intent":
                suffix = ".benchmark-cleanup-intent.json"

                def pause_write(path, payload):
                    if str(path).endswith(suffix):
                        ready_queue.put({"cut_ready": True, "started": started, "anchor": anchor})
                        time.sleep(60)
                    return real_write(path, payload)

                worker_module._write_json_atomic = pause_write
            elif receipt_cut:
                target_stage = cut.removeprefix("receipt_")

                def pause_receipt(stage, path):
                    if stage == target_stage:
                        ready_queue.put({"cut_ready": True, "started": started, "anchor": anchor})
                        time.sleep(60)

                worker_module._benchmark_cleanup_fault_hook = pause_receipt
            else:
                def pause_close(scope):
                    intent_exists = bool(list(root_dir.glob("*.benchmark-cleanup-intent.json")))
                    if intent_exists:
                        if cut == "after_job_close":
                            real_close(scope)
                        ready_queue.put({"cut_ready": True, "started": started, "anchor": anchor})
                        time.sleep(60)
                    return real_close(scope)

                WindowsProcessScope.close = pause_close
            registry.observe_benchmark_worker_cleanup(
                worker_id=started["worker_id"], run_id="run-parent-death",
                stage="screen_understanding", operation_id="operation-parent-death",
                terminate=True, expected_operation_anchor=anchor,
                supervision_root=root,
            )
        ready_queue.put({"started": started, "anchor": anchor})
        time.sleep(60)
    except BaseException as error:
        ready_queue.put({"error": f"{type(error).__name__}: {error}"})


def _benchmark_controller_owner_helper(root_path: str, ready_queue) -> None:
    root = compose_test_benchmark_worker_supervision_root(
        journal_root=Path(root_path), test_capability=object(),
        workflow_store=LearningWorkflowRunStore(), test_store_capability=object(),
    )
    with hold_benchmark_worker_controller(
        supervision_root=root, run_id="run-controller-process",
        stage="screen_understanding", operation_id="operation-controller-process",
    ):
        ready_queue.put({"owned": True})
        time.sleep(60)


def _benchmark_inspection_controller_owner_helper(
    root_path: str,
    run_id: str,
    stage: str,
    operation_id: str,
    ready_queue,
) -> None:
    root = compose_test_benchmark_worker_supervision_root(
        journal_root=Path(root_path), test_capability=object(),
        workflow_store=LearningWorkflowRunStore(), test_store_capability=object(),
    )
    with hold_benchmark_worker_controller(
        supervision_root=root,
        run_id=run_id,
        stage=stage,
        operation_id=operation_id,
    ):
        ready_queue.put({"owned": True})
        time.sleep(60)


def _benchmark_controller_contender_helper(
    root_path: str,
    ready_queue,
    run_id: str,
    operation_id: str,
) -> None:
    root = compose_test_benchmark_worker_supervision_root(
        journal_root=Path(root_path), test_capability=object(),
        workflow_store=LearningWorkflowRunStore(), test_store_capability=object(),
    )
    try:
        with hold_benchmark_worker_controller(
            supervision_root=root, run_id=run_id,
            stage="screen_understanding", operation_id=operation_id,
            timeout_ms=200,
        ):
            ready_queue.put({"entered": True})
    except BaseException as error:
        ready_queue.put({
            "entered": False,
            "error_type": type(error).__name__,
            "message": str(error),
        })


def _benchmark_controller_waiting_contender_helper(
    root_path: str,
    ready_queue,
    finished_event,
    run_id: str,
    operation_id: str,
) -> None:
    root = compose_test_benchmark_worker_supervision_root(
        journal_root=Path(root_path), test_capability=object(),
        workflow_store=LearningWorkflowRunStore(), test_store_capability=object(),
    )
    ready_queue.put({"waiting": True})
    try:
        with hold_benchmark_worker_controller(
            supervision_root=root, run_id=run_id,
            stage="screen_understanding", operation_id=operation_id,
            timeout_ms=5000,
        ):
            ready_queue.put({"entered": True})
    except BaseException as error:
        ready_queue.put({
            "entered": False,
            "error_type": type(error).__name__,
            "message": str(error),
        })
    finally:
        finished_event.set()


def _benchmark_raw_mutex_waiter_helper(
    controller_name: str,
    ready_queue,
) -> None:
    import win32api
    import win32event

    handle = win32event.CreateMutex(None, False, controller_name)
    try:
        outcome = win32event.WaitForSingleObject(handle, 1000)
        acquired = outcome in {
            win32event.WAIT_OBJECT_0,
            win32event.WAIT_ABANDONED,
        }
        ready_queue.put({"acquired": acquired, "outcome": int(outcome)})
        if acquired:
            win32event.ReleaseMutex(handle)
    finally:
        win32api.CloseHandle(handle)


def test_worker_registry_starts_and_reports_owned_process(tmp_path: Path) -> None:
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )

    started = registry.start(
        run_id="run-1",
        stage="numbered_map",
        operation_id="operation-1",
        task_kind="panel_learning_two_stage_understanding",
        payload={"app_name": "test"},
    )

    assert started["status"] == "running"
    assert started["backend_compute_owner"] == "backend_process_worker"
    assert started["worker_id"]
    assert started["pid"] == 4321
    status = registry.status(
        worker_id=started["worker_id"],
        run_id="run-1",
        operation_id="operation-1",
    )
    assert status["status"] == "running"


def test_worker_registry_persists_identity_journal_without_raw_payload(
    tmp_path: Path,
) -> None:
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )

    started = registry.start(
        run_id="run-journal",
        stage="numbered_map",
        operation_id="operation-journal",
        task_kind="panel_learning_two_stage_understanding",
        payload={"secret_text": "must-not-be-persisted"},
    )

    journal_path = Path(started["journal_path"])
    journal_text = journal_path.read_text(encoding="utf-8")
    journal = json.loads(journal_text)
    assert journal["contract_version"] == "learning_stage_worker_journal_v1"
    assert journal["worker_id"] == started["worker_id"]
    assert journal["operation_id"] == "operation-journal"
    assert journal["payload_sha256"]
    assert "must-not-be-persisted" not in journal_text
    assert "payload" not in journal


def test_worker_registry_recovers_completed_result_after_restart(
    tmp_path: Path,
) -> None:
    first_registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    started = first_registry.start(
        run_id="run-restart",
        stage="screen_understanding",
        operation_id="operation-restart",
        task_kind="vision_observe_screen",
        payload={"capture_live": False},
    )
    first_record = first_registry._records[started["worker_id"]]
    process = first_record["process"]
    process.target(*process.args)
    process.alive = False
    process.exitcode = 0

    restarted_registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    recovered = restarted_registry.attachment_by_operation(
        run_id="run-restart",
        stage="screen_understanding",
        operation_id="operation-restart",
    )

    assert recovered is not None
    assert recovered["worker_id"] == started["worker_id"]
    assert recovered["status"] == "completed"
    assert recovered["result_available"] is True
    assert recovered["runtime_attached"] is False
    assert recovered["result_adopted"] is False
    assert "response" not in recovered


def test_worker_registry_reuses_recovered_operation_only_for_same_payload(
    tmp_path: Path,
) -> None:
    first_registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    started = first_registry.start(
        run_id="run-idempotent",
        stage="fusion",
        operation_id="operation-idempotent",
        task_kind="panel_learning_recognition_trial",
        payload={"image_path": "same.png"},
    )
    restarted_registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )

    recovered = restarted_registry.start(
        run_id="run-idempotent",
        stage="fusion",
        operation_id="operation-idempotent",
        task_kind="panel_learning_recognition_trial",
        payload={"image_path": "same.png"},
    )

    assert recovered["worker_id"] == started["worker_id"]
    assert recovered["status"] == "detached_running"
    with pytest.raises(LearningStageWorkerError, match="payload identity"):
        restarted_registry.start(
            run_id="run-idempotent",
            stage="fusion",
            operation_id="operation-idempotent",
            task_kind="panel_learning_recognition_trial",
            payload={"image_path": "different.png"},
        )


def test_worker_registry_allows_sequential_task_kinds_in_one_operation(
    tmp_path: Path,
) -> None:
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    observe = registry.start(
        run_id="run-chain",
        stage="screen_understanding",
        operation_id="operation-chain",
        task_kind="vision_observe_screen",
        payload={"capture_live": False, "image_path": "capture.png"},
    )
    _finish_fake_worker(registry, observe)

    draft = registry.start(
        run_id="run-chain",
        stage="screen_understanding",
        operation_id="operation-chain",
        task_kind="panel_learning_recognition_trial",
        payload={"image_path": "capture.png"},
    )

    assert draft["worker_id"] != observe["worker_id"]
    assert draft["status"] == "running"
    attached = registry.attachment_by_operation(
        run_id="run-chain",
        stage="screen_understanding",
        operation_id="operation-chain",
    )
    assert attached is not None
    assert attached["worker_id"] == draft["worker_id"]


def test_worker_registry_allows_sequential_batches_but_not_concurrent_batches(
    tmp_path: Path,
) -> None:
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    first = registry.start(
        run_id="run-batches",
        stage="precise_calibration",
        operation_id="operation-batches",
        task_kind="vision_locate_target",
        payload={"goal": "batch-1"},
    )
    with pytest.raises(LearningStageWorkerError, match="active worker"):
        registry.start(
            run_id="run-batches",
            stage="precise_calibration",
            operation_id="operation-batches",
            task_kind="vision_locate_target",
            payload={"goal": "batch-2"},
        )
    _finish_fake_worker(registry, first)

    second = registry.start(
        run_id="run-batches",
        stage="precise_calibration",
        operation_id="operation-batches",
        task_kind="vision_locate_target",
        payload={"goal": "batch-2"},
    )

    assert second["worker_id"] != first["worker_id"]
    assert second["status"] == "running"


def test_worker_registry_reuses_identical_active_backend_continuation(
    tmp_path: Path,
) -> None:
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    first = registry.start(
        run_id="run-continuation",
        stage="screen_understanding",
        operation_id="operation-continuation",
        task_kind="panel_learning_recognition_trial",
        payload={"image_path": "capture.png"},
    )

    reused = registry.start(
        run_id="run-continuation",
        stage="screen_understanding",
        operation_id="operation-continuation",
        task_kind="panel_learning_recognition_trial",
        payload={"image_path": "capture.png"},
        reuse_active_identical=True,
    )

    assert reused["worker_id"] == first["worker_id"]
    assert reused["status"] == "running"


def test_worker_registry_recovers_multiple_workers_for_same_operation(
    tmp_path: Path,
) -> None:
    first_registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    first = first_registry.start(
        run_id="run-recover-chain",
        stage="screen_understanding",
        operation_id="operation-recover-chain",
        task_kind="vision_observe_screen",
        payload={"capture_live": False},
    )
    _finish_fake_worker(first_registry, first)
    second = first_registry.start(
        run_id="run-recover-chain",
        stage="screen_understanding",
        operation_id="operation-recover-chain",
        task_kind="panel_learning_recognition_trial",
        payload={"image_path": "capture.png"},
    )

    restarted_registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    attached = restarted_registry.attachment_by_operation(
        run_id="run-recover-chain",
        stage="screen_understanding",
        operation_id="operation-recover-chain",
    )

    assert attached is not None
    assert attached["worker_id"] == second["worker_id"]
    assert attached["status"] == "detached_running"


def test_worker_registry_rejects_mismatched_result_identity(
    tmp_path: Path,
) -> None:
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    started = registry.start(
        run_id="run-integrity",
        stage="numbered_map",
        operation_id="operation-integrity",
        task_kind="panel_learning_two_stage_understanding",
        payload={},
    )
    record = registry._records[started["worker_id"]]
    process = record["process"]
    process.alive = False
    process.exitcode = 0
    Path(record["result_path"]).write_text(
        json.dumps(
            {
                "contract_version": "learning_stage_worker_result_v2",
                "worker_id": started["worker_id"],
                "run_id": "run-integrity",
                "stage": "numbered_map",
                "operation_id": "wrong-operation",
                "task_kind": "panel_learning_two_stage_understanding",
                "model_request_id": started["model_request_id"],
                "payload_sha256": record["payload_sha256"],
                "status": "completed",
                "response": {"success": True},
            }
        ),
        encoding="utf-8",
    )

    status = registry.status(
        worker_id=started["worker_id"],
        run_id="run-integrity",
        operation_id="operation-integrity",
    )

    assert status["status"] == "failed"
    assert status["error"]["type"] == "WorkerResultIdentityMismatch"


def test_worker_registry_rejects_unknown_task_and_duplicate_operation(tmp_path: Path) -> None:
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )

    with pytest.raises(LearningStageWorkerError, match="task_kind"):
        registry.start(
            run_id="run-1",
            stage="numbered_map",
            operation_id="operation-1",
            task_kind="arbitrary_python",
            payload={},
        )

    registry.start(
        run_id="run-1",
        stage="numbered_map",
        operation_id="operation-1",
        task_kind="panel_learning_two_stage_understanding",
        payload={},
    )
    with pytest.raises(LearningStageWorkerError, match="already has an active worker"):
        registry.start(
            run_id="run-1",
            stage="numbered_map",
            operation_id="operation-1",
            task_kind="panel_learning_two_stage_understanding",
            payload={},
        )


def test_worker_dispatches_backend_calibration_sequence(monkeypatch) -> None:
    events: list[object] = []

    def run_learning_calibration_sequence(payload):
        events.append(("task", payload))
        return {
            "success": True,
            "data": {
                "contract_version": "learning_calibration_sequence_result_v1",
            },
        }

    def profile_for_stage(stage, profile_id):
        events.append(("profile", stage, profile_id))
        return {
            "profile_id": profile_id,
            "provider_mode": "local_grounding",
        }

    def build_model_resource_preflight(profile):
        events.append(("preflight", profile["profile_id"]))
        return {
            "resource_mode": "normal",
            "model_launch_allowed": True,
        }

    def ensure_model_server(**kwargs):
        events.append(("ensure", kwargs))
        return {
            "before": {"status": "unreachable"},
            "after": {"status": "running"},
        }

    monkeypatch.setattr(
        "app.learn.calibration_sequence.run_learning_calibration_sequence",
        run_learning_calibration_sequence,
    )
    monkeypatch.setattr(
        "app.core.model_server.profile_for_stage",
        profile_for_stage,
    )
    monkeypatch.setattr(
        "app.core.gpu_resources.build_model_resource_preflight",
        build_model_resource_preflight,
    )
    monkeypatch.setattr(
        "app.core.model_server.ensure_model_server",
        ensure_model_server,
    )

    response = execute_learning_stage_worker_task(
        "panel_learning_calibration_sequence",
        {
            "contract_version": "learning_calibration_sequence_request_v1",
            "profile_id": "vista-test",
            "locate_payload": {"provider_mode": "local_grounding"},
        },
    )

    assert response["success"] is True
    assert events == [
        ("profile", "locate", "vista-test"),
        ("preflight", "vista-test"),
        (
            "ensure",
            {
                "stage": "locate",
                "profile_id": "vista-test",
                "wait_until_ready": True,
                "wait_seconds": 180.0,
            },
        ),
        (
            "task",
        {
            "contract_version": "learning_calibration_sequence_request_v1",
                "profile_id": "vista-test",
            "locate_payload": {"provider_mode": "local_grounding"},
            },
        ),
    ]


def test_worker_rejects_model_stage_when_resource_preflight_blocks(
    monkeypatch,
) -> None:
    task_called = False

    def run_learning_calibration_sequence(_payload):
        nonlocal task_called
        task_called = True
        return {"success": True}

    monkeypatch.setattr(
        "app.learn.calibration_sequence.run_learning_calibration_sequence",
        run_learning_calibration_sequence,
    )
    monkeypatch.setattr(
        "app.core.model_server.profile_for_stage",
        lambda _stage, _profile_id: {
            "profile_id": "vista-test",
            "provider_mode": "local_grounding",
        },
    )
    monkeypatch.setattr(
        "app.core.gpu_resources.build_model_resource_preflight",
        lambda _profile: {
            "resource_mode": "critical",
            "model_launch_allowed": False,
            "reason_codes": ["gpu_memory_pressure"],
        },
    )

    with pytest.raises(
        LearningStageWorkerError,
        match="model resource preflight blocked",
    ):
        execute_learning_stage_worker_task(
            "panel_learning_calibration_sequence",
            {
                "contract_version": "learning_calibration_sequence_request_v1",
                "profile_id": "vista-test",
                "locate_payload": {"provider_mode": "local_grounding"},
            },
        )

    assert task_called is False


def test_worker_registry_cancel_terminates_process_and_preserves_audit(tmp_path: Path) -> None:
    cancellation_calls: list[dict[str, object]] = []

    def cancel_model_request(**kwargs):
        cancellation_calls.append(kwargs)
        return {
            "contract_version": "model_request_cancellation_v1",
            "status": "terminated",
            "model_service_compute_termination": "terminated",
        }

    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
        model_request_cancel=cancel_model_request,
    )
    started = registry.start(
        run_id="run-1",
        stage="precise_calibration",
        operation_id="operation-1",
        task_kind="vision_locate_target",
        payload={"goal": "locate"},
    )

    cancelled = registry.cancel_by_operation(
        run_id="run-1",
        stage="precise_calibration",
        operation_id="operation-1",
    )

    assert cancelled["status"] == "cancelled"
    assert cancelled["backend_compute_termination"] == "terminated"
    assert cancelled["model_service_compute_termination"] == "terminated"
    assert cancelled["model_request_cancellation"]["status"] == "terminated"
    assert cancelled["worker_id"] == started["worker_id"]
    assert started["model_request_id"]
    assert cancellation_calls == [
        {
            "request_id": started["model_request_id"],
            "task_kind": "vision_locate_target",
            "payload": {"goal": "locate"},
        }
    ]
    process = registry._records[started["worker_id"]]["process"]
    assert process.terminated is True
    assert process.is_alive() is False
    assert process.args[3] == started["model_request_id"]


def test_benchmark_worker_prepare_and_pre_anchor_inspection_are_byte_stable(
    tmp_path: Path,
) -> None:
    registry, root, store, source, reservation, anchor = _benchmark_registry_fixture(
        tmp_path
    )
    del store, source, anchor

    assert set(reservation) == {
        "contract_version",
        "authority_kind",
        "run_id",
        "stage",
        "operation_id",
        "workflow_revision",
        "task_kind",
        "payload_sha256",
        "handler_payload_source",
        "handler_payload_source_ref",
        "worker_id",
        "model_request_id",
        "execution_nonce",
        "supervision_inputs_ref",
        "reservation_state",
        "abort_observation_ref",
        "predecessor_content_sha256",
        "content_sha256",
    }
    assert reservation["reservation_state"] == "reserved"
    assert registry._records == {}
    inspected = registry.inspect_prepared_benchmark_worker_identity(
        run_id=str(reservation["run_id"]),
        stage=str(reservation["stage"]),
        operation_id=str(reservation["operation_id"]),
        supervision_root=root,
    )
    assert inspected == reservation

    reloaded = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
        benchmark_supervision_root=root,
    )
    assert reloaded.inspect_prepared_benchmark_worker_identity(
        run_id=str(reservation["run_id"]),
        stage=str(reservation["stage"]),
        operation_id=str(reservation["operation_id"]),
        supervision_root=root,
    ) == reservation
    assert not list(tmp_path.glob("*.result.json"))
    assert not list(tmp_path.glob("*.benchmark-owner.json"))
    assert not list(tmp_path.glob("*.benchmark-beacon.json"))


@pytest.mark.parametrize(
    "fault",
    [
        "source_digest", "corpus_digest", "case_shape", "projection_version",
        "binding_shape", "capture_shape", "handler_sha", "predecessor",
    ],
)
def test_benchmark_worker_handler_payload_source_rejects_each_closed_fault(
    tmp_path: Path,
    fault: str,
) -> None:
    from app.learn.recognition.uei.canonical import seal_immutable

    root = compose_test_benchmark_worker_supervision_root(
        journal_root=tmp_path, test_capability=object(),
        workflow_store=LearningWorkflowRunStore(), test_store_capability=object(),
    )
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path, benchmark_supervision_root=root,
    )
    source = _benchmark_handler_payload_source()
    broken = deepcopy(source)
    if fault == "source_digest":
        broken["content_sha256"] = "f" * 64
    elif fault == "corpus_digest":
        broken["provider_corpus_file_ref"]["content_sha256"] = "f" * 64
        raw = deepcopy(broken); raw.pop("content_sha256")
        broken = seal_immutable(raw)
    elif fault == "case_shape":
        broken["provider_case_ref"]["extra"] = True
        raw = deepcopy(broken); raw.pop("content_sha256")
        broken = seal_immutable(raw)
    elif fault == "projection_version":
        broken["projection_contract_version"] = "wrong"
        raw = deepcopy(broken); raw.pop("content_sha256")
        broken = seal_immutable(raw)
    elif fault in {"binding_shape", "capture_shape"}:
        key = "window_binding_ref" if fault == "binding_shape" else "capture_ref"
        broken[key]["extra"] = True
        raw = deepcopy(broken); raw.pop("content_sha256")
        broken = seal_immutable(raw)
    elif fault == "handler_sha":
        broken["handler_payload_sha256"] = "bad"
        raw = deepcopy(broken); raw.pop("content_sha256")
        broken = seal_immutable(raw)
    else:
        broken["predecessor_content_sha256"] = "f" * 64
        raw = deepcopy(broken); raw.pop("content_sha256")
        broken = seal_immutable(raw)
    with pytest.raises(LearningStageWorkerError, match="benchmark"):
        registry.prepare_benchmark_worker_identity(
            run_id="run-source-fault", stage="screen_understanding",
            operation_id="operation-source-fault", workflow_revision=1,
            task_kind="vision_observe_screen", handler_payload_source=broken,
            supervision_root=root,
        )
    assert not list(tmp_path.glob("*.benchmark-reservation.json"))


@pytest.mark.parametrize(
    "field_path",
    [
        ("provider_corpus_file_ref", "file_sha256"),
        ("provider_corpus_file_ref", "source_parent_ref", "content_sha256"),
        ("provider_case_ref", "case_content_sha256"),
        ("projection_rules_content_sha256",),
        ("window_binding_ref", "content_sha256"),
        ("capture_ref", "content_sha256"),
        ("handler_payload_sha256",),
    ],
)
def test_benchmark_worker_source_rejects_non_lowerhex_sha_fields(
    tmp_path: Path,
    field_path: tuple[str, ...],
) -> None:
    from app.learn.recognition.uei.canonical import seal_immutable

    root = compose_test_benchmark_worker_supervision_root(
        journal_root=tmp_path,
        test_capability=object(),
        workflow_store=LearningWorkflowRunStore(),
        test_store_capability=object(),
    )
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        benchmark_supervision_root=root,
    )
    broken = deepcopy(_benchmark_handler_payload_source())
    target = broken
    for key in field_path[:-1]:
        target = target[key]
    target[field_path[-1]] = "Z" * 64
    if field_path[:1] == ("provider_corpus_file_ref",):
        corpus = broken["provider_corpus_file_ref"]
        corpus_raw = deepcopy(corpus)
        corpus_raw.pop("content_sha256")
        broken["provider_corpus_file_ref"] = seal_immutable(corpus_raw)
        broken["predecessor_content_sha256"] = broken[
            "provider_corpus_file_ref"
        ]["content_sha256"]
    raw = deepcopy(broken)
    raw.pop("content_sha256")
    broken = seal_immutable(raw)

    with pytest.raises(LearningStageWorkerError, match="invalid|exact content ref"):
        registry.prepare_benchmark_worker_identity(
            run_id="run-invalid-sha",
            stage="screen_understanding",
            operation_id="operation-invalid-sha",
            workflow_revision=1,
            task_kind="vision_observe_screen",
            handler_payload_source=broken,
            supervision_root=root,
        )


def test_benchmark_worker_anchor_and_supervision_reject_substitution(
    tmp_path: Path,
) -> None:
    registry, root, store, source, reservation, anchor = _benchmark_registry_fixture(
        tmp_path
    )
    del registry, store, source
    import psutil

    assert validate_benchmark_worker_operation_anchor_v1(
        anchor,
        supervision_root=root,
        expected_reservation=reservation,
    ) == anchor
    supervisor = {
        "pid": os.getpid(),
        "create_time_ns": int(
            round(psutil.Process(os.getpid()).create_time() * 1_000_000_000)
        ),
    }
    supervision = compose_benchmark_worker_supervision_v1(
        supervision_root=root,
        reservation=reservation,
        expected_operation_anchor=anchor,
        supervisor_process_identity=supervisor,
        startup_gate_timeout_ms=15_000,
    )
    assert validate_benchmark_worker_supervision_v1(
        supervision,
        supervision_root=root,
        expected_operation_anchor=anchor,
    ) == supervision

    wrong = deepcopy(anchor)
    wrong["worker_id"] = "wrong-worker"
    with pytest.raises(LearningStageWorkerError):
        validate_benchmark_worker_operation_anchor_v1(
            wrong,
            supervision_root=root,
            expected_reservation=reservation,
        )
    wrong_root = BenchmarkWorkerSupervisionRoot(
        authority_kind=root.authority_kind,
        journal_root=root.journal_root,
        root_capability=object(),
        read_only_store_authority=root.read_only_store_authority,
        store_identity_sha256=root.store_identity_sha256,
    )
    with pytest.raises(LearningStageWorkerError, match="capability"):
        validate_benchmark_worker_operation_anchor_v1(
            anchor,
            supervision_root=wrong_root,
            expected_reservation=reservation,
        )


def test_benchmark_worker_test_root_rejects_production_and_cross_test_overlap(
    tmp_path: Path,
) -> None:
    from app.learn.workflow_store import learning_workflow_run_store

    first_root = tmp_path / "first"
    root = compose_test_benchmark_worker_supervision_root(
        journal_root=first_root,
        test_capability=object(),
        workflow_store=LearningWorkflowRunStore(),
        test_store_capability=object(),
    )
    token_path = first_root / ".benchmark-test-memory-store-token.json"
    token = json.loads(token_path.read_text(encoding="utf-8"))
    assert token["contract_version"] == (
        "benchmark_worker_test_memory_store_token_v1"
    )
    assert token["journal_root"] == str(first_root.resolve())
    assert len(token["memory_store_token"]) == 64
    assert root.store_identity_sha256 == root.read_only_store_authority.identity_sha256

    with pytest.raises(LearningStageWorkerError, match="cross-test"):
        compose_test_benchmark_worker_supervision_root(
            journal_root=first_root,
            test_capability=object(),
            workflow_store=LearningWorkflowRunStore(),
            test_store_capability=object(),
        )

    shared_capability = object()
    compose_test_benchmark_worker_supervision_root(
        journal_root=tmp_path / "second",
        test_capability=shared_capability,
        workflow_store=LearningWorkflowRunStore(),
        test_store_capability=object(),
    )
    with pytest.raises(LearningStageWorkerError, match="cross-test"):
        compose_test_benchmark_worker_supervision_root(
            journal_root=tmp_path / "third",
            test_capability=shared_capability,
            workflow_store=LearningWorkflowRunStore(),
            test_store_capability=object(),
        )

    production_root = (
        Path(__file__).resolve().parents[1] / "logs" / "workflow-workers"
    ).resolve()
    with pytest.raises(LearningStageWorkerError, match="production"):
        compose_test_benchmark_worker_supervision_root(
            journal_root=production_root,
            test_capability=object(),
            workflow_store=LearningWorkflowRunStore(),
            test_store_capability=object(),
        )
    with pytest.raises(LearningStageWorkerError, match="production"):
        compose_test_benchmark_worker_supervision_root(
            journal_root=tmp_path / "production-store-substitution",
            test_capability=object(),
            workflow_store=learning_workflow_run_store,
            test_store_capability=object(),
        )
    with pytest.raises(LearningStageWorkerError, match="production"):
        compose_test_benchmark_worker_supervision_root(
            journal_root=tmp_path / "production-state-overlap",
            test_capability=object(),
            workflow_store=LearningWorkflowRunStore(
                state_path=(
                    getattr(learning_workflow_run_store, "_state_path", None)
                    or (
                        Path(__file__).resolve().parents[1]
                        / "runtime_state"
                        / "learning-workflow-runs.json"
                    )
                )
            ),
            test_store_capability=object(),
        )


def test_benchmark_worker_controller_is_recursive_and_times_out_cross_thread(
    tmp_path: Path,
) -> None:
    registry, root, store, source, reservation, anchor = _benchmark_registry_fixture(
        tmp_path
    )
    del registry, store, source, reservation, anchor
    assert BENCHMARK_WORKER_CONTROLLER_DEFAULT_TIMEOUT_MS == 5000
    entered = Event()
    errors: list[BaseException] = []

    with hold_benchmark_worker_controller(
        supervision_root=root,
        run_id="run-controller",
        stage="screen_understanding",
        operation_id="operation-controller",
    ) as outer:
        with hold_benchmark_worker_controller(
            supervision_root=root,
            run_id="run-controller",
            stage="screen_understanding",
            operation_id="operation-controller",
        ) as inner:
            assert inner is outer
            assert outer["contract_version"] == (
                "benchmark_worker_controller_guard_v1"
            )
            assert outer["acquire_outcome"] == "acquired"
            assert outer["abandoned_revalidation_ref"] is None

        def contend() -> None:
            entered.set()
            try:
                with hold_benchmark_worker_controller(
                    supervision_root=root,
                    run_id="run-controller",
                    stage="screen_understanding",
                    operation_id="operation-controller",
                    timeout_ms=50,
                ):
                    pytest.fail("controller mutex unexpectedly admitted contender")
            except BaseException as error:
                errors.append(error)

        thread = Thread(target=contend)
        thread.start()
        assert entered.wait(timeout=1)
        thread.join(timeout=2)
    assert len(errors) == 1
    assert isinstance(errors[0], LearningStageWorkerError)
    assert str(errors[0]) == "benchmark worker controller mutex timed out"


def test_benchmark_worker_controller_cleanup_sidecar_preserves_primary_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import win32api
    import win32event

    root = compose_test_benchmark_worker_supervision_root(
        journal_root=tmp_path, test_capability=object(),
        workflow_store=LearningWorkflowRunStore(), test_store_capability=object(),
    )
    real_release = win32event.ReleaseMutex
    release_calls = 0

    def release_then_throw(handle) -> None:
        nonlocal release_calls
        release_calls += 1
        real_release(handle)
        raise OSError("injected-release-success-after-throw")

    monkeypatch.setattr(win32event, "ReleaseMutex", release_then_throw)
    with pytest.raises(LearningStageWorkerError, match="primary-controller-error") as captured:
        with hold_benchmark_worker_controller(
            supervision_root=root, run_id="run-controller-release",
            stage="screen_understanding", operation_id="operation-controller-release",
        ):
            raise RuntimeError("primary-controller-error")
    assert isinstance(captured.value.__cause__, RuntimeError)
    assert release_calls == 1
    first_sidecar = json.loads(
        next(tmp_path.glob("*.benchmark-controller-cleanup-failure.json"))
        .read_text(encoding="utf-8")
    )
    assert first_sidecar["primary_exception"]["message"] == "primary-controller-error"
    assert first_sidecar["release_result"]["status"] == "error"
    assert first_sidecar["close_result"]["status"] == "retained"

    state_path = next(tmp_path.glob("*.benchmark-controller-state.json"))
    assert json.loads(state_path.read_text(encoding="utf-8"))["state"] == (
        "recovery_required"
    )

    monkeypatch.setattr(win32event, "ReleaseMutex", real_release)
    with pytest.raises(LearningStageWorkerError, match="recovery required"):
        with hold_benchmark_worker_controller(
            supervision_root=root, run_id="run-controller-release",
            stage="screen_understanding", operation_id="operation-controller-release",
        ):
            pytest.fail("recovery call entered business body")
    with hold_benchmark_worker_controller(
        supervision_root=root, run_id="run-controller-release",
        stage="screen_understanding", operation_id="operation-controller-release",
    ):
        pass

    real_close = win32api.CloseHandle
    close_calls = 0

    def close_then_throw(handle) -> None:
        nonlocal close_calls
        close_calls += 1
        real_close(handle)
        raise OSError("injected-close-success-after-throw")

    monkeypatch.setattr(win32api, "CloseHandle", close_then_throw)
    with pytest.raises(
        LearningStageWorkerError,
        match="benchmark worker controller cleanup failed",
    ):
        with hold_benchmark_worker_controller(
            supervision_root=root, run_id="run-controller-close",
            stage="screen_understanding", operation_id="operation-controller-close",
        ):
            pass
    assert close_calls == 1
    sidecars = list(tmp_path.glob("*.benchmark-controller-cleanup-failure.json"))
    assert len(sidecars) == 2
    assert any(
        json.loads(path.read_text(encoding="utf-8"))["close_result"]["status"]
        == "error"
        for path in sidecars
    )
    monkeypatch.setattr(win32api, "CloseHandle", real_close)
    with pytest.raises(LearningStageWorkerError, match="recovery required"):
        with hold_benchmark_worker_controller(
            supervision_root=root, run_id="run-controller-close",
            stage="screen_understanding", operation_id="operation-controller-close",
        ):
            pytest.fail("close recovery call entered business body")
    with hold_benchmark_worker_controller(
        supervision_root=root, run_id="run-controller-close",
        stage="screen_understanding", operation_id="operation-controller-close",
    ):
        pass


@pytest.mark.parametrize("failure_mode", ["before", "api_false", "success_after"])
def test_benchmark_worker_controller_release_failure_retains_ownership_until_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    import win32event

    root = compose_test_benchmark_worker_supervision_root(
        journal_root=tmp_path, test_capability=object(),
        workflow_store=LearningWorkflowRunStore(), test_store_capability=object(),
    )
    real_release = win32event.ReleaseMutex
    injected = {"done": False}

    def faulty_release(handle):
        if injected["done"]:
            return real_release(handle)
        injected["done"] = True
        if failure_mode == "success_after":
            real_release(handle)
        if failure_mode == "api_false":
            return False
        raise OSError(f"injected-release-{failure_mode}")

    monkeypatch.setattr(win32event, "ReleaseMutex", faulty_release)
    with pytest.raises(
        LearningStageWorkerError,
        match="benchmark worker controller cleanup failed",
    ):
        with hold_benchmark_worker_controller(
            supervision_root=root, run_id=f"run-release-{failure_mode}",
            stage="screen_understanding",
            operation_id=f"operation-release-{failure_mode}",
        ):
            pass
    state_path = next(tmp_path.glob("*.benchmark-controller-state.json"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["state"] == "recovery_required"
    assert state["close_result"] == {"status": "retained"}

    monkeypatch.setattr(win32event, "ReleaseMutex", real_release)
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    contender = context.Process(
        target=_benchmark_controller_contender_helper,
        args=(
            str(tmp_path), queue, f"run-release-{failure_mode}",
            f"operation-release-{failure_mode}",
        ),
        name=f"test-owned-controller-contender-{failure_mode}",
    )
    contender.start()
    try:
        observed = queue.get(timeout=10)
        contender.join(timeout=10)
        assert contender.is_alive() is False
        assert observed["entered"] is False
        assert observed["message"] == "benchmark worker controller recovery required"
    finally:
        if contender.is_alive():
            contender.terminate(); contender.join(timeout=10)
        queue.close(); queue.join_thread()

    with pytest.raises(LearningStageWorkerError, match="recovery required"):
        with hold_benchmark_worker_controller(
            supervision_root=root, run_id=f"run-release-{failure_mode}",
            stage="screen_understanding",
            operation_id=f"operation-release-{failure_mode}",
        ):
            pytest.fail("recovery call entered business body")
    with hold_benchmark_worker_controller(
        supervision_root=root, run_id=f"run-release-{failure_mode}",
        stage="screen_understanding",
        operation_id=f"operation-release-{failure_mode}",
    ):
        pass


@pytest.mark.parametrize("failure_mode", ["before", "api_false", "success_after"])
def test_benchmark_worker_controller_close_failure_is_durable_until_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_mode: str,
) -> None:
    import win32api

    root = compose_test_benchmark_worker_supervision_root(
        journal_root=tmp_path, test_capability=object(),
        workflow_store=LearningWorkflowRunStore(), test_store_capability=object(),
    )
    real_close = win32api.CloseHandle
    injected = {"done": False}

    def faulty_close(handle):
        if injected["done"]:
            return real_close(handle)
        injected["done"] = True
        if failure_mode == "success_after":
            real_close(handle)
        if failure_mode == "api_false":
            return False
        raise OSError(f"injected-close-{failure_mode}")

    monkeypatch.setattr(win32api, "CloseHandle", faulty_close)
    with pytest.raises(
        LearningStageWorkerError,
        match="benchmark worker controller cleanup failed",
    ):
        with hold_benchmark_worker_controller(
            supervision_root=root, run_id=f"run-close-{failure_mode}",
            stage="screen_understanding",
            operation_id=f"operation-close-{failure_mode}",
        ):
            pass
    state = json.loads(
        next(tmp_path.glob("*.benchmark-controller-state.json"))
        .read_text(encoding="utf-8")
    )
    assert state["state"] == "recovery_required"
    assert state["release_result"] == {"status": "released"}
    assert state["close_result"]["status"] == "error"

    monkeypatch.setattr(win32api, "CloseHandle", real_close)
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    contender = context.Process(
        target=_benchmark_controller_contender_helper,
        args=(
            str(tmp_path), queue, f"run-close-{failure_mode}",
            f"operation-close-{failure_mode}",
        ),
        name=f"test-owned-controller-close-contender-{failure_mode}",
    )
    contender.start()
    try:
        observed = queue.get(timeout=10)
        contender.join(timeout=10)
        assert contender.is_alive() is False
        assert observed["entered"] is False
        assert observed["message"] == "benchmark worker controller recovery required"
    finally:
        if contender.is_alive():
            contender.terminate(); contender.join(timeout=10)
        queue.close(); queue.join_thread()

    with pytest.raises(LearningStageWorkerError, match="recovery required"):
        with hold_benchmark_worker_controller(
            supervision_root=root, run_id=f"run-close-{failure_mode}",
            stage="screen_understanding",
            operation_id=f"operation-close-{failure_mode}",
        ):
            pytest.fail("close recovery call entered business body")
    with hold_benchmark_worker_controller(
        supervision_root=root, run_id=f"run-close-{failure_mode}",
        stage="screen_understanding",
        operation_id=f"operation-close-{failure_mode}",
    ):
        pass


def test_benchmark_worker_controller_recursive_release_failure_keeps_exact_depth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import win32event

    root = compose_test_benchmark_worker_supervision_root(
        journal_root=tmp_path, test_capability=object(),
        workflow_store=LearningWorkflowRunStore(), test_store_capability=object(),
    )
    real_release = win32event.ReleaseMutex
    injected = {"done": False}

    def fail_once_before_release(handle):
        if not injected["done"]:
            injected["done"] = True
            raise OSError("injected-recursive-release-before-call")
        return real_release(handle)

    monkeypatch.setattr(win32event, "ReleaseMutex", fail_once_before_release)
    with pytest.raises(
        LearningStageWorkerError,
        match="benchmark worker controller cleanup failed",
    ):
        with hold_benchmark_worker_controller(
            supervision_root=root, run_id="run-recursive-release",
            stage="screen_understanding",
            operation_id="operation-recursive-release",
        ):
            with hold_benchmark_worker_controller(
                supervision_root=root, run_id="run-recursive-release",
                stage="screen_understanding",
                operation_id="operation-recursive-release",
            ):
                pass
    sidecar = json.loads(
        next(tmp_path.glob("*.benchmark-controller-cleanup-failure.json"))
        .read_text(encoding="utf-8")
    )
    assert sidecar["recursion_level"] == 2

    monkeypatch.setattr(win32event, "ReleaseMutex", real_release)
    with pytest.raises(LearningStageWorkerError, match="recovery required"):
        with hold_benchmark_worker_controller(
            supervision_root=root, run_id="run-recursive-release",
            stage="screen_understanding",
            operation_id="operation-recursive-release",
        ):
            pytest.fail("recursive recovery call entered business body")
    with hold_benchmark_worker_controller(
        supervision_root=root, run_id="run-recursive-release",
        stage="screen_understanding",
        operation_id="operation-recursive-release",
    ) as outer:
        with hold_benchmark_worker_controller(
            supervision_root=root, run_id="run-recursive-release",
            stage="screen_understanding",
            operation_id="operation-recursive-release",
        ) as inner:
            assert inner is outer


def test_benchmark_worker_controller_release_fence_blocks_already_waiting_contender(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import win32event

    root = compose_test_benchmark_worker_supervision_root(
        journal_root=tmp_path, test_capability=object(),
        workflow_store=LearningWorkflowRunStore(), test_store_capability=object(),
    )
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    finished = context.Event()
    real_release = win32event.ReleaseMutex
    contender = context.Process(
        target=_benchmark_controller_waiting_contender_helper,
        args=(
            str(tmp_path), queue, finished, "run-release-fence",
            "operation-release-fence",
        ),
        name="test-owned-controller-release-fence-contender",
    )

    def release_then_wait_and_throw(handle):
        result = real_release(handle)
        assert finished.wait(timeout=5)
        raise OSError("injected-release-success-after-waiter")

    with pytest.raises(
        LearningStageWorkerError,
        match="benchmark worker controller cleanup failed",
    ):
        with hold_benchmark_worker_controller(
            supervision_root=root, run_id="run-release-fence",
            stage="screen_understanding", operation_id="operation-release-fence",
        ):
            contender.start()
            assert queue.get(timeout=10) == {"waiting": True}
            monkeypatch.setattr(
                win32event, "ReleaseMutex", release_then_wait_and_throw,
            )
    monkeypatch.setattr(win32event, "ReleaseMutex", real_release)
    try:
        outcome = queue.get(timeout=10)
        contender.join(timeout=10)
        assert contender.is_alive() is False
        assert outcome["entered"] is False
        assert outcome["message"] == "benchmark worker controller recovery required"
    finally:
        monkeypatch.setattr(win32event, "ReleaseMutex", real_release)
        if contender.is_alive():
            contender.terminate(); contender.join(timeout=10)
        queue.close(); queue.join_thread()


def test_benchmark_worker_controller_real_process_timeout_then_abandoned_revalidation(
    tmp_path: Path,
) -> None:
    import win32api
    import win32con
    import win32event
    from app.learn.hybrid.windows_process_scope import (
        benchmark_worker_controller_mutex_name_v1,
    )

    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    owner = context.Process(
        target=_benchmark_controller_owner_helper,
        args=(str(tmp_path), queue),
        name="test-owned-benchmark-controller-owner",
    )
    owner.start()
    witness = None
    try:
        assert queue.get(timeout=10) == {"owned": True}
        root = compose_test_benchmark_worker_supervision_root(
            journal_root=tmp_path, test_capability=object(),
            workflow_store=LearningWorkflowRunStore(), test_store_capability=object(),
        )
        with pytest.raises(
            LearningStageWorkerError,
            match="benchmark worker controller mutex timed out",
        ):
            with hold_benchmark_worker_controller(
                supervision_root=root, run_id="run-controller-process",
                stage="screen_understanding", operation_id="operation-controller-process",
                timeout_ms=100,
            ):
                pytest.fail("live owner admitted a second controller")
        assert not list(tmp_path.glob("*.benchmark-reservation.json"))
        controller_name = benchmark_worker_controller_mutex_name_v1(
            authority_kind=root.authority_kind,
            run_id="run-controller-process",
            stage="screen_understanding",
            operation_id="operation-controller-process",
        )
        witness = win32event.OpenMutex(
            win32con.SYNCHRONIZE,
            False,
            controller_name,
        )
        owner.terminate(); owner.join(timeout=10)
        assert owner.is_alive() is False
        with hold_benchmark_worker_controller(
            supervision_root=root, run_id="run-controller-process",
            stage="screen_understanding", operation_id="operation-controller-process",
        ) as guard:
            assert guard["acquire_outcome"] == "abandoned_revalidated_clean"
            assert guard["abandoned_revalidation_ref"] is not None
            assert not list(tmp_path.glob("*.benchmark-owner.json"))
        revalidation = json.loads(
            (
                tmp_path
                / "operation-controller-process.benchmark-controller-abandoned-revalidation.json"
            ).read_text(encoding="utf-8")
        )
        assert revalidation["outcome"] == "verified_clean"
        assert revalidation["store_state"] == "absent"
        assert revalidation["reservation_ref"] is None
        assert revalidation["owner_ref"] is None
    finally:
        if witness is not None:
            win32api.CloseHandle(witness)
        if owner.is_alive():
            owner.terminate(); owner.join(timeout=10)
        queue.close(); queue.join_thread()


def test_benchmark_worker_controller_abandoned_dirty_revalidation_stays_durable(
    tmp_path: Path,
) -> None:
    import win32api
    import win32con
    import win32event
    from app.learn.hybrid.windows_process_scope import (
        benchmark_worker_controller_mutex_name_v1,
    )
    from app.learn.recognition.uei.canonical import seal_immutable

    root = compose_test_benchmark_worker_supervision_root(
        journal_root=tmp_path, test_capability=object(),
        workflow_store=LearningWorkflowRunStore(), test_store_capability=object(),
    )
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    owner = context.Process(
        target=_benchmark_controller_owner_helper,
        args=(str(tmp_path), queue),
        name="test-owned-controller-abandoned-dirty",
    )
    witness = None
    owner.start()
    try:
        assert queue.get(timeout=10) == {"owned": True}
        controller_name = benchmark_worker_controller_mutex_name_v1(
            authority_kind=root.authority_kind,
            run_id="run-controller-process",
            stage="screen_understanding",
            operation_id="operation-controller-process",
        )
        witness = win32event.OpenMutex(
            win32con.SYNCHRONIZE, False, controller_name,
        )
        dirty_reservation = seal_immutable({
            "run_id": "run-controller-process",
            "stage": "screen_understanding",
            "operation_id": "operation-controller-process",
        })
        (
            tmp_path
            / "operation-controller-process.benchmark-reservation.json"
        ).write_text(json.dumps(dirty_reservation), encoding="utf-8")
        owner.terminate(); owner.join(timeout=10)
        assert owner.is_alive() is False
        with pytest.raises(LearningStageWorkerError, match="recovery required"):
            with hold_benchmark_worker_controller(
                supervision_root=root, run_id="run-controller-process",
                stage="screen_understanding",
                operation_id="operation-controller-process",
            ):
                pytest.fail("dirty abandoned controller entered business body")
        revalidation = json.loads(
            (
                tmp_path
                / "operation-controller-process.benchmark-controller-abandoned-revalidation.json"
            ).read_text(encoding="utf-8")
        )
        assert revalidation["outcome"] == "recovery_required"
        assert revalidation["reservation_ref"] == {
            "content_sha256": dirty_reservation["content_sha256"]
        }
        state = json.loads(
            next(tmp_path.glob("*.benchmark-controller-state.json"))
            .read_text(encoding="utf-8")
        )
        assert state["state"] == "recovery_required"
        assert state["predecessor_content_sha256"] == revalidation[
            "content_sha256"
        ]
        raw_queue = context.Queue()
        raw_waiter = context.Process(
            target=_benchmark_raw_mutex_waiter_helper,
            args=(controller_name, raw_queue),
            name="test-owned-controller-abandoned-dirty-raw-waiter",
        )
        raw_waiter.start()
        try:
            raw_outcome = raw_queue.get(timeout=10)
            raw_waiter.join(timeout=10)
            assert raw_waiter.is_alive() is False
            assert raw_outcome["acquired"] is True
        finally:
            if raw_waiter.is_alive():
                raw_waiter.terminate(); raw_waiter.join(timeout=10)
            raw_queue.close(); raw_queue.join_thread()
        with pytest.raises(LearningStageWorkerError, match="recovery required"):
            with hold_benchmark_worker_controller(
                supervision_root=root, run_id="run-controller-process",
                stage="screen_understanding",
                operation_id="operation-controller-process",
            ):
                pytest.fail("durable recovery state admitted business body")
    finally:
        if witness is not None:
            win32api.CloseHandle(witness)
        if owner.is_alive():
            owner.terminate(); owner.join(timeout=10)
        queue.close(); queue.join_thread()


def test_benchmark_worker_confirm_requires_anchor_before_launch_and_payload_exact(
    tmp_path: Path,
) -> None:
    registry, root, store, source, reservation, anchor = _benchmark_registry_fixture(
        tmp_path
    )
    del store
    reservation_ref = {"content_sha256": reservation["content_sha256"]}
    with pytest.raises(LearningStageWorkerError, match="anchored"):
        registry.launch_prepared_benchmark_worker(
            reservation_ref=reservation_ref,
            expected_operation_anchor=anchor,
            authoritative_payload={"capture_live": False},
            supervision_root=root,
        )

    confirmation = registry.confirm_prepared_benchmark_worker_anchor(
        reservation_ref=reservation_ref,
        expected_operation_anchor=anchor,
        supervision_root=root,
    )
    replay = registry.confirm_prepared_benchmark_worker_anchor(
        reservation_ref=reservation_ref,
        expected_operation_anchor=anchor,
        supervision_root=root,
    )
    assert confirmation == replay
    assert confirmation["outcome"] == "verified_anchor_confirmed"
    assert confirmation["prior_state"] == "reserved"
    assert confirmation["new_state"] == "anchored"
    assert set(confirmation) == {
        "contract_version",
        "outcome",
        "reservation_ref",
        "anchored_reservation_ref",
        "operation_anchor_ref",
        "expected_supervision_ref",
        "handler_payload_source_ref",
        "run_id",
        "stage",
        "operation_id",
        "workflow_revision",
        "worker_id",
        "payload_sha256",
        "execution_nonce",
        "prior_state",
        "new_state",
        "predecessor_content_sha256",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    confirmation_path = (
        tmp_path
        / f"{reservation['operation_id']}.benchmark-anchor-confirmation.json"
    )
    confirmation_path.unlink()
    repaired = registry.confirm_prepared_benchmark_worker_anchor(
        reservation_ref=reservation_ref,
        expected_operation_anchor=anchor,
        supervision_root=root,
    )
    assert repaired == confirmation
    assert json.loads(confirmation_path.read_text(encoding="utf-8")) == confirmation
    confirmation_path.write_text(
        json.dumps({**confirmation, "worker_id": "tampered-worker"}),
        encoding="utf-8",
    )
    with pytest.raises(LearningStageWorkerError, match="confirmation"):
        registry.confirm_prepared_benchmark_worker_anchor(
            reservation_ref=reservation_ref,
            expected_operation_anchor=anchor,
            supervision_root=root,
        )
    confirmation_path.write_text(json.dumps(confirmation), encoding="utf-8")

    with pytest.raises(LearningStageWorkerError, match="payload"):
        registry.launch_prepared_benchmark_worker(
            reservation_ref={"content_sha256": confirmation["anchored_reservation_ref"]["content_sha256"]},
            expected_operation_anchor=anchor,
            authoritative_payload={"capture_live": True},
            supervision_root=root,
        )
    assert registry._records == {}
    assert not list(tmp_path.glob("*.benchmark-owner.json"))


def test_benchmark_worker_anchor_confirmation_crash_cut_is_idempotently_repaired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import workflow_worker as worker_module

    registry, root, store, source, reservation, anchor = _benchmark_registry_fixture(
        tmp_path
    )
    del store, source
    real_write = worker_module._write_json_atomic

    def fail_confirmation(path, payload):
        if str(path).endswith(".benchmark-anchor-confirmation.json"):
            raise OSError("injected-anchor-confirmation-cut")
        return real_write(path, payload)

    monkeypatch.setattr(worker_module, "_write_json_atomic", fail_confirmation)
    with pytest.raises(OSError, match="injected-anchor-confirmation-cut"):
        registry.confirm_prepared_benchmark_worker_anchor(
            reservation_ref={"content_sha256": reservation["content_sha256"]},
            expected_operation_anchor=anchor,
            supervision_root=root,
        )
    monkeypatch.setattr(worker_module, "_write_json_atomic", real_write)
    restarted = LearningStageWorkerRegistry(
        result_root=tmp_path,
        benchmark_supervision_root=root,
    )
    repaired = restarted.confirm_prepared_benchmark_worker_anchor(
        reservation_ref={"content_sha256": reservation["content_sha256"]},
        expected_operation_anchor=anchor,
        supervision_root=root,
    )
    assert repaired["outcome"] == "verified_anchor_confirmed"
    assert repaired["reservation_ref"] == {
        "content_sha256": reservation["content_sha256"]
    }


def test_benchmark_worker_preexisting_exact_job_is_collision_without_spawn(
    tmp_path: Path,
) -> None:
    from app.learn.hybrid.windows_process_scope import (
        WindowsProcessScope,
        benchmark_worker_scope_name_v1,
        spawn_process_in_scope,
    )

    registry, root, store, source, reservation, anchor = _benchmark_registry_fixture(
        tmp_path
    )
    del store, source
    confirmation = registry.confirm_prepared_benchmark_worker_anchor(
        reservation_ref={"content_sha256": reservation["content_sha256"]},
        expected_operation_anchor=anchor, supervision_root=root,
    )
    scope_name = benchmark_worker_scope_name_v1(
        authority_kind=root.authority_kind, run_id=reservation["run_id"],
        stage=reservation["stage"], operation_id=reservation["operation_id"],
        worker_id=reservation["worker_id"], payload_sha256=reservation["payload_sha256"],
        execution_nonce=reservation["execution_nonce"],
    )
    collision = WindowsProcessScope(scope_name, create=True)
    foreign = spawn_process_in_scope(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        scope_name=scope_name, cwd=tmp_path,
    )
    time.sleep(0.2)
    before_members = collision.pids()
    try:
        with pytest.raises(Exception, match="already exists"):
            registry.launch_prepared_benchmark_worker(
                reservation_ref=confirmation["anchored_reservation_ref"],
                expected_operation_anchor=anchor,
                authoritative_payload={"capture_live": False},
                supervision_root=root,
            )
        assert registry._records == {}
        assert foreign.pid in before_members
        assert collision.pids() == before_members
        assert foreign.poll() is None
    finally:
        collision.terminate()
        foreign.wait(timeout=10)
        foreign.close()
        collision.close()


def test_benchmark_worker_anchored_without_record_requires_closed_no_launch_observation(
    tmp_path: Path,
) -> None:
    registry, root, store, source, reservation, anchor = _benchmark_registry_fixture(
        tmp_path
    )
    del store, source
    confirmation = registry.confirm_prepared_benchmark_worker_anchor(
        reservation_ref={"content_sha256": reservation["content_sha256"]},
        expected_operation_anchor=anchor,
        supervision_root=root,
    )
    receipt = registry.observe_benchmark_worker_cleanup(
        worker_id=reservation["worker_id"],
        run_id=reservation["run_id"],
        stage=reservation["stage"],
        operation_id=reservation["operation_id"],
        terminate=True,
        expected_operation_anchor=anchor,
        supervision_root=root,
    )
    assert receipt["outcome"] == "verified_not_launched"
    assert registry.observe_benchmark_worker_cleanup(
        worker_id=reservation["worker_id"],
        run_id=reservation["run_id"],
        stage=reservation["stage"],
        operation_id=reservation["operation_id"],
        terminate=True,
        expected_operation_anchor=anchor,
        supervision_root=root,
    ) == receipt
    observation = _read_benchmark_artifact_by_ref(
        tmp_path, receipt["reservation_abort_ref"]
    )
    assert observation["contract_version"] == (
        "benchmark_worker_not_launched_observation_v1"
    )
    assert observation["reservation_ref"] == confirmation[
        "anchored_reservation_ref"
    ]
    predecessor = confirmation["anchored_reservation_ref"]["content_sha256"]
    for field in (
        "owner_absence_observation_ref",
        "process_event_job_beacon_absence_observation_ref",
        "result_absence_observation_ref",
        "provider_absence_observation_ref",
    ):
        artifact = _read_benchmark_artifact_by_ref(tmp_path, observation[field])
        assert artifact["predecessor_content_sha256"] == predecessor
        predecessor = artifact["content_sha256"]


def test_benchmark_worker_no_launch_receipt_cut_recovers_byte_identically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import workflow_worker as worker_module

    registry, root, store, source, reservation, anchor = _benchmark_registry_fixture(
        tmp_path
    )
    del store, source
    registry.confirm_prepared_benchmark_worker_anchor(
        reservation_ref={"content_sha256": reservation["content_sha256"]},
        expected_operation_anchor=anchor,
        supervision_root=root,
    )
    real_write = worker_module._write_benchmark_cleanup_receipt_atomic

    def fail_receipt(path, payload):
        raise OSError("injected-no-launch-receipt-cut")

    monkeypatch.setattr(
        worker_module, "_write_benchmark_cleanup_receipt_atomic", fail_receipt
    )
    kwargs = {
        "worker_id": reservation["worker_id"],
        "run_id": reservation["run_id"],
        "stage": reservation["stage"],
        "operation_id": reservation["operation_id"],
        "terminate": True,
        "expected_operation_anchor": anchor,
        "supervision_root": root,
    }
    with pytest.raises(OSError, match="injected-no-launch-receipt-cut"):
        registry.observe_benchmark_worker_cleanup(**kwargs)
    monkeypatch.setattr(
        worker_module, "_write_benchmark_cleanup_receipt_atomic", real_write
    )

    restarted = LearningStageWorkerRegistry(
        result_root=tmp_path, benchmark_supervision_root=root
    )
    first = restarted.observe_benchmark_worker_cleanup(**kwargs)
    second = restarted.observe_benchmark_worker_cleanup(**kwargs)
    assert first == second
    assert first["outcome"] == "verified_not_launched"
    receipt_path = tmp_path / f"{reservation['worker_id']}.benchmark-cleanup.json"
    receipt_path.unlink()
    provider_absence_path = (
        tmp_path
        / f"{reservation['worker_id']}.pre-anchor-provider-absence.json"
    )
    provider_absence = json.loads(
        provider_absence_path.read_text(encoding="utf-8")
    )
    provider_absence["checks"] = {"provider_owner_absent": False}
    provider_absence_path.write_text(
        json.dumps(provider_absence), encoding="utf-8"
    )
    damaged = LearningStageWorkerRegistry(
        result_root=tmp_path, benchmark_supervision_root=root
    )
    with pytest.raises(LearningStageWorkerError):
        damaged.observe_benchmark_worker_cleanup(**kwargs)
    assert not receipt_path.exists()


def test_benchmark_worker_real_gate_timeout_never_runs_handler_and_stays_recovery_required(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import windows_process_scope

    store = LearningWorkflowRunStore()
    root = compose_test_benchmark_worker_supervision_root(
        journal_root=tmp_path, test_capability=object(), workflow_store=store,
        test_store_capability=object(),
    )
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path, benchmark_supervision_root=root,
    )
    source = _benchmark_handler_payload_source()
    reservation = registry.prepare_benchmark_worker_identity(
        run_id="run-gate-timeout", stage="screen_understanding",
        operation_id="operation-gate-timeout", workflow_revision=1,
        task_kind="vision_observe_screen", handler_payload_source=source,
        supervision_root=root,
    )
    anchor = compose_benchmark_worker_operation_anchor_v1(
        supervision_root=root, reservation=reservation,
        handler_payload_source=source, window_binding_ref=source["window_binding_ref"],
        capture_ref=source["capture_ref"], predecessor_content_sha256=None,
    )
    confirmation = registry.confirm_prepared_benchmark_worker_anchor(
        reservation_ref={"content_sha256": reservation["content_sha256"]},
        expected_operation_anchor=anchor, supervision_root=root,
    )
    real_assign = windows_process_scope.assign_exact_process_identity_to_scope

    def delay_past_child_gate(**kwargs):
        time.sleep(15.2)
        return real_assign(**kwargs)

    monkeypatch.setattr(
        windows_process_scope,
        "assign_exact_process_identity_to_scope",
        delay_past_child_gate,
    )
    with pytest.raises(Exception):
        registry.launch_prepared_benchmark_worker(
            reservation_ref=confirmation["anchored_reservation_ref"],
            expected_operation_anchor=anchor,
            authoritative_payload={"capture_live": False},
            supervision_root=root,
        )
    monkeypatch.setattr(
        windows_process_scope,
        "assign_exact_process_identity_to_scope",
        real_assign,
    )
    restarted = LearningStageWorkerRegistry(
        result_root=tmp_path, benchmark_supervision_root=root,
    )
    cleanup = restarted.observe_benchmark_worker_cleanup(
        worker_id=reservation["worker_id"], run_id=reservation["run_id"],
        stage=reservation["stage"], operation_id=reservation["operation_id"],
        terminate=True, expected_operation_anchor=anchor,
        supervision_root=root,
    )
    assert cleanup["status"] == "recovery_required"
    assert not list(tmp_path.glob("*.result.json"))


def test_benchmark_worker_duplicate_beacon_rejects_without_foreign_identity_adoption(
    tmp_path: Path,
) -> None:
    import psutil
    from app.learn.recognition.uei.canonical import seal_immutable

    store = LearningWorkflowRunStore()
    root = compose_test_benchmark_worker_supervision_root(
        journal_root=tmp_path, test_capability=object(), workflow_store=store,
        test_store_capability=object(),
    )
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path, benchmark_supervision_root=root,
    )
    source = _benchmark_handler_payload_source()
    reservation = registry.prepare_benchmark_worker_identity(
        run_id="run-duplicate-beacon", stage="screen_understanding",
        operation_id="operation-duplicate-beacon", workflow_revision=1,
        task_kind="vision_observe_screen", handler_payload_source=source,
        supervision_root=root,
    )
    anchor = compose_benchmark_worker_operation_anchor_v1(
        supervision_root=root, reservation=reservation,
        handler_payload_source=source, window_binding_ref=source["window_binding_ref"],
        capture_ref=source["capture_ref"], predecessor_content_sha256=None,
    )
    confirmation = registry.confirm_prepared_benchmark_worker_anchor(
        reservation_ref={"content_sha256": reservation["content_sha256"]},
        expected_operation_anchor=anchor, supervision_root=root,
    )
    fake = seal_immutable({
        "contract_version": "benchmark_worker_identity_beacon_v1",
        "worker_id": reservation["worker_id"],
        "operation_anchor_ref": {"content_sha256": anchor["anchor_identity_sha256"]},
        "process_identity": {"pid": os.getpid(), "create_time_ns": 1},
        "predecessor_content_sha256": "f" * 64,
    })
    beacon_path = tmp_path / f"{reservation['worker_id']}.benchmark-beacon.json"
    beacon_path.write_text(json.dumps(fake), encoding="utf-8")
    with pytest.raises(LearningStageWorkerError, match="beacon identity mismatch"):
        registry.launch_prepared_benchmark_worker(
            reservation_ref=confirmation["anchored_reservation_ref"],
            expected_operation_anchor=anchor,
            authoritative_payload={"capture_live": False},
            supervision_root=root,
        )
    assert not beacon_path.exists()
    assert psutil.Process(os.getpid()).is_running()


def test_benchmark_worker_abort_same_operation_without_store_decision_is_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, root, store, source, reservation, anchor = _benchmark_registry_fixture(
        tmp_path
    )
    del source
    monkeypatch.setattr(
        store,
        "get",
        lambda run_id: {
            "run_id": run_id,
            "revision": 7,
            "evidence_refs": {
            "stage_execution": {
                "contract_version": "learning_workflow_stage_operation_v1",
                "operation_id": "operation-benchmark-worker",
                "stage": "screen_understanding",
                "owner": "backend_lease",
                "started_at": "2026-08-26T00:00:00+00:00",
                "lease_expires_at": "2026-08-26T00:10:00+00:00",
            },
        },
        },
    )

    with pytest.raises(LearningStageWorkerError, match="indeterminate"):
        registry.abort_prepared_benchmark_worker_before_anchor(
            reservation_ref={"content_sha256": reservation["content_sha256"]},
            run_id=str(reservation["run_id"]),
            stage=str(reservation["stage"]),
            operation_id=str(reservation["operation_id"]),
            workflow_revision=int(reservation["workflow_revision"]),
            expected_operation_anchor=anchor,
            reason="store_cas_lost",
            supervision_root=root,
        )
    assert registry.inspect_prepared_benchmark_worker_identity(
        run_id=str(reservation["run_id"]),
        stage=str(reservation["stage"]),
        operation_id=str(reservation["operation_id"]),
        supervision_root=root,
    ) == reservation


def test_benchmark_worker_pre_anchor_abort_uses_fresh_store_and_replays_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry, root, store, source, reservation, anchor = _benchmark_registry_fixture(
        tmp_path
    )
    del source
    calls: list[str] = []
    monkeypatch.setattr(
        store, "get",
        lambda run_id: calls.append(run_id) or {
            "run_id": run_id, "revision": 8, "current_stage": "screen_understanding",
            "terminal": False, "evidence_refs": {},
        },
    )
    kwargs = {
        "reservation_ref": {"content_sha256": reservation["content_sha256"]},
        "run_id": reservation["run_id"], "stage": reservation["stage"],
        "operation_id": reservation["operation_id"],
        "workflow_revision": reservation["workflow_revision"],
        "expected_operation_anchor": anchor, "reason": "store_cas_lost",
        "supervision_root": root,
    }
    first = registry.abort_prepared_benchmark_worker_before_anchor(**kwargs)
    second = registry.abort_prepared_benchmark_worker_before_anchor(**kwargs)
    assert first == second
    assert first["outcome"] == "verified_aborted_before_anchor"
    assert set(first) == {
        "contract_version",
        "outcome",
        "authority_kind",
        "reservation_ref",
        "store_anchor_decision_ref",
        "abort_observation_ref",
        "aborted_reservation_ref",
        "run_id",
        "stage",
        "operation_id",
        "workflow_revision",
        "worker_id",
        "model_request_id",
        "payload_sha256",
        "handler_payload_source_ref",
        "execution_nonce",
        "reason",
        "prior_state",
        "owner_absence_observation_ref",
        "process_event_job_beacon_absence_observation_ref",
        "result_absence_observation_ref",
        "provider_absence_observation_ref",
        "predecessor_content_sha256",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    predecessor = reservation["content_sha256"]
    for field in (
        "owner_absence_observation_ref",
        "process_event_job_beacon_absence_observation_ref",
        "result_absence_observation_ref",
        "provider_absence_observation_ref",
    ):
        artifact = _read_benchmark_artifact_by_ref(tmp_path, first[field])
        assert artifact["predecessor_content_sha256"] == predecessor
        predecessor = artifact["content_sha256"]
    decision = _read_benchmark_artifact_by_ref(
        tmp_path, first["store_anchor_decision_ref"]
    )
    assert set(decision) == {
        "contract_version",
        "authority_kind",
        "store_identity_sha256",
        "store_state_found",
        "current_state_content_sha256",
        "current_revision",
        "current_stage",
        "current_operation_id",
        "current_operation_outcome",
        "current_incumbent_document_ref",
        "current_operation_anchor_ref",
        "run_id",
        "stage",
        "operation_id",
        "workflow_revision",
        "reservation_ref",
        "expected_operation_anchor_ref",
        "reason",
        "outcome",
        "predicate",
        "content_sha256",
    }
    assert decision["reason"] == "store_cas_lost"
    assert decision["outcome"] == "matching_anchor_absent_store_cas_lost"
    assert calls == [reservation["run_id"], reservation["run_id"]]
    receipt_path = (
        tmp_path
        / f"{reservation['operation_id']}.benchmark-pre-anchor-abort-receipt.json"
    )
    receipt_path.write_text(
        json.dumps({**first, "worker_id": "tampered-worker"}),
        encoding="utf-8",
    )
    with pytest.raises(LearningStageWorkerError, match="abort receipt"):
        registry.abort_prepared_benchmark_worker_before_anchor(**kwargs)
    receipt_path.write_text(json.dumps(first), encoding="utf-8")
    inspected = registry.inspect_prepared_benchmark_worker_identity(
        run_id=reservation["run_id"], stage=reservation["stage"],
        operation_id=reservation["operation_id"], supervision_root=root,
    )
    assert inspected["reservation_state"] == "aborted_before_anchor"
    assert registry._records == {}


@pytest.mark.parametrize(
    "suffix",
    [
        ".benchmark-store-decision.json",
        ".benchmark-pre-anchor-abort.json",
        ".benchmark-reservation.json",
        ".benchmark-pre-anchor-abort-receipt.json",
    ],
)
def test_benchmark_worker_pre_anchor_abort_atomic_cut_recovers_from_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
) -> None:
    from app.learn import workflow_worker as worker_module

    registry, root, store, source, reservation, anchor = _benchmark_registry_fixture(
        tmp_path
    )
    del source
    monkeypatch.setattr(
        store, "get",
        lambda run_id: {
            "run_id": run_id, "revision": 8, "current_stage": "screen_understanding",
            "terminal": False, "evidence_refs": {},
        },
    )
    real_write = worker_module._write_json_atomic
    injected = {"done": False}

    def fail_stage(path, payload):
        if str(path).endswith(suffix) and not injected["done"]:
            injected["done"] = True
            raise OSError(f"injected-abort-cut:{suffix}")
        return real_write(path, payload)

    monkeypatch.setattr(worker_module, "_write_json_atomic", fail_stage)
    kwargs = {
        "reservation_ref": {"content_sha256": reservation["content_sha256"]},
        "run_id": reservation["run_id"], "stage": reservation["stage"],
        "operation_id": reservation["operation_id"],
        "workflow_revision": reservation["workflow_revision"],
        "expected_operation_anchor": anchor, "reason": "store_cas_lost",
        "supervision_root": root,
    }
    with pytest.raises(OSError, match="injected-abort-cut"):
        registry.abort_prepared_benchmark_worker_before_anchor(**kwargs)
    monkeypatch.setattr(worker_module, "_write_json_atomic", real_write)
    restarted = LearningStageWorkerRegistry(
        result_root=tmp_path, benchmark_supervision_root=root,
    )
    receipt = restarted.abort_prepared_benchmark_worker_before_anchor(**kwargs)
    assert receipt["outcome"] == "verified_aborted_before_anchor"
    assert restarted._records == {}


@pytest.mark.parametrize("damage", ["tampered", "missing", "stale_ref"])
def test_benchmark_worker_abort_missing_receipt_validates_observation_first(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
) -> None:
    registry, root, store, source, reservation, anchor = _benchmark_registry_fixture(
        tmp_path
    )
    del source
    monkeypatch.setattr(
        store,
        "get",
        lambda run_id: {
            "run_id": run_id,
            "revision": 8,
            "current_stage": "screen_understanding",
            "terminal": False,
            "evidence_refs": {},
        },
    )
    kwargs = {
        "reservation_ref": {"content_sha256": reservation["content_sha256"]},
        "run_id": reservation["run_id"],
        "stage": reservation["stage"],
        "operation_id": reservation["operation_id"],
        "workflow_revision": reservation["workflow_revision"],
        "expected_operation_anchor": anchor,
        "reason": "store_cas_lost",
        "supervision_root": root,
    }
    registry.abort_prepared_benchmark_worker_before_anchor(**kwargs)
    receipt_path = (
        tmp_path
        / f"{reservation['operation_id']}.benchmark-pre-anchor-abort-receipt.json"
    )
    receipt_path.unlink()
    observation_path = (
        tmp_path / f"{reservation['operation_id']}.benchmark-pre-anchor-abort.json"
    )
    if damage == "tampered":
        observation = json.loads(observation_path.read_text(encoding="utf-8"))
        observation["unsealed_forgery"] = True
        observation_path.write_text(json.dumps(observation), encoding="utf-8")
    elif damage == "missing":
        observation_path.unlink()
    else:
        from app.learn.recognition.uei.canonical import seal_immutable

        reservation_path = (
            tmp_path / f"{reservation['operation_id']}.benchmark-reservation.json"
        )
        aborted = json.loads(reservation_path.read_text(encoding="utf-8"))
        aborted_body = dict(aborted)
        aborted_body.pop("content_sha256")
        aborted_body["abort_observation_ref"] = {"content_sha256": "f" * 64}
        reservation_path.write_text(
            json.dumps(seal_immutable(aborted_body)), encoding="utf-8"
        )

    restarted = LearningStageWorkerRegistry(
        result_root=tmp_path, benchmark_supervision_root=root
    )
    with pytest.raises(LearningStageWorkerError):
        restarted.abort_prepared_benchmark_worker_before_anchor(**kwargs)
    assert not receipt_path.exists()


def test_benchmark_worker_pre_anchor_abort_rejects_matching_store_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.recognition.uei.canonical import seal_immutable

    registry, root, store, source, reservation, anchor = _benchmark_registry_fixture(
        tmp_path
    )
    del source
    incumbent = seal_immutable({
        "contract_version": "benchmark_v2_incumbent_operation_v1",
        "operation_anchor_ref": {"content_sha256": anchor["content_sha256"]},
    })
    monkeypatch.setattr(
        store, "get",
        lambda run_id: {
            "run_id": run_id, "revision": reservation["workflow_revision"],
            "current_stage": reservation["stage"], "terminal": False,
            "current_evidence_refs": {
                "stage_execution": {
                    "operation_id": reservation["operation_id"],
                    "benchmark_v2_incumbent": incumbent,
                }
            },
        },
    )
    with pytest.raises(LearningStageWorkerError, match="operation anchor already exists"):
        registry.abort_prepared_benchmark_worker_before_anchor(
            reservation_ref={"content_sha256": reservation["content_sha256"]},
            run_id=reservation["run_id"], stage=reservation["stage"],
            operation_id=reservation["operation_id"],
            workflow_revision=reservation["workflow_revision"],
            expected_operation_anchor=anchor, reason="store_cas_lost",
            supervision_root=root,
        )
    assert registry.inspect_prepared_benchmark_worker_identity(
        run_id=reservation["run_id"], stage=reservation["stage"],
        operation_id=reservation["operation_id"], supervision_root=root,
    ) == reservation


@pytest.mark.parametrize(
    ("reason", "store_fields", "expected_outcome"),
    [
        (
            "cancelled",
            {
                "revision": 7,
                "current_stage": "screen_understanding",
                "terminal": True,
                "current_evidence_refs": {
                    "stage_execution": {
                        "operation_id": "operation-benchmark-worker"
                    }
                },
            },
            "matching_anchor_absent_cancelled",
        ),
        (
            "stale",
            {
                "revision": 7,
                "current_stage": "numbered_map",
                "terminal": False,
                "current_evidence_refs": {
                    "stage_execution": {
                        "operation_id": "replacement-operation"
                    }
                },
            },
            "matching_anchor_absent_stale",
        ),
    ],
)
def test_benchmark_worker_pre_anchor_abort_reason_matches_store_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
    store_fields: dict[str, object],
    expected_outcome: str,
) -> None:
    registry, root, store, source, reservation, anchor = _benchmark_registry_fixture(
        tmp_path
    )
    del source
    monkeypatch.setattr(
        store,
        "get",
        lambda run_id: {"run_id": run_id, **deepcopy(store_fields)},
    )
    receipt = registry.abort_prepared_benchmark_worker_before_anchor(
        reservation_ref={"content_sha256": reservation["content_sha256"]},
        run_id=reservation["run_id"],
        stage=reservation["stage"],
        operation_id=reservation["operation_id"],
        workflow_revision=reservation["workflow_revision"],
        expected_operation_anchor=anchor,
        reason=reason,
        supervision_root=root,
    )
    decision = _read_benchmark_artifact_by_ref(
        tmp_path, receipt["store_anchor_decision_ref"]
    )
    assert decision["reason"] == reason
    assert decision["outcome"] == expected_outcome


def test_benchmark_worker_pre_anchor_abort_missing_run_is_closed_stale_decision(
    tmp_path: Path,
) -> None:
    registry, root, store, source, reservation, anchor = _benchmark_registry_fixture(
        tmp_path
    )
    del store, source
    receipt = registry.abort_prepared_benchmark_worker_before_anchor(
        reservation_ref={"content_sha256": reservation["content_sha256"]},
        run_id=reservation["run_id"],
        stage=reservation["stage"],
        operation_id=reservation["operation_id"],
        workflow_revision=reservation["workflow_revision"],
        expected_operation_anchor=anchor,
        reason="stale",
        supervision_root=root,
    )
    decision = _read_benchmark_artifact_by_ref(
        tmp_path, receipt["store_anchor_decision_ref"]
    )
    assert decision["store_state_found"] is False
    for field in (
        "current_state_content_sha256",
        "current_revision",
        "current_stage",
        "current_operation_id",
        "current_operation_outcome",
        "current_incumbent_document_ref",
        "current_operation_anchor_ref",
    ):
        assert decision[field] is None
    assert decision["outcome"] == "matching_anchor_absent_stale"


@pytest.mark.parametrize("existing_kind", ["owner_job", "startup_event", "provider_owner"])
def test_benchmark_worker_pre_anchor_abort_fresh_probes_exact_launch_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing_kind: str,
) -> None:
    import win32api
    import win32event
    from app.learn.hybrid.windows_process_scope import (
        WindowsProcessScope,
        benchmark_worker_scope_name_v1,
    )

    registry, root, store, source, reservation, anchor = _benchmark_registry_fixture(
        tmp_path
    )
    del source
    monkeypatch.setattr(
        store,
        "get",
        lambda run_id: {
            "run_id": run_id,
            "revision": 8,
            "current_stage": "screen_understanding",
            "terminal": False,
            "evidence_refs": {},
        },
    )
    scope_name = benchmark_worker_scope_name_v1(
        authority_kind=root.authority_kind,
        run_id=reservation["run_id"],
        stage=reservation["stage"],
        operation_id=reservation["operation_id"],
        worker_id=reservation["worker_id"],
        payload_sha256=reservation["payload_sha256"],
        execution_nonce=reservation["execution_nonce"],
    )
    event_name = (
        "Local\\AgentGuiBenchmarkWorkerGate-"
        + hashlib.sha256(
            json.dumps(
                {"scope_name": scope_name},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
    )
    scope = None
    event_handle = None
    provider_path = tmp_path / f"{reservation['worker_id']}.provider-owner.json"
    try:
        if existing_kind == "owner_job":
            scope = WindowsProcessScope(scope_name, create=True)
        elif existing_kind == "startup_event":
            event_handle = win32event.CreateEvent(None, True, False, event_name)
        else:
            provider_path.write_text("{}", encoding="utf-8")
        with pytest.raises(LearningStageWorkerError, match="launch artifacts|present"):
            registry.abort_prepared_benchmark_worker_before_anchor(
                reservation_ref={"content_sha256": reservation["content_sha256"]},
                run_id=reservation["run_id"],
                stage=reservation["stage"],
                operation_id=reservation["operation_id"],
                workflow_revision=reservation["workflow_revision"],
                expected_operation_anchor=anchor,
                reason="store_cas_lost",
                supervision_root=root,
            )
    finally:
        if event_handle is not None:
            win32api.CloseHandle(event_handle)
        if scope is not None:
            scope.close()
        provider_path.unlink(missing_ok=True)


def test_benchmark_worker_pre_anchor_abort_job_api_error_is_indeterminate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import windows_process_scope

    registry, root, store, source, reservation, anchor = _benchmark_registry_fixture(
        tmp_path
    )
    del source
    monkeypatch.setattr(
        store,
        "get",
        lambda run_id: {
            "run_id": run_id,
            "revision": 8,
            "current_stage": "screen_understanding",
            "terminal": False,
            "evidence_refs": {},
        },
    )

    class ProbeError(OSError):
        winerror = 5

    monkeypatch.setattr(
        windows_process_scope,
        "WindowsProcessScope",
        lambda *args, **kwargs: (_ for _ in ()).throw(ProbeError("denied")),
    )
    with pytest.raises(LearningStageWorkerError, match="indeterminate"):
        registry.abort_prepared_benchmark_worker_before_anchor(
            reservation_ref={"content_sha256": reservation["content_sha256"]},
            run_id=reservation["run_id"],
            stage=reservation["stage"],
            operation_id=reservation["operation_id"],
            workflow_revision=reservation["workflow_revision"],
            expected_operation_anchor=anchor,
            reason="store_cas_lost",
            supervision_root=root,
        )


def test_benchmark_worker_generic_start_rejects_private_markers(
    tmp_path: Path,
) -> None:
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    for marker in (
        "_benchmark_worker_supervision",
        "_benchmark_worker_bootstrap",
        "_benchmark_worker_handler_payload_source",
    ):
        with pytest.raises(LearningStageWorkerError, match="reserved"):
            registry.start(
                run_id=f"run-{marker}",
                stage="screen_understanding",
                operation_id=f"operation-{marker}",
                task_kind="vision_observe_screen",
                payload={marker: {}},
            )
    assert registry._records == {}


def test_benchmark_worker_real_gate_assigns_before_release_and_cleanup_is_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LearningWorkflowRunStore()
    root = compose_test_benchmark_worker_supervision_root(
        journal_root=tmp_path,
        test_capability=object(),
        workflow_store=store,
        test_store_capability=object(),
    )
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        benchmark_supervision_root=root,
    )
    source = _benchmark_handler_payload_source()
    reservation = registry.prepare_benchmark_worker_identity(
        run_id="run-real-gate", stage="screen_understanding",
        operation_id="operation-real-gate", workflow_revision=1,
        task_kind="vision_observe_screen", handler_payload_source=source,
        supervision_root=root,
    )
    anchor = compose_benchmark_worker_operation_anchor_v1(
        supervision_root=root, reservation=reservation,
        handler_payload_source=source,
        window_binding_ref=source["window_binding_ref"],
        capture_ref=source["capture_ref"], predecessor_content_sha256=None,
    )
    confirmation = registry.confirm_prepared_benchmark_worker_anchor(
        reservation_ref={"content_sha256": reservation["content_sha256"]},
        expected_operation_anchor=anchor, supervision_root=root,
    )
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        benchmark_supervision_root=root,
    )
    started = None
    try:
        started = registry.launch_prepared_benchmark_worker(
            reservation_ref=confirmation["anchored_reservation_ref"],
            expected_operation_anchor=anchor,
            authoritative_payload={"capture_live": False},
            supervision_root=root,
        )
        owner = json.loads(
            Path(registry._records[started["worker_id"]]["benchmark_owner_path"])
            .read_text(encoding="utf-8")
        )
        assert owner["phase"] == "gate_released"
        assert owner["assignment_observation_ref"] is not None
        assert owner["job_policy"] == {
            "kill_on_job_close": True,
            "breakaway_ok": False,
            "silent_breakaway_ok": False,
            "owner_handle_authority": "registry_parent",
        }
        launch_anchor_path = (
            tmp_path
            / f"{started['worker_id']}.benchmark-launch-identity-anchor.json"
        )
        launch_identity_anchor = json.loads(
            launch_anchor_path.read_text(encoding="utf-8")
        )
        launch_anchor_bytes = launch_anchor_path.read_bytes()
        assert launch_identity_anchor["contract_version"] == (
            "benchmark_worker_launch_identity_anchor_v1"
        )
        from app.learn import workflow_worker as worker_module

        with pytest.raises(
            LearningStageWorkerError,
            match="launch identity anchor already exists",
        ):
            worker_module._write_json_create_only(
                launch_anchor_path,
                launch_identity_anchor,
            )
        assert launch_anchor_path.read_bytes() == launch_anchor_bytes
        assignment_path = (
            tmp_path / f"{started['worker_id']}.benchmark-assignment.json"
        )
        launch_assignment = json.loads(
            assignment_path.read_text(encoding="utf-8")
        )
        assert launch_assignment["predecessor_content_sha256"] == (
            launch_identity_anchor["assignment_predecessor_content_sha256"]
        )
        assert launch_identity_anchor["assignment_observation_ref"] == {
            "content_sha256": launch_assignment["content_sha256"]
        }
    finally:
        if started is not None:
            from app.learn import workflow_worker as worker_module
            from app.learn.hybrid.windows_process_scope import WindowsProcessScope
            fault_counts: dict[tuple[str, str], int] = {}

            def staged_handle_fault(kind: str, stage: str) -> None:
                key = (kind, stage)
                if fault_counts.get(key, 0) == 0:
                    fault_counts[key] = 1
                    raise RuntimeError(f"injected-{kind}-{stage}")

            monkeypatch.setattr(
                worker_module, "_benchmark_handle_fault_hook", staged_handle_fault
            )
            for kind in ("worker_process", "startup_event", "beacon_file"):
                with pytest.raises(
                    RuntimeError, match=f"injected-{kind}-before_call"
                ):
                    registry.observe_benchmark_worker_cleanup(
                        worker_id=started["worker_id"], run_id="run-real-gate",
                        stage="screen_understanding", operation_id="operation-real-gate",
                        terminate=True, expected_operation_anchor=anchor,
                        supervision_root=root,
                    )
                record = registry._records[started["worker_id"]]
                if kind == "worker_process":
                    owned = record["process"]
                    real_api = owned.close
                    monkeypatch.setattr(
                        owned, "close",
                        lambda: (_ for _ in ()).throw(OSError("injected-worker-process-api-error")),
                    )
                elif kind == "startup_event":
                    import win32api
                    event_handle = record["benchmark_event_handle"]
                    real_api = win32api.CloseHandle

                    def fail_event(handle):
                        if int(handle) == int(event_handle):
                            raise OSError("injected-startup-event-api-error")
                        return real_api(handle)

                    monkeypatch.setattr(win32api, "CloseHandle", fail_event)
                else:
                    beacon_path = Path(record["benchmark_beacon_path"])
                    real_api = Path.unlink

                    def fail_beacon(path, *args, **kwargs):
                        if path == beacon_path:
                            raise OSError("injected-beacon-file-api-error")
                        return real_api(path, *args, **kwargs)

                    monkeypatch.setattr(Path, "unlink", fail_beacon)
                with pytest.raises(OSError, match=f"injected-{kind.replace('_', '-')}-api-error"):
                    registry.observe_benchmark_worker_cleanup(
                        worker_id=started["worker_id"], run_id="run-real-gate",
                        stage="screen_understanding", operation_id="operation-real-gate",
                        terminate=True, expected_operation_anchor=anchor,
                        supervision_root=root,
                    )
                record = registry._records[started["worker_id"]]
                error_suffix = {
                    "worker_process": "worker-process-close-error.json",
                    "startup_event": "startup-event-close-error.json",
                    "beacon_file": "beacon-file-close-error.json",
                }[kind]
                error_observation = json.loads(
                    (tmp_path / f"{started['worker_id']}.{error_suffix}")
                    .read_text(encoding="utf-8")
                )
                assert worker_module.content_sha256(error_observation) == (
                    error_observation["content_sha256"]
                )
                assert error_observation["handle_kind"] == kind
                assert error_observation["handle_identity"] == (
                    worker_module._benchmark_handle_identity(
                        handle_kind=kind,
                        launch_identity_anchor=launch_identity_anchor,
                        scope_name=owner["scope_name"],
                    )
                )
                assert error_observation["call_result"] is None
                assert error_observation["call_error"] == {
                    "error_type": "OSError",
                    "message": (
                        f"injected-{kind.replace('_', '-')}-api-error"
                    ),
                }
                assert error_observation["observed_at"]
                if kind == "worker_process":
                    expected_error_predecessor = record[
                        "benchmark_exit_observation_ref"
                    ]["content_sha256"]
                else:
                    predecessor_kind = {
                        "startup_event": "worker_process",
                        "beacon_file": "startup_event",
                    }[kind]
                    expected_error_predecessor = record[
                        "benchmark_handle_refs"
                    ][predecessor_kind]["content_sha256"]
                assert error_observation[
                    "predecessor_content_sha256"
                ] == expected_error_predecessor
                if kind == "worker_process":
                    monkeypatch.setattr(owned, "close", real_api)
                elif kind == "startup_event":
                    monkeypatch.setattr(win32api, "CloseHandle", real_api)
                else:
                    monkeypatch.setattr(Path, "unlink", real_api)
                with pytest.raises(
                    RuntimeError, match=f"injected-{kind}-after_success"
                ):
                    registry.observe_benchmark_worker_cleanup(
                        worker_id=started["worker_id"], run_id="run-real-gate",
                        stage="screen_understanding", operation_id="operation-real-gate",
                        terminate=True, expected_operation_anchor=anchor,
                        supervision_root=root,
                    )
            monkeypatch.setattr(
                worker_module,
                "_benchmark_handle_fault_hook",
                lambda handle_kind, stage: None,
            )
            owned_scope = registry._records[started["worker_id"]]["benchmark_scope"]
            real_pids = owned_scope.pids
            monkeypatch.setattr(owned_scope, "pids", lambda: [999999])
            with pytest.raises(
                LearningStageWorkerError,
                match="benchmark Job did not reach stable zero",
            ):
                registry.observe_benchmark_worker_cleanup(
                    worker_id=started["worker_id"], run_id="run-real-gate",
                    stage="screen_understanding", operation_id="operation-real-gate",
                    terminate=False, expected_operation_anchor=anchor,
                    supervision_root=root,
                )
            monkeypatch.setattr(owned_scope, "pids", real_pids)
            real_close = WindowsProcessScope.close
            owner_before = {"done": False}

            def owner_job_before(kind: str, stage: str) -> None:
                if kind == "owner_job" and stage == "before_call" and not owner_before["done"]:
                    owner_before["done"] = True
                    raise RuntimeError("injected-owner-job-before-call")

            monkeypatch.setattr(
                worker_module, "_benchmark_handle_fault_hook", owner_job_before
            )
            with pytest.raises(RuntimeError, match="injected-owner-job-before-call"):
                registry.observe_benchmark_worker_cleanup(
                    worker_id=started["worker_id"], run_id="run-real-gate",
                    stage="screen_understanding", operation_id="operation-real-gate",
                    terminate=True, expected_operation_anchor=anchor,
                    supervision_root=root,
                )
            monkeypatch.setattr(
                worker_module,
                "_benchmark_handle_fault_hook",
                lambda handle_kind, stage: None,
            )
            monkeypatch.setattr(
                WindowsProcessScope,
                "close",
                lambda scope: (_ for _ in ()).throw(
                    OSError("injected-owner-job-api-error")
                ),
            )
            with pytest.raises(OSError, match="injected-owner-job-api-error"):
                registry.observe_benchmark_worker_cleanup(
                    worker_id=started["worker_id"], run_id="run-real-gate",
                    stage="screen_understanding", operation_id="operation-real-gate",
                    terminate=True, expected_operation_anchor=anchor,
                    supervision_root=root,
                )
            owner_job_error = json.loads(
                (
                    tmp_path
                    / f"{started['worker_id']}.owner-job-close-error.json"
                ).read_text(encoding="utf-8")
            )
            assert worker_module.content_sha256(owner_job_error) == (
                owner_job_error["content_sha256"]
            )
            assert owner_job_error["handle_kind"] == "owner_job"
            assert owner_job_error["handle_identity"] == {
                "scope_name": owner["scope_name"]
            }
            assert owner_job_error["call_result"] is None
            assert owner_job_error["call_error"] == {
                "error_type": "OSError",
                "message": "injected-owner-job-api-error",
            }
            assert owner_job_error["observed_at"]
            pending_intent = json.loads(
                (
                    tmp_path
                    / f"{started['worker_id']}.benchmark-cleanup-intent.json"
                ).read_text(encoding="utf-8")
            )
            assert owner_job_error["predecessor_content_sha256"] == (
                pending_intent["content_sha256"]
            )
            monkeypatch.setattr(WindowsProcessScope, "close", real_close)
            injected = {"done": False}

            def owner_job_after(kind: str, stage: str) -> None:
                if (
                    kind == "owner_job"
                    and stage == "after_success"
                    and not injected["done"]
                ):
                    injected["done"] = True
                    raise RuntimeError("injected-job-close-success-after-throw")

            monkeypatch.setattr(
                worker_module, "_benchmark_handle_fault_hook", owner_job_after
            )
            with pytest.raises(
                RuntimeError, match="injected-job-close-success-after-throw"
            ):
                registry.observe_benchmark_worker_cleanup(
                    worker_id=started["worker_id"], run_id="run-real-gate",
                    stage="screen_understanding", operation_id="operation-real-gate",
                    terminate=True, expected_operation_anchor=anchor,
                    supervision_root=root,
                )
            receipt = registry.observe_benchmark_worker_cleanup(
                worker_id=started["worker_id"], run_id="run-real-gate",
                stage="screen_understanding", operation_id="operation-real-gate",
                terminate=True, expected_operation_anchor=anchor,
                supervision_root=root,
            )
            assert receipt["outcome"] == "verified_exact_worker_exited"
            intent = _read_benchmark_artifact_by_ref(
                tmp_path, receipt["finalization_intent_ref"]
            )
            assignment = _read_benchmark_artifact_by_ref(
                tmp_path, receipt["assignment_proven_ref"]
            )
            assert assignment["contract_version"] == (
                "benchmark_worker_scope_assignment_v1"
            )
            stable_zero = _read_benchmark_artifact_by_ref(
                tmp_path, intent["stable_zero_observation_ref"]
            )
            assert stable_zero["samples"] == [[], [], []]
            exit_observation = _read_benchmark_artifact_by_ref(
                tmp_path, intent["exit_observation_ref"]
            )
            assert exit_observation["contract_version"] == (
                "benchmark_worker_exit_join_observation_v1"
            )
            assert exit_observation["join_result"] == "joined"
            assert exit_observation["join_error"] is None
            predecessor = None
            for kind in ("worker_process", "startup_event", "beacon_file"):
                observation = _read_benchmark_artifact_by_ref(
                    tmp_path, receipt["exact_handle_observation_refs"][kind]
                )
                assert observation["handle_identity"]
                assert observation["call_result"] == "success"
                assert observation["call_error"] is None
                assert observation["observed_at"]
                if predecessor is None:
                    assert len(observation["predecessor_content_sha256"]) == 64
                else:
                    assert observation["predecessor_content_sha256"] == predecessor
                predecessor = observation["content_sha256"]
            job_absence = _read_benchmark_artifact_by_ref(
                tmp_path, receipt["job_absence_observation_ref"]
            )
            worker_absence = _read_benchmark_artifact_by_ref(
                tmp_path, receipt["worker_absence_observation_ref"]
            )
            assert job_absence["outcome"] == "absent"
            assert worker_absence["outcome"] == "absent"
            assert worker_absence["predecessor_content_sha256"] == (
                job_absence["content_sha256"]
            )
            receipt_path = (
                tmp_path / f"{started['worker_id']}.benchmark-cleanup.json"
            )
            receipt_path.write_text(
                json.dumps({**receipt, "outcome": "tampered"}),
                encoding="utf-8",
            )
            with pytest.raises(LearningStageWorkerError, match="receipt"):
                registry.observe_benchmark_worker_cleanup(
                    worker_id=started["worker_id"],
                    run_id="run-real-gate",
                    stage="screen_understanding",
                    operation_id="operation-real-gate",
                    terminate=True,
                    expected_operation_anchor=anchor,
                    supervision_root=root,
                )
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            from app.learn.recognition.uei.canonical import seal_immutable

            cleanup_kwargs = {
                "worker_id": started["worker_id"],
                "run_id": "run-real-gate",
                "stage": "screen_understanding",
                "operation_id": "operation-real-gate",
                "terminate": True,
                "expected_operation_anchor": anchor,
                "supervision_root": root,
            }
            exit_path = tmp_path / f"{started['worker_id']}.exit-join.json"
            original_exit_bytes = exit_path.read_bytes()
            for damage in ("missing", "corrupt", "rehashed"):
                if damage == "missing":
                    exit_path.unlink()
                elif damage == "corrupt":
                    exit_path.write_text("{", encoding="utf-8")
                else:
                    exit_body = dict(exit_observation)
                    exit_body.pop("content_sha256")
                    exit_body["exitcode"] = int(exit_body["exitcode"]) + 1
                    exit_path.write_text(
                        json.dumps(seal_immutable(exit_body)), encoding="utf-8"
                    )
                with pytest.raises(LearningStageWorkerError):
                    registry.observe_benchmark_worker_cleanup(**cleanup_kwargs)
                exit_path.write_bytes(original_exit_bytes)

            worker_handle_path = (
                tmp_path / f"{started['worker_id']}.worker-process-close.json"
            )
            worker_handle = json.loads(
                worker_handle_path.read_text(encoding="utf-8")
            )
            original_handle_bytes = worker_handle_path.read_bytes()
            for field, replacement_value in (
                ("handle_identity", {"process_identity": {"pid": 999999, "create_time_ns": 1}}),
                ("call_result", "forged_success"),
                ("predecessor_content_sha256", "f" * 64),
            ):
                handle_body = dict(worker_handle)
                handle_body.pop("content_sha256")
                handle_body[field] = replacement_value
                worker_handle_path.write_text(
                    json.dumps(seal_immutable(handle_body)), encoding="utf-8"
                )
                with pytest.raises(LearningStageWorkerError):
                    registry.observe_benchmark_worker_cleanup(**cleanup_kwargs)
                worker_handle_path.write_bytes(original_handle_bytes)

            owner_path = tmp_path / f"{started['worker_id']}.benchmark-owner.json"
            current_owner = json.loads(owner_path.read_text(encoding="utf-8"))
            original_owner_bytes = owner_path.read_bytes()
            for field, replacement_value in (
                (
                    "supervisor_process_identity",
                    {
                        "pid": int(
                            launch_identity_anchor[
                                "supervisor_process_identity"
                            ]["pid"]
                        ) + 100000,
                        "create_time_ns": int(
                            launch_identity_anchor[
                                "supervisor_process_identity"
                            ]["create_time_ns"]
                        ) + 256,
                    },
                ),
                ("beacon_ref", {"content_sha256": "e" * 64}),
            ):
                owner_body = dict(current_owner)
                owner_body.pop("content_sha256")
                owner_body[field] = replacement_value
                owner_path.write_text(
                    json.dumps(seal_immutable(owner_body)),
                    encoding="utf-8",
                )
                with pytest.raises(LearningStageWorkerError):
                    registry.observe_benchmark_worker_cleanup(**cleanup_kwargs)
                owner_path.write_bytes(original_owner_bytes)

            alternate_process = {
                "pid": int(launch_identity_anchor["process_identity"]["pid"]) + 100000,
                "create_time_ns": int(
                    launch_identity_anchor["process_identity"]["create_time_ns"]
                ) + 256,
            }
            alternate_supervisor = {
                "pid": int(
                    launch_identity_anchor["supervisor_process_identity"]["pid"]
                ) + 100000,
                "create_time_ns": int(
                    launch_identity_anchor["supervisor_process_identity"][
                        "create_time_ns"
                    ]
                ) + 256,
            }
            alternate_beacon_ref = {"content_sha256": "e" * 64}
            anchored = worker_module._benchmark_transitioned_reservation(
                reservation, "anchored"
            )
            launching = worker_module._benchmark_transitioned_reservation(
                anchored, "launching"
            )
            alternate_supervision = compose_benchmark_worker_supervision_v1(
                supervision_root=root,
                reservation=reservation,
                expected_operation_anchor=anchor,
                supervisor_process_identity=alternate_supervisor,
                startup_gate_timeout_ms=15_000,
            )
            alternate_acquiring = (
                LearningStageWorkerRegistry._benchmark_owner_journal(
                    current=anchored,
                    anchor=anchor,
                    supervision=alternate_supervision,
                    scope_name=current_owner["scope_name"],
                    supervisor_identity=alternate_supervisor,
                    phase="acquiring",
                    process_identity=None,
                    beacon_ref=None,
                    assignment_ref=None,
                    gate_state="closed",
                    predecessor=None,
                )
            )
            assignment_body = dict(assignment)
            assignment_body.pop("content_sha256")
            assignment_body["process_identity"] = alternate_process
            assignment_body["observed_member_identities"] = [alternate_process]
            assignment_body["predecessor_content_sha256"] = alternate_acquiring[
                "content_sha256"
            ]
            alternate_assignment = seal_immutable(assignment_body)
            assignment_path.write_text(
                json.dumps(alternate_assignment), encoding="utf-8"
            )
            alternate_assignment_ref = {
                "content_sha256": alternate_assignment["content_sha256"]
            }
            alternate_assigned_owner = (
                LearningStageWorkerRegistry._benchmark_owner_journal(
                    current=launching,
                    anchor=anchor,
                    supervision=alternate_supervision,
                    scope_name=current_owner["scope_name"],
                    supervisor_identity=alternate_supervisor,
                    phase="assignment_proven",
                    process_identity=alternate_process,
                    beacon_ref=alternate_beacon_ref,
                    assignment_ref=alternate_assignment_ref,
                    gate_state="closed",
                    predecessor=alternate_acquiring["content_sha256"],
                )
            )
            alternate_gate_owner = (
                LearningStageWorkerRegistry._benchmark_owner_journal(
                    current=launching,
                    anchor=anchor,
                    supervision=alternate_supervision,
                    scope_name=current_owner["scope_name"],
                    supervisor_identity=alternate_supervisor,
                    phase="gate_released",
                    process_identity=alternate_process,
                    beacon_ref=alternate_beacon_ref,
                    assignment_ref=alternate_assignment_ref,
                    gate_state="released",
                    predecessor=alternate_assigned_owner["content_sha256"],
                )
            )

            alternate_exit_body = dict(exit_observation)
            alternate_exit_body.pop("content_sha256")
            alternate_exit_body["process_identity"] = alternate_process
            alternate_exit_body["predecessor_content_sha256"] = (
                alternate_gate_owner["content_sha256"]
            )
            alternate_exit = seal_immutable(alternate_exit_body)
            exit_path.write_text(json.dumps(alternate_exit), encoding="utf-8")

            alternate_handle_refs = {}
            predecessor = alternate_exit["content_sha256"]
            handle_paths = {
                "worker_process": "worker-process-close.json",
                "startup_event": "startup-event-close.json",
                "beacon_file": "beacon-file-close.json",
            }
            original_handle_refs = intent["exact_handle_observation_refs"]
            for kind in ("worker_process", "startup_event", "beacon_file"):
                observation = _read_benchmark_artifact_by_ref(
                    tmp_path, original_handle_refs[kind]
                )
                body = dict(observation)
                body.pop("content_sha256")
                if kind == "worker_process":
                    body["handle_identity"] = {
                        "process_identity": alternate_process
                    }
                elif kind == "beacon_file":
                    body["handle_identity"] = {
                        "beacon_ref": alternate_beacon_ref
                    }
                body["predecessor_content_sha256"] = predecessor
                reminted = seal_immutable(body)
                (tmp_path / f"{started['worker_id']}.{handle_paths[kind]}").write_text(
                    json.dumps(reminted), encoding="utf-8"
                )
                alternate_handle_refs[kind] = {
                    "content_sha256": reminted["content_sha256"]
                }
                predecessor = reminted["content_sha256"]

            stable_body = dict(stable_zero)
            stable_body.pop("content_sha256")
            stable_body["samples"] = [[], [], []]
            stable_body["predecessor_content_sha256"] = predecessor
            alternate_stable = seal_immutable(stable_body)
            stable_path = tmp_path / f"{started['worker_id']}.stable-zero.json"
            stable_path.write_text(json.dumps(alternate_stable), encoding="utf-8")

            intent_body = dict(intent)
            intent_body.pop("content_sha256")
            intent_body.update({
                "supervision_ref": {
                    "content_sha256": alternate_supervision["content_sha256"]
                },
                "assignment_proven_ref": alternate_assignment_ref,
                "supervisor_process_identity": alternate_supervisor,
                "process_identity": alternate_process,
                "exit_observation_ref": {
                    "content_sha256": alternate_exit["content_sha256"]
                },
                "stable_zero_observation_ref": {
                    "content_sha256": alternate_stable["content_sha256"]
                },
                "exact_handle_observation_refs": alternate_handle_refs,
                "predecessor_content_sha256": alternate_gate_owner[
                    "content_sha256"
                ],
            })
            alternate_intent = seal_immutable(intent_body)
            intent_path = (
                tmp_path / f"{started['worker_id']}.benchmark-cleanup-intent.json"
            )
            intent_path.write_text(json.dumps(alternate_intent), encoding="utf-8")

            owner_body = dict(alternate_gate_owner)
            owner_body.pop("content_sha256")
            owner_body.update({
                "phase": "cleanup_finalization_intent",
                "exit_observation_ref": {
                    "content_sha256": alternate_exit["content_sha256"]
                },
                "stable_zero_observation_ref": {
                    "content_sha256": alternate_stable["content_sha256"]
                },
                "exact_handle_observation_refs": alternate_handle_refs,
                "cleanup_finalization_intent": {
                    "content_sha256": alternate_intent["content_sha256"]
                },
                "predecessor_content_sha256": alternate_gate_owner[
                    "content_sha256"
                ],
            })
            alternate_owner = seal_immutable(owner_body)
            owner_path.write_text(json.dumps(alternate_owner), encoding="utf-8")

            job_body = dict(job_absence)
            job_body.pop("content_sha256")
            job_body["predecessor_content_sha256"] = alternate_intent[
                "content_sha256"
            ]
            alternate_job = seal_immutable(job_body)
            job_path = tmp_path / f"{started['worker_id']}.job-absence.json"
            job_path.write_text(json.dumps(alternate_job), encoding="utf-8")
            worker_body = dict(worker_absence)
            worker_body.pop("content_sha256")
            worker_body["process_identity"] = alternate_process
            worker_body["predecessor_content_sha256"] = alternate_job[
                "content_sha256"
            ]
            alternate_worker = seal_immutable(worker_body)
            worker_path = tmp_path / f"{started['worker_id']}.worker-absence.json"
            worker_path.write_text(json.dumps(alternate_worker), encoding="utf-8")

            receipt_body = dict(receipt)
            receipt_body.pop("content_sha256")
            receipt_body.update({
                "supervision_ref": {
                    "content_sha256": alternate_supervision["content_sha256"]
                },
                "process_identity": alternate_process,
                "assignment_proven_ref": alternate_assignment_ref,
                "finalization_intent_ref": {
                    "content_sha256": alternate_intent["content_sha256"]
                },
                "exact_handle_observation_refs": alternate_handle_refs,
                "job_absence_observation_ref": {
                    "content_sha256": alternate_job["content_sha256"]
                },
                "worker_absence_observation_ref": {
                    "content_sha256": alternate_worker["content_sha256"]
                },
            })
            alternate_receipt = seal_immutable(receipt_body)
            receipt_path.write_text(json.dumps(alternate_receipt), encoding="utf-8")
            with pytest.raises(
                LearningStageWorkerError,
                match="assignment|launch identity anchor",
            ):
                registry.observe_benchmark_worker_cleanup(**cleanup_kwargs)
            assert not Path(
                registry._records[started["worker_id"]]["benchmark_beacon_path"]
            ).exists()


def test_benchmark_worker_process_probe_access_denied_is_indeterminate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psutil
    from app.learn import workflow_worker as worker_module

    monkeypatch.setattr(
        psutil,
        "Process",
        lambda pid: (_ for _ in ()).throw(psutil.AccessDenied(pid)),
    )

    with pytest.raises(LearningStageWorkerError, match="indeterminate"):
        LearningStageWorkerRegistry._benchmark_process_incarnation_absent(
            {"pid": 43210, "create_time_ns": 123}
        )
    observation = worker_module._benchmark_cleanup_replay_process_probe(
        {"pid": 43210, "create_time_ns": 123}
    )
    assert observation["outcome"] == "indeterminate"
    assert observation["observed_process_identity"] is None
    assert observation["error"]["error_type"] == "AccessDenied"
    assert worker_module.content_sha256(observation) == (
        observation["content_sha256"]
    )


def test_benchmark_worker_cleanup_replay_process_probe_exact_incarnation_decisions(
) -> None:
    import psutil
    from app.learn import workflow_worker as worker_module

    identity = {
        "pid": os.getpid(),
        "create_time_ns": int(
            round(psutil.Process().create_time() * 1_000_000_000)
        ),
    }
    present = worker_module._benchmark_cleanup_replay_process_probe(identity)
    assert present["contract_version"] == (
        "benchmark_worker_cleanup_replay_process_probe_v1"
    )
    assert present["expected_process_identity"] == identity
    assert present["observed_process_identity"] == identity
    assert present["outcome"] == "same_incarnation_live"
    assert present["error"] is None
    assert worker_module.content_sha256(present) == present["content_sha256"]

    different = worker_module._benchmark_cleanup_replay_process_probe({
        **identity,
        "create_time_ns": identity["create_time_ns"] + 2_000_000_000,
    })
    assert different["observed_process_identity"] == identity
    assert different["outcome"] == "different_incarnation"
    assert different["error"] is None
    assert worker_module.content_sha256(different) == different["content_sha256"]


def test_benchmark_worker_cleanup_replay_job_probe_rejects_live_empty_name(
) -> None:
    from app.learn import workflow_worker as worker_module
    from app.learn.hybrid.windows_process_scope import WindowsProcessScope

    scope_name = "Local\\AgentGuiBenchmarkWorkerTest-" + "c" * 64
    owner = WindowsProcessScope(scope_name, create=True)
    try:
        present = worker_module._benchmark_cleanup_replay_job_probe(scope_name)
        assert present["contract_version"] == (
            "benchmark_worker_cleanup_replay_job_probe_v1"
        )
        assert present["scope_name"] == scope_name
        assert present["outcome"] == "job_name_present"
        assert present["member_pids"] == []
        assert present["error"] is None
        assert present["temporary_handle_close"] == "closed"
        assert worker_module.content_sha256(present) == present["content_sha256"]
    finally:
        owner.close()

    absent = worker_module._benchmark_cleanup_replay_job_probe(scope_name)
    assert absent["outcome"] == "job_name_absent"
    assert absent["member_pids"] is None
    assert absent["error"] is None
    assert absent["temporary_handle_close"] == "not_opened"
    assert worker_module.content_sha256(absent) == absent["content_sha256"]


def test_benchmark_worker_cleanup_job_probe_api_error_is_indeterminate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import workflow_worker as worker_module
    from app.learn.hybrid import windows_process_scope

    registry = LearningStageWorkerRegistry(result_root=tmp_path)

    class ProbeError(OSError):
        winerror = 5

    monkeypatch.setattr(
        windows_process_scope,
        "WindowsProcessScope",
        lambda *args, **kwargs: (_ for _ in ()).throw(ProbeError("denied")),
    )
    with pytest.raises(LearningStageWorkerError, match="indeterminate"):
        registry._persist_benchmark_absence_observation(
            worker_id="worker-probe-error",
            observation_kind="job",
            scope_name="Local\\AgentGuiBenchmarkWorkerTest-" + "a" * 64,
            process_identity=None,
            predecessor_content_sha256="b" * 64,
        )
    assert not list(tmp_path.glob("*.job-absence.json"))
    observation = worker_module._benchmark_cleanup_replay_job_probe(
        "Local\\AgentGuiBenchmarkWorkerTest-" + "a" * 64
    )
    assert observation["outcome"] == "indeterminate"
    assert observation["member_pids"] is None
    assert observation["temporary_handle_close"] == "not_opened"
    assert observation["error"]["stage"] == "open"
    assert observation["error"]["winerror"] == 5
    assert worker_module.content_sha256(observation) == (
        observation["content_sha256"]
    )


def test_benchmark_worker_controller_post_launch_release_fault_never_second_spawns(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import win32event

    root = compose_test_benchmark_worker_supervision_root(
        journal_root=tmp_path, test_capability=object(),
        workflow_store=LearningWorkflowRunStore(), test_store_capability=object(),
    )
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path, benchmark_supervision_root=root,
    )
    source = _benchmark_handler_payload_source()
    reservation = registry.prepare_benchmark_worker_identity(
        run_id="run-controller-post-launch", stage="screen_understanding",
        operation_id="operation-controller-post-launch", workflow_revision=1,
        task_kind="vision_observe_screen", handler_payload_source=source,
        supervision_root=root,
    )
    anchor = compose_benchmark_worker_operation_anchor_v1(
        supervision_root=root, reservation=reservation,
        handler_payload_source=source,
        window_binding_ref=source["window_binding_ref"], capture_ref=source["capture_ref"],
        predecessor_content_sha256=None,
    )
    confirmation = registry.confirm_prepared_benchmark_worker_anchor(
        reservation_ref={"content_sha256": reservation["content_sha256"]},
        expected_operation_anchor=anchor, supervision_root=root,
    )
    real_release = win32event.ReleaseMutex
    injected = {"done": False}

    def release_after_success(handle):
        real_release(handle)
        if not injected["done"]:
            injected["done"] = True
            raise OSError("injected-post-launch-release")

    monkeypatch.setattr(win32event, "ReleaseMutex", release_after_success)
    try:
        with pytest.raises(
            LearningStageWorkerError,
            match="benchmark worker controller cleanup failed",
        ):
            registry.launch_prepared_benchmark_worker(
                reservation_ref=confirmation["anchored_reservation_ref"],
                expected_operation_anchor=anchor,
                authoritative_payload={"capture_live": False},
                supervision_root=root,
            )
        monkeypatch.setattr(win32event, "ReleaseMutex", real_release)
        with pytest.raises(LearningStageWorkerError, match="recovery required"):
            registry.inspect_prepared_benchmark_worker_identity(
                run_id=reservation["run_id"], stage=reservation["stage"],
                operation_id=reservation["operation_id"], supervision_root=root,
            )
        current = registry.inspect_prepared_benchmark_worker_identity(
            run_id=reservation["run_id"], stage=reservation["stage"],
            operation_id=reservation["operation_id"], supervision_root=root,
        )
        assert current["reservation_state"] == "launched"
        assert len(registry._records) == 1
        with pytest.raises(LearningStageWorkerError, match="anchored"):
            registry.launch_prepared_benchmark_worker(
                reservation_ref={"content_sha256": current["content_sha256"]},
                expected_operation_anchor=anchor,
                authoritative_payload={"capture_live": False},
                supervision_root=root,
            )
    finally:
        monkeypatch.setattr(win32event, "ReleaseMutex", real_release)
        if registry._records:
            registry.observe_benchmark_worker_cleanup(
                worker_id=reservation["worker_id"], run_id=reservation["run_id"],
                stage=reservation["stage"], operation_id=reservation["operation_id"],
                terminate=True, expected_operation_anchor=anchor,
                supervision_root=root,
            )


@pytest.mark.parametrize("job_close_fault", [False, True])
def test_benchmark_worker_launch_exception_seals_assignment_and_cleanup_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    job_close_fault: bool,
) -> None:
    import psutil
    import win32event
    from app.learn import workflow_worker as worker_module
    from app.learn.hybrid.windows_process_scope import WindowsProcessScope

    registry, root, store, source, reservation, anchor = _benchmark_registry_fixture(
        tmp_path
    )
    del store, source
    confirmation = registry.confirm_prepared_benchmark_worker_anchor(
        reservation_ref={"content_sha256": reservation["content_sha256"]},
        expected_operation_anchor=anchor,
        supervision_root=root,
    )
    registry._process_factory = multiprocessing.get_context("spawn").Process
    real_write_json = worker_module._write_json_atomic
    real_scope_close = WindowsProcessScope.close
    injected_owner = {"done": False}

    def fail_after_assignment_owner(path, payload):
        result = real_write_json(path, payload)
        if (
            not injected_owner["done"]
            and str(path).endswith(".benchmark-owner.json")
            and payload.get("phase") == "assignment_proven"
        ):
            injected_owner["done"] = True
            raise OSError("injected-after-assignment-owner")
        return result

    def close_after_success(scope):
        result = real_scope_close(scope)
        if injected_owner["done"]:
            raise OSError("injected-job-close-success-after")
        return result

    monkeypatch.setattr(worker_module, "_write_json_atomic", fail_after_assignment_owner)
    if job_close_fault:
        monkeypatch.setattr(WindowsProcessScope, "close", close_after_success)
    expected_error = (
        worker_module.LearningStageWorkerCleanupError
        if job_close_fault
        else OSError
    )
    try:
        with pytest.raises(expected_error) as captured:
            registry.launch_prepared_benchmark_worker(
                reservation_ref=confirmation["anchored_reservation_ref"],
                expected_operation_anchor=anchor,
                authoritative_payload={"capture_live": False},
                supervision_root=root,
            )
        cleanup = json.loads(
            next(tmp_path.glob("*.benchmark-launch-failure-cleanup.json"))
            .read_text(encoding="utf-8")
        )
        assert worker_module.content_sha256(cleanup) == cleanup["content_sha256"]
        assert cleanup["assignment_observation_ref"] is not None
        assert cleanup["process_identity"] is not None
        assert cleanup["scope_name"].startswith(
            "Local\\AgentGuiBenchmarkWorkerTest-"
        )
        assert cleanup["process_terminate"]["status"] == "completed"
        assert cleanup["job_terminate"]["status"] == "completed"
        assert cleanup["process_join"]["status"] == "completed"
        assert cleanup["process_join"]["result"]["alive_after"] is False
        assert cleanup["process_close"]["status"] == "completed"
        assert cleanup["event_close"]["status"] == "completed"
        assert cleanup["beacon_unlink"]["status"] == "completed"
        assert cleanup["job_close"]["status"] == (
            "error" if job_close_fault else "completed"
        )
        assert cleanup["cleanup_status"] == (
            "indeterminate" if job_close_fault else "verified"
        )
        if job_close_fault:
            assert captured.value.cleanup_evidence == cleanup

        owner = json.loads(
            next(tmp_path.glob("*.benchmark-owner.json")).read_text(encoding="utf-8")
        )
        assignment = json.loads(
            next(tmp_path.glob("*.benchmark-assignment.json"))
            .read_text(encoding="utf-8")
        )
        assert owner["phase"] == "recovery_required"
        assert owner["assignment_observation_ref"] == {
            "content_sha256": assignment["content_sha256"]
        }
        assert owner["process_identity"] == cleanup["process_identity"]
        assert owner["scope_name"] == cleanup["scope_name"]
        assert owner["exit_observation_ref"] == {
            "content_sha256": cleanup["content_sha256"]
        }
        current = registry.inspect_prepared_benchmark_worker_identity(
            run_id=reservation["run_id"], stage=reservation["stage"],
            operation_id=reservation["operation_id"], supervision_root=root,
        )
        assert current["reservation_state"] == "launching"
        with pytest.raises(LearningStageWorkerError, match="anchored"):
            registry.launch_prepared_benchmark_worker(
                reservation_ref={"content_sha256": current["content_sha256"]},
                expected_operation_anchor=anchor,
                authoritative_payload={"capture_live": False},
                supervision_root=root,
            )
        process_identity = cleanup["process_identity"]
        try:
            process = psutil.Process(process_identity["pid"])
            assert int(round(process.create_time() * 1_000_000_000)) != (
                process_identity["create_time_ns"]
            )
        except psutil.NoSuchProcess:
            pass
        with pytest.raises(Exception):
            WindowsProcessScope(cleanup["scope_name"], create=False)

        if job_close_fault:
            operation_key = (
                reservation["run_id"], reservation["stage"],
                reservation["operation_id"],
            )
            assert operation_key in registry._failed_start_cleanups
            retained = registry._failed_start_cleanups[operation_key]
            assert retained["benchmark_process"] is not None
            assert retained["benchmark_event_handle"] is not None
            assert retained["benchmark_scope"] is not None
            monkeypatch.setattr(WindowsProcessScope, "close", real_scope_close)
            retry = registry.observe_benchmark_worker_cleanup(
                worker_id=reservation["worker_id"], run_id=reservation["run_id"],
                stage=reservation["stage"], operation_id=reservation["operation_id"],
                terminate=True, expected_operation_anchor=anchor,
                supervision_root=root,
            )
            assert retry["status"] == "recovery_required"
            assert retry["cleanup_status"] == "verified"

        restarted = LearningStageWorkerRegistry(
            result_root=tmp_path, benchmark_supervision_root=root,
        )
        recovery = restarted.observe_benchmark_worker_cleanup(
            worker_id=reservation["worker_id"], run_id=reservation["run_id"],
            stage=reservation["stage"], operation_id=reservation["operation_id"],
            terminate=True, expected_operation_anchor=anchor,
            supervision_root=root,
        )
        assert recovery["status"] == "recovery_required"
        assert recovery["process_identity"] == cleanup["process_identity"]
    finally:
        monkeypatch.setattr(worker_module, "_write_json_atomic", real_write_json)
        monkeypatch.setattr(WindowsProcessScope, "close", real_scope_close)
        for process in psutil.process_iter(["pid", "cmdline"]):
            cmdline = " ".join(process.info.get("cmdline") or [])
            if reservation["worker_id"] in cmdline:
                process.kill()
                process.wait(timeout=10)


@pytest.mark.parametrize(
    ("resource", "failure_mode"),
    [
        (resource, mode)
        for resource in ("process_close", "event_close", "job_close")
        for mode in ("before", "api_false", "success_after")
    ]
    + [("terminate_and_job_close", "before")],
)
def test_benchmark_worker_failed_launch_cleanup_fault_matrix_retries_owned_objects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    resource: str,
    failure_mode: str,
) -> None:
    import psutil
    import win32event
    from app.learn import workflow_worker as worker_module
    from app.learn.hybrid.windows_process_scope import WindowsProcessScope

    registry, root, store, source, reservation, anchor = _benchmark_registry_fixture(
        tmp_path
    )
    del store, source
    confirmation = registry.confirm_prepared_benchmark_worker_anchor(
        reservation_ref={"content_sha256": reservation["content_sha256"]},
        expected_operation_anchor=anchor, supervision_root=root,
    )
    registry._process_factory = multiprocessing.get_context("spawn").Process
    real_write = worker_module._write_json_atomic
    assignment_cut = {"done": False}

    def fail_after_assignment_owner(path, payload):
        result = real_write(path, payload)
        if (
            not assignment_cut["done"]
            and str(path).endswith(".benchmark-owner.json")
            and payload.get("phase") == "assignment_proven"
        ):
            assignment_cut["done"] = True
            raise OSError("injected-after-assignment-owner")
        return result

    monkeypatch.setattr(worker_module, "_write_json_atomic", fail_after_assignment_owner)
    wrapper_by_resource = {
        "process_close": "_benchmark_failed_launch_process_close",
        "event_close": "_benchmark_failed_launch_event_close",
        "job_close": "_benchmark_failed_launch_job_close",
    }
    patched: dict[str, object] = {}

    def install_fault(wrapper_name: str, mode: str) -> None:
        real = getattr(worker_module, wrapper_name)
        patched[wrapper_name] = real

        def fault(*args, **kwargs):
            if mode == "success_after":
                real(*args, **kwargs)
            if mode == "api_false":
                return False
            raise OSError(f"injected-{wrapper_name}-{mode}")

        monkeypatch.setattr(worker_module, wrapper_name, fault)

    if resource == "terminate_and_job_close":
        install_fault("_benchmark_failed_launch_process_terminate", "before")
        install_fault("_benchmark_failed_launch_job_close", "before")
        expected_failed_steps = {"process_terminate", "job_close"}
    else:
        install_fault(wrapper_by_resource[resource], failure_mode)
        expected_failed_steps = {resource}
    operation_key = (
        reservation["run_id"], reservation["stage"], reservation["operation_id"],
    )
    cleanup = None
    try:
        with pytest.raises(worker_module.LearningStageWorkerCleanupError):
            registry.launch_prepared_benchmark_worker(
                reservation_ref=confirmation["anchored_reservation_ref"],
                expected_operation_anchor=anchor,
                authoritative_payload={"capture_live": False},
                supervision_root=root,
            )
        cleanup = json.loads(
            next(tmp_path.glob("*.benchmark-launch-failure-cleanup.json"))
            .read_text(encoding="utf-8")
        )
        assert cleanup["cleanup_status"] == "indeterminate"
        assert expected_failed_steps.issubset(
            {item["step"] for item in cleanup["cleanup_failures"]}
        )
        retained = registry._failed_start_cleanups[operation_key]
        assert retained["benchmark_process"] is not None
        assert retained["benchmark_event_handle"] is not None
        assert retained["benchmark_scope"] is not None
        with pytest.raises(LearningStageWorkerError, match="anchored"):
            registry.launch_prepared_benchmark_worker(
                reservation_ref=confirmation["anchored_reservation_ref"],
                expected_operation_anchor=anchor,
                authoritative_payload={"capture_live": False},
                supervision_root=root,
            )

        monkeypatch.setattr(worker_module, "_write_json_atomic", real_write)
        for wrapper_name, real in patched.items():
            monkeypatch.setattr(worker_module, wrapper_name, real)
        retry = registry.observe_benchmark_worker_cleanup(
            worker_id=reservation["worker_id"], run_id=reservation["run_id"],
            stage=reservation["stage"], operation_id=reservation["operation_id"],
            terminate=True, expected_operation_anchor=anchor,
            supervision_root=root,
        )
        assert retry["cleanup_status"] == "verified"
        assert operation_key not in registry._failed_start_cleanups
        retry_observation = _read_benchmark_artifact_by_ref(
            tmp_path, retry["cleanup_observation_ref"]
        )
        assert retry_observation["cleanup_attempt"] == 1
        assert retry_observation["predecessor_content_sha256"] == cleanup[
            "content_sha256"
        ]
        assert retry_observation["job_stable_zero"] == {
            "status": "completed",
            "result": {"samples": [[], [], []]},
        }
        assert all(
            retry_observation[name]["status"] == "completed"
            for name in (
                "process_terminate", "job_terminate", "process_join",
                "job_stable_zero", "process_close", "event_close",
                "beacon_unlink", "job_close",
            )
        )
        identity = retry_observation["process_identity"]
        try:
            observed = psutil.Process(identity["pid"])
            assert int(round(observed.create_time() * 1_000_000_000)) != (
                identity["create_time_ns"]
            )
        except psutil.NoSuchProcess:
            pass
        with pytest.raises(Exception):
            WindowsProcessScope(retry_observation["scope_name"], create=False)
        event_name = (
            "Local\\AgentGuiBenchmarkWorkerGate-"
            + worker_module.content_sha256({
                "scope_name": retry_observation["scope_name"]
            })
        )
        with pytest.raises(Exception):
            win32event.OpenEvent(
                win32event.EVENT_MODIFY_STATE | 0x00100000, False, event_name,
            )
        assert not list(tmp_path.glob("*.benchmark-beacon.json"))
    finally:
        monkeypatch.setattr(worker_module, "_write_json_atomic", real_write)
        for wrapper_name, real in patched.items():
            monkeypatch.setattr(worker_module, wrapper_name, real)
        retained = registry._failed_start_cleanups.get(operation_key)
        if isinstance(retained, dict):
            try:
                registry.observe_benchmark_worker_cleanup(
                    worker_id=reservation["worker_id"], run_id=reservation["run_id"],
                    stage=reservation["stage"], operation_id=reservation["operation_id"],
                    terminate=True, expected_operation_anchor=anchor,
                    supervision_root=root,
                )
            except BaseException:
                process = retained.get("benchmark_process")
                if process is not None:
                    try:
                        if process.is_alive():
                            process.terminate(); process.join(timeout=10)
                    except BaseException:
                        pass
                scope = retained.get("benchmark_scope")
                if scope is not None:
                    try: scope.terminate()
                    except BaseException: pass
                    try: scope.close()
                    except BaseException: pass
                handle = retained.get("benchmark_event_handle")
                if handle is not None:
                    try:
                        import win32api
                        win32api.CloseHandle(handle)
                    except BaseException:
                        pass


def test_benchmark_worker_real_parent_death_recovers_without_second_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    outer = context.Process(
        target=_benchmark_parent_death_helper,
        args=(str(tmp_path), queue),
        name="test-owned-benchmark-parent-death",
    )
    outer.start()
    message = None
    try:
        message = queue.get(timeout=25)
        assert "error" not in message, message.get("error")
        outer.terminate()
        outer.join(timeout=10)
        assert outer.is_alive() is False

        root = compose_test_benchmark_worker_supervision_root(
            journal_root=tmp_path, test_capability=object(),
            workflow_store=LearningWorkflowRunStore(),
            test_store_capability=object(),
        )
        registry = LearningStageWorkerRegistry(
            result_root=tmp_path, benchmark_supervision_root=root,
        )
        started = message["started"]
        receipt = registry.observe_benchmark_worker_cleanup(
            worker_id=started["worker_id"], run_id="run-parent-death",
            stage="screen_understanding", operation_id="operation-parent-death",
            terminate=True, expected_operation_anchor=message["anchor"],
            supervision_root=root,
        )
        assert receipt["outcome"] == "verified_exact_worker_exited"
        assert receipt["supervisor_absence_observation_ref"] is not None
        intent = _read_benchmark_artifact_by_ref(
            tmp_path, receipt["finalization_intent_ref"]
        )
        stable_zero = _read_benchmark_artifact_by_ref(
            tmp_path, intent["stable_zero_observation_ref"]
        )
        assert len(stable_zero["samples"]) == 3
        predecessor = intent["predecessor_content_sha256"]
        for field in (
            "job_absence_observation_ref",
            "worker_absence_observation_ref",
            "supervisor_absence_observation_ref",
        ):
            observation = _read_benchmark_artifact_by_ref(
                tmp_path, receipt[field]
            )
            assert observation["outcome"] == "absent"
            assert len(observation["predecessor_content_sha256"]) == 64
        replay_kwargs = {
            "worker_id": started["worker_id"],
            "run_id": "run-parent-death",
            "stage": "screen_understanding",
            "operation_id": "operation-parent-death",
            "terminate": True,
            "expected_operation_anchor": message["anchor"],
            "supervision_root": root,
        }
        receipt_path = (
            tmp_path / f"{started['worker_id']}.benchmark-cleanup.json"
        )
        receipt_bytes = receipt_path.read_bytes()
        assert registry.observe_benchmark_worker_cleanup(**replay_kwargs) == receipt
        assert registry.observe_benchmark_worker_cleanup(**replay_kwargs) == receipt
        assert receipt_path.read_bytes() == receipt_bytes

        from app.learn.hybrid.windows_process_scope import WindowsProcessScope

        owner = json.loads(
            (
                tmp_path / f"{started['worker_id']}.benchmark-owner.json"
            ).read_text(encoding="utf-8")
        )
        collision = WindowsProcessScope(owner["scope_name"], create=True)
        try:
            assert collision.pids() == []
            with pytest.raises(
                LearningStageWorkerError,
                match="cleanup replay Job name is present",
            ):
                registry.observe_benchmark_worker_cleanup(**replay_kwargs)
        finally:
            collision.close()
        assert receipt_path.read_bytes() == receipt_bytes

        import psutil

        real_psutil_process = psutil.Process
        expected_process_identity = receipt["process_identity"]

        class ObservedProcess:
            def __init__(self, create_time_ns: int) -> None:
                self._create_time_ns = create_time_ns

            def create_time(self) -> float:
                return self._create_time_ns / 1_000_000_000

        monkeypatch.setattr(
            psutil,
            "Process",
            lambda pid: ObservedProcess(
                expected_process_identity["create_time_ns"]
            ),
        )
        with pytest.raises(
            LearningStageWorkerError,
            match="cleanup replay worker incarnation is live",
        ):
            registry.observe_benchmark_worker_cleanup(**replay_kwargs)
        assert receipt_path.read_bytes() == receipt_bytes

        monkeypatch.setattr(
            psutil,
            "Process",
            lambda pid: ObservedProcess(
                expected_process_identity["create_time_ns"]
                + 2_000_000_000
            ),
        )
        assert registry.observe_benchmark_worker_cleanup(**replay_kwargs) == receipt
        assert receipt_path.read_bytes() == receipt_bytes

        monkeypatch.setattr(
            psutil,
            "Process",
            lambda pid: (_ for _ in ()).throw(psutil.AccessDenied(pid)),
        )
        with pytest.raises(
            LearningStageWorkerError,
            match="cleanup replay process probe is indeterminate",
        ):
            registry.observe_benchmark_worker_cleanup(**replay_kwargs)
        monkeypatch.setattr(
            psutil,
            "Process",
            lambda pid: (_ for _ in ()).throw(
                OSError("injected-replay-process-api-error")
            ),
        )
        with pytest.raises(
            LearningStageWorkerError,
            match="cleanup replay process probe is indeterminate",
        ):
            registry.observe_benchmark_worker_cleanup(**replay_kwargs)
        monkeypatch.setattr(psutil, "Process", real_psutil_process)
        assert receipt_path.read_bytes() == receipt_bytes

        real_scope_init = WindowsProcessScope.__init__

        class OpenProbeError(OSError):
            def __init__(self, code: int, message: str) -> None:
                super().__init__(code, message)
                self.winerror = code

        monkeypatch.setattr(
            WindowsProcessScope,
            "__init__",
            lambda self, name, create: (_ for _ in ()).throw(
                OpenProbeError(5, "injected-replay-job-access-denied")
            ),
        )
        with pytest.raises(
            LearningStageWorkerError,
            match="cleanup replay Job probe is indeterminate",
        ):
            registry.observe_benchmark_worker_cleanup(**replay_kwargs)
        monkeypatch.setattr(
            WindowsProcessScope,
            "__init__",
            lambda self, name, create: (_ for _ in ()).throw(
                OpenProbeError(87, "injected-replay-job-api-error")
            ),
        )
        with pytest.raises(
            LearningStageWorkerError,
            match="cleanup replay Job probe is indeterminate",
        ):
            registry.observe_benchmark_worker_cleanup(**replay_kwargs)
        monkeypatch.setattr(WindowsProcessScope, "__init__", real_scope_init)

        collision = WindowsProcessScope(owner["scope_name"], create=True)
        real_scope_pids = WindowsProcessScope.pids
        real_scope_close = WindowsProcessScope.close
        try:
            monkeypatch.setattr(
                WindowsProcessScope,
                "pids",
                lambda scope: (_ for _ in ()).throw(
                    OSError("injected-replay-job-query-error")
                ),
            )
            with pytest.raises(
                LearningStageWorkerError,
                match="cleanup replay Job probe is indeterminate",
            ):
                registry.observe_benchmark_worker_cleanup(**replay_kwargs)
            monkeypatch.setattr(WindowsProcessScope, "pids", real_scope_pids)

            def close_then_raise(scope: WindowsProcessScope) -> None:
                real_scope_close(scope)
                raise OSError("injected-replay-job-close-error")

            monkeypatch.setattr(
                WindowsProcessScope,
                "close",
                close_then_raise,
            )
            with pytest.raises(
                LearningStageWorkerError,
                match="cleanup replay Job probe is indeterminate",
            ):
                registry.observe_benchmark_worker_cleanup(**replay_kwargs)
        finally:
            monkeypatch.setattr(WindowsProcessScope, "pids", real_scope_pids)
            monkeypatch.setattr(WindowsProcessScope, "close", real_scope_close)
            collision.close()
        assert receipt_path.read_bytes() == receipt_bytes
        assert registry.observe_benchmark_worker_cleanup(**replay_kwargs) == receipt
        assert receipt_path.read_bytes() == receipt_bytes
        assert len(list(tmp_path.glob("*.worker.json"))) == 1
    finally:
        if outer.is_alive():
            outer.terminate()
            outer.join(timeout=10)
        queue.close()
        queue.join_thread()


def test_benchmark_worker_parent_death_before_assignment_terminates_beacon_identity(
    tmp_path: Path,
) -> None:
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    outer = context.Process(
        target=_benchmark_parent_death_helper,
        args=(str(tmp_path), queue, "pre_assignment"),
        name="test-owned-benchmark-preassignment-parent-death",
    )
    outer.start()
    message = None
    try:
        message = queue.get(timeout=25)
        assert message.get("cut_ready") is True, message
        outer.terminate(); outer.join(timeout=10)
        assert outer.is_alive() is False
        root = compose_test_benchmark_worker_supervision_root(
            journal_root=tmp_path, test_capability=object(),
            workflow_store=LearningWorkflowRunStore(),
            test_store_capability=object(),
        )
        registry = LearningStageWorkerRegistry(
            result_root=tmp_path, benchmark_supervision_root=root,
        )
        cleanup = registry.observe_benchmark_worker_cleanup(
            worker_id=message["worker_id"], run_id="run-parent-death",
            stage="screen_understanding", operation_id="operation-parent-death",
            terminate=True, expected_operation_anchor=message["anchor"],
            supervision_root=root,
        )
        assert cleanup["status"] == "recovery_required"
        assert cleanup["exact_process_termination"]["outcome"] in {
            "verified_exact_incarnation_terminated",
            "exact_incarnation_already_absent",
        }
        assert not list(tmp_path.glob("*.benchmark-cleanup.json"))
    finally:
        if outer.is_alive():
            outer.terminate(); outer.join(timeout=10)
        queue.close(); queue.join_thread()


@pytest.mark.parametrize(
    "cut",
    [
        "assignment_proven", "result_write", "before_intent", "after_intent", "after_job_close",
        "receipt_temp_create", "receipt_write", "receipt_file_flush",
        "receipt_directory_fsync", "receipt_atomic_replace",
    ],
)
def test_benchmark_worker_parent_death_cleanup_cut_recovers_same_incarnation(
    tmp_path: Path,
    cut: str,
) -> None:
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    outer = context.Process(
        target=_benchmark_parent_death_helper,
        args=(str(tmp_path), queue, cut),
        name=f"test-owned-benchmark-parent-death-{cut}",
    )
    outer.start()
    try:
        message = queue.get(timeout=30)
        assert message.get("cut_ready") is True, message
        outer.terminate(); outer.join(timeout=10)
        assert outer.is_alive() is False
        root = compose_test_benchmark_worker_supervision_root(
            journal_root=tmp_path, test_capability=object(),
            workflow_store=LearningWorkflowRunStore(), test_store_capability=object(),
        )
        registry = LearningStageWorkerRegistry(
            result_root=tmp_path, benchmark_supervision_root=root,
        )
        started = message["started"]
        receipt = registry.observe_benchmark_worker_cleanup(
            worker_id=started["worker_id"], run_id="run-parent-death",
            stage="screen_understanding", operation_id="operation-parent-death",
            terminate=True, expected_operation_anchor=message["anchor"],
            supervision_root=root,
        )
        assert receipt["outcome"] == "verified_exact_worker_exited"
        assert len(list(tmp_path.glob("*.worker.json"))) == (
            0 if cut == "assignment_proven" else 1
        )
    finally:
        if outer.is_alive():
            outer.terminate(); outer.join(timeout=10)
        queue.close(); queue.join_thread()


def test_completed_result_identity_is_pre_adopt_read_only_and_closed(
    tmp_path: Path,
) -> None:
    registry, started = _identity_inspection_registry(tmp_path, suffix="closed")
    envelope = _write_completed_result_for_identity_inspection(registry, started)
    record = registry._records[str(started["worker_id"])]

    inspected = registry.inspect_completed_result_identity(
        worker_id=str(started["worker_id"]),
        run_id=str(record["run_id"]),
        stage=str(record["stage"]),
        operation_id=str(record["operation_id"]),
    )

    expected_keys = {
        "contract_version",
        "status",
        "worker_id",
        "run_id",
        "stage",
        "operation_id",
        "task_kind",
        "model_request_id",
        "payload_sha256",
        "result_sha256",
        "result_available",
        "normal_binding_evidence_ref",
        "provider_cleanup_evidence_ref",
    }
    assert set(inspected) == expected_keys
    assert inspected == {
        "contract_version": "learning_stage_worker_completed_result_identity_v1",
        "status": "completed",
        "worker_id": started["worker_id"],
        "run_id": record["run_id"],
        "stage": record["stage"],
        "operation_id": record["operation_id"],
        "task_kind": record["task_kind"],
        "model_request_id": record["model_request_id"],
        "payload_sha256": record["payload_sha256"],
        "result_sha256": hashlib.sha256(
            json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest(),
        "result_available": True,
        "normal_binding_evidence_ref": {"content_sha256": "a" * 64},
        "provider_cleanup_evidence_ref": None,
    }
    assert record.get("result_adoption") is None
    journal_path = Path(record["journal_path"])
    journal_after_first_inspection = journal_path.read_text(encoding="utf-8")
    assert "result_adoption" not in json.loads(journal_after_first_inspection)

    inspected_again = registry.inspect_completed_result_identity(
        worker_id=str(started["worker_id"]),
        run_id=str(record["run_id"]),
        stage=str(record["stage"]),
        operation_id=str(record["operation_id"]),
    )
    assert inspected_again == inspected
    assert journal_path.read_text(encoding="utf-8") == journal_after_first_inspection


@pytest.mark.parametrize(
    ("identity_key", "wrong_value"),
    [
        ("worker_id", "wrong-worker"),
        ("run_id", "wrong-run"),
        ("stage", "wrong-stage"),
        ("operation_id", "wrong-operation"),
        ("task_kind", "vision_locate_target"),
        ("model_request_id", "wrong-model-request"),
        ("payload_sha256", "b" * 64),
    ],
)
def test_completed_result_identity_rejects_mismatched_envelope_identity(
    tmp_path: Path,
    identity_key: str,
    wrong_value: str,
) -> None:
    registry, started = _identity_inspection_registry(
        tmp_path / identity_key,
        suffix=identity_key,
    )
    record = registry._records[str(started["worker_id"])]
    _write_completed_result_for_identity_inspection(
        registry,
        started,
        overrides={identity_key: wrong_value},
    )

    with pytest.raises(LearningStageWorkerError, match="completed result"):
        registry.inspect_completed_result_identity(
            worker_id=str(started["worker_id"]),
            run_id=str(record["run_id"]),
            stage=str(record["stage"]),
            operation_id=str(record["operation_id"]),
        )


@pytest.mark.parametrize(
    ("argument_name", "wrong_value"),
    [
        ("worker_id", "wrong-worker"),
        ("run_id", "wrong-run"),
        ("stage", "wrong-stage"),
        ("operation_id", "wrong-operation"),
    ],
)
def test_completed_result_identity_rejects_wrong_lookup_identity(
    tmp_path: Path,
    argument_name: str,
    wrong_value: str,
) -> None:
    registry, started = _identity_inspection_registry(tmp_path, suffix=argument_name)
    record = registry._records[str(started["worker_id"])]
    _write_completed_result_for_identity_inspection(registry, started)
    arguments = {
        "worker_id": str(started["worker_id"]),
        "run_id": str(record["run_id"]),
        "stage": str(record["stage"]),
        "operation_id": str(record["operation_id"]),
    }
    arguments[argument_name] = wrong_value

    with pytest.raises(LearningStageWorkerError):
        registry.inspect_completed_result_identity(**arguments)


@pytest.mark.parametrize(
    "overrides",
    [
        {"status": "running"},
        {"status": "failed", "error": {"type": "ExpectedFailure"}},
        {"response": ["not", "an", "object"]},
    ],
)
def test_completed_result_identity_rejects_noncompleted_or_invalid_response(
    tmp_path: Path,
    overrides: dict[str, object],
) -> None:
    suffix = str(len(list(tmp_path.parent.iterdir())))
    registry, started = _identity_inspection_registry(tmp_path, suffix=suffix)
    record = registry._records[str(started["worker_id"])]
    _write_completed_result_for_identity_inspection(
        registry,
        started,
        overrides=overrides,
    )

    with pytest.raises(LearningStageWorkerError, match="completed result"):
        registry.inspect_completed_result_identity(
            worker_id=str(started["worker_id"]),
            run_id=str(record["run_id"]),
            stage=str(record["stage"]),
            operation_id=str(record["operation_id"]),
        )


def test_completed_result_identity_rejects_broken_result_json(tmp_path: Path) -> None:
    registry, started = _identity_inspection_registry(tmp_path, suffix="broken-json")
    record = registry._records[str(started["worker_id"])]
    process = record["process"]
    process.alive = False
    process.exitcode = 0
    Path(record["result_path"]).write_text("{broken", encoding="utf-8")

    with pytest.raises(LearningStageWorkerError, match="completed result"):
        registry.inspect_completed_result_identity(
            worker_id=str(started["worker_id"]),
            run_id=str(record["run_id"]),
            stage=str(record["stage"]),
            operation_id=str(record["operation_id"]),
        )


@pytest.mark.parametrize(
    "invalid_ref",
    [
        {},
        {"content_sha256": "a" * 64, "extra": "forbidden"},
        {"content_sha256": "A" * 64},
        {"content_sha256": "a" * 63},
        {"content_sha256": 7},
        ["a" * 64],
    ],
)
@pytest.mark.parametrize(
    "ref_name",
    ["normal_binding_evidence_ref", "provider_cleanup_evidence_ref"],
)
def test_completed_result_identity_rejects_nonclosed_evidence_ref(
    tmp_path: Path,
    ref_name: str,
    invalid_ref: object,
) -> None:
    suffix = f"{ref_name}-{len(list(tmp_path.parent.iterdir()))}"
    registry, started = _identity_inspection_registry(tmp_path, suffix=suffix)
    record = registry._records[str(started["worker_id"])]
    _write_completed_result_for_identity_inspection(
        registry,
        started,
        overrides={ref_name: invalid_ref},
    )

    with pytest.raises(LearningStageWorkerError, match="evidence ref"):
        registry.inspect_completed_result_identity(
            worker_id=str(started["worker_id"]),
            run_id=str(record["run_id"]),
            stage=str(record["stage"]),
            operation_id=str(record["operation_id"]),
        )


def test_completed_result_identity_digest_is_exact_adoption_handoff(
    tmp_path: Path,
) -> None:
    registry, started = _identity_inspection_registry(tmp_path, suffix="handoff")
    record = registry._records[str(started["worker_id"])]
    _write_completed_result_for_identity_inspection(registry, started)
    arguments = {
        "worker_id": str(started["worker_id"]),
        "run_id": str(record["run_id"]),
        "stage": str(record["stage"]),
        "operation_id": str(record["operation_id"]),
    }

    inspected = registry.inspect_completed_result_identity(**arguments)
    result_path = Path(record["result_path"])
    reminted = json.loads(result_path.read_text(encoding="utf-8"))
    reminted["response"]["data"]["value"] = 2
    result_path.write_text(
        json.dumps(reminted, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    adopted = registry.adopt_result(**arguments)

    assert adopted["receipt"]["result_sha256"] == inspected["result_sha256"]
    assert adopted["response"]["data"]["value"] == 1


def test_completed_result_identity_is_stable_during_concurrent_adoption(
    tmp_path: Path,
) -> None:
    registry, started = _identity_inspection_registry(tmp_path, suffix="concurrent")
    record = registry._records[str(started["worker_id"])]
    _write_completed_result_for_identity_inspection(registry, started)
    arguments = {
        "worker_id": str(started["worker_id"]),
        "run_id": str(record["run_id"]),
        "stage": str(record["stage"]),
        "operation_id": str(record["operation_id"]),
    }
    start_gate = Event()
    inspections: list[dict[str, object]] = []
    adoptions: list[dict[str, object]] = []
    errors: list[BaseException] = []
    result_lock = Lock()

    def inspect() -> None:
        start_gate.wait()
        try:
            result = registry.inspect_completed_result_identity(**arguments)
            with result_lock:
                inspections.append(result)
        except BaseException as error:
            with result_lock:
                errors.append(error)

    def adopt() -> None:
        start_gate.wait()
        try:
            result = registry.adopt_result(**arguments)
            with result_lock:
                adoptions.append(result)
        except BaseException as error:
            with result_lock:
                errors.append(error)

    threads = [Thread(target=inspect), Thread(target=adopt), Thread(target=adopt)]
    for thread in threads:
        thread.start()
    start_gate.set()
    for thread in threads:
        thread.join(timeout=5)

    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert len(inspections) == 1
    assert len(adoptions) == 2
    assert {
        adoption["receipt"]["result_sha256"] for adoption in adoptions
    } == {inspections[0]["result_sha256"]}
    assert adoptions[0]["receipt"] == adoptions[1]["receipt"]
    assert registry.adopt_result(**arguments)["receipt"] == adoptions[0]["receipt"]


def test_completed_result_identity_reload_snapshots_current_same_identity_remint(
    tmp_path: Path,
) -> None:
    registry, started = _identity_inspection_registry(tmp_path, suffix="remint")
    record = registry._records[str(started["worker_id"])]
    _write_completed_result_for_identity_inspection(registry, started)
    arguments = {
        "worker_id": str(started["worker_id"]),
        "run_id": str(record["run_id"]),
        "stage": str(record["stage"]),
        "operation_id": str(record["operation_id"]),
    }
    original = registry.inspect_completed_result_identity(**arguments)

    _write_completed_result_for_identity_inspection(
        registry,
        started,
        response={"success": True, "data": {"value": "reminted"}},
    )
    assert registry.inspect_completed_result_identity(**arguments) == original

    reloaded = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    current = reloaded.inspect_completed_result_identity(**arguments)
    assert current["result_sha256"] != original["result_sha256"]
    assert current["status"] == "completed"
    assert not any("tamper" in key for key in current)


def test_worker_registry_requires_explicit_adoption_for_completed_response(
    tmp_path: Path,
) -> None:
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    started = registry.start(
        run_id="run-1",
        stage="review_repair",
        operation_id="operation-1",
        task_kind="panel_learning_model_review_repair",
        payload={},
    )
    record = registry._records[started["worker_id"]]
    process = record["process"]
    process.alive = False
    process.exitcode = 0
    Path(record["result_path"]).write_text(
        json.dumps(
            {
                "contract_version": "learning_stage_worker_result_v2",
                "worker_id": started["worker_id"],
                "run_id": "run-1",
                "stage": "review_repair",
                "operation_id": "operation-1",
                "task_kind": "panel_learning_model_review_repair",
                "model_request_id": started["model_request_id"],
                "payload_sha256": record["payload_sha256"],
                "status": "completed",
                "response": {"success": True, "data": {"value": 1}},
            }
        ),
        encoding="utf-8",
    )

    status = registry.status(
        worker_id=started["worker_id"],
        run_id="run-1",
        operation_id="operation-1",
    )

    assert status["status"] == "completed"
    assert status["result_available"] is True
    assert status["result_adopted"] is False
    assert "response" not in status

    adopted = registry.adopt_result(
        worker_id=started["worker_id"],
        run_id="run-1",
        stage="review_repair",
        operation_id="operation-1",
    )

    assert adopted["contract_version"] == "learning_stage_worker_result_adoption_v1"
    assert adopted["status"] == "adopted"
    assert adopted["response"]["success"] is True
    assert adopted["response"]["data"]["value"] == 1
    assert adopted["receipt"]["worker_id"] == started["worker_id"]
    assert adopted["receipt"]["result_sha256"]

    adopted_again = registry.adopt_result(
        worker_id=started["worker_id"],
        run_id="run-1",
        stage="review_repair",
        operation_id="operation-1",
    )
    assert adopted_again["receipt"] == adopted["receipt"]

    adopted_status = registry.status(
        worker_id=started["worker_id"],
        run_id="run-1",
        operation_id="operation-1",
    )
    assert adopted_status["result_adopted"] is True
    assert adopted_status["adoption_receipt"] == adopted["receipt"]
    assert "response" not in adopted_status

    adopted_result = registry.read_adopted_result(
        worker_id=started["worker_id"],
        run_id="run-1",
        stage="review_repair",
        operation_id="operation-1",
    )
    assert adopted_result["receipt"] == adopted["receipt"]
    assert adopted_result["response"]["data"]["value"] == 1


def test_worker_registry_rejects_result_read_before_adoption(
    tmp_path: Path,
) -> None:
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    started = registry.start(
        run_id="run-unadopted",
        stage="numbered_map",
        operation_id="operation-unadopted",
        task_kind="panel_learning_two_stage_understanding",
        payload={},
    )
    _finish_fake_worker(
        registry,
        started,
        response={"success": True, "data": {"result": {}}},
    )

    with pytest.raises(
        LearningStageWorkerError,
        match="result has not been adopted",
    ):
        registry.read_adopted_result(
            worker_id=started["worker_id"],
            run_id="run-unadopted",
            stage="numbered_map",
            operation_id="operation-unadopted",
        )


def test_worker_registry_recovers_durable_result_adoption_after_restart(
    tmp_path: Path,
) -> None:
    first_registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    started = first_registry.start(
        run_id="run-adoption-restart",
        stage="fusion",
        operation_id="operation-adoption-restart",
        task_kind="panel_learning_recognition_trial",
        payload={"image_path": "capture.png"},
    )
    _finish_fake_worker(
        first_registry,
        started,
        response={"success": True, "data": {"trial_path": "trial.json"}},
    )
    adopted = first_registry.adopt_result(
        worker_id=started["worker_id"],
        run_id="run-adoption-restart",
        stage="fusion",
        operation_id="operation-adoption-restart",
    )

    restarted_registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    recovered = restarted_registry.status(
        worker_id=started["worker_id"],
        run_id="run-adoption-restart",
        operation_id="operation-adoption-restart",
    )
    recovered_adoption = restarted_registry.adopt_result(
        worker_id=started["worker_id"],
        run_id="run-adoption-restart",
        stage="fusion",
        operation_id="operation-adoption-restart",
    )
    recovered_result = restarted_registry.read_adopted_result(
        worker_id=started["worker_id"],
        run_id="run-adoption-restart",
        stage="fusion",
        operation_id="operation-adoption-restart",
    )

    assert recovered["result_adopted"] is True
    assert recovered["adoption_receipt"] == adopted["receipt"]
    assert recovered_adoption["receipt"] == adopted["receipt"]
    assert recovered_adoption["response"]["data"]["trial_path"] == "trial.json"
    assert recovered_result["receipt"] == adopted["receipt"]
    assert recovered_result["response"]["data"]["trial_path"] == "trial.json"


def test_worker_registry_rejects_tampered_result_after_adoption_restart(
    tmp_path: Path,
) -> None:
    first_registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    started = first_registry.start(
        run_id="run-adoption-integrity",
        stage="fusion",
        operation_id="operation-adoption-integrity",
        task_kind="panel_learning_recognition_trial",
        payload={"image_path": "capture.png"},
    )
    _finish_fake_worker(
        first_registry,
        started,
        response={"success": True, "data": {"trial_path": "original.json"}},
    )
    first_registry.adopt_result(
        worker_id=started["worker_id"],
        run_id="run-adoption-integrity",
        stage="fusion",
        operation_id="operation-adoption-integrity",
    )
    result_path = Path(first_registry._records[started["worker_id"]]["result_path"])
    tampered = json.loads(result_path.read_text(encoding="utf-8"))
    tampered["response"]["data"]["trial_path"] = "tampered.json"
    result_path.write_text(json.dumps(tampered), encoding="utf-8")

    restarted_registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    recovered = restarted_registry.status(
        worker_id=started["worker_id"],
        run_id="run-adoption-integrity",
        operation_id="operation-adoption-integrity",
    )

    assert recovered["status"] == "failed"
    assert recovered["result_adopted"] is False
    assert recovered["error"]["type"] == "WorkerResultAdoptionDigestMismatch"


def test_worker_registry_rejects_adoption_for_failed_result(tmp_path: Path) -> None:
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    started = registry.start(
        run_id="run-failed-adoption",
        stage="fusion",
        operation_id="operation-failed-adoption",
        task_kind="panel_learning_recognition_trial",
        payload={},
    )
    record = registry._records[started["worker_id"]]
    process = record["process"]
    process.alive = False
    process.exitcode = 1
    registry.status(
        worker_id=started["worker_id"],
        run_id="run-failed-adoption",
        operation_id="operation-failed-adoption",
    )

    with pytest.raises(LearningStageWorkerError, match="completed result"):
        registry.adopt_result(
            worker_id=started["worker_id"],
            run_id="run-failed-adoption",
            stage="fusion",
            operation_id="operation-failed-adoption",
        )


def test_worker_registry_rejects_cross_operation_status_lookup(tmp_path: Path) -> None:
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    started = registry.start(
        run_id="run-1",
        stage="fusion",
        operation_id="operation-1",
        task_kind="panel_learning_recognition_trial",
        payload={},
    )

    with pytest.raises(LearningStageWorkerError, match="ownership"):
        registry.status(
            worker_id=started["worker_id"],
            run_id="run-2",
            operation_id="operation-1",
        )


def test_real_spawn_worker_reports_invalid_payload_without_model_call(
    tmp_path: Path,
) -> None:
    registry = LearningStageWorkerRegistry(result_root=tmp_path)
    started = registry.start(
        run_id="run-real-spawn",
        stage="precise_calibration",
        operation_id="operation-real-spawn",
        task_kind="vision_locate_target",
        payload={},
    )

    deadline = time.monotonic() + 15.0
    status = started
    while status["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
        status = registry.status(
            worker_id=started["worker_id"],
            run_id="run-real-spawn",
            operation_id="operation-real-spawn",
        )

    assert status["status"] == "failed"
    assert status["backend_compute_owner"] == "backend_process_worker"
    assert status["error"]["type"] in {"ValidationError", "WorkerResultMissing"}
    assert Path(status["result_path"]).is_file()


def test_real_observe_worker_reports_missing_image_without_model_call(
    tmp_path: Path,
) -> None:
    registry = LearningStageWorkerRegistry(result_root=tmp_path)
    started = registry.start(
        run_id="run-real-observe",
        stage="screen_understanding",
        operation_id="operation-real-observe",
        task_kind="vision_observe_screen",
        payload={"capture_live": False},
    )

    deadline = time.monotonic() + 15.0
    status = started
    while status["status"] == "running" and time.monotonic() < deadline:
        time.sleep(0.05)
        status = registry.status(
            worker_id=started["worker_id"],
            run_id="run-real-observe",
            operation_id="operation-real-observe",
        )

    assert status["status"] == "completed"
    assert status["backend_compute_owner"] == "backend_process_worker"
    assert status["result_available"] is True
    assert "response" not in status
    adopted = registry.adopt_result(
        worker_id=started["worker_id"],
        run_id="run-real-observe",
        stage="screen_understanding",
        operation_id="operation-real-observe",
    )
    assert adopted["response"]["success"] is False
    assert adopted["response"]["error"]["code"] == "observe_screen_failed"
    assert Path(status["result_path"]).is_file()


def test_real_worker_process_is_terminated_by_operation_cancel(
    tmp_path: Path,
) -> None:
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_sleeping_process_factory,
    )
    started = registry.start(
        run_id="run-real-cancel",
        stage="precise_calibration",
        operation_id="operation-real-cancel",
        task_kind="vision_locate_target",
        payload={"goal": "not executed by the sleeping test process"},
    )

    cancelled = registry.cancel_by_operation(
        run_id="run-real-cancel",
        stage="precise_calibration",
        operation_id="operation-real-cancel",
    )

    assert cancelled["status"] == "cancelled"
    assert cancelled["backend_compute_termination"] == "terminated"
    process = registry._records[started["worker_id"]]["process"]
    assert process.is_alive() is False


def test_worker_dispatches_managed_hybrid_omni_with_internal_cancellation_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from threading import Event
    from app.learn import workflow_worker

    seen: dict[str, object] = {}

    def fake_run(payload, *, cancellation_event=None):
        seen["payload"] = payload
        seen["cancellation_event"] = cancellation_event
        return {"contract_version": "hybrid_omni_discovery_result_v1", "outcome": "completed"}

    monkeypatch.setattr(workflow_worker, "run_hybrid_omni_task", fake_run)
    cancellation_event = Event()
    response = execute_learning_stage_worker_task(
        "panel_learning_hybrid_omni_discovery",
        {"run_id": "run-hybrid"},
        cancellation_event=cancellation_event,
    )

    assert response["outcome"] == "completed"
    assert seen == {
        "payload": {"run_id": "run-hybrid"},
        "cancellation_event": cancellation_event,
    }


def test_worker_dispatches_managed_hybrid_fusion_without_model_acquisition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from threading import Event
    from app.learn import workflow_worker

    seen: dict[str, object] = {}

    def fake_run(payload, *, cancellation_event=None):
        seen["payload"] = payload
        seen["cancellation_event"] = cancellation_event
        return {"contract_version": "hybrid_fusion_result_v1", "candidates": []}

    monkeypatch.setattr(workflow_worker, "run_hybrid_fusion_task", fake_run)
    cancellation_event = Event()
    response = execute_learning_stage_worker_task(
        "panel_learning_hybrid_fusion",
        {"run_id": "run-fusion"},
        cancellation_event=cancellation_event,
    )

    assert response == {"contract_version": "hybrid_fusion_result_v1", "candidates": []}
    assert seen == {
        "payload": {"run_id": "run-fusion"},
        "cancellation_event": cancellation_event,
    }
    assert "panel_learning_hybrid_fusion" not in workflow_worker._MODEL_STAGE_BY_TASK_KIND


def test_panel_request_contract_accepts_managed_hybrid_fusion() -> None:
    from app.api.panel import PanelStartLearningStageWorkerRequest

    request = PanelStartLearningStageWorkerRequest.model_validate(
        {
            "run_id": "run-fusion",
            "expected_revision": 1,
            "stage": "fusion",
            "operation_id": "operation-fusion",
            "task_kind": "panel_learning_hybrid_fusion",
            "payload": {},
        }
    )

    assert request.task_kind == "panel_learning_hybrid_fusion"


def test_managed_hybrid_fusion_enforces_sealed_full_producer_boundary() -> None:
    from app.learn.recognition.uei.canonical import seal_immutable
    from tests.test_learn_hybrid_fusion import _inputs

    config, bundle, inventory, bindings = _inputs()
    payload = {
        "config": config,
        "capture_bundle": bundle,
        "omni_inventory": seal_immutable(inventory),
        "qwen_bindings": seal_immutable(bindings),
    }

    result = execute_learning_stage_worker_task(
        "panel_learning_hybrid_fusion",
        payload,
    )

    assert result["candidates"][0]["state"] == "BOUND"
    payload["omni_inventory"].pop("content_sha256")
    with pytest.raises(ValueError, match="content_sha256"):
        execute_learning_stage_worker_task(
            "panel_learning_hybrid_fusion",
            payload,
        )

    payload["omni_inventory"] = seal_immutable(inventory)
    bindings["context_ref"] = {
        "id": "hybrid-context/wrong",
        "content_sha256": "78" * 32,
    }
    payload["qwen_bindings"] = seal_immutable(bindings)
    with pytest.raises(ValueError, match="context_ref"):
        execute_learning_stage_worker_task(
            "panel_learning_hybrid_fusion",
            payload,
        )


def test_worker_dispatches_managed_hybrid_qwen_through_existing_model_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import workflow_worker

    events: list[object] = []
    lease = {
        "contract_version": "qwen_model_server_lease_v1",
        "lease_id": "lease-qwen",
        "owner_request_id": "learn-qwen-request",
        "profile_id": "qwen3_vl_8b_q4_k_m",
        "server_base_url": "http://127.0.0.1:13240/v1",
        "server_model_id": "qwen",
    }
    monkeypatch.setenv("AGENT_GUI_MODEL_REQUEST_ID", "learn-qwen-request")
    monkeypatch.setattr(
        workflow_worker,
        "validate_hybrid_qwen_task_payload",
        lambda payload: events.append(("validate", payload)),
    )

    profile = {
        "profile_id": "qwen3_vl_8b_q4_k_m",
        "provider_mode": "local_understanding",
    }
    monkeypatch.setattr(
        "app.core.gpu_resources.build_model_resource_preflight",
        lambda profile: events.append(("preflight", profile["profile_id"]))
        or {"resource_mode": "normal", "model_launch_allowed": True},
    )
    def acquire(**kwargs):
        validator = kwargs.pop("profile_validator")
        events.append(("acquire", kwargs))
        validator(profile)
        return lease

    monkeypatch.setattr(
        "app.core.model_server.ensure_and_acquire_qwen_model_lease",
        acquire,
    )
    monkeypatch.setattr(
        workflow_worker,
        "run_hybrid_qwen_task",
        lambda payload, cancellation_event=None, model_lease=None, include_cleanup_receipt=False: events.append(
            ("task", payload, cancellation_event, model_lease, include_cleanup_receipt)
        )
        or {"qwen_bindings": {"contract_version": "hybrid_qwen_bindings_v1"},
            "qwen_cleanup_receipt": {"contract_version": "hybrid_qwen_cleanup_receipt_v1"}},
    )

    response = execute_learning_stage_worker_task(
        "panel_learning_hybrid_qwen_binding",
        {"run_id": "run-qwen"},
    )

    assert response == {"contract_version": "hybrid_qwen_bindings_v1"}
    assert events == [
        ("validate", {"run_id": "run-qwen"}),
        (
            "acquire",
            {
                "stage": "understanding",
                "profile_id": None,
                "request_id": "learn-qwen-request",
                "wait_seconds": 180.0,
            },
        ),
        ("preflight", "qwen3_vl_8b_q4_k_m"),
        ("task", {"run_id": "run-qwen"}, None, lease, True),
    ]


def test_existing_managed_qwen_consumer_uses_shared_lease_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import workflow_worker

    events: list[object] = []
    lease = {"lease_id": "observe-lease", "owner_request_id": "observe-owner"}
    monkeypatch.setenv("AGENT_GUI_MODEL_REQUEST_ID", "observe-owner")
    monkeypatch.setattr(
        "app.core.model_server.ensure_and_acquire_qwen_model_lease",
        lambda **kwargs: events.append(("acquire", kwargs)) or lease,
    )
    monkeypatch.setattr(
        "app.core.model_server.ensure_model_server",
        lambda **kwargs: pytest.fail("managed Qwen consumer bypassed shared acquisition"),
    )
    monkeypatch.setattr(
        "app.core.model_server._mark_qwen_model_request_in_flight",
        lambda model_lease: events.append(("in_flight", model_lease)),
    )
    monkeypatch.setattr(
        "app.core.model_server.profile_for_stage",
        lambda *args, **kwargs: {
            "profile_id": "qwen3_vl_8b_q4_k_m",
            "provider_mode": "local_understanding",
        },
    )
    monkeypatch.setattr(
        "app.core.gpu_resources.build_model_resource_preflight",
        lambda profile: {"resource_mode": "normal", "model_launch_allowed": True},
    )
    monkeypatch.setattr(
        "app.core.model_server.reconcile_qwen_model_lease_failure",
        lambda **kwargs: events.append(("reconcile", kwargs))
        or {"status": "released"},
    )
    monkeypatch.setattr(
        workflow_worker,
        "run_recognition_task",
        lambda *args, **kwargs: {"ok": True},
    )
    monkeypatch.setattr(
        workflow_worker,
        "recognition_result_to_legacy_response",
        lambda value: value,
    )

    response = execute_learning_stage_worker_task(
        "panel_learning_recognition_trial",
        {"app_name": "test"},
    )

    assert response == {"ok": True}
    assert events[0][0] == "acquire"
    assert events[0][1]["request_id"] == "observe-owner"
    assert events[1] == ("in_flight", lease)
    assert events[-1] == (
        "reconcile",
        {
            "model_lease": lease,
            "compute_completed": False,
            "reason": "managed_consumer_completed",
        },
    )


def test_non_hybrid_degraded_result_preserves_unproven_provider_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import workflow_worker

    lease = {"lease_id": "observe-lease", "owner_request_id": "observe-owner"}
    reconciliations: list[dict[str, object]] = []
    monkeypatch.setattr(
        workflow_worker,
        "_ensure_learning_stage_model_ready",
        lambda *args, **kwargs: lease,
    )
    monkeypatch.setattr(
        workflow_worker,
        "run_recognition_task",
        lambda *args, **kwargs: {"status": "degraded", "success": False},
    )
    monkeypatch.setattr(
        workflow_worker,
        "recognition_result_to_legacy_response",
        lambda value: value,
    )
    monkeypatch.setattr(
        "app.core.model_server.release_managed_qwen_model_lease",
        lambda *args, **kwargs: pytest.fail(
            "unproven provider completion reached the terminal release helper"
        ),
    )
    monkeypatch.setattr(
        "app.core.model_server.reconcile_qwen_model_lease_failure",
        lambda **kwargs: reconciliations.append(kwargs)
        or {"status": "cancellation_acknowledged_pending"},
    )

    response = execute_learning_stage_worker_task(
        "panel_learning_recognition_trial",
        {"app_name": "test"},
    )

    assert response == {"status": "degraded", "success": False}
    assert reconciliations == [
        {
            "model_lease": lease,
            "compute_completed": False,
            "reason": "managed_consumer_completed",
        }
    ]


def test_observe_worker_binds_exact_lease_into_production_screen_reader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import workflow_worker

    lease = {"lease_id": "observe-lease", "owner_request_id": "observe-owner"}
    monkeypatch.setattr(
        workflow_worker,
        "_ensure_learning_stage_model_ready",
        lambda *args, **kwargs: lease,
    )
    monkeypatch.setattr(
        "app.core.model_server.reconcile_qwen_model_lease_failure",
        lambda **kwargs: {"status": "cancellation_acknowledged_pending"},
    )

    def observe(task, *, project_root, screen_reader):
        del task, project_root
        assert screen_reader.func is workflow_worker.read_screen
        assert screen_reader.keywords == {"managed_model_lease": lease}
        return {"outcome": "completed"}

    monkeypatch.setattr(workflow_worker, "run_observe_task", observe)
    monkeypatch.setattr(
        workflow_worker,
        "observe_result_to_legacy_response",
        lambda value: value,
    )

    response = execute_learning_stage_worker_task(
        "vision_observe_screen",
        {"capture_live": False, "image_path": "controlled.png"},
    )

    assert response == {"outcome": "completed"}


def test_worker_passes_exact_model_review_lease_to_production_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from functools import partial

    from app.learn import workflow_worker
    from app.learn.recognition import panel_review_pipeline
    from app.learn.workflow_contracts import LearningTaskResult

    lease = {
        "lease_id": "review-lease",
        "incarnation_id": "review-incarnation",
        "owner_request_id": "review-owner",
    }
    monkeypatch.setattr(
        workflow_worker,
        "_ensure_learning_stage_model_ready",
        lambda *args, **kwargs: lease,
    )
    monkeypatch.setattr(
        "app.core.model_server.reconcile_qwen_model_lease_failure",
        lambda **kwargs: {"status": "released"},
    )

    def production_runner(**kwargs):
        del kwargs
        return {}

    monkeypatch.setattr(
        panel_review_pipeline,
        "run_panel_learning_model_review_repair",
        production_runner,
    )

    def run_task(task_input, *, project_root, review_runner):
        del task_input, project_root
        assert isinstance(review_runner, partial)
        assert review_runner.func is production_runner
        assert review_runner.keywords == {"managed_model_lease": lease}
        return LearningTaskResult(
            outcome="completed",
            payload={"status": "ready_for_calibration", "calibration_permission": True},
        )

    monkeypatch.setattr(workflow_worker, "run_model_review_task", run_task)

    response = execute_learning_stage_worker_task(
        "panel_learning_model_review_repair",
        {
            "two_stage_report_path": "two-stage.json",
            "screenshot_path": "screen.png",
            "composite_overlay_path": "overlay.png",
        },
    )

    assert response["success"] is True


@pytest.mark.parametrize(
    "task_kind",
    [
        "panel_learning_recognition_trial",
        "panel_learning_two_stage_understanding",
        "panel_learning_model_review_repair",
        "panel_learning_hybrid_qwen_binding",
        "vision_observe_screen",
    ],
)
def test_every_managed_qwen_consumer_acquires_the_common_owner_domain(
    monkeypatch: pytest.MonkeyPatch,
    task_kind: str,
) -> None:
    from app.learn import workflow_worker

    calls = []
    lease = {"lease_id": f"lease-{task_kind}"}
    monkeypatch.setenv("AGENT_GUI_MODEL_REQUEST_ID", f"request-{task_kind}")

    def acquire(**kwargs):
        calls.append(kwargs)
        kwargs["profile_validator"](
            {
                "profile_id": "qwen3_vl_8b_q4_k_m",
                "provider_mode": "local_understanding",
            }
        )
        return lease

    monkeypatch.setattr(
        "app.core.model_server.ensure_and_acquire_qwen_model_lease",
        acquire,
    )
    monkeypatch.setattr(
        "app.core.model_server._mark_qwen_model_request_in_flight",
        lambda selected: calls.append({"marked_in_flight": selected}),
    )
    monkeypatch.setattr(
        "app.core.gpu_resources.build_model_resource_preflight",
        lambda profile: {"resource_mode": "normal", "model_launch_allowed": True},
    )

    acquired = workflow_worker._ensure_learning_stage_model_ready(
        task_kind,
        {},
    )

    assert acquired == lease
    assert calls[0]["request_id"] == f"request-{task_kind}"
    if task_kind == "panel_learning_hybrid_qwen_binding":
        assert len(calls) == 1
    else:
        assert calls[1] == {"marked_in_flight": lease}


def test_managed_qwen_rejects_unsealed_inventory_before_model_acquisition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import workflow_worker

    monkeypatch.setattr(
        workflow_worker,
        "_ensure_learning_stage_model_ready",
        lambda *args, **kwargs: pytest.fail("unsealed inventory reached model acquisition"),
    )
    with pytest.raises(ValueError, match="sealed Omni inventory"):
        execute_learning_stage_worker_task(
            "panel_learning_hybrid_qwen_binding",
            {"run_id": "run-qwen", "omni_inventory": {"content_sha256": "0" * 64}},
        )


@pytest.mark.parametrize(
    "task_kind",
    [
        "panel_learning_recognition_trial",
        "panel_learning_two_stage_understanding",
        "panel_learning_model_review_repair",
        "panel_learning_hybrid_qwen_binding",
        "vision_observe_screen",
    ],
)
def test_qwen_ensure_to_lease_publication_is_atomic_with_cancellation(
    monkeypatch: pytest.MonkeyPatch,
    task_kind: str,
) -> None:
    from app.learn import workflow_worker

    entered_ensure = Event()
    release_ensure = Event()
    published = Event()
    cancelled = Event()
    managed_event = workflow_worker._ManagedCancellationEvent(
        event=Event(),
        lock=Lock(),
    )
    profile = {"profile_id": "qwen", "provider_mode": "local_understanding"}
    monkeypatch.setenv("AGENT_GUI_MODEL_REQUEST_ID", "request-atomic")
    monkeypatch.setattr("app.core.model_server.profile_for_stage", lambda *args: profile)
    monkeypatch.setattr(
        "app.core.gpu_resources.build_model_resource_preflight",
        lambda selected: {"resource_mode": "normal", "model_launch_allowed": True},
    )

    def ensure(**kwargs):
        validator = kwargs.pop("profile_validator")
        validator(profile)
        entered_ensure.set()
        release_ensure.wait(timeout=2.0)
        published.set()
        return {"lease_id": "published"}

    monkeypatch.setattr(
        "app.core.model_server.ensure_and_acquire_qwen_model_lease",
        ensure,
    )
    monkeypatch.setattr(
        "app.core.model_server._mark_qwen_model_request_in_flight",
        lambda lease: None,
    )
    outcome: dict[str, object] = {}

    worker = Thread(
        target=lambda: outcome.update(
            lease=workflow_worker._ensure_learning_stage_model_ready(
                task_kind,
                {},
                cancellation_event=managed_event,
            )
        )
    )
    cancel = Thread(target=lambda: (managed_event.set(), cancelled.set()))
    worker.start()
    assert entered_ensure.wait(timeout=1.0) is True
    cancel.start()
    time.sleep(0.05)
    assert cancelled.is_set() is False
    release_ensure.set()
    worker.join(timeout=1.0)
    cancel.join(timeout=1.0)

    assert published.is_set() is True
    assert cancelled.is_set() is True
    assert managed_event.is_set() is True
    assert outcome["lease"] == {"lease_id": "published"}

    pre_cancelled = workflow_worker._ManagedCancellationEvent(event=Event(), lock=Lock())
    pre_cancelled.set()
    with pytest.raises(LearningStageWorkerError, match="cancelled before model acquisition"):
        workflow_worker._ensure_learning_stage_model_ready(
            task_kind,
            {},
            cancellation_event=pre_cancelled,
        )


def test_managed_hybrid_qwen_cancel_uses_existing_model_cancellation(
    tmp_path: Path,
) -> None:
    cancellation_calls: list[dict[str, object]] = []
    registry: LearningStageWorkerRegistry
    started: dict[str, object]

    def cancel_request(**kwargs):
        event = registry._records[str(started["worker_id"])]["cancellation_event"]
        assert event is not None
        assert event.is_set() is True
        cancellation_calls.append(kwargs)
        return {
            "contract_version": "model_request_cancellation_v1",
            "status": "terminated",
            "model_service_compute_termination": "terminated",
        }

    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
        model_request_cancel=cancel_request,
    )
    payload = {"run_id": "run-qwen", "omni_inventory": {"immutable": True}}
    started = registry.start(
        run_id="run-qwen",
        stage="screen_understanding",
        operation_id="operation-qwen",
        task_kind="panel_learning_hybrid_qwen_binding",
        payload=payload,
    )

    cancelled = registry.cancel_by_operation(
        run_id="run-qwen",
        stage="screen_understanding",
        operation_id="operation-qwen",
    )

    assert cancelled["status"] == "cancelled"
    assert cancelled["model_service_compute_termination"] == "terminated"
    assert cancellation_calls == [
        {
            "request_id": started["model_request_id"],
            "task_kind": "panel_learning_hybrid_qwen_binding",
            "payload": payload,
        }
    ]


def test_reloaded_hybrid_qwen_worker_cancels_durable_owner_before_wrapper_status(
    tmp_path: Path,
) -> None:
    first = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    started = first.start(
        run_id="run-reload-qwen",
        stage="screen_understanding",
        operation_id="operation-reload-qwen",
        task_kind="panel_learning_hybrid_qwen_binding",
        payload={"run_id": "run-reload-qwen", "omni_inventory": {"immutable": True}},
    )
    calls: list[dict[str, object]] = []
    reloaded = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
        model_request_cancel=lambda **kwargs: calls.append(kwargs) or {
            "contract_version": "model_request_cancellation_v1",
            "status": "cancellation_acknowledged_pending",
            "model_service_compute_termination": "cancellation_acknowledged_pending",
        },
    )

    cancelled = reloaded.cancel_by_operation(
        run_id="run-reload-qwen",
        stage="screen_understanding",
        operation_id="operation-reload-qwen",
    )

    assert calls == [{
        "request_id": started["model_request_id"],
        "task_kind": "panel_learning_hybrid_qwen_binding",
        "payload": {},
    }]
    assert cancelled["status"] == "cancellation_pending"
    assert cancelled["backend_compute_termination"] == "not_covered"
    assert cancelled["model_service_compute_termination"] == (
        "cancellation_acknowledged_pending"
    )
    assert cancelled["runtime_attached"] is False


def test_reloaded_hybrid_qwen_terminal_owner_result_does_not_claim_wrapper_exit(
    tmp_path: Path,
) -> None:
    first = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    first.start(
        run_id="run-reload-terminal",
        stage="screen_understanding",
        operation_id="operation-reload-terminal",
        task_kind="panel_learning_hybrid_qwen_binding",
        payload={"run_id": "run-reload-terminal", "omni_inventory": {"immutable": True}},
    )
    reloaded = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
        model_request_cancel=lambda **kwargs: {
            "contract_version": "model_request_cancellation_v1",
            "status": "request_not_active",
            "model_service_compute_termination": "request_not_active",
        },
    )

    cancelled = reloaded.cancel_by_operation(
        run_id="run-reload-terminal",
        stage="screen_understanding",
        operation_id="operation-reload-terminal",
    )

    assert cancelled["status"] == "detached_running"
    assert cancelled["backend_compute_termination"] == "not_covered"
    assert cancelled["model_service_compute_termination"] == "request_not_active"
    assert cancelled["runtime_attached"] is False


@pytest.mark.parametrize(
    "task_kind",
    [
        "panel_learning_recognition_trial",
        "panel_learning_two_stage_understanding",
        "panel_learning_model_review_repair",
        "panel_learning_hybrid_qwen_binding",
        "vision_observe_screen",
    ],
)
def test_managed_qwen_shared_no_endpoint_cancel_remains_attached_pending(
    tmp_path: Path,
    task_kind: str,
) -> None:
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
        model_request_cancel=lambda **kwargs: {
            "contract_version": "model_request_cancellation_v1",
            "status": "cancellation_acknowledged_pending",
            "model_service_compute_termination": "cancellation_acknowledged_pending",
            "provider_results": [{"server_termination": "owned_pending"}],
        },
    )
    started = registry.start(
        run_id="run-qwen",
        stage="screen_understanding",
        operation_id="operation-qwen-pending",
        task_kind=task_kind,
        payload={"run_id": "run-qwen", "omni_inventory": {"immutable": True}},
    )
    record = registry._records[str(started["worker_id"])]
    process = record["process"]

    pending = registry.cancel_by_operation(
        run_id="run-qwen",
        stage="screen_understanding",
        operation_id="operation-qwen-pending",
    )

    assert pending["status"] == "cancellation_pending"
    assert pending["backend_compute_termination"] == "pending"
    assert pending["model_service_compute_termination"] == "cancellation_acknowledged_pending"
    assert process.is_alive() is True
    assert process.terminated is False
    assert process.killed is False
    assert record["cancellation_event"].is_set() is True
    assert registry._active_by_operation[("run-qwen", "screen_understanding", "operation-qwen-pending")] == started["worker_id"]


def test_managed_qwen_pending_cancel_reconciles_after_worker_exit(
    tmp_path: Path,
) -> None:
    calls = 0

    def cancel_request(**kwargs):
        nonlocal calls
        del kwargs
        calls += 1
        if calls == 1:
            return {
                "contract_version": "model_request_cancellation_v1",
                "status": "cancellation_acknowledged_pending",
                "model_service_compute_termination": "cancellation_acknowledged_pending",
            }
        return {
            "contract_version": "model_request_cancellation_v1",
            "status": "terminated",
            "model_service_compute_termination": "terminated",
        }

    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
        model_request_cancel=cancel_request,
    )
    started = registry.start(
        run_id="run-qwen",
        stage="screen_understanding",
        operation_id="operation-qwen-reconcile",
        task_kind="panel_learning_hybrid_qwen_binding",
        payload={"run_id": "run-qwen", "omni_inventory": {"immutable": True}},
    )
    first = registry.cancel_by_operation(
        run_id="run-qwen",
        stage="screen_understanding",
        operation_id="operation-qwen-reconcile",
    )
    assert first["status"] == "cancellation_pending"
    record = registry._records[str(started["worker_id"])]
    record["process"].alive = False
    record["process"].exitcode = 1

    reconciled = registry.cancel_by_operation(
        run_id="run-qwen",
        stage="screen_understanding",
        operation_id="operation-qwen-reconcile",
    )
    assert reconciled["status"] == "cancelled"
    assert reconciled["model_service_compute_termination"] == "terminated"
    assert calls == 2


def test_managed_qwen_pending_cancel_real_finalizer_then_owner_retry_closes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import model_server

    lease_root = tmp_path / "leases"
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", lease_root)
    profile = {
        "profile_id": "qwen",
        "provider_mode": "local_understanding",
        "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
    }
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path / "workers",
        process_factory=_fake_process_factory,
        model_request_cancel=model_server.cancel_model_request,
    )
    started = registry.start(
        run_id="run-qwen",
        stage="screen_understanding",
        operation_id="operation-qwen-real-reconcile",
        task_kind="panel_learning_hybrid_qwen_binding",
        payload={"run_id": "run-qwen", "omni_inventory": {"immutable": True}},
    )
    readiness = {
        "started": True,
        "after": {
            "status": "running",
            "base_url": "http://127.0.0.1:13240/v1",
            "model_id": "qwen",
            "server_process_identity": {"pid": 9101, "create_time_ns": 111},
            "server_socket": {"host": "127.0.0.1", "port": 13240},
        },
    }
    monkeypatch.setattr(
        model_server,
        "_observe_qwen_server_binding",
        lambda selected, current: {
            "server_process_identity": dict(current["after"]["server_process_identity"]),
            "server_socket": dict(current["after"]["server_socket"]),
        },
    )
    owned = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id=str(started["model_request_id"]),
        readiness=readiness,
    )
    retained = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id="other-active-owner",
        readiness={**readiness, "started": False},
    )
    model_server._mark_qwen_model_request_in_flight(owned)
    monkeypatch.setattr(
        model_server,
        "_terminate_exact_qwen_server_process",
        lambda expected: pytest.fail("shared Qwen process was terminated"),
    )

    first = registry.cancel_by_operation(
        run_id="run-qwen",
        stage="screen_understanding",
        operation_id="operation-qwen-real-reconcile",
    )
    assert first["status"] == "cancellation_pending"

    finalized = model_server.reconcile_qwen_model_lease_failure(
        model_lease=owned,
        compute_completed=True,
        reason="worker_http_completed_after_cancel",
    )
    assert finalized["status"] == "released"
    assert model_server.qwen_model_lease_is_active(retained) is True
    record = registry._records[str(started["worker_id"])]
    record["process"].alive = False
    record["process"].exitcode = 1

    retry = registry.cancel_by_operation(
        run_id="run-qwen",
        stage="screen_understanding",
        operation_id="operation-qwen-real-reconcile",
    )
    assert retry["status"] == "cancelled"
    assert retry["model_service_compute_termination"] == "request_not_active"
    assert retry["model_request_cancellation"]["provider_results"][0]["owner_receipt"]["status"] == "finalized"


def test_hybrid_omni_registry_cancel_requires_valid_cooperative_cleanup_handshake(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import workflow_worker

    cancellation_calls: list[dict[str, object]] = []
    ref = {"id": "fixture/ref", "content_sha256": "12" * 32}

    def fake_run(payload, *, cancellation_event=None):
        del payload
        assert cancellation_event.is_set()
        return {
            "contract_version": "hybrid_omni_discovery_result_v1",
            "outcome": "failed",
            "provider_invocation_id": "invocation/" + "34" * 32,
            "provider_claim_status": "complete",
            "provider_status": "failed",
            "provider_reason_class": "runtime_provider_failed",
            "failure_reason": "runtime_cancelled",
            "provider_result_ref": ref,
            "provider_error_ref": ref,
            "provider_receipt_ref": ref,
            "cleanup_status": "clean",
        }

    monkeypatch.setattr(workflow_worker, "run_hybrid_omni_task", fake_run)
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_cooperative_fake_process_factory,
        model_request_cancel=lambda **kwargs: cancellation_calls.append(kwargs),
    )
    started = registry.start(
        run_id="run-hybrid",
        stage="screen_understanding",
        operation_id="operation-hybrid",
        task_kind="panel_learning_hybrid_omni_discovery",
        payload={"run_id": "run-hybrid"},
    )
    process = registry._records[started["worker_id"]]["process"]
    cancellation_event = process.args[5]

    cancelled = registry.cancel_by_operation(
        run_id="run-hybrid",
        stage="screen_understanding",
        operation_id="operation-hybrid",
    )

    assert cancellation_event.is_set()
    assert cancelled["status"] == "completed"
    assert cancelled["backend_compute_termination"] == "terminated"
    assert cancelled["model_service_compute_termination"] == "not_covered"
    assert cancelled["cooperative_cleanup"]["provider_claim_status"] == "complete"
    assert cancelled["cooperative_cleanup"]["cleanup_status"] == "clean"
    assert cancellation_calls == []
    assert process.terminated is False


def test_hybrid_omni_missing_handshake_times_out_without_relinquishing_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import workflow_worker

    monkeypatch.setattr(workflow_worker, "_HYBRID_OMNI_CLEANUP_WAIT_SECONDS", 0.01)
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    started = registry.start(
        run_id="run-timeout",
        stage="screen_understanding",
        operation_id="operation-timeout",
        task_kind="panel_learning_hybrid_omni_discovery",
        payload={"run_id": "run-timeout"},
    )
    record = registry._records[started["worker_id"]]
    process = record["process"]
    operation_key = ("run-timeout", "screen_understanding", "operation-timeout")

    with pytest.raises(LearningStageWorkerError, match="handshake timed out"):
        registry.cancel_by_operation(
            run_id="run-timeout",
            stage="screen_understanding",
            operation_id="operation-timeout",
        )

    assert record["status"] == "running"
    assert record["process"] is process
    assert process.is_alive()
    assert process.terminated is False
    assert process.killed is False
    assert registry._active_by_operation[operation_key] == started["worker_id"]

    recovered = _finish_fake_worker(
        registry,
        started,
        response={"outcome": "completed-after-timeout"},
    )
    assert recovered["status"] == "completed"
    assert recovered["result_available"] is True
    assert operation_key not in registry._active_by_operation

def test_real_managed_omni_cancel_waits_for_nested_cleanup_and_completed_claim(
    tmp_path: Path,
) -> None:
    from tests.test_learn_hybrid_omni_discovery import _facts

    facts = _facts(tmp_path)
    payload = dict(facts["payload"])
    payload.pop("project_root")
    worker_script = tmp_path / "controlled_omni_worker.py"
    worker_script.write_text(
        """from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument("--input-json", required=True)
parser.add_argument("--output-json", required=True)
args = parser.parse_args()
request = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
capture_path = Path(request["input_path"])
exchange = Path(args.input_json).parent
(capture_path.parent / "managed-exchange.txt").write_text(str(exchange), encoding="utf-8")
(capture_path.parent / "managed-worker.pid").write_text(str(__import__("os").getpid()), encoding="utf-8")
grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
(capture_path.parent / "managed-grandchild.pid").write_text(str(grandchild.pid), encoding="utf-8")
while True:
    time.sleep(1)
""",
        encoding="utf-8",
    )
    code_path = tmp_path / "controlled-code"
    weights_path = tmp_path / "controlled-weights"
    cache_path = tmp_path / "controlled-cache"
    for path in (code_path, weights_path, cache_path):
        path.mkdir()
    cleanup_entered = tmp_path / "cleanup-entered"
    cleanup_release = tmp_path / "cleanup-release"
    lease_root = tmp_path / "managed-leases"
    control = {
        "interpreter": sys.executable,
        "worker_script": str(worker_script),
        "code_path": str(code_path),
        "weights_path": str(weights_path),
        "cache_path": str(cache_path),
        "cleanup_entered": str(cleanup_entered),
        "cleanup_release": str(cleanup_release),
        "lease_root": str(lease_root),
        "project_root": str(tmp_path),
    }
    context = multiprocessing.get_context("spawn")

    def process_factory(*, target, args, name):
        return context.Process(
            target=_spawned_managed_omni_test_entry,
            args=(target, args, control),
            name=name,
        )

    registry = LearningStageWorkerRegistry(
        result_root=tmp_path / "worker-results",
        process_factory=process_factory,
    )
    started = registry.start(
        run_id="run-omni",
        stage="screen_understanding",
        operation_id="operation-omni",
        task_kind="panel_learning_hybrid_omni_discovery",
        payload=payload,
    )
    capture_dir = Path(facts["image"]).parent
    worker_pid_path = capture_dir / "managed-worker.pid"
    grandchild_pid_path = capture_dir / "managed-grandchild.pid"
    deadline = time.monotonic() + 15
    while (
        (not worker_pid_path.exists() or not grandchild_pid_path.exists())
        and time.monotonic() < deadline
    ):
        time.sleep(0.02)
    assert worker_pid_path.is_file() and grandchild_pid_path.is_file()
    worker_pid = int(worker_pid_path.read_text(encoding="utf-8"))
    grandchild_pid = int(grandchild_pid_path.read_text(encoding="utf-8"))

    cancellation: dict[str, object] = {}
    errors: list[BaseException] = []

    def cancel() -> None:
        try:
            cancellation.update(
                registry.cancel_by_operation(
                    run_id="run-omni",
                    stage="screen_understanding",
                    operation_id="operation-omni",
                )
            )
        except BaseException as exc:
            errors.append(exc)

    cancel_thread = Thread(target=cancel)
    cancel_thread.start()
    deadline = time.monotonic() + 15
    while not cleanup_entered.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert cleanup_entered.is_file()
    exchange_path = Path(
        (capture_dir / "managed-exchange.txt").read_text(encoding="utf-8")
    )
    try:
        time.sleep(3.3)
        assert cancel_thread.is_alive()
        assert registry._records[started["worker_id"]]["process"].is_alive()
        assert list(lease_root.glob("*.lock"))
        assert exchange_path.is_dir()
        claims = list(
            (tmp_path / "artifacts" / "uei-shadow-store" / ".shadow-runtime-claims").glob("*.json")
        )
        assert claims
        assert json.loads(claims[0].read_text(encoding="utf-8"))["state"] == "in_progress"
    finally:
        cleanup_release.write_text("release", encoding="utf-8")
        cancel_thread.join(timeout=20)

    assert not errors
    assert not cancel_thread.is_alive()
    assert cancellation["backend_compute_termination"] == "terminated"
    assert cancellation["cooperative_cleanup"]["cleanup_status"] == "clean"
    assert cancellation["cooperative_cleanup"]["provider_receipt_ref"]["id"].startswith("receipt/")
    assert cancellation["cooperative_cleanup"]["provider_error_ref"]["id"].startswith("error/")
    assert cancellation["cooperative_cleanup"]["provider_claim_status"] == "complete"
    assert not exchange_path.exists()
    assert list(lease_root.glob("*.lock")) == []
    deadline = time.monotonic() + 10
    while (
        (_pid_is_active(worker_pid) or _pid_is_active(grandchild_pid))
        and time.monotonic() < deadline
    ):
        time.sleep(0.05)
    assert not _pid_is_active(worker_pid)
    assert not _pid_is_active(grandchild_pid)
    claims = list(
        (tmp_path / "artifacts" / "uei-shadow-store" / ".shadow-runtime-claims").glob("*.json")
    )
    assert claims
    assert all(
        json.loads(path.read_text(encoding="utf-8"))["state"] == "complete"
        for path in claims
    )


def test_hybrid_registered_handler_chain_resolves_actual_callables() -> None:
    from app.learn import workflow_worker

    expected = {
        "panel_learning_hybrid_omni_discovery": "run_hybrid_omni_task",
        "panel_learning_hybrid_qwen_binding": "run_hybrid_qwen_task",
        "panel_learning_hybrid_fusion": "run_hybrid_fusion_task",
        "panel_learning_calibration_sequence": "run_learning_calibration_sequence",
        "panel_learning_hybrid_review_projection": "run_hybrid_review_projection_task",
    }
    assert set(workflow_worker.HYBRID_STAGE_HANDLER_REGISTRY) == set(expected)
    for task_kind, name in expected.items():
        assert workflow_worker.resolve_hybrid_stage_handler(task_kind).__name__ == name


@pytest.mark.parametrize(
    ("task_kind", "required_receipt"),
    [
        ("panel_learning_hybrid_qwen_binding", "omni_cleanup_receipt"),
        ("panel_learning_calibration_sequence", "qwen_gpu_cleanup_receipt"),
        ("panel_learning_hybrid_review_projection", "vista_cleanup_receipt"),
    ],
)
def test_hybrid_next_provider_guard_runs_before_handler_or_model_acquisition(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    task_kind: str,
    required_receipt: str,
) -> None:
    from app.learn import workflow_worker

    calls: list[str] = []
    monkeypatch.setattr(
        workflow_worker,
        "validate_hybrid_qwen_task_payload",
        lambda payload: calls.append("validate"),
    )
    monkeypatch.setattr(
        workflow_worker,
        "_ensure_learning_stage_model_ready",
        lambda *args, **kwargs: calls.append("model") or None,
    )
    handler = workflow_worker.resolve_hybrid_stage_handler(task_kind)
    monkeypatch.setattr(
        workflow_worker,
        handler.__name__,
        lambda *args, **kwargs: calls.append("handler") or {},
        raising=False,
    )
    run_id = "run-guard"
    response = workflow_worker.execute_learning_stage_worker_task(
        task_kind,
        {
            "learning_pipeline_mode": "hybrid_v1_1",
            "_hybrid_orchestration": {"run_id": run_id},
            "_hybrid_supervisor": _hybrid_supervisor(
                run_id=run_id,
                task_kind=task_kind,
                lease_path=tmp_path / "vista-lease.json",
            ),
        },
    )
    assert response["outcome"] == "failed"
    assert required_receipt in response["result"]["failure_reason"]
    assert "model" not in calls
    assert "handler" not in calls


def test_hybrid_cross_run_cleanup_receipt_replay_rejects_before_acquisition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import workflow_worker

    task_kind = "panel_learning_hybrid_qwen_binding"
    active_run = "run-active-lineage"
    replayed_lineage = _hybrid_lineage(
        run_id="run-replayed-lineage",
        task_kind=task_kind,
    )
    omni_inventory = {"contract_version": "hybrid_omni_inventory_v1", "items": []}
    capture_bundle = {"contract_version": "hybrid_capture_bundle_v1", "items": []}
    replayed_receipt = _hybrid_cleanup_receipt(
        "omni",
        lineage=replayed_lineage,
        predecessor=capture_bundle,
        provider_result=omni_inventory,
    )
    calls: list[str] = []
    monkeypatch.setattr(
        workflow_worker,
        "_ensure_learning_stage_model_ready",
        lambda *args, **kwargs: calls.append("model"),
    )
    monkeypatch.setattr(
        workflow_worker,
        "run_hybrid_qwen_task",
        lambda *args, **kwargs: calls.append("handler") or {},
    )

    response = workflow_worker.execute_learning_stage_worker_task(
        task_kind,
        {
            "learning_pipeline_mode": "hybrid_v1_1",
            "_hybrid_orchestration": {
                "omni_inventory": omni_inventory,
                "omni_cleanup_receipt": replayed_receipt,
            },
            "_hybrid_supervisor": _hybrid_supervisor(
                run_id=active_run,
                task_kind=task_kind,
                lease_path=tmp_path / "unused-vista-lease.json",
            ),
        },
    )

    assert response["outcome"] == "failed"
    assert "lineage mismatch" in response["result"]["failure_reason"]
    assert calls == []


def test_hybrid_omni_completion_publishes_verified_cleanup_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.learn import workflow_worker
    from app.learn.recognition.uei.canonical import content_sha256

    run_id = "run-omni-clean"
    task_kind = "panel_learning_hybrid_omni_discovery"
    capture_ref = {"id": "capture/omni-clean", "content_sha256": "2" * 64}
    inventory = {"contract_version": "hybrid_omni_inventory_v1", "items": []}
    monkeypatch.setattr(workflow_worker, "_ensure_learning_stage_model_ready", lambda *a, **k: None)
    monkeypatch.setattr(
        workflow_worker,
        "run_hybrid_omni_task",
        lambda *a, **k: {
            "contract_version": "hybrid_omni_discovery_result_v1",
            "outcome": "completed",
            "inventory": inventory,
            "provider_claim_status": "complete",
            "provider_status": "completed",
            "provider_receipt_ref": {"id": "receipt/omni", "content_sha256": "1" * 64},
            "cleanup_status": "clean",
        },
    )
    monkeypatch.setattr(
        workflow_worker,
        "_observe_hybrid_omni_cleanup",
        lambda result, **kwargs: _hybrid_cleanup_inventory(
            "omni",
            lineage=kwargs["lineage"],
            predecessor_sha256=kwargs["predecessor_sha256"],
            provider_result_sha256=content_sha256(inventory),
        ),
    )
    response = workflow_worker.execute_learning_stage_worker_task(
        task_kind,
        {
            "learning_pipeline_mode": "hybrid_v1_1",
            "hybrid_capture_bundle_ref": capture_ref,
            "_hybrid_orchestration": {"run_id": run_id},
            "_hybrid_supervisor": _hybrid_supervisor(
                run_id=run_id,
                task_kind=task_kind,
                lease_path=tmp_path / "vista-lease.json",
            ),
        },
    )
    receipt = response["orchestration"]["omni_cleanup_receipt"]
    assert receipt["provider"] == "omni"
    assert receipt["cleanup_status"] == "verified"


def test_hybrid_vista_completion_releases_before_review_receipt(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.core import model_server
    from app.learn import workflow_worker
    from app.learn.recognition.uei.canonical import content_sha256

    run_id = "run-vista-clean"
    task_kind = "panel_learning_calibration_sequence"
    lineage = _hybrid_lineage(run_id=run_id, task_kind=task_kind)
    omni_inventory = {"contract_version": "hybrid_omni_inventory_v1", "items": []}
    qwen_bindings = {"contract_version": "hybrid_qwen_bindings_v1", "items": []}
    fusion_result = {"contract_version": "hybrid_fusion_result_v1", "items": []}
    qwen_receipt = _hybrid_cleanup_receipt(
        "qwen",
        lineage=lineage,
        predecessor=omni_inventory,
        provider_result=qwen_bindings,
    )
    vista_lease = {
        "contract_version": "hybrid_vista_model_lease_v2",
        "provider": "vista",
        "incarnation_id": "vista-incarnation",
        "profile": {"profile_id": "vista"},
        "process_identities": [{"pid": 4200, "create_time_ns": 100_000_000_000}],
    }
    monkeypatch.setattr(
        workflow_worker,
        "_ensure_learning_stage_model_ready",
        lambda *a, **k: vista_lease,
    )
    monkeypatch.setattr(
        workflow_worker, "_mark_supervised_vista_released", lambda *a, **k: None
    )
    monkeypatch.setattr(
        workflow_worker,
        "run_learning_calibration_sequence",
        lambda *a, **k: {
            "contract_version": "learning_calibration_sequence_result_v1",
            "calibration_sequence": {
                "contract_version": "learning_calibration_sequence_v1",
                "requests": [],
            },
        },
    )
    monkeypatch.setattr(
        model_server,
        "release_hybrid_vista_model_lease",
        lambda lease, **kwargs: _hybrid_cleanup_inventory(
            "vista",
            lineage=kwargs["lineage"],
            predecessor_sha256=kwargs["predecessor_sha256"],
            provider_result_sha256=kwargs["provider_result_sha256"],
        ),
    )
    response = workflow_worker.execute_learning_stage_worker_task(
        "panel_learning_calibration_sequence",
        {
            "learning_pipeline_mode": "hybrid_v1_1",
            "_hybrid_orchestration": {
                "run_id": run_id,
                "qwen_bindings": qwen_bindings,
                "fusion_result": fusion_result,
                "qwen_gpu_cleanup_receipt": qwen_receipt,
            },
            "_hybrid_supervisor": _hybrid_supervisor(
                run_id=run_id,
                task_kind=task_kind,
                lease_path=tmp_path / "vista-lease.json",
            ),
        },
    )
    receipt = response["orchestration"]["vista_cleanup_receipt"]
    assert receipt["provider"] == "vista"
    assert receipt["cleanup_status"] == "verified"
    assert response["lifecycle_evidence"]["vista_cleanup_receipt"] == receipt


def test_hybrid_vista_handler_failure_still_releases_exact_lease(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.core import model_server
    from app.learn import workflow_worker
    from app.learn.recognition.uei.canonical import content_sha256

    run_id = "run-vista-failure"
    task_kind = "panel_learning_calibration_sequence"
    lineage = _hybrid_lineage(run_id=run_id, task_kind=task_kind)
    omni_inventory = {"contract_version": "hybrid_omni_inventory_v1", "items": []}
    qwen_bindings = {"contract_version": "hybrid_qwen_bindings_v1", "items": []}
    fusion_result = {"contract_version": "hybrid_fusion_result_v1", "items": []}
    qwen_receipt = _hybrid_cleanup_receipt(
        "qwen",
        lineage=lineage,
        predecessor=omni_inventory,
        provider_result=qwen_bindings,
    )
    supervisor = _hybrid_supervisor(
        run_id=run_id,
        task_kind=task_kind,
        lease_path=tmp_path / "vista-lease.json",
    )
    vista_lease = {
        "contract_version": "hybrid_vista_model_lease_v2",
        "provider": "vista",
        "incarnation_id": "vista-failure-incarnation",
        "profile": {"profile_id": "vista"},
        "process_identities": [{"pid": 4201, "create_time_ns": 100_000_000_000}],
        "process_scope_name": supervisor["process_scope_name"],
    }
    workflow_worker._publish_supervised_vista_acquiring(
        supervisor,
        predecessor_sha256=content_sha256(fusion_result),
        profile_id="vista",
    )
    monkeypatch.setattr(
        workflow_worker,
        "_ensure_learning_stage_model_ready",
        lambda *a, **k: (
            workflow_worker._publish_supervised_vista_lease(
                supervisor,
                vista_lease,
                predecessor_sha256=content_sha256(fusion_result),
            )
            or vista_lease
        ),
    )
    monkeypatch.setattr(
        workflow_worker,
        "run_learning_calibration_sequence",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("vista handler failed")),
    )
    monkeypatch.setattr(
        model_server,
        "release_hybrid_vista_model_lease",
        lambda lease, **kwargs: _hybrid_cleanup_inventory(
            "vista",
            lineage=kwargs["lineage"],
            predecessor_sha256=kwargs["predecessor_sha256"],
            provider_result_sha256=kwargs["provider_result_sha256"],
            termination_reason="failure_recovery",
        ),
    )
    response = workflow_worker.execute_learning_stage_worker_task(
        "panel_learning_calibration_sequence",
        {
            "learning_pipeline_mode": "hybrid_v1_1",
            "_hybrid_orchestration": {
                "run_id": run_id,
                "qwen_bindings": qwen_bindings,
                "fusion_result": fusion_result,
                "qwen_gpu_cleanup_receipt": qwen_receipt,
            },
            "_hybrid_supervisor": supervisor,
        },
    )
    assert response["outcome"] == "failed"
    assert response["result"]["failure_reason"] == "vista handler failed"
    assert response["result"]["model_lifecycle"]["vista_cleanup_receipt"]["cleanup_status"] == "verified"


def test_hybrid_vista_registry_cancel_waits_for_cooperative_cleanup_without_termination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import workflow_worker

    run_id = "run-vista-cancel"
    operation_id = "operation-vista-cancel"
    task_kind = "panel_learning_calibration_sequence"
    lineage = _hybrid_lineage(
        run_id=run_id,
        task_kind=task_kind,
        operation_id=operation_id,
    )
    omni_inventory = {"contract_version": "hybrid_omni_inventory_v1", "items": []}
    qwen_bindings = {"contract_version": "hybrid_qwen_bindings_v1", "items": []}
    fusion_result = {"contract_version": "hybrid_fusion_result_v1", "items": []}
    qwen_receipt = _hybrid_cleanup_receipt(
        "qwen",
        lineage=lineage,
        predecessor=omni_inventory,
        provider_result=qwen_bindings,
    )
    monkeypatch.setattr(
        workflow_worker,
        "_ensure_learning_stage_model_ready",
        lambda *a, **k: None,
    )

    def cancelled_handler(*args, **kwargs):
        raise workflow_worker.LearningStageWorkerError(
            "VISTA cancelled before model acquisition"
        )

    monkeypatch.setattr(
        workflow_worker,
        "run_learning_calibration_sequence",
        cancelled_handler,
    )
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_cooperative_fake_process_factory,
        model_request_cancel=lambda **kwargs: {
            "contract_version": "model_request_cancellation_v1",
            "status": "request_not_active",
            "model_service_compute_termination": "request_not_active",
        },
    )
    started = registry.start(
        run_id=run_id,
        stage="screen_understanding",
        operation_id=operation_id,
        task_kind=task_kind,
        authoritative_workflow_revision=7,
        payload={
            "learning_pipeline_mode": "hybrid_v1_1",
            "workflow_revision": 7,
            "_hybrid_orchestration": {
                "qwen_bindings": qwen_bindings,
                "fusion_result": fusion_result,
                "qwen_gpu_cleanup_receipt": qwen_receipt,
            },
        },
    )
    process = registry._records[started["worker_id"]]["process"]

    cancelled = registry.cancel_by_operation(
        run_id=run_id,
        stage="screen_understanding",
        operation_id=operation_id,
    )

    assert cancelled["backend_compute_termination"] == "terminated"
    assert cancelled["cooperative_cleanup"]["cleanup_status"] == "not_acquired"
    assert process.terminated is False
    assert process.killed is False


def test_hybrid_vista_outer_worker_death_remains_nonterminal_until_exact_lease_is_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import model_server
    from app.learn import workflow_worker

    run_id = "run-vista-outer-death"
    operation_id = "operation-vista-outer-death"
    task_kind = "panel_learning_calibration_sequence"
    lineage = _hybrid_lineage(
        run_id=run_id,
        task_kind=task_kind,
        operation_id=operation_id,
    )
    omni_inventory = {"contract_version": "hybrid_omni_inventory_v1", "items": []}
    qwen_bindings = {"contract_version": "hybrid_qwen_bindings_v1", "items": []}
    fusion_result = {"contract_version": "hybrid_fusion_result_v1", "items": []}
    qwen_receipt = _hybrid_cleanup_receipt(
        "qwen",
        lineage=lineage,
        predecessor=omni_inventory,
        provider_result=qwen_bindings,
    )
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    started = registry.start(
        run_id=run_id,
        stage="screen_understanding",
        operation_id=operation_id,
        task_kind=task_kind,
        authoritative_workflow_revision=7,
        payload={
            "learning_pipeline_mode": "hybrid_v1_1",
            "workflow_revision": 7,
            "_hybrid_orchestration": {
                "qwen_bindings": qwen_bindings,
                "fusion_result": fusion_result,
                "qwen_gpu_cleanup_receipt": qwen_receipt,
            },
        },
    )
    record = registry._records[started["worker_id"]]
    supervisor = record["process"].args[2]["_hybrid_supervisor"]
    model_lease = {
        "contract_version": "hybrid_vista_model_lease_v2",
        "provider": "vista",
        "incarnation_id": "vista-outer-death-incarnation",
        "profile": {"profile_id": "vista"},
        "process_identities": [
            {"pid": 6123, "create_time_ns": 612_300_000_000}
        ],
        "process_scope_name": supervisor["process_scope_name"],
    }
    from app.learn.recognition.uei.canonical import content_sha256

    workflow_worker._publish_supervised_vista_lease(
        supervisor,
        model_lease,
        predecessor_sha256=content_sha256(fusion_result),
    )
    record["process"].alive = False
    record["process"].exitcode = -9
    observations = [
        _hybrid_cleanup_inventory(
            "vista",
            lineage=lineage,
            predecessor_sha256=content_sha256(fusion_result),
            provider_result_sha256="f" * 64,
        ),
        _hybrid_cleanup_inventory(
            "vista",
            lineage=lineage,
            predecessor_sha256=content_sha256(fusion_result),
            provider_result_sha256="f" * 64,
        ),
    ]
    observations[0]["release_status"] = "failed"
    observations[0]["provider_processes_after"] = [
        deepcopy(model_lease["process_identities"][0])
    ]
    observations[0]["source_cleanup_evidence"] = {"status": "failed"}

    def release_observed(lease, **kwargs):
        observation = observations.pop(0)
        observation["provider_result_sha256"] = kwargs["provider_result_sha256"]
        return observation

    monkeypatch.setattr(
        model_server,
        "release_hybrid_vista_model_lease",
        release_observed,
    )
    from app.learn.hybrid import windows_process_scope

    real_scope_observer = windows_process_scope.observe_process_scope_cleanup
    scope_attempts = 0

    def fail_closed_once(*args, **kwargs):
        nonlocal scope_attempts
        scope_attempts += 1
        if scope_attempts == 1:
            return {
                "contract_version": "hybrid_windows_process_scope_v1",
                "scope_name": args[0],
                "cleanup_status": "indeterminate",
            }
        return real_scope_observer(*args, **kwargs)

    monkeypatch.setattr(
        windows_process_scope, "observe_process_scope_cleanup", fail_closed_once
    )

    pending = registry.status(
        worker_id=started["worker_id"],
        run_id=run_id,
        operation_id=operation_id,
    )
    assert pending["status"] == "recovery_required"
    assert registry._records[started["worker_id"]].get("worker_result") is None

    recovered_registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    terminal = recovered_registry.status(
        worker_id=started["worker_id"],
        run_id=run_id,
        operation_id=operation_id,
    )
    assert terminal["status"] == "failed"
    lease_document = json.loads(
        Path(record["provider_lease_path"]).read_text(encoding="utf-8")
    )
    assert lease_document["state"] in {"released", "recovered"}


def test_hybrid_vista_outer_worker_death_during_acquiring_reconciles_exact_job(
    tmp_path: Path,
) -> None:
    from app.learn.hybrid.windows_process_scope import spawn_process_in_scope

    run_id = "run-vista-acquiring-death"
    operation_id = "operation-vista-acquiring-death"
    task_kind = "panel_learning_calibration_sequence"
    lineage = _hybrid_lineage(
        run_id=run_id,
        task_kind=task_kind,
        operation_id=operation_id,
    )
    omni_inventory = {"contract_version": "hybrid_omni_inventory_v1", "items": []}
    qwen_bindings = {"contract_version": "hybrid_qwen_bindings_v1", "items": []}
    fusion_result = {"contract_version": "hybrid_fusion_result_v1", "items": []}
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    started = registry.start(
        run_id=run_id,
        stage="screen_understanding",
        operation_id=operation_id,
        task_kind=task_kind,
        authoritative_workflow_revision=7,
        payload={
            "learning_pipeline_mode": "hybrid_v1_1",
            "workflow_revision": 7,
            "_hybrid_orchestration": {
                "qwen_bindings": qwen_bindings,
                "fusion_result": fusion_result,
                "qwen_gpu_cleanup_receipt": _hybrid_cleanup_receipt(
                    "qwen",
                    lineage=lineage,
                    predecessor=omni_inventory,
                    provider_result=qwen_bindings,
                ),
            },
        },
    )
    record = registry._records[started["worker_id"]]
    helper = spawn_process_in_scope(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        scope_name=record["provider_scope_name"],
        cwd=tmp_path,
    )
    record["process"].alive = False
    record["process"].exitcode = -9
    try:
        terminal = registry.status(
            worker_id=started["worker_id"],
            run_id=run_id,
            operation_id=operation_id,
        )
    finally:
        scope = record.get("provider_scope")
        if scope is not None:
            scope.close()

    assert terminal["status"] == "failed"
    assert helper.poll() is not None
    helper.close()
    reconciliation = terminal["supervisor_reconciliation"]
    assert reconciliation["status"] == "verified"
    assert helper.pid in reconciliation["scope_cleanup_evidence"][
        "observed_member_pids_before"
    ]
    lease_document = json.loads(
        Path(record["provider_lease_path"]).read_text(encoding="utf-8")
    )
    assert lease_document["state"] == "recovered"


def test_hybrid_qwen_outer_worker_death_reconciles_exact_job_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid.windows_process_scope import spawn_process_in_scope

    run_id = "run-qwen-owner-death"
    operation_id = "operation-qwen-owner-death"
    task_kind = "panel_learning_hybrid_qwen_binding"
    lineage = _hybrid_lineage(
        run_id=run_id,
        task_kind=task_kind,
        operation_id=operation_id,
    )
    capture_bundle = {"contract_version": "hybrid_capture_bundle_v1", "items": []}
    omni_inventory = {"contract_version": "hybrid_omni_inventory_v1", "items": []}
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    started = registry.start(
        run_id=run_id,
        stage="screen_understanding",
        operation_id=operation_id,
        task_kind=task_kind,
        authoritative_workflow_revision=7,
        payload={
            "learning_pipeline_mode": "hybrid_v1_1",
            "workflow_revision": 7,
            "_hybrid_orchestration": {
                "omni_inventory": omni_inventory,
                "omni_cleanup_receipt": _hybrid_cleanup_receipt(
                    "omni",
                    lineage=lineage,
                    predecessor=capture_bundle,
                    provider_result=omni_inventory,
                ),
            },
        },
    )
    record = registry._records[started["worker_id"]]
    from app.core import model_server

    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen-leases")
    helper = spawn_process_in_scope(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        scope_name=record["provider_scope_name"],
        cwd=tmp_path,
    )
    profile = {
        "profile_id": "qwen-worker-death",
        "endpoint": "http://127.0.0.1:54323/v1/chat/completions",
        "pid_file": str(tmp_path / "qwen-worker-death.pid"),
    }
    readiness = {
        "started": True,
        "after": {
            "status": "running",
            "base_url": "http://127.0.0.1:54323/v1",
            "model_id": "qwen",
            "server_process_identity": helper.process_identity,
            "server_socket": {"host": "127.0.0.1", "port": 54323},
        },
    }
    monkeypatch.setenv("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", record["provider_scope_name"])
    monkeypatch.setenv(
        "AGENT_GUI_HYBRID_PROVIDER_RUNTIME_PATH", record["provider_runtime_path"]
    )
    monkeypatch.setenv(
        "AGENT_GUI_HYBRID_LINEAGE_JSON", json.dumps(record["provider_lineage"])
    )
    monkeypatch.setattr(
        model_server,
        "check_model_server",
        lambda selected, timeout=1.0: {"status": "unreachable"},
    )
    monkeypatch.setattr(
        model_server,
        "_observe_qwen_server_binding",
        lambda selected, observed: {
            "base_url": observed["after"]["base_url"],
            "model_id": observed["after"]["model_id"],
            "server_process_identity": observed["after"]["server_process_identity"],
            "server_socket": observed["after"]["server_socket"],
        },
    )
    lease = model_server.acquire_qwen_model_lease(
        profile=profile,
        request_id=record["model_request_id"],
        readiness=readiness,
    )
    record["process"].alive = False
    record["process"].exitcode = -9
    try:
        terminal = registry.status(
            worker_id=started["worker_id"],
            run_id=run_id,
            operation_id=operation_id,
        )
    finally:
        scope = record.get("provider_scope")
        if scope is not None:
            scope.close()

    assert terminal["status"] == "failed"
    assert helper.poll() is not None
    helper.close()
    evidence = terminal["supervisor_reconciliation"]["scope_cleanup_evidence"]
    assert evidence["cleanup_status"] == "verified"
    assert model_server.qwen_model_lease_is_active(lease) is False
    assert model_server._load_qwen_owner_tombstone(
        record["model_request_id"]
    )["lease_id"] == lease["lease_id"]
    release_result = terminal["supervisor_reconciliation"][
        "provider_cleanup_evidence"
    ]["owner_tombstone"]["release_result"]
    assert helper.pid in release_result["hybrid_process_scope_acquisition"][
        "member_pids"
    ]
    assert release_result["release"]["status"] == "proven_absent"
    recovered = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    assert recovered.status(
        worker_id=started["worker_id"],
        run_id=run_id,
        operation_id=operation_id,
    )["status"] == "failed"


def test_hybrid_omni_outer_worker_death_reconciles_exact_job_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid.windows_process_scope import spawn_process_in_scope

    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    started = registry.start(
        run_id="run-omni-owner-death",
        stage="screen_understanding",
        operation_id="operation-omni-owner-death",
        task_kind="panel_learning_hybrid_omni_discovery",
        authoritative_workflow_revision=7,
        payload={
            "learning_pipeline_mode": "hybrid_v1_1",
            "workflow_revision": 7,
            "hybrid_capture_bundle_ref": {
                "id": "hybrid-capture/omni-owner-death",
                "content_sha256": "a" * 64,
            },
        },
    )
    record = registry._records[started["worker_id"]]
    from app.learn.recognition.uei import omniparser_shadow_adapter as adapter_module

    monkeypatch.setattr(
        adapter_module, "OMNI_CLEANUP_OBSERVATION_ROOT", tmp_path / "omni-cleanup"
    )
    manager = adapter_module.ProcessResourceLeaseManager(root=tmp_path / "omni-leases")
    lease = manager("gpu_vision")
    assert lease is not None
    adapter_module.persist_omniparser_invocation_owner(
        Path(record["provider_runtime_path"]),
        invocation_id="invocation/outer-worker-death",
        resource_group="gpu_vision",
        resource_lease=lease,
        lineage=record["provider_lineage"],
        process_scope_name=record["provider_scope_name"],
    )
    helper = spawn_process_in_scope(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        scope_name=record["provider_scope_name"],
        cwd=tmp_path,
    )
    adapter_module.publish_omniparser_process_identity(
        Path(record["provider_runtime_path"]),
        process_identity=helper.process_identity,
    )
    record["process"].alive = False
    record["process"].exitcode = -9
    try:
        terminal = registry.status(
            worker_id=started["worker_id"],
            run_id="run-omni-owner-death",
            operation_id="operation-omni-owner-death",
        )
    finally:
        scope = record.get("provider_scope")
        if scope is not None:
            scope.close()

    assert terminal["status"] == "failed"
    assert helper.poll() is not None
    helper.close()
    evidence = terminal["supervisor_reconciliation"]["scope_cleanup_evidence"]
    assert helper.pid in evidence["observed_member_pids_before"]
    assert evidence["cleanup_status"] == "verified"
    assert list((tmp_path / "omni-leases").glob("*.lock")) == []
    recovered = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    assert recovered.status(
        worker_id=started["worker_id"],
        run_id="run-omni-owner-death",
        operation_id="operation-omni-owner-death",
    )["status"] == "failed"


@pytest.mark.parametrize("journal_mutation", ["scope_substitution", "missing_owner"])
def test_recovered_hybrid_journal_scope_substitution_never_opens_unrelated_job(
    tmp_path: Path,
    journal_mutation: str,
) -> None:
    from app.learn.hybrid.windows_process_scope import (
        WindowsProcessScope,
        process_scope_name,
        spawn_process_in_scope,
    )

    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    started = registry.start(
        run_id="run-journal-owner",
        stage="screen_understanding",
        operation_id="operation-journal-owner",
        task_kind="panel_learning_hybrid_omni_discovery",
        authoritative_workflow_revision=7,
        payload={
            "learning_pipeline_mode": "hybrid_v1_1",
            "workflow_revision": 7,
            "hybrid_capture_bundle_ref": {
                "id": "hybrid-capture/journal-owner",
                "content_sha256": "b" * 64,
            },
        },
    )
    record = registry._records[started["worker_id"]]
    unrelated_lineage = {
        "run_id": "run-unrelated",
        "workflow_revision": 99,
        "operation_id": "operation-unrelated",
        "stage": "screen_understanding",
        "stage_execution_id": "unrelated-execution",
    }
    unrelated_name = process_scope_name(unrelated_lineage, "omni")
    unrelated_scope = WindowsProcessScope(unrelated_name, create=True)
    unrelated = spawn_process_in_scope(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        scope_name=unrelated_name,
        cwd=tmp_path,
    )
    journal_path = Path(record["journal_path"])
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    if journal_mutation == "scope_substitution":
        journal["provider_scope_name"] = unrelated_name
    else:
        journal.pop("provider_owner_file")
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    original_scope = record.get("provider_scope")
    if original_scope is not None:
        original_scope.close()
        record["provider_scope"] = None
    try:
        recovered = LearningStageWorkerRegistry(
            result_root=tmp_path,
            process_factory=_fake_process_factory,
        )
        status = recovered.status(
            worker_id=started["worker_id"],
            run_id="run-journal-owner",
            operation_id="operation-journal-owner",
        )
        assert status["status"] == "recovery_required"
        assert status["provider_recovery_blocked"] is True
        assert unrelated.poll() is None
    finally:
        unrelated_scope.terminate()
        unrelated.wait(10)
        unrelated.close()
        unrelated_scope.close()


def _benchmark_launch_owner_state(
    tmp_path: Path,
    *,
    phase: str,
) -> tuple[
    LearningStageWorkerRegistry,
    BenchmarkWorkerSupervisionRoot,
    LearningWorkflowRunStore,
    dict[str, object],
    dict[str, object],
]:
    from app.learn import workflow_worker as worker_module
    from app.learn.recognition.uei.canonical import seal_immutable
    import psutil

    registry, root, store, _source, reservation, anchor = (
        _benchmark_registry_fixture(tmp_path)
    )
    registry.confirm_prepared_benchmark_worker_anchor(
        reservation_ref={"content_sha256": reservation["content_sha256"]},
        expected_operation_anchor=anchor,
        supervision_root=root,
    )
    anchored = registry.inspect_prepared_benchmark_worker_identity(
        run_id=str(reservation["run_id"]),
        stage=str(reservation["stage"]),
        operation_id=str(reservation["operation_id"]),
        supervision_root=root,
    )
    if phase == "anchored":
        return registry, root, store, reservation, anchor

    supervisor_identity = {
        "pid": os.getpid(),
        "create_time_ns": int(
            round(psutil.Process().create_time() * 1_000_000_000)
        ),
    }
    supervision = compose_benchmark_worker_supervision_v1(
        supervision_root=root,
        reservation=reservation,
        expected_operation_anchor=anchor,
        supervisor_process_identity=supervisor_identity,
        startup_gate_timeout_ms=15_000,
    )
    scope_name = str(supervision["scope_name"])
    owner_path = tmp_path / f"{reservation['worker_id']}.benchmark-owner.json"
    acquiring = LearningStageWorkerRegistry._benchmark_owner_journal(
        current=anchored,
        anchor=anchor,
        supervision=supervision,
        scope_name=scope_name,
        supervisor_identity=supervisor_identity,
        phase="acquiring",
        process_identity=None,
        beacon_ref=None,
        assignment_ref=None,
        gate_state="closed",
        predecessor=None,
    )
    worker_module._write_json_atomic(owner_path, acquiring)
    launching = LearningStageWorkerRegistry._transition_benchmark_reservation(
        anchored, "launching"
    )
    worker_module._write_json_atomic(
        tmp_path / f"{reservation['operation_id']}.benchmark-reservation.json",
        launching,
    )
    if phase == "acquiring":
        return registry, root, store, reservation, anchor

    process_identity = {"pid": 43210, "create_time_ns": 123_456_789_000}
    job_policy = {
        "kill_on_job_close": True,
        "breakaway_ok": False,
        "silent_breakaway_ok": False,
        "owner_handle_authority": "registry_parent",
    }
    assignment = seal_immutable(
        {
            "contract_version": "benchmark_worker_scope_assignment_v1",
            "scope_name": scope_name,
            "process_identity": process_identity,
            "observed_member_identities": [process_identity],
            "job_policy": job_policy,
            "temporary_process_handle_close": {
                "handle_kind": "temporary_process",
                "status": "closed",
            },
            "temporary_job_handle_close": {
                "handle_kind": "temporary_job",
                "status": "closed",
            },
            "predecessor_content_sha256": acquiring["content_sha256"],
        }
    )
    worker_module._write_json_atomic(
        tmp_path / f"{reservation['worker_id']}.benchmark-assignment.json",
        assignment,
    )
    assignment_ref = {"content_sha256": assignment["content_sha256"]}
    beacon_ref = {"content_sha256": "b" * 64}
    assigned = LearningStageWorkerRegistry._benchmark_owner_journal(
        current=launching,
        anchor=anchor,
        supervision=supervision,
        scope_name=scope_name,
        supervisor_identity=supervisor_identity,
        phase="assignment_proven",
        process_identity=process_identity,
        beacon_ref=beacon_ref,
        assignment_ref=assignment_ref,
        gate_state="closed",
        predecessor=acquiring["content_sha256"],
    )
    worker_module._write_json_atomic(owner_path, assigned)
    launch_anchor = worker_module._compose_benchmark_launch_identity_anchor(
        anchored_reservation=anchored,
        launching_reservation=launching,
        operation_anchor=anchor,
        supervision=supervision,
        supervisor_process_identity=supervisor_identity,
        beacon_ref=beacon_ref,
        process_identity=process_identity,
        assignment=assignment,
    )
    worker_module._write_json_create_only(
        tmp_path
        / f"{reservation['worker_id']}.benchmark-launch-identity-anchor.json",
        launch_anchor,
    )
    if phase == "assignment_proven":
        return registry, root, store, reservation, anchor

    gate = LearningStageWorkerRegistry._benchmark_owner_journal(
        current=launching,
        anchor=anchor,
        supervision=supervision,
        scope_name=scope_name,
        supervisor_identity=supervisor_identity,
        phase="gate_released",
        process_identity=process_identity,
        beacon_ref=beacon_ref,
        assignment_ref=assignment_ref,
        gate_state="released",
        predecessor=assigned["content_sha256"],
    )
    worker_module._write_json_atomic(owner_path, gate)
    launched = LearningStageWorkerRegistry._transition_benchmark_reservation(
        launching, "launched"
    )
    worker_module._write_json_atomic(
        tmp_path / f"{reservation['operation_id']}.benchmark-reservation.json",
        launched,
    )
    if phase == "result_completed":
        worker_module._write_json_atomic(
            tmp_path / f"{reservation['worker_id']}.result.json",
            {
                "contract_version": "learning_stage_worker_result_v2",
                "worker_id": reservation["worker_id"],
                "run_id": reservation["run_id"],
                "stage": reservation["stage"],
                "operation_id": reservation["operation_id"],
                "task_kind": reservation["task_kind"],
                "model_request_id": reservation["model_request_id"],
                "payload_sha256": reservation["payload_sha256"],
                "status": "completed",
                "response": {"success": True},
            },
        )
    if phase in {"gate_released", "result_completed"}:
        return registry, root, store, reservation, anchor

    handle_refs = {
        "worker_process": {"content_sha256": "c" * 64},
        "startup_event": {"content_sha256": "d" * 64},
        "beacon_file": {"content_sha256": "e" * 64},
    }
    intent = seal_immutable(
        {
            "contract_version": "benchmark_worker_cleanup_finalization_intent_v1",
            "supervision_ref": {"content_sha256": supervision["content_sha256"]},
            "assignment_proven_ref": assignment_ref,
            "run_id": reservation["run_id"],
            "stage": reservation["stage"],
            "operation_id": reservation["operation_id"],
            "worker_id": reservation["worker_id"],
            "supervisor_process_identity": supervisor_identity,
            "process_identity": process_identity,
            "scope_name": scope_name,
            "gate_state": "released",
            "exit_observation_ref": {"content_sha256": "f" * 64},
            "stable_zero_observation_ref": {"content_sha256": "1" * 64},
            "exact_owned_handles": {
                "worker_process": "closed_explicitly",
                "startup_event": "closed_explicitly",
                "beacon_file": "closed_explicitly",
                "owner_job": "open",
            },
            "exact_handle_observation_refs": handle_refs,
            "owner_job_handle_close_planned": True,
            "cleanup_receipt_id": worker_module.content_sha256(
                {"worker_id": reservation["worker_id"], "scope_name": scope_name}
            ),
            "predecessor_content_sha256": gate["content_sha256"],
        }
    )
    worker_module._write_json_atomic(
        tmp_path / f"{reservation['worker_id']}.benchmark-cleanup-intent.json",
        intent,
    )
    owner_body = deepcopy(gate)
    owner_body.pop("content_sha256")
    owner_body.update(
        {
            "phase": "cleanup_finalization_intent",
            "exit_observation_ref": intent["exit_observation_ref"],
            "stable_zero_observation_ref": intent["stable_zero_observation_ref"],
            "exact_handle_observation_refs": handle_refs,
            "cleanup_finalization_intent": {
                "content_sha256": intent["content_sha256"]
            },
            "predecessor_content_sha256": gate["content_sha256"],
        }
    )
    worker_module._write_json_atomic(owner_path, seal_immutable(owner_body))
    return registry, root, store, reservation, anchor


def _inspect_benchmark_launch_owner(
    registry: LearningStageWorkerRegistry,
    root: BenchmarkWorkerSupervisionRoot,
    reservation: dict[str, object],
    anchor: dict[str, object],
) -> dict[str, object]:
    return dict(
        registry.inspect_benchmark_worker_launch_owner(
            worker_id=str(reservation["worker_id"]),
            run_id=str(reservation["run_id"]),
            stage=str(reservation["stage"]),
            operation_id=str(reservation["operation_id"]),
            reservation_ref={"content_sha256": reservation["content_sha256"]},
            expected_operation_anchor=anchor,
            supervision_root=root,
        )
    )


def _damage_benchmark_inspection_authority(
    path: Path,
    *,
    mode: str,
    resealed_field: str,
) -> bytes:
    from app.learn.recognition.uei.canonical import seal_immutable

    original = path.read_bytes()
    if mode == "deleted":
        path.unlink()
    elif mode == "malformed":
        path.write_bytes(b"{")
    elif mode == "non_object":
        path.write_bytes(b"[]")
    elif mode == "raw_corruption":
        body = json.loads(original.decode("utf-8"))
        digest = str(body["content_sha256"])
        body["content_sha256"] = (
            ("0" if digest[0] != "0" else "1") + digest[1:]
        )
        path.write_bytes(
            json.dumps(
                body,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    elif mode == "resealed":
        body = json.loads(original.decode("utf-8"))
        body.pop("content_sha256")
        body[resealed_field] = f"resealed-wrong-{resealed_field}"
        path.write_bytes(
            json.dumps(
                seal_immutable(body),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
    else:
        raise AssertionError(f"unsupported authority damage mode: {mode}")
    return original


@pytest.mark.parametrize(
    ("phase", "owner_phase", "reservation_state", "assignment_state"),
    [
        ("anchored", None, "anchored", "not_proven"),
        ("acquiring", "acquiring", "launching", "not_proven"),
        ("assignment_proven", "assignment_proven", "launching", "proven"),
        ("gate_released", "gate_released", "launched", "proven"),
        ("result_completed", "gate_released", "launched", "proven"),
        (
            "cleanup_finalization_intent",
            "cleanup_finalization_intent",
            "launched",
            "proven",
        ),
    ],
)
def test_benchmark_worker_launch_owner_inspection_phases_replay_fresh(
    tmp_path: Path,
    phase: str,
    owner_phase: str | None,
    reservation_state: str,
    assignment_state: str,
) -> None:
    from app.learn import workflow_worker as worker_module

    _registry, root, _store, reservation, anchor = (
        _benchmark_launch_owner_state(tmp_path, phase=phase)
    )
    before = {
        path.name: path.read_bytes()
        for path in tmp_path.glob("*.json")
        if "benchmark-controller" not in path.name
    }
    first_registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
        benchmark_supervision_root=root,
    )
    first = _inspect_benchmark_launch_owner(
        first_registry, root, reservation, anchor
    )
    second_registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
        benchmark_supervision_root=root,
    )
    second = _inspect_benchmark_launch_owner(
        second_registry, root, reservation, anchor
    )

    assert set(first) == {
        "contract_version",
        "authority_kind",
        "run_id",
        "stage",
        "operation_id",
        "worker_id",
        "model_request_id",
        "payload_sha256",
        "execution_nonce",
        "reservation_ref",
        "current_reservation_ref",
        "operation_anchor_ref",
        "expected_supervision_ref",
        "supervision_ref",
        "reservation_state",
        "owner_phase",
        "assignment_state",
        "process_identity",
        "scope_name",
        "assignment_proven_ref",
        "artifact_is_authorization",
        "execute_binding_enabled",
        "content_sha256",
    }
    assert first["contract_version"] == (
        "benchmark_worker_launch_owner_inspection_v1"
    )
    assert first["owner_phase"] == owner_phase
    assert first["reservation_state"] == reservation_state
    assert first["assignment_state"] == assignment_state
    assert first["artifact_is_authorization"] is False
    assert first["execute_binding_enabled"] is False
    assert worker_module.content_sha256(first) == first["content_sha256"]
    if assignment_state == "not_proven":
        assert first["process_identity"] is None
        assert first["scope_name"] is None
        assert first["assignment_proven_ref"] is None
    else:
        assert first["process_identity"] is not None
        assert first["scope_name"] is not None
        assert first["assignment_proven_ref"] is not None
    assert json.dumps(
        first, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") == json.dumps(
        second, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    assert {
        path.name: path.read_bytes()
        for path in tmp_path.glob("*.json")
        if "benchmark-controller" not in path.name
    } == before


def test_benchmark_worker_launch_owner_inspection_rejects_identity_and_lineage_faults(
    tmp_path: Path,
) -> None:
    from app.learn import workflow_worker as worker_module
    from app.learn.recognition.uei.canonical import seal_immutable

    _registry, root, _store, reservation, anchor = (
        _benchmark_launch_owner_state(tmp_path, phase="gate_released")
    )
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
        benchmark_supervision_root=root,
    )
    base = {
        "worker_id": str(reservation["worker_id"]),
        "run_id": str(reservation["run_id"]),
        "stage": str(reservation["stage"]),
        "operation_id": str(reservation["operation_id"]),
        "reservation_ref": {"content_sha256": reservation["content_sha256"]},
        "expected_operation_anchor": anchor,
        "supervision_root": root,
    }
    for field, wrong in (
        ("worker_id", "worker-wrong"),
        ("run_id", "run-wrong"),
        ("stage", "stage-wrong"),
        ("operation_id", "operation-wrong"),
    ):
        with pytest.raises(LearningStageWorkerError):
            registry.inspect_benchmark_worker_launch_owner(
                **{**base, field: wrong}
            )
    with pytest.raises(LearningStageWorkerError):
        registry.inspect_benchmark_worker_launch_owner(
            **{
                **base,
                "reservation_ref": {"content_sha256": "0" * 64},
            }
        )
    wrong_anchor_body = deepcopy(anchor)
    wrong_anchor_body.pop("content_sha256")
    wrong_anchor_body["expected_supervision_ref"] = {
        "content_sha256": "0" * 64
    }
    with pytest.raises(LearningStageWorkerError):
        registry.inspect_benchmark_worker_launch_owner(
            **{
                **base,
                "expected_operation_anchor": seal_immutable(wrong_anchor_body),
            }
        )
    other_root = compose_test_benchmark_worker_supervision_root(
        journal_root=tmp_path / "other-root",
        test_capability=object(),
        workflow_store=LearningWorkflowRunStore(),
        test_store_capability=object(),
    )
    with pytest.raises(LearningStageWorkerError):
        registry.inspect_benchmark_worker_launch_owner(
            **{**base, "supervision_root": other_root}
        )

    paths_and_changes = [
        (
            tmp_path / f"{reservation['worker_id']}.benchmark-owner.json",
            "supervision_ref",
            {"content_sha256": "1" * 64},
        ),
        (
            tmp_path / f"{reservation['worker_id']}.benchmark-owner.json",
            "scope_name",
            "Local\\AgentGuiBenchmarkWorkerWrong-" + "2" * 64,
        ),
        (
            tmp_path / f"{reservation['worker_id']}.benchmark-owner.json",
            "process_identity",
            {"pid": 43211, "create_time_ns": 123_456_789_000},
        ),
        (
            tmp_path / f"{reservation['worker_id']}.benchmark-owner.json",
            "assignment_observation_ref",
            {"content_sha256": "3" * 64},
        ),
        (
            tmp_path
            / f"{reservation['worker_id']}.benchmark-launch-identity-anchor.json",
            "actual_supervision_ref",
            {"content_sha256": "4" * 64},
        ),
        (
            tmp_path / f"{reservation['worker_id']}.benchmark-assignment.json",
            "scope_name",
            "Local\\AgentGuiBenchmarkWorkerWrong-" + "5" * 64,
        ),
        (
            tmp_path / f"{reservation['worker_id']}.benchmark-owner.json",
            "cleanup_receipt_ref",
            {"content_sha256": "6" * 64},
        ),
    ]
    for path, field, value in paths_and_changes:
        original_bytes = path.read_bytes()
        body = json.loads(original_bytes.decode("utf-8"))
        body.pop("content_sha256")
        body[field] = value
        worker_module._write_json_atomic(path, seal_immutable(body))
        try:
            with pytest.raises(LearningStageWorkerError):
                registry.inspect_benchmark_worker_launch_owner(**base)
        finally:
            path.write_bytes(original_bytes)


@pytest.mark.parametrize(
    ("authority", "phase", "suffix", "resealed_field"),
    [
        ("owner", "gate_released", "benchmark-owner.json", "execution_nonce"),
        (
            "assignment",
            "gate_released",
            "benchmark-assignment.json",
            "scope_name",
        ),
        (
            "launch_anchor",
            "gate_released",
            "benchmark-launch-identity-anchor.json",
            "actual_supervision_ref",
        ),
        (
            "cleanup_intent",
            "cleanup_finalization_intent",
            "benchmark-cleanup-intent.json",
            "scope_name",
        ),
    ],
)
@pytest.mark.parametrize(
    "damage",
    ["deleted", "malformed", "non_object", "raw_corruption", "resealed"],
)
def test_benchmark_worker_launch_owner_inspection_rejects_corrupt_authority_store_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authority: str,
    phase: str,
    suffix: str,
    resealed_field: str,
    damage: str,
) -> None:
    import win32event
    from app.learn import workflow_worker as worker_module

    authority_root = tmp_path / authority
    _registry, root, store, reservation, anchor = _benchmark_launch_owner_state(
        authority_root, phase=phase
    )
    calls = {
        "spawn": 0,
        "store": 0,
        "provider": 0,
        "termination": 0,
        "cleanup": 0,
        "gate_release": 0,
        "write": 0,
    }

    def fail_spawn(**_kwargs):
        calls["spawn"] += 1
        pytest.fail("corrupt inspection must not spawn")

    def fail_store(_authority, _run_id):
        calls["store"] += 1
        pytest.fail("corrupt inspection must not read workflow store")

    def fail_provider(*_args, **_kwargs):
        calls["provider"] += 1
        pytest.fail("corrupt inspection must not call provider")

    def fail_termination(_identity):
        calls["termination"] += 1
        pytest.fail("corrupt inspection must not terminate")

    def fail_cleanup(**_kwargs):
        calls["cleanup"] += 1
        pytest.fail("corrupt inspection must not clean up")

    def fail_gate_release(_handle):
        calls["gate_release"] += 1
        pytest.fail("corrupt inspection must not release startup gate")

    def fail_write(*_args, **_kwargs):
        calls["write"] += 1
        pytest.fail("corrupt inspection must not mutate B1 authority")

    registry = LearningStageWorkerRegistry(
        result_root=authority_root,
        process_factory=fail_spawn,
        model_request_cancel=fail_provider,
        benchmark_supervision_root=root,
    )
    monkeypatch.setattr(type(root.read_only_store_authority), "get", fail_store)
    monkeypatch.setattr(
        LearningStageWorkerRegistry,
        "_terminate_exact_benchmark_process",
        staticmethod(fail_termination),
    )
    monkeypatch.setattr(
        registry, "observe_benchmark_worker_cleanup", fail_cleanup
    )
    monkeypatch.setattr(win32event, "SetEvent", fail_gate_release)
    monkeypatch.setattr(registry, "_persist_benchmark_reservation", fail_write)
    monkeypatch.setattr(worker_module, "_write_json_create_only", fail_write)
    monkeypatch.setattr(
        worker_module, "_write_benchmark_cleanup_receipt_atomic", fail_write
    )
    authority_path = authority_root / f"{reservation['worker_id']}.{suffix}"
    before_store = deepcopy(store._states)
    original = _damage_benchmark_inspection_authority(
        authority_path,
        mode=damage,
        resealed_field=resealed_field,
    )
    damaged_files = {
        path.name: path.read_bytes()
        for path in authority_root.glob("*.json")
        if "benchmark-controller" not in path.name
    }
    try:
        with pytest.raises(LearningStageWorkerError):
            _inspect_benchmark_launch_owner(registry, root, reservation, anchor)
        assert {
            path.name: path.read_bytes()
            for path in authority_root.glob("*.json")
            if "benchmark-controller" not in path.name
        } == damaged_files
        assert store._states == before_store
        assert calls == {
            "spawn": 0,
            "store": 0,
            "provider": 0,
            "termination": 0,
            "cleanup": 0,
            "gate_release": 0,
            "write": 0,
        }
    finally:
        authority_path.write_bytes(original)


def test_benchmark_worker_launch_owner_inspection_is_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import workflow_worker as worker_module

    _registry, root, store, reservation, anchor = _benchmark_launch_owner_state(
        tmp_path, phase="gate_released"
    )
    calls = {
        "spawn": 0,
        "store": 0,
        "provider": 0,
        "termination": 0,
        "write": 0,
    }

    def fail_spawn(**_kwargs):
        calls["spawn"] += 1
        pytest.fail("inspection must not spawn")

    def fail_store(_authority, _run_id):
        calls["store"] += 1
        pytest.fail("inspection must not read workflow store")

    def fail_provider(*_args, **_kwargs):
        calls["provider"] += 1
        pytest.fail("inspection must not call a provider")

    def fail_termination(_identity):
        calls["termination"] += 1
        pytest.fail("inspection must not terminate")

    def fail_write(*_args, **_kwargs):
        calls["write"] += 1
        pytest.fail("inspection must not mutate journals")

    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=fail_spawn,
        model_request_cancel=fail_provider,
        benchmark_supervision_root=root,
    )
    monkeypatch.setattr(
        type(root.read_only_store_authority), "get", fail_store
    )
    monkeypatch.setattr(
        LearningStageWorkerRegistry,
        "_terminate_exact_benchmark_process",
        staticmethod(fail_termination),
    )
    monkeypatch.setattr(registry, "_persist_benchmark_reservation", fail_write)
    monkeypatch.setattr(worker_module, "_write_json_create_only", fail_write)
    monkeypatch.setattr(
        worker_module, "_write_benchmark_cleanup_receipt_atomic", fail_write
    )
    before_files = {
        path.name: path.read_bytes()
        for path in tmp_path.glob("*.json")
        if "benchmark-controller" not in path.name
    }
    before_store = deepcopy(store._states)

    _inspect_benchmark_launch_owner(registry, root, reservation, anchor)

    assert calls == {
        "spawn": 0,
        "store": 0,
        "provider": 0,
        "termination": 0,
        "write": 0,
    }
    assert {
        path.name: path.read_bytes()
        for path in tmp_path.glob("*.json")
        if "benchmark-controller" not in path.name
    } == before_files
    assert store._states == before_store


def test_benchmark_worker_launch_owner_inspection_abandoned_controller_fails_store_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import win32api
    import win32con
    import win32event
    from app.learn.hybrid.windows_process_scope import (
        benchmark_worker_controller_mutex_name_v1,
    )

    _registry, root, _store, reservation, anchor = _benchmark_launch_owner_state(
        tmp_path, phase="anchored"
    )
    counts = {
        "store": 0,
        "glob": 0,
        "registry": 0,
        "spawn": 0,
        "provider": 0,
        "termination": 0,
        "cleanup": 0,
        "gate_release": 0,
    }

    def fail_spawn(**_kwargs):
        counts["spawn"] += 1
        pytest.fail("abandoned inspection must not spawn")

    def fail_provider(*_args, **_kwargs):
        counts["provider"] += 1
        pytest.fail("abandoned inspection must not call provider")

    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=fail_spawn,
        model_request_cancel=fail_provider,
        benchmark_supervision_root=root,
    )
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    owner = context.Process(
        target=_benchmark_inspection_controller_owner_helper,
        args=(
            str(tmp_path),
            str(reservation["run_id"]),
            str(reservation["stage"]),
            str(reservation["operation_id"]),
            queue,
        ),
        name="test-owned-benchmark-inspection-controller",
    )
    controller_name = benchmark_worker_controller_mutex_name_v1(
        authority_kind=root.authority_kind,
        run_id=str(reservation["run_id"]),
        stage=str(reservation["stage"]),
        operation_id=str(reservation["operation_id"]),
    )
    real_glob = Path.glob
    real_set_event = win32event.SetEvent

    def sentinel_store(_authority, _run_id):
        counts["store"] += 1
        raise AssertionError("workflow store callback is forbidden")

    def sentinel_glob(path: Path, pattern: str):
        if path.resolve() == tmp_path.resolve() and pattern == "*.benchmark-owner.json":
            counts["glob"] += 1
            return iter(())
        return real_glob(path, pattern)

    class ForbiddenRegistryLock:
        def __enter__(self):
            counts["registry"] += 1
            raise AssertionError("Registry business body is forbidden")

        def __exit__(self, *_args):
            return False

    def sentinel_termination(_identity):
        counts["termination"] += 1
        pytest.fail("abandoned inspection must not terminate")

    def sentinel_cleanup(**_kwargs):
        counts["cleanup"] += 1
        pytest.fail("abandoned inspection must not clean up")

    def sentinel_gate_release(handle):
        counts["gate_release"] += 1
        pytest.fail(f"abandoned inspection must not release gate {handle}")

    witness = None
    owner.start()
    try:
        assert queue.get(timeout=10) == {"owned": True}
        witness = win32event.OpenMutex(win32con.SYNCHRONIZE, False, controller_name)
        owner.terminate()
        owner.join(timeout=10)
        assert owner.is_alive() is False
        monkeypatch.setattr(
            type(root.read_only_store_authority), "get", sentinel_store
        )
        monkeypatch.setattr(Path, "glob", sentinel_glob)
        monkeypatch.setattr(registry, "_lock", ForbiddenRegistryLock())
        monkeypatch.setattr(
            LearningStageWorkerRegistry,
            "_terminate_exact_benchmark_process",
            staticmethod(sentinel_termination),
        )
        monkeypatch.setattr(
            registry, "observe_benchmark_worker_cleanup", sentinel_cleanup
        )
        monkeypatch.setattr(win32event, "SetEvent", sentinel_gate_release)

        with pytest.raises(LearningStageWorkerError):
            _inspect_benchmark_launch_owner(registry, root, reservation, anchor)

        assert counts == {
            "store": 0,
            "glob": 0,
            "registry": 0,
            "spawn": 0,
            "provider": 0,
            "termination": 0,
            "cleanup": 0,
            "gate_release": 0,
        }
    finally:
        monkeypatch.setattr(win32event, "SetEvent", real_set_event)
        if owner.is_alive():
            owner.terminate()
            owner.join(timeout=10)
        owner.close()
        queue.close()
        queue.join_thread()
        if witness is not None:
            win32api.CloseHandle(witness)
        with pytest.raises(Exception):
            win32event.OpenMutex(win32con.SYNCHRONIZE, False, controller_name)
        with pytest.raises(ValueError):
            owner.is_alive()


def test_benchmark_worker_launch_owner_inspection_cleanup_verified_and_zero_residue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import psutil
    import win32api
    import win32con
    import win32event
    import win32gui
    import win32process
    from app.learn import workflow_worker as worker_module
    from app.learn.hybrid.windows_process_scope import (
        WindowsProcessScope,
        benchmark_worker_controller_mutex_name_v1,
        benchmark_worker_scope_name_v1,
    )

    registry, root, _store, _source, reservation, anchor = (
        _benchmark_registry_fixture(tmp_path)
    )
    confirmation = registry.confirm_prepared_benchmark_worker_anchor(
        reservation_ref={"content_sha256": reservation["content_sha256"]},
        expected_operation_anchor=anchor,
        supervision_root=root,
    )
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        benchmark_supervision_root=root,
    )
    worker_id = str(reservation["worker_id"])
    run_id = str(reservation["run_id"])
    stage = str(reservation["stage"])
    operation_id = str(reservation["operation_id"])
    scope_name = benchmark_worker_scope_name_v1(
        authority_kind=root.authority_kind,
        run_id=run_id,
        stage=stage,
        operation_id=operation_id,
        worker_id=worker_id,
        payload_sha256=str(reservation["payload_sha256"]),
        execution_nonce=str(reservation["execution_nonce"]),
    )
    event_name = (
        "Local\\AgentGuiBenchmarkWorkerGate-"
        + worker_module.content_sha256({"scope_name": scope_name})
    )
    mutex_name = benchmark_worker_controller_mutex_name_v1(
        authority_kind=root.authority_kind,
        run_id=run_id,
        stage=stage,
        operation_id=operation_id,
    )
    launch_anchor_path = (
        tmp_path / f"{worker_id}.benchmark-launch-identity-anchor.json"
    )
    owner_path = tmp_path / f"{worker_id}.benchmark-owner.json"
    receipt_path = tmp_path / f"{worker_id}.benchmark-cleanup.json"
    cleanup_kwargs = {
        "worker_id": worker_id,
        "run_id": run_id,
        "stage": stage,
        "operation_id": operation_id,
        "terminate": True,
        "expected_operation_anchor": anchor,
        "supervision_root": root,
    }
    real_fault_hook = worker_module._benchmark_handle_fault_hook
    observed_identity = None
    receipt = None
    projection = None
    cleanup_errors: list[str] = []
    probe_failures: list[str] = []

    def discover_process_identity() -> dict[str, int] | None:
        record = registry._records.get(worker_id)
        if isinstance(record, dict):
            process = record.get("process")
            pid = getattr(process, "pid", None)
            if isinstance(pid, int):
                try:
                    create_time_ns = int(
                        round(psutil.Process(pid).create_time() * 1_000_000_000)
                    )
                except psutil.Error:
                    pass
                else:
                    return {"pid": pid, "create_time_ns": create_time_ns}
        for path in (launch_anchor_path, owner_path):
            if not path.exists():
                continue
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            identity = document.get("process_identity")
            if (
                isinstance(identity, dict)
                and isinstance(identity.get("pid"), int)
                and isinstance(identity.get("create_time_ns"), int)
            ):
                return {
                    "pid": int(identity["pid"]),
                    "create_time_ns": int(identity["create_time_ns"]),
                }
        return None

    try:
        registry.launch_prepared_benchmark_worker(
            reservation_ref=confirmation["anchored_reservation_ref"],
            expected_operation_anchor=anchor,
            authoritative_payload={"capture_live": False},
            supervision_root=root,
        )
        observed_identity = discover_process_identity()
        assert observed_identity is not None
        gate_projection = _inspect_benchmark_launch_owner(
            registry, root, reservation, anchor
        )
        assert gate_projection["owner_phase"] == "gate_released"
        deadline = time.monotonic() + 20
        status = {"status": "running"}
        while time.monotonic() < deadline:
            status = registry.status(
                worker_id=worker_id,
                run_id=run_id,
                operation_id=operation_id,
            )
            if status["status"] == "completed":
                break
            time.sleep(0.02)
        assert status["status"] == "completed"
        completed_projection = _inspect_benchmark_launch_owner(
            registry, root, reservation, anchor
        )
        assert completed_projection == gate_projection

        injected = False

        def fail_after_owner_job_close(handle_kind: str, hook_stage: str) -> None:
            nonlocal injected
            if (
                not injected
                and handle_kind == "owner_job"
                and hook_stage == "after_success"
            ):
                injected = True
                raise RuntimeError("injected-owner-job-after-success")
            real_fault_hook(handle_kind, hook_stage)

        monkeypatch.setattr(
            worker_module,
            "_benchmark_handle_fault_hook",
            fail_after_owner_job_close,
        )
        with pytest.raises(
            RuntimeError, match="injected-owner-job-after-success"
        ):
            registry.observe_benchmark_worker_cleanup(
                **{**cleanup_kwargs, "terminate": False}
            )
        intent_projection = _inspect_benchmark_launch_owner(
            registry, root, reservation, anchor
        )
        assert intent_projection["owner_phase"] == "cleanup_finalization_intent"
        assert not receipt_path.exists()
        monkeypatch.setattr(
            worker_module, "_benchmark_handle_fault_hook", real_fault_hook
        )

        receipt = registry.observe_benchmark_worker_cleanup(
            **{**cleanup_kwargs, "terminate": False}
        )
        receipt_bytes = receipt_path.read_bytes()
        projection = _inspect_benchmark_launch_owner(
            registry, root, reservation, anchor
        )
        assert projection == intent_projection

        corruption_calls = {
            "spawn": 0,
            "store": 0,
            "provider": 0,
            "termination": 0,
            "cleanup": 0,
            "gate_release": 0,
            "write": 0,
        }

        def fail_corrupt_spawn(**_kwargs):
            corruption_calls["spawn"] += 1
            pytest.fail("corrupt receipt inspection must not spawn")

        def fail_corrupt_store(_authority, _run_id):
            corruption_calls["store"] += 1
            pytest.fail("corrupt receipt inspection must not read store")

        def fail_corrupt_provider(*_args, **_kwargs):
            corruption_calls["provider"] += 1
            pytest.fail("corrupt receipt inspection must not call provider")

        def fail_corrupt_termination(_identity):
            corruption_calls["termination"] += 1
            pytest.fail("corrupt receipt inspection must not terminate")

        def fail_corrupt_cleanup(**_kwargs):
            corruption_calls["cleanup"] += 1
            pytest.fail("corrupt receipt inspection must not clean up")

        def fail_corrupt_gate_release(_handle):
            corruption_calls["gate_release"] += 1
            pytest.fail("corrupt receipt inspection must not release gate")

        def fail_corrupt_write(*_args, **_kwargs):
            corruption_calls["write"] += 1
            pytest.fail("corrupt receipt inspection must not mutate authority")

        corrupt_registry = LearningStageWorkerRegistry(
            result_root=tmp_path,
            process_factory=fail_corrupt_spawn,
            model_request_cancel=fail_corrupt_provider,
            benchmark_supervision_root=root,
        )
        with monkeypatch.context() as inspection_patch:
            inspection_patch.setattr(
                type(root.read_only_store_authority),
                "get",
                fail_corrupt_store,
            )
            inspection_patch.setattr(
                LearningStageWorkerRegistry,
                "_terminate_exact_benchmark_process",
                staticmethod(fail_corrupt_termination),
            )
            inspection_patch.setattr(
                corrupt_registry,
                "observe_benchmark_worker_cleanup",
                fail_corrupt_cleanup,
            )
            inspection_patch.setattr(
                win32event, "SetEvent", fail_corrupt_gate_release
            )
            inspection_patch.setattr(
                corrupt_registry,
                "_persist_benchmark_reservation",
                fail_corrupt_write,
            )
            inspection_patch.setattr(
                worker_module, "_write_json_create_only", fail_corrupt_write
            )
            inspection_patch.setattr(
                worker_module,
                "_write_benchmark_cleanup_receipt_atomic",
                fail_corrupt_write,
            )
            for damage in (
                "deleted",
                "malformed",
                "non_object",
                "raw_corruption",
                "resealed",
            ):
                original = _damage_benchmark_inspection_authority(
                    receipt_path,
                    mode=damage,
                    resealed_field="outcome",
                )
                damaged_files = {
                    path.name: path.read_bytes()
                    for path in tmp_path.glob("*.json")
                    if "benchmark-controller" not in path.name
                }
                try:
                    with pytest.raises(LearningStageWorkerError):
                        _inspect_benchmark_launch_owner(
                            corrupt_registry, root, reservation, anchor
                        )
                    assert {
                        path.name: path.read_bytes()
                        for path in tmp_path.glob("*.json")
                        if "benchmark-controller" not in path.name
                    } == damaged_files
                finally:
                    receipt_path.write_bytes(original)
            assert corruption_calls == {
                "spawn": 0,
                "store": 0,
                "provider": 0,
                "termination": 0,
                "cleanup": 0,
                "gate_release": 0,
                "write": 0,
            }

        fresh = LearningStageWorkerRegistry(
            result_root=tmp_path,
            benchmark_supervision_root=root,
        )
        replay_projection = _inspect_benchmark_launch_owner(
            fresh, root, reservation, anchor
        )
        replay_receipt = fresh.observe_benchmark_worker_cleanup(
            **{**cleanup_kwargs, "terminate": False}
        )
        after_replay = _inspect_benchmark_launch_owner(
            fresh, root, reservation, anchor
        )
        assert projection == replay_projection == after_replay
        assert replay_receipt == receipt
        assert receipt_path.read_bytes() == receipt_bytes
    finally:
        monkeypatch.setattr(
            worker_module, "_benchmark_handle_fault_hook", real_fault_hook
        )
        if observed_identity is None:
            observed_identity = discover_process_identity()

        cleanup_succeeded = False
        cleanup_registries = [registry]
        try:
            cleanup_registries.append(
                LearningStageWorkerRegistry(
                    result_root=tmp_path,
                    benchmark_supervision_root=root,
                )
            )
        except BaseException as error:
            cleanup_errors.append(
                f"cleanup registry recovery {type(error).__name__}: {error}"
            )
        for cleanup_index, cleanup_registry in enumerate(cleanup_registries):
            try:
                cleanup_registry.observe_benchmark_worker_cleanup(**cleanup_kwargs)
            except BaseException as error:
                cleanup_errors.append(
                    f"cleanup[{cleanup_index}] {type(error).__name__}: {error}"
                )
            else:
                cleanup_succeeded = True
                break
        if not cleanup_succeeded:
            cleanup_errors.append("no cleanup attempt completed")

        if observed_identity is None:
            probe_failures.append("PID identity was not recoverable")
        else:
            try:
                process_probe = (
                    worker_module._benchmark_cleanup_replay_process_probe(
                        observed_identity
                    )
                )
            except BaseException as error:
                probe_failures.append(
                    f"PID probe {type(error).__name__}: {error}"
                )
            else:
                if process_probe["outcome"] not in {
                    "no_such_process",
                    "pid_absent",
                    "different_incarnation",
                }:
                    probe_failures.append(
                        f"PID probe outcome {process_probe['outcome']}"
                    )

        try:
            job_probe = worker_module._benchmark_cleanup_replay_job_probe(
                scope_name
            )
        except BaseException as error:
            probe_failures.append(f"Job probe {type(error).__name__}: {error}")
        else:
            if job_probe["outcome"] != "job_name_absent":
                probe_failures.append(f"Job probe outcome {job_probe['outcome']}")

        try:
            scope_probe = WindowsProcessScope(scope_name, create=False)
        except BaseException:
            pass
        else:
            try:
                scope_probe.close()
            except BaseException as error:
                probe_failures.append(
                    f"Job probe handle close {type(error).__name__}: {error}"
                )
            else:
                probe_failures.append("Job name remained openable")

        try:
            event_probe = win32event.OpenEvent(
                win32event.EVENT_MODIFY_STATE | 0x00100000,
                False,
                event_name,
            )
        except BaseException:
            pass
        else:
            try:
                win32api.CloseHandle(event_probe)
            except BaseException as error:
                probe_failures.append(
                    f"Event probe handle close {type(error).__name__}: {error}"
                )
            else:
                probe_failures.append("startup Event remained openable")

        try:
            mutex_probe = win32event.OpenMutex(
                win32con.SYNCHRONIZE, False, mutex_name
            )
        except BaseException:
            pass
        else:
            try:
                win32api.CloseHandle(mutex_probe)
            except BaseException as error:
                probe_failures.append(
                    f"mutex probe handle close {type(error).__name__}: {error}"
                )
            else:
                probe_failures.append("controller mutex remained openable")

        if observed_identity is not None:
            pid = int(observed_identity["pid"])
            try:
                listeners = [
                    connection
                    for connection in psutil.net_connections(kind="tcp")
                    if connection.pid == pid
                    and connection.status == psutil.CONN_LISTEN
                ]
            except BaseException as error:
                probe_failures.append(
                    f"listener probe {type(error).__name__}: {error}"
                )
            else:
                if listeners:
                    probe_failures.append(f"listeners remained: {listeners!r}")

            windows: list[int] = []

            def collect_window(hwnd: int, _extra: object) -> bool:
                _thread_id, window_pid = win32process.GetWindowThreadProcessId(
                    hwnd
                )
                if window_pid == pid and win32gui.IsWindow(hwnd):
                    windows.append(hwnd)
                return True

            try:
                win32gui.EnumWindows(collect_window, None)
            except BaseException as error:
                probe_failures.append(
                    f"HWND probe {type(error).__name__}: {error}"
                )
            else:
                if windows:
                    probe_failures.append(f"HWNDs remained: {windows!r}")

        record = registry._records.get(worker_id)
        if isinstance(record, dict) and record.get("process") is not None:
            try:
                record["process"].is_alive()
            except ValueError:
                pass
            except BaseException as error:
                probe_failures.append(
                    f"process handle probe {type(error).__name__}: {error}"
                )
            else:
                probe_failures.append("multiprocessing process handle remained open")

        assert not cleanup_errors and not probe_failures, (
            f"cleanup_errors={cleanup_errors!r}; "
            f"probe_failures={probe_failures!r}"
        )

def test_benchmark_provider_acquisition_prepares_exact_owner_and_replays_after_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import model_server

    registry_root = tmp_path / "registry"
    lease_root = tmp_path / "qwen-leases"
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", lease_root)
    registry, root, anchored, runtime_owner = _anchored_benchmark_provider_fixture(
        registry_root
    )

    first = registry.prepare_benchmark_provider_acquisition(
        reservation_ref={"content_sha256": anchored["content_sha256"]},
        runtime_owner_ref=runtime_owner,
    )
    journal_path = next(registry_root.glob("*.benchmark-provider.json"))
    journal_bytes = journal_path.read_bytes()
    second = registry.prepare_benchmark_provider_acquisition(
        reservation_ref={"content_sha256": anchored["content_sha256"]},
        runtime_owner_ref=runtime_owner,
    )
    restarted = LearningStageWorkerRegistry(
        result_root=registry_root,
        process_factory=_fake_process_factory,
        benchmark_supervision_root=root,
    )
    replay = restarted.prepare_benchmark_provider_acquisition(
        reservation_ref={"content_sha256": anchored["content_sha256"]},
        runtime_owner_ref=runtime_owner,
    )

    assert first == second == replay
    assert journal_path.read_bytes() == journal_bytes
    assert first["contract_version"] == "benchmark_provider_acquisition_ref_v1"
    assert first["reservation_ref"] == {
        "content_sha256": anchored["content_sha256"]
    }
    assert first["runtime_owner_ref"] == {
        "content_sha256": runtime_owner["content_sha256"]
    }
    assert set(first) == {
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
    journal = json.loads(
        next(registry_root.glob("*.benchmark-provider.json")).read_text(
            encoding="utf-8"
        )
    )
    production_observation = model_server.observe_qwen_model_request_acquisition(
        anchored["model_request_id"],
        acquisition_intent_ref=journal["acquisition_intent_ref"],
        runtime_owner_ref=journal["runtime_owner_ref"],
    )
    prepared_observation_ref = {
        "content_sha256": production_observation["content_sha256"]
    }
    assert first["prepared_materialization_ledger_ref"] == (
        production_observation["prepared_materialization_ledger_ref"]
    )
    assert first["prepared_acquisition_observation_ref"] == (
        prepared_observation_ref
    )
    assert first["materialization_ledger_ref"] == production_observation[
        "materialization_ledger_ref"
    ]
    assert first["acquisition_observation_ref"] == prepared_observation_ref
    assert journal["prepared_materialization_ledger_ref"] == (
        production_observation["prepared_materialization_ledger_ref"]
    )
    assert journal["prepared_acquisition_observation_ref"] == (
        prepared_observation_ref
    )
    assert journal["materialization_ledger_ref"] == production_observation[
        "materialization_ledger_ref"
    ]
    assert journal["acquisition_observation_ref"] == prepared_observation_ref
    forbidden_truth = {
        key
        for key in journal
        if key.startswith("verified_") or "stable_zero" in key or "absence" in key
    }
    assert forbidden_truth == set()
    assert not list(lease_root.glob("*.lease.json"))
    assert not list(lease_root.glob("*.pid"))


@pytest.mark.parametrize(
    "field",
    [
        "authority_kind",
        "run_id",
        "stage",
        "operation_id",
        "worker_id",
        "model_request_id",
        "reservation_ref",
        "payload_sha256",
    ],
)
def test_benchmark_provider_acquisition_rejects_owner_substitution_before_prepare(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
) -> None:
    from app.core import model_server
    from app.learn import workflow_worker as worker_module
    from app.learn.recognition.uei.canonical import seal_immutable

    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen")
    registry, _root, anchored, runtime_owner = _anchored_benchmark_provider_fixture(
        tmp_path / "registry"
    )
    calls: list[str] = []
    production_prepare = model_server.prepare_qwen_model_request_acquisition_owner

    def counted_prepare(request_id, *, runtime_owner_ref):
        calls.append(request_id)
        return production_prepare(request_id, runtime_owner_ref=runtime_owner_ref)

    monkeypatch.setattr(
        worker_module,
        "prepare_qwen_model_request_acquisition_owner",
        counted_prepare,
        raising=False,
    )
    altered = deepcopy(runtime_owner)
    altered.pop("content_sha256")
    altered[field] = (
        {"content_sha256": "f" * 64}
        if field == "reservation_ref"
        else ("f" * 64 if field == "payload_sha256" else f"wrong-{field}")
    )
    altered = seal_immutable(altered)

    with pytest.raises(LearningStageWorkerError):
        registry.prepare_benchmark_provider_acquisition(
            reservation_ref={"content_sha256": anchored["content_sha256"]},
            runtime_owner_ref=altered,
        )
    assert calls == []


def test_benchmark_provider_cleanup_cancelled_before_launch_uses_production_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import model_server

    registry_root = tmp_path / "registry"
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen")
    registry, root, anchored, runtime_owner = _anchored_benchmark_provider_fixture(
        registry_root
    )
    registry.prepare_benchmark_provider_acquisition(
        reservation_ref={"content_sha256": anchored["content_sha256"]},
        runtime_owner_ref=runtime_owner,
    )
    provider_path = next(registry_root.glob("*.benchmark-provider.json"))
    prepared_provider = json.loads(provider_path.read_text(encoding="utf-8"))
    prepared_lineage = {
        field: deepcopy(prepared_provider[field])
        for field in (
            "prepared_acquisition_observation_ref",
            "prepared_materialization_ledger_ref",
        )
    }
    _install_benchmark_provider_abort_primitive(
        tmp_path, monkeypatch, request_id=anchored["model_request_id"]
    )
    source = anchored["handler_payload_source"]
    anchor = compose_benchmark_worker_operation_anchor_v1(
        supervision_root=root,
        reservation={
            **anchored,
            "reservation_state": "reserved",
            "abort_observation_ref": None,
            "predecessor_content_sha256": source["content_sha256"],
            "content_sha256": anchored["predecessor_content_sha256"],
        },
        handler_payload_source=source,
        window_binding_ref=source["window_binding_ref"],
        capture_ref=source["capture_ref"],
        predecessor_content_sha256=None,
    )
    registry.observe_benchmark_worker_cleanup(
        worker_id=anchored["worker_id"],
        run_id=anchored["run_id"],
        stage=anchored["stage"],
        operation_id=anchored["operation_id"],
        terminate=True,
        expected_operation_anchor=anchor,
        supervision_root=root,
    )

    first = registry.reconcile_benchmark_provider_cleanup(
        worker_id=anchored["worker_id"],
        run_id=anchored["run_id"],
        stage=anchored["stage"],
        operation_id=anchored["operation_id"],
    )
    restarted = LearningStageWorkerRegistry(
        result_root=registry_root,
        process_factory=_fake_process_factory,
        benchmark_supervision_root=root,
    )
    replay = restarted.reconcile_benchmark_provider_cleanup(
        worker_id=anchored["worker_id"],
        run_id=anchored["run_id"],
        stage=anchored["stage"],
        operation_id=anchored["operation_id"],
    )

    assert first == replay
    assert first["status"] == "cleanup_verified"
    assert first["outcome"] == "verified_not_acquired"
    assert first["cleanup_receipt_ref"] is not None
    current_provider = json.loads(provider_path.read_text(encoding="utf-8"))
    production_observation = model_server.observe_qwen_model_request_acquisition(
        anchored["model_request_id"],
        acquisition_intent_ref=current_provider["acquisition_intent_ref"],
        runtime_owner_ref=current_provider["runtime_owner_ref"],
    )
    assert {
        field: current_provider[field] for field in prepared_lineage
    } == prepared_lineage
    assert current_provider["acquisition_observation_ref"] == {
        "content_sha256": production_observation["content_sha256"]
    }
    assert current_provider["materialization_ledger_ref"] == (
        production_observation["materialization_ledger_ref"]
    )
    terminal = json.loads(
        next(registry_root.glob("*.benchmark-provider-cleanup.json")).read_text(
            encoding="utf-8"
        )
    )
    assert "receipt" not in terminal
    assert terminal["cleanup_receipt_ref"] == first["cleanup_receipt_ref"]
    terminal_bytes = next(
        registry_root.glob("*.benchmark-provider-cleanup.json")
    ).read_bytes()
    production_receipt_path = model_server._qwen_acquisition_artifact_paths(
        anchored["model_request_id"]
    )["cleanup_receipt"]
    drifted = json.loads(production_receipt_path.read_text(encoding="utf-8"))
    drifted["release_reason"] = "edited"
    production_receipt_path.write_text(json.dumps(drifted), encoding="utf-8")
    pending = restarted.reconcile_benchmark_provider_cleanup(
        worker_id=anchored["worker_id"],
        run_id=anchored["run_id"],
        stage=anchored["stage"],
        operation_id=anchored["operation_id"],
    )
    assert pending["status"] == "cleanup_pending"
    assert pending["cleanup_receipt_ref"] is None
    assert next(
        registry_root.glob("*.benchmark-provider-cleanup.json")
    ).read_bytes() == terminal_bytes


def test_benchmark_provider_cleanup_materialization_without_lease_stays_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import model_server

    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen")
    registry, root, anchored, runtime_owner = _anchored_benchmark_provider_fixture(
        tmp_path / "registry"
    )
    registry.prepare_benchmark_provider_acquisition(
        reservation_ref={"content_sha256": anchored["content_sha256"]},
        runtime_owner_ref=runtime_owner,
    )
    prepared_provider = json.loads(
        next((tmp_path / "registry").glob("*.benchmark-provider.json")).read_text(
            encoding="utf-8"
        )
    )
    prepared_lineage = {
        field: deepcopy(prepared_provider[field])
        for field in (
            "prepared_acquisition_observation_ref",
            "prepared_materialization_ledger_ref",
        )
    }
    model_server._transition_qwen_model_request_materialization(
        anchored["model_request_id"], transition="launch"
    )

    pending = registry.reconcile_benchmark_provider_cleanup(
        worker_id=anchored["worker_id"],
        run_id=anchored["run_id"],
        stage=anchored["stage"],
        operation_id=anchored["operation_id"],
    )

    assert pending["status"] == "cleanup_pending"
    assert pending["outcome"] == "indeterminate"
    assert pending["cleanup_receipt_ref"] is None
    assert not list(
        (tmp_path / "registry").glob("*.benchmark-provider-cleanup.json")
    )
    provider_journal = json.loads(
        next((tmp_path / "registry").glob("*.benchmark-provider.json")).read_text(
            encoding="utf-8"
        )
    )
    current_observation = model_server.observe_qwen_model_request_acquisition(
        anchored["model_request_id"],
        acquisition_intent_ref=provider_journal["acquisition_intent_ref"],
        runtime_owner_ref=runtime_owner,
    )
    assert provider_journal["materialization_ledger_ref"] == (
        current_observation["materialization_ledger_ref"]
    )
    assert provider_journal["acquisition_observation_ref"] == {
        "content_sha256": current_observation["content_sha256"]
    }
    assert {
        field: provider_journal[field] for field in prepared_lineage
    } == prepared_lineage
    provider_path = next(
        (tmp_path / "registry").glob("*.benchmark-provider.json")
    )
    provider_bytes = provider_path.read_bytes()
    restarted = LearningStageWorkerRegistry(
        result_root=tmp_path / "registry",
        process_factory=_fake_process_factory,
        benchmark_supervision_root=root,
    )
    replay = restarted.reconcile_benchmark_provider_cleanup(
        worker_id=anchored["worker_id"],
        run_id=anchored["run_id"],
        stage=anchored["stage"],
        operation_id=anchored["operation_id"],
    )
    assert replay == pending
    assert provider_path.read_bytes() == provider_bytes


@pytest.mark.parametrize(
    ("field", "wrong"),
    [
        ("worker_id", "wrong-worker"),
        ("run_id", "wrong-run"),
        ("stage", "wrong-stage"),
        ("operation_id", "wrong-operation"),
    ],
)
def test_benchmark_provider_cleanup_rejects_caller_identity_substitution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    wrong: str,
) -> None:
    from app.core import model_server

    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen")
    registry, _root, anchored, runtime_owner = _anchored_benchmark_provider_fixture(
        tmp_path / "registry"
    )
    registry.prepare_benchmark_provider_acquisition(
        reservation_ref={"content_sha256": anchored["content_sha256"]},
        runtime_owner_ref=runtime_owner,
    )
    identity = {
        "worker_id": anchored["worker_id"],
        "run_id": anchored["run_id"],
        "stage": anchored["stage"],
        "operation_id": anchored["operation_id"],
    }
    identity[field] = wrong
    with pytest.raises(LearningStageWorkerError):
        registry.reconcile_benchmark_provider_cleanup(**identity)


def test_benchmark_provider_acquisition_rejects_reserved_and_stale_refs_before_production(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import model_server
    from app.learn import workflow_worker as worker_module
    from app.learn.recognition.uei.canonical import seal_immutable

    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen")
    registry, root, _store, _source, reserved, anchor = _benchmark_registry_fixture(
        tmp_path / "registry"
    )
    calls: list[str] = []
    monkeypatch.setattr(
        worker_module,
        "prepare_qwen_model_request_acquisition_owner",
        lambda request_id, *, runtime_owner_ref: calls.append(request_id),
    )

    def owner_for(reservation_ref):
        return seal_immutable(
            {
                "contract_version": "benchmark_provider_runtime_owner_v1",
                "authority_kind": reserved["authority_kind"],
                "run_id": reserved["run_id"],
                "stage": reserved["stage"],
                "operation_id": reserved["operation_id"],
                "worker_id": reserved["worker_id"],
                "model_request_id": reserved["model_request_id"],
                "reservation_ref": reservation_ref,
                "payload_sha256": reserved["payload_sha256"],
            }
        )

    reserved_ref = {"content_sha256": reserved["content_sha256"]}
    with pytest.raises(LearningStageWorkerError, match="anchored"):
        registry.prepare_benchmark_provider_acquisition(
            reservation_ref=reserved_ref,
            runtime_owner_ref=owner_for(reserved_ref),
        )
    registry.confirm_prepared_benchmark_worker_anchor(
        reservation_ref=reserved_ref,
        expected_operation_anchor=anchor,
        supervision_root=root,
    )
    with pytest.raises(LearningStageWorkerError, match="anchored"):
        registry.prepare_benchmark_provider_acquisition(
            reservation_ref=reserved_ref,
            runtime_owner_ref=owner_for(reserved_ref),
        )
    assert calls == []


def test_benchmark_provider_acquisition_recovers_registry_write_cut_from_production_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import model_server
    from app.learn import workflow_worker as worker_module

    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen")
    registry_root = tmp_path / "registry"
    registry, _root, anchored, runtime_owner = _anchored_benchmark_provider_fixture(
        registry_root
    )
    real_create = worker_module._write_json_create_only

    def fail_provider_journal(path, payload):
        if Path(path).name.endswith(".benchmark-provider.json"):
            raise OSError("injected-provider-journal-cut")
        return real_create(path, payload)

    monkeypatch.setattr(worker_module, "_write_json_create_only", fail_provider_journal)
    with pytest.raises(OSError, match="injected-provider-journal-cut"):
        registry.prepare_benchmark_provider_acquisition(
            reservation_ref={"content_sha256": anchored["content_sha256"]},
            runtime_owner_ref=runtime_owner,
        )
    monkeypatch.setattr(worker_module, "_write_json_create_only", real_create)

    recovered = registry.prepare_benchmark_provider_acquisition(
        reservation_ref={"content_sha256": anchored["content_sha256"]},
        runtime_owner_ref=runtime_owner,
    )
    assert recovered["acquisition_owner_ref"] is not None
    assert len(list(registry_root.glob("*.benchmark-provider.json"))) == 1
    assert len(
        list((tmp_path / "qwen" / "benchmark_acquisitions").glob("*/acquisition-owner.json"))
    ) == 1


def test_benchmark_provider_acquisition_restart_rejects_partial_registry_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import model_server

    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen")
    registry_root = tmp_path / "registry"
    registry, root, anchored, runtime_owner = _anchored_benchmark_provider_fixture(
        registry_root
    )
    registry.prepare_benchmark_provider_acquisition(
        reservation_ref={"content_sha256": anchored["content_sha256"]},
        runtime_owner_ref=runtime_owner,
    )
    journal_path = next(registry_root.glob("*.benchmark-provider.json"))
    partial = json.loads(journal_path.read_text(encoding="utf-8"))
    partial.pop("acquisition_owner_ref")
    journal_path.write_text(json.dumps(partial), encoding="utf-8")

    with pytest.raises(LearningStageWorkerError, match="provider journal"):
        LearningStageWorkerRegistry(
            result_root=registry_root,
            process_factory=_fake_process_factory,
            benchmark_supervision_root=root,
        )


def test_benchmark_provider_cleanup_acquired_release_projects_only_production_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from urllib.parse import urlsplit

    from app.core import model_server
    from app.learn.hybrid.windows_process_scope import (
        WindowsProcessScope,
        process_scope_name,
        spawn_process_in_scope,
    )

    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen")
    registry, _root, anchored, runtime_owner = _anchored_benchmark_provider_fixture(
        tmp_path / "registry"
    )
    registry.prepare_benchmark_provider_acquisition(
        reservation_ref={"content_sha256": anchored["content_sha256"]},
        runtime_owner_ref=runtime_owner,
    )
    lineage = {
        "run_id": anchored["run_id"],
        "workflow_revision": anchored["workflow_revision"],
        "operation_id": anchored["operation_id"],
        "stage": anchored["stage"],
        "stage_execution_id": f"execution-{anchored['operation_id']}",
    }
    scope_name = process_scope_name(lineage, "qwen")
    scope = WindowsProcessScope(scope_name, create=True)
    helper = spawn_process_in_scope(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        scope_name=scope_name,
        cwd=tmp_path,
    )
    endpoint = "http://127.0.0.1:54329/v1/chat/completions"
    base_url = "http://127.0.0.1:54329/v1"
    parsed = urlsplit(base_url)
    readiness = {
        "started": True,
        "after": {
            "status": "running",
            "base_url": base_url,
            "model_id": "qwen",
            "server_process_identity": deepcopy(helper.process_identity),
            "server_socket": {"host": parsed.hostname, "port": parsed.port},
        },
    }
    profile = {
        "profile_id": "qwen-benchmark-registry",
        "endpoint": endpoint,
        "pid_file": str(tmp_path / "qwen-benchmark-registry.pid"),
    }
    monkeypatch.setenv("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", scope_name)
    monkeypatch.setattr(
        model_server,
        "_observe_qwen_server_binding",
        lambda selected, observed: {
            "server_process_identity": deepcopy(
                observed["after"]["server_process_identity"]
            ),
            "server_socket": deepcopy(observed["after"]["server_socket"]),
        },
    )
    monkeypatch.setattr(
        model_server,
        "_attest_exact_qwen_socket_owner",
        lambda server_socket, process_identity: (
            model_server._current_process_identity(process_identity["pid"])
            == process_identity
        ),
    )
    monkeypatch.setattr(
        model_server,
        "check_model_server",
        lambda selected, timeout=1.0: {"status": "unreachable"},
    )
    try:
        lease = model_server.acquire_qwen_model_lease(
            profile=profile,
            request_id=anchored["model_request_id"],
            readiness=readiness,
        )
        released = model_server._release_exact_qwen_lease(
            lease, reason="controlled-benchmark-registry-release"
        )
        projected = registry.reconcile_benchmark_provider_cleanup(
            worker_id=anchored["worker_id"],
            run_id=anchored["run_id"],
            stage=anchored["stage"],
            operation_id=anchored["operation_id"],
        )
        assert released["server_termination"] == "verified_exact_process_exited"
        assert projected["status"] == "cleanup_verified"
        assert projected["outcome"] == "verified_exact_process_exited"
        receipt = model_server.observe_qwen_model_request_cleanup(
            anchored["model_request_id"]
        )
        assert projected["cleanup_receipt_ref"] == {
            "content_sha256": receipt["content_sha256"]
        }
        assert "server_process_identity" not in projected
    finally:
        helper.close()
        scope.close()


@pytest.mark.parametrize(
    "damage",
    [
        "not_launched_missing",
        "not_launched_edited",
        "cleanup_missing",
        "cleanup_edited",
        "absence_parent_missing",
        "abort_ref_substituted",
    ],
)
def test_benchmark_provider_cleanup_damaged_b1_cancel_chain_never_calls_abort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    damage: str,
) -> None:
    from app.core import model_server
    from app.learn import workflow_worker as worker_module
    from app.learn.recognition.uei.canonical import seal_immutable

    registry_root = tmp_path / "registry"
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen")
    registry, root, anchored, runtime_owner = _anchored_benchmark_provider_fixture(
        registry_root
    )
    registry.prepare_benchmark_provider_acquisition(
        reservation_ref={"content_sha256": anchored["content_sha256"]},
        runtime_owner_ref=runtime_owner,
    )
    _cancel_anchored_benchmark_without_launch(registry, root, anchored)
    worker_id = anchored["worker_id"]
    paths = {
        "not_launched": registry_root / f"{worker_id}.benchmark-not-launched.json",
        "cleanup": registry_root / f"{worker_id}.benchmark-cleanup.json",
        "absence": registry_root / f"{worker_id}.pre-anchor-provider-absence.json",
    }
    if damage == "absence_parent_missing":
        paths["absence"].unlink()
    elif damage.endswith("_missing"):
        paths[damage.removesuffix("_missing")].unlink()
    elif damage.endswith("_edited"):
        path = paths[damage.removesuffix("_edited")]
        value = json.loads(path.read_text(encoding="utf-8"))
        value["edited"] = True
        path.write_text(json.dumps(value), encoding="utf-8")
    else:
        key = (anchored["run_id"], anchored["stage"], anchored["operation_id"])
        current = deepcopy(registry._benchmark_reservations[key])
        current.pop("content_sha256")
        current["abort_observation_ref"] = {"content_sha256": "f" * 64}
        registry._benchmark_reservations[key] = seal_immutable(current)

    abort_calls: list[str] = []

    def reject_abort(request_id, **kwargs):
        del kwargs
        abort_calls.append(request_id)
        raise RuntimeError("abort must not be called")

    monkeypatch.setattr(
        worker_module, "abort_qwen_model_request_acquisition", reject_abort
    )
    result = registry.reconcile_benchmark_provider_cleanup(
        worker_id=anchored["worker_id"],
        run_id=anchored["run_id"],
        stage=anchored["stage"],
        operation_id=anchored["operation_id"],
    )
    assert result["status"] == "cleanup_pending"
    assert abort_calls == []


def test_benchmark_provider_cleanup_materialized_cancel_contradiction_never_aborts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import model_server
    from app.learn import workflow_worker as worker_module

    registry_root = tmp_path / "registry"
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen")
    registry, root, anchored, runtime_owner = _anchored_benchmark_provider_fixture(
        registry_root
    )
    registry.prepare_benchmark_provider_acquisition(
        reservation_ref={"content_sha256": anchored["content_sha256"]},
        runtime_owner_ref=runtime_owner,
    )
    _cancel_anchored_benchmark_without_launch(registry, root, anchored)
    model_server._transition_qwen_model_request_materialization(
        anchored["model_request_id"], transition="launch"
    )
    abort_calls: list[str] = []

    def reject_abort(request_id, **kwargs):
        del kwargs
        abort_calls.append(request_id)
        raise RuntimeError("materialized owner must not be aborted")

    monkeypatch.setattr(
        worker_module, "abort_qwen_model_request_acquisition", reject_abort
    )
    pending = registry.reconcile_benchmark_provider_cleanup(
        worker_id=anchored["worker_id"],
        run_id=anchored["run_id"],
        stage=anchored["stage"],
        operation_id=anchored["operation_id"],
    )
    assert pending["status"] == "cleanup_pending"
    assert abort_calls == []


def test_benchmark_provider_cleanup_wrong_active_root_blocks_prepare_and_reconcile_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import model_server
    from app.learn import workflow_worker as worker_module

    registry_root = tmp_path / "registry"
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen")
    registry, _root, anchored, runtime_owner = _anchored_benchmark_provider_fixture(
        registry_root
    )
    registry.prepare_benchmark_provider_acquisition(
        reservation_ref={"content_sha256": anchored["content_sha256"]},
        runtime_owner_ref=runtime_owner,
    )
    wrong_root = compose_test_benchmark_worker_supervision_root(
        journal_root=tmp_path / "wrong-root",
        test_capability=object(),
        workflow_store=LearningWorkflowRunStore(),
        test_store_capability=object(),
    )
    registry._benchmark_supervision_root = wrong_root
    calls: list[str] = []

    def reject(name):
        def injected(*args, **kwargs):
            del args, kwargs
            calls.append(name)
            raise RuntimeError(f"{name} must not be called")

        return injected

    monkeypatch.setattr(
        worker_module,
        "prepare_qwen_model_request_acquisition_owner",
        reject("prepare"),
    )
    monkeypatch.setattr(
        worker_module,
        "observe_qwen_model_request_acquisition",
        reject("acquisition_observe"),
        raising=False,
    )
    monkeypatch.setattr(
        worker_module,
        "observe_qwen_model_request_cleanup",
        reject("cleanup_observe"),
    )
    with pytest.raises(LearningStageWorkerError):
        registry.prepare_benchmark_provider_acquisition(
            reservation_ref={"content_sha256": anchored["content_sha256"]},
            runtime_owner_ref=runtime_owner,
        )
    with pytest.raises(LearningStageWorkerError):
        registry.reconcile_benchmark_provider_cleanup(
            worker_id=anchored["worker_id"],
            run_id=anchored["run_id"],
            stage=anchored["stage"],
            operation_id=anchored["operation_id"],
        )
    assert calls == []


@pytest.mark.parametrize(
    "artifact_name",
    ["owner", "intent", "ledger", "ledger_revision_zero"],
)
def test_benchmark_provider_acquisition_replay_rejects_production_artifact_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    artifact_name: str,
) -> None:
    from app.core import model_server

    registry_root = tmp_path / "registry"
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen")
    registry, _root, anchored, runtime_owner = _anchored_benchmark_provider_fixture(
        registry_root
    )
    registry.prepare_benchmark_provider_acquisition(
        reservation_ref={"content_sha256": anchored["content_sha256"]},
        runtime_owner_ref=runtime_owner,
    )
    journal_path = next(registry_root.glob("*.benchmark-provider.json"))
    journal_bytes = journal_path.read_bytes()
    artifact_path = model_server._qwen_acquisition_artifact_paths(
        anchored["model_request_id"]
    )[artifact_name]
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact["content_sha256"] = "f" * 64
    artifact_path.write_text(json.dumps(artifact), encoding="utf-8")

    with pytest.raises(LearningStageWorkerError):
        registry.prepare_benchmark_provider_acquisition(
            reservation_ref={"content_sha256": anchored["content_sha256"]},
            runtime_owner_ref=runtime_owner,
        )
    assert journal_path.read_bytes() == journal_bytes


def test_benchmark_provider_acquisition_replay_rejects_legacy_observation_mapping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import model_server
    from app.learn import workflow_worker as worker_module

    registry_root = tmp_path / "registry"
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen")
    registry, _root, anchored, runtime_owner = _anchored_benchmark_provider_fixture(
        registry_root
    )
    registry.prepare_benchmark_provider_acquisition(
        reservation_ref={"content_sha256": anchored["content_sha256"]},
        runtime_owner_ref=runtime_owner,
    )
    journal_path = next(registry_root.glob("*.benchmark-provider.json"))
    journal_bytes = journal_path.read_bytes()
    monkeypatch.setattr(
        worker_module,
        "observe_qwen_model_request_acquisition",
        lambda *args, **kwargs: {
            "contract_version": "legacy_qwen_acquisition_observation_v0"
        },
    )
    with pytest.raises(LearningStageWorkerError):
        registry.prepare_benchmark_provider_acquisition(
            reservation_ref={"content_sha256": anchored["content_sha256"]},
            runtime_owner_ref=runtime_owner,
        )
    assert journal_path.read_bytes() == journal_bytes


def test_benchmark_provider_cleanup_snapshot_mutation_during_observation_stays_pending(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import model_server
    from app.learn import workflow_worker as worker_module

    registry_root = tmp_path / "registry"
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen")
    registry, _root, anchored, runtime_owner = _anchored_benchmark_provider_fixture(
        registry_root
    )
    registry.prepare_benchmark_provider_acquisition(
        reservation_ref={"content_sha256": anchored["content_sha256"]},
        runtime_owner_ref=runtime_owner,
    )
    entered = Event()
    release = Event()
    production_observe = model_server.observe_qwen_model_request_acquisition
    cleanup_calls: list[str] = []
    abort_calls: list[str] = []

    def paused_observe(request_id, **kwargs):
        entered.set()
        assert release.wait(timeout=10)
        return production_observe(request_id, **kwargs)

    monkeypatch.setattr(
        worker_module, "observe_qwen_model_request_acquisition", paused_observe
    )
    monkeypatch.setattr(
        worker_module,
        "observe_qwen_model_request_cleanup",
        lambda request_id: cleanup_calls.append(request_id),
    )
    monkeypatch.setattr(
        worker_module,
        "abort_qwen_model_request_acquisition",
        lambda request_id, **kwargs: abort_calls.append(request_id),
    )
    results: list[dict[str, object]] = []
    failures: list[BaseException] = []

    def reconcile() -> None:
        try:
            results.append(
                registry.reconcile_benchmark_provider_cleanup(
                    worker_id=anchored["worker_id"],
                    run_id=anchored["run_id"],
                    stage=anchored["stage"],
                    operation_id=anchored["operation_id"],
                )
            )
        except BaseException as error:
            failures.append(error)

    thread = Thread(target=reconcile)
    thread.start()
    assert entered.wait(timeout=10)
    key = (anchored["run_id"], anchored["stage"], anchored["operation_id"])
    registry._benchmark_reservations[key] = (
        worker_module._benchmark_transitioned_reservation(anchored, "launching")
    )
    release.set()
    thread.join(timeout=10)
    assert thread.is_alive() is False
    assert failures == []
    assert results[0]["status"] == "cleanup_pending"
    assert abort_calls == []
    assert cleanup_calls == []


def test_benchmark_provider_acquisition_cross_root_copy_is_rejected_on_load(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shutil

    from app.core import model_server

    source_root = tmp_path / "source"
    target_root = tmp_path / "target"
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen")
    registry, _source_supervision, anchored, runtime_owner = (
        _anchored_benchmark_provider_fixture(source_root)
    )
    registry.prepare_benchmark_provider_acquisition(
        reservation_ref={"content_sha256": anchored["content_sha256"]},
        runtime_owner_ref=runtime_owner,
    )
    target_supervision = compose_test_benchmark_worker_supervision_root(
        journal_root=target_root,
        test_capability=object(),
        workflow_store=LearningWorkflowRunStore(),
        test_store_capability=object(),
    )
    for pattern in ("*.benchmark-reservation.json", "*.benchmark-provider.json"):
        for source in source_root.glob(pattern):
            shutil.copy2(source, target_root / source.name)

    with pytest.raises(LearningStageWorkerError, match="supervision identity"):
        LearningStageWorkerRegistry(
            result_root=target_root,
            benchmark_supervision_root=target_supervision,
        )


@pytest.mark.parametrize("transition", ["launch", "abort"])
@pytest.mark.parametrize(
    "substituted_field",
    [
        "prepared_acquisition_observation_ref",
        "prepared_materialization_ledger_ref",
        "acquisition_observation_ref",
        "materialization_ledger_ref",
    ],
)
def test_benchmark_provider_cleanup_resealed_substituted_registry_lineage_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    transition: str,
    substituted_field: str,
) -> None:
    from app.core import model_server
    from app.learn import workflow_worker as worker_module
    from app.learn.recognition.uei.canonical import seal_immutable

    registry_root = tmp_path / "registry"
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen")
    registry, root, anchored, runtime_owner = _anchored_benchmark_provider_fixture(
        registry_root
    )
    registry.prepare_benchmark_provider_acquisition(
        reservation_ref={"content_sha256": anchored["content_sha256"]},
        runtime_owner_ref=runtime_owner,
    )
    model_server._transition_qwen_model_request_materialization(
        anchored["model_request_id"], transition=transition
    )
    journal_path = next(registry_root.glob("*.benchmark-provider.json"))
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    journal.pop("content_sha256")
    journal[substituted_field] = {"content_sha256": "f" * 64}
    substituted = seal_immutable(journal)
    journal_path.write_text(
        json.dumps(substituted, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    substituted_bytes = journal_path.read_bytes()
    cleanup_calls: list[str] = []
    abort_calls: list[str] = []
    monkeypatch.setattr(
        worker_module,
        "observe_qwen_model_request_cleanup",
        lambda request_id: cleanup_calls.append(request_id),
    )
    monkeypatch.setattr(
        worker_module,
        "abort_qwen_model_request_acquisition",
        lambda request_id, **kwargs: abort_calls.append(request_id),
    )

    with pytest.raises(LearningStageWorkerError, match="acquisition lineage"):
        LearningStageWorkerRegistry(
            result_root=registry_root,
            process_factory=_fake_process_factory,
            benchmark_supervision_root=root,
        )

    assert cleanup_calls == []
    assert abort_calls == []
    assert journal_path.read_bytes() == substituted_bytes
    assert not list(registry_root.glob("*.benchmark-provider-cleanup.json"))


def test_benchmark_provider_acquisition_rejects_worker_and_model_request_reuse_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from app.core import model_server
    from app.learn import workflow_worker as worker_module

    registry_root = tmp_path / "registry"
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen")
    registry, root, anchored, runtime_owner = _anchored_benchmark_provider_fixture(
        registry_root
    )
    registry.prepare_benchmark_provider_acquisition(
        reservation_ref={"content_sha256": anchored["content_sha256"]},
        runtime_owner_ref=runtime_owner,
    )
    repeated = [anchored["worker_id"]]

    def repeated_uuid() -> SimpleNamespace:
        return SimpleNamespace(hex=repeated.pop(0) if repeated else "e" * 32)

    monkeypatch.setattr(worker_module, "uuid4", repeated_uuid)

    with pytest.raises(LearningStageWorkerError, match="identity reuse"):
        registry.prepare_benchmark_worker_identity(
            run_id=anchored["run_id"],
            stage=anchored["stage"],
            operation_id="operation-reused-worker",
            workflow_revision=anchored["workflow_revision"],
            task_kind=anchored["task_kind"],
            handler_payload_source=anchored["handler_payload_source"],
            supervision_root=root,
        )

    assert len(list(registry_root.glob("*.benchmark-reservation.json"))) == 1
    assert len(list(registry_root.glob("*.benchmark-provider.json"))) == 1


@pytest.mark.parametrize(
    ("signal", "observation"),
    [
        ("worker_exit", {"status": "worker_exited", "exitcode": 0}),
        (
            "current_stable_zero",
            {
                "status": "cleanup_pending",
                "scope_stable_zero_ref": {"content_sha256": "a" * 64},
            },
        ),
        (
            "request_not_active",
            {
                "status": "request_not_active",
                "model_service_compute_termination": "request_not_active",
            },
        ),
        (
            "missing_pid",
            {
                "contract_version": "qwen_model_request_cleanup_receipt_v1",
                "outcome": "verified_exact_process_exited",
                "server_process_identity": None,
            },
        ),
        (
            "missing_lease",
            {
                "contract_version": "qwen_model_request_cleanup_receipt_v1",
                "outcome": "verified_exact_process_exited",
                "lease_ref": None,
            },
        ),
        (
            "test_authored_mapping",
            {
                "contract_version": "qwen_model_request_cleanup_receipt_v1",
                "outcome": "verified_not_acquired",
                "content_sha256": "b" * 64,
            },
        ),
    ],
)
def test_benchmark_provider_cleanup_nonproduction_signals_cannot_mint_terminal_truth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    signal: str,
    observation: dict[str, object],
) -> None:
    from app.core import model_server
    from app.learn import workflow_worker as worker_module

    registry_root = tmp_path / "registry"
    monkeypatch.setattr(model_server, "MODEL_SERVER_LEASE_DIR", tmp_path / "qwen")
    registry, _root, anchored, runtime_owner = _anchored_benchmark_provider_fixture(
        registry_root
    )
    registry.prepare_benchmark_provider_acquisition(
        reservation_ref={"content_sha256": anchored["content_sha256"]},
        runtime_owner_ref=runtime_owner,
    )
    cleanup_calls: list[str] = []
    abort_calls: list[str] = []

    def observe_pending(request_id: str) -> dict[str, object]:
        cleanup_calls.append(request_id)
        return deepcopy(observation)

    monkeypatch.setattr(
        worker_module, "observe_qwen_model_request_cleanup", observe_pending
    )
    monkeypatch.setattr(
        worker_module,
        "abort_qwen_model_request_acquisition",
        lambda request_id, **kwargs: abort_calls.append(request_id),
    )

    result = registry.reconcile_benchmark_provider_cleanup(
        worker_id=anchored["worker_id"],
        run_id=anchored["run_id"],
        stage=anchored["stage"],
        operation_id=anchored["operation_id"],
    )

    assert cleanup_calls == [anchored["model_request_id"]]
    assert abort_calls == []
    assert result["status"] == "cleanup_pending", signal
    assert result["outcome"] == "indeterminate"
    assert result["cleanup_receipt_ref"] is None
    assert not list(registry_root.glob("*.benchmark-provider-cleanup.json"))

def test_hybrid_vista_cancel_handshake_timeout_reconciles_acquired_supervised_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import model_server
    from app.learn import workflow_worker
    from app.learn.recognition.uei.canonical import content_sha256

    run_id = "run-vista-cancel-acquired"
    operation_id = "operation-vista-cancel-acquired"
    task_kind = "panel_learning_calibration_sequence"
    lineage = _hybrid_lineage(
        run_id=run_id,
        task_kind=task_kind,
        operation_id=operation_id,
    )
    omni_inventory = {"contract_version": "hybrid_omni_inventory_v1", "items": []}
    qwen_bindings = {"contract_version": "hybrid_qwen_bindings_v1", "items": []}
    fusion_result = {"contract_version": "hybrid_fusion_result_v1", "items": []}
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
        model_request_cancel=lambda **kwargs: {
            "contract_version": "model_request_cancellation_v1",
            "status": "request_not_active",
            "model_service_compute_termination": "request_not_active",
        },
    )
    started = registry.start(
        run_id=run_id,
        stage="screen_understanding",
        operation_id=operation_id,
        task_kind=task_kind,
        authoritative_workflow_revision=7,
        payload={
            "learning_pipeline_mode": "hybrid_v1_1",
            "workflow_revision": 7,
            "_hybrid_orchestration": {
                "qwen_bindings": qwen_bindings,
                "fusion_result": fusion_result,
                "qwen_gpu_cleanup_receipt": _hybrid_cleanup_receipt(
                    "qwen",
                    lineage=lineage,
                    predecessor=omni_inventory,
                    provider_result=qwen_bindings,
                ),
            },
        },
    )
    record = registry._records[started["worker_id"]]
    supervisor = record["process"].args[2]["_hybrid_supervisor"]
    model_lease = {
        "contract_version": "hybrid_vista_model_lease_v2",
        "provider": "vista",
        "incarnation_id": "vista-cancel-incarnation",
        "profile": {"profile_id": "vista"},
        "process_identities": [
            {"pid": 7123, "create_time_ns": 712_300_000_000}
        ],
        "process_scope_name": supervisor["process_scope_name"],
    }
    workflow_worker._publish_supervised_vista_lease(
        supervisor,
        model_lease,
        predecessor_sha256=content_sha256(fusion_result),
    )
    monkeypatch.setattr(workflow_worker, "_HYBRID_VISTA_CLEANUP_WAIT_SECONDS", 0.0)
    monkeypatch.setattr(
        model_server,
        "release_hybrid_vista_model_lease",
        lambda lease, **kwargs: _hybrid_cleanup_inventory(
            "vista",
            lineage=kwargs["lineage"],
            predecessor_sha256=kwargs["predecessor_sha256"],
            provider_result_sha256=kwargs["provider_result_sha256"],
            termination_reason="cancellation_recovery",
        ),
    )

    cancelled = registry.cancel_by_operation(
        run_id=run_id,
        stage="screen_understanding",
        operation_id=operation_id,
    )

    assert cancelled["status"] == "cancelled"
    assert cancelled["backend_compute_termination"] == "terminated"
    assert cancelled["model_service_compute_termination"] == "terminated"
    assert record["process"].terminated is True
    lease_document = json.loads(
        Path(record["provider_lease_path"]).read_text(encoding="utf-8")
    )
    assert lease_document["state"] == "released"


def test_duplicate_hybrid_stage_result_without_provider_owner_cleanup_requires_recovery(
    tmp_path: Path,
) -> None:
    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=_fake_process_factory,
    )
    payload = {
        "learning_pipeline_mode": "hybrid_v1_1",
        "run_id": "run-hybrid",
        "workflow_revision": 7,
        "hybrid_capture_bundle_ref": {
            "id": "hybrid-capture/test",
            "content_sha256": "1" * 64,
        },
    }
    first = registry.start(
        run_id="run-hybrid",
        stage="screen_understanding",
        operation_id="operation-hybrid",
        task_kind="panel_learning_hybrid_omni_discovery",
        payload=payload,
        authoritative_workflow_revision=7,
        reuse_active_identical=True,
    )
    record = registry._records[first["worker_id"]]
    process = record["process"]
    process.alive = False
    process.exitcode = 0
    Path(record["result_path"]).write_text(
        json.dumps(
            {
                "contract_version": "learning_stage_worker_result_v2",
                "worker_id": first["worker_id"],
                "run_id": "run-hybrid",
                "stage": "screen_understanding",
                "operation_id": "operation-hybrid",
                "task_kind": "panel_learning_hybrid_omni_discovery",
                "model_request_id": first["model_request_id"],
                "payload_sha256": first["payload_sha256"],
                "status": "completed",
                "finished_at": "2026-08-25T00:00:00+00:00",
                "response": {"artifact_ref": "sealed/result"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    duplicate = registry.start(
        run_id="run-hybrid",
        stage="screen_understanding",
        operation_id="operation-hybrid",
        task_kind="panel_learning_hybrid_omni_discovery",
        payload=payload,
        authoritative_workflow_revision=7,
        reuse_active_identical=True,
    )

    assert duplicate["worker_id"] == first["worker_id"]
    assert duplicate["payload_sha256"] == first["payload_sha256"]
    assert duplicate["status"] == "recovery_required"
    assert duplicate["result_available"] is False
    assert duplicate["result_path"] == first["result_path"]
    assert len(registry._records) == 1


@pytest.mark.parametrize(
    "failure_stage",
    ["owner_write", "runtime_write", "process_factory", "journal_write", "process_start"],
)
def test_hybrid_worker_start_failure_closes_scope_and_allows_safe_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    from app.learn import workflow_worker
    from app.learn.hybrid.windows_process_scope import (
        WindowsProcessScope,
        process_scope_name,
        spawn_process_in_scope,
    )

    run_id = f"run-start-failure-{failure_stage}"
    operation_id = f"operation-start-failure-{failure_stage}"
    lineage = _hybrid_lineage(
        run_id=run_id,
        task_kind="panel_learning_hybrid_omni_discovery",
        operation_id=operation_id,
    )
    scope_name = process_scope_name(lineage, "omni")
    original_owner_write = workflow_worker._write_hybrid_provider_owner
    original_json_write = workflow_worker._write_json_atomic
    failed_processes = []

    class StartFailureProcess(_FakeProcess):
        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            self.closed = False
            self.helper = None
            self.helper_returncode = None

        def start(self) -> None:
            self.helper = spawn_process_in_scope(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                scope_name=scope_name,
                cwd=tmp_path,
            )
            raise RuntimeError("injected-process-start")

        def is_alive(self) -> bool:
            return self.helper is not None and self.helper.poll() is None

        def terminate(self) -> None:
            assert self.helper is not None
            self.helper.terminate()

        def join(self, timeout: float | None = None) -> None:
            assert self.helper is not None
            self.helper.wait(timeout)

        def close(self) -> None:
            if self.helper is not None:
                self.helper_returncode = self.helper.poll()
                self.helper.close()
            self.closed = True

    def failing_json_write(path: Path, payload: dict) -> None:
        if failure_stage == "runtime_write" and path.name.endswith(
            ".provider-runtime.json"
        ):
            raise RuntimeError("injected-runtime-write")
        original_json_write(path, payload)

    if failure_stage == "owner_write":
        monkeypatch.setattr(
            workflow_worker,
            "_write_hybrid_provider_owner",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("injected-owner-write")
            ),
        )
    elif failure_stage == "runtime_write":
        monkeypatch.setattr(workflow_worker, "_write_json_atomic", failing_json_write)

    def factory(*, target, args, name):
        if failure_stage == "process_factory":
            raise RuntimeError("injected-process-factory")
        if failure_stage == "process_start":
            process = StartFailureProcess(target=target, args=args, name=name)
            failed_processes.append(process)
            return process
        return _FakeProcess(target=target, args=args, name=name)

    registry = LearningStageWorkerRegistry(result_root=tmp_path, process_factory=factory)
    if failure_stage == "journal_write":
        monkeypatch.setattr(
            registry,
            "_persist_record_journal",
            lambda record: (_ for _ in ()).throw(
                RuntimeError("injected-journal-write")
            ),
        )

    payload = {
        "learning_pipeline_mode": "hybrid_v1_1",
        "workflow_revision": 7,
        "hybrid_capture_bundle_ref": {
            "id": f"hybrid-capture/{failure_stage}",
            "content_sha256": "c" * 64,
        },
    }
    with pytest.raises(
        RuntimeError, match=f"injected-{failure_stage.replace('_', '-')}"
    ):
        registry.start(
            run_id=run_id,
            stage="screen_understanding",
            operation_id=operation_id,
            task_kind="panel_learning_hybrid_omni_discovery",
            authoritative_workflow_revision=7,
            payload=payload,
        )

    assert registry._records == {}
    assert registry._active_by_operation == {}
    assert registry._workers_by_operation == {}
    assert registry._workers_by_invocation == {}
    assert list(tmp_path.glob("*.provider-owner.json")) == []
    assert list(tmp_path.glob("*.provider-runtime.json")) == []
    assert list(tmp_path.glob("*.worker.json")) == []
    if failure_stage == "process_start":
        assert failed_processes[0].closed is True
        assert failed_processes[0].helper_returncode is not None
    probe = WindowsProcessScope(scope_name, create=True)
    probe.close()

    monkeypatch.setattr(workflow_worker, "_write_hybrid_provider_owner", original_owner_write)
    monkeypatch.setattr(workflow_worker, "_write_json_atomic", original_json_write)
    monkeypatch.setattr(
        registry,
        "_persist_record_journal",
        registry.__class__._persist_record_journal.__get__(registry),
    )
    registry._process_factory = _fake_process_factory
    retried = registry.start(
        run_id=run_id,
        stage="screen_understanding",
        operation_id=operation_id,
        task_kind="panel_learning_hybrid_omni_discovery",
        authoritative_workflow_revision=7,
        payload=payload,
    )
    retried_record = registry._records[retried["worker_id"]]
    assert retried_record["process"].started is True
    retried_record["provider_scope"].close()
    retried_record["provider_scope"] = None


def test_failed_worker_start_cleanup_surfaces_each_failure_and_retains_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import workflow_worker
    from app.learn.hybrid.windows_process_scope import process_scope_name

    lineage = _hybrid_lineage(
        run_id="run-cleanup-failure-evidence",
        task_kind="panel_learning_hybrid_omni_discovery",
    )
    scope_name = process_scope_name(lineage, "omni")

    class ThrowingProcess:
        def is_alive(self):
            return True

        def terminate(self):
            raise RuntimeError("terminate-failed")

        def join(self, timeout=None):
            del timeout
            raise RuntimeError("join-failed")

        def close(self):
            raise RuntimeError("process-close-failed")

    class ThrowingScope:
        name = scope_name

        def close(self):
            raise RuntimeError("job-close-failed")

    first = tmp_path / "first.owner.json"
    second = tmp_path / "second.runtime.json"
    first.write_text("owner", encoding="utf-8")
    second.write_text("runtime", encoding="utf-8")
    with pytest.raises(
        workflow_worker.LearningStageWorkerCleanupError,
        match="Hybrid worker start cleanup is indeterminate",
    ) as captured:
        workflow_worker._cleanup_failed_worker_start(
            provider_scope=ThrowingScope(),
            process=ThrowingProcess(),
            artifact_paths=(first, second),
        )

    evidence = captured.value.cleanup_evidence
    assert evidence["cleanup_status"] == "indeterminate"
    assert {item["step"] for item in evidence["failures"]} == {
        "process_terminate",
        "process_join",
        "process_observe_after",
        "process_close",
        "provider_scope_close",
    }
    assert first.exists() is True
    assert second.exists() is True
    assert evidence["artifact_paths_after"] == [
        str(first.resolve()),
        str(second.resolve()),
    ]


def test_failed_worker_start_cleanup_surfaces_artifact_unlink_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import workflow_worker

    first = tmp_path / "first.owner.json"
    second = tmp_path / "second.runtime.json"
    first.write_text("owner", encoding="utf-8")
    second.write_text("runtime", encoding="utf-8")
    real_unlink = Path.unlink

    def fail_one_unlink(path, *args, **kwargs):
        if path == first:
            raise OSError("unlink-failed")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_one_unlink)
    with pytest.raises(workflow_worker.LearningStageWorkerCleanupError) as captured:
        workflow_worker._cleanup_failed_worker_start(
            provider_scope=None,
            process=None,
            artifact_paths=(first, second),
        )

    evidence = captured.value.cleanup_evidence
    assert evidence["cleanup_status"] == "indeterminate"
    assert [item["step"] for item in evidence["failures"]] == [
        "artifact_unlink"
    ]
    assert first.exists() is True
    assert second.exists() is False
    assert evidence["artifact_paths_after"] == [str(first.resolve())]


def test_registry_retains_recovery_state_when_start_cleanup_is_indeterminate(
    tmp_path: Path,
) -> None:
    from app.learn import workflow_worker
    from app.learn.hybrid.windows_process_scope import (
        WindowsProcessScope,
        process_scope_name,
        spawn_process_in_scope,
    )

    run_id = "run-start-cleanup-indeterminate"
    operation_id = "operation-start-cleanup-indeterminate"
    lineage = _hybrid_lineage(
        run_id=run_id,
        task_kind="panel_learning_hybrid_omni_discovery",
        operation_id=operation_id,
    )
    exact_scope_name = process_scope_name(lineage, "omni")
    unrelated_lineage = {
        **lineage,
        "run_id": "run-start-cleanup-unrelated",
        "operation_id": "operation-start-cleanup-unrelated",
        "stage_execution_id": "execution-start-cleanup-unrelated",
    }
    unrelated_scope_name = process_scope_name(unrelated_lineage, "omni")
    unrelated_scope = WindowsProcessScope(unrelated_scope_name, create=True)
    unrelated = spawn_process_in_scope(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        scope_name=unrelated_scope_name,
        cwd=tmp_path,
    )
    processes = []

    class IndeterminateStartProcess(_FakeProcess):
        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            self.helper = None
            self.join_called = False
            self.close_called = False

        def start(self) -> None:
            self.helper = spawn_process_in_scope(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                scope_name=exact_scope_name,
                cwd=tmp_path,
            )
            raise RuntimeError("injected-start-after-helper")

        def is_alive(self) -> bool:
            return self.helper is not None and self.helper.poll() is None

        def terminate(self) -> None:
            raise RuntimeError("injected-terminate-failure")

        def join(self, timeout=None) -> None:
            del timeout
            self.join_called = True
            raise RuntimeError("injected-join-failure")

        def close(self) -> None:
            self.close_called = True
            raise RuntimeError("injected-process-close-failure")

    def process_factory(*, target, args, name):
        process = IndeterminateStartProcess(target=target, args=args, name=name)
        processes.append(process)
        return process

    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=process_factory,
    )
    payload = {
        "learning_pipeline_mode": "hybrid_v1_1",
        "workflow_revision": 7,
        "hybrid_capture_bundle_ref": {
            "id": "hybrid-capture/start-cleanup-indeterminate",
            "content_sha256": "d" * 64,
        },
    }
    try:
        with pytest.raises(
            workflow_worker.LearningStageWorkerCleanupError,
            match="Hybrid worker start cleanup is indeterminate",
        ) as captured:
            registry.start(
                run_id=run_id,
                stage="screen_understanding",
                operation_id=operation_id,
                task_kind="panel_learning_hybrid_omni_discovery",
                authoritative_workflow_revision=7,
                payload=payload,
            )
        evidence = captured.value.cleanup_evidence
        assert evidence["cleanup_status"] == "indeterminate"
        assert processes[0].join_called is True
        assert processes[0].close_called is True
        assert processes[0].helper.poll() is not None
        assert unrelated.poll() is None
        assert len(registry._records) == 1
        record = next(iter(registry._records.values()))
        assert record["status"] == "recovery_required"
        assert record["start_cleanup_evidence"] == evidence
        assert Path(record["provider_owner_path"]).exists()
        assert Path(record["provider_runtime_path"]).exists()
        with pytest.raises(LearningStageWorkerError, match="operation already has"):
            registry.start(
                run_id=run_id,
                stage="screen_understanding",
                operation_id=operation_id,
                task_kind="panel_learning_hybrid_omni_discovery",
                authoritative_workflow_revision=7,
                payload={**payload, "retry_nonce": 1},
            )
        assert unrelated.poll() is None
        restarted = LearningStageWorkerRegistry(
            result_root=tmp_path,
            process_factory=_fake_process_factory,
        )
        restarted_record = next(iter(restarted._records.values()))
        assert restarted_record["status"] == "recovery_required"
        assert restarted_record["start_cleanup_evidence"] == evidence
        assert unrelated.poll() is None
    finally:
        if processes and processes[0].helper is not None:
            processes[0].helper.close()
        unrelated_scope.terminate()
        unrelated.wait(10)
        unrelated.close()
        unrelated_scope.close()


def test_registry_job_close_failure_retains_exact_scope_and_never_touches_unrelated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import workflow_worker
    from app.learn.hybrid.windows_process_scope import (
        WindowsProcessScope,
        process_scope_name,
        spawn_process_in_scope,
    )

    run_id = "run-job-close-failure"
    operation_id = "operation-job-close-failure"
    lineage = _hybrid_lineage(
        run_id=run_id,
        task_kind="panel_learning_hybrid_omni_discovery",
        operation_id=operation_id,
    )
    exact_scope_name = process_scope_name(lineage, "omni")
    unrelated_lineage = {
        **lineage,
        "run_id": "run-job-close-unrelated",
        "operation_id": "operation-job-close-unrelated",
        "stage_execution_id": "execution-job-close-unrelated",
    }
    unrelated_scope_name = process_scope_name(unrelated_lineage, "omni")
    unrelated_scope = WindowsProcessScope(unrelated_scope_name, create=True)
    unrelated = spawn_process_in_scope(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        scope_name=unrelated_scope_name,
        cwd=tmp_path,
    )
    real_scope_close = WindowsProcessScope.close
    exact_close_calls = 0

    def fail_owner_close(scope):
        nonlocal exact_close_calls
        if scope.name == exact_scope_name:
            exact_close_calls += 1
            if exact_close_calls == 2:
                raise RuntimeError("injected-exact-job-close-failure")
        return real_scope_close(scope)

    monkeypatch.setattr(WindowsProcessScope, "close", fail_owner_close)
    processes = []

    class JobCloseFailureProcess(_FakeProcess):
        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            self.helper = None
            self.closed = False

        def start(self) -> None:
            self.helper = spawn_process_in_scope(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                scope_name=exact_scope_name,
                cwd=tmp_path,
            )
            raise RuntimeError("injected-start-before-job-close")

        def is_alive(self) -> bool:
            return self.helper is not None and self.helper.poll() is None

        def terminate(self) -> None:
            assert self.helper is not None
            self.helper.terminate()

        def join(self, timeout=None) -> None:
            assert self.helper is not None
            self.helper.wait(timeout)

        def close(self) -> None:
            assert self.helper is not None
            self.helper.close()
            self.closed = True

    def process_factory(*, target, args, name):
        process = JobCloseFailureProcess(target=target, args=args, name=name)
        processes.append(process)
        return process

    registry = LearningStageWorkerRegistry(
        result_root=tmp_path,
        process_factory=process_factory,
    )
    try:
        with pytest.raises(
            workflow_worker.LearningStageWorkerCleanupError
        ) as captured:
            registry.start(
                run_id=run_id,
                stage="screen_understanding",
                operation_id=operation_id,
                task_kind="panel_learning_hybrid_omni_discovery",
                authoritative_workflow_revision=7,
                payload={
                    "learning_pipeline_mode": "hybrid_v1_1",
                    "workflow_revision": 7,
                    "hybrid_capture_bundle_ref": {
                        "id": "hybrid-capture/job-close-failure",
                        "content_sha256": "e" * 64,
                    },
                },
            )
        evidence = captured.value.cleanup_evidence
        assert {item["step"] for item in evidence["failures"]} == {
            "provider_scope_close"
        }
        assert evidence["provider_scope_name"] == exact_scope_name
        assert unrelated.poll() is None
        record = next(iter(registry._records.values()))
        assert record["status"] == "recovery_required"
        assert record["provider_scope"]._closed is False
        assert Path(record["provider_owner_path"]).exists()
        assert Path(record["provider_runtime_path"]).exists()
    finally:
        monkeypatch.setattr(WindowsProcessScope, "close", real_scope_close)
        if processes and processes[0].helper is not None and not processes[0].closed:
            processes[0].helper.close()
        if registry._records:
            retained = next(iter(registry._records.values())).get("provider_scope")
            if retained is not None and not retained._closed:
                retained.close()
        unrelated_scope.terminate()
        unrelated.wait(10)
        unrelated.close()
        unrelated_scope.close()
