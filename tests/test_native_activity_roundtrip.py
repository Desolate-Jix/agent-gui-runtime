from __future__ import annotations

import base64
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from weakref import WeakValueDictionary

import pytest

from app.agent.desktop_backend import DeterministicFakeBackend
import app.agent.live_controller as live_controller_module
from app.agent.live_controller import LiveController
from app.agent.live_runtime_composition import (
    ExistingWindowsCurrentEvidenceAdapter,
    ExistingWindowsCurrentEvidenceVisibilityChecker,
)
from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore, content_sha256
from app.agent.reviewed_workflow_gate import ReviewedWorkflowGateAdapter
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
from app.agent.runtime_contracts import RuntimeResultReceiptV1
from app.agent.runtime_grounded_consume import content_sha256 as consume_content_sha256
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStoreError
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from app.agent.runtime_session_selection import RuntimeSessionSelection
from app.api.agent_runtime import AgentRuntimeIntentRequest, LocalAgentRuntimeCallsite
from app.desktop_review.host import DesktopReviewHost
from tests.test_agent_link_shared_host import _post
from tests.test_desktop_exact_review import _new_runtime, _png_bytes
from tests.test_live_runtime_composition_w3b import (
    _SequencedRecognitionRunner,
    _SequencedScreenshotService,
    _UIAProvider,
    _state_payloads,
)


_BINDING = {
    "kind": "native",
    "display_name": "Lonlife Accelerator",
    "executable_identity": r"D:\Lonlife\lonlife_acc.exe",
    "product_name": "Lonlife",
}


@pytest.fixture(autouse=True)
def _isolated_window_leases(monkeypatch: pytest.MonkeyPatch) -> None:
    """本模块只使用私有 fake HWND，不得保留全局 runtime lease。"""
    monkeypatch.setattr(live_controller_module, "_WINDOW_LEASES", WeakValueDictionary())


def _activity_batch() -> dict:
    image = base64.b64encode(_png_bytes("white")).decode("ascii")
    return {
        "contract_version": "agent_link_v1",
        "idempotency_key": "exact-review-batch",
        "batch_id": "exact-review-batch",
        "title": "Synthetic native activity transitions",
        "learning_outcome": "completed",
        "screenshots": [{"screenshot_id": "screen", "png_base64": image}],
        "interfaces": [
            {
                "interface_id": "inactive",
                "screenshot_id": "screen",
                "meaning": "Acceleration is inactive",
                "regions": [
                    {
                        "region_id": "start",
                        "bbox": [40.0, 20.0, 30.0, 30.0],
                        "name": "Start acceleration",
                        "meaning": "start activity",
                    }
                ],
            },
            {
                "interface_id": "active",
                "screenshot_id": "screen",
                "meaning": "Acceleration is active",
                "regions": [
                    {
                        "region_id": "stop",
                        "bbox": [40.0, 20.0, 30.0, 30.0],
                        "name": "Stop acceleration",
                        "meaning": "stop activity",
                    }
                ],
            },
        ],
        "relationships": [],
        "steps": [
            {
                "step_id": "start-acceleration",
                "action_type": "start_activity",
                "target_region_id": "start",
                "start_state": "inactive",
                "arrival_state": "active",
                "prerequisites": [],
                "expected_result": "Acceleration is active",
                "stop_condition": "stop only after activity is active",
            },
            {
                "step_id": "stop-acceleration",
                "action_type": "stop_activity",
                "target_region_id": "stop",
                "start_state": "active",
                "arrival_state": "inactive",
                "prerequisites": [],
                "expected_result": "Acceleration is inactive",
                "stop_condition": "stop only after activity is inactive",
            },
        ],
        "issues": [],
    }


class _BoundWindowManager:
    def __init__(self) -> None:
        self.bound = SimpleNamespace(
            handle=4242,
            process_id=9001,
            is_active=True,
            rect=SimpleNamespace(left=10, top=20, right=330, bottom=220),
        )

    def get_bound_window(self):
        return self.bound


class _NativeIdentityReader:
    def __init__(self) -> None:
        self.calls = 0
        self.replace_after: int | None = None

    def read_identity(self, target_window_handle: int) -> dict:
        self.calls += 1
        replaced = self.replace_after is not None and self.calls > self.replace_after
        return {
            "contract_version": "windows_native_identity_observation_v1",
            "provider": "windows_native_identity",
            "status": "observed",
            "target_window_handle": target_window_handle,
            "process_id": 9001,
            "process_create_time": 2000.5 if replaced else 1000.5,
            "executable_path": r"d:\lonlife\lonlife_acc.exe",
        }


class _AllowedVisibility:
    def check(self, **_kwargs: object) -> dict:
        return {
            "bound_window_handle": 4242,
            "point_visibility": {"allowed": True},
        }


def _compile_activity_asset(tmp_path: Path) -> tuple[ReviewedWorkflowAssetStore, dict]:
    store, _, facade, workspace = _new_runtime(tmp_path, _activity_batch())
    try:
        prepared = facade.prepare_exact_review(
            "task",
            "exact-review-batch",
            workspace["revision"],
            deepcopy(_BINDING),
        )
        approved = facade.record_review_decisions(
            prepared["review_ref"],
            prepared["approval_revision"],
            [subject["subject_id"] for subject in prepared["subjects"]],
        )
        compiled = facade.compile_exact_review(
            prepared["review_ref"], approved["approval_revision"]
        )
        assert compiled["status"] == "compiled", compiled
        facade.publish_exact_review(compiled["compile_receipt_id"])
        assets = ReviewedWorkflowAssetStore(project_root=tmp_path / "root")
        active = assets.registry()["active_by_asset"]
        assert len(active) == 1
        asset = assets.load_active(next(iter(active)))
        assert asset["application"] == {
            "identity_status": "resolved",
            "kind": "native",
            "allow_external_sites": False,
            "executable": "lonlife_acc.exe",
            "product_identity": "lonlife",
            "executable_path": r"d:\lonlife\lonlife_acc.exe",
        }
        return assets, asset
    finally:
        facade.close()
        store.close()


def _runtime(
    tmp_path: Path,
    *,
    action: str,
) -> SimpleNamespace:
    assets, asset = _compile_activity_asset(tmp_path)
    states_by_name = {state["display_name"]: state for state in asset["states"]}
    source_name = "Acceleration is inactive" if action == "start_activity" else "Acceleration is active"
    target_name = "Acceleration is active" if action == "start_activity" else "Acceleration is inactive"
    source_state = states_by_name[source_name]
    target_state = states_by_name[target_name]
    manager = _BoundWindowManager()
    identity_reader = _NativeIdentityReader()
    project_root = assets.project_root
    screenshot = _SequencedScreenshotService(
        project_root,
        colors=[(1, 20, 30)] * 12,
    )
    recognition = _SequencedRecognitionRunner(
        [_state_payloads(asset, source_state["state_id"])] * 4
        + [_state_payloads(asset, target_state["state_id"])] * 4
    )
    evidence = ExistingWindowsCurrentEvidenceAdapter(
        project_root=project_root,
        application_identity_key="native:lonlife_acc.exe:lonlife",
        screenshot_service=screenshot,
        window_manager=manager,
        native_identity_reader=identity_reader,
        recognition_runner=recognition,
        uia_provider=_UIAProvider(),
    )
    receipts = RuntimeReceiptStore(project_root=project_root)
    claims = RuntimeIntentClaimStore(
        project_root=project_root,
        receipt_store=receipts,
    )
    backend = DeterministicFakeBackend()
    controllers: list[LiveController] = []

    def build(binding):
        controller = LiveController(
            binding=binding,
            asset_loader=assets,
            observation_source=evidence,
            target_resolver=evidence,
            gate=ReviewedWorkflowGateAdapter(),
            window_visibility_checker=ExistingWindowsCurrentEvidenceVisibilityChecker(
                evidence_adapter=evidence,
                delegate=_AllowedVisibility(),
            ),
            backend=backend,
            intent_claim_store=claims,
            grounding_policy={
                "minimum_confidence": 0.45,
                "minimum_score_margin": 0.06,
            },
        )
        controllers.append(controller)
        return controller

    service = LocalAgentRuntimeCallsite(
        project_root=project_root,
        asset_store=assets,
        claim_store=claims,
        window_manager=manager,
        controller_factory=build,
        selection=RuntimeSessionSelection(
            asset["asset_id"], content_sha256(asset), 4242, 9001
        ),
    )
    return SimpleNamespace(
        asset=asset,
        service=service,
        claims=claims,
        receipts=receipts,
        backend=backend,
        manager=manager,
        identity_reader=identity_reader,
        screenshot=screenshot,
        recognition=recognition,
        controllers=controllers,
        target_source_node_id=target_state["source_node_id"],
    )


def _request(observation, semantic_action: str) -> AgentRuntimeIntentRequest:
    action = next(
        item
        for item in observation.available_actions
        if item.semantic_action == semantic_action
    )
    return AgentRuntimeIntentRequest(
        intent_id=f"intent.{semantic_action}",
        session_id=observation.session_id,
        observation_id=observation.observation_id,
        action_id=action.action_id,
    )


def _consume_native_activity(runtime: SimpleNamespace, semantic_action: str) -> str:
    """用同一套 fake C1/C2 走完 durable consume，供篡改读取断言复用。"""
    observation = runtime.service.start_session()
    request = _request(observation, semantic_action)
    assert runtime.service.prepare_grounded_review(request).to_dict()["status"] == "prepared"
    pending = runtime.service.request_grounded_confirmation(request)
    confirmation_id = pending.grounded_confirmation.confirmation_id
    runtime.service.decide_grounded_confirmation(
        confirmation_id=confirmation_id,
        decision="approved",
    )
    receipt = runtime.service.consume_grounded_confirmation(
        confirmation_id=confirmation_id,
    )
    assert isinstance(receipt, RuntimeResultReceiptV1)
    assert receipt.outcome == "VERIFIED"
    assert receipt.next_observation_id is not None
    assert runtime.backend.attempt_count == runtime.backend.dispatch_count == 1
    return confirmation_id


@pytest.mark.parametrize("semantic_action", ["start_activity", "stop_activity"])
def test_native_activity_roundtrip_uses_exact_review_and_owned_http_once(
    tmp_path: Path,
    semantic_action: str,
) -> None:
    runtime = _runtime(tmp_path, action=semantic_action)
    observation = runtime.service.start_session()
    request = _request(observation, semantic_action)

    preview = runtime.service.prepare_grounded_review(request)
    assert preview.to_dict()["status"] == "prepared"
    assert runtime.backend.attempt_count == 0

    pending = runtime.service.request_grounded_confirmation(request)
    confirmation_id = pending.grounded_confirmation.confirmation_id
    assert pending.phase == "grounded_confirmation_pending"
    assert runtime.backend.attempt_count == 0

    host = DesktopReviewHost(
        tmp_path / "host-inbox.json",
        tmp_path / "host-reviews",
        "native-activity-reviewer",
        port=0,
    )
    operation_error: BaseException | None = None
    try:
        host.start()
        host.attach_grounded_runtime(runtime.service, confirmation_id=confirmation_id)
        learning = host.connections.create_connection("native-activity", "synthetic")
        status, denied = _post(
            host.status()["base_url"] + "/action/execute_recognition_plan",
            learning["token"],
            {"confirmation_id": confirmation_id},
        )
        assert status == 401
        assert denied["error"]["result_unknown"] is False
        assert runtime.backend.attempt_count == 0

        runtime.service.decide_grounded_confirmation(
            confirmation_id=confirmation_id,
            decision="approved",
        )
        response = host.single_step.execute(confirmation_id=confirmation_id)
        assert response["kind"] == "receipt", response["payload"]
        receipt = RuntimeResultReceiptV1.model_validate(response["payload"])
        assert receipt.outcome == "VERIFIED"
        assert receipt.reason_code == "none"
        assert receipt.attempt_count == 1
        assert receipt.effect_status == receipt.destination_status == "verified"
        assert receipt.next_observation_id is not None
        assert receipt.evidence.verification_ref is not None
        next_observation = runtime.receipts.resolve_next_observation(receipt.receipt_id)
        assert next_observation.observation_id == receipt.next_observation_id
        assert next_observation.state.source_interface_id == runtime.target_source_node_id
        assert runtime.backend.attempt_count == runtime.backend.dispatch_count == 1
        assert runtime.backend.commands[0].semantic_action == semantic_action
        repeated = host.single_step.execute(confirmation_id=confirmation_id)
        assert repeated == response
        assert runtime.backend.attempt_count == 1
    except BaseException as error:
        operation_error = error
        raise
    finally:
        try:
            host.close()
        except Exception:
            if operation_error is None:
                raise


def test_native_activity_replacement_during_preview_is_denied_before_dispatch(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path, action="start_activity")
    observation = runtime.service.start_session()
    runtime.identity_reader.replace_after = runtime.identity_reader.calls + 1

    preview = runtime.service.prepare_grounded_review(_request(observation, "start_activity"))

    assert preview.status in {"REJECTED", "RECOVERY_REQUIRED"}
    assert runtime.backend.attempt_count == 0
    assert runtime.backend.commands == []


@pytest.mark.parametrize("mutation", ["path", "pid", "creation_time", "missing_identity"])
def test_rehashed_native_consume_identity_fact_is_rejected_without_new_dispatch(
    tmp_path: Path,
    mutation: str,
) -> None:
    runtime = _runtime(tmp_path, action="start_activity")
    confirmation_id = _consume_native_activity(runtime, "start_activity")
    consume_path = next(runtime.claims.grounded_consume_root.iterdir())
    marker = json.loads(consume_path.read_text(encoding="utf-8"))
    current = marker["current_observation"]
    native = current["native_identity"]
    if mutation == "path":
        native["executable_path"] = r"d:\other\lonlife_acc.exe"
    elif mutation == "pid":
        native["process_id"] = 9002
    elif mutation == "creation_time":
        native["process_create_time"] = 2000.6
    else:
        current.pop("native_identity")
    marker["consume_binding_sha256"] = consume_content_sha256(
        {key: value for key, value in marker.items() if key != "consume_binding_sha256"}
    )
    consume_path.write_text(
        json.dumps(marker, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeIntentClaimStoreError):
        runtime.claims.get_for_grounded_confirmation(confirmation_id=confirmation_id)
    assert runtime.backend.attempt_count == runtime.backend.dispatch_count == 1
