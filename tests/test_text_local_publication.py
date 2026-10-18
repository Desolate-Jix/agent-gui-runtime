"""真实编译、当前证据、控制器和磁盘 claim，只有系统窗口/识别是隔离替身。"""
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
import json

import pytest

from app.agent.desktop_backend import DeterministicFakeBackend
from app.agent.live_controller import LiveController, LiveControllerDecision
from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore, content_sha256
from app.agent.reviewed_workflow_gate import ReviewedWorkflowGateAdapter
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from app.agent.runtime_session_selection import RuntimeSessionSelection
from app.agent.text_parameters import resolve_text_parameters
from app.agent.text_execution import text_execution_reference
from app.api.agent_runtime import LocalAgentRuntimeCallsite, AgentRuntimeIntentRequest
from tests.test_live_controller_w4 import _WindowVisibilityChecker
from tests.test_live_runtime_composition_w3b import _bound
import test_text_formal_review_flow as flow


@pytest.fixture
def local(tmp_path, monkeypatch):
    parameters = deepcopy(flow.PARAMETERS)
    parameters["content"] = {"kind": "variable", "name": "query"}
    monkeypatch.setattr(flow, "PARAMETERS", parameters)
    asset, adapter, transition, *_ = flow.text_preview_inputs(tmp_path)
    window = SimpleNamespace(**vars(_bound()), is_active=True, title="Synthetic field", process_name="browser.exe")
    windows = SimpleNamespace(get_bound_window=lambda: window,
        list_visible_windows=lambda: [vars(window)], bind_window_by_handle=lambda handle: window)
    adapter._window_manager = windows
    assets = ReviewedWorkflowAssetStore(project_root=tmp_path)
    assets.publish(asset, expected_registry_revision=0)
    claims = RuntimeIntentClaimStore(project_root=tmp_path, receipt_store=RuntimeReceiptStore(project_root=tmp_path))
    backend = DeterministicFakeBackend()
    controllers = []

    def build(binding):
        controller = LiveController(binding=binding, asset_loader=assets, observation_source=adapter,
            target_resolver=adapter, gate=ReviewedWorkflowGateAdapter(), backend=backend,
            window_visibility_checker=_WindowVisibilityChecker(bound_window_handle=4242),
            intent_claim_store=claims, grounding_policy=flow.POLICY)
        controllers.append(controller)
        return controller

    service = LocalAgentRuntimeCallsite(project_root=tmp_path, asset_store=assets, claim_store=claims,
        window_manager=windows, controller_factory=build,
        selection=RuntimeSessionSelection(asset["asset_id"], content_sha256(asset), 4242, 9001))
    try:
        observation = service.start_session()
        request = AgentRuntimeIntentRequest(intent_id="text-intent", session_id=observation.session_id,
            observation_id=observation.observation_id, action_id=transition["transition_id"])
        yield SimpleNamespace(service=service, observation=observation, request=request, claims=claims,
                              backend=backend, root=tmp_path, controllers=controllers, windows=windows, asset=asset)
    finally:
        for controller in controllers:
            for session_id in list(controller._sessions):
                if session_id in controller._grounded_publications:
                    service.cancel_grounded_review(session_id=session_id)
                else:
                    controller.abandon_session(session_id=session_id)



@pytest.fixture
def local_fixed(tmp_path, monkeypatch):
    parameters = deepcopy(flow.PARAMETERS)
    parameters["content"] = {"kind": "literal", "text": "原始中文\r\n固定来源"}
    monkeypatch.setattr(flow, "PARAMETERS", parameters)
    asset, adapter, transition, *_ = flow.text_preview_inputs(tmp_path)
    window = SimpleNamespace(**vars(_bound()), is_active=True, title="Synthetic field", process_name="browser.exe")
    windows = SimpleNamespace(get_bound_window=lambda: window,
        list_visible_windows=lambda: [vars(window)], bind_window_by_handle=lambda handle: window)
    adapter._window_manager = windows
    assets = ReviewedWorkflowAssetStore(project_root=tmp_path)
    assets.publish(asset, expected_registry_revision=0)
    claims = RuntimeIntentClaimStore(project_root=tmp_path, receipt_store=RuntimeReceiptStore(project_root=tmp_path))
    backend = DeterministicFakeBackend()
    controllers = []
    def build(binding):
        controller = LiveController(binding=binding, asset_loader=assets, observation_source=adapter,
            target_resolver=adapter, gate=ReviewedWorkflowGateAdapter(), backend=backend,
            window_visibility_checker=_WindowVisibilityChecker(bound_window_handle=4242),
            intent_claim_store=claims, grounding_policy=flow.POLICY)
        controllers.append(controller)
        return controller
    service = LocalAgentRuntimeCallsite(project_root=tmp_path, asset_store=assets, claim_store=claims,
        window_manager=windows, controller_factory=build,
        selection=RuntimeSessionSelection(asset["asset_id"], content_sha256(asset), 4242, 9001))
    try:
        observation = service.start_session()
        request = AgentRuntimeIntentRequest(intent_id="text-intent", session_id=observation.session_id,
            observation_id=observation.observation_id, action_id=transition["transition_id"])
        yield SimpleNamespace(service=service, observation=observation, request=request, claims=claims,
                              backend=backend, root=tmp_path, controllers=controllers, windows=windows, asset=asset)
    finally:
        for controller in controllers:
            for session_id in list(controller._sessions):
                if session_id in controller._grounded_publications:
                    service.cancel_grounded_review(session_id=session_id)
                else:
                    controller.abandon_session(session_id=session_id)

def test_local_value_is_frozen_before_preview_persisted_as_reference_only(local):
    reviewed = local.service.get_local_reviewed_text_parameters(action_id=local.request.action_id)
    variables = {"query": "仅本次输入\r\n不进入公开观察"}
    resolved = resolve_text_parameters(reviewed, variables)
    claim = local.service.request_grounded_confirmation(local.request, text_input=resolved)
    assert not isinstance(claim, LiveControllerDecision)
    variables["query"] = "mutated"
    preview = claim.grounded_confirmation.preview.to_dict()
    assert preview["text_execution_ref"] == text_execution_reference(resolved)
    # JSON 会转义换行，检查实际序列化值而不是永远匹配不到的原始 CRLF。
    encoded_value = json.dumps(resolved.text, ensure_ascii=False)
    assert encoded_value not in json.dumps(preview, ensure_ascii=False)
    assert encoded_value not in json.dumps(local.observation.model_dump(mode="json"), ensure_ascii=False)
    assert local.backend.attempt_count == 0
    cid = claim.grounded_confirmation.confirmation_id
    assert local.service.get_local_grounded_text_input(confirmation_id=cid) == resolved
    reloaded = local.claims.get_for_grounded_confirmation(confirmation_id=cid)
    assert reloaded.grounded_confirmation.preview.to_dict() == preview
    for path in local.root.rglob("*.json"):
        # 此目录存放文件锁哨兵，不是持久 JSON 载荷；其余载荷必须能严格解析。
        if path.parent == local.claims.phase_locks_root:
            continue
        assert encoded_value not in json.dumps(json.loads(path.read_text(encoding="utf-8")), ensure_ascii=False)
    changed = replace(resolved, text="different")
    rejected = local.service.request_grounded_confirmation(local.request, text_input=changed)
    assert rejected.status == "REJECTED"
    assert local.service.get_local_grounded_text_input(confirmation_id=cid) == resolved
    assert local.claims.get_for_grounded_confirmation(confirmation_id=cid).grounded_confirmation.preview.to_dict() == preview
    assert local.backend.attempt_count == 0


def test_agent_intent_cannot_supply_value_and_missing_variable_does_not_claim(local):
    with pytest.raises(ValueError):
        AgentRuntimeIntentRequest.model_validate({**local.request.model_dump(), "text_values": {"query": "unreviewed"}})
    result = local.service.request_grounded_confirmation(local.request)
    assert result.status == "REJECTED"
    assert result.reason_code == "text_input_required"
    assert local.claims.list_unresolved_claims() == ()
    assert local.backend.attempt_count == 0
