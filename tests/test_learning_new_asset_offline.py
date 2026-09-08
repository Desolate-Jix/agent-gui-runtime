from __future__ import annotations

import json
import os
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


def _selection_replay_source(tmp_path: Path) -> dict[str, Any]:
    from app.learn.draft_review import load_learning_draft_review, save_reviewed_template_candidate
    from app.learn.hybrid.selection_persistence import persist_selection_review_trial
    from app.learn.workflow_tasks.hybrid_selection import run_hybrid_selection_task
    from tests.test_learning_selection_roundtrip import _payload

    tmp_path.mkdir(parents=True, exist_ok=True)
    _facts, payload = _payload(tmp_path)
    trial = persist_selection_review_trial(
        project_root=tmp_path,
        payload=payload,
        response=run_hybrid_selection_task(payload),
    )
    initial = load_learning_draft_review(trial, project_root=tmp_path)
    selected = next(
        candidate
        for candidate in initial["hybrid_review_projection"]["candidates"]
        if candidate["selection"] is not None
    )
    saved = save_reviewed_template_candidate(
        trial,
        {
            "expected_hybrid_review_projection_ref": initial["hybrid_review_projection_ref"],
            "hybrid_review_decisions": [
                {
                    "decision_id": "decision/s2-rebox",
                    "decision_type": "rebox",
                    "candidate_id": selected["candidate_id"],
                    "bbox": [41, 21, 119, 51],
                },
                {
                    "decision_id": "decision/s2-semantic",
                    "decision_type": "semantic_edit",
                    "candidate_id": selected["candidate_id"],
                    "semantics": {
                        "role": "button",
                        "label": "Quick Apply",
                        "description": "Explicit human review of the replay proposal.",
                    },
                },
            ],
        },
        project_root=tmp_path,
    )
    return load_learning_draft_review(
        saved["reviewed_template_candidate_path"],
        project_root=tmp_path,
        discover_related_sidecars=False,
    )

def _approve_subject(subject: dict[str, Any], subject_kind: str) -> None:
    from app.agent.reviewed_workflow_compiler import (
        _GRANULAR_CONFIRMATION_CONTRACTS,
        _granular_review_revision,
    )

    subject.update(
        review_status="human_approved",
        reviewed_by_human=True,
        display_only=True,
        artifact_is_authorization=False,
        execute_binding_enabled=False,
    )
    subject["human_review_confirmation"] = {
        "contract_version": _GRANULAR_CONFIRMATION_CONTRACTS[subject_kind],
        "revision": _granular_review_revision(subject),
    }


def fresh_selection_replay_review(tmp_path: Path) -> dict[str, Any]:
    from app.learn.interface_workflow_review import (
        build_interface_node_review_revision,
        build_interface_workflow_review,
    )

    source = _selection_replay_source(tmp_path)
    source["draft"]["screen_summary"] = "Job Detail"
    source["draft"]["state_signature"] = "s2-job-detail-selection-replay"
    source["draft"]["action_templates"] = [{
        "action_template_id": "open_apply_entry",
        "semantic_action": "open_apply_flow",
        "target_control_id": "",
        "target_region_id": source["draft"]["regions"][0]["region_id"],
        "target_interface_id": "",
    }]
    boundary_source = json.loads(json.dumps(source))
    boundary_source["draft"].update({
        "screen_summary": "Apply Entry / Choose documents",
        "state_signature": "s2-apply-entry-stop-boundary",
        "regions": [],
        "action_templates": [],
    })
    review = build_interface_workflow_review(
        goal="Offline simulated replay: open the application entry and stop.",
        application_identity={"url": "https://nz.seek.com/jobs/123"},
        draft_sources=[source, boundary_source],
    )
    detail, boundary = review["nodes"]
    detail["node_id"] = "job_detail"
    boundary["node_id"] = "apply_entry"
    review["workflow"]["entry_node_id"] = "job_detail"
    review["workflow"]["node_ids"] = ["job_detail", "apply_entry"]
    review["edges"][0]["source_node_id"] = "job_detail"
    review["edges"][0]["target_node_id"] = "apply_entry"
    detail["review_status"] = "human_approved"
    detail["reviewed_by_human"] = True
    boundary["review_status"] = "needs_learning"
    boundary["reviewed_by_human"] = False
    edge = review["edges"][0]
    edge.update(
        operation_id="open_apply_entry",
        display_name="Open Apply Entry",
        action_type="open_apply_flow",
        semantic_action="open_apply_flow",
        action_template_id="open_apply_entry",
        target_control_id="",
        target_region_id=detail["regions"][0]["region_id"],
        risk_level="medium",
        requires_user_confirmation=True,
        preconditions=["Job Detail identity is visible"],
        success_conditions=["Apply Entry / Choose documents identity is visible"],
        failure_conditions=["Unexpected origin or modal requires a safe stop"],
        review_status="human_approved",
    )
    action = detail["action_candidates"][0]
    action["target_interface_id"] = "apply_entry"
    _approve_subject(detail["regions"][0], "target_control")
    _approve_subject(action, "action_candidate")
    _approve_subject(edge, "edge")
    detail["human_review_confirmation"] = {
        "contract_version": "interface_node_human_review_confirmation_v1",
        "revision": build_interface_node_review_revision(review, node_id=detail["node_id"]),
    }
    review["workflow"]["review_status"] = "human_approved"
    return review


def fresh_selection_replay_review_asset(tmp_path: Path) -> dict[str, Any]:
    from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore
    from app.api import reviewed_workflows
    from app.learn.interface_workflow_service import save_interface_workflow_review_transaction

    review = fresh_selection_replay_review(tmp_path)
    saved = save_interface_workflow_review_transaction(
        review, project_root=tmp_path, out_dir=None
    )
    workflow_id = saved["workflow_id"]
    application_identity_key = saved["application_identity_key"]
    source_sha256 = sha256(Path(saved["path"]).read_bytes()).hexdigest()
    published = reviewed_workflows.publish_reviewed_workflow_asset_endpoint(
        reviewed_workflows.PanelPublishReviewedWorkflowAssetRequest(
            application_identity_key=application_identity_key,
            workflow_id=workflow_id,
            expected_source_workflow_sha256=source_sha256,
            expected_registry_revision=0,
        ),
        project_root=tmp_path,
    )
    assert published.success is True
    asset_id = published.data["publish_result"]["asset_id"]
    asset = ReviewedWorkflowAssetStore(project_root=tmp_path).load_active(asset_id)
    return {
        "review": review,
        "saved": saved,
        "asset": asset,
        "asset_id": asset_id,
        "content_sha256": published.data["publish_result"]["content_sha256"],
        "source_path": Path(saved["path"]),
        "source_sha256": source_sha256,
        "published": published.data["publish_result"],
        "compile_result": published.data["compile_result"],
        "application_identity_key": application_identity_key,
        "workflow_id": workflow_id,
    }



def test_panel_path_publishes_fresh_simulated_selection_replay_asset_and_fresh_process_loads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.panel as panel_api
    from app.main import app

    review = fresh_selection_replay_review(tmp_path)
    detail = review["nodes"][0]
    assert detail["selection_replay_provenance"]["execution_origin"] == "replay"
    assert detail["selection_replay_provenance"]["simulated_offline"] is True
    assert detail["selection_replay_provenance"]["projection_ref"]["id"].startswith("hybrid-selection-review/")
    assert detail["regions"][0]["model_proposal"]["selection"]["provider_id"] == "gui_actor_3b_bf16"
    assert detail["regions"][0]["reviewed_semantics"]["status"] == "human_supplied"

    monkeypatch.setattr(panel_api, "ROOT_DIR", tmp_path)
    with TestClient(app) as client:
        saved = client.post("/panel/save_interface_workflow_review", json={"review": review})
        assert saved.status_code == 200
        saved_body = saved.json()
        assert saved_body["success"] is True
        saved_path = Path(saved_body["data"]["path"])
        saved_review = json.loads(saved_path.read_text(encoding="utf-8"))
        saved_detail = next(node for node in saved_review["nodes"] if node["display_name"] == "Job Detail")
        assert saved_detail["selection_replay_provenance"]["simulated_offline"] is True
        assert saved_detail["regions"][0]["model_proposal"]["selection"]["provider_id"] == "gui_actor_3b_bf16"
        assert saved_detail["regions"][0]["review_decisions"][0]["source"] == "human_review"

        workflow_id = saved_body["data"]["workflow_id"]
        identity_key = saved_body["data"]["application_identity_key"]
        source_sha = sha256(saved_path.read_bytes()).hexdigest()
        compiled = client.post(
            "/panel/compile_reviewed_workflow_asset",
            json={
                "application_identity_key": identity_key,
                "workflow_id": workflow_id,
                "expected_source_workflow_sha256": source_sha,
            },
        )
        assert compiled.status_code == 200
        assert compiled.json()["success"] is True
        assert compiled.json()["data"]["result"]["status"] == "compiled"
        assert not (tmp_path / "runtime_state" / "reviewed-workflow-assets-v2").exists()

        published = client.post(
            "/panel/publish_reviewed_workflow_asset",
            json={
                "application_identity_key": identity_key,
                "workflow_id": workflow_id,
                "expected_source_workflow_sha256": source_sha,
                "expected_registry_revision": 0,
            },
        )
        assert published.status_code == 200
        assert published.json()["success"] is True
        publish_data = published.json()["data"]["publish_result"]

    fresh_load = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore; "
                f"asset=ReviewedWorkflowAssetStore(project_root={str(tmp_path)!r}).load_active({publish_data['asset_id']!r}); "
                "import json; print(json.dumps({'asset_id': asset['asset_id'], 'states': [state['display_name'] for state in asset['states']], 'actions': [transition['semantic_action'] for transition in asset['transitions']], 'authorized': asset['safety']['artifact_is_authorization']}))"
            ),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH": ":memory:"},
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    loaded = json.loads(fresh_load.stdout)
    assert loaded == {
        "asset_id": publish_data["asset_id"],
        "states": ["Apply Entry / Choose documents", "Job Detail"],
        "actions": ["open_apply_flow"],
        "authorized": False,
    }


def test_selection_replay_provenance_missing_or_stale_confirmation_fails_closed(tmp_path: Path) -> None:
    import app.api.panel as panel_api

    missing = fresh_selection_replay_review(tmp_path)
    del missing["nodes"][0]["selection_replay_provenance"]
    original_root = panel_api.ROOT_DIR
    panel_api.ROOT_DIR = tmp_path
    try:
        failed = panel_api.save_interface_workflow_review_endpoint(
            panel_api.PanelSaveInterfaceWorkflowReviewRequest(review=missing)
        )
        assert failed.success is False
        assert failed.error.code == "interface_workflow_review_save_failed"

        forged = fresh_selection_replay_review(tmp_path / "forged")
        forged["nodes"][0]["selection_replay_provenance"].update(
            execution_origin="actual_model",
            simulated_offline=False,
        )
        failed = panel_api.save_interface_workflow_review_endpoint(
            panel_api.PanelSaveInterfaceWorkflowReviewRequest(review=forged)
        )
        assert failed.success is False
        assert failed.error.code == "interface_workflow_review_save_failed"
    finally:
        panel_api.ROOT_DIR = original_root


def _refresh_selection_review_confirmations(review: dict[str, Any]) -> None:
    from app.learn.interface_workflow_review import build_interface_node_review_revision

    detail = review["nodes"][0]
    for region in detail.get("regions", []):
        if isinstance(region, dict):
            _approve_subject(region, "target_control")
    for action in detail.get("action_candidates", []):
        if isinstance(action, dict):
            _approve_subject(action, "action_candidate")
    for edge in review.get("edges", []):
        if isinstance(edge, dict):
            _approve_subject(edge, "edge")
    detail["human_review_confirmation"] = {
        "contract_version": "interface_node_human_review_confirmation_v1",
        "revision": build_interface_node_review_revision(review, node_id=detail["node_id"]),
    }


def test_selection_source_cannot_be_relabelled_as_legacy_to_remove_apply_confirmation(
    tmp_path: Path,
) -> None:
    import app.api.panel as panel_api

    review = fresh_selection_replay_review(tmp_path)
    detail = review["nodes"][0]
    detail.pop("selection_replay_provenance")
    for region in detail["regions"]:
        region["kind"] = "ordinary_region"
        region.pop("provenance", None)
    review["edges"][0].update(risk_level="low", requires_user_confirmation=False)
    _refresh_selection_review_confirmations(review)
    original_root = panel_api.ROOT_DIR
    panel_api.ROOT_DIR = tmp_path
    try:
        failed = panel_api.save_interface_workflow_review_endpoint(
            panel_api.PanelSaveInterfaceWorkflowReviewRequest(review=review)
        )
        assert failed.success is False
        assert failed.error.code == "interface_workflow_review_save_failed"
    finally:
        panel_api.ROOT_DIR = original_root


def test_selection_source_rejects_forged_provider(tmp_path: Path) -> None:
    import app.api.panel as panel_api

    review = fresh_selection_replay_review(tmp_path)
    region = review["nodes"][0]["regions"][0]
    region["model_proposal"]["selection"]["provider_id"] = "forged-provider"
    _refresh_selection_review_confirmations(review)
    original_root = panel_api.ROOT_DIR
    panel_api.ROOT_DIR = tmp_path
    try:
        failed = panel_api.save_interface_workflow_review_endpoint(
            panel_api.PanelSaveInterfaceWorkflowReviewRequest(review=review)
        )
        assert failed.success is False
        assert failed.error.code == "interface_workflow_review_save_failed"
    finally:
        panel_api.ROOT_DIR = original_root


def test_selection_source_rejects_changed_review_ledger(tmp_path: Path) -> None:
    import app.api.panel as panel_api

    review = fresh_selection_replay_review(tmp_path)
    region = review["nodes"][0]["regions"][0]
    region["review_decisions"].append(
        {"decision_id": "forged-ledger-entry", "source": "human_review"}
    )
    _refresh_selection_review_confirmations(review)
    original_root = panel_api.ROOT_DIR
    panel_api.ROOT_DIR = tmp_path
    try:
        failed = panel_api.save_interface_workflow_review_endpoint(
            panel_api.PanelSaveInterfaceWorkflowReviewRequest(review=review)
        )
        assert failed.success is False
        assert failed.error.code == "interface_workflow_review_save_failed"
    finally:
        panel_api.ROOT_DIR = original_root


def test_open_apply_flow_requires_confirmed_medium_or_high_risk(tmp_path: Path) -> None:
    import app.api.panel as panel_api

    review = fresh_selection_replay_review(tmp_path)
    review["edges"][0].update(risk_level="low", requires_user_confirmation=False)
    original_root = panel_api.ROOT_DIR
    panel_api.ROOT_DIR = tmp_path
    try:
        failed = panel_api.save_interface_workflow_review_endpoint(
            panel_api.PanelSaveInterfaceWorkflowReviewRequest(review=review)
        )
        assert failed.success is False
        assert failed.error.code == "interface_workflow_review_save_failed"
    finally:
        panel_api.ROOT_DIR = original_root
