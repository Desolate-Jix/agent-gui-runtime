from __future__ import annotations

import inspect
from pathlib import Path

from PIL import Image

from app.core.runtime_artifacts import RuntimeTimer
from app.operation.observe.contracts import ObserveScreenTaskInput


def test_base_observation_returns_read_only_operation_evidence() -> None:
    from app.operation.observe.contracts import ObserveScreenReadResult
    from app.operation.observe.service import run_base_observation

    captured = {}

    def screen_reader(request):
        captured["request"] = request
        return ObserveScreenReadResult(
            success=True,
            message="Screen reading completed",
            payload={
                "image_size": {"width": 800, "height": 600},
                "state_guess": "home",
                "screen_summary": "Sample home screen",
            },
        )

    result = run_base_observation(
        ObserveScreenTaskInput(
            app_name="sample_app",
            capture_live=False,
            image_path="artifacts/screenshots/sample.png",
        ),
        image_source_resolver=lambda _task: (
            "artifacts/screenshots/sample.png",
            None,
        ),
        screen_reader=screen_reader,
        degraded_builder=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("degraded builder must not run")
        ),
        image_size_builder=lambda **_kwargs: {"width": 800, "height": 600},
    )

    assert result.outcome == "completed"
    assert result.failure is None
    assert result.payload["image_path"] == "artifacts/screenshots/sample.png"
    assert result.payload["observation"]["state_guess"] == "home"
    assert result.payload["operation_context"]["skill_id"] == "observe_screen"
    assert result.payload["operation_context"]["requires_gate"] is False
    assert result.payload["operation_trace_link"]["result_status"] == "success"
    assert captured["request"].provider_mode == "local_understanding"
    assert captured["request"].metadata["ocr_anchors"]["enabled"] is True


def test_base_observation_keeps_model_failure_explicitly_degraded() -> None:
    from app.operation.observe.contracts import ObserveScreenReadResult
    from app.operation.observe.service import run_base_observation

    result = run_base_observation(
        ObserveScreenTaskInput(
            app_name="sample_app",
            capture_live=False,
            image_path="artifacts/screenshots/sample.png",
        ),
        image_source_resolver=lambda _task: (
            "artifacts/screenshots/sample.png",
            None,
        ),
        screen_reader=lambda _request: ObserveScreenReadResult(
            success=False,
            message="Screen reading failed",
            error={"code": "screen_reading_failed", "details": "model timeout"},
            model_io={"status": "failed"},
        ),
        degraded_builder=lambda **kwargs: {
            "contract_version": "screen_observation_v1",
            "status": "degraded",
            "image_path": kwargs["image_path"],
            "degraded_reason": {
                "code": "screen_reading_failed",
                "model_io": kwargs["screen_result"].model_io,
            },
        },
        image_size_builder=lambda **_kwargs: {"width": 800, "height": 600},
    )

    assert result.outcome == "completed"
    assert result.payload["observation"]["status"] == "degraded"
    assert result.payload["observation"]["degraded_reason"]["model_io"] == {
        "status": "failed"
    }


def test_base_observation_uses_caller_timer_for_route_enrichment() -> None:
    from app.operation.observe.contracts import ObserveScreenReadResult
    from app.operation.observe.service import run_base_observation

    timer = RuntimeTimer()
    with timer.step("route_adapter"):
        result = run_base_observation(
            ObserveScreenTaskInput(
                app_name="sample_app",
                capture_live=False,
                image_path="artifacts/screenshots/sample.png",
            ),
            image_source_resolver=lambda _task: (
                "artifacts/screenshots/sample.png",
                None,
            ),
            screen_reader=lambda _request: ObserveScreenReadResult(
                success=True,
                message="Screen reading completed",
                payload={"state_guess": "home"},
            ),
            degraded_builder=lambda **_kwargs: (_ for _ in ()).throw(
                AssertionError("degraded builder must not run")
            ),
            image_size_builder=lambda **_kwargs: {
                "width": 800,
                "height": 600,
            },
            timer=timer,
        )

    step_names = [step["name"] for step in timer.to_dict()["steps"]]
    assert result.outcome == "completed"
    assert step_names == ["route_adapter", "resolve_image_source", "screen_reading"]


def test_base_observation_returns_structured_failure_for_source_error() -> None:
    from app.operation.observe.service import run_base_observation

    result = run_base_observation(
        ObserveScreenTaskInput(capture_live=False),
        image_source_resolver=lambda _task: (_ for _ in ()).throw(
            ValueError("Provide image_path or set capture_live=true")
        ),
        screen_reader=lambda _request: (_ for _ in ()).throw(
            AssertionError("screen reader must not run")
        ),
        degraded_builder=lambda **_kwargs: {},
        image_size_builder=lambda **_kwargs: {},
    )

    assert result.outcome == "failed"
    assert result.payload["timings"]["total_ms"] >= 0
    assert result.failure is not None
    assert result.failure.code == "observe_screen_failed"
    assert "Provide image_path" in result.failure.details


def test_saved_observe_image_source_does_not_capture_window(tmp_path: Path) -> None:
    from app.operation.observe.image_source import resolve_observe_image_source

    image_path = tmp_path / "saved.png"
    Image.new("RGB", (32, 24), "white").save(image_path)

    resolved, live_capture = resolve_observe_image_source(
        ObserveScreenTaskInput(
            capture_live=False,
            image_path=str(image_path),
        ),
        capture_window=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("saved source must not capture a window")
        ),
        sleep=lambda _seconds: None,
    )

    assert resolved == str(image_path)
    assert live_capture is None


def test_observe_operation_modules_do_not_import_api_or_learn() -> None:
    from app.operation.observe import image_source, service

    source = inspect.getsource(image_source) + inspect.getsource(service)

    assert "app.api" not in source
    assert "app.learn" not in source
    assert "fastapi" not in source
