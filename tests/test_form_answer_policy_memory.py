from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.agent.form_answer_policy_memory import FormAnswerPolicyMemoryStore
from app.agent.form_question_contracts import build_form_question_contract
from app.agent.form_question_understanding import normalize_form_question_intent
from app.agent.reviewed_interface_memory import ReviewedInterfaceMemoryStore


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
EVIDENCE_HASH = "a" * 64


def _understanding(label: str) -> dict:
    return normalize_form_question_intent(
        build_form_question_contract(
            {
                "question_id": "work_rights",
                "label": label,
                "field_type": "radio",
                "required": True,
                "risk": "ordinary_field",
            }
        )
    )


def _approved_policy(
    store: FormAnswerPolicyMemoryStore,
    *,
    scope_type: str = "site",
    scope_key: str = "careers.example",
    label: str = "Do you have the right to work in New Zealand?",
    expires_at: datetime | None = None,
) -> dict:
    return store.record_review(
        question_understanding=_understanding(label),
        review_decision="approved",
        scope_type=scope_type,
        scope_key=scope_key,
        answer_reference="evidence:work_rights:nz:v1",
        evidence_hash=EVIDENCE_HASH,
        reviewed_at=NOW,
        expires_at=expires_at or NOW + timedelta(days=30),
    )


def test_human_approved_synonym_reuses_reviewed_answer_reference(tmp_path) -> None:
    store = FormAnswerPolicyMemoryStore(project_root=tmp_path)
    _approved_policy(store)

    result = store.resolve(
        question_understanding=_understanding("Are you legally authorized to work in New Zealand?"),
        scope_context={"site": "careers.example"},
        now=NOW + timedelta(days=1),
    )

    assert result["status"] == "reviewed_strategy_available"
    assert result["answer_reference"] == "evidence:work_rights:nz:v1"
    assert result["scope"] == {"type": "site", "key": "careers.example"}
    assert result["fill_authorized"] is False
    assert result["artifact_is_authorization"] is False


def test_human_rejection_blocks_reuse(tmp_path) -> None:
    store = FormAnswerPolicyMemoryStore(project_root=tmp_path)
    store.record_review(
        question_understanding=_understanding("Do you have the right to work in New Zealand?"),
        review_decision="rejected",
        scope_type="site",
        scope_key="careers.example",
        answer_reference="evidence:work_rights:nz:v1",
        evidence_hash=EVIDENCE_HASH,
        reviewed_at=NOW,
        expires_at=NOW + timedelta(days=30),
    )

    result = store.resolve(
        question_understanding=_understanding("Are you legally authorized to work in New Zealand?"),
        scope_context={"site": "careers.example"},
        now=NOW + timedelta(days=1),
    )

    assert result["status"] == "blocked_by_human_review"
    assert result["answer_reference"] is None
    assert result["requires_user_review"] is True


def test_inverse_question_polarity_requires_re_evaluation(tmp_path) -> None:
    store = FormAnswerPolicyMemoryStore(project_root=tmp_path)
    _approved_policy(store)

    result = store.resolve(
        question_understanding=_understanding("Do you require sponsorship to work in New Zealand?"),
        scope_context={"site": "careers.example"},
        now=NOW + timedelta(days=1),
    )

    assert result["status"] == "requires_re_evaluation"
    assert result["reason"] == "semantic_polarity_changed"
    assert result["answer_reference"] is None


def test_expired_evidence_is_not_reused(tmp_path) -> None:
    store = FormAnswerPolicyMemoryStore(project_root=tmp_path)
    _approved_policy(store, expires_at=NOW + timedelta(hours=1))

    result = store.resolve(
        question_understanding=_understanding("Are you legally authorized to work in New Zealand?"),
        scope_context={"site": "careers.example"},
        now=NOW + timedelta(days=1),
    )

    assert result["status"] == "needs_user_review"
    assert result["reason"] == "reviewed_evidence_expired"
    assert result["answer_reference"] is None


@pytest.mark.parametrize(
    ("scope_type", "scope_key", "scope_context"),
    [
        ("one_time", "attempt-7", {"one_time": "attempt-7"}),
        ("workflow_class", "job_application", {"workflow_class": "job_application"}),
        ("site", "careers.example", {"site": "careers.example"}),
        ("global_profile", "default", {}),
    ],
)
def test_supported_scopes_match_only_their_reviewed_context(
    tmp_path,
    scope_type: str,
    scope_key: str,
    scope_context: dict,
) -> None:
    store = FormAnswerPolicyMemoryStore(project_root=tmp_path)
    _approved_policy(store, scope_type=scope_type, scope_key=scope_key)

    matched = store.resolve(
        question_understanding=_understanding("Are you legally authorized to work in New Zealand?"),
        scope_context=scope_context,
        now=NOW + timedelta(days=1),
    )

    assert matched["status"] == "reviewed_strategy_available"

    if scope_type != "global_profile":
        mismatched = store.resolve(
            question_understanding=_understanding("Are you legally authorized to work in New Zealand?"),
            scope_context={scope_type: "different"},
            now=NOW + timedelta(days=1),
        )
        assert mismatched["status"] == "needs_user_review"
        assert mismatched["reason"] == "no_matching_reviewed_scope"


def test_unknown_intent_never_reuses_a_reviewed_strategy(tmp_path) -> None:
    store = FormAnswerPolicyMemoryStore(project_root=tmp_path)
    _approved_policy(store)

    result = store.resolve(
        question_understanding={
            "intent": "unknown_question",
            "polarity": "unknown",
            "confidence": 0.0,
            "recommended_policy": "needs_user_review",
        },
        scope_context={"site": "careers.example"},
        now=NOW,
    )

    assert result["status"] == "needs_user_review"
    assert result["reason"] == "unknown_or_ambiguous_question_intent"


def test_memory_persists_only_references_hashes_and_redacted_agent_context(tmp_path) -> None:
    raw_pii = "private.person@example.invalid"
    store = FormAnswerPolicyMemoryStore(project_root=tmp_path)
    recorded = _approved_policy(store)

    result = store.resolve(
        question_understanding=_understanding("Are you legally authorized to work in New Zealand?"),
        scope_context={"site": "careers.example"},
        now=NOW + timedelta(days=1),
    )
    serialized_result = json.dumps(result, ensure_ascii=False)
    persisted = (tmp_path / recorded["record_path"]).read_text(encoding="utf-8")

    assert raw_pii not in persisted
    assert raw_pii not in serialized_result
    assert '"bbox"' not in persisted
    assert '"click_point"' not in persisted
    assert '"raw_value"' not in persisted
    assert EVIDENCE_HASH in persisted
    assert "evidence:work_rights:nz:v1" in persisted

    with pytest.raises(ValueError, match="opaque evidence reference"):
        store.record_review(
            question_understanding=_understanding("Do you have the right to work in New Zealand?"),
            review_decision="approved",
            scope_type="site",
            scope_key="careers.example",
            answer_reference=raw_pii,
            evidence_hash=EVIDENCE_HASH,
            reviewed_at=NOW,
            expires_at=NOW + timedelta(days=30),
        )


def test_reviewed_interface_memory_exposes_answer_policy_as_non_authorizing_agent_evidence(tmp_path) -> None:
    answer_store = FormAnswerPolicyMemoryStore(project_root=tmp_path)
    _approved_policy(answer_store)
    interface_store = ReviewedInterfaceMemoryStore(project_root=tmp_path)

    context = interface_store.form_answer_policy_context(
        question_understanding=_understanding("Are you legally authorized to work in New Zealand?"),
        scope_context={"site": "careers.example"},
        now=NOW + timedelta(days=1),
    )

    assert context["contract_version"] == "form_answer_policy_agent_context_v1"
    assert context["resolution"]["status"] == "reviewed_strategy_available"
    assert context["execution_contract"] == {
        "current_inventory_required": True,
        "current_target_resolution_required": True,
        "policy_gate_required": True,
        "action_gate_required": True,
        "artifact_is_authorization": False,
    }
