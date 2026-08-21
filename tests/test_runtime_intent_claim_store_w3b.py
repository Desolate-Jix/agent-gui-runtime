from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from threading import Barrier, Thread

import pytest

from app.agent.desktop_backend import BackendDispatchReceipt
from app.agent.runtime_contracts import (
    RuntimeResultReceiptV1,
    validate_agent_intent_v1,
    validate_agent_observation_v1,
)
from tests.test_agent_runtime_contracts_v1 import (
    _intent_payload,
    _observation_payload,
)
from tests.test_runtime_receipt_store_w3b import _receipt_payload


def _observation():
    return validate_agent_observation_v1(_observation_payload())


def _intent():
    observation = _observation()
    return validate_agent_intent_v1(
        _intent_payload(),
        observation=observation,
    )


def _binding(**changes) -> dict[str, object]:
    value: dict[str, object] = {
        "workflow_id": "workflow.seek.portfolio",
        "asset_id": "asset.seek.portfolio",
        "application_identity_key": "web:nz.seek.com",
        "target_window_handle": 7001,
    }
    value.update(changes)
    return value


def _backend_for(outcome: str) -> BackendDispatchReceipt | None:
    if outcome == "BLOCKED":
        return None
    return BackendDispatchReceipt(
        receipt_ref="backend-receipt:1",
        status="dispatched",
        reason_code="none",
    )


def _store_receipt(receipt_store, outcome: str = "DISPATCHED") -> dict[str, str]:
    payload = _receipt_payload(outcome)
    payload["intent_id"] = _intent().intent_id
    return receipt_store.put(
        RuntimeResultReceiptV1.model_validate(payload),
        backend_receipt=_backend_for(outcome),
    )


def test_claim_persists_exact_validated_contracts_without_action_authority(
    tmp_path: Path,
) -> None:
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    store = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
    )
    snapshot = store.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    )

    assert snapshot.phase == "claimed"
    assert snapshot.observation == _observation()
    assert snapshot.intent == _intent()
    assert snapshot.server_binding.workflow_id == "workflow.seek.portfolio"
    assert snapshot.recovery_required is True
    assert snapshot.grants_action_authority is False
    assert snapshot.artifact_is_authorization is False
    raw = next(store.claims_root.glob("*.json")).read_text(encoding="utf-8")
    for forbidden in ('"bbox"', '"click_point"', '"gate_decision_ref"', '"authority"'):
        assert forbidden not in raw
    assert '"observation_sha256"' in raw
    assert '"intent_sha256"' in raw
    assert '"binding_sha256"' in raw


def test_claim_reloads_exact_phase_after_restart(tmp_path: Path) -> None:
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    receipt_store = RuntimeReceiptStore(project_root=tmp_path)
    first = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=receipt_store,
    )
    claimed = first.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    )
    started = first.mark_dispatch_started(
        session_id=claimed.observation.session_id,
        observation_id=claimed.observation.observation_id,
    )

    restarted = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
    )
    recovered = restarted.get_for_observation(
        session_id=claimed.observation.session_id,
        observation_id=claimed.observation.observation_id,
    )

    assert recovered.phase == started.phase == "dispatch_started"
    assert recovered.claim_content_sha256 == claimed.claim_content_sha256
    assert recovered.recovery_required is True
    assert recovered.terminal_receipt_ref is None


def test_claim_store_rejects_receipt_store_from_another_project_root(
    tmp_path: Path,
) -> None:
    from app.agent.runtime_intent_claim_store import (
        RuntimeIntentClaimStore,
        RuntimeIntentClaimStoreError,
    )
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    with pytest.raises(RuntimeIntentClaimStoreError, match="project root"):
        RuntimeIntentClaimStore(
            project_root=tmp_path / "claims-project",
            receipt_store=RuntimeReceiptStore(project_root=tmp_path / "other-project"),
        )


def test_identical_claim_is_idempotent_but_same_observation_conflict_fails(
    tmp_path: Path,
) -> None:
    from app.agent.runtime_intent_claim_store import (
        RuntimeIntentClaimStore,
        RuntimeIntentClaimStoreError,
    )
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    store = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
    )
    first = store.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    )
    assert store.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    ) == first

    with pytest.raises(RuntimeIntentClaimStoreError, match="identity conflict"):
        store.claim(
            observation=_observation(),
            intent=_intent(),
            server_binding=_binding(target_window_handle=7002),
        )


@pytest.mark.parametrize(
    "binding,match",
    [
        ({**_binding(), "extra": True}, "strict"),
        (_binding(workflow_id="workflow.wrong"), "workflow"),
        (_binding(asset_id="asset.wrong"), "asset"),
        (_binding(application_identity_key="web:example.com"), "application"),
        (_binding(target_window_handle=0), "window"),
    ],
)
def test_claim_rejects_invalid_or_cross_context_server_binding(
    tmp_path: Path,
    binding: dict[str, object],
    match: str,
) -> None:
    from app.agent.runtime_intent_claim_store import (
        RuntimeIntentClaimStore,
        RuntimeIntentClaimStoreError,
    )
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    with pytest.raises(RuntimeIntentClaimStoreError, match=match):
        RuntimeIntentClaimStore(
            project_root=tmp_path,
            receipt_store=RuntimeReceiptStore(project_root=tmp_path),
        ).claim(
            observation=_observation(),
            intent=_intent(),
            server_binding=binding,
        )


def test_claim_reload_rejects_payload_hash_tampering(tmp_path: Path) -> None:
    from app.agent.runtime_intent_claim_store import (
        RuntimeIntentClaimStore,
        RuntimeIntentClaimStoreError,
    )
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    store = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
    )
    store.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    )
    path = next(store.claims_root.glob("*.json"))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["server_binding"]["target_window_handle"] = 8008
    path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeIntentClaimStoreError, match="hash|tamper"):
        store.get_for_observation(
            session_id=_observation().session_id,
            observation_id=_observation().observation_id,
        )


def test_dispatch_started_and_terminal_transitions_are_idempotent(
    tmp_path: Path,
) -> None:
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    receipt_store = RuntimeReceiptStore(project_root=tmp_path)
    store = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=receipt_store,
    )
    claim = store.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    )
    started = store.mark_dispatch_started(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
    )
    assert store.mark_dispatch_started(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
    ) == started
    receipt_ref = _store_receipt(receipt_store)
    terminal = store.terminalize(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
        receipt_ref=receipt_ref,
    )
    assert store.terminalize(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
        receipt_ref=receipt_ref,
    ) == terminal
    assert terminal.phase == "terminal"
    assert terminal.recovery_required is False
    assert terminal.terminal_receipt_ref == receipt_ref
    assert terminal.grants_action_authority is False

    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStoreError

    with pytest.raises(RuntimeIntentClaimStoreError, match="terminal"):
        store.mark_dispatch_started(
            session_id=claim.observation.session_id,
            observation_id=claim.observation.observation_id,
        )


def test_dispatch_phase_marker_tampering_fails_closed(tmp_path: Path) -> None:
    from app.agent.runtime_intent_claim_store import (
        RuntimeIntentClaimStore,
        RuntimeIntentClaimStoreError,
    )
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    store = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
    )
    claim = store.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    )
    store.mark_dispatch_started(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
    )
    marker_path = next(store.dispatch_started_root.glob("*.json"))
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["claim_content_sha256"] = "f" * 64
    marker_path.write_text(
        json.dumps(
            marker,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeIntentClaimStoreError, match="tampered"):
        store.get_for_observation(
            session_id=claim.observation.session_id,
            observation_id=claim.observation.observation_id,
        )


def test_attempt_zero_receipt_can_terminalize_directly_from_claimed(
    tmp_path: Path,
) -> None:
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    receipt_store = RuntimeReceiptStore(project_root=tmp_path)
    store = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=receipt_store,
    )
    claim = store.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    )
    receipt_ref = _store_receipt(receipt_store, "BLOCKED")

    terminal = store.terminalize(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
        receipt_ref=receipt_ref,
    )

    assert terminal.phase == "terminal"
    assert terminal.terminal_receipt_ref == receipt_ref


def test_attempt_one_requires_dispatch_started_and_attempt_zero_rejects_it(
    tmp_path: Path,
) -> None:
    from app.agent.runtime_intent_claim_store import (
        RuntimeIntentClaimStore,
        RuntimeIntentClaimStoreError,
    )
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    receipt_store = RuntimeReceiptStore(project_root=tmp_path)
    store = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=receipt_store,
    )
    claim = store.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    )
    dispatched_ref = _store_receipt(receipt_store)
    with pytest.raises(RuntimeIntentClaimStoreError, match="dispatch_started"):
        store.terminalize(
            session_id=claim.observation.session_id,
            observation_id=claim.observation.observation_id,
            receipt_ref=dispatched_ref,
        )

    second_root = tmp_path / "attempt-zero-after-start"
    second_receipts = RuntimeReceiptStore(project_root=second_root)
    second_store = RuntimeIntentClaimStore(
        project_root=second_root,
        receipt_store=second_receipts,
    )
    second_claim = second_store.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    )
    second_store.mark_dispatch_started(
        session_id=second_claim.observation.session_id,
        observation_id=second_claim.observation.observation_id,
    )
    blocked_ref = _store_receipt(second_receipts, "BLOCKED")
    with pytest.raises(RuntimeIntentClaimStoreError, match="attempt_count|claimed"):
        second_store.terminalize(
            session_id=second_claim.observation.session_id,
            observation_id=second_claim.observation.observation_id,
            receipt_ref=blocked_ref,
        )


def test_terminal_requires_precommitted_authoritative_receipt(tmp_path: Path) -> None:
    from app.agent.runtime_intent_claim_store import (
        RuntimeIntentClaimStore,
        RuntimeIntentClaimStoreError,
    )
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    store = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
    )
    claim = store.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    )
    store.mark_dispatch_started(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
    )

    with pytest.raises(RuntimeIntentClaimStoreError, match="receipt"):
        store.terminalize(
            session_id=claim.observation.session_id,
            observation_id=claim.observation.observation_id,
            receipt_ref={
                "receipt_id": "receipt:missing",
                "content_sha256": "f" * 64,
            },
        )


def test_terminalize_rejects_corrupt_dispatch_marker_without_terminal_publish(
    tmp_path: Path,
) -> None:
    from app.agent.runtime_intent_claim_store import (
        RuntimeIntentClaimStore,
        RuntimeIntentClaimStoreError,
    )
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    receipt_store = RuntimeReceiptStore(project_root=tmp_path)
    store = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=receipt_store,
    )
    claim = store.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    )
    store.mark_dispatch_started(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
    )
    marker_path = next(store.dispatch_started_root.glob("*.json"))
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["claim_content_sha256"] = "f" * 64
    marker_path.write_text(
        json.dumps(
            marker,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    receipt_ref = _store_receipt(receipt_store)

    with pytest.raises(RuntimeIntentClaimStoreError, match="dispatch_started|tampered"):
        store.terminalize(
            session_id=claim.observation.session_id,
            observation_id=claim.observation.observation_id,
            receipt_ref=receipt_ref,
        )

    assert list(store.terminal_root.glob("*.json")) == []


def test_terminal_rejects_receipt_from_other_claim_context(tmp_path: Path) -> None:
    from app.agent.runtime_intent_claim_store import (
        RuntimeIntentClaimStore,
        RuntimeIntentClaimStoreError,
    )
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    receipt_store = RuntimeReceiptStore(project_root=tmp_path)
    store = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=receipt_store,
    )
    claim = store.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    )
    store.mark_dispatch_started(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
    )
    payload = _receipt_payload()
    payload["receipt_id"] = "receipt:other-context"
    payload["session_id"] = "session-other"
    payload["observation_id"] = "observation-other"
    payload["intent_id"] = "intent.other"
    other_ref = receipt_store.put(
        RuntimeResultReceiptV1.model_validate(payload),
        backend_receipt=_backend_for("DISPATCHED"),
    )

    with pytest.raises(RuntimeIntentClaimStoreError, match="lineage|context"):
        store.terminalize(
            session_id=claim.observation.session_id,
            observation_id=claim.observation.observation_id,
            receipt_ref=other_ref,
        )


def test_restart_repairs_missing_terminal_marker_from_authoritative_receipt(
    tmp_path: Path,
) -> None:
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    receipt_store = RuntimeReceiptStore(project_root=tmp_path)
    first = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=receipt_store,
    )
    claim = first.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    )
    first.mark_dispatch_started(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
    )
    receipt_ref = _store_receipt(receipt_store)
    assert list(first.terminal_root.glob("*.json")) == []

    restarted = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
    )
    recovered = restarted.get_for_observation(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
    )

    assert recovered.phase == "terminal"
    assert recovered.terminal_receipt_ref == receipt_ref
    assert len(list(restarted.terminal_root.glob("*.json"))) == 1


def test_concurrent_conflicting_claim_has_exactly_one_winner(tmp_path: Path) -> None:
    from app.agent.runtime_intent_claim_store import (
        RuntimeIntentClaimStore,
        RuntimeIntentClaimStoreError,
    )
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    store = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
    )
    barrier = Barrier(2)
    results = []
    failures: list[BaseException] = []

    def create(binding: dict[str, object]) -> None:
        try:
            barrier.wait()
            results.append(
                store.claim(
                    observation=_observation(),
                    intent=_intent(),
                    server_binding=binding,
                )
            )
        except BaseException as exc:
            failures.append(exc)

    threads = [
        Thread(target=create, args=(_binding(target_window_handle=handle),))
        for handle in (7001, 7002)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(results) == len(failures) == 1
    assert isinstance(failures[0], RuntimeIntentClaimStoreError)
    assert "identity conflict" in str(failures[0])
