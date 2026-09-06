from copy import deepcopy
from hashlib import sha256

import pytest


def _facts(tmp_path):
    from tests.test_learning_selection_roundtrip import _payload
    from app.learn.hybrid.target_selection import parse_gui_actor_selection
    from app.learn.hybrid.selection_refinement import build_selection_roi_request
    _, payload = _payload(tmp_path)
    selection = parse_gui_actor_selection(payload["gui_actor_selection_input"], capture_bundle=payload["capture_bundle"], omni_inventory=payload["omni_inventory"], target_text=payload["target_text"])
    request = build_selection_roi_request(selection=selection, inventory=payload["omni_inventory"])
    raw = "[500, 500]"
    result = {"contract_version": "vista_current_source_result_v1", "provider_id": "vista_4b", "raw_output_utf8": raw,
              "native_output_ref": {"id": "vista/replay/one", "sha256": sha256(raw.encode()).hexdigest()},
              "roi_image_sha256": "ab" * 32, "source_score": None,
              "target_sha256": sha256(payload["target_text"].encode()).hexdigest()}
    native = {"contract_version": "hybrid_selection_vista_input_v1", "request": request,
              "roi_image_sha256": "ab" * 32, "provider_result": result}
    return payload, selection, native


def test_refinement_preserves_original_selection_and_maps_exact_baseline_roi(tmp_path):
    from app.learn.hybrid.selection_refinement import resolve_selection_refinement
    payload, selection, native = _facts(tmp_path)
    before = deepcopy(selection)
    record = resolve_selection_refinement(selection=selection, policy={"policy_version": "selection_refinement_modes_v1", "mode": "always", "geometric_trigger": False}, inventory=payload["omni_inventory"], vista_refinement_input=native)
    assert record["status"] == "validated"
    assert record["provider_result"]["canonical_capture_pixel_point"] == [80, 36]
    assert record["provider_result"]["source_score"] is None
    assert selection == before
    assert native["request"]["roi_bbox"] == [40, 20, 120, 52]


@pytest.mark.parametrize("pair", ["[0, 0]", "[1000, 500]", "[NaN, 4]", "not a pair"])
def test_refinement_invalid_point_is_review_required_not_original_point_fallback(tmp_path, pair):
    from app.learn.hybrid.selection_refinement import resolve_selection_refinement
    payload, selection, native = _facts(tmp_path)
    native["provider_result"]["raw_output_utf8"] = pair
    native["provider_result"]["native_output_ref"]["sha256"] = sha256(pair.encode()).hexdigest()
    record = resolve_selection_refinement(selection=selection, policy={"policy_version": "selection_refinement_modes_v1", "mode": "always", "geometric_trigger": False}, inventory=payload["omni_inventory"], vista_refinement_input=native)
    assert record["status"] == "review_required"
    assert record["provider_result"]["canonical_capture_pixel_point"] is None


@pytest.mark.parametrize("tamper", ["candidate", "image", "target", "raw_hash", "roi"])
def test_refinement_rejects_parent_or_raw_binding_drift(tmp_path, tamper):
    from app.learn.hybrid.selection_refinement import resolve_selection_refinement
    payload, selection, native = _facts(tmp_path)
    if tamper == "candidate": native["request"]["candidate_id"] = "candidate/other"
    if tamper == "image": native["provider_result"]["roi_image_sha256"] = "cd" * 32
    if tamper == "target": native["provider_result"]["target_sha256"] = "cd" * 32
    if tamper == "raw_hash": native["provider_result"]["raw_output_utf8"] = "[400,500]"
    if tamper == "roi": native["request"]["roi_bbox"][0] += 1
    with pytest.raises(ValueError):
        resolve_selection_refinement(selection=selection, policy={"policy_version": "selection_refinement_modes_v1", "mode": "always", "geometric_trigger": False}, inventory=payload["omni_inventory"], vista_refinement_input=native)


def test_refinement_crosses_worker_review_save_and_reload_with_parent_evidence(tmp_path):
    from app.learn.workflow_tasks.hybrid_selection import run_hybrid_selection_task
    from app.learn.hybrid.selection_persistence import persist_selection_review_trial
    from app.learn.draft_review import load_learning_draft_review, save_reviewed_template_candidate
    payload, selection, native = _facts(tmp_path)
    payload["refinement_policy"] = {"policy_version": "selection_refinement_modes_v1", "mode": "always", "geometric_trigger": False}
    payload["vista_refinement_input"] = native
    response = run_hybrid_selection_task(payload)
    assert response["outcome"] == "completed"
    trial = persist_selection_review_trial(project_root=tmp_path, payload=payload, response=response)
    loaded = load_learning_draft_review(trial, project_root=tmp_path)
    assert loaded["hybrid_review_projection"]["refinement"]["status"] == "validated"
    assert loaded["hybrid_selection_review_parent_evidence"]["vista_refinement_input"] == native
    saved = save_reviewed_template_candidate(trial, {"expected_hybrid_review_projection_ref": loaded["hybrid_review_projection_ref"],
        "hybrid_review_decisions": [{"decision_id": "decision/refined/edit", "candidate_id": selection["candidate_id"], "decision_type": "semantic_edit", "semantics": {"role": "button", "label": "快速申请", "description": "模拟审核"}}]}, project_root=tmp_path)
    after = load_learning_draft_review(saved["reviewed_template_candidate_path"], project_root=tmp_path)
    assert after["hybrid_review_projection"]["refinement"] == response["refinement"]
    assert after["hybrid_review_projection"]["selection"] == selection


def test_client_cannot_claim_actual_refiner_without_server_execution(tmp_path):
    from app.learn.workflow_tasks.hybrid_selection import run_hybrid_selection_task
    from tests.test_learning_selection_actual_origin import _actual_payload_and_proof
    # 同一冻结 fixture 重建后 capture identity 相同。
    _, _, native = _facts(tmp_path)
    payload, proof = _actual_payload_and_proof(tmp_path)
    payload["refinement_policy"] = {"policy_version": "selection_refinement_modes_v1", "mode": "always", "geometric_trigger": False}
    payload["vista_refinement_input"] = native
    response = run_hybrid_selection_task(payload, actual_execution=proof)
    assert response["outcome"] == "safe_stopped"
    assert "refinement_actual_execution" in response["reason"]
