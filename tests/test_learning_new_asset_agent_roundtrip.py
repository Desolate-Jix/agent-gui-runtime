"""新离线学习资产贯通真实 Agent 路由/适配层；所有观测与派发均为替身。"""

from copy import deepcopy
import gc
import hashlib
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.agent.desktop_backend import DeterministicFakeBackend
from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore, content_sha256
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from app.api.agent_runtime import LocalAgentRuntimeCallsite, get_agent_runtime_callsite, router
from tests.test_live_runtime_composition_w3b import (
    _OriginReader, _SequencedRecognitionRunner, _SequencedScreenshotService, _UIAProvider, _state_payloads,
)


class _Window:
    def __init__(self):
        self.bound = SimpleNamespace(handle=4242, process_id=9001, is_active=True,
                                     rect=SimpleNamespace(left=10, top=20, right=330, bottom=220))

    def get_bound_window(self):
        return self.bound

    def validate_bound_point_visibility(self, *, bound, x, y):
        assert bound is self.bound
        assert 0 <= x <= 320 and 0 <= y <= 200
        return {"allowed": True, "click_point": {"x": x, "y": y}}


def _runtime(tmp_path, monkeypatch, *, initial_source_node="job_detail"):
    from tests.test_learning_new_asset_offline import fresh_selection_replay_review_asset
    import app.agent.live_runtime_composition as composition
    import app.core.screenshot as screenshot_module
    import app.core.window_manager as window_module
    import app.operation.screen_reading.uia_provider as uia_module

    learned = fresh_selection_replay_review_asset(tmp_path)
    asset = learned["asset"]
    states = {state["source_node_id"]: state for state in asset["states"]}
    window = _Window()
    screenshots = _SequencedScreenshotService(tmp_path, colors=[(1, 20, 30), (2, 20, 30), (3, 20, 30), (3, 20, 30), (4, 20, 30)])
    origin = _OriginReader(origin=asset["application"]["canonical_origin"])
    initial_state = states[initial_source_node]
    runner = _SequencedRecognitionRunner([
        _state_payloads(asset, initial_state["state_id"]),
        _state_payloads(asset, initial_state["state_id"]),
        _state_payloads(asset, initial_state["state_id"]),
        _state_payloads(asset, states["apply_entry"]["state_id"]),
    ])
    backend = DeterministicFakeBackend()
    monkeypatch.setattr(screenshot_module, "screenshot_service", screenshots)
    monkeypatch.setattr(window_module, "window_manager", window)
    monkeypatch.setattr(uia_module, "uia_provider", _UIAProvider(handle=4242, process_id=9001))
    monkeypatch.setattr(composition, "WindowsUIAOriginReader", lambda **kw: origin)
    monkeypatch.setattr(composition, "_run_existing_read_only_recognition", runner)
    monkeypatch.setattr(composition, "ExistingWindowsBackendAdapter", lambda: backend)
    receipts = RuntimeReceiptStore(project_root=tmp_path)
    claims = RuntimeIntentClaimStore(project_root=tmp_path, receipt_store=receipts)
    store = ReviewedWorkflowAssetStore(project_root=tmp_path)
    callsite = LocalAgentRuntimeCallsite(project_root=tmp_path, asset_store=store, window_manager=window, claim_store=claims)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_agent_runtime_callsite] = lambda: callsite
    client = TestClient(app, client=("127.0.0.1", 51000))
    return SimpleNamespace(learned=learned, asset=asset, states=states, window=window, backend=backend,
                           receipts=receipts, claims=claims, client=client, store=store)


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    active = _runtime(tmp_path, monkeypatch)
    try:
        yield active
    finally:
        active.client.close()
        active.client.app.dependency_overrides.pop(get_agent_runtime_callsite, None)
        gc.collect()


@pytest.fixture
def initial_safe_stop_runtime(tmp_path, monkeypatch):
    active = _runtime(
        tmp_path,
        monkeypatch,
        initial_source_node="apply_entry",
    )
    try:
        yield active
    finally:
        active.client.close()
        active.client.app.dependency_overrides.pop(get_agent_runtime_callsite, None)
        gc.collect()


def _start(runtime):
    response = runtime.client.post("/runtime/agent/session/start", json={})
    assert response.status_code == 200, response.text
    observation = response.json()["data"]
    action = next(item for item in observation["available_actions"] if item["semantic_action"] == "open_apply_flow")
    return observation, {"intent_id": "offline-new-learning-intent", "session_id": observation["session_id"],
                         "observation_id": observation["observation_id"], "action_id": action["action_id"]}


def test_initial_safe_stop_observation_is_terminal_and_releases_runtime_lease(
    initial_safe_stop_runtime,
):
    first = initial_safe_stop_runtime.client.post("/runtime/agent/session/start", json={})
    second = initial_safe_stop_runtime.client.post("/runtime/agent/session/start", json={})

    assert first.status_code == second.status_code == 200
    first_observation = first.json()["data"]
    second_observation = second.json()["data"]
    assert first_observation["session_id"] != second_observation["session_id"]
    assert first_observation["safe_stop"] == second_observation["safe_stop"] == {
        "required": True,
        "reason_code": "stop_boundary",
    }
    assert initial_safe_stop_runtime.claims.list_unresolved_claims() == ()
    assert initial_safe_stop_runtime.backend.attempt_count == 0
    assert initial_safe_stop_runtime.backend.dispatch_count == 0


def test_initial_matched_observation_remains_active_and_safe_stop_close_refuses(runtime):
    started = runtime.client.post("/runtime/agent/session/start", json={})
    assert started.status_code == 200, started.text
    callsite = runtime.client.app.dependency_overrides[get_agent_runtime_callsite]()
    with pytest.raises(ValueError, match="initial safe-stop"):
        callsite._controller.close_initial_safe_stop(
            session_id=started.json()["data"]["session_id"],
        )
    repeated = runtime.client.post("/runtime/agent/session/start", json={})
    assert repeated.status_code == 409, repeated.text
    assert runtime.backend.attempt_count == runtime.backend.dispatch_count == 0


@pytest.mark.parametrize("blocker", ["consumed", "durable_claim"])
def test_initial_safe_stop_close_refuses_consumed_or_claimed_session(
    initial_safe_stop_runtime,
    monkeypatch,
    blocker,
):
    callsite = initial_safe_stop_runtime.client.app.dependency_overrides[
        get_agent_runtime_callsite
    ]()
    resolved = callsite._resolve_server_binding()
    controller = callsite._controller_factory(resolved.binding)
    snapshot = controller.start_session()
    session = controller._sessions[snapshot.session_id]
    assert snapshot.current_observation.safe_stop.required is True

    if blocker == "consumed":
        session.consumed = True
    else:
        original_find = controller._intent_claim_store.find_for_observation
        monkeypatch.setattr(
            controller._intent_claim_store,
            "find_for_observation",
            lambda **_kwargs: SimpleNamespace(),
        )
    with pytest.raises(ValueError):
        controller.close_initial_safe_stop(session_id=snapshot.session_id)

    assert controller._sessions[snapshot.session_id] is session
    competing = callsite._controller_factory(resolved.binding)
    with pytest.raises(RuntimeError, match="window lease is already held"):
        competing.start_session()

    if blocker == "consumed":
        session.consumed = False
    else:
        monkeypatch.setattr(
            controller._intent_claim_store,
            "find_for_observation",
            original_find,
        )
    controller.close_initial_safe_stop(session_id=snapshot.session_id)
    assert snapshot.session_id not in controller._sessions

    released = callsite._controller_factory(resolved.binding)
    released_snapshot = released.start_session()
    released.close_initial_safe_stop(session_id=released_snapshot.session_id)


def test_initial_safe_stop_close_refuses_unknown_session(initial_safe_stop_runtime):
    callsite = initial_safe_stop_runtime.client.app.dependency_overrides[
        get_agent_runtime_callsite
    ]()
    controller = callsite._controller_factory(callsite._resolve_server_binding().binding)

    with pytest.raises(ValueError, match="not owned"):
        controller.close_initial_safe_stop(session_id="session.unknown")


def test_fresh_reviewed_asset_reaches_real_agent_confirmation_and_persisted_safe_stop(runtime):
    original = deepcopy(runtime.asset)
    source = runtime.learned["source_path"]
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    observation, intent = _start(runtime)
    assert observation["workflow"]["workflow_id"] == original["source_review_lineage"]["source_workflow_id"]
    assert observation["workflow"]["asset_id"] == original["asset_id"]
    assert observation["workflow"]["asset_content_sha256"] == content_sha256(original)
    assert observation["workflow"]["source_workflow_sha256"] == runtime.learned["source_sha256"]
    pending = runtime.client.post("/runtime/agent/intent/submit", json=intent)
    assert pending.status_code == 200, pending.text
    assert pending.json()["data"]["status"] == "NEEDS_REVIEW"
    assert runtime.backend.dispatch_count == runtime.backend.attempt_count == 0
    approval = {"confirmation_id": pending.json()["data"]["confirmation_id"], "decision": "approved"}
    response = runtime.client.post("/runtime/agent/confirmation/decide", json=approval)
    assert response.status_code == 200, response.text
    receipt = response.json()["data"]
    assert receipt["workflow"] == observation["workflow"]
    assert (receipt["outcome"], receipt["reason_code"]) == ("SAFE_STOP", "stop_boundary")
    assert receipt["attempt_count"] == runtime.backend.dispatch_count == len(runtime.backend.commands) == 1
    assert receipt["effect_status"] == receipt["destination_status"] == "verified"
    persisted = runtime.receipts.load_by_receipt_id(receipt["receipt_id"])
    assert persisted.runtime_receipt.model_dump(mode="json") == receipt
    assert persisted.next_observation.state.state_id == runtime.states["apply_entry"]["state_id"]
    assert [action.semantic_action for action in persisted.next_observation.available_actions] == ["safe_stop"]
    for endpoint, payload in [("confirmation/decide", approval), ("intent/submit", intent)]:
        repeated = runtime.client.post(f"/runtime/agent/{endpoint}", json=payload)
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["data"] == receipt
    assert runtime.backend.dispatch_count == runtime.backend.attempt_count == 1
    assert runtime.store.load_active(original["asset_id"]) == original
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
    # 将真实路由响应交给面板控制器，防止前后端各自伪造一套兼容契约。
    browser_contract = subprocess.run(
        ["node", "-e", """
const fs = require('node:fs');
const assert = require('node:assert/strict');
const { createAgentRuntimePanel } = require('./app/web_panel/agent_runtime_panel.js');
const data = JSON.parse(fs.readFileSync(0, 'utf8'));
let index = 0;
const expected = [
  ['/runtime/agent/session/start', {}],
  ['/runtime/agent/intent/submit', data.intent],
  ['/runtime/agent/confirmation/decide', data.approval],
];
const controller = createAgentRuntimePanel({
  createIntentId: () => data.intent.intent_id,
  request: async (method, path, payload) => {
    assert.equal(method, 'POST');
    assert.deepEqual([path, payload], expected[index]);
    return {success: true, data: data.responses[index++]};
  },
});
(async () => {
  assert.equal(index, 0);
  await controller.start();
  assert.equal(controller.getState().phase, 'ready');
  await controller.requestStep();
  assert.equal(controller.getState().phase, 'needs_review');
  await controller.decide('approved');
  assert.equal(controller.getState().phase, 'terminal');
  assert.deepEqual(controller.getState().receipt, data.responses[2]);
  assert.equal(index, 3);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""],
        cwd=Path(__file__).resolve().parents[1],
        input=json.dumps({"intent": intent, "approval": approval,
                          "responses": [observation, pending.json()["data"], receipt]}, ensure_ascii=False),
        text=True, encoding="utf-8", capture_output=True, timeout=20,
    )
    assert browser_contract.returncode == 0, browser_contract.stderr


@pytest.mark.parametrize("invalid", ["stale_observation", "forbidden_action", "wrong_window"])
def test_new_asset_invalid_intent_or_window_never_dispatches(runtime, invalid):
    _, intent = _start(runtime)
    if invalid == "stale_observation":
        intent["observation_id"] = "old-observation"
    elif invalid == "forbidden_action":
        intent["action_id"] = "final_submit"
    else:
        runtime.window.bound.process_id += 1
    response = runtime.client.post("/runtime/agent/intent/submit", json=intent)
    assert response.status_code in (409, 412), response.text
    assert response.json()["success"] is False
    assert runtime.backend.dispatch_count == runtime.backend.attempt_count == 0


def test_new_asset_confirmation_denial_never_dispatches(runtime):
    _, intent = _start(runtime)
    pending = runtime.client.post("/runtime/agent/intent/submit", json=intent)
    assert pending.status_code == 200, pending.text
    response = runtime.client.post("/runtime/agent/confirmation/decide", json={
        "confirmation_id": pending.json()["data"]["confirmation_id"], "decision": "denied"})
    assert response.status_code == 200, response.text
    assert response.json()["data"]["status"] == "REJECTED"
    assert runtime.backend.dispatch_count == runtime.backend.attempt_count == 0
