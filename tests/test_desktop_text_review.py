from __future__ import annotations

import copy

import pytest

from app.agent.action_semantics import REVIEWED_SINGLE_STEP_ACTIONS
from app.desktop_review.exact_review import ExactReviewError
from test_desktop_exact_review import _batch, _complete, _load, _new_runtime, _prepare, _record_dir


FIXED_PARAMETERS = {
    "contract_version": "reviewed_text_parameters_v1",
    "target_field_id": "open",
    "content": {"kind": "literal", "text": "\u4f60\u597d\nquery"},
    "clear_existing": True,
    "sensitive": False,
    "submit": False,
    "clipboard_policy": "restore_previous",
}
VARIABLE_PARAMETERS = {
    **FIXED_PARAMETERS,
    "content": {"kind": "variable", "name": "query_text"},
}


def _with_reviewed_interface_identity(batch):
    for interface in batch["interfaces"]:
        interface["recognition_text"] = f"Reviewed interface {interface['interface_id']}"
    return batch


@pytest.mark.parametrize("parameters", [FIXED_PARAMETERS, VARIABLE_PARAMETERS])
def test_text_parameters_survive_native_save_exact_review_and_compilation(tmp_path, parameters):
    batch = _with_reviewed_interface_identity(_batch(action_type="fill_field"))
    parameters = {**parameters, "target_field_id": batch["steps"][0]["target_region_id"]}
    batch["steps"][0]["text_parameters"] = copy.deepcopy(parameters)
    store, _, facade, workspace = _new_runtime(tmp_path, batch)
    try:
        prepared = _prepare(facade, workspace)
        subjects = [
            subject for subject in prepared["subjects"]
            if subject["kind"] in {"action", "edge"}
            and subject["content"].get("external_step_id") == "open"
        ]
        assert len(subjects) == 2
        assert [subject["content"]["text_parameters"] for subject in subjects] == [parameters, parameters]
        assert {subject["content"]["risk_level"] for subject in subjects if subject["kind"] == "edge"} == {"medium"}
        compiled = _complete(facade, prepared)
        assert compiled["status"] == "compiled", compiled
        receipt = _load(_record_dir(tmp_path / "root") / f"receipt-{compiled['compile_receipt_id']}.json")
        transition = receipt["asset"]["transitions"][0]
        assert transition["semantic_action"] == "fill_field"
        assert transition["text_parameters"] == parameters
        source_state = next(state for state in receipt["asset"]["states"] if state["state_id"] == transition["source_state_id"])
        anchor = next(item for item in source_state["identity_anchors"] if item["anchor_id"] == transition["element_ref"])
        assert anchor["text_field_id"] == "open"
        assert transition["risk_policy"]["risk_level"] == "medium"
        assert transition["risk_policy"]["requires_user_confirmation"] is True
        assert "fill_field" in REVIEWED_SINGLE_STEP_ACTIONS
    finally:
        facade.close()
        store.close()


def test_saving_changed_text_parameters_invalidates_prepared_exact_review(tmp_path):
    batch = _with_reviewed_interface_identity(_batch(action_type="fill_field"))
    batch["steps"][0]["text_parameters"] = {**copy.deepcopy(FIXED_PARAMETERS), "target_field_id": "open"}
    store, _, facade, workspace = _new_runtime(tmp_path, batch)
    try:
        prepared = _prepare(facade, workspace)
        edited = copy.deepcopy(workspace["batch"])
        edited["steps"][0]["text_parameters"]["content"]["text"] = "changed"
        facade.save_revision("task", "exact-review-batch", workspace["revision"], edited)
        with pytest.raises(ExactReviewError, match="revision|current"):
            facade.record_review_decisions(prepared["review_ref"], 0, [])
    finally:
        facade.close()
        store.close()


def test_relearning_text_candidate_is_adopted_then_exact_reviewed_and_compiled(tmp_path):
    import test_desktop_flow_candidates as flow_tests
    from test_desktop_flow_candidates import _APPLICATION, _setup, _submit
    from test_agent_link_flow_candidates import flow_changes

    original_flow_batch = flow_tests.flow_batch
    flow_tests.flow_batch = lambda: _with_reviewed_interface_identity(original_flow_batch())
    _, _, store, service, grant, facade, saved = _setup(tmp_path)
    try:
        first_review = facade.prepare_exact_review(
            "task-flow", "flow-batch", saved["revision"], copy.deepcopy(_APPLICATION)
        )
        first_approved = facade.record_review_decisions(
            first_review["review_ref"], first_review["approval_revision"],
            [subject["subject_id"] for subject in first_review["subjects"]],
        )
        change = copy.deepcopy(flow_changes()[0])
        parameters = {**VARIABLE_PARAMETERS, "target_field_id": "r2"}
        change.update(action_type="fill_field", target_region_id="r2", text_parameters=parameters)
        _, candidate, comparison = _submit(service, grant, facade, changes=[change], key="adopt-text")
        adopted = facade.adopt_relearn_candidate(
            "task-flow", "flow-batch", saved["revision"], candidate["candidate_id"],
            comparison["candidate_sha256"], comparison["review_baseline_sha256"], "adopt-text",
        )
        adopted_step = next(step for step in adopted["snapshot"]["batch"]["steps"] if step["step_id"] == "s1")
        assert adopted_step["text_parameters"] == parameters
        with pytest.raises(ExactReviewError, match="revision|current"):
            facade.compile_exact_review(first_review["review_ref"], first_approved["approval_revision"])

        second_review = facade.prepare_exact_review(
            "task-flow", "flow-batch", adopted["snapshot"]["revision"], copy.deepcopy(_APPLICATION)
        )
        compiled = _complete(facade, second_review)
        assert compiled["status"] == "compiled", compiled
    finally:
        facade.close()
        store.close()
        flow_tests.flow_batch = original_flow_batch
