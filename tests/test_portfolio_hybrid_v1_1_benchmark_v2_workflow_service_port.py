from __future__ import annotations

from copy import deepcopy
import inspect
from pathlib import Path
from threading import Barrier, Thread

import pytest

from app.learn.hybrid import benchmark_v2_incumbent_operation as incumbent
from app.learn.hybrid.benchmark_v2_contracts import canonical_json_bytes, content_sha256
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


def _screen_group() -> dict[str, object]:
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
        capture_bundle={"bundle_id": "capture-bundle"},
    )


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


def _reseal(document: dict[str, object]) -> dict[str, object]:
    document["content_sha256"] = content_sha256(document)
    return document


def test_canonical_service_surface_has_only_exact_keyword_inputs() -> None:
    expected = {
        "start_hybrid_operation": ("screen_group", "window_binding"),
        "continue_hybrid_operation": ("operation_ref",),
        "start_incumbent_observe": ("provider_case_ref", "window_binding"),
        "poll_incumbent_observe": ("operation_ref",),
        "adopt_and_terminalize_incumbent": ("operation_ref", "worker_ref"),
        "cancel_operation": ("operation_ref",),
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


def test_contract_skeletons_fail_closed_without_worker_or_provider_dispatch() -> None:
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
            incumbent.BenchmarkV2WorkflowServicePortUnavailableError,
            match="orchestration is unavailable before Amendment S2/S3",
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
