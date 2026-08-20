from __future__ import annotations

import inspect

from app.api.models.request import VisionObserveScreenRequestModel


def test_observe_task_input_accepts_public_api_payload_without_transport_dependency() -> None:
    from app.operation.observe.contracts import ObserveScreenTaskInput

    api_request = VisionObserveScreenRequestModel(
        app_name="sample_app",
        state_hint="home",
        provider_mode="local_understanding",
        learn_depth="deep",
        capture_live=False,
        image_path="artifacts/screenshots/sample.png",
        metadata={"source": "contract_test"},
        operation_context={
            "capture_id": "capture:test",
            "evidence_refs": ["artifacts/screenshots/sample.png"],
        },
    )

    task = ObserveScreenTaskInput.model_validate(api_request.model_dump())

    assert task.capture_live is False
    assert task.image_path == "artifacts/screenshots/sample.png"
    assert task.learn_depth == "deep"
    assert task.write_policy.model_dump() == {
        "path_graph": True,
        "element_memory": True,
        "trace": True,
    }
    assert task.operation_context.capture_id == "capture:test"
    assert task.operation_context.evidence_refs == [
        "artifacts/screenshots/sample.png"
    ]


def test_observe_task_input_aligns_implicit_write_policy_with_learning_depth() -> None:
    from app.operation.observe.contracts import ObserveScreenTaskInput

    fast = ObserveScreenTaskInput(learn_depth="fast")
    deep = ObserveScreenTaskInput(learn_depth="deep")

    assert fast.write_policy.element_memory is False
    assert deep.write_policy.element_memory is True


def test_observe_task_result_distinguishes_failure_from_completed_payload() -> None:
    from app.operation.observe.contracts import (
        ObserveScreenTaskFailure,
        ObserveScreenTaskResult,
    )

    completed = ObserveScreenTaskResult(
        outcome="completed",
        payload={"contract_version": "screen_observation_v1"},
    )
    failed = ObserveScreenTaskResult(
        outcome="failed",
        failure=ObserveScreenTaskFailure(
            code="observe_screen_failed",
            details="source image missing",
        ),
    )

    assert completed.failure is None
    assert completed.payload["contract_version"] == "screen_observation_v1"
    assert failed.payload == {}
    assert failed.failure is not None
    assert failed.failure.code == "observe_screen_failed"


def test_observe_contract_module_has_no_api_or_learn_dependency() -> None:
    from app.operation.observe import contracts

    source = inspect.getsource(contracts)

    assert "app.api" not in source
    assert "app.learn" not in source
    assert "fastapi" not in source
