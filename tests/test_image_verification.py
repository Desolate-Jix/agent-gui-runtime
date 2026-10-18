from hashlib import sha256
from io import BytesIO
from types import SimpleNamespace

import numpy as np
from PIL import Image
import pytest


def sample(tmp_path):
    pixels = np.random.default_rng(42).integers(0, 256, (60, 80, 3), dtype=np.uint8)
    stream = BytesIO()
    Image.fromarray(pixels).save(stream, format="PNG")
    raw = stream.getvalue()
    digest = sha256(raw).hexdigest()
    check = dict(contract_version="workflow_image_check.v1", reference_sha256=digest,
                 reference_size=[80, 60], template_bbox=[10, 10, 20, 20],
                 search_roi=[0, 0, 80, 60], threshold=0.95)
    path = tmp_path / "desktop-review" / "evidence-objects" / (digest + ".png")
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    frame = dict(image_path=str(path), sha256=digest, image_size={"width": 80, "height": 60},
                 capture_id="fresh", window_identity={"handle": 1, "process_id": 2, "process_create_time": 3},
                 window_rect=[0, 0, 80, 60])
    return check, raw, pixels, frame


def test_unique_template_matches_and_binds_original_bytes(tmp_path):
    from app.learning_memory.image_verification import load_reference_image, match_image_check
    check, raw, _, frame = sample(tmp_path)
    assert load_reference_image(SimpleNamespace(_artifact_root=tmp_path), check) == raw
    proof = match_image_check(check, raw, frame)
    assert proof["matched"] is True
    assert proof["bbox"] == [10, 10, 20, 20]
    assert proof["capture_sha256"] == frame["sha256"]


def test_repeated_template_is_ambiguous(tmp_path):
    from app.learning_memory.image_verification import match_image_check
    check, raw, pixels, frame = sample(tmp_path)
    pixels[35:55, 45:65] = pixels[10:30, 10:30]
    Image.fromarray(pixels).save(frame["image_path"], format="PNG")
    frame["sha256"] = sha256(open(frame["image_path"], "rb").read()).hexdigest()
    result = match_image_check(check, raw, frame)
    assert result["matched"] is False and result["ambiguous"] is True


@pytest.mark.parametrize("field,value", [("threshold", True), ("threshold", 0.49),
    ("template_bbox", [-1, 0, 5, 5]), ("search_roi", [0, 0, 81, 60]), ("enabled", True)])
def test_invalid_configuration_rejected(tmp_path, field, value):
    from app.learning_memory.image_verification import validate_image_check
    check, _, _, _ = sample(tmp_path)
    check[field] = value
    with pytest.raises(ValueError):
        validate_image_check(check)


def test_reference_tampering_and_low_texture_rejected(tmp_path):
    from app.learning_memory.image_verification import load_reference_image
    check, raw, _, frame = sample(tmp_path)
    open(frame["image_path"], "wb").write(raw + b"changed")
    with pytest.raises(ValueError, match="sha256"):
        load_reference_image(SimpleNamespace(_artifact_root=tmp_path), check)


def test_polling_is_bounded_and_does_not_require_uia(tmp_path, monkeypatch):
    from app.learning_memory.image_verification import observe_image_check
    check, raw, pixels, frame = sample(tmp_path)
    pixels[:] = np.random.default_rng(99).integers(0, 256, pixels.shape, dtype=np.uint8)
    Image.fromarray(pixels).save(frame["image_path"], format="PNG")
    frame["sha256"] = sha256(open(frame["image_path"], "rb").read()).hexdigest()
    calls = []
    def capture(coordinator, handle, pid, *, recipe):
        assert recipe is None
        calls.append(True)
        return dict(frame, capture_id="fresh-" + str(len(calls))), {"uia": {"status": "not_required"}}
    monkeypatch.setattr("app.learning_memory.memory_observation.capture_memory_observation", capture)
    from tests.test_image_wait_early_exit import Clock
    clock = Clock()
    monkeypatch.setattr("app.learning_memory.image_verification.monotonic", clock.monotonic)
    monkeypatch.setattr("app.learning_memory.image_verification.sleep", clock.wait)
    result = observe_image_check(object(), target={"handle": 1, "process_id": 2},
        identity=frame["window_identity"], check=check, reference_raw=raw)
    assert result["complete"] is False
    assert len(result["evidence"]["attempts"]) == 20
    assert clock.now == 2


def test_polling_rejects_window_geometry_drift_between_attempts(tmp_path, monkeypatch):
    from app.learning_memory.image_verification import observe_image_check
    check, raw, _, frame = sample(tmp_path)
    count = []
    def capture(*args, **kwargs):
        count.append(True)
        return dict(frame, window_rect=[5, 5, 85, 65] if len(count) > 1 else frame["window_rect"]), {}
    def match(*args):
        return {"matched": False, "reason": "image_not_matched"}
    monkeypatch.setattr("app.learning_memory.memory_observation.capture_memory_observation", capture)
    monkeypatch.setattr("app.learning_memory.image_verification.match_image_check", match)
    monkeypatch.setattr("app.learning_memory.image_verification.sleep", lambda _: None)
    result = observe_image_check(object(), target={"handle": 1, "process_id": 2},
        identity=frame["window_identity"], check=check, reference_raw=raw)
    assert result["reason"] == "workflow_image_observation_geometry_changed"
    assert len(count) == 2


def test_low_texture_reference_is_rejected(tmp_path):
    from app.learning_memory.image_verification import load_reference_image
    check, _, _, _ = sample(tmp_path)
    stream = BytesIO()
    Image.new("RGB", (80, 60), "white").save(stream, format="PNG")
    raw = stream.getvalue()
    check["reference_sha256"] = sha256(raw).hexdigest()
    path = tmp_path / "desktop-review/evidence-objects" / (check["reference_sha256"] + ".png")
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="texture"):
        load_reference_image(SimpleNamespace(_artifact_root=tmp_path), check)


def test_overlapping_distinct_matches_are_not_suppressed(tmp_path):
    from app.learning_memory.image_verification import match_image_check
    check, _, pixels, frame = sample(tmp_path)
    stripe = np.random.default_rng(5).integers(0, 256, (20, 10, 3), dtype=np.uint8)
    pixels[:20, :30] = np.tile(stripe, (1, 3, 1))
    Image.fromarray(pixels).save(frame["image_path"], format="PNG")
    raw = open(frame["image_path"], "rb").read()
    check.update(reference_sha256=sha256(raw).hexdigest(), template_bbox=[0, 0, 20, 20], search_roi=[0, 0, 30, 20])
    frame["sha256"] = check["reference_sha256"]
    result = match_image_check(check, raw, frame)
    assert result["ambiguous"] is True and result["matched"] is False
