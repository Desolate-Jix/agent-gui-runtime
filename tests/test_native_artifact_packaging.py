from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from PIL import Image
import pytest

from app.desktop_review.connections import NativeConnectionError
from app.desktop_review.host import DesktopReviewHost


@pytest.fixture
def ready(tmp_path):
    host = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "reviews", "test-reviewer-secret-long")
    host.start()
    grant = host.connections.create_connection("task-native", "test-agent")
    binding = {"connection_id": grant["connection_id"], "task_id": grant["task_id"], "host_id": host.status()["host_id"], "base_url": host.status()["base_url"]}
    image = tmp_path / "原图.png"
    Image.new("RGB", (40, 24), "white").save(image, "PNG")
    try:
        yield host, binding, image, tmp_path / "bundle.json"
    finally:
        host.close()


def test_native_packaging_binds_selected_images_without_mutating_inbox(ready):
    host, binding, image, output = ready
    store = output.parent / "inbox.json"
    before = store.read_bytes()
    result = host.connections.prepare_artifact_bundle(binding, {"image-001": image}, output)
    assert result["connection_id"] == binding["connection_id"]
    assert result["task_id"] == "task-native"
    assert result["bundle_path"] == str(output.resolve())
    raw = image.read_bytes()
    assert result["screenshots"] == [{"screenshot_id": "image-001", "artifact_id": "image-001", "sha256": hashlib.sha256(raw).hexdigest()}]
    bundle = json.loads(output.read_text(encoding="utf-8"))
    assert base64.b64decode(bundle["artifacts"][0]["png_base64"], validate=True) == raw
    assert "token" not in json.dumps(result)
    assert store.read_bytes() == before


@pytest.mark.parametrize("field", ["connection_id", "task_id", "host_id", "base_url"])
def test_changed_binding_rejected_before_file_creation(ready, field):
    host, binding, image, output = ready
    binding[field] = "changed"
    with pytest.raises(NativeConnectionError):
        host.connections.prepare_artifact_bundle(binding, {"image-001": image}, output)
    assert not output.exists()


def test_revoked_connection_cannot_register_images(ready):
    host, binding, image, output = ready
    host.connections.revoke_connection(binding["connection_id"], "revoke-test")
    with pytest.raises(NativeConnectionError):
        host.connections.prepare_artifact_bundle(binding, {"image-001": image}, output)
    assert not output.exists()


def test_unknown_binding_field_is_not_forwarded(ready):
    host, binding, image, output = ready
    binding["token"] = "must-not-be-used"
    with pytest.raises(NativeConnectionError):
        host.connections.prepare_artifact_bundle(binding, {"image-001": image}, output)
    assert not output.exists()


def test_existing_output_is_unchanged_and_error_is_redacted(ready):
    host, binding, image, output = ready
    output.write_bytes(b"existing-user-file")
    with pytest.raises(NativeConnectionError) as caught:
        host.connections.prepare_artifact_bundle(binding, {"image-001": image}, output)
    assert output.read_bytes() == b"existing-user-file"
    assert str(output) not in str(caught.value)
    assert caught.value.code == "artifact_output_exists"


def test_post_package_host_drift_does_not_return_attachable_receipt(ready, monkeypatch):
    import app.desktop_review.connections as module
    from app.agent_link.artifact_packaging import prepare_bundle

    host, binding, image, output = ready
    state = {"changed": False}
    original_status = host.connections._host_status

    def status():
        value = original_status()
        if state["changed"]:
            value["host_id"] = "changed-host"
        return value

    def package(*args, **kwargs):
        result = prepare_bundle(*args, **kwargs)
        state["changed"] = True
        return result

    monkeypatch.setattr(host.connections, "_host_status", status)
    monkeypatch.setattr(module, "prepare_bundle", package)
    with pytest.raises(NativeConnectionError) as caught:
        host.connections.prepare_artifact_bundle(binding, {"image-001": image}, output)
    assert caught.value.result_unknown is True
    assert output.exists()


def test_stopped_host_cannot_register_images(ready):
    host, binding, image, output = ready
    host.close()
    with pytest.raises(NativeConnectionError):
        host.connections.prepare_artifact_bundle(binding, {"image-001": image}, output)
    assert not output.exists()
