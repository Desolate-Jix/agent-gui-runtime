from __future__ import annotations

from copy import deepcopy
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.learn.hybrid import benchmark_v2_incumbent_operation as incumbent
from app.learn.recognition.uei.canonical import seal_immutable
from app.learn.workflow_service import (
    LearningWorkflowStageOperationError,
    _benchmark_v2_incumbent_child_slot,
    _project_benchmark_v2_incumbent_pre_reservation_recovery,
    cancel_learning_workflow_stage_operation,
    compose_test_learning_workflow_service_unit,
    start_learning_workflow_stage_operation,
    transition_learning_workflow_run,
)
from app.learn.workflow_store import LearningWorkflowRunStore
from app.learn.workflow_worker import (
    LearningStageWorkerError,
    LearningStageWorkerRegistry,
    compose_test_benchmark_worker_supervision_root,
)
from app.learn.workflow_state import LearningWorkflowTransitionError


SHA_A = "a" * 64
SHA_B = "b" * 64


def _case(case_id: str, digest: str = SHA_A) -> dict[str, str]:
    return {"case_id": case_id, "case_content_sha256": digest}


def _binding(
    *,
    window_digest: str = SHA_A,
    capture_digest: str = SHA_B,
) -> dict[str, object]:
    return incumbent.compose_benchmark_v2_workflow_window_binding(
        run_id="parent-run",
        operation_id="parent-operation",
        window_binding_ref={"id": "window-1", "content_sha256": window_digest},
        capture_ref={"id": "capture-1", "content_sha256": capture_digest},
        owner_journal_ref={"content_sha256": SHA_A},
        expected_uia_root_ref={"content_sha256": SHA_B},
    )


def _hybrid_group() -> dict[str, object]:
    return incumbent.compose_benchmark_v2_hybrid_screen_group_start(
        attempt_ref=seal_immutable({"attempt_id": "attempt-hybrid-pre-start"}),
        partition="regression",
        screen_group="screen-group-hybrid-pre-start",
        provider_corpus_ref=seal_immutable({"kind": "provider-corpus"}),
        case_refs=[_case(f"case-{index}") for index in range(5)],
        hybrid_capture_bundle_ref={"id": "bundle", "content_sha256": SHA_A},
        request_ref={"id": "request", "content_sha256": SHA_B},
        registration_ref={"id": "registration", "content_sha256": SHA_A},
        manifest_ref={"id": "manifest", "content_sha256": SHA_B},
        capture_image_path="screenshots/regression/hybrid-pre-start.png",
        hybrid_config={},
        capture_bundle={},
    )


def test_child_slot_is_unique_deterministic_and_keeps_parent_capture_authority() -> None:
    binding = _binding()
    slots = [
        _benchmark_v2_incumbent_child_slot(
            provider_case_ref=_case(f"case-{index}"),
            window_binding=binding,
        )
        for index in range(5)
    ]

    assert len({slot["run_id"] for slot in slots}) == 5
    assert len({slot["operation_id"] for slot in slots}) == 5
    assert all(slot["parent_window_binding"] == binding for slot in slots)
    assert _benchmark_v2_incumbent_child_slot(
        provider_case_ref=_case("case-0"),
        window_binding=binding,
    ) == slots[0]

    same_id_different_sha = _benchmark_v2_incumbent_child_slot(
        provider_case_ref=_case("case-0", SHA_B),
        window_binding=binding,
    )
    assert same_id_different_sha["run_id"] == slots[0]["run_id"]
    assert same_id_different_sha["operation_id"] == slots[0]["operation_id"]
    assert same_id_different_sha["provider_case_ref"] != slots[0]["provider_case_ref"]

    changed_binding = _binding(window_digest=SHA_B, capture_digest=SHA_A)
    cross_binding = _benchmark_v2_incumbent_child_slot(
        provider_case_ref=_case("case-0"),
        window_binding=changed_binding,
    )
    assert cross_binding["run_id"] == slots[0]["run_id"]
    assert cross_binding["operation_id"] == slots[0]["operation_id"]
    assert cross_binding["parent_window_binding"] != slots[0]["parent_window_binding"]


class _ObserveOnlyStore:
    def __init__(self, state: object = None, *, missing: bool = False) -> None:
        self.state = state
        self.missing = missing
        self.get_calls: list[str] = []
        self.mutation_calls = 0

    def get(self, run_id: str):
        self.get_calls.append(run_id)
        if self.missing:
            raise LearningWorkflowTransitionError("workflow run not found")
        return deepcopy(self.state)

    def transition(self, **_kwargs):
        self.mutation_calls += 1
        raise AssertionError("read-only incumbent lookup mutated the store")


def _service(store: object) -> incumbent.BenchmarkV2IncumbentWorkflowService:
    composition = compose_test_learning_workflow_service_unit(
        store=store,
        worker_registry=object(),
        project_root=Path.cwd(),
        benchmark_supervision_root=object(),
        provider_case_resolver=object(),
        benchmark_v2_worker_binding_resolver=object(),
    )
    return incumbent.BenchmarkV2IncumbentWorkflowService(composition)


def test_lookup_incumbent_absent_slot_is_none_without_mutation_or_provider_call() -> None:
    store = _ObserveOnlyStore(missing=True)
    service = _service(store)

    assert service.lookup_incumbent_observe(
        provider_case_ref=_case("case-1"),
        window_binding=_binding(),
    ) is None
    assert len(store.get_calls) == 1
    assert store.mutation_calls == 0


def test_lookup_incumbent_existing_incomplete_slot_requires_recovery() -> None:
    slot = _benchmark_v2_incumbent_child_slot(
        provider_case_ref=_case("case-1"), window_binding=_binding()
    )
    store = _ObserveOnlyStore(
        {
            "run_id": slot["run_id"],
            "revision": 1,
            "current_stage": "bind_capture",
            "stages": {},
        }
    )
    service = _service(store)

    with pytest.raises(LearningWorkflowStageOperationError, match="recovery_required"):
        service.lookup_incumbent_observe(
            provider_case_ref=_case("case-1"),
            window_binding=_binding(),
        )
    assert store.mutation_calls == 0


def test_recover_incumbent_pre_reservation_start_safe_stops_without_model_launch(
    tmp_path: Path,
) -> None:
    binding = _binding()
    provider_case_ref = _case("case-pre-reservation")
    slot = _benchmark_v2_incumbent_child_slot(
        provider_case_ref=provider_case_ref,
        window_binding=binding,
    )
    capture_path = tmp_path / "artifacts" / "screenshots" / "capture.png"
    capture_path.parent.mkdir(parents=True)
    capture_path.write_bytes(b"not-used-by-recovery")
    start_intent = seal_immutable(
        {
            "contract_version": "benchmark_v2_incumbent_child_run_start_intent_v1",
            "provider_case_ref": deepcopy(slot["provider_case_ref"]),
            "parent_run_id": binding["run_id"],
            "parent_stage": binding["stage"],
            "parent_operation_id": binding["operation_id"],
            "window_binding_ref": deepcopy(binding["window_binding_ref"]),
            "capture_ref": deepcopy(binding["capture_ref"]),
            "run_id": slot["run_id"],
            "stage": slot["stage"],
            "operation_id": slot["operation_id"],
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )
    store = LearningWorkflowRunStore()
    root = compose_test_benchmark_worker_supervision_root(
        journal_root=tmp_path / "worker-journals",
        test_capability=object(),
        workflow_store=store,
        test_store_capability=object(),
    )
    registry = LearningStageWorkerRegistry(
        result_root=root.journal_root,
        benchmark_supervision_root=root,
    )
    composition = compose_test_learning_workflow_service_unit(
        store=store,
        worker_registry=registry,
        project_root=tmp_path,
        benchmark_supervision_root=root,
        provider_case_resolver=object(),
        benchmark_v2_worker_binding_resolver=object(),
    )
    service = incumbent.BenchmarkV2IncumbentWorkflowService(composition)
    current = transition_learning_workflow_run(
        store=store,
        project_root=tmp_path,
        run_id=str(slot["run_id"]),
        expected_revision=0,
        stage="bind_capture",
        outcome="running",
        reason="benchmark_v2 incumbent child capture binding",
        evidence_refs={"benchmark_v2_incumbent_child_start_intent": start_intent},
    )
    current = transition_learning_workflow_run(
        store=store,
        project_root=tmp_path,
        run_id=str(slot["run_id"]),
        expected_revision=int(current["revision"]),
        stage="bind_capture",
        outcome="completed",
        reason="benchmark_v2 incumbent child capture bound",
        evidence_refs={
            "image_path": str(capture_path),
            "benchmark_v2_incumbent_child_start_intent": start_intent,
        },
    )
    current = start_learning_workflow_stage_operation(
        store=store,
        project_root=tmp_path,
        run_id=str(slot["run_id"]),
        expected_revision=int(current["revision"]),
        stage=str(slot["stage"]),
        operation_id=str(slot["operation_id"]),
        reason="benchmark_v2 incumbent child workflow service start",
        lease_seconds=1,
        now=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )["workflow_state"]

    recovered = service.recover_incumbent_pre_reservation(
        provider_case_ref=provider_case_ref,
        window_binding=binding,
    )
    replay = service.recover_incumbent_pre_reservation(
        provider_case_ref=provider_case_ref,
        window_binding=binding,
    )
    corrupt_terminal = deepcopy(store.get(str(slot["run_id"])))
    corrupt_terminal["stages"][str(slot["stage"])]["evidence_refs"][
        "stage_execution"
    ]["result_outcome"] = "completed"
    with pytest.raises(
        LearningWorkflowStageOperationError,
        match="recovery stage execution is invalid",
    ):
        _project_benchmark_v2_incumbent_pre_reservation_recovery(
            composition=composition,
            workflow_state=corrupt_terminal,
            slot=slot,
        )
    with pytest.raises(
        LearningWorkflowStageOperationError,
        match="child start lineage",
    ):
        service.recover_incumbent_pre_reservation(
            provider_case_ref=_case("case-pre-reservation", SHA_B),
            window_binding=binding,
        )

    assert recovered == replay
    assert recovered["status"] == "safe_stopped"
    assert recovered["operation_id"] == slot["operation_id"]
    assert recovered["artifact_is_authorization"] is False
    assert recovered["execute_binding_enabled"] is False
    assert store.get(str(slot["run_id"]))["terminal"] is True
    assert not list(root.journal_root.glob("*.benchmark-reservation.json"))
    assert not list(root.journal_root.glob("*.benchmark-owner.json"))
    assert not list(root.journal_root.glob("*.worker.json"))


def test_recover_incumbent_pre_reservation_ignores_regular_terminal(
    tmp_path: Path,
) -> None:
    binding = _binding()
    provider_case_ref = _case("case-regular-terminal")
    slot = _benchmark_v2_incumbent_child_slot(
        provider_case_ref=provider_case_ref,
        window_binding=binding,
    )
    store = LearningWorkflowRunStore()
    current = store.transition(
        run_id=str(slot["run_id"]),
        expected_revision=0,
        stage="bind_capture",
        outcome="running",
        evidence_refs={},
    )
    current = store.transition(
        run_id=str(slot["run_id"]),
        expected_revision=int(current["revision"]),
        stage="bind_capture",
        outcome="completed",
        evidence_refs={"image_path": "unused.png"},
    )
    current = start_learning_workflow_stage_operation(
        store=store,
        project_root=tmp_path,
        run_id=str(slot["run_id"]),
        expected_revision=int(current["revision"]),
        stage=str(slot["stage"]),
        operation_id=str(slot["operation_id"]),
    )["workflow_state"]
    cancel_learning_workflow_stage_operation(
        store=store,
        project_root=tmp_path,
        run_id=str(slot["run_id"]),
        expected_revision=int(current["revision"]),
        stage=str(slot["stage"]),
        operation_id=str(slot["operation_id"]),
        reason="regular terminal",
    )
    composition = compose_test_learning_workflow_service_unit(
        store=store,
        worker_registry=object(),
        project_root=tmp_path,
        benchmark_supervision_root=object(),
        provider_case_resolver=object(),
        benchmark_v2_worker_binding_resolver=object(),
    )

    assert incumbent.BenchmarkV2IncumbentWorkflowService(
        composition
    ).recover_incumbent_pre_reservation(
        provider_case_ref=provider_case_ref,
        window_binding=binding,
    ) is None


def test_recover_hybrid_pre_reservation_requires_exact_store_and_worker_absence(
    tmp_path: Path,
) -> None:
    from app.learn.workflow_worker import _benchmark_operation_artifact_path

    store = LearningWorkflowRunStore()
    root = compose_test_benchmark_worker_supervision_root(
        journal_root=tmp_path / "worker-journals",
        test_capability=object(),
        workflow_store=store,
        test_store_capability=object(),
    )
    registry = LearningStageWorkerRegistry(
        result_root=root.journal_root,
        benchmark_supervision_root=root,
    )
    composition = compose_test_learning_workflow_service_unit(
        store=store,
        worker_registry=registry,
        project_root=tmp_path,
        benchmark_supervision_root=root,
        provider_case_resolver=object(),
        benchmark_v2_worker_binding_resolver=object(),
    )
    service = incumbent.BenchmarkV2IncumbentWorkflowService(composition)
    group = _hybrid_group()
    binding = _binding()
    intent_ref = {"content_sha256": "c" * 64}

    recovered = service.recover_hybrid_pre_reservation(
        screen_group=group,
        window_binding=binding,
        service_intent_ref=intent_ref,
    )
    replay = service.recover_hybrid_pre_reservation(
        screen_group=group,
        window_binding=binding,
        service_intent_ref=intent_ref,
    )

    assert recovered == replay
    assert recovered["contract_version"] == (
        "benchmark_v2_hybrid_pre_reservation_recovery_v1"
    )
    assert recovered["status"] == "safe_stopped"
    assert recovered["service_intent_ref"] == intent_ref
    assert recovered["run_id"] == binding["run_id"]
    assert recovered["window_binding_ref"] == binding["window_binding_ref"]
    assert recovered["capture_ref"] == binding["capture_ref"]
    assert recovered["reservation_absence_ref"]["contract_version"] == (
        "benchmark_worker_pre_reservation_absence_v1"
    )
    assert recovered["reservation_absence_ref"]["run_id"] == binding["run_id"]
    assert recovered["reservation_absence_ref"]["stage"] == binding["stage"]
    assert recovered["reservation_absence_ref"]["operation_id"] == (
        binding["operation_id"]
    )
    assert recovered["artifact_is_authorization"] is False
    assert recovered["execute_binding_enabled"] is False

    durable = _benchmark_operation_artifact_path(
        root.journal_root,
        str(binding["operation_id"]),
        ".benchmark-reservation.json",
    )
    durable.write_text("{}\n", encoding="utf-8")
    with pytest.raises(LearningStageWorkerError, match="durable worker state"):
        service.recover_hybrid_pre_reservation(
            screen_group=group,
            window_binding=binding,
            service_intent_ref=intent_ref,
        )


def test_recover_hybrid_pre_reservation_rejects_any_existing_workflow_state(
    tmp_path: Path,
) -> None:
    store = LearningWorkflowRunStore()
    root = compose_test_benchmark_worker_supervision_root(
        journal_root=tmp_path / "worker-journals",
        test_capability=object(),
        workflow_store=store,
        test_store_capability=object(),
    )
    registry = LearningStageWorkerRegistry(
        result_root=root.journal_root,
        benchmark_supervision_root=root,
    )
    composition = compose_test_learning_workflow_service_unit(
        store=store,
        worker_registry=registry,
        project_root=tmp_path,
        benchmark_supervision_root=root,
        provider_case_resolver=object(),
        benchmark_v2_worker_binding_resolver=object(),
    )
    service = incumbent.BenchmarkV2IncumbentWorkflowService(composition)
    group = _hybrid_group()
    binding = _binding()
    store.transition(
        run_id=str(binding["run_id"]),
        expected_revision=0,
        stage="bind_capture",
        outcome="running",
    )

    assert (
        service.recover_hybrid_pre_reservation(
            screen_group=group,
            window_binding=binding,
            service_intent_ref={"content_sha256": "c" * 64},
        )
        is None
    )


def test_start_uses_five_unique_child_slots_and_replays_same_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.learn.workflow_service as workflow_service

    store = _ObserveOnlyStore()
    service = _service(store)
    starts: list[dict[str, object]] = []
    durable: dict[tuple[str, str], dict[str, object]] = {}

    monkeypatch.setattr(
        workflow_service,
        "get_learning_workflow_operation_lock",
        lambda **_kwargs: nullcontext(),
    )
    monkeypatch.setattr(
        workflow_service,
        "_ensure_benchmark_v2_incumbent_child_workflow_run",
        lambda **_kwargs: {"revision": 7},
        raising=False,
    )
    monkeypatch.setattr(
        workflow_service,
        "_benchmark_v2_parent_has_hybrid_binding",
        lambda **_kwargs: True,
        raising=False,
    )

    def start(**kwargs):
        starts.append(deepcopy(kwargs))
        key = (str(kwargs["run_id"]), str(kwargs["operation_id"]))
        durable[key] = {
            "case": deepcopy(kwargs["request"]["provider_case_ref"]),
            "binding": deepcopy(kwargs["parent_window_binding"]),
            "step": {"slot": key},
        }

    def lookup(**kwargs):
        slot = _benchmark_v2_incumbent_child_slot(
            provider_case_ref=kwargs["provider_case_ref"],
            window_binding=kwargs["window_binding"],
        )
        key = (str(slot["run_id"]), str(slot["operation_id"]))
        existing = durable.get(key)
        if existing is None:
            return None
        if (
            existing["case"] != slot["provider_case_ref"]
            or existing["binding"] != slot["parent_window_binding"]
        ):
            raise LearningWorkflowStageOperationError(
                "benchmark_v2 incumbent lookup recovery_required: stale slot"
            )
        return deepcopy(existing["step"])

    monkeypatch.setattr(
        workflow_service, "_start_benchmark_v2_incumbent_operation", start
    )
    monkeypatch.setattr(
        workflow_service, "_lookup_benchmark_v2_incumbent_workflow_service", lookup
    )

    binding = _binding()
    results = [
        service.start_incumbent_observe(
            provider_case_ref=_case(f"case-{index}"),
            window_binding=binding,
        )
        for index in range(5)
    ]
    assert len(starts) == 5
    assert len({item["run_id"] for item in starts}) == 5
    assert len({item["operation_id"] for item in starts}) == 5
    assert all(item["parent_window_binding"] == binding for item in starts)
    assert len({tuple(result["slot"]) for result in results}) == 5

    replay = service.start_incumbent_observe(
        provider_case_ref=_case("case-0"), window_binding=binding
    )
    assert replay == results[0]
    assert len(starts) == 5

    with pytest.raises(LearningWorkflowStageOperationError, match="recovery_required"):
        service.start_incumbent_observe(
            provider_case_ref=_case("case-0", SHA_B), window_binding=binding
        )
    with pytest.raises(LearningWorkflowStageOperationError, match="recovery_required"):
        service.start_incumbent_observe(
            provider_case_ref=_case("case-0"),
            window_binding=_binding(window_digest=SHA_B, capture_digest=SHA_A),
        )
    assert len(starts) == 5


def test_actual_stable_zero_surface_is_service_owned_and_keyword_only() -> None:
    service = _service(_ObserveOnlyStore(missing=True))
    with pytest.raises(ValueError, match="exactly six"):
        service.attest_actual_operations_stable_zero(operation_refs=[])


def _stable_operation(
    *, mode: str, index: int, status: str
) -> dict[str, object]:
    run_id = "parent-run" if mode == "hybrid_v1_1" else f"child-run-{index}"
    operation_id = (
        "parent-operation" if mode == "hybrid_v1_1" else f"child-operation-{index}"
    )
    return incumbent.compose_benchmark_v2_workflow_service_operation_ref(
        mode=mode,
        run_id=run_id,
        stage="screen_understanding",
        operation_id=operation_id,
        workflow_state_ref={
            "run_id": run_id,
            "revision": index + 1,
            "content_sha256": f"{index + 1:x}" * 64,
        },
        stage_execution_ref={
            "run_id": run_id,
            "stage": "screen_understanding",
            "operation_id": operation_id,
            "revision": index + 1,
            "content_sha256": f"{index + 7:x}" * 64,
        },
        request_ref={"id": f"request-{index}", "content_sha256": SHA_A},
        window_binding_ref={"id": "window-1", "content_sha256": SHA_A},
        capture_ref={"id": "capture-1", "content_sha256": SHA_B},
        worker_ref=seal_immutable(
            {
                "worker_id": f"worker-{index}",
                "model_request_id": f"model-request-{index}",
                "payload_sha256": SHA_A,
            }
        ),
        status=status,
        predecessor_content_sha256="f" * 64,
    )


def _stable_receipt(*, hybrid_status: str = "safe_stopped") -> dict[str, object]:
    operations = [
        _stable_operation(mode="hybrid_v1_1", index=0, status=hybrid_status),
        *[
            _stable_operation(
                mode="incumbent_qwen_only", index=index, status="cancelled"
            )
            for index in range(1, 6)
        ],
    ]
    entries = []
    for operation in operations:
        worker = operation["worker_ref"]
        if operation["mode"] == "hybrid_v1_1":
            if hybrid_status == "complete":
                worker_cleanup = seal_immutable(
                    {
                        "contract_version": (
                            "benchmark_v2_hybrid_completed_worker_cleanup_ref_v1"
                        ),
                        "run_id": operation["run_id"],
                        "stage": operation["stage"],
                        "operation_id": operation["operation_id"],
                        "worker_id": worker["worker_id"],
                        "model_request_id": worker["model_request_id"],
                        "payload_sha256": worker["payload_sha256"],
                        "worker_status": "completed",
                        "runtime_attached": False,
                        "result_available": True,
                    }
                )
            else:
                worker_cleanup = seal_immutable(
                    {
                        "contract_version": "benchmark_v2_hybrid_worker_cleanup_ref_v1",
                        "run_id": operation["run_id"],
                        "stage": operation["stage"],
                        "operation_id": operation["operation_id"],
                        "worker_id": worker["worker_id"],
                        "model_request_id": worker["model_request_id"],
                        "payload_sha256": worker["payload_sha256"],
                        "backend_compute_termination": "terminated",
                        "model_service_compute_termination": "terminated",
                    }
                )
        else:
            worker_cleanup = seal_immutable(
                {
                    "contract_version": "benchmark_worker_cleanup_receipt_v1",
                    "outcome": "verified_exact_worker_exited",
                    "run_id": operation["run_id"],
                    "stage": operation["stage"],
                    "operation_id": operation["operation_id"],
                    "worker_id": worker["worker_id"],
                    "reservation_ref": {
                        "content_sha256": f"{int(str(operation['request_ref']['id']).rsplit('-', 1)[1]) + 1:x}" * 64
                    },
                }
            )
        provider_cleanup = seal_immutable(
            {
                "contract_version": "benchmark_provider_cleanup_ref_v1",
                "status": "cleanup_verified",
                "outcome": "verified_exact_process_exited",
                "run_id": operation["run_id"],
                "stage": operation["stage"],
                "operation_id": operation["operation_id"],
                "worker_id": worker["worker_id"],
                "model_request_id": worker["model_request_id"],
                "payload_sha256": worker["payload_sha256"],
            }
        )
        terminal_receipt = (
            seal_immutable(
                {
                    "contract_version": "benchmark_v2_incumbent_terminal_receipt_v1",
                    "outcome": "benchmark_v2_incumbent_cancelled",
                    "run_id": operation["run_id"],
                    "stage": operation["stage"],
                    "operation_id": operation["operation_id"],
                    "worker_id": worker["worker_id"],
                    "model_request_id": worker["model_request_id"],
                    "payload_sha256": worker["payload_sha256"],
                    "result_sha256": None,
                    "terminal_intent_ref": None,
                    "cancel_intent_ref": {"content_sha256": "f" * 64},
                    "generic_adoption_ref": None,
                    "window_adoption_ref": None,
                    "worker_cleanup_ref": worker_cleanup,
                    "provider_cleanup_ref": provider_cleanup,
                    "provider_cleanup_outcome": provider_cleanup["outcome"],
                    "terminal_at": "2026-09-01T05:00:00+00:00",
                    "artifact_is_authorization": False,
                    "execute_binding_enabled": False,
                    "predecessor_content_sha256": operation[
                        "predecessor_content_sha256"
                    ],
                }
            )
            if operation["mode"] == "incumbent_qwen_only"
            else seal_immutable(
                {
                    "run_id": operation["run_id"],
                    "stage": operation["stage"],
                    "operation_id": operation["operation_id"],
                    "worker_id": worker["worker_id"],
                }
            )
        )
        entries.append(
            {
                "operation_ref_sha256": operation["content_sha256"],
                "terminal_receipt_ref": terminal_receipt,
                "worker_cleanup_ref": worker_cleanup,
                "provider_cleanup_ref": provider_cleanup,
            }
        )
    return seal_immutable(
        {
            "contract_version": "benchmark_v2_actual_operations_stable_zero_v1",
            "operation_refs": operations,
            "cleanup_entries": entries,
            "window_binding_ref": {"id": "window-1", "content_sha256": SHA_A},
            "capture_ref": {"id": "capture-1", "content_sha256": SHA_B},
            "cleanup_status": "stable_zero",
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
        }
    )


def test_stable_zero_validator_rejects_active_cross_worker_and_aggregate_cleanup() -> None:
    receipt = _stable_receipt()
    assert incumbent.validate_benchmark_v2_actual_operations_stable_zero(receipt) == receipt
    completed = _stable_receipt(hybrid_status="complete")
    assert incumbent.validate_benchmark_v2_actual_operations_stable_zero(completed) == completed

    safe_stopped_completed = deepcopy(receipt)
    safe_stopped_completed["cleanup_entries"][0]["worker_cleanup_ref"] = deepcopy(
        completed["cleanup_entries"][0]["worker_cleanup_ref"]
    )
    safe_stopped_completed = seal_immutable(
        {
            key: value
            for key, value in safe_stopped_completed.items()
            if key != "content_sha256"
        }
    )
    assert (
        incumbent.validate_benchmark_v2_actual_operations_stable_zero(
            safe_stopped_completed
        )
        == safe_stopped_completed
    )

    active = _stable_receipt(hybrid_status="pending")
    with pytest.raises(ValueError, match="active operation"):
        incumbent.validate_benchmark_v2_actual_operations_stable_zero(active)

    cross_worker = deepcopy(receipt)
    cleanup = deepcopy(cross_worker["cleanup_entries"][1]["worker_cleanup_ref"])
    cleanup["worker_id"] = "worker-elsewhere"
    cross_worker["cleanup_entries"][1]["worker_cleanup_ref"] = seal_immutable(
        {key: value for key, value in cleanup.items() if key != "content_sha256"}
    )
    cross_worker = seal_immutable(
        {key: value for key, value in cross_worker.items() if key != "content_sha256"}
    )
    with pytest.raises(
        ValueError,
        match="(terminal cleanup lineage|worker cleanup) is stale",
    ):
        incumbent.validate_benchmark_v2_actual_operations_stable_zero(cross_worker)

    aggregate = deepcopy(receipt)
    aggregate["cleanup_entries"][1]["worker_cleanup_ref"] = seal_immutable(
        {"cleanup_status": "stable_zero"}
    )
    aggregate = seal_immutable(
        {key: value for key, value in aggregate.items() if key != "content_sha256"}
    )
    with pytest.raises(
        ValueError,
        match="(terminal cleanup lineage|worker cleanup) is stale",
    ):
        incumbent.validate_benchmark_v2_actual_operations_stable_zero(aggregate)


def test_stable_zero_validator_accepts_only_exact_fusion_safe_stop_cleanup() -> None:
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import (
        _actual_fusion_safe_stop_cleanup,
        _actual_fusion_safe_stop_step,
    )

    fusion_step = _actual_fusion_safe_stop_step(
        {"request_ref": {"id": "request-0", "content_sha256": SHA_A}},
        {
            "run_id": "parent-run",
            "stage": "screen_understanding",
            "operation_id": "parent-operation",
            "window_binding_ref": {"id": "window-1", "content_sha256": SHA_A},
            "capture_ref": {"id": "capture-1", "content_sha256": SHA_B},
        },
    )
    operation = fusion_step["operation_ref"]
    cleanup = _actual_fusion_safe_stop_cleanup(operation)
    receipt = deepcopy(_stable_receipt())
    receipt["operation_refs"][0] = operation
    receipt["cleanup_entries"][0] = {
        "operation_ref_sha256": operation["content_sha256"],
        "terminal_receipt_ref": seal_immutable(
            {
                "run_id": operation["run_id"],
                "stage": operation["stage"],
                "operation_id": operation["operation_id"],
                "worker_id": operation["worker_ref"]["worker_id"],
            }
        ),
        "worker_cleanup_ref": cleanup["worker_cleanup_ref"],
        "provider_cleanup_ref": cleanup[
            "fusion_direct_provider_cleanup_ref"
        ],
    }
    receipt = seal_immutable(
        {key: value for key, value in receipt.items() if key != "content_sha256"}
    )

    assert incumbent.validate_benchmark_v2_actual_operations_stable_zero(receipt) == receipt

    for mutation in ("nonfusion", "complete", "cross_lineage"):
        malformed = deepcopy(receipt)
        if mutation == "nonfusion":
            malformed["operation_refs"][0]["worker_ref"]["task_kind"] = (
                "panel_learning_hybrid_qwen_binding"
            )
            malformed["operation_refs"][0]["worker_ref"] = seal_immutable(
                {
                    key: value
                    for key, value in malformed["operation_refs"][0]["worker_ref"].items()
                    if key != "content_sha256"
                }
            )
        elif mutation == "complete":
            malformed["operation_refs"][0]["status"] = "complete"
        else:
            malformed["cleanup_entries"][0]["provider_cleanup_ref"][
                "operation_id"
            ] = "foreign-operation"
            malformed["cleanup_entries"][0]["provider_cleanup_ref"] = seal_immutable(
                {
                    key: value
                    for key, value in malformed["cleanup_entries"][0][
                        "provider_cleanup_ref"
                    ].items()
                    if key != "content_sha256"
                }
            )
        if mutation in {"nonfusion", "complete"}:
            malformed["operation_refs"][0] = seal_immutable(
                {
                    key: value
                    for key, value in malformed["operation_refs"][0].items()
                    if key != "content_sha256"
                }
            )
            malformed["cleanup_entries"][0]["operation_ref_sha256"] = malformed[
                "operation_refs"
            ][0]["content_sha256"]
        malformed = seal_immutable(
            {key: value for key, value in malformed.items() if key != "content_sha256"}
        )
        with pytest.raises(ValueError):
            incumbent.validate_benchmark_v2_actual_operations_stable_zero(malformed)
