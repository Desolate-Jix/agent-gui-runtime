from copy import deepcopy
from types import SimpleNamespace

import pytest

from app.agent.desktop_backend import DeterministicFakeBackend
from app.agent.live_controller import LiveController
from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore, content_sha256
from app.agent.reviewed_workflow_gate import ReviewedWorkflowGateAdapter
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore, RuntimeIntentClaimStoreError
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from app.agent.runtime_session_selection import RuntimeSessionSelection
from app.api.agent_runtime import AgentRuntimeCallsiteError, AgentRuntimeIntentRequest, LocalAgentRuntimeCallsite
from tests.test_live_controller_w4 import (
    _asset, _current_observation, _projected_agent_observation, _ObservationSource,
    _TargetResolver, _WindowVisibilityChecker,
)
from tests.test_reviewed_workflow_gate_w4 import _recognition_inputs


@pytest.fixture
def live(tmp_path):
    asset = _asset()
    transition = next(item for item in asset["transitions"] if item["transition_id"] == "open_apply_flow")
    transition["risk_policy"]["requires_user_confirmation"] = True
    transition["risk_policy"]["automatic_execution_allowed"] = False
    assets = ReviewedWorkflowAssetStore(project_root=tmp_path)
    assets.publish(asset, expected_registry_revision=0)
    claims = RuntimeIntentClaimStore(project_root=tmp_path, receipt_store=RuntimeReceiptStore(project_root=tmp_path))
    windows = SimpleNamespace(bound=SimpleNamespace(handle=88401, process_id=9301, is_active=True))
    windows.get_bound_window = lambda: windows.bound
    controllers, backends, sources = [], [], []

    class Source(_ObservationSource):
        def create_initial(self, **kwargs):
            current = _current_observation(asset, capture_id="capture-initial-detail", anchors=("anchor_detail", "quick_apply"))
            return _projected_agent_observation(asset, kwargs["session_id"], kwargs["workflow"], current)

    class Resolver(_TargetResolver):
        def resolve(self, **kwargs):
            result = super().resolve(**kwargs)
            candidates, local = _recognition_inputs()
            element_ref = kwargs["selection"]["element_ref"]
            for candidate in candidates.candidates:
                candidate.element_id = element_ref
                candidate.element.element_id = element_ref
            for item in local.results:
                item.element_id = element_ref
            result["gate_context"] = {"candidates": candidates, "local_grounding": local}
            return result

    def build(binding):
        source = Source(asset, current=_current_observation(asset, capture_id="capture-review-detail", anchors=("anchor_detail", "quick_apply")), target_process_id=9301)
        backend = DeterministicFakeBackend()
        controller = LiveController(
            binding=binding, asset_loader=assets, observation_source=source,
            target_resolver=Resolver(), gate=ReviewedWorkflowGateAdapter(),
            window_visibility_checker=_WindowVisibilityChecker(bound_window_handle=88401),
            backend=backend, intent_claim_store=claims,
            grounding_policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2},
        )
        controllers.append(controller)
        backends.append(backend)
        sources.append(source)
        return controller

    service = LocalAgentRuntimeCallsite(
        project_root=tmp_path, asset_store=assets, claim_store=claims, window_manager=windows,
        controller_factory=build, selection=RuntimeSessionSelection(asset["asset_id"], content_sha256(asset), 88401, 9301),
    )
    context = SimpleNamespace(service=service, assets=assets, claims=claims, windows=windows, controllers=controllers, backends=backends, sources=sources)
    try:
        yield context
    finally:
        for controller in controllers:
            for session_id in list(controller._sessions):
                controller.abandon_session(session_id=session_id)


def _request(observation):
    action = next(item for item in observation.available_actions if item.semantic_action == "open_apply_flow")
    return AgentRuntimeIntentRequest(intent_id="intent.local-preview", session_id=observation.session_id,
        observation_id=observation.observation_id, action_id=action.action_id)


def test_cancel_prepared_session_is_exact_idempotent_and_releases_real_lease(live):
    observation = live.service.start_session()
    live.service.cancel_prepared_session(session_id=observation.session_id)
    live.service.cancel_prepared_session(session_id=observation.session_id)
    restarted = live.service.start_session()
    assert restarted.session_id != observation.session_id
    assert len(live.controllers) == 2
    assert all(backend.attempt_count == 0 for backend in live.backends)
    assert live.claims.list_unresolved_claims() == ()


def test_cancel_foreign_identity_does_not_discard_owned_session(live):
    observation = live.service.start_session()
    with pytest.raises(AgentRuntimeCallsiteError) as raised:
        live.service.cancel_prepared_session(session_id="session.foreign")
    assert raised.value.status_code == 409
    assert observation.session_id in live.controllers[0]._sessions
    live.service.cancel_prepared_session(session_id=observation.session_id)


def test_cancel_storage_failure_retains_exact_owner_for_start_retry(live, monkeypatch):
    observation = live.service.start_session()
    lookup = live.claims.find_for_observation
    calls = []

    def unavailable(**kwargs):
        calls.append(kwargs["session_id"])
        raise RuntimeIntentClaimStoreError("synthetic lookup failure")

    with monkeypatch.context() as patch:
        patch.setattr(live.claims, "find_for_observation", unavailable)
        for _ in range(2):
            with pytest.raises(AgentRuntimeCallsiteError) as raised:
                live.service.cancel_prepared_session(session_id=observation.session_id)
            assert raised.value.status_code == 503
        assert len(live.controllers) == 1
        assert observation.session_id in live.controllers[0]._sessions
        with pytest.raises(AgentRuntimeCallsiteError) as raised:
            live.service.start_session()
        assert raised.value.code == "agent_runtime_cleanup_required"
        assert len(live.controllers) == 1
    assert lookup(session_id=observation.session_id, observation_id=observation.observation_id) is None
    restarted = live.service.start_session()
    assert restarted.session_id != observation.session_id
    live.service.cancel_prepared_session(session_id=observation.session_id)
    assert restarted.session_id in live.controllers[-1]._sessions
    assert calls == [observation.session_id] * 3


def test_cancel_cannot_erase_durable_pending_confirmation(live):
    observation = live.service.start_session()
    pending = live.service.submit_intent(_request(observation))
    assert pending.status == "NEEDS_REVIEW"
    before = live.claims.get_for_confirmation(confirmation_id=pending.confirmation_id)
    with pytest.raises(AgentRuntimeCallsiteError) as raised:
        live.service.cancel_prepared_session(session_id=observation.session_id)
    assert raised.value.code == "agent_runtime_session_consumed"
    assert live.claims.get_for_confirmation(confirmation_id=pending.confirmation_id) == before
    assert live.backends[0].attempt_count == 0
    assert live.service._pending_cleanup is None


def test_local_callsite_returns_grounded_preview_without_executing(live):
    observation = live.service.start_session()
    preview = live.service.prepare_grounded_review(_request(observation)).to_dict()
    assert preview["session_id"] == observation.session_id
    assert preview["target_window_handle"] == 88401 and preview["target_process_id"] == 9301
    assert preview["artifact_is_authorization"] is False
    assert preview["grants_action_authority"] is False
    assert live.backends[0].attempt_count == 0
    assert live.claims.list_unresolved_claims() == ()
    live.service.cancel_prepared_session(session_id=observation.session_id)
    assert live.service.start_session().session_id != observation.session_id


@pytest.mark.parametrize("field", ["session_id", "observation_id", "action_id"])
def test_preview_rejects_foreign_intent_before_capture(live, field):
    observation = live.service.start_session()
    request = _request(observation).model_copy(update={field: "foreign.identity"})
    with pytest.raises(AgentRuntimeCallsiteError) as raised:
        live.service.prepare_grounded_review(request)
    assert raised.value.code == "agent_runtime_invalid_intent"
    assert live.sources[0].projected_calls == 0
    assert live.backends[0].attempt_count == 0


def test_preview_requires_explicit_local_selection(live):
    observation = live.service.start_session()
    live.service._selection = None
    with pytest.raises(AgentRuntimeCallsiteError) as raised:
        live.service.prepare_grounded_review(_request(observation))
    assert raised.value.code == "agent_runtime_selection_required"
    assert live.sources[0].projected_calls == 0


def test_preview_post_capture_window_drift_releases_exact_owner(live, monkeypatch):
    observation = live.service.start_session()
    capture = live.sources[0].capture_projected

    def drift(**kwargs):
        projected = capture(**kwargs)
        live.windows.bound.process_id = 9302
        return projected

    monkeypatch.setattr(live.sources[0], "capture_projected", drift)
    with pytest.raises(AgentRuntimeCallsiteError) as raised:
        live.service.prepare_grounded_review(_request(observation))
    assert raised.value.code == "agent_runtime_selection_binding_mismatch"
    assert observation.session_id not in live.controllers[0]._sessions
    assert live.backends[0].attempt_count == 0
    live.windows.bound.process_id = 9301
    assert live.service.start_session().session_id != observation.session_id


def test_preview_drift_cleanup_failure_blocks_new_prepare_until_exact_retry(live, monkeypatch):
    observation = live.service.start_session()
    capture = live.sources[0].capture_projected
    lookup = live.claims.find_for_observation

    def drift(**kwargs):
        projected = capture(**kwargs)
        live.windows.bound.process_id = 9302
        return projected

    def unavailable_after_drift(**kwargs):
        if live.windows.bound.process_id == 9302:
            raise RuntimeIntentClaimStoreError("synthetic post-preview lookup error")
        return lookup(**kwargs)

    monkeypatch.setattr(live.sources[0], "capture_projected", drift)
    monkeypatch.setattr(live.claims, "find_for_observation", unavailable_after_drift)
    with pytest.raises(AgentRuntimeCallsiteError) as raised:
        live.service.prepare_grounded_review(_request(observation))
    assert raised.value.code == "agent_runtime_cleanup_required"
    with pytest.raises(AgentRuntimeCallsiteError) as retry:
        live.service.start_session()
    assert retry.value.code == "agent_runtime_cleanup_required"
    assert len(live.controllers) == 1
    assert observation.session_id in live.controllers[0]._sessions
    live.windows.bound.process_id = 9301
    assert live.service.start_session().session_id != observation.session_id
    assert len(live.controllers) == 2
    assert all(backend.attempt_count == 0 for backend in live.backends)


def test_preview_asset_replacement_before_capture_invalidates_session(live):
    observation = live.service.start_session()
    asset = live.assets.load_active(observation.workflow.asset_id)
    asset["source_review_lineage"]["current_revision_hash"] = "8" * 64
    asset["source_review_lineage"]["reviewed_revision_hash"] = "8" * 64
    live.assets.publish(asset, expected_registry_revision=1)
    with pytest.raises(AgentRuntimeCallsiteError) as raised:
        live.service.prepare_grounded_review(_request(observation))
    assert raised.value.code == "agent_runtime_selected_asset_mismatch"
    assert live.sources[0].projected_calls == 0
    assert observation.session_id not in live.controllers[0]._sessions
    assert live.backends[0].attempt_count == 0


def test_preview_does_not_add_http_preview_cancel_or_approval_routes():
    from app.api.agent_runtime import router
    paths = [route.path for route in router.routes]
    assert not any("preview" in path or "cancel" in path or "grounded" in path for path in paths)
