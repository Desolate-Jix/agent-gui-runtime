"""纯函数精修决策；不启动 provider，也不伪造 provider 输出。"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

MODES_POLICY_VERSION = "selection_refinement_modes_v1"
EDGE_TRIGGER_VERSION = "selection_edge_margin_trigger_v1"
EDGE_MARGIN_RATIO = 0.1


def decide_refinement(*, selection: dict, policy: dict) -> dict:
    """在唯一、同 capture 且显式几何触发时才返回 requested。"""
    if not isinstance(selection, Mapping) or selection.get("contract_version") != "hybrid_target_selection_v1":
        raise ValueError("refinement requires hybrid_target_selection_v1")
    if not isinstance(policy, Mapping) or set(policy) != {"policy_version", "mode", "geometric_trigger"}:
        raise ValueError("refinement policy is not closed")
    allowed_modes = {
        "selection_refinement_conditional_v1": {"conditional"},
        MODES_POLICY_VERSION: {"never", "conditional", "always"},
    }.get(policy["policy_version"], set())
    if policy["mode"] not in allowed_modes or not isinstance(policy["geometric_trigger"], bool):
        raise ValueError("refinement policy is invalid")
    selection_status = selection.get("selection_status")
    candidate_id = selection.get("candidate_id")
    reason = _not_requested_reason(selection_status)
    base: dict[str, Any] = {
        "contract_version": "hybrid_selection_refinement_v1",
        "candidate_id": candidate_id if isinstance(candidate_id, str) else None,
        "policy_version": policy["policy_version"],
        "policy": deepcopy(dict(policy)),
        "parent_refs": deepcopy(selection.get("parent_refs")) if isinstance(selection.get("parent_refs"), Mapping) else {},
        "provider_result": None,
    }
    if reason is not None:
        return {**base, "status": "not_requested", "reason": reason}
    point = selection.get("model_proposal", {}).get("canonical_capture_pixel_point") if isinstance(selection.get("model_proposal"), Mapping) else None
    if not isinstance(candidate_id, str) or not isinstance(point, list) or len(point) != 2:
        return {**base, "status": "not_requested", "reason": "invalid_selection"}
    if selection_status != "selected":
        return {**base, "status": "not_requested", "reason": "invalid_selection"}
    if policy["mode"] == "never":
        return {**base, "status": "skipped", "reason": "policy_never"}
    if policy["mode"] == "always":
        return {**base, "status": "requested", "reason": "policy_always"}
    if not policy["geometric_trigger"]:
        return {**base, "status": "skipped", "reason": "valid_unique_point_no_geometric_trigger"}
    return {**base, "status": "requested", "reason": "explicit_geometric_trigger"}


def _not_requested_reason(status: object) -> str | None:
    return {
        "ambiguous": "ambiguous_selection",
        "unbound": "no_candidate_selection",
        "provider_failure": "provider_failure",
    }.get(status)


__all__ = ["decide_refinement"]
