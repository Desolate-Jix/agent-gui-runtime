from __future__ import annotations

from typing import Any, Literal, cast

from pydantic import BaseModel, Field


LearningPipelineMode = Literal["incumbent", "hybrid_v1_1"]


def normalize_learning_pipeline_mode(value: object = "incumbent") -> LearningPipelineMode:
    normalized = str(value or "incumbent").strip()
    if normalized not in {"incumbent", "hybrid_v1_1"}:
        raise ValueError("learning_pipeline_mode must be incumbent or hybrid_v1_1")
    return cast(LearningPipelineMode, normalized)


class LearningTaskFailure(BaseModel):
    code: str = Field(min_length=1)
    details: str


class LearningTaskResult(BaseModel):
    outcome: Literal["completed", "safe_stopped", "failed"]
    payload: dict[str, Any] = Field(default_factory=dict)
    failure: LearningTaskFailure | None = None


class ModelReviewTaskInput(BaseModel):
    two_stage_report_path: str = Field(min_length=1)
    screenshot_path: str = Field(min_length=1)
    composite_overlay_path: str = Field(min_length=1)
    model_profile_id: str = "learn_mode_qwen3_vl_8b"
    timeout_seconds: int = Field(default=240, ge=30, le=900)


class RecognitionTaskInput(BaseModel):
    app_name: str = "unknown_app"
    state_hint: str = ""
    summary: str = ""
    observation_evidence: dict[str, Any] = Field(default_factory=dict)
    crop_size: dict[str, Any] = Field(default_factory=dict)
    two_stage_report_path: str | None = None


class TwoStageUnderstandingTaskInput(BaseModel):
    app_name: str = "unknown_app"
    state_hint: str = ""
    trace_path: str | None = None
    source_image_path: str | None = None
    observe_result: dict[str, Any] = Field(default_factory=dict)
    require_stage1_gate: bool = True
    stage2_region_strategy: Literal[
        "partitioned",
        "global_no_partition",
    ] = "partitioned"
