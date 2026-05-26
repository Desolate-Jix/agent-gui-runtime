from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ROIModel(BaseModel):
    """Rectangular region of interest within the bound window."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class BindWindowRequest(BaseModel):
    """Request model for binding the runtime to a target window."""

    process_name: Optional[str] = None
    title: Optional[str] = None


class OpenAppRequest(BaseModel):
    """Request model for opening an application from the runtime app catalog."""

    app_id: Optional[str] = None
    command: Optional[list[str]] = None
    process_name: Optional[str] = None
    title: Optional[str] = None
    bind_after_open: bool = True
    wait_seconds: float = Field(default=1.5, ge=0.0, le=10.0)


class CaptureWindowRequest(BaseModel):
    """Request model for capturing the currently bound window."""

    roi: Optional[ROIModel] = None
    save_image: bool = True


class FindTemplateRequest(BaseModel):
    """Request model for template matching within an optional ROI."""

    name: str = Field(min_length=1)
    roi: Optional[ROIModel] = None


class OCRRegionRequest(BaseModel):
    """Request model for OCR within a target ROI."""

    roi: ROIModel
    save_image: bool = True
    debug: bool = False


class ClickTemplateRequest(BaseModel):
    """Request model for clicking a matched template."""

    name: str = Field(min_length=1)
    roi: Optional[ROIModel] = None
    enable_validation: bool = True


class ClickTextRequest(BaseModel):
    """Request model for locating text via OCR and clicking it."""

    text: str = Field(min_length=1)
    roi: Optional[ROIModel] = None
    partial_match: bool = False
    enable_validation: bool = True
    max_retries: int = Field(default=3, ge=1, le=6)


class ExecuteRecognitionPlanRequest(BaseModel):
    """Request model for executing a gated recognition plan against a bound window."""

    goal: str = Field(min_length=1)
    task: str = Field(default="click_target", min_length=1)
    app_name: Optional[str] = None
    state_hint: Optional[str] = None
    provider_mode: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    top_k: int = Field(default=5, ge=1, le=20)
    image_path: Optional[str] = None
    capture_live: bool = True
    allow_saved_image_execution: bool = False
    enable_post_click_verification: bool = True
    max_execution_attempts: int = Field(default=2, ge=1, le=3)
    dry_run: bool = False


class ExecuteConfirmedPointRequest(BaseModel):
    """Execute a human-confirmed point relative to the currently bound window."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    bbox: Optional[ROIModel] = None
    label: Optional[str] = None
    source_trace_path: Optional[str] = None
    dry_run: bool = True


class WaitForSceneRequest(BaseModel):
    """Request model for waiting until a named scene is detected."""

    scene_name: str = Field(min_length=1)
    timeout: float = Field(default=3.0, gt=0)


class VisionAnalyzeRequestModel(BaseModel):
    """Request model for unified vision analysis across local/api providers."""

    image_path: str = Field(min_length=1)
    task: str = Field(default="analyze_ui", min_length=1)
    app_name: Optional[str] = None
    goal: Optional[str] = None
    state_hint: Optional[str] = None
    provider_mode: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class VisionRecognitionPlanRequestModel(VisionAnalyzeRequestModel):
    """Request model for no-click staged recognition planning."""

    top_k: int = Field(default=5, ge=1, le=20)


class VisionObserveScreenRequestModel(BaseModel):
    """Request model for capturing and understanding the current bound screen."""

    task: str = Field(default="observe_screen", min_length=1)
    app_name: Optional[str] = None
    state_hint: Optional[str] = None
    provider_mode: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    capture_live: bool = True
    image_path: Optional[str] = None


class VisionLocateTargetRequestModel(BaseModel):
    """Request model for precise no-click target localization."""

    goal: str = Field(min_length=1)
    task: str = Field(default="click_target", min_length=1)
    app_name: Optional[str] = None
    state_hint: Optional[str] = None
    provider_mode: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    top_k: int = Field(default=5, ge=1, le=20)
    capture_live: bool = True
    image_path: Optional[str] = None


class VisionReviewOverlayRequestModel(BaseModel):
    """Request model for drawing human-review overlays from a saved vision trace."""

    trace_path: str = Field(min_length=1)
    region_layer: str = Field(default="vision_provider_raw", min_length=1)
    include_regions: bool = True
    include_ocr: bool = True
    label_regions: bool = True
    label_ocr: bool = False


class VisionRecognitionPlanOverlayRequestModel(BaseModel):
    """Request model for drawing recognition-plan review overlays."""

    trace_path: str = Field(min_length=1)
    include_rejected: bool = True
    include_points: bool = True
    label_candidates: bool = True
    label_reasons: bool = True
