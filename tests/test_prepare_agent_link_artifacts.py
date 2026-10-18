from __future__ import annotations

import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys

from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[1]


def png(path):
    image = Image.new("RGB", (40, 24), "white")
    buffer = BytesIO(); image.save(buffer, "PNG")
    path.write_bytes(buffer.getvalue())
    return buffer.getvalue()


def test_prepare_bundle_preserves_bytes_and_stdout_contains_only_references(tmp_path):
    from scripts.prepare_agent_link_artifacts import prepare_bundle

    image = tmp_path / "原图.png"
    original = png(image)
    output = tmp_path / "transport.json"
    result = prepare_bundle({"library": image}, connection_id="connection-test", task_id="task-test", output=output)
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["contract_version"] == "agent_link_artifact_bundle_v1"
    assert saved["connection_id"] == result["connection_id"] == "connection-test"
    assert saved["task_id"] == result["task_id"] == "task-test"
    assert base64.b64decode(saved["artifacts"][0]["png_base64"], validate=True) == original
    assert result["screenshots"] == [{"screenshot_id": "library", "artifact_id": "library", "sha256": hashlib.sha256(original).hexdigest()}]
    assert result["bundle_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert "png_base64" not in json.dumps(result)
    assert image.read_bytes() == original
    with pytest.raises(FileExistsError):
        prepare_bundle({"library": image}, connection_id="connection-test", task_id="task-test", output=output)
    assert saved == json.loads(output.read_text(encoding="utf-8"))


def test_invalid_png_does_not_create_package(tmp_path):
    from scripts.prepare_agent_link_artifacts import prepare_bundle

    bad = tmp_path / "bad.png"; bad.write_bytes(b"not a PNG")
    output = tmp_path / "transport.json"
    with pytest.raises((ValueError, RuntimeError)):
        prepare_bundle({"bad": bad}, connection_id="connection-test", task_id="task-test", output=output)
    assert not output.exists()


def test_packager_cli_is_reproducible_from_other_working_directory(tmp_path):
    original = tmp_path / "input.png"; png(original)
    output = tmp_path / "bundle.json"
    command = [sys.executable, str(ROOT / "scripts/prepare_agent_link_artifacts.py"), "--connection-id", "connection-test", "--task-id", "task-test", "--output", str(output), "--image", "library=" + str(original)]
    run = subprocess.run(command, cwd=tmp_path, capture_output=True, timeout=10)
    assert run.returncode == 0, run.stderr.decode("utf-8")
    result = json.loads(run.stdout.decode("utf-8"))
    assert result["bundle_path"] == str(output.resolve())
    assert "png_base64" not in run.stdout.decode("utf-8")


def test_post_write_verification_read_is_bounded(tmp_path, monkeypatch):
    from app.agent_link.artifacts import MAX_ARTIFACT_BUNDLE_BYTES
    from scripts.prepare_agent_link_artifacts import prepare_bundle

    original = tmp_path / "input.png"; png(original)
    output = tmp_path / "bundle.json"
    open_file, reads = Path.open, []

    class TrackedReader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.stream.close()

        def read(self, size=-1):
            reads.append(size)
            return self.stream.read(size)

    def tracked_open(path, mode="r", *args, **kwargs):
        stream = open_file(path, mode, *args, **kwargs)
        return TrackedReader(stream) if path == output and mode == "rb" else stream

    monkeypatch.setattr(Path, "open", tracked_open)
    prepare_bundle({"library": original}, connection_id="connection-test", task_id="task-test", output=output)
    assert reads == [MAX_ARTIFACT_BUNDLE_BYTES + 1]
