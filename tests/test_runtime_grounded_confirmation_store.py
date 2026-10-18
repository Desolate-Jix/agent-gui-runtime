from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from threading import Barrier, Thread

import pytest

from app.agent.grounded_action_preview import GroundedActionPreview
from app.agent.runtime_contracts import (
    RuntimeResultReceiptV1,
    validate_agent_intent_v1,
    validate_agent_observation_v1,
)
from app.agent.runtime_intent_claim_store import (
    RuntimeIntentClaimStore,
    RuntimeIntentClaimStoreError,
)
from app.agent.runtime_receipt_store import RuntimeReceiptStore
from tests.test_live_controller_grounded_preview import _review_controller
from tests.test_live_controller_w4 import _intent
from tests.test_reviewed_workflow_asset_v2 import _asset
from tests.test_runtime_receipt_store_w3b import _receipt_payload


class _Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 7, 1, 2, 3, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value


class _InitialRiskConsistentSource:
    def __init__(self, inner) -> None:
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def create_initial(self, **kwargs):
        result = self._inner.create_initial(**kwargs)
        payload = result.model_dump(mode="json")
        action = next(
            item
            for item in payload["available_actions"]
            if item["action_id"] == "open_detail"
        )
        action["requires_user_confirmation"] = True
        action["risk_level"] = "medium"
        return validate_agent_observation_v1(payload)


def _canonical(value: dict) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _rehash(value: dict, field: str) -> None:
    body = {key: item for key, item in value.items() if key != field}
    value[field] = hashlib.sha256(_canonical(body)).hexdigest()


def _rebind_preview_action(
    preview: GroundedActionPreview,
    *,
    action_id: str | None = None,
    requires_confirmation: bool | None = None,
) -> GroundedActionPreview:
    value = preview.to_dict()
    action = next(
        item
        for item in value["current_observation"]["available_actions"]
        if item["action_id"] == value["review_selection"]["transition_id"]
    )
    if action_id is not None:
        action["action_id"] = action_id
        value["review_selection"]["transition_id"] = action_id
        value["grounding_preview"]["transition_id"] = action_id
    if requires_confirmation is not None:
        action["requires_user_confirmation"] = requires_confirmation
        action["risk_level"] = "medium" if requires_confirmation else "low"
        value["review_selection"]["requires_user_confirmation"] = requires_confirmation
    from app.agent.reviewed_workflow_replay import _review_selection_hash

    selection_hash = _review_selection_hash(value["review_selection"])
    value["review_selection"]["review_selection_sha256"] = selection_hash
    value["review_selection"]["selection_sha256"] = selection_hash
    value["grounding_preview"]["review_selection_sha256"] = selection_hash
    value["grounding_preview"]["gate_selection_sha256"] = selection_hash
    _rehash(value["grounding_preview"], "preview_sha256")
    _rehash(value, "content_sha256")
    return GroundedActionPreview.from_dict(value)


def _prepared_claim(
    tmp_path: Path,
    *,
    clock: _Clock | None = None,
    requires_confirmation: bool = False,
):
    handle = 10000 + int(hashlib.sha256(str(tmp_path).encode()).hexdigest()[:5], 16)
    asset = _asset()
    asset["transitions"][0]["risk_policy"]["requires_user_confirmation"] = (
        requires_confirmation
    )
    if requires_confirmation:
        asset["transitions"][0]["risk_policy"]["automatic_execution_allowed"] = False
    controller, _source, _resolver, _gate, backend = _review_controller(
        tmp_path,
        target_window_handle=handle,
        asset_override=asset,
    )
    if requires_confirmation:
        controller._observation_source = _InitialRiskConsistentSource(
            controller._observation_source
        )
    session = controller.start_session()
    preview = controller.prepare_grounded_review(
        _intent(session),
        target_process_id=9001,
    )
    assert isinstance(preview, GroundedActionPreview)
    intent = validate_agent_intent_v1(
        _intent(session),
        observation=session.current_observation,
    )
    store = controller._intent_claim_store
    if clock is not None:
        store._clock = clock
    claim = store.claim(
        observation=session.current_observation,
        intent=intent,
        server_binding={
            "workflow_id": controller._binding.workflow_id,
            "asset_id": controller._binding.asset_id,
            "application_identity_key": controller._binding.application_identity_key,
            "target_window_handle": controller._binding.target_window_handle,
        },
    )
    assert claim.phase == "claimed"
    assert backend.attempt_count == 0
    return controller, store, session, preview, backend


@pytest.mark.parametrize("requires_confirmation", [False, True])
def test_grounded_request_persists_actual_preview_and_reopens_without_authority(
    tmp_path: Path,
    requires_confirmation: bool,
) -> None:
    clock = _Clock()
    controller, store, session, preview, backend = _prepared_claim(
        tmp_path,
        clock=clock,
        requires_confirmation=requires_confirmation,
    )

    pending = store.mark_grounded_confirmation_pending(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
        preview=preview,
    )
    again = store.mark_grounded_confirmation_pending(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
        preview=preview,
    )

    assert pending.phase == "grounded_confirmation_pending"
    assert pending.grounded_confirmation is not None
    grounded = pending.grounded_confirmation
    assert grounded.confirmation_id.startswith("grounded-confirmation.")
    assert grounded.preview.to_dict() == preview.to_dict()
    assert grounded.requested_at == "2026-09-07T01:02:03Z"
    assert grounded.expires_at == "2026-09-07T01:07:03Z"
    assert grounded.owner_is_current is True
    assert grounded.decision is None
    assert grounded.grants_action_authority is False
    assert grounded.artifact_is_authorization is False
    assert again == pending
    assert backend.attempt_count == 0
    assert not any(store.dispatch_started_root.iterdir())
    assert not any(store.verification_pending_root.iterdir())
    assert not any(store.terminal_root.iterdir())
    assert not any(store.confirmation_requests_root.iterdir())

    request_bytes = next(store.grounded_requests_root.iterdir()).read_bytes()
    restarted = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
        clock=clock,
    )
    recovered = restarted.get_for_grounded_confirmation(
        confirmation_id=grounded.confirmation_id
    )
    assert recovered.grounded_confirmation is not None
    assert recovered.grounded_confirmation.owner_is_current is False
    assert recovered.grounded_confirmation.preview.to_dict() == preview.to_dict()
    assert next(restarted.grounded_requests_root.iterdir()).read_bytes() == request_bytes
    assert backend.attempt_count == 0
    del controller


def test_grounded_decision_close_and_restart_guards(tmp_path: Path) -> None:
    clock = _Clock()
    _controller, store, session, preview, backend = _prepared_claim(tmp_path, clock=clock)
    pending = store.mark_grounded_confirmation_pending(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
        preview=preview,
    )
    confirmation_id = pending.grounded_confirmation.confirmation_id

    approved = store.record_grounded_confirmation_decision(
        confirmation_id=confirmation_id,
        decision="approved",
    )
    assert approved.phase == "grounded_confirmation_approved"
    assert approved.grounded_confirmation.decision == "approved"
    approved_decision_sha = approved.grounded_confirmation.decision_content_sha256
    decision_bytes = next(store.grounded_decisions_root.iterdir()).read_bytes()
    assert (
        store.record_grounded_confirmation_decision(
            confirmation_id=confirmation_id,
            decision="approved",
        )
        == approved
    )
    with pytest.raises(RuntimeIntentClaimStoreError, match="conflict"):
        store.record_grounded_confirmation_decision(
            confirmation_id=confirmation_id,
            decision="denied",
        )

    restarted = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
        clock=clock,
    )
    restarted_result = restarted.record_grounded_confirmation_decision(
        confirmation_id=confirmation_id,
        decision="approved",
    )
    assert restarted_result.phase == "grounded_confirmation_closed"
    assert restarted_result.grounded_confirmation.closed_reason_code == (
        "grounded_confirmation_restarted"
    )
    assert restarted_result.grounded_confirmation.decision == "approved"
    assert restarted_result.grounded_confirmation.decision_content_sha256 == approved_decision_sha
    assert next(restarted.grounded_decisions_root.iterdir()).read_bytes() == decision_bytes
    assert (
        restarted.record_grounded_confirmation_decision(
            confirmation_id=confirmation_id,
            decision="approved",
        )
        == restarted_result
    )
    with pytest.raises(RuntimeIntentClaimStoreError):
        restarted.mark_dispatch_started(
            session_id=session.session_id,
            observation_id=session.current_observation.observation_id,
        )
    assert backend.attempt_count == 0


def test_cross_owner_denial_and_expired_same_denial_are_idempotent(tmp_path: Path) -> None:
    clock = _Clock()
    _controller, store, session, preview, _backend = _prepared_claim(tmp_path, clock=clock)
    pending = store.mark_grounded_confirmation_pending(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
        preview=preview,
    )
    restarted = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
        clock=clock,
    )
    denied = restarted.record_grounded_confirmation_decision(
        confirmation_id=pending.grounded_confirmation.confirmation_id,
        decision="denied",
    )
    assert denied.phase == "grounded_confirmation_denied"
    assert denied.grounded_confirmation.owner_is_current is False
    decision_sha = denied.grounded_confirmation.decision_content_sha256
    clock.value += timedelta(seconds=301)
    repeated = store.record_grounded_confirmation_decision(
        confirmation_id=pending.grounded_confirmation.confirmation_id,
        decision="denied",
    )
    assert repeated.phase == "grounded_confirmation_denied"
    assert repeated.grounded_confirmation.decision_content_sha256 == decision_sha


def test_grounded_expiry_and_explicit_close_require_server_facts(tmp_path: Path) -> None:
    clock = _Clock()
    _controller, store, session, preview, _backend = _prepared_claim(tmp_path, clock=clock)
    pending = store.mark_grounded_confirmation_pending(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
        preview=preview,
    )
    confirmation_id = pending.grounded_confirmation.confirmation_id
    with pytest.raises(RuntimeIntentClaimStoreError, match="expired"):
        store.close_grounded_confirmation(
            confirmation_id=confirmation_id,
            reason_code="grounded_confirmation_expired",
        )
    with pytest.raises(RuntimeIntentClaimStoreError, match="invalid"):
        store.close_grounded_confirmation(
            confirmation_id=confirmation_id,
            reason_code="invented",
        )
    clock.value += timedelta(seconds=300)
    closed = store.close_grounded_confirmation(
        confirmation_id=confirmation_id,
        reason_code="grounded_confirmation_expired",
    )
    assert closed.phase == "grounded_confirmation_closed"
    assert closed.grounded_confirmation.closed_reason_code == "grounded_confirmation_expired"
    with pytest.raises(RuntimeIntentClaimStoreError):
        store.record_grounded_confirmation_decision(
            confirmation_id=confirmation_id,
            decision="approved",
        )


def test_grounded_mixed_and_orphan_markers_fail_before_receipt_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller, store, session, preview, _backend = _prepared_claim(tmp_path)
    pending = store.mark_grounded_confirmation_pending(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
        preview=preview,
    )
    called = False

    def forbidden(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("receipt lookup must not run")

    monkeypatch.setattr(store, "_find_receipt", forbidden)
    identity = pending.claim_id.removeprefix("claim.")
    store._publish_bytes(
        store._confirmation_request_path(identity),
        b"{}",
    )
    with pytest.raises(RuntimeIntentClaimStoreError, match="mixed"):
        store.get_for_observation(
            session_id=session.session_id,
            observation_id=session.current_observation.observation_id,
        )
    assert called is False


def test_orphan_grounded_marker_fails_before_receipt_lookup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller, store, session, _preview, _backend = _prepared_claim(tmp_path)
    identity = store._identity_hash(
        session.session_id,
        session.current_observation.observation_id,
    )
    store._publish_bytes(store._grounded_decision_path(identity), b"{}")
    called = False

    def forbidden(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("receipt lookup must not run")

    monkeypatch.setattr(store, "_find_receipt", forbidden)
    with pytest.raises(RuntimeIntentClaimStoreError, match="orphan"):
        store.get_for_observation(
            session_id=session.session_id,
            observation_id=session.current_observation.observation_id,
        )
    assert called is False


def test_grounded_loader_rejects_nested_tamper_even_with_recomputed_parent_hash(
    tmp_path: Path,
) -> None:
    _controller, store, session, preview, _backend = _prepared_claim(tmp_path)
    pending = store.mark_grounded_confirmation_pending(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
        preview=preview,
    )
    request_path = next(store.grounded_requests_root.iterdir())
    record = json.loads(request_path.read_text(encoding="utf-8"))
    record["preview"]["grounding_preview"]["bbox"]["x"] += 1
    _rehash(record, "request_binding_sha256")
    request_path.write_bytes(_canonical(record))

    with pytest.raises(RuntimeIntentClaimStoreError, match="tampered"):
        store.get_for_grounded_confirmation(
            confirmation_id=pending.grounded_confirmation.confirmation_id
        )


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(extra="forbidden"),
        lambda value: value.pop("intent_id"),
        lambda value: value.update(owner_instance_id="owner.not-hex"),
        lambda value: value.update(expires_at="2026-09-07T01:07:04Z"),
        lambda value: value.update(claim_content_sha256="0" * 64),
    ],
)
def test_grounded_request_strict_loader_rejects_rehashed_tamper(
    tmp_path: Path,
    mutate,
) -> None:
    _controller, store, session, preview, _backend = _prepared_claim(tmp_path)
    pending = store.mark_grounded_confirmation_pending(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
        preview=preview,
    )
    request_path = next(store.grounded_requests_root.iterdir())
    record = json.loads(request_path.read_text(encoding="utf-8"))
    mutate(record)
    _rehash(record, "request_binding_sha256")
    request_path.write_bytes(_canonical(record))
    with pytest.raises(RuntimeIntentClaimStoreError):
        store.get_for_grounded_confirmation(
            confirmation_id=pending.grounded_confirmation.confirmation_id
        )


def test_grounded_request_retry_keeps_first_bytes_and_ttl_across_store_instances(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    _controller, store, session, preview, _backend = _prepared_claim(tmp_path, clock=clock)
    first = store.mark_grounded_confirmation_pending(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
        preview=preview,
    )
    original = next(store.grounded_requests_root.iterdir()).read_bytes()
    clock.value += timedelta(seconds=120)
    restarted = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
        clock=clock,
    )
    second = restarted.mark_grounded_confirmation_pending(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
        preview=preview,
    )
    assert second.grounded_confirmation.confirmation_id == (
        first.grounded_confirmation.confirmation_id
    )
    assert second.grounded_confirmation.requested_at == first.grounded_confirmation.requested_at
    assert second.grounded_confirmation.expires_at == first.grounded_confirmation.expires_at
    assert next(restarted.grounded_requests_root.iterdir()).read_bytes() == original


def test_grounded_request_post_publish_failure_retries_same_fact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller, store, session, preview, _backend = _prepared_claim(tmp_path)
    original_publish = store._publish_bytes
    crashed = False

    def crash_after_publish(target: Path, contents: bytes) -> bool:
        nonlocal crashed
        result = original_publish(target, contents)
        if target.parent == store.grounded_requests_root and not crashed:
            crashed = True
            raise RuntimeIntentClaimStoreError("injected post-publish failure")
        return result

    monkeypatch.setattr(store, "_publish_bytes", crash_after_publish)
    with pytest.raises(RuntimeIntentClaimStoreError, match="post-publish"):
        store.mark_grounded_confirmation_pending(
            session_id=session.session_id,
            observation_id=session.current_observation.observation_id,
            preview=preview,
        )
    persisted = next(store.grounded_requests_root.iterdir()).read_bytes()
    recovered = store.mark_grounded_confirmation_pending(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
        preview=preview,
    )
    assert recovered.phase == "grounded_confirmation_pending"
    assert next(store.grounded_requests_root.iterdir()).read_bytes() == persisted


@pytest.mark.parametrize(
    "changes",
    [
        {"action_id": "other-transition"},
        {"requires_confirmation": True},
    ],
)
def test_grounded_request_rejects_self_consistent_preview_for_wrong_base_action(
    tmp_path: Path,
    changes: dict,
) -> None:
    _controller, store, session, preview, _backend = _prepared_claim(tmp_path)
    forged = _rebind_preview_action(preview, **changes)
    # DTO 本身完全合法；拒绝来自 immutable base claim action 交叉绑定。
    assert GroundedActionPreview.from_dict(forged.to_dict()) == forged
    with pytest.raises(RuntimeIntentClaimStoreError, match="base claim"):
        store.mark_grounded_confirmation_pending(
            session_id=session.session_id,
            observation_id=session.current_observation.observation_id,
            preview=forged,
        )
    assert not any(store.grounded_requests_root.iterdir())


def test_grounded_request_pre_publish_failure_leaves_base_claim_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller, store, session, preview, _backend = _prepared_claim(tmp_path)
    original_publish = store._publish_bytes

    def fail_before_publish(target: Path, contents: bytes) -> bool:
        if target.parent == store.grounded_requests_root:
            raise RuntimeIntentClaimStoreError("injected pre-publish failure")
        return original_publish(target, contents)

    monkeypatch.setattr(store, "_publish_bytes", fail_before_publish)
    with pytest.raises(RuntimeIntentClaimStoreError, match="pre-publish"):
        store.mark_grounded_confirmation_pending(
            session_id=session.session_id,
            observation_id=session.current_observation.observation_id,
            preview=preview,
        )
    assert not any(store.grounded_requests_root.iterdir())
    current = store.get_for_observation(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
    )
    assert current.phase == "claimed"


def test_every_legacy_execution_entry_rejects_grounded_before_receipt_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _controller, store, session, preview, _backend = _prepared_claim(tmp_path)
    store.mark_grounded_confirmation_pending(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
        preview=preview,
    )
    receipt_calls = 0

    def forbidden(*_args, **_kwargs):
        nonlocal receipt_calls
        receipt_calls += 1
        raise AssertionError("receipt access must not run")

    monkeypatch.setattr(store, "_find_receipt", forbidden)
    monkeypatch.setattr(store, "_resolve_receipt", forbidden)
    monkeypatch.setattr(store._receipt_store, "put", forbidden)
    common = {
        "session_id": session.session_id,
        "observation_id": session.current_observation.observation_id,
    }
    operations = [
        lambda: store.mark_confirmation_pending(
            **common,
            current_observation={},
            state_resolution={},
            transition_id="x",
            semantic_action="x",
            target_process_id=1,
        ),
        lambda: store.mark_dispatch_started(**common),
        lambda: store.mark_verification_pending(
            **common,
            current_observation={},
            selection={},
            grounding={},
            gate={},
            gate_decision_ref="x",
            backend_receipt=None,
            target_process_id=1,
        ),
        lambda: store.terminalize(**common, receipt_ref={}),
        lambda: store.persist_terminal(**common, receipt=None),
    ]
    for operation in operations:
        with pytest.raises(RuntimeIntentClaimStoreError, match="grounded confirmation"):
            operation()
    assert receipt_calls == 0


def test_clock_rewind_rejects_decision_and_close_before_immutable_publish(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    _controller, store, session, preview, _backend = _prepared_claim(tmp_path, clock=clock)
    pending = store.mark_grounded_confirmation_pending(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
        preview=preview,
    )
    confirmation_id = pending.grounded_confirmation.confirmation_id
    clock.value -= timedelta(seconds=1)
    with pytest.raises(RuntimeIntentClaimStoreError, match="time"):
        store.record_grounded_confirmation_decision(
            confirmation_id=confirmation_id,
            decision="approved",
        )
    assert not any(store.grounded_decisions_root.iterdir())
    for reason in (
        "grounded_confirmation_cancelled",
        "grounded_confirmation_stale",
    ):
        with pytest.raises(RuntimeIntentClaimStoreError, match="time"):
            store.close_grounded_confirmation(
                confirmation_id=confirmation_id,
                reason_code=reason,
            )
        assert not any(store.grounded_closed_root.iterdir())
    clock.value += timedelta(seconds=1)
    approved = store.record_grounded_confirmation_decision(
        confirmation_id=confirmation_id,
        decision="approved",
    )
    assert approved.phase == "grounded_confirmation_approved"


def test_clock_rewind_before_decision_time_rejects_close_then_recovers(
    tmp_path: Path,
) -> None:
    clock = _Clock()
    _controller, store, session, preview, _backend = _prepared_claim(tmp_path, clock=clock)
    pending = store.mark_grounded_confirmation_pending(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
        preview=preview,
    )
    confirmation_id = pending.grounded_confirmation.confirmation_id
    clock.value += timedelta(seconds=10)
    store.record_grounded_confirmation_decision(
        confirmation_id=confirmation_id,
        decision="approved",
    )
    clock.value -= timedelta(seconds=5)
    with pytest.raises(RuntimeIntentClaimStoreError, match="time"):
        store.close_grounded_confirmation(
            confirmation_id=confirmation_id,
            reason_code="grounded_confirmation_cancelled",
        )
    assert not any(store.grounded_closed_root.iterdir())
    clock.value += timedelta(seconds=6)
    closed = store.close_grounded_confirmation(
        confirmation_id=confirmation_id,
        reason_code="grounded_confirmation_cancelled",
    )
    assert closed.phase == "grounded_confirmation_closed"


def test_clock_rewind_rejects_restart_close_before_publish(tmp_path: Path) -> None:
    clock = _Clock()
    _controller, store, session, preview, _backend = _prepared_claim(tmp_path, clock=clock)
    pending = store.mark_grounded_confirmation_pending(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
        preview=preview,
    )
    confirmation_id = pending.grounded_confirmation.confirmation_id
    clock.value -= timedelta(seconds=1)
    restarted = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
        clock=clock,
    )
    with pytest.raises(RuntimeIntentClaimStoreError, match="time"):
        restarted.record_grounded_confirmation_decision(
            confirmation_id=confirmation_id,
            decision="approved",
        )
    assert not any(store.grounded_closed_root.iterdir())
    clock.value += timedelta(seconds=1)
    closed = restarted.record_grounded_confirmation_decision(
        confirmation_id=confirmation_id,
        decision="approved",
    )
    assert closed.grounded_confirmation.closed_reason_code == (
        "grounded_confirmation_restarted"
    )


def test_committed_same_intent_receipt_conflicts_before_grounded_read_or_write(
    tmp_path: Path,
) -> None:
    _controller, store, session, preview, _backend = _prepared_claim(tmp_path)
    pending = store.mark_grounded_confirmation_pending(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
        preview=preview,
    )
    request_bytes = next(store.grounded_requests_root.iterdir()).read_bytes()
    payload = _receipt_payload("BLOCKED")
    payload.update(
        receipt_id="receipt:grounded-conflict",
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
        intent_id=pending.intent.intent_id,
        workflow=pending.observation.workflow.model_dump(mode="json"),
    )
    initial_action = next(
        action
        for action in pending.observation.available_actions
        if action.action_id == pending.intent.action_id
    )
    payload["action"] = {
        "action_id": initial_action.action_id,
        "semantic_action": initial_action.semantic_action,
    }
    payload["evidence"]["state_resolution_ref"] = pending.observation.state_resolution_ref
    receipt = RuntimeResultReceiptV1.model_validate(payload)
    store._receipt_store.put(receipt)

    operations = [
        lambda: store.get_for_observation(
            session_id=session.session_id,
            observation_id=session.current_observation.observation_id,
        ),
        lambda: store.mark_grounded_confirmation_pending(
            session_id=session.session_id,
            observation_id=session.current_observation.observation_id,
            preview=preview,
        ),
        lambda: store.record_grounded_confirmation_decision(
            confirmation_id=pending.grounded_confirmation.confirmation_id,
            decision="approved",
        ),
        lambda: store.close_grounded_confirmation(
            confirmation_id=pending.grounded_confirmation.confirmation_id,
            reason_code="grounded_confirmation_cancelled",
        ),
    ]
    for operation in operations:
        with pytest.raises(RuntimeIntentClaimStoreError, match="receipt conflict"):
            operation()
    assert next(store.grounded_requests_root.iterdir()).read_bytes() == request_bytes
    assert not any(store.grounded_decisions_root.iterdir())
    assert not any(store.grounded_closed_root.iterdir())
    assert not any(store.terminal_root.iterdir())


def test_concurrent_opposite_grounded_decisions_commit_exactly_one(tmp_path: Path) -> None:
    _controller, store, session, preview, _backend = _prepared_claim(tmp_path)
    pending = store.mark_grounded_confirmation_pending(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
        preview=preview,
    )
    confirmation_id = pending.grounded_confirmation.confirmation_id
    barrier = Barrier(2)
    results: list[str] = []

    def worker(decision: str) -> None:
        barrier.wait()
        try:
            result = store.record_grounded_confirmation_decision(
                confirmation_id=confirmation_id,
                decision=decision,
            )
            results.append(result.grounded_confirmation.decision)
        except RuntimeIntentClaimStoreError:
            results.append("conflict")

    threads = [Thread(target=worker, args=(value,)) for value in ("approved", "denied")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert sorted(results).count("conflict") == 1
    assert len([value for value in results if value in {"approved", "denied"}]) == 1


@pytest.mark.parametrize(
    "record_kind,mutation",
    [
        ("decision", "request_sha"),
        ("decision", "claim_id"),
        ("decision", "claim_sha"),
        ("decision", "extra"),
        ("decision", "missing"),
        ("decision", "bool_flag"),
        ("decision", "time"),
        ("closed", "request_sha"),
        ("closed", "claim_id"),
        ("closed", "claim_sha"),
        ("closed", "decision_sha"),
        ("closed", "extra"),
        ("closed", "missing"),
        ("closed", "bool_flag"),
        ("closed", "time"),
    ],
)
def test_grounded_decision_and_closed_children_reject_rehashed_lineage_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    record_kind: str,
    mutation: str,
) -> None:
    clock = _Clock()
    _controller, store, session, preview, _backend = _prepared_claim(tmp_path, clock=clock)
    pending = store.mark_grounded_confirmation_pending(
        session_id=session.session_id,
        observation_id=session.current_observation.observation_id,
        preview=preview,
    )
    confirmation_id = pending.grounded_confirmation.confirmation_id
    store.record_grounded_confirmation_decision(
        confirmation_id=confirmation_id,
        decision="approved",
    )
    if record_kind == "closed":
        store.close_grounded_confirmation(
            confirmation_id=confirmation_id,
            reason_code="grounded_confirmation_cancelled",
        )
    claim_path = next(store.claims_root.iterdir())
    request_path = next(store.grounded_requests_root.iterdir())
    decision_path = next(store.grounded_decisions_root.iterdir())
    child_path = (
        decision_path
        if record_kind == "decision"
        else next(store.grounded_closed_root.iterdir())
    )
    original_claim = claim_path.read_bytes()
    original_request = request_path.read_bytes()
    original_decision = decision_path.read_bytes()
    child = json.loads(child_path.read_text(encoding="utf-8"))
    if mutation == "request_sha":
        child["request_content_sha256"] = "0" * 64
    elif mutation == "claim_id":
        child["claim_id"] = f"claim.{'0' * 64}"
    elif mutation == "claim_sha":
        child["claim_content_sha256"] = "0" * 64
    elif mutation == "decision_sha":
        child["decision_content_sha256"] = "0" * 64
    elif mutation == "extra":
        child["extra"] = "forbidden"
    elif mutation == "missing":
        child.pop("decision" if record_kind == "decision" else "reason_code")
    elif mutation == "bool_flag":
        child["artifact_is_authorization"] = 0
    elif mutation == "time":
        child["decided_at" if record_kind == "decision" else "closed_at"] = (
            "2026-09-07T01:02:03+00:00"
        )
    else:
        raise AssertionError(f"unknown mutation: {mutation}")
    binding_field = (
        "decision_binding_sha256"
        if record_kind == "decision"
        else "closed_binding_sha256"
    )
    _rehash(child, binding_field)
    corrupted_child = _canonical(child)
    child_path.write_bytes(corrupted_child)
    receipt_lookup = False

    def forbidden(*_args, **_kwargs):
        nonlocal receipt_lookup
        receipt_lookup = True
        raise AssertionError("receipt lookup must not run")

    monkeypatch.setattr(store, "_find_receipt", forbidden)
    with pytest.raises(RuntimeIntentClaimStoreError):
        store.get_for_observation(
            session_id=session.session_id,
            observation_id=session.current_observation.observation_id,
        )
    assert receipt_lookup is False
    assert claim_path.read_bytes() == original_claim
    assert request_path.read_bytes() == original_request
    if record_kind == "closed":
        assert decision_path.read_bytes() == original_decision
    assert child_path.read_bytes() == corrupted_child


def test_grounded_confirmation_apis_reject_legacy_confirmation_id_family(
    tmp_path: Path,
) -> None:
    _controller, store, _session, _preview, _backend = _prepared_claim(tmp_path)
    wrong_id = f"confirmation.{'0' * 64}"
    operations = [
        lambda: store.get_for_grounded_confirmation(confirmation_id=wrong_id),
        lambda: store.record_grounded_confirmation_decision(
            confirmation_id=wrong_id,
            decision="approved",
        ),
        lambda: store.close_grounded_confirmation(
            confirmation_id=wrong_id,
            reason_code="grounded_confirmation_cancelled",
        ),
    ]
    for operation in operations:
        with pytest.raises(RuntimeIntentClaimStoreError, match="identity is invalid"):
            operation()
    assert not any(store.grounded_requests_root.iterdir())
    assert not any(store.grounded_decisions_root.iterdir())
    assert not any(store.grounded_closed_root.iterdir())
