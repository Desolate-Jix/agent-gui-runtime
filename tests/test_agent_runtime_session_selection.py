from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agent.reviewed_workflow_asset import content_sha256
from app.agent.runtime_session_selection import RuntimeSessionSelection
from app.api.agent_runtime import (
    AgentRuntimeCallsiteError,
    AgentRuntimeConfirmationDecisionRequest,
    AgentRuntimeIntentRequest,
    LocalAgentRuntimeCallsite,
)
from tests.test_agent_runtime_api_v1 import (
    _Assets,
    _Claims,
    _Controller,
    _WindowManager,
    _client,
    _factory,
    _reviewed_asset,
    _workflow,
)


def _selection(assets: _Assets, asset_id: str = "portfolio.seek1") -> RuntimeSessionSelection:
    return RuntimeSessionSelection(
        asset_id=asset_id,
        asset_content_sha256=content_sha256(assets.assets[asset_id]),
        target_window_handle=77,
        target_process_id=1234,
    )


def test_exact_selection_prepares_one_of_two_active_assets(tmp_path: Path) -> None:
    from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore

    assets = {
        asset_id: _reviewed_asset(asset_id)
        for asset_id in ("portfolio.seek0", "portfolio.seek1")
    }
    asset_store = ReviewedWorkflowAssetStore(project_root=tmp_path)
    asset_store.publish(assets["portfolio.seek0"], expected_registry_revision=0)
    asset_store.publish(assets["portfolio.seek1"], expected_registry_revision=1)
    claims = _Claims()
    controllers = []
    bindings = []

    def build(binding):
        bindings.append(binding)
        controller = _Controller(
            claims,
            binding=binding,
            requires_confirmation=False,
            workflow=_workflow(
                asset_id=binding.asset_id,
                asset=assets[binding.asset_id],
            ),
        )
        controllers.append(controller)
        return controller

    service = LocalAgentRuntimeCallsite(
        project_root=tmp_path,
        asset_store=asset_store,
        window_manager=_WindowManager(),
        claim_store=claims,
        controller_factory=build,
        selection=RuntimeSessionSelection(
            asset_id="portfolio.seek1",
            asset_content_sha256=content_sha256(assets["portfolio.seek1"]),
            target_window_handle=77,
            target_process_id=1234,
        ),
    )

    observation = service.start_session()

    assert observation.workflow.asset_id == "portfolio.seek1"
    assert [binding.asset_id for binding in bindings] == ["portfolio.seek1"]
    assert len(controllers) == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("asset_id", ""),
        ("asset_id", " selected.asset"),
        ("asset_id", "a" * 257),
        ("asset_content_sha256", "A" * 64),
        ("asset_content_sha256", "a" * 63),
        ("target_window_handle", True),
        ("target_window_handle", 0),
        ("target_process_id", True),
        ("target_process_id", -1),
    ],
)
def test_selection_rejects_invalid_fields(field: str, value: object) -> None:
    values = {
        "asset_id": "selected.asset",
        "asset_content_sha256": "a" * 64,
        "target_window_handle": 77,
        "target_process_id": 1234,
    }
    values[field] = value

    with pytest.raises(ValueError, match="runtime session"):
        RuntimeSessionSelection(**values)


def test_callsite_rejects_non_selection_before_dependency_access(tmp_path: Path) -> None:
    class Dependency:
        calls = 0

        def __getattr__(self, _name):
            self.calls += 1
            raise AssertionError("dependency must not be accessed")

    dependency = Dependency()
    with pytest.raises(TypeError, match="RuntimeSessionSelection"):
        LocalAgentRuntimeCallsite(
            project_root=tmp_path,
            asset_store=dependency,
            window_manager=dependency,
            claim_store=dependency,
            controller_factory=dependency,
            selection={"asset_id": "forged"},
        )
    assert dependency.calls == 0


@pytest.mark.parametrize(
    ("selection_factory", "window_factory", "code"),
    [
        (
            lambda assets: RuntimeSessionSelection(
                asset_id="portfolio.missing",
                asset_content_sha256="a" * 64,
                target_window_handle=77,
                target_process_id=1234,
            ),
            _WindowManager,
            "agent_runtime_selected_asset_inactive",
        ),
        (
            lambda assets: RuntimeSessionSelection(
                asset_id="portfolio.seek1",
                asset_content_sha256="a" * 64,
                target_window_handle=77,
                target_process_id=1234,
            ),
            _WindowManager,
            "agent_runtime_selected_asset_mismatch",
        ),
        (
            _selection,
            lambda: _WindowManager(active=False),
            "agent_runtime_bound_window_inactive",
        ),
        (
            _selection,
            lambda: SimpleNamespace(
                get_bound_window=lambda: SimpleNamespace(
                    handle=78, process_id=1234, is_active=True
                )
            ),
            "agent_runtime_selection_binding_mismatch",
        ),
        (
            _selection,
            lambda: _WindowManager(pid=4321),
            "agent_runtime_selection_binding_mismatch",
        ),
    ],
)
def test_invalid_selected_asset_or_window_builds_no_controller(
    selection_factory,
    window_factory,
    code: str,
    tmp_path: Path,
) -> None:
    assets = _Assets(count=2)
    claims, controllers, _, build = _factory(assets=assets)
    service = LocalAgentRuntimeCallsite(
        project_root=tmp_path,
        asset_store=assets,
        window_manager=window_factory(),
        claim_store=claims,
        controller_factory=build,
        selection=selection_factory(assets),
    )

    with pytest.raises(AgentRuntimeCallsiteError) as raised:
        service.start_session()

    assert raised.value.code == code
    assert controllers == []


def test_unselected_asset_change_does_not_block_selected_asset(tmp_path: Path) -> None:
    assets = _Assets(count=2)
    assets.active["portfolio.seek0"] = "f" * 64
    claims = _Claims()
    controllers = []

    def build(binding):
        controller = _Controller(
            claims,
            binding=binding,
            requires_confirmation=False,
            workflow=_workflow(
                asset_id=binding.asset_id,
                asset=assets.assets[binding.asset_id],
            ),
        )
        controllers.append(controller)
        return controller

    service = LocalAgentRuntimeCallsite(
        project_root=tmp_path,
        asset_store=assets,
        window_manager=_WindowManager(),
        claim_store=claims,
        controller_factory=build,
        selection=_selection(assets),
    )

    assert service.start_session().workflow.asset_id == "portfolio.seek1"
    assert len(controllers) == 1


def test_loaded_selected_asset_must_match_registry_bytes(tmp_path: Path) -> None:
    assets = _Assets(count=2)
    selection = _selection(assets)
    assets.assets[selection.asset_id]["source_review_lineage"][
        "current_revision_hash"
    ] = "9" * 64
    assets.assets[selection.asset_id]["source_review_lineage"][
        "reviewed_revision_hash"
    ] = "9" * 64
    claims, controllers, _, build = _factory(assets=assets)
    service = LocalAgentRuntimeCallsite(
        project_root=tmp_path,
        asset_store=assets,
        window_manager=_WindowManager(),
        claim_store=claims,
        controller_factory=build,
        selection=selection,
    )

    with pytest.raises(AgentRuntimeCallsiteError) as raised:
        service.start_session()

    assert raised.value.code == "agent_runtime_recovery_required"
    assert controllers == []


def test_selected_asset_replacement_during_prepare_is_abandoned(tmp_path: Path) -> None:
    assets = _Assets(count=2)
    selection = _selection(assets)
    claims = _Claims()
    controllers = []

    class AbandonableController(_Controller):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.abandon_calls = []

        def abandon_session(self, *, session_id: str) -> None:
            self.abandon_calls.append(session_id)

    def build(binding):
        controller = AbandonableController(
            claims,
            binding=binding,
            requires_confirmation=False,
            workflow=_workflow(
                asset_id=binding.asset_id,
                asset=assets.assets[binding.asset_id],
            ),
        )
        controllers.append(controller)
        replacement = deepcopy(assets.assets[binding.asset_id])
        replacement["source_review_lineage"]["current_revision_hash"] = "8" * 64
        replacement["source_review_lineage"]["reviewed_revision_hash"] = "8" * 64
        assets.assets[binding.asset_id] = replacement
        assets.active[binding.asset_id] = content_sha256(replacement)
        return controller

    service = LocalAgentRuntimeCallsite(
        project_root=tmp_path,
        asset_store=assets,
        window_manager=_WindowManager(),
        claim_store=claims,
        controller_factory=build,
        selection=selection,
    )

    with pytest.raises(AgentRuntimeCallsiteError) as raised:
        service.start_session()

    assert raised.value.code == "agent_runtime_selected_asset_mismatch"
    assert len(controllers) == 1
    assert controllers[0].submissions == []
    assert controllers[0].abandon_calls == ["session.initial"]


def test_http_start_body_cannot_override_selection(tmp_path: Path) -> None:
    assets = _Assets(count=2)
    claims, controllers, _, build = _factory(assets=assets)
    service = LocalAgentRuntimeCallsite(
        project_root=tmp_path,
        asset_store=assets,
        window_manager=_WindowManager(),
        claim_store=claims,
        controller_factory=build,
        selection=_selection(assets),
    )

    response = _client(service).post(
        "/runtime/agent/session/start",
        json={"asset_id": "portfolio.seek0"},
    )

    assert response.status_code == 422
    assert controllers == []


def test_confirmation_recovery_rechecks_selected_process_before_factory(
    tmp_path: Path,
) -> None:
    assets = _Assets(count=2)
    claims = _Claims()
    windows = _WindowManager()
    controllers = []

    def build(binding):
        controller = _Controller(
            claims,
            binding=binding,
            requires_confirmation=True,
            workflow=_workflow(
                asset_id=binding.asset_id,
                asset=assets.assets[binding.asset_id],
            ),
        )
        controllers.append(controller)
        return controller

    selection = _selection(assets)
    service = LocalAgentRuntimeCallsite(
        project_root=tmp_path,
        asset_store=assets,
        window_manager=windows,
        claim_store=claims,
        controller_factory=build,
        selection=selection,
    )
    observation = service.start_session()
    action = next(
        candidate
        for candidate in observation.available_actions
        if candidate.semantic_action == "open_apply_flow"
    )
    pending = service.submit_intent(
        AgentRuntimeIntentRequest(
            intent_id="intent.selected-recovery",
            session_id=observation.session_id,
            observation_id=observation.observation_id,
            action_id=action.action_id,
        )
    )
    assert pending.status == "NEEDS_REVIEW"
    assert controllers[0].attempts == 0

    windows.bound.process_id = 4321
    recovered_controllers = []
    recovered = LocalAgentRuntimeCallsite(
        project_root=tmp_path,
        asset_store=assets,
        window_manager=windows,
        claim_store=claims,
        controller_factory=lambda binding: recovered_controllers.append(binding),
        selection=selection,
    )

    with pytest.raises(AgentRuntimeCallsiteError) as raised:
        recovered.decide_confirmation(
            AgentRuntimeConfirmationDecisionRequest(
                confirmation_id=pending.confirmation_id,
                decision="approved",
            )
        )

    assert raised.value.code == "agent_runtime_selection_binding_mismatch"
    assert recovered_controllers == []
    assert controllers[0].attempts == 0


def test_failed_cleanup_is_retried_before_any_new_controller(tmp_path: Path) -> None:
    assets = _Assets(count=2)
    claims = _Claims()
    windows = _WindowManager()
    controllers = []

    class DriftingController(_Controller):
        allow_cleanup = False

        def __init__(self, *args, drift: bool, **kwargs):
            super().__init__(*args, **kwargs)
            self.drift = drift
            self.abandon_calls = []

        def start_session(self):
            session = super().start_session()
            if self.drift:
                windows.bound.process_id = 4321
            return session

        def abandon_session(self, *, session_id: str) -> None:
            self.abandon_calls.append(session_id)
            if not self.allow_cleanup:
                raise RuntimeError("cleanup blocked")

    def build(binding):
        controller = DriftingController(
            claims,
            binding=binding,
            requires_confirmation=False,
            workflow=_workflow(
                asset_id=binding.asset_id,
                asset=assets.assets[binding.asset_id],
            ),
            drift=not controllers,
        )
        controllers.append(controller)
        return controller

    service = LocalAgentRuntimeCallsite(
        project_root=tmp_path,
        asset_store=assets,
        window_manager=windows,
        claim_store=claims,
        controller_factory=build,
        selection=_selection(assets),
    )

    with pytest.raises(AgentRuntimeCallsiteError) as first:
        service.start_session()
    assert first.value.code == "agent_runtime_cleanup_required"
    assert len(controllers) == 1

    with pytest.raises(AgentRuntimeCallsiteError) as retry:
        service.start_session()
    assert retry.value.code == "agent_runtime_cleanup_required"
    assert len(controllers) == 1
    assert controllers[0].abandon_calls == ["session.initial", "session.initial"]

    controllers[0].allow_cleanup = True
    windows.bound.process_id = 1234
    assert service.start_session().workflow.asset_id == "portfolio.seek1"
    assert len(controllers) == 2
    assert controllers[0].abandon_calls == [
        "session.initial",
        "session.initial",
        "session.initial",
    ]


def test_real_controller_drift_cleanup_releases_window_lease(tmp_path: Path) -> None:
    from app.agent.desktop_backend import DeterministicFakeBackend
    from app.agent.live_controller import LiveController
    from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from app.agent.runtime_receipt_store import RuntimeReceiptStore
    from tests.test_live_controller_w4 import (
        _Gate,
        _ObservationSource,
        _TargetResolver,
        _WindowVisibilityChecker,
        _asset,
    )

    asset = _asset()
    asset_store = ReviewedWorkflowAssetStore(project_root=tmp_path)
    asset_store.publish(asset, expected_registry_revision=0)
    claim_store = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
    )
    windows = SimpleNamespace(
        bound=SimpleNamespace(handle=8624, process_id=9101, is_active=True)
    )
    windows.get_bound_window = lambda: windows.bound
    controllers = []
    backends = []

    class DriftingSource(_ObservationSource):
        def create_initial(self, **kwargs):
            observation = super().create_initial(**kwargs)
            windows.bound.process_id = 9102
            return observation

    def build(binding):
        source = DriftingSource(asset) if not controllers else _ObservationSource(asset)
        backend = DeterministicFakeBackend()
        controller = LiveController(
            binding=binding,
            asset_loader=asset_store,
            observation_source=source,
            target_resolver=_TargetResolver(),
            gate=_Gate(),
            window_visibility_checker=_WindowVisibilityChecker(
                bound_window_handle=8624
            ),
            backend=backend,
            intent_claim_store=claim_store,
            grounding_policy={
                "minimum_confidence": 0.9,
                "minimum_score_margin": 0.2,
            },
        )
        controllers.append(controller)
        backends.append(backend)
        return controller

    service = LocalAgentRuntimeCallsite(
        project_root=tmp_path,
        asset_store=asset_store,
        window_manager=windows,
        claim_store=claim_store,
        controller_factory=build,
        selection=RuntimeSessionSelection(
            asset_id=asset["asset_id"],
            asset_content_sha256=content_sha256(asset),
            target_window_handle=8624,
            target_process_id=9101,
        ),
    )

    with pytest.raises(AgentRuntimeCallsiteError) as drifted:
        service.start_session()
    assert drifted.value.code == "agent_runtime_selection_binding_mismatch"
    assert len(controllers) == 1
    assert backends[0].attempt_count == backends[0].dispatch_count == 0

    windows.bound.process_id = 9101
    observation = service.start_session()
    try:
        assert len(controllers) == 2
        assert backends[1].attempt_count == backends[1].dispatch_count == 0
        assert claim_store.list_unresolved_claims() == ()
    finally:
        controllers[1].abandon_session(session_id=observation.session_id)


def test_initial_safe_stop_cleanup_failure_retains_real_owner_until_retry(tmp_path, monkeypatch):
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStoreError
    from tests.test_live_controller_w4 import (
        _asset, _controller, _current_observation, _projected_agent_observation,
    )

    asset = _asset()
    digest = content_sha256(asset)
    controller, source, _, _, backend = _controller(tmp_path / "owner", target_window_handle=91805)
    other, _, _, _, other_backend = _controller(tmp_path / "other", target_window_handle=91805)
    claim_store = controller._intent_claim_store
    lookup = claim_store.find_for_observation
    factory_calls, lookup_calls, sessions = [], [], []

    def terminal_initial(**kwargs):
        sessions.append(kwargs["session_id"])
        current = _current_observation(asset, anchors=("anchor_apply_entry",))
        return _projected_agent_observation(asset, kwargs["session_id"], kwargs["workflow"], current)

    def unavailable(**kwargs):
        lookup_calls.append(kwargs["session_id"])
        raise RuntimeIntentClaimStoreError("synthetic unavailable claim store")

    def build(binding):
        factory_calls.append(binding)
        return controller

    monkeypatch.setattr(source, "create_initial", terminal_initial)
    monkeypatch.setattr(claim_store, "find_for_observation", unavailable)
    service = LocalAgentRuntimeCallsite(
        project_root=tmp_path,
        asset_store=SimpleNamespace(
            registry=lambda: {"active_by_asset": {asset["asset_id"]: digest}},
            load_active=lambda _asset_id: deepcopy(asset),
        ),
        window_manager=SimpleNamespace(get_bound_window=lambda: SimpleNamespace(
            handle=91805, process_id=9001, is_active=True,
        )),
        claim_store=claim_store,
        controller_factory=build,
        selection=RuntimeSessionSelection(asset["asset_id"], digest, 91805, 9001),
    )
    try:
        for _ in range(2):
            with pytest.raises(AgentRuntimeCallsiteError) as raised:
                service.start_session()
            assert raised.value.code == "agent_runtime_cleanup_required"
        assert len(factory_calls) == 1 and len(sessions) == 1
        assert lookup_calls == [sessions[0], sessions[0]]
        with pytest.raises(RuntimeError, match="lease|session|window"):
            other.start_session()
        monkeypatch.setattr(claim_store, "find_for_observation", lookup)
        assert service.start_session().safe_stop.required is True
        assert len(factory_calls) == 2 and len(sessions) == 2
        restarted = other.start_session()
        other.abandon_session(session_id=restarted.session_id)
        assert backend.commands == [] and other_backend.commands == []
        assert claim_store.list_unresolved_claims() == ()
    finally:
        monkeypatch.setattr(claim_store, "find_for_observation", lookup)
        for session_id in sessions:
            if session_id in controller._sessions:
                controller.abandon_session(session_id=session_id)
