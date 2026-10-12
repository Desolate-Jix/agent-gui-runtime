"""缺省截图身份绑定实际文件；相同像素不能合并不同采集事件。"""
from copy import deepcopy
from hashlib import sha256
import os

from PIL import Image
import pytest

from app.execution.decision_check import decision_frame


IDENTITY = {"handle": 10, "process_id": 20, "process_create_time": 30.0}


@pytest.fixture
def capture(tmp_path):
    path = tmp_path / "Capture-One.png"
    Image.new("RGB", (24, 16), "white").save(path)
    return {"image_path": str(path), "sha256": sha256(path.read_bytes()).hexdigest(),
        "window_identity": deepcopy(IDENTITY)}


def test_identical_pixels_in_different_capture_artifacts_have_distinct_default_ids(capture, tmp_path):
    other = tmp_path / "Capture-Two.png"
    other.write_bytes((tmp_path / "Capture-One.png").read_bytes())
    second = {**capture, "image_path": str(other)}
    first = decision_frame(capture, IDENTITY, role="before")
    after = decision_frame(second, IDENTITY, role="after")
    assert first["sha256"] == after["sha256"]
    assert first["capture_id"] != after["capture_id"]


@pytest.mark.parametrize("alias", ["relative", "dot", "case"])
def test_same_capture_artifact_path_aliases_normalize_to_stable_default_id(capture, tmp_path, monkeypatch, alias):
    if alias == "case" and os.name != "nt":
        pytest.skip("case aliases follow the Windows filesystem")
    monkeypatch.chdir(tmp_path)
    original = decision_frame(capture, IDENTITY, role="after")
    if alias == "relative":
        image_path = "Capture-One.png"
    elif alias == "dot":
        (tmp_path / "subdir").mkdir()
        image_path = str(tmp_path / "subdir" / ".." / "Capture-One.png")
    else:
        image_path = capture["image_path"].upper()
    normalized = decision_frame({**capture, "image_path": image_path}, IDENTITY, role="after")
    assert normalized["capture_id"] == original["capture_id"]
    assert normalized["sha256"] == original["sha256"]


def test_same_capture_role_and_display_metadata_do_not_create_a_new_artifact(capture):
    before = deepcopy(capture)
    original = decision_frame(capture, IDENTITY, role="before")
    repeated = decision_frame({**capture, "frame_id": "claimed-new-frame", "observation_stage": "after_render_wait"},
        IDENTITY, role="after")
    assert repeated["capture_id"] == original["capture_id"]
    assert capture == before


def test_explicit_capture_id_is_preserved(capture):
    result = decision_frame({**capture, "capture_id": "native-capture-event-42"}, IDENTITY, role="after")
    assert result["capture_id"] == "native-capture-event-42"


def test_default_capture_id_also_binds_current_artifact_content(capture, tmp_path):
    original = decision_frame(capture, IDENTITY, role="after")
    Image.new("RGB", (24, 16), "blue").save(tmp_path / "Capture-One.png")
    updated = decision_frame({"image_path": capture["image_path"]}, IDENTITY, role="after")
    assert updated["sha256"] != original["sha256"] and updated["capture_id"] != original["capture_id"]


@pytest.mark.parametrize("fault", ["hash", "window"])
def test_artifact_identity_keeps_original_integrity_and_window_checks(capture, fault):
    if fault == "hash":
        capture["sha256"] = "0" * 64
    else:
        capture["window_identity"]["handle"] += 1
    with pytest.raises(ValueError, match="capture (hash|window identity) mismatch"):
        decision_frame(capture, IDENTITY, role="after")
