from __future__ import annotations

import pytest
from datetime import datetime, timedelta, timezone

from app.agent.fresh_learning_action_contracts import FreshLearningIntent
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from tests.test_formal_fresh_graph_source import _stage
from tests.test_formal_fresh_runtime_session import _runtime


@pytest.mark.parametrize("marker_root", ["dispatch_started_root", "grounded_consume_root", "confirmation_requests_root"])
def test_fresh_confirmation_rejects_mixed_execution_or_legacy_markers(tmp_path, marker_root):
    from tests.test_fresh_learning_action_preview import _setup
    host, owner, runtime, backend, claims, source, session, intent = _setup(tmp_path)
    injected = None
    try:
        pending = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001)
        confirmation_id = pending.grounded_confirmation.confirmation_id
        identity = pending.claim_id.removeprefix("claim.")
        injected = getattr(claims, marker_root) / (identity + ".json")
        injected.write_bytes(b"{}")
        with pytest.raises(ValueError, match="mixed"):
            claims.get_for_grounded_confirmation(confirmation_id=confirmation_id)
        with pytest.raises(ValueError, match="mixed"):
            claims.record_grounded_confirmation_decision(confirmation_id=confirmation_id, decision="approved")
        assert backend.commands == []
    finally:
        if injected is not None:
            assert injected.resolve().is_relative_to(tmp_path.resolve())
            injected.unlink()
        runtime.cancel_grounded_review(session_id=session.session_id)
        host.close()


def _fresh_session(tmp_path):
    host, connection, segment, _packet, _args, staged = _stage(tmp_path)
    runtime = session = None
    try:
        runtime, _backend, claims, source = _runtime(host, connection, segment, staged)
        session = runtime.start_session_preparation(preparation_id="fresh-claim")
        return host, runtime, session, claims, source
    except BaseException:
        if runtime is not None and session is not None:
            runtime.abandon_session(session_id=session.session_id)
        host.close()
        raise


def test_fresh_intent_is_strict_and_binds_actual_runtime_observation(tmp_path):
    host, runtime, session, _claims, source = _fresh_session(tmp_path)
    try:
        observation = session.current_observation.to_dict()
        intent = FreshLearningIntent.from_dict({
            "contract_version": "fresh_learning_action_intent_v1",
            "intent_id": "intent.fresh",
            "session_id": session.session_id,
            "observation_id": observation["observation_id"],
            "source_sha256": source.reference()["source_sha256"],
            "action_id": "action.open",
            "semantic_action": "open_detail",
            "goal": "Inspect the selected item",
        })
        assert intent.to_dict()["semantic_action"] == "open_detail"
        with pytest.raises(ValueError):
            FreshLearningIntent.from_dict({**intent.to_dict(), "click_point": {"x": 1}})
    finally:
        runtime.abandon_session(session_id=session.session_id)
        host.close()


def test_fresh_claim_uses_existing_store_root_and_rejects_conflicting_intent(tmp_path):
    host, runtime, session, claims, source = _fresh_session(tmp_path)
    try:
        observation = session.current_observation.to_dict()
        source_reference = source.reference()
        intent = FreshLearningIntent.from_dict({
            "contract_version": "fresh_learning_action_intent_v1", "intent_id": "intent.claim",
            "session_id": session.session_id, "observation_id": observation["observation_id"],
            "source_sha256": source_reference["source_sha256"], "action_id": "action.open",
            "semantic_action": "open_detail", "goal": "Open detail",
        })
        claimed = claims.claim_fresh_learning(observation=observation, intent=intent,
            source_reference=source_reference)
        assert claimed.phase == "claimed"
        assert claimed.observation.to_dict() == observation
        assert claimed.intent == intent
        assert claims.claim_fresh_learning(observation=observation, intent=intent,
            source_reference=source_reference) == claimed
        changed = FreshLearningIntent.from_dict({**intent.to_dict(), "intent_id": "intent.changed"})
        with pytest.raises(ValueError, match="conflict"):
            claims.claim_fresh_learning(observation=observation, intent=changed,
                source_reference=source_reference)
    finally:
        with pytest.raises(ValueError, match="durable intent claim"):
            runtime.abandon_session(session_id=session.session_id)
        host.close()


def test_fresh_grounded_pending_denial_and_close_use_actual_preview(tmp_path):
    from app.agent.fresh_learning_action_preview import build_fresh_learning_action_preview
    from tests.test_fresh_learning_action_preview import _setup

    host, owner, runtime, _backend, claims, source, session, intent = _setup(tmp_path)
    try:
        observation, reference = session.current_observation.to_dict(), source.reference()
        claimed = claims.claim_fresh_learning(observation=observation, intent=intent,
            source_reference=reference)
        bundle = owner.observe_for_action(target_window_handle=4242, target_process_id=9001, goal=intent.goal)
        capture_source = host.fresh_learning.archive.record(bundle.packet,
            **{key: reference[key] for key in ("connection_id", "task_id", "segment_id")})
        preview = build_fresh_learning_action_preview(bundle=bundle, capture_source=capture_source,
            observation=observation, intent=intent, source_reference=reference)
        pending = claims.mark_grounded_confirmation_pending(session_id=observation["session_id"],
            observation_id=observation["observation_id"], preview=preview)
        confirmation_id = pending.grounded_confirmation.confirmation_id
        assert pending.phase == "grounded_confirmation_pending"
        from app.agent.fresh_learning_action_preview import FreshLearningActionPreview
        assert isinstance(pending.grounded_confirmation.preview, FreshLearningActionPreview)
        assert pending.grounded_confirmation.preview.to_dict() == preview.to_dict()
        assert pending.grounded_confirmation.owner_is_current is True
        assert pending.grounded_confirmation.request_content_sha256
        assert pending.grounded_confirmation.requested_at < pending.grounded_confirmation.expires_at
        assert pending.grounded_confirmation.closed_reason_code is None
        assert claims.list_grounded_claims() == (pending,)
        assert claims.get_for_grounded_confirmation(confirmation_id=confirmation_id) == pending
        assert claims.mark_grounded_confirmation_pending(session_id=observation["session_id"],
            observation_id=observation["observation_id"], preview=preview) == pending
        denied = claims.record_grounded_confirmation_decision(confirmation_id=confirmation_id, decision="denied")
        assert denied.phase == "grounded_confirmation_denied"
        closed = claims.close_grounded_confirmation(confirmation_id=confirmation_id,
            reason_code="grounded_confirmation_cancelled")
        assert closed.phase == "grounded_confirmation_closed"
        with pytest.raises(ValueError, match="cannot be consumed"):
            claims.begin_grounded_confirmation_consume(confirmation_id=confirmation_id,
                fresh_preview=preview, current_observation={}, selection={}, grounding={},
                execution_gate={}, gate_decision_ref="gate.no", target_process_id=9001)
    finally:
        with pytest.raises(ValueError, match="durable intent claim"):
            runtime.abandon_session(session_id=session.session_id)
        host.close()


def test_fresh_pending_rejects_new_capture_and_restarted_owner_cannot_approve(tmp_path):
    from app.agent.fresh_learning_action_preview import build_fresh_learning_action_preview
    from tests.test_fresh_learning_action_preview import _setup

    host, owner, runtime, _backend, claims, source, session, intent = _setup(tmp_path)
    try:
        observation, reference = session.current_observation.to_dict(), source.reference()
        claims.claim_fresh_learning(observation=observation, intent=intent, source_reference=reference)

        def make_preview():
            bundle = owner.observe_for_action(target_window_handle=4242, target_process_id=9001, goal=intent.goal)
            capture_source = host.fresh_learning.archive.record(bundle.packet,
                **{key: reference[key] for key in ("connection_id", "task_id", "segment_id")})
            return build_fresh_learning_action_preview(bundle=bundle, capture_source=capture_source,
                observation=observation, intent=intent, source_reference=reference)

        first = make_preview()
        pending = claims.mark_grounded_confirmation_pending(session_id=observation["session_id"],
            observation_id=observation["observation_id"], preview=first)
        with pytest.raises(ValueError, match="conflict"):
            claims.mark_grounded_confirmation_pending(session_id=observation["session_id"],
                observation_id=observation["observation_id"], preview=make_preview())
        reopened = RuntimeIntentClaimStore(project_root=source.project_root,
            receipt_store=RuntimeReceiptStore(project_root=source.project_root))
        result = reopened.record_grounded_confirmation_decision(
            confirmation_id=pending.grounded_confirmation.confirmation_id, decision="approved")
        assert result.phase == "grounded_confirmation_closed"
        assert result.grounded_confirmation.closed_reason == "grounded_confirmation_restarted"
    finally:
        with pytest.raises(ValueError, match="durable intent claim"):
            runtime.abandon_session(session_id=session.session_id)
        host.close()


def test_fresh_pending_expiry_closes_without_approval_authority(tmp_path):
    from app.agent.fresh_learning_action_preview import build_fresh_learning_action_preview
    from tests.test_fresh_learning_action_preview import _setup

    host, owner, runtime, _backend, _claims, source, session, intent = _setup(tmp_path)
    try:
        observation, reference = session.current_observation.to_dict(), source.reference()
        now = [datetime(2026, 9, 10, tzinfo=timezone.utc)]
        claims = RuntimeIntentClaimStore(project_root=source.project_root,
            receipt_store=RuntimeReceiptStore(project_root=source.project_root), clock=lambda: now[0])
        claims.claim_fresh_learning(observation=observation, intent=intent, source_reference=reference)
        bundle = owner.observe_for_action(target_window_handle=4242, target_process_id=9001, goal=intent.goal)
        capture_source = host.fresh_learning.archive.record(bundle.packet,
            **{key: reference[key] for key in ("connection_id", "task_id", "segment_id")})
        preview = build_fresh_learning_action_preview(bundle=bundle, capture_source=capture_source,
            observation=observation, intent=intent, source_reference=reference)
        pending = claims.mark_grounded_confirmation_pending(session_id=observation["session_id"],
            observation_id=observation["observation_id"], preview=preview)
        now[0] += timedelta(seconds=301)
        expired = claims.record_grounded_confirmation_decision(
            confirmation_id=pending.grounded_confirmation.confirmation_id, decision="approved")
        assert expired.phase == "grounded_confirmation_closed"
        assert expired.grounded_confirmation.closed_reason == "grounded_confirmation_expired"
    finally:
        with pytest.raises(ValueError, match="durable intent claim"):
            runtime.abandon_session(session_id=session.session_id)
        host.close()
