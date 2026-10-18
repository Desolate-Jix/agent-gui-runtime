from copy import deepcopy
from hashlib import sha256
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.agent.live_runtime_composition import ExistingWindowsCurrentEvidenceAdapter
from app.agent.native_identity import asset_application_identity_key
from app.agent.reviewed_workflow_gate import ReviewedWorkflowGateAdapter
from app.agent.reviewed_workflow_replay import resolve_current_state, select_transition_for_review, validate_review_grounding_preview
from app.desktop_review.window import ReviewMainWindow, ensure_application
from test_desktop_exact_review import _batch, _complete, _load, _new_runtime, _record_dir
from test_desktop_review_window import _wait_loaded, _wait_workers
from test_desktop_scroll_review import PARAMETERS
from tests.test_live_runtime_composition_w3b import _RecognitionRunner, _ScreenshotService, _UIAProvider, _entry_payloads
from tests.test_native_current_evidence import _NativeIdentityReader, _StableWindowManager


def test_developer_batch_scroll_edit_save_compile_and_current_scroll_preview(tmp_path):
    batch = _batch(action_type="scroll_region")
    batch["steps"][0]["scroll_parameters"] = deepcopy(PARAMETERS)
    store, _, facade, initial = _new_runtime(tmp_path, batch)
    application = ensure_application()
    window = ReviewMainWindow(facade)
    window.show()
    # 默认入口是新学内容；开发者批次编辑必须先切换到实际可见的批次页。
    assert window.show_inbox()
    window.load_batch("task", "exact-review-batch")
    try:
        _wait_loaded(window)
        _wait_workers(window)
        window.step_table.selectRow(0)
        application.processEvents()
        window.scroll_direction.setCurrentIndex(window.scroll_direction.findData("up"))
        window.scroll_wheel_clicks.setValue(4)
        window.save_current()
        _wait_workers(window)
        saved = facade.load_batch("task", "exact-review-batch")
        expected = {**PARAMETERS, "direction": "up", "wheel_clicks": 4}
        assert saved["revision"] == initial["revision"] + 1
        assert saved["batch"]["steps"][0]["scroll_parameters"] == expected

        executable = r"C:\Windows\System32\notepad.exe"
        prepared = facade.prepare_exact_review("task", "exact-review-batch", saved["revision"],
            {"kind": "native", "display_name": "Notepad", "executable_identity": executable, "product_name": "Notepad"})
        compiled = _complete(facade, prepared)
        assert compiled["status"] == "compiled", compiled
        receipt = _load(_record_dir(tmp_path / "root") / f"receipt-{compiled['compile_receipt_id']}.json")
        asset = receipt["asset"]
        transition = next(item for item in asset["transitions"] if item["semantic_action"] == "scroll_region")
        assert transition["scroll_parameters"] == expected

        screenshot = _ScreenshotService(tmp_path)
        adapter = ExistingWindowsCurrentEvidenceAdapter(
            project_root=tmp_path, application_identity_key=asset_application_identity_key(asset["application"]),
            screenshot_service=screenshot, window_manager=_StableWindowManager(),
            native_identity_reader=_NativeIdentityReader(executable_path=executable),
            recognition_runner=_RecognitionRunner(_entry_payloads(asset)), uia_provider=_UIAProvider(),
        )
        current = adapter.capture_current(session_id="native-scroll-review", asset=asset, target_window_handle=4242)
        assert current["screenshot_sha256"] == sha256(screenshot.paths[0].read_bytes()).hexdigest()
        resolution = resolve_current_state(asset, current)
        selection = select_transition_for_review(asset, resolution, transition_id=transition["transition_id"], current_observation=current)
        assert selection["status"] == "selected", selection
        resolved = adapter.resolve(session_id="native-scroll-review", selection=selection, current_observation=current)
        assert resolved["status"] == "resolved", resolved
        gate = ReviewedWorkflowGateAdapter().evaluate_review(selection=selection, grounding=resolved["grounding"], **resolved["gate_context"])
        preview = validate_review_grounding_preview(asset, selection, resolved["grounding"], gate,
            policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2})
        assert preview["status"] == "validated", preview
        assert preview["scroll_parameters"] == expected
        assert preview["reviewed_revision_hash"] == selection["reviewed_revision_hash"]
        assert preview["review_only"] is True
        capture_path = os.environ.get("R7H_REVIEW_SCREENSHOT")
        if capture_path:
            window.grab().save(capture_path)
    finally:
        _wait_workers(window)
        window._dirty = False
        window.close()
        application.processEvents()
        store.close()
