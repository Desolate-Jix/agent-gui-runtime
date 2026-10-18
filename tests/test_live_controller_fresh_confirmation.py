"""从零学习的实际控制器到同库确认链，所有输入保持零派发。"""

import pytest

from app.agent.live_controller import LiveControllerDecision
from tests.test_fresh_learning_action_preview import _setup


@pytest.mark.parametrize("decision", ["approved", "denied", "cancelled"])
def test_fresh_controller_publishes_exact_preview_then_independent_decision(tmp_path, decision):
    host, owner, runtime, backend, claims, source, session, intent = _setup(tmp_path)
    confirmation_id = None
    try:
        claim = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001)
        assert not isinstance(claim, LiveControllerDecision), claim
        assert claim.phase == "grounded_confirmation_pending"
        confirmation_id = claim.grounded_confirmation.confirmation_id
        assert len(owner._screenshot_service.calls) == 2
        assert runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001) == claim
        assert len(owner._screenshot_service.calls) == 2
        assert runtime.get_local_grounded_image(confirmation_id=confirmation_id) == owner._screenshot_service.path.read_bytes()
        if decision == "cancelled":
            result = runtime.cancel_grounded_review(session_id=session.session_id)
            assert result.phase == "grounded_confirmation_closed"
        else:
            result = runtime.record_grounded_confirmation_decision(confirmation_id=confirmation_id, decision=decision)
            assert result.phase == "grounded_confirmation_" + decision
        assert backend.commands == []
        assert list(claims.dispatch_started_root.glob("*.json")) == []
        if decision == "approved":
            blocked = runtime.consume_grounded_confirmation(confirmation_id=confirmation_id)
            assert isinstance(blocked, LiveControllerDecision) and blocked.status == "REJECTED"
            assert backend.commands == []
    finally:
        if confirmation_id is not None and session.session_id in runtime._sessions:
            runtime.cancel_grounded_review(session_id=session.session_id)
        elif session.session_id in runtime._grounded_publications:
            runtime.cancel_grounded_review(session_id=session.session_id)
        elif confirmation_id is None:
            runtime.abandon_session(session_id=session.session_id)
        host.close()


def test_fresh_confirmation_history_is_readable_without_fake_workflow(tmp_path):
    from app.desktop_review.grounded_history import history_item
    from app.desktop_review.grounded_history_dialog import _item
    host, owner, runtime, backend, claims, source, session, intent = _setup(tmp_path)
    try:
        claim = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001)
        assert not isinstance(claim, LiveControllerDecision), claim
        item = history_item(claims, claim)
        assert item["selection"]["source_kind"] == "fresh_learning"
        assert "asset_id" not in item["selection"]
        assert _item(item) == item
        assert item["operation"] == "close_unexecuted"
        assert item["receipt"] is None
    finally:
        if session.session_id in runtime._grounded_publications:
            runtime.cancel_grounded_review(session_id=session.session_id)
        else:
            runtime.abandon_session(session_id=session.session_id)
        host.close()


def test_bad_fresh_intent_rejects_before_capture_or_claim(tmp_path):
    host, owner, runtime, backend, claims, source, session, intent = _setup(tmp_path)
    try:
        rejected = runtime.request_grounded_confirmation({**intent.to_dict(), "click_point": {"x": 1, "y": 2}}, target_process_id=9001)
        assert isinstance(rejected, LiveControllerDecision) and rejected.status == "REJECTED"
        assert len(owner._screenshot_service.calls) == 1
        assert claims.find_for_observation(session_id=session.session_id, observation_id=intent.observation_id) is None
    finally:
        runtime.abandon_session(session_id=session.session_id)
        host.close()


def test_tampered_archived_png_blocks_approval_but_can_still_be_denied(tmp_path):
    host, owner, runtime, backend, claims, source, session, intent = _setup(tmp_path)
    try:
        claim = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001)
        assert not isinstance(claim, LiveControllerDecision), claim
        confirmation_id = claim.grounded_confirmation.confirmation_id
        preview = claim.grounded_confirmation.preview.to_dict()
        path = host.fresh_learning.archive.png_root / (preview["capture_source"]["screenshot_sha256"] + ".png")
        path.write_bytes(b"tampered-png")
        rejected = runtime.record_grounded_confirmation_decision(confirmation_id=confirmation_id, decision="approved")
        assert isinstance(rejected, LiveControllerDecision) and rejected.status == "RECOVERY_REQUIRED"
        assert claims.get_for_grounded_confirmation(confirmation_id=confirmation_id).phase == "grounded_confirmation_pending"
        with pytest.raises(ValueError):
            runtime.get_local_grounded_image(confirmation_id=confirmation_id)
        denied = runtime.record_grounded_confirmation_decision(confirmation_id=confirmation_id, decision="denied")
        assert denied.phase == "grounded_confirmation_denied"
        assert session.session_id not in runtime._sessions
        assert backend.commands == []
    finally:
        if session.session_id in runtime._grounded_publications:
            runtime.cancel_grounded_review(session_id=session.session_id)
        host.close()


def test_request_retry_after_uncertain_publish_reuses_same_preview_and_claim(tmp_path, monkeypatch):
    host, owner, runtime, backend, claims, source, session, intent = _setup(tmp_path)
    real_mark = claims.mark_grounded_confirmation_pending
    calls = []
    def uncertain(**kwargs):
        result = real_mark(**kwargs)
        calls.append(result.claim_id)
        if len(calls) == 1:
            raise OSError("simulated response loss after durable publication")
        return result
    monkeypatch.setattr(claims, "mark_grounded_confirmation_pending", uncertain)
    try:
        first = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001)
        assert isinstance(first, LiveControllerDecision) and first.status == "RECOVERY_REQUIRED"
        second = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001)
        assert second.phase == "grounded_confirmation_pending"
        assert len(owner._screenshot_service.calls) == 2
        assert calls == [second.claim_id, second.claim_id]
        assert backend.commands == []
    finally:
        if session.session_id in runtime._grounded_publications:
            runtime.cancel_grounded_review(session_id=session.session_id)
        host.close()


def test_observed_payment_target_is_not_promoted_by_open_detail_proposal(tmp_path):
    host, owner, runtime, backend, claims, source, session, intent = _setup(tmp_path)
    intent = type(intent).from_dict({**intent.to_dict(), "goal": "Pay now"})
    try:
        result = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001)
        assert isinstance(result, LiveControllerDecision) and result.status == "REJECTED"
        assert claims.find_for_observation(session_id=session.session_id, observation_id=intent.observation_id) is None
        assert backend.commands == []
    finally:
        runtime.abandon_session(session_id=session.session_id)
        host.close()
