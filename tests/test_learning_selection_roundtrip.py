from __future__ import annotations

from hashlib import sha256
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def _payload(tmp_path):
    from app.learn.hybrid.omni_candidates import omni_inventory_from_ledger
    from tests.test_learning_hybrid_vertical_slice import _vertical
    facts = _vertical(tmp_path)
    raw = '{"topk_points":[[0.5,0.4]]}'
    return facts, {
        "learning_pipeline_mode": "hybrid_v1_2", "execution_origin": "replay", "gui_actor_provider_state": "replay_ready",
        "run_id": "run-recorded", "workflow_revision": 7, "capture_bundle": facts["bundle"],
        "omni_inventory": omni_inventory_from_ledger(facts["ledger"]), "target_text": "\u5feb\u901f\u7533\u8bf7 Quick Apply",
        "gui_actor_selection_input": {"raw_output_utf8": raw, "native_output_ref": {"id": "native/replay/roundtrip", "sha256": sha256(raw.encode()).hexdigest()}, "provider_id": "gui_actor_3b_bf16", "native_profile": {"contract_version": "goal_binding_native_profile_v1", "provider_id": "gui_actor_3b_bf16", "native_shape": "gui_actor_topk_points_v1", "coordinate_space": "normalized_0_1"}, "source_score": None, "capture_id": facts["bundle"]["capture_identity"]["capture_id"], "image_sha256": facts["bundle"]["capture_identity"]["screenshot_sha256"]},
        "refinement_policy": {"policy_version": "selection_refinement_conditional_v1", "mode": "conditional", "geometric_trigger": False},
        "capture_image_path": facts["image"].relative_to(tmp_path).as_posix(),
    }


def test_selection_trial_roundtrip_reload_and_missing_semantics_blocks_compile(tmp_path):
    from app.learn.draft_review import load_learning_draft_review
    from app.learn.hybrid.selection_persistence import persist_selection_review_trial
    from app.learn.pathgraph_candidate import build_pathgraph_candidate_from_review
    from app.learn.workflow_tasks.hybrid_selection import run_hybrid_selection_task

    facts, payload = _payload(tmp_path)
    response = run_hybrid_selection_task(payload)
    trial = persist_selection_review_trial(project_root=tmp_path, payload=payload, response=response)
    loaded = load_learning_draft_review(trial, project_root=tmp_path)
    assert loaded["hybrid_review_projection"]["contract_version"] == "hybrid_selection_review_v1"
    assert loaded["hybrid_review_projection"]["learning_state"] == "needs_semantic_review"
    assert loaded["draft"]["regions"][0]["reviewed_semantics"]["status"] == "missing"
    blocked = build_pathgraph_candidate_from_review(trial, {"expected_hybrid_review_projection_ref": loaded["hybrid_review_projection_ref"]}, project_root=tmp_path)
    assert blocked["validation_status"] == "blocked_missing_semantics"
    assert blocked["execute_binding_enabled"] is False

    code = "from app.learn.draft_review import load_learning_draft_review; import json; print(json.dumps(load_learning_draft_review(r'%s', project_root=r'%s')['hybrid_review_projection']['screen_facts'], ensure_ascii=False))" % (trial, str(tmp_path))
    fresh = subprocess.run([sys.executable, "-c", code], cwd=tmp_path, env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONPATH": str(Path(__file__).resolve().parents[1])}, capture_output=True, text=True, encoding="utf-8", check=True)
    assert facts["bundle"]["capture_identity"]["screenshot_sha256"] in fresh.stdout


def test_selection_persist_rejects_response_or_image_tamper(tmp_path):
    from copy import deepcopy
    from app.learn.hybrid.selection_persistence import persist_selection_review_trial
    from app.learn.workflow_tasks.hybrid_selection import run_hybrid_selection_task
    facts, payload = _payload(tmp_path)
    response = run_hybrid_selection_task(payload)
    tampered = deepcopy(response)
    tampered["selection"]["target_text"] = "other"
    with pytest.raises(ValueError, match="independently rerun"):
        persist_selection_review_trial(project_root=tmp_path, payload=payload, response=tampered)
    facts["image"].write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA mismatch"):
        persist_selection_review_trial(project_root=tmp_path, payload=payload, response=response)

def test_selection_semantic_human_edit_is_persisted_without_fabricating_pathgraph(tmp_path):
    from app.learn.draft_review import load_learning_draft_review, save_reviewed_template_candidate
    from app.learn.hybrid.selection_persistence import persist_selection_review_trial
    from app.learn.workflow_tasks.hybrid_selection import run_hybrid_selection_task
    facts, payload = _payload(tmp_path)
    trial = persist_selection_review_trial(project_root=tmp_path, payload=payload, response=run_hybrid_selection_task(payload))
    initial = load_learning_draft_review(trial, project_root=tmp_path)
    selected = next(item for item in initial["hybrid_review_projection"]["candidates"] if item["selection"] is not None)
    saved = save_reviewed_template_candidate(trial, {"expected_hybrid_review_projection_ref": initial["hybrid_review_projection_ref"], "hybrid_review_decisions": [{"decision_id": "decision/semantic-cn", "candidate_id": selected["candidate_id"], "decision_type": "semantic_edit", "semantics": {"role": "button", "label": "快速申请", "description": "人工补充"}}]}, project_root=tmp_path)
    candidate = json.loads((tmp_path / saved["reviewed_template_candidate_path"]).read_text(encoding="utf-8"))
    learning = candidate["draft"]["hybrid_selection_learning"]
    assert learning["learning_state"] == "ready_for_learning"
    assert learning["state_semantics"] == "not_fabricated"
    assert learning["action_semantics"] == "not_fabricated"


def test_same_capture_cannot_substitute_another_target_record(tmp_path):
    from app.learn.draft_review import load_learning_draft_review
    from app.learn.hybrid.selection_persistence import persist_selection_review_trial
    from app.learn.workflow_tasks.hybrid_selection import run_hybrid_selection_task
    _, payload = _payload(tmp_path)
    first = persist_selection_review_trial(project_root=tmp_path, payload=payload, response=run_hybrid_selection_task(payload))
    payload["target_text"] = "different target"
    other = persist_selection_review_trial(project_root=tmp_path, payload=payload, response=run_hybrid_selection_task(payload))
    original = json.loads((tmp_path / first).read_text(encoding="utf-8"))
    replacement = json.loads((tmp_path / other).read_text(encoding="utf-8"))
    original["hybrid_selection_review_projection_ref"] = replacement["hybrid_selection_review_projection_ref"]
    (tmp_path / first).write_text(json.dumps(original), encoding="utf-8")
    with pytest.raises(ValueError, match="trial identity"):
        load_learning_draft_review(first, project_root=tmp_path)


def test_selection_saved_overlay_projects_current_boxes_without_duplicating_durable_regions(tmp_path):
    from PIL import Image
    from app.learn.draft_review import load_learning_draft_review, save_reviewed_template_candidate
    from app.learn.hybrid.selection_persistence import persist_selection_review_trial
    from app.learn.workflow_tasks.hybrid_selection import run_hybrid_selection_task

    _, payload = _payload(tmp_path)
    trial = persist_selection_review_trial(project_root=tmp_path, payload=payload, response=run_hybrid_selection_task(payload))
    initial = load_learning_draft_review(trial, project_root=tmp_path)
    selected = next(item for item in initial["hybrid_review_projection"]["candidates"] if item["selection"] is not None)
    saved = save_reviewed_template_candidate(trial, {
        "expected_hybrid_review_projection_ref": initial["hybrid_review_projection_ref"],
        "hybrid_review_decisions": [{"decision_id": "decision/overlay/rebox", "candidate_id": selected["candidate_id"],
                                   "decision_type": "rebox", "bbox": [41, 21, 119, 51]}],
    }, project_root=tmp_path)
    durable = json.loads((tmp_path / saved["reviewed_template_candidate_path"]).read_text(encoding="utf-8"))
    assert durable["draft"]["regions"] == []
    with Image.open(tmp_path / saved["reviewed_overlay_path"]) as overlay:
        assert overlay.getpixel((41, 21)) == (220, 30, 50)
        assert overlay.getpixel((4, 5)) == (0, 110, 230)
    reloaded = load_learning_draft_review(saved["reviewed_template_candidate_path"], project_root=tmp_path)
    after = next(item for item in reloaded["hybrid_review_projection"]["candidates"] if item["selection"] is not None)
    assert after["model_proposal"] == selected["model_proposal"]
    assert after["reviewed_geometry"]["bbox"] == [41, 21, 119, 51]


def test_selection_diagnostics_follow_review_projection_through_save_load_and_graph(tmp_path):
    from app.learn.draft_review import load_learning_draft_review
    from app.learn.hybrid.selection_persistence import persist_selection_review_trial
    from app.learn.pathgraph_candidate import build_pathgraph_candidate_from_review
    from app.learn.workflow_tasks.hybrid_selection import run_hybrid_selection_task

    _, payload = _payload(tmp_path)
    trial = persist_selection_review_trial(project_root=tmp_path, payload=payload, response=run_hybrid_selection_task(payload))
    initial = load_learning_draft_review(trial, project_root=tmp_path)
    selected = next(c for c in initial["hybrid_review_projection"]["candidates"] if c["selection"] is not None)
    unselected = next(c for c in initial["hybrid_review_projection"]["candidates"] if c["selection"] is None)
    result = build_pathgraph_candidate_from_review(trial, {
        "expected_hybrid_review_projection_ref": initial["hybrid_review_projection_ref"],
        "hybrid_review_decisions": [
            {"decision_id": "decision/summary/rebox", "decision_type": "rebox", "candidate_id": selected["candidate_id"], "bbox": [41, 21, 119, 51]},
            {"decision_id": "decision/summary/unselected", "decision_type": "rebox", "candidate_id": unselected["candidate_id"], "bbox": [5, 6, 17, 18]},
            {"decision_id": "decision/summary/semantic", "decision_type": "semantic_edit", "candidate_id": selected["candidate_id"], "semantics": {"role": "button", "label": "快速申请", "description": "模拟审核"}},
        ],
    }, project_root=tmp_path)
    manual = result["manual_bbox_edit_summary"]
    assert manual["edited_region_count"] == 2
    assert manual["point_inside_bbox_passed"] == 1
    assert manual["point_unavailable_count"] == 1
    assert manual["invalid_geometry_count"] == 0
    assert manual["point_evidence"] == "model_original_diagnostic_only"
    precise = result["precise_understanding_summary"]
    assert precise["region_count"] == precise["bbox_region_count"] == result["summary"]["region_count"] == 1
    assert precise["candidate_count"] == 2
    assert precise["state_count"] == precise["action_template_count"] == 0
    reloaded = load_learning_draft_review(result["reviewed_template_candidate_path"], project_root=tmp_path)
    assert reloaded["audit"]["manual_bbox_edit_summary"] == manual
    assert reloaded["audit"]["precise_understanding_summary"] == precise
    # 旧摘要只是缓存，加载时必须由已验证投影重算，不能让过期零值冒充事实。
    path = tmp_path / result["reviewed_template_candidate_path"]
    durable = json.loads(path.read_text(encoding="utf-8"))
    durable["audit"]["manual_bbox_edit_summary"]["edited_region_count"] = 0
    path.write_text(json.dumps(durable, ensure_ascii=False), encoding="utf-8")
    assert load_learning_draft_review(path, project_root=tmp_path)["audit"]["manual_bbox_edit_summary"] == manual


def test_selection_missing_semantics_has_candidates_but_no_understood_regions(tmp_path):
    from app.learn.draft_review import load_learning_draft_review
    from app.learn.hybrid.selection_persistence import persist_selection_review_trial
    from app.learn.workflow_tasks.hybrid_selection import run_hybrid_selection_task

    _, payload = _payload(tmp_path)
    trial = persist_selection_review_trial(project_root=tmp_path, payload=payload, response=run_hybrid_selection_task(payload))
    loaded = load_learning_draft_review(trial, project_root=tmp_path)
    summary = loaded["audit"]["precise_understanding_summary"]
    assert summary["candidate_count"] == 2
    assert summary["region_count"] == summary["state_count"] == summary["action_template_count"] == 0
    assert summary["learning_state"] == "compile_rejected"
    assert summary["execute_binding_enabled"] is False
