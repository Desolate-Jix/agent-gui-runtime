"""专用播放核验复用原票据；所有桌面与判断边界均使用离线合成证据。"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from app.execution.task_plan_contract import validate_task_plan
from tests.test_task_plan_adaptive_review import OfflineAssessment, review_request
from tests.test_task_plan_runner import complete_original, scene


CONDITION = "The intended video has started playback during the observed interval."


def video_plan(*, count=1, always_main=False):
    rule = {"kind": "video_playback", "decision_condition": CONDITION}
    if always_main:
        rule["review_policy"] = "always_main"
    return {"schema_version": "task_plan.v2", "title": "Start intended video", "inputs": {},
        "steps": [{"step_id": "step-" + str(i), "action": {"kind": "click", "goal": "Open intended video"},
            "verification": deepcopy(rule)} for i in range(count)]}


def test_video_contract_is_explicit_v2_and_uses_short_default_render_grace():
    from app.execution.task_plan_backend import TaskPlanBackend
    value = video_plan()
    assert validate_task_plan(value) == value
    assert TaskPlanBackend._command(value["steps"][0], {})["observation_wait_ms"] == 500
    value["schema_version"] = "task_plan.v1"
    with pytest.raises(ValueError):
        validate_task_plan(value)


@pytest.mark.parametrize("patch", [{"wait_policy": {}}, {"goal": "video"}, {"decision_condition": ""},
    {"review_policy": "adaptive"}, {"render_grace_ms": True}, {"render_grace_ms": 2001}])
def test_video_contract_rejects_undeclared_authority_and_parallel_wait(patch):
    value = video_plan()
    value["steps"][0]["verification"].update(patch)
    with pytest.raises(ValueError):
        validate_task_plan(value)


def playback_scene(tmp_path, monkeypatch, *, service=None, mode="progress", source=None, slow_capture=0):
    from app.execution import video_playback_verification as module
    s = scene(tmp_path, monkeypatch, source=source or video_plan(), decision=service)
    original = complete_original(s, native=False)
    original.receipt["result"]["observation"]["capture"].update(
        image_size={"width": 80, "height": 60}, window_rect=[0, 0, 80, 60])
    write_json_snapshot(tmp_path / "responses" / (original.command_id + ".json"), original.receipt)
    clock = SimpleNamespace(seconds=0.0)
    monkeypatch.setattr(module, "now_ns", lambda: int(clock.seconds * 1e9))
    calls = SimpleNamespace(capture=[], locate=[], observe=[])
    region = {"bbox": [0, 0, 80, 60], "content_bbox": [0, 0, 80, 50], "masks": []}
    def locate(coordinator, frame, **kwargs):
        calls.locate.append(deepcopy(frame))
        return {"region": deepcopy(region), "evidence": {"fixture": "offline", "source_frame": deepcopy(frame)}, "refs": []}
    def capture(coordinator, **kwargs):
        kwargs["cancelled"]()
        calls.capture.append(kwargs["observation_id"])
        clock.seconds += slow_capture
        path = tmp_path / "captures" / (kwargs["observation_id"] + ".png")
        Image.new("RGB", (80, 60), (10 * len(calls.capture), 0, 0)).save(path)
        return {"frame": {"capture_id": kwargs["observation_id"], "image_path": str(path),
            "sha256": sha256(path.read_bytes()).hexdigest(), "window_identity": deepcopy(s.target),
            "role": "observation"}, "capture_elapsed_ms": slow_capture * 1000}
    def observe(frame, locator, **kwargs):
        calls.observe.append(frame["capture_id"])
        index = int(frame["capture_id"].rsplit("-", 1)[1])
        return {"capture_id": frame["capture_id"], "position_seconds": float(index) if mode == "progress" else None,
            "state": "paused" if mode == "paused" else "playing" if mode == "progress" else "unknown"}
    monkeypatch.setattr(module, "locate_player", locate)
    monkeypatch.setattr(module, "capture_followup", capture)
    monkeypatch.setattr(module, "observe_player_frame", observe)
    monkeypatch.setattr(module, "observation_evidence_refs", lambda *args, **kwargs: [])
    monkeypatch.setattr(module, "page_loading", lambda *args, **kwargs: False, raising=False)
    return s, original, clock, calls


def tick_samples(s, clock, *, count=3):
    s.runtime.tick(force=True)
    result = None
    for index in range(count):
        clock.seconds = 1 + index * .5
        result = s.runtime.tick(force=True)
    return result


def _first_sample(s, clock):
    s.runtime.tick(force=True)
    clock.seconds = 1
    return s.runtime.tick(force=True)


def test_unknown_original_never_localizes_or_captures(tmp_path, monkeypatch):
    s, _, _, calls = playback_scene(tmp_path, monkeypatch)
    complete_original(s, status="unknown", native=False)
    result = s.runtime.tick(force=True)
    assert result["history"] == [] and calls.locate == [] and calls.capture == []



def test_always_main_keeps_complete_sample_packet_for_bound_review_continue(tmp_path, monkeypatch):
    s, original, clock, calls = playback_scene(tmp_path, monkeypatch, source=video_plan(always_main=True))
    waiting = tick_samples(s, clock)
    assert waiting["review_required"] is True and waiting["history"] == []
    packet = waiting["review_packet"]
    assert packet["schema"] == "review_packet.v4" and len(packet["video_playback"]["samples"]) == 3
    assert packet["reason"] == "decision_always_main"
    reviewed = s.runtime.control(review_request(s, waiting, original), "video-main-review")
    assert reviewed["status"] == "completed" and len(calls.capture) == 3
    resumed = s.runtime.control({"action": "continue", "run_id": s.run_id,
        "wait_id": waiting["wait"]["wait_id"]}, "video-main-continue")
    assert resumed["status"] == "completed" and len(list(tmp_path.glob("commands/*.json"))) == 1



def test_restore_with_unfinished_capture_claim_never_replays_capture(tmp_path, monkeypatch):
    from app.execution.video_playback_verification import VideoPlaybackLedger
    s, _, clock, calls = playback_scene(tmp_path, monkeypatch)
    _first_sample(s, clock)
    ledger = VideoPlaybackLedger(s.runtime.backend, s.runtime.backend.status(s.run_id)["pending"]["execution_request_id"])
    ledger.append("capture_claimed", {"index": 2, "claimed_ns": int(1.5e9)})
    clock.seconds = 1.5
    result = s.runtime.tick(force=True)
    assert result["review_required"] is True and "unknown" in result["review_packet"]["reason"]
    assert len(calls.capture) == 1 and len(list(tmp_path.glob("commands/*.json"))) == 1



def test_cancel_stops_sampling_and_settles_original_input_fact(tmp_path, monkeypatch):
    s, original, clock, calls = playback_scene(tmp_path, monkeypatch)
    _first_sample(s, clock)
    s.runtime.control({"action": "cancel", "run_id": s.run_id}, "video-cancel")
    clock.seconds = 1.5
    final = s.runtime.tick(force=True)
    assert final["status"] == "cancelled" and len(calls.capture) == 1
    assert final["history"][0]["execution_request_id"] == original.command_id
    assert final["history"][0]["original_input_status"] == "completed"



def test_policy_change_stops_before_new_capture(tmp_path, monkeypatch):
    service = OfflineAssessment()
    s, _, clock, calls = playback_scene(tmp_path, monkeypatch, service=service)
    _first_sample(s, clock)
    monkeypatch.setattr(service, "status", lambda: {"contract_version": "decision_profile.v2", "profile_sha256": "f" * 64})
    clock.seconds = 1.5
    result = s.runtime.tick(force=True)
    assert result["review_required"] is True and "profile_changed" in result["review_packet"]["reason"]
    assert len(calls.capture) == 1 and service.calls == []



def test_tampered_sample_cannot_be_adopted_or_reviewed(tmp_path, monkeypatch):
    s, _, clock, calls = playback_scene(tmp_path, monkeypatch)
    _first_sample(s, clock)
    path = tmp_path / "captures" / (calls.capture[0] + ".png")
    Image.new("RGB", (80, 60), "blue").save(path)
    clock.seconds = 1.5
    result = s.runtime.tick(force=True)
    assert result["history"] == [] and "review_packet" not in result
    assert result["wait"].get("error") and len(calls.capture) == 1



def test_uncertain_no_api_packet_contains_all_samples_and_does_not_poll_again(tmp_path, monkeypatch):
    s, original, clock, calls = playback_scene(tmp_path, monkeypatch, mode="unknown")
    waiting = tick_samples(s, clock, count=3)
    assert waiting["review_required"] is True and waiting["history"] == []
    packet = waiting["review_packet"]
    assert len(packet["video_playback"]["samples"]) == len(calls.capture) == 3
    for item in packet["video_playback"]["samples"]:
        assert item["frame"]["role"] == "observation"
        assert item["frame"]["capture_id"] != original.capture["capture_id"]
    clock.seconds = 100
    assert s.runtime.tick(force=True) is None
    reviewed = s.runtime.control(review_request(s, waiting, original), "no-api-video-main-review")
    assert reviewed["status"] == "completed" and len(calls.capture) == 3



@pytest.mark.parametrize("damage", ["missing_proof", "forged_analysis", "forged_local_success", "wrong_policy"])
def test_backend_rejects_forged_or_policy_forbidden_playing_success(tmp_path, monkeypatch, damage):
    s, original, clock, _ = playback_scene(tmp_path, monkeypatch, source=video_plan(always_main=True))
    tick_samples(s, clock)
    state = s.runtime.backend.status(s.run_id)
    result = deepcopy(next(iter(state["verification_results"].values())))
    result.pop("review_packet", None)
    result.update(verdict="success", judged_by="video_playback", reason="video_playback_confirmed")
    if damage == "missing_proof":
        result.pop("video_playback")
    elif damage == "forged_analysis":
        result["video_playback"]["analysis"] = {"status": "playing"}
    elif damage == "forged_local_success":
        result["video_playback"]["samples"][0]["elapsed_ms"] = 999
    with pytest.raises(ValueError, match="task_plan_video"):
        s.runtime.backend.record_verified_result(s.run_id, "forged-video-success", original.command_id,
            result, target_identity=lambda: deepcopy(s.target))
    assert s.runtime.backend.status(s.run_id)["history"] == []



@pytest.mark.parametrize("stage", ["api", "backend_authentication"])
def test_temporal_late_completion_is_reviewed_without_repeating_request(tmp_path, monkeypatch, stage):
    service = OfflineAssessment(disposition="continue")
    s, original, clock, calls = playback_scene(tmp_path, monkeypatch, service=service, mode="unknown")
    if stage == "api":
        service.during = lambda: setattr(clock, "seconds", 8.1)
    else:
        validate, validations = service.validate_result, []
        def late(value, **binding):
            validations.append(binding)
            if len(validations) == 2:
                clock.seconds = 8.1
            return validate(value, **binding)
        monkeypatch.setattr(service, "validate_result", late)
    waiting = tick_samples(s, clock, count=3)
    assert waiting["review_required"] is True and "budget" in waiting["review_packet"]["reason"]
    assert waiting["history"] == [] and len(service.calls) == 1 and len(calls.capture) == 3
    assert s.runtime.tick(force=True) is None
    s.runtime.control(review_request(s, waiting, original), "late-video-main-review")
    assert len(service.calls) == 1



def test_process_clock_change_requires_review_and_preserves_original_budget(tmp_path, monkeypatch):
    from app.execution import video_playback_verification as module
    s, _, clock, calls = playback_scene(tmp_path, monkeypatch)
    _first_sample(s, clock)
    monkeypatch.setattr(module, "CLOCK_ID", "different-process")
    clock.seconds = 1.5
    waiting = s.runtime.tick(force=True)
    assert "clock_changed" in waiting["review_packet"]["reason"] and len(calls.capture) == 1



def test_original_window_identity_change_stops_before_next_sample(tmp_path, monkeypatch):
    s, _, clock, calls = playback_scene(tmp_path, monkeypatch)
    _first_sample(s, clock)
    s.target["process_create_time"] += 1
    clock.seconds = 1.5
    stopped = s.runtime.tick(force=True)
    assert stopped["history"] == [] and len(calls.capture) == 1
    assert stopped["wait"].get("error") or stopped.get("review_required")



def test_verified_ledger_reuses_parsed_events_only_within_the_current_phase(tmp_path, monkeypatch):
    from pathlib import Path
    from app.execution import video_playback_verification as module
    s, original, clock, _ = playback_scene(tmp_path, monkeypatch)
    _first_sample(s, clock)
    ledger = module.VideoPlaybackLedger(s.runtime.backend, original.command_id)
    reads = []
    for name in ("read_bytes", "read_text"):
        read = getattr(Path, name)
        def counted(path, *args, _read=read, **kwargs):
            if path.parent == ledger.root:
                reads.append(str(path))
            return _read(path, *args, **kwargs)
        monkeypatch.setattr(Path, name, counted)
    original_events = ledger.read()
    first_read_count = len(reads)
    for _ in range(8):
        assert ledger.header()["execution_request_id"] == original.command_id
        assert len(ledger.samples()) == 1
        ledger.payloads("analyzed")
    assert len(reads) == first_read_count
    original_events[0]["payload"]["owner_id"] = "caller-mutated"
    assert ledger.header()["owner_id"] == s.runtime.backend.owner_id
    ledger.summary()
    assert len(reads) > first_read_count



def _change_latest_event_with_identical_size_and_mtime(ledger):
    import json
    import os
    path = sorted(ledger.root.glob("*.json"))[-1]
    before, stat = path.read_bytes(), path.stat()
    value = json.loads(before.decode("utf-8"))
    event = value["event"]
    value["event"] = event[:-1] + ("z" if event[-1] != "z" else "x")
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    assert len(raw) == len(before)
    path.write_bytes(raw)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert path.stat().st_mtime_ns == stat.st_mtime_ns



def test_guard_refresh_detects_same_size_same_mtime_tamper_and_clears_cache(tmp_path, monkeypatch):
    from app.execution import video_playback_verification as module
    s, original, clock, _ = playback_scene(tmp_path, monkeypatch)
    _first_sample(s, clock)
    ledger = module.VideoPlaybackLedger(s.runtime.backend, original.command_id)
    ledger.read()
    _change_latest_event_with_identical_size_and_mtime(ledger)
    with pytest.raises(ValueError, match="task_plan_video_chain"):
        module._guard(s.runtime.backend, s.runtime.backend.status(s.run_id), ledger, None, lambda: deepcopy(s.target))
    assert ledger._cached_events is None
    with pytest.raises(ValueError, match="task_plan_video_chain"):
        ledger.read()



@pytest.mark.parametrize("boundary", ["capture"])
def test_external_boundary_never_trusts_previous_phase_ledger_cache(tmp_path, monkeypatch, boundary):
    from app.execution import video_playback_verification as module
    s, original, clock, calls = playback_scene(tmp_path, monkeypatch)
    function_name = "locate_player" if boundary == "locator" else "capture_followup"
    operation = getattr(module, function_name)
    def tampered(*args, **kwargs):
        result = operation(*args, **kwargs)
        _change_latest_event_with_identical_size_and_mtime(module.VideoPlaybackLedger(s.runtime.backend, original.command_id))
        return result
    monkeypatch.setattr(module, function_name, tampered)
    waiting = _first_sample(s, clock)
    assert waiting["history"] == [] and "review_packet" not in waiting
    assert "chain" in waiting["wait"]["error"]["message"]
    assert len(calls.capture) == (1 if boundary == "capture" else 0)



@pytest.mark.parametrize("boundary", ["decision", "adoption"])
def test_temporal_decision_and_adoption_refresh_reject_ledger_tampering(tmp_path, monkeypatch, boundary):
    from app.execution import video_playback_verification as module
    service = OfflineAssessment(disposition="continue")
    s, original, clock, calls = playback_scene(tmp_path, monkeypatch, service=service, mode="unknown")
    def tamper():
        _change_latest_event_with_identical_size_and_mtime(module.VideoPlaybackLedger(s.runtime.backend, original.command_id))
    if boundary == "decision":
        service.during = tamper
    else:
        validate, validations = service.validate_result, []
        def after_authentication(value, **binding):
            validations.append(binding)
            if len(validations) == 2:
                tamper()
            return validate(value, **binding)
        monkeypatch.setattr(service, "validate_result", after_authentication)
    waiting = tick_samples(s, clock, count=3)
    assert waiting["history"] == [] and "review_packet" not in waiting
    assert waiting["wait"].get("error") and len(service.calls) == 1 and len(calls.capture) == 3
    assert len(list(tmp_path.glob("commands/*.json"))) == 1


def _legacy_ledger(s, original):
    from app.execution import video_playback_verification as module
    s.runtime.tick(force=True)
    ledger = module.VideoPlaybackLedger(s.runtime.backend, original.command_id)
    path = ledger.root / "0000.json"
    # 合成历史 v1 原件；生产恢复路径不得改写旧账本版本。
    event = read_json_snapshot(path)
    event["payload"]["analysis_policy"] = module.LEGACY_ANALYSIS_POLICY
    write_json_snapshot(path, event)
    return module.VideoPlaybackLedger(s.runtime.backend, original.command_id)


def test_unfinished_v1_ledger_requires_main_without_reinterpreting_or_resampling(tmp_path, monkeypatch):
    s, original, clock, calls = playback_scene(tmp_path, monkeypatch)
    ledger = _legacy_ledger(s, original)
    clock.seconds = 1
    result = s.runtime.tick(force=True)
    assert result["review_required"] is True and result["history"] == []
    assert result["review_packet"]["reason"] == "video_playback_legacy_requires_main_review"
    assert result["review_packet"]["video_playback"]["schema"] == "video_playback_binding.v1"
    assert calls.capture == [] and calls.locate == [] and calls.observe == []
    assert ledger.header()["analysis_policy"] == "video_playback_local.v1"


def test_completed_v1_pixel_progress_proof_still_uses_original_authentication(tmp_path, monkeypatch):
    from app.execution import video_playback_verification as module
    from app.execution.task_plan_observation_evidence import reference
    s, original, clock, calls = playback_scene(tmp_path, monkeypatch)
    ledger = _legacy_ledger(s, original)
    locator = module.locate_player(None, ledger.header()["original_frame"])
    ledger.append("location_claimed", {"claimed_ns": 0})
    ledger.append("located", {"locator": locator, "completed_ns": 0})
    for index in range(1, 4):
        clock.seconds = (index - 1) * .5
        stamp = module.now_ns()
        ledger.append("capture_claimed", {"index": index, "claimed_ns": stamp})
        captured = module.capture_followup(None, observation_id="legacy-frame-" + str(index), cancelled=lambda: False)
        frame = captured["frame"]
        ledger.append("captured", {"index": index, "frame": frame, "image_ref": reference(tmp_path, frame["image_path"]),
            "elapsed_ms": clock.seconds * 1000, "capture_elapsed_ms": 0, "completed_ns": stamp,
            "observation": module.observe_player_frame(frame, locator), "observation_refs": []})
    analysis = module._analysis(ledger.samples(), locator["region"])
    assert analysis["status"] == "playing"
    ledger.append("analyzed", {"analysis": analysis, "analysis_elapsed_ms": 0})
    module._finish(ledger, "video_playback_confirmed")
    summary = ledger.summary()
    assert summary["schema"] == "video_playback_binding.v1" and module._outcome(ledger)["local_success"] is True
    state = s.runtime.backend.status(s.run_id)
    valid = module.validate_video_playback(s.runtime.backend, state, summary, ledger.artifacts(), ledger.header()["after"])
    assert valid.summary() == summary
    monkeypatch.setattr(module, "observe_player_frame", lambda frame, *args, **kwargs:
        {"capture_id": frame["capture_id"], "position_seconds": None, "state": "unknown"})
    with pytest.raises(ValueError, match="sample_proof_invalid"):
        module.validate_video_playback(s.runtime.backend, state, summary, ledger.artifacts(), ledger.header()["after"])
