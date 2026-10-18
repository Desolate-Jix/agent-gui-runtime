"""未知持久结果保留，但已停止的本地执行所有者可以退出。"""
from hashlib import sha256

import pytest

from app.desktop_review.single_step import NativeSingleStepController
from tests.test_fresh_dispatch_graph import _ready, _close


@pytest.mark.parametrize("failure", ["after_before_record", "after_dispatch_marker"])
def test_preparation_failure_releases_local_owner_without_rewriting_or_retry(tmp_path, monkeypatch, failure):
    host, _, runtime, backend, claims, session, _, confirmation_id = _ready(tmp_path)
    native = NativeSingleStepController()
    native.attach(runtime, confirmation_id=confirmation_id)
    native.set_accepting(True)
    try:
        if failure == "after_before_record":
            import app.agent.learned_control_reference as reference
            original = runtime._action_learning_recorder.record_before
            def record_then_invalidate(**kwargs):
                result = original(**kwargs)
                def unavailable(*args):
                    raise ValueError("isolated late pinned memory failure")
                monkeypatch.setattr(reference, "revalidate_learned_control", unavailable)
                return result
            monkeypatch.setattr(runtime._action_learning_recorder, "record_before", record_then_invalidate)
        else:
            original = claims.mark_fresh_dispatch_started
            def mark_then_lose_result(**kwargs):
                original(**kwargs)
                raise OSError("isolated dispatch marker reply loss")
            monkeypatch.setattr(claims, "mark_fresh_dispatch_started", mark_then_lose_result)
        result = native.execute_server(confirmation_id=confirmation_id)
        assert result["payload"]["reason_code"] == "fresh_dispatch_preparation_failed"
        before = claims.get_for_grounded_confirmation(confirmation_id=confirmation_id)
        expected = "grounded_confirmation_consume_started" if failure == "after_before_record" else "dispatch_started"
        assert before.phase == expected and before.recovery_required is True
        preserved = {p: sha256(p.read_bytes()).hexdigest() for p in tmp_path.rglob("*.json")}
        native.cleanup_attachment(confirmation_id=confirmation_id)
        assert native.attachment_snapshot() is None
        assert session.session_id not in runtime._sessions
        assert session.session_id not in runtime._grounded_publications
        after = claims.get_for_grounded_confirmation(confirmation_id=confirmation_id)
        assert after == before
        assert runtime.release_local_fresh_recovery(confirmation_id=confirmation_id) == before
        assert all(p.exists() and sha256(p.read_bytes()).hexdigest() == digest for p, digest in preserved.items())
        assert runtime.consume_grounded_confirmation(confirmation_id=confirmation_id).reason_code == "fresh_dispatch_indeterminate"
        from app.agent.fresh_learning_action_contracts import FreshLearningIntent
        from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
        from app.agent.runtime_receipt_store import RuntimeReceiptStore
        reopened = RuntimeIntentClaimStore(project_root=claims.project_root,
            receipt_store=RuntimeReceiptStore(project_root=claims.project_root))
        persisted = reopened.get_for_grounded_confirmation(confirmation_id=confirmation_id)
        assert persisted.phase == expected and persisted.recovery_required is True
        assert persisted.grounded_confirmation.owner_is_current is False
        changed_intent = FreshLearningIntent.from_dict({**before.intent.to_dict(), "intent_id": "intent.cannot-retry"})
        with pytest.raises(ValueError, match="conflict"):
            reopened.claim_fresh_learning(observation=before.observation.to_dict(), intent=changed_intent,
                source_reference=runtime._binding.source.reference())
        assert backend.commands == []
        native.cleanup_attachment()
    finally:
        _close(host, runtime)


def test_unconsumed_approval_cannot_be_treated_as_recovery_release(tmp_path):
    host, _, runtime, backend, _, session, _, confirmation_id = _ready(tmp_path)
    try:
        with pytest.raises(ValueError, match="durable phase"):
            runtime.release_local_fresh_recovery(confirmation_id=confirmation_id)
        assert session.session_id in runtime._sessions and backend.commands == []
    finally:
        _close(host, runtime)


def test_window_release_failure_retains_attachment_and_retry_is_no_input(tmp_path, monkeypatch):
    from app.desktop_review.single_step import NativeSingleStepError
    host, _, runtime, backend, claims, session, _, confirmation_id = _ready(tmp_path)
    native = NativeSingleStepController()
    native.attach(runtime, confirmation_id=confirmation_id)
    native.set_accepting(True)
    mark, release = claims.mark_fresh_dispatch_started, runtime._release_window_lease
    try:
        def lost(**kwargs):
            mark(**kwargs)
            raise OSError("isolated marker reply loss")
        monkeypatch.setattr(claims, "mark_fresh_dispatch_started", lost)
        native.execute_server(confirmation_id=confirmation_id)
        def release_failed(lease):
            raise OSError("isolated lease release failure")
        monkeypatch.setattr(runtime, "_release_window_lease", release_failed)
        with pytest.raises(NativeSingleStepError, match="cleanup could not be verified"):
            native.cleanup_attachment(confirmation_id=confirmation_id)
        assert native.attachment_snapshot() is not None
        assert session.session_id in runtime._sessions
        monkeypatch.setattr(runtime, "_release_window_lease", release)
        native.cleanup_attachment(confirmation_id=confirmation_id)
        assert native.attachment_snapshot() is None
        assert claims.get_for_grounded_confirmation(confirmation_id=confirmation_id).phase == "dispatch_started"
        assert backend.commands == []
    finally:
        monkeypatch.setattr(runtime, "_release_window_lease", release)
        _close(host, runtime)


@pytest.mark.parametrize("exit_mode", ["cancel_then_shutdown", "shutdown"])
def test_real_host_and_owner_thread_exit_with_pending_memory_failure(tmp_path, monkeypatch, exit_mode):
    from tests.test_fresh_agent_stdio import _rig
    from tests.test_learned_control_reference import _saved

    with _rig(tmp_path) as (host, coordinator, connection, segment, staged, instances):
        service, token = host._service, connection["token"]
        prepared = service.agent_call(token, "prepare_fresh_learning_runtime", {
            "segment_id": segment["segment_id"], "batch_id": staged["batch_id"], "idempotency_key": "release-late"})
        runtime, backend = instances[0][1:3]
        _, _, selected = _saved(host, runtime._binding.source)
        scope = {"segment_id": segment["segment_id"], "preparation_id": prepared["preparation_id"]}
        service.agent_call(token, "request_fresh_learning_action", {**scope,
            "intent_id": "intent.late-release", "action_id": "action.view",
            "semantic_action": "open_detail", "goal": "View details", "learned_control": selected})
        view = coordinator.current_fresh_review()
        coordinator.approve(confirmation_id=view["confirmation_id"], preview_content_sha256=view["preview"]["preview_sha256"])
        recorder = host.learning_segments.recorder
        original, reader = recorder.record_before, host.facade.get_interface_memory
        def record_then_invalidate(**kwargs):
            result = original(**kwargs)
            def unavailable(*args, **keys):
                raise ValueError("isolated pinned memory unavailable after recording")
            monkeypatch.setattr(host.facade, "get_interface_memory", unavailable)
            return result
        monkeypatch.setattr(recorder, "record_before", record_then_invalidate)
        result = coordinator.execute(confirmation_id=view["confirmation_id"])
        assert result["payload"]["reason_code"] == "fresh_dispatch_preparation_failed"
        monkeypatch.setattr(host.facade, "get_interface_memory", reader)
        claims = runtime._intent_claim_store
        before = claims.get_for_grounded_confirmation(confirmation_id=view["confirmation_id"])
        recorded = recorder.list_learning_sessions()
        assert any(item["pending_before_refs"] for item in recorded)
        if exit_mode == "cancel_then_shutdown":
            assert coordinator.cancel()["cleanup_verified"] is True
            factual = service.agent_call(token, "get_fresh_learning_runtime", scope)
            assert factual["cleanup_verified"] is True
            assert factual["recovery_required"] is True
            assert factual["claim_phase"] == "grounded_confirmation_consume_started"
        coordinator.shutdown()
        assert host.status()["phase"] == "stopped"
        assert not coordinator._owner._thread.is_alive()
        assert prepared["session_id"] not in runtime._sessions
        assert claims.get_for_grounded_confirmation(confirmation_id=view["confirmation_id"]) == before
        assert recorder.list_learning_sessions() == recorded
        assert backend.commands == []
