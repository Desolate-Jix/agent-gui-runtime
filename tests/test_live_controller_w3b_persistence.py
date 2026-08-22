from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from threading import Event, Thread
from datetime import datetime, timedelta, timezone

import pytest

from tests.test_live_controller_w4 import (
    _Gate,
    _ObservationSource,
    _TargetResolver,
    _TrustedAssetLoader,
    _WindowVisibilityChecker,
    _asset,
    _current_observation,
    _intent,
)


class _ConfirmationObservationSource(_ObservationSource):
    def create_initial(self, **kwargs):
        from app.agent.runtime_contracts import validate_agent_observation_v1

        observation = super().create_initial(**kwargs)
        payload = observation.model_dump(mode="json")
        payload["available_actions"][0]["requires_user_confirmation"] = True
        return validate_agent_observation_v1(payload)


def _claim_store(tmp_path: Path):
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    return RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
    )


def _controller(
    tmp_path: Path,
    *,
    asset=None,
    claim_store=None,
    source=None,
    resolver=None,
    gate=None,
    backend=None,
    visibility=None,
    target_window_handle: int = 6242,
):
    from app.agent.desktop_backend import DeterministicFakeBackend
    from app.agent.live_controller import LiveController, ServerWorkflowBinding

    asset = asset or _asset()
    store = claim_store or _claim_store(tmp_path)
    requires_confirmation = any(
        transition.get("risk_policy", {}).get("requires_user_confirmation") is True
        for transition in asset.get("transitions", [])
    )
    source = source or (
        _ConfirmationObservationSource(asset)
        if requires_confirmation
        else _ObservationSource(asset)
    )
    resolver = resolver or _TargetResolver()
    gate = gate or _Gate()
    backend = backend or DeterministicFakeBackend()
    controller = LiveController(
        binding=ServerWorkflowBinding(
            workflow_id="workflow.seek.portfolio",
            asset_id=asset["asset_id"],
            application_identity_key="web:nz.seek.com",
            target_window_handle=target_window_handle,
        ),
        asset_loader=_TrustedAssetLoader(asset),
        observation_source=source,
        target_resolver=resolver,
        gate=gate,
        window_visibility_checker=visibility
        or _WindowVisibilityChecker(bound_window_handle=target_window_handle),
        backend=backend,
        grounding_policy={"minimum_confidence": 0.9, "minimum_score_margin": 0.2},
        intent_claim_store=store,
    )
    return controller, store, source, resolver, gate, backend


def test_valid_intent_is_durably_claimed_before_fresh_capture(tmp_path: Path) -> None:
    store = _claim_store(tmp_path)

    class ClaimAwareSource(_ObservationSource):
        observed_claim_phases = []

        def capture_projected(self, *, session_id, workflow, asset, target_window_handle):
            snapshot = store.find_for_observation(
                session_id=session_id,
                observation_id="observation-initial",
            )
            self.observed_claim_phases.append(
                snapshot.phase if snapshot is not None else None
            )
            return super().capture_projected(
                session_id=session_id,
                workflow=workflow,
                asset=asset,
                target_window_handle=target_window_handle,
            )

    source = ClaimAwareSource(_asset())
    controller, _, _, _, _, backend = _controller(
        tmp_path,
        claim_store=store,
        source=source,
    )
    session = controller.start_session()

    result = controller.submit_intent(_intent(session))

    assert result.outcome == "VERIFIED"
    assert source.observed_claim_phases == ["claimed", "verification_pending"]
    assert store.load_terminal_receipt(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
    ) == result
    assert backend.dispatch_count == 1
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    record = RuntimeReceiptStore(project_root=tmp_path).load_by_receipt_id(
        result.receipt_id
    )
    assert record.verification_evidence is not None
    assert record.next_observation is not None
    assert record.next_observation.observation_id == result.next_observation_id
    assert record.verification_evidence["post_capture_lineage"]["capture_id"] == (
        record.next_observation.current_capture.capture_id
    )
    assert record.verification_evidence["post_state_resolution"]["state_id"] == (
        record.next_observation.state.state_id
    )
    assert record.verification_evidence["post_state_resolution"][
        "resolution_sha256"
    ] == record.next_observation.state.resolution_sha256


def test_duplicate_and_restart_return_exact_terminal_receipt_without_dispatch(
    tmp_path: Path,
) -> None:
    first, store, _, _, _, first_backend = _controller(tmp_path)
    session = first.start_session()
    payload = _intent(session)
    original = first.submit_intent(payload)

    same_process = first.submit_intent(payload)
    restarted, _, restarted_source, _, _, restarted_backend = _controller(
        tmp_path,
        claim_store=_claim_store(tmp_path),
    )
    after_restart = restarted.submit_intent(payload)

    assert same_process == after_restart == original
    assert first_backend.dispatch_count == 1
    assert restarted_backend.dispatch_count == 0
    assert restarted_source.current_calls == 0
    assert restarted_source.projected_calls == 0


@pytest.mark.parametrize(
    "mark_dispatch,expected_reason",
    [
        (False, "observation_consumed"),
        (True, "dispatch_indeterminate"),
    ],
)
def test_pending_claim_never_retries_after_restart(
    tmp_path: Path,
    mark_dispatch: bool,
    expected_reason: str,
) -> None:
    first, store, _, _, _, _ = _controller(tmp_path)
    session = first.start_session()
    payload = _intent(session)
    store.claim(
        observation=session.current_observation,
        intent=payload,
        server_binding={
            "workflow_id": "workflow.seek.portfolio",
            "asset_id": _asset()["asset_id"],
            "application_identity_key": "web:nz.seek.com",
            "target_window_handle": 6242,
        },
    )
    if mark_dispatch:
        store.mark_dispatch_started(
            session_id=session.session_id,
            observation_id=session.current_observation.observation_id,
        )

    restarted, _, source, resolver, gate, backend = _controller(
        tmp_path,
        claim_store=_claim_store(tmp_path),
    )
    result = restarted.submit_intent(payload)

    assert (result.status, result.reason_code) == (
        "RECOVERY_REQUIRED",
        expected_reason,
    )
    assert source.current_calls == resolver.calls == gate.calls == 0
    assert backend.attempt_count == 0


def test_same_process_pending_recovery_releases_window_lease(tmp_path: Path) -> None:
    controller, store, _, _, _, _ = _controller(tmp_path)
    session = controller.start_session()
    payload = _intent(session)
    store.claim(
        observation=session.current_observation,
        intent=payload,
        server_binding={
            "workflow_id": "workflow.seek.portfolio",
            "asset_id": _asset()["asset_id"],
            "application_identity_key": "web:nz.seek.com",
            "target_window_handle": 6242,
        },
    )

    recovered = controller.submit_intent(payload)
    replacement = controller.start_session()

    assert (recovered.status, recovered.reason_code) == (
        "RECOVERY_REQUIRED",
        "observation_consumed",
    )
    assert replacement.session_id != session.session_id


def test_inflight_duplicate_never_releases_active_window_lease(tmp_path: Path) -> None:
    from app.agent.desktop_backend import DeterministicFakeBackend

    class PausingBackend:
        def __init__(self) -> None:
            self.inner = DeterministicFakeBackend()
            self.entered = Event()
            self.resume = Event()

        def dispatch(self, command, *, authority):
            self.entered.set()
            assert self.resume.wait(timeout=5)
            return self.inner.dispatch(command, authority=authority)

    backend = PausingBackend()
    controller, _, _, _, _, _ = _controller(tmp_path / "active", backend=backend)
    session = controller.start_session()
    payload = _intent(session)
    results = []
    worker = Thread(target=lambda: results.append(controller.submit_intent(payload)))
    worker.start()
    assert backend.entered.wait(timeout=5)

    duplicate = controller.submit_intent(payload)
    contender, _, _, _, _, _ = _controller(tmp_path / "contender")
    with pytest.raises(RuntimeError, match="window lease"):
        contender.start_session()

    backend.resume.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert (duplicate.status, duplicate.reason_code) == (
        "RECOVERY_REQUIRED",
        "dispatch_indeterminate",
    )
    assert results[0].outcome == "VERIFIED"


def test_claim_failure_before_commit_has_zero_side_effects_and_can_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStoreError

    controller, store, source, resolver, gate, backend = _controller(tmp_path)
    session = controller.start_session()
    original_claim = store.claim
    calls = 0

    def fail_once(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeIntentClaimStoreError("injected pre-commit failure")
        return original_claim(**kwargs)

    monkeypatch.setattr(store, "claim", fail_once)
    first = controller.submit_intent(_intent(session))
    second = controller.submit_intent(_intent(session))

    assert (first.status, first.reason_code) == (
        "RECOVERY_REQUIRED",
        "claim_persistence_failed",
    )
    assert second.outcome == "VERIFIED"
    assert source.current_calls == 0
    assert source.projected_calls == 2
    assert resolver.calls == gate.calls == 1
    assert backend.dispatch_count == 1


def test_dispatch_marker_failure_blocks_backend(tmp_path: Path, monkeypatch) -> None:
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStoreError

    controller, store, _, _, _, backend = _controller(tmp_path)
    session = controller.start_session()

    def fail_marker(**kwargs):
        raise RuntimeIntentClaimStoreError("injected marker failure")

    monkeypatch.setattr(store, "mark_dispatch_started", fail_marker)
    result = controller.submit_intent(_intent(session))

    assert (result.status, result.reason_code) == (
        "RECOVERY_REQUIRED",
        "dispatch_marker_failed",
    )
    assert backend.attempt_count == 0


def test_post_dispatch_persistence_failure_never_blindly_retries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStoreError

    controller, store, source, resolver, gate, backend = _controller(tmp_path)
    session = controller.start_session()
    payload = _intent(session)

    def fail_terminal(**kwargs):
        raise RuntimeIntentClaimStoreError("injected post-dispatch failure")

    monkeypatch.setattr(store, "persist_terminal", fail_terminal)
    first = controller.submit_intent(payload)
    second = controller.submit_intent(payload)

    assert (first.status, first.reason_code) == (
        "RECOVERY_REQUIRED",
        "receipt_persistence_failed",
    )
    assert (second.status, second.reason_code) == (
        "RECOVERY_REQUIRED",
        "receipt_persistence_failed",
    )
    checkpoint = store.find_for_observation(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
    )
    assert checkpoint is not None
    assert checkpoint.phase == "verification_pending"
    assert source.projected_calls == 3
    assert resolver.calls == gate.calls == 1
    assert backend.dispatch_count == 1


def test_conflicting_duplicate_payload_is_consumed_without_second_dispatch(
    tmp_path: Path,
) -> None:
    controller, _, _, _, _, backend = _controller(tmp_path)
    session = controller.start_session()
    payload = _intent(session)
    original = controller.submit_intent(payload)
    conflicting = dict(payload)
    conflicting["intent_id"] = "intent.conflicting"

    result = controller.submit_intent(conflicting)
    injected = dict(payload)
    injected["bbox"] = [1, 2, 3, 4]
    injected_result = controller.submit_intent(injected)

    assert original.outcome == "VERIFIED"
    assert (result.status, result.reason_code) == (
        "REJECTED",
        "observation_consumed",
    )
    assert (injected_result.status, injected_result.reason_code) == (
        "REJECTED",
        "observation_consumed",
    )
    assert backend.dispatch_count == 1


def test_backend_exception_is_persisted_as_indeterminate_without_retry(
    tmp_path: Path,
) -> None:
    class RaisingBackend:
        calls = 0

        def dispatch(self, command, *, authority):
            self.calls += 1
            raise RuntimeError("lost backend response")

    backend = RaisingBackend()
    controller, store, _, _, _, _ = _controller(tmp_path, backend=backend)
    session = controller.start_session()
    payload = _intent(session)

    result = controller.submit_intent(payload)
    duplicate = controller.submit_intent(payload)

    assert (result.outcome, result.reason_code) == (
        "INDETERMINATE",
        "backend_result_lost",
    )
    assert duplicate == result
    assert store.load_terminal_receipt(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
    ) == result
    assert backend.calls == 1


@pytest.mark.parametrize(
    "malformed",
    [
        None,
        pytest.param("invalid_pair", id="malformed-dataclass"),
        pytest.param("whitespace_ref", id="whitespace-ref"),
        pytest.param("overlong_ref", id="overlong-ref"),
        pytest.param("illegal_ref", id="illegal-ref"),
    ],
)
def test_malformed_backend_return_becomes_durable_indeterminate(
    tmp_path: Path,
    malformed,
) -> None:
    from app.agent.desktop_backend import BackendDispatchReceipt

    class MalformedBackend:
        calls = 0

        def dispatch(self, command, *, authority):
            self.calls += 1
            if malformed == "invalid_pair":
                return BackendDispatchReceipt(
                    receipt_ref="",
                    status="dispatched",
                    reason_code="backend_failed",
                )
            if malformed == "whitespace_ref":
                return BackendDispatchReceipt(
                    receipt_ref=" ",
                    status="dispatched",
                    reason_code="none",
                )
            if malformed == "overlong_ref":
                return BackendDispatchReceipt(
                    receipt_ref="a" * 257,
                    status="dispatched",
                    reason_code="none",
                )
            if malformed == "illegal_ref":
                return BackendDispatchReceipt(
                    receipt_ref="backend receipt?invalid",
                    status="dispatched",
                    reason_code="none",
                )
            return None

    backend = MalformedBackend()
    controller, _, _, _, _, _ = _controller(tmp_path, backend=backend)
    session = controller.start_session()
    payload = _intent(session)

    result = controller.submit_intent(payload)
    duplicate = controller.submit_intent(payload)
    restarted, _, _, _, _, restarted_backend = _controller(
        tmp_path,
        claim_store=_claim_store(tmp_path),
    )
    after_restart = restarted.submit_intent(payload)

    assert (result.outcome, result.reason_code) == (
        "INDETERMINATE",
        "backend_result_lost",
    )
    assert result.dispatch_status == "indeterminate"
    assert duplicate == after_restart == result
    assert backend.calls == 1
    assert restarted_backend.attempt_count == 0


@pytest.mark.parametrize(
    "stage,expected_reason",
    [
        ("capture", "current_capture_failed"),
        ("state", "state_resolution_failed"),
        ("selection", "transition_selection_failed"),
        ("resolver", "target_resolution_failed"),
        ("gate", "gate_evaluation_failed"),
        ("grounding", "grounding_validation_failed"),
        ("visibility", "visibility_check_failed"),
    ],
)
def test_pre_dispatch_stage_exception_requires_recovery_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    expected_reason: str,
) -> None:
    import app.agent.live_controller as live_controller_module

    asset = _asset()

    class RaisingSource(_ObservationSource):
        def capture_projected(self, **kwargs):
            if stage == "capture":
                raise RuntimeError("capture failed")
            return super().capture_projected(**kwargs)

    class RaisingResolver(_TargetResolver):
        def resolve(self, **kwargs):
            if stage == "resolver":
                raise RuntimeError("resolver failed")
            return super().resolve(**kwargs)

    class RaisingGate(_Gate):
        def evaluate(self, **kwargs):
            if stage == "gate":
                raise RuntimeError("gate failed")
            return super().evaluate(**kwargs)

    class RaisingVisibility(_WindowVisibilityChecker):
        def check(self, **kwargs):
            if stage == "visibility":
                raise RuntimeError("visibility failed")
            return super().check(**kwargs)

    if stage == "state":
        original_resolve = live_controller_module.resolve_current_state
        resolve_calls = 0

        def fail_c1_state_resolution(*args, **kwargs):
            nonlocal resolve_calls
            resolve_calls += 1
            if resolve_calls == 2:
                raise RuntimeError("state failed")
            return original_resolve(*args, **kwargs)

        monkeypatch.setattr(
            live_controller_module,
            "resolve_current_state",
            fail_c1_state_resolution,
        )
    if stage == "selection":
        monkeypatch.setattr(
            live_controller_module,
            "select_verified_transition",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("selection failed")
            ),
        )
    if stage == "grounding":
        monkeypatch.setattr(
            live_controller_module,
            "validate_current_grounding",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                RuntimeError("grounding failed")
            ),
        )

    controller, _, _, _, _, backend = _controller(
        tmp_path,
        source=RaisingSource(asset),
        resolver=RaisingResolver(),
        gate=RaisingGate(),
        visibility=RaisingVisibility(bound_window_handle=6242),
    )
    session = controller.start_session()
    payload = _intent(session)

    result = controller.submit_intent(payload)
    duplicate = controller.submit_intent(payload)

    assert (result.status, result.reason_code) == (
        "RECOVERY_REQUIRED",
        expected_reason,
    )
    assert (duplicate.status, duplicate.reason_code) == (
        "RECOVERY_REQUIRED",
        "observation_consumed",
    )
    assert backend.attempt_count == 0


def test_human_review_transition_returns_durable_confirmation_request(tmp_path: Path) -> None:
    asset = _asset()
    transition = next(
        item for item in asset["transitions"] if item["transition_id"] == "open_detail"
    )
    transition["risk_policy"]["requires_user_confirmation"] = True
    transition["risk_policy"]["automatic_execution_allowed"] = False
    source = _ConfirmationObservationSource(asset)
    controller, store, _, _, _, backend = _controller(
        tmp_path,
        asset=asset,
        source=source,
    )
    session = controller.start_session()

    result = controller.submit_intent(_intent(session))

    assert (result.status, result.reason_code) == (
        "CONFIRMATION_REQUIRED",
        "human_confirmation_required",
    )
    assert result.confirmation_id
    pending = store.get_for_observation(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
    )
    assert pending.phase == "confirmation_pending"
    assert pending.confirmation is not None
    assert pending.confirmation.confirmation_id == result.confirmation_id
    assert backend.attempt_count == 0


def test_approved_confirmation_resumes_after_restart_with_fresh_c1_and_one_dispatch(
    tmp_path: Path,
) -> None:
    asset = _asset()
    transition = next(
        item for item in asset["transitions"] if item["transition_id"] == "open_detail"
    )
    transition["risk_policy"]["requires_user_confirmation"] = True
    transition["risk_policy"]["automatic_execution_allowed"] = False
    first, _, _, _, _, first_backend = _controller(tmp_path, asset=asset)
    session = first.start_session()
    payload = _intent(session)
    pending = first.submit_intent(payload)

    approved = first.record_confirmation_decision(
        confirmation_id=pending.confirmation_id,
        decision="approved",
    )
    assert (approved.status, approved.reason_code, approved.confirmation_id) == (
        "APPROVED",
        "confirmation_approved",
        pending.confirmation_id,
    )

    restarted, store, source, resolver, gate, restarted_backend = _controller(
        tmp_path,
        asset=asset,
        claim_store=_claim_store(tmp_path),
    )
    result = restarted.submit_intent(payload)
    duplicate = restarted.submit_intent(payload)

    assert result.outcome == "VERIFIED"
    assert duplicate == result
    assert first_backend.attempt_count == 0
    assert restarted_backend.dispatch_count == 1
    assert source.projected_calls == 2
    assert resolver.calls == gate.calls == 1
    terminal = store.get_for_observation(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
    )
    assert terminal.phase == "terminal"
    assert terminal.confirmation is not None
    assert terminal.confirmation.evidence_ref in result.evidence.trace_refs
    assert terminal.verification_checkpoint is not None
    assert (
        terminal.verification_checkpoint.selection["human_confirmation_evidence_ref"]
        == terminal.confirmation.evidence_ref
    )
    same_decision_after_terminal = restarted.record_confirmation_decision(
        confirmation_id=pending.confirmation_id,
        decision="approved",
    )
    assert same_decision_after_terminal == approved


def test_denied_and_expired_confirmation_are_durable_zero_dispatch_decisions(
    tmp_path: Path,
) -> None:
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    asset = _asset()
    transition = next(
        item for item in asset["transitions"] if item["transition_id"] == "open_detail"
    )
    transition["risk_policy"]["requires_user_confirmation"] = True
    transition["risk_policy"]["automatic_execution_allowed"] = False

    denied, _, _, _, _, denied_backend = _controller(tmp_path / "denied", asset=asset)
    denied_session = denied.start_session()
    denied_payload = _intent(denied_session)
    denied_pending = denied.submit_intent(denied_payload)
    denied_decision = denied.record_confirmation_decision(
        confirmation_id=denied_pending.confirmation_id,
        decision="denied",
    )
    denied_retry = denied.submit_intent(denied_payload)
    assert denied_decision == denied_retry == type(denied_decision)(
        "REJECTED", "confirmation_denied", denied_pending.confirmation_id
    )
    assert denied_backend.attempt_count == 0

    now = [datetime(2026, 8, 22, 1, 2, 3, tzinfo=timezone.utc)]
    expired_root = tmp_path / "expired"
    expired_store = RuntimeIntentClaimStore(
        project_root=expired_root,
        receipt_store=RuntimeReceiptStore(project_root=expired_root),
        clock=lambda: now[0],
    )
    expired, _, source, resolver, gate, expired_backend = _controller(
        expired_root,
        asset=asset,
        claim_store=expired_store,
    )
    expired_session = expired.start_session()
    expired_payload = _intent(expired_session)
    expired_pending = expired.submit_intent(expired_payload)
    expired.record_confirmation_decision(
        confirmation_id=expired_pending.confirmation_id,
        decision="approved",
    )
    calls_before_retry = source.projected_calls
    now[0] += timedelta(minutes=6)
    expired_retry = expired.submit_intent(expired_payload)
    exact_duplicate = expired.submit_intent(expired_payload)
    assert expired_retry == exact_duplicate == type(expired_retry)(
        "REJECTED", "confirmation_expired", expired_pending.confirmation_id
    )
    assert source.projected_calls == calls_before_retry
    assert resolver.calls == gate.calls == expired_backend.attempt_count == 0

    late_root = tmp_path / "late-approval"
    now[0] = datetime(2026, 8, 22, 2, 0, 0, tzinfo=timezone.utc)
    late_store = RuntimeIntentClaimStore(
        project_root=late_root,
        receipt_store=RuntimeReceiptStore(project_root=late_root),
        clock=lambda: now[0],
    )
    late, _, _, _, _, late_backend = _controller(
        late_root, asset=asset, claim_store=late_store
    )
    late_session = late.start_session()
    late_pending = late.submit_intent(_intent(late_session))
    now[0] += timedelta(minutes=6)
    late_decision = late.record_confirmation_decision(
        confirmation_id=late_pending.confirmation_id,
        decision="approved",
    )
    assert late_decision == type(late_decision)(
        "REJECTED", "confirmation_expired", late_pending.confirmation_id
    )
    assert late_backend.attempt_count == 0


def test_stale_asset_closes_approval_and_never_dispatches_after_restore(
    tmp_path: Path,
) -> None:
    asset = _asset()
    transition = next(
        item for item in asset["transitions"] if item["transition_id"] == "open_detail"
    )
    transition["risk_policy"]["requires_user_confirmation"] = True
    transition["risk_policy"]["automatic_execution_allowed"] = False
    first, _, _, _, _, _ = _controller(tmp_path, asset=asset)
    session = first.start_session()
    payload = _intent(session)
    pending = first.submit_intent(payload)
    first.record_confirmation_decision(
        confirmation_id=pending.confirmation_id,
        decision="approved",
    )

    stale_asset = deepcopy(asset)
    stale_asset["application"]["display_name"] = "Changed reviewed application"
    stale, _, stale_source, _, _, stale_backend = _controller(
        tmp_path,
        asset=stale_asset,
        claim_store=_claim_store(tmp_path),
    )
    stale_result = stale.submit_intent(payload)
    assert stale_result == type(stale_result)(
        "REJECTED", "confirmation_stale", pending.confirmation_id
    )
    assert stale_source.projected_calls == stale_backend.attempt_count == 0

    restored, store, restored_source, _, _, restored_backend = _controller(
        tmp_path,
        asset=asset,
        claim_store=_claim_store(tmp_path),
    )
    duplicate = restored.submit_intent(payload)
    assert duplicate == stale_result
    assert restored_source.projected_calls == restored_backend.attempt_count == 0
    closed = store.get_for_observation(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
    )
    assert closed.phase == "confirmation_closed"
    assert closed.confirmation.closed_reason_code == "confirmation_stale"


def test_stale_pid_after_approval_closes_before_grounding_or_dispatch(
    tmp_path: Path,
) -> None:
    asset = _asset()
    transition = next(
        item for item in asset["transitions"] if item["transition_id"] == "open_detail"
    )
    transition["risk_policy"]["requires_user_confirmation"] = True
    transition["risk_policy"]["automatic_execution_allowed"] = False
    first, _, _, _, _, _ = _controller(tmp_path, asset=asset)
    session = first.start_session()
    payload = _intent(session)
    pending = first.submit_intent(payload)
    first.record_confirmation_decision(
        confirmation_id=pending.confirmation_id,
        decision="approved",
    )

    source = _ConfirmationObservationSource(asset, target_process_id=9002)
    restarted, store, _, resolver, gate, backend = _controller(
        tmp_path,
        asset=asset,
        claim_store=_claim_store(tmp_path),
        source=source,
    )
    result = restarted.submit_intent(payload)
    duplicate = restarted.submit_intent(payload)
    assert result == duplicate == type(result)(
        "REJECTED", "confirmation_stale", pending.confirmation_id
    )
    assert source.projected_calls == 1
    assert resolver.calls == gate.calls == backend.attempt_count == 0
    closed = store.get_for_observation(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
    )
    assert closed.phase == "confirmation_closed"


def test_confirmation_decision_writer_must_match_exact_controller_binding(
    tmp_path: Path,
) -> None:
    asset = _asset()
    transition = next(
        item for item in asset["transitions"] if item["transition_id"] == "open_detail"
    )
    transition["risk_policy"]["requires_user_confirmation"] = True
    transition["risk_policy"]["automatic_execution_allowed"] = False
    owner, store, _, _, _, owner_backend = _controller(tmp_path, asset=asset)
    session = owner.start_session()
    pending = owner.submit_intent(_intent(session))

    wrong, _, _, _, _, wrong_backend = _controller(
        tmp_path,
        asset=asset,
        claim_store=_claim_store(tmp_path),
        target_window_handle=7000,
    )
    rejected = wrong.record_confirmation_decision(
        confirmation_id=pending.confirmation_id,
        decision="approved",
    )
    assert rejected == type(rejected)(
        "REJECTED", "confirmation_binding_mismatch", pending.confirmation_id
    )
    persisted = store.get_for_observation(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
    )
    assert persisted.phase == "confirmation_pending"
    assert owner_backend.attempt_count == wrong_backend.attempt_count == 0


@pytest.mark.parametrize(
    "case,expected",
    [
        ("safe_stop", ("SAFE_STOP", "safe_stop_boundary")),
        ("stale", ("BLOCKED", "stale_candidate")),
        ("state_unresolved", ("BLOCKED", "target_unresolved")),
    ],
)
def test_valid_early_paths_return_durable_typed_receipts(
    tmp_path: Path,
    case: str,
    expected: tuple[str, str],
) -> None:
    asset = _asset()
    current = None
    if case == "stale":
        current = _current_observation(asset, capture_id="capture-initial")
    elif case == "state_unresolved":
        current = _current_observation(asset, anchors=())
    source = _ObservationSource(asset, current=current)
    controller, store, _, _, _, backend = _controller(tmp_path, source=source)
    session = controller.start_session()
    payload = _intent(session)
    if case == "safe_stop":
        payload["intent_id"] = "intent.safe-stop"
        payload["action_id"] = "runtime.safe_stop"

    result = controller.submit_intent(payload)

    assert (result.outcome, result.reason_code) == expected
    assert store.load_terminal_receipt(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
    ) == result
    assert backend.attempt_count == 0
