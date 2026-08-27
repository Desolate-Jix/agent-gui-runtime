"""通过 WorkflowService 公共边界运行 Benchmark-v2 的四臂屏幕组。"""

from __future__ import annotations

from copy import deepcopy
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
    expected_operation_id: str | None,
    predecessor_step: Mapping[str, object] | None,
) -> dict[str, Any]:
    step = validate_benchmark_v2_workflow_service_step(value)
    operation = step["operation_ref"]
    if step["mode"] != expected_mode:
        raise ValueError("benchmark service step mode is stale")
    for name in ("run_id", "stage"):
        if operation[name] != binding[name]:
            raise ValueError(f"benchmark service step {name} is stale")
    if operation["window_binding_ref"] != binding["window_binding_ref"]:
        raise ValueError("benchmark service step window binding is stale")
    if operation["capture_ref"] != binding["capture_ref"]:
        raise ValueError("benchmark service step capture ref is stale")
    if expected_mode == "hybrid_v1_1" and operation["operation_id"] != binding[
        "operation_id"
    ]:
        raise ValueError("benchmark Hybrid operation identity is stale")
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
    hybrid_evidence = _extract_hybrid_evidence(hybrid_terminal, group=group)
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
        arms = {
            "qwen_only": {"response": deepcopy(projection["response"])},
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
) -> dict[str, dict[str, Any]]:
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
    ] or orchestration.get("capture_bundle") != group["capture_bundle"]:
        raise ValueError("Hybrid terminal capture parents are stale")
    if (
        review.get("outcome") != "completed"
        or review.get("review_status") != "REVIEW_REQUIRED"
        or review.get("automatic_acceptance") is not False
        or review.get("execute_binding_enabled") is not False
        or review.get("no_live_click_authorization") is not True
        or not isinstance(review.get("proposals"), list)
    ):
        raise ValueError("Hybrid terminal review projection is invalid")
    omni = _mapping(orchestration.get("omni_inventory"), "Omni inventory")
    qwen = _mapping(orchestration.get("qwen_bindings"), "Qwen bindings")
    fusion = _mapping(orchestration.get("fusion_result"), "fusion result")
    return {
        "omni_only_discovery": {"omni_inventory": omni},
        "omni_to_qwen": {
            "omni_inventory": deepcopy(omni),
            "qwen_bindings": qwen,
            "fusion_result": fusion,
        },
        "omni_to_qwen_vista": {
            "omni_inventory": deepcopy(omni),
            "qwen_bindings": deepcopy(qwen),
            "fusion_result": deepcopy(fusion),
            "review_projection": deepcopy(dict(review)),
        },
    }


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
