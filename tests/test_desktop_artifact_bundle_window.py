import hashlib
import json
from threading import Event
import time
from pathlib import Path
import pytest

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from app.desktop_review.connection_dialog import ConnectionManagerDialog
from app.desktop_review.host import DesktopReviewHost


_resources = []


@pytest.fixture(autouse=True)
def cleanup_owned_dialogs():
    try:
        yield
    finally:
        for app, host, dialog in _resources:
            try:
                _wait(dialog)
                dialog.clear_secret()
                dialog.close()
                app.clipboard().clear()
            finally:
                host.close()
        _resources.clear()


def _wait(dialog, timeout=5.0):
    deadline = time.monotonic() + timeout
    while dialog._jobs:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError(
                f"Qt 作业未在 {timeout:.1f} 秒内结束：pending={dialog._pending!r}, jobs={len(dialog._jobs)}"
            )
        loop = QEventLoop()
        QTimer.singleShot(max(1, int(min(remaining, 0.05) * 1000)), loop.quit)
        loop.exec()


def _png(path):
    image = QImage(3, 2, QImage.Format.Format_RGBA8888)
    image.fill(QColor("#1d5d90"))
    assert image.save(str(path), "PNG")


def _ready_dialog(tmp_path):
    app = QApplication.instance() or QApplication([])
    host = DesktopReviewHost(tmp_path / "state.sqlite", tmp_path / "review", "reviewer-token-123456")
    host.start()
    dialog = ConnectionManagerDialog(host.connections)
    _resources.append((app, host, dialog))
    _wait(dialog)
    created = host.connections.create_connection("task-a", "native-ui")
    status = host.status()
    dialog._secret = {**created, "host_id": status["host_id"], "base_url": status["base_url"]}
    dialog.snapshot = {"host": status, "connections": host.connections.list_connections()}
    dialog._controls()
    return app, host, dialog, created


def test_real_bundle_job_stores_exact_bytes_and_only_explicit_references(monkeypatch, tmp_path):
    app, host, dialog, created = _ready_dialog(tmp_path)
    image = tmp_path / "capture.png"
    _png(image)
    source = image.read_bytes()
    output = tmp_path / "bundle.json"
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *args: ([str(image)], "PNG 图片 (*.png)")))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *args: (str(output), "JSON 文件 (*.json)")))
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args: QMessageBox.StandardButton.Yes))

    dialog.register_artifact_bundle()
    _wait(dialog)

    stored = output.read_bytes()
    bundle = json.loads(stored)
    refs = dialog._artifact_refs["refs"]
    assert refs["bundle_sha256"] == hashlib.sha256(stored).hexdigest()
    assert bundle["connection_id"] == created["connection_id"]
    assert bundle["task_id"] == "task-a"
    assert host.facade.list_batches() == []
    assert refs["screenshots"] == [{"screenshot_id": "image-001", "artifact_id": "image-001", "sha256": hashlib.sha256(source).hexdigest()}]
    assert dialog._config(masked=True)["env"]["AGENT_LINK_ARTIFACT_BUNDLE"] == str(output.resolve())
    assert "<本连接密钥已隐藏>" in dialog.config_preview.toPlainText()
    dialog.config_format.setCurrentIndex(1)
    assert json.loads(dialog.config_preview.toPlainText())["env"]["AGENT_LINK_ARTIFACT_BUNDLE"] == str(output.resolve())

    dialog.copy_image_references()
    copied = json.loads(app.clipboard().text())
    assert copied == {"connection_id": created["connection_id"], "task_id": "task-a", "screenshots": refs["screenshots"]}
    assert created["token"] not in app.clipboard().text()
    dialog.detach_artifact_bundle()
    assert output.exists()
    assert "AGENT_LINK_ARTIFACT_BUNDLE" not in dialog._config(masked=True)["env"]
    app.clipboard().clear()
    dialog.clear_secret()
    dialog.close()
    host.close()


def test_cancel_and_existing_output_have_no_artifact_or_clipboard_side_effect(monkeypatch, tmp_path):
    app, host, dialog, _ = _ready_dialog(tmp_path)
    image = tmp_path / "capture.png"
    _png(image)
    existing = tmp_path / "existing.json"
    existing.write_bytes(b"keep")
    app.clipboard().setText("unchanged")
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *args: ([str(image)], "PNG 图片 (*.png)")))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *args: (str(existing), "JSON 文件 (*.json)")))
    dialog.register_artifact_bundle()
    assert existing.read_bytes() == b"keep"
    assert dialog._artifact_refs is None
    assert app.clipboard().text() == "unchanged"
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *args: ([], "PNG 图片 (*.png)")))
    dialog.register_artifact_bundle()
    assert dialog._artifact_refs is None
    assert app.clipboard().text() == "unchanged"
    app.clipboard().clear()
    dialog.clear_secret()
    dialog.close()
    host.close()


def test_artifact_receipt_requires_current_binding_lowercase_digests_and_exact_ids(tmp_path):
    binding = {"connection_id": "conn-a", "task_id": "task-a", "host_id": "host-a", "base_url": "http://127.0.0.1:9123"}
    image = tmp_path / "capture.png"
    output = tmp_path / "bundle.json"
    valid = {
        "contract_version": "agent_link_artifact_references_v1", "connection_id": "conn-a",
        "task_id": "task-a", "bundle_path": str(output.resolve()), "bundle_sha256": "a" * 64,
        "screenshots": [{"screenshot_id": "image-001", "artifact_id": "image-001", "sha256": "b" * 64}],
    }
    assert ConnectionManagerDialog._valid_artifact_refs(valid, binding, {"image-001": image.resolve()}, output.resolve())
    upper = dict(valid, bundle_sha256="A" * 64)
    assert not ConnectionManagerDialog._valid_artifact_refs(upper, binding, {"image-001": image.resolve()}, output.resolve())
    wrong_id = dict(valid, screenshots=[{"screenshot_id": "image-001", "artifact_id": "artifact-image-001", "sha256": "b" * 64}])
    assert not ConnectionManagerDialog._valid_artifact_refs(wrong_id, binding, {"image-001": image.resolve()}, output.resolve())


def test_stale_receipt_cannot_replace_refs_and_refresh_host_drift_clears_them(tmp_path):
    app, host, dialog, created = _ready_dialog(tmp_path)
    output = tmp_path / "bundle.json"
    binding = {key: dialog._secret[key] for key in ("connection_id", "task_id", "host_id", "base_url")}
    result = {
        "contract_version": "agent_link_artifact_references_v1", "connection_id": binding["connection_id"],
        "task_id": binding["task_id"], "bundle_path": str(output.resolve()), "bundle_sha256": "a" * 64,
        "screenshots": [{"screenshot_id": "image-001", "artifact_id": "image-001", "sha256": "b" * 64}],
    }
    previous = {"binding": binding, "refs": {**result, "bundle_path": "previous.json"}}
    dialog._artifact_refs = previous
    dialog._secret = {**dialog._secret, "connection_id": "replacement"}
    dialog._request_id = 9
    dialog._pending = ("prepare_artifacts", {"binding": binding, "images": {"image-001": tmp_path / "capture.png"}, "output": output})
    dialog._succeeded(9, result)
    assert dialog._artifact_refs == previous

    dialog._secret = {**created, "host_id": binding["host_id"], "base_url": binding["base_url"]}
    dialog._artifact_refs = previous
    drifted = dict(host.status(), base_url="http://127.0.0.1:9124")
    dialog._request_id = 10
    dialog._pending = ("refresh", None)
    dialog._succeeded(10, {"host": drifted, "connections": host.connections.list_connections()})
    assert dialog._secret is None
    assert dialog._artifact_refs is None
    app.clipboard().clear()
    dialog.close()
    host.close()


def test_clear_and_revoke_remove_attached_refs(monkeypatch, tmp_path):
    app, host, dialog, created = _ready_dialog(tmp_path)
    dialog._artifact_refs = {"binding": {}, "refs": {"bundle_path": "attached.json"}}
    dialog.clear_secret()
    assert dialog._artifact_refs is None
    dialog._secret = {**created, "host_id": host.status()["host_id"], "base_url": host.status()["base_url"]}
    dialog._artifact_refs = {"binding": {}, "refs": {"bundle_path": "attached.json"}}
    dialog._render_connections(host.connections.list_connections())
    dialog.table.selectRow(0)
    dialog._controls()
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args: QMessageBox.StandardButton.Yes))
    dialog.revoke_connection()
    _wait(dialog)
    _wait(dialog)
    assert dialog._secret is None
    assert dialog._artifact_refs is None
    app.clipboard().clear()
    dialog.close()
    host.close()


def test_busy_artifact_job_blocks_close_and_reentry(tmp_path):
    app, host, dialog, _ = _ready_dialog(tmp_path)
    release = Event()
    started = Event()
    calls = []

    def blocked():
        calls.append("started")
        started.set()
        release.wait(2)
        return {}

    dialog._start("prepare_artifacts", {"binding": {}, "images": {}, "output": tmp_path / "bundle.json"}, blocked)
    for _ in range(20):
        if started.is_set():
            break
        loop = QEventLoop()
        QTimer.singleShot(20, loop.quit)
        loop.exec()
    assert started.is_set()
    assert dialog._busy
    assert not dialog._can_close()
    dialog._start("prepare_artifacts", None, lambda: calls.append("duplicate"))
    assert calls == ["started"]
    release.set()
    _wait(dialog)
    assert calls == ["started"]
    dialog.clear_secret()
    app.clipboard().clear()
    dialog.close()
    host.close()
