from __future__ import annotations

import base64
import hashlib
import heapq
import json
import os
import time
import urllib.error
import urllib.request
from copy import deepcopy
from pathlib import Path
from threading import Lock
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import FileResponse, PlainTextResponse, Response
from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict, Field

from app.agent.continuous_task_handoff import (
    load_continuous_task_handoff,
    start_continuous_task_resume,
)
from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore
from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore, content_sha256
from app.agent.reviewed_workflow_compiler import compile_reviewed_workflow_asset_v2
from app.agent.reviewed_workflow_replay import resolve_current_state
from app.core.runtime_artifacts import write_trace
from app.core.model_server import load_model_profiles
from app.core.model_server import model_base_url
from app.learn.draft_review import load_learning_draft_review
from app.learn.interface_workflow_review import (
    build_interface_node_review_revision,
    build_interface_workflow_review,
    delete_interface_workflow_review_candidate,
    delete_learning_evidence,
    load_interface_workflow_library_registry,
    load_interface_workflow_review_context,
    evaluate_interface_workflow_node_integrity,
    save_interface_workflow_review_candidate,
)
from app.learn.application_interface_graph import (
    save_workflow_review_as_application_assets,
)
from app.learn.agent_evidence import PersistedReviewRevision
from app.learn.assisted_template_review import (
    create_assisted_template_acceptance_suggestions,
    create_assisted_template_acceptance_simulation,
    create_assisted_template_asset_candidate,
    create_assisted_template_audited_promotion_request,
    create_assisted_template_graph_draft,
    create_assisted_template_promotion_preflight,
    create_assisted_template_review_package,
    load_assisted_template_review_package,
    save_assisted_template_review_decisions,
)
from app.learn.model_artifact_loader import load_model_learning_artifact
from app.learn.calibration_artifact import (
    LearningCalibrationArtifactError,
    create_learning_calibration_artifact,
)
from app.learn.model_trial import build_learning_model_trial
from app.learn.pathgraph_candidate import attach_detail_observe_result_to_candidate, build_pathgraph_candidate_from_review
from app.learn.scoped_capture import (
    SCOPED_CAPTURE_CONTRACT_VERSION,
    ScopedCaptureCompositionError,
    ScopedCaptureError,
    build_scoped_capture_artifact,
)
from app.learn.surface_rule_registry import build_surface_rule_registry_panel_view
from app.learn.workflow_evidence import (
    LearningWorkflowEvidenceError,
)
from app.learn.workflow_continuation import (
    LearningStageWorkerContinuationError,
)
from app.learn.workflow_runner import run_learning_workflow_readonly_tail
from app.learn.workflow_service import (
    LearningWorkflowServiceComposition,
    LearningWorkflowStageOperationError,
    adopt_guarded_learning_stage_worker_result,
    cancel_guarded_learning_workflow_stage_operation,
    continue_guarded_learning_stage_worker_result,
    compose_test_learning_workflow_service,
    finish_guarded_learning_workflow_stage_operation,
    get_production_learning_workflow_service_composition,
    heartbeat_guarded_learning_workflow_stage_operation,
    project_guarded_learning_workflow_runtime_attachment,
    recover_guarded_learning_workflow_stage_operation,
    start_guarded_learning_stage_worker,
    start_learning_workflow_stage_operation,
    status_guarded_learning_stage_worker,
    transition_learning_workflow_run,
)
from app.learn.workflow_worker import (
    HYBRID_STAGE_HANDLER_REGISTRY,
    LearningStageWorkerError,
    hybrid_registered_handler_chain_ready,
    hybrid_registered_lifecycle_status,
    learning_stage_worker_registry,
)
from app.learn.workflow_state import (
    LEARNING_WORKFLOW_STAGES,
    LearningWorkflowTransitionError,
    validate_learning_workflow_state,
)
from app.learn.workflow_contracts import (
    LearningPipelineMode,
    ModelReviewTaskInput,
    RecognitionTaskInput,
    TwoStageUnderstandingTaskInput,
)
from app.learn.workflow_task_result_adapter import (
    model_review_result_to_legacy_response,
    recognition_result_to_legacy_response,
    two_stage_result_to_legacy_response,
)
from app.learn.workflow_tasks.model_review import run_model_review_task
from app.learn.workflow_tasks.recognition import run_recognition_task
from app.learn.workflow_tasks.two_stage import run_two_stage_understanding_task
from app.learn.workflow_store import learning_workflow_run_store
from app.learn.recognition import (
    fusion_status_from_two_stage,
)
from app.api.models.response import APIResponse, ErrorModel
from scripts.report_learn_fusion_model_start_approval_packet import (
    report_learn_fusion_model_start_approval_packet,
)
from scripts.report_learn_fusion_calibration_pre_run_check import (
    report_learn_fusion_calibration_pre_run_check,
)
from scripts.report_learn_fusion_pathgraph_integration_readiness import (
    report_learn_fusion_pathgraph_integration_readiness,
)
from scripts.report_learn_fusion_current_evidence_packet import (
    report_learn_fusion_current_evidence_packet,
)
from scripts.build_learn_precise_understanding_candidate import (
    build_learn_precise_understanding_candidate,
)
from scripts.build_learn_page_detail_candidate import (
    build_learn_page_detail_candidate,
)
from scripts.build_learn_demo_scaffold import (
    build_learn_demo_scaffold,
)
from scripts.report_learning_mode_demo_goal_readiness import (
    report_learning_mode_demo_goal_readiness,
)
from app.learn.recognition.panel_review_pipeline import run_panel_learning_model_review_repair

PANEL_DIR = Path(__file__).resolve().parents[1] / "web_panel"
PANEL_INDEX = PANEL_DIR / "index.html"
ROOT_DIR = Path(__file__).resolve().parents[2]
UPLOAD_DIR = ROOT_DIR / "artifacts" / "web-panel" / "uploads"
SETTINGS_PANEL_ARTIFACT_DIR = ROOT_DIR / "artifacts" / "settings-panel"
VISION_CONFIG_PATH = ROOT_DIR / "configs" / "vision.json"
PANEL_CONFIG_PATH = ROOT_DIR / "configs" / "settings_panel.json"
SCOPED_CAPTURE_ARTIFACT_DIR = ROOT_DIR / "artifacts" / "learning-runs" / "scoped-capture"
continuous_task_memory_store = ReviewedInterfaceMemoryStore(project_root=ROOT_DIR)

router = APIRouter(tags=["panel"])
_PRODUCTION_PANEL_WORKFLOW_STORE = learning_workflow_run_store
_PRODUCTION_PANEL_WORKER_REGISTRY = learning_stage_worker_registry


def _panel_learning_workflow_service_composition(
) -> LearningWorkflowServiceComposition:
    if (
        learning_workflow_run_store is _PRODUCTION_PANEL_WORKFLOW_STORE
        and learning_stage_worker_registry is _PRODUCTION_PANEL_WORKER_REGISTRY
    ):
        return get_production_learning_workflow_service_composition()
    return compose_test_learning_workflow_service(
        store=learning_workflow_run_store,
        worker_registry=learning_stage_worker_registry,
        project_root=ROOT_DIR,
    )


def _hybrid_experimental_rollout_ready() -> bool:
    from app.learn.hybrid.contracts import load_hybrid_config

    try:
        config = load_hybrid_config(ROOT_DIR)
    except (OSError, TypeError, ValueError):
        return False
    return (
        config.get("rollout_mode") == "opt_in"
        and hybrid_registered_handler_chain_ready()
    )


def _hybrid_rollout_status() -> dict[str, Any]:
    from app.learn.hybrid.contracts import load_hybrid_config

    lifecycle = hybrid_registered_lifecycle_status()
    try:
        config_ready = load_hybrid_config(ROOT_DIR).get("rollout_mode") == "opt_in"
    except (OSError, TypeError, ValueError):
        config_ready = False
    components = {"config": config_ready, **deepcopy(lifecycle["components"])}
    ready = all(components.values())
    return {
        "contract_version": "hybrid_rollout_status_v1",
        "learning_pipeline_mode": "hybrid_v1_1",
        "ready": ready,
        "rollout": "experimental" if ready else "unavailable",
        "reason": (
            "hybrid_rollout_experimental"
            if ready
            else "hybrid_experimental_rollout_unavailable"
        ),
        "components": components,
        "incumbent_default": True,
    }


_INTERFACE_WORKFLOW_SAVE_LOCKS_GUARD = Lock()
_INTERFACE_WORKFLOW_SAVE_LOCKS: dict[str, Lock] = {}


class PanelImageUploadRequest(BaseModel):
    filename: str = Field(min_length=1)
    content_base64: str = Field(min_length=1)
    content_type: Optional[str] = None


class PanelManualBoxRequest(BaseModel):
    image_path: str = Field(min_length=1)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    label: Optional[str] = None


class PanelInterfaceAssetCropRequest(BaseModel):
    source_image_path: str = Field(min_length=1)
    asset_id: str = Field(min_length=1)
    label: Optional[str] = None
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    padding_px: int = Field(default=6, ge=0, le=80)
    context_padding_px: int = Field(default=16, ge=0, le=160)


class PanelApplyModelProfileRequest(BaseModel):
    stage: str = Field(pattern="^(observe|locate)$")
    profile_id: str = Field(min_length=1)
    timeout_seconds: int = Field(default=600, ge=1, le=1800)
    language: str = "zh-CN"
    observe_prompt: Optional[str] = None
    locate_prompt: Optional[str] = None


class PanelModelTestRequest(BaseModel):
    profile_id: str = Field(min_length=1)
    stage: str = Field(default="observe", pattern="^(observe|locate)$")
    prompt: str = Field(min_length=1)
    image_path: Optional[str] = None
    max_tokens: int = Field(default=2048, ge=1, le=8192)
    temperature: float = Field(default=0.1, ge=0.0, le=2.0)


class PanelLoadModelArtifactRequest(BaseModel):
    trial_path: str = Field(min_length=1)


class PanelLoadLearningDraftReviewRequest(BaseModel):
    source_path: str = Field(min_length=1)
    discover_related_sidecars: bool = True
    workflow_run_id: Optional[str] = None


class PanelLoadLiveSafeFillPreflightRequest(BaseModel):
    preflight_path: str = Field(min_length=1)


class PanelScopedCaptureSegmentRecord(BaseModel):
    image_path: str = Field(min_length=1)
    capture_id: Any = None
    scroll_trace_path: str | None = None
    scroll_effect: Any = None


class PanelComposeScopedLearningCaptureRequest(BaseModel):
    segment_records: list[PanelScopedCaptureSegmentRecord] = Field(min_length=1)
    roi: dict[str, Any]
    viewport: dict[str, Any]
    stop_reason: str


class PanelLoadInterfaceWorkflowReviewRequest(BaseModel):
    goal: str = ""
    application_identity: dict[str, Any] = Field(default_factory=dict)
    draft_source_paths: list[str] = Field(default_factory=list, max_length=100)
    discover_related_sidecars: bool = True
    workflow_run_ids_by_source: dict[str, str] = Field(default_factory=dict)


class PanelSaveInterfaceWorkflowReviewRequest(BaseModel):
    review: dict[str, Any] = Field(default_factory=dict)
    out_dir: Optional[str] = None


class PanelDeleteLearningEvidenceRequest(BaseModel):
    source_path: str = Field(min_length=1)


class PanelDeleteInterfaceWorkflowRequest(BaseModel):
    workflow_id: str = Field(min_length=1)


class PanelCompileReviewedWorkflowAssetRequest(BaseModel):
    """服务端解析 v1 人审流程并编译 v2 资产。"""

    model_config = ConfigDict(extra="forbid")
    application_identity_key: str = Field(min_length=1)
    workflow_id: str = Field(min_length=1)
    expected_source_workflow_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")


class PanelPublishReviewedWorkflowAssetRequest(PanelCompileReviewedWorkflowAssetRequest):
    """重新编译后以 CAS revision 发布 v2 资产。"""

    expected_registry_revision: int = Field(ge=0)


class PanelPreviewReviewedWorkflowReplayRequest(BaseModel):
    """只读地解析已发布资产的当前状态；绝不捕获或执行。"""

    model_config = ConfigDict(extra="forbid")
    asset_id: str = Field(min_length=1)
    expected_content_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    current_observation: dict[str, Any] | None = None


class PanelCreateLearningDemoGoalReadinessRequest(BaseModel):
    scaffold_path: str = Field(min_length=1)
    out_dir: Optional[str] = None


class PanelSaveLearningDraftReviewRequest(BaseModel):
    source_path: str = Field(min_length=1)
    review_patch: dict[str, Any] = Field(default_factory=dict)


class PanelResumeContinuousTaskRequest(BaseModel):
    run_dir: str = Field(min_length=1)
    base_url: str = Field(min_length=1)


class PanelRunLearningModelTrialRequest(BaseModel):
    image_path: str = Field(min_length=1)
    app_name: str = "unknown_app"
    state_hint: str = ""
    goal: str = "learn a reusable UI workflow template from this screen"
    validation_mode: str = Field(default="standard", pattern="^(strict_blind|standard)$")
    max_attempts: int = Field(default=2, ge=1, le=5)
    max_output_tokens: int = Field(default=3072, ge=256, le=8192)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    timeout_seconds: int = Field(default=180, ge=1, le=600)
    learning_image_max_edge: int = Field(default=768, ge=128, le=1280)
    allow_fast_profile_fallback: bool = False
    observation_evidence: dict[str, Any] = Field(default_factory=dict)


class PanelRunLearningRecognitionTrialRequest(BaseModel):
    app_name: str = "unknown_app"
    state_hint: str = ""
    summary: str = ""
    observation_evidence: dict[str, Any] = Field(default_factory=dict)
    crop_size: dict[str, Any] = Field(default_factory=dict)
    two_stage_report_path: Optional[str] = None


class PanelRunLearningTwoStageUnderstandingRequest(BaseModel):
    app_name: str = "unknown_app"
    state_hint: str = ""
    trace_path: Optional[str] = None
    source_image_path: Optional[str] = None
    observe_result: dict[str, Any] = Field(default_factory=dict)
    require_stage1_gate: bool = True
    stage2_region_strategy: str = Field(default="partitioned", pattern="^(partitioned|global_no_partition)$")


class PanelRunLearningModelReviewRepairRequest(BaseModel):
    two_stage_report_path: str = Field(min_length=1)
    screenshot_path: str = Field(min_length=1)
    composite_overlay_path: str = Field(min_length=1)
    model_profile_id: str = "learn_mode_qwen3_vl_8b"
    timeout_seconds: int = Field(default=240, ge=30, le=900)


class PanelTransitionLearningWorkflowStateRequest(BaseModel):
    run_id: str = Field(min_length=1)
    expected_revision: int = Field(default=0, ge=0)
    stage: str = Field(
        pattern=(
            "^(bind_capture|screen_understanding|numbered_map|precise_calibration|"
            "review_repair|fusion|page_details|pathgraph_draft|complete)$"
        )
    )
    outcome: str = Field(pattern="^(running|completed|failed|safe_stopped)$")
    reason: str = ""
    evidence_refs: dict[str, Any] = Field(default_factory=dict)


class PanelStartLearningWorkflowStageOperationRequest(BaseModel):
    run_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    stage: str = Field(
        pattern=(
            "^(screen_understanding|numbered_map|precise_calibration|"
            "review_repair|fusion)$"
        )
    )
    reason: str = ""
    lease_seconds: int = Field(default=600, ge=30, le=1800)
    learning_pipeline_mode: LearningPipelineMode = "incumbent"


class PanelFinishLearningWorkflowStageOperationRequest(BaseModel):
    run_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    stage: str = Field(
        pattern=(
            "^(screen_understanding|numbered_map|precise_calibration|"
            "review_repair|fusion)$"
        )
    )
    operation_id: str = Field(min_length=1)
    outcome: str = Field(pattern="^(completed|failed|safe_stopped)$")
    reason: str = ""
    evidence_refs: dict[str, Any] = Field(default_factory=dict)


class PanelHeartbeatLearningWorkflowStageOperationRequest(BaseModel):
    run_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    stage: str = Field(
        pattern=(
            "^(screen_understanding|numbered_map|precise_calibration|"
            "review_repair|fusion)$"
        )
    )
    operation_id: str = Field(min_length=1)
    lease_seconds: int = Field(default=600, ge=30, le=1800)


class PanelCancelLearningWorkflowStageOperationRequest(BaseModel):
    run_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    stage: str = Field(
        pattern=(
            "^(screen_understanding|numbered_map|precise_calibration|"
            "review_repair|fusion)$"
        )
    )
    operation_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class PanelStartLearningStageWorkerRequest(BaseModel):
    run_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    stage: str = Field(
        pattern="^(screen_understanding|numbered_map|precise_calibration|review_repair|fusion)$"
    )
    operation_id: str = Field(min_length=1)
    task_kind: str = Field(
        pattern=(
            "^(panel_learning_recognition_trial|"
            "panel_learning_two_stage_understanding|"
            "panel_learning_model_review_repair|vision_observe_screen|"
            "panel_learning_calibration_sequence|"
            "panel_learning_hybrid_omni_discovery|"
            "panel_learning_hybrid_qwen_binding|"
            "panel_learning_hybrid_fusion|"
            "panel_learning_hybrid_review_projection|vision_locate_target)$"
        )
    )
    payload: dict[str, Any] = Field(default_factory=dict)


class PanelAdoptLearningStageWorkerResultRequest(BaseModel):
    run_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    stage: str = Field(
        pattern="^(screen_understanding|numbered_map|precise_calibration|review_repair|fusion)$"
    )
    operation_id: str = Field(min_length=1)
    worker_id: str = Field(min_length=1)


class PanelContinueLearningStageWorkerResultRequest(BaseModel):
    run_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    stage: str = Field(
        pattern="^(screen_understanding|numbered_map|precise_calibration|review_repair|fusion)$"
    )
    operation_id: str = Field(min_length=1)
    worker_id: str = Field(min_length=1)


class PanelRecoverLearningWorkflowStageOperationRequest(BaseModel):
    run_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)


class PanelSaveLearningCalibrationResultRequest(BaseModel):
    run_id: str = Field(min_length=1)
    trace_path: str = Field(min_length=1)
    source_image_path: str = Field(min_length=1)
    numbering_report_path: str = Field(min_length=1)
    overlay_path: str = Field(min_length=1)


class PanelRunLearningWorkflowReadonlyTailRequest(BaseModel):
    run_id: str = Field(min_length=1)
    expected_revision: int = Field(ge=0)
    source_path: str = Field(min_length=1)
    out_dir: Optional[str] = None


class PanelGeneratePathGraphCandidateRequest(BaseModel):
    source_path: str = Field(min_length=1)
    review_patch: dict[str, Any] = Field(default_factory=dict)


class PanelAttachDetailObserveResultRequest(BaseModel):
    candidate_path: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    detail_source_path: str = Field(min_length=1)


class PanelAssistedTemplateReviewPackageRequest(BaseModel):
    candidate_path: str = Field(min_length=1)
    review_decision: str = "prepare_for_review"
    reviewer_note: str = ""


class PanelLoadAssistedTemplateReviewPackageRequest(BaseModel):
    package_path: str = Field(min_length=1)


class PanelSaveAssistedTemplateReviewDecisionsRequest(BaseModel):
    package_path: str = Field(min_length=1)
    decisions: list[dict[str, Any]] = Field(default_factory=list)
    overall_decision: str = "needs_changes"
    reviewer_note: str = ""


class PanelCreateAssistedTemplateAssetCandidateRequest(BaseModel):
    package_path: str = Field(min_length=1)
    review_record_path: Optional[str] = None


class PanelCreateAssistedTemplateGraphDraftRequest(BaseModel):
    asset_candidate_path: str = Field(min_length=1)


class PanelCreateAssistedTemplateAcceptanceSuggestionsRequest(BaseModel):
    package_path: str = Field(min_length=1)


class PanelCreateAssistedTemplateAcceptanceSimulationRequest(BaseModel):
    package_path: str = Field(min_length=1)


class PanelCreateAssistedTemplatePromotionPreflightRequest(BaseModel):
    package_path: str = Field(min_length=1)


class PanelCreateAssistedTemplateAuditedPromotionRequestRequest(BaseModel):
    package_path: str = Field(min_length=1)


class PanelCreateModelStartApprovalPacketRequest(BaseModel):
    candidate_path: Optional[str] = None
    runbook_path: Optional[str] = None
    preflight_report_path: Optional[str] = None
    demo_readiness_report_path: Optional[str] = None
    out_dir: Optional[str] = None


class PanelCreateCalibrationPreRunCheckRequest(BaseModel):
    candidate_path: Optional[str] = None
    approval_packet_path: Optional[str] = None
    out_dir: Optional[str] = None


class PanelCreatePathgraphIntegrationReadinessRequest(BaseModel):
    candidate_path: str = Field(min_length=1)
    out_dir: Optional[str] = None


class PanelCreateCurrentEvidencePacketRequest(BaseModel):
    source_path: str = Field(min_length=1)
    out_dir: Optional[str] = None


class PanelCreatePreciseUnderstandingCandidateRequest(BaseModel):
    source_path: str = Field(min_length=1)
    out_dir: Optional[str] = None


class PanelCreatePageDetailCandidateRequest(BaseModel):
    source_path: str = Field(min_length=1)
    out_dir: Optional[str] = None


class PanelCreateLearningDemoScaffoldRequest(BaseModel):
    source_path: str = Field(min_length=1)
    out_dir: Optional[str] = None


@router.get("/panel", include_in_schema=False)
def web_panel() -> FileResponse:
    """Serve the browser-based local test panel."""
    response = FileResponse(PANEL_INDEX, media_type="text/html; charset=utf-8")
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@router.get("/panel/file", include_in_schema=False)
def panel_file(path: str) -> Response:
    """Serve a local artifact/log image path for browser-panel preview."""
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = ROOT_DIR / resolved
    resolved = resolved.resolve()
    allowed_roots = [(ROOT_DIR / "artifacts").resolve(), (ROOT_DIR / "logs").resolve()]
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        return PlainTextResponse("Not found", status_code=404)
    if not resolved.exists() or not resolved.is_file():
        return PlainTextResponse("Not found", status_code=404)
    response = FileResponse(resolved)
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@router.post("/panel/compose_scoped_learning_capture", response_model=APIResponse)
def compose_scoped_learning_capture_endpoint(
    request: PanelComposeScopedLearningCaptureRequest,
) -> APIResponse:
    """组合已捕获的受限区域片段，不触发实时运行时操作。"""

    try:
        segment_records = _resolve_scoped_capture_segment_records(request.segment_records)
    except (FileNotFoundError, OSError, TypeError, ValueError) as exc:
        return APIResponse(
            success=False,
            message="Scoped capture paths are not managed artifacts",
            data=None,
            error=ErrorModel(code="invalid_scoped_capture_path", details=str(exc)),
        )

    try:
        manifest = build_scoped_capture_artifact(
            segment_records=segment_records,
            output_dir=SCOPED_CAPTURE_ARTIFACT_DIR / uuid4().hex,
            roi=request.roi,
            viewport=request.viewport,
            stop_reason=request.stop_reason,
        )
        composite_path = Path(manifest["composite_path"])
        manifest_path = Path(manifest["manifest_path"])
        if not composite_path.is_file() or not manifest_path.is_file():
            raise RuntimeError("scoped capture artifact was not published")
    except ScopedCaptureError as exc:
        return APIResponse(
            success=False,
            message="Scoped capture input is invalid",
            data=None,
            error=ErrorModel(code="invalid_scoped_capture_input", details=str(exc)),
        )
    except ScopedCaptureCompositionError as exc:
        return APIResponse(
            success=False,
            message="Scoped capture composition failed",
            data=None,
            error=ErrorModel(code="scoped_capture_composition_failed", details=str(exc)),
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Scoped capture composition failed",
            data=None,
            error=ErrorModel(code="scoped_capture_composition_failed", details=str(exc)),
        )

    data = dict(manifest)
    data.update(
        {
            "capture_contract_version": SCOPED_CAPTURE_CONTRACT_VERSION,
            "capture_mode": "scoped_long",
            "artifact_is_authorization": False,
            "historical_coordinates_are_priors": True,
            "runtime_execution_allowed": False,
            "scroll_executed_by_this_route": False,
        }
    )
    return APIResponse(
        success=True,
        message="Scoped learning capture composed",
        data=data,
        error=None,
    )


@router.post("/panel/save_learning_calibration_result", response_model=APIResponse)
def save_learning_calibration_result_endpoint(
    request: PanelSaveLearningCalibrationResultRequest,
) -> APIResponse:
    """保存绑定当前截图和编号报告的只读精准校准结果。"""

    try:
        result = create_learning_calibration_artifact(
            run_id=request.run_id,
            trace_path=request.trace_path,
            source_image_path=request.source_image_path,
            numbering_report_path=request.numbering_report_path,
            overlay_path=request.overlay_path,
            project_root=ROOT_DIR,
        )
        return APIResponse(
            success=True,
            message="Learning calibration result saved",
            data=result,
            error=None,
        )
    except LearningCalibrationArtifactError as exc:
        return APIResponse(
            success=False,
            message="Learning calibration result rejected",
            data=None,
            error=ErrorModel(
                code="learning_calibration_result_invalid",
                details=str(exc),
            ),
        )


@router.post("/panel/transition_learning_workflow_state", response_model=APIResponse)
def transition_learning_workflow_state_endpoint(
    request: PanelTransitionLearningWorkflowStateRequest,
) -> APIResponse:
    """由服务端状态源校验学习流程阶段和 revision。"""

    managed_stages = {
        "screen_understanding",
        "numbered_map",
        "precise_calibration",
        "review_repair",
        "fusion",
    }
    managed_transition_is_reachable = False
    if request.stage in managed_stages:
        try:
            current = learning_workflow_run_store.get(request.run_id)
        except LearningWorkflowTransitionError:
            current = None
        if (
            isinstance(current, dict)
            and current.get("revision") == request.expected_revision
        ):
            current_stage = str(current.get("current_stage") or "")
            current_stage_record = current.get("stages", {}).get(current_stage, {})
            if (
                current_stage == request.stage
                and current_stage_record.get("status") == "running"
                and request.outcome in {"completed", "failed", "safe_stopped"}
            ):
                managed_transition_is_reachable = True
            elif current_stage in LEARNING_WORKFLOW_STAGES:
                current_index = LEARNING_WORKFLOW_STAGES.index(current_stage)
                target_index = LEARNING_WORKFLOW_STAGES.index(request.stage)
                managed_transition_is_reachable = (
                    target_index == current_index + 1
                    and current_stage_record.get("status") == "completed"
                    and request.outcome == "running"
                )
    if managed_transition_is_reachable:
        return APIResponse(
            success=False,
            message=f"{request.stage} must use a managed workflow stage operation",
            data=None,
            error=ErrorModel(
                code="learning_workflow_stage_operation_required",
                details=(
                    "Use /panel/start_learning_workflow_stage_operation and "
                    "/panel/finish_learning_workflow_stage_operation"
                ),
            ),
        )
    try:
        workflow_state = transition_learning_workflow_run(
            store=learning_workflow_run_store,
            project_root=ROOT_DIR,
            run_id=request.run_id,
            expected_revision=request.expected_revision,
            stage=request.stage,
            outcome=request.outcome,
            reason=request.reason,
            evidence_refs=request.evidence_refs,
        )
        return APIResponse(
            success=True,
            message="Learning workflow state transitioned",
            data={"workflow_state": workflow_state},
            error=None,
        )
    except LearningWorkflowEvidenceError as exc:
        return APIResponse(
            success=False,
            message="Learning workflow evidence rejected",
            data=None,
            error=ErrorModel(
                code="learning_workflow_evidence_invalid",
                details=str(exc),
            ),
        )
    except LearningWorkflowTransitionError as exc:
        return APIResponse(
            success=False,
            message="Learning workflow state transition rejected",
            data=None,
            error=ErrorModel(
                code="learning_workflow_transition_invalid",
                details=str(exc),
            ),
        )


@router.get("/panel/hybrid_rollout_status", response_model=APIResponse)
def hybrid_rollout_status_endpoint() -> APIResponse:
    """返回唯一后端派生的 Hybrid experimental readiness。"""
    return APIResponse(
        success=True,
        message="Hybrid rollout status",
        data=_hybrid_rollout_status(),
        error=None,
    )


@router.post(
    "/panel/start_learning_workflow_stage_operation",
    response_model=APIResponse,
)
def start_learning_workflow_stage_operation_endpoint(
    request: PanelStartLearningWorkflowStageOperationRequest,
) -> APIResponse:
    """签发服务端阶段租约，防止浏览器超时后遗留无主运行状态。"""

    if (
        request.learning_pipeline_mode == "hybrid_v1_1"
        and not _hybrid_experimental_rollout_ready()
    ):
        return APIResponse(
            success=False,
            message="Hybrid learning pipeline experimental rollout is unavailable",
            data=None,
            error=ErrorModel(
                code="hybrid_experimental_rollout_unavailable",
                details="hybrid_v1_1 registered lifecycle chain is incomplete",
            ),
        )

    try:
        result = start_learning_workflow_stage_operation(
            store=learning_workflow_run_store,
            project_root=ROOT_DIR,
            run_id=request.run_id,
            expected_revision=request.expected_revision,
            stage=request.stage,
            reason=request.reason,
            lease_seconds=request.lease_seconds,
            learning_pipeline_mode=request.learning_pipeline_mode,
        )
        return APIResponse(
            success=True,
            message="Learning workflow stage operation started",
            data=result,
            error=None,
        )
    except (
        LearningWorkflowStageOperationError,
        LearningWorkflowTransitionError,
    ) as exc:
        return APIResponse(
            success=False,
            message="Learning workflow stage operation start rejected",
            data=None,
            error=ErrorModel(
                code="learning_workflow_stage_operation_start_invalid",
                details=str(exc),
            ),
        )


@router.post(
    "/panel/heartbeat_learning_workflow_stage_operation",
    response_model=APIResponse,
)
def heartbeat_learning_workflow_stage_operation_endpoint(
    request: PanelHeartbeatLearningWorkflowStageOperationRequest,
) -> APIResponse:
    """续租当前阶段 operation，并保留可回放的 heartbeat 事件。"""

    try:
        result = heartbeat_guarded_learning_workflow_stage_operation(
            composition=_panel_learning_workflow_service_composition(),
            run_id=request.run_id,
            expected_revision=request.expected_revision,
            stage=request.stage,
            operation_id=request.operation_id,
            lease_seconds=request.lease_seconds,
        )
        return APIResponse(
            success=True,
            message="Learning workflow stage operation heartbeat accepted",
            data=result,
            error=None,
        )
    except (
        LearningWorkflowStageOperationError,
        LearningWorkflowTransitionError,
    ) as exc:
        return APIResponse(
            success=False,
            message="Learning workflow stage operation heartbeat rejected",
            data=None,
            error=ErrorModel(
                code="learning_workflow_stage_operation_heartbeat_invalid",
                details=str(exc),
            ),
        )


@router.post(
    "/panel/start_learning_stage_worker",
    response_model=APIResponse,
)
def start_learning_stage_worker_endpoint(
    request: PanelStartLearningStageWorkerRequest,
) -> APIResponse:
    """将当前受管 operation 的白名单任务交给隔离后端进程。"""

    hybrid_requested = (
        request.task_kind.startswith("panel_learning_hybrid_")
        or request.payload.get("learning_pipeline_mode") == "hybrid_v1_1"
    )
    if hybrid_requested and (
        not _hybrid_experimental_rollout_ready()
        or request.task_kind not in HYBRID_STAGE_HANDLER_REGISTRY
    ):
        return APIResponse(
            success=False,
            message="Hybrid learning pipeline experimental rollout is unavailable",
            data=None,
            error=ErrorModel(
                code="hybrid_experimental_rollout_unavailable",
                details="hybrid_v1_1 registered lifecycle chain is incomplete",
            ),
        )
    if (
        hybrid_requested
        and request.task_kind != "panel_learning_hybrid_omni_discovery"
    ):
        return APIResponse(
            success=False,
            message="Hybrid continuation is supervisor-owned",
            data=None,
            error=ErrorModel(
                code="hybrid_backend_continuation_required",
                details=(
                    "cleanup receipts and predecessor lineage are derived by the "
                    "active backend continuation"
                ),
            ),
        )

    try:
        worker_payload = deepcopy(request.payload)
        worker_payload.pop("_hybrid_supervisor", None)
        if hybrid_requested:
            supplied_revision = worker_payload.get("workflow_revision")
            if supplied_revision is not None and supplied_revision != request.expected_revision:
                raise LearningStageWorkerError(
                    "Hybrid caller workflow revision does not match active revision"
                )
            worker_payload["workflow_revision"] = request.expected_revision
        result = start_guarded_learning_stage_worker(
            composition=_panel_learning_workflow_service_composition(),
            run_id=request.run_id,
            expected_revision=request.expected_revision,
            stage=request.stage,
            operation_id=request.operation_id,
            task_kind=request.task_kind,
            payload=worker_payload,
        )
        return APIResponse(
            success=True,
            message="Learning stage worker started",
            data=result,
            error=None,
        )
    except (
        LearningStageWorkerError,
        LearningWorkflowStageOperationError,
        LearningWorkflowTransitionError,
    ) as exc:
        return APIResponse(
            success=False,
            message="Learning stage worker start rejected",
            data=None,
            error=ErrorModel(
                code="learning_stage_worker_start_invalid",
                details=str(exc),
            ),
        )


@router.get(
    "/panel/learning_stage_worker/{worker_id}",
    response_model=APIResponse,
)
def get_learning_stage_worker_endpoint(
    worker_id: str,
    run_id: str,
    operation_id: str,
) -> APIResponse:
    """读取属于同一 run/operation 的 worker 状态和最终 API 响应。"""

    try:
        result = status_guarded_learning_stage_worker(
            composition=_panel_learning_workflow_service_composition(),
            worker_id=worker_id,
            run_id=run_id,
            operation_id=operation_id,
        )
        return APIResponse(
            success=True,
            message="Learning stage worker status",
            data=result,
            error=None,
        )
    except LearningStageWorkerError as exc:
        return APIResponse(
            success=False,
            message="Learning stage worker status rejected",
            data=None,
            error=ErrorModel(
                code="learning_stage_worker_status_invalid",
                details=str(exc),
            ),
        )


@router.post(
    "/panel/adopt_learning_stage_worker_result",
    response_model=APIResponse,
)
def adopt_learning_stage_worker_result_endpoint(
    request: PanelAdoptLearningStageWorkerResultRequest,
) -> APIResponse:
    """接纳当前受管 operation 的完成结果；状态查询本身不暴露响应。"""

    try:
        result = adopt_guarded_learning_stage_worker_result(
            composition=_panel_learning_workflow_service_composition(),
            worker_id=request.worker_id,
            run_id=request.run_id,
            expected_revision=request.expected_revision,
            stage=request.stage,
            operation_id=request.operation_id,
        )
        return APIResponse(
            success=True,
            message="Learning stage worker result adopted",
            data=result,
            error=None,
        )
    except (
        LearningStageWorkerError,
        LearningWorkflowStageOperationError,
        LearningWorkflowTransitionError,
    ) as exc:
        return APIResponse(
            success=False,
            message="Learning stage worker result adoption rejected",
            data=None,
            error=ErrorModel(
                code="learning_stage_worker_result_adoption_invalid",
                details=str(exc),
            ),
        )


@router.post(
    "/panel/continue_learning_stage_worker_result",
    response_model=APIResponse,
)
def continue_learning_stage_worker_result_endpoint(
    request: PanelContinueLearningStageWorkerResultRequest,
) -> APIResponse:
    """由后端解释已接纳结果，必要时完成对应阶段。"""

    try:
        result = continue_guarded_learning_stage_worker_result(
            composition=_panel_learning_workflow_service_composition(),
            run_id=request.run_id,
            expected_revision=request.expected_revision,
            stage=request.stage,
            operation_id=request.operation_id,
            worker_id=request.worker_id,
        )
        return APIResponse(
            success=True,
            message="Learning stage worker result continued",
            data=result,
            error=None,
        )
    except (
        LearningStageWorkerContinuationError,
        LearningStageWorkerError,
        LearningWorkflowEvidenceError,
        LearningWorkflowStageOperationError,
        LearningWorkflowTransitionError,
    ) as exc:
        return APIResponse(
            success=False,
            message="Learning stage worker result continuation rejected",
            data=None,
            error=ErrorModel(
                code="learning_stage_worker_result_continuation_invalid",
                details=str(exc),
            ),
        )


@router.post(
    "/panel/cancel_learning_workflow_stage_operation",
    response_model=APIResponse,
)
def cancel_learning_workflow_stage_operation_endpoint(
    request: PanelCancelLearningWorkflowStageOperationRequest,
) -> APIResponse:
    """安全停止当前受管阶段；后端计算终止能力单独报告。"""

    try:
        result = cancel_guarded_learning_workflow_stage_operation(
            composition=_panel_learning_workflow_service_composition(),
            run_id=request.run_id,
            expected_revision=request.expected_revision,
            stage=request.stage,
            operation_id=request.operation_id,
            reason=request.reason,
        )
        return APIResponse(
            success=True,
            message="Learning workflow stage operation cancelled",
            data=result,
            error=None,
        )
    except (
        LearningStageWorkerError,
        LearningWorkflowStageOperationError,
        LearningWorkflowTransitionError,
    ) as exc:
        return APIResponse(
            success=False,
            message="Learning workflow stage operation cancellation rejected",
            data=None,
            error=ErrorModel(
                code="learning_workflow_stage_operation_cancel_invalid",
                details=str(exc),
            ),
        )


@router.post(
    "/panel/finish_learning_workflow_stage_operation",
    response_model=APIResponse,
)
def finish_learning_workflow_stage_operation_endpoint(
    request: PanelFinishLearningWorkflowStageOperationRequest,
) -> APIResponse:
    """只接受当前租约持有者提交的阶段完成或失败结果。"""

    try:
        result = finish_guarded_learning_workflow_stage_operation(
            composition=_panel_learning_workflow_service_composition(),
            run_id=request.run_id,
            expected_revision=request.expected_revision,
            stage=request.stage,
            operation_id=request.operation_id,
            outcome=request.outcome,
            reason=request.reason,
            evidence_refs=request.evidence_refs,
        )
        return APIResponse(
            success=True,
            message="Learning workflow stage operation finished",
            data=result,
            error=None,
        )
    except LearningWorkflowEvidenceError as exc:
        return APIResponse(
            success=False,
            message="Learning workflow stage operation evidence rejected",
            data=None,
            error=ErrorModel(
                code="learning_workflow_evidence_invalid",
                details=str(exc),
            ),
        )
    except (
        LearningWorkflowStageOperationError,
        LearningWorkflowTransitionError,
    ) as exc:
        return APIResponse(
            success=False,
            message="Learning workflow stage operation finish rejected",
            data=None,
            error=ErrorModel(
                code="learning_workflow_stage_operation_finish_invalid",
                details=str(exc),
            ),
        )


@router.post(
    "/panel/recover_learning_workflow_stage_operation",
    response_model=APIResponse,
)
def recover_learning_workflow_stage_operation_endpoint(
    request: PanelRecoverLearningWorkflowStageOperationRequest,
) -> APIResponse:
    """刷新面板时终止已过期租约，不把仍有效或旧版阶段误判为失败。"""

    try:
        result = recover_guarded_learning_workflow_stage_operation(
            composition=_panel_learning_workflow_service_composition(),
            run_id=request.run_id,
            expected_revision=request.expected_revision,
        )
        return APIResponse(
            success=True,
            message="Learning workflow stage operation recovery checked",
            data=result,
            error=None,
        )
    except (
        LearningWorkflowStageOperationError,
        LearningWorkflowTransitionError,
    ) as exc:
        return APIResponse(
            success=False,
            message="Learning workflow stage operation recovery rejected",
            data=None,
            error=ErrorModel(
                code="learning_workflow_stage_operation_recovery_invalid",
                details=str(exc),
            ),
        )


@router.post(
    "/panel/run_learning_workflow_readonly_tail",
    response_model=APIResponse,
)
def run_learning_workflow_readonly_tail_endpoint(
    request: PanelRunLearningWorkflowReadonlyTailRequest,
) -> APIResponse:
    """由后端执行页面详情、只读 PathGraph 和完成阶段。"""

    try:
        result = run_learning_workflow_readonly_tail(
            run_id=request.run_id,
            expected_revision=request.expected_revision,
            source_path=request.source_path,
            out_dir=request.out_dir,
            project_root=ROOT_DIR,
            store=learning_workflow_run_store,
            page_detail_builder=build_learn_page_detail_candidate,
            scaffold_builder=build_learn_demo_scaffold,
        )
        result["trace_path"] = write_trace(
            category="panel",
            operation="run-learning-workflow-readonly-tail",
            payload={
                "success": result["success"],
                "request": request.model_dump(),
                "result": result,
            },
            name_hint=request.run_id,
        )
        if result["success"] is True:
            return APIResponse(
                success=True,
                message="Learning workflow read-only tail completed",
                data=result,
                error=None,
            )
        return APIResponse(
            success=False,
            message="Learning workflow read-only tail failed",
            data=result,
            error=ErrorModel(
                code="learning_workflow_readonly_tail_failed",
                details=str(result.get("error") or "read-only tail failed"),
            ),
        )
    except LearningWorkflowEvidenceError as exc:
        return APIResponse(
            success=False,
            message="Learning workflow read-only tail evidence rejected",
            data=None,
            error=ErrorModel(
                code="learning_workflow_evidence_invalid",
                details=str(exc),
            ),
        )
    except LearningWorkflowTransitionError as exc:
        return APIResponse(
            success=False,
            message="Learning workflow read-only tail transition rejected",
            data=None,
            error=ErrorModel(
                code="learning_workflow_transition_invalid",
                details=str(exc),
            ),
        )
    except ValueError as exc:
        return APIResponse(
            success=False,
            message="Learning workflow read-only tail request rejected",
            data=None,
            error=ErrorModel(
                code="learning_workflow_readonly_tail_invalid",
                details=str(exc),
            ),
        )


@router.get("/panel/learning_workflow_state/{run_id}", response_model=APIResponse)
def get_learning_workflow_state_endpoint(run_id: str) -> APIResponse:
    """按 run_id 恢复服务端保存的学习流程状态。"""

    try:
        composition = _panel_learning_workflow_service_composition()
        workflow_state = composition.store.get(run_id)
        runtime_attachment = project_guarded_learning_workflow_runtime_attachment(
            composition=composition,
            workflow_state=workflow_state,
        )
        return APIResponse(
            success=True,
            message="Learning workflow state recovered",
            data={
                "workflow_state": workflow_state,
                "runtime_attachment": runtime_attachment,
            },
            error=None,
        )
    except LearningWorkflowTransitionError as exc:
        return APIResponse(
            success=False,
            message="Learning workflow state not found",
            data=None,
            error=ErrorModel(
                code="learning_workflow_run_not_found",
                details=str(exc),
            ),
        )


@router.post("/panel/load_model_artifact", response_model=APIResponse)
def load_model_artifact(request: PanelLoadModelArtifactRequest) -> APIResponse:
    """Load a model learning product as read-only derived replay artifacts."""
    try:
        result = load_model_learning_artifact(request.trial_path, project_root=ROOT_DIR)
        trace_path = write_trace(
            category="panel",
            operation="load_model_artifact",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint=result.get("summary", {}).get("app_id") or "model_artifact",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="Model artifact loaded", data=result, error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Model artifact load failed",
            data=None,
            error=ErrorModel(code="model_artifact_load_failed", details=str(exc)),
        )


def _authoritative_hybrid_workflow_expectations(
    workflow_run_id: str | None,
    *,
    source_path: str,
) -> tuple[str | None, int | None, dict[str, str] | None]:
    """仅从服务端工作流存储恢复 Hybrid 新鲜度与来源绑定。"""

    normalized_run_id = str(workflow_run_id or "").strip()
    if not normalized_run_id:
        return None, None, None
    try:
        state = validate_learning_workflow_state(
            learning_workflow_run_store.get(normalized_run_id)
        )
    except (LearningWorkflowTransitionError, TypeError, ValueError):
        return None, None, None
    revision = state.get("revision")
    if (
        state.get("run_id") != normalized_run_id
        or isinstance(revision, bool)
        or not isinstance(revision, int)
        or revision < 0
    ):
        return None, None, None
    try:
        resolved_sources = _authoritative_hybrid_source_binding_paths(source_path)
    except (OSError, TypeError, ValueError):
        return None, None, None
    source_keys = {
        "trial_path",
        "source_path",
        "original_draft_path",
        "review_path",
        "scaffold_path",
    }
    source_bound = False
    bound_source_path: Path | None = None
    for event in state.get("events", []):
        refs = event.get("evidence_refs") if isinstance(event, dict) else None
        if not isinstance(refs, dict):
            continue
        for key in source_keys:
            evidence_path = refs.get(key)
            if not isinstance(evidence_path, str) or not evidence_path.strip():
                continue
            try:
                resolved_evidence = _resolve_panel_artifact_file(evidence_path)
                source_bound = resolved_evidence in resolved_sources
            except (OSError, TypeError, ValueError):
                continue
            if source_bound:
                bound_source_path = resolved_evidence
                break
        if source_bound:
            break
    if not source_bound:
        return None, None, None
    lineage_ref = _authoritative_hybrid_capture_lineage_from_source(
        str(bound_source_path)
    )
    if lineage_ref is None:
        return None, None, None
    managed_present, managed_revision, managed_lineage_ref = (
        _authoritative_managed_hybrid_trial_expectations(
            state=state,
            trial_path=bound_source_path,
            capture_lineage_ref=lineage_ref,
        )
    )
    if managed_present:
        if managed_revision is None or managed_lineage_ref is None:
            return None, None, None
        return str(state["run_id"]), managed_revision, managed_lineage_ref
    return str(state["run_id"]), revision, lineage_ref


def _authoritative_managed_hybrid_trial_expectations(
    *,
    state: dict[str, Any],
    trial_path: Path,
    capture_lineage_ref: dict[str, str],
) -> tuple[bool, int | None, dict[str, str] | None]:
    """从服务端绑定的 managed trial 恢复生成投影时的操作版本。"""

    resolved_trial = trial_path.resolve()
    managed_completions: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    for event in state.get("events", []):
        if not isinstance(event, dict):
            continue
        refs = event.get("evidence_refs")
        if not isinstance(refs, dict):
            continue
        continuation = refs.get("worker_continuation")
        event_trial = refs.get("trial_path")
        try:
            event_trial_path = (
                _resolve_panel_artifact_file(event_trial)
                if isinstance(event_trial, str) and event_trial.strip()
                else None
            )
        except (OSError, TypeError, ValueError):
            event_trial_path = None
        if (
            event_trial_path == resolved_trial
            and isinstance(continuation, dict)
            and continuation.get("task_kind")
            == "panel_learning_hybrid_review_projection"
        ):
            managed_completions.append((event, refs, continuation))
    if not managed_completions:
        return False, None, None
    if len(managed_completions) != 1:
        return True, None, None
    completion_event, completion_refs, continuation = managed_completions[0]
    if (
        completion_event.get("stage") != "screen_understanding"
        or completion_event.get("outcome") != "completed"
    ):
        return True, None, None
    try:
        payload = json.loads(trial_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return True, None, None
    if not isinstance(payload, dict) or "managed_hybrid_lineage" not in payload:
        return True, None, None
    managed = payload.get("managed_hybrid_lineage")
    expected_managed_fields = {
        "run_id",
        "workflow_revision",
        "operation_id",
        "worker_id",
        "result_sha256",
        "capture_lineage_ref",
        "hybrid_capture_bundle_ref",
    }
    if not isinstance(managed, dict) or set(managed) != expected_managed_fields:
        return True, None, None
    run_id = managed.get("run_id")
    operation_revision = managed.get("workflow_revision")
    operation_id = managed.get("operation_id")
    worker_id = managed.get("worker_id")
    result_sha256 = managed.get("result_sha256")
    if (
        run_id != state.get("run_id")
        or isinstance(operation_revision, bool)
        or not isinstance(operation_revision, int)
        or operation_revision < 0
        or not all(
            isinstance(value, str) and value
            for value in (operation_id, worker_id, result_sha256)
        )
        or len(result_sha256) != 64
        or managed.get("capture_lineage_ref") != capture_lineage_ref
        or managed.get("hybrid_capture_bundle_ref")
        != completion_refs.get("hybrid_capture_bundle_ref")
        or continuation.get("operation_id") != operation_id
        or continuation.get("worker_id") != worker_id
        or continuation.get("result_sha256") != result_sha256
    ):
        return True, None, None
    operation_bound = False
    for event in state.get("events", []):
        if not isinstance(event, dict):
            continue
        refs = event.get("evidence_refs")
        if not isinstance(refs, dict):
            continue
        execution = refs.get("stage_execution")
        if (
            event.get("revision") == operation_revision
            and isinstance(execution, dict)
            and execution.get("operation_id") == operation_id
            and execution.get("stage") == "screen_understanding"
        ):
            operation_bound = True
    if (
        not operation_bound
        or not isinstance(completion_event.get("revision"), int)
        or completion_event["revision"] <= operation_revision
    ):
        return True, None, None
    return True, operation_revision, deepcopy(capture_lineage_ref)


def _authoritative_hybrid_source_binding_paths(source_path: str) -> set[Path]:
    """只允许服务端受管审核件回溯到工作流已经记录的原始来源。"""

    resolved = _resolve_panel_artifact_file(source_path)
    paths = {resolved}
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return paths
    if not isinstance(payload, dict) or payload.get("contract_version") != "reviewed_template_candidate_v1":
        return paths
    source = payload.get("source")
    original = source.get("original_draft_path") if isinstance(source, dict) else None
    if isinstance(original, str) and original.strip():
        paths.add(_resolve_panel_artifact_file(original))
    return paths


def _authoritative_hybrid_capture_lineage_from_source(
    source_path: str,
) -> dict[str, str] | None:
    resolved = _resolve_panel_artifact_file(source_path)
    try:
        payload = json.loads(resolved.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    candidates = [payload]
    for key in ("draft", "learning_draft", "best_learning_draft"):
        child = payload.get(key)
        if isinstance(child, dict):
            candidates.append(child)
    refs: dict[tuple[str, str], dict[str, str]] = {}
    for candidate in candidates:
        values = [candidate.get("capture_lineage_ref")]
        page_details = candidate.get("page_details")
        if isinstance(page_details, dict):
            values.append(page_details.get("capture_lineage_ref"))
        for value in values:
            if (
                isinstance(value, dict)
                and set(value) == {"id", "content_sha256"}
                and all(isinstance(value.get(field), str) and value[field] for field in ("id", "content_sha256"))
            ):
                ref = {"id": value["id"], "content_sha256": value["content_sha256"]}
                refs[(ref["id"], ref["content_sha256"])] = ref
    return next(iter(refs.values())) if len(refs) == 1 else None


@router.post("/panel/load_learning_draft_review", response_model=APIResponse)
def load_learning_draft_review_endpoint(request: PanelLoadLearningDraftReviewRequest) -> APIResponse:
    """Load a model learning draft for display-only human review."""
    try:
        expected_run_id, expected_revision, expected_lineage_ref = _authoritative_hybrid_workflow_expectations(
            request.workflow_run_id,
            source_path=request.source_path,
        )
        load_options: dict[str, Any] = {
            "project_root": ROOT_DIR,
            "discover_related_sidecars": request.discover_related_sidecars,
        }
        if expected_run_id is not None and expected_revision is not None:
            load_options.update(
                expected_hybrid_run_id=expected_run_id,
                expected_hybrid_workflow_revision=expected_revision,
                expected_current_capture_lineage_ref=expected_lineage_ref,
            )
        result = load_learning_draft_review(request.source_path, **load_options)
        trace_path = write_trace(
            category="panel",
            operation="load-learning-draft-review",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint="learning_draft_review",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="Learning draft review loaded", data=result, error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Learning draft review load failed",
            data=None,
            error=ErrorModel(code="learning_draft_review_load_failed", details=str(exc)),
        )


@router.post("/panel/load_live_safe_fill_preflight", response_model=APIResponse)
def load_live_safe_fill_preflight_endpoint(
    request: PanelLoadLiveSafeFillPreflightRequest,
) -> APIResponse:
    """加载脱敏的单字段填写预检，只用于人工审查。"""

    try:
        resolved = _resolve_panel_artifact_file(request.preflight_path)
        source = json.loads(resolved.read_text(encoding="utf-8-sig"))
        if not isinstance(source, dict):
            raise ValueError("live safe-fill preflight must be a JSON object")
        if source.get("contract_version") != "seek_live_safe_fill_preflight_v1":
            raise ValueError("unsupported live safe-fill preflight contract")
        value_evidence = source.get("value_evidence") if isinstance(source.get("value_evidence"), dict) else {}
        if source.get("pii_redacted") is not True or value_evidence.get("value_redacted") is not True:
            raise ValueError("live safe-fill preflight is not redacted")
        field = source.get("field") if isinstance(source.get("field"), dict) else {}
        target = source.get("target") if isinstance(source.get("target"), dict) else {}
        verification = (
            source.get("expected_verification")
            if isinstance(source.get("expected_verification"), dict)
            else {}
        )
        safety = source.get("safety") if isinstance(source.get("safety"), dict) else {}
        evidence = source.get("evidence") if isinstance(source.get("evidence"), dict) else {}
        projection = {
            "contract_version": source["contract_version"],
            "status": source.get("status"),
            "approval_state": source.get("approval_state"),
            "interpretation": source.get("interpretation"),
            "field": {
                key: field.get(key)
                for key in ("id", "label", "field_type", "risk_class", "required")
            },
            "value_evidence": {
                key: value_evidence.get(key)
                for key in ("answer_source", "value_length", "value_hash", "value_redacted")
            },
            "target": {
                key: target.get(key)
                for key in ("state_type", "current_step")
            },
            "expected_verification": {
                key: verification.get(key)
                for key in (
                    "mode",
                    "expected_value_hash",
                    "expected_value_length",
                    "raw_value_must_not_be_recorded",
                )
            },
            "safety": {
                key: safety.get(key)
                for key in (
                    "max_fields",
                    "cover_letter_fill_allowed",
                    "continue_allowed",
                    "final_submit_allowed",
                    "artifact_is_authorization",
                )
            },
            "evidence": {
                key: evidence.get(key)
                for key in ("screenshot_path", "trace_path", "source_report_path")
            },
            "failure_reasons": list(source.get("failure_reasons") or []),
            "pii_redacted": True,
            "source_path": _relative_panel_path(resolved),
            "display_only": True,
            "artifact_is_authorization": False,
        }
        return APIResponse(
            success=True,
            message="Live safe-fill preflight loaded for review",
            data=projection,
            error=None,
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Live safe-fill preflight load failed",
            data=None,
            error=ErrorModel(code="live_safe_fill_preflight_load_failed", details=str(exc)),
        )


@router.post("/panel/load_interface_workflow_review", response_model=APIResponse)
def load_interface_workflow_review_endpoint(
    request: PanelLoadInterfaceWorkflowReviewRequest,
) -> APIResponse:
    """加载多份单界面草稿，生成只读的单软件流程审核图。"""

    loaded_reviews: list[dict[str, Any]] = []
    invalid_sources: list[dict[str, Any]] = []
    for source_path in request.draft_source_paths:
        normalized_path = str(source_path or "").strip()
        if not normalized_path:
            invalid_sources.append(
                {
                    "source_path": "",
                    "failure_category": "invalid_review_source",
                    "reason": "source path is empty",
                }
            )
            continue
        try:
            expected_run_id, expected_revision, expected_lineage_ref = _authoritative_hybrid_workflow_expectations(
                request.workflow_run_ids_by_source.get(normalized_path),
                source_path=normalized_path,
            )
            load_options: dict[str, Any] = {
                "project_root": ROOT_DIR,
                "discover_related_sidecars": request.discover_related_sidecars,
            }
            if expected_run_id is not None and expected_revision is not None:
                load_options.update(
                    expected_hybrid_run_id=expected_run_id,
                    expected_hybrid_workflow_revision=expected_revision,
                    expected_current_capture_lineage_ref=expected_lineage_ref,
                )
            loaded_reviews.append(
                load_learning_draft_review(normalized_path, **load_options)
            )
        except Exception as exc:
            invalid_sources.append(
                {
                    "source_path": normalized_path,
                    "failure_category": "invalid_review_source",
                    "reason": str(exc),
                }
            )
    try:
        result = build_interface_workflow_review(
            goal=request.goal,
            application_identity=request.application_identity,
            draft_sources=loaded_reviews,
        )
        result["invalid_sources"].extend(invalid_sources)
        trace_path = write_trace(
            category="panel",
            operation="load-interface-workflow-review",
            payload={
                "success": True,
                "request": request.model_dump(),
                "result": result,
            },
            name_hint="interface_workflow_review",
        )
        result["trace_path"] = trace_path
        return APIResponse(
            success=True,
            message="Interface workflow review loaded",
            data=result,
            error=None,
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Interface workflow review load failed",
            data=None,
            error=ErrorModel(
                code="interface_workflow_review_load_failed",
                details=str(exc),
            ),
        )


def _interface_node_review_revision_hash(revision: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            revision,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _restore_unchanged_interface_review_confirmations(
    review: dict[str, Any],
) -> dict[str, Any]:
    """仅用服务端已验证的同一修订续存人工审核事实。"""

    prepared = deepcopy(review)
    workflow = prepared.get("workflow") if isinstance(prepared, dict) else None
    workflow_id = str(workflow.get("workflow_id") or "").strip() if isinstance(workflow, dict) else ""
    if not workflow_id:
        return prepared

    registry = load_interface_workflow_library_registry(project_root=ROOT_DIR)
    record = registry.get("workflows", {}).get(workflow_id)
    if not isinstance(record, dict):
        return prepared
    identity_key = str(record.get("application_identity_key") or "").strip()
    if not identity_key:
        return prepared
    persisted = load_interface_workflow_review_context(
        project_root=ROOT_DIR,
        application_identity_key=identity_key,
        workflow_id=workflow_id,
    )
    persisted_nodes = {
        str(node.get("node_id") or "").strip(): node
        for node in persisted.get("nodes") or []
        if isinstance(node, dict) and str(node.get("node_id") or "").strip()
    }
    reviewed_statuses = {
        "approved",
        "human_approved",
        "human_confirmed",
        "human_reviewed",
        "reviewed",
    }
    for node in prepared.get("nodes") or []:
        if not isinstance(node, dict) or node.get("reviewed_by_human") is not True:
            continue
        if str(node.get("review_status") or "").strip().casefold() not in reviewed_statuses:
            continue
        node_id = str(node.get("node_id") or "").strip()
        previous = persisted_nodes.get(node_id)
        if not isinstance(previous, dict) or previous.get("reviewed_by_human") is not True:
            continue
        if str(previous.get("review_status") or "").strip().casefold() not in reviewed_statuses:
            continue
        persisted_path = Path(str(record.get("path") or ""))
        persisted_path = (
            persisted_path.resolve()
            if persisted_path.is_absolute()
            else (ROOT_DIR / persisted_path).resolve()
        )
        persisted_source_asset_sha256 = hashlib.sha256(
            persisted_path.read_bytes()
        ).hexdigest()
        integrity = evaluate_interface_workflow_node_integrity(
            review=persisted,
            node=previous,
            record=record,
            project_root=ROOT_DIR,
            source_asset_sha256=persisted_source_asset_sha256,
        )
        if not (
            integrity["eligibility"]["agent_usable"]
            and integrity["integrity_verified"]
        ):
            continue
        previous_revision = integrity["canonical_revision"]
        current_revision = build_interface_node_review_revision(
            prepared,
            node_id=node_id,
        )
        if current_revision != previous_revision:
            continue
        node["human_review_confirmation"] = {
            "contract_version": "interface_node_human_review_confirmation_v1",
            "revision": current_revision,
        }
    return prepared


def _interface_workflow_save_lock(review: dict[str, Any]) -> Lock:
    workflow = review.get("workflow") if isinstance(review, dict) else None
    workflow_id = str(workflow.get("workflow_id") or "").strip() if isinstance(workflow, dict) else ""
    lock_key = "".join(
        character if character.isalnum() or character in "_.-" else "_"
        for character in workflow_id
    ).strip("._") or "__invalid_workflow__"
    return _interface_workflow_lock(workflow_id)


def _interface_workflow_lock(workflow_id: str) -> Lock:
    lock_key = "".join(
        character if character.isalnum() or character in "_.-" else "_"
        for character in str(workflow_id or "").strip()
    ).strip("._") or "__invalid_workflow__"
    with _INTERFACE_WORKFLOW_SAVE_LOCKS_GUARD:
        return _INTERFACE_WORKFLOW_SAVE_LOCKS.setdefault(lock_key, Lock())


def _save_interface_workflow_review_transaction(
    review: dict[str, Any],
    *,
    out_dir: str | None,
) -> dict[str, Any]:
    """串行化同一流程的审核重算、落盘与只读投影。"""

    with _interface_workflow_save_lock(review):
        prepared_review = _restore_unchanged_interface_review_confirmations(review)
        result = save_interface_workflow_review_candidate(
            prepared_review,
            project_root=ROOT_DIR,
            out_dir=out_dir,
        )
        saved_review_path = Path(result["path"])
        saved_review_bytes = saved_review_path.read_bytes()
        normalized_review = json.loads(saved_review_bytes.decode("utf-8-sig"))
        result["saved_review"] = normalized_review
        if result["node_count"] > 0:
            registry = load_interface_workflow_library_registry(project_root=ROOT_DIR)
            workflow_record = registry.get("workflows", {}).get(result["workflow_id"])
            trusted_revisions: dict[str, PersistedReviewRevision] = {}
            if isinstance(workflow_record, dict):
                source_asset_sha256 = hashlib.sha256(saved_review_bytes).hexdigest()
                for node in normalized_review.get("nodes") or []:
                    if not isinstance(node, dict):
                        continue
                    node_id = str(node.get("node_id") or "").strip()
                    integrity = evaluate_interface_workflow_node_integrity(
                        review=normalized_review,
                        node=node,
                        record=workflow_record,
                        project_root=ROOT_DIR,
                        source_asset_sha256=source_asset_sha256,
                    )
                    if (
                        integrity["integrity_verified"]
                        and integrity["eligibility"]["agent_usable"]
                    ):
                        trusted_revisions[node_id] = PersistedReviewRevision(
                            revision=integrity["canonical_revision"],
                            revision_hash=integrity["canonical_revision_hash"],
                            source_asset_sha256=source_asset_sha256,
                        )
            result["interface_asset_projection"] = save_workflow_review_as_application_assets(
                normalized_review,
                project_root=ROOT_DIR,
                persisted_review_revisions=trusted_revisions,
            )
        else:
            result["interface_asset_projection"] = {
                "status": "not_covered",
                "reason": "workflow_has_no_interface_nodes",
                "saved_interface_count": 0,
                "saved_transition_count": 0,
                "artifact_is_authorization": False,
            }
        return result


@router.post("/panel/save_interface_workflow_review", response_model=APIResponse)
def save_interface_workflow_review_endpoint(
    request: PanelSaveInterfaceWorkflowReviewRequest,
) -> APIResponse:
    """保存人工审核后的单软件流程草稿，不发布到 Agent Memory。"""

    try:
        result = _save_interface_workflow_review_transaction(
            request.review,
            out_dir=request.out_dir,
        )
        trace_path = write_trace(
            category="panel",
            operation="save-interface-workflow-review",
            payload={
                "success": True,
                "workflow_id": result["workflow_id"],
                "saved_path": result["path"],
                "node_count": result["node_count"],
                "edge_count": result["edge_count"],
                "interface_asset_projection": result["interface_asset_projection"],
                "review_status": result["review_status"],
                "published": False,
                "artifact_is_authorization": False,
            },
            name_hint=result["workflow_id"],
        )
        result["trace_path"] = trace_path
        return APIResponse(
            success=True,
            message="Interface workflow review draft saved",
            data=result,
            error=None,
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Interface workflow review save failed",
            data=None,
            error=ErrorModel(
                code="interface_workflow_review_save_failed",
                details=str(exc),
            ),
        )


def _resolve_reviewed_workflow_source(
    *, application_identity_key: str, workflow_id: str
) -> tuple[str, str]:
    """仅信任 v1 registry 中绑定的项目内 source workflow。"""

    identity_key = str(application_identity_key or "").strip()
    selected_workflow_id = str(workflow_id or "").strip()
    registry = load_interface_workflow_library_registry(project_root=ROOT_DIR)
    if not isinstance(registry, dict):
        raise ValueError("interface workflow registry is invalid")
    applications = registry.get("applications")
    workflows = registry.get("workflows")
    revision = registry.get("registry_revision")
    if not isinstance(applications, dict) or not isinstance(workflows, dict) or type(revision) is not int or revision < 0:
        raise ValueError("interface workflow registry shape is invalid")
    application = applications.get(identity_key)
    if not isinstance(application, dict):
        raise ValueError("interface workflow application identity not found")
    workflow_ids = application.get("workflow_ids")
    if not isinstance(workflow_ids, list) or any(not isinstance(item, str) for item in workflow_ids):
        raise ValueError("interface workflow application workflow_ids are invalid")
    if selected_workflow_id not in set(workflow_ids):
        raise ValueError("interface workflow does not belong to selected application")
    record = workflows.get(selected_workflow_id)
    if not isinstance(record, dict):
        raise ValueError("interface workflow not found")
    if str(record.get("application_identity_key") or "").strip() != identity_key:
        raise ValueError("interface workflow application identity mismatch")
    declared_path = Path(str(record.get("path") or ""))
    resolved_path = declared_path.resolve() if declared_path.is_absolute() else (ROOT_DIR / declared_path).resolve()
    if ROOT_DIR not in resolved_path.parents or not resolved_path.is_file():
        raise ValueError("interface workflow source path is invalid")
    source_sha = str(record.get("source_asset_sha256") or "").strip().lower()
    if len(source_sha) != 64 or any(character not in "0123456789abcdef" for character in source_sha):
        raise ValueError("interface workflow source SHA-256 is invalid")
    return resolved_path.relative_to(ROOT_DIR).as_posix(), source_sha


def _compile_reviewed_workflow_request(
    request: PanelCompileReviewedWorkflowAssetRequest,
) -> dict[str, Any]:
    source_path, registry_sha = _resolve_reviewed_workflow_source(
        application_identity_key=request.application_identity_key,
        workflow_id=request.workflow_id,
    )
    expected_sha = request.expected_source_workflow_sha256.lower()
    if expected_sha != registry_sha:
        return {
            "contract_version": "reviewed_workflow_compile_result_v2",
            "status": "blocked",
            "asset": None,
            "blocked_reasons": [{"code": "source_workflow_sha256_mismatch", "message": "expected source workflow SHA-256 does not match registry binding"}],
        }
    return compile_reviewed_workflow_asset_v2(
        project_root=ROOT_DIR,
        source_workflow_path=source_path,
        expected_source_workflow_sha256=expected_sha,
    )


def _safe_blocked_compile_result(result: dict[str, Any]) -> dict[str, Any]:
    """阻断结果只暴露稳定 reason code，绝不回传编译器的文件路径文本。"""

    return {
        "contract_version": "reviewed_workflow_compile_result_v2",
        "status": "blocked",
        "asset": None,
        "blocked_reasons": [
            {"code": str(item.get("code") or "compile_blocked"), "message": "reviewed workflow compilation blocked"}
            for item in result.get("blocked_reasons", [])
            if isinstance(item, dict)
        ],
    }


@router.post("/panel/compile_reviewed_workflow_asset", response_model=APIResponse)
def compile_reviewed_workflow_asset_endpoint(request: PanelCompileReviewedWorkflowAssetRequest) -> APIResponse:
    """编译服务端注册的人审流程；此端点不写入 v2 CAS。"""

    try:
        result = _compile_reviewed_workflow_request(request)
        registry_revision = ReviewedWorkflowAssetStore(project_root=ROOT_DIR).registry()["registry_revision"]
    except (OSError, ValueError, json.JSONDecodeError):
        return APIResponse(success=False, message="Reviewed workflow compile failed", data=None, error=ErrorModel(code="reviewed_workflow_compile_failed", details="server-side reviewed workflow source validation failed"))
    if result.get("status") != "compiled":
        return APIResponse(success=False, message="Reviewed workflow compile blocked", data={"result": _safe_blocked_compile_result(result), "registry_revision": registry_revision, "artifact_is_authorization": False, "execute_binding_enabled": False}, error=ErrorModel(code="reviewed_workflow_compile_blocked", details="reviewed workflow compilation did not satisfy fail-closed checks"))
    return APIResponse(success=True, message="Reviewed workflow compiled", data={"result": result, "registry_revision": registry_revision, "artifact_is_authorization": False, "execute_binding_enabled": False}, error=None)


@router.post("/panel/publish_reviewed_workflow_asset", response_model=APIResponse)
def publish_reviewed_workflow_asset_endpoint(request: PanelPublishReviewedWorkflowAssetRequest) -> APIResponse:
    """在 CAS 写入前重新编译；从不接受客户端提供的 asset。"""

    try:
        with _interface_workflow_lock(request.workflow_id):
            compile_request = PanelCompileReviewedWorkflowAssetRequest(
                application_identity_key=request.application_identity_key,
                workflow_id=request.workflow_id,
                expected_source_workflow_sha256=request.expected_source_workflow_sha256,
            )
            result = _compile_reviewed_workflow_request(compile_request)
            if result.get("status") != "compiled" or not isinstance(result.get("asset"), dict):
                return APIResponse(success=False, message="Reviewed workflow publish blocked", data={"compile_result": _safe_blocked_compile_result(result)}, error=ErrorModel(code="reviewed_workflow_compile_blocked", details="reviewed workflow must compile immediately before publish"))
            # 在 CAS 写入前再次读取 v1 binding 与 source bytes，避免 save/delete 的 TOCTOU。
            source_path, source_sha = _resolve_reviewed_workflow_source(application_identity_key=request.application_identity_key, workflow_id=request.workflow_id)
            if (
                request.workflow_id
                != result["asset"]["source_review_lineage"]["source_workflow_id"]
                or source_sha
                != result["asset"]["source_review_lineage"]["source_workflow_sha256"]
                or hashlib.sha256((ROOT_DIR / source_path).read_bytes()).hexdigest()
                != source_sha
            ):
                return APIResponse(success=False, message="Reviewed workflow publish blocked", data={"compile_result": result}, error=ErrorModel(code="reviewed_workflow_source_changed", details="reviewed workflow source changed before publish"))
            publish_result = ReviewedWorkflowAssetStore(project_root=ROOT_DIR).publish(result["asset"], expected_registry_revision=request.expected_registry_revision)
    except (OSError, ValueError, json.JSONDecodeError):
        return APIResponse(success=False, message="Reviewed workflow publish failed", data=None, error=ErrorModel(code="reviewed_workflow_publish_failed", details="server-side reviewed workflow publish validation failed"))
    return APIResponse(success=True, message="Reviewed workflow published", data={"compile_result": result, "publish_result": publish_result, "artifact_is_authorization": False, "execute_binding_enabled": False}, error=None)


@router.post("/panel/preview_reviewed_workflow_replay", response_model=APIResponse)
def preview_reviewed_workflow_replay_endpoint(request: PanelPreviewReviewedWorkflowReplayRequest) -> APIResponse:
    """只读 replay preview：仅加载 CAS 与解析 observation，绝不调用捕获或 action。"""

    try:
        asset = ReviewedWorkflowAssetStore(project_root=ROOT_DIR).load_active(request.asset_id)
        actual_sha = content_sha256(asset)
        preview_base = {"mode": "read_only_preview", "would_call_action_api": False, "execution_authorized": False, "artifact_is_authorization": False, "execute_binding_enabled": False}
        if actual_sha != request.expected_content_sha256.lower():
            return APIResponse(success=False, message="Reviewed workflow preview blocked", data=preview_base, error=ErrorModel(code="reviewed_workflow_preview_hash_mismatch", details="expected content SHA-256 does not match active reviewed workflow asset"))
        if not request.current_observation:
            return APIResponse(success=False, message="Reviewed workflow preview observation required", data={**preview_base, "asset_id": asset["asset_id"], "content_sha256": actual_sha}, error=ErrorModel(code="reviewed_workflow_preview_observation_required", details="a nonempty current observation is required for read-only replay preview"))
        resolution = resolve_current_state(asset, request.current_observation)
    except (OSError, ValueError, json.JSONDecodeError):
        return APIResponse(success=False, message="Reviewed workflow preview failed", data={"mode": "read_only_preview", "would_call_action_api": False, "execution_authorized": False, "artifact_is_authorization": False, "execute_binding_enabled": False}, error=ErrorModel(code="reviewed_workflow_preview_failed", details="server-side reviewed workflow preview validation failed"))
    data = {**preview_base, "asset_id": asset["asset_id"], "content_sha256": actual_sha, "state_resolution": resolution}
    if resolution.get("status") != "resolved":
        return APIResponse(success=False, message="Reviewed workflow preview unresolved", data=data, error=ErrorModel(code="reviewed_workflow_preview_unresolved", details="current observation did not resolve one reviewed workflow state"))
    return APIResponse(success=True, message="Reviewed workflow replay preview resolved", data=data, error=None)


@router.post("/panel/delete_learning_evidence", response_model=APIResponse)
def delete_learning_evidence_endpoint(
    request: PanelDeleteLearningEvidenceRequest,
) -> APIResponse:
    """删除未被流程引用的单界面学习证据。"""

    try:
        result = delete_learning_evidence(
            project_root=ROOT_DIR,
            source_path=request.source_path,
        )
        result["trace_path"] = write_trace(
            category="panel",
            operation="delete-learning-evidence",
            payload={
                "success": True,
                "deleted_path": result["deleted_path"],
                "associated_files_preserved": result["associated_files_preserved"],
                "artifact_is_authorization": False,
            },
            name_hint="learning_evidence_deleted",
        )
        return APIResponse(
            success=True,
            message="Learning evidence deleted",
            data=result,
            error=None,
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Learning evidence delete failed",
            data=None,
            error=ErrorModel(
                code="learning_evidence_delete_failed",
                details=str(exc),
            ),
        )


@router.post("/panel/delete_interface_workflow", response_model=APIResponse)
def delete_interface_workflow_endpoint(
    request: PanelDeleteInterfaceWorkflowRequest,
) -> APIResponse:
    """删除一个流程资产，但保留可由其他流程复用的单界面证据。"""

    try:
        with _interface_workflow_lock(request.workflow_id):
            result = delete_interface_workflow_review_candidate(
                project_root=ROOT_DIR,
                workflow_id=request.workflow_id,
            )
        result["trace_path"] = write_trace(
            category="panel",
            operation="delete-interface-workflow",
            payload={
                "success": True,
                "workflow_id": result["workflow_id"],
                "deleted_path": result["deleted_path"],
                "single_interface_evidence_deleted": False,
                "artifact_is_authorization": False,
            },
            name_hint=result["workflow_id"],
        )
        return APIResponse(
            success=True,
            message="Interface workflow deleted",
            data=result,
            error=None,
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Interface workflow delete failed",
            data=None,
            error=ErrorModel(
                code="interface_workflow_delete_failed",
                details=str(exc),
            ),
        )


@router.get("/panel/learning_draft_sources", response_model=APIResponse)
def list_learning_draft_sources_endpoint(limit: int = 12, include_recent: bool = True) -> APIResponse:
    """List recent learning draft sources that can be loaded for review."""
    try:
        bounded_limit = max(1, min(int(limit or 12), 50))
        result = _list_recent_learning_draft_sources(limit=bounded_limit, include_recent=include_recent)
        return APIResponse(success=True, message="Learning draft sources listed", data=result, error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Learning draft source list failed",
            data=None,
            error=ErrorModel(code="learning_draft_source_list_failed", details=str(exc)),
        )


@router.get("/panel/surface_rule_registry", response_model=APIResponse)
def list_surface_rule_registry_endpoint() -> APIResponse:
    """List safe, read-only summaries of human correction rule candidates."""
    try:
        result = build_surface_rule_registry_panel_view(project_root=ROOT_DIR)
        return APIResponse(success=True, message="Surface rule registry listed", data=result, error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Surface rule registry list failed",
            data=None,
            error=ErrorModel(code="surface_rule_registry_list_failed", details=str(exc)),
        )


@router.post("/panel/save_learning_draft_review", response_model=APIResponse)
def save_learning_draft_review_endpoint(request: PanelSaveLearningDraftReviewRequest) -> APIResponse:
    """Save a reviewed template candidate without enabling execution."""
    try:
        review_patch = deepcopy(request.review_patch)
        workflow_run_id = review_patch.pop("_hybrid_workflow_run_id", None)
        expected_run_id, expected_revision, expected_lineage_ref = (
            _authoritative_hybrid_workflow_expectations(
                workflow_run_id,
                source_path=request.source_path,
            )
        )
        review_patch.pop("_server_hybrid_expectations", None)
        if (
            expected_run_id is not None
            and expected_revision is not None
            and expected_lineage_ref is not None
        ):
            review_patch["_server_hybrid_expectations"] = {
                "run_id": expected_run_id,
                "workflow_revision": expected_revision,
                "capture_lineage_ref": expected_lineage_ref,
            }
        result = build_pathgraph_candidate_from_review(
            request.source_path,
            review_patch,
            project_root=ROOT_DIR,
        )
        trace_path = write_trace(
            category="panel",
            operation="save-learning-draft-review",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint="reviewed_template_candidate",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="Reviewed template candidate saved", data=result, error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Learning draft review save failed",
            data=None,
            error=ErrorModel(code="learning_draft_review_save_failed", details=str(exc)),
        )


@router.get("/panel/continuous_task_handoff", response_model=APIResponse)
def continuous_task_handoff_endpoint(run_dir: Optional[str] = None) -> APIResponse:
    """Load a paused continuous-task handoff without operating the target app."""
    try:
        result = load_continuous_task_handoff(
            project_root=ROOT_DIR,
            run_dir=run_dir,
            memory_store=continuous_task_memory_store,
        )
        return APIResponse(success=True, message="Continuous task handoff loaded", data=result, error=None)
    except (ValueError, OSError, KeyError) as exc:
        return APIResponse(
            success=False,
            message="Continuous task handoff is unavailable",
            data=None,
            error=ErrorModel(code="continuous_task_handoff_unavailable", details=str(exc)),
        )


@router.post("/panel/resume_continuous_task", response_model=APIResponse)
def resume_continuous_task_endpoint(request: PanelResumeContinuousTaskRequest) -> APIResponse:
    """Resume the same no-submit task only after reviewed memory passes the handoff gate."""
    try:
        result = start_continuous_task_resume(
            project_root=ROOT_DIR,
            run_dir=request.run_dir,
            memory_store=continuous_task_memory_store,
            base_url=request.base_url,
        )
        return APIResponse(success=True, message="Continuous task resume started", data=result, error=None)
    except (ValueError, OSError, KeyError) as exc:
        return APIResponse(
            success=False,
            message="Continuous task resume was blocked",
            data=None,
            error=ErrorModel(code="continuous_task_resume_blocked", details=str(exc)),
        )


@router.post("/panel/run_learning_model_trial", response_model=APIResponse)
def run_learning_model_trial_endpoint(request: PanelRunLearningModelTrialRequest) -> APIResponse:
    """Run and save a raw Learning Studio draft trial without creating executable assets."""
    try:
        image_path = _resolve_panel_learning_image_path(request.image_path)
    except FileNotFoundError as exc:
        return APIResponse(
            success=False,
            message="Learning model trial image not found",
            data={"image_path": request.image_path},
            error=ErrorModel(code="learning_trial_image_not_found", details=str(exc)),
        )
    except ValueError as exc:
        return APIResponse(
            success=False,
            message="Learning model trial image path is not allowed",
            data={"image_path": request.image_path},
            error=ErrorModel(code="learning_trial_image_not_allowed", details=str(exc)),
        )

    try:
        result = build_learning_model_trial(
            image_path=image_path,
            app_name=request.app_name,
            state_hint=request.state_hint,
            goal=request.goal,
            validation_mode=request.validation_mode,
            max_attempts=request.max_attempts,
            observation_evidence=request.observation_evidence,
            learning_parameter_overrides={
                "max_output_tokens": request.max_output_tokens,
                "temperature": request.temperature,
                "timeout_seconds": request.timeout_seconds,
                "learning_image_max_edge": request.learning_image_max_edge,
                "allow_fast_profile_fallback": request.allow_fast_profile_fallback,
            },
        )
        safety = {
            **(result.get("safety") if isinstance(result.get("safety"), dict) else {}),
            "real_clicks_performed": 0,
            "promotion_allowed": False,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "live_safe_fill_attempted": 0,
            "final_submit_forbidden": True,
            "real_action_requires_gate": True,
        }
        reference_available = bool((result.get("target_contract") or {}).get("reference_template")) if isinstance(result.get("target_contract"), dict) else False
        saved_payload = {
            **result,
            "artifact_type": "raw_learning_trial",
            "draft_only": True,
            "draft_graph_preview": True,
            "runtime_path_graph": False,
            "promotion_allowed": False,
            "artifact_is_authorization": False,
            "execute_binding_enabled": False,
            "real_clicks": 0,
            "live_safe_fill_attempted": 0,
            "final_submit_forbidden": True,
            "real_action_requires_gate": True,
            "reference_available": reference_available,
            "safety": safety,
            "panel_learning_studio": {
                "contract_version": "panel_learning_studio_trial_v1",
                "draft_graph_preview": True,
                "display_only": True,
                "source": "panel_run_learning_model_trial",
            },
        }
        trial_path = _save_panel_learning_trial(saved_payload, app_name=request.app_name)
        trace_path = write_trace(
            category="panel",
            operation="run-learning-model-trial",
            payload={
                "success": True,
                "request": request.model_dump(),
                "result": {
                    "trial_path": trial_path,
                    "status": saved_payload.get("status"),
                    "artifact_type": saved_payload.get("artifact_type"),
                    "draft_only": True,
                    "real_clicks": 0,
                    "promotion_allowed": False,
                },
            },
            name_hint="learning_model_trial",
        )
        return APIResponse(
            success=True,
            message="Learning draft trial saved",
            data={
                "contract_version": "panel_learning_model_trial_run_v1",
                "artifact_type": "raw_learning_trial",
                "draft_only": True,
                "draft_graph_preview": True,
                "runtime_path_graph": False,
                "trial_path": trial_path,
                "trace_path": trace_path,
                "status": saved_payload.get("status"),
                "best_score_percent": saved_payload.get("best_score_percent") if reference_available else None,
                "alignment_score": saved_payload.get("best_score_percent") if reference_available else "not_available",
                "reference_available": saved_payload.get("reference_available"),
                "promotion_allowed": False,
                "artifact_is_authorization": False,
                "execute_binding_enabled": False,
                "real_clicks": 0,
                "live_safe_fill_attempted": 0,
                "final_submit_forbidden": True,
                "real_action_requires_gate": True,
                "safety": safety,
                "summary": {
                    "app_name": saved_payload.get("app_name"),
                    "state_hint": saved_payload.get("state_hint"),
                    "attempt_count": saved_payload.get("attempt_count"),
                    "best_attempt_index": saved_payload.get("best_attempt_index"),
                    "draft_section_counts": _learning_draft_section_counts(saved_payload.get("best_learning_draft")),
                },
            },
            error=None,
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Learning model trial failed",
            data={"image_path": request.image_path, "app_name": request.app_name},
            error=ErrorModel(code="learning_model_trial_failed", details=str(exc)),
        )


@router.post("/panel/run_learning_recognition_trial", response_model=APIResponse)
def run_learning_recognition_trial_endpoint(request: PanelRunLearningRecognitionTrialRequest) -> APIResponse:
    """Build a display-only learning draft from current observe/coordinate evidence."""
    result = run_recognition_task(
        RecognitionTaskInput.model_validate(request.model_dump()),
        project_root=ROOT_DIR,
    )
    return APIResponse.model_validate(
        recognition_result_to_legacy_response(result)
    )


@router.post("/panel/run_learning_two_stage_understanding", response_model=APIResponse)
def run_learning_two_stage_understanding_endpoint(
    request: PanelRunLearningTwoStageUnderstandingRequest,
) -> APIResponse:
    """Run the real learning-panel Stage1 gate + Stage2 numbering path."""
    result = run_two_stage_understanding_task(
        TwoStageUnderstandingTaskInput.model_validate(request.model_dump()),
        project_root=ROOT_DIR,
    )
    return APIResponse.model_validate(
        two_stage_result_to_legacy_response(result)
    )


@router.post("/panel/run_learning_model_review_repair", response_model=APIResponse)
def run_learning_model_review_repair_endpoint(
    request: PanelRunLearningModelReviewRepairRequest,
) -> APIResponse:
    """运行只读模型复核、确定性修复、最终编号与完整性 Gate。"""

    result = run_model_review_task(
        ModelReviewTaskInput.model_validate(request.model_dump()),
        project_root=ROOT_DIR,
        review_runner=run_panel_learning_model_review_repair,
        trace_writer=write_trace,
        path_resolver=_resolve_under_root_path,
    )
    return APIResponse.model_validate(
        model_review_result_to_legacy_response(result)
    )


@router.post("/panel/generate_pathgraph_candidate", response_model=APIResponse)
def generate_pathgraph_candidate_endpoint(request: PanelGeneratePathGraphCandidateRequest) -> APIResponse:
    """Generate a non-executable PathGraph candidate from the reviewed learning draft."""
    try:
        result = build_pathgraph_candidate_from_review(
            request.source_path,
            request.review_patch,
            project_root=ROOT_DIR,
        )
        trace_path = write_trace(
            category="panel",
            operation="generate-pathgraph-candidate",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint="pathgraph_candidate",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="PathGraph candidate generated", data=result, error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="PathGraph candidate generation failed",
            data=None,
            error=ErrorModel(code="pathgraph_candidate_generation_failed", details=str(exc)),
        )


@router.post("/panel/attach_detail_observe_result", response_model=APIResponse)
def attach_detail_observe_result_endpoint(request: PanelAttachDetailObserveResultRequest) -> APIResponse:
    """Attach a reviewed detail observe result to an existing non-executable PathGraph candidate."""
    try:
        result = attach_detail_observe_result_to_candidate(
            request.candidate_path,
            request_id=request.request_id,
            detail_source_path=request.detail_source_path,
            project_root=ROOT_DIR,
        )
        trace_path = write_trace(
            category="panel",
            operation="attach-detail-observe-result",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint="detail_observe_attachment",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="Detail observe result attached", data=result, error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Detail observe attachment failed",
            data=None,
            error=ErrorModel(code="detail_observe_attachment_failed", details=str(exc)),
        )


@router.post("/panel/create_assisted_template_review_package", response_model=APIResponse)
def create_assisted_template_review_package_endpoint(request: PanelAssistedTemplateReviewPackageRequest) -> APIResponse:
    """Create a review-only assisted-template package from a promotion-gate-passed candidate."""
    try:
        result = create_assisted_template_review_package(
            request.candidate_path,
            review_decision=request.review_decision,
            reviewer_note=request.reviewer_note,
            project_root=ROOT_DIR,
        )
        trace_path = write_trace(
            category="panel",
            operation="create-assisted-template-review-package",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint="assisted_template_review_package",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="Assisted template review package created", data=result, error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Assisted template review package creation failed",
            data=None,
            error=ErrorModel(code="assisted_template_review_package_failed", details=str(exc)),
        )


@router.post("/panel/load_assisted_template_review_package", response_model=APIResponse)
def load_assisted_template_review_package_endpoint(request: PanelLoadAssistedTemplateReviewPackageRequest) -> APIResponse:
    """Load a review-only assisted-template package for checklist display."""
    try:
        result = load_assisted_template_review_package(request.package_path, project_root=ROOT_DIR)
        trace_path = write_trace(
            category="panel",
            operation="load-assisted-template-review-package",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint="assisted_template_review_package",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="Assisted template review package loaded", data=result, error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Assisted template review package load failed",
            data=None,
            error=ErrorModel(code="assisted_template_review_package_load_failed", details=str(exc)),
        )


@router.post("/panel/save_assisted_template_review_decisions", response_model=APIResponse)
def save_assisted_template_review_decisions_endpoint(
    request: PanelSaveAssistedTemplateReviewDecisionsRequest,
) -> APIResponse:
    """Save human checklist decisions for a review-only assisted-template package."""
    try:
        result = save_assisted_template_review_decisions(
            request.package_path,
            request.decisions,
            overall_decision=request.overall_decision,
            reviewer_note=request.reviewer_note,
            project_root=ROOT_DIR,
        )
        trace_path = write_trace(
            category="panel",
            operation="save-assisted-template-review-decisions",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint="assisted_template_review_decisions",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="Assisted template review decisions saved", data=result, error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Assisted template review decisions save failed",
            data=None,
            error=ErrorModel(code="assisted_template_review_decisions_save_failed", details=str(exc)),
        )


@router.post("/panel/create_assisted_template_asset_candidate", response_model=APIResponse)
def create_assisted_template_asset_candidate_endpoint(
    request: PanelCreateAssistedTemplateAssetCandidateRequest,
) -> APIResponse:
    """Create a non-executable asset candidate from accepted assisted-template checklist items."""
    try:
        result = create_assisted_template_asset_candidate(
            request.package_path,
            review_record_path=request.review_record_path,
            project_root=ROOT_DIR,
        )
        trace_path = write_trace(
            category="panel",
            operation="create-assisted-template-asset-candidate",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint="assisted_template_asset_candidate",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="Assisted template asset candidate created", data=result, error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Assisted template asset candidate creation failed",
            data=None,
            error=ErrorModel(code="assisted_template_asset_candidate_failed", details=str(exc)),
        )


@router.post("/panel/create_assisted_template_graph_draft", response_model=APIResponse)
def create_assisted_template_graph_draft_endpoint(
    request: PanelCreateAssistedTemplateGraphDraftRequest,
) -> APIResponse:
    """Create a non-executable graph-shaped draft from an assisted-template asset candidate."""
    try:
        result = create_assisted_template_graph_draft(
            request.asset_candidate_path,
            project_root=ROOT_DIR,
        )
        trace_path = write_trace(
            category="panel",
            operation="create-assisted-template-graph-draft",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint="assisted_template_graph_draft",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="Assisted template graph draft created", data=result, error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Assisted template graph draft creation failed",
            data=None,
            error=ErrorModel(code="assisted_template_graph_draft_failed", details=str(exc)),
        )


@router.post("/panel/create_assisted_template_acceptance_suggestions", response_model=APIResponse)
def create_assisted_template_acceptance_suggestions_endpoint(
    request: PanelCreateAssistedTemplateAcceptanceSuggestionsRequest,
) -> APIResponse:
    """Create linked checklist suggestions for human review only."""
    try:
        result = create_assisted_template_acceptance_suggestions(
            request.package_path,
            project_root=ROOT_DIR,
        )
        trace_path = write_trace(
            category="panel",
            operation="create-assisted-template-acceptance-suggestions",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint="assisted_template_acceptance_suggestions",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="Assisted template acceptance suggestions created", data=result, error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Assisted template acceptance suggestion creation failed",
            data=None,
            error=ErrorModel(code="assisted_template_acceptance_suggestions_failed", details=str(exc)),
        )


@router.post("/panel/create_assisted_template_promotion_preflight", response_model=APIResponse)
def create_assisted_template_promotion_preflight_endpoint(
    request: PanelCreateAssistedTemplatePromotionPreflightRequest,
) -> APIResponse:
    """Create a review-only manual preflight before any audited Runtime promotion path."""
    try:
        result = create_assisted_template_promotion_preflight(
            request.package_path,
            project_root=ROOT_DIR,
        )
        trace_path = write_trace(
            category="panel",
            operation="create-assisted-template-promotion-preflight",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint="assisted_template_promotion_preflight",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="Assisted template promotion preflight created", data=result, error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Assisted template promotion preflight failed",
            data=None,
            error=ErrorModel(code="assisted_template_promotion_preflight_failed", details=str(exc)),
        )


@router.post("/panel/create_assisted_template_acceptance_simulation", response_model=APIResponse)
def create_assisted_template_acceptance_simulation_endpoint(
    request: PanelCreateAssistedTemplateAcceptanceSimulationRequest,
) -> APIResponse:
    """Create a non-authorizing simulation for accepting linked checklist suggestions."""
    try:
        result = create_assisted_template_acceptance_simulation(
            request.package_path,
            project_root=ROOT_DIR,
        )
        trace_path = write_trace(
            category="panel",
            operation="create-assisted-template-acceptance-simulation",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint="assisted_template_acceptance_simulation",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="Assisted template acceptance simulation created", data=result, error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Assisted template acceptance simulation failed",
            data=None,
            error=ErrorModel(code="assisted_template_acceptance_simulation_failed", details=str(exc)),
        )


@router.post("/panel/create_assisted_template_audited_promotion_request", response_model=APIResponse)
def create_assisted_template_audited_promotion_request_endpoint(
    request: PanelCreateAssistedTemplateAuditedPromotionRequestRequest,
) -> APIResponse:
    """Create a non-authorizing audited promotion request preview from a ready preflight."""
    try:
        result = create_assisted_template_audited_promotion_request(
            request.package_path,
            project_root=ROOT_DIR,
        )
        trace_path = write_trace(
            category="panel",
            operation="create-assisted-template-audited-promotion-request",
            payload={"success": True, "request": request.model_dump(), "result": result},
            name_hint="assisted_template_audited_promotion_request",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="Assisted template audited promotion request created", data=result, error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Assisted template audited promotion request failed",
            data=None,
            error=ErrorModel(code="assisted_template_audited_promotion_request_failed", details=str(exc)),
        )


@router.post("/panel/create_model_start_approval_packet", response_model=APIResponse)
def create_model_start_approval_packet_endpoint(request: PanelCreateModelStartApprovalPacketRequest) -> APIResponse:
    """Create the no-execute approval packet before any learn-fusion model start."""
    try:
        input_paths = _model_start_approval_packet_input_paths(request)
        result = report_learn_fusion_model_start_approval_packet(
            runbook_path=input_paths["runbook_path"],
            preflight_report_path=input_paths["preflight_report_path"],
            demo_readiness_report_path=input_paths["demo_readiness_report_path"],
            out_dir=input_paths["out_dir"],
            project_root=ROOT_DIR,
        )
        trace_path = write_trace(
            category="panel",
            operation="create-model-start-approval-packet",
            payload={"success": True, "request": request.model_dump(), "resolved_inputs": input_paths, "result": result},
            name_hint="learn_fusion_model_start_approval_packet",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="Model-start approval packet created", data=result, error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Model-start approval packet creation failed",
            data=None,
            error=ErrorModel(code="model_start_approval_packet_failed", details=str(exc)),
        )


@router.post("/panel/create_calibration_pre_run_check", response_model=APIResponse)
def create_calibration_pre_run_check_endpoint(request: PanelCreateCalibrationPreRunCheckRequest) -> APIResponse:
    """Create the no-model calibration command packet pre-run check."""
    try:
        input_paths = _calibration_pre_run_check_input_paths(request)
        result = report_learn_fusion_calibration_pre_run_check(
            approval_packet_path=input_paths["approval_packet_path"],
            out_dir=input_paths["out_dir"],
            project_root=ROOT_DIR,
        )
        trace_path = write_trace(
            category="panel",
            operation="create-calibration-pre-run-check",
            payload={"success": True, "request": request.model_dump(), "resolved_inputs": input_paths, "result": result},
            name_hint="learn_fusion_calibration_pre_run_check",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="Calibration pre-run check created", data=result, error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Calibration pre-run check creation failed",
            data=None,
            error=ErrorModel(code="calibration_pre_run_check_failed", details=str(exc)),
        )


@router.post("/panel/create_pathgraph_integration_readiness", response_model=APIResponse)
def create_pathgraph_integration_readiness_endpoint(
    request: PanelCreatePathgraphIntegrationReadinessRequest,
) -> APIResponse:
    """Create the display-only PathGraph integration readiness report."""
    try:
        input_paths = _pathgraph_integration_readiness_input_paths(request)
        result = report_learn_fusion_pathgraph_integration_readiness(
            pathgraph_candidate_path=input_paths["candidate_path"],
            out_dir=input_paths["out_dir"],
            project_root=ROOT_DIR,
        )
        trace_path = write_trace(
            category="panel",
            operation="create-pathgraph-integration-readiness",
            payload={"success": True, "request": request.model_dump(), "resolved_inputs": input_paths, "result": result},
            name_hint="learn_fusion_pathgraph_integration_readiness",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="PathGraph integration readiness created", data=result, error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="PathGraph integration readiness creation failed",
            data=None,
            error=ErrorModel(code="pathgraph_integration_readiness_failed", details=str(exc)),
        )


@router.post("/panel/create_current_evidence_packet", response_model=APIResponse)
def create_current_evidence_packet_endpoint(request: PanelCreateCurrentEvidencePacketRequest) -> APIResponse:
    """Create the display-only current learn-fusion evidence packet."""
    try:
        input_paths = _current_evidence_packet_input_paths(request)
        result = report_learn_fusion_current_evidence_packet(
            source_path=input_paths["source_path"],
            out_dir=input_paths["out_dir"],
            project_root=ROOT_DIR,
        )
        trace_path = write_trace(
            category="panel",
            operation="create-current-evidence-packet",
            payload={"success": True, "request": request.model_dump(), "resolved_inputs": input_paths, "result": result},
            name_hint="learn_fusion_current_evidence_packet",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="Current evidence packet created", data=result, error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Current evidence packet creation failed",
            data=None,
            error=ErrorModel(code="current_evidence_packet_failed", details=str(exc)),
        )


@router.post("/panel/create_precise_understanding_candidate", response_model=APIResponse)
def create_precise_understanding_candidate_endpoint(
    request: PanelCreatePreciseUnderstandingCandidateRequest,
) -> APIResponse:
    """Create the display-only precise-understanding candidate for future PathGraph preparation."""
    try:
        input_paths = _precise_understanding_candidate_input_paths(request)
        result = build_learn_precise_understanding_candidate(
            source_path=input_paths["source_path"],
            out_dir=input_paths["out_dir"],
            project_root=ROOT_DIR,
        )
        trace_path = write_trace(
            category="panel",
            operation="create-precise-understanding-candidate",
            payload={"success": True, "request": request.model_dump(), "resolved_inputs": input_paths, "result": result},
            name_hint="learn_precise_understanding_candidate",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="Precise understanding candidate created", data=result, error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Precise understanding candidate creation failed",
            data=None,
            error=ErrorModel(code="precise_understanding_candidate_failed", details=str(exc)),
        )


@router.post("/panel/create_page_detail_candidate", response_model=APIResponse)
def create_page_detail_candidate_endpoint(request: PanelCreatePageDetailCandidateRequest) -> APIResponse:
    """Create the display-only template-like page detail candidate for Learning Mode demo."""
    try:
        input_paths = _page_detail_candidate_input_paths(request)
        result = build_learn_page_detail_candidate(
            source_path=input_paths["source_path"],
            out_dir=input_paths["out_dir"],
            project_root=ROOT_DIR,
        )
        trace_path = write_trace(
            category="panel",
            operation="create-page-detail-candidate",
            payload={"success": True, "request": request.model_dump(), "resolved_inputs": input_paths, "result": result},
            name_hint="learn_page_detail_candidate",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="Page detail candidate created", data=result, error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Page detail candidate creation failed",
            data=None,
            error=ErrorModel(code="page_detail_candidate_failed", details=str(exc)),
        )


@router.post("/panel/create_learning_demo_scaffold", response_model=APIResponse)
def create_learning_demo_scaffold_endpoint(request: PanelCreateLearningDemoScaffoldRequest) -> APIResponse:
    """Create the review-only Learning Mode demo scaffold sidecar chain."""
    try:
        input_paths = _learning_demo_scaffold_input_paths(request)
        result = build_learn_demo_scaffold(
            source_path=input_paths["source_path"],
            out_dir=input_paths["out_dir"],
            project_root=ROOT_DIR,
        )
        trace_path = write_trace(
            category="panel",
            operation="create-learning-demo-scaffold",
            payload={"success": True, "request": request.model_dump(), "resolved_inputs": input_paths, "result": result},
            name_hint="learn_mode_demo_scaffold",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="Learning demo scaffold created", data=result, error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Learning demo scaffold creation failed",
            data=None,
            error=ErrorModel(code="learning_demo_scaffold_failed", details=str(exc)),
        )


@router.post("/panel/create_learning_demo_goal_readiness", response_model=APIResponse)
def create_learning_demo_goal_readiness_endpoint(request: PanelCreateLearningDemoGoalReadinessRequest) -> APIResponse:
    """Create the review-only Learning Mode demo goal-readiness sidecar report."""
    try:
        input_paths = _learning_demo_goal_readiness_input_paths(request)
        result = report_learning_mode_demo_goal_readiness(
            scaffold_path=input_paths["scaffold_path"],
            out_dir=input_paths["out_dir"],
            project_root=ROOT_DIR,
        )
        trace_path = write_trace(
            category="panel",
            operation="create-learning-demo-goal-readiness",
            payload={"success": True, "request": request.model_dump(), "resolved_inputs": input_paths, "result": result},
            name_hint="learning_mode_demo_goal_readiness",
        )
        result["trace_path"] = trace_path
        return APIResponse(success=True, message="Learning demo goal readiness created", data=result, error=None)
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Learning demo goal readiness creation failed",
            data=None,
            error=ErrorModel(code="learning_demo_goal_readiness_failed", details=str(exc)),
        )


def _model_start_approval_packet_input_paths(request: PanelCreateModelStartApprovalPacketRequest) -> dict[str, str]:
    if request.candidate_path:
        candidate_path = _resolve_under_root_path(request.candidate_path)
        review = load_learning_draft_review(_relative_panel_path(candidate_path), project_root=ROOT_DIR)
        candidate_review = (
            review.get("pathgraph_candidate_review") if isinstance(review.get("pathgraph_candidate_review"), dict) else {}
        )
        runbook = candidate_review.get("model_start_runbook") if isinstance(candidate_review.get("model_start_runbook"), dict) else {}
        preflight = (
            candidate_review.get("model_start_preflight")
            if isinstance(candidate_review.get("model_start_preflight"), dict)
            else {}
        )
        demo = candidate_review.get("demo_readiness") if isinstance(candidate_review.get("demo_readiness"), dict) else {}
        out_dir = _resolve_under_root_path(request.out_dir) if request.out_dir else candidate_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        preflight_path = request.preflight_report_path or preflight.get("report_path") or str(
            candidate_path.parent / "learn_fusion_model_start_preflight_report.json"
        )
        demo_path = request.demo_readiness_report_path or demo.get("report_path") or str(
            candidate_path.parent / "learn_fusion_demo_readiness_report.json"
        )
        runbook_path = _model_start_runbook_path(runbook, out_dir, fallback_path=preflight.get("runbook_path"))
        return {
            "runbook_path": _relative_panel_path(_resolve_under_root_path(str(runbook_path))),
            "preflight_report_path": _relative_panel_path(_resolve_under_root_path(str(preflight_path))),
            "demo_readiness_report_path": _relative_panel_path(_resolve_under_root_path(str(demo_path))),
            "out_dir": _relative_panel_path(out_dir),
        }
    if not (request.runbook_path and request.preflight_report_path and request.demo_readiness_report_path and request.out_dir):
        raise ValueError("candidate_path or all explicit approval packet paths are required")
    return {
        "runbook_path": _relative_panel_path(_resolve_under_root_path(request.runbook_path)),
        "preflight_report_path": _relative_panel_path(_resolve_under_root_path(request.preflight_report_path)),
        "demo_readiness_report_path": _relative_panel_path(_resolve_under_root_path(request.demo_readiness_report_path)),
        "out_dir": _relative_panel_path(_resolve_under_root_path(request.out_dir)),
    }


def _model_start_runbook_path(runbook: dict[str, Any], out_dir: Path, *, fallback_path: Any = None) -> Path:
    if isinstance(fallback_path, str) and fallback_path.strip():
        return _resolve_under_root_path(fallback_path)
    for key in ("source_runbook_path", "runbook_path", "report_path"):
        value = runbook.get(key)
        if isinstance(value, str) and value.strip():
            return _resolve_under_root_path(value)
    if not runbook:
        raise ValueError("model_start_runbook missing from candidate")
    embedded_path = out_dir / "learn_fusion_model_start_runbook_embedded.json"
    embedded_path.write_text(json.dumps(runbook, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return embedded_path


def _calibration_pre_run_check_input_paths(request: PanelCreateCalibrationPreRunCheckRequest) -> dict[str, str]:
    if request.candidate_path:
        candidate_path = _resolve_under_root_path(request.candidate_path)
        out_dir = _resolve_under_root_path(request.out_dir) if request.out_dir else candidate_path.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        approval_packet_path = request.approval_packet_path or str(
            candidate_path.parent / "learn_fusion_model_start_approval_packet.json"
        )
        return {
            "approval_packet_path": _relative_panel_path(_resolve_under_root_path(approval_packet_path)),
            "out_dir": _relative_panel_path(out_dir),
        }
    if not (request.approval_packet_path and request.out_dir):
        raise ValueError("candidate_path or approval_packet_path and out_dir are required")
    return {
        "approval_packet_path": _relative_panel_path(_resolve_under_root_path(request.approval_packet_path)),
        "out_dir": _relative_panel_path(_resolve_under_root_path(request.out_dir)),
    }


def _pathgraph_integration_readiness_input_paths(
    request: PanelCreatePathgraphIntegrationReadinessRequest,
) -> dict[str, str]:
    candidate_path = _resolve_under_root_path(request.candidate_path)
    out_dir = _resolve_under_root_path(request.out_dir) if request.out_dir else candidate_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    return {
        "candidate_path": _relative_panel_path(candidate_path),
        "out_dir": _relative_panel_path(out_dir),
    }


def _current_evidence_packet_input_paths(request: PanelCreateCurrentEvidencePacketRequest) -> dict[str, str]:
    source_path = _resolve_under_root_path(request.source_path)
    out_dir = _resolve_under_root_path(request.out_dir) if request.out_dir else source_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    return {
        "source_path": _relative_panel_path(source_path),
        "out_dir": _relative_panel_path(out_dir),
    }


def _precise_understanding_candidate_input_paths(
    request: PanelCreatePreciseUnderstandingCandidateRequest,
) -> dict[str, str]:
    source_path = _resolve_under_root_path(request.source_path)
    out_dir = _resolve_under_root_path(request.out_dir) if request.out_dir else source_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    return {
        "source_path": _relative_panel_path(source_path),
        "out_dir": _relative_panel_path(out_dir),
    }


def _page_detail_candidate_input_paths(request: PanelCreatePageDetailCandidateRequest) -> dict[str, str]:
    source_path = _resolve_under_root_path(request.source_path)
    out_dir = _resolve_under_root_path(request.out_dir) if request.out_dir else source_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    return {
        "source_path": _relative_panel_path(source_path),
        "out_dir": _relative_panel_path(out_dir),
    }


def _learning_demo_scaffold_input_paths(request: PanelCreateLearningDemoScaffoldRequest) -> dict[str, str]:
    source_path = _resolve_under_root_path(request.source_path)
    out_dir = _resolve_under_root_path(request.out_dir) if request.out_dir else source_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    return {
        "source_path": _relative_panel_path(source_path),
        "out_dir": _relative_panel_path(out_dir),
    }


def _learning_demo_goal_readiness_input_paths(request: PanelCreateLearningDemoGoalReadinessRequest) -> dict[str, str]:
    scaffold_path = _resolve_under_root_path(request.scaffold_path)
    out_dir = _resolve_under_root_path(request.out_dir) if request.out_dir else scaffold_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    return {
        "scaffold_path": _relative_panel_path(scaffold_path),
        "out_dir": _relative_panel_path(out_dir),
    }


def _resolve_under_root_path(path: str | Path) -> Path:
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = ROOT_DIR / resolved
    resolved = resolved.resolve()
    root = ROOT_DIR.resolve()
    if resolved != root and root not in resolved.parents:
        raise ValueError(f"path is outside project root: {resolved}")
    return resolved


PINNED_LEARNING_DRAFT_SOURCE_PATHS: list[str] = []

MAX_PINNED_LEARNING_DRAFT_SOURCES = 3
MAX_RECENT_LEARNING_DRAFT_CANDIDATE_ATTEMPTS = 6
MAX_RECENT_LEARNING_DRAFT_CANDIDATE_SCAN = 64


def _list_recent_learning_draft_sources(*, limit: int = 16, include_recent: bool = True) -> dict[str, Any]:
    roots = [
        ROOT_DIR / "artifacts" / "learning-runs",
        ROOT_DIR / "artifacts" / "learning-draft-review",
    ]
    pinned_paths = [ROOT_DIR / path for path in PINNED_LEARNING_DRAFT_SOURCE_PATHS]
    candidates: list[Path] = []
    sources: list[dict[str, Any]] = []
    skipped_count = 0
    suppressed_pinned_count = 0
    seen_paths: set[str] = set()
    for path in pinned_paths:
        if len(sources) >= min(MAX_PINNED_LEARNING_DRAFT_SOURCES, limit):
            break
        if not path.exists() or not path.is_file():
            continue
        try:
            source = _learning_draft_source_entry(path, pinned=True)
        except Exception:
            skipped_count += 1
            continue
        source["source_category"] = "recommended_current_precise_understanding"
        source["pinned"] = True
        sources.append(source)
        seen_paths.add(str(path.resolve()))
    for path in pinned_paths:
        resolved_text = str(path.resolve())
        if path.exists() and resolved_text not in seen_paths:
            seen_paths.add(resolved_text)
            suppressed_pinned_count += 1
    if include_recent:
        candidates = _discover_recent_named_files(
            roots,
            names={"trial_result.json", "reviewed_template_candidate.json", "pathgraph_candidate.json"},
            limit=MAX_RECENT_LEARNING_DRAFT_CANDIDATE_SCAN,
        )
    targeted_benchmark_scan_performed = False
    scanned_candidates = candidates[:MAX_RECENT_LEARNING_DRAFT_CANDIDATE_SCAN]
    quick_ready_candidates = []
    quick_incomplete_candidates = []
    for path in scanned_candidates:
        if _learning_draft_candidate_has_display_evidence(path):
            quick_ready_candidates.append(path)
        else:
            quick_incomplete_candidates.append(path)
    ranked_candidates = quick_ready_candidates + quick_incomplete_candidates
    candidate_attempt_limit = min(MAX_RECENT_LEARNING_DRAFT_CANDIDATE_ATTEMPTS, max(0, limit - len(sources)))
    candidate_attempt_count = 0
    for path in ranked_candidates:
        if len(sources) >= limit:
            break
        if str(path.resolve()) in seen_paths:
            continue
        if candidate_attempt_count >= candidate_attempt_limit:
            break
        candidate_attempt_count += 1
        try:
            source = (
                _learning_draft_trial_source_entry(path)
                if path.name == "trial_result.json"
                else _learning_draft_source_entry(path, pinned=False)
            )
        except Exception:
            skipped_count += 1
            continue
        source["source_category"] = _learning_draft_source_category(path, default=source.get("source_category"))
        sources.append(source)
        seen_paths.add(str(path.resolve()))
    recommended = next(
        (
            source
            for source in sources
            if source.get("pinned") is not True and source.get("display_completeness_status") == "ready"
        ),
        None,
    ) or next(
        (source for source in sources if source.get("display_completeness_status") == "ready"),
        None,
    )
    for source in sources:
        source["recommended_for_panel_review"] = source is recommended
    return {
        "contract_version": "panel_learning_draft_sources_v1",
        "roots": [_relative_panel_path(root) for root in roots],
        "targeted_benchmark_roots": [],
        "pinned_source_paths": [_relative_panel_path(path) for path in pinned_paths if path.exists()],
        "sources": sources,
        "skipped_count": skipped_count,
        "limit": limit,
        "include_recent": include_recent,
        "candidate_attempt_limit": candidate_attempt_limit,
        "candidate_attempt_count": candidate_attempt_count,
        "candidate_scan_limit": MAX_RECENT_LEARNING_DRAFT_CANDIDATE_SCAN,
        "candidate_scan_count": len(scanned_candidates),
        "candidate_discovery_strategy": "bounded_recent_directory_walk_v1",
        "candidate_quick_ready_count": len(quick_ready_candidates),
        "targeted_benchmark_scan_performed": targeted_benchmark_scan_performed,
        "max_pinned_sources": MAX_PINNED_LEARNING_DRAFT_SOURCES,
        "max_recent_candidate_attempts": MAX_RECENT_LEARNING_DRAFT_CANDIDATE_ATTEMPTS,
        "suppressed_pinned_count": suppressed_pinned_count,
        "recommended_source_path": recommended.get("source_path") if isinstance(recommended, dict) else None,
        "recommendation_status": "display_complete_recent_draft" if isinstance(recommended, dict) else "not_available",
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _discover_recent_named_files(roots: list[Path], *, names: set[str], limit: int) -> list[Path]:
    bounded_limit = max(1, int(limit or 1))
    directory_heap: list[tuple[int, int, Path]] = []
    candidates: list[tuple[int, Path]] = []
    sequence = 0
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        try:
            modified_ns = root.stat().st_mtime_ns
        except OSError:
            continue
        heapq.heappush(directory_heap, (-modified_ns, sequence, root))
        sequence += 1

    while directory_heap:
        newest_directory_ns = -directory_heap[0][0]
        if len(candidates) >= bounded_limit:
            oldest_candidate_ns = min(item[0] for item in candidates)
            if newest_directory_ns <= oldest_candidate_ns:
                break
        _, _, directory = heapq.heappop(directory_heap)
        try:
            entries = list(os.scandir(directory))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    heapq.heappush(directory_heap, (-entry.stat(follow_symlinks=False).st_mtime_ns, sequence, Path(entry.path)))
                    sequence += 1
                elif entry.name in names and entry.is_file(follow_symlinks=False):
                    candidates.append((entry.stat(follow_symlinks=False).st_mtime_ns, Path(entry.path)))
            except OSError:
                continue
        if len(candidates) > bounded_limit:
            candidates.sort(key=lambda item: item[0], reverse=True)
            del candidates[bounded_limit:]
    candidates.sort(key=lambda item: item[0], reverse=True)
    return [path for _, path in candidates[:bounded_limit]]


def _learning_draft_source_category(path: Path, *, default: Any = None) -> str:
    if path.name == "learn_page_detail_candidate.json":
        return "recent_learning_page_detail"
    if path.name == "learn_mode_demo_scaffold.json":
        return "recent_learning_demo_scaffold"
    return str(default or "recent_learning_draft")


def _learning_draft_source_entry(path: Path, *, pinned: bool) -> dict[str, Any]:
    review = load_learning_draft_review(
        _relative_panel_path(path),
        project_root=ROOT_DIR,
        discover_related_sidecars=False,
    )
    draft = review.get("draft") if isinstance(review.get("draft"), dict) else {}
    counts = _learning_draft_section_counts(draft)
    source = review.get("source") if isinstance(review.get("source"), dict) else {}
    preview = review.get("screen_understanding_preview") if isinstance(review.get("screen_understanding_preview"), dict) else {}
    candidate_review = (
        review.get("pathgraph_candidate_review") if isinstance(review.get("pathgraph_candidate_review"), dict) else {}
    )
    candidate_summary = (
        candidate_review.get("pathgraph_readiness_summary")
        if isinstance(candidate_review.get("pathgraph_readiness_summary"), dict)
        else {}
    )
    candidate_preflight = (
        candidate_review.get("model_start_preflight")
        if isinstance(candidate_review.get("model_start_preflight"), dict)
        else {}
    )
    candidate_demo = (
        candidate_review.get("demo_readiness") if isinstance(candidate_review.get("demo_readiness"), dict) else {}
    )
    candidate_approval_packet = (
        candidate_review.get("model_start_approval_packet")
        if isinstance(candidate_review.get("model_start_approval_packet"), dict)
        else {}
    )
    candidate_calibration_pre_run = (
        candidate_review.get("calibration_pre_run_check")
        if isinstance(candidate_review.get("calibration_pre_run_check"), dict)
        else {}
    )
    candidate_pathgraph_integration = (
        candidate_review.get("pathgraph_integration_readiness")
        if isinstance(candidate_review.get("pathgraph_integration_readiness"), dict)
        else {}
    )
    candidate_current_evidence = (
        candidate_review.get("current_evidence_packet")
        if isinstance(candidate_review.get("current_evidence_packet"), dict)
        else {}
    )
    candidate_precise_understanding = (
        candidate_review.get("precise_understanding_candidate")
        if isinstance(candidate_review.get("precise_understanding_candidate"), dict)
        else {}
    )
    candidate_page_detail = (
        candidate_review.get("page_detail_candidate")
        if isinstance(candidate_review.get("page_detail_candidate"), dict)
        else {}
    )
    candidate_demo_scaffold = (
        candidate_review.get("learn_mode_demo_scaffold")
        if isinstance(candidate_review.get("learn_mode_demo_scaffold"), dict)
        else {}
    )
    candidate_demo_goal_readiness = (
        candidate_review.get("learning_mode_demo_goal_readiness")
        if isinstance(candidate_review.get("learning_mode_demo_goal_readiness"), dict)
        else {}
    )
    readiness = (
        preview.get("precise_understanding_readiness_summary")
        if isinstance(preview.get("precise_understanding_readiness_summary"), dict)
        else {}
    )
    handoff = preview.get("calibration_handoff_report") if isinstance(preview.get("calibration_handoff_report"), dict) else {}
    handoff_future = handoff.get("future_outputs") if isinstance(handoff.get("future_outputs"), dict) else {}
    consistency = (
        preview.get("calibration_handoff_consistency_report")
        if isinstance(preview.get("calibration_handoff_consistency_report"), dict)
        else {}
    )
    consistency_summary = consistency.get("summary") if isinstance(consistency.get("summary"), dict) else {}
    runbook = preview.get("model_start_runbook") if isinstance(preview.get("model_start_runbook"), dict) else {}
    entry = {
        "source_path": source.get("source_path") or _relative_panel_path(path),
        "source_trial_path": source.get("source_trial_path"),
        "screen_summary": draft.get("screen_summary") or "",
        "state_guess": draft.get("state_guess") or "",
        "state_count": counts["states"],
        "region_count": counts["regions"],
        "action_template_count": counts["action_templates"],
        "blocker_count": counts["blockers"],
        "verification_rule_count": counts["verification_rules"],
        "modified_at": path.stat().st_mtime,
        "source_category": "recent_learning_draft",
        "pinned": pinned,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    source_image_path = _learning_draft_display_source_image_path(draft)
    source_image_exists = False
    if source_image_path:
        try:
            source_image_exists = _resolve_under_root_path(source_image_path).is_file()
        except ValueError:
            source_image_exists = False
    display_missing = []
    if not source_image_exists:
        display_missing.append("source_image")
    if counts["states"] < 1:
        display_missing.append("states")
    if counts["regions"] < 1:
        display_missing.append("regions")
    entry.update(
        {
            "source_image_path": source_image_path,
            "source_image_exists": source_image_exists,
            "display_completeness_status": "ready" if not display_missing else "incomplete",
            "display_missing_fields": display_missing,
            "recommended_for_panel_review": False,
        }
    )
    if readiness:
        entry.update(
            {
                "readiness_status": readiness.get("readiness_status"),
                "calibration_coverage_rate": readiness.get("calibration_coverage_rate"),
                "pending_calibration_ready_count": readiness.get("pending_calibration_ready_count"),
                "pending_calibration_review_count": readiness.get("pending_calibration_review_count"),
                "pathgraph_status": readiness.get("pathgraph_status"),
            }
        )
    if handoff:
        entry.update(
            {
                "handoff_status": handoff.get("handoff_status"),
                "safe_to_start_after_user_approval": handoff.get("safe_to_start_after_user_approval") is True,
                "rerun_report_status": handoff_future.get("rerun_report_status"),
            }
        )
    if consistency:
        entry.update(
            {
                "consistency_status": consistency.get("consistency_status"),
                "post_batch_refresh_has_batch_plan": consistency_summary.get("post_batch_refresh_has_batch_plan") is True,
                "refresh_blocks_before_future_rerun": consistency_summary.get("refresh_blocks_before_future_rerun") is True,
                "consistency_blocker_count": len(consistency.get("blockers")) if isinstance(consistency.get("blockers"), list) else 0,
            }
        )
    if runbook:
        ready_regions = runbook.get("ready_region_numbers") if isinstance(runbook.get("ready_region_numbers"), list) else []
        review_regions = (
            runbook.get("review_blocked_region_numbers")
            if isinstance(runbook.get("review_blocked_region_numbers"), list)
            else []
        )
        entry.update(
            {
                "runbook_status": runbook.get("runbook_status"),
                "approval_required": runbook.get("approval_required") is True,
                "may_start_model_after_user_approval": runbook.get("may_start_model_after_user_approval") is True,
                "may_run_calibration_batch_now": runbook.get("may_run_calibration_batch_now") is True,
                "runbook_ready_region_count": len(ready_regions),
                "runbook_review_blocked_region_count": len(review_regions),
                "runbook_blocker_count": len(runbook.get("blockers")) if isinstance(runbook.get("blockers"), list) else 0,
            }
        )
    if candidate_review:
        entry.update(
            {
                "pathgraph_candidate_path": candidate_review.get("pathgraph_candidate_path"),
                "candidate_validation_status": candidate_summary.get("validation_status"),
                "candidate_readiness_status": candidate_summary.get("readiness_status"),
            }
        )
    if candidate_preflight:
        entry.update(
            {
                "preflight_status": candidate_preflight.get("preflight_status"),
                "preflight_may_start_model_after_user_approval": (
                    candidate_preflight.get("may_start_model_after_user_approval") is True
                ),
                "preflight_may_run_calibration_batch_now": candidate_preflight.get("may_run_calibration_batch_now") is True,
                "preflight_blocker_count": (
                    len(candidate_preflight.get("blockers")) if isinstance(candidate_preflight.get("blockers"), list) else 0
                ),
            }
        )
    if candidate_demo:
        entry.update(
            {
                "demo_readiness_status": candidate_demo.get("demo_readiness_status"),
                "demo_readiness_may_run_calibration_batch_now": (
                    candidate_demo.get("may_run_calibration_batch_now") is True
                ),
                "demo_readiness_blocker_count": (
                    len(candidate_demo.get("blockers")) if isinstance(candidate_demo.get("blockers"), list) else 0
                ),
            }
        )
    if candidate_approval_packet:
        entry.update(
            {
                "approval_packet_status": candidate_approval_packet.get("approval_packet_status"),
                "approval_packet_requires_explicit_user_approval": (
                    candidate_approval_packet.get("requires_explicit_user_approval") is True
                ),
                "approval_packet_may_run_calibration_batch_now": (
                    candidate_approval_packet.get("may_run_calibration_batch_now") is True
                ),
                "approval_packet_blocker_count": (
                    len(candidate_approval_packet.get("blockers"))
                    if isinstance(candidate_approval_packet.get("blockers"), list)
                    else 0
                ),
            }
        )
    if candidate_calibration_pre_run:
        calibration_snapshot = (
            candidate_calibration_pre_run.get("model_runtime_snapshot")
            if isinstance(candidate_calibration_pre_run.get("model_runtime_snapshot"), dict)
            else {}
        )
        entry.update(
            {
                "calibration_pre_run_status": candidate_calibration_pre_run.get("effective_pre_run_status")
                or candidate_calibration_pre_run.get("pre_run_status"),
                "calibration_pre_run_raw_status": candidate_calibration_pre_run.get("pre_run_status"),
                "calibration_pre_run_checked_at": calibration_snapshot.get("checked_at"),
                "calibration_pre_run_model_ports_clear": calibration_snapshot.get("model_ports_clear") is True,
                "calibration_pre_run_model_processes_clear": calibration_snapshot.get("model_processes_clear") is True,
                "calibration_pre_run_approval_packet_checksum_status": candidate_calibration_pre_run.get(
                    "approval_packet_checksum_status"
                ),
                "calibration_pre_run_requires_explicit_user_approval": (
                    candidate_calibration_pre_run.get("requires_explicit_user_approval") is True
                ),
                "calibration_pre_run_may_run_calibration_batch_now": (
                    candidate_calibration_pre_run.get("may_run_calibration_batch_now") is True
                ),
                "calibration_pre_run_blocker_count": (
                    len(candidate_calibration_pre_run.get("blockers"))
                    if isinstance(candidate_calibration_pre_run.get("blockers"), list)
                    else 0
                ),
            }
        )
    if candidate_pathgraph_integration:
        integration_report_path = candidate_pathgraph_integration.get("report_path")
        entry.update(
            {
                "pathgraph_integration_status": candidate_pathgraph_integration.get("integration_readiness_status"),
                "pathgraph_integration_report_path": (
                    _relative_panel_path(_resolve_under_root_path(integration_report_path)).replace("\\", "/")
                    if isinstance(integration_report_path, str) and integration_report_path.strip()
                    else None
                ),
                "pathgraph_integration_ready_for_audited_review": (
                    candidate_pathgraph_integration.get("ready_for_audited_pathgraph_review") is True
                ),
                "pathgraph_integration_ready_for_runtime_promotion": (
                    candidate_pathgraph_integration.get("ready_for_runtime_pathgraph_promotion") is True
                ),
                "pathgraph_integration_blocker_count": (
                    len(candidate_pathgraph_integration.get("blockers"))
                    if isinstance(candidate_pathgraph_integration.get("blockers"), list)
                    else 0
                ),
            }
        )
    if candidate_current_evidence:
        packet_report_path = candidate_current_evidence.get("report_path")
        packet_calibration = (
            candidate_current_evidence.get("calibration")
            if isinstance(candidate_current_evidence.get("calibration"), dict)
            else {}
        )
        packet_readiness = (
            packet_calibration.get("readiness_summary") if isinstance(packet_calibration.get("readiness_summary"), dict) else {}
        )
        packet_pathgraph = (
            candidate_current_evidence.get("pathgraph")
            if isinstance(candidate_current_evidence.get("pathgraph"), dict)
            else {}
        )
        packet_safety = (
            candidate_current_evidence.get("safety") if isinstance(candidate_current_evidence.get("safety"), dict) else {}
        )
        entry.update(
            {
                "current_evidence_packet_status": "available",
                "current_evidence_packet_path": (
                    _relative_panel_path(_resolve_under_root_path(packet_report_path)).replace("\\", "/")
                    if isinstance(packet_report_path, str) and packet_report_path.strip()
                    else None
                ),
                "current_evidence_packet_coverage": packet_readiness.get("calibration_coverage_rate"),
                "current_evidence_packet_integration_status": packet_pathgraph.get("integration_readiness_status"),
                "current_evidence_packet_runtime_promotion": packet_safety.get("runtime_pathgraph_promotion") is True,
                "current_evidence_packet_model_started": packet_safety.get("model_started") is True,
            }
        )
    if candidate_precise_understanding:
        precise_report_path = candidate_precise_understanding.get("report_path")
        precise_summary = (
            candidate_precise_understanding.get("summary")
            if isinstance(candidate_precise_understanding.get("summary"), dict)
            else {}
        )
        precise_safety = (
            candidate_precise_understanding.get("safety")
            if isinstance(candidate_precise_understanding.get("safety"), dict)
            else {}
        )
        entry.update(
            {
                "precise_understanding_candidate_status": candidate_precise_understanding.get("readiness_status"),
                "precise_understanding_candidate_path": (
                    _relative_panel_path(_resolve_under_root_path(precise_report_path)).replace("\\", "/")
                    if isinstance(precise_report_path, str) and precise_report_path.strip()
                    else None
                ),
                "precise_understanding_candidate_total_regions": precise_summary.get("total_regions"),
                "precise_understanding_candidate_pending_count": precise_summary.get("pending_calibration_count"),
                "precise_understanding_candidate_review_blocked_count": precise_summary.get("review_blocked_count"),
                "precise_understanding_candidate_pathgraph_ready_count": precise_summary.get(
                    "pathgraph_candidate_review_ready_count"
                ),
                "precise_understanding_candidate_runtime_promotion": (
                    precise_safety.get("runtime_pathgraph_promotion") is True
                ),
                "precise_understanding_candidate_model_started": precise_safety.get("model_started") is True,
            }
        )
    if candidate_page_detail:
        page_detail_report_path = candidate_page_detail.get("report_path")
        page_detail_summary = (
            candidate_page_detail.get("summary") if isinstance(candidate_page_detail.get("summary"), dict) else {}
        )
        page_detail_safety = (
            candidate_page_detail.get("safety") if isinstance(candidate_page_detail.get("safety"), dict) else {}
        )
        entry.update(
            {
                "page_detail_candidate_status": candidate_page_detail.get("readiness_status"),
                "page_detail_candidate_path": (
                    _relative_panel_path(_resolve_under_root_path(page_detail_report_path)).replace("\\", "/")
                    if isinstance(page_detail_report_path, str) and page_detail_report_path.strip()
                    else None
                ),
                "page_detail_candidate_region_count": page_detail_summary.get("region_count"),
                "page_detail_candidate_section_count": page_detail_summary.get("section_count"),
                "page_detail_candidate_possible_operation_count": page_detail_summary.get("possible_operation_count"),
                "page_detail_candidate_runtime_promotion": page_detail_safety.get("runtime_pathgraph_promotion") is True,
                "page_detail_candidate_model_started": page_detail_safety.get("model_started") is True,
            }
        )
    if candidate_demo_scaffold:
        scaffold_report_path = candidate_demo_scaffold.get("report_path")
        scaffold_summary = (
            candidate_demo_scaffold.get("summary") if isinstance(candidate_demo_scaffold.get("summary"), dict) else {}
        )
        scaffold_display = (
            candidate_demo_scaffold.get("display_readiness")
            if isinstance(candidate_demo_scaffold.get("display_readiness"), dict)
            else {}
        )
        scaffold_model_only = (
            candidate_demo_scaffold.get("model_only_demo_readiness")
            if isinstance(candidate_demo_scaffold.get("model_only_demo_readiness"), dict)
            else {}
        )
        scaffold_provenance = (
            candidate_demo_scaffold.get("model_provenance_audit")
            if isinstance(candidate_demo_scaffold.get("model_provenance_audit"), dict)
            else {}
        )
        scaffold_safety = (
            candidate_demo_scaffold.get("safety") if isinstance(candidate_demo_scaffold.get("safety"), dict) else {}
        )
        entry.update(
            {
                "learning_demo_scaffold_status": "available",
                "learning_demo_scaffold_path": (
                    _relative_panel_path(_resolve_under_root_path(scaffold_report_path)).replace("\\", "/")
                    if isinstance(scaffold_report_path, str) and scaffold_report_path.strip()
                    else None
                ),
                "learning_demo_scaffold_artifact_count": scaffold_summary.get("artifact_count"),
                "learning_demo_scaffold_failure_count": scaffold_summary.get("failure_count"),
                "learning_demo_scaffold_model_preview_status": scaffold_summary.get(
                    "model_generated_pathgraph_preview_status"
                ),
                "learning_demo_scaffold_model_preview_region_count": scaffold_summary.get(
                    "model_generated_pathgraph_preview_region_count"
                ),
                "learning_demo_scaffold_model_preview_action_count": scaffold_summary.get(
                    "model_generated_pathgraph_preview_action_count"
                ),
                "learning_demo_scaffold_model_page_detail_section_count": scaffold_summary.get(
                    "model_generated_page_detail_section_count"
                ),
                "learning_demo_scaffold_model_page_detail_operation_count": scaffold_summary.get(
                    "model_generated_page_detail_possible_operation_count"
                ),
                "learning_demo_scaffold_model_only_status": scaffold_model_only.get("status"),
                "learning_demo_scaffold_model_only_ready": scaffold_model_only.get("ready") is True,
                "learning_demo_scaffold_page_detail_ready": (
                    scaffold_display.get("pathgraph_detail_can_show_page_detail") is True
                ),
                "learning_demo_scaffold_model_origin_status": scaffold_provenance.get("status"),
                "learning_demo_scaffold_actual_model_call_evidence_count": scaffold_provenance.get(
                    "actual_model_call_evidence_count"
                ),
                "learning_demo_scaffold_assisted_evidence_count": scaffold_provenance.get(
                    "assisted_or_human_review_evidence_count"
                ),
                "learning_demo_scaffold_fully_model_generated": (
                    scaffold_provenance.get("meets_fully_model_generated_demo_requirement") is True
                ),
                "learning_demo_scaffold_runtime_promotion": scaffold_safety.get("runtime_pathgraph_promotion") is True,
                "learning_demo_scaffold_model_started": scaffold_safety.get("model_started") is True,
            }
        )
    if candidate_demo_goal_readiness:
        goal_report_path = candidate_demo_goal_readiness.get("report_path")
        goal_summary = (
            candidate_demo_goal_readiness.get("summary")
            if isinstance(candidate_demo_goal_readiness.get("summary"), dict)
            else {}
        )
        fresh_model_acceptance = (
            candidate_demo_goal_readiness.get("fresh_model_chain_acceptance")
            if isinstance(candidate_demo_goal_readiness.get("fresh_model_chain_acceptance"), dict)
            else {}
        )
        fresh_model_source_breakdown = (
            fresh_model_acceptance.get("source_breakdown")
            if isinstance(fresh_model_acceptance.get("source_breakdown"), dict)
            else {}
        )
        fresh_model_blockers = (
            fresh_model_acceptance.get("blocking_reasons")
            if isinstance(fresh_model_acceptance.get("blocking_reasons"), list)
            else []
        )
        fresh_model_replacement_plan = (
            fresh_model_acceptance.get("replacement_plan")
            if isinstance(fresh_model_acceptance.get("replacement_plan"), dict)
            else {}
        )
        fresh_model_replacement_steps = (
            fresh_model_replacement_plan.get("replacement_steps")
            if isinstance(fresh_model_replacement_plan.get("replacement_steps"), list)
            else []
        )
        fresh_model_sources_to_replace = (
            fresh_model_replacement_plan.get("sources_to_replace")
            if isinstance(fresh_model_replacement_plan.get("sources_to_replace"), list)
            else []
        )
        presentation_acceptance = (
            candidate_demo_goal_readiness.get("presentation_acceptance")
            if isinstance(candidate_demo_goal_readiness.get("presentation_acceptance"), dict)
            else {}
        )
        presentation_blockers = (
            presentation_acceptance.get("blocking_reasons")
            if isinstance(presentation_acceptance.get("blocking_reasons"), list)
            else []
        )
        goal_chain = (
            candidate_demo_goal_readiness.get("demo_chain_manifest")
            if isinstance(candidate_demo_goal_readiness.get("demo_chain_manifest"), dict)
            else {}
        )
        goal_chain_steps = goal_chain.get("steps") if isinstance(goal_chain.get("steps"), list) else []
        goal_chain_ready_steps = [
            item for item in goal_chain_steps if isinstance(item, dict) and item.get("stage_ready_for_display") is True
        ]
        goal_chain_missing_proofs = sum(
            len(item.get("missing_proof_fields"))
            for item in goal_chain_steps
            if isinstance(item, dict) and isinstance(item.get("missing_proof_fields"), list)
        )
        goal_chain_blockers = (
            goal_chain.get("final_goal_blockers")
            if isinstance(goal_chain.get("final_goal_blockers"), list)
            else candidate_demo_goal_readiness.get("blocking_reasons")
            if isinstance(candidate_demo_goal_readiness.get("blocking_reasons"), list)
            else []
        )
        goal_safety = (
            candidate_demo_goal_readiness.get("safety")
            if isinstance(candidate_demo_goal_readiness.get("safety"), dict)
            else {}
        )
        entry.update(
            {
                "learning_demo_goal_status": candidate_demo_goal_readiness.get("demo_goal_status"),
                "learning_demo_goal_path": (
                    _relative_panel_path(_resolve_under_root_path(goal_report_path)).replace("\\", "/")
                    if isinstance(goal_report_path, str) and goal_report_path.strip()
                    else None
                ),
                "learning_demo_goal_display_ready": candidate_demo_goal_readiness.get("display_demo_ready") is True,
                "learning_demo_goal_final_complete": candidate_demo_goal_readiness.get("final_goal_complete") is True,
                "learning_demo_goal_passed_requirement_count": goal_summary.get("passed_requirement_count"),
                "learning_demo_goal_failed_requirement_count": goal_summary.get("failed_requirement_count"),
                "learning_demo_goal_blocker_count": (
                    len(candidate_demo_goal_readiness.get("blocking_reasons"))
                    if isinstance(candidate_demo_goal_readiness.get("blocking_reasons"), list)
                    else 0
                ),
                "learning_demo_chain_can_be_demoed": goal_chain.get("chain_can_be_demoed") is True,
                "learning_demo_chain_final_complete": goal_chain.get("chain_is_final_goal_complete") is True,
                "learning_demo_chain_ready_step_count": len(goal_chain_ready_steps),
                "learning_demo_chain_total_step_count": len(goal_chain_steps),
                "learning_demo_chain_missing_proof_count": goal_chain_missing_proofs,
                "learning_demo_chain_blocker_count": len(goal_chain_blockers),
                "learning_demo_goal_runtime_promotion": goal_safety.get("runtime_pathgraph_promotion") is True,
                "learning_demo_goal_model_started": goal_safety.get("model_started") is True,
            }
        )
        if fresh_model_acceptance:
            entry.update(
                {
                    "fresh_model_acceptance_status": fresh_model_acceptance.get("acceptance_status"),
                    "fresh_model_chain_accepted": fresh_model_acceptance.get("accepted") is True,
                    "fresh_model_counts_as_final_goal_completion": (
                        fresh_model_acceptance.get("counts_as_final_goal_completion") is True
                    ),
                    "fresh_model_actual_model_call_evidence_count": fresh_model_acceptance.get(
                        "actual_model_call_evidence_count"
                    ),
                    "fresh_model_assisted_or_human_review_evidence_count": fresh_model_acceptance.get(
                        "assisted_or_human_review_evidence_count"
                    ),
                    "fresh_model_acceptance_blocker_count": len(fresh_model_blockers),
                    "fresh_model_source_breakdown_actual_model_call": fresh_model_source_breakdown.get(
                        "actual_model_call"
                    ),
                    "fresh_model_source_breakdown_assisted_or_human_review": fresh_model_source_breakdown.get(
                        "assisted_or_human_review"
                    ),
                    "fresh_model_source_breakdown_fixture_only": fresh_model_source_breakdown.get("fixture_only"),
                    "fresh_model_source_breakdown_recorded_model_output": fresh_model_source_breakdown.get(
                        "recorded_model_output"
                    ),
                }
            )
        if presentation_acceptance:
            entry.update(
                {
                    "presentation_acceptance_status": presentation_acceptance.get("acceptance_status"),
                    "presentation_accepted": presentation_acceptance.get("accepted") is True,
                    "presentation_same_source_three_image_evidence": (
                        presentation_acceptance.get("same_source_three_image_evidence") is True
                    ),
                    "presentation_frontend_revision_matches": (
                        presentation_acceptance.get("frontend_revision_matches") is True
                    ),
                    "presentation_desktop_viewport_covered": (
                        presentation_acceptance.get("desktop_viewport_covered") is True
                    ),
                    "presentation_narrow_viewport_covered": (
                        presentation_acceptance.get("narrow_viewport_covered") is True
                    ),
                    "presentation_blocker_count": len(presentation_blockers),
                }
            )
            if fresh_model_replacement_plan:
                entry.update(
                    {
                        "fresh_model_replacement_required": (
                            fresh_model_replacement_plan.get("replacement_required") is True
                        ),
                        "fresh_model_replacement_plan_status": fresh_model_replacement_plan.get("plan_status"),
                        "fresh_model_replacement_sources_to_replace": [
                            str(item) for item in fresh_model_sources_to_replace if str(item).strip()
                        ],
                        "fresh_model_replacement_required_source_type": fresh_model_replacement_plan.get(
                            "required_source_type"
                        ),
                        "fresh_model_replacement_step_count": len(fresh_model_replacement_steps),
                        "fresh_model_replacement_command_executes_now_count": sum(
                            1
                            for item in fresh_model_replacement_steps
                            if isinstance(item, dict) and item.get("command_executes_now") is True
                        ),
                    }
                )
    return entry


def _is_learning_draft_source_candidate_file(path: Path) -> bool:
    return path.name in {"trial_result.json", "reviewed_template_candidate.json", "pathgraph_candidate.json"}


def _learning_draft_candidate_has_display_evidence(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    for draft in _learning_draft_candidate_drafts(payload):
        states = _learning_draft_candidate_section(draft, "states")
        regions = _learning_draft_candidate_section(draft, "regions")
        if not states or not regions:
            continue
        source_image_path = _learning_draft_display_source_image_path(draft)
        if not source_image_path:
            continue
        try:
            if _resolve_under_root_path(source_image_path).is_file():
                return True
        except ValueError:
            continue
    return False


def _learning_draft_trial_source_entry(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("learning draft source must be a JSON object")
    drafts = _learning_draft_candidate_drafts(payload)
    if not drafts:
        raise ValueError("trial result does not contain a learning draft")
    draft = max(
        drafts,
        key=lambda item: len(_learning_draft_candidate_section(item, "states"))
        + len(_learning_draft_candidate_section(item, "regions")),
    )
    sections = {
        name: len(_learning_draft_candidate_section(draft, name))
        for name in ("states", "regions", "action_templates", "blockers", "verification_rules")
    }
    source_image_path = _learning_draft_display_source_image_path(draft)
    source_image_exists = False
    if source_image_path:
        try:
            source_image_exists = _resolve_under_root_path(source_image_path).is_file()
        except ValueError:
            source_image_exists = False
    display_missing = []
    if not source_image_exists:
        display_missing.append("source_image")
    if sections["states"] < 1:
        display_missing.append("states")
    if sections["regions"] < 1:
        display_missing.append("regions")
    return {
        "source_path": _relative_panel_path(path),
        "source_trial_path": _relative_panel_path(path),
        "screen_summary": str(draft.get("screen_summary") or payload.get("summary") or ""),
        "state_guess": str(draft.get("state_guess") or payload.get("state_hint") or ""),
        "state_count": sections["states"],
        "region_count": sections["regions"],
        "action_template_count": sections["action_templates"],
        "blocker_count": sections["blockers"],
        "verification_rule_count": sections["verification_rules"],
        "modified_at": path.stat().st_mtime,
        "source_category": "recent_learning_draft",
        "pinned": False,
        "source_image_path": source_image_path,
        "source_image_exists": source_image_exists,
        "display_completeness_status": "ready" if not display_missing else "incomplete",
        "display_missing_fields": display_missing,
        "recommended_for_panel_review": False,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }


def _learning_draft_candidate_drafts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [payload.get("draft"), payload.get("best_learning_draft"), payload.get("learning_draft")]
    two_stage = payload.get("two_stage_understanding")
    if isinstance(two_stage, dict):
        candidates.append(two_stage.get("learning_draft"))
    return [item for item in candidates if isinstance(item, dict)]


def _learning_draft_candidate_section(draft: dict[str, Any], name: str) -> list[Any]:
    direct = draft.get(name)
    if isinstance(direct, list):
        return direct
    workflow_draft = draft.get("workflow_draft") if isinstance(draft.get("workflow_draft"), dict) else {}
    interface_draft = draft.get("interface_draft") if isinstance(draft.get("interface_draft"), dict) else {}
    container = interface_draft if name == "regions" else workflow_draft
    value = container.get(name)
    return value if isinstance(value, list) else []


def _learning_draft_display_source_image_path(draft: dict[str, Any]) -> str:
    page_details = draft.get("page_details") if isinstance(draft.get("page_details"), dict) else {}
    screen = page_details.get("screen") if isinstance(page_details.get("screen"), dict) else {}
    candidates = (
        screen.get("compiled_overlay_path"),
        screen.get("full_screen_understanding_overlay_path"),
        screen.get("source_image_path"),
        screen.get("image_path"),
        screen.get("screenshot_path"),
        page_details.get("compiled_overlay_path"),
        page_details.get("full_screen_understanding_overlay_path"),
        page_details.get("source_image_path"),
        page_details.get("image_path"),
        page_details.get("screenshot_path"),
        draft.get("source_image_path"),
        draft.get("image_path"),
        draft.get("screenshot_path"),
    )
    return next((str(value).strip() for value in candidates if str(value or "").strip()), "")


def _relative_panel_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT_DIR.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _resolve_panel_artifact_file(path: str) -> Path:
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = ROOT_DIR / resolved
    resolved = resolved.resolve()
    allowed_roots = [(ROOT_DIR / "artifacts").resolve(), (ROOT_DIR / "logs").resolve()]
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        raise ValueError(str(resolved))
    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(str(resolved))
    return resolved


def _resolve_scoped_capture_segment_records(
    records: list[PanelScopedCaptureSegmentRecord],
) -> list[dict[str, Any]]:
    resolved_records: list[dict[str, Any]] = []
    for record in records:
        resolved = record.model_dump()
        resolved["image_path"] = str(_resolve_panel_artifact_file(record.image_path))
        scroll_trace_path = str(record.scroll_trace_path or "").strip()
        if scroll_trace_path:
            resolved["scroll_trace_path"] = str(_resolve_panel_artifact_file(scroll_trace_path))
        resolved_records.append(resolved)
    return resolved_records


def _resolve_panel_learning_image_path(path: str) -> Path:
    return _resolve_panel_artifact_file(path)


def _load_two_stage_fusion_status_for_learning_draft(path: str | None) -> dict[str, Any] | None:
    path_text = str(path or "").strip()
    if not path_text:
        return None
    resolved = _resolve_panel_artifact_file(path_text)
    report = json.loads(resolved.read_text(encoding="utf-8-sig"))
    if not isinstance(report, dict):
        raise ValueError("two-stage report must be a JSON object")
    fusion_status = report.get("fusion_status") if isinstance(report.get("fusion_status"), dict) else {}
    if not fusion_status:
        fusion_status = fusion_status_from_two_stage(report)
    fusion_status = dict(fusion_status)
    fusion_status["source_two_stage_report_path"] = _relative_panel_path(resolved)
    fusion_status["attachment_source"] = "panel_run_learning_recognition_trial.two_stage_report_path"
    fusion_status["display_only"] = True
    fusion_status["artifact_is_authorization"] = False
    fusion_status["execute_binding_enabled"] = False
    stage1_gate = report.get("stage1_gate") if isinstance(report.get("stage1_gate"), dict) else {}
    stage2 = report.get("stage2_numbering") if isinstance(report.get("stage2_numbering"), dict) else {}
    fusion = report.get("fusion") if isinstance(report.get("fusion"), dict) else {}
    review_boxes = fusion.get("fused_review_boxes") if isinstance(fusion.get("fused_review_boxes"), list) else []
    fusion_summary = fusion_status.get("summary") if isinstance(fusion_status.get("summary"), dict) else {}
    fusion_status["stage1_gate_status"] = _str(stage1_gate.get("status"))
    fusion_status["stage2_numbering_skipped"] = bool(report.get("stage2_numbering_skipped"))
    fusion_status["review_box_count"] = len(review_boxes) or _int_or_zero(fusion_summary.get("fused_review_box_count"))
    fusion_status["stage2_numbered_region_count"] = len(stage2.get("regions") if isinstance(stage2.get("regions"), list) else [])
    return fusion_status


def _attach_current_calibrated_fusion_overlay(
    fusion_status: dict[str, Any],
    observation_evidence: dict[str, Any],
) -> dict[str, Any]:
    """仅把真实完成的 Stage2 + VISTA 融合图登记为最终展示图。"""

    result = dict(fusion_status)
    overlay_evidence = (
        observation_evidence.get("coordinate_overlay")
        if isinstance(observation_evidence.get("coordinate_overlay"), dict)
        else {}
    )
    target_summary = (
        observation_evidence.get("learn_all_targets_summary")
        if isinstance(observation_evidence.get("learn_all_targets_summary"), dict)
        else {}
    )
    qualifies = (
        _str(result.get("stage1_gate_status")) == "passed"
        and overlay_evidence.get("status") == "ready"
        and overlay_evidence.get("base_visual_source") == "two_stage_numbered_overlay"
        and overlay_evidence.get("final_fusion_overlay") is True
        and target_summary.get("coordinate_calibration_status") == "model_validation_completed"
        and _int_or_zero(target_summary.get("calibration_target_count")) > 0
        and _int_or_zero(target_summary.get("vista_validated_count")) > 0
    )
    overlay_value = _str(observation_evidence.get("coordinate_overlay_path"))
    if not qualifies or not overlay_value:
        return result

    overlay_path = _resolve_panel_learning_image_path(overlay_value)
    relative_overlay = _relative_panel_path(overlay_path)
    previous_compiled = _str(result.get("compiled_overlay_path"))
    previous_full = _str(result.get("full_screen_understanding_overlay_path"))
    result.update(
        {
            "stage2_compiled_overlay_path": previous_compiled or previous_full,
            "stage2_full_screen_understanding_overlay_path": previous_full or previous_compiled,
            "calibration_overlay_path": relative_overlay,
            "precise_calibration_overlay_path": relative_overlay,
            "compiled_overlay_path": relative_overlay,
            "full_screen_understanding_overlay_path": relative_overlay,
            "display_overlay_source": "two_stage_plus_precise_calibration",
            "final_fusion_overlay": True,
            "calibration_evidence_status": "model_validation_completed",
        }
    )
    return result


def _load_two_stage_report_for_learning_draft(path: str | None) -> dict[str, Any] | None:
    path_text = str(path or "").strip()
    if not path_text:
        return None
    resolved = _resolve_panel_artifact_file(path_text)
    report = json.loads(resolved.read_text(encoding="utf-8-sig"))
    if not isinstance(report, dict):
        raise ValueError("two-stage report must be a JSON object")
    report = dict(report)
    report["source_two_stage_report_path"] = _relative_panel_path(resolved)
    report["attachment_source"] = "panel_run_learning_recognition_trial.two_stage_report_path"
    report["display_only"] = True
    report["artifact_is_authorization"] = False
    report["execute_binding_enabled"] = False
    return report


def _attach_two_stage_numbered_review_regions_to_observe_bundle(
    observe_bundle: dict[str, Any],
    path: str | None,
) -> dict[str, Any]:
    path_text = str(path or "").strip()
    if not path_text:
        return {"attached_count": 0, "reason": "no_two_stage_report_path"}
    resolved = _resolve_panel_artifact_file(path_text)
    report = json.loads(resolved.read_text(encoding="utf-8-sig"))
    if not isinstance(report, dict):
        raise ValueError("two-stage report must be a JSON object")
    review_regions = _two_stage_numbered_items_as_review_regions(report, source_path=_relative_panel_path(resolved))
    if not review_regions:
        _record_two_stage_review_evidence_summary(
            observe_bundle,
            source_path=_relative_panel_path(resolved),
            attached_count=0,
            skipped_reason="no_numbered_items",
        )
        return {"attached_count": 0, "reason": "no_numbered_items", "source_two_stage_report_path": _relative_panel_path(resolved)}
    sources = observe_bundle.setdefault("sources", {})
    if not isinstance(sources, dict):
        sources = {}
        observe_bundle["sources"] = sources
    vision = sources.get("vision") if isinstance(sources.get("vision"), dict) else {}
    regions = vision.get("regions") if isinstance(vision.get("regions"), list) else []
    vision["regions"] = [*regions, *review_regions]
    sources["vision"] = vision
    _record_two_stage_review_evidence_summary(
        observe_bundle,
        source_path=_relative_panel_path(resolved),
        attached_count=len(review_regions),
        skipped_reason="",
    )
    return {
        "attached_count": len(review_regions),
        "reason": "attached_two_stage_numbered_items_as_review_only_regions",
        "source_two_stage_report_path": _relative_panel_path(resolved),
    }


def _record_two_stage_review_evidence_summary(
    observe_bundle: dict[str, Any],
    *,
    source_path: str,
    attached_count: int,
    skipped_reason: str,
) -> None:
    evidence = observe_bundle.get("panel_observation_evidence")
    if not isinstance(evidence, dict):
        evidence = {}
        observe_bundle["panel_observation_evidence"] = evidence
    evidence["two_stage_numbered_review_evidence"] = {
        "contract_version": "panel_two_stage_numbered_review_evidence_v1",
        "source_two_stage_report_path": source_path,
        "attached_count": int(attached_count),
        "skipped_reason": skipped_reason,
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "interpretation": (
            "Stage2 numbered items are read-only learning draft evidence. They are not calibrated targets, "
            "click authorization, or Runtime PathGraph promotion evidence."
        ),
    }


def _two_stage_numbered_items_as_review_regions(report: dict[str, Any], *, source_path: str) -> list[dict[str, Any]]:
    stage2 = report.get("stage2_numbering") if isinstance(report.get("stage2_numbering"), dict) else {}
    regions = stage2.get("regions") if isinstance(stage2.get("regions"), list) else []
    out: list[dict[str, Any]] = []
    for region_index, region in enumerate(regions, start=1):
        if not isinstance(region, dict):
            continue
        parent_region_id = _str(region.get("region_id") or f"stage2_region_{region_index}")
        parent_label = _str(region.get("label") or parent_region_id)
        items = region.get("numbered_items") if isinstance(region.get("numbered_items"), list) else []
        for item_index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            bbox = _normalized_bbox(item.get("bbox"))
            if not bbox.get("w") or not bbox.get("h"):
                continue
            label = _str(item.get("label") or item.get("text") or item.get("name") or item.get("number"))
            if not label:
                continue
            item_id = _str(item.get("item_id") or item.get("id") or item.get("number") or f"item_{item_index}")
            out.append(
                {
                    "id": f"two_stage_review_{parent_region_id}_{item_id}",
                    "region_id": f"two_stage_review_{parent_region_id}_{item_id}",
                    "label": label,
                    "role": _str(item.get("role") or "review_only"),
                    "bbox": bbox,
                    "description": f"Stage2 read-only item {item.get('number') or item_index} in {parent_label}",
                    "parent_region_id": parent_region_id,
                    "parent_region_label": parent_label,
                    "stage2_number": _str(item.get("number")),
                    "source": "two_stage_numbered_item_review_only",
                    "source_two_stage_report_path": source_path,
                    "review_only": True,
                    "display_only": True,
                    "artifact_is_authorization": False,
                    "execute_binding_enabled": False,
                    "no_click_authorization": True,
                    "text_lines": [
                        _str(line)
                        for line in item.get("text_lines", [])
                        if _str(line)
                    ]
                    if isinstance(item.get("text_lines"), list)
                    else [],
                }
            )
    return out


def _precise_understanding_status_from_fusion_status(fusion_status: dict[str, Any] | None) -> str:
    if not fusion_status:
        return "not_attached"
    if fusion_status.get("stage1_gate_status") == "blocked_before_stage2_numbering":
        return "review_overlay_attached_stage1_blocked"
    if _int_or_zero(fusion_status.get("review_box_count")) or fusion_status.get("compiled_overlay_path"):
        return "review_overlay_attached"
    return "attached_without_review_overlay"


def _learning_recognition_review_box_status(
    *,
    two_stage_review_evidence: dict[str, Any],
    two_stage_fusion_status: dict[str, Any] | None,
) -> dict[str, Any]:
    attached_count = _int_or_zero(two_stage_review_evidence.get("attached_count"))
    fusion_status = two_stage_fusion_status if isinstance(two_stage_fusion_status, dict) else {}
    fusion_summary = fusion_status.get("summary") if isinstance(fusion_status.get("summary"), dict) else {}
    review_box_count = max(
        attached_count,
        _int_or_zero(fusion_status.get("review_box_count")),
        _int_or_zero(fusion_summary.get("fused_review_box_count")),
    )
    numbered_region_count = _int_or_zero(fusion_status.get("stage2_numbered_region_count"))
    stage1_gate_status = _str(fusion_status.get("stage1_gate_status"))
    if stage1_gate_status == "blocked_before_stage2_numbering":
        status = "blocked_before_stage2_numbering"
    elif review_box_count or numbered_region_count:
        status = "review_boxes_ready"
    else:
        status = "empty"
    return {
        "contract_version": "panel_learning_review_box_status_v1",
        "status": status,
        "target_count": 0,
        "validated_count": 0,
        "invalid_count": 0,
        "review_box_count": review_box_count,
        "stage1_gate_status": stage1_gate_status,
        "stage2_numbered_region_count": numbered_region_count,
        "source_two_stage_report_path": _str(fusion_status.get("source_two_stage_report_path")),
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
        "no_click_authorization": True,
        "interpretation": (
            "review boxes are learning-draft display evidence only; target_count remains zero until "
            "separate grounding evidence creates executable candidates"
        ),
    }


def _attach_two_stage_fusion_status_to_learning_result(
    result: dict[str, Any],
    fusion_status: dict[str, Any],
) -> None:
    draft = result.get("learning_draft") if isinstance(result.get("learning_draft"), dict) else {}
    if not draft:
        return
    page_details = draft.get("page_details") if isinstance(draft.get("page_details"), dict) else {}
    pipeline_audit = (
        page_details.get("pipeline_audit")
        if isinstance(page_details.get("pipeline_audit"), dict)
        else {}
    )
    current_status = (
        pipeline_audit.get("precise_understanding_fusion_status")
        if isinstance(pipeline_audit.get("precise_understanding_fusion_status"), dict)
        else {}
    )
    attached_status = dict(fusion_status)
    current_values = {
        key: value
        for key, value in current_status.items()
        if value not in (None, "", [], {})
    }
    if attached_status.get("final_fusion_overlay") is True:
        final_overlay_keys = {
            "compiled_overlay_path",
            "full_screen_understanding_overlay_path",
            "calibration_overlay_path",
            "precise_calibration_overlay_path",
            "stage2_compiled_overlay_path",
            "stage2_full_screen_understanding_overlay_path",
            "display_overlay_source",
            "final_fusion_overlay",
            "calibration_evidence_status",
        }
        attached_status.update(
            {
                key: value
                for key, value in current_values.items()
                if key not in final_overlay_keys or key not in attached_status
            }
        )
    else:
        attached_status.update(current_values)
    pipeline_audit["precise_understanding_fusion_status"] = attached_status
    page_details["pipeline_audit"] = pipeline_audit
    if attached_status.get("compiled_overlay_path"):
        page_details["compiled_overlay_path"] = attached_status.get("compiled_overlay_path")
    if attached_status.get("full_screen_understanding_overlay_path"):
        page_details["full_screen_understanding_overlay_path"] = attached_status.get(
            "full_screen_understanding_overlay_path"
        )
    draft["page_details"] = page_details
    result["learning_draft"] = draft


def _save_panel_learning_trial(payload: dict[str, Any], *, app_name: str) -> str:
    run_root = ROOT_DIR / "artifacts" / "learning-runs"
    run_root.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
    millis = int((time.time() % 1) * 1000)
    safe_app = _safe_panel_learning_slug(app_name or payload.get("app_name") or "unknown_app")
    run_dir = run_root / f"panel_{timestamp}-{millis:03d}_{safe_app}"
    run_dir.mkdir(parents=True, exist_ok=False)
    trial_path = run_dir / "trial_result.json"
    trial_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        return str(trial_path.relative_to(ROOT_DIR))
    except ValueError:
        return str(trial_path)


def _safe_panel_learning_slug(value: Any) -> str:
    text = str(value or "unknown_app").strip().lower()
    cleaned = "".join(ch if ch.isalnum() or ch in "_.-" else "_" for ch in text)
    cleaned = "_".join(part for part in cleaned.split("_") if part)
    return cleaned[:80] or "unknown_app"


def _learning_draft_section_counts(draft: Any) -> dict[str, int]:
    if not isinstance(draft, dict):
        return {"states": 0, "regions": 0, "action_templates": 0, "blockers": 0, "verification_rules": 0}
    workflow = draft.get("workflow_draft") if isinstance(draft.get("workflow_draft"), dict) else {}
    interface = draft.get("interface_draft") if isinstance(draft.get("interface_draft"), dict) else {}
    states = workflow.get("states") or draft.get("states") or []
    regions = interface.get("regions") or draft.get("regions") or []
    actions = workflow.get("action_templates") or draft.get("action_templates") or []
    rules = workflow.get("verification_rules") or draft.get("verification_rules") or []
    return {
        "states": len(states),
        "regions": len(regions),
        "action_templates": len(actions),
        "blockers": len(draft.get("blockers") or []),
        "verification_rules": len(rules),
    }


def _normalized_bbox(value: Any) -> dict[str, int]:
    value = value if isinstance(value, dict) else {}
    return {
        "x": _int_or_zero(value.get("x")),
        "y": _int_or_zero(value.get("y")),
        "w": max(0, _int_or_zero(value.get("w") if "w" in value else value.get("width"))),
        "h": max(0, _int_or_zero(value.get("h") if "h" in value else value.get("height"))),
    }


def _str(value: Any) -> str:
    return str(value or "").strip()


def _int_or_zero(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


@router.get("/panel/list_traces", include_in_schema=False)
def list_traces(limit: int = 50, include_tests: bool = False, mode: Optional[str] = None) -> APIResponse:
    """List recent trace files from logs/traces/."""
    try:
        mode_filter = str(mode or "").strip().lower()
        if mode_filter not in {"", "learn", "execute"}:
            return APIResponse(success=False, message="Invalid trace mode", data=None, error=ErrorModel(code="invalid_trace_mode", details=mode))
        traces_dir = ROOT_DIR / "logs" / "traces"
        if not traces_dir.exists():
            return APIResponse(success=True, message="No traces yet", data={"traces": []}, error=None)
        requested_limit = max(0, min(int(limit), 500))
        if requested_limit == 0:
            return APIResponse(success=True, message="0 traces", data={"traces": []}, error=None)
        candidates: list[tuple[int, str, Path, str, int, float]] = []
        for category_dir in sorted(traces_dir.iterdir(), reverse=True):
            if not category_dir.is_dir():
                continue
            for tf in category_dir.iterdir():
                if tf.suffix != ".json":
                    continue
                try:
                    stat = tf.stat()
                except OSError:
                    continue
                candidates.append((
                    stat.st_mtime_ns,
                    tf.name,
                    tf,
                    category_dir.name,
                    stat.st_size,
                    stat.st_mtime,
                ))
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        files = []
        for _, _, tf, category, size, modified in candidates:
            if len(files) >= requested_limit:
                break
            meta, references_pytest_temp = _trace_list_candidate_metadata(tf)
            if not include_tests and references_pytest_temp:
                continue
            if mode_filter and meta.get("agent_mode") != mode_filter:
                continue
            files.append({
                "name": tf.name,
                "path": str(tf.resolve()),
                "category": category,
                **meta,
                "size": size,
                "modified": modified,
            })
        return APIResponse(success=True, message=f"{len(files)} traces", data={"traces": files}, error=None)
    except Exception as exc:
        return APIResponse(success=False, message="List failed", data=None, error=ErrorModel(code="trace_list_failed", details=str(exc)))


def _trace_list_candidate_metadata(path: Path) -> tuple[dict[str, str], bool]:
    parts = path.stem.split("__")
    operation = parts[1] if len(parts) > 1 else ""
    metadata: dict[str, str] = {"operation": operation, "agent_mode": "", "mode_contract_version": "", "contract_version": ""}
    try:
        source_bytes = path.read_bytes()
    except Exception:
        return metadata, False
    normalized = source_bytes.decode("utf-8-sig", errors="ignore").replace("\\\\", "\\").replace("/", "\\").casefold()
    references_pytest_temp = "\\pytest-of-" in normalized or "\\pytest-" in normalized
    try:
        payload = json.loads(source_bytes.decode("utf-8-sig"))
    except Exception:
        return metadata, references_pytest_temp
    trace = payload.get("result") if isinstance(payload, dict) and isinstance(payload.get("result"), dict) else payload
    request = payload.get("request") if isinstance(payload, dict) and isinstance(payload.get("request"), dict) else {}
    if isinstance(trace, dict):
        metadata["agent_mode"] = str(trace.get("agent_mode") or request.get("agent_mode") or "")
        metadata["mode_contract_version"] = str(trace.get("mode_contract_version") or "")
        metadata["contract_version"] = str(trace.get("contract_version") or "")
        plan = trace.get("recognition_plan")
        if not metadata["agent_mode"] and isinstance(plan, dict):
            metadata["agent_mode"] = str(plan.get("agent_mode") or "")
            metadata["mode_contract_version"] = str(plan.get("mode_contract_version") or "")
    return metadata, references_pytest_temp


@router.get("/panel/inspect_trace", include_in_schema=False)
def inspect_trace(path: str) -> APIResponse:
    """Read a trace JSON and return a parsed summary for the inspector panel."""
    try:
        resolved = Path(path).expanduser()
        if not resolved.is_absolute():
            resolved = ROOT_DIR / resolved
        resolved = resolved.resolve()
        if not resolved.exists() or not resolved.is_file():
            return APIResponse(success=False, message="Trace file not found", data=None, error=ErrorModel(code="trace_not_found", details=str(path)))
        raw_trace = json.loads(resolved.read_text(encoding="utf-8-sig"))
        trace = raw_trace.get("result") if isinstance(raw_trace, dict) and isinstance(raw_trace.get("result"), dict) else raw_trace

        parsed: dict[str, Any] = {
            "file": resolved.name,
            "path": str(resolved),
            "sections": {},  # raw trace sections keyed by stage id
            "flow_stages": [],
        }

        # Timings
        timings = trace.get("timings") or trace.get("runtime_timing_v1") or {}
        if isinstance(timings, dict):
            steps = timings.get("steps") or []
            total_ms = timings.get("total_ms") or 0
            parsed["total_time"] = f"{total_ms / 1000:.1f}s" if total_ms else ""
            parsed["stages"] = [{"name": s.get("name") or "unknown_step", "ms": s.get("elapsed_ms") or s.get("duration_ms") or 0} for s in steps[:20]]
            parsed["sections"]["timings"] = timings
        else:
            parsed["total_time"] = ""
            parsed["stages"] = []

        # Contract / task
        parsed["contract"] = trace.get("contract_version") or trace.get("task") or ""

        # Request info (鈫?goal stage)
        request = raw_trace.get("request") or trace.get("request") or {}
        if isinstance(request, dict):
            parsed["goal"] = request.get("goal") or trace.get("goal") or ""
            parsed["app_name"] = request.get("app_name") or trace.get("app_name") or ""
            parsed["state_hint"] = request.get("state_hint") or trace.get("state_hint") or ""
            parsed["provider"] = request.get("provider_mode") or trace.get("provider_mode") or ""
            if not parsed["contract"]:
                parsed["contract"] = request.get("task") or ""
            parsed["sections"]["goal"] = request

        # Capture info
        parsed["sections"]["capture"] = trace.get("live_capture") or trace.get("capture") or {
            "image_path": trace.get("image_path") or (request.get("image_path") if isinstance(request, dict) else "") or "",
        }
        plan = trace.get("recognition_plan") or (trace if trace.get("candidate_result") or trace.get("pre_click_decision") else {})
        if not isinstance(plan, dict):
            plan = {}
        plan_image_path = plan.get("image_path") or trace.get("image_path") or parsed["sections"].get("capture", {}).get("image_path")
        parse_result = trace.get("parse_result") if isinstance(trace.get("parse_result"), dict) else {}
        if not parse_result and isinstance(plan.get("parse_result"), dict):
            parse_result = plan["parse_result"]
        model_io = _first_dict(
            trace.get("model_io"),
            plan.get("model_io"),
            raw_trace.get("model_io") if isinstance(raw_trace, dict) else None,
            ((trace.get("degraded_reason") or {}).get("model_io")) if isinstance(trace.get("degraded_reason"), dict) else None,
            ((trace.get("raw_refs") or {}).get("model_io")) if isinstance(trace.get("raw_refs"), dict) else None,
        )
        if model_io:
            parsed["model_io_status"] = model_io.get("status") or ""
            parsed["model_io_attempt_count"] = int(model_io.get("attempt_count") or len(model_io.get("attempts") or []))
            parsed["sections"]["model_io"] = model_io

        if trace.get("output_path") or trace.get("candidate_count") is not None or trace.get("decision_count") is not None:
            parsed["sections"]["overlay"] = {
                "trace_path": trace.get("trace_path"),
                "image_path": trace.get("image_path"),
                "output_path": trace.get("output_path"),
                "candidate_count": trace.get("candidate_count"),
                "decision_count": trace.get("decision_count"),
                "narrow_result_count": trace.get("narrow_result_count"),
                "selected_candidate_id": trace.get("selected_candidate_id"),
            }
            if not parsed["contract"]:
                parsed["contract"] = "recognition_overlay_trace"
        coordinate_preview = trace.get("recognition_plan_overlay")
        if isinstance(coordinate_preview, dict):
            parsed["sections"]["coordinate_preview"] = coordinate_preview
            parsed["coordinate_preview_output_path"] = coordinate_preview.get("output_path") or coordinate_preview.get("overlay_path")
            parsed["coordinate_preview_candidate_count"] = coordinate_preview.get("candidate_count")
            parsed["coordinate_preview_decision_count"] = coordinate_preview.get("decision_count")

        # OCR result
        ocr = parse_result.get("ocr_result") or trace.get("ocr_result") or {}
        parsed["ocr_count"] = _ocr_count(ocr)
        if _meaningful_trace_section(ocr):
            parsed["sections"]["ocr"] = {"image_path": plan_image_path, **ocr} if isinstance(ocr, dict) else {"image_path": plan_image_path, "raw": ocr}

        # Vision
        vision_section = {
            "image_path": plan_image_path,
            "vision_regions": parse_result.get("vision_regions") or trace.get("vision_regions"),
            "vision_provider": trace.get("execution_path", {}).get("vision_provider_used") or trace.get("vision_provider_used") or "",
            "vision_model_used": trace.get("execution_path", {}).get("vision_model_used") or trace.get("vision_model_used") or False,
        }
        if vision_section["vision_regions"] or vision_section["vision_provider"] or vision_section["vision_model_used"]:
            parsed["sections"]["vision"] = vision_section

        # Recognition plan
        if isinstance(plan, dict) and plan:
            candidate_result = plan.get("candidate_result") or {}
            parsed["candidates"] = candidate_result.get("summary", {}).get("returned_count", 0)
            parsed["has_recommendation"] = bool(
                candidate_result.get("has_recommendation") or candidate_result.get("summary", {}).get("has_recommendation")
            )
            parsed["sections"]["candidates"] = {"image_path": plan_image_path, **candidate_result}

            pre_click = plan.get("pre_click_decision") or trace.get("pre_click_decision") or {}
            parsed["gate_allowed"] = pre_click.get("allowed")
            parsed["gate_reason"] = _gate_reason_text(pre_click)
            parsed["sections"]["gate"] = {
                "image_path": plan_image_path,
                "located_point": trace.get("located_point"),
                "located_bbox": trace.get("located_bbox"),
                "candidate_result": candidate_result,
                **pre_click,
            }

            parsed["selected_point"] = pre_click.get("selected_click_point") or trace.get("selected_click_point") or trace.get("located_point")
            parsed["sections"]["target"] = {
                "image_path": plan_image_path,
                "selected_click_point": parsed["selected_point"],
                "located_point": trace.get("located_point"),
                "located_bbox": trace.get("located_bbox"),
                "recommended_target": trace.get("recommended_target") or plan.get("recommended_target"),
                "location_status": trace.get("location_status"),
            }
            path_map_review = trace.get("path_map_review")
            if isinstance(path_map_review, dict):
                summary = path_map_review.get("summary") if isinstance(path_map_review.get("summary"), dict) else {}
                parsed["path_map_review_additions"] = int(summary.get("addition_count") or len(path_map_review.get("additions") or []))
                parsed["path_map_review_removals"] = int(summary.get("removal_count") or len(path_map_review.get("removals") or []))
                parsed["path_map_review_status"] = path_map_review.get("status") or ""
                parsed["sections"]["path_review"] = path_map_review
            path_graph_recall = trace.get("path_graph_recall") or plan.get("path_graph_recall")
            if isinstance(path_graph_recall, dict):
                summary = path_graph_recall.get("summary") if isinstance(path_graph_recall.get("summary"), dict) else {}
                parsed["path_graph_recall_count"] = int(summary.get("recalled_count") or len(path_graph_recall.get("candidates") or []))
                parsed["path_graph_recall_status"] = path_graph_recall.get("status") or ""
                state_match = path_graph_recall.get("state_match") if isinstance(path_graph_recall.get("state_match"), dict) else {}
                parsed["path_graph_recall_state"] = state_match.get("state_id") or ""
                parsed["sections"]["path_recall"] = path_graph_recall
            visual_asset_recall = trace.get("visual_asset_recall") or plan.get("visual_asset_recall")
            if isinstance(visual_asset_recall, dict):
                parsed["visual_asset_recall_status"] = visual_asset_recall.get("status") or ""
                parsed["visual_asset_fast_lane_used"] = bool(
                    visual_asset_recall.get("fast_lane_allowed")
                    or (trace.get("execution_path") or {}).get("visual_asset_fast_lane_used")
                    or (plan.get("execution_path") or {}).get("visual_asset_fast_lane_used")
                )
                parsed["visual_asset_matched_count"] = int(
                    visual_asset_recall.get("matched_count")
                    or len([item for item in visual_asset_recall.get("matches") or [] if isinstance(item, dict) and item.get("matched")])
                )
                parsed["sections"]["visual_asset_recall"] = visual_asset_recall
            fallback_plan = trace.get("fallback_plan")
            if isinstance(fallback_plan, dict):
                parsed["fallback_status"] = fallback_plan.get("status") or ""
                parsed["fallback_step_count"] = len(fallback_plan.get("steps") or []) if isinstance(fallback_plan.get("steps"), list) else 0
                parsed["fallback_reason"] = fallback_plan.get("failure_reason") or ""
                parsed["sections"]["fallback"] = fallback_plan
            agent_guidance = trace.get("agent_execution_guidance")
            if isinstance(agent_guidance, dict):
                parsed["agent_guidance_status"] = agent_guidance.get("status") or ""
                parsed["agent_guidance_next_action"] = agent_guidance.get("next_action") or ""
                parsed["sections"]["agent_guidance"] = agent_guidance
            memory_writeback = trace.get("element_memory_writeback")
            if isinstance(memory_writeback, dict):
                parsed["memory_status"] = memory_writeback.get("status") or ""
                parsed["memory_transition_id"] = memory_writeback.get("transition_id") or ""
                parsed["sections"]["memory"] = memory_writeback

            parsed["sections"]["click"] = plan.get("execution") or trace.get("click_result") or trace.get("execution_path") or {}
            parsed["sections"]["verify"] = trace.get("post_click_verification") or trace.get("semantic_post_click_verification") or {}

        path_map_review = trace.get("path_map_review")
        if isinstance(path_map_review, dict) and "path_review" not in parsed["sections"]:
            summary = path_map_review.get("summary") if isinstance(path_map_review.get("summary"), dict) else {}
            parsed["path_map_review_additions"] = int(summary.get("addition_count") or len(path_map_review.get("additions") or []))
            parsed["path_map_review_removals"] = int(summary.get("removal_count") or len(path_map_review.get("removals") or []))
            parsed["path_map_review_status"] = path_map_review.get("status") or ""
            learn_all_targets = trace.get("learn_all_targets") if isinstance(trace.get("learn_all_targets"), dict) else {}
            parsed["sections"]["path_review"] = {
                **path_map_review,
                "learn_all_targets": learn_all_targets,
                "coordinate_overlay_path": trace.get("coordinate_overlay_path") or learn_all_targets.get("overlay_path"),
                "coordinate_overlay": trace.get("coordinate_overlay") or learn_all_targets.get("overlay"),
            }

        # Screen understanding
        screen = trace.get("screen_reading") or trace.get("parse_result", {}).get("screen_reading") or {}
        if not screen and trace.get("contract_version") == "screen_reading_v1":
            screen = trace
        if isinstance(screen, dict):
            parsed["screen_summary"] = str(screen.get("screen_summary") or "")[:400]
            parsed["state_guess"] = screen.get("state_guess") or ""
            parsed["sections"]["screen"] = screen
            screen_inventory = _first_dict(
                trace.get("screen_inventory"),
                plan.get("screen_inventory"),
                parse_result.get("screen_inventory"),
                screen.get("screen_inventory"),
            )
            if screen_inventory and screen_inventory.get("contract_version") == "screen_inventory_v1":
                inventory_summary = screen_inventory.get("summary") if isinstance(screen_inventory.get("summary"), dict) else {}
                quality = screen_inventory.get("quality") if isinstance(screen_inventory.get("quality"), dict) else {}
                parsed["screen_inventory_action_count"] = int(
                    inventory_summary.get("available_action_count")
                    or len(screen_inventory.get("available_actions") or [])
                )
                parsed["screen_inventory_page_element_count"] = int(
                    inventory_summary.get("page_element_count")
                    or len(screen_inventory.get("page_elements") or [])
                )
                parsed["screen_inventory_card_count"] = int(
                    inventory_summary.get("card_count")
                    or len(screen_inventory.get("cards") or [])
                )
                parsed["screen_inventory_coordinate_coverage"] = quality.get("coordinate_coverage")
                parsed["sections"]["screen_inventory"] = screen_inventory

        # Observe-screen semantic map / navigation path seed.
        screen_map = trace.get("screen_map") or {}
        if isinstance(screen_map, dict) and screen_map.get("contract_version") == "screen_map_v1":
            candidates = screen_map.get("candidates") if isinstance(screen_map.get("candidates"), list) else []
            summary = screen_map.get("summary") if isinstance(screen_map.get("summary"), dict) else {}
            parsed["path_map_count"] = len(candidates)
            parsed["path_map_state_id"] = screen_map.get("state_id") or ""
            parsed["path_map_summary"] = (
                summary.get("screen_summary")
                or screen_map.get("state_hint")
                or parsed.get("screen_summary")
                or ""
            )
            parsed["sections"]["path_map"] = screen_map
        path_graph_deep_review = trace.get("path_graph_deep_review")
        if isinstance(path_graph_deep_review, dict):
            summary = path_graph_deep_review.get("summary") if isinstance(path_graph_deep_review.get("summary"), dict) else {}
            parsed["path_graph_deep_status"] = path_graph_deep_review.get("status") or ""
            parsed["path_graph_deep_additions"] = int(summary.get("missing_text_addition_count") or 0)
            parsed["path_graph_deep_removals"] = int(summary.get("duplicate_count") or 0)
            parsed["path_graph_deep_output_count"] = int(summary.get("output_candidate_count") or 0)
            parsed["sections"]["path_deep"] = {
                **path_graph_deep_review,
                "path_graph_delta": trace.get("path_graph_delta") if isinstance(trace.get("path_graph_delta"), dict) else None,
                "element_memory_init_plan": trace.get("element_memory_init_plan") if isinstance(trace.get("element_memory_init_plan"), dict) else None,
            }

        # Execution
        exec_path = trace.get("execution_path") or {}
        parsed["action_executed"] = exec_path.get("action_executed", False)

        # Verification
        verify = trace.get("post_click_verification") or trace.get("semantic_post_click_verification")
        if isinstance(verify, dict):
            parsed["verified"] = not (verify.get("verified") is False or verify.get("success") is False)
            parsed["verification_detail"] = str(verify.get("detail") or verify.get("message") or "")[:200]

        # Errors
        errors = []
        if trace.get("error"):
            errors.append(str(trace["error"])[:200])
        if isinstance(plan, dict) and plan.get("error"):
            errors.append(str(plan["error"])[:200])
        parsed["errors"] = errors
        if errors:
            parsed["sections"]["error"] = {"errors": errors}

        # Model info
        parsed["model_used"] = exec_path.get("vision_model_used") or trace.get("vision_model_used") or False
        parsed["model_provider"] = exec_path.get("vision_provider_used") or trace.get("vision_provider_used") or ""
        if isinstance(trace.get("layers"), list):
            flow_stages = _layer_flow_stages(trace["layers"])
        else:
            flow_stages = _trace_flow_stages(parsed)
        if not flow_stages:
            flow_stages = [{
                "id": "raw",
                "label": "Raw Trace",
                "value": parsed.get("contract") or resolved.name,
                "status": "done",
                "summary": "No known contract-specific stages matched; showing the full trace JSON.",
                "raw": trace,
            }]
        parsed["flow_stages"] = flow_stages

        return APIResponse(success=True, message="Trace parsed", data=parsed, error=None)
    except Exception as exc:
        return APIResponse(success=False, message="Trace parse error", data=None, error=ErrorModel(code="trace_parse_error", details=str(exc)))


@router.post("/panel/upload_image", response_model=APIResponse)
def upload_panel_image(request: PanelImageUploadRequest) -> APIResponse:
    """Store an image dragged into the browser panel and return a runtime image path."""
    try:
        suffix = Path(request.filename).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            suffix = ".png"
        safe_stem = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in Path(request.filename).stem)[:80]
        safe_name = f"{safe_stem or 'upload'}{suffix}"
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        payload = base64.b64decode(request.content_base64, validate=True)
        output = UPLOAD_DIR / safe_name
        if output.exists():
            output = UPLOAD_DIR / f"{safe_stem or 'upload'}-{len(list(UPLOAD_DIR.glob((safe_stem or 'upload') + '*')))}{suffix}"
        output.write_bytes(payload)
        image_path = str(output.resolve())
        return APIResponse(
            success=True,
            message="Image uploaded",
            data={
                "image_path": image_path,
                "image_url": f"/panel/file?path={image_path}",
                "content_type": request.content_type,
            },
            error=None,
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Image upload failed",
            data=None,
            error=ErrorModel(code="panel_image_upload_failed", details=str(exc)),
        )


@router.post("/panel/manual_box", response_model=APIResponse)
def render_manual_box(request: PanelManualBoxRequest) -> APIResponse:
    """Render an operator-provided candidate box onto the current screenshot."""
    try:
        source_path = Path(request.image_path).expanduser()
        if not source_path.is_absolute():
            source_path = ROOT_DIR / source_path
        source_path = source_path.resolve()
        allowed_roots = [(ROOT_DIR / "artifacts").resolve(), (ROOT_DIR / "logs").resolve()]
        if not any(source_path == root or root in source_path.parents for root in allowed_roots):
            raise ValueError("Image path is outside artifacts/logs")
        if not source_path.exists() or not source_path.is_file():
            raise FileNotFoundError(str(source_path))

        SETTINGS_PANEL_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
        output = SETTINGS_PANEL_ARTIFACT_DIR / f"manual-box-{time.strftime('%Y%m%d-%H%M%S')}.png"
        label = (request.label or "target").strip() or "target"
        image = Image.open(source_path).convert("RGB")
        draw = ImageDraw.Draw(image)
        x2 = request.x + request.width
        y2 = request.y + request.height
        draw.rectangle([request.x, request.y, x2, y2], outline=(255, 0, 80), width=4)
        draw.text((request.x + 4, max(0, request.y - 18)), label, fill=(255, 0, 80))
        image.save(output)
        overlay_path = str(output.resolve())
        return APIResponse(
            success=True,
            message="Manual candidate box rendered",
            data={
                "manual_overlay_path": overlay_path,
                "image_path": overlay_path,
                "image_url": f"/panel/file?path={overlay_path}",
                "bbox": {"x": request.x, "y": request.y, "w": request.width, "h": request.height},
                "label": label,
            },
            error=None,
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Manual candidate box failed",
            data=None,
            error=ErrorModel(code="panel_manual_box_failed", details=str(exc)),
        )


@router.post("/panel/crop_interface_asset", response_model=APIResponse)
def crop_interface_asset(request: PanelInterfaceAssetCropRequest) -> APIResponse:
    try:
        source_path = _resolve_allowed_artifact(request.source_image_path)
        crop_dir = INTERFACE_MAP_DIR / "crops"
        crop_dir.mkdir(parents=True, exist_ok=True)
        safe_asset = _safe_file_stem(request.asset_id)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        with Image.open(source_path) as image:
            width, height = image.size
            bbox = _clip_xywh(request.x, request.y, request.width, request.height, width, height)
            if bbox is None:
                raise ValueError("crop bbox is outside source image")
            tight_box = _expand_box(bbox, width, height, request.padding_px)
            context_box = _expand_box(bbox, width, height, request.context_padding_px)
            tight_crop = image.crop(tight_box)
            context_crop = image.crop(context_box)
            tight_path = crop_dir / f"{safe_asset}-{stamp}.tight.png"
            context_path = crop_dir / f"{safe_asset}-{stamp}.context.png"
            tight_crop.save(tight_path)
            context_crop.save(context_path)
        tight_ref = str(tight_path.resolve())
        context_ref = str(context_path.resolve())
        bbox_payload = _box_to_xywh(bbox)
        click_point = {"x": bbox_payload["x"] + bbox_payload["w"] // 2, "y": bbox_payload["y"] + bbox_payload["h"] // 2}
        trace_payload = {
            "contract_version": "learned_interface_map_asset_crop_trace_v1",
            "asset_id": request.asset_id,
            "label": request.label or "",
            "source_image_path": str(source_path),
            "tight_crop_ref": tight_ref,
            "context_crop_ref": context_ref,
            "bbox": bbox_payload,
            "click_point": click_point,
            "padding_px": request.padding_px,
            "context_padding_px": request.context_padding_px,
            "artifact_is_authorization": False,
            "can_authorize_click": False,
        }
        trace_path = write_trace(category="panel", operation="crop-interface-asset", payload=trace_payload, name_hint=safe_asset)
        return APIResponse(
            success=True,
            message="Interface asset cropped",
            data={
                "contract_version": "learned_interface_map_asset_crop_v1",
                "asset_id": request.asset_id,
                "source_image_path": str(source_path),
                "tight_crop_ref": tight_ref,
                "context_crop_ref": context_ref,
                "tight_crop_url": f"/panel/file?path={tight_ref}",
                "context_crop_url": f"/panel/file?path={context_ref}",
                "bbox": bbox_payload,
                "click_point": click_point,
                "padding_px": request.padding_px,
                "context_padding_px": request.context_padding_px,
                "trace_path": trace_path,
                "artifact_is_authorization": False,
                "can_authorize_click": False,
            },
            error=None,
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Interface asset crop failed",
            data=None,
            error=ErrorModel(code="interface_asset_crop_failed", details=str(exc)),
        )


@router.post("/panel/apply_model_profile", response_model=APIResponse)
def apply_panel_model_profile(request: PanelApplyModelProfileRequest) -> APIResponse:
    """Persist a selected browser-panel model profile into the runtime config files."""
    try:
        profiles = load_model_profiles()
        profile = next((item for item in profiles if item.get("profile_id") == request.profile_id), None)
        if not profile:
            raise ValueError(f"Model profile not found: {request.profile_id}")

        vision_config = _load_json(VISION_CONFIG_PATH, {"vision": {}})
        vision = vision_config.setdefault("vision", {})
        vision["mode"] = "local"
        vision["timeout_seconds"] = request.timeout_seconds
        target_key = "local_understanding" if request.stage == "observe" else "local_grounding"
        target = {
            "model_name": str(profile.get("model_name") or Path(str(profile.get("model_path") or "")).name),
            "endpoint": profile.get("endpoint") or None,
        }
        for key in (
            "profile_id",
            "runtime",
            "output_contract",
            "provider_mode",
            "input_format",
            "supports_ocr_anchors",
            "model_path",
        ):
            if key in profile:
                target[key] = profile.get(key)
        vision[target_key] = target
        if request.stage == "locate":
            vision["local"] = dict(target)
        elif "local" not in vision and target_key == "local_grounding":
            vision["local"] = dict(target)
        _save_json(VISION_CONFIG_PATH, vision_config)

        panel_config = _load_json(PANEL_CONFIG_PATH, {})
        panel_config["language"] = request.language
        panel_config["runtime_base_url"] = panel_config.get("runtime_base_url") or "http://127.0.0.1:8000"
        prompts = panel_config.setdefault("prompt_overrides", {})
        if request.observe_prompt is not None:
            prompts["observe_additional_rules"] = request.observe_prompt
        if request.locate_prompt is not None:
            prompts["locate_additional_rules"] = request.locate_prompt
        scripts = panel_config.setdefault("model_scripts", {})
        scripts["start"] = str(profile.get("start_script") or scripts.get("start") or "scripts/model_servers/start_llama_vision_server.ps1")
        scripts["stop"] = str(profile.get("stop_script") or scripts.get("stop") or "scripts/model_servers/stop_local_vision_server.ps1")
        label = str(profile.get("label") or profile.get("profile_id") or request.profile_id)
        if request.stage == "observe":
            panel_config["observe_model_profile"] = label
        else:
            panel_config["locate_model_profile"] = label
        _save_json(PANEL_CONFIG_PATH, panel_config)

        return APIResponse(
            success=True,
            message="Model profile applied",
            data={
                "stage": request.stage,
                "profile": profile,
                "vision_config_path": str(VISION_CONFIG_PATH),
                "panel_config_path": str(PANEL_CONFIG_PATH),
                "vision": vision,
            },
            error=None,
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Model profile apply failed",
            data=None,
            error=ErrorModel(code="panel_apply_model_profile_failed", details=str(exc)),
        )


@router.post("/panel/model_test", response_model=APIResponse)
def panel_model_test(request: PanelModelTestRequest) -> APIResponse:
    """Send a prompt, optionally with an image, to a configured vision model profile."""
    try:
        profile = next((item for item in load_model_profiles() if item.get("profile_id") == request.profile_id), None)
        if not profile:
            raise ValueError(f"Model profile not found: {request.profile_id}")

        messages: list[dict[str, Any]] = [{"role": "user", "content": request.prompt}]
        image_payload = None
        if request.image_path:
            image_path = _resolve_allowed_artifact(request.image_path)
            content_type = _image_content_type(image_path)
            image_payload = base64.b64encode(image_path.read_bytes()).decode("ascii")
            messages[0]["content"] = [
                {"type": "text", "text": request.prompt},
                {"type": "image_url", "image_url": {"url": f"data:{content_type};base64,{image_payload}"}},
            ]

        model_name = str(profile.get("model_name") or Path(str(profile.get("model_path") or "local-model")).name)
        payload = {
            "model": model_name,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        endpoint = f"{model_base_url(profile).rstrip('/')}/chat/completions"
        http_request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=600) as response:
                raw_text = response.read().decode("utf-8", errors="replace")
                response_status = response.status
        except urllib.error.HTTPError as exc:
            raw_text = exc.read().decode("utf-8", errors="replace")
            model_io = {
                "contract_version": "model_io_trace_v1",
                "status": "failed",
                "provider": "panel_model_test",
                "model_name": model_name,
                "endpoint": endpoint,
                "attempt_count": 1,
                "attempts": [
                    {
                        "status": "failed",
                        "http_status": exc.code,
                        "model_io": {
                            "contract_version": "model_io_attempt_v1",
                            "input": {
                                "prompt": request.prompt,
                                "image_path": request.image_path,
                                "max_tokens": request.max_tokens,
                                "temperature": request.temperature,
                            },
                            "output": {"raw_text": raw_text, "raw_response": raw_text},
                        },
                    }
                ],
            }
            trace_path = write_trace(
                category="vision",
                operation="panel_model_test",
                payload={"success": False, "request": request.model_dump(), "model_io": model_io, "error": raw_text},
                name_hint=request.profile_id,
            )
            return APIResponse(
                success=False,
                message="Model request failed",
                data={"endpoint": endpoint, "status": exc.code, "raw_response": raw_text, "model_io": model_io, "trace_path": trace_path},
                error=ErrorModel(code="panel_model_test_http_error", details=raw_text[:1000]),
            )

        try:
            raw_json = json.loads(raw_text)
        except json.JSONDecodeError:
            raw_json = None
        content = _extract_chat_content(raw_json) if isinstance(raw_json, dict) else raw_text
        model_io = {
            "contract_version": "model_io_trace_v1",
            "status": "success",
            "provider": "panel_model_test",
            "model_name": model_name,
            "endpoint": endpoint,
            "raw_text": content,
            "raw_response": raw_json if raw_json is not None else raw_text,
            "attempt_count": 1,
            "attempts": [
                {
                    "status": "success",
                    "http_status": response_status,
                    "model_io": {
                        "contract_version": "model_io_attempt_v1",
                        "input": {
                            "prompt": request.prompt,
                            "image_path": request.image_path,
                            "max_tokens": request.max_tokens,
                            "temperature": request.temperature,
                        },
                        "output": {
                            "raw_text": content,
                            "raw_response": raw_json if raw_json is not None else raw_text,
                        },
                    },
                }
            ],
        }
        trace_path = write_trace(
            category="vision",
            operation="panel_model_test",
            payload={"success": True, "request": request.model_dump(), "model_io": model_io},
            name_hint=request.profile_id,
        )
        return APIResponse(
            success=True,
            message="Model response received",
            data={
                "endpoint": endpoint,
                "profile_id": request.profile_id,
                "stage": request.stage,
                "model": model_name,
                "status": response_status,
                "content": content,
                "raw_response": raw_json if raw_json is not None else raw_text,
                "image_attached": image_payload is not None,
                "model_io": model_io,
                "trace_path": trace_path,
            },
            error=None,
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Model test failed",
            data=None,
            error=ErrorModel(code="panel_model_test_failed", details=str(exc)),
        )


PATH_GRAPH_DIR = ROOT_DIR / "artifacts" / "path-graphs"
INTERFACE_MAP_DIR = ROOT_DIR / "artifacts" / "interface-maps"
INTERFACE_WORKFLOW_DIR = ROOT_DIR / "artifacts" / "interface-workflow-reviews"


@router.post("/panel/open_trace_folder", include_in_schema=False)
def open_trace_folder() -> APIResponse:
    """Open the logs/traces folder in Explorer."""
    import os
    import subprocess
    import sys

    folder = ROOT_DIR / "logs" / "traces"
    folder.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(str(folder))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(folder)], check=False)
        else:
            subprocess.run(["xdg-open", str(folder)], check=False)
        return APIResponse(success=True, message=f"Opened {folder}", data={"folder": str(folder)}, error=None)
    except Exception as exc:
        return APIResponse(success=False, message="Could not open folder", data=None, error=ErrorModel(code="folder_open_failed", details=str(exc)))


@router.post("/panel/open_path_folder", include_in_schema=False)
def open_path_folder() -> APIResponse:
    """Open the path-graph save folder in Explorer."""
    import os
    import subprocess
    import sys

    PATH_GRAPH_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(str(PATH_GRAPH_DIR))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(PATH_GRAPH_DIR)], check=False)
        else:
            subprocess.run(["xdg-open", str(PATH_GRAPH_DIR)], check=False)
        return APIResponse(success=True, message=f"Opened {PATH_GRAPH_DIR}", data={"folder": str(PATH_GRAPH_DIR)}, error=None)
    except Exception as exc:
        return APIResponse(success=False, message="Could not open folder", data=None, error=ErrorModel(code="folder_open_failed", details=str(exc)))


@router.post("/panel/open_interface_workflow_folder", include_in_schema=False)
def open_interface_workflow_folder() -> APIResponse:
    """打开固定的已学习软件流程目录。"""
    import subprocess
    import sys

    INTERFACE_WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(str(INTERFACE_WORKFLOW_DIR))
        elif sys.platform == "darwin":
            subprocess.run(["open", str(INTERFACE_WORKFLOW_DIR)], check=False)
        else:
            subprocess.run(["xdg-open", str(INTERFACE_WORKFLOW_DIR)], check=False)
        return APIResponse(
            success=True,
            message=f"Opened {INTERFACE_WORKFLOW_DIR}",
            data={"folder": str(INTERFACE_WORKFLOW_DIR)},
            error=None,
        )
    except Exception as exc:
        return APIResponse(
            success=False,
            message="Could not open learned workflow folder",
            data=None,
            error=ErrorModel(code="folder_open_failed", details=str(exc)),
        )


@router.post("/panel/save_path_graph", include_in_schema=False)
def save_path_graph_to_disk(request: dict) -> APIResponse:
    """Persist a path graph JSON to artifacts/path-graphs/ with a custom filename."""
    try:
        PATH_GRAPH_DIR.mkdir(parents=True, exist_ok=True)
        file_name = str(request.get("file_name") or "unnamed_path_graph.json")
        payload = request.get("payload") or request
        safe_name = "".join(c if c.isalnum() or c in "_.-" else "_" for c in file_name)
        if not safe_name.endswith(".json"):
            safe_name += ".json"
        filepath = PATH_GRAPH_DIR / safe_name
        filepath.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return APIResponse(success=True, message=f"Saved to {filepath.name}", data={"path": str(filepath)}, error=None)
    except Exception as exc:
        return APIResponse(success=False, message="Save failed", data=None, error=ErrorModel(code="path_graph_save_failed", details=str(exc)))


@router.post("/panel/save_interface_map", include_in_schema=False)
def save_interface_map_to_disk(request: dict) -> APIResponse:
    try:
        INTERFACE_MAP_DIR.mkdir(parents=True, exist_ok=True)
        file_name = str(request.get("file_name") or "learned_interface_map.json")
        payload = request.get("payload")
        if not isinstance(payload, dict):
            return APIResponse(
                success=False,
                message="Save failed",
                data=None,
                error=ErrorModel(code="invalid_interface_map_payload", details="payload must be an object"),
            )
        safe_name = "".join(c if c.isalnum() or c in "_.-" else "_" for c in file_name)
        if not safe_name.endswith(".json"):
            safe_name += ".json"
        filepath = INTERFACE_MAP_DIR / safe_name
        filepath.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        trace_payload = {
            "contract_version": "learned_interface_map_edit_trace_v1",
            "source_path": request.get("source_path") or "",
            "saved_path": str(filepath.resolve()),
            "edited_at": time.time(),
            "edit_summary": request.get("edit_summary") or {},
            "payload_summary": {
                "contract_version": payload.get("contract_version"),
                "app_id": payload.get("app_id"),
                "region_count": len(payload.get("regions") or []),
                "fixed_visual_asset_count": len(payload.get("fixed_visual_assets") or []),
                "dynamic_area_count": len(payload.get("dynamic_areas") or []),
                "danger_zone_count": len(payload.get("danger_zones") or []),
            },
        }
        trace_path = write_trace(category="panel", operation="save-interface-map", payload=trace_payload, name_hint=safe_name)
        return APIResponse(success=True, message=f"Saved to {filepath.name}", data={"path": str(filepath), "trace_path": trace_path}, error=None)
    except Exception as exc:
        return APIResponse(success=False, message="Save failed", data=None, error=ErrorModel(code="interface_map_save_failed", details=str(exc)))


def _load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return dict(default)
    return json.loads(path.read_text(encoding="utf-8"))


def _save_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _resolve_allowed_artifact(path: str) -> Path:
    resolved = Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = ROOT_DIR / resolved
    resolved = resolved.resolve()
    allowed_roots = [(ROOT_DIR / "artifacts").resolve(), (ROOT_DIR / "logs").resolve()]
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        raise ValueError("Image path is outside artifacts/logs")
    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(str(resolved))
    return resolved


def _image_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".bmp":
        return "image/bmp"
    return "image/png"


def _safe_file_stem(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in str(value))
    return safe.strip("._")[:96] or "interface_asset"


def _clip_xywh(x: int, y: int, width: int, height: int, image_width: int, image_height: int) -> tuple[int, int, int, int] | None:
    left = max(0, min(int(x), image_width))
    top = max(0, min(int(y), image_height))
    right = max(0, min(int(x) + int(width), image_width))
    bottom = max(0, min(int(y) + int(height), image_height))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _expand_box(box: tuple[int, int, int, int], image_width: int, image_height: int, padding: int) -> tuple[int, int, int, int]:
    left, top, right, bottom = box
    pad = max(0, int(padding))
    return (
        max(0, left - pad),
        max(0, top - pad),
        min(image_width, right + pad),
        min(image_height, bottom + pad),
    )


def _box_to_xywh(box: tuple[int, int, int, int]) -> dict[str, int]:
    left, top, right, bottom = box
    return {"x": int(left), "y": int(top), "w": int(right - left), "h": int(bottom - top)}


def _extract_chat_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message")
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):
                    parts = []
                    for item in content:
                        if isinstance(item, dict):
                            text = item.get("text")
                            if isinstance(text, str):
                                parts.append(text)
                    if parts:
                        return "\n".join(parts)
            text = first.get("text")
            if isinstance(text, str):
                return text
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _ocr_count(ocr: Any) -> int:
    if not isinstance(ocr, dict):
        return 0
    metadata = ocr.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("match_count"), int):
        return int(metadata["match_count"])
    matches = ocr.get("matches")
    if isinstance(matches, list):
        return len(matches)
    return 0


def _gate_reason_text(pre_click: Any) -> str:
    if not isinstance(pre_click, dict):
        return ""
    parts: list[str] = []
    if pre_click.get("reason"):
        parts.append(str(pre_click["reason"]))
    reasons = pre_click.get("reasons")
    if isinstance(reasons, list) and reasons:
        parts.append("reasons: " + ", ".join(str(item) for item in reasons[:6]))
    summary = pre_click.get("summary")
    if isinstance(summary, dict):
        summary_bits = []
        for key in ("candidate_count", "allowed_candidate_count", "top_margin_ok", "margin_to_second"):
            if key in summary:
                summary_bits.append(f"{key}={summary[key]}")
        if summary_bits:
            parts.append("summary: " + ", ".join(summary_bits))
    decisions = pre_click.get("candidate_decisions")
    if isinstance(decisions, list):
        for decision in decisions[:3]:
            if not isinstance(decision, dict):
                continue
            decision_reasons = decision.get("reasons")
            reason_text = ", ".join(str(item) for item in decision_reasons[:6]) if isinstance(decision_reasons, list) else ""
            candidate_id = decision.get("candidate_id") or decision.get("element_id") or "candidate"
            allowed = decision.get("allowed")
            click_point = decision.get("click_point")
            parts.append(f"{candidate_id}: allowed={allowed}, click_point={click_point}, reasons={reason_text}")
    return " | ".join(part for part in parts if part)[:1200]


def _trace_flow_stages(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    sections = parsed.get("sections") if isinstance(parsed.get("sections"), dict) else {}

    def add(stage_id: str, label: str, value: str = "", status: str = "done") -> dict[str, Any] | None:
        raw = sections.get(stage_id)
        if not _meaningful_trace_section(raw):
            return None
        return {
            "id": stage_id,
            "label": label,
            "value": value,
            "status": status,
            "summary": _stage_summary(stage_id, parsed),
            "raw": raw,
        }

    stages = [
        add("goal", "Request", str(parsed.get("goal") or parsed.get("contract") or "")),
        add("capture", "Capture", str(parsed.get("app_name") or "image")),
        add("overlay", "Overlay", _overlay_label(sections.get("overlay"))),
        add("ocr", "OCR", f"{parsed.get('ocr_count') or 0} anchors"),
        add("vision", "Vision", str(parsed.get("model_provider") or parsed.get("provider") or "")),
        add("model_io", "Model IO", _model_io_label(sections.get("model_io")), "done" if parsed.get("model_io_status") != "failed" else "error"),
        add("screen", "Screen", str(parsed.get("state_guess") or "")),
        add("screen_inventory", "Inventory", _screen_inventory_label(sections.get("screen_inventory"))),
        add("path_map", "Path Map", _path_map_label(sections.get("path_map"))),
        add("path_deep", "Path Deep", _path_deep_label(sections.get("path_deep"))),
        add("path_recall", "Path Recall", _path_recall_label(sections.get("path_recall"))),
        add("visual_asset_recall", "Visual Assets", _visual_asset_recall_label(sections.get("visual_asset_recall"))),
        add("path_review", "Path Review", _path_review_label(sections.get("path_review"))),
        add("candidates", "Candidates", f"{parsed.get('candidates') or 0} returned"),
        add("coordinate_preview", "Coordinate Preview", _coordinate_preview_label(sections.get("coordinate_preview"))),
        add(
            "gate",
            "Gate",
            "ALLOW" if parsed.get("gate_allowed") is True else "BLOCK" if parsed.get("gate_allowed") is False else "",
            "done" if parsed.get("gate_allowed") is True else "blocked" if parsed.get("gate_allowed") is False else "done",
        ),
        add("target", "Target", _point_label(parsed.get("selected_point"))) if parsed.get("selected_point") else None,
        add("agent_guidance", "Agent Guidance", _agent_guidance_label(sections.get("agent_guidance"))),
        add("click", "Action", "executed" if parsed.get("action_executed") else "dry-run"),
        add("memory", "Memory", _memory_label(sections.get("memory"))),
        add(
            "verify",
            "Verify",
            "PASS" if parsed.get("verified") is True else "FAIL" if parsed.get("verified") is False else "",
            "done" if parsed.get("verified") is not False else "error",
        ),
        add("fallback", "Fallback", _fallback_label(sections.get("fallback")), "blocked"),
        add("error", "Error", f"{len(parsed.get('errors') or [])} error(s)", "error"),
        add("timings", "Timings", str(parsed.get("total_time") or "")),
    ]
    return [stage for stage in stages if stage is not None]


def _layer_flow_stages(layers: list[Any]) -> list[dict[str, Any]]:
    stages: list[dict[str, Any]] = []
    for index, layer in enumerate(layers):
        if not isinstance(layer, dict):
            continue
        layer_name = str(layer.get("layer") or f"layer_{index + 1}")
        status = "done" if layer.get("ok") is not False else "error"
        summary = layer.get("summary")
        value = _compact_value(summary) or ("ok" if status == "done" else "error")
        stages.append(
            {
                "id": f"layer_{index + 1}",
                "label": layer_name,
                "value": value,
                "status": status,
                "summary": json.dumps(summary, ensure_ascii=False, indent=2) if isinstance(summary, dict) else str(summary or ""),
                "raw": layer,
            }
        )
    return stages


def _meaningful_trace_section(raw: Any) -> bool:
    if raw in (None, {}, []):
        return False
    if isinstance(raw, dict):
        if any(key in raw for key in ("allowed", "ok", "verified", "success")):
            return True
        return any(value not in (None, "", [], {}, False) for value in raw.values())
    return True


def _first_dict(*values: Any) -> dict[str, Any] | None:
    for value in values:
        if isinstance(value, dict):
            return value
    return None


def _overlay_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    count = raw.get("candidate_count")
    decision_count = raw.get("decision_count")
    parts = []
    if count is not None:
        parts.append(f"{count} candidates")
    if decision_count is not None:
        parts.append(f"{decision_count} decisions")
    return ", ".join(parts)


def _path_map_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    count = summary.get("candidate_count")
    if count is None and isinstance(raw.get("candidates"), list):
        count = len(raw["candidates"])
    state_id = raw.get("state_id")
    parts = []
    if count is not None:
        parts.append(f"{count} candidates")
    if state_id:
        parts.append(str(state_id))
    return ", ".join(parts)


def _screen_inventory_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    action_count = summary.get("available_action_count")
    if action_count is None and isinstance(raw.get("available_actions"), list):
        action_count = len(raw["available_actions"])
    page_count = summary.get("page_element_count")
    if page_count is None and isinstance(raw.get("page_elements"), list):
        page_count = len(raw["page_elements"])
    card_count = summary.get("card_count")
    if card_count is None and isinstance(raw.get("cards"), list):
        card_count = len(raw["cards"])
    parts = []
    if action_count is not None:
        parts.append(f"{action_count} actions")
    if page_count is not None:
        parts.append(f"{page_count} text")
    if card_count is not None:
        parts.append(f"{card_count} cards")
    return ", ".join(parts)


def _model_io_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    status = str(raw.get("status") or "")
    attempts = raw.get("attempt_count")
    if attempts is None and isinstance(raw.get("attempts"), list):
        attempts = len(raw["attempts"])
    provider = str(raw.get("provider") or raw.get("model_name") or "")
    parts = []
    if status:
        parts.append(status)
    if attempts is not None:
        parts.append(f"{attempts} attempt(s)")
    if provider:
        parts.append(provider)
    return ", ".join(parts)


def _path_recall_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    count = summary.get("recalled_count")
    if count is None and isinstance(raw.get("candidates"), list):
        count = len(raw["candidates"])
    state_match = raw.get("state_match") if isinstance(raw.get("state_match"), dict) else {}
    parts = []
    if count is not None:
        parts.append(f"{count} recalled")
    if state_match.get("state_id"):
        parts.append(str(state_match["state_id"]))
    return ", ".join(parts)


def _visual_asset_recall_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    status = str(raw.get("status") or "")
    matched = raw.get("matched_count")
    if matched is None and isinstance(raw.get("matches"), list):
        matched = len([item for item in raw["matches"] if isinstance(item, dict) and item.get("matched")])
    fast_lane = raw.get("fast_lane_allowed")
    selected = raw.get("selected_asset_id") or raw.get("selected_candidate_id")
    parts = []
    if status:
        parts.append(status)
    if matched is not None:
        parts.append(f"{matched} matched")
    if fast_lane is not None:
        parts.append("fast lane" if fast_lane else "gate only")
    if selected:
        parts.append(str(selected)[:32])
    return ", ".join(parts)


def _path_deep_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    additions = summary.get("missing_text_addition_count")
    removals = summary.get("duplicate_count")
    if additions is None:
        delta = raw.get("path_graph_delta") if isinstance(raw.get("path_graph_delta"), dict) else {}
        additions = len(delta.get("additions") or []) if isinstance(delta.get("additions"), list) else 0
    if removals is None:
        delta = raw.get("path_graph_delta") if isinstance(raw.get("path_graph_delta"), dict) else {}
        removals = len(delta.get("removals") or []) if isinstance(delta.get("removals"), list) else 0
    return f"+{additions} / -{removals}"


def _path_review_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    summary = raw.get("summary") if isinstance(raw.get("summary"), dict) else {}
    additions = summary.get("addition_count")
    removals = summary.get("removal_count")
    if additions is None:
        additions = len(raw.get("additions") or []) if isinstance(raw.get("additions"), list) else 0
    if removals is None:
        removals = len(raw.get("removals") or []) if isinstance(raw.get("removals"), list) else 0
    return f"+{additions} / -{removals}"


def _coordinate_preview_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    count = raw.get("candidate_count")
    decisions = raw.get("decision_count")
    selected = raw.get("selected_candidate_id")
    parts = []
    if count is not None:
        parts.append(f"{count} candidates")
    if decisions is not None:
        parts.append(f"{decisions} decisions")
    if selected:
        parts.append(str(selected)[:24])
    return ", ".join(parts)


def _agent_guidance_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    return ", ".join(str(item) for item in [raw.get("status"), raw.get("next_action")] if item)


def _memory_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    status = str(raw.get("status") or "")
    transition_id = str(raw.get("transition_id") or "")
    return ", ".join(part for part in [status, transition_id[:12]] if part)


def _fallback_label(raw: Any) -> str:
    if not isinstance(raw, dict):
        return ""
    steps = raw.get("steps") if isinstance(raw.get("steps"), list) else []
    reason = str(raw.get("failure_reason") or "")
    parts = []
    if reason:
        parts.append(reason)
    parts.append(f"{len(steps)} step(s)")
    return ", ".join(parts)


def _compact_value(value: Any) -> str:
    if isinstance(value, dict):
        for key in ["contract_version", "provider", "region_count", "element_count", "text_count", "status"]:
            if key in value:
                return f"{key}: {value[key]}"
        return f"{len(value)} fields"
    if isinstance(value, list):
        return f"{len(value)} items"
    return str(value or "")


def _stage_summary(stage_id: str, parsed: dict[str, Any]) -> str:
    if stage_id == "goal":
        return str(parsed.get("goal") or parsed.get("state_hint") or parsed.get("contract") or "")
    if stage_id == "ocr":
        return f"OCR anchors: {parsed.get('ocr_count') or 0}"
    if stage_id == "vision":
        return str(parsed.get("screen_summary") or parsed.get("model_provider") or "")
    if stage_id == "model_io":
        status = parsed.get("model_io_status") or ""
        attempts = parsed.get("model_io_attempt_count") or 0
        return f"Model IO {status}: {attempts} attempt(s) with full input prompt and raw model output in raw JSON.".strip()
    if stage_id == "screen":
        return str(parsed.get("screen_summary") or parsed.get("state_guess") or "")
    if stage_id == "screen_inventory":
        actions = parsed.get("screen_inventory_action_count") or 0
        page_elements = parsed.get("screen_inventory_page_element_count") or 0
        cards = parsed.get("screen_inventory_card_count") or 0
        coverage = parsed.get("screen_inventory_coordinate_coverage")
        coverage_text = f"; coordinate coverage: {coverage:.2f}" if isinstance(coverage, (int, float)) else ""
        return f"Screen inventory: {actions} action(s), {page_elements} page element(s), {cards} card(s){coverage_text}"
    if stage_id == "path_map":
        count = parsed.get("path_map_count") or 0
        state_id = parsed.get("path_map_state_id") or ""
        summary = parsed.get("path_map_summary") or ""
        prefix = f"Path map candidates: {count}"
        if state_id:
            prefix += f"; state: {state_id}"
        return f"{prefix}\n{summary}".strip()
    if stage_id == "path_recall":
        count = parsed.get("path_graph_recall_count") or 0
        status = parsed.get("path_graph_recall_status") or ""
        state_id = parsed.get("path_graph_recall_state") or ""
        suffix = f"; state: {state_id}" if state_id else ""
        return f"Path recall {status}: {count} candidate(s){suffix}".strip()
    if stage_id == "visual_asset_recall":
        status = parsed.get("visual_asset_recall_status") or ""
        matched = parsed.get("visual_asset_matched_count") or 0
        fast_lane = parsed.get("visual_asset_fast_lane_used")
        lane = "; fast lane" if fast_lane else ""
        return f"Visual asset recall {status}: {matched} matched asset(s){lane}".strip()
    if stage_id == "path_deep":
        status = parsed.get("path_graph_deep_status") or ""
        output_count = parsed.get("path_graph_deep_output_count") or 0
        additions = parsed.get("path_graph_deep_additions") or 0
        removals = parsed.get("path_graph_deep_removals") or 0
        return f"Path deep {status}: {output_count} candidate(s), +{additions}, -{removals}".strip()
    if stage_id == "path_review":
        additions = parsed.get("path_map_review_additions") or 0
        removals = parsed.get("path_map_review_removals") or 0
        status = parsed.get("path_map_review_status") or ""
        return f"Path review {status}: +{additions}, -{removals}".strip()
    if stage_id == "coordinate_preview":
        path = parsed.get("coordinate_preview_output_path") or ""
        count = parsed.get("coordinate_preview_candidate_count")
        decisions = parsed.get("coordinate_preview_decision_count")
        return f"Pre-rendered coordinate overlay: {count} candidate(s), {decisions} decision(s). {path}".strip()
    if stage_id == "candidates":
        return f"Candidates returned: {parsed.get('candidates') or 0}; recommendation: {bool(parsed.get('has_recommendation'))}"
    if stage_id == "gate":
        return str(parsed.get("gate_reason") or "")
    if stage_id == "target":
        return _point_label(parsed.get("selected_point"))
    if stage_id == "agent_guidance":
        return f"{parsed.get('agent_guidance_status') or ''}: {parsed.get('agent_guidance_next_action') or ''}".strip()
    if stage_id == "click":
        return "Action executed" if parsed.get("action_executed") else "Dry run or not executed"
    if stage_id == "memory":
        status = parsed.get("memory_status") or ""
        transition_id = parsed.get("memory_transition_id") or ""
        return f"ElementMemory writeback {status}: {transition_id}".strip()
    if stage_id == "verify":
        return str(parsed.get("verification_detail") or "")
    if stage_id == "fallback":
        reason = parsed.get("fallback_reason") or ""
        count = parsed.get("fallback_step_count") or 0
        return f"Fallback planned for {reason}: {count} step(s)".strip()
    if stage_id == "error":
        return "\n".join(parsed.get("errors") or [])
    return ""


def _point_label(point: Any) -> str:
    if not isinstance(point, dict):
        return ""
    x = point.get("x")
    y = point.get("y")
    if x is None or y is None:
        return ""
    return f"({round(float(x))}, {round(float(y))})"
