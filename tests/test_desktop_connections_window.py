from __future__ import annotations

import copy
import http.client
import json
import os
from pathlib import Path
import sys
import threading
import time

import pytest
from PySide6.QtCore import Qt, QTimer, QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox

from app.desktop_review.window import ReviewMainWindow, ensure_application
from test_desktop_relearn_window import _wait
from test_desktop_review_window import _Facade


class _Connections:
    def __init__(self):
        self.records = []
        self.created = []
        self.revocations = []
        self.failure = False
        self.response_mutation = None
        self.hold = None
        self.host = {"contract_version": "native_review_host_v1", "host_id": "host-test",
                     "phase": "ready", "base_url": "http://127.0.0.1:49123", "staging_only": True}

    def host_status(self):
        return copy.deepcopy(self.host)

    def list_connections(self):
        if self.hold is not None:
            self.hold.wait(4)
        return copy.deepcopy(self.records)

    def create_connection(self, task_id, agent_name):
        self.created.append((task_id, agent_name))
        if self.failure:
            raise RuntimeError("synthetic-secret-must-not-be-rendered")
        item = {"connection_id": "connection-new", "task_id": task_id,
                "agent_name": agent_name, "revoked": False, "created_at": 123456789}
        self.records.append(item)
        result = {key: item[key] for key in ("connection_id", "task_id", "agent_name")}
        result.update(contract_version="agent_link_v1", staging_only=True, token="synthetic-agent-secret-123456")
        if self.response_mutation:
            self.response_mutation(result)
        return result

    def revoke_connection(self, connection_id, idempotency_key):
        self.revocations.append((connection_id, idempotency_key))
        for record in self.records:
            if record["connection_id"] == connection_id:
                record["revoked"] = True
        return {"contract_version": "agent_link_v1", "connection_id": connection_id,
                "status": "revoked", "staging_only": True}


def _ready(controller=None):
    from app.desktop_review.connection_dialog import ConnectionManagerDialog
    application = ensure_application()
    controller = controller or _Connections()
    dialog = ConnectionManagerDialog(controller)
    dialog.show()
    _wait(lambda: dialog.snapshot is not None and not dialog._jobs)
    return application, controller, dialog


def _draft(dialog):
    dialog.task_id.setText("task-native")
    dialog.agent_name.setText("合成 MCP 客户端")


def _close(dialog):
    _wait(lambda: not dialog._jobs)
    dialog.clear_secret()
    dialog.close()
    ensure_application().processEvents()


def test_native_connection_create_masked_credentials_copy_and_authorization_status():
    application, controller, dialog = _ready()
    try:
        _draft(dialog)
        QTest.mouseClick(dialog.create_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert controller.created == [("task-native", "合成 MCP 客户端")]
        assert dialog.token.echoMode() == QLineEdit.EchoMode.Password
        assert dialog.token.text() == "synthetic-agent-secret-123456"
        assert "synthetic-agent-secret" not in dialog.config_preview.toPlainText()
        dialog.config_format.setCurrentIndex(1)
        QTest.mouseClick(dialog.copy_config_button, Qt.MouseButton.LeftButton)
        config = json.loads(QApplication.clipboard().text())
        assert config["env"] == {"AGENT_LINK_BASE_URL": controller.host["base_url"], "AGENT_LINK_TOKEN": dialog.token.text()}
        assert "REVIEWER" not in json.dumps(config)
        assert not dialog.task_id.text() and not dialog.agent_name.text()
        assert dialog.table.rowCount() == 1
        assert "不代表在线" in dialog.table.item(0, 3).text()
        assert "未验证" in dialog.host_label.text()
    finally:
        QApplication.clipboard().clear()
        _close(dialog)


@pytest.mark.parametrize("mutation", [
    lambda result: result.update(task_id="wrong-task"),
    lambda result: result.update(staging_only=False),
    lambda result: result.update(reviewer_token="must-not-leak"),
])
def test_invalid_create_receipt_keeps_draft_and_requires_manual_recovery(mutation):
    application, controller, dialog = _ready()
    try:
        controller.response_mutation = mutation
        _draft(dialog)
        QTest.mouseClick(dialog.create_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert dialog.task_id.text() == "task-native"
        assert not dialog.token.text()
        assert not dialog.create_button.isEnabled()
        assert len(controller.created) == 1
        QTest.mouseClick(dialog.refresh_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert not dialog.create_button.isEnabled()
        assert dialog.recovery_checked.isEnabled()
        assert len(controller.created) == 1
    finally:
        _close(dialog)


def test_create_failure_is_redacted_without_automatic_mint_retry():
    application, controller, dialog = _ready()
    try:
        controller.failure = True
        _draft(dialog)
        QTest.mouseClick(dialog.create_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert len(controller.created) == 1
        assert "synthetic-secret" not in dialog.status.text()
        assert "不确定" in dialog.status.text()
        assert dialog.task_id.text() == "task-native"
        assert not dialog.create_button.isEnabled()
    finally:
        _close(dialog)


def test_failed_refresh_discards_cached_ready_and_disables_credential_copy():
    class LostReceiver(_Connections):
        unavailable = False

        def list_connections(self):
            if self.unavailable:
                raise RuntimeError("synthetic-read-error-must-not-be-rendered")
            return super().list_connections()

    application, controller, dialog = _ready(LostReceiver())
    try:
        _draft(dialog)
        QTest.mouseClick(dialog.create_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert dialog.copy_config_button.isEnabled()
        controller.unavailable = True
        QTest.mouseClick(dialog.refresh_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert dialog.snapshot is None
        assert "就绪" not in dialog.host_label.text()
        assert not dialog.copy_config_button.isEnabled() and not dialog.create_button.isEnabled()
        assert dialog.table.rowCount() == 0
        assert "synthetic-read-error" not in dialog.status.text()
        assert len(controller.created) == 1
    finally:
        _close(dialog)


def test_native_revoke_confirmation_defaults_cancel_then_persists_exact_id():
    controller = _Connections()
    controller.create_connection("task-native", "合成 MCP 客户端")
    application, controller, dialog = _ready(controller)
    try:
        dialog.table.selectRow(0)
        defaults = []
        def answer(button):
            def callback():
                prompt = application.activeModalWidget()
                if isinstance(prompt, QMessageBox):
                    defaults.append(prompt.defaultButton() == prompt.button(QMessageBox.StandardButton.Cancel))
                    QTest.mouseClick(prompt.button(button), Qt.MouseButton.LeftButton)
            return callback
        QTimer.singleShot(0, answer(QMessageBox.StandardButton.Cancel))
        QTest.mouseClick(dialog.revoke_button, Qt.MouseButton.LeftButton)
        assert controller.revocations == []
        QTimer.singleShot(0, answer(QMessageBox.StandardButton.Yes))
        QTest.mouseClick(dialog.revoke_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert defaults == [True, True]
        assert len(controller.revocations) == 1 and controller.revocations[0][0] == "connection-new"
        assert dialog.table.item(0, 3).text() == "已撤销"
        assert not dialog.revoke_button.isEnabled()
    finally:
        _close(dialog)


def test_busy_refresh_does_not_destroy_dialog_or_allow_mutation():
    application, controller, dialog = _ready()
    try:
        controller.hold = threading.Event()
        _draft(dialog)
        QTest.mouseClick(dialog.refresh_button, Qt.MouseButton.LeftButton)
        assert not dialog.create_button.isEnabled()
        dialog.close()
        application.processEvents()
        assert dialog.isVisible()
        controller.hold.set()
        _wait(lambda: not dialog._jobs)
        assert dialog.create_button.isEnabled()
    finally:
        if controller.hold is not None:
            controller.hold.set()
        _close(dialog)


def test_connection_manager_is_available_without_loaded_batch():
    application = ensure_application()
    facade = _Facade()
    window = None
    try:
        window = ReviewMainWindow(facade, connections=_Connections())
        window.show()
        _wait(lambda: not window._jobs)
        assert window.workspace is None
        assert window.connections_action.isEnabled()
    finally:
        if window is not None:
            window.close()
            application.processEvents()


def test_online_batch_refresh_never_blocks_the_qt_thread():
    application = ensure_application()
    release = threading.Event()
    class SlowFacade(_Facade):
        def list_batches(self):
            release.wait(1)
            return []
    window = None
    try:
        started = time.monotonic()
        window = ReviewMainWindow(SlowFacade(), connections=_Connections())
        assert time.monotonic() - started < 0.4
        assert window._jobs
        release.set()
        _wait(lambda: not window._jobs)
    finally:
        release.set()
        if window is not None:
            _wait(lambda: not window._jobs)
            window.close()
            application.processEvents()


def test_online_shutdown_waits_finished_before_window_closes_and_retries_failure():
    application = ensure_application()
    release = threading.Event()
    calls = []
    def shutdown():
        calls.append("close")
        if len(calls) == 1:
            raise RuntimeError("synthetic-secret-error")
        release.wait(4)
    window = ReviewMainWindow(_Facade(), connections=_Connections(), shutdown=shutdown)
    window.show()
    try:
        _wait(lambda: not window._jobs)
        window.close()
        _wait(lambda: not window._jobs)
        assert window.isVisible() and window._operation == "host_failed"
        assert "synthetic-secret" not in window.status.currentMessage()
        assert not window.connections_action.isEnabled()
        window.close()
        assert window.isVisible() and window._operation == "host_closing"
        window.close()
        assert calls.count("close") <= 2
        release.set()
        _wait(lambda: not window._jobs and not window.isVisible())
        assert calls == ["close", "close"]
    finally:
        release.set()
        _wait(lambda: not window._jobs)
        if window.isVisible():
            window.close()
            _wait(lambda: not window._jobs)


def test_startup_failure_does_not_fallback_to_editable_offline_ui():
    application = ensure_application()
    closed = []
    def startup():
        raise RuntimeError("synthetic-startup-secret")
    window = ReviewMainWindow(_Facade(), connections=_Connections(), startup=startup,
                              shutdown=lambda: closed.append(True))
    window.show()
    try:
        _wait(lambda: not window._jobs)
        assert window._operation == "host_failed"
        assert not window.batch_tree.isEnabled() and not window.connections_action.isEnabled()
        assert "synthetic-startup-secret" not in window.status.currentMessage()
        window.close()
        _wait(lambda: not window._jobs and not window.isVisible())
        assert closed == [True]
    finally:
        if window.isVisible():
            window.close()
            _wait(lambda: not window._jobs)


def test_native_launcher_documents_explicit_shared_listener_flag(monkeypatch, capsys):
    from app.desktop_review import application as desktop_application
    monkeypatch.setattr(sys, "argv", ["application.py", "--help"])
    with pytest.raises(SystemExit) as outcome:
        desktop_application.main()
    assert outcome.value.code == 0
    assert "--listen-port" in capsys.readouterr().out


def test_native_launcher_wires_actual_shared_host_without_exporting_reviewer_secret(tmp_path, monkeypatch):
    from app.desktop_review import application as desktop_application
    from app.desktop_review import host as host_module, window as window_module
    application = ensure_application()
    actual_host, actual_window = host_module.DesktopReviewHost, window_module.ReviewMainWindow
    hosts, windows, tokens = [], [], []

    class CapturedHost(actual_host):
        def __init__(self, state, root, token, **kwargs):
            tokens.append(token)
            super().__init__(state, root, token, **kwargs)
            hosts.append(self)

    def capture_window(*args, **kwargs):
        window = actual_window(*args, **kwargs)
        windows.append(window)
        return window

    class LauncherApplication:
        def exec(self):
            window = windows[0]
            _wait(lambda: window._operation == "idle" and not window._jobs)
            assert hosts[0].status()["phase"] == "ready"
            assert window._connections is hosts[0].connections
            assert window.connections_action.isEnabled()
            assert window._single_step is not None
            assert window.single_step_action.isEnabled()
            assert window._single_step._owner.thread_id is None
            assert window._single_step._project_root == (tmp_path / "review").resolve()
            window.close()
            _wait(lambda: not window._jobs and not window.isVisible())
            return 0

    monkeypatch.setenv("AGENT_LINK_REVIEWER_TOKEN", "inherited-reviewer-must-not-be-used")
    monkeypatch.setattr(sys, "argv", ["application.py", "--state-path", str(tmp_path / "inbox.json"),
                                      "--review-root", str(tmp_path / "review"), "--listen-port", "0"])
    monkeypatch.setattr(host_module, "DesktopReviewHost", CapturedHost)
    monkeypatch.setattr(window_module, "ReviewMainWindow", capture_window)
    monkeypatch.setattr(window_module, "ensure_application", lambda: LauncherApplication())
    try:
        assert desktop_application.main() == 0
        assert len(hosts) == len(tokens) == 1
        assert tokens[0] != "inherited-reviewer-must-not-be-used" and len(tokens[0]) >= 32
        assert os.environ["AGENT_LINK_REVIEWER_TOKEN"] == "inherited-reviewer-must-not-be-used"
        assert hosts[0].status()["phase"] == "stopped"
    finally:
        for window in windows:
            _wait(lambda: not window._jobs)
            window.close()
            _wait(lambda: not window._jobs)
        for host in hosts:
            host.close()
        application.processEvents()


@pytest.mark.parametrize("port", ["-1", "65536"])
def test_native_launcher_rejects_invalid_port_before_creating_state(tmp_path, monkeypatch, port):
    from app.desktop_review import application as desktop_application
    state, root = tmp_path / "inbox.json", tmp_path / "review"
    monkeypatch.setattr(sys, "argv", ["application.py", "--state-path", str(state),
                                      "--review-root", str(root), "--listen-port", port])
    with pytest.raises(SystemExit) as outcome:
        desktop_application.main()
    assert outcome.value.code == 2
    assert not state.exists() and not root.exists()


def test_connection_dialog_can_reopen_after_toolbar_modal_closes():
    from app.desktop_review.connection_dialog import ConnectionManagerDialog
    application = ensure_application()
    controller = _Connections()
    window = ReviewMainWindow(_Facade(), connections=controller)
    window.show()
    dialog = None
    try:
        _wait(lambda: not window._jobs)
        seen = []
        def close_modal():
            modal = application.activeModalWidget()
            if isinstance(modal, ConnectionManagerDialog):
                if modal._jobs:
                    QTimer.singleShot(10, close_modal)
                    return
                seen.append(True)
                modal.close()
        QTimer.singleShot(0, close_modal)
        window.connections_action.trigger()
        assert seen == [True]
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not window.findChildren(ConnectionManagerDialog)
        dialog = ConnectionManagerDialog(controller, window)
        dialog.show()
        _wait(lambda: dialog.snapshot is not None and not dialog._jobs)
        assert dialog.snapshot["host"]["phase"] == "ready"
    finally:
        if dialog is not None:
            _close(dialog)
        _wait(lambda: not window._jobs)
        window.close(); application.processEvents()


def _http(base_url, token, role, operation, payload):
    from urllib.parse import urlsplit
    target = urlsplit(base_url)
    connection = http.client.HTTPConnection(target.hostname, target.port, timeout=5)
    try:
        connection.request("POST", f"/{role}/{operation}", body=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                           headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


def _assert_readable_connection_header(dialog):
    host, note = dialog.host_label, dialog.layout().itemAt(1).widget()
    assert host.isVisible() and note.isVisible()
    assert dialog.rect().contains(host.geometry())
    assert dialog.rect().contains(note.geometry())
    assert host.geometry().bottom() < note.geometry().top(), (host.geometry(), note.geometry())


def test_real_native_shared_host_create_receive_review_revoke_and_restart(tmp_path):
    from app.desktop_review.connection_dialog import ConnectionManagerDialog
    from app.desktop_review.host import DesktopReviewHost
    from test_desktop_review_integration import _synthetic_batch
    from test_desktop_review_window import _wait_loaded
    application = ensure_application()
    state, root = tmp_path / "inbox.json", tmp_path / "review-data"
    reviewer_token = "synthetic-reviewer-only-123456"
    host = DesktopReviewHost(state, root, reviewer_token, port=0)
    window = dialog = None
    try:
        window = ReviewMainWindow(host.facade, connections=host.connections, startup=host.start, shutdown=host.close)
        window.show()
        _wait(lambda: window._operation == "idle" and not window._jobs)
        assert host.status()["phase"] == "ready"
        observed_dialogs = []
        def inspect_open_dialog():
            modal = application.activeModalWidget()
            if isinstance(modal, ConnectionManagerDialog):
                if modal._jobs:
                    QTimer.singleShot(10, inspect_open_dialog)
                    return
                observed_dialogs.append(modal.controller is host.connections)
                modal.close()
        QTimer.singleShot(0, inspect_open_dialog)
        window.connections_action.trigger()
        assert observed_dialogs == [True]
        dialog = ConnectionManagerDialog(host.connections, window)
        dialog.resize(1200, 800)
        dialog.show()
        _wait(lambda: dialog.snapshot is not None and not dialog._jobs)
        _draft(dialog)
        QTest.mouseClick(dialog.create_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert dialog.token.text() and dialog.table.rowCount() == 1
        dialog.config_format.setCurrentIndex(1)
        QTest.mouseClick(dialog.copy_config_button, Qt.MouseButton.LeftButton)
        config = json.loads(QApplication.clipboard().text())
        agent_token = config["env"]["AGENT_LINK_TOKEN"]
        base_url = config["env"]["AGENT_LINK_BASE_URL"]
        assert reviewer_token not in json.dumps(config)
        assert _http(base_url, reviewer_token, "reviewer", "list_connections", {})[0] == 404
        batch = _synthetic_batch(application)
        status, receipt = _http(base_url, agent_token, "agent", "submit_batch", batch)
        assert status == 200 and receipt["staging_only"] is True
        output = Path(os.environ.get("AGENT_REVIEW_QA_DIR", str(tmp_path / "qa")))
        output.mkdir(parents=True, exist_ok=True)
        application.processEvents()
        _assert_readable_connection_header(dialog)
        assert dialog.grab().save(str(output / "native-agent-connection-created.png"))
        QTest.mouseClick(dialog.clear_secret_button, Qt.MouseButton.LeftButton)
        dialog.close(); application.processEvents(); dialog = None
        QTest.mouseClick(window.reload_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not window._jobs)
        assert window.batch_tree.topLevelItemCount() == 1
        row = window.batch_tree.topLevelItem(0)
        QTest.mouseClick(window.batch_tree.viewport(), Qt.MouseButton.LeftButton, pos=window.batch_tree.visualItemRect(row).center())
        _wait_loaded(window)
        _wait(lambda: not window._jobs)
        assert window.workspace["batch_id"] == batch["batch_id"]
        window.interface_meaning.setText("真实HTTP收件后的人工审核")
        window.save_current()
        _wait(lambda: not window._jobs)
        assert window.workspace["revision"] == 1
        saved = host.facade.load_batch("task-native", batch["batch_id"])
        assert saved == window.workspace
        assert host.facade.list_reviewed_assets() == []
        dialog = ConnectionManagerDialog(host.connections, window)
        dialog.resize(1200, 800); dialog.show()
        _wait(lambda: dialog.snapshot is not None and not dialog._jobs)
        dialog.table.selectRow(0)
        defaults = []
        def revoke():
            prompt = application.activeModalWidget()
            if isinstance(prompt, QMessageBox):
                defaults.append(prompt.defaultButton() == prompt.button(QMessageBox.StandardButton.Cancel))
                QTest.mouseClick(prompt.button(QMessageBox.StandardButton.Yes), Qt.MouseButton.LeftButton)
        QTimer.singleShot(0, revoke)
        QTest.mouseClick(dialog.revoke_button, Qt.MouseButton.LeftButton)
        _wait(lambda: not dialog._jobs)
        assert defaults == [True]
        assert dialog.table.item(0, 3).text() == "已撤销"
        status, error = _http(base_url, agent_token, "agent", "status", {})
        assert status != 200 and error["error"]["code"] == "connection_revoked"
        application.processEvents()
        _assert_readable_connection_header(dialog)
        assert dialog.grab().save(str(output / "native-agent-connection-revoked.png"))
        dialog.close(); application.processEvents(); dialog = None
        window.close()
        _wait(lambda: not window._jobs and not window.isVisible())
        assert host.status()["phase"] == "stopped"
    finally:
        QApplication.clipboard().clear()
        if dialog is not None:
            _close(dialog)
        if window is not None and window.isVisible():
            _wait(lambda: not window._jobs)
            window._dirty = False
            window.close()
            _wait(lambda: not window._jobs)
        host.close()
    reopened = DesktopReviewHost(state, root, reviewer_token, port=0)
    try:
        reopened.start()
        assert reopened.status()["host_id"] != host.status()["host_id"]
        assert reopened.facade.load_batch("task-native", batch["batch_id"]) == saved
        assert reopened.connections.list_connections()[0]["revoked"] is True
        status, error = _http(reopened.status()["base_url"], agent_token, "agent", "status", {})
        assert status != 200 and error["error"]["code"] == "connection_revoked"
    finally:
        reopened.close()
