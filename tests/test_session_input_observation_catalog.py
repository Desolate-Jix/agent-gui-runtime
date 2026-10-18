from hashlib import sha256

import pytest

from app.core.json_snapshot import write_json_snapshot
from app.execution import session_input_terminal as module
from tests.test_session_input_terminal import job


PNG = b"\x89PNG\r\n\x1a\noriginal-business-frame"


def scene(tmp_path):
    root = tmp_path / "session"
    directory = root / "workflow-observations"
    directory.mkdir(parents=True)
    image = directory / "current.png"
    image.write_bytes(PNG)
    frame = {"image_path": str(image), "sha256": sha256(PNG).hexdigest()}
    envelope = {"contract_version": "workflow_observation.v1", "frame": frame,
                "native_evidence": {"before_frame": frame, "after_frame": frame}}
    path = directory / "rule.json"
    write_json_snapshot(path, envelope)
    return root, image, path, envelope


def test_exact_observation_and_repeated_frame_references_are_pinned(tmp_path):
    root, image, path, _ = scene(tmp_path)
    result = module.inspect_session_input_terminal(root, root.parent / "memory-library")
    assert set(result["files"]) == {"workflow-observations/rule.json", "workflow-observations/current.png"}
    assert result["files"]["workflow-observations/current.png"] == sha256(PNG).hexdigest()


@pytest.mark.parametrize("failure", ["missing", "escape", "sha", "signature", "conflicting_ref"])
def test_referenced_png_failure_rejected(tmp_path, failure):
    root, image, path, envelope = scene(tmp_path)
    if failure == "missing": envelope["frame"]["image_path"] = str(image.parent / "missing.png")
    if failure == "escape": envelope["frame"]["image_path"] = str(tmp_path / "personal.png")
    if failure == "sha": envelope["frame"]["sha256"] = "f" * 64
    if failure == "signature": image.write_bytes(b"not PNG"); envelope["frame"]["sha256"] = sha256(b"not PNG").hexdigest()
    if failure == "conflicting_ref": envelope["native_evidence"]["after_frame"] = {**envelope["frame"], "sha256": "f" * 64}
    write_json_snapshot(path, envelope)
    with pytest.raises(ValueError, match="session_input_"):
        module.inspect_session_input_terminal(root, root.parent / "memory-library")


@pytest.mark.parametrize("change", ["image", "new_envelope", "envelope"])
def test_observation_catalog_drift_rejected(tmp_path, monkeypatch, change):
    root, image, path, envelope = scene(tmp_path)
    job(root)
    original = module._worker
    def drift(worker, eid):
        if change == "image": image.write_bytes(PNG + b"changed")
        elif change == "new_envelope": write_json_snapshot(path.parent / "new.json", envelope)
        else: path.write_bytes(path.read_bytes() + b" ")
        return original(worker, eid)
    monkeypatch.setattr(module, "_worker", drift)
    with pytest.raises(ValueError, match="session_input_"):
        module.inspect_session_input_terminal(root, root.parent / "memory-library")


def test_read_text_and_history_read_observation_frames_are_pinned(tmp_path):
    root, image, _, envelope = scene(tmp_path)
    (root / "commands").mkdir()
    (root / "responses").mkdir()
    (root / "workflow-trials").mkdir()
    write_json_snapshot(root / "commands/read.json", {"kind": "read_text"})
    write_json_snapshot(root / "responses/read.json", {"status": "returned", "command": {"kind": "read_text"}, "observation": envelope["frame"], "result": {}})
    write_json_snapshot(root / "workflow-trials/trial-read.json", {"run_id": "trial-read", "pending": None, "history": [{"read_observation": envelope["frame"]}]})
    assert module.inspect_session_input_terminal(root, root.parent / "memory-library")["files"]["workflow-observations/current.png"] == sha256(image.read_bytes()).hexdigest()
