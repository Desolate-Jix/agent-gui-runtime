from __future__ import annotations

from typing import Any


CONTRACT_VERSION = "form_action_gate_decision_v1"
ALLOWED_POLICIES = {"auto_fill", "derived_with_evidence"}
SAFE_INTERCEPT_POLICIES = {"blocked_sensitive", "final_submit"}


def evaluate_form_action_policy(
    *,
    question: dict[str, Any] | None,
    decision: dict[str, Any] | None,
) -> dict[str, Any]:
    question_payload = question if isinstance(question, dict) else {}
    decision_payload = decision if isinstance(decision, dict) else {}
    policy = str(decision_payload.get("policy") or "needs_user_review")
    allowed = False
    reason = "policy_requires_review"
    if question_payload.get("disabled") is True:
        reason = "field_disabled"
    elif str(question_payload.get("risk") or "") == "final_submit" or policy == "final_submit":
        reason = "final_submit_forbidden"
    elif policy in ALLOWED_POLICIES:
        if not _has_answer_evidence(decision_payload):
            reason = "answer_evidence_missing"
        else:
            allowed = True
            reason = "answer_policy_and_evidence_valid"
    elif policy == "blocked_sensitive":
        reason = "sensitive_field_blocked"
    elif policy == "unsupported":
        reason = "unsupported_field"

    return {
        "contract_version": CONTRACT_VERSION,
        "question_id": question_payload.get("question_id") or decision_payload.get("question_id"),
        "policy": policy,
        "policy_allowed": allowed,
        "reason": reason,
        "unsafe_prevented": bool(not allowed and policy in SAFE_INTERCEPT_POLICIES),
        "execution_authorized": False,
        "requires_current_grounding": True,
        "requires_action_gate": True,
        "fill_attempted": False,
        "submit_attempted": False,
        "artifact_is_authorization": False,
    }


def _has_answer_evidence(decision: dict[str, Any]) -> bool:
    return bool(
        decision.get("evidence_refs")
        and decision.get("value_reference")
        and decision.get("value_hash")
        and int(decision.get("value_length") or 0) > 0
    )
