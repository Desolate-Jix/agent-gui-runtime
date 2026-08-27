from __future__ import annotations

from copy import deepcopy
from contextlib import nullcontext
from pathlib import Path

import pytest

from app.learn.hybrid import benchmark_v2_incumbent_operation as incumbent
from app.learn.recognition.uei.canonical import seal_immutable
from app.learn.workflow_service import (
    LearningWorkflowStageOperationError,
    _benchmark_v2_incumbent_child_slot,
    compose_test_learning_workflow_service_unit,
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
        predecessor_content_sha256=None,
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
        entries.append(
            {
                "operation_ref_sha256": operation["content_sha256"],
                "terminal_receipt_ref": seal_immutable(
                    {
                        "run_id": operation["run_id"],
                        "stage": operation["stage"],
                        "operation_id": operation["operation_id"],
                        "worker_id": worker["worker_id"],
                    }
                ),
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
    with pytest.raises(ValueError, match="worker cleanup is stale"):
        incumbent.validate_benchmark_v2_actual_operations_stable_zero(cross_worker)

    aggregate = deepcopy(receipt)
    aggregate["cleanup_entries"][1]["worker_cleanup_ref"] = seal_immutable(
        {"cleanup_status": "stable_zero"}
    )
    aggregate = seal_immutable(
        {key: value for key, value in aggregate.items() if key != "content_sha256"}
    )
    with pytest.raises(ValueError, match="worker cleanup is stale"):
        incumbent.validate_benchmark_v2_actual_operations_stable_zero(aggregate)
