import hashlib
import json

import pytest

from app.agent.action_learning_recorder import ActionLearningRecorder, ActionLearningRecorderError
from tests.test_formal_action_learning_provenance import _bytes, _fresh
from tests.test_formal_action_learning_recorder import _controller, _UnknownBackend
from tests.test_live_controller_w4 import _intent


def _reseal(value):
    payload = dict(value)
    payload.pop("content_sha256")
    value["content_sha256"] = hashlib.sha256(_bytes(payload)).hexdigest()


@pytest.mark.parametrize("field", ["capture_id", "screenshot_sha256", "viewport", "bbox", "click", "pid", "window", "selection_sha256", "grounding_sha256", "current_observation_sha256"])
def test_resealed_before_must_match_committed_dispatch_checkpoint(tmp_path, field):
    recorder, _, _, backend, _, _ = _fresh(tmp_path)
    ledger = json.loads(recorder.ledger_path.read_text(encoding="utf-8"))
    event = next(iter(ledger["sessions"]["learning.provenance"]["events"].values()))
    before = event["before"]
    if field == "capture_id":
        before["capture"][field] = "capture.forged"
    elif field == "screenshot_sha256":
        before["capture"][field] = "0" * 64
    elif field == "viewport":
        before["geometry"]["viewport_size"]["width"] += 1
    elif field == "bbox":
        before["geometry"]["bbox"]["x"] += 1
    elif field == "click":
        before["geometry"]["click_point"][0] += 1
    elif field == "pid":
        before["geometry"]["target_process_id"] += 1
    elif field == "window":
        before["geometry"]["target_window_handle"] += 1
    else:
        before[field] = "0" * 64
    _reseal(before)
    _reseal(event)
    forged = _bytes(ledger)
    recorder.ledger_path.write_bytes(forged)

    with pytest.raises(ActionLearningRecorderError, match="authoritative"):
        ActionLearningRecorder(project_root=tmp_path)
    assert recorder.ledger_path.read_bytes() == forged
    assert backend.attempt_count == 1


def test_source_read_is_revision_bound_and_uses_current_not_initial_or_post(tmp_path):
    recorder, runtime, _, backend, _, _ = _fresh(tmp_path)
    session = recorder.get_learning_session(learning_session_id="learning.provenance")
    result = recorder.read_learning_session_sources(
        learning_session_id="learning.provenance", runtime_session_id=runtime.session_id,
        expected_revision=session["revision"],
    )
    event_id = next(iter(session["events"]))
    assert result["session"] == session
    assert result["before_sources"][event_id]["status"] == "verified"
    assert len(result["before_sources"][event_id]["checkpoint_sha256"]) == 64
    assert session["events"][event_id]["before"]["capture"]["capture_id"] == "capture-current"
    result["session"]["events"][event_id]["before"]["capture"]["capture_id"] = "mutated"
    assert recorder.get_learning_session(learning_session_id="learning.provenance") == session
    with pytest.raises(ActionLearningRecorderError, match="revision"):
        recorder.read_learning_session_sources(
            learning_session_id="learning.provenance", runtime_session_id=runtime.session_id,
            expected_revision=session["revision"] + 1,
        )
    assert backend.attempt_count == 1


def test_unknown_without_checkpoint_is_retained_but_before_source_unavailable(tmp_path):
    recorder = ActionLearningRecorder(project_root=tmp_path)
    backend = _UnknownBackend()
    controller, _, _, _, _ = _controller(tmp_path, recorder, backend=backend)
    runtime = controller.start_session()
    recorder.start_learning_session(learning_session_id="learning.unknown", runtime_session_id=runtime.session_id)
    receipt = controller.submit_intent(_intent(runtime))
    session = recorder.get_learning_session(learning_session_id="learning.unknown")
    result = recorder.read_learning_session_sources(
        learning_session_id="learning.unknown", runtime_session_id=runtime.session_id,
        expected_revision=session["revision"],
    )
    event_id = next(iter(session["events"]))
    assert result["session"] == session
    assert result["before_sources"][event_id] == {
        "status": "unavailable", "reason": "verification_checkpoint_unavailable",
        "checkpoint_sha256": None,
    }
    assert receipt.outcome == result["session"]["events"][event_id]["terminal"]["outcome"] == "INDETERMINATE"
    assert backend.attempt_count == 1


def test_recording_read_does_not_repair_a_missing_terminal_marker(tmp_path):
    recorder, runtime, _, backend, claims, _ = _fresh(tmp_path)
    identity = claims._identity_hash(runtime.session_id, runtime.current_observation.observation_id)
    marker = claims._terminal_path(identity)
    marker.unlink()
    with pytest.raises(ActionLearningRecorderError, match="authoritative"):
        recorder.get_learning_session(learning_session_id="learning.provenance")
    assert not marker.exists()
    assert backend.attempt_count == 1
