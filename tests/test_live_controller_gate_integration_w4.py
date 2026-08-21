from __future__ import annotations

from app.agent.desktop_backend import DeterministicFakeBackend
from app.agent.live_controller import LiveController, ServerWorkflowBinding
from app.agent.reviewed_workflow_gate import ReviewedWorkflowGateAdapter
from tests.test_live_controller_w4 import (
    _ObservationSource,
    _TargetResolver,
    _TrustedAssetLoader,
    _WindowVisibilityChecker,
    _intent,
)
from tests.test_reviewed_workflow_asset_v2 import _asset
from tests.test_reviewed_workflow_gate_w4 import _recognition_inputs


class _ResolverWithCurrentGateEvidence(_TargetResolver):
    def __init__(self, *, policy_allowed: bool = True) -> None:
        super().__init__()
        self._policy_allowed = policy_allowed

    def resolve(self, *, selection: dict, current_observation: dict) -> dict:
        result = super().resolve(
            selection=selection,
            current_observation=current_observation,
        )
        candidates, local_grounding = _recognition_inputs(
            policy_allowed=self._policy_allowed,
        )
        result["gate_context"] = {
            "candidates": candidates,
            "local_grounding": local_grounding,
        }
        return result


def test_live_controller_uses_existing_pre_click_policy_before_dispatch(tmp_path) -> None:
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    asset = _asset()
    backend = DeterministicFakeBackend()
    controller = LiveController(
        binding=ServerWorkflowBinding(
            workflow_id="workflow.seek.portfolio",
            asset_id=asset["asset_id"],
            application_identity_key="web:nz.seek.com",
            target_window_handle=4545,
        ),
        asset_loader=_TrustedAssetLoader(asset),
        observation_source=_ObservationSource(asset),
        target_resolver=_ResolverWithCurrentGateEvidence(),
        gate=ReviewedWorkflowGateAdapter(),
        window_visibility_checker=_WindowVisibilityChecker(
            bound_window_handle=4545,
        ),
        backend=backend,
        intent_claim_store=RuntimeIntentClaimStore(
            project_root=tmp_path,
            receipt_store=RuntimeReceiptStore(project_root=tmp_path),
        ),
        grounding_policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2},
    )
    session = controller.start_session()

    receipt = controller.submit_intent(_intent(session))

    assert receipt.outcome == "DISPATCHED"
    assert receipt.reason_code == "verification_pending"
    assert backend.dispatch_count == 1


def test_existing_pre_click_policy_block_produces_zero_dispatch(tmp_path) -> None:
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    asset = _asset()
    backend = DeterministicFakeBackend()
    controller = LiveController(
        binding=ServerWorkflowBinding(
            workflow_id="workflow.seek.portfolio",
            asset_id=asset["asset_id"],
            application_identity_key="web:nz.seek.com",
            target_window_handle=4747,
        ),
        asset_loader=_TrustedAssetLoader(asset),
        observation_source=_ObservationSource(asset),
        target_resolver=_ResolverWithCurrentGateEvidence(policy_allowed=False),
        gate=ReviewedWorkflowGateAdapter(),
        window_visibility_checker=_WindowVisibilityChecker(
            bound_window_handle=4747,
        ),
        backend=backend,
        intent_claim_store=RuntimeIntentClaimStore(
            project_root=tmp_path,
            receipt_store=RuntimeReceiptStore(project_root=tmp_path),
        ),
        grounding_policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2},
    )
    session = controller.start_session()

    receipt = controller.submit_intent(_intent(session))

    assert receipt.outcome == "BLOCKED"
    assert receipt.reason_code == "pre_click_rejected"
    assert backend.attempt_count == 0


def test_missing_server_gate_context_fails_closed_for_reviewed_gate(tmp_path) -> None:
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    asset = _asset()
    backend = DeterministicFakeBackend()
    controller = LiveController(
        binding=ServerWorkflowBinding(
            workflow_id="workflow.seek.portfolio",
            asset_id=asset["asset_id"],
            application_identity_key="web:nz.seek.com",
            target_window_handle=4646,
        ),
        asset_loader=_TrustedAssetLoader(asset),
        observation_source=_ObservationSource(asset),
        target_resolver=_TargetResolver(),
        gate=ReviewedWorkflowGateAdapter(),
        window_visibility_checker=_WindowVisibilityChecker(
            bound_window_handle=4646,
        ),
        backend=backend,
        intent_claim_store=RuntimeIntentClaimStore(
            project_root=tmp_path,
            receipt_store=RuntimeReceiptStore(project_root=tmp_path),
        ),
        grounding_policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2},
    )
    session = controller.start_session()

    receipt = controller.submit_intent(_intent(session))

    assert receipt.outcome == "BLOCKED"
    assert receipt.reason_code == "pre_click_rejected"
    assert backend.attempt_count == 0
