from __future__ import annotations

import base64
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from weakref import WeakValueDictionary

import pytest
from PIL import Image

import app.agent.live_controller as live_controller_module
from app.agent.desktop_backend import ExistingWindowsBackendAdapter
from app.agent.live_controller import LiveController
from app.agent.live_runtime_composition import (
    ExistingWindowsCurrentEvidenceAdapter,
    ExistingWindowsCurrentEvidenceVisibilityChecker,
)
from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore, content_sha256
from app.agent.reviewed_workflow_gate import ReviewedWorkflowGateAdapter
from app.agent.runtime_contracts import RuntimeResultReceiptV1
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
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

_SCROLL_PARAMETERS = {
    "contract_version": "reviewed_scroll_parameters_v1",
    "target_container_id": "scroll-pane",
    "axis": "vertical",
    "direction": "down",
    "wheel_clicks": 2,
    "unit": "wheel_detent",
}


@pytest.fixture(autouse=True)
def _isolated_window_leases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(live_controller_module, "_WINDOW_LEASES", WeakValueDictionary())


def _scroll_batch() -> dict:
    image = base64.b64encode(_png_bytes("white")).decode("ascii")
    return {
        "contract_version": "agent_link_v1",
        "idempotency_key": "exact-review-batch",
        "batch_id": "exact-review-batch",
        "title": "Synthetic native scroll transition",
        "learning_outcome": "completed",
        "screenshots": [{"screenshot_id": "screen", "png_base64": image}],
        "interfaces": [
            {
                "interface_id": "scrollable",
                "screenshot_id": "screen",
                "meaning": "A native scroll pane is visible",
                "regions": [
                    {
                        "region_id": "scroll-pane",
                        "bbox": [2.0, 3.0, 20.0, 12.0],
                        "name": "Scroll pane",
                        "meaning": "scroll the reviewed pane",
                    }
                ],
            }
        ],
        "relationships": [],
        "steps": [
            {
                "step_id": "scroll-once",
                "action_type": "scroll_region",
                "target_region_id": "scroll-pane",
                "scroll_parameters": deepcopy(_SCROLL_PARAMETERS),
                "start_state": "scrollable",
                "arrival_state": "scrollable",
                "prerequisites": [],
                "expected_result": "The reviewed pane has moved down",
                "stop_condition": "stop after one reviewed wheel action",
            }
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
    def read_identity(self, target_window_handle: int) -> dict:
        return {
            "contract_version": "windows_native_identity_observation_v1",
            "provider": "windows_native_identity",
            "status": "observed",
            "target_window_handle": target_window_handle,
            "process_id": 9001,
            "process_create_time": 1000.5,
            "executable_path": r"d:\lonlife\lonlife_acc.exe",
        }


class _AllowedVisibility:
    def check(self, **_kwargs: object) -> dict:
        return {
            "bound_window_handle": 4242,
            "point_visibility": {"allowed": True},
        }


class _FakeScrollInput:
    """记录真实后端请求，绝不触及 Windows 输入边界。"""

    def __init__(self) -> None:
        self.scroll_calls: list[dict[str, object]] = []

    def scroll_window(
        self, *, direction: str, wheel_clicks: int, x: int, y: int
    ) -> dict[str, object]:
        self.scroll_calls.append(
            {
                "direction": direction,
                "wheel_clicks": wheel_clicks,
                "x": x,
                "y": y,
            }
        )
        return {
            "scrolled": True,
            "direction": direction,
            "wheel_clicks": wheel_clicks,
            "wheel_delta": -120 * wheel_clicks,
            "window_handle": 4242,
        }


class _ScrollEffectScreenshotService(_SequencedScreenshotService):
    """仅在 fake 滚轮已执行后改变已审核容器的像素。"""

    def __init__(
        self,
        root: Path,
        *,
        input_boundary: _FakeScrollInput,
        visual_effect: bool,
        repaint_after_post_scroll_capture: int = 1,
    ) -> None:
        super().__init__(root, colors=[(1, 20, 30)] * 12)
        self._input_boundary = input_boundary
        self._visual_effect = visual_effect
        self._repaint_after_post_scroll_capture = repaint_after_post_scroll_capture
        self.post_scroll_captures = 0

    def capture_window(self, **kwargs: object) -> dict[str, object]:
        result = super().capture_window(**kwargs)
        if self._input_boundary.scroll_calls:
            self.post_scroll_captures += 1
        if (
            self._visual_effect
            and self.post_scroll_captures >= self._repaint_after_post_scroll_capture
        ):
            with Image.open(str(result["image_path"])) as image:
                changed = image.copy()
            for x in range(40, 160):
                for y in range(50, 90):
                    changed.putpixel((x, y), (200, 20, 30))
            changed.save(str(result["image_path"]))
        return result


def _compile_scroll_asset(tmp_path: Path) -> tuple[ReviewedWorkflowAssetStore, dict]:
    store, _, facade, workspace = _new_runtime(tmp_path, _scroll_batch())
    try:
        prepared = facade.prepare_exact_review(
            "task", "exact-review-batch", workspace["revision"], deepcopy(_BINDING)
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
        return assets, assets.load_active(next(iter(active)))
    finally:
        facade.close()
        store.close()


def _runtime(
    tmp_path: Path,
    *,
    visual_effect: bool = True,
    repaint_after_post_scroll_capture: int = 1,
) -> SimpleNamespace:
    assets, asset = _compile_scroll_asset(tmp_path)
    manager = _BoundWindowManager()
    input_boundary = _FakeScrollInput()
    screenshot = _ScrollEffectScreenshotService(
        assets.project_root,
        input_boundary=input_boundary,
        visual_effect=visual_effect,
        repaint_after_post_scroll_capture=repaint_after_post_scroll_capture,
    )
    recognition = _SequencedRecognitionRunner(
        [_state_payloads(asset, asset["entry_state_id"])] * 8
    )
    evidence = ExistingWindowsCurrentEvidenceAdapter(
        project_root=assets.project_root,
        application_identity_key="native:lonlife_acc.exe:lonlife",
        screenshot_service=screenshot,
        window_manager=manager,
        native_identity_reader=_NativeIdentityReader(),
        recognition_runner=recognition,
        uia_provider=_UIAProvider(),
    )
    receipts = RuntimeReceiptStore(project_root=assets.project_root)
    claims = RuntimeIntentClaimStore(project_root=assets.project_root, receipt_store=receipts)
    backend = ExistingWindowsBackendAdapter(
        input_controller=input_boundary, window_manager=manager
    )

    def build(binding):
        return LiveController(
            binding=binding,
            asset_loader=assets,
            observation_source=evidence,
            target_resolver=evidence,
            gate=ReviewedWorkflowGateAdapter(),
            window_visibility_checker=ExistingWindowsCurrentEvidenceVisibilityChecker(
                evidence_adapter=evidence, delegate=_AllowedVisibility()
            ),
            backend=backend,
            intent_claim_store=claims,
            grounding_policy={"minimum_confidence": 0.45, "minimum_score_margin": 0.06},
        )

    service = LocalAgentRuntimeCallsite(
        project_root=assets.project_root,
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
        screenshot=screenshot,
        input_boundary=input_boundary,
    )


def _request(observation) -> AgentRuntimeIntentRequest:
    action = next(
        action
        for action in observation.available_actions
        if action.semantic_action == "scroll_region"
    )
    return AgentRuntimeIntentRequest(
        intent_id="intent.scroll-region",
        session_id=observation.session_id,
        observation_id=observation.observation_id,
        action_id=action.action_id,
    )


def test_native_scroll_roundtrip_reviews_confirms_dispatches_once_and_rereads_result(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    observation = runtime.service.start_session()
    request = _request(observation)

    preview = runtime.service.prepare_grounded_review(request)
    assert preview.to_dict()["status"] == "prepared"
    assert runtime.input_boundary.scroll_calls == []

    pending = runtime.service.request_grounded_confirmation(request)
    confirmation_id = pending.grounded_confirmation.confirmation_id
    assert pending.phase == "grounded_confirmation_pending"
    assert runtime.input_boundary.scroll_calls == []

    host = DesktopReviewHost(
        tmp_path / "host-inbox.json",
        tmp_path / "host-reviews",
        "native-scroll-reviewer",
        port=0,
    )
    operation_error: BaseException | None = None
    try:
        host.start()
        host.attach_grounded_runtime(runtime.service, confirmation_id=confirmation_id)
        learning = host.connections.create_connection("native-scroll", "synthetic")
        status, denied = _post(
            host.status()["base_url"] + "/action/execute_recognition_plan",
            learning["token"],
            {"confirmation_id": confirmation_id},
        )
        assert status == 401
        assert denied["error"]["result_unknown"] is False
        assert runtime.input_boundary.scroll_calls == []

        runtime.service.decide_grounded_confirmation(
            confirmation_id=confirmation_id, decision="approved"
        )
        response = host.single_step.execute(confirmation_id=confirmation_id)
        assert response["kind"] == "receipt", response["payload"]
        receipt = RuntimeResultReceiptV1.model_validate(response["payload"])
        assert receipt.outcome == "VERIFIED"
        assert receipt.next_observation_id is not None
        assert len(runtime.input_boundary.scroll_calls) == 1
        assert runtime.input_boundary.scroll_calls == [
            {"direction": "down", "wheel_clicks": 2, "x": 100, "y": 70}
        ]
        assert receipt.action.semantic_action == "scroll_region"
        assert receipt.action.scroll_parameters == _SCROLL_PARAMETERS
        verification = runtime.receipts.resolve_verification_evidence(receipt.receipt_id)
        spatial = verification["scroll_spatial_evidence"]
        assert spatial["status"] == "target_visual_change"
        assert spatial["direction_verified"] is None
        claim = runtime.claims.get_for_grounded_confirmation(
            confirmation_id=confirmation_id
        )
        checkpoint = claim.verification_checkpoint
        assert checkpoint is not None
        assert checkpoint.scroll_capture is not None
        assert checkpoint.scroll_capture["capture_id"] == checkpoint.current_observation["capture_id"]
        assert checkpoint.scroll_capture["image_sha256"] == checkpoint.current_observation["screenshot_sha256"]

        reread = runtime.receipts.resolve_next_observation(receipt.receipt_id)
        assert reread.observation_id == receipt.next_observation_id
        repeated = host.single_step.execute(confirmation_id=confirmation_id)
        assert repeated == response
        assert len(runtime.input_boundary.scroll_calls) == 1
    except BaseException as error:
        operation_error = error
        raise
    finally:
        try:
            host.close()
        except Exception:
            if operation_error is None:
                raise


def test_native_scroll_no_visual_effect_is_verified_failed_without_redispatch(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path, visual_effect=False)
    observation = runtime.service.start_session()
    request = _request(observation)
    assert runtime.service.prepare_grounded_review(request).to_dict()["status"] == "prepared"
    pending = runtime.service.request_grounded_confirmation(request)
    confirmation_id = pending.grounded_confirmation.confirmation_id

    host = DesktopReviewHost(
        tmp_path / "host-inbox.json",
        tmp_path / "host-reviews",
        "native-scroll-no-effect-reviewer",
        port=0,
    )
    operation_error: BaseException | None = None
    try:
        host.start()
        host.attach_grounded_runtime(runtime.service, confirmation_id=confirmation_id)
        runtime.service.decide_grounded_confirmation(
            confirmation_id=confirmation_id, decision="approved"
        )
        response = host.single_step.execute(confirmation_id=confirmation_id)
        assert response["kind"] == "receipt", response["payload"]
        receipt = RuntimeResultReceiptV1.model_validate(response["payload"])
        assert receipt.outcome == "VERIFICATION_FAILED"
        assert receipt.reason_code == "scroll_no_visual_change"
        assert receipt.next_observation_id is None
        assert len(runtime.input_boundary.scroll_calls) == 1
        verification = runtime.receipts.resolve_verification_evidence(receipt.receipt_id)
        spatial = verification["scroll_spatial_evidence"]
        assert spatial["status"] == "no_visual_change"
        assert spatial["direction_verified"] is None
        assert host.single_step.execute(confirmation_id=confirmation_id) == response
        assert len(runtime.input_boundary.scroll_calls) == 1
    except BaseException as error:
        operation_error = error
        raise
    finally:
        try:
            host.close()
        except Exception:
            if operation_error is None:
                raise


def test_native_scroll_delayed_target_repaint_is_verified_with_one_dispatch(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path, repaint_after_post_scroll_capture=2)
    observation = runtime.service.start_session()
    request = _request(observation)
    assert runtime.service.prepare_grounded_review(request).to_dict()["status"] == "prepared"
    pending = runtime.service.request_grounded_confirmation(request)
    confirmation_id = pending.grounded_confirmation.confirmation_id

    host = DesktopReviewHost(
        tmp_path / "host-inbox.json",
        tmp_path / "host-reviews",
        "native-scroll-delayed-repaint-reviewer",
        port=0,
    )
    operation_error: BaseException | None = None
    try:
        host.start()
        host.attach_grounded_runtime(runtime.service, confirmation_id=confirmation_id)
        runtime.service.decide_grounded_confirmation(
            confirmation_id=confirmation_id, decision="approved"
        )
        response = host.single_step.execute(confirmation_id=confirmation_id)
        assert response["kind"] == "receipt", response["payload"]
        receipt = RuntimeResultReceiptV1.model_validate(response["payload"])
        assert receipt.outcome == "VERIFIED"
        assert runtime.screenshot.post_scroll_captures == 2
        assert len(runtime.input_boundary.scroll_calls) == 1
    except BaseException as error:
        operation_error = error
        raise
    finally:
        try:
            host.close()
        except Exception:
            if operation_error is None:
                raise
