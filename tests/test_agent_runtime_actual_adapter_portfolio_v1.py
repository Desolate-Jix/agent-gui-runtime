from __future__ import annotations

from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.agent.desktop_backend import DeterministicFakeBackend
from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore, content_sha256
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from app.api.agent_runtime import (
    LocalAgentRuntimeCallsite,
    get_agent_runtime_callsite,
    router,
)
from tests.test_live_controller_portfolio_confirmation_v1 import (
    _compiled_portfolio_asset,
)
from tests.test_live_runtime_composition_w3b import (
    _OriginReader,
    _SequencedRecognitionRunner,
    _SequencedScreenshotService,
    _UIAProvider,
    _state_payloads,
)


class _StableWindowManager:
    def __init__(self) -> None:
        self.bound = SimpleNamespace(
            handle=4242,
            process_id=9001,
            is_active=True,
            rect=SimpleNamespace(left=10, top=20, right=330, bottom=220),
        )
        self.calls = 0
        self.visibility_calls: list[dict[str, int]] = []

    def get_bound_window(self):
        self.calls += 1
        return self.bound

    def validate_bound_point_visibility(self, *, bound: object, x: int, y: int):
        assert bound is self.bound
        assert 0 <= x <= 320
        assert 0 <= y <= 200
        self.visibility_calls.append({"x": x, "y": y})
        return {"allowed": True, "click_point": {"x": x, "y": y}}


def _route_client(callsite: LocalAgentRuntimeCallsite) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_agent_runtime_callsite] = lambda: callsite
    return TestClient(app, client=("127.0.0.1", 50000))


def test_route_executes_compiled_open_apply_flow_once_and_stops_at_apply_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.agent.live_runtime_composition as composition
    import app.core.screenshot as screenshot_module
    import app.core.window_manager as window_module
    import app.operation.screen_reading.uia_provider as uia_module

    asset = _compiled_portfolio_asset(tmp_path)
    original_asset = deepcopy(asset)
    original_asset_hash = content_sha256(asset)
    states_by_source = {item["source_node_id"]: item for item in asset["states"]}
    transition = asset["transitions"][0]
    detail_state = states_by_source["job_detail"]
    apply_entry_state = states_by_source["apply_entry"]

    asset_store = ReviewedWorkflowAssetStore(project_root=tmp_path)
    published = asset_store.publish(asset, expected_registry_revision=0)
    assert published["status"] == "published"
    assert asset == original_asset
    assert content_sha256(asset_store.load_active(asset["asset_id"])) == original_asset_hash

    manager = _StableWindowManager()
    screenshot = _SequencedScreenshotService(
        tmp_path,
        colors=[
            (1, 20, 30),
            (2, 20, 30),
            (3, 20, 30),
            (3, 20, 30),
            (4, 20, 30),
        ],
    )
    origin = _OriginReader(origin="https://nz.seek.com")
    uia = _UIAProvider(handle=4242, process_id=9001)
    runner = _SequencedRecognitionRunner(
        [
            _state_payloads(asset, detail_state["state_id"]),
            _state_payloads(asset, detail_state["state_id"]),
            _state_payloads(asset, detail_state["state_id"]),
            _state_payloads(asset, apply_entry_state["state_id"]),
        ]
    )
    backend = DeterministicFakeBackend()

    monkeypatch.setattr(screenshot_module, "screenshot_service", screenshot)
    monkeypatch.setattr(window_module, "window_manager", manager)
    monkeypatch.setattr(uia_module, "uia_provider", uia)
    monkeypatch.setattr(
        composition,
        "WindowsUIAOriginReader",
        lambda **_kwargs: origin,
    )
    monkeypatch.setattr(composition, "_run_existing_read_only_recognition", runner)
    monkeypatch.setattr(composition, "ExistingWindowsBackendAdapter", lambda: backend)

    receipt_store = RuntimeReceiptStore(project_root=tmp_path)
    claim_store = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=receipt_store,
    )
    callsite = LocalAgentRuntimeCallsite(
        project_root=tmp_path,
        asset_store=asset_store,
        window_manager=manager,
        claim_store=claim_store,
    )
    client = _route_client(callsite)

    started = client.post("/runtime/agent/session/start", json={})
    assert started.status_code == 200, started.text
    observation = started.json()["data"]
    assert observation["workflow"] == {
        "workflow_id": asset["asset_id"],
        "asset_id": asset["asset_id"],
        "asset_content_sha256": original_asset_hash,
        "source_workflow_sha256": asset["source_review_lineage"]["source_workflow_sha256"],
        "reviewed_revision_hash": asset["source_review_lineage"]["reviewed_revision_hash"],
    }
    assert observation["state"]["state_id"] == detail_state["state_id"]
    action = next(
        item
        for item in observation["available_actions"]
        if item["semantic_action"] == "open_apply_flow"
    )
    assert action["action_id"] == transition["transition_id"]
    assert action["action_id"] != action["semantic_action"]
    assert action["requires_user_confirmation"] is True

    intent_payload = {
        "intent_id": "intent.actual-adapter-open-apply",
        "session_id": observation["session_id"],
        "observation_id": observation["observation_id"],
        "action_id": action["action_id"],
    }
    assert set(intent_payload) == {
        "intent_id",
        "session_id",
        "observation_id",
        "action_id",
    }
    pending = client.post("/runtime/agent/intent/submit", json=intent_payload)
    assert pending.status_code == 200, pending.text
    assert pending.json()["data"] == {
        "status": "NEEDS_REVIEW",
        "reason_code": "human_confirmation_required",
        "confirmation_id": pending.json()["data"]["confirmation_id"],
    }
    confirmation_id = pending.json()["data"]["confirmation_id"]
    assert backend.attempt_count == backend.dispatch_count == 0

    confirmation_payload = {
        "confirmation_id": confirmation_id,
        "decision": "approved",
    }
    assert set(confirmation_payload) == {"confirmation_id", "decision"}
    approved = client.post(
        "/runtime/agent/confirmation/decide",
        json=confirmation_payload,
    )
    assert approved.status_code == 200, approved.text
    receipt = approved.json()["data"]
    assert receipt["workflow"] == observation["workflow"]
    assert receipt["action"] == {
        "action_id": transition["transition_id"],
        "semantic_action": "open_apply_flow",
    }
    assert receipt["outcome"] == "SAFE_STOP"
    assert receipt["reason_code"] == "stop_boundary"
    assert receipt["attempt_count"] == 1
    assert receipt["gate_status"] == "allowed"
    assert receipt["dispatch_status"] == "dispatched"
    assert receipt["effect_status"] == "verified"
    assert receipt["destination_status"] == "verified"
    assert receipt["safe_stop"] == {
        "required": True,
        "reason_code": "stop_boundary",
    }
    assert receipt["next_observation_id"]
    evidence = receipt["evidence"]
    for key in (
        "state_resolution_ref",
        "selection_ref",
        "candidate_ref",
        "gate_decision_ref",
        "backend_receipt_ref",
        "verification_ref",
    ):
        assert evidence[key]

    assert backend.attempt_count == backend.dispatch_count == len(backend.commands) == 1
    command = backend.commands[0]
    assert command.semantic_action == "open_apply_flow"
    assert command.target_window_handle == 4242
    assert command.capture_id in evidence["candidate_ref"]
    assert command.candidate_id in evidence["candidate_ref"]
    assert manager.visibility_calls == [
        {"x": int(command.click_point[0]), "y": int(command.click_point[1])}
    ]

    claim = claim_store.get_for_observation(
        session_id=observation["session_id"],
        observation_id=observation["observation_id"],
    )
    assert claim.phase == "terminal"
    assert claim.intent.model_dump(mode="json") == {
        "contract_version": "agent_intent_v1",
        **intent_payload,
        "workflow": observation["workflow"],
    }
    assert claim.confirmation is not None
    assert claim.confirmation.decision == "approved"
    assert claim.confirmation.evidence_ref in evidence["trace_refs"]
    assert f"trace:live-controller:{receipt['receipt_id']}" in evidence["trace_refs"]

    persisted = receipt_store.load_by_receipt_id(receipt["receipt_id"])
    assert persisted.runtime_receipt.model_dump(mode="json") == receipt
    assert persisted.backend_receipt is not None
    assert persisted.backend_receipt.receipt_ref == evidence["backend_receipt_ref"]
    assert persisted.verification_evidence is not None
    assert persisted.verification_evidence["status"] == "verified"
    assert persisted.verification_evidence["post_state_resolution"]["state_id"] == (
        apply_entry_state["state_id"]
    )
    next_observation = persisted.next_observation
    assert next_observation is not None
    assert next_observation.observation_id == receipt["next_observation_id"]
    assert next_observation.state.status == "stop_boundary"
    assert next_observation.state.state_id == apply_entry_state["state_id"]
    assert next_observation.state.state_availability == "stop_boundary"
    assert [item.semantic_action for item in next_observation.available_actions] == [
        "safe_stop"
    ]

    serialized_terminal = json.dumps(
        {
            "receipt": receipt,
            "next_observation": next_observation.model_dump(mode="json"),
        },
        ensure_ascii=False,
    )
    for forbidden in ("fill_field", "continue_next_step", "final_submit"):
        assert forbidden not in serialized_terminal

    assert [item["purpose"] for item in screenshot.calls] == [
        "runtime-observation",
        "runtime-observation",
        "runtime-observation",
        "runtime-pre-dispatch-freshness",
        "runtime-observation",
    ]
    assert screenshot.paths[2].read_bytes() == screenshot.paths[3].read_bytes()
    assert screenshot.paths[3].read_bytes() != screenshot.paths[4].read_bytes()
    assert len(runner.capture_paths) == 4
    all_anchor_labels = {
        anchor["label"]
        for state in asset["states"]
        for anchor in state["identity_anchors"]
    }
    recognition_calls_by_path = Counter(
        (str(call["image_path"]), str(call["goal"])) for call in runner.calls
    )
    assert set(recognition_calls_by_path.values()) == {1}
    assert len(runner.calls) == len(runner.capture_paths) * len(all_anchor_labels)
    for capture_path in runner.capture_paths:
        assert {
            str(call["goal"])
            for call in runner.calls
            if call["image_path"] == capture_path
        } == all_anchor_labels
    assert len(uia.calls) == 4
    assert origin.calls == [4242] * 8

    before_duplicate_counts = {
        "screenshots": len(screenshot.calls),
        "recognition": len(runner.calls),
        "attempts": backend.attempt_count,
        "dispatches": backend.dispatch_count,
    }
    repeated_approval = client.post(
        "/runtime/agent/confirmation/decide",
        json=confirmation_payload,
    )
    repeated_intent = client.post(
        "/runtime/agent/intent/submit",
        json=intent_payload,
    )
    assert repeated_approval.status_code == repeated_intent.status_code == 200
    assert repeated_approval.json()["data"] == receipt
    assert repeated_intent.json()["data"] == receipt
    assert {
        "screenshots": len(screenshot.calls),
        "recognition": len(runner.calls),
        "attempts": backend.attempt_count,
        "dispatches": backend.dispatch_count,
    } == before_duplicate_counts
