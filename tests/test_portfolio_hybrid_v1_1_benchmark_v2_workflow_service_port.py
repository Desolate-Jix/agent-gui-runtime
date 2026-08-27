from __future__ import annotations

from copy import deepcopy
import inspect

import pytest

from app.learn.hybrid import benchmark_v2_incumbent_operation as incumbent
from app.learn.hybrid.benchmark_v2_contracts import canonical_json_bytes, content_sha256


SHA_A = "a" * 64
SHA_B = "b" * 64


def _identity(identity: str, digest: str = SHA_A) -> dict[str, object]:
    return {"id": identity, "content_sha256": digest}


def _sealed_parent(kind: str, digest: str = SHA_A) -> dict[str, object]:
    body: dict[str, object] = {"kind": kind, "parent_sha256": digest}
    body["content_sha256"] = content_sha256(body)
    return body


def _window_binding() -> dict[str, object]:
    return incumbent.compose_benchmark_v2_workflow_window_binding(
        run_id="run-1",
        operation_id="operation-1",
        window_binding_ref=_identity("window-1"),
        capture_ref=_identity("capture-1"),
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
        lambda: service.start_incumbent_observe(
            provider_case_ref={"case_id": "case-1", "case_content_sha256": SHA_A},
            window_binding=_window_binding(),
        ),
        lambda: service.poll_incumbent_observe(operation_ref=operation_ref),
        lambda: service.adopt_and_terminalize_incumbent(
            operation_ref=operation_ref,
            worker_ref=operation_ref["worker_ref"],
        ),
        lambda: service.cancel_operation(operation_ref=operation_ref),
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
