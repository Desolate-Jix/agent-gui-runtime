from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.api import memory as memory_api
from app.api import panel as panel_api
from app.learn.workflow_contracts import LearningTaskResult
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
    assert 'data-stage="template_display"' not in response.text
    assert 'data-stage="learn_validation"' not in response.text
    assert 'data-stage="execute_actions"' in response.text
    assert 'data-stage="execute_task_run"' not in response.text
    assert 'data-stage="execute_locate"' in response.text
    assert 'data-i18n="nav_group_replay"' not in response.text
    assert 'data-i18n="nav_group_replay_flow"' not in response.text
    assert 'data-stage="open_bind"' in response.text
    assert 'data-stage="capture"' in response.text
    assert 'data-stage="learn_interface" data-step="1"' in response.text
    assert 'data-stage="execute_actions" data-step="1"' in response.text
    assert 'data-stage="execute_locate" data-step="2"' in response.text
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
    assert 'data-learn-replay-view="template"' not in response.text
    assert 'data-learn-replay-view="draft"' not in response.text
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
    assert 'id="learningCorrectionMemoryRefreshBtn"' in response.text
    assert 'id="learningCorrectionMemorySummary"' in response.text
    assert 'id="learningCorrectionMemoryList"' in response.text
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
    assert 'id="learningDraftHierarchySummary"' in response.text
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


def test_learning_workflow_transition_endpoint_rejects_stage_skip() -> None:
    client = TestClient(app)
    first = client.post(
        "/panel/transition_learning_workflow_state",
        json={
            "run_id": "run-panel",
            "expected_revision": 0,
            "stage": "bind_capture",
            "outcome": "running",
            "reason": "started",
            "evidence_refs": {},
        },
    )

    assert first.status_code == 200
    assert first.json()["success"] is True
    state = first.json()["data"]["workflow_state"]

    skipped = client.post(
        "/panel/transition_learning_workflow_state",
        json={
            "run_id": "run-panel",
            "expected_revision": state["revision"],
            "stage": "numbered_map",
            "outcome": "running",
            "reason": "invalid skip",
            "evidence_refs": {},
        },
    )

    assert skipped.status_code == 200
    assert skipped.json()["success"] is False
    assert skipped.json()["error"]["code"] == "learning_workflow_transition_invalid"


def test_learning_workflow_state_endpoint_recovers_by_run_id() -> None:
    client = TestClient(app)
    run_id = "run-panel-recovery"
    started = client.post(
        "/panel/transition_learning_workflow_state",
        json={
            "run_id": run_id,
            "expected_revision": 0,
            "stage": "bind_capture",
            "outcome": "running",
        },
    )
    assert started.json()["success"] is True

    recovered = client.get(f"/panel/learning_workflow_state/{run_id}")

    assert recovered.status_code == 200
    assert recovered.json()["success"] is True
    assert recovered.json()["data"]["workflow_state"]["revision"] == 1
    assert recovered.json()["data"]["workflow_state"]["current_stage"] == "bind_capture"


def test_panel_saves_structured_learning_calibration_result(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    source_image = tmp_path / "artifacts" / "screenshots" / "capture.png"
    numbering_report = tmp_path / "artifacts" / "learning-runs" / "run-panel" / "stage2.json"
    overlay = tmp_path / "artifacts" / "review-overlays" / "calibrated.png"
    trace_path = tmp_path / "logs" / "traces" / "vision" / "calibration.json"
    for path, content in (
        (source_image, b"capture"),
        (numbering_report, b"numbering"),
        (overlay, b"overlay"),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text(
        json.dumps(
            {
                "success": True,
                "request": {
                    "image_path": str(source_image),
                    "metadata": {
                        "two_stage_report_path": str(numbering_report),
                        "learning_interface_flow": True,
                        "no_live_click_authorization": True,
                    },
                },
                "result": {
                    "image_path": str(source_image),
                    "learn_all_targets": {
                        "overlay_path": str(overlay),
                        "vista_coordinate_validation": {
                            "validated_count": 2,
                            "failed_count": 0,
                            "batch": {
                                "resumable": False,
                                "completed_count": 2,
                                "remaining_count": 0,
                            },
                        },
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    response = TestClient(app).post(
        "/panel/save_learning_calibration_result",
        json={
            "run_id": "run-panel",
            "trace_path": str(trace_path),
            "source_image_path": str(source_image),
            "numbering_report_path": str(numbering_report),
            "overlay_path": str(overlay),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    result_path = tmp_path / payload["data"]["result_path"]
    assert result_path.exists()
    saved = json.loads(result_path.read_text(encoding="utf-8"))
    assert saved["contract_version"] == "learning_calibration_result_v1"
    assert saved["calibration_summary"]["remaining_count"] == 0


def test_learning_workflow_transition_endpoint_rejects_completion_without_evidence() -> None:
    client = TestClient(app)
    run_id = "run-panel-missing-evidence"
    started = client.post(
        "/panel/transition_learning_workflow_state",
        json={
            "run_id": run_id,
            "expected_revision": 0,
            "stage": "bind_capture",
            "outcome": "running",
        },
    ).json()["data"]["workflow_state"]

    rejected = client.post(
        "/panel/transition_learning_workflow_state",
        json={
            "run_id": run_id,
            "expected_revision": started["revision"],
            "stage": "bind_capture",
            "outcome": "completed",
            "reason": "captured",
            "evidence_refs": {},
        },
    )

    assert rejected.status_code == 200
    assert rejected.json()["success"] is False
    assert "bind_capture completed requires evidence: image_path" in rejected.json()["error"]["details"]
    recovered = client.get(f"/panel/learning_workflow_state/{run_id}").json()
    assert recovered["data"]["workflow_state"]["revision"] == started["revision"]
    assert recovered["data"]["workflow_state"]["stages"]["bind_capture"]["status"] == "running"


def test_learning_workflow_transition_endpoint_verifies_completed_artifact(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    image_path = tmp_path / "artifacts" / "screenshots" / "capture.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"verified capture")
    expected_sha256 = hashlib.sha256(image_path.read_bytes()).hexdigest()
    client = TestClient(app)
    run_id = "run-panel-verified-evidence"
    started = client.post(
        "/panel/transition_learning_workflow_state",
        json={
            "run_id": run_id,
            "expected_revision": 0,
            "stage": "bind_capture",
            "outcome": "running",
        },
    ).json()["data"]["workflow_state"]

    completed = client.post(
        "/panel/transition_learning_workflow_state",
        json={
            "run_id": run_id,
            "expected_revision": started["revision"],
            "stage": "bind_capture",
            "outcome": "completed",
            "reason": "captured",
            "evidence_refs": {
                "image_path": "artifacts/screenshots/capture.png",
                "screenshot_sha256": expected_sha256,
            },
        },
    ).json()

    assert completed["success"] is True
    evidence = completed["data"]["workflow_state"]["current_evidence_refs"]
    assert evidence["evidence_integrity"]["verified"] is True
    assert evidence["evidence_integrity"]["artifacts"]["image_path"]["sha256"] == expected_sha256


def test_learning_workflow_transition_endpoint_rejects_stale_evidence_without_revision_change(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    image_path = tmp_path / "artifacts" / "screenshots" / "capture.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"current capture")
    client = TestClient(app)
    run_id = "run-panel-stale-evidence"
    started = client.post(
        "/panel/transition_learning_workflow_state",
        json={
            "run_id": run_id,
            "expected_revision": 0,
            "stage": "bind_capture",
            "outcome": "running",
        },
    ).json()["data"]["workflow_state"]

    rejected = client.post(
        "/panel/transition_learning_workflow_state",
        json={
            "run_id": run_id,
            "expected_revision": started["revision"],
            "stage": "bind_capture",
            "outcome": "completed",
            "reason": "captured",
            "evidence_refs": {
                "image_path": "artifacts/screenshots/capture.png",
                "screenshot_sha256": "0" * 64,
            },
        },
    ).json()

    assert rejected["success"] is False
    assert rejected["error"]["code"] == "learning_workflow_evidence_invalid"
    recovered = client.get(f"/panel/learning_workflow_state/{run_id}").json()
    state = recovered["data"]["workflow_state"]
    assert state["revision"] == started["revision"]
    assert state["stages"]["bind_capture"]["status"] == "running"


def test_learning_workflow_transition_endpoint_rejects_cross_capture_artifact_without_revision_change(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    bound_image = tmp_path / "artifacts" / "screenshots" / "bound.png"
    stale_image = tmp_path / "artifacts" / "screenshots" / "stale.png"
    bound_image.parent.mkdir(parents=True)
    bound_image.write_bytes(b"bound capture")
    stale_image.write_bytes(b"stale capture")
    stale_sha256 = hashlib.sha256(stale_image.read_bytes()).hexdigest()
    trial_path = tmp_path / "artifacts" / "learning-runs" / "stale-trial.json"
    trial_path.parent.mkdir(parents=True)
    trial_path.write_text(
        json.dumps(
            {
                "observe_bundle": {"source_image_path": str(stale_image)},
                "capture_sha256": stale_sha256,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    client = TestClient(app)
    run_id = "run-panel-cross-capture"

    state = client.post(
        "/panel/transition_learning_workflow_state",
        json={
            "run_id": run_id,
            "expected_revision": 0,
            "stage": "bind_capture",
            "outcome": "running",
        },
    ).json()["data"]["workflow_state"]
    state = client.post(
        "/panel/transition_learning_workflow_state",
        json={
            "run_id": run_id,
            "expected_revision": state["revision"],
            "stage": "bind_capture",
            "outcome": "completed",
            "evidence_refs": {"image_path": str(bound_image)},
        },
    ).json()["data"]["workflow_state"]
    started = client.post(
        "/panel/start_learning_workflow_stage_operation",
        json={
            "run_id": run_id,
            "expected_revision": state["revision"],
            "stage": "screen_understanding",
            "reason": "cross-capture lineage test",
            "lease_seconds": 600,
        },
    ).json()["data"]
    state = started["workflow_state"]

    rejected = client.post(
        "/panel/finish_learning_workflow_stage_operation",
        json={
            "run_id": run_id,
            "expected_revision": state["revision"],
            "stage": "screen_understanding",
            "operation_id": started["operation_id"],
            "outcome": "completed",
            "evidence_refs": {"trial_path": str(trial_path)},
        },
    ).json()

    assert rejected["success"] is False
    assert rejected["error"]["code"] == "learning_workflow_evidence_invalid"
    assert "capture lineage mismatch" in rejected["error"]["details"]
    recovered = client.get(f"/panel/learning_workflow_state/{run_id}").json()
    persisted = recovered["data"]["workflow_state"]
    assert persisted["revision"] == state["revision"]
    assert persisted["stages"]["screen_understanding"]["status"] == "running"


def test_panel_learning_progress_uses_structured_workflow_state() -> None:
    panel_js = (panel_api.PANEL_DIR / "panel.js").read_text(encoding="utf-8")

    assert "/panel/transition_learning_workflow_state" in panel_js
    assert "/panel/learning_workflow_state/" in panel_js
    assert "renderLearningWorkflowState" in panel_js
    assert "expected_revision" in panel_js
    assert "sessionStorage" in panel_js
    assert "previous_state: currentLearningWorkflowState" not in panel_js
    assert 'const failed = ["failed", "blocked", "no usable"' not in panel_js


def test_panel_learning_progress_exposes_detached_runtime_recovery_state() -> None:
    panel_js = (panel_api.PANEL_DIR / "panel.js").read_text(encoding="utf-8")

    render_start = panel_js.index("function renderLearningWorkflowState")
    render_end = panel_js.index("function newLearningWorkflowRunId", render_start)
    render_body = panel_js[render_start:render_end]
    recover_start = panel_js.index("async function recoverLearningWorkflowState")
    recover_end = panel_js.index("async function restoreLearningWorkflowState", recover_start)
    recover_body = panel_js[recover_start:recover_end]

    assert '["data", "runtime_attachment"]' in recover_body
    assert '"running_detached"' in render_body
    assert '"recovery_required"' in render_body
    assert '"worker_finished"' in render_body
    assert '"result_available"' in render_body
    assert '"result_adopted"' in render_body
    assert "continuation_required" in render_body


def test_panel_image_frame_clears_transient_missing_state_after_image_loads() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8")

    start = panel_js.index("function panelImageHtml")
    body = panel_js[start:panel_js.index("\nfunction ", start + 1)]

    assert "onerror=" in body
    assert "onload=" in body
    assert "classList.remove('image-missing')" in body


def test_saved_workflow_status_counts_formal_interface_nodes() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8")

    start = panel_js.index("function renderInterfaceWorkflowReviewSelection")
    body = panel_js[start:panel_js.index("\nfunction ", start + 1)]

    assert "graph.nodes.length" in body
    assert "个流程界面" in body
    assert "个历史界面" not in body


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
    assert 'encodeURIComponent(profileId)' in response.text
    assert 'GET /runtime/models?profile_id=' in response.text
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
    assert "/panel/surface_rule_registry" in response.text
    assert "loadLearningCorrectionMemoryRegistry" in response.text
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


def test_panel_surface_rule_registry_endpoint_is_read_only_and_safe(monkeypatch) -> None:
    client = TestClient(app)
    expected = {
        "contract_version": "panel_surface_rule_registry_v1",
        "status_counts": {"candidate": 1},
        "rules": [{"rule_id": "surface_correction_demo", "status": "candidate"}],
        "candidate_rules_affect_production": False,
        "production_rule_policy": "active_only",
        "model_activation_allowed": False,
        "no_click_authorization": True,
    }
    monkeypatch.setattr(panel_api, "build_surface_rule_registry_panel_view", lambda **kwargs: expected)

    response = client.get("/panel/surface_rule_registry")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"] == expected
    assert body["error"] is None


def test_learning_correction_memory_refreshes_after_human_review_save() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    save_start = panel_js.index("async function saveLearningDraftReview")
    save_end = panel_js.index("async function generatePathGraphCandidate", save_start)
    save_body = panel_js[save_start:save_end]

    assert 'api("GET", "/panel/surface_rule_registry"' in panel_js
    assert 'void loadLearningCorrectionMemoryRegistry({ skipResponse: true })' in save_body
    assert "Reviewed template candidate loaded, but CorrectionMemory refresh failed" in save_body
    assert 'on("learningCorrectionMemoryRefreshBtn", "click", loadLearningCorrectionMemoryRegistry)' in panel_js


def test_learning_draft_box_save_refreshes_parent_before_closing_editor() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    save_start = panel_js.index("async function saveLearningDraftReview")
    save_end = panel_js.index("async function generatePathGraphCandidate", save_start)
    save_body = panel_js[save_start:save_end]
    refresh_start = panel_js.index("async function refreshSavedLearningDraftReview")
    refresh_end = panel_js.index("async function refreshCurrentInterfaceWorkflowEvidence", refresh_start)
    refresh_body = panel_js[refresh_start:refresh_end]

    saving_index = save_body.index('apply.textContent = "Saving review..."')
    refresh_index = save_body.index("await refreshSavedLearningDraftReview({")
    workflow_refresh_index = save_body.index("reviewedPath,")
    close_index = save_body.index("closeImageInspector()")
    correction_index = save_body.index("void loadLearningCorrectionMemoryRegistry({ skipResponse: true })")

    assert saving_index < refresh_index < workflow_refresh_index < close_index < correction_index
    assert "setLearningDraftReviewSourcePath(sourcePath)" in refresh_body
    assert 'const reviewedPath = String(data.reviewed_template_candidate_path || "").trim()' in save_body
    assert "Reviewed template candidate save response is missing reviewed_template_candidate_path" in save_body
    assert "try {" in save_body
    assert "} finally {" in save_body
    assert 'apply.textContent = saveSucceeded ? "Saved" : "Save review";' in save_body
    assert "apply.disabled = false" in save_body
    assert "previousSourcePath: sourcePath" in save_body
    assert "discoverRelatedSidecars: false" in panel_js
    assert "supersedePendingLoad: true" in panel_js
    assert "skipReviewRender: true" in panel_js
    assert "if (!refreshed?.review)" in save_body
    assert "binding === true" in refresh_body
    assert 'binding === "not_bound"' in refresh_body
    assert "return null;" in refresh_body


def test_interface_workflow_exposes_manual_current_evidence_refresh() -> None:
    index_html = Path("app/web_panel/index.html").read_text(encoding="utf-8")
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    assert 'id="interfaceWorkflowRefreshEvidenceBtn"' in index_html
    assert "刷新当前证据" in index_html
    assert "async function refreshCurrentInterfaceWorkflowEvidence" in panel_js
    assert (
        'on("interfaceWorkflowRefreshEvidenceBtn", "click", '
        "refreshCurrentInterfaceWorkflowEvidence)"
    ) in panel_js
    refresh_start = panel_js.index("async function refreshCurrentInterfaceWorkflowEvidence")
    refresh_end = panel_js.index("\n}\n", refresh_start) + len("\n}")
    refresh_body = panel_js[refresh_start:refresh_end]
    shared_refresh_start = panel_js.index("async function refreshSavedLearningDraftReview")
    shared_refresh_end = panel_js.index("\n}\n", shared_refresh_start) + len("\n}")
    shared_refresh_body = panel_js[shared_refresh_start:shared_refresh_end]
    assert "refreshSavedLearningDraftReview({" in refresh_body
    assert "applyReviewedEvidenceToCurrentWorkflowNode" in shared_refresh_body
    assert "saveInterfaceWorkflowReview({ commitEditor: false })" in shared_refresh_body
    assert "loadInterfaceWorkflowReview" not in shared_refresh_body
    assert "discoverRelatedSidecars: false" in shared_refresh_body
    assert "supersedePendingLoad: true" in shared_refresh_body
    assert "skipReviewRender: true" in shared_refresh_body


def test_learning_results_entry_splits_workflows_by_interface_review_status() -> None:
    index_html = Path("app/web_panel/index.html").read_text(encoding="utf-8")
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    assert 'id="interfaceAssetUnreviewedPage"' in index_html
    assert 'id="interfaceAssetReviewedPage"' in index_html
    assert 'id="interfaceWorkflowUnreviewedList"' in index_html
    assert 'id="interfaceWorkflowReviewedList"' in index_html
    assert "未审核" in index_html
    assert "已审核" in index_html
    assert "function renderInterfaceWorkflowReviewGroups" in panel_js
    assert "buildInterfaceAssetLibrary" in panel_js
    assert "openInterfaceWorkflowReviewGroupNode" in panel_js
    assert 'class="interface-workflow-existing-selector"' in index_html
    assert 'class="interface-workflow-existing-selector" hidden' not in index_html
    assert "选择已有软件 / 网站流程" in index_html
    assert "打开所选流程" in index_html

    page_start = panel_js.index("function showInterfaceAssetPage(page)")
    page_end = panel_js.index("\nfunction setInterfaceWorkflowLibraryOptions", page_start)
    page_body = panel_js[page_start:page_end]
    assert "renderInterfaceWorkflowReviewGroups();" not in page_body


def test_single_interface_review_uses_exact_source_without_sidecar_rescan() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    start = panel_js.index("async function previewInterfaceWorkflowSource()")
    end = panel_js.index("\nasync function addInterfaceWorkflowSource", start)
    body = panel_js[start:end]

    assert "discover_related_sidecars: false" in body


def test_workflow_graph_explains_review_state_without_implying_authorization() -> None:
    index_html = Path("app/web_panel/index.html").read_text(encoding="utf-8")
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    assert "已审核界面" in index_html
    assert "未审核界面" in index_html
    assert "证据无效" in index_html
    assert "橙色虚线路径需要人工审核" in index_html
    assert "summarizeWorkflowReadiness" in panel_js
    assert "仍非执行授权" in panel_js


def test_learning_draft_box_editor_exposes_agent_semantics_and_destination_controls() -> None:
    index_html = Path("app/web_panel/index.html").read_text(encoding="utf-8")

    for control_id in (
        "imageInspectorLabel",
        "imageInspectorDescription",
        "imageInspectorActionTypeSelect",
        "imageInspectorInputSemantics",
        "imageInspectorDestinationKind",
        "imageInspectorDestinationValue",
        "imageInspectorVerificationRule",
        "imageInspectorRiskLevel",
    ):
        assert f'id="{control_id}"' in index_html


def test_learning_draft_box_editor_exposes_blocked_external_apply_action() -> None:
    index_html = Path("app/web_panel/index.html").read_text(encoding="utf-8")

    action_select_start = index_html.index('id="imageInspectorActionTypeSelect"')
    action_select_end = index_html.index("</select>", action_select_start)
    action_select = index_html[action_select_start:action_select_end]
    assert '<option value="open_external_apply">open_external_apply (blocked)</option>' in action_select


def test_learning_draft_panel_exposes_reviewed_memory_execute_acceptance_controls() -> None:
    index_html = Path("app/web_panel/index.html").read_text(encoding="utf-8")

    assert 'id="learningOperationalMemoryPanel"' in index_html
    assert 'id="learningMemoryInterfaceId"' in index_html
    assert 'id="learningMemoryActionSelect"' in index_html
    assert 'id="learningMemoryPublishBtn"' in index_html
    assert 'id="learningMemoryLoadBtn"' in index_html
    assert 'id="learningMemoryDryRunBtn"' in index_html
    assert 'id="learningMemoryExecuteBtn"' in index_html
    assert 'id="learningMemoryReturnToEditBtn"' in index_html


def test_generic_learning_panel_hides_seek_continuous_task_handoff_controls() -> None:
    index_html = Path("app/web_panel/index.html").read_text(encoding="utf-8")
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8")

    assert 'id="continuousTaskHandoffPanel"' not in index_html
    assert 'id="continuousTaskRunDir"' not in index_html
    assert 'id="continuousTaskUseForLearningBtn"' not in index_html
    assert 'id="continuousTaskResumeBtn"' not in index_html
    assert "/panel/continuous_task_handoff" in panel_js
    assert "/panel/resume_continuous_task" in panel_js
    boot_start = panel_js.index("async function boot()")
    boot_body = panel_js[boot_start:panel_js.index("boot();", boot_start)]
    assert "loadContinuousTaskHandoff" not in boot_body


def test_learning_draft_reviewed_memory_execution_requires_fresh_runtime_resolution() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    start = panel_js.index("async function executeLearningOperationalMemory")
    end = panel_js.index("function returnLearningOperationalMemoryToReview", start)
    body = panel_js[start:end]

    assert "interface_memory_id" in body
    assert "interface_memory_action_id" in body
    assert "capture_live: true" in body
    assert "max_execution_attempts: 1" in body
    assert "approved_plan_id" not in body
    assert '"/action/execute_recognition_plan"' in body


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
        "review_repair",
        "fusion",
        "pathgraph_draft",
        "complete",
    ]:
        assert f'data-learning-flow-step="{step}"' in html

    flow_steps_match = re.search(
        r"const LEARNING_INTERFACE_FLOW_STEPS = \[(.*?)\];",
        panel_js,
        flags=re.DOTALL,
    )
    assert flow_steps_match is not None
    assert re.findall(r'"([a-z_]+)"', flow_steps_match.group(1)) == [
        "bind_capture",
        "screen_understanding",
        "numbered_map",
        "precise_calibration",
        "review_repair",
        "fusion",
        "page_details",
        "pathgraph_draft",
        "complete",
    ]

    assert 'id="learningDraftHistoryList"' in html
    assert 'id="learningDraftScreenshotPanel"' in html
    assert 'id="learningDraftPathGraphPanel"' in html
    assert 'id="learningDraftPathResizer"' in html
    assert 'id="learningDraftPathLayoutResetBtn"' in html
    assert 'id="learningDraftInterfaceDetailPanel"' in html
    assert 'id="learningDraftManualEditPanel"' in html
    assert (
        '<details class="learning-review-section learning-screen-preview-section" '
        'id="learningDraftScreenUnderstandingDiagnostics">'
    ) in html
    assert re.search(
        r"\.learning-draft-pathgraph-panel\s*\{[^}]*order:\s*3;",
        panel_css,
        flags=re.DOTALL,
    )
    assert re.search(
        r"\.learning-review-panel\s*\{[^}]*order:\s*4;",
        panel_css,
        flags=re.DOTALL,
    )
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
    assert "function renderLearningWorkflowState" in panel_js
    assert "async function transitionLearningWorkflowState" in panel_js
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
    assert "function nextLearningStageOperation" in panel_js
    assert '"panel_learning_two_stage_understanding"' in panel_js
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
    assert "/panel/continue_learning_stage_worker_result" in panel_js
    assert 'renderLearningDraftScreenshotPath(overlayPath, "learning two-stage fused overlay")' in panel_js
    numbered_map_start = panel_js.index("function learningDraftNumberedMapImagePath")
    numbered_map_body = panel_js[numbered_map_start:panel_js.index("function renderLearningDraftScreenshotPath", numbered_map_start)]
    assert numbered_map_body.index("preview.compiled_overlay_path") < numbered_map_body.index("learningDraftSourceImagePath(draft)")
    assert "draft?.page_details?.precise_understanding_fusion_status?.compiled_overlay_path" in panel_js
    assert numbered_map_body.index("draft?.page_details?.screen?.compiled_overlay_path") < numbered_map_body.index(
        "learningDraftSourceImagePath(draft)"
    )
    assert "filtered_non_actionable" in panel_js
    assert "backend-managed stage chain completed · draft only" in panel_js
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
    assert "target_region_id: manualCandidate.targetRegionId" in panel_js
    assert "target_action_template_id: manualCandidate.targetActionTemplateId" in panel_js
    assert "async function refreshSavedLearningDraftReview" in panel_js
    assert "discoverRelatedSidecars: false" in panel_js
    assert "Reviewed template candidate saved, but panel refresh failed" in panel_js
    assert ".learning-interface-prep-card" in panel_css
    assert ".learning-interface-flow-card" in panel_css
    assert ".learning-draft-review-workspace" in panel_css
    assert ".learning-draft-screenshot-frame" in panel_css
    assert re.search(r"\.learning-review-panel\s*\{[^}]*grid-column:\s*1\s*/\s*-1;", panel_css)
    assert "max-height: none" in panel_css
    assert "max-height: 360px" not in panel_css

    resize_start = panel_js.index("function bindLearningDraftPathResize")
    resize_end = panel_js.index("function renderLearningDraftPathPreview", resize_start)
    resize_body = panel_js[resize_start:resize_end]
    assert 'resizer.addEventListener("pointerdown"' in resize_body
    assert 'resizer.addEventListener("pointermove"' in resize_body
    assert "resizer.setPointerCapture?.(event.pointerId)" in resize_body
    assert 'resizer.addEventListener("keydown"' in resize_body
    assert 'event.key === "Home"' in resize_body
    assert 'event.key === "End"' in resize_body

    spatial_start = panel_js.index("function renderLearningPageDetailSpatialMap")
    spatial_end = panel_js.index("function renderLearningPageDetailSpatialSections", spatial_start)
    spatial_body = panel_js[spatial_start:spatial_end]
    assert 'style="aspect-ratio:${width}/${height};"' in spatial_body

    region_start = panel_js.index("function renderLearningPageDetailSpatialRegion")
    region_end = panel_js.index("function renderLearningPageDetailSections", region_start)
    region_body = panel_js[region_start:region_end]
    assert "(Number(bbox.w || 1) / layout.width) * 100" in region_body
    assert "(Number(bbox.h || 1) / layout.height) * 100" in region_body
    assert ".learning-page-layout-map" in panel_css
    assert "overflow: hidden" in panel_css


def test_learning_mode_sidebar_exposes_one_learning_workspace_and_keeps_internal_tools_hidden() -> None:
    html = Path("app/web_panel/index.html").read_text(encoding="utf-8")
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8")
    panel_css = Path("app/web_panel/panel.css").read_text(encoding="utf-8")

    assert html.count('data-stage="learn_interface"') == 1
    assert 'data-i18n="nav_learn_interface"' in html
    assert 'data-stage="learn_interface" data-step="1"' in html
    assert 'data-stage="template_display"' not in html
    assert 'data-stage="trace"' not in html
    assert 'data-stage="learn_validation"' not in html
    assert 'data-stage="execute_task_run"' not in html
    assert 'data-stage="execute_locate" data-step="2"' in html
    assert 'data-learn-replay-view=' not in html
    assert '<section class="learn-replay-subview active" data-learn-replay-panel="draft">' in html
    assert '<details class="replay-advanced-tools">' in html
    assert 'data-i18n="nav_learn_replay"' not in html
    assert 'data-i18n="nav_learn_observe"' not in html
    assert 'data-i18n="nav_learn_locate"' not in html
    assert "学习产物回放" not in html
    assert "body.agent-mode-learn .nav-group-system" in panel_css
    assert "body.agent-mode-learn .policy-strip" in panel_css
    assert "body.agent-mode-learn .page-meta-strip" in panel_css
    assert "body.agent-mode-learn .response-surface" in panel_css
    assert "body.agent-mode-learn .content-grid" in panel_css
    assert 'body.learn-replay-draft-subview .stage-page[data-page="learn_replay"] > h3' in panel_css
    assert "body.learn-replay-draft-subview .learning-draft-history-panel" in panel_css
    assert "body.learn-replay-draft-subview .learning-draft-screenshot-panel" in panel_css
    assert "body.learn-replay-draft-subview #learningDraftReviewPanel" in panel_css
    assert "body.learn-replay-draft-subview #learningDraftPathGraphPanel" in panel_css

    assert 'learn_interface: {' in panel_js
    assert 'template_display: {' in panel_js
    assert 'learnReplaySubview: "draft"' in panel_js
    assert 'learnReplaySubview: "template"' in panel_js
    assert 'let currentLearnReplaySubview = "draft";' in panel_js
    assert 'on("agentModeLearnBtn", "click", () => showStage("learn_interface"))' in panel_js
    assert 'if (page === "learn_replay" && meta.learnReplaySubview)' in panel_js


def test_learning_workspace_stacks_graph_evidence_and_on_demand_inspector() -> None:
    panel_css = Path("app/web_panel/panel.css").read_text(encoding="utf-8")

    assert "grid-template-columns: minmax(0, 1fr);" in panel_css
    assert ".interface-workflow-inspector-panel[hidden]" in panel_css
    assert "display: none;" in panel_css
    assert "@media (max-width: 1500px)" in panel_css
    responsive_start = panel_css.index("@media (max-width: 1500px)")
    responsive_end = panel_css.index("@media (max-width: 980px)", responsive_start)
    responsive_body = panel_css[responsive_start:responsive_end]
    assert ".interface-workflow-node-workspace" in responsive_body
    assert "grid-template-columns: minmax(0, 1fr);" in responsive_body
    assert ".interface-workflow-inspector-panel" in responsive_body
    assert "grid-column: auto;" in responsive_body


def test_panel_api_response_result_helper_preserves_two_stage_gate_data() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    result_of_start = panel_js.index("function resultOf(response)")
    result_of_body = panel_js[result_of_start:panel_js.index("function statusTextForResponse", result_of_start)]
    assert 'response.data !== null' in result_of_body
    assert 'response.result !== null' in result_of_body
    assert "if (Object.keys(result).length) return result;" in result_of_body
    assert "if (Object.keys(data).length) return data;" in result_of_body

    allows_start = panel_js.index("function learningTwoStageAllowsDraftTrial")
    allows_body = panel_js[allows_start:panel_js.index("async function runLearningTwoStageUnderstanding", allows_start)]
    assert 'nestedGet(result, ["stage1_gate", "status"])' in allows_body
    assert 'gateStatus === "passed"' in allows_body
    assert 'nestedGet(result, ["stage2_numbering_skipped"]) !== true' in allows_body


def test_panel_two_stage_endpoint_forwards_explicit_source_image_override(monkeypatch, tmp_path) -> None:
    client = TestClient(app)
    override_image = tmp_path / "override.png"
    Image.new("RGB", (111, 77), "white").save(override_image)
    captured_input = {}

    def fake_run(task_input, *, project_root):
        captured_input.update(task_input.model_dump())
        return LearningTaskResult(
            outcome="completed",
            payload={
                "contract_version": "panel_learning_two_stage_understanding_run_v1",
                "source_image_override": {
                    "status": "applied",
                    "original_path": "artifacts/screenshots/stale.png",
                    "path": str(override_image),
                },
                "image_path": str(override_image),
                "summary": {"stage2_calibration_candidate_count": 3},
                "learn_all_targets": {
                    "stage2_calibration_candidate_count": 3,
                },
            },
        )

    monkeypatch.setattr(
        panel_api,
        "run_two_stage_understanding_task",
        fake_run,
    )

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
    assert captured_input["source_image_path"] == str(override_image)
    assert data["source_image_override"]["status"] == "applied"
    assert data["source_image_override"]["original_path"] == "artifacts/screenshots/stale.png"
    assert data["image_path"] == str(override_image)
    assert data["summary"]["stage2_calibration_candidate_count"] == 3
    assert data["learn_all_targets"]["stage2_calibration_candidate_count"] == 3


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


def test_panel_status_text_treats_calibration_targets_as_ready() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    status_start = panel_js.index("function statusTextForResponse")
    status_body = panel_js[status_start:panel_js.index("function nestedGet", status_start)]

    assert "const calibrationTargetCount" in status_body
    assert "targetCount <= 0 && calibrationTargetCount <= 0" in status_body
    assert status_body.index("calibrationTargetCount") < status_body.index('return "no_targets";')


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
    assert 'nestedGet(result, ["learn_all_targets", "calibration_targets"])' in evidence_body
    assert 'nestedGet(result, ["learn_all_targets", "vista_coordinate_validation"])' in evidence_body
    assert "const calibrationEvidenceTargets = [...learnTargets, ...calibrationTargets]" in evidence_body
    assert "calibrated_targets: compactLearningDraftTargets(calibrationEvidenceTargets, 96)" in evidence_body
    assert "vista_validated_count" in evidence_body
    assert "vista_outside_count" in evidence_body
    assert "vista_needs_review_count" in evidence_body
    assert "vista_skipped_count" in evidence_body


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
    assert "payload.metadata.two_stage_report_path = calibrationSourceReportPath" in calibration_body
    assert "payload.metadata.final_numbering_revision" not in calibration_body
    assert "payload.metadata.review_repair_integrity_gate_passed" not in calibration_body
    assert "payload.metadata.learn_vista_coordinate_validation" not in calibration_body
    assert '"learning_calibration_sequence_request_v1"' in calibration_body
    assert '"panel_learning_calibration_sequence"' in calibration_body
    assert "locate_payload: payload" in calibration_body

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

    assert "followContinuationChain: true" in flow_body
    assert "runLearningDeepCalibration(" not in flow_body
    assert "runLearningDraftTrial(" not in flow_body
    assert "function backendContinuationStageWorker" in panel_js
    assert 'taskKind === "panel_learning_calibration_sequence"' in panel_js
    assert 'taskKind === "panel_learning_recognition_trial"' in panel_js


def test_learning_interface_bind_capture_is_model_free() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    capture_start = panel_js.index("async function captureLearningDraftWindow")
    capture_end = panel_js.index("async function runLearningScreenObserve", capture_start)
    capture_body = panel_js[capture_start:capture_end]
    flow_start = panel_js.index("async function runLearningInterfaceFlow")
    flow_body = panel_js[flow_start:panel_js.index("async function completeLearningInterfaceReadonlyFlow", flow_start)]
    screen_operation_start = flow_body.index(
        'const screenUnderstandingOperation = await startLearningWorkflowStageOperation'
    )
    bind_capture_body = flow_body[:screen_operation_start]

    assert '"/state/capture_window"' in capture_body
    assert 'ensureStageModelReady("observe"' not in capture_body
    assert '"/vision/observe_screen"' not in capture_body
    assert 'ensureStageModelReady("observe"' not in bind_capture_body
    assert '"vision_observe_screen"' not in bind_capture_body


def test_learning_interface_screen_understanding_operation_owns_observe_and_draft() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    observe_start = panel_js.index("async function runLearningScreenObserve")
    observe_end = panel_js.index("function renderLearningWorkflowState", observe_start)
    observe_body = panel_js[observe_start:observe_end]
    flow_start = panel_js.index("async function runLearningInterfaceFlow")
    flow_body = panel_js[flow_start:panel_js.index("async function completeLearningInterfaceReadonlyFlow", flow_start)]
    operation_start = flow_body.index(
        'const screenUnderstandingOperation = await startLearningWorkflowStageOperation'
    )
    operation_body = flow_body[operation_start:]

    assert 'ensureStageModelReady("observe", profileId, { signal: options.signal })' in observe_body
    assert '"vision_observe_screen"' in observe_body
    assert "capture_live: false" in observe_body
    assert "image_path: sourceImagePath" in observe_body
    assert "operation: options.operation" in observe_body
    assert "return runLearningScreenObserve({" in operation_body
    assert "followContinuationChain: true" in operation_body
    assert "runLearningDraftTrial(" not in operation_body
    assert "learningStageContinuationFinished(trialResponse)" in operation_body
    assert 'learningStageContinuation(trialResponse).outcome === "completed"' in operation_body


def test_learning_interface_records_coordinate_overlay_fusion_provenance() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    evidence_start = panel_js.index("function buildLearningDraftObservationEvidence")
    evidence_body = panel_js[evidence_start:panel_js.index("function setLearningTrialResultPath", evidence_start)]
    assert "const coordinateOverlay = nestedGet(result, [\"learn_all_targets\", \"overlay\"])" in evidence_body
    assert "coordinate_overlay: {" in evidence_body
    assert 'base_visual_source: String(coordinateOverlay.base_visual_source || "")' in evidence_body
    assert "final_fusion_overlay: coordinateOverlay.final_fusion_overlay === true" in evidence_body


def test_learning_interface_passes_selected_grounding_profile_without_changing_default() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    assert 'locate: "vista_4b_transformers"' in panel_js
    assert 'const DEFAULT_LEARNING_GROUNDING_PROFILE_ID = "learn_mode_uground_2b";' not in panel_js

    calibration_start = panel_js.index("async function runLearningDeepCalibration")
    calibration_body = panel_js[calibration_start:panel_js.index("function learningTwoStageUnderstandingPayload", calibration_start)]
    assert 'const profile = syncStageProvider("locate");' in calibration_body
    assert "payload.metadata.learn_grounding_profile_id = profileId;" in calibration_body


def test_learning_interface_fusion_uses_dedicated_latest_calibration_response() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    assert "let lastLearningDeepCalibrationResponse = null;" in panel_js

    clear_start = panel_js.index("function clearLearningDraftWorkspaceForNewRun")
    clear_body = panel_js[clear_start:panel_js.index("function activeStagePage", clear_start)]
    assert "lastLearningDeepCalibrationResponse = null;" in clear_body

    calibration_start = panel_js.index("async function runLearningDeepCalibration")
    calibration_body = panel_js[calibration_start:panel_js.index("function learningTwoStageUnderstandingPayload", calibration_start)]
    assert "lastLearningDeepCalibrationResponse = response;" in calibration_body

    evidence_start = panel_js.index("function buildLearningDraftObservationEvidence")
    evidence_body = panel_js[evidence_start:panel_js.index("function setLearningTrialResultPath", evidence_start)]
    assert "resultOf(lastLearningDeepCalibrationResponse || lastResponse)" in evidence_body
    assert "calibration_evidence_source" in evidence_body


def test_learning_interface_flow_stops_before_calibration_when_stage1_gate_blocks() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    flow_start = panel_js.index("async function runLearningInterfaceFlow")
    flow_body = panel_js[flow_start:panel_js.index("async function completeLearningInterfaceReadonlyFlow", flow_start)]
    assert "runLearningDeepCalibration(" not in flow_body
    assert "backendContinuationStageWorker(continuationData)" in panel_js
    assert "if (!operation && !worker) return null" in panel_js
    assert "if (!managedChainCompleted) return trialResponse" in flow_body


def test_learning_interface_flow_keeps_latest_fused_review_overlay() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    flow_start = panel_js.index("async function runLearningInterfaceFlow")
    flow_body = panel_js[flow_start:panel_js.index("async function completeLearningInterfaceReadonlyFlow", flow_start)]
    overlay_render = 'renderLearningDraftScreenshotPath(overlayPath, "learning two-stage fused overlay")'
    handler_start = panel_js.index("async function applyManagedLearningStageWorkerResponse")
    handler_end = panel_js.index("async function runLearningInterfaceFlow", handler_start)
    handler_body = panel_js[handler_start:handler_end]

    assert handler_body.count(overlay_render) == 1
    assert "lastLearningFinalReviewedOverlayPath" in flow_body


def test_learning_interface_precise_calibration_reports_live_progress_and_stops_on_failure() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    calibration_start = panel_js.index("async function runLearningDeepCalibration")
    calibration_end = panel_js.index("function learningTwoStageUnderstandingPayload", calibration_start)
    calibration_body = panel_js[calibration_start:calibration_end]
    assert "runLearningCalibrationProgress" in calibration_body
    assert '"learning_flow_calibration_loading_model"' in calibration_body
    assert '"learning_flow_calibration_running_chain"' in calibration_body
    assert "learningCalibrationTimeoutSeconds" in calibration_body
    assert "learningCalibrationTimeoutSeconds(candidateCount)" in calibration_body
    assert 'learning_flow_calibration_loading_model: "正在检查 / 加载定位模型"' in panel_js
    assert 'learning_flow_calibration_loading_model: "Checking / loading locator model"' in panel_js
    assert 'learning_flow_calibration_running_chain: "正在执行 OCR + VISTA + rerank + gate dry-run"' in panel_js
    assert 'learning_flow_calibration_running_chain: "Running OCR + VISTA + rerank + gate dry-run"' in panel_js
    assert "batchAborted" in panel_js
    assert "learn_calibration_blocked" in panel_js
    assert 'taskKind === "panel_learning_calibration_sequence"' in panel_js
    assert "lastLearningDeepCalibrationResponse = response" in panel_js

    progress_start = panel_js.index("async function runLearningCalibrationProgress")
    progress_end = panel_js.index("async function runLearningDeepCalibration", progress_start)
    progress_body = panel_js[progress_start:progress_end]
    assert "candidateCount" in progress_body
    assert 't("learning_flow_calibration_candidate_count")' in progress_body
    assert 'learning_flow_calibration_candidate_count: "编号候选"' in panel_js
    assert 'learning_flow_calibration_candidate_count: "numbered candidates"' in panel_js

    assert "learningTwoStageCalibrationTargetCount" in calibration_body
    assert "const candidateCount = learningTwoStageCalibrationTargetCount()" in calibration_body
    assert "{ candidateCount }" in calibration_body

    timeout_start = panel_js.index("function learningCalibrationTimeoutSeconds")
    timeout_end = panel_js.index("function learningTwoStageCalibrationTargetCount", timeout_start)
    timeout_body = panel_js[timeout_start:timeout_end]
    assert "count * 20 + 60" in timeout_body
    assert "900" in timeout_body

    flow_start = panel_js.index("async function runLearningInterfaceFlow")
    flow_end = panel_js.index("async function completeLearningInterfaceReadonlyFlow", flow_start)
    flow_body = panel_js[flow_start:flow_end]
    failure_start = flow_body.index("if (!trialResponse?.success)")
    failure_end = flow_body.index("if (!learningStageContinuationFinished", failure_start)
    failure_body = flow_body[failure_start:failure_end]
    assert "completeLearningInterfaceReadonlyFlow" not in failure_body
    assert "recoverLearningWorkflowState" in failure_body
    assert "return trialResponse" in failure_body
    assert "runLearningDeepCalibration(" not in flow_body


def test_learning_interface_uses_actual_calibration_candidate_count_for_progress() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    count_start = panel_js.index("function learningTwoStageCalibrationTargetCount")
    count_end = panel_js.index("async function runLearningCalibrationProgress", count_start)
    count_body = panel_js[count_start:count_end]

    assert '["stage2_numbering", "calibration_candidate_count"]' in count_body
    assert count_body.index('calibration_candidate_count') < count_body.index('numbered_item_count')
    assert "const explicitCandidateCount" in count_body
    assert "explicitCandidateCount ?? numberedItemCount" in count_body
    assert "calibration_candidate_count\"]\n      ||" not in count_body


def test_learning_interface_precise_calibration_is_revision_bound_and_resumable() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    calibration_start = panel_js.index("async function runLearningDeepCalibration")
    calibration_end = panel_js.index("function learningTwoStageUnderstandingPayload", calibration_start)
    calibration_body = panel_js[calibration_start:calibration_end]
    assert "LEARNING_CALIBRATION_BATCH_SIZE" in panel_js
    assert '"learning_calibration_sequence_request_v1"' in calibration_body
    assert "candidate_count: candidateCount" in calibration_body
    assert "calibration_source_revision: calibrationSourceRevision" in calibration_body
    assert "maximum_batch_size: LEARNING_CALIBRATION_BATCH_SIZE" in calibration_body
    assert "locate_payload: payload" in calibration_body
    assert "resumeResults" not in calibration_body
    assert "for (let batchIndex" not in calibration_body
    assert '"vision_locate_target"' not in calibration_body


def test_learning_interface_uses_backend_calibration_artifact_continuation() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    flow_start = panel_js.index("async function runLearningInterfaceFlow")
    flow_end = panel_js.index("async function completeLearningInterfaceReadonlyFlow", flow_start)
    flow_body = panel_js[flow_start:flow_end]
    assert "saveLearningCalibrationResult(" not in panel_js
    assert '"/panel/save_learning_calibration_result"' not in panel_js
    assert "followContinuationChain: true" in flow_body
    assert "backendContinuationStageWorker(continuationData)" in panel_js
    assert 'taskKind === "panel_learning_calibration_sequence"' in panel_js


def test_learning_interface_checks_resources_before_starting_real_locator_model() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    calibration_start = panel_js.index("async function runLearningDeepCalibration")
    calibration_end = panel_js.index("function learningTwoStageUnderstandingPayload", calibration_start)
    calibration_body = panel_js[calibration_start:calibration_end]

    assert "async function learningModelResourcePreflight" in panel_js
    assert "/runtime/models/resource_preflight?" in panel_js
    assert "recommended_batch_size" in panel_js
    assert calibration_body.index("learningModelResourcePreflight") < calibration_body.index("ensureStageModelReady")
    assert "const calibrationBatchSize =" not in calibration_body
    assert "maximum_batch_size: LEARNING_CALIBRATION_BATCH_SIZE" in calibration_body
    assert "batchResourcePreflight" not in calibration_body
    assert "learningCalibrationTimeoutSeconds(candidateCount)" in calibration_body
    assert 'learning_flow_calibration_checking_resources: "正在检查 GPU / 内存占用"' in panel_js
    assert 'learning_flow_calibration_checking_resources: "Checking GPU / memory use"' in panel_js


def test_learning_calibration_batch_recovery_is_backend_owned() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    calibration_start = panel_js.index("async function runLearningDeepCalibration")
    calibration_end = panel_js.index("function learningTwoStageUnderstandingPayload", calibration_start)
    calibration_body = panel_js[calibration_start:calibration_end]

    assert '"panel_learning_calibration_sequence"' in calibration_body
    assert "fallbackPath:" not in calibration_body
    assert "for (let batchIndex" not in calibration_body
    assert "learningVistaRetryableAbortReason" not in panel_js
    assert "learningVistaCompletedResumeResults" not in panel_js
    assert "waitForStageModelIdle" not in panel_js
    assert '"vision_locate_target"' not in calibration_body


def test_learning_calibration_resume_compaction_is_not_frontend_owned() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    assert "function learningVistaResumeResultForTransport" not in panel_js
    assert "function learningVistaCompletedResumeResults" not in panel_js


def test_every_learning_model_inference_checks_resources_before_real_model_call() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    preflight_start = panel_js.index("async function learningModelResourcePreflight")
    preflight_end = panel_js.index("async function runLearningCalibrationProgress", preflight_start)
    preflight_body = panel_js[preflight_start:preflight_end]
    assert "new URLSearchParams({ stage })" in preflight_body

    ensure_start = panel_js.index("async function ensureStageModelReady")
    ensure_end = panel_js.index("async function applyModelProfile", ensure_start)
    ensure_body = panel_js[ensure_start:ensure_end]
    assert "options.resourcePreflight" in ensure_body
    assert "learningModelResourcePreflight(stage, profileId, { signal: options.signal })" in ensure_body
    assert ensure_body.index("learningModelResourcePreflight") < ensure_body.index("/runtime/models?")
    assert 'resourcePreflight.resourceMode === "critical"' in ensure_body
    assert "resourcePreflight.modelLaunchAllowed === false" in ensure_body
    assert ensure_body.index('resourcePreflight.resourceMode === "critical"') < ensure_body.index("/runtime/models?")
    assert "model_start_blocked_by_resource_preflight" in ensure_body

    assert "model_launch_allowed" in preflight_body
    assert "reason_codes" in preflight_body

    draft_start = panel_js.index("async function runLearningDraftTrial")
    draft_end = panel_js.index("function learningReviewLabel", draft_start)
    draft_body = panel_js[draft_start:draft_end]
    assert draft_body.index('ensureStageModelReady("observe"') < draft_body.index(
        'runManagedLearningStageWorker('
    )
    assert '"panel_learning_recognition_trial"' in draft_body
    assert 'fallbackPath: "/panel/run_learning_recognition_trial"' in draft_body

    stage2_start = panel_js.index("async function runLearningTwoStageUnderstanding")
    stage2_end = panel_js.index("async function runLearningModelReviewRepair", stage2_start)
    stage2_body = panel_js[stage2_start:stage2_end]
    assert stage2_body.index('ensureStageModelReady("observe"') < stage2_body.index(
        'runManagedLearningStageWorker('
    )
    assert '"panel_learning_two_stage_understanding"' in stage2_body
    assert 'fallbackPath: "/panel/run_learning_two_stage_understanding"' in stage2_body

    review_start = panel_js.index("async function runLearningModelReviewRepair")
    review_end = panel_js.index("async function runLearningInterfaceFlow", review_start)
    review_body = panel_js[review_start:review_end]
    assert review_body.index('ensureStageModelReady("observe"') < review_body.index(
        'runManagedLearningStageWorker('
    )
    assert '"panel_learning_model_review_repair"' in review_body
    assert 'fallbackPath: "/panel/run_learning_model_review_repair"' in review_body


def test_managed_learning_worker_explicitly_adopts_completed_result() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    helper_start = panel_js.index("async function runManagedLearningStageWorker")
    helper_end = panel_js.index(
        "async function finishLearningWorkflowStageOperation",
        helper_start,
    )
    helper_body = panel_js[helper_start:helper_end]

    assert "/panel/adopt_learning_stage_worker_result" in helper_body
    assert "workerStatus.response" not in helper_body
    assert "result_available" in helper_body


def test_locator_reuses_resource_preflight_for_model_readiness() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    calibration_start = panel_js.index("async function runLearningDeepCalibration")
    calibration_end = panel_js.index("function learningTwoStageUnderstandingPayload", calibration_start)
    calibration_body = panel_js[calibration_start:calibration_end]

    assert "learningModelResourcePreflight(" in calibration_body
    assert '"locate", profileId, { signal: options.signal }' in calibration_body
    assert 'ensureStageModelReady("locate", profileId, { resourcePreflight, signal: options.signal })' in calibration_body


def test_learning_draft_compacts_vista_evidence_before_fusion_payload() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    compact_start = panel_js.index("function compactVistaCoordinateValidation")
    compact_end = panel_js.index("function compactLearningDraftTargets", compact_start)
    vista_body = panel_js[compact_start:compact_end]
    targets_start = compact_end
    targets_end = panel_js.index("function screenMapEvidenceCount", targets_start)
    targets_body = panel_js[targets_start:targets_end]

    assert "coordinate_transform" in vista_body
    assert "gate_result" in vista_body
    assert "overlay_path" in vista_body
    assert "model_io" not in vista_body
    assert "precise_locator_evidence" not in vista_body
    assert "compactVistaCoordinateValidation(target.vista_coordinate_validation)" in targets_body
    assert "? target.vista_coordinate_validation : null" not in targets_body


def test_learning_interface_flow_marks_unhandled_exception_as_terminal_failure() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    flow_start = panel_js.index("async function runLearningInterfaceFlow")
    flow_end = panel_js.index("async function completeLearningInterfaceReadonlyFlow", flow_start)
    flow_body = panel_js[flow_start:flow_end]

    assert "catch (error)" in flow_body
    assert "transitionLearningWorkflowState(" in flow_body
    assert "activeLearningStageOperation" in flow_body
    assert "finishLearningWorkflowStageOperation(" in flow_body
    assert 'currentLearningInterfaceFlowStep,\n            "failed"' in flow_body
    assert "learning flow failed" in flow_body
    assert "return { success: false" in flow_body


def test_learning_interface_flow_uses_returned_artifact_shapes_for_evidence() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    flow_start = panel_js.index("async function runLearningInterfaceFlow")
    flow_end = panel_js.index("async function runLearningDraftTrial", flow_start)
    flow_body = panel_js[flow_start:flow_end]

    assert "fallbackResult: resultOf(trialResponse)" in flow_body
    assert "learningTrialArtifactPath(trial)" not in flow_body
    assert "learningTrialArtifactPath(fusedTrial)" not in flow_body
    assert "learningStageContinuationFinished(trialResponse)" in flow_body
    assert "learningPageDetailArtifactPath(pageDetail || {})" in flow_body
    assert "learningScaffoldArtifactPath(scaffold || {})" in flow_body
    assert 'nestedGet(trial, ["data", "trial_path"])' not in flow_body
    assert "fusedTrial" not in flow_body
    assert 'nestedGet(pageDetail, ["data", "source_path"])' not in flow_body
    assert 'nestedGet(scaffold, ["data", "scaffold_path"])' not in flow_body


def test_learning_interface_step_status_keeps_global_status_in_sync() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    helper_start = panel_js.index("function renderLearningWorkflowState")
    helper_end = panel_js.index("function newLearningWorkflowRunId", helper_start)
    helper_body = panel_js[helper_start:helper_end]
    assert 'workflowStatus === "completed"' in helper_body
    assert 'workflowStatus === "failed" || workflowStatus === "safe_stopped"' in helper_body
    assert 'setStatus("running", "running")' in helper_body
    assert 'setStatus("ok", "ok")' in helper_body
    assert 'setStatus("failed", "error")' in helper_body


def test_learning_interface_binding_uses_and_verifies_exact_window_handle() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    bind_start = panel_js.index("async function bindSelectedWindow")
    bind_end = panel_js.index("async function captureBoundWindow", bind_start)
    bind_body = panel_js[bind_start:bind_end]
    assert "expectedCandidate?.handle" in bind_body
    assert "handle: expectedHandle" in bind_body
    assert "boundHandle !== expectedHandle" in bind_body
    assert "window_binding_mismatch" in bind_body


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
                "endpoint": "http://127.0.0.1:13240/v1/chat/completions",
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
                "endpoint": "http://127.0.0.1:13240/v1",
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
                "error": "failed to reach local vision endpoint http://127.0.0.1:13240/v1/chat/completions",
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


def test_panel_keeps_internal_learning_assets_without_exposing_subview_switch() -> None:
    index_html = Path("app/web_panel/index.html").read_text(encoding="utf-8")
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8")
    panel_css = Path("app/web_panel/panel.css").read_text(encoding="utf-8")

    assert 'class="button-row replay-template-actions"' in index_html
    assert 'class="replay-action-disclosure"' in index_html
    assert 'class="button-row replay-template-advanced-actions"' in index_html
    assert 'class="button-row replay-learning-actions"' in index_html
    assert 'class="learn-replay-subnav"' not in index_html
    assert 'data-learn-replay-panel="template"' in index_html
    assert '<section class="learn-replay-subview active" data-learn-replay-panel="draft">' in index_html
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
    assert 'let currentLearnReplaySubview = "draft";' in panel_js
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
    assert "const candidateSourcePath = learningPageDetailArtifactPath(data) || sourcePath;" in panel_js
    assert "const scaffoldSourcePath = learningScaffoldArtifactPath(data) || sourcePath;" in panel_js
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
    assert "renderLearningPresentationAcceptance" in panel_js
    assert "presentation_acceptance" in panel_js
    assert "same_source_three_image_evidence" in panel_js
    assert "frontend_revision_matches" in panel_js
    assert "desktop_viewport_covered" in panel_js
    assert "narrow_viewport_covered" in panel_js
    assert "presentation_status=${presentationAcceptance?.acceptance_status" in panel_js
    assert "presentation_blockers=${presentationBlockers.length}" in panel_js
    assert "counts_as_final_goal_completion" in panel_js
    assert "source_breakdown" in panel_js
    assert "fresh_model_acceptance_status" in panel_js
    assert "fresh_model_chain_accepted" in panel_js
    assert "fresh_model_counts_as_final_goal_completion" in panel_js
    assert "fresh_acceptance=${freshModelAcceptance}" in panel_js
    assert "fresh_actual_model=${freshModelActualEvidence}" in panel_js
    assert "fresh_assisted=${freshModelAssistedEvidence}" in panel_js
    assert "presentation=${presentationAcceptance}" in panel_js
    assert "presentation_ready=${source.presentation_accepted" in panel_js
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
    assert "presentation_accepted === true" in preferred_body
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
    assert "learning-demo-presentation-acceptance" in panel_css
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
    assert 'readonly_preview=${readonlyPreviewStatus || "not_generated"}' in panel_js
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
    assert "orderedLearningDraftSources" in panel_js
    assert 'item.recommended_for_panel_review === true ? "[Recommended current] "' in panel_js
    assert 'item.pinned === true ? "[Pinned reference] "' in panel_js
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
    load_review_start = panel_js.index("async function loadLearningDraftReview")
    load_review_end = panel_js.index("async function saveLearningDraftReview", load_review_start)
    load_review_body = panel_js[load_review_start:load_review_end]
    assert 'clearLearningDraftReviewDisplay(`loading · ${sourcePath}`, {' in load_review_body
    assert "preserveWorkflowReview: options.skipWorkflowReview === true" in load_review_body
    assert load_review_body.index("clearLearningDraftReviewDisplay") < load_review_body.index(
        'api("POST", "/panel/load_learning_draft_review"'
    )
    assert "function clearLearningDraftWorkspaceForNewRun" in panel_js
    assert "function renderLearningDraftPathPreview" in panel_js
    assert "function renderLearningDraftHierarchy" in panel_js
    assert "ui_hierarchy_graph_v1" in panel_js
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
    assert "renderLearningDraftHierarchy(draft)" in panel_js
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
    assert "const binding = await bindSelectedWindow()" in run_flow_body
    assert run_flow_body.index("const binding = await bindSelectedWindow()") < run_flow_body.index("runLearningInterfaceCaptureStrategy")
    assert '"bind_capture",\n        "failed",\n        `bind failed' in run_flow_body
    assert 'clearLearningDraftWorkspaceForNewRun("not_loaded · new learning run started")' in run_flow_body
    assert run_flow_body.index("clearLearningDraftWorkspaceForNewRun") < run_flow_body.index("runLearningInterfaceCaptureStrategy")
    assert 'clearScreenUnderstandingResidualDisplays("not_loaded · screen understanding started")' in capture_trial_body
    assert "await applyLearningDraftTrialResponse(response, options)" in run_trial_body
    apply_trial_start = panel_js.index("async function applyLearningDraftTrialResponse")
    apply_trial_end = panel_js.index("function learningReviewLabel", apply_trial_start)
    apply_trial_body = panel_js[apply_trial_start:apply_trial_end]
    assert "await loadLearningDraftReview({" in apply_trial_body
    assert 'clearScreenUnderstandingResidualDisplays("not_loaded · generating learning draft", {' in run_trial_body
    assert "preserveTwoStageReportPath: Boolean(options.preserveTwoStageReportPath)" in run_trial_body
    request_payload_start = panel_js.index("function learningRecognitionTrialRequestPayload")
    capture_trial_start_for_payload = panel_js.index("async function captureLearningDraftWindow", request_payload_start)
    request_payload_body = panel_js[request_payload_start:capture_trial_start_for_payload]
    assert (
        "two_stage_report_path: String(lastLearningFinalStage2ReportPath || "
        "lastLearningTwoStageReportPath || \"\").trim() || null"
    ) in request_payload_body
    assert run_trial_body.index("const payload = learningRecognitionTrialRequestPayload()") < run_trial_body.index(
        'clearScreenUnderstandingResidualDisplays("not_loaded · generating learning draft", {'
    )
    assert "followContinuationChain: true" in run_flow_body
    assert "learningStageContinuationFinished(trialResponse)" in run_flow_body
    assert 'learningStageContinuation(trialResponse).outcome === "completed"' in run_flow_body
    screen_operation_body = run_flow_body[
        run_flow_body.index(
            'startLearningWorkflowStageOperation(\n      "screen_understanding"'
        )
        :
    ]
    assert "runLearningDraftTrial(" not in screen_operation_body
    assert "runLearningTwoStageUnderstanding(" not in run_flow_body
    assert "runLearningDeepCalibration(" not in run_flow_body
    assert "runLearningModelReviewRepair(" not in run_flow_body
    assert "nextLearningStageOperation(" not in run_flow_body
    assert "backendContinuationStageWorker(continuationData)" in panel_js
    assert "runLearningScreenObserve({" in run_flow_body
    assert "followContinuationChain: true" in run_flow_body
    assert "let lastLearningTwoStageReportPath" in panel_js
    assert "let lastLearningFusedTrialPath" in panel_js
    assert 'lastLearningTwoStageReportPath = ""' in panel_js
    assert 'lastLearningTwoStageReportPath = String(resultOf(response).report_path || "").trim()' in panel_js
    assert "if (options.preserveTwoStageReportPath)" in run_trial_body
    assert "lastLearningFusedTrialPath = trialPath" in run_trial_body
    create_page_detail_start = panel_js.index("async function createPageDetailCandidate")
    create_demo_scaffold_start = panel_js.index("async function createLearningDemoScaffold")
    create_page_detail_body = panel_js[create_page_detail_start:create_demo_scaffold_start]
    assert create_page_detail_body.index("lastLearningFusedTrialPath") < create_page_detail_body.index("lastLearningTwoStageReportPath")
    assert create_page_detail_body.index("lastLearningTwoStageReportPath") < create_page_detail_body.index("learningPathGraphCandidatePath")
    assert create_page_detail_body.index("lastLearningTwoStageReportPath") < create_page_detail_body.index("learningDetailObserveCandidatePath")
    assert create_page_detail_body.index("lastLearningTwoStageReportPath") < create_page_detail_body.index("learningDraftReviewSourcePath()")
    assert 'stage2_region_strategy: "partitioned"' in panel_js
    assert 'stage2_region_strategy: "global_no_partition"' not in run_flow_body
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
    assert 'if (selected === "draft") {' in set_subview_body
    assert "hideSharedPathSurface();" in set_subview_body
    assert set_subview_body.index('if (selected === "draft") {') < set_subview_body.index(
        "hideSharedPathSurface();"
    )
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


def test_learning_draft_panel_exposes_full_image_bbox_editor_controls() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    index_html = Path("app/web_panel/index.html").read_text(encoding="utf-8-sig")

    assert '<script src="/panel/assets/learning_draft_editor.js' in index_html
    for control_id in (
        "learningDraftOpenBoxEditorBtn",
        "imageInspectorAddRegionBtn",
        "imageInspectorDeleteBoxBtn",
        "imageInspectorUndoBtn",
        "imageInspectorRedoBtn",
        "imageInspectorRoleSelect",
        "imageInspectorParentSelect",
        "imageInspectorReason",
    ):
        assert f'id="{control_id}"' in index_html
    assert "LearningDraftEditorState.createLearningDraftEditorState" in panel_js
    assert 'contract_version: "human_review_patch_v1"' in panel_js
    assert "renderLearningDraftEditorBoxes" in panel_js
    assert "resetLearningDraftEditorState" in panel_js


def test_panel_two_stage_endpoint_returns_review_boxes_for_real_learning_flow(
    monkeypatch,
    tmp_path,
) -> None:
    client = TestClient(app)
    report_path = tmp_path / "two-stage.json"
    saved_report = {
        "model_grounding_evidence": {
            "status": "not_valid_for_model_grounding_evidence"
        },
        "learn_all_targets": {
            "review_box_count": 1,
            "review_boxes": [
                {
                    "id": "R1",
                    "label": "Main Card",
                    "role": "review_only",
                    "bbox": {"x": 10, "y": 20, "w": 100, "h": 80},
                }
            ],
            "overlay_path": "artifacts/review-overlays/demo_two_stage.png",
            "stage1_gate_status": "passed",
        },
    }
    report_path.write_text(
        json.dumps(saved_report, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        panel_api,
        "run_two_stage_understanding_task",
        lambda task_input, *, project_root: LearningTaskResult(
            outcome="completed",
            payload={
                "contract_version": "panel_learning_two_stage_understanding_run_v1",
                "stage1_gate": {"status": "passed"},
                "stage2_numbering_skipped": False,
                "learn_all_targets": saved_report["learn_all_targets"],
                "coordinate_overlay_path": "artifacts/review-overlays/demo_two_stage.png",
                "model_grounding_evidence": saved_report[
                    "model_grounding_evidence"
                ],
                "summary": {
                    "model_grounding_evidence_status": (
                        "not_valid_for_model_grounding_evidence"
                    ),
                    "stage2_numbered_item_count": 7,
                },
                "real_clicks": 0,
                "promotion_allowed": False,
                "report_path": str(report_path),
            },
        ),
    )

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
    assert data["summary"]["stage2_numbered_item_count"] == 7
    assert data["real_clicks"] == 0
    assert data["promotion_allowed"] is False
    saved_report = json.loads(Path(data["report_path"]).read_text(encoding="utf-8-sig"))
    assert saved_report["model_grounding_evidence"]["status"] == "not_valid_for_model_grounding_evidence"
    assert saved_report["learn_all_targets"]["review_box_count"] == 1
    assert saved_report["learn_all_targets"]["review_boxes"][0]["label"] == "Main Card"
    assert saved_report["learn_all_targets"]["overlay_path"] == "artifacts/review-overlays/demo_two_stage.png"
    assert saved_report["learn_all_targets"]["stage1_gate_status"] == "passed"

def test_panel_learning_model_review_repair_returns_final_numbering_for_calibration(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client = TestClient(app)
    source_report = tmp_path / "two_stage.json"
    screenshot = tmp_path / "screen.png"
    overlay = tmp_path / "before.png"
    source_report.write_text("{}", encoding="utf-8")
    screenshot.write_bytes(b"screen")
    overlay.write_bytes(b"overlay")
    final_report = tmp_path / "final_stage2.json"
    final_overlay = tmp_path / "final.png"
    final_report.write_text("{}", encoding="utf-8")
    final_overlay.write_bytes(b"final")

    def fake_run(**kwargs):
        assert kwargs["two_stage_report_path"] == source_report.resolve()
        assert kwargs["screenshot_path"] == screenshot.resolve()
        assert kwargs["composite_overlay_path"] == overlay.resolve()
        assert kwargs["model_profile_id"] == "learn_mode_qwen3_vl_8b"
        return {
            "contract_version": "panel_learning_model_review_repair_result_v1",
            "status": "ready_for_calibration",
            "calibration_permission": True,
            "final_stage2_report_path": str(final_report.resolve()),
            "final_repaired_overlay_path": str(final_overlay.resolve()),
            "final_numbering_revision": "final-revision-1",
            "integrity_gate": {"passed": True, "failure_categories": []},
            "three_image_evidence": {
                "original": str(screenshot.resolve()),
                "before_review_fusion": str(overlay.resolve()),
                "final_repaired_fusion": str(final_overlay.resolve()),
            },
            "safety": {"display_only": True, "real_clicks": 0, "live_fills": 0, "live_submits": 0},
        }

    monkeypatch.setattr(panel_api, "_resolve_under_root_path", lambda value: Path(value).resolve())
    monkeypatch.setattr(panel_api, "run_panel_learning_model_review_repair", fake_run)

    response = client.post(
        "/panel/run_learning_model_review_repair",
        json={
            "two_stage_report_path": str(source_report),
            "screenshot_path": str(screenshot),
            "composite_overlay_path": str(overlay),
            "model_profile_id": "learn_mode_qwen3_vl_8b",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["calibration_permission"] is True
    assert payload["data"]["final_stage2_report_path"] == str(final_report.resolve())
    assert payload["data"]["final_numbering_revision"] == "final-revision-1"
    assert payload["data"]["real_clicks"] == 0


def test_panel_learning_model_review_repair_safe_stop_is_not_api_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    client = TestClient(app)
    source_report = tmp_path / "two_stage.json"
    screenshot = tmp_path / "screen.png"
    overlay = tmp_path / "before.png"
    source_report.write_text("{}", encoding="utf-8")
    screenshot.write_bytes(b"screen")
    overlay.write_bytes(b"overlay")

    monkeypatch.setattr(panel_api, "_resolve_under_root_path", lambda value: Path(value).resolve())
    monkeypatch.setattr(
        panel_api,
        "run_panel_learning_model_review_repair",
        lambda **kwargs: {
            "contract_version": "panel_learning_model_review_repair_result_v1",
            "status": "safe_stop",
            "calibration_permission": False,
            "final_stage2_report_path": "",
            "final_repaired_overlay_path": str(overlay.resolve()),
            "final_numbering_revision": "",
            "integrity_gate": {
                "passed": False,
                "failure_categories": ["needs_human_review"],
            },
            "safety": {"display_only": True, "real_clicks": 0, "live_fills": 0, "live_submits": 0},
        },
    )

    response = client.post(
        "/panel/run_learning_model_review_repair",
        json={
            "two_stage_report_path": str(source_report),
            "screenshot_path": str(screenshot),
            "composite_overlay_path": str(overlay),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["status"] == "safe_stop"
    assert payload["data"]["calibration_permission"] is False
    assert payload["data"]["integrity_gate"]["failure_categories"] == ["needs_human_review"]
    assert payload["data"]["real_clicks"] == 0


def test_learning_interface_flow_calibrates_before_model_review_and_repair() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    html = Path("app/web_panel/index.html").read_text(encoding="utf-8-sig")
    flow_start = panel_js.index("async function runLearningInterfaceFlow")
    flow_body = panel_js[flow_start:panel_js.index("async function completeLearningInterfaceReadonlyFlow", flow_start)]

    assert 'data-learning-flow-step="review_repair"' in html
    assert 'data-i18n="learning_flow_review_repair"' in html
    assert "followContinuationChain: true" in flow_body
    assert "runLearningDeepCalibration(" not in flow_body
    assert "runLearningModelReviewRepair(" not in flow_body
    assert 'taskKind === "panel_learning_calibration_sequence"' in panel_js
    assert 'taskKind === "panel_learning_model_review_repair"' in panel_js

    assert panel_js.index('"precise_calibration",') < panel_js.index('"review_repair",')
    assert html.index('data-learning-flow-step="precise_calibration"') < html.index(
        'data-learning-flow-step="review_repair"'
    )


def test_learning_interface_flow_progress_matches_real_artifact_dependencies() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    html = Path("app/web_panel/index.html").read_text(encoding="utf-8-sig")
    flow_start = panel_js.index("async function runLearningInterfaceFlow")
    flow_end = panel_js.index("async function completeLearningInterfaceReadonlyFlow", flow_start)
    flow_body = panel_js[flow_start:flow_end]
    complete_body = panel_js[flow_end:panel_js.index("async function runLearningDraftTrial", flow_end)]

    assert 'markLearningInterfaceFlowStepDone("page_details")' not in flow_body
    assert 'setLearningInterfaceFlowStep("page_details"' not in flow_body
    assert "/panel/run_learning_workflow_readonly_tail" in complete_body
    assert "createPageDetailCandidate()" not in complete_body
    assert "createLearningDemoScaffold()" not in complete_body
    assert 'transitionLearningWorkflowState("page_details"' not in complete_body
    assert 'transitionLearningWorkflowState("pathgraph_draft"' not in complete_body
    assert 'transitionLearningWorkflowState("complete"' not in complete_body
    assert 'nestedGet(response, ["data", "workflow_state"])' in complete_body
    assert "runLearningDeepCalibration(" not in flow_body
    assert "runLearningModelReviewRepair(" not in flow_body
    assert "runLearningDraftTrial(" not in flow_body
    assert "backendContinuationStageWorker(continuationData)" in panel_js
    assert html.index('data-learning-flow-step="precise_calibration"') < html.index(
        'data-learning-flow-step="review_repair"'
    )
    assert html.index('data-learning-flow-step="review_repair"') < html.index(
        'data-learning-flow-step="fusion"'
    )
    assert html.index('data-learning-flow-step="fusion"') < html.index(
        'data-learning-flow-step="page_details"'
    )


def test_learning_interface_flow_has_explicit_completed_step_marker() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    helper_start = panel_js.index("function renderLearningWorkflowState")
    helper_end = panel_js.index("function newLearningWorkflowRunId", helper_start)
    helper_body = panel_js[helper_start:helper_end]
    assert 'data-learning-flow-step' in helper_body
    assert 'item.classList.toggle("is-done", stageStatus === "completed")' in helper_body
    assert 'item.classList.toggle("is-active", itemStep === currentStage && stageStatus === "running")' in helper_body


def test_learning_model_review_repair_renders_final_overlay_and_binds_final_graph() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    assert "let lastLearningReviewRepairResponse = null;" in panel_js
    assert "let lastLearningFinalStage2ReportPath = \"\";" in panel_js
    assert "let lastLearningFinalNumberingRevision = \"\";" in panel_js
    review_start = panel_js.index("async function runLearningModelReviewRepair")
    review_end = panel_js.index("async function runLearningInterfaceFlow", review_start)
    review_body = panel_js[review_start:review_end]
    payload_start = panel_js.index("function learningModelReviewRepairPayload")
    payload_end = panel_js.index("async function runLearningModelReviewRepair", payload_start)
    payload_body = panel_js[payload_start:payload_end]
    assert '"panel_learning_model_review_repair"' in review_body
    assert 'fallbackPath: "/panel/run_learning_model_review_repair"' in review_body
    assert 'renderLearningDraftScreenshotPath(finalOverlayPath, "learning final reviewed fusion overlay")' in review_body
    assert "lastLearningFinalStage2ReportPath" in review_body
    assert "lastLearningFinalNumberingRevision" in review_body

    calibration_start = panel_js.index("async function runLearningDeepCalibration")
    calibration_end = panel_js.index("function learningTwoStageUnderstandingPayload", calibration_start)
    calibration_body = panel_js[calibration_start:calibration_end]
    assert "payload.metadata.two_stage_report_path = calibrationSourceReportPath" in calibration_body
    assert "payload.metadata.final_numbering_revision" not in calibration_body
    assert "payload.metadata.review_repair_integrity_gate_passed" not in calibration_body
    assert "learningDeepCalibrationOverlayPath(calibrationResponse)" in payload_body


def test_seek_search_button_visual_asset_declares_missing_source_as_stale() -> None:
    map_path = Path("artifacts/visual-match-smoke/live_seek_20260624/learned_interface_map_calibrated_real_crops.json")
    interface_map = json.loads(map_path.read_text(encoding="utf-8"))
    asset = next(item for item in interface_map["fixed_visual_assets"] if item["asset_id"] == "seek:visual:search_button")

    source_path = Path(asset["source"]["source_image_path"])
    tight_path = Path(asset["template_refs"]["tight_crop_ref"])
    context_path = Path(asset["template_refs"]["context_crop_ref"])
    bbox = asset["source"]["bbox"]

    assert not source_path.exists()
    assert asset["source_fixture_validity"] == {
        "status": "invalid",
        "failure_category": "stale_fixture",
        "reason": "source screenshot is missing; retained tight/context crops are replay assets only",
        "source_audit_available": False,
        "excluded_from_source_evidence_denominator": True,
    }
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
        if source_path and not source_path.exists():
            validity = asset.get("source_fixture_validity") or {}
            assert validity.get("status") == "invalid", f"{asset_id} missing source is not marked invalid"
            assert validity.get("failure_category") == "stale_fixture"
            assert validity.get("excluded_from_source_evidence_denominator") is True

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


def test_learning_draft_page_detail_renders_same_source_once() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    scaffold_start = panel_js.index("function renderLearningDemoScaffold")
    scaffold_end = panel_js.index("function renderLearningPageDetailPathGraphCorrespondence", scaffold_start)
    scaffold_body = panel_js[scaffold_start:scaffold_end]

    assert "function learningPageDetailSourceIdentity" in panel_js
    assert "function renderLearningPageDetailPreviewIfDistinct" in panel_js
    assert "const canonicalPageDetail = candidateReview.page_detail_candidate" in scaffold_body
    assert "renderLearningPageDetailPreviewIfDistinct(modelPageDetail, canonicalPageDetail" in scaffold_body
    assert "renderLearningPageDetailPreviewIfDistinct(readonlyPageDetail, canonicalPageDetail" in scaffold_body


def test_learning_draft_history_sources_load_during_panel_boot() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    boot_start = panel_js.index("async function boot()")
    boot_end = panel_js.index("\nboot();", boot_start)
    boot_body = panel_js[boot_start:boot_end]

    assert "loadLearningDetailObserveSources();" in boot_body
    assert boot_body.index("loadLearningDetailObserveSources();") < boot_body.index("refreshModels();")


def test_panel_learning_review_assets_use_current_cache_key() -> None:
    panel_html = Path("app/web_panel/index.html").read_text(encoding="utf-8-sig")

    assert "/panel/assets/panel.css?v=20260815-learning-screenshot-visibility-1" in panel_html
    assert "/panel/assets/learning_draft_editor.js?v=20260729-box-editor-status-1" in panel_html
    assert "/panel/assets/learning_workflow_review.js?v=20260810-review-pages-4" in panel_html
    assert "/panel/assets/interface_workflow_graph.js?v=20260815-workflow-layout-bounds-1" in panel_html
    assert "/panel/assets/panel.js?v=20260821-reviewed-workflow-v2-panel-1" in panel_html


def test_learning_draft_history_visibly_separates_current_and_pinned_sources() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    render_start = panel_js.index("function renderLearningDraftHistoryList")
    render_end = panel_js.index("function orderedLearningDraftSources", render_start)
    render_body = panel_js[render_start:render_end]

    assert 'item.recommended_for_panel_review === true ? "[Recommended current] "' in render_body
    assert 'item.pinned === true ? "[Pinned reference] "' in render_body


def test_learning_draft_review_load_coalesces_duplicate_source_before_clearing_view() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    load_start = panel_js.index("async function loadLearningDraftReview")
    load_end = panel_js.index("\nasync function ", load_start + 1)
    load_body = panel_js[load_start:load_end]

    assert "learningDraftReviewLoadPromise" in load_body
    assert "learningDraftReviewLoadSourcePath === sourcePath" in load_body
    assert "return learningDraftReviewLoadPromise" in load_body
    assert load_body.index("learningDraftReviewLoadPromise") < load_body.index(
        "clearLearningDraftReviewDisplay"
    )


def test_interface_workflow_evidence_layer_switch_preserves_unsaved_editor_values() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    handler_start = panel_js.index('on("interfaceWorkflowLayerTabs", "click"')
    handler_end = panel_js.index("\n  });", handler_start) + len("\n  });")
    handler_body = panel_js[handler_start:handler_end]

    assert "state.selectLayer(layer)" in handler_body
    assert "renderActiveInterfaceWorkflowEvidence()" in handler_body
    assert "renderInterfaceWorkflowReviewSelection()" not in handler_body


def test_panel_contains_generic_interface_workflow_review_workspace() -> None:
    client = TestClient(app)
    response = client.get("/panel")

    assert response.status_code == 200
    html = response.text
    assert 'id="interfaceWorkflowReviewPanel"' in html
    assert 'id="interfaceWorkflowThreeColumnWorkbench"' in html
    assert 'id="interfaceWorkflowIdentityInput"' in html
    assert 'id="interfaceWorkflowPathColumn"' in html
    assert 'id="interfaceWorkflowEvidenceColumn"' in html
    assert 'id="interfaceWorkflowReviewToolsColumn"' in html
    assert 'href="#interfaceWorkflowThreeColumnWorkbench"' in html
    assert "路径图与界面证据" in html
    assert "先在下方带框图选择具体控件" in html
    assert "先在左侧路径图选择具体控件" not in html
    assert "修正当前界面" in html
    assert 'id="interfaceWorkflowGraph"' in html
    assert 'id="interfaceWorkflowGraphCanvas"' in html
    assert 'id="interfaceWorkflowGraphTooltip"' in html
    assert 'id="interfaceWorkflowGraphContextMenu"' in html
    assert 'id="interfaceWorkflowGraphLinkStatus"' in html
    assert 'id="interfaceWorkflowGraphEmpty"' in html
    assert 'id="interfaceWorkflowGraphZoomOut"' in html
    assert 'id="interfaceWorkflowGraphBack"' in html
    assert 'id="interfaceWorkflowGraphZoomIn"' in html
    assert 'id="interfaceWorkflowGraphReset"' in html
    assert 'id="interfaceWorkflowGraphLegend"' in html
    assert "圆点代表界面，连线代表操作与跳转" in html
    assert "加入单界面" in html
    assert 'id="interfaceAssetAttachDialog"' in html
    assert "加入流程" in html
    assert "加入并连接" in html
    assert "用当前框连接下一个界面" in html
    assert 'id="interfaceWorkflowEvidence"' in html
    assert 'id="interfaceWorkflowStepAudit"' in html
    assert 'id="interfaceWorkflowEvidenceModeWorkflow"' in html
    assert 'id="interfaceWorkflowEvidenceModePreview"' in html
    assert 'id="interfaceWorkflowInspector"' in html
    assert 'id="interfaceWorkflowLayerTabs"' in html
    assert 'id="interfaceWorkflowNodeName"' in html
    assert 'id="interfaceWorkflowSurfaceType"' in html
    assert 'id="interfaceWorkflowNodeReviewStatus"' in html
    assert '<option value="human_approved">human_approved（需显式确认）</option>' in html
    assert 'id="interfaceWorkflowNodeHumanReviewConfirmed"' in html
    assert "确认当前 revision 已人工审核" in html
    assert 'id="interfaceWorkflowTransitionAction"' in html
    assert 'id="interfaceWorkflowTransitionTarget"' in html
    assert 'id="interfaceWorkflowSourceSelect"' in html
    assert 'id="interfaceWorkflowSourcePreviewBtn"' in html
    assert 'id="interfaceWorkflowSourceNameInput"' in html
    assert 'id="interfaceWorkflowAttachWorkflowSelect"' in html
    assert 'id="interfaceWorkflowAttachFromNodeSelect"' not in html
    assert 'id="interfaceWorkflowAttachActionType"' not in html
    assert 'id="interfaceWorkflowAttachActionLabel"' not in html
    assert 'id="interfaceWorkflowAttachTargetControl"' not in html
    assert 'id="interfaceWorkflowAttachPickControlBtn"' not in html
    assert "job_card" not in html
    assert 'id="interfaceWorkflowSourcePreview"' in html
    assert 'id="interfaceWorkflowAddSourceBtn"' in html
    assert 'id="interfaceWorkflowRemoveSourceBtn"' in html
    assert 'id="interfaceWorkflowSourceStatus"' in html
    assert 'id="interfaceWorkflowEditBoxesBtn"' in html
    assert 'id="interfaceWorkflowReviewToolsToggle"' in html
    assert 'id="interfaceWorkflowSaveBtn"' in html
    assert 'id="interfaceWorkflowMemoryBtn"' in html
    assert 'id="interfaceWorkflowSaveStatus"' in html
    assert "/panel/assets/learning_workflow_review.js" in html
    assert "/panel/assets/interface_workflow_graph.js" in html
    assert "SEEK workflow review" not in html
    assert 'class="learning-review-section learning-draft-history-panel legacy-learning-review-panel" hidden' in html
    assert 'class="learning-review-section learning-draft-screenshot-panel legacy-learning-review-panel" id="learningDraftScreenshotPanel" hidden' in html
    assert 'class="learning-review-panel legacy-learning-review-panel" id="learningDraftReviewPanel" hidden' in html

    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    assert '"/panel/save_interface_workflow_review"' in panel_js
    assert "function openInterfaceWorkflowMemoryVerification" in panel_js
    assert "function renderInterfaceWorkflowStepAudit" in panel_js
    assert 'scrollIntoView({ behavior: "smooth", block: "start" })' in panel_js


def _human_review_persistence_review(
    *,
    workflow_id: str,
    confirmed: bool,
) -> dict:
    node = {
        "node_id": "reviewed_interface",
        "display_name": "Reviewed interface",
        "surface_type": "detail",
        "state_signature": "reviewed-interface-v1",
        "evidence": {
            "source_screenshot_path": "artifacts/screenshots/reviewed-interface.png",
        },
        "content_descriptors": [
            {
                "content_id": "reviewed_title",
                "label": "Reviewed interface",
                "content_behavior": "fixed_label",
                "agent_usage": "identity_anchor",
                "read_policy": "on_interface_match",
                "agent_description": "确认当前界面身份",
            }
        ],
        "controls": [],
        "action_candidates": [],
        "verification_rules": [
            {
                "rule_id": "safe_stop_visible",
                "expected_decision": "safe_stop",
            }
        ],
        "blockers": [
            {
                "blocker_id": "review_complete",
                "safe_stop_required": True,
            }
        ],
        "manual_revision": {
            "semantic_description": "读取当前界面语义后安全停止",
        },
    }
    review = {
        "contract_version": "single_application_workflow_review_v1",
        "workflow": {
            "workflow_id": workflow_id,
            "goal": "Review one interface",
            "application_identity": {
                "url": f"https://{workflow_id}.example.test/items",
            },
            "entry_node_id": node["node_id"],
            "node_ids": [node["node_id"]],
            "edge_ids": [],
            "review_status": "needs_human_review",
        },
        "nodes": [node],
        "edges": [],
        "display_only": True,
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    if confirmed:
        node.update(
            {
                "review_status": "human_approved",
                "reviewed_by_human": True,
                "human_review_confirmation": {
                    "contract_version": "interface_node_human_review_confirmation_v1",
                    "revision": {
                        "node": json.loads(json.dumps(node, ensure_ascii=False)),
                        "outgoing_edges": [],
                    },
                },
            }
        )
        revision_node = node["human_review_confirmation"]["revision"]["node"]
        revision_node.pop("review_status", None)
        revision_node.pop("reviewed_by_human", None)
        revision_node.pop("human_review_confirmation", None)
    return review


def test_panel_save_rejects_label_only_and_client_reported_revision_hash(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    review = _human_review_persistence_review(
        workflow_id="label-only-review",
        confirmed=False,
    )
    node = review["nodes"][0]
    node.update(
        {
            "review_status": "human_approved",
            "reviewed_by_human": True,
            "reviewed_revision_hash": "f" * 64,
            "current_revision_hash": "f" * 64,
        }
    )

    response = TestClient(app).post(
        "/panel/save_interface_workflow_review",
        json={"review": review},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True, payload
    projection = payload["data"]["interface_asset_projection"]
    assert projection["agent_evidence_projection"]["agent_usable_count"] == 0
    assert projection["agent_evidence_projection"]["needs_human_review_count"] == 1
    saved = json.loads(Path(payload["data"]["path"]).read_text(encoding="utf-8"))
    assert saved["nodes"][0]["review_status"] == "needs_human_review"
    assert saved["nodes"][0]["reviewed_by_human"] is False
    assert saved["nodes"][0]["reviewed_revision_hash"] == ""
    asset_path = tmp_path / projection["interface_results"][0]["asset_path"]
    asset = json.loads(asset_path.read_text(encoding="utf-8"))
    assert asset["review"]["reviewed_by_human"] is False
    assert asset["review"]["reviewed_revision_hash"] == ""
    assert asset["artifact_is_authorization"] is False


def test_panel_save_revokes_stale_confirmation_for_every_agent_consumed_revision_field(
    tmp_path: Path,
    monkeypatch,
) -> None:
    mutations = {
        "semantics": lambda node: node.update(display_name="Changed semantics"),
        "source": lambda node: node.update(source_paths=["artifacts/changed-source.json"]),
        "control": lambda node: node.update(controls=[{"control_id": "changed-control"}]),
        "action": lambda node: node.update(
            action_candidates=[{"action_type": "open_detail", "target_control_id": "changed-control"}]
        ),
        "screenshot": lambda node: node["evidence"].update(
            source_screenshot_path="artifacts/screenshots/changed.png"
        ),
    }
    client = TestClient(app)
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)

    for name, mutate in mutations.items():
        review = _human_review_persistence_review(
            workflow_id=f"stale-{name}-review",
            confirmed=True,
        )
        approved = client.post(
            "/panel/save_interface_workflow_review",
            json={"review": review},
        ).json()
        assert approved["success"] is True, approved
        stale_review = json.loads(
            Path(approved["data"]["path"]).read_text(encoding="utf-8")
        )
        approved_node = stale_review["nodes"][0]
        assert approved_node["reviewed_by_human"] is True
        assert approved_node["reviewed_revision_hash"] == approved_node["current_revision_hash"]
        mutate(approved_node)

        response = client.post(
            "/panel/save_interface_workflow_review",
            json={"review": stale_review},
        )

        payload = response.json()
        assert payload["success"] is True, payload
        saved = json.loads(Path(payload["data"]["path"]).read_text(encoding="utf-8"))
        node = saved["nodes"][0]
        assert node["review_status"] == "needs_human_review", name
        assert node["reviewed_by_human"] is False, name
        projection = payload["data"]["interface_asset_projection"]
        assert projection["agent_evidence_projection"]["agent_usable_count"] == 0, name


def test_panel_save_refresh_preserves_approval_only_for_the_unchanged_server_revision(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(memory_api, "ROOT_DIR", tmp_path)
    client = TestClient(app)
    review = _human_review_persistence_review(
        workflow_id="save-refresh-review",
        confirmed=True,
    )
    first = client.post(
        "/panel/save_interface_workflow_review",
        json={"review": review},
    ).json()
    assert first["success"] is True, first
    first_saved = json.loads(Path(first["data"]["path"]).read_text(encoding="utf-8"))
    first_node = first_saved["nodes"][0]
    assert first_node["reviewed_by_human"] is True
    assert first_node["reviewed_revision_hash"] == first_node["current_revision_hash"]

    refreshed = client.get(
        "/memory/interface_workflows/review_context",
        params={
            "application_identity_key": first["data"]["application_identity_key"],
            "workflow_id": first["data"]["workflow_id"],
        },
    ).json()
    assert refreshed["success"] is True, refreshed
    second = client.post(
        "/panel/save_interface_workflow_review",
        json={"review": refreshed["data"]},
    ).json()

    assert second["success"] is True, second
    second_saved = json.loads(Path(second["data"]["path"]).read_text(encoding="utf-8"))
    second_node = second_saved["nodes"][0]
    assert second_node["reviewed_by_human"] is True
    assert second_node["review_status"] == "human_approved"
    assert second_node["reviewed_revision_hash"] == first_node["reviewed_revision_hash"]
    projection = second["data"]["interface_asset_projection"]
    assert projection["agent_evidence_projection"]["agent_usable_count"] == 1
    assert second_saved["artifact_is_authorization"] is False
    assert second_saved["safety"]["final_submit_forbidden"] is True


def test_concurrent_changed_save_cannot_be_overwritten_by_stale_approved_refresh(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    baseline = TestClient(app).post(
        "/panel/save_interface_workflow_review",
        json={
            "review": _human_review_persistence_review(
                workflow_id="concurrent-review",
                confirmed=True,
            )
        },
    ).json()
    assert baseline["success"] is True, baseline
    approved_refresh = json.loads(
        Path(baseline["data"]["path"]).read_text(encoding="utf-8")
    )
    changed_review = json.loads(json.dumps(approved_refresh, ensure_ascii=False))
    changed_review["nodes"][0]["display_name"] = "Changed concurrently"

    changed_started = threading.Event()
    unchanged_started = threading.Event()
    changed_saved = threading.Event()
    real_save = panel_api.save_interface_workflow_review_candidate

    def ordered_save(review, *, project_root, out_dir=None):
        changed = review["nodes"][0]["display_name"] == "Changed concurrently"
        if changed:
            changed_started.set()
            unchanged_started.wait(timeout=0.25)
            try:
                return real_save(review, project_root=project_root, out_dir=out_dir)
            finally:
                changed_saved.set()
        unchanged_started.set()
        assert changed_saved.wait(timeout=2)
        return real_save(review, project_root=project_root, out_dir=out_dir)

    monkeypatch.setattr(
        panel_api,
        "save_interface_workflow_review_candidate",
        ordered_save,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        changed_future = executor.submit(
            lambda: TestClient(app).post(
                "/panel/save_interface_workflow_review",
                json={"review": changed_review},
            ).json()
        )
        assert changed_started.wait(timeout=2)
        unchanged_future = executor.submit(
            lambda: TestClient(app).post(
                "/panel/save_interface_workflow_review",
                json={"review": approved_refresh},
            ).json()
        )
        changed_response = changed_future.result(timeout=5)
        unchanged_response = unchanged_future.result(timeout=5)

    assert changed_response["success"] is True, changed_response
    assert unchanged_response["success"] is True, unchanged_response
    final_review = json.loads(
        Path(unchanged_response["data"]["path"]).read_text(encoding="utf-8")
    )
    final_node = final_review["nodes"][0]
    assert final_node["reviewed_by_human"] is False
    assert final_node["review_status"] == "needs_human_review"
    assert final_node["reviewed_revision_hash"] == ""
    assert unchanged_response["data"]["interface_asset_projection"][
        "agent_evidence_projection"
    ]["agent_usable_count"] == 0


def test_learning_assets_use_three_top_level_pages() -> None:
    html = Path("app/web_panel/index.html").read_text(encoding="utf-8-sig")

    for element_id in (
        "interfaceAssetUnreviewedPage",
        "interfaceAssetReviewedPage",
        "interfaceWorkflowLibraryPage",
        "interfaceAssetSharedEvidence",
    ):
        assert f'id="{element_id}"' in html
    assert "interface-workflow-review-groups" not in html
    assert "interface-workflow-source-manager" not in html


def test_unreviewed_page_explains_agent_block() -> None:
    html = Path("app/web_panel/index.html").read_text(encoding="utf-8-sig")

    assert "未审核界面不会提供给 Agent 直接使用" in html
    assert "审核通过仍不是执行授权" in html


def test_learning_asset_tabs_switch_shared_evidence_workspace() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    assert "const interfaceAssetWorkspaceState" in panel_js
    assert "function showInterfaceAssetPage" in panel_js
    assert 'on("interfaceAssetUnreviewedTab", "click"' in panel_js
    assert 'on("interfaceAssetReviewedTab", "click"' in panel_js
    assert 'on("interfaceWorkflowLibraryTab", "click"' in panel_js
    assert "interfaceAssetSharedEvidence.appendChild(evidencePanel)" in panel_js
    assert "workflowWorkbench.appendChild(evidencePanel)" in panel_js


def test_learning_asset_workspace_uses_master_detail_layout() -> None:
    panel_css = Path("app/web_panel/panel.css").read_text(encoding="utf-8-sig")

    assert ".interface-asset-workspace" in panel_css
    assert "grid-template-columns: minmax(240px, 30%) minmax(0, 70%);" in panel_css
    assert "height: clamp(300px, 38vh, 460px);" in panel_css


def test_interface_workflow_evidence_and_runtime_audit_switch_together() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    render_start = panel_js.index("function renderActiveInterfaceWorkflowEvidence")
    render_end = panel_js.index("\n}\n", render_start) + len("\n}")
    render_body = panel_js[render_start:render_end]

    assert "const view = state?.current?.() || null" in render_body
    assert "renderInterfaceWorkflowEvidence(view)" in render_body
    assert "renderInterfaceWorkflowStepAudit(view)" in render_body


def test_interface_workflow_panel_exposes_non_authorizing_safe_fill_preflight_review() -> None:
    html = Path("app/web_panel/index.html").read_text(encoding="utf-8-sig")
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    assert 'id="interfaceWorkflowSafeFillPreflightPath"' in html
    assert 'id="interfaceWorkflowSafeFillPreflightLoadBtn"' in html
    assert 'id="interfaceWorkflowSafeFillPreflight"' in html
    assert 'id="interfaceWorkflowSafeFillPreflightStatus"' in html
    assert "function renderInterfaceWorkflowSafeFillPreflight" in panel_js
    assert 'api("POST", "/panel/load_live_safe_fill_preflight"' in panel_js
    assert "artifact_is_authorization" in panel_js
    assert "不是执行授权" in panel_js


def test_panel_loads_only_redacted_live_safe_fill_preflight(tmp_path: Path) -> None:
    client = TestClient(app)
    preflight_dir = Path("artifacts") / "tests" / tmp_path.name
    preflight_dir.mkdir(parents=True, exist_ok=True)
    preflight_path = preflight_dir / "live_safe_fill_preflight.json"
    preflight_path.write_text(
        json.dumps(
            {
                "contract_version": "seek_live_safe_fill_preflight_v1",
                "status": "ready_for_human_review",
                "approval_state": "awaiting_explicit_approval",
                "field": {"id": "email", "risk_class": "ordinary_field"},
                "value_evidence": {
                    "value_hash": "abc123",
                    "value_length": 17,
                    "value_redacted": True,
                    "raw_value": "must-not-leak@example.invalid",
                },
                "safety": {"artifact_is_authorization": False},
                "pii_redacted": True,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    try:
        response = client.post(
            "/panel/load_live_safe_fill_preflight",
            json={"preflight_path": str(preflight_path)},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["data"]["contract_version"] == "seek_live_safe_fill_preflight_v1"
        assert payload["data"]["pii_redacted"] is True
        assert "must-not-leak@example.invalid" not in response.text
    finally:
        preflight_path.unlink(missing_ok=True)
        preflight_dir.rmdir()


def test_panel_rejects_live_safe_fill_preflight_outside_artifact_roots(tmp_path: Path) -> None:
    client = TestClient(app)
    preflight_path = tmp_path / "live_safe_fill_preflight.json"
    preflight_path.write_text("{}", encoding="utf-8")

    response = client.post(
        "/panel/load_live_safe_fill_preflight",
        json={"preflight_path": str(preflight_path)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "live_safe_fill_preflight_load_failed"


def test_interface_workflow_graph_uses_branching_canvas_instead_of_linear_steps() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    render_start = panel_js.index("function renderInterfaceWorkflowReviewSelection")
    render_end = panel_js.index("function commitInterfaceWorkflowEditorToState", render_start)
    render_body = panel_js[render_start:render_end]

    assert "renderInterfaceWorkflowGraph(graph)" in render_body
    assert "interface-workflow-path-step" not in render_body
    assert "下一界面尚未加入" not in render_body
    assert 'if (layoutNode.kind !== "interface") return;' in panel_js
    assert "interfaceWorkflowSelectedOperationId = \"\"" in panel_js
    assert "interfaceWorkflowReviewState.focusInterface(layoutNode.ref_id)" in panel_js
    assert "createInterfaceWorkflowSimulation" in panel_js
    assert "window.requestAnimationFrame(tick)" in panel_js
    assert "interfaceWorkflowGraphSimulation.isSettled()" in panel_js
    assert "Math.max(0.35" in panel_js


def _extract_javascript_function(source: str, marker: str) -> str:
    start = source.index(marker)
    opening = source.index("{", start)
    depth = 0
    quote = ""
    escaped = False
    line_comment = False
    block_comment = False
    index = opening
    while index < len(source):
        char = source[index]
        next_char = source[index + 1] if index + 1 < len(source) else ""
        if line_comment:
            if char in "\n":
                line_comment = False
        elif block_comment:
            if char == "*" and next_char == "/":
                block_comment = False
                index += 1
        elif quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        elif char in "'\"`":
            quote = char
        elif char == "/" and next_char == "/":
            line_comment = True
            index += 1
        elif char == "/" and next_char == "*":
            block_comment = True
            index += 1
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
        index += 1
    raise AssertionError(f"unterminated JavaScript function: {marker}")


def test_interface_workflow_correction_opens_existing_full_image_box_editor() -> None:
    html = Path("app/web_panel/index.html").read_text(encoding="utf-8-sig")
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    handler_start = panel_js.index('on("interfaceWorkflowReviewToolsToggle"')
    handler_end = panel_js.index("\n  });", handler_start) + len("\n  });")
    handler_body = panel_js[handler_start:handler_end]
    function_body = _extract_javascript_function(
        panel_js,
        "async function openCurrentInterfaceWorkflowBoxEditor",
    )

    assert "openCurrentInterfaceWorkflowBoxEditor" in handler_body
    assert "setInterfaceWorkflowCorrectionOpen" not in handler_body
    assert "function openCurrentInterfaceWorkflowBoxEditor" in panel_js
    correction_open_index = function_body.index("setInterfaceWorkflowCorrectionOpen(true, view);")
    current_source_index = function_body.index("if (currentLearningDraftReviewMatchesSource(sourcePath))")
    assert correction_open_index < current_source_index
    assert "await loadLearningDraftReview({" in panel_js
    assert "skipWorkflowReview: true" in panel_js
    assert "discoverRelatedSidecars: false" in function_body
    assert "supersedePendingLoad: true" in function_body
    assert "skipReviewRender: true" in function_body
    load_review_start = panel_js.index("async function loadLearningDraftReview")
    load_review_end = panel_js.index("async function saveLearningDraftReview", load_review_start)
    load_review_body = panel_js[load_review_start:load_review_end]
    assert "discover_related_sidecars: options.discoverRelatedSidecars !== false" in load_review_body
    assert "options.supersedePendingLoad !== true" in load_review_body
    assert "loadRequestToken !== learningDraftReviewLoadRequestToken" in load_review_body
    assert "learningDraftReview = data;" in load_review_body
    assert "if (!options.skipReviewRender)" in load_review_body
    assert "function interfaceWorkflowEditableImagePath" in panel_js
    assert 'entry?.layer === "source"' in panel_js
    editable_image_body = _extract_javascript_function(
        panel_js,
        "function interfaceWorkflowEditableImagePath",
    )
    assert "view?.active_image_path" not in editable_image_body
    assert "const editorImagePath = interfaceWorkflowEditableImagePath(view);" in function_body
    assert "const currentEditorImagePath = learningDraftSourceImagePath(learningDraftReview?.draft || {})" in function_body
    assert "const loadedEditorImagePath = learningDraftSourceImagePath(review.draft);" in function_body
    assert 'if (!loadedEditorImagePath)' in function_body
    assert "当前界面缺少可编辑原图" in function_body
    assert "openLearningDraftBoxEditor(currentEditorImagePath)" in function_body
    assert "openLearningDraftBoxEditor(loadedEditorImagePath)" in function_body
    assert function_body.index("const loadedEditorImagePath") > function_body.index(
        "await loadLearningDraftReview({"
    )
    assert "openLearningDraftBoxEditor(view.active_image_path)" not in function_body
    assert "function currentLearningDraftReviewMatchesSource" in panel_js
    assert "currentLearningDraftReviewMatchesSource(sourcePath)" in function_body
    assert function_body.index("currentLearningDraftReviewMatchesSource(sourcePath)") < function_body.index(
        "await loadLearningDraftReview({"
    )
    assert 'title: "正在加载框编辑器..."' in function_body
    assert function_body.index('title: "正在加载框编辑器..."') < function_body.index(
        "await loadLearningDraftReview({"
    )
    assert "closeImageInspector();" in function_body
    assert "setInterfaceWorkflowCorrectionOpen(false);" in function_body
    assert function_body.index('toggle.textContent = "正在打开框编辑器...";') < function_body.index(
        "await loadLearningDraftReview({"
    )
    assert 'id="interfaceWorkflowBoxEditorStatus"' in html
    assert 'role="status"' in html[html.index('id="interfaceWorkflowBoxEditorStatus"') - 120 :]
    assert "setInterfaceWorkflowBoxEditorStatus" in function_body
    assert '"正在加载可编辑证据…"' in function_body
    assert '"当前界面没有可编辑的学习证据"' in function_body
    assert '"当前界面学习证据加载失败"' in function_body
    assert "catch (error)" in function_body
    assert '"无法打开修正工具"' in function_body


def test_interface_workflow_box_editor_prefers_saved_editable_evidence_projection() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    function_start = panel_js.index("function interfaceWorkflowEditableReviewSourcePath")
    function_end = panel_js.index("\n}\n", function_start) + 2
    function_body = panel_js[function_start:function_end]

    assert "editable_review_source_path" in function_body
    assert "source_paths" in function_body


def test_reviewed_node_refresh_preserves_the_saved_multi_interface_graph() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    helper_start = panel_js.index("function applyReviewedEvidenceToCurrentWorkflowNode")
    helper_end = panel_js.index("\n}\n", helper_start) + 2
    helper_body = panel_js[helper_start:helper_end]
    refresh_start = panel_js.index("async function refreshSavedLearningDraftReview")
    refresh_end = panel_js.index("\n}\n", refresh_start) + 2
    refresh_body = panel_js[refresh_start:refresh_end]

    assert "replaceReviewedNodeEvidenceBySource" in helper_body
    assert "previousSourcePath" in helper_body
    assert "reviewedPath" in helper_body
    assert "regions" in helper_body
    assert "action_candidates" in helper_body
    assert "saveInterfaceWorkflowReview({ commitEditor: false })" in refresh_body
    assert "applyReviewedEvidenceToCurrentWorkflowNode" in refresh_body
    assert "loadInterfaceWorkflowReview" not in refresh_body
    assert "interfaceWorkflowEditableReviewSourcePath(view)" in panel_js

    save_start = panel_js.index("async function saveInterfaceWorkflowReview")
    save_end = panel_js.index("\nasync function loadInterfaceWorkflowReview", save_start)
    save_body = panel_js[save_start:save_end]
    assert "{ commitEditor = true } = {}" in save_body
    assert "commitEditor" in save_body
    assert "interfaceWorkflowReviewState.snapshot()" in save_body


def test_interface_workflow_refresh_skips_related_sidecar_discovery() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    load_start = panel_js.index("async function loadInterfaceWorkflowReview")
    load_end = panel_js.index("async function addInterfaceWorkflowSource", load_start)
    load_body = panel_js[load_start:load_end]
    refresh_start = panel_js.index("async function refreshSavedLearningDraftReview")
    refresh_end = panel_js.index("async function refreshCurrentInterfaceWorkflowEvidence", refresh_start)
    refresh_body = panel_js[refresh_start:refresh_end]

    assert "discover_related_sidecars: options.discoverRelatedSidecars !== false" in load_body
    assert "discoverRelatedSidecars: false" in refresh_body


def test_interface_workflow_graph_draws_plain_small_text_on_links() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    start = panel_js.index("function drawInterfaceWorkflowGraphLink")
    end = panel_js.index("\nfunction drawInterfaceWorkflowGraphNode", start)
    body = panel_js[start:end]
    label_body = body[body.index("const label =") :]

    assert "interfaceWorkflowEdgeLabelLayout" in label_body
    assert "labelLayout.visible" in label_body
    assert "labelLayout.max_width" in label_body
    assert "labelLayout.font_size" in label_body
    assert "interfaceWorkflowGraphText(ctx, label" in label_body
    assert "interfaceWorkflowGraphRoundedRect" not in label_body
    assert 'rgba(255, 255, 255' not in label_body


def test_interface_workflow_graph_keeps_evidence_visible_below_compact_canvas() -> None:
    panel_css = Path("app/web_panel/panel.css").read_text(encoding="utf-8-sig")
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    assert "height: clamp(300px, 38vh, 460px);" in panel_css
    assert ".interface-workflow-graph-stage" in panel_css
    assert "#interfaceWorkflowGraphCanvas" in panel_css
    assert "height: 100%;" in panel_css
    assert "Math.max(280, Number(stage?.clientHeight" in panel_js
    assert "Math.max(520, Number(stage?.clientHeight" not in panel_js


def test_interface_workflow_graph_measures_labels_with_the_selected_font() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    start = panel_js.index("function interfaceWorkflowGraphText")
    end = panel_js.index("\nfunction interfaceWorkflowGraphCurve", start)
    body = panel_js[start:end]

    assert body.index("ctx.font =") < body.index("ctx.measureText")


def test_interface_workflow_operation_selection_highlights_only_verified_target_evidence() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    assert "resolveInterfaceWorkflowTargetEvidence" in panel_js
    assert "interfaceWorkflowEvidenceTargetHighlight" in panel_js
    assert "目标证据不可用" in panel_js
    assert "|| operations[0]" not in panel_js
    assert "renderInterfaceWorkflowEvidence(view)" in panel_js
    assert "renderInterfaceWorkflowGraph(interfaceWorkflowReviewState?.graph()" in panel_js


def test_interface_workflow_panel_composes_multiple_history_sources_without_losing_edits() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    assert "let interfaceWorkflowDraftSourcePaths = []" in panel_js
    assert "function setInterfaceWorkflowSourceOptions" in panel_js
    assert "async function addInterfaceWorkflowSource" in panel_js
    assert "async function removeCurrentInterfaceWorkflowSource" in panel_js
    assert "mergeEditableWorkflowReview" in panel_js
    assert "commitInterfaceWorkflowEditorToState" in panel_js
    assert 'on("interfaceWorkflowAddSourceBtn", "click", addInterfaceWorkflowSource)' in panel_js
    assert 'on("interfaceWorkflowSourcePreviewBtn", "click", previewInterfaceWorkflowSource)' in panel_js
    assert 'on("interfaceWorkflowRemoveSourceBtn", "click", removeCurrentInterfaceWorkflowSource)' in panel_js


def test_interface_asset_attach_uses_explicit_dialog() -> None:
    html = Path("app/web_panel/index.html").read_text(encoding="utf-8-sig")
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    assert 'id="interfaceAssetAttachDialog"' in html
    assert 'id="interfaceAssetAttachDialogCloseBtn"' in html
    assert 'id="interfaceAssetAttachOnlyBtn"' in html
    assert 'id="interfaceAssetAttachAndConnectBtn"' in html
    assert 'id="interfaceAssetAttachWarning"' in html
    assert 'class="interface-workflow-source-controls" hidden' not in html
    assert "function openInterfaceAssetAttachDialog" in panel_js
    assert "function closeInterfaceAssetAttachDialog" in panel_js
    assert 'on("interfaceAssetAttachOnlyBtn", "click"' in panel_js
    assert 'on("interfaceAssetAttachAndConnectBtn", "click"' in panel_js


def test_interface_workflow_add_copy_does_not_imply_automatic_linking() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    assert 'interface_workflow_add: "加入流程"' in panel_js
    assert 'interface_workflow_add: "加入并连接"' not in panel_js


def test_learning_draft_add_mode_immediately_updates_overlay_pointer_state() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    start = panel_js.index("function updateLearningDraftEditorControls")
    end = panel_js.index("\nfunction applyLearningDraftEditorMetadataFromControls", start)
    body = panel_js[start:end]

    assert '$("imageInspectorDraftBoxes")' in body
    assert 'classList.toggle("is-add-mode", learningDraftEditorAddMode)' in body


def test_learning_draft_role_change_preserves_pending_metadata_before_rerender() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    start = panel_js.index('$(' + '"imageInspectorRoleSelect"' + ')?.addEventListener("change"')
    end = panel_js.index('\n  $("imageInspectorParentSelect")', start)
    body = panel_js[start:end]

    assert "applyLearningDraftEditorMetadataFromControls();" in body
    assert body.index("applyLearningDraftEditorMetadataFromControls();") < body.index('op: "update_role"')

    parent_start = panel_js.index('$("imageInspectorParentSelect")?.addEventListener("change"')
    parent_end = panel_js.index('\n  [', parent_start)
    parent_body = panel_js[parent_start:parent_end]
    assert "applyLearningDraftEditorMetadataFromControls();" in parent_body
    assert parent_body.index("applyLearningDraftEditorMetadataFromControls();") < parent_body.index('op: "update_parent"')


def test_interface_workflow_panel_loads_saved_workflows_by_application() -> None:
    html = Path("app/web_panel/index.html").read_text(encoding="utf-8-sig")
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    assert 'id="interfaceWorkflowLibrarySelect"' in html
    assert 'id="interfaceWorkflowLoadSavedBtn"' in html
    assert 'class="interface-workflow-existing-selector"' in html
    assert 'class="interface-workflow-existing-selector" hidden' not in html
    assert 'id="interfaceWorkflowCreateBtn"' in html
    assert 'id="interfaceWorkflowOpenFolderBtn"' in html
    assert 'id="interfaceWorkflowNewNameInput"' in html
    assert 'id="interfaceWorkflowLibraryStatus"' in html
    assert '"/memory/interface_workflows/registry"' in panel_js
    assert "/memory/interface_workflows/review_context?application_identity_key=" in panel_js
    assert "workflow_id=${encodeURIComponent(workflowId)}" in panel_js
    assert "async function loadSavedInterfaceWorkflowReview" in panel_js
    assert "async function createInterfaceWorkflow" in panel_js
    assert 'on("interfaceWorkflowLoadSavedBtn", "click", loadSavedInterfaceWorkflowReview)' in panel_js
    assert 'on("interfaceWorkflowCreateBtn", "click", createInterfaceWorkflow)' in panel_js
    assert 'on("interfaceWorkflowOpenFolderBtn", "click"' in panel_js


def test_interface_workflow_panel_supports_confirmed_evidence_and_workflow_deletion() -> None:
    html = Path("app/web_panel/index.html").read_text(encoding="utf-8-sig")
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    panel_api = Path("app/api/panel.py").read_text(encoding="utf-8-sig")

    assert 'id="interfaceWorkflowDeleteBtn"' in html
    assert "interface-asset-list-delete" in panel_js
    assert "async function deleteInterfaceAssetEvidence" in panel_js
    assert "async function deleteSelectedInterfaceWorkflow" in panel_js
    assert '"/panel/delete_learning_evidence"' in panel_js
    assert '"/panel/delete_interface_workflow"' in panel_js
    assert "window.confirm" in panel_js
    assert 'on("interfaceWorkflowDeleteBtn", "click", deleteSelectedInterfaceWorkflow)' in panel_js
    assert '@router.post("/panel/delete_learning_evidence"' in panel_api
    assert '@router.post("/panel/delete_interface_workflow"' in panel_api


def test_adding_a_single_interface_does_not_create_a_transition() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    start = panel_js.index("async function addInterfaceWorkflowSource")
    end = panel_js.index("\nasync function removeCurrentInterfaceWorkflowSource", start)
    body = panel_js[start:end]

    assert "addInterfaceNode" in body
    assert "addOperation" not in body
    assert "interfaceWorkflowAttachFromNodeSelect" not in body
    assert "interfaceWorkflowAttachActionType" not in body
    assert "interfaceWorkflowAttachTargetControl" not in body
    assert "界面已加入流程，尚未连接" in body


def test_adding_a_single_interface_preserves_name_entered_before_preview_reload() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    start = panel_js.index("async function addInterfaceWorkflowSource")
    end = panel_js.index("\nasync function removeCurrentInterfaceWorkflowSource", start)
    body = panel_js[start:end]

    captured_at = body.index("const requestedDisplayName")
    previewed_at = body.index("await previewInterfaceWorkflowSource()")

    assert captured_at < previewed_at
    assert "newNode.display_name = requestedDisplayName" in body


def test_workflow_graph_context_menu_supports_link_creation_and_link_removal() -> None:
    html = Path("app/web_panel/index.html").read_text(encoding="utf-8-sig")
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    assert 'data-interface-workflow-context-action="start-link"' in html
    assert 'id="interfaceWorkflowGraphContextEdges"' in html
    assert 'data-interface-workflow-context-action="delete-edge"' in panel_js
    assert "deleteInterfaceWorkflowGraphEdge" in panel_js


def test_panel_exposes_only_the_fixed_learned_workflow_folder() -> None:
    panel_api = Path("app/api/panel.py").read_text(encoding="utf-8-sig")

    assert 'INTERFACE_WORKFLOW_DIR = ROOT_DIR / "artifacts" / "interface-workflow-reviews"' in panel_api
    assert '@router.post("/panel/open_interface_workflow_folder"' in panel_api


def test_interface_workflow_panel_reopens_saved_workflows_after_boot_and_save() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    registry_start = panel_js.index("async function loadInterfaceWorkflowLibraryRegistry")
    registry_end = panel_js.index("\nasync function loadSavedInterfaceWorkflowReview", registry_start)
    registry_body = panel_js[registry_start:registry_end]
    save_start = panel_js.index("async function saveInterfaceWorkflowReview")
    save_end = panel_js.index("\nasync function loadInterfaceWorkflowReview", save_start)
    save_body = panel_js[save_start:save_end]
    boot_start = panel_js.index("async function boot")
    boot_body = panel_js[boot_start:]

    assert "preferredWorkflowId" in registry_body
    assert "openSelected" in registry_body
    assert "await loadSavedInterfaceWorkflowReview()" in registry_body
    assert "response.data?.workflow_id" in save_body
    assert "openSelected: true" in save_body
    assert "selectedNodeId" in save_body
    assert "interfaceWorkflowReviewState.select(selectedNodeId)" in save_body
    assert "renderInterfaceWorkflowReviewSelection()" in save_body
    assert "await loadInterfaceWorkflowLibraryRegistry({" in boot_body
    assert "openSelected: true" in boot_body
    assert boot_body.index("await loadInterfaceWorkflowLibraryRegistry({") < boot_body.index(
        "await loadLearningDetailObserveSources()"
    )


def test_recent_single_interface_load_does_not_replace_open_saved_workflow() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    start = panel_js.index("async function maybeLoadCurrentLearningDraftReview")
    end = panel_js.index("\nfunction setLearnReplaySubview", start)
    body = panel_js[start:end]
    load_start = panel_js.index("async function loadLearningDraftReview")
    load_end = panel_js.index("\nasync function saveLearningDraftReview", load_start)
    load_body = panel_js[load_start:load_end]
    clear_start = panel_js.index("function clearLearningDraftReviewDisplay")
    clear_end = panel_js.index("\nfunction renderLearningCorrectionMemoryRegistry", clear_start)
    clear_body = panel_js[clear_start:clear_end]

    assert 'const options = { skipResponse: true };' in body
    assert 'typeof interfaceWorkflowReviewState !== "undefined"' in body
    assert "options.skipWorkflowReview = true" in body
    assert "preserveWorkflowReview: options.skipWorkflowReview === true" in load_body
    assert "if (!options.preserveWorkflowReview) clearInterfaceWorkflowReview(reason)" in clear_body


def test_saved_workflow_member_open_prefers_snapshot_identity_over_source_builder() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    start = panel_js.index("async function openInterfaceWorkflowReviewGroupNode")
    end = panel_js.index("\nfunction showInterfaceAssetPage", start)
    body = panel_js[start:end]

    assert "resolveInterfaceAssetOpenTarget" in body
    assert 'target.mode === "saved_workflow"' in body
    assert 'target.mode === "source_preview"' in body
    assert body.index('target.mode === "saved_workflow"') < body.index(
        'target.mode === "source_preview"'
    )


def test_existing_workflow_review_save_and_remove_never_rebuild_from_source_files() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    refresh_start = panel_js.index("async function refreshSavedLearningDraftReview")
    refresh_end = panel_js.index("\nasync function refreshCurrentInterfaceWorkflowEvidence", refresh_start)
    refresh_body = panel_js[refresh_start:refresh_end]
    remove_start = panel_js.index("async function removeCurrentInterfaceWorkflowSource")
    remove_end = panel_js.index("\nfunction renderLearningDraftReview", remove_start)
    remove_body = panel_js[remove_start:remove_end]

    assert "loadInterfaceWorkflowReview" not in refresh_body
    assert "removeInterfaceNode" in remove_body
    assert "loadInterfaceWorkflowReview" not in remove_body
    assert "saveInterfaceWorkflowReview" in remove_body

    draft_start = panel_js.index("async function loadLearningDraftReview")
    draft_end = panel_js.index("\nasync function saveLearningDraftReview", draft_start)
    draft_body = panel_js[draft_start:draft_end]
    assert "loadInterfaceWorkflowReview" not in draft_body

    add_start = panel_js.index("async function addInterfaceWorkflowSource")
    add_end = panel_js.index("\nasync function removeCurrentInterfaceWorkflowSource", add_start)
    add_body = panel_js[add_start:add_end]
    assert "previewInterfaceWorkflowSource" in add_body


def test_interface_workflow_library_prefers_newest_saved_workflow() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    start = panel_js.index("function setInterfaceWorkflowLibraryOptions")
    end = panel_js.index("\nasync function loadInterfaceWorkflowLibraryRegistry", start)
    body = panel_js[start:end]

    assert "preferredWorkflowId" in body
    assert "workflowOrder" in body
    assert ".sort(" in body
    assert "options[0]?.workflowId" in body


def test_learning_draft_load_failure_replaces_loading_state() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    start = panel_js.index("async function loadLearningDraftReview")
    end = panel_js.index("\nasync function saveLearningDraftReview", start)
    body = panel_js[start:end]

    assert "clearLearningDraftReviewDisplay(`加载失败 · ${sourcePath}`)" in body
    assert "catch (error)" in body


def test_panel_contains_reviewed_operation_toolbar() -> None:
    html = Path("app/web_panel/index.html").read_text(encoding="utf-8-sig")
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    for element_id in (
        "interfaceWorkflowOperationList",
        "interfaceWorkflowOperationType",
        "interfaceWorkflowOperationLabel",
        "interfaceWorkflowOperationTargetControl",
        "interfaceWorkflowOperationTargetNode",
        "interfaceWorkflowOperationPlaceholderName",
        "interfaceWorkflowOperationConfirmation",
        "interfaceWorkflowOperationAddBtn",
        "interfaceWorkflowOperationUpdateBtn",
        "interfaceWorkflowOperationDeleteBtn",
        "interfaceWorkflowOperationDryRunBtn",
        "interfaceWorkflowOperationStatus",
    ):
        assert f'id="{element_id}"' in html

    assert "function addInterfaceWorkflowOperation" in panel_js
    assert "function updateInterfaceWorkflowOperation" in panel_js
    assert "function removeInterfaceWorkflowOperation" in panel_js
    assert "function createInterfaceWorkflowPlaceholderNode" in panel_js


def test_workflow_graph_link_creation_uses_hidden_modal_without_scrolling() -> None:
    html = Path("app/web_panel/index.html").read_text(encoding="utf-8-sig")
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    assert 'id="interfaceWorkflowLinkDialog"' in html
    assert 'id="interfaceWorkflowLinkDialogSource"' in html
    assert 'id="interfaceWorkflowLinkDialogTarget"' in html
    assert 'id="interfaceWorkflowLinkDialogBody"' in html
    assert 'id="interfaceWorkflowLinkDialogCancelBtn"' in html
    assert 'id="interfaceWorkflowLinkDialogSaveBtn"' in html
    assert 'id="interfaceWorkflowOperationToolbar"' in html
    assert '<dialog class="interface-workflow-link-dialog" id="interfaceWorkflowLinkDialog">' in html

    start = panel_js.index("function completeInterfaceWorkflowGraphLink")
    end = panel_js.index("\nfunction ", start + 20)
    body = panel_js[start:end]

    assert "openInterfaceWorkflowLinkDialog(link)" in body
    assert "setInterfaceWorkflowCorrectionOpen(true)" not in body
    assert "scrollIntoView" not in body
    assert "function openInterfaceWorkflowLinkDialog" in panel_js
    assert "function closeInterfaceWorkflowLinkDialog" in panel_js
    assert 'on("interfaceWorkflowLinkDialogSaveBtn", "click"' in panel_js
    assert 'on("interfaceWorkflowLinkDialogCancelBtn", "click"' in panel_js


def test_workflow_link_control_pick_uses_dedicated_modal_and_resumes_link_editor() -> None:
    html = Path("app/web_panel/index.html").read_text(encoding="utf-8-sig")
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    for element_id in (
        "interfaceWorkflowEvidenceAnchor",
        "interfaceWorkflowControlPickerDialog",
        "interfaceWorkflowControlPickerDialogBody",
        "interfaceWorkflowControlPickerDialogCancelBtn",
    ):
        assert f'id="{element_id}"' in html

    start = panel_js.index("function startInterfaceWorkflowOperationControlPick")
    end = panel_js.index("\nfunction ", start + 20)
    start_body = panel_js[start:end]
    select = panel_js.index("function selectInterfaceWorkflowEvidenceControl")
    select_end = panel_js.index("\nfunction ", select + 20)
    select_body = panel_js[select:select_end]

    assert "openInterfaceWorkflowControlPickerDialog()" in start_body
    assert "scrollIntoView" not in start_body
    assert "closeInterfaceWorkflowControlPickerDialog({ resumeLinkDialog: true })" in select_body
    assert "function openInterfaceWorkflowControlPickerDialog" in panel_js
    assert "function closeInterfaceWorkflowControlPickerDialog" in panel_js
    assert 'on("interfaceWorkflowControlPickerDialogCancelBtn", "click"' in panel_js


def test_reviewed_operation_dry_run_never_requests_execution() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    start = panel_js.index("async function dryRunInterfaceWorkflowOperation")
    end = panel_js.index("\nasync function ", start + 20)
    body = panel_js[start:end]

    assert '"/action/execute_recognition_plan"' in body
    assert "capture_live: true" in body
    assert "dry_run: true" in body
    assert "action_executed=false" in body
    assert "dry_run: false" not in body


def test_interface_workflow_editor_keeps_unsaved_status_after_rerender() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    start = panel_js.index("function renderInterfaceWorkflowEditor")
    end = panel_js.index("\nfunction renderInterfaceWorkflowReview", start)
    body = panel_js[start:end]

    assert "interfaceWorkflowHasUnsavedChanges" in body
    assert "有未保存修改 · 保存后才能安全验证" in body


def test_interface_workflow_content_semantics_editor_is_available() -> None:
    html = Path("app/web_panel/index.html").read_text(encoding="utf-8-sig")
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    for element_id in (
        "interfaceWorkflowContentEditor",
        "interfaceWorkflowContentTarget",
        "interfaceWorkflowContentBehavior",
        "interfaceWorkflowContentAgentUsage",
        "interfaceWorkflowContentReadPolicy",
        "interfaceWorkflowContentDescription",
        "interfaceWorkflowContentSaveBtn",
        "interfaceWorkflowContentStatus",
    ):
        assert f'id="{element_id}"' in html

    assert "function renderInterfaceWorkflowContentEditor" in panel_js
    assert "function saveInterfaceWorkflowContentDescriptor" in panel_js
    assert "content_descriptors" in panel_js
    assert "Agent 只在当前观察中读取动态值" in html


def _write_managed_scoped_capture_segments(directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    first = directory / "first.png"
    second = directory / "second.png"
    first_rows = [(index * 37 + 11) % 251 for index in range(32)]
    second_rows = first_rows[-16:] + [(index * 53 + 19) % 251 for index in range(16)]
    for path, rows in ((first, first_rows), (second, second_rows)):
        image = Image.new("L", (10, len(rows)))
        image.putdata([(value + column * 17) % 256 for value in rows for column in range(10)])
        image.convert("RGB").save(path)
    return first, second


def _scoped_capture_request(segment_records: list[dict]) -> dict:
    return {
        "segment_records": segment_records,
        "roi": {"x": 0, "y": 0, "width": 10, "height": 32},
        "viewport": {"width": 10, "height": 32},
        "stop_reason": "reached_bottom",
    }


def test_panel_composes_managed_scoped_capture_and_preserves_evidence(tmp_path: Path) -> None:
    source_dir = Path("artifacts") / "tests" / f"scoped-capture-panel-{tmp_path.name}"
    first, second = _write_managed_scoped_capture_segments(source_dir)
    trace_path = source_dir / "scroll-trace.json"
    trace_path.write_text('{"changed": true}\n', encoding="utf-8")
    client = TestClient(app)
    response_data: dict | None = None
    try:
        request = _scoped_capture_request(
            [
                {
                    "image_path": str(first),
                    "capture_id": "capture-first",
                    "scroll_trace_path": str(trace_path),
                    "scroll_effect": {"changed": True, "delta": 16},
                },
                {"image_path": str(second), "capture_id": "capture-second"},
            ]
        )
        request["output_dir"] = str(tmp_path / "caller-selected-output")

        response = client.post("/panel/compose_scoped_learning_capture", json=request)

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        response_data = payload["data"]
        composite_path = Path(response_data["composite_path"])
        manifest_path = Path(response_data["manifest_path"])
        expected_root = (panel_api.ROOT_DIR / "artifacts" / "learning-runs" / "scoped-capture").resolve()
        assert composite_path.is_absolute() and composite_path.is_file()
        assert manifest_path.is_absolute() and manifest_path.is_file()
        assert expected_root in composite_path.parents
        assert expected_root in manifest_path.parents
        assert not (tmp_path / "caller-selected-output").exists()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["segments"][0]["capture_id"] == "capture-first"
        assert manifest["segments"][0]["scroll_trace_path"] == str(trace_path.resolve())
        assert manifest["segments"][0]["scroll_effect"] == {"changed": True, "delta": 16}
        assert response_data["capture_contract_version"] == "scoped_learning_capture_v1"
        assert response_data["capture_mode"] == "scoped_long"
        assert response_data["artifact_is_authorization"] is False
        assert response_data["historical_coordinates_are_priors"] is True
        assert response_data["runtime_execution_allowed"] is False
        assert response_data["scroll_executed_by_this_route"] is False
    finally:
        if response_data:
            shutil.rmtree(Path(response_data["manifest_path"]).parent, ignore_errors=True)
        shutil.rmtree(source_dir, ignore_errors=True)


def test_panel_rejects_unmanaged_scoped_capture_segment_before_builder(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        panel_api,
        "build_scoped_capture_artifact",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("builder must not run")),
    )
    response = TestClient(app).post(
        "/panel/compose_scoped_learning_capture",
        json=_scoped_capture_request([{"image_path": str(tmp_path / "outside.png")}]),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "invalid_scoped_capture_path"


def test_panel_rejects_unmanaged_scoped_capture_scroll_trace_before_builder(tmp_path: Path, monkeypatch) -> None:
    source_dir = Path("artifacts") / "tests" / f"scoped-capture-panel-{tmp_path.name}"
    first, _ = _write_managed_scoped_capture_segments(source_dir)
    outside_trace = tmp_path / "outside-trace.json"
    outside_trace.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        panel_api,
        "build_scoped_capture_artifact",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("builder must not run")),
    )
    try:
        response = TestClient(app).post(
            "/panel/compose_scoped_learning_capture",
            json=_scoped_capture_request(
                [{"image_path": str(first), "scroll_trace_path": str(outside_trace)}]
            ),
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is False
        assert payload["error"]["code"] == "invalid_scoped_capture_path"
    finally:
        shutil.rmtree(source_dir, ignore_errors=True)


def _fail_scoped_capture_runtime_boundary(*args, **kwargs):
    raise AssertionError("scoped composition route must stay offline")


def test_panel_scoped_capture_schema_requires_segment_and_image() -> None:
    client = TestClient(app)
    base_request = _scoped_capture_request([])

    empty_segments = client.post("/panel/compose_scoped_learning_capture", json=base_request)
    empty_image = client.post(
        "/panel/compose_scoped_learning_capture",
        json=_scoped_capture_request([{"image_path": ""}]),
    )

    assert empty_segments.status_code == 422
    assert empty_image.status_code == 422


def test_panel_maps_scoped_capture_composition_failure(tmp_path: Path, monkeypatch) -> None:
    source_dir = Path("artifacts") / "tests" / f"scoped-capture-panel-{tmp_path.name}"
    first, _ = _write_managed_scoped_capture_segments(source_dir)
    try:
        monkeypatch.setattr(
            panel_api,
            "build_scoped_capture_artifact",
            lambda **kwargs: (_ for _ in ()).throw(
                panel_api.ScopedCaptureCompositionError("publish failed")
            ),
        )

        response = TestClient(app).post(
            "/panel/compose_scoped_learning_capture",
            json=_scoped_capture_request([{"image_path": str(first)}]),
        )

        assert response.status_code == 200
        assert response.json()["error"]["code"] == "scoped_capture_composition_failed"
    finally:
        shutil.rmtree(source_dir, ignore_errors=True)


def test_panel_rejects_missing_managed_scoped_capture_segment_before_builder(tmp_path: Path, monkeypatch) -> None:
    missing = Path("artifacts") / "tests" / f"scoped-capture-panel-{tmp_path.name}" / "missing.png"
    monkeypatch.setattr(panel_api, "build_scoped_capture_artifact", _fail_scoped_capture_runtime_boundary)

    response = TestClient(app).post(
        "/panel/compose_scoped_learning_capture",
        json=_scoped_capture_request([{"image_path": str(missing)}]),
    )

    assert response.status_code == 200
    assert response.json()["error"]["code"] == "invalid_scoped_capture_path"


def test_panel_rejects_scoped_capture_traversal_before_builder(monkeypatch) -> None:
    monkeypatch.setattr(panel_api, "build_scoped_capture_artifact", _fail_scoped_capture_runtime_boundary)
    traversal_path = str(Path("artifacts") / "tests" / ".." / ".." / "outside.png")

    response = TestClient(app).post(
        "/panel/compose_scoped_learning_capture",
        json=_scoped_capture_request([{"image_path": traversal_path}]),
    )

    assert response.status_code == 200
    assert response.json()["error"]["code"] == "invalid_scoped_capture_path"


def test_panel_scoped_capture_success_uses_unique_output_dirs_and_stays_offline(
    tmp_path: Path, monkeypatch
) -> None:
    source_dir = Path("artifacts") / "tests" / f"scoped-capture-panel-{tmp_path.name}"
    first, _ = _write_managed_scoped_capture_segments(source_dir)
    for name in (
        "write_trace",
        "model_base_url",
        "run_learning_workflow_readonly_tail",
        "run_model_review_task",
        "run_recognition_task",
        "run_two_stage_understanding_task",
        "start_learning_workflow_stage_operation",
    ):
        monkeypatch.setattr(panel_api, name, _fail_scoped_capture_runtime_boundary)
    response_data: list[dict] = []
    try:
        client = TestClient(app)
        request = _scoped_capture_request([{"image_path": str(first)}])
        for _ in range(2):
            response = client.post("/panel/compose_scoped_learning_capture", json=request)
            assert response.status_code == 200
            payload = response.json()
            assert payload["success"] is True
            response_data.append(payload["data"])

        output_dirs = {Path(data["manifest_path"]).parent for data in response_data}
        assert len(output_dirs) == 2
        assert all(directory.is_dir() for directory in output_dirs)
    finally:
        for data in response_data:
            shutil.rmtree(Path(data["manifest_path"]).parent, ignore_errors=True)
        shutil.rmtree(source_dir, ignore_errors=True)


def test_panel_maps_invalid_scoped_capture_roi_to_input_error(tmp_path: Path) -> None:
    source_dir = Path("artifacts") / "tests" / f"scoped-capture-panel-{tmp_path.name}"
    first, _ = _write_managed_scoped_capture_segments(source_dir)
    try:
        request = _scoped_capture_request([{"image_path": str(first)}])
        request["roi"] = {"x": 0, "y": 0, "width": 11, "height": 32}

        response = TestClient(app).post("/panel/compose_scoped_learning_capture", json=request)

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is False
        assert payload["error"]["code"] == "invalid_scoped_capture_input"
    finally:
        shutil.rmtree(source_dir, ignore_errors=True)


def test_panel_maps_invalid_scoped_capture_stop_reason_to_input_error(tmp_path: Path) -> None:
    source_dir = Path("artifacts") / "tests" / f"scoped-capture-panel-{tmp_path.name}"
    first, _ = _write_managed_scoped_capture_segments(source_dir)
    try:
        request = _scoped_capture_request([{"image_path": str(first)}])
        request["stop_reason"] = "not-a-builder-stop-reason"

        response = TestClient(app).post("/panel/compose_scoped_learning_capture", json=request)

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is False
        assert payload["error"]["code"] == "invalid_scoped_capture_input"
    finally:
        shutil.rmtree(source_dir, ignore_errors=True)


def test_panel_maps_generic_scoped_capture_builder_runtime_error(tmp_path: Path, monkeypatch) -> None:
    source_dir = Path("artifacts") / "tests" / f"scoped-capture-panel-{tmp_path.name}"
    first, _ = _write_managed_scoped_capture_segments(source_dir)
    try:
        monkeypatch.setattr(
            panel_api,
            "build_scoped_capture_artifact",
            lambda **kwargs: (_ for _ in ()).throw(RuntimeError("unexpected composition failure")),
        )

        response = TestClient(app).post(
            "/panel/compose_scoped_learning_capture",
            json=_scoped_capture_request([{"image_path": str(first)}]),
        )

        assert response.status_code == 200
        assert response.json()["error"]["code"] == "scoped_capture_composition_failed"
    finally:
        shutil.rmtree(source_dir, ignore_errors=True)


def test_panel_maps_server_output_resolution_failure_to_composition_error(tmp_path: Path, monkeypatch) -> None:
    import app.learn.scoped_capture as scoped_capture

    source_dir = Path("artifacts") / "tests" / f"scoped-capture-panel-{tmp_path.name}"
    first, _ = _write_managed_scoped_capture_segments(source_dir)

    class FailingOutputPath:
        def expanduser(self):
            return self

        def resolve(self):
            raise OSError("server output resolution failed")

    try:
        monkeypatch.setattr(scoped_capture, "Path", lambda value: FailingOutputPath())

        response = TestClient(app).post(
            "/panel/compose_scoped_learning_capture",
            json=_scoped_capture_request([{"image_path": str(first)}]),
        )

        assert response.status_code == 200
        assert response.json()["error"]["code"] == "scoped_capture_composition_failed"
    finally:
        shutil.rmtree(source_dir, ignore_errors=True)


def test_panel_rejects_existing_traversal_target_before_builder(tmp_path: Path, monkeypatch) -> None:
    outside_path = panel_api.ROOT_DIR.parent / f"scoped-capture-traversal-{tmp_path.name}.png"
    Image.new("RGB", (1, 1), "white").save(outside_path)
    traversal_path = str(panel_api.ROOT_DIR / "artifacts" / ".." / ".." / outside_path.name)
    monkeypatch.setattr(panel_api, "build_scoped_capture_artifact", _fail_scoped_capture_runtime_boundary)
    try:
        response = TestClient(app).post(
            "/panel/compose_scoped_learning_capture",
            json=_scoped_capture_request([{"image_path": traversal_path}]),
        )

        assert response.status_code == 200
        assert response.json()["error"]["code"] == "invalid_scoped_capture_path"
    finally:
        outside_path.unlink(missing_ok=True)


def test_panel_scoped_capture_success_never_reaches_runtime_side_effect_boundaries(
    tmp_path: Path, monkeypatch
) -> None:
    from app.api import action as action_api
    from app.api import execute as execute_api
    from app.core import model_server
    from app.core.input_controller import input_controller
    from app.core.screenshot import screenshot_service
    from app.gate import window as gate_window
    from app.operation.vision_protocol import executor_adapter

    source_dir = Path("artifacts") / "tests" / f"scoped-capture-panel-{tmp_path.name}"
    first, _ = _write_managed_scoped_capture_segments(source_dir)
    response_data: dict | None = None
    try:
        monkeypatch.setattr(screenshot_service, "capture_window", _fail_scoped_capture_runtime_boundary)
        monkeypatch.setattr(input_controller, "scroll_window", _fail_scoped_capture_runtime_boundary)
        monkeypatch.setattr(model_server.urllib.request, "urlopen", _fail_scoped_capture_runtime_boundary)
        monkeypatch.setattr(gate_window, "validate_bound_window_for_app", _fail_scoped_capture_runtime_boundary)
        monkeypatch.setattr(action_api, "execute_recognition_plan", _fail_scoped_capture_runtime_boundary)
        monkeypatch.setattr(executor_adapter, "execute_vision_action", _fail_scoped_capture_runtime_boundary)
        monkeypatch.setattr(execute_api, "execute_step", _fail_scoped_capture_runtime_boundary)
        monkeypatch.setattr(execute_api, "_dispatch_low_level_step", _fail_scoped_capture_runtime_boundary)

        response = TestClient(app).post(
            "/panel/compose_scoped_learning_capture",
            json=_scoped_capture_request([{"image_path": str(first)}]),
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        response_data = payload["data"]
        assert response_data["artifact_is_authorization"] is False
        assert response_data["runtime_execution_allowed"] is False
    finally:
        if response_data:
            shutil.rmtree(Path(response_data["manifest_path"]).parent, ignore_errors=True)
        shutil.rmtree(source_dir, ignore_errors=True)



def test_learning_interface_scoped_capture_controls_and_flow_binding_are_present() -> None:
    index_html = Path("app/web_panel/index.html").read_text(encoding="utf-8-sig")
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")

    for control_id in [
        "learningCaptureModeNormal",
        "learningCaptureModeScopedLong",
        "learningScopedCaptureConfirmed",
        "learningScopedCaptureRoiX",
        "learningScopedCaptureRoiY",
        "learningScopedCaptureRoiWidth",
        "learningScopedCaptureRoiHeight",
        "learningScopedCaptureScrollScope",
        "learningScopedCaptureTargetPane",
        "learningScopedCaptureTargetContainerId",
        "learningScopedCaptureWheelClicks",
        "learningScopedCaptureMaxSegments",
        "learningScopedCaptureProgress",
        "learningScopedCaptureCompositePath",
        "learningScopedCaptureManifestPath",
        "learningScopedCaptureArtifactPolicy",
    ]:
        assert f'id="{control_id}"' in index_html
    assert 'id="learningCaptureModeNormal" type="radio" name="learningCaptureMode" value="normal" checked' in index_html
    assert 'id="learningScopedCaptureFields" hidden' in index_html
    assert "\u672a\u8bc4\u4f30\uff0c\u4eba\u5de5\u9009\u62e9\u4e3a\u51c6" in index_html

    strategy_start = panel_js.index("async function runLearningInterfaceCaptureStrategy")
    strategy_end = panel_js.index("async function runLearningScreenObserve", strategy_start)
    strategy_body = panel_js[strategy_start:strategy_end]
    assert "resetScopedLearningCaptureState();" in strategy_body
    assert "runScopedLearningCaptureSequence" in strategy_body
    assert '"/action/scroll"' in strategy_body
    assert '"/panel/compose_scoped_learning_capture"' in strategy_body
    assert "setLearningSourceImagePath(result.image_path)" in strategy_body
    assert 'learningCaptureModeScopedLong")?.checked' in panel_js
    render_start = panel_js.index("function renderScopedLearningCaptureState")
    render_end = panel_js.index("function resetScopedLearningCaptureState", render_start)
    render_body = panel_js[render_start:render_end]
    assert "artifact_is_authorization" in render_body
    assert "historical_coordinates_are_priors" in render_body

    flow_start = panel_js.index("async function runLearningInterfaceFlow")
    flow_body = panel_js[flow_start:panel_js.index("async function completeLearningInterfaceReadonlyFlow", flow_start)]
    assert "runLearningInterfaceCaptureStrategy" in flow_body
    assert "if (!capture?.model_allowed)" in flow_body


def test_learning_interface_scoped_capture_cancellation_aborts_bind_capture_sequence() -> None:
    panel_js = Path("app/web_panel/panel.js").read_text(encoding="utf-8-sig")
    cancel_start = panel_js.index("async function cancelActiveLearningInterfaceFlow")
    cancel_end = panel_js.index("async function runLearningStageTaskWithHeartbeat", cancel_start)
    cancel_body = panel_js[cancel_start:cancel_end]

    assert "activeScopedLearningCaptureContext" in cancel_body
    assert "activeScopedLearningCaptureContext.controller.abort()" in cancel_body
    assert "cancelled" in cancel_body
