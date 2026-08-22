from __future__ import annotations

from copy import deepcopy
import hashlib
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
from tests.test_runtime_receipt_store_w3b import (
    _blocked_verification,
    _next_observation,
    _semantic_success_receipt,
    _verification,
    _verification_failed_receipt,
)


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


def _verification_checkpoint_inputs() -> dict[str, object]:
    observation = _observation()
    selection_sha256 = "d" * 64
    current_observation = {
        "contract_version": "reviewed_workflow_current_observation_v1",
        "asset_id": observation.workflow.asset_id,
        "expected_asset_content_sha256": observation.workflow.asset_content_sha256,
        "capture_id": "capture-current",
        "screenshot_sha256": "f" * 64,
        "viewport_size": {"width": 1280, "height": 720},
        "origin": "https://nz.seek.com",
        "observed_anchor_evidence": [],
    }
    selection = {
        "contract_version": "verified_transition_selection_v1",
        "status": "selected",
        "asset_id": observation.workflow.asset_id,
        "asset_content_sha256": observation.workflow.asset_content_sha256,
        "source_workflow_sha256": observation.workflow.source_workflow_sha256,
        "reviewed_revision_hash": observation.workflow.reviewed_revision_hash,
        "transition_id": "transition.open-detail",
        "source_state_id": observation.state.state_id,
        "semantic_action": "open_detail",
        "selection_sha256": selection_sha256,
        "capture_lineage": {
            "capture_id": current_observation["capture_id"],
            "screenshot_sha256": current_observation["screenshot_sha256"],
            "viewport_size": current_observation["viewport_size"],
        },
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    grounding = {
        "contract_version": "reviewed_workflow_current_grounding_v1",
        "asset_content_sha256": observation.workflow.asset_content_sha256,
        "transition_id": "transition.open-detail",
        "source_state_id": observation.state.state_id,
        "semantic_action": "open_detail",
        "selection_sha256": selection_sha256,
        "capture_id": current_observation["capture_id"],
        "screenshot_sha256": current_observation["screenshot_sha256"],
        "viewport_size": current_observation["viewport_size"],
        "candidate_id": "candidate-open-detail",
        "click_point": {"x": 640.0, "y": 360.0},
        "artifact_is_authorization": False,
        "execute_binding_enabled": False,
    }
    gate = {
        "contract_version": "pre_click_decision_v1",
        "allowed": True,
        "asset_content_sha256": observation.workflow.asset_content_sha256,
        "transition_id": "transition.open-detail",
        "selection_sha256": selection_sha256,
        "selected_candidate_id": "candidate-open-detail",
        "selected_element_id": "job-card",
        "selected_click_point": {"x": 640.0, "y": 360.0},
        "capture_id": current_observation["capture_id"],
        "screenshot_sha256": current_observation["screenshot_sha256"],
        "viewport_size": current_observation["viewport_size"],
        "evidence_refs": ["gate:1"],
        "artifact_is_authorization": False,
    }
    return {
        "current_observation": current_observation,
        "selection": selection,
        "grounding": grounding,
        "gate": gate,
        "gate_decision_ref": "gate:1",
        "backend_receipt": _backend_for("DISPATCHED"),
        "target_process_id": 9001,
    }


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


def test_find_for_observation_returns_none_only_when_claim_is_absent(
    tmp_path: Path,
) -> None:
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    store = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
    )

    assert store.find_for_observation(
        session_id=_observation().session_id,
        observation_id=_observation().observation_id,
    ) is None

    claimed = store.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    )
    assert store.find_for_observation(
        session_id=claimed.observation.session_id,
        observation_id=claimed.observation.observation_id,
    ) == claimed


def test_persist_terminal_seals_backend_and_loads_exact_receipt_after_restart(
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
    store.mark_dispatch_started(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
    )
    receipt_payload = _receipt_payload("DISPATCHED")
    receipt_payload["intent_id"] = claim.intent.intent_id
    receipt = RuntimeResultReceiptV1.model_validate(receipt_payload)
    backend = _backend_for("DISPATCHED")

    persisted = store.persist_terminal(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
        receipt=receipt,
        backend_receipt=backend,
    )

    assert persisted == receipt
    restarted = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
    )
    assert restarted.load_terminal_receipt(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
    ) == receipt


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


def test_verification_pending_persists_exact_immutable_checkpoint_after_restart(
    tmp_path: Path,
) -> None:
    from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStore
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    first = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
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
    inputs = _verification_checkpoint_inputs()

    pending = first.mark_verification_pending(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
        **inputs,
    )

    restarted = RuntimeIntentClaimStore(
        project_root=tmp_path,
        receipt_store=RuntimeReceiptStore(project_root=tmp_path),
    )
    recovered = restarted.get_for_observation(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
    )
    assert pending.phase == recovered.phase == "verification_pending"
    checkpoint = recovered.verification_checkpoint
    assert checkpoint is not None
    assert checkpoint.claim_id == claim.claim_id
    assert checkpoint.claim_content_sha256 == claim.claim_content_sha256
    assert checkpoint.current_observation == inputs["current_observation"]
    assert checkpoint.selection == inputs["selection"]
    assert checkpoint.grounding == inputs["grounding"]
    assert checkpoint.gate == inputs["gate"]
    assert checkpoint.gate_decision_ref == "gate:1"
    assert checkpoint.backend_receipt == inputs["backend_receipt"]
    assert checkpoint.target_process_id == 9001
    assert checkpoint.artifact_is_authorization is False
    assert checkpoint.grants_action_authority is False
    mutated = checkpoint.selection
    mutated["selection_sha256"] = "f" * 64
    assert checkpoint.selection == inputs["selection"]

    marker_path = next(first.verification_pending_root.glob("*.json"))
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["store_contract_version"] == "runtime_intent_verification_pending_v2"
    assert set(marker) == {
        "store_contract_version",
        "claim_id",
        "claim_content_sha256",
        "phase",
        "current_observation",
        "selection",
        "grounding",
        "gate",
        "gate_decision_ref",
        "backend_receipt",
        "target_process_id",
        "artifact_is_authorization",
        "grants_action_authority",
        "checkpoint_sha256",
    }
    raw = marker_path.read_text(encoding="utf-8")
    assert '"artifact_is_authorization":false' in raw
    assert '"grants_action_authority":false' in raw
    assert '"authority_token"' not in raw


def test_identical_verification_checkpoint_is_idempotent_but_conflict_fails(
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
    claim = store.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    )
    store.mark_dispatch_started(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
    )
    inputs = _verification_checkpoint_inputs()
    first = store.mark_verification_pending(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
        **inputs,
    )
    assert store.mark_verification_pending(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
        **inputs,
    ) == first

    conflict = deepcopy(inputs)
    conflict["backend_receipt"] = BackendDispatchReceipt(
        receipt_ref="backend-receipt:2",
        status="dispatched",
        reason_code="none",
    )
    with pytest.raises(RuntimeIntentClaimStoreError, match="verification_pending.*conflict"):
        store.mark_verification_pending(
            session_id=claim.observation.session_id,
            observation_id=claim.observation.observation_id,
            **conflict,
        )


def test_verification_pending_cannot_return_to_dispatch_started(tmp_path: Path) -> None:
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
    store.mark_verification_pending(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
        **_verification_checkpoint_inputs(),
    )

    with pytest.raises(RuntimeIntentClaimStoreError, match="verification_pending"):
        store.mark_dispatch_started(
            session_id=claim.observation.session_id,
            observation_id=claim.observation.observation_id,
        )


def test_verification_pending_requires_dispatch_started_and_definitive_dispatch(
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
    claim = store.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    )
    inputs = _verification_checkpoint_inputs()
    with pytest.raises(RuntimeIntentClaimStoreError, match="dispatch_started"):
        store.mark_verification_pending(
            session_id=claim.observation.session_id,
            observation_id=claim.observation.observation_id,
            **inputs,
        )

    store.mark_dispatch_started(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
    )
    for backend in (
        BackendDispatchReceipt("backend-receipt:1", "not_started", "backend_failed"),
        BackendDispatchReceipt("backend-receipt:1", "indeterminate", "backend_result_lost"),
        BackendDispatchReceipt("", "dispatched", "none"),
        BackendDispatchReceipt("backend-receipt:1", "dispatched", "backend_failed"),
        {"receipt_ref": "backend-receipt:1", "status": "dispatched", "reason_code": "none"},
    ):
        invalid = dict(inputs)
        invalid["backend_receipt"] = backend
        with pytest.raises(RuntimeIntentClaimStoreError, match="backend.*receipt|dispatched"):
            store.mark_verification_pending(
                session_id=claim.observation.session_id,
                observation_id=claim.observation.observation_id,
                **invalid,
            )
    assert list(store.verification_pending_root.glob("*.json")) == []


@pytest.mark.parametrize("target_process_id", [0, -1, True])
def test_verification_pending_rejects_invalid_target_process_id(
    tmp_path: Path,
    target_process_id: object,
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
    claim = store.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    )
    store.mark_dispatch_started(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
    )
    inputs = _verification_checkpoint_inputs()
    inputs["target_process_id"] = target_process_id

    with pytest.raises(RuntimeIntentClaimStoreError, match="target_process_id|process"):
        store.mark_verification_pending(
            session_id=claim.observation.session_id,
            observation_id=claim.observation.observation_id,
            **inputs,
        )


@pytest.mark.parametrize("mutation", ["tamper", "missing", "legacy_v1"])
def test_verification_pending_rejects_pid_marker_tamper_or_legacy_v1(
    tmp_path: Path,
    mutation: str,
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
    claim = store.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    )
    store.mark_dispatch_started(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
    )
    store.mark_verification_pending(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
        **_verification_checkpoint_inputs(),
    )
    path = next(store.verification_pending_root.glob("*.json"))
    marker = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "tamper":
        marker["target_process_id"] = 9002
    else:
        marker.pop("target_process_id")
        if mutation == "legacy_v1":
            marker["store_contract_version"] = "runtime_intent_verification_pending_v1"
            payload = dict(marker)
            payload.pop("checkpoint_sha256")
            raw = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            marker["checkpoint_sha256"] = hashlib.sha256(raw).hexdigest()
    path.write_text(
        json.dumps(marker, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeIntentClaimStoreError, match="tampered|invalid"):
        store.get_for_observation(
            session_id=claim.observation.session_id,
            observation_id=claim.observation.observation_id,
        )


def test_verification_pending_rejects_c1_reusing_claim_c0_capture(
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
    claim = store.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    )
    store.mark_dispatch_started(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
    )
    inputs = _verification_checkpoint_inputs()
    c0_capture_id = claim.observation.current_capture.capture_id
    inputs["current_observation"]["capture_id"] = c0_capture_id
    inputs["selection"]["capture_lineage"]["capture_id"] = c0_capture_id
    inputs["grounding"]["capture_id"] = c0_capture_id
    inputs["gate"]["capture_id"] = c0_capture_id

    with pytest.raises(RuntimeIntentClaimStoreError, match="capture|newer|C1"):
        store.mark_verification_pending(
            session_id=claim.observation.session_id,
            observation_id=claim.observation.observation_id,
            **inputs,
        )


@pytest.mark.parametrize(
    "mutation",
    ["cross_intent", "cross_action", "malformed_selection_sha256"],
)
def test_verification_pending_rejects_selection_outside_claimed_intent(
    tmp_path: Path,
    mutation: str,
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
    claim = store.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    )
    store.mark_dispatch_started(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
    )
    inputs = _verification_checkpoint_inputs()
    if mutation == "cross_intent":
        for field in ("selection", "grounding", "gate"):
            inputs[field]["transition_id"] = "transition.other"
    elif mutation == "cross_action":
        inputs["selection"]["semantic_action"] = "close_modal"
        inputs["grounding"]["semantic_action"] = "close_modal"
    else:
        inputs["selection"]["selection_sha256"] = "not-a-sha256"
        inputs["gate"]["selection_sha256"] = "not-a-sha256"

    with pytest.raises(RuntimeIntentClaimStoreError, match="intent|action|selection"):
        store.mark_verification_pending(
            session_id=claim.observation.session_id,
            observation_id=claim.observation.observation_id,
            **inputs,
        )


def test_verification_pending_rejects_cross_claim_lineage_or_authority_smuggling(
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
    claim = store.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    )
    store.mark_dispatch_started(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
    )
    cross_claim = _verification_checkpoint_inputs()
    cross_claim["current_observation"] = deepcopy(cross_claim["current_observation"])
    cross_claim["current_observation"]["asset_id"] = "asset.other"
    with pytest.raises(RuntimeIntentClaimStoreError, match="observation|lineage"):
        store.mark_verification_pending(
            session_id=claim.observation.session_id,
            observation_id=claim.observation.observation_id,
            **cross_claim,
        )

    for field, value in (
        ("authority_token", "opaque-secret"),
        ("authorization", True),
        ("grants_action_authority", True),
    ):
        smuggled = _verification_checkpoint_inputs()
        smuggled["grounding"] = deepcopy(smuggled["grounding"])
        smuggled["grounding"][field] = value
        with pytest.raises(RuntimeIntentClaimStoreError, match="authority|authorization"):
            store.mark_verification_pending(
                session_id=claim.observation.session_id,
                observation_id=claim.observation.observation_id,
                **smuggled,
            )


def test_verification_pending_marker_tamper_or_extra_field_fails_closed(
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
    claim = store.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    )
    store.mark_dispatch_started(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
    )
    store.mark_verification_pending(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
        **_verification_checkpoint_inputs(),
    )
    path = next(store.verification_pending_root.glob("*.json"))
    marker = json.loads(path.read_text(encoding="utf-8"))
    marker["approved_to_redispatch"] = True
    path.write_text(
        json.dumps(marker, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeIntentClaimStoreError, match="tampered|invalid"):
        store.get_for_observation(
            session_id=claim.observation.session_id,
            observation_id=claim.observation.observation_id,
        )


def test_terminal_takes_precedence_and_pending_cannot_be_marked_after_terminal(
    tmp_path: Path,
) -> None:
    from app.agent.runtime_intent_claim_store import (
        RuntimeIntentClaimStore,
        RuntimeIntentClaimStoreError,
    )
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    receipt_store = RuntimeReceiptStore(project_root=tmp_path)
    store = RuntimeIntentClaimStore(project_root=tmp_path, receipt_store=receipt_store)
    claim = store.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    )
    store.mark_dispatch_started(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
    )
    inputs = _verification_checkpoint_inputs()
    store.mark_verification_pending(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
        **inputs,
    )
    receipt_ref = _store_receipt(receipt_store)
    terminal = store.terminalize(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
        receipt_ref=receipt_ref,
    )
    assert terminal.phase == "terminal"
    assert terminal.verification_checkpoint is not None
    with pytest.raises(RuntimeIntentClaimStoreError, match="terminal"):
        store.mark_verification_pending(
            session_id=claim.observation.session_id,
            observation_id=claim.observation.observation_id,
            **inputs,
        )


def test_semantic_terminal_requires_verification_pending_and_forwards_evidence(
    tmp_path: Path,
) -> None:
    from app.agent.runtime_intent_claim_store import (
        RuntimeIntentClaimStore,
        RuntimeIntentClaimStoreError,
    )
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    next_observation = _next_observation()
    verification = _verification(next_observation)
    receipt_payload = _semantic_success_receipt(
        verification,
        next_observation,
    ).model_dump(mode="json")
    receipt_payload["intent_id"] = _intent().intent_id
    receipt = RuntimeResultReceiptV1.model_validate(receipt_payload)

    without_checkpoint_root = tmp_path / "without-checkpoint"
    without_checkpoint = RuntimeIntentClaimStore(
        project_root=without_checkpoint_root,
        receipt_store=RuntimeReceiptStore(project_root=without_checkpoint_root),
    )
    first_claim = without_checkpoint.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    )
    without_checkpoint.mark_dispatch_started(
        session_id=first_claim.observation.session_id,
        observation_id=first_claim.observation.observation_id,
    )
    with pytest.raises(RuntimeIntentClaimStoreError, match="verification_pending"):
        without_checkpoint.persist_terminal(
            session_id=first_claim.observation.session_id,
            observation_id=first_claim.observation.observation_id,
            receipt=receipt,
            backend_receipt=_backend_for("DISPATCHED"),
            verification_evidence=verification,
            next_observation=next_observation,
        )

    receipt_store = RuntimeReceiptStore(project_root=tmp_path)
    store = RuntimeIntentClaimStore(project_root=tmp_path, receipt_store=receipt_store)
    claim = store.claim(
        observation=_observation(),
        intent=_intent(),
        server_binding=_binding(),
    )
    store.mark_dispatch_started(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
    )
    store.mark_verification_pending(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
        **_verification_checkpoint_inputs(),
    )
    assert store.persist_terminal(
        session_id=claim.observation.session_id,
        observation_id=claim.observation.observation_id,
        receipt=receipt,
        backend_receipt=_backend_for("DISPATCHED"),
        verification_evidence=verification,
        next_observation=next_observation,
    ) == receipt
    record = receipt_store.find_for_intent(
        session_id=receipt.session_id,
        observation_id=receipt.observation_id,
        intent_id=receipt.intent_id,
    )
    assert record is not None
    assert record.verification_evidence == verification
    assert record.next_observation == next_observation


def test_verification_failed_requires_verification_pending(tmp_path: Path) -> None:
    from app.agent.runtime_intent_claim_store import (
        RuntimeIntentClaimStore,
        RuntimeIntentClaimStoreError,
    )
    from app.agent.runtime_receipt_store import RuntimeReceiptStore

    verification = _blocked_verification("destination_mismatch")
    receipt_payload = _verification_failed_receipt(verification).model_dump(mode="json")
    receipt_payload["intent_id"] = _intent().intent_id
    receipt = RuntimeResultReceiptV1.model_validate(receipt_payload)
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
    with pytest.raises(RuntimeIntentClaimStoreError, match="verification_pending"):
        store.persist_terminal(
            session_id=claim.observation.session_id,
            observation_id=claim.observation.observation_id,
            receipt=receipt,
            backend_receipt=_backend_for("DISPATCHED"),
            verification_evidence=verification,
        )
