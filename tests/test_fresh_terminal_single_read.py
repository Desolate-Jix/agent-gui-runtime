"""终结证据每次读取完整校验一次；不跨请求缓存或重发模拟输入。"""
import json

import pytest

from app.agent.fresh_learning_action_contracts import canonical_json_bytes
from app.agent.live_controller import LiveControllerDecision
from app.agent.runtime_intent_claim_store import RuntimeIntentClaimStoreError
from app.agent.runtime_receipt_store import RuntimeReceiptStoreError
from tests.test_fresh_text_dispatch import _ready_text
from tests.test_fresh_text_visual_integration import _change_capture


def test_terminal_read_validates_consume_once_per_request(tmp_path, monkeypatch):
    with _ready_text(tmp_path) as (_, owner, runtime, input_boundary, claims, session, _, cid, _):
        _change_capture(owner, monkeypatch)
        receipt = runtime.consume_grounded_confirmation(confirmation_id=cid)
        assert not isinstance(receipt, LiveControllerDecision), receipt
        assert len(input_boundary.calls) == 1
        counts = {"consume": 0, "visual": 0}
        load_consume = claims._load_fresh_consume
        validate_visual = claims._validate_fresh_text_visual_record

        def consume(*args, **kwargs):
            counts["consume"] += 1
            return load_consume(*args, **kwargs)

        def visual(*args, **kwargs):
            counts["visual"] += 1
            return validate_visual(*args, **kwargs)

        monkeypatch.setattr(claims, "_load_fresh_consume", consume)
        monkeypatch.setattr(claims, "_validate_fresh_text_visual_record", visual)
        previous = None
        for expected in (1, 2):
            snapshot, record = claims.read_committed_terminal_evidence(
                session_id=session.session_id, observation_id=receipt.observation_id)
            assert counts == {"consume": expected, "visual": expected}
            assert snapshot.phase == "terminal" and not snapshot.recovery_required
            assert snapshot.grounded_confirmation.confirmation_id == cid
            assert record.runtime_receipt == receipt
            if previous is not None:
                assert snapshot == previous
            previous = snapshot
        assert len(input_boundary.calls) == 1


@pytest.mark.parametrize("tamper", ("consume", "dispatch", "terminal", "proof", "png", "receipt", "decision"))
def test_terminal_read_rejects_cross_request_corruption(tmp_path, monkeypatch, tamper):
    with _ready_text(tmp_path) as (_, owner, runtime, input_boundary, claims, session, _, cid, _):
        _change_capture(owner, monkeypatch)
        receipt = runtime.consume_grounded_confirmation(confirmation_id=cid)
        assert not isinstance(receipt, LiveControllerDecision), receipt
        identity = cid.split(".")[-1]
        scope = dict(session_id=session.session_id, observation_id=receipt.observation_id)
        snapshot, record = claims.read_committed_terminal_evidence(**scope)
        root = claims.root
        paths = {
            "consume": root / "grounded-consume-started" / (identity + ".json"),
            "dispatch": root / "dispatch-started" / (identity + ".json"),
            "terminal": root / "terminal" / (identity + ".json"),
            "proof": root / ("text-visual-stability-" + identity + ".json"),
            "decision": root / "grounded-decisions" / (identity + ".json"),
        }
        if tamper == "png":
            preview = snapshot.grounded_consume.fresh_preview.to_dict()
            digest = preview["capture_source"]["screenshot_sha256"]
            path = claims.project_root / "runtime_state/fresh-learning-v1/png" / (digest + ".png")
        elif tamper == "receipt":
            path = claims._receipt_store._object_path(record.content_sha256)
        else:
            path = paths[tamper]
        original = path.read_bytes()
        try:
            if tamper in {"png", "receipt"}:
                changed = b"synthetic corrupt evidence"
            else:
                value = json.loads(original)
                if tamper == "proof":
                    value["proof"]["changed_pixels"] += 1
                elif tamper == "consume":
                    value["approved_preview_sha256"] = "0" * 64
                elif tamper == "decision":
                    value["decision"] = "denied"
                else:
                    value["claim_id"] = "claim." + "0" * 64
                changed = canonical_json_bytes(value)
            path.write_bytes(changed)
            with pytest.raises((RuntimeIntentClaimStoreError, RuntimeReceiptStoreError)):
                claims.read_committed_terminal_evidence(**scope)
            assert len(input_boundary.calls) == 1
        finally:
            path.write_bytes(original)
        restored, restored_record = claims.read_committed_terminal_evidence(**scope)
        assert restored == snapshot and restored_record.content_sha256 == record.content_sha256
        assert len(input_boundary.calls) == 1
