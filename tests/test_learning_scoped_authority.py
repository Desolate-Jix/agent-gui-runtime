import json

import pytest

from app.agent.action_learning_recorder import ActionLearningRecorder, ActionLearningRecorderError
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
from tests.test_formal_action_learning_provenance import _bytes
from tests.test_formal_action_learning_recorder import _controller
from tests.test_live_controller_w4 import _intent


@pytest.fixture
def two_sessions(tmp_path):
    recorder = ActionLearningRecorder(project_root=tmp_path)
    entries = []
    for index in range(2):
        controller, _, backend, claims, receipts = _controller(tmp_path, recorder)
        runtime = controller.start_session()
        learning_id = f"learning.scope-{index}"
        recorder.start_learning_session(learning_session_id=learning_id, runtime_session_id=runtime.session_id)
        receipt = controller.submit_intent(_intent(runtime))
        assert receipt.outcome == "VERIFIED" and backend.attempt_count == 1
        snapshot = claims.get_for_observation(
            session_id=runtime.session_id, observation_id=runtime.current_observation.observation_id,
        )
        entries.append((learning_id, runtime, backend, receipts._object_path(snapshot.terminal_receipt_ref["content_sha256"])))
    return recorder, entries


def _read(recorder, entry, method):
    learning_id, runtime, _, _ = entry
    if method == "get":
        return recorder.get_learning_session(learning_session_id=learning_id)
    if method == "binding":
        return recorder.get_active_learning_binding(runtime_session_id=runtime.session_id)
    return recorder.read_learning_session_sources(
        learning_session_id=learning_id, runtime_session_id=runtime.session_id, expected_revision=3,
    )


@pytest.mark.parametrize("method", ["get", "sources", "binding"])
def test_single_session_read_only_proves_requested_events(two_sessions, monkeypatch, method):
    recorder, entries = two_sessions
    calls = []
    original = RuntimeIntentClaimStore.read_committed_terminal_evidence

    def observed(self, *, session_id, observation_id):
        calls.append(session_id)
        return original(self, session_id=session_id, observation_id=observation_id)

    monkeypatch.setattr(RuntimeIntentClaimStore, "read_committed_terminal_evidence", observed)
    _read(recorder, entries[0], method)
    assert calls == [entries[0][1].session_id]
    calls.clear()
    recorder.list_learning_sessions()
    assert sorted(calls) == sorted(entry[1].session_id for entry in entries)
    calls.clear()
    recorder.start_learning_session(learning_session_id="learning.new", runtime_session_id="session.new")
    assert sorted(calls) == sorted(entry[1].session_id for entry in entries)
    assert all(entry[2].attempt_count == 1 for entry in entries)


@pytest.mark.parametrize("method", ["get", "sources", "binding"])
def test_unrelated_authority_failure_is_isolated_but_global_audit_rejects(two_sessions, method):
    recorder, entries = two_sessions
    entries[1][3].write_bytes(b"{}")
    _read(recorder, entries[0], method)
    with pytest.raises(ActionLearningRecorderError, match="authoritative"):
        _read(recorder, entries[1], method)
    with pytest.raises(ActionLearningRecorderError, match="authoritative"):
        recorder.list_learning_sessions()
    with pytest.raises(ActionLearningRecorderError, match="authoritative"):
        recorder.start_learning_session(learning_session_id="learning.new", runtime_session_id="session.new")
    with pytest.raises(ActionLearningRecorderError, match="authoritative"):
        ActionLearningRecorder(project_root=recorder.project_root)
    assert all(entry[2].attempt_count == 1 for entry in entries)


@pytest.mark.parametrize("method", ["get", "sources", "binding"])
def test_each_target_read_revalidates_authority_without_cache(two_sessions, method):
    recorder, entries = two_sessions
    _read(recorder, entries[0], method)
    entries[0][3].write_bytes(b"{}")
    with pytest.raises(ActionLearningRecorderError, match="authoritative"):
        _read(recorder, entries[0], method)
    assert entries[0][2].attempt_count == 1


@pytest.mark.parametrize("method", ["get", "sources", "binding"])
@pytest.mark.parametrize("damage", ["canonical", "schema", "event_hash", "binding"])
def test_full_ledger_structure_still_checked_for_scoped_read(two_sessions, method, damage):
    recorder, entries = two_sessions
    ledger = json.loads(recorder.ledger_path.read_text(encoding="utf-8"))
    other = ledger["sessions"][entries[1][0]]
    if damage == "canonical":
        recorder.ledger_path.write_bytes(_bytes(ledger) + b"\n")
    else:
        if damage == "schema":
            other["unexpected"] = True
        elif damage == "event_hash":
            next(iter(other["events"].values()))["content_sha256"] = "0" * 64
        else:
            ledger["runtime_bindings"][entries[1][1].session_id] = entries[0][0]
        recorder.ledger_path.write_bytes(_bytes(ledger))
    with pytest.raises(ActionLearningRecorderError):
        _read(recorder, entries[0], method)
    assert all(entry[2].attempt_count == 1 for entry in entries)


def test_unbound_runtime_does_not_prove_unrelated_events(two_sessions, monkeypatch):
    recorder, _ = two_sessions

    def unexpected(*args, **kwargs):
        pytest.fail("unbound runtime must not verify unrelated terminal evidence")

    monkeypatch.setattr(RuntimeIntentClaimStore, "read_committed_terminal_evidence", unexpected)
    assert recorder.get_active_learning_binding(runtime_session_id="session.unbound") is None


def test_segment_read_cost_tracks_own_events_not_other_history(tmp_path, monkeypatch):
    from tests.test_formal_learning_segments import TASK, _connection, _owners, _perform_action, _start

    store, service, recorder, archive, owner = _owners(tmp_path)
    try:
        target = _connection(service)
        segment = _start(owner, target)
        own = [
            _perform_action(tmp_path, owner, recorder, archive, target, segment["segment_id"], sequence=index)
            for index in (1, 2)
        ]
        other = _connection(service, "other-agent")
        unrelated = _start(owner, other)
        foreign = _perform_action(tmp_path, owner, recorder, archive, other, unrelated["segment_id"], sequence=3)
        calls = []
        original = RuntimeIntentClaimStore.read_committed_terminal_evidence

        def observed(self, *, session_id, observation_id):
            calls.append(session_id)
            return original(self, session_id=session_id, observation_id=observation_id)

        monkeypatch.setattr(RuntimeIntentClaimStore, "read_committed_terminal_evidence", observed)
        result = owner.get(connection_id=target["connection_id"], task_id=TASK, segment_id=segment["segment_id"])
        assert result["source_status"] == "complete"
        assert len(calls) == 6
        assert all(calls.count(item[0].session_id) == 3 for item in own)
        assert foreign[0].session_id not in calls
        assert all(item[2].attempt_count == 1 for item in own + [foreign])
    finally:
        store.close()
