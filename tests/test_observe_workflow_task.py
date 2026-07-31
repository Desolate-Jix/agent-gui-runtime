from __future__ import annotations

from pathlib import Path

from app.operation.observe.contracts import (
    ObserveScreenReadResult,
    ObserveScreenTaskInput,
)


def test_run_observe_task_builds_shared_learning_result(tmp_path: Path) -> None:
    from app.learn.workflow_tasks.observe import run_observe_task

    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"fixture")

    result = run_observe_task(
        ObserveScreenTaskInput(
            app_name="sample",
            capture_live=False,
            image_path=str(image_path),
        ),
        project_root=tmp_path,
        image_source_resolver=lambda task: (str(task.image_path), None),
        screen_reader=lambda _request: ObserveScreenReadResult(
            success=True,
            message="ok",
            payload={
                "image_size": {"width": 800, "height": 600},
                "state_guess": "sample home",
                "screen_summary": "Sample home screen",
                "texts": [],
                "screen_reading": {"ui": {"elements": []}},
            },
        ),
        degraded_builder=lambda **_kwargs: {},
        image_size_builder=lambda **_kwargs: {"width": 800, "height": 600},
        trace_writer=lambda **_kwargs: "logs/traces/observe.json",
    )

    assert result.outcome == "completed"
    assert result.failure is None
    assert result.payload["contract_version"] == "screen_observation_v1"
    assert result.payload["screen_map"]["contract_version"] == "screen_map_v1"
    assert result.payload["operation_context"]["skill_id"] == "observe_screen"
    assert result.payload["trace_path"] == "logs/traces/observe.json"
    assert result.payload["agent_mode"] == "learn"
    assert result.payload["write_policy"]["trace"] is True


def test_observe_result_adapter_preserves_legacy_api_shape() -> None:
    from app.learn.workflow_task_result_adapter import (
        observe_result_to_legacy_response,
    )
    from app.operation.observe.contracts import ObserveScreenTaskResult

    response = observe_result_to_legacy_response(
        ObserveScreenTaskResult(
            outcome="completed",
            payload={"contract_version": "screen_observation_v1"},
        )
    )

    assert response == {
        "success": True,
        "message": "Screen observation completed",
        "data": {
            "result": {"contract_version": "screen_observation_v1"},
        },
        "error": None,
    }

