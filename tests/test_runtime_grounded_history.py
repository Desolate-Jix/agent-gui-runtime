import pytest
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStoreError
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore

def test_grounded_history_empty_and_corrupt_claim_fails_closed(tmp_path):
    store=RuntimeIntentClaimStore(project_root=tmp_path,receipt_store=RuntimeReceiptStore(project_root=tmp_path))
    assert store.list_grounded_claims() == ()
    (store.claims_root / ("a"*64 + ".json")).write_text("{}",encoding="utf-8")
    with pytest.raises(RuntimeIntentClaimStoreError): store.list_grounded_claims()


def test_grounded_history_returns_pending_but_not_legacy_claim(tmp_path):
    from tests.test_runtime_grounded_confirmation_store import _prepared_claim
    _, store, session, preview, _ = _prepared_claim(tmp_path)
    legacy = store.get_for_observation(session_id=session.session_id, observation_id=session.current_observation.observation_id)
    assert store.list_grounded_claims() == ()
    pending = store.mark_grounded_confirmation_pending(session_id=session.session_id, observation_id=session.current_observation.observation_id, preview=preview)
    history = store.list_grounded_claims()
    assert history == (pending,) and history[0].phase == "grounded_confirmation_pending"
    assert legacy.claim_id == pending.claim_id


@pytest.mark.parametrize("decision", ["approved", "denied"])
def test_grounded_history_decision_phases_and_reopen_owner(tmp_path, decision):
    from tests.test_runtime_grounded_confirmation_store import _prepared_claim, _Clock
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    clock = _Clock()
    _, store, session, preview, _ = _prepared_claim(tmp_path, clock=clock)
    pending = store.mark_grounded_confirmation_pending(session_id=session.session_id, observation_id=session.current_observation.observation_id, preview=preview)
    result = store.record_grounded_confirmation_decision(confirmation_id=pending.grounded_confirmation.confirmation_id, decision=decision)
    assert store.list_grounded_claims() == (result,)
    reopened = RuntimeIntentClaimStore(project_root=tmp_path, receipt_store=RuntimeReceiptStore(project_root=tmp_path), clock=clock)
    history = reopened.list_grounded_claims()
    assert len(history) == 1 and history[0].claim_id == result.claim_id
    assert history[0].grounded_confirmation.owner_is_current is False


def test_grounded_history_closed_phase(tmp_path):
    from tests.test_runtime_grounded_confirmation_store import _prepared_claim, _Clock
    clock = _Clock(); _, store, session, preview, _ = _prepared_claim(tmp_path, clock=clock)
    pending=store.mark_grounded_confirmation_pending(session_id=session.session_id, observation_id=session.current_observation.observation_id, preview=preview)
    clock.value += __import__("datetime").timedelta(seconds=300)
    closed=store.close_grounded_confirmation(confirmation_id=pending.grounded_confirmation.confirmation_id, reason_code="grounded_confirmation_expired")
    assert store.list_grounded_claims() == (closed,)
