"""新记录发布版本进入实际运行时，不导入旧学习资产。"""

from app.agent.agent_observation_adapter import adapt_reviewed_context_to_agent_observation_v1
from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore, content_sha256
from app.agent.reviewed_workflow_replay import resolve_current_state
from app.desktop_review.host import DesktopReviewHost
from types import SimpleNamespace
import pytest

from app.agent.desktop_backend import DeterministicFakeBackend
from app.agent.live_controller import LiveController, ProjectedObservationCapture
from app.agent.reviewed_workflow_gate import ReviewedWorkflowGateAdapter
from app.agent.runtime_contracts import WorkflowRefV1
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from app.agent.runtime_session_selection import RuntimeSessionSelection
from app.api.agent_runtime import AgentRuntimeIntentRequest, LocalAgentRuntimeCallsite
from tests.test_live_controller_w4 import _TargetResolver, _WindowVisibilityChecker
from tests.test_reviewed_workflow_gate_w4 import _recognition_inputs
from tests.test_formal_fresh_graph_source import REVIEWER
from tests.test_fresh_recorded_exact_review import (
    test_recorded_action_enters_review_without_inventing_effect_or_interface_identity as _publish_fresh,
)


def _current(asset, state_id, capture_id):
    state = next(item for item in asset["states"] if item["state_id"] == state_id)
    return {
        "contract_version": "reviewed_workflow_current_observation_v1",
        "asset_id": asset["asset_id"], "expected_asset_content_sha256": content_sha256(asset),
        "capture_id": capture_id, "screenshot_sha256": "e" * 64,
        "viewport_size": {"width": 1440, "height": 900}, "origin": "https://fresh.example",
        "observed_anchor_evidence": [
            {"anchor_id": anchor["anchor_id"], "matched": True, "confidence": 0.95,
             "evidence_ref": f"evidence:{capture_id}:{anchor['anchor_id']}"}
            for anchor in state["identity_anchors"]
        ],
    }


class _FreshVersionObservations:
    def __init__(self, root, asset):
        self.root = root
        self.asset = asset
        self.projected_calls = 0

    def _project(self, session_id, workflow, current):
        return adapt_reviewed_context_to_agent_observation_v1(
            observation_id=f"observation.{current['capture_id']}", session_id=session_id,
            workflow_id=workflow["workflow_id"], reviewed_asset=self.asset,
            current_observation=current, state_resolution=resolve_current_state(self.asset, current),
            project_root=self.root, application_identity_key="web:fresh.example")

    def create_initial(self, *, session_id, workflow, asset, target_window_handle):
        assert target_window_handle == 4242 and asset == self.asset
        current = _current(asset, asset["transitions"][0]["source_state_id"], "capture-reuse-initial")
        return self._project(session_id, workflow, current)

    def read_cached_grounded_image(self, **_kwargs):
        # 合成夹具仅向既有本地预览读取器提供最小 PNG，不代表真实截图证据。
        import base64
        return base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL4hAAAAABJRU5ErkJggg==")

    def capture_projected(self, *, session_id, workflow, asset, target_window_handle):
        assert target_window_handle == 4242 and asset == self.asset
        self.projected_calls += 1
        transition = asset["transitions"][0]
        state = transition["target_state_id" if self.projected_calls >= 3 else "source_state_id"]
        current = _current(asset, state, f"capture-reuse-{self.projected_calls}")
        return ProjectedObservationCapture(
            session_id=session_id, workflow=WorkflowRefV1.model_validate(workflow),
            application_identity_key="web:fresh.example", asset_id=asset["asset_id"],
            asset_content_sha256=content_sha256(asset), target_window_handle=4242,
            target_process_id=9001, current_observation=current,
            agent_observation=self._project(session_id, workflow, current))


class _FreshVersionResolver(_TargetResolver):
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


@pytest.mark.parametrize("existing_evidence_adapter,drift_before_confirmation", [
    (False, False), (True, False), (True, True),
])
def test_fresh_recorded_version_reuses_through_confirmed_canonical_http(
    tmp_path, existing_evidence_adapter, drift_before_confirmation,
):
    _publish_fresh(tmp_path)
    root = tmp_path / "review"
    assets = ReviewedWorkflowAssetStore(project_root=root)
    versions = assets.registry()["current_version_by_workflow"]
    assert len(versions) == 1
    workflow_id, version_id = next(iter(versions.items()))
    host = DesktopReviewHost(tmp_path / "inbox.json", root, REVIEWER, port=0)
    try:
        memory = host.facade.get_workflow_memory([workflow_id], workflow_id, version_id)
        published = assets.load_workflow_version(workflow_id, version_id)
        asset = published["asset"]
        assert content_sha256(asset) == memory["asset_sha256"]
        transition = asset["transitions"][0]
        current = _current(asset, transition["source_state_id"], "capture-reuse-initial")
        resolution = resolve_current_state(asset, current)
        assert resolution["status"] == "resolved", resolution
        projected = adapt_reviewed_context_to_agent_observation_v1(
            observation_id="observation.reuse.initial", session_id="session.reuse.initial",
            workflow_id=asset["source_review_lineage"]["source_workflow_id"],
            reviewed_asset=asset, current_observation=current, state_resolution=resolution,
            project_root=root, application_identity_key="web:fresh.example")
        assert projected.safe_stop.required is False, projected.model_dump(mode="json")
        assert any(action.action_id == transition["transition_id"]
                   for action in projected.available_actions)

        claims = RuntimeIntentClaimStore(project_root=root,
            receipt_store=RuntimeReceiptStore(project_root=root))
        backend = DeterministicFakeBackend()
        source = _FreshVersionObservations(root, asset)
        windows = SimpleNamespace(bound=SimpleNamespace(handle=4242, process_id=9001, is_active=True))
        windows.get_bound_window = lambda: windows.bound
        resolver = _FreshVersionResolver()
        if existing_evidence_adapter:
            from app.agent.live_runtime_composition import ExistingWindowsCurrentEvidenceAdapter
            from tests.test_live_runtime_composition_w3b import (
                _ScreenshotService, _SequencedScreenshotService, _OriginReader, _UIAProvider,
                _bound, _state_payloads, _empty_recognition, _recognition,
            )
            windows.bound = _bound()
            windows.bound.is_active = True
            screenshots = (_ScreenshotService(root) if drift_before_confirmation else
                _SequencedScreenshotService(root, colors=[(1, 20, 30)] * 3 + [(30, 20, 1)]))
            before_payloads = _state_payloads(asset, transition["source_state_id"])
            # 目标输入独立于编译产物：画面上只有真实按钮文字，没有动作名称。
            before_payloads.pop("open_detail", None)
            before_payloads["View details"] = _recognition("View details", role="button")
            after_payloads = _state_payloads(asset, transition["target_state_id"])
            recognition_goals = []

            def recognize(**kwargs):
                recognition_goals.append(kwargs["goal"])
                payloads = after_payloads if backend.attempt_count else before_payloads
                return payloads.get(kwargs["goal"], _empty_recognition(kwargs["goal"]))

            source = ExistingWindowsCurrentEvidenceAdapter(project_root=root,
                application_identity_key="web:fresh.example", window_manager=windows,
                screenshot_service=screenshots, origin_reader=_OriginReader(origin="https://fresh.example"),
                uia_provider=_UIAProvider(), recognition_runner=recognize)
            resolver = source
        controllers = []

        def build(binding):
            controller = LiveController(binding=binding, asset_loader=assets,
                observation_source=source, target_resolver=resolver,
                gate=ReviewedWorkflowGateAdapter(),
                window_visibility_checker=_WindowVisibilityChecker(bound_window_handle=4242),
                backend=backend, intent_claim_store=claims,
                grounding_policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2},
                verification_max_capture_attempts=1, verification_poll_interval_seconds=0.0)
            controllers.append(controller)
            return controller

        callsite = LocalAgentRuntimeCallsite(project_root=root, asset_store=assets,
            claim_store=claims, window_manager=windows, controller_factory=build,
            selection=RuntimeSessionSelection(memory["asset_id"], memory["asset_sha256"], 4242, 9001))
        observation = callsite.start_session()
        assert observation.workflow.asset_content_sha256 == memory["asset_sha256"]
        assert observation.state.state_id == transition["source_state_id"]
        pending = callsite.request_grounded_confirmation(AgentRuntimeIntentRequest(
            intent_id="intent.reuse.explicit-version", session_id=observation.session_id,
            observation_id=observation.observation_id, action_id=transition["transition_id"]))
        assert hasattr(pending, "grounded_confirmation"), pending
        confirmation_id = pending.grounded_confirmation.confirmation_id
        assert backend.attempt_count == 0
        approved = callsite.decide_grounded_confirmation(confirmation_id=confirmation_id, decision="approved")
        assert approved.phase == "grounded_confirmation_approved" and backend.attempt_count == 0
        host.start()
        host.attach_grounded_runtime(callsite, confirmation_id=confirmation_id)
        response = host.single_step.execute(confirmation_id=confirmation_id)
        if drift_before_confirmation:
            assert response["kind"] == "decision"
            assert response["payload"]["reason_code"] == "grounded_confirmation_stale"
            assert backend.attempt_count == 0
            host.release_grounded_runtime(confirmation_id=confirmation_id, timeout=30.0)
            assert all(not controller._sessions for controller in controllers)
            assert claims.list_unresolved_claims() == ()
            return
        assert response["kind"] == "receipt", response["payload"].get("reason_code", response["payload"])
        receipt = response["payload"]
        assert receipt["outcome"] == "VERIFIED", receipt
        assert receipt["workflow"]["asset_content_sha256"] == memory["asset_sha256"]
        assert receipt["attempt_count"] == 1 and backend.attempt_count == 1
        # 新定位必须进入派发，不能重用首次学习时的 (60, 30)。
        assert backend.commands[0].capture_id != observation.current_capture.capture_id
        if existing_evidence_adapter:
            source_state = next(state for state in asset["states"]
                if state["state_id"] == transition["source_state_id"])
            target_anchor = next(anchor for anchor in source_state["identity_anchors"]
                if anchor["anchor_id"] == transition["element_ref"])
            assert target_anchor["label"] == "View details"
            assert target_anchor["kind"] == "control"
            assert "View details" in recognition_goals and "open_detail" not in recognition_goals
            assert backend.commands[0].capture_id.startswith("runtime-capture.")
            assert backend.commands[0].click_point == (100.0, 70.0)
            assert len(screenshots.calls) == 4
        else:
            assert backend.commands[0].capture_id == "capture-reuse-2"
            assert backend.commands[0].click_point == (220.0, 240.0)
            assert source.projected_calls == 3
        assert host.single_step.execute(confirmation_id=confirmation_id) == response
        assert backend.attempt_count == 1
        host.release_grounded_runtime(confirmation_id=confirmation_id, timeout=30.0)
        assert all(not controller._sessions for controller in controllers)
        assert claims.list_unresolved_claims() == ()
    finally:
        host.close()
