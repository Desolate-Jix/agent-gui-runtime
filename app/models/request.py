from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class ROIModel(BaseModel):
    """Rectangular region of interest within the bound window."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class WritePolicyModel(BaseModel):
    """Controls which persistent learning surfaces a request may update."""

    path_graph: bool = True
    element_memory: bool = False
    trace: bool = True


def _learn_fast_write_policy() -> WritePolicyModel:
    return WritePolicyModel(path_graph=True, element_memory=False, trace=True)


def _learn_deep_write_policy() -> WritePolicyModel:
    return WritePolicyModel(path_graph=True, element_memory=True, trace=True)


def _execute_write_policy() -> WritePolicyModel:
    return WritePolicyModel(path_graph=False, element_memory=True, trace=True)


class BindWindowRequest(BaseModel):
    """Request model for binding the runtime to a target window."""

    process_name: Optional[str] = None
    title: Optional[str] = None


class ResizeBoundWindowRequest(BaseModel):
    """Request model for resizing the currently bound window."""

    width: int = Field(gt=0)
    height: int = Field(gt=0)
    left: Optional[int] = None
    top: Optional[int] = None
    focus: bool = True


class OpenAppRequest(BaseModel):
    """Request model for opening an application from the runtime app catalog."""

    app_id: Optional[str] = None
    command: Optional[list[str]] = None
    url: Optional[str] = None
    process_name: Optional[str] = None
    title: Optional[str] = None
    bind_after_open: bool = True
    prefer_new_window: bool = True
    maximize_after_open: bool = True
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


class TypeTextRequest(BaseModel):
    """Request model for typing text into the currently bound window."""

    text: str = Field(min_length=1)
    x: Optional[int] = Field(default=None, ge=0)
    y: Optional[int] = Field(default=None, ge=0)
    click_before_typing: bool = False
    clear_existing: bool = False
    submit: bool = False
    restore_clipboard: bool = True
    dry_run: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScrollRequest(BaseModel):
    """Request model for scrolling the currently bound window."""

    contract_version: Optional[str] = None
    goal_id: Optional[str] = None
    task_chain_id: Optional[str] = None
    source_trace_path: Optional[str] = None
    scroll_scope: Literal["window", "page", "container"] = "window"
    target_pane: Optional[Literal["page", "results_list", "job_detail", "filter_panel", "modal", "dropdown", "unknown"]] = None
    target_container_id: Optional[str] = None
    container_bbox: Optional[ROIModel] = None
    coordinate_window_size: Optional[dict[str, int]] = None
    target_point_policy: Literal["explicit_point", "safe_interior_center"] = "safe_interior_center"
    direction: Literal["down", "up"] = "down"
    wheel_clicks: int = Field(default=4, ge=1, le=20)
    x: Optional[int] = Field(default=None, ge=0)
    y: Optional[int] = Field(default=None, ge=0)
    reason: Optional[str] = None
    missing_evidence: list[str] = Field(default_factory=list)
    expected_effect: dict[str, Any] = Field(default_factory=dict)
    scroll_history: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False
    enable_verification: bool = True


class RuntimePrepareRequest(BaseModel):
    """Request model for preparing local runtime dependencies before an agent run."""

    start_models: bool = True
    stages: list[str] = Field(default_factory=lambda: ["observe", "locate"])
    wait_until_ready: bool = False
    wait_seconds: float = Field(default=0.0, ge=0.0, le=180.0)


class ModelServerRequest(BaseModel):
    """Request model for starting or checking a local vision model profile."""

    stage: str = Field(default="locate", min_length=1)
    profile_id: Optional[str] = None
    wait_until_ready: bool = False
    wait_seconds: float = Field(default=0.0, ge=0.0, le=180.0)


class ExecuteRecognitionPlanRequest(BaseModel):
    """Request model for executing a gated recognition plan against a bound window."""

    goal: str = Field(min_length=1)
    approved_plan_id: Optional[str] = None
    learned_instruction_id: Optional[str] = None
    learning_mode: Optional[str] = None
    task: str = Field(default="click_target", min_length=1)
    app_name: Optional[str] = None
    state_hint: Optional[str] = None
    provider_mode: Optional[str] = None
    agent_mode: Literal["learn", "execute"] = "execute"
    learn_depth: Optional[Literal["fast", "deep"]] = None
    write_policy: WritePolicyModel = Field(default_factory=_execute_write_policy)
    metadata: dict[str, Any] = Field(default_factory=dict)
    top_k: int = Field(default=5, ge=1, le=20)
    image_path: Optional[str] = None
    observe_trace_path: Optional[str] = None
    capture_live: bool = True
    allow_saved_image_execution: bool = False
    enable_post_click_verification: bool = True
    max_execution_attempts: int = Field(default=2, ge=1, le=3)
    dry_run: bool = False


class AvailableActionsRequest(BaseModel):
    """Request model for path-graph-assisted Execute action discovery."""

    contract_version: Literal["available_actions_request_v1"] = "available_actions_request_v1"
    runtime_graph_path: Optional[str] = None
    runtime_path_graph: dict[str, Any] = Field(default_factory=dict)
    capture_live: bool = False
    include_screen_inventory: bool = True
    include_scroll_containers: bool = True
    current_state_id: Optional[str] = None
    screen_inventory: dict[str, Any] = Field(default_factory=dict)
    scroll_containers: dict[str, Any] | list[dict[str, Any]] | None = None
    task_context: dict[str, Any] = Field(default_factory=dict)
    safety: dict[str, Any] = Field(
        default_factory=lambda: {"forbid_final_submit": True, "allow_apply_entry": False, "allow_safe_fill": False}
    )


class ExecuteStepRequest(BaseModel):
    """Request model for executing one selected path-graph action step."""

    contract_version: Literal["execute_step_request_v1"] = "execute_step_request_v1"
    runtime_graph_path: Optional[str] = None
    runtime_path_graph: dict[str, Any] = Field(default_factory=dict)
    available_actions_trace_path: Optional[str] = None
    current_state_id: Optional[str] = None
    requested_action_id: Optional[str] = None
    approved_plan_id: Optional[str] = None
    path_graph_resolution: dict[str, Any] = Field(default_factory=dict)
    selected_action: dict[str, Any] = Field(default_factory=dict)
    input_text: Optional[str] = None
    target_point: dict[str, Any] | None = None
    clear_existing: Optional[bool] = None
    submit: Optional[bool] = None
    safety: dict[str, Any] = Field(
        default_factory=lambda: {"forbid_final_submit": True, "allow_apply_entry": False, "allow_safe_fill": False}
    )
    dry_run: bool = True
    dispatch_low_level: bool = False


class ExecuteObserveRequest(BaseModel):
    """Request model for lightweight execute-scoped state observation."""

    app_id: Optional[str] = None
    observation: dict[str, Any] = Field(default_factory=dict)
    application_flow_state: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecuteVerifyDiffRequest(BaseModel):
    """Request model for lightweight before/after screenshot diff verification."""

    before_image: str = Field(min_length=1)
    after_image: str = Field(min_length=1)
    expected_change: Optional[str] = None
    target_bbox: Optional[ROIModel] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecuteReadRegionBatchRequest(BaseModel):
    """Request model for merging already-captured ROI/OCR long-read evidence."""

    target_container_id: str = Field(min_length=1)
    target_bbox: Optional[dict[str, Any]] = None
    captures: list[dict[str, Any]] = Field(default_factory=list)
    max_captures: int = Field(default=5, ge=1, le=20)
    stop_after_no_new_content: int = Field(default=2, ge=1, le=10)
    wrong_scope_detected: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecuteFormInventoryRequest(BaseModel):
    """Request model for lightweight form field inventory generation."""

    app_id: Optional[str] = None
    application_flow_state: dict[str, Any] = Field(default_factory=dict)
    employer_question_inventory: dict[str, Any] = Field(default_factory=dict)
    application_answer_plan: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


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
    agent_mode: Literal["learn", "execute"] = "execute"
    learn_depth: Optional[Literal["fast", "deep"]] = None
    write_policy: WritePolicyModel = Field(default_factory=_execute_write_policy)
    metadata: dict[str, Any] = Field(default_factory=dict)


class VisionRecognitionPlanRequestModel(VisionAnalyzeRequestModel):
    """Request model for no-click staged recognition planning."""

    top_k: int = Field(default=5, ge=1, le=20)
    observe_trace_path: Optional[str] = None


class VisionObserveScreenRequestModel(BaseModel):
    """Request model for capturing and understanding the current bound screen."""

    task: str = Field(default="observe_screen", min_length=1)
    app_name: Optional[str] = None
    state_hint: Optional[str] = None
    provider_mode: Optional[str] = None
    agent_mode: Literal["learn", "execute"] = "learn"
    learn_depth: Literal["fast", "deep"] = "fast"
    write_policy: WritePolicyModel = Field(default_factory=_learn_fast_write_policy)
    metadata: dict[str, Any] = Field(default_factory=dict)
    capture_live: bool = True
    image_path: Optional[str] = None

    @model_validator(mode="after")
    def align_default_write_policy_with_depth(self) -> "VisionObserveScreenRequestModel":
        if self.learn_depth == "deep" and "write_policy" not in self.model_fields_set:
            self.write_policy = _learn_deep_write_policy()
        return self


class VisionLocateTargetRequestModel(BaseModel):
    """Request model for precise no-click target localization."""

    goal: str = Field(min_length=1)
    task: str = Field(default="click_target", min_length=1)
    app_name: Optional[str] = None
    state_hint: Optional[str] = None
    provider_mode: Optional[str] = None
    agent_mode: Literal["learn", "execute"] = "execute"
    learn_depth: Optional[Literal["fast", "deep"]] = None
    write_policy: WritePolicyModel = Field(default_factory=_execute_write_policy)
    metadata: dict[str, Any] = Field(default_factory=dict)
    top_k: int = Field(default=5, ge=1, le=20)
    capture_live: bool = True
    image_path: Optional[str] = None
    observe_trace_path: Optional[str] = None


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
