from types import SimpleNamespace

import pytest

from app.agent.runtime_intent_claim_store import RuntimeIntentClaimSnapshot, RuntimeIntentClaimStoreError
from app.agent.runtime_session_selection import RuntimeSessionSelection
from app.api.agent_runtime import AgentRuntimeCallsiteError, LocalAgentRuntimeCallsite
from tests.test_agent_runtime_api_v1 import _client
from tests.test_agent_runtime_grounded_preview import live, _request


@pytest.fixture
def published(live):
    observation = live.service.start_session()
    request = _request(observation)
    claim = live.service.request_grounded_confirmation(request)
    assert isinstance(claim, RuntimeIntentClaimSnapshot)
    try:
        yield SimpleNamespace(live=live, observation=observation, request=request, claim=claim)
    finally:
        # 仅通过实际公开取消接缝回收本测试会话，不手工修改 session/lease。
        live.service.cancel_grounded_review(session_id=observation.session_id)


def test_actual_publication_returns_same_owner_store_snapshot(published):
    live, claim = published.live, published.claim
    grounded = claim.grounded_confirmation
    assert claim.phase == "grounded_confirmation_pending"
    assert grounded.owner_is_current is True
    assert grounded.preview.to_dict()["observation_id"] == published.observation.observation_id
    assert live.claims.get_for_grounded_confirmation(confirmation_id=grounded.confirmation_id) == claim
    assert sum(source.projected_calls for source in live.sources) == 1
    assert len(list(live.claims.claims_root.iterdir())) == 1
    assert len(list(live.claims.grounded_requests_root.iterdir())) == 1
    assert not list(live.claims.dispatch_started_root.iterdir())
    assert not list(live.claims.terminal_root.iterdir())
    assert all(backend.attempt_count == 0 for backend in live.backends)


def test_same_publication_retry_neither_recaptures_nor_renews_request(published):
    live = published.live
    initial = next(live.claims.grounded_requests_root.iterdir()).read_bytes()
    again = live.service.request_grounded_confirmation(published.request)
    assert again == published.claim
    assert next(live.claims.grounded_requests_root.iterdir()).read_bytes() == initial
    assert sum(source.projected_calls for source in live.sources) == 1
    assert all(backend.attempt_count == 0 for backend in live.backends)


@pytest.mark.parametrize("decision", ["approved", "denied"])
def test_public_grounded_decision_is_not_execution_and_denial_releases_window(published, decision):
    live = published.live
    claim = live.service.decide_grounded_confirmation(
        confirmation_id=published.claim.grounded_confirmation.confirmation_id, decision=decision,
    )
    assert claim.phase == f"grounded_confirmation_{decision}"
    assert claim.grounded_confirmation.grants_action_authority is False
    assert claim.grounded_confirmation.artifact_is_authorization is False
    assert sum(source.projected_calls for source in live.sources) == 1
    assert all(backend.attempt_count == 0 for backend in live.backends)
    if decision == "denied":
        new_observation = live.service.start_session()
        assert new_observation.session_id != published.observation.session_id
    else:
        with pytest.raises(AgentRuntimeCallsiteError):
            live.service.start_session()
        assert len(live.controllers) == 1


def test_public_grounded_cancel_closes_then_allows_same_window_prepare(published):
    live = published.live
    closed = live.service.cancel_grounded_review(session_id=published.observation.session_id)
    assert closed.phase == "grounded_confirmation_closed"
    assert closed.grounded_confirmation.closed_reason_code == "grounded_confirmation_cancelled"
    assert live.claims.list_unresolved_claims() == ()
    new_observation = live.service.start_session()
    assert new_observation.session_id != published.observation.session_id
    assert all(backend.attempt_count == 0 for backend in live.backends)


def test_legacy_http_cannot_consume_active_publication_or_release_its_lease(published):
    live = published.live
    confirmation_id = published.claim.grounded_confirmation.confirmation_id
    with _client(live.service) as client:
        approval = client.post("/runtime/agent/confirmation/decide", json={
            "confirmation_id": confirmation_id, "decision": "approved",
        })
        submission = client.post("/runtime/agent/intent/submit", json=published.request.model_dump(mode="json"))
    assert approval.status_code in {409, 412}
    assert submission.status_code == 200
    assert submission.json()["data"]["status"] == "RECOVERY_REQUIRED"
    assert live.claims.get_for_grounded_confirmation(confirmation_id=confirmation_id) == published.claim
    assert sum(source.projected_calls for source in live.sources) == 1
    assert all(backend.attempt_count == 0 for backend in live.backends)
    with pytest.raises(AgentRuntimeCallsiteError):
        live.service.start_session()
    assert len(live.controllers) == 1


def test_same_store_new_callsite_cannot_restore_missing_controller_owner(published, tmp_path):
    live, claim = published.live, published.claim

    def forbidden_factory(_binding):
        raise AssertionError("Recovery must not construct a controller")

    other = LocalAgentRuntimeCallsite(
        project_root=tmp_path, asset_store=live.assets, window_manager=live.windows,
        claim_store=live.claims, controller_factory=forbidden_factory,
        selection=RuntimeSessionSelection(claim.observation.workflow.asset_id,
                                          claim.observation.workflow.asset_content_sha256, 88401, 9301),
    )
    with pytest.raises(AgentRuntimeCallsiteError) as error:
        other.decide_grounded_confirmation(
            confirmation_id=claim.grounded_confirmation.confirmation_id, decision="approved",
        )
    assert "owner" in error.value.code
    assert live.claims.get_for_grounded_confirmation(
        confirmation_id=claim.grounded_confirmation.confirmation_id,
    ) == claim
    assert sum(source.projected_calls for source in live.sources) == 1
    assert all(backend.attempt_count == 0 for backend in live.backends)


def test_post_publish_failure_uses_same_context_and_snapshot_on_explicit_retry(live, monkeypatch):
    observation = live.service.start_session()
    request = _request(observation)
    publish_request = live.service.request_grounded_confirmation
    original = live.claims._publish_bytes

    def fail_after_publish(path, contents):
        result = original(path, contents)
        if path.parent == live.claims.grounded_requests_root:
            raise RuntimeIntentClaimStoreError("injected grounded publication uncertainty")
        return result

    try:
        with monkeypatch.context() as patch:
            patch.setattr(live.claims, "_publish_bytes", fail_after_publish)
            uncertain = publish_request(request)
        assert uncertain.status == "RECOVERY_REQUIRED"
        persisted = next(live.claims.grounded_requests_root.iterdir()).read_bytes()
        recovered = publish_request(request)
        assert recovered.phase == "grounded_confirmation_pending"
        assert next(live.claims.grounded_requests_root.iterdir()).read_bytes() == persisted
        assert sum(source.projected_calls for source in live.sources) == 1
        assert all(backend.attempt_count == 0 for backend in live.backends)
    finally:
        live.service.cancel_grounded_review(session_id=observation.session_id)


def test_same_request_retry_after_window_drift_closes_original_publication(live):
    observation = live.service.start_session()
    request = _request(observation)
    claim = live.service.request_grounded_confirmation(request)
    controller = live.controllers[0]
    try:
        live.windows.bound.process_id = 9302
        with pytest.raises(AgentRuntimeCallsiteError):
            live.service.request_grounded_confirmation(request)
        stored = live.claims.get_for_grounded_confirmation(
            confirmation_id=claim.grounded_confirmation.confirmation_id,
        )
        assert stored.phase == "grounded_confirmation_closed"
        assert stored.grounded_confirmation.closed_reason_code == "grounded_confirmation_stale"
        assert sum(source.projected_calls for source in live.sources) == 1
        assert all(backend.attempt_count == 0 for backend in live.backends)
        live.windows.bound.process_id = 9301
        assert live.service.start_session().session_id != observation.session_id
    finally:
        live.windows.bound.process_id = 9301
        # 故障断言也通过原 controller 的公开取消回收，绝不手工解锁。
        controller.cancel_grounded_review(session_id=observation.session_id)


def test_default_factory_actual_publication_and_approval_share_store_owner(live, tmp_path, monkeypatch):
    from app.agent.desktop_backend import DeterministicFakeBackend
    from app.agent import live_runtime_composition as composition
    from tests.test_live_controller_w4 import _WindowVisibilityChecker

    prepared = live.service.start_session()
    source = live.sources[0]
    resolver = live.controllers[0]._target_resolver
    live.service.cancel_prepared_session(session_id=prepared.session_id)
    backend = DeterministicFakeBackend()
    evidence = SimpleNamespace(
        create_initial=source.create_initial,
        capture_projected=source.capture_projected,
        resolve=resolver.resolve,
    )
    # 仅替换被动证据、可见性与输入端；默认 factory、builder、controller 和 Gate 均为真实实现。
    monkeypatch.setattr(composition, "ExistingWindowsCurrentEvidenceAdapter", lambda **_kwargs: evidence)
    monkeypatch.setattr(composition, "ExistingWindowsCurrentEvidenceVisibilityChecker",
                        lambda **_kwargs: _WindowVisibilityChecker(bound_window_handle=88401))
    monkeypatch.setattr(composition, "ExistingWindowManagerVisibilityChecker",
                        lambda: _WindowVisibilityChecker(bound_window_handle=88401))
    monkeypatch.setattr(composition, "ExistingWindowsBackendAdapter", lambda: backend)
    service = LocalAgentRuntimeCallsite(
        project_root=tmp_path, asset_store=live.assets, window_manager=live.windows,
        claim_store=live.claims,
        selection=RuntimeSessionSelection(prepared.workflow.asset_id,
                                          prepared.workflow.asset_content_sha256, 88401, 9301),
    )
    observation = service.start_session()
    try:
        pending = service.request_grounded_confirmation(_request(observation))
        assert pending.grounded_confirmation.owner_is_current is True
        approved = service.decide_grounded_confirmation(
            confirmation_id=pending.grounded_confirmation.confirmation_id, decision="approved",
        )
        assert approved.phase == "grounded_confirmation_approved"
        assert live.claims.get_for_grounded_confirmation(
            confirmation_id=pending.grounded_confirmation.confirmation_id,
        ) == approved
        assert source.projected_calls == 1
        assert backend.attempt_count == 0
    finally:
        service.cancel_grounded_review(session_id=observation.session_id)


@pytest.mark.parametrize("reopened_store", [False, True])
def test_legacy_http_history_replay_never_restores_grounded_controller(published, tmp_path, reopened_store):
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    live = published.live
    calls = []

    def forbidden_factory(_binding):
        calls.append("constructed")
        raise AssertionError("Historical grounded replay must not construct a controller")

    claims = RuntimeIntentClaimStore(project_root=tmp_path, receipt_store=RuntimeReceiptStore(project_root=tmp_path)) if reopened_store else live.claims
    other = LocalAgentRuntimeCallsite(
        project_root=tmp_path, asset_store=live.assets, window_manager=live.windows,
        claim_store=claims, controller_factory=forbidden_factory,
        selection=RuntimeSessionSelection(published.observation.workflow.asset_id,
                                          published.observation.workflow.asset_content_sha256, 88401, 9301),
    )
    raw_request = next(live.claims.grounded_requests_root.iterdir()).read_bytes()
    with _client(other) as client:
        response = client.post("/runtime/agent/intent/submit", json=published.request.model_dump(mode="json"))
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "RECOVERY_REQUIRED"
    assert calls == []
    assert next(live.claims.grounded_requests_root.iterdir()).read_bytes() == raw_request
    assert live.claims.get_for_grounded_confirmation(
        confirmation_id=published.claim.grounded_confirmation.confirmation_id,
    ) == published.claim
    assert sum(source.projected_calls for source in live.sources) == 1
    assert all(backend.attempt_count == 0 for backend in live.backends)
