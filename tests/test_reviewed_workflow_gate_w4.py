from __future__ import annotations

from copy import deepcopy

import pytest

from app.agent.reviewed_workflow_replay import validate_current_grounding
from app.operation.recognition import (
    CandidateRankResult,
    LocalGroundingCandidateResult,
    LocalGroundingResult,
)
from app.vision.schemas import BBox
from tests.test_pre_click_decision import _candidate, _rank_result
from tests.test_reviewed_workflow_asset_v2 import _asset
from tests.test_reviewed_workflow_replay_v2 import _grounding, _selection


def _recognition_inputs(
    *,
    policy_allowed: bool = True,
) -> tuple[CandidateRankResult, LocalGroundingResult]:
    candidate = _candidate(
        candidate_id="candidate-current",
        element_id="job_card",
        label="Job card",
        score=0.95,
        allowed=policy_allowed,
        bbox=BBox(x=100, y=200, w=300, h=80),
        click_point={"x": 220, "y": 240},
    )
    candidates = _rank_result(candidate, margin=0.40)
    candidates.goal = "click job card"
    local = LocalGroundingResult(
        goal=candidates.goal,
        results=[
            LocalGroundingCandidateResult(
                candidate_id="candidate-current",
                element_id="job_card",
                status="grounded",
                crop_path="crop.png",
                crop_bbox={"x": 80, "y": 180, "width": 340, "height": 120},
                refined_click_point={"x": 220, "y": 240},
                coordinate_source="local_ocr_text_center",
                confidence=0.95,
                matched_text="Job card",
                matched_text_bbox={"x": 100, "y": 200, "width": 100, "height": 20},
            )
        ],
        recommended_candidate_id="candidate-current",
    )
    return candidates, local


def _evaluate(*, policy_allowed: bool = True, grounding: dict | None = None) -> dict:
    from app.agent.reviewed_workflow_gate import ReviewedWorkflowGateAdapter

    candidates, local = _recognition_inputs(policy_allowed=policy_allowed)
    return ReviewedWorkflowGateAdapter().evaluate(
        selection=_selection(),
        grounding=_grounding(_asset()) if grounding is None else grounding,
        candidates=candidates,
        local_grounding=local,
    )


def test_real_pre_click_policy_allow_builds_current_lineage_gate() -> None:
    asset = _asset()
    selection = _selection(asset)
    grounding = _grounding(asset)

    gate = _evaluate(grounding=grounding)

    assert gate["contract_version"] == "pre_click_decision_v1"
    assert gate["allowed"] is True
    assert gate["selected_candidate_id"] == grounding["candidate_id"]
    assert gate["selected_element_id"] == selection["element_ref"]
    assert gate["selected_click_point"] == grounding["click_point"]
    assert gate["capture_id"] == selection["capture_lineage"]["capture_id"]
    assert validate_current_grounding(
        asset,
        selection,
        grounding,
        gate,
        policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2},
    )["status"] == "validated"


def test_real_pre_click_policy_block_remains_blocked() -> None:
    gate = _evaluate(policy_allowed=False)

    assert gate["allowed"] is False
    assert gate["selected_candidate_id"] == "candidate-current"


@pytest.mark.parametrize(
    "field,value",
    [
        ("capture_id", "capture-other"),
        ("candidate_id", "candidate-other"),
        ("click_point", {"x": 221, "y": 240}),
        ("bbox", {"x": 101, "y": 200, "w": 300, "h": 80}),
    ],
)
def test_current_grounding_binding_mismatch_fails_closed(field: str, value: object) -> None:
    grounding = deepcopy(_grounding(_asset()))
    grounding[field] = value

    gate = _evaluate(grounding=grounding)

    assert gate["allowed"] is False


def test_local_grounding_element_mismatch_fails_closed() -> None:
    from app.agent.reviewed_workflow_gate import ReviewedWorkflowGateAdapter

    candidates, local = _recognition_inputs()
    local.results[0].element_id = "element-other"

    gate = ReviewedWorkflowGateAdapter().evaluate(
        selection=_selection(),
        grounding=_grounding(_asset()),
        candidates=candidates,
        local_grounding=local,
    )

    assert gate["allowed"] is False
