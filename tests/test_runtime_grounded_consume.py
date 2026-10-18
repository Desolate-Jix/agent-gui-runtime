import json
from copy import deepcopy

import pytest

from app.agent.runtime_contracts import RuntimeResultReceiptV1
from app.agent.runtime_grounded_consume import content_sha256
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStoreError
from app.agent.reviewed_workflow_replay import _selection_hash
from tests.test_agent_runtime_grounded_preview import _request, live
from tests.test_live_controller_w4 import _current_observation


def test_store_projects_grounded_consume_and_terminal_lineage(live):
    observation = live.service.start_session()
    source = live.sources[0]
    source.post_current_sequence = [
        _current_observation(
            source.asset,
            capture_id="capture-consume-fresh",
            anchors=("anchor_detail", "quick_apply"),
        ),
        _current_observation(
            source.asset,
            capture_id="capture-consume-post",
            anchors=("anchor_apply_entry",),
        ),
    ]
    pending = live.service.request_grounded_confirmation(_request(observation))
    confirmation_id = pending.grounded_confirmation.confirmation_id
    live.service.decide_grounded_confirmation(
        confirmation_id=confirmation_id,
        decision="approved",
    )

    try:
        receipt = live.service.consume_grounded_confirmation(confirmation_id=confirmation_id)
        claim = live.claims.get_for_grounded_confirmation(confirmation_id=confirmation_id)

        assert isinstance(receipt, RuntimeResultReceiptV1)
        assert claim.phase == "terminal"
        assert claim.grounded_consume is not None
        assert claim.grounded_consume.evidence_ref in receipt.evidence.trace_refs
        assert len(list(live.claims.grounded_consume_root.iterdir())) == 1
    finally:
        claim = live.claims.get_for_grounded_confirmation(confirmation_id=confirmation_id)
        if claim.phase == "grounded_confirmation_approved":
            live.service.cancel_grounded_review(session_id=observation.session_id)


def test_tampered_consume_child_is_rejected_before_terminal_receipt_replay(live):
    observation = live.service.start_session()
    source = live.sources[0]
    source.post_current_sequence = [
        _current_observation(
            source.asset,
            capture_id="capture-tamper-fresh",
            anchors=("anchor_detail", "quick_apply"),
        ),
        _current_observation(
            source.asset,
            capture_id="capture-tamper-post",
            anchors=("anchor_apply_entry",),
        ),
    ]
    pending = live.service.request_grounded_confirmation(_request(observation))
    confirmation_id = pending.grounded_confirmation.confirmation_id
    live.service.decide_grounded_confirmation(
        confirmation_id=confirmation_id, decision="approved"
    )
    receipt = live.service.consume_grounded_confirmation(confirmation_id=confirmation_id)
    assert isinstance(receipt, RuntimeResultReceiptV1)
    request_bytes = {
        path: path.read_bytes() for path in live.claims.grounded_requests_root.iterdir()
    }
    consume_path = next(live.claims.grounded_consume_root.iterdir())
    marker = json.loads(consume_path.read_text(encoding="utf-8"))
    marker["grounding"]["bbox"]["x"] += 1.0
    marker["consume_binding_sha256"] = content_sha256(
        {key: value for key, value in marker.items() if key != "consume_binding_sha256"}
    )
    consume_path.write_text(
        json.dumps(
            marker,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeIntentClaimStoreError):
        live.claims.get_for_grounded_confirmation(confirmation_id=confirmation_id)
    assert live.backends[0].attempt_count == 1
    assert request_bytes == {
        path: path.read_bytes() for path in live.claims.grounded_requests_root.iterdir()
    }


def test_rehashed_forged_grounded_proof_ref_is_rejected_on_reload(live):
    observation = live.service.start_session()
    source = live.sources[0]
    source.post_current_sequence = [
        _current_observation(
            source.asset,
            capture_id="capture-proof-fresh",
            anchors=("anchor_detail", "quick_apply"),
        ),
        _current_observation(
            source.asset,
            capture_id="capture-proof-post",
            anchors=("anchor_apply_entry",),
        ),
    ]
    pending = live.service.request_grounded_confirmation(_request(observation))
    confirmation_id = pending.grounded_confirmation.confirmation_id
    live.service.decide_grounded_confirmation(
        confirmation_id=confirmation_id, decision="approved"
    )
    receipt = live.service.consume_grounded_confirmation(confirmation_id=confirmation_id)
    assert isinstance(receipt, RuntimeResultReceiptV1)
    consume_path = next(live.claims.grounded_consume_root.iterdir())
    marker = json.loads(consume_path.read_text(encoding="utf-8"))
    marker["selection"]["human_confirmation_evidence_ref"] = (
        "grounded-confirmation-proof:" + "a" * 64
    )
    marker["selection"]["selection_sha256"] = _selection_hash(marker["selection"])
    marker["gate"]["selection_sha256"] = marker["selection"]["selection_sha256"]
    marker["consume_binding_sha256"] = content_sha256(
        {key: value for key, value in marker.items() if key != "consume_binding_sha256"}
    )
    consume_path.write_text(
        json.dumps(marker, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeIntentClaimStoreError, match="grounded consume lineage mismatch"):
        live.claims.get_for_grounded_confirmation(confirmation_id=confirmation_id)


@pytest.mark.parametrize("mutation", ["bbox", "pid"])
def test_checkpoint_publish_requires_exact_frozen_consume_bundle(
    live, monkeypatch, mutation
):
    observation = live.service.start_session()
    source = live.sources[0]
    source.post_current_sequence = [
        _current_observation(
            source.asset,
            capture_id=f"capture-{mutation}-fresh",
            anchors=("anchor_detail", "quick_apply"),
        ),
        _current_observation(
            source.asset,
            capture_id=f"capture-{mutation}-post",
            anchors=("anchor_apply_entry",),
        ),
    ]
    pending = live.service.request_grounded_confirmation(_request(observation))
    confirmation_id = pending.grounded_confirmation.confirmation_id
    live.service.decide_grounded_confirmation(
        confirmation_id=confirmation_id, decision="approved"
    )
    original = live.claims.mark_grounded_verification_pending
    captured = {}

    def publish_different_bundle(**kwargs):
        captured.update(deepcopy(kwargs))
        changed = deepcopy(kwargs)
        if mutation == "bbox":
            changed["grounding"]["bbox"]["x"] += 1.0
        else:
            changed["target_process_id"] += 1
        return original(**changed)

    monkeypatch.setattr(
        live.claims, "mark_grounded_verification_pending", publish_different_bundle
    )
    controller = live.controllers[0]
    try:
        result = live.service.consume_grounded_confirmation(
            confirmation_id=confirmation_id
        )
        assert result.status == "RECOVERY_REQUIRED"
        assert result.reason_code == "verification_checkpoint_failed"
        assert not tuple(live.claims.verification_pending_root.iterdir())
        assert live.backends[0].attempt_count == 1
    finally:
        monkeypatch.setattr(live.claims, "mark_grounded_verification_pending", original)
        if captured and not tuple(live.claims.verification_pending_root.iterdir()):
            original(**captured)
        controller.consume_grounded_confirmation(confirmation_id=confirmation_id)


def test_rehashed_checkpoint_with_different_consume_bundle_is_rejected(live):
    observation = live.service.start_session()
    source = live.sources[0]
    source.post_current_sequence = [
        _current_observation(
            source.asset,
            capture_id="capture-checkpoint-tamper-fresh",
            anchors=("anchor_detail", "quick_apply"),
        ),
        _current_observation(
            source.asset,
            capture_id="capture-checkpoint-tamper-post",
            anchors=("anchor_apply_entry",),
        ),
    ]
    pending = live.service.request_grounded_confirmation(_request(observation))
    confirmation_id = pending.grounded_confirmation.confirmation_id
    live.service.decide_grounded_confirmation(
        confirmation_id=confirmation_id, decision="approved"
    )
    receipt = live.service.consume_grounded_confirmation(confirmation_id=confirmation_id)
    assert isinstance(receipt, RuntimeResultReceiptV1)
    checkpoint_path = next(live.claims.verification_pending_root.iterdir())
    marker = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    marker["grounding"]["bbox"]["x"] += 1.0
    marker["checkpoint_sha256"] = content_sha256(
        {key: value for key, value in marker.items() if key != "checkpoint_sha256"}
    )
    checkpoint_path.write_text(
        json.dumps(marker, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )

    with pytest.raises(RuntimeIntentClaimStoreError, match="checkpoint bundle differs from consume"):
        live.claims.get_for_grounded_confirmation(confirmation_id=confirmation_id)
