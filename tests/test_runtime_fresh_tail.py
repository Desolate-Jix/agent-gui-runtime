from app.agent.runtime_fresh_receipt import RuntimeFreshResultReceipt
from app.agent.runtime_receipt_store import RuntimeReceiptStore
import pytest


def test_fresh_receipt_has_no_workflow_and_is_factual():
    receipt = RuntimeFreshResultReceipt.from_dict({
        "contract_version": "runtime_fresh_result_receipt_v1", "receipt_id": "receipt.fresh",
        "issued_at": "2026-09-10T00:00:00Z", "session_id": "session.fresh",
        "observation_id": "observation.fresh", "intent_id": "intent.fresh",
        "source_sha256": "a" * 64, "action": {"action_id": "action.open", "semantic_action": "open_detail"},
        "outcome": "OBSERVATION_FAILED", "reason_code": "after_observation_unavailable",
        "attempt_count": 1, "gate_status": "allowed", "dispatch_status": "dispatched",
        "effect_status": "not_verified", "destination_status": "not_evaluated",
        "evidence": {"source_sha256": "a" * 64, "approved_preview_sha256": "b" * 64,
            "fresh_preview_sha256": "c" * 64, "consume_content_sha256": "d" * 64,
            "confirmation_id": "grounded-confirmation." + "e" * 64, "capture_id": "capture.after",
            "candidate_ref": "candidate:one", "gate_decision_ref": "gate:one"},
        "next_observation_id": None, "artifact_is_authorization": False,
    })
    assert receipt.workflow is None
    assert receipt.model_dump(mode="json")["effect_status"] == "not_verified"


def test_fresh_receipt_uses_existing_receipt_store_root(tmp_path):
    receipt = RuntimeFreshResultReceipt.from_dict({
        "contract_version": "runtime_fresh_result_receipt_v1", "receipt_id": "receipt.fresh",
        "issued_at": "2026-09-10T00:00:00Z", "session_id": "session.fresh", "observation_id": "observation.fresh",
        "intent_id": "intent.fresh", "source_sha256": "a" * 64,
        "action": {"action_id": "action.open", "semantic_action": "open_detail"}, "outcome": "EXECUTION_FAILED",
        "reason_code": "backend_not_started", "attempt_count": 1, "gate_status": "allowed", "dispatch_status": "not_started",
        "effect_status": "not_verified", "destination_status": "not_evaluated",
        "evidence": {"source_sha256": "a" * 64, "approved_preview_sha256": "b" * 64, "fresh_preview_sha256": "c" * 64,
            "consume_content_sha256": "d" * 64, "confirmation_id": "grounded-confirmation." + "e" * 64,
            "capture_id": "capture.after", "candidate_ref": "candidate:one", "gate_decision_ref": "gate:one"},
        "next_observation_id": None, "artifact_is_authorization": False})
    store = RuntimeReceiptStore(project_root=tmp_path)
    from app.agent.desktop_backend import BackendDispatchReceipt
    ref = store.put(receipt, backend_receipt=BackendDispatchReceipt("backend.fresh", "not_started", "backend_failed"))
    assert store.get(ref).runtime_receipt == receipt
    assert store.find_for_intent(session_id="session.fresh", observation_id="observation.fresh", intent_id="intent.fresh").runtime_receipt == receipt


def test_fresh_receipt_rejects_backend_status_mismatch(tmp_path):
    from app.agent.desktop_backend import BackendDispatchReceipt
    store = RuntimeReceiptStore(project_root=tmp_path)
    receipt = RuntimeFreshResultReceipt.from_dict({
        "contract_version":"runtime_fresh_result_receipt_v1","receipt_id":"receipt.pair","issued_at":"2026-09-10T00:00:00Z","session_id":"session.pair","observation_id":"observation.pair","intent_id":"intent.pair","source_sha256":"a"*64,
        "action":{"action_id":"action.open","semantic_action":"open_detail"},"outcome":"EXECUTION_FAILED","reason_code":"backend_not_started","attempt_count":1,"gate_status":"allowed","dispatch_status":"not_started","effect_status":"not_verified","destination_status":"not_evaluated",
        "evidence":{"source_sha256":"a"*64,"approved_preview_sha256":"b"*64,"fresh_preview_sha256":"c"*64,"consume_content_sha256":"d"*64,"confirmation_id":"grounded-confirmation."+"e"*64,"capture_id":"capture.pair","candidate_ref":"candidate:pair","gate_decision_ref":"gate:pair"},"next_observation_id":None,"artifact_is_authorization":False})
    with pytest.raises(ValueError, match="dispatch status"):
        store.put(receipt, backend_receipt=BackendDispatchReceipt("backend.pair", "dispatched", "none"))


def test_actual_fresh_approved_consume_is_readable_and_dispatches_once(tmp_path):
    from app.agent.fresh_learning_action_preview import build_fresh_learning_action_preview
    from tests.test_fresh_learning_action_preview import _setup
    host, owner, runtime, _backend, claims, source, session, intent = _setup(tmp_path)
    try:
        observation, reference = session.current_observation.to_dict(), source.reference()
        claims.claim_fresh_learning(observation=observation, intent=intent, source_reference=reference)
        def preview():
            bundle = owner.observe_for_action(target_window_handle=4242, target_process_id=9001, goal=intent.goal)
            capture = host.fresh_learning.archive.record(bundle.packet,
                **{k: reference[k] for k in ("connection_id", "task_id", "segment_id")})
            return build_fresh_learning_action_preview(bundle=bundle, capture_source=capture,
                observation=observation, intent=intent, source_reference=reference)
        approved = preview()
        pending = claims.mark_grounded_confirmation_pending(session_id=session.session_id,
            observation_id=observation["observation_id"], preview=approved)
        confirmed = claims.record_grounded_confirmation_decision(
            confirmation_id=pending.grounded_confirmation.confirmation_id, decision="approved")
        consumed = claims.begin_fresh_confirmation_consume(session.session_id, observation["observation_id"],
            fresh_preview=preview())
        assert consumed.phase == "grounded_confirmation_consume_started"
        assert consumed.grounded_consume.fresh_preview.content_sha256
        assert claims.get_for_grounded_confirmation(confirmation_id=pending.grounded_confirmation.confirmation_id).phase == consumed.phase
        dispatched = claims.mark_fresh_dispatch_started(session.session_id, observation["observation_id"])
        assert dispatched.phase == "dispatch_started"
        assert claims.mark_fresh_dispatch_started(session.session_id, observation["observation_id"]) == dispatched
    finally:
        with pytest.raises(ValueError): runtime.abandon_session(session_id=session.session_id)
        host.close()
