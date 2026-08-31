"""通过 WorkflowService 公共边界运行 Benchmark-v2 的四臂屏幕组。"""

from __future__ import annotations

import base64
from copy import deepcopy
from hashlib import sha256
import time
from typing import Any, Mapping, Protocol

from app.learn.hybrid.benchmark_v2_contracts import (
    BENCHMARK_RELEASE_ID,
    canonical_json_bytes,
    content_sha256,
)
from app.learn.hybrid.benchmark_v2_incumbent_operation import (
    validate_benchmark_v2_hybrid_screen_group_start,
    validate_benchmark_v2_workflow_service_step,
    validate_benchmark_v2_workflow_window_binding,
)
from app.learn.hybrid.contracts import (
    validate_fusion_result,
    validate_qwen_bindings,
)
from app.learn.hybrid.omni_candidates import validate_current_capture_bundle
from app.learn.hybrid.qwen_binding import validate_sealed_omni_inventory
from app.learn.hybrid.vista_refinement import build_vista_requests
from app.learn.recognition.uei.canonical import (
    content_sha256 as uei_content_sha256,
)


_ARM_IDS = (
    "qwen_only",
    "omni_only_discovery",
    "omni_to_qwen",
    "omni_to_qwen_vista",
)
_NONTERMINAL = frozenset({"pending", "advanced"})
_TERMINAL = frozenset({"complete", "safe_stopped", "cancelled"})
_POLL_TIMEOUT_SECONDS = 900.0
_POLL_INITIAL_INTERVAL_SECONDS = 0.05
_POLL_MAX_INTERVAL_SECONDS = 1.0
_MAX_PUBLIC_STEPS = 100_000
_monotonic = time.monotonic
_sleep = time.sleep
_SAFETY = {
    "artifact_is_authorization": False,
    "execute_binding_enabled": False,
}


class WorkflowServicePort(Protocol):
    def start_hybrid_operation(
        self,
        *,
        screen_group: Mapping[str, object],
        window_binding: Mapping[str, object],
    ) -> Mapping[str, object]: ...

    def continue_hybrid_operation(
        self,
        *,
        operation_ref: Mapping[str, object],
    ) -> Mapping[str, object]: ...

    def start_incumbent_observe(
        self,
        *,
        provider_case_ref: Mapping[str, object],
        window_binding: Mapping[str, object],
    ) -> Mapping[str, object]: ...

    def poll_incumbent_observe(
        self,
        *,
        operation_ref: Mapping[str, object],
    ) -> Mapping[str, object]: ...

    def adopt_and_terminalize_incumbent(
        self,
        *,
        operation_ref: Mapping[str, object],
        worker_ref: Mapping[str, object],
    ) -> Mapping[str, object]: ...

    def cancel_operation(
        self,
        *,
        operation_ref: Mapping[str, object],
    ) -> Mapping[str, object]: ...


def run_screen_group(
    *,
    provider_group: Mapping[str, object],
    service: WorkflowServicePort,
    window_owner: object,
    lifecycle: object,
    prediction_sink: object,
) -> dict[str, object]:
    """运行一个屏幕组；服务独占阶段选择、版本推进与结果接纳。"""

    group = validate_benchmark_v2_hybrid_screen_group_start(provider_group)
    binding: dict[str, Any] | None = None
    latest_operations: dict[str, dict[str, Any]] = {}
    terminal_steps: list[dict[str, Any]] = []
    hybrid_terminal: dict[str, Any] | None = None
    primary_error: BaseException | None = None
    cleanup_errors: list[BaseException] = []
    close_ref: dict[str, Any] | None = None
    lifecycle_ref: dict[str, Any] | None = None

    try:
        binding = validate_benchmark_v2_workflow_window_binding(
            _call_port(
                window_owner,
                "open_screen_group",
                provider_group=deepcopy(group),
            )
        )
        hybrid_terminal = _run_hybrid(
            group=group,
            binding=binding,
            service=service,
            latest_operations=latest_operations,
        )
        terminal_steps.append(hybrid_terminal)
        for case_ref in group["case_refs"]:
            terminal = _run_incumbent(
                case_ref=case_ref,
                binding=binding,
                service=service,
                latest_operations=latest_operations,
            )
            terminal_steps.append(terminal)
    except BaseException as exc:
        primary_error = exc
    finally:
        for key in list(latest_operations):
            operation_ref = latest_operations[key]
            try:
                service.cancel_operation(operation_ref=deepcopy(operation_ref))
            except BaseException as exc:
                cleanup_errors.append(exc)
        if binding is not None:
            try:
                close_ref = _sealed_parent(
                    _call_port(
                        window_owner,
                        "close_screen_group",
                        window_binding=deepcopy(binding),
                        reason="benchmark_v2_screen_group_finished",
                    ),
                    "benchmark window close ref",
                )
            except BaseException as exc:
                cleanup_errors.append(exc)
            if len(terminal_steps) == 6 and close_ref is not None:
                try:
                    lifecycle_ref = _sealed_parent(
                        _call_port(
                            lifecycle,
                            "stable_zero",
                            provider_group=deepcopy(group),
                            window_binding=deepcopy(binding),
                            execution_refs=[
                                _execution_ref(step["operation_ref"])
                                for step in terminal_steps
                            ],
                            window_close_ref=deepcopy(close_ref),
                        ),
                        "benchmark lifecycle ref",
                    )
                except BaseException as exc:
                    cleanup_errors.append(exc)

    if primary_error is not None:
        for cleanup_error in cleanup_errors:
            primary_error.add_note(f"benchmark cleanup failed: {cleanup_error}")
        raise primary_error
    if cleanup_errors:
        raise ExceptionGroup("benchmark screen-group cleanup failed", cleanup_errors)
    if binding is None or close_ref is None or lifecycle_ref is None:
        raise RuntimeError("benchmark screen-group cleanup evidence is incomplete")
    if hybrid_terminal is None or len(terminal_steps) != 6:
        raise RuntimeError("benchmark screen-group terminal evidence is incomplete")

    projection = _compose_screen_group_projection(
        group=group,
        binding=binding,
        hybrid_terminal=hybrid_terminal,
        incumbent_terminals=terminal_steps[1:],
        close_ref=close_ref,
        lifecycle_ref=lifecycle_ref,
    )
    _call_port(
        prediction_sink,
        "write_screen_group",
        projection=deepcopy(projection),
    )
    return projection


def _run_hybrid(
    *,
    group: Mapping[str, object],
    binding: Mapping[str, object],
    service: WorkflowServicePort,
    latest_operations: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    step = _validated_service_step(
        service.start_hybrid_operation(
            screen_group=deepcopy(dict(group)),
            window_binding=deepcopy(dict(binding)),
        ),
        expected_mode="hybrid_v1_1",
        binding=binding,
        request_ref=group["request_ref"],
        expected_run_id=None,
        expected_operation_id=None,
        predecessor_step=None,
    )
    operation_id = str(step["operation_ref"]["operation_id"])
    latest_operations["hybrid"] = deepcopy(step["operation_ref"])
    deadline = _monotonic() + _POLL_TIMEOUT_SECONDS
    interval = _POLL_INITIAL_INTERVAL_SECONDS
    for _ in range(_MAX_PUBLIC_STEPS):
        status = step["status"]
        if status == "complete":
            _require_terminal_projection(step, "Hybrid")
            return step
        if status in _TERMINAL:
            raise ValueError(f"Hybrid operation stopped without a complete result: {status}")
        if status not in _NONTERMINAL:
            raise ValueError(f"Hybrid operation returned unsupported status: {status}")
        if status == "pending":
            interval = _wait_for_next_poll(
                deadline=deadline,
                interval=interval,
                label="Hybrid operation",
            )
        previous_step = deepcopy(step)
        consumed = deepcopy(step["operation_ref"])
        returned = service.continue_hybrid_operation(operation_ref=consumed)
        step = _validated_service_step(
            returned,
            expected_mode="hybrid_v1_1",
            binding=binding,
            request_ref=group["request_ref"],
            expected_run_id=str(step["operation_ref"]["run_id"]),
            expected_operation_id=operation_id,
            predecessor_step=previous_step,
        )
        if step["operation_ref"]["content_sha256"] != consumed["content_sha256"]:
            interval = _POLL_INITIAL_INTERVAL_SECONDS
        latest_operations["hybrid"] = deepcopy(step["operation_ref"])
    raise RuntimeError("Hybrid operation exceeded the bounded public continuation limit")


def _run_incumbent(
    *,
    case_ref: Mapping[str, object],
    binding: Mapping[str, object],
    service: WorkflowServicePort,
    latest_operations: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    key = f"incumbent/{case_ref['case_id']}"
    expected_request_ref = {
        "id": str(case_ref["case_id"]),
        "content_sha256": str(case_ref["case_content_sha256"]),
    }
    step = _validated_service_step(
        service.start_incumbent_observe(
            provider_case_ref=deepcopy(dict(case_ref)),
            window_binding=deepcopy(dict(binding)),
        ),
        expected_mode="incumbent_qwen_only",
        binding=binding,
        request_ref=expected_request_ref,
        expected_run_id=None,
        expected_operation_id=None,
        predecessor_step=None,
    )
    _require_incumbent_observe_step(step)
    operation_id = str(step["operation_ref"]["operation_id"])
    latest_operations[key] = deepcopy(step["operation_ref"])
    deadline = _monotonic() + _POLL_TIMEOUT_SECONDS
    interval = _POLL_INITIAL_INTERVAL_SECONDS
    for _ in range(_MAX_PUBLIC_STEPS):
        status = step["status"]
        if status == "complete":
            _require_terminal_projection(step, "incumbent")
            return step
        if status in _TERMINAL:
            raise ValueError(
                f"incumbent operation stopped without a complete result: {status}"
            )
        if status == "pending":
            interval = _wait_for_next_poll(
                deadline=deadline,
                interval=interval,
                label="incumbent operation",
            )
            previous_step = deepcopy(step)
            consumed = deepcopy(step["operation_ref"])
            returned = service.poll_incumbent_observe(operation_ref=consumed)
            step = _validated_service_step(
                returned,
                expected_mode="incumbent_qwen_only",
                binding=binding,
                request_ref=consumed["request_ref"],
                expected_run_id=str(consumed["run_id"]),
                expected_operation_id=operation_id,
                predecessor_step=previous_step,
            )
            _require_incumbent_observe_step(step)
            if step["operation_ref"]["content_sha256"] != consumed["content_sha256"]:
                interval = _POLL_INITIAL_INTERVAL_SECONDS
            latest_operations[key] = deepcopy(step["operation_ref"])
            continue
        if status == "advanced":
            worker_ref = step.get("worker_ref")
            if not isinstance(worker_ref, Mapping):
                raise ValueError("incumbent advanced step lost its worker ref")
            previous_step = deepcopy(step)
            consumed = deepcopy(step["operation_ref"])
            returned = service.adopt_and_terminalize_incumbent(
                operation_ref=consumed,
                worker_ref=deepcopy(dict(worker_ref)),
            )
            step = _validated_service_step(
                returned,
                expected_mode="incumbent_qwen_only",
                binding=binding,
                request_ref=consumed["request_ref"],
                expected_run_id=str(consumed["run_id"]),
                expected_operation_id=operation_id,
                predecessor_step=previous_step,
            )
            _require_incumbent_observe_step(step)
            latest_operations[key] = deepcopy(step["operation_ref"])
            continue
        raise ValueError(f"incumbent operation returned unsupported status: {status}")
    raise RuntimeError("incumbent operation exceeded the bounded public polling limit")


def _validated_service_step(
    value: object,
    *,
    expected_mode: str,
    binding: Mapping[str, object],
    request_ref: Mapping[str, object] | None,
    expected_run_id: str | None,
    expected_operation_id: str | None,
    predecessor_step: Mapping[str, object] | None,
) -> dict[str, Any]:
    step = validate_benchmark_v2_workflow_service_step(value)
    operation = step["operation_ref"]
    if step["mode"] != expected_mode:
        raise ValueError("benchmark service step mode is stale")
    if operation["stage"] != binding["stage"]:
        raise ValueError("benchmark service step stage is stale")
    if operation["window_binding_ref"] != binding["window_binding_ref"]:
        raise ValueError("benchmark service step window binding is stale")
    if operation["capture_ref"] != binding["capture_ref"]:
        raise ValueError("benchmark service step capture ref is stale")
    if expected_mode == "hybrid_v1_1" and (
        operation["run_id"] != binding["run_id"]
        or operation["operation_id"] != binding["operation_id"]
    ):
        raise ValueError("benchmark Hybrid operation identity is stale")
    if expected_run_id is not None and operation["run_id"] != expected_run_id:
        raise ValueError("benchmark service successor run identity is stale")
    if (
        expected_operation_id is not None
        and operation["operation_id"] != expected_operation_id
    ):
        raise ValueError("benchmark service successor operation identity is stale")
    if request_ref is not None and operation["request_ref"] != request_ref:
        raise ValueError("benchmark service step request ref is stale")
    if predecessor_step is not None:
        predecessor = predecessor_step["operation_ref"]
        same_ref = operation["content_sha256"] == predecessor["content_sha256"]
        if same_ref:
            if canonical_json_bytes(step) != canonical_json_bytes(predecessor_step):
                raise ValueError(
                    "benchmark service same-ref replay is not byte-identical"
                )
        elif _is_incumbent_read_only_poll_transition(
            predecessor_step=predecessor_step,
            successor_step=step,
        ):
            pass
        elif _is_incumbent_durable_projection_successor_step(
            predecessor_step=predecessor_step,
            successor_step=step,
        ):
            pass
        elif operation["predecessor_content_sha256"] != predecessor[
            "content_sha256"
        ]:
            raise ValueError("benchmark service step predecessor is stale")
        else:
            for name in ("workflow_state_ref", "stage_execution_ref"):
                if operation[name]["revision"] <= predecessor[name]["revision"]:
                    raise ValueError(
                        f"benchmark service successor {name} revision did not advance"
                    )
    return step


def _is_incumbent_read_only_poll_transition(
    *,
    predecessor_step: Mapping[str, object],
    successor_step: Mapping[str, object],
) -> bool:
    if (
        predecessor_step.get("mode") != "incumbent_qwen_only"
        or successor_step.get("mode") != "incumbent_qwen_only"
        or predecessor_step.get("status") != "pending"
        or successor_step.get("status") != "advanced"
    ):
        return False
    predecessor_operation = predecessor_step.get("operation_ref")
    successor_operation = successor_step.get("operation_ref")
    if not isinstance(predecessor_operation, Mapping) or not isinstance(
        successor_operation, Mapping
    ):
        return False
    stable_predecessor_operation = {
        name: deepcopy(value)
        for name, value in predecessor_operation.items()
        if name not in {"status", "content_sha256"}
    }
    stable_successor_operation = {
        name: deepcopy(value)
        for name, value in successor_operation.items()
        if name not in {"status", "content_sha256"}
    }
    if stable_successor_operation != stable_predecessor_operation:
        return False
    stable_predecessor_step = {
        name: deepcopy(value)
        for name, value in predecessor_step.items()
        if name not in {"status", "operation_ref", "content_sha256"}
    }
    stable_successor_step = {
        name: deepcopy(value)
        for name, value in successor_step.items()
        if name not in {"status", "operation_ref", "content_sha256"}
    }
    if stable_successor_step != stable_predecessor_step:
        return False
    return (
        successor_step.get("adopted_result_projection") is None
        and successor_step.get("terminal_receipt") is None
        and successor_step.get("cleanup_refs")
        == {"worker_cleanup_ref": None, "provider_cleanup_ref": None}
    )


def _is_incumbent_durable_projection_successor_step(
    *,
    predecessor_step: Mapping[str, object],
    successor_step: Mapping[str, object],
) -> bool:
    predecessor_operation = predecessor_step.get("operation_ref")
    successor_operation = successor_step.get("operation_ref")
    if not isinstance(predecessor_operation, Mapping) or not isinstance(
        successor_operation, Mapping
    ):
        return False
    stable_step_fields = (
        "mode",
        "worker_ref",
        "observed_task_kind",
        "provider_dispatch_context_projection",
        "artifact_is_authorization",
        "execute_binding_enabled",
    )
    if not all(
        successor_step.get(name) == predecessor_step.get(name)
        for name in stable_step_fields
    ):
        return False
    if successor_operation.get("status") in {"advanced", "cleanup_pending"} and (
        successor_step.get("adopted_result_projection") is not None
        or successor_step.get("terminal_receipt") is not None
        or successor_step.get("cleanup_refs")
        != {"worker_cleanup_ref": None, "provider_cleanup_ref": None}
    ):
        return False
    return _is_incumbent_durable_projection_successor_operation(
        predecessor_operation=predecessor_operation,
        successor_operation=successor_operation,
    )


def _is_incumbent_durable_projection_successor_operation(
    *,
    predecessor_operation: Mapping[str, object],
    successor_operation: Mapping[str, object],
) -> bool:
    allowed_status_transitions = {
        "pending": {"advanced", "cleanup_pending", "cancelled", "safe_stopped"},
        "advanced": {
            "advanced",
            "complete",
            "cleanup_pending",
            "cancelled",
            "safe_stopped",
        },
        "cleanup_pending": {"cleanup_pending", "cancelled", "safe_stopped"},
    }
    predecessor_status = predecessor_operation.get("status")
    successor_status = successor_operation.get("status")
    if (
        predecessor_operation.get("mode") != "incumbent_qwen_only"
        or successor_operation.get("mode") != "incumbent_qwen_only"
        or successor_status not in allowed_status_transitions.get(
            predecessor_status, set()
        )
    ):
        return False
    immutable = (
        "contract_version",
        "mode",
        "run_id",
        "stage",
        "operation_id",
        "request_ref",
        "window_binding_ref",
        "capture_ref",
        "worker_ref",
        "artifact_is_authorization",
        "execute_binding_enabled",
    )
    if any(
        successor_operation.get(name) != predecessor_operation.get(name)
        for name in immutable
    ):
        return False
    for name in ("workflow_state_ref", "stage_execution_ref"):
        predecessor_ref = predecessor_operation.get(name)
        successor_ref = successor_operation.get(name)
        if not isinstance(predecessor_ref, Mapping) or not isinstance(
            successor_ref, Mapping
        ):
            return False
        if successor_ref.get("revision", -1) <= predecessor_ref.get("revision", -1):
            return False
        if successor_ref.get("content_sha256") == predecessor_ref.get(
            "content_sha256"
        ):
            return False
    return True


def _wait_for_next_poll(*, deadline: float, interval: float, label: str) -> float:
    remaining = deadline - _monotonic()
    if remaining <= 0:
        raise TimeoutError(f"{label} exceeded its monotonic deadline")
    delay = min(max(interval, _POLL_INITIAL_INTERVAL_SECONDS), remaining)
    if delay <= 0:
        raise TimeoutError(f"{label} exceeded its monotonic deadline")
    _sleep(delay)
    if _monotonic() >= deadline:
        raise TimeoutError(f"{label} exceeded its monotonic deadline")
    return min(delay * 2.0, _POLL_MAX_INTERVAL_SECONDS)


def _require_terminal_projection(step: Mapping[str, object], label: str) -> None:
    if not isinstance(step.get("adopted_result_projection"), Mapping):
        raise ValueError(f"{label} terminal step lost its adopted response")


def _require_incumbent_observe_step(step: Mapping[str, object]) -> None:
    if step.get("observed_task_kind") != "vision_observe_screen":
        raise ValueError("incumbent operation escaped its single-observe task")


def _compose_screen_group_projection(
    *,
    group: Mapping[str, object],
    binding: Mapping[str, object],
    hybrid_terminal: Mapping[str, object],
    incumbent_terminals: list[Mapping[str, object]],
    close_ref: Mapping[str, object],
    lifecycle_ref: Mapping[str, object],
) -> dict[str, Any]:
    if len(incumbent_terminals) != len(group["case_refs"]):
        raise ValueError("incumbent terminal target multiset is incomplete")
    hybrid_evidence, pre_vista_evidence = _extract_hybrid_evidence(
        hybrid_terminal,
        group=group,
    )
    shared_parent_refs = {
        "screen_group_ref": {
            "id": str(group["screen_group"]),
            "content_sha256": str(group["content_sha256"]),
        },
        "hybrid_capture_bundle_ref": deepcopy(group["hybrid_capture_bundle_ref"]),
        "window_binding_ref": deepcopy(binding["window_binding_ref"]),
        "capture_ref": deepcopy(binding["capture_ref"]),
        "owner_journal_ref": deepcopy(binding["owner_journal_ref"]),
        "expected_uia_root_ref": deepcopy(binding["expected_uia_root_ref"]),
    }
    rows: list[dict[str, Any]] = []
    for case_ref, incumbent_step in zip(
        group["case_refs"], incumbent_terminals, strict=True
    ):
        projection = incumbent_step["adopted_result_projection"]
        if not isinstance(projection, Mapping):
            raise ValueError("incumbent terminal target projection is missing")
        incumbent_response = _mapping(
            projection["response"], "incumbent Qwen response"
        )
        incumbent_dispatch_refs = _dispatch_receipt_refs(
            incumbent_response.pop(
                "_benchmark_v2_provider_dispatch_receipt_refs", None
            ),
            expected_providers={"qwen"},
        )
        arms = {
            "qwen_only": {
                "response": incumbent_response,
                "provider_dispatch_receipt_refs": incumbent_dispatch_refs,
            },
            **hybrid_evidence,
        }
        for arm_id in _ARM_IDS:
            rows.append(
                {
                    "case_ref": deepcopy(case_ref),
                    "arm_id": arm_id,
                    "observation": deepcopy(arms[arm_id]),
                    "execution_ref": _execution_ref(
                        incumbent_step["operation_ref"]
                        if arm_id == "qwen_only"
                        else hybrid_terminal["operation_ref"]
                    ),
                    "shared_parent_refs": deepcopy(shared_parent_refs),
                    **deepcopy(_SAFETY),
                }
            )
    expected_pairs = {
        (item["case_id"], arm_id)
        for item in group["case_refs"]
        for arm_id in _ARM_IDS
    }
    if {(row["case_ref"]["case_id"], row["arm_id"]) for row in rows} != expected_pairs:
        raise ValueError("benchmark four-arm target multiset is incomplete")
    body = {
        "contract_version": "benchmark_v2_actual_screen_group_projection_v1",
        "benchmark_release_id": BENCHMARK_RELEASE_ID,
        "partition": str(group["partition"]),
        "screen_group": str(group["screen_group"]),
        "request_ref": deepcopy(group["request_ref"]),
        "shared_parent_refs": shared_parent_refs,
        "pre_vista_evidence": pre_vista_evidence,
        "rows": rows,
        "execution_refs": [
            _execution_ref(hybrid_terminal["operation_ref"]),
            *[
                _execution_ref(step["operation_ref"])
                for step in incumbent_terminals
            ],
        ],
        "window_close_ref": deepcopy(dict(close_ref)),
        "lifecycle_ref": deepcopy(dict(lifecycle_ref)),
        **deepcopy(_SAFETY),
    }
    result = deepcopy(body)
    result["content_sha256"] = content_sha256(result)
    return result


def _extract_hybrid_evidence(
    terminal: Mapping[str, object],
    *,
    group: Mapping[str, object],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    projection = terminal.get("adopted_result_projection")
    response = projection.get("response") if isinstance(projection, Mapping) else None
    if not isinstance(response, Mapping):
        raise ValueError("Hybrid terminal response is missing")
    if (
        response.get("contract_version")
        != "learning_hybrid_managed_stage_result_v1"
        or
        response.get("learning_pipeline_mode") != "hybrid_v1_1"
        or response.get("task_kind")
        != "panel_learning_hybrid_review_projection"
        or response.get("outcome") != "completed"
    ):
        raise ValueError("Hybrid terminal response is not complete")
    orchestration = response.get("orchestration")
    review = response.get("result")
    if not isinstance(orchestration, Mapping) or not isinstance(review, Mapping):
        raise ValueError("Hybrid terminal response lost its server projection")
    if orchestration.get("hybrid_capture_bundle_ref") != group[
        "hybrid_capture_bundle_ref"
    ]:
        raise ValueError("Hybrid terminal capture parents are stale")
    capture_bundle = validate_current_capture_bundle(
        _mapping(orchestration.get("capture_bundle"), "capture bundle")
    )
    if canonical_json_bytes(capture_bundle) != canonical_json_bytes(
        group["capture_bundle"]
    ):
        raise ValueError("Hybrid terminal capture parents are stale")
    omni = _mapping(orchestration.get("omni_inventory"), "Omni inventory")
    validated_omni = validate_sealed_omni_inventory(omni)
    qwen = _mapping(orchestration.get("qwen_bindings"), "Qwen bindings")
    validated_qwen = validate_qwen_bindings(
        _unseal_for_closed_validator(qwen, "Qwen bindings"),
        validated_omni,
    )
    fusion = _mapping(orchestration.get("fusion_result"), "fusion result")
    validate_fusion_result(
        _unseal_for_closed_validator(fusion, "fusion result"),
        validated_omni,
        validated_qwen,
    )
    from app.core.model_server import validate_qwen_cleanup_receipt

    qwen_cleanup_receipt = validate_qwen_cleanup_receipt(
        _mapping(
            orchestration.get("qwen_cleanup_receipt"),
            "Qwen cleanup receipt",
        )
    )
    workflow_revision = orchestration.get("workflow_revision")
    if (
        isinstance(workflow_revision, bool)
        or not isinstance(workflow_revision, int)
        or workflow_revision != capture_bundle["workflow_revision"]
    ):
        raise ValueError("Hybrid workflow revision is stale")
    raw_vista_requests = orchestration.get("hybrid_vista_requests")
    if not isinstance(raw_vista_requests, list):
        raise ValueError("Hybrid exact submitted VISTA requests are missing")
    submitted_vista_requests = [
        _mapping(item, "submitted VISTA request") for item in raw_vista_requests
    ]
    expected_vista_requests = build_vista_requests(
        fusion,
        capture_bundle,
        omni_inventory=omni,
        qwen_bindings=qwen,
        qwen_cleanup_receipt=qwen_cleanup_receipt,
        expected_workflow_revision=workflow_revision,
    )
    if len(submitted_vista_requests) != len(expected_vista_requests) or any(
        canonical_json_bytes(propagated) != canonical_json_bytes(expected)
        for propagated, expected in zip(
            submitted_vista_requests,
            expected_vista_requests,
            strict=True,
        )
    ):
        raise ValueError(
            "Hybrid propagated VISTA requests differ from exact calibration output"
        )
    _require_exact_bound_request_coverage(
        fusion=fusion,
        submitted_vista_requests=submitted_vista_requests,
    )
    pre_vista_evidence = _compose_pre_vista_evidence(
        group=group,
        omni_inventory=omni,
        qwen_bindings=qwen,
        fusion_result=fusion,
        submitted_vista_requests=submitted_vista_requests,
    )
    if (
        review.get("outcome") != "completed"
        or review.get("review_status") != "REVIEW_REQUIRED"
        or review.get("automatic_acceptance") is not False
        or review.get("execute_binding_enabled") is not False
        or review.get("no_live_click_authorization") is not True
        or not isinstance(review.get("proposals"), list)
    ):
        raise ValueError("Hybrid terminal review projection is invalid")
    dispatch_refs = _dispatch_receipt_refs(
        orchestration.get("benchmark_v2_provider_dispatch_receipt_refs"),
        expected_providers={"omni", "qwen", "vista"},
    )
    omni_refs = [item for item in dispatch_refs if item["provider"] == "omni"]
    omni_qwen_refs = [
        item for item in dispatch_refs if item["provider"] in {"omni", "qwen"}
    ]
    arms = {
        "omni_only_discovery": {
            "omni_inventory": omni,
            "provider_dispatch_receipt_refs": omni_refs,
        },
        "omni_to_qwen": {
            "omni_inventory": deepcopy(omni),
            "qwen_bindings": qwen,
            "fusion_result": fusion,
            "provider_dispatch_receipt_refs": omni_qwen_refs,
        },
        "omni_to_qwen_vista": {
            "omni_inventory": deepcopy(omni),
            "qwen_bindings": deepcopy(qwen),
            "fusion_result": deepcopy(fusion),
            "review_projection": deepcopy(dict(review)),
            "provider_dispatch_receipt_refs": dispatch_refs,
        },
    }
    return arms, pre_vista_evidence


def _require_exact_bound_request_coverage(
    *,
    fusion: Mapping[str, object],
    submitted_vista_requests: list[Mapping[str, object]],
) -> None:
    candidates = fusion.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("Hybrid fusion candidates are missing")
    bound_ids: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            raise ValueError("Hybrid fusion candidate is invalid")
        if candidate.get("state") == "BOUND":
            candidate_id = candidate.get("candidate_id")
            if not isinstance(candidate_id, str) or not candidate_id:
                raise ValueError("Hybrid BOUND candidate identity is missing")
            bound_ids.append(candidate_id)
    request_ids: list[str] = []
    for request in submitted_vista_requests:
        candidate_id = request.get("candidate_id")
        if (
            not isinstance(candidate_id, str)
            or not candidate_id
            or request.get("submission_status") != "SUBMITTED"
        ):
            raise ValueError("Hybrid submitted VISTA request is invalid")
        request_ids.append(candidate_id)
    if (
        len(set(bound_ids)) != len(bound_ids)
        or len(set(request_ids)) != len(request_ids)
        or sorted(request_ids) != sorted(bound_ids)
    ):
        raise ValueError("Hybrid submitted VISTA requests do not cover exact BOUND candidates")


def _compose_pre_vista_evidence(
    *,
    group: Mapping[str, object],
    omni_inventory: Mapping[str, object],
    qwen_bindings: Mapping[str, object],
    fusion_result: Mapping[str, object],
    submitted_vista_requests: list[Mapping[str, object]],
) -> dict[str, Any]:
    sorted_requests = sorted(
        (deepcopy(dict(item)) for item in submitted_vista_requests),
        key=lambda item: str(item["candidate_id"]),
    )
    body = {
        "contract_version": "benchmark_v2_actual_pre_vista_evidence_v1",
        "provider_group_ref": {
            "id": str(group["screen_group"]),
            "content_sha256": str(group["content_sha256"]),
        },
        "omni_inventory_envelope": _raw_class_envelope(
            omni_inventory,
            id_prefix="omni-inventory",
            domain=b"benchmark-v2-omni-inventory\0",
        ),
        "qwen_bindings_envelope": _raw_class_envelope(
            qwen_bindings,
            id_prefix="qwen-bindings",
            domain=b"benchmark-v2-qwen-bindings\0",
        ),
        "fusion_result_envelope": _raw_class_envelope(
            fusion_result,
            id_prefix="fusion-result",
            domain=b"benchmark-v2-fusion-result\0",
        ),
        "submitted_vista_request_envelopes": [
            _raw_class_envelope(
                request,
                id_prefix="submitted-vista-request",
                domain=b"benchmark-v2-submitted-vista-request\0",
            )
            for request in sorted_requests
        ],
        "safety": deepcopy(_SAFETY),
    }
    result = deepcopy(body)
    result["content_sha256"] = content_sha256(result)
    return result


def _raw_class_envelope(
    value: Mapping[str, object],
    *,
    id_prefix: str,
    domain: bytes,
) -> dict[str, object]:
    canonical_bytes = canonical_json_bytes(dict(value))
    return {
        "ref": {
            "id": f"{id_prefix}/{sha256(domain + canonical_bytes).hexdigest()}",
            "content_sha256": sha256(canonical_bytes).hexdigest(),
        },
        "canonical_bytes_b64": base64.b64encode(canonical_bytes).decode("ascii"),
    }


def _unseal_for_closed_validator(
    value: Mapping[str, object],
    name: str,
) -> dict[str, Any]:
    sealed = deepcopy(dict(value))
    declared = sealed.pop("content_sha256", None)
    if not isinstance(declared, str) or declared != uei_content_sha256(dict(value)):
        raise ValueError(f"Hybrid {name} content_sha256 is invalid")
    return sealed


def _dispatch_receipt_refs(
    value: object, *, expected_providers: set[str]
) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValueError("provider dispatch receipt refs are missing")
    refs: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {
            "provider",
            "content_sha256",
        }:
            raise ValueError("provider dispatch receipt ref is invalid")
        provider = item.get("provider")
        digest = item.get("content_sha256")
        if (
            provider not in expected_providers
            or not isinstance(digest, str)
            or len(digest) != 64
        ):
            raise ValueError("provider dispatch receipt ref is stale")
        refs.append({"provider": str(provider), "content_sha256": digest})
    if {item["provider"] for item in refs} != expected_providers:
        raise ValueError("provider dispatch receipt provider multiset is incomplete")
    if len({item["content_sha256"] for item in refs}) != len(refs):
        raise ValueError("provider dispatch receipt refs are duplicated")
    return refs


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Hybrid {name} is missing")
    return deepcopy(dict(value))


def _execution_ref(operation_ref: Mapping[str, object]) -> dict[str, str]:
    return {
        "id": f"{operation_ref['mode']}/{operation_ref['operation_id']}",
        "content_sha256": str(operation_ref["content_sha256"]),
    }


def _sealed_parent(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a sealed mapping")
    result = deepcopy(dict(value))
    digest = result.get("content_sha256")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError(f"{name} is invalid")
    return result


def _call_port(port: object, method_name: str, **kwargs: object) -> object:
    method = getattr(port, method_name, None)
    if not callable(method):
        raise TypeError(f"benchmark port does not implement {method_name}")
    return method(**kwargs)


__all__ = ["WorkflowServicePort", "run_screen_group"]
