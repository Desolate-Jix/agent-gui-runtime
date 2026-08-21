"""Reviewed Workflow 到现有 ``pre_click_decision_v1`` 的内部适配器。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.operation.recognition.decision import decide_pre_click
from app.operation.recognition.schemas import (
    CandidateRankResult,
    LocalGroundingResult,
    PreClickDecisionResult,
    RecognitionCandidate,
)


class ReviewedWorkflowGateAdapter:
    """只把服务端当前识别证据投影到现有 Gate，不授予执行权。"""

    def __init__(
        self,
        *,
        min_candidate_score: float = 0.45,
        min_margin: float = 0.06,
        min_local_text_similarity: float = 0.45,
        allow_low_margin_when_grounded: bool = False,
    ) -> None:
        self._min_candidate_score = min_candidate_score
        self._min_margin = min_margin
        self._min_local_text_similarity = min_local_text_similarity
        self._allow_low_margin_when_grounded = allow_low_margin_when_grounded

    def evaluate(
        self,
        *,
        selection: Mapping[str, Any],
        grounding: Mapping[str, Any],
        candidates: CandidateRankResult,
        local_grounding: LocalGroundingResult,
        expected_effect: dict[str, object] | None = None,
    ) -> dict[str, Any]:
        policy_decision = decide_pre_click(
            goal=candidates.goal,
            candidates=candidates,
            grounding=local_grounding,
            min_candidate_score=self._min_candidate_score,
            min_margin=self._min_margin,
            min_local_text_similarity=self._min_local_text_similarity,
            allow_low_margin_when_grounded=self._allow_low_margin_when_grounded,
            expected_effect=expected_effect,
        )
        binding_matches = _binding_matches(
            selection=selection,
            grounding=grounding,
            candidates=candidates,
            local_grounding=local_grounding,
            policy_decision=policy_decision,
        )
        lineage = selection.get("capture_lineage")
        lineage = lineage if isinstance(lineage, Mapping) else {}
        candidate_id = grounding.get("candidate_id")
        candidate_ref = candidate_id if isinstance(candidate_id, str) and candidate_id else "unresolved"
        capture_id = lineage.get("capture_id")
        capture_ref = capture_id if isinstance(capture_id, str) and capture_id else "unresolved"
        allowed = policy_decision.allowed and binding_matches
        return {
            "contract_version": "pre_click_decision_v1",
            "allowed": allowed,
            "asset_content_sha256": selection.get("asset_content_sha256"),
            "transition_id": selection.get("transition_id"),
            "selection_sha256": selection.get("selection_sha256"),
            "selected_candidate_id": grounding.get("candidate_id"),
            "selected_element_id": selection.get("element_ref"),
            "selected_click_point": grounding.get("click_point"),
            "capture_id": lineage.get("capture_id"),
            "screenshot_sha256": lineage.get("screenshot_sha256"),
            "viewport_size": lineage.get("viewport_size"),
            "evidence_refs": [
                f"gate:pre-click:{capture_ref}:{candidate_ref}:{'allowed' if allowed else 'blocked'}"
            ],
        }


def _binding_matches(
    *,
    selection: Mapping[str, Any],
    grounding: Mapping[str, Any],
    candidates: CandidateRankResult,
    local_grounding: LocalGroundingResult,
    policy_decision: PreClickDecisionResult,
) -> bool:
    if (
        selection.get("contract_version") != "verified_transition_selection_v1"
        or selection.get("status") != "selected"
        or grounding.get("contract_version") != "reviewed_workflow_current_grounding_v1"
        or grounding.get("candidate_current") is not True
        or grounding.get("eligible") is not True
    ):
        return False
    lineage = selection.get("capture_lineage")
    if not isinstance(lineage, Mapping):
        return False
    if any(
        grounding.get(key) != lineage.get(key)
        for key in ("capture_id", "screenshot_sha256", "viewport_size")
    ):
        return False
    if (
        grounding.get("asset_content_sha256") != selection.get("asset_content_sha256")
        or grounding.get("transition_id") != selection.get("transition_id")
        or grounding.get("source_state_id") != selection.get("source_state_id")
        or grounding.get("element_ref") != selection.get("element_ref")
    ):
        return False

    candidate_id = grounding.get("candidate_id")
    candidate = next(
        (item for item in candidates.candidates if item.candidate_id == candidate_id),
        None,
    )
    if candidate is None or candidate.element_id != selection.get("element_ref"):
        return False
    local = next(
        (item for item in local_grounding.results if item.candidate_id == candidate_id),
        None,
    )
    if local is None or local.element_id != selection.get("element_ref"):
        return False
    if grounding.get("bbox") != _candidate_bbox(candidate):
        return False

    candidate_decision = next(
        (item for item in policy_decision.candidate_decisions if item.candidate_id == candidate_id),
        None,
    )
    if candidate_decision is None or candidate_decision.element_id != selection.get("element_ref"):
        return False
    if candidate_decision.click_point != grounding.get("click_point"):
        return False
    if policy_decision.allowed and (
        policy_decision.selected_candidate_id != candidate_id
        or policy_decision.selected_element_id != selection.get("element_ref")
        or policy_decision.selected_click_point != grounding.get("click_point")
    ):
        return False
    return True


def _candidate_bbox(candidate: RecognitionCandidate) -> dict[str, int]:
    if candidate.refined_bbox:
        bbox = candidate.refined_bbox
        return {
            "x": int(bbox.get("x", 0)),
            "y": int(bbox.get("y", 0)),
            "w": int(bbox.get("w", bbox.get("width", 0))),
            "h": int(bbox.get("h", bbox.get("height", 0))),
        }
    return candidate.element.bbox.to_dict()


__all__ = ["ReviewedWorkflowGateAdapter"]
