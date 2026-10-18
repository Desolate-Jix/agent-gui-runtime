"""首次来源进入既有控制器与准备生命周期，不伪装成已审核流程。"""

from dataclasses import FrozenInstanceError
import json

import pytest

from app.agent import live_controller
from app.agent.desktop_backend import DeterministicFakeBackend
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from tests.test_formal_fresh_graph_source import _stage, REVIEWER
from tests.test_formal_fresh_learning_observation import _owner, _ScreenshotService, _OriginReader, _NativeReader


class _UnusedExecutionDependency:
    def __getattr__(self, name):
        raise AssertionError(f"first-use preparation must not call execution dependency: {name}")


def _runtime(host, connection, segment, staged, *, observation_owner=None, source=None):
    assert hasattr(live_controller, "ServerFreshLearningBinding"), "fresh source cannot enter the existing controller"
    from app.agent.fresh_learning_runtime_source import load_fresh_learning_runtime_source

    root = host.fresh_learning.archive.project_root
    scope = {"connection_id": connection["connection_id"], "task_id": connection["task_id"],
             "segment_id": segment["segment_id"], "batch_id": staged["batch_id"]}
    source = source or load_fresh_learning_runtime_source(host.fresh_learning, **scope)
    backend = DeterministicFakeBackend()
    receipts = RuntimeReceiptStore(project_root=root)
    claims = RuntimeIntentClaimStore(project_root=root, receipt_store=receipts)
    runtime = live_controller.LiveController(
        binding=live_controller.ServerFreshLearningBinding(source),
        fresh_source_owner=host.fresh_learning,
        observation_source=observation_owner or _owner(root),
        asset_loader=_UnusedExecutionDependency(),
        target_resolver=_UnusedExecutionDependency(), gate=_UnusedExecutionDependency(),
        window_visibility_checker=_UnusedExecutionDependency(),
        backend=backend, intent_claim_store=claims, grounding_policy={},
    )
    return runtime, backend, claims, source


def test_fresh_committed_source_starts_actual_controller_without_reviewed_asset(tmp_path):
    host, connection, segment, packet, args, staged = _stage(tmp_path)
    runtime = session = None
    try:
        screenshot = _ScreenshotService(host.fresh_learning.archive.project_root)
        runtime, backend, claims, source = _runtime(host, connection, segment, staged,
            observation_owner=_owner(host.fresh_learning.archive.project_root, screenshot=screenshot))
        session = runtime.start_session_preparation(preparation_id="fresh-prepare")
        assert session.source.reference() == source.reference()
        assert session.source.packet.png_bytes == packet.png_bytes
        current = session.current_observation.to_dict()
        assert current["contract_version"] == "fresh_learning_runtime_observation_v1"
        assert current["session_id"] == session.session_id
        assert current["source"] == source.reference()
        assert current["state"] == "unreviewed"
        assert current["execution_ready"] is False and current["available_actions"] == []
        assert current["artifact_is_authorization"] is False
        assert current["capture"]["capture_id"] != packet.evidence()["capture"]["capture_id"]
        assert session.current_observation.packet.png_bytes == screenshot.path.read_bytes()
        assert screenshot.calls == [{"save_image": True, "focus_window": False, "purpose": "learning-observation"}]
        saved = host.fresh_learning.archive.read(current["capture_source"],
            connection_id=connection["connection_id"], task_id=connection["task_id"], segment_id=segment["segment_id"])
        assert saved == session.current_observation.packet
        assert not any(name in json.dumps(current) for name in ("asset_id", "reviewed_revision_hash", "source_workflow_sha256"))
        assert backend.commands == []
        assert claims.find_for_observation(session_id=session.session_id,
            observation_id=session.current_observation.observation_id) is None
        assert not (host.fresh_learning.archive.project_root / "runtime_state/reviewed-workflow-assets-v2").exists()
        current["source"]["batch_id"] = "client-edit"
        assert session.current_observation.to_dict()["source"]["batch_id"] == staged["batch_id"]
        with pytest.raises(FrozenInstanceError):
            session.session_id = "changed"
        runtime.cancel_session_preparation(preparation_id="fresh-prepare")
        runtime.cancel_session_preparation(preparation_id="fresh-prepare")
        assert session.session_id not in runtime._sessions
    finally:
        if runtime is not None and session is not None:
            runtime.abandon_session(session_id=session.session_id)
        host.close()


def test_fresh_session_uses_same_window_lease_as_reviewed_controller(tmp_path):
    from tests.test_live_controller_w4 import _controller

    host, connection, segment, packet, args, staged = _stage(tmp_path)
    fresh = current = reviewed = reviewed_session = None
    try:
        fresh, _, _, _ = _runtime(host, connection, segment, staged)
        current = fresh.start_session_preparation(preparation_id="fresh-lease")
        reviewed, *_ = _controller(tmp_path / "reviewed-isolated")
        with pytest.raises(RuntimeError, match="lease is already held"):
            reviewed.start_session()
        fresh.cancel_session_preparation(preparation_id="fresh-lease")
        reviewed_session = reviewed.start_session()
        second, _, _, _ = _runtime(host, connection, segment, staged)
        with pytest.raises(RuntimeError, match="lease is already held"):
            second.start_session()
    finally:
        if reviewed is not None and reviewed_session is not None:
            reviewed.abandon_session(session_id=reviewed_session.session_id)
        if fresh is not None and current is not None:
            fresh.abandon_session(session_id=current.session_id)
        host.close()


def test_first_use_cannot_fall_into_reviewed_action_or_recovery_api(tmp_path):
    host, connection, segment, packet, args, staged = _stage(tmp_path)
    runtime = session = None
    try:
        runtime, backend, claims, _ = _runtime(host, connection, segment, staged)
        session = runtime.start_session()
        payload = {"session_id": session.session_id,
                   "observation_id": session.current_observation.observation_id,
                   "action_id": "open_detail"}
        decisions = [runtime.submit_intent(payload),
            runtime.prepare_grounded_review(payload, target_process_id=9001),
            runtime.request_grounded_confirmation(payload, target_process_id=9001),
            runtime.record_confirmation_decision(confirmation_id="not-fresh", decision="approved"),
            runtime.record_grounded_confirmation_decision(confirmation_id="not-fresh", decision="approved"),
            runtime.consume_grounded_confirmation(confirmation_id="not-fresh")]
        assert all(decisions[index] == live_controller.LiveControllerDecision(
            "REJECTED", "fresh_learning_confirmation_not_available") for index in (0, 3))
        assert all(decisions[index] == live_controller.LiveControllerDecision(
            "REJECTED", "invalid_intent") for index in (1, 2))
        assert decisions[4].status == "RECOVERY_REQUIRED"
        assert decisions[4].reason_code == "grounded_confirmation_integrity_failed"
        assert decisions[5].status == "RECOVERY_REQUIRED"
        assert decisions[5].reason_code == "grounded_confirmation_integrity_failed"
        with pytest.raises(ValueError, match="fresh learning"):
            runtime.get_local_reviewed_text_parameters(session_id=session.session_id, action_id="fill_field")
        with pytest.raises(ValueError, match="fresh learning"):
            runtime.close_initial_safe_stop(session_id=session.session_id)
        assert backend.commands == []
        assert claims.find_for_observation(session_id=session.session_id,
            observation_id=session.current_observation.observation_id) is None
        assert session.session_id in runtime._sessions
    finally:
        if runtime is not None and session is not None:
            runtime.abandon_session(session_id=session.session_id)
        host.close()


def test_capture_failure_releases_the_same_preparation_lease(tmp_path):
    host, connection, segment, packet, args, staged = _stage(tmp_path)
    good = session = None
    try:
        root = host.fresh_learning.archive.project_root
        failed, backend, _, _ = _runtime(host, connection, segment, staged,
            observation_owner=_owner(root, origin=_OriginReader("https://wrong.example")))
        with pytest.raises(ValueError, match="origin"):
            failed.start_session_preparation(preparation_id="failed-capture")
        failed.cancel_session_preparation(preparation_id="failed-capture")
        assert backend.commands == [] and failed._sessions == {}
        good, _, _, _ = _runtime(host, connection, segment, staged)
        session = good.start_session()
    finally:
        if good is not None and session is not None:
            good.abandon_session(session_id=session.session_id)
        host.close()


def test_revoked_after_binding_is_rejected_before_passive_capture(tmp_path):
    host, connection, segment, packet, args, staged = _stage(tmp_path)
    try:
        root = host.fresh_learning.archive.project_root
        screenshot = _ScreenshotService(root)
        runtime, backend, _, _ = _runtime(host, connection, segment, staged,
            observation_owner=_owner(root, screenshot=screenshot))
        host._service.reviewer_call(REVIEWER, "revoke_connection", {
            "connection_id": connection["connection_id"], "idempotency_key": "revoke-runtime"})
        with pytest.raises(ValueError):
            runtime.start_session_preparation(preparation_id="revoked-binding")
        runtime.cancel_session_preparation(preparation_id="revoked-binding")
        assert screenshot.calls == [] and backend.commands == []
    finally:
        host.close()


def test_observation_owner_root_drift_is_rejected_before_capture(tmp_path):
    host, connection, segment, packet, args, staged = _stage(tmp_path)
    runtime = session = None
    try:
        root = host.fresh_learning.archive.project_root
        screenshot = _ScreenshotService(root)
        owner = _owner(root, screenshot=screenshot)
        runtime, backend, _, _ = _runtime(host, connection, segment, staged, observation_owner=owner)
        owner.project_root = tmp_path / "unrelated"
        with pytest.raises(ValueError, match="root"):
            session = runtime.start_session()
        assert screenshot.calls == [] and backend.commands == []
    finally:
        if runtime is not None and session is not None:
            runtime.abandon_session(session_id=session.session_id)
        host.close()


def test_source_revoked_during_capture_never_registers_a_session(tmp_path):
    host, connection, segment, packet, args, staged = _stage(tmp_path)
    try:
        class RevokingCapture(_ScreenshotService):
            def capture_window(self, **kwargs):
                result = super().capture_window(**kwargs)
                host._service.reviewer_call(REVIEWER, "revoke_connection", {
                    "connection_id": connection["connection_id"], "idempotency_key": "revoke-during-capture"})
                return result

        root = host.fresh_learning.archive.project_root
        runtime, backend, _, _ = _runtime(host, connection, segment, staged,
            observation_owner=_owner(root, screenshot=RevokingCapture(root)))
        with pytest.raises(ValueError, match="scope|ownership"):
            runtime.start_session_preparation(preparation_id="race-start")
        runtime.cancel_session_preparation(preparation_id="race-start")
        assert runtime._sessions == {} and backend.commands == []
        assert len(list(host.fresh_learning.archive.records_root.glob("*.json"))) == 1
    finally:
        host.close()


def test_native_process_instance_change_releases_preparation_without_claim(tmp_path):
    application = {"kind": "native", "executable_path": r"c:\fresh\app.exe"}
    initial = _owner(tmp_path / "native-initial", application=application).observe(
        target_window_handle=4242, target_process_id=9001)
    host, connection, segment, packet, args, staged = _stage(tmp_path, packet=initial)
    try:
        root = host.fresh_learning.archive.project_root
        runtime, backend, _, _ = _runtime(host, connection, segment, staged,
            observation_owner=_owner(root, application=application,
                native=_NativeReader(200.5, 200.5, 200.5)))
        with pytest.raises(ValueError, match="application or process changed"):
            runtime.start_session_preparation(preparation_id="native-instance-drift")
        runtime.cancel_session_preparation(preparation_id="native-instance-drift")
        assert runtime._sessions == {} and backend.commands == []
        assert len(list(host.fresh_learning.archive.records_root.glob("*.json"))) == 1
    finally:
        host.close()


def test_reopen_revalidates_source_but_cannot_reuse_old_session_owner(tmp_path):
    from app.desktop_review.host import DesktopReviewHost

    host, connection, segment, packet, args, staged = _stage(tmp_path)
    old = new = session = restarted = None
    try:
        old, _, _, source = _runtime(host, connection, segment, staged)
        session = old.start_session_preparation(preparation_id="old-owner")
        old.cancel_session_preparation(preparation_id="old-owner")
    finally:
        host.close()
    reopened = DesktopReviewHost(tmp_path / "inbox.json", tmp_path / "review", REVIEWER)
    try:
        new, backend, _, _ = _runtime(reopened, connection, segment, staged, source=source)
        restarted = new.start_session_preparation(preparation_id="new-owner")
        assert restarted.session_id != session.session_id
        assert restarted.source == session.source
        assert restarted.current_observation.observation_id != session.current_observation.observation_id
        with pytest.raises(ValueError, match="not owned"):
            new.cancel_session_preparation(preparation_id="old-owner")
        with pytest.raises(ValueError, match="not owned"):
            old.abandon_session(session_id=restarted.session_id)
        assert backend.commands == []
    finally:
        if new is not None and restarted is not None:
            new.cancel_session_preparation(preparation_id="new-owner")
        reopened.close()
