import hashlib
import json

import pytest

from app.agent.action_learning_recorder import ActionLearningRecorder, ActionLearningRecorderError
from app.agent.runtime_intent_claim_store import STORE_ROOT as CLAIM_ROOT
from app.agent.runtime_receipt_store import STORE_ROOT as RECEIPT_ROOT
from tests.test_formal_action_learning_recorder import _controller
from tests.test_live_controller_w4 import _intent


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _fresh(root):
    recorder = ActionLearningRecorder(project_root=root)
    controller, _, backend, claims, receipts = _controller(root, recorder)
    runtime = controller.start_session()
    recorder.start_learning_session(learning_session_id="learning.provenance", runtime_session_id=runtime.session_id)
    receipt = controller.submit_intent(_intent(runtime))
    assert receipt.outcome == "VERIFIED" and backend.attempt_count == 1
    return recorder, runtime, receipt, backend, claims, receipts


@pytest.mark.parametrize("target", ["terminal_reason", "terminal_action", "before_intent"])
def test_resealed_ledger_projection_must_match_authoritative_receipt(tmp_path, target):
    recorder, _, receipt, backend, _, _ = _fresh(tmp_path)
    ledger = json.loads(recorder.ledger_path.read_text(encoding="utf-8"))
    event = next(iter(ledger["sessions"]["learning.provenance"]["events"].values()))
    if target == "terminal_reason":
        event["terminal"]["reason_code"] = "backend_result_lost"
    elif target == "terminal_action":
        event["terminal"]["action"]["action_id"] = "action.forged"
    else:
        event["before"]["intent_id"] = "intent.forged"
        payload = dict(event["before"])
        payload.pop("content_sha256")
        event["before"]["content_sha256"] = hashlib.sha256(_bytes(payload)).hexdigest()
    payload = dict(event)
    payload.pop("content_sha256")
    event["content_sha256"] = hashlib.sha256(_bytes(payload)).hexdigest()
    forged = _bytes(ledger)
    recorder.ledger_path.write_bytes(forged)

    with pytest.raises(ActionLearningRecorderError, match="authoritative"):
        recorder.get_learning_session(learning_session_id="learning.provenance")
    with pytest.raises(ActionLearningRecorderError, match="authoritative"):
        ActionLearningRecorder(project_root=tmp_path)
    assert recorder.ledger_path.read_bytes() == forged
    assert receipt.reason_code == "none" and backend.attempt_count == 1


def test_completed_record_revalidates_authoritative_receipt_on_each_read(tmp_path):
    recorder, runtime, _, backend, claims, receipts = _fresh(tmp_path)
    ref = claims.get_for_observation(session_id=runtime.session_id, observation_id=runtime.current_observation.observation_id).terminal_receipt_ref
    receipts._object_path(ref["content_sha256"]).unlink()
    with pytest.raises(ActionLearningRecorderError, match="authoritative"):
        recorder.get_learning_session(learning_session_id="learning.provenance")
    assert not receipts._object_path(ref["content_sha256"]).exists()
    assert backend.attempt_count == 1


def test_copied_ledger_without_authority_does_not_recreate_missing_store_layout(tmp_path):
    recorder, _, _, backend, _, _ = _fresh(tmp_path / "source")
    isolated = tmp_path / "isolated"
    ledger_path = isolated / "runtime_state/action-learning-v1/ledger.json"
    ledger_path.parent.mkdir(parents=True)
    ledger_path.write_bytes(recorder.ledger_path.read_bytes())
    with pytest.raises(ActionLearningRecorderError, match="authoritative"):
        ActionLearningRecorder(project_root=isolated)
    assert not (isolated / RECEIPT_ROOT).exists()
    assert not (isolated / CLAIM_ROOT).exists()
    assert backend.attempt_count == 1


def test_concurrent_change_during_unlocked_verification_is_not_overwritten(tmp_path, monkeypatch):
    recorder = ActionLearningRecorder(project_root=tmp_path)
    other = ActionLearningRecorder(project_root=tmp_path)
    original = recorder._validate_authoritative_events
    changed = False

    def concurrent_change(ledger):
        nonlocal changed
        original(ledger)
        if not changed:
            changed = True
            other.start_learning_session(learning_session_id="learning.other", runtime_session_id="session.other")

    monkeypatch.setattr(recorder, "_validate_authoritative_events", concurrent_change)
    with pytest.raises(ActionLearningRecorderError, match="changed during verification"):
        recorder.start_learning_session(learning_session_id="learning.main", runtime_session_id="session.main")
    sessions = other.list_learning_sessions()
    assert [session["learning_session_id"] for session in sessions] == ["learning.other"]


def test_terminal_observer_cannot_mutate_recording_or_returned_receipt(tmp_path):
    recorder = ActionLearningRecorder(project_root=tmp_path)
    controller, _, backend, claims, _ = _controller(tmp_path, None)

    def mutate_observer(verified):
        object.__setattr__(verified.record.runtime_receipt, "reason_code", "backend_result_lost")
        if verified.record.verification_evidence is not None:
            verified.record.verification_evidence["status"] = "forged"

    claims.add_terminal_receipt_observer(mutate_observer)
    controller.set_action_learning_recorder(recorder)
    runtime = controller.start_session()
    recorder.start_learning_session(learning_session_id="learning.provenance", runtime_session_id=runtime.session_id)
    receipt = controller.submit_intent(_intent(runtime))
    event = next(iter(recorder.get_learning_session(learning_session_id="learning.provenance")["events"].values()))
    assert event["terminal"]["outcome"] == receipt.outcome == "VERIFIED"
    assert event["terminal"]["reason_code"] == receipt.reason_code == "none"
    assert backend.attempt_count == 1
