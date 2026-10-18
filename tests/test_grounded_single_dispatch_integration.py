from copy import deepcopy
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.agent.runtime_contracts import RuntimeResultReceiptV1
from app.api.agent_runtime import AgentRuntimeCallsiteError
from tests.test_agent_runtime_api_v1 import _client
from tests.test_agent_runtime_grounded_preview import _request, live
from tests.test_live_controller_w4 import _current_observation


@pytest.fixture
def approved(live):
    observation = live.service.start_session()
    source = live.sources[0]
    source.post_current_sequence = [
        _current_observation(source.asset, capture_id="capture-consume-fresh", anchors=("anchor_detail", "quick_apply")),
        _current_observation(source.asset, capture_id="capture-consume-post", anchors=("anchor_apply_entry",)),
    ]
    request = _request(observation)
    pending = live.service.request_grounded_confirmation(request)
    confirmation_id = pending.grounded_confirmation.confirmation_id
    decision = live.service.decide_grounded_confirmation(confirmation_id=confirmation_id, decision="approved")
    try:
        yield SimpleNamespace(live=live, observation=observation, request=request, decision=decision, confirmation_id=confirmation_id)
    finally:
        claim = live.claims.get_for_grounded_confirmation(confirmation_id=confirmation_id)
        if claim.phase in {"grounded_confirmation_pending", "grounded_confirmation_approved", "grounded_confirmation_denied", "grounded_confirmation_closed"}:
            live.service.cancel_grounded_review(session_id=observation.session_id)


def test_actual_grounded_approval_fresh_capture_single_dispatch_and_receipt(approved, monkeypatch):
    live = approved.live
    gate = live.controllers[0]._gate
    gate_calls = []
    review_evaluate, execution_evaluate = gate.evaluate_review, gate.evaluate

    def counted_review(**kwargs):
        gate_calls.append("review")
        return review_evaluate(**kwargs)

    def counted_execution(**kwargs):
        gate_calls.append("execution")
        return execution_evaluate(**kwargs)

    monkeypatch.setattr(gate, "evaluate_review", counted_review)
    monkeypatch.setattr(gate, "evaluate", counted_execution)
    initial_resolver_calls = live.controllers[0]._target_resolver.calls
    result = live.service.consume_grounded_confirmation(confirmation_id=approved.confirmation_id)
    assert isinstance(result, RuntimeResultReceiptV1)
    assert result.outcome == "SAFE_STOP"
    assert result.reason_code == "stop_boundary"
    assert result.attempt_count == 1
    assert sum(backend.attempt_count for backend in live.backends) == 1
    assert sum(source.projected_calls for source in live.sources) == 3
    assert live.controllers[0]._target_resolver.calls == initial_resolver_calls + 1
    assert gate_calls == ["review", "execution"]
    assert any(ref.startswith("grounded-consume:") for ref in result.evidence.trace_refs)
    claim = live.claims.get_for_grounded_confirmation(confirmation_id=approved.confirmation_id)
    assert claim.phase == "terminal"
    assert claim.grounded_consume is not None
    repeated = live.service.consume_grounded_confirmation(confirmation_id=approved.confirmation_id)
    assert repeated == result
    assert sum(backend.attempt_count for backend in live.backends) == 1
    assert sum(source.projected_calls for source in live.sources) == 3
    assert gate_calls == ["review", "execution"]


@pytest.mark.parametrize("drift", ["capture_reuse", "screenshot", "viewport"])
def test_changed_approved_visual_facts_never_dispatch(approved, drift):
    live = approved.live
    source = live.sources[0]
    fresh = deepcopy(source.post_current_sequence[0])
    if drift == "capture_reuse":
        fresh["capture_id"] = source.current["capture_id"]
    elif drift == "screenshot":
        fresh["screenshot_sha256"] = "a" * 64
    else:
        fresh["viewport_size"] = {"width": 1441, "height": 900}
    source.post_current_sequence[0] = fresh
    result = live.service.consume_grounded_confirmation(confirmation_id=approved.confirmation_id)
    assert not isinstance(result, RuntimeResultReceiptV1) or result.attempt_count == 0
    assert sum(backend.attempt_count for backend in live.backends) == 0
    assert not list(live.claims.dispatch_started_root.iterdir())
    claim = live.claims.get_for_grounded_confirmation(confirmation_id=approved.confirmation_id)
    assert claim.phase == "grounded_confirmation_closed"
    assert claim.grounded_confirmation.closed_reason_code == "grounded_confirmation_stale"


def test_legacy_http_does_not_receive_a_grounded_consume_capability(approved):
    live = approved.live
    with _client(live.service) as client:
        response = client.post("/runtime/agent/grounded/consume", json={"confirmation_id": approved.confirmation_id})
        replay = client.post("/runtime/agent/intent/submit", json=approved.request.model_dump(mode="json"))
    assert response.status_code == 404
    assert replay.json()["data"]["status"] == "RECOVERY_REQUIRED"
    assert sum(source.projected_calls for source in live.sources) == 1
    assert all(backend.attempt_count == 0 for backend in live.backends)


def test_full_frame_drift_at_visibility_check_invalidates_grounded_approval(approved, monkeypatch):
    live = approved.live
    checker = live.controllers[0]._window_visibility_checker
    check = checker.check

    def frame_changed(**kwargs):
        result = dict(check(**kwargs))
        result["freshness"] = {
            "status": "allowed", "reason": "target_region_unchanged", "full_frame_status": "changed",
        }
        return result

    monkeypatch.setattr(checker, "check", frame_changed)
    live.service.consume_grounded_confirmation(confirmation_id=approved.confirmation_id)
    assert sum(backend.attempt_count for backend in live.backends) == 0
    assert not list(live.claims.dispatch_started_root.iterdir())
    claim = live.claims.get_for_grounded_confirmation(confirmation_id=approved.confirmation_id)
    assert claim.phase == "grounded_confirmation_closed"
    assert claim.grounded_confirmation.closed_reason_code == "grounded_confirmation_stale"


def test_expired_approval_is_rejected_before_any_fresh_capture(approved, monkeypatch):
    live = approved.live
    expires = datetime.fromisoformat(approved.decision.grounded_confirmation.expires_at.replace("Z", "+00:00"))
    monkeypatch.setattr(live.claims, "_clock", lambda: expires + timedelta(seconds=1))
    captures_before = sum(source.projected_calls for source in live.sources)
    result = live.service.consume_grounded_confirmation(confirmation_id=approved.confirmation_id)
    assert not isinstance(result, RuntimeResultReceiptV1)
    assert sum(source.projected_calls for source in live.sources) == captures_before
    assert all(backend.attempt_count == 0 for backend in live.backends)
    assert not list(live.claims.grounded_consume_root.iterdir())


def test_same_consume_retry_finishes_exact_terminal_cleanup_without_recapture(approved, monkeypatch):
    live = approved.live
    controller = live.controllers[0]
    release = controller._release_window_lease
    released_leases = []

    def fail_once(lease):
        released_leases.append(lease)
        if len(released_leases) == 1:
            raise RuntimeError("synthetic exact terminal release failure")
        return release(lease)

    monkeypatch.setattr(controller, "_release_window_lease", fail_once)
    try:
        first = live.service.consume_grounded_confirmation(confirmation_id=approved.confirmation_id)
        assert first.reason_code == "grounded_confirmation_cleanup_required"
        assert approved.observation.session_id in controller._sessions
        captures_before = sum(source.projected_calls for source in live.sources)
        second = live.service.consume_grounded_confirmation(confirmation_id=approved.confirmation_id)
        assert isinstance(second, RuntimeResultReceiptV1)
        assert len(released_leases) == 2
        assert released_leases[0] is released_leases[1]
        assert approved.observation.session_id not in controller._sessions
        assert sum(source.projected_calls for source in live.sources) == captures_before
        assert sum(backend.attempt_count for backend in live.backends) == 1
    finally:
        if approved.observation.session_id in controller._sessions:
            controller.consume_grounded_confirmation(confirmation_id=approved.confirmation_id)
