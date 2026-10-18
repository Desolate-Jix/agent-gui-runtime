from __future__ import annotations

import copy

import pytest

from app.desktop_review.exact_review import ExactReviewError
from test_desktop_exact_review import _batch, _complete, _load, _new_runtime, _prepare, _record_dir


PARAMETERS = {
    "contract_version": "reviewed_scroll_parameters_v1",
    "target_container_id": "open",
    "axis": "vertical",
    "direction": "down",
    "wheel_clicks": 3,
    "unit": "wheel_detent",
}


def test_scroll_parameters_survive_native_save_exact_review_and_compilation(tmp_path):
    batch = _batch(action_type="scroll_region")
    batch["steps"][0]["scroll_parameters"] = copy.deepcopy(PARAMETERS)
    store, _, facade, workspace = _new_runtime(tmp_path, batch)
    try:
        prepared = _prepare(facade, workspace)
        scroll_subjects = [
            subject for subject in prepared["subjects"]
            if subject["kind"] in {"action", "edge"}
            and subject["content"].get("external_step_id") == "open"
        ]
        assert len(scroll_subjects) == 2
        assert [subject["content"]["scroll_parameters"] for subject in scroll_subjects] == [PARAMETERS, PARAMETERS]
        assert {subject["content"]["risk_level"] for subject in scroll_subjects if subject["kind"] == "edge"} == {"medium"}
        compiled = _complete(facade, prepared)
        assert compiled["status"] == "compiled", compiled
        receipt = _load(_record_dir(tmp_path / "root") / f"receipt-{compiled['compile_receipt_id']}.json")
        transition = receipt["asset"]["transitions"][0]
        assert transition["semantic_action"] == "scroll_region"
        assert transition["scroll_parameters"] == PARAMETERS
        assert transition["risk_policy"]["risk_level"] == "medium"
        assert transition["risk_policy"]["requires_user_confirmation"] is True
    finally:
        facade.close()
        store.close()


def test_relearning_scroll_candidate_is_adopted_then_exact_reviewed_and_compiled(tmp_path):
    from test_desktop_flow_candidates import _APPLICATION, _setup, _submit
    from test_agent_link_flow_candidates import flow_changes

    _, _, store, service, grant, facade, saved = _setup(tmp_path)
    try:
        first_review = facade.prepare_exact_review(
            "task-flow", "flow-batch", saved["revision"], copy.deepcopy(_APPLICATION)
        )
        first_approved = facade.record_review_decisions(
            first_review["review_ref"],
            first_review["approval_revision"],
            [subject["subject_id"] for subject in first_review["subjects"]],
        )
        change = copy.deepcopy(flow_changes()[0])
        parameters = {
            "contract_version": "reviewed_scroll_parameters_v1",
            "target_container_id": "r2",
            "axis": "vertical",
            "direction": "up",
            "wheel_clicks": 2,
            "unit": "wheel_detent",
        }
        change.update(action_type="scroll_region", target_region_id="r2", scroll_parameters=parameters)
        _, candidate, comparison = _submit(service, grant, facade, changes=[change], key="adopt-scroll")
        adopted = facade.adopt_relearn_candidate(
            "task-flow", "flow-batch", saved["revision"], candidate["candidate_id"],
            comparison["candidate_sha256"], comparison["review_baseline_sha256"], "adopt-scroll",
        )
        adopted_step = next(step for step in adopted["snapshot"]["batch"]["steps"] if step["step_id"] == "s1")
        assert adopted_step["scroll_parameters"] == parameters
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


def test_saving_changed_scroll_parameters_invalidates_prepared_exact_review(tmp_path):
    batch = _batch(action_type="scroll_region")
    batch["steps"][0]["scroll_parameters"] = copy.deepcopy(PARAMETERS)
    store, _, facade, workspace = _new_runtime(tmp_path, batch)
    try:
        prepared = _prepare(facade, workspace)
        edited = copy.deepcopy(workspace["batch"])
        edited["steps"][0]["scroll_parameters"]["direction"] = "up"
        facade.save_revision("task", "exact-review-batch", workspace["revision"], edited)
        import pytest
        from app.desktop_review.exact_review import ExactReviewError
        with pytest.raises(ExactReviewError, match="revision|current"):
            facade.record_review_decisions(prepared["review_ref"], 0, [])
    finally:
        facade.close()
        store.close()
