"""光标闪烁只能等待原像素重现，不能放宽身份、哈希或时间条件。"""
from copy import deepcopy
import hashlib
from types import SimpleNamespace

import pytest

from app.agent.fresh_capture_stability import check_fresh_capture_pixels


def _evidence():
    return {"target": {"window_handle": 5}, "application": {"process_id": 7},
        "uia": {"snapshot_sha256": "same-uia"}, "capture": {
            "capture_id": "before", "capture_clock_id": "clock", "observed_at_ns": 100,
            "capture_started_ns": 90, "viewport_size": {"width": 10, "height": 10},
            "screenshot_sha256": hashlib.sha256(b"original-png").hexdigest()}}


def _packet(original, *, pixels=b"original-png", change=None, index=1):
    evidence = deepcopy(original)
    evidence["capture"].update(capture_id=f"after-{index}", capture_started_ns=100 + index * 10,
        observed_at_ns=101 + index * 10,
        screenshot_sha256=hashlib.sha256(pixels).hexdigest())
    if change:
        section, key, value = change
        evidence[section][key] = value
    return SimpleNamespace(png_bytes=pixels, evidence=lambda: evidence)


def _run(monkeypatch, packets, *, retry=True):
    import app.agent.fresh_capture_stability as module
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    calls = []
    def observe():
        calls.append("observe")
        return packets[min(len(calls) - 1, len(packets) - 1)]
    result = check_fresh_capture_pixels(original=_evidence(), observe=observe,
        validate_source=lambda: None, allow_transient_retry=retry)
    return result, calls


def test_transient_pixels_wait_for_an_exact_new_capture(monkeypatch):
    original = _evidence()
    result, calls = _run(monkeypatch, [_packet(original, pixels=b"caret-on"), _packet(original, index=2)])
    assert len(calls) == 2 and result["attempts"] == 2
    assert result["screenshot_sha256"] == original["capture"]["screenshot_sha256"]


@pytest.mark.parametrize("change", [
    ("target", "window_handle", 6), ("application", "process_id", 8),
    ("uia", "snapshot_sha256", "changed"), ("capture", "viewport_size", {"width": 9, "height": 10}),
    ("capture", "capture_clock_id", "different"), ("capture", "capture_id", "before"),
    ("capture", "capture_started_ns", 100), ("capture", "screenshot_sha256", "forged"),
])
def test_identity_or_integrity_drift_cannot_recover_by_retry(monkeypatch, change):
    with pytest.raises(ValueError):
        _run(monkeypatch, [_packet(_evidence(), change=change), _packet(_evidence())])


@pytest.mark.parametrize("retry", [False, True])
def test_persistent_pixel_drift_never_passes(monkeypatch, retry):
    with pytest.raises(ValueError):
        _run(monkeypatch, [_packet(_evidence(), pixels=b"different")], retry=retry)


def test_non_text_path_does_not_gain_transient_retry(monkeypatch):
    with pytest.raises(ValueError):
        _run(monkeypatch, [_packet(_evidence(), pixels=b"different"), _packet(_evidence())], retry=False)


def test_retry_cannot_replay_the_same_capture_identity(monkeypatch):
    with pytest.raises(ValueError):
        _run(monkeypatch, [_packet(_evidence(), pixels=b"different"), _packet(_evidence())])


def test_source_revocation_during_wait_rejects(monkeypatch):
    import app.agent.fresh_capture_stability as module
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    checks = []
    def validate():
        checks.append(1)
        if len(checks) == 3:
            raise ValueError("source revoked")
    with pytest.raises(ValueError, match="source revoked"):
        check_fresh_capture_pixels(original=_evidence(),
            observe=lambda: _packet(_evidence(), pixels=b"changed"), validate_source=validate,
            allow_transient_retry=True)


def test_capture_identity_diagnostic_names_stage_without_local_values(caplog):
    from app.agent.fresh_capture_stability import require_exact_fresh_capture
    original = _evidence()
    packet = _packet(original,change=('uia','private','PRIVATE_CONTROL_VALUE'))
    with pytest.raises(ValueError,match='identity or capture integrity'):
        require_exact_fresh_capture(original=original,current=packet.evidence(),png_bytes=packet.png_bytes)
    assert 'fresh_capture_binding_rejected' in caplog.text
    assert "'uia_unchanged': False" in caplog.text
    assert "'target_unchanged': True" in caplog.text
    assert 'PRIVATE_CONTROL_VALUE' not in caplog.text


@pytest.mark.parametrize("persistent", [False, True])
def test_text_capture_stabilizes_before_calling_the_model(tmp_path, monkeypatch, persistent):
    from PIL import Image
    from tests.test_fresh_text_preview import _native_owner
    from app.agent.fresh_learning_observation import FreshLearningObservationError

    owner = _native_owner(tmp_path)
    expected = owner.observe(target_window_handle=4242, target_process_id=9001).evidence()
    capture, recognize = owner._screenshot_service.capture_window, owner._recognize
    probes, model_calls = [], []
    def capture_pixels(**kwargs):
        result = capture(**kwargs)
        probes.append(1)
        if persistent or len(probes) == 1:
            with Image.open(owner._screenshot_service.path) as source:
                altered = Image.new("RGB", source.size, "black")
            altered.save(owner._screenshot_service.path)
        return result
    def recognize_once(**kwargs):
        model_calls.append(1)
        return recognize(**kwargs)
    monkeypatch.setattr(owner._screenshot_service, "capture_window", capture_pixels)
    monkeypatch.setattr(owner, "_recognize", recognize_once)
    def observe():
        return owner.observe_for_action(target_window_handle=4242, target_process_id=9001,
            goal="Name", semantic_action="fill_field", expected_visual=expected)
    if persistent:
        with pytest.raises(FreshLearningObservationError):
            observe()
        assert len(probes) == 7 and model_calls == []
    else:
        bundle = observe()
        assert len(probes) == 2 and len(model_calls) == 1
        assert bundle.packet.evidence()["capture"]["screenshot_sha256"] == expected["capture"]["screenshot_sha256"]
