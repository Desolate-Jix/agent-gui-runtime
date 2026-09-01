from __future__ import annotations

from copy import deepcopy
import ast
from datetime import datetime, timedelta
import hashlib
import inspect
import json
from pathlib import Path
from threading import Barrier, Thread

import pytest

from app.learn.hybrid import benchmark_v2_incumbent_operation as incumbent
from app.learn.hybrid.benchmark_v2_contracts import canonical_json_bytes, content_sha256
from app.learn.recognition.uei.canonical import seal_immutable
from test_portfolio_hybrid_v1_1_benchmark_v2_incumbent import (
    _prepared_document,
    _provider_owner_changes,
    source_bundle,
    validated_provider_snapshot,
)


SHA_A = "a" * 64
SHA_B = "b" * 64


def _identity(identity: str, digest: str = SHA_A) -> dict[str, object]:
    return {"id": identity, "content_sha256": digest}


def _sealed_parent(kind: str, digest: str = SHA_A) -> dict[str, object]:
    body: dict[str, object] = {"kind": kind, "parent_sha256": digest}
    body["content_sha256"] = content_sha256(body)
    return body


def _window_binding(
    *,
    run_id: str = "run-1",
    operation_id: str = "operation-1",
    window_binding_ref: dict[str, object] | None = None,
    capture_ref: dict[str, object] | None = None,
) -> dict[str, object]:
    return incumbent.compose_benchmark_v2_workflow_window_binding(
        run_id=run_id,
        operation_id=operation_id,
        window_binding_ref=window_binding_ref or _identity("window-1"),
        capture_ref=capture_ref or _identity("capture-1"),
        owner_journal_ref=_sealed_parent("owner-journal"),
        expected_uia_root_ref=_sealed_parent("uia-root"),
    )


def _screen_group(
    *,
    capture_bundle: dict[str, object] | None = None,
    hybrid_capture_bundle_ref: dict[str, object] | None = None,
    capture_image_path: str = "artifacts/benchmark/screen-group-1.png",
) -> dict[str, object]:
    bundle_ref = _identity("capture-bundle")
    expanded_bundle = capture_bundle or {
        "bundle_id": "capture-bundle",
        "bundle_ref": bundle_ref,
        "run_id": "run-h1",
        "workflow_revision": 0,
    }
    if hybrid_capture_bundle_ref is not None:
        bundle_ref = deepcopy(hybrid_capture_bundle_ref)
    elif isinstance(expanded_bundle.get("bundle_ref"), dict):
        bundle_ref = deepcopy(expanded_bundle["bundle_ref"])
    return incumbent.compose_benchmark_v2_hybrid_screen_group_start(
        attempt_ref=_sealed_parent("attempt"),
        partition="regression",
        screen_group="screen-group-1",
        provider_corpus_ref=_sealed_parent("provider-corpus"),
        case_refs=[
            {"case_id": f"case-{index}", "case_content_sha256": SHA_A}
            for index in range(5)
        ],
        hybrid_capture_bundle_ref=bundle_ref,
        request_ref=_identity("request-1"),
        registration_ref=_identity("registration-1"),
        manifest_ref=_identity("manifest-1"),
        capture_image_path=capture_image_path,
        hybrid_config={"mode": "hybrid_v1_1"},
        capture_bundle=expanded_bundle,
    )


def _hybrid_worker_payload() -> dict[str, object]:
    group = _screen_group()
    orchestration = {
        "run_id": "run-h1",
        "workflow_revision": 0,
        "hybrid_capture_bundle_ref": deepcopy(
            group["hybrid_capture_bundle_ref"]
        ),
        "capture_image_path": group["capture_image_path"],
        "hybrid_config": deepcopy(group["hybrid_config"]),
        "capture_bundle": deepcopy(group["capture_bundle"]),
    }
    return {
        "learning_pipeline_mode": "hybrid_v1_1",
        "workflow_revision": 0,
        "_hybrid_orchestration": orchestration,
    }


def _operation_ref(
    *,
    mode: str = "hybrid_v1_1",
    status: str = "pending",
    worker_ref: dict[str, object] | None = None,
) -> dict[str, object]:
    return incumbent.compose_benchmark_v2_workflow_service_operation_ref(
        mode=mode,
        run_id="run-1",
        stage="screen_understanding",
        operation_id="operation-1",
        workflow_state_ref={
            "run_id": "run-1",
            "revision": 7,
            "content_sha256": SHA_A,
        },
        stage_execution_ref={
            "run_id": "run-1",
            "stage": "screen_understanding",
            "operation_id": "operation-1",
            "revision": 7,
            "content_sha256": SHA_B,
        },
        request_ref=_identity("request-1"),
        window_binding_ref=_identity("window-1"),
        capture_ref=_identity("capture-1"),
        worker_ref=worker_ref,
        status=status,
        predecessor_operation_ref=None,
    )


def _adopted_projection() -> dict[str, object]:
    return incumbent.compose_benchmark_v2_adopted_result_projection(
        mode="incumbent_qwen_only",
        run_id="run-1",
        stage="screen_understanding",
        operation_id="operation-1",
        worker_ref=_sealed_parent("worker"),
        model_request_ref=_identity("model-request-1"),
        payload_ref={"content_sha256": SHA_A},
        result_ref={"content_sha256": SHA_B},
        adoption_ref=_sealed_parent("adoption"),
        response={"elements": [{"text": "Quick apply"}]},
        terminal_receipt=_sealed_parent("terminal-receipt"),
        window_adoption_ref=_sealed_parent("window-adoption"),
        worker_cleanup_ref=_sealed_parent("worker-cleanup"),
        provider_cleanup_ref=_sealed_parent("provider-cleanup"),
    )


def _step() -> dict[str, object]:
    operation_ref = _operation_ref(
        mode="incumbent_qwen_only",
        status="complete",
        worker_ref=_sealed_parent("worker"),
    )
    projection = _adopted_projection()
    return incumbent.compose_benchmark_v2_workflow_service_step(
        operation_ref=operation_ref,
        observed_task_kind="vision_observe_screen",
        adopted_result_projection=projection,
        terminal_receipt=projection["terminal_receipt"],
        cleanup_refs={
            "worker_cleanup_ref": projection["worker_cleanup_ref"],
            "provider_cleanup_ref": projection["provider_cleanup_ref"],
        },
    )


def _provider_context_projection() -> dict[str, object]:
    operation: dict[str, object] = {
        "run_id": "run-1",
        "stage": "screen_understanding",
        "operation_id": "operation-1",
        "revision": 6,
        "window_binding_ref": _identity("window-1"),
        "capture_ref": _identity("capture-1"),
    }
    operation["content_sha256"] = content_sha256(operation)
    return incumbent.compose_benchmark_v2_provider_dispatch_context_projection(
        provider="qwen",
        context_content_sha256=SHA_B,
        operation_ref=operation,
    )


def _reseal(document: dict[str, object]) -> dict[str, object]:
    document["content_sha256"] = content_sha256(document)
    return document


def test_canonical_service_surface_has_only_exact_keyword_inputs() -> None:
    expected = {
        "start_hybrid_operation": ("screen_group", "window_binding"),
        "lookup_hybrid_operation": ("screen_group", "window_binding"),
        "continue_hybrid_operation": ("operation_ref",),
        "start_incumbent_observe": ("provider_case_ref", "window_binding"),
        "lookup_incumbent_observe": ("provider_case_ref", "window_binding"),
        "poll_incumbent_observe": ("operation_ref",),
        "adopt_and_terminalize_incumbent": ("operation_ref", "worker_ref"),
        "cancel_operation": ("operation_ref",),
        "attest_completed_hybrid_cleanup": ("operation_ref",),
        "attest_fusion_safe_stop_cleanup": ("operation_ref",),
        "attest_actual_operations_stable_zero": ("operation_refs",),
    }
    for method_name, names in expected.items():
        signature = inspect.signature(
            getattr(incumbent.BenchmarkV2IncumbentWorkflowService, method_name)
        )
        parameters = tuple(signature.parameters.values())
        assert parameters[0].name == "self"
        assert tuple(parameter.name for parameter in parameters[1:]) == names
        assert all(
            parameter.kind is inspect.Parameter.KEYWORD_ONLY
            for parameter in parameters[1:]
        )


def test_production_service_getter_is_identity_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    composition = object()
    monkeypatch.setattr(
        "app.learn.workflow_service.get_production_learning_workflow_service_composition",
        lambda: composition,
    )
    monkeypatch.setattr(
        incumbent,
        "_PRODUCTION_BENCHMARK_V2_WORKFLOW_SERVICE",
        None,
    )

    first = incumbent.get_production_benchmark_v2_workflow_service()
    second = incumbent.get_production_benchmark_v2_workflow_service()

    assert first is second


@pytest.mark.parametrize(
    ("factory", "validator"),
    [
        (_window_binding, incumbent.validate_benchmark_v2_workflow_window_binding),
        (_screen_group, incumbent.validate_benchmark_v2_hybrid_screen_group_start),
        (_operation_ref, incumbent.validate_benchmark_v2_workflow_service_operation_ref),
        (_adopted_projection, incumbent.validate_benchmark_v2_adopted_result_projection),
        (
            _provider_context_projection,
            incumbent.validate_benchmark_v2_provider_dispatch_context_projection,
        ),
        (_step, incumbent.validate_benchmark_v2_workflow_service_step),
    ],
)
def test_service_contracts_are_closed_and_digest_bound(factory, validator) -> None:
    document = factory()
    assert validator(document) == document
    assert validator(document) is not document

    extra = deepcopy(document)
    extra["unexpected"] = True
    with pytest.raises(ValueError, match="schema is not closed"):
        validator(extra)

    missing = deepcopy(document)
    missing.pop(next(iter(missing)))
    with pytest.raises(ValueError, match="schema is not closed"):
        validator(missing)

    changed = deepcopy(document)
    changed["content_sha256"] = SHA_B
    with pytest.raises(ValueError, match="content SHA mismatch"):
        validator(changed)


def test_start_contracts_reject_resealed_authority_and_wrong_group_shape() -> None:
    binding = _window_binding()
    binding["safety"] = {
        "artifact_is_authorization": True,
        "execute_binding_enabled": False,
    }
    with pytest.raises(ValueError, match="cannot authorize actions"):
        incumbent.validate_benchmark_v2_workflow_window_binding(_reseal(binding))

    screen_group = _screen_group()
    screen_group["case_refs"] = screen_group["case_refs"][:4]
    with pytest.raises(ValueError, match="exactly five"):
        incumbent.validate_benchmark_v2_hybrid_screen_group_start(
            _reseal(screen_group)
        )


def test_operation_ref_rejects_resealed_stale_cross_field_revision() -> None:
    operation_ref = _operation_ref()
    operation_ref["workflow_state_ref"]["revision"] = 8

    with pytest.raises(ValueError, match="revision lineage is stale"):
        incumbent.validate_benchmark_v2_workflow_service_operation_ref(
            _reseal(operation_ref)
        )


def test_adopted_projection_requires_response_bytes_not_only_a_digest() -> None:
    projection = _adopted_projection()
    assert projection["response_canonical_json"].encode("utf-8") == canonical_json_bytes(
        projection["response"]
    )
    projection["response"] = {"elements": []}

    with pytest.raises(ValueError, match="canonical response bytes mismatch"):
        incumbent.validate_benchmark_v2_adopted_result_projection(
            _reseal(projection)
        )


def test_step_rejects_resealed_operation_status_substitution() -> None:
    step = _step()
    step["status"] = "pending"

    with pytest.raises(ValueError, match="status does not match"):
        incumbent.validate_benchmark_v2_workflow_service_step(_reseal(step))


def test_u2_service_step_reserves_closed_pathless_dispatch_context_projection() -> None:
    step = _step()

    assert "provider_dispatch_context_projection" in step
    assert step["provider_dispatch_context_projection"] is None
    projection = _provider_context_projection()
    assert "receipt_journal_path" not in projection
    assert projection["artifact_is_authorization"] is False


def test_contract_skeletons_fail_closed_without_worker_or_provider_dispatch() -> None:
    from app.learn.workflow_service import LearningWorkflowStageOperationError

    service = incumbent.BenchmarkV2IncumbentWorkflowService(object())
    operation_ref = _operation_ref(worker_ref=_sealed_parent("worker"))
    calls = (
        lambda: service.start_hybrid_operation(
            screen_group=_screen_group(), window_binding=_window_binding()
        ),
        lambda: service.continue_hybrid_operation(operation_ref=operation_ref),
    )
    for call in calls:
        with pytest.raises(
            LearningWorkflowStageOperationError,
            match="composition must be factory-minted",
        ):
            call()


def test_canonical_methods_do_not_accept_orchestration_authority_arguments() -> None:
    service = incumbent.BenchmarkV2IncumbentWorkflowService(object())
    forbidden = {
        "store": object(),
        "registry": object(),
        "composition": object(),
        "expected_revision": 7,
        "task_kind": "vision_observe_screen",
        "payload": {},
        "handler": object(),
        "model": object(),
        "provider": object(),
        "action": object(),
    }
    for name, value in forbidden.items():
        with pytest.raises(TypeError, match=name):
            service.continue_hybrid_operation(
                operation_ref=_operation_ref(), **{name: value}
            )


class _S2Registry:
    def __init__(self) -> None:
        self.worker_status = "running"
        self.status_calls = 0
        self.read_calls = 0
        self.adopt_calls = 0
        self.cancel_calls = 0
        self.adoption: dict[str, object] | None = None

    def status(self, **kwargs) -> dict[str, object]:
        self.status_calls += 1
        return {
            "status": self.worker_status,
            "worker_id": kwargs["worker_id"],
            "run_id": kwargs["run_id"],
            "operation_id": kwargs["operation_id"],
        }

    def read_adopted_result(self, **_kwargs) -> dict[str, object]:
        self.read_calls += 1
        if self.adoption is None:
            raise AssertionError("adopted response was read before terminal adoption")
        return deepcopy(self.adoption)

    def adopt_result(self, **_kwargs) -> dict[str, object]:
        self.adopt_calls += 1
        raise AssertionError("focused service-port test reached Registry adoption")

    def cancel_by_operation(self, **_kwargs) -> dict[str, object]:
        self.cancel_calls += 1
        raise AssertionError("focused service-port test reached Registry cancellation")


def _s2_service(tmp_path: Path, registry: _S2Registry):
    from app.learn.workflow_service import (
        compose_test_learning_workflow_service_unit,
        start_learning_workflow_stage_operation,
    )
    from app.learn.workflow_store import LearningWorkflowRunStore

    store = LearningWorkflowRunStore(state_path=tmp_path / "workflow-state.json")
    binding = store.transition(
        run_id="run-c1",
        expected_revision=0,
        stage="bind_capture",
        outcome="running",
        evidence_refs={},
    )
    bound = store.transition(
        run_id="run-c1",
        expected_revision=binding["revision"],
        stage="bind_capture",
        outcome="completed",
        evidence_refs={"image_path": "artifacts/capture-c1.png"},
    )
    start_learning_workflow_stage_operation(
        store=store,
        project_root=tmp_path,
        run_id="run-c1",
        expected_revision=bound["revision"],
        stage="screen_understanding",
        operation_id="operation-c1",
    )
    composition = compose_test_learning_workflow_service_unit(
        store=store,
        worker_registry=registry,
        project_root=tmp_path,
        benchmark_supervision_root=object(),
        provider_case_resolver=object(),
        benchmark_v2_worker_binding_resolver=object(),
    )
    return (
        store,
        composition,
        incumbent.BenchmarkV2IncumbentWorkflowService(composition),
    )


def _s2_window_binding(source_bundle: dict[str, object]) -> dict[str, object]:
    source = source_bundle["handler_payload_source"]
    return _window_binding(
        run_id="run-c1",
        operation_id="operation-c1",
        window_binding_ref=deepcopy(source["window_binding_ref"]),
        capture_ref=deepcopy(source["capture_ref"]),
    )


def _install_s2_start(
    monkeypatch: pytest.MonkeyPatch,
    *,
    store,
    composition,
    source_bundle: dict[str, object],
    calls: list[dict[str, object]],
) -> None:
    import app.learn.workflow_service as workflow_service

    def _start(**kwargs):
        calls.append(
            {
                name: deepcopy(value)
                for name, value in kwargs.items()
                if name != "composition"
            }
        )
        current = store.get("run-c1")
        assert kwargs["expected_revision"] == current["revision"]
        operation = _prepared_document(
            source_bundle,
            prepared_revision=current["revision"] + 1,
        )
        workflow_service._persist_benchmark_v2_incumbent_operation(
            composition=composition,
            workflow_state=current,
            stage="screen_understanding",
            operation=operation,
        )
        return {
            "worker_id": operation["worker_ref"]["worker_id"],
            "workflow_revision": 999_999,
        }

    monkeypatch.setattr(
        workflow_service,
        "_start_benchmark_v2_incumbent_operation",
        _start,
    )


def _start_s2_service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    store,
    composition,
    service,
    source_bundle: dict[str, object],
    calls: list[dict[str, object]],
) -> dict[str, object]:
    _install_s2_start(
        monkeypatch,
        store=store,
        composition=composition,
        source_bundle=source_bundle,
        calls=calls,
    )
    source = source_bundle["handler_payload_source"]
    return service.start_incumbent_observe(
        provider_case_ref=deepcopy(source["provider_case_ref"]),
        window_binding=_s2_window_binding(source_bundle),
    )


def _persist_s2_transition(
    *,
    workflow_service,
    composition,
    current: dict[str, object],
    operation: dict[str, object],
    to_phase: str,
    changes: dict[str, object],
):
    operation = incumbent.transition_benchmark_v2_incumbent_operation(
        operation,
        to_phase=to_phase,
        changes=changes,
    )
    current = workflow_service._persist_benchmark_v2_incumbent_operation(
        composition=composition,
        workflow_state=current,
        stage="screen_understanding",
        operation=operation,
    )
    return current, operation


def test_s2_start_fixes_task_and_projects_authoritative_store_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_bundle: dict[str, object],
) -> None:
    registry = _S2Registry()
    store, composition, service = _s2_service(tmp_path, registry)
    calls: list[dict[str, object]] = []
    try:
        step = _start_s2_service(
            monkeypatch,
            store=store,
            composition=composition,
            service=service,
            source_bundle=source_bundle,
            calls=calls,
        )
        authoritative = store.get("run-c1")

        assert len(calls) == 1
        assert calls[0]["task_kind"] == "vision_observe_screen"
        assert calls[0]["request"] == {
            "provider_case_ref": source_bundle["handler_payload_source"][
                "provider_case_ref"
            ],
            "window_binding_ref": source_bundle["handler_payload_source"][
                "window_binding_ref"
            ],
            "capture_ref": source_bundle["handler_payload_source"]["capture_ref"],
        }
        assert step["status"] == "pending"
        assert step["observed_task_kind"] == "vision_observe_screen"
        assert step["operation_ref"]["workflow_state_ref"]["revision"] == (
            authoritative["revision"]
        )
        assert step["operation_ref"]["stage_execution_ref"]["revision"] == (
            authoritative["revision"]
        )
        assert step["operation_ref"]["worker_ref"]["worker_id"] == "worker-c1"
        assert step["artifact_is_authorization"] is False
        assert step["execute_binding_enabled"] is False
    finally:
        store.close()


@pytest.mark.parametrize(
    "mutated_parent",
    ("request_ref", "window_binding_ref", "capture_ref", "worker_ref"),
)
def test_s2_resealed_nonterminal_lineage_rejects_before_downstream_calls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_bundle: dict[str, object],
    mutated_parent: str,
) -> None:
    import app.learn.workflow_service as workflow_service
    from app.learn.recognition.uei.canonical import seal_immutable

    registry = _S2Registry()
    store, composition, service = _s2_service(tmp_path, registry)
    low_level_calls = {"resume": 0, "cancel": 0}
    start_calls: list[dict[str, object]] = []
    try:
        started = _start_s2_service(
            monkeypatch,
            store=store,
            composition=composition,
            service=service,
            source_bundle=source_bundle,
            calls=start_calls,
        )

        def _unexpected_resume(**_kwargs):
            low_level_calls["resume"] += 1
            raise AssertionError("stale operation reached Task6 resume")

        def _unexpected_cancel(**_kwargs):
            low_level_calls["cancel"] += 1
            raise AssertionError("stale operation reached Task6 cancel")

        monkeypatch.setattr(
            workflow_service,
            "_resume_benchmark_v2_incumbent_operation",
            _unexpected_resume,
        )
        monkeypatch.setattr(
            workflow_service,
            "_cancel_benchmark_v2_incumbent_operation",
            _unexpected_cancel,
        )
        stale = deepcopy(started["operation_ref"])
        if mutated_parent == "worker_ref":
            worker_body = deepcopy(stale["worker_ref"])
            worker_body.pop("content_sha256")
            worker_body["worker_id"] = "worker-cross-case"
            stale["worker_ref"] = seal_immutable(worker_body)
        else:
            stale[mutated_parent]["id"] = f"cross-{mutated_parent}"
        stale["content_sha256"] = content_sha256(stale)

        with pytest.raises(ValueError, match="stale"):
            service.poll_incumbent_observe(operation_ref=stale)

        assert registry.status_calls == 0
        assert registry.read_calls == 0
        assert registry.adopt_calls == 0
        assert registry.cancel_calls == 0
        assert len(start_calls) == 1
        assert low_level_calls == {"resume": 0, "cancel": 0}
    finally:
        store.close()


def test_s2_facade_and_low_level_start_share_one_task6_lock_and_dispatch_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_bundle: dict[str, object],
) -> None:
    import app.learn.workflow_service as workflow_service

    registry = _S2Registry()
    store, composition, service = _s2_service(tmp_path, registry)
    source = source_bundle["handler_payload_source"]
    request = {
        "provider_case_ref": deepcopy(source["provider_case_ref"]),
        "window_binding_ref": deepcopy(source["window_binding_ref"]),
        "capture_ref": deepcopy(source["capture_ref"]),
    }
    initial_revision = store.get("run-c1")["revision"]
    real_get_lock = workflow_service.get_learning_workflow_operation_lock
    shared_lock = real_get_lock(
        store=store,
        run_id="run-c1",
        operation_id="operation-c1",
    )
    lock_observations: list[tuple[str, str, object]] = []
    dispatch_count = 0
    fake_start_calls = 0
    active_count = 0
    maximum_active_count = 0
    start_gate = Barrier(3)
    results: list[dict[str, object]] = []
    errors: list[BaseException] = []

    def _tracked_get_lock(**kwargs):
        lock = real_get_lock(**kwargs)
        lock_observations.append((kwargs["run_id"], kwargs["operation_id"], lock))
        return lock

    def _serialized_start(**kwargs):
        nonlocal dispatch_count, fake_start_calls, active_count, maximum_active_count
        lock = workflow_service.get_learning_workflow_operation_lock(
            store=kwargs["composition"].store,
            run_id=kwargs["run_id"],
            operation_id=kwargs["operation_id"],
        )
        with lock:
            fake_start_calls += 1
            active_count += 1
            maximum_active_count = max(maximum_active_count, active_count)
            try:
                current = store.get("run-c1")
                operation = workflow_service._benchmark_v2_incumbent_operation_from_state(
                    current, "screen_understanding"
                )
                if operation is None:
                    dispatch_count += 1
                    operation = _prepared_document(
                        source_bundle,
                        prepared_revision=current["revision"] + 1,
                    )
                    workflow_service._persist_benchmark_v2_incumbent_operation(
                        composition=composition,
                        workflow_state=current,
                        stage="screen_understanding",
                        operation=operation,
                    )
                return {"worker_id": operation["worker_ref"]["worker_id"]}
            finally:
                active_count -= 1

    monkeypatch.setattr(
        workflow_service,
        "get_learning_workflow_operation_lock",
        _tracked_get_lock,
    )
    monkeypatch.setattr(
        workflow_service,
        "_start_benchmark_v2_incumbent_operation",
        _serialized_start,
    )

    def _run_high_level() -> None:
        try:
            start_gate.wait()
            results.append(
                service.start_incumbent_observe(
                    provider_case_ref=deepcopy(source["provider_case_ref"]),
                    window_binding=_s2_window_binding(source_bundle),
                )
            )
        except BaseException as error:
            errors.append(error)

    def _run_low_level() -> None:
        try:
            start_gate.wait()
            results.append(
                service.start(
                    run_id="run-c1",
                    expected_revision=initial_revision,
                    stage="screen_understanding",
                    operation_id="operation-c1",
                    task_kind="vision_observe_screen",
                    request=deepcopy(request),
                )
            )
        except BaseException as error:
            errors.append(error)

    high_level = Thread(target=_run_high_level, name="s2-high-level")
    low_level = Thread(target=_run_low_level, name="s2-low-level")
    try:
        high_level.start()
        low_level.start()
        start_gate.wait()
        high_level.join(timeout=10)
        low_level.join(timeout=10)

        assert not high_level.is_alive()
        assert not low_level.is_alive()
        assert errors == []
        assert len(results) == 2
        assert dispatch_count == 1
        assert fake_start_calls == 2
        assert maximum_active_count == 1
        assert len(lock_observations) == 3
        assert all(
            run_id == "run-c1"
            and operation_id == "operation-c1"
            and lock is shared_lock
            for run_id, operation_id, lock in lock_observations
        )
    finally:
        store.close()


def test_s2_poll_is_read_only_and_rejects_stale_ref_before_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_bundle: dict[str, object],
) -> None:
    registry = _S2Registry()
    store, composition, service = _s2_service(tmp_path, registry)
    try:
        started = _start_s2_service(
            monkeypatch,
            store=store,
            composition=composition,
            service=service,
            source_bundle=source_bundle,
            calls=[],
        )
        registry.worker_status = "completed"
        revision_before = store.get("run-c1")["revision"]
        advanced = service.poll_incumbent_observe(
            operation_ref=started["operation_ref"]
        )
        replay = service.poll_incumbent_observe(
            operation_ref=advanced["operation_ref"]
        )

        assert advanced["status"] == "advanced"
        assert replay == advanced
        assert store.get("run-c1")["revision"] == revision_before
        assert registry.status_calls == 2

        stale = deepcopy(advanced["operation_ref"])
        stale["workflow_state_ref"]["revision"] += 1
        stale["stage_execution_ref"]["revision"] += 1
        stale["content_sha256"] = content_sha256(stale)
        with pytest.raises(ValueError, match="stale"):
            service.poll_incumbent_observe(operation_ref=stale)
        assert registry.status_calls == 2
    finally:
        store.close()


def test_s2_adopt_returns_exact_response_and_terminal_replay_is_byte_identical(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_bundle: dict[str, object],
) -> None:
    import app.learn.workflow_service as workflow_service
    from app.learn.recognition.uei.canonical import seal_immutable

    registry = _S2Registry()
    store, composition, service = _s2_service(tmp_path, registry)
    resume_calls = 0
    response = {
        "success": True,
        "recorded_qwen_response": {"content": "observation only"},
        "action_candidates": [],
    }
    try:
        started = _start_s2_service(
            monkeypatch,
            store=store,
            composition=composition,
            service=service,
            source_bundle=source_bundle,
            calls=[],
        )
        registry.worker_status = "completed"
        advanced = service.poll_incumbent_observe(
            operation_ref=started["operation_ref"]
        )

        def _resume(**kwargs):
            nonlocal resume_calls
            resume_calls += 1
            current = store.get("run-c1")
            assert kwargs["expected_revision"] == current["revision"]
            operation = current["stages"]["screen_understanding"]["evidence_refs"][
                "stage_execution"
            ]["benchmark_v2_incumbent"]
            current, operation = _persist_s2_transition(
                workflow_service=workflow_service,
                composition=composition,
                current=current,
                operation=operation,
                to_phase="provider_owner_prepared",
                changes=_provider_owner_changes(),
            )
            current, operation = _persist_s2_transition(
                workflow_service=workflow_service,
                composition=composition,
                current=current,
                operation=operation,
                to_phase="worker_starting",
                changes={},
            )
            current, operation = _persist_s2_transition(
                workflow_service=workflow_service,
                composition=composition,
                current=current,
                operation=operation,
                to_phase="worker_bound",
                changes={
                    "worker_ref": {
                        **operation["worker_ref"],
                        "supervision_ref": {"content_sha256": "9" * 64},
                    }
                },
            )
            normal_binding_ref = seal_immutable({"kind": "normal-binding"})
            provider_evidence_ref = seal_immutable({"kind": "provider-evidence"})
            result_identity = seal_immutable(
                {
                    "result_sha256": "b" * 64,
                    "normal_binding_evidence_ref": normal_binding_ref,
                    "provider_cleanup_evidence_ref": provider_evidence_ref,
                }
            )
            current, operation = _persist_s2_transition(
                workflow_service=workflow_service,
                composition=composition,
                current=current,
                operation=operation,
                to_phase="result_ready",
                changes={"result_identity_ref": result_identity},
            )
            worker_cleanup = seal_immutable(
                {"outcome": "verified_exact_worker_exited"}
            )
            provider_cleanup = seal_immutable(
                {"outcome": "verified_exact_process_exited"}
            )
            terminal_intent = incumbent.compose_benchmark_v2_incumbent_terminal_intent(
                operation=operation,
                result_sha256="b" * 64,
                normal_binding_evidence_ref=normal_binding_ref,
                provider_cleanup_evidence_ref=provider_evidence_ref,
                worker_cleanup_evidence_ref=worker_cleanup,
                intent_at="2026-08-27T00:00:00+00:00",
            )
            current, operation = _persist_s2_transition(
                workflow_service=workflow_service,
                composition=composition,
                current=current,
                operation=operation,
                to_phase="terminal_intent",
                changes={"terminal_intent": terminal_intent},
            )
            receipt = {
                "contract_version": "learning_stage_worker_result_adoption_v1",
                "worker_id": operation["worker_ref"]["worker_id"],
                "run_id": operation["run_id"],
                "stage": operation["stage"],
                "operation_id": operation["operation_id"],
                "task_kind": "vision_observe_screen",
                "model_request_id": operation["worker_ref"]["model_request_id"],
                "payload_sha256": operation["worker_ref"]["payload_sha256"],
                "result_sha256": "b" * 64,
                "adopted_at": "2026-08-27T00:00:01+00:00",
            }
            registry.adoption = {
                "contract_version": "learning_stage_worker_result_adoption_v1",
                "status": "adopted",
                "receipt": receipt,
                "response": deepcopy(response),
            }
            generic_ref = {"content_sha256": content_sha256(receipt)}
            current, operation = _persist_s2_transition(
                workflow_service=workflow_service,
                composition=composition,
                current=current,
                operation=operation,
                to_phase="adopted",
                changes={"generic_adoption_ref": generic_ref},
            )
            window_adoption = seal_immutable(
                {
                    "contract_version": "benchmark-window-adoption-test-v1",
                    "artifact_is_authorization": False,
                    "execute_binding_enabled": False,
                }
            )
            terminal_receipt = (
                incumbent.compose_benchmark_v2_incumbent_terminal_receipt(
                    operation=operation,
                    outcome="benchmark_v2_incumbent_observe_complete",
                    window_adoption_ref=window_adoption,
                    worker_cleanup_ref=worker_cleanup,
                    provider_cleanup_ref=provider_cleanup,
                    terminal_at="2026-08-27T00:00:02+00:00",
                )
            )
            current, operation = _persist_s2_transition(
                workflow_service=workflow_service,
                composition=composition,
                current=current,
                operation=operation,
                to_phase="complete",
                changes={
                    "window_adoption_ref": window_adoption,
                    "worker_cleanup_ref": worker_cleanup,
                    "provider_cleanup_ref": provider_cleanup,
                    "terminal_receipt": terminal_receipt,
                },
            )
            return {
                "contract_version": "benchmark_v2_incumbent_resume_v1",
                "status": "complete",
                "terminal_receipt": terminal_receipt,
                "operation": operation,
            }

        monkeypatch.setattr(
            workflow_service,
            "_resume_benchmark_v2_incumbent_operation",
            _resume,
        )
        complete = service.adopt_and_terminalize_incumbent(
            operation_ref=advanced["operation_ref"],
            worker_ref=advanced["worker_ref"],
        )
        revision_after_complete = store.get("run-c1")["revision"]
        for mutated_parent in (
            "stage_execution_ref",
            "predecessor_content_sha256",
        ):
            stale_terminal_ref = deepcopy(complete["operation_ref"])
            if mutated_parent == "stage_execution_ref":
                stale_terminal_ref[mutated_parent]["content_sha256"] = "0" * 64
            else:
                stale_terminal_ref[mutated_parent] = "0" * 64
            stale_terminal_ref["content_sha256"] = content_sha256(
                stale_terminal_ref
            )
            with pytest.raises(ValueError, match="stale"):
                service.adopt_and_terminalize_incumbent(
                    operation_ref=stale_terminal_ref,
                    worker_ref=complete["worker_ref"],
                )
            assert resume_calls == 1
            assert registry.read_calls == 1
            assert registry.adopt_calls == 0
            assert registry.cancel_calls == 0
        replay = service.adopt_and_terminalize_incumbent(
            operation_ref=complete["operation_ref"],
            worker_ref=complete["worker_ref"],
        )

        assert complete["status"] == "complete"
        assert complete["adopted_result_projection"]["response"] == response
        assert complete["adopted_result_projection"]["terminal_receipt"] == (
            complete["terminal_receipt"]
        )
        assert canonical_json_bytes(replay) == canonical_json_bytes(complete)
        assert store.get("run-c1")["revision"] == revision_after_complete
        assert resume_calls == 1
        assert registry.read_calls == 2
        registry.adoption["response"] = None
        with pytest.raises(ValueError, match="generic adoption lineage differs"):
            service.adopt_and_terminalize_incumbent(
                operation_ref=complete["operation_ref"],
                worker_ref=complete["worker_ref"],
            )
        assert resume_calls == 1
        assert registry.read_calls == 3
    finally:
        store.close()


def test_s2_cancel_routes_existing_task6_path_and_projects_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_bundle: dict[str, object],
) -> None:
    import app.learn.workflow_service as workflow_service
    from app.learn.recognition.uei.canonical import seal_immutable

    registry = _S2Registry()
    store, composition, service = _s2_service(tmp_path, registry)
    cancel_calls = 0
    try:
        started = _start_s2_service(
            monkeypatch,
            store=store,
            composition=composition,
            service=service,
            source_bundle=source_bundle,
            calls=[],
        )

        def _cancel(**kwargs):
            nonlocal cancel_calls
            cancel_calls += 1
            current = store.get("run-c1")
            assert kwargs["expected_revision"] == current["revision"]
            operation = current["stages"]["screen_understanding"]["evidence_refs"][
                "stage_execution"
            ]["benchmark_v2_incumbent"]
            intent = incumbent.compose_benchmark_v2_incumbent_cancel_intent(
                operation=operation,
                reason=kwargs["reason"],
                intent_at="2026-08-27T00:00:00+00:00",
                process_identity=None,
                scope_name=None,
                assignment_proven_ref=None,
            )
            current, operation = _persist_s2_transition(
                workflow_service=workflow_service,
                composition=composition,
                current=current,
                operation=operation,
                to_phase="cancel_intent",
                changes={"cancel_intent": intent},
            )
            worker_cleanup = seal_immutable({"outcome": "verified_not_launched"})
            provider_cleanup = seal_immutable({"outcome": "verified_not_acquired"})
            current, operation = _persist_s2_transition(
                workflow_service=workflow_service,
                composition=composition,
                current=current,
                operation=operation,
                to_phase="cleanup_pending",
                changes={
                    "worker_cleanup_ref": worker_cleanup,
                    "provider_cleanup_ref": provider_cleanup,
                },
            )
            operation = incumbent.advance_benchmark_v2_incumbent_cancel_cleanup(
                operation,
                worker_cleanup_ref=worker_cleanup,
                provider_cleanup_ref=provider_cleanup,
                provider_materialization_state="aborted_never_materialized",
                provider_lease_acquired=False,
                terminal_at="2026-08-27T00:00:01+00:00",
            )
            workflow_service._persist_benchmark_v2_incumbent_operation(
                composition=composition,
                workflow_state=current,
                stage="screen_understanding",
                operation=operation,
            )
            return {
                "contract_version": "benchmark_v2_incumbent_cancel_v1",
                "status": "cancelled",
                "terminal_receipt": operation["terminal_receipt"],
                "operation": operation,
            }

        monkeypatch.setattr(
            workflow_service,
            "_cancel_benchmark_v2_incumbent_operation",
            _cancel,
        )
        cancelled = service.cancel_operation(operation_ref=started["operation_ref"])

        assert cancelled["status"] == "cancelled"
        assert cancelled["adopted_result_projection"] is None
        assert cancelled["terminal_receipt"]["outcome"] == (
            "benchmark_v2_incumbent_cancelled"
        )
        assert cancelled["cleanup_refs"]["worker_cleanup_ref"]["outcome"] == (
            "verified_not_launched"
        )
        assert cancelled["cleanup_refs"]["provider_cleanup_ref"]["outcome"] == (
            "verified_not_acquired"
        )
        assert cancel_calls == 1
    finally:
        store.close()


class _S3Registry:
    def __init__(self) -> None:
        self.records: list[dict[str, object]] = []
        self.start_calls = 0
        self.status_calls = 0
        self.adopt_calls = 0
        self.read_calls = 0
        self.cancel_calls = 0
        self.materialize_cleanup_calls = 0
        self.active_resources = 0

    @property
    def current(self) -> dict[str, object] | None:
        return self.records[-1] if self.records else None

    def start(self, **kwargs) -> dict[str, object]:
        current = self.current
        if (
            kwargs.get("reuse_active_identical") is True
            and isinstance(current, dict)
            and current["status"] == "running"
            and current["task_kind"] == kwargs["task_kind"]
            and current["payload"] == kwargs["payload"]
        ):
            return deepcopy(current)
        self.start_calls += 1
        payload_bytes = json.dumps(
            kwargs["payload"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        record: dict[str, object] = {
            "worker_id": f"worker-hybrid-{self.start_calls}",
            "run_id": kwargs["run_id"],
            "stage": kwargs["stage"],
            "operation_id": kwargs["operation_id"],
            "task_kind": kwargs["task_kind"],
            "model_request_id": f"request-hybrid-{self.start_calls}",
            "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
            "authoritative_workflow_revision": kwargs.get(
                "authoritative_workflow_revision"
            ),
            "payload": deepcopy(kwargs["payload"]),
            "status": "running",
            "runtime_attached": True,
            "result_available": False,
            "result_adopted": False,
            "adoption_receipt": None,
        }
        self.records.append(record)
        self.active_resources = 1
        return deepcopy(record)

    def status(self, **kwargs) -> dict[str, object]:
        self.status_calls += 1
        current = self._owned(kwargs)
        return deepcopy(current)

    def attachment_by_operation(self, **kwargs) -> dict[str, object] | None:
        current = self.current
        if current is None:
            return None
        if any(current[name] != kwargs[name] for name in kwargs):
            return None
        return deepcopy(current)

    def adopt_result(self, **kwargs) -> dict[str, object]:
        self.adopt_calls += 1
        current = self._owned(kwargs)
        if current["status"] != "completed":
            raise AssertionError("hybrid worker was adopted before completion")
        result_validator = kwargs.get("result_validator")
        if callable(result_validator):
            result_validator(deepcopy(current["response"]))
        receipt = current.get("adoption_receipt")
        if not isinstance(receipt, dict):
            response = current["response"]
            result_sha256 = hashlib.sha256(
                json.dumps(
                    {"status": "completed", "response": response},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            receipt = {
                "contract_version": "learning_stage_worker_result_adoption_v1",
                "worker_id": current["worker_id"],
                "run_id": current["run_id"],
                "stage": current["stage"],
                "operation_id": current["operation_id"],
                "task_kind": current["task_kind"],
                "model_request_id": current["model_request_id"],
                "payload_sha256": current["payload_sha256"],
                "result_sha256": result_sha256,
                "adopted_at": "2026-08-27T00:00:00+00:00",
            }
            current["adoption_receipt"] = receipt
            current["result_adopted"] = True
        return {
            "contract_version": "learning_stage_worker_result_adoption_v1",
            "status": "adopted",
            "receipt": deepcopy(receipt),
            "response": deepcopy(current["response"]),
        }

    def read_adopted_result(self, **kwargs) -> dict[str, object]:
        self.read_calls += 1
        current = self._owned(kwargs)
        receipt = current.get("adoption_receipt")
        if not isinstance(receipt, dict):
            raise AssertionError("hybrid terminal replay preceded adoption")
        return {
            "contract_version": "learning_stage_worker_result_adoption_v1",
            "status": "adopted",
            "receipt": deepcopy(receipt),
            "response": deepcopy(current["response"]),
        }

    def cancel_by_operation(self, **kwargs) -> dict[str, object]:
        self.cancel_calls += 1
        current = self._owned(kwargs)
        if (
            current["task_kind"] == "panel_learning_hybrid_fusion"
            and current["status"] == "completed"
        ):
            self.active_resources = 0
            return {
                **deepcopy(current),
                "backend_compute_termination": "not_running",
                "model_service_compute_termination": "request_not_active",
                "model_request_cancellation": {"status": "request_not_active"},
            }
        current["status"] = "cancelled"
        current["runtime_attached"] = False
        self.active_resources = 0
        provider_cleanup_ref = seal_immutable(
            {
                "contract_version": "benchmark_provider_cleanup_ref_v1",
                "status": "cleanup_verified",
                "outcome": "verified_exact_process_exited",
                "authority_kind": (
                    "benchmark_v2_workflow_service_dispatch_cleanup"
                ),
                "run_id": current["run_id"],
                "stage": current["stage"],
                "operation_id": current["operation_id"],
                "worker_id": current["worker_id"],
                "model_request_id": current["model_request_id"],
                "payload_sha256": current["payload_sha256"],
                "reservation_ref": {"content_sha256": "a" * 64},
                "acquisition_owner_ref": {"content_sha256": "b" * 64},
                "acquisition_intent_ref": {"content_sha256": "c" * 64},
                "runtime_owner_ref": {"content_sha256": "c" * 64},
                "cleanup_receipt_ref": {"content_sha256": "d" * 64},
            }
        )
        current["benchmark_provider_cleanup_ref"] = provider_cleanup_ref
        return {
            "worker_id": current["worker_id"],
            "model_request_id": current["model_request_id"],
            "payload_sha256": current["payload_sha256"],
            "backend_compute_termination": "terminated",
            "model_service_compute_termination": "request_not_active",
            "model_request_cancellation": {"status": "not_active"},
            "benchmark_provider_cleanup_ref": deepcopy(provider_cleanup_ref),
        }

    def attest_completed_fusion_direct_provider_cleanup(
        self, **kwargs
    ) -> dict[str, object]:
        current = self._owned(kwargs)
        worker_ref = deepcopy(kwargs["returned_worker_ref"])
        worker_cleanup = deepcopy(kwargs["worker_cleanup_ref"])
        observation = seal_immutable(
            {
                "contract_version": (
                    "benchmark_v2_hybrid_fusion_direct_provider_absence_observation_v1"
                ),
                **{
                    name: current[name]
                    for name in (
                        "run_id", "stage", "operation_id", "worker_id",
                        "model_request_id", "payload_sha256", "task_kind",
                    )
                },
                "handler_registry_provider": None,
                "evidence_scope": "fusion_worker_direct_provider_only",
                "current_worker_ref": worker_ref,
                "latest_operation_worker_ref": worker_ref,
                "worker_runtime_attachment_absent": True,
                "provider_scope_absent": True,
                "provider_journal_absent": True,
                "provider_cleanup_journal_absent": True,
                "deterministic_provider_lease_artifact_absent": True,
                "deterministic_provider_owner_artifact_absent": True,
                "deterministic_provider_runtime_artifact_absent": True,
                "historical_provider_lineage_allowed": True,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        )
        return seal_immutable(
            {
                "contract_version": (
                    "benchmark_v2_hybrid_fusion_direct_provider_cleanup_ref_v1"
                ),
                "status": "cleanup_verified",
                "outcome": "verified_fusion_direct_provider_not_applicable",
                "authority_kind": (
                    "benchmark_v2_workflow_service_fusion_direct_provider_cleanup"
                ),
                **{
                    name: current[name]
                    for name in (
                        "run_id", "stage", "operation_id", "worker_id",
                        "model_request_id", "payload_sha256", "task_kind",
                    )
                },
                "direct_provider_role": None,
                "evidence_scope": "fusion_worker_direct_provider_only",
                "worker_status": "completed",
                "runtime_attached": False,
                "result_available": True,
                "result_adopted": True,
                "continuation_phase": kwargs["continuation_phase"],
                "cancellation_backend_termination": worker_cleanup[
                    "backend_compute_termination"
                ],
                "cancellation_model_request_termination": worker_cleanup[
                    "model_service_compute_termination"
                ],
                "service_binding_ref": deepcopy(kwargs["service_binding_ref"]),
                "terminal_continuation_receipt_ref": deepcopy(
                    kwargs["terminal_continuation_receipt_ref"]
                ),
                "returned_worker_ref": worker_ref,
                "worker_cleanup_ref": {
                    "content_sha256": worker_cleanup["content_sha256"]
                },
                "live_absence_observation": observation,
                "historical_provider_lineage_allowed": True,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        )

    def materialize_completed_hybrid_provider_cleanup(
        self, **kwargs
    ) -> dict[str, object]:
        self.materialize_cleanup_calls += 1
        current = self._owned(kwargs)
        if (
            current["status"] != "completed"
            or current["runtime_attached"] is not False
            or current["result_available"] is not True
        ):
            raise AssertionError("completed Hybrid cleanup was materialized too early")
        context_ref = kwargs.get("dispatch_context_ref")
        if (
            not isinstance(context_ref, dict)
            or context_ref.get("provider") not in {"omni", "qwen"}
            or not isinstance(context_ref.get("dispatch_context"), dict)
        ):
            raise AssertionError("completed Hybrid cleanup lost its service context")
        projection = current.get("benchmark_provider_cleanup_ref")
        if not isinstance(projection, dict):
            projection = _s3_provider_cleanup_ref(current)
            current["benchmark_provider_cleanup_ref"] = projection
        return deepcopy(projection)

    def complete_current(self, response: dict[str, object]) -> None:
        current = self.current
        if current is None:
            raise AssertionError("no hybrid worker exists")
        current["status"] = "completed"
        current["runtime_attached"] = False
        current["result_available"] = True
        current["response"] = deepcopy(response)
        self.active_resources = 0

    def _owned(self, kwargs: dict[str, object]) -> dict[str, object]:
        current = self.current
        if current is None:
            raise AssertionError("hybrid worker is missing")
        for name in ("worker_id", "run_id", "stage", "operation_id"):
            if name in kwargs and current[name] != kwargs[name]:
                raise AssertionError(f"hybrid worker ownership differs: {name}")
        return current


def _s3_provider_cleanup_ref(worker: dict[str, object]) -> dict[str, object]:
    return seal_immutable(
        {
            "contract_version": "benchmark_provider_cleanup_ref_v1",
            "status": "cleanup_verified",
            "outcome": "verified_exact_process_exited",
            "authority_kind": "benchmark_v2_workflow_service_dispatch_cleanup",
            "run_id": worker["run_id"],
            "stage": worker["stage"],
            "operation_id": worker["operation_id"],
            "worker_id": worker["worker_id"],
            "model_request_id": worker["model_request_id"],
            "payload_sha256": worker["payload_sha256"],
            "reservation_ref": {"content_sha256": "a" * 64},
            "acquisition_owner_ref": {"content_sha256": "b" * 64},
            "acquisition_intent_ref": {"content_sha256": "c" * 64},
            "runtime_owner_ref": {"content_sha256": "d" * 64},
            "cleanup_receipt_ref": {"content_sha256": "e" * 64},
        }
    )


def _s3_vista_supervisor_cleanup_receipt(
    worker: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    from app.learn.hybrid.gpu_lifecycle import release_hybrid_provider

    lineage_body = {
        "run_id": str(worker["run_id"]),
        "workflow_revision": 0,
        "operation_id": str(worker["operation_id"]),
        "stage": str(worker["stage"]),
    }
    lineage = {
        **lineage_body,
        "stage_execution_id": hashlib.sha256(
            json.dumps(
                lineage_body,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }
    process_identity = {"pid": 404, "create_time_ns": 505}
    process_scope_name = f"Local\\AgentGuiHybrid-vista-{'f' * 64}"
    model_lease = {
        "contract_version": "hybrid_vista_model_lease_v2",
        "provider": "vista",
        "incarnation_id": "vista-incarnation-h1",
        "process_identities": [deepcopy(process_identity)],
        "process_scope_name": process_scope_name,
        "profile": {
            "profile_id": "vista_4b_transformers",
            "host": "127.0.0.1",
            "port": 13244,
        },
        "process_scope_acquisition": {
            "contract_version": "hybrid_process_scope_acquisition_v1",
            "scope_name": process_scope_name,
            "member_pids": [process_identity["pid"]],
            "process_identities": [deepcopy(process_identity)],
        },
    }
    inventory = {
        "contract_version": "hybrid_provider_process_inventory_v2",
        "provider": "vista",
        "observer_contract": "hybrid_vista_cleanup_observer_v1",
        "release_status": "verified",
        "termination_reason": "failed_worker_reconciled",
        "lineage": lineage,
        "provider_lease_identity": {
            "incarnation_id": model_lease["incarnation_id"],
            "profile_id": "vista_4b_transformers",
            "process_identities": [deepcopy(process_identity)],
            "process_scope_name": process_scope_name,
        },
        "predecessor_sha256": "7" * 64,
        "provider_result_sha256": "8" * 64,
        "provider_processes_after": [],
        "helper_processes_after": [],
        "orphan_descendant_pids": [],
        "active_listeners_after": [],
        "lease_files_after": [],
        "source_cleanup_evidence": {
            "status": "verified",
            "model_lease": model_lease,
        },
    }
    receipt = release_hybrid_provider(
        "vista",
        process_inventory=lambda _provider: inventory,
    )
    return receipt, lineage


class _S3ReviewNoProviderRegistry(_S3Registry):
    def __init__(self) -> None:
        super().__init__()
        self.review_no_provider_cleanup_calls = 0

    def cancel_by_operation(self, **kwargs) -> dict[str, object]:
        self.cancel_calls += 1
        current = self._owned(kwargs)
        if current["status"] != "completed":
            raise AssertionError("review worker must already be completed")
        self.active_resources = 0
        return {
            **deepcopy(current),
            "backend_compute_termination": "not_running",
            "model_service_compute_termination": "request_not_active",
            "model_request_cancellation": {"status": "request_not_active"},
        }

    def attest_completed_review_no_provider_cleanup(
        self, **kwargs
    ) -> dict[str, object]:
        self.review_no_provider_cleanup_calls += 1
        current = self._owned(kwargs)
        worker_ref = kwargs["returned_worker_ref"]
        worker_cleanup = kwargs["worker_cleanup_ref"]
        observation = seal_immutable(
            {
                "contract_version": (
                    "benchmark_v2_hybrid_no_provider_live_absence_observation_v1"
                ),
                **{
                    name: current[name]
                    for name in (
                        "run_id",
                        "stage",
                        "operation_id",
                        "worker_id",
                        "model_request_id",
                        "payload_sha256",
                    )
                },
                "task_kind": "panel_learning_hybrid_review_projection",
                "provider_role": "review",
                "current_worker_ref": deepcopy(worker_ref),
                "latest_operation_worker_ref": deepcopy(worker_ref),
                "review_dispatch_context_absent": True,
                "review_dispatch_receipt_absent": True,
                "provider_scope_absent": True,
                "provider_journal_absent": True,
                "provider_cleanup_journal_absent": True,
                "deterministic_provider_lease_artifact_absent": True,
                "deterministic_provider_owner_artifact_absent": True,
                "deterministic_provider_runtime_artifact_absent": True,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        )
        projection = seal_immutable(
            {
                "contract_version": (
                    "benchmark_v2_hybrid_no_provider_cleanup_ref_v1"
                ),
                "status": "cleanup_verified",
                "outcome": "verified_review_provider_not_applicable",
                "authority_kind": (
                    "benchmark_v2_workflow_service_review_no_provider_cleanup"
                ),
                **{
                    name: current[name]
                    for name in (
                        "run_id",
                        "stage",
                        "operation_id",
                        "worker_id",
                        "model_request_id",
                        "payload_sha256",
                    )
                },
                "task_kind": "panel_learning_hybrid_review_projection",
                "provider_role": "review",
                "worker_status": "completed",
                "runtime_attached": False,
                "result_available": True,
                "result_adopted": True,
                "continuation_phase": "terminal_prepared",
                "cancellation_backend_termination": worker_cleanup[
                    "backend_compute_termination"
                ],
                "cancellation_model_request_termination": worker_cleanup[
                    "model_service_compute_termination"
                ],
                "service_binding_ref": deepcopy(kwargs["service_binding_ref"]),
                "terminal_prepared_continuation_receipt_ref": deepcopy(
                    kwargs["terminal_prepared_continuation_receipt_ref"]
                ),
                "returned_worker_ref": deepcopy(worker_ref),
                "worker_cleanup_ref": {
                    "content_sha256": worker_cleanup["content_sha256"]
                },
                "live_absence_observation": observation,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
            }
        )
        current["benchmark_v2_no_provider_cleanup_ref"] = deepcopy(projection)
        return projection


def _s3_service(
    tmp_path: Path,
    registry: _S3Registry,
    *,
    benchmark_v2_worker_binding_resolver: object | None = None,
):
    from app.learn.workflow_service import (
        compose_test_learning_workflow_service_unit,
        start_learning_workflow_stage_operation,
    )
    from app.learn.workflow_store import LearningWorkflowRunStore

    store = LearningWorkflowRunStore(state_path=tmp_path / "workflow-state.json")
    binding = store.transition(
        run_id="run-h1",
        expected_revision=0,
        stage="bind_capture",
        outcome="running",
        evidence_refs={},
    )
    bound = store.transition(
        run_id="run-h1",
        expected_revision=binding["revision"],
        stage="bind_capture",
        outcome="completed",
        evidence_refs={"image_path": "artifacts/hybrid-capture.png"},
    )
    started = start_learning_workflow_stage_operation(
        store=store,
        project_root=tmp_path,
        run_id="run-h1",
        expected_revision=bound["revision"],
        stage="screen_understanding",
        operation_id="operation-h1",
        learning_pipeline_mode="hybrid_v1_1",
    )
    composition = compose_test_learning_workflow_service_unit(
        store=store,
        worker_registry=registry,
        project_root=tmp_path,
        benchmark_v2_worker_binding_resolver=benchmark_v2_worker_binding_resolver,
    )
    return (
        store,
        composition,
        incumbent.BenchmarkV2IncumbentWorkflowService(composition),
        started,
    )


def _s3_window_binding() -> dict[str, object]:
    return _window_binding(run_id="run-h1", operation_id="operation-h1")


def _s3_omni_dispatch_context(tmp_path: Path) -> dict[str, object]:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as attestation

    binding = _s3_window_binding()
    operation_ref = {
        "run_id": "run-h1",
        "stage": "screen_understanding",
        "operation_id": "operation-h1",
        "revision": 4,
        "window_binding_ref": deepcopy(binding["window_binding_ref"]),
        "capture_ref": deepcopy(binding["capture_ref"]),
    }
    return attestation.compose_benchmark_dispatch_context(
        provider="omni",
        operation_ref=operation_ref,
        window_binding={
            "contract_version": "test_window_binding_v1",
            "exact_hwnd": 101,
            "process_identity": {"pid": 202, "create_time_ns": 303},
            "job_name": "job-h1",
            "payload_sha256": "c" * 64,
        },
        receipt_journal_path=attestation._fixed_dispatch_journal_path(
            operation_ref
        ),
    )


def test_s3_hybrid_binding_keeps_each_exact_server_issued_provider_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import workflow_service
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as attestation
    from app.learn.hybrid.benchmark_v2_dispatch_attestation import (
        compose_benchmark_dispatch_context,
    )

    monkeypatch.setattr(attestation, "PROJECT_ROOT", tmp_path)
    binding = workflow_service._compose_benchmark_v2_hybrid_service_binding(
        screen_group=_screen_group(),
        window_binding=_s3_window_binding(),
    )
    contexts = []
    for provider, revision in (("omni", 7), ("qwen", 8), ("vista", 10)):
        operation_ref = {
            "run_id": "run-h1",
            "stage": "screen_understanding",
            "operation_id": "operation-h1",
            "revision": revision,
            "window_binding_ref": deepcopy(
                _s3_window_binding()["window_binding_ref"]
            ),
            "capture_ref": deepcopy(_s3_window_binding()["capture_ref"]),
        }
        context = compose_benchmark_dispatch_context(
            provider=provider,
            operation_ref=operation_ref,
            window_binding={
                "contract_version": "test_window_binding_v1",
                "exact_hwnd": 101,
                "process_identity": {"pid": 202, "create_time_ns": 303},
                "job_name": "job-h1",
                "payload_sha256": "c" * 64,
            },
            receipt_journal_path=attestation._fixed_dispatch_journal_path(
                operation_ref
            ),
        )
        contexts.append(context)
        binding = workflow_service._benchmark_v2_hybrid_binding_with_dispatch_context(
            binding=binding,
            context=context,
        )

    refs = binding["provider_dispatch_context_refs"]
    assert [
        refs[provider]["dispatch_context"]["operation_ref"]["revision"]
        for provider in ("omni", "qwen", "vista")
    ] == [7, 8, 10]
    assert [
        refs[provider]["dispatch_context"]["content_sha256"]
        for provider in ("omni", "qwen", "vista")
    ] == [context["content_sha256"] for context in contexts]

    stale_qwen = deepcopy(contexts[1])
    stale_qwen["operation_ref"]["revision"] = 9
    from app.learn.hybrid.benchmark_v2_contracts import content_sha256

    stale_qwen["operation_ref"].pop("content_sha256")
    stale_qwen["operation_ref"]["content_sha256"] = content_sha256(
        stale_qwen["operation_ref"]
    )
    stale_qwen["content_sha256"] = content_sha256(stale_qwen)
    with pytest.raises(
        workflow_service.LearningWorkflowStageOperationError,
        match="already issued|differs|stale",
    ):
        workflow_service._benchmark_v2_hybrid_binding_with_dispatch_context(
            binding=binding,
            context=stale_qwen,
        )


def test_s3_public_facade_adopts_each_server_issued_provider_revision_across_transitions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import workflow_service
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as attestation

    monkeypatch.setattr(attestation, "PROJECT_ROOT", tmp_path)
    registry = _S3Registry()
    store, composition, service, _started = _s3_service(
        tmp_path,
        registry,
        benchmark_v2_worker_binding_resolver=object(),
    )
    serialized_window = {
        "contract_version": "test_window_binding_v1",
        "exact_hwnd": 101,
        "process_identity": {"pid": 202, "create_time_ns": 303},
        "job_name": "job-h1",
        "payload_sha256": "c" * 64,
    }
    monkeypatch.setattr(
        "app.learn.hybrid.benchmark_v2_worker_binding.resolve_server_worker_window_binding",
        lambda **_kwargs: {"serialized_window_binding": deepcopy(serialized_window)},
    )
    monkeypatch.setattr(
        attestation,
        "_attest_exact_window",
        lambda value: {"content_sha256": "d" * 64},
    )
    from test_portfolio_hybrid_v1_1_benchmark_v2_dispatch_attestation import (
        _runtime_attestation,
    )

    monkeypatch.setattr(
        attestation,
        "_attest_exact_provider_runtime",
        lambda provider, value: _runtime_attestation(
            attestation,
            provider=provider,
            digit={"omni": "1", "qwen": "2", "vista": "3"}[provider],
        ),
    )
    task_order = [
        "panel_learning_hybrid_omni_discovery",
        "panel_learning_hybrid_qwen_binding",
        "panel_learning_hybrid_fusion",
        "panel_learning_calibration_sequence",
        "panel_learning_hybrid_review_projection",
    ]
    receipt_refs: list[dict[str, str]] = []
    context_refs: dict[str, dict[str, object]] = {}
    issued_revisions: dict[str, int] = {}
    continuation_calls = 0
    public_context_projections: list[dict[str, object] | None] = []

    def _complete_current() -> None:
        current = registry.current
        assert current is not None
        payload = current["payload"]
        assert isinstance(payload, dict)
        assert payload["workflow_revision"] == 0
        assert payload["_hybrid_orchestration"]["workflow_revision"] == 0
        assert current["authoritative_workflow_revision"] == 0
        context = payload.get("_benchmark_v2_dispatch_context")
        task_kind = str(current["task_kind"])
        if isinstance(context, dict):
            provider = str(context["provider"])
            dispatch_count = 2 if provider == "vista" else 1
            with attestation.install_benchmark_dispatch_attestor(
                dispatch_context=context
            ):
                for _ in range(dispatch_count):
                    attestation.attest_benchmark_provider_dispatch(
                        provider=provider,
                        operation_ref=context["operation_ref"],
                        window_binding=context["window_binding"],
                        provider_runtime={"provider": provider},
                    )
                receipt_refs.extend(
                    attestation.current_benchmark_dispatch_receipt_refs()
                )
            context_refs[provider] = (
                attestation.compose_benchmark_dispatch_context_ref(context=context)
            )
            issued_revisions[provider] = int(context["operation_ref"]["revision"])
        orchestration: dict[str, object] = {
            "benchmark_v2_provider_dispatch_receipt_refs": deepcopy(receipt_refs),
            "benchmark_v2_provider_dispatch_context_refs": deepcopy(context_refs),
        }
        if "vista" in context_refs:
            orchestration["benchmark_v2_vista_batch_count"] = 2
        result: dict[str, object] = {"success": True}
        if task_kind == "panel_learning_calibration_sequence":
            result = {
                "success": True,
                "data": {
                    "result": {
                        "calibration_sequence": {
                            "contract_version": "learning_calibration_sequence_result_v1",
                            "status": "completed",
                            "batch_count": 2,
                        }
                    }
                },
            }
        registry.complete_current(
            {
                "contract_version": "learning_hybrid_managed_stage_result_v1",
                "orchestration": orchestration,
                "result": result,
            }
        )

    def _continue(**kwargs):
        nonlocal continuation_calls
        continuation_calls += 1
        current_worker = registry.current
        assert current_worker is not None
        index = task_order.index(str(current_worker["task_kind"]))
        state = store.get("run-h1")
        if index + 1 < len(task_order):
            next_task_kind = task_order[index + 1]
            context = workflow_service._benchmark_v2_dispatch_context_for_worker(
                composition=composition,
                window_binding=_s3_window_binding(),
                task_kind=next_task_kind,
                revision=int(state["revision"]),
            )
            sink = kwargs.get("_benchmark_dispatch_context_sink")
            if isinstance(context, dict) and callable(sink):
                sink(context)
            orchestration = deepcopy(
                current_worker["payload"]["_hybrid_orchestration"]
            )
            payload = {
                "learning_pipeline_mode": "hybrid_v1_1",
                "workflow_revision": orchestration["workflow_revision"],
                "_hybrid_orchestration": orchestration,
                "sequence_index": index + 1,
            }
            if isinstance(context, dict):
                payload["_benchmark_v2_dispatch_context"] = context
            worker = workflow_service.start_guarded_learning_stage_worker(
                composition=composition,
                run_id="run-h1",
                expected_revision=int(state["revision"]),
                stage="screen_understanding",
                operation_id="operation-h1",
                task_kind=next_task_kind,
                payload=payload,
                reuse_active_identical=True,
            )
            return {
                "stage_finished": False,
                "next_worker": worker,
                "workflow_state": state,
            }
        evidence_path = tmp_path / "artifacts" / "hybrid-review.json"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text("{}", encoding="utf-8")
        finished = workflow_service.finish_learning_workflow_stage_operation(
            store=store,
            project_root=tmp_path,
            run_id="run-h1",
            expected_revision=int(state["revision"]),
            stage="screen_understanding",
            operation_id="operation-h1",
            outcome="completed",
            reason="hybrid review completed",
            evidence_refs={"trial_path": "artifacts/hybrid-review.json"},
        )
        return {
            "stage_finished": True,
            "outcome": "completed",
            "next_stage_operation": None,
            "next_stage_worker": None,
            "workflow_state": finished["workflow_state"],
        }

    monkeypatch.setattr(
        workflow_service,
        "continue_guarded_learning_stage_worker_result",
        _continue,
    )
    try:
        step = service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        observed = []
        while step["status"] != "complete":
            observed.append(step["observed_task_kind"])
            public_context_projections.append(
                deepcopy(step["provider_dispatch_context_projection"])
            )
            _complete_current()
            step = service.continue_hybrid_operation(
                operation_ref=step["operation_ref"]
            )

        assert observed == task_order
        assert list(issued_revisions) == ["omni", "qwen", "vista"]
        assert issued_revisions["omni"] < issued_revisions["qwen"]
        assert issued_revisions["qwen"] < issued_revisions["vista"]
        assert [
            projection["provider"] if isinstance(projection, dict) else None
            for projection in public_context_projections
        ] == ["omni", "qwen", None, "vista", None]
        assert [
            projection["operation_ref"]["revision"]
            for projection in public_context_projections
            if isinstance(projection, dict)
        ] == [
            issued_revisions["omni"],
            issued_revisions["qwen"],
            issued_revisions["vista"],
        ]
        assert all(
            "receipt_journal_path" not in projection
            for projection in public_context_projections
            if isinstance(projection, dict)
        )
        assert continuation_calls == len(task_order)
        assert registry.adopt_calls == len(task_order)
        assert len(receipt_refs) == 4
    finally:
        store.close()


def test_s3_start_uses_authoritative_initial_builder_once_and_replays(
    tmp_path: Path,
) -> None:
    registry = _S3Registry()
    store, _composition, service, _started = _s3_service(tmp_path, registry)
    try:
        first = service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        replay = service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )

        assert first == replay
        assert first["mode"] == "hybrid_v1_1"
        assert first["observed_task_kind"] == (
            "panel_learning_hybrid_omni_discovery"
        )
        assert registry.start_calls == 1
        assert registry.current is not None
        assert registry.current["payload"]["workflow_revision"] == 0
        assert registry.current["payload"]["_hybrid_orchestration"][
            "workflow_revision"
        ] == 0
        assert registry.current["authoritative_workflow_revision"] == 0
        assert first["artifact_is_authorization"] is False
        assert first["execute_binding_enabled"] is False
    finally:
        store.close()


def test_s3_start_preserves_capture_revision_after_context_persistence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as attestation

    registry = _S3Registry()
    store, _composition, service, _started = _s3_service(
        tmp_path,
        registry,
        benchmark_v2_worker_binding_resolver=object(),
    )
    serialized_window = {
        "contract_version": "test_window_binding_v1",
        "exact_hwnd": 101,
        "process_identity": {"pid": 202, "create_time_ns": 303},
        "job_name": "job-h1",
        "payload_sha256": "c" * 64,
    }
    monkeypatch.setattr(
        "app.learn.hybrid.benchmark_v2_worker_binding.resolve_server_worker_window_binding",
        lambda **_kwargs: {"serialized_window_binding": deepcopy(serialized_window)},
    )
    monkeypatch.setattr(attestation, "PROJECT_ROOT", tmp_path)

    try:
        service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )

        assert registry.current is not None
        assert "_benchmark_v2_dispatch_context" in registry.current["payload"]
        payload = registry.current["payload"]
        assert payload["workflow_revision"] == 0
        assert payload["_hybrid_orchestration"]["workflow_revision"] == 0
        assert registry.current["authoritative_workflow_revision"] == 0
        workflow_state = store.get("run-h1")
        assert workflow_state["revision"] == 5
        assert payload["_benchmark_v2_dispatch_context"]["operation_ref"][
            "revision"
        ] == 4
    finally:
        store.close()


@pytest.mark.parametrize(
    ("capture_bundle", "screen_group_ref"),
    [
        (
            {
                "bundle_id": "capture-bundle",
                "bundle_ref": _identity("capture-bundle"),
                "run_id": "other-run",
                "workflow_revision": 0,
            },
            _identity("capture-bundle"),
        ),
        (
            {
                "bundle_id": "capture-bundle",
                "bundle_ref": _identity("other-bundle", SHA_B),
                "run_id": "run-h1",
                "workflow_revision": 0,
            },
            _identity("capture-bundle"),
        ),
    ],
    ids=("cross-run", "bundle-ref-mismatch"),
)
def test_s3_start_rejects_unbound_capture_lineage_before_registry_start(
    tmp_path: Path,
    capture_bundle: dict[str, object],
    screen_group_ref: dict[str, object],
) -> None:
    from app.learn.workflow_service import LearningWorkflowStageOperationError

    registry = _S3Registry()
    store, _composition, service, _started = _s3_service(tmp_path, registry)
    try:
        with pytest.raises(
            LearningWorkflowStageOperationError,
            match="capture bundle lineage is invalid",
        ):
            service.start_hybrid_operation(
                screen_group=_screen_group(
                    capture_bundle=capture_bundle,
                    hybrid_capture_bundle_ref=screen_group_ref,
                ),
                window_binding=_s3_window_binding(),
            )

        assert registry.start_calls == 0
        assert registry.current is None
    finally:
        store.close()


def test_s3_initial_payload_loads_exact_capture_revision_before_provider_dispatch(
    tmp_path: Path,
) -> None:
    from app.learn import workflow_service
    from app.learn.hybrid.capture import load_and_verify_hybrid_capture_bundle
    from test_learn_hybrid_capture import _bundle

    capture_bundle = _bundle(tmp_path, run_id="run-h1", revision=0)
    registry = _S3Registry()
    store, _composition, service, _started = _s3_service(tmp_path, registry)
    try:
        binding = workflow_service._compose_benchmark_v2_hybrid_service_binding(
            screen_group=_screen_group(
                capture_bundle=capture_bundle,
                capture_image_path="artifacts/screenshots/capture.png",
            ),
            window_binding=_s3_window_binding(),
        )
        assert workflow_service._require_benchmark_v2_hybrid_capture_bundle(
            project_root=tmp_path,
            binding=binding,
        ) == 0
        stale_bundle = deepcopy(capture_bundle)
        stale_bundle["workflow_revision"] = 1
        stale_binding = (
            workflow_service._compose_benchmark_v2_hybrid_service_binding(
                screen_group=_screen_group(
                    capture_bundle=stale_bundle,
                    hybrid_capture_bundle_ref=deepcopy(
                        capture_bundle["bundle_ref"]
                    ),
                    capture_image_path="artifacts/screenshots/capture.png",
                ),
                window_binding=_s3_window_binding(),
            )
        )
        with pytest.raises(
            workflow_service.LearningWorkflowStageOperationError,
            match="stale workflow revision",
        ):
            workflow_service._require_benchmark_v2_hybrid_capture_bundle(
                project_root=tmp_path,
                binding=stale_binding,
            )
        type_confused_bundle = deepcopy(capture_bundle)
        type_confused_bundle["capture_identity"]["image_size"]["height"] = 6.0
        type_confused_binding = (
            workflow_service._compose_benchmark_v2_hybrid_service_binding(
                screen_group=_screen_group(
                    capture_bundle=type_confused_bundle,
                    hybrid_capture_bundle_ref=deepcopy(
                        capture_bundle["bundle_ref"]
                    ),
                    capture_image_path="artifacts/screenshots/capture.png",
                ),
                window_binding=_s3_window_binding(),
            )
        )
        with pytest.raises(
            workflow_service.LearningWorkflowStageOperationError,
            match="expanded capture bundle is stale",
        ):
            workflow_service._require_benchmark_v2_hybrid_capture_bundle(
                project_root=tmp_path,
                binding=type_confused_binding,
            )
        assert registry.start_calls == 0

        service.start_hybrid_operation(
            screen_group=_screen_group(
                capture_bundle=capture_bundle,
                capture_image_path="artifacts/screenshots/capture.png",
            ),
            window_binding=_s3_window_binding(),
        )

        assert registry.current is not None
        payload = registry.current["payload"]
        loaded = load_and_verify_hybrid_capture_bundle(
            project_root=tmp_path,
            bundle_ref=payload["hybrid_capture_bundle_ref"],
            expected_run_id="run-h1",
            expected_workflow_revision=payload["workflow_revision"],
        )
        assert loaded["workflow_revision"] == 0
        assert registry.start_calls == 1
        with pytest.raises(ValueError, match="stale workflow revision"):
            load_and_verify_hybrid_capture_bundle(
                project_root=tmp_path,
                bundle_ref=payload["hybrid_capture_bundle_ref"],
                expected_run_id="run-h1",
                expected_workflow_revision=store.get("run-h1")["revision"],
            )
    finally:
        store.close()


def test_s3_generic_omni_continuation_preserves_capture_revision(
    tmp_path: Path,
) -> None:
    registry = _S3Registry()
    store, _composition, service, _started = _s3_service(tmp_path, registry)
    try:
        step = service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        assert registry.current is not None
        orchestration = deepcopy(
            registry.current["payload"]["_hybrid_orchestration"]
        )
        registry.complete_current(
            {
                "contract_version": "learning_hybrid_managed_stage_result_v1",
                "learning_pipeline_mode": "hybrid_v1_1",
                "task_kind": "panel_learning_hybrid_omni_discovery",
                "outcome": "completed",
                "orchestration": orchestration,
                "result": {
                    "contract_version": "hybrid_omni_discovery_result_v1",
                    "hybrid_capture_bundle_ref": deepcopy(
                        orchestration["hybrid_capture_bundle_ref"]
                    ),
                    "inventory": {"contract_version": "test_inventory_v1"},
                },
            }
        )

        advanced = service.continue_hybrid_operation(
            operation_ref=step["operation_ref"]
        )

        assert advanced["observed_task_kind"] == (
            "panel_learning_hybrid_qwen_binding"
        )
        assert registry.current is not None
        assert registry.current["payload"]["workflow_revision"] == 0
        assert registry.current["payload"]["_hybrid_orchestration"][
            "workflow_revision"
        ] == 0
        assert registry.current["authoritative_workflow_revision"] == 0
        assert store.get("run-h1")["revision"] > 0
    finally:
        store.close()


def test_s3_terminal_review_uses_capture_revision_while_store_cas_advances(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import workflow_service
    from test_learn_hybrid_capture import _bundle

    capture_bundle = _bundle(tmp_path, run_id="run-h1", revision=0)
    screen_group = _screen_group(
        capture_bundle=capture_bundle,
        capture_image_path="artifacts/screenshots/capture.png",
    )
    registry = _S3Registry()
    store, composition, _service, _started = _s3_service(tmp_path, registry)
    monkeypatch.setattr(
        workflow_service,
        "_managed_hybrid_large_review_projection",
        lambda **_kwargs: {"contract_version": "test_large_review_v1"},
    )
    try:
        binding = workflow_service._compose_benchmark_v2_hybrid_service_binding(
            screen_group=screen_group,
            window_binding=_s3_window_binding(),
        )
        current = workflow_service._persist_benchmark_v2_hybrid_service_binding(
            composition=composition,
            workflow_state=store.get("run-h1"),
            stage="screen_understanding",
            binding=binding,
        )
        response = {
            "contract_version": "learning_hybrid_managed_stage_result_v1",
            "learning_pipeline_mode": "hybrid_v1_1",
            "task_kind": "panel_learning_hybrid_review_projection",
            "outcome": "completed",
            "supervisor_lineage": {
                "run_id": "run-h1",
                "workflow_revision": 0,
                "operation_id": "operation-h1",
                "stage": "screen_understanding",
            },
            "orchestration": {
                "run_id": "run-h1",
                "workflow_revision": 0,
                "hybrid_capture_bundle_ref": deepcopy(
                    capture_bundle["bundle_ref"]
                ),
                "capture_bundle": deepcopy(capture_bundle),
                "capture_image_path": "artifacts/screenshots/capture.png",
            },
            "result": {
                "contract_version": "hybrid_review_projection_v1",
                "outcome": "completed",
                "review_status": "REVIEW_REQUIRED",
                "automatic_acceptance": False,
                "hybrid_capture_bundle_ref": deepcopy(
                    capture_bundle["bundle_ref"]
                ),
                "proposals": [
                    {
                        "candidate_id": "candidate/one",
                        "roi_ref": {
                            "capture_lineage_ref": deepcopy(
                                capture_bundle["capture_lineage_ref"]
                            )
                        },
                    }
                ],
                "execute_binding_enabled": False,
                "no_live_click_authorization": True,
            },
        }

        trial_path = workflow_service._persist_managed_hybrid_review_trial(
            project_root=tmp_path,
            run_id="run-h1",
            workflow_revision=0,
            operation_id="operation-h1",
            worker_id="worker-review",
            result_sha256="d" * 64,
            response=deepcopy(response),
            current=current,
        )

        assert current["revision"] > 0
        assert (tmp_path / trial_path).is_file()
        for lineage_owner in ("supervisor_lineage", "orchestration"):
            stale = deepcopy(response)
            stale[lineage_owner]["workflow_revision"] = 1
            with pytest.raises(
                workflow_service.LearningWorkflowStageOperationError,
                match="lineage is stale|orchestration is stale",
            ):
                workflow_service._persist_managed_hybrid_review_trial(
                    project_root=tmp_path,
                    run_id="run-h1",
                    workflow_revision=0,
                    operation_id="operation-h1",
                    worker_id="worker-review",
                    result_sha256="d" * 64,
                    response=stale,
                    current=current,
                )
    finally:
        store.close()


@pytest.mark.parametrize(
    "mutated_field",
    (
        "workflow_revision",
        "workflow_revision_bool",
        "orchestration_revision",
        "orchestration_revision_float",
        "orchestration_run_id",
        "orchestration_bundle_ref",
        "orchestration_capture_bundle_revision_float",
        "top_level_run_id",
        "top_level_bundle_ref",
    ),
)
def test_s3_worker_start_rejects_mutated_capture_revision_before_registry_start(
    tmp_path: Path,
    mutated_field: str,
) -> None:
    from app.learn import workflow_service

    registry = _S3Registry()
    store, composition, _service, _started = _s3_service(tmp_path, registry)
    try:
        binding = workflow_service._compose_benchmark_v2_hybrid_service_binding(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        current = workflow_service._persist_benchmark_v2_hybrid_service_binding(
            composition=composition,
            workflow_state=store.get("run-h1"),
            stage="screen_understanding",
            binding=binding,
        )
        payload = _hybrid_worker_payload()
        if mutated_field == "workflow_revision":
            payload["workflow_revision"] = 1
        elif mutated_field == "workflow_revision_bool":
            payload["workflow_revision"] = False
        elif mutated_field == "orchestration_revision":
            payload["_hybrid_orchestration"]["workflow_revision"] = 1
        elif mutated_field == "orchestration_revision_float":
            payload["_hybrid_orchestration"]["workflow_revision"] = 0.0
        elif mutated_field == "orchestration_run_id":
            payload["_hybrid_orchestration"]["run_id"] = "other-run"
        elif mutated_field == "orchestration_bundle_ref":
            payload["_hybrid_orchestration"]["hybrid_capture_bundle_ref"] = (
                _identity("other-bundle", SHA_B)
            )
        elif mutated_field == "orchestration_capture_bundle_revision_float":
            payload["_hybrid_orchestration"]["capture_bundle"][
                "workflow_revision"
            ] = 0.0
        elif mutated_field == "top_level_run_id":
            payload["run_id"] = "other-run"
        else:
            payload["hybrid_capture_bundle_ref"] = _identity(
                "other-bundle", SHA_B
            )

        with pytest.raises(
            workflow_service.LearningWorkflowStageOperationError,
            match="payload workflow lineage is stale",
        ):
            workflow_service.start_guarded_learning_stage_worker(
                composition=composition,
                run_id="run-h1",
                expected_revision=current["revision"],
                stage="screen_understanding",
                operation_id="operation-h1",
                task_kind="panel_learning_hybrid_omni_discovery",
                payload=payload,
            )

        assert registry.start_calls == 0
    finally:
        store.close()


def test_s3_worker_start_rejects_stale_store_cas_with_valid_capture_revision(
    tmp_path: Path,
) -> None:
    from app.learn import workflow_service

    registry = _S3Registry()
    store, composition, _service, _started = _s3_service(tmp_path, registry)
    try:
        binding = workflow_service._compose_benchmark_v2_hybrid_service_binding(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        current = workflow_service._persist_benchmark_v2_hybrid_service_binding(
            composition=composition,
            workflow_state=store.get("run-h1"),
            stage="screen_understanding",
            binding=binding,
        )
        with pytest.raises(
            workflow_service.LearningWorkflowStageOperationError,
            match="revision conflict",
        ):
            workflow_service.start_guarded_learning_stage_worker(
                composition=composition,
                run_id="run-h1",
                expected_revision=current["revision"] - 1,
                stage="screen_understanding",
                operation_id="operation-h1",
                task_kind="panel_learning_hybrid_omni_discovery",
                payload=_hybrid_worker_payload(),
            )

        assert registry.start_calls == 0
    finally:
        store.close()


def test_u2_lookup_hybrid_operation_is_read_only_none_then_exact_step(
    tmp_path: Path,
) -> None:
    registry = _S3Registry()
    store, _composition, service, _started = _s3_service(tmp_path, registry)
    try:
        assert service.lookup_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        ) is None
        assert registry.start_calls == 0
        assert registry.status_calls == 0
        assert registry.adopt_calls == 0
        assert registry.cancel_calls == 0

        started = service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        counters = (
            registry.start_calls,
            registry.status_calls,
            registry.adopt_calls,
            registry.read_calls,
            registry.cancel_calls,
        )
        looked_up = service.lookup_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )

        assert looked_up == started
        assert (
            registry.start_calls,
            registry.status_calls,
            registry.adopt_calls,
            registry.read_calls,
            registry.cancel_calls,
        ) == counters
    finally:
        store.close()


def test_u2_lookup_rejects_stale_binding_before_attachment_projection(
    tmp_path: Path,
) -> None:
    registry = _S3Registry()
    store, _composition, service, _started = _s3_service(tmp_path, registry)
    try:
        service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        stale_binding = _window_binding(
            run_id="run-h1",
            operation_id="operation-h1",
            window_binding_ref=_identity("stale-window", SHA_B),
        )
        counters = (
            registry.start_calls,
            registry.status_calls,
            registry.adopt_calls,
            registry.read_calls,
            registry.cancel_calls,
        )

        with pytest.raises(ValueError, match="stale"):
            service.lookup_hybrid_operation(
                screen_group=_screen_group(),
                window_binding=stale_binding,
            )

        assert (
            registry.start_calls,
            registry.status_calls,
            registry.adopt_calls,
            registry.read_calls,
            registry.cancel_calls,
        ) == counters
    finally:
        store.close()


def test_u2_lookup_reports_recovery_required_when_binding_lost_attachment(
    tmp_path: Path,
) -> None:
    from app.learn.workflow_service import LearningWorkflowStageOperationError

    registry = _S3Registry()
    store, _composition, service, _started = _s3_service(tmp_path, registry)
    try:
        service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        registry.records.clear()

        with pytest.raises(
            LearningWorkflowStageOperationError,
            match="recovery_required",
        ):
            service.lookup_hybrid_operation(
                screen_group=_screen_group(),
                window_binding=_s3_window_binding(),
            )

        assert registry.start_calls == 1
        assert registry.status_calls == 0
        assert registry.adopt_calls == 0
        assert registry.cancel_calls == 0
    finally:
        store.close()


def test_u2_hybrid_service_owns_fresh_run_initialization_idempotently(
    tmp_path: Path,
) -> None:
    from app.learn.workflow_service import compose_test_learning_workflow_service_unit
    from app.learn.workflow_store import LearningWorkflowRunStore

    capture = tmp_path / "artifacts" / "benchmark" / "screen-group-1.png"
    capture.parent.mkdir(parents=True, exist_ok=True)
    capture.write_bytes(b"production-like-capture")
    store = LearningWorkflowRunStore(state_path=tmp_path / "fresh-workflow-state.json")
    registry = _S3Registry()
    composition = compose_test_learning_workflow_service_unit(
        store=store,
        worker_registry=registry,
        project_root=tmp_path,
    )
    service = incumbent.BenchmarkV2IncumbentWorkflowService(composition)
    try:
        assert service.lookup_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        ) is None

        first = service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        replay = service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        current = store.get("run-h1")

        assert replay == first
        assert current["current_stage"] == "screen_understanding"
        assert current["stages"]["screen_understanding"]["status"] == "running"
        assert current["stages"]["screen_understanding"]["evidence_refs"][
            "stage_execution"
        ]["operation_id"] == "operation-h1"
        assert registry.start_calls == 1
    finally:
        store.close()


def test_s3_continue_advances_exact_existing_order_one_producer_per_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.learn.workflow_service as workflow_service

    registry = _S3Registry()
    store, composition, service, _started = _s3_service(tmp_path, registry)
    task_order = [
        "panel_learning_hybrid_omni_discovery",
        "panel_learning_hybrid_qwen_binding",
        "panel_learning_hybrid_fusion",
        "panel_learning_calibration_sequence",
        "panel_learning_hybrid_review_projection",
    ]
    continuation_calls = 0

    def _continue(**kwargs):
        nonlocal continuation_calls
        continuation_calls += 1
        current = registry.current
        assert current is not None
        index = task_order.index(str(current["task_kind"]))
        state = store.get("run-h1")
        if index + 1 < len(task_order):
            worker = workflow_service.start_guarded_learning_stage_worker(
                composition=composition,
                run_id="run-h1",
                expected_revision=state["revision"],
                stage="screen_understanding",
                operation_id="operation-h1",
                task_kind=task_order[index + 1],
                payload={
                    "learning_pipeline_mode": "hybrid_v1_1",
                    "workflow_revision": current["payload"][
                        "workflow_revision"
                    ],
                    "_hybrid_orchestration": deepcopy(
                        current["payload"]["_hybrid_orchestration"]
                    ),
                    "sequence_index": index + 1,
                },
                reuse_active_identical=True,
            )
            return {
                "stage_finished": False,
                "next_worker": worker,
                "workflow_state": state,
            }
        evidence_path = tmp_path / "artifacts" / "hybrid-review.json"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text("{}", encoding="utf-8")
        finished = workflow_service.finish_learning_workflow_stage_operation(
            store=store,
            project_root=tmp_path,
            run_id="run-h1",
            expected_revision=state["revision"],
            stage="screen_understanding",
            operation_id="operation-h1",
            outcome="completed",
            reason="hybrid review completed",
            evidence_refs={"trial_path": "artifacts/hybrid-review.json"},
        )
        return {
            "stage_finished": True,
            "outcome": "completed",
            "next_stage_operation": None,
            "next_stage_worker": None,
            "workflow_state": finished["workflow_state"],
        }

    monkeypatch.setattr(
        workflow_service,
        "continue_guarded_learning_stage_worker_result",
        _continue,
    )
    try:
        step = service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        observed = [step["observed_task_kind"]]
        terminal_consumed_ref = None
        for task_kind in task_order:
            assert step["observed_task_kind"] == task_kind
            registry.complete_current(
                {"success": True, "completed_task_kind": task_kind}
            )
            terminal_consumed_ref = deepcopy(step["operation_ref"])
            step = service.continue_hybrid_operation(
                operation_ref=terminal_consumed_ref
            )
            if step["status"] != "complete":
                observed.append(step["observed_task_kind"])
                replay = service.continue_hybrid_operation(
                    operation_ref=step["operation_ref"]
                )
                assert replay == step

        terminal_replay = service.continue_hybrid_operation(
            operation_ref=step["operation_ref"]
        )
        assert terminal_replay == step
        assert terminal_consumed_ref is not None
        lost_terminal_response_replay = service.continue_hybrid_operation(
            operation_ref=terminal_consumed_ref
        )
        assert canonical_json_bytes(lost_terminal_response_replay) == (
            canonical_json_bytes(step)
        )
        assert step["operation_ref"]["predecessor_content_sha256"] == (
            terminal_consumed_ref["content_sha256"]
        )
        assert observed == task_order
        assert continuation_calls == len(task_order)
        assert registry.start_calls == len(task_order)
        assert registry.adopt_calls == len(task_order)
        assert step["status"] == "complete"
        assert step["adopted_result_projection"]["response"] == {
            "success": True,
            "completed_task_kind": task_order[-1],
        }
    finally:
        store.close()


def test_s3_lost_response_retry_replays_consumed_ref_without_second_producer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.learn.workflow_service as workflow_service

    registry = _S3Registry()
    store, composition, service, _started = _s3_service(tmp_path, registry)
    continuation_calls = 0

    def _continue(**_kwargs):
        nonlocal continuation_calls
        continuation_calls += 1
        state = store.get("run-h1")
        current = registry.current
        assert current is not None
        worker = workflow_service.start_guarded_learning_stage_worker(
            composition=composition,
            run_id="run-h1",
            expected_revision=state["revision"],
            stage="screen_understanding",
            operation_id="operation-h1",
            task_kind="panel_learning_hybrid_qwen_binding",
            payload={
                "learning_pipeline_mode": "hybrid_v1_1",
                "workflow_revision": current["payload"]["workflow_revision"],
                "_hybrid_orchestration": deepcopy(
                    current["payload"]["_hybrid_orchestration"]
                ),
                "sequence_index": 1,
            },
            reuse_active_identical=True,
        )
        return {
            "stage_finished": False,
            "next_worker": worker,
            "workflow_state": state,
        }

    monkeypatch.setattr(
        workflow_service,
        "continue_guarded_learning_stage_worker_result",
        _continue,
    )
    try:
        initial = service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        consumed_ref = deepcopy(initial["operation_ref"])
        registry.complete_current({"success": True, "stage": "omni"})

        returned = service.continue_hybrid_operation(operation_ref=consumed_ref)
        retried = service.continue_hybrid_operation(operation_ref=consumed_ref)

        assert canonical_json_bytes(retried) == canonical_json_bytes(returned)
        assert returned["operation_ref"]["predecessor_content_sha256"] == (
            consumed_ref["content_sha256"]
        )
        assert continuation_calls == 1
        assert registry.adopt_calls == 1
        assert registry.start_calls == 2
    finally:
        store.close()


def test_s3_expired_pending_vista_recovery_projects_verified_cleanup_without_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.learn.workflow_service as workflow_service
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as attestation

    monkeypatch.setattr(attestation, "PROJECT_ROOT", tmp_path.resolve())
    registry = _S3Registry()
    store, composition, service, _started = _s3_service(tmp_path, registry)

    def _continue(**kwargs):
        state = store.get("run-h1")
        current = registry.current
        assert current is not None
        binding = _s3_window_binding()
        operation_ref = {
            "run_id": "run-h1",
            "stage": "screen_understanding",
            "operation_id": "operation-h1",
            "revision": int(state["revision"]),
            "window_binding_ref": deepcopy(binding["window_binding_ref"]),
            "capture_ref": deepcopy(binding["capture_ref"]),
        }
        context = attestation.compose_benchmark_dispatch_context(
            provider="vista",
            operation_ref=operation_ref,
            window_binding={
                "contract_version": "test_window_binding_v1",
                "exact_hwnd": 101,
                "process_identity": {"pid": 202, "create_time_ns": 303},
                "job_name": "job-h1",
                "payload_sha256": "c" * 64,
            },
            receipt_journal_path=attestation._fixed_dispatch_journal_path(
                operation_ref
            ),
        )
        sink = kwargs.get("_benchmark_dispatch_context_sink")
        assert callable(sink)
        sink(context)
        worker = workflow_service.start_guarded_learning_stage_worker(
            composition=composition,
            run_id="run-h1",
            expected_revision=int(state["revision"]),
            stage="screen_understanding",
            operation_id="operation-h1",
            task_kind="panel_learning_calibration_sequence",
            payload={
                "learning_pipeline_mode": "hybrid_v1_1",
                "workflow_revision": current["payload"]["workflow_revision"],
                "_hybrid_orchestration": deepcopy(
                    current["payload"]["_hybrid_orchestration"]
                ),
                "sequence_index": 3,
                "_benchmark_v2_dispatch_context": deepcopy(context),
            },
            reuse_active_identical=True,
        )
        return {
            "stage_finished": False,
            "next_worker": worker,
            "workflow_state": state,
        }

    monkeypatch.setattr(
        workflow_service,
        "continue_guarded_learning_stage_worker_result",
        _continue,
    )
    try:
        initial = service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        consumed_ref = deepcopy(initial["operation_ref"])
        registry.complete_current({"success": True, "stage": "omni"})

        returned = service.continue_hybrid_operation(
            operation_ref=consumed_ref
        )
        assert returned["status"] == "pending"
        assert returned["observed_task_kind"] == (
            "panel_learning_calibration_sequence"
        )
        worker = registry.current
        assert worker is not None
        cleanup_receipt, provider_lineage = (
            _s3_vista_supervisor_cleanup_receipt(worker)
        )
        worker.update(
            {
                "status": "failed",
                "runtime_attached": False,
                "result_available": False,
                "result_adopted": False,
                "provider": "vista",
                "provider_lineage": provider_lineage,
                "provider_scope_name": cleanup_receipt[
                    "provider_lease_identity"
                ]["process_scope_name"],
                "workflow_revision": 0,
                "pid": None,
                "recovered_from_journal": True,
                "supervisor_reconciliation": {
                    "contract_version": "hybrid_supervisor_reconciliation_v1",
                    "status": "verified",
                    "cleanup_receipt": cleanup_receipt,
                },
            }
        )
        registry.active_resources = 0
        state = store.get("run-h1")
        execution = state["stages"]["screen_understanding"]["evidence_refs"][
            "stage_execution"
        ]
        recovered = workflow_service.recover_guarded_learning_workflow_stage_operation(
            composition=composition,
            run_id="run-h1",
            expected_revision=int(state["revision"]),
            now=datetime.fromisoformat(execution["lease_expires_at"])
            + timedelta(seconds=1),
        )
        assert recovered["recovery_status"] == "expired_operation_failed"

        projected = service.lookup_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        assert projected is not None
        assert projected["status"] == "safe_stopped"
        assert projected["observed_task_kind"] == (
            "panel_learning_calibration_sequence"
        )
        assert projected["operation_ref"]["predecessor_content_sha256"] == (
            consumed_ref["content_sha256"]
        )
        worker_ref = projected["operation_ref"]["worker_ref"]
        worker_cleanup = projected["cleanup_refs"]["worker_cleanup_ref"]
        provider_cleanup = projected["cleanup_refs"]["provider_cleanup_ref"]
        assert worker_cleanup["backend_compute_termination"] == "not_running"
        assert worker_cleanup["model_service_compute_termination"] == "terminated"
        assert worker_cleanup["cancellation_ref"] == {
            "content_sha256": cleanup_receipt["content_sha256"]
        }
        recovered_execution = store.get("run-h1")["stages"][
            "screen_understanding"
        ]["evidence_refs"]["stage_execution"]
        vista_context = recovered_execution["benchmark_v2_workflow_service_hybrid"][
            "provider_dispatch_context_refs"
        ]["vista"]["dispatch_context"]
        assert provider_cleanup["reservation_ref"] == {
            "content_sha256": vista_context["content_sha256"]
        }
        assert provider_cleanup["acquisition_intent_ref"] == (
            provider_cleanup["reservation_ref"]
        )
        acquisition = cleanup_receipt["source_cleanup_evidence"]["model_lease"][
            "process_scope_acquisition"
        ]
        assert provider_cleanup["acquisition_owner_ref"] == {
            "content_sha256": content_sha256(acquisition)
        }
        assert provider_cleanup["cleanup_receipt_ref"] == {
            "content_sha256": cleanup_receipt["content_sha256"]
        }
        for cleanup_name in ("worker_cleanup_ref", "provider_cleanup_ref"):
            cleanup_ref = projected["cleanup_refs"][cleanup_name]
            assert isinstance(cleanup_ref, dict)
            for name in (
                "run_id",
                "stage",
                "operation_id",
                "worker_id",
                "model_request_id",
                "payload_sha256",
            ):
                assert cleanup_ref[name] == worker_ref[name]

        replay = service.lookup_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        cancelled = service.cancel_operation(
            operation_ref=projected["operation_ref"]
        )
        assert canonical_json_bytes(replay) == canonical_json_bytes(projected)
        assert canonical_json_bytes(cancelled) == canonical_json_bytes(projected)
        assert registry.start_calls == 2
        assert registry.adopt_calls == 1
        assert registry.cancel_calls == 0
        assert registry.active_resources == 0
    finally:
        store.close()


@pytest.mark.parametrize(
    "violation",
    (
        "worker_not_recovered",
        "reconciliation_not_verified",
        "receipt_lineage",
        "receipt_residue",
        "lease_identity",
        "record_scope_name",
        "lease_scope_name",
        "receipt_scope_name",
        "acquisition_scope_name",
        "profile_id",
        "member_pids_missing_provider_pid",
        "worker_workflow_revision",
        "binding_workflow_revision",
        "provider_lineage_workflow_revision",
    ),
)
def test_s3_expired_vista_cleanup_projection_rejects_tampered_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    violation: str,
) -> None:
    import app.learn.workflow_service as workflow_service
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as attestation

    monkeypatch.setattr(attestation, "PROJECT_ROOT", tmp_path.resolve())
    registry = _S3Registry()
    worker = registry.start(
        run_id="run-h1",
        stage="screen_understanding",
        operation_id="operation-h1",
        task_kind="panel_learning_calibration_sequence",
        payload=_hybrid_worker_payload(),
    )
    cleanup_receipt, provider_lineage = _s3_vista_supervisor_cleanup_receipt(
        worker
    )
    worker.update(
        {
            "status": "failed",
            "runtime_attached": False,
            "result_available": False,
            "result_adopted": False,
            "provider": "vista",
            "provider_lineage": provider_lineage,
            "provider_scope_name": cleanup_receipt[
                "provider_lease_identity"
            ]["process_scope_name"],
            "workflow_revision": 0,
            "pid": None,
            "recovered_from_journal": True,
            "supervisor_reconciliation": {
                "contract_version": "hybrid_supervisor_reconciliation_v1",
                "status": "verified",
                "cleanup_receipt": cleanup_receipt,
            },
        }
    )
    context = attestation.compose_benchmark_dispatch_context(
        provider="vista",
        operation_ref={
            "run_id": "run-h1",
            "stage": "screen_understanding",
            "operation_id": "operation-h1",
            "revision": 4,
            "window_binding_ref": deepcopy(
                _s3_window_binding()["window_binding_ref"]
            ),
            "capture_ref": deepcopy(_s3_window_binding()["capture_ref"]),
        },
        window_binding={
            "contract_version": "test_window_binding_v1",
            "exact_hwnd": 101,
            "process_identity": {"pid": 202, "create_time_ns": 303},
            "job_name": "job-h1",
            "payload_sha256": "c" * 64,
        },
        receipt_journal_path=attestation._fixed_dispatch_journal_path(
            {
                "run_id": "run-h1",
                "stage": "screen_understanding",
                "operation_id": "operation-h1",
                "revision": 4,
                "window_binding_ref": deepcopy(
                    _s3_window_binding()["window_binding_ref"]
                ),
                "capture_ref": deepcopy(_s3_window_binding()["capture_ref"]),
            }
        ),
    )
    screen_group = _screen_group()
    if violation == "binding_workflow_revision":
        capture_bundle = deepcopy(screen_group["capture_bundle"])
        capture_bundle["workflow_revision"] = 1
        screen_group = _screen_group(capture_bundle=capture_bundle)
    binding = workflow_service._benchmark_v2_hybrid_binding_with_dispatch_context(
        binding=workflow_service._compose_benchmark_v2_hybrid_service_binding(
            screen_group=screen_group,
            window_binding=_s3_window_binding(),
        ),
        context=context,
    )
    if violation == "worker_not_recovered":
        worker["recovered_from_journal"] = False
    elif violation == "reconciliation_not_verified":
        worker["supervisor_reconciliation"]["status"] = "indeterminate"
    elif violation == "record_scope_name":
        worker["provider_scope_name"] = (
            f"Local\\AgentGuiHybrid-vista-{'e' * 64}"
        )
    elif violation == "worker_workflow_revision":
        worker["workflow_revision"] = 1
    else:
        tampered = deepcopy(cleanup_receipt)
        tampered.pop("content_sha256")
        if violation == "receipt_lineage":
            tampered["lineage"]["operation_id"] = "operation-other"
        elif violation == "receipt_residue":
            tampered["orphan_provider_pids"] = [404]
        elif violation == "lease_scope_name":
            tampered["source_cleanup_evidence"]["model_lease"][
                "process_scope_name"
            ] = f"Local\\AgentGuiHybrid-vista-{'e' * 64}"
        elif violation == "receipt_scope_name":
            tampered["provider_lease_identity"]["process_scope_name"] = (
                f"Local\\AgentGuiHybrid-vista-{'e' * 64}"
            )
        elif violation == "acquisition_scope_name":
            tampered["source_cleanup_evidence"]["model_lease"][
                "process_scope_acquisition"
            ]["scope_name"] = f"Local\\AgentGuiHybrid-vista-{'e' * 64}"
        elif violation == "profile_id":
            tampered["source_cleanup_evidence"]["model_lease"]["profile"][
                "profile_id"
            ] = "vista_other"
        elif violation == "member_pids_missing_provider_pid":
            tampered["source_cleanup_evidence"]["model_lease"][
                "process_scope_acquisition"
            ]["member_pids"] = [999]
        elif violation == "provider_lineage_workflow_revision":
            tampered["lineage"]["workflow_revision"] = 1
            worker["provider_lineage"] = deepcopy(tampered["lineage"])
        else:
            tampered["source_cleanup_evidence"]["model_lease"][
                "incarnation_id"
            ] = "vista-incarnation-other"
        worker["supervisor_reconciliation"]["cleanup_receipt"] = (
            seal_immutable(tampered)
        )

    with pytest.raises(workflow_service.LearningWorkflowStageOperationError):
        workflow_service._project_benchmark_v2_hybrid_expired_failure_cleanup(
            workflow_state={
                "stages": {"screen_understanding": {"status": "failed"}}
            },
            stage_execution={
                "result_outcome": "failed",
                "recovery_status": "expired_operation_failed",
            },
            binding=binding,
            worker_record=worker,
        )


@pytest.mark.parametrize(
    ("remaining_seconds", "expected_heartbeats"),
    ((301, 0), (300, 1)),
)
def test_s3_pending_hybrid_renews_only_inside_window_after_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    remaining_seconds: int,
    expected_heartbeats: int,
) -> None:
    import app.learn.workflow_service as workflow_service

    registry = _S3Registry()
    store, _composition, service, _started = _s3_service(tmp_path, registry)
    heartbeat_calls = 0
    real_heartbeat = (
        workflow_service.heartbeat_guarded_learning_workflow_stage_operation
    )

    def _heartbeat(**kwargs):
        nonlocal heartbeat_calls
        heartbeat_calls += 1
        return real_heartbeat(**kwargs)

    monkeypatch.setattr(
        workflow_service,
        "heartbeat_guarded_learning_workflow_stage_operation",
        _heartbeat,
    )
    try:
        initial = service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        execution = store.get("run-h1")["stages"]["screen_understanding"][
            "evidence_refs"
        ]["stage_execution"]
        original_expiry = datetime.fromisoformat(execution["lease_expires_at"])
        checked_at = original_expiry - timedelta(seconds=remaining_seconds)
        real_utc_datetime = workflow_service._utc_datetime
        monkeypatch.setattr(
            workflow_service,
            "_utc_datetime",
            lambda value: (
                checked_at if value is None else real_utc_datetime(value)
            ),
        )

        returned = service.continue_hybrid_operation(
            operation_ref=initial["operation_ref"]
        )
        current = store.get("run-h1")
        renewed_execution = current["stages"]["screen_understanding"][
            "evidence_refs"
        ]["stage_execution"]

        assert returned["status"] == "pending"
        assert heartbeat_calls == expected_heartbeats
        if expected_heartbeats == 0:
            assert returned["operation_ref"] == initial["operation_ref"]
            assert "heartbeat_count" not in renewed_execution
            assert (
                renewed_execution["lease_expires_at"]
                == execution["lease_expires_at"]
            )
            return

        receipt = renewed_execution["benchmark_v2_workflow_service_hybrid"][
            "continuation_receipt"
        ]
        assert receipt["receipt_phase"] == "returned"
        assert receipt["returned_status"] == "pending"
        assert receipt["consumed_operation_ref_sha256"] == initial[
            "operation_ref"
        ]["content_sha256"]
        assert renewed_execution["heartbeat_count"] == 1
        assert datetime.fromisoformat(
            renewed_execution["lease_expires_at"]
        ) == checked_at + timedelta(seconds=600)
        assert returned["operation_ref"]["predecessor_content_sha256"] == initial[
            "operation_ref"
        ]["content_sha256"]
        replay = service.continue_hybrid_operation(
            operation_ref=initial["operation_ref"]
        )
        assert canonical_json_bytes(replay) == canonical_json_bytes(returned)
        assert heartbeat_calls == 1
        assert registry.start_calls == 1
        assert registry.adopt_calls == 0
    finally:
        store.close()


def test_s3_pending_hybrid_replays_receipt_when_heartbeat_response_is_lost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.learn.workflow_service as workflow_service

    registry = _S3Registry()
    store, _composition, service, _started = _s3_service(tmp_path, registry)
    heartbeat_calls = 0
    real_heartbeat = (
        workflow_service.heartbeat_guarded_learning_workflow_stage_operation
    )
    try:
        initial = service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        execution = store.get("run-h1")["stages"]["screen_understanding"][
            "evidence_refs"
        ]["stage_execution"]
        original_expiry = datetime.fromisoformat(execution["lease_expires_at"])
        checked_at = original_expiry - timedelta(seconds=300)
        real_utc_datetime = workflow_service._utc_datetime
        monkeypatch.setattr(
            workflow_service,
            "_utc_datetime",
            lambda value: (
                checked_at if value is None else real_utc_datetime(value)
            ),
        )
        expected_consumed_refs = [
            initial["operation_ref"]["content_sha256"]
        ]

        def _flaky_heartbeat(**kwargs):
            nonlocal heartbeat_calls
            heartbeat_calls += 1
            current_execution = store.get("run-h1")["stages"][
                "screen_understanding"
            ]["evidence_refs"]["stage_execution"]
            receipt = current_execution[
                "benchmark_v2_workflow_service_hybrid"
            ]["continuation_receipt"]
            assert receipt["consumed_operation_ref_sha256"] == (
                expected_consumed_refs[-1]
            )
            if heartbeat_calls == 1:
                raise RuntimeError("lost heartbeat response after receipt")
            return real_heartbeat(**kwargs)

        monkeypatch.setattr(
            workflow_service,
            "heartbeat_guarded_learning_workflow_stage_operation",
            _flaky_heartbeat,
        )

        with pytest.raises(
            RuntimeError, match="lost heartbeat response after receipt"
        ):
            service.continue_hybrid_operation(
                operation_ref=initial["operation_ref"]
            )

        after_failure = store.get("run-h1")["stages"]["screen_understanding"][
            "evidence_refs"
        ]["stage_execution"]
        assert "heartbeat_count" not in after_failure
        replay = service.continue_hybrid_operation(
            operation_ref=initial["operation_ref"]
        )
        assert replay["status"] == "pending"
        assert heartbeat_calls == 1
        expected_consumed_refs.append(
            replay["operation_ref"]["content_sha256"]
        )

        renewed = service.continue_hybrid_operation(
            operation_ref=replay["operation_ref"]
        )
        renewed_execution = store.get("run-h1")["stages"][
            "screen_understanding"
        ]["evidence_refs"]["stage_execution"]
        assert renewed["status"] == "pending"
        assert heartbeat_calls == 2
        assert renewed_execution["heartbeat_count"] == 1
        assert renewed["operation_ref"]["predecessor_content_sha256"] == replay[
            "operation_ref"
        ]["content_sha256"]
        assert registry.start_calls == 1
        assert registry.adopt_calls == 0
    finally:
        store.close()


def test_s3_early_failure_persists_predecessor_before_terminal_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.learn.workflow_service as workflow_service

    registry = _S3Registry()
    store, _composition, service, _started = _s3_service(tmp_path, registry)
    continuation_calls = 0

    def _continue(**_kwargs):
        nonlocal continuation_calls
        continuation_calls += 1
        if continuation_calls == 1:
            raise RuntimeError("transient early failure continuation")
        state = store.get("run-h1")
        finished = workflow_service.finish_learning_workflow_stage_operation(
            store=store,
            project_root=tmp_path,
            run_id="run-h1",
            expected_revision=state["revision"],
            stage="screen_understanding",
            operation_id="operation-h1",
            outcome="safe_stopped",
            reason="hybrid Omni worker failed",
        )
        return {
            "stage_finished": True,
            "outcome": "safe_stopped",
            "next_stage_operation": None,
            "next_stage_worker": None,
            "workflow_state": finished["workflow_state"],
        }

    monkeypatch.setattr(
        workflow_service,
        "continue_guarded_learning_stage_worker_result",
        _continue,
    )
    try:
        initial = service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        consumed_ref = deepcopy(initial["operation_ref"])
        registry.complete_current(
            {
                "contract_version": "learning_hybrid_managed_stage_result_v1",
                "learning_pipeline_mode": "hybrid_v1_1",
                "task_kind": "panel_learning_hybrid_omni_discovery",
                "outcome": "failed",
                "orchestration": {},
                "result": {"failure_reason": "provider failed"},
            }
        )

        with pytest.raises(
            RuntimeError, match="transient early failure continuation"
        ):
            service.continue_hybrid_operation(operation_ref=consumed_ref)

        prepared_state = store.get("run-h1")
        prepared_receipt = prepared_state["stages"]["screen_understanding"][
            "evidence_refs"
        ]["stage_execution"]["benchmark_v2_workflow_service_hybrid"][
            "continuation_receipt"
        ]
        assert prepared_receipt["receipt_phase"] == "terminal_prepared"
        assert prepared_receipt["consumed_operation_ref_sha256"] == consumed_ref[
            "content_sha256"
        ]

        returned = service.continue_hybrid_operation(operation_ref=consumed_ref)
        replay = service.continue_hybrid_operation(operation_ref=consumed_ref)
        reconciled = service.cancel_operation(
            operation_ref=returned["operation_ref"]
        )

        assert returned["status"] == "safe_stopped"
        assert returned["operation_ref"]["predecessor_content_sha256"] == (
            consumed_ref["content_sha256"]
        )
        assert canonical_json_bytes(replay) == canonical_json_bytes(returned)
        assert canonical_json_bytes(reconciled) == canonical_json_bytes(returned)
        assert store.get("run-h1")["terminal"] is True
        assert registry.active_resources == 0
        assert continuation_calls == 2
        assert registry.adopt_calls == 1
    finally:
        store.close()


def _s3_start_fusion_with_pending_receipt(
    *,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    import app.learn.workflow_service as workflow_service

    registry = _S3Registry()
    store, composition, service, _started = _s3_service(tmp_path, registry)
    monkeypatch.setattr(
        workflow_service,
        "build_learning_pipeline_initial_worker_request",
        lambda **_kwargs: {
            "task_kind": "panel_learning_hybrid_fusion",
            "payload": _hybrid_worker_payload(),
        },
    )
    initial = service.start_hybrid_operation(
        screen_group=_screen_group(),
        window_binding=_s3_window_binding(),
    )
    worker = registry.current
    assert worker is not None
    current = store.get("run-h1")
    stage_execution = current["stages"]["screen_understanding"]["evidence_refs"][
        "stage_execution"
    ]
    binding = stage_execution["benchmark_v2_workflow_service_hybrid"]
    current = workflow_service._persist_benchmark_v2_hybrid_continuation_receipt(
        composition=composition,
        workflow_state=current,
        stage="screen_understanding",
        binding=binding,
        consumed_operation_ref=initial["operation_ref"],
        worker_record=worker,
        returned_status="pending",
    )
    stage_execution = current["stages"]["screen_understanding"]["evidence_refs"][
        "stage_execution"
    ]
    binding = stage_execution["benchmark_v2_workflow_service_hybrid"]
    pending = workflow_service._project_benchmark_v2_hybrid_step(
        composition=composition,
        workflow_state=current,
        stage_execution=stage_execution,
        binding=binding,
        worker_record=worker,
        status="pending",
    )
    return store, composition, service, registry, pending


def _s3_fusion_safe_stop_response(worker: dict[str, object]) -> dict[str, object]:
    return {
        "contract_version": "learning_hybrid_managed_stage_result_v1",
        "learning_pipeline_mode": "hybrid_v1_1",
        "task_kind": "panel_learning_hybrid_fusion",
        "outcome": "completed",
        "orchestration": deepcopy(worker["payload"]["_hybrid_orchestration"]),
        "result": {
            "contract_version": "hybrid_fusion_result_v1",
            "candidates": [],
        },
    }


@pytest.mark.parametrize(
    ("continuation_sha_kind", "projects_result"),
    (("exact", True), ("wrong", False)),
)
def test_s3_fusion_terminal_safe_stop_prepares_terminal_receipt_before_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    continuation_sha_kind: str,
    projects_result: bool,
) -> None:
    import app.learn.workflow_service as workflow_service

    store, _composition, service, registry, pending = (
        _s3_start_fusion_with_pending_receipt(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
        )
    )

    def _continue(**_kwargs):
        current_worker = registry.current
        assert current_worker is not None
        adoption_receipt = current_worker.get("adoption_receipt")
        assert isinstance(adoption_receipt, dict)
        result_sha256 = str(adoption_receipt["result_sha256"])
        if continuation_sha_kind == "wrong":
            result_sha256 = SHA_B
        state = store.get("run-h1")
        finished = workflow_service.finish_learning_workflow_stage_operation(
            store=store,
            project_root=tmp_path,
            run_id="run-h1",
            expected_revision=state["revision"],
            stage="screen_understanding",
            operation_id="operation-h1",
            outcome="safe_stopped",
            reason="Hybrid fusion produced no VISTA-eligible BOUND candidates",
            evidence_refs={
                "worker_continuation": {
                    "contract_version": "learning_stage_worker_continuation_v1",
                    "worker_id": current_worker["worker_id"],
                    "operation_id": "operation-h1",
                    "task_kind": "panel_learning_hybrid_fusion",
                    "result_sha256": result_sha256,
                }
            },
        )
        return {
            "stage_finished": True,
            "outcome": "safe_stopped",
            "next_stage_operation": None,
            "next_stage_worker": None,
            "workflow_state": finished["workflow_state"],
        }

    monkeypatch.setattr(
        workflow_service,
        "continue_guarded_learning_stage_worker_result",
        _continue,
    )
    try:
        worker = registry.current
        assert worker is not None
        registry.complete_current(_s3_fusion_safe_stop_response(worker))
        consumed_ref = deepcopy(pending["operation_ref"])

        returned = service.continue_hybrid_operation(operation_ref=consumed_ref)
        replay = service.continue_hybrid_operation(operation_ref=consumed_ref)
        terminal_state = store.get("run-h1")
        receipt = terminal_state["stages"]["screen_understanding"][
            "evidence_refs"
        ]["stage_execution"]["benchmark_v2_workflow_service_hybrid"][
            "continuation_receipt"
        ]

        assert returned["status"] == "safe_stopped"
        if projects_result:
            projection = returned["adopted_result_projection"]
            assert projection["response"] == _s3_fusion_safe_stop_response(worker)
            assert projection["artifact_is_authorization"] is False
            assert projection["execute_binding_enabled"] is False
        else:
            assert returned["adopted_result_projection"] is None
        assert receipt["receipt_phase"] == "terminal_prepared"
        assert receipt["returned_status"] is None
        assert receipt["consumed_operation_ref_sha256"] == consumed_ref[
            "content_sha256"
        ]
        assert returned["operation_ref"]["predecessor_content_sha256"] == (
            consumed_ref["content_sha256"]
        )
        assert canonical_json_bytes(replay) == canonical_json_bytes(returned)
        assert registry.cancel_calls == 0
        assert registry.materialize_cleanup_calls == 0
    finally:
        store.close()


@pytest.mark.parametrize(
    "violation",
    (
        "wrong_task_kind",
        "not_adopted",
        "wrong_result_outcome",
        "vista_eligible_bound",
        "missing_worker_continuation",
        "extra_worker_continuation_field",
        "wrong_continuation_worker",
        "wrong_continuation_operation",
        "wrong_continuation_task",
        "wrong_continuation_result_sha",
    ),
)
def test_s3_legacy_fusion_pending_receipt_compatibility_is_narrow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    violation: str,
) -> None:
    import app.learn.workflow_service as workflow_service

    store, composition, _service, registry, _pending = (
        _s3_start_fusion_with_pending_receipt(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
        )
    )
    try:
        worker = registry.current
        assert worker is not None
        response = _s3_fusion_safe_stop_response(worker)
        if violation == "vista_eligible_bound":
            response["result"]["candidates"] = [
                {"state": "BOUND", "vista_eligible": True}
            ]
        registry.complete_current(response)
        adoption = None
        if violation != "not_adopted":
            adoption = registry.adopt_result(
                worker_id=worker["worker_id"],
                run_id="run-h1",
                stage="screen_understanding",
                operation_id="operation-h1",
            )
        if violation == "wrong_task_kind":
            assert registry.current is not None
            registry.current["task_kind"] = "panel_learning_hybrid_qwen_binding"
        continuation = {
            "contract_version": "learning_stage_worker_continuation_v1",
            "worker_id": worker["worker_id"],
            "operation_id": "operation-h1",
            "task_kind": "panel_learning_hybrid_fusion",
            "result_sha256": (
                adoption["receipt"]["result_sha256"]
                if isinstance(adoption, dict)
                else SHA_A
            ),
        }
        if violation == "extra_worker_continuation_field":
            continuation["unexpected"] = True
        elif violation == "wrong_continuation_worker":
            continuation["worker_id"] = "worker-from-another-run"
        elif violation == "wrong_continuation_operation":
            continuation["operation_id"] = "operation-from-another-run"
        elif violation == "wrong_continuation_task":
            continuation["task_kind"] = "panel_learning_hybrid_qwen_binding"
        elif violation == "wrong_continuation_result_sha":
            continuation["result_sha256"] = SHA_B
        state = store.get("run-h1")
        workflow_service.finish_learning_workflow_stage_operation(
            store=store,
            project_root=tmp_path,
            run_id="run-h1",
            expected_revision=state["revision"],
            stage="screen_understanding",
            operation_id="operation-h1",
            outcome=(
                "failed" if violation == "wrong_result_outcome" else "safe_stopped"
            ),
            reason="terminal compatibility negative control",
            evidence_refs=(
                {}
                if violation == "missing_worker_continuation"
                else {"worker_continuation": continuation}
            ),
        )
        current = store.get("run-h1")
        stage_execution = current["stages"]["screen_understanding"][
            "evidence_refs"
        ]["stage_execution"]
        binding = stage_execution["benchmark_v2_workflow_service_hybrid"]
        attached = registry.current
        assert attached is not None

        assert (
            workflow_service._benchmark_v2_hybrid_legacy_fusion_safe_stop_verified(
                composition=composition,
                workflow_state=current,
                stage_execution=stage_execution,
                binding=binding,
                worker_record=attached,
            )
            is False
        )
    finally:
        store.close()


def test_s3_lookup_legacy_fusion_pending_receipt_projects_safe_stop_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.learn.workflow_service as workflow_service

    store, _composition, service, registry, pending = (
        _s3_start_fusion_with_pending_receipt(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
        )
    )
    try:
        worker = registry.current
        assert worker is not None
        registry.complete_current(_s3_fusion_safe_stop_response(worker))
        adoption = registry.adopt_result(
            worker_id=worker["worker_id"],
            run_id="run-h1",
            stage="screen_understanding",
            operation_id="operation-h1",
        )
        state = store.get("run-h1")
        workflow_service.finish_learning_workflow_stage_operation(
            store=store,
            project_root=tmp_path,
            run_id="run-h1",
            expected_revision=state["revision"],
            stage="screen_understanding",
            operation_id="operation-h1",
            outcome="safe_stopped",
            reason="Hybrid fusion produced no VISTA-eligible BOUND candidates",
            evidence_refs={
                "worker_continuation": {
                    "contract_version": "learning_stage_worker_continuation_v1",
                    "worker_id": worker["worker_id"],
                    "operation_id": "operation-h1",
                    "task_kind": "panel_learning_hybrid_fusion",
                    "result_sha256": adoption["receipt"]["result_sha256"],
                }
            },
        )
        state_before = store.get("run-h1")
        state_bytes = canonical_json_bytes(state_before)

        projected = service.lookup_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )

        assert projected["status"] == "safe_stopped"
        projection = projected["adopted_result_projection"]
        assert projection["response"] == _s3_fusion_safe_stop_response(worker)
        assert projection["artifact_is_authorization"] is False
        assert projection["execute_binding_enabled"] is False
        assert projected["operation_ref"]["predecessor_content_sha256"] == pending[
            "operation_ref"
        ]["predecessor_content_sha256"]
        assert canonical_json_bytes(store.get("run-h1")) == state_bytes
        assert registry.start_calls == 1
        assert registry.adopt_calls == 1
        assert registry.cancel_calls == 0
        assert registry.materialize_cleanup_calls == 0
    finally:
        store.close()


def test_s3_legacy_fusion_safe_stop_cleanup_bridge_is_explicit_and_replay_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.learn.workflow_service as workflow_service

    store, _composition, service, registry, pending = (
        _s3_start_fusion_with_pending_receipt(
            tmp_path=tmp_path,
            monkeypatch=monkeypatch,
        )
    )
    try:
        worker = registry.current
        assert worker is not None
        registry.complete_current(_s3_fusion_safe_stop_response(worker))
        adoption = registry.adopt_result(
            worker_id=worker["worker_id"],
            run_id="run-h1",
            stage="screen_understanding",
            operation_id="operation-h1",
        )
        state = store.get("run-h1")
        workflow_service.finish_learning_workflow_stage_operation(
            store=store,
            project_root=tmp_path,
            run_id="run-h1",
            expected_revision=state["revision"],
            stage="screen_understanding",
            operation_id="operation-h1",
            outcome="safe_stopped",
            reason="Hybrid fusion produced no VISTA-eligible BOUND candidates",
            evidence_refs={
                "worker_continuation": {
                    "contract_version": "learning_stage_worker_continuation_v1",
                    "worker_id": worker["worker_id"],
                    "operation_id": "operation-h1",
                    "task_kind": "panel_learning_hybrid_fusion",
                    "result_sha256": adoption["receipt"]["result_sha256"],
                }
            },
        )
        terminal = service.lookup_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        revision_before = store.get("run-h1")["revision"]

        cleanup = service.attest_fusion_safe_stop_cleanup(
            operation_ref=terminal["operation_ref"]
        )
        replay = service.attest_fusion_safe_stop_cleanup(
            operation_ref=terminal["operation_ref"]
        )

        assert terminal["cleanup_refs"] == {
            "worker_cleanup_ref": None,
            "provider_cleanup_ref": None,
        }
        assert cleanup["contract_version"] == (
            "benchmark_v2_actual_fusion_safe_stop_cleanup_v1"
        )
        assert cleanup["operation_ref"] == terminal["operation_ref"]
        assert cleanup["worker_cleanup_ref"]["backend_compute_termination"] in {
            "not_running",
            "terminated",
        }
        direct = cleanup["fusion_direct_provider_cleanup_ref"]
        assert direct["contract_version"] == (
            "benchmark_v2_hybrid_fusion_direct_provider_cleanup_ref_v1"
        )
        assert direct["direct_provider_role"] is None
        assert direct["historical_provider_lineage_allowed"] is True
        assert canonical_json_bytes(replay) == canonical_json_bytes(cleanup)
        assert store.get("run-h1")["revision"] == revision_before
        assert pending["operation_ref"]["content_sha256"] != terminal[
            "operation_ref"
        ]["content_sha256"]
    finally:
        store.close()


def test_s3_expired_completed_terminal_result_recovers_without_second_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.learn.workflow_service as workflow_service
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as attestation

    registry = _S3Registry()
    store, _composition, service, _started = _s3_service(tmp_path, registry)
    real_continue = workflow_service.continue_guarded_learning_stage_worker_result
    continuation_calls = 0
    try:
        monkeypatch.setattr(attestation, "PROJECT_ROOT", tmp_path.resolve())
        dispatch_context = _s3_omni_dispatch_context(tmp_path)
        monkeypatch.setattr(
            workflow_service,
            "_benchmark_v2_dispatch_context_for_worker",
            lambda **_kwargs: deepcopy(dispatch_context),
        )
        initial = service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        consumed_ref = deepcopy(initial["operation_ref"])
        registry.complete_current(
            {
                "contract_version": "learning_hybrid_managed_stage_result_v1",
                "learning_pipeline_mode": "hybrid_v1_1",
                "task_kind": "panel_learning_hybrid_omni_discovery",
                "outcome": "failed",
                "orchestration": {},
                "result": {"failure_reason": "provider failed"},
            }
        )
        worker = registry.current
        assert worker is not None
        execution = store.get("run-h1")["stages"]["screen_understanding"][
            "evidence_refs"
        ]["stage_execution"]
        lease_expires_at = datetime.fromisoformat(execution["lease_expires_at"])
        worker_finished_at = lease_expires_at - timedelta(seconds=1)
        worker["finished_at"] = worker_finished_at.isoformat()
        worker["payload"] = None
        wall_clock = lease_expires_at + timedelta(seconds=1)
        real_utc_datetime = workflow_service._utc_datetime
        monkeypatch.setattr(
            workflow_service,
            "_utc_datetime",
            lambda value: (
                wall_clock if value is None else real_utc_datetime(value)
            ),
        )

        def _flaky_continue(**kwargs):
            nonlocal continuation_calls
            continuation_calls += 1
            assert kwargs["now"] == worker_finished_at
            if continuation_calls == 1:
                raise RuntimeError("lost expired terminal continuation response")
            return real_continue(**kwargs)

        monkeypatch.setattr(
            workflow_service,
            "continue_guarded_learning_stage_worker_result",
            _flaky_continue,
        )

        with pytest.raises(
            RuntimeError, match="lost expired terminal continuation response"
        ):
            service.continue_hybrid_operation(operation_ref=consumed_ref)

        prepared = store.get("run-h1")
        assert prepared["terminal"] is False
        assert worker["result_adopted"] is True
        assert registry.adopt_calls == 1
        assert registry.start_calls == 1

        terminal = service.continue_hybrid_operation(operation_ref=consumed_ref)
        assert registry.current is not None
        registry.current["recovered_from_journal"] = True
        replay = service.continue_hybrid_operation(operation_ref=consumed_ref)

        assert terminal["status"] == "safe_stopped"
        assert canonical_json_bytes(replay) == canonical_json_bytes(terminal)
        assert store.get("run-h1")["terminal"] is True
        assert terminal["cleanup_refs"]["worker_cleanup_ref"][
            "contract_version"
        ] == "benchmark_v2_hybrid_completed_worker_cleanup_ref_v1"
        assert terminal["cleanup_refs"]["provider_cleanup_ref"] == worker[
            "benchmark_provider_cleanup_ref"
        ]
        assert registry.adopt_calls == 1
        assert registry.start_calls == 1
        assert registry.materialize_cleanup_calls == 2
        assert registry.cancel_calls == 0
        assert registry.active_resources == 0
        assert continuation_calls == 2
    finally:
        store.close()


def test_s3_expired_terminal_adoption_retries_after_preparation_write_loss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.learn.workflow_service as workflow_service
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as attestation

    registry = _S3Registry()
    store, _composition, service, _started = _s3_service(tmp_path, registry)
    try:
        monkeypatch.setattr(attestation, "PROJECT_ROOT", tmp_path.resolve())
        dispatch_context = _s3_omni_dispatch_context(tmp_path)
        monkeypatch.setattr(
            workflow_service,
            "_benchmark_v2_dispatch_context_for_worker",
            lambda **_kwargs: deepcopy(dispatch_context),
        )
        initial = service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        registry.complete_current(
            {
                "contract_version": "learning_hybrid_managed_stage_result_v1",
                "learning_pipeline_mode": "hybrid_v1_1",
                "task_kind": "panel_learning_hybrid_omni_discovery",
                "outcome": "failed",
                "orchestration": {},
                "result": {"failure_reason": "provider failed"},
            }
        )
        worker = registry.current
        assert worker is not None
        execution = store.get("run-h1")["stages"]["screen_understanding"][
            "evidence_refs"
        ]["stage_execution"]
        lease_expires_at = datetime.fromisoformat(execution["lease_expires_at"])
        worker["finished_at"] = (
            lease_expires_at - timedelta(seconds=1)
        ).isoformat()
        worker["payload"] = None
        wall_clock = lease_expires_at + timedelta(seconds=1)
        real_utc_datetime = workflow_service._utc_datetime
        monkeypatch.setattr(
            workflow_service,
            "_utc_datetime",
            lambda value: (
                wall_clock if value is None else real_utc_datetime(value)
            ),
        )
        real_persist = (
            workflow_service._persist_benchmark_v2_hybrid_continuation_receipt
        )
        persistence_calls = 0

        def _flaky_persist(**kwargs):
            nonlocal persistence_calls
            persistence_calls += 1
            if persistence_calls == 1:
                raise RuntimeError("lost terminal preparation write")
            return real_persist(**kwargs)

        monkeypatch.setattr(
            workflow_service,
            "_persist_benchmark_v2_hybrid_continuation_receipt",
            _flaky_persist,
        )

        with pytest.raises(RuntimeError, match="lost terminal preparation write"):
            service.continue_hybrid_operation(
                operation_ref=initial["operation_ref"]
            )

        assert worker["result_adopted"] is True
        assert store.get("run-h1")["terminal"] is False

        terminal = service.continue_hybrid_operation(
            operation_ref=initial["operation_ref"]
        )

        assert terminal["status"] == "safe_stopped"
        assert store.get("run-h1")["terminal"] is True
        assert registry.start_calls == 1
        assert registry.cancel_calls == 0
        assert registry.active_resources == 0
        assert registry.adopt_calls == 2
        assert registry.materialize_cleanup_calls == 2
        assert persistence_calls == 2
    finally:
        store.close()


@pytest.mark.parametrize(
    ("violation", "error_match"),
    (
        ("late_completion", "outside the lease interval"),
        ("pre_start_completion", "outside the lease interval"),
        ("missing_cleanup", "provider cleanup is not closed"),
        ("nonterminal_success", "result is not terminal-safe"),
        ("wrong_task_kind", "result is not terminal-safe"),
    ),
)
def test_s3_expired_completed_terminal_recovery_fails_closed_before_adoption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    violation: str,
    error_match: str,
) -> None:
    import app.learn.workflow_service as workflow_service

    registry = _S3Registry()
    store, _composition, service, _started = _s3_service(tmp_path, registry)
    try:
        initial = service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        response_outcome = (
            "completed" if violation == "nonterminal_success" else "failed"
        )
        registry.complete_current(
            {
                "contract_version": "learning_hybrid_managed_stage_result_v1",
                "learning_pipeline_mode": "hybrid_v1_1",
                "task_kind": (
                    "panel_learning_hybrid_qwen_binding"
                    if violation == "wrong_task_kind"
                    else "panel_learning_hybrid_omni_discovery"
                ),
                "outcome": response_outcome,
                "orchestration": {},
                "result": {},
            }
        )
        worker = registry.current
        assert worker is not None
        execution = store.get("run-h1")["stages"]["screen_understanding"][
            "evidence_refs"
        ]["stage_execution"]
        lease_expires_at = datetime.fromisoformat(execution["lease_expires_at"])
        started_at = datetime.fromisoformat(execution["started_at"])
        if violation == "late_completion":
            worker_finished_at = lease_expires_at + timedelta(seconds=1)
        elif violation == "pre_start_completion":
            worker_finished_at = started_at - timedelta(seconds=1)
        else:
            worker_finished_at = lease_expires_at - timedelta(seconds=1)
        worker["finished_at"] = worker_finished_at.isoformat()
        if violation != "missing_cleanup":
            worker["benchmark_provider_cleanup_ref"] = _s3_provider_cleanup_ref(
                worker
            )
        wall_clock = lease_expires_at + timedelta(seconds=2)
        real_utc_datetime = workflow_service._utc_datetime
        monkeypatch.setattr(
            workflow_service,
            "_utc_datetime",
            lambda value: (
                wall_clock if value is None else real_utc_datetime(value)
            ),
        )

        with pytest.raises(
            workflow_service.LearningWorkflowStageOperationError,
            match=error_match,
        ):
            service.continue_hybrid_operation(
                operation_ref=initial["operation_ref"]
            )

        assert worker["result_adopted"] is False
        assert store.get("run-h1")["terminal"] is False
        assert registry.start_calls == 1
        assert registry.cancel_calls == 0
        assert registry.active_resources == 0
    finally:
        store.close()


def test_s3_terminal_prepared_retry_resumes_without_false_terminal_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.learn.workflow_service as workflow_service

    registry = _S3Registry()
    store, _composition, service, _started = _s3_service(tmp_path, registry)
    continuation_calls = 0

    monkeypatch.setattr(
        workflow_service,
        "build_learning_pipeline_initial_worker_request",
        lambda **_kwargs: {
            "task_kind": "panel_learning_hybrid_review_projection",
            "payload": _hybrid_worker_payload(),
        },
    )

    def _continue(**_kwargs):
        nonlocal continuation_calls
        continuation_calls += 1
        if continuation_calls == 1:
            raise RuntimeError("transient terminal continuation failure")
        state = store.get("run-h1")
        evidence_path = tmp_path / "artifacts" / "terminal-review.json"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text("{}", encoding="utf-8")
        finished = workflow_service.finish_learning_workflow_stage_operation(
            store=store,
            project_root=tmp_path,
            run_id="run-h1",
            expected_revision=state["revision"],
            stage="screen_understanding",
            operation_id="operation-h1",
            outcome="completed",
            reason="terminal retry completed",
            evidence_refs={"trial_path": "artifacts/terminal-review.json"},
        )
        return {
            "stage_finished": True,
            "outcome": "completed",
            "next_stage_operation": None,
            "next_stage_worker": None,
            "workflow_state": finished["workflow_state"],
        }

    monkeypatch.setattr(
        workflow_service,
        "continue_guarded_learning_stage_worker_result",
        _continue,
    )
    try:
        initial = service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        consumed_ref = deepcopy(initial["operation_ref"])
        registry.complete_current({"outcome": "completed", "success": True})

        with pytest.raises(
            RuntimeError, match="transient terminal continuation failure"
        ):
            service.continue_hybrid_operation(operation_ref=consumed_ref)

        prepared_state = store.get("run-h1")
        prepared_execution = prepared_state["stages"]["screen_understanding"][
            "evidence_refs"
        ]["stage_execution"]
        prepared_receipt = prepared_execution[
            "benchmark_v2_workflow_service_hybrid"
        ]["continuation_receipt"]
        assert prepared_state["stages"]["screen_understanding"]["status"] == (
            "running"
        )
        assert prepared_receipt["receipt_phase"] == "terminal_prepared"
        assert prepared_receipt["returned_status"] is None

        returned = service.continue_hybrid_operation(operation_ref=consumed_ref)
        replay = service.continue_hybrid_operation(operation_ref=consumed_ref)

        assert returned["status"] == "complete"
        assert canonical_json_bytes(replay) == canonical_json_bytes(returned)
        assert returned["operation_ref"]["predecessor_content_sha256"] == (
            consumed_ref["content_sha256"]
        )
        assert continuation_calls == 2
        assert registry.status_calls == 1
        assert registry.adopt_calls == 1
        assert registry.start_calls == 1
    finally:
        store.close()


def test_completed_review_hybrid_cleanup_is_separate_and_replay_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.learn.workflow_service as workflow_service

    registry = _S3ReviewNoProviderRegistry()
    store, _composition, service, _started = _s3_service(tmp_path, registry)
    monkeypatch.setattr(
        workflow_service,
        "build_learning_pipeline_initial_worker_request",
        lambda **_kwargs: {
            "task_kind": "panel_learning_hybrid_review_projection",
            "payload": _hybrid_worker_payload(),
        },
    )

    def _continue(**_kwargs):
        state = store.get("run-h1")
        evidence_path = tmp_path / "artifacts" / "completed-review.json"
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text("{}", encoding="utf-8")
        finished = workflow_service.finish_learning_workflow_stage_operation(
            store=store,
            project_root=tmp_path,
            run_id="run-h1",
            expected_revision=state["revision"],
            stage="screen_understanding",
            operation_id="operation-h1",
            outcome="completed",
            reason="completed review projection",
            evidence_refs={"trial_path": "artifacts/completed-review.json"},
        )
        return {
            "stage_finished": True,
            "outcome": "completed",
            "next_stage_operation": None,
            "next_stage_worker": None,
            "workflow_state": finished["workflow_state"],
        }

    monkeypatch.setattr(
        workflow_service,
        "continue_guarded_learning_stage_worker_result",
        _continue,
    )
    try:
        initial = service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        registry.complete_current({"outcome": "completed", "success": True})
        returned = service.continue_hybrid_operation(
            operation_ref=initial["operation_ref"]
        )
        revision_before = store.get("run-h1")["revision"]
        step_before = service.lookup_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )

        cleanup = service.attest_completed_hybrid_cleanup(
            operation_ref=returned["operation_ref"]
        )
        cleanup_replay = service.attest_completed_hybrid_cleanup(
            operation_ref=returned["operation_ref"]
        )
        step_after = service.lookup_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )

        assert returned["status"] == "complete"
        assert returned["cleanup_refs"] == {
            "worker_cleanup_ref": None,
            "provider_cleanup_ref": None,
        }
        assert cleanup["contract_version"] == (
            "benchmark_v2_actual_completed_hybrid_cleanup_v1"
        )
        assert cleanup["operation_ref"] == returned["operation_ref"]
        assert cleanup["cleanup_status"] == "stable_zero"
        assert cleanup["worker_cleanup_ref"]["contract_version"] == (
            "benchmark_v2_hybrid_worker_cleanup_ref_v1"
        )
        assert cleanup["provider_cleanup_ref"]["contract_version"] == (
            "benchmark_v2_hybrid_no_provider_cleanup_ref_v1"
        )
        assert canonical_json_bytes(cleanup_replay) == canonical_json_bytes(cleanup)
        for path in (
            ("worker_cleanup_ref",),
            ("provider_cleanup_ref",),
            ("provider_cleanup_ref", "live_absence_observation"),
        ):
            tampered = deepcopy(cleanup)
            target = tampered
            for name in path:
                target = target[name]
            target["unexpected"] = True
            _reseal(target)
            if len(path) == 2:
                _reseal(tampered["provider_cleanup_ref"])
            _reseal(tampered)
            with pytest.raises(ValueError, match="not closed"):
                incumbent.validate_benchmark_v2_actual_completed_hybrid_cleanup(
                    tampered
                )
        authorizing = deepcopy(cleanup)
        authorizing["artifact_is_authorization"] = True
        _reseal(authorizing)
        with pytest.raises(ValueError, match="cleanup is invalid"):
            incumbent.validate_benchmark_v2_actual_completed_hybrid_cleanup(
                authorizing
            )
        stale_provider = deepcopy(cleanup)
        stale_provider["provider_cleanup_ref"]["operation_id"] = "other-operation"
        _reseal(stale_provider["provider_cleanup_ref"])
        _reseal(stale_provider)
        with pytest.raises(ValueError, match="provider cleanup is stale"):
            incumbent.validate_benchmark_v2_actual_completed_hybrid_cleanup(
                stale_provider
            )
        assert canonical_json_bytes(step_after) == canonical_json_bytes(step_before)
        assert store.get("run-h1")["revision"] == revision_before
        assert registry.cancel_calls == 2
        assert registry.review_no_provider_cleanup_calls == 2
        assert registry.active_resources == 0
    finally:
        store.close()


def test_actual_stable_zero_propagates_completed_review_no_provider_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.learn.workflow_service as workflow_service
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import (
        _ActualService,
        _actual_completed_review_cleanup,
        _actual_completed_review_step,
        _actual_incumbent_cancelled_terminal_receipt,
        _actual_operation,
    )

    binding = {
        "stage": "screen_understanding",
        "window_binding_ref": _identity("window-review-stable-zero"),
        "capture_ref": _identity("capture-review-stable-zero", SHA_B),
    }
    screen_group = {
        "request_ref": _identity("request-review-stable-zero", "c" * 64)
    }
    review_step = _actual_completed_review_step(
        screen_group,
        {
            **binding,
            "run_id": "run-review-stable-zero",
            "operation_id": "operation-review-stable-zero",
        },
    )
    review_operation = review_step["operation_ref"]
    review_cleanup = _actual_completed_review_cleanup(review_operation)
    review_worker = {
        **deepcopy(review_operation["worker_ref"]),
        "status": "completed",
        "runtime_attached": False,
        "result_available": True,
        "result_adopted": True,
    }

    fake_service = _ActualService([])
    incumbent_terminals = []
    child_states = {}
    for index in range(5):
        pending = _actual_operation(
            mode="incumbent_qwen_only",
            operation_id=f"incumbent-review-stable-zero-{index}",
            request_ref={
                "id": f"case-review-stable-zero-{index}",
                "content_sha256": f"{index + 1:x}" * 64,
            },
            binding={
                **binding,
                "run_id": f"run-review-stable-zero-{index}",
            },
            revision=index + 1,
        )
        terminal = fake_service.cancel_operation(operation_ref=pending)
        incumbent_terminals.append(terminal)
        operation_ref = terminal["operation_ref"]
        cleanup = terminal["cleanup_refs"]
        child_states[operation_ref["run_id"]] = {
            "execution": {"operation_id": operation_ref["operation_id"]},
            "operation": {
                "_operation_ref": operation_ref,
                "phase": operation_ref["status"],
                "run_id": operation_ref["run_id"],
                "stage": operation_ref["stage"],
                "operation_id": operation_ref["operation_id"],
                "handler_payload_source": {
                    "provider_case_ref": {
                        "case_id": operation_ref["request_ref"]["id"]
                    }
                },
                "window_binding_ref": operation_ref["window_binding_ref"],
                "capture_ref": operation_ref["capture_ref"],
                "worker_cleanup_ref": cleanup["worker_cleanup_ref"],
                "provider_cleanup_ref": cleanup["provider_cleanup_ref"],
                "reservation_ref": cleanup["worker_cleanup_ref"]["reservation_ref"],
                    "terminal_receipt": _actual_incumbent_cancelled_terminal_receipt(
                        operation=operation_ref,
                        worker_cleanup_ref=cleanup["worker_cleanup_ref"],
                        provider_cleanup_ref=cleanup["provider_cleanup_ref"],
                    ),
            },
        }

    class _Store:
        def get(self, run_id: str) -> dict[str, object]:
            return child_states[run_id]

    class _Root:
        authority_kind = "benchmark_v2_workflow_service_dispatch_cleanup"

    composition = workflow_service.compose_test_learning_workflow_service_unit(
        store=_Store(),
        worker_registry=object(),
        project_root=tmp_path,
        benchmark_supervision_root=_Root(),
    )
    service = incumbent.BenchmarkV2IncumbentWorkflowService(composition)
    completed_cleanup_calls = []

    monkeypatch.setattr(
        workflow_service,
        "_benchmark_v2_hybrid_service_context",
        lambda **_kwargs: (
            {"run_id": review_operation["run_id"]},
            {"operation_id": review_operation["operation_id"]},
            {"content_sha256": "d" * 64},
            review_worker,
            review_operation,
        ),
    )
    monkeypatch.setattr(
        workflow_service,
        "_benchmark_v2_hybrid_service_status",
        lambda **_kwargs: "complete",
    )
    monkeypatch.setattr(
        workflow_service,
        "_project_benchmark_v2_hybrid_step",
        lambda **_kwargs: {
            "cleanup_refs": {
                "worker_cleanup_ref": None,
                "provider_cleanup_ref": None,
            }
        },
    )

    def _attest_completed(**kwargs: object) -> dict[str, object]:
        completed_cleanup_calls.append(deepcopy(dict(kwargs)))
        return deepcopy(review_cleanup)

    monkeypatch.setattr(
        workflow_service,
        "_attest_benchmark_v2_actual_completed_hybrid_cleanup",
        _attest_completed,
    )
    monkeypatch.setattr(
        workflow_service,
        "_benchmark_v2_stage_execution",
        lambda current, _stage: current["execution"],
    )
    monkeypatch.setattr(
        workflow_service,
        "_benchmark_v2_incumbent_operation_from_state",
        lambda current, _stage: current["operation"],
    )
    monkeypatch.setattr(
        workflow_service,
        "_project_benchmark_v2_workflow_service_operation_ref",
        lambda **kwargs: kwargs["operation"]["_operation_ref"],
    )
    monkeypatch.setattr(
        workflow_service,
        "_benchmark_v2_incumbent_parent_binding_identity",
        lambda **_kwargs: (
            review_operation["run_id"],
            review_operation["operation_id"],
        ),
    )
    monkeypatch.setattr(
        workflow_service,
        "_validate_benchmark_v2_actual_incumbent_worker_cleanup",
        lambda *, cleanup, operation: cleanup,
    )
    monkeypatch.setattr(
        workflow_service,
        "_validate_benchmark_v2_provider_cleanup_parent",
        lambda *, cleanup, **_kwargs: cleanup,
    )

    operation_refs = [
        review_operation,
        *(item["operation_ref"] for item in incumbent_terminals),
    ]
    first = service.attest_actual_operations_stable_zero(
        operation_refs=operation_refs
    )
    replay = service.attest_actual_operations_stable_zero(
        operation_refs=operation_refs
    )

    assert canonical_json_bytes(replay) == canonical_json_bytes(first)
    assert len(completed_cleanup_calls) == 2
    assert all(
        call["operation_ref"] == review_operation
        for call in completed_cleanup_calls
    )
    hybrid_entry = next(
        item
        for item in first["cleanup_entries"]
        if item["operation_ref_sha256"] == review_operation["content_sha256"]
    )
    assert hybrid_entry["provider_cleanup_ref"] == review_cleanup[
        "provider_cleanup_ref"
    ]
    assert hybrid_entry["provider_cleanup_ref"]["contract_version"] == (
        "benchmark_v2_hybrid_no_provider_cleanup_ref_v1"
    )


def test_actual_stable_zero_propagates_exact_fusion_safe_stop_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.learn.workflow_service as workflow_service
    from test_portfolio_hybrid_v1_1_benchmark_v2_runtime import (
        _ActualService,
        _actual_fusion_safe_stop_cleanup,
        _actual_fusion_safe_stop_step,
        _actual_incumbent_cancelled_terminal_receipt,
        _actual_operation,
    )

    binding = {
        "stage": "screen_understanding",
        "window_binding_ref": _identity("window-fusion-stable-zero"),
        "capture_ref": _identity("capture-fusion-stable-zero", SHA_B),
        "run_id": "run-fusion-stable-zero",
        "operation_id": "operation-fusion-stable-zero",
    }
    screen_group = {
        "request_ref": _identity("request-fusion-stable-zero", "c" * 64)
    }
    fusion_step = _actual_fusion_safe_stop_step(screen_group, binding)
    fusion_operation = fusion_step["operation_ref"]
    fusion_cleanup = _actual_fusion_safe_stop_cleanup(fusion_operation)
    fusion_worker = {
        **deepcopy(fusion_operation["worker_ref"]),
        "status": "completed",
        "runtime_attached": False,
        "result_available": True,
        "result_adopted": True,
    }

    fake_service = _ActualService([])
    incumbent_terminals = []
    child_states = {}
    for index in range(5):
        pending = _actual_operation(
            mode="incumbent_qwen_only",
            operation_id=f"incumbent-fusion-stable-zero-{index}",
            request_ref={
                "id": f"case-fusion-stable-zero-{index}",
                "content_sha256": f"{index + 1:x}" * 64,
            },
            binding={
                **binding,
                "run_id": f"run-fusion-stable-zero-{index}",
            },
            revision=index + 1,
        )
        terminal = fake_service.cancel_operation(operation_ref=pending)
        incumbent_terminals.append(terminal)
        operation_ref = terminal["operation_ref"]
        cleanup = terminal["cleanup_refs"]
        child_states[operation_ref["run_id"]] = {
            "execution": {"operation_id": operation_ref["operation_id"]},
            "operation": {
                "_operation_ref": operation_ref,
                "phase": operation_ref["status"],
                "run_id": operation_ref["run_id"],
                "stage": operation_ref["stage"],
                "operation_id": operation_ref["operation_id"],
                "handler_payload_source": {
                    "provider_case_ref": {
                        "case_id": operation_ref["request_ref"]["id"]
                    }
                },
                "window_binding_ref": operation_ref["window_binding_ref"],
                "capture_ref": operation_ref["capture_ref"],
                "worker_cleanup_ref": cleanup["worker_cleanup_ref"],
                "provider_cleanup_ref": cleanup["provider_cleanup_ref"],
                "reservation_ref": cleanup["worker_cleanup_ref"]["reservation_ref"],
                "terminal_receipt": _actual_incumbent_cancelled_terminal_receipt(
                    operation=operation_ref,
                    worker_cleanup_ref=cleanup["worker_cleanup_ref"],
                    provider_cleanup_ref=cleanup["provider_cleanup_ref"],
                ),
            },
        }

    class _Store:
        def get(self, run_id: str) -> dict[str, object]:
            return child_states[run_id]

    class _Root:
        authority_kind = "benchmark_v2_workflow_service_dispatch_cleanup"

    composition = workflow_service.compose_test_learning_workflow_service_unit(
        store=_Store(),
        worker_registry=object(),
        project_root=tmp_path,
        benchmark_supervision_root=_Root(),
    )
    service = incumbent.BenchmarkV2IncumbentWorkflowService(composition)
    fusion_cleanup_calls = []
    monkeypatch.setattr(
        workflow_service,
        "_benchmark_v2_hybrid_service_context",
        lambda **_kwargs: (
            {"run_id": fusion_operation["run_id"]},
            {"operation_id": fusion_operation["operation_id"]},
            {"content_sha256": "d" * 64},
            fusion_worker,
            fusion_operation,
        ),
    )
    monkeypatch.setattr(
        workflow_service,
        "_benchmark_v2_hybrid_service_status",
        lambda **_kwargs: "safe_stopped",
    )
    monkeypatch.setattr(
        workflow_service,
        "_project_benchmark_v2_hybrid_step",
        lambda **_kwargs: deepcopy(fusion_step),
    )

    def _attest_fusion(**kwargs: object) -> dict[str, object]:
        fusion_cleanup_calls.append(deepcopy(dict(kwargs)))
        return deepcopy(fusion_cleanup)

    monkeypatch.setattr(
        workflow_service,
        "_attest_benchmark_v2_actual_fusion_safe_stop_cleanup",
        _attest_fusion,
    )
    monkeypatch.setattr(
        workflow_service,
        "_benchmark_v2_stage_execution",
        lambda current, _stage: current["execution"],
    )
    monkeypatch.setattr(
        workflow_service,
        "_benchmark_v2_incumbent_operation_from_state",
        lambda current, _stage: current["operation"],
    )
    monkeypatch.setattr(
        workflow_service,
        "_project_benchmark_v2_workflow_service_operation_ref",
        lambda **kwargs: kwargs["operation"]["_operation_ref"],
    )
    monkeypatch.setattr(
        workflow_service,
        "_benchmark_v2_incumbent_parent_binding_identity",
        lambda **_kwargs: (
            fusion_operation["run_id"],
            fusion_operation["operation_id"],
        ),
    )
    monkeypatch.setattr(
        workflow_service,
        "_validate_benchmark_v2_actual_incumbent_worker_cleanup",
        lambda *, cleanup, operation: cleanup,
    )
    monkeypatch.setattr(
        workflow_service,
        "_validate_benchmark_v2_provider_cleanup_parent",
        lambda *, cleanup, **_kwargs: cleanup,
    )

    receipt = service.attest_actual_operations_stable_zero(
        operation_refs=[
            fusion_operation,
            *(item["operation_ref"] for item in incumbent_terminals),
        ]
    )

    assert len(fusion_cleanup_calls) == 1
    assert fusion_cleanup_calls[0]["operation_ref"] == fusion_operation
    hybrid_entry = next(
        item
        for item in receipt["cleanup_entries"]
        if item["operation_ref_sha256"] == fusion_operation["content_sha256"]
    )
    assert hybrid_entry["worker_cleanup_ref"] == fusion_cleanup[
        "worker_cleanup_ref"
    ]
    assert hybrid_entry["provider_cleanup_ref"] == fusion_cleanup[
        "fusion_direct_provider_cleanup_ref"
    ]


def test_completed_hybrid_cleanup_rejects_nonterminal_without_side_effects(
    tmp_path: Path,
) -> None:
    import app.learn.workflow_service as workflow_service

    registry = _S3Registry()
    store, _composition, service, _started = _s3_service(tmp_path, registry)
    try:
        initial = service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )

        with pytest.raises(
            workflow_service.LearningWorkflowStageOperationError,
            match="cleanup bridge is unavailable",
        ):
            service.attest_completed_hybrid_cleanup(
                operation_ref=initial["operation_ref"]
            )

        assert registry.cancel_calls == 0
    finally:
        service.cancel_operation(operation_ref=initial["operation_ref"])
        store.close()


def test_s3_terminal_prepared_state_remains_cancellable_with_zero_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.learn.workflow_service as workflow_service

    registry = _S3Registry()
    store, _composition, service, _started = _s3_service(tmp_path, registry)
    continuation_calls = 0

    monkeypatch.setattr(
        workflow_service,
        "build_learning_pipeline_initial_worker_request",
        lambda **_kwargs: {
            "task_kind": "panel_learning_hybrid_review_projection",
            "payload": _hybrid_worker_payload(),
        },
    )

    def _continue(**_kwargs):
        nonlocal continuation_calls
        continuation_calls += 1
        raise RuntimeError("transient terminal continuation failure")

    monkeypatch.setattr(
        workflow_service,
        "continue_guarded_learning_stage_worker_result",
        _continue,
    )
    try:
        initial = service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        consumed_ref = deepcopy(initial["operation_ref"])
        registry.complete_current({"outcome": "completed", "success": True})
        with pytest.raises(RuntimeError):
            service.continue_hybrid_operation(operation_ref=consumed_ref)

        cancelled = service.cancel_operation(operation_ref=consumed_ref)
        replay = service.cancel_operation(operation_ref=cancelled["operation_ref"])

        assert cancelled["status"] == "safe_stopped"
        assert canonical_json_bytes(replay) == canonical_json_bytes(cancelled)
        assert cancelled["operation_ref"]["predecessor_content_sha256"] == (
            consumed_ref["content_sha256"]
        )
        assert continuation_calls == 1
        assert registry.status_calls == 1
        assert registry.adopt_calls == 1
        assert registry.cancel_calls == 1
        assert registry.active_resources == 0
    finally:
        store.close()


def test_s3_terminal_prepared_review_without_provider_projects_exact_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.learn.workflow_service as workflow_service

    registry = _S3ReviewNoProviderRegistry()
    store, _composition, service, _started = _s3_service(tmp_path, registry)
    monkeypatch.setattr(
        workflow_service,
        "build_learning_pipeline_initial_worker_request",
        lambda **_kwargs: {
            "task_kind": "panel_learning_hybrid_review_projection",
            "payload": _hybrid_worker_payload(),
        },
    )
    monkeypatch.setattr(
        workflow_service,
        "continue_guarded_learning_stage_worker_result",
        lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("transient terminal continuation failure")
        ),
    )
    try:
        initial = service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        consumed_ref = deepcopy(initial["operation_ref"])
        registry.complete_current({"outcome": "completed", "success": True})
        with pytest.raises(RuntimeError, match="transient terminal continuation failure"):
            service.continue_hybrid_operation(operation_ref=consumed_ref)

        terminal = service.cancel_operation(operation_ref=consumed_ref)
        replay = service.cancel_operation(operation_ref=terminal["operation_ref"])

        provider_cleanup = terminal["cleanup_refs"]["provider_cleanup_ref"]
        worker_cleanup = terminal["cleanup_refs"]["worker_cleanup_ref"]
        assert terminal["status"] == "safe_stopped"
        assert provider_cleanup["contract_version"] == (
            "benchmark_v2_hybrid_no_provider_cleanup_ref_v1"
        )
        assert provider_cleanup["worker_cleanup_ref"] == {
            "content_sha256": worker_cleanup["content_sha256"]
        }
        assert provider_cleanup["returned_worker_ref"] == terminal["operation_ref"][
            "worker_ref"
        ]
        assert provider_cleanup["live_absence_observation"][
            "review_dispatch_context_absent"
        ] is True
        assert provider_cleanup["live_absence_observation"][
            "review_dispatch_receipt_absent"
        ] is True
        assert canonical_json_bytes(replay) == canonical_json_bytes(terminal)
        assert registry.review_no_provider_cleanup_calls == 2
        assert registry.cancel_calls == 1
        assert registry.active_resources == 0
    finally:
        store.close()


@pytest.mark.parametrize(
    "mutated_parent",
    (
        "predecessor_content_sha256",
        "revision",
        "worker_ref",
        "window_binding_ref",
        "capture_ref",
    ),
)
def test_s3_stale_hybrid_ref_rejects_before_downstream_effects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutated_parent: str,
) -> None:
    import app.learn.workflow_service as workflow_service
    from app.learn.recognition.uei.canonical import seal_immutable

    registry = _S3Registry()
    store, _composition, service, _started = _s3_service(tmp_path, registry)
    continuation_calls = 0

    def _unexpected_continue(**_kwargs):
        nonlocal continuation_calls
        continuation_calls += 1
        raise AssertionError("stale hybrid ref reached continuation")

    monkeypatch.setattr(
        workflow_service,
        "continue_guarded_learning_stage_worker_result",
        _unexpected_continue,
    )
    try:
        started = service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        stale = deepcopy(started["operation_ref"])
        if mutated_parent == "predecessor_content_sha256":
            stale[mutated_parent] = "0" * 64
        elif mutated_parent == "revision":
            stale["workflow_state_ref"]["revision"] += 1
            stale["stage_execution_ref"]["revision"] += 1
        elif mutated_parent == "worker_ref":
            worker = deepcopy(stale["worker_ref"])
            worker.pop("content_sha256")
            worker["worker_id"] = "worker-hybrid-stale"
            stale["worker_ref"] = seal_immutable(worker)
        else:
            stale[mutated_parent]["id"] = f"stale-{mutated_parent}"
        stale["content_sha256"] = content_sha256(stale)

        with pytest.raises(ValueError, match="stale"):
            service.continue_hybrid_operation(operation_ref=stale)

        assert registry.status_calls == 0
        assert registry.adopt_calls == 0
        assert registry.read_calls == 0
        assert registry.cancel_calls == 0
        assert registry.start_calls == 1
        assert continuation_calls == 0
    finally:
        store.close()


def test_s3_hybrid_cancel_replays_and_leaves_zero_resources(tmp_path: Path) -> None:
    registry = _S3Registry()
    store, _composition, service, _started = _s3_service(tmp_path, registry)
    try:
        started = service.start_hybrid_operation(
            screen_group=_screen_group(),
            window_binding=_s3_window_binding(),
        )
        cancelled = service.cancel_operation(
            operation_ref=started["operation_ref"]
        )
        replay = service.cancel_operation(
            operation_ref=cancelled["operation_ref"]
        )

        assert replay == cancelled
        assert cancelled["status"] == "safe_stopped"
        worker = cancelled["operation_ref"]["worker_ref"]
        worker_cleanup = cancelled["cleanup_refs"]["worker_cleanup_ref"]
        provider_cleanup = cancelled["cleanup_refs"]["provider_cleanup_ref"]
        assert all(
            worker_cleanup[name] == worker[name]
            for name in ("worker_id", "model_request_id", "payload_sha256")
        )
        assert all(
            provider_cleanup[name] == worker[name]
            for name in ("worker_id", "model_request_id", "payload_sha256")
        )
        assert provider_cleanup["contract_version"] == (
            "benchmark_provider_cleanup_ref_v1"
        )
        assert registry.cancel_calls == 1
        assert registry.active_resources == 0
    finally:
        store.close()


def test_s3_vista_completed_cleanup_materialization_uses_vista_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Service materialization must not silently skip VISTA's pre-dispatch path."""
    from app.learn import workflow_service
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as attestation

    monkeypatch.setattr(attestation, "PROJECT_ROOT", tmp_path.resolve())
    registry = _S3Registry()
    store, composition, _service, _started = _s3_service(tmp_path, registry)
    context = attestation.compose_benchmark_dispatch_context(
        provider="vista",
        operation_ref={
            "run_id": "run-h1",
            "stage": "screen_understanding",
            "operation_id": "operation-h1",
            "revision": 4,
            "window_binding_ref": deepcopy(_s3_window_binding()["window_binding_ref"]),
            "capture_ref": deepcopy(_s3_window_binding()["capture_ref"]),
        },
        window_binding={
            "contract_version": "test_window_binding_v1",
            "exact_hwnd": 101,
            "process_identity": {"pid": 202, "create_time_ns": 303},
            "job_name": "job-h1",
            "payload_sha256": "c" * 64,
        },
        receipt_journal_path=attestation._fixed_dispatch_journal_path(
            {
                "run_id": "run-h1",
                "stage": "screen_understanding",
                "operation_id": "operation-h1",
                "revision": 4,
                "window_binding_ref": deepcopy(
                    _s3_window_binding()["window_binding_ref"]
                ),
                "capture_ref": deepcopy(_s3_window_binding()["capture_ref"]),
            }
        ),
    )
    worker = registry.start(
        run_id="run-h1",
        stage="screen_understanding",
        operation_id="operation-h1",
        task_kind="panel_learning_calibration_sequence",
        payload=_hybrid_worker_payload(),
    )
    registry.complete_current({"outcome": "failed"})
    worker = registry.current
    assert worker is not None
    calls: list[dict[str, object]] = []

    def _materialize(**kwargs: object) -> dict[str, object]:
        calls.append(deepcopy(dict(kwargs)))
        worker["benchmark_provider_cleanup_ref"] = _s3_provider_cleanup_ref(worker)
        return deepcopy(worker["benchmark_provider_cleanup_ref"])

    monkeypatch.setattr(registry, "materialize_completed_hybrid_provider_cleanup", _materialize)
    refreshed = workflow_service._materialize_benchmark_v2_hybrid_completed_cleanup(
        composition=composition,
        binding={
            "provider_dispatch_context_refs": {
                "vista": attestation.compose_benchmark_dispatch_context_ref(context=context)
            }
        },
        worker_record=worker,
    )
    assert len(calls) == 1
    assert calls[0]["dispatch_context_ref"]["provider"] == "vista"
    assert refreshed["benchmark_provider_cleanup_ref"] == worker["benchmark_provider_cleanup_ref"]
    store.close()


def test_s3_safe_stopped_completed_vista_cancel_materializes_cleanup_before_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import workflow_service

    registry = _S3Registry()
    store, composition, _service, _started = _s3_service(tmp_path, registry)
    worker = registry.start(
        run_id="run-h1",
        stage="screen_understanding",
        operation_id="operation-h1",
        task_kind="panel_learning_calibration_sequence",
        payload=_hybrid_worker_payload(),
    )
    registry.complete_current({"outcome": "failed"})
    worker = registry.current
    assert worker is not None
    worker["result_adopted"] = True
    current = store.get("run-h1")
    stage_execution = {"safe": "stopped"}
    binding = {"provider_dispatch_context_refs": {"vista": {}}}
    supplied = {"stage": "screen_understanding"}
    materialized = _s3_provider_cleanup_ref(worker)
    worker["benchmark_provider_cleanup_ref"] = deepcopy(materialized)
    calls: list[str] = []
    try:
        monkeypatch.setattr(
            workflow_service,
            "_benchmark_v2_hybrid_terminal_prepared_context",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            workflow_service,
            "_benchmark_v2_hybrid_service_context",
            lambda **_kwargs: (current, stage_execution, binding, worker, supplied),
        )
        monkeypatch.setattr(
            workflow_service,
            "_benchmark_v2_hybrid_service_status",
            lambda **_kwargs: "safe_stopped",
        )

        def _materialize(**_kwargs: object) -> dict[str, object]:
            calls.append("materialize")
            return {**worker, "benchmark_provider_cleanup_ref": deepcopy(materialized)}

        monkeypatch.setattr(
            workflow_service,
            "_materialize_benchmark_v2_hybrid_completed_cleanup",
            _materialize,
        )

        def _project(**kwargs: object) -> dict[str, object]:
            calls.append("project")
            assert kwargs["worker_record"]["benchmark_provider_cleanup_ref"] == materialized
            return {"status": "safe_stopped", "cleanup_refs": {"provider_cleanup_ref": materialized}}

        monkeypatch.setattr(workflow_service, "_project_benchmark_v2_hybrid_step", _project)
        result = workflow_service._cancel_benchmark_v2_hybrid_workflow_service(
            composition=composition,
            operation_ref={"run_id": "run-h1", "operation_id": "operation-h1"},
        )
        replay = workflow_service._cancel_benchmark_v2_hybrid_workflow_service(
            composition=composition,
            operation_ref={"run_id": "run-h1", "operation_id": "operation-h1"},
        )
        assert result["cleanup_refs"]["provider_cleanup_ref"] == materialized
        assert replay == result
        assert calls == ["materialize", "project", "materialize", "project"]
    finally:
        store.close()


def test_s3_safe_stopped_completed_qwen_cancel_materializes_cleanup_before_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import workflow_service

    registry = _S3Registry()
    store, composition, _service, _started = _s3_service(tmp_path, registry)
    registry.start(
        run_id="run-h1",
        stage="screen_understanding",
        operation_id="operation-h1",
        task_kind="panel_learning_hybrid_qwen_binding",
        payload=_hybrid_worker_payload(),
    )
    registry.complete_current({"outcome": "failed"})
    worker = registry.current
    assert worker is not None
    worker["result_adopted"] = True
    current = store.get("run-h1")
    materialized = _s3_provider_cleanup_ref(worker)
    worker_cleanup = {"content_sha256": "f" * 64}
    calls: list[str] = []
    try:
        monkeypatch.setattr(
            workflow_service,
            "_benchmark_v2_hybrid_terminal_prepared_context",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            workflow_service,
            "_benchmark_v2_hybrid_service_context",
            lambda **_kwargs: (
                current,
                {"safe": "stopped"},
                {"provider_dispatch_context_refs": {"qwen": {}}},
                worker,
                {"stage": "screen_understanding"},
            ),
        )
        monkeypatch.setattr(
            workflow_service,
            "_benchmark_v2_hybrid_service_status",
            lambda **_kwargs: "safe_stopped",
        )

        def _materialize(**_kwargs: object) -> dict[str, object]:
            calls.append("materialize")
            return {**worker, "benchmark_provider_cleanup_ref": deepcopy(materialized)}

        monkeypatch.setattr(
            workflow_service,
            "_materialize_benchmark_v2_hybrid_completed_cleanup",
            _materialize,
        )

        def _project(**kwargs: object) -> dict[str, object]:
            calls.append("project")
            assert kwargs["worker_record"]["benchmark_provider_cleanup_ref"] == materialized
            return {
                "status": "safe_stopped",
                "cleanup_refs": {
                    "worker_cleanup_ref": worker_cleanup,
                    "provider_cleanup_ref": materialized,
                },
            }

        monkeypatch.setattr(workflow_service, "_project_benchmark_v2_hybrid_step", _project)
        result = workflow_service._cancel_benchmark_v2_hybrid_workflow_service(
            composition=composition,
            operation_ref={"run_id": "run-h1", "operation_id": "operation-h1"},
        )
        assert result["cleanup_refs"]["worker_cleanup_ref"] == worker_cleanup
        assert result["cleanup_refs"]["provider_cleanup_ref"] == materialized
        assert calls == ["materialize", "project"]
    finally:
        store.close()


@pytest.mark.parametrize(
    ("backend_termination", "model_termination", "expected_verified"),
    [
        ("not_running", "request_not_active", True),
        ("not_covered", "request_not_active", False),
        ("not_running", "cancel_failed", False),
    ],
)
def test_s3_safe_stopped_projection_requires_terminal_cancellation_cleanup(
    monkeypatch: pytest.MonkeyPatch,
    backend_termination: str,
    model_termination: str,
    expected_verified: bool,
) -> None:
    from types import SimpleNamespace

    from app.learn import workflow_service
    from app.learn.hybrid import benchmark_v2_incumbent_operation as incumbent

    worker = {
        "run_id": "run-h1",
        "stage": "screen_understanding",
        "operation_id": "operation-h1",
        "worker_id": "worker-h1",
        "model_request_id": "request-h1",
        "payload_sha256": "1" * 64,
        "task_kind": "panel_learning_hybrid_qwen_binding",
        "result_adopted": True,
        "benchmark_provider_cleanup_ref": {"content_sha256": "2" * 64},
    }
    captured: dict[str, object] = {}
    provider_cleanup = {"content_sha256": "3" * 64}

    monkeypatch.setattr(
        workflow_service,
        "_project_benchmark_v2_hybrid_expired_failure_cleanup",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        workflow_service,
        "_validate_benchmark_v2_hybrid_provider_cleanup",
        lambda **_kwargs: deepcopy(provider_cleanup),
    )

    def project_operation_ref(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"content_sha256": "4" * 64}

    monkeypatch.setattr(
        workflow_service,
        "_project_benchmark_v2_hybrid_operation_ref",
        project_operation_ref,
    )
    monkeypatch.setattr(
        incumbent,
        "compose_benchmark_v2_workflow_service_step",
        lambda **kwargs: deepcopy(dict(kwargs)),
    )

    projected = workflow_service._project_benchmark_v2_hybrid_step(
        composition=SimpleNamespace(worker_registry=object()),
        workflow_state={},
        stage_execution={
            "cancellation": {
                "backend_compute_termination": backend_termination,
                "model_service_compute_termination": model_termination,
            }
        },
        binding={"provider_dispatch_context_refs": {}},
        worker_record=worker,
        status="safe_stopped",
    )

    assert captured["recovered_cleanup_verified"] is expected_verified
    assert projected["cleanup_refs"]["worker_cleanup_ref"] is not None
    assert projected["cleanup_refs"]["provider_cleanup_ref"] == provider_cleanup


@pytest.mark.parametrize(
    ("scenario", "expected_verified"),
    [
        ("absent", True),
        ("committed", False),
        ("missing_context", False),
        ("malformed_context", False),
        ("provider_mismatch", False),
        ("cross_lineage", False),
        ("run_mismatch", False),
        ("stage_mismatch", False),
        ("window_binding_ref_mismatch", False),
        ("capture_ref_mismatch", False),
        ("journal_binding_mismatch", False),
        ("not_completed", False),
        ("runtime_attached", False),
        ("result_unavailable", False),
        ("nonterminal_cleanup", False),
        ("adopted", False),
        ("non_qwen", False),
    ],
)
def test_s3_qwen_predispatch_safe_stop_requires_durable_zero_dispatch_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
    expected_verified: bool,
) -> None:
    from types import SimpleNamespace

    from app.learn import workflow_service
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as attestation
    from app.learn.hybrid import benchmark_v2_incumbent_operation as incumbent
    from test_portfolio_hybrid_v1_1_benchmark_v2_dispatch_attestation import (
        _runtime_attestation,
    )

    monkeypatch.setattr(attestation, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        attestation,
        "_attest_exact_window",
        lambda value: {"content_sha256": "d" * 64},
    )
    monkeypatch.setattr(
        attestation,
        "_attest_exact_provider_runtime",
        lambda provider, value: _runtime_attestation(
            attestation,
            provider=provider,
            digit="2",
        ),
    )
    window_binding = _s3_window_binding()
    operation_ref = {
        "run_id": "run-h1",
        "stage": "screen_understanding",
        "operation_id": (
            "operation-other" if scenario == "cross_lineage" else "operation-h1"
        ),
        "revision": 5,
        "window_binding_ref": deepcopy(window_binding["window_binding_ref"]),
        "capture_ref": deepcopy(window_binding["capture_ref"]),
    }
    if scenario == "window_binding_ref_mismatch":
        operation_ref["window_binding_ref"] = deepcopy(
            window_binding["window_binding_ref"]
        )
        operation_ref["window_binding_ref"]["content_sha256"] = "e" * 64
    if scenario == "capture_ref_mismatch":
        operation_ref["capture_ref"] = deepcopy(window_binding["capture_ref"])
        operation_ref["capture_ref"]["content_sha256"] = "f" * 64
    context = attestation.compose_benchmark_dispatch_context(
        provider="omni" if scenario == "provider_mismatch" else "qwen",
        operation_ref=operation_ref,
        window_binding={
            "contract_version": "test_window_binding_v1",
            "exact_hwnd": 101,
            "process_identity": {"pid": 202, "create_time_ns": 303},
            "job_name": "job-h1",
            "payload_sha256": "c" * 64,
        },
        receipt_journal_path=attestation._fixed_dispatch_journal_path(operation_ref),
    )
    if scenario == "committed":
        with attestation.install_benchmark_dispatch_attestor(
            dispatch_context=context
        ):
            attestation.attest_benchmark_provider_dispatch(
                provider="qwen",
                operation_ref=context["operation_ref"],
                window_binding=context["window_binding"],
                provider_runtime={"provider": "qwen"},
            )
    context_refs = {
        "qwen": attestation.compose_benchmark_dispatch_context_ref(context=context)
    }
    if scenario == "missing_context":
        context_refs = {}
    elif scenario == "malformed_context":
        context_refs["qwen"]["content_sha256"] = "0" * 64
    worker = {
        "run_id": "run-other" if scenario == "run_mismatch" else "run-h1",
        "stage": (
            "stage-other"
            if scenario == "stage_mismatch"
            else "screen_understanding"
        ),
        "operation_id": "operation-h1",
        "worker_id": "worker-h1",
        "model_request_id": "request-h1",
        "payload_sha256": "1" * 64,
        "task_kind": (
            "panel_learning_hybrid_omni_discovery"
            if scenario == "non_qwen"
            else "panel_learning_hybrid_qwen_binding"
        ),
        "status": "failed" if scenario == "not_completed" else "completed",
        "runtime_attached": scenario == "runtime_attached",
        "result_available": scenario != "result_unavailable",
        "result_adopted": scenario == "adopted",
    }
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        workflow_service,
        "_project_benchmark_v2_hybrid_expired_failure_cleanup",
        lambda **_kwargs: None,
    )

    def project_operation_ref(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"content_sha256": "4" * 64}

    monkeypatch.setattr(
        workflow_service,
        "_project_benchmark_v2_hybrid_operation_ref",
        project_operation_ref,
    )
    monkeypatch.setattr(
        incumbent,
        "compose_benchmark_v2_workflow_service_step",
        lambda **kwargs: deepcopy(dict(kwargs)),
    )

    binding = {
        "window_binding": window_binding,
        "provider_dispatch_context_refs": context_refs,
    }
    original_binding = deepcopy(binding)
    original_worker = deepcopy(worker)
    project_root = (
        tmp_path / "other-root"
        if scenario == "journal_binding_mismatch"
        else tmp_path
    )

    def call() -> dict[str, object]:
        return workflow_service._project_benchmark_v2_hybrid_step(
            composition=SimpleNamespace(
                worker_registry=object(), project_root=project_root
            ),
            workflow_state={},
            stage_execution={
                "cancellation": {
                    "backend_compute_termination": (
                        "not_covered"
                        if scenario == "nonterminal_cleanup"
                        else "not_running"
                    ),
                    "model_service_compute_termination": "request_not_active",
                }
            },
            binding=binding,
            worker_record=worker,
            status="safe_stopped",
        )

    if scenario == "malformed_context":
        with pytest.raises(
            workflow_service.LearningWorkflowStageOperationError,
            match="Qwen predispatch cleanup context is invalid",
        ):
            call()
        assert binding == original_binding
        assert worker == original_worker
        return

    projected = call()

    assert captured["recovered_cleanup_verified"] is expected_verified
    assert projected["cleanup_refs"]["worker_cleanup_ref"] is not None
    assert projected["cleanup_refs"]["provider_cleanup_ref"] is None
    assert binding == original_binding
    assert worker == original_worker


def test_s3_qwen_zero_dispatch_cleanup_is_reused_by_service_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import workflow_service
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as attestation
    from app.learn.hybrid import benchmark_v2_incumbent_operation as incumbent
    from test_portfolio_hybrid_v1_1_benchmark_v2_dispatch_attestation import (
        _runtime_attestation,
    )

    monkeypatch.setattr(attestation, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        attestation,
        "_attest_exact_window",
        lambda value: {"content_sha256": "d" * 64},
    )
    monkeypatch.setattr(
        attestation,
        "_attest_exact_provider_runtime",
        lambda provider, value: _runtime_attestation(
            attestation,
            provider=provider,
            digit="2",
        ),
    )
    window_binding = _s3_window_binding()
    operation_context_ref = {
        "run_id": "run-h1",
        "stage": "screen_understanding",
        "operation_id": "operation-h1",
        "revision": 5,
        "window_binding_ref": deepcopy(window_binding["window_binding_ref"]),
        "capture_ref": deepcopy(window_binding["capture_ref"]),
    }
    context = attestation.compose_benchmark_dispatch_context(
        provider="qwen",
        operation_ref=operation_context_ref,
        window_binding={
            "contract_version": "test_window_binding_v1",
            "exact_hwnd": 101,
            "process_identity": {"pid": 202, "create_time_ns": 303},
            "job_name": "job-h1",
            "payload_sha256": "c" * 64,
        },
        receipt_journal_path=attestation._fixed_dispatch_journal_path(
            operation_context_ref
        ),
    )
    binding = {
        "window_binding": window_binding,
        "provider_dispatch_context_refs": {
            "qwen": attestation.compose_benchmark_dispatch_context_ref(
                context=context
            )
        },
    }
    worker = {
        "run_id": "run-h1",
        "stage": "screen_understanding",
        "operation_id": "operation-h1",
        "worker_id": "worker-h1",
        "model_request_id": "request-h1",
        "payload_sha256": "1" * 64,
        "task_kind": "panel_learning_hybrid_qwen_binding",
        "status": "completed",
        "runtime_attached": False,
        "result_available": True,
        "result_adopted": False,
    }
    stage_execution = {
        "cancellation": {
            "backend_compute_termination": "not_running",
            "model_service_compute_termination": "request_not_active",
        }
    }
    current = {"run_id": "run-h1", "revision": 7}
    supplied = {
        "mode": "hybrid_v1_1",
        "run_id": "run-h1",
        "stage": "screen_understanding",
        "operation_id": "operation-h1",
        "status": "safe_stopped",
    }

    class _Store:
        def get(self, run_id: str) -> dict[str, object]:
            assert run_id == "run-h1"
            return deepcopy(current)

    composition = workflow_service.compose_test_learning_workflow_service_unit(
        store=_Store(),
        worker_registry=object(),
        project_root=tmp_path,
    )
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        incumbent,
        "validate_benchmark_v2_workflow_service_operation_ref",
        lambda value: deepcopy(supplied),
    )
    monkeypatch.setattr(
        workflow_service,
        "_benchmark_v2_stage_execution",
        lambda *_args: deepcopy(stage_execution),
    )
    monkeypatch.setattr(
        workflow_service,
        "_benchmark_v2_hybrid_service_binding_from_execution",
        lambda _execution: deepcopy(binding),
    )
    monkeypatch.setattr(
        workflow_service,
        "_benchmark_v2_hybrid_attachment",
        lambda **_kwargs: deepcopy(worker),
    )
    monkeypatch.setattr(
        workflow_service,
        "_benchmark_v2_hybrid_service_status",
        lambda **_kwargs: "safe_stopped",
    )
    monkeypatch.setattr(
        workflow_service,
        "_project_benchmark_v2_hybrid_expired_failure_cleanup",
        lambda **_kwargs: None,
    )

    def project_operation_ref(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return deepcopy(supplied)

    monkeypatch.setattr(
        workflow_service,
        "_project_benchmark_v2_hybrid_operation_ref",
        project_operation_ref,
    )

    result = workflow_service._benchmark_v2_hybrid_service_context(
        composition=composition,
        operation_ref=supplied,
    )

    assert result[-1] == supplied
    assert captured["recovered_cleanup_verified"] is True


def test_s3_safe_stopped_completed_omni_cancel_materializes_cleanup_before_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import workflow_service

    registry = _S3Registry()
    store, composition, _service, _started = _s3_service(tmp_path, registry)
    registry.start(
        run_id="run-h1",
        stage="screen_understanding",
        operation_id="operation-h1",
        task_kind="panel_learning_hybrid_omni_discovery",
        payload=_hybrid_worker_payload(),
    )
    registry.complete_current({"outcome": "failed"})
    worker = registry.current
    assert worker is not None
    worker["result_adopted"] = True
    current = store.get("run-h1")
    materialized = _s3_provider_cleanup_ref(worker)
    worker_cleanup = {"content_sha256": "f" * 64}
    calls: list[str] = []
    try:
        monkeypatch.setattr(
            workflow_service,
            "_benchmark_v2_hybrid_terminal_prepared_context",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            workflow_service,
            "_benchmark_v2_hybrid_service_context",
            lambda **_kwargs: (
                current,
                {"safe": "stopped"},
                {"provider_dispatch_context_refs": {"omni": {}}},
                worker,
                {"stage": "screen_understanding"},
            ),
        )
        monkeypatch.setattr(
            workflow_service,
            "_benchmark_v2_hybrid_service_status",
            lambda **_kwargs: "safe_stopped",
        )

        def _materialize(**_kwargs: object) -> dict[str, object]:
            calls.append("materialize")
            return {**worker, "benchmark_provider_cleanup_ref": deepcopy(materialized)}

        monkeypatch.setattr(
            workflow_service,
            "_materialize_benchmark_v2_hybrid_completed_cleanup",
            _materialize,
        )

        def _project(**kwargs: object) -> dict[str, object]:
            calls.append("project")
            assert kwargs["worker_record"]["benchmark_provider_cleanup_ref"] == materialized
            return {
                "status": "safe_stopped",
                "cleanup_refs": {
                    "worker_cleanup_ref": worker_cleanup,
                    "provider_cleanup_ref": materialized,
                },
            }

        monkeypatch.setattr(workflow_service, "_project_benchmark_v2_hybrid_step", _project)
        result = workflow_service._cancel_benchmark_v2_hybrid_workflow_service(
            composition=composition,
            operation_ref={"run_id": "run-h1", "operation_id": "operation-h1"},
        )
        replay = workflow_service._cancel_benchmark_v2_hybrid_workflow_service(
            composition=composition,
            operation_ref={"run_id": "run-h1", "operation_id": "operation-h1"},
        )
        assert result["cleanup_refs"]["worker_cleanup_ref"] == worker_cleanup
        assert result["cleanup_refs"]["provider_cleanup_ref"] == materialized
        assert replay == result
        assert calls == ["materialize", "project", "materialize", "project"]
    finally:
        store.close()


@pytest.mark.parametrize(
    "task_kind",
    (
        "panel_learning_hybrid_fusion",
        "panel_learning_hybrid_review_projection",
    ),
)
def test_s3_safe_stopped_non_vista_cancel_does_not_materialize_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    task_kind: str,
) -> None:
    from app.learn import workflow_service

    registry = _S3Registry()
    store, composition, _service, _started = _s3_service(tmp_path, registry)
    registry.start(
        run_id="run-h1",
        stage="screen_understanding",
        operation_id="operation-h1",
        task_kind=task_kind,
        payload=_hybrid_worker_payload(),
    )
    registry.complete_current({"outcome": "failed"})
    worker = registry.current
    assert worker is not None
    worker["result_adopted"] = True
    current = store.get("run-h1")
    try:
        monkeypatch.setattr(
            workflow_service,
            "_benchmark_v2_hybrid_terminal_prepared_context",
            lambda **_kwargs: None,
        )
        monkeypatch.setattr(
            workflow_service,
            "_benchmark_v2_hybrid_service_context",
            lambda **_kwargs: (
                current,
                {"safe": "stopped"},
                {"provider_dispatch_context_refs": {}},
                worker,
                {"stage": "screen_understanding"},
            ),
        )
        monkeypatch.setattr(
            workflow_service,
            "_benchmark_v2_hybrid_service_status",
            lambda **_kwargs: "safe_stopped",
        )
        monkeypatch.setattr(
            workflow_service,
            "_materialize_benchmark_v2_hybrid_completed_cleanup",
            lambda **_kwargs: (_ for _ in ()).throw(
                AssertionError("non-VISTA cleanup materialization")
            ),
        )
        monkeypatch.setattr(
            workflow_service,
            "_project_benchmark_v2_hybrid_step",
            lambda **_kwargs: {"status": "safe_stopped"},
        )
        assert workflow_service._cancel_benchmark_v2_hybrid_workflow_service(
            composition=composition,
            operation_ref={"run_id": "run-h1", "operation_id": "operation-h1"},
        ) == {"status": "safe_stopped"}
    finally:
        store.close()


def test_s3_service_facade_has_no_handler_provider_model_or_action_imports() -> None:
    source = Path("app/learn/workflow_service.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {
        "_lookup_benchmark_v2_hybrid_workflow_service",
        "_start_benchmark_v2_hybrid_workflow_service",
        "_continue_benchmark_v2_hybrid_workflow_service",
        "_cancel_benchmark_v2_hybrid_workflow_service",
    }
    functions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in names
    }
    assert set(functions) == names
    forbidden = {"handler", "provider", "model", "action"}
    violations: list[str] = []
    for name, function in functions.items():
        for node in ast.walk(function):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                modules = [
                    alias.name
                    for alias in node.names
                ] + ([node.module] if isinstance(node, ast.ImportFrom) else [])
                if any(
                    token in str(module).casefold()
                    for module in modules
                    for token in forbidden
                ):
                    violations.append(f"{name}:import:{node.lineno}")
            if isinstance(node, ast.Call):
                called = (
                    node.func.attr
                    if isinstance(node.func, ast.Attribute)
                    else node.func.id
                    if isinstance(node.func, ast.Name)
                    else ""
                )
                if any(token in called.casefold() for token in forbidden):
                    violations.append(f"{name}:call:{called}:{node.lineno}")
    assert violations == []


def test_s3_managed_vista_failure_uses_only_actual_dispatch_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.learn import workflow_service

    failure_response = {
        "success": False,
        "message": "calibration_batch_resource_blocked",
        "data": {
            "contract_version": "learning_calibration_sequence_result_v1",
            "failure_category": "calibration_batch_resource_blocked",
            "batch_count": 0,
            "resource_preflight": {
                "resource_mode": "critical",
                "model_launch_allowed": False,
            },
            "no_live_click_authorization": True,
            "dry_run": True,
        },
        "error": {
            "code": "calibration_batch_resource_blocked",
            "details": "calibration_batch_resource_blocked",
        },
    }
    response = {
        "contract_version": "learning_hybrid_managed_stage_result_v1",
        "learning_pipeline_mode": "hybrid_v1_1",
        "task_kind": "panel_learning_calibration_sequence",
        "outcome": "failed",
        "result": failure_response,
        "orchestration": {
            "benchmark_v2_vista_batch_count": 0,
            "benchmark_v2_provider_dispatch_receipt_refs": [
                {"provider": "omni", "content_sha256": "a" * 64},
                {"provider": "qwen", "content_sha256": "b" * 64},
            ],
            "benchmark_v2_provider_dispatch_context_refs": {
                "omni": {"provider": "omni"},
                "qwen": {"provider": "qwen"},
            },
        },
    }

    captured: dict[str, object] = {}

    def validate_dispatch(**kwargs):
        captured.update(kwargs)
        return deepcopy(dict(kwargs["response"]))

    monkeypatch.setattr(
        workflow_service,
        "_validate_benchmark_v2_dispatch_response",
        validate_dispatch,
    )

    class _Composition:
        composition_kind = "production"
        benchmark_v2_worker_binding_resolver = object()

    adopted = workflow_service._validate_benchmark_v2_hybrid_adoption(
        composition=_Composition(),
        response=response,
        window_binding={},
        task_kind="panel_learning_calibration_sequence",
        provider_dispatch_context_refs={
            "omni": {"provider": "omni"},
            "qwen": {"provider": "qwen"},
        },
    )
    assert adopted == response
    assert captured["expected_provider_counts"] == {"omni": 1, "qwen": 1}


@pytest.mark.parametrize("qwen_dispatch_count", [0, 1])
def test_s3_managed_qwen_handler_failure_uses_committed_dispatch_count(
    monkeypatch: pytest.MonkeyPatch,
    qwen_dispatch_count: int,
) -> None:
    from app.learn import workflow_service

    response = {
        "contract_version": "learning_hybrid_managed_stage_result_v1",
        "learning_pipeline_mode": "hybrid_v1_1",
        "task_kind": "panel_learning_hybrid_qwen_binding",
        "outcome": "failed",
        "result": {
            "contract_version": "learning_hybrid_stage_failure_v1",
            "failure_reason": "window binding geometry or DPI drifted",
            "error_type": "ValueError",
            "error_notes": [],
            "model_lifecycle": {
                "status": "request_not_active",
                "model_service_compute_termination": "request_not_active",
            },
        },
        "orchestration": {
            "benchmark_v2_provider_dispatch_receipt_refs": [
                {"provider": "omni", "content_sha256": "a" * 64},
                *[
                    {"provider": "qwen", "content_sha256": "b" * 64}
                    for _ in range(qwen_dispatch_count)
                ],
            ],
            "benchmark_v2_provider_dispatch_context_refs": {
                "omni": {"provider": "omni"},
                **(
                    {"qwen": {"provider": "qwen"}}
                    if qwen_dispatch_count
                    else {}
                ),
            },
        },
    }
    captured: dict[str, object] = {}

    def validate_dispatch(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return deepcopy(dict(kwargs["response"]))

    monkeypatch.setattr(
        workflow_service,
        "_validate_benchmark_v2_dispatch_response",
        validate_dispatch,
    )

    class _Composition:
        composition_kind = "production"
        benchmark_v2_worker_binding_resolver = object()

    adopted = workflow_service._validate_benchmark_v2_hybrid_adoption(
        composition=_Composition(),
        response=response,
        window_binding={},
        task_kind="panel_learning_hybrid_qwen_binding",
        provider_dispatch_context_refs={
            "omni": {"provider": "omni"},
            **(
                {"qwen": {"provider": "qwen"}}
                if qwen_dispatch_count
                else {}
            ),
        },
    )
    assert adopted == response
    expected_counts = {"omni": 1}
    if qwen_dispatch_count:
        expected_counts["qwen"] = qwen_dispatch_count
    assert captured["expected_provider_counts"] == expected_counts


@pytest.mark.parametrize(
    "scenario",
    [
        "absent",
        "committed",
        "missing_issued_context",
        "cross_lineage_context",
        "response_task_kind_mismatch",
    ],
)
def test_s3_qwen_predispatch_failure_requires_durable_dispatch_absence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    from types import SimpleNamespace

    from app.learn import workflow_service
    from app.learn.hybrid import benchmark_v2_dispatch_attestation as attestation
    from test_portfolio_hybrid_v1_1_benchmark_v2_dispatch_attestation import (
        _runtime_attestation,
    )

    monkeypatch.setattr(attestation, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        attestation,
        "_attest_exact_window",
        lambda value: {"content_sha256": "d" * 64},
    )
    monkeypatch.setattr(
        attestation,
        "_attest_exact_provider_runtime",
        lambda provider, value: _runtime_attestation(
            attestation,
            provider=provider,
            digit={"omni": "1", "qwen": "2"}[provider],
        ),
    )
    binding = _s3_window_binding()
    serialized_window = {
        "contract_version": "test_window_binding_v1",
        "exact_hwnd": 101,
        "process_identity": {"pid": 202, "create_time_ns": 303},
        "job_name": "job-h1",
        "payload_sha256": "c" * 64,
    }

    def context(
        provider: str,
        revision: int,
        *,
        operation_id: str = "operation-h1",
    ) -> dict[str, object]:
        operation_ref = {
            "run_id": "run-h1",
            "stage": "screen_understanding",
            "operation_id": operation_id,
            "revision": revision,
            "window_binding_ref": deepcopy(binding["window_binding_ref"]),
            "capture_ref": deepcopy(binding["capture_ref"]),
        }
        return attestation.compose_benchmark_dispatch_context(
            provider=provider,
            operation_ref=operation_ref,
            window_binding=deepcopy(serialized_window),
            receipt_journal_path=attestation._fixed_dispatch_journal_path(
                operation_ref
            ),
        )

    omni_context = context("omni", 4)
    qwen_context = context(
        "qwen",
        5,
        operation_id=(
            "operation-other" if scenario == "cross_lineage_context" else "operation-h1"
        ),
    )
    with attestation.install_benchmark_dispatch_attestor(
        dispatch_context=omni_context
    ):
        attestation.attest_benchmark_provider_dispatch(
            provider="omni",
            operation_ref=omni_context["operation_ref"],
            window_binding=omni_context["window_binding"],
            provider_runtime={"provider": "omni"},
        )
        omni_receipts = attestation.current_benchmark_dispatch_receipt_refs()
    if scenario == "committed":
        with attestation.install_benchmark_dispatch_attestor(
            dispatch_context=qwen_context
        ):
            attestation.attest_benchmark_provider_dispatch(
                provider="qwen",
                operation_ref=qwen_context["operation_ref"],
                window_binding=qwen_context["window_binding"],
                provider_runtime={"provider": "qwen"},
            )

    omni_ref = attestation.compose_benchmark_dispatch_context_ref(
        context=omni_context
    )
    qwen_ref = attestation.compose_benchmark_dispatch_context_ref(
        context=qwen_context
    )
    response = {
        "contract_version": "learning_hybrid_managed_stage_result_v1",
        "learning_pipeline_mode": "hybrid_v1_1",
        "task_kind": "panel_learning_hybrid_qwen_binding",
        "outcome": "failed",
        "result": {
            "contract_version": "learning_hybrid_stage_failure_v1",
            "failure_reason": "window binding geometry or DPI drifted",
            "error_type": "ValueError",
            "error_notes": [],
            "model_lifecycle": {
                "status": "request_not_active",
                "model_service_compute_termination": "request_not_active",
            },
        },
        "orchestration": {
            "benchmark_v2_provider_dispatch_receipt_refs": omni_receipts,
            "benchmark_v2_provider_dispatch_context_refs": {
                "omni": omni_ref
            },
        },
    }
    if scenario == "response_task_kind_mismatch":
        response["task_kind"] = "panel_learning_hybrid_omni_discovery"
    composition = SimpleNamespace(
        composition_kind="production",
        benchmark_v2_worker_binding_resolver=object(),
        project_root=tmp_path,
    )
    issued_context_refs = {"omni": omni_ref, "qwen": qwen_ref}
    if scenario in {"missing_issued_context", "response_task_kind_mismatch"}:
        issued_context_refs.pop("qwen")
    kwargs = {
        "composition": composition,
        "response": response,
        "window_binding": binding,
        "task_kind": "panel_learning_hybrid_qwen_binding",
        "provider_dispatch_context_refs": issued_context_refs,
    }
    if scenario != "absent":
        expected_error = (
            "committed dispatch context was omitted"
            if scenario == "committed"
            else "server-issued dispatch context"
        )
        with pytest.raises(
            workflow_service.LearningWorkflowStageOperationError,
            match=expected_error,
        ):
            workflow_service._validate_benchmark_v2_hybrid_adoption(**kwargs)
    else:
        assert workflow_service._validate_benchmark_v2_hybrid_adoption(
            **kwargs
        ) == response


@pytest.mark.parametrize("vista_dispatch_count", [0, 1])
def test_s3_managed_vista_handler_failure_uses_committed_dispatch_count(
    monkeypatch: pytest.MonkeyPatch,
    vista_dispatch_count: int,
) -> None:
    from app.learn import workflow_service

    response = {
        "contract_version": "learning_hybrid_managed_stage_result_v1",
        "learning_pipeline_mode": "hybrid_v1_1",
        "task_kind": "panel_learning_calibration_sequence",
        "outcome": "failed",
        "result": {
            "contract_version": "learning_hybrid_stage_failure_v1",
            "failure_reason": "controlled VISTA failure",
            "error_type": "RuntimeError",
            "error_notes": [],
            "model_lifecycle": {
                "vista_cleanup_receipt": {"cleanup_status": "verified"}
            },
        },
        "orchestration": {
            "benchmark_v2_vista_batch_count": vista_dispatch_count,
            "benchmark_v2_provider_dispatch_receipt_refs": [
                {"provider": "omni", "content_sha256": "a" * 64},
                {"provider": "qwen", "content_sha256": "b" * 64},
                *[
                    {"provider": "vista", "content_sha256": "c" * 64}
                    for _ in range(vista_dispatch_count)
                ],
            ],
        },
    }
    captured: dict[str, object] = {}

    def validate_dispatch(**kwargs):
        captured.update(kwargs)
        return deepcopy(dict(kwargs["response"]))

    monkeypatch.setattr(
        workflow_service,
        "_validate_benchmark_v2_dispatch_response",
        validate_dispatch,
    )

    class _Composition:
        composition_kind = "production"
        benchmark_v2_worker_binding_resolver = object()

    adopted = workflow_service._validate_benchmark_v2_hybrid_adoption(
        composition=_Composition(),
        response=response,
        window_binding={},
        task_kind="panel_learning_calibration_sequence",
        provider_dispatch_context_refs={},
    )
    assert adopted == response
    expected_counts = {"omni": 1, "qwen": 1}
    if vista_dispatch_count:
        expected_counts["vista"] = vista_dispatch_count
    assert captured["expected_provider_counts"] == expected_counts


def test_s3_completed_vista_dispatch_count_remains_positive_and_exact() -> None:
    from app.learn import workflow_service

    completed = {
        "contract_version": "learning_hybrid_managed_stage_result_v1",
        "learning_pipeline_mode": "hybrid_v1_1",
        "task_kind": "panel_learning_calibration_sequence",
        "outcome": "completed",
        "result": {
            "calibration_sequence": {
                "contract_version": "learning_calibration_sequence_result_v1",
                "status": "completed",
                "batch_count": 2,
            }
        },
        "orchestration": {"benchmark_v2_vista_batch_count": 2},
    }
    assert workflow_service._benchmark_v2_expected_dispatch_counts(
        task_kind="panel_learning_calibration_sequence",
        response=completed,
    ) == {"omni": 1, "qwen": 1, "vista": 2}

    completed["orchestration"]["benchmark_v2_vista_batch_count"] = 0
    completed["result"]["calibration_sequence"]["batch_count"] = 0
    with pytest.raises(
        workflow_service.LearningWorkflowStageOperationError,
        match="batch_count",
    ):
        workflow_service._benchmark_v2_expected_dispatch_counts(
            task_kind="panel_learning_calibration_sequence",
            response=completed,
        )

    failed_after_two_batches = {
        "contract_version": "learning_hybrid_managed_stage_result_v1",
        "learning_pipeline_mode": "hybrid_v1_1",
        "task_kind": "panel_learning_calibration_sequence",
        "outcome": "failed",
        "result": {
            "success": False,
            "data": {
                "contract_version": "learning_calibration_sequence_result_v1",
                "failure_category": "calibration_worker_response_invalid",
                "batch_count": 2,
            },
        },
        "orchestration": {"benchmark_v2_vista_batch_count": 2},
    }
    assert workflow_service._benchmark_v2_expected_dispatch_counts(
        task_kind="panel_learning_calibration_sequence",
        response=failed_after_two_batches,
    ) == {"omni": 1, "qwen": 1, "vista": 2}

    failed_after_two_batches["result"]["data"]["batch_count"] = 1
    with pytest.raises(
        workflow_service.LearningWorkflowStageOperationError,
        match="failure batch_count",
    ):
        workflow_service._benchmark_v2_expected_dispatch_counts(
            task_kind="panel_learning_calibration_sequence",
            response=failed_after_two_batches,
        )
def test_vista_not_acquired_provider_cleanup_uses_typed_recovered_lease_ref() -> None:
    from app.learn import workflow_service
    from app.learn.recognition.uei.canonical import seal_immutable

    worker = {
        "run_id": "run-vista-not-acquired",
        "stage": "screen_understanding",
        "operation_id": "operation-vista-not-acquired",
        "worker_id": "worker-vista-not-acquired",
        "model_request_id": "request-vista-not-acquired",
        "payload_sha256": "1" * 64,
        "task_kind": "panel_learning_calibration_sequence",
    }
    projection = seal_immutable(
        {
            "contract_version": "benchmark_provider_cleanup_ref_v1",
            "status": "cleanup_verified",
            "outcome": "verified_not_acquired",
            "provider": "vista",
            "task_kind": "panel_learning_calibration_sequence",
            "authority_kind": "benchmark_v2_workflow_service_dispatch_cleanup",
            **{name: worker[name] for name in (
                "run_id",
                "stage",
                "operation_id",
                "worker_id",
                "model_request_id",
                "payload_sha256",
            )},
            "reservation_ref": {"content_sha256": "2" * 64},
            "acquisition_owner_ref": {"content_sha256": "3" * 64},
            "acquisition_intent_ref": {"content_sha256": "2" * 64},
            "runtime_owner_ref": {"content_sha256": "4" * 64},
            "recovered_lease_ref": {"content_sha256": "5" * 64},
        }
    )

    assert workflow_service._validate_benchmark_v2_hybrid_provider_cleanup(
        cleanup=projection,
        worker_record=worker,
    ) == projection

    confused = dict(projection)
    confused.pop("content_sha256")
    confused["cleanup_receipt_ref"] = confused.pop("recovered_lease_ref")
    with pytest.raises(workflow_service.LearningWorkflowStageOperationError):
        workflow_service._validate_benchmark_v2_hybrid_provider_cleanup(
            cleanup=seal_immutable(confused),
            worker_record=worker,
        )
    with pytest.raises(workflow_service.LearningWorkflowStageOperationError):
        workflow_service._validate_benchmark_v2_hybrid_provider_cleanup(
            cleanup=projection,
            worker_record={**worker, "task_kind": "panel_learning_hybrid_qwen_binding"},
        )

    qwen_projection = dict(projection)
    qwen_projection.pop("content_sha256")
    qwen_projection.pop("provider")
    qwen_projection.pop("task_kind")
    qwen_projection["cleanup_receipt_ref"] = qwen_projection.pop(
        "recovered_lease_ref"
    )
    qwen_projection = seal_immutable(qwen_projection)
    assert workflow_service._validate_benchmark_v2_hybrid_provider_cleanup(
        cleanup=qwen_projection,
        worker_record={**worker, "task_kind": "panel_learning_hybrid_qwen_binding"},
    ) == qwen_projection
