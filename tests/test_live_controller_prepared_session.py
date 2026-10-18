"""只用假观测/后端验证真实控制器的未消费会话释放。"""
from __future__ import annotations

import pytest
import threading

from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStoreError
from tests.test_live_controller_w4 import _controller, _intent


def test_abandon_unclaimed_session_releases_only_owned_window_without_dispatch(tmp_path):
    controller, source, _, _, backend = _controller(tmp_path / "first", target_window_handle=91801)
    other, _, _, _, other_backend = _controller(tmp_path / "other", target_window_handle=91801)
    session = controller.start_session()
    with pytest.raises(RuntimeError, match="lease|session|window"):
        other.start_session()
    controller.abandon_session(session_id=session.session_id)
    controller.abandon_session(session_id=session.session_id)
    restarted = other.start_session()
    try:
        assert restarted.session_id != session.session_id
        assert backend.commands == [] and other_backend.commands == []
        assert source.current_calls == 0
        assert not controller._intent_claim_store.list_unresolved_claims()
        assert not list((tmp_path / "first").rglob("*receipt*.json"))
        assert controller.submit_intent(_intent(session)).reason_code == "unknown_session"
    finally:
        other.abandon_session(session_id=restarted.session_id)


def test_abandon_rejects_foreign_session_without_releasing_its_lease(tmp_path):
    owner, _, _, _, backend = _controller(tmp_path / "owner", target_window_handle=91802)
    foreign, _, _, _, _ = _controller(tmp_path / "foreign", target_window_handle=91802)
    session = owner.start_session()
    try:
        with pytest.raises(ValueError, match="owned|unknown"):
            foreign.abandon_session(session_id=session.session_id)
        with pytest.raises(RuntimeError, match="lease|session|window"):
            foreign.start_session()
        assert backend.commands == []
    finally:
        owner.abandon_session(session_id=session.session_id)


@pytest.mark.parametrize("failure", ["claim", "consumed", "confirmation", "storage"])
def test_abandon_refuses_unverified_or_claimed_session_and_keeps_owner(tmp_path, monkeypatch, failure):
    controller, _, _, _, backend = _controller(tmp_path / "owner", target_window_handle=91803)
    other, _, _, _, _ = _controller(tmp_path / "other", target_window_handle=91803)
    session = controller.start_session()
    state = controller._sessions[session.session_id]
    store = controller._intent_claim_store
    original = store.find_for_observation
    if failure == "claim":
        def found(**kwargs):
            return object()
        monkeypatch.setattr(store, "find_for_observation", found)
    elif failure == "storage":
        def unavailable(**kwargs):
            raise RuntimeIntentClaimStoreError("synthetic unreadable claim")
        monkeypatch.setattr(store, "find_for_observation", unavailable)
    elif failure == "confirmation":
        state.confirmation = object()
    else:
        state.consumed = True
    try:
        with pytest.raises((ValueError, RuntimeIntentClaimStoreError)):
            controller.abandon_session(session_id=session.session_id)
        assert session.session_id in controller._sessions
        with pytest.raises(RuntimeError, match="lease|session|window"):
            other.start_session()
        assert backend.commands == []
    finally:
        monkeypatch.setattr(store, "find_for_observation", original)
        state.consumed = False
        state.confirmation = None
        controller.abandon_session(session_id=session.session_id)


def test_abandon_cannot_erase_real_pending_confirmation(tmp_path):
    from tests.test_live_controller_w3b_persistence import (
        _asset, _controller as confirmation_controller, _intent as confirmation_intent,
    )
    asset = _asset()
    transition = next(item for item in asset["transitions"] if item["transition_id"] == "open_detail")
    transition["risk_policy"]["requires_user_confirmation"] = True
    transition["risk_policy"]["automatic_execution_allowed"] = False
    controller, store, _, _, _, backend = confirmation_controller(tmp_path, asset=asset)
    session = controller.start_session()
    result = controller.submit_intent(confirmation_intent(session))
    assert result.status == "CONFIRMATION_REQUIRED"
    pending = store.get_for_confirmation(confirmation_id=result.confirmation_id)
    with pytest.raises(ValueError, match="owned"):
        controller.abandon_session(session_id=session.session_id)
    assert store.get_for_confirmation(confirmation_id=result.confirmation_id) == pending
    assert backend.attempt_count == 0


def test_abandon_serializes_with_submit_without_dispatch(tmp_path, monkeypatch):
    controller, _, _, _, backend = _controller(tmp_path, target_window_handle=91804)
    session = controller.start_session()
    entered, release = threading.Event(), threading.Event()
    original = controller._intent_claim_store.find_for_observation
    outcomes, errors = [], []

    def held_lookup(**kwargs):
        if threading.current_thread().name == "owned-abandon":
            entered.set()
            assert release.wait(3)
        return original(**kwargs)

    def abandon():
        try:
            controller.abandon_session(session_id=session.session_id)
        except BaseException as error:
            errors.append(error)

    def submit():
        try:
            outcomes.append(controller.submit_intent(_intent(session)))
        except BaseException as error:
            errors.append(error)

    monkeypatch.setattr(controller._intent_claim_store, "find_for_observation", held_lookup)
    first = threading.Thread(target=abandon, name="owned-abandon")
    second = threading.Thread(target=submit, name="owned-submit")
    first.start()
    try:
        assert entered.wait(3)
        second.start()
    finally:
        release.set()
        first.join(3)
        if second.ident is not None:
            second.join(3)
    assert not first.is_alive() and not second.is_alive() and errors == []
    assert len(outcomes) == 1 and outcomes[0].reason_code == "unknown_session"
    assert backend.commands == []
    assert not controller._intent_claim_store.list_unresolved_claims()
