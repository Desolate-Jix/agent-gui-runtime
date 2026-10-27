"""Read-only observation settlement uses the original queue, packets and history."""
from copy import deepcopy

import pytest

from app.core.json_snapshot import read_json_snapshot, write_json_snapshot
from tests.test_session_input_task_plan import control
from tests.test_session_input_terminal import inspect, save
from tests.test_task_plan_adaptive_review import adaptive_plan, review_request
from tests.test_task_plan_manual_observation import manual_scene, observe_request


def observed_plan(tmp_path, monkeypatch, *, count=1, replay=False, finish=True, rejected=False,
        rejection_at=None, terminal_replay=False, maintained_capture=False):
    root = tmp_path / "session"
    root.mkdir()
    source = adaptive_plan(count=1)
    s, original, waiting, calls, _ = manual_scene(root, monkeypatch, source=source)
    if maintained_capture:
        from hashlib import sha256
        from types import SimpleNamespace
        from PIL import Image
        from app.execution import task_plan_manual_observation as manual
        from app.execution import task_plan_observation_capture as capture
        monkeypatch.setattr(manual, "capture_followup", capture.capture_followup)
        s.co._owner = SimpleNamespace(call=lambda fn: fn())
        def capture_memory(*args, **kwargs):
            path = root / "captures" / "maintained-source.png"
            Image.new("RGB", (80, 60), "blue").save(path)
            calls.append(path.stem)
            return {"capture_id": "source-capture-independent-of-observation-id", "image_path": str(path),
                "sha256": sha256(path.read_bytes()).hexdigest(), "window_identity": deepcopy(s.target),
                "window_rect": [0, 0, 80, 60], "image_size": {"width": 80, "height": 60}}, None
        monkeypatch.setattr(capture, "capture_memory_observation", capture_memory)
    command = {"kind": "task_plan", "request": {"action": "start", "plan": source}}
    save(root, "commands", "plan-start", command)
    save(root, "responses", "plan-start", {"status": "returned", "command": command, "result": s.first})
    if rejected or rejection_at is not None:
        from app.execution import task_plan_manual_observation as manual
        capture = manual.capture_followup
        attempts = []
        def failed_capture(*args, **kwargs):
            attempts.append(kwargs["observation_id"])
            if rejected or len(attempts) == rejection_at:
                raise ValueError("task_plan_observation_capture_failed")
            return capture(*args, **kwargs)
        monkeypatch.setattr(manual, "capture_followup", failed_capture)
    request = observe_request(s, waiting)
    observed = control(s, request, "observe-original")
    for index in range(1, count):
        observed = control(s, observe_request(s, observed, logical="manual-" + str(index + 1)),
            "observe-" + str(index + 1))
    if replay:
        observed = control(s, request, "observe-replay")
    if finish:
        control(s, review_request(s, observed, original), "review-original")
        final = control(s, {"action": "continue", "run_id": s.run_id,
            "wait_id": waiting["wait"]["wait_id"]}, "continue-original")
        assert final["runner_state"] == "completed"
        if terminal_replay:
            observed = control(s, request, "observe-after-terminal")
    return s, original, waiting, observed, calls


@pytest.mark.parametrize("count,replay", [(1, False), (1, True), (2, True)])
def test_successful_observe_settles_read_only_without_replaying_original(tmp_path, monkeypatch, count, replay):
    s, original, _, observed, calls = observed_plan(tmp_path, monkeypatch, count=count, replay=replay)
    before = {p: p.read_bytes() for p in s.session.rglob("*") if p.is_file()}
    proof = inspect(s.session)
    assert proof["commands"][original.command_id]["action_executed"] is True
    for key in ["observe-original", *(["observe-2"] if count == 2 else []),
            *(["observe-replay"] if replay else [])]:
        assert proof["commands"][key] == {"kind": "task_plan", "terminal_status": "completed",
            "action_executed": False, "run_id": s.run_id}
    assert len(calls) == count
    assert len([p for p in (s.session / "commands").glob("*.json")
        if read_json_snapshot(p)["kind"] != "task_plan"]) == 1
    assert before == {p: p.read_bytes() for p in s.session.rglob("*") if p.is_file()}


def test_completed_capture_rejection_has_a_bound_read_only_settlement(tmp_path, monkeypatch):
    s, original, _, observed, calls = observed_plan(tmp_path, monkeypatch, rejected=True)
    assert observed["manual_observation"]["status"] == "rejected" and calls == []
    before = {p: p.read_bytes() for p in s.session.rglob("*") if p.is_file()}
    proof = inspect(s.session)
    assert proof["commands"][original.command_id]["action_executed"] is True
    assert proof["commands"]["observe-original"] == {"kind": "task_plan", "terminal_status": "completed",
        "action_executed": False, "run_id": s.run_id}
    assert before == {p: p.read_bytes() for p in s.session.rglob("*") if p.is_file()}


@pytest.mark.parametrize("rejection_at", [1, 2])
def test_captured_and_rejected_observations_share_the_original_packet_chain(tmp_path, monkeypatch, rejection_at):
    s, original, _, _, calls = observed_plan(tmp_path, monkeypatch, count=2, rejection_at=rejection_at)
    proof = inspect(s.session)
    assert len(calls) == 1 and proof["commands"][original.command_id]["action_executed"] is True
    assert all(proof["commands"][key]["action_executed"] is False for key in ("observe-original", "observe-2"))


def test_terminal_logical_observation_reread_preserves_read_only_settlement(tmp_path, monkeypatch):
    s, _, _, observed, calls = observed_plan(tmp_path, monkeypatch, terminal_replay=True)
    assert observed["runner_state"] == "completed" and "review_packet" not in observed
    assert len(calls) == 1
    assert inspect(s.session)["commands"]["observe-after-terminal"]["action_executed"] is False


def test_maintained_capture_keeps_source_capture_identity_when_settling(tmp_path, monkeypatch):
    s, _, _, observed, calls = observed_plan(tmp_path, monkeypatch, maintained_capture=True)
    assert observed["manual_observation"]["frame"]["capture_id"] == "source-capture-independent-of-observation-id"
    assert len(calls) == 1
    assert inspect(s.session)["commands"]["observe-original"]["action_executed"] is False


@pytest.mark.parametrize("damage", ["execution_id", "step_id", "wait_id", "packet_hash", "response_frame",
    "response_packet", "response_wait", "request_hash", "request_result", "result_read_only", "result_boolean_type", "reserved", "unknown",
    "missing_revision", "missing_record", "missing_packet", "missing_image", "image_bytes", "image_hash",
    "orphan_artifact", "budget", "intermediate_unknown"])
def test_missing_changed_or_unknown_observation_evidence_never_settles(tmp_path, monkeypatch, damage):
    s, original, _, observed, _ = observed_plan(tmp_path, monkeypatch)
    trial_path = s.runtime.backend._path(s.run_id)
    trial = read_json_snapshot(trial_path)
    entries = trial["manual_observations"][original.command_id]
    saved = entries["requests"]["manual-one"]
    response = read_json_snapshot(s.session / "responses" / "observe-original.json")
    if damage in {"execution_id", "step_id", "wait_id", "packet_hash"}:
        key = {"execution_id": "execution_request_id", "packet_hash": "review_packet_sha256"}.get(damage, damage)
        response["command"]["request"][key] = "0" * 64 if damage == "packet_hash" else "other-identity"
        save(s.session, "commands", "observe-original", response["command"])
    if damage == "response_frame": response["result"]["manual_observation"]["frame"]["capture_id"] = "other-frame"
    if damage == "response_packet": response["result"]["review_packet"]["after"]["sha256"] = "0" * 64
    if damage == "response_wait": response["result"]["wait"]["wait_id"] = "other-wait"
    if damage == "request_hash": saved["request_sha256"] = "0" * 64
    if damage == "request_result": saved["result"]["observation_request_id"] = "other-logical"
    if damage == "result_read_only": saved["result"]["read_only"] = False
    if damage == "result_boolean_type": saved["result"]["read_only"] = 1
    if damage == "reserved": saved["status"] = "reserved"
    if damage == "unknown": saved["result"]["status"] = "unknown"
    if damage == "missing_revision": entries["revisions"] = []
    if damage == "missing_record": (s.session / saved["record_ref"]["path"]).unlink()
    if damage == "missing_packet": (s.session / entries["revisions"][0]["packet_ref"]["path"]).unlink()
    image = s.session / read_json_snapshot(s.session / saved["record_ref"]["path"])["image_ref"]["path"] if damage != "missing_record" else None
    if damage == "missing_image": image.unlink()
    if damage == "image_bytes": image.write_bytes(image.read_bytes() + b"changed")
    if damage == "image_hash":
        record_path = s.session / saved["record_ref"]["path"]
        record = read_json_snapshot(record_path)
        record["frame"]["sha256"] = "0" * 64
        write_json_snapshot(record_path, record)
    if damage == "orphan_artifact":
        save(s.session, "task-plan-manual-observations/" + original.command_id, "unknown-middle", {"status": "unknown"})
    if damage == "budget": saved["capture_budget"]["remaining"] = 0
    if damage == "intermediate_unknown":
        extra = deepcopy(saved)
        extra["status"] = "reserved"
        entries["requests"]["unknown-extra"] = extra
    write_json_snapshot(trial_path, trial)
    save(s.session, "responses", "observe-original", response)
    with pytest.raises(ValueError, match="session_input_"):
        inspect(s.session)

@pytest.mark.parametrize("damage", ["reserved", "unknown", "result_mismatch", "half_record", "half_png"])
def test_capture_rejection_with_unfinished_or_half_written_artifacts_never_settles(tmp_path, monkeypatch, damage):
    from app.execution.task_plan_review import digest
    s, original, _, _, _ = observed_plan(tmp_path, monkeypatch, rejected=True)
    path = s.runtime.backend._path(s.run_id)
    trial = read_json_snapshot(path)
    saved = trial["manual_observations"][original.command_id]["requests"]["manual-one"]
    if damage == "reserved": saved["status"] = "reserved"
    if damage == "unknown": saved["result"]["status"] = "unknown"
    if damage == "result_mismatch": saved["result"]["observation_request_id"] = "wrong-request"
    if damage == "half_record":
        save(s.session, "task-plan-manual-observations/" + original.command_id,
            "capture-" + digest(saved["request"]), {"status": "unknown"})
    if damage == "half_png":
        from PIL import Image
        identifier = "task-manual-" + digest([s.run_id, original.command_id, "manual-one"])[:32]
        directory = s.session / "task-plan-observations"
        directory.mkdir(exist_ok=True)
        Image.new("RGB", (80, 60), "red").save(directory / (identifier + ".png"))
    write_json_snapshot(path, trial)
    with pytest.raises(ValueError, match="session_input_"):
        inspect(s.session)

