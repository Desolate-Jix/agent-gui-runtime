from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest

from test_reviewed_workflow_compiler_v2 import _base_review, _persist_reviewed_workflow, _run_compile


PARAMETERS = {"contract_version": "reviewed_scroll_parameters_v1", "target_container_id": "detail-pane", "axis": "vertical", "direction": "down", "wheel_clicks": 2, "unit": "wheel_detent"}


def scroll_review():
    review = _base_review()
    node, edge = review["nodes"][0], review["edges"][0]
    node["controls"] = []
    node["regions"] = [{"region_id": "detail-pane", "label": "Details panel"}]
    candidate = node["action_candidates"][0]
    candidate.update(semantic_action="scroll_region", target_control_id="", target_region_id="detail-pane", scroll_parameters=deepcopy(PARAMETERS))
    edge.update(action_type="scroll_region", target_control_id="", target_region_id="detail-pane", scroll_parameters=deepcopy(PARAMETERS), requires_user_confirmation=True, risk_level="medium")
    return review


def test_saved_approved_scroll_compiles_exact_parameters_without_runtime_coordinates(tmp_path):
    source, digest = _persist_reviewed_workflow(tmp_path, scroll_review())
    saved = json.loads(source.read_text(encoding="utf-8"))
    assert saved["nodes"][0]["action_candidates"][0]["scroll_parameters"] == PARAMETERS
    assert saved["edges"][0]["scroll_parameters"] == PARAMETERS
    result = _run_compile(tmp_path, source, digest)
    assert result["status"] == "compiled", result["blocked_reasons"]
    transition = next(item for item in result["asset"]["transitions"] if item["semantic_action"] == "scroll_region")
    assert transition["scroll_parameters"] == PARAMETERS
    assert transition["risk_policy"]["requires_user_confirmation"] is True
    assert transition["risk_policy"]["automatic_execution_allowed"] is False
    assert "target_bbox" not in json.dumps(transition["scroll_parameters"])
    assert sha256(source.read_bytes()).hexdigest() == digest


def test_compiler_rejects_independently_approved_but_disagreeing_candidate_and_edge(tmp_path):
    review = scroll_review()
    review["edges"][0]["scroll_parameters"]["wheel_clicks"] = 3
    source, digest = _persist_reviewed_workflow(tmp_path, review)
    result = _run_compile(tmp_path, source, digest)
    assert result["status"] == "blocked"
    assert any(reason["code"] == "edge_action_candidate_approval_invalid" for reason in result["blocked_reasons"])


@pytest.mark.parametrize("subject", ["edge", "candidate"])
@pytest.mark.parametrize("mutation", [{"wheel_clicks": True}, {"wheel_clicks": 21}, {"target_container_id": "other-pane"}, {"x": 50}])
def test_review_save_rejects_malformed_or_unbound_scroll_parameters(tmp_path, subject, mutation):
    from app.learn.interface_workflow_review import save_interface_workflow_review_candidate

    review = scroll_review()
    item = review["edges"][0] if subject == "edge" else review["nodes"][0]["action_candidates"][0]
    item["scroll_parameters"].update(mutation)
    with pytest.raises(ValueError):
        save_interface_workflow_review_candidate(review, project_root=tmp_path)


def test_changed_scroll_parameter_does_not_reuse_prior_human_approval(tmp_path):
    from app.learn.interface_workflow_review import save_interface_workflow_review_candidate

    source, _ = _persist_reviewed_workflow(tmp_path, scroll_review())
    review = json.loads(source.read_text(encoding="utf-8"))
    review["nodes"][0]["action_candidates"][0]["scroll_parameters"]["direction"] = "up"
    review["edges"][0]["scroll_parameters"]["direction"] = "up"
    saved = save_interface_workflow_review_candidate(review, project_root=tmp_path)
    path = Path(saved["path"])
    result = _run_compile(tmp_path, path, sha256(path.read_bytes()).hexdigest())
    assert result["status"] == "blocked"


@pytest.mark.parametrize("mutation", [{"wheel_clicks": 0}, {"x": 50}, {"target_container_id": ""}, {"target_container_id": "other-pane"}])
def test_compiled_asset_validator_rechecks_scroll_payload(tmp_path, mutation):
    from app.agent.reviewed_workflow_asset import validate_reviewed_workflow_asset

    source, digest = _persist_reviewed_workflow(tmp_path, scroll_review())
    asset = _run_compile(tmp_path, source, digest)["asset"]
    assert asset is not None
    transition = next(item for item in asset["transitions"] if item["semantic_action"] == "scroll_region")
    transition["scroll_parameters"].update(mutation)
    with pytest.raises(ValueError):
        validate_reviewed_workflow_asset(asset)


def test_legacy_click_compilation_does_not_gain_empty_scroll_fields(tmp_path):
    source, digest = _persist_reviewed_workflow(tmp_path)
    result = _run_compile(tmp_path, source, digest)
    assert result["status"] == "compiled"
    assert all("scroll_parameters" not in transition for transition in result["asset"]["transitions"])


def test_compiler_subject_matching_does_not_trust_two_missing_parameter_payloads():
    from app.agent.reviewed_workflow_compiler import _exact_transition_subjects

    review = scroll_review()
    del review["nodes"][0]["action_candidates"][0]["scroll_parameters"]
    del review["edges"][0]["scroll_parameters"]
    _, candidate, error = _exact_transition_subjects(node=review["nodes"][0], edge=review["edges"][0])
    assert candidate is None
    assert error
