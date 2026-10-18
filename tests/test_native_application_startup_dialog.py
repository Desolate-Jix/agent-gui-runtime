from __future__ import annotations

import pytest
import time
from threading import Event

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from app.desktop_review.application_startup_dialog import ApplicationStartupDialog
from app.desktop_review.window import ensure_application


class _Provider:
    def __init__(self):
        self.confirmed = []

    def list_requests(self):
        return [{"request_id": "request-1", "task_id": "task", "app_id": "notes", "url": "https://example.test", "created_at": 1, "status": "pending_human_confirmation"}]

    def preview(self, request_id):
        assert request_id == "request-1"
        return {"contract_version": "native_window_preparation_v1", "preparation_id": "prep-1", "mode": "launch", "identity": None, "source": "app_catalog", "app_id": "notes", "name": "Notes", "url": "https://example.test", "command": [r"C:\Fixture\notes.exe", "https://example.test"], "executable_path": r"C:\Fixture\notes.exe", "catalog_entry_sha256": "a" * 64, "executable_sha256": "b" * 64, "expires_in_seconds": 60, "preview_sha256": "c" * 64}

    def confirm(self, request_id, expected_preview_sha256=None):
        self.confirmed.append(request_id)
        return {"status": "launched_window_ready", "process_id": 42, "window": {"handle": 8, "process_id": 42, "title": "Notes"}}


def _dialog(provider, monkeypatch):
    ensure_application()
    dialog = ApplicationStartupDialog(provider, auto_refresh=False)
    dialog._render(provider.list_requests())
    def synchronous(operation, callback):
        dialog._operation = operation
        dialog._request_id += 1
        dialog._succeeded(dialog._request_id, callback())
        dialog._operation = None
        dialog._controls()
    monkeypatch.setattr(dialog, "_start", synchronous)
    return dialog


def test_dialog_previews_exact_command_and_cancel_is_the_default(monkeypatch: pytest.MonkeyPatch):
    provider = _Provider()
    dialog = _dialog(provider, monkeypatch)
    monkeypatch.setattr(QMessageBox, "exec", lambda _box: QMessageBox.StandardButton.Cancel)
    try:
        assert dialog.requests.rowCount() == 1
        dialog.requests.selectRow(0)
        dialog.preview()
        assert "notes.exe" in dialog.preview_text.toPlainText()
        assert dialog.confirm_button.isEnabled()
        dialog.confirm()
        assert provider.confirmed == []
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dialog_confirm_runs_in_background_after_explicit_yes(monkeypatch: pytest.MonkeyPatch):
    provider = _Provider()
    dialog = _dialog(provider, monkeypatch)
    monkeypatch.setattr(QMessageBox, "exec", lambda _box: QMessageBox.StandardButton.Yes)
    try:
        assert dialog.requests.rowCount() == 1
        dialog.requests.selectRow(0)
        dialog.preview()
        assert dialog.confirm_button.isEnabled()
        dialog.confirm()
        assert provider.confirmed == ["request-1"]
        assert "launched_window_ready" in dialog.receipt_text.toPlainText()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_busy_dialog_refuses_escape_and_close_until_job_finishes(monkeypatch: pytest.MonkeyPatch):
    provider = _Provider()
    dialog = _dialog(provider, monkeypatch)
    try:
        marker = object()
        dialog._jobs.add(marker)
        dialog.reject()
        assert dialog.isVisible() is False and "仍在运行" in dialog.status.text()
        class _Event:
            ignored = False
            accepted = False
            def ignore(self): self.ignored = True
            def accept(self): self.accepted = True
        event = _Event()
        dialog.closeEvent(event)
        assert event.ignored is True and event.accepted is False
        dialog._jobs.discard(marker)
    finally:
        dialog.close()
        dialog.deleteLater()


class _BlockingProvider(_Provider):
    def __init__(self):
        super().__init__()
        self.started = Event()
        self.release = Event()

    def confirm(self, request_id, expected_preview_sha256=None):
        self.confirmed.append(request_id)
        self.started.set()
        assert self.release.wait(3)
        return {"status": "launched_window_ready", "process_id": 42,
                "window": {"handle": 8, "process_id": 42, "title": "Notes"}}


def _wait(predicate, timeout=3):
    application = ensure_application()
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline
        QTest.qWait(10)
        application.processEvents()


def test_real_background_confirm_blocks_escape_and_close_until_completion(monkeypatch: pytest.MonkeyPatch):
    provider = _BlockingProvider()
    ensure_application()
    dialog = ApplicationStartupDialog(provider, auto_refresh=False)
    monkeypatch.setattr(QMessageBox, "exec", lambda _box: QMessageBox.StandardButton.Yes)
    try:
        dialog._render(provider.list_requests())
        dialog.show()
        dialog.requests.selectRow(0)
        preview = provider.preview("request-1")
        dialog._preview = preview
        dialog.preview_text.setPlainText(str(preview))
        dialog._controls()
        dialog.confirm()
        _wait(provider.started.is_set)
        assert len(dialog._jobs) == 1 and provider.confirmed == ["request-1"] and dialog.isVisible()
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        dialog.close()
        assert dialog.isVisible() and provider.confirmed == ["request-1"]
        provider.release.set()
        _wait(lambda: not dialog._jobs)
        dialog.close()
        _wait(lambda: not dialog.isVisible())
        assert provider.confirmed == ["request-1"]
    finally:
        provider.release.set()
        _wait(lambda: not dialog._jobs)
        dialog.close()
        dialog.deleteLater()
