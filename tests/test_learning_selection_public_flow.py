from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import subprocess

import pytest


def selection_input(root):
    from app.learn.hybrid.omni_candidates import omni_inventory_from_ledger
    from tests.test_learning_hybrid_vertical_slice import _vertical

    facts = _vertical(root)
    raw = '{"topk_points":[[0.5,0.4]]}'
    payload = {
        "learning_pipeline_mode": "hybrid_v1_2",
        "execution_origin": "replay",
        "gui_actor_provider_state": "replay_ready",
        "run_id": "run-recorded",
        "workflow_revision": 7,
        "capture_image_path": facts["image"].relative_to(root).as_posix(),
        "capture_bundle": facts["bundle"],
        "omni_inventory": omni_inventory_from_ledger(facts["ledger"]),
        "gui_actor_selection_input": {
            "raw_output_utf8": raw,
            "native_output_ref": {"id": "native/replay/public-flow", "sha256": sha256(raw.encode("utf-8")).hexdigest()},
            "provider_id": "gui_actor_3b_bf16",
            "native_profile": {
                "contract_version": "goal_binding_native_profile_v1",
                "provider_id": "gui_actor_3b_bf16",
                "native_shape": "gui_actor_topk_points_v1",
                "coordinate_space": "normalized_0_1",
            },
            "source_score": None,
            "capture_id": facts["bundle"]["capture_identity"]["capture_id"],
            "image_sha256": facts["bundle"]["capture_identity"]["screenshot_sha256"],
        },
        "target_text": "Quick Apply",
        "refinement_policy": {"policy_version": "selection_refinement_conditional_v1", "mode": "conditional", "geometric_trigger": False},
    }
    path = root / "artifacts" / "selection-input.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path, payload


def test_selection_prepare_never_relabels_actual_as_replay(tmp_path):
    from app.learn.workflow_service import prepare_learning_selection_review_replay

    path = tmp_path / "input.json"
    path.write_text(json.dumps({"learning_pipeline_mode": "hybrid_v1_2", "execution_origin": "actual_model"}), encoding="utf-8")
    with pytest.raises(ValueError, match="replay"):
        prepare_learning_selection_review_replay(project_root=tmp_path, source_path=path)


def test_selection_prepare_does_not_intercept_ordinary_draft(tmp_path):
    from app.learn.workflow_service import prepare_learning_selection_review_replay

    path = tmp_path / "draft.json"
    path.write_text('{"contract_version":"learning_template_draft_v1"}', encoding="utf-8")
    assert prepare_learning_selection_review_replay(project_root=tmp_path, source_path=path) is None


def test_selection_prepare_rejects_outside_project(tmp_path):
    from app.learn.workflow_service import prepare_learning_selection_review_replay

    with pytest.raises(ValueError, match="project root"):
        prepare_learning_selection_review_replay(project_root=tmp_path, source_path=tmp_path.parent / "outside.json")


def test_selection_refinement_not_ready_has_no_review_artifact(tmp_path):
    from app.learn.workflow_service import prepare_learning_selection_review_replay

    path, payload = selection_input(tmp_path)
    payload["refinement_policy"]["geometric_trigger"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="refinement_provider_not_ready"):
        prepare_learning_selection_review_replay(project_root=tmp_path, source_path=path)


def test_public_load_edit_save_reload_consumes_the_same_protocol(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import panel

    path, _ = selection_input(tmp_path)
    monkeypatch.setattr(panel, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(panel, "write_trace", lambda **kwargs: "logs/test-trace.json")
    app = FastAPI()
    app.include_router(panel.router)
    client = TestClient(app)
    loaded = client.post("/panel/load_learning_draft_review", json={"source_path": path.relative_to(tmp_path).as_posix(), "discover_related_sidecars": False}).json()
    assert loaded["success"], loaded
    data = loaded["data"]
    assert data["prepared_from_selection_replay"] is True
    projection = data["hybrid_review_projection"]
    assert "hybrid_selection_review_projection" not in data
    selected = next(item for item in projection["candidates"] if item["selection"] is not None)
    candidate_id = selected["candidate_id"]
    assert selected["model_proposal"]["selection"]["source_score"] is None
    assert data["draft"]["regions"]
    pending = client.post("/panel/save_learning_draft_review", json={"source_path": data["trial_path"], "review_patch": {"hybrid_review_decisions": [], "expected_hybrid_review_projection_ref": data["hybrid_review_projection_ref"]}}).json()
    assert pending["success"], pending
    assert pending["data"]["validation_status"] == "blocked_missing_semantics"
    assert not pending["data"].get("runtime_path_graph_candidate_path")
    decisions = [
        {"decision_id": "decision/public-rebox", "decision_type": "rebox", "candidate_id": candidate_id, "bbox": [41, 21, 119, 51]},
        {"decision_id": "decision/public-semantic", "decision_type": "semantic_edit", "candidate_id": candidate_id, "semantics": {"role": "button", "label": "快速申请", "description": "人工确认的按钮"}},
    ]
    saved = client.post("/panel/save_learning_draft_review", json={"source_path": data["trial_path"], "review_patch": {"hybrid_review_decisions": decisions, "expected_hybrid_review_projection_ref": data["hybrid_review_projection_ref"]}}).json()
    assert saved["success"], saved
    saved_path = saved["data"]["reviewed_template_candidate_path"]
    reloaded = client.post("/panel/load_learning_draft_review", json={"source_path": saved_path, "discover_related_sidecars": False}).json()
    assert reloaded["success"], reloaded
    after = reloaded["data"]["hybrid_review_projection"]
    revised = next(item for item in after["candidates"] if item["candidate_id"] == candidate_id)
    assert revised["model_proposal"] == selected["model_proposal"]
    assert revised["reviewed_geometry"]["bbox"] == [41, 21, 119, 51]
    assert revised["reviewed_semantics"]["label"] == "快速申请"
    assert len(after["review_decisions"]) == 2
    # 重新保存完整历史不得把服务端追加字段误判成改写。
    repeated = client.post("/panel/save_learning_draft_review", json={"source_path": saved_path, "review_patch": {"hybrid_review_decisions": after["review_decisions"], "expected_hybrid_review_projection_ref": reloaded["data"]["hybrid_review_projection_ref"]}}).json()
    assert repeated["success"], repeated
    graph = json.loads((tmp_path / saved["data"]["runtime_path_graph_candidate_path"]).read_text(encoding="utf-8"))
    assert any(item.get("label") == "快速申请" for item in graph["regions"])
    assert graph["states"] == []
    assert graph["action_templates"] == []
    assert graph["execute_binding_enabled"] is False


def test_real_panel_selection_patch_is_accepted_by_existing_save_api(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api import panel

    path, _ = selection_input(tmp_path)
    monkeypatch.setattr(panel, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(panel, "write_trace", lambda **kwargs: "logs/test-trace.json")
    app = FastAPI()
    app.include_router(panel.router)
    client = TestClient(app)
    loaded = client.post("/panel/load_learning_draft_review", json={
        "source_path": path.relative_to(tmp_path).as_posix(), "discover_related_sidecars": False,
    }).json()["data"]
    script = r"""
const fs = require('node:fs'), vm = require('node:vm');
const {createHybridReviewState} = require('./app/web_panel/learning_workflow_review.js');
const review = JSON.parse(fs.readFileSync(0, 'utf8'));
const state = createHybridReviewState(review.hybrid_review_projection);
state.editSemantics(review.hybrid_review_projection.selection.candidate_id,
  {role:'button', label:'\u5feb\u901f\u7533\u8bf7', description:'panel contract regression'});
const source = fs.readFileSync('./app/web_panel/panel.js','utf8');
const begin = source.indexOf('function learningDraftReviewPatch');
const end = source.indexOf('\nfunction learningDraftArray',begin);
const context = vm.createContext({structuredClone, learningDraftReview:review, learningHybridReviewState:state,
  $:()=>null, learningDraftManualCandidate:()=>({targetRegionId:review.draft.regions[0].region_id,targetActionTemplateId:''}),
  learningReviewTextareaItems:()=>[], learningDraftOwnershipOperations:()=>[], learningDraftEditorOperations:()=>[],
  learningDraftReviewBboxEdits:{regions:{},actions:{}}});
const imageBegin = source.indexOf('function learningDraftSourceImagePath');
const imageEnd = source.indexOf('\nfunction learningDraftStateId',imageBegin);
vm.runInContext(source.slice(imageBegin,imageEnd),context);
vm.runInContext(source.slice(begin,end),context);
process.stdout.write(JSON.stringify(context.learningDraftReviewPatch()));
"""
    result = subprocess.run(["node", "-e", script], input=json.dumps(loaded, ensure_ascii=False),
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, encoding="utf-8", check=True)
    patch = json.loads(result.stdout)
    saved = client.post("/panel/save_learning_draft_review", json={
        "source_path": loaded["trial_path"], "review_patch": patch,
    }).json()
    assert saved["success"], saved
    for field in ("manual_edit", "operations", "region_bbox_updates", "action_bbox_updates"):
        assert field not in patch
    after = client.post("/panel/load_learning_draft_review", json={
        "source_path": saved["data"]["reviewed_template_candidate_path"], "discover_related_sidecars": False,
    }).json()["data"]["hybrid_review_projection"]
    selected = next(c for c in after["candidates"] if c["selection"] is not None)
    assert selected["reviewed_semantics"]["label"] == "快速申请"
    assert selected["selection"]["model_proposal"]["source_score"] is None
