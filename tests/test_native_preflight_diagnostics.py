from __future__ import annotations

from types import SimpleNamespace

from app.desktop_review.window import ensure_application
from app.desktop_review.single_step_dialog import SingleStepDialog
from test_desktop_single_step_dialog import _Coordinator, _click
from test_native_single_step_coordinator import _Host, _Runtime, _Windows, _coordinator


def _selection():
    return {
        "asset_id": "asset-1",
        "asset_content_sha256": "c" * 64,
        "target_window_handle": 41,
        "target_process_id": 7,
    }


def test_prepare_exposes_actual_safe_stop_preflight_diagnostic():
    runtime, windows, host = _Runtime(), _Windows(), _Host()
    runtime.observation.available_actions = (
        SimpleNamespace(action_id="runtime.safe_stop", semantic_action="safe_stop", target_state_id=None),
    )
    runtime.observation.safe_stop = SimpleNamespace(required=True, reason_code="no_available_action")
    runtime.observation.state = SimpleNamespace(status="matched", state_id="state-1")
    runtime.observation.current_capture = SimpleNamespace(capture_id="capture-1")
    runtime.observation.blockers = (
        SimpleNamespace(blocker_id="blocker.no_available_action", description="No reviewed action is available."),
    )
    coordinator = _coordinator(runtime, windows, host, lambda: None, lambda: None)
    try:
        result = coordinator.prepare(**_selection())
        assert result["actions"] == []
        assert result["diagnostic"] == {
            "contract_version": "native_preflight_diagnostic_v1",
            "status": "available",
            "safe_stop_reason_code": "no_available_action",
            "state_status": "matched",
            "state_id": "state-1",
            "capture_id": "capture-1",
            "blockers": [{
                "reason_code": "blocker.no_available_action",
                "description": "No reviewed action is available.",
            }],
            "artifact_is_authorization": False,
        }
    finally:
        coordinator.cancel()
        coordinator.shutdown()


def test_prepare_marks_legacy_observation_diagnostic_unavailable():
    runtime, windows, host = _Runtime(), _Windows(), _Host()
    runtime.observation.available_actions = (
        SimpleNamespace(action_id="runtime.safe_stop", semantic_action="safe_stop", target_state_id=None),
    )
    coordinator = _coordinator(runtime, windows, host, lambda: None, lambda: None)
    try:
        result = coordinator.prepare(**_selection())
        assert result["diagnostic"] == {
            "contract_version": "native_preflight_diagnostic_v1",
            "status": "unavailable",
            "unavailable_reason_code": "observation_diagnostic_fields_unavailable",
            "artifact_is_authorization": False,
        }
    finally:
        coordinator.cancel()
        coordinator.shutdown()


def test_dialog_shows_unavailable_diagnostic_for_empty_legacy_prepare_result():
    class EmptyLegacyCoordinator(_Coordinator):
        def prepare(self, **selection):
            result = super().prepare(**selection)
            result["actions"] = []
            return result

    ensure_application()
    dialog = SingleStepDialog(EmptyLegacyCoordinator())
    dialog.show()
    _click(dialog.refresh_button, dialog)
    dialog.asset_selector.setCurrentIndex(0)
    dialog.window_selector.setCurrentIndex(0)
    _click(dialog.prepare_button, dialog)
    try:
        assert dialog.action_selector.count() == 0
        assert not dialog.review_button.isEnabled()
        assert "诊断不可用" in dialog.status_label.text()
        assert "observation_diagnostic_fields_unavailable" in dialog.status_label.text()
    finally:
        _click(dialog.cancel_button, dialog)
        dialog.close()


def test_dialog_keeps_normal_actions_reviewable_when_diagnostic_is_unavailable():
    ensure_application()
    dialog = SingleStepDialog(_Coordinator())
    dialog.show()
    _click(dialog.refresh_button, dialog)
    dialog.asset_selector.setCurrentIndex(0)
    dialog.window_selector.setCurrentIndex(0)
    _click(dialog.prepare_button, dialog)
    try:
        assert dialog.action_selector.count() == 1
        dialog.action_selector.setCurrentIndex(0)
        assert dialog.review_button.isEnabled()
        assert "当前没有可执行动作" not in dialog.status_label.text()
    finally:
        _click(dialog.cancel_button, dialog)
        dialog.close()


def test_dialog_renders_available_state_unknown_zero_action_diagnostic_and_keeps_release_enabled():
    class StateUnknownCoordinator(_Coordinator):
        def prepare(self, **selection):
            result = super().prepare(**selection)
            result["actions"] = []
            result["diagnostic"] = {
                "contract_version": "native_preflight_diagnostic_v1",
                "status": "available",
                "safe_stop_reason_code": "state_unknown",
                "state_status": "unknown",
                "state_id": None,
                "capture_id": "capture-current-1",
                "blockers": [{
                    "reason_code": "blocker.state_unknown",
                    "description": "Runtime requires safe stop: state_unknown.",
                }],
                "artifact_is_authorization": False,
            }
            return result

    ensure_application()
    dialog = SingleStepDialog(StateUnknownCoordinator())
    dialog.show()
    _click(dialog.refresh_button, dialog)
    dialog.asset_selector.setCurrentIndex(0)
    dialog.window_selector.setCurrentIndex(0)
    _click(dialog.prepare_button, dialog)
    try:
        assert "无法确认当前界面状态" in dialog.status_label.text()
        assert "state_unknown" in dialog.status_label.text()
        assert dialog.receipt_text.isReadOnly()
        assert '"status": "available"' in dialog.receipt_text.toPlainText()
        assert "capture-current-1" in dialog.receipt_text.toPlainText()
        assert not dialog.review_button.isEnabled()
        assert not dialog.approve_button.isEnabled()
        assert not dialog.execute_button.isEnabled()
        assert dialog.cancel_button.isEnabled()
    finally:
        _click(dialog.cancel_button, dialog)
        dialog.close()
