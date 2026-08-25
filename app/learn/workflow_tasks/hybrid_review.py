from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.core.model_server import validate_qwen_cleanup_receipt
from app.learn.hybrid.vista_refinement import validate_vista_proposal
from app.learn.recognition.uei.canonical import canonical_json_bytes, seal_immutable


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
            "projection_shape": "hybrid_vista_review_task_projection_v1",
            "outcome": "safe_stopped",
            "failure_reason": "cancelled_before_review_projection",
            "review_status": "REVIEW_REQUIRED",
            "automatic_acceptance": False,
            "proposals": [],
        }
    cleanup_receipt = validate_qwen_cleanup_receipt(payload.get("qwen_cleanup_receipt"))
    requests = payload.get("hybrid_vista_requests")
    if not isinstance(requests, list) or not requests:
        raise ValueError("Hybrid review projection requires exact VISTA requests")
    request_by_id = {
        str(item.get("candidate_id") or ""): item
        for item in requests
        if isinstance(item, dict)
    }
    if len(request_by_id) != len(requests) or "" in request_by_id:
        raise ValueError("Hybrid VISTA request identity set is invalid")
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
        request = request_by_id.get(candidate_id)
        submitted = item.get("hybrid_vista_request")
        if request is None or canonical_json_bytes(submitted) != canonical_json_bytes(request):
            raise ValueError("Hybrid VISTA result is cross-attached to a request")
        raw_provider_result = proposal.get("raw_provider_result")
        revalidated = validate_vista_proposal(
            request=request,
            raw_result=raw_provider_result,
        )
        if canonical_json_bytes(revalidated) != canonical_json_bytes(proposal):
            raise ValueError("Hybrid VISTA proposal does not match raw provider evidence")
        if proposal.get("review_status") != "REVIEW_REQUIRED":
            raise ValueError("Hybrid VISTA proposal must remain review required")
        normalized = deepcopy(proposal)
        normalized["automatic_acceptance"] = False
        normalized.pop("canonical_acceptance", None)
        proposals.append(normalized)
    if seen_ids != set(request_by_id) or len(proposals) != len(requests):
        raise ValueError("Hybrid review projection request/result coverage mismatch")
    return seal_immutable(
        {
            "contract_version": "hybrid_review_projection_v1",
            "projection_shape": "hybrid_vista_review_task_projection_v1",
            "outcome": "completed",
            "review_status": "REVIEW_REQUIRED",
            "automatic_acceptance": False,
            "proposals": proposals,
            "hybrid_capture_bundle_ref": deepcopy(
                payload.get("hybrid_capture_bundle_ref")
            ),
            "qwen_cleanup_receipt": deepcopy(cleanup_receipt),
            "requested_candidate_ids": list(request_by_id),
            "completed_candidate_ids": [item["candidate_id"] for item in proposals],
            "completed_count": len(proposals),
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
