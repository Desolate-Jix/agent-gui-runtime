from __future__ import annotations

from app.learn.workflow_contracts import (
    LearningTaskResult,
    ModelReviewTaskInput,
    RecognitionTaskInput,
    TwoStageUnderstandingTaskInput,
)


def test_model_review_task_input_preserves_public_request_defaults() -> None:
    value = ModelReviewTaskInput.model_validate(
        {
            "two_stage_report_path": "artifacts/report.json",
            "screenshot_path": "artifacts/screen.png",
            "composite_overlay_path": "artifacts/overlay.png",
        }
    )

    assert value.model_profile_id == "learn_mode_qwen3_vl_8b"
    assert value.timeout_seconds == 240


def test_learning_task_result_is_transport_neutral() -> None:
    fields = set(LearningTaskResult.model_fields)

    assert fields == {"outcome", "payload", "failure"}
    assert "status_code" not in fields
    assert "message" not in fields
    assert "error" not in fields


def test_recognition_task_input_preserves_public_request_defaults() -> None:
    value = RecognitionTaskInput()

    assert value.app_name == "unknown_app"
    assert value.state_hint == ""
    assert value.summary == ""
    assert value.observation_evidence == {}
    assert value.crop_size == {}
    assert value.two_stage_report_path is None


def test_two_stage_understanding_input_preserves_public_request_defaults() -> None:
    value = TwoStageUnderstandingTaskInput()

    assert value.app_name == "unknown_app"
    assert value.state_hint == ""
    assert value.trace_path is None
    assert value.source_image_path is None
    assert value.observe_result == {}
    assert value.require_stage1_gate is True
    assert value.stage2_region_strategy == "partitioned"
