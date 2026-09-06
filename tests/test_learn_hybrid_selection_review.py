from __future__ import annotations

from hashlib import sha256


def _raw(facts: dict) -> dict:
    value = '{"topk_points":[[0.5,0.4]]}'
    return {"raw_output_utf8": value, "native_output_ref": {"id": "native/gui-actor/case-1", "sha256": sha256(value.encode("utf-8")).hexdigest()}, "provider_id": "gui_actor_3b_bf16", "native_profile": {"contract_version": "goal_binding_native_profile_v1", "provider_id": "gui_actor_3b_bf16", "native_shape": "gui_actor_topk_points_v1", "coordinate_space": "normalized_0_1"}, "source_score": None, "capture_id": facts["bundle"]["capture_identity"]["capture_id"], "image_sha256": facts["bundle"]["capture_identity"]["screenshot_sha256"]}


def _policy() -> dict:
    return {"policy_version": "selection_refinement_conditional_v1", "mode": "conditional", "geometric_trigger": False}


def test_selection_review_keeps_established_candidate_view_and_appends_human_correction(tmp_path) -> None:
    from app.learn.hybrid.omni_candidates import omni_inventory_from_ledger
    from app.learn.hybrid.refinement_policy import decide_refinement
    from app.learn.hybrid.selection_review import apply_selection_review_decisions, project_selection_review
    from app.learn.hybrid.target_selection import parse_gui_actor_selection
    from tests.test_learning_hybrid_vertical_slice import _vertical

    facts = _vertical(tmp_path)
    inventory = omni_inventory_from_ledger(facts["ledger"])
    selection = parse_gui_actor_selection(
        {"raw_output_utf8": '{"topk_points":[[0.5,0.4]]}', "native_output_ref": {"id": "native/gui-actor/case-1", "sha256": sha256(b'{"topk_points":[[0.5,0.4]]}').hexdigest()}, "provider_id": "gui_actor_3b_bf16", "native_profile": {"contract_version": "goal_binding_native_profile_v1", "provider_id": "gui_actor_3b_bf16", "native_shape": "gui_actor_topk_points_v1", "coordinate_space": "normalized_0_1"}, "source_score": None, "capture_id": facts["bundle"]["capture_identity"]["capture_id"], "image_sha256": facts["bundle"]["capture_identity"]["screenshot_sha256"]},
        capture_bundle=facts["bundle"], omni_inventory=inventory, target_text="Quick Apply",
    )
    refinement = decide_refinement(selection=selection, policy={"policy_version": "selection_refinement_conditional_v1", "mode": "conditional", "geometric_trigger": False})
    projection = project_selection_review(capture_bundle=facts["bundle"], omni_inventory=inventory, gui_actor_selection_input=_raw(facts), target_text="Quick Apply", refinement_policy=_policy(), selection=selection, refinement=refinement)

    chosen = next(item for item in projection["candidates"] if item["candidate_id"] == selection["candidate_id"])
    assert projection["contract_version"] == "hybrid_selection_review_v1"
    assert projection["screen_facts"]["displayed_image"]["sha256"] == facts["bundle"]["capture_identity"]["screenshot_sha256"]
    assert chosen["model_proposal"]["bbox_original"] == inventory["candidates"][0]["bbox_original"]
    assert chosen["reviewed_semantics"]["status"] == "missing"
    assert projection["learning_state"] == "needs_semantic_review"

    corrected = apply_selection_review_decisions(projection, decisions=[{"decision_id": "decision/rebox-1", "candidate_id": selection["candidate_id"], "decision_type": "rebox", "bbox": [41, 20, 120, 52]}], capture_bundle=facts["bundle"], omni_inventory=inventory, gui_actor_selection_input=_raw(facts), target_text="Quick Apply", refinement_policy=_policy())
    updated = next(item for item in corrected["candidates"] if item["candidate_id"] == selection["candidate_id"])
    assert updated["model_proposal"] == chosen["model_proposal"]
    assert updated["reviewed_geometry"]["source"] == "human_rebox"
    assert len(updated["review_decisions"]) == 1


def test_selection_review_rejects_selection_that_changes_raw_parent_values(tmp_path) -> None:
    from copy import deepcopy
    import pytest
    from app.learn.hybrid.omni_candidates import omni_inventory_from_ledger
    from app.learn.hybrid.refinement_policy import decide_refinement
    from app.learn.hybrid.selection_review import project_selection_review
    from app.learn.hybrid.target_selection import parse_gui_actor_selection
    from tests.test_learning_hybrid_vertical_slice import _vertical

    facts = _vertical(tmp_path)
    inventory = omni_inventory_from_ledger(facts["ledger"])
    raw = {"raw_output_utf8": '{"topk_points":[[0.5,0.4]]}', "native_output_ref": {"id": "native/gui-actor/case-1", "sha256": sha256(b'{"topk_points":[[0.5,0.4]]}').hexdigest()}, "provider_id": "gui_actor_3b_bf16", "native_profile": {"contract_version": "goal_binding_native_profile_v1", "provider_id": "gui_actor_3b_bf16", "native_shape": "gui_actor_topk_points_v1", "coordinate_space": "normalized_0_1"}, "source_score": None, "capture_id": facts["bundle"]["capture_identity"]["capture_id"], "image_sha256": facts["bundle"]["capture_identity"]["screenshot_sha256"]}
    selection = parse_gui_actor_selection(raw, capture_bundle=facts["bundle"], omni_inventory=inventory, target_text="Quick Apply")
    tampered = deepcopy(selection)
    tampered["target_text"] = "Other"
    refinement = decide_refinement(selection=tampered, policy={"policy_version": "selection_refinement_conditional_v1", "mode": "conditional", "geometric_trigger": False})
    with pytest.raises(ValueError):
        project_selection_review(capture_bundle=facts["bundle"], omni_inventory=inventory, gui_actor_selection_input=raw, target_text="Quick Apply", refinement_policy=_policy(), selection=tampered, refinement=refinement)


def test_empty_decision_apply_rejects_authority_tampered_projection(tmp_path) -> None:
    from copy import deepcopy
    import pytest
    from app.learn.hybrid.omni_candidates import omni_inventory_from_ledger
    from app.learn.hybrid.refinement_policy import decide_refinement
    from app.learn.hybrid.selection_review import apply_selection_review_decisions, project_selection_review
    from app.learn.hybrid.target_selection import parse_gui_actor_selection
    from tests.test_learning_hybrid_vertical_slice import _vertical

    facts = _vertical(tmp_path)
    inventory = omni_inventory_from_ledger(facts["ledger"])
    raw = {"raw_output_utf8": '{"topk_points":[[0.5,0.4]]}', "native_output_ref": {"id": "native/gui-actor/case-1", "sha256": sha256(b'{"topk_points":[[0.5,0.4]]}').hexdigest()}, "provider_id": "gui_actor_3b_bf16", "native_profile": {"contract_version": "goal_binding_native_profile_v1", "provider_id": "gui_actor_3b_bf16", "native_shape": "gui_actor_topk_points_v1", "coordinate_space": "normalized_0_1"}, "source_score": None, "capture_id": facts["bundle"]["capture_identity"]["capture_id"], "image_sha256": facts["bundle"]["capture_identity"]["screenshot_sha256"]}
    selection = parse_gui_actor_selection(raw, capture_bundle=facts["bundle"], omni_inventory=inventory, target_text="Quick Apply")
    refinement = decide_refinement(selection=selection, policy={"policy_version": "selection_refinement_conditional_v1", "mode": "conditional", "geometric_trigger": False})
    projection = project_selection_review(capture_bundle=facts["bundle"], omni_inventory=inventory, gui_actor_selection_input=_raw(facts), target_text="Quick Apply", refinement_policy=_policy(), selection=selection, refinement=refinement)
    forged = deepcopy(projection)
    forged["execute_binding_enabled"] = True
    with pytest.raises(ValueError):
        apply_selection_review_decisions(forged, decisions=[], capture_bundle=facts["bundle"], omni_inventory=inventory, gui_actor_selection_input=raw, target_text="Quick Apply", refinement_policy=_policy())
