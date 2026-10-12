"""三张新截图与单次判断的离线运行时合同。"""
from copy import deepcopy

import pytest

from app.execution import video_playback_verification as module
from tests.test_task_plan_adaptive_review import OfflineAssessment, review_request
from tests.test_task_plan_video_playback import playback_scene, video_plan


def picture_scene(tmp_path, monkeypatch, *, service=None, source=None, slow_capture=0):
    return playback_scene(tmp_path, monkeypatch, service=service, source=source,
        slow_capture=slow_capture, mode="unknown")


def capture_three(s, clock):
    s.runtime.tick(force=True)
    for seconds in (1.0, 1.5, 2.0):
        clock.seconds = seconds
        result = s.runtime.tick(force=True)
    return result


def test_exact_three_new_frames_one_decision_and_no_local_observers(tmp_path, monkeypatch):
    service = OfflineAssessment(disposition="continue")
    s, original, clock, calls = picture_scene(tmp_path, monkeypatch, service=service)
    def forbidden(*args, **kwargs):
        pytest.fail("新路径不得定位、OCR、检查白屏或本地差异")
    for name in ("locate_player", "observe_player_frame", "observation_evidence_refs", "page_loading", "_analysis"):
        monkeypatch.setattr(module, name, forbidden)
    result = capture_three(s, clock)
    assert result["status"] == "completed" and result["history"][0]["judged_by"] == "decision"
    assert len(service.calls) == 1 and len(calls.capture) == 3
    assert len(list(tmp_path.glob("commands/*.json"))) == 1
    ledger = module.VideoPlaybackLedger(s.runtime.backend, original.command_id)
    assert ledger.header()["analysis_policy"] == "video_picture_change.v1"
    assert ledger.summary()["schema"] == "video_playback_binding.v2"
    assert ledger.summary()["region"] is None and ledger.summary()["analysis"] is None
    assert ledger.summary()["readiness_observations"] == []
    assert [item["elapsed_ms"] for item in ledger.samples()] == [1000, 1500, 2000]
    assert all(set(item) == {"frame", "elapsed_ms"} for item in ledger.samples())
    temporal = service.calls[0]["temporal_context"]
    assert set(temporal) == {"schema", "original_after", "samples", "selected_capture_ids", "timeout_seconds"}
    assert temporal["schema"] == "temporal_playback.v2" and temporal["samples"] == ledger.samples()
    assert temporal["selected_capture_ids"] == [item["frame"]["capture_id"] for item in ledger.samples()]
    assert temporal["original_after"] == service.calls[0]["frames"][0]
    assert temporal["original_after"]["sha256"] == original.capture["sha256"]
    assert temporal["timeout_seconds"] == 6
    assert module._outcome(ledger)["local_success"] is False


def test_minimum_first_wait_and_neighbor_spacing_are_observed(tmp_path, monkeypatch):
    s, _, clock, calls = picture_scene(tmp_path, monkeypatch)
    first = s.runtime.tick(force=True)
    assert first["observation_pending"] is True and calls.capture == []
    for seconds in (.999, 1.0, 1.499, 1.5, 1.999, 2.0):
        clock.seconds = seconds
        result = s.runtime.tick(force=True)
        assert len(calls.capture) == (0 if seconds < 1 else 1 if seconds < 1.5 else 2 if seconds < 2 else 3)
    assert result["review_required"] is True and result["history"] == []
    clock.seconds = 100
    assert s.runtime.tick(force=True) is None and len(calls.capture) == 3


@pytest.mark.parametrize("gate", ["unconfigured", "always_main", "shadow"])
def test_review_modes_still_collect_three_and_never_adopt_or_repeat(tmp_path, monkeypatch, gate):
    service = None if gate == "unconfigured" else OfflineAssessment(
        disposition="continue" if gate == "shadow" else "review_required")
    if gate == "shadow":
        status = service.status
        monkeypatch.setattr(service, "status", lambda: {**status(), "adoption_mode": "shadow"})
    s, original, clock, calls = picture_scene(tmp_path, monkeypatch, service=service,
        source=video_plan(always_main=gate == "always_main"))
    result = capture_three(s, clock)
    assert result["review_required"] is True and result["history"] == [] and len(calls.capture) == 3
    assert len(result["review_packet"]["video_playback"]["samples"]) == 3
    if service:
        assert len(service.calls) == (1 if gate == "shadow" else 0)
    assert s.runtime.tick(force=True) is None
    reviewed = s.runtime.control(review_request(s, result, original), "picture-main-review")
    assert reviewed["status"] == "completed" and len(calls.capture) == 3


@pytest.mark.parametrize("stage", ["capture", "decision", "authentication"])
def test_total_budget_rejects_late_result_without_replaying(stage, tmp_path, monkeypatch):
    service = OfflineAssessment(disposition="continue")
    s, _, clock, calls = picture_scene(tmp_path, monkeypatch, service=service,
        slow_capture=7.1 if stage == "capture" else 0)
    if stage == "decision":
        service.during = lambda: setattr(clock, "seconds", 8.1)
    elif stage == "authentication":
        validate, validations = service.validate_result, []
        def late(value, **binding):
            validations.append(binding)
            if len(validations) == 2:
                clock.seconds = 8.1
            return validate(value, **binding)
        monkeypatch.setattr(service, "validate_result", late)
    s.runtime.tick(force=True)
    for seconds in (1, 1.5, 2):
        clock.seconds = max(clock.seconds, seconds)
        result = s.runtime.tick(force=True)
        if result.get("review_required"):
            break
    assert result["review_required"] is True and "budget" in result["review_packet"]["reason"]
    assert result["history"] == [] and len(calls.capture) == (1 if stage == "capture" else 3)
    assert len(service.calls) == (0 if stage == "capture" else 1)
    assert s.runtime.tick(force=True) is None


@pytest.mark.parametrize("claim", ["capture_claimed", "assessment_claimed"])
def test_unknown_claim_stops_without_new_read_or_judgment(tmp_path, monkeypatch, claim):
    service = OfflineAssessment(disposition="continue")
    s, original, clock, calls = picture_scene(tmp_path, monkeypatch, service=service)
    s.runtime.tick(force=True)
    ledger = module.VideoPlaybackLedger(s.runtime.backend, original.command_id)
    if claim == "assessment_claimed":
        class Interrupted(BaseException):
            pass
        def interrupted(*args, **kwargs):
            raise Interrupted()
        monkeypatch.setattr(module, "assess", interrupted)
        for seconds in (1, 1.5):
            clock.seconds = seconds
            s.runtime.tick(force=True)
        clock.seconds = 2
        with pytest.raises(Interrupted):
            s.runtime.tick(force=True)
    else:
        ledger.append(claim, {"index": 1, "claimed_ns": 1_000_000_000})
    clock.seconds = 2.1
    result = s.runtime.tick(force=True)
    assert result["review_required"] is True and "unknown" in result["review_packet"]["reason"]
    assert len(calls.capture) == (3 if claim == "assessment_claimed" else 0) and service.calls == []


def test_elapsed_budget_starts_after_original_render_grace(tmp_path, monkeypatch):
    s, _, clock, calls = picture_scene(tmp_path, monkeypatch)
    clock.seconds = 50
    s.runtime.tick(force=True)
    clock.seconds = 50.999
    s.runtime.tick(force=True)
    assert calls.capture == []
    clock.seconds = 51
    s.runtime.tick(force=True)
    assert len(calls.capture) == 1


def test_distinct_captures_with_identical_pixels_are_sent_once_to_decision(tmp_path, monkeypatch):
    from hashlib import sha256
    from pathlib import Path
    service = OfflineAssessment(disposition="review_required")
    s, _, clock, calls = picture_scene(tmp_path, monkeypatch, service=service)
    capture = module.capture_followup
    pixels = []
    def static_picture(*args, **kwargs):
        value = capture(*args, **kwargs)
        path = Path(value["frame"]["image_path"])
        if not pixels:
            pixels.append(path.read_bytes())
        path.write_bytes(pixels[0])
        value["frame"]["sha256"] = sha256(pixels[0]).hexdigest()
        return value
    monkeypatch.setattr(module, "capture_followup", static_picture)
    result = capture_three(s, clock)
    assert result["review_required"] is True and result["history"] == []
    samples = service.calls[0]["temporal_context"]["samples"]
    assert len({item["frame"]["sha256"] for item in samples}) == 1
    assert len({item["frame"]["capture_id"] for item in samples}) == 3
    assert len(service.calls) == 1 and len(calls.capture) == 3


@pytest.mark.parametrize("damage", ["window", "size", "duplicate", "hash"])
def test_capture_integrity_is_preserved(tmp_path, monkeypatch, damage):
    s, original, clock, calls = picture_scene(tmp_path, monkeypatch)
    capture = module.capture_followup
    def damaged(*args, **kwargs):
        value = capture(*args, **kwargs)
        if damage == "window":
            value["frame"]["window_identity"]["process_create_time"] += 1
        elif damage == "size":
            from PIL import Image
            from hashlib import sha256
            from pathlib import Path
            path = Path(value["frame"]["image_path"])
            Image.new("RGB", (81, 60), "blue").save(path)
            value["frame"]["sha256"] = sha256(path.read_bytes()).hexdigest()
        elif damage == "duplicate":
            value["frame"]["capture_id"] = original.capture["capture_id"]
        else:
            value["frame"]["sha256"] = "0" * 64
        return value
    s.runtime.tick(force=True)
    monkeypatch.setattr(module, "capture_followup", damaged)
    clock.seconds = 1
    result = s.runtime.tick(force=True)
    assert result["history"] == [] and len(calls.capture) == 1
    assert result.get("review_required") or result["wait"].get("error")
