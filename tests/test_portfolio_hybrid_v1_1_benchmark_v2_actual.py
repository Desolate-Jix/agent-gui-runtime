from __future__ import annotations

import ast
import base64
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from app.learn.hybrid import benchmark_v2_incumbent_operation as incumbent
from app.learn.hybrid import benchmark_v2_actual as actual
from app.learn.hybrid.benchmark_v2_actual import (
    WorkflowServicePort,
    run_screen_group,
)
from app.learn.hybrid.benchmark_v2_contracts import content_sha256
from app.learn.hybrid.vista_refinement import build_vista_requests
from app.learn.recognition.uei.canonical import seal_immutable
from tests.test_learn_hybrid_vista_refinement import _authoritative_inputs


SHA_A = "a" * 64
SHA_B = "b" * 64


def _identity(identity: str, digest: str = SHA_A) -> dict[str, object]:
    return {"id": identity, "content_sha256": digest}


def _sealed_parent(kind: str, digest: str = SHA_A) -> dict[str, object]:
    value: dict[str, object] = {"kind": kind, "parent_sha256": digest}
    value["content_sha256"] = content_sha256(value)
    return value


def _provider_group() -> dict[str, object]:
    _, capture_bundle, _, _, _ = _authoritative_inputs()
    return incumbent.compose_benchmark_v2_hybrid_screen_group_start(
        attempt_ref=_sealed_parent("attempt"),
        partition="regression",
        screen_group="screen-group-1",
        provider_corpus_ref=_sealed_parent("provider-corpus"),
        case_refs=[
            {"case_id": f"case-{index}", "case_content_sha256": SHA_A}
            for index in range(5)
        ],
        hybrid_capture_bundle_ref=_identity("capture-bundle"),
        request_ref=_identity("request-1"),
        registration_ref=_identity("registration-1"),
        manifest_ref=_identity("manifest-1"),
        capture_image_path="artifacts/benchmark/screen-group-1.png",
        hybrid_config={"mode": "hybrid_v1_1"},
        capture_bundle=capture_bundle,
    )


def _window_binding() -> dict[str, object]:
    return incumbent.compose_benchmark_v2_workflow_window_binding(
        run_id="run-actual-1",
        operation_id="operation-actual-1",
        window_binding_ref=_identity("window-1"),
        capture_ref=_identity("capture-1", SHA_B),
        owner_journal_ref=_sealed_parent("owner-journal"),
        expected_uia_root_ref=_sealed_parent("uia-root"),
    )


def _operation_ref(
    *,
    mode: str,
    operation_id: str,
    request_ref: Mapping[str, object],
    window_binding: Mapping[str, object],
    worker_ref: Mapping[str, object],
    status: str,
    revision: int,
    predecessor: Mapping[str, object] | None,
    run_id: str | None = None,
) -> dict[str, object]:
    operation_run_id = run_id or str(window_binding["run_id"])
    return incumbent.compose_benchmark_v2_workflow_service_operation_ref(
        mode=mode,
        run_id=operation_run_id,
        stage=str(window_binding["stage"]),
        operation_id=operation_id,
        workflow_state_ref={
            "run_id": operation_run_id,
            "revision": revision,
            "content_sha256": f"{revision % 10}" * 64,
        },
        stage_execution_ref={
            "run_id": operation_run_id,
            "stage": str(window_binding["stage"]),
            "operation_id": operation_id,
            "revision": revision,
            "content_sha256": f"{(revision + 5) % 10}" * 64,
        },
        request_ref=request_ref,
        window_binding_ref=window_binding["window_binding_ref"],
        capture_ref=window_binding["capture_ref"],
        worker_ref=worker_ref,
        status=status,
        predecessor_operation_ref=predecessor,
    )


def _projection(
    *,
    mode: str,
    operation_ref: Mapping[str, object],
    response: Mapping[str, object],
    terminal: bool,
) -> dict[str, object]:
    suffix = str(operation_ref["operation_id"])
    parents = {
        "terminal_receipt": _sealed_parent(f"terminal-{suffix}"),
        "window_adoption_ref": _sealed_parent(f"window-adoption-{suffix}"),
        "worker_cleanup_ref": _sealed_parent(f"worker-cleanup-{suffix}"),
        "provider_cleanup_ref": _sealed_parent(f"provider-cleanup-{suffix}"),
    }
    if not terminal:
        parents = {name: None for name in parents}
    return incumbent.compose_benchmark_v2_adopted_result_projection(
        mode=mode,
        run_id=str(operation_ref["run_id"]),
        stage=str(operation_ref["stage"]),
        operation_id=str(operation_ref["operation_id"]),
        worker_ref=operation_ref["worker_ref"],
        model_request_ref=_identity(f"model-{suffix}"),
        payload_ref={"content_sha256": SHA_A},
        result_ref={"content_sha256": SHA_B},
        adoption_ref=_sealed_parent(f"adoption-{suffix}"),
        response=response,
        **parents,
    )


def _step(
    operation_ref: Mapping[str, object],
    *,
    task_kind: str,
    projection: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return incumbent.compose_benchmark_v2_workflow_service_step(
        operation_ref=operation_ref,
        observed_task_kind=task_kind,
        adopted_result_projection=projection,
        terminal_receipt=(projection or {}).get("terminal_receipt"),
        cleanup_refs={
            "worker_cleanup_ref": (projection or {}).get("worker_cleanup_ref"),
            "provider_cleanup_ref": (projection or {}).get("provider_cleanup_ref"),
        },
    )


def test_incumbent_child_identity_keeps_parent_window_capture_and_case_authority() -> None:
    binding = _window_binding()
    request_ref = _identity("case-child")
    child = _operation_ref(
        mode="incumbent_qwen_only",
        operation_id="incumbent-child-operation",
        request_ref=request_ref,
        window_binding=binding,
        worker_ref=_sealed_parent("incumbent-child-worker"),
        status="pending",
        revision=1,
        predecessor=None,
        run_id="incumbent-child-run",
    )
    step = _step(child, task_kind="vision_observe_screen")

    assert actual._validated_service_step(
        step,
        expected_mode="incumbent_qwen_only",
        binding=binding,
        request_ref=request_ref,
        expected_run_id=None,
        expected_operation_id=None,
        predecessor_step=None,
    ) == step


@pytest.mark.parametrize("fault", ("window", "capture", "request", "child_switch"))
def test_incumbent_child_lineage_drift_is_rejected(fault: str) -> None:
    binding = _window_binding()
    request_ref = _identity("case-child")
    child = _operation_ref(
        mode="incumbent_qwen_only",
        operation_id="incumbent-child-operation",
        request_ref=request_ref,
        window_binding=binding,
        worker_ref=_sealed_parent("incumbent-child-worker"),
        status="pending",
        revision=1,
        predecessor=None,
        run_id="incumbent-child-run",
    )
    predecessor = _step(child, task_kind="vision_observe_screen")
    changed_binding = deepcopy(binding)
    changed_request = request_ref
    next_run_id = str(child["run_id"])
    next_operation_id = str(child["operation_id"])
    if fault == "window":
        changed_binding["window_binding_ref"] = _identity("other-window")
    elif fault == "capture":
        changed_binding["capture_ref"] = _identity("other-capture")
    elif fault == "request":
        changed_request = _identity("other-case")
    else:
        next_run_id = "different-child-run"
        next_operation_id = "different-child-operation"
    successor = _operation_ref(
        mode="incumbent_qwen_only",
        operation_id=next_operation_id,
        request_ref=changed_request,
        window_binding=changed_binding,
        worker_ref=child["worker_ref"],
        status="advanced",
        revision=2,
        predecessor=child,
        run_id=next_run_id,
    )

    with pytest.raises(ValueError, match="window|capture|request|identity|stale"):
        actual._validated_service_step(
            _step(successor, task_kind="vision_observe_screen"),
            expected_mode="incumbent_qwen_only",
            binding=binding,
            request_ref=request_ref,
            expected_run_id=str(child["run_id"]),
            expected_operation_id=str(child["operation_id"]),
            predecessor_step=predecessor,
        )


class _FakeWorkflowService:
    def __init__(
        self,
        *,
        duplicate_reads: bool = False,
        pending_replays: int = 0,
        never_complete_hybrid: bool = False,
        stale_hybrid: bool = False,
        successor_fault: str | None = None,
    ) -> None:
        self.pending_replays = max(pending_replays, 1 if duplicate_reads else 0)
        self.never_complete_hybrid = never_complete_hybrid
        self.stale_hybrid = stale_hybrid
        self.successor_fault = successor_fault
        self.successor_fault_used = False
        self.window_binding: dict[str, object] | None = None
        self.provider_group: dict[str, object] | None = None
        self.hybrid_start_calls = 0
        self.hybrid_continue_calls = 0
        self.hybrid_producer_count = 0
        self.incumbent_start_calls = 0
        self.incumbent_poll_calls = 0
        self.incumbent_adopt_calls = 0
        self.incumbent_poll_transitions: list[
            tuple[dict[str, object], dict[str, object]]
        ] = []
        self.cancel_calls = 0
        self.downstream_incumbent_starts = 0
        self.active_ops: dict[str, dict[str, object]] = {}
        self.active_workers: set[str] = set()
        self._hybrid_index = 0
        self._hybrid_replays: dict[str, int] = {}
        self._incumbent: dict[str, dict[str, Any]] = {}

    def _hybrid_response(self) -> dict[str, object]:
        assert self.provider_group is not None
        fusion, capture_bundle, inventory, bindings, cleanup_receipt = (
            _authoritative_inputs()
        )
        vista_requests = build_vista_requests(
            fusion,
            capture_bundle,
            omni_inventory=inventory,
            qwen_bindings=bindings,
            qwen_cleanup_receipt=cleanup_receipt,
            expected_workflow_revision=int(capture_bundle["workflow_revision"]),
        )
        return {
            "contract_version": "learning_hybrid_managed_stage_result_v1",
            "learning_pipeline_mode": "hybrid_v1_1",
            "task_kind": "panel_learning_hybrid_review_projection",
            "outcome": "completed",
            "result": {
                "contract_version": "hybrid_review_projection_v1",
                "outcome": "completed",
                "review_status": "REVIEW_REQUIRED",
                "automatic_acceptance": False,
                "proposals": [
                    {
                        "candidate_id": request["candidate_id"],
                        "status": "validated",
                    }
                    for request in vista_requests
                ],
                "execute_binding_enabled": False,
                "no_live_click_authorization": True,
            },
            "orchestration": {
                "hybrid_capture_bundle_ref": deepcopy(
                    self.provider_group["hybrid_capture_bundle_ref"]
                ),
                "capture_bundle": deepcopy(capture_bundle),
                "omni_inventory": deepcopy(inventory),
                "qwen_bindings": deepcopy(bindings),
                "fusion_result": deepcopy(fusion),
                "qwen_cleanup_receipt": deepcopy(cleanup_receipt),
                "workflow_revision": capture_bundle["workflow_revision"],
                "hybrid_vista_requests": deepcopy(vista_requests),
                "benchmark_v2_provider_dispatch_receipt_refs": [
                    {"provider": "omni", "content_sha256": "1" * 64},
                    {"provider": "qwen", "content_sha256": "2" * 64},
                    {"provider": "vista", "content_sha256": "3" * 64},
                ],
            },
            "supervisor_lineage": {"kind": "managed"},
            "lifecycle_evidence": {},
        }

    def _hybrid_step(self, *, status: str) -> dict[str, object]:
        assert self.window_binding is not None
        assert self.provider_group is not None
        worker_ref = _sealed_parent(f"hybrid-worker-{self._hybrid_index}")
        predecessor = self.active_ops.get("hybrid")
        operation_ref = _operation_ref(
            mode="hybrid_v1_1",
            operation_id=str(self.window_binding["operation_id"]),
            request_ref=self.provider_group["request_ref"],
            window_binding=self.window_binding,
            worker_ref=worker_ref,
            status=status,
            revision=10 + self._hybrid_index,
            predecessor=predecessor,
        )
        projection = None
        if status == "complete":
            projection = _projection(
                mode="hybrid_v1_1",
                operation_ref=operation_ref,
                response=self._hybrid_response(),
                terminal=False,
            )
        step = _step(
            operation_ref,
            task_kind=f"server-managed-hybrid-{self._hybrid_index}",
            projection=projection,
        )
        self.active_ops["hybrid"] = deepcopy(operation_ref)
        self.active_workers.add(str(worker_ref["content_sha256"]))
        return step

    def start_hybrid_operation(self, *, screen_group, window_binding):
        self.hybrid_start_calls += 1
        self.provider_group = deepcopy(dict(screen_group))
        self.window_binding = deepcopy(dict(window_binding))
        self.hybrid_producer_count += 1
        return self._hybrid_step(status="pending")

    def continue_hybrid_operation(self, *, operation_ref):
        self.hybrid_continue_calls += 1
        if dict(operation_ref) != self.active_ops.get("hybrid"):
            raise ValueError("stale hybrid operation ref")
        digest = str(operation_ref["content_sha256"])
        if self.stale_hybrid:
            stale = deepcopy(dict(operation_ref))
            stale["capture_ref"] = _identity("capture-stale")
            stale["content_sha256"] = content_sha256(stale)
            return _step(stale, task_kind="server-managed-stale")
        replay_count = self._hybrid_replays.get(digest, 0)
        if self.never_complete_hybrid or replay_count < self.pending_replays:
            self._hybrid_replays[digest] = replay_count + 1
            return _step(operation_ref, task_kind=f"server-managed-hybrid-{self._hybrid_index}")
        if self.successor_fault is not None and not self.successor_fault_used:
            self.successor_fault_used = True
            if self.successor_fault == "same_digest_changed_step":
                return _step(operation_ref, task_kind="server-managed-mutated-replay")
            assert self.window_binding is not None
            assert self.provider_group is not None
            next_operation_id = str(self.window_binding["operation_id"])
            next_revision = int(operation_ref["workflow_state_ref"]["revision"]) + 1
            if self.successor_fault == "switched_operation_id":
                next_operation_id = "operation-switched"
            elif self.successor_fault == "same_revision":
                next_revision = int(operation_ref["workflow_state_ref"]["revision"])
            elif self.successor_fault == "decreasing_revision":
                next_revision = int(operation_ref["workflow_state_ref"]["revision"]) - 1
            else:
                raise AssertionError(f"unknown successor fault: {self.successor_fault}")
            worker_ref = _sealed_parent("hybrid-worker-faulty-successor")
            faulty = _operation_ref(
                mode="hybrid_v1_1",
                operation_id=next_operation_id,
                request_ref=self.provider_group["request_ref"],
                window_binding=self.window_binding,
                worker_ref=worker_ref,
                status="pending",
                revision=next_revision,
                predecessor=operation_ref,
            )
            self.active_workers.discard(
                str(operation_ref["worker_ref"]["content_sha256"])
            )
            self.active_workers.add(str(worker_ref["content_sha256"]))
            self.active_ops["hybrid"] = deepcopy(faulty)
            return _step(faulty, task_kind="server-managed-faulty-successor")
        self.active_workers.discard(
            str(self.active_ops["hybrid"]["worker_ref"]["content_sha256"])
        )
        if self._hybrid_index == 4:
            assert self.window_binding is not None
            assert self.provider_group is not None
            consumed = deepcopy(self.active_ops["hybrid"])
            complete = _operation_ref(
                mode="hybrid_v1_1",
                operation_id=str(self.window_binding["operation_id"]),
                request_ref=self.provider_group["request_ref"],
                window_binding=self.window_binding,
                worker_ref=consumed["worker_ref"],
                status="complete",
                revision=int(consumed["workflow_state_ref"]["revision"]) + 1,
                predecessor=consumed,
            )
            projection = _projection(
                mode="hybrid_v1_1",
                operation_ref=complete,
                response=self._hybrid_response(),
                terminal=False,
            )
            terminal = _step(
                complete,
                task_kind="server-managed-hybrid-review",
                projection=projection,
            )
            self.active_ops["hybrid"] = deepcopy(complete)
            return terminal
        self._hybrid_index += 1
        self.hybrid_producer_count += 1
        return self._hybrid_step(status="pending")

    def start_incumbent_observe(self, *, provider_case_ref, window_binding):
        self.incumbent_start_calls += 1
        case_id = str(provider_case_ref["case_id"])
        worker_ref = _sealed_parent(f"incumbent-worker-{case_id}")
        operation_ref = _operation_ref(
            mode="incumbent_qwen_only",
            operation_id=f"incumbent-{case_id}",
            request_ref=_identity(case_id),
            window_binding=window_binding,
            worker_ref=worker_ref,
            status="pending",
            revision=30 + self.incumbent_start_calls,
            predecessor=None,
            run_id=f"incumbent-run-{case_id}",
        )
        self._incumbent[case_id] = {
            "case_ref": deepcopy(dict(provider_case_ref)),
            "current": deepcopy(operation_ref),
            "poll_replays": 0,
            "terminal": None,
        }
        self.active_ops[case_id] = deepcopy(operation_ref)
        self.active_workers.add(str(worker_ref["content_sha256"]))
        return _step(operation_ref, task_kind="vision_observe_screen")

    def poll_incumbent_observe(self, *, operation_ref):
        self.incumbent_poll_calls += 1
        case_id = str(operation_ref["operation_id"]).removeprefix("incumbent-")
        state = self._incumbent[case_id]
        if dict(operation_ref) != state["current"]:
            raise ValueError("stale incumbent operation ref")
        if state["poll_replays"] < self.pending_replays:
            state["poll_replays"] += 1
            return _step(operation_ref, task_kind="vision_observe_screen")
        advanced = _operation_ref(
            mode="incumbent_qwen_only",
            operation_id=str(operation_ref["operation_id"]),
            request_ref=operation_ref["request_ref"],
            window_binding=self.window_binding,
            worker_ref=operation_ref["worker_ref"],
            status="advanced",
            revision=int(operation_ref["workflow_state_ref"]["revision"]),
            predecessor=None,
            run_id=str(operation_ref["run_id"]),
        )
        state["current"] = deepcopy(advanced)
        self.active_ops[case_id] = deepcopy(advanced)
        pending_step = _step(operation_ref, task_kind="vision_observe_screen")
        advanced_step = _step(advanced, task_kind="vision_observe_screen")
        self.incumbent_poll_transitions.append(
            (deepcopy(pending_step), deepcopy(advanced_step))
        )
        return advanced_step

    def adopt_and_terminalize_incumbent(self, *, operation_ref, worker_ref):
        self.incumbent_adopt_calls += 1
        case_id = str(operation_ref["operation_id"]).removeprefix("incumbent-")
        state = self._incumbent[case_id]
        if state["terminal"] is not None:
            return deepcopy(state["terminal"])
        if (
            dict(operation_ref) != state["current"]
            or dict(worker_ref) != operation_ref["worker_ref"]
        ):
            raise ValueError("stale incumbent adoption")
        complete = _operation_ref(
            mode="incumbent_qwen_only",
            operation_id=str(operation_ref["operation_id"]),
            request_ref=operation_ref["request_ref"],
            window_binding=self.window_binding,
            worker_ref=worker_ref,
            status="complete",
            revision=int(operation_ref["workflow_state_ref"]["revision"]) + 1,
            predecessor=operation_ref,
            run_id=str(operation_ref["run_id"]),
        )
        projection = _projection(
            mode="incumbent_qwen_only",
            operation_ref=complete,
            response={
                "case_id": case_id,
                "elements": [{"candidate_id": f"qwen-{case_id}"}],
                "_benchmark_v2_provider_dispatch_receipt_refs": [
                    {
                        "provider": "qwen",
                        "content_sha256": __import__("hashlib")
                        .sha256(case_id.encode("utf-8"))
                        .hexdigest(),
                    }
                ],
            },
            terminal=True,
        )
        terminal = _step(
            complete,
            task_kind="vision_observe_screen",
            projection=projection,
        )
        state["current"] = deepcopy(complete)
        state["terminal"] = deepcopy(terminal)
        self.active_ops[case_id] = deepcopy(complete)
        self.active_workers.discard(str(worker_ref["content_sha256"]))
        return terminal

    def cancel_operation(self, *, operation_ref):
        self.cancel_calls += 1
        key = "hybrid" if operation_ref["mode"] == "hybrid_v1_1" else str(
            operation_ref["operation_id"]
        ).removeprefix("incumbent-")
        current = self.active_ops.get(key)
        if current is not None and dict(operation_ref) != current:
            stable_current = {
                name: deepcopy(value)
                for name, value in current.items()
                if name not in {"status", "content_sha256"}
            }
            stable_supplied = {
                name: deepcopy(value)
                for name, value in operation_ref.items()
                if name not in {"status", "content_sha256"}
            }
            if (
                stable_current != stable_supplied
                and current.get("predecessor_content_sha256")
                != operation_ref.get("content_sha256")
            ):
                raise ValueError("stale cleanup operation ref")
        self.active_ops.pop(key, None)
        if current is not None and current.get("worker_ref") is not None:
            self.active_workers.discard(
                str(current["worker_ref"]["content_sha256"])
            )
        if operation_ref.get("worker_ref") is not None:
            self.active_workers.discard(str(operation_ref["worker_ref"]["content_sha256"]))
        return {"status": "reconciled", "operation_ref": deepcopy(dict(operation_ref))}


class _FakeWindowOwner:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.binding = _window_binding()
        self.active_windows: set[str] = set()
        self.service: _FakeWorkflowService | None = None

    def open_screen_group(self, *, provider_group):
        self.events.append("window-open")
        self.active_windows.add(str(self.binding["window_binding_ref"]["id"]))
        return deepcopy(self.binding)

    def close_screen_group(self, *, window_binding, reason):
        self.events.append("window-close")
        assert self.service is not None
        assert not self.service.active_ops
        assert not self.service.active_workers
        self.active_windows.discard(str(window_binding["window_binding_ref"]["id"]))
        return _sealed_parent("window-close")


class _FakeLifecycle:
    def __init__(
        self,
        events: list[str],
        service: _FakeWorkflowService,
        owner: _FakeWindowOwner,
    ) -> None:
        self.events = events
        self.service = service
        self.owner = owner
        self.active_listeners = {"listener"}
        self.active_leases = {"lease"}

    def stable_zero(self, *, provider_group, window_binding, execution_refs, window_close_ref):
        self.events.append("lifecycle-stable-zero")
        self.active_listeners.clear()
        self.active_leases.clear()
        assert not self.service.active_ops
        assert not self.service.active_workers
        assert not self.owner.active_windows
        return _sealed_parent("stable-zero")


class _FakePredictionSink:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.values: list[dict[str, object]] = []

    def write_screen_group(self, *, projection):
        self.events.append("prediction-write")
        self.values.append(deepcopy(dict(projection)))
        return _identity("prediction-1", str(projection["content_sha256"]))


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        assert seconds > 0
        self.sleeps.append(seconds)
        self.now += seconds


def _ports(
    *,
    duplicate_reads: bool = False,
    pending_replays: int = 0,
    never_complete_hybrid: bool = False,
    stale_hybrid: bool = False,
    successor_fault: str | None = None,
):
    events: list[str] = []
    service = _FakeWorkflowService(
        duplicate_reads=duplicate_reads,
        pending_replays=pending_replays,
        never_complete_hybrid=never_complete_hybrid,
        stale_hybrid=stale_hybrid,
        successor_fault=successor_fault,
    )
    owner = _FakeWindowOwner(events)
    owner.service = service
    lifecycle = _FakeLifecycle(events, service, owner)
    sink = _FakePredictionSink(events)
    return events, service, owner, lifecycle, sink


def test_actual_adapter_exposes_only_the_canonical_workflow_service_port() -> None:
    expected = {
        "start_hybrid_operation": ("self", "screen_group", "window_binding"),
        "continue_hybrid_operation": ("self", "operation_ref"),
        "start_incumbent_observe": ("self", "provider_case_ref", "window_binding"),
        "poll_incumbent_observe": ("self", "operation_ref"),
        "adopt_and_terminalize_incumbent": (
            "self",
            "operation_ref",
            "worker_ref",
        ),
        "cancel_operation": ("self", "operation_ref"),
    }
    for name, parameters in expected.items():
        assert tuple(inspect.signature(getattr(WorkflowServicePort, name)).parameters) == parameters
    assert tuple(inspect.signature(run_screen_group).parameters) == (
        "provider_group",
        "service",
        "window_owner",
        "lifecycle",
        "prediction_sink",
    )


def test_actual_adapter_ast_has_no_private_or_action_boundary() -> None:
    source_path = Path(__file__).parents[1] / "app" / "learn" / "hybrid" / "benchmark_v2_actual.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    source = source_path.read_text(encoding="utf-8")
    assert not any(
        forbidden in imported or forbidden in source
        for forbidden in (
            "LearningStageWorkerRegistry",
            "learning_workflow_run_store",
            "workflow_store",
            "workflow_worker",
            "handler",
            ".composition",
            ".start(",
            ".resume(",
            ".cancel(",
        )
    )
    forbidden_calls = {"click", "fill", "publish", "execute_action"}
    assert not {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    } & forbidden_calls


def test_run_screen_group_uses_one_hybrid_cascade_and_five_incumbent_operations() -> None:
    events, service, owner, lifecycle, sink = _ports()

    result = run_screen_group(
        provider_group=_provider_group(),
        service=service,
        window_owner=owner,
        lifecycle=lifecycle,
        prediction_sink=sink,
    )

    assert service.hybrid_start_calls == 1
    assert service.hybrid_producer_count == 5
    assert service.incumbent_start_calls == 5
    assert service.incumbent_adopt_calls == 5
    assert service.downstream_incumbent_starts == 0
    assert service.cancel_calls == 6
    assert len(result["rows"]) == 20
    assert {
        (row["case_ref"]["case_id"], row["arm_id"])
        for row in result["rows"]
    } == {
        (f"case-{case_index}", arm_id)
        for case_index in range(5)
        for arm_id in (
            "qwen_only",
            "omni_only_discovery",
            "omni_to_qwen",
            "omni_to_qwen_vista",
        )
    }
    assert result["artifact_is_authorization"] is False
    assert result["execute_binding_enabled"] is False
    assert result["content_sha256"] == content_sha256(result)
    assert sink.values == [result]
    assert events[-3:] == [
        "window-close",
        "lifecycle-stable-zero",
        "prediction-write",
    ]
    assert not service.active_ops
    assert not service.active_workers
    assert not owner.active_windows
    assert not lifecycle.active_listeners
    assert not lifecycle.active_leases

    shared = result["shared_parent_refs"]
    for row in result["rows"]:
        assert row["shared_parent_refs"] == shared
        refs = row["observation"]["provider_dispatch_receipt_refs"]
        assert {ref["provider"] for ref in refs} == {
            "qwen_only": {"qwen"},
            "omni_only_discovery": {"omni"},
            "omni_to_qwen": {"omni", "qwen"},
            "omni_to_qwen_vista": {"omni", "qwen", "vista"},
        }[row["arm_id"]]
    assert shared == {
        "screen_group_ref": {
            "id": "screen-group-1",
            "content_sha256": _provider_group()["content_sha256"],
        },
        "hybrid_capture_bundle_ref": _provider_group()["hybrid_capture_bundle_ref"],
        "window_binding_ref": _window_binding()["window_binding_ref"],
        "capture_ref": _window_binding()["capture_ref"],
        "owner_journal_ref": _window_binding()["owner_journal_ref"],
        "expected_uia_root_ref": _window_binding()["expected_uia_root_ref"],
    }


def test_actual_projection_seals_exact_pre_vista_evidence_with_class_specific_refs() -> None:
    events, service, owner, lifecycle, sink = _ports()

    result = run_screen_group(
        provider_group=_provider_group(),
        service=service,
        window_owner=owner,
        lifecycle=lifecycle,
        prediction_sink=sink,
    )

    evidence = result["pre_vista_evidence"]
    assert set(evidence) == {
        "contract_version",
        "provider_group_ref",
        "omni_inventory_envelope",
        "qwen_bindings_envelope",
        "fusion_result_envelope",
        "submitted_vista_request_envelopes",
        "safety",
        "content_sha256",
    }
    assert evidence["contract_version"] == "benchmark_v2_actual_pre_vista_evidence_v1"
    assert evidence["provider_group_ref"] == {
        "id": "screen-group-1",
        "content_sha256": _provider_group()["content_sha256"],
    }
    assert evidence["safety"] == {
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    assert evidence["content_sha256"] == content_sha256(evidence)

    expected_prefixes = (
        ("omni_inventory_envelope", "omni-inventory", b"benchmark-v2-omni-inventory\0"),
        ("qwen_bindings_envelope", "qwen-bindings", b"benchmark-v2-qwen-bindings\0"),
        ("fusion_result_envelope", "fusion-result", b"benchmark-v2-fusion-result\0"),
    )
    for field, id_prefix, domain in expected_prefixes:
        envelope = evidence[field]
        assert set(envelope) == {"ref", "canonical_bytes_b64"}
        raw = base64.b64decode(envelope["canonical_bytes_b64"], validate=True)
        assert raw == json.dumps(
            json.loads(raw.decode("utf-8")),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        assert envelope["ref"] == {
            "id": f"{id_prefix}/" + hashlib.sha256(domain + raw).hexdigest(),
            "content_sha256": hashlib.sha256(raw).hexdigest(),
        }

    request_envelopes = evidence["submitted_vista_request_envelopes"]
    decoded_requests = [
        json.loads(base64.b64decode(item["canonical_bytes_b64"], validate=True))
        for item in request_envelopes
    ]
    assert [item["candidate_id"] for item in decoded_requests] == sorted(
        item["candidate_id"] for item in decoded_requests
    )
    for envelope in request_envelopes:
        assert set(envelope) == {"ref", "canonical_bytes_b64"}
        raw = base64.b64decode(envelope["canonical_bytes_b64"], validate=True)
        assert envelope["ref"] == {
            "id": "submitted-vista-request/"
            + hashlib.sha256(b"benchmark-v2-submitted-vista-request\0" + raw).hexdigest(),
            "content_sha256": hashlib.sha256(raw).hexdigest(),
        }

    fusion, capture_bundle, inventory, bindings, cleanup_receipt = (
        _authoritative_inputs()
    )
    assert decoded_requests == sorted(
        build_vista_requests(
            fusion,
            capture_bundle,
            omni_inventory=inventory,
            qwen_bindings=bindings,
            qwen_cleanup_receipt=cleanup_receipt,
            expected_workflow_revision=int(capture_bundle["workflow_revision"]),
        ),
        key=lambda item: item["candidate_id"],
    )


@pytest.mark.parametrize("confidence", (1.0, 0.0, -0.0, 1e-7))
def test_uei_jcs_sealed_legal_floats_pass_closed_validators_and_actual_projection(
    confidence: float,
) -> None:
    _, service, owner, lifecycle, sink = _ports()
    original_response = service._hybrid_response

    def legal_float_response() -> dict[str, object]:
        response = original_response()
        orchestration = response["orchestration"]
        qwen = deepcopy(orchestration["qwen_bindings"])
        qwen.pop("content_sha256")
        qwen["bindings"][0]["semantic_confidence"] = confidence
        qwen = seal_immutable(qwen)
        orchestration["qwen_bindings"] = qwen
        orchestration["hybrid_vista_requests"] = build_vista_requests(
            orchestration["fusion_result"],
            orchestration["capture_bundle"],
            omni_inventory=orchestration["omni_inventory"],
            qwen_bindings=qwen,
            qwen_cleanup_receipt=orchestration["qwen_cleanup_receipt"],
            expected_workflow_revision=int(orchestration["workflow_revision"]),
        )
        return response

    service._hybrid_response = legal_float_response
    projection = run_screen_group(
        provider_group=_provider_group(),
        service=service,
        window_owner=owner,
        lifecycle=lifecycle,
        prediction_sink=sink,
    )

    evidence = projection["pre_vista_evidence"]
    qwen_bytes = base64.b64decode(
        evidence["qwen_bindings_envelope"]["canonical_bytes_b64"],
        validate=True,
    )
    decoded = json.loads(qwen_bytes.decode("utf-8"))
    assert decoded["bindings"][0]["semantic_confidence"] == confidence
    assert evidence["content_sha256"] == content_sha256(evidence)
    assert projection["content_sha256"] == content_sha256(projection)


def test_final_review_proposal_mutation_cannot_change_pre_vista_evidence() -> None:
    _, service_a, owner_a, lifecycle_a, sink_a = _ports()
    baseline = run_screen_group(
        provider_group=_provider_group(),
        service=service_a,
        window_owner=owner_a,
        lifecycle=lifecycle_a,
        prediction_sink=sink_a,
    )["pre_vista_evidence"]

    _, service_b, owner_b, lifecycle_b, sink_b = _ports()
    original_response = service_b._hybrid_response

    def mutated_response() -> dict[str, object]:
        response = original_response()
        response["result"]["proposals"] = [
            {"candidate_id": "proposal-only-mutation", "status": "failed"}
        ]
        return response

    service_b._hybrid_response = mutated_response
    mutated = run_screen_group(
        provider_group=_provider_group(),
        service=service_b,
        window_owner=owner_b,
        lifecycle=lifecycle_b,
        prediction_sink=sink_b,
    )["pre_vista_evidence"]

    assert mutated == baseline


@pytest.mark.parametrize(
    "fault",
    ("missing", "non_list", "duplicate", "omitted", "foreign_candidate"),
)
def test_invalid_propagated_pre_vista_requests_fail_closed_and_still_clean_up(
    fault: str,
) -> None:
    events, service, owner, lifecycle, sink = _ports()
    original_response = service._hybrid_response

    def invalid_requests_response() -> dict[str, object]:
        response = original_response()
        requests = response["orchestration"]["hybrid_vista_requests"]
        if fault == "missing":
            response["orchestration"].pop("hybrid_vista_requests")
        elif fault == "non_list":
            response["orchestration"]["hybrid_vista_requests"] = {"invalid": True}
        elif fault == "duplicate":
            response["orchestration"]["hybrid_vista_requests"] = [
                deepcopy(requests[0]),
                deepcopy(requests[0]),
            ]
        elif fault == "omitted":
            response["orchestration"]["hybrid_vista_requests"] = []
        else:
            foreign = deepcopy(requests[0])
            foreign["candidate_id"] = "foreign-candidate"
            response["orchestration"]["hybrid_vista_requests"] = [foreign]
        return response

    service._hybrid_response = invalid_requests_response
    with pytest.raises(ValueError, match="VISTA request"):
        run_screen_group(
            provider_group=_provider_group(),
            service=service,
            window_owner=owner,
            lifecycle=lifecycle,
            prediction_sink=sink,
        )

    assert not sink.values
    assert events[-2:] == ["window-close", "lifecycle-stable-zero"]
    assert not service.active_ops
    assert not service.active_workers
    assert not owner.active_windows


@pytest.mark.parametrize(
    "parent_name",
    ("omni_inventory", "qwen_bindings", "fusion_result"),
)
def test_pre_vista_parent_closed_validators_reject_absolute_path_extra_field(
    parent_name: str,
) -> None:
    events, service, owner, lifecycle, sink = _ports()
    original_response = service._hybrid_response

    def tampered_response() -> dict[str, object]:
        response = original_response()
        parent = deepcopy(response["orchestration"][parent_name])
        parent.pop("content_sha256")
        parent["debug_path"] = r"C:\private\benchmark\raw.json"
        response["orchestration"][parent_name] = seal_immutable(parent)
        return response

    service._hybrid_response = tampered_response
    with pytest.raises(ValueError, match="inventory|Qwen|fusion"):
        run_screen_group(
            provider_group=_provider_group(),
            service=service,
            window_owner=owner,
            lifecycle=lifecycle,
            prediction_sink=sink,
        )

    assert not sink.values
    assert events[-2:] == ["window-close", "lifecycle-stable-zero"]
    assert not service.active_ops
    assert not service.active_workers
    assert not owner.active_windows


@pytest.mark.parametrize("fault", ("absolute_path_extra", "source_revision"))
def test_propagated_vista_request_must_byte_match_closed_rebuild(fault: str) -> None:
    events, service, owner, lifecycle, sink = _ports()
    original_response = service._hybrid_response

    def tampered_response() -> dict[str, object]:
        response = original_response()
        request = deepcopy(
            response["orchestration"]["hybrid_vista_requests"][0]
        )
        request.pop("content_sha256")
        if fault == "absolute_path_extra":
            request["raw_path"] = r"C:\private\benchmark\request.json"
        else:
            request["source_revision"] = "f" * 64
        response["orchestration"]["hybrid_vista_requests"] = [
            seal_immutable(request)
        ]
        return response

    service._hybrid_response = tampered_response
    with pytest.raises(
        ValueError,
        match="differ from exact calibration output",
    ):
        run_screen_group(
            provider_group=_provider_group(),
            service=service,
            window_owner=owner,
            lifecycle=lifecycle,
            prediction_sink=sink,
        )

    assert not sink.values
    assert events[-2:] == ["window-close", "lifecycle-stable-zero"]
    assert not service.active_ops
    assert not service.active_workers
    assert not owner.active_windows


def test_duplicate_public_reads_do_not_duplicate_hybrid_or_incumbent_producers() -> None:
    events, service, owner, lifecycle, sink = _ports(duplicate_reads=True)

    result = run_screen_group(
        provider_group=_provider_group(),
        service=service,
        window_owner=owner,
        lifecycle=lifecycle,
        prediction_sink=sink,
    )

    assert len(result["rows"]) == 20
    assert service.hybrid_start_calls == 1
    assert service.hybrid_producer_count == 5
    assert service.hybrid_continue_calls == 10
    assert service.incumbent_start_calls == 5
    assert service.incumbent_poll_calls == 10
    assert service.incumbent_adopt_calls == 5
    assert service.downstream_incumbent_starts == 0
    assert len(sink.values) == 1


def test_incumbent_pending_to_advanced_is_read_only_then_adopts_exactly_once() -> None:
    events, service, owner, lifecycle, sink = _ports()

    result = run_screen_group(
        provider_group=_provider_group(),
        service=service,
        window_owner=owner,
        lifecycle=lifecycle,
        prediction_sink=sink,
    )

    assert len(result["rows"]) == 20
    assert len(service.incumbent_poll_transitions) == 5
    assert service.incumbent_adopt_calls == 5
    for pending_step, advanced_step in service.incumbent_poll_transitions:
        assert pending_step["status"] == "pending"
        assert advanced_step["status"] == "advanced"
        pending_operation = pending_step["operation_ref"]
        advanced_operation = advanced_step["operation_ref"]
        for name in (
            "mode",
            "run_id",
            "stage",
            "operation_id",
            "workflow_state_ref",
            "stage_execution_ref",
            "request_ref",
            "window_binding_ref",
            "capture_ref",
            "worker_ref",
            "predecessor_content_sha256",
            "artifact_is_authorization",
            "execute_binding_enabled",
        ):
            assert advanced_operation[name] == pending_operation[name]
        for name in (
            "mode",
            "worker_ref",
            "observed_task_kind",
            "adopted_result_projection",
            "terminal_receipt",
            "cleanup_refs",
            "artifact_is_authorization",
            "execute_binding_enabled",
        ):
            assert advanced_step[name] == pending_step[name]
        assert advanced_step["adopted_result_projection"] is None
        assert advanced_step["terminal_receipt"] is None
        assert advanced_step["cleanup_refs"] == {
            "worker_cleanup_ref": None,
            "provider_cleanup_ref": None,
        }
    assert not service.active_ops
    assert not service.active_workers
    assert not owner.active_windows
    assert not lifecycle.active_listeners
    assert not lifecycle.active_leases


def test_stale_hybrid_projection_fails_closed_before_prediction_and_still_cleans_up() -> None:
    events, service, owner, lifecycle, sink = _ports(stale_hybrid=True)

    with pytest.raises(ValueError, match="capture|stale"):
        run_screen_group(
            provider_group=_provider_group(),
            service=service,
            window_owner=owner,
            lifecycle=lifecycle,
            prediction_sink=sink,
        )

    assert service.hybrid_start_calls == 1
    assert service.incumbent_start_calls == 0
    assert not sink.values
    assert events[-2:] == ["window-close", "lifecycle-stable-zero"]
    assert not service.active_ops
    assert not service.active_workers
    assert not owner.active_windows


def test_wrong_target_multiset_is_rejected_before_any_window_or_service_start() -> None:
    events, service, owner, lifecycle, sink = _ports()
    provider_group = _provider_group()
    provider_group["case_refs"] = provider_group["case_refs"][:4]
    provider_group["content_sha256"] = content_sha256(provider_group)

    with pytest.raises(ValueError, match="five case refs"):
        run_screen_group(
            provider_group=provider_group,
            service=service,
            window_owner=owner,
            lifecycle=lifecycle,
            prediction_sink=sink,
        )

    assert not events
    assert service.hybrid_start_calls == 0
    assert not sink.values


def test_prediction_sink_failure_occurs_only_after_stable_zero() -> None:
    events, service, owner, lifecycle, sink = _ports()

    def fail_write(*, projection):
        events.append("prediction-write-failed")
        assert not service.active_ops
        assert not service.active_workers
        assert not owner.active_windows
        raise RuntimeError("prediction sink unavailable")

    sink.write_screen_group = fail_write
    with pytest.raises(RuntimeError, match="prediction sink unavailable"):
        run_screen_group(
            provider_group=_provider_group(),
            service=service,
            window_owner=owner,
            lifecycle=lifecycle,
            prediction_sink=sink,
        )

    assert events[-3:] == [
        "window-close",
        "lifecycle-stable-zero",
        "prediction-write-failed",
    ]


def test_pending_workers_wait_with_nonzero_backoff_and_complete_before_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeClock()
    monkeypatch.setattr(actual, "_monotonic", clock.monotonic)
    monkeypatch.setattr(actual, "_sleep", clock.sleep)
    events, service, owner, lifecycle, sink = _ports(pending_replays=3)

    result = run_screen_group(
        provider_group=_provider_group(),
        service=service,
        window_owner=owner,
        lifecycle=lifecycle,
        prediction_sink=sink,
    )

    assert len(result["rows"]) == 20
    assert len(clock.sleeps) == 40
    assert all(delay > 0 for delay in clock.sleeps)
    assert clock.now < actual._POLL_TIMEOUT_SECONDS * 6
    assert service.hybrid_producer_count == 5
    assert service.incumbent_start_calls == 5
    assert service.cancel_calls == 6
    assert not service.active_ops
    assert not service.active_workers


def test_true_poll_deadline_times_out_then_reconciles_before_window_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _FakeClock()
    monkeypatch.setattr(actual, "_monotonic", clock.monotonic)
    monkeypatch.setattr(actual, "_sleep", clock.sleep)
    monkeypatch.setattr(actual, "_POLL_TIMEOUT_SECONDS", 0.12)
    events, service, owner, lifecycle, sink = _ports(never_complete_hybrid=True)

    with pytest.raises(TimeoutError, match="deadline"):
        run_screen_group(
            provider_group=_provider_group(),
            service=service,
            window_owner=owner,
            lifecycle=lifecycle,
            prediction_sink=sink,
        )

    assert clock.sleeps
    assert all(delay > 0 for delay in clock.sleeps)
    assert service.hybrid_start_calls == 1
    assert service.incumbent_start_calls == 0
    assert service.cancel_calls == 1
    assert events[-2:] == ["window-close", "lifecycle-stable-zero"]
    assert not sink.values
    assert not service.active_ops
    assert not service.active_workers
    assert not owner.active_windows
    assert not lifecycle.active_listeners
    assert not lifecycle.active_leases


@pytest.mark.parametrize(
    "fault",
    (
        "switched_operation_id",
        "same_revision",
        "decreasing_revision",
        "same_digest_changed_step",
    ),
)
def test_successor_lineage_fault_fails_before_second_downstream_call_and_cleans_up(
    fault: str,
) -> None:
    events, service, owner, lifecycle, sink = _ports(successor_fault=fault)

    with pytest.raises(ValueError, match="operation|revision|replay|stale"):
        run_screen_group(
            provider_group=_provider_group(),
            service=service,
            window_owner=owner,
            lifecycle=lifecycle,
            prediction_sink=sink,
        )

    assert service.hybrid_continue_calls == 1
    assert service.incumbent_start_calls == 0
    assert service.cancel_calls == 1
    assert events[-2:] == ["window-close", "lifecycle-stable-zero"]
    assert not sink.values
    assert not service.active_ops
    assert not service.active_workers
    assert not owner.active_windows
