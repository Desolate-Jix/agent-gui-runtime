"""准备清理重试与持久化重开必须保持相同学习来源。"""

import pytest

from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStoreError
from app.agent_link.contracts import AgentLinkError
from app.agent_link.learning_runtime_binding import LearningRuntimeBinding
from app.agent_link.store import AgentLinkStore
from app.api.agent_runtime import AgentRuntimeCallsiteError
from tests.test_formal_learning_runtime_binding import _fixture, _make_callsite, TASK


def _binding(owner, connection, segment):
    return LearningRuntimeBinding(owner, connection["connection_id"], TASK, segment["segment_id"])


def test_claim_read_failure_retry_finishes_exact_learning_child(tmp_path, monkeypatch):
    store, _, connection, recorder, owner, segment = _fixture(tmp_path)
    try:
        binding = _binding(owner, connection, segment)
        runtime, _, _, backend = _make_callsite(tmp_path, binding)
        observation = runtime.start_session()
        original = runtime._claim_store.find_for_observation

        def unavailable(**kwargs):
            raise RuntimeIntentClaimStoreError("injected transient read failure")

        monkeypatch.setattr(runtime._claim_store, "find_for_observation", unavailable)
        with pytest.raises(AgentRuntimeCallsiteError):
            runtime.cancel_prepared_session(session_id=observation.session_id)
        monkeypatch.setattr(runtime._claim_store, "find_for_observation", original)
        runtime.cancel_prepared_session(session_id=observation.session_id)
        current = owner.get(connection_id=connection["connection_id"], task_id=TASK, segment_id=segment["segment_id"])
        assert current["children"][0]["phase"] == "cancelled"
        assert recorder.list_learning_sessions()[0]["status"] == "finished"
        assert backend.attempt_count == 0
    finally:
        store.close()


@pytest.mark.parametrize("through_callsite", [False, True])
def test_partial_bind_cleanup_retries_metadata_and_finishes_existing_recorder(tmp_path, monkeypatch, through_callsite):
    store, _, connection, recorder, owner, segment = _fixture(tmp_path)
    try:
        binding = _binding(owner, connection, segment)
        original = store.mutate
        failures = {"commit_bound": 1, "commit_cancelled": int(through_callsite)}

        def fail_commit(change):
            name = change.__name__
            if failures.get(name, 0):
                failures[name] -= 1
                raise AgentLinkError("persistence_failed", "injected commit failure")
            return original(change)

        monkeypatch.setattr(store, "mutate", fail_commit)
        if through_callsite:
            runtime, _, _, backend = _make_callsite(tmp_path, binding)
            with pytest.raises(AgentRuntimeCallsiteError):
                runtime.start_session()
            assert runtime.cancel_local_preparation()["cleanup_verified"] is True
            assert backend.attempt_count == 0
        else:
            with pytest.raises(AgentLinkError):
                binding.attach_validated_runtime(runtime_session_id="session.partial")
            binding.close_unconsumed(runtime_session_id="session.partial")
        current = owner.get(connection_id=connection["connection_id"], task_id=TASK, segment_id=segment["segment_id"])
        assert current["children"][0]["phase"] == "cancelled"
        assert recorder.list_learning_sessions()[0]["status"] == "finished"
    finally:
        store.close()


def test_cancelled_segment_reopens_without_corrupting_inbox(tmp_path):
    store, _, connection, recorder, owner, segment = _fixture(tmp_path)
    binding = _binding(owner, connection, segment)
    binding.attach_validated_runtime(runtime_session_id="session.cancelled")
    current = binding.close_unconsumed(runtime_session_id="session.cancelled")
    owner.finish(connection_id=connection["connection_id"], task_id=TASK,
                 segment_id=segment["segment_id"], expected_revision=current["revision"])
    store.close()
    reopened = AgentLinkStore(tmp_path / "agent-link.json")
    try:
        actual = reopened.read(lambda state: state["connections"][connection["connection_id"]]["learning_segments"][segment["segment_id"]])
        assert actual["status"] == "closed" and actual["children"][0]["phase"] == "cancelled"
    finally:
        reopened.close()


def test_closed_segment_cannot_create_new_runtime_binding(tmp_path):
    store, _, connection, _, owner, segment = _fixture(tmp_path)
    try:
        owner.finish(connection_id=connection["connection_id"], task_id=TASK,
                     segment_id=segment["segment_id"], expected_revision=segment["revision"])
        with pytest.raises(AgentLinkError) as denied:
            _binding(owner, connection, segment)
        assert denied.value.code == "learning_busy"
    finally:
        store.close()
