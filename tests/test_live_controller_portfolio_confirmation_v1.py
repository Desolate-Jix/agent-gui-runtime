from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path


def _compiled_portfolio_asset(tmp_path: Path) -> dict:
    from app.agent.reviewed_workflow_compiler import compile_reviewed_workflow_asset_v2
    from tests.test_portfolio_v1_reviewed_asset import _save_integrity_reviewed_source

    source, source_sha256 = _save_integrity_reviewed_source(tmp_path)
    compiled = compile_reviewed_workflow_asset_v2(
        project_root=tmp_path,
        source_workflow_path=source.relative_to(tmp_path),
        expected_source_workflow_sha256=source_sha256,
    )
    assert compiled["status"] == "compiled"
    return compiled["asset"]


def _current(asset: dict, source_node_id: str, capture_id: str) -> dict:
    from app.agent.reviewed_workflow_asset import content_sha256

    state = next(item for item in asset["states"] if item["source_node_id"] == source_node_id)
    return {
        "contract_version": "reviewed_workflow_current_observation_v1",
        "asset_id": asset["asset_id"],
        "expected_asset_content_sha256": content_sha256(asset),
        "capture_id": capture_id,
        "screenshot_sha256": hashlib.sha256(capture_id.encode("utf-8")).hexdigest(),
        "viewport_size": {"width": 1440, "height": 900},
        "origin": asset["application"]["canonical_origin"],
        "observed_anchor_evidence": [
            {
                "anchor_id": anchor_id,
                "matched": True,
                "confidence": 0.99,
                "evidence_ref": f"evidence:{capture_id}:{anchor_id}",
            }
            for anchor_id in [item["anchor_id"] for item in state["identity_anchors"]]
        ],
    }


class _AssetLoader:
    def __init__(self, asset: dict) -> None:
        self.asset = asset

    def load_active(self, asset_id: str) -> dict:
        return deepcopy(self.asset)


class _PortfolioSource:
    def __init__(self, *, asset: dict, project_root: Path) -> None:
        self.asset = asset
        self.project_root = project_root
        self.initial = _current(asset, "job_detail", "capture-initial-detail")
        self.detail = _current(asset, "job_detail", "capture-detail")
        self.apply_entry = _current(asset, "apply_entry", "capture-apply-entry")
        self.projected_calls = 0

    def _agent_observation(self, session_id: str, workflow: dict, current: dict):
        from app.agent.reviewed_workflow_replay import resolve_current_state
        from app.agent.runtime_contracts import validate_agent_observation_v1

        resolution = resolve_current_state(self.asset, current)
        state = next(
            item for item in self.asset["states"] if item["state_id"] == resolution["state_id"]
        )
        resolution_ref = f"state-resolution:{current['capture_id']}"
        capture_ref = f"capture:{current['capture_id']}"
        safe_stop = state["availability"] == "stop_boundary"
        actions = []
        if not safe_stop:
            for transition in self.asset["transitions"]:
                if transition["transition_id"] not in state["allowed_transition_ids"]:
                    continue
                actions.append(
                    {
                        "action_id": transition["transition_id"],
                        "semantic_action": transition["semantic_action"],
                        "description": "Open the reviewed application entry.",
                        "target_state_id": transition["target_state_id"],
                        "expected_effect": "Reach the reviewed Apply Entry stop boundary.",
                        "verification_rule_refs": [
                            f"workflow-rule:{rule['rule_id']}"
                            for rule in transition["post_action_verification"]["semantic_success_rules"]
                        ],
                        "risk_level": transition["risk_policy"]["risk_level"],
                        "requires_user_confirmation": True,
                    }
                )
        actions.append(
            {
                "action_id": "runtime.safe_stop",
                "semantic_action": "safe_stop",
                "description": "Stop without dispatch.",
                "target_state_id": None,
                "expected_effect": "Stop without dispatch.",
                "verification_rule_refs": [],
                "risk_level": "low",
                "requires_user_confirmation": False,
            }
        )
        return validate_agent_observation_v1(
            {
                "contract_version": "agent_observation_v1",
                "observation_id": (
                "observation-initial"
                if current["capture_id"] == "capture-initial-detail"
                else (
                    "observation-detail-current"
                    if current["capture_id"] == "capture-detail"
                    else "observation-apply-entry"
                )
                ),
                "session_id": session_id,
                "workflow": workflow,
                "application": {
                    "identity_ref": "application:web:nz.seek.com",
                    "kind": "web",
                    "display_name": "nz.seek.com",
                },
                "state_resolution_ref": resolution_ref,
                "current_capture": {
                    "capture_id": current["capture_id"],
                    "screenshot_sha256": current["screenshot_sha256"],
                    "evidence_ref": capture_ref,
                },
                "state": {
                    "status": "stop_boundary" if safe_stop else "matched",
                    "state_id": state["state_id"],
                    "state_availability": state["availability"],
                    "resolution_sha256": resolution["resolution_sha256"],
                    "source_interface_id": state["source_node_id"],
                    "display_name": state["display_name"],
                    "surface_type": state["state_type"],
                    "responsibility": "Portfolio v1 reviewed state.",
                },
                "semantic_facts": [],
                "evidence_refs": [resolution_ref, capture_ref],
                "blockers": (
                    [
                        {
                            "blocker_id": "blocker.stop-boundary",
                            "blocker_type": "policy",
                            "description": "Apply Entry is the Portfolio v1 stop boundary.",
                            "safe_stop_required": True,
                            "evidence_refs": [resolution_ref],
                        }
                    ]
                    if safe_stop
                    else []
                ),
                "available_actions": actions,
                "safe_stop": {
                    "required": safe_stop,
                    "reason_code": "stop_boundary" if safe_stop else "none",
                },
                "artifact_is_authorization": False,
            }
        )

    def create_initial(self, *, session_id, workflow, asset, target_window_handle):
        return self._agent_observation(session_id, workflow, self.initial)

    def capture_current(self, *, session_id, asset, target_window_handle):
        return deepcopy(self.detail)

    def capture_projected(self, *, session_id, workflow, asset, target_window_handle):
        from app.agent.live_controller import ProjectedObservationCapture
        from app.agent.reviewed_workflow_asset import content_sha256
        from app.agent.runtime_contracts import WorkflowRefV1

        self.projected_calls += 1
        current = self.detail if self.projected_calls == 1 else self.apply_entry
        return ProjectedObservationCapture(
            session_id=session_id,
            workflow=WorkflowRefV1.model_validate(workflow),
            application_identity_key="web:nz.seek.com",
            asset_id=asset["asset_id"],
            asset_content_sha256=content_sha256(asset),
            target_window_handle=6242,
            target_process_id=9001,
            current_observation=deepcopy(current),
            agent_observation=self._agent_observation(session_id, workflow, current),
        )


def _controller(tmp_path: Path, asset: dict, source: _PortfolioSource):
    from app.agent.desktop_backend import DeterministicFakeBackend
    from app.agent.live_controller import LiveController, ServerWorkflowBinding
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from app.agent.runtime_receipt_store import RuntimeReceiptStore
    from tests.test_live_controller_w4 import (
        _Gate,
        _TargetResolver,
        _WindowVisibilityChecker,
    )

    store = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
    )
    backend = DeterministicFakeBackend()
    controller = LiveController(
        binding=ServerWorkflowBinding(
            workflow_id="portfolio_v1_reviewed_two_state",
            asset_id=asset["asset_id"],
            application_identity_key="web:nz.seek.com",
            target_window_handle=6242,
        ),
        asset_loader=_AssetLoader(asset),
        observation_source=source,
        target_resolver=_TargetResolver(),
        gate=_Gate(),
        window_visibility_checker=_WindowVisibilityChecker(bound_window_handle=6242),
        backend=backend,
        intent_claim_store=store,
        grounding_policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2},
    )
    return controller, store, backend


def test_portfolio_confirmation_resumes_once_and_stops_at_apply_entry(
    tmp_path: Path,
) -> None:
    asset = _compiled_portfolio_asset(tmp_path)
    first_source = _PortfolioSource(asset=asset, project_root=tmp_path)
    first, _, first_backend = _controller(tmp_path, asset, first_source)
    session = first.start_session()
    action = next(
        item
        for item in session.current_observation.available_actions
        if item.semantic_action == "open_apply_flow"
    )
    payload = {
        "contract_version": "agent_intent_v1",
        "intent_id": "intent.portfolio-open-apply",
        "session_id": session.session_id,
        "observation_id": session.current_observation.observation_id,
        "workflow": session.workflow.model_dump(mode="json"),
        "action_id": action.action_id,
    }
    pending = first.submit_intent(payload)
    assert (pending.status, pending.reason_code) == (
        "CONFIRMATION_REQUIRED",
        "human_confirmation_required",
    )
    first.record_confirmation_decision(
        confirmation_id=pending.confirmation_id,
        decision="approved",
    )

    restarted_source = _PortfolioSource(asset=asset, project_root=tmp_path)
    restarted, store, backend = _controller(tmp_path, asset, restarted_source)
    result = restarted.submit_intent(payload)
    duplicate = restarted.submit_intent(payload)

    assert result.outcome == "SAFE_STOP"
    assert result.reason_code == "stop_boundary"
    assert result.action.semantic_action == "open_apply_flow"
    assert result.attempt_count == 1
    assert duplicate == result
    assert first_backend.attempt_count == 0
    assert backend.dispatch_count == 1
    assert restarted_source.projected_calls == 2
    claim = store.get_for_observation(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
    )
    assert claim.phase == "terminal"
    assert claim.confirmation is not None
    assert claim.confirmation.evidence_ref in result.evidence.trace_refs
    assert all(
        forbidden not in json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
        for forbidden in ("fill_field", "continue_next_step", "final_submit")
    )
