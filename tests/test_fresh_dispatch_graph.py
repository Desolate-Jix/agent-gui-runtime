"""首次学习批准后经同一派发和权威记录链进入同段图。"""

import pytest

from app.agent.fresh_learning_action_contracts import FreshLearningIntent
from app.agent.live_controller import LiveControllerDecision
from tests.test_fresh_learning_action_preview import _setup


class _Visible:
    def __init__(self):
        self.calls = []

    def check(self, **kwargs):
        self.calls.append(kwargs)
        return {"bound_window_handle": kwargs["target_window_handle"],
                "point_visibility": {"allowed": True}}


def _ready(tmp_path):
    host, owner, runtime, backend, claims, source, old_session, intent = _setup(tmp_path)
    runtime.cancel_session_preparation(preparation_id="fresh.preview")
    runtime.set_action_learning_recorder(host.fresh_learning.segments.recorder)
    runtime._window_visibility_checker = _Visible()
    session = runtime.start_session()
    scope = {key: source.reference()[key] for key in ("connection_id", "task_id", "segment_id")}
    host.fresh_learning.segments.attach_runtime(**scope, runtime_session_id=session.session_id)
    intent = FreshLearningIntent.from_dict({**intent.to_dict(), "session_id": session.session_id,
        "observation_id": session.current_observation.observation_id})
    claim = runtime.request_grounded_confirmation(intent.to_dict(), target_process_id=9001)
    assert not isinstance(claim, LiveControllerDecision), claim
    confirmation_id = claim.grounded_confirmation.confirmation_id
    approved = runtime.record_grounded_confirmation_decision(confirmation_id=confirmation_id, decision="approved")
    assert approved.phase == "grounded_confirmation_approved"
    return host, owner, runtime, backend, claims, session, scope, confirmation_id


def _close(host, runtime):
    try:
        for session_id in list(runtime._sessions):
            if session_id in runtime._grounded_publications:
                runtime.cancel_grounded_review(session_id=session_id)
            else:
                runtime.abandon_session(session_id=session_id)
    finally:
        # 失败夹具不得把模拟窗口租约泄漏给下一项；生产清理另有显式断言。
        for current in runtime._sessions.values():
            runtime._release_window_lease(current.window_lease)
        host.close()


def test_fresh_confirmed_action_records_once_and_joins_original_images_to_same_graph(tmp_path):
    host, owner, runtime, backend, claims, session, scope, confirmation_id = _ready(tmp_path)
    try:
        result = runtime.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert not isinstance(result, LiveControllerDecision), result
        assert result.outcome == "ACTION_RECORDED"
        assert result.effect_status == "not_verified"
        assert result.destination_status == "not_evaluated"
        assert len(backend.commands) == 1
        assert len(runtime._window_visibility_checker.calls) == 1
        assert runtime.consume_grounded_confirmation(confirmation_id=confirmation_id) == result
        assert len(backend.commands) == 1
        segment = host.fresh_learning.segments.get(**scope)
        child = segment["children"][0]
        recorder = host.fresh_learning.segments.recorder
        learned = recorder.get_learning_session(learning_session_id=child["learning_session_id"])
        assert len(learned["events"]) == 1 and learned["recording_gaps"] == []
        event = next(iter(learned["events"].values()))
        assert "workflow" not in event["before"]
        assert event["terminal"]["next_observation_ref"]["state"] == "unreviewed"
        evidence = host.fresh_learning.segments.capture_archive.read_session_evidence(
            learning_session_id=child["learning_session_id"], runtime_session_id=session.session_id,
            expected_revision=learned["revision"]).evidence()
        assert evidence["event_sources"][0]["before"]["status"] == "available"
        assert evidence["event_sources"][0]["after"]["status"] == "available"
        synced = host.fresh_learning.sync_actions(**scope)
        graph = host.fresh_learning.facade.load_graph_revision(synced["logical_workflow_id"])
        assert len(graph["graph"]["edges"]) == 1
        assert len(graph["graph"]["nodes"]) == 3
        assert session.session_id not in runtime._sessions
    finally:
        _close(host, runtime)


def test_after_capture_failure_cannot_make_approved_action_executable_again(tmp_path, monkeypatch):
    host, owner, runtime, backend, claims, session, scope, confirmation_id = _ready(tmp_path)
    try:
        observe = owner.observe
        def broken_after(**kwargs):
            if backend.commands:
                raise OSError("isolated post-capture failure")
            return observe(**kwargs)
        monkeypatch.setattr(owner, "observe", broken_after)
        result = runtime.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert not isinstance(result, LiveControllerDecision), result
        assert result.outcome == "OBSERVATION_FAILED" and result.next_observation_id is None
        assert runtime.consume_grounded_confirmation(confirmation_id=confirmation_id) == result
        assert len(backend.commands) == 1
    finally:
        _close(host, runtime)


def test_visibility_failure_closes_before_any_input(tmp_path):
    host, owner, runtime, backend, claims, session, scope, confirmation_id = _ready(tmp_path)
    try:
        runtime._window_visibility_checker.check = lambda **kwargs: {
            "bound_window_handle": 999, "point_visibility": {"allowed": True}}
        result = runtime.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert isinstance(result, LiveControllerDecision) and result.status == "REJECTED"
        assert backend.commands == []
        assert claims.get_for_grounded_confirmation(confirmation_id=confirmation_id).phase == "grounded_confirmation_closed"
    finally:
        _close(host, runtime)


def test_graph_write_failure_retries_projection_only_without_another_click(tmp_path, monkeypatch):
    host, owner, runtime, backend, claims, session, scope, confirmation_id = _ready(tmp_path)
    sync = host.fresh_learning.sync_actions
    try:
        def failed_sync(**kwargs):
            raise OSError("isolated graph write failure")
        monkeypatch.setattr(host.fresh_learning, "sync_actions", failed_sync)
        first = runtime.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert isinstance(first, LiveControllerDecision) and first.reason_code == "learning_graph_sync_failed"
        assert claims.get_for_grounded_confirmation(confirmation_id=confirmation_id).phase == "terminal"
        assert len(backend.commands) == 1
        count = len(owner._screenshot_service.calls)
        monkeypatch.setattr(host.fresh_learning, "sync_actions", sync)
        second = runtime.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert second.outcome == "ACTION_RECORDED"
        assert len(backend.commands) == 1 and len(owner._screenshot_service.calls) == count
    finally:
        _close(host, runtime)


def test_lost_backend_response_is_unknown_and_never_retried(tmp_path, monkeypatch):
    host, owner, runtime, backend, claims, session, scope, confirmation_id = _ready(tmp_path)
    dispatch = backend.dispatch
    try:
        def lost(command, **kwargs):
            dispatch(command, **kwargs)
            raise OSError("isolated response loss after input")
        monkeypatch.setattr(backend, "dispatch", lost)
        result = runtime.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert result.outcome == "EXECUTION_UNKNOWN" and result.next_observation_id is None
        assert runtime.consume_grounded_confirmation(confirmation_id=confirmation_id) == result
        assert len(backend.commands) == 1
    finally:
        _close(host, runtime)


def test_terminal_response_loss_can_recover_without_another_dispatch(tmp_path, monkeypatch):
    host, owner, runtime, backend, claims, session, scope, confirmation_id = _ready(tmp_path)
    persist = claims.persist_fresh_terminal
    try:
        def lost(*args, **kwargs):
            persist(*args, **kwargs)
            raise OSError("isolated response loss after terminal commit")
        monkeypatch.setattr(claims, "persist_fresh_terminal", lost)
        first = runtime.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert isinstance(first, LiveControllerDecision) and first.reason_code == "fresh_receipt_persistence_failed"
        second = runtime.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert second.outcome == "ACTION_RECORDED"
        assert len(backend.commands) == 1
    finally:
        _close(host, runtime)


def test_confirmation_from_another_fresh_source_is_not_reused(tmp_path):
    from app.agent.fresh_learning_runtime_session import ServerFreshLearningBinding
    from app.agent.fresh_learning_runtime_source import load_fresh_learning_runtime_source

    host, owner, runtime, backend, claims, session, scope, confirmation_id = _ready(tmp_path)
    try:
        staged = host.fresh_learning.stage(**scope, idempotency_key="other-source",
            title="Other observation", meaning="An independent fresh source",
            packet=session.source.packet)
        source = load_fresh_learning_runtime_source(host.fresh_learning, **scope, batch_id=staged["batch_id"])
        runtime._binding = ServerFreshLearningBinding(source)
        result = runtime.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert isinstance(result, LiveControllerDecision) and result.status == "REJECTED"
        assert result.reason_code == "fresh_learning_source_mismatch"
        assert backend.commands == []
    finally:
        _close(host, runtime)


def test_recorder_gap_is_reported_and_recovered_without_input_retry(tmp_path, monkeypatch):
    host, owner, runtime, backend, claims, session, scope, confirmation_id = _ready(tmp_path)
    recorder = host.fresh_learning.segments.recorder
    write = recorder._write_ledger
    try:
        def fail_event(ledger):
            if any(value["events"] for value in ledger["sessions"].values()):
                raise OSError("isolated terminal observer write failure")
            return write(ledger)
        monkeypatch.setattr(recorder, "_write_ledger", fail_event)
        first = runtime.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert isinstance(first, LiveControllerDecision)
        assert first.reason_code == "learning_graph_pending"
        assert len(backend.commands) == 1
        monkeypatch.setattr(recorder, "_write_ledger", write)
        second = runtime.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert second.outcome == "ACTION_RECORDED"
        assert len(backend.commands) == 1
    finally:
        _close(host, runtime)


def test_same_window_changed_pixels_after_action_observation_blocks_input(tmp_path, monkeypatch):
    from PIL import Image

    host, owner, runtime, backend, claims, session, scope, confirmation_id = _ready(tmp_path)
    observe = owner.observe_for_action
    capture = owner._screenshot_service.capture_window
    pixels_changed = False
    try:
        def capture_changed_pixels(**kwargs):
            result = capture(**kwargs)
            if pixels_changed:
                with Image.open(owner._screenshot_service.path) as image:
                    changed = Image.new("RGB", image.size, "black")
                changed.save(owner._screenshot_service.path)
            return result
        def changed_after_recognition(**kwargs):
            nonlocal pixels_changed
            bundle = observe(**kwargs)
            pixels_changed = True
            return bundle
        monkeypatch.setattr(owner._screenshot_service, "capture_window", capture_changed_pixels)
        monkeypatch.setattr(owner, "observe_for_action", changed_after_recognition)
        result = runtime.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert isinstance(result, LiveControllerDecision) and result.status == "REJECTED"
        assert backend.commands == []
        assert claims.get_for_grounded_confirmation(confirmation_id=confirmation_id).phase == "grounded_confirmation_closed"
    finally:
        _close(host, runtime)


def test_interrupted_dispatch_marker_cannot_retry_and_can_release_local_window(tmp_path, monkeypatch):
    host, owner, runtime, backend, claims, session, scope, confirmation_id = _ready(tmp_path)
    mark = claims.mark_fresh_dispatch_started
    try:
        def lost(*args, **kwargs):
            mark(*args, **kwargs)
            raise OSError("isolated response loss after dispatch marker")
        monkeypatch.setattr(claims, "mark_fresh_dispatch_started", lost)
        first = runtime.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert isinstance(first, LiveControllerDecision) and first.status == "RECOVERY_REQUIRED"
        retry = runtime.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert retry.reason_code == "fresh_dispatch_indeterminate"
        assert backend.commands == []
        cancelled = runtime.cancel_grounded_review(session_id=session.session_id)
        assert isinstance(cancelled, LiveControllerDecision)
        assert cancelled.reason_code == "fresh_dispatch_indeterminate"
        assert session.session_id not in runtime._sessions
        assert claims.get_for_grounded_confirmation(confirmation_id=confirmation_id).phase == "dispatch_started"
        assert backend.commands == []
    finally:
        _close(host, runtime)


def test_source_corruption_during_visibility_capture_blocks_input(tmp_path, monkeypatch):
    host, owner, runtime, backend, claims, session, scope, confirmation_id = _ready(tmp_path)
    observe = owner.observe
    try:
        def corrupt_source_after_probe(**kwargs):
            packet = observe(**kwargs)
            digest = session.source.packet.evidence()["capture"]["screenshot_sha256"]
            (host.fresh_learning.archive.png_root / (digest + ".png")).write_bytes(b"isolated-source-corruption")
            return packet
        monkeypatch.setattr(owner, "observe", corrupt_source_after_probe)
        result = runtime.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert isinstance(result, LiveControllerDecision) and result.status == "REJECTED"
        assert backend.commands == []
        assert claims.get_for_grounded_confirmation(confirmation_id=confirmation_id).phase == "grounded_confirmation_closed"
    finally:
        _close(host, runtime)


@pytest.mark.parametrize("marker,field", [("terminal", "grounded_consume_ref"), ("dispatch", "claim_content_sha256")])
def test_terminal_read_revalidates_all_phase_marker_bindings(tmp_path, marker, field):
    import json
    from app.agent.fresh_learning_action_contracts import canonical_json_bytes
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStoreError

    host, owner, runtime, backend, claims, session, scope, confirmation_id = _ready(tmp_path)
    try:
        receipt = runtime.consume_grounded_confirmation(confirmation_id=confirmation_id)
        assert receipt.outcome == "ACTION_RECORDED"
        identity = claims._identity_hash(session.session_id, session.current_observation.observation_id)
        path = claims._terminal_path(identity) if marker == "terminal" else claims._dispatch_path(identity)
        value = json.loads(path.read_text(encoding="utf-8"))
        value[field] = "fresh-grounded-consume:" + "0" * 64 if marker == "terminal" else "0" * 64
        path.write_bytes(canonical_json_bytes(value))
        with pytest.raises(RuntimeIntentClaimStoreError):
            claims.load_terminal_receipt(session_id=session.session_id,
                observation_id=session.current_observation.observation_id)
        assert len(backend.commands) == 1
    finally:
        _close(host, runtime)
