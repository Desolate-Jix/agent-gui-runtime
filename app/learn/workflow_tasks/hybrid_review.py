from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.learn.hybrid.vista_refinement import QWEN_RELEASE_PREREQUISITE
from app.learn.recognition.uei.canonical import seal_immutable


def run_hybrid_review_projection_task(
    payload: dict[str, Any],
    *,
    cancellation_event: Any | None = None,
) -> dict[str, Any]:
    """把校准提议投影为最终人工审核输入；不调用模型或执行动作。"""

    if not isinstance(payload, dict):
        raise ValueError("Hybrid review projection payload must be an object")
    if _cancelled(cancellation_event):
        return {
            "contract_version": "hybrid_review_projection_v1",
            "outcome": "safe_stopped",
            "failure_reason": "cancelled_before_review_projection",
            "review_status": "REVIEW_REQUIRED",
            "automatic_acceptance": False,
            "proposals": [],
        }
    if payload.get("qwen_release_prerequisite") != QWEN_RELEASE_PREREQUISITE:
        raise ValueError("Hybrid review projection lost Qwen release prerequisite")
    raw_results = payload.get("hybrid_vista_results")
    if not isinstance(raw_results, list) or not raw_results:
        raise ValueError("Hybrid review projection requires VISTA results")
    proposals: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in raw_results:
        if not isinstance(item, dict):
            raise ValueError("Hybrid VISTA result must be an object")
        proposal = item.get("hybrid_vista_proposal", item)
        if not isinstance(proposal, dict):
            raise ValueError("Hybrid VISTA proposal must be an object")
        candidate_id = str(proposal.get("candidate_id") or "").strip()
        if not candidate_id or candidate_id in seen_ids:
            raise ValueError("Hybrid review projection candidate identity is invalid")
        seen_ids.add(candidate_id)
        if proposal.get("review_status") != "REVIEW_REQUIRED":
            raise ValueError("Hybrid VISTA proposal must remain review required")
        normalized = deepcopy(proposal)
        normalized["automatic_acceptance"] = False
        normalized.pop("canonical_acceptance", None)
        proposals.append(normalized)
    return seal_immutable(
        {
            "contract_version": "hybrid_review_projection_v1",
            "outcome": "completed",
            "review_status": "REVIEW_REQUIRED",
            "automatic_acceptance": False,
            "proposals": proposals,
            "hybrid_capture_bundle_ref": deepcopy(
                payload.get("hybrid_capture_bundle_ref")
            ),
            "qwen_release_prerequisite": deepcopy(
                QWEN_RELEASE_PREREQUISITE
            ),
            "no_live_click_authorization": True,
            "execute_binding_enabled": False,
        }
    )


def _cancelled(cancellation_event: Any | None) -> bool:
    return bool(
        cancellation_event is not None
        and hasattr(cancellation_event, "is_set")
        and cancellation_event.is_set()
    )


__all__ = ["run_hybrid_review_projection_task"]
