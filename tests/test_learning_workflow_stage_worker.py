from __future__ import annotations

import json
import multiprocessing
import os
import subprocess
import sys
from threading import Event, Lock, Thread
import time
from pathlib import Path

import pytest

from app.learn.workflow_worker import (
    LearningStageWorkerError,
    LearningStageWorkerRegistry,
    execute_learning_stage_worker_task,
)


@pytest.fixture(autouse=True)
def _deny_real_model_server_start(monkeypatch: pytest.MonkeyPatch) -> None:
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
        lambda payload, cancellation_event=None, model_lease=None: events.append(
            ("task", payload, cancellation_event, model_lease)
        )
        or {"contract_version": "hybrid_qwen_bindings_v1"},
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
        ("task", {"run_id": "run-qwen"}, None, lease),
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
        "app.core.model_server.release_managed_qwen_model_lease",
        lambda model_lease, reason: events.append(("release", model_lease, reason))
        or {"status": "released"},
        raising=False,
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
    assert events[-1] == ("release", lease, "managed_consumer_completed")


@pytest.mark.parametrize(
    "task_kind",
    [
        "panel_learning_two_stage_understanding",
        "panel_learning_model_review_repair",
        "panel_learning_hybrid_qwen_binding",
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


def test_qwen_ensure_to_lease_publication_is_atomic_with_cancellation(
    monkeypatch: pytest.MonkeyPatch,
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
    outcome: dict[str, object] = {}

    worker = Thread(
        target=lambda: outcome.update(
            lease=workflow_worker._ensure_learning_stage_model_ready(
                "panel_learning_hybrid_qwen_binding",
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
            "panel_learning_hybrid_qwen_binding",
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


def test_managed_qwen_shared_no_endpoint_cancel_remains_attached_pending(
    tmp_path: Path,
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
        task_kind="panel_learning_hybrid_qwen_binding",
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
