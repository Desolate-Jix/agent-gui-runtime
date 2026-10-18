from dataclasses import replace

import pytest

from app.agent.desktop_backend import DeterministicFakeBackend
from app.agent.live_controller import LiveController
from app.agent.runtime_contracts import RuntimeResultReceiptV1
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore, RuntimeIntentClaimStoreError
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from app.api.agent_runtime import AgentRuntimeCallsiteError, LocalAgentRuntimeCallsite
from tests.test_agent_runtime_grounded_preview import _request, live
from tests.test_live_controller_w4 import _current_observation


@pytest.fixture(autouse=True)
def _release_test_processes(live):
    yield
    for controller in live.controllers:
        for session in list(controller._sessions.values()) + list(controller._grounded_recovery_sessions.values()):
            controller._release_window_lease(session.window_lease)
        controller._sessions.clear()
        controller._grounded_recovery_sessions.clear()
        controller._grounded_publications.clear()


def _pending(live, *, approve=True):
    observation = live.service.start_session()
    claim = live.service.request_grounded_confirmation(_request(observation))
    cid = claim.grounded_confirmation.confirmation_id
    if approve:
        live.service.decide_grounded_confirmation(confirmation_id=cid, decision="approved")
    return cid


def _checkpoint(live, monkeypatch, *, fail_at="persist_grounded_terminal"):
    cid = _pending(live)
    source = live.sources[0]
    source.post_current_sequence = [
        _current_observation(source.asset, capture_id="recovery-fresh", anchors=("anchor_detail", "quick_apply")),
        _current_observation(source.asset, capture_id="recovery-post", anchors=("anchor_apply_entry",)),
    ]
    original = getattr(live.claims, fail_at)

    def fail(**kwargs):
        raise RuntimeIntentClaimStoreError("synthetic crash prefix")

    monkeypatch.setattr(live.claims, fail_at, fail)
    result = live.service.consume_grounded_confirmation(confirmation_id=cid)
    assert result.status == "RECOVERY_REQUIRED"
    monkeypatch.setattr(live.claims, fail_at, original)
    # 模拟进程离开后 OS lease 不再被旧测试对象持有，不修改持久事实。
    controller = live.controllers[0]
    for session in controller._sessions.values():
        controller._release_window_lease(session.window_lease)
    controller._sessions.clear()
    controller._grounded_publications.clear()
    return cid


def _reopen(live, tmp_path, *, selection=None, factory=None):
    claims = RuntimeIntentClaimStore(project_root=tmp_path, receipt_store=RuntimeReceiptStore(project_root=tmp_path))
    built = []
    original = live.controllers[0]

    def build(binding):
        backend = DeterministicFakeBackend()
        controller = LiveController(
            binding=binding, asset_loader=live.assets, observation_source=live.sources[0],
            target_resolver=original._target_resolver, gate=original._gate,
            window_visibility_checker=original._window_visibility_checker,
            backend=backend, intent_claim_store=claims, grounding_policy=original._grounding_policy,
        )
        built.append((controller, backend))
        live.controllers.append(controller)
        return controller

    runtime = LocalAgentRuntimeCallsite(
        project_root=tmp_path, asset_store=live.assets, claim_store=claims, window_manager=live.windows,
        selection=selection or live.service._selection, controller_factory=factory or build,
    )
    return runtime, claims, built


def test_new_callsite_checkpoint_only_rechecks_never_redispatches(live, tmp_path, monkeypatch):
    cid = _checkpoint(live, monkeypatch)
    runtime, claims, built = _reopen(live, tmp_path)
    assert claims.get_for_grounded_confirmation(confirmation_id=cid).phase == "verification_pending"
    assert [item.grounded_confirmation.confirmation_id for item in claims.list_grounded_claims()] == [cid]
    result = runtime.recover_grounded_confirmation(confirmation_id=cid)
    assert isinstance(result, RuntimeResultReceiptV1)
    assert len(built) == 1
    assert built[0][1].attempt_count == 0
    assert live.backends[0].attempt_count == 1
    assert not built[0][0]._grounded_recovery_sessions
    assert runtime.recover_grounded_confirmation(confirmation_id=cid) == result
    assert len(built) == 1


@pytest.mark.parametrize("approve", [False, True])
def test_restart_does_not_recover_pending_approval(live, tmp_path, approve):
    cid = _pending(live, approve=approve)
    runtime, claims, built = _reopen(live, tmp_path)
    before = claims.get_for_grounded_confirmation(confirmation_id=cid).phase
    result = runtime.recover_grounded_confirmation(confirmation_id=cid)
    assert result.status == "RECOVERY_REQUIRED"
    assert result.reason_code == "grounded_recovery_not_allowed"
    assert claims.get_for_grounded_confirmation(confirmation_id=cid).phase == before
    assert not built
    assert live.backends[0].attempt_count == 0


@pytest.mark.parametrize("fail_at,phase,attempts", [
    ("mark_grounded_dispatch_started", "grounded_confirmation_consume_started", 0),
    ("mark_grounded_verification_pending", "dispatch_started", 1),
])
def test_indeterminate_crash_prefix_cannot_restart(live, tmp_path, monkeypatch, fail_at, phase, attempts):
    cid = _checkpoint(live, monkeypatch, fail_at=fail_at)
    runtime, claims, built = _reopen(live, tmp_path)
    assert claims.get_for_grounded_confirmation(confirmation_id=cid).phase == phase
    assert [item.grounded_confirmation.confirmation_id for item in claims.list_grounded_claims()] == [cid]
    result = runtime.recover_grounded_confirmation(confirmation_id=cid)
    assert result.status == "RECOVERY_REQUIRED"
    assert result.reason_code in {"dispatch_indeterminate", "grounded_consume_indeterminate"}
    assert not built
    assert live.backends[0].attempt_count == attempts
    assert claims.get_for_grounded_confirmation(confirmation_id=cid).phase == phase


@pytest.mark.parametrize("changes", [{"target_process_id": 9302}, {"target_window_handle": 88402}, {"asset_content_sha256": "f" * 64}])
def test_recovery_rejects_foreign_selection_before_factory(live, tmp_path, monkeypatch, changes):
    cid = _checkpoint(live, monkeypatch)
    runtime, _, built = _reopen(live, tmp_path, selection=replace(live.service._selection, **changes))
    with pytest.raises(AgentRuntimeCallsiteError):
        runtime.recover_grounded_confirmation(confirmation_id=cid)
    assert not built


def test_recovery_cannot_replace_current_live_owner(live):
    cid = _pending(live)
    with pytest.raises(AgentRuntimeCallsiteError):
        live.service.recover_grounded_confirmation(confirmation_id=cid)
    assert live.service._controller is live.controllers[0]
    assert live.backends[0].attempt_count == 0


def test_terminal_history_needs_no_window_or_factory(live, tmp_path, monkeypatch):
    cid = _checkpoint(live, monkeypatch)
    runtime, _, _ = _reopen(live, tmp_path)
    receipt = runtime.recover_grounded_confirmation(confirmation_id=cid)
    restarted, _, built = _reopen(live, tmp_path)
    assert [item.phase for item in restarted._claim_store.list_grounded_claims()] == ["terminal"]
    live.windows.bound = None
    assert restarted.recover_grounded_confirmation(confirmation_id=cid) == receipt
    assert not built


def test_failed_recovery_factory_is_not_repeated_or_replaced_by_start(live, tmp_path, monkeypatch):
    cid = _checkpoint(live, monkeypatch)
    attempts = []

    def fail(binding):
        attempts.append(binding)
        raise RuntimeError("synthetic factory outcome unknown")

    runtime, _, _ = _reopen(live, tmp_path, factory=fail)
    for _ in range(2):
        with pytest.raises(AgentRuntimeCallsiteError):
            runtime.recover_grounded_confirmation(confirmation_id=cid)
    with pytest.raises(AgentRuntimeCallsiteError):
        runtime.start_session()
    assert len(attempts) == 1


def test_recovery_cleanup_failure_keeps_controller_and_retries_only_cleanup(live, tmp_path, monkeypatch):
    cid = _checkpoint(live, monkeypatch)
    runtime, _, built = _reopen(live, tmp_path)
    build = runtime._controller_factory
    calls = []

    def factory(binding):
        controller = build(binding)
        release = controller._release_window_lease

        def fail_once(lease):
            calls.append(lease)
            if len(calls) == 1:
                raise RuntimeError("synthetic release failure")
            release(lease)

        monkeypatch.setattr(controller, "_release_window_lease", fail_once)
        return controller

    runtime._controller_factory = factory
    first = runtime.recover_grounded_confirmation(confirmation_id=cid)
    assert first.reason_code == "grounded_confirmation_cleanup_required"
    captured = live.sources[0].projected_calls
    with pytest.raises(AgentRuntimeCallsiteError):
        runtime.start_session()
    second = runtime.recover_grounded_confirmation(confirmation_id=cid)
    assert isinstance(second, RuntimeResultReceiptV1)
    assert len(built) == 1 and len(calls) == 2
    assert live.sources[0].projected_calls == captured
    assert built[0][1].attempt_count == 0
