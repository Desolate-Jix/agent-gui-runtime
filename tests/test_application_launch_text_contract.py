"""启动预览不得让排版控制符改变人工所见命令。"""
import pytest

from app.agent_link.contracts import AgentLinkError
from app.desktop_review.application_startup import _url
from app.desktop_review.application_startup_dialog import ApplicationStartupDialog
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinatorError
from app.desktop_review.window import ensure_application
from PySide6.QtWidgets import QMessageBox
from tests.test_catalog_window_preparation import catalog_host
from tests.test_window_preparation_authority import scene
from tests.test_native_application_startup_dialog import _Provider


@pytest.mark.parametrize("codepoint", [0x7f, 0x85, 0x202e, 0x2028, 0x2029, 0x2066, 0x200b])
def test_agent_url_rejects_display_controls(codepoint):
    with pytest.raises(AgentLinkError):
        _url("https://example.org/" + chr(codepoint) + "suffix")


@pytest.mark.parametrize("codepoint", [0x202e, 0x2028])
def test_catalog_preview_rejects_display_controls_without_launch(catalog_host, codepoint):
    coordinator, _catalog, launched, _state, _exe = catalog_host
    with pytest.raises(NativeSingleStepCoordinatorError):
        coordinator.preview_application_launch(app_id="fixture", url="https://example.org/" + chr(codepoint))
    assert launched == []


def test_untrusted_task_label_is_escaped_in_request_table():
    ensure_application()
    provider = _Provider()
    dialog = ApplicationStartupDialog(provider, auto_refresh=False)
    try:
        requests = provider.list_requests()
        requests[0]["task_id"] = "地图\u202e测试"
        dialog._render(requests)
        assert dialog.requests.item(0, 1).text() == "地图\\u202e测试"
        assert provider.confirmed == []
    finally:
        dialog.close()
        dialog.deleteLater()


def test_normal_chinese_url_is_preserved():
    assert _url("https://example.org/地图?q=博物馆") == "https://example.org/地图?q=博物馆"


def test_preview_and_confirmation_escape_controls_without_losing_chinese(monkeypatch):
    ensure_application()
    provider = _Provider()
    dialog = ApplicationStartupDialog(provider, auto_refresh=False)
    seen = []
    def cancel(box):
        seen.append(box.text())
        assert box.defaultButton() == box.button(QMessageBox.StandardButton.Cancel)
        return QMessageBox.StandardButton.Cancel
    monkeypatch.setattr(QMessageBox, "exec", cancel)
    try:
        dialog._render(provider.list_requests())
        dialog.requests.selectRow(0)
        preview = provider.preview("request-1")
        preview["name"] = "地图\u202e应用"
        dialog._operation = "preview"
        dialog._succeeded(dialog._request_id, preview)
        dialog._controls()
        assert "地图\\u202e应用" in dialog.preview_text.toPlainText()
        assert "\u202e" not in dialog.preview_text.toPlainText()
        dialog.confirm()
        assert len(seen) == 1 and "地图\\u202e应用" in seen[0] and "\u202e" not in seen[0]
        assert provider.confirmed == []
    finally:
        dialog.close()
        dialog.deleteLater()
