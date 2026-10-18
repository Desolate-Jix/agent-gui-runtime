from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from app.agent.desktop_backend import DeterministicFakeBackend
from app.agent.live_controller import LiveController
from app.agent.live_runtime_composition import ExistingWindowsCurrentEvidenceAdapter
from app.agent.reviewed_workflow_asset import ReviewedWorkflowAssetStore, content_sha256
from app.agent.reviewed_workflow_gate import ReviewedWorkflowGateAdapter
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from app.agent.runtime_session_selection import RuntimeSessionSelection
from app.api.agent_runtime import LocalAgentRuntimeCallsite
from app.desktop_review.host import DesktopReviewHost
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator
from app.desktop_review.single_step_dialog import SingleStepDialog
from app.desktop_review.window import ensure_application
from app.desktop_review.workspace import NativeReviewFacade
from tests.test_desktop_exact_review import _batch, _complete, _new_runtime, _record_dir, _load
from tests.test_live_controller_w4 import _WindowVisibilityChecker
from tests.test_live_runtime_composition_w3b import (
    _RecognitionRunner,
    _ScreenshotService,
    _UIAProvider,
    _bound,
    _recognition,
)
from tests.test_native_current_evidence import _NativeIdentityReader
from tests.test_desktop_single_step_dialog import _click, _idle, _wait
from tests.text_field_fixture_support import SyntheticTextFieldReader

_SYNTHETIC_NATIVE_BINDING = {
    "kind": "native",
    "display_name": "Synthetic Editor",
    "executable_identity": r"D:\Synthetic\editor.exe",
    "product_name": "Notepad",
}


def _coherent_text_entry_payloads(asset: dict) -> dict[str, dict]:
    state = next(item for item in asset["states"] if item["state_id"] == asset["entry_state_id"])
    interface_anchor = next(item for item in state["identity_anchors"] if not item.get("text_field_id"))
    field_anchor = next(item for item in state["identity_anchors"] if item.get("text_field_id") == "open")
    return {
        interface_anchor["label"]: _recognition(
            interface_anchor["label"], role="text", candidate_id="candidate-reviewed-interface",
            element_id="current-reviewed-interface",
        ),
        field_anchor["label"]: _recognition(
            field_anchor["label"], role="input", candidate_id="candidate-reviewed-text-field",
            element_id="current-reviewed-text-field",
        ),
    }


@pytest.mark.parametrize(
    ("kind", "expected", "parameters"),
    [
        (
            "literal",
            "你好\r\n固定来源",
            {"kind": "literal", "text": "你好\r\n固定来源"},
        ),
        (
            "variable",
            "用户输入\n第二行",
            {"kind": "variable", "name": "query_text"},
        ),
    ],
)
def test_saved_native_text_asset_reopens_compiles_and_reaches_actual_preview(
    tmp_path: Path, kind: str, expected: str, parameters: dict
) -> None:
    ensure_application()
    batch = _batch(action_type="fill_field")
    batch["interfaces"][0]["recognition_text"] = "Synthetic editor surface"
    text_parameters = {
        "contract_version": "reviewed_text_parameters_v1",
        "target_field_id": "open",
        "content": parameters,
        "clear_existing": True,
        "sensitive": False,
        "submit": False,
        "clipboard_policy": "restore_previous",
    }
    batch["steps"][0]["text_parameters"] = copy.deepcopy(text_parameters)

    store, service, facade, workspace = _new_runtime(tmp_path, batch)
    review_root = tmp_path / "root"
    try:
        # 关闭原宿主后重新打开同一份已保存来源。
        facade.close()
        facade = None
        reopened = NativeReviewFacade(service, "exact-review-token", review_root)
        loaded = reopened.load_batch("task", "exact-review-batch")
        assert loaded["revision"] == workspace["revision"]
        prepared = reopened.prepare_exact_review(
            "task", "exact-review-batch", loaded["revision"], copy.deepcopy(_SYNTHETIC_NATIVE_BINDING)
        )
        compiled = _complete(reopened, prepared)
        assert compiled["status"] == "compiled", compiled
        receipt = _load(_record_dir(review_root) / f"receipt-{compiled['compile_receipt_id']}.json")
        exact_asset = receipt["asset"]
        published = reopened.publish_exact_review(compiled["compile_receipt_id"])
        assert published["content_sha256"] == content_sha256(exact_asset)
        assert reopened.load_batch("task", "exact-review-batch")["batch"] == loaded["batch"]
        active = ReviewedWorkflowAssetStore(project_root=review_root).load_active(exact_asset["asset_id"])
        assert content_sha256(active) == content_sha256(exact_asset)
        bound = _bound()
        bound.is_active = True
        bound.title = "Synthetic Notepad"
        bound.process_name = "editor.exe"
        windows = SimpleNamespace(
            get_bound_window=lambda: bound,
            list_visible_windows=lambda: [vars(bound)],
            bind_window_by_handle=lambda _handle: bound,
        )
        capture_root = tmp_path / "captures"
        capture_root.mkdir()
        screenshot = _ScreenshotService(capture_root)
        runner = _RecognitionRunner(_coherent_text_entry_payloads(exact_asset))
        adapter = ExistingWindowsCurrentEvidenceAdapter(
            project_root=review_root,
            application_identity_key="native:editor.exe:notepad",
            screenshot_service=screenshot,
            window_manager=windows,
            native_identity_reader=_NativeIdentityReader(
                executable_path=r"d:\synthetic\editor.exe"
            ),
            recognition_runner=runner,
            uia_provider=_UIAProvider(),
            text_field_reader=SyntheticTextFieldReader(),
        )
        claims = RuntimeIntentClaimStore(
            project_root=tmp_path,
            receipt_store=RuntimeReceiptStore(project_root=tmp_path),
        )
        backend = DeterministicFakeBackend()
        controllers = []

        def build(binding):
            controller = LiveController(
                binding=binding,
                asset_loader=ReviewedWorkflowAssetStore(project_root=review_root),
                observation_source=adapter,
                target_resolver=adapter,
                gate=ReviewedWorkflowGateAdapter(),
                backend=backend,
                window_visibility_checker=_WindowVisibilityChecker(bound_window_handle=4242),
                intent_claim_store=claims,
                grounding_policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2},
            )
            controllers.append(controller)
            return controller

        service_runtime = LocalAgentRuntimeCallsite(
            project_root=tmp_path,
            asset_store=ReviewedWorkflowAssetStore(project_root=review_root),
            claim_store=claims,
            window_manager=windows,
            controller_factory=build,
            selection=RuntimeSessionSelection(
                exact_asset["asset_id"], content_sha256(exact_asset), 4242, 9001
            ),
        )
        factory = lambda **_kwargs: service_runtime
        factory.window_manager = windows
        facade_view = SimpleNamespace(list_reviewed_assets=reopened.list_reviewed_assets)
        host = DesktopReviewHost(
            tmp_path / "host.sqlite", tmp_path / "review", "saved-native-token", port=0
        )
        host.start()
        coordinator = NativeSingleStepCoordinator(
            tmp_path,
            facade_view,
            host,
            runtime_factory=factory,
            thread_initializer=lambda: None,
            thread_finalizer=lambda: None,
            foreground_timeout=0.1,
        )
        dialog = SingleStepDialog(coordinator)
        dialog.show()
        try:
            _click(dialog.refresh_button, dialog)
            dialog.asset_selector.setCurrentIndex(0)
            dialog.window_selector.setCurrentIndex(0)
            _click(dialog.prepare_button, dialog)
            assert dialog._phase == "observed", dialog.status_label.text()
            dialog.action_selector.setCurrentIndex(0)
            _click(dialog.review_button, dialog)
            _wait(lambda: getattr(dialog, "_text_input_dialog", None) is not None)
            editor = dialog._text_input_dialog
            if kind == "variable":
                editor.text_editor.setPlainText(expected)
            else:
                assert editor.text_editor.toPlainText() == expected.replace("\r\n", "\n")
                assert editor.text_editor.isReadOnly()
            QTest.mouseClick(editor.continue_button, Qt.MouseButton.LeftButton)
            _idle(dialog)
            assert dialog.preview_widget.review["text_input_local"].text == expected
            assert dialog.preview_widget.text_value_editor.toPlainText() == expected.replace("\r\n", "\n")
            assert dialog.preview_widget.text_value_editor.isReadOnly()
            assert backend.attempt_count == 0
            _click(dialog.approve_button, dialog)
            assert dialog.preview_widget.review["phase"] == "approved"
            assert backend.attempt_count == 0
            _click(dialog.cancel_button, dialog)
            assert coordinator._runtime is None
            assert claims.list_unresolved_claims() == ()
        finally:
            dialog.close()
            _idle(dialog)
            coordinator.shutdown()
            host.close()
            for controller in controllers:
                for session_id in list(controller._sessions):
                    controller.abandon_session(session_id=session_id)
    finally:
        if facade is not None:
            facade.close()
        store.close()
