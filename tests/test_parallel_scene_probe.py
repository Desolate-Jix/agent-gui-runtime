"""并行预检仅产生关联数据；所有计算均为受控离线回调。"""
from hashlib import sha256
from importlib import import_module
import json
from threading import Event
from time import perf_counter, perf_counter_ns

import pytest
from pydantic import ValidationError

from app.judgment.profile import DecisionProfile


IDENTITY = {"handle": 100, "process_id": 200, "process_create_time": 1234.5}


def binding():
    return {"capture_id": "frame-1", "attempt_id": "attempt-1", "window_identity": dict(IDENTITY)}


def grounded(**kwargs):
    return {**binding(), "candidate": {"bbox": {"x": 1, "y": 2, "w": 3, "h": 4}}}


def scene(disposition="pass", **changes):
    return {**binding(), "disposition": disposition, "authenticated": True, **changes}


def run(ground=grounded, probe=lambda **kwargs: scene(), *, budget_ms=1000, cancelled=lambda: False):
    return import_module("app.execution.parallel_scene_probe").run_parallel_scene_probe(
        ground=ground, probe=probe, deadline_ns=perf_counter_ns() + budget_ms * 1_000_000, cancelled=cancelled)


@pytest.mark.parametrize("version,expected", [
    ("decision_profile.v1", "b1febc5086362f8d5d6ce86e9e1d499fab0567fe487653e82c80bfb436b6a2af"),
    ("decision_profile.v2", "635a6d1ddfbe559efac8e2287c6b2ea5b6b64ee41536c700b5401ca974e05d71"),
])
def test_absent_scene_precheck_keeps_legacy_dump_and_hash(version, expected):
    profile = DecisionProfile(contract_version=version)
    assert profile.scene_precheck == "off"
    assert "scene_precheck" not in profile.model_dump()
    assert "scene_precheck" not in profile.model_dump(mode="json")
    assert "scene_precheck" not in json.loads(profile.model_dump_json())
    encoded = json.dumps(profile.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()
    assert sha256(encoded).hexdigest() == expected


@pytest.mark.parametrize("choice", ["off", "parallel"])
def test_explicit_v2_scene_precheck_roundtrips(choice):
    profile = DecisionProfile(contract_version="decision_profile.v2", scene_precheck=choice)
    assert profile.scene_precheck == choice
    assert profile.model_dump(mode="json")["scene_precheck"] == choice
    assert DecisionProfile.model_validate_json(profile.model_dump_json()).scene_precheck == choice


@pytest.mark.parametrize("choice", ["off", "parallel", None, True, "PARALLEL"])
def test_explicit_v1_scene_precheck_is_rejected(choice):
    with pytest.raises(ValidationError):
        DecisionProfile(contract_version="decision_profile.v1", scene_precheck=choice)


@pytest.mark.parametrize("choice", [None, True, 1, "PARALLEL", ""])
def test_invalid_v2_scene_precheck_is_rejected(choice):
    with pytest.raises(ValidationError):
        DecisionProfile(contract_version="decision_profile.v2", scene_precheck=choice)


def test_parallel_scene_pass_never_authorizes_candidate():
    result = run()
    assert result["status"] == "joined"
    assert result["grounding"]["candidate"]["bbox"] == {"x": 1, "y": 2, "w": 3, "h": 4}
    assert result["scene"]["disposition"] == "pass"
    assert result["authorizes_action"] is False
    assert result["requires_candidate_review"] is True


def test_workers_share_original_deadline_and_run_concurrently():
    ground_started, probe_started = Event(), Event()
    observed = []
    deadline = perf_counter_ns() + 1_000_000_000

    def ground(*, deadline_ns, cancelled):
        observed.append(deadline_ns)
        ground_started.set()
        assert probe_started.wait(.5)
        assert not cancelled()
        return grounded()

    def probe(*, deadline_ns, cancelled):
        observed.append(deadline_ns)
        probe_started.set()
        assert ground_started.wait(.5)
        assert not cancelled()
        return scene()

    result = import_module("app.execution.parallel_scene_probe").run_parallel_scene_probe(
        ground=ground, probe=probe, deadline_ns=deadline, cancelled=lambda: False)
    assert result["status"] == "joined"
    assert observed == [deadline, deadline]


@pytest.mark.parametrize("field", ["capture_id", "attempt_id", "window_identity"])
def test_same_frame_attempt_and_window_required_at_join(field):
    invalid = scene()
    invalid[field] = "other" if field != "window_identity" else {**IDENTITY, "process_create_time": 9999}
    result = run(probe=lambda **kwargs: invalid)
    assert result["status"] == "unknown"
    assert result["grounding"] is None
    assert result["authorizes_action"] is False


@pytest.mark.parametrize("field", ["capture_id", "attempt_id", "window_identity"])
def test_missing_binding_cannot_be_adopted(field):
    invalid = scene()
    invalid.pop(field)
    result = run(probe=lambda **kwargs: invalid)
    assert result["status"] == "unknown"
    assert result["grounding"] is None


def test_early_block_cancels_grounding_without_waiting_for_it():
    started, stopped = Event(), Event()

    def ground(*, deadline_ns, cancelled):
        started.set()
        while not cancelled():
            stopped.wait(.005)
        stopped.set()
        return grounded()

    def probe(**kwargs):
        assert started.wait(.5)
        return scene("block")

    result = run(ground=ground, probe=probe)
    assert result["status"] == "blocked"
    assert result["grounding"] is None
    assert result["cancellation_requested"] is True
    assert result["authorizes_action"] is False
    assert stopped.wait(.5)


@pytest.mark.parametrize("disposition", ["unknown", "unavailable"])
def test_unknown_or_unavailable_probe_does_not_claim_block(disposition):
    result = run(probe=lambda **kwargs: scene(disposition, authenticated=False))
    assert result["status"] == "joined"
    assert result["scene"]["disposition"] == disposition
    assert result["grounding"]["candidate"]


@pytest.mark.parametrize("disposition", ["block", "pass"])
def test_unverified_scene_result_cannot_be_adopted(disposition):
    result = run(probe=lambda **kwargs: scene(disposition, authenticated=False))
    assert result["status"] == "unknown"
    assert result["grounding"] is None


def test_extra_probe_records_attempts_without_claiming_paid_requests():
    result = run()
    assert result["started_attempts"] == {"ground": 1, "probe": 1}
    assert result["cancellation_does_not_imply_no_charge"] is True
    assert "paid_requests" not in result


def test_timeout_does_not_join_uncooperative_http_or_adopt_late_result():
    release, started, exited = Event(), Event(), Event()

    def ground(**kwargs):
        started.set()
        try:
            release.wait(5)
            return grounded()
        finally:
            exited.set()

    begin = perf_counter()
    try:
        result = run(ground=ground, budget_ms=50)
        assert started.is_set()
        assert result["status"] == "timeout"
        assert result["grounding"] is None and result["scene"] is None
        assert result["unfinished_at_return"] == ["ground"]
        assert perf_counter() - begin < .5
    finally:
        release.set()
    assert exited.wait(.5)
    assert result["grounding"] is None


def test_cancelled_in_flight_result_is_not_adopted():
    external_cancel, started = Event(), Event()

    def ground(**kwargs):
        started.set()
        external_cancel.set()
        return grounded()

    result = run(ground=ground, cancelled=external_cancel.is_set)
    assert started.is_set()
    assert result["status"] == "cancelled"
    assert result["grounding"] is None and result["scene"] is None


def test_pre_cancelled_attempt_starts_no_workers():
    result = run(cancelled=lambda: True)
    assert result["status"] == "cancelled"
    assert result["started_attempts"] == {"ground": 0, "probe": 0}


def test_expired_attempt_starts_no_workers():
    result = run(budget_ms=-1)
    assert result["status"] == "timeout"
    assert result["started_attempts"] == {"ground": 0, "probe": 0}


def test_worker_error_returns_unknown_without_exception_text():
    def failed(**kwargs):
        raise OSError("credential-like provider detail")

    result = run(probe=failed)
    assert result["status"] == "unknown"
    assert result["errors"] == {"probe": "OSError"}
    assert "credential-like" not in json.dumps(result)
