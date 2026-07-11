from __future__ import annotations

import base64
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.api import panel as panel_api
from app.main import app


def test_web_panel_serves_browser_control_surface() -> None:
    client = TestClient(app)

    response = client.get("/panel")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "charset=utf-8" in response.headers["content-type"]
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert response.headers["pragma"] == "no-cache"
    assert "OpenClaw Console" in response.text
    assert "/panel/assets/panel.js" in response.text
    assert 'class="language-toggle"' in response.text
    assert 'data-language="zh-CN"' in response.text
    assert 'class="workspace-switch"' in response.text
    assert 'data-i18n="workspace_switch"' in response.text
    assert 'class="workspace-hint workspace-hint-learn"' in response.text
    assert 'class="workspace-hint workspace-hint-execute"' in response.text
    assert 'id="agentModeLearnBtn"' in response.text
    assert 'id="agentModeExecuteBtn"' in response.text
    assert 'id="agentModeSystemBtn"' not in response.text
    assert 'id="settingsBtn"' in response.text
    assert 'class="settings-gear"' in response.text
    assert 'class="workspace-option active"' in response.text
    assert 'class="mode-group"' not in response.text
    assert 'data-i18n="nav_group_system"' in response.text
    assert 'data-i18n="nav_group_learn"' in response.text
    assert 'data-i18n="nav_group_execute"' in response.text
    assert 'data-i18n="nav_group_learn_flow"' in response.text
    assert 'data-i18n="nav_group_execute_flow"' in response.text
    assert 'data-stage="learn_interface"' in response.text
    assert 'data-stage="template_display"' in response.text
    assert 'data-stage="learn_validation"' in response.text
    assert 'data-stage="execute_actions"' in response.text
    assert 'data-stage="execute_task_run"' in response.text
    assert 'data-stage="execute_locate"' in response.text
    assert 'data-i18n="nav_group_replay"' not in response.text
    assert 'data-i18n="nav_group_replay_flow"' not in response.text
    assert 'data-stage="open_bind"' in response.text
    assert 'data-stage="capture"' in response.text
    assert 'data-stage="learn_interface" data-step="1"' in response.text
    assert 'data-stage="template_display" data-step="2"' in response.text
    assert 'data-stage="trace" data-step="3"' in response.text
    assert 'data-stage="learn_validation" data-step="4"' in response.text
    assert 'data-stage="execute_task_run" data-step="2"' in response.text
    assert 'data-stage="execute_actions" data-step="1"' in response.text
    assert 'data-stage="execute_locate" data-step="3"' in response.text
    assert 'id="pageMetaStrip"' in response.text
    assert 'id="pageApiBadge"' in response.text
    assert 'id="pageSideEffectBadge"' in response.text
    assert 'id="resetLayoutBtn"' in response.text
    assert 'data-mode-scope="learn"' in response.text
    assert 'data-mode-scope="execute"' in response.text
    assert 'id="traceModeFilter"' in response.text
    assert 'id="learnFastBtn"' not in response.text
    assert 'id="learnDeepBtn"' not in response.text
    assert 'id="observeBtn" data-i18n="learn_fast_build_path"' in response.text
    assert 'id="locateBtn" data-i18n="learn_deep_calibrate_path"' in response.text
    assert 'id="writePathGraph"' in response.text
    assert 'id="writeElementMemory"' in response.text
    assert 'id="writeTrace"' in response.text
    assert 'id="windowSelect"' in response.text
    assert 'id="appCatalogSelect"' in response.text
    assert 'id="appCatalogOptions"' in response.text
    assert 'id="appId" value=""' in response.text
    assert 'id="appUrl" value=""' in response.text
    assert 'id="observeApp" value=""' in response.text
    assert 'id="observeState" value=""' in response.text
    assert 'id="locateApp" value=""' in response.text
    assert 'id="locateState" value=""' in response.text
    assert 'id="executeApp" value=""' in response.text
    assert 'id="executeActionsApp" value=""' in response.text
    assert 'id="executeActionsGraphPath"' in response.text
    assert 'id="executeActionsGraphJson"' in response.text
    assert 'id="executeObserveBtn"' in response.text
    assert 'id="availableActionsBtn"' in response.text
    assert 'id="learnValidationPlanBtn"' in response.text
    assert 'id="learnValidationStepBtn"' in response.text
    assert 'id="replayPreset"' in response.text
    assert 'value="github_issues">GitHub Issues' in response.text
    assert 'id="replayGraphPath"' in response.text
    assert 'id="replayAppProfileId"' in response.text
    assert 'id="replayAppProfileLoadBtn"' in response.text
    assert 'id="replayAppProfileSummary"' in response.text
    assert 'id="replayAgentPromptId"' in response.text
    assert 'id="replayAgentPromptVersion"' in response.text
    assert 'id="replayAgentPromptVersionSelect"' in response.text
    assert 'id="replayAgentPromptCompareVersion"' in response.text
    assert 'id="replayAgentPromptLoadBtn"' in response.text
    assert 'id="replayAgentPromptVersionsBtn"' in response.text
    assert 'id="replayAgentPromptLoadVersionBtn"' in response.text
    assert 'id="replayAgentPromptDiffBtn"' in response.text
    assert 'id="replayAgentPromptSaveBtn"' in response.text
    assert 'id="replayAgentPromptRollbackBtn"' in response.text
    assert 'id="replayAgentPromptSummary"' in response.text
    assert 'id="replayAgentPromptTemplate"' in response.text
    assert 'id="replayAgentPromptDiff"' in response.text
    assert 'id="replayInterfaceMapPath"' in response.text
    assert 'id="replayInterfaceCalibrationPath"' in response.text
    assert 'data-i18n="template_replay_section"' in response.text
    assert 'data-i18n="learning_studio_section"' in response.text
    assert 'data-learn-replay-view="template"' in response.text
    assert 'data-learn-replay-view="draft"' in response.text
    assert 'data-learn-replay-panel="template"' in response.text
    assert 'data-learn-replay-panel="draft"' in response.text
    assert 'id="replayModelArtifactPath"' in response.text
    assert 'id="learningTrialApp"' in response.text
    assert 'id="learningTrialState"' in response.text
    assert 'id="learningTrialImagePath"' in response.text
    assert 'id="learningTrialResultPath"' in response.text
    assert 'id="learningTrialResultPath" value=""' in response.text
    assert 'id="learningDraftReviewSourcePath" value=""' in response.text
    assert 'id="learningPathGraphCandidatePath" value=""' in response.text
    assert 'id="learningPathGraphValidationPath" value=""' in response.text
    assert "new_site_python_org_20260702_after_similarity_fix" not in response.text
    assert "trial_result_cae1c88703" not in response.text
    assert 'id="learningPathGraphCandidatePath"' in response.text
    assert 'id="learningPathGraphValidationPath"' in response.text
    assert 'id="replayLoadBtn"' in response.text
    assert 'id="replayModelArtifactLoadBtn"' in response.text
    assert 'value="model_artifact_single_step">model_artifact_single_step' in response.text
    assert 'id="replayInterfaceMapLoadBtn"' in response.text
    assert 'id="replayInterfaceCalibrationLoadBtn"' in response.text
    assert 'id="learningGeneralizationBtn"' not in response.text
    assert 'id="learningDraftGenerateBtn"' not in response.text
    assert 'id="learningTemplateViewBtn"' not in response.text
    assert 'id="learningDraftViewBtn"' not in response.text
    assert 'id="learningWorkbench"' not in response.text
    assert 'id="learningTemplatePanel"' not in response.text
    assert 'id="learningOutputPanel"' not in response.text
    assert 'id="learningDraftReviewLoadBtn"' in response.text
    assert 'id="learningDraftRecommendedLoadBtn"' in response.text
    assert 'id="learningDraftReviewSaveBtn"' in response.text
    assert 'id="learningAssistedTemplateAcceptanceSimulationBtn"' in response.text
    assert 'id="learningAssistedTemplateAcceptanceSimulationSummary"' in response.text
    assert 'data-i18n="learning_assisted_template_acceptance_simulation_create"' in response.text
    assert 'id="learningAssistedTemplateAuditedPromotionRequestBtn"' in response.text
    assert 'id="learningAssistedTemplateAuditedPromotionRequestSummary"' in response.text
    assert 'data-i18n="learning_assisted_template_audited_promotion_request_create"' in response.text
    assert 'id="learningAssistedTemplateDecisionsSaveAuditPreviewBtn"' in response.text
    assert 'data-i18n="learning_assisted_template_decisions_save_audit_preview"' in response.text
    assert 'id="learningTrialCaptureBtn"' in response.text
    assert 'id="learningTrialRunBtn"' in response.text
    assert 'id="learningPathGraphCandidateBtn"' in response.text
    assert 'id="learningPreciseUnderstandingCandidateBtn"' in response.text
    assert 'data-i18n="learning_precise_understanding_candidate_create"' in response.text
    assert 'id="learningPageDetailCandidateBtn"' in response.text
    assert 'data-i18n="learning_page_detail_candidate_create"' in response.text
    assert 'id="learningDemoScaffoldBtn"' in response.text
    assert 'data-i18n="learning_demo_scaffold_create"' in response.text
    assert 'id="learningDemoGoalReadinessBtn"' in response.text
    assert 'data-i18n="learning_demo_goal_readiness_create"' in response.text
    assert 'id="learningDraftFreshnessDemoCase"' in response.text
    assert 'id="learningDraftFreshnessDemoBtn"' in response.text
    assert 'id="learningDraftReviewPanel"' in response.text
    assert 'id="learningDraftPathPreview"' in response.text
    assert 'id="learningDraftPathMap"' in response.text
    assert 'id="learningDraftPathDetail"' in response.text
    assert 'data-i18n="learning_draft_path_preview_title"' in response.text
    assert 'class="replay-action-disclosure"' in response.text
    assert 'data-i18n="replay_advanced_actions"' in response.text
    assert 'id="learningDraftReviewSummary"' in response.text
    assert 'data-i18n="learning_draft_states"' in response.text
    assert 'data-i18n="learning_draft_regions"' in response.text
    assert 'data-i18n="learning_draft_actions"' in response.text
    assert 'id="learningLoadDraftGraphBtn"' not in response.text
    assert 'id="learningShowInterfaceDetailsBtn"' not in response.text
    assert 'id="learningDraftPanel"' not in response.text
    assert 'id="replayInterfaceMapSaveName"' in response.text
    assert 'id="replayInterfaceMapSaveBtn"' in response.text
    assert 'id="seekApplicationRecordPath"' in response.text
    assert 'id="seekApplicationAuditPath"' in response.text
    assert 'id="seekApplicationArtifactPath"' in response.text
    assert 'id="seekApplicationEvidenceLoadBtn"' in response.text
    assert 'id="seekApplicationEvidenceSummary"' in response.text
    assert 'id="seekApplicationFilledFields"' in response.text
    assert 'id="replayRegressionPath"' in response.text
    assert 'id="replayRegressionLoadBtn"' in response.text
    assert 'id="learnSampleGatePath"' in response.text
    assert 'id="learnSampleGateLoadBtn"' in response.text
    assert 'data-i18n="learn_sample_gate"' in response.text
    assert 'value="python_docs_search">Python Docs Search' in response.text
    assert 'id="replayValidationPlanBtn"' in response.text
    assert 'id="replayTaskStepBtn"' in response.text
    assert 'id="taskRunStartBtn"' in response.text
    assert 'id="taskRunNextBtn"' in response.text
    assert 'data-i18n="app_catalog_help"' in response.text
    assert 'data-i18n="window_candidates_help"' in response.text
    assert 'data-i18n="allow_apply_entry_help"' in response.text
    assert 'id="pointX" type="number"' in response.text
    assert 'id="pointY" type="number"' in response.text
    assert 'id="dryRunBtn" data-i18n="plan_click_preview"' in response.text
    assert 'id="executeBtn" class="danger" data-i18n="plan_execute_click"' in response.text
    assert 'id="confirmedDryRunBtn" data-i18n="point_click_preview"' in response.text
    assert 'id="confirmedClickBtn" class="danger" data-i18n="point_execute_click"' in response.text
    assert 'id="observeModelProfile"' in response.text
    assert 'id="locateModelProfile"' in response.text
    assert 'id="modelTestSendBtn"' in response.text
    assert 'id="modelTestProfile"' in response.text
    assert 'id="modelTestImagePath"' in response.text
    assert 'id="applyObserveModelBtn"' in response.text
    assert 'id="applyLocateModelBtn"' in response.text
    assert 'nav-path-panel' in response.text
    assert 'id="flowDiagram"' in response.text
    assert 'id="savePathBtn"' in response.text
    assert 'id="navPathCanvas"' in response.text
    assert response.text.index('id="navPathPanel"') < response.text.index('class="panel preview-panel"')
    assert response.text.index('class="panel preview-panel"') < response.text.index('<aside class="response-surface">')
    assert 'data-page="open_bind"' in response.text
    assert 'id="listAppsBtn"' in response.text
    assert 'data-page="model_test"' in response.text
    assert 'id="roiX"' in response.text
    assert 'id="analyzeBtn"' in response.text
    assert 'id="manualBoxBtn"' in response.text
    assert 'id="saveAsOverlay"' in response.text
    assert 'id="saveAsFileName"' in response.text
    assert 'id="saveAsConfirmBtn"' in response.text


def test_web_panel_serves_static_assets() -> None:
    client = TestClient(app)

    response = client.get("/panel/assets/panel.js")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert response.headers["pragma"] == "no-cache"
    assert "renderNavPath" in response.text
    assert "renderFlowGraph" in response.text
    assert "detectFlowStagesFromResponse" in response.text
    assert "savePathGraph" in response.text
    assert "confirmSaveAs" in response.text
    assert "buildPathGraphPayload" in response.text
    assert "generateFakePathData" in response.text
    assert "ALL_FLOW_STAGES" in response.text
    assert "applyLanguage" in response.text
    assert "function setAppCatalog" in response.text
    assert '["data", "catalog", "apps"]' in response.text
    assert "setWindowCandidates" in response.text
    assert "testModelService" in response.text
    assert "DEFAULT_STAGE_PROFILE_IDS" in response.text
    assert 'observe: "qwen3_vl_8b_q4_k_m"' in response.text
    assert 'understanding: "qwen3_vl_8b_q4_k_m"' in response.text
    assert 'locate: "vista_4b_transformers"' in response.text
    assert 'on("modelTestStage", "change", () => syncModelTestProfile())' in response.text
    assert 'warning: { color: "#71634e"' in response.text
    assert 'setStatus("model service loading", "warning")' in response.text
    assert "model service not found" in response.text
    assert "ensureStageModelReady" in response.text
    assert "panel_model_action_v1" in response.text
    assert "waitControl?.checked" in response.text
    assert "syncAppAndStateFields" in response.text
    assert "appNameFromWindow" in response.text
    assert "appIdFromProcessName" in response.text
    assert "PAGE_REGISTRY" in response.text
    assert "/execute/available_actions" in response.text
    assert "/vision/observe_screen" in response.text
    assert "callExecuteObserve" in response.text
    assert "callAvailableActions" in response.text
    assert "buildAvailableActionsPayload" in response.text
    assert "generateLearnValidationPlan" in response.text
    assert "runLearnValidationStep" in response.text
    assert "loadReplayArtifact" in response.text
    assert "loadReplayModelArtifact" in response.text
    assert "/panel/load_model_artifact" in response.text
    assert "loadLearningDraftReview" in response.text
    assert "saveLearningDraftReview" in response.text
    assert "runLearningDraftTrial" in response.text
    assert "captureLearningDraftWindow" in response.text
    assert "buildLearningDraftObservationEvidence" in response.text
    assert "screenMapEvidenceCount" in response.text
    assert "compactLearningDraftTargets" in response.text
    assert "learningRecognitionTrialRequestPayload" in response.text
    assert "coordinate_validation:" in response.text
    assert "screen_map:" in response.text
    assert "screen_map_available_no_recent_learn_deep" in response.text
    assert "panel_learning_draft_observation_evidence_v1" in response.text
    assert "setLearnReplaySubview" in response.text
    assert "applyLearnReplaySubviewChrome" in response.text
    assert "/panel/run_learning_recognition_trial" in response.text
    assert "/panel/run_learning_two_stage_understanding" in response.text
    assert "generatePathGraphCandidate" in response.text
    assert "renderLearningDraftPathPreview" in response.text
    assert "renderLearningDraftPathDetail" in response.text
    assert "renderLearningDraftPageDetailCards" in response.text
    assert "renderLearningDraftPipelineAudit" in response.text
    assert "renderLearningDraftPathgraphReviewQueue" in response.text
    assert "renderLearningDraftPathgraphPreflightPlan" in response.text
    assert "learningDraftPreviewButton" in response.text
    assert "previewLearningDraftBbox" in response.text
    assert "bindLearningDraftPreviewButtons" in response.text
    assert "openImageInspector" in response.text
    assert "closeImageInspector" in response.text
    assert "applyImageInspectorSelectionToDraft" in response.text
    assert "bindImageInspectorEditDrag" in response.text
    assert "learningDraftHumanReviewMeta" in response.text
    assert "learningDraftBboxText" in response.text
    assert "learningDraftManualBboxEditSummary" in response.text
    assert "renderLearningDraftManualBboxEditSummary" in response.text
    assert "manual_bbox_edit_summary_v1" in response.text
    assert "learningDraftSourceFreshnessSummary" in response.text
    assert "renderLearningDraftSourceFreshnessSummary" in response.text
    assert "source_freshness_summary_v1" in response.text
    assert "loadLearningDraftFreshnessDemo" in response.text
    assert "LEARNING_DRAFT_FRESHNESS_DEMO_CASES" in response.text
    assert "artifacts/learning-draft-freshness-demo/freshness_demo_summary.json" in response.text
    assert "learning-review-edited-badge" in response.text
    assert "if (!bbox && !(editKind && imagePath)) return" in response.text
    assert "if (!hasBbox && !editContext)" in response.text
    assert "region_bbox_updates" in response.text
    assert "action_bbox_updates" in response.text
    assert "learning_draft_page_understanding" in response.text
    assert "learning_draft_pipeline_audit" in response.text
    assert "learning_draft_preview_bbox" in response.text
    assert "learning_draft_image_inspector" in response.text
    assert "learning_draft_edit_bbox" in response.text
    assert "learning_draft_apply_selected_bbox" in response.text
    assert "learning_draft_drag_bbox_hint" in response.text
    assert "learning_draft_bbox_edited" in response.text
    assert "learning_draft_bbox_edit_summary" in response.text
    assert "learning_draft_source_freshness_summary" in response.text
    assert "learning_draft_freshness_demo_case" in response.text
    assert "learning_draft_load_freshness_demo" in response.text
    assert "learning_draft_cleanup" in response.text
    assert "learning_draft_gate" in response.text
    assert "learning_draft_roi_grounding" in response.text
    assert "learning_draft_fusion_status" in response.text
    assert "gate_diagnosis" in response.text
    assert "learning_draft_pathgraph_review_queue" in response.text
    assert "pathgraph_queue:open_detail" in response.text
    assert "review_bucket" in response.text
    assert "learning_draft_pathgraph_preflight_plan" in response.text
    assert "preflight:open_detail_transitions" in response.text
    assert "preflight:pending_calibration_ready" in response.text
    assert "pending_calibration_ready_count" in response.text
    assert "pending_calibration_batch" in response.text
    assert "pathgraphReadinessCurrentEvidencePacket" in response.text
    assert "pathgraphReadinessPreciseUnderstandingCandidate" in response.text

    assert "renderLearningPageDetailCandidate" in response.text
    assert "renderLearningPageDetailSpatialMap" in response.text
    assert "learning-page-layout-map" in response.text
    assert "learning-page-detail-sections" in response.text
    assert "current_evidence_packet=available" in response.text
    assert "current_packet_coverage=${currentEvidencePacketSummary.coverage}" in response.text
    assert "current_evidence_packet=${currentEvidencePacketReportPath}" in response.text
    assert "current_evidence_packet_safety=${currentEvidencePacketSummary.safety.join" in response.text
    assert "precise_understanding=${preciseUnderstandingCandidate.readiness_status}" in response.text
    assert "precise_understanding_candidate=${preciseUnderstandingReportPath}" in response.text
    assert "precise_understanding_safety=${preciseUnderstandingSummary.safety.join" in response.text
    assert "learning_draft_review_patch_proposal" in response.text
    assert "review_patch:actions" in response.text
    assert "learning_assisted_template_package_path" in response.text
    assert "learning_assisted_template_package_create" in response.text
    assert "learning_assisted_template_package_load" in response.text
    assert "learning_assisted_template_suggestions_create" in response.text
    assert "learning_assisted_template_suggestions" in response.text
    assert "learning_assisted_template_acceptance_simulation_create" in response.text
    assert "learning_assisted_template_acceptance_simulation" in response.text
    assert "learning_assisted_template_acceptance_simulation_apply" in response.text
    assert "learning_assisted_template_asset_candidate_path" in response.text
    assert "learning_assisted_template_asset_candidate_create" in response.text
    assert "learning_assisted_template_graph_draft_path" in response.text
    assert "learning_assisted_template_graph_draft_create" in response.text
    assert "learning_assisted_template_checklist" in response.text
    assert "learning_assisted_template_decisions_save" in response.text
    assert "learning_assisted_template_decisions_save_export" in response.text
    assert "learning_assisted_template_decisions_save_graph_preview" in response.text
    assert "learning_assisted_template_decisions_save_audit_preview" in response.text
    assert "learning_assisted_template_promotion_preflight_create" in response.text
    assert "learning_assisted_template_promotion_preflight" in response.text
    assert "learning_assisted_template_audited_promotion_request_create" in response.text
    assert "learning_assisted_template_audited_promotion_request" in response.text
    assert "screen_understanding_full_overlay" in response.text
    assert "screen_understanding_calibration_backlog" in response.text
    assert "screen_understanding_calibration_batch_plan" in response.text
    assert "screen_understanding_calibration_handoff" in response.text
    assert "screen_understanding_calibration_batch_acceptance" in response.text
    assert "renderScreenUnderstandingCalibrationBatchAcceptance" in response.text
    assert "calibration_batch_acceptance_report" in response.text
    assert "ready_for_post_batch_refresh" in response.text
    assert "screen_understanding_handoff_consistency" in response.text
    assert "renderScreenUnderstandingHandoffConsistency" in response.text
    assert "calibration_handoff_consistency_report" in response.text
    assert "consistency_status" in response.text
    assert "screen_understanding_evidence_integrity" in response.text
    assert "renderScreenUnderstandingEvidenceIntegrity" in response.text
    assert "missing_declared_evidence" in response.text
    assert "sha256" in response.text
    assert "renderScreenUnderstandingCalibrationHandoff" in response.text
    assert "calibration_handoff_report" in response.text
    assert "safe_to_start_after_user_approval" in response.text
    assert "rerun_report_status" in response.text
    assert "backlog_ready" in response.text
    assert "backlog_review" in response.text
    assert "batch_ready" in response.text
    assert "batch_review" in response.text
    assert "calibration_batch_ready_region_numbers" in response.text
    assert "command_executes_now" in response.text
    assert "precise_understanding_readiness_summary" in response.text
    assert "readiness=" in response.text
    assert "pending_ready=" in response.text
    assert "pending_review=" in response.text
    assert "calibration_backlog_items" in response.text
    assert "full_screen_understanding_overlay_path" in response.text
    assert "showScreenUnderstandingOverlay" in response.text
    assert "learning_draft_review_only_regions" in response.text
    assert "learning_draft_grounding_candidates" in response.text
    assert "pageDetails.pipeline_audit" in response.text
    assert "data-learning-draft-preview-bbox" in response.text
    assert "draft.page_details" in response.text
    assert "data-learning-draft-node" in response.text
    assert "/panel/generate_pathgraph_candidate" in response.text
    assert "/panel/create_assisted_template_review_package" in response.text
    assert "/panel/create_assisted_template_audited_promotion_request" in response.text
    assert "/panel/load_assisted_template_review_package" in response.text
    assert "/panel/create_assisted_template_acceptance_suggestions" in response.text
    assert "/panel/create_assisted_template_acceptance_simulation" in response.text
    assert "applyAssistedTemplateAcceptanceSimulationToChecklist" in response.text
    assert "saveAssistedTemplateReviewDecisionsAndBuildAuditPreview" in response.text
    assert "audit_request_preview_path" in response.text
    assert "data-assisted-template-simulation-apply" in response.text
    assert "simulation_applied_to_unsaved_checklist" in response.text
    assert "/panel/save_assisted_template_review_decisions" in response.text
    assert "/panel/create_assisted_template_asset_candidate" in response.text
    assert "/panel/create_assisted_template_graph_draft" in response.text
    assert "/panel/create_assisted_template_promotion_preflight" in response.text
    assert "renderAssistedTemplateAcceptanceSuggestions" in response.text
    assert "applyAssistedTemplateSuggestion" in response.text
    assert "data-assisted-template-suggestion-apply" in response.text
    assert "renderAssistedTemplateCompletenessSummary" in response.text
    assert "learning_assisted_template_completeness" in response.text
    assert "saveAssistedTemplateReviewDecisionsAndBuildGraphDraft" in response.text
    assert "renderAssistedTemplateReviewToGraphDiff" in response.text
    assert "learning_assisted_template_review_to_graph_diff" in response.text
    assert "renderAssistedTemplatePromotionPreflight" in response.text
    assert "createAssistedTemplatePromotionPreflight" in response.text
    assert "blocker_details" in response.text
    assert "recommended_action" in response.text
    assert "renderAssistedTemplateGraphDraftSummary" in response.text
    assert "renderAssistedGraphDraftList" in response.text
    assert "data-assisted-template-decision" in response.text
    assert "data-assisted-template-note" in response.text
    assert "data-assisted-template-override" in response.text
    assert "semantic_action" in response.text
    assert "target_entity" in response.text
    assert "/panel/load_learning_draft_review" in response.text
    assert "/panel/save_learning_draft_review" in response.text
    assert 'on("replayModelArtifactLoadBtn", "click", loadReplayModelArtifact)' in response.text
    assert 'task_template === "model_artifact_single_step"' in response.text
    assert 'isModelArtifactTaskRun' in response.text
    assert 'model_learning_artifact_loader_v1' in response.text
    assert 'if (isModelLoadedRuntimePathGraph(graph)) return null;' in response.text
    assert "renderReplayGraph" in response.text
    assert "loadSeekApplicationEvidence" in response.text
    assert "renderSeekApplicationEvidence" in response.text
    assert "DEFAULT_SEEK_APPLICATION_RECORD_PATH" in response.text
    assert "DEFAULT_SEEK_GRAPH_PATH" in response.text
    assert "DEFAULT_WIKIPEDIA_GRAPH_PATH" in response.text
    assert "DEFAULT_GITHUB_ISSUES_GRAPH_PATH" in response.text
    assert "DEFAULT_PYTHON_DOCS_SEARCH_GRAPH_PATH" in response.text
    assert "DEFAULT_ARTIFACT_REPLAY_REGRESSION_PATH" in response.text
    assert "renderReplayRegressionReport" in response.text
    assert "loadReplayRegressionReport" in response.text
    assert "executeTaskRunNextStep" in response.text
    assert "DEFAULT_INPUT_DEMO_GRAPH_PATH" in response.text
    assert "read_issue_thread" in response.text
    assert "input_write_action_forbidden_in_learn_validation" in response.text
    assert "planned_not_executed" in response.text
    assert "responseAllowsPathGraphWrite" in response.text
    assert "select_launch_app" in response.text
    assert "Coordinate Calibration / Learn Deep" in response.text
    assert "Build click plan (no window action)" in response.text
    assert "Real coordinate click" in response.text
    assert "refreshDraggableCards" in response.text
    assert "cardCanMoveToContainer" in response.text
    assert "preparePointerCardDrag" in response.text
    assert "CARD_DRAG_START_THRESHOLD_PX" in response.text
    assert "startPointerCardDrag" in response.text
    assert "syncDraggedCardToPoint" in response.text
    assert "card-drag-placeholder" in response.text
    assert "card-drag-zone" in response.text
    assert "card-drag-handle" not in response.text
    assert "data-drag-label" not in response.text
    assert "isOperationalProfile" in response.text
    assert "modelProfiles.filter(isOperationalProfile)" in response.text
    assert "previous && isOperationalProfile(previousProfile) ? previous : defaultProfileId(stage)" in response.text
    assert "resetCardLayout" in response.text
    assert "CARD_ORDER_STORAGE_KEY" in response.text
    assert "BROWSER_APP_IDS" in response.text
    assert "appNameFromUrl" in response.text
    assert "MouseTesterWeb" in response.text
    assert "stripBrowserTitleSuffix" in response.text
    assert "canonicalAppNameFromTitle" in response.text
    assert "stateHintFromWindow" in response.text
    assert "syncWindowAppAndState" in response.text
    assert "Agentic Loop-first" in response.text
    assert "const workflowStep = options.workflowStep || null" in response.text
    assert "roiPayload" in response.text
    assert "callAnalyzeApi" in response.text
    assert "generateManualBox" in response.text
    assert "applyModelProfile" in response.text
    assert "collectControlsFromResult" in response.text
    assert "modePayload" in response.text
    assert "syncStageLearningControls" in response.text
    assert 'stage === "observe" ? "learn"' in response.text
    assert 'stage === "observe" ? "fast"' in response.text
    assert 'return new Set(["locate", "execute_actions", "learn_replay", "learn_validation", "execute_task_run", "execute"]);' in response.text
    assert "function currentPageAllowsSharedPathSurface" in response.text
    assert "function isScreenUnderstandingResponse" in response.text
    assert "if (isScreenUnderstandingResponse(result)) return false;" in response.text
    assert "function resetSharedPathForScreenUnderstanding" in response.text
    assert "function isScreenUnderstandingStageActive" in response.text
    assert "function shouldBlockPathGraphRestoreForScreenUnderstanding" in response.text
    assert 'document.body.dataset.pathSurface = pathVisible ? "visible" : "hidden"' in response.text
    assert "const pathVisible = setSharedPathSurfaceVisibility(page)" in response.text
    assert "pathPanel.hidden = !pathVisible" in response.text
    assert "pathDetailPanel.hidden = !pathVisible" in response.text
    assert 'pathPanel.setAttribute("aria-hidden", pathVisible ? "false" : "true")' in response.text
    assert "clearSharedPathDetailDisplay()" in response.text
    assert "function enterScreenUnderstandingStage()" in response.text
    assert "if (page === \"observe\") enterScreenUnderstandingStage();" in response.text
    assert 'document.body.dataset.pathSurface = "hidden";' in response.text
    assert 'setSharedPathSurfaceVisibility("observe");' in response.text
    assert "cancelAnimationFrame(pathAnimId);" in response.text
    assert 'ctx.clearRect(0, 0, canvas.width || 0, canvas.height || 0);' in response.text
    assert "renderNavPath();" in response.text
    assert "if (!sharedPathSurfaceVisible())" in response.text
    assert "document.body.dataset.stagePage = page" in response.text
    assert 'document.body.classList.toggle("learn-fast-clean-stage", page === "observe")' in response.text
    assert 'if (isScreenUnderstandingResponse(result)) return;' in response.text
    assert 'const isObserveScreenTask = taskType === "observe_screen"' in response.text
    assert "const restored = isObserveScreenTask ? false : restorePathGraph(respAppName)" in response.text
    assert "if (shouldBlockPathGraphRestoreForScreenUnderstanding())" in response.text
    restore_body = response.text[
        response.text.index("function restorePathGraph"):
        response.text.index("function updatePathAppLabel")
    ]
    runtime_render_body = response.text[
        response.text.index("function renderRuntimePathGraph"):
        response.text.index("function updateRuntimePathGraphHighlight")
    ]
    assert "resetSharedPathForScreenUnderstanding(appName || navPathAppName)" in restore_body
    assert "resetSharedPathForScreenUnderstanding(options.path || graph.app_id || navPathAppName)" in runtime_render_body
    assert "const isObserveScreenResponse =" in response.text
    assert "resetSharedPathForScreenUnderstanding(result.app_name || nestedGet(result, [\"request\", \"app_name\"]) || navPathAppName)" in response.text
    assert "if (isObserveScreenResponse) hideSharedPathSurface();" in response.text
    assert 'const needsPreview = new Set(["capture", "observe", "locate", "execute"]);' in response.text
    assert 'goal: learnLocate ? "learn all visible controls" : goal' in response.text
    assert "learn_fast_build_path" in response.text
    assert "learn_deep_calibrate_path" in response.text
    assert "locate_current_target" in response.text
    assert "writePolicyPayload" in response.text
    assert "agent_mode" in response.text
    assert "learn_depth" in response.text
    assert "write_policy" in response.text
    assert "screen_map?.candidates" in response.text
    assert "screen_map_candidate_v1" in response.text
    assert "PATH_CANVAS_FONT" in response.text
    assert "traceDisplayValue" in response.text
    assert "collectTraceStageVisuals" in response.text
    assert "current_roi_ref" in response.text
    assert "current_match_ref" in response.text
    assert "learned_interface_map" in response.text
    assert "renderInterfaceMap" in response.text
    assert "loadReplayInterfaceCalibrationReport" in response.text
    assert "loadLearningGeneralization" not in response.text
    assert "/runtime/learning/seek/draft" not in response.text
    assert "/runtime/learning/generalization" not in response.text
    assert "interfaceCalibrationSummaryHtml" in response.text
    assert "interfaceCalibrationMatchForAsset" in response.text
    assert "interfaceReviewPolicyForAsset" in response.text
    assert "interfaceClickPermissionMeta" in response.text
    assert "normalizeInterfaceMapReviewPolicies" in response.text
    assert "syncInterfaceMapDangerZones" in response.text
    assert "click_permission" in response.text
    assert "manual_review_required" in response.text
    assert "gate_required" in response.text
    assert "initialStageFromQuery" in response.text
    assert "skip_boot_models" in response.text
    assert "panelQueryFlag" in response.text
    assert "low_risk_fast_lane_eligible" in response.text
    assert "recropInterfaceAsset" in response.text
    assert "openInterfaceCropSelector" in response.text
    assert "interfaceAssetFullSourceImage" in response.text
    assert "source.source_image_path || source.capture_id || crop.source_image_path || geometry.source_image_path || refs.source_image_path" in response.text
    assert "data-interface-select-crop" in response.text
    assert "data-interface-crop-selector-image" in response.text
    assert "/panel/crop_interface_asset" in response.text
    assert "data-interface-recrops-asset" in response.text
    assert "data-interface-crop" in response.text
    assert "saveReplayInterfaceMap" in response.text
    assert "/panel/save_interface_map" in response.text
    assert "data-interface-edit" in response.text
    assert "data-interface-inspect" in response.text
    assert "interfaceInspectorHtml" in response.text
    assert "interfaceStateFlowHtml" in response.text
    assert "interfaceRegionLaneHtml" in response.text
    assert "source bbox is learning evidence only" in response.text
    assert "Current match required" in response.text
    assert "Visual calibration" in response.text
    assert "interface_map_calibration_panel_load_v1" in response.text
    assert "can_authorize_click = false" in response.text
    assert "replay_current_roi" in response.text
    assert "score_gap" in response.text or "score gap" in response.text
    assert "activateTraceStageVisuals" in response.text
    assert "tracePathMapHtml" in response.text
    assert "traceDynamicPathGraphHtml" in response.text
    assert "applyPathMapReview" in response.text
    assert "path_map_review" in response.text
    assert "candidate_id" in response.text
    assert "section_id" in response.text
    assert "learn_all_targets" in response.text
    assert "coordinate_overlay_path" in response.text
    assert '["learn_all_targets", "overlay_path"]' in response.text
    assert "Learn Mode locates every current PathGraph child control" in response.text
    assert "pathControlNodeId" in response.text
    assert "expandedPathNodeId" in response.text
    assert "lastIndexOf" in response.text
    assert "applyPathReviewUpdate" in response.text
    assert "renderFocusedControlDetail" in response.text

    css_response = client.get("/panel/assets/panel.css")

    assert css_response.status_code == 200
    assert css_response.headers["cache-control"] == "no-store, max-age=0"
    assert css_response.headers["pragma"] == "no-cache"
    assert "path-detail-sections" in css_response.text
    assert "interface-known-layout-seek-application" in css_response.text
    assert "interface-region-summary" in css_response.text
    assert "interface-inspector-summary" in css_response.text
    assert "interface-inspector-region-action-group" in css_response.text
    assert "runtime-node-region-action-group" not in css_response.text
    assert "Microsoft YaHei" in css_response.text
    assert "grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr)" in css_response.text
    assert "tf-stage-visuals" in css_response.text
    assert "tf-stage-image-missing" in css_response.text
    assert "tf-path-map" in css_response.text
    assert "tf-path-graph" in css_response.text
    assert "mode-strip" in css_response.text
    assert "workspace-switch" in css_response.text
    assert "workspace-option" in css_response.text
    assert "nav-group-subtitle" in css_response.text
    assert "body.agent-mode-learn .nav-group-execute" in css_response.text
    assert "body.agent-mode-execute .nav-group-learn" in css_response.text
    assert ".settings-entry" in css_response.text
    assert "body.agent-mode-learn .nav-group-system" in css_response.text
    assert "card-drop-active" in css_response.text
    assert "card-drag-zone" in css_response.text
    assert "card-drag-placeholder" in css_response.text
    assert "card-dragging-active" in css_response.text
    assert "meta-action" in css_response.text
    assert "run-summary" in css_response.text
    assert "interface-map-panel" in css_response.text
    assert "interface-workbench" in css_response.text
    assert "interface-canvas" in css_response.text
    assert "interface-calibration-summary" in css_response.text
    assert "interface-calibration-metrics" in css_response.text
    assert "interface-state-flow" in css_response.text
    assert "interface-lane-stack" in css_response.text
    assert "interface-visual-node" in css_response.text
    assert "interface-node-matched" in css_response.text
    assert "interface-node-ambiguous" in css_response.text
    assert ".interface-node-badges i.warn" in css_response.text
    assert "interface-dynamic-node" in css_response.text
    assert "interface-danger-node" in css_response.text
    assert "interface-asset-grid" in css_response.text
    assert "interface-chip-danger" in css_response.text
    assert "interface-edit-grid" in css_response.text
    assert "interface-inspector" in css_response.text
    assert "learning-draft-panel" not in css_response.text
    assert "learning-draft-card" not in css_response.text
    assert "learning-draft-table" not in css_response.text
    assert "interface-evidence-grid" in css_response.text
    assert "interface-crop-editor" in css_response.text
    assert "interface-crop-selector-modal" in css_response.text
    assert "interface-crop-selector-box" in css_response.text
    assert "run-timeline" in css_response.text
    assert "action-table" in css_response.text
    assert "ctrl-focused" in css_response.text
    assert "focused-control-card" in css_response.text
    assert ".run-badge.warn" in css_response.text


def test_learning_interface_flow_has_unified_progress_and_simple_review_surface() -> None:
    html = Path("app/web_panel/index.html").read_text(encoding="utf-8")
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8")
    panel_css = Path("app/web_panel/panel.css").read_text(encoding="utf-8")

    assert 'id="learningInterfaceRunBtn"' in html
    assert 'data-i18n="learning_interface_run"' in html
    assert 'id="learningInterfacePrepCard"' in html
    assert 'id="learningInterfaceAppCatalogSelect"' in html
    assert 'id="learningInterfaceWindowSelect"' in html
    assert 'id="learningInterfaceListAppsBtn"' in html
    assert 'id="learningInterfaceOpenAppBtn"' in html
    assert 'id="learningInterfaceListWindowsBtn"' in html
    assert 'id="learningInterfaceBindWindowBtn"' in html
    assert 'id="learningInterfaceCaptureBtn"' in html
    assert 'id="learningInterfaceFlowProgress"' in html
    assert 'id="learningInterfaceFlowStatus"' in html
    for step in [
        "bind_capture",
        "screen_understanding",
        "numbered_map",
        "page_details",
        "precise_calibration",
        "fusion",
        "pathgraph_draft",
        "complete",
    ]:
        assert f'data-learning-flow-step="{step}"' in html

    assert 'id="learningDraftHistoryList"' in html
    assert 'id="learningDraftScreenshotPanel"' in html
    assert 'id="learningDraftPathGraphPanel"' in html
    assert 'id="learningDraftPathResizer"' in html
    assert 'id="learningDraftPathLayoutResetBtn"' in html
    assert 'id="learningDraftInterfaceDetailPanel"' in html
    assert 'id="learningDraftManualEditPanel"' in html
    for field_id in [
        "learningDraftManualRegionLabel",
        "learningDraftManualRegionRole",
        "learningDraftManualRegionSection",
        "learningDraftManualOperation",
        "learningDraftManualEnterPathGraph",
        "learningDraftManualNeedsRecalibration",
        "learningDraftManualNotes",
        "learningDraftManualSaveBtn",
    ]:
        assert f'id="{field_id}"' in html

    assert '<details class="replay-action-disclosure" id="learningDraftAdvancedDiagnostics">' in html
    assert "const LEARNING_INTERFACE_FLOW_STEPS" in panel_js
    assert "function setLearningInterfaceFlowStep" in panel_js
    assert "function learningInterfaceTrialEvidenceSummary" in panel_js
    assert "function learningInterfaceTrialEvidenceStatusText" in panel_js
    assert "function learningDeepCalibrationEvidenceSummary" in panel_js
    assert "function learningDeepCalibrationEvidenceStatusText" in panel_js
    assert "function learningDeepCalibrationOverlayPath" in panel_js
    assert "function renderLearningDraftScreenshotPath" in panel_js
    assert "async function runLearningDeepCalibration" in panel_js
    assert "async function completeLearningInterfaceReadonlyFlow" in panel_js
    assert "async function runLearningInterfaceFlow" in panel_js
    assert "hasNumberedOverlayEvidence" in panel_js
    assert "hasCalibratedEvidence" in panel_js
    assert "Stage1 region gate + two-stage numbering" in panel_js
    assert "async function runLearningTwoStageUnderstanding" in panel_js
    assert "/panel/run_learning_two_stage_understanding" in panel_js
    assert "function learningTwoStageAllowsDraftTrial" in panel_js
    two_stage_overlay_start = panel_js.index("function learningTwoStageOverlayPath")
    two_stage_overlay_body = panel_js[
        two_stage_overlay_start:panel_js.index("function learningTwoStageAllowsDraftTrial", two_stage_overlay_start)
    ]
    assert two_stage_overlay_body.index("result.compiled_overlay_path") < two_stage_overlay_body.index(
        "result.coordinate_overlay_path"
    )
    assert "nestedGet(result, [\"fusion\", \"compiled_overlay_path\"])" in two_stage_overlay_body
    assert "Stage1 gate blocked Stage2" in panel_js
    assert "two-stage boxes accepted for draft review" in panel_js
    assert 'renderLearningDraftScreenshotPath(twoStageOverlayPath, "learning two-stage fused overlay")' in panel_js
    numbered_map_start = panel_js.index("function learningDraftNumberedMapImagePath")
    numbered_map_body = panel_js[numbered_map_start:panel_js.index("function renderLearningDraftScreenshotPath", numbered_map_start)]
    assert numbered_map_body.index("preview.compiled_overlay_path") < numbered_map_body.index("learningDraftSourceImagePath(draft)")
    assert "draft?.page_details?.precise_understanding_fusion_status?.compiled_overlay_path" in panel_js
    assert "filtered_non_actionable" in panel_js
    assert "two-stage fused draft · Stage1 gate passed" in panel_js
    assert "function syncLearningInterfacePrepFromSharedControls" in panel_js
    assert "function learningDraftRegionId" in panel_js
    assert "learningDraftRegionId(region, index)" in panel_js
    assert "const regionIds = new Set(regions.map((region, index) => learningDraftRegionId(region, index)))" in panel_js
    assert 'on("learningInterfaceRunBtn", "click", runLearningInterfaceFlow)' in panel_js
    assert 'on("learningInterfaceListWindowsBtn", "click", learningInterfaceListWindows)' in panel_js
    assert 'on("learningInterfaceBindWindowBtn", "click", learningInterfaceBindWindow)' in panel_js
    assert 'on("learningInterfaceCaptureBtn", "click", learningInterfaceCapture)' in panel_js
    assert "renderLearningDraftHistoryList" in panel_js
    assert "renderLearningDraftScreenshotPanel" in panel_js
    assert "renderLearningDraftManualEditPanel" in panel_js
    assert ".learning-interface-prep-card" in panel_css
    assert ".learning-interface-flow-card" in panel_css
    assert ".learning-draft-review-workspace" in panel_css
    assert ".learning-draft-screenshot-frame" in panel_css
    assert "max-height: none" in panel_css
    assert "max-height: 360px" not in panel_css


def test_learning_mode_sidebar_uses_demo_stage_names_without_draft_replay_label() -> None:
    html = Path("app/web_panel/index.html").read_text(encoding="utf-8")
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8")
    panel_css = Path("app/web_panel/panel.css").read_text(encoding="utf-8")

    expected_order = [
        'data-stage="learn_interface"',
        'data-stage="template_display"',
        'data-stage="trace"',
        'data-stage="learn_validation"',
    ]
    positions = [html.index(item) for item in expected_order]
    assert positions == sorted(positions)
    assert 'data-i18n="nav_learn_interface"' in html
    assert 'data-i18n="nav_template_display"' in html
    assert 'data-stage="learn_interface" data-step="1"' in html
    assert 'data-stage="template_display" data-step="2"' in html
    assert 'data-stage="trace" data-step="3"' in html
    assert 'data-stage="learn_validation" data-step="4"' in html
    assert 'data-i18n="nav_learn_replay"' not in html
    assert 'data-i18n="nav_learn_observe"' not in html
    assert 'data-i18n="nav_learn_locate"' not in html
    assert "学习产物回放" not in html
    assert "body.agent-mode-learn .nav-group-system" in panel_css

    assert 'learn_interface: {' in panel_js
    assert 'template_display: {' in panel_js
    assert 'learnReplaySubview: "draft"' in panel_js
    assert 'learnReplaySubview: "template"' in panel_js
    assert 'on("agentModeLearnBtn", "click", () => showStage("learn_interface"))' in panel_js
    assert 'if (page === "learn_replay" && meta.learnReplaySubview)' in panel_js


def test_panel_api_response_result_helper_preserves_two_stage_gate_data() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    result_of_start = panel_js.index("function resultOf(response)")
    result_of_body = panel_js[result_of_start:panel_js.index("function statusTextForResponse", result_of_start)]
    assert "if (Object.keys(result).length) return result;" in result_of_body
    assert "if (Object.keys(data).length) return data;" in result_of_body

    allows_start = panel_js.index("function learningTwoStageAllowsDraftTrial")
    allows_body = panel_js[allows_start:panel_js.index("async function runLearningTwoStageUnderstanding", allows_start)]
    assert 'nestedGet(result, ["stage1_gate", "status"])' in allows_body
    assert 'gateStatus === "passed"' in allows_body
    assert 'nestedGet(result, ["stage2_numbering_skipped"]) !== true' in allows_body


def test_panel_two_stage_endpoint_records_explicit_source_image_override(monkeypatch, tmp_path) -> None:
    client = TestClient(app)
    override_image = tmp_path / "override.png"
    Image.new("RGB", (111, 77), "white").save(override_image)

    monkeypatch.setattr(panel_api, "_resolve_panel_learning_image_path", lambda path: Path(path))
    monkeypatch.setattr(
        panel_api,
        "_observe_bundle_from_trace_result",
        lambda result, trace_path: {
            "image_path": "artifacts/screenshots/stale.png",
            "source_image_path": "artifacts/screenshots/stale.png",
            "screen_size": {"width": 320, "height": 240},
            "screen_reading": {"screen_summary": "demo screen"},
        },
    )
    monkeypatch.setattr(
        panel_api,
        "_stage1_inventory_from_trace_result",
        lambda result: [{"item_id": "item_1", "label": "Main", "bbox": {"x": 0, "y": 0, "w": 111, "h": 77}}],
    )
    monkeypatch.setattr(
        panel_api,
        "build_inventory_layout_graph",
        lambda inventory, screen_size=None: {"node_count": len(inventory), "zone_count": 1, "zones": {}},
    )
    captured_bundle = {}

    def fake_two_stage(**kwargs):
        captured_bundle.update(kwargs["bundle"])
        return {
            "stage1_gate": {"status": "passed", "failure_categories": [], "allow_stage2_numbering": True},
            "stage2_numbering_skipped": False,
            "stage2_numbering": {"regions": [{"region_id": "R1"}]},
            "fusion": {
                "compiled_overlay_path": "artifacts/review-overlays/demo_two_stage.png",
                "fused_review_boxes": [
                    {"id": "R1", "label": "Main", "role": "review_only", "bbox": {"x": 1, "y": 2, "w": 3, "h": 4}}
                ],
            },
        }

    monkeypatch.setattr(panel_api, "build_two_stage_screen_understanding", fake_two_stage)
    monkeypatch.setattr(panel_api, "fusion_status_from_two_stage", lambda report: {"status": "available"})

    response = client.post(
        "/panel/run_learning_two_stage_understanding",
        json={
            "app_name": "demo_app",
            "state_hint": "home",
            "source_image_path": str(override_image),
            "observe_result": {"image_path": "artifacts/screenshots/stale.png", "image_size": {"width": 320, "height": 240}},
            "require_stage1_gate": True,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["source_image_override"]["status"] == "applied"
    assert data["source_image_override"]["original_path"] == "artifacts/screenshots/stale.png"
    assert data["image_path"] == str(override_image)
    assert captured_bundle["image_path"] == str(override_image)
    assert captured_bundle["screen_size"] == {"width": 111, "height": 77}
    saved_report = json.loads(Path(data["report_path"]).read_text(encoding="utf-8-sig"))
    assert saved_report["source_image_override"]["status"] == "applied"
    assert saved_report["observe_bundle"]["image_path"] == str(override_image)


def test_panel_status_text_does_not_label_two_stage_review_boxes_as_no_targets() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    status_start = panel_js.index("function statusTextForResponse")
    status_body = panel_js[status_start:panel_js.index("function nestedGet", status_start)]

    assert 'return "stage1_blocked";' in status_body
    assert 'return "review_boxes_ready";' in status_body
    assert 'learnStatus === "two_stage_stage1_gate_passed"' in status_body
    assert 'result?.location_status === "learn_review_boxes_ready"' in status_body
    assert "reviewBoxCount > 0" in status_body
    assert "numberedRegionCount > 0" in status_body
    assert "twoStageAttached" in status_body
    assert 'resultSummary?.two_stage_report_attached === true' in status_body
    assert status_body.index('return "review_boxes_ready";') < status_body.index('return "no_targets";')


def test_learning_deep_calibration_reports_when_model_validation_did_not_run() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    summary_start = panel_js.index("function learningDeepCalibrationEvidenceSummary")
    summary_body = panel_js[summary_start:panel_js.index("function learningDeepCalibrationOverlayPath", summary_start)]
    assert "modelValidationStatus" in summary_body
    assert "vistaValidationStatus" in summary_body
    assert "learn_locate_model_review" in summary_body
    assert "vista_validation_enabled" in summary_body
    assert 'model_validation=${evidence.modelValidationStatus || "unknown"}' in panel_js
    assert 'vista_validation=${evidence.vistaValidationStatus || "unknown"}' in panel_js

    evidence_start = panel_js.index("function buildLearningDraftObservationEvidence")
    evidence_body = panel_js[evidence_start:panel_js.index("function setLearningTrialResultPath", evidence_start)]
    assert "hasCoordinateReviewEvidence" in evidence_body
    assert "hasCalibratedTargets ? " not in evidence_body
    assert "coordinate_calibration_status" in evidence_body


def test_learning_interface_keeps_display_overlay_out_of_source_image_path() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    assert "let learningSourceImagePath = \"\";" in panel_js
    assert "function isLearningDisplayOverlayPath" in panel_js
    assert "artifacts/review-overlays/" in panel_js
    assert "__two-stage-understanding__" in panel_js
    assert "function firstLearningSourceImagePath" in panel_js
    assert "function setLearningSourceImagePath" in panel_js

    set_current_start = panel_js.index("function setCurrentImage")
    set_current_body = panel_js[set_current_start:panel_js.index("function isLearningDisplayOverlayPath", set_current_start)]
    assert "learningImagePath && !isLearningDisplayOverlayPath(currentImagePath)" in set_current_body

    two_stage_start = panel_js.index("async function runLearningTwoStageUnderstanding")
    two_stage_body = panel_js[two_stage_start:panel_js.index("async function runLearningInterfaceFlow", two_stage_start)]
    assert "renderLearningDraftScreenshotPath(overlayPath, \"learning two-stage fused overlay\")" in two_stage_body
    assert "setCurrentImage(overlayPath)" not in two_stage_body

    calibration_start = panel_js.index("async function runLearningDeepCalibration")
    calibration_body = panel_js[calibration_start:panel_js.index("function learningTwoStageUnderstandingPayload", calibration_start)]
    assert "lastLearningDraftObserveTracePath || lastObserveTracePath" in calibration_body
    assert "payload.agent_mode = \"learn\"" in calibration_body
    assert "payload.learn_depth = \"deep\"" in calibration_body
    assert "payload.metadata.learn_all_targets = true" in calibration_body

    two_stage_payload_start = panel_js.index("function learningTwoStageUnderstandingPayload")
    two_stage_payload_body = panel_js[two_stage_payload_start:panel_js.index("function learningTwoStageOverlayPath", two_stage_payload_start)]
    assert "const observeResult = resultOf(lastLearningDraftObserveResponse || lastResponse);" in two_stage_payload_body
    assert "const sourceImagePath = firstLearningSourceImagePath(" in two_stage_payload_body
    assert "source_image_path: sourceImagePath || null" in two_stage_payload_body

    evidence_start = panel_js.index("function buildLearningDraftObservationEvidence")
    evidence_body = panel_js[evidence_start:panel_js.index("function setLearningTrialResultPath", evidence_start)]
    assert "const observeResult = resultOf(lastLearningDraftObserveResponse || {});" in evidence_body
    assert "observeResult.screen_map && typeof observeResult.screen_map === \"object\"" in evidence_body
    assert "current_image_path: firstLearningSourceImagePath(" in evidence_body
    assert "observeResult.image_path" in evidence_body
    assert "rejected_display_overlay_input_path" in evidence_body
    assert 'current_image_path: String($("learningTrialImagePath")?.value || currentImagePath' not in evidence_body


def test_learning_interface_flow_runs_deep_calibration_before_fusion_trial() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    flow_start = panel_js.index("async function runLearningInterfaceFlow")
    flow_body = panel_js[flow_start:panel_js.index("async function completeLearningInterfaceReadonlyFlow", flow_start)]

    assert "const calibration = await runLearningDeepCalibration()" in flow_body
    assert "const calibrationEvidence = learningDeepCalibrationEvidenceSummary(calibration)" in flow_body
    assert "const calibrationOverlayPath = learningDeepCalibrationOverlayPath(calibration)" in flow_body
    assert "renderLearningDraftScreenshotPath(calibrationOverlayPath, \"learning deep calibration overlay\")" in flow_body
    assert flow_body.index("const calibration = await runLearningDeepCalibration()") < flow_body.index(
        "const fusedTrial = await runLearningDraftTrial"
    )


def test_web_panel_saves_interface_map_with_edit_trace() -> None:
    client = TestClient(app)
    response = client.post(
        "/panel/save_interface_map",
        json={
            "file_name": "panel_test_interface_map.json",
            "source_path": "artifacts/visual-match-smoke/local_seek_buttons/learned_interface_map.json",
            "edit_summary": {"edited_in_panel": True, "authorization_changed": False},
            "payload": {
                "contract_version": "learned_interface_map_v1",
                "app_id": "seek",
                "regions": [{"region_id": "job_detail", "label": "Job detail", "region_type": "detail_content"}],
                "fixed_visual_assets": [
                    {
                        "asset_id": "seek:visual:quick_apply_button",
                        "label": "Quick apply",
                        "semantic_action": "open_apply_flow",
                        "danger_level": "low",
                        "can_authorize_click": False,
                    }
                ],
                "dynamic_areas": [],
                "danger_zones": [],
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    saved_path = Path(body["data"]["path"])
    trace_path = Path(body["data"]["trace_path"])
    assert saved_path.exists()
    assert trace_path.exists()
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert saved["contract_version"] == "learned_interface_map_v1"
    assert saved["fixed_visual_assets"][0]["can_authorize_click"] is False
    assert trace["contract_version"] == "learned_interface_map_edit_trace_v1"
    assert trace["edit_summary"]["authorization_changed"] is False
    saved_path.unlink(missing_ok=True)
    trace_path.unlink(missing_ok=True)


def test_web_panel_crops_interface_asset_with_trace() -> None:
    client = TestClient(app)
    source_path = Path("artifacts/interface-map-crop-test-source.png")
    source_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (240, 160), "white")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((80, 50, 170, 96), radius=8, fill=(230, 0, 125))
    image.save(source_path)

    response = client.post(
        "/panel/crop_interface_asset",
        json={
            "source_image_path": str(source_path),
            "asset_id": "seek:visual:quick_apply_button",
            "label": "Quick apply",
            "x": 80,
            "y": 50,
            "width": 90,
            "height": 46,
            "padding_px": 4,
            "context_padding_px": 12,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    tight_path = Path(data["tight_crop_ref"])
    context_path = Path(data["context_crop_ref"])
    trace_path = Path(data["trace_path"])
    assert tight_path.exists()
    assert context_path.exists()
    assert trace_path.exists()
    assert data["bbox"] == {"x": 80, "y": 50, "w": 90, "h": 46}
    assert data["can_authorize_click"] is False
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    assert trace["contract_version"] == "learned_interface_map_asset_crop_trace_v1"
    assert trace["artifact_is_authorization"] is False
    tight_path.unlink(missing_ok=True)
    context_path.unlink(missing_ok=True)
    trace_path.unlink(missing_ok=True)
    source_path.unlink(missing_ok=True)


def test_input_demo_runtime_path_graph_fixture_is_dry_run_only() -> None:
    path = Path("artifacts/demo/runtime_path_graph_input_demo.json")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["contract_version"] == "runtime_path_graph_v1"
    action = payload["action_templates"][0]
    assert action["action_template_id"] == "fill_demo_text_field"
    assert action["action_type"] == "input"
    assert action["input_policy"]["dry_run_only"] is True
    assert action["input_policy"]["allow_live_input"] is False
    assert action["input_policy"]["submit_allowed"] is False
    assert payload["safety_policy"]["allow_live_input"] is False
    assert payload["safety_policy"]["forbid_final_submit"] is True


def test_wikipedia_runtime_path_graph_fixture_is_read_only_page_scroll() -> None:
    path = Path("artifacts/wikipedia/runtime_path_graph_wikipedia_search_v1.json")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["contract_version"] == "runtime_path_graph_v1"
    assert payload["app_id"] == "wikipedia"
    actions = {item["action_template_id"]: item for item in payload["action_templates"]}
    assert actions["open_search_result"]["action_type"] == "click"
    assert actions["read_article"]["action_type"] == "scroll"
    assert actions["read_article"]["scroll_target"]["target_container_id"] == "wikipedia:page"
    assert actions["read_article"]["scroll_target"]["target_pane"] == "page"
    assert payload["safety_policy"]["forbid_final_submit"] is True
    assert payload["safety_policy"]["allow_live_input"] is False


def test_github_issues_runtime_path_graph_fixture_is_read_only_page_scroll() -> None:
    path = Path("artifacts/github/runtime_path_graph_github_issues_v1.json")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["contract_version"] == "runtime_path_graph_v1"
    assert payload["app_id"] == "github"
    assert payload["page_type"] == "issues_list_to_issue_detail"
    actions = {item["action_template_id"]: item for item in payload["action_templates"]}
    assert actions["open_issue_from_list"]["action_type"] == "click"
    assert "do not click the Open tab" in actions["open_issue_from_list"]["goal_template"]
    assert actions["open_issue_from_list"]["candidate_constraints"]["required_region_id"] == "issues_list"
    assert "Open" in actions["open_issue_from_list"]["candidate_constraints"]["exclude_targets"]
    assert actions["read_issue_detail"]["action_type"] == "scroll"
    assert actions["read_issue_detail"]["scroll_target"]["target_container_id"] == "github:page"
    assert actions["read_issue_detail"]["scroll_target"]["target_pane"] == "page"
    assert actions["load_more_issues"]["scroll_target"]["target_container_id"] == "github:page"
    assert payload["safety_policy"]["mode"] == "read_only"
    assert payload["safety_policy"]["forbid_final_submit"] is True
    assert payload["safety_policy"]["allow_live_input"] is False


def test_python_docs_search_runtime_path_graph_fixture_has_input_dry_run_policy() -> None:
    path = Path("artifacts/docs_search/runtime_path_graph_python_docs_search_v1.json")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["contract_version"] == "runtime_path_graph_v1"
    assert payload["app_id"] == "python_docs"
    assert payload["page_type"] == "docs_search_results_with_article"
    state_ids = {item["state_id"] for item in payload["states"]}
    assert {
        "docs:search_page",
        "docs:search_results",
        "docs:article_page",
        "docs:article_scrolled",
        "docs:blocked_write_or_login",
    } <= state_ids
    region_ids = {item["region_id"] for item in payload["regions"]}
    assert {
        "docs:search_form",
        "docs:search_input",
        "docs:search_button",
        "docs:search_results_list",
        "docs:search_result_item",
        "docs:article_body",
    } <= region_ids
    actions = {item["action_template_id"]: item for item in payload["action_templates"]}
    assert actions["type_public_search_query"]["low_level_action_type"] == "input"
    assert actions["type_public_search_query"]["input_policy"]["input_category"] == "public_search_query"
    assert actions["type_public_search_query"]["input_policy"]["submit_allowed"] is True
    assert actions["type_public_search_query"]["input_policy"]["requires_explicit_live_smoke_mode"] is True
    assert actions["trigger_search"]["low_level_action_type"] == "click"
    assert actions["open_search_result"]["low_level_action_type"] == "click"
    assert actions["read_article"]["low_level_action_type"] == "scroll"
    assert actions["read_article"]["scroll_target"]["target_container_id"] == "docs:page"
    assert payload["safety_policy"]["artifact_cannot_authorize_click"] is True
    assert payload["safety_policy"]["forbid_final_submit"] is True
    assert payload["safety_policy"]["allow_live_input"] is False
    assert "pii" in payload["safety_policy"]["forbidden_input_categories"]
    assert "Submit" in payload["safety_policy"]["forbidden_click_texts"]
    forbidden = set(payload["safety_policy"]["forbidden_targets"])
    assert {"Log in", "Edit", "Submit", "Save", "Delete", "Upload", "Comment"} <= forbidden


def test_web_panel_uploads_and_serves_image() -> None:
    client = TestClient(app)
    png_1x1 = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )

    upload = client.post(
        "/panel/upload_image",
        json={
            "filename": "sample.png",
            "content_base64": base64.b64encode(png_1x1).decode("ascii"),
            "content_type": "image/png",
        },
    )

    assert upload.status_code == 200
    assert upload.json()["success"] is True
    image_path = upload.json()["data"]["image_path"]

    served = client.get("/panel/file", params={"path": image_path})

    assert served.status_code == 200
    assert served.content == png_1x1
    assert served.headers["cache-control"] == "no-store, max-age=0"
    assert served.headers["pragma"] == "no-cache"


def test_web_panel_file_rejects_outside_paths() -> None:
    client = TestClient(app)

    response = client.get("/panel/file", params={"path": "C:/Windows/win.ini"})

    assert response.status_code == 404


def test_web_panel_trace_list_filters_pytest_temp_traces(tmp_path, monkeypatch) -> None:
    client = TestClient(app)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    trace_dir = tmp_path / "logs" / "traces" / "vision"
    trace_dir.mkdir(parents=True)
    normal_trace = trace_dir / "normal.json"
    test_trace = trace_dir / "pytest-temp.json"
    normal_trace.write_text(
        json.dumps({"success": True, "result": {"image_path": r"D:\agent-gui-runtime\artifacts\screenshots\capture.png"}}),
        encoding="utf-8",
    )
    test_trace.write_text(
        json.dumps({"success": True, "result": {"image_path": r"C:\Users\me\AppData\Local\Temp\pytest-of-me\case\capture.png"}}),
        encoding="utf-8",
    )

    response = client.get("/panel/list_traces")

    assert response.status_code == 200
    names = [item["name"] for item in response.json()["data"]["traces"]]
    assert names == ["normal.json"]

    with_tests = client.get("/panel/list_traces", params={"include_tests": "true"})
    names_with_tests = {item["name"] for item in with_tests.json()["data"]["traces"]}
    assert names_with_tests == {"normal.json", "pytest-temp.json"}


def test_web_panel_trace_list_filters_by_agent_mode(tmp_path, monkeypatch) -> None:
    client = TestClient(app)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    vision_dir = tmp_path / "logs" / "traces" / "vision"
    action_dir = tmp_path / "logs" / "traces" / "actions"
    vision_dir.mkdir(parents=True)
    action_dir.mkdir(parents=True)
    learn_trace = vision_dir / "20260615-010000-000000__learn-mode-fast-observe__demo.json"
    execute_trace = action_dir / "20260615-010001-000000__execute-mode-plan-preview__demo.json"
    learn_trace.write_text(
        json.dumps({"success": True, "result": {"contract_version": "screen_observation_v1", "agent_mode": "learn"}}),
        encoding="utf-8",
    )
    execute_trace.write_text(
        json.dumps({"success": True, "result": {"contract_version": "execute_recognition_plan_v1", "agent_mode": "execute"}}),
        encoding="utf-8",
    )

    learn_response = client.get("/panel/list_traces", params={"mode": "learn"})
    execute_response = client.get("/panel/list_traces", params={"mode": "execute"})

    learn_items = learn_response.json()["data"]["traces"]
    execute_items = execute_response.json()["data"]["traces"]
    assert [item["name"] for item in learn_items] == [learn_trace.name]
    assert learn_items[0]["operation"] == "learn-mode-fast-observe"
    assert learn_items[0]["agent_mode"] == "learn"
    assert [item["name"] for item in execute_items] == [execute_trace.name]
    assert execute_items[0]["operation"] == "execute-mode-plan-preview"
    assert execute_items[0]["agent_mode"] == "execute"


def test_web_panel_renders_manual_candidate_box() -> None:
    client = TestClient(app)
    png_1x1 = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="
    )
    upload = client.post(
        "/panel/upload_image",
        json={
            "filename": "manual-source.png",
            "content_base64": base64.b64encode(png_1x1).decode("ascii"),
            "content_type": "image/png",
        },
    )
    image_path = upload.json()["data"]["image_path"]

    response = client.post(
        "/panel/manual_box",
        json={"image_path": image_path, "x": 0, "y": 0, "width": 1, "height": 1, "label": "target"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["manual_overlay_path"].endswith(".png")
    assert body["data"]["bbox"] == {"x": 0, "y": 0, "w": 1, "h": 1}

    served = client.get("/panel/file", params={"path": body["data"]["manual_overlay_path"]})

    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/png")


def test_web_panel_applies_model_profile_to_temp_configs(tmp_path, monkeypatch) -> None:
    client = TestClient(app)
    vision_config = tmp_path / "vision.json"
    panel_config = tmp_path / "settings_panel.json"
    monkeypatch.setattr(panel_api, "VISION_CONFIG_PATH", vision_config)
    monkeypatch.setattr(panel_api, "PANEL_CONFIG_PATH", panel_config)
    monkeypatch.setattr(
        panel_api,
        "load_model_profiles",
        lambda: [
            {
                "profile_id": "demo_observe",
                "label": "Demo Observe",
                "model_name": "demo.gguf",
                "endpoint": "http://127.0.0.1:1240/v1/chat/completions",
                "runtime": "llama_cpp",
                "output_contract": "vision_regions_v1",
                "start_script": "scripts/start.ps1",
                "stop_script": "scripts/stop.ps1",
            }
        ],
    )

    response = client.post(
        "/panel/apply_model_profile",
        json={
            "stage": "observe",
            "profile_id": "demo_observe",
            "timeout_seconds": 321,
            "language": "zh-CN",
            "observe_prompt": "observe rules",
            "locate_prompt": "locate rules",
        },
    )

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert "demo.gguf" in vision_config.read_text(encoding="utf-8")
    saved_vision = json.loads(vision_config.read_text(encoding="utf-8"))
    assert saved_vision["vision"]["local_understanding"]["output_contract"] == "vision_regions_v1"
    assert saved_vision["vision"]["local_understanding"]["runtime"] == "llama_cpp"
    assert "Demo Observe" in panel_config.read_text(encoding="utf-8")


def test_web_panel_model_test_writes_model_io_trace(monkeypatch) -> None:
    client = TestClient(app)

    class FakeHTTPResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "model says ok"}}]}).encode("utf-8")

    monkeypatch.setattr(
        panel_api,
        "load_model_profiles",
        lambda: [
            {
                "profile_id": "demo_observe",
                "model_name": "demo-model",
                "endpoint": "http://127.0.0.1:1240/v1",
            }
        ],
    )
    monkeypatch.setattr(panel_api.urllib.request, "urlopen", lambda request, timeout: FakeHTTPResponse())

    response = client.post(
        "/panel/model_test",
        json={
            "profile_id": "demo_observe",
            "stage": "observe",
            "prompt": "read the screen",
            "max_tokens": 64,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["model_io"]["contract_version"] == "model_io_trace_v1"
    assert data["model_io"]["attempts"][0]["model_io"]["input"]["prompt"] == "read the screen"
    assert data["model_io"]["attempts"][0]["model_io"]["output"]["raw_text"] == "model says ok"
    trace = json.loads(Path(data["trace_path"]).read_text(encoding="utf-8"))
    assert trace["model_io"]["provider"] == "panel_model_test"


def test_web_panel_inspects_trace_result_by_stage(tmp_path) -> None:
    client = TestClient(app)
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(
        json.dumps(
            {
                "success": True,
                "request": {"goal": "click start", "app_name": "demo", "provider_mode": "local"},
                "result": {
                    "contract_version": "recognition_plan_v1",
                    "image_path": "artifacts/capture.png",
                    "parse_result": {
                        "ocr_result": {"matches": [{"text": "Start"}], "metadata": {}},
                        "vision_regions": {"screen_summary": "demo page"},
                    },
                    "candidate_result": {
                        "summary": {"returned_count": 1, "has_recommendation": True},
                        "candidates": [{"label": "Start", "element": {"bbox": {"x": 10, "y": 20, "w": 30, "h": 40}}}],
                    },
                    "pre_click_decision": {
                        "allowed": False,
                        "reasons": ["no_candidate_passed_pre_click_checks"],
                        "summary": {"candidate_count": 1, "allowed_candidate_count": 0},
                        "candidate_decisions": [
                            {
                                "candidate_id": "candidate_start",
                                "allowed": False,
                                "click_point": {"x": 25, "y": 40},
                                "reasons": ["interaction_policy_blocked", "precision_text_target_requires_confirmation"],
                            }
                        ],
                    },
                    "execution_path": {"vision_provider_used": "dummy", "action_executed": False},
                    "timings": {"total_ms": 12, "steps": [{"name": "ocr", "elapsed_ms": 4}]},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = client.get("/panel/inspect_trace", params={"path": str(trace_path)})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["ocr_count"] == 1
    assert data["candidates"] == 1
    assert data["gate_allowed"] is False
    assert "no_candidate_passed_pre_click_checks" in data["gate_reason"]
    assert "interaction_policy_blocked" in data["gate_reason"]
    assert [stage["id"] for stage in data["flow_stages"]] == [
        "goal",
        "capture",
        "ocr",
        "vision",
        "candidates",
        "gate",
        "click",
        "timings",
    ]
    assert data["flow_stages"][2]["raw"]["matches"][0]["text"] == "Start"
    assert data["sections"]["candidates"]["image_path"] == "artifacts/capture.png"
    assert data["sections"]["gate"]["image_path"] == "artifacts/capture.png"


def test_web_panel_inspects_visual_asset_recall_stage(tmp_path) -> None:
    client = TestClient(app)
    trace_path = tmp_path / "visual-asset-trace.json"
    trace_path.write_text(
        json.dumps(
            {
                "success": True,
                "request": {"goal": "click quick apply", "app_name": "seek", "provider_mode": "local_grounding"},
                "result": {
                    "contract_version": "recognition_plan_v1",
                    "image_path": "artifacts/capture.png",
                    "visual_asset_recall": {
                        "contract_version": "visual_asset_recall_v1",
                        "status": "matched",
                        "matched_count": 1,
                        "fast_lane_allowed": True,
                        "selected_asset_id": "seek.quick_apply.primary",
                        "matches": [
                            {
                                "asset_id": "seek.quick_apply.primary",
                                "label": "Quick apply",
                                "semantic_action": "open_apply_flow",
                                "matched": True,
                                "match_score": 0.99,
                                "elapsed_ms": 12.3,
                                "template_path": "artifacts/visual-assets/quick-apply.png",
                                "current_roi_ref": "artifacts/visual-assets/current-roi.png",
                                "current_match_ref": "artifacts/visual-assets/current-match.png",
                                "bbox": {"x": 620, "y": 210, "w": 150, "h": 46},
                                "click_point": {"x": 695, "y": 233},
                            }
                        ],
                    },
                    "candidate_result": {
                        "summary": {
                            "returned_count": 1,
                            "has_recommendation": True,
                            "seeded_candidate_selected": True,
                        },
                        "candidates": [],
                    },
                    "pre_click_decision": {
                        "allowed": True,
                        "selected_click_point": {"x": 695, "y": 233},
                        "reasons": ["pre_click_candidate_allowed"],
                    },
                    "execution_path": {"visual_asset_fast_lane_used": True, "action_executed": False},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = client.get("/panel/inspect_trace", params={"path": str(trace_path)})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    data = body["data"]
    assert data["visual_asset_recall_status"] == "matched"
    assert data["visual_asset_fast_lane_used"] is True
    assert data["visual_asset_matched_count"] == 1
    stage_by_id = {stage["id"]: stage for stage in data["flow_stages"]}
    visual_stage = stage_by_id["visual_asset_recall"]
    assert visual_stage["label"] == "Visual Assets"
    assert "1 matched" in visual_stage["value"]
    assert "fast lane" in visual_stage["value"]
    assert "Visual asset recall matched: 1 matched asset(s); fast lane" == visual_stage["summary"]
    assert visual_stage["raw"]["matches"][0]["template_path"].endswith("quick-apply.png")
    assert visual_stage["raw"]["matches"][0]["current_roi_ref"].endswith("current-roi.png")
    assert visual_stage["raw"]["matches"][0]["current_match_ref"].endswith("current-match.png")


def test_web_panel_inspects_locate_trace_nested_plan_ocr_and_visuals(tmp_path) -> None:
    client = TestClient(app)
    trace_path = tmp_path / "locate-trace.json"
    image_path = str(tmp_path / "capture.png")
    trace_path.write_text(
        json.dumps(
            {
                "success": True,
                "request": {"goal": "click news", "app_name": "steam", "provider_mode": "local_grounding"},
                "result": {
                    "contract_version": "target_location_v1",
                    "image_path": image_path,
                    "located_point": {"x": 334, "y": 94},
                    "located_bbox": {"x": 300, "y": 80, "w": 60, "h": 30},
                    "path_map_review": {
                        "contract_version": "path_map_review_v1",
                        "status": "ready",
                        "summary": {"addition_count": 1, "removal_count": 1},
                        "additions": [{"candidate_id": "locate_review_news", "label": "News"}],
                        "removals": [{"candidate_id": "old_news", "label": "News"}],
                    },
                    "recognition_plan": {
                        "image_path": image_path,
                        "path_graph_recall": {
                            "contract_version": "path_graph_recall_v1",
                            "status": "ready",
                            "state_match": {"status": "matched", "state_id": "state_news"},
                            "summary": {"candidate_count": 3, "recalled_count": 1},
                            "candidates": [{"candidate_id": "news_card", "label": "News"}],
                        },
                        "parse_result": {
                            "ocr_result": {"matches": [{"text": "News"}], "metadata": {"match_count": 1}},
                            "vision_regions": {"regions": [{"label": "news card"}]},
                        },
                        "candidate_result": {
                            "summary": {"returned_count": 1, "has_recommendation": True},
                            "candidates": [
                                {
                                    "candidate_id": "candidate_news",
                                    "element": {"bbox": {"x": 300, "y": 80, "w": 60, "h": 30}},
                                }
                            ],
                        },
                        "pre_click_decision": {
                            "allowed": False,
                            "reasons": ["no_candidate_passed_pre_click_checks"],
                            "candidate_decisions": [
                                {"candidate_id": "candidate_news", "allowed": False, "reasons": ["interaction_policy_blocked"]}
                            ],
                        },
                    },
                    "execution_path": {"vision_provider_used": "dummy", "action_executed": False},
                    "timings": {"total_ms": 10, "steps": []},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = client.get("/panel/inspect_trace", params={"path": str(trace_path)})

    assert response.status_code == 200
    data = response.json()["data"]
    stage_ids = [stage["id"] for stage in data["flow_stages"]]
    assert "ocr" in stage_ids
    assert "path_recall" in stage_ids
    assert "path_review" in stage_ids
    assert data["sections"]["ocr"]["image_path"] == image_path
    assert data["sections"]["ocr"]["matches"][0]["text"] == "News"
    assert data["sections"]["gate"]["candidate_result"]["candidates"][0]["candidate_id"] == "candidate_news"
    assert data["sections"]["target"]["image_path"] == image_path
    path_review = next(stage for stage in data["flow_stages"] if stage["id"] == "path_review")
    assert path_review["value"] == "+1 / -1"
    assert path_review["raw"]["additions"][0]["candidate_id"] == "locate_review_news"
    path_recall = next(stage for stage in data["flow_stages"] if stage["id"] == "path_recall")
    assert path_recall["value"] == "1 recalled, state_news"
    assert path_recall["raw"]["candidates"][0]["candidate_id"] == "news_card"


def test_web_panel_inspects_archived_overlay_trace(tmp_path) -> None:
    client = TestClient(app)
    trace_path = tmp_path / "overlay.json"
    trace_path.write_text(
        json.dumps(
            {
                "success": True,
                "request": {"trace_path": "recognition-plan.json"},
                "result": {
                    "trace_path": "recognition-plan.json",
                    "image_path": "capture.png",
                    "output_path": "overlay.png",
                    "candidate_count": 2,
                    "decision_count": 2,
                    "selected_candidate_id": "candidate_start",
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8-sig",
    )

    response = client.get("/panel/inspect_trace", params={"path": str(trace_path)})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["contract"] == "recognition_overlay_trace"
    assert data["total_time"] == ""
    assert data["provider"] == ""
    assert [stage["id"] for stage in data["flow_stages"]] == ["goal", "capture", "overlay"]
    assert data["flow_stages"][2]["value"] == "2 candidates, 2 decisions"
    assert data["flow_stages"][2]["raw"]["output_path"] == "overlay.png"


def test_web_panel_inspects_archived_layer_trace(tmp_path) -> None:
    client = TestClient(app)
    trace_path = tmp_path / "layer.json"
    trace_path.write_text(
        json.dumps(
            {
                "success": True,
                "request": {"app_name": "demo"},
                "result": {
                    "contract_version": "vision_layer_trace_v1",
                    "image_path": "capture.png",
                    "final_ok": True,
                    "layers": [
                        {"layer": "input_image", "ok": True, "summary": {"image_exists": True}},
                        {"layer": "vision_provider_raw", "ok": False, "summary": {"provider": "dummy"}},
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = client.get("/panel/inspect_trace", params={"path": str(trace_path)})

    assert response.status_code == 200
    stages = response.json()["data"]["flow_stages"]
    assert [stage["label"] for stage in stages] == ["input_image", "vision_provider_raw"]
    assert stages[0]["status"] == "done"
    assert stages[1]["status"] == "error"


def test_web_panel_inspects_screen_reading_trace(tmp_path) -> None:
    client = TestClient(app)
    trace_path = tmp_path / "screen-reading.json"
    trace_path.write_text(
        json.dumps(
            {
                "success": True,
                "request": {"task": "analyze_ui", "app_name": "demo"},
                "result": {
                    "contract_version": "screen_reading_v1",
                    "image_path": "capture.png",
                    "app_name": "demo",
                    "screen_summary": "dummy page",
                    "state_guess": "dummy_state",
                    "texts": [{"text": "Start"}],
                    "ui": {"summary": {"element_count": 1}, "elements": [{"label": "Start"}]},
                    "screen_inventory": {
                        "contract_version": "screen_inventory_v1",
                        "available_actions": [
                            {"id": "action_start", "label": "Start", "role": "button", "point": {"x": 40, "y": 50}},
                            {"id": "action_search", "label": "Search", "role": "input", "point": {"x": 140, "y": 30}},
                        ],
                        "page_elements": [{"id": "text_title", "text": "Demo title"}],
                        "cards": [{"id": "card_1", "title": "Demo card", "child_ids": ["action_start"]}],
                        "summary": {
                            "available_action_count": 2,
                            "page_element_count": 1,
                            "card_count": 1,
                        },
                        "quality": {"coordinate_coverage": 1.0},
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = client.get("/panel/inspect_trace", params={"path": str(trace_path)})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["contract"] == "screen_reading_v1"
    assert data["screen_summary"] == "dummy page"
    stage_ids = [stage["id"] for stage in data["flow_stages"]]
    assert "screen" in stage_ids
    assert "screen_inventory" in stage_ids
    assert "click" not in stage_ids
    inventory_stage = next(stage for stage in data["flow_stages"] if stage["id"] == "screen_inventory")
    assert inventory_stage["value"] == "2 actions, 1 text, 1 cards"
    assert "coordinate coverage: 1.00" in inventory_stage["summary"]
    assert data["sections"]["screen_inventory"]["available_actions"][0]["label"] == "Start"


def test_web_panel_inspects_observe_trace_path_map(tmp_path) -> None:
    client = TestClient(app)
    trace_path = tmp_path / "observe-mousetester.json"
    image_path = str(tmp_path / "mousetester.png")
    trace_path.write_text(
        json.dumps(
            {
                "success": True,
                "request": {"task": "observe_screen", "app_name": "MouseTesterWeb", "provider_mode": "local_understanding"},
                "result": {
                    "contract_version": "screen_observation_v1",
                    "image_path": image_path,
                    "app_name": "MouseTesterWeb",
                    "screen_summary": "MouseTester main page with click test cards.",
                    "state_guess": "MouseTester main page",
                    "screen_reading": {
                        "screen_summary": "MouseTester main page with click test cards.",
                        "state_guess": "MouseTester main page",
                    },
                    "screen_map": {
                        "contract_version": "screen_map_v1",
                        "state_id": "state_mouse_123",
                        "app_name": "MouseTesterWeb",
                        "image_path": image_path,
                        "state_hint": "MouseTester main page",
                        "summary": {
                            "candidate_count": 2,
                            "safe_candidate_count": 2,
                            "section_count": 2,
                            "screen_summary": "MouseTester main page with click test cards.",
                        },
                        "sections": [
                            {
                                "contract_version": "screen_map_section_v1",
                                "section_id": "page_header",
                                "label": "Top navigation",
                                "role": "navigation",
                                "bbox": {"x": 0, "y": 80, "w": 1600, "h": 120},
                            },
                            {
                                "contract_version": "screen_map_section_v1",
                                "section_id": "main_content",
                                "label": "Main content",
                                "role": "content",
                                "bbox": {"x": 0, "y": 260, "w": 1600, "h": 500},
                            },
                        ],
                        "candidates": [
                            {
                                "contract_version": "screen_map_candidate_v1",
                                "candidate_id": "element_click_here",
                                "label": "点击此处测试",
                                "role": "button",
                                "goal_hint": "open or activate 点击此处测试",
                                "expected_effect": "click counter starts",
                                "risk_class": "safe_click_allowed",
                                "section_id": "main_content",
                                "bbox": {"x": 676, "y": 323, "width": 74, "height": 42},
                                "click_point": {"x": 713, "y": 344},
                                "confidence": 0.98,
                            },
                            {
                                "contract_version": "screen_map_candidate_v1",
                                "candidate_id": "element_cps",
                                "label": "CPS 测试",
                                "role": "card",
                                "goal_hint": "open or activate CPS 测试",
                                "expected_effect": "CPS card is selected",
                                "risk_class": "safe_dry_run_only",
                                "bbox": {"x": 500, "y": 460, "width": 130, "height": 200},
                                "click_point": {"x": 565, "y": 560},
                                "confidence": 0.94,
                            },
                        ],
                    },
                    "path_graph_deep_review": {
                        "contract_version": "path_graph_deep_review_v1",
                        "status": "ready",
                        "state_id": "state_mouse_123",
                        "summary": {
                            "input_candidate_count": 3,
                            "output_candidate_count": 2,
                            "duplicate_count": 1,
                            "missing_text_addition_count": 0,
                        },
                        "candidate_decisions": [
                            {"candidate_id": "element_click_here", "action": "keep"},
                            {"candidate_id": "duplicate_click_here", "action": "remove"},
                        ],
                    },
                    "path_graph_delta": {
                        "contract_version": "path_graph_delta_v1",
                        "status": "ready",
                        "additions": [],
                        "removals": [{"candidate_id": "duplicate_click_here"}],
                        "updates": [{"field": "screen_map.summary"}],
                    },
                    "element_memory_init_plan": {
                        "contract_version": "element_memory_init_plan_v1",
                        "status": "planned",
                        "entry_count": 2,
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = client.get("/panel/inspect_trace", params={"path": str(trace_path)})

    assert response.status_code == 200
    data = response.json()["data"]
    stage_ids = [stage["id"] for stage in data["flow_stages"]]
    assert "path_map" in stage_ids
    assert "path_deep" in stage_ids
    path_stage = next(stage for stage in data["flow_stages"] if stage["id"] == "path_map")
    assert path_stage["value"] == "2 candidates, state_mouse_123"
    assert "Path map candidates: 2" in path_stage["summary"]
    assert path_stage["raw"]["sections"][1]["section_id"] == "main_content"
    assert path_stage["raw"]["candidates"][0]["section_id"] == "main_content"
    assert path_stage["raw"]["candidates"][0]["label"] == "点击此处测试"
    assert path_stage["raw"]["candidates"][0]["bbox"]["x"] == 676
    deep_stage = next(stage for stage in data["flow_stages"] if stage["id"] == "path_deep")
    assert deep_stage["value"] == "+0 / -1"
    assert "Path deep ready" in deep_stage["summary"]
    assert deep_stage["raw"]["path_graph_delta"]["removals"][0]["candidate_id"] == "duplicate_click_here"


def test_web_panel_inspects_execute_memory_and_fallback_stages(tmp_path) -> None:
    client = TestClient(app)
    trace_path = tmp_path / "execute-trace.json"
    trace_path.write_text(
        json.dumps(
            {
                "success": False,
                "request": {"goal": "Target test", "app_name": "demo"},
                "result": {
                    "contract_version": "execute_recognition_plan_v1",
                    "goal": "Target test",
                    "image_path": "capture.png",
                    "recognition_plan": {
                        "pre_click_decision": {"allowed": False, "reasons": ["missing_local_ocr_text"]},
                        "candidate_result": {"summary": {"returned_count": 1}},
                    },
                    "execution_path": {"action_executed": False},
                    "fallback_plan": {
                        "contract_version": "execute_fallback_plan_v1",
                        "status": "planned",
                        "failure_reason": "pre_click_rejected",
                        "steps": [{"name": "local_rescan_top_candidates"}],
                    },
                    "recognition_plan_overlay": {
                        "trace_path": "recognition-plan.json",
                        "image_path": "capture.png",
                        "output_path": "overlay.png",
                        "candidate_count": 2,
                        "decision_count": 1,
                        "selected_candidate_id": "candidate_1",
                    },
                    "agent_execution_guidance": {
                        "contract_version": "agent_execute_guidance_v1",
                        "status": "blocked",
                        "next_action": "recover_with_fallback_plan",
                    },
                    "element_memory_writeback": {
                        "contract_version": "execute_transition_memory_v1",
                        "status": "written",
                        "transition_id": "exec-1234567890",
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = client.get("/panel/inspect_trace", params={"path": str(trace_path)})

    assert response.status_code == 200
    data = response.json()["data"]
    stage_ids = [stage["id"] for stage in data["flow_stages"]]
    assert "memory" in stage_ids
    assert "fallback" in stage_ids
    assert "coordinate_preview" in stage_ids
    assert "agent_guidance" in stage_ids
    memory = next(stage for stage in data["flow_stages"] if stage["id"] == "memory")
    fallback = next(stage for stage in data["flow_stages"] if stage["id"] == "fallback")
    preview = next(stage for stage in data["flow_stages"] if stage["id"] == "coordinate_preview")
    guidance = next(stage for stage in data["flow_stages"] if stage["id"] == "agent_guidance")
    assert memory["value"] == "written, exec-1234567"
    assert "ElementMemory writeback written" in memory["summary"]
    assert fallback["value"] == "pre_click_rejected, 1 step(s)"
    assert fallback["raw"]["steps"][0]["name"] == "local_rescan_top_candidates"
    assert preview["value"] == "2 candidates, 1 decisions, candidate_1"
    assert "overlay.png" in preview["summary"]
    assert guidance["value"] == "blocked, recover_with_fallback_plan"


def test_web_panel_inspects_learn_locate_coordinate_overlay_stage(tmp_path) -> None:
    client = TestClient(app)
    image_path = tmp_path / "screen.png"
    overlay_path = tmp_path / "learn-targets.png"
    image_path.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="))
    overlay_path.write_bytes(image_path.read_bytes())
    trace_path = tmp_path / "learn-locate-trace.json"
    target = {
        "candidate_id": "search_box",
        "label": "Search box",
        "role": "text_input",
        "bbox": {"x": 10, "y": 20, "w": 120, "h": 32},
        "click_point": {"x": 70, "y": 36},
        "coordinate_validation": {
            "contract_version": "learn_target_coordinate_validation_v1",
            "status": "valid",
            "click_point_inside_bbox": True,
        },
    }
    trace_path.write_text(
        json.dumps(
            {
                "success": True,
                "request": {"goal": "learn all visible controls", "app_name": "google"},
                "result": {
                    "contract_version": "target_location_v1",
                    "agent_mode": "learn",
                    "learn_depth": "deep",
                    "goal": "learn all visible controls",
                    "image_path": str(image_path),
                    "location_status": "learn_all_targets_ready",
                    "coordinate_overlay_path": str(overlay_path),
                    "learn_all_targets": {
                        "contract_version": "learn_all_target_locations_v1",
                        "status": "ready",
                        "target_count": 1,
                        "validated_count": 1,
                        "invalid_count": 0,
                        "overlay_path": str(overlay_path),
                        "targets": [target],
                    },
                    "path_map_review": {
                        "contract_version": "path_map_review_v1",
                        "status": "learn_all_targets",
                        "summary": {
                            "addition_count": 1,
                            "validated_count": 1,
                            "invalid_count": 0,
                            "coordinate_overlay_path": str(overlay_path),
                            "removal_count": 0,
                            "kept_count": 0,
                        },
                        "additions": [target],
                        "removals": [],
                        "kept": [],
                    },
                    "execution_path": {"action_executed": False, "learn_all_targets_used": True},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = client.get("/panel/inspect_trace", params={"path": str(trace_path)})

    assert response.status_code == 200
    data = response.json()["data"]
    path_review = next(stage for stage in data["flow_stages"] if stage["id"] == "path_review")
    assert path_review["value"] == "+1 / -0"
    assert path_review["raw"]["coordinate_overlay_path"] == str(overlay_path)
    assert path_review["raw"]["learn_all_targets"]["targets"][0]["coordinate_validation"]["status"] == "valid"


def test_web_panel_inspects_failed_screen_reading_trace(tmp_path) -> None:
    client = TestClient(app)
    trace_path = tmp_path / "failed-screen-reading.json"
    image_path = tmp_path / "capture.png"
    image_path.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII="))
    trace_path.write_text(
        json.dumps(
            {
                "success": False,
                "request": {
                    "image_path": str(image_path),
                    "task": "observe_screen",
                    "goal": "understand the current interface",
                    "provider_mode": "local_understanding",
                },
                "error": "failed to reach local vision endpoint http://127.0.0.1:1240/v1/chat/completions",
                "model_io": {
                    "contract_version": "model_io_trace_v1",
                    "status": "failed",
                    "provider": "local",
                    "model_name": "qwen",
                    "attempt_count": 1,
                    "attempts": [
                        {
                            "status": "failed",
                            "model_io": {
                                "contract_version": "model_io_attempt_v1",
                                "input": {"prompt": "read the current interface"},
                                "output": {"raw_text": "{bad json"},
                            },
                        }
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = client.get("/panel/inspect_trace", params={"path": str(trace_path)})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["contract"] == "observe_screen"
    assert data["provider"] == "local_understanding"
    stage_ids = [stage["id"] for stage in data["flow_stages"]]
    assert stage_ids == ["goal", "capture", "model_io", "error"]
    assert data["flow_stages"][1]["raw"]["image_path"] == str(image_path)
    model_io = next(stage for stage in data["flow_stages"] if stage["id"] == "model_io")
    assert model_io["value"] == "failed, 1 attempt(s), local"
    assert model_io["raw"]["attempts"][0]["model_io"]["output"]["raw_text"] == "{bad json"
    assert "failed to reach local vision endpoint" in data["flow_stages"][-1]["summary"]


def test_panel_path_detail_keeps_interface_inspector_and_seek_layout() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8")
    panel_html = Path("app/web_panel/index.html").read_text(encoding="utf-8")

    assert "path-detail-interface-workbench" in panel_js
    assert "path-detail-interface-inspector" in panel_js
    assert "bindPathDetailInterfaceControls" in panel_js
    assert "[data-path-detail-inspect], [data-interface-inspect]" in panel_js
    assert "interfaceKnownSeekRegionLayoutHtml" in panel_js
    assert "interfaceAssetShouldShowThumb" in panel_js
    assert "runtimeNodeOperationItemsHtml" in panel_js
    assert "const operationItems = runtimeNodeOperationItemsHtml(node)" not in panel_js
    assert "runtimeNodeRegionWorkflowItemsHtml" not in panel_js
    assert "const regionOperationItems = runtimeNodeRegionWorkflowItemsHtml(node)" not in panel_js
    assert "interface-inspector-region-action-group" in panel_js
    assert "runtimePathGraphView.currentStateId = nodeId" in panel_js
    assert "state: nodeId" in panel_js
    assert "runtime-architecture-strip" in panel_html
    assert "runtime-node-architecture" in panel_js
    assert "Agentic Loop-first" in panel_js
    assert "runtimeArchitectureProfilePath" in panel_js
    assert "fetchRuntimeAppProfile" in panel_js
    assert "fetchRuntimeOperationSkills" in panel_js
    assert "fetchRuntimeGateContracts" in panel_js
    assert "/runtime/operation_skills" in panel_js
    assert "/runtime/gate_contracts" in panel_js
    assert "operation_skill_catalog" in panel_js
    assert "gate_contract_catalog" in panel_js
    assert "operation_layer_skills" in panel_js
    assert "gate_layer_contracts" in panel_js
    assert "fetchRuntimeAgentPrompt" in panel_js
    assert "fetchRuntimeAgentPromptVersions" in panel_js
    assert "fetchRuntimeAgentPromptVersion" in panel_js
    assert "fetchRuntimeAgentPromptDiff" in panel_js
    assert "saveRuntimeAgentPromptVersion" in panel_js
    assert "rollbackRuntimeAgentPromptVersion" in panel_js
    assert "loadReplayAgentPrompt" in panel_js
    assert "loadReplayAgentPromptVersions" in panel_js
    assert "loadSelectedReplayAgentPromptVersion" in panel_js
    assert "diffReplayAgentPromptVersions" in panel_js
    assert "saveReplayAgentPromptVersion" in panel_js
    assert "rollbackReplayAgentPromptVersion" in panel_js
    assert "/runtime/agent_prompts/" in panel_js
    assert "/versions/" in panel_js
    assert "/diff?" in panel_js
    assert "/rollback" in panel_js
    assert "agent-prompt-editor" in panel_html
    assert "agent-prompt-diff" in panel_html
    assert "agent-prompt-policy" in panel_js
    assert "loadReplayAppProfile" in panel_js
    assert "renderReplayAppProfile" in panel_js
    assert "/runtime/app_profiles/" in panel_js
    assert "app-profile-policy" in panel_js
    assert "DEFAULT_SEEK_APP_PROFILE_PATH" in panel_js
    assert "PathGraph 是学习出来的 workflow 资产" in panel_js
    assert "导航资产，不是动作授权" in panel_js
    assert "runtime-node-workflow" not in panel_js
    assert "graph.action_templates" in panel_js
    assert "ensureReplayInterfaceMapForRuntimeGraph" in panel_js
    assert "inferInterfaceMapPresetForGraph" in panel_js
    assert "interfaceWorkflowActionsForRegion" in panel_js
    assert "interfaceInspectorStateRegionsHtml" in panel_js
    assert "interfaceInspectorStateWorkflowHtml" in panel_js
    assert "interfaceInspectorRegionWorkflowHtml" in panel_js
    assert "interface-inspector-page-regions" in panel_js
    assert "interface-inspector-workflow" in panel_js
    assert "interfacePathNodeIdForStateRef" in panel_js
    assert "showNavNodeDetail(pathNodeId, null, { preserveInterfaceSelection: true })" in panel_js
    assert "interfaceKnownSeekApplicationRegionLayoutHtml" in panel_js
    assert "interfaceKnownRegionWorkflowActions" in panel_js
    assert "interfaceRegionSummaryText" in panel_js
    assert "Workflow / 可调用 skill" in panel_js
    assert "需确认" in panel_js
    assert "操作已按页面节点和具体区域拆分" in panel_js
    assert "页面摘要" in panel_js
    assert "interface-region-ops" not in panel_js
    assert "path-screen-region-hints" not in panel_js
    assert "interfaceRegionOperationHints" not in panel_js
    assert "node.runtimeGraphNode ? \"\" : clickableControls" in panel_js
    assert "node.runtimeGraphNode ? \"\" : possibleEntries" in panel_js
    assert "showNavNodeDetail(firstState)" in panel_js
    assert "interfaceNodeTransitionsHtml(transitions)" not in panel_js
    assert "${stateRegionsHtml}\n    ${stateWorkflowHtml}\n    ${regionWorkflowHtml}\n    ${regionContentsHtml}\n    ${interfaceInspectorEditorHtml(selected, regionIds)}" in panel_js
    assert "application_documents" in panel_js
    assert "application_review_step" in panel_js
    assert "detect_application_step" in panel_js
    assert "skill.read_application_progress" in panel_js
    assert "fill_employer_questions" in panel_js
    assert "final_submit" in panel_js
    assert "interface-crop-source-preview" in panel_js
    assert "interface-crop-selector-modal" in panel_js
    assert "writeInterfaceCropValues" in panel_js
    assert "image.naturalWidth / Math.max(1, rect.width)" in panel_js
    assert "interface-crop-disabled" in panel_js
    assert "interface-inspector-contents" in panel_js
    assert "replay_region_contents" in panel_js
    assert "<strong>可用操作</strong>" not in panel_js
    assert "scroll region" in panel_js
    assert "visual evidence" in panel_js
    assert "interfaceDynamicAreaSummary" in panel_js
    assert "这里会出现岗位卡片" in panel_js
    assert "最终提交必须阻断" in panel_js
    assert "top_search_area" in panel_js
    assert "results_list" in panel_js
    assert "job_detail" in panel_js
    assert "runtime-node-edges" not in panel_js


def test_panel_translation_keys_stay_bilingual() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8")
    panel_html = Path("app/web_panel/index.html").read_text(encoding="utf-8")
    zh_start = panel_js.index('  "zh-CN": {')
    en_start = panel_js.index('  "en-US": {')
    end = panel_js.index("};", panel_js.index("const translations"))
    key_pattern = re.compile(r"^\s*([A-Za-z0-9_]+):", re.M)
    zh_keys = set(key_pattern.findall(panel_js[zh_start:en_start]))
    en_keys = set(key_pattern.findall(panel_js[en_start:end]))
    html_keys = set(re.findall(r'data-i18n="([^"]+)"', panel_html))

    assert zh_keys == en_keys
    assert html_keys <= zh_keys
    assert "replay_screen_regions" in zh_keys
    assert "replay_workflow_skill" in zh_keys
    assert "replay_region_contents" in zh_keys
    assert "interface_calibration_report_path" in zh_keys
    assert "load_interface_calibration" in zh_keys
    assert "use_current_app_map" in zh_keys
    assert "runtime_architecture_title" in zh_keys
    assert "runtime_architecture_pathgraph_hint" in zh_keys
    assert "app_profile_id" in zh_keys
    assert "load_app_profile" in zh_keys
    assert "app_profile_summary" in zh_keys
    assert "agent_prompt_id" in zh_keys
    assert "load_agent_prompt" in zh_keys
    assert "save_agent_prompt_version" in zh_keys
    assert "agent_prompt_summary" in zh_keys
    assert "generate_learning_draft" not in zh_keys
    assert "generate_learning_generalization" not in zh_keys
    assert "learning_template_title" not in zh_keys
    assert "learning_output_title" not in zh_keys
    assert "learning_view_template" not in zh_keys
    assert "learning_view_draft" not in zh_keys
    assert "learning_draft_review" in zh_keys
    assert "learning_draft_review_save" in zh_keys
    assert "learning_draft_summary" in zh_keys
    assert "learning_draft_states" in zh_keys
    assert "learning_draft_regions" in zh_keys
    assert "learning_draft_actions" in zh_keys
    assert "learning_draft_blockers" in zh_keys
    assert "learning_draft_verification_rules" in zh_keys
    assert "learning_draft_safety_status" in zh_keys
    assert "learning_draft_path_preview_title" in zh_keys
    assert "learning_draft_path_preview_hint" in zh_keys
    assert "learning_draft_not_executable" in zh_keys
    assert "learning_draft_node_detail" in zh_keys
    assert "learning_draft_related_regions" in zh_keys
    assert "learning_draft_related_actions" in zh_keys
    assert "learning_draft_no_path_nodes" in zh_keys
    assert "learning_draft_evidence_sources" in zh_keys
    assert "learning_review_empty" in zh_keys
    assert "replay_advanced_actions" in zh_keys
    assert "replay_advanced_actions_hint" in zh_keys
    assert "learning_trial_capture" in zh_keys
    assert "learning_trial_run" in zh_keys
    assert "learning_trial_result_path" in zh_keys
    assert "template_subinterface" in zh_keys
    assert "learning_draft_subinterface" in zh_keys
    assert "learning_pathgraph_candidate_generate" in zh_keys
    assert "learning_pathgraph_candidate_path" in zh_keys
    assert "learning_pathgraph_validation_path" in zh_keys
    assert "learning_assisted_template_package_path" in zh_keys
    assert "learning_assisted_template_package_create" in zh_keys
    assert "learning_assisted_template_package_load" in zh_keys
    assert "learning_assisted_template_suggestions_create" in zh_keys
    assert "learning_assisted_template_suggestions" in zh_keys
    assert "learning_assisted_template_suggestion_apply" in zh_keys
    assert "learning_assisted_template_acceptance_simulation_apply" in zh_keys
    assert "learning_assisted_template_completeness" in zh_keys
    assert "learning_assisted_template_completeness_passed" in zh_keys
    assert "learning_assisted_template_completeness_blocked" in zh_keys
    assert "learning_assisted_template_asset_candidate_path" in zh_keys
    assert "learning_assisted_template_asset_candidate_create" in zh_keys
    assert "learning_assisted_template_graph_draft_path" in zh_keys
    assert "learning_assisted_template_graph_draft_create" in zh_keys
    assert "learning_assisted_template_checklist" in zh_keys
    assert "learning_assisted_template_empty" in zh_keys
    assert "learning_assisted_template_decisions_save" in zh_keys
    assert "learning_assisted_template_decisions_save_export" in zh_keys
    assert "learning_assisted_template_decisions_save_graph_preview" in zh_keys
    assert "learning_assisted_template_review_to_graph_diff" in zh_keys
    assert "learning_assisted_template_promotion_preflight_create" in zh_keys
    assert "learning_assisted_template_promotion_preflight" in zh_keys
    assert "learning_load_draft_graph" not in zh_keys
    assert "learning_show_interface_details" not in zh_keys
    assert "learning_output_seek_template" not in zh_keys
    assert "learning_output_navigation_graph" not in zh_keys
    assert "learning_output_interface_details" not in zh_keys
    assert "learning_output_interface_regions" not in zh_keys
    assert "learning_output_draft_actions" not in zh_keys
    assert "learning_draft_title" not in zh_keys
    assert "learning_site_validation" not in zh_keys
    assert "learning_overall_score" not in zh_keys
    assert "learning_generalization_title" not in zh_keys
    assert "learning_diff" not in zh_keys


def test_panel_removes_wrong_learning_draft_workbench() -> None:
    index_html = Path("app/web_panel/index.html").read_text(encoding="utf-8")
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8")
    panel_css = Path("app/web_panel/panel.css").read_text(encoding="utf-8")

    assert 'class="button-row replay-template-actions"' in index_html
    assert 'class="replay-action-disclosure"' in index_html
    assert 'class="button-row replay-template-advanced-actions"' in index_html
    assert 'class="button-row replay-learning-actions"' in index_html
    assert 'class="learn-replay-subnav"' in index_html
    assert 'data-learn-replay-panel="template"' in index_html
    assert 'data-learn-replay-panel="draft"' in index_html
    assert 'class="form-section-label wide-control"' in index_html
    assert 'class="form-section-label wide-control learning-studio-section-label"' in index_html
    assert 'data-i18n="template_replay_section"' in index_html
    assert 'data-i18n="learning_studio_section"' in index_html
    assert 'id="learningTrialResultPath"' in index_html
    assert 'id="learningTrialCaptureBtn"' in index_html
    assert 'id="learningTrialRunBtn"' in index_html
    assert 'id="learningPathGraphCandidatePath"' in index_html
    assert 'id="learningPathGraphValidationPath"' in index_html
    assert 'id="learningPathGraphCandidateBtn"' in index_html
    assert 'id="learningDraftFreshnessDemoCase"' in index_html
    assert 'id="learningDraftFreshnessDemoBtn"' in index_html
    assert 'value="freshness_checksum_mismatch"' in index_html
    assert 'id="learningTrialResultPath" value=""' in index_html
    assert 'id="learningDraftReviewSourcePath" value=""' in index_html
    assert 'id="learningDraftRecommendedLoadBtn"' in index_html
    assert 'id="learningPathGraphCandidatePath" value=""' in index_html
    assert 'id="learningPathGraphValidationPath" value=""' in index_html
    assert "trial_result_cae1c88703" not in index_html
    assert "new_site_python_org_20260702_after_similarity_fix" not in index_html
    assert 'class="learning-mode-switch"' not in index_html
    assert 'data-learning-view="template"' not in index_html
    assert 'data-learning-panel="draft"' not in index_html
    assert 'id="learningTemplatePanel"' not in index_html
    assert 'id="learningOutputPanel"' not in index_html
    assert 'id="learningDraftReviewPanel"' in index_html
    assert 'id="learningDraftReviewSummary"' in index_html
    assert 'id="learningDraftPathPreview"' in index_html
    assert 'id="learningDraftPathMap"' in index_html
    assert 'id="learningDraftPathDetail"' in index_html
    assert 'id="learningDetailObserveCandidatePath"' in index_html
    assert 'id="learningDetailObserveRequestSelect"' in index_html
    assert 'id="learningDetailObserveRequestId"' in index_html
    assert 'id="learningDetailObserveSourceSelect"' in index_html
    assert 'id="learningDetailObserveSourcePath"' in index_html
    assert 'id="learningDetailObserveSourcesBtn"' in index_html
    assert 'id="learningDetailObserveAttachBtn"' in index_html
    assert 'id="imageInspectorOverlay"' in index_html
    assert 'id="imageInspectorImage"' in index_html
    assert 'id="imageInspectorBox"' in index_html
    assert 'id="imageInspectorPoint"' in index_html
    assert 'id="imageInspectorFooter"' in index_html
    assert 'id="imageInspectorApplyBoxBtn"' in index_html
    assert "function renderLearningTemplateSummary" not in panel_js
    assert "function setLearningWorkbenchView" not in panel_js
    assert 'let currentLearnReplaySubview = "template";' in panel_js
    assert 'document.body.classList.toggle("learn-replay-draft-subview", draftActive);' in panel_js


def test_learning_draft_panel_renders_open_detail_transition_hints() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    panel_css = Path("app/web_panel/panel.css").read_text(encoding="utf-8-sig")
    panel_html = Path("app/web_panel/index.html").read_text(encoding="utf-8-sig")

    assert "function escapeAttr" in panel_js
    assert 'data-screen-understanding-overlay="${escapeAttr(fullOverlayPath)}"' in panel_js
    assert "learningDraftTransitionHintForAction" in panel_js
    assert "learn_open_detail_transition_hint_v1" in panel_js
    assert "learningDraftStateTransitions" in panel_js
    assert "renderLearningDraftDetailAttachments" in panel_js
    assert "renderLearningDraftPathGraphReadiness" in panel_js
    assert "pathgraphReadinessRunbook" in panel_js
    assert "pathgraphReadinessRunbookChecklist" in panel_js
    assert "pathgraphReadinessEvidenceRequirements" in panel_js
    assert "pathgraphReadinessPreflight" in panel_js
    assert "pathgraphReadinessDemo" in panel_js
    assert "pathgraphReadinessApprovalPacket" in panel_js
    assert "pathgraphReadinessApprovalPacketChecklist" in panel_js
    assert "pathgraphReadinessApprovalPacketEvidence" in panel_js
    assert "pathgraphReadinessCalibrationPreRun" in panel_js
    assert "pathgraphReadinessCalibrationPreRunChecklist" in panel_js
    assert "pathgraphReadinessCalibrationPreRunEvidence" in panel_js
    assert "pathgraphReadinessCalibrationPreRunModelSnapshot" in panel_js
    assert "createModelStartApprovalPacket" in panel_js
    assert "createCalibrationPreRunCheck" in panel_js
    assert "createPathgraphIntegrationReadiness" in panel_js
    assert "createCurrentEvidencePacket" in panel_js
    assert "createPreciseUnderstandingCandidate" in panel_js
    assert "createPageDetailCandidate" in panel_js
    assert "createLearningDemoScaffold" in panel_js
    assert "const candidateSourcePath = String(data.report_path || data.page_detail_candidate_path || sourcePath || \"\").trim();" in panel_js
    assert "const scaffoldSourcePath = String(data.report_path || data.learn_mode_demo_scaffold_path || sourcePath || \"\").trim();" in panel_js
    assert "/panel/create_model_start_approval_packet" in panel_js
    assert "/panel/create_calibration_pre_run_check" in panel_js
    assert "/panel/create_pathgraph_integration_readiness" in panel_js
    assert "/panel/create_current_evidence_packet" in panel_js
    assert "/panel/create_precise_understanding_candidate" in panel_js
    assert "/panel/create_page_detail_candidate" in panel_js
    assert "/panel/create_learning_demo_scaffold" in panel_js
    assert "/panel/create_learning_demo_goal_readiness" in panel_js
    assert 'on("learningModelStartApprovalPacketBtn", "click", createModelStartApprovalPacket);' in panel_js
    assert 'on("learningCalibrationPreRunCheckBtn", "click", createCalibrationPreRunCheck);' in panel_js
    assert 'on("learningPathGraphIntegrationReadinessBtn", "click", createPathgraphIntegrationReadiness);' in panel_js
    assert 'on("learningCurrentEvidencePacketBtn", "click", createCurrentEvidencePacket);' in panel_js
    assert 'on("learningPreciseUnderstandingCandidateBtn", "click", createPreciseUnderstandingCandidate);' in panel_js
    assert 'on("learningPageDetailCandidateBtn", "click", createPageDetailCandidate);' in panel_js
    assert 'on("learningDemoScaffoldBtn", "click", createLearningDemoScaffold);' in panel_js
    assert 'on("learningDemoGoalReadinessBtn", "click", createLearningDemoGoalReadiness);' in panel_js
    assert "learning_model_start_approval_packet_create" in panel_html
    assert "learning_calibration_pre_run_check_create" in panel_html
    assert "learning_pathgraph_integration_readiness_create" in panel_html
    assert "learning_current_evidence_packet_create" in panel_html
    assert "learning_page_detail_candidate_create" in panel_html
    assert "learning_demo_scaffold_create" in panel_html
    assert "learning_demo_goal_readiness_create" in panel_html
    assert "learning_demo_scaffold" in panel_js
    assert "learning_demo_goal_readiness" in panel_js
    assert "renderLearningDemoGoalReadiness" in panel_js
    assert "renderLearningFreshModelChainAcceptance" in panel_js
    assert "fresh_model_chain_acceptance" in panel_js
    assert "counts_as_final_goal_completion" in panel_js
    assert "source_breakdown" in panel_js
    assert "fresh_model_acceptance_status" in panel_js
    assert "fresh_model_chain_accepted" in panel_js
    assert "fresh_model_counts_as_final_goal_completion" in panel_js
    assert "fresh_acceptance=${freshModelAcceptance}" in panel_js
    assert "fresh_actual_model=${freshModelActualEvidence}" in panel_js
    assert "fresh_assisted=${freshModelAssistedEvidence}" in panel_js
    assert "renderLearningFreshModelReplacementPlan" in panel_js
    assert "replacement_plan" in panel_js
    assert "learning-demo-fresh-replacement-plan" in panel_css
    assert "replacement_required=${plan.replacement_required" in panel_js
    assert "required_source_type=${plan.required_source_type" in panel_js
    assert "fresh_model_replacement_required" in panel_js
    assert "fresh_replacement=${source.fresh_model_replacement_required" in panel_js
    assert "fresh_replacement_plan=${freshModelReplacementPlan}" in panel_js
    assert "fresh_replace_sources=${freshModelSourcesToReplace.join" in panel_js
    assert "renderLearningDemoChainManifest" in panel_js
    assert "demo_chain_manifest" in panel_js
    assert "chain_can_be_demoed" in panel_js
    assert "stage_ready_for_display" in panel_js
    assert "proof_fields" in panel_js
    assert "learning_demo_chain_can_be_demoed" in panel_js
    assert "learning_demo_chain_final_complete" in panel_js
    assert "learning_demo_chain_ready_step_count" in panel_js
    assert "learning_demo_chain_missing_proof_count" in panel_js
    assert "demo_chain=${source.learning_demo_chain_can_be_demoed" in panel_js
    assert "demoChainBadge" in panel_js
    assert "item.learning_demo_chain_can_be_demoed === true" in panel_js
    assert "item.learning_demo_chain_final_complete !== true" in panel_js
    preferred_start = panel_js.index("function preferredLearningDraftReviewSource")
    preferred_body = panel_js[preferred_start : panel_js.index("function learningDraftSourceMetaText", preferred_start)]
    assert "fresh_model_chain_accepted === true" in preferred_body
    assert "fresh_model_counts_as_final_goal_completion === true" in preferred_body
    assert preferred_body.index("fresh_model_chain_accepted === true") < preferred_body.index(
        "learning_demo_chain_can_be_demoed === true"
    )
    assert 'panelQueryFlag("demo_chain")' in panel_js
    assert 'panelQueryFlag("demoChain")' in panel_js
    assert "Learning demo chain preloaded from recommended source" in panel_js
    assert "renderLearningDemoNextAction" in panel_js
    assert "renderLearningDemoEvidenceMapItem" in panel_js
    assert "demo_evidence_map" in panel_js
    assert "artifact_exists" in panel_js
    assert "artifact_sha256_prefix" in panel_js
    assert "layout_mode=${item.layout_mode}" in panel_js
    assert "layout_section_count=${item.layout_section_count}" in panel_js
    assert "bbox_regions=${item.bbox_region_count}" in panel_js
    assert "operation_kinds=${item.operation_kinds.join" in panel_js
    assert "renderLearningPageDetailSectionSummary" in panel_js
    assert "renderLearningPageDetailOperationLinks" in panel_js
    assert "renderLearningPageDetailSpatialSections" in panel_js
    assert "renderLearningPageDetailSpatialMap(regions, bounds, sections, displayGroups)" in panel_js
    assert "renderLearningPageDetailSpatialFooterConnectors" in panel_js
    assert "item.render_in_spatial_preview !== false" in panel_js
    assert "footer_connectors" in panel_js
    assert "section.operation_summary" in panel_js
    assert "section.operation_links" in panel_js
    assert "learning-page-layout-section" in panel_css
    assert "learning-page-layout-footer-connector" in panel_css
    assert "kind_counts" in panel_js
    assert "readiness_counts" in panel_js
    assert "learning-page-detail-section-summary" in panel_css
    assert "learning-page-detail-operation-links" in panel_css
    assert "next_action_status" in panel_js
    assert "run_command_preview" in panel_js
    assert "command_executes_now" in panel_js
    assert "start_model_flag_included" in panel_js
    assert "learning-demo-next-actions" in panel_css
    assert "learning-demo-next-action" in panel_css
    assert "learning-demo-evidence-map" in panel_css
    assert "learning-demo-evidence-item" in panel_css
    assert "learning-demo-chain-manifest" in panel_css
    assert "learning-demo-chain-step" in panel_css
    assert "learning-demo-fresh-acceptance" in panel_css
    assert "runbook_status=${runbook.runbook_status" in panel_js
    assert "preflight_status=${preflight.preflight_status" in panel_js
    assert "demo_readiness=${demo.demo_readiness_status" in panel_js
    assert "approval_packet=${approvalPacket.approval_packet_status" in panel_js
    assert "calibration_pre_run=${pathgraphReadinessCalibrationPreRunStatus(calibrationPreRun)}" in panel_js
    assert "pathgraph_integration=${pathgraphIntegration.integration_readiness_status" in panel_js
    assert "pathgraphReadinessIntegration" in panel_js
    assert "pathgraphReadinessIntegrationChecklist" in panel_js
    assert "function pathgraphReadinessCalibrationPreRunStatus" in panel_js
    assert "approval_packet_checklist=${approvalPacketChecklist.join" in panel_js
    assert "approval_packet_evidence=${approvalPacketEvidence.join" in panel_js
    assert "calibration_pre_run_checklist=${calibrationPreRunChecklist.join" in panel_js
    assert "calibration_pre_run_evidence=${calibrationPreRunEvidence.join" in panel_js
    assert "calibration_pre_run_model_snapshot=${calibrationPreRunModelSnapshot.join" in panel_js
    assert "pathgraph_integration_checklist=${pathgraphIntegrationChecklist.join" in panel_js
    assert "pathgraph_integration_report=${pathgraphIntegrationReportPath}" in panel_js
    assert "runtime_promotion:${integration.ready_for_runtime_pathgraph_promotion === true ? \"true\" : \"false\"}" in panel_js
    assert "checked_at:${snapshot.checked_at || \"-\"}" in panel_js
    assert "model_ports_clear:${snapshot.model_ports_clear === true ? \"true\" : \"false\"}" in panel_js
    assert "model_processes_clear:${snapshot.model_processes_clear === true ? \"true\" : \"false\"}" in panel_js
    assert "tasks_path:${report.tasks_path || \"-\"}" in panel_js
    assert "approval_packet_sha256:${report.approval_packet_sha256 || \"-\"}" in panel_js
    assert "approval_packet_checksum_status:${report.approval_packet_checksum_status || \"unknown\"}" in panel_js
    assert "approval_packet_current_sha256:${report.approval_packet_current_sha256 || \"-\"}" in panel_js
    assert "batch_plan:${report.batch_plan_path || \"-\"}" in panel_js
    assert "expected_rerun:${report.expected_rerun_report_path || \"-\"}" in panel_js
    assert "refresh_rerun:${report.refresh_rerun_report_path || \"-\"}" in panel_js
    assert "approval_packet_calibration_preview=${approvalCalibrationCommandPreview}" in panel_js
    assert "approval_packet_refresh_preview=${approvalRefreshCommandPreview}" in panel_js
    assert "preflight_start_after_approval=${preflight.may_start_model_after_user_approval" in panel_js
    assert "may_run_now=${runbook.may_run_calibration_batch_now" in panel_js
    assert "approval_required:${runbook.approval_required === true ? \"true\" : \"false\"}" in panel_js
    assert "authorization:${runbook.artifact_is_authorization === true ? \"true\" : \"false\"}" in panel_js
    assert "calibration_preview=${calibrationCommandPreview}" in panel_js
    assert "refresh_preview=${refreshCommandPreview}" in panel_js
    assert "evidence_requirements=${evidenceRequirements.join" in panel_js
    assert "future_rerun_report:${expectedOutputs.rerun_report_status || \"unknown\"}" in panel_js
    assert "ready_regions:${readyRegions.join" in panel_js
    assert "promotion_review_gate" in panel_js
    assert "gate_status" in panel_js
    assert "learning_draft_pathgraph_readiness" in panel_js
    assert "renderLearningDemoScaffold" in panel_js
    assert "renderLearningDemoFlowStep" in panel_js
    assert "learning-demo-flow" in panel_css
    assert "learning-demo-flow-step" in panel_css
    assert "learning-demo-provenance" in panel_css
    assert "learning-demo-provenance-row" in panel_css
    assert "demo_scaffold=${scaffold.report_path}" in panel_js
    assert "model_origin=${provenance.status" in panel_js
    assert "actual_model_evidence=${provenance.actual_model_call_evidence_count" in panel_js
    assert "fully_model_generated=${provenance.meets_fully_model_generated_demo_requirement" in panel_js
    assert "model_preview=${summary.model_generated_pathgraph_preview_status" in panel_js
    assert "model_preview_regions=${summary.model_generated_pathgraph_preview_region_count" in panel_js
    assert "model_preview_actions=${summary.model_generated_pathgraph_preview_action_count" in panel_js
    assert "model_page_sections=${summary.model_generated_page_detail_section_count" in panel_js
    assert "model_page_ops=${summary.model_generated_page_detail_possible_operation_count" in panel_js
    assert "readonly_preview=${summary.page_detail_readonly_pathgraph_preview_status" in panel_js
    assert "readonly_preview_regions=${summary.page_detail_readonly_pathgraph_preview_region_count" in panel_js
    assert "readonly_preview_groups=${summary.page_detail_readonly_pathgraph_preview_display_group_count" in panel_js
    assert "model_only_demo=${modelOnlyReadiness.status" in panel_js
    assert "model_only_ready=${modelOnlyReadiness.ready" in panel_js
    assert "renderLearningModelOnlyDemoReadiness" in panel_js
    assert "Model-only demo readiness" in panel_js
    assert "learning-model-only-readiness" in panel_css
    assert "renderLearningDemoProvenanceEvidence" in panel_js
    assert "renderLearningModelGeneratedPageDetailPreview" in panel_js
    assert "Model-only page detail preview" in panel_js
    assert "Read-only PathGraph page detail preview" in panel_js
    assert "learning-model-page-detail-preview" in panel_css
    assert "width:${width.toFixed(3)}%" in panel_js
    assert "height:${height.toFixed(3)}%" in panel_js
    assert "Math.max(width, 6)" not in panel_js
    assert "Math.max(width, 7)" not in panel_js
    assert "Math.max(width, 8)" not in panel_js
    assert "box-sizing: border-box;" in panel_css
    spatial_css = "\n".join(
        panel_css[panel_css.index(selector) : panel_css.index("}", panel_css.index(selector))]
        for selector in (
            ".learning-page-layout-region",
            ".learning-page-layout-section",
            ".learning-page-layout-group",
        )
    )
    assert "min-width: 74px;" not in spatial_css
    assert "min-height: 44px;" not in spatial_css
    assert "min-width: 0;" in spatial_css
    assert "min-height: 0;" in spatial_css
    assert "not_geometry_equivalence=true" in panel_js
    assert "section_bucket_correspondence=true" in panel_js
    assert "demo_model_origin=${demoScaffoldModelOrigin}" in panel_js
    assert "demo_model_preview=${demoScaffoldModelPreview}" in panel_js
    assert "demo_model_only=${demoScaffoldModelOnlyStatus}" in panel_js
    assert "demo_model_preview_regions=${demoScaffoldModelPreviewRegions}" in panel_js
    assert "demo_model_preview_actions=${demoScaffoldModelPreviewActions}" in panel_js
    assert "demo_model_page_sections=${demoScaffoldModelPageSections}" in panel_js
    assert "demo_model_page_ops=${demoScaffoldModelPageOps}" in panel_js
    assert "demo_fully_model_generated=${source.learning_demo_scaffold_fully_model_generated" in panel_js
    assert "demo_model_only_ready=${source.learning_demo_scaffold_model_only_ready" in panel_js
    assert "learning_demo_goal_status" in panel_js
    assert "demo_goal=${demoGoalStatus}" in panel_js
    assert "learning_demo_goal_final_complete" in panel_js
    assert "demo_goal_final=${source.learning_demo_goal_final_complete" in panel_js
    assert "${renderLearningDemoScaffold(review)}" in panel_js
    assert "learning_draft_detail_attachments" in panel_js
    assert "learning_draft_attached_detail_regions" in panel_js
    assert "learning_draft_attached_detail_actions" in panel_js
    assert "setLearningDetailObserveRequests" in panel_js
    assert "learningDetailObserveRequestSelect" in panel_js
    assert "loadLearningDetailObserveSources" in panel_js
    assert "setLearningDetailObserveSourceOptions" in panel_js
    assert "setRecommendedLearningDraftReviewSource" in panel_js
    assert "loadRecommendedLearningDraftReview" in panel_js
    assert 'on("learningDraftRecommendedLoadBtn", "click", loadRecommendedLearningDraftReview);' in panel_js
    assert "recommended_current_precise_understanding" in panel_js
    assert "item.pinned" in panel_js
    assert "learningDraftReviewSourcePath" in panel_js
    assert "readiness_status" in panel_js
    assert "handoff_status" in panel_js
    assert "consistency_status" in panel_js
    assert "model_start_runbook" in panel_js
    assert "renderScreenUnderstandingModelStartRunbook" in panel_js
    assert "screen_understanding_model_start_runbook" in panel_js
    assert "runbook_status" in panel_js
    assert "may_start_model_after_user_approval" in panel_js
    assert "may_run_calibration_batch_now" in panel_js
    assert "runbook_ready_region_count" in panel_js
    assert "post_batch_refresh_has_batch_plan" in panel_js
    assert "refresh_blocks_before_future_rerun" in panel_js
    assert "calibration_coverage_rate" in panel_js
    assert "learningDraftSourceMetaText" in panel_js
    assert "learningDraftSourceLoadPath" in panel_js
    assert "preferredLearningDraftReviewSource" in panel_js
    assert "const recommended = preferredLearningDraftReviewSource(sources);" in panel_js
    assert 'item.preflight_status || "") === "ready_for_explicit_model_start"' in panel_js
    assert "item.pathgraph_candidate_path" in panel_js
    assert "[Ready preflight]" in panel_js
    assert "preflight=${preflight}" in panel_js
    assert "preflight_start_after_approval=true" in panel_js
    assert "demo=${demoReadiness}" in panel_js
    assert "demo_readiness_may_run_calibration_batch_now" in panel_js
    assert "demo_run_now=" in panel_js
    assert "approval=${approvalPacket}" in panel_js
    assert "approval_packet_may_run_calibration_batch_now" in panel_js
    assert "approval_run_now=" in panel_js
    assert "calibration_pre_run=${calibrationPreRun}" in panel_js
    assert "pathgraph_integration=${pathgraphIntegration}" in panel_js
    assert "pathgraph_integration_report=${pathgraphIntegrationReportPath}" in panel_js
    assert "calibration_pre_run_checked_at=${calibrationPreRunCheckedAt}" in panel_js
    assert "calibration_pre_run_checked_at" in panel_js
    assert "calibration_pre_run_model_ports_clear=" in panel_js
    assert "calibration_pre_run_model_processes_clear=" in panel_js
    assert "calibration_pre_run_may_run_calibration_batch_now" in panel_js
    assert "calibration_pre_run_now=" in panel_js
    assert "calibration_pre_run_checksum=${calibrationPreRunChecksumStatus}" in panel_js
    assert "/panel/learning_draft_sources" in panel_js
    assert "recent_learning_page_detail" in panel_js
    assert "recent_learning_demo_scaffold" in panel_js
    assert "learning_demo_scaffold_page_detail_ready" in panel_js
    assert 'on("learningDetailObserveSourceSelect", "change"' in panel_js
    assert 'on("learningDetailObserveSourcesBtn", "click", loadLearningDetailObserveSources);' in panel_js
    assert "attachLearningDetailObserveResult" in panel_js
    assert 'on("learningDetailObserveAttachBtn", "click", attachLearningDetailObserveResult);' in panel_js
    assert "/panel/attach_detail_observe_result" in panel_js
    assert "transition=${transitionType}->${nextRole}" in panel_js
    assert "learning_draft_candidate_transitions" in panel_js
    assert "execute_binding_enabled=false" in panel_js
    assert 'applyLearnReplaySubviewChrome(page);' in panel_js
    assert "currentLearnReplaySubview = selected;" in panel_js
    assert "function learningRuntimeGraphFromDraft" not in panel_js
    assert "function learningInterfaceMapFromDraft" not in panel_js
    assert "function loadLearningDraftPathGraph" not in panel_js
    assert "function showLearningDraftInterfaceDetails" not in panel_js
    assert "function loadLearningDraftSharedViews" not in panel_js
    assert "function clearLearningDraftReviewDisplay" in panel_js
    assert "function clearLearningDraftWorkspaceForNewRun" in panel_js
    assert "function renderLearningDraftPathPreview" in panel_js
    assert "function renderLearningDraftPathDetail" in panel_js
    assert "function buildLearningDraftObservationEvidence" in panel_js
    assert "function screenMapEvidenceCount" in panel_js
    assert "screen_map_available_no_recent_learn_deep" in panel_js
    assert "hasCoordinateReviewEvidence" in panel_js
    assert "coordinate_calibration_status" in panel_js
    assert "calibrated_targets: compactLearningDraftTargets" in panel_js
    assert "function learningTrialRequestPayload" not in panel_js
    assert "function learningRecognitionTrialRequestPayload" in panel_js
    assert "/panel/run_learning_recognition_trial" in panel_js
    assert "/panel/run_learning_model_trial" not in panel_js
    assert "data-learning-draft-node" in panel_js
    render_review_start = panel_js.index("function renderLearningDraftReview")
    clear_review_start = panel_js.index("function clearLearningDraftReviewDisplay")
    render_review_body = panel_js[render_review_start:clear_review_start]
    assert "renderLearningDraftPathPreview(review)" in render_review_body
    assert "renderRuntimePathGraph" not in render_review_body
    readiness_start = panel_js.index("function renderLearningDraftPathGraphReadiness")
    runbook_start = panel_js.index("function pathgraphReadinessRunbook")
    readiness_body = panel_js[readiness_start:runbook_start]
    assert "pathgraph_integration_report=${pathgraphIntegrationReportPath}" in readiness_body
    assert "navPathCanvas" not in render_review_body
    assert "learning_draft_review_auto_loaded: false" in panel_js
    assert "$(\"learningTrialResultPath\")?.value" in panel_js
    assert "$(\"learningPathGraphCandidatePath\")?.value" in panel_js
    assert "$(\"learningPathGraphValidationPath\")?.value" in panel_js
    assert 'clearLearningDraftReviewDisplay("not_loaded · source path prepared; click Load learning draft")' in panel_js
    load_model_start = panel_js.index("async function loadReplayModelArtifact")
    load_app_profile_start = panel_js.index("async function loadReplayAppProfile")
    load_model_body = panel_js[load_model_start:load_app_profile_start]
    assert "await loadLearningDraftReview({ skipResponse: true })" not in load_model_body
    capture_trial_start = panel_js.index("async function captureLearningDraftWindow")
    run_trial_start = panel_js.index("async function runLearningDraftTrial")
    learning_review_start = panel_js.index("function learningReviewLabel")
    capture_trial_body = panel_js[capture_trial_start:run_trial_start]
    run_trial_body = panel_js[run_trial_start:learning_review_start]
    run_flow_start = panel_js.index("async function runLearningInterfaceFlow")
    run_flow_end = panel_js.index("async function runLearningDraftTrial")
    run_flow_body = panel_js[run_flow_start:run_flow_end]
    assert 'clearLearningDraftWorkspaceForNewRun("not_loaded · new learning run started")' in run_flow_body
    assert run_flow_body.index("clearLearningDraftWorkspaceForNewRun") < run_flow_body.index("captureLearningDraftWindow")
    assert 'clearScreenUnderstandingResidualDisplays("not_loaded · screen understanding started")' in capture_trial_body
    assert "await loadLearningDraftReview({ skipResponse: true })" in run_trial_body
    assert 'clearScreenUnderstandingResidualDisplays("not_loaded · generating learning draft", {' in run_trial_body
    assert "preserveTwoStageReportPath: Boolean(options.preserveTwoStageReportPath)" in run_trial_body
    request_payload_start = panel_js.index("function learningRecognitionTrialRequestPayload")
    capture_trial_start_for_payload = panel_js.index("async function captureLearningDraftWindow", request_payload_start)
    request_payload_body = panel_js[request_payload_start:capture_trial_start_for_payload]
    assert "two_stage_report_path: String(lastLearningTwoStageReportPath || \"\").trim() || null" in request_payload_body
    assert run_trial_body.index("const payload = learningRecognitionTrialRequestPayload()") < run_trial_body.index(
        'clearScreenUnderstandingResidualDisplays("not_loaded · generating learning draft", {'
    )
    assert "const trialEvidence = learningInterfaceTrialEvidenceSummary(trial)" in run_flow_body
    assert "const twoStage = await runLearningTwoStageUnderstanding()" in run_flow_body
    assert "const twoStageAllowed = learningTwoStageAllowsDraftTrial(twoStage)" in run_flow_body
    assert "if (!twoStageAllowed)" in run_flow_body
    blocked_stage_body = run_flow_body[
        run_flow_body.index("if (!twoStageAllowed)"):
        run_flow_body.index("setLearningInterfaceFlowStep(\n      \"fusion\"", run_flow_body.index("if (!twoStageAllowed)"))
    ]
    assert "return trial" not in blocked_stage_body
    assert "loading review overlay" in blocked_stage_body
    assert "const fusedTrial = await runLearningDraftTrial({ preserveTwoStageReportPath: true })" in run_flow_body
    assert "let lastLearningTwoStageReportPath" in panel_js
    assert 'lastLearningTwoStageReportPath = ""' in panel_js
    assert 'lastLearningTwoStageReportPath = String(resultOf(response).report_path || "").trim()' in panel_js
    create_page_detail_start = panel_js.index("async function createPageDetailCandidate")
    create_demo_scaffold_start = panel_js.index("async function createLearningDemoScaffold")
    create_page_detail_body = panel_js[create_page_detail_start:create_demo_scaffold_start]
    assert create_page_detail_body.index("lastLearningTwoStageReportPath") < create_page_detail_body.index("learningPathGraphCandidatePath")
    assert create_page_detail_body.index("lastLearningTwoStageReportPath") < create_page_detail_body.index("learningDetailObserveCandidatePath")
    assert create_page_detail_body.index("lastLearningTwoStageReportPath") < create_page_detail_body.index("learningDraftReviewSourcePath()")
    assert 'stage2_region_strategy: "partitioned"' in panel_js
    assert 'stage2_region_strategy: "global_no_partition"' not in run_flow_body
    assert run_flow_body.index("const twoStage = await runLearningTwoStageUnderstanding()") < run_flow_body.index("const fusedTrial = await runLearningDraftTrial")
    assert run_flow_body.index("if (!twoStageAllowed)") < run_flow_body.index("const fusedTrial = await runLearningDraftTrial")
    assert "replayModelArtifactPath" not in run_trial_body
    assert "loadReplayModelArtifact" not in run_trial_body
    assert "/execute/" not in run_trial_body
    generate_start = panel_js.index("async function generatePathGraphCandidate")
    load_model_start_again = panel_js.index("async function loadReplayModelArtifact")
    generate_body = panel_js[generate_start:load_model_start_again]
    assert "/panel/generate_pathgraph_candidate" in generate_body
    assert "replayGraphPath" not in generate_body
    assert "taskRunGraphPath" not in generate_body
    assert "loadReplayModelArtifact" not in generate_body
    assert "/execute/" not in generate_body
    assert "learning_draft_shared_views_loaded_v1" not in panel_js
    assert "learned_seek_template_draft" not in panel_js
    assert "learned_navigation_path_graph_draft" not in panel_js
    assert "learning_output_draft_regions" not in panel_js
    assert "learning_output_draft_actions" not in panel_js
    assert "learning_output_coverage" not in panel_js
    assert "learning_site_validation" not in panel_js
    assert "learning_overall_score" not in panel_js
    assert "report.prompt_parameter_feedback" not in panel_js
    assert ".learning-mode-switch" not in panel_css
    assert ".learning-workbench" not in panel_css
    assert ".learning-template-panel" not in panel_css
    assert ".learning-output-panel" not in panel_css
    assert ".learning-review-panel" in panel_css
    assert ".learning-review-preview-bbox" in panel_css
    assert ".image-inspector-overlay" in panel_css
    assert ".screen-understanding-overlay-toolbar" in panel_css
    assert ".image-inspector-box" in panel_css
    assert ".image-inspector-point" in panel_css
    assert ".image-inspector-footer" in panel_css
    assert ".learning-review-edited-badge" in panel_css
    assert ".learning-review-bbox-summary" in panel_css

    assert ".learning-draft-path-preview" in panel_css
    assert ".learning-draft-path-grid" in panel_css
    assert ".learning-draft-path-resizer" in panel_css
    assert "grid-column: 1 / -1" in panel_css
    assert "--learning-draft-path-map-width" in panel_css
    assert ".learning-draft-node.active" in panel_css
    assert ".form-section-label" in panel_css
    assert ".learn-replay-subview" in panel_css
    assert ".learn-replay-subview.active" in panel_css
    assert ".learn-replay-tab.active" in panel_css
    assert ".replay-action-disclosure" in panel_css
    assert ".learning-review-summary" in panel_css
    assert "body.learn-replay-draft-subview .nav-path-panel" in panel_css
    assert "body.learn-replay-draft-subview .path-detail-panel" in panel_css
    assert "body.learn-fast-clean-stage .nav-path-panel" in panel_css
    assert "body.learn-fast-clean-stage .path-detail-panel" in panel_css
    assert 'body:not([data-path-surface="visible"]) .nav-path-panel' in panel_css
    assert 'body:not([data-path-surface="visible"]) .path-detail-panel' in panel_css
    assert "[hidden]" in panel_css
    assert 'body[data-stage-page="observe"] .nav-path-panel' in panel_css
    assert 'body[data-stage-page="observe"] .path-detail-panel' in panel_css
    assert 'body[data-stage-page="observe"] #navPathPanel' in panel_css
    assert 'body[data-stage-page="observe"] #pathDetailPanel' in panel_css
    assert 'body[data-stage-page="observe"] .stage-page[data-page="learn_replay"]' in panel_css
    assert 'body[data-stage-page="observe"] .learn-replay-subview[data-learn-replay-panel="template"]' in panel_css
    assert 'body[data-stage-page="observe"] #replayGraphSummary' in panel_css
    assert 'body[data-stage-page="observe"] #replayInterfaceMapPanel' in panel_css
    assert 'body[data-stage-page="observe"] #replayGraphActions' in panel_css
    assert 'body[data-stage-page="observe"] #learningDraftReviewPanel' in panel_css
    assert 'body[data-stage-page="observe"] #learningDraftPathPreview' in panel_css
    assert 'body.learn-fast-clean-stage .stage-page[data-page="learn_replay"]' in panel_css
    assert 'body.learn-fast-clean-stage .learn-replay-subview[data-learn-replay-panel="template"]' in panel_css
    assert 'body.learn-fast-clean-stage #replayGraphSummary' in panel_css
    assert 'body.learn-fast-clean-stage #replayInterfaceMapPanel' in panel_css
    assert 'body.learn-fast-clean-stage #replayGraphActions' in panel_css
    assert 'body.learn-fast-clean-stage #learningDraftReviewPanel' in panel_css
    assert 'body.learn-fast-clean-stage #learningDraftPathPreview' in panel_css
    assert 'body[data-path-surface="hidden"] .nav-path-panel' in panel_css
    assert 'body[data-path-surface="hidden"] .path-detail-panel' in panel_css
    assert 'body[data-path-surface="hidden"] #navPathPanel' in panel_css
    assert 'body[data-path-surface="hidden"] #pathDetailPanel' in panel_css
    assert "function hideSharedPathSurface()" in panel_js
    assert "function bindLearningDraftPathResize" in panel_js
    assert "LEARNING_DRAFT_PATH_SPLIT_STORAGE_KEY" in panel_js
    assert 'on("learningDraftPathLayoutResetBtn", "click", resetLearningDraftPathLayout)' in panel_js
    assert "function clearScreenUnderstandingResidualDisplays" in panel_js
    assert 'setSharedPathSurfaceVisibility("observe");' in panel_js
    assert 'resetSharedPathForScreenUnderstanding($("observeApp").value || $("locateApp").value || "")' in panel_js
    assert 'resetSharedPathForScreenUnderstanding($("observeApp").value || "")' in panel_js
    assert 'clearScreenUnderstandingResidualDisplays("not_loaded · screen understanding started")' in panel_js
    clear_artifacts_start = panel_js.index("function clearLearningDraftTrialArtifacts")
    active_stage_start = panel_js.index("function activeStagePage")
    clear_artifacts_body = panel_js[clear_artifacts_start:active_stage_start]
    assert 'setLearningTrialResultPath("")' in clear_artifacts_body
    assert 'setLearningDraftReviewSourcePath("")' in clear_artifacts_body
    assert "setLearningPathGraphCandidatePaths({})" in clear_artifacts_body
    assert "clearLearningDraftReviewDisplay(reason)" in clear_artifacts_body
    clear_residual_start = panel_js.index("function clearScreenUnderstandingResidualDisplays")
    clear_residual_end = panel_js.index("function enterScreenUnderstandingStage")
    clear_residual_body = panel_js[clear_residual_start:clear_residual_end]
    assert 'setLearnReplaySubview("draft")' not in clear_residual_body
    assert "clearLearningDraftTrialArtifacts(reason, options)" in clear_residual_body
    assert "preserveTwoStageReportPath" in clear_artifacts_body
    assert 'lastLearningTwoStageReportPath = ""' in clear_artifacts_body
    assert "clearTemplateReplayResidualDisplays(reason)" in clear_residual_body
    assert "clearSharedPathDetailDisplay()" in clear_residual_body
    assert "hideSharedPathSurface()" in clear_residual_body
    assert '$("responseText").textContent = "{}"' in clear_residual_body
    clear_template_start = panel_js.index("function clearTemplateReplayResidualDisplays")
    clear_template_end = panel_js.index("function clearScreenUnderstandingResidualDisplays")
    clear_template_body = panel_js[clear_template_start:clear_template_end]
    assert '$("replayGraphSummary").innerHTML = ""' in clear_template_body
    assert '$("replayInterfaceMapPanel").innerHTML = ""' in clear_template_body
    assert '$("replayGraphActions").innerHTML = ""' in clear_template_body
    assert '$("replayAgentPromptSummary").innerHTML = ""' in clear_template_body
    assert '$("replayAgentPromptTemplate").value = ""' in clear_template_body
    assert '$("replayAgentPromptDiff").textContent = ""' in clear_template_body
    assert "replayArtifact = null" in clear_template_body
    assert "replayInterfaceMap = null" in clear_template_body
    assert "selectedInterfaceMapRef = \"\"" in clear_template_body
    enter_observe_start = panel_js.index("function enterScreenUnderstandingStage")
    enter_observe_end = panel_js.index("function clearSharedPathDetailDisplay")
    enter_observe_body = panel_js[enter_observe_start:enter_observe_end]
    assert 'clearScreenUnderstandingResidualDisplays("not_loaded · screen understanding started")' in enter_observe_body
    assert 'setSharedPathSurfaceVisibility("observe")' not in enter_observe_body
    assert "hideSharedPathSurface()" in enter_observe_body
    assert "renderLearningDraftPathPreview" not in enter_observe_body
    assert "renderLearningDraftPathDetail" not in enter_observe_body
    set_subview_start = panel_js.index("function setLearnReplaySubview")
    set_subview_end = panel_js.index("function learningRecognitionTrialRequestPayload")
    set_subview_body = panel_js[set_subview_start:set_subview_end]
    assert 'if (selected === "draft") hideSharedPathSurface()' in set_subview_body
    observe_handler_start = panel_js.index('on("observeBtn", "click"')
    observe_handler_end = panel_js.index('on("analyzeBtn", "click"', observe_handler_start)
    observe_handler_body = panel_js[observe_handler_start:observe_handler_end]
    assert 'clearScreenUnderstandingResidualDisplays("not_loaded · screen understanding started")' in observe_handler_body
    assert observe_handler_body.index("clearScreenUnderstandingResidualDisplays") < observe_handler_body.index("ensureStageModelReady")
    render_nav_start = panel_js.index("function renderNavPath")
    render_nav_end = panel_js.index("/* 鈹€鈹€ Fake test data")
    render_nav_body = panel_js[render_nav_start:render_nav_end]
    hidden_branch = render_nav_body[
        render_nav_body.index("if (!sharedPathSurfaceVisible())"):
        render_nav_body.index("if (!ensurePathCanvas())")
    ]
    assert "clearSharedPathDetailDisplay()" in hidden_branch
    assert ".learning-interface-detail-grid" not in panel_css


def test_panel_two_stage_endpoint_returns_review_boxes_for_real_learning_flow(monkeypatch) -> None:
    client = TestClient(app)

    monkeypatch.setattr(
        panel_api,
        "_observe_bundle_from_trace_result",
        lambda result, trace_path: {
            "image_path": result.get("image_path", ""),
            "source_image_path": result.get("image_path", ""),
            "screen_size": {"width": 320, "height": 240},
            "screen_reading": {"screen_summary": "demo screen"},
        },
    )
    monkeypatch.setattr(
        panel_api,
        "_stage1_inventory_from_trace_result",
        lambda result: [{"item_id": "item_1", "label": "Main", "bbox": {"x": 0, "y": 0, "w": 320, "h": 240}}],
    )
    monkeypatch.setattr(
        panel_api,
        "build_inventory_layout_graph",
        lambda inventory, screen_size=None: {"node_count": len(inventory), "zone_count": 1, "zones": {}},
    )
    monkeypatch.setattr(
        panel_api,
        "build_two_stage_screen_understanding",
        lambda **kwargs: {
            "stage1_gate": {"status": "passed", "failure_categories": [], "allow_stage2_numbering": True},
            "stage2_numbering_skipped": False,
            "stage2_numbering": {"regions": [{"region_id": "R1"}]},
            "fusion": {
                "compiled_overlay_path": "artifacts/review-overlays/demo_two_stage.png",
                "full_screen_understanding_overlay_path": "artifacts/review-overlays/demo_two_stage.png",
                "fused_review_boxes": [
                    {
                        "id": "R1",
                        "label": "Main Card",
                        "role": "review_only",
                        "bbox": {"x": 10, "y": 20, "w": 100, "h": 80},
                    }
                ],
            },
        },
    )
    monkeypatch.setattr(panel_api, "fusion_status_from_two_stage", lambda report: {"status": "available"})

    response = client.post(
        "/panel/run_learning_two_stage_understanding",
        json={
            "app_name": "demo_app",
            "state_hint": "home",
            "observe_result": {"image_path": "artifacts/screenshots/demo.png", "image_size": {"width": 320, "height": 240}},
            "require_stage1_gate": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["contract_version"] == "panel_learning_two_stage_understanding_run_v1"
    assert data["stage1_gate"]["status"] == "passed"
    assert data["stage2_numbering_skipped"] is False
    assert data["learn_all_targets"]["review_box_count"] == 1
    assert data["learn_all_targets"]["review_boxes"][0]["label"] == "Main Card"
    assert data["coordinate_overlay_path"] == "artifacts/review-overlays/demo_two_stage.png"
    assert data["model_grounding_evidence"]["status"] == "not_valid_for_model_grounding_evidence"
    assert data["summary"]["model_grounding_evidence_status"] == "not_valid_for_model_grounding_evidence"
    assert data["real_clicks"] == 0
    assert data["promotion_allowed"] is False
    saved_report = json.loads(Path(data["report_path"]).read_text(encoding="utf-8-sig"))
    assert saved_report["model_grounding_evidence"]["status"] == "not_valid_for_model_grounding_evidence"
    assert saved_report["learn_all_targets"]["review_box_count"] == 1
    assert saved_report["learn_all_targets"]["review_boxes"][0]["label"] == "Main Card"
    assert saved_report["learn_all_targets"]["overlay_path"] == "artifacts/review-overlays/demo_two_stage.png"
    assert saved_report["learn_all_targets"]["stage1_gate_status"] == "passed"

def test_seek_search_button_visual_asset_uses_real_source_screenshot() -> None:
    map_path = Path("artifacts/visual-match-smoke/live_seek_20260624/learned_interface_map_calibrated_real_crops.json")
    interface_map = json.loads(map_path.read_text(encoding="utf-8"))
    asset = next(item for item in interface_map["fixed_visual_assets"] if item["asset_id"] == "seek:visual:search_button")

    source_path = Path(asset["source"]["source_image_path"])
    tight_path = Path(asset["template_refs"]["tight_crop_ref"])
    context_path = Path(asset["template_refs"]["context_crop_ref"])
    bbox = asset["source"]["bbox"]

    assert source_path.exists()
    assert tight_path.exists()
    assert context_path.exists()
    assert asset["template_refs"]["source_image_path"] == asset["source"]["source_image_path"]
    assert bbox["x"] > 1700
    assert bbox["y"] < 260

    with Image.open(tight_path) as image:
        rgb_bytes = image.convert("RGB").tobytes()
        magenta_pixels = sum(
            1
            for index in range(0, len(rgb_bytes), 3)
            if rgb_bytes[index] > 190 and rgb_bytes[index + 1] < 80 and rgb_bytes[index + 2] > 110
        )
        assert magenta_pixels > 1000


def test_seek_search_input_precedes_search_button_by_screen_position() -> None:
    map_path = Path("artifacts/visual-match-smoke/live_seek_20260624/learned_interface_map_calibrated_real_crops.json")
    interface_map = json.loads(map_path.read_text(encoding="utf-8"))
    assets = {item["asset_id"]: item for item in interface_map["fixed_visual_assets"]}
    search_input = assets["seek:visual:search_input"]
    search_button = assets["seek:visual:search_button"]

    input_x = search_input["bbox"]["x"]
    button_x = search_button["source"]["bbox"]["x"]

    assert search_input["region_id"] == search_button["region_id"] == "top_search_area"
    assert input_x < button_x
    assert search_input["label"] == "Search input field"
    assert search_button["label"] == "Search button"


def test_panel_region_workflow_stays_in_node_detail_and_inspector() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8")

    runtime_detail_start = panel_js.index("function runtimeNodeDetailHtml")
    screen_regions_start = panel_js.index("function pathDetailScreenRegionsHtml")
    layout_panel_start = panel_js.index("function interfaceLayoutRegionPanelHtml")
    child_layout_start = panel_js.index("function interfaceLayoutChildRegionHtml")
    inspector_workflow_start = panel_js.index("function interfaceInspectorRegionWorkflowHtml")
    inspector_state_workflow_start = panel_js.index("function interfaceInspectorStateWorkflowHtml")
    inspector_editor_start = panel_js.index("function interfaceInspectorEditorHtml")

    runtime_detail_body = panel_js[runtime_detail_start:screen_regions_start]
    screen_regions_body = panel_js[screen_regions_start:layout_panel_start]
    layout_panel_body = panel_js[layout_panel_start:child_layout_start]
    inspector_state_workflow_body = panel_js[inspector_state_workflow_start:inspector_workflow_start]
    inspector_workflow_body = panel_js[inspector_workflow_start:inspector_editor_start]

    assert "replay_workflow_skill" not in runtime_detail_body
    assert "runtimeNodeRegionWorkflowItemsHtml(node)" not in runtime_detail_body
    assert "replay_workflow_skill" in inspector_state_workflow_body
    assert "interface-inspector-region-action-group" in inspector_state_workflow_body
    assert "interfaceRegionRefsForState(state, regions)" in inspector_state_workflow_body
    assert "interfaceWorkflowActionsForRegion(regionId)" in inspector_state_workflow_body
    assert "replay_workflow_skill" in inspector_workflow_body
    assert "interfaceInspectorRegionWorkflowHtml" not in screen_regions_body
    assert "replay_workflow_skill" not in screen_regions_body
    assert "interfaceInspectorRegionWorkflowHtml" not in layout_panel_body
    assert "replay_workflow_skill" not in layout_panel_body
    assert layout_panel_body.index("interface-layout-children") < layout_panel_body.index("interface-layout-assets")


def test_panel_interface_map_uses_compact_structural_assets() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8")
    panel_css = Path("app/web_panel/panel.css").read_text(encoding="utf-8")

    assert "function interfaceRegionContentNodesHtml" in panel_js
    assert "function interfaceSortedVisualAssets" in panel_js
    assert "function interfaceAssetSortBbox" in panel_js
    assert 'loading="eager"' in panel_js
    assert 'decoding="async"' in panel_js
    content_nodes_start = panel_js.index("function interfaceRegionContentNodesHtml")
    content_nodes_end = panel_js.index("function interfaceVisualNodeHtml")
    content_nodes_body = panel_js[content_nodes_start:content_nodes_end]
    assert "regionDynamics.map" in content_nodes_body
    assert "visualAssets.map" in content_nodes_body
    assert content_nodes_body.index("regionDynamics.map") < content_nodes_body.index("visualAssets.map")
    assert "interfaceSortedVisualAssets(regionAssets)" in panel_js
    assert "const compact = !showThumb && !crop" in panel_js
    assert "interface-visual-node-compact" in panel_js
    assert "interface-visual-node-compact" in panel_css
    assert "结构节点 / no button crop" in panel_css
    assert "interface-dynamic-summary" in panel_css
    assert 'data-region-id="application_progress"' in panel_css
    assert 'data-region-id="application_review_step"' in panel_css
    assert 'data-region-id="${escapeHtml(regionId)}"' in panel_js
    assert "while (changed)" in panel_js
    assert "regionIds.add(regionId)" in panel_js
    assert 'if (id === "application_review_step") return nestedEntry(id, ["application_review"]);' in panel_js
    assert 'interfaceLayoutChildRegionHtml(childEntry, assets, dynamicAreas, dangerZones, states, transitions, childEntry.childEntries || [])' in panel_js
    assert '${childEntries.length ? " open" : ""}' in panel_js
    assert '.interface-child-region[data-region-id="application_review_step"] > .interface-layout-children' in panel_css
    assert '.interface-child-region[data-region-id="application_progress"],\n.interface-known-layout-seek-application .interface-child-region[data-region-id="application_review_step"]' not in panel_css
    assert '.interface-child-region[data-region-id="application_profile"],\n.interface-known-layout-seek-application .interface-child-region[data-region-id="application_review_step"]' in panel_css
    show_detail_start = panel_js.index("function showNavNodeDetail")
    show_detail_end = panel_js.index("function bindPathDetailInterfaceControls")
    show_detail_body = panel_js[show_detail_start:show_detail_end]
    assert "currentNavNodeId = nodeId" in show_detail_body
    assert "runtimePathGraphView.currentStateId = nodeId" in show_detail_body
    assert "setPathGraphBadges" in show_detail_body


def test_seek_default_interface_map_contains_application_visual_assets() -> None:
    map_path = Path("artifacts/visual-match-smoke/live_seek_20260624/learned_interface_map_calibrated_real_crops.json")
    data = json.loads(map_path.read_text(encoding="utf-8"))
    graph_path = Path("artifacts/seek/runtime_path_graph_seek_mvp_20260617.json")
    graph = json.loads(graph_path.read_text(encoding="utf-8"))

    assets = {
        item.get("asset_id"): item
        for item in data.get("fixed_visual_assets", [])
        if str(item.get("region_id", "")).startswith("application_")
    }
    assert "seek:visual:application_progress_steps" in assets
    assert "seek:visual:resume_select_dropdown" in assets
    assert "seek:visual:cover_letter_text_area" in assets
    assert "seek:visual:application_continue_button" in assets
    assert "seek:visual:submit_application_button" in assets
    assert all((item.get("template_refs") or {}).get("tight_crop_ref") for item in assets.values())
    assert all(item.get("can_authorize_click") is False for item in assets.values())
    assert assets["seek:visual:submit_application_button"].get("semantic_action") == "final_submit"

    application_regions = {
        item.get("region_id"): item
        for item in data.get("regions", [])
        if str(item.get("region_id", "")).startswith("application_")
    }
    expected_application_steps = [
        "application_progress",
        "application_documents",
        "application_questions",
        "application_profile",
        "application_review_step",
    ]
    states = {item.get("state_id"): item for item in data.get("states", [])}
    assert states["seek_application_page"].get("region_refs") == ["application_form"]
    display_states = {item.get("state_id"): item for item in graph.get("display_states", [])}
    graph_regions = {item.get("region_id"): item for item in graph.get("regions", [])}
    graph_actions = {item.get("action_template_id"): item for item in graph.get("action_templates", [])}
    assert display_states["seek_application_page"].get("region_refs") == ["application_form"]
    assert graph_regions["application_form"].get("child_region_ids") == expected_application_steps
    assert graph_regions["application_review_step"].get("parent_region_id") == "application_form"
    assert graph_regions["application_review_step"].get("child_region_ids") == ["application_review"]
    assert graph_regions["application_review"].get("parent_region_id") == "application_review_step"
    for action_id in [
        "read_application_flow",
        "detect_application_step",
        "keep_default_resume",
        "fill_employer_questions",
        "continue_application_next_step",
        "continue_without_profile_mutation",
        "extract_final_review",
        "final_submit",
    ]:
        assert action_id in graph_actions
        assert graph_actions[action_id].get("safety_policy", {}).get("final_submit_forbidden") is True
    assert graph_actions["final_submit"].get("safety_policy", {}).get("hard_block") is True
    assert application_regions["application_form"].get("description")
    assert application_regions["application_form"].get("child_region_ids") == expected_application_steps
    assert application_regions["application_review_step"].get("parent_region_id") == "application_form"
    assert application_regions["application_review_step"].get("region_type") == "form_flow"
    assert application_regions["application_review_step"].get("child_region_ids") == ["application_review"]
    assert application_regions["application_review"].get("parent_region_id") == "application_review_step"
    assert "final Submit remains hard-blocked" in application_regions["application_review"].get("description", "")

    application_dynamic = {
        item.get("area_id"): item
        for item in data.get("dynamic_areas", [])
        if str(item.get("region_id", "")).startswith("application_")
    }
    assert "seek:application:question_fields_roi" in application_dynamic
    assert "seek:application:final_review_roi" in application_dynamic
    assert application_dynamic["seek:application:cover_letter_roi"].get("description")
    assert application_dynamic["seek:application:question_fields_roi"].get("semantic_role") == "employer_question_fields"
    assert application_dynamic["seek:application:final_review_roi"].get("semantic_role") == "final_review_summary"


def test_seek_default_interface_map_contains_home_page_visual_assets() -> None:
    map_path = Path("artifacts/visual-match-smoke/live_seek_20260624/learned_interface_map_calibrated_real_crops.json")
    data = json.loads(map_path.read_text(encoding="utf-8"))

    assets = {
        item.get("asset_id"): item
        for item in data.get("fixed_visual_assets", [])
    }
    states = {item.get("state_id"): item for item in data.get("states", [])}
    assert states["seek_home_page"].get("region_refs") == ["top_search_area", "results_list", "job_detail"]
    regions = {item.get("region_id"): item for item in data.get("regions", [])}
    for region_id in ["top_search_area", "results_list", "job_card", "job_detail", "detail_header", "detail_body"]:
        assert regions[region_id].get("description")
    required = {
        "seek:visual:search_input": ("top_search_area", "type_public_search_query"),
        "seek:visual:search_button": ("top_search_area", "search_or_filter_results"),
        "seek:visual:job_card_shape": ("job_card", "open_detail"),
        "seek:visual:apply_button": ("detail_header", "external_apply_flow"),
        "seek:visual:quick_apply_button": ("detail_header", "open_apply_flow"),
        "seek:visual:save_icon": ("detail_header", "save_or_bookmark"),
    }
    for asset_id, (region_id, semantic_action) in required.items():
        asset = assets[asset_id]
        refs = asset.get("template_refs") or {}
        crop_path = Path(refs.get("tight_crop_ref") or "")
        source_path = Path(refs.get("source_image_path") or "")
        assert asset.get("region_id") == region_id
        assert asset.get("semantic_action") == semantic_action
        assert crop_path.exists(), f"{asset_id} crop is missing: {crop_path}"
        if source_path:
            assert source_path.exists(), f"{asset_id} source image is missing: {source_path}"

    apply_refs = assets["seek:visual:apply_button"].get("template_refs") or {}
    apply_ref_text = json.dumps(apply_refs, ensure_ascii=False)
    search_input_refs = assets["seek:visual:search_input"].get("template_refs") or {}
    search_input_ref_text = json.dumps(search_input_refs, ensure_ascii=False)
    assert assets["seek:visual:search_input"].get("role") == "input"
    assert "search_input" in search_input_ref_text
    assert "search_button" not in search_input_ref_text
    assert "quick_apply" not in apply_ref_text
    assert "quick_apply" not in str(assets["seek:visual:apply_button"].get("template_alias_asset_id", ""))
    assert "Quick Apply" not in str(assets["seek:visual:apply_button"].get("template_alias_reason", ""))
    assert "quick_apply" in str((assets["seek:visual:quick_apply_button"].get("template_refs") or {}).get("tight_crop_ref", ""))
    assert assets["seek:visual:apply_button"].get("danger_level") == "external_flow_entry"
    assert assets["seek:visual:apply_button"].get("semantic_action") == "external_apply_flow"
    assert assets["seek:visual:quick_apply_button"].get("semantic_action") == "open_apply_flow"
    summary = data.get("summary") or {}
    assert summary.get("state_count") == len(data.get("states") or [])
    assert summary.get("region_count") == len(data.get("regions") or [])
    assert summary.get("fixed_visual_asset_count") == len(data.get("fixed_visual_assets") or [])
    assert summary.get("dynamic_area_count") == len(data.get("dynamic_areas") or [])
    assert summary.get("danger_zone_count") == len(data.get("danger_zones") or [])
    assert "Apply uses Quick Apply" not in str(summary.get("real_crop_ref_note", ""))
    assert "standard Apply is an external application entry" in str(summary.get("real_crop_ref_note", ""))

    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    assert "external_apply_flow" in panel_js
    assert "external_flow_entry" in panel_js

    dynamic_areas = {
        item.get("area_id"): item
        for item in data.get("dynamic_areas", [])
    }
    job_cards_area = dynamic_areas["seek:job_cards"]
    assert job_cards_area.get("region_id") == "results_list"
    assert job_cards_area.get("label") == "Job cards list"
    assert job_cards_area.get("semantic_role") == "repeatable_job_cards"
