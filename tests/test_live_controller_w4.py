from __future__ import annotations

from copy import deepcopy

import pytest

from app.agent.reviewed_workflow_asset import content_sha256
from app.agent.runtime_contracts import validate_agent_observation_v1
from tests.test_reviewed_workflow_asset_v2 import _asset


def _workflow_ref(asset: dict, workflow_id: str = "workflow.seek.portfolio") -> dict:
    return {
        "workflow_id": workflow_id,
        "asset_id": asset["asset_id"],
        "asset_content_sha256": content_sha256(asset),
        "source_workflow_sha256": asset["source_review_lineage"]["source_workflow_sha256"],
        "reviewed_revision_hash": asset["source_review_lineage"]["reviewed_revision_hash"],
    }


def _agent_observation(session_id: str, workflow: dict) -> dict:
    return {
        "contract_version": "agent_observation_v1",
        "observation_id": "observation-initial",
        "session_id": session_id,
        "workflow": workflow,
        "application": {
            "identity_ref": "application:web:nz.seek.com",
            "kind": "web",
            "display_name": "nz.seek.com",
        },
        "state_resolution_ref": "state-resolution:initial",
        "current_capture": {
            "capture_id": "capture-initial",
            "screenshot_sha256": "d" * 64,
            "evidence_ref": "capture:initial",
        },
        "state": {
            "status": "matched",
            "state_id": "homepage",
            "state_availability": "reviewed",
            "resolution_sha256": "e" * 64,
            "source_interface_id": "interface.homepage",
            "display_name": "Homepage",
            "surface_type": "web_page",
            "responsibility": "Open a reviewed job detail.",
        },
        "semantic_facts": [],
        "evidence_refs": ["state-resolution:initial", "capture:initial"],
        "blockers": [],
        "available_actions": [
            {
                "action_id": "open_detail",
                "semantic_action": "open_detail",
                "description": "Open the reviewed job detail.",
                "target_state_id": "detail",
                "expected_effect": "Reach the reviewed detail state.",
                "verification_rule_refs": ["workflow-rule:detail-visible"],
                "risk_level": "low",
                "requires_user_confirmation": False,
            },
            {
                "action_id": "runtime.safe_stop",
                "semantic_action": "safe_stop",
                "description": "Stop without dispatch.",
                "target_state_id": None,
                "expected_effect": "Stop without dispatch.",
                "verification_rule_refs": [],
                "risk_level": "low",
                "requires_user_confirmation": False,
            },
        ],
        "safe_stop": {"required": False, "reason_code": "none"},
        "artifact_is_authorization": False,
    }


def _current_observation(asset: dict, *, capture_id: str = "capture-current", anchors: tuple[str, ...] = ("anchor_homepage", "job_card")) -> dict:
    return {
        "contract_version": "reviewed_workflow_current_observation_v1",
        "asset_id": asset["asset_id"],
        "expected_asset_content_sha256": content_sha256(asset),
        "capture_id": capture_id,
        "screenshot_sha256": "f" * 64,
        "viewport_size": {"width": 1440, "height": 900},
        "origin": "https://nz.seek.com",
        "observed_anchor_evidence": [
            {
                "anchor_id": anchor,
                "matched": True,
                "confidence": 0.95,
                "evidence_ref": f"evidence:{capture_id}:{anchor}",
            }
            for anchor in anchors
        ],
    }


class _ObservationSource:
    def __init__(self, asset: dict, *, current: dict | None = None) -> None:
        self.asset = asset
        self.current = current or _current_observation(asset)
        self.initial_calls = 0
        self.current_calls = 0
        self.initial_window_handles: list[int] = []
        self.current_window_handles: list[int] = []

    def create_initial(self, *, session_id: str, workflow: dict, target_window_handle: int) -> object:
        self.initial_calls += 1
        self.initial_window_handles.append(target_window_handle)
        return validate_agent_observation_v1(_agent_observation(session_id, workflow))

    def capture_current(self, *, session_id: str, asset: dict, target_window_handle: int) -> dict:
        self.current_calls += 1
        self.current_window_handles.append(target_window_handle)
        return deepcopy(self.current)


class _TrustedAssetLoader:
    def __init__(self, asset: dict) -> None:
        self.asset = asset
        self.calls: list[str] = []

    def load_active(self, asset_id: str) -> dict:
        self.calls.append(asset_id)
        return deepcopy(self.asset)


class _TargetResolver:
    def __init__(self, status: str = "resolved") -> None:
        self.status = status
        self.calls = 0

    def resolve(self, *, selection: dict, current_observation: dict) -> dict:
        self.calls += 1
        if self.status != "resolved":
            return {"status": self.status}
        lineage = selection["capture_lineage"]
        return {
            "status": "resolved",
            "grounding": {
                "contract_version": "reviewed_workflow_current_grounding_v1",
                "asset_content_sha256": selection["asset_content_sha256"],
                "transition_id": selection["transition_id"],
                "source_state_id": selection["source_state_id"],
                "capture_id": lineage["capture_id"],
                "screenshot_sha256": lineage["screenshot_sha256"],
                "viewport_size": lineage["viewport_size"],
                "element_ref": selection["element_ref"],
                "candidate_id": "candidate-current",
                "candidate_current": True,
                "eligible": True,
                "confidence": 0.95,
                "score_margin": 0.40,
                "bbox": {"x": 100, "y": 200, "w": 300, "h": 80},
                "click_point": {"x": 220, "y": 240},
                "evidence_refs": [f"grounding:{lineage['capture_id']}:job-card"],
            },
        }


class _Gate:
    def __init__(self, *, allowed: bool = True) -> None:
        self.allowed = allowed
        self.calls = 0

    def evaluate(self, *, selection: dict, grounding: dict) -> dict:
        self.calls += 1
        lineage = selection["capture_lineage"]
        return {
            "contract_version": "pre_click_decision_v1",
            "allowed": self.allowed,
            "asset_content_sha256": selection["asset_content_sha256"],
            "transition_id": selection["transition_id"],
            "selection_sha256": selection["selection_sha256"],
            "selected_candidate_id": grounding["candidate_id"],
            "selected_element_id": selection["element_ref"],
            "selected_click_point": grounding["click_point"],
            "capture_id": lineage["capture_id"],
            "screenshot_sha256": lineage["screenshot_sha256"],
            "viewport_size": lineage["viewport_size"],
            "evidence_refs": [f"gate:{lineage['capture_id']}"],
        }


class _WindowVisibilityChecker:
    def __init__(
        self,
        *,
        bound_window_handle: int = 4242,
        visible: bool = True,
    ) -> None:
        self.bound_window_handle = bound_window_handle
        self.visible = visible
        self.calls: list[tuple[int, tuple[float, float]]] = []

    def check(self, *, target_window_handle: int, click_point: tuple[float, float]) -> dict:
        self.calls.append((target_window_handle, click_point))
        if self.bound_window_handle != target_window_handle:
            return {
                "bound_window_handle": self.bound_window_handle,
                "point_visibility": None,
            }
        return {
            "bound_window_handle": self.bound_window_handle,
            "point_visibility": {"allowed": self.visible},
        }


def _controller(
    tmp_path,
    *,
    resolver_status: str = "resolved",
    gate_allowed: bool = True,
    backend_fail: bool = False,
    current: dict | None = None,
    backend_override=None,
    target_window_handle: int = 4242,
    visibility_checker=None,
):
    from app.agent.desktop_backend import DeterministicFakeBackend
    from app.agent.live_controller import LiveController, ServerWorkflowBinding
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    asset = _asset()
    asset_loader = _TrustedAssetLoader(asset)
    source = _ObservationSource(asset, current=current)
    resolver = _TargetResolver(resolver_status)
    gate = _Gate(allowed=gate_allowed)
    backend = backend_override or DeterministicFakeBackend(fail=backend_fail)
    visibility = visibility_checker or _WindowVisibilityChecker(
        bound_window_handle=target_window_handle,
    )
    controller = LiveController(
        binding=ServerWorkflowBinding(
            workflow_id="workflow.seek.portfolio",
            asset_id=asset["asset_id"],
            application_identity_key="web:nz.seek.com",
            target_window_handle=target_window_handle,
        ),
        asset_loader=asset_loader,
        observation_source=source,
        target_resolver=resolver,
        gate=gate,
        window_visibility_checker=visibility,
        backend=backend,
        intent_claim_store=RuntimeIntentClaimStore(
            project_root=tmp_path,
            receipt_store=RuntimeReceiptStore(project_root=tmp_path),
        ),
        grounding_policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2},
    )
    return controller, source, resolver, gate, backend


def _intent(session) -> dict:
    return {
        "contract_version": "agent_intent_v1",
        "intent_id": "intent.open-detail",
        "session_id": session.session_id,
        "observation_id": session.current_observation.observation_id,
        "workflow": session.current_observation.workflow.model_dump(mode="json"),
        "action_id": "open_detail",
    }


def test_session_is_server_created_and_pins_workflow_revision(tmp_path) -> None:
    controller, source, _, _, _ = _controller(tmp_path)

    session = controller.start_session()

    assert session.session_id.startswith("session.")
    assert session.current_observation.session_id == session.session_id
    assert session.current_observation.workflow == session.workflow
    assert session.workflow.asset_content_sha256 == content_sha256(_asset())
    assert source.initial_calls == 1
    assert source.initial_window_handles == [4242]


def test_start_session_can_load_the_server_active_asset_store(tmp_path) -> None:
    from app.agent.desktop_backend import DeterministicFakeBackend
    from app.agent.live_controller import LiveController, ServerWorkflowBinding
    from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    asset = _asset()
    ReviewedWorkflowAssetStore(project_root=tmp_path).publish(
        asset,
        expected_registry_revision=0,
    )
    source = _ObservationSource(asset)
    controller = LiveController(
        binding=ServerWorkflowBinding(
            workflow_id="workflow.seek.portfolio",
            asset_id=asset["asset_id"],
            application_identity_key="web:nz.seek.com",
            target_window_handle=4343,
        ),
        project_root=tmp_path,
        observation_source=source,
        target_resolver=_TargetResolver(),
        gate=_Gate(),
        window_visibility_checker=_WindowVisibilityChecker(bound_window_handle=4343),
        backend=DeterministicFakeBackend(),
        intent_claim_store=RuntimeIntentClaimStore(
            project_root=tmp_path,
            receipt_store=RuntimeReceiptStore(project_root=tmp_path),
        ),
        grounding_policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2},
    )

    session = controller.start_session()

    assert session.workflow.asset_content_sha256 == content_sha256(asset)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(session_id="session.wrong"),
        lambda payload: payload.update(observation_id="observation.stale"),
        lambda payload: payload["workflow"].update(reviewed_revision_hash="0" * 64),
        lambda payload: payload.update(action_id="unknown.action"),
        lambda payload: payload.update(bbox=[1, 2, 3, 4]),
        lambda payload: payload.update(click_point={"x": 1, "y": 2}),
        lambda payload: payload.update(approved=True),
        lambda payload: payload.update(skip_gate=True),
        lambda payload: payload.update(dispatch_token="forged"),
        lambda payload: payload.update(authority={"dispatch": True}),
        lambda payload: payload.update(target_window_handle=9999),
    ],
)
def test_invalid_or_authority_injected_intent_has_zero_dispatch(mutation, tmp_path) -> None:
    controller, source, resolver, gate, backend = _controller(tmp_path)
    session = controller.start_session()
    payload = _intent(session)
    mutation(payload)

    result = controller.submit_intent(payload)

    assert result.status == "REJECTED"
    assert backend.attempt_count == 0
    assert source.current_calls == 0
    assert resolver.calls == 0
    assert gate.calls == 0


def test_accepted_intent_uses_fresh_current_evidence_before_gate_and_dispatch(tmp_path) -> None:
    from app.agent.runtime_contracts import (
        validate_agent_intent_v1,
        validate_runtime_result_receipt_v1,
    )

    controller, source, resolver, gate, backend = _controller(tmp_path)
    session = controller.start_session()
    payload = _intent(session)

    result = controller.submit_intent(payload)

    assert result.outcome == "DISPATCHED"
    assert result.reason_code == "verification_pending"
    assert result.effect_status == "not_evaluated"
    assert result.destination_status == "not_evaluated"
    assert result.evidence.verification_ref is None
    assert source.current_calls == resolver.calls == gate.calls == 1
    assert source.current_window_handles == [4242]
    assert backend.dispatch_count == 1
    assert backend.commands[0].capture_id == "capture-current"
    assert backend.commands[0].click_point == (220.0, 240.0)
    intent = validate_agent_intent_v1(payload, observation=session.current_observation)
    assert validate_runtime_result_receipt_v1(
        result.model_dump(mode="json"),
        observation=session.current_observation,
        intent=intent,
    ) == result


@pytest.mark.parametrize(
    "resolver_status,expected_status,expected_reason",
    [
        ("missing", "BLOCKED", "target_unresolved"),
        ("ambiguous", "BLOCKED", "grounding_ambiguous"),
        ("stale", "BLOCKED", "stale_candidate"),
        ("wrong_context", "BLOCKED", "capture_lineage_mismatch"),
    ],
)
def test_unresolved_current_target_never_reaches_gate_or_backend(resolver_status, expected_status, expected_reason, tmp_path) -> None:
    controller, _, _, gate, backend = _controller(tmp_path, resolver_status=resolver_status)
    session = controller.start_session()

    result = controller.submit_intent(_intent(session))

    assert (result.outcome, result.reason_code) == (expected_status, expected_reason)
    assert gate.calls == 0
    assert backend.attempt_count == 0


def test_unresolved_or_ambiguous_current_state_has_zero_dispatch(tmp_path) -> None:
    asset = _asset()
    current = _current_observation(asset, anchors=())
    controller, _, resolver, gate, backend = _controller(tmp_path, current=current)
    session = controller.start_session()

    result = controller.submit_intent(_intent(session))

    # 冻结 Receipt Contract 只允许 safe_stop intent 生成 non-dispatch SAFE_STOP；
    # 非 safe_stop intent 的 state drift 必须投影成 action-level target_unresolved。
    assert result.outcome == "BLOCKED"
    assert result.reason_code == "target_unresolved"
    assert resolver.calls == gate.calls == backend.attempt_count == 0


def test_gate_block_has_zero_dispatch(tmp_path) -> None:
    controller, _, _, gate, backend = _controller(tmp_path, gate_allowed=False)
    session = controller.start_session()

    result = controller.submit_intent(_intent(session))

    assert result.outcome == "BLOCKED"
    assert result.reason_code == "pre_click_rejected"
    assert gate.calls == 1
    assert backend.attempt_count == 0


def test_replay_of_consumed_intent_is_rejected_and_total_dispatch_remains_one(tmp_path) -> None:
    controller, _, _, _, backend = _controller(tmp_path)
    session = controller.start_session()
    payload = _intent(session)

    first = controller.submit_intent(payload)
    second = controller.submit_intent(payload)

    assert first.outcome == "DISPATCHED"
    assert second == first
    assert backend.dispatch_count == 1


def test_backend_failure_is_execution_failed_and_never_verified(tmp_path) -> None:
    controller, _, _, _, backend = _controller(tmp_path, backend_fail=True)
    session = controller.start_session()

    result = controller.submit_intent(_intent(session))

    assert result.outcome == "EXECUTION_FAILED"
    assert result.reason_code == "backend_failed"
    assert result.effect_status == "not_evaluated"
    assert backend.attempt_count == 1
    assert backend.dispatch_count == 0


def test_backend_indeterminate_result_never_becomes_execution_failed_or_verified(tmp_path) -> None:
    from app.agent.desktop_backend import BackendDispatchReceipt

    class IndeterminateBackend:
        def __init__(self) -> None:
            self.calls = 0

        def dispatch(self, command, *, authority):
            self.calls += 1
            return BackendDispatchReceipt(
                receipt_ref="backend-receipt:lost",
                status="indeterminate",
                reason_code="backend_result_lost",
            )

    backend = IndeterminateBackend()
    controller, _, _, _, _ = _controller(tmp_path, backend_override=backend)
    session = controller.start_session()

    result = controller.submit_intent(_intent(session))

    assert result.outcome == "INDETERMINATE"
    assert result.reason_code == "backend_result_lost"
    assert result.dispatch_status == "indeterminate"
    assert result.effect_status == "indeterminate"
    assert result.destination_status == "indeterminate"
    assert backend.calls == 1


def test_start_session_rejects_binding_identity_not_owned_by_reviewed_asset(tmp_path) -> None:
    from app.agent.desktop_backend import DeterministicFakeBackend
    from app.agent.live_controller import LiveController, ServerWorkflowBinding
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    asset = _asset()
    controller = LiveController(
        binding=ServerWorkflowBinding(
            workflow_id="workflow.seek.portfolio",
            asset_id=asset["asset_id"],
            application_identity_key="web:forged.example",
            target_window_handle=4444,
        ),
        asset_loader=_TrustedAssetLoader(asset),
        observation_source=_ObservationSource(asset),
        target_resolver=_TargetResolver(),
        gate=_Gate(),
        window_visibility_checker=_WindowVisibilityChecker(bound_window_handle=4444),
        backend=DeterministicFakeBackend(),
        intent_claim_store=RuntimeIntentClaimStore(
            project_root=tmp_path,
            receipt_store=RuntimeReceiptStore(project_root=tmp_path),
        ),
        grounding_policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2},
    )

    with pytest.raises(ValueError, match="application identity"):
        controller.start_session()


def test_start_session_rejects_observation_application_identity_mismatch(tmp_path) -> None:
    class ForgedObservationSource(_ObservationSource):
        def create_initial(self, *, session_id: str, workflow: dict, target_window_handle: int) -> object:
            payload = _agent_observation(session_id, workflow)
            payload["application"]["identity_ref"] = "application:web:forged.example"
            return validate_agent_observation_v1(payload)

    from app.agent.desktop_backend import DeterministicFakeBackend
    from app.agent.live_controller import LiveController, ServerWorkflowBinding
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    asset = _asset()
    controller = LiveController(
        binding=ServerWorkflowBinding(
            workflow_id="workflow.seek.portfolio",
            asset_id=asset["asset_id"],
            application_identity_key="web:nz.seek.com",
            target_window_handle=4545,
        ),
        asset_loader=_TrustedAssetLoader(asset),
        observation_source=ForgedObservationSource(asset),
        target_resolver=_TargetResolver(),
        gate=_Gate(),
        window_visibility_checker=_WindowVisibilityChecker(bound_window_handle=4545),
        backend=DeterministicFakeBackend(),
        intent_claim_store=RuntimeIntentClaimStore(
            project_root=tmp_path,
            receipt_store=RuntimeReceiptStore(project_root=tmp_path),
        ),
        grounding_policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2},
    )

    with pytest.raises(ValueError, match="application identity"):
        controller.start_session()


def test_second_mutating_session_for_same_window_is_rejected(tmp_path) -> None:
    controller, _, _, _, _ = _controller(tmp_path, target_window_handle=4646)
    first = controller.start_session()

    with pytest.raises(RuntimeError, match="window lease"):
        controller.start_session()

    assert first.current_observation.session_id == first.session_id


def test_window_lease_is_shared_across_live_controller_instances(tmp_path) -> None:
    first_controller, _, _, _, _ = _controller(tmp_path / "first", target_window_handle=4696)
    second_controller, _, _, _, _ = _controller(tmp_path / "second", target_window_handle=4696)
    first_controller.start_session()

    with pytest.raises(RuntimeError, match="window lease"):
        second_controller.start_session()


@pytest.mark.parametrize(
    "visibility,expected_reason",
    [
        (_WindowVisibilityChecker(bound_window_handle=9999), "foreground_window_changed"),
        (_WindowVisibilityChecker(bound_window_handle=4747, visible=False), "target_occluded"),
    ],
)
def test_runtime_visibility_block_after_gate_has_zero_dispatch(visibility, expected_reason, tmp_path) -> None:
    controller, _, _, gate, backend = _controller(
        tmp_path,
        target_window_handle=4747,
        visibility_checker=visibility,
    )
    session = controller.start_session()

    result = controller.submit_intent(_intent(session))

    assert result.outcome == "BLOCKED"
    assert result.reason_code == expected_reason
    assert gate.calls == 1
    assert backend.attempt_count == 0


def test_valid_dispatch_is_bound_to_server_target_window_exactly_once(tmp_path) -> None:
    controller, _, _, _, backend = _controller(tmp_path, target_window_handle=4848)
    session = controller.start_session()
    payload = _intent(session)

    first = controller.submit_intent(payload)
    second = controller.submit_intent(payload)

    assert first.outcome == "DISPATCHED"
    assert second == first
    assert backend.dispatch_count == 1
    assert backend.commands[0].target_window_handle == 4848


def test_window_manager_visibility_adapter_returns_facts_not_authority() -> None:
    from app.agent.live_controller import ExistingWindowManagerVisibilityChecker

    class Bound:
        handle = 4949

    class WindowManager:
        def __init__(self) -> None:
            self.calls: list[tuple[int, int, int]] = []

        def get_bound_window(self):
            return Bound()

        def validate_bound_point_visibility(self, *, bound, x: int, y: int) -> dict:
            self.calls.append((bound.handle, x, y))
            return {"allowed": True, "reason": "target_point_owned_by_bound_window"}

    manager = WindowManager()
    checker = ExistingWindowManagerVisibilityChecker(window_manager=manager)

    facts = checker.check(target_window_handle=4949, click_point=(220.0, 240.0))

    assert facts == {
        "bound_window_handle": 4949,
        "point_visibility": {
            "allowed": True,
            "reason": "target_point_owned_by_bound_window",
        },
    }
    assert manager.calls == [(4949, 220, 240)]
